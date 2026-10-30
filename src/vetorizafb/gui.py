"""Staged calibration and review UI for the shared OCR core."""
from dataclasses import asdict
import json
import math
import os
import shutil
import webbrowser
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont
import traceback

from .runtime import configure_gis_runtime
configure_gis_runtime()

from PIL import Image, ImageDraw, ImageTk

from .core import Config, ProcessingCancelled
from .pipeline import write_json_atomic
from .viewer import ChartViewer
from .workflow import ChartSession
from .dialogs import ScrollablePanel,PositionDialog,OffsetDialog
from . import __version__
from .calibration import CalibrationPreview, MASK_KEYS
from .auto_bounds import suggest_bounds
from .area import is_polygon
from .box_diagnostics import export_box_measurements
from .area import inside as inside_area
from .branding import apply_icon, asset_photo
from .ui import Tooltip, rounded_controls
from .models import default_model_root,discover_models,download_model,ConnectionSettings,save_model_root,inspect_model
from .model_dialog import ModelDownloadDialog


class Application:
    def __init__(self,root):
        self.root, self.session = root,None
        self.busy = self.review_dirty = False
        self._closed=False
        self._one_shot_mode=False
        self.roi = None
        self.preview = CalibrationPreview()
        self._preview_id = None
        self.measurement = None
        self.measure_text = tk.StringVar()
        self.events, self.cancel = queue.Queue(),threading.Event()
        self.path, self.output = tk.StringVar(),tk.StringVar()
        self.model = tk.StringVar(value='PP-OCRv6_small_rec')
        self.model_dir, self.target_crs = tk.StringVar(),tk.StringVar(value='EPSG:4326')
        self.models_root=tk.StringVar(value=str(default_model_root()))
        self.local_models={}
        self.network_settings=ConnectionSettings()
        self.status = tk.StringVar(value='Selecione uma carta GeoTIFF para iniciar.')
        self.validity, self.counts = tk.StringVar(),tk.StringVar()
        self.counts_summary=tk.StringVar()
        self.stage_states=[]
        self.sort_column=None
        self.sort_reverse=False
        self.tooltips=[]
        self.roi_text = tk.StringVar(value='Carta inteira')
        self.area_mode = tk.StringVar(value='whole')
        self.filter = tk.StringVar(value='Todos')
        self.review_note = tk.StringVar()
        self.follow_review = tk.BooleanVar(value=True)
        self.selection_text = tk.StringVar(value='0 selecionados')
        self.show_tooltips=tk.BooleanVar(value=self.load_tooltips_preference())
        Tooltip.set_enabled(root,self.show_tooltips.get())
        self.live_preview=tk.BooleanVar(value=False)
        self._preview_busy=False
        self._auto_busy=False
        self._preview_revision=0
        self._selection_anchor = self._last_followed = None
        self.fields = {k:tk.BooleanVar(value=v) if isinstance(v,bool) else tk.StringVar(value=str(v))
                       for k,v in asdict(Config()).items()}
        root.title(f'VetorizaFB {__version__} — processamento e revisão')
        root.geometry('1450x950');root.minsize(1050,720)
        self.configure_style()
        self.icon_path = apply_icon(root)
        self.set_config(Config())
        self.build()
        for key,var in self.fields.items():
            var.trace_add('write',lambda *args,k=key:self.field_changed(k))
        for var in (self.model,self.model_dir):var.trace_add('write',lambda *args:self.refresh_validity())
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.bind('<F1>',lambda e:self.open_manual())
        root.bind('<Control-o>',lambda e:self.choose_chart())
        root.bind('<Control-s>',lambda e:self.save_project())
        self._poll_id=root.after(80,self.poll)
        self.path.trace_add('write',lambda *args:self.refresh_chart_prompt())
        self.refresh_validity()

    def configure_style(self):
        style=ttk.Style(self.root)
        families=set(tkfont.families(self.root))
        self.ui_font=next((f for f in ('Segoe UI','DejaVu Sans','Nimbus Sans','Helvetica') if f in families),tkfont.nametofont('TkDefaultFont').actual('family'))
        tkfont.nametofont('TkDefaultFont').configure(family=self.ui_font,size=10)
        tkfont.nametofont('TkTextFont').configure(family=self.ui_font,size=10)
        if 'clam' in style.theme_names():style.theme_use('clam')
        style.configure('.',font=(self.ui_font,10),background='#f5f8fb',foreground='#19364a')
        style.configure('TButton',padding=(6,1),borderwidth=1,relief='flat',background='#e5f1fb',foreground='#164f77',bordercolor='#b6d3e9',focusthickness=1,focuscolor='#0a70b5')
        style.map('TButton',background=[('disabled','#eef1f4'),('pressed','#c4dfef'),('active','#d2e8f9')],foreground=[('disabled','#8d9baa')],bordercolor=[('disabled','#e0e6ec'),('active','#468eb9')])
        style.configure('TMenubutton',padding=(8,4),borderwidth=1,relief='flat',background='#e5f1fb',foreground='#164f77',bordercolor='#b6d3e9')
        style.map('TMenubutton',background=[('disabled','#eef1f4'),('active','#d2e8f9')],foreground=[('disabled','#8d9baa')])
        for name,bg,hover,fg in [('Primary','#096fab','#085a8b','white'),('Approve','#e1f4e9','#c9ead8','#17663d'),('Reject','#fbe6e8','#f5cfd4','#9c2635')]:
            style.configure(name+'.TButton',background=bg,foreground=fg,bordercolor=bg)
            style.map(name+'.TButton',background=[('disabled','#eef1f4'),('pressed',hover),('active',hover)],foreground=[('disabled','#8d9baa')])
        style.configure('TNotebook',background='#f5f8fb',borderwidth=0,tabmargins=0)
        style.configure('TNotebook.Tab',font=(self.ui_font,9),padding=(4,3),background='#e5f1fb',foreground='#17547e',borderwidth=0,lightcolor='#e5f1fb',darkcolor='#e5f1fb')
        style.map('TNotebook.Tab',padding=[('selected',(4,4)),('!selected',(2,2))],background=[('selected','#153b50'),('active','#cee7f8')],foreground=[('selected','white')],lightcolor=[('selected','#153b50')],darkcolor=[('selected','#153b50')],bordercolor=[('selected','#153b50')])
        style.configure('TEntry',fieldbackground='white',padding=(4,2),bordercolor='#cbd9e4')
        style.configure('Required.TEntry',fieldbackground='#fff2bf',bordercolor='#d9b650')
        style.configure('TCombobox',fieldbackground='white',background='#e5f1fb',arrowcolor='#17547e',padding=3)
        style.map('TCombobox',fieldbackground=[('readonly','white')],foreground=[('readonly','#19364a')])
        style.configure('Treeview',rowheight=24,background='white',fieldbackground='white',borderwidth=0)
        style.configure('Treeview.Heading',font=(self.ui_font,9,'bold'),background='#e7eff5',foreground='#36576d',padding=5,relief='flat')
        style.map('Treeview',background=[('selected','#176b85')],foreground=[('selected','white')])
        self._control_images=rounded_controls(style,self.root)
        style.configure('Brand.TFrame',background='#eaf4f8')
        style.configure('Brand.Field.TFrame',background='#eaf4f8')
        style.configure('Brand.Field.TLabel',background='#eaf4f8',foreground='#153b50',font=(self.ui_font,10,'bold'))
        style.configure('Brand.TLabel',background='#eaf4f8',foreground='#153b50',font=(self.ui_font,16,'bold'))
        style.configure('Tooltip.TLabel',background='#17374b',foreground='white',font=(self.ui_font,9))
        self.stage_icons={}
        for state,colour in [('empty','#afbdc8'),('pending','#f1b747'),('ready','#57cba1'),('busy','#5eb5ff')]:
            im=Image.new('RGBA',(7,7))
            ImageDraw.Draw(im).ellipse((1,1,6,6),fill=colour)
            self.stage_icons[state]=ImageTk.PhotoImage(im,master=self.root)

    def tip(self,widget,text):
        item=Tooltip(widget,text);self.tooltips.append(item);return item

    @staticmethod
    def tooltip_preferences_path():
        return Path(os.environ.get('APPDATA',Path.home()/'.config'))/'VetorizaFB'/'interface.json'

    def load_tooltips_preference(self):
        try:
            value=json.loads(self.tooltip_preferences_path().read_text(encoding='utf-8'))
            return value['show_tooltips'] if isinstance(value,dict) and isinstance(value.get('show_tooltips'),bool) else True
        except (OSError,ValueError,TypeError,KeyError):return True

    def toggle_tooltips(self):
        enabled=self.show_tooltips.get()
        Tooltip.set_enabled(self.root,enabled)
        try:write_json_atomic(self.tooltip_preferences_path(),{'show_tooltips':enabled})
        except OSError:self.status.set('A preferência das dicas vale nesta sessão; não foi possível salvá-la.')

    def refresh_chart_prompt(self):
        if not hasattr(self,'chart_entry'):return
        loaded=self.session is not None and self.path.get().strip()==str(self.session.path)
        self.chart_entry.configure(style='TEntry' if loaded else 'Required.TEntry')

    def show_shortcuts(self):
        popup=tk.Toplevel(self.root);popup.title('Atalhos');popup.resizable(False,False)
        panel=ttk.Frame(popup,padding=18);panel.pack()
        for row,(keys,action) in enumerate([
            ('Setas','Navegar entre sondagens'),('Shift + setas','Selecionar faixa'),('Ctrl + clique','Selecionar ou desselecionar'),
            ('Ctrl + A','Aprovar selecionados'),('Delete','Excluir selecionados'),('Ctrl + E','Editar profundidade'),
            ('Ctrl + Shift + A','Selecionar todos os visíveis'),('Esc','Limpar seleção / cancelar ferramenta'),
            ('Ctrl + O / Ctrl + S','Abrir carta / salvar projeto'),('F1','Abrir manual')]):
            ttk.Label(panel,text=keys,font=(self.ui_font,10,'bold')).grid(row=row,column=0,sticky='w',padx=(0,24),pady=5)
            ttk.Label(panel,text=action).grid(row=row,column=1,sticky='w',pady=5)
        ttk.Label(panel,text='Atalhos de revisão: imagem e tabela. Campos de texto mantêm seus atalhos.',wraplength=430).grid(row=11,column=0,columnspan=2,sticky='w',pady=(12,0))
        return popup

    def show_review_menu(self,event):
        # Preserve the current multi-selection; right click never approves a point.
        self.refresh_review_controls()
        if hasattr(self,'review_menu'):self.review_menu.destroy()
        menu=self.review_menu=tk.Menu(self.root,tearoff=False)
        if getattr(event,'widget',None) is self.viewer.canvas and self.viewer.mode.get() in {'Selecionar área','Selecionar para excluir'}:
            shapes=tk.Menu(menu,tearoff=False)
            for shape in ('Retângulo','Polígono','Laço livre'):
                shapes.add_radiobutton(label=shape,value=shape,variable=self.viewer.area_shape,
                                       command=self.viewer.cancel_area)
            menu.add_cascade(label='Formato da área',menu=shapes)
            menu.add_separator()
        if getattr(event,'widget',None) is self.viewer.canvas and self.viewer.layer.get() in {'Caixas','Dígitos'}:
            menu.add_command(label='Excluir caixas selecionadas',accelerator='Delete',command=self.delete_selection,
                             state='normal' if self.viewer.selected_box_ids else 'disabled')
            menu.add_separator()
        for key,label,shortcut in [('accepted','Aprovar','Ctrl+A'),('rejected','Excluir','Delete'),('edit','Editar','Ctrl+E'),('unreviewed','Marcar pendente','')]:
            button=self.review_buttons[key]
            menu.add_command(label=label,accelerator=shortcut,command=button.invoke,state='disabled' if button.instate(['disabled']) else 'normal')
        self.update_restore_menu()
        menu.add_cascade(label='Restaurar',menu=self.restore_menu,state='normal' if self.review_ready() and self.can_restore('both') else 'disabled')
        menu.add_separator();menu.add_command(label='Atalhos…',command=self.show_shortcuts)
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()

    def open_manual(self):
        manual=Path(__file__).parent/'assets'/'manual_ptbr.html'
        try:
            if not manual.is_file():raise OSError('Manual local não encontrado. Reinstale o pacote.')
            if not webbrowser.open(manual.resolve().as_uri()):raise OSError('Não foi possível abrir o navegador padrão.')
        except OSError as exc:messagebox.showerror('Manual',str(exc),parent=self.root)

    def about(self):
        popup=tk.Toplevel(self.root);popup.title('Sobre o VetorizaFB');popup.resizable(False,False)
        apply_icon(popup,self.icon_path)
        panel=ttk.Frame(popup,padding=24);panel.pack(fill='both',expand=True)
        popup._brand_images=[asset_photo(popup,'logo_app.png',(150,150))]
        institutions=ttk.Frame(panel);institutions.pack(pady=(0,12))
        for name,label in [('logo_mb.png','Marinha do Brasil'),('logo_chm.png','Centro de Hidrografia da Marinha')]:
            photo=asset_photo(popup,name,(56,56));popup._brand_images.append(photo)
            badge=ttk.Frame(institutions,width=200,height=115);badge.pack(side='left',padx=8);badge.pack_propagate(False)
            ttk.Label(badge,image=photo).pack()
            ttk.Label(badge,text=label,wraplength=190,anchor='center',justify='center').pack(fill='x')
        ttk.Label(panel,image=popup._brand_images[0]).pack(pady=(0,12))
        ttk.Label(panel,text=f'Versão {__version__}',font=(self.ui_font,16,'bold'),foreground='#153b50').pack(pady=(0,0))
        ttk.Label(panel,text='Extração e revisão de sondagens em cartas náuticas',padding=(0,8)).pack()
        ttk.Label(panel,text='Ivan Bodra Guimarães',wraplength=500).pack()
        buttons=ttk.Frame(panel);buttons.pack(pady=(18,0))
        ttk.Button(buttons,text='Abrir manual',command=self.open_manual).pack(side='left',padx=6)
        ttk.Button(buttons,text='Fechar',command=popup.destroy).pack(side='left',padx=6)
        return popup

    def choose_icon(self):
        path=filedialog.askopenfilename(title='Selecionar ícone original',filetypes=[('Ícone ou imagem','*.ico *.png')])
        if not path:return
        try:
            with Image.open(path) as image:image.verify()
            folder=Path(os.environ.get('APPDATA',Path.home()/'.config'))/'VetorizaFB';folder.mkdir(parents=True,exist_ok=True)
            target=folder/('logo_vetorizafb'+Path(path).suffix.lower())
            if Path(path).resolve()!=target.resolve():shutil.copyfile(path,target)
            (folder/'selected-icon.txt').write_text(target.name,encoding='utf-8')
            self.icon_path=apply_icon(self.root,target)
            if self.icon_path:self.brand_icon.configure(image=self.root._vetorizafb_icon)
            self.status.set('Ícone original carregado. Será reutilizado nas próximas aberturas.')
        except (OSError,ValueError) as exc:messagebox.showerror('Ícone',str(exc),parent=self.root)

    def schedule_preview(self):
        if not self.live_preview.get():return
        self._preview_revision+=1
        if self._preview_id:self.root.after_cancel(self._preview_id)
        self._preview_id=self.root.after(300,self.update_preview)

    def field_changed(self,key):
        if key=='segmentation' and hasattr(self,'blur_entry'):self.update_mode_controls()
        self.refresh_validity()
        if key in ('dpi','reference_dpi','segmentation','exclude_magenta','threshold','blur_size','kernel_size',
                   'min_w','max_w','min_h','max_h','exclude_yellow','yellow_delta','yellow_min_fraction'):
            self.schedule_preview()

    def update_mode_controls(self):
        state='normal' if self.fields['segmentation'].get()=='Realce' else 'disabled'
        for widget in (self.blur_entry,self.dilation_entry):widget.configure(state=state)
        if hasattr(self,'group_mode_combo'):
            fb=self.fields['segmentation'].get()=='Folha de bordo'
            if fb:self.fields['grouping'].set('FB')
            elif self.fields['grouping'].get() in ('fb','FB'):self.fields['grouping'].set('relative')
            self.group_mode_combo.configure(state='disabled' if fb else 'readonly',
                                            values=['FB'] if fb else ['relative','fixed'])
            self.decimal_max_entry.configure(state='disabled' if fb else 'normal')
            if hasattr(self,'fb_distance_entry'):
                self.fb_distance_entry.configure(state='normal' if fb else 'disabled')
                self.fb_advanced_button.configure(state='normal' if fb else 'disabled')

    def configure_fb_grouping(self):
        if self.busy or self.fields['segmentation'].get()!='Folha de bordo':return
        window=tk.Toplevel(self.root);window.title('Ajustes de agrupamento FB')
        window.transient(self.root);window.resizable(False,False)
        body=ttk.Frame(window,padding=12);body.pack(fill='both',expand=True)
        values={}
        options=[
            ('Semelhança de altura','fb_integer_height_ratio','0 < valor ≤ 1. Razão mínima entre a menor e a maior altura dos algarismos do inteiro.'),
            ('Sobreposição','fb_overlap','0 ≤ valor < 1. Sobreposição horizontal máxima como fração da menor largura.'),
            ('Sobreposição vertical do decimal','fb_decimal_top_overlap','Valor ≥ 0. Quanto o topo do decimal pode subir acima da base do inteiro, como fração da altura do inteiro.'),
            ('Limite inferior do decimal','fb_decimal_max_gap','Valor ≥ 0. Distância máxima da base do inteiro até o topo do decimal, como fração da altura do inteiro.'),
            ('Recuo do decimal','fb_decimal_left','Valor ≥ 0. Recuo horizontal permitido antes da borda direita do inteiro, como fração da altura; limitado à largura da última caixa.'),
            ('Margem de ambiguidade','fb_ambiguity_margin','Valor ≥ 0. Diferença mínima entre os escores geométricos dos candidatos. Aumentar mantém mais casos para revisão.'),
            ('Altura dos componentes pequenos','fb_small_ratio','0 < valor ≤ 1. Altura relativa abaixo da qual um componente próximo e rebaixado pode ficar para revisão.')]
        for row,(label,key,hint) in enumerate(options):
            ttk.Label(body,text=label).grid(row=row,column=0,sticky='w',padx=(0,10),pady=3)
            var=tk.StringVar(window,value=self.fields[key].get());values[key]=var
            entry=ttk.Entry(body,textvariable=var,width=7);entry.grid(row=row,column=1,sticky='w',pady=3)
            self.tip(entry,hint)
        keep=tk.BooleanVar(window,value=self.fields['fb_keep_small'].get())
        check=ttk.Checkbutton(body,text='Gerar candidatos para componentes pequenos isolados',variable=keep)
        check.grid(row=7,column=0,columnspan=2,sticky='w',pady=6)
        self.tip(check,'Marcado: permite candidatos pequenos sem decimal associado. Desmarcado: mantém os casos próximos de inteiros maiores para revisão.')
        ttk.Label(body,text='Proporções: 0.25 = 25%. Use ponto decimal.').grid(row=8,column=0,columnspan=2,sticky='w',pady=5)
        def apply():
            try:
                changes={key:float(var.get()) for key,var in values.items()}
                changes['fb_keep_small']=keep.get()
                Config(**dict(asdict(self.config()),**changes))
            except (ValueError,TypeError) as exc:
                messagebox.showerror('Parâmetros FB',str(exc),parent=window);return
            for key,value in changes.items():self.fields[key].set(value)
            window.destroy()
        bar=ttk.Frame(body);bar.grid(row=9,column=0,columnspan=2,sticky='e',pady=(8,0))
        ttk.Button(bar,text='Aplicar',command=apply).pack(side='left',padx=4)
        ttk.Button(bar,text='Cancelar',command=window.destroy).pack(side='left')
        window.bind('<Escape>',lambda e:window.destroy())
        window.bind('<Return>',lambda e:apply())

    def toggle_live_preview(self):
        if self.live_preview.get():
            self.viewer.layer.set('Caixas')
            self.viewer.render()
            if not self.session or self.busy:return
            self.schedule_preview()
        else:
            self._preview_revision+=1
            if self._preview_id:self.root.after_cancel(self._preview_id);self._preview_id=None

    def update_preview(self):
        if self._preview_id:self.root.after_cancel(self._preview_id)
        self._preview_id=None
        if self.busy or not self.session:return
        try:
            cfg=self.config()
            if self._preview_busy:return
            self._preview_busy=True;revision=self._preview_revision;session=self.session;roi=self.roi
            def worker():
                try:self.events.put(('preview',(revision,session,self.preview.classify(session,cfg,roi),cfg,roi),None))
                except Exception as exc:self.events.put(('preview_error',(revision,str(exc)),None))
            threading.Thread(target=worker,daemon=True).start()
        except (ValueError,TypeError) as exc:
            self.viewer.preview_boxes=[]
            if self.viewer.layer.get()=='Caixas':
                self.viewer.inspection_text.set(str(exc));self.viewer.render_preview_boxes()

    def measure_character(self):
        self.viewer.mode.set('Medir caractere')
        self.viewer.layer.set('Caixas');self.update_preview()
        self.status.set('Clique em uma caixa ou arraste um retângulo; medidas em pixels originais.')

    def use_measurement(self,minimum):
        if not self.measurement:return
        try:
            cfg=self.config();w,h=self.measurement
            # Segmentação usa limites estritos, expressos em pixels na DPI de referência.
            values=[max(0,math.ceil(v/cfg.scale)-1) if minimum else math.floor(v/cfg.scale)+1 for v in (w,h)]
            low='min_' if minimum else 'max_'
            for key,value in zip(('w','h'),values):self.fields[low+key].set(str(value))
            self.viewer.layer.set('Caixas')
            if self.live_preview.get():self.update_preview()
        except (ValueError,TypeError) as exc:self.status.set(str(exc))

    def auto_dimensions(self):
        if not self.session or self.busy or self._auto_busy:return
        try:cfg=self.config()
        except (ValueError,TypeError) as exc:self.status.set(str(exc));return
        session,roi=self.session,self.roi
        self._auto_busy=True;self.auto_button.configure(state='disabled')
        self.status.set('Analisando as dimensões das caixas…')
        def worker():
            try:
                key=(id(session),tuple(getattr(cfg,k) for k in MASK_KEYS))
                if session.valid_segments(cfg,roi) and session.all_boxes is not None:
                    boxes=session.all_boxes
                elif not self._preview_busy and self.preview.contour_key==(key,session.validate_roi(roi)):
                    boxes=self.preview.contours
                else:
                    boxes=CalibrationPreview().contours_for(session,cfg,roi)
                result=suggest_bounds(boxes,cfg.scale)
                self.events.put(('auto_dimensions',(session,roi,key,result),None))
            except Exception as exc:self.events.put(('auto_dimensions_error',str(exc),None))
        threading.Thread(target=worker,daemon=True).start()

    def build(self):
        menu=tk.Menu(self.root);self.root.configure(menu=menu)
        files=tk.Menu(menu,tearoff=False);menu.add_cascade(label='Arquivo',menu=files)
        for label,command in [('Abrir carta (Ctrl+O)',self.choose_chart),('Abrir projeto',self.open_project),
                              ('Salvar projeto (Ctrl+S)',self.save_project),('Fechar projeto',self.close_project),('Carregar parâmetros',self.load_config),
                              ('Salvar parâmetros',self.save_config),('Exportar medidas das caixas…',self.export_box_measurements),
                              ('Sair',self.close)]:
            files.add_command(label=label,command=command)
        help_menu=tk.Menu(menu,tearoff=False);menu.add_cascade(label='Ajuda',menu=help_menu)
        help_menu.add_command(label='Manual de uso (F1)',command=self.open_manual)
        help_menu.add_command(label='Atalhos de teclado…',command=self.show_shortcuts)
        help_menu.add_checkbutton(label='Mostrar dicas ao passar o cursor',variable=self.show_tooltips,
                                  command=self.toggle_tooltips)
        help_menu.add_separator();help_menu.add_command(label='Sobre o VetorizaFB',command=self.about)
        brand=ttk.Frame(self.root,padding=(12,3),style='Brand.TFrame');brand.pack(fill='x')
        self.header_logo=asset_photo(self.root,'logo_vetorizaFB.png',(36,28))
        self.brand_icon=ttk.Label(brand,image=self.header_logo,style='Brand.TLabel')
        self.brand_icon.pack(side='left',padx=(0,10))
        ttk.Label(brand,text='VetorizaFB',style='Brand.TLabel').pack(side='left')
        ttk.Separator(brand,orient='vertical').pack(side='left',fill='y',padx=14,pady=2)
        header=ttk.Frame(brand,style='Brand.Field.TFrame');header.pack(side='right',fill='x',expand=True)
        header.columnconfigure(1,weight=1)
        ttk.Label(header,text='Carta Náutica:',style='Brand.Field.TLabel').grid(row=0,column=0,sticky='w')
        self.chart_entry=ttk.Entry(header,textvariable=self.path,style='Required.TEntry')
        self.chart_entry.grid(row=0,column=1,sticky='ew',padx=6)
        self.chart_entry.bind('<Return>',lambda e:self.load_chart())
        self.tip(self.chart_entry,'Digite o caminho e pressione Enter para abrir a carta.')
        ttk.Button(header,text='Abrir…',command=self.choose_chart).grid(row=0,column=2)
        split=ttk.Panedwindow(self.root,orient='horizontal');split.pack(fill='both',expand=True,padx=8)
        left=ttk.Frame(split,width=365);split.add(left,weight=0)
        self.tabs=ttk.Notebook(left);self.tabs.pack(fill='both',expand=True)
        self.segment_panel=ScrollablePanel(self.tabs);seg=self.segment_panel.content
        ocr,group,export=[ttk.Frame(self.tabs,padding=9) for _ in range(3)]
        for frame,label in [(self.segment_panel,'1. Preparar'),(ocr,'2. Reconhecer'),(group,'3. Agrupar'),(export,'4. Exportar')]:
            self.tabs.add(frame,text=label,image=self.stage_icons['empty'],compound='left');frame.columnconfigure(1,weight=1)
        self.stage_labels=['Preparar','Reconhecer','Agrupar','Exportar']
        for i,label in enumerate(self.stage_labels):self.tabs.tab(i,text=label)
        self.tab_tip=self.tip(self.tabs,lambda:self.stage_tooltip())
        self.tabs.bind('<Motion>',self.tab_hover)
        seg.columnconfigure(1,weight=1)
        def within_limit(text,limit,percent=False):
            if not text:return True  # Allow a field to be cleared while editing.
            if percent:
                if text.count('.')>1 or any(c not in '0123456789.' for c in text):return False
                if text=='.':return True
                return float(text)<=limit
            return text.isascii() and text.isdecimal() and int(text)<=limit
        def setting(frame,row,label,key,values=None):
            ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w',pady=2)
            percent=key=='yellow_min_fraction'
            field=ttk.Frame(frame) if percent else frame
            widget=ttk.Combobox(field,textvariable=self.fields[key],values=values,state='readonly',width=16 if key=='segmentation' else 9) if values else ttk.Entry(field,textvariable=self.fields[key],width=6)
            if key in ('threshold','yellow_delta','yellow_min_fraction'):
                limit=100 if key=='yellow_min_fraction' else 255
                widget.configure(validate='key',validatecommand=(self.root.register(
                    lambda text,maximum=limit,pct=key=='yellow_min_fraction':within_limit(text,maximum,pct)),'%P'))
            if percent:
                field.grid(row=row,column=1,sticky='w',padx=(2,0),pady=1)
                widget.pack(side='left');ttk.Label(field,text='%').pack(side='left',padx=(3,0))
            else:widget.grid(row=row,column=1,sticky='w',padx=(2,0),pady=1)
            hints={
                'yellow_delta':'Valor maior inclui tons de amarelo mais suaves.',
                'threshold':'Aumente para incluir traços mais claros. Valores altos podem acabar incluindo o fundo.',
                'segmentation':'Realce suaviza e amplia os traços; Bruto usa os pixels escuros diretamente.',
                'yellow_min_fraction':'Percentual de amarelo necessário para descartar a caixa.',
                'decimal_height_ratio':'Altura máxima do algarismo decimal em relação à altura da parte inteira.',
                'tol_x':'Em FB: espaço máximo entre bordas dos algarismos do inteiro, em pixels da carta.',
                'tol_y':'Em FB: diferença máxima entre as bases dos algarismos do inteiro, em pixels da carta.',
                'decimal_drop':'Rebaixamento mínimo do centro do decimal, como fração da altura do inteiro.',
                'fb_decimal_distance':'Afastamento horizontal máximo após o inteiro, como fração da altura do inteiro.',
                'min_confidence':'Escore mínimo para aceitar um dígito.'}
            if key in hints:self.tip(widget,hints[key])
            return widget
        for row,(label,key,values) in enumerate([
            ('Modo','segmentation',['Realce','Bruto','Folha de bordo']),('Claridade','threshold',None),
            ('Desfoque','blur_size',None),('Dilatação','kernel_size',None)]):
            widget=setting(seg,row,label,key,values)
            if key=='blur_size':self.blur_entry=widget
            if key=='kernel_size':self.dilation_entry=widget
        self.update_mode_controls()
        def size_range(row,label,minimum,maximum):
            ttk.Label(seg,text=f'{label} Mín.').grid(row=row,column=0,sticky='w',pady=2)
            inputs=ttk.Frame(seg);inputs.grid(row=row,column=1,columnspan=3,sticky='w',padx=(2,0),pady=1)
            ttk.Entry(inputs,textvariable=self.fields[minimum],width=6).pack(side='left')
            ttk.Label(inputs,text='Máx.').pack(side='left',padx=(8,3))
            ttk.Entry(inputs,textvariable=self.fields[maximum],width=6).pack(side='left')
        size_range(4,'Largura', 'min_w','max_w')
        size_range(5,'Altura', 'min_h','max_h')
        measuring=ttk.Frame(seg);measuring.grid(row=6,column=0,columnspan=4,sticky='w',pady=(2,3))
        ttk.Button(measuring,text='Definir mín.',width=11,command=lambda:self.use_measurement(True)).grid(row=0,column=0,sticky='w',padx=(0,3),pady=(0,2))
        ttk.Button(measuring,text='Definir máx.',width=11,command=lambda:self.use_measurement(False)).grid(row=0,column=1,sticky='w',pady=(0,2))
        ttk.Button(measuring,text='Medir',width=11,command=self.measure_character).grid(row=1,column=0,sticky='w',padx=(0,3))
        self.auto_button=ttk.Button(measuring,text='Auto',width=7,command=self.auto_dimensions)
        self.auto_button.grid(row=1,column=1,sticky='w')
        self.measure_label=ttk.Label(seg,textvariable=self.measure_text)
        self.measure_label.grid(row=7,column=0,columnspan=2,sticky='w')
        self.measure_label.grid_remove()
        ttk.Checkbutton(seg,text='Ignorar traços magenta',variable=self.fields['exclude_magenta']).grid(row=8,column=0,columnspan=2,sticky='w',pady=2)
        ttk.Checkbutton(seg,text='Descartar caixas em terra',variable=self.fields['exclude_yellow']).grid(row=9,column=0,columnspan=2,sticky='w',pady=2)
        setting(seg,10,'Sensibilidade','yellow_delta')
        setting(seg,11,'Cobertura','yellow_min_fraction')
        ttk.Checkbutton(seg,text='Prévia',variable=self.live_preview,command=self.toggle_live_preview).grid(row=12,column=0,columnspan=2,sticky='w',pady=2)
        self.seg_button=ttk.Button(seg,text='Preparar',width=11,style='Primary.TButton',command=lambda:self.run_stage('segment'))
        self.seg_button.grid(row=13,column=0,columnspan=2,sticky='w',pady=(2,2))
        area=ttk.Frame(seg);area.grid(row=14,column=0,columnspan=2,sticky='w',pady=2)
        ttk.Radiobutton(area,text='Carta inteira',variable=self.area_mode,value='whole',command=lambda:self.set_roi(None)).pack(side='left')
        ttk.Radiobutton(area,text='Selecionar área',variable=self.area_mode,value='select',command=self.select_area).pack(side='left',padx=(10,0))
        model_panel=ttk.Frame(ocr);model_panel.grid(row=0,column=0,columnspan=2,sticky='ew',pady=(0,10))
   …13371 tokens truncated…{self.session.path.stem}.medidas-caixas.csv',
            filetypes=[('Tabela CSV','*.csv')])
        if not destination:return
        session=self.session
        self.start(lambda:export_box_measurements(session,destination),
                   lambda counts:messagebox.showinfo('Medidas das caixas',
                       f"{sum(counts.values())} caixas exportadas para {destination}",parent=self.root),
                   cancellable=False)

    def save_project(self,after_save=None):
        if self.busy or not self.session:return
        path=filedialog.asksaveasfilename(defaultextension='.vfproject.json',filetypes=[('Projeto VetorizaFB','*.vfproject.json')])
        if path:
            def done(_):
                self.review_dirty=False
                if after_save:after_save()
            self.start(lambda:self.session.save_project(path),done,cancellable=False)

    def close_project(self):
        if self.busy or self.session is None:return
        answer=messagebox.askyesnocancel('Fechar projeto','Deseja salvar o projeto antes de fechar?',parent=self.root)
        if answer is None:return
        if answer:self.save_project(after_save=self.clear_project)
        else:self.clear_project()

    def clear_project(self):
        self.session=None;self.roi=None;self.review_dirty=False;self.measurement=None
        self.path.set('');self.output.set('');self.review_note.set('');self.measure_text.set('');self.measure_label.grid_remove()
        self.counts.set('');self.counts_summary.set('');self.filter.set('Todos')
        self.area_mode.set('whole');self.roi_text.set('Carta inteira');self.sort_column=None;self.sort_reverse=False
        self._selection_anchor=self._last_followed=None
        self.viewer.session=None;self.viewer.preview_boxes=[];self.viewer.measurement=None
        self.viewer.refresh_layers()
        self.viewer.selected_id=None;self.viewer.selected_ids=set();self.viewer.roi=None
        self.viewer.canvas.delete('all');self.viewer.photo=None
        self.viewer.layer.set('Original');self.viewer.mode.set('Inspecionar')
        self.viewer.inspection_text.set('');self.viewer.zoom_text.set('')
        self.preview=CalibrationPreview();self.set_config(Config())
        labels={'id':'ID','depth':'Profundidade','confidence':'Confiança','status':'Revisão','origin':'Observações'}
        for key,label in labels.items():self.tree.heading(key,text=label)
        self.refresh_points();self.refresh_validity()
        self.status.set('Selecione uma Carta Náutica para iniciar.')

    def open_project(self):
        if self.busy or not self.confirm_replace():return
        path=filedialog.askopenfilename(filetypes=[('Projeto VetorizaFB','*.vfproject.json')])
        if not path:return
        override=None
        try:
            data=json.loads(Path(path).read_text(encoding='utf-8'))
            if not Path(data.get('input_path','')).is_file():
                override=filedialog.askopenfilename(title='Localize a carta original deste projeto',filetypes=[('Carta GeoTIFF','*.tif *.tiff')])
                if not override:return
        except Exception as exc:
            messagebox.showerror('Projeto',str(exc));return
        def done(session):
            self.session=session;self.path.set(str(session.path));self.roi=session.roi;self.set_config(session.config)
            self.model.set(session.model_spec[0]);self.model_dir.set(session.model_spec[1] or '')
            if session.model_spec[1]:self.models_root.set(str(Path(session.model_spec[1]).parent))
            self.refresh_models(select=False)
            self.output.set(str(session.path.parent/'results'/session.path.stem));self.viewer.set_session(session)
            self.viewer.layer.set('Sondagens' if session.review else 'Dígitos' if session.digits else 'Caixas')
            if session.all_boxes is not None:self.update_preview()
            self.area_mode.set('select' if self.roi else 'whole');self.roi_text.set(f'Área poligonal: {len(self.roi)} vértices' if is_polygon(self.roi) else f'Área em pixels: {self.roi}' if self.roi else 'Carta inteira');self.review_dirty=False
        self.start(lambda:ChartSession.load_project(path,override),done)

    def save_config(self):
        if self.busy:return
        try:config=self.config()
        except ValueError as exc:messagebox.showerror('Parâmetros',str(exc));return
        path=filedialog.asksaveasfilename(defaultextension='.json')
        if path:
            try:write_json_atomic(Path(path),asdict(config))
            except Exception as exc:messagebox.showerror('Parâmetros',str(exc))

    def load_config(self):
        if self.busy:return
        path=filedialog.askopenfilename(filetypes=[('Parâmetros JSON','*.json')])
        if path:
            try:self.set_config(Config(**json.loads(Path(path).read_text(encoding='utf-8'))))
            except Exception as exc:messagebox.showerror('Parâmetros',str(exc))

    def close(self):
        if self.busy:
            self.cancel.set();messagebox.showinfo('Processando','Cancelamento solicitado. Aguarde o lote/etapa antes de fechar.');return
        if self.confirm_replace():
            self._closed=True
            for tip in self.tooltips:tip.hide()
            if self._preview_id:self.root.after_cancel(self._preview_id)
            self.root.after_cancel(self._poll_id);self.root.destroy()


def main():
    root=tk.Tk();Application(root);root.mainloop()


if __name__=='__main__':main()
