---
name: klayout-python
description: Write KLayout (pya) Python macros, scripts, and layout automation (DB/geometry/app APIs).
---

# KLayout Python (pya)

Use this skill when you need to **script KLayout** with Python:
- write **macros** (GUI or batch)
- generate or edit layouts (GDS/OAS)
- run geometry/region operations
- interact with the KLayout application UI APIs

Official docs (Qt5): https://www.klayout.de/doc-qt5/programming/index.html

## Key facts (from docs)
- Python binding module is **`pya`** (Ruby uses `RBA`) and class/method names are mostly the same.
- Python macros are loaded from **`.py`** files or **`.lym`** files with interpreter set to Python.
- KLayout uses `KLAYOUT_PYTHONPATH` (Python >=3) to extend Python search paths.

See `references/overview.md` for a compact cheat sheet.

## Working modes
### 1) Standalone / batch script
Use when you just need DB/geometry work and file I/O.

Typical flow:
1. `import pya`
2. `layout = pya.Layout()`
3. read or build hierarchy + shapes
4. `layout.write("out.gds")`

### 2) In-app macro (GUI)
Use when you need views, layer lists, selections, markers, menus, etc.

Typical flow:
1. `app = pya.Application.instance()`
2. `mw = app.main_window()`
3. get/create view/layout, then operate on `LayoutView`/`CellView`.

## Coordinate conventions
- The DB stores **integer coordinates in database units** (`layout.dbu` is microns per DB unit).
- Many classes have **D*** floating-point twins (e.g. `DBox`) in **microns**.

## Templates
Use the example scripts in `scripts/` as starting points:
- `basic_template.py` — create a layout/cell/layer and insert shapes
- `file_io_template.py` — read/merge/write with options
- `hierarchical_layout.py` — cell instances / arrays
- `region_operations.py` — Regions + boolean/sizing
- `drc_template.py` — placeholder patterns for rule checks (adjust to your DRC flow)

## When you need more detail
Read:
- `references/overview.md`

Then consult the class reference pages linked from the programming docs index.
