"""Non-mutating size preview over the last segmentation's native contours."""
from .core import yellow_background_fraction

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

    def classify(self, session, config, roi):
        if session.all_boxes is None or session.seg_key is None:
            raise ValueError('Execute a etapa 1 para obter os contornos.')
        if roi != session.roi or any(getattr(config, k) != getattr(session.config, k) for k in MASK_KEYS):
            raise ValueError('Máscara ou área alterada: execute a etapa 1 para renovar a prévia.')
        source = (id(session), id(session.all_boxes), config.scale, config.yellow_delta)
        if source != self.source:
            self.source, self.fractions = source, {}
        result = []
        for b in session.all_boxes:
            reasons = size_reasons(b, config)
            if not reasons and config.exclude_yellow:
                if b not in self.fractions:
                    self.fractions[b] = yellow_background_fraction(session.rgb, b, config)
                if self.fractions[b] >= config.yellow_min_fraction:
                    reasons.append('fundo amarelo')
            result.append((b, '; '.join(reasons)))
        return result
