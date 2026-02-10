# 改動計劃（Change Plan）— klayout_skill_test

> 目標：把鋼鐵人（opencode）提出的優化建議落地成「可執行的改動清單」，每一項都包含：
> - 現行行為（As-Is）
> - 問題/風險
> - 預期目標（To-Be）
> - 實作步驟（What to change）
> - 測試驗證（How to verify）
> - 影響範圍/相容性（Compatibility）

本文優先覆蓋 **High priority**；Medium/Low 放在後段當 backlog。

---

## 0. 基準資訊

- Repo：`/home/istale/.openclaw/workspace/klayout_skill_test`
- Server：`klayout_gui_tcp_server.py`（JSON-RPC/TCP）
- 測試入口：`./run_all_tests.sh`
- API 文件：`docs/API.md`

### 名詞（避免漂移）
- 「單位」：`unit`（方法參數，用於回傳座標單位，例如 `um` 或 `dbu`）
- 「圖層索引」：`layer_index`（layout layer index，不是 layer/datatype pair）
- 「錨點」：此 repo 暫不使用（避免與自動點擊系統混用）

---

## 1. 統一 JSON-RPC error.data schema（文件 ↔ 實作一致）

### As-Is（現行行為）
- `docs/API.md`（errors 範例）描述 error.data 形式偏向：
  - `data: { type: <string>, details: <object> }`
- 但 server 實作 `_err()`/`_err_std()` 可能會把欄位「直接平鋪」在 `data` 內，而不是包在 `details`。

### 問題/風險
- Client 依文件實作時會固定讀 `data.details`，結果拿不到資訊。
- 無法建立穩定的錯誤處理與上層 retry/分流策略。

### To-Be（預期目標）
- 統一為下列 schema（建議）：
  - `error.data = { "type": <string>, "details": <object|null> }`
- 所有 `_err*` helper 都保證：
  - `type` 一定存在
  - 額外資訊一律放 `details`

### 實作步驟
1. 盤點 `_err()`/`_err_std()` 以及所有 call site 目前塞到 `data` 的欄位。
2. 修改 helper：
   - 若 caller 傳的是 dict，就包進 `details`。
   - 既有平鋪欄位改移到 `details`。
3. 更新 `docs/API.md`：
   - 統一範例
   - 列出「error.data.type / error.data.details」為正式 API。

### 測試驗證
- 新增測試：任意觸發 `CellNotFound` / `InvalidParams` / `InvalidPath`
  - assert `error.data.type` 存在
  - assert `error.data.details` 為 object（或 null）
  - 不再接受平鋪欄位

### Compatibility
- **breaking change**（對依賴平鋪欄位的 client）。
- 建議先提供一個短期相容期：
  - `details` 內含原先欄位，並保留平鋪欄位 1-2 版（或反過來），最後再移除。

---

## 2. 統一錯誤 type ↔ code 對應（CellNotFound 等）

### As-Is
- 同一 error type 在不同方法可能對應不同 code。

### 問題/風險
- client 不能用 code 做穩定分類。

### To-Be
- 建立「錯誤對照表」：每個 `type` 對應固定 `code`。

### 實作步驟
1. 在 server 集中定義 mapping（例如常數 dict）。
2. 全面替換 call site，或讓 `_err_std(type=...)` 自動套用 code。
3. 更新 `docs/API.md` errors section。

### 測試驗證
- 測試觸發 `CellNotFound` 於多個 method，assert code 一致。

### Compatibility
- 可能是 breaking（若 client 依賴舊 code）。

---

## 3. 統一路徑 resolver + 錯誤 type/code（export/open vs screenshot/render）

### As-Is
- export/open 與 screenshot/render 使用不同 resolver：
  - export/open：固定 `_SERVER_CWD_REAL`
  - screenshot/render：使用 `os.getcwd()`
- 錯誤 type/code 也不同（`PathNotAllowed -32010` vs `InvalidPath -32015`）

