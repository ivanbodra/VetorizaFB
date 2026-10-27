# FB 5.0: first measured experiment

The region-first geometric prototype finds 53 of 59 distinct reference soundings
and reads 34 complete values correctly out of 58 readable reference values.
There are still 20 unmatched regions and six missed soundings. This supports
further isolated development; it is insufficient for automatic extraction or
UI integration. No definitive detector or handwriting model is selected.

All application files remain byte-for-byte at 4.0.5 commit `e48583f`. The dedicated
branch contains additions only under `experiments/fb_v5`.

## Input and reference

- TIFF: 2,858 × 1,563, RGB uint8, 13,401,948 bytes, 96 dpi metadata.
- Declared CRS: EPSG:22524, Córrego Alegre 1970–72 / UTM zone 24S.
  Pixel spacing: 0.565794446 m; filename text is not used to infer a CRS.
- Six exact native-pixel windows: regular handwriting (A), lowered decimetres
  and touching strokes (B), curved contour (C), grid (D), damage/fading (E),
  and coast/coordinate-annotation negatives (F).
- 59 distinct sounding regions; 58 provisionally readable values. E04 has an
  ambiguous 4/9 decimetre and is detection-only. C04 is ignored because it is the
  same original sounding as A13; global source boxes exposed the duplication.
- Visual labels are provisional assistant annotations, awaiting the user's
  adjudication. This is one development sheet, not an independent test set.
  Ignored margins contain clipped text; ambiguous contour-only semantics are
  ignored rather than assigned invented sounding labels.

The separately supplied `sample/reference.json` records source SHA-256, original ROI
origins, native boxes, readings, exclusions and annotation protocol.

## Metric definitions

A detection is a one-to-one region/reference match at bounding-box IoU ≥ 0.5.
Maximum-cardinality matching avoids double-counting fragmented detections. This
is a region-overlap metric; it does not certify that every handwritten stroke
was captured. In the stable baselines, final regions are measured **after** their
existing OCR/grouping; the raw glyph-box metric is retained separately in JSON.

Unmatched evaluated regions include spurious ink and fragmented/bad boxes.
Ignored areas are excluded, without overriding overlaps with known positives.
A complete correct reading requires both the principal integer and the optional
decimetre to match; leading integer zeros do not change the integer. Failed and
non-numeric readings are retained as abstentions. No letters are guessed as
digits and no depth-neighbour correction is used.

Integer/decimetre errors below are measured only on matched, readable references
and may overlap. Missing detections are reported through the found count rather
than invented integer/decimetre readings. The complete-correct count is also
reported against all 58 readable references, so misses cannot improve it.

## Detection through final interpretation

| Method | Found /59 | False regions | Complete correct /58 | Integer errors* | Decimetre errors* | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|
| 4.0.5, default / TIFF 96 dpi | 0 | 80 | 0 | — | — | 24.21 | 700 |
| 4.0.5, black / native-size calibration | 24 | 39 | 20 | 2 | 3 | 19.01 | 702 |
| FB geometry, normalized / no straight-line masking | 52 | 19 | 24 | 23 | 27 | 11.80 | 693 |
| FB geometry + straight-line masking / whole crop | 53 | 20 | 24 | 24 | 28 | 12.18 | 701 |
| Paddle detector, original / native scale | 27 | 33 | 14 | 9 | 13 | 10.08 | 709 |
| Paddle detector, normalized / native scale | 28 | 31 | 17 | 7 | 11 | 10.78 | 716 |
| Paddle detector, original / 2x scale | 27 | 31 | 12 | 11 | 14 | 11.42 | 928 |
| Paddle detector, normalized / 2x scale | 26 | 29 | 9 | 12 | 14 | 11.63 | 930 |
| FB geometry + straight-line masking / automatic parts | 53 | 20 | 34 | 4 | 17 | 18.11 | 694 |

*Conditional denominators differ by method. The automatic-part prototype has
52 matched readable references, 34 exact readings, 4 integer errors and 17
decimetre errors; three cases have both errors. It also misses six sounding
regions. Its 20 false regions consist of 19 spurious regions and one fragment/
malformed box. Recognition of false candidates is not counted as a true reading.

`stable_96` uses the current default `Config(dpi=96)`. Its size limits become too
small for these handwritten glyphs. `stable_600_black` uses
`Config(dpi=600, segmentation="black")` to test the current algorithm with larger
native-pixel limits and tolerances. It does not resize or re-georeference the
TIFF. Both retain the stable single-digit recognition/grouping logic, including
its directed-1 retry. This controls for DPI without modifying the application.

The geometric variants use declared 32 px glyph height, 51 px background closing,
CLAHE, threshold 175, short stroke grouping and optional 128 px straight-line
masking. OCR reads original pixels, not the line-erased mask. Paddle variants
use the same mobile detector with its packaged defaults, `limit_type=max`, side
limit 960, at native and explicitly inverted 2x input scale. These settings are
comparators; no detector hyperparameter search or model fine-tuning was done.

## Recognition isolated from detection

The same manually boxed reference crops are recognized independently of any
candidate detector. Both strategies use the same `PP-OCRv6_small_rec` weights.
Whole-crop recognition still uses detected layout evidence to interpret the
last digit; it is not scored as plain digit transcription alone. In the parts
strategy, regions without an automatically separable lower-right part fall
back to a whole-crop reading, preserving failures and context.

