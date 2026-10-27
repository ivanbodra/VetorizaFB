# Medidas das caixas de cartas náuticas

Esta exportação serve para estudar os limites de largura e altura dos segmentos de uma CN. Ela não executa OCR, não altera o projeto e não cria XYZ.

1. Abra a CN e ajuste o modo, a claridade e os demais parâmetros de preparação.
2. Se quiser estudar apenas um trecho, selecione a área antes de preparar.
3. Clique em **Preparar**.
4. Use **Arquivo → Exportar medidas das caixas…** e salve o CSV.
5. Para comparar modos ou parâmetros, repita em arquivos CSV separados.

Cada linha representa um contorno encontrado **antes** da exclusão por tamanho ou cor. As dimensões e posições estão em pixels da imagem original. `selection` indica `mantida`, `descartada_tamanho` ou `descartada_cor` segundo os parâmetros aplicados; é uma decisão dos filtros, **não** uma identificação de dígito. `size_reasons` informa quais limites foram ultrapassados. `touches_roi_border` marca contornos cortados pela borda da área processada. As colunas da carta, área e configuração repetem o contexto para que cada CSV possa ser analisado separadamente.

O nome da carta aparece no arquivo; o caminho completo, a imagem, os resultados do OCR e as decisões de revisão não são exportados. Para estudar os picos de dimensões, compartilhe o CSV de uma **CN impressa**, não de uma folha de bordo. Mantenha arquivos distintos para cada carta e configuração.
