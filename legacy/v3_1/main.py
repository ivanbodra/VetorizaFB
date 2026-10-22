# hydrovectorizer_gui/main.py

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import ocr_segmented
import geo_utils
import export_utils
import os
import webbrowser
import time
import pandas as pd
from PIL import Image, ImageTk
import cv2

# --- Demais funções ---
def open_manual():
    webbrowser.open("HydroVectorizer_Instrucoes.pdf")

def show_about():
    about_win = tk.Toplevel(root)
    about_win.title("Sobre")
    about_win.configure(bg="#ebfcf8")
    tk.Label(about_win, text="Versão Beta 3.1 (31OUT2025)", bg="#ebfcf8").pack()
    tk.Label(about_win, text="Contato: CHM-311 CC Ivan - ivan.bodra@marinha.mil.br", bg="#ebfcf8").pack()

def select_output_folder():
    folder = filedialog.askdirectory()
    if folder:
        entry_output.delete(0, tk.END)
        entry_output.insert(0, folder)
        # update_run_button()

# --- Funções das imagens ---
def mostrar_imagem(path, scale=None, max_width=900, max_height=700):
    try:
        global zoom_factor
        img = Image.open(path)

        if scale is None:
            scale = zoom_factor  # usa o zoom atual

        w, h = img.size
        w_scaled, h_scaled = int(w * scale), int(h * scale)

        img = img.resize((w_scaled, h_scaled), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        img_label.config(image=photo)
        img_label.image = photo
        canvas.config(scrollregion=canvas.bbox("all"))

    except Exception as e:
        print(f"Erro ao exibir imagem: {e}")


def atualizar_imagem():
    global zoom_factor
    if 0 <= imagem_atual_index < len(imagens_geradas): 
        mostrar_imagem(imagens_geradas[imagem_atual_index], scale=zoom_factor)
        status_var.set(f"Visualizando: {os.path.basename(imagens_geradas[imagem_atual_index])}")
        if imagem_atual_index == 0:
            voltar_button.config(state="disabled")
        else:
            voltar_button.config(state="normal")
        if imagem_atual_index == len(imagens_geradas) - 1:
            avancar_button.config(state="disabled")
        else:
            avancar_button.config(state="normal")   

def avancar_imagem():
    global imagem_atual_index
    if imagem_atual_index < len(imagens_geradas) - 1:
        imagem_atual_index += 1
        atualizar_imagem()

def voltar_imagem():
    global imagem_atual_index
    if imagem_atual_index > 0:
        imagem_atual_index -= 1
        atualizar_imagem()

def selecionar_imagem():
    caminho = filedialog.askopenfilename(filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff")])
    if caminho:
        mostrar_imagem(caminho)
        status_var.set(f"Visualizando (manual): {os.path.basename(caminho)}")

def reprocessar_imagem():
    atualizar_imagem()

def scroll_zoom(event):
    global zoom_factor
    if event.delta > 0 or event.num == 4:   # scroll up
        zoom_factor = min(4.0, 1.6* zoom_factor)
    elif event.delta < 0 or event.num == 5: # scroll down
        zoom_factor = max(0.1, 0.8*zoom_factor)
    atualizar_imagem()

def zoom_in():
    global zoom_factor
    zoom_factor = min(4.0, 1.6*zoom_factor)
    atualizar_imagem()

def zoom_out():
    global zoom_factor
    zoom_factor = max(0.1, 0.8*zoom_factor)
    atualizar_imagem()

"""
def start_pan(event):
    drag_data["x"] = event.x
    drag_data["y"] = event.y

def do_pan(event):
    dx = drag_data["x"] - event.x
    dy = drag_data["y"] - event.y
    canvas.xview_scroll(int(dx), "units")
    canvas.yview_scroll(int(dy), "units")
    drag_data["x"] = event.x
    drag_data["y"] = event.y
"""
# --- Etapa 1 preprocessamento da imagem e segmentação ---
def etapa_1(image_path, valor_threshold=127, blur_size=5, kernel_size=2,
            min_h=10, max_h=100, min_w=3, max_w=80):
    global imagens_geradas, dilated, boxes, tempo_preprocess, tempo_boxes
    
    # Garantir que blur seja ímpar
    if blur_size % 2 == 0:
        blur_size += 1

    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        status_var.set("Erro: não foi possível abrir a imagem")
        return

    # Aplica desfoque
    blur = cv2.GaussianBlur(img, (blur_size, blur_size), 0)

    # Binarização com threshold manual
    _, thresh = cv2.threshold(blur, valor_threshold, 255, cv2.THRESH_BINARY_INV)

    # Dilatação com kernel definido
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    dilated = cv2.dilate(thresh, kernel, iterations=1)

    tempo_preprocess = time.time() - inicio_preprocess
    inicio_boxes = time.time()

    # Detecção de contornos e filtragem
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = [cv2.boundingRect(c) for c in contours
             if min_h < cv2.boundingRect(c)[3] < max_h and min_w < cv2.boundingRect(c)[2] < max_w]

    # Visualização dos boxes
    vis = cv2.cvtColor(dilated, cv2.COLOR_GRAY2BGR)
    for (x, y, w, h) in boxes:
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 255), 2)

    os.makedirs("temp", exist_ok=True)
    vis_path = os.path.join("temp","temp_etapa1.png")
    if vis_path not in imagens_geradas:
        imagens_geradas.append(vis_path) 
    cv2.imwrite(vis_path, vis)
    mostrar_imagem(vis_path, scale=zoom_factor)
    status_var.set(f"Etapa 1 concluída. Caixas detectadas: {len(boxes)}")
    OCR_button.config(state="normal")

    tempo_boxes = time.time() - inicio_boxes
    return boxes, dilated

