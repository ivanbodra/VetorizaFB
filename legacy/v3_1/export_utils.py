# export_utils.py
# Utilitários de exportação para o HydroVectorizer / VetorizaFB
# - Escolha automática das colunas de coordenadas (lon/lat, crs_x/crs_y, pixel_x/pixel_y)
# - Exportação XYZ: X Y Z Conf
# - Exportação de LOG com tempos, projeção e formato de coordenadas
# - Exportação de .info (CARIS) com CoordinateFormat coerente

from datetime import datetime

def _pick_xy_columns(df):
    """
    Escolhe as colunas de coordenadas por prioridade.
    Retorna (x_col, y_col, coord_fmt), onde coord_fmt ∈ {'DecimalDegrees','Projected','Pixels'}.
    """
    cols = set(df.columns)

    # 1) Preferir lon/lat (WGS84)
    if {'lon', 'lat'}.issubset(cols):
        return 'lon', 'lat', 'DecimalDegrees'
    if {'longitude', 'latitude'}.issubset(cols):
        return 'longitude', 'latitude', 'DecimalDegrees'

    # 2) Coordenadas no CRS do raster (metros, UTM/Mercator, etc.)
    if {'crs_x', 'crs_y'}.issubset(cols):
        return 'crs_x', 'crs_y', 'Projected'

    # 3) Fallback: pixels (útil para debug)
    if {'pixel_x', 'pixel_y'}.issubset(cols):
        return 'pixel_x', 'pixel_y', 'Pixels'

    # 4) Último recurso: tentar nomes genéricos
    if {'x', 'y'}.issubset(cols):
        return 'x', 'y', 'Projected'
    if {'X', 'Y'}.issubset(cols):
        return 'X', 'Y', 'Projected'

    raise KeyError(
        "Não encontrei colunas de coordenadas compatíveis. "
        "Use lon/lat, crs_x/crs_y ou pixel_x/pixel_y."
    )


def export_xyz(df, path):
    """
    Escreve arquivo XYZ com 4 colunas: X Y Z Confidence
    Detecta automaticamente quais colunas usar para X e Y.
    """
    if df is None or df.empty:
        raise ValueError("DataFrame vazio ao exportar XYZ.")

    x_col, y_col, _coord_fmt = _pick_xy_columns(df)

    with open(path, 'w', encoding='utf-8') as f:
        for _, row in df.iterrows():
            x = row[x_col]
            y = row[y_col]
            z = float(row['depth'])
            conf = float(row['confidence'])
            f.write(f"{x} {y} {z:.2f} {conf:.2f}\n")


