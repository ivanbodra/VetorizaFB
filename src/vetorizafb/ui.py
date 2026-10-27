"""Small, local desktop helpers: contextual help without permanent legends."""
import tkinter as tk
from tkinter import ttk
from weakref import WeakSet
from PIL import Image, ImageDraw, ImageTk


def rounded_controls(style, root):
    """Image-backed clam elements keep native ttk controls and their keyboard behavior."""
    if 'Rounded.border' in style.element_names():
        return getattr(root,'_rounded_images',[])
    images=[]

    def surface(colour, *, top_only=False):
        scale=3
        im=Image.new('RGBA',(24*scale,24*scale))
        draw=ImageDraw.Draw(im)
        inset=2*scale if top_only else 0
        draw.rounded_rectangle((inset,0,24*scale-1-inset,24*scale-1),radius=6*scale,fill=colour)
        if top_only:
            draw.rectangle((inset,7*scale,24*scale-1-inset,24*scale-1),fill=colour)
        photo=ImageTk.PhotoImage(im.resize((24,24),Image.Resampling.LANCZOS),master=root)
        images.append(photo)
        return photo

    def element(name, palette, top_only=False):
        normal=surface(palette[0],top_only=top_only)
        selected=surface(palette[1],top_only=top_only)
        active=surface(palette[2],top_only=top_only)
        disabled=surface(palette[3],top_only=top_only)
        style.element_create(name,'image',normal,
                             ('disabled',disabled),('selected',selected),
                             ('pressed',active),('active',active),border=9,sticky='nsew')

    def replace_border(layout, replacement):
        name, options=layout[0]
        return [(replacement,{**options,'children':options['children']})]

    button_layout=style.layout('TButton')
    for key,normal,hover in [('Rounded','#e5f1fb','#d2e8f9'),
                              ('PrimaryRounded','#096fab','#085a8b'),
                              ('ApproveRounded','#e1f4e9','#c9ead8'),
                              ('RejectRounded','#fbe6e8','#f5cfd4')]:
        element(key+'.border',(normal,hover,hover,'#eef1f4'))
        button_children=[('Button.padding',{'sticky':'nsew','children':[('Button.label',{'sticky':'nsew'})]})]
        style.layout({'Rounded':'TButton','PrimaryRounded':'Primary.TButton',
                      'ApproveRounded':'Approve.TButton','RejectRounded':'Reject.TButton'}[key],
                     [(key+'.border',{'sticky':'nsew','children':button_children})])
    element('RoundedMenu.border',('#e5f1fb','#d2e8f9','#d2e8f9','#eef1f4'))
    style.layout('TMenubutton',replace_border(style.layout('TMenubutton'),'RoundedMenu.border'))
    element('RoundedTab.tab',('#e5f1fb','#153b50','#cee7f8','#eef1f4'),top_only=True)
    style.layout('TNotebook.Tab',replace_border(style.layout('TNotebook.Tab'),'RoundedTab.tab'))
    root._rounded_images=images
    return images


class Tooltip:
    _instances=WeakSet()

    def __init__(self, widget, text, delay=550):
        self.widget, self.text, self.delay = widget, text, delay
        self.pending = self.popup = None
        self._instances.add(self)
        widget.bind('<Enter>', self.schedule, add='+')
        widget.bind('<Leave>', self.hide, add='+')
        widget.bind('<ButtonPress>', self.hide, add='+')
        widget.bind('<Destroy>', self.hide, add='+')

    def schedule(self, event=None):
        self.hide()
        if not getattr(self.widget._root(),'_vetorizafb_tooltips_enabled',True):return
        self.pending = self.widget.after(self.delay, self.show)

    def show(self):
        self.pending = None
        if not getattr(self.widget._root(),'_vetorizafb_tooltips_enabled',True):return
        text = self.text() if callable(self.text) else self.text
        if not text or not self.widget.winfo_exists():return
        self.popup=tk.Toplevel(self.widget)
        self.popup.wm_overrideredirect(True)
        ttk.Label(self.popup,text=text,style='Tooltip.TLabel',padding=(10,7),wraplength=400).pack()
        self.popup.update_idletasks()
        x=min(self.widget.winfo_pointerx()+12,self.popup.winfo_screenwidth()-self.popup.winfo_reqwidth()-8)
        y=min(self.widget.winfo_pointery()+18,self.popup.winfo_screenheight()-self.popup.winfo_reqheight()-8)
        self.popup.geometry(f'+{max(0,x)}+{max(0,y)}')

    def hide(self,event=None):
        if self.pending:
            self.widget.after_cancel(self.pending);self.pending=None
        if self.popup:
            if self.popup.winfo_exists():self.popup.destroy()
            self.popup=None

    @classmethod
    def set_enabled(cls,root,enabled):
        root._vetorizafb_tooltips_enabled=bool(enabled)
        if not enabled:
            for item in tuple(cls._instances):
                if item.widget._root() is root:item.hide()
