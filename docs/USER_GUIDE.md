# VetorizaFB 0.4 user guide

Updated 2026-10-23. Development branch: `ocr-modernization`, PR #1.
The [0.1 guide](USER_GUIDE_0_1.md) is retained for historical reference.

This version retains PaddleOCR 3.x and restores staged calibration and image
inspection. It also introduces explicit point review. It is an experimental
raster-chart extraction tool; approval of points is an operator decision, not
an automatic accuracy certification. Historical handwritten FB extraction is
still a later module.

## Install or update

Run from the repository root, the directory containing `pyproject.toml`, rather
than `legacy/v3_1`. On Windows use a separate 64-bit Python 3.12 environment.
Do not use the QGIS Python installation.

```powershell
cd "D:\Bathy\Estudos\Programas\VetorizaFB"
git status
git switch ocr-modernization
git pull --ff-only
Test-Path .\pyproject.toml
```

The last command must return `True`. Preserve any local changes before updating.
For a first installation, clone the branch or download/extract its branch ZIP,
then create the environment in that root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[ocr,test]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\vetorizafb-gui.exe
```

On an existing installation, reuse the root `.venv` and rerun the editable
installation after updating. Confirm that the window title shows **0.4.0**.
Linux equivalents are `.venv/bin/python`, `.venv/bin/vetorizafb-gui` and
`.venv/bin/vetorizafb`; Tkinter and a display are required for the GUI tests.
Use `xvfb-run -a python -m pytest -q` in a headless Linux test environment.

Standalone CLI/GUI entry points ignore inherited `PROJ_LIB`, `PROJ_DATA` and
`GDAL_DATA` when Rasterio supplies its own wheel data. Changes affect only the
application process, not PostgreSQL/QGIS installations or persistent settings.
Set `VETORIZAFB_KEEP_GIS_ENV=1` only when deliberately using a compatible custom
GIS-data environment. In a terminal running pytest directly with an old PostGIS
PROJ environment, use the session-only workaround before testing:

```powershell
Remove-Item Env:PROJ_LIB -ErrorAction SilentlyContinue
Remove-Item Env:PROJ_DATA -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pytest -q
```

## 1. Open the chart

Select **Selecionar / abrir**, or enter a path and choose **Abrir caminho**.
Use a correctly georeferenced 8-bit GeoTIFF. The real experiments use RGB charts;
grayscale and palette reading paths also exist. CRS/geotransform control XY;
DPI controls only character dimensions and is not a geographic scale.

The effective TIFF DPI populates the field. If it is missing, the GUI asks for
it; a cancelled answer leaves an invalid/empty field until you supply a value.
The whole image is decoded into RAM. Region processing reduces OCR work, but
it is not a windowed reader for a 135 MB historical FB.

## 2. Inspect and segment

In **1. Segmentar**, adjust effective/reference DPI, segmentation mode, threshold,
blur, dilation and character width/height limits. Dimensions are defined at
`reference_dpi=600` and multiplied by effective DPI/reference DPI. Width/height
limits are strict. The inspector reports actual-pixel dimensions and P98-clipped
histograms with the applied minimum/maximum limits. Larger outliers are not all
shown on the histogram axis.

Choose **Executar etapa 1**. **Inspecionar dimensões / histogramas** opens the
calibration inspector. The chart can be displayed as **Original**, **Máscara** or
**Caixas**. Change parameters and rerun segmentation to apply a new calibration.
Later stages are marked pending; old reads cannot be exported under new settings.

For a local experiment, choose **Selecionar área** above the chart and drag a
rectangle, then rerun stage 1. **Usar carta inteira** removes this restriction.
All character boxes and exported XY retain the original full-image coordinate
system. Cutting through a character at an ROI boundary can change its contour;
leave a margin around soundings. A new ROI replaces the working region; it does
not accumulate results from several ROIs into one project.

When excluding marginal coordinates, select the useful chart area inside the
frame before processing. This also omits any legitimate soundings outside that
rectangle, so check the intended coverage. There is no automatic margin mask.
Rotation alone is insufficient: the example contains both vertical and
horizontal coordinate labels, while italic sounding digits have slanted strokes.
Contour labels use the same digits as soundings and remain subject to review.

## 3. OCR and character inspection

In **2. OCR**, select PP-OCRv6 small/medium or PP-OCRv5 server. Small remains the
provisional default. Optional local model folders must match the selected model
and contain the extracted inference files, not a training checkpoint or archive.
With an empty folder field, PaddleOCR may retrieve weights on first use.
The installed setup and GUI use CPU; GPU configuration is outside this setup.

Set batch size (1-1024), crop padding (0-100 actual pixels) and minimum confidence.
**Reler possíveis “1”** is enabled by default. Narrow, unresolved `I`, `l`, `|`,
`!` or empty readings are eligible for a second model reading after binarization,
white padding and 2x enlargement. A local letter-neighbour check suppresses
apparent word contexts. Only an actual model output of exactly `1` with a score
at least `max(0.80, minimum confidence)` is selected. Recognized zeros and
multi-character readings are never replaced by this directed pass. A failed
retry gets one final attempt in 0.3.1: isolate the dominant ink component that
overlaps the original character box, remove disconnected neighbouring fragments,
then reread that crop with white padding and 2x enlargement. A model result such
as `1.` is preserved; it is never shortened into a digit. The isolated reading
must independently return exactly `1` above the same confidence threshold.
Blank crops or components failing the overlap/size checks are skipped. A failed
final retry stays unresolved; this is not a forced `I` → `1` substitution.

**Reler todos os demais ambíguos** enables the broader retry and is off by default.
It accepts any single numeric alternative above the configured minimum. When
both options are enabled they share one retry batch; directed candidates retain
the stricter `1` rule. Other crops, including apparent words skipped by the
directed filter, can still enter the broader retry. Letters and line fragments
can become false positives, so use this option experimentally.

Both raw readings and real scores remain recorded. Affected groups receive
`ocr_retry`; directed recoveries also receive `ocr_one_retry` and the table shows
**Releitura dirigida: 1**. Every generated point starts pending. No synthetic
confidence is inserted and a model score is not a probability of a correct
sounding. An isolated recovery has digit method `ocr_one_isolated` and alternative
method `isolated_component_padded_2x`. See the [follow-up diagnostic results](REMAINING_ONES.md)
and [original directed-retry results](REVIEW_AND_ONES.md).

Choose **Executar etapa 2**. Progress reports batches; model loading and individual
batches cannot be interrupted midway. Cancellation is checked between batches
and stages, preserving the last fully completed stage. A recognizer is reused
for subsequent runs with the same model specification.

Select **OCR** above the chart, zoom in and click a character box to view its
crop, original text/score, selected reading, method and alternatives. Green
character boxes have numeric readings; orange boxes are unresolved/unread.
A numeric reading below the grouping confidence threshold can still be excluded
from a sounding. A high score does not establish correct cartographic meaning.

## 4. Group without repeating OCR

In **3. Agrupar**, adjust fixed/relative spacing, horizontal and vertical tolerances,
subscript height/drop, maximum integer eligible for decimal interpretation and
confidence. Choose **Executar etapa 3 / reagrupar**. When only grouping settings
change, valid digit reads are reused. Changing minimum confidence requires new
OCR when either retry is enabled, because it affects retry eligibility/selection.

**Executar etapas pendentes (1 → 3)** computes only invalid/missing stages. Explicit
stage buttons rerun that stage. Re-segmenting, re-reading or regrouping replaces
downstream results/review, so save the project first. Unsaved review decisions
trigger a confirmation before replacement. Export stays disabled while the UI
configuration, model or ROI differs from the last complete processing state.

The algorithm retains greedy X order, horizontal-window stopping and a maximum
of four digits per group. Y buckets reduce scans through vertically aligned
characters without changing the earlier grouping decisions on the regression
corpus. Groups of two/three digits may interpret their last digit as a decimal.
The default integer limit 31 is a configurable heuristic, not a universal CN/FB
rule. Raw OCR can still confuse contour labels and sounding text.

## Optional yellow-background rejection

In **1. Segmentar**, enable **Excluir caixas com fundo amarelo**. This is off by
default so existing calibrations remain unchanged. The scrollable panel exposes
**R−B e G−B mínimos** (default 25 on the 0-255 channel scale) and **Fração mínima
do fundo** (default 0.60). A box is rejected when enough non-dark background pixels
meet both channel-difference limits. A small surrounding margin helps estimate
the background of narrow ones; dark numeral ink is ignored. Signed arithmetic
prevents cyan/blue subtraction from wrapping into a false yellow result.

The rule includes some yellow-green tints. White, grey and cyan do not satisfy
the default rule; mixed coast-boundary boxes can remain. Warm paper or a genuine
sounding on yellow-tinted water can also satisfy it, so tune against the original
chart. **Rejeitadas por cor** displays excluded boxes over their original pixels;
the count appears beside accepted boxes. This is box filtering, not a rewrite of
the original raster or the **Máscara** layer. Changing these settings invalidates
segmentation and downstream stages; rerun 1 → 3. The JSON profile
`configs/chart_300dpi_yellow_filter.json` is an optional 300-DPI starting point.

## 5. Navigate and review

Mouse wheel zooms around the pointer. **Ajustar**, **100%**, plus and minus control
scale. In **Inspecionar** mode, drag to pan. **Sondagens** displays point anchors,
boxes and interpreted depths: orange pending, green accepted, red rejected,
blue selected. The active point has an additional ring. Labels are suppressed
at small scales for legibility; zoom in.

Click the table or the chart to use review shortcuts. Arrows follow the order
of the **visible table rows**, rather than searching spatially. Navigation stops
at the ends. With **Acompanhar ponto / zoom** enabled, a new active point is
centred as far as chart edges allow and zoom is calculated from the sounding
height (about 80 screen pixels, capped at 800%), with surrounding context.
Repeated navigation does not multiply the zoom. Disable following to retain
manual zoom/pan; double-click or **Ampliar ponto** explicitly focuses the active
point regardless of this setting.

| Shortcut / control | Action in the review table or chart |
|---|---|
| Down / Right | Next visible point; select it and make it active |
| Up / Left | Previous visible point |
| Shift + arrow | Extend or shrink a contiguous selection from its anchor |
| Ctrl + click | Toggle individual points in the table or soundings image |
| Shift + click | Select a range; in the image this uses table order |
| Ctrl+Space | Toggle selection of the active point without changing its focus |
| Ctrl+A | Approve all selected points |
| Ctrl+X | Reject all selected points, keeping their history |
| Ctrl+E | Edit the depth when exactly one point is selected |
| Ctrl+Shift+A / **Selecionar todos** | Select every visible row |
| Esc / **Limpar seleção** | Deselect all points |
| **Inverter seleção** | Toggle selection across the visible rows |

Filter **Todos**, **Pendentes**, **Aprovados** or **Excluídos**. Select-all respects
the filter; choose **Todos** first to include the whole working result. The
selection count shows how many visible points are selected. With a pending-only
filter, approval/exclusion removes those rows and selects the next remaining
point so review can continue. Ctrl+A is approval here; it no longer selects all.
These bindings are local to the table/chart. Parameter and note fields retain
their normal text-editing keys and cannot approve/reject a point through them.

Add an optional **Nota da revisão** before an action; batch decisions record it
for every selected point. Editing and approval are disabled during processing
or when the configured stages are stale.

- **Editar valor** changes one selected depth, preserving its original value.
  Enter a finite value with at most one decimal; it becomes pending again.
- **Aprovar seleção** explicitly accepts all selected points. It is not an automatic check.
- **Excluir seleção** rejects selected spurious points; original data and history remain.
- **Pendente** reopens an accepted/rejected decision.
- **Inserir ponto** mode lets you click a missed sounding and enter its depth.
  Manual points have no model confidence and remain pending until accepted.
- **Mover selecionado** mode changes the anchor of one selected point by clicking
  the chart. The original detection box stays in the audit; the new XY is pending.

The review panel now exposes these tools directly:

| Button | Operation |
|---|---|
| **Adicionar profundidade** | Click the new anchor on the chart, then enter its depth |
| **Mover ponto** | Select one row, then click its new anchor |
| **Posição…** | Enter the selected point's X/Y in original-image pixels |
| **Offset…** | Preview and apply an incremental displacement to all or selected points |

The insert/move buttons activate a one-click tool and return to **Inspecionar**
after use. Esc cancels it and clears the selection. The original mode selector
remains available for repeated insertions/moves. A newly inserted pending point
is made visible/active even if the previous table filter hid pending points.
Numeric position forms accept a decimal comma or point and reject nonfinite or
out-of-image coordinates. Manual points retain no model confidence. The review
note is stored with manual insertion and position changes.

### Incremental position offsets

**Offset…** adds ΔX/ΔY to current anchor positions. Reapplying adds another
increment; it does not set an absolute cumulative offset. **Todas as sondagens**
includes rows hidden by the table filter and rejected points. **Selecionadas**
limits the operation to the explicit selection, when one exists.

- **Pixels da imagem:** positive X moves right; positive Y moves down. Values are
  original raster pixels, independent of viewport zoom or DPI calibration.
- **Metros no CRS projetado:** ΔX/ΔY follow the source chart's projected grid axes,
  rather than the chosen export CRS. The full inverse affine handles rotation
  and shear; source linear units are converted when needed. These are projected
  grid metres, not geodesic ground-distance adjustments. A geographic source CRS
  cannot use this option; use pixels instead.

**Prévia (sem alterar)** reports the point count and equivalent pixel offset.
**Aplicar** validates every target before moving any point; one out-of-image
target rejects the whole batch. Zero displacement does nothing. Depths, original
records, OCR boxes, raster georeferencing and DPI are unchanged. The anchor moves;
the OCR box stays over the source text for inspection.

Previously approved moved points become pending. Rejected points remain rejected.
Every target records before/after positions, requested units/deltas, equivalent
pixel deltas, a shared batch ID and the review note. Save the project to retain
the history; exported coordinates use the edited anchors. An inverse incremental
offset can move positions back, while their audit trail remains. Recheck positions
before approving the shifted set.

Review complete values and decimal typography, including zeros, narrow/slanted
ones, touching lines, dense groups, contour labels, land annotations, tables,
coordinates and chart boundaries. Find omissions as well as incorrect/excess
points. The default automatic anchor remains the text bounding-box centre,
which is not a validated cartographic sounding anchor.

## 6. Save and resume

Use **Salvar projeto de revisão** or Ctrl+S to save `.vfproject.json`. It contains
source path/SHA-256, applied configuration, ROI, model specification, character
boxes/readings, point decisions, original values and dated review actions.
Pixels and model weights are not embedded. Save parameters separately through
the **Arquivo** menu to reuse a calibration on another chart.

**Abrir projeto** restores valid cached stages without model inference; the mask
and dimension inspector are reconstructed from the source. If the source moved,
select its new location. A different source hash is rejected. Source modification
also blocks export. Save the applied state before changing settings; unsaved
UI parameter edits are not recorded as processed results. A source must remain
available for project loading and geographic export.

Projects saved by 0.2 without a `retry_one` field reopen with that option disabled:
their cached OCR and review are preserved under the behaviour actually used.
Enable the new option and rerun OCR/grouping when you want directed retry;
save the existing project first if it contains review decisions to retain.

To apply the 0.3.1 crop-isolation fix to a cached 0.3.0 project, explicitly rerun
**Executar etapa 2**, then **Executar etapa 3 / reagrupar**, with **Reler possíveis
“1”** enabled. Opening a saved project restores its cached readings; the pending-
stages button can reuse them. Save the original review before replacing it.

## 7. Export candidates or accepted points

In **4. Exportar**, choose an output directory and target CRS. Default EPSG:4326
means X=longitude, Y=latitude in decimal degrees. For projected XY in metres,
choose the appropriate CRS for your area. Z remains metres, positive down,
with the chart's vertical reference unchanged. Manual positions use the same
full-image coordinate transform. No interpolation or vertical datum conversion
is performed.

**Exportar candidatos** excludes rejected points and writes a `.candidates`
bundle, containing both pending and accepted points. **Exportar somente aprovados**
writes a `.reviewed` bundle and refuses an empty approved set. Pending and
rejected points never enter reviewed XYZ. Check the reviewed count against your
intended coverage; approving a subset does not establish chart completeness.
Existing files with the same stem trigger an overwrite confirmation.

Each bundle has:

| Suffix | Content |
|---|---|
| `.xyz` | Headerless, space-separated X Y depth with decimal point `.` |
| `.csv` | Pixel/target XY, depth, confidence, bounds, character IDs, flags and status |
| `.digits.json` | Original and alternative character OCR readings |
| `.review.json` | Complete review history, including rejected and omitted-from-export records |
| `.preview.jpg` | Complete chart with exported points |
| `.metadata.json` | Input/configuration/model/CRS, stage times, counts and output hashes |

Files are validated and written in a temporary staging directory before publish.
Metadata is published last as a completion marker with SHA-256 hashes. A multi-file
rename is not a filesystem transaction; an interrupted publish can be detected
by checking hashes. Keep metadata beside XYZ, which has no CRS declaration.

Import CSV in your GIS with `x` and `y` and the declared target CRS; keep `depth`
as an attribute and overlay the source chart. Do not assign the source projected
CRS to longitude/latitude values. Structured CSV fields are quoted: use a proper
CSV reader. Compare point positions with actual chart conventions before approval.

## CLI compatibility and remaining limits

The existing command remains available and produces an unreviewed bundle with
the original stem. It does not approve points:

```powershell
.\.venv\Scripts\vetorizafb.exe "C:\cartas\1822geotiff.tif" `
  --output-dir "C:\cartas\results\1822" `
  --model PP-OCRv6_small_rec `
  --config configs/chart_300dpi_retry.json
```

