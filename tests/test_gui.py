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
    models=tmp_path/'models'/'PP-OCRv6_small_rec';models.mkdir(parents=True)
    (models/'inference.yml').write_text('Global:\n  model_name: PP-OCRv6_small_rec\n')
    (models/'inference.json').write_text('{}');(models/'inference.pdiparams').write_bytes(b'test fixture')
    monkeypatch.setenv('VETORIZAFB_MODELS_DIR',str(models.parent))
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
    if instance._preview_id:root.after_cancel(instance._preview_id)
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


def finish_preview(app):
    until=time.monotonic()+5
    while (app._preview_busy or app._preview_id) and time.monotonic()<until:
        app.root.update();time.sleep(.01)
    app.root.update()
    assert not app._preview_busy and app._preview_id is None


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
    for layer in ('Original','Editada','Caixas','Dígitos','Sondagens'):
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
    for widget in [app.note_entry,app.note_button,app.footer,*app.toolbar_widgets]:
        assert widget.winfo_ismapped()
        assert widget.winfo_rooty()+widget.winfo_height()<=app.root.winfo_rooty()+app.root.winfo_height()


def test_live_preview_reuses_contours_and_updates_mask_without_mutating_review(app):
    from vetorizafb.calibration import MASK_KEYS
    app.run_stage('all');finish(app)
    boxes=app.session.boxes;digits=app.session.digits;review=app.session.review
    app.viewer.layer.set('Caixas');app.update_preview();finish_preview(app)
    assert app.viewer.preview_boxes and not app.viewer.preview_boxes[0][1]
    app.live_preview.set(True);app.fields['min_w'].set('15');finish_preview(app)
    assert 'largura' in app.viewer.preview_boxes[0][1]
    assert app.session.boxes is boxes and app.session.digits is digits and app.session.review is review
    assert not app.session.valid_segments(app.config())
    app.fields['threshold'].set('100');finish_preview(app)
    assert app.session.digits is digits and app.session.review is review
    assert app.preview.mask_key[1][MASK_KEYS.index('threshold')]==100


def test_measurement_uses_native_pixels_independent_of_zoom(app):
    from types import SimpleNamespace
    app.run_stage('segment');finish(app)
    app.measure_character();v=app.viewer
    for scale in (2,4):
        v.scale=scale;v.left=v.top=0
        v.press(SimpleNamespace(x=20*scale,y=20*scale))
        v.release(SimpleNamespace(x=30*scale,y=45*scale,state=0))
        assert app.measurement==(10,25)
    app.fields['dpi'].set('300')
    app.canvas_action('measure',(10,25))
    assert app.measure_text.get()=='10 × 25 px'
    app.use_measurement(True)
    assert app.fields['min_w'].get()=='9' and app.fields['min_h'].get()=='24'


def test_manual_about_and_preview_toggle(app,monkeypatch):
    from pathlib import Path
    from vetorizafb import __version__
    assert __version__=='4.0.5' and '4.0.5' in app.root.title()
    urls=[];monkeypatch.setattr('vetorizafb.gui.webbrowser.open',lambda url:urls.append(url) or True)
    app.open_manual();assert urls[0].startswith('file:') and urls[0].endswith('manual_ptbr.html')
    popup=app.about();app.root.update();assert popup.winfo_exists();popup.destroy()
    app.run_stage('segment');finish(app);app.viewer.layer.set('Caixas')
    app.fields['min_w'].set('15');app.update_preview();finish_preview(app)
    app.viewer.scale=2;app.viewer.render();assert app.viewer._visible_preview
    app.viewer.show_rejected.set(False);app.viewer.render();assert not app.viewer._visible_preview


