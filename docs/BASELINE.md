# Received baseline

The seven source uploads are preserved byte for byte in `legacy/`. See
`source_manifest.json` for original names, repository paths, and SHA-256 hashes.

- `legacy/v3_1/main.py` is the previously integrated Tkinter workflow.
- `legacy/v4_prototype/main.py` is an interface and segmentation prototype;
  its OCR and export actions are placeholders.
- `legacy/tools/create_rectangles.py` is a geometry experiment.

The author reports 100% accuracy on `21300plano.tif`, followed by failures on
other charts. No reviewed reference XYZ or original environment lockfile was
provided. Record that result as author-reported, not independently reproduced.
The original v3.1 application also references splash/logo assets not included
in the source uploads. Its imports eagerly initialize PaddleOCR.

## Development scope

1. Published nautical chart rasters: reproduce the baseline, compare OCR models,
   validate complete depth values and pixel/geographic positions, and export XYZ.
2. Historical hydrographic field sheets: a separate later module, with support
   for handwriting, dense sounding lines, nonuniform illumination, annotations,
   large-image windowing, and source-datum transformations.

The supplied `ortofb_geo-supdir.tif` is a cropped extract (approximately 8.46 MB),
not the approximately 135 MB full field sheet described by the author.
It is tagged Corrego Alegre 1970-72 / UTM zone 24S. Do not assume WGS84 or use
the raster chart decimal-depth limit as a rule for historical field sheets.

Input rasters and model weights stay outside Git. Tests and experiment reports
must distinguish synthetic regression checks, crop-level OCR checks, and complete
chart extraction accuracy. A crop recognition score is not full-chart accuracy.
