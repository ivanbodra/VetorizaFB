"""Reusable processing stages, cache invalidation and resumable review projects."""
from dataclasses import asdict
import json
import math
from pathlib import Path
import time
import cv2
import numpy as np

from .core import Box, Config, Digit, check_cancel, group, recognize, segment_details
from .ocr import PaddleRecognizer
from .pipeline import export_results, read_chart, sha256, write_json_atomic
from .review import ReviewSet
from .geospatial import offset_to_pixels
from .area import bounds as area_bounds, is_polygon, polygon_mask, inside

SEGMENT_KEYS = ('reference_dpi','dpi','segmentation','threshold','blur_size','kernel_size',
                'min_w','max_w','min_h','max_h','exclude_yellow','exclude_magenta','yellow_delta','yellow_min_fraction')
GROUP_KEYS = ('reference_dpi','dpi','grouping','tol_x','tol_y','decimal_height_ratio',
              'decimal_drop','decimal_max_integer','min_confidence',
              'fb_decimal_distance','fb_integer_height_ratio','fb_overlap',
              'fb_decimal_top_overlap','fb_decimal_max_gap','fb_decimal_left',
              'fb_ambiguity_margin','fb_small_ratio','fb_keep_small')


def signature(config, keys):
    return tuple(getattr(config, k) for k in keys)


