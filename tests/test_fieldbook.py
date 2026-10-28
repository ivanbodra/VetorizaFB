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
    digits=[d(10,10,40,40,'35',0),d(25,53,8,14,'8',1),d(40,53,8,14,'9',2)]
    assert group(digits,cfg())==[]


def test_reading_preserves_multi_digit_and_nonnumeric_without_correction():
    class Engine:
        def predict(self,crops):return [('35',.9),('S',.5)]
    a=recognize(np.full((100,100,3),255,np.uint8),[Box(1,1,40,40),Box(50,50,10,14)],Engine())
    assert a[0].raw_text=='35' and a[0].text is None
    assert a[1].raw_text=='S'


def test_fieldbook_token_accepts_trailing_dot_without_losing_raw_text():
    from vetorizafb.fieldbook import token
    class Engine:
        def predict(self,crops):return [('8.',.94)]
    result=recognize(np.full((60,60,3),255,np.uint8),[Box(10,10,20,30)],Engine())
    assert result[0].raw_text=='8.' and result[0].text=='8'
    assert token(result[0])=='8' and result[0].score==.94
