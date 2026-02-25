#!/usr/bin/env python3
"""Trace stats for KLayout tool traces.

Usage:
  python3 scripts/trace_stats.py [traces_dir]

Outputs counts and rates for transport errors and retries.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from collections import Counter, defaultdict


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


def main(argv: list[str]) -> int:
    traces_dir = Path(argv[1]) if len(argv) > 1 else Path("traces")
    if not traces_dir.exists():
        print(f"traces dir not found: {traces_dir}", file=sys.stderr)
        return 2

    files = sorted(traces_dir.glob("run_*.jsonl"))
    if not files:
        print(f"no trace files under: {traces_dir}")
        return 0

    total = 0
    ok = 0
    transport_err = 0
    retries = 0

    by_tool = Counter()
    by_tool_transport = Counter()
    by_errno = Counter()
    by_errtype = Counter()

    for fp in files:
        for e in iter_jsonl(fp):
            total += 1
            tool = e.get("tool", "")
            by_tool[tool] += 1
            ok_flag = e.get("ok")
            if ok_flag is None:
                # Back-compat with older traces: infer from rpc_response
                rr = e.get("rpc_response", {})
                ok_flag = ("error" not in rr)
            if ok_flag is True:
                ok += 1

            te = e.get("transport_error")
            if te:
                transport_err += 1
                by_tool_transport[tool] += 1
                if "errno" in te:
                    by_errno[str(te.get("errno"))] += 1
                by_errtype[te.get("type", "")] += 1

            if int(e.get("retry_count", 0) or 0) > 0:
                retries += 1

    fail = total - ok

    def pct(x: int, d: int) -> str:
        return f"{(100.0 * x / d):.2f}%" if d else "0%"

    print("== Trace Stats ==")
    print(f"trace_files: {len(files)}")
    print(f"total_calls: {total}")
    print(f"ok: {ok} ({pct(ok, total)})")
    print(f"fail: {fail} ({pct(fail, total)})")
    print(f"transport_error: {transport_err} ({pct(transport_err, total)})")
    print(f"calls_with_retry: {retries} ({pct(retries, total)})")

    if by_errtype:
        print("\n-- transport_error types --")
        for k, v in by_errtype.most_common():
            print(f"{k}: {v}")

    if by_errno:
        print("\n-- transport_error errno --")
        for k, v in by_errno.most_common():
            print(f"errno {k}: {v}")

    if by_tool_transport:
        print("\n-- transport_error by tool --")
        for k, v in by_tool_transport.most_common():
            print(f"{k}: {v} / {by_tool[k]} ({pct(v, by_tool[k])})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
