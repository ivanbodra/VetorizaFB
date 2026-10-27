# Incremental 5.0 architecture

## Why 4.0.5 fails on this material

The following findings refer to the current GitHub source at `e48583f`, not to
the legacy files attached to the project.

1. **DPI is treated as character scale.** In `core.Config.scale` and
   `segment_details`, strict width/height limits are multiplied by `dpi/600`.
   This TIFF reports 96 dpi, reducing the default upper height from 100 to 16
   pixels and width from 80 to 12.8. Many handwritten main figures are roughly
   25–40 pixels high. Matching these bounds to the observed glyph size is
   necessary, but does not solve the structural problems below.
2. **Preparation has no manuscript model.** `segmentation_mask` offers Gaussian
   blur/fixed inverse threshold/dilation (`legacy`, Realce), or a fixed dark-RGB
   threshold (`black`, Bruto). There is no background normalization, adaptive
   local contrast or distinction between grid/contour and handwriting. At
   96 dpi the default blur and dilation both reduce to one pixel.
3. **Contours are foreground components, not sounding regions.** The current
   `RETR_CCOMP` revision correctly avoids treating holes as additional glyphs;
   it does not reconnect detached pen strokes or split ink joined to a line.
   A disconnected digit becomes several boxes. A touching integer/decimetre
   can become one box. A digit joined to a grid or contour can inherit the
   line's oversized box and be rejected. Enlarging limits admits more lines.
4. **`Digit.text` accepts exactly one digit.** `recognize` sends each component
   crop to the recognizer. A correct multi-character response such as `83` or
   `108` is deliberately unusable as a single stable `Digit`. A missing stroke
   is not recovered by changing a confidence threshold. The narrow-1 retries
   operate after segmentation and cannot restore a candidate discarded earlier.
5. **Grouping is downstream of those losses.** `group` filters unread/low-score
   digits first, greedily joins by centre distances and limits a group to four
   members. Its decimal rule applies only to 2–3 members, requires a lower,
   shorter last glyph and an integer no larger than 31. Missing components,
   variable slant/spacing and touching ink invalidate those assumptions. A
   whole-region recognizer also needs explicit structure: `108` is ambiguous
   between 108 and a 10 with a lowered 8.
6. **The point anchor follows the text box.** The current `Sounding` position is
   the centre of the union of recognized glyph boxes. Losing a main digit or
   attaching a line changes that coordinate. Including a lower-right decimetre
   also moves the centre. Neither this centre nor an alternative has been
   validated against the original sheet's sounding-placement convention.

The existing code is internally consistent with printed-chart glyph extraction.
These observations justify a separate FB path, not changes to its thresholds,
`Digit` contract or grouping semantics.

## Stage 0: this isolated experiment

Keep all executable changes in `experiments/fb_v5`, outside the installed
application package. Preserve 4.0.5 files and version exactly. Annotate regions
before evaluating detectors, evaluate recognition again on fixed reference
crops, and retain all errors/abstentions. A larger model is not a prerequisite.

`prepare()` estimates the paper background by a 51 px grayscale closing,
normalizes by division, applies CLAHE and thresholds the normalized image.
These are declared sample-scale experimental settings, not universal defaults.
Horizontal/vertical openings use 128 px kernels, substantially longer than a
normal handwritten 1. They generate a separate line layer. Only the geometric
proposal mask has those pixels removed. Original/normalized ink is retained.
Curved lines and crossings remain explicit unresolved cases.

The geometric proposal experiment joins nearby foreground strokes with a short
horizontal dilation before producing regions. It still uses components as an
implementation tool; it no longer assumes one component equals one digit. It
is a comparison baseline with known line/annotation false positives, not a
general manuscript detector.

## Stage 1: a separately owned FB processing session

After the reference and approach are reviewed, add a `FieldSheetSession` in a
separate application module. Keep `ChartSession`, existing `Config` values and
old project reconstruction unchanged. The GUI controller will dispatch the
three simple labels **Realce**, **Bruto**, **Folha de bordo** to the appropriate
session; the first two keep their current path. Do not add FB as another
`legacy`/`black` parameter preset.

The FB session owns typed source, preparation, detection, reading, structure and
anchor records. A `SoundingRegion` has a stable ID, native polygon/box, source
window origin, scale transform, provenance, flags and possible parent regions.
A `StructuredReading` holds raw whole/part responses and scores, main integer,
optional decimetre, geometry evidence and an unresolved/recognized state.
No multi-character region is forced into the one-character `Digit` type.