# --- Botão de execução da etapa 1 ---
def rodar_etapa_1():
    global inicio_preprocess
    inicio_preprocess = time.time()
    
    image_path = entry_file.get()
    if not image_path:
        messagebox.showerror("Erro", "Selecione uma imagem primeiro")
        return

    # Pega os valores dos campos
    valor_threshold = int(entry_thresh.get())
    blur_size = int(entry_blur.get())
    kernel_size = int(entry_dilate.get())
    min_h = int(entry_min_h.get())
    max_h = int(entry_max_h.get())
    min_w = int(entry_min_w.get())
    max_w = int(entry_max_w.get())

    etapa_1(image_path,
            valor_threshold=valor_threshold,
            blur_size=blur_size,
            kernel_size=kernel_size,
            min_h=min_h,
            max_h=max_h,
            min_w=min_w,
            max_w=max_w)
            


# --- Etapa 1b reconhecimento de dígitos ---
def rodar_etapa_1b():
    
    global digits_df, imagem_atual_index, tempo_ocr

    inicio_ocr = time.time()
    
    image_path = entry_file.get()
    if not image_path:
        messagebox.showerror("Erro", "Selecione uma imagem primeiro")
        return
    if dilated is None or not boxes:
        messagebox.showerror("Erro", "Execute primeiro a Etapa 1")
        return

    status_var.set("Executando OCR...")
    start = time.time()
    digits_df = ocr_segmented.recognize_digits(dilated, boxes)
    
    # Gera imagem com os boxes coloridos
    ocr_debug_path = os.path.join("temp", "temp_OCR_raw.png")
    import debug_utils  # se ainda não estiver importado
    debug_utils.generate_ocr_debug_image(image_path, digits_df, ocr_debug_path, scale=0.5)

    mostrar_imagem(ocr_debug_path)
    if ocr_debug_path not in imagens_geradas:
        imagens_geradas.append(ocr_debug_path) 

    tempo_ocr = time.time() - inicio_ocr
    status_var.set(f"Etapa 2 concluída. Dígitos reconhecidos: {len(digits_df)} em {tempo_ocr:.2f}s")
    imagem_atual_index += 1

    agrupar_button.config(state="normal")

