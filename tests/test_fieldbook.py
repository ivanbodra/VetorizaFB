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
    config=replace(cfg(),decimal_height_ratio=ratio,decimal_drop=.4,tol_x=12,tol_y=10)
    for readings in (digits,list(reversed(digits))):
        result=group(readings,config)
        assert len(result)==1 and result[0].depth==35.8
        assert result[0].digit_ids==[1404,1418,1429]


def test_real_project_annotations_do_not_suppress_40_8_and_41():
    digits=[d(2798,1889,31,63,'4',1302),d(2839,1890,22,61,'0',1321),
            d(2868,1948,15,31,'8',1336),d(2871,1982,13,16,'2',1341),
            d(2886,1890,28,64,'4',1352),d(2923,1890,5,63,'1',1376),
            d(2887,1985,10,14,'2',1353),d(2907,1991,15,8,'2',1366)]
    result=group(digits,replace(cfg(),decimal_drop=.4,tol_x=12,tol_y=10))
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


@pytest.mark.parametrize('reverse',[False,True])
def test_adjacent_33_soundings_do_not_form_333(reverse):
    # Exact boxes from the reported FB project, including the OCR letter l.
    digits=[d(3288,85,29,66,'3',1568),d(3318,84,25,67,'3',1581),
            d(3345,155,4,25,'l',1592),d(3356,88,28,67,'3',1599),
            d(3382,88,26,66,'3',1615),d(3406,150,15,24,'3',1624)]
    if reverse:digits.reverse()
    result=group(digits,replace(cfg(),tol_x=12,tol_y=10,decimal_drop=.4))
    assert [(s.depth,s.digit_ids) for s in result]==[(33,[1568,1581]),(33.3,[1599,1615,1624])]


def test_small_annotation_fragments_stay_available_without_isolated_soundings():
    from vetorizafb.fieldbook import group as fb_group
    digits=[d(2798,1889,31,63,'4',1302),d(2839,1890,22,61,'0',1321),
            d(2868,1948,15,31,'8',1336),d(2871,1982,13,16,'2',1341),
            d(2886,1890,28,64,'4',1352),d(2923,1890,5,63,'1',1376),
            d(2887,1985,10,14,'2',1353),d(2907,1991,15,8,'2',1366)]
    notes={}
    result=fb_group(digits,replace(cfg(),decimal_drop=.4,tol_x=12,tol_y=10),diagnostics=notes)
    assert sorted(s.depth for s in result)==[40.8,41]
    assert all(notes[i]!='Incluída em sondagem' for i in (1341,1353,1366))


def test_isolated_small_sounding_without_larger_neighbour_is_kept():
    assert [s.depth for s in group([d(10,10,10,20,'5',0)],cfg())]==[5]


def test_three_digit_integer_with_close_spacing_is_kept():
    digits=[d(10,10,15,40,'1',0),d(27,10,15,40,'2',1),d(44,10,15,40,'3',2)]
    assert [s.depth for s in group(digits,cfg())]==[123]


@pytest.mark.parametrize('ratio',[.6,.95])
def test_real_project_31_4_and_31_9_with_user_spacing(ratio):
    digits=[d(2957,91,26,62,'3',1394),d(2994,90,7,59,'1',1407),d(3003,160,17,29,'4',1415),
            d(3048,102,27,60,'3',1435),d(3079,97,7,63,'1',1454),d(3095,150,14,25,'9',1462)]
    config=replace(cfg(),tol_x=12,tol_y=10,decimal_drop=.4,decimal_height_ratio=ratio)
    result=group(digits,config)
    assert [(s.depth,s.digit_ids) for s in result]==[(31.4,[1394,1407,1415]),(31.9,[1435,1454,1462])]


def test_horizontal_distance_has_no_hidden_height_cap():
    digits=[d(10,10,15,40,'3',0),d(45,10,15,40,'5',1)]
    assert [s.depth for s in group(digits,replace(cfg(),tol_x=20))]==[35]
    assert [s.depth for s in group(digits,replace(cfg(),tol_x=19))]==[3,5]


def test_decimal_height_has_no_hidden_75_percent_cap():
    digits=[d(10,10,30,40,'35',0),d(42,45,10,32,'8',1)]
    assert group(digits,replace(cfg(),decimal_height_ratio=.85))[0].depth==35.8
    assert all(s.depth!=35.8 for s in group(digits,replace(cfg(),decimal_height_ratio=.75)))


