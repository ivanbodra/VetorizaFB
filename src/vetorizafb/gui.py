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
import numpy as np

from .core import Config, ProcessingCancelled
from .pipeline import write_json_atomic
from .viewer import ChartViewer
from .workflow import ChartSession
from .dialogs import ScrollablePanel,PositionDialog,OffsetDialog
from . import __version__
from .calibration import CalibrationPreview
from .branding import apply_icon, asset_photo
from .ui import Tooltip
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
        self.tooltips=[]
        self.roi_text = tk.StringVar(value='Área: carta inteira')
        self.filter = tk.StringVar(value='Todos')
        self.review_note = tk.StringVar()
        self.follow_review = tk.BooleanVar(value=True)
        self.selection_text = tk.StringVar(value='0 selecionados')
        self._selection_anchor = self._last_followed = None
        self.fields = {k:tk.BooleanVar(value=v) if isinstance(v,bool) else tk.StringVar(value=str(v))
                       for k,v in asdict(Config()).items()}
        root.title(f'VetorizaFB {__version__} — processamento e revisão')
        root.geometry('1450x950');root.minsize(1050,720)
        self.configure_style()
        self.icon_path = apply_icon(root)
        self.build()
        for var in [*self.fields.values(),self.model,self.model_dir]:
            var.trace_add('write',lambda *args:self.refresh_validity())
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
        style.configure('TButton',padding=(8,4),borderwidth=1,relief='flat',background='#e5f1fb',foreground='#164f77',bordercolor='#b6d3e9',focusthickness=1,focuscolor='#0a70b5')
        style.map('TButton',background=[('disabled','#eef1f4'),('pressed','#c4dfef'),('active','#d2e8f9')],foreground=[('disabled','#8d9baa')],bordercolor=[('disabled','#e0e6ec'),('active','#468eb9')])
        for name,bg,hover,fg in [('Primary','#096fab','#085a8b','white'),('Approve','#e1f4e9','#c9ead8','#17663d'),('Reject','#fbe6e8','#f5cfd4','#9c2635')]:
            style.configure(name+'.TButton',background=bg,foreground=fg,bordercolor=bg)
            style.map(name+'.TButton',background=[('disabled','#eef1f4'),('pressed',hover),('active',hover)],foreground=[('disabled','#8d9baa')])
        style.configure('TNotebook',background='#f5f8fb',borderwidth=0,tabmargins=0)
        style.configure('TNotebook.Tab',padding=(7,7),background='#e5f1fb',foreground='#17547e',borderwidth=0,lightcolor='#e5f1fb',darkcolor='#e5f1fb')
        style.map('TNotebook.Tab',background=[('selected','#096fab'),('active','#cee7f8')],foreground=[('selected','white')],lightcolor=[('selected','#096fab')],darkcolor=[('selected','#096fab')],bordercolor=[('selected','#096fab')])
        style.configure('TEntry',fieldbackground='white',padding=4,bordercolor='#cbd9e4')
        style.configure('Required.TEntry',fieldbackground='#fff2bf',bordercolor='#d9b650')
        style.configure('TCombobox',fieldbackground='white',background='#e5f1fb',arrowcolor='#17547e',padding=3)
        style.map('TCombobox',fieldbackground=[('readonly','white')],foreground=[('readonly','#19364a')])
        style.configure('Treeview',rowheight=24,background='white',fieldbackground='white',borderwidth=0)
        style.configure('Treeview.Heading',font=(self.ui_font,9,'bold'),background='#e7eff5',foreground='#36576d',padding=5,relief='flat')
        style.map('Treeview',background=[('selected','#176b85')],foreground=[('selected','white')])
        style.configure('Brand.TFrame',background='#153b50')
        style.configure('Brand.TLabel',background='#153b50',foreground='white',font=(self.ui_font,18,'bold'))
        style.configure('Tooltip.TLabel',background='#17374b',foreground='white',font=(self.ui_font,9))
        self.stage_icons={}
        for state,colour in [('empty','#afbdc8'),('pending','#f1b747'),('ready','#57cba1'),('busy','#5eb5ff')]:
            im=Image.new('RGBA',(10,10))
            ImageDraw.Draw(im).ellipse((1,1,8,8),fill=colour)
            self.stage_icons[state]=ImageTk.PhotoImage(im,master=self.root)

    def tip(self,widget,text):
        item=Tooltip(widget,text);self.tooltips.append(item);return item

    def refresh_chart_prompt(self):
        if not hasattr(self,'chart_entry'):return
        loaded=self.session is not None and self.path.get().strip()==str(self.session.path)
        self.chart_entry.configure(style='TEntry' if loaded else 'Required.TEntry')

    def show_shortcuts(self):
        popup=tk.Toplevel(self.root);popup.title('Atalhos');popup.resizable(False,False)
        panel=ttk.Frame(popup,padding=18);panel.pack()
        for row,(keys,action) in enumerate([
            ('Setas','Navegar entre sondagens'),('Shift + setas','Selecionar faixa'),('Ctrl + clique','Selecionar ou desselecionar'),
            ('Ctrl + A','Aprovar selecionados'),('Ctrl + X','Excluir selecionados'),('Ctrl + E','Editar profundidade'),
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
        for key,label,shortcut in [('accepted','Aprovar','Ctrl+A'),('rejected','Excluir','Ctrl+X'),('edit','Editar','Ctrl+E'),('unreviewed','Marcar pendente','')]:
            button=self.review_buttons[key]
            menu.add_command(label=label,accelerator=shortcut,command=button.invoke,state='disabled' if button.instate(['disabled']) else 'normal')
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
        ttk.Label(panel,image=popup._brand_images[0]).pack(pady=(0,12))
        institutions=ttk.Frame(panel);institutions.pack(pady=(0,12))
        for name,label in [('logo_mb.png','Marinha do Brasil'),('logo_chm.png','Centro de Hidrografia da Marinha')]:
            photo=asset_photo(popup,name,(56,56));popup._brand_images.append(photo)
            badge=ttk.Frame(institutions);badge.pack(side='left',padx=14)
            ttk.Label(badge,image=photo).pack()
            ttk.Label(badge,text=label,wraplength=170,anchor='center').pack()
        ttk.Label(panel,text=f'Versão {__version__}',font=(self.ui_font,16,'bold')).pack(anchor='w')
        ttk.Label(panel,text='Extração e revisão de sondagens em cartas náuticas',padding=(0,8)).pack(anchor='w')
        ttk.Label(panel,text='Ivan Bodra Guimarães',wraplength=500).pack(anchor='w')
        ttk.Button(panel,text='Abrir manual (F1)',command=self.open_manual).pack(side='left',pady=(18,0))
        ttk.Button(panel,text='Fechar',command=popup.destroy).pack(side='right',pady=(18,0))
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
        if self._preview_id:self.root.after_cancel(self._preview_id)
        self._preview_id=self.root.after(180,self.update_preview)

    def update_preview(self):
        if self._preview_id:self.root.after_cancel(self._preview_id)
        self._preview_id=None
        if self.busy or not self.session:return
        try:
            result=self.preview.classify(self.session,self.config(),self.roi)
            self.viewer.preview_boxes=result
            if self.viewer.layer.get()=='Prévia dos filtros':
                kept=sum(not reason for _,reason in result)
                self.viewer.inspection_text.set(f'{kept} aceitas • {len(result)-kept} descartadas • prévia, ainda não aplicada')
                self.viewer.render()
        except (ValueError,TypeError) as exc:
            self.viewer.preview_boxes=[]
            if self.viewer.layer.get()=='Prévia dos filtros':
                self.viewer.inspection_text.set(str(exc));self.viewer.render()

    def measure_character(self):
        self.viewer.mode.set('Medir caractere')
        self.viewer.layer.set('Prévia dos filtros');self.update_preview()
        self.status.set('Arraste um retângulo justo ao redor de um numeral; medidas em pixels originais.')

    def use_measurement(self,minimum):
        if not self.measurement:return
        try:
            cfg=self.config();w,h=self.measurement
            # Bounds are strict in the existing segmentation; leave one reference pixel of margin.
            values=[max(1,math.floor(v/cfg.scale)-1) if minimum else math.ceil(v/cfg.scale)+1 for v in (w,h)]
            low='min_' if minimum else 'max_'
            for key,value in zip(('w','h'),values):self.fields[low+key].set(str(value))
            self.viewer.layer.set('Prévia dos filtros');self.update_preview()
        except (ValueError,TypeError) as exc:self.status.set(str(exc))

    def build(self):
        menu=tk.Menu(self.root);self.root.configure(menu=menu)
        files=tk.Menu(menu,tearoff=False);menu.add_cascade(label='Arquivo',menu=files)
        for label,command in [('Abrir carta (Ctrl+O)',self.choose_chart),('Abrir projeto',self.open_project),
                              ('Salvar projeto (Ctrl+S)',self.save_project),('Carregar parâmetros',self.load_config),
                              ('Salvar parâmetros',self.save_config),('Sair',self.close)]:
            files.add_command(label=label,command=command)
        help_menu=tk.Menu(menu,tearoff=False);menu.add_cascade(label='Ajuda',menu=help_menu)
        help_menu.add_command(label='Manual de uso (F1)',command=self.open_manual)
        help_menu.add_command(label='Atalhos de teclado…',command=self.show_shortcuts)
        help_menu.add_command(label='Carregar ícone original…',command=self.choose_icon)
        help_menu.add_separator();help_menu.add_command(label='Sobre o VetorizaFB',command=self.about)
        brand=ttk.Frame(self.root,padding=(12,5),style='Brand.TFrame');brand.pack(fill='x')
        self.header_logo=asset_photo(self.root,'logo_vetorizaFB.png',(44,34))
        self.brand_icon=ttk.Label(brand,image=self.header_logo,style='Brand.TLabel')
        self.brand_icon.pack(side='left',padx=(0,10))
        ttk.Label(brand,text=f'VetorizaFB  {__version__}',style='Brand.TLabel').pack(side='left')
        ttk.Button(brand,text='Manual · F1',command=self.open_manual).pack(side='right')
        header=ttk.Frame(self.root,padding=8);header.pack(fill='x');header.columnconfigure(1,weight=1)
        ttk.Label(header,text='CN').grid(row=0,column=0,sticky='w')
        self.chart_entry=ttk.Entry(header,textvariable=self.path,style='Required.TEntry')
        self.chart_entry.grid(row=0,column=1,sticky='ew',padx=6)
        self.tip(self.chart_entry,'Selecione uma carta náutica GeoTIFF ou informe o caminho e clique em Carregar. O amarelo indica que essa carta ainda não foi carregada.')
        ttk.Button(header,text='Abrir…',command=self.choose_chart).grid(row=0,column=2)
        ttk.Button(header,text='Carregar',command=self.load_chart).grid(row=0,column=3,padx=5)
        split=ttk.Panedwindow(self.root,orient='horizontal');split.pack(fill='both',expand=True,padx=8)
        left=ttk.Frame(split,width=355);split.add(left,weight=0)
        self.tabs=ttk.Notebook(left);self.tabs.pack(fill='both',expand=True)
        self.segment_panel=ScrollablePanel(self.tabs);seg=self.segment_panel.content
        ocr,group,export=[ttk.Frame(self.tabs,padding=9) for _ in range(3)]
        for frame,label in [(self.segment_panel,'1. Segmentar'),(ocr,'2. OCR'),(group,'3. Agrupar'),(export,'4. Exportar')]:
            self.tabs.add(frame,text=label,image=self.stage_icons['empty'],compound='left');frame.columnconfigure(1,weight=1)
        self.stage_labels=['1 Segmentar','2 OCR','3 Agrupar','4 Exportar']
        for i,label in enumerate(self.stage_labels):self.tabs.tab(i,text=label)
        self.tab_tip=self.tip(self.tabs,lambda:self.stage_tooltip())
        self.tabs.bind('<Motion>',self.tab_hover)
        seg.columnconfigure(1,weight=1)
        def setting(frame,row,label,key,values=None):
            ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w',pady=2)
            widget=ttk.Combobox(frame,textvariable=self.fields[key],values=values,state='readonly',width=13) if values else ttk.Entry(frame,textvariable=self.fields[key],width=14)
            widget.grid(row=row,column=1,sticky='ew',padx=(8,0),pady=2)
            hints={
                'dpi':'DPI real da carta. As dimensões dos filtros são escaladas em relação ao DPI de referência.',
                'reference_dpi':'DPI em que os limites de tamanho foram calibrados.',
                'min_w':'Largura mínima no DPI de referência. O limite é estrito: a caixa deve ser maior.',
                'max_w':'Largura máxima no DPI de referência. O limite é estrito: a caixa deve ser menor.',
                'min_h':'Altura mínima no DPI de referência; preserve também os decímetros menores.',
                'max_h':'Altura máxima no DPI de referência.',
                'yellow_delta':'Diferença mínima R−B e G−B nos pixels de fundo; a tinta escura é ignorada.',
                'yellow_min_fraction':'Fração mínima de fundo amarelo para rejeitar a caixa.',
                'crop_padding':'Margem em pixels originais ao redor do caractere para o OCR.',
                'min_confidence':'Escore mínimo aceito; a releitura dirigida do numeral 1 exige pelo menos 0,80.'}
            if key in hints:self.tip(widget,hints[key])
        for row,(label,key,values) in enumerate([
            ('DPI efetivo','dpi',None),('DPI de referência','reference_dpi',None),
            ('Modo','segmentation',['legacy','black']),('Limiar (0–255)','threshold',None),
            ('Desfoque','blur_size',None),('Dilatação','kernel_size',None),
            ('Largura mínima','min_w',None),('Largura máxima','max_w',None),
            ('Altura mínima','min_h',None),('Altura máxima','max_h',None)]):setting(seg,row,label,key,values)
        ttk.Checkbutton(seg,text='Excluir caixas com fundo amarelo',variable=self.fields['exclude_yellow']).grid(row=10,column=0,columnspan=2,sticky='w',pady=6)
        setting(seg,11,'R−B e G−B mínimos','yellow_delta')
        setting(seg,12,'Fração mínima do fundo','yellow_min_fraction')
        self.seg_button=ttk.Button(seg,text='Segmentar',style='Primary.TButton',command=lambda:self.run_stage('segment'))
        self.seg_button.grid(row=14,column=0,columnspan=2,sticky='ew',pady=8)
        ttk.Button(seg,text='Dimensões',command=self.inspect_sizes).grid(row=15,column=0,columnspan=2,sticky='ew',pady=3)
        ttk.Label(seg,textvariable=self.roi_text,wraplength=280).grid(row=16,column=0,columnspan=2,sticky='w',pady=8)
        ttk.Button(seg,text='Usar carta inteira',command=lambda:self.set_roi(None)).grid(row=17,column=0,columnspan=2,sticky='ew')
        ttk.Button(seg,text='Medir caractere',command=self.measure_character).grid(row=19,column=0,columnspan=2,sticky='ew',pady=5)
        ttk.Label(seg,textvariable=self.measure_text,wraplength=285).grid(row=20,column=0,columnspan=2,sticky='w',pady=5)
        ttk.Button(seg,text='Definir mínimos',command=lambda:self.use_measurement(True)).grid(row=21,column=0,columnspan=2,sticky='ew')
        ttk.Button(seg,text='Definir máximos',command=lambda:self.use_measurement(False)).grid(row=22,column=0,columnspan=2,sticky='ew',pady=3)
        ttk.Button(seg,text='Prévia dos filtros',command=lambda:(self.viewer.layer.set('Prévia dos filtros'),self.update_preview())).grid(row=23,column=0,columnspan=2,sticky='ew',pady=6)
        model_panel=ttk.Frame(ocr);model_panel.grid(row=0,column=0,columnspan=2,sticky='ew',pady=(0,10))
        model_panel.columnconfigure(1,weight=1)
        ttk.Label(model_panel,text='Pasta').grid(row=0,column=0,sticky='w',padx=(0,6),pady=4)
        self.models_entry=ttk.Entry(model_panel,textvariable=self.models_root,width=19)
        self.models_entry.grid(row=0,column=1,sticky='ew',pady=4)
        self.models_entry.bind('<Return>',lambda e:self.refresh_models())
        self.models_folder_button=ttk.Button(model_panel,text='…',width=2,command=self.choose_model)
        self.models_folder_button.grid(row=0,column=2,padx=(4,0),pady=4)
        ttk.Label(model_panel,text='Download').grid(row=1,column=0,sticky='w',padx=(0,6),pady=4)
        self.download_button=ttk.Button(model_panel,text='Conexão / baixar…',command=self.configure_model_download)
        self.download_button.grid(row=1,column=1,columnspan=2,sticky='ew',pady=4)
        ttk.Label(model_panel,text='Local').grid(row=2,column=0,sticky='w',padx=(0,6),pady=4)
        self.local_model_combo=ttk.Combobox(model_panel,textvariable=self.model,state='readonly',width=22)
        self.local_model_combo.grid(row=2,column=1,sticky='ew',pady=4)
        self.local_model_combo.bind('<<ComboboxSelected>>',lambda e:self.select_local_model())
        self.refresh_models_button=ttk.Button(model_panel,text='↻',width=2,command=self.refresh_models)
        self.refresh_models_button.grid(row=2,column=2,padx=(4,0),pady=4)
        self.tip(self.models_entry,lambda:self.models_root.get()+'\nPasta com subpastas de modelos, ou a própria pasta de um modelo. Enter atualiza a lista; nenhum arquivo é movido.')
        self.tip(self.local_model_combo,lambda:self.model_dir.get() or 'Nenhum modelo local selecionado. Escolha uma pasta ou baixe um modelo.')
        self.tip(self.download_button,'Escolher o modelo e a conexão antes de baixar. Download separado do reconhecimento; credenciais apenas nesta sessão.')
        self.tip(self.refresh_models_button,'Procurar novamente os modelos completos na pasta indicada.')
        self.refresh_models()
        for row,(label,key) in enumerate([('Tamanho do lote','ocr_batch_size'),('Margem do recorte (px)','crop_padding'),('Confiança mínima','min_confidence')],6):setting(ocr,row,label,key)
        ttk.Checkbutton(ocr,text='Reler possíveis “1”',variable=self.fields['retry_one']).grid(row=9,column=0,columnspan=2,sticky='w',pady=(8,2))
        ttk.Checkbutton(ocr,text='Reler ambíguos',variable=self.fields['retry_ambiguous']).grid(row=10,column=0,columnspan=2,sticky='w',pady=3)
        self.ocr_button=ttk.Button(ocr,text='Reconhecer',style='Primary.TButton',command=lambda:self.run_stage('ocr'))
        self.ocr_button.grid(row=12,column=0,columnspan=2,sticky='ew',pady=8)
        for row,(label,key,values) in enumerate([
            ('Modo','grouping',['relative','fixed']),('Distância X','tol_x',None),('Tolerância Y','tol_y',None),
            ('Razão altura decimal','decimal_height_ratio',None),('Queda decimal','decimal_drop',None),
            ('Inteiro máximo p/ decimal','decimal_max_integer',None),('Confiança mínima','min_confidence',None)]):setting(group,row,label,key,values)
        self.group_button=ttk.Button(group,text='Agrupar',style='Primary.TButton',command=lambda:self.run_stage('group'))
        self.group_button.grid(row=8,column=0,columnspan=2,sticky='ew',pady=10)
        ttk.Label(export,text='Pasta de saída').grid(row=0,column=0,columnspan=2,sticky='w')
        ttk.Entry(export,textvariable=self.output).grid(row=1,column=0,columnspan=2,sticky='ew',pady=5)
        ttk.Button(export,text='Selecionar saída',command=lambda:self.output.set(filedialog.askdirectory() or self.output.get())).grid(row=2,column=0,columnspan=2,sticky='ew')
        ttk.Label(export,text='CRS de saída').grid(row=3,column=0,sticky='w',pady=12)
        ttk.Entry(export,textvariable=self.target_crs).grid(row=3,column=1,sticky='ew')
        self.export_button=ttk.Button(export,text='Exportar candidatos',command=lambda:self.export(False))
        self.export_button.grid(row=4,column=0,columnspan=2,sticky='ew',pady=5)
        self.reviewed_button=ttk.Button(export,text='Exportar aprovados',command=lambda:self.export(True))
        self.reviewed_button.grid(row=5,column=0,columnspan=2,sticky='ew',pady=5)
        ttk.Button(export,text='Salvar projeto',command=self.save_project).grid(row=6,column=0,columnspan=2,sticky='ew',pady=10)
        ttk.Button(export,text='Abrir projeto',command=self.open_project).grid(row=7,column=0,columnspan=2,sticky='ew')
        controls=ttk.Frame(left);controls.pack(side='bottom',fill='x',before=self.tabs)
        self.run_button=ttk.Button(controls,text='Processar',style='Primary.TButton',command=lambda:self.run_stage('all'))
        self.run_button.pack(fill='x',pady=8)
        self.cancel_button=ttk.Button(controls,text='Cancelar',command=self.cancel.set,state='disabled');self.cancel_button.pack(fill='x')
        self.progress=ttk.Progressbar(controls,mode='determinate');self.progress.pack(fill='x',pady=6)
        summary=ttk.Label(controls,textvariable=self.counts_summary);summary.pack(fill='x',pady=3)
        self.tip(summary,lambda:self.counts.get())
        right=ttk.Panedwindow(split,orient='vertical');split.add(right,weight=1)
        self.viewer=ChartViewer(right,self.canvas_action);right.add(self.viewer,weight=3)
        bottom=ttk.Frame(right);right.add(bottom,weight=1)
        heading=ttk.Frame(bottom);heading.pack(fill='x')
        ttk.Label(heading,text='Revisão de sondagens').pack(side='left',padx=4)
        ttk.Label(heading,textvariable=self.selection_text).pack(side='left',padx=12)
        filt=ttk.Combobox(heading,textvariable=self.filter,state='readonly',width=12,values=['Todos','Pendentes','Aprovados','Excluídos']);filt.pack(side='right',padx=4)
        filt.bind('<<ComboboxSelected>>',lambda e:self.refresh_points())
        bar=ttk.Frame(bottom);bar.pack(fill='x')
        self.review_buttons={}
        for key,label,cmd in [('accepted','Aprovar',lambda:self.review_action('accepted')),('rejected','Excluir',lambda:self.review_action('rejected')),
                              ('unreviewed','Pendente',lambda:self.review_action('unreviewed')),('edit','Editar',self.correct_depth),('focus','Ampliar',self.focus_selected)]:
            button=ttk.Button(bar,text=label,command=cmd,width=0,style={'accepted':'Approve.TButton','rejected':'Reject.TButton'}.get(key,'TButton'));button.grid(row=0,column=len(self.review_buttons),padx=2,pady=2,sticky='w')
            self.review_buttons[key]=button
        tools=bar
        for key,label,cmd in [('insert','Adicionar',lambda:self.activate_review_tool('Inserir ponto')),
                              ('move','Mover',lambda:self.activate_review_tool('Mover selecionado')),
                              ('position','Posição…',self.edit_position),('offset','Offset…',self.offset_dialog)]:
            button=ttk.Button(tools,text=label,command=cmd,width=0);button.grid(row=0,column=len(self.review_buttons),padx=2,pady=2,sticky='w')
            self.review_buttons[key]=button
        bar.bind('<Configure>',lambda event:self.layout_review_toolbar(event.width))
        select=ttk.Frame(bottom);select.pack(fill='x')
        for label,cmd in [('Todos',self.select_all_points),('Limpar',self.clear_point_selection),('Inverter',self.invert_point_selection)]:
            ttk.Button(select,text=label,command=cmd,width=0).pack(side='left',padx=2,pady=3)
        ttk.Checkbutton(select,text='Acompanhar',variable=self.follow_review,command=lambda:self.focus_selected() if self.follow_review.get() else None).pack(side='left',padx=8)
        self.tree=ttk.Treeview(bottom,columns=['id','depth','confidence','status','origin'],show='headings',selectmode='extended',height=5)
        for key,label,width in [('id','ID',45),('depth','Profundidade',100),('confidence','Confiança',85),('status','Revisão',100),('origin','Observações',240)]:
            self.tree.heading(key,text=label);self.tree.column(key,width=width,minwidth=35)
        scroll=ttk.Scrollbar(bottom,orient='vertical',command=self.tree.yview);scroll.pack(side='right',fill='y');self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(fill='both',expand=True)
        self.tree.bind('<<TreeviewSelect>>',lambda e:self.select_point())
        self.tree.bind('<Double-1>',lambda e:self.focus_selected())
        self.tree.bind('<ButtonPress-1>',self.review_click)
        # Local bindings leave Ctrl+A/Ctrl+X and arrow editing native in entries.
        for widget in (self.tree,self.viewer.canvas):
            for key,step in [('Up',-1),('Left',-1),('Down',1),('Right',1)]:
                widget.bind(f'<{key}>',lambda e,s=step:self.navigate_review(s))
                widget.bind(f'<Shift-{key}>',lambda e,s=step:self.navigate_review(s,extend=True))
            for key,command in [('Control-a',lambda:self.review_action('accepted')),
                                ('Control-x',lambda:self.review_action('rejected')),
                                ('Control-e',self.correct_depth),('Control-Shift-A',self.select_all_points),
                                ('Escape',self.clear_point_selection),('Control-space',self.toggle_active_point)]:
                widget.bind(f'<{key}>',lambda e,cmd=command:self.review_shortcut(cmd))
        notes=ttk.Frame(bottom);notes.pack(fill='x',before=self.tree)
        ttk.Label(notes,text='Nota').pack(side='left',padx=4)
        self.note_entry=ttk.Entry(notes,textvariable=self.review_note)
        self.note_entry.pack(side='left',fill='x',expand=True,padx=4,pady=3)
        self.footer=ttk.Label(self.root,textvariable=self.status,wraplength=1400,padding=(8,3))
        self.footer.pack(side='bottom',fill='x',before=split)
        self.footer.bind('<Configure>',lambda e:self.footer.configure(wraplength=max(100,e.width-16)))
        for key,text in {
            'accepted':'Aprovar selecionados · Ctrl+A', 'rejected':'Excluir selecionados · Ctrl+X',
            'unreviewed':'Voltar selecionados para pendentes', 'edit':'Editar uma profundidade · Ctrl+E',
            'focus':'Centralizar e ampliar o ponto ativo', 'insert':'Adicionar profundidade: clique na imagem. Esc cancela.',
            'move':'Mover o ponto selecionado: clique na nova posição.', 'position':'Editar X/Y em pixels originais',
            'offset':'Prévia e deslocamento de todos os pontos ou dos selecionados'}.items():self.tip(self.review_buttons[key],text)
        self.tip(self.seg_button,'Aplicar os filtros e recalcular a segmentação. Requer uma carta carregada.')
        self.tip(self.ocr_button,'Reconhecer as caixas da segmentação atual. A releitura preserva o texto e o escore originais.')
        self.tip(self.group_button,'Agrupar dígitos em profundidades; reutiliza o OCR válido. Salve a revisão antes de reagrupar.')
        self.tip(self.run_button,'Executar somente as etapas pendentes: segmentar, reconhecer e agrupar.')
        self.tip(self.cancel_button,'Solicitar cancelamento ao término do lote ou etapa atual.')
        for widget in (self.tree,self.viewer.canvas):widget.bind('<Button-3>',self.show_review_menu)
        # Fit compact toolbar labels to their content rather than Tk's default width.
        def compact(widget):
            for child in widget.winfo_children():
                if isinstance(child,ttk.Button):child.configure(width=0)
                compact(child)
        compact(self.root)

    def layout_review_toolbar(self,width):
        x=y=0
        height=max(button.winfo_reqheight() for button in self.review_buttons.values())+4
        for button in self.review_buttons.values():
            needed=button.winfo_reqwidth()+4
            if x and x+needed>width:x=0;y+=height
            button.grid_forget()
            button.place(x=x+2,y=y+2,width=needed-4,height=height-4)
            x+=needed
        self.review_buttons['accepted'].master.configure(height=y+height)

    def config(self):
        defaults=asdict(Config());data={}
        integers={'threshold','blur_size','kernel_size','min_w','max_w','min_h','max_h','ocr_batch_size','crop_padding','yellow_delta'}
        for key,var in self.fields.items():
            value=var.get()
            try:
                if isinstance(defaults[key],bool):data[key]=bool(value)
                elif key in integers:data[key]=int(value)
                elif isinstance(defaults[key],str):data[key]=str(value)
                else:data[key]=float(value)
            except (ValueError,TypeError):raise ValueError(f'Valor inválido em {key}')
        return Config(**data)

    def model_spec(self):return (self.model.get(),self.model_dir.get().strip() or None,'cpu')

    def set_config(self,config):
        for k,v in asdict(config).items():self.fields[k].set(v)

    def tab_hover(self,event):
        try:index=self.tabs.index(f'@{event.x},{event.y}')
        except tk.TclError:return
        if index!=getattr(self,'_hover_tab',None):
            self._hover_tab=index;self.tab_tip.schedule()

    def stage_tooltip(self):
        index=getattr(self,'_hover_tab',0)
        if not self.stage_states:return 'Carregue uma carta para iniciar.'
        names=['Segmentação','OCR','Agrupamento','Exportação']
        info={'empty':'carregue uma carta','pending':'precisa executar ou atualizar','ready':'atualizada','busy':'processando'}
        return names[index]+': '+info[self.stage_states[index]]+'.'

    def refresh_validity(self):
        if hasattr(self,"viewer"):self.schedule_preview()
        if not hasattr(self,'seg_button'):return
        seg=digits=groups=False
        try:
            cfg=self.config()
            if self.session:
                seg=self.session.valid_segments(cfg,self.roi)
                digits=self.session.valid_digits(cfg,self.model_spec(),self.roi)
                groups=self.session.valid_groups(cfg,self.model_spec(),self.roi)
            self.validity.set(f"Segmentação: {'atualizada' if seg else 'pendente'} | OCR: {'atualizado' if digits else 'pendente'} | Agrupamento: {'atualizado' if groups else 'pendente'}")
        except (ValueError,TypeError) as exc:
            self.validity.set(str(exc))
            if not self.busy:self.status.set(str(exc))
        for button,enabled in [(self.seg_button,self.session is not None),(self.ocr_button,seg),
                               (self.group_button,digits),(self.run_button,self.session is not None),
                               (self.export_button,groups),(self.reviewed_button,groups and self.session.review.counts['accepted']>0)]:
            button.configure(state='normal' if enabled and not self.busy else 'disabled')
        for widget in (self.models_entry,self.models_folder_button,self.download_button,self.refresh_models_button):widget.configure(state='disabled' if self.busy else 'normal')
        self.local_model_combo.configure(state='disabled' if self.busy else 'readonly')
        self.refresh_chart_prompt()
        self.stage_states=[('empty' if self.session is None else 'busy' if self.busy else 'ready' if valid else 'pending') for valid in (seg,digits,groups,groups)]
        for index,state in enumerate(self.stage_states):self.tabs.tab(index,image=self.stage_icons[state])
        self.refresh_review_controls()

    def start(self,task,done=lambda result:None,cancellable=True):
        if self.busy:return
        self.busy=True;self.cancel.clear();self.refresh_validity()
        self.viewer.mode.set('Inspecionar');self._one_shot_mode=False
        self.viewer.suspended=True
        self.cancel_button.configure(state='normal' if cancellable else 'disabled')
        self.progress.configure(mode='indeterminate');self.progress.start(12)
        self.status.set('Processando. Cancelamento é verificado entre lotes e etapas.')
        def worker():
            try:self.events.put(('ok',task(),done))
            except Exception as exc:self.events.put(('error',exc,traceback.format_exc()))
        threading.Thread(target=worker,daemon=True).start()

    def report_progress(self,current,total,stage):self.events.put(('progress',(current,total,stage),None))

    def poll(self):
        try:
            while True:
                kind,value,callback=self.events.get_nowait()
                if kind=='progress':
                    current,total,stage=value;self.progress.stop();self.progress.configure(mode='determinate',value=100*current/max(1,total));self.status.set(f'{stage}: {current}/{total}')
                else:
                    self.busy=False;self.progress.stop();self.progress.configure(mode='determinate',value=0)
                    self.viewer.suspended=False
                    self.cancel_button.configure(state='disabled')
                    if kind=='ok':
                        try:
                            callback(value);self.status.set('Concluído.')
                        except Exception as exc:
                            self.status.set(str(exc));messagebox.showerror('Interface',str(exc),parent=self.root)
                    elif isinstance(value,ProcessingCancelled):self.status.set('Cancelado. Etapas já concluídas foram preservadas.')
                    else:
                        self.status.set(str(value));messagebox.showerror('Processamento',str(value),parent=self.root)
                    self.refresh_points();self.refresh_validity()
                    if self.session:self.viewer.render()
        except queue.Empty:pass
        if not self._closed:self._poll_id=self.root.after(80,self.poll)

    def confirm_replace(self):
        return not self.review_dirty or messagebox.askyesno('Preservar revisão','Há decisões de revisão não salvas. Salve o projeto para preservá-las. Deseja substituir/fechar esta revisão mesmo assim?',parent=self.root)

    def choose_chart(self):
        if self.busy:return
        path=filedialog.askopenfilename(filetypes=[('Carta GeoTIFF','*.tif *.tiff')])
        if path:self.path.set(path);self.load_chart()

    def load_chart(self):
        if self.busy or not self.confirm_replace():return
        path=self.path.get()
        def done(session):
            self.session=session;self.roi=None;self.review_dirty=False
            self.path.set(str(session.path))
            self.set_config(session.config);self.viewer.set_session(session)
            self.output.set(str(session.path.parent/'results'/session.path.stem))
            if session.dpi is None:
                dpi=simpledialog.askfloat('DPI ausente','Informe o DPI efetivo da carta antes de segmentar:',minvalue=1,parent=self.root)
                self.fields['dpi'].set('' if dpi is None else str(dpi))
            self.roi_text.set('Área: carta inteira')
        self.start(lambda:ChartSession(path),done)

    def choose_model(self):
        if self.busy:return
        path=filedialog.askdirectory(title='Pasta com modelos OCR',initialdir=self.models_root.get())
        if not path:return
        selected=inspect_model(path)
        if selected:path=str(selected.path.parent)
        self.models_root.set(path);self.refresh_models()
        if selected:self.model.set(selected.name);self.select_local_model()
        try:save_model_root(path)
        except OSError:self.status.set('Pasta selecionada; não foi possível guardar a preferência.')

    def refresh_models(self,select=True):
        if self.busy:return
        models=discover_models(self.models_root.get()) if self.models_root.get().strip() else []
        self.local_models={}
        for model in models:self.local_models.setdefault(model.name,model)
        self.local_model_combo.configure(values=list(self.local_models))
        if select:
            name=self.model.get() if self.model.get() in self.local_models else next(iter(self.local_models),'')
            self.model.set(name);self.select_local_model()

    def select_local_model(self):
        if self.busy:return
        model=self.local_models.get(self.model.get())
        self.model_dir.set(str(model.path) if model else '')
        if hasattr(self,'review_buttons'):self.refresh_validity()

    def configure_model_download(self):
        if self.busy:return
        root=self.models_root.get().strip()
        direct=inspect_model(root) if root else None
        if direct:root=str(direct.path.parent);self.models_root.set(root)
        if not root:messagebox.showerror('Modelos','Informe uma pasta para os modelos.',parent=self.root);return
        dialog=ModelDownloadDialog(self.root,root,self.network_settings,self.model.get())
        if dialog.result is None:return
        name,connection=dialog.result;self.network_settings=connection
        def progress(received,total):
            self.report_progress(received,total or max(1,received),f'Baixando {name}')
        def done(model):
            # Source path is always explicit after download; no implicit network on OCR.
            self.refresh_models();self.model.set(model.name);self.local_models[model.name]=model
            self.local_model_combo.configure(values=list(self.local_models));self.select_local_model()
            try:save_model_root(root)
            except OSError:pass
        self.start(lambda:download_model(name,root,connection,cancel=self.cancel,progress=progress),done)

    def require_local_model(self,spec):
        name,path,_=spec
        if path:
            model=inspect_model(path)
            if model and model.name==name:return (name,str(model.path),spec[2])
        else:
            candidates=discover_models(self.models_root.get())
            for model in candidates:
                if model.name==name:return (name,str(model.path),spec[2])
        raise ValueError('Selecione um modelo local completo ou use Conexão / baixar antes de executar o OCR.')

    def set_roi(self,roi):
        if self.busy:return
        self.roi=roi;self.viewer.roi=roi
        self.roi_text.set(f'Área em pixels: {roi}' if roi else 'Área: carta inteira')
        self.refresh_validity();self.viewer.render()

    def run_stage(self,stage):
        if self.busy or self.session is None:return
        try:
            cfg=self.config();spec=self.model_spec()
            if stage=='ocr' or (stage=='all' and not self.session.valid_digits(cfg,spec,self.roi)):spec=self.require_local_model(spec)
        except ValueError as exc:messagebox.showerror('Parâmetros',str(exc));return
        if not self.confirm_replace():return
        if spec[1] and spec[1]!=self.model_dir.get():self.model_dir.set(spec[1])
        session,roi=self.session,self.roi
        previous_review=session.review
        def task():
            if stage=='segment' or (stage=='all' and not session.valid_segments(cfg,roi)):session.segment(cfg,roi,self.cancel)
            if stage=='ocr' or (stage=='all' and not session.valid_digits(cfg,spec,roi)):
                session.run_ocr(cfg,spec,roi,progress=self.report_progress,cancel=self.cancel)
            if stage=='group' or (stage=='all' and not session.valid_groups(cfg,spec,roi)):session.run_grouping(cfg,spec,roi,self.cancel)
        def done(_):
            if session.review is not previous_review:self.review_dirty=False
            self.viewer.layer.set('Sondagens' if session.review is not None else 'OCR' if session.digits is not None else 'Caixas')
            self.viewer.selected_id=None
        self.start(task,done)

    def refresh_points(self):
        selection=self.tree.selection();active=self.tree.focus()
        previous=list(self.tree.get_children())
        previous_index=previous.index(active) if active in previous else None
        self.tree.delete(*previous)
        if self.session is None:
            self.select_point();return
        session=self.session;counts=session.review.counts if session.review else {}
        timing_names={'segment':'Segmentação','ocr':'OCR','group':'Agrupamento'}
        self.counts_summary.set(f"{len(session.boxes or [])} caixas · {sum(counts.values())} sondagens")
        self.counts.set(f"Caixas: {len(session.boxes or [])} | Cor: {len(session.color_rejected)} rejeitadas | Dígitos: {sum(d.text is not None for d in session.digits or [])}\nPendentes: {counts.get('unreviewed',0)} | Aprovados: {counts.get('accepted',0)} | Excluídos: {counts.get('rejected',0)}\n"+', '.join(f'{timing_names[k]}: {v:.3f}s' for k,v in session.timings.items()))
        if session.review is None:
            self.select_point();return
        selected_status={'Pendentes':'unreviewed','Aprovados':'accepted','Excluídos':'rejected'}.get(self.filter.get())
        labels={'unreviewed':'Pendente','accepted':'Aprovado','rejected':'Excluído'}
        for item in session.review.items:
            if selected_status and item['status']!=selected_status:continue
            s=item['current'];conf=s['confidence']
            flags={'ocr_retry':'Releitura OCR','ocr_one_retry':'Releitura dirigida: 1','manual_depth':'Valor corrigido','manual_position':'Posição corrigida','manual_addition':'Ponto manual'}
            visible_flags=[f for f in s['flags'] if f!='ocr_retry' or 'ocr_one_retry' not in s['flags']]
            self.tree.insert('','end',iid=str(item['id']),values=[item['id'],f"{s['depth']:g}",'' if conf is None else f'{conf:.3f}',labels[item['status']],', '.join(flags.get(f,f) for f in visible_flags)])
        remaining=[i for i in selection if self.tree.exists(i)]
        self.tree.selection_set(remaining)
        rows=self.tree.get_children()
        if active and self.tree.exists(active):self.tree.focus(active)
        elif previous_index is not None and rows:
            # In a Pending-only view, approving/excluding moves to the next row.
            next_id=rows[min(previous_index,len(rows)-1)]
            self.tree.focus(next_id)
            if not remaining:self.tree.selection_set(next_id)
            self.tree.see(next_id)
            self._selection_anchor=next_id
        self.select_point()

    def refresh_review_controls(self):
        if not hasattr(self,'tree'):return
        selected=len(self.tree.selection());ready=self.review_ready()
        self.selection_text.set(f'{selected} selecionados / {len(self.tree.get_children())} visíveis')
        for key,button in self.review_buttons.items():
            if key in {'edit','move','position'}:enabled=ready and selected==1
            elif key=='insert':enabled=ready
            elif key=='offset':enabled=ready and bool(self.session.review.items)
            elif key=='focus':enabled=ready and bool(self.tree.focus())
            else:enabled=ready and selected>0
            button.configure(state='normal' if enabled else 'disabled')

    def review_ready(self):
        if self.busy or not self.session:return False
        try:return self.session.valid_groups(self.config(),self.model_spec(),self.roi)
        except ValueError:return False

    def review_action(self,action):
        if not self.review_ready():return
        for point_id in self.tree.selection():self.session.review.change(point_id,action,note=self.review_note.get())
        if self.tree.selection():self.review_dirty=True
        self.refresh_points();self.refresh_validity();self.viewer.render()

    def correct_depth(self):
        if not self.review_ready() or len(self.tree.selection())!=1:return
        point_id=self.tree.selection()[0];item=self.session.review.item(point_id)
        value=simpledialog.askfloat('Corrigir profundidade','Valor em metros, até uma casa decimal:',initialvalue=item['current']['depth'],parent=self.root)
        if value is None:return
        try:self.session.review.change(point_id,'correct_depth',depth=value,note=self.review_note.get())
        except ValueError as exc:messagebox.showerror('Profundidade',str(exc));return
        self.review_dirty=True;self.refresh_points();self.refresh_validity();self.viewer.render()

    def select_point(self):
        selected=self.tree.selection();active=self.tree.focus()
        if not active and selected:
            active=selected[-1];self.tree.focus(active)
        self.viewer.selected_ids={int(i) for i in selected}
        self.viewer.selected_id=int(active) if active else None
        self.refresh_review_controls()
        if self.busy:return
        key=None
        if active and self.session and self.session.review:
            s=self.session.review.item(active)['current']
            key=(id(self.session.review),active,s['pixel_x'],s['pixel_y'],tuple(s['bounds']))
        if self.follow_review.get() and key is not None and key!=self._last_followed:
            self.focus_selected()
        else:self.viewer.render()
        self._last_followed=key

    def focus_selected(self):
        active=self.tree.focus() or next(iter(self.tree.selection()),None)
        if self.busy or not self.session or not active or self.session.review is None:return
        s=self.session.review.item(active)['current']
        self.viewer.layer.set('Sondagens');self.viewer.focus(s['pixel_x'],s['pixel_y'],s['bounds'])

    def review_shortcut(self,command):
        if not self.busy:command()
        return 'break'

    def review_click(self,event):
        row=self.tree.identify_row(event.y)
        if row and not event.state & 1:self._selection_anchor=row

    def navigate_review(self,step,extend=False):
        if self.busy:return 'break'
        rows=list(self.tree.get_children())
        if not rows:return 'break'
        active=self.tree.focus()
        index=rows.index(active) if active in rows else (-1 if step>0 else len(rows))
        target=rows[max(0,min(len(rows)-1,index+step))]
        if extend:
            anchor=self._selection_anchor if self._selection_anchor in rows else active if active in rows else target
            self._selection_anchor=anchor
            a,b=sorted((rows.index(anchor),rows.index(target)))
            self.tree.selection_set(rows[a:b+1])
        else:
            self.tree.selection_set(target);self._selection_anchor=target
        self.tree.focus(target);self.tree.see(target);self.select_point()
        return 'break'

    def select_all_points(self):
        if self.busy:return
        rows=self.tree.get_children();self.tree.selection_set(rows)
        if rows and not self.tree.focus():self.tree.focus(rows[0])
        self.select_point()

    def clear_point_selection(self):
        if self.busy:return
        self.viewer.mode.set('Inspecionar');self._one_shot_mode=False
        self.tree.selection_remove(self.tree.selection());self.tree.focus('')
        self._selection_anchor=None;self.select_point()

    def invert_point_selection(self):
        if self.busy:return
        selected=set(self.tree.selection())
        self.tree.selection_set([i for i in self.tree.get_children() if i not in selected])
        self.select_point()

    def toggle_active_point(self):
        active=self.tree.focus()
        if self.busy or not active:return
        if active in self.tree.selection():self.tree.selection_remove(active)
        else:self.tree.selection_add(active)
        self.select_point()

    def activate_review_tool(self,mode):
        if not self.review_ready() or (mode=='Mover selecionado' and len(self.tree.selection())!=1):return
        self._one_shot_mode=True;self.viewer.layer.set('Sondagens');self.viewer.mode.set(mode)
        self.viewer.canvas.focus_set()
        self.status.set('Clique na posição da nova profundidade. Esc cancela.' if mode=='Inserir ponto'
                        else 'Clique na nova posição da sondagem selecionada. Esc cancela.')

    def finish_position_edit(self,point_id):
        self.review_dirty=True;self.filter.set('Todos');self.refresh_points()
        self.tree.selection_set(str(point_id));self.tree.focus(str(point_id));self.tree.see(str(point_id))
        self.select_point();self.refresh_validity()

    def edit_position(self):
        if not self.review_ready() or len(self.tree.selection())!=1:return
        point_id=self.tree.selection()[0]
        dialog=PositionDialog(self.root,self.session,point_id)
        if dialog.result is None:return
        try:self.session.reposition_point(point_id,*dialog.result,note=self.review_note.get())
        except ValueError as exc:messagebox.showerror('Posição',str(exc),parent=self.root);return
        self.finish_position_edit(point_id)

    def offset_dialog(self):
        if not self.review_ready() or not self.session.review.items:return
        dialog=OffsetDialog(self.root,self.session,self.tree.selection())
        if dialog.result is None:return
        try:result=self.session.offset_points(**dialog.result,note=self.review_note.get())
        except (ValueError,KeyError) as exc:messagebox.showerror('Deslocamento',str(exc),parent=self.root);return
        if result['batch_id'] is None:return
        self.review_dirty=True;self.filter.set('Todos');self.refresh_points();self.refresh_validity()
        self._last_followed=None;self.select_point()
        self.status.set(f"Deslocamento aplicado a {result['count']} sondagens: Δpixel X={result['pixel_dx']:.6g}, Y={result['pixel_dy']:.6g}. Revise as novas posições.")

    def canvas_action(self,action,xy):
        if self.busy:return
        if action=='measure':
            self.measurement=xy
            try:
                scale=self.config().scale
                self.measure_text.set(f'{xy[0]} × {xy[1]} px originais\n{xy[0]/scale:.1f} × {xy[1]/scale:.1f} px no DPI de referência')
                self.viewer.inspection_text.set(self.measure_text.get().replace('\n',' • '))
            except (ValueError,TypeError):self.measure_text.set('Corrija os parâmetros de DPI para converter a medida.')
            return
        if action=='roi':self.set_roi(xy);return
        if action in {'Inserir ponto','Mover selecionado'}:
            if not self.review_ready():return
            if action=='Inserir ponto':
                value=simpledialog.askfloat('Sondagem ausente','Profundidade em metros, até uma casa decimal:',parent=self.root)
                if value is None:
                    if self._one_shot_mode:self.viewer.mode.set('Inspecionar');self._one_shot_mode=False
                    return
                try:point_id=self.session.add_point(*xy,value,note=self.review_note.get())
                except ValueError as exc:messagebox.showerror('Profundidade',str(exc));return
            else:
                if len(self.tree.selection())!=1:return
                point_id=self.tree.selection()[0]
                try:self.session.reposition_point(point_id,*xy,note=self.review_note.get())
                except ValueError as exc:messagebox.showerror('Posição',str(exc));return
            if self._one_shot_mode:self.viewer.mode.set('Inspecionar');self._one_shot_mode=False
            self.finish_position_edit(point_id);return
        if self.session and self.viewer.layer.get()=='OCR' and self.session.digits:
            px,py=xy
            nearby=[d for d in self.session.digits if d.box.x-3<=px<=d.box.x+d.box.w+3 and d.box.y-3<=py<=d.box.y+d.box.h+3]
            if nearby:self.inspect_digit(min(nearby,key=lambda d:math.hypot(d.box.center[0]-px,d.box.center[1]-py)))
        elif self.session and self.session.review and self.session.review.items:
            px,py=xy
            item=min(self.session.review.items,key=lambda i:math.hypot(i['current']['pixel_x']-px,i['current']['pixel_y']-py))
            s=item['current']
            if math.hypot(s['pixel_x']-px,s['pixel_y']-py)*self.viewer.scale<30:
                self.filter.set('Todos');self.refresh_points();point_id=str(item['id'])
                if action=='toggle_point':
                    if point_id in self.tree.selection():self.tree.selection_remove(point_id)
                    else:self.tree.selection_add(point_id)
                elif action=='range_point' and self._selection_anchor in self.tree.get_children():
                    rows=list(self.tree.get_children());a,b=sorted((rows.index(self._selection_anchor),rows.index(point_id)))
                    self.tree.selection_set(rows[a:b+1])
                else:self.tree.selection_set(point_id)
                if action!='range_point':self._selection_anchor=point_id
                self.tree.focus(point_id);self.tree.see(point_id);self.select_point()

    def inspect_digit(self,digit):
        popup=tk.Toplevel(self.root);popup.title(f'Caractere {digit.index} / leitura original e alternativas')
        b=digit.box;rgb=self.session.rgb
        crop=Image.fromarray(rgb[max(0,b.y-8):b.y+b.h+8,max(0,b.x-8):b.x+b.w+8])
        factor=max(1,min(8,200/crop.height));crop=crop.resize((round(crop.width*factor),round(crop.height*factor)))
        photo=ImageTk.PhotoImage(crop);label=ttk.Label(popup,image=photo);label.image=photo;label.pack(padx=12,pady=12)
        text=f"Texto original: {digit.raw_text!r}\nEscore original: {digit.confidence:.4f}\nLeitura usada: {digit.text!r}\nMétodo: {digit.method}\nCaixa: {b}\nAlternativas: {digit.alternatives}"
        ttk.Label(popup,text=text,wraplength=650,padding=12).pack()

    def inspect_sizes(self):
        if self.busy or not self.session:return
        boxes=self.session.all_boxes
        if boxes is None:messagebox.showinfo('Dimensões','Execute a etapa 1 para atualizar o inspetor.');return
        popup=tk.Toplevel(self.root);popup.title('Dimensões de contornos / calibração');popup.geometry('760x550')
        ttk.Label(popup,text=f'{len(boxes)} contornos; {len(self.session.boxes)} caixas aceitas. Dimensões em pixels reais.',padding=10).pack()
        canvas=tk.Canvas(popup,bg='white');canvas.pack(fill='both',expand=True)
        if not boxes:return
        def draw(event=None):
            canvas.delete('all');cw,ch=max(1,canvas.winfo_width()),max(1,canvas.winfo_height())
            for offset,key in [(0,'w'),(ch/2,'h')]:
                vals=[getattr(b,key) for b in boxes];limit=max(20,float(np.percentile(vals,98)))
                hist,edges=np.histogram(vals,bins=35,range=(0,limit));maxv=max(1,max(hist))
                canvas.create_text(15,offset+15,text=('Largura' if key=='w' else 'Altura')+f' (até P98={limit:.1f}px)',anchor='w')
                for i,value in enumerate(hist):
                    x=35+i*(cw-65)/35;y=offset+ch/2-25
                    canvas.create_rectangle(x,y-(ch/2-65)*value/maxv,x+(cw-65)/35-1,y,fill='#368a9b',outline='')
                cfg=self.session.config
                for name,colour in [('min_'+key,'#00a000'),('max_'+key,'#c00000')]:
                    value=getattr(cfg,name)*cfg.scale
                    if value<=limit:
                        x=35+value/limit*(cw-65);canvas.create_line(x,offset+35,x,offset+ch/2-25,fill=colour,width=2)
                        canvas.create_text(x,offset+ch/2-13,text=f'{value:g}',fill=colour)
        canvas.bind('<Configure>',draw)

    def export(self,accepted_only):
        if not self.review_ready():return
        if not self.output.get():messagebox.showerror('Saída','Selecione uma pasta de saída.');return
        suffix='reviewed' if accepted_only else 'candidates'
        target=Path(self.output.get())/f'{self.session.path.stem}.{suffix}.metadata.json'
        if target.exists() and not messagebox.askyesno('Arquivos existentes','Substituir os arquivos desta exportação?',parent=self.root):return
        directory,crs=self.output.get(),self.target_crs.get()
        self.start(lambda:self.session.export(directory,target_crs=crs,accepted_only=accepted_only),
                   lambda meta:messagebox.showinfo('Exportação',f"{meta['soundings']} pontos gravados em {directory}\n{meta['status']}",parent=self.root),cancellable=False)

    def save_project(self):
        if self.busy or not self.session:return
        path=filedialog.asksaveasfilename(defaultextension='.vfproject.json',filetypes=[('Projeto VetorizaFB','*.vfproject.json')])
        if path:
            def done(_):self.review_dirty=False
            self.start(lambda:self.session.save_project(path),done,cancellable=False)

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
            self.viewer.layer.set('Sondagens' if session.review else 'OCR' if session.digits else 'Caixas')
            self.roi_text.set(f'Área em pixels: {self.roi}' if self.roi else 'Área: carta inteira');self.review_dirty=False
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
