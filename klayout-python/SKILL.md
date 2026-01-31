---
name: klayout-python
description: Write KLayout (pya) Python macros, scripts, and layout automation (Qt5; offline docs bundled).
---

# KLayout Python (pya) — Qt5 (Offline)

Use this skill when you need to **script KLayout** with Python:
- write **macros** (GUI or batch)
- generate/edit layouts (GDS/OAS)
- run geometry/region operations
- interact with KLayout application APIs

This skill is designed for **offline machines**. The full Qt5 programming + class reference is bundled under:
- `references/docs_md/` (preferred; searchable markdown)
- `references/docs_html/` (raw mirror)

Start here:
- `references/docs_md/INDEX.md`

## Key facts (from docs)
- Python binding module is **`pya`** (Ruby uses `RBA`)
- Python macros can be `.py` or `.lym` with interpreter set to Python
- KLayout extends Python search via `KLAYOUT_PYTHONPATH` (Python >= 3)

Source pages (online originals):
- https://www.klayout.de/doc-qt5/programming/index.html
- https://www.klayout.de/doc-qt5/programming/python.html

## Working modes
### 1) Standalone / batch script
Typical flow:
1. `import pya`
2. `layout = pya.Layout()`
3. read or build hierarchy + shapes
4. `layout.write("out.gds")`

### 2) In-app macro (GUI)
Typical flow:
1. `app = pya.Application.instance()`
2. `mw = app.main_window()`
3. use `LayoutView` / `CellView` / menus / markers.

## How to search the offline docs
When you need an API detail, search locally:

```bash
# from repo root
grep -RIn "LayoutView" klayout-python/references/docs_md | head

# if ripgrep is available
rg -n "class_Layout" klayout-python/references/docs_md/code | head
```

Prefer the programming pages first:
- `references/docs_md/programming/*.md`

Then jump into the class reference:
- `references/docs_md/code/index.md`

## Templates
Use the example scripts in `scripts/` as starting points:
- `basic_template.py` — create a layout/cell/layer and insert shapes
- `file_io_template.py` — read/merge/write
- `hierarchical_layout.py` — cell instances / arrays
- `region_operations.py` — Regions + boolean/sizing
- `drc_template.py` — DRC patterns (adjust to your flow)

## Quick cheat sheet
See `references/overview.md` (small, curated). For canonical behavior, consult `references/docs_md/*`.
