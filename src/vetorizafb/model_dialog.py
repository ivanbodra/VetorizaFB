"""Compact connection/download form; credentials remain in process memory only."""
import tkinter as tk
from tkinter import ttk,simpledialog,filedialog,messagebox

from .models import ConnectionSettings,MODEL_NAMES
from .ui import Tooltip


class ModelDownloadDialog(simpledialog.Dialog):
    def __init__(self,parent,root,connection=None,model_name=None):
        self.destination=root;self.previous=connection or ConnectionSettings()
        self.name=tk.StringVar(parent,value=model_name if model_name in MODEL_NAMES else MODEL_NAMES[0])
        self.mode=tk.StringVar(parent,value={'system':'Automática','direct':'Direta','proxy':'Proxy'}[self.previous.mode])
        self.server=tk.StringVar(parent,value=self.previous.server)
        self.username=tk.StringVar(parent,value=self.previous.username)
        self.password=tk.StringVar(parent,value=self.previous.password)
        self.ca_file=tk.StringVar(parent,value=self.previous.ca_file)
        self.result=None
        super().__init__(parent,title='Conexão e download do modelo')

    def body(self,master):
        self.configure(background='#f5f8fb');master.configure(background='#f5f8fb')
        master.columnconfigure(1,weight=1);self.proxy_fields=[]
        ttk.Label(master,text='Modelo').grid(row=0,column=0,sticky='w',padx=6,pady=5)
        model=ttk.Combobox(master,textvariable=self.name,values=MODEL_NAMES,state='readonly',width=30)
        model.grid(row=0,column=1,columnspan=2,sticky='ew',padx=6,pady=5)
        ttk.Label(master,text='Conexão').grid(row=1,column=0,sticky='w',padx=6,pady=5)
        mode=ttk.Combobox(master,textvariable=self.mode,values=['Automática','Direta','Proxy'],state='readonly')
        mode.grid(row=1,column=1,columnspan=2,sticky='ew',padx=6,pady=5)
        Tooltip(mode,'Automática usa a configuração de rede disponível ao Python; Direta ignora proxies. Automática não interpreta PAC.')
        for row,label,var in [(2,'Servidor:porta',self.server),(3,'Usuário',self.username),(4,'Senha',self.password)]:
            ttk.Label(master,text=label).grid(row=row,column=0,sticky='w',padx=6,pady=5)
            entry=ttk.Entry(master,textvariable=var,show='•' if row==4 else '')
            entry.grid(row=row,column=1,columnspan=2,sticky='ew',padx=6,pady=5);self.proxy_fields.append(entry)
        ttk.Label(master,text='Certificado CA').grid(row=5,column=0,sticky='w',padx=6,pady=5)
        ca=ttk.Entry(master,textvariable=self.ca_file);ca.grid(row=5,column=1,sticky='ew',padx=6,pady=5)
        Tooltip(ca,'Certificado PEM da rede, se necessário.')
        ttk.Button(master,text='…',width=2,command=lambda:self.ca_file.set(filedialog.askopenfilename(parent=self,filetypes=[('Certificado PEM','*.pem *.crt'),('Todos','*.*')]) or self.ca_file.get())).grid(row=5,column=2,padx=4)
        ttk.Label(master,text=f'Pasta: {self.destination}',wraplength=400).grid(row=6,column=0,columnspan=3,sticky='w',padx=6,pady=(10,3))
        ttk.Label(master,text='Usuário e senha não são gravados em disco.',wraplength=400).grid(row=7,column=0,columnspan=3,sticky='w',padx=6,pady=3)
        self.mode.trace_add('write',lambda *args:self.update_mode());self.update_mode()
        return model

    def update_mode(self):
        for widget in self.proxy_fields:widget.configure(state='normal' if self.mode.get()=='Proxy' else 'disabled')

    def buttonbox(self):
        bar=ttk.Frame(self);bar.pack(fill='x',padx=12,pady=10)
        ttk.Button(bar,text='Baixar',style='Primary.TButton',command=self.ok).pack(side='left')
        ttk.Button(bar,text='Cancelar',command=self.cancel).pack(side='right')
        self.bind('<Return>',self.ok);self.bind('<Escape>',self.cancel)

    def validate(self):
        try:
            setting=ConnectionSettings(mode={'Automática':'system','Direta':'direct','Proxy':'proxy'}[self.mode.get()],
                server=self.server.get().strip(),username=self.username.get(),password=self.password.get(),ca_file=self.ca_file.get().strip())
            setting.validate();self.result=(self.name.get(),setting)
        except ValueError as exc:messagebox.showerror('Conexão',str(exc),parent=self);return False
        return True
