"""Numbers inside closed map boundaries remain foreground, glyph holes do not."""
from dataclasses import replace
import json

import cv2
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from vetorizafb.core import Box,Config,segment_details,segment
from vetorizafb.workflow import ChartSession


@pytest.fixture
def chart():
    rgb=np.full((180,240,3),(217,255,255),np.uint8)
    # Magenta frame, black contour ring, and a disconnected ring-shaped digit.
    cv2.rectangle(rgb,(10,10),(220,160),(255,0,255),1)
    cv2.rectangle(rgb,(30,30),(200,140),(0,0,0),1)
    cv2.rectangle(rgb,(65,60),(80,85),(0,0,0),2)
    rgb[60:86,100:106]=0
    return rgb


def config():
    return Config(dpi=300,reference_dpi=300,blur_size=1,kernel_size=1,min_w=3,max_w=40,min_h=8,max_h=40,exclude_magenta=False)


def test_nested_characters_survive_closed_frames_and_contour_lines(chart):
    mask,all_boxes,accepted=segment_details(chart,config())
    assert accepted==[Box(64,59,18,28),Box(100,60,6,26)]
    assert len(all_boxes)==4  # two boundaries plus two glyphs; no hole boxes
    assert segment_details(chart,config(),contour_revision=1)[2]==[]


def test_holes_in_zero_are_not_duplicate_candidates():
    rgb=np.full((100,100,3),255,np.uint8)
    cv2.rectangle(rgb,(30,25),(55,60),(0,0,0),2)
    boxes=segment(rgb,config())
    assert boxes==[Box(29,24,28,38)]


def test_open_frame_has_same_characters_as_closed_frame(chart):
    closed=segment(chart,config())
    chart[10,100:120]=(217,255,255)
    assert segment(chart,config())==closed


def test_yellow_filter_still_applies_to_nested_characters(chart):
    chart[(chart[:,:,0]==217)&(chart[:,:,1]==255)]=(245,245,120)
    _,_,accepted,rejected=segment_details(chart,replace(config(),exclude_yellow=True),return_rejected=True)
    assert accepted==[] and len(rejected)==2


def test_old_project_keeps_review_and_old_contour_preview_until_explicit_segment(tmp_path,chart):
    chart[45:71,228:234]=0  # a real old-version candidate outside the frame
    path=tmp_path/'chart.tif'
    with rasterio.open(path,'w',driver='GTiff',width=240,height=180,count=3,dtype='uint8',crs='EPSG:3857',transform=from_origin(100,200,1,1)) as ds:ds.write(chart.transpose(2,0,1))
    session=ChartSession(path);cfg=config();spec=('test',None,'cpu')
    session.segment(cfg)
    _,old_all,old_boxes=segment_details(chart,cfg,contour_revision=1)
    session.contour_revision=1;session.boxes=old_boxes;session.all_boxes=old_all
    session.seg_key=session.expected_seg_key(cfg)
    class Reader:
        def predict(self,crops):return [('1',.99)]*len(crops)
    session.run_ocr(cfg,spec,engine=Reader());session.run_grouping(cfg,spec)
    session.review.change(0,'accepted',note='Saved review')
    file=tmp_path/'old.vfproject.json';session.save_project(file)
    data=json.loads(file.read_text());data.pop('contour_revision')
    # A project has its own saved boxes/readings; loading never recreates them.
    file.write_text(json.dumps(data))
    restored=ChartSession.load_project(file)
    assert restored.contour_revision==1 and restored.review.items==session.review.items
    assert restored.valid_groups(restored.config,spec)
    assert len(restored.all_boxes)==2  # historical EXTERNAL preview
    restored.save_project(tmp_path/'preserved.vfproject.json')
    assert json.loads((tmp_path/'preserved.vfproject.json').read_text())['contour_revision']==1
    restored.segment(cfg)
    assert restored.contour_revision==2 and len(restored.boxes)==3 and restored.review is None
    assert not restored.valid_digits(cfg,spec)


def test_magenta_frame_is_ignored_without_losing_black_digits(chart):
    cfg=replace(config(),exclude_magenta=True)
    _,all_boxes,accepted=segment_details(chart,cfg)
    assert accepted==[Box(64,59,18,28),Box(100,60,6,26)]
    assert len(all_boxes)==3  # black frame and two glyphs; no magenta frame
