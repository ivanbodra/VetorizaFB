# Restored tools and validation - 0.2.0

Date: 2026-10-22. Branch: `ocr-modernization` / PR #1.

The first experimental interface removed important working tools from the
received application. Version 0.2 retains the modern OCR integration and restores
staged operation, calibration and inspection. It also adds explicit point review
and resumable projects. It does not claim an independently reproduced historical
EasyOCR 3.0.1 executable or proven 100% full-chart accuracy.

## Functional changes

| Working need | Version 0.2 implementation |
|---|---|
| Segmentation calibration | Editable DPI, grayscale/black mask, threshold, blur/dilation, size limits, applied-parameter histograms |
| Intermediate inspection | Original, mask, character boxes, OCR and sounding layers; zoom around pointer, pan, fit, 100%, point focus and character crop/reading popup |
| Control by stage | Separate segmentation/OCR/grouping/export, stage signatures and cached OCR reuse when only grouping changes |
| Work on a local area | Drag a rectangular ROI; processing preserves original raster coordinates; one working ROI per project |
| Difficult characters | Optional real second model reading after binary normalization, white padding and 2x enlargement; original text/score and alternative remain recorded |
| Correct final results | Correct depth, reposition anchors, add missed points, reject spurious points, explicitly approve and attach review notes |
| Resume work | JSON review project with source SHA-256, configuration, ROI, digit readings, originals and dated decision history; moved source can be located again |
| Traceable export | Separate candidate/accepted-only bundles, including raw readings, full review history, metadata, hashes and preview |
| Reduce repeated comparisons | Y buckets merged in original X order, retaining greedy decisions while reducing vertical-column scans |
| Windows GIS conflict | Standalone entry points use wheel data instead of inherited PostGIS paths; no persistent system settings are changed |

Original uploaded files under `legacy/` are unchanged. Old assets/branding are
not recreated. Geometric guesses with fabricated confidence are not reinstated;
the second OCR reading and explicit manual corrections provide traceable ways
to recover difficult digits. ROI processing is not a tiled input reader.

## Real OCR comparison

The same small development set still has **19 positive crops and two contour-label
negative crops**: 5 positives on 21300, 6 on 1410 and 8 on 1822. The assistant's
annotations are not independently reviewed, and these samples were used during
development. They are not a held-out or complete-chart reference.

| v6 small, legacy segmentation, relative grouping | Positive crops correct | 1822 positive crops correct | Contour negatives falsely accepted |
|---|---:|---:|---:|
| Initial single reading | 17/19 | 7/8 | 2/2 |
| Optional normalized second reading | 18/19 | 8/8 | 2/2 |

Crop s16 has expected depth 1.8. The first reading of its narrow integer digit
is `I` with score 0.511219; the second reading is `1` with score 0.993863, retained
as a separate real model result. The initial report's statement that segmentation
lost this digit was incorrect: its box exists. The remaining s11 failure still
contains an extra 7.0 alongside correct 26.5. The black-mask variant remains
16/19 and can gain an extra line-fragment candidate with retry. Retry is therefore
**off by default**; it is a calibration option, not a universal improvement.

Full raw readings, configurations, input/model hashes and summaries are in
[ppocrv6-small-retry-crops.json](experiments/ppocrv6-small-retry-crops.json).

## Complete-chart consistency and execution

With cached original readings and retry off, the new grouping produced exactly
the prior depths, confidence, pixel positions, bounds and digit memberships on
all three complete charts: 163 / 3,077 / 2,826 candidate groups. This is a
no-change comparison against the earlier experimental runner, not a correctness
comparison against independently reviewed soundings or the historical stable app.
See [full-chart grouping equivalence](experiments/grouping-full-chart-equivalence.json).

The complete 1822 raster was also run again through real v6-small inference with
retry enabled. All 9,973 segmentation boxes and all first-pass OCR texts matched
the earlier run. Retry was attempted on 5,447 ambiguous/low-score crops; 947
alternate readings were selected. Numeric readings increased from 4,615 to 5,535
and candidate groups from 2,826 to 3,244. **An increased count is not an increased
count of correct soundings.** Extra contour/land/annotation candidates remain
possible. No full-chart precision/recall or accuracy percentage is claimed.

