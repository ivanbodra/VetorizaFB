"""Render only the visible viewport, retaining original pixel coordinates."""
import math
from functools import lru_cache
from statistics import median
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageDraw, ImageFont, ImageTk
from .ui import Tooltip
from .area import is_polygon, bounds as area_bounds


@lru_cache(maxsize=13)
def label_font(size):
    # Arial is available on Windows; Pillow also resolves DejaVu on Linux.
    for name in ('arial.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow 10.0 compatibility
        return ImageFont.load_default()


def draw_label(draw, image_size, position, text, colour, screen_height, screen_width):
    text = str(text)
    minimum = draw.textbbox((0, 0), text, font=label_font(12))
    if screen_width < minimum[2]-minimum[0]:return
    font = label_font(max(12, min(24, round(screen_height * .25))))
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x, y = position
    x = max(0, min(x, image_size[0] - (right-left)))
    y = max(0, min(y - (bottom-top) - 3, image_size[1] - (bottom-top)))
    draw.text((x-left, y-top), text, font=font, fill=colour)


def integer_height(sounding, digit_map):
    ids = sounding.get('digit_ids', [])
    if sounding.get('interpretation') in {'fb_subscript', 'subscript_decimal'}:
        ids = ids[:-1]
    heights = [digit_map[i].box.h for i in ids if i in digit_map]
    return median(heights) if heights else sounding['bounds'][3]-sounding['bounds'][1]


class ChartViewer(ttk.Frame):
    def __init__(self, parent, on_action):
        super().__init__(parent)
        self.on_action, self.session = on_action, None
        self.roi = self.selected_id = self.photo = self._press = None
        self.selected_ids = set()
        self.selected_box_ids = set()
        self.scale, self.left, self.top = 1., 0., 0.
        self.suspended=False
        self._visible_preview = []
        self.preview_boxes = []
        self.measurement = None
        self._resize_job=None
        self.show_rejected = tk.BooleanVar(value=True)
        self.inspection_text = tk.StringVar()
        self.layer = tk.StringVar(value='Original')
        self.mode = tk.StringVar(value='Inspecionar')
        self.area_shape=tk.StringVar(value='Retângulo')
        self._area_points=[]
        self.zoom_text = tk.StringVar()
        bar = ttk.Frame(self); bar.pack(fill='x')
        for text, cmd in [('Ajustar',self.fit),('100%',lambda:self.zoom_to(1)),
                          ('−',lambda:self.zoom_to(self.scale/1.4)),('+',lambda:self.zoom_to(self.scale*1.4))]:
            button=ttk.Button(bar,text=text,command=cmd,width=3 if text in {'−','+'} else 0)
            button.pack(side='left',padx=2,pady=2)
        ttk.Label(bar,textvariable=self.zoom_text,width=6).pack(side='left')
        layer = self.layer_combo = ttk.Combobox(bar,textvariable=self.layer,state='readonly',width=10,
                             values=['Original','Editada','Caixas'])
        layer.pack(side='left',padx=3); layer.bind('<<ComboboxSelected>>',lambda e:self.render())
        ttk.Combobox(bar,textvariable=self.mode,state='readonly',width=21,
                     values=['Inspecionar','Selecionar área','Selecionar para excluir','Medir caractere','Inserir ponto','Mover selecionado']).pack(side='left',padx=4)
        ttk.Checkbutton(bar,text='Descartadas',variable=self.show_rejected,command=self.render_preview_boxes).pack(side='left',padx=5)
        self.canvas = tk.Canvas(self,bg='#e2eaf0',highlightthickness=0)
        self.mode.trace_add('write',lambda *args:self.canvas.configure(cursor='crosshair' if self.mode.get() in {'Inserir ponto','Mover selecionado','Selecionar área','Selecionar para excluir','Medir caractere'} else ''))
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Motion>',self.hover)
        self.canvas.bind('<Configure>',self.on_resize)
        self.canvas.bind('<ButtonPress-1>',self.press)
        self.canvas.bind('<B1-Motion>',self.drag)
        self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<Double-Button-1>',self.finish_polygon)
        self.canvas.bind('<MouseWheel>',lambda e:self.zoom_to(self.scale*(1.3 if e.delta>0 else 1/1.3),e.x,e.y))
        self.canvas.bind('<Button-4>',lambda e:self.zoom_to(self.scale*1.3,e.x,e.y))
        self.canvas.bind('<Button-5>',lambda e:self.zoom_to(self.scale/1.3,e.x,e.y))

        Tooltip(layer,'Caixas: verde = mantida; cinza = descartada.')

    def render_preview_boxes(self):
        self.canvas.delete('preview','hover')
        self._visible_preview=[]
        if self.session is None or self.layer.get()!='Caixas':return
        cw,ch=max(1,self.canvas.winfo_width()),max(1,self.canvas.winfo_height())
        x1,y1=self.left,self.top;x2,y2=x1+cw/self.scale,y1+ch/self.scale
        excluded={self.session.boxes[i] for i in self.session.excluded_boxes} if self.session.boxes else set()
        for b,reason in self.preview_boxes:
            if b.x+b.w<x1 or b.x>x2 or b.y+b.h<y1 or b.y>y2:continue
            if b in excluded:reason='excluída'
            if reason and not self.show_rejected.get():continue
            self._visible_preview.append((b,reason))
            self.canvas.create_rectangle((b.x-x1)*self.scale,(b.y-y1)*self.scale,
                (b.x+b.w-x1)*self.scale,(b.y+b.h-y1)*self.scale,
                outline='#c4c9ce' if reason else '#008879',width=1,tags='preview')
        for i in self.selected_box_ids:
            if self.session.boxes is None or i>=len(self.session.boxes):continue
            b=self.session.boxes[i]
            self.canvas.create_rectangle((b.x-x1)*self.scale,(b.y-y1)*self.scale,
                (b.x+b.w-x1)*self.scale,(b.y+b.h-y1)*self.scale,
                outline='#005bff',width=2,tags='preview')

    def on_resize(self,event=None):
        if self.session is None:return
        if self._resize_job:self.after_cancel(self._resize_job)
        self._resize_job=self.after(80,self.render_after_resize)

    def render_after_resize(self):
        self._resize_job=None
        self.render()

    def set_session(self,session):
        self.preview_boxes = []; self.measurement = None
        self.session, self.roi, self.selected_id = session,session.roi,None
        self.selected_ids=set()
        self.selected_box_ids=set()
        self.cancel_area()
        self.refresh_layers()
        self.after_idle(self.fit)

    def refresh_layers(self):
        options=['Original','Editada','Caixas']
        if self.session is not None and self.session.digits is not None:options.append('Dígitos')
        if self.session is not None and self.session.review is not None:options.append('Sondagens')
        self.layer_combo.configure(values=options)
        if self.layer.get() not in options:self.layer.set(options[-1])

    def fit(self):
        if self.session is None:return
        h,w = self.session.rgb.shape[:2]
        self.scale = min(max(1,self.canvas.winfo_width())/w,max(1,self.canvas.winfo_height())/h)
        self.left = self.top = 0
        self.render()

    def zoom_to(self,scale,cx=None,cy=None):
        if self.session is None:return
        cx = self.canvas.winfo_width()/2 if cx is None else cx
        cy = self.canvas.winfo_height()/2 if cy is None else cy
        px,py = self.left+cx/self.scale,self.top+cy/self.scale
        self.scale = max(.01,min(20.,scale))
        self.left,self.top = px-cx/self.scale,py-cy/self.scale
        self.render()

    def focus(self,x,y,bounds=None):
        if bounds is None:self.scale=max(2.,self.scale)
        else:
            a,b,c,d=bounds
            # About 80 screen pixels per sounding height, capped for context.
            self.scale=max(.01,min(8.,80/max(10,d-b),
                           max(1,self.canvas.winfo_width())*.65/max(20,c-a),
                           max(1,self.canvas.winfo_height())*.65/max(20,d-b)))
        self.left = x-self.canvas.winfo_width()/self.scale/2
        self.top = y-self.canvas.winfo_height()/self.scale/2
        self.render()

    def pixel(self,x,y):return self.left+x/self.scale,self.top+y/self.scale

    def image_point(self,x,y):
        px,py=self.pixel(x,y)
        h,w=self.session.rgb.shape[:2]
        return (max(0,min(w-1,round(px))),max(0,min(h-1,round(py))))

    def draw_area_draft(self, cursor=None):
        self.canvas.delete('selection')
        if not self._area_points:return
        points=self._area_points+([cursor] if cursor else [])
        screen=[((x-self.left)*self.scale,(y-self.top)*self.scale) for x,y in points]
        for x,y in screen:self.canvas.create_oval(x-2,y-2,x+2,y+2,fill='#00b6dd',outline='',tags='selection')
        if len(screen)>1:self.canvas.create_line(*[v for p in screen for v in p],fill='#00b6dd',width=2,tags='selection')

    def cancel_area(self):
        self._area_points=[];self._press=None;self.canvas.delete('selection')

    def finish_polygon(self,event):
        if self.session is None or self.mode.get() not in {'Selecionar área','Selecionar para excluir'} or self.area_shape.get()!='Polígono':return
        point=self.image_point(event.x,event.y)
        if not self._area_points or self._area_points[-1]!=point:self._area_points.append(point)
        self.commit_area();return 'break'

    def commit_area(self):
        points=tuple(dict.fromkeys(self._area_points))
        if len(points)>=3:
            self.on_action('roi' if self.mode.get()=='Selecionar área' else 'select_area',points)
            self.cancel_area()
        else:self.cancel_area()

    def press(self,event):
        self.canvas.focus_set();self._press = event.x,event.y,self.left,self.top
        if self.session is not None and self.mode.get() in {'Selecionar área','Selecionar para excluir'}:
            shape=self.area_shape.get()
            if shape=='Polígono':
                point=self.image_point(event.x,event.y)
                if not self._area_points or self._area_points[-1]!=point:self._area_points.append(point)
                self.draw_area_draft()
            elif shape=='Laço livre':self._area_points=[self.image_point(event.x,event.y)]

    def drag(self,event):
        if not self._press:return
        x,y,left,top = self._press
        if self.mode.get() in {'Selecionar área','Selecionar para excluir'} and self.area_shape.get()=='Polígono':return
        if self.mode.get() in {'Selecionar área','Selecionar para excluir'} and self.area_shape.get()=='Laço livre':
            point=self.image_point(event.x,event.y)
            if point!=self._area_points[-1]:self._area_points.append(point)
            self.draw_area_draft();return
        if self.mode.get() in {'Selecionar área','Selecionar para excluir','Medir caractere'}:
            self.canvas.delete('selection')
            self.canvas.create_rectangle(x,y,event.x,event.y,outline='#00d5ff',width=2,tags='selection')
        elif self.mode.get() == 'Inspecionar':
            self.left,self.top = left-(event.x-x)/self.scale,top-(event.y-y)/self.scale
            self.render()

    def release(self,event):
        if self.session is None or not self._press:return
        sx,sy,left,top = self._press; self._press = None
        px,py = self.pixel(event.x,event.y)
        h,w = self.session.rgb.shape[:2]
        if self.mode.get() in {'Selecionar área','Selecionar para excluir'} and self.area_shape.get()=='Polígono':return
        if self.mode.get() in {'Selecionar área','Selecionar para excluir'} and self.area_shape.get()=='Laço livre':
            point=self.image_point(event.x,event.y)
            if not self._area_points or self._area_points[-1]!=point:self._area_points.append(point)
            self.commit_area();return
        if self.mode.get() in {'Selecionar área','Selecionar para excluir','Medir caractere'}:
            ax,ay = left+sx/self.scale,top+sy/self.scale
            x1,y1 = max(0,math.floor(min(ax,px))),max(0,math.floor(min(ay,py)))
            x2,y2 = min(w,math.ceil(max(ax,px))),min(h,math.ceil(max(ay,py)))
            self.canvas.delete('selection')
            if self.mode.get()=='Medir caractere' and math.hypot(event.x-sx,event.y-sy)<5:
                candidates=[b for b,_ in self._visible_preview if b.x<=px<=b.x+b.w and b.y<=py<=b.y+b.h]
                if not candidates and self.session.all_boxes:
                    candidates=[b for b in self.session.all_boxes if b.x<=px<=b.x+b.w and b.y<=py<=b.y+b.h]
                if candidates:
                    b=min(candidates,key=lambda b:b.w*b.h)
                    self.measurement=(b.x,b.y,b.x+b.w,b.y+b.h)
                    self.on_action('measure',(b.w,b.h));self.render()
                return
            if x2>x1 and y2>y1:
                if self.mode.get() == 'Medir caractere':
                    self.measurement=(x1,y1,x2,y2);self.on_action('measure',(x2-x1,y2-y1));self.render()
                else:self.on_action('roi' if self.mode.get()=='Selecionar área' else 'select_area',(x1,y1,x2-x1,y2-y1))
        elif math.hypot(event.x-sx,event.y-sy)<5 and 0<=px<w and 0<=py<h:
            action=self.mode.get()
            if action=='Inspecionar':
                if event.state & 4:action='toggle_point'
                elif event.state & 1:action='range_point'
            self.on_action(action,(px,py))

    def hover(self,event):
        if self.mode.get() in {'Selecionar área','Selecionar para excluir'} and self.area_shape.get()=='Polígono' and self._area_points:
            self.draw_area_draft(self.image_point(event.x,event.y));return
        if self.layer.get() != 'Caixas' or self._press:return
        x,y=self.pixel(event.x,event.y)
        matches=[(b,reason) for b,reason in self._visible_preview if b.x<=x<=b.x+b.w and b.y<=y<=b.y+b.h]
        self.canvas.delete('hover')
        if not matches:return
        b,reason=min(matches,key=lambda pair:pair[0].w*pair[0].h)
        self.inspection_text.set(f'{b.w} × {b.h} px — {reason or "aceita pelos filtros"}')
        self.canvas.create_rectangle((b.x-self.left)*self.scale,(b.y-self.top)*self.scale,
            (b.x+b.w-self.left)*self.scale,(b.y+b.h-self.top)*self.scale,outline='#007c91',width=2,tags='hover')

    def render(self):
        if self.session is None or self.suspended:return
        h,w = self.session.rgb.shape[:2]
        cw,ch = max(1,self.canvas.winfo_width()),max(1,self.canvas.winfo_height())
        self.left = max(0,min(self.left,max(0,w-cw/self.scale)))
        self.top = max(0,min(self.top,max(0,h-ch/self.scale)))
        x1,y1 = math.floor(self.left),math.floor(self.top)
        x2,y2 = min(w,math.ceil(self.left+cw/self.scale)),min(h,math.ceil(self.top+ch/self.scale))
        output_size=(max(1,round((x2-x1)*self.scale)),max(1,round((y2-y1)*self.scale)))
        display=getattr(self.session,'display',None)
        edited=self.layer.get() == 'Editada' and self.session.mask is not None
        if edited:
            image=Image.new('RGB',output_size,'#343c42')
        elif display is not None and display.pixels is self.session.rgb:
            image=display.render((x1,y1,x2,y2),self.scale)
        else:
            image=Image.fromarray(self.session.rgb[y1:y2,x1:x2]).resize(output_size,Image.Resampling.BILINEAR)
        if edited:
            rx,ry,rw,rh = area_bounds(self.session.roi,w,h)
            ax,ay,bx,by = max(x1,rx),max(y1,ry),min(x2,rx+rw),min(y2,ry+rh)
            if bx>ax and by>ay:
                display=getattr(self.session,'mask_display',None)
                if display is not None and display.pixels is self.session.mask:
                    patch=display.render((ax-rx,ay-ry,bx-rx,by-ry),self.scale)
                else:
                    patch=Image.fromarray(self.session.mask[ay-ry:by-ry,ax-rx:bx-rx]).resize(
                        (max(1,round((bx-ax)*self.scale)),max(1,round((by-ay)*self.scale))),Image.Resampling.BILINEAR)
                image.paste(patch.convert('RGB'),(round((ax-x1)*self.scale),round((ay-y1)*self.scale)))
        draw = ImageDraw.Draw(image)
        def point(x,y):return ((x-x1)*self.scale,(y-y1)*self.scale)
        def box(bounds,colour,label=None,label_height=None):
            a,b,c,d = bounds
            if c<x1 or a>x2 or d<y1 or b>y2:return
            draw.rectangle((*point(a,b),*point(c,d)),outline=colour,width=1)
            if label is not None:
                draw_label(draw,image.size,point(a,b),label,colour,
                           (d-b if label_height is None else label_height)*self.scale,
                           (c-a)*self.scale)
        layer = self.layer.get()
        if self.measurement:box(self.measurement,'#007c91')
        if layer == 'Dígitos' and self.session.digits is not None:
            digit_map = {d.index:d for d in self.session.digits or []}
            for i,b in enumerate(self.session.boxes or []):
                d = digit_map.get(i)
                from .fieldbook import token
                text=(token(d) if self.session.config.segmentation=='fb' else d.text) if d else None
                if i in self.session.excluded_boxes:continue
                box((b.x,b.y,b.x+b.w,b.y+b.h),'#005bff' if i in self.selected_box_ids else '#ffb020' if text is None else '#00b000',text or '?')
        if layer == 'Sondagens' and self.session.review is not None:
            digit_map = {d.index:d for d in self.session.digits or []}
            for item in self.session.review.items:
                s = item['current']
                colour = {'unreviewed':'#f08000','accepted':'#00a000','rejected':'#df2040'}[item['status']]
                if item['id'] in self.selected_ids:colour = '#0068df'
                if item['id'] == self.selected_id:colour = '#005bff'
                box(s['bounds'],colour,f"{s['depth']:g}",integer_height(s,digit_map))
                px,py = point(s['pixel_x'],s['pixel_y'])
                selected = item['id']==self.selected_id or item['id'] in self.selected_ids
                marker_visible = (s['bounds'][3]-s['bounds'][1])*self.scale >= 20 or selected
                if marker_visible and -20<=px<=cw+20 and -20<=py<=ch+20:
                    draw.ellipse((px-3,py-3,px+3,py+3),outline=colour,width=2)
                    if item['id']==self.selected_id:draw.ellipse((px-7,py-7,px+7,py+7),outline=colour,width=2)
        if self.roi:
            if is_polygon(self.roi):draw.line([point(x,y) for x,y in (*self.roi,self.roi[0])],fill='#0068ff',width=2)
            else:
                x,y,rw,rh = self.roi;box((x,y,x+rw,y+rh),'#0068ff')
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.delete('all')
        self.canvas.create_image((x1-self.left)*self.scale,(y1-self.top)*self.scale,image=self.photo,anchor='nw')
        self.render_preview_boxes()
        self.draw_area_draft()
        self.zoom_text.set(f'{self.scale*100:.0f}%')