def test_decimal_horizontal_and_vertical_limits_are_configurable():
    digits=[d(10,10,30,40,'35',0),d(52,44,10,16,'8',1)]
    assert group(digits,replace(cfg(),fb_decimal_distance=.5))[0].depth==35.8
    assert all(s.depth!=35.8 for s in group(digits,replace(cfg(),fb_decimal_distance=.2)))
    digits=[d(10,10,30,40,'35',0),d(40,64,10,16,'8',1)]
    assert group(digits,replace(cfg(),fb_decimal_max_gap=.4))[0].depth==35.8
    assert all(s.depth!=35.8 for s in group(digits,replace(cfg(),fb_decimal_max_gap=.2)))


def test_decimal_top_overlap_is_configurable():
    digits=[d(10,10,30,40,'35',0),d(40,40,10,20,'8',1)]
    assert group(digits,replace(cfg(),fb_decimal_top_overlap=.25))[0].depth==35.8
    assert all(s.depth!=35.8 for s in group(digits,replace(cfg(),fb_decimal_top_overlap=.1)))


def test_integer_height_and_overlap_are_configurable():
    digits=[d(10,10,20,40,'3',0),d(30,24,15,26,'5',1)]
    assert group(digits,replace(cfg(),fb_integer_height_ratio=.6))[0].depth==35
    assert all(s.depth!=35 for s in group(digits,replace(cfg(),fb_integer_height_ratio=.8)))
    digits=[d(10,10,20,40,'3',0),d(26,10,20,40,'5',1)]
    assert group(digits,replace(cfg(),fb_overlap=.25))[0].depth==35
    assert all(s.depth!=35 for s in group(digits,replace(cfg(),fb_overlap=.1)))


def test_keep_small_switch_preserves_annotation_candidates_for_review():
    digits=[d(10,10,30,60,'40',0),d(20,98,10,15,'2',1)]
    assert [s.depth for s in group(digits,cfg())]==[40]
    assert sorted(s.depth for s in group(digits,replace(cfg(),fb_keep_small=True)))==[2,40]


@pytest.mark.parametrize('key,value',[
    ('fb_integer_height_ratio',0),('fb_integer_height_ratio',1.1),
    ('fb_overlap',1),('fb_decimal_distance',-1),('fb_decimal_top_overlap',float('nan')),
    ('fb_decimal_max_gap',-1),('fb_decimal_left',-1),('fb_ambiguity_margin',-1),
    ('fb_small_ratio',0),('fb_keep_small','yes')])
def test_fb_parameter_validation(key,value):
    with pytest.raises(ValueError):replace(cfg(),**{key:value})


class RetryEngine:
    def __init__(self,*batches):self.batches=list(batches);self.shapes=[]
    def predict(self,crops):
        self.shapes.append([c.shape for c in crops])
        return self.batches.pop(0)


def test_fb_retry_flags_off_make_only_initial_reading():
    engine=RetryEngine([('l',.55)])
    result=recognize(np.full((60,60,3),255,np.uint8),[Box(10,10,4,30)],engine)
    assert len(engine.shapes)==1 and result[0].raw_text=='l'
    assert result[0].alternatives==[]


def test_fb_retry_one_recovers_thin_stroke_and_preserves_original():
    engine=RetryEngine([('l',.55)],[('1',.93)])
    progress=[]
    result=recognize(np.full((60,60,3),255,np.uint8),[Box(10,10,4,30)],engine,
                     retry_one=True,progress=lambda a,b,c:progress.append((a,b,c)))
    one=result[0]
    assert one.raw_text=='l' and one.confidence==.55
    assert one.text=='1' and one.score==.93 and one.method=='fb_one_retry'
    assert one.alternatives==[dict(text='1',confidence=.93,method='fb_binary_padded_2x')]
    assert len(engine.shapes)==2 and all(len(p)==3 for p in progress)


def test_fb_retry_one_uses_tight_second_crop_for_empty_reading():
    engine=RetryEngine([('',0)],[('l',.9)],[('1',.94)])
    one=recognize(np.full((60,60,3),255,np.uint8),[Box(10,10,3,30)],engine,retry_one=True)[0]
    assert one.raw_text=='' and one.text=='1'
    assert [a['method'] for a in one.alternatives]==['fb_binary_padded_2x','fb_tight_padded_2x']
    assert engine.shapes[1]!=engine.shapes[2]


