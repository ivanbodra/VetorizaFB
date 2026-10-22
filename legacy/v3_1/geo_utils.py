# geo_utils.py
from osgeo import gdal, osr
import numpy as np
import pandas as pd

def get_geotransform(image_path):
    """
    Retorna (geo_transform, srs_wkt).
    geo_transform = (origin_x, pixel_width, rot_x, origin_y, rot_y, pixel_height)
    """
    ds = gdal.Open(image_path)
    if ds is None:
        raise FileNotFoundError(f"Não foi possível abrir o arquivo GeoTIFF: {image_path}")
    gt = ds.GetGeoTransform()
    srs_wkt = ds.GetProjection()
    return gt, srs_wkt

def _pixels_to_crsxy(px, py, gt, center=True):
    """
    Converte arrays de col/lin (px, py) -> coordenadas no CRS do raster (x,y),
    usando a matriz completa (com rotação) e opcionalmente o centro do pixel.
    """
    # GeoTransform:
    # Xgeo = GT0 + Col*GT1 + Row*GT2
    # Ygeo = GT3 + Col*GT4 + Row*GT5
    if center:
        px = np.asarray(px, dtype=np.float64) + 0.5
        py = np.asarray(py, dtype=np.float64) + 0.5
    else:
        px = np.asarray(px, dtype=np.float64)
        py = np.asarray(py, dtype=np.float64)

    x = gt[0] + px * gt[1] + py * gt[2]
    y = gt[3] + px * gt[4] + py * gt[5]
    return x, y

def _crsxy_to_lonlat(xs, ys, srs_wkt):
    """
    Converte listas/arrays de (x,y) no CRS do raster para WGS84 (lon,lat) usando OSR.
    """
    src = osr.SpatialReference()
    src.ImportFromWkt(srs_wkt)
    # if já geográfico (lon/lat), apenas retorna os próprios valores
    if src.IsGeographic():
        return np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)

    dst = osr.SpatialReference()
    dst.ImportFromEPSG(4326)  # WGS84
    ct = osr.CoordinateTransformation(src, dst)

    # OSR não é vetorizado; convertemos em lista de tuplas
    out_lon = np.empty(len(xs), dtype=np.float64)
    out_lat = np.empty(len(xs), dtype=np.float64)
    for i, (xx, yy) in enumerate(zip(xs, ys)):
        lon, lat, _ = ct.TransformPoint(float(xx), float(yy))
        out_lon[i] = lon
        out_lat[i] = lat
    return out_lon, out_lat

def apply_geotransform(df, geo_transform, srs_wkt=None, add_lonlat=True, pixel_center=True):
    """
    Adiciona colunas no CRS do raster e, opcionalmente, lon/lat (WGS84).

    Entradas esperadas no df: 'pixel_x' (coluna), 'pixel_y' (linha).
    Saídas adicionadas:
      - 'crs_x', 'crs_y'  (sempre)
      - 'lon', 'lat'      (se add_lonlat=True e srs_wkt informado)

    Observações:
      - Usa a matriz completa do GeoTransform (com rotação).
      - Usa o centro do pixel por padrão (pixel_center=True).
    """
    if 'pixel_x' not in df.columns or 'pixel_y' not in df.columns:
        raise KeyError("DataFrame deve conter colunas 'pixel_x' e 'pixel_y'.")

    # Converte todos de uma vez (vetorizado)
    xs, ys = _pixels_to_crsxy(df['pixel_x'].to_numpy(), df['pixel_y'].to_numpy(),
                              geo_transform, center=pixel_center)
    df = df.copy()
    df['crs_x'] = xs
    df['crs_y'] = ys

    # Opcional: adiciona lon/lat (WGS84)
    if add_lonlat and srs_wkt:
        lon, lat = _crsxy_to_lonlat(xs, ys, srs_wkt)
        df['lon'] = lon
        df['lat'] = lat

    return df
