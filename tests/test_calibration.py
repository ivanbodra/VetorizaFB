from dataclasses import replace
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from vetorizafb.calibration import CalibrationPreview, MASK_KEYS
from vetorizafb.core import Box, Config, segment_details


def session():
    cfg=Config(segmentation='black',min_w=3,max_w=40,min_h=4,max_h=50)
    rgb=np.full((80,120,3),255,np.uint8)
    rgb[10:30,10:13]=0;rgb[20:45,50:60]=0
    _,all_boxes,boxes=segment_details(rgb,cfg)
    return SimpleNamespace(rgb=rgb,config=cfg,all_boxes=all_boxes,boxes=boxes,roi=None,seg_key=('test',),review={'unchanged':True})


def test_preview_recovers_size_exclusions_without_mutation():
    s=session();before=deepcopy(s.__dict__);preview=CalibrationPreview()
    changed=replace(s.config,min_w=2)
    result=preview.classify(s,changed,None)
    assert sorted((b for b,reason in result if not reason),key=lambda b:b.x)==segment_details(s.rgb,changed)[2]
    assert len([b for b,r in result if not r])==2 and len(s.boxes)==1
    assert s.review==before['review'] and s.config==before['config'] and s.boxes==before['boxes']
    assert np.array_equal(s.rgb,before['rgb'])


def test_preview_strict_boundary_and_scaled_dimensions():
    from vetorizafb.calibration import size_reasons
    cfg=Config(dpi=300,min_w=4,min_h=10)
    assert 'largura' in ';'.join(size_reasons(Box(0,0,2,15),cfg))
    assert not size_reasons(Box(0,0,3,15),cfg)


@pytest.mark.parametrize('key',MASK_KEYS)
def test_preview_refuses_stale_mask(key):
    s=session();cfg=replace(s.config,**{key:('legacy' if key=='segmentation' else not getattr(s.config,key) if key=='exclude_magenta' else getattr(s.config,key)+2)})
    with pytest.raises(ValueError,match='Máscara'):CalibrationPreview().classify(s,cfg,None)


def test_preview_refuses_changed_roi_and_missing_contours():
    s=session()
    with pytest.raises(ValueError):CalibrationPreview().classify(s,s.config,(0,0,10,10))
    s.all_boxes=None
    with pytest.raises(ValueError):CalibrationPreview().classify(s,s.config,None)


def test_colour_cache_matches_processing_and_invalidates_on_new_contours(monkeypatch):
    import vetorizafb.calibration as module
    s=session();s.rgb[:]=(240,230,100);s.rgb[20:45,50:60]=0
    s.all_boxes=segment_details(s.rgb,s.config)[1]
    preview=CalibrationPreview();calls=[]
    original=module.yellow_background_fraction
    monkeypatch.setattr(module,'yellow_background_fraction',lambda *args:(calls.append(1),original(*args))[1])
    cfg=replace(s.config,exclude_yellow=True)
    result=preview.classify(s,cfg,None)
    assert [b for b,r in result if not r]==segment_details(s.rgb,cfg)[2]
    n=len(calls);preview.classify(s,replace(cfg,yellow_min_fraction=.8),None);assert len(calls)==n
    s.all_boxes=list(s.all_boxes);preview.classify(s,cfg,None);assert len(calls)>n
