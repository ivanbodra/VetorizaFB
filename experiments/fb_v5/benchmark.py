"""Reproducible diagnostics, measured per method in a separate CPU process.

Run from repository root: python -m experiments.fb_v5.benchmark --help
No automatic model download. See download_models.py for the explicit action.
"""
import argparse
from dataclasses import asdict
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import psutil

from .poc import (PrepareOptions, StageCache, atomic_json, crop, digest,
                  evaluate_detection, file_digest, image_digest, morph_regions,
                  paddle_regions, prepare, reading_scores, recognize_regions,
                  stage_keys, read_regions, interpret_regions)

HERE = Path(__file__).resolve().parent
SAMPLE = HERE/"sample"
METHODS = ("stable_96", "stable_600_black", "morph_raw", "morph_lines",
           "paddle_raw", "paddle_normalized", "paddle_raw_2x", "paddle_normalized_2x")
METHODS = METHODS + ("morph_lines_split",)


class MemoryMeter:
    """Whole-process RSS, with kernel high-water mark when available.

    /proc/self also works when the executor PID namespace differs from /proc.
    Resolving /proc/<os.getpid()> would measure an unrelated host process here.
    """
    @staticmethod
    def rss():
        if Path("/proc/self/statm").is_file():
            return int(Path("/proc/self/statm").read_text().split()[1])*os.sysconf("SC_PAGE_SIZE")
        return psutil.Process().memory_info().rss

    def __enter__(self):
        self.base = self.peak = self.rss()
        self.stop = threading.Event()
        def sample():
            while not self.stop.wait(.01):
                self.peak = max(self.peak, self.rss())
        self.thread = threading.Thread(target=sample, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.peak = max(self.peak, self.rss())
        self.stop.set()
        self.thread.join()
        if Path("/proc/self/status").is_file():
            for line in Path("/proc/self/status").read_text().splitlines():
                if line.startswith("VmHWM:"):
                    self.peak = max(self.peak, int(line.split()[1])*1024)
        else:
            info = psutil.Process().memory_info()
            self.peak = max(self.peak, getattr(info, "peak_wset", info.rss))


class Reader:
    def __init__(self, model_dir):
        path = Path(model_dir)/"PP-OCRv6_small_rec_infer"
        if not path.is_dir():
            raise FileNotFoundError("Use --model-root with explicitly downloaded local assets")
        from paddleocr import TextRecognition
        self.model = TextRecognition(model_name="PP-OCRv6_small_rec", model_dir=str(path),
                                     device="cpu", cpu_threads=2, enable_mkldnn=False)

    def predict(self, crops):
        results = self.model.predict([c[:, :, ::-1].copy() for c in crops], batch_size=len(crops))
        return [(str(r["rec_text"]), float(r["rec_score"])) for r in results]


def detector_load(model_root):
    path = Path(model_root)/"PP-OCRv5_mobile_det_infer"
    if not path.is_dir():
        raise FileNotFoundError("Explicitly download the detector before this experiment")
    from paddleocr import TextDetection
    return TextDetection(model_name="PP-OCRv5_mobile_det", model_dir=str(path), device="cpu",
                         cpu_threads=2, enable_mkldnn=False)


def fingerprint_models(root):
    return {str(p.relative_to(root)): file_digest(p)
            for p in sorted(Path(root).glob("*_infer/*")) if p.is_file()}


def versions():
    result = {}
    for name in ("numpy", "opencv-contrib-python", "paddleocr", "paddlepaddle", "paddlex", "psutil", "rasterio", "pyproj"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def output_regions(soundings):
    return [dict(box=list(s.bounds), flags=s.flags, score=s.confidence,
                 integer=str(int(s.depth)),
                 decimetre=(str(round((s.depth-int(s.depth))*10)) if s.interpretation == "subscript_decimal" else None),
                 value=s.depth) for s in soundings]


def run_worker(method, model_root, destination, cache_root):
    # Imports of stable code happen only here, never through application startup.
    sys.path.insert(0, str(HERE.parents[1]/"src"))
    from vetorizafb.core import Config, group, recognize, segment_details
    reference = json.loads((SAMPLE/"reference.json").read_text())
    cv2.setNumThreads(2)
    start = time.perf_counter()
    timings = dict(load_models=0., preparation=0., detection=0., recognition=0., grouping=0.)
    cache = StageCache(cache_root)
    results = []
    with MemoryMeter() as memory:
        stamp = time.perf_counter()
        reader = Reader(model_root)
        detector = detector_load(model_root) if method.startswith("paddle") else None
        timings["load_models"] = time.perf_counter()-stamp
        model_key = dict(files=fingerprint_models(model_root), versions=versions(), cpu_threads=2, mkldnn=False)
        for tile in reference["tiles"]:
            rgb = np.array(Image.open(SAMPLE/tile["file"]).convert("RGB"))
            options = PrepareOptions()
            source_key = dict(pixels=image_digest(rgb), source=reference["source_sha256"], roi=tile["roi"])
            strategy = "split" if method.endswith("_split") else "whole"
            detector_key = dict(method=method.removesuffix("_split"), code=file_digest(HERE/"poc.py"), model=model_key if detector else None,
                                limit_side_len=960, limit_type="max", glyph_height=options.glyph_height,
                                scale=2 if method.endswith("_2x") else 1)
            keys = stage_keys(source_key, asdict(options), detector_key, model_key,
                              ["auto-component-layout", strategy], "strict-structure-no-neighbours")
            stamp = time.perf_counter()
            prepared, prep_hit = cache.get_or_compute("prepared", keys["prepared"], lambda: prepare(rgb, options))
            timings["preparation"] += time.perf_counter()-stamp
            stamp = time.perf_counter()
            if method.startswith("stable"):
                cfg = Config(dpi=96) if method == "stable_96" else Config(dpi=600, segmentation="black")
                mask, all_boxes, boxes = segment_details(rgb, cfg)
                # Complete-region metric on glyph boxes is intentionally separate
                # from the same metric after the stable OCR/grouping stages.
                proposals = [dict(box=[b.x, b.y, b.x+b.w, b.y+b.h], flags=[], score=None) for b in boxes]
                detection_hit = False
            else:
                def detect():
                    if method.startswith("morph"):
                        return morph_regions(prepared, glyph_height=options.glyph_height,
                                             suppress_straight=method.startswith("morph_lines"))
                    image = (np.repeat(prepared["normalized"][:, :, None], 3, axis=2)
                             if method.startswith("paddle_normalized") else rgb)
                    return paddle_regions(image, detector, scale=2 if method.endswith("_2x") else 1)
                proposals, detection_hit = cache.get_or_compute("regions", keys["regions"], detect)
            timings["detection"] += time.perf_counter()-stamp
            stamp = time.perf_counter()
            if method.startswith("stable"):
                digits = recognize(rgb, boxes, reader, batch_size=8, pad=cfg.crop_padding,
                                   retry=cfg.retry_ambiguous, retry_one=cfg.retry_one,
                                   min_confidence=cfg.min_confidence)
                timings["recognition"] += time.perf_counter()-stamp
                stamp = time.perf_counter()
                soundings = group(digits, cfg)
                predictions = output_regions(soundings)
                final_regions = predictions
                timings["grouping"] += time.perf_counter()-stamp
                readings_hit = grouping_hit = False
            else:
                raw_readings, readings_hit = cache.get_or_compute("readings", keys["readings"],
                                          lambda: read_regions(rgb, proposals, reader, strategy=strategy))
                timings["recognition"] += time.perf_counter()-stamp
                stamp = time.perf_counter()
                predictions, grouping_hit = cache.get_or_compute("grouping", keys["grouping"],
                                                                 lambda: interpret_regions(raw_readings))
                final_regions = proposals
                timings["grouping"] += time.perf_counter()-stamp
            detection = evaluate_detection(proposals, tile["soundings"], tile["ignore"])
            final = evaluate_detection(final_regions, tile["soundings"], tile["ignore"])
            matched_p = [predictions[m["region"]] for m in final["matches"]]
            matched_t = [tile["soundings"][m["truth"]] for m in final["matches"]]
            result = dict(tile=tile["id"], regions=proposals, predictions=predictions,
                          final_regions=final_regions, detection=detection, final_detection=final,
                          recognition_on_matched=reading_scores(matched_p, matched_t),
                          cache_hits=dict(prepared=prep_hit, regions=detection_hit,
                                          readings=readings_hit, grouping=grouping_hit))
            results.append(result)
            print(f'{method} tile {tile["id"]}: found {final["found"]}/{final["reference"]}', flush=True)
    record = dict(method=method, timings_seconds=timings, wall_seconds=time.perf_counter()-start,
                  memory=dict(peak_rss_mib=memory.peak/2**20, base_rss_mib=memory.base/2**20,
                              incremental_peak_mib=(memory.peak-memory.base)/2**20, sampling_ms=10),
                  results=results, versions=versions(), model_files=model_key["files"],
                  environment=dict(os=platform.platform(), python=platform.python_version(),
                                   machine=platform.machine(), cpu=platform.processor(),
                                   logical_cpus=os.cpu_count(), inference_threads=2, device="cpu"),
                  reference_sha256=file_digest(SAMPLE/"reference.json"),
                  code_sha256={p.name: file_digest(p) for p in (HERE/"poc.py", HERE/"benchmark.py")})
    atomic_json(destination/(method+".json"), record)
    print(json.dumps(dict(method=method, wall_seconds=record["wall_seconds"], memory=record["memory"])), flush=True)


def recognition_diagnostic(model_root, destination):
    reference = json.loads((SAMPLE/"reference.json").read_text())
    cv2.setNumThreads(2)
    rows = []
    with MemoryMeter() as memory:
        stamp = time.perf_counter()
        reader = Reader(model_root)
        load_seconds = time.perf_counter()-stamp
        for tile in reference["tiles"]:
            rgb = np.array(Image.open(SAMPLE/tile["file"]).convert("RGB"))
            truth = tile["soundings"]
            regions = [dict(box=t["box"], flags=[], score=None) for t in truth]
            for strategy in ("whole", "split"):
                stamp = time.perf_counter()
                predictions = recognize_regions(rgb, regions, reader, strategy=strategy)
                seconds = time.perf_counter()-stamp
                rows.append(dict(tile=tile["id"], strategy=strategy, predictions=predictions,
                                 metrics=reading_scores(predictions, truth), seconds=seconds))
    atomic_json(destination/"recognition_diagnostic.json",
                dict(results=rows, load_seconds=load_seconds, peak_rss_mib=memory.peak/2**20,
                     reference_sha256=file_digest(SAMPLE/"reference.json"),
                     versions=versions(), model_files=fingerprint_models(model_root),
                     code_sha256={p.name: file_digest(p) for p in (HERE/"poc.py", HERE/"benchmark.py")}))


def font(size=13):
    for name in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"):
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


def visuals(destination):
    reference = json.loads((SAMPLE/"reference.json").read_text())
    evidence = destination/"images"
    evidence.mkdir(parents=True, exist_ok=True)
    sheets = []
    for tile in reference["tiles"]:
        base = Image.open(SAMPLE/tile["file"]).convert("RGB").resize((tile["roi"][2]*2, tile["roi"][3]*2))
        draw = ImageDraw.Draw(base)
        for t in tile["soundings"]:
            b = [p*2 for p in t["box"]]
            draw.rectangle(b, outline="#005dcc", width=2)
            value = ("?" if not t.get("recognition_eligible", True) else
                     t["integer"] + (","+t["decimetre"] if t["decimetre"] is not None else ""))
            draw.text((b[0], max(0, b[1]-14)), t["id"]+" "+value, fill="#0045aa", font=font(13))
        base.save(evidence/(tile["id"]+"_reference.png"))
        for method in ("stable_600_black", "morph_lines", "paddle_raw_2x", "paddle_normalized_2x"):
            path = destination/(method+".json")
            if not path.is_file():
                continue
            record = json.loads(path.read_text())
            result = next(r for r in record["results"] if r["tile"] == tile["id"])
            canvas = Image.open(SAMPLE/tile["file"]).convert("RGB").resize(base.size)
            draw = ImageDraw.Draw(canvas)
            detection = result["final_detection"]
            matched = {m["region"] for m in detection["matches"]}
            ignored = set(detection["ignored_region_ids"])
            for i, region in enumerate(result["final_regions"]):
                color = "#00a248" if i in matched else "#999999" if i in ignored else "#e13a23"
                b = [p*2 for p in region["box"]]
                draw.rectangle(b, outline=color, width=2)
                draw.text((b[0], max(0, b[1]-13)), str(i), font=font(12), fill=color)
            canvas.save(evidence/(tile["id"]+"_"+method+".png"))
            if tile["id"] in ("C", "D"):
                card = Image.new("RGB", (base.width, base.height+32), "white")
                card.paste(canvas, (0, 32))
                ImageDraw.Draw(card).text((8, 6), tile["id"]+" / "+method, fill="#222222", font=font(18))
                sheets.append(card)
    if sheets:
        columns = 4
        cw, ch = max(s.width for s in sheets), max(s.height for s in sheets)
        sheet = Image.new("RGB", (cw*columns, ch*2), "white")
        for i, card in enumerate(sheets):
            sheet.paste(card, (i%columns*cw, i//columns*ch))
        sheet.save(evidence/"comparison.png")
    # Independent hand-crop contact sheet, with predictions for direct auditing.
    diag = destination/"recognition_diagnostic.json"
    if diag.is_file():
        data = json.loads(diag.read_text())
        examples = []
        for tile in reference["tiles"]:
            rgb = np.array(Image.open(SAMPLE/tile["file"]).convert("RGB"))
            preds = next(r for r in data["results"] if r["tile"] == tile["id"] and r["strategy"] == "whole")["predictions"]
            for t, p in zip(tile["soundings"], preds):
                card = Image.new("RGB", (180, 125), "white")
                patch = Image.fromarray(crop(rgb, t["box"]))
                patch.thumbnail((150, 73))
                patch = patch.resize((patch.width*2, patch.height*2)) if patch.height < 35 else patch
                patch.thumbnail((160, 77))
                card.paste(patch, ((180-patch.width)//2, 20))
                d = ImageDraw.Draw(card)
                value = ("?" if not t.get("recognition_eligible", True) else
                         t["integer"] + (","+t["decimetre"] if t["decimetre"] is not None else ""))
                d.text((5, 2), t["id"]+" ref "+value, font=font(), fill="black")
                out = "?" if p["value"] is None else f'{p["value"]:g}'
                d.text((5, 98), "whole crop: "+out, font=font(), fill="#0045aa")
                examples.append(card)
        sheet = Image.new("RGB", (180*8, 125*((len(examples)+7)//8)), "#dddddd")
        for i, card in enumerate(examples):
            sheet.paste(card, ((i%8)*180, (i//8)*125))
        sheet.save(evidence/"recognition_audit.png")


def summarize(destination):
    rows = []
    for method in METHODS:
        path = destination/(method+".json")
        if not path.is_file():
            continue
        r = json.loads(path.read_text())
        final = [x["final_detection"] for x in r["results"]]
        metrics = [x["recognition_on_matched"] for x in r["results"]]
        rows.append(dict(method=method, found=sum(x["found"] for x in final),
                         false_regions=sum(x["false_regions"] for x in final),
                         spurious=sum(x["spurious"] for x in final),
                         fragments_or_bad_boxes=sum(x["fragments_or_bad_boxes"] for x in final),
                         exact=sum(x["exact"] for x in metrics),
                         eligible_matched=sum(x["total"] for x in metrics),
                         integer_errors_on_found=sum(x["integer_errors"] for x in metrics),
                         decimetre_errors_on_found=sum(x["decimetre_errors"] for x in metrics),
                         wall_seconds=r["wall_seconds"], peak_rss_mib=r["memory"]["peak_rss_mib"]))
    diag = destination/"recognition_diagnostic.json"
    oracle = []
    if diag.is_file():
        data = json.loads(diag.read_text())
        for strategy in ("whole", "split"):
            rows_s = [r for r in data["results"] if r["strategy"] == strategy]
            oracle.append(dict(strategy=strategy,
                               **{k: sum(r["metrics"][k] for r in rows_s) for k in ("total", "excluded", "exact", "integer_errors", "decimetre_errors", "abstentions")},
                               seconds=sum(r["seconds"] for r in rows_s)))
    atomic_json(destination/"summary.json", dict(end_to_end=rows, recognition_fixed_regions=oracle))
    print(json.dumps(dict(end_to_end=rows, recognition_fixed_regions=oracle), indent=2))


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("--output", type=Path, default=HERE/"evidence")
    parser.add_argument("--cache", type=Path, default=HERE/"cache")
    parser.add_argument("--worker", choices=METHODS+("diagnostic",))
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=METHODS)
    parser.add_argument("--visuals-only", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.visuals_only:
        visuals(args.output)
        summarize(args.output)
        return
    if args.model_root is None:
        parser.error("--model-root is required; weights are never fetched implicitly")
    if args.worker:
        if args.worker == "diagnostic":
            recognition_diagnostic(args.model_root, args.output)
        else:
            run_worker(args.worker, args.model_root, args.output, args.cache)
        return
    for method in list(args.methods)+["diagnostic"]:
        subprocess.run([sys.executable, "-m", "experiments.fb_v5.benchmark", "--worker", method,
                        "--model-root", str(args.model_root.resolve()), "--output", str(args.output.resolve()),
                        "--cache", str(args.cache.resolve())], check=True)
    visuals(args.output)
    summarize(args.output)


if __name__ == "__main__":
    main()
