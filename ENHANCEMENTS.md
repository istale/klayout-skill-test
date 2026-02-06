# Enhancements / Roadmap Notes

This file tracks **non-required** improvements and future feature ideas.
Keep it lightweight and implementation-oriented.

## Layers APIs

### Current (Req5)
- `layout.get_layers` returns the list of **defined/valid layers** from the active layout.
- Implementation uses `layout.layer_indexes()` + `layout.layer_infos()`.

### Planned enhancement: layers that are actually used by shapes
Problem: A "defined" layer may exist even if no shapes are present on it.
For some workflows we want the list of layers that are **actually used** by shapes.

Proposed approach:
- Reuse the same output schema as `layout.get_layers` (list of objects containing
  `{layer, datatype, name, layer_index}`), but change only the **data source**.
- Add a new RPC method such as:
  - `layout.get_layers_used` (or `layout.get_layers` with a param `{source:"used"}`)

Implementation ideas (data source options):
1) **Fast path** (preferred): Use KLayout APIs that can report used layers directly
   if available (e.g., via iterators over shapes per cell/layer).
2) **Scan path** (fallback): Iterate through cells and detect which `layer_index`
   have non-empty shapes:
   - For each cell: check shapes lists per layer
   - Union `layer_index` values where shape count > 0

Notes:
- Avoid making this the default behavior of `layout.get_layers` to preserve
  deterministic behavior and performance.
- Consider supporting both "defined" and "used" variants via an optional param.

## Programmatic screenshots

### Planned enhancement: headless / no-interaction screenshot export
Current `view.screenshot` uses `MainWindow.current_view()` and fails with
`NoCurrentView` in headless/no-interaction runs.

Goal:
- Support producing PNG output even when no GUI view is currently open.

Implementation ideas:
1) Create a `LayoutView` programmatically and attach/show the active layout
   (`LayoutView.show_layout(...)`), optionally initializing layers.
2) Set viewport to `zoom_fit` (or a target bbox) and export via
   `save_image_with_options`.
3) Consider a separate RPC method (to keep semantics clear):
   - `layout.render_png` or `screenshot.render`

Notes:
- Needs careful handling of technology/layer properties if visual fidelity
  matters.
- In pure batch mode without Qt/GUI, this may still be impossible depending on
  how KLayout was built; if so, document required run mode.
