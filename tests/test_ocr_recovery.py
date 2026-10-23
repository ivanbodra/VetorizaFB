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
