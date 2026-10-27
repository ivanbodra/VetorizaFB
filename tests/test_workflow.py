from dataclasses import replace
import json
from pathlib import Path
import threading

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from vetorizafb.core import Config, ProcessingCancelled
from vetorizafb.pipeline import sha256
from vetorizafb.workflow import ChartSession


SPEC=('PP-OCRv6_small_rec',None,'cpu')


@pytest.fixture
def session(tmp_path):
    path=tmp_path/'chart.tif'
    rgb=np.full((3,120,200),255,np.uint8)
    rgb[:,20:45,20:30]=0;rgb[:,70:95,150:160]=0
    with rasterio.open(path,'w',driver='GTiff',width=200,height=120,count=3,dtype='uint8',crs='EPSG:3857',transform=from_origin(100,200,2,2)) as ds:ds.write(rgb)
    return ChartSession(path)


class Reader:
    def __init__(self):self.calls=0
    def predict(self,crops):self.calls+=1;return [('0',.99)]*len(crops)


def ready(session):
    cfg=Config(segmentation='black')
    session.segment(cfg)
    session.run_ocr(cfg,SPEC,engine=Reader())
    session.run_grouping(cfg,SPEC)
    return cfg


def test_stage_changes_invalidate_only_required_work(session):
    cfg=ready(session)
    assert session.valid_groups(cfg,SPEC)
    changed=replace(cfg,tol_x=35)
    assert session.valid_digits(changed,SPEC) and not session.valid_groups(changed,SPEC)
    old_digits=session.digits
    session.run_grouping(changed,SPEC)
    assert session.digits is old_digits
    assert not session.valid_digits(replace(cfg,crop_padding=5),SPEC)
    assert session.valid_segments(replace(cfg,retry_one=False))
    assert not session.valid_digits(replace(cfg,retry_one=False),SPEC)
    assert not session.valid_segments(replace(cfg,threshold=90))
    with pytest.raises(ValueError,match='etapa 1'):
        session.run_ocr(replace(cfg,threshold=90),SPEC,engine=Reader())


def test_roi_keeps_original_pixel_and_geographic_coordinates(session,tmp_path):
    cfg=Config(segmentation='black');roi=(140,60,40,50)
    session.segment(cfg,roi)
    assert session.boxes[0].x==150 and session.boxes[0].y==70
    session.run_ocr(cfg,SPEC,roi,engine=Reader());session.run_grouping(cfg,SPEC,roi)
    session.export(tmp_path/'out',target_crs='EPSG:3857')
    row=(tmp_path/'out/chart.candidates.xyz').read_text().strip().split()
    assert list(map(float,row))==[410,35,0]


def test_polygon_limits_segmentation_ocr_grouping_and_project_reload(session,tmp_path):
    cfg=Config(segmentation='black')
    # Both black glyphs lie inside the polygon's bounding rectangle; only
    # the left one lies within its actual contour.
    area=((10,10),(190,10),(70,110),(10,110))
    session.segment(cfg,area)
    assert len(session.boxes)==1 and session.boxes[0].x==20
    assert session.valid_segments(cfg,area)
    assert not session.valid_segments(cfg,(10,10,181,101))
    session.run_ocr(cfg,SPEC,area,engine=Reader())
    session.run_grouping(cfg,SPEC,area)
    assert len(session.review.items)==1
    path=tmp_path/'selection.vfproject.json'
    session.save_project(path)
    restored=ChartSession.load_project(path)
    assert restored.roi==area and restored.valid_groups(cfg,SPEC,area)
    assert len(restored.boxes)==1 and len(restored.review.items)==1


def test_polygon_requires_three_valid_image_vertices(session):
    cfg=Config(segmentation='black')
    for area in (((10,10),(11,11),(12,12)), ((-1,0),(20,0),(20,20)),
                 ((0,0),(201,0),(20,20))):
        with pytest.raises(ValueError):session.segment(cfg,area)


