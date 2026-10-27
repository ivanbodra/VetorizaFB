# VetorizaFB 5.0.0 — PySide6 desktop and field sheets

This development release incorporates `cn-area-selection` 9a149c7 (4.0.6),
including automatic size estimates, diagnostics and irregular selections, and
`ui-pyside6-design` 22c8a8e (the SVG icon family and visual guidelines).
The design branch supplied assets, not existing Qt application code.

## Windows update

In PowerShell at the repository root, with HTTPS_PROXY already set when needed:

```powershell
git fetch origin
git switch v5.0-folhas-de-bordo
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -e ".[qt,ocr,test]"
.\.venv\Scripts\vetorizafb-gui.exe
```

`python -m vetorizafb.qt_gui` is an alternative launcher. Python 3.12 x64 is
recommended, outside QGIS. Startup isolates wheel GIS data from inherited
PostGIS PROJ variables. The retained Tk interface is `vetorizafb-classic.exe`.
The application version is 5.0.0; this is an experimental development release.

## Qt workflow

Open a georeferenced TIFF or an existing review JSON project. Four tabs expose
preparation, reading, grouping and export. Prepare offers Realce, Bruto and
Folha de bordo. Preview only segments and never loads an OCR engine. Selecting
an area enables a right-click menu for rectangle, polygon and freehand; Esc
cancels the outline. Coordinates are original pixels regardless of zoom/pan.
Use the wheel to zoom; Mover restores pan. Medir caixa reports pixel dimensions.

In Reconhecer select a local model directory. Baixar modelo is explicit and
supports Automática (including HTTPS_PROXY), Direta, or Proxy with masked
password and optional CA file. No weights are shipped. Reading requires a local
model selected from the inspected files; it never starts a download implicitly.
OCR and processing run in a worker thread with the editing controls disabled.

Field-sheet preparation normalizes the background and local contrast. The
existing contour size filters still supply boxes. The FB reader preserves 1–3
digit tokens instead of imposing CN's one-digit rule. Its separate grouping
combines closely aligned integer fragments and a smaller lower digit, with no
31 m ceiling. It abstains on conflicting decimal associations. Missing decimals
are flagged, and every automatic FB anchor is marked unverified. Main-text
centre is provisional; review the coordinate before approving.

The review table switches between readings and soundings. Somente incertas
filters invalid/low-confidence tokens and, after FB grouping, unassigned tokens.
Correcting a reading retains previous evidence in alternatives and invalidates
grouping without another OCR call. FB box union/split invalidates OCR and grouping;
rerun Ler caixas. Split supports horizontal or vertical pixel offsets.
Sounding correction, explicit acceptance/rejection, observations and manual
insertion/movement reuse the review history. To insert/move, click the desired
map position in pan mode and use the respective action. Save/open projects
retains geometry, raw readings, corrections and review. Export validates stage
settings and uses the existing candidate/accepted-only XYZ bundles and CRS tools.

## Verification and remaining limits

New tests cover multi-character FB reads, integer-fragment grouping, lower
subscripts above 31 m, ambiguous-link abstention, unchanged CN token handling,
Qt project round-trip, manual correction invalidation and edited-box invalidation.
Qt is tested offscreen on Linux, with fake OCR for deterministic processing
checks; this does not establish handwritten accuracy. The submitted native TIFF
was loaded and segmented in the Qt workbench for visual inspection.

The Qt shell does not yet expose all advanced classic controls (parameter
profiles, batch coordinate offsets, restoration controls and keyboard review
shortcuts). They remain available in the retained classic interface. The Qt
viewer/session currently loads the full raster; the separate windowed experiment
is not yet connected to this viewer. A 530 MB raster on Windows/8 GB and native
Windows rendering remain to be verified. No 690-point accuracy claim or model
training is included in this release. Existing reviewed projects are not
silently converted to field-sheet mode.
