"""Detection-only preview. Does not import, initialize or call an OCR engine."""
import argparse
from dataclasses import asdict
from pathlib import Path
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .poc import (PrepareOptions, StageCache, atomic_json, file_digest,
                  image_digest, morph_regions, prepare, stage_keys)


def preview(path, output, roi=None, cache_root=None):
    start = time.perf_counter()
    # Rasterio gives explicit CRS/affine metadata; original source is untouched.
    import rasterio
    from rasterio.windows import Window
    with rasterio.open(path) as ds:
        if ds.dtypes[0] != "uint8" or ds.count < 3:
            raise ValueError("This proof of concept expects the supplied RGB uint8 sheet")
        x, y, w, h = roi or (0, 0, ds.width, ds.height)
        if min(x, y) < 0 or min(w, h) < 1 or x+w > ds.width or y+h > ds.height:
            raise ValueError("ROI outside source raster")
        if w*h > 16_000_000:
            raise ValueError("Use an ROI up to 16 MP in this proof of concept")
        rgb = ds.read([1, 2, 3], window=Window(x, y, w, h)).transpose(1, 2, 0).copy()
        affine = list(ds.transform)
        crs = str(ds.crs)
    opts = PrepareOptions()
    key = stage_keys(dict(source=file_digest(path), roi=[x, y, w, h], pixels=image_digest(rgb)),
                     asdict(opts), "morph-lines", None, None, None)
    cache = StageCache(cache_root or Path(output)/"cache")
    prepared, prep_hit = cache.get_or_compute("prepared", key["prepared"], lambda: prepare(rgb, opts))
    regions, detection_hit = cache.get_or_compute("regions", key["regions"], lambda: morph_regions(prepared))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    canvas = Image.fromarray(rgb)
    draw = ImageDraw.Draw(canvas)
    for r in regions:
        draw.rectangle(r["box"], outline="#00a249", width=1)
    canvas.save(output/"candidates_native.png")
    canvas.thumbnail((1800, 1000))
    canvas.save(output/"candidates_overview.png")
    original = Image.fromarray(rgb)
    original.thumbnail((1800, 1000))
    original.save(output/"source_overview.png")
    Image.fromarray(prepared["normalized"]).save(output/"normalized.png")
    Image.fromarray(prepared["lines"]).save(output/"straight_lines.png")
    global_regions = [dict(r, box=[r["box"][0]+x, r["box"][1]+y, r["box"][2]+x, r["box"][3]+y]) for r in regions]
    result = dict(source_sha256=file_digest(path), roi=[x, y, w, h], crs=crs, source_affine=affine,
                  coordinate_convention="global native pixel-edge xyxy; not map coordinates",
                  candidate_count=len(regions), regions=global_regions,
                  options=asdict(opts), seconds=time.perf_counter()-start,
                  cache_hits=dict(prepared=prep_hit, regions=detection_hit), recognition_executed=False,
                  anchor_status="No sounding anchor assigned; no XYZ export in PoC")
    atomic_json(output/"preview.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--roi", type=int, nargs=4, metavar=("X", "Y", "W", "H"))
    args = parser.parse_args()
    cv2.setNumThreads(2)
    result = preview(args.input, args.output, args.roi)
    print({k: result[k] for k in ("candidate_count", "seconds", "cache_hits", "recognition_executed")})


if __name__ == "__main__":
    main()
