"""Explicit position/offset forms and a scrollable calibration panel."""
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox


class ScrollablePanel(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent)
        self.canvas=tk.Canvas(self,highlightthickness=0,borderwidth=0,width=330,bg='#f5f8fb')
        self.scroll=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side='left',fill='both',expand=True)
        self.content=ttk.Frame(self.canvas,padding=9)
        window=self.canvas.create_window((0,0),window=self.content,anchor='nw')
        self._layout_pending=False
        def queue_layout(event=None):
            if not self._layout_pending:
                self._layout_pending=True
                self.after_idle(layout)
        def layout():
            self._layout_pending=False
            height=max(1,self.canvas.winfo_height())
            requested=self.content.winfo_reqheight()
            need_scroll=requested>height
            if need_scroll and not self.scroll.winfo_manager():
                self.scroll.pack(side='right',fill='y',before=self.canvas)
            elif not need_scroll and self.scroll.winfo_manager():
                self.scroll.pack_forget();self.canvas.yview_moveto(0)
            width=max(1,self.canvas.winfo_width())
            target_height=max(height,requested)
            if self.canvas.itemcget(window,'width')!=str(width) or self.canvas.itemcget(window,'height')!=str(target_height):
                self.canvas.itemconfigure(window,width=width,height=target_height)
            self.canvas.configure(scrollregion=(0,0,width,target_height))
        self.canvas.bind('<Configure>',queue_layout)
        self.content.bind('<Configure>',queue_layout)
        queue_layout()


def number(variable):
    try:return float(variable.get().strip().replace(',','.'))
    except ValueError as exc:raise ValueError('Informe um número válido, com ponto ou vírgula decimal') from exc


class ReviewDialog(simpledialog.Dialog):
    def buttonbox(self):
        bar=ttk.Frame(self)
        ttk.Button(bar,text='Aplicar',command=self.ok).pack(side='left',padx=5,pady=6)
        ttk.Button(bar,text='Cancelar',command=self.cancel).pack(side='left',padx=5,pady=6)
        bar.pack()
        self.bind('<Return>',self.ok);self.bind('<Escape>',self.cancel)


class PositionDialog(ReviewDialog):
    def __init__(self,parent,session,point_id):
        self.session=session
        s=session.review.item(point_id)['current']
        self.x=tk.StringVar(parent,value=f"{s['pixel_x']:.12g}")
        self.y=tk.StringVar(parent,value=f"{s['pixel_y']:.12g}")
        super().__init__(parent,title=f'Posição da sondagem {point_id}')

    def body(self,master):
        ttk.Label(master,text='Coordenadas em pixels da imagem original; X à direita, Y para baixo.',wraplength=400).grid(row=0,column=0,columnspan=2,pady=8)
        first=None
        for row,label,var in [(1,'X (pixel)',self.x),(2,'Y (pixel)',self.y)]:
            ttk.Label(master,text=label).grid(row=row,column=0,sticky='w',padx=6,pady=5)
            entry=ttk.Entry(master,textvariable=var,width=22);entry.grid(row=row,column=1,padx=6,pady=5)
            if first is None:first=entry
        return first

    def validate(self):
        try:self.result=self.session.validate_position(number(self.x),number(self.y))
        except (ValueError,OverflowError) as exc:
            messagebox.showerror('Posição',str(exc),parent=self);return False
        return True


class OffsetDialog(ReviewDialog):
    def __init__(self,parent,session,selected):
        self.session,self.selected=session,list(selected)
        self.x,self.y=tk.StringVar(parent,value='0'),tk.StringVar(parent,value='0')
        self.unit=tk.StringVar(parent,value='Pixels da imagem')
        self.scope=tk.StringVar(parent,value='Todas as sondagens')
        self.preview_text=tk.StringVar(parent,value='Use “Prévia” para conferir o deslocamento antes de aplicar.')
        super().__init__(parent,title='Deslocamento adicional das posições')

    def body(self,master):
        ttk.Label(master,text='O deslocamento é somado às posições atuais. Todas inclui pontos ocultos pelo filtro e excluídos. Aprovações retornam a pendente; excluídos permanecem excluídos.',wraplength=460).grid(row=0,column=0,columnspan=2,padx=6,pady=8)
        first=None
        for row,label,var in [(1,'ΔX',self.x),(2,'ΔY',self.y)]:
            ttk.Label(master,text=label).grid(row=row,column=0,sticky='w',padx=6,pady=5)
            entry=ttk.Entry(master,textvariable=var,width=24);entry.grid(row=row,column=1,sticky='ew',padx=6,pady=5)
            if first is None:first=entry
        for row,label,var,values in [(3,'Unidade',self.unit,['Pixels da imagem','Metros no CRS projetado']),
                                     (4,'Aplicar a',self.scope,['Todas as sondagens']+(['Selecionadas'] if self.selected else []))]:
            ttk.Label(master,text=label).grid(row=row,column=0,sticky='w',padx=6,pady=5)
            ttk.Combobox(master,textvariable=var,values=values,state='readonly',width=28).grid(row=row,column=1,padx=6,pady=5)
        ttk.Label(master,text='Pixels: +X direita, +Y baixo. Metros: ΔX/ΔY nos eixos do CRS da carta.',wraplength=460).grid(row=5,column=0,columnspan=2,padx=6,pady=8)
        ttk.Button(master,text='Prévia (sem alterar)',command=self.preview).grid(row=6,column=0,columnspan=2,pady=5)
        ttk.Label(master,textvariable=self.preview_text,wraplength=460).grid(row=7,column=0,columnspan=2,padx=6,pady=8)
        return first

    def values(self):
        return dict(dx=number(self.x),dy=number(self.y),
                    unit='pixels' if self.unit.get()=='Pixels da imagem' else 'metres',
                    point_ids=self.selected if self.scope.get()=='Selecionadas' else None)

    def preview(self):
        try:
            p=self.session.preview_offset(**self.values())
            self.preview_text.set(f"{p['count']} sondagens; Δpixel X={p['pixel_dx']:.6g}, Y={p['pixel_dy']:.6g}. Todas as posições ficam dentro da carta.")
        except (ValueError,OverflowError,KeyError) as exc:self.preview_text.set(str(exc))

    def validate(self):
        try:
            values=self.values();self.session.preview_offset(**values);self.result=values
        except (ValueError,OverflowError,KeyError) as exc:
            messagebox.showerror('Deslocamento',str(exc),parent=self);return False
        return True
