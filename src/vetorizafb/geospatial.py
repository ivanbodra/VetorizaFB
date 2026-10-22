"""Pixel-edge coordinates -> declared CRS, without an extra half-pixel offset."""
import numpy as np
from pyproj import CRS, Transformer


def transform_points(points, affine, source_crs, target_crs="EPSG:4326"):
    if source_crs is None:
        raise ValueError("A valid source CRS is required for geographic export")
    source, target = CRS.from_user_input(source_crs), CRS.from_user_input(target_crs)
    xy = [(affine.a*float(x)+affine.b*float(y)+affine.c,
           affine.d*float(x)+affine.e*float(y)+affine.f) for x,y in points]
    if not xy:
        return []
    tr = Transformer.from_crs(source, target, always_xy=True)
    x, y = tr.transform(*zip(*xy), errcheck=True)
    result = list(zip(x,y))
    if not np.isfinite(np.asarray(result)).all():
        raise ValueError("Nonfinite transformed coordinates")
    return result