def test_reviewed_export_excludes_pending_and_rejected_and_keeps_audit(session,tmp_path):
    ready(session)
    session.review.change(0,'correct_depth',depth=8.7)
    session.review.change(0,'accepted',note='Checked on source chart')
    session.review.change(1,'rejected',note='Contour label')
    manual=session.review.add_manual(100,50,3.2)
    assert session.review.item(manual)['status']=='unreviewed'
    meta=session.export(tmp_path/'out',target_crs='EPSG:3857',accepted_only=True)
    assert meta['soundings']==1
    assert (tmp_path/'out/chart.reviewed.xyz').read_text().split()[-1]=='8.7'
    audit=json.loads((tmp_path/'out/chart.reviewed.review.json').read_text())
    assert audit[0]['original']['depth']==0 and audit[0]['current']['depth']==8.7
    assert len(audit[0]['history'])==2 and audit[1]['status']=='rejected'
    assert all(sha256(tmp_path/'out'/name)==digest for name,digest in meta['output_sha256'].items())


def test_empty_approved_export_fails_without_writing(session,tmp_path):
    ready(session)
    with pytest.raises(ValueError,match='aprovado'):
        session.export(tmp_path/'out',accepted_only=True)
    assert not (tmp_path/'out').exists()


def test_failed_transform_does_not_publish_partial_files(session,tmp_path):
    ready(session)
    with pytest.raises(Exception):session.export(tmp_path/'out',target_crs='EPSG:0')
    assert not list((tmp_path/'out').glob('*'))


def test_reposition_and_depth_correction_require_approval_again(session):
    ready(session);r=session.review
    r.change(0,'accepted');r.change(0,'reposition',xy=(30,40))
    assert r.item(0)['status']=='unreviewed'
    assert r.item(0)['current']['pixel_x']==30
    r.change(0,'accepted');r.change(0,'correct_depth',depth=1.8)
    assert r.item(0)['status']=='unreviewed'
    with pytest.raises(ValueError):r.change(0,'correct_depth',depth=1.234)


def test_project_roundtrip_retains_edits_and_does_not_need_ocr(session,tmp_path):
    cfg=ready(session);session.review.change(0,'correct_depth',depth=1.8);session.review.change(0,'accepted')
    project=tmp_path/'saved.vfproject.json';session.save_project(project)
    restored=ChartSession.load_project(project)
    assert restored.valid_groups(cfg,SPEC)
    assert restored.review.items==session.review.items
    assert restored.digits==session.digits and restored._engine is None
    restored.export(tmp_path/'reviewed',accepted_only=True)


def test_project_refuses_modified_source(session,tmp_path):
    ready(session);project=tmp_path/'saved.vfproject.json';session.save_project(project)
    with session.path.open('ab') as f:f.write(b'changed')
    with pytest.raises(ValueError,match='SHA-256'):ChartSession.load_project(project)
    with pytest.raises(ValueError,match='modificada'):session.export(tmp_path/'out')


def test_project_refuses_invalid_digit_pairing(session,tmp_path):
    ready(session);project=tmp_path/'saved.vfproject.json';session.save_project(project)
    data=json.loads(project.read_text());data['digits'][0]['index']=99
    project.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='caixas'):ChartSession.load_project(project)


def test_old_project_does_not_claim_new_one_retry_was_run(session,tmp_path):
    ready(session);session.review.change(0,'accepted')
    project=tmp_path/'old.vfproject.json';session.save_project(project)
    data=json.loads(project.read_text());data['config'].pop('retry_one')
    for key in ('exclude_yellow','yellow_delta','yellow_min_fraction'):data['config'].pop(key)
    project.write_text(json.dumps(data))
    restored=ChartSession.load_project(project)
    assert restored.config.retry_one is False
    assert restored.config.exclude_yellow is False
    assert restored.valid_groups(restored.config,SPEC) and restored.review.counts['accepted']==1
    assert not restored.valid_digits(replace(restored.config,retry_one=True),SPEC)


