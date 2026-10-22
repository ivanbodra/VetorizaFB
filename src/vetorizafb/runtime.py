"""Isolate standalone entry points from foreign PostGIS/QGIS data directories."""
import importlib.util
import os
from pathlib import Path


def configure_gis_runtime():
    """Prefer wheel-provided data, only in this process and before GIS imports.

    A source/Conda installation without bundled data is left alone. Advanced
    users who intentionally supply custom grids can opt out explicitly.
    """
    if os.environ.get('VETORIZAFB_KEEP_GIS_ENV') == '1':
        return {}
    spec = importlib.util.find_spec('rasterio')
    if spec is None or spec.origin is None:
        return {}
    package = Path(spec.origin).parent
    if not (package/'proj_data/proj.db').is_file():
        return {}
    removed = {}
    for name in ('PROJ_LIB','PROJ_DATA'):
        if name in os.environ:
            removed[name] = os.environ.pop(name)
    if (package/'gdal_data').is_dir() and 'GDAL_DATA' in os.environ:
        removed['GDAL_DATA'] = os.environ.pop('GDAL_DATA')
    return removed
