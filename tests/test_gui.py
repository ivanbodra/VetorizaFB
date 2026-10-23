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


def review_points(app):
    app.run_stage('all');finish(app)
    # A viewport smaller than the chart is necessary to verify following/zoom.
    app.session.rgb=np.full((1000,2000,3),255,np.uint8)
    for x,y in [(400,250),(800,450),(1200,650)]:app.session.review.add_manual(x,y,11.1)
    app.refresh_points();app.refresh_validity();app.clear_point_selection()


def key(app,sequence,widget=None):
    widget=widget or app.tree
    widget.focus_force();app.root.update()
    widget.event_generate(sequence);app.root.update()


def test_keyboard_navigation_range_and_zoom_follow_active_point(app):
    review_points(app)
    key(app,'<Down>');assert app.tree.selection()==('0',)
    key(app,'<Right>');assert app.tree.selection()==('1',)
    key(app,'<Shift-Right>')
    assert app.tree.selection()==('1','2') and app.tree.focus()=='2'
    assert app.viewer.selected_id==2 and app.viewer.selected_ids=={1,2}
    cx,cy=app.viewer.pixel(app.viewer.canvas.winfo_width()/2,app.viewer.canvas.winfo_height()/2)
    assert (cx,cy)==pytest.approx((800,450))
    scale=app.viewer.scale
    key(app,'<Shift-Right>');assert app.tree.selection()==('1','2','3')
    assert app.viewer.scale==scale  # no cumulative zoom on each arrow
    key(app,'<Control-space>');assert app.tree.selection()==('1','2')
    assert app.tree.focus()=='3' and app.viewer.selected_id==3
    app.follow_review.set(False);left,top,scale=app.viewer.left,app.viewer.top,app.viewer.scale
    key(app,'<Left>')
    assert (app.viewer.left,app.viewer.top,app.viewer.scale)==(left,top,scale)
    key(app,'<Escape>');assert not app.tree.selection() and app.viewer.selected_id is None


def test_keyboard_batch_approval_exclusion_edit_and_filtered_selection(app,monkeypatch):
    review_points(app)
    key(app,'<Control-Shift-A>')
    assert len(app.tree.selection())==4
    app.review_note.set('Conferido na carta')
    key(app,'<Control-a>')
    assert app.session.review.counts['accepted']==4
    assert all(i['history'][-1]['note']=='Conferido na carta' for i in app.session.review.items)
    app.clear_point_selection();app.navigate_review(1);key(app,'<Control-x>')
    assert app.session.review.item(0)['status']=='rejected'
    monkeypatch.setattr('vetorizafb.gui.simpledialog.askfloat',lambda *a,**k:10.1)
    key(app,'<Down>');key(app,'<Control-e>')
    assert app.session.review.item(1)['current']['depth']==10.1
    assert app.session.review.item(1)['status']=='unreviewed'
    app.filter.set('Pendentes');app.refresh_points()
    key(app,'<Control-Shift-A>');assert app.tree.selection()==('1',)
    key(app,'<Control-a>');assert not app.tree.get_children()
    assert app.session.review.counts=={'accepted':3,'rejected':1,'unreviewed':0}
    assert app.viewer.selected_ids==set() and app.viewer.selected_id is None


def test_pending_filter_advances_and_text_fields_keep_their_keys(app):
    review_points(app)
    app.filter.set('Pendentes');app.refresh_points();key(app,'<Down>')
    key(app,'<Control-a>')
    assert app.tree.selection()==('1',) and app.viewer.selected_id==1
    key(app,'<Control-x>');assert app.tree.selection()==('2',)
    before=app.session.review.counts.copy()
    app.review_note.set('Editar esta nota')
    key(app,'<Control-a>',app.note_entry)
    key(app,'<Left>',app.note_entry)
    assert app.session.review.counts==before and app.tree.selection()==('2',)
    app.fields['threshold'].set('100')
    key(app,'<Control-a>');key(app,'<Control-x>')
    assert app.session.review.counts==before


def test_canvas_toggle_range_and_invert_selection(app):
    review_points(app);app.viewer.layer.set('Sondagens')
    app.canvas_action('Inspecionar',(400,250))
    app.canvas_action('toggle_point',(1200,650))
    assert app.tree.selection()==('1','3') and app.viewer.selected_id==3
    app.canvas_action('toggle_point',(400,250))
    assert app.tree.selection()==('3',)
    app.canvas_action('range_point',(1200,650))
    assert app.tree.selection()==('1','2','3')
    app.invert_point_selection();assert app.tree.selection()==('0',)
    key(app,'<Control-a>',app.viewer.canvas)
    assert app.session.review.item(0)['status']=='accepted'