The retry profile is experimental, not a universal calibration. With `--config`,
unspecified fields use defaults, including DPI=600; always set effective DPI in
a custom file. Without it, CLI uses TIFF DPI and rejects missing DPI metadata.

The chart-frame/sounding classifier, automatic contour-label rejection, trained
sounding detector, automatic skew/line separation and whole-image tiled reading
are not implemented. The UI is a restoration/extension of functional tools, not
a reproduction of the old branding/assets or an independently reproduced copy
of the historical EasyOCR 3.0.1 executable. Neither automated tests nor the small
crop experiment establish 100% full-chart extraction accuracy.

See [colour-filter/position-tool validation](COLOR_AND_POSITIONS.md),
[remaining-one/crop-isolation validation](REMAINING_ONES.md),
[keyboard/one-retry validation](REVIEW_AND_ONES.md),
[0.2 restoration validation](RESTORATION.md), [initial experiments](EXPERIMENTS.md)
and the [official model catalogue](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/module_usage/text_recognition.en.md).

## Version 4.0 — visual calibration and application identity

The application is now named **VetorizaFB 4.0** at the author's request (this
supersedes the development sequence 0.4.0). Existing project format and original
sources are retained. F1 and Help → Manual open the bundled offline Portuguese
manual; Help → About identifies the running version.