def test_loaded_review_ids_and_batch_decisions_preserve_history(session):
    from vetorizafb.review import ReviewSet
    ready(session)
    records=session.review.items
    records[0]['id']=20;records[1]['id']=3
    review=ReviewSet.from_items(records)
    new=review.add_manual(100,50,10.1)
    assert new==21
    for point_id in [20,3,new]:review.change(point_id,'accepted',note='Batch check')
    assert review.counts['accepted']==3
    assert all(review.item(i)['history'][-1]['note']=='Batch check' for i in [20,3,new])


def test_colour_filter_invalidates_segmentation_and_retains_roi_coordinates(session,tmp_path):
    cfg=ready(session)
    changed=replace(cfg,exclude_yellow=True)
    assert not session.valid_segments(changed) and not session.valid_digits(changed,SPEC)
    session.rgb[:]=(245,245,120);session.rgb[70:95,150:160]=0
    roi=(140,60,40,50);session.segment(changed,roi)
    assert session.boxes==[] and session.color_rejected[0].x==150
    session.run_ocr(changed,SPEC,roi,engine=Reader());session.run_grouping(changed,SPEC,roi)
    point=session.add_point(155,82.5,1.1)
    assert session.review.item(point)['current']['confidence'] is None


def test_offset_all_preserves_originals_depths_and_rejected_status(session,tmp_path):
    from copy import deepcopy
    ready(session);r=session.review
    r.change(0,'accepted');r.change(1,'rejected')
    r.add_manual(100,50,3.2)
    before=deepcopy(r.items)
    preview=session.preview_offset(3,-2)
    assert preview['count']==3 and r.items==before
    result=session.offset_points(3,-2,note='Align sounding anchors')
    for old,new in zip(before,r.items):
        assert new['original']==old['original']
        assert new['current']['depth']==old['current']['depth']
        assert new['current']['bounds']==old['current']['bounds']
        assert new['current']['pixel_x']==old['current']['pixel_x']+3
        assert new['current']['pixel_y']==old['current']['pixel_y']-2
        assert new['history'][-1]['batch_id']==result['batch_id']
    assert [i['status'] for i in r.items]==['unreviewed','rejected','unreviewed']
    project=tmp_path/'offset.vfproject.json';session.save_project(project)
    loaded=ChartSession.load_project(project)
    assert loaded.review.items==r.items
    loaded.review.change(0,'accepted')
    loaded.export(tmp_path/'out',target_crs='EPSG:3857',accepted_only=True)
    xyz=list(map(float,(tmp_path/'out/chart.reviewed.xyz').read_text().split()))
    assert xyz==pytest.approx([156,139,0])


def test_offset_batch_is_all_or_nothing_and_selected_scope_is_independent(session):
    from copy import deepcopy
    ready(session);before=deepcopy(session.review.items)
    with pytest.raises(ValueError):session.offset_points(60,0)
    assert session.review.items==before
    session.offset_points(60,0,point_ids=[0,0])
    assert session.review.item(0)['current']['pixel_x']==85
    assert session.review.item(1)==before[1]


@pytest.mark.parametrize('dx,dy',[(float('nan'),0),(0,float('inf')),(-1000,0),(0,1000)])
def test_invalid_offset_never_mutates_points(session,dx,dy):
    from copy import deepcopy
    ready(session);before=deepcopy(session.review.items)
    with pytest.raises(ValueError):session.offset_points(dx,dy)
    assert session.review.items==before