class ChartSession:
    def __init__(self, path, display_size=(1600,1000)):
        self.path = Path(path).resolve()
        self.rgb, self.affine, self.crs, self.dpi = read_chart(self.path)
        if self.crs is None:
            raise ValueError("A carta não possui CRS. Corrija o georreferenciamento antes de extrair.")
        self.input_hash = sha256(self.path)
        from .display import DisplayPyramid
        self.display = DisplayPyramid(self.rgb,display_size)
        self.mask_display = None
        self.config = Config(dpi=self.dpi or 600)
        self.boxes = self.all_boxes = self.digits = self.review = None
        self.excluded_boxes = set()
        self.mask = None
        self.color_rejected=[]
        self.contour_revision=2
        self.roi = None
        self.seg_key = self.ocr_key = self.group_key = None
        self.timings = {}
        self.grouping_diagnostics = {}
        self.model_spec = ('PP-OCRv6_small_rec', None, 'cpu')
        self._engine = None
        self._engine_spec = None

    def validate_roi(self, roi):
        if roi is None:
            return None
        if is_polygon(roi):
            points=tuple(tuple(p) for p in roi)
            if (len(points)<3 or any(type(v) is not int or v<0 for p in points for v in p)
                    or any(x>=self.rgb.shape[1] or y>=self.rgb.shape[0] for x,y in points)
                    or cv2.contourArea(np.asarray(points,dtype=np.float32))<=0):
                raise ValueError('Polígono inválido ou fora da carta')
            return points
        if len(roi)!=4 or any(type(v) is not int for v in roi):
            raise ValueError('Área inválida')
        x,y,w,h = roi
        if any(not isinstance(v,int) for v in roi) or min(x,y)<0 or min(w,h)<1 or x+w>self.rgb.shape[1] or y+h>self.rgb.shape[0]:
            raise ValueError("A área deve estar inteiramente dentro da carta")
        return tuple(roi)

    def expected_seg_key(self, config, roi=None):
        return signature(config, SEGMENT_KEYS), self.validate_roi(roi), self.contour_revision

    def expected_ocr_key(self, config, model_spec):
        return (self.seg_key, tuple(model_spec), config.ocr_batch_size, config.crop_padding,
                config.retry_ambiguous, config.retry_one,
                config.min_confidence if config.retry_ambiguous or config.retry_one else None)

    def valid_segments(self, config, roi=None):
        return self.boxes is not None and self.seg_key == self.expected_seg_key(config,roi)

    def valid_digits(self, config, model_spec, roi=None):
        return self.valid_segments(config,roi) and self.digits is not None and self.ocr_key == self.expected_ocr_key(config,model_spec)

    def valid_groups(self, config, model_spec, roi=None):
        return self.valid_digits(config,model_spec,roi) and self.review is not None and self.group_key == (self.ocr_key,signature(config,GROUP_KEYS))

    def segment(self, config, roi=None, cancel=None):
        roi = self.validate_roi(roi)
        check_cancel(cancel)
        start = time.perf_counter()
        x,y,w,h = area_bounds(roi,self.rgb.shape[1],self.rgb.shape[0])
        mask, all_boxes, boxes, rejected = segment_details(self.rgb[y:y+h,x:x+w],config,return_rejected=True,
                                            area_mask=polygon_mask(roi,(x,y,w,h)))
        check_cancel(cancel)
        self.mask = mask
        from .display import DisplayPyramid
        self.mask_display = DisplayPyramid(mask,self.display.viewport)
        self.all_boxes = [Box(b.x+x,b.y+y,b.w,b.h) for b in all_boxes]
        self.boxes = [Box(b.x+x,b.y+y,b.w,b.h) for b in boxes]
        self.excluded_boxes.clear()
        self.color_rejected=[Box(b.x+x,b.y+y,b.w,b.h) for b in rejected]
        self.roi = roi
        self.contour_revision=2
        self.seg_key = self.expected_seg_key(config,roi)
        self.digits = self.review = self.ocr_key = self.group_key = None
        self.config = Config(**asdict(config))
        self.timings = {'segment':time.perf_counter()-start}

    def run_ocr(self, config, model_spec, roi=None, *, engine=None, progress=None, cancel=None):
        if not self.valid_segments(config,roi):
            raise ValueError("Parâmetros de segmentação mudaram. Execute a etapa 1.")
        check_cancel(cancel)
        start = time.perf_counter()
        if engine is None:
            if self._engine is None or self._engine_spec != tuple(model_spec):
                self._engine = PaddleRecognizer(*model_spec)
                self._engine_spec = tuple(model_spec)
            engine = self._engine
        reader = recognize
        if config.segmentation == "fb":
            from .fieldbook import recognize as reader
        digits = reader(self.rgb,self.boxes,engine,config.ocr_batch_size,config.crop_padding,
                           retry=config.retry_ambiguous,retry_one=config.retry_one,min_confidence=config.min_confidence,
                           progress=progress,cancel=cancel)
        check_cancel(cancel)
        self.digits = digits
        self.model_spec = tuple(model_spec)
        self.ocr_key = self.expected_ocr_key(config,model_spec)
        self.review = self.group_key = None
        self.config = Config(**asdict(config))
        self.timings['ocr'] = time.perf_counter()-start
        self.timings.pop('group',None)

    def run_grouping(self, config, model_spec, roi=None, cancel=None):
        if not self.valid_digits(config,model_spec,roi):
            raise ValueError("Leituras ausentes ou parâmetros OCR mudaram. Execute a etapa 2.")
        check_cancel(cancel)
        start = time.perf_counter()
        diagnostics={}
        if config.grouping=='fb':
            from .fieldbook import group as fb_group
            soundings=fb_group([d for d in self.digits if d.index not in self.excluded_boxes],config,diagnostics=diagnostics)
        else:soundings=group([d for d in self.digits if d.index not in self.excluded_boxes],config)
        review = ReviewSet([s for s in soundings if inside(roi,s.pixel_x,s.pixel_y)])
        check_cancel(cancel)
        self.review = review
        self.grouping_diagnostics = diagnostics
        self.group_key = (self.ocr_key,signature(config,GROUP_KEYS))
        self.config = Config(**asdict(config))
        self.timings['group'] = time.perf_counter()-start

    def exclude_boxes(self, indices):
        if self.boxes is None or any(type(i) is not int or i<0 or i>=len(self.boxes) for i in indices):
            raise ValueError('Seleção de caixas inválida')
        newly=set(indices)-self.excluded_boxes
        if newly:
            self.excluded_boxes.update(newly)
            self.review=self.group_key=None
            self.timings.pop('group',None)
        return len(newly)

    def restore_boxes(self, indices):
        restored=self.excluded_boxes.intersection(indices)
        if restored:
            self.excluded_boxes.difference_update(restored)
            self.review=self.group_key=None
            self.timings.pop('group',None)
        return len(restored)

    def verify_source(self):
        if sha256(self.path) != self.input_hash:
            raise ValueError("A carta foi modificada no disco. Reabra e reprocesse a entrada.")

    def validate_position(self,x,y):
        x,y=float(x),float(y)
        if not all(math.isfinite(v) for v in (x,y)) or not (0<=x<=self.rgb.shape[1] and 0<=y<=self.rgb.shape[0]):
            raise ValueError('A posição deve estar dentro da carta original')
        return x,y

    def reposition_point(self,point_id,x,y,*,note=''):
        if self.review is None:raise ValueError('Execute o agrupamento antes de revisar')
        self.review.change(point_id,'reposition',xy=self.validate_position(x,y),note=note)

    def add_point(self,x,y,depth,*,note=''):
        if self.review is None:raise ValueError('Execute o agrupamento antes de revisar')
        x,y=self.validate_position(x,y)
        return self.review.add_manual(x,y,depth,note=note)

    def preview_offset(self,dx,dy,*,unit='pixels',point_ids=None):
        if self.review is None:raise ValueError('Execute o agrupamento antes de revisar')
        ids=([item['id'] for item in self.review.items] if point_ids is None
             else list(dict.fromkeys(int(i) for i in point_ids)))
        if not ids:raise ValueError('Nenhuma sondagem no conjunto escolhido')
        px,py=offset_to_pixels(dx,dy,self.affine,self.crs,unit)
        for point_id in ids:
            s=self.review.item(point_id)['current']
            self.validate_position(s['pixel_x']+px,s['pixel_y']+py)
        return dict(point_ids=ids,pixel_dx=px,pixel_dy=py,count=len(ids),
                    unit=unit,requested_dx=float(dx),requested_dy=float(dy))

    def offset_points(self,dx,dy,*,unit='pixels',point_ids=None,note=''):
        preview=self.preview_offset(dx,dy,unit=unit,point_ids=point_ids)
        batch_id=self.review.offset(preview['point_ids'],preview['pixel_dx'],preview['pixel_dy'],note=note,
                                    context={k:preview[k] for k in ('unit','requested_dx','requested_dy')})
        return dict(preview,batch_id=batch_id)

    def export(self, output_dir, *, target_crs='EPSG:4326', accepted_only=False):
        if self.review is None:
            raise ValueError("Execute o agrupamento antes de exportar")
        soundings = self.review.soundings(accepted_only=accepted_only)
        if accepted_only and not soundings:
            raise ValueError("Nenhum ponto aprovado. Revise e aprove os pontos antes de exportar.")
        self.verify_source()
        suffix = 'reviewed' if accepted_only else 'candidates'
        return export_results(self.path,output_dir,self.rgb,self.affine,self.crs,
                              self.config,self.model_spec[0],self.boxes,self.digits,soundings,
                              target_crs=target_crs,stem=f'{self.path.stem}.{suffix}',
                              status='accepted points only' if accepted_only else 'unreviewed/accepted candidates; rejected points excluded',
                              extra={'roi':self.roi,'stage_seconds':self.timings,'review_counts':self.review.counts,
                                     'review_history':self.review.items,'color_rejected_boxes':len(self.color_rejected)})

    def save_project(self, path):
        self.verify_source()
        data = {'format':'vetorizafb-project','version':1,'input_path':str(self.path),
                'input_sha256':self.input_hash,'config':asdict(self.config),
                'roi':self.roi,'model_spec':self.model_spec,'timings':self.timings,
                'contour_revision':self.contour_revision,
                'boxes':None if self.boxes is None else [asdict(b) for b in self.boxes],
                'excluded_boxes':sorted(self.excluded_boxes),
                'digits':None if self.digits is None else [asdict(d) for d in self.digits],
                'review':None if self.review is None else self.review.items}
        from . import __version__
        data['application_version'] = __version__
        write_json_atomic(Path(path),data)

    @classmethod
    def load_project(cls, path, input_override=None):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if data.get('format') != 'vetorizafb-project' or data.get('version') != 1:
            raise ValueError("Formato de projeto desconhecido")
        session = cls(input_override or data['input_path'])
        if session.input_hash != data['input_sha256']:
            raise ValueError("O projeto pertence a outra imagem (SHA-256 diferente)")
        # Old projects did not perform the new directed retry. Keep their cached
        # readings and review decisions valid under their original behaviour.
        options=dict(data['config']);options.setdefault('retry_one',False)
        session.config = config = Config(**options)
        session.contour_revision=data.get('contour_revision',1)
        if type(session.contour_revision) is not int or session.contour_revision not in (1,2):
            raise ValueError('Revisão de contornos desconhecida no projeto')
        session.roi = session.validate_roi(tuple(data['roi']) if data['roi'] else None)
        session.model_spec = tuple(data['model_spec'])
        session.timings = data['timings']
        if data['boxes'] is not None:
            session.boxes = [Box(**b) for b in data['boxes']]
            exclusions=data.get('excluded_boxes',[])
            if (not isinstance(exclusions,list) or any(type(i) is not int or i<0 or i>=len(session.boxes) for i in exclusions)):
                raise ValueError('Caixas excluídas inválidas no projeto')
            session.excluded_boxes=set(exclusions)
            for b in session.boxes:
                if min(b.x,b.y)<0 or min(b.w,b.h)<1 or b.x+b.w>session.rgb.shape[1] or b.y+b.h>session.rgb.shape[0]:
                    raise ValueError("Caixa fora da imagem no projeto")
            session.seg_key = session.expected_seg_key(config,session.roi)
            x,y,w,h = area_bounds(session.roi,session.rgb.shape[1],session.rgb.shape[0])
            session.mask,all_boxes,_,rejected=segment_details(session.rgb[y:y+h,x:x+w],config,return_rejected=True,contour_revision=session.contour_revision,
                                              area_mask=polygon_mask(session.roi,(x,y,w,h)))
            session.color_rejected=[Box(b.x+x,b.y+y,b.w,b.h) for b in rejected]
            session.all_boxes = [Box(b.x+x,b.y+y,b.w,b.h) for b in all_boxes]
        if data['digits'] is not None:
            if session.boxes is None:
                raise ValueError("Leituras sem segmentação no projeto")
            session.digits = [Digit(**dict(d,box=Box(**d['box']))) for d in data['digits']]
            if len(session.digits) != len(session.boxes) or any(d.box!=b or d.index!=i for i,(d,b) in enumerate(zip(session.digits,session.boxes))):
                raise ValueError("Leituras não correspondem às caixas do projeto")
            session.ocr_key = session.expected_ocr_key(config,session.model_spec)
        if data['review'] is not None:
            if session.digits is None:
                raise ValueError("Revisão sem leituras no projeto")
            session.review = ReviewSet.from_items(data['review'])
            for item in session.review.items:
                s = item['current']
                if not 0<=s['pixel_x']<=session.rgb.shape[1] or not 0<=s['pixel_y']<=session.rgb.shape[0]:
                    raise ValueError("Ponto fora da imagem no projeto")
            session.group_key = (session.ocr_key,signature(config,GROUP_KEYS))
        if session.mask is not None:
            from .display import DisplayPyramid
            session.mask_display=DisplayPyramid(session.mask,session.display.viewport)
        return session
