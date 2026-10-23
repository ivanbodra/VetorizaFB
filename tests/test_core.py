import pytest
import numpy as np
from affine import Affine

from vetorizafb.core import Box, Config, Digit, group, recognize, segment
from vetorizafb.geospatial import transform_points


def d(text,x=0,y=0,w=12,h=20,index=0,confidence=.99):
    return Digit(Box(x,y,w,h),text,confidence,index)


def test_zero_is_a_valid_digit():
    assert group([d('0')],Config())[0].depth == 0


def test_unrecognized_digit_does_not_remove_valid_digits():
    result=group([d('1'),d('?',100),d('2',15,index=2)],Config())
    assert [s.depth for s in result] == [12]


@pytest.mark.parametrize('text',['11','l','-','', '3.5'])
def test_multichar_and_nonnumeric_readings_are_not_truncated(text):
    assert d(text).text is None


def test_subscript_and_bbox_centre():
    result=group([d('2',0),d('3',15,index=1),d('5',30,8,9,14,index=2)],Config())
    assert len(result)==1 and result[0].depth==23.5
    assert result[0].bounds==(0,0,39,22)
    assert (result[0].pixel_x,result[0].pixel_y)==(19.5,11)


def test_integer_digits_on_same_baseline():
    assert group([d('2'),d('3',15,index=1)],Config())[0].depth==23


def test_relative_geometry_keeps_large_subscript_with_integer():
    digits=[d('8',0,0,28,36),d('7',34,19,21,29,index=1)]
    assert [s.depth for s in group(digits,Config(grouping='relative'))]==[8.7]
    assert [s.depth for s in group(digits,Config(grouping='fixed'))]==[8,7]


def test_confidence_is_not_increased_by_grouping():
    assert group([d('1',confidence=.5),d('2',15,index=1)],Config())[0].confidence==.5


def test_batch_order_and_raw_text_are_preserved():
    class Reader:
        def __init__(self):self.i=0
        def predict(self,crops):
            out=[(str((self.i+i)%10),.99) for i in range(len(crops))]
            self.i+=len(crops);return out
    out=recognize(np.full((30,100,3),255,np.uint8),[Box(i*10,1,5,20) for i in range(8)],Reader(),batch_size=3)
    assert [r.text for r in out]==list('01234567')
    assert [r.index for r in out]==list(range(8))


def test_missing_batch_results_fail_explicitly():
    class Reader:
        def predict(self,crops):return []
    with pytest.raises(RuntimeError):recognize(np.zeros((30,30,3),np.uint8),[Box(1,1,5,20)],Reader())


def test_segmentation_finds_dark_foreground_not_white_background():
    rgb=np.full((100,100,3),255,np.uint8);rgb[20:45,20:30]=0
    boxes=segment(rgb,Config(segmentation='black'))
    assert boxes==[Box(20,20,10,25)]


def test_dpi_scaling_retains_equivalent_symbol():
    large=np.full((100,100,3),255,np.uint8);large[20:44,20:30]=0
    small=large[::2,::2].copy()
    assert len(segment(large,Config(segmentation='black',dpi=600)))==1
    assert len(segment(small,Config(segmentation='black',dpi=300)))==1


def test_no_double_half_pixel_shift():
    assert transform_points([(10,20)],Affine(2,0,100,0,-2,200),'EPSG:3857','EPSG:3857')==[(120.,160.)]


def test_rotation_is_respected():
    assert transform_points([(10,20)],Affine(2,1,100,.5,-2,200),'EPSG:3857','EPSG:3857')==[(140.,165.)]


def test_geographic_datum_is_actually_transformed():
    point=transform_points([(-48,-15)],Affine.identity(),'EPSG:4225','EPSG:4326')[0]
    assert abs(point[0]+48)>1e-6 or abs(point[1]+15)>1e-6


def test_lon_lat_axis_order():
    xy=transform_points([(-48,-15)],Affine.identity(),'EPSG:4326','EPSG:4326')
    assert xy==[(-48.,-15.)]


def test_missing_crs_is_rejected():
    with pytest.raises(ValueError):transform_points([(1,2)],Affine.identity(),None)


@pytest.mark.parametrize('values',[{'dpi':0},{'tol_x':0},{'decimal_drop':-1},{'min_w':90},{'min_confidence':2}])
def test_invalid_configuration_is_rejected(values):
    with pytest.raises(ValueError):Config(**values)
