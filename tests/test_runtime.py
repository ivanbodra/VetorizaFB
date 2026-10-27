import os
from pathlib import Path
import subprocess
import sys

import pytest
import rasterio


def test_standalone_uses_own_proj_data_with_foreign_postgis_environment(tmp_path):
    if not (Path(rasterio.__file__).parent/'proj_data/proj.db').exists():
        pytest.skip('No wheel-provided PROJ database')
    foreign=tmp_path/'foreign';foreign.mkdir();(foreign/'proj.db').write_bytes(b'incompatible database')
    environment=dict(os.environ,PROJ_DATA=str(foreign),PROJ_LIB=str(foreign),GDAL_DATA=str(foreign))
    environment.pop('VETORIZAFB_KEEP_GIS_ENV',None)
    code='from vetorizafb.runtime import configure_gis_runtime; configure_gis_runtime(); import rasterio; print(rasterio.crs.CRS.from_epsg(3857).to_epsg())'
    result=subprocess.run([sys.executable,'-c',code],env=environment,text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='3857'
