"""Reproducible extraction with explicit metadata and exactly three XYZ columns."""
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import tempfile
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


def write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(data,f,indent=2,allow_nan=False)
            f.write('\n')
        os.replace(name,path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def export_results(path, output_dir, rgb, affine, source_crs, config, model_name,
                   boxes, digits, soundings, *, target_crs='EPSG:4326',stem=None,
                   status='unreviewed candidates; not a complete cartographic classification',
                   extra=None, start=None):
    """Validate and stage every file before publishing; metadata is published last.

    Multi-file rename is not a filesystem transaction. An interrupted publish
    can be detected through the hashes in the final metadata completion marker.
    """
    start = time.perf_counter() if start is None else start
    xy = transform_points([(s.pixel_x,s.pixel_y) for s in soundings],
                          affine, source_crs, target_crs)
    if not all(np.isfinite([x,y,s.depth]).all() for (x,y),s in zip(xy,soundings)):
        raise ValueError("Invalid XYZ value")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = stem or Path(path).stem
    versions={}
    for package in ['vetorizafb','paddleocr','paddlepaddle','numpy','rasterio','pyproj','opencv-python','opencv-contrib-python']:
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
          'status':status,'complete':True}
    from . import __version__
    meta['application_version'] = __version__
    extra = dict(extra or {})
    review_history = extra.pop('review_history',None)
    meta.update(extra)
    with tempfile.TemporaryDirectory(prefix='.vetorizafb-',dir=out) as temp:
        stage = Path(temp)
        with open(stage/f'{stem}.xyz','w',encoding='utf-8') as f:
            for (x,y),s in zip(xy,soundings):
                f.write(f'{x:.10f} {y:.10f} {s.depth:.1f}\n')
        fields = ['pixel_x','pixel_y','depth','confidence','bounds','digit_ids',
                  'interpretation','review_status','flags','x','y']
        with open(stage/f'{stem}.csv','w',newline='',encoding='utf-8') as f:
            writer = csv.DictWriter(f,fieldnames=fields)
            writer.writeheader()
            writer.writerows(dict(asdict(s),x=x,y=y) for (x,y),s in zip(xy,soundings))
        write_json_atomic(stage/f'{stem}.digits.json',[asdict(d) for d in digits])
        if review_history is not None:
            write_json_atomic(stage/f'{stem}.review.json',review_history)
        preview = rgb.copy()
        for s in soundings:
            x1,y1,x2,y2 = map(int,s.bounds)
            colour = (0,150,0) if s.review_status == 'accepted' else (255,140,0)
            cv2.rectangle(preview,(x1,y1),(x2,y2),colour,1)
            cv2.circle(preview,(round(s.pixel_x),round(s.pixel_y)),2,colour,1)
            cv2.putText(preview,f'{s.depth:g}',(x1,max(10,y1-4)),cv2.FONT_HERSHEY_SIMPLEX,.4,(255,0,0),1)
        Image.fromarray(preview).save(stage/f'{stem}.preview.jpg')
        del preview
        files = sorted(stage.iterdir())
        meta['output_sha256'] = {f.name:sha256(f) for f in files}
        meta['elapsed_seconds'] = time.perf_counter()-start
        write_json_atomic(stage/f'{stem}.metadata.json',meta)
        for file in files:
            os.replace(file,out/file.name)
        os.replace(stage/f'{stem}.metadata.json',out/f'{stem}.metadata.json')
    return meta


def extract(path, output_dir, config=None, model_name="PP-OCRv6_small_rec",
            model_dir=None, device="cpu", target_crs="EPSG:4326", engine=None):
    start = time.perf_counter()
    input_hash = sha256(path)
    rgb, affine, source_crs, dpi = read_chart(path)
    if source_crs is None:
        raise ValueError("The input has no CRS; geographic XYZ export is blocked")
    if config is None:
        if dpi is None:
            raise ValueError("Input has no DPI metadata; supply an explicit configuration")
        config = Config(dpi=dpi)
    boxes = segment(rgb, config)
    engine = engine or PaddleRecognizer(model_name, model_dir, device)
    digits = recognize(rgb,boxes,engine,config.ocr_batch_size,config.crop_padding,
                       retry=config.retry_ambiguous,retry_one=config.retry_one,min_confidence=config.min_confidence)
    soundings = group(digits,config)
    if sha256(path) != input_hash:
        raise ValueError("Input changed while processing")
    return export_results(path,output_dir,rgb,affine,source_crs,config,model_name,
                          boxes,digits,soundings,target_crs=target_crs,start=start)
