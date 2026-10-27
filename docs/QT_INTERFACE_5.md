# VetorizaFB 5.0 — PySide6 interface preview

A new, standalone Qt interface prototype lives at `src/vetorizafb/qt_preview.py`.

## Run

```powershell
git switch v5.0-folhas-de-bordo
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install PySide6
.\.venv\Scripts\python.exe -m vetorizafb.qt_preview
```

This launches the preview separately from the maintained Tk interface.

## Design language

- Navy `#102D46` and ink `#153B50`; warm gold `#E7BA4B` for selection.
- Light surfaces, thin separators, Segoe UI typography.
- Persistent chart workspace, adjustable split panels, compact toolbar.
- Stage navigation: Prepare, Recognize, Group, Review, Export.
- Processing mode chooser: Enhanced, Raw, Field Sheet (shown in Portuguese).
- Image-space ROI tools: rectangle, polygon, freehand lasso.
- Zoom with mouse wheel; drag-to-pan; fit image.

## Scope and limitations

This is a design and interaction prototype, **not** the complete application.
The OCR, grouping, review persistence and export buttons are intentionally disabled.
The preparation controls are visual placeholders and do not yet update the core configuration.
The viewer uses Qt's QPixmap decoder; support for large GeoTIFF rasters and geospatial metadata needs a rasterio-backed adapter.
The Qt ROI geometry is not yet wired to ChartSession and does not filter OCR results.
No visual or automated tests have been run against a Windows Qt installation yet.

## Integration plan

1. Connect chart loading through ChartSession and rasterio-backed rendering.
2. Bind the preparation widgets to Config and staged processing.
3. Move review table, point editing and export actions to Qt.
4. Load SVG icons from `assets/icons` and provide accessible labels/tooltips.
5. Add headless Qt widget tests and Windows smoke tests before changing the default launcher.
