"""Chart segmentation and geometric grouping, independent of the GUI/OCR model."""
from bisect import bisect_right
from dataclasses import dataclass, field
from heapq import merge
from itertools import islice
import math
import re

import cv2
import numpy as np


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    def __post_init__(self):
        if any(not isinstance(v,int) or isinstance(v,bool) for v in (self.x,self.y,self.w,self.h)) or min(self.x,self.y)<0 or min(self.w,self.h)<1:
            raise ValueError("Invalid character box")

    @property
    def center(self):
        return self.x + self.w / 2, self.y + self.h / 2


@dataclass
class Digit:
    box: Box
    raw_text: str
    confidence: float
    index: int
    alternatives: list = field(default_factory=list)
    selected_text: str | None = None
    selected_confidence: float | None = None
    method: str = "ocr"

    def __post_init__(self):
        for value in (self.confidence,self.selected_confidence):
            if value is not None and (not math.isfinite(float(value)) or not 0<=value<=1):
                raise ValueError("Invalid OCR confidence")
        if not isinstance(self.raw_text,str) or (self.selected_text is not None and re.fullmatch(r'[0-9]{1,3}',self.selected_text) is None):
            raise ValueError("Invalid OCR text/selection")

    @property
    def text(self):
        # A multi-character crop is ambiguous: never silently truncate it.
        t = (self.selected_text if self.selected_text is not None else self.raw_text).strip()
        return t if len(t) == 1 and t in "0123456789" else None

    @property
    def score(self):
        return self.confidence if self.selected_confidence is None else self.selected_confidence


def normalize_trailing_dot(digits):
    """Use an OCR digit followed by a stray dot without erasing the raw reading."""
    for digit in digits:
        if digit.text is None and re.fullmatch(r'[0-9]\.',digit.raw_text.strip()):
            digit.selected_text=digit.raw_text.strip()[0]
            digit.selected_confidence=digit.confidence
            digit.method=f'{digit.method}_trailing_dot'
    return digits


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
    flags: list = field(default_factory=list)


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
    # FB geometry ratios are local and independent of chart resolution.
    fb_decimal_distance: float = .45
    fb_integer_height_ratio: float = .75
    fb_overlap: float = .15
    fb_decimal_top_overlap: float = .25
    fb_decimal_max_gap: float = .30
    fb_decimal_left: float = .65
    fb_ambiguity_margin: float = .20
    fb_small_ratio: float = .60
    fb_keep_small: bool = False
    min_confidence: float = .35
    ocr_batch_size: int = 64
    crop_padding: int = 3
    retry_ambiguous: bool = False
    retry_one: bool = True
    exclude_yellow: bool = False
    exclude_magenta: bool = True
    yellow_delta: int = 25
    yellow_min_fraction: float = .6

    def __post_init__(self):
        fb_ratios = ('fb_decimal_distance','fb_integer_height_ratio','fb_overlap',
                     'fb_decimal_top_overlap','fb_decimal_max_gap','fb_decimal_left',
                     'fb_ambiguity_margin','fb_small_ratio')
        numeric = [getattr(self,key) for key in fb_ratios] + [self.reference_dpi, self.dpi, self.tol_x, self.tol_y,
                   self.decimal_height_ratio, self.decimal_drop,
                   self.decimal_max_integer, self.min_confidence,
                   self.threshold, self.blur_size, self.kernel_size,
                   self.min_w, self.max_w, self.min_h, self.max_h,
                   self.ocr_batch_size, self.crop_padding,self.yellow_delta,self.yellow_min_fraction]
        if not all(math.isfinite(float(v)) for v in numeric):
            raise ValueError("Configuration values must be finite")
        if not 0 < self.fb_integer_height_ratio <= 1 or not 0 < self.fb_small_ratio <= 1:
            raise ValueError('FB: as proporções de altura devem ser maiores que 0 e até 1')
        if not 0 <= self.fb_overlap < 1:
            raise ValueError('FB: sobreposição deve ser maior ou igual a 0 e menor que 1')
        for key in ('fb_decimal_distance','fb_decimal_top_overlap','fb_decimal_max_gap',
                    'fb_decimal_left','fb_ambiguity_margin'):
            if getattr(self,key)<0:raise ValueError(f'FB: {key} deve ser maior ou igual a 0')
        if self.reference_dpi <= 0 or self.dpi <= 0:
            raise ValueError("DPI must be positive")
        if not 0 <= self.threshold <= 255 or self.blur_size < 1 or self.kernel_size < 1:
            raise ValueError("Invalid threshold/blur/kernel")
        if not (0 <= self.min_w < self.max_w and 0 <= self.min_h < self.max_h):
            raise ValueError("Invalid box dimensions")
        if self.tol_x <= 0 or self.tol_y < 0 or not 0 < self.decimal_height_ratio <= 1:
            raise ValueError("Invalid grouping geometry")
        if self.decimal_drop < 0 or self.decimal_max_integer < 0 or not 0 <= self.min_confidence <= 1:
            raise ValueError("Invalid decimal/confidence setting")
        if self.segmentation not in {"legacy", "black", "fb"}:
            raise ValueError("segmentation must be legacy or black")
        if self.grouping not in {"fixed", "relative", "fb"}:
            raise ValueError("grouping must be fixed or relative")
        for key in ("threshold", "ocr_batch_size", "crop_padding", "yellow_delta"):
            if not isinstance(getattr(self, key), int) or isinstance(getattr(self, key), bool):
                raise ValueError(f"{key} must be an integer")
        if not 1 <= self.ocr_batch_size <= 1024 or not 0 <= self.crop_padding <= 100:
            raise ValueError("Invalid OCR batch size/padding")
        if not 1<=self.yellow_delta<=255 or not 0<self.yellow_min_fraction<=1:
            raise ValueError('Invalid yellow-background threshold/fraction')
        for key in ('retry_ambiguous','retry_one','exclude_yellow','exclude_magenta','fb_keep_small'):
            if not isinstance(getattr(self,key),bool):raise ValueError(f"{key} must be boolean")

    @property
    def scale(self):
        return self.dpi / self.reference_dpi


