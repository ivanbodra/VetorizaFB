"""Classic Tk reading review; retains existing main-window layout."""
import tkinter as tk
from tkinter import ttk,messagebox,simpledialog
from PIL import Image,ImageTk
from .fieldbook import token
from .token_review import correct,edit_boxes


class TokenDialog(tk.Toplevel):
    def __init__(self,app,index=None):
        super().__init__(app.root);self.app=app;self.session=app.session
        self.title('Revisar leituras');self.geometry('780x600')
        self.only=tk.BooleanVar(self,value=False)
        toolbar=ttk.Frame(self,padding=8);toolbar.pack(fill='x')
        ttk.Checkbutton(toolbar,text='Somente incertas / sem grupo',variable=self.only,command=self.refresh).pack(side='left')
        ttk.Button(toolbar,text='Corrigir',command=self.correct).pack(side='left',padx=4)
        if self.session.config.segmentation=='fb':
            ttk.Button(toolbar,text='Unir caixas',command=self.merge).pack(side='left',padx=4)
            ttk.Button(toolbar,text='Dividir caixa…',command=self.split).pack(side='left',padx=4)
        ttk.Label(self,text='Selecione uma leitura para ver o recorte. Ctrl/clique ou Shift seleciona várias caixas.',padding=6).pack(fill='x')
        self.image=ttk.Label(self,anchor='center');self.image.pack(fill='x',pady=8)
        body=ttk.Frame(self);body.pack(fill='both',expand=True,padx=8)
        self.table=ttk.Treeview(body,columns=('id','text','score','state','method'),show='headings',selectmode='extended')
        for key,label in zip(self.table['columns'],('ID','Leitura','Confiança','Estado','Método')):
            self.table.heading(key,text=label);self.table.column(key,width=110,stretch=True)
        scroll=ttk.Scrollbar(body,orient='vertical',command=self.table.yview);self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');self.table.pack(fill='both',expand=True)
        self.table.bind('<<TreeviewSelect>>',lambda _:self.show_crop());self.table.bind('<Double-1>',lambda _:self.correct())
        self.refresh()
        if index is not None and self.table.exists(str(index)):
            self.table.selection_set(str(index));self.table.see(str(index));self.show_crop()
    def refresh(self):
        self.table.delete(*self.table.get_children())
        s=self.session;assigned={i for item in s.review.items for i in item['current']['digit_ids']} if s.review else None
        for d in s.digits or []:
            t=token(d) if s.config.segmentation=='fb' else d.text
            uncertain=t is None or d.score<s.config.min_confidence or (assigned is not None and d.index not in assigned)
            if self.only.get() and not uncertain:continue
            self.table.insert('','end',iid=str(d.index),values=(d.index,d.raw_text,f'{d.score:.3f}','Incerta / sem grupo' if uncertain else 'Lida',d.method))
    def ids(self):return [int(i) for i in self.table.selection()]
    def show_crop(self):
        ids=self.ids()
        if not ids:return
        boxes=[self.session.digits[i].box for i in ids]
        x=max(0,min(b.x for b in boxes)-12);y=max(0,min(b.y for b in boxes)-12)
        r=max(b.x+b.w for b in boxes)+12;bottom=max(b.y+b.h for b in boxes)+12
        patch=Image.fromarray(self.session.rgb[y:bottom,x:r]);patch.thumbnail((600,160))
        factor=min(4,600/patch.width,160/patch.height);patch=patch.resize((max(1,round(patch.width*factor)),max(1,round(patch.height*factor))))
        self.photo=ImageTk.PhotoImage(patch);self.image.configure(image=self.photo)
        b=boxes[0];self.app.viewer.focus(*b.center,(b.x,b.y,b.x+b.w,b.y+b.h))
    def permitted(self):
        if self.app.busy or self.app.session is not self.session:return False
        try:
            if not self.session.valid_digits(self.app.config(),self.app.model_spec(),self.app.roi):raise ValueError('Parâmetros mudaram. Execute Reconhecer novamente.')
        except ValueError as e:messagebox.showerror('Leituras',str(e),parent=self);return False
        return self.session.review is None or self.app.confirm_replace()
    def changed(self):
        self.app.review_dirty=True;self.app.refresh_points();self.app.refresh_validity();self.app.viewer.refresh_layers();self.app.viewer.render()
    def correct(self):
        ids=self.ids()
        if len(ids)!=1 or not self.permitted():return
        value=simpledialog.askstring('Corrigir leitura','Algarismos; deixe vazio para rejeitar a leitura:',initialvalue=self.session.digits[ids[0]].raw_text,parent=self)
        if value is None:return
        try:correct(self.session,ids[0],value)
        except ValueError as e:messagebox.showerror('Leitura',str(e),parent=self);return
        self.changed();self.refresh()
    def merge(self):self.geometry_edit()
    def split(self):
        ids=self.ids()
        if len(ids)!=1:return
        vertical=messagebox.askyesnocancel('Dividir caixa','Divisão vertical? Sim: vertical. Não: horizontal.',parent=self)
        if vertical is None:return
        b=self.session.digits[ids[0]].box;limit=b.w if vertical else b.h
        if limit<2:return
        pos=simpledialog.askinteger('Dividir caixa','Posição a partir da borda (pixels):',initialvalue=limit//2,minvalue=1,maxvalue=limit-1,parent=self)
        if pos is not None:self.geometry_edit('vertical' if vertical else 'horizontal',pos)
    def geometry_edit(self,axis=None,position=None):
        if not self.permitted():return
        try:edit_boxes(self.session,self.ids(),axis=axis,position=position)
        except ValueError as e:messagebox.showerror('Caixas',str(e),parent=self);return
        self.changed();self.app.viewer.layer.set('Caixas');self.app.viewer.render()
        self.app.status.set('Caixas alteradas. Execute Reconhecer para atualizar as leituras.');self.destroy()
