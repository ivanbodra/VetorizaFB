# Raster chart OCR experiment — 2026-10-22

This report records the initial 0.1 runner. Version 0.2 restores staged controls,
adds point review and an optional OCR retry; see [restoration validation](RESTORATION.md).

The original seven source files are preserved in `legacy/`, with their original
line endings and checksums. This experiment evaluates the new modular runner;
it does not independently reproduce the author's reported 100% baseline result.

## Why the original settings do not transfer

The supplied `21300plano.tif` is 600 dpi, whereas `1410geotiff.tif` and
`1822geotiff.tif` are 300 dpi. Character dimensions therefore differ in pixels.
The original contour filters and grouping tolerances were fixed pixel values.
Other differences include denser content, contour crossings and cartographic
symbols. DPI scaling addresses only one part of that distribution change.

Source inspection also found API and data-handling problems: the legacy code
mixes PaddleOCR interfaces, has fallback paths that can mishandle zero or insert
replacement digits, and can reject digit columns converted to floating point.
The v4 prototype's OCR/export functions are placeholders. Missing splash/logo
assets and an absent original dependency lockfile further limit baseline
reproduction.

The update uses PaddleOCR 3.7.0/PaddlePaddle 3.3.1 and its `TextRecognition`
interface, retains raw text, rejects ambiguous multi-character digit crops and
never inserts replacement digits or increases confidence. Coordinates use the
declared input CRS and full affine transform, with explicit XY order and without
an additional half-pixel shift.

## Small diagnostic set

The set contains 19 sounding crops and two negative crops (contour labels),
selected manually from the three supplied charts. Coordinates and annotations
are in [crop_reference.json](experiments/crop_reference.json). The annotations
were visually read by the assistant and **have not been independently reviewed**.
No complete chart has a reviewed reference XYZ.

For a positive crop to pass, the pipeline must return exactly one candidate with
the complete expected depth; extra candidates also fail the crop. A negative
passes only if no candidate is returned. Pixel anchors are not scored here.
The images remain external; each report identifies them by SHA-256 and size.
Models were downloaded from the official PaddleOCR inference-model catalogue;
reports record the model-file checksums and installed OCR versions.

| Recognition model | Fixed grouping, legacy segmentation | Relative grouping, legacy segmentation | Contour-label crops falsely accepted |
|---|---:|---:|---:|
| PP-OCRv5 server | 4/19 | 16/19 | 2/2 |
| PP-OCRv6 small | 5/19 | 17/19 | 2/2 |
| PP-OCRv6 medium | 4/19 | 17/19 | 2/2 |

Relative grouping adapts spacing to detected character height. This allows
lower-positioned decimetres to remain grouped with the integer part. It was
developed using this diagnostic set; these are development results, not a
held-out estimate of generalization. All models/configurations accepted the
two contour labels. A black-ink segmentation alternative did not improve the
relative-grouping result: v5 16/19, v6 small 16/19, v6 medium 15/19.

| Chart | Positive crops | v5 server | v6 small | v6 medium |
|---|---:|---:|---:|---:|
| 21300plano.tif | 5 | 5 | 5 | 5 |
| 1410geotiff.tif | 6 | 5 | 5 | 5 |
| 1822geotiff.tif | 8 | 6 | 7 | 7 |

This second table uses relative grouping and legacy segmentation. Detailed
readings, including rejected characters and full-crop OCR, are available in:

- [PP-OCRv5 server](experiments/ppocrv5-server-crops.json)
- [PP-OCRv6 small](experiments/ppocrv6-small-crops.json)
- [PP-OCRv6 medium](experiments/ppocrv6-medium-crops.json)

Examples explain the remaining failures. In crop s16 (depth 1.8), the small
recognizer originally returns `I` for the first character; the strict numeric
filter removes it, leaving 8.0. The earlier diagnosis that segmentation lost
this character was incorrect: its box is present. The 0.2 optional second OCR
reading recovers `1` with the original and alternative readings retained.
Small produces an extra 7.0 alongside the correct
26.5 in s11. Medium misses the 3 in depth 32 in s07. Full-crop OCR frequently
returns `87`, `235` or `08`, without the decimal implied by chart typography;
plain string-to-number conversion would therefore also produce wrong depths.

PP-OCRv6 small is the provisional default because its count matches medium on
this tiny set with a smaller model. Different cases fail for each variant; no
claim of broad superiority is supported. Elapsed times are recorded for audit,
but concurrent CPU workloads make them unsuitable as a speed ranking.

## Complete chart execution

The runner is also exercised on the complete three rasters with v6 small,
legacy segmentation, relative grouping and automatic TIFF DPI. Metadata and
structural export checks are recorded in
[full_chart_smoke.json](experiments/full_chart_smoke.json).

| Complete raster | Character boxes | Numeric readings | Unreviewed XYZ candidates | CPU elapsed seconds |
|---|---:|---:|---:|---:|
| 21300plano.tif | 411 | 292 | 163 | 16.9 |
| 1410geotiff.tif | 9,556 | 4,631 | 3,077 | 244.8 |
| 1822geotiff.tif | 9,973 | 4,615 | 2,826 | 259.4 |

All exported rows have exactly three finite XYZ columns; their depths and row
counts match the provenance CSV. Transforming exported XY back to pixels
recovered the stored candidate centres with maximum error below 0.000003 pixel.
This checks transformation consistency, not whether the text centre is the
cartographically correct sounding position. Large runs overlapped on the CPU;
the recorded times are observations from this environment, not a speed benchmark.

These runs check that full images can pass through OCR, grouping and geographic
XYZ export. Candidate counts are **not** counts of correctly extracted soundings.
No precision, recall, depth accuracy or geographic anchor accuracy is claimed
for a complete chart. The synthetic coordinate regression tests do not replace
comparison with surveyed or manually verified cartographic anchors.

## What is validated and what remains

There are 26 automated core/pipeline checks, covering zero, subscript decimals,
raw readings, OCR batch ordering, DPI scaling, CRS/datum conversion, rotated
affines, axis order and synthetic GeoTIFF-to-XYZ output. The real-model crop and
complete-image experiments supplement these tests. Windows installation and
the Tkinter window have not been exercised in this environment.

The runner still loads whole images into RAM, has no chart-frame mask or
cartographic classifier, uses a geometric text-box centre as an unverified
point anchor, and has no correction/approval editor. Removing an unreadable
character can leave a wrong partial depth. Confidence is the minimum OCR score
among retained characters; it is not a calibrated sounding-level probability.

Before consolidation, create a reviewed dataset across chart styles, including
contour labels and crowded areas; reserve whole charts for held-out evaluation.
Score detection precision/recall, exact complete depth, decimal interpretation
and XY error separately. Then evaluate a sounding detector/classifier and
introduce correction and approval before final export.

The photographed historical FB is a later, separate task. Handwriting, variable
illumination, overlapping annotations and decimal conventions need separate
labels and experiments. The supplied crop is 8.46 MB, while the full original
is reported as approximately 135 MB. It was not included in these OCR scores.

## Official model references

- [PaddleOCR text-recognition module and inference models](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/module_usage/text_recognition.en.md)
- [PP-OCRv6 architecture and usage](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-OCRv6/PP-OCRv6.en.md)

Upstream general OCR benchmark percentages are not chart sounding extraction
scores and are not compared numerically with this diagnostic set.
