# DEV — Developer notes

## Test / verification commands

### Unit tests

目前沒有獨立的「不需啟動 KLayout server」單元測試。

（若未來需要恢復此類測試，建議優先針對 TCP client / 協定層做純函式或 mock-based 測試。）

### Integration tests (requires local KLayout binary)
- Run (starts/stops the server per test):
  - `./run_all_tests.sh`

## Engineering policy "instinct" (continuous-learning-v2)

- Trigger: We need to change code in this repo, but we don't want the workflow to depend on a running KLayout server for basic correctness checks.
- Action: Prefer adding a small **unit test** first (using stdlib `unittest`), then implement the minimal change, and record a one-liner verification command here.
- Evidence:（待補）目前尚無可離線執行的單元測試；僅保留整合測試腳本 `./run_all_tests.sh`。
- Confidence: High (runs fast, deterministic, no external dependency).