def test_original_icon_is_loaded_and_persisted(app,tmp_path,monkeypatch):
    from PIL import Image
    source=tmp_path/'original.png';Image.new('RGBA',(32,32),'navy').save(source)
    monkeypatch.setenv('APPDATA',str(tmp_path/'preferences'))
    monkeypatch.setattr('vetorizafb.gui.filedialog.askopenfilename',lambda **kw:str(source))
    app.choose_icon()
    assert app.icon_path.read_bytes()==source.read_bytes()
    from vetorizafb.branding import apply_icon
    assert apply_icon(app.root)==app.icon_path
    assert app.brand_icon.cget('image')


def test_execution_controls_remain_visible_at_minimum_window(app):
    app.root.geometry('1050x720');app.root.update()
    for widget in (app.run_button,app.cancel_button,app.progress):
        assert widget.winfo_ismapped()
        assert widget.winfo_rooty()+widget.winfo_height()<=app.root.winfo_rooty()+app.root.winfo_height()


def test_bundled_identity_works_without_user_icon(app,tmp_path,monkeypatch):
    from pathlib import Path
    from vetorizafb.branding import apply_icon,asset_photo
    monkeypatch.setenv('APPDATA',str(tmp_path/'empty'))
    icon=apply_icon(app.root)
    assert icon.name=='logo_vetorizafb.ico' and icon.parent.name=='assets'
    assert len(app.root._vetorizafb_icons)==5
    photo=asset_photo(app.root,'logo_vetorizaFB.png',(100,100))
    assert photo.width()==100 and photo.height()==74
    popup=app.about();app.root.update()
    assert len(popup._brand_images)==3
    popup.destroy()


def test_last_selected_icon_format_has_priority(app,tmp_path,monkeypatch):
    from pathlib import Path
    from PIL import Image
    from vetorizafb.branding import apply_icon
    monkeypatch.setenv('APPDATA',str(tmp_path/'preferences'))
    ico=Path(__file__).parents[1]/'src/vetorizafb/assets/logo_vetorizafb.ico'
    png=tmp_path/'new.png';Image.new('RGBA',(32,32),'teal').save(png)
    for source in (ico,png,ico):
        monkeypatch.setattr('vetorizafb.gui.filedialog.askopenfilename',lambda **kw:str(source))
        app.choose_icon()
        assert apply_icon(app.root)==app.icon_path
        assert app.icon_path.suffix==source.suffix


def test_tab_readiness_tracks_stage_invalidation_without_status_row(app):
    from tkinter import ttk
    assert app.stage_states==['pending']*4
    assert not [w for w in app.chart_entry.master.winfo_children() if isinstance(w,ttk.Label) and str(w.cget('textvariable'))==str(app.validity)]
    app.run_stage('all');finish(app)
    assert app.stage_states==['ready']*4
    app.fields['tol_x'].set('35')
    assert app.stage_states==['ready','ready','pending','pending']
    app.fields['min_w'].set('4')
    assert app.stage_states==['pending']*4
    assert app.ocr_button.instate(['disabled'])
    app.session=None;app.refresh_validity()
    assert app.stage_states==['empty']*4


def test_cn_prompt_distinguishes_loaded_and_new_paths(app):
    app.path.set(str(app.session.path));assert app.chart_entry.cget('style')=='TEntry'
    app.path.set(str(app.session.path.parent/'other.tif'))
    assert app.chart_entry.cget('style')=='Required.TEntry'
    app.path.set('');assert app.chart_entry.cget('style')=='Required.TEntry'


def test_compact_toolbar_never_cuts_actions_and_has_no_details_strip(app):
    app.root.geometry('1050x720');app.root.update()
    bar=app.review_buttons['accepted'].master
    for button in app.toolbar_widgets:
        assert button.winfo_x()>=0
        assert button.winfo_x()+button.winfo_width()<=bar.winfo_width()
    app.viewer.layer.set('Original');app.viewer.mode.set('Inspecionar');app.root.update()
    assert not hasattr(app.viewer,'details')
    assert app.viewer.canvas.winfo_height()>=220
    app.viewer.layer.set('Caixas');app.root.update()
    app.viewer.layer.set('Original');app.viewer.mode.set('Medir caractere');app.root.update()


