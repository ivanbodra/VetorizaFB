"""Native large GeoTIFF loading avoids Pillow's unrelated pixel-count guard."""
import warnings

import numpy as np
from PIL import Image
import pytest
import rasterio
from rasterio.transform import from_origin

from vetorizafb.pipeline import read_chart,chart_dpi


@pytest.mark.parametrize('kind',['rgb','palette','gray'])
def test_geotiff_load_keeps_pixels_crs_transform_dpi_without_pillow(tmp_path,monkeypatch,kind):
    path=tmp_path/'chart.tif';affine=from_origin(123,456,2,3)
    band=np.arange(80,dtype=np.uint8).reshape(8,10)
    rgb=np.stack((band,255-band,band//2),axis=2)
    with rasterio.open(path,'w',driver='GTiff',width=10,height=8,count=3 if kind=='rgb' else 1,dtype='uint8',crs='EPSG:3857',transform=affine) as ds:
        ds.update_tags(TIFFTAG_XRESOLUTION='300',TIFFTAG_YRESOLUTION='300',TIFFTAG_RESOLUTIONUNIT='2 (pixels/inch)')
        if kind=='rgb':ds.write(rgb.transpose(2,0,1))
        else:
            ds.write(band,1)
            if kind=='palette':ds.write_colormap(1,{i:(i,255-i,i//2,255) for i in range(256)})
    # Even a small TIFF exceeds this deliberately low guard. No Pillow read or
    # global guard override may be involved; other image opens stay protected.
    monkeypatch.setattr(Image,'MAX_IMAGE_PIXELS',10)
    monkeypatch.setattr(Image,'open',lambda *args,**kwargs:pytest.fail('GeoTIFF must not be reopened through Pillow'))
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        got,transform,crs,dpi=read_chart(path)
    expected=rgb if kind in ('rgb','palette') else np.repeat(band[:,:,None],3,axis=2)
    assert np.array_equal(got,expected)
    assert transform==affine and crs.to_epsg()==3857 and dpi==300
    assert Image.MAX_IMAGE_PIXELS==10


@pytest.mark.parametrize('tags,expected',[
    ({'TIFFTAG_XRESOLUTION':'300','TIFFTAG_YRESOLUTION':'600','TIFFTAG_RESOLUTIONUNIT':'2 (pixels/inch)'},450),
    ({'TIFFTAG_XRESOLUTION':'100/1','TIFFTAG_YRESOLUTION':'100','TIFFTAG_RESOLUTIONUNIT':'3 (pixels/cm)'},254),
    ({'TIFFTAG_XRESOLUTION':'300','TIFFTAG_YRESOLUTION':'300'},300),
    ({'TIFFTAG_XRESOLUTION':'300','TIFFTAG_YRESOLUTION':'300','TIFFTAG_RESOLUTIONUNIT':'1 (unitless)'},None),
    ({'TIFFTAG_XRESOLUTION':'0','TIFFTAG_YRESOLUTION':'300'},None),
    ({'TIFFTAG_XRESOLUTION':'nan','TIFFTAG_YRESOLUTION':'300'},None),
    ({'TIFFTAG_XRESOLUTION':'300/0','TIFFTAG_YRESOLUTION':'300'},None),
    ({},None),
])
def test_tiff_resolution_units_and_missing_metadata(tags,expected):
    assert chart_dpi(tags)==expected
