# MCP 規格（v0）— KLayout JSON-RPC 工具端（給 Cline 使用）

> 本文件把目前討論過的「KLayout server + MCP server + 動態 port 註冊 + trace 蒐集」整理成可實作的規格。
>
> 目標：短期用 Cline/Agent 直接操控 KLayout；同時以結構化 trace 蒐集使用者語言與操作模式，作為後續 layout skill / workflow 演進的資料基礎。

---

## 0. 用詞（統一）

- **KLayout Server**：KLayout 內執行的 Python macro server（本 repo：`klayout_gui_tcp_server.py`），提供 **JSON-RPC 2.0 over TCP**。
- **MCP Server**：外部獨立常駐的 Python 服務，對 Cline 暴露 tools；內部呼叫 KLayout Server 的 JSON-RPC。
- **Registry（Port 註冊檔）**：共用路徑下的 JSONL 檔，用於記錄「使用者帳號 ↔ port ↔ KLayout 啟動資料夾（project_dir）」。
- **Trace（互動紀錄）**：工具層（MCP）記錄的結構化 JSONL，保存每次 tool call 的 request/response 與產物路徑。
- **Artifacts（產物）**：screenshot/export 等輸出檔案，統一落盤到專案內 `artifacts/`。

---

## 1. 需求與約束

### 1.1 需求
- Cline 作為 Agent，透過 MCP tools 呼叫 KLayout 能力（對齊 `docs/API.md`）。
- 支援 **KLayout Server 動態 port**：不要求固定 port。
- 以「使用者 copy 整個資料夾回去用」的方式分發專案：
  - **KLayout Server 的 `project_dir` 以 KLayout 啟動時的資料夾（cwd）為準**。
- Trace/Artifacts 先放在此 repo（`klayout-skill-test/`）底下。

### 1.2 不做的事（v0）
- 不做 SSE / WebSocket 即時推播。
- 不做 KLayout 內建聊天面板（短期先用 Cline 介面）。
- 不做複雜 multi-session state / 多 client 併發控制（先 single-user / best-effort）。

---

## 2. Registry（Port 註冊檔）

### 2.1 路徑
- 預設：`~/.klayout/klayout_server_registry.jsonl`
- 可覆寫：`KLAYOUT_SERVER_REGISTRY_PATH`（完整路徑）

### 2.2 格式
- JSONL（每行一筆 JSON 物件，append-only）

### 2.3 欄位（最小集合）
- `ts_utc`：ISO 8601 UTC 字串
- `user`：使用者帳號（`getpass.getuser()`）
- `pid`：KLayout 進程 pid（`os.getpid()`）
- `port`：實際監聽 port
- `project_dir`：KLayout 啟動資料夾（`os.getcwd()`）

> 可選欄位（之後擴充）：`server_version`, `mode(gui/headless)`。

### 2.4 寫入時機（KLayout Server 端）
- KLayout Server 啟動後、確認監聽 port 後立即寫入一筆。
- 寫入失敗不得導致 server crash（best-effort，console 警告即可）。

### 2.5 MCP 端選擇規則（v0）
- 以 `user` 篩選。
- 以 `realpath(project_dir)` 進一步匹配（避免符號連結 mismatch）。
- 由新到舊嘗試：每筆都先做 `ping` health-check；第一個可用者即採用。

### 2.6 Stale / malformed handling（v0 必要）
- 讀 JSONL 時：
  - 忽略 malformed JSON 行、缺欄位行。
  - tolerate partial line（append 競爭導致）。
- staleness（建議）：
  - 若 `pid` 已不存在（POSIX `os.kill(pid, 0)` 失敗），視為 stale，可跳過。
  - 若 `ping` 失敗，嘗試更舊的同 `(user, project_dir_realpath)` 記錄。

---

## 3. MCP Server（Python）