# --- Etapa 2 agrupamento de dígitos ---
def rodar_etapa_2():
    global depths_df, imagem_atual_index, tempo_agrupamento, bode_verde_img

    inicio_agrupamento = time.time()
    
    if digits_df is None or digits_df.empty:
        messagebox.showerror("Erro", "Execute a Etapa 2 antes de agrupar.")
        return

    try:
        distance_threshold = int(entry_distance_threshold.get())
        vertical_threshold = int(entry_vertical_threshold.get())
    except ValueError:
        messagebox.showerror("Erro", "Verifique se os valores de distância e altura mínima são numéricos.")
        return

    status_var.set("Agrupando profundidades...")
    start = time.time()
    depths_df = ocr_segmented.group_digits_by_position(digits_df, distance_threshold, vertical_threshold)
    elapsed = time.time() - start

    # --- AQUI adicionamos o georreferenciamento automático ---
    try:
        image_path = entry_file.get()
        gt, srs_wkt = geo_utils.get_geotransform(image_path)
        depths_df = geo_utils.apply_geotransform(depths_df, gt, srs_wkt, add_lonlat=True)
    except Exception as e:
        print(f"⚠️ Erro ao aplicar geotransform na etapa 2: {e}")
    # ---------------------------------------------------------

    if depths_df.empty:
        messagebox.showwarning("Aviso", "Nenhuma profundidade foi agrupada. Verifique os parâmetros.")
        return

    # Gera imagem de debug
    agrup_path = os.path.join("temp", "temp_debug_agrupamento.png")
    import debug_utils
    debug_utils.generate_grouped_image(entry_file.get(), depths_df, agrup_path, scale=0.5)

    if agrup_path not in imagens_geradas:
        imagens_geradas.append(agrup_path)
    mostrar_imagem(agrup_path)
    status_var.set(f"Agrupamento concluído. {len(depths_df)} profundidades detectadas em {elapsed:.2f}s.")
    imagem_atual_index += 1
    bode_verde_pil = Image.open("bode_verde.png")
    bode_verde_pil = bode_verde_pil.resize((int(bode_verde_pil.width * 38 / bode_verde_pil.height), 38), Image.Resampling.LANCZOS)
    bode_verde_img = ImageTk.PhotoImage(bode_verde_pil)

    exportar_button.config(state="normal", image=bode_verde_img, compound="left")

    tempo_agrupamento = time.time() - inicio_agrupamento

def exportar_xyz():
    global depths_df
    if depths_df is None or depths_df.empty:
        messagebox.showerror("Erro", "Execute a Etapa 2 antes de exportar.")
        return

    depths_df['depth'] = pd.to_numeric(depths_df['depth'], errors='coerce')
    
    inicio_geo = time.time()
    status_var.set("Aplicando georreferenciamento...")
    # a ser incluído na etapa 2 de agrupamento, com caixas de entrada e visualização na imagem de agrupamento, com círculo vermelho:
    # depths_df['pixel_x'] += offset_x 
    # depths_df['pixel_y'] += offset_y

    image_path = entry_file.get()
    usuario = entry_usuario.get()
    senha = entry_senha.get()
    output_dir = entry_output.get()
    # offset_x = int(entry_offset_x.get())
    # offset_y = int(entry_offset_y.get())

    if not all([image_path, output_dir, usuario, senha]):
        status_var.set("Erro: campos obrigatórios não preenchidos")
        status_bar.config(bg="#800000")
        messagebox.showerror("Erro", "Preencha todos os campos obrigatórios.")
        return

    if usuario and senha:
        proxy_url = f"http://{usuario}:{senha}@proxy-armacao.mb:6060"
        os.environ["HTTP_PROXY"] = proxy_url
        os.environ["HTTPS_PROXY"] = proxy_url

    try:
        gt, projection = geo_utils.get_geotransform(image_path)
    except FileNotFoundError as e:
        status_var.set("Erro ao abrir o GeoTIFF")
        status_bar.config(bg="#800000")
        messagebox.showerror("Erro", str(e))
        return

    depths_df = geo_utils.apply_geotransform(depths_df, gt)

    tempo_geo = time.time() - inicio_geo

    status_var.set(f"Exportando arquivos... Total: {len(depths_df)} pontos, decimais: {sum(depths_df['depth'] % 1 != 0):.0f}")
    
    output_dir = entry_output.get()
    output_xyz = os.path.join(output_dir, 'output_depths.xyz')
    output_log = os.path.join(output_dir, 'extraction.log')
    output_info = os.path.join(output_dir, 'output_depths.info')
    
    export_utils.export_xyz(depths_df, output_xyz)
    export_utils.export_log(
        depths_df,
        output_log,
        projection,
        tempo_preprocess=tempo_preprocess,
        tempo_boxes=tempo_boxes,
        tempo_ocr=tempo_ocr,
        tempo_agrupamento=tempo_agrupamento,
        tempo_geo=tempo_geo,
        tempo_total=time.time() - inicio_total,
        usuario=usuario,
        nome_arquivo=os.path.basename(image_path)
    )   

    #export_utils.export_info_file(output_info)
    export_utils.export_info_file(depths_df, output_info)

    status_var.set("Exportação concluída com sucesso!")
    status_bar.config(bg="#02801C")
    messagebox.showinfo("Sucesso", "Exportação concluída.")
    
    for img_path in imagens_geradas:
        os.remove(img_path)

    for button in [OCR_button, agrupar_button, exportar_button]:
        button.config(state="disabled")


