# KLayout GUI 物件模型（MainWindow / LayoutView / current_view）

本文件整理我們目前在 `klayout_gui_tcp_server.py` 裡實際使用到的 GUI 物件關係與操作習慣，目標是讓 `view.*` 類 RPC 的**前置條件**、**失敗原因**、與**修復手段（view.ensure）**清楚可查。

> 術語（先用一組固定名詞）
> - **主視窗**：MainWindow（`pya.Application.instance().main_window()`）
> - **版圖視圖**：LayoutView（MainWindow 的其中一個 view；`mw.current_view()`）
> - **目前視圖**：current_view（MainWindow 的 current LayoutView；有時會是 `None`）
> - **版圖**：Layout（`pya.Layout()`）
> - **儲存格視圖**：CellView（LayoutView 內的 cellview；`view.active_cellview()`）

---

## 1. 物件階層（常用取得路徑）

在 GUI 模式下，常見的取得鏈如下：

```python
app = pya.Application.instance()
mw  = app.main_window()          # 主視窗 MainWindow
view = mw.current_view()         # 版圖視圖 LayoutView（目前視圖 current_view）
cv   = view.active_cellview()    # 儲存格視圖 CellView
ly   = cv.layout()               # 版圖 Layout
cell = cv.cell                   # 目前 cell（依版本可能是屬性/方法）
```

我們的 server 端 `view.*` RPC 主要就是在 **LayoutView** 上做事情：
- 改 viewport（`view.zoom_fit()` / 自行計算 DBox）
- 改 hierarchy geometry 顯示深度（`view.max_hier()` / `view.min_hier_levels` / `view.max_hier_levels`）
- 匯出 PNG（`view.save_image_with_options(...)`）

---

## 2. 為什麼 current_view 常常是 None？

在我們常用的啟動方式：

- 測試/伺服器（macro server）最常用：`klayout -e -rm klayout_gui_tcp_server.py`

這種模式下 **不一定會自動開啟/建立 GUI 的目前視圖（current_view）**。
因此，任何依賴 GUI 的 RPC（例如 `view.screenshot` / `view.set_viewport` / `view.set_hier_levels`）都可能失敗。

在 server 中，我們把這類失敗明確化為錯誤：
- `MainWindowUnavailable`（-32013）：連 MainWindow 都拿不到（通常是非 GUI / 沒有 main window 的情境）
- `NoCurrentView`（-32016）：MainWindow 有，但 current_view 取得不到/無法建立

---

## 3. view.ensure：GUI 前置條件的「補齊器」

### 3.1 目的
`view.ensure` 的責任是：
1) 確保 **主視窗** 存在
2) 確保 **目前視圖（current_view）** 存在
3) 把 server 目前的 **active layout** 顯示到該 view（建立 cellview）
4)（可選）做 `zoom_fit`

### 3.2 實作要點（對齊現有程式碼）
在 `klayout_gui_tcp_server.py` 裡：
- `view.ensure` 會呼叫 `_ensure_current_view(_STATE.layout)`
- `_ensure_current_view` 會嘗試：
  - `mw.current_view()` 取得 LayoutView
  - 若沒有，會嘗試切換 `mw.current_view_index` 並用 `mw.view(i)` 拿到 view
  - 拿到 view 後呼叫 `view.show_layout(layout, True)`（或相容版本 `add_cellview=True`）

### 3.3 RPC 行為
- 成功：回傳 `{"ok": true, "views": <views_n>, "current_view_index": <idx>}`
- 失敗：
  - `MainWindowUnavailable` → -32013
  - `NoCurrentView` → -32016
  - `InternalError`（show_layout 失敗）→ -32099

> 操作建議：
> - 客戶端在呼叫任何 `view.*` GUI RPC 前，先呼叫一次 `view.ensure`。

---

## 4. view.screenshot（GUI 匯出 PNG）

### 4.1 前置條件
- 必須有 MainWindow + current_view
- 且 view 上已經有 layout（建議先 `view.ensure`）

### 4.2 參數重點（現有 server）
- `path`：輸出檔案（若缺 `.png` 會自動補）
- `width` / `height`
- viewport：`viewport_mode` + `units` + `box/center/size/steps`
- `save_image_with_options` 的一些輸出參數：`oversampling/resolution/linewidth/monochrome`

### 4.3 典型使用順序
1) `view.ensure`（可選 zoom_fit=true）
2) `view.set_hier_levels`（例如 mode=max）
3) `view.set_viewport`（或在 screenshot 內直接指定 viewport）
4) `view.screenshot`

---

## 5. view.set_viewport（只改視圖，不截圖）

### 5.1 前置條件
- 必須有 MainWindow + current_view（同樣建議先 `view.ensure`）

### 5.2 viewport_mode
- `fit`：zoom_fit
- `box`：指定視窗範圍 `[x1,y1,x2,y2]`
- `center_size`：指定中心與大小
- `relative`：以目前 viewport 做相對移動（steps）

units 支援：`dbu` 或 `um`（server 內部會轉成 `pya.DBox` 的 micron 單位）

---

## 6. view.set_hier_levels（hierarchy geometry 顯示深度）

這個 RPC 控制的是 **版圖視圖裡 hierarchy geometry 的顯示深度**（KLayout 的 `min_hier_levels/max_hier_levels` 與 `max_hier()`），
不是去操作 Hierarchy Browser 的 tree widget 展開節點。

- `mode=max`：呼叫 `view.max_hier()`
- `mode=set`：設定 `view.min_hier_levels` / `view.max_hier_levels`

---

## 7. 已知限制 / 待整理點

- `-e -rm` 模式下 current_view 的建立行為在不同 KLayout 版本/啟動條件可能不一致，`view.ensure` 目前以 best-effort 實作。
- 若後續要做更強的 GUI 控制（例如 hierarchy browser 展開節點），應另開「UI widget 操作」類 RPC，並清楚標註 brittleness。
