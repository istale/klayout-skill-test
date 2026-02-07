# 術語表（Glossary）

本文件用來落實「術語 hygiene」：同一概念只用一個中文名稱（必要時括號標示程式/API 名稱）。

---

## GUI
- **主視窗**（MainWindow）：`pya.Application.instance().main_window()`
- **版圖視圖**（LayoutView）：KLayout GUI 的 view；`mw.current_view()` 回傳
- **目前視圖**（current_view）：主視窗目前選中的 LayoutView
- **儲存格視圖**（CellView）：`view.active_cellview()`

---

## 單位與座標
- **DBU**：database unit（整數座標）
- **um**：micrometer（浮點座標）
- **邊界框**：bbox
  - `bbox`：通常表示 DBU 的 bbox（整數）
  - `bbox_um`：以 um 回傳的 bbox（浮點）
- **點列表**：points
  - `points_um`：以 um 回傳的點

---

## 階層（Hierarchy）
- **層級**：hierarchy
- **層級深度**：hierarchy depth（instance edges 數）
- **層級路徑**（hierarchy_path）：從起始 cell 到目標 shape/cell 的 cell name list（例如 `hier.shapes_rec` 回傳）
- **路徑段落**（path segments）：`hier.query_down.instances[].path`，從 query root 到「parent cell」的 cell name list

---

## Instance / Array
- **實例**（instance）：cell instantiation
- **陣列實例**（array instance）：regular array（nx*ny）
- **展開**（expanded）：把陣列實例展成每個實體 element
- **展開索引**（expanded_index）：`{ix,iy}`，表示 array element 在 a/b 軸的索引

---

## Guardrail
- **結果上限**（max_results / limit / max_paths）：避免輸出爆量
- **過多結果**（TooManyResults）：超過 guardrail 時回的錯誤 type