# --- Splash screen ---
splash_root = tk.Tk()
splash_root.overrideredirect(True)  # Remove bordas da janela
splash_img = Image.open("splash.png")
splash_img = splash_img.resize((400, 438), Image.Resampling.LANCZOS)
splash_photo = ImageTk.PhotoImage(splash_img)
splash_label = tk.Label(splash_root, image=splash_photo)
splash_label.pack()

# Centraliza na tela
screen_width = splash_root.winfo_screenwidth()
screen_height = splash_root.winfo_screenheight()
x = (screen_width // 2) - (400 // 2)
y = (screen_height // 2) - (438 // 2)
splash_root.geometry(f"400x438+{x}+{y}")

# Atualiza e exibe por 3 segundos
splash_root.update()
splash_root.after(3000, splash_root.destroy)
splash_root.mainloop()
inicio_total = time.time()

# --- Construção do GUI ---   
root = tk.Tk()
root.title("VetorizaFB v.B_3.1")
root.iconbitmap("logo_vetorizaFB.ico")
root.configure(bg="#ebfcf8")
root.grid_columnconfigure(1, weight=1)  # coluna do frame_imagem
root.after_idle(lambda: root.eval('tk::PlaceWindow %s center' % root.winfo_toplevel())) # centraliza o GUI na tela ao abrir o programa

menu_bar = tk.Menu(root)
root.config(menu=menu_bar)
about_menu = tk.Menu(menu_bar, tearoff=0)
about_menu.add_command(label="Sobre", command=show_about)
about_menu.add_command(label="Manual", command=open_manual)
menu_bar.add_cascade(label="Ajuda", menu=about_menu)

# --- Cabeçalho com logo e título institucional ---
header_frame = ttk.Frame(root)
header_frame.grid(row=0, column=0, columnspan=1, padx=10, pady=(5, 0), sticky="ew")
header_frame.grid_columnconfigure(0, weight=1)
header_frame.grid_columnconfigure(1, weight=1)
header_frame.grid_columnconfigure(2, weight=1)

try:
    logo_pil = Image.open("logo_mb.png")
    logo_pil = logo_pil.resize((int(logo_pil.width * 56 / logo_pil.height), 56), Image.Resampling.LANCZOS)
    logo_img = ImageTk.PhotoImage(logo_pil)
    tk.Label(header_frame, image=logo_img, bg="#ebfcf8").grid(row=0, column=0, rowspan=2, padx=10)
except:
    tk.Label(header_frame, text="[ Logo ]", bg="#ebfcf8").grid(row=0, column=0, rowspan=2, padx=10)

tk.Label(header_frame, text="Marinha do Brasil", font=("Arial", 12), bg="#ebfcf8").grid(row=0, column=1)
tk.Label(header_frame, text="Centro de Hidrografia da Marinha", font=("Arial", 12), bg="#ebfcf8").grid(row=1, column=1)

try:
    logo_pil2 = Image.open("logo_chm.png")
    logo_pil2 = logo_pil2.resize((int(logo_pil2.width * 56 / logo_pil2.height), 56), Image.Resampling.LANCZOS)
    logo_img2 = ImageTk.PhotoImage(logo_pil2)
    tk.Label(header_frame, image=logo_img2, bg="#ebfcf8").grid(row=0, column=2, rowspan=2, padx=10)
except:
    tk.Label(header_frame, text="[ Logo ]", bg="#ebfcf8").grid(row=0, column=2, rowspan=2, padx=10)

# Proxy
frame_proxy = ttk.LabelFrame(root, text="Conexão à Internet (Proxy)")
frame_proxy.grid(row=1, column=0, padx=10, pady=5, sticky="ew")

tk.Label(frame_proxy, text="Usuário*:", bg="#f7fffd").grid(row=0, column=0, sticky="w", padx=5, pady=2)
entry_usuario = ttk.Entry(frame_proxy, width=20)
entry_usuario.grid(row=0, column=1, padx=5, pady=2)
# entry_usuario.bind("<KeyRelease>", update_run_button)

tk.Label(frame_proxy, text="Senha*:", bg="#f7fffd").grid(row=1, column=0, sticky="w", padx=5, pady=2)
entry_senha = ttk.Entry(frame_proxy, width=20, show="*")
entry_senha.grid(row=1, column=1, padx=5, pady=2)
# entry_senha.bind("<KeyRelease>", update_run_button)

# Entrada
frame_input = ttk.LabelFrame(root, text="Entrada")
frame_input.grid(row=2, column=0, padx=10, pady=5, sticky="ew")

tk.Label(frame_input, text="Arquivo GeoTIFF*:", bg="#f7fffd").grid(row=0, column=0, sticky="w", padx=5)
entry_file = ttk.Entry(frame_input, width=30)
entry_file.grid(row=0, column=1, padx=5, pady=2)
# entry_file.bind("<KeyRelease>", update_run_button)
ttk.Button(frame_input, text="Selecionar arquivo", command=lambda: [entry_file.delete(0, tk.END), entry_file.insert(0, filedialog.askopenfilename())]).grid(row=0, column=2, padx=5, pady=2)
# ttk.Button(frame_input, text="Selecionar arquivo", command=lambda: [entry_file.delete(0, tk.END), entry_file.insert(0, filedialog.askopenfilename()), update_run_button()]).grid(row=0, column=2, padx=5, pady=2)
# ttk.Button().columnconfigure(0, minsize=20)

tk.Label(frame_input, text="Pasta de saída*:", bg="#f7fffd").grid(row=1, column=0, sticky="w", padx=5)
entry_output = ttk.Entry(frame_input, width=30)
entry_output.grid(row=1, column=1, padx=5, pady=2)
# entry_output.bind("<KeyRelease>", update_run_button)
ttk.Button(frame_input, text="Selecionar pasta", command=select_output_folder).grid(row=1, column=2, sticky="ew", padx=5, pady=2)
# set the width of the ttk.Button as 20
# ttk.Button().columnconfigure(0, minsize=20)

# var_same_output = tk.BooleanVar()
# ttk.Checkbutton(frame_input, text="Usar mesma pasta do arquivo", variable=var_same_output, command=lambda: set_same_output() if var_same_output.get() else None).grid(row=2, column=1, sticky="w", padx=5, pady=2)

# frame_config = ttk.LabelFrame(root, text="Configurações")
# frame_config.grid(row=3, column=0, padx=10, pady=5, sticky="ew")

# Etapa 1
frame_etapas = ttk.LabelFrame(root, text="Processamento")
frame_etapas.grid(row=3, column=0, padx=10, pady=5, sticky="w")
frame_etapa1 = ttk.LabelFrame(frame_etapas, text="  Etapa 1 - Pré-processamento")
frame_etapa1.grid(row=0, column=0, padx=10, pady=5, sticky="w")

# Threshold para binarização
tk.Label(frame_etapa1, text="Threshold binarização:", bg="#f7fffd").grid(row=0, column=0, sticky="w", padx=5, pady=2)
entry_thresh = ttk.Entry(frame_etapa1, width=5)
entry_thresh.insert(0, "120")
entry_thresh.grid(row=0, column=1, padx=5, pady=2)

# Tamanho do blur
tk.Label(frame_etapa1, text="Gaussian Blur (ímpar):", bg="#f7fffd").grid(row=1, column=0, sticky="w", padx=5, pady=2)
entry_blur = ttk.Entry(frame_etapa1, width=5)
entry_blur.insert(0, "5")
entry_blur.grid(row=1, column=1, padx=5, pady=2)

# Kernel da dilatação
tk.Label(frame_etapa1, text="Kernel dilatação:", bg="#f7fffd").grid(row=2, column=0, sticky="w", padx=5, pady=2)
entry_dilate = ttk.Entry(frame_etapa1, width=5)
entry_dilate.insert(0, "2")
entry_dilate.grid(row=2, column=1, padx=5, pady=2)

# Altura mínima/máxima
tk.Label(frame_etapa1, text="Altura mínima:", bg="#f7fffd").grid(row=3, column=0, sticky="w", padx=5, pady=2)
entry_min_h = ttk.Entry(frame_etapa1, width=5)
entry_min_h.insert(0, "10")
entry_min_h.grid(row=3, column=1, padx=5, pady=2)

tk.Label(frame_etapa1, text="Altura máxima:", bg="#f7fffd").grid(row=4, column=0, sticky="w", padx=5, pady=2)
entry_max_h = ttk.Entry(frame_etapa1, width=5)
entry_max_h.insert(0, "100")
entry_max_h.grid(row=4, column=1, padx=5, pady=2)

# Largura mínima/máxima
tk.Label(frame_etapa1, text="Largura mínima:", bg="#f7fffd").grid(row=5, column=0, sticky="w", padx=5, pady=2)
entry_min_w = ttk.Entry(frame_etapa1, width=5)
entry_min_w.insert(0, "3")
entry_min_w.grid(row=5, column=1, padx=5, pady=2)

tk.Label(frame_etapa1, text="Largura máxima:", bg="#f7fffd").grid(row=6, column=0, sticky="w", padx=5, pady=2)
entry_max_w = ttk.Entry(frame_etapa1, width=5)
entry_max_w.insert(0, "80")
entry_max_w.grid(row=6, column=1, padx=5, pady=2)

# frame_run = ttk.Frame(root)
# frame_run.configure(style="TFrame")
# frame_run.grid(row=4, column=0, pady=(10, 10), sticky="ew")

progress = ttk.Progressbar(root, orient="horizontal", length=100, mode="determinate")
progress.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 5))

