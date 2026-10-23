"""Small, local desktop helpers: contextual help without permanent legends."""
import tkinter as tk
from tkinter import ttk


class Tooltip:
    def __init__(self, widget, text, delay=550):
        self.widget, self.text, self.delay = widget, text, delay
        self.pending = self.popup = None
        widget.bind('<Enter>', self.schedule, add='+')
        widget.bind('<Leave>', self.hide, add='+')
        widget.bind('<ButtonPress>', self.hide, add='+')
        widget.bind('<Destroy>', self.hide, add='+')

    def schedule(self, event=None):
        self.hide()
        self.pending = self.widget.after(self.delay, self.show)

    def show(self):
        self.pending = None
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
