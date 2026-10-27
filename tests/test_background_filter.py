from dataclasses import replace
import numpy as np
import pytest

from vetorizafb.core import Box,Config,segment_details,yellow_background_fraction


@pytest.mark.parametrize('background,rejected',[
    ((245,245,120),True),((180,220,60),True),((255,255,255),False),
    ((120,255,255),False),((40,120,255),False),((180,180,180),False),
    ((245,245,230),False),((255,80,80),False)])
def test_yellow_filter_uses_original_background_and_signed_channel_differences(background,rejected):
    rgb=np.full((80,80,3),background,np.uint8);rgb[20:50,30:36]=0
    cfg=Config(segmentation='black',exclude_yellow=True)
    _,all_boxes,kept,removed=segment_details(rgb,cfg,return_rejected=True)
    assert len(all_boxes)==1 and len(removed)==int(rejected) and len(kept)==int(not rejected)
    _,_,unfiltered=segment_details(rgb,replace(cfg,exclude_yellow=False))
    assert len(unfiltered)==1


def test_background_fraction_ignores_black_ink_and_retains_mixed_boundary_by_default():
    rgb=np.full((40,40,3),(245,245,120),np.uint8);rgb[:,20:]=(120,255,255)
    rgb[10:30,18:22]=0;b=Box(18,10,4,20)
    fraction=yellow_background_fraction(rgb,b,Config())
    assert fraction==pytest.approx(.5)
    _,_,kept,removed=segment_details(rgb,Config(segmentation='black',exclude_yellow=True),return_rejected=True)
    assert len(kept)==1 and removed==[]
    _,_,kept,removed=segment_details(rgb,Config(segmentation='black',exclude_yellow=True,yellow_min_fraction=.4),return_rejected=True)
    assert kept==[] and len(removed)==1


@pytest.mark.parametrize('options',[{'yellow_delta':0},{'yellow_delta':256},{'yellow_delta':1.5},
                                  {'yellow_min_fraction':0},{'yellow_min_fraction':1.1},{'exclude_yellow':'yes'}])
def test_invalid_colour_settings_are_rejected(options):
    with pytest.raises(ValueError):Config(**options)
