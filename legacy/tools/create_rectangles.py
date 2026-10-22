from PIL import Image, ImageDraw, ImageFont
import numpy as np
import math
import cv2

# Parâmetros
img_width = 1190
img_height = 150
rect_width = 5
rect_height = 25
spacing = 60
num_rects = 19
start_x = 50
start_y = 50
background_color = 255

# Criar imagem base
image = Image.new("L", (img_width, img_height), color=background_color)
draw = ImageDraw.Draw(image)
teoricos = []

# Desenhar retângulos
for i in range(num_rects):
    angle_deg = i * 10 + 90
    teoricos.append(angle_deg)
    angle_rad = math.radians(angle_deg)
    cx = start_x + i * spacing
    cy = start_y

    corners = [(-rect_width / 2, -rect_height / 2),
               (rect_width / 2, -rect_height / 2),
               (rect_width / 2, rect_height / 2),
               (-rect_width / 2, rect_height / 2)]

    rotated_corners = []
    for x, y in corners:
        xr = x * math.cos(angle_rad) - y * math.sin(angle_rad)
        yr = x * math.sin(angle_rad) + y * math.cos(angle_rad)
        rotated_corners.append((xr + cx, yr + cy))

    draw.polygon(rotated_corners, fill=0)

# OpenCV: converter e binarizar
image_cv = np.array(image)
_, image_thresh = cv2.threshold(image_cv, 127, 255, cv2.THRESH_BINARY_INV)
contours, _ = cv2.findContours(image_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

# Converter para imagem colorida OpenCV e desenhar boxes amarelos
output_img = cv2.cvtColor(image_cv, cv2.COLOR_GRAY2BGR)
contours = sorted(contours, key=lambda cnt: cv2.minAreaRect(cnt)[0][0])

for cnt in contours:
    rect = cv2.minAreaRect(cnt)
    box = cv2.boxPoints(rect)
    box = np.intp(box)
    cv2.drawContours(output_img, [box], 0, (255, 255, 0), 1)  # amarelo

# Só agora: converter para PIL para escrever os textos
image_pil_annotated = Image.fromarray(output_img)
draw_annotated = ImageDraw.Draw(image_pil_annotated)
font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", size=12)

# Escrever ângulos
for i, cnt in enumerate(contours):
    rect = cv2.minAreaRect(cnt)
    cx, cy = rect[0]
    angle_detected = rect[2]
    angle_human = angle_detected + 90 if rect[1][0] < rect[1][1] else angle_detected
    angle_theoretical = teoricos[i]

    #draw_annotated.text((cx - 15, cy + 20), f"T: {angle_theoretical}°", font=font, fill=(0, 0, 255))     # Azul
    draw_annotated.text((cx - 15, cy + 22), f"{angle_detected:.1f}°", font=font, fill=(255, 0, 0))    # Vermelho
   # draw_annotated.text((cx - 15, cy + 38), f"H: {angle_human:.1f}°", font=font, fill=(255, 165, 0))     # Laranja

# Salvar imagem final
final_image = np.array(image_pil_annotated)
# Etapa extra: adicionar título e legenda

# Criar nova imagem com espaço extra no topo
extra_height = 60
annotated_with_legend = Image.new("RGB", (img_width, img_height + extra_height), (255, 255, 255))

# Colar a imagem final original no novo espaço
annotated_with_legend.paste(Image.fromarray(final_image), (0, extra_height))

# Adicionar título e legenda
draw_legend = ImageDraw.Draw(annotated_with_legend)

title = "Análise da Função cv2.minAreaRect()"
subtitle = "Valor do ângulo calculado pela função cv2.minAreaRect() com seus respectivos bounding boxes em amarelo"

# Escrever o texto centralizado
draw_legend.text((10, 5), title.encode('utf-8').decode('utf-8'), fill=(0, 0, 0), font=font)
draw_legend.text((10, 25), subtitle.encode('utf-8').decode('utf-8'), fill=(80, 80, 80), font=font)

# Salvar imagem final com legenda
annotated_with_legend.save("comparacao_TDH_com_legenda.png")
print("📌 Imagem final com título e legenda salva como 'comparacao_TDH_com_legenda.png'")

cv2.imwrite("comparacao_TDH_com_box.png", final_image)
print("✅ Imagem corrigida salva como 'comparacao_TDH_com_box.png'")

""" 
Esta imagem demonstra a aplicação da função cv2.minAreaRect(), do OpenCV, para estimativa da orientação de retângulos rotacionados.

Cada retângulo preto foi desenhado com um ângulo teórico (T), variando de 90° a 270°, em incrementos de 10°. Para cada figura:

(T) representa o ângulo utilizado na construção do retângulo.

(D) é o valor bruto retornado pela função minAreaRect(), que reflete a inclinação do lado mais longo do retângulo com relação ao eixo horizontal, podendo variar entre -90° e 0° (quando o lado mais longo é vertical).

(H) é o ajuste do ângulo para uma interpretação mais intuitiva (para humanos), adicionando +90° quando o lado mais longo está na vertical.

A caixa amarela ao redor de cada retângulo corresponde à bounding box mínima calculada automaticamente pela função.

Essa visualização ajuda a entender:

O comportamento da função quanto à orientação e forma do retângulo.

Por que é necessário interpretar ou corrigir o valor de angle dependendo das proporções da figura.

Como o valor de (D) pode parecer contraintuitivo se não for interpretado de acordo com a convenção do OpenCV.
"""