def test_context_help_preserves_review_selection_and_tooltip_lifecycle(app,monkeypatch):
    from types import SimpleNamespace
    from vetorizafb.ui import Tooltip
    review_points(app);app.tree.selection_set(('0','1'));before=app.session.review.counts.copy()
    # Native Windows popup menus wait for user input; exercise real menu entries
    # and review actions without entering that OS-owned modal loop in CI.
    monkeypatch.setattr('tkinter.Menu.tk_popup',lambda *args,**kwargs:None)
    app.show_review_menu(SimpleNamespace(x_root=100,y_root=100))
    app.review_menu.unpost()
    assert app.tree.selection()==('0','1') and app.session.review.counts==before
    # A contextual action applies to the existing selection, exactly like the button.
    app.review_menu.invoke(0)
    assert app.session.review.counts['accepted']==2
    popup=app.show_shortcuts();app.root.update();popup.destroy()
    tip=Tooltip(app.review_buttons['accepted'],'Aprovar · Ctrl+A')
    tip.show();assert tip.popup.winfo_exists()
    tip.hide();assert tip.popup is None
    tip.schedule();assert tip.pending
    tip.hide();assert tip.pending is None


def test_model_panel_lists_only_complete_local_models_and_selection_invalidates_ocr(app):
    from test_models import model_files
    from vetorizafb.models import MODEL_NAMES
    app.run_stage('all');finish(app)
    root=__import__('pathlib').Path(app.models_root.get())
    model_files(root/MODEL_NAMES[1],MODEL_NAMES[1]);(root/'partial').mkdir()
    app.refresh_models()
    assert set(app.local_model_combo.cget('values'))==set(MODEL_NAMES[:2])
    app.model.set(MODEL_NAMES[1]);app.local_model_combo.event_generate('<<ComboboxSelected>>');app.root.update()
    assert app.model_dir.get()==str(root/MODEL_NAMES[1])
    assert not app.review_ready() and app.group_button.instate(['disabled'])


def test_ocr_without_model_never_starts_an_implicit_download(app,tmp_path,monkeypatch):
    errors=[];monkeypatch.setattr('vetorizafb.gui.messagebox.showerror',lambda *args,**kwargs:errors.append(args))
    app.models_root.set(str(tmp_path/'empty'));app.refresh_models()
    assert app.local_model_combo.cget('values')==''
    app.run_stage('all')
    assert not app.busy and app.session._engine is None
    assert 'Conexão / baixar' in errors[0][1]
    app.run_stage('segment');finish(app)
    assert app.session.boxes is not None


def test_explicit_download_populates_local_selector_and_never_saves_password(app,tmp_path,monkeypatch):
    from test_models import model_files
    from vetorizafb.models import ConnectionSettings,MODEL_NAMES,LocalModel,preferences_path
    cfg=ConnectionSettings(mode='proxy',server='proxy.example:3128',username='operator',password='private-secret')
    class Dialog:
        result=(MODEL_NAMES[1],cfg)
        def __init__(self,*args):pass
    monkeypatch.setenv('APPDATA',str(tmp_path/'settings'))
    monkeypatch.setattr('vetorizafb.gui.ModelDownloadDialog',Dialog)
    calls=[]
    def download(name,root,connection,**kwargs):
        calls.append(connection);path=model_files(__import__('pathlib').Path(root)/name,name)
        kwargs['progress'](10,10);return LocalModel(name,path)
    monkeypatch.setattr('vetorizafb.gui.download_model',download)
    app.configure_model_download();finish(app)
    assert calls==[cfg] and app.model.get()==MODEL_NAMES[1]
    assert app.model_dir.get().endswith(MODEL_NAMES[1])
    assert 'private-secret' not in preferences_path().read_text()
    assert 'operator' not in preferences_path().read_text()
    assert app.session.digits is None  # download never runs OCR


