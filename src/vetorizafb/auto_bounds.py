"""Suggest per-chart character dimensions from unfiltered contour geometry."""
import math

import numpy as np


def suggest_bounds(boxes, scale):
    """Return strict bounds in chart pixels; never mistake current filtering for labels.

    Height-weighted frequency suppresses abundant one-pixel specks. The main
    height band is intentionally broad enough to contain smaller numerals; a
    conditional width distribution also retains narrow, full-height glyphs.
    """
    if not boxes or not math.isfinite(scale) or scale <= 0:
        raise ValueError('Não há caixas suficientes para estimar as dimensões.')
    sizes = np.asarray([(b.w, b.h) for b in boxes], dtype=np.float64)
    widths, heights = sizes.T
    plausible = ((heights >= max(5, 8 * scale)) & (widths >= 2) &
                 (widths / heights >= .22) & (widths / heights <= 1.25))
    if np.count_nonzero(plausible) < 30:
        raise ValueError('Poucas caixas com dimensões compatíveis; ajuste a área ou o tratamento da imagem.')
    histogram = np.bincount(heights[plausible].astype(int))
    heights_px = np.arange(len(histogram))
    dominant = int(np.argmax(histogram * heights_px))
    band = plausible & (heights >= .62 * dominant) & (heights <= 1.18 * dominant)
    if np.count_nonzero(band) < 30:
        raise ValueError('Não foi encontrada uma faixa de dimensões consistente.')
    # The segmentation uses strict inequalities. Include one chart pixel outside
    # the 5th–95th percentile interval so boundary-sized characters survive.
    min_w, max_w = np.percentile(widths[band], [5, 95])
    min_h, max_h = np.percentile(heights[band], [5, 95])
    return (max(.01, math.floor(min_w) - 1), math.ceil(max_w) + 1,
            max(.01, math.floor(min_h) - 1), math.ceil(max_h) + 1)
