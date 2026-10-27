# VetorizaFB — icon design study

Minimalist outline icon family for the future desktop interface.

- Canvas: 24 × 24 viewBox; SVG vector assets.
- Stroke: 1.7, rounded caps and joins.
- Primary ink: #153B50 (nautical navy).
- Neutral, flat silhouettes; no gradients or shadows.
- Intended display: 20–24 px, with active/disabled states applied by the UI.

## Navigation tabs

- `tab-prepare`: sliders / calibration.
- `tab-recognize`: OCR frame and characters.
- `tab-group`: connected boxes.
- `tab-export`: outgoing data arrow.

## Chart selection and inspection

- `open-chart`, `whole-chart`, `select-rectangle`, `select-polygon`, `select-lasso`, `measure`, `preview`, `zoom-in`, `zoom-out`, `pan`, `layers`.

## Workflow and review

- `process`, `save-project`, `open-project`, `review`.

The icons are assets only; wiring to Qt widgets and application commands is a separate UI implementation step. Keep the source SVGs as the canonical editable masters. Colors may be overridden by SVG rendering in the Qt interface.
