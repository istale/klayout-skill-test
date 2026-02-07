# 相容性與實作備註（COMPAT）

本文件記錄一些「規格外但會影響行為」的實作細節，目標是避免未來改動造成無意的行為漂移。

---

## 1) `hier.query_down.engine`（iterator vs dfs）

### 背景
KLayout 的 `RecursiveInstanceIterator`（`Cell.begin_instances_rec`）在有 regular array instance 時，**會逐 array element 迭代**。

這對 `mode=expanded` 很有用（可以自然拿到 `InstElement.ia/ib` 與 per-element transform），
但對 `mode=structural` 會造成輸出爆量與效能問題（原本 structural 是「陣列算 1 筆」）。

### 現況（server 實作策略）
- `mode=expanded`：
  - `engine=iterator`：使用 `RecursiveInstanceIterator` 迭代 instance elements。
  - 回傳 record 一律 `kind="single"`（代表實體 element），並附 `expanded_index={ix,iy}`（best-effort）。
- `mode=structural`：
  - 即使指定 `engine=iterator`，目前仍會採用 DFS（避免 iterator 的 per-element 爆量行為）。

> 這是一個「策略性選擇」，不是 KLayout API 的限制。

### 建議
若未來確定要支援 structural 也走 iterator，需額外做：
- array element 去重（以 Instance identity + parent cell 做 key）
- 或改用 iterator 的 selection/targets 能力縮小輸出

---

## 2) `hier.query_down_stats`（統計口徑）
- 只做 `child_cell` 分組
- **固定採用展開口徑**：regular array instance 算 nx*ny
- 只回傳統計，不回 instances

---

## 3) `hier.shapes_rec`（begin_shapes_rec / it.path）
不同 KLayout build 的 Python binding 對 `begin_shapes_rec()` 簽名可能不同：
- 某些版本要求 `begin_shapes_rec(layer)`

因此 server 採用「逐 layer 走 iterator」策略：
- 對每個 layer index 建立 `RecursiveShapeIterator(layout, cell, layer)`
- hierarchy_path 優先用 `it.inst_path()`，若拿不到則 fallback 用 `it.path`（官方文件）

---

## 4) GUI current_view
在 `klayout -e -rm` 啟動模式下，`MainWindow.current_view()` 不保證存在。
- `view.ensure` 以 best-effort 嘗試取得/切換 view 並 show layout。
- 依賴 GUI 的 RPC 若無 current_view，會回 `NoCurrentView`。

詳情見：`docs/GUI_MODEL.md`