def test_real_proxy_dialog_validates_mode_and_keeps_credentials_in_memory(app):
    from vetorizafb.model_dialog import ModelDownloadDialog
    from vetorizafb.models import ConnectionSettings
    def enter():
        dialog=next(w for w in app.root.winfo_children() if isinstance(w,ModelDownloadDialog))
        try:
            assert all(field.instate(['disabled']) for field in dialog.proxy_fields)
            dialog.mode.set('Proxy');assert all(field.instate(['!disabled']) for field in dialog.proxy_fields)
            dialog.server.set('proxy.example:3128');dialog.username.set('operator');dialog.password.set('private-secret')
            dialog.ok()
        finally:
            if dialog.winfo_exists():dialog.cancel()
    app.root.after(100,enter)
    dialog=ModelDownloadDialog(app.root,app.models_root.get(),ConnectionSettings())
    assert dialog.result[1].mode=='proxy' and dialog.result[1].password=='private-secret'


def test_native_pixel_fields_preserve_historical_config(app):
    from dataclasses import replace
    from vetorizafb.core import Config, segment_details
    old=Config(dpi=300,reference_dpi=600,segmentation='legacy',min_w=3,max_w=71,blur_size=5)
    app.set_config(old)
    assert app.fields['min_w'].get()=='1.5'
    assert app.fields['max_w'].get()=='35.5'
    assert app.fields['segmentation'].get()=='Realce'
    assert app.fields['yellow_min_fraction'].get()=='60'
    assert app.config()==old
    a=segment_details(app.session.rgb,app.config());b=segment_details(app.session.rgb,old)
    np.testing.assert_array_equal(a[0],b[0])
    assert a[1:]==b[1:]
    app.fields['min_w'].set('2')
    assert app.config().min_w*app.config().scale==2
    app.set_config(replace(old,dpi=450))
    assert app.config()==replace(old,dpi=450)


def test_color_controls_have_intuitive_direction(app):
    from vetorizafb.core import Config
    app.set_config(Config(yellow_delta=25,yellow_min_fraction=.6))
    baseline=app.config()
    app.fields['yellow_delta'].set(str(int(app.fields['yellow_delta'].get())+5))
    app.fields['yellow_min_fraction'].set('75')
    assert app.config().yellow_delta==baseline.yellow_delta-5
    assert app.config().yellow_min_fraction==.75


def test_compact_stage_names_and_native_pixel_controls(app):
    from tkinter import ttk
    assert [app.tabs.tab(i,'text') for i in range(4)]==['Preparar','Reconhecer','Agrupar','Exportar']
    def descendants(parent):
        for child in parent.winfo_children():
            yield child
            yield from descendants(child)
    widgets=list(descendants(app.root))
    labels=[str(w.cget('text')) for w in widgets if isinstance(w,ttk.Label)]
    assert not any('DPI' in text for text in labels)
    combos=[w for w in widgets if isinstance(w,ttk.Combobox)]
    assert tuple(app.viewer.layer_combo.cget('values'))==('Original','Editada','Caixas')
    assert any(tuple(w.cget('values'))==('Realce','Bruto') for w in combos)
    app.root.geometry('1050x720');app.root.update()
    import tkinter as tk
    visible=set()
    for x in range(app.tabs.winfo_width()):
        try:visible.add(app.tabs.index(f'@{x},10'))
        except tk.TclError:pass
    assert visible=={0,1,2,3}


def test_preview_is_opt_in_and_digit_layer_requires_ocr(app):
    assert not app.live_preview.get()
    assert app._preview_id is None
    app.fields['min_w'].set('4')
    assert app._preview_id is None
    app.run_stage('segment');finish(app)
    assert app.viewer.layer.get()=='Caixas' and app.viewer.preview_boxes
    assert 'Dígitos' not in app.viewer.layer_combo.cget('values')
    app.live_preview.set(True);app.toggle_live_preview()
    assert app._preview_id is not None
    app.live_preview.set(False);app.toggle_live_preview()
    assert app._preview_id is None
    app.run_stage('ocr');finish(app)
    assert 'Dígitos' in app.viewer.layer_combo.cget('values')


