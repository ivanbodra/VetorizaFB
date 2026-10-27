# VetorizaFB 5.0.0

PySide6 desktop with a separate Folha de bordo mode. See [installation, workflow and validation](docs/V5_DESKTOP.md).

# VetorizaFB

Extract georeferenced sounding candidates from raster nautical charts and review
them before XYZ export. Historical handwritten hydrographic field sheets are a
separate future module.

## Previous desktop: 4.0.6 (retained classic interface)

Branch `ocr-modernization` / [PR #1](https://github.com/ivanbodra/VetorizaFB/pull/1).
The original seven uploaded files remain byte-for-byte preserved under `legacy/`
on `main` and this branch. The historical EasyOCR 3.0.1 executable is not fully
represented by those uploads; the v4 interface prototype contains OCR/export
placeholders. This is an experimental development update, not an established
replacement with proven 100% chart accuracy.

Version 4.0 adds live size-filter preview, native-pixel measurement, offline
Portuguese help and About, while retaining the PaddleOCR 3.x core and staged tools:

- Separate segmentation, OCR, grouping and export stages with valid-stage reuse.
- Editable DPI, thresholds, blur/dilation, size filters, crop padding, batch size,
  confidence, spacing and decimal interpretation, plus JSON parameter profiles.
- Original/mask/boxes/OCR/soundings layers, zoom, pan, ROI selection, contour-size
  histograms and character-crop inspection.
- Optional yellow-background box rejection using signed R-B/G-B differences and
  a configurable background fraction, with a separate rejected-box layer.
- Directed rereading of possible narrow `1` glyphs, enabled by default, plus an
  optional broader retry. Failed directed reads get a final isolated-component
  crop to remove neighbouring ink. All readings preserve real model scores.
- Arrow navigation with following/size-based zoom, Shift range selection,
  Ctrl+click toggles, visible-row selection and batch approval/exclusion.
  In the chart/table, Ctrl+A approves, Ctrl+X rejects and Ctrl+E edits one value;
  Ctrl+Shift+A selects all visible rows. Text-entry shortcuts keep their scope.
- Correction, repositioning, manual insertion, rejection and explicit acceptance
  of points, with a saved decision trail and resumable review projects.
- Direct insertion/move buttons, numeric pixel-position editing and incremental
  offsets for all or selected points, in image pixels or projected source-grid
  metres. Preview and full-batch validation precede changes; moved approvals
  become pending and rejected points remain rejected.
- Separate candidate and accepted-only XYZ bundles; staged writes, completion
  metadata and output hashes.
- Y-bucket indexing that preserves greedy group decisions on the regression
  corpus while reducing repeated scans through vertical columns.

Read the [current user guide](docs/USER_GUIDE.md) and
[colour-filter/position-tool validation](docs/COLOR_AND_POSITIONS.md).
Earlier reports cover [0.3 keyboard/one-retry validation](docs/REVIEW_AND_ONES.md),
[0.2 restoration](docs/RESTORATION.md), [initial OCR experiments](docs/EXPERIMENTS.md),
[0.1 grouping](docs/GROUPING_AUDIT.md) and [baseline scope](docs/BASELINE.md).

## Windows quick start

Use a separate 64-bit Python 3.12 environment outside QGIS. Start in the project
root containing `pyproject.toml`, not inside `legacy/v3_1`.

```powershell
git clone --branch ocr-modernization https://github.com/ivanbodra/VetorizaFB.git
cd VetorizaFB
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[ocr,test]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\vetorizafb-gui.exe
```

For an existing clone, preserve local changes, switch to `ocr-modernization`,
run `git pull --ff-only` and repeat installation into the root `.venv`. The window
must show **4.0.6**. Linux uses `.venv/bin/python`, `.venv/bin/vetorizafb-gui`
and a Tk display; use `xvfb-run -a python -m pytest -q` for headless GUI tests.
CPU PaddleOCR 3.7.0/PaddlePaddle 3.3.1 and OpenCV versions are pinned; supporting
dependencies have ranges. First use may retrieve weights, or select a matching
local official inference-model folder. No model weights or input rasters are
committed. No current packaged Windows installer is supplied.

Standalone entry points isolate wheel-provided GIS data from inherited PostGIS
PROJ paths, without changing system installations. See the guide for the
session-only pytest workaround and custom-GIS-data opt-out.

## CLI

```powershell
.\.venv\Scripts\vetorizafb.exe "C:\cartas\1822geotiff.tif" `
  --output-dir "C:\cartas\results\1822" `
  --model PP-OCRv6_small_rec `
  --config configs/chart_300dpi_retry.json
```

The example enables the broader experimental retry. Directed `1` retry is on by
default; broader retry is off. Without
`--config`, DPI comes from TIFF metadata. A custom configuration must specify
actual DPI; absent values use defaults. Target CRS defaults to EPSG:4326, with
X=longitude and Y=latitude; `--target-crs` selects another appropriate CRS.
Z is metres, positive down, with source vertical reference unchanged.

CLI outputs unreviewed XYZ/CSV, raw readings, metadata and preview. GUI exports
`.candidates` bundles (rejected points excluded) or `.reviewed` bundles containing
only explicitly accepted points. Both include `.review.json` decision history.
A source hash mismatch blocks project loading/export. Approval of a subset does
not establish complete chart coverage.

## Accuracy and limits

The five soundings in the user's screenshot were located in the original 21300
GeoTIFF: directed retry improves exact crop matches from 2/5 to 5/5, also confirmed
when processing the whole chart. On the earlier, separate development set it
matches 18/19 positive crops; both contour-label negatives remain false positives.
These are diagnostic samples, not a full-chart accuracy reference. Read the
[validation report](docs/REVIEW_AND_ONES.md) for scope and reproducible results.

The 0.3.1 isolated-component retry also restores an 11.9 previously read as 1.9
and an 11.1 read as 1.1. The four soundings in the follow-up screenshot match
their expected values in the native GeoTIFF tests. Marginal coordinate labels
and contour labels remain candidates for operator review; use a useful-area ROI
to omit margins when appropriate. See the [follow-up evidence](docs/REMAINING_ONES.md).

The automatic point anchor is the text-box centre and remains unverified against
cartographic anchors; a reviewer can reposition it. There is no trained sounding
classifier, automatic chart-frame mask, automatic line separation or tiled input
reader. The whole raster is held in RAM. Historical FB handwriting and decimal
conventions need independent annotations and validation.

Run meaningful regression tests and use complete independently reviewed charts
before asserting operational accuracy. Input files, model weights and locally
generated results stay outside Git; original source checksums are recorded in
[the manifest](docs/source_manifest.json).
