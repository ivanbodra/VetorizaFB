"""VetorizaFB 5.0 Qt workbench; delegates chart stages and review to ChartSession."""
from .runtime import configure_gis_runtime
configure_gis_runtime()
import sys
from pathlib import Path
from dataclasses import asdict
from datetime import datetime, timezone
import threading

from PySide6.QtCore import Qt, Signal, QThread, QRectF, QSize
from PySide6.QtGui import QImage, QPixmap, QIcon, QPen, QColor, QPainterPath
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,
    QFormLayout,QSplitter,QTabWidget,QGraphicsView,QGraphicsScene,QFileDialog,
    QPushButton,QComboBox,QSpinBox,QDoubleSpinBox,QLabel,QTableWidget,QTableWidgetItem,
    QMessageBox,QInputDialog,QLineEdit,QCheckBox,QMenu,QDialog,QDialogButtonBox,QProgressBar)
from . import __version__
from .core import Config
from .workflow import ChartSession
from .models import default_model_root, discover_models, download_model, ConnectionSettings, MODEL_NAMES


def icon(name):return QIcon(str(Path(__file__).parent/'assets/icons'/(name+'.svg')))


class Worker(QThread):
    completed=Signal(object)
    failed=Signal(str)
    def __init__(self,fn):super().__init__();self.fn=fn
    def run(self):
        try:self.completed.emit(self.fn())
        except Exception as error:self.failed.emit(str(error))


class Canvas(QGraphicsView):
    selected=Signal(object)
    clicked=Signal(float,float)
    def __init__(self):
        super().__init__();self.setScene(QGraphicsScene(self));self.setDragMode(self.DragMode.ScrollHandDrag)
        self.area_mode=None;self.points=[];self.outline=None;self.base=None
        self.setTransformationAnchor(self.ViewportAnchor.AnchorUnderMouse)
    def show_image(self,rgb):
        self.scene().clear();self.outline=None
        h,w=rgb.shape[:2];data=rgb.copy(order='C')
        image=QImage(data.data,w,h,w*3,QImage.Format.Format_RGB888).copy()
        self.base=self.scene().addPixmap(QPixmap.fromImage(image));self.setSceneRect(QRectF(0,0,w,h));self.fitInView(self.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio)
    def wheelEvent(self,event):self.scale(1.2 if event.angleDelta().y()>0 else 1/1.2,1.2 if event.angleDelta().y()>0 else 1/1.2)
    def position(self,event):
        p=self.mapToScene(event.position().toPoint());r=self.sceneRect()
        return (int(max(0,min(r.width()-1,p.x()))),int(max(0,min(r.height()-1,p.y()))))
    def contextMenuEvent(self,event):
        if not self.area_mode:return super().contextMenuEvent(event)
        menu=QMenu(self)
        for label,mode in [('Retângulo','rectangle'),('Polígono','polygon'),('Laço livre','lasso')]:
            a=menu.addAction(label);a.triggered.connect(lambda checked=False,m=mode:self.choose(m))
        menu.exec(event.globalPos())
    def choose(self,mode):self.cancel();self.area_mode=mode;self.setDragMode(self.DragMode.NoDrag)
    def cancel(self):
        self.points=[]
        if self.outline:self.scene().removeItem(self.outline);self.outline=None
    def draw_outline(self):
        if self.outline:self.scene().removeItem(self.outline)
        path=QPainterPath()
        if self.points:
            path.moveTo(*self.points[0])
            for p in self.points[1:]:path.lineTo(*p)
        self.outline=self.scene().addPath(path,QPen(QColor('#d66b17'),2));self.outline.setZValue(10)
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and self.area_mode and self.base:
            p=self.position(event)
            if self.area_mode=='polygon':self.points.append(p)
            else:self.points=[p]
            self.draw_outline();return
        if event.button()==Qt.MouseButton.LeftButton and self.base:self.clicked.emit(*self.position(event))
        super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if self.area_mode and self.points:
            p=self.position(event)
            if self.area_mode=='rectangle' and event.buttons() & Qt.MouseButton.LeftButton:
                a=self.points[0];self.points=[a,(p[0],a[1]),p,(a[0],p[1]),a];self.draw_outline();return
            if self.area_mode=='lasso' and event.buttons() & Qt.MouseButton.LeftButton:self.points.append(p);self.draw_outline();return
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        if self.area_mode in ('rectangle','lasso') and len(self.points)>=3:
            self.selected.emit(tuple(self.points));return
        super().mouseReleaseEvent(event)
    def mouseDoubleClickEvent(self,event):
        if self.area_mode=='polygon' and len(self.points)>=3:self.selected.emit(tuple(self.points));return
        super().mouseDoubleClickEvent(event)
    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:self.cancel();return
        super().keyPressEvent(event)


