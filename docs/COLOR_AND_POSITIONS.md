# Colour rejection and position editing (0.4.0)

Updated 2026-10-23. Branch `ocr-modernization`, PR #1. OCR recovery and indexed
grouping are retained; this update filters segmentation candidates and extends
the review tools rather than replacing the workflow.

## Yellow backgrounds

The optional filter inspects original RGB pixels in each size-eligible character
box plus a small margin (`max(2, round(2 × DPI/reference DPI))`). Pixels with
`max(R,G,B) < 128` are ignored as dark ink. Among the remaining pixels, a yellow
pixel satisfies `R-B >= yellow_delta` and `G-B >= yellow_delta`, using signed
arithmetic. Reject the box if that fraction reaches `yellow_min_fraction`.
Defaults are 25 and 0.60; `exclude_yellow` defaults to false. There is no OCR
inference for rejected boxes. White, grey, cyan/blue and mixed-boundary controls
are covered by regression tests. Some yellow-green tints are intentionally
included by this channel relation; it is not a semantic land/water classifier.

Accepted boxes retain their native coordinates. Rejected boxes have a dedicated
viewer layer and count, are reconstructed on project load from the source/config,
and the GUI export metadata records their count. The source raster and mask are
not recoloured. Old projects without the new settings retain the disabled filter.

The [native-chart smoke record](experiments/yellow-filter-smoke.json) uses the
default legacy segmentation with each TIFF's actual DPI, changing only the
filter flag:

| Chart | Boxes before | Boxes after | Rejected by colour |
|---|---:|---:|---:|
| 21300 | 411 | 411 | 0 |
| 1410 | 9,556 | 8,071 | 1,485 |
| 1822 | 9,973 | 7,692 | 2,281 |

No boxes within the earlier 19 positive diagnostic sounding crops were rejected.
This is a segmentation-only retention check, not an OCR rerun or complete-chart
accuracy estimate. Rejection counts have not been independently classified as
all valid exclusions; review the colour layer on the intended chart. Rasters
and screenshots are not committed. Reproduce with:

```powershell
python scripts/benchmark_color_filter.py --data-dir "C:\cartas" --output yellow-filter-results.json
```

## Direct tools and offsets

The existing click-to-insert and click-to-move modes are exposed as review-panel
buttons. One-click activation, cursor feedback, Esc cancellation, numeric X/Y
editing, validation and automatic selection of inserted points make them easier
to use. Review-note/history preservation and pending-after-edit semantics remain.

Offset preview and application share full-batch validation. Offsets are
incremental in original pixels or source projected-grid metres, using unit
conversion and the complete inverse affine. Geographic source CRSs are rejected
for metre offsets. Targets can be all points, including hidden/rejected ones, or
the explicit selection. Out-of-bounds/nonfinite targets reject the whole batch
before mutation. Zero offset does not append history or reopen approval.

The original record, depth and text bounds are preserved. Moved accepted points
become pending; rejected points stay rejected. Each per-point record includes a
common batch ID, requested units/deltas, pixel deltas and before/after snapshots.
Project round trips and approved-only XYZ export after editing are tested.

The 104-test suite covers signed colour differences, background/ink separation,
mixed boundaries, ROI coordinates, cache invalidation, old projects, original
values/history, batch atomicity and scope, source-map offsets with rotated affine
and projected foot units, geographic-CRS refusal, zero offset, actual Tk dialogs
and shortcuts, hidden-row insertion, and control visibility at 1050 × 720.
Earlier OCR-one and grouping-equivalence tests remain included. The segmentation
panel scrolls; notes/status are allocated before the expandable review list so
additional controls do not hide them at the minimum window size.

See the [user guide](USER_GUIDE.md) for controls, units and update instructions.
