"""VetorizaFB 5.0 professional Qt workspace.

Maintains the existing ChartSession processing and review model.
Run with: python -m vetorizafb.qt_workspace
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sys
import traceback

from PySide6.QtCore import Qt, QThread, QObject, Signal, QSize, QPointF
from PySide6.QtGui import QAction, QColor, QFont, QImage, QPixmap, QPen, QBrush, QPainter, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QToolButton, QVBoxLayout,
    QHBoxLayout, QFormLayout, QFrame, QSplitter, QStackedWidget, QScrollArea,
    QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QFileDialog, QMessageBox,
    QProgressBar, QStatusBar, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QLineEdit, QGroupBox, QToolBar, QGraphicsRectItem,
    QGraphicsEllipseItem, QStyle, QMenu
)

from .core import Config
from .workflow import ChartSession
from .qt_preview import ChartCanvas

NAVY = "#102D46"
INK = "#153B50"
GOLD = "#E7BA4B"
MUTED = "#647D90"
BASE = "#F4F7FA"
EDGE = "#D9E3EB"

STAGES = [
    ("Preparar", "Ajuste da imagem e segmentação", "⚙"),
    ("Reconhecer", "Leitura dos caracteres", "◎"),
    ("Agrupar", "Composição das sondagens", "▦"),
    ("Revisar", "Validação dos resultados", "✓"),
    ("Exportar", "Entrega dos dados", "⇩"),
]


class Job(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int, str)

    def __init__(self, task):
        super().__init__()
        self.task = task

    def run(self):
        try:
            self.finished.emit(self.task(self.progress.emit))
        except Exception:
            self.failed.emit(traceback.format_exc())


def field(label, widget, *, hint=None):
    area = QWidget()
    col = QVBoxLayout(area)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(5)
    title = QLabel(label)
    title.setObjectName("fieldLabel")
    col.addWidget(title)
    col.addWidget(widget)
    if hint:
        note = QLabel(hint)
        note.setObjectName("hint")
        note.setWordWrap(True)
        col.addWidget(note)
    return area


class Workspace(QMainWindow):
    def __init__(self):
        super().__init__()
        self.session = None
        self.roi = None
        self.job_thread = None
        self.job_worker = None
        self.active_stage = 0
        self.stage_buttons = []
        self.dirty = False
        self._overlay_items = []
        self._build()
        self._style()
        self._refresh()
        self.setWindowTitle("VetorizaFB 5.0 | Processamento batimétrico")
        self.resize(1540, 940)
        self.setMinimumSize(1100, 700)

    def _button(self, text, slot, icon=None, *, kind=None):
        b = QPushButton(text)
        b.clicked.connect(slot)
        if kind:
            b.setProperty("kind", kind)
        if icon:
            b.setIcon(self.style().standardIcon(icon))
        return b

    def _build(self):
        root = QWidget()
        overall = QVBoxLayout(root)
        overall.setContentsMargins(0, 0, 0, 0)
        overall.setSpacing(0)
        self.setCentralWidget(root)

        header = QFrame()
        header.setObjectName("brandHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(22, 10, 22, 10)
        insignia = QLabel("◈")
        insignia.setObjectName("brandMark")
        h.addWidget(insignia)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        product = QLabel("VetorizaFB")
        product.setObjectName("brandTitle")
        title_box.addWidget(product)
        subtitle = QLabel("VETORIZAÇÃO E REVISÃO BATIMÉTRICA")
        subtitle.setObjectName("brandSubtitle")
        title_box.addWidget(subtitle)
        h.addLayout(title_box)
        version = QLabel("5.0")
        version.setObjectName("version")
        h.addWidget(version)
        h.addStretch()
        self.document_name = QLabel("Nenhuma carta aberta")
        self.document_name.setObjectName("headerFile")
        h.addWidget(self.document_name)
        overall.addWidget(header)

        toolbar = QFrame()
        toolbar.setObjectName("commandBar")
        commands = QHBoxLayout(toolbar)
        commands.setContentsMargins(17, 9, 17, 9)
        commands.setSpacing(7)
        self.open_btn = self._button("Abrir carta", self.open_chart, QStyle.StandardPixmap.SP_DirOpenIcon)
        self.open_project_btn = self._button("Abrir projeto", self.open_project, QStyle.StandardPixmap.SP_DialogOpenButton)
        self.save_btn = self._button("Salvar", self.save_project, QStyle.StandardPixmap.SP_DialogSaveButton)
        for b in (self.open_btn, self.open_project_btn, self.save_btn):
            commands.addWidget(b)
        commands.addWidget(self._separator())
        self.fit_btn = self._button("Ajustar", self.fit_chart)
        commands.addWidget(self.fit_btn)
        self.mode_buttons = {}
        for key, label in [("pan", "Mover"), ("rectangle", "Retângulo"), ("polygon", "Polígono"), ("lasso", "Laço livre")]:
            b = self._button(label, lambda _checked=False, m=key: self.set_tool(m))
            b.setCheckable(True)
            self.mode_buttons[key] = b
            commands.addWidget(b)
        self.mode_buttons["pan"].setChecked(True)
        commands.addStretch()
        self.execute_btn = self._button("Executar etapa", self.execute, kind="primary")
        commands.addWidget(self.execute_btn)
        overall.addWidget(toolbar)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)
        body.setHandleWidth(1)
        overall.addWidget(body, 1)

        navigation = QFrame()
        navigation.setObjectName("navigation")
        nav = QVBoxLayout(navigation)
        nav.setContentsMargins(9, 18, 9, 12)
        nav.setSpacing(5)
        nav_label = QLabel("FLUXO DE TRABALHO")
        nav_label.setObjectName("navLabel")
        nav.addWidget(nav_label)
        for index, (name, description, symbol) in enumerate(STAGES):
            b = QPushButton(f"  {symbol}     {name}")
            b.setObjectName("navItem")
            b.setToolTip(description)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=index: self.show_stage(i))
            nav.addWidget(b)
            self.stage_buttons.append(b)
        nav.addStretch()
        nav.addWidget(self._separator(vertical=False))
        self.nav_summary = QLabel("0 caixas\n0 sondagens")
        self.nav_summary.setObjectName("navSummary")
        nav.addWidget(self.nav_summary)
        navigation.setFixedWidth(194)
        body.addWidget(navigation)

        self.properties = QStackedWidget()
        self.properties.setObjectName("properties")
        self.properties.setMinimumWidth(275)
        self.properties.setMaximumWidth(400)
        self._build_properties()
        body.addWidget(self.properties)

        work = QSplitter(Qt.Orientation.Vertical)
        work.setChildrenCollapsible(False)
        work.setHandleWidth(5)
        self.work = work
        chart_holder = QWidget()
        chart_layout = QVBoxLayout(chart_holder)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(0)
        chart_head = QFrame()
        chart_head.setObjectName("chartHeader")
        ch = QHBoxLayout(chart_head)
        ch.setContentsMargins(16, 8, 14, 8)
        self.chart_title = QLabel("VISUALIZADOR CARTOGRÁFICO")
        self.chart_title.setObjectName("chartTitle")
        ch.addWidget(self.chart_title)
        ch.addStretch()
        self.layer_combo = QComboBox()
        self.layer_combo.addItems(["Carta original", "Caixas detectadas", "Sondagens"])
        self.layer_combo.currentIndexChanged.connect(self.draw_overlay)
        self.layer_combo.setFixedWidth(185)
        ch.addWidget(QLabel("Camada"))
        ch.addWidget(self.layer_combo)
        self.collapse_btn = self._button("Ocultar revisão", self.toggle_review)
        ch.addWidget(self.collapse_btn)
        chart_layout.addWidget(chart_head)
        self.canvas = ChartCanvas()
        self.canvas.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.canvas.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.canvas.area_selected.connect(self.area_selected)
        chart_layout.addWidget(self.canvas, 1)
        work.addWidget(chart_holder)

        review = QFrame()
        review.setObjectName("reviewPanel")
        review_layout = QVBoxLayout(review)
        review_layout.setContentsMargins(14, 10, 14, 10)
        review_head = QHBoxLayout()
        review_head.addWidget(QLabel("RESULTADOS  /  REVISÃO DE SONDAGENS"))
        review_head.addStretch()
        self.count_badge = QLabel("Sem resultados")
        self.count_badge.setObjectName("countBadge")
        review_head.addWidget(self.count_badge)
        review_layout.addLayout(review_head)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "Profundidade (m)", "Confiança", "Estado", "Observações"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self.focus_selected)
        review_layout.addWidget(self.table)
        review_controls = QHBoxLayout()
        for label, action, color in [("Aprovar", "accept", "approve"), ("Rejeitar", "reject", "reject"), ("Restaurar", "reset", None)]:
            b = self._button(label, lambda _=False, a=action: self.review_action(a), kind=color)
            review_controls.addWidget(b)
        review_controls.addStretch()
        self.depth_edit = QLineEdit()
        self.depth_edit.setPlaceholderText("Nova profundidade")
        self.depth_edit.setFixedWidth(155)
        review_controls.addWidget(self.depth_edit)
        review_controls.addWidget(self._button("Corrigir valor", self.correct_depth))
        review_layout.addLayout(review_controls)
        work.addWidget(review)
        work.setSizes([680, 230])
        self.review_panel = review
        body.addWidget(work)
        body.setSizes([194, 324, 1030])
        self.show_stage(0)

        status = QStatusBar()
        self.setStatusBar(status)
        self.status_label = QLabel("Pronto para abrir uma carta.")
        status.addWidget(self.status_label, 1)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(170)
        self.progress.setVisible(False)
        status.addPermanentWidget(self.progress)

        self.set_tool("pan")
        self._shortcuts()

    def _shortcuts(self):
        for sequence, slot in [("Ctrl+O", self.open_chart), ("Ctrl+S", self.save_project), ("Ctrl+Shift+O", self.open_project)]:
            action = QAction(self)
            action.setShortcut(sequence)
            action.triggered.connect(slot)
            self.addAction(action)

    def _separator(self, *, vertical=True):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine if vertical else QFrame.Shape.HLine)
        line.setObjectName("separator")
        return line

    def _panel(self, title, subtitle):
        outer = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(19, 23, 19, 22)
        layout.setSpacing(14)
        heading = QLabel(title)
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)
        descriptor = QLabel(subtitle)
        descriptor.setObjectName("panelDescription")
        descriptor.setWordWrap(True)
        layout.addWidget(descriptor)
        scroll.setWidget(outer)
        return scroll, layout

    def _section(self, layout, text):
        header = QLabel(text.upper())
        header.setObjectName("sectionLabel")
        layout.addSpacing(6)
        layout.addWidget(header)

    def _spin(self, value, minimum=0, maximum=99999, suffix=""):
        box = QSpinBox()
        box.setRange(minimum, maximum)
        box.setValue(value)
        box.setSuffix(suffix)
        return box

    def _build_properties(self):
        pane, form = self._panel("Preparar carta", "Configure a segmentação antes de reconhecer as sondagens.")
        self._section(form, "Origem")
        self.chart_path = QLabel("Nenhuma carta selecionada")
        self.chart_path.setWordWrap(True)
        self.chart_path.setObjectName("hint")
        form.addWidget(self.chart_path)
        self._section(form, "Modo de processamento")
        self.mode = QComboBox()
        self.mode.addItem("Realce", "legacy")
        self.mode.addItem("Bruto", "black")
        self.mode.addItem("Folha de bordo", "fb")
        form.addWidget(self.mode)
        self._section(form, "Dimensões dos caracteres")
        defaults = Config()
        self.sizes = {}
        for key, label in [("min_w", "Largura mínima"), ("max_w", "Largura máxima"), ("min_h", "Altura mínima"), ("max_h", "Altura máxima")]:
            self.sizes[key] = self._spin(getattr(defaults, key), 1, 10000, " px")
            form.addWidget(field(label, self.sizes[key]))
        self._section(form, "Tratamento")
        self.exclude_magenta = QCheckBox("Ignorar traços magenta")
        self.exclude_magenta.setChecked(defaults.exclude_magenta)
        form.addWidget(self.exclude_magenta)
        self.exclude_yellow = QCheckBox("Descartar caixas em terra")
        form.addWidget(self.exclude_yellow)
        self.threshold = self._spin(defaults.threshold, 0, 255)
        form.addWidget(field("Limiar", self.threshold))
        form.addStretch()
        self.properties.addWidget(pane)

        pane, form = self._panel("Reconhecer caracteres", "Leia os dígitos das caixas detectadas com o modelo OCR.")
        self._section(form, "Modelo")
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems(["PP-OCRv6_small_rec"])
        form.addWidget(field("Modelo OCR", self.model))
        self.model_dir = QLineEdit()
        self.model_dir.setPlaceholderText("Pasta local do modelo (opcional)")
        form.addWidget(field("Diretório do modelo", self.model_dir))
        form.addWidget(self._button("Localizar modelo…", self.pick_model))
        self._section(form, "Leitura")
        self.batch_size = self._spin(defaults.ocr_batch_size, 1, 1024)
        form.addWidget(field("Tamanho do lote", self.batch_size))
        self.retry_one = QCheckBox("Reler possíveis dígitos 1")
        self.retry_one.setChecked(True)
        form.addWidget(self.retry_one)
        self.retry_ambiguous = QCheckBox("Reler leituras ambíguas")
        form.addWidget(self.retry_ambiguous)
        form.addStretch()
        self.properties.addWidget(pane)

        pane, form = self._panel("Agrupar sondagens", "Defina os critérios para combinar os caracteres reconhecidos.")
        self._section(form, "Geometria")
        self.grouping = QComboBox()
        self.grouping.addItem("Relativo", "relative")
        self.grouping.addItem("Distância fixa", "fixed")
        self.grouping.addItem("Folha de bordo", "fb")
        form.addWidget(field("Método", self.grouping))
        self.tol_x = self._spin(int(defaults.tol_x), 1, 500)
        self.tol_y = self._spin(int(defaults.tol_y), 0, 500)
        form.addWidget(field("Tolerância horizontal", self.tol_x))
        form.addWidget(field("Tolerância vertical", self.tol_y))
        form.addStretch()
        self.properties.addWidget(pane)

        pane, form = self._panel("Revisar resultados", "Selecione as linhas na tabela para aprovar, rejeitar ou corrigir sondagens.")
        form.addWidget(QLabel("A seleção é sincronizada com a localização da sondagem na carta."))
        form.addWidget(self._button("Mostrar painel de revisão", lambda: self.set_review_visible(True)))
        form.addStretch()
        self.properties.addWidget(pane)

        pane, form = self._panel("Exportar dados", "Exporte o conjunto de sondagens em coordenadas georreferenciadas.")
        self._section(form, "Saída")
        self.target_crs = QLineEdit("EPSG:4326")
        form.addWidget(field("Sistema de referência", self.target_crs))
        self.output_dir = QLineEdit()
        self.output_dir.setPlaceholderText("Diretório de saída")
        form.addWidget(field("Pasta de saída", self.output_dir))
        form.addWidget(self._button("Escolher pasta…", self.pick_output))
        form.addWidget(self._button("Exportar candidatos", lambda: self.export(False), kind="primary"))
        form.addWidget(self._button("Exportar aprovados", lambda: self.export(True)))
        form.addStretch()
        self.properties.addWidget(pane)

    def _style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { font-family: 'Segoe UI'; font-size: 12px; color: #153B50; background: #F4F7FA; }
            QFrame#brandHeader { background: #102D46; min-height: 57px; }
            QFrame#brandHeader QLabel { background: transparent; color: #FFFFFF; }
            QLabel#brandMark { color: #E7BA4B; font-size: 25px; }
            QLabel#brandTitle { color: white; font-size: 22px; font-weight: 700; }
            QLabel#brandSubtitle { color: #A9C2D3; font-size: 9px; letter-spacing: 1px; }
            QLabel#version { color: #E7BA4B; font-size: 12px; font-weight: 700; padding: 4px 9px; border: 1px solid #50718A; border-radius: 7px; }
            QLabel#headerFile { color: #C5D8E6; font-size: 12px; }
            QFrame#commandBar { background: white; border-bottom: 1px solid #D9E3EB; }
            QFrame#commandBar QPushButton { background: transparent; padding: 9px 11px; border: 1px solid transparent; border-radius: 7px; }
            QFrame#commandBar QPushButton:hover { background: #EAF2F7; }
            QFrame#commandBar QPushButton:checked { background: #FFF0C8; border: 1px solid #E7BA4B; }
            QPushButton { padding: 9px 11px; border: 1px solid #D4DFE7; border-radius: 7px; background: white; text-align: center; }
            QPushButton:hover { background: #EAF3F8; border-color: #AFC3D1; }
            QPushButton:disabled { color: #9EACB7; background: #F2F5F7; }
            QPushButton[kind="primary"] { background: #176589; color: white; border: 1px solid #176589; font-weight: 600; }
            QPushButton[kind="primary"]:hover { background: #105373; }
            QPushButton[kind="approve"] { color: #17704D; }
            QPushButton[kind="reject"] { color: #B0474D; }
            QFrame#navigation { background: #102D46; }
            QFrame#navigation QLabel { background: transparent; color: #AEC2D1; }
            QLabel#navLabel { font-size: 10px; font-weight: 700; padding: 4px 5px 13px; }
            QLabel#navSummary { font-size: 12px; padding: 13px 7px; line-height: 1.5; }
            QPushButton#navItem { text-align: left; color: #DAE6EE; background: transparent; border: none; border-radius: 7px; padding: 15px 12px; font-size: 13px; }
            QPushButton#navItem:hover { background: #1C435E; }
            QPushButton#navItem:checked { background: #274A63; color: white; border-left: 3px solid #E7BA4B; font-weight: 700; }
            QStackedWidget#properties, QScrollArea { background: white; border: none; }
            QScrollArea QWidget { background: white; }
            QLabel#panelTitle { color: #102D46; font-size: 20px; font-weight: 700; }
            QLabel#panelDescription { color: #607A8C; font-size: 12px; }
            QLabel#sectionLabel { color: #50738B; font-size: 10px; font-weight: 700; padding: 9px 0 4px; }
            QLabel#fieldLabel { color: #294B60; font-weight: 600; font-size: 11px; }
            QLabel#hint { color: #738A9A; font-size: 11px; }
            QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox { background: white; border: 1px solid #CBD9E3; border-radius: 6px; min-height: 27px; padding: 5px 8px; }
            QComboBox:focus, QLineEdit:focus, QSpinBox:focus { border-color: #28789C; }
            QCheckBox { spacing: 8px; padding: 4px 0; }
            QFrame#chartHeader { background: #F9FBFD; border-bottom: 1px solid #D9E3EB; }
            QLabel#chartTitle { font-size: 11px; font-weight: 700; color: #50738B; }
            QFrame#reviewPanel { background: white; border-top: 1px solid #D9E3EB; }
            QFrame#reviewPanel QLabel { background: white; }
            QLabel#countBadge { color: #176589; font-weight: 600; }
            QTableWidget { background: white; alternate-background-color: #F5F9FC; gridline-color: #E5EBF0; selection-background-color: #D9EAF5; selection-color: #102D46; border: 1px solid #DFE6EC; }
            QHeaderView::section { background: #EFF4F8; color: #486C81; padding: 8px; border: none; border-bottom: 1px solid #D9E3EB; font-weight: 600; }
            QStatusBar { background: #EAF0F5; color: #4C687C; }
            QSplitter::handle { background: #D9E3EB; }
        """)

    def show_stage(self, index):
        self.active_stage = index
        self.properties.setCurrentIndex(index)
        for i, b in enumerate(self.stage_buttons):
            b.setChecked(i == index)
        self.execute_btn.setText(["Preparar imagem", "Reconhecer dígitos", "Agrupar sondagens", "Revisar sondagens", "Exportar dados"][index])
        self._refresh()

    def set_tool(self, mode):
        self.canvas.set_mode(mode)
        for key, button in self.mode_buttons.items():
            button.setChecked(key == mode)

    def toggle_review(self):
        self.set_review_visible(not self.review_panel.isVisible())

    def set_review_visible(self, visible):
        self.review_panel.setVisible(visible)
        self.collapse_btn.setText("Ocultar revisão" if visible else "Mostrar revisão")

    def fit_chart(self):
        if self.canvas.pixmap_item is not None:
            self.canvas.fitInView(self.canvas.image_bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def area_selected(self, pts):
        if self.session is None:
            return
        roi = tuple((int(x), int(y)) for x, y in pts)
        try:
            self.roi = self.session.validate_roi(roi)
            self.status_label.setText(f"Área selecionada: {len(roi)} vértices")
            self._refresh()
        except ValueError as error:
            QMessageBox.warning(self, "Seleção de área", str(error))

    def _task(self, task, on_done, message):
        if self.job_thread is not None:
            return
        self.status_label.setText(message)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.job_thread = QThread(self)
        self.job_worker = Job(task)
        self.job_worker.moveToThread(self.job_thread)
        self.job_thread.started.connect(self.job_worker.run)
        self.job_worker.finished.connect(on_done)
        self.job_worker.failed.connect(lambda detail: QMessageBox.critical(self, "VetorizaFB", detail))
        self.job_worker.progress.connect(self._progress)
        self.job_worker.finished.connect(self.job_thread.quit)
        self.job_worker.failed.connect(self.job_thread.quit)
        self.job_thread.finished.connect(self._task_finished)
        self.job_worker.finished.connect(self.job_worker.deleteLater)
        self.job_worker.failed.connect(self.job_worker.deleteLater)
        self.job_thread.finished.connect(self.job_thread.deleteLater)
        self.execute_btn.setEnabled(False)
        self.job_thread.start()

    def _progress(self, current, total, stage):
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(current)
        self.status_label.setText(f"{stage}: {current}/{total}")

    def _task_finished(self):
        self.job_thread = None
        self.job_worker = None
        self.progress.setVisible(False)
        self.execute_btn.setEnabled(True)
        self._refresh()

    def _install_session(self, session):
        self.session = session
        self.roi = session.roi
        self.document_name.setText(session.path.name)
        self.chart_path.setText(str(session.path))
        rgb = session.rgb
        height, width = rgb.shape[:2]
        img = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format.Format_RGB888).copy()
        pm = QPixmap.fromImage(img)
        self.canvas.scene().clear()
        self.canvas.pixmap_item = self.canvas.scene().addPixmap(pm)
        self.canvas.image_bounds = self.canvas.pixmap_item.boundingRect()
        self.canvas.scene().setSceneRect(self.canvas.image_bounds)
        self.canvas.resetTransform()
        self.fit_chart()
        self._overlay_items = []
        self._load_config(session.config)
        self.draw_overlay()
        self.populate_review()
        self.status_label.setText(f"Carta carregada: {session.path.name}  ·  {width} × {height} px")
        self._refresh()

    def open_chart(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir carta náutica", "", "Cartas e rasters (*.tif *.tiff *.png *.jpg *.jpeg);;Todos os arquivos (*)")
        if path:
            self._task(lambda progress: ChartSession(path), self._install_session, "Abrindo carta e verificando georreferenciamento…")

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir projeto", "", "Projetos (*.json)")
        if path:
            self._task(lambda progress: ChartSession.load_project(path), self._install_session, "Restaurando projeto…")

    def save_project(self):
        if not self.session:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Salvar projeto", f"{self.session.path.stem}.vetorizafb.json", "Projetos (*.json)")
        if path:
            try:
                self.session.save_project(path)
                self.dirty = False
                self.status_label.setText("Projeto salvo.")
            except Exception as error:
                QMessageBox.warning(self, "Salvar projeto", str(error))

    def pick_model(self):
        path = QFileDialog.getExistingDirectory(self, "Diretório do modelo OCR")
        if path:
            self.model_dir.setText(path)

    def pick_output(self):
        path = QFileDialog.getExistingDirectory(self, "Pasta de saída")
        if path:
            self.output_dir.setText(path)

    def _config(self):
        values = asdict(self.session.config if self.session else Config())
        values["segmentation"] = self.mode.currentData()
        values["grouping"] = self.grouping.currentData()
        values["threshold"] = self.threshold.value()
        values["exclude_magenta"] = self.exclude_magenta.isChecked()
        values["exclude_yellow"] = self.exclude_yellow.isChecked()
        values["ocr_batch_size"] = self.batch_size.value()
        values["retry_one"] = self.retry_one.isChecked()
        values["retry_ambiguous"] = self.retry_ambiguous.isChecked()
        values["tol_x"] = float(self.tol_x.value())
        values["tol_y"] = float(self.tol_y.value())
        for name, control in self.sizes.items():
            values[name] = control.value()
        return Config(**values)

    def _load_config(self, cfg):
        self.mode.setCurrentIndex(max(0, self.mode.findData(cfg.segmentation)))
        self.grouping.setCurrentIndex(max(0, self.grouping.findData(cfg.grouping)))
        self.threshold.setValue(cfg.threshold)
        self.exclude_magenta.setChecked(cfg.exclude_magenta)
        self.exclude_yellow.setChecked(cfg.exclude_yellow)
        self.retry_one.setChecked(cfg.retry_one)
        self.retry_ambiguous.setChecked(cfg.retry_ambiguous)
        self.batch_size.setValue(cfg.ocr_batch_size)
        self.tol_x.setValue(int(cfg.tol_x))
        self.tol_y.setValue(int(cfg.tol_y))
        for key, widget in self.sizes.items():
            widget.setValue(getattr(cfg, key))

    def _model_spec(self):
        return (self.model.currentText().strip(), self.model_dir.text().strip() or None, "cpu")

    def execute(self):
        if not self.session:
            return
        if self.active_stage == 3:
            self.set_review_visible(True)
            return
        if self.active_stage == 4:
            self.export(False)
            return
        try:
            cfg = self._config()
            spec = self._model_spec()
        except Exception as error:
            QMessageBox.warning(self, "Parâmetros", str(error))
            return
        stage = self.active_stage
        session, roi = self.session, self.roi

        def task(progress):
            if stage == 0:
                session.segment(cfg, roi)
            elif stage == 1:
                session.run_ocr(cfg, spec, roi, progress=progress)
            elif stage == 2:
                session.run_grouping(cfg, spec, roi)
            return stage

        self._task(task, self._stage_done, ["Preparando a imagem…", "Reconhecendo caracteres…", "Agrupando sondagens…"][stage])

    def _stage_done(self, stage):
        self.layer_combo.setCurrentIndex(1 if stage == 0 else 2)
        self.draw_overlay()
        self.populate_review()
        self.status_label.setText(["Segmentação concluída.", "Reconhecimento concluído.", "Agrupamento concluído."][stage])
        if stage < 2:
            self.show_stage(stage + 1)

    def _refresh(self):
        if not hasattr(self, "execute_btn"):
            return
        ready = self.session is not None
        self.save_btn.setEnabled(ready)
        self.fit_btn.setEnabled(ready)
        self.execute_btn.setEnabled(ready and self.job_thread is None)
        if ready:
            boxes = len(self.session.boxes or [])
            counts = self.session.review.counts if self.session.review else {}
            self.nav_summary.setText(f"{boxes} caixas\n{sum(counts.values())} sondagens\n{counts.get('accepted', 0)} aprovadas")
            self.count_badge.setText(f"{sum(counts.values())} sondagens · {counts.get('unreviewed', 0)} pendentes")
        else:
            self.nav_summary.setText("Nenhuma carta\ncarregada")
            self.count_badge.setText("Sem resultados")

    def draw_overlay(self):
        for item in self._overlay_items:
            if item.scene():
                self.canvas.scene().removeItem(item)
        self._overlay_items = []
        if self.session is None:
            return
        layer = self.layer_combo.currentIndex()
        if layer == 1:
            for b in self.session.boxes or []:
                item = self.canvas.scene().addRect(b.x, b.y, b.w, b.h, QPen(QColor("#D38F19"), 1))
                item.setZValue(3)
                self._overlay_items.append(item)
        elif layer == 2 and self.session.review:
            for item in self.session.review.items:
                p = item["current"]
                color = {"accepted": "#258A67", "rejected": "#BE4B54"}.get(item["status"], "#D38F19")
                marker = self.canvas.scene().addEllipse(p["pixel_x"] - 3, p["pixel_y"] - 3, 6, 6, QPen(QColor(color), 1.2), QBrush(QColor(color)))
                marker.setZValue(3)
                self._overlay_items.append(marker)

    def populate_review(self):
        rows = self.session.review.items if self.session and self.session.review else []
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        names = {"unreviewed": "Pendente", "accepted": "Aprovado", "rejected": "Rejeitado"}
        for i, item in enumerate(rows):
            p = item["current"]
            confidence = p.get("confidence")
            values = [str(item["id"]), f'{p["depth"]:g}', "" if confidence is None else f"{confidence:.2f}", names.get(item["status"], item["status"]), item.get("note", "")]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.ItemDataRole.UserRole, str(item["id"]))
                self.table.setItem(i, col, cell)
        self.table.blockSignals(False)
        self._refresh()

    def focus_selected(self):
        if not self.session or not self.session.review:
            return
        selected = self.table.selectedItems()
        if not selected:
            return
        point_id = selected[0].data(Qt.ItemDataRole.UserRole)
        item = next((it for it in self.session.review.items if str(it["id"]) == point_id), None)
        if item:
            p = item["current"]
            self.canvas.centerOn(p["pixel_x"], p["pixel_y"])

    def _selected_ids(self):
        return list({str(self.table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)) for index in self.table.selectionModel().selectedRows()})

    def review_action(self, action):
        if not self.session or not self.session.review:
            return
        try:
            for point_id in self._selected_ids():
                self.session.review.change(point_id, action)
            self.dirty = True
            self.populate_review()
            self.draw_overlay()
        except Exception as error:
            QMessageBox.warning(self, "Revisão", str(error))

    def correct_depth(self):
        if not self.session or not self.session.review or not self._selected_ids():
            return
        try:
            value = float(self.depth_edit.text().replace(",", "."))
            for point_id in self._selected_ids():
                self.session.review.change(point_id, "correct", depth=value)
            self.dirty = True
            self.populate_review()
            self.draw_overlay()
        except Exception as error:
            QMessageBox.warning(self, "Correção", str(error))

    def export(self, approved):
        if not self.session:
            return
        path = self.output_dir.text().strip()
        if not path:
            path = QFileDialog.getExistingDirectory(self, "Pasta de saída")
            if not path:
                return
            self.output_dir.setText(path)
        session, crs = self.session, self.target_crs.text().strip()
        self._task(lambda progress: session.export(path, target_crs=crs, accepted_only=approved),
                   lambda result: self.status_label.setText(f"Exportação concluída em {path}"),
                   "Exportando sondagens georreferenciadas…")


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    window = Workspace()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