The small detector and geometric proposals remain replaceable adapters. Preserve
unread regions for review. A later classifier can distinguish sounding, contour
label, coordinate annotation and other ink, if a labelled corpus demonstrates
that it reduces false positives without unacceptable sounding loss.

## Stage 2: structure and review

Read whole regions and automatically proposed integer/decimetre parts. Retain
both hypotheses when they disagree. The experimental component rule is useful
but cannot settle joined parts or all slanted writing. A future part detector
or small digit model must show improvement on held-out sheets before becoming
a dependency. In particular, do not treat a valid OCR response `1.1` as 11.1
without additional pixel evidence.

The numeric interpreter validates explicit decimal syntax or part geometry;
there is no automatic depth-range limit or neighbour-driven substitution.
Neighbour consistency can add a review flag with its reason and preserve the
reading. Confidence alone is not calibrated probability of a correct sounding.

Adapt recognized FB records into the existing review operations and shared
geospatial/export validation. Keep the richer FB provenance and project schema
separate; do not pretend its regions are stable chart digits. Include source
hash, method, region/part bounds, raw readings, decisions and anchor state in
saved FB projects. Old chart projects must continue loading without migration.

For later merge/split review actions, create child regions with parent IDs,
retain original proposals and history, invalidate readings/interpretation only
for affected regions, and return affected approvals to pending. Geometry edits
must never silently retain an earlier accepted numeric/coordinate result.

## Stage 3: native coordinates and the sounding anchor

The source declares **EPSG:22524, Córrego Alegre 1970–72 / UTM 24S**, regardless
of the filename. Preserve that CRS and the source affine; do not relabel it as
WGS84. Resizing used by a detector must be inverted before applying ROI origin
and the affine. Follow the current pixel-edge convention, without adding an
extra half-pixel offset. Keep the original vertical reference unchanged.

The PoC assigns **no sounding anchor and exports no XYZ**. For the next
experiment, compare the union-box centre with the main-integer ink-box centre
and any identifiable sounding-position mark, against hydrographer annotations
on the original sheet. An integer-centre anchor is a hypothesis, not an
established cartographic rule. Record the selected rule, bounds and verification
state separately from OCR confidence. Reuse manual positioning after that rule
is settled. The declared 0.566 m pixel spacing is not a claim of survey or
georeferencing accuracy.

## Cache contract

| Layer | Depends on | Must not depend on |
|---|---|---|
| Treated image | source hash/window, preparation settings, algorithm revision | OCR model, confidence, grouping/review |
| Regions | treated-image key, detector/weights/settings and geometry edits | recognizer, numeric interpretation |
| Readings | region pixels/parts, recognizer weights/version, input strategy | depth-neighbour checks, approval |
| Grouping/interpretation | raw readings, geometry evidence, interpreter settings | model execution |

The PoC implements these four caches with atomic files, content keys, array
shape/type validation and JSON payload hashes. Code-file changes conservatively
invalidate preparation and descendants. Stage-specific code revisions can make
that finer later. Benchmark outputs include actual cache hits. Preview calls
preparation/detection only; neither import nor initialization of a recognizer
is allowed in that path.

## Memory and models

The supplied raster is 4.47 MP and the PoC fits it in memory. It does not
establish support for arbitrary full-size survey mosaics. Production FB input
should read native raster windows (initial candidate: 1024 px plus a measured
halo), keep original coordinates, deduplicate overlapping proposals and test
soundings crossing tile boundaries. Cache arrays on disk and release windows.
Use CPU batches of 4–8 initially, bounded thread counts and cancellable stages.

Load at most one detector and one recognizer; measure their combined process
memory on an actual Windows 8 GB machine before integration. A Linux CPU
measurement is only a resource observation, not Windows validation. Keep local
weights usable offline. Downloads remain separate explicit actions supporting
automatic, direct and proxy connections, with no credentials in project files.

## Evidence needed before UI integration

1. User-adjudicated positive, negative, ambiguous and anchor annotations;
   preserve the current provisional set and label versions.
2. Additional sheets/writers/scales, with development and held-out evaluation
   split by source sheet, not by neighbouring crops of the same handwriting.
3. Detection recall/false regions and complete-value/integer/decimetre errors
   reported separately, including failures and unresolved readings. Record
   misses separately from recognition errors on found regions.
4. Runtime/RSS, cache invalidation, source/ROI/scale coordinate tests, seam cases
   and model availability on Windows CPU. No hidden downloads in preview.
5. Existing printed-chart regression tests and historical project loading;
   then a small controller/UI addition, keeping the two stable modes intact.
