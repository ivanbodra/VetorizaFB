import threading
import numpy as np
import pytest

from vetorizafb.core import Box,Config,ProcessingCancelled,group,recognize


class TwoReads:
    def __init__(self,retry):self.calls=0;self.retry=retry
    def predict(self,crops):
        self.calls+=1
        return [('l',.96)]*len(crops) if self.calls==1 else [self.retry]*len(crops)


def test_recovery_keeps_original_and_real_alternative_scores():
    digits=recognize(np.full((40,40,3),255,np.uint8),[Box(10,10,5,20)],TwoReads(('1',.88)),retry=True)
    d=digits[0]
    assert (d.raw_text,d.confidence,d.text,d.score)==('l',.96,'1',.88)
    assert d.alternatives==[dict(text='1',confidence=.88,method='binary_padded_2x')]
    sounding=group(digits,Config())[0]
    assert sounding.depth==1 and sounding.confidence==.88 and sounding.flags==['ocr_retry']


@pytest.mark.parametrize('reading',[('11',.99),('',.99),('I',.99),('1',.1)])
def test_recovery_does_not_guess_or_truncate(reading):
    digits=recognize(np.full((40,40,3),255,np.uint8),[Box(10,10,5,20)],TwoReads(reading),retry=True)
    assert digits[0].text is None and group(digits,Config())==[]


def test_cancel_between_batches_has_no_next_model_call():
    cancel=threading.Event()
    class Reader:
        calls=0
        def predict(self,crops):self.calls+=1;cancel.set();return [('0',.99)]*len(crops)
    reader=Reader()
    with pytest.raises(ProcessingCancelled):
        recognize(np.full((40,40,3),255,np.uint8),[Box(2,2,5,20),Box(15,2,5,20)],reader,batch_size=1,cancel=cancel)
    assert reader.calls==1


def test_directed_one_retry_uses_model_score_and_keeps_pending():
    reader=TwoReads(('1',.88))
    digits=recognize(np.full((40,40,3),255,np.uint8),[Box(10,10,5,20)],reader,retry_one=True)
    d=digits[0]
    assert (d.raw_text,d.confidence,d.text,d.score,d.method)==('l',.96,'1',.88,'ocr_one_retry')
    s=group(digits,Config())[0]
    assert s.depth==1 and s.review_status=='unreviewed' and 'ocr_one_retry' in s.flags


@pytest.mark.parametrize('reading',[('7',.99),('11',.99),('1',.79),('I',.99)])
def test_directed_retry_does_not_force_a_one(reading):
    d=recognize(np.full((40,40,3),255,np.uint8),[Box(10,10,5,20)],TwoReads(reading),retry_one=True)[0]
    assert d.text is None and d.selected_confidence is None
    assert d.alternatives[0]['confidence']==reading[1]


def test_directed_retry_leaves_zero_wide_glyphs_and_words_unchanged():
    class Reader:
        calls=0
        def predict(self,crops):
            self.calls+=1
            assert self.calls==1  # none of these boxes should be retried
            return [('0',.01),('I',.9),('I',.9),('D',.9),('11',.99)]
    ds=recognize(np.full((50,200,3),255,np.uint8),
                 [Box(2,10,6,20),Box(30,10,18,20),Box(65,10,5,20),Box(74,10,12,20),Box(150,10,6,20)],Reader(),retry_one=True)
    assert ds[0].text=='0' and ds[0].score==.01 and all(not d.alternatives for d in ds)


def test_adjacent_ambiguous_ones_are_retried_together():
    ds=recognize(np.full((40,60,3),255,np.uint8),[Box(10,10,6,20),Box(22,10,6,20)],TwoReads(('1',.94)),retry_one=True)
    assert [s.depth for s in group(ds,Config())]==[11.]


def test_general_retry_keeps_the_directed_one_threshold_when_both_enabled():
    d=recognize(np.full((40,40,3),255,np.uint8),[Box(10,10,5,20)],TwoReads(('1',.6)),retry=True,retry_one=True)[0]
    assert d.text is None


def narrow_stroke_with_neighbour():
    rgb=np.full((45,60,3),255,np.uint8)
    rgb[10:30,12:15]=0
    rgb[11:14,19:21]=0  # disconnected neighbour enters the padded crop
    return rgb,Box(10,9,7,22)


class ThreeReads:
    def __init__(self,last):self.calls=0;self.last=last;self.crops=[]
    def predict(self,crops):
        self.crops.extend(crops);self.calls+=1
        return [[('I',.55)],[('1.',.79)],[self.last]][self.calls-1]


def test_isolated_retry_recovers_one_without_truncating_punctuated_reading():
    rgb,b=narrow_stroke_with_neighbour();reader=ThreeReads(('1',.98))
    d=recognize(rgb,[b],reader,retry_one=True)[0]
    assert (d.box,d.raw_text,d.confidence)==(b,'I',.55)
    assert (d.text,d.score,d.method)==('1',.98,'ocr_one_isolated')
    assert [(a['text'],a['confidence']) for a in d.alternatives]==[('1.',.79),('1',.98)]
    assert d.alternatives[-1]['method']=='isolated_component_padded_2x'
    import cv2
    ink=(reader.crops[-1].mean(axis=2)<128).astype(np.uint8)
    assert cv2.connectedComponents(ink)[0]==2  # background plus the one stroke
    s=group([d],Config())[0]
    assert s.review_status=='unreviewed' and 'ocr_one_retry' in s.flags


@pytest.mark.parametrize('last',[('1.',.99),('11',.99),('7',.99),('1',.79)])
def test_isolated_retry_still_requires_an_exact_confident_one(last):
    rgb,b=narrow_stroke_with_neighbour()
    d=recognize(rgb,[b],ThreeReads(last),retry_one=True)[0]
    assert d.text is None and d.selected_confidence is None
    assert d.alternatives[-1]['text']==last[0]


def test_cancellation_before_isolation_does_not_call_the_model_again():
    cancel=threading.Event();rgb,b=narrow_stroke_with_neighbour()
    class Reader(ThreeReads):
        def predict(self,crops):
            result=super().predict(crops)
            if self.calls==2:cancel.set()
            return result
    reader=Reader(('1',.99))
    with pytest.raises(ProcessingCancelled):recognize(rgb,[b],reader,retry_one=True,cancel=cancel)
    assert reader.calls==2
