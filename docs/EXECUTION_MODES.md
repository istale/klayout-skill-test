# 執行模式與前置條件（KLayout 啟動方式 / GUI 可用性）

本文件整理本專案（`klayout_skill_test`）在不同 KLayout 啟動方式下：
- 哪些 RPC 會可用 / 不可用
- 常見錯誤（`MainWindowUnavailable` / `NoCurrentView`）的原因
- 推薦的啟動命令與測試方式

---

## 1) 固定版本與執行檔路徑
本專案目前固定使用：
- KLayout executable：`/home/istale/klayout-build/0.30.5-qt5/klayout`
- KLayout home：`/home/istale/klayout-build/0.30.5-qt5`

（偏好：文件必須包含完整路徑，不依賴 PATH）

---

## 2) 常用啟動方式

### A. Macro server（最常用）
```bash
KLAYOUT_SERVER_PORT=5055 /home/istale/klayout-build/0.30.5-qt5/klayout -e -rm klayout_gui_tcp_server.py
```

特性：
- 可操作 Layout database（cells/layers/shapes/instances）
- **不保證有 GUI 的 current_view**
- 因此 `view.*` 類 GUI RPC 可能回 `NoCurrentView`

### B. GUI 模式（需要 screenshot/GUI 操作時）
```bash
/home/istale/klayout-build/0.30.5-qt5/klayout -rm klayout_gui_tcp_server.py
```

特性：
- 有 MainWindow 與 LayoutView 的機率高
- `view.ensure` 更容易成功

---

## 3) GUI 相關 RPC 的前置條件

### 需要 GUI（MainWindow + current_view）
- `view.ensure`
- `view.screenshot`
- `view.set_viewport`
- `view.set_hier_levels`

常見錯誤：
- `MainWindowUnavailable`（-32013）：拿不到 main window（通常不是 GUI 環境）
- `NoCurrentView`（-32016）：MainWindow 存在，但 current_view 取得不到/無法建立

修復建議：
1) 優先呼叫 `view.ensure`
2) 若仍失敗，改用「GUI 模式」啟動（上節 B）

詳細 GUI 物件模型見：`docs/GUI_MODEL.md`

---

## 4) Headless / Database-only 可用的 RPC
通常不依賴 GUI（只要 layout 存在）：
- `layout.new`, `layout.open`, `layout.export`
- `layer.new`, `cell.create`, `shape.create`
- `instance.create`, `instance_array.create`
- `layout.get_*`
- `hier.query_*`（down/up/stats）
- `hier.shapes_rec`（是 DB iterator，不需要 GUI）

---

## 5) 測試建議

### 跑整套 integration tests
```bash
cd /home/istale/.openclaw/workspace/klayout_skill_test
./run_all_tests.sh
```

備註：
- `test_client_jsonrpc_req7_view_set_viewport.py` 在沒有 current_view 時會 SKIP（屬預期行為）。
