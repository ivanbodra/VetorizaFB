"""Field-sheet tokens and layout. No neighbouring depths or reference XYZ used."""
import re
import cv2
import numpy as np
from .core import Digit, Sounding, check_cancel, normalize_trailing_dot


def mask(rgb, config):
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    background=cv2.morphologyEx(gray,cv2.MORPH_CLOSE,np.ones((51,51),np.uint8))
    flat=cv2.divide(gray,np.maximum(background,1),scale=255)
    local=cv2.createCLAHE(2.,(8,8)).apply(flat)
    return np.uint8(local < config.threshold)*255


def token(d):
    t=(d.selected_text if d.selected_text is not None else d.raw_text).strip()
    return t if re.fullmatch(r'[0-9]{1,3}',t) else None


def recognize(rgb,boxes,engine,batch_size=64,pad=3,*,progress=None,cancel=None,**kwargs):
    digits=[]
    for start in range(0,len(boxes),batch_size):
        check_cancel(cancel)
        chunk=boxes[start:start+batch_size]
        crops=[rgb[max(0,b.y-pad):min(rgb.shape[0],b.y+b.h+pad),max(0,b.x-pad):min(rgb.shape[1],b.x+b.w+pad)].copy() for b in chunk]
        readings=engine.predict(crops)
        if len(readings)!=len(chunk):raise ValueError('Quantidade inesperada de leituras')
        digits.extend(Digit(b,str(t),float(s),start+i,method='fb_token') for i,(b,(t,s)) in enumerate(zip(chunk,readings)))
        if progress:progress(min(start+batch_size,len(boxes)),len(boxes),'OCR: folha de bordo')
    return normalize_trailing_dot(digits)


def group(digits,config,*,diagnostics=None):
    """Build local integer chains, then match smaller lowered decimal tokens.

    Values never resolve geometry. Ambiguous matches remain ungrouped.
    Distances use source pixels, including the configured DPI scale.
    """
    notes=diagnostics if diagnostics is not None else {}
    usable=sorted([d for d in digits if token(d) is not None and d.score>=config.min_confidence],
                  key=lambda d:(d.box.x,d.box.y,d.index))
    for d in digits:
        notes[d.index]='Leitura inválida ou abaixo da confiança mínima'
    if not usable:return []
    x_limit=config.tol_x*config.scale
    y_limit=config.tol_y*config.scale
    used=set();principals=[]
    for d in usable:
        if d.index in used:continue
        parts=[d];used.add(d.index)
        for e in usable:
            if e.index in used:continue
            a=parts[-1].box;b=e.box
            if b.x<=a.x:continue
            h=min(a.h,b.h);gap=b.x-(a.x+a.w)
            # Compare neighbours locally; a short decimal cannot join an integer.
            if (min(a.h,b.h)/max(a.h,b.h)>=.75
                    and -min(a.w,b.w)*.15<=gap<=min(x_limit,h*.35)
                    and abs(b.y+b.h-a.y-a.h)<=y_limit
                    and sum(len(token(p)) for p in parts)+len(token(e))<=3):
                parts.append(e);used.add(e.index)
        principals.append(parts)

    links={};reverse={}
    for i,parts in enumerate(principals):
        h=float(np.median([d.box.h for d in parts]))
        bottom=float(np.median([d.box.y+d.box.h for d in parts]))
        cy=float(np.mean([d.box.center[1] for d in parts]))
        last=parts[-1].box;right=last.x+last.w
        # A joined multi-digit token may contain the decimal's horizontal anchor.
        left=right-min(last.w,h*.65)
        for j,tail in enumerate(principals):
            if i==j or len(tail)!=1 or len(token(tail[0]))!=1:continue
            d=tail[0];b=d.box;cx,ty=b.center
            if (b.h<h*.75 and b.h<=h*config.decimal_height_ratio
                    and left<=cx<=right+min(x_limit,h*.45)
                    and bottom-h*.15<=b.y<=bottom+h*.30
                    and ty>=cy+h*config.decimal_drop):
                score=abs(cx-(right+h*.1))/h+abs(b.y-bottom)/h
                links.setdefault(i,[]).append((score,j))
                reverse.setdefault(j,[]).append((score,i))

    # Select only geometrically separated winners, independently of iteration order.
    def winner(options):
        ordered=sorted(options)
        if len(ordered)>1 and ordered[1][0]-ordered[0][0]<.20:return None
        return ordered[0][1] if ordered else None
    matches={};ambiguous=set()
    for i,options in links.items():
        j=winner(options)
        if j is not None and winner(reverse[j])==i:matches[i]=j
        else:ambiguous.add(i)
    tails=set(reverse)
    result=[]
    for i,parts in enumerate(principals):
        if i in tails:
            for d in parts:notes[d.index]='Candidato a decimal sem associação definida'
        if i in ambiguous:
            for d in parts:notes[d.index]='Associação decimal ambígua'
        if i in tails or i in ambiguous:continue
        decimal=principals[matches[i]] if i in matches else []
        integer=''.join(token(d) for d in parts)
        depth=int(integer)+(int(token(decimal[0]))/10 if decimal else 0)
        all_parts=parts+decimal
        x=min(d.box.x for d in all_parts);y=min(d.box.y for d in all_parts)
        right=max(d.box.x+d.box.w for d in all_parts);bottom=max(d.box.y+d.box.h for d in all_parts)
        mx=(min(d.box.x for d in parts)+max(d.box.x+d.box.w for d in parts))/2
        my=(min(d.box.y for d in parts)+max(d.box.y+d.box.h for d in parts))/2
        flags=['fb_anchor_unverified']
        if not decimal:flags.append('fb_no_decimetre')
        result.append(Sounding(mx,my,depth,min(d.score for d in all_parts),(x,y,right,bottom),
            [d.index for d in all_parts],'fb_subscript' if decimal else 'fb_integer',flags=flags))
    for sounding in result:
        for index in sounding.digit_ids:notes[index]='Incluída em sondagem'
    return result