class Window(QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle(f'VetorizaFB {__version__}');self.resize(1440,900)
        self.session=None;self.roi=None;self.worker=None;self.dirty=False;self.cancel_event=threading.Event();self.model_root=default_model_root()
        root=QWidget();self.setCentralWidget(root);layout=QVBoxLayout(root)
        top=QHBoxLayout();layout.addLayout(top)
        self.path=QLineEdit();self.path.setPlaceholderText('Carta náutica ou folha de bordo georreferenciada')
        top.addWidget(QLabel('VetorizaFB 5.0'));top.addWidget(self.path,1)
        self.controls=[]
        self.button(top,'Abrir…',self.open_chart,'open-chart');self.button(top,'Abrir projeto',self.open_project,'open-project');self.button(top,'Salvar projeto',self.save_project,'save-project')
        splitter=QSplitter();layout.addWidget(splitter,1)
        self.tabs=QTabWidget();self.tabs.setIconSize(QSize(18,18));self.tabs.setUsesScrollButtons(False);self.tabs.setMinimumWidth(420);self.tabs.setMaximumWidth(460);splitter.addWidget(self.tabs)
        self.fields={}
        prep=self.page('Preparar','tab-prepare');self.mode=QComboBox();self.mode.addItems(['Realce','Bruto','Folha de bordo']);prep.addRow('Modo',self.mode)
        self.spin(prep,'Claridade','threshold',1,255,120)
        self.spin(prep,'Largura mínima (px)','min_w',1,1000,3);self.spin(prep,'Largura máxima (px)','max_w',2,1000,80)
        self.spin(prep,'Altura mínima (px)','min_h',1,1000,10);self.spin(prep,'Altura máxima (px)','max_h',2,1000,100)
        self.spin(prep,'Desfoque','blur_size',1,51,5);self.spin(prep,'Dilatação','kernel_size',1,20,2)
        self.magenta=QCheckBox('Ignorar traços magenta');self.magenta.setChecked(True);prep.addRow(self.magenta)
        self.yellow=QCheckBox('Descartar caixas em fundo amarelo');prep.addRow(self.yellow)
        self.button(prep,'Auto: dimensões',self.auto_size,'measure')
        self.button(prep,'Medir caixa',self.measure,'measure')
        self.button(prep,'Selecionar área',lambda:self.canvas.choose('rectangle'),'select-rectangle')
        self.button(prep,'Carta inteira',self.whole,'whole-chart')
        self.button(prep,'Prévia de caixas',lambda:self.stage('segment'),'preview')
        rec=self.page('Reconhecer','tab-recognize');self.models=QComboBox();rec.addRow('Modelo local',self.models)
        self.button(rec,'Pasta dos modelos…',self.model_folder,'open-project');self.button(rec,'Baixar modelo…',self.download,'process')
        self.spin(rec,'Confiança mínima','min_confidence',0,1,.35,True)
        self.spin(rec,'Margem do recorte (px)','crop_padding',0,100,3)
        self.button(rec,'Ler caixas',lambda:self.stage('ocr'),'process')
        rec.addRow(QLabel('FB: aceita de 1 a 3 algarismos por caixa.'))
        grouping=self.page('Agrupar','tab-group')
        self.spin(grouping,'Distância horizontal (px)','tol_x',1,200,30)
        self.spin(grouping,'Tolerância vertical (px)','tol_y',0,100,6)
        self.spin(grouping,'Altura relativa do decímetro','decimal_height_ratio',.1,1,.72,True)
        self.spin(grouping,'Rebaixamento do decímetro','decimal_drop',0,2,.1,True)
        self.button(grouping,'Agrupar',lambda:self.stage('group'),'tab-group')
        self.button(grouping,'Gerar sondagens',lambda:self.stage('all'),'process')
        self.fb_note=QLabel('FB: associa o inteiro ao algarismo menor abaixo.\nAssociações ambíguas ficam sem sondagem.\nO ponto automático requer conferência.');self.fb_note.setWordWrap(True);grouping.addRow(self.fb_note)
        export=self.page('Exportar','tab-export');self.target=QLineEdit('EPSG:4326');export.addRow('CRS de saída',self.target)
        self.button(export,'Exportar aprovadas',lambda:self.export(True),'approve');self.button(export,'Exportar candidatas',lambda:self.export(False),'tab-export')
        right=QSplitter(Qt.Orientation.Vertical);splitter.addWidget(right);splitter.setStretchFactor(1,1)
        chart=QWidget();cl=QVBoxLayout(chart);tools=QHBoxLayout();cl.addLayout(tools)
        self.button(tools,'Ajustar',lambda:self.canvas.fitInView(self.canvas.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio),'whole-chart')
        self.button(tools,'Mover',self.pan,'pan')
        self.layer=QComboBox();self.layer.addItems(['Original','Caixas','Leituras','Sondagens']);self.layer.currentTextChanged.connect(self.redraw);tools.addWidget(self.layer)
        self.canvas=Canvas();cl.addWidget(self.canvas);right.addWidget(chart)
        self.canvas.selected.connect(self.set_area);self.canvas.clicked.connect(self.canvas_click)
        review=QWidget();rl=QVBoxLayout(review);actions=QHBoxLayout();rl.addLayout(actions)
        self.table_kind=QComboBox();self.table_kind.addItems(['Sondagens','Leituras']);self.table_kind.currentIndexChanged.connect(self.refresh_table);actions.addWidget(self.table_kind)
        self.uncertain=QCheckBox('Somente incertas');self.uncertain.toggled.connect(self.refresh_table);actions.addWidget(self.uncertain)
        self.button(actions,'Corrigir',self.correct,'review');self.button(actions,'Aprovar',lambda:self.decision('accepted'),'approve');self.button(actions,'Rejeitar',lambda:self.decision('rejected'))
        actions2=QHBoxLayout();rl.addLayout(actions2)
        self.button(actions2,'Unir caixas FB',self.merge_boxes);self.button(actions2,'Dividir caixa FB',self.split_box)
        self.button(actions2,'Inserir ponto',self.add_point);self.button(actions2,'Mover ponto',self.move_point);self.button(actions2,'Observação',self.note)
        self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['ID','Leitura / valor','Confiança','Estado','Observações']);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.table.itemSelectionChanged.connect(self.focus_row);rl.addWidget(self.table);right.addWidget(review);right.setSizes([600,230])
        self.progress=QProgressBar();self.progress.setRange(0,0);self.progress.hide();layout.addWidget(self.progress)
        self.mode.currentIndexChanged.connect(self.mode_changed);self.mode_changed();self.refresh_models()
        self.setStyleSheet('QMainWindow,QWidget{background:#f4f7f8;color:#153B50;font-size:12px} QTabBar::tab{padding:5px;font-size:11px} QTabBar::tab:selected,QPushButton:pressed{background:#153B50;color:white} QPushButton{padding:6px;border:1px solid #bdcbd2;border-radius:3px} QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox,QTableWidget{background:white;padding:3px} QGraphicsView{background:#dbe3e7}')
    def page(self,title,name):
        w=QWidget();form=QFormLayout(w);self.tabs.addTab(w,icon(name),title);return form
    def button(self,layout,text,fn,name=None):
        b=QPushButton(text);b.clicked.connect(fn)
        if name:b.setIcon(icon(name))
        if isinstance(layout,QFormLayout):layout.addRow(b)
        else:layout.addWidget(b)
        self.controls.append(b);return b
    def spin(self,form,label,key,lo,hi,value,decimal=False):
        w=QDoubleSpinBox() if decimal else QSpinBox();w.setRange(lo,hi);w.setValue(value)
        if decimal:w.setSingleStep(.05)
        form.addRow(label,w);self.fields[key]=w
    def config(self):
        base=asdict(self.session.config) if self.session else asdict(Config())
        base.update({k:w.value() for k,w in self.fields.items()})
        base.update(dpi=600,segmentation=['legacy','black','fb'][self.mode.currentIndex()],grouping='fb' if self.mode.currentIndex()==2 else 'relative',exclude_magenta=self.magenta.isChecked(),exclude_yellow=self.yellow.isChecked())
        return Config(**base)
    def mode_changed(self):
        fb=self.mode.currentIndex()==2
        for k in ('blur_size','kernel_size'):self.fields[k].setEnabled(self.mode.currentIndex()==0)
        self.fb_note.setVisible(fb)
        self.fields['decimal_height_ratio'].setValue(.72 if fb else .95)
        if fb:self.fields['threshold'].setValue(175);self.yellow.setChecked(False)
    def spec(self):
        item=self.models.currentData()
        if item is None:raise ValueError('Selecione um modelo local. Use Baixar modelo para obter os arquivos.')
        return (item.name,str(item.path),'cpu')
    def error(self,text):QMessageBox.critical(self,'Erro',str(text))
    def launch(self,fn,done):
        if self.worker and self.worker.isRunning():return
        self.progress.show()
        for b in self.controls:b.setEnabled(False)
        self.tabs.setEnabled(False);self.table.setEnabled(False);self.canvas.setEnabled(False)
        self.worker=Worker(fn);self.worker.completed.connect(done);self.worker.failed.connect(self.error);self.worker.finished.connect(self.finished);self.worker.start()
    def finished(self):
        self.progress.hide()
        for b in self.controls:b.setEnabled(True)
        self.tabs.setEnabled(True);self.table.setEnabled(True);self.canvas.setEnabled(True)
    def discard(self):
        if not self.dirty:return True
        answer=QMessageBox.question(self,'Projeto alterado','Salvar o projeto antes de continuar?',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel)
        if answer==QMessageBox.StandardButton.Cancel:return False
        if answer==QMessageBox.StandardButton.Save:return self.save_project()
        return True
    def open_chart(self):
        if not self.discard():return
        path,_=QFileDialog.getOpenFileName(self,'Abrir carta',self.path.text(),'Raster (*.tif *.tiff)')
        if path:self.launch(lambda:ChartSession(path),self.loaded)
    def loaded(self,s):
        self.session=s;self.roi=s.roi;self.path.setText(str(s.path));self.dirty=False
        self.mode.setCurrentIndex(['legacy','black','fb'].index(s.config.segmentation))
        for k,w in self.fields.items():w.setValue(getattr(s.config,k))
        self.magenta.setChecked(s.config.exclude_magenta);self.yellow.setChecked(s.config.exclude_yellow)
        self.canvas.show_image(s.rgb);self.refresh_table();self.redraw()
    def open_project(self):
        if not self.discard():return
        path,_=QFileDialog.getOpenFileName(self,'Abrir projeto','','Projeto (*.json)')
        if path:self.launch(lambda:ChartSession.load_project(path),self.loaded)
    def save_project(self):
        if not self.session:return False
        path,_=QFileDialog.getSaveFileName(self,'Salvar projeto','','Projeto (*.json)')
        if not path:return False
        try:self.session.save_project(path);self.dirty=False;return True
        except Exception as e:self.error(e);return False
    def measure(self):
        self.measuring=True;self.canvas.choose('rectangle');self.statusBar().showMessage('Arraste sobre uma caixa para medir largura e altura.')
    def note(self):
        if not self.session or not self.session.review or self.table_kind.currentIndex()!=0:return
        text,ok=QInputDialog.getText(self,'Observação','Texto para as sondagens selecionadas')
        if ok and text.strip():
            for i in self.ids():self.session.review.change(i,'note',note=text.strip())
            self.dirty=True;self.refresh_table()
    def set_area(self,area):
        if getattr(self,'measuring',False):
            self.measuring=False
            xs,ys=zip(*area);self.statusBar().showMessage(f'Medida: {max(xs)-min(xs)+1} × {max(ys)-min(ys)+1} pixels');self.pan();return
        if self.session:
            try:self.roi=self.session.validate_roi(area);self.statusBar().showMessage('Área definida. Clique direito para escolher retângulo, polígono ou laço.')
            except Exception as e:self.error(e)
    def whole(self):self.roi=None;self.canvas.cancel()
    def pan(self):self.canvas.cancel();self.canvas.area_mode=None;self.canvas.setDragMode(Canvas.DragMode.ScrollHandDrag)
    def stage(self,stage):
        if not self.session:return
        try:
            cfg=self.config();spec=self.spec() if stage!='segment' else None;roi=self.roi;s=self.session
        except Exception as e:self.error(e);return
        if s.review is not None and QMessageBox.question(self,'Reprocessar','Reprocessar substitui as decisões de revisão. Continuar?')!=QMessageBox.StandardButton.Yes:return
        def work():
            if stage in ('segment','all') and not s.valid_segments(cfg,roi):s.segment(cfg,roi)
            if stage in ('ocr','all') and not s.valid_digits(cfg,spec,roi):s.run_ocr(cfg,spec,roi)
            if stage in ('group','all'):s.run_grouping(cfg,spec,roi)
        def done(_):
            self.dirty=True;self.layer.setCurrentText('Caixas' if stage=='segment' else 'Leituras' if stage=='ocr' else 'Sondagens');self.refresh_table();self.redraw();self.statusBar().showMessage('Etapa concluída')
        self.launch(work,done)
    def refresh_models(self):
        self.models.clear()
        for m in discover_models(self.model_root):self.models.addItem(m.name,m)
    def model_folder(self):
        p=QFileDialog.getExistingDirectory(self,'Pasta dos modelos',str(self.model_root))
        if p:self.model_root=Path(p);self.refresh_models()
    def download(self):
        d=QDialog(self);d.setWindowTitle('Baixar modelo');f=QFormLayout(d)
        name=QComboBox();name.addItems(MODEL_NAMES);f.addRow('Modelo',name)
        connection=QComboBox();connection.addItems(['Automática','Direta','Proxy']);f.addRow('Conexão',connection)
        server=QLineEdit();user=QLineEdit();password=QLineEdit();password.setEchoMode(QLineEdit.EchoMode.Password);ca=QLineEdit()
        for label,w in [('Servidor:porta',server),('Usuário',user),('Senha',password),('Certificado CA (opcional)',ca)]:f.addRow(label,w)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(d.accept);buttons.rejected.connect(d.reject);f.addRow(buttons)
        if d.exec()!=QDialog.DialogCode.Accepted:return
        try:c=ConnectionSettings(['system','direct','proxy'][connection.currentIndex()],server.text(),user.text(),password.text(),ca.text());c.validate()
        except Exception as e:self.error(e);return
        model=name.currentText();self.launch(lambda:download_model(model,self.model_root,c),lambda _:self.refresh_models())
    def redraw(self,*_):
        if not self.session or not self.canvas.base:return
        for item in list(self.canvas.scene().items()):
            if item is not self.canvas.base and item is not self.canvas.outline:self.canvas.scene().removeItem(item)
        layer=self.layer.currentText();s=self.session
        if layer in ('Caixas','Leituras'):
            for i,b in enumerate(s.boxes or []):
                self.canvas.scene().addRect(b.x,b.y,b.w,b.h,QPen(QColor('#26895c'),1))
                if layer=='Leituras' and s.digits:
                    t=self.canvas.scene().addText(s.digits[i].raw_text);t.setPos(b.x,b.y-20);t.setDefaultTextColor(Qt.GlobalColor.darkBlue)
        if layer=='Sondagens' and s.review:
            for item in s.review.items:
                p=item['current'];x,y=p['pixel_x'],p['pixel_y'];color='#26895c' if item['status']=='accepted' else '#c44134' if item['status']=='rejected' else '#bc7816'
                self.canvas.scene().addEllipse(x-3,y-3,6,6,QPen(QColor(color),2));t=self.canvas.scene().addText(str(p['depth']));t.setPos(x+3,y);t.setDefaultTextColor(Qt.GlobalColor.darkBlue)
    def refresh_table(self,*_):
        self.table.setRowCount(0)
        if not self.session:return
        s=self.session;reads=self.table_kind.currentIndex()==1
        if reads:
            from .fieldbook import token
            for d in s.digits or []:
                uncertain=(token(d) is None if s.config.segmentation=='fb' else d.text is None) or d.score<s.config.min_confidence
                if s.review and s.config.segmentation=='fb':
                    assigned={i for item in s.review.items for i in item['current']['digit_ids']}
                    uncertain=uncertain or d.index not in assigned
                if self.uncertain.isChecked() and not uncertain:continue
                self.row([d.index,d.raw_text,round(d.score,3),'Incerta' if uncertain else 'Lida',d.method])
        elif s.review:
            for i in s.review.items:
                if self.uncertain.isChecked() and i['status']=='accepted':continue
                p=i['current'];self.row([i['id'],p['depth'],p['confidence'],i['status'],i['note'] or ', '.join(p['flags'])])
    def row(self,values):
        r=self.table.rowCount();self.table.insertRow(r)
        for c,v in enumerate(values):self.table.setItem(r,c,QTableWidgetItem(str(v)))
    def ids(self):return sorted({int(self.table.item(i.row(),0).text()) for i in self.table.selectedIndexes()})
    def focus_row(self):
        ids=self.ids()
        if not ids or not self.session:return
        if self.table_kind.currentIndex()==1:
            b=self.session.digits[ids[0]].box;rect=QRectF(b.x-30,b.y-30,b.w+60,b.h+60)
        else:
            p=self.session.review.item(ids[0])['current'];rect=QRectF(p['pixel_x']-100,p['pixel_y']-80,200,160)
        self.canvas.fitInView(rect,Qt.AspectRatioMode.KeepAspectRatio)
    def correct(self):
        ids=self.ids()
        if len(ids)!=1:return
        s=self.session
        if self.table_kind.currentIndex()==1:
            d=s.digits[ids[0]];text,ok=QInputDialog.getText(self,'Corrigir leitura','Algarismos (vazio = rejeitar)',text=d.raw_text)
            if not ok:return
            import re
            if text and not re.fullmatch(r'[0-9]{1,3}' if s.config.segmentation=='fb' else '[0-9]',text):self.error('Leitura inválida');return
            d.alternatives.append(dict(text=d.raw_text,score=d.confidence,method=d.method,timestamp=datetime.now(timezone.utc).isoformat()))
            d.raw_text=text;d.confidence=1.;d.selected_text=None;d.selected_confidence=None;d.method='manual';s.review=s.group_key=None
        else:
            text,ok=QInputDialog.getText(self,'Corrigir sondagem','Profundidade (m)',text=str(s.review.item(ids[0])['current']['depth']))
            if not ok:return
            try:s.review.change(ids[0],'correct_depth',depth=text.replace(',','.'))
            except Exception as e:self.error(e);return
        self.dirty=True;self.refresh_table();self.redraw()
    def decision(self,action):
        if not self.session or self.table_kind.currentIndex()!=0 or not self.session.review:return
        for i in self.ids():self.session.review.change(i,action)
        self.dirty=True;self.refresh_table();self.redraw()
    def canvas_click(self,x,y):self.last_click=(x,y)
    def add_point(self):
        if not self.session or not self.session.review or not hasattr(self,'last_click'):self.error('Clique na carta e execute o agrupamento antes de inserir.');return
        value,ok=QInputDialog.getDouble(self,'Inserir ponto','Profundidade (m)',0,0,12000,1)
        if ok:self.session.add_point(*self.last_click,value);self.dirty=True;self.refresh_table();self.redraw()
    def move_point(self):
        ids=self.ids()
        if len(ids)!=1 or self.table_kind.currentIndex()!=0 or not hasattr(self,'last_click'):return
        self.session.reposition_point(ids[0],*self.last_click);self.dirty=True;self.refresh_table();self.redraw()
    def alter_boxes(self,split=False):
        if not self.session or self.session.config.segmentation!='fb' or self.table_kind.currentIndex()!=1:return
        from .core import Box
        ids=self.ids();s=self.session
        if not ids or (split and len(ids)!=1):return
        boxes=[s.digits[i].box for i in ids];x=min(b.x for b in boxes);y=min(b.y for b in boxes);right=max(b.x+b.w for b in boxes);bottom=max(b.y+b.h for b in boxes)
        if split:
            axis,ok=QInputDialog.getItem(self,'Dividir caixa','Direção',['Vertical','Horizontal'],0,False)
            if not ok:return
            limit=(right-x if axis=='Vertical' else bottom-y)
            if limit<2:return
            pos,ok=QInputDialog.getInt(self,'Dividir caixa','Posição a partir da borda (px)',limit//2,1,limit-1)
            if not ok:return
            new=[Box(x,y,pos,bottom-y),Box(x+pos,y,right-x-pos,bottom-y)] if axis=='Vertical' else [Box(x,y,right-x,pos),Box(x,y+pos,right-x,bottom-y-pos)]
        else:
            if len(ids)<2:return
            new=[Box(x,y,right-x,bottom-y)]
        # Edited geometry is persisted in boxes; old OCR cannot survive this change.
        s.boxes=[b for i,b in enumerate(s.boxes) if i not in ids]+new
        s.digits=s.review=s.ocr_key=s.group_key=None;self.dirty=True;self.layer.setCurrentText('Caixas');self.refresh_table();self.redraw();self.statusBar().showMessage('Caixas alteradas. Execute Ler caixas novamente.')
    def merge_boxes(self):self.alter_boxes()
    def split_box(self):self.alter_boxes(True)
    def auto_size(self):
        if not self.session:return
        from .auto_bounds import suggest_bounds
        try:
            result=suggest_bounds(self.session.all_boxes or [],1.)
            if result:
                for k,value in zip(('min_w','max_w','min_h','max_h'),result):self.fields[k].setValue(max(1,int(value)))
        except Exception as e:self.error(e)
    def export(self,approved):
        if not self.session:return
        if not self.session.valid_groups(self.config(),self.session.model_spec,self.roi):self.error('Parâmetros mudaram. Gere as sondagens antes de exportar.');return
        path=QFileDialog.getExistingDirectory(self,'Exportar XYZ')
        if path:
            target=self.target.text();self.launch(lambda:self.session.export(path,target_crs=target,accepted_only=approved),lambda _:self.statusBar().showMessage('Exportação concluída'))
    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():self.error('Aguarde a etapa terminar antes de fechar.');event.ignore();return
        if self.discard():event.accept()
        else:event.ignore()


def main():
    app=QApplication.instance() or QApplication(sys.argv);w=Window();w.show();return app.exec()


if __name__=='__main__':sys.exit(main())
