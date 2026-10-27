import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication,QInputDialog
from vetorizafb.qt_gui import Window
from vetorizafb.core import Box,Digit,Config
from vetorizafb.workflow import ChartSession
import rasterio
from rasterio.transform import from_origin

@pytest.fixture
def window(tmp_path):
    app=QApplication.instance() or QApplication([])
    path=tmp_path/'fb.tif'
    with rasterio.open(path,'w',driver='GTiff',width=160,height=100,count=3,dtype='uint8',crs='EPSG:4326',transform=from_origin(-43,-23,.001,.001)) as ds:ds.write(np.full((3,100,160),255,np.uint8))
    w=Window();w.loaded(ChartSession(path));yield w
    w.dirty=False;w.close();app.processEvents()

def ready(w):
    s=w.session;w.mode.setCurrentIndex(2);cfg=w.config();s.segment(cfg)
    s.boxes=[Box(10,10,40,40),Box(30,53,10,14)]
    s.digits=[Digit(s.boxes[0],'35',.99,0),Digit(s.boxes[1],'8',.99,1)]
    s.model_spec=('PP-OCRv6_small_rec',None,'cpu');s.ocr_key=s.expected_ocr_key(cfg,s.model_spec)
    return s,cfg

def test_modes_and_group_project_roundtrip(window,tmp_path):
    s,cfg=ready(window);s.run_grouping(cfg,s.model_spec)
    assert s.review.items[0]['current']['depth']==35.8
    p=tmp_path/'project.json';s.save_project(p);loaded=ChartSession.load_project(p)
    assert loaded.valid_groups(cfg,s.model_spec)
    assert loaded.digits[0].raw_text=='35'
    assert window.tabs.count()==4 and window.mode.count()==3

def test_manual_multi_token_correction_invalidates_groups(window,monkeypatch):
    s,cfg=ready(window);s.run_grouping(cfg,s.model_spec)
    window.table_kind.setCurrentIndex(1);window.refresh_table();window.table.selectRow(0)
    monkeypatch.setattr(QInputDialog,'getText',lambda *a,**k:('36',True))
    window.correct()
    assert s.digits[0].raw_text=='36' and s.digits[0].alternatives[0]['text']=='35'
    assert s.review is None
    s.run_grouping(cfg,s.model_spec);assert s.review.items[0]['current']['depth']==36.8

def test_merge_boxes_removes_stale_ocr(window,monkeypatch):
    s,cfg=ready(window);window.table_kind.setCurrentIndex(1);window.refresh_table()
    monkeypatch.setattr(window,'ids',lambda:[0,1]);window.merge_boxes()
    assert len(s.boxes)==1 and s.boxes[0]==Box(10,10,40,57)
    assert s.digits is None and s.review is None