def export_log(df, path, projection,
               tempo_preprocess=None,
               tempo_boxes=None,
               tempo_ocr=None,
               tempo_agrupamento=None,
               tempo_geo=None,
               tempo_total=None,
               usuario=None,
               nome_arquivo=None):
    """
    Exporta um log textual com informações de execução.
    Agora inclui o CoordinateFormat e as colunas X/Y detectadas.
    """
    # Identificar o formato de coordenadas
    try:
        x_col, y_col, coord_fmt = _pick_xy_columns(df)
    except Exception:
        x_col, y_col, coord_fmt = ("?", "?", "?")

    with open(path, 'w', encoding='utf-8') as log:
        log.write(f"Data e hora da exportação: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        if nome_arquivo:
            log.write(f"Arquivo de entrada: {nome_arquivo}\n")
        if usuario:
            log.write(f"Usuário: {usuario}\n")

        log.write(f"Total de profundidades detectadas: {len(df)}\n")
        if 'confidence' in df.columns:
            try:
                low_conf = (df['confidence'].astype(float) < 0.5).sum()
            except Exception:
                low_conf = (df['confidence'] < 0.5).sum()
            log.write(f"Profundidades com baixa confiança (< 0.5): {low_conf}\n")

        # Projeção e formato de coordenadas
        log.write(f"Projeção geográfica (WKT/CRS): {projection}\n")
        log.write(f"Colunas X/Y exportadas: {x_col}, {y_col}\n")
        log.write(f"CoordinateFormat detectado: {coord_fmt}\n")

        # Tempos de execução
        if tempo_preprocess is not None:
            log.write(f"Tempo de pré-processamento: {tempo_preprocess:.2f} segundos\n")
        if tempo_boxes is not None:
            log.write(f"Tempo de segmentação (boxes): {tempo_boxes:.2f} segundos\n")
        if tempo_ocr is not None:
            log.write(f"Tempo de OCR: {tempo_ocr:.2f} segundos\n")
        if tempo_agrupamento is not None:
            log.write(f"Tempo de agrupamento: {tempo_agrupamento:.2f} segundos\n")
        if tempo_geo is not None:
            log.write(f"Tempo de georreferenciamento: {tempo_geo:.2f} segundos\n")
        if tempo_total is not None:
            log.write(f"Tempo total de execução: {tempo_total:.2f} segundos\n")


def export_info_file(df, path):
    """
    Gera o .info compatível com o CARIS.
    Detecta o formato de coordenadas conforme as colunas presentes no DF:
      - lon/lat            -> DecimalDegrees
      - crs_x/crs_y        -> Projected
      - pixel_x/pixel_y    -> Projected (fallback; Pixels não é aceito no .info)
    """
    if df is None or df.empty:
        raise ValueError("DataFrame vazio ao gerar .info.")

    # Identifica o formato de coordenadas
    _, _, coord_fmt = _pick_xy_columns(df)
    if coord_fmt == 'Pixels':
        coord_fmt = 'Projected'

    with open(path, 'w', encoding='utf-8') as info_file:
        info_file.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        info_file.write('<cif:FormatInformation xmlns:cif="http://www.caris.com/cif/2.2" version="2.2">\n')
        info_file.write('  <cif:SkipLines>0</cif:SkipLines>\n')
        info_file.write('  <cif:Type>Elevation</cif:Type>\n')
        info_file.write('  <cif:Delimited>\n')
        info_file.write('    <cif:Delimiter>space</cif:Delimiter>\n')
        info_file.write('    <cif:Column>\n')
        info_file.write('      <cif:AttributeName>X</cif:AttributeName>\n')
        info_file.write('      <cif:Multiplier>1</cif:Multiplier>\n')
        info_file.write(f'      <cif:CoordinateFormat>{coord_fmt}</cif:CoordinateFormat>\n')
        info_file.write('      <cif:DataType>DOUBLE</cif:DataType>\n')
        info_file.write('      <cif:Index>0</cif:Index>\n')
        info_file.write('    </cif:Column>\n')
        info_file.write('    <cif:Column>\n')
        info_file.write('      <cif:AttributeName>Y</cif:AttributeName>\n')
        info_file.write('      <cif:Multiplier>1</cif:Multiplier>\n')
        info_file.write(f'      <cif:CoordinateFormat>{coord_fmt}</cif:CoordinateFormat>\n')
        info_file.write('      <cif:DataType>DOUBLE</cif:DataType>\n')
        info_file.write('      <cif:Index>1</cif:Index>\n')
        info_file.write('    </cif:Column>\n')
        info_file.write('    <cif:Column>\n')
        info_file.write('      <cif:AttributeName>Z</cif:AttributeName>\n')
        info_file.write('      <cif:Multiplier>1</cif:Multiplier>\n')
        info_file.write('      <cif:Orientation>down</cif:Orientation>\n')
        info_file.write('      <cif:Unit>m</cif:Unit>\n')
        info_file.write('      <cif:DataType>DOUBLE</cif:DataType>\n')
        info_file.write('      <cif:Index>2</cif:Index>\n')
        info_file.write('    </cif:Column>\n')
        info_file.write('    <cif:Column>\n')
        info_file.write('      <cif:AttributeName>Confidence</cif:AttributeName>\n')
        info_file.write('      <cif:Multiplier>1</cif:Multiplier>\n')
        info_file.write('      <cif:DataType>DOUBLE</cif:DataType>\n')
        info_file.write('      <cif:Index>3</cif:Index>\n')
        info_file.write('    </cif:Column>\n')
        info_file.write('  </cif:Delimited>\n')
        info_file.write('</cif:FormatInformation>\n')
