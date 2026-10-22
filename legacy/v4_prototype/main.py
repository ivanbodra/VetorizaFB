# -*- coding: utf-8 -*-
"""
VetorizaFB (HydroVectorizer) v4.0 — main.py

GUI Tkinter com frame lateral + preview central.
Etapa 1 (segmentação) implementada com:
  - Pré-processamento simples (grayscale -> Otsu -> findContours)
  - Filtro por dimensões (min_w, max_w, min_h, max_h)
  - Preview com boxes coloridos (verde/lara/Vermelho)
  - Ferramenta de inspeção de dimensões (Toplevel) com histogramas w/h e estatísticas

Etapas 2 e 3 estão com handlers conectados e stubs prontos para integração
com os módulos `ocr_segmented.py` e `export_utils.py`.

Dependências diretas deste arquivo:
  - Python >= 3.10
  - tkinter, Pillow, numpy, opencv-python
  - (opcional) rasterio para GeoTIFF

Estrutura de pastas esperada:
  - temp/ (será criada automaticamente)

Observação: evitamos usar matplotlib nos histogramas para reduzir dependências.
Os histogramas são renderizados via OpenCV (cv2) e exibidos como imagens no Tkinter.
"""

from __future__ import annotations
import os
import sys
import time
import math
import json
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import numpy as np
import cv2

# rasterio é opcional (para GeoTIFF). Se não existir, seguimos sem geo.
try:
    import rasterio
    from rasterio.transform import Affine
    RASTERIO_OK = True
except Exception:
    rasterio = None
    Affine = None
    RASTERIO_OK = False

# Stubs opcionais para módulos futuros — integração depois
try:
    import ocr_segmented  # esperado: PaddleOCR 3.x encapsulado
except Exception:
    ocr_segmented = None

try:
    import export_utils  # esperado: CSV/XYZ e *_info.txt
except Exception:
    export_utils = None

# ------------------------------ Utilidades básicas ------------------------------

TEMP_DIR = os.path.join(os.path.dirname(__file__), 'temp')
os.makedirs(TEMP_DIR, exist_ok=True)

Color = Tuple[int, int, int]
COLOR_GREEN: Color = (0, 255, 0)
COLOR_ORANGE: Color = (0, 165, 255)
COLOR_RED: Color = (0, 0, 255)

BOX_CLASS_INSIDE = 0   # dentro do intervalo => verde
BOX_CLASS_SMALL = 1    # abaixo do mínimo => laranja
BOX_CLASS_LARGE = 2    # acima do máximo => vermelho

@dataclass
class GeoRef:
    transform: Optional["Affine"]
    crs_wkt: Optional[str]

@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int
    klass: int  # 0=ok, 1=small, 2=large

# ------------------------------ App Principal ------------------------------

class HydroVectorizerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("VetorizaFB v4.0 — HydroVectorizer")
        self.geometry("1280x800")
        self.minsize(1100, 700)

        # Estado
        self.img_path: Optional[str] = None
        self.src_bgr: Optional[np.ndarray] = None  # imagem original BGR (cv2)
        self.gray: Optional[np.ndarray] = None
        self.georef: Optional[GeoRef] = None
        self.boxes_all: List[Box] = []
        self.boxes_valid: List[Box] = []
        self.preview_rgb: Optional[np.ndarray] = None
        self.tk_preview: Optional[ImageTk.PhotoImage] = None
        self.zoom_var = tk.DoubleVar(value=0.75)

        # Parâmetros — Etapa 1
        self.min_w = tk.IntVar(value=6)
        self.max_w = tk.IntVar(value=40)
        self.min_h = tk.IntVar(value=10)
        self.max_h = tk.IntVar(value=60)
        self.save_debug = tk.BooleanVar(value=False)

        # Parâmetros — Etapa 2 (OCR)
        self.pad_crop = tk.IntVar(value=2)
        self.batch_size = tk.IntVar(value=96)
        self.use_batched = tk.BooleanVar(value=True)

        # Parâmetros — Etapa 3 (Agrupamento)
        self.tol_x = tk.IntVar(value=12)
        self.tol_y = tk.IntVar(value=14)
        self.height_ratio_decimal_max = tk.DoubleVar(value=0.95)
        self.min_vertical_drop_decimal = tk.DoubleVar(value=0.10)
        self.max_depth_for_decimal = tk.DoubleVar(value=31.0)
        self.export_geo = tk.BooleanVar(value=True)

        # Widgets principais
        self._build_layout()
        self._build_sidebar()
        self._build_statusbar()

        # Atalhos
        self.bind('<Control-o>', lambda e: self.on_load_image())
        self.bind('<plus>', lambda e: self._zoom(+0.1))
        self.bind('<minus>', lambda e: self._zoom(-0.1))

    # -------------------------- Construção da UI --------------------------
    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)

        # Frame lateral (controles)
        self.sidebar = ttk.Frame(self)
        self.sidebar.grid(row=0, column=0, sticky='nsw')

        # Área de preview central
        self.preview_frame = ttk.Frame(self)
        self.preview_frame.grid(row=0, column=1, sticky='nsew')
        self.preview_frame.rowconfigure(0, weight=1)
        self.preview_frame.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(self.preview_frame, bg="#111111", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')

        # Scrollbars opcionais (se desejar no futuro)
        # vsb = ttk.Scrollbar(self.preview_frame, orient='vertical', command=self.canvas.yview)
        # hsb = ttk.Scrollbar(self.preview_frame, orient='horizontal', command=self.canvas.xview)
        # self.canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

    def _build_statusbar(self) -> None:
        self.statusbar = ttk.Frame(self)
        self.statusbar.grid(row=1, column=0, columnspan=2, sticky='ew')
        self.statusbar.columnconfigure(0, weight=1)
        self.statusbar.columnconfigure(1, weight=0)

        self.status_msg = tk.StringVar(value='Pronto.')
        ttk.Label(self.statusbar, textvariable=self.status_msg).grid(row=0, column=0, sticky='w', padx=8, pady=4)

        self.meta_msg = tk.StringVar(value='—')
        ttk.Label(self.statusbar, textvariable=self.meta_msg).grid(row=0, column=1, sticky='e', padx=8, pady=4)

    def _build_sidebar(self) -> None:
        sb = self.sidebar
        for i in range(0, 80):
            sb.rowconfigure(i, weight=0)
        sb.columnconfigure(0, weight=1)
        pad = dict(padx=10, pady=4)

        # Carregamento
        ttk.Label(sb, text='Carregamento', font=('Segoe UI', 11, 'bold')).grid(row=0, column=0, sticky='w', **pad)
        ttk.Button(sb, text='Carregar imagem (Ctrl+O)', command=self.on_load_image).grid(row=1, column=0, sticky='ew', **pad)

        frm_meta = ttk.Frame(sb)
        frm_meta.grid(row=2, column=0, sticky='ew', **pad)
        frm_meta.columnconfigure(1, weight=1)
        ttk.Label(frm_meta, text='Zoom:').grid(row=0, column=0, sticky='w')
        ttk.Entry(frm_meta, textvariable=self.zoom_var, width=6).grid(row=0, column=1, sticky='w')
        ttk.Button(frm_meta, text='Aplicar', command=self.on_apply_zoom).grid(row=0, column=2, sticky='w', padx=6)

        self.lbl_loaded = ttk.Label(sb, text='(nenhuma imagem)')
        self.lbl_loaded.grid(row=3, column=0, sticky='w', **pad)

        # Etapa 1 — Segmentação
        ttk.Separator(sb).grid(row=10, column=0, sticky='ew', pady=(8, 6))
        ttk.Label(sb, text='Etapa 1 — Segmentação', font=('Segoe UI', 11, 'bold')).grid(row=11, column=0, sticky='w', **pad)

        grid1 = ttk.Frame(sb)
        grid1.grid(row=12, column=0, sticky='ew', **pad)
        for c in range(4):
            grid1.columnconfigure(c, weight=1)
        ttk.Label(grid1, text='min_w').grid(row=0, column=0); ttk.Entry(grid1, textvariable=self.min_w, width=6).grid(row=0, column=1)
        ttk.Label(grid1, text='max_w').grid(row=0, column=2); ttk.Entry(grid1, textvariable=self.max_w, width=6).grid(row=0, column=3)
        ttk.Label(grid1, text='min_h').grid(row=1, column=0); ttk.Entry(grid1, textvariable=self.min_h, width=6).grid(row=1, column=1)
        ttk.Label(grid1, text='max_h').grid(row=1, column=2); ttk.Entry(grid1, textvariable=self.max_h, width=6).grid(row=1, column=3)

        ttk.Button(sb, text='🟡 Executar Etapa 1', command=self.on_run_stage1).grid(row=13, column=0, sticky='ew', **pad)
        self.btn_inspect = ttk.Button(sb, text='📏 Inspecionar dimensões', command=self.on_open_inspector, state='disabled')
        self.btn_inspect.grid(row=14, column=0, sticky='ew', **pad)
        ttk.Checkbutton(sb, text='Salvar depuração (imagem/CSV)', variable=self.save_debug).grid(row=15, column=0, sticky='w', **pad)
        self.stage1_status = tk.StringVar(value='—')
        ttk.Label(sb, textvariable=self.stage1_status).grid(row=16, column=0, sticky='w', **pad)

        # Etapa 2 — OCR
        ttk.Separator(sb).grid(row=20, column=0, sticky='ew', pady=(8, 6))
        ttk.Label(sb, text='Etapa 2 — OCR (PaddleOCR 3.x)', font=('Segoe UI', 11, 'bold')).grid(row=21, column=0, sticky='w', **pad)

        grid2 = ttk.Frame(sb)
        grid2.grid(row=22, column=0, sticky='ew', **pad)
        for c in range(4):
            grid2.columnconfigure(c, weight=1)
        ttk.Label(grid2, text='pad_crop').grid(row=0, column=0); ttk.Entry(grid2, textvariable=self.pad_crop, width=6).grid(row=0, column=1)
        ttk.Label(grid2, text='batch_size').grid(row=0, column=2); ttk.Entry(grid2, textvariable=self.batch_size, width=6).grid(row=0, column=3)
        ttk.Checkbutton(sb, text='Usar batched (recomendado)', variable=self.use_batched).grid(row=23, column=0, sticky='w', **pad)
        ttk.Button(sb, text='🟢 Executar Etapa 2', command=self.on_run_stage2).grid(row=24, column=0, sticky='ew', **pad)
        self.stage2_status = tk.StringVar(value='—')
        ttk.Label(sb, textvariable=self.stage2_status).grid(row=25, column=0, sticky='w', **pad)

        # Etapa 3 — Agrupamento/Exportação
        ttk.Separator(sb).grid(row=30, column=0, sticky='ew', pady=(8, 6))
        ttk.Label(sb, text='Etapa 3 — Agrupamento/Exportação', font=('Segoe UI', 11, 'bold')).grid(row=31, column=0, sticky='w', **pad)

        grid3 = ttk.Frame(sb)
        grid3.grid(row=32, column=0, sticky='ew', **pad)
        for c in range(6):
            grid3.columnconfigure(c, weight=1)
        ttk.Label(grid3, text='tol_x').grid(row=0, column=0); ttk.Entry(grid3, textvariable=self.tol_x, width=6).grid(row=0, column=1)
        ttk.Label(grid3, text='tol_y').grid(row=0, column=2); ttk.Entry(grid3, textvariable=self.tol_y, width=6).grid(row=0, column=3)
        ttk.Label(grid3, text='h_ratio_dec_max').grid(row=1, column=0); ttk.Entry(grid3, textvariable=self.height_ratio_decimal_max, width=6).grid(row=1, column=1)
        ttk.Label(grid3, text='min_drop_dec').grid(row=1, column=2); ttk.Entry(grid3, textvariable=self.min_vertical_drop_decimal, width=6).grid(row=1, column=3)
        ttk.Label(grid3, text='max_depth_dec').grid(row=1, column=4); ttk.Entry(grid3, textvariable=self.max_depth_for_decimal, width=6).grid(row=1, column=5)

        ttk.Checkbutton(sb, text='Exportar em coordenadas geográficas (se disponível)', variable=self.export_geo).grid(row=33, column=0, sticky='w', **pad)
        ttk.Button(sb, text='🔵 Executar Etapa 3', command=self.on_run_stage3).grid(row=34, column=0, sticky='ew', **pad)
        self.stage3_status = tk.StringVar(value='—')
        ttk.Label(sb, textvariable=self.stage3_status).grid(row=35, column=0, sticky='w', **pad)

    # -------------------------- Handlers topo --------------------------
	# Carregar Imagem
    def on_load_image(self) -> None:
        path = filedialog.askopenfilename(
            title='Selecione uma imagem (GeoTIFF/PNG/JPG)',
            filetypes=[('Imagens', '*.tif *.tiff *.png *.jpg *.jpeg'), ('Todos', '*.*')]
        )
        if not path:
            return
        try:
            t0 = time.time()
            src_bgr, gray, georef = self._read_image_any(path)
            self.img_path = path
            self.src_bgr = src_bgr
            self.gray = gray
            self.georef = georef
            self.boxes_all = []
            self.boxes_valid = []
            self._update_preview(self.src_bgr)
            fn = os.path.basename(path)
            h, w = self.src_bgr.shape[:2]
            meta = f"{fn} — {w}x{h}px"
            if georef and georef.crs_wkt:
                meta += " | GeoTIFF"
            self.lbl_loaded.config(text=meta)
            self.meta_msg.set(meta)
            self.status_msg.set(f"Imagem carregada em {time.time()-t0:.2f}s")
        except Exception as exc:
            messagebox.showerror('Erro ao carregar', str(exc))

    def on_apply_zoom(self) -> None:
        if self.src_bgr is None:
            return
        self._update_preview(self.preview_rgb if self.preview_rgb is not None else self.src_bgr)

    def on_run_stage1(self) -> None:
        if self.gray is None:
            messagebox.showwarning('Aviso', 'Carregue uma imagem primeiro.')
            return
        t0 = time.time()
        # pré-processamento leve + OTSU
        blur = cv2.medianBlur(self.gray, 3)
        _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # Inverter para achar blobs escuros (texto) se necessário
        if self._white_ratio(self.gray) < 0.5:
            th = 255 - th
        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes: List[Box] = []
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            boxes.append(Box(x, y, w, h, klass=-1))
        self.boxes_all = boxes

        # filtrar por limites e classificar
        mnw, mxw = self.min_w.get(), self.max_w.get()
        mnh, mxh = self.min_h.get(), self.max_h.get()
        for b in self.boxes_all:
            klass = BOX_CLASS_INSIDE
            if b.w < mnw or b.h < mnh:
                klass = BOX_CLASS_SMALL
            elif b.w > mxw or b.h > mxh:
                klass = BOX_CLASS_LARGE
            b.klass = klass
        self.boxes_valid = [b for b in self.boxes_all if b.klass == BOX_CLASS_INSIDE]

        # Desenhar preview
        preview = self._render_boxes_preview(self.src_bgr, self.boxes_all)
        self._update_preview(preview)

        # Salvar debug se pedido
        if self.save_debug.get():
            out_img = os.path.join(TEMP_DIR, 'temp_etapa1.png')
            cv2.imwrite(out_img, cv2.cvtColor(preview, cv2.COLOR_RGB2BGR))
            dims_csv = os.path.join(TEMP_DIR, 'boxes_dims.csv')
            self._write_boxes_csv(dims_csv, self.boxes_all)

        dt = time.time() - t0
        self.stage1_status.set(f"Caixas detectadas: {len(self.boxes_all)} (válidos: {len(self.boxes_valid)}) | tempo: {dt:.2f}s")
        self.btn_inspect.config(state='normal' if self.boxes_all else 'disabled')
        self.status_msg.set('Etapa 1 concluída.')

    def on_open_inspector(self) -> None:
        if not self.boxes_all:
            return
        InspectorWindow(self)

    def on_run_stage2(self) -> None:
        if self.src_bgr is None or not self.boxes_valid:
            messagebox.showwarning('Aviso', 'Execute a Etapa 1 e garanta que há caixas válidas.')
            return
        t0 = time.time()
        # Integração futura com ocr_segmented
        if ocr_segmented is None:
            self.stage2_status.set('Módulo ocr_segmented não encontrado — implementar/instalar.')
            self.status_msg.set('Etapa 2: stub executado.')
            return
        try:
            # Exemplo de chamada futura (pseudo):
            # reader = ocr_segmented.get_reader()
            # digits_df = ocr_segmented.recognize_digits_batched(self.src_bgr, self.boxes_valid,
            #     pad=self.pad_crop.get(), batch_size=self.batch_size.get(), use_batched=self.use_batched.get())
            # self._last_digits_df = digits_df
            # self.stage2_status.set(f"Lidos: {len(digits_df)} | tempo: {time.time()-t0:.2f}s")
            # self.status_msg.set('Etapa 2 concluída.')
            self.stage2_status.set('OCR integrado futuramente (stub).')
            self.status_msg.set('Etapa 2: stub executado.')
        except Exception as exc:
            messagebox.showerror('Erro na Etapa 2', str(exc))

    def on_run_stage3(self) -> None:
        # Integração futura com agrupamento + export_utils
        t0 = time.time()
        if export_utils is None:
            self.stage3_status.set('Módulo export_utils não encontrado — implementar/instalar.')
            self.status_msg.set('Etapa 3: stub executado.')
            return
        try:
            # Exemplo (pseudo):
            # grouped_df = group_digits_by_position(self._last_digits_df,
            #     tol_x=self.tol_x.get(), tol_y=self.tol_y.get(),
            #     height_ratio_decimal_max=self.height_ratio_decimal_max.get(),
            #     min_vertical_drop_decimal=self.min_vertical_drop_decimal.get(),
            #     max_depth_for_decimal=self.max_depth_for_decimal.get())
            # if self.export_geo.get() and self.georef:
            #     grouped_df = geo_utils.attach_geo(grouped_df, self.georef)
            # out_paths = export_utils.export_all(grouped_df, self.img_path, info_dict={...})
            self.stage3_status.set('Agrupamento/Exportação integrados futuramente (stub).')
            self.status_msg.set('Etapa 3: stub executado.')
        except Exception as exc:
            messagebox.showerror('Erro na Etapa 3', str(exc))

    # -------------------------- Núcleo de imagem --------------------------
    def _read_image_any(self, path: str) -> Tuple[np.ndarray, np.ndarray, Optional[GeoRef]]:
        ext = os.path.splitext(path)[1].lower()
        georef: Optional[GeoRef] = None
        if ext in ('.tif', '.tiff') and RASTERIO_OK:
            with rasterio.open(path) as ds:
                arr = ds.read()  # shape: (bands, H, W)
                # Converter para BGR/RGB
                if arr.ndim == 3 and arr.shape[0] >= 3:
                    # rasterio: bandas no formato (C,H,W). Usamos 0..2 e transpondo para (H,W,C)
                    rgb = np.stack([arr[0], arr[1], arr[2]], axis=2)
                    rgb = _normalize_to_uint8(rgb)
                else:
                    # banda única
                    g = _normalize_to_uint8(arr[0]) if arr.ndim == 3 else _normalize_to_uint8(arr)
                    rgb = cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
                transform = ds.transform
                crs_wkt = str(ds.crs) if ds.crs else None
                georef = GeoRef(transform=transform, crs_wkt=crs_wkt)
        else:
            bgr = cv2.imread(path, cv2.IMREAD_COLOR)
            if bgr is None:
                raise ValueError('Não foi possível abrir a imagem.')
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        return bgr, gray, georef

    def _update_preview(self, img_rgb: np.ndarray) -> None:
        self.preview_rgb = img_rgb.copy()
        zoom = max(self.zoom_var.get(), 0.05)
        h, w = img_rgb.shape[:2]
        new_size = (max(1, int(w * zoom)), max(1, int(h * zoom)))
        disp = cv2.resize(img_rgb, new_size, interpolation=cv2.INTER_NEAREST)
        im = Image.fromarray(disp)
        self.tk_preview = ImageTk.PhotoImage(im)
        self.canvas.delete('all')
        self.canvas.create_image(0, 0, image=self.tk_preview, anchor='nw')
        self.canvas.config(scrollregion=(0, 0, disp.shape[1], disp.shape[0]))

    def _render_boxes_preview(self, src_bgr: np.ndarray, boxes: List[Box]) -> np.ndarray:
        rgb = cv2.cvtColor(src_bgr, cv2.COLOR_BGR2RGB)
        out = rgb.copy()
        for b in boxes:
            color = COLOR_GREEN if b.klass == BOX_CLASS_INSIDE else (COLOR_ORANGE if b.klass == BOX_CLASS_SMALL else COLOR_RED)
            cv2.rectangle(out, (b.x, b.y), (b.x + b.w, b.y + b.h), color, 1)
        return out

    def _write_boxes_csv(self, path: str, boxes: List[Box]) -> None:
        with open(path, 'w', encoding='utf-8') as f:
            f.write('x,y,w,h,class\n')
            for b in boxes:
                f.write(f'{b.x},{b.y},{b.w},{b.h},{b.klass}\n')

    @staticmethod
    def _white_ratio(gray: np.ndarray) -> float:
        # proporção de pixels > 127
        return float((gray > 127).mean())

    def _zoom(self, delta: float) -> None:
        self.zoom_var.set(max(0.05, self.zoom_var.get() + delta))
        self.on_apply_zoom()

# ------------------------------ Inspector Window ------------------------------

class InspectorWindow(tk.Toplevel):
    def __init__(self, app: HydroVectorizerApp):
        super().__init__(app)
        self.app = app
        self.title('Inspeção de dimensões (Etapa 1)')
        self.geometry('900x600')
        self.minsize(800, 560)

        self.w_values = np.array([b.w for b in self.app.boxes_all], dtype=np.int32)
        self.h_values = np.array([b.h for b in self.app.boxes_all], dtype=np.int32)

        self._build_ui()
        self._refresh_stats_and_plots()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)

        # Painel de controles
        ctrl = ttk.Frame(self)
        ctrl.grid(row=0, column=0, sticky='nsw', padx=8, pady=8)
        for i in range(10):
            ctrl.rowconfigure(i, weight=0)
        ctrl.columnconfigure(0, weight=1)

        ttk.Label(ctrl, text='Filtros (px)', font=('Segoe UI', 10, 'bold')).grid(row=0, column=0, sticky='w', pady=(0,6))
        self.var_min_w = tk.IntVar(value=self.app.min_w.get())
        self.var_max_w = tk.IntVar(value=self.app.max_w.get())
        self.var_min_h = tk.IntVar(value=self.app.min_h.get())
        self.var_max_h = tk.IntVar(value=self.app.max_h.get())

        grid = ttk.Frame(ctrl); grid.grid(row=1, column=0, sticky='ew')
        for c in range(4): grid.columnconfigure(c, weight=1)
        ttk.Label(grid, text='min_w').grid(row=0, column=0); ttk.Entry(grid, textvariable=self.var_min_w, width=6).grid(row=0, column=1)
        ttk.Label(grid, text='max_w').grid(row=0, column=2); ttk.Entry(grid, textvariable=self.var_max_w, width=6).grid(row=0, column=3)
        ttk.Label(grid, text='min_h').grid(row=1, column=0); ttk.Entry(grid, textvariable=self.var_min_h, width=6).grid(row=1, column=1)
        ttk.Label(grid, text='max_h').grid(row=1, column=2); ttk.Entry(grid, textvariable=self.var_max_h, width=6).grid(row=1, column=3)

        ttk.Button(ctrl, text='Atualizar preview', command=self._apply_and_refresh).grid(row=2, column=0, sticky='ew', pady=(8,6))
        ttk.Label(ctrl, text='Legenda:', font=('Segoe UI', 10, 'bold')).grid(row=3, column=0, sticky='w', pady=(8,4))
        ttk.Label(ctrl, text='Verde: dentro | Laranja: menor | Vermelho: maior').grid(row=4, column=0, sticky='w')

        self.lbl_stats = ttk.Label(ctrl, text='—', justify='left')
        self.lbl_stats.grid(row=5, column=0, sticky='w', pady=(10,0))

        # Área de plots (histogramas)
        plots = ttk.Frame(self)
        plots.grid(row=0, column=1, sticky='nsew', padx=8, pady=8)
        plots.columnconfigure(0, weight=1)
        plots.rowconfigure(0, weight=1)
        plots.rowconfigure(1, weight=1)

        self.canvas_w = tk.Canvas(plots, bg='#111', height=250)
        self.canvas_h = tk.Canvas(plots, bg='#111', height=250)
        self.canvas_w.grid(row=0, column=0, sticky='nsew', pady=(0,6))
        self.canvas_h.grid(row=1, column=0, sticky='nsew')

        # Rodapé
        footer = ttk.Frame(self)
        footer.grid(row=1, column=0, columnspan=2, sticky='ew', padx=8, pady=8)
        footer.columnconfigure(0, weight=1)
        ttk.Button(footer, text='Aplicar ao app e fechar', command=self._commit_and_close).grid(row=0, column=0, sticky='e')

    def _refresh_stats_and_plots(self) -> None:
        w = self.w_values
        h = self.h_values
        stats_text = self._fmt_stats('w', w) + '\n' + self._fmt_stats('h', h)
        self.lbl_stats.config(text=stats_text)
        self._draw_hist_on_canvas(self.canvas_w, w, title='Histograma de larguras (w)')
        self._draw_hist_on_canvas(self.canvas_h, h, title='Histograma de alturas (h)')

    @staticmethod
    def _fmt_stats(name: str, v: np.ndarray) -> str:
        if v.size == 0:
            return f"{name}: (sem dados)"
        p5 = np.percentile(v, 5)
        p95 = np.percentile(v, 95)
        return (
            f"{name}: min={int(v.min())}  max={int(v.max())}  média={v.mean():.1f}  mediana={np.median(v):.1f}  "
            f"p5={int(p5)}  p95={int(p95)}  n={v.size}"
        )

    def _draw_hist_on_canvas(self, canvas: tk.Canvas, values: np.ndarray, title: str) -> None:
        canvas.delete('all')
        w = canvas.winfo_width() or 800
        h = canvas.winfo_height() or 250
        # fundo
        canvas.create_rectangle(0, 0, w, h, fill='#111', outline='')
        canvas.create_text(10, 14, anchor='w', text=title, fill='#dddddd', font=('Segoe UI', 10, 'bold'))
        if values.size == 0:
            canvas.create_text(w//2, h//2, text='(sem dados)', fill='#888')
            return
        bins = min(64, max(16, int(values.size**0.5)))
        hist, edges = np.histogram(values, bins=bins)
        hist = hist.astype(np.float32)
        if hist.max() > 0:
            hist /= hist.max()
        pad_left, pad_right, pad_top, pad_bottom = 40, 10, 30, 30
        plot_w = w - pad_left - pad_right
        plot_h = h - pad_top - pad_bottom
        if plot_w <= 0 or plot_h <= 0:
            return
        # eixo x (faixas)
        for i in range(bins):
            x0 = pad_left + int(i * (plot_w / bins))
            x1 = pad_left + int((i + 1) * (plot_w / bins)) - 1
            y1 = h - pad_bottom
            y0 = y1 - int(hist[i] * plot_h)
            canvas.create_rectangle(x0, y0, x1, y1, fill='#4ea3ff', outline='')
        # limites atuais
        if 'largura' in title or '(w)' in title:
            mn, mx = self.var_min_w.get(), self.var_max_w.get()
            vmin, vmax = values.min(), values.max()
        else:
            mn, mx = self.var_min_h.get(), self.var_max_h.get()
            vmin, vmax = values.min(), values.max()
        if vmax == vmin:
            vmax = vmin + 1
        def x_from_val(val: float) -> int:
            t = (val - vmin) / (vmax - vmin)
            return pad_left + int(t * plot_w)
        # linhas de limite
        x_mn = x_from_val(mn)
        x_mx = x_from_val(mx)
        y0 = pad_top
        y1 = h - pad_bottom
        canvas.create_line(x_mn, y0, x_mn, y1, fill='#ffcc00', width=2)
        canvas.create_line(x_mx, y0, x_mx, y1, fill='#ff4444', width=2)
        canvas.create_text(x_mn+4, y0+10, anchor='w', text=f"min={mn}", fill='#ffcc00')
        canvas.create_text(x_mx-4, y0+10, anchor='e', text=f"max={mx}", fill='#ff4444')

    def _apply_and_refresh(self) -> None:
        # Atualiza classificação dos boxes no app (sem fechar)
        mnw, mxw = self.var_min_w.get(), self.var_max_w.get()
        mnh, mxh = self.var_min_h.get(), self.var_max_h.get()
        for b in self.app.boxes_all:
            klass = BOX_CLASS_INSIDE
            if b.w < mnw or b.h < mnh:
                klass = BOX_CLASS_SMALL
            elif b.w > mxw or b.h > mxh:
                klass = BOX_CLASS_LARGE
            b.klass = klass
        self.app.boxes_valid = [b for b in self.app.boxes_all if b.klass == BOX_CLASS_INSIDE]
        # redesenhar preview no app
        preview = self.app._render_boxes_preview(self.app.src_bgr, self.app.boxes_all)
        self.app._update_preview(preview)
        # atualizar hist/estatísticas
        self._refresh_stats_and_plots()
        # status
        self.app.stage1_status.set(f"Caixas detectadas: {len(self.app.boxes_all)} (válidos: {len(self.app.boxes_valid)})")
        self.app.status_msg.set('Filtros aplicados (inspector).')

    def _commit_and_close(self) -> None:
        # Copia valores para o app e fecha
        self.app.min_w.set(self.var_min_w.get())
        self.app.max_w.set(self.var_max_w.get())
        self.app.min_h.set(self.var_min_h.get())
        self.app.max_h.set(self.var_max_h.get())
        self.destroy()

# ------------------------------ Helpers ------------------------------

def _normalize_to_uint8(arr: np.ndarray) -> np.ndarray:
    arr = arr.astype(np.float32)
    mn, mx = float(arr.min()), float(arr.max())
    if mx <= mn:
        return np.zeros_like(arr, dtype=np.uint8)
    arr = (arr - mn) / (mx - mn)
    arr = (arr * 255.0).clip(0, 255).astype(np.uint8)
    return arr

# ------------------------------ Main ------------------------------

if __name__ == '__main__':
    app = HydroVectorizerApp()
    app.mainloop()
