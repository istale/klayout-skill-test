# DEV — Developer notes

## Test / verification commands

### Unit tests (no KLayout server required)
- Run:
  - `python3 -m unittest -q tests.test_mcp_registry_entries_unit`

### Integration tests (requires local KLayout binary)
- Run (starts/stops the server per test):
  - `./run_all_tests.sh`

## Engineering policy "instinct" (continuous-learning-v2)

- Trigger: We need to change code in this repo, but we don't want the workflow to depend on a running KLayout server for basic correctness checks.
- Action: Prefer adding a small **unit test** first (using stdlib `unittest`), then implement the minimal change, and record a one-liner verification command here.
- Evidence: `tests/test_mcp_registry_entries_unit.py` verifies `_read_registry_entries()` behavior (coercion + malformed skipping).
- Confidence: High (runs fast, deterministic, no external dependency).
