# -*- coding: utf-8 -*-
"""
ocr_segmented.py
Reconhecimento de dígitos a partir de boxes + agrupamento sequencial por posição.

- recognize_digits           : OCR por crop (PaddleOCR), com fallbacks rápidos
- recognize_digits_batched   : OCR em lotes (PaddleOCR), mais rápido para muitos boxes
- group_digits_by_position   : agrupamento sequencial (1..4 dígitos), com identificação do decimal

Observações:
- Requer PaddleOCR instalado:
    pip install paddlepaddle paddleocr
  (ou paddlepaddle-gpu se houver GPU compatível)

- Para uso totalmente offline, defina (antes de importar PaddleOCR):
    import os
    os.environ["PADDLEOCR_HOME"] = r"C:\HydroVectorizer\paddle_models"
"""

import os
import re
import cv2
import numpy as np
import pandas as pd

# ==============================
# Inicialização do PaddleOCR
# ==============================
try:
    from paddleocr import PaddleOCR
except ImportError as _e:
    raise ImportError(
        "PaddleOCR não encontrado. Instale com:\n"
        "  pip install paddlepaddle paddleocr\n"
        "ou (GPU):\n"
        "  pip install paddlepaddle-gpu paddleocr\n"
    ) from _e

# Você pode sobrescrever via variável de ambiente antes de importar este módulo:
# os.environ["PADDLEOCR_HOME"] = r"C:\HydroVectorizer\paddle_models"

# Ajuste use_gpu=True se houver CUDA disponível
reader = PaddleOCR(
    use_angle_cls=False,   # não tentar rotação (nossos boxes já estão alinhados)
    lang='en',             # latin (funciona bem para dígitos)
#    lang='en_number',             # modelo focado em dígitos - n~ao reconheceu
#    det=False,             # só reconhecimento (a detecção já é feita na etapa 1)
#    rec=True,
#    use_gpu=False,         # troque para True se tiver GPU com paddlepaddle-gpu instalado
#    show_log=False
    device='cpu'
)


