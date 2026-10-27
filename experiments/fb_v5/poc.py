"""Small, CPU-only field-sheet experiment; deliberately outside src/vetorizafb.

Coordinates are native pixel edges (xyxy). Preparation/detection never load OCR.
Original ink is preserved: the line mask is used for proposals, not recognition.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import zipfile

import cv2
import numpy as np

REVISION = "fb-poc-1"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(",", ":")).encode()).hexdigest()


def image_digest(image):
    return digest([list(image.shape), str(image.dtype),
                   hashlib.sha256(image.tobytes()).hexdigest()])


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@dataclass(frozen=True)
class PrepareOptions:
    background_window: int = 51
    clahe_clip: float = 2.0
    threshold: int = 175
    glyph_height: int = 32  # Native pixels; independent of unreliable TIFF DPI.

    def __post_init__(self):
        if (type(self.background_window) is not int or self.background_window < 3
                or self.background_window % 2 != 1 or self.clahe_clip <= 0
                or not math.isfinite(self.clahe_clip)
                or type(self.threshold) is not int or not 0 < self.threshold < 256
                or type(self.glyph_height) is not int or self.glyph_height < 8):
            raise ValueError("Invalid FB preparation settings")


def prepare(rgb, options=PrepareOptions()):
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("Expected RGB uint8")
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE,
                                 np.ones((options.background_window,) * 2, np.uint8))
    flat = cv2.divide(gray, np.maximum(background, 1), scale=255)
    local = cv2.createCLAHE(clipLimit=options.clahe_clip, tileGridSize=(8, 8)).apply(flat)
    ink = np.uint8(local < options.threshold) * 255
    # A single '1' is far shorter than these kernels. Intersections can still
    # lose strokes, so original/normalized images remain the OCR sources.
    length = options.glyph_height * 4
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, length), np.uint8))
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((length, 1), np.uint8))
    lines = cv2.bitwise_or(horizontal, vertical)
    return dict(gray=gray, normalized=local, ink=ink, lines=lines)


def morph_regions(prepared, *, glyph_height=32, suppress_straight=True):
    ink = prepared["ink"].copy()
    if suppress_straight:
        ink[prepared["lines"] > 0] = 0
    kh, kw = max(1, round(glyph_height * .12)), max(3, round(glyph_height * .40))
    connected = cv2.dilate(ink, np.ones((kh, kw), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(connected)
    regions = []
    for n in range(1, count):
        x, y, w, h, _ = map(int, stats[n])
        ys, xs = np.where((labels[y:y+h, x:x+w] == n) & (ink[y:y+h, x:x+w] > 0))
        if xs.size < 16:
            continue
        x1, y1 = x + int(xs.min()), y + int(ys.min())
        x2, y2 = x + int(xs.max()) + 1, y + int(ys.max()) + 1
        w, h = x2-x1, y2-y1
        if not (.18*glyph_height <= w <= 3.4*glyph_height
                and .42*glyph_height <= h <= 2.0*glyph_height
                and .025 <= xs.size/(w*h) <= .72):
            continue
        flags = []
        pad = 3
        if np.any(prepared["lines"][max(0, y1-pad):y2+pad, max(0, x1-pad):x2+pad]):
            flags.append("straight_line_contact")
        regions.append(dict(box=[x1, y1, x2, y2], flags=flags, score=None))
    return sorted(regions, key=lambda r: (r["box"][1], r["box"][0]))


def paddle_regions(rgb, detector, scale=1):
    if scale not in (1, 2):
        raise ValueError("Experimental detector scale must be 1 or 2")
    detector_rgb = rgb if scale == 1 else cv2.resize(rgb, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    results = detector.predict(detector_rgb[:, :, ::-1].copy(), limit_side_len=960, limit_type="max")
    if len(results) != 1:
        raise RuntimeError("Unexpected detector result count")
    result = results[0]
    polygons, scores = result["dt_polys"], result["dt_scores"]
    if len(polygons) != len(scores):
        raise RuntimeError("Detector polygons/scores disagree")
    h, w = rgb.shape[:2]
    regions = []
    for polygon, score in zip(polygons, scores):
        p = np.asarray(polygon, dtype=float)/scale
        box = [max(0, int(np.floor(p[:, 0].min()))), max(0, int(np.floor(p[:, 1].min()))),
               min(w, int(np.ceil(p[:, 0].max())) + 1), min(h, int(np.ceil(p[:, 1].max())) + 1)]
        if box[2] > box[0] and box[3] > box[1]:
            regions.append(dict(box=box, polygon=p.tolist(), score=float(score), flags=[]))
    return sorted(regions, key=lambda r: (r["box"][1], r["box"][0]))


def crop(image, box, pad=3):
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= image.shape[1] and 0 <= y1 < y2 <= image.shape[0]):
        raise ValueError("Region outside native image")
    return image[max(0, y1-pad):min(image.shape[0], y2+pad),
                 max(0, x1-pad):min(image.shape[1], x2+pad)].copy()


def split_layout(rgb):
    """Provisional right/lower-component rule, independent of OCR and depth.

    Returns a split in local pixels or None. Joined glyphs deliberately remain
    unresolved rather than inventing a decimetre from a numeric range.
    """
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    count, _, stats, _ = cv2.connectedComponentsWithStats(ink)
    parts = [tuple(map(int, s)) for s in stats[1:] if s[4] >= 5 and s[3] >= 4]
    if len(parts) < 2:
        return None
    height = max(s[3] for s in parts)
    main = [s for s in parts if s[3] >= .72*height]
    baseline = float(np.median([s[1]+s[3]/2 for s in main]))
    right = max(s[0]+s[2] for s in main)
    tails = [s for s in parts if .22*height <= s[3] <= .78*height
             and s[1]+s[3]/2 >= baseline+.14*height
             and s[0] >= right-.15*height]
    if not tails:
        return None
    tail = min(tails, key=lambda s: s[0])
    left_main = max((s[0]+s[2] for s in main if s[0] < tail[0]), default=0)
    if not left_main or tail[0] < left_main:
        return None
    split = (left_main+tail[0])//2
    return split if 0 < split < rgb.shape[1] else None


def parse_whole(text, has_decimetre):
    text = text.strip()
    # No letter->digit guessing, arbitrary punctuation stripping or range fix.
    if re.fullmatch(r"[0-9]{1,3}[.,][0-9]", text):
        a, b = re.split(r"[.,]", text)
        return dict(integer=a, decimetre=b, value=float(a)+int(b)/10)
    if not re.fullmatch(r"[0-9]{1,4}", text):
        return dict(integer=None, decimetre=None, value=None)
    if has_decimetre:
        if len(text) < 2:
            return dict(integer=None, decimetre=None, value=None)
        a, b = text[:-1], text[-1]
        return dict(integer=a, decimetre=b, value=int(a)+int(b)/10)
    return dict(integer=text, decimetre=None, value=float(text))


def parse_parts(integer, decimetre=None):
    integer = integer.strip()
    decimetre = None if decimetre is None else decimetre.strip()
    if not re.fullmatch(r"[0-9]{1,3}", integer):
        integer = None
    if decimetre is not None and not re.fullmatch(r"[0-9]", decimetre):
        decimetre = "?"
    value = None if integer is None or decimetre == "?" else int(integer)+(int(decimetre)/10 if decimetre is not None else 0)
    return dict(integer=integer, decimetre=decimetre, value=value)


def model_crops_read(crops, engine, batch_size=8):
    output = []
    for start in range(0, len(crops), batch_size):
        readings = engine.predict(crops[start:start+batch_size])
        if len(readings) != len(crops[start:start+batch_size]):
            raise RuntimeError("Unexpected recognition result count")
        for text, score in readings:
            if not math.isfinite(float(score)) or not 0 <= score <= 1:
                raise ValueError("Invalid recognition score")
            output.append(dict(text=str(text), score=float(score)))
    return output


def read_regions(rgb, regions, engine, *, strategy="whole"):
    if strategy not in ("whole", "split"):
        raise ValueError("Unknown recognition strategy")
    crops, jobs, layouts = [], [], []
    for i, region in enumerate(regions):
        b = region["box"]
        patch = crop(rgb, b, pad=0)
        split = split_layout(patch)
        layouts.append(split)
        if strategy == "whole" or split is None:
            crops.append(crop(rgb, b))
            jobs.append((i, "whole"))
        else:
            for side, p in (("integer", patch[:, :split]), ("decimetre", patch[:, split:])):
                # Keep complete ink in each part; white border does not change
                # source coordinates and avoids tiny unsupported input shapes.
                p = cv2.copyMakeBorder(p, 5, 5, 5, 5, cv2.BORDER_CONSTANT, value=(255, 255, 255))
                crops.append(p)
                jobs.append((i, side))
    results = [{} for _ in regions]
    for (i, side), reading in zip(jobs, model_crops_read(crops, engine)):
        results[i][side] = reading
    return [dict(region=regions[i], readings=readings, split_x=layouts[i], strategy=strategy)
            for i, readings in enumerate(results)]


def interpret_regions(records):
    """Reinterpret cached text/layout evidence without another model call."""
    output = []
    for record in records:
        readings = record["readings"]
        if "whole" in readings:
            parsed = parse_whole(readings["whole"]["text"], record["split_x"] is not None)
        else:
            parsed = parse_parts(readings["integer"]["text"], readings["decimetre"]["text"])
        output.append(dict(record, **parsed))
    return output


def recognize_regions(rgb, regions, engine, *, strategy="whole"):
    return interpret_regions(read_regions(rgb, regions, engine, strategy=strategy))


def stage_keys(source, prepare_options, detector, model, layout, grouping):
    """Dependencies are explicit; review/grouping changes do not re-run OCR."""
    preparation = digest([REVISION, file_digest(__file__), source, prepare_options])
    detection = digest([preparation, detector])
    readings = digest([detection, model, layout])
    grouped = digest([readings, grouping])
    return dict(prepared=preparation, regions=detection, readings=readings, grouping=grouped)


class StageCache:
    """Content-addressed, bounded-stage outputs; corrupt entries are recomputed."""
    stages = {"prepared", "regions", "readings", "grouping"}

    def __init__(self, root):
        self.root = Path(root)

    def get_or_compute(self, stage, key, compute):
        if stage not in self.stages or not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("Invalid cache stage/key")
        suffix = ".npz" if stage == "prepared" else ".json"
        path = self.root/stage/(key+suffix)
        try:
            if stage == "prepared":
                with np.load(path, allow_pickle=False) as archive:
                    data = {k: archive[k] for k in archive.files}
                if set(data) != {"gray", "normalized", "ink", "lines"}:
                    raise ValueError("Incomplete preparation cache")
                shape = data["gray"].shape
                if len(shape) != 2 or any(v.dtype != np.uint8 or v.shape != shape for v in data.values()):
                    raise ValueError("Invalid preparation cache arrays")
                return data, True
            record = json.loads(path.read_text())
            if (record["key"] != key or record["revision"] != REVISION or record["stage"] != stage
                    or digest(record["data"]) != record["data_sha256"]):
                raise ValueError("Stale cache")
            return record["data"], True
        except (OSError, ValueError, KeyError, TypeError, EOFError, zipfile.BadZipFile):
            pass
        data = compute()
        path.parent.mkdir(parents=True, exist_ok=True)
        if stage == "prepared":
            fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as stream:
                    np.savez_compressed(stream, **data)
                os.replace(name, path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        else:
            atomic_json(path, dict(key=key, revision=REVISION, stage=stage, data=data, data_sha256=digest(data)))
        return data, False


def area(box):
    return max(0, box[2]-box[0])*max(0, box[3]-box[1])


def intersection(a, b):
    return area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def iou(a, b):
    shared = intersection(a, b)
    return shared/max(1, area(a)+area(b)-shared)


def evaluate_detection(regions, truth, ignore=(), threshold=.5):
    """Maximum-cardinality one-to-one matching; no double-counted fragments."""
    edges = {i: sorted([j for j, t in enumerate(truth) if iou(r["box"], t["box"]) >= threshold],
                       key=lambda j: -iou(r["box"], truth[j]["box"]))
             for i, r in enumerate(regions)}
    matched_truth = {}

    def assign(i, seen):
        for j in edges[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in matched_truth or assign(matched_truth[j], seen):
                matched_truth[j] = i
                return True
        return False

    for i in sorted(edges, key=lambda j: len(edges[j])):
        assign(i, set())
    matched_regions = set(matched_truth.values())
    ignored, fragments, spurious = [], [], []
    for i, r in enumerate(regions):
        if i in matched_regions:
            continue
        b = r["box"]
        # Known text has precedence over an overlapping ignore border.
        touches_truth = any(intersection(b, t["box"])/max(1, min(area(b), area(t["box"]))) >= .25 for t in truth)
        if not touches_truth and any(intersection(b, b2)/max(1, area(b)) >= .5 for b2 in ignore):
            ignored.append(i)
        elif touches_truth:
            fragments.append(i)
        else:
            spurious.append(i)
    return dict(reference=len(truth), found=len(matched_truth), missed=len(truth)-len(matched_truth),
                false_regions=len(fragments)+len(spurious), fragments_or_bad_boxes=len(fragments),
                spurious=len(spurious), ignored=len(ignored),
                matches=[dict(truth=j, region=i, iou=iou(regions[i]["box"], truth[j]["box"]))
                         for j, i in sorted(matched_truth.items())],
                false_region_ids=fragments+spurious, ignored_region_ids=ignored)


def reading_scores(predictions, truth):
    if len(predictions) != len(truth):
        raise ValueError("Recognition diagnostic requires one crop per truth")
    pairs = [(p, t) for p, t in zip(predictions, truth) if t.get("recognition_eligible", True)]
    def integer_equal(p, t):
        value = p["integer"]
        return value is not None and value.isascii() and value.isdigit() and int(value) == int(t["integer"])
    return dict(total=len(pairs), excluded=len(truth)-len(pairs),
                exact=sum(integer_equal(p, t) and p["decimetre"] == t["decimetre"] for p, t in pairs),
                integer_errors=sum(not integer_equal(p, t) for p, t in pairs),
                decimetre_errors=sum(p["decimetre"] != t["decimetre"] for p, t in pairs),
                abstentions=sum(p["value"] is None for p, t in pairs))
