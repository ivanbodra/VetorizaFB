import json
import numpy as np
import rasterio
from rasterio.transform import from_origin

from vetorizafb.core import Config
from vetorizafb.pipeline import extract


def test_geotiff_to_xyz_preserves_coordinates_and_trace(tmp_path):
    path=tmp_path/'chart.tif'
    rgb=np.full((3,100,100),255,np.uint8);rgb[:,20:45,20:30]=0
    with rasterio.open(path,'w',driver='GTiff',width=100,height=100,count=3,dtype='uint8',
                       crs='EPSG:3857',transform=from_origin(100,200,2,2)) as ds:ds.write(rgb)
    class Reader:
        def predict(self,crops):return [('0',.99) for _ in crops]
    meta=extract(path,tmp_path/'out',Config(segmentation='black'),target_crs='EPSG:3857',engine=Reader(),model_name='test-double')
    row=(tmp_path/'out/chart.xyz').read_text().strip().split()
    assert len(row)==3 and list(map(float,row))==[150,135,0]
    assert meta['status'].startswith('unreviewed')
    assert json.loads((tmp_path/'out/chart.digits.json').read_text())[0]['raw_text']=='0'
