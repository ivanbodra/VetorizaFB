"""Chart segmentation and geometric grouping, independent of the GUI/OCR model."""
from dataclasses import asdict, dataclass
import math

import cv2
import numpy as np


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self):
        return self.x + self.w / 2, self.y + self.h / 2


@dataclass
class Digit:
    box: Box
    raw_text: str
    confidence: float
    index: int

    @property
    def text(self):
        # A multi-character crop is ambiguous: never silently truncate it.
        t = self.raw_text.strip()
        return t if len(t) == 1 and t in "0123456789" else None


@dataclass
class Sounding:
    pixel_x: float
    pixel_y: float
    depth: float
    confidence: float
    bounds: tuple
    digit_ids: list
    interpretation: str
    review_status: str = "unreviewed"


@dataclass
class Config:
    # Baseline dimensions are calibrated at 600 dpi, the author's test chart.
    reference_dpi: float = 600
    dpi: float = 600
    segmentation: str = "legacy"
    grouping: str = "relative"
    threshold: int = 120
    blur_size: int = 5
    kernel_size: int = 2
    min_w: int = 3
    max_w: int = 80
    min_h: int = 10
    max_h: int = 100
    tol_x: float = 30
    tol_y: float = 6
    decimal_height_ratio: float = .95
    decimal_drop: float = .10
    decimal_max_integer: float = 31
    min_confidence: float = .35

    def __post_init__(self):
        numeric = [self.reference_dpi, self.dpi, self.tol_x, self.tol_y,
                   self.decimal_height_ratio, self.decimal_drop,
                   self.decimal_max_integer, self.min_confidence]
        if not all(math.isfinite(float(v)) for v in numeric):
            raise ValueError("Configuration values must be finite")
        if self.reference_dpi <= 0 or self.dpi <= 0:
            raise ValueError("DPI must be positive")
        if not 0 <= self.threshold <= 255 or self.blur_size < 1 or self.kernel_size < 1:
            raise ValueError("Invalid threshold/blur/kernel")
        if not (0 < self.min_w < self.max_w and 0 < self.min_h < self.max_h):
            raise ValueError("Invalid box dimensions")
        if self.tol_x <= 0 or self.tol_y < 0 or not 0 < self.decimal_height_ratio <= 1:
            raise ValueError("Invalid grouping geometry")
        if self.decimal_drop < 0 or self.decimal_max_integer < 0 or not 0 <= self.min_confidence <= 1:
            raise ValueError("Invalid decimal/confidence setting")
        if self.segmentation not in {"legacy", "black"}:
            raise ValueError("segmentation must be legacy or black")
        if self.grouping not in {"fixed", "relative"}:
            raise ValueError("grouping must be fixed or relative")

    @property
    def scale(self):
        return self.dpi / self.reference_dpi


def segment(rgb, config):
    """Return boxes in ORIGINAL raster coordinates; never resize the whole chart."""
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("Expected an RGB uint8 image")
    s = config.scale
    if config.segmentation == "legacy":
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        blur = max(1, round(config.blur_size * s))
        blur += blur % 2 == 0
        gray = cv2.GaussianBlur(gray, (blur, blur), 0)
        _, mask = cv2.threshold(gray, config.threshold, 255, cv2.THRESH_BINARY_INV)
        k = max(1, round(config.kernel_size * s))
        mask = cv2.dilate(mask, np.ones((k, k), np.uint8), iterations=1)
    else:
        # Supplemental black-ink mask; original color crops still feed the OCR.
        mask = (rgb.max(axis=2) < config.threshold).astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = [Box(*cv2.boundingRect(c)) for c in contours]
    boxes = [b for b in boxes if config.min_w*s < b.w < config.max_w*s
             and config.min_h*s < b.h < config.max_h*s]
    return sorted(boxes, key=lambda b: (b.x, b.y))


def recognize(rgb, boxes, engine, batch_size=64, pad=3):
    if batch_size < 1 or pad < 0:
        raise ValueError("Invalid batch size or padding")
    out = []
    h, w = rgb.shape[:2]
    for start in range(0, len(boxes), batch_size):
        subset = boxes[start:start+batch_size]
        crops = [rgb[max(0,b.y-pad):min(h,b.y+b.h+pad),
                     max(0,b.x-pad):min(w,b.x+b.w+pad)].copy() for b in subset]
        if any(c.size == 0 for c in crops):
            raise ValueError("A box is outside the input image")
        readings = engine.predict(crops)
        if len(readings) != len(subset):
            raise RuntimeError("OCR result count does not match crop count")
        for i, (box, (raw, conf)) in enumerate(zip(subset, readings)):
            conf = float(conf)
            if not math.isfinite(conf) or not 0 <= conf <= 1:
                raise ValueError("Invalid OCR confidence")
            out.append(Digit(box, str(raw), conf, start+i))
    return out


def group(digits, config):
    """Baseline-style chart grouping with typed digits and retained provenance.

    This is a geometric candidate generator, not a cartographic classifier.
    Contour labels and hazard annotations still require review.
    """
    ds = sorted([d for d in digits if d.text is not None
                 and d.confidence >= config.min_confidence],
                key=lambda d: (d.box.center[0], d.box.center[1]))
    used, out = set(), []
    for i, first in enumerate(ds):
        if i in used:
            continue
        members = [first]
        used.add(i)
        last_x, first_y = first.box.center
        for j in range(i+1, len(ds)):
            candidate = ds[j]
            x, y = candidate.box.center
            x_limit=config.tol_x*config.scale
            y_limit=config.tol_y*config.scale
            if config.grouping == 'relative':
                # Decimetre centres are lower than the integer baseline. A fixed
                # six-pixel Y limit rejected valid decimals even on the test chart.
                x_limit=max(x_limit,1.4*first.box.h)
                y_limit=max(y_limit,.6*first.box.h)
            if x-last_x > x_limit:
                break
            if j not in used and abs(y-first_y) <= y_limit:
                members.append(candidate)
                used.add(j)
                last_x = x
                if len(members) == 4:
                    break
        texts = ''.join(d.text for d in members)
        is_decimal = False
        if 2 <= len(members) <= 3:
            integers, tail = members[:-1], members[-1]
            mean_h = float(np.mean([d.box.h for d in integers]))
            mean_y = float(np.mean([d.box.center[1] for d in integers]))
            is_decimal = (tail.box.h <= config.decimal_height_ratio*mean_h
                          and tail.box.center[1]-mean_y >= config.decimal_drop*mean_h
                          and int(texts[:-1]) <= config.decimal_max_integer)
        depth = int(texts[:-1]) + int(texts[-1])/10 if is_decimal else float(texts)
        xmin = min(d.box.x for d in members)
        xmax = max(d.box.x+d.box.w for d in members)
        ymin = min(d.box.y for d in members)
        ymax = max(d.box.y+d.box.h for d in members)
        out.append(Sounding((xmin+xmax)/2, (ymin+ymax)/2, depth,
                            min(d.confidence for d in members),
                            (xmin,ymin,xmax,ymax), [d.index for d in members],
                            "subscript_decimal" if is_decimal else "integer"))
    return out
