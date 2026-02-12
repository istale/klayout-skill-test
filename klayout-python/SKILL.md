---
name: klayout-python
description: Control KLayout with Python (pya) and our JSON-RPC/TCP GUI server macro (klayout_gui_tcp_server.py). Use for layout automation, querying hierarchy/shapes, export/open/render/screenshot, and debugging server/client behavior (Qt5; offline docs bundled).
---

# KLayout Python (pya) + GUI TCP Server（離線）

這個 skill 目前的重心是：
- **用 Python（pya）寫 KLayout macro**
- 以及：透過本 repo 的 **JSON-RPC/TCP server**（`klayout_gui_tcp_server.py`）從「客戶端」控制 KLayout（含 GUI 行為）

## 0) 最重要的入口（不要猜）
- Server 程式：`klayout_gui_tcp_server.py`
- API 規格：`docs/API.md`
- 測試入口：`./run_all_tests.sh`

> 任何行為不確定：以 `docs/API.md` + 測試檔 `test_client_jsonrpc_*.py` 為準。

## 1) 啟動 server（推薦指令）

**固定用完整路徑（不要靠 PATH）**：

- Headless（常用、穩定）：
  ```bash
  /home/istale/klayout-build/0.30.5-qt5/klayout -e -rm klayout_gui_tcp_server.py
  ```

- 真的需要 GUI view / screenshot 時：用 GUI 模式起 KLayout（不要 `-e`），例如：
  ```bash
  /home/istale/klayout-build/0.30.5-qt5/klayout -rm klayout_gui_tcp_server.py
  ```

> 注意：`-e -rm` 常常 **不會自動建立 current_view**。所以 GUI 類 API 需要先 `view.ensure`。

## 2) Transport（客戶端如何講話）
- TCP + newline-delimited JSON
- 一行一個 JSON-RPC 2.0 request；server 回一行 response
- **單一 client**（第二個連線會被拒絕）

## 3) 最常用的 RPC 工作流（照做）

### 3.1 Layout 基本流程
1. `layout.new`（建立 in-memory layout + top cell）
2. `layer.new` / `cell.create` / `shape.create` / `instance.create` / `instance_array.create`...
3. `layout.export`（寫出 gds）

### 3.2 Layout 資訊查詢
- `layout.get_topcell` - 取得 top cell 名稱
- `layout.get_layers` - 取得所有 layer 定義
- `layout.get_dbu` - 取得 dbu 值
- `layout.get_cells` - 取得所有 cell 名稱列表
- `layout.get_hierarchy_depth` - 取得 hierarchy 深度

### 3.3 要 screenshot
1. `view.ensure`（確保 GUI view 存在）
2. `view.set_viewport`（可選）
3. `view.screenshot`

### 3.4 控制 view hierarchy 顯示深度
- `view.set_hier_levels`（mode: "max" | "set"）

### 3.5 要 headless render PNG
- 用 `layout.render_png`

### 3.6 Hierarchy 查詢（需求6+）
- `hier.query_down` - 向下列舉 instances（mode: "structural" | "expanded"）
- `hier.query_down_stats` - 統計 instance 數量（依 child_cell 分組）
- `hier.query_up_paths` - 查詢指定 cell 的所有 upward 路徑
- `hier.shapes_rec` - 遞迴列出 shapes + hierarchy_path
- `hier.shapes_rec_boxes` - 將 shapes 轉為 box set（DBU，支援 polygon 分解）

## 4) 路徑限制（安全規則）
涉及檔案路徑的 RPC（例如 `layout.open` / `layout.export` / `view.screenshot` / `layout.render_png`）：
- 只允許 server 啟動 cwd 底下的相對路徑
- 不能用 `..` 跳脫

（實際錯誤型別看 `docs/API.md` 的 errors 與測試。）

## 5) 錯誤格式（client 解析要點）
- 走 JSON-RPC 2.0 `error`
- **機器可讀分類**在：`error.data.type`
- 額外資訊在：`error.data.details`

## 6) 離線文件（pya / KLayout API 查詢）
這份 skill 仍保留離線文件鏡像：
- `references/docs_md/`（優先，用 markdown 可 grep）
- `references/docs_html/`（原始鏡像）

起點：`references/docs_md/INDEX.md`

查 API 的做法：
```bash
# from repo root
rg -n "class_LayoutView" klayout-python/references/docs_md | head
rg -n "begin_shapes_rec" klayout-python/references/docs_md | head
```

## 7) 只靠本 skill 的最小驗收（不使用 repo 測試程式）

> 目的：讓任何人/代理只看本 SKILL.md，就能做 end-to-end smoke test。

### 7.1 啟動 server
在 repo root 執行（擇一）：

- Headless：
  ```bash
  /home/istale/klayout-build/0.30.5-qt5/klayout -e -rm klayout_gui_tcp_server.py
  ```

- GUI（需要 screenshot 時）：
  ```bash
  /home/istale/klayout-build/0.30.5-qt5/klayout -rm klayout_gui_tcp_server.py
  ```

### 7.2 用最小 client 送 RPC（newline-delimited JSON-RPC）
本 repo 提供最小 client：
- `klayout-python/scripts/jsonrpc_client.py`

範例（假設 server 監聽在 port 5055；實際 port 由啟動方式/環境決定）：

1) ping
```bash
python3 klayout-python/scripts/jsonrpc_client.py ping --port 5055
```
預期：response 內 `result.pong=true`

2) 建立 layout
```bash
python3 klayout-python/scripts/jsonrpc_client.py layout.new \
  --port 5055 \
  --params '{"dbu":0.001,"top_cell":"TOP","clear_previous":true}'
```
預期：`result.layout_id` 存在，`result.top_cell=="TOP"`

3) 匯出 GDS
```bash
python3 klayout-python/scripts/jsonrpc_client.py layout.export \
  --port 5055 \
  --params '{"path":"out.gds","overwrite":true}'
```
預期：`result.written=true` 且 repo root 下生成 `out.gds`

4)（可選，GUI）確保 view + screenshot
```bash
python3 klayout-python/scripts/jsonrpc_client.py view.ensure --port 5055
python3 klayout-python/scripts/jsonrpc_client.py view.screenshot \
  --port 5055 \
  --params '{"path":"out.png","overwrite":true}'
```
預期：生成 `out.png`

## 8) 驗收 / 回歸（開發用）
- 改 server 行為或 client 假設時：仍建議跑完整回歸
  ```bash
  ./run_all_tests.sh
  ```
