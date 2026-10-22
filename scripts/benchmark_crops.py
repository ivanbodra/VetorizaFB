"""Diagnostic OCR benchmark on fixed, visually inspected chart crops.

No input images or model weights are committed. The numeric annotations were
read by the assistant and require independent review before becoming ground truth.
"""
import argparse
from dataclasses import asdict
import importlib.metadata
import json
from pathlib import Path
import time

from PIL import Image
import rasterio
from rasterio.windows import Window

from vetorizafb.core import Config, group, recognize, segment
from vetorizafb.ocr import PaddleRecognizer
from vetorizafb.pipeline import sha256


def main():
    p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,required=True)
    p.add_argument('--model',required=True);p.add_argument('--model-dir')
    p.add_argument('--reference',type=Path,default=Path(__file__).resolve().parents[1]/'docs/experiments/crop_reference.json')
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();reference=json.loads(args.reference.read_text())
    engine=PaddleRecognizer(args.model,args.model_dir)
    records=[];inputs={};start=time.perf_counter()
    for sample in reference['samples']:
        path=args.data_dir/sample['image']
        if sample['image'] not in inputs:
            inputs[sample['image']]={'sha256':sha256(path),'size_bytes':path.stat().st_size}
        x1,y1,x2,y2=sample['box']
        with rasterio.open(path) as ds:
            rgb=ds.read([1,2,3],window=Window(x1,y1,x2-x1,y2-y1)).transpose(1,2,0)
        with Image.open(path) as im:dpi=float(im.info['dpi'][0])
        full_text,full_confidence=engine.predict([rgb])[0]
        runs={}
        for segmentation in ['legacy','black']:
            cfg=Config(dpi=dpi,segmentation=segmentation)
            boxes=segment(rgb,cfg);digits=recognize(rgb,boxes,engine)
            for grouping in ['fixed','relative']:
                cfg.grouping=grouping
                sounding=group(digits,cfg);values=[s.depth for s in sounding]
                expected=sample['expected_depth']
                correct=(not values) if expected is None else (len(values)==1 and abs(values[0]-expected)<1e-8)
                runs[f'{segmentation}_{grouping}']={'values':values,'correct':correct,
                    'config':asdict(cfg),'digits':[asdict(d) for d in digits]}
        records.append(dict(sample,full_crop_ocr={'text':full_text,'confidence':full_confidence},runs=runs))
        print(sample['id'],args.model,'expected',sample['expected_depth'],
              'whole',repr(full_text),'legacy',runs['legacy_relative']['values'],'black',runs['black_relative']['values'],flush=True)
    positives=[r for r in records if r['kind']=='sounding']
    negatives=[r for r in records if r['kind']!='sounding']
    summary={mode:{'correct_positive_crops':sum(r['runs'][mode]['correct'] for r in positives),
                   'positive_crops':len(positives),
                   'false_positive_negative_crops':sum(not r['runs'][mode]['correct'] for r in negatives),
                   'negative_crops':len(negatives)} for mode in ['legacy_fixed','legacy_relative','black_fixed','black_relative']}
    packages={p:importlib.metadata.version(p) for p in ['paddleocr','paddlepaddle','paddlex']}
    weights={}
    if args.model_dir:
        weights={f.name:sha256(f) for f in Path(args.model_dir).iterdir() if f.is_file()}
    result={'model':args.model,'packages':packages,'model_files_sha256':weights,
            'scope':reference['scope'],'input_files':inputs,'summary':summary,
            'elapsed_seconds_excluding_model_load':time.perf_counter()-start,'records':records}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
