# Historical field sheets: isolated 5.0 proof of concept

This experiment starts from `main` commit
`e48583f720619f5c73a5a74445d0362e4012aceb` (4.0.5), on branch
`v5.0-folhas-de-bordo`. No application file, dependency declaration, version,
GUI mode, model registry or printed-chart processing path is changed.

Read [the architecture](ARCHITECTURE.md) and [measured results](RESULTS.md).

The six source-image windows and generated evidence are provided separately in
`VetorizaFB_5_0_Evidencias.zip`, following the repository policy of keeping input
imagery and generated outputs outside Git. Extract that archive **at the
repository root** before running the sample benchmark. It restores the
`experiments/fb_v5/sample/` (pixels and annotations) and
`experiments/fb_v5/evidence/` paths. All executable experiment code is committed
here; the labelled source sample stays with the separately supplied evidence.

## What is implemented

- Native-resolution background flattening, local contrast, separate original,
  normalized, foreground and long-straight-line masks.
- Complete-region proposals from geometric ink grouping, with/without straight
  line masking; raw and normalized Paddle detector inputs at native/2x scale.
- Recognition of whole regions versus automatic main-integer/decimetre crops.
  A component rule proposes a smaller, lower rightmost part. Joined parts can
  remain unresolved. Raw text and actual model scores are retained.
- Four atomic, content-addressed caches: preparation, regions, readings and
  interpretation/grouping. Source/ROI, parameters, code revision, library
  versions, weights and recognition strategy enter their dependencies.
- A detection-only GeoTIFF preview; a six-tile reference; per-method processes
  measuring wall time and whole-process RSS; raw JSON outputs and visual audits.

No handwriting-specific model is selected. The recognizer is the small model
already used by the stable application. `PP-OCRv5_mobile_det` is an experimental
detector comparator. This is neither a sounding classifier nor an operational
extractor. No points are approved and no XYZ is produced by this experiment.

## Reproduce on Windows / CPU

From the project root, preserving any local work:

```powershell
cd D:\Bathy\Estudos\Programas\VetorizaFB
git fetch origin
git switch v5.0-folhas-de-bordo
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -e ".[ocr,test]" psutil
.\.venv\Scripts\python.exe -m pytest -q experiments/fb_v5/tests
```

If no environment exists, create it first with `py -3.12 -m venv .venv`.
The normal application still reports **4.0.5**. Start it normally to work with
printed charts; the proof of concept runs only with the commands below.

Download experiment weights explicitly into a separate folder:

```powershell
.\.venv\Scripts\python.exe -m experiments.fb_v5.download_models `
  --root models\fb-v5 --connection direct
```

`--connection system` uses the automatic environment/system connection.
`--connection proxy --proxy-server host:port --proxy-user user` prompts for a
password without putting it on the command line. `--ca-file path` accepts an
organization CA. Credentials are not written to results. The download uses the
stable connection-settings/archive-extraction helpers and the official Paddle
BOS source; it does not change the stable model registry.

Evaluate the committed small sample (the original TIFF is not needed):

```powershell
.\.venv\Scripts\python.exe -m experiments.fb_v5.benchmark `
  --model-root models\fb-v5 --output results\fb-v5 `
  --cache results\fb-v5-cache
```

The runner processes methods sequentially in fresh CPU processes, then evaluates
recognition on the same manually boxed crops. Missing local weights cause an
error; the benchmark never initiates a model download. Each actual reading is
preserved, including rejected/non-numeric text. Warm cache reruns are explicitly
marked in the per-tile `cache_hits` fields.

Generate an overlay on the supplied TIFF **without recognition or model loading**:

```powershell
.\.venv\Scripts\python.exe -m experiments.fb_v5.preview `
  "C:\FB\ortomosaico_geo_ct_edico_wgs2sw_bw.tif" `
  --output results\fb-v5-preview
```

Use `--roi X Y W H` for a native-pixel window. This prototype accepts the supplied
RGB uint8 type and limits the selected window to 16 MP. It is not yet a complete
tiled, arbitrary-raster loader. Overlay coordinates are native/global pixels;
the source CRS/affine and ROI are recorded, without assigning cartographic anchors.

Linux uses `python` or `.venv/bin/python` for the same module commands. Optional
`psutil` is needed only by the benchmark. There is no new application dependency.

## Evidence and reference

- Reference regions and provisional visual readings: `sample/reference.json`
  in the supplied archive.
- Machine-readable summary: `evidence/summary.json` in the supplied archive.
- Source metadata: `evidence/input_metadata.json`.
- C/D region comparison: `evidence/images/comparison_focus.png`.
- Whole/part recognition audit: `evidence/images/recognition_comparison.png`.

To regenerate the compact comparison from saved benchmark results:

```powershell
.\.venv\Scripts\python.exe -m experiments.fb_v5.render_evidence --evidence results\fb-v5
```

The six sample PNGs are exact native-resolution windows of the supplied raster.
Their source hash and global ROI origins are in the reference. There are 59 distinct
sounding regions and 58 provisionally readable values. E04's decimetre is
visually ambiguous and is detection-only. The assistant's labels require user
adjudication; they are not a hydrographer-certified or independent test corpus.

The benchmark uses only geometry, pixels and raw model outputs. Neighbouring
depth values never correct a reading. No trained-model accuracy claim follows
from this small single-sheet diagnostic.
