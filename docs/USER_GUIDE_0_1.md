# VetorizaFB user guide

Updated 2026-10-22. Scope: package **0.1.0**, experimental `ocr-modernization`
branch / [PR #1](https://github.com/ivanbodra/VetorizaFB/pull/1). Processing
implementation audited at commit `e41353dc2e29e62f8bcadb1bac75f5f5d0e3fa2a`.

This guide describes the current standalone runner. It supersedes operating
instructions for the earlier 3.0.1 EasyOCR application and the v4 interface
prototype; it does not claim that the experimental runner replaces a validated
historical release. The original seven files remain in `legacy/`.

## 1. Purpose and supported inputs

VetorizaFB reads a georeferenced nautical chart raster, detects character boxes,
recognizes digits, groups candidate sounding depths and exports XYZ. Outputs
are unreviewed candidates. It does not interpolate a seabed surface or read a
chart raster as if it were a depth-valued DEM.

Use an 8-bit GeoTIFF with a correct CRS and geotransform. RGB, grayscale and
palette images have reading paths; real experiments used the supplied RGB
charts. DPI metadata controls scale-dependent character filters. If DPI is
missing or incorrect, use a JSON configuration through the CLI. DPI does not
define geographic coordinates; those come from the geotransform and CRS.

Historical photographed/orthorectified handwritten field sheets are a separate
future module. The current decimal heuristics and whole-image loading are not
validated for them. TIFF compression/file size does not indicate peak RAM use.

## 2. Install on Windows

Use a separate 64-bit Python 3.12 installation and Git. Do not install into the
QGIS Python environment. There is no packaged Windows installer or validated
current `.exe` distribution in this update; the commands below install Python
entry points into a virtual environment.

Open PowerShell in a working folder:

```powershell
git clone --branch ocr-modernization `
  https://github.com/ivanbodra/VetorizaFB.git
cd VetorizaFB
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[ocr,test]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\vetorizafb-gui.exe
```

The backtick at a continued PowerShell line's end must be its last character.
No activation command or execution-policy change is needed. If Git is not
available, download the `ocr-modernization` branch ZIP from GitHub, extract it,
open PowerShell inside the extracted folder and start at the virtual-environment
command. Do not inadvertently download `main`, which contains the archived
baseline rather than the new runner.

The experiment used PaddleOCR 3.7.0 and PaddlePaddle 3.3.1 on CPU. These and
OpenCV are pinned; supporting dependencies have ranges. The default CPU install
is not a GPU setup. First use can download model weights. On a restricted
network, use a local official inference model as described below; the new GUI
does not have the old proxy username/password fields.

Linux: use `python3 -m venv .venv`, then `.venv/bin/python`,
`.venv/bin/vetorizafb` and `.venv/bin/vetorizafb-gui`. Install your distribution's
Tkinter package if needed. Extraction/tests were exercised on Linux/Python 3.12;
Windows installation and the desktop window are not yet validated.

## 3. Run through the desktop window

1. Run `vetorizafb-gui` from the environment above.
2. In **Carta**, select the GeoTIFF.
3. In **Pasta de saída**, select a new result directory. If empty when choosing
   a chart, it is populated as `results/<chart-stem>` beside the input.
4. Choose **Modelo OCR**. Start with `PP-OCRv6_small_rec`.
5. Leave **Modelo local (opcional)** empty for automatic model retrieval, or
   select a compatible extracted inference-model folder.
6. Click **Extrair candidatos e gerar XYZ** and wait. The progress bar indicates
   activity; it does not show percentage complete. Do not start another run or
   close the window while processing.
7. Read the candidate and numeric-box counts. The preview displays the complete
   chart with orange candidate boxes and red depth labels. Open the saved
   full-resolution JPG externally for detailed inspection.

The current GUI has no parameter editor, target-CRS selector, manual candidate
correction, approval action, preview zoom/pan or cancellation. Use the CLI for
configuration and target CRS. Editing the GUI paths during a run does not alter
the captured input for that run. A repeated run using the same input stem and
output directory overwrites the corresponding files; use separate folders for
each model/configuration.

The old staged buttons and parameter inspector belong to archived interfaces;
their presence in old screenshots does not describe this window.

## 4. Command line, models and coordinates

From the repository root in PowerShell:

```powershell
$vf = ".\.venv\Scripts\vetorizafb.exe"
& $vf "C:\cartas\1410geotiff.tif" `
  --output-dir "C:\cartas\results\1410-small" `
  --model PP-OCRv6_small_rec
```

The default device is `cpu`. Supported tested recognizers are
`PP-OCRv6_small_rec`, `PP-OCRv6_medium_rec` and `PP-OCRv5_server_rec`.
The model name and any local model directory must refer to the same model.
For offline use, obtain an official **inference** archive, extract it, and pass
the directory directly containing `inference.json`, `inference.pdiparams` and
`inference.yml`, rather than its parent or an unextracted archive:

```powershell
& $vf "C:\cartas\1410geotiff.tif" `
  --output-dir "C:\cartas\results\1410-offline" `
  --model PP-OCRv6_small_rec `
  --model-dir "C:\modelos\PP-OCRv6_small_rec_infer"
```

The default target CRS is EPSG:4326: **X = longitude, Y = latitude**, in decimal
degrees. Select a suitable projected target CRS with `--target-crs` when metre
XY coordinates are required. For example, `--target-crs EPSG:31984` requests
SIRGAS 2000 / UTM 24S; use it only for an appropriate area/workflow, not as a
universal default. Source datums are transformed with pyproj; the software
does not assume that all GeoTIFFs are WGS84.

Z is depth in metres, positive down, with the source chart's vertical reference
unchanged. No vertical datum conversion is performed. The point anchor is the
detected text group's bounding-box centre, not a validated hydrographic anchor.

## 5. Configuration and calibration

Without `--config`, the software reads TIFF DPI and uses `Config` defaults.
With `--config`, values come from the JSON and unspecified values use defaults,
including **600 dpi**; automatic TIFF DPI is not merged into a supplied config.
Always set the actual DPI explicitly in custom files.

For a 300 dpi chart, save this as `configs/chart_300dpi.json`:

```json
{
  "dpi": 300,
  "segmentation": "legacy",
  "grouping": "relative",
  "threshold": 120,
  "min_confidence": 0.35
}
```

```powershell
& $vf "C:\cartas\1410geotiff.tif" `
  --output-dir "C:\cartas\results\1410-config" `
  --config configs/chart_300dpi.json
```

| Setting | Default | Meaning |
|---|---:|---|
| `reference_dpi`, `dpi` | 600, 600 | Scale = actual DPI / reference DPI |
| `segmentation` | `legacy` | Grayscale/blur/threshold/dilation; `black` is an alternative black-ink mask |
| `threshold` | 120 | Dark foreground threshold, 0 to 255 |
| `blur_size`, `kernel_size` | 5, 2 | Scaled blur/dilation sizes in legacy mode; blur becomes odd |
| `min_w`, `max_w` | 3, 80 | Strict character-width limits at reference DPI |
| `min_h`, `max_h` | 10, 100 | Strict character-height limits at reference DPI |
| `grouping` | `relative` | `fixed` uses only scaled tolerances |
| `tol_x`, `tol_y` | 30, 6 | Reference-pixel horizontal and vertical tolerances |
| `decimal_height_ratio` | 0.95 | Last digit height relative to the integer digits |
| `decimal_drop` | 0.10 | Last-digit vertical drop as a fraction of integer height |
| `decimal_max_integer` | 31 | Maximum integer part eligible for subscript decimal interpretation |
| `min_confidence` | 0.35 | Minimum character OCR score for grouping |

In relative mode X tolerance is at least 1.4 times the first character height;
Y tolerance is at least 0.6 times that height. Groups contain one to four digits.
Decimal interpretation applies to groups of two or three digits and only to
the last digit. The integer-part limit 31 is a configurable legacy heuristic,
not a universal cartographic standard, and must not be copied to FB workflows.

Larger tolerances can merge adjacent soundings. Lower confidence thresholds can
admit more spurious characters. Higher confidence thresholds can drop a digit
and leave an incorrect partial depth. DPI scaling does not solve all typography,
rotation, touching-line or symbol-classification problems. Change one setting at
a time, retain outputs in a new directory and review the resulting points.

## 6. Output files and GIS inspection

For `1410geotiff.tif`, the output directory contains:

| File | Content |
|---|---|
| `1410geotiff.xyz` | Headerless, space-delimited X Y depth; decimal point `.` |
| `1410geotiff.csv` | Candidate geometry, depth, confidence, IDs, interpretation, status and XY |
| `1410geotiff.digits.json` | All raw OCR readings and character boxes, including rejected readings |
| `1410geotiff.metadata.json` | Input SHA-256, CRS, model, configuration, package versions, counts and time |
| `1410geotiff.preview.jpg` | Complete chart with candidate boxes and interpreted values |

XYZ has exactly three columns and no CRS declaration. Preserve its metadata
alongside it. The CSV contains `pixel_x`, `pixel_y`, `depth`, `confidence`,
`bounds`, `digit_ids`, `interpretation`, `review_status`, `x`, `y`. Pixel values
are continuous raster coordinates; XY values use the requested target CRS.
`bounds` and `digit_ids` are structured values serialized in quoted CSV fields;
use a real CSV reader rather than splitting every comma manually.

For GIS inspection, import the CSV as delimited text, use `x`/`y` as coordinates
and assign the CRS from the metadata. Keep `depth` as an attribute and overlay
the source raster. With the default target, choose EPSG:4326; do not assign the
input raster's projected CRS to longitude/latitude output. Importing XYZ as
points is also possible with a whitespace delimiter and the same declared CRS.

All candidates have `review_status=unreviewed`. The program has no approval or
write-back editor. Correct/filter points in a separate reviewed GIS dataset,
retain their provenance, then export your reviewed XYZ under a new filename.
Confirm XY order, units and the required Z sign in the receiving application.
No raster resampling, interpolation or depth-surface generation occurs here.

## 7. Review before using XYZ

Inspect complete sounding groups, especially zero, lowered decimetres, slanted
digits, digits touching contours, crowded areas, chart borders, coordinates and
hazard labels. Check for missing soundings as well as incorrect and extra points.
Contour labels are a demonstrated false-positive class, not a hypothetical risk.

Confidence is the minimum score of the accepted characters; it is not a
calibrated probability that the sounding is correct. A high-scoring `87` can
still need the cartographic interpretation 8.7. Rejected characters are retained
in the digits JSON but can leave a wrong partial depth in the candidate set.

Validate point location against the original sounding mark/text convention.
Coordinate round-trip consistency tests only verify the transformation math;
they do not establish the correct cartographic anchor or source-raster accuracy.
Define separate acceptance criteria for detection precision/recall, exact depth,
decimal interpretation, XY error and vertical-reference compatibility.

The 19 positive development crops produced 16 correct complete depths with
PP-OCRv5 server and 17 with each PP-OCRv6 variant. All three models incorrectly
accepted both contour-label negatives. The annotations were manually read by
the assistant, not independently reviewed, and were used during development.
These are not full-chart accuracy percentages or a held-out generalization test.

Full runs produced 163, 3,077 and 2,826 unreviewed candidates on 21300, 1410 and
1822 respectively. The author's earlier 100% result on 21300 is not independently
reproduced by these runs. See `docs/EXPERIMENTS.md` for the recorded evidence.

## 8. Grouping optimization and processing time

The efficient sequential search strategy is present in the registered legacy
`group_digits_by_position` function and current `core.group`: sort by X, scan a
bounded horizontal window, mark used characters, and stop at four accepted
digits. There is no global enumeration of digit combinations.

On the stored OCR readings, grouping alone took median 0.0022 s / 0.0617 s /
0.0538 s on the three charts (three repetitions). Complete extraction previously
took 16.9 s / 244.8 s / 259.4 s. These are different timing sessions on one CPU
environment; the full runs overlapped. They are not hardware requirements or
guaranteed execution times. Box count, pixel count, model/device, memory and
downloads all affect perceived duration.

The algorithm has O(n log n) sorting and a density-dependent scan. Its worst
case is still O(n²), not exponential: many same-X characters at different Y
positions can force repeated scans. A synthetic 1,000/2,000/4,000-character
vertical-column case took 0.319/1.330/5.042 s. A future two-dimensional index
could address this, but none is implemented in the audited version.

Historical discussion mentioned both Union-Find and sequential variants. The
received files contain the sequential variant. The earlier stable 3.0.1/EasyOCR
release/executable is not fully represented by this seven-file snapshot; exact
identity with that historical version cannot be certified. See
`docs/GROUPING_AUDIT.md` and its raw benchmark report.

## 9. Troubleshooting and updating

| Symptom | Action |
|---|---|
| `py` or Python 3.12 not found | Install Python 3.12 for the operating system and retry in a new terminal |
| `ModuleNotFoundError` | Run pip and the application from the same `.venv`; rerun the editable install |
| QGIS/PyQt import error | Run standalone outside QGIS; this application uses Tkinter |
| Model download fails | Use the matching official local inference-model directory; no model weights are committed |
| `Input has no DPI metadata` | Supply `--config` with the actual DPI through the CLI |
| `The input has no CRS` | Correct/establish the raster georeferencing in a GIS before extraction |
| `Only 8-bit chart imagery` | Prepare an appropriate 8-bit cartographic copy preserving georeferencing; do not treat elevation samples as chart colours |
| Too many/few candidates | Inspect boxes/raw readings and calibrate; count alone is not an accuracy metric |
| Preview too small | Open the saved full-resolution JPG externally; the current canvas only fits the image |
| Very slow or memory failure | Start with one chart/CPU job, verify available RAM and box count; whole-image processing has no tiling yet |

The GPU package/device configuration is outside this tested CPU setup.
If a model directory is present but inference fails, confirm its model name,
files, dependency versions and the exact terminal message; a training checkpoint
is not necessarily an inference directory.

If the repository was cloned with Git, preserve local changes before updating:

```powershell
git status
git switch ocr-modernization
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -e ".[ocr,test]"
.\.venv\Scripts\python.exe -m pytest -q
git rev-parse HEAD
```

Keep the commit ID, input checksum, metadata, configuration and reviewed
reference points for each comparison. Core tests need no model download; they
do not validate the desktop window or establish real-chart accuracy. Crop
experiments can be reproduced with `scripts/benchmark_crops.py`; grouping-only
timings use `scripts/benchmark_grouping.py` and pandas.

## References

- [Current development branch](https://github.com/ivanbodra/VetorizaFB/tree/ocr-modernization)
- [Original baseline and scope](BASELINE.md)
- [Measured OCR/full-chart experiments](EXPERIMENTS.md)
- [Grouping algorithm audit](GROUPING_AUDIT.md)
- [Official PaddleOCR inference model catalogue](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/module_usage/text_recognition.en.md)
