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
    project.write_text(json.dumps(data))
    restored=ChartSession.load_project(project)
    assert restored.config.retry_one is False
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


def test_cancelled_ocr_preserves_previous_results(session):
    cfg=ready(session);digits=session.digits;review=session.review
    cancel=threading.Event();cancel.set()
    with pytest.raises(ProcessingCancelled):session.run_ocr(cfg,SPEC,engine=Reader(),cancel=cancel)
    assert session.digits is digits and session.review is review


@pytest.mark.parametrize('roi',[(-1,0,10,10),(0,0,0,10),(0,0,300,10),(0.5,0,10,10)])
def test_invalid_roi_is_rejected(session,roi):
    with pytest.raises(ValueError):session.segment(Config(),roi)
