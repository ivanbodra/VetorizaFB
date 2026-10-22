"""Reproducible extraction with explicit metadata and exactly three XYZ columns."""
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time

import cv2
import numpy as np
from PIL import Image
import rasterio

from .core import Config, group, recognize, segment
from .geospatial import transform_points
from .ocr import PaddleRecognizer


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def read_chart(path):
    with rasterio.open(path) as ds:
        if ds.count < 3:
            # Pillow expands a color palette correctly; uint8 single-band imagery
            # is supported too. Other radiometric formats need an explicit policy.
            if ds.dtypes[0] != 'uint8':
                raise ValueError("Only 8-bit chart imagery is currently supported")
            with Image.open(path) as im:
                rgb = np.asarray(im.convert('RGB'))
        else:
            arr = ds.read([1,2,3])
            if arr.dtype != np.uint8:
                raise ValueError("Only 8-bit chart imagery is currently supported")
            rgb = arr.transpose(1,2,0)
        dpi = None
        with Image.open(path) as im:
            val = im.info.get('dpi')
            if val and len(val) >= 2 and min(val) > 0:
                dpi = float(sum(val[:2])/2)
        return rgb.copy(), ds.transform, ds.crs, dpi


def extract(path, output_dir, config=None, model_name="PP-OCRv6_small_rec",
            model_dir=None, device="cpu", target_crs="EPSG:4326", engine=None):
    start = time.perf_counter()
    rgb, affine, source_crs, dpi = read_chart(path)
    if source_crs is None:
        raise ValueError("The input has no CRS; geographic XYZ export is blocked")
    if config is None:
        if dpi is None:
            raise ValueError("Input has no DPI metadata; supply an explicit configuration")
        config = Config(dpi=dpi)
    boxes = segment(rgb, config)
    engine = engine or PaddleRecognizer(model_name, model_dir, device)
    digits = recognize(rgb, boxes, engine)
    soundings = group(digits, config)
    xy = transform_points([(s.pixel_x,s.pixel_y) for s in soundings],
                          affine, source_crs, target_crs)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(path).stem
    xyz_path, csv_path = out/f'{stem}.xyz', out/f'{stem}.csv'
    # All these are unreviewed candidates, clearly identified in the metadata.
    with open(xyz_path,'w',encoding='utf-8') as f:
        for (x,y),s in zip(xy,soundings):
            if not np.isfinite([x,y,s.depth]).all():
                raise ValueError("Invalid XYZ value")
            f.write(f'{x:.10f} {y:.10f} {s.depth:.1f}\n')
    rows = [dict(asdict(s), x=x,y=y) for (x,y),s in zip(xy,soundings)]
    fields = ['pixel_x','pixel_y','depth','confidence','bounds','digit_ids',
              'interpretation','review_status','x','y']
    with open(csv_path,'w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    (out/f'{stem}.digits.json').write_text(json.dumps([asdict(d) for d in digits],indent=2))
    versions={}
    for package in ['paddleocr','paddlepaddle','numpy','rasterio','pyproj','opencv-python','opencv-contrib-python']:
        try: versions[package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError: pass
    meta={'input_name':Path(path).name,'input_sha256':sha256(path),
          'source_crs_wkt':source_crs.to_wkt(),'target_crs':target_crs,
          'z_convention':'metres, positive down, source chart vertical reference unchanged',
          'pixel_convention':'continuous pixel-edge coordinates; bbox centre; no extra 0.5',
          'model':model_name,'config':asdict(config),'packages':versions,
          'timestamp_utc':datetime.now(timezone.utc).isoformat(),
          'boxes':len(boxes),'recognized_digits':sum(d.text is not None for d in digits),
          'soundings':len(soundings),'elapsed_seconds':time.perf_counter()-start,
          'status':'unreviewed candidates; not a complete cartographic classification'}
    (out/f'{stem}.metadata.json').write_text(json.dumps(meta,indent=2))
    preview=rgb.copy()
    for s in soundings:
        x1,y1,x2,y2=map(int,s.bounds)
        cv2.rectangle(preview,(x1,y1),(x2,y2),(255,140,0),1)
        cv2.putText(preview,f'{s.depth:g}',(x1,max(10,y1-4)),cv2.FONT_HERSHEY_SIMPLEX,.4,(255,0,0),1)
    Image.fromarray(preview).save(out/f'{stem}.preview.jpg')
    return meta
