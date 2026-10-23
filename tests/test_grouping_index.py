from dataclasses import asdict
import random

import pytest

from vetorizafb.core import Box,Config,Digit,group
from fixtures.pre_index_group import reference_group


@pytest.mark.parametrize('mode',['fixed','relative'])
def test_y_index_preserves_pre_index_group_decisions(mode):
    rng=random.Random(20261022)
    for _ in range(60):
        cfg=Config(grouping=mode,dpi=rng.choice([300,600]),tol_x=rng.choice([10,30,60]),tol_y=rng.choice([0,6,12]))
        digits=[Digit(Box(rng.randint(0,250),rng.randint(0,250),rng.randint(4,20),rng.randint(10,40)),
                      rng.choice(list('0123456789')+['?','11','l']),rng.choice([.2,.7,.99]),i)
                for i in range(80)]
        assert [asdict(s) for s in group(digits,cfg)]==[asdict(s) for s in reference_group(digits,cfg)]


def test_large_vertical_column_remains_separate():
    digits=[Digit(Box(0,i*100,12,20),str(i%10),.99,i) for i in range(6000)]
    result=group(digits,Config())
    assert len(result)==6000 and all(len(s.digit_ids)==1 for s in result)