# =====================================================================
# Função: recognize_digits (OCR por crop, sequencial)
# =====================================================================
def recognize_digits(img_gray, boxes, pad=3, conf_min_heuristic=0.35):
    """
    Reconhece dígitos usando PaddleOCR, 1 crop por vez (sequencial).
    Aplica fallbacks leves (geométricos) somente quando OCR falha ou conf < conf_min_heuristic.

    Parâmetros
    ---------
    img_gray : np.ndarray (HxW), imagem em tons de cinza
    boxes    : list[(x,y,w,h)]
    pad      : int, padding em torno do box para o crop do OCR
    conf_min_heuristic : float, confiança mínima para dispensar fallbacks

    Retorna
    -------
    DataFrame com colunas:
      ['raw_text','digit','center_x','center_y','height','confidence','ocr_fallback']
    """
    recognized = []
    if boxes is None or len(boxes) == 0:
        return pd.DataFrame(columns=[
            'raw_text','digit','center_x','center_y','height','confidence','ocr_fallback'
        ])

    H, W = img_gray.shape[:2]

    for (x, y, w, h) in boxes:
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(W, x + w + pad)
        y2 = min(H, y + h + pad)
        crop = img_gray[y1:y2, x1:x2]

        # Normaliza para altura ~32 px (ajuda o recognizer)
        ch, cw = crop.shape[:2]
        if ch > 0 and cw > 0:
            scale = 32.0 / max(8.0, float(ch))
            nh, nw = max(8, int(round(ch * scale))), max(6, int(round(cw * scale)))
            crop = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_LINEAR)

        # PaddleOCR: det=False => passa lista ou imagem única
        try:
            results = reader.ocr(crop, det=False, rec=True)
        except Exception:
            results = []

        text, conf, digit, ocr_fallback = '', 0.0, None, False

        # Formatos típicos: [[('7', 0.98)]] ou [[ ((coords), ('7',0.98)) ]]
        if results and isinstance(results, list) and len(results) > 0:
            head = results[0]
            if isinstance(head, list) and len(head) > 0:
                cand = head[0]
                # Caso simples: ('7', 0.98)
                if isinstance(cand, (list, tuple)) and len(cand) == 2 and isinstance(cand[0], str):
                    text = cand[0]; conf = float(cand[1])
                # Caso com coords: ((coords), ('7',0.98))
                elif isinstance(cand, (list, tuple)) and len(cand) == 2 and isinstance(cand[1], (list, tuple)) and isinstance(cand[1][0], str):
                    text = cand[1][0]; conf = float(cand[1][1])
                else:
                    # tenta encontrar um par (str, float)
                    for t in head:
                        if isinstance(t, (list, tuple)) and len(t) >= 2 and isinstance(t[0], str):
                            text = t[0]; conf = float(t[1])
                            break

            # Saneamento simples
            text = str(text).strip()
            if text in ['ll', 'Il', 'Ii', 'li']:
                text = '11'; conf = max(conf, 0.7); ocr_fallback = True
            if text in ['/', 'l', 'L', 'i', 'I', '!', '|']:
                text = '1'; conf = max(conf, 0.7); ocr_fallback = True
            if text == "'":
                text = '0'; conf = max(conf, 0.7); ocr_fallback = True
            text = text[:1] if text else ''
            if text.isdigit():
                digit = int(text)

        # Fallbacks só se falhou ou confiança baixa
        if (not digit) or (conf < conf_min_heuristic):
            # Fallback 1: detectar "1" por geometria
            contours, _ = cv2.findContours(crop, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                if len(cnt) >= 4:
                    rect = cv2.minAreaRect(cnt)
                    (_, _), (w_rect, h_rect), angle = rect
                    aspect = (h_rect + 1e-5) / (w_rect + 1e-5)
                    if w_rect < 12 and h_rect > 9 and aspect > 1.5:
                        angle = abs(angle)
                        if angle < 20 or angle > 70:
                            text = '1'; digit = 1; conf = max(conf, 0.5); ocr_fallback = True
                            break

        if (not digit) or (conf < conf_min_heuristic):
            # Fallback 2: HoughLinesP (rápido)
            lines = cv2.HoughLinesP(crop, 1, np.pi/180, threshold=12, minLineLength=9, maxLineGap=2)
            if lines is not None and 1 <= len(lines) <= 3:
                angs = [abs(np.degrees(np.arctan2(y2 - y1, x2 - x1))) for [[x1l, y1l, x2l, y2l]] in lines]
                if len(angs) > 0:
                    med = np.median(angs)
                    if 40 < med < 135:
                        text = '1'; digit = 1; conf = max(conf, 0.45); ocr_fallback = True

        if (not digit) or (conf < conf_min_heuristic):
            # Fallback 3: tentativa de "7" ou "4"
            contours, _ = cv2.findContours(crop, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                _, _, w_cnt, h_cnt = cv2.boundingRect(cnt)
                aspect_ratio = (h_cnt + 1e-5) / (w_cnt + 1e-5)
                inv_aspect   = (w_cnt + 1e-5) / (h_cnt + 1e-5)
                if inv_aspect > 1.5 and h_cnt > 10:
                    text = '7'; digit = 7; conf = max(conf, 0.4); ocr_fallback = True; break
                elif 0.5 < aspect_ratio < 1.5 and 10 < h_cnt < 60:
                    text = '4'; digit = 4; conf = max(conf, 0.4); ocr_fallback = True; break

        if text is None:
            text = ''

        recognized.append({
            'raw_text': text,
            'digit': (int(text) if text.isdigit() else None),
            'center_x': x + w / 2.0,
            'center_y': y + h / 2.0,
            'height': h,
            'confidence': float(conf),
            'ocr_fallback': bool(ocr_fallback)
        })

    df = pd.DataFrame(recognized)
    # debug opcional:
    try:
        df.to_csv("ocr_raw_debug.csv", index=False)
    except Exception:
        pass
    return df


# =====================================================================
# Função: recognize_digits_batched (OCR em lotes)
# =====================================================================
def recognize_digits_batched(img_gray, boxes,
                             batch_size=128,
                             pad=2,
                             conf_min_heuristic=0.35):
    """
    Versão batched do OCR com PaddleOCR.
    - Processa crops em lotes (batch_size) para reduzir overhead de chamadas.
    - Mantém o mesmo formato de retorno da versão sequencial.

    Parâmetros:
      img_gray : np.ndarray (HxW), imagem em tons de cinza
      boxes    : list[(x,y,w,h)]
      batch_size : int, tamanho do lote para OCR
      pad        : int, margem ao redor de cada box
      conf_min_heuristic : float, confiança mínima para dispensar fallbacks

    Retorna:
      DataFrame com colunas:
      ['raw_text','digit','center_x','center_y','height','confidence','ocr_fallback']
    """
    recognized = []
    if boxes is None or len(boxes) == 0:
        return pd.DataFrame(columns=[
            'raw_text','digit','center_x','center_y','height','confidence','ocr_fallback'
        ])

    H, W = img_gray.shape[:2]

    # 1) Preparar crops e metadados
    crops, meta = [], []  # meta: (x, y, w, h, x1, y1)
    for (x, y, w, h) in boxes:
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(W, x + w + pad)
        y2 = min(H, y + h + pad)
        crop = img_gray[y1:y2, x1:x2]

        ch, cw = crop.shape[:2]
        if ch > 0 and cw > 0:
            scale = 32.0 / max(8.0, float(ch))
            nh, nw = max(8, int(round(ch * scale))), max(6, int(round(cw * scale)))
            crop = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_LINEAR)

        crops.append(crop)
        meta.append((x, y, w, h, x1, y1))

    # 2) Rodar OCR em lotes
    ocr_results = []
    for i in range(0, len(crops), batch_size):
        batch = crops[i:i+batch_size]
        try:
            res = reader.ocr(batch, det=False, rec=True)  # aceita lista de imagens
        except Exception:
            # fallback: processa um a um (raro)
            res = [reader.ocr(b, det=False, rec=True) for b in batch]

        # normaliza formato para lista
        for item in res:
            ocr_results.append(item if isinstance(item, list) else [])

    # 3) Interpretar resultados + fallbacks quando necessário
    for idx, res in enumerate(ocr_results):
        x, y, w, h, x1, y1 = meta[idx]
        crop = crops[idx]

        text = ''
        conf = 0.0
        digit = None
        ocr_fallback = False

        if res and len(res) > 0:
            head = res[0]
            # Padrão: [('7', 0.98)] OU [((coords), ('7',0.98))]
            if isinstance(head, (list, tuple)) and len(head) > 0:
                cand = head[0]
                if isinstance(cand, (list, tuple)) and len(cand) == 2 and isinstance(cand[0], str):
                    text, conf = cand[0], float(cand[1])
                elif isinstance(cand, (list, tuple)) and len(cand) == 2 and isinstance(cand[1], (list, tuple)) and isinstance(cand[1][0], str):
                    text, conf = cand[1][0], float(cand[1][1])
                else:
                    for t in head:
                        if isinstance(t, (list, tuple)) and len(t) >= 2 and isinstance(t[0], str):
                            text, conf = t[0], float(t[1])
                            break

            # saneamento simples
            text = str(text).strip()
            if text in ['ll', 'Il', 'Ii', 'li']:
                text = '11'; conf = max(conf, 0.7); ocr_fallback = True
            if text in ['/', 'l', 'L', 'i', 'I', '!', '|']:
                text = '1'; conf = max(conf, 0.7); ocr_fallback = True
            if text == "'":
                text = '0'; conf = max(conf, 0.7); ocr_fallback = True
            text = text[:1] if text else ''
            if text.isdigit():
                digit = int(text)

        # Fallbacks só se falhou ou conf baixa
        if (not digit) or (conf < conf_min_heuristic):
            contours, _ = cv2.findContours(crop, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                if len(cnt) >= 4:
                    rect = cv2.minAreaRect(cnt)
                    (_, _), (w_rect, h_rect), angle = rect
                    aspect = (h_rect + 1e-5) / (w_rect + 1e-5)
                    if w_rect < 12 and h_rect > 9 and aspect > 1.5:
                        angle = abs(angle)
                        if angle < 20 or angle > 70:
                            text = '1'; digit = 1; conf = max(conf, 0.5); ocr_fallback = True
                            break

        if (not digit) or (conf < conf_min_heuristic):
            lines = cv2.HoughLinesP(crop, 1, np.pi/180, threshold=12, minLineLength=9, maxLineGap=2)
            if lines is not None and 1 <= len(lines) <= 3:
                angs = [abs(np.degrees(np.arctan2(y2 - y1, x2 - x1))) for [[x1l, y1l, x2l, y2l]] in lines]
                if len(angs) > 0:
                    med = np.median(angs)
                    if 40 < med < 135:
                        text = '1'; digit = 1; conf = max(conf, 0.45); ocr_fallback = True

        if (not digit) or (conf < conf_min_heuristic):
            contours, _ = cv2.findContours(crop, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                _, _, w_cnt, h_cnt = cv2.boundingRect(cnt)
                aspect_ratio = (h_cnt + 1e-5) / (w_cnt + 1e-5)
                inv_aspect   = (w_cnt + 1e-5) / (h_cnt + 1e-5)
                if inv_aspect > 1.5 and h_cnt > 10:
                    text = '7'; digit = 7; conf = max(conf, 0.4); ocr_fallback = True; break
                elif 0.5 < aspect_ratio < 1.5 and 10 < h_cnt < 60:
                    text = '4'; digit = 4; conf = max(conf, 0.4); ocr_fallback = True; break

        if text is None:
            text = ''

        recognized.append({
            'raw_text': text,
            'digit': (int(text) if text.isdigit() else None),
            'center_x': x + w / 2.0,
            'center_y': y + h / 2.0,
            'height': h,
            'confidence': float(conf),
            'ocr_fallback': bool(ocr_fallback)
        })

    df = pd.DataFrame(recognized)
    # debug opcional:
    try:
        df.to_csv("ocr_raw_debug_batched.csv", index=False)
    except Exception:
        pass
    return df


# =====================================================================
# Função: group_digits_by_position (agrupamento sequencial + decimal)
# =====================================================================
def group_digits_by_position(digits_df: pd.DataFrame,
                             tol_x: float = 30.0,
                             tol_y: float = 6.0,
                             # Regras do decimal
                             max_depth_for_decimal: float = 31.0,   # ajuste conforme norma interna
                             height_ratio_decimal_max: float = 0.95, # decimal deve ser menor que inteiros (ex.: 0.95)
                             min_vertical_drop_decimal: float = 0.10 # fração da altura média dos inteiros (ex.: 0.10)
                             ) -> pd.DataFrame:
    """
    Agrupamento sequencial por X (1..4 dígitos):
      - Ordena por center_x.
      - Para cada i (não usado), tenta formar um grupo com até 4 dígitos:
          * candidato j precisa obedecer:
              (x[j] - x_last) <= tol_x
              abs(y[j] - y_first) <= tol_y
          * para no primeiro que viola X (a partir do último anexado).
      - Grupo fecha com 1..4 dígitos (no máx. 4 -> até 6000).
      - Decimal (se houver) é SEMPRE o último dígito do grupo (direita), sujeito às regras.
      - Um dígito pertence a um único grupo (não reabre grupo do 2º/3º).

    Saída: DataFrame com colunas:
      ['pixel_x','pixel_y','depth','confidence','x_min','x_max','y_min','y_max']
    """
    cols_out = ['pixel_x','pixel_y','depth','confidence','x_min','x_max','y_min','y_max']
    if digits_df is None or digits_df.empty:
        return pd.DataFrame(columns=cols_out)

    # Preparação
    df = digits_df.copy()
    for c in ('center_x','center_y','height','confidence'):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')

    def _is_digit_ok(v):
        if pd.isna(v): return False
        s = str(v).strip()
        return len(s) == 1 and s.isdigit()

    df = df[df['digit'].apply(_is_digit_ok)].reset_index(drop=True)
    if df.empty:
        return pd.DataFrame(columns=cols_out)

    # Ordena por X
    df = df.sort_values('center_x').reset_index(drop=True)

    x = df['center_x'].to_numpy(float)
    y = df['center_y'].to_numpy(float)
    h = df['height'  ].to_numpy(float)
    d = df['digit'   ].astype(str).to_numpy()
    c = df['confidence'].to_numpy(float) if 'confidence' in df.columns else np.zeros(len(df), float)

    n = len(df)
    used = np.zeros(n, dtype=bool)
    out = []

    i = 0
    while i < n:
        if used[i]:
            i += 1
            continue

        # inicia grupo com o dígito i
        group_idx = [i]
        used[i] = True

        x_first = x[i]
        y_first = y[i]
        x_last  = x[i]   # a tolerância em X é sempre em relação ao ÚLTIMO anexado

        # tenta anexar até 3 candidatos (grupo máx 4 dígitos)
        j = i + 1
        while j < n and len(group_idx) < 4:
            # se já passou da janela em X (desde o último), podemos parar
            if (x[j] - x_last) > tol_x:
                break

            if (not used[j]) and (abs(y[j] - y_first) <= tol_y) and ((x[j] - x_last) >= 0):
                # anexa
                group_idx.append(j)
                used[j] = True
                x_last = x[j]  # janela passa a considerar o novo último
                j += 1
            else:
                # não serve este j → tenta o próximo (enquanto dentro de tol_x vs x_last)
                j += 1

        # Constrói valor respeitando regra do decimal no último dígito
        def _compose_and_push(int_idx, dec_idx):
            """int_idx = lista de índices para parte inteira; dec_idx = lista (0 ou 1) p/ decimal."""
            if not int_idx:
                return

            int_str = "".join([d[k] for k in int_idx])
            try:
                int_val = int(int_str)
            except ValueError:
                return

            if dec_idx:
                dec_str = "".join([d[k] for k in dec_idx])
                try:
                    val = float(f"{int_str}.{dec_str}")
                except ValueError:
                    val = float(int_val)
            else:
                val = float(int_val)

            used_all = int_idx + dec_idx
            xs = x[used_all]; ys = y[used_all]; hs = h[used_all]; cs = c[used_all]
            pixel_x = float(xs.mean())
            pixel_y = float(ys.mean())
            x_min = float(np.min(xs - hs/2.0))
            x_max = float(np.max(xs + hs/2.0))
            y_min = float(np.min(ys - hs/2.0))
            y_max = float(np.max(ys + hs/2.0))
            conf  = float(cs.mean()) if cs.size else 0.0

            out.append({
                'pixel_x': pixel_x,
                'pixel_y': pixel_y,
                'depth':   val,
                'confidence': conf,
                'x_min': x_min, 'x_max': x_max, 'y_min': y_min, 'y_max': y_max
            })

        # Decisão do decimal conforme o tamanho do grupo
        L = len(group_idx)
        if L == 1:
            _compose_and_push([group_idx[0]], [])
        elif L == 2:
            k1, k2 = group_idx
            int_part = int(d[k1])  # só um dígito na parte inteira
            # critérios de decimal para o 2º:
            is_smaller = (h[k2] <= height_ratio_decimal_max * h[k1])
            vertical_drop = (y[k2] - y[k1])  # positivo = mais abaixo
            is_lower = (vertical_drop >= min_vertical_drop_decimal * h[k1])
            can_have_decimal = (int_part <= max_depth_for_decimal)
            if is_smaller and is_lower and can_have_decimal:
                _compose_and_push([k1], [k2])
            else:
                _compose_and_push([k1, k2], [])
        elif L == 3:
            k1, k2, k3 = group_idx
            int_part = int(d[k1] + d[k2])  # dois dígitos de inteiro
            mean_h12 = 0.5 * (h[k1] + h[k2])
            mean_y12 = 0.5 * (y[k1] + y[k2])
            is_smaller = (h[k3] <= height_ratio_decimal_max * mean_h12)
            vertical_drop = (y[k3] - mean_y12)
            is_lower = (vertical_drop >= min_vertical_drop_decimal * mean_h12)
            can_have_decimal = (int_part <= max_depth_for_decimal)
            if is_smaller and is_lower and can_have_decimal:
                _compose_and_push([k1, k2], [k3])
            else:
                _compose_and_push([k1, k2, k3], [])
        else:  # L == 4
            _compose_and_push(group_idx, [])

        i += 1

    if not out:
        return pd.DataFrame(columns=cols_out)

    out_df = pd.DataFrame(out, columns=cols_out)
    # Tipagem coerente
    out_df[cols_out] = out_df[cols_out].apply(pd.to_numeric, errors='coerce')
    return out_df