Run segmentation once, then use **Medir caractere** to drag a native-pixel
rectangle independent of zoom. The panel shows native and reference-DPI sizes.
Buttons can set minimum/maximum width and height, allowing one reference pixel
of margin because existing size tests use strict inequalities. Measure narrow
ones, wide zeros and small decimal glyphs before setting the full range.

**Prévia dos filtros** reclassifies cached contours on parameter changes without
OCR or mutation of the session, review, exports or stage signatures. Accepted
boxes are green; rejected boxes have thin light-grey outlines. Toggle rejected
visibility. At less than 60% zoom, outlines are hidden; hover at a useful zoom
shows native size and rejection reason and highlights only that box. Width,
height and yellow-background controls update after a brief debounce. Changes to
mask/DPI/ROI require stage 1 again; invalid or stale previews clear their boxes.
Apply the chosen limits with stage 1 before OCR. The preview is calibration,
not classification of soundings or a guarantee of accuracy.

The original identity artwork is now bundled: the supplied multi-resolution ICO
is the default window icon, the original monitor PNG appears in the header,
and About shows the full application logo with the MB/CHM marks. Images preserve
their aspect ratios. The original splash and additional mascot are retained as
assets; no artificial startup delay or loading screen is introduced. User-selected
icons remain supported and the last selected format persists across launches.
All seven supplied images are preserved byte-for-byte in package assets.