### 問題/風險
- 安全策略不一致；不同方法行為不易預期。

### To-Be
- 所有寫檔/輸出路徑都走同一個 resolver（同一個「允許範圍」概念）。
- 錯誤型別一致。

### 實作步驟
1. 抽象成單一 `_resolve_output_path(kind, path, default_ext)`。
2. export/open/screenshot/render 改用同一 resolver。
3. `docs/API.md` 補上 `InvalidPath`（若保留）。

### 測試驗證
- 建立測試：
  - relative path OK
  - `..` path 被拒
  - 錯誤 type/code 一致

---

## 4. `hier.shapes_rec_boxes` 讓 `merge_boxes` 對 polygon/path 一致

### As-Is
- handler 的 `merge_boxes=false` 只對 polygon 生效；path 不支援。

### 問題/風險
- API 參數語意不可靠。

### To-Be
- `merge_boxes` 對 `polygon` 與 `path` 同等生效。

### 實作步驟
- 調整 `_shape_to_boxes_dbu`：
  - 讓它可回傳「raw boxes」與「merged boxes」，由 handler 決定。
  - 或在 handler 若 `kind in {polygon,path}` 且 `merge_boxes=false` 時重建 unmerged。

### 測試驗證
- 新增 path case：
  - `merge_boxes=true/false` 的 boxes 數量/形狀應符合預期（至少確定不被垂直 merge）。

---

## 5. polygon→boxes scanline 一致性檢查（避免 silent wrong result）

### As-Is
- scanline pairing 沒檢查交點數是否偶數。

### 問題/風險
- 自交/退化 polygon 可能回出錯誤 boxes，且不報錯。

### To-Be
- 遇到不一致就回 `InvalidParams`，並帶明確 reason。

### 實作步驟
- 在每個 band：
  - 若 `len(xs)` 為奇數 → error
  - 可加入 duplicate x / zero-width interval guard

### 測試驗證
- 建立一個退化/自交/非矩形洞的測試 polygon（或刻意構造 edge case），assert `InvalidParams`。

---

## 6. layer_filter 預設列舉改用 `layout.layer_indexes()`（效能）

### As-Is
- `layer_filter is None` 時使用 `range(layout.layers())`。

### 問題/風險
- layer index 稀疏或 layer 數很大時，掃描成本暴增。

### To-Be
- 預設只掃描實際存在的 layer indexes。

### 實作步驟
- 改成：
  - `layer_filter = layout.layer_indexes()`

### 測試驗證
- 回歸測試：既有 tests 全部應通過。

---

## 7. 測試穩定性：檔案落盤等待用 polling 取代 sleep

### As-Is
- PNG 測試用 `time.sleep(0.2)` 等檔案。

### To-Be
- 用 deadline/poll：
  - 在 N 秒內檢查檔案存在且 size>0

### 實作步驟
- 加 helper `wait_for_file(path, timeout_s)`
- 替換所有 sleep。

### 測試驗證
- 在慢機器/CI 更穩。

---

## 8. 測試穩定性：server readiness timeout 可調

### As-Is
- `run_all_tests.sh` readiness deadline 5s。

### To-Be
- 提供 env：`RUN_ALL_TESTS_SERVER_READY_S`（例如預設 10s）。

### 實作步驟
- bash + python readiness script 讀 env。

---

# Backlog（Medium/Low）

## M1. 參數命名一致化（unit vs units）
- 統一欄位名或增加 alias 支援，並更新 docs。

## M2. docs/API.md Methods Index 補齊
- Index 加上 `hier.shapes_rec_boxes`。

## M3. hierarchy_path 語意文件化 + 測試強化
- 固定是否包含 start_cell 等。

## L1. bbox min/max 微效能
- 收點同時累積 bbox。

## L2. 測試目錄整理
- 將 root 下 `test_client_jsonrpc_*.py` 移入 `tests/`，保留 `run_all_tests.sh` 作入口。
