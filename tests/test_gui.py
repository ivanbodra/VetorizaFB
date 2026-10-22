"""Exercise actual Tk widgets and worker completion under Xvfb or Windows."""
import os
import sys
import time

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

pytestmark=pytest.mark.skipif(sys.platform!='win32' and not os.environ.get('DISPLAY'),reason='Needs an X display (xvfb-run) or Windows desktop')


@pytest.fixture
def app(tmp_path,monkeypatch,tk_root):
    import tkinter as tk
    from vetorizafb.gui import Application
    from vetorizafb.workflow import ChartSession
    from vetorizafb.core import Config
    path=tmp_path/'chart.tif'
    rgb=np.full((3,120,200),255,np.uint8);rgb[:,20:45,20:30]=0
    with rasterio.open(path,'w',driver='GTiff',width=200,height=120,count=3,dtype='uint8',crs='EPSG:3857',transform=from_origin(100,200,2,2)) as ds:ds.write(rgb)
    root=tk_root;errors=[];root.report_callback_exception=lambda *args:errors.append(args)
    instance=Application(root);root.geometry('1200x850')
    instance.session=ChartSession(path);instance.set_config(Config(segmentation='black'))
    instance.viewer.set_session(instance.session);root.update()
    instance.refresh_validity()
    monkeypatch.setattr('vetorizafb.gui.messagebox.showerror',lambda *a,**k:errors.append(a))
    class Reader:
        def __init__(self,*args):self.calls=0
        def predict(self,crops):self.calls+=1;return [('0',.99)]*len(crops)
    monkeypatch.setattr('vetorizafb.workflow.PaddleRecognizer',Reader)
    yield instance
    root.update()
    instance._closed=True
    root.after_cancel(instance._poll_id)
    for widget in root.winfo_children():widget.destroy()
    root.update_idletasks()
    assert not errors,errors


@pytest.fixture(scope='module')
def tk_root():
    # The application has one Tcl/Tk interpreter for its entire lifetime.
    # Reuse that lifecycle in tests instead of repeatedly destroying/recreating
    # Tcl interpreters, which was intermittent on the Windows runner.
    import tkinter as tk
    root=tk.Tk()
    yield root
    root.destroy()


def finish(app):
    until=time.monotonic()+5
    while app.busy and time.monotonic()<until:
        app.root.update();time.sleep(.01)
    app.root.update()
    assert not app.busy


def test_staged_gui_review_and_parameter_invalidation(app,monkeypatch):
    app.run_stage('all');finish(app)
    assert len(app.tree.get_children())==1
    assert app.review_ready()
    calls=app.session._engine.calls
    app.fields['tol_x'].set('35')
    assert app.export_button.instate(['disabled'])
    app.run_stage('group');finish(app)
    assert app.session._engine.calls==calls
    app.tree.selection_set('0');app.review_action('accepted')
    assert app.session.review.counts['accepted']==1
    monkeypatch.setattr('vetorizafb.gui.simpledialog.askfloat',lambda *a,**k:1.8)
    app.correct_depth()
    assert app.session.review.item(0)['current']['depth']==1.8
    assert app.session.review.counts['accepted']==0
    app.review_action('accepted')
    assert app.reviewed_button.instate(['!disabled'])
    app.fields['threshold'].set('100')
    assert app.ocr_button.instate(['disabled']) and not app.review_ready()


def test_zoom_roi_and_manual_point_tools(app,monkeypatch):
    app.run_stage('all');finish(app)
    app.viewer.zoom_to(2,50,50);app.viewer.focus(25,32.5)
    for layer in ('Original','Máscara','Caixas','OCR','Sondagens'):
        app.viewer.layer.set(layer);app.viewer.render();app.root.update()
    monkeypatch.setattr('vetorizafb.gui.simpledialog.askfloat',lambda *a,**k:2.8)
    app.canvas_action('Inserir ponto',(100,70))
    assert len(app.session.review.items)==2
    app.tree.selection_set('1');app.canvas_action('Mover selecionado',(110,75))
    assert app.session.review.item(1)['current']['pixel_x']==110
    app.set_roi((10,10,40,50))
    assert app.viewer.roi==(10,10,40,50) and not app.review_ready()


def test_save_project_from_gui(app,tmp_path,monkeypatch):
    from vetorizafb.workflow import ChartSession
    app.run_stage('all');finish(app)
    app.tree.selection_set('0');app.review_action('accepted')
    path=tmp_path/'review.vfproject.json'
    monkeypatch.setattr('vetorizafb.gui.filedialog.asksaveasfilename',lambda **k:str(path))
    app.save_project();finish(app)
    assert not app.review_dirty
    restored=ChartSession.load_project(path)
    assert restored.review.counts['accepted']==1