### Compact desktop workspace

The native Python/Tkinter application retains its processing and project format.
The active tab is blue; readiness dots represent current (green), stale/pending
(amber), processing (light blue) and no chart (grey). Hover provides the textual
meaning. Tabs remain available for configuration, while execution buttons retain
stage validity checks. The fixed stage-status line and shortcut legend are
removed. The CN path field is pale yellow until that path has been loaded.

Review actions use short labels (Aprovar, Excluir, Editar, Adicionar, Mover).
The toolbar wraps to preserve every action at smaller widths. Contextual tooltips,
Help → Keyboard shortcuts and a chart/table right-click menu replace permanent
explanatory text. Right-click preserves the current multi-selection; review keys
retain their original scope. Grey indicates disabled controls; available controls
use blue, with soft green/red for approval/exclusion. About omits implementation
and icon-filename diagnostics. Preview details show only during preview/measurement;
the sidebar summary exposes full counts and timings on hover. No dependency or
OCR/geospatial algorithm changes are required.

### OCR models and explicit proxy-aware downloads

The OCR tab has three compact rows: **Pasta**, **Download → Conexão / baixar…**,
and **Local**. The first row selects a model library folder (or a single model
folder); the last lists only supported complete local inference models. Browse
or enter a folder and press Enter/refresh. Selecting a different model invalidates
OCR/grouping validity without deleting review decisions. Model discovery requires
`inference.yml` with a supported model identity, nonempty `inference.pdiparams`
and `inference.json` or `inference.pdmodel`. This is structural validation, not a
model-accuracy or weight-integrity certification.

