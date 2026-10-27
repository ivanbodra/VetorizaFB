from types import SimpleNamespace
import pytest
from vetorizafb.core import Box,Digit,Config
from vetorizafb.token_review import correct,edit_boxes


def session(fb=True):
    boxes=[Box(10,10,20,40),Box(32,10,20,40)]
    return SimpleNamespace(config=Config(segmentation='fb' if fb else 'legacy'),boxes=boxes,
        digits=[Digit(b,t,.9,i) for i,(b,t) in enumerate(zip(boxes,['3','5']))],review=object(),group_key='g',ocr_key='r')


def test_manual_multi_token_keeps_evidence_and_invalidates_only_groups():
    s=session();correct(s,0,'35')
    assert s.digits[0].raw_text=='35' and s.digits[0].alternatives[0]['text']=='3'
    assert s.review is None and s.group_key is None and s.ocr_key=='r'


def test_cn_cannot_accept_multi_character_correction():
    s=session(False)
    with pytest.raises(ValueError):correct(s,0,'35')
    assert s.digits[0].raw_text=='3'


def test_union_and_split_invalidate_readings():
    s=session();edit_boxes(s,[0,1]);assert s.boxes==[Box(10,10,42,40)]
    assert s.digits is None and s.ocr_key is None
    edit_boxes(s,[0],axis='horizontal',position=20)
    assert s.boxes==[Box(10,10,42,20),Box(10,30,42,20)]


def test_bad_split_is_atomic():
    s=session();before=s.boxes[:]
    with pytest.raises(ValueError):edit_boxes(s,[0],axis='vertical',position=20)
    assert s.boxes==before and s.digits is not None