status_var = tk.StringVar()
status_var.set("Aguardando preenchimento...")
status_bar = tk.Label(root, textvariable=status_var, relief=tk.SUNKEN, anchor="w", bg="#ebfcf8", fg="black")
status_bar.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 5))

# Frame Etapa 3
frame_etapa2 = ttk.LabelFrame(frame_etapas, text="  Etapa 2 - Agrupamento")
frame_etapa2.grid(row=0, column=1, padx=10, pady=5, sticky="n")

tk.Label(frame_etapa2, text="Dist. hor. máx.:", bg="#f7fffd").grid(row=0, column=0, sticky="w", padx=5, pady=2)
entry_distance_threshold = ttk.Entry(frame_etapa2, width=5)
entry_distance_threshold.insert(0, "30")
entry_distance_threshold.grid(row=0, column=1, padx=5, pady=2)

tk.Label(frame_etapa2, text="Altura mín. (decimal):", bg="#f7fffd").grid(row=1, column=0, sticky="w", padx=5, pady=2)
entry_vertical_threshold = ttk.Entry(frame_etapa2, width=5)
entry_vertical_threshold.insert(0, "6")
entry_vertical_threshold.grid(row=1, column=1, padx=5, pady=2)

agrupar_button = ttk.Button(frame_etapa2, text="▶ Agrupar", command=rodar_etapa_2)
agrupar_button.grid(row=2, column=0, columnspan=2, padx=5, pady=5)
agrupar_button.config(state="disabled")

