import numpy as np
import pytest
from PIL import Image
from vetorizafb.display import DisplayPyramid, read_preview


def test_three_levels_and_original_at_close_zoom(monkeypatch):
    pixels=np.zeros((800,1000,3),np.uint8)
    pixels[:,:,0]=np.arange(1000,dtype=np.uint16)%256
    pyramid=DisplayPyramid(pixels,(100,80))
    assert len(pyramid.levels)==2
    calls=[]
    original=Image.fromarray
    def recording(array,*a,**kw):
        calls.append(array.shape)
        return original(array,*a,**kw)
    monkeypatch.setattr(Image,'fromarray',recording)
    assert pyramid.render((100,100,500,500),.1).size==(40,40)
    assert not calls
    assert pyramid.render((100,100,150,140),2).size==(100,80)
    assert calls==[(40,50,3)]
    assert pyramid.pixels is pixels


def test_reduced_crop_keeps_original_coordinates():
    y,x=np.indices((800,1000))
    pixels=np.stack((x//4,y//4,np.zeros_like(x)),axis=2).astype(np.uint8)
    pyramid=DisplayPyramid(pixels,(100,80))
    result=np.asarray(pyramid.render((200,200,600,600),.1))
    assert result.shape==(40,40,3)
    assert abs(int(result[20,20,0])-101)<=2
    assert abs(int(result[20,20,1])-101)<=2


def test_small_image_does_not_allocate_reductions():
    pixels=np.zeros((40,60),np.uint8)
    pyramid=DisplayPyramid(pixels,(100,100))
    assert not pyramid.levels
    assert pyramid.render((5,5,20,30),1).mode=='L'


def test_preview_preserves_palette_colours(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    path=tmp_path/'palette.tif'
    with rasterio.open(path,'w',driver='GTiff',width=100,height=80,count=1,
                       dtype='uint8',crs='EPSG:3857',transform=from_origin(100,100,1,1)) as ds:
        ds.write(np.ones((80,100),np.uint8),1)
        ds.write_colormap(1,{0:(255,255,255),1:(10,30,80)})
    preview=read_preview(path,(10,8))
    assert preview.size==(10,8)
    assert preview.getpixel((0,0))==(10,30,80)
