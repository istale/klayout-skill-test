# KLayout Python (pya) — Practical Cheat Sheet

Primary reference index:
- https://www.klayout.de/doc-qt5/programming/index.html

## Where code lives (macros)
From the docs:
- Python macros can be `.py` or `.lym` (with interpreter set to Python).
- “Ruby’s `RBA` namespace is `pya` for Python”.
- Python search path can be extended via `KLAYOUT_PYTHONPATH`.

See: https://www.klayout.de/doc-qt5/programming/python.html

---

## 1) Minimal file I/O (batch)
```python
import pya

ly = pya.Layout()
ly.read("in.gds")      # merges into existing layout
ly.write("out.gds")
ly.write("out.oas")
```

The database unit is `ly.dbu` (microns per DB unit). DB geometry uses integer coordinates; D* classes are micron floats.

See: https://www.klayout.de/doc-qt5/programming/database_api.html

---

## 2) Create a new layout + a rectangle
(Directly adapted from the docs’ Python example)
```python
import pya

layout = pya.Layout()
top = layout.create_cell("TOP")
l1 = layout.layer(1, 0)

# integer DBU box: (0,0)-(1000,2000) in database units
top.shapes(l1).insert(pya.Box(0, 0, 1000, 2000))

layout.write("t.gds")
```

See: https://www.klayout.de/doc-qt5/programming/python.html

---

## 3) Cells, hierarchy, and instances
Common patterns:
```python
import pya

ly = pya.Layout()
ly.dbu = 0.001

TOP = ly.create_cell("TOP")
CHILD = ly.create_cell("CHILD")

# Create an instance of CHILD inside TOP
trans = pya.Trans(pya.Point(0, 0))
inst_arr = pya.CellInstArray(CHILD.cell_index(), trans)
TOP.insert(inst_arr)
```

Notes:
- `CellInstArray` represents one instance or an array of instances.
- Use class docs for full constructor options.

See: https://www.klayout.de/doc-qt5/programming/database_api.html

---

## 4) Layers and shapes

### Layer indices
Layers are represented by **layer indices** inside a `Layout`. You obtain/create them via `layout.layer(...)` or `layout.insert_layer(LayerInfo(...))`.

### Iterate shapes in a cell on a layer
```python
shapes = TOP.shapes(l1)
for s in shapes.each():
    if s.is_box():
        b = s.box
    elif s.is_polygon():
        p = s.polygon
    elif s.is_path():
        path = s.path
    elif s.is_text():
        t = s.text
```

See: https://www.klayout.de/doc-qt5/programming/database_api.html

---

## 5) Geometry primitives and transforms
Core integer-coordinate primitives include `Point`, `Box`, `Polygon`, `Path`, `Text`, plus transforms (`Trans`, `CplxTrans`, etc).

Key rule from the docs: some transforms (e.g. non-90° rotations) require converting boxes to polygons for correct results.

See: https://www.klayout.de/doc-qt5/programming/geometry_api.html

---

## 6) Regions (boolean geometry)
`Region` is the workhorse for boolean ops, sizing, etc.

```python
import pya

r1 = pya.Region()
r2 = pya.Region()

u = r1 + r2        # union
i = r1 & r2        # intersection
s = r1 - r2        # subtraction
x = r1 ^ r2        # xor

expanded = u.sized(100)   # size in DB units (integer geometry)
```

Important:
- Region operations are primarily for **integer DBU geometry**. If you start from micron floats (D*), convert appropriately.

See: https://www.klayout.de/doc-qt5/programming/geometry_api.html

---

## 7) Application/UI entry points (when running inside KLayout)
If you’re writing a macro that touches the UI:
```python
import pya

app = pya.Application.instance()
mw = app.main_window()
view = mw.current_view()
```

The application API covers `Application`, `MainWindow`, `LayoutView`, etc.

See: https://www.klayout.de/doc-qt5/programming/application_api.html
