"""Modern VetorizaFB 5.0 shell around the existing fully functional Qt workbench.

The original Qt Window owns the processing, review and tool callbacks.
This class only reorganizes its widgets and styles without replacing them.
"""
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSplitter, QStackedWidget, QVBoxLayout, QWidget, QTabWidget
)
from .qt_gui import Window as FunctionalWindow


ICONS = Path(__file__).resolve().parents[2] / "assets" / "icons"
STAGES = (
    ("Preparar", "tab-prepare", "Segmentação e dimensões"),
    ("Reconhecer", "tab-recognize", "Leitura OCR"),
    ("Agrupar", "tab-group", "Composição das sondagens"),
    ("Exportar", "tab-export", "Dados georreferenciados"),
)


def icon(name):
    path = ICONS / (name + ".svg")
    return QIcon(str(path)) if path.exists() else QIcon()


class ModernWindow(FunctionalWindow):
    def __init__(self):
        super().__init__()
        self._install_shell()
        self._theme()
        self.setWindowTitle("VetorizaFB 5.0  |  Processamento e revisão batimétrica")
        self.resize(1560, 940)
        self.setMinimumSize(1100, 720)

    def _install_shell(self):
        old_root = self.centralWidget()
        old_layout = old_root.layout()
        old_top = old_layout.itemAt(0).layout()
        original_split = old_layout.itemAt(1).widget()
        progress = self.progress

        # Keep every original button and its signal connections.
        top_widgets = []
        for index in range(old_top.count()):
            obj = old_top.itemAt(index).widget()
            if obj:
                top_widgets.append(obj)
        for widget in top_widgets:
            old_top.removeWidget(widget)
            widget.setParent(None)
        old_layout.removeWidget(original_split)
        original_split.setParent(None)
        old_layout.removeWidget(progress)
        progress.setParent(None)

        former_tabs = original_split.widget(0)
        former_work = original_split.widget(1)
        original_split.setParent(None)

        # Extract, rather than recreate, the stage pages; all original fields
        # and their processing callbacks remain attached to those same widgets.
        pages = []
        while former_tabs.count():
            page = former_tabs.widget(0)
            former_tabs.removeTab(0)
            page.setParent(None)
            pages.append(page)
        former_tabs.hide()

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        brand = QFrame()
        brand.setObjectName("brand")
        bh = QHBoxLayout(brand)
        bh.setContentsMargins(22, 9, 22, 9)
        brand_icon = QLabel("◈")
        brand_icon.setObjectName("brandIcon")
        bh.addWidget(brand_icon)
        brand_name = QLabel("VetorizaFB")
        brand_name.setObjectName("brandName")
        bh.addWidget(brand_name)
        version = QLabel("5.0")
        version.setObjectName("version")
        bh.addWidget(version)
        bh.addSpacing(14)
        caption = QLabel("CARTAS NÁUTICAS  /  FOLHAS DE BORDO")
        caption.setObjectName("brandCaption")
        bh.addWidget(caption)
        bh.addStretch(1)
        brand_status = QLabel("PROCESSAMENTO BATIMÉTRICO")
        brand_status.setObjectName("brandCaption")
        bh.addWidget(brand_status)
        layout.addWidget(brand)

        commands = QFrame()
        commands.setObjectName("commands")
        line = QHBoxLayout(commands)
        line.setContentsMargins(15, 8, 15, 8)
        line.setSpacing(7)
        self.path.setMinimumWidth(180)
        self.path.setMaximumWidth(340)
        self.path.setToolTip("Caminho da carta ou folha de bordo")
        line.addWidget(self.path)
        for widget in top_widgets:
            if widget is self.path or isinstance(widget, QLabel):
                continue
            widget.setIconSize(QSize(18, 18))
            line.addWidget(widget)
        line.addStretch()
        self.save_header = QLabel("ETAPAS  ·  PROCESSAR  ·  REVISAR")
        self.save_header.setObjectName("toolbarCaption")
        line.addWidget(self.save_header)
        layout.addWidget(commands)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setObjectName("body")
        body.setChildrenCollapsible(False)
        body.setHandleWidth(4)

        side = QFrame()
        side.setObjectName("sidebar")
        nav = QVBoxLayout(side)
        nav.setContentsMargins(9, 18, 9, 10)
        nav.setSpacing(6)
        heading = QLabel("FLUXO DE TRABALHO")
        heading.setObjectName("sidebarLabel")
        nav.addWidget(heading)
        self.stage_navigation = []
        for number, (name, ico, subtitle) in enumerate(STAGES):
            b = QPushButton("  " + name)
            b.setObjectName("stageNavigation")
            b.setCheckable(True)
            b.setIcon(icon(ico))
            b.setIconSize(QSize(21, 21))
            b.setToolTip(subtitle)
            b.clicked.connect(lambda checked=False, i=number: self.select_stage(i))
            nav.addWidget(b)
            self.stage_navigation.append(b)
        nav.addStretch()
        summary = QLabel("SELEÇÃO E PROCESSAMENTO\nVetorizaFB 5.0")
        summary.setObjectName("sidebarFoot")
        nav.addWidget(summary)
        side.setFixedWidth(170)
        body.addWidget(side)

        self.properties_stack = QStackedWidget()
        self.properties_stack.setObjectName("properties")
        self.properties_stack.setMinimumWidth(290)
        self.properties_stack.setMaximumWidth(415)
        for number, page in enumerate(pages):
            pane = QWidget()
            pv = QVBoxLayout(pane)
            pv.setContentsMargins(0, 0, 0, 0)
            pv.setSpacing(0)
            top = QFrame()
            top.setObjectName("propertiesHeader")
            ph = QVBoxLayout(top)
            ph.setContentsMargins(18, 19, 18, 15)
            title = QLabel(STAGES[number][0])
            title.setObjectName("propertiesTitle")
            ph.addWidget(title)
            sub = QLabel(STAGES[number][2])
            sub.setObjectName("propertiesSubtitle")
            ph.addWidget(sub)
            pv.addWidget(top)
            scroller = QScrollArea()
            scroller.setObjectName("propertiesScroll")
            scroller.setWidgetResizable(True)
            scroller.setFrameShape(QFrame.Shape.NoFrame)
            scroller.setWidget(page)
            pv.addWidget(scroller)
            self.properties_stack.addWidget(pane)
        body.addWidget(self.properties_stack)

        # The original canvas, layer switcher, review table, toolbar and
        # all their actions stay inside the original vertical work splitter.
        former_work.setParent(None)
        body.addWidget(former_work)
        body.setSizes([170, 340, 1050])
        former_work.setSizes([640, 250])
        self.work_splitter = former_work
        self._review_widget = former_work.widget(1)

        # Native chart zoom/pan without cluttering the large map canvas.
        self.canvas.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.canvas.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        layout.addWidget(body, 1)
        layout.addWidget(progress)
        # Qt processing methods still call self.tabs.setEnabled(...).
        # Preserve the original tabs object under the new root, hidden.
        former_tabs.setParent(root)
        former_tabs.hide()
        self.setCentralWidget(root)
        self._unused_tabs = former_tabs

        # A compact review toggle sits in the chart's existing toolbar.
        chart_widget = former_work.widget(0)
        chart_tools = chart_widget.layout().itemAt(0).layout()
        self.review_toggle = QPushButton("Ocultar revisão")
        self.review_toggle.setObjectName("reviewToggle")
        self.review_toggle.clicked.connect(self.toggle_review)
        chart_tools.addWidget(self.review_toggle)

        self.select_stage(0)
        self._apply_icons()

    def _apply_icons(self):
        replacements = {
            "Abrir…": "open-chart",
            "Abrir projeto": "open-project",
            "Salvar projeto": "save-project",
            "Ajustar": "whole-chart",
            "Mover": "pan",
            "Selecionar área": "select-rectangle",
            "Gerar sondagens": "process",
            "Prévia de caixas": "preview",
            "Exportar aprovadas": "tab-export",
            "Exportar candidatas": "tab-export",
        }
        for button in self.controls:
            name = replacements.get(button.text())
            if name:
                ico = icon(name)
                if not ico.isNull():
                    button.setIcon(ico)

    def select_stage(self, index):
        self.properties_stack.setCurrentIndex(index)
        for n, b in enumerate(self.stage_navigation):
            b.setChecked(n == index)

    def toggle_review(self):
        target = not self._review_widget.isVisible()
        self._review_widget.setVisible(target)
        self.review_toggle.setText("Ocultar revisão" if target else "Mostrar revisão")

    def _theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #F4F7FA; color: #153B50; font: 12px 'Segoe UI'; }
            QFrame#brand { background: #102D46; min-height: 52px; }
            QFrame#brand QLabel { background: transparent; color: #FFFFFF; }
            QLabel#brandIcon { color: #E7BA4B; font: 25px 'Segoe UI'; }
            QLabel#brandName { color: white; font: 700 22px 'Segoe UI'; }
            QLabel#version { border: 1px solid #56738A; border-radius: 6px; padding: 3px 8px; color: #E7BA4B; font-weight: 700; }
            QLabel#brandCaption { color: #B0C9D8; font: 10px 'Segoe UI'; letter-spacing: 1px; }
            QFrame#commands { background: #FFFFFF; border-bottom: 1px solid #D7E2EA; }
            QLabel#toolbarCaption { color: #718A9B; font: 10px 'Segoe UI'; }
            QPushButton { background: #FFFFFF; border: 1px solid #D4DFE7; border-radius: 7px; padding: 9px 11px; text-align: center; }
            QPushButton:hover { border-color: #9AB5C8; background: #EDF5FA; }
            QPushButton:pressed { background: #DCEAF3; }
            QPushButton:disabled { background: #F0F3F6; color: #9CAEBB; }
            QFrame#sidebar { background: #102D46; }
            QFrame#sidebar QLabel { background: transparent; color: #B0C7D6; }
            QLabel#sidebarLabel { padding: 5px 4px 13px; font-size: 10px; font-weight: 700; }
            QLabel#sidebarFoot { padding: 13px 5px; font-size: 10px; }
            QPushButton#stageNavigation { background: transparent; border: 0; color: #E3EDF3; border-radius: 7px; padding: 15px 9px; text-align: left; font-size: 13px; }
            QPushButton#stageNavigation:hover { background: #1C425E; }
            QPushButton#stageNavigation:checked { background: #28516B; color: white; border-left: 3px solid #E7BA4B; font-weight: 700; }
            QStackedWidget#properties { background: white; }
            QFrame#propertiesHeader { background: white; border-bottom: 1px solid #E4EBF0; }
            QLabel#propertiesTitle { color: #102D46; font: 700 20px 'Segoe UI'; background: white; }
            QLabel#propertiesSubtitle { color: #607B8D; background: white; }
            QScrollArea#propertiesScroll { border: 0; background: #FFFFFF; }
            QScrollArea#propertiesScroll QWidget { background: white; }
            QFormLayout { spacing: 9px; }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: white; border: 1px solid #C8D7E1; border-radius: 6px; padding: 5px 7px; min-height: 25px; }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #21799D; }
            QGraphicsView { background: #E5EDF2; border: 0; }
            QTableWidget { background: white; alternate-background-color: #F5F9FC; selection-background-color: #D8EDF7; selection-color: #153B50; border: 1px solid #D8E2EA; }
            QHeaderView::section { background: #EDF3F7; color: #3B6079; border: 0; border-bottom: 1px solid #D7E2EA; padding: 7px; }
            QSplitter::handle { background: #DCE5EC; }
            QProgressBar { border: 0; background: #E6EDF3; color: #153B50; height: 7px; }
            QProgressBar::chunk { background: #E7BA4B; }
        """)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ModernWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
