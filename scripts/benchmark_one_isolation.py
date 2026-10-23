"""Compare directed-one recovery against the immutable 0.3.0 core blob.

Requires repository history containing that blob and local official OCR weights.
Images and model weights are not committed. These are diagnostic annotations,
not an independently reviewed full-chart accuracy reference.
"""
import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import types

from PIL import Image
import rasterio
from rasterio.windows import Window

from vetorizafb import __version__, core
from vetorizafb.ocr import PaddleRecognizer
from vetorizafb.pipeline import read_chart, sha256, write_json_atomic

ROOT=Path(__file__).resolve().parents[1]
BASELINE_COMMIT='6b66bd521da23da6cdd5e7c294a0e0f1187ff49b'
BASELINE_BLOB='e82216a38077fa26291c2400e68b818d0f436bb1'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--model-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        source=subprocess.check_output(['git','cat-file','blob',BASELINE_BLOB],cwd=ROOT,stderr=subprocess.PIPE)
    except (OSError,subprocess.CalledProcessError):
        parser.error('The 0.3.0 baseline blob is unavailable. Use a Git clone with its history, rather than a branch ZIP/shallow clone.')
    baseline=types.ModuleType('vetorizafb_core_0_3_0')
    sys.modules[baseline.__name__]=baseline
    exec(compile(source,'core_0_3_0.py','exec'),baseline.__dict__)
    os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK','True')
    model=args.model_dir.resolve()
    engine=PaddleRecognizer('PP-OCRv6_small_rec',str(model),'cpu')
    inputs={};records=[];start=time.perf_counter()
    references=[('current','remaining-ones-reference.json'),
                ('previous_five','one-reference.json'),('previous_19','crop_reference.json')]
    current_reference=None
    for refname,filename in references:
        reference=json.loads((ROOT/'docs/experiments'/filename).read_text(encoding='utf-8'))
        if refname=='current':current_reference=reference
        for case in reference['samples']:
            if refname=='previous_five' and case['kind']!='sounding':continue
            path=args.data_dir/case['image']
            if case['image'] not in inputs:
                inputs[case['image']]={'sha256':sha256(path),'bytes':path.stat().st_size}
            a,b,c,d=case['box']
            with rasterio.open(path) as ds:
                rgb=ds.read([1,2,3],window=Window(a,b,c-a,d-b)).transpose(1,2,0)
            with Image.open(path) as im:dpi=float(im.info['dpi'][0])
            runs={}
            for name,module in [('before',baseline),('after',core)]:
                config=module.Config(dpi=dpi)
                boxes=module.segment(rgb,config)
                digits=module.recognize(rgb,boxes,engine,retry_one=True,min_confidence=config.min_confidence)
                values=[s.depth for s in module.group(digits,config)]
                expected=case['expected_depth']
                correct=not values if expected is None else len(values)==1 and abs(values[0]-expected)<1e-8
                runs[name]={'values':values,'correct':correct,'digits':[asdict(x) for x in digits]}
            records.append(dict(case,reference=refname,runs=runs))
            print(refname,case['id'],runs['before']['values'],runs['after']['values'],flush=True)
    # Whole-chart checks avoid changes caused by an ROI boundary or crop padding.
    rgb,*_=read_chart(args.data_dir/'21300plano.tif')
    full={};full_digits={}
    for name,module in [('before',baseline),('after',core)]:
        config=module.Config();boxes=module.segment(rgb,config)
        digits=module.recognize(rgb,boxes,engine,retry_one=True)
        soundings=module.group(digits,config)
        checks=[]
        for case in current_reference['samples']:
            a,b,c,d=case['box']
            checks.append({'id':case['id'],'expected_depth':case['expected_depth'],
                           'values':[s.depth for s in soundings if a<=s.pixel_x<c and b<=s.pixel_y<d]})
        full[name]={'boxes':len(boxes),'candidate_count':len(soundings),'checks':checks}
        full_digits[name]=digits
    full['changed_readings']=[{'index':d.index,'box':asdict(d.box),'before_text':p.text,
                              'after_text':d.text,'raw_text':d.raw_text,'raw_confidence':d.confidence,
                              'alternatives':d.alternatives,'selected_confidence':d.selected_confidence,
                              'method':d.method}
                             for p,d in zip(full_digits['before'],full_digits['after'])
                             if (p.text,p.score)!=(d.text,d.score)]
    full['punctuation_control']=[asdict(d) for d in full_digits['after'] if d.index==393]
    selectors=[('current_screenshot',lambda r:r.get('set')=='current_screenshot'),
               ('additional_one',lambda r:r.get('set')=='additional_one'),
               ('previous_five',lambda r:r['reference']=='previous_five'),
               ('previous_19_positive',lambda r:r['reference']=='previous_19' and r['kind']=='sounding'),
               ('previous_contour_negatives',lambda r:r['reference']=='previous_19' and r['kind']!='sounding'),
               ('marginal_coordinate_negatives',lambda r:'coordinate' in r['kind']),
               ('word_negative',lambda r:r['kind']=='printed_word')]
    summary={}
    for label,predicate in selectors:
        subset=[r for r in records if predicate(r)]
        summary[label]={'samples':len(subset),'before_correct':sum(r['runs']['before']['correct'] for r in subset),
                        'after_correct':sum(r['runs']['after']['correct'] for r in subset)}
    report={'scope':'Assistant-read diagnostic comparisons, not independent full-chart ground truth. Marginal-coordinate and contour-label negatives remain false positives; no automatic exclusion is added.',
            'application_version':__version__,'baseline_commit':BASELINE_COMMIT,'baseline_core_git_blob':BASELINE_BLOB,
            'current_core_sha256':hashlib.sha256(Path(core.__file__).read_bytes()).hexdigest(),
            'model':'PP-OCRv6_small_rec','device':'cpu','config':asdict(core.Config()),
            'packages':{p:importlib.metadata.version(p) for p in ['paddleocr','paddlepaddle','paddlex']},
            'model_files_sha256':{f.name:sha256(f) for f in model.iterdir() if f.is_file()},
            'input_files':inputs,'elapsed_seconds_excluding_model_load':time.perf_counter()-start,
            'summary':summary,'full_chart':full,'records':records}
    write_json_atomic(args.output,report)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