def segmentation_mask(rgb, config):
    """Foreground mask shared by processing and the parameter inspector."""
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("Expected an RGB uint8 image")
    if config.segmentation == "fb":
        from .fieldbook import mask
        return mask(rgb, config)
    s = config.scale
    magenta=None
    if config.exclude_magenta:
        red,green,blue=rgb[:,:,0],rgb[:,:,1],rgb[:,:,2]
        # Values below 100 are rejected before uint8 subtraction can wrap.
        magenta=(red>=100)&(blue>=100)&(green<=red-55)&(green<=blue-55)
    if config.segmentation == "legacy":
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        if magenta is not None:gray[magenta]=255
        blur = max(1, round(config.blur_size * s))
        blur += blur % 2 == 0
        gray = cv2.GaussianBlur(gray, (blur, blur), 0)
        _, mask = cv2.threshold(gray, config.threshold, 255, cv2.THRESH_BINARY_INV)
        k = max(1, round(config.kernel_size * s))
        mask = cv2.dilate(mask, np.ones((k, k), np.uint8), iterations=1)
    else:
        # Supplemental black-ink mask; original color crops still feed the OCR.
        mask = (rgb.max(axis=2) < config.threshold).astype(np.uint8) * 255
    if magenta is not None:mask[magenta]=0
    return mask


def yellow_background_fraction(rgb,box,config):
    """Fraction of non-dark background with R-B and G-B >= delta.

    Inspect original pixels, including a small surrounding margin for narrow
    glyphs. Signed differences prevent cyan/blue uint8 wraparound errors.
    """
    pad=max(2,round(2*config.scale));b=box;h,w=rgb.shape[:2]
    patch=rgb[max(0,b.y-pad):min(h,b.y+b.h+pad),max(0,b.x-pad):min(w,b.x+b.w+pad)].astype(np.int16)
    background=patch.max(axis=2)>=128
    count=int(background.sum())
    if not count:return 0.
    yellow=(patch[:,:,0]-patch[:,:,2]>=config.yellow_delta)&(patch[:,:,1]-patch[:,:,2]>=config.yellow_delta)
    return float(np.count_nonzero(yellow & background)/count)


def segment_details(rgb, config, *, return_rejected=False, contour_revision=2, area_mask=None):
    mask = segmentation_mask(rgb, config)
    if area_mask is not None:
        if area_mask.shape!=mask.shape:raise ValueError('Area mask dimensions do not match image')
        mask=cv2.bitwise_and(mask,area_mask)
    if contour_revision not in (1,2):raise ValueError('Unknown contour revision')
    # CCOMP places every foreground component at the top level, including
    # digits inside closed chart frames. Children are background holes in
    # glyphs/lines, not additional characters. EXTERNAL is kept only to
    # reconstruct historical project previews without rewriting saved OCR.
    mode=cv2.RETR_CCOMP if contour_revision==2 else cv2.RETR_EXTERNAL
    contours,hierarchy = cv2.findContours(mask,mode,cv2.CHAIN_APPROX_SIMPLE)
    all_boxes = [Box(*cv2.boundingRect(c)) for i,c in enumerate(contours)
                 if contour_revision==1 or hierarchy[0,i,3]<0]
    s = config.scale
    boxes = [b for b in all_boxes if config.min_w*s < b.w < config.max_w*s
             and config.min_h*s < b.h < config.max_h*s]
    rejected=[]
    if config.exclude_yellow:
        kept=[]
        for b in boxes:
            (rejected if yellow_background_fraction(rgb,b,config)>=config.yellow_min_fraction else kept).append(b)
        boxes=kept
    result=(mask,all_boxes,sorted(boxes,key=lambda b:(b.x,b.y)))
    return (*result,sorted(rejected,key=lambda b:(b.x,b.y))) if return_rejected else result


