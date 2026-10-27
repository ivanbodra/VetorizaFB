# VetorizaFB 5.0 — modern PySide6 interface

The default desktop entry point on branch `v5.0-folhas-de-bordo` is now
`vetorizafb.qt_modern:main`.

## Install and run (Windows)

```powershell
git switch v5.0-folhas-de-bordo
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -e ".[qt,ocr,test]"
.\.venv\Scripts\vetorizafb-gui.exe
```

To launch without reinstalling scripts, use
`.\.venv\Scripts\python.exe -m vetorizafb.qt_modern`.

The prior fully functional Qt window remains available through
`vetorizafb-qt-legacy`; the Tk implementation remains available through
`vetorizafb-classic`.

## Design

- Identity: nautical navy `#102D46`, cool paper `#F4F7FA`, golden focus `#E7BA4B`.
- SVG iconography stored under `assets/icons/`.
- Compact product header, single main toolbar, vertical process navigation.
- Contextual parameters beside the chart, separated from chart navigation.
- Large chart canvas with hidden scrollbars and native wheel zoom/drag pan.
- Collapsible review table with the original review actions.
- Scalable splitters for workspace allocation.

## Preserved operation

The modern shell inherits from the existing functional
`vetorizafb.qt_gui.Window`. Existing buttons, input widgets and their
connections are **moved**, not replaced. Consequently, it retains the
working ChartSession operations: chart/project loading, segmentation, OCR,
grouping, FB box corrections, model download, area selection, point review,
project saving and georeferenced export.

`qt_workspace.py` is an independent experimental shell; it is **not**
the default executable.

## Testing

`tests/test_qt_modern.py` contains offscreen Qt smoke tests for navigation,
preserved controls and collapsible review. Tests are optional (skipped if
PySide6 is not installed). These tests and real chart processing still need
execution and validation on the intended Windows environment. No claim of
complete end-to-end verification is made here.