Existing `~/.paddlex/official_models` is the default and is neither moved nor
copied. `PADDLE_PDX_CACHE_HOME` is respected. Each model occupies its own child
folder; `_infer` folders from manual extraction are accepted as well. In frozen
builds a populated `models` folder beside the executable is used when no folder
preference exists. The selected library location is saved per user. Existing
project OCR signatures are retained on open; selecting/re-running with a local
path requires reviewing any replaced results as before.

The download form selects one of the three supported recognition models and one
connection mode: **Sistema** (Requests-recognized environment/static system proxy
settings), **Direta** (ignore inherited proxy settings), or **Proxy** (explicit
HTTP/HTTPS server:port, optionally username/password). Basic proxy authentication
is supported; PAC execution, NTLM/Kerberos and integrated Windows authentication
are not implemented. Optional PEM CA configuration preserves TLS verification.
Credentials remain in process memory for the session, are masked in the form,
and are not saved in projects, parameter profiles or model-folder preferences.
No global proxy environment variables are modified.

Downloads use official Paddle BOS inference archives, separately from OCR. The
chosen connection applies only to the download's own HTTP session. Temporary
files are extracted within the destination filesystem, with path/link/type/size
checks; only a complete matching model is published. Failed or cancelled transfers
remove their temporary files. Existing complete models are reused; incomplete
existing target folders are preserved and reported rather than overwritten.
Cancellation is checked between transfer/extraction chunks; connection/read waits
are bounded to 15/45 seconds. The GUI blocks recognition without a complete local
model and explains how to obtain one instead of silently attempting a download.
The CLI retains its prior automatic-download fallback when no local model exists.