### 3.1 職責
- 對 Cline 暴露結構化 tools（schema + structured result）。
- 解析 registry 找到正確 KLayout endpoint（`127.0.0.1:<port>`）。
- 呼叫 JSON-RPC method（對齊 `docs/API.md`）。
- 統一寫入 trace（JSONL）。
- 管理 artifacts 的預設輸出路徑（若呼叫者未指定）。
- **避免並行 RPC**：KLayout Server 單 client；MCP 端需加 process-level lock。

### 3.2 檔案落點（v0 建議）
- MCP 程式碼（擇一）：`mcp/` 或 `src/klayout_mcp/`
- Trace 落點：`./traces/`
- Artifacts 落點：`./artifacts/`

> `./traces/` 與 `./artifacts/` 是 **repo 內路徑**（便於打包/搬運）。

### 3.3 Endpoint resolution order（v0 必要）
依序嘗試：
1) `KLAYOUT_ENDPOINT=127.0.0.1:PORT`（bypass registry，debug/CI 用）
2) 讀 registry：
   - path：`$KLAYOUT_SERVER_REGISTRY_PATH` 或預設
   - filter：`user == getpass.getuser()`
   - match：`realpath(project_dir)` == MCP 目標專案的 realpath
     - MCP 目標專案路徑來源：
       - `KLAYOUT_PROJECT_DIR`（建議提供；否則用 MCP process cwd）
   - sort：由新到舊（以 `ts_utc` 或檔案順序）
   - 對每筆做 `ping`，第一個成功者採用

---

## 4. Trace（互動紀錄）

### 4.1 目的
- 蒐集「工具層真實執行」的 ground truth：每一次 tool call 實際發出的 JSON-RPC request/response。
- 後續可用於：
  - 萃取可重播 workflow
  - 回歸測試
  - 失敗案例分析（錯誤碼/重試策略）

### 4.2 格式
- JSONL（append-only）

### 4.3 建議欄位（v0 最小 + replay 友善）
每次 tool call 至少包含：
- `ts_utc`
- `run_id`：一次任務/一次 tool call 的識別（v0 可每次 tool call 自產）
- `tool`：MCP tool name
- `endpoint`：`127.0.0.1:<port>`
- `project_dir_realpath`
- `registry_match`：選到的 registry 記錄（至少 `{user,pid,port,project_dir,ts_utc}`）
- `mcp_params`：呼叫 MCP tool 的參數（含 defaults 套用後）
- `rpc_request`：`{id, method, params}`
- `rpc_response`：`{result}` 或 `{error:{code,message,data}}`（完整保留 `error.data.type/details`）
- `duration_ms`
- `artifacts`：`[{kind, path}]`（若有產物；path 建議為相對路徑）

### 4.4 檔名
- `traces/run_<YYYYmmdd_HHMMSS>_<shortid>.jsonl`

---

## 5. Artifacts（產物）

### 5.1 目錄
- 目錄：`./artifacts/`

### 5.2 路徑規則（非常重要）
- 對於會傳給 JSON-RPC 的 `path`（例如 `view.screenshot` / `layout.export` / `layout.render_png`）：
  - MCP **必須傳相對路徑**，且此相對路徑是相對於 KLayout Server 的 `project_dir`。
  - 例如：`artifacts/screenshot_<ts>.png`
- MCP 可以在 tool 層允許 `path=None`，但 **送到 JSON-RPC 時一定要補出實際 path**。

### 5.3 預設檔名（v0）
- 若呼叫者未指定 `path`：
  - `view.screenshot` → `artifacts/screenshot_<ts>.png`
  - `layout.export` → `artifacts/export_<ts>.gds`
  - `layout.render_png` → `artifacts/render_<ts>.png`

---

## 6. MCP tools（v0）清單（對齊 docs/API.md）

> v0 先以「薄包裝」為主：MCP tool 名稱 ↔ 直接對應 JSON-RPC method。

### 6.1 Tool naming
建議 tool names（避免撞名，統一 `klayout_` 前綴）。

