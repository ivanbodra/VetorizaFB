import argparse
from dataclasses import fields
import json

from .runtime import configure_gis_runtime
configure_gis_runtime()

from .core import Config
from .pipeline import extract


def main():
    p=argparse.ArgumentParser(description='Extract unreviewed sounding candidates from a GeoTIFF chart')
    p.add_argument('input');p.add_argument('--output-dir',required=True)
    p.add_argument('--model',default='PP-OCRv6_small_rec');p.add_argument('--model-dir')
    p.add_argument('--device',default='cpu');p.add_argument('--target-crs',default='EPSG:4326')
    p.add_argument('--config',help='JSON Config values; use explicit DPI for files without metadata')
    args=p.parse_args()
    config=None
    if args.config:
        with open(args.config) as f: config=Config(**json.load(f))
    try:
        result=extract(args.input,args.output_dir,config,args.model,args.model_dir,args.device,args.target_crs)
    except Exception as exc:
        p.exit(1,f'Extraction failed: {exc}\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
