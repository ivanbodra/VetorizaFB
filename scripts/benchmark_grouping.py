"""Measure grouping alone, without segmentation, model loading or OCR.

The legacy function is extracted with AST so importing its eager OCR reader is
unnecessary. String digits are supplied deliberately: this isolates grouping
performance from the legacy dataframe dtype problem.
"""
import argparse
import ast
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import statistics
import time

import numpy as np
import pandas as pd

from vetorizafb.core import Box, Config, Digit, group


def legacy_function(path):
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == 'group_digits_by_position')
    namespace = {'pd': pd, 'np': np}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[node.name]


def legacy_input(digits):
    return pd.DataFrame([{'center_x': d.box.center[0], 'center_y': d.box.center[1],
                          'height': d.box.h, 'digit': d.raw_text,
                          'confidence': d.confidence} for d in digits])


def measure(function, value, repeats):
    timings = []
    for _ in range(repeats):
        start = time.perf_counter()
        result = function(value)
        timings.append(time.perf_counter() - start)
    return {'median_seconds': statistics.median(timings),
            'seconds': timings, 'groups': len(result)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--digits-files', nargs='*', type=Path, default=[])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--sizes', type=int, nargs='+', default=[500, 1000, 2000, 4000])
    args = parser.parse_args()
    if args.repeats < 1 or any(n < 1 for n in args.sizes):
        parser.error('repeats and sizes must be positive')
    root = Path(__file__).resolve().parents[1]
    legacy_path = root / 'legacy/v3_1/ocr_segmented.py'
    modern_path = root / 'src/vetorizafb/core.py'
    legacy = legacy_function(legacy_path)
    config = Config()
    runs = []

    def run_case(label, digits, cfg, metadata=None):
        # Prepare the legacy dataframe outside the timer; its internal sort and
        # conversion remain timed. Each implementation uses its own result rules.
        frame = legacy_input(digits)
        item = {'case': label, 'digits': len(digits), 'config': asdict(cfg),
                'metadata': metadata or {},
                'modern': measure(lambda ds: group(ds, cfg), digits, args.repeats),
                'legacy': measure(lambda df: legacy(df, tol_x=cfg.tol_x*cfg.scale,
                                                   tol_y=cfg.tol_y*cfg.scale),
                                  frame, args.repeats)}
        runs.append(item)
        print(label, len(digits), 'modern', item['modern']['median_seconds'],
              'legacy', item['legacy']['median_seconds'], flush=True)

    for path in args.digits_files:
        entries = json.loads(path.read_text())
        digits = [Digit(Box(**d['box']), d['raw_text'], d['confidence'], d['index'])
                  for d in entries]
        metadata_path = path.with_name(path.name.replace('.digits.json', '.metadata.json'))
        metadata = json.loads(metadata_path.read_text())
        run_case(path.name, digits, Config(**metadata['config']),
                 {'input_sha256': metadata['input_sha256'],
                  'digits_json_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})

    for n in args.sizes:
        # Fixed local density: two digits per group; every group has its own X window.
        sparse = [Digit(Box((i//2)*100+(i%2)*16, 0, 12, 20),
                        str(i%10), .99, i) for i in range(n)]
        run_case('synthetic_sparse_pairs', sparse, Config())
        # Adversarial: every X lies in the window but no Y can be grouped.
        # This exposes the quadratic worst case of an X-only candidate window.
        column = [Digit(Box(0, i*100, 12, 20), str(i%10), .99, i) for i in range(n)]
        run_case('synthetic_same_x_distinct_y', column, Config())

    report = {'scope': 'Grouping performance only; timings are environment-specific. '
                       'Legacy and modern numeric grouping rules are not identical.',
              'python': platform.python_version(), 'platform': platform.platform(),
              'source_commit': 'e41353dc2e29e62f8bcadb1bac75f5f5d0e3fa2a',
              'source_sha256': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in [legacy_path, modern_path]},
              'repeats': args.repeats, 'runs': runs}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
