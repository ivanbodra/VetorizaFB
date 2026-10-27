# Windowed FB development — 1506-001/1989 view1

The isolated `windowed.py` module adds bounded raster reads, native pixel-edge
coordinates, per-window preparation/detection caches, strict DMS/metric reference
parsing and a geographic alignment overlay. No OCR engine is loaded.

```sh
python -m experiments.fb_v5.windowed sheet.tif reference.txt \
  --reference-crs EPSG:4326 --output results/view1 --glyph-height 32
```

The XYZ datum is not encoded in its text. EPSG:4326 in this experiment is an
explicit working assumption consistent with the submitted WGS 84 GeoTIFF;
confirm the XYZ export datum before assigning positional accuracy. Pixel-edge
coordinates follow the complete inverse affine, including rotation.

## Observations and measured runs

Input: 4841 × 2391 RGB uint8 raster, EPSG:4326, 690 reference rows, all inside
raster bounds. Two duplicate coordinate rows are retained with distinct IDs.
The representative inspected crop shows points near the main integer, with a
lower, often detached decimetre. This is preliminary alignment evidence only.
Neither the reference's completeness nor every pairing has been verified.

| Proposal glyph height | Windows | Candidate regions | Cold seconds |
|---|---:|---:|---:|
| 32 px | 28 | 360 | 7.14 |
| 64 px | 28 | 151 | 10.29 |

Linux CPU, two OpenCV threads. Whole-process peak RSS for the 64 px run was
246.96 MiB (includes raster/PROJ libraries and output rendering). These are raw
proposal counts, **not found soundings**. In inspected overlays the existing
morphological detector frequently separates the integer and lower decimetre.
Increasing the scale alone does not solve the layout. No recognition accuracy,
false-positive rate or XYZ accuracy is claimed from these runs.

Raster windows have a halo of five glyph heights. A candidate belongs only to
the core containing its centre. This avoids trivial duplicates for identical
boxes at core boundaries; tile-context changes can still fragment or shift
boxes. A seam regression on independently labelled examples remains necessary.
The reader holds one expanded tile plus its preparation arrays and a bounded
1800 × 1000 overview. Raster compression and internal block layout can affect
I/O performance; a 500 MB original and Windows 8 GB have not yet been measured.

## Next processing experiment

Build and validate a layout-aware association of the main integer and a lower
small digit. Preserve both possible associations when close neighbouring
soundings make the choice ambiguous. Use confirmed pixel boxes to score detection
independently from reading; never use the XYZ depth to select or correct OCR.
Before personalized character recognition, separate user-provided training
examples from held-out regions and compare accepted-error rate and coverage.

## Validation

28 experimental tests pass, including four new tests for malformed coordinate
rejection, duplicate preservation, rotated affine inversion and exact core
coverage. Existing printed-chart application files are untouched. Generated
reference overlays and source data remain outside Git, consistent with repo policy.
