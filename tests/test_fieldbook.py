from dataclasses import replace
import numpy as np
import pytest
from vetorizafb.core import Box,Digit,Config,group
from vetorizafb.fieldbook import recognize


def d(x,y,w,h,text,index):return Digit(Box(x,y,w,h),text,.99,index)
def cfg():return Config(segmentation='fb',grouping='fb',decimal_height_ratio=.72)


def test_joined_integer_and_lower_decimetre_above_cn_limit():
    digits=[d(10,10,40,40,'35',0),d(30,53,10,14,'8',1)]
    result=group(digits,cfg())
    assert len(result)==1 and result[0].depth==35.8
    assert result[0].digit_ids==[0,1] and result[0].pixel_y==30
    assert all(0 not in s.digit_ids for s in group(digits,Config())) # CN retains single-character rule


def test_separate_integer_and_optional_decimal():
    digits=[d(10,10,15,40,'3',0),d(27,10,15,40,'5',1),d(30,53,10,14,'8',2),d(100,10,35,40,'42',3)]
    assert [s.depth for s in group(digits,cfg())]==[35.8,42.]


def test_ambiguous_lower_candidates_abstain():
    digits=[d(10,10,40,40,'35',0),d(40,53,8,14,'8',1),d(42,53,8,14,'9',2)]
    assert group(digits,cfg())==[]


def test_reading_preserves_multi_digit_and_nonnumeric_without_correction():
    class Engine:
        def predict(self,crops):return [('35',.9),('S',.5)]
    a=recognize(np.full((100,100,3),255,np.uint8),[Box(1,1,40,40),Box(50,50,10,14)],Engine())
    assert a[0].raw_text=='35' and a[0].text is None
    assert a[1].raw_text=='S'


def test_fieldbook_recognition_reports_progress_with_stage():
    class Engine:
        def predict(self,crops):return [('3',.9) for _ in crops]
    updates=[]
    recognize(np.full((60,60,3),255,np.uint8),[Box(10,10,20,30)],Engine(),
              progress=lambda current,total,stage:updates.append((current,total,stage)))
    assert updates==[(1,1,'OCR: folha de bordo')]


def test_fieldbook_token_accepts_trailing_dot_without_losing_raw_text():
    from vetorizafb.fieldbook import token
    class Engine:
        def predict(self,crops):return [('8.',.94)]
    result=recognize(np.full((60,60,3),255,np.uint8),[Box(10,10,20,30)],Engine())
    assert result[0].raw_text=='8.' and result[0].text=='8'
    assert token(result[0])=='8' and result[0].score==.94


@pytest.mark.parametrize('ratio',[.6,.95])
def test_real_project_35_8_with_touching_boxes_and_different_tops(ratio):
    digits=[d(2985,1032,26,57,'3',1404),d(3011,1029,24,59,'5',1418),
            d(3039,1091,14,25,'8',1429)]
    config=replace(cfg(),decimal_height_ratio=ratio,decimal_drop=.4,tol_x=60,tol_y=10)
    for readings in (digits,list(reversed(digits))):
        result=group(readings,config)
        assert len(result)==1 and result[0].depth==35.8
        assert result[0].digit_ids==[1404,1418,1429]


def test_real_project_annotations_do_not_suppress_40_8_and_41():
    digits=[d(2798,1889,31,63,'4',1302),d(2839,1890,22,61,'0',1321),
            d(2868,1948,15,31,'8',1336),d(2871,1982,13,16,'2',1341),
            d(2886,1890,28,64,'4',1352),d(2923,1890,5,63,'1',1376),
            d(2887,1985,10,14,'2',1353),d(2907,1991,15,8,'2',1366)]
    result=group(digits,replace(cfg(),decimal_drop=.4,tol_x=60,tol_y=10))
    assert any(s.depth==40.8 and s.digit_ids==[1302,1321,1336] for s in result)
    assert any(s.depth==41 and s.digit_ids==[1352,1376] for s in result)


def test_fb_vertical_tolerance_and_small_horizontal_overlap():
    digits=[d(10,10,20,40,'3',0),d(28,13,20,40,'5',1)]
    assert [s.depth for s in group(digits,replace(cfg(),tol_y=3))]==[35]
    assert [s.depth for s in group(digits,replace(cfg(),tol_y=2))]==[3,5]


def test_separate_rows_and_distant_soundings_remain_separate():
    digits=[d(10,10,20,40,'3',0),d(10,100,20,40,'4',1),d(90,10,20,40,'5',2)]
    assert sorted(s.depth for s in group(digits,cfg()))==[3,4,5]


def test_ambiguous_decimal_has_diagnostic_and_no_invented_integer():
    from vetorizafb.fieldbook import group as fb_group
    notes={}
    digits=[d(10,10,40,40,'35',0),d(40,53,8,14,'8',1),d(42,53,8,14,'9',2)]
    assert fb_group(digits,cfg(),diagnostics=notes)==[]
    assert notes[0]=='Associação decimal ambígua'