def segment(rgb, config):
    """Return boxes in ORIGINAL raster coordinates; never resize the chart."""
    return segment_details(rgb, config)[2]


class ProcessingCancelled(RuntimeError):
    pass


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise ProcessingCancelled("Processing cancelled between batches/stages")


def one_retry_candidates(digits):
    """Narrow nonnumeric strokes outside apparent words; no character guessing.

    Use a spatial grid to inspect local neighbours, rather than all pairs.
    This is a conservative retry filter, not a sounding/letter classifier.
    """
    if not digits:return []
    ambiguous={'I','l','|','!',''}
    size=max(1.,float(np.median([d.box.h for d in digits]))*2)
    grid={}
    for d in digits:
        x,y=d.box.center
        grid.setdefault((math.floor(x/size),math.floor(y/size)),[]).append(d)
    candidates=[]
    for d in digits:
        b=d.box;x,y=b.center
        if d.text is not None or d.raw_text.strip() not in ambiguous or not .15<=b.w/b.h<=.65:continue
        word=False;radius=1.8*b.h
        for gx in range(math.floor((x-radius)/size),math.floor((x+radius)/size)+1):
            for gy in range(math.floor((y-b.h*.6)/size),math.floor((y+b.h*.6)/size)+1):
                for other in grid.get((gx,gy),[]):
                    ox,oy=other.box.center;t=other.raw_text.strip()
                    if (other.index!=d.index and abs(ox-x)<=radius and abs(oy-y)<=b.h*.6
                        and .65*b.h<=other.box.h<=1.5*b.h and other.confidence>=.5
                        and t not in ambiguous and any(c.isalpha() for c in t)):
                        word=True;break
        if not word:candidates.append(d)
    return candidates


