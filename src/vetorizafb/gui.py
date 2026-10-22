"""Small desktop runner for the same tested extraction core used by the CLI."""
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .pipeline import extract


def main():
    root=tk.Tk();root.title('VetorizaFB — avaliação OCR');root.geometry('1150x800')
    source=tk.StringVar();dest=tk.StringVar();model=tk.StringVar(value='PP-OCRv6_small_rec')
    model_dir=tk.StringVar();status=tk.StringVar(value='Selecione uma carta GeoTIFF.')
    events=queue.Queue();worker=None;photo=None
    controls=ttk.Frame(root,padding=10);controls.pack(fill='x')
    controls.columnconfigure(1,weight=1)

    def choose_source():
        path=filedialog.askopenfilename(filetypes=[('GeoTIFF','*.tif *.tiff')])
        if path:
            source.set(path)
            if not dest.get():dest.set(str(Path(path).parent/'results'/Path(path).stem))
    for row,(label,var,command) in enumerate([
        ('Carta',source,choose_source),
        ('Pasta de saída',dest,lambda: dest.set(filedialog.askdirectory() or dest.get())),
        ('Modelo local (opcional)',model_dir,lambda: model_dir.set(filedialog.askdirectory() or model_dir.get()))]):
        ttk.Label(controls,text=label).grid(row=row,column=0,sticky='w')
        ttk.Entry(controls,textvariable=var).grid(row=row,column=1,sticky='ew',padx=8,pady=3)
        ttk.Button(controls,text='Selecionar',command=command).grid(row=row,column=2)
    ttk.Label(controls,text='Modelo OCR').grid(row=3,column=0,sticky='w')
    ttk.Combobox(controls,textvariable=model,state='readonly',values=[
        'PP-OCRv6_small_rec','PP-OCRv6_medium_rec','PP-OCRv5_server_rec']).grid(row=3,column=1,sticky='w',padx=8)
    ttk.Label(controls,text='Saída experimental: candidatos não revisados. Confira a imagem de resultado antes de usar o XYZ.').grid(row=4,column=0,columnspan=3,sticky='w',pady=6)
    progress=ttk.Progressbar(root,mode='indeterminate');progress.pack(fill='x',padx=10)
    ttk.Label(root,textvariable=status).pack(fill='x',padx=10,pady=5)
    canvas=tk.Canvas(root,bg='#202428');canvas.pack(fill='both',expand=True,padx=10,pady=10)

    def show_image(path):
        nonlocal photo
        with Image.open(path) as im:
            im.thumbnail((max(200,canvas.winfo_width()),max(200,canvas.winfo_height())))
            photo=ImageTk.PhotoImage(im.copy())
        canvas.delete('all');canvas.create_image(0,0,image=photo,anchor='nw')

    def run():
        nonlocal worker
        if worker is not None and worker.is_alive():return
        if not Path(source.get()).is_file() or not dest.get():
            messagebox.showerror('Entrada inválida','Selecione a carta e a pasta de saída.');return
        args=(source.get(),dest.get(),model.get(),model_dir.get() or None)
        button.configure(state='disabled');progress.start();status.set('Executando OCR. O primeiro uso pode baixar os pesos do modelo.')
        def task():
            try:
                result=extract(args[0],args[1],model_name=args[2],model_dir=args[3])
                events.put(('ok',result,Path(args[1])/f'{Path(args[0]).stem}.preview.jpg'))
            except Exception as exc:events.put(('error',str(exc),None))
        worker=threading.Thread(target=task,daemon=True);worker.start()

    button=ttk.Button(controls,text='Extrair candidatos e gerar XYZ',command=run)
    button.grid(row=5,column=0,columnspan=3,sticky='ew')

    def poll():
        try:kind,result,path=events.get_nowait()
        except queue.Empty:pass
        else:
            progress.stop();button.configure(state='normal')
            if kind=='error':status.set('Falha.');messagebox.showerror('Erro de processamento',result)
            else:
                status.set(f"{result['soundings']} candidatos; {result['recognized_digits']}/{result['boxes']} caixas com leitura numérica. Resultado exige revisão.")
                show_image(path)
        root.after(100,poll)
    def close():
        if worker is not None and worker.is_alive():
            messagebox.showinfo('Processamento em andamento','Aguarde a conclusão antes de fechar.');return
        root.destroy()
    root.protocol('WM_DELETE_WINDOW',close);root.after(100,poll);root.mainloop()


if __name__=='__main__':main()