# Frame Etapa 2b - exportação
bode_cinza_pil = Image.open("bode_cinza.png")
bode_cinza_pil = bode_cinza_pil.resize((int(bode_cinza_pil.width * 38 / bode_cinza_pil.height), 38), Image.Resampling.LANCZOS)
bode_cinza_img = ImageTk.PhotoImage(bode_cinza_pil)
exportar_button = ttk.Button(frame_etapas, text=" Exportar XYZ", image=bode_cinza_img, compound=tk.LEFT, command=exportar_xyz)
exportar_button.grid(row=0, column=1, columnspan=2, padx=5, pady=5, sticky="s")
exportar_button.config(state="disabled")

# --- Frame para exibição da imagem ao lado direito ---
frame_imagem = ttk.LabelFrame(root, text="Visualização da Imagem")
frame_imagem.grid(row=0, column=1, rowspan=5, padx=(5, 10), pady=5, sticky="nsew")
frame_imagem.grid_rowconfigure(0, weight=1)
frame_imagem.grid_columnconfigure(0, weight=1)

# --- Botões de navegação e controle de imagem ---
frame_botoes_img = ttk.Frame(frame_imagem)
frame_botoes_img.grid(row=0, column=0, pady=5, sticky="ew")
#frame_botoes_img.pack(pady=5) # refatorar com grid 