### 6.2 Tool response envelope（v0 建議固定格式）
所有 tool 建議回傳一致 envelope：
```json
{
  "ok": true,
  "endpoint": "127.0.0.1:5055",
  "duration_ms": 12,
  "result": {"...": "..."},
  "artifacts": [{"kind":"screenshot","path":"artifacts/screenshot_...png"}]
}
```
若 JSON-RPC error：
```json
{
  "ok": false,
  "endpoint": "127.0.0.1:5055",
  "duration_ms": 12,
  "error": {"code": -32016, "message": "...", "data": {"type": "NoCurrentView", "details": {...}}}
}
```

### 6.3 Tools（v0）
1) `klayout_ping()` → `ping`
2) `klayout_layout_new(dbu, top_cell="TOP", clear_previous=True)` → `layout.new`
3) `klayout_layer_new(layer, datatype=0, name=None, as_current=True)` → `layer.new`
4) `klayout_shape_create(cell, type, coords, units="dbu", layer_index=None, layer=None)` → `shape.create`
5) `klayout_view_ensure(zoom_fit=False)` → `view.ensure`
6) `klayout_view_screenshot(path=None, width=..., height=..., viewport_mode="fit", ...)` → `view.screenshot`
   - 注意：JSON-RPC `view.screenshot` **需要 path**；MCP 需補預設 `artifacts/screenshot_<ts>.png`。
7) `klayout_layout_export(path=None, overwrite=True)` → `layout.export`
8) `klayout_layout_render_png(path=None, width=..., height=..., viewport_mode="fit", ...)` → `layout.render_png`
   - 建議作為 headless fallback：若 `view.screenshot` 回 `MainWindowUnavailable` / `NoCurrentView`，改用 `layout.render_png`。

---

## 7. KLayout Server（macro）需要的改動（v0）

> 本節是 v0 的硬需求：若不做，MCP 的「動態 port discovery」無法工作。

### 7.1 Registry 寫入（硬需求）
- 啟動後寫入 registry（append 一行 JSON）：
  - path：`$KLAYOUT_SERVER_REGISTRY_PATH` 或預設 `~/.klayout/klayout_server_registry.jsonl`
  - `project_dir = os.getcwd()`（本規格已決策）
- 寫入失敗不得導致 server crash（best-effort）。

Example line：
```json
{"ts_utc":"2026-02-15T02:00:00Z","user":"istale","pid":12345,"port":51234,"project_dir":"/home/istale/.openclaw/workspace/klayout_skill_test"}
```

### 7.2 Console 訊息（建議）
- 額外印出：`CWD=<project_dir>`（方便 debug registry mismatch）。

### 7.3（可選）RPC：`server.info`
- 提供 MCP health-check / debug（非 v0 hard requirement）。

---

## 8. 驗收（Definition of Done / v0）

- [ ] KLayout Server 啟動後，registry 檔新增一筆（含 user/pid/port/project_dir）
- [ ] MCP `klayout_ping` 能透過 registry 找到 port 並成功回應 `pong`
- [ ] `layout_new` / `layer_new` / `shape_create` 可連續呼叫成功
- [ ] `view_ensure` + `view_screenshot` 可產生 png 到 `artifacts/` 並回傳路徑
- [ ] `layout_export` 可輸出 gds 到 `artifacts/`（或指定路徑）
- [ ] 每次 MCP tool call 都寫入 JSONL trace，含 request/response、endpoint、duration、artifact paths
- [ ] 異常情境訊息清楚：
  - registry 缺失 → 引導使用者先啟動 KLayout Server
  - registry port 失效/不可連 → 引導重啟 server
  - `NoCurrentView` / `MainWindowUnavailable` → 建議 fallback 到 `layout.render_png`

---

## 9. 後續（v1+）

- 將 `run_id` 與 Cline hook 的「對話回合」做關聯（例如由 Cline 傳入或 MCP 接收 `trace_id`）。
- 更完整的 policy（寫檔/路徑白名單、危險操作提示）。
- 多專案/多 instance registry 選擇 UI（列出候選讓使用者選）。
- MCP 端加入 replay runner（將某次 trace 的 plan 直接重播）。