def test_enabling_preview_prepares_boxes_and_opens_layer(app):
    assert app.session.all_boxes is None
    app.live_preview.set(True);app.toggle_live_preview();finish_preview(app)
    assert app.viewer.layer.get()=='Caixas'
    assert app.session.all_boxes is None
    assert app.viewer.preview_boxes
    app.live_preview.set(False);app.toggle_live_preview()
    app.fields['min_w'].set('4')
    assert app._preview_id is None


def test_review_header_sort_is_numeric_and_persists_without_mutating_model(app):
    from copy import deepcopy
    app.run_stage('all');finish(app)
    review=app.session.review
    review.add_manual(30,30,10)
    review.add_manual(35,35,2)
    review.add_manual(40,40,-1)
    before=deepcopy(review.items);app.refresh_points()
    app.sort_review('depth')
    assert [float(app.tree.set(row,'depth')) for row in app.tree.get_children()]==[-1,0,2,10]
    target=app.tree.get_children()[1];app.tree.selection_set(target);app.tree.focus(target)
    app.sort_review('depth')
    assert [float(app.tree.set(row,'depth')) for row in app.tree.get_children()]==[10,2,0,-1]
    assert app.tree.selection()==(target,) and app.tree.focus()==target
    app.refresh_points()
    assert [float(app.tree.set(row,'depth')) for row in app.tree.get_children()]==[10,2,0,-1]
    app.sort_review('confidence')
    assert app.tree.set(app.tree.get_children()[0],'confidence')!=''
    app.sort_review('confidence')
    assert app.tree.set(app.tree.get_children()[0],'confidence')!=''
    assert review.items==before
    assert app.review_filter.master is app.tree.master.winfo_children()[0]


def test_restore_menu_restores_selected_original_without_touching_manual(app):
    app.run_stage('all');finish(app)
    review=app.session.review;original=review.item(0)['original'].copy()
    review.change(0,'correct_depth',depth=8)
    review.change(0,'reposition',xy=(50,60))
    manual=review.add_manual(40,45,9)
    app.refresh_points();app.tree.selection_set(('0',str(manual)))
    app.restore_original('depth')
    assert review.item(0)['current']['depth']==original['depth']
    assert review.item(0)['current']['pixel_x']==50
    assert review.item(manual)['current']['depth']==9
    assert app.review_dirty and app.can_restore('position') and not app.can_restore('depth')
    app.restore_original('position')
    assert review.item(0)['current']['pixel_x']==original['pixel_x']
    assert not app.can_restore('both')


def test_include_note_without_editing_value_position_or_status(app,tmp_path):
    from copy import deepcopy
    from vetorizafb.workflow import ChartSession
    app.run_stage('all');finish(app)
    app.tree.selection_set('0');app.tree.focus('0');app.select_point()
    app.review_action('accepted')
    before=deepcopy(app.session.review.item(0)['current'])
    app.review_note.set('Conferido na carta')
    assert not app.note_button.instate(['disabled'])
    app.note_button.invoke()
    item=app.session.review.item(0)
    assert item['current']==before and item['status']=='accepted'
    assert item['note']=='Conferido na carta' and item['history'][-1]['action']=='note'
    assert 'Conferido na carta' in app.tree.set('0','origin')
    assert app.review_dirty and app.review_note.get()==''
    path=tmp_path/'notes.vfproject.json';app.session.save_project(path)
    assert ChartSession.load_project(path).review.item(0)['note']=='Conferido na carta'