Recorded metadata/export checks are in
[1822 retry execution](experiments/1822-retry-execution.json).
This full extraction ran against development source via PYTHONPATH while the
installed package metadata still identified the earlier 0.1.0 build; that
observed version is retained in the report. Release source/package version is
0.2.0, and package-build/CI checks verify its installation separately.

## Grouping performance

The pre-index search could repeatedly inspect most of a vertical column.
The new implementation buckets Y, then lazily merges candidate indices in their
original X order. It avoids allocating a copy of every remaining candidate list.
The horizontal stopping and four-digit greedy decisions remain the same.

| Synthetic same-X, distinct-Y digits | Previous X-window median (s) | New Y-index median (s) |
|---|---:|---:|
| 1,000 | 0.3192 | 0.0095 |
| 2,000 | 1.3300 | 0.0144 |
| 4,000 | 5.0423 | 0.0288 |

These are environment-specific observations in separate timing sessions, not a
universal complexity or speedup guarantee. Indexing adds overhead on sparse
pairs (new 4,000-digit case approximately 0.075 s versus previous 0.030 s).
Pathologically dense buckets can still require repeated scans; no universal
linear-time claim is made. Complete-chart grouping remained below 0.05 s on the
stored readings in this run. Raw results are in
[Y-index performance](experiments/grouping-y-index-performance.json).

## Automated validation

53 automated checks passed locally with an actual Tk display under Xvfb, including:

- The original zero, decimal, batch, DPI, CRS/datum, axis-order and affine cases.
- Indexed-versus-frozen-pre-index grouping equivalence on 120 randomized cases
  and a 6,000-character vertical column.
- Stage-cache invalidation, original-pixel ROI positions and geographic export.
- Cancellation before/between batches without replacing prior completed results.
- Original/alternative OCR scores, without multi-character truncation or guesses.
- Review corrections that require reapproval, exclusion of pending/rejected
  points from accepted-only XYZ, complete audit retention and output hash checks.
- Project save/load without inference, source-hash mismatch and malformed digit
  mapping rejection, no partial publish when coordinate validation fails.
- Actual Tk stage controls, progress completion, edits, ROI, zoom/layers and
  project saving, plus a subprocess with incompatible foreign PROJ variables.

GitHub Actions runs the suite on Linux with Xvfb and on Windows/Python 3.12.
These GUI tests use a deterministic fake recognizer to isolate workflow behavior;
real OCR was evaluated separately above. They do not reproduce the user's exact
Windows/PostGIS installation, monitor scaling or institutional network.

## Review and export guarantees

Changing relevant settings makes downstream stages pending and disables GUI
export until reprocessed. A model object is reused with the same specification;
grouping-only changes reuse valid reads. Cancellation occurs between stages or
batches, not inside a native model call or model download. Review operations run
on the UI thread while processing is idle.

Correcting a depth or position returns the point to pending. Manual points have
no OCR confidence. Accepted-only export rejects an empty approved set and never
includes pending/rejected records. It is not a completeness certificate: the
operator must inspect missing points too. Originals and review events remain in
the project and `.review.json` even when a point is excluded from XYZ.

All files are validated/staged before publication; metadata with hashes is
published last. A multi-file rename cannot be a single filesystem transaction,
so interrupted publishes are detected using the hashes. Projects contain the
applied processing state, not unprocessed parameter edits or embedded rasters.

## Remaining accuracy work

The automatic point location remains a geometric text-box centre until manually
repositioned. A chart-frame/water-area mask, sounding-vs-contour classifier,
trained detector, skew/line separation, tiled reading and independently reviewed
complete-chart reference are not implemented. They are not represented as
completed by the test count, UI restoration or the 8/8 development-crop result.

See the [current operating guide](USER_GUIDE.md) for installation, safe updating,
the staged controls, review operations, file meanings and coordinate conventions.