def isolated_one_crop(rgb, box, pad):
    """Remove disconnected neighbouring ink before a final directed OCR read.

    Keep the dominant component overlapping this character's original box.
    No digit value is inferred from the component and the box is not changed.
    """
    h,w=rgb.shape[:2];b=box
    x,y=max(0,b.x-pad),max(0,b.y-pad)
    patch=rgb[y:min(h,b.y+b.h+pad),x:min(w,b.x+b.w+pad)]
    gray=cv2.cvtColor(patch,cv2.COLOR_RGB2GRAY)
    _,ink=cv2.threshold(gray,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
    count,labels,stats,_=cv2.connectedComponentsWithStats(ink,connectivity=8)
    inside=labels[b.y-y:b.y-y+b.h,b.x-x:b.x-x+b.w]
    overlap=np.bincount(inside.ravel(),minlength=count);overlap[0]=0
    label=int(overlap.argmax())
    if label==0:return None
    left,top,width,height,area=map(int,stats[label])
    if (not .65*b.h<=height<=1.3*b.h or width>1.3*b.w
        or overlap[label]<max(5,.8*overlap.sum()) or overlap[label]<.6*area):
        return None
    bw=np.where(labels[top:top+height,left:left+width]==label,0,255).astype(np.uint8)
    bw=cv2.copyMakeBorder(bw,8,8,8,8,cv2.BORDER_CONSTANT,value=255)
    bw=cv2.resize(bw,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
    return cv2.cvtColor(bw,cv2.COLOR_GRAY2RGB)


def recognize(rgb, boxes, engine, batch_size=64, pad=3, *, retry=False, retry_one=False,
              min_confidence=.35, progress=None, cancel=None):
    if batch_size < 1 or pad < 0:
        raise ValueError("Invalid batch size or padding")
    out = []
    h, w = rgb.shape[:2]
    for start in range(0, len(boxes), batch_size):
        check_cancel(cancel)
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
        if progress:
            progress(min(start+len(subset), len(boxes)), len(boxes), "OCR")
    if retry or retry_one:
        # Recover difficult crops with a second *real* model reading, not a
        # guessed character or fabricated confidence. Keep both readings.
        ones=one_retry_candidates(out) if retry_one else []
        directed={d.index for d in ones}
        ambiguous = ([d for d in out if d.text is None or d.score < min_confidence]
                     if retry else ones)
        for start in range(0, len(ambiguous), batch_size):
            check_cancel(cancel)
            subset = ambiguous[start:start+batch_size]
            crops = []
            for d in subset:
                b = d.box
                crop = rgb[max(0,b.y-pad):min(h,b.y+b.h+pad),
                           max(0,b.x-pad):min(w,b.x+b.w+pad)]
                gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
                _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
                bw = cv2.copyMakeBorder(bw, 6, 6, 6, 6, cv2.BORDER_CONSTANT, value=255)
                bw = cv2.resize(bw, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                crops.append(cv2.cvtColor(bw, cv2.COLOR_GRAY2RGB))
            readings = engine.predict(crops)
            if len(readings) != len(subset):
                raise RuntimeError("Retry OCR result count does not match crop count")
            for d, (raw, conf) in zip(subset, readings):
                raw, conf = str(raw), float(conf)
                if not math.isfinite(conf) or not 0 <= conf <= 1:
                    raise ValueError("Invalid retry OCR confidence")
                d.alternatives.append(dict(text=raw, confidence=conf, method="binary_padded_2x"))
                is_one=d.index in directed
                eligible=(raw.strip()=='1' and conf>=max(.8,min_confidence) if is_one else
                          len(raw.strip())==1 and raw.strip() in '0123456789' and conf>=min_confidence)
                if eligible:
                    if d.text is None or conf > d.score:
                        d.selected_text, d.selected_confidence, d.method = raw.strip(), conf, "ocr_one_retry" if is_one else "ocr_retry"
            if progress:
                progress(min(start+len(subset),len(ambiguous)),len(ambiguous),"OCR retry" if retry else "OCR: reler possíveis 1")
        # A neighbour's small detached fragment can turn a true one into '1.'.
        # Re-read its isolated ink instead of stripping/truncating model text.
        remaining=[d for d in ones if d.text is None]
        for start in range(0,len(remaining),batch_size):
            check_cancel(cancel)
            subset=[];crops=[]
            for d in remaining[start:start+batch_size]:
                crop=isolated_one_crop(rgb,d.box,pad)
                if crop is not None:subset.append(d);crops.append(crop)
            if not crops:continue
            readings=engine.predict(crops)
            if len(readings)!=len(subset):raise RuntimeError('Isolated OCR result count does not match crop count')
            for d,(raw,conf) in zip(subset,readings):
                raw,conf=str(raw),float(conf)
                if not math.isfinite(conf) or not 0<=conf<=1:raise ValueError('Invalid isolated OCR confidence')
                d.alternatives.append(dict(text=raw,confidence=conf,method='isolated_component_padded_2x'))
                if raw.strip()=='1' and conf>=max(.8,min_confidence):
                    d.selected_text,d.selected_confidence,d.method='1',conf,'ocr_one_isolated'
            if progress:progress(min(start+batch_size,len(remaining)),len(remaining),'OCR: isolar possíveis 1')
    check_cancel(cancel)
    return normalize_trailing_dot(out)


def group(digits, config):
    if config.grouping == "fb":
        from .fieldbook import group as fb_group
        return fb_group(digits, config)
    """Baseline-style chart grouping with typed digits and retained provenance.

    This is a geometric candidate generator, not a cartographic classifier.
    Contour labels and hazard annotations still require review.
    """
    ds = sorted([d for d in digits if d.text is not None
                 and d.score >= config.min_confidence],
                key=lambda d: (d.box.center[0], d.box.center[1]))
    # Y buckets avoid scanning a full vertical column. Merge candidates by their
    # original X-sorted index so the existing greedy grouping decisions survive.
    bin_size = max(config.tol_y*config.scale,
                   float(np.median([d.box.h for d in ds]))*.6 if ds and config.grouping == 'relative' else 1, 1)
    bins = {}
    for i, d in enumerate(ds):
        bins.setdefault(math.floor(d.box.center[1]/bin_size), []).append(i)
    used, out = set(), []
    for i, first in enumerate(ds):
        if i in used:
            continue
        members = [first]
        used.add(i)
        last_x, first_y = first.box.center
        x_limit=config.tol_x*config.scale
        y_limit=config.tol_y*config.scale
        if config.grouping == 'relative':
            x_limit=max(x_limit,1.4*first.box.h)
            y_limit=max(y_limit,.6*first.box.h)
        streams = []
        for bucket in range(math.floor((first_y-y_limit)/bin_size),
                            math.floor((first_y+y_limit)/bin_size)+1):
            indices = bins.get(bucket, [])
            streams.append(islice(indices, bisect_right(indices, i), None))
        for j in merge(*streams):
            candidate = ds[j]
            x, y = candidate.box.center
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
        flags = ["ocr_retry"] if any(d.method != "ocr" for d in members) else []
        if any(d.method in {'ocr_one_retry','ocr_one_isolated'} for d in members):flags.append('ocr_one_retry')
        out.append(Sounding((xmin+xmax)/2, (ymin+ymax)/2, depth,
                            min(d.score for d in members),
                            (xmin,ymin,xmax,ymax), [d.index for d in members],
                            "subscript_decimal" if is_decimal else "integer", flags=flags))
    return out
