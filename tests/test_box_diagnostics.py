"""The diagnostic export includes rejected contours and native-pixel dimensions."""
import csv
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from vetorizafb.box_diagnostics import export_box_measurements


def test_export_all_contours_with_size_and_color_exclusions(tmp_path):
    from collections import namedtuple
    Box = namedtuple('Box', 'x y w h')
    kept = Box(10, 20, 8, 18)
    thin = Box(22, 20, 2, 18)
    land = Box(36, 20, 8, 18)
    cfg = SimpleNamespace(scale=1, segmentation='black', threshold=120,
        blur_size=1, kernel_size=1, exclude_magenta=False, exclude_yellow=True,
        yellow_delta=25, yellow_min_fraction=.6,
        min_w=3, max_w=30, min_h=10, max_h=25)
    session = SimpleNamespace(path=Path('chart.tif'), rgb=np.zeros((80, 100, 3),dtype=np.uint8),
        roi=(5, 5, 60, 60), config=cfg, all_boxes=[kept, thin, land],
        boxes=[kept], color_rejected=[land])
    output = tmp_path/'boxes.csv'
    counts=export_box_measurements(session,output)
    with output.open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
    assert counts=={'mantida':1,'descartada_tamanho':1,'descartada_cor':1}
    assert [(r['x_px'],r['width_px'],r['height_px'],r['selection']) for r in rows]==[
        ('10','8','18','mantida'),('22','2','18','descartada_tamanho'),
        ('36','8','18','descartada_cor')]
    assert rows[1]['size_reasons']=='largura_abaixo_minimo'
    assert rows[0]['roi_x_px']=='5' and rows[0]['mode']=='Bruto'
