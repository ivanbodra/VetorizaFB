"""Pixel-edge coordinates -> declared CRS, without an extra half-pixel offset."""
import numpy as np
import math
from pyproj import CRS, Transformer


def offset_to_pixels(dx,dy,affine,source_crs,unit='pixels'):
    """Convert an incremental image/grid offset; metres are source-grid metres."""
    dx,dy=float(dx),float(dy)
    if not all(math.isfinite(v) for v in (dx,dy)):raise ValueError('O deslocamento deve ser finito')
    if unit=='pixels':return dx,dy
    if unit!='metres':raise ValueError('Unidade de deslocamento desconhecida')
    crs=CRS.from_user_input(source_crs)
    if not crs.is_projected or len(crs.axis_info)<2:
        raise ValueError('Deslocamento em metros exige CRS projetado; use pixels nesta carta')
    factors=[axis.unit_conversion_factor for axis in crs.axis_info[:2]]
    if any(f is None or not math.isfinite(f) or f<=0 for f in factors):
        raise ValueError('Unidades lineares do CRS desconhecidas')
    dx,dy=dx/factors[0],dy/factors[1]
    det=affine.a*affine.e-affine.b*affine.d
    if not math.isfinite(det) or det==0:raise ValueError('Transformação da carta não invertível')
    result=((affine.e*dx-affine.b*dy)/det,(-affine.d*dx+affine.a*dy)/det)
    if not all(math.isfinite(v) for v in result):raise ValueError('Deslocamento não finito')
    return result


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
