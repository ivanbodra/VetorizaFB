# Review navigation and directed numeral-one retry (0.3.0)

Updated 2026-10-23. Branch `ocr-modernization`, PR #1. The staged processing,
inspection, editing and export tools introduced in 0.2 remain available.

## Operator workflow

The table and chart now handle arrow navigation, range selection, individual
toggles, select-all/clear/invert and batch approval/rejection. The active row is
tracked separately from the selection, so a multi-selection follows its active
point rather than repeatedly jumping to its first member. Zoom is calculated
from the sounding bounds, with a cap and context margin. Following can be
disabled. Filtered views and bulk actions preserve point IDs and dated history.

Ctrl+A approves, Ctrl+X rejects, Ctrl+E edits one value, and Ctrl+Shift+A selects
all visible rows. These bindings apply only to the review table and chart;
text fields keep their own bindings. The [guide](USER_GUIDE.md#5-navigate-and-review)
documents every shortcut and the exact meaning of filtered select-all.

Review item lookup now uses an ID index. Approving a selection no longer scans
the entire review list to find each successive point. The existing Y-bucket
grouping algorithm is retained; its equivalence regression tests still run.

## Numeral 1: actual inference rather than forced substitution

The user's screenshot contains 10.8, 10.1, 11, 11.1 and 10.5 on cyan background.
Those five soundings were located in the original `21300plano.tif`. Narrow
slanted ones can be returned as `I`, including the decimal character. The
existing binary/padded/2x retry recovers these glyphs, but was off by default.

New `retry_one=true` enables a directed pass by default. It selects only narrow
unresolved stroke-like readings outside apparent letter contexts. A spatial
grid supplies local neighbours. A real second model reading must return exactly
`1` with score at least `max(0.80, min_confidence)`. Original text/confidence,
alternative text/confidence and the selection method remain in the digit record.
Recovered groups are flagged `ocr_one_retry` and start unreviewed. Zero and
multi-character crops are not forced into ones. Failed retries remain unresolved.

The context filter is a heuristic, not a cartographic classifier. Optional
broader retry remains available and can still admit letters or line fragments.
There is no automatic approval or guaranteed separation of every printed I/1.

## Reproducible diagnostic evidence

PP-OCRv6 small, PaddleOCR 3.7.0 / PaddlePaddle 3.3.1 / PaddleX 3.7.2, CPU.
Input hashes, model-file hashes, configuration, digit traces and all four
segmentation/grouping combinations are stored in the linked reports.
The primary comparison below uses `legacy` segmentation and `relative` grouping.

| Diagnostic set | Primary OCR only | Directed-one retry |
|---|---:|---:|
| Five screenshot sounding crops: exact complete values | 2/5 | 5/5 |
| Printed word TIDE: false sounding detections | 0/1 | 0/1 |
| Earlier development set: exact positive sounding crops | 17/19 (0.1 recorded run) | 18/19 |
| Earlier contour-label negatives: false positives | 2/2 (0.1 recorded run) | 2/2 |

The five new positives are supplementary cases and do not replace the older
denominator. All annotations were read by the assistant and need independent
review; neither set measures complete-chart accuracy. The unresolved older
positive contains the expected 26.5 plus a spurious 7. The two contour-label
false positives remain an explicit classification limitation.

- [Fixed coordinates/annotations for screenshot cases and TIDE](experiments/one-reference.json)
- [Primary-only crop results](experiments/one-before.json)
- [Directed retry crop results](experiments/one-after.json)
- [Earlier 19-positive/2-negative set with directed retry](experiments/crops-directed-one.json)
- [Full-chart 21300 processing and checked cases](experiments/one-full-chart.json)

A separate whole-chart run processed all 411 segmented boxes, retried 35 and
selected 32 alternative ones. Checking only the same five locations again gave
2/5 before and 5/5 after, and TIDE produced no points. The printed I in TIDE
remained unresolved, rather than being turned into a sounding. Counts of extra
digits or candidates are not accuracy measurements for the rest of the chart.

Run the crop comparison from the repository root after installing OCR extras:

```powershell
python scripts/benchmark_crops.py --data-dir "C:\cartas" --model PP-OCRv6_small_rec --model-dir "C:\modelos\PP-OCRv6_small_rec_infer" --reference docs/experiments/one-reference.json --no-retry-one --output before.json
python scripts/benchmark_crops.py --data-dir "C:\cartas" --model PP-OCRv6_small_rec --model-dir "C:\modelos\PP-OCRv6_small_rec_infer" --reference docs/experiments/one-reference.json --output after.json
```

For the original sample set, omit `--reference`. `--no-retry-one` reproduces the
primary-only path; `--retry-ambiguous` additionally enables broader retry. Input
rasters, model weights and screenshots are not committed.

## Regression coverage

The 67-test suite includes actual Tk keyboard events and worker completion,
range/toggle/canvas selections, active-point zoom, batch history, filtered
select-all/advance, text-field key scope, stale-state blocking, targeted retry
thresholds, zero/multi-character preservation, word contexts, adjacent ambiguous
ones, old-project migration, coordinate/export integrity and indexed grouping
equivalence. On headless Linux run `xvfb-run -a python -m pytest -q`; Windows runs
`python -m pytest -q`. No model download is needed for unit/GUI tests; the real
model experiments above are separate evidence.