@pytest.mark.parametrize('answer',[None,False,True])
def test_close_project_cancel_discard_or_save(app,tmp_path,monkeypatch,answer):
    from vetorizafb.workflow import ChartSession
    app.run_stage('all');finish(app)
    app.review_dirty=True;session=app.session
    path=tmp_path/'closed.vfproject.json'
    monkeypatch.setattr('vetorizafb.gui.messagebox.askyesnocancel',lambda *a,**k:answer)
    monkeypatch.setattr('vetorizafb.gui.filedialog.asksaveasfilename',lambda **k:str(path))
    app.close_project();finish(app)
    if answer is None:
        assert app.session is session and app.review_dirty and not path.exists()
    else:
        assert app.session is None and not app.tree.get_children() and not app.review_dirty
        assert not app.viewer.canvas.find_all() and app.path.get()==''
        assert app.root.winfo_exists()
        if answer:assert ChartSession.load_project(path).review.items==session.review.items


def test_cancel_save_or_failed_save_keeps_project_open(app,monkeypatch):
    app.run_stage('all');finish(app);session=app.session;app.review_dirty=True
    monkeypatch.setattr('vetorizafb.gui.messagebox.askyesnocancel',lambda *a,**k:True)
    monkeypatch.setattr('vetorizafb.gui.filedialog.asksaveasfilename',lambda **k:'')
    app.close_project()
    assert app.session is session and app.review_dirty
    monkeypatch.setattr('vetorizafb.gui.filedialog.asksaveasfilename',lambda **k:'unused.vfproject.json')
    def fail(path):raise OSError('Gravação indisponível')
    monkeypatch.setattr(session,'save_project',fail)
    errors=[];monkeypatch.setattr(app,'show_copyable_error',lambda *a,**k:errors.append(a))
    app.close_project();finish(app)
    assert app.session is session and app.review_dirty and errors


def test_single_header_and_single_row_review_toolbar(app):
    from tkinter import ttk
    app.root.geometry('1050x720');app.root.update()
    centers=[w.winfo_y()+w.winfo_height()/2 for w in app.toolbar_widgets]
    assert max(centers)-min(centers)<=1
    assert app.chart_entry.master.master is app.brand_icon.master
    labels=[w.cget('text') for w in app.chart_entry.master.winfo_children() if isinstance(w,ttk.Label)]
    assert labels==['Carta Náutica:']
    assert app.chart_entry.bind('<Return>')
    assert app.actions_button.winfo_ismapped() and app.selection_button.winfo_ismapped()
    assert not app.review_buttons['insert'].winfo_ismapped()


def test_low_zoom_keeps_preview_boxes_visible(app):
    app.run_stage('segment');finish(app)
    app.viewer.layer.set('Caixas');app.update_preview();finish_preview(app)
    app.viewer.scale=.2;app.viewer.render()
    assert app.viewer._visible_preview
    assert 'Amplie' not in app.viewer.inspection_text.get()


def test_error_dialog_can_copy_message(app):
    popup=app.show_copyable_error('Processamento','Erro de teste: detalhes copiáveis')
    buttons=[w for w in popup.winfo_children()[0].winfo_children() if hasattr(w,'winfo_children')]
    bar=buttons[-1]
    copy=next(w for w in bar.winfo_children() if w.cget('text')=='Copiar erro')
    copy.invoke()
    assert popup.clipboard_get()=='Erro de teste: detalhes copiáveis'
    popup.destroy()


def test_download_label_names_model_before_first_byte(app,monkeypatch):
    from vetorizafb.models import ConnectionSettings
    class Choice:
        result=('PP-OCRv6_small_rec',ConnectionSettings(mode='direct'))
    monkeypatch.setattr('vetorizafb.gui.ModelDownloadDialog',lambda *a,**k:Choice())
    import threading
    gate=threading.Event()
    def download(*a,**k):gate.wait(3);raise RuntimeError('Download interrompido')
    monkeypatch.setattr('vetorizafb.gui.download_model',download)
    app.configure_model_download()
    assert app.progress_label.get()=='Baixando PP-OCRv6_small_rec…'
    gate.set()
    monkeypatch.setattr(app,'show_copyable_error',lambda *a,**k:None)
    finish(app)
