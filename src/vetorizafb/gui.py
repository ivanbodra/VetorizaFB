"""Staged calibration and review UI for the shared OCR core."""
from dataclasses import asdict
import json
import math
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import traceback

from .runtime import configure_gis_runtime
configure_gis_runtime()

from PIL import Image, ImageTk
import numpy as np

from .core import Config, ProcessingCancelled
from .pipeline import write_json_atomic
from .viewer import ChartViewer
from .workflow import ChartSession
from . import __version__


class Application:
    def __init__(self,root):
        self.root, self.session = root,None
        self.busy = self.review_dirty = False
        self._closed=False
        self.roi = None
        self.events, self.cancel = queue.Queue(),threading.Event()
        self.path, self.output = tk.StringVar(),tk.StringVar()
        self.model = tk.StringVar(value='PP-OCRv6_small_rec')
        self.model_dir, self.target_crs = tk.StringVar(),tk.StringVar(value='EPSG:4326')
        self.status = tk.StringVar(value='Selecione uma carta GeoTIFF para iniciar.')
        self.validity, self.counts = tk.StringVar(),tk.StringVar()
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
        self.build()
        for var in [*self.fields.values(),self.model,self.model_dir]:
            var.trace_add('write',lambda *args:self.refresh_validity())
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.bind('<Control-o>',lambda e:self.choose_chart())
        root.bind('<Control-s>',lambda e:self.save_project())
        self._poll_id=root.after(80,self.poll)
        self.refresh_validity()

    def build(self):
        menu=tk.Menu(self.root);self.root.configure(menu=menu)
        files=tk.Menu(menu,tearoff=False);menu.add_cascade(label='Arquivo',menu=files)
        for label,command in [('Abrir carta (Ctrl+O)',self.choose_chart),('Abrir projeto',self.open_project),
                              ('Salvar projeto (Ctrl+S)',self.save_project),('Carregar parâmetros',self.load_config),
                              ('Salvar parâmetros',self.save_config),('Sair',self.close)]:
            files.add_command(label=label,command=command)
        header=ttk.Frame(self.root,padding=8);header.pack(fill='x');header.columnconfigure(1,weight=1)
        ttk.Label(header,text='Carta').grid(row=0,column=0,sticky='w')
        ttk.Entry(header,textvariable=self.path).grid(row=0,column=1,sticky='ew',padx=6)
        ttk.Button(header,text='Selecionar / abrir',command=self.choose_chart).grid(row=0,column=2)
        ttk.Button(header,text='Abrir caminho',command=self.load_chart).grid(row=0,column=3,padx=5)
        ttk.Label(header,textvariable=self.validity).grid(row=1,column=0,columnspan=4,sticky='w',pady=5)
        split=ttk.Panedwindow(self.root,orient='horizontal');split.pack(fill='both',expand=True,padx=8)
        left=ttk.Frame(split,width=355);split.add(left,weight=0)
        self.tabs=ttk.Notebook(left);self.tabs.pack(fill='both',expand=True)
        seg,ocr,group,export=[ttk.Frame(self.tabs,padding=9) for _ in range(4)]
        for frame,label in [(seg,'1. Segmentar'),(ocr,'2. OCR'),(group,'3. Agrupar'),(export,'4. Exportar')]:
            self.tabs.add(frame,text=label);frame.columnconfigure(1,weight=1)
        def setting(frame,row,label,key,values=None):
            ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w',pady=4)
            widget=ttk.Combobox(frame,textvariable=self.fields[key],values=values,state='readonly',width=13) if values else ttk.Entry(frame,textvariable=self.fields[key],width=14)
            widget.grid(row=row,column=1,sticky='ew',padx=(8,0),pady=3)
        for row,(label,key,values) in enumerate([
            ('DPI efetivo','dpi',None),('DPI de referência','reference_dpi',None),
            ('Modo','segmentation',['legacy','black']),('Limiar (0–255)','threshold',None),
            ('Desfoque','blur_size',None),('Dilatação','kernel_size',None),
            ('Largura mínima','min_w',None),('Largura máxima','max_w',None),
            ('Altura mínima','min_h',None),('Altura máxima','max_h',None)]):setting(seg,row,label,key,values)
        self.seg_button=ttk.Button(seg,text='Executar etapa 1',command=lambda:self.run_stage('segment'))
        self.seg_button.grid(row=11,column=0,columnspan=2,sticky='ew',pady=8)
        ttk.Button(seg,text='Inspecionar dimensões / histogramas',command=self.inspect_sizes).grid(row=12,column=0,columnspan=2,sticky='ew',pady=3)
        ttk.Label(seg,textvariable=self.roi_text,wraplength=310).grid(row=13,column=0,columnspan=2,sticky='w',pady=8)
        ttk.Button(seg,text='Usar carta inteira',command=lambda:self.set_roi(None)).grid(row=14,column=0,columnspan=2,sticky='ew')
        ttk.Label(seg,text='Para trabalhar por área, escolha “Selecionar área” na imagem e arraste um retângulo. As coordenadas continuam referidas à carta original.',wraplength=310).grid(row=15,column=0,columnspan=2,pady=12,sticky='w')
        ttk.Label(ocr,text='Modelo OCR').grid(row=0,column=0,sticky='w')
        ttk.Combobox(ocr,textvariable=self.model,state='readonly',width=23,values=['PP-OCRv6_small_rec','PP-OCRv6_medium_rec','PP-OCRv5_server_rec']).grid(row=1,column=0,columnspan=2,sticky='ew',pady=5)
        ttk.Label(ocr,text='Pasta local de inferência (opcional)').grid(row=2,column=0,columnspan=2,sticky='w',pady=(10,3))
        ttk.Entry(ocr,textvariable=self.model_dir).grid(row=3,column=0,columnspan=2,sticky='ew')
        ttk.Button(ocr,text='Selecionar pasta do modelo',command=self.choose_model).grid(row=4,column=0,columnspan=2,sticky='ew',pady=5)
        for row,(label,key) in enumerate([('Tamanho do lote','ocr_batch_size'),('Margem do recorte (px)','crop_padding'),('Confiança mínima','min_confidence')],6):setting(ocr,row,label,key)
        ttk.Checkbutton(ocr,text='Reler possíveis “1” (I / l / traço estreito)',variable=self.fields['retry_one']).grid(row=9,column=0,columnspan=2,sticky='w',pady=(8,2))
        ttk.Checkbutton(ocr,text='Reler todos os demais ambíguos',variable=self.fields['retry_ambiguous']).grid(row=10,column=0,columnspan=2,sticky='w',pady=3)
        ttk.Label(ocr,text='Releitura: binário + margem + 2×. O “1” dirigido exige escore ≥ 0,80. O texto original é preservado; os pontos continuam pendentes de revisão.',wraplength=310).grid(row=11,column=0,columnspan=2,sticky='w',pady=8)
        self.ocr_button=ttk.Button(ocr,text='Executar etapa 2',command=lambda:self.run_stage('ocr'))
        self.ocr_button.grid(row=12,column=0,columnspan=2,sticky='ew',pady=8)
        for row,(label,key,values) in enumerate([
            ('Modo','grouping',['relative','fixed']),('Distância X','tol_x',None),('Tolerância Y','tol_y',None),
            ('Razão altura decimal','decimal_height_ratio',None),('Queda decimal','decimal_drop',None),
            ('Inteiro máximo p/ decimal','decimal_max_integer',None),('Confiança mínima','min_confidence',None)]):setting(group,row,label,key,values)
        self.group_button=ttk.Button(group,text='Executar etapa 3 / reagrupar',command=lambda:self.run_stage('group'))
        self.group_button.grid(row=8,column=0,columnspan=2,sticky='ew',pady=10)
        ttk.Label(group,text='Alterar só o agrupamento reutiliza o OCR válido. Reagrupar cria outra revisão; salve o projeto antes de substituir decisões.',wraplength=310).grid(row=9,column=0,columnspan=2,pady=10,sticky='w')
        ttk.Label(export,text='Pasta de saída').grid(row=0,column=0,columnspan=2,sticky='w')
        ttk.Entry(export,textvariable=self.output).grid(row=1,column=0,columnspan=2,sticky='ew',pady=5)
        ttk.Button(export,text='Selecionar saída',command=lambda:self.output.set(filedialog.askdirectory() or self.output.get())).grid(row=2,column=0,columnspan=2,sticky='ew')
        ttk.Label(export,text='CRS de saída').grid(row=3,column=0,sticky='w',pady=12)
        ttk.Entry(export,textvariable=self.target_crs).grid(row=3,column=1,sticky='ew')
        self.export_button=ttk.Button(export,text='Exportar candidatos',command=lambda:self.export(False))
        self.export_button.grid(row=4,column=0,columnspan=2,sticky='ew',pady=5)
        self.reviewed_button=ttk.Button(export,text='Exportar somente aprovados',command=lambda:self.export(True))
        self.reviewed_button.grid(row=5,column=0,columnspan=2,sticky='ew',pady=5)
        ttk.Button(export,text='Salvar projeto de revisão',command=self.save_project).grid(row=6,column=0,columnspan=2,sticky='ew',pady=10)
        ttk.Button(export,text='Abrir projeto de revisão',command=self.open_project).grid(row=7,column=0,columnspan=2,sticky='ew')
        ttk.Label(export,text='XYZ: X Y profundidade. Padrão EPSG:4326 (longitude, latitude). Z em metros, positivo para baixo. Sem conversão de datum vertical.',wraplength=310).grid(row=8,column=0,columnspan=2,sticky='w',pady=15)
        self.run_button=ttk.Button(left,text='Executar etapas pendentes (1 → 3)',command=lambda:self.run_stage('all'))
        self.run_button.pack(fill='x',pady=8)
        self.cancel_button=ttk.Button(left,text='Cancelar entre lotes / etapas',command=self.cancel.set,state='disabled');self.cancel_button.pack(fill='x')
        self.progress=ttk.Progressbar(left,mode='determinate');self.progress.pack(fill='x',pady=6)
        ttk.Label(left,textvariable=self.counts,wraplength=335).pack(fill='x',pady=5)
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
        for key,label,cmd in [('accepted','Aprovar seleção',lambda:self.review_action('accepted')),('rejected','Excluir seleção',lambda:self.review_action('rejected')),
                              ('unreviewed','Pendente',lambda:self.review_action('unreviewed')),('edit','Editar valor',self.correct_depth),('focus','Ampliar ponto',self.focus_selected)]:
            button=ttk.Button(bar,text=label,command=cmd);button.pack(side='left',padx=2,pady=3)
            self.review_buttons[key]=button
        select=ttk.Frame(bottom);select.pack(fill='x')
        for label,cmd in [('Selecionar todos',self.select_all_points),('Limpar seleção',self.clear_point_selection),('Inverter seleção',self.invert_point_selection)]:
            ttk.Button(select,text=label,command=cmd).pack(side='left',padx=2,pady=3)
        ttk.Checkbutton(select,text='Acompanhar ponto / zoom',variable=self.follow_review,command=lambda:self.focus_selected() if self.follow_review.get() else None).pack(side='left',padx=8)
        self.tree=ttk.Treeview(bottom,columns=['id','depth','confidence','status','origin'],show='headings',selectmode='extended',height=7)
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
        help_label=ttk.Label(bottom,text='Setas: navegar · Shift+setas: faixa · Ctrl+clique: alternar · Ctrl+A: aprovar · Ctrl+X: excluir · Ctrl+E: editar · Ctrl+Shift+A: todos · Esc: limpar',wraplength=1000)
        help_label.pack(fill='x',padx=4,pady=3)
        help_label.bind('<Configure>',lambda e:help_label.configure(wraplength=max(100,e.width-8)))
        notes=ttk.Frame(bottom);notes.pack(fill='x')
        ttk.Label(notes,text='Nota da revisão:').pack(side='left',padx=4)
        self.note_entry=ttk.Entry(notes,textvariable=self.review_note)
        self.note_entry.pack(side='left',fill='x',expand=True,padx=4,pady=3)
        ttk.Label(self.root,textvariable=self.status,wraplength=1400,padding=8).pack(fill='x')

    def config(self):
        defaults=asdict(Config());data={}
        integers={'threshold','blur_size','kernel_size','min_w','max_w','min_h','max_h','ocr_batch_size','crop_padding'}
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

    def refresh_validity(self):
        if not hasattr(self,'seg_button'):return
        seg=digits=groups=False
        try:
            cfg=self.config()
            if self.session:
                seg=self.session.valid_segments(cfg,self.roi)
                digits=self.session.valid_digits(cfg,self.model_spec(),self.roi)
                groups=self.session.valid_groups(cfg,self.model_spec(),self.roi)
            self.validity.set(f"Segmentação: {'atualizada' if seg else 'pendente'} | OCR: {'atualizado' if digits else 'pendente'} | Agrupamento: {'atualizado' if groups else 'pendente'}")
        except (ValueError,TypeError) as exc:self.validity.set(str(exc))
        for button,enabled in [(self.seg_button,self.session is not None),(self.ocr_button,seg),
                               (self.group_button,digits),(self.run_button,self.session is not None),
                               (self.export_button,groups),(self.reviewed_button,groups and self.session.review.counts['accepted']>0)]:
            button.configure(state='normal' if enabled and not self.busy else 'disabled')
        self.refresh_review_controls()

    def start(self,task,done=lambda result:None,cancellable=True):
        if self.busy:return
        self.busy=True;self.cancel.clear();self.refresh_validity()
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
                            callback(value);self.status.set('Concluído. Confira as etapas e revise os pontos antes do XYZ final.')
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
        if not self.busy:self.model_dir.set(filedialog.askdirectory() or self.model_dir.get())

    def set_roi(self,roi):
        if self.busy:return
        self.roi=roi;self.viewer.roi=roi
        self.roi_text.set(f'Área em pixels: {roi}' if roi else 'Área: carta inteira')
        self.refresh_validity();self.viewer.render()

    def run_stage(self,stage):
        if self.busy or self.session is None:return
        try:cfg=self.config();spec=self.model_spec()
        except ValueError as exc:messagebox.showerror('Parâmetros',str(exc));return
        if not self.confirm_replace():return
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
        self.counts.set(f"Caixas: {len(session.boxes or [])} | Dígitos: {sum(d.text is not None for d in session.digits or [])}\nPendentes: {counts.get('unreviewed',0)} | Aprovados: {counts.get('accepted',0)} | Excluídos: {counts.get('rejected',0)}\n"+', '.join(f'{timing_names[k]}: {v:.3f}s' for k,v in session.timings.items()))
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
            enabled=ready and (selected==1 if key=='edit' else bool(self.tree.focus()) if key=='focus' else selected>0)
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

    def canvas_action(self,action,xy):
        if self.busy:return
        if action=='roi':self.set_roi(xy);return
        if action in {'Inserir ponto','Mover selecionado'}:
            if not self.review_ready():return
            if action=='Inserir ponto':
                value=simpledialog.askfloat('Sondagem ausente','Profundidade em metros, até uma casa decimal:',parent=self.root)
                if value is None:return
                try:point_id=self.session.review.add_manual(*xy,value)
                except ValueError as exc:messagebox.showerror('Profundidade',str(exc));return
            else:
                if len(self.tree.selection())!=1:return
                point_id=self.tree.selection()[0];self.session.review.change(point_id,'reposition',xy=xy,note=self.review_note.get())
            self.review_dirty=True;self.refresh_points()
            if self.tree.exists(str(point_id)):self.tree.selection_set(str(point_id));self.tree.see(str(point_id))
            self.refresh_validity();self.viewer.render();return
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
            self._closed=True;self.root.after_cancel(self._poll_id);self.root.destroy()


def main():
    root=tk.Tk();Application(root);root.mainloop()


if __name__=='__main__':main()
