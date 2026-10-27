import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import Affine
from experiments.fb_v5.windowed import angle, load_reference, owned, project_reference, tiles


def test_dms_axis_and_range():
    assert angle('043-12-00,000W',True) == pytest.approx(-43.2)
    for text, axis in [('043-60-00W',True),('043-00-60W',True),('181-00-00W',True),('043-00-00W',False)]:
        with pytest.raises(ValueError): angle(text,axis)


def test_reference_preserves_duplicates(tmp_path):
    path=tmp_path/'ref.txt'
    path.write_text('Longitude;Latitude;Depth\n043-00-00W;23-00-00S;10.30 m\n043-00-00W;23-00-00S;10.30 m\n')
    records=load_reference(path)
    assert len(records)==2 and records[0]['depth']=='10.30'
    assert records[0]['id'] != records[1]['id']


def test_rotated_pixel_transform_and_half_open_extent():
    affine=Affine(.001,.0001,-43,.0001,-.001,-23)
    x,y=affine*(4.5,6.5)
    with MemoryFile() as mem:
        with mem.open(driver='GTiff',width=10,height=10,count=1,dtype='uint8',crs='EPSG:4326',transform=affine) as ds:
            output=project_reference([dict(longitude=x,latitude=y)],'EPSG:4326',ds)
    assert output[0]['pixel']==pytest.approx([4.5,6.5])
    assert output[0]['inside']


def test_tile_ownership_covers_every_pixel_once():
    coverage=np.zeros((301,503),dtype=int)
    for core,read in tiles(503,301,128,20):
        x,y,x2,y2=core
        coverage[y:y2,x:x2]+=1
        assert read[0]<=x and read[1]<=y and read[2]>=x2 and read[3]>=y2
    assert np.all(coverage==1)
    assert owned([126,0,130,4],(128,0,256,128))
    assert not owned([126,0,130,4],(0,0,128,128))