def test_direct_insert_move_buttons_and_hidden_pending_point_focus(app,monkeypatch):
    review_points(app);app.session.review.change(0,'accepted')
    app.filter.set('Aprovados');app.refresh_points()
    app.review_note.set('Manual sounding')
    app.review_buttons['insert'].invoke()
    assert app.viewer.mode.get()=='Inserir ponto'
    monkeypatch.setattr('vetorizafb.gui.simpledialog.askfloat',lambda *a,**k:1.9)
    app.canvas_action('Inserir ponto',(100,70))
    assert app.filter.get()=='Todos' and app.tree.focus()=='4'
    assert app.tree.selection()==('4',) and app.viewer.selected_id==4
    assert app.session.review.item(4)['history'][-1]['note']=='Manual sounding'
    assert app.viewer.mode.get()=='Inspecionar'
    app.review_action('accepted');app.review_buttons['move'].invoke()
    app.canvas_action('Mover selecionado',(120,80))
    item=app.session.review.item(4)
    assert (item['current']['pixel_x'],item['current']['pixel_y'])==(120,80)
    assert item['status']=='unreviewed' and item['current']['confidence'] is None
    assert app.viewer.mode.get()=='Inspecionar'
    app.review_buttons['insert'].invoke();key(app,'<Escape>',app.viewer.canvas)
    assert app.viewer.mode.get()=='Inspecionar' and len(app.session.review.items)==5


def test_real_numeric_position_dialog_accepts_decimal_comma(app):
    from vetorizafb.dialogs import PositionDialog
    review_points(app);app.navigate_review(1);app.review_action('accepted')
    def enter():
        dialog=next(w for w in app.root.winfo_children() if isinstance(w,PositionDialog))
        try:dialog.x.set('40,5');dialog.y.set('50');dialog.ok()
        finally:
            if dialog.winfo_exists():dialog.cancel()
    app.root.after(80,enter)
    app.review_buttons['position'].invoke();app.root.update()
    item=app.session.review.item(0)
    assert (item['current']['pixel_x'],item['current']['pixel_y'])==(40.5,50)
    assert item['status']=='unreviewed'


def test_real_offset_dialog_previews_all_points_despite_active_filter(app):
    from copy import deepcopy
    from vetorizafb.dialogs import OffsetDialog
    review_points(app);app.session.review.change(0,'accepted');app.session.review.change(2,'rejected')
    app.filter.set('Aprovados');app.refresh_points()
    before=deepcopy(app.session.review.items)
    def enter():
        dialog=next(w for w in app.root.winfo_children() if isinstance(w,OffsetDialog))
        try:
            dialog.x.set('4');dialog.y.set('-2');dialog.preview()
            assert app.session.review.items==before
            assert '4 sondagens' in dialog.preview_text.get()
            dialog.ok()
        finally:
            if dialog.winfo_exists():dialog.cancel()
    app.root.after(80,enter)
    app.review_buttons['offset'].invoke();app.root.update()
    assert len(app.session.review.items)==4
    assert app.session.review.item(0)['status']=='unreviewed'
    assert app.session.review.item(2)['status']=='rejected'
    for old,item in zip(before,app.session.review.items):
        assert item['current']['pixel_x']==old['current']['pixel_x']+4
        assert item['current']['pixel_y']==old['current']['pixel_y']-2


def test_gui_yellow_filter_configuration_invalidation_and_layer(app):
    app.run_stage('all');finish(app)
    app.fields['exclude_yellow'].set(True)
    assert not app.review_ready() and app.ocr_button.instate(['disabled'])
    app.session.rgb[:]=(245,245,120);app.session.rgb[20:45,20:30]=0
    app.run_stage('segment');finish(app)
    assert len(app.session.color_rejected)==1 and app.session.boxes==[]
    app.viewer.layer.set('Rejeitadas por cor');app.viewer.render();app.root.update()
    assert 'Cor: 1 rejeitadas' in app.counts.get()


def test_review_controls_and_notes_remain_visible_at_minimum_window_size(app):
    app.root.geometry('1050x720');app.root.update()
    for widget in [app.note_entry,app.footer,*app.review_buttons.values()]:
        assert widget.winfo_ismapped()
        assert widget.winfo_rooty()+widget.winfo_height()<=app.root.winfo_rooty()+app.root.winfo_height()
