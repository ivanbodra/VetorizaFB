"""Windowed FB proposals and geographic reference audit; never executes OCR.

Run with --reference-crs explicitly: XYZ text has no embedded datum.
Point proximity is diagnostic only, never a detection/reading accuracy metric.
"""
import argparse
import csv
from dataclasses import asdict
from decimal import Decimal
import math
from pathlib import Path
import re
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw
from vetorizafb.runtime import configure_gis_runtime
configure_gis_runtime()
import rasterio
from rasterio.windows import Window
from rasterio.warp import transform

from .poc import (PrepareOptions, StageCache, atomic_json, file_digest,
                  morph_regions, prepare, stage_keys)


def angle(text, longitude):
    match = re.fullmatch(r'(\d+)-(\d+)-(\d+(?:[.,]\d+)?)([NSEW])', text.strip())
    if not match:
        raise ValueError(f'Invalid DMS coordinate: {text!r}')
    degrees, minutes, seconds, hemisphere = match.groups()
    degrees, minutes, seconds = int(degrees), int(minutes), float(seconds.replace(',', '.'))
    limit = 180 if longitude else 90
    if (hemisphere not in ('EW' if longitude else 'NS') or minutes >= 60 or seconds >= 60
            or degrees > limit or (degrees == limit and (minutes or seconds))):
        raise ValueError('DMS coordinate outside valid range/axis')
    return (-1 if hemisphere in 'SW' else 1)*(degrees+minutes/60+seconds/3600)


def load_reference(path):
    records = []
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, delimiter=';')
        if reader.fieldnames != ['Longitude', 'Latitude', 'Depth']:
            raise ValueError('Expected Longitude;Latitude;Depth')
        for index, row in enumerate(reader, 1):
            match = re.fullmatch(r'(\d+(?:[.,]\d+)?)\s*m', row['Depth'].strip())
            if not match:
                raise ValueError(f'Invalid depth at row {index}')
            depth = Decimal(match[1].replace(',', '.'))
            records.append(dict(id=index, longitude=angle(row['Longitude'], True),
                                latitude=angle(row['Latitude'], False), depth=str(depth)))
    return records


def project_reference(records, source_crs, dataset):
    if not dataset.crs:
        raise ValueError('Raster CRS missing')
    if not records:
        return []
    xs, ys = transform(source_crs, dataset.crs, [p['longitude'] for p in records],
                       [p['latitude'] for p in records])
    inverse = ~dataset.transform
    output = []
    for record, x, y in zip(records, xs, ys):
        col, row = inverse*(x, y)  # pixel-edge coordinates, including rotated rasters
        if not math.isfinite(col+row):
            raise ValueError('Nonfinite reference transformation')
        output.append(dict(record, pixel=[col, row], inside=0 <= col < dataset.width and 0 <= row < dataset.height))
    return output


def tiles(width, height, size, halo):
    if size < 128 or halo < 0 or 2*halo >= size:
        raise ValueError('Invalid tile/halo dimensions')
    for y in range(0, height, size):
        for x in range(0, width, size):
            core = (x, y, min(width, x+size), min(height, y+size))
            read = (max(0, x-halo), max(0, y-halo), min(width, x+size+halo), min(height, y+size+halo))
            yield core, read


def owned(box, core):
    cx, cy = (box[0]+box[2])/2, (box[1]+box[3])/2
    return core[0] <= cx < core[2] and core[1] <= cy < core[3]


def run(source, reference, output, reference_crs, glyph_height=32, tile_size=768):
    started = time.perf_counter()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    cache = StageCache(output/'cache')
    opts = PrepareOptions(glyph_height=glyph_height)
    source_hash = file_digest(source)
    regions, hits = [], dict(prepared=0, regions=0)
    with rasterio.open(source) as ds:
        if ds.count < 3 or ds.dtypes[:3] != ('uint8',)*3:
            raise ValueError('Expected RGB uint8 raster')
        points = project_reference(load_reference(reference), reference_crs, ds)
        halo = glyph_height*5
        tile_count = 0
        for core, read in tiles(ds.width, ds.height, tile_size, halo):
            x, y, x2, y2 = read
            rgb = ds.read([1, 2, 3], window=Window(x, y, x2-x, y2-y)).transpose(1, 2, 0).copy()
            keys = stage_keys(dict(sha256=source_hash, window=read), asdict(opts),
                              'windowed-morph-v1', None, None, None)
            prepared, hit = cache.get_or_compute('prepared', keys['prepared'], lambda: prepare(rgb, opts))
            hits['prepared'] += hit
            local, hit = cache.get_or_compute('regions', keys['regions'],
                lambda: morph_regions(prepared, glyph_height=glyph_height))
            hits['regions'] += hit
            for region in local:
                a, b, c, d = region['box']
                box = [a+x, b+y, c+x, d+y]
                if owned(box, core):
                    regions.append(dict(region, box=box))
            tile_count += 1
            print(f'tile {tile_count}: {len(regions)} proposals', flush=True)
        scale = min(1, 1800/ds.width, 1000/ds.height)
        canvas = Image.fromarray(ds.read([1, 2, 3], out_shape=(3, max(1,round(ds.height*scale)),
            max(1,round(ds.width*scale)))).transpose(1, 2, 0))
        draw = ImageDraw.Draw(canvas)
        for region in regions:
            draw.rectangle([v*scale for v in region['box']], outline='#00a060')
        for point in points:
            x, y = [v*scale for v in point['pixel']]
            draw.line((x-3,y,x+3,y), fill='#ff0050', width=1)
            draw.line((x,y-3,x,y+3), fill='#ff0050', width=1)
        canvas.save(output/'alignment_overview.png')
        metadata = dict(crs=str(ds.crs), affine=list(ds.transform), shape=[ds.height, ds.width])
    unique_xy = {(p['longitude'],p['latitude']) for p in points}
    result = dict(source_sha256=source_hash, reference_sha256=file_digest(reference),
        reference_crs=reference_crs, **metadata, options=asdict(opts), tile_size=tile_size,
        halo=halo, tiles=tile_count, cache_hits=hits, regions=regions, reference=points,
        reference_count=len(points), duplicate_coordinate_rows=len(points)-len(unique_xy),
        inside=sum(p['inside'] for p in points), candidate_count=len(regions),
        seconds=time.perf_counter()-started, recognition_executed=False,
        accuracy_status='Unscored: point-to-text registration and reference completeness require validation')
    atomic_json(output/'audit.json',result)
    return result


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('reference',type=Path)
    parser.add_argument('--reference-crs',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--glyph-height',type=int,default=32)
    parser.add_argument('--tile-size',type=int,default=768)
    args = parser.parse_args()
    cv2.setNumThreads(2)
    result = run(**vars(args))
    print({k:result[k] for k in ('reference_count','inside','candidate_count','seconds','cache_hits')})


if __name__ == '__main__':
    main()
