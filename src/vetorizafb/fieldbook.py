"""Field-sheet tokens and layout. No neighbouring depths or reference XYZ used."""
import re
import math
import cv2
import numpy as np
from .core import Digit, Sounding, check_cancel, normalize_trailing_dot, isolated_one_crop


def mask(rgb, config):
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    background=cv2.morphologyEx(gray,cv2.MORPH_CLOSE,np.ones((51,51),np.uint8))
    flat=cv2.divide(gray,np.maximum(background,1),scale=255)
    local=cv2.createCLAHE(2.,(8,8)).apply(flat)
    return np.uint8(local < config.threshold)*255


def token(d):
    t=(d.selected_text if d.selected_text is not None else d.raw_text).strip()
    return t if re.fullmatch(r'[0-9]{1,3}',t) else None


def recognize(rgb,boxes,engine,batch_size=64,pad=3,*,retry=False,retry_one=False,
              min_confidence=.35,progress=None,cancel=None):
    if batch_size<1 or pad<0:raise ValueError('Lote e margem de recorte inválidos')
    if not math.isfinite(min_confidence) or not 0<=min_confidence<=1:
        raise ValueError('Confiança mínima inválida')
    digits=[]
    h,w=rgb.shape[:2]
    def crop(box,margin):
        if min(box.x,box.y)<0 or box.x+box.w>w or box.y+box.h>h:
            raise ValueError('Caixa fora da imagem')
        return rgb[max(0,box.y-margin):min(h,box.y+box.h+margin),
                   max(0,box.x-margin):min(w,box.x+box.w+margin)].copy()
    def predict(crops):
        readings=engine.predict(crops)
        if len(readings)!=len(crops):raise ValueError('Quantidade inesperada de leituras')
        checked=[]
        for text,score in readings:
            score=float(score)
            if not math.isfinite(score) or not 0<=score<=1:raise ValueError('Confiança OCR inválida')
            checked.append((str(text),score))
        return checked
    for start in range(0,len(boxes),batch_size):
        check_cancel(cancel)
        chunk=boxes[start:start+batch_size]
        readings=predict([crop(b,pad) for b in chunk])
        digits.extend(Digit(b,t,s,start+i,method='fb_token') for i,(b,(t,s)) in enumerate(zip(chunk,readings)))
        if progress:progress(min(start+len(chunk),len(boxes)),len(boxes),'OCR: folha de bordo')
    normalize_trailing_dot(digits)
    # Narrow strokes only select candidates for a real model retry, never a value.
    ones={d.index for d in digits if retry_one and d.box.w/d.box.h<=.65
          and (token(d) is None or d.score<min_confidence)
          and d.raw_text.strip() in {'','I','i','l','|','!','1','1.'}}
    def unresolved(d):
        return (d.index in ones and (token(d) is None or d.score<min_confidence)
                or retry and (token(d) is None or d.score<min_confidence))
    def attempt(subset,prepare,method,stage,only_one=False):
        for start in range(0,len(subset),batch_size):
            check_cancel(cancel)
            batch=subset[start:start+batch_size]
            pairs=[(d,prepare(d)) for d in batch]
            pairs=[(d,c) for d,c in pairs if c is not None]
            if pairs:
                readings=predict([c for _,c in pairs])
                for (d,_),(raw,score) in zip(pairs,readings):
                    d.alternatives.append(dict(text=raw,confidence=score,method=method))
                    text=raw.strip()
                    if re.fullmatch(r'[0-9]\.',text):text=text[0]
                    directed=only_one or d.index in ones
                    eligible=(text=='1' and score>=max(.8,min_confidence) if directed else
                              re.fullmatch(r'[0-9]{1,3}',text) is not None and score>=min_confidence)
                    if eligible and (token(d) is None or score>d.score):
                        d.selected_text,d.selected_confidence=text,score
                        d.method='fb_one_retry' if directed else 'fb_retry'
            if progress:progress(min(start+len(batch),len(subset)),len(subset),stage)
    def binary(d):
        gray=cv2.cvtColor(crop(d.box,pad),cv2.COLOR_RGB2GRAY)
        _,bw=cv2.threshold(gray,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        bw=cv2.copyMakeBorder(bw,6,6,6,6,cv2.BORDER_CONSTANT,value=255)
        return cv2.cvtColor(cv2.resize(bw,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC),cv2.COLOR_GRAY2RGB)
    def tight(d):
        c=cv2.copyMakeBorder(crop(d.box,0),8,8,8,8,cv2.BORDER_CONSTANT,value=(255,255,255))
        return cv2.resize(c,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
    if retry or retry_one:
        attempt([d for d in digits if unresolved(d)],binary,'fb_binary_padded_2x','OCR FB: reler leituras')
        attempt([d for d in digits if unresolved(d)],tight,'fb_tight_padded_2x','OCR FB: reler recortes')
        attempt([d for d in digits if d.index in ones and unresolved(d)],
                lambda d:isolated_one_crop(rgb,d.box,pad),'fb_isolated_one_2x',
                'OCR FB: isolar possíveis 1',only_one=True)
    check_cancel(cancel)
    return digits


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
            if (min(a.h,b.h)/max(a.h,b.h)>=config.fb_integer_height_ratio
                    and -min(a.w,b.w)*config.fb_overlap<=gap<=x_limit
                    and abs(b.y+b.h-a.y-a.h)<=y_limit
                    and sum(len(token(p)) for p in parts)+len(token(e))<=3):
                parts.append(e);used.add(e.index)
        principals.append(parts)

    geometry=[(float(np.median([d.box.h for d in parts])),
               min(d.box.x for d in parts),max(d.box.x+d.box.w for d in parts),
               min(d.box.y for d in parts),float(np.median([d.box.y+d.box.h for d in parts])),
               float(np.mean([d.box.center[1] for d in parts]))) for parts in principals]
    links={};reverse={}
    for i,parts in enumerate(principals):
        h,_,_,_,bottom,cy=geometry[i]
        last=parts[-1].box;right=last.x+last.w
        # A joined multi-digit token may contain the decimal's horizontal anchor.
        left=right-min(last.w,h*config.fb_decimal_left)
        for j,tail in enumerate(principals):
            if i==j or len(tail)!=1 or len(token(tail[0]))!=1:continue
            d=tail[0];b=d.box;cx,ty=b.center
            if (b.h<=h*config.decimal_height_ratio
                    and left<=cx<=right+h*config.fb_decimal_distance
                    and bottom-h*config.fb_decimal_top_overlap<=b.y<=bottom+h*config.fb_decimal_max_gap
                    and ty>=cy+h*config.decimal_drop):
                score=abs(cx-(right+h*.1))/h+abs(b.y-bottom)/h
                links.setdefault(i,[]).append((score,j))
                reverse.setdefault(j,[]).append((score,i))

    # Select only geometrically separated winners, independently of iteration order.
    def winner(options):
        ordered=sorted(options)
        if len(ordered)>1 and ordered[1][0]-ordered[0][0]<config.fb_ambiguity_margin:return None
        return ordered[0][1] if ordered else None
    matches={};ambiguous=set()
    for i,options in links.items():
        j=winner(options)
        if j is not None and winner(reverse[j])==i:matches[i]=j
        else:ambiguous.add(i)
    tails=set(reverse)
    # A small nearby component is not sufficient evidence for an independent
    # sounding. Retain it for review instead of exporting annotation fragments.
    small_nearby=set()
    for i,parts in enumerate(principals):
        if config.fb_keep_small or i in tails or i in links:continue
        h,left,right,top,_,_=geometry[i]
        cx=(left+right)/2
        for j,other in enumerate(principals):
            if i==j:continue
            reference,left,right,_,bottom,_=geometry[j]
            if h>=reference*config.fb_small_ratio:continue
            if left-reference*.15<=cx<=right+reference*.65 and bottom-reference*.15<=top<=bottom+reference:
                small_nearby.add(i)
                break
    result=[]
    for i,parts in enumerate(principals):
        if i in tails:
            for d in parts:notes[d.index]='Candidato a decimal sem associação definida'
        if i in ambiguous:
            for d in parts:notes[d.index]='Associação decimal ambígua'
        if i in small_nearby:
            for d in parts:notes[d.index]='Componente pequeno próximo de sondagem; revisar'
        if i in tails or i in ambiguous or i in small_nearby:continue
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
