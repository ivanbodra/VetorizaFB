# Grouping performance audit

This is the historical 0.1 audit. Version 0.2 adds Y-bucket indexing while
preserving the greedy grouping decisions; see [restoration validation](RESTORATION.md).

Audit date: 2026-10-22. Audited OCR branch commit:
`e41353dc2e29e62f8bcadb1bac75f5f5d0e3fa2a`.

## Finding

**The received/registered source contains the sequential grouping optimization,
and the modern core preserves its main search strategy.** It does not contain
Union-Find, BFS, KDTree or a two-dimensional spatial index.

| Location | Implementation | Status |
|---|---|---|
| `legacy/v3_1/ocr_segmented.py` | `group_digits_by_position` | Original uploaded bytes preserved on `main` and OCR branch |
| `src/vetorizafb/core.py` | `group` | Active implementation on `ocr-modernization` |
| `legacy/v4_prototype/main.py` | OCR/export callbacks | Placeholders; not the current runnable application |

Both grouping functions sort digits by horizontal centre, scan forward only
while candidates remain within the horizontal distance from the last accepted
digit, track used digits and stop at four digits per group. This avoids a global
combinatorial search for candidate digit combinations. The modern version adds
relative spacing based on character height; it does not reproduce every legacy
numeric rule or coordinate convention identically.

The historical conversation identifies the user's stable application as
3.0.1/EasyOCR and records an efficient grouping algorithm. Earlier discussion
also considered a horizontal window with Union-Find, followed by sequential
greedy grouping. These historical descriptions do not establish which exact
3.0.1 file the user last executed. The supplied seven-file snapshot contains
PaddleOCR integration attempts, not a complete verified copy of that EasyOCR
release. Therefore the audit confirms the algorithm present in the available
files, not byte identity with an unavailable historical executable or source.

Remote Git blob hashes were checked against the local legacy grouping file and
modern core/CLI/GUI before this audit. No processing code was changed as part of
this audit or the user-guide update.

## Measured grouping time

The previously generated `*.digits.json` files were read and passed through
grouping directly. Segmentation, model loading, OCR, file conversion and preview
drawing are excluded. Three repetitions; table values are medians on this
Linux/Python 3.12 environment. N includes all OCR boxes, including readings
subsequently rejected by the grouping filter.

| Input | OCR boxes | Modern grouping (s) | Legacy grouping (s) | Modern groups |
|---|---:|---:|---:|---:|
| 21300plano | 411 | 0.0022 | 0.0092 | 163 |
| 1410geotiff | 9,556 | 0.0617 | 0.1153 | 3,077 |
| 1822geotiff | 9,973 | 0.0538 | 0.1344 | 2,826 |

The legacy dataframe is prepared with string digits outside the timer to avoid
its separate floating-point dtype rejection issue. Its internal conversion and
sorting remain timed. Legacy and modern grouping use different filtering,
spacing and output semantics, so these timings are not a correctness-equivalent
speedup claim. They show that grouping is small in these runs. Complete-pipeline
times of 16.9/244.8/259.4 s were measured earlier, not in the same timing session;
do not subtract these medians to derive an exact OCR-only time.

## Complexity and stress case

This is not an exponential algorithm. Sorting is O(n log n); scanning costs
depend on the number of candidates inside each horizontal window. With bounded
local density, growth can be near linear after sorting. **The worst case remains
O(n²)**: if many characters share the same X but lie outside one another's Y
tolerance, every forward scan can inspect most remaining characters. The
four-digit group limit does not bound the number of rejected candidates scanned.

| Synthetic input digits | Sparse pairs: modern (s) | Same X, distinct Y: modern (s) |
|---|---:|---:|
| 500 | 0.0036 | 0.0774 |
| 1,000 | 0.0064 | 0.3192 |
| 2,000 | 0.0132 | 1.3300 |
| 4,000 | 0.0296 | 5.0423 |

The adversarial doubling pattern demonstrates the quadratic limit. It is not a
prediction of a particular chart's time. Future hardening could add a Y-aware
spatial index, preserving group order and decimal decisions with regression
tests; no such change is claimed here.

## Reproduce

Install `.[ocr,test]` (which includes pandas transitively) or install pandas
separately in a core-only environment. Generate the three full-chart results
with the current CLI, then run from the repository root:

```powershell
.venv\Scripts\python.exe scripts/benchmark_grouping.py `
  --output results/grouping-performance.json `
  --digits-files `
  results/21300-small/21300plano.digits.json `
  results/1410-small/1410geotiff.digits.json `
  results/1822-small/1822geotiff.digits.json
```

Omit `--digits-files` to run only the two synthetic scaling cases. The
[raw report](experiments/grouping-performance.json) records repeated timings,
source hashes, configurations and input hashes. The script extracts only the
legacy grouping function via AST; it does not import its eager OCR initializer.