def test_offset_metres_uses_map_axes_including_rotated_affine(session):
    from affine import Affine
    from vetorizafb.geospatial import transform_points
    ready(session);session.affine=Affine(2,.5,100,.3,-3,200)
    original=[(i['current']['pixel_x'],i['current']['pixel_y']) for i in session.review.items]
    old=transform_points(original,session.affine,session.crs,'EPSG:3857')
    session.offset_points(10,6,unit='metres')
    new=transform_points([(i['current']['pixel_x'],i['current']['pixel_y']) for i in session.review.items],session.affine,session.crs,'EPSG:3857')
    assert np.asarray(new)-np.asarray(old)==pytest.approx(np.tile([10,6],(2,1)))
    session.crs='EPSG:4326'
    with pytest.raises(ValueError,match='projetado'):session.offset_points(1,1,unit='metres')


def test_zero_offset_does_not_reset_approval_or_append_history(session):
    from copy import deepcopy
    ready(session);session.review.change(0,'accepted');before=deepcopy(session.review.items)
    assert session.offset_points(0,0)['batch_id'] is None
    assert session.review.items==before


def test_numeric_position_validation_before_edit_or_insertion(session):
    ready(session)
    with pytest.raises(ValueError):session.reposition_point(0,-1,20)
    with pytest.raises(ValueError):session.add_point(201,20,1.1)
    assert len(session.review.items)==2
    session.reposition_point(0,40,45)
    assert session.review.item(0)['current']['pixel_x']==40


def test_metre_offset_converts_projected_foot_units():
    from affine import Affine
    from pyproj import CRS
    from vetorizafb.geospatial import offset_to_pixels
    crs=CRS.from_epsg(2263);factor=crs.axis_info[0].unit_conversion_factor
    dx,dy=offset_to_pixels(10,6,Affine(2,0,0,0,-3,0),crs,'metres')
    assert (dx*2*factor,dy*-3*factor)==pytest.approx((10,6))


def test_cancelled_ocr_preserves_previous_results(session):
    cfg=ready(session);digits=session.digits;review=session.review
    cancel=threading.Event();cancel.set()
    with pytest.raises(ProcessingCancelled):session.run_ocr(cfg,SPEC,engine=Reader(),cancel=cancel)
    assert session.digits is digits and session.review is review


@pytest.mark.parametrize('roi',[(-1,0,10,10),(0,0,0,10),(0,0,300,10),(0.5,0,10,10)])
def test_invalid_roi_is_rejected(session,roi):
    with pytest.raises(ValueError):session.segment(Config(),roi)


@pytest.mark.parametrize('action',['restore_depth','restore_position','restore_both'])
def test_restore_original_preserves_history_and_independent_edits(session,tmp_path,action):
    from copy import deepcopy
    ready(session);review=session.review;original=deepcopy(review.item(0)['original'])
    review.change(0,'correct_depth',depth=12.3)
    review.change(0,'reposition',xy=(50,60))
    review.change(0,'accepted')
    before=deepcopy(review.item(0))
    review.change(0,action,note='Conferido na carta')
    item=review.item(0)
    assert item['original']==original and item['history'][:-1]==before['history']
    assert item['status']=='unreviewed' and item['history'][-1]['previous_status']=='accepted'
    assert item['current']['depth']==(12.3 if action=='restore_position' else original['depth'])
    assert item['current']['pixel_x']==(50 if action=='restore_depth' else original['pixel_x'])
    assert ('manual_depth' in item['current']['flags'])==(action=='restore_position')
    assert ('manual_position' in item['current']['flags'])==(action=='restore_depth')
    project=tmp_path/'restore.vfproject.json';session.save_project(project)
    reopened=ChartSession.load_project(project)
    assert reopened.review.items==review.items


def test_restore_noop_and_manual_points_are_protected(session):
    from copy import deepcopy
    ready(session);review=session.review;before=deepcopy(review.items)
    assert review.change(0,'restore_both') is False
    assert review.items==before
    point=review.add_manual(20,30,4.5);before=deepcopy(review.item(point))
    with pytest.raises(ValueError,match='no original'):review.change(point,'restore_both')
    assert review.item(point)==before
