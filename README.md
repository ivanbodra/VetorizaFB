# VetorizaFB

Extract georeferenced sounding points and depth values from nautical chart rasters.

The initial scope is published raster nautical charts (GeoTIFF). Historical photographed and orthorectified hydrographic field sheets are a separate future module.

## Baseline

The uploaded v3.1 implementation and v4 interface prototype are preserved under `legacy/`, without modifications. The v4 prototype does not yet integrate OCR and export. The author reports 100% accuracy on `21300plano.tif`; this result has not been independently reproduced and does not establish performance on other charts.

See [baseline and scope](docs/BASELINE.md) and [source checksums](docs/source_manifest.json).

Input rasters and downloaded model weights remain external to Git.
