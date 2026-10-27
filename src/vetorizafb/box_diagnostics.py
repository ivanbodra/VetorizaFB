"""Export every prepared contour for chart-specific size analysis."""
import csv
import os
from pathlib import Path
import tempfile
from .area import bounds as area_bounds


HEADERS = (
    'chart', 'image_width_px', 'image_height_px',
    'roi_x_px', 'roi_y_px', 'roi_width_px', 'roi_height_px',
    'mode', 'clarity', 'blur_px', 'dilation_px', 'ignore_magenta',
    'discard_on_land', 'yellow_sensitivity', 'yellow_coverage_pct',
    'current_min_width_px', 'current_max_width_px',
    'current_min_height_px', 'current_max_height_px',
    'box_id', 'x_px', 'y_px', 'width_px', 'height_px',
    'area_px2', 'width_over_height', 'touches_roi_border',
    'selection', 'size_reasons',
)


def export_box_measurements(session, destination):
    """Write a single CSV; no OCR, chart pixels, or review decisions are exported."""
    if session.all_boxes is None:
        raise ValueError('Execute Preparar antes de exportar as medidas das caixas.')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    height, width = session.rgb.shape[:2]
    rx, ry, rw, rh = area_bounds(session.roi,width,height)
    config = session.config
    scale = config.scale
    kept = set(session.boxes or [])
    rejected_color = set(session.color_rejected)
    metadata = (
        session.path.name, width, height, rx, ry, rw, rh,
        {'legacy': 'Realce', 'black': 'Bruto'}.get(config.segmentation, config.segmentation),
        config.threshold, config.blur_size * scale, config.kernel_size * scale,
        config.exclude_magenta, config.exclude_yellow, 256 - config.yellow_delta,
        100 * config.yellow_min_fraction,
        config.min_w * scale, config.max_w * scale,
        config.min_h * scale, config.max_h * scale,
    )
    counts = {'mantida': 0, 'descartada_tamanho': 0, 'descartada_cor': 0}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8-sig', newline='',
                                         dir=destination.parent, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            writer = csv.writer(stream)
            writer.writerow(HEADERS)
            for index, box in enumerate(session.all_boxes):
                reasons = []
                if box.w <= config.min_w * scale:reasons.append('largura_abaixo_minimo')
                if box.w >= config.max_w * scale:reasons.append('largura_acima_maximo')
                if box.h <= config.min_h * scale:reasons.append('altura_abaixo_minimo')
                if box.h >= config.max_h * scale:reasons.append('altura_acima_maximo')
                selection = ('mantida' if box in kept else
                             'descartada_cor' if box in rejected_color else 'descartada_tamanho')
                counts[selection] += 1
                border = box.x <= rx or box.y <= ry or box.x + box.w >= rx + rw or box.y + box.h >= ry + rh
                writer.writerow((*metadata, index, box.x, box.y, box.w, box.h,
                                 box.w * box.h, round(box.w / box.h, 5), border,
                                 selection, ';'.join(reasons)))
        os.replace(temporary, destination)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return counts
