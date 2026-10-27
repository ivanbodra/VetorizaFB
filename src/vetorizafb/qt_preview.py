"""VetorizaFB 5.0 — PySide6 visual prototype.

Run: python -m pip install PySide6
     python -m vetorizafb.qt_preview

The Qt window is a design preview; processing remains in the maintained GUI.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QAction, QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDockWidget, QFileDialog,
    QFrame, QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsScene,
    QGraphicsView, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QSplitter, QStatusBar, QTabWidget, QToolBar,
    QVBoxLayout, QWidget, QFormLayout, QSpinBox, QCheckBox,
)

NAVY = "#102D46"
INK = "#153B50"
GOLD = "#E7BA4B"
PAPER = "#F4F7FA"
LINE = "#D8E2E9"


class ChartCanvas(QGraphicsView):
    area_selected = Signal(object)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#E9F0F4"))
        self.mode = "pan"
        self.points = []
        self.preview = None
        self.pixmap_item = None
        self.image_bounds = QRectF()
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)

    def load_image(self, path):
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            raise ValueError("Não foi possível abrir a imagem.")
        self.scene().clear()
        self.pixmap_item = self.scene().addPixmap(pixmap)
        self.image_bounds = QRectF(0, 0, pixmap.width(), pixmap.height())
        self.scene().setSceneRect(self.image_bounds)
        self.resetTransform()
        self.fitInView(self.image_bounds, Qt.AspectRatioMode.KeepAspectRatio)
        self.points = []
        self.preview = None

    def set_mode(self, mode):
        self.mode = mode
        self.points = []
        self._clear_preview()
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if mode == "pan" else QGraphicsView.DragMode.NoDrag)
        self.setCursor(Qt.CursorShape.OpenHandCursor if mode == "pan" else Qt.CursorShape.CrossCursor)

    def _position(self, event):
        p = self.mapToScene(event.position().toPoint())
        return QPointF(
            max(0, min(p.x(), self.image_bounds.width())),
            max(0, min(p.y(), self.image_bounds.height())),
        )

    def _clear_preview(self):
        if self.preview is not None:
            self.scene().removeItem(self.preview)
            self.preview = None

    def _render_path(self, points, close=False):
        self._clear_preview()
        if not points:
            return
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        if close and len(points) >= 3:
            path.closeSubpath()
        item = QGraphicsPathItem(path)
        item.setPen(QPen(QColor(GOLD), 2, Qt.PenStyle.DashLine))
        item.setBrush(QColor(231, 186, 75, 32) if close else Qt.BrushStyle.NoBrush)
        item.setZValue(10)
        self.scene().addItem(item)
        self.preview = item

    def _commit(self):
        if len(self.points) < 3:
            self.points = []
            self._clear_preview()
            return
        self._render_path(self.points, True)
        self.area_selected.emit([(round(p.x(), 2), round(p.y(), 2)) for p in self.points])
        self.points = []

    def mousePressEvent(self, event):
        if self.pixmap_item is not None and event.button() == Qt.MouseButton.LeftButton and self.mode != "pan":
            p = self._position(event)
            if self.mode == "rectangle":
                self.points = [p, p]
            elif self.mode == "polygon":
                self.points.append(p)
            elif self.mode == "lasso":
                self.points = [p]
            self._render_path(self.points)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.pixmap_item is not None:
            p = self._position(event)
            if self.mode == "rectangle" and len(self.points) == 2:
                a = self.points[0]
                self.points[1] = p
                self._render_path([a, QPointF(p.x(), a.y()), p, QPointF(a.x(), p.y())], True)
            elif self.mode == "lasso" and self.points and event.buttons() & Qt.MouseButton.LeftButton:
                if (p - self.points[-1]).manhattanLength() >= 2:
                    self.points.append(p)
                    self._render_path(self.points)
            elif self.mode == "polygon" and self.points:
                self._render_path(self.points + [p])
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.mode == "rectangle" and len(self.points) == 2:
            a, b = self.points
            if abs(a.x() - b.x()) >= 2 and abs(a.y() - b.y()) >= 2:
                self.points = [a, QPointF(b.x(), a.y()), b, QPointF(a.x(), b.y())]
                self._commit()
            else:
                self.points = []
                self._clear_preview()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.mode == "lasso" and self.points:
            self._commit()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.mode == "polygon" and len(self.points) >= 3:
            self._commit()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.points = []
            self._clear_preview()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        scale = self.transform().m11()
        if 0.05 <= scale * factor <= 25:
            self.scale(factor, factor)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VetorizaFB 5.0 — Design Preview")
        self.resize(1440, 880)
        self.setMinimumSize(1000, 650)
        self.canvas = ChartCanvas()
        self._build()
        self._style()

    def _tool(self, bar, label, callback, *, checkable=False, checked=False, enabled=True):
        action = QAction(label, self)
        action.setCheckable(checkable)
        action.setChecked(checked)
        action.setEnabled(enabled)
        action.triggered.connect(callback)
        bar.addAction(action)
        return action

    def _build(self):
        header = QWidget()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        brand = QLabel("◈  VetorizaFB")
        brand.setObjectName("brand")
        header_layout.addWidget(brand)
        header_layout.addWidget(QLabel("5.0  |  Cartas náuticas e folhas de bordo"))
        header_layout.addStretch()
        header_layout.addWidget(QLabel("CHM  ·  Processamento batimétrico"))
        self.setMenuWidget(header)

        bar = QToolBar("Ferramentas")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.addToolBar(bar)
        self._tool(bar, "Abrir carta", self.open_chart)
        self._tool(bar, "Ajustar carta", self.fit)
        bar.addSeparator()
        self.mode_actions = {}
        for mode, label in [("pan", "Mover"), ("rectangle", "Retângulo"), ("polygon", "Polígono"), ("lasso", "Laço livre")]:
            self.mode_actions[mode] = self._tool(bar, label, lambda checked=False, m=mode: self.choose_mode(m), checkable=True, checked=mode == "pan")
        bar.addSeparator()
        self._tool(bar, "Reconhecer", self.not_integrated, enabled=False)
        self._tool(bar, "Agrupar", self.not_integrated, enabled=False)
        self._tool(bar, "Exportar", self.not_integrated, enabled=False)

        left = QTabWidget()
        left.setObjectName("stages")
        left.setTabPosition(QTabWidget.TabPosition.North)
        for name, page in [
            ("Preparar", self._prepare()),
            ("Reconhecer", self._stage_info("Reconhecimento OCR", "Configuração do modelo e revisão de dígitos.")),
            ("Agrupar", self._stage_info("Agrupamento", "Configuração espacial e interpretação das sondagens.")),
            ("Revisar", self._stage_info("Revisão", "Validação, edição e aprovação de sondagens.")),
            ("Exportar", self._stage_info("Exportação", "Exportação georreferenciada de sondagens aprovadas.")),
        ]:
            left.addTab(page, name)
        left.setMinimumWidth(310)
        left.setMaximumWidth(490)

        central = QSplitter(Qt.Orientation.Horizontal)
        central.addWidget(left)
        work = QSplitter(Qt.Orientation.Vertical)
        work.addWidget(self.canvas)
        review = QWidget()
        review_layout = QVBoxLayout(review)
        review_layout.addWidget(QLabel("RESULTADOS  ·  Sondagens e inspeção"))
        review_layout.addWidget(QLabel("Abra uma carta para iniciar a visualização."))
        work.addWidget(review)
        work.setSizes([660, 145])
        central.addWidget(work)
        central.setSizes([355, 1085])
        self.setCentralWidget(central)

        status = QStatusBar()
        self.setStatusBar(status)
        self.statusBar().showMessage("Pronto · Protótipo visual PySide6 · OCR não conectado")
        self.canvas.area_selected.connect(lambda pts: self.statusBar().showMessage(f"Área delimitada: {len(pts)} vértices em coordenadas de imagem"))

    def _stage_info(self, title, description):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        note = QLabel(description)
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        return panel

    def _prepare(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        title = QLabel("Preparação da imagem")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("Modo de processamento"))
        modes = QComboBox()
        modes.addItems(["Realce", "Bruto", "Folha de bordo"])
        layout.addWidget(modes)
        layout.addSpacing(14)
        layout.addWidget(QLabel("Dimensões dos caracteres"))
        form = QFormLayout()
        for name, value in [("Largura mínima", 8), ("Largura máxima", 42), ("Altura mínima", 9), ("Altura máxima", 48)]:
            field = QSpinBox()
            field.setRange(1, 10000)
            field.setValue(value)
            field.setSuffix(" px")
            form.addRow(name, field)
        layout.addLayout(form)
        layout.addSpacing(12)
        layout.addWidget(QCheckBox("Mostrar caixas detectadas"))
        layout.addWidget(QCheckBox("Ignorar traços magenta"))
        layout.addStretch()
        note = QLabel("Visualização de design. Os controles de processamento serão conectados ao fluxo existente.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        return panel

    def _style(self):
        self.setStyleSheet("""
            QMainWindow { background: #F4F7FA; color: #153B50; }
            QWidget#header { background: #102D46; min-height: 58px; }
            QWidget#header QLabel { color: #CADAE5; font: 12px 'Segoe UI'; }
            QWidget#header QLabel#brand { color: #FFFFFF; font: 700 21px 'Segoe UI'; }
            QToolBar { background: #FFFFFF; border-bottom: 1px solid #D8E2E9; spacing: 8px; padding: 9px; }
            QToolButton { color: #153B50; padding: 9px 11px; border-radius: 7px; font: 12px 'Segoe UI'; }
            QToolButton:hover { background: #E9F1F7; }
            QToolButton:checked { background: #F8E9C3; color: #102D46; }
            QTabWidget#stages::pane { background: #FFFFFF; border: none; }
            QTabBar::tab { background: #E9EFF4; color: #476073; padding: 12px 10px; }
            QTabBar::tab:selected { background: #FFFFFF; color: #102D46; border-bottom: 3px solid #E7BA4B; font-weight: bold; }
            QLabel { color: #153B50; font: 12px 'Segoe UI'; }
            QLabel#sectionTitle { font: 700 17px 'Segoe UI'; margin: 12px 0; }
            QLabel#muted { color: #6B7F8D; }
            QComboBox, QSpinBox { background: #FFFFFF; border: 1px solid #CAD7E0; border-radius: 6px; padding: 7px; min-height: 20px; }
            QSplitter::handle { background: #D8E2E9; }
            QStatusBar { background: #EDF3F7; color: #496273; }
        """)

    def choose_mode(self, mode):
        self.canvas.set_mode(mode)
        for name, action in self.mode_actions.items():
            action.setChecked(name == mode)

    def fit(self):
        if self.canvas.pixmap_item is not None:
            self.canvas.fitInView(self.canvas.image_bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def open_chart(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir carta", "", "Imagens (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if path:
            try:
                self.canvas.load_image(path)
                self.statusBar().showMessage(f"Carta aberta: {Path(path).name}")
            except ValueError as error:
                QMessageBox.warning(self, "Imagem", str(error))

    def not_integrated(self):
        QMessageBox.information(self, "Em desenvolvimento", "Esta ação será integrada ao processamento do VetorizaFB.")


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
