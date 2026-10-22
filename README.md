# VetorizaFB

Extract georeferenced sounding points and depth values from nautical chart rasters.

The initial scope is published raster nautical charts (GeoTIFF). Historical photographed and orthorectified hydrographic field sheets are a separate future module.

## Baseline

The uploaded v3.1 implementation and v4 interface prototype are preserved under `legacy/`, without modifications. The v4 prototype does not yet integrate OCR and export. The author reports 100% accuracy on `21300plano.tif`; this result has not been independently reproduced and does not establish performance on other charts.

See [baseline and scope](docs/BASELINE.md) and [source checksums](docs/source_manifest.json).

Input rasters and downloaded model weights remain external to Git.

## Experimental OCR update

The `ocr-modernization` branch adds a standalone extraction core, a command-line
runner and a small Tkinter desktop runner. It uses PaddleOCR 3.x
`TextRecognition`, with selectable PP-OCRv6 small/medium and PP-OCRv5 server
recognizers. It does not require QGIS or PyQt.

**This version generates unreviewed candidates.** It still accepts contour
labels, may miss characters touching lines, and cannot guarantee correct depths
or exact sounding positions. See the [measured results](docs/EXPERIMENTS.md).

## Install

Use a separate Python 3.12 environment, outside the QGIS Python installation.
The CPU dependencies used in the experiment are pinned in `pyproject.toml`;
other supporting dependencies have version ranges.

```powershell
git clone --branch ocr-modernization https://github.com/ivanbodra/VetorizaFB.git
cd VetorizaFB
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[ocr,test]"
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\vetorizafb-gui.exe
```

On Linux, use `python3 -m venv .venv`, then `.venv/bin/python` and
`.venv/bin/vetorizafb-gui`. The desktop runner needs Tkinter (often installed as
`python3-tk` on Linux). CPU extraction was exercised on Linux/Python 3.12;
the Windows installation and desktop window have not yet been validated.

The first extraction downloads the selected model through PaddleOCR. For an
offline machine, download the official inference model on a connected machine,
extract it, and select the directory containing `inference.json`,
`inference.pdiparams` and `inference.yml`. Pass it as `--model-dir` in the CLI.
See the [official model catalogue](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/module_usage/text_recognition.en.md).

## Run

```powershell
.venv\Scripts\vetorizafb.exe "C:\cartas\1410geotiff.tif" --output-dir "C:\cartas\results\1410" --model PP-OCRv6_small_rec
```

The default configuration reads DPI from the TIFF and scales segmentation
dimensions relative to 600 dpi. It retains the original raster coordinates.
An image with missing DPI needs `--config path/to/config.json`; use
`configs/chart_600dpi.json` as a template and set its actual DPI. DPI scaling is
a starting point, not a substitute for calibration against font sizes and chart
content. `--target-crs EPSG:4326` is the default; X is longitude and Y latitude.
Use an appropriate projected target CRS when metre-based XY coordinates are
required. Input without a CRS is rejected.

Each extraction writes:

- `name.xyz`: exactly three space-separated columns, X Y depth, without a header.
- `name.csv`: coordinates, candidate bounding boxes, character IDs, confidence,
  decimal interpretation and `unreviewed` status.
- `name.digits.json`: all character OCR readings, including rejected text.
- `name.metadata.json`: input checksum, CRS, parameters, package versions and counts.
- `name.preview.jpg`: the complete chart with candidate boxes and depths.

Z preserves the chart's depth values in metres, positive down; no vertical datum
conversion or interpolation is performed. The point is the detected text's
bounding-box centre, a geometric proxy that has not been validated against true
sounding anchors. Review the preview and CSV before using XYZ. The current
desktop runner displays the preview but does not edit or approve candidates.

## Reproduce the crop comparison

Keep the three input files together outside Git, with their original filenames.

```powershell
.venv\Scripts\python.exe scripts/benchmark_crops.py --data-dir "C:\cartas" --model PP-OCRv6_small_rec --output results/v6-small-crops.json
```

Repeat with `PP-OCRv6_medium_rec` and `PP-OCRv5_server_rec`. The script evaluates
the fixed regions in `docs/experiments/crop_reference.json`, using two
segmentation modes and two grouping modes. Reports include raw readings and
checksums. Full-chart accuracy still needs an independently reviewed reference
set, including missing points and false positives.

## Remaining work

1. Build a reviewed reference set across chart styles; measure detection precision,
   recall, exact depth and geographic error separately.
2. Detect sounding groups and distinguish them from contour labels, coordinates,
   place names and hazard annotations. Evaluate a trained detector on held-out charts.
3. Add candidate review/correction and reliable anchors, then validate final XYZ.
4. Add windowed processing before supporting large historical field sheets.
   The current runner loads a whole raster into memory.

Historical FB handwriting requires separate annotations and decimal conventions;
the raster-chart `decimal_max_integer=31` heuristic must not be reused without
validation. No FB recognition accuracy is claimed in this update.
