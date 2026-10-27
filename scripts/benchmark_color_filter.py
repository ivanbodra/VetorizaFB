"""Record opt-in colour rejection on local charts; counts are not accuracy."""
import argparse
from dataclasses import asdict,replace
import json
from pathlib import Path
import time

from vetorizafb import __version__
from vetorizafb.core import Config,segment_details,yellow_background_fraction
from vetorizafb.pipeline import read_chart,sha256,write_json_atomic


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    reference=json.loads((Path(__file__).resolve().parents[1]/'docs/experiments/crop_reference.json').read_text())
    records=[]
    for name in ['21300plano.tif','1410geotiff.tif','1822geotiff.tif']:
        path=args.data_dir/name;rgb,_,_,dpi=read_chart(path);cfg=Config(dpi=dpi)
        start=time.perf_counter();_,_,before=segment_details(rgb,cfg)
        active=replace(cfg,exclude_yellow=True)
        _,_,after,rejected=segment_details(rgb,active,return_rejected=True)
        dropped=set(rejected)
        checks=[]
        for case in reference['samples']:
            if case['image']!=name or case['kind']!='sounding':continue
            a,b,c,d=case['box']
            boxes=[box for box in before if a<=box.center[0]<c and b<=box.center[1]<d]
            checks.append({'id':case['id'],'boxes_before':len(boxes),'boxes_rejected':sum(box in dropped for box in boxes)})
        record={'input':name,'sha256':sha256(path),'dpi':dpi,'config':asdict(active),
                'boxes_before':len(before),'boxes_after':len(after),'rejected_boxes':len(rejected),
                'elapsed_seconds':time.perf_counter()-start,'positive_crop_box_checks':checks,
                'rejection_examples':[{'box':asdict(b),'yellow_background_fraction':yellow_background_fraction(rgb,b,active)} for b in rejected[:12]]}
        records.append(record);print(name,len(before),len(after),len(rejected),flush=True)
    write_json_atomic(args.output,{'application_version':__version__,
        'scope':'Segmentation-only smoke test, without model inference. Rejection counts are not classification accuracy. Positive-crop box retention does not measure complete-chart sounding recall.',
        'records':records})


if __name__=='__main__':main()
