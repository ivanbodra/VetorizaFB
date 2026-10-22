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
