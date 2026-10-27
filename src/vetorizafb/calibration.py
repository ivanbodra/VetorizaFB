"""Non-mutating box preview with reusable masks and contours."""
import cv2
from .area import bounds as area_bounds, polygon_mask
from .core import Box, segmentation_mask, yellow_background_fraction

MASK_KEYS = ('dpi', 'reference_dpi', 'segmentation', 'exclude_magenta', 'threshold', 'blur_size', 'kernel_size')


def size_reasons(box, config):
    reasons = []
    for axis, label in [('w', 'largura'), ('h', 'altura')]:
        value = getattr(box, axis)
        low, high = (getattr(config, p + axis) * config.scale for p in ('min_', 'max_'))
        if value <= low: reasons.append(f'{label} ≤ mínimo ({low:g} px)')
        if value >= high: reasons.append(f'{label} ≥ máximo ({high:g} px)')
    return reasons


class CalibrationPreview:
    def __init__(self):
        self.source = None
        self.fractions = {}
        self.mask_key = None
        self.mask = None
        self.contour_key = None
        self.contours = []

    def contours_for(self,session,config,roi):
        roi=session.validate_roi(roi)
        key=(id(session),tuple(getattr(config,k) for k in MASK_KEYS))
        if self.mask_key!=key:
            # Keep a full-chart mask so a different selection does not redo image treatment.
            if session.mask is not None and session.roi is None and session.seg_key is not None and all(
                getattr(config,k)==getattr(session.config,k) for k in MASK_KEYS):
                self.mask=session.mask
            else:self.mask=segmentation_mask(session.rgb,config)
            self.mask_key=key;self.contour_key=None
        contour_key=(key,roi)
        if self.contour_key!=contour_key:
            x,y,w,h=area_bounds(roi,self.mask.shape[1],self.mask.shape[0])
            crop=self.mask[y:y+h,x:x+w].copy()
            shape=polygon_mask(roi,(x,y,w,h))
            if shape is not None:crop=cv2.bitwise_and(crop,shape)
            mode=cv2.RETR_CCOMP if session.contour_revision==2 else cv2.RETR_EXTERNAL
            contours,hierarchy=cv2.findContours(crop,mode,cv2.CHAIN_APPROX_SIMPLE)
            self.contours=[Box(a+x,b+y,c,d) for i,contour in enumerate(contours)
                if session.contour_revision==1 or hierarchy[0,i,3]<0
                for a,b,c,d in [cv2.boundingRect(contour)]]
            self.contour_key=contour_key
        return self.contours

    def classify(self, session, config, roi):
        boxes=self.contours_for(session,config,roi)
        source = (self.contour_key,config.scale, config.yellow_delta)
        if source != self.source:
            self.source, self.fractions = source, {}
        result = []
        for b in boxes:
            reasons = size_reasons(b, config)
            if not reasons and config.exclude_yellow:
                if b not in self.fractions:
                    self.fractions[b] = yellow_background_fraction(session.rgb, b, config)
                if self.fractions[b] >= config.yellow_min_fraction:
                    reasons.append('fundo amarelo')
            result.append((b, '; '.join(reasons)))
        return result