voltar_button = ttk.Button(frame_botoes_img, text="⬅ Anterior", command=voltar_imagem)
voltar_button.grid(row=0, column=0, padx=5)
avancar_button = ttk.Button(frame_botoes_img, text="Avançar ➡", command=avancar_imagem)
avancar_button.grid(row=0, column=1, padx=5)
# ttk.Button(frame_botoes_img, text="🔁 Reprocessar", command=reprocessar_imagem).grid(row=0, column=2, padx=5)
# ttk.Button(frame_botoes_img, text="📂 Selecionar imagem", command=selecionar_imagem).grid(row=0, column=3, padx=5)
ttk.Button(frame_botoes_img, text="🔍 +", command=zoom_in).grid(row=0, column=4, padx=5)
ttk.Button(frame_botoes_img, text="🔍 -", command=zoom_out).grid(row=0, column=5, padx=5)


zoom_factor = 0.1  # começa com 10% da escala original

canvas = tk.Canvas(frame_imagem, bg="#dbece7", width=900, height=700)
canvas.grid(row=1, column=0, sticky="nsew") 

scroll_y = tk.Scrollbar(frame_imagem, orient="vertical", command=canvas.yview)
scroll_y.grid(row=1, column=1, sticky="ns")

scroll_x = tk.Scrollbar(frame_imagem, orient="horizontal", command=canvas.xview)
scroll_x.grid(row=2, column=0, sticky="ew")

canvas.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
frame_imagem.grid_rowconfigure(0, weight=1)
frame_imagem.grid_columnconfigure(0, weight=1)

canvas.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
"""# Variáveis auxiliares para pan
drag_data = {"x": 0, "y": 0}
canvas.bind("<ButtonPress-1>", lambda e: start_pan(e) if not img_label.cget("image") else None)
canvas.bind("<B1-Motion>", lambda e: do_pan(e) if not img_label.cget("image") else None)
"""
img_label = tk.Label(canvas, bg="#dbece7")
img_window = canvas.create_window((0, 0), window=img_label, anchor="nw")

imagem_atual_index = 0
imagens_geradas = []

style_run = ttk.Style()
style_run.configure("Run.TButton", background="#f7fffd", foreground="black", padding=6)

ttk.Button(frame_etapa1, text="▶ Etapa 1", command=rodar_etapa_1).grid(row=7, column=0, padx=5, pady=5, sticky="w")
OCR_button = ttk.Button(frame_etapa1, text="▶ Ler dígitos", command=rodar_etapa_1b)
OCR_button.grid(row=7, column=1, columnspan=1, sticky="e", padx=5, pady=5)
OCR_button.config(state="disabled")

style = ttk.Style()
style.theme_use('clam')  # ou 'alt', 'vista', 'default' conforme sua preferência
style.configure("TCheckbutton", background="#f7fffd", foreground="black")
style.configure("TLabel", background="#f7fffd", foreground="black")
style.configure("TButton", padding=6, relief="raised", background="#75c79e", foreground="black")
style.configure("TProgressbar", thickness=10, troughcolor='#dbece7', background='#02801C')
style.configure("TLabelframe", background="#f7fffd", borderwidth=1)
style.configure("TFrame", background="#ebfcf8", borderwidth=0)
style.configure("TLabelframe.Label", background="#f7fffd", foreground="black", font=("Arial", 9, "bold"))

root.mainloop()
