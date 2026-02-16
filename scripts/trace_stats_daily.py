#!/usr/bin/env python3
"""Daily trace stats for KLayout MCP.

Usage:
  python3 scripts/trace_stats_daily.py [traces_dir]

Reads traces/run_*.jsonl and prints daily buckets (UTC) for:
- total calls
- ok/fail
- transport_error count
- calls with retry

Notes:
- Back-compat: if `ok` is missing, infer from `rpc_response`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def parse_ts(ts_utc: str) -> datetime | None:
    if not ts_utc:
        return None
    try:
        return datetime.strptime(ts_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def ok_flag(entry: dict) -> bool:
    if entry.get("ok") is not None:
        return bool(entry.get("ok"))
    rr = entry.get("rpc_response", {})
    return "error" not in rr


def main(argv: list[str]) -> int:
    traces_dir = Path(argv[1]) if len(argv) > 1 else Path("traces")
    files = sorted(traces_dir.glob("run_*.jsonl"))
    if not files:
        print(f"no trace files under: {traces_dir}")
        return 0

    buckets = defaultdict(lambda: {"total": 0, "ok": 0, "fail": 0, "transport": 0, "retry": 0})

    for fp in files:
        for e in iter_jsonl(fp):
            ts = parse_ts(e.get("ts_utc", ""))
            if ts is None:
                continue
            day_key = ts.strftime("%Y-%m-%d")
            b = buckets[day_key]
            b["total"] += 1
            if ok_flag(e):
                b["ok"] += 1
            else:
                b["fail"] += 1
            if e.get("transport_error"):
                b["transport"] += 1
            if int(e.get("retry_count", 0) or 0) > 0:
                b["retry"] += 1

    print("day(UTC)\ttotal\tok\tfail\ttransport_error\twith_retry")
    for k in sorted(buckets.keys()):
        b = buckets[k]
        print(f"{k}\t{b['total']}\t{b['ok']}\t{b['fail']}\t{b['transport']}\t{b['retry']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
