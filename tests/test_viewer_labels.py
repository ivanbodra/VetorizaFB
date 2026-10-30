"""Check the actual viewport renderer without requiring a desktop display."""
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from vetorizafb.core import Box, Digit
from vetorizafb.viewer import ChartViewer, draw_label, integer_height


def test_integer_height_excludes_lowered_decimal():
    digits = {0: Digit(Box(10, 10, 15, 60), '3', 1, 0),
              1: Digit(Box(30, 10, 15, 60), '1', 1, 1),
              2: Digit(Box(50, 90, 10, 20), '9', 1, 2)}
    sounding = dict(digit_ids=[0, 1, 2], interpretation='fb_subscript', bounds=(10, 10, 60, 110))
    assert integer_height(sounding, digits) == 60
    assert integer_height(sounding, {}) == 100


@pytest.mark.parametrize('height', [2, 60, 500])
def test_label_stays_inside_viewport(height):
    image = Image.new('RGB', (120, 50), 'black')
    draw_label(ImageDraw.Draw(image), image.size, (119, 0), '31.9', 'orange', height, 120)
    bounds = image.getbbox()
    assert bounds is not None
    assert bounds[0] < 100 and bounds[1] == 0
    assert bounds[2] <= 120 and bounds[3] < 35


@pytest.mark.parametrize('selected,expected_markers', [(False, 0), (True, 2)])
def test_small_sounding_has_label_and_only_selected_marker(monkeypatch, selected, expected_markers):
    import vetorizafb.viewer as module
    labels, markers = [], []
    monkeypatch.setattr(module, 'draw_label', lambda *args: labels.append(args))
    monkeypatch.setattr(module.ImageDraw.ImageDraw, 'ellipse', lambda *a, **kw: markers.append(a))
    monkeypatch.setattr(module.ImageTk, 'PhotoImage', lambda image: image)
    canvas = SimpleNamespace(winfo_width=lambda: 100, winfo_height=lambda: 100,
                             delete=lambda *a: None, create_image=lambda *a, **kw: None)
    sounding = dict(bounds=(20, 20, 50, 60), pixel_x=35, pixel_y=35, depth=31.9)
    session = SimpleNamespace(rgb=np.zeros((400, 400, 3), np.uint8), digits=[],
                              review=SimpleNamespace(items=[dict(id=0, current=sounding, status='unreviewed')]))
    viewer = SimpleNamespace(session=session, suspended=False, canvas=canvas, scale=.25,
                             left=0, top=0, layer=SimpleNamespace(get=lambda: 'Sondagens'),
                             measurement=None, roi=None, selected_id=0 if selected else None,
                             selected_ids=set(), render_preview_boxes=lambda: None,
                             draw_area_draft=lambda: None, zoom_text=SimpleNamespace(set=lambda v: None))
    ChartViewer.render(viewer)
    assert len(labels) == 1
    assert labels[0][3] == '31.9'
    assert len(markers) == expected_markers


def test_measure_click_uses_exact_component_box():
    calls=[]
    box=Box(20, 20, 10, 25)
    viewer=SimpleNamespace(session=SimpleNamespace(rgb=np.zeros((100,100,3),np.uint8),all_boxes=[box]),
        _press=(24, 24, 0, 0), left=0, top=0, scale=1,
        mode=SimpleNamespace(get=lambda:'Medir caractere'),
        area_shape=SimpleNamespace(get=lambda:'Retângulo'),
        canvas=SimpleNamespace(delete=lambda *args:None),
        pixel=lambda x,y:(x,y), _visible_preview=[(box,None)],
        on_action=lambda *args:calls.append(args), render=lambda:None)
    ChartViewer.release(viewer,SimpleNamespace(x=24,y=24,state=0))
    assert viewer.measurement==(20,20,30,45)
    assert calls==[('measure',(10,25))]


def test_labels_hide_below_minimum_text_width_and_have_no_white_outline():
    from vetorizafb.viewer import label_font
    image=Image.new('RGB',(120,50),'black')
    draw=ImageDraw.Draw(image)
    bounds=draw.textbbox((0,0),'8',font=label_font(12))
    width=bounds[2]-bounds[0]
    draw_label(draw,image.size,(10,25),'8','green',30,width-.1)
    assert image.getbbox() is None
    draw_label(draw,image.size,(10,25),'8','green',30,width)
    assert image.getbbox() is not None
    assert not np.asarray(image)[:, :, [0, 2]].any()
