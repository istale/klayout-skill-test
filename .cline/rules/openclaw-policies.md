# OpenClaw POLICIES（移植版，供 Cline 在本 repo 參考）

> 目的：當 Cline 在本 repo 需要「寫/改程式」時，套用一致的工程規範。
> 若只是執行 layout tool calls（不改 code），本文件不強制。

## 1) TDD 工作流（摘要）
- 先寫測試（紅）→ 最小實作（綠）→ 重構（保持綠）
- 至少覆蓋：正常路徑、錯誤路徑、邊界條件
- 每次回報要附：如何驗證（命令 + 結果摘要）

## 2) Code Review（摘要）
- 在準備提交/推送前：
  - 看 `git diff` / `git status`
  - 理解周邊程式碼（不只 patch）
  - 用清單掃：
    - CRITICAL：密鑰/注入/XSS/授權繞過/敏感 log
    - HIGH：缺錯誤處理/timeout、缺測試、console.log
- 只回報高信心問題；結尾要給：Approve / Warning / Block

## 3) 持續學習 v2（摘要）
- 若使用者說「下次不要再犯 / 以後都照這個做」：把結論落盤
- 格式（Trigger/Action/Evidence/Confidence）
- 本 repo 優先落盤位置：
  - `docs/`（規格/流程）
  - `.clinerules`（永遠啟用的 guardrails）
  - `.cline/skills/*`（可重用工作流）
