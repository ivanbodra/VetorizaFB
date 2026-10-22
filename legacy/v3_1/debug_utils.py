# debug_utils.py

import cv2
import os
import pandas as pd

"""
def generate_segmented_debug_image(image_path, boxes, output_path, scale=1.0): # gera imagem 1 (debug_boxes) de todos digitos encontrados
    img = cv2.imread(image_path)
    for (x, y, w, h) in boxes:
        # top_left = (int(x * scale), int(y * scale))
        # bottom_right = (int((x + w) * scale), int((y + h) * scale))
        top_left = (x, y)
        bottom_right = (x + w, y + h)
        cv2.rectangle(img, top_left, bottom_right, (255, 0, 0), 2)
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale)
    cv2.imwrite(output_path, img)

def generate_debug_image(image_path, digits_df, output_path, scale=1.0): # gera imagem 3 (debug_profundidades_sem_filtro) dos números reconhecidos
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Imagem não encontrada: {image_path}")

    for _, row in digits_df.iterrows():
        x = int(row['center_x'])
        y = int(row['center_y'])
        h = int(row['height'])
        cv2.rectangle(img, (x - h//2, y - h//2), (x + h//2, y + h//2), (0, 255, 0), 2)
        cv2.putText(img, str(row['digit']), (x - h//2, y - h//2 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1, cv2.LINE_AA)

    if scale != 1.0:
        img = cv2.resize(img, (0, 0), fx=scale, fy=scale)

    cv2.imwrite(output_path, img)

def generate_final_result_debug_image(image_path, depths_df, output_path, scale=1.0): # gera imagem 4 (debug_profundidades_resultado) do resultado final
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Imagem não encontrada: {image_path}")

    for _, row in depths_df.iterrows():
        x = int(row['pixel_x'])
        y = int(row['pixel_y'])
        cv2.circle(img, (x, y), 6, (10, 10, 250), 2)
        cv2.putText(img, f"{row['depth']:.1f}", (x + 5, y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 2, (10, 10, 250), 2, cv2.LINE_AA)

    if scale != 1.0:
        img = cv2.resize(img, (0, 0), fx=scale, fy=scale)

    cv2.imwrite(output_path, img)
"""

def generate_grouped_image(image_path, grouped_df, output_path, scale=1.0): # gera imagem 3 (debug_profundidades_resultado) do resultado final
    import cv2
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Imagem não encontrada: {image_path}")

    for _, row in grouped_df.iterrows():
        x = int(row['pixel_x'])
        y = int(row['pixel_y'])
        h = int(row['y_max'])-int(row['y_min'])  # altura de referência para box
        value = f"{row['depth']:.1f}"
        conf = row['confidence']

        cv2.rectangle(img, (int(row['x_min']), int(row['y_max'])), (int(row['x_max']), int(row['y_min'])), (0, 255, 0), 2)
        cv2.drawMarker(img, (x, y), (10, 10, 250), cv2.MARKER_CROSS, 6, 2) # incluir offsets aqui
        #cv2.circle(img, (x, y), 6, (10, 10, 250), 2) # incluir offsets aqui
        cv2.putText(img, value, (x - h//2, y - h//2 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1, cv2.LINE_AA)
        cv2.putText(img, f"C:{conf:.2f}", (x - h//2, y + h//2 + 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)

    if scale != 1.0:
        img = cv2.resize(img, (0, 0), fx=scale, fy=scale)

    cv2.imwrite(output_path, img)

def generate_ocr_debug_image(image_path, digits_df, output_path, scale=1.0): # gera imagem 2 (debug_ocr_raw) com os caracteres encontrados
    import cv2
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Imagem não encontrada: {image_path}")

    for _, row in digits_df.iterrows():
        x = int(row['center_x'])
        y = int(row['center_y'])
        h = int(row['height'])
        text = row.get('raw_text', '')
        conf = f"{row['confidence']:.2f}"

        # Define a cor do bounding box
        if pd.isna(text) or text == '':
            color = (0, 0, 255)  # vermelho - não reconhecido
        elif row.get('ocr_fallback', False):
            color = (0, 255, 255)  # amarelo - reconhecido por fallback
        else:
            color = (0, 255, 0)  # verde - reconhecido pelo EasyOCR

        top_left = (x - h // 2, y - h // 2)
        bottom_right = (x + h // 2, y + h // 2)

        cv2.rectangle(img, top_left, bottom_right, color, 2)

        if text:
            cv2.putText(img, str(text), (top_left[0], top_left[1] - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1, cv2.LINE_AA)
            cv2.putText(img, f"C: {conf}", (top_left[0], bottom_right[1] + 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1, cv2.LINE_AA)

    if scale != 1.0:
        img = cv2.resize(img, (0, 0), fx=scale, fy=scale)

    cv2.imwrite(output_path, img)