Tests cover isolated proxy modes, escaped credentials, TLS/proxy/timeout/407
messages, archive traversal/symlinks, cancellation/partial cleanup, existing-model
retention, selectors and real Tk connection forms. HTTP failure/download responses
are simulated; an actual corporate proxy and rebuilt Windows executable still
require deployment validation. No input chart is uploaded by model download.


### Closed chart frames and nested contours

Segmentation retains foreground components inside closed chart frames and contour
lines. CCOMP's two-level hierarchy separates these components from background
holes in 0/6/8/9; glyph holes do not become duplicate boxes. This is a different
cause than blur erasing thin strokes. Use blur 1 for the documented 21010 example,
then re-run segmentation, OCR and grouping.

The native 21010 check, using the preceding screenshot settings with blur 1,
recovers 443 candidate character boxes inside the recorded closed-frame region
(previously zero), preserving all 3,615 previously accepted boxes unchanged. The
whole chart now has 4,088 accepted boxes. These are component counts, not verified
soundings or recall/precision measurements; no OCR was executed. Configuration,
region, input hash and results are in experiments/21010-nested-contours.json.

Projects record the contour extraction revision. Old projects without this field
retain their saved boxes, OCR, decisions and historical preview; loading never
adds candidates or claims the correction already ran. Save the review before
explicitly running segmentation to apply the change, then rerun OCR/grouping.
Numbers physically connected to lines remain a separate limitation.
