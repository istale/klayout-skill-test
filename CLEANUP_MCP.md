# MCP Server 移除計畫

> 最後更新：2026-02-25  
> 目的：移除所有 MCP server 相關程式碼與文件，保留 TCP server (KLayout JSON-RPC) 作為主要通訊方式。

---

## 📋 當前狀態

專案中包含 5 項 MCP 相關檔案/目錄：

| 序 | 檔案/目錄 | 路徑 | 大小 | 狀態 |
|----|-----------|------|------|------|
| 1 | MCP Server 主程式 | `mcp/klayout_mcp_server.py` | ~33KB | 待移除 |
| 2 | MCP Selftest | `mcp_selftest.py` | ~8KB | 待移除 |
| 3 | MCP Spec 文檔 | `docs/MCP_SPEC.md` | ~10KB | 待移除 |
| 4 | Unit Test | `tests/test_mcp_registry_entries_unit.py` | ~3KB | 待移除 |
| 5 | .cline Skill 文檔 | `.cline/skills/klayout-layout/SKILL.md` | ~3KB | 待移除 |

---

## 🎯 移除內容（共 5 項）

| 序 | 檔案/目錄 | 移除原因 |
|----|-----------|----------|
| 1 | `mcp/klayout_mcp_server.py` | MCP server 主程式（主要物件） |
| 2 | `mcp_selftest.py` | MCP server 測試檔（依賴 mcp/） |
| 3 | `docs/MCP_SPEC.md` | MCP 規格文件（已無用） |
| 4 | `tests/test_mcp_registry_entries_unit.py` | MCP registry 解析單元測試（依賴 mcp/） |
| 5 | `.cline/skills/klayout-layout/SKILL.md` | Cline skill 文檔（MCP server 使用） |

---

## 🔍 移除後的影響分析

| 檔案 | 是否引用 MCP | 影響程度 |
|------|--------------|----------|
| `klayout_gui_tcp_server.py` | ❌ 否 | 無影響（TCP server 是獨立的） |
| `README.md` | ⚠️ 可能提及 MCP | 需檢查並更新 |
| `docs/API.md` | ❌ 否 | 無影響（只描述 TCP protocol） |
| `docs/DEV.md` | ⚠️ 有提及 MCP test command | 需更新（移除 MCP unit test command） |
| `docs/EXECUTION_MODES.md` | ⚠️ 可能提及 | 需檢查 |
| `tests/test_client_*.py` | ❌ 否 | 無影響（測試 TCP client） |

---

## 🛠 執行步驟

### Step 1: 備份（可選）

建立 `mcp_backup_2026-02-25.tar.gz`（以防未來需要）：

```bash
tar -czf mcp_backup_2026-02-25.tar.gz \
    mcp/ \
    mcp_selftest.py
```

### Step 2: 移除檔案

```bash
# 刪除 mcp 目錄與所有內容
rm -rf mcp/

# 刪除独立的 MCP 檔案
rm -f mcp_selftest.py

# 刪除 MCP spec 文檔
rm -f docs/MCP_SPEC.md

# 刪除 MCP registry unit test
rm -f tests/test_mcp_registry_entries_unit.py

# 刪除 .cline skill 文檔
rm -f .cline/skills/klayout-layout/SKILL.md

# 清理空目錄
rmdir .cline/skills 2>/dev/null || true
```

### Step 3: 更新引用檔

#### `docs/DEV.md` — 移除 MCP unit test command

目前內容：
```markdown
### Unit tests (no KLayout server required)
- Run:
  - `python3 -m unittest -q tests.test_mcp_registry_entries_unit`
```

建議改為：
```markdown
### Unit tests (no KLayout server required)
- 僅剩 TCP client 測試，請直接執行：
  - `python3 tests/test_client_ping.py` (需 KLayout server running)
```

#### `README.md` — 檢查是否提及 MCP

執行搜尋：
```bash
grep -i "mcp" README.md || echo "No MCP mentions found"
```

若發現 MCP 相關內容，請更新描述。

#### `docs/EXECUTION_MODES.md` — 檢查是否提及 MCP

執行搜尋：
```bash
grep -i "mcp" docs/EXECUTION_MODES.md || echo "No MCP mentions found"
```

### Step 4: 驗證

確認剩餘檔案不依賴 MCP：

```bash
# 確認 mcp 相關檔案全部刪除
ls -la mcp/ || echo "✓ mcp directory removed"

# 確認 README.md 不再提及 MCP
grep -i "mcp" README.md || echo "✓ No MCP mentions in README"

# 確認 docs/DEV.md 不再提及 MCP unit test
grep -i "mcp_registry_entries_unit" docs/DEV.md || echo "✓ No MCP unit test ref in DEV.md"
```

---

## ✅ 確認問題（已決策）

| 問題 | 決議 |
|------|------|
| 是否確認移除全部 5 項？ | ✅ 是 |
| 是否需要保留 `mcp_selftest.py` 改寫為 TCP client test？ | ❌ 否 |
| 是否需要保留 `docs/MCP_SPEC.md` 作為歷史文件？ | ❌ 否 |

---

## 📝 執行記錄

- **執行時間**：2026-02-25  
- **執行者**：OpenClaw（小號）  
- **備份檔位置**：`mcp_backup_2026-02-25.tar.gz`  
- **最終狀態**：
  - 已刪除：`mcp/`、`mcp_selftest.py`、`docs/MCP_SPEC.md`、`tests/test_mcp_registry_entries_unit.py`、`.cline/skills/klayout-layout/SKILL.md`
  - 已更新：`docs/DEV.md`（移除 MCP unit test 引用）
  - 註：`klayout_gui_tcp_server.py` 保留 registry 寫入功能，但已移除「MCP v0」字樣，改為「dynamic port discovery」。
