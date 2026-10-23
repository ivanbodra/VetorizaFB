# Remaining numeral ones and marginal labels (0.3.1)

Updated 2026-10-23. Branch `ocr-modernization`, PR #1.

## Diagnosed failure and correction

In the follow-up screenshot, the lower 11.9 loses its first one and becomes 1.9.
Its original character box exists: `(652, 4298, 14, 35)` in `21300plano.tif`.
Primary OCR returns `I`; the 0.3.0 binary/padded retry returns `1.`. The latter is
correctly rejected as a multi-character reading. Neighbouring ink in the padded
crop is the observed source of interference, rather than a missing contour.

Version 0.3.1 gives failed directed candidates a final actual model reading:

1. Find the dominant connected ink component overlapping the original box.
2. Require a plausible size, dominant overlap within the box and substantial
   overlap with the component, rejecting empty/unsuitable crops.
3. Whiten other disconnected components, crop to the retained component, add
   white padding and enlarge 2x.
4. Accept only model output exactly `1`, with score at least
   `max(0.80, min_confidence)`. Otherwise leave it unresolved.

For the missed 11.9, the final model score is 0.988561. A second missed one in
an 11.1 at `(7218, 1619, 13, 35)` is recovered with score 0.983289. Its previous
complete sounding value was 1.1. There is no truncation of `1.` and no fabricated
score. The character box and geospatial transform are unchanged. Original and
both alternative readings remain recorded; method `ocr_one_isolated` uses the
existing `ocr_one_retry` sounding flag, and the result starts pending.

## Evidence and exact scope

The new benchmark loads the immutable 0.3.0 core blob
`e82216a38077fa26291c2400e68b818d0f436bb1` from commit `6b66bd5`, then runs the old
and new core with the same real PP-OCRv6 small model and inputs. Input, model and
current-core hashes, configurations and complete digit alternatives are recorded.

| Diagnostic set | 0.3.0 | 0.3.1 |
|---|---:|---:|
| Four sounding crops in the follow-up screenshot: exact complete values | 3/4 | 4/4 |
| Additional missed 11.1 outside that screenshot | 0/1 | 1/1 |
| Previous screenshot's five sounding crops | 5/5 | 5/5 |
| Earlier positive development crops | 18/19 | 18/19 |
| Contour-label negatives producing false positives | 2/2 | 2/2 |
| Marginal-coordinate negatives producing false positives | 2/2 | 2/2 |
| Printed-word negative producing false positives | 0/1 | 0/1 |

A separate full-chart comparison processed all 411 boxes. Only the two selected
digit readings above changed; the corresponding values became 11.9 and 11.1.
Candidate count stayed at 166, illustrating why candidate counts do not establish
recognition accuracy. All four checked screenshot locations match under the
default test configuration. A narrow marginal punctuation mark remains unresolved:
the isolated reading has score 0.639445, below the acceptance floor.

These are assistant-read diagnostic annotations, not independently reviewed
ground truth for the complete chart. The 18/19 and negative-set limitations
remain unchanged. The GUI tests and the real-model experiment are separate checks.
The 73-test suite passes locally under Xvfb, including exact-output/score guards,
component isolation, cancellation, actual Tk shortcuts, review history,
geospatial integrity and grouping-equivalence regressions. The 0.3.1 wheel
builds and its package sources match the working files.

- [Native-pixel follow-up annotations](experiments/remaining-ones-reference.json)
- [Before/after readings, hashes and whole-chart checks](experiments/one-isolation-validation.json)
- [Prior 0.3.0 validation](REVIEW_AND_ONES.md)

From a repository clone containing its history and an OCR-enabled environment:

```powershell
python scripts/benchmark_one_isolation.py --data-dir "C:\cartas" --model-dir "C:\modelos\PP-OCRv6_small_rec_infer" --output isolation-results.json
```

The script requires the original 21300, 1410 and 1822 GeoTIFFs and extracted
official PP-OCRv6 small inference files. It uses CPU and does not commit pixels
or weights. A ZIP/shallow checkout without the baseline blob cannot run the
historical comparison until the necessary repository history is available.

## Margins, rotation and contour labels

The operator's review remains the current decision mechanism for these false
positives. The example has vertically oriented coordinates on the left and
horizontal coordinates at the bottom. Text-line orientation could help identify
the former; it cannot remove both by itself. Stroke slant in italic ones is
also different from the orientation of a whole text line. No automatic rotation
filter or silent coordinate/contour rejection is introduced by this patch.

Use **Selecionar área** to restrict processing to a useful interior rectangle,
or reject marginal points through the existing review panel. ROI coordinates
remain tied to the original GeoTIFF. Check coverage because an interior rectangle
can omit legitimate nearby soundings. A future automatic proposal would need
to combine frame position, text-line orientation and coordinate-symbol context,
with operator review of the proposed exclusions.

To update cached results, save the current project, leave **Reler possíveis “1”**
enabled, explicitly rerun OCR (stage 2), then regroup (stage 3). Opening a project
preserves cached values instead of silently replacing its review decisions.
