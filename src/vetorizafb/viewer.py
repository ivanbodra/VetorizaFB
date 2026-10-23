"""Render only the visible viewport, retaining original pixel coordinates."""
import math
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk


class ChartViewer(ttk.Frame):
    def __init__(self, parent, on_action):
        super().__init__(parent)
        self.on_action, self.session = on_action, None
        self.roi = self.selected_id = self.photo = self._press = None
        self.selected_ids = set()
        self.scale, self.left, self.top = 1., 0., 0.
        self.suspended=False
        self.layer = tk.StringVar(value='Original')
        self.mode = tk.StringVar(value='Inspecionar')
        self.zoom_text = tk.StringVar()
        bar = ttk.Frame(self); bar.pack(fill='x')
        for text, cmd in [('Ajustar',self.fit),('100%',lambda:self.zoom_to(1)),
                          ('−',lambda:self.zoom_to(self.scale/1.4)),('+',lambda:self.zoom_to(self.scale*1.4))]:
            ttk.Button(bar,text=text,command=cmd,width=7).pack(side='left',padx=2,pady=3)
        ttk.Label(bar,textvariable=self.zoom_text,width=8).pack(side='left')
        layer = ttk.Combobox(bar,textvariable=self.layer,state='readonly',width=12,
                             values=['Original','Máscara','Caixas','Rejeitadas por cor','OCR','Sondagens'])
        layer.pack(side='left',padx=4); layer.bind('<<ComboboxSelected>>',lambda e:self.render())
        ttk.Combobox(bar,textvariable=self.mode,state='readonly',width=18,
                     values=['Inspecionar','Selecionar área','Inserir ponto','Mover selecionado']).pack(side='left',padx=4)
        self.canvas = tk.Canvas(self,bg='#20272d',highlightthickness=0)
        self.mode.trace_add('write',lambda *args:self.canvas.configure(cursor='crosshair' if self.mode.get() in {'Inserir ponto','Mover selecionado','Selecionar área'} else ''))
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda e:self.render())
        self.canvas.bind('<ButtonPress-1>',self.press)
        self.canvas.bind('<B1-Motion>',self.drag)
        self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<MouseWheel>',lambda e:self.zoom_to(self.scale*(1.3 if e.delta>0 else 1/1.3),e.x,e.y))
        self.canvas.bind('<Button-4>',lambda e:self.zoom_to(self.scale*1.3,e.x,e.y))
        self.canvas.bind('<Button-5>',lambda e:self.zoom_to(self.scale/1.3,e.x,e.y))

    def set_session(self,session):
        self.session, self.roi, self.selected_id = session,session.roi,None
        self.selected_ids=set()
        self.after_idle(self.fit)

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

    def press(self,event):
        self.canvas.focus_set();self._press = event.x,event.y,self.left,self.top

    def drag(self,event):
        if not self._press:return
        x,y,left,top = self._press
        if self.mode.get() == 'Selecionar área':
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
        if self.mode.get() == 'Selecionar área':
            ax,ay = left+sx/self.scale,top+sy/self.scale
            x1,y1 = max(0,math.floor(min(ax,px))),max(0,math.floor(min(ay,py)))
            x2,y2 = min(w,math.ceil(max(ax,px))),min(h,math.ceil(max(ay,py)))
            self.canvas.delete('selection')
            if x2>x1 and y2>y1:self.on_action('roi',(x1,y1,x2-x1,y2-y1))
        elif math.hypot(event.x-sx,event.y-sy)<5 and 0<=px<w and 0<=py<h:
            action=self.mode.get()
            if action=='Inspecionar':
                if event.state & 4:action='toggle_point'
                elif event.state & 1:action='range_point'
            self.on_action(action,(px,py))

    def render(self):
        if self.session is None or self.suspended:return
        h,w = self.session.rgb.shape[:2]
        cw,ch = max(1,self.canvas.winfo_width()),max(1,self.canvas.winfo_height())
        self.left = max(0,min(self.left,max(0,w-cw/self.scale)))
        self.top = max(0,min(self.top,max(0,h-ch/self.scale)))
        x1,y1 = math.floor(self.left),math.floor(self.top)
        x2,y2 = min(w,math.ceil(self.left+cw/self.scale)),min(h,math.ceil(self.top+ch/self.scale))
        image = Image.fromarray(self.session.rgb[y1:y2,x1:x2])
        if self.layer.get() == 'Máscara' and self.session.mask is not None:
            rx,ry,rw,rh = self.session.roi or (0,0,w,h)
            image = Image.new('RGB',image.size,'#343c42')
            ax,ay,bx,by = max(x1,rx),max(y1,ry),min(x2,rx+rw),min(y2,ry+rh)
            if bx>ax and by>ay:
                image.paste(Image.fromarray(self.session.mask[ay-ry:by-ry,ax-rx:bx-rx]).convert('RGB'),(ax-x1,ay-y1))
        image = image.resize((max(1,round((x2-x1)*self.scale)),max(1,round((y2-y1)*self.scale))),Image.Resampling.BILINEAR)
        draw = ImageDraw.Draw(image)
        def point(x,y):return ((x-x1)*self.scale,(y-y1)*self.scale)
        def box(bounds,colour,label=None):
            a,b,c,d = bounds
            if c<x1 or a>x2 or d<y1 or b>y2:return
            draw.rectangle((*point(a,b),*point(c,d)),outline=colour,width=1)
            if label is not None and self.scale>=.45:
                draw.text(point(a,max(0,b-12/self.scale)),str(label),fill=colour)
        layer = self.layer.get()
        if layer=='Rejeitadas por cor':
            for b in self.session.color_rejected:box((b.x,b.y,b.x+b.w,b.y+b.h),'#df2040')
        if layer in {'Caixas','OCR'}:
            digit_map = {d.index:d for d in self.session.digits or []}
            for i,b in enumerate(self.session.boxes or []):
                d = digit_map.get(i)
                box((b.x,b.y,b.x+b.w,b.y+b.h),'#ffb020' if d is None or d.text is None else '#00b000',
                    (d.text or '?') if layer == 'OCR' and d is not None else None)
        if layer == 'Sondagens' and self.session.review is not None:
            for item in self.session.review.items:
                s = item['current']
                colour = {'unreviewed':'#f08000','accepted':'#00a000','rejected':'#df2040'}[item['status']]
                if item['id'] in self.selected_ids:colour = '#0068df'
                if item['id'] == self.selected_id:colour = '#005bff'
                box(s['bounds'],colour)
                px,py = point(s['pixel_x'],s['pixel_y'])
                if -20<=px<=cw+20 and -20<=py<=ch+20:
                    draw.ellipse((px-3,py-3,px+3,py+3),outline=colour,width=2)
                    if item['id']==self.selected_id:draw.ellipse((px-7,py-7,px+7,py+7),outline=colour,width=2)
                    if self.scale>=.45:draw.text((px+5,py-15),f"{s['depth']:g}",fill=colour)
        if self.roi:
            x,y,rw,rh = self.roi;box((x,y,x+rw,y+rh),'#0068ff')
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.delete('all')
        self.canvas.create_image((x1-self.left)*self.scale,(y1-self.top)*self.scale,image=self.photo,anchor='nw')
        self.zoom_text.set(f'{self.scale*100:.0f}%')
