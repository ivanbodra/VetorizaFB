"""Auditable token edits shared by the classic field-sheet review dialog."""
from datetime import datetime, timezone
import re
from .core import Box


def correct(session,index,text):
    if session.digits is None:raise ValueError('Execute Reconhecer primeiro.')
    text=text.strip()
    if text and not re.fullmatch(r'[0-9]{1,3}' if session.config.segmentation=='fb' else '[0-9]',text):
        raise ValueError('Informe até três algarismos em FB, ou um algarismo em carta impressa.')
    d=session.digits[index]
    d.alternatives.append(dict(text=d.raw_text,score=d.confidence,method=d.method,
                               action='manual_correction',timestamp=datetime.now(timezone.utc).isoformat()))
    d.raw_text=text;d.confidence=1.;d.selected_text=None;d.selected_confidence=None;d.method='manual'
    session.review=session.group_key=None


def edit_boxes(session,indices,*,axis=None,position=None):
    if session.config.segmentation!='fb':raise ValueError('União e divisão de caixas disponíveis no modo Folha de bordo.')
    ids=sorted(set(indices))
    if not ids or session.boxes is None:raise ValueError('Selecione as caixas.')
    boxes=[session.boxes[i] for i in ids]
    x=min(b.x for b in boxes);y=min(b.y for b in boxes)
    r=max(b.x+b.w for b in boxes);bottom=max(b.y+b.h for b in boxes)
    if axis is None:
        if len(ids)<2:raise ValueError('Selecione pelo menos duas caixas.')
        new=[Box(x,y,r-x,bottom-y)]
    else:
        if len(ids)!=1 or axis not in ('vertical','horizontal'):raise ValueError('Selecione uma caixa para dividir.')
        limit=r-x if axis=='vertical' else bottom-y
        if type(position) is not int or not 0<position<limit:raise ValueError('A divisão deve ficar dentro da caixa.')
        new=([Box(x,y,position,bottom-y),Box(x+position,y,r-x-position,bottom-y)] if axis=='vertical'
             else [Box(x,y,r-x,position),Box(x,y+position,r-x,bottom-y-position)])
    session.boxes=[b for i,b in enumerate(session.boxes) if i not in ids]+new
    session.digits=session.review=session.ocr_key=session.group_key=None