def test_fb_one_retry_does_not_guess_from_l_or_accept_other_digits():
    engine=RetryEngine([('l',.99)],[('7',.99)],[('l',.99)])
    one=recognize(np.full((60,60,3),255,np.uint8),[Box(10,10,3,30)],engine,retry_one=True)[0]
    assert one.text is None and one.raw_text=='l'
    assert len(one.alternatives)==2


def test_fb_one_retry_does_not_accept_low_score_one():
    engine=RetryEngine([('l',.55)],[('1',.7)],[('1',.79)])
    one=recognize(np.full((60,60,3),255,np.uint8),[Box(10,10,3,30)],engine,retry_one=True)[0]
    assert one.text is None


def test_fb_ambiguous_retry_accepts_multi_digit_without_truncation():
    from vetorizafb.fieldbook import token
    from dataclasses import asdict
    engine=RetryEngine([('S',.5),('42',.99)],[('35',.95)])
    result=recognize(np.full((80,100,3),255,np.uint8),[Box(10,10,30,40),Box(50,10,30,40)],
                     engine,retry=True)
    assert token(result[0])=='35' and result[0].raw_text=='S'
    assert result[0].text is None # CN still accepts only single digits.
    assert token(result[1])=='42' and not result[1].alternatives
    assert [len(shapes) for shapes in engine.shapes]==[2,1]
    saved=asdict(result[0]);saved['box']=Box(**saved['box'])
    assert token(Digit(**saved))=='35'


def test_fb_ambiguous_retry_improves_low_confidence_number_only():
    engine=RetryEngine([('36',.2)],[('35',.85)])
    from vetorizafb.fieldbook import token
    result=recognize(np.full((70,70,3),255,np.uint8),[Box(10,10,30,40)],engine,retry=True)
    assert token(result[0])=='35' and result[0].confidence==.2 and result[0].score==.85


def test_fb_one_flag_does_not_retry_wide_nonnumeric_reading():
    engine=RetryEngine([('S',.5)])
    recognize(np.full((70,70,3),255,np.uint8),[Box(10,10,30,40)],engine,retry_one=True)
    assert len(engine.shapes)==1


@pytest.mark.parametrize('score',[float('nan'),float('inf'),-.1,1.1])
def test_fb_retry_rejects_invalid_confidence(score):
    engine=RetryEngine([('l',.5)],[('1',score)])
    with pytest.raises(ValueError,match='Confiança'):
        recognize(np.full((60,60,3),255,np.uint8),[Box(10,10,4,30)],engine,retry_one=True)


def test_fb_retry_validates_count_and_cancellation():
    engine=RetryEngine([('l',.5)],[])
    with pytest.raises(ValueError,match='Quantidade'):
        recognize(np.full((60,60,3),255,np.uint8),[Box(10,10,4,30)],engine,retry_one=True)
    import threading
    from vetorizafb.core import ProcessingCancelled
    cancel=threading.Event()
    class Engine:
        def predict(self,crops):cancel.set();return [('l',.5)]
    with pytest.raises(ProcessingCancelled):
        recognize(np.full((60,60,3),255,np.uint8),[Box(10,10,4,30)],Engine(),retry_one=True,cancel=cancel)


def test_fb_directed_retry_can_isolate_ink_after_other_attempts_fail(monkeypatch):
    monkeypatch.setattr('vetorizafb.fieldbook.isolated_one_crop',lambda *a:np.full((70,30,3),255,np.uint8))
    engine=RetryEngine([('',0)],[('l',.7)],[('',0)],[('1',.96)])
    one=recognize(np.full((60,60,3),255,np.uint8),[Box(10,10,4,30)],engine,retry_one=True)[0]
    assert one.text=='1' and one.raw_text=='' and one.score==.96
    assert one.alternatives[-1]['method']=='fb_isolated_one_2x'


def test_fb_combined_flags_retry_union_without_touching_valid_tokens():
    engine=RetryEngine([('l',.55),('S',.4),('42',.99)],[('1',.92),('35',.95)])
    result=recognize(np.full((80,140,3),255,np.uint8),
        [Box(10,10,4,30),Box(35,10,30,40),Box(85,10,30,40)],engine,retry=True,retry_one=True)
    from vetorizafb.fieldbook import token
    assert [token(d) for d in result]==['1','35','42']
    assert [len(shapes) for shapes in engine.shapes]==[3,2]