| Strategy | Complete correct | Integer errors | Decimetre errors | Abstentions | Recognition seconds |
|---|---:|---:|---:|---:|---:|
| Whole crop + layout interpretation | 25/58 | 29 | 32 | 25 | 5.72 |
| Automatic integer/decimetre parts | 37/58 | 8 | 19 | 13 | 10.43 |

Automatic separation improves exact reference-crop readings from 25/58 (43.1%)
to 37/58 (63.8%). This demonstrates a representation/layout bottleneck with the
existing small recognizer. It does not establish that separation is always
beneficial: connected parts and very narrow decimetres remain difficult.

Examples in the visual audit include A02 (10.9 recovered by separate reading),
A04 (11.1 loses a principal 1), A13 (10.7 becomes 10.1), B13 (8.9 becomes 89 when
joined parts are not separated), and D01 (8.3 joined to a grid becomes 83). Raw
texts and genuine model scores are retained; even a high score cannot settle
those cartographic/handwriting ambiguities.

## Automatic-part prototype by condition

| Tile | Reference regions | Found | False regions | Complete correct | Integer errors* | Decimetre errors* |
|---|---:|---:|---:|---:|---:|---:|
| A | 16 | 15 | 5 | 10 | 2 | 4 |
| B | 14 | 14 | 5 | 7 | 2 | 7 |
| C | 10 | 7 | 2 | 7 | 0 | 0 |
| D | 8 | 6 | 3 | 3 | 0 | 3 |
| E | 11 | 11 | 3 | 7 | 0 | 3 |
| F | 0 | 0 | 2 | 0 | 0 | 0 |

The six missed reference IDs are A04, C03, C08, C09, D01 and D03. Three are in the
curved-contour window and two in the grid window. The negative coast window
still produces two false regions. Straight-line masking changes the geometry
baseline from 52 to 53 found regions and from 19 to 20 false regions; this modest
tradeoff is not enough to adopt blanket line removal. The original ink remains
available, and single isolated 1 strokes are covered by a synthetic test.

## Timing, memory, cache and full-sheet preview

Measurements were made sequentially in fresh Linux x86-64 Python 3.12.14 CPU
processes, with two inference threads, GPU disabled and MKL-DNN disabled for the
common comparison. Peak RSS uses `/proc/self` and the kernel high-water mark,
plus 10 ms sampling; it is not Python-only allocation memory. This also avoids
the executor's PID-namespace mismatch. Input/output, model initialization and
processing are included in the end-to-end wall times; recognition-only timings
exclude model initialization. Model fingerprints, versions, stage times and
per-tile cache-hit fields are preserved in every run record.

The tabulated run used a new, empty reading-cache directory. Preparation could
be shared across methods and the identical geometric region result could be
shared between whole/parts variants. No tabulated method reused cached OCR
readings. A repeat is a separate cache-reuse measurement:

- Whole/parts prototype repeat: 2.78 s; all four caches hit for all six windows. Model initialization is still included in this benchmark process.
- Detection-only full TIFF: 1.03 s, 234 MiB peak RSS, 460 **unreviewed candidates**. No recognition or recognizer initialization. This is not a count of true soundings.
- Repeated full-sheet preview: 0.76 s, both preparation/region caches hit; no recognition.

These are single-run observations on this environment and supplied raster,
not a Windows performance guarantee. A real Windows CPU machine with 8 GB RAM,
additional sheets, larger rasters and tiled seam handling remain to be tested.
The small recognizer archive is about 20.4 MiB and mobile detector about 4.7 MiB;
no handwriting-specific or large language/vision model was downloaded.

## Visual evidence

`evidence/images/comparison_focus.png` in the supplied evidence archive compares
stable native-size calibration (left) with FB geometric proposals (right).

Green means a matched region, not a verified value. Red means a false or
fragmented evaluated region; gray means ignored. Regions touching the curved
contour and grid remain visible failures instead of being hidden.

`evidence/images/recognition_comparison.png` compares whole-crop and
automatic-part readings for every reference crop.

`?` means an unresolved/non-numeric reading. E04 is not scored for recognition.

The separately supplied `VetorizaFB_5_0_Evidencias.zip` includes the full-sheet
overlay (`evidence/full/candidates_overview.png`), native-resolution overlay,
all detector comparisons, raw readings, machine-readable summary and validation
record. Source-image windows and generated outputs remain outside Git.

## Decision for the next increment

Continue with a separate FB session, full-region proposals and explicit
integer/decimetre structure. Preserve both whole/part evidence and unresolved
regions for review. First adjudicate this reference and the sounding anchor,
expand the sheet-level corpus, and improve line-contact/annotation handling.
The tested Paddle detector settings do not justify replacing geometric proposals
in this sample; another detector or handwriting model needs a measured gain on
held-out sheets. No approach is integrated into the GUI at this stage.

The [architecture](ARCHITECTURE.md) specifies the independent FB path, the four
cache dependencies, future merge/split history, native-coordinate mapping and
reuse of review/geospatial/export operations. The PoC deliberately assigns no
cartographic sounding anchor and produces no XYZ.

Validation: 24 FB processing/cache/detection/interpretation/download/preview tests
and 146 existing stable-processing tests passed. GUI tests were not rerun because
no GUI or existing application file was changed. The proof of concept and
results are the complete scope of this first increment.

Primary model/API references: [official Paddle text detection documentation](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/module_usage/text_detection.en.md)
and [text recognition documentation](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/module_usage/text_recognition.en.md).
