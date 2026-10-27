"""Field-sheet tokens and layout. No neighbouring depths or reference XYZ used."""
import re
import cv2
import numpy as np
from .core import Digit, Sounding, check_cancel


def mask(rgb, config):
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    background=cv2.morphologyEx(gray,cv2.MORPH_CLOSE,np.ones((51,51),np.uint8))
    flat=cv2.divide(gray,np.maximum(background,1),scale=255)
    local=cv2.createCLAHE(2.,(8,8)).apply(flat)
    return np.uint8(local < config.threshold)*255


def token(d):
    t=d.raw_text.strip()
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
        if progress:progress(min(start+batch_size,len(boxes)),len(boxes))
    return digits


def group(digits,config):
    """Associate principal tokens with smaller lower digits; ambiguous links abstain.

    Principal neighbouring fragments may concatenate only with a narrow gap and
    aligned baseline. A decimal is optional; numeric depth never resolves layout.
    """
    usable=[d for d in digits if token(d) is not None and d.score>=config.min_confidence]
    if not usable:return []
    h=float(np.percentile([d.box.h for d in usable],75))
    large=sorted([d for d in usable if d.box.h>=h*config.decimal_height_ratio],key=lambda d:(d.box.y,d.box.x))
    small=[d for d in usable if d.box.h<h*config.decimal_height_ratio and len(token(d))==1]
    used=set();principals=[]
    for d in large:
        if d.index in used:continue
        parts=[d];used.add(d.index)
        for e in sorted(large,key=lambda a:a.box.x):
            if e.index in used:continue
            last=parts[-1].box;b=e.box
            gap=b.x-(last.x+last.w)
            if 0<=gap<=min(config.tol_x*.25,h*.18) and abs((b.y+b.h)-(last.y+last.h))<=h*.18:
                if sum(len(token(p)) for p in parts)+len(token(e))<=3:
                    parts.append(e);used.add(e.index)
        principals.append(parts)
    links={};reverse={}
    for i,parts in enumerate(principals):
        x=min(p.box.x for p in parts);right=max(p.box.x+p.box.w for p in parts)
        bottom=max(p.box.y+p.box.h for p in parts);top=min(p.box.y for p in parts)
        for d in small:
            b=d.box;cx,cy=b.center
            if x-h*.15<=cx<=right+h*.45 and bottom-h*.15<=b.y<=bottom+h*.65 and cy>(top+bottom)/2+h*config.decimal_drop:
                links.setdefault(i,[]).append(d);reverse.setdefault(d.index,[]).append(i)
    result=[]
    for i,parts in enumerate(principals):
        tails=links.get(i,[]);flags=['fb_anchor_unverified']
        if len(tails)>1 or any(len(reverse[d.index])>1 for d in tails):
            # Do not output a plausible but incomplete integer as a depth.
            continue
        integer=''.join(token(d) for d in sorted(parts,key=lambda d:d.box.x))
        depth=int(integer)
        if tails:depth+=int(token(tails[0]))/10
        else:flags.append('fb_no_decimetre')
        main=list(parts);all_parts=main+tails
        x=min(d.box.x for d in all_parts);y=min(d.box.y for d in all_parts)
        right=max(d.box.x+d.box.w for d in all_parts);bottom=max(d.box.y+d.box.h for d in all_parts)
        # Provisional anchor: principal text centre, independent of decimal size.
        mx=(min(d.box.x for d in main)+max(d.box.x+d.box.w for d in main))/2
        my=(min(d.box.y for d in main)+max(d.box.y+d.box.h for d in main))/2
        result.append(Sounding(mx,my,depth,min(d.score for d in all_parts),(x,y,right,bottom),
            [d.index for d in all_parts],'fb_subscript' if tails else 'fb_integer',flags=flags))
    return result
