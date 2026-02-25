#!/usr/bin/env python3
"""Generate a deeper hierarchy GDS for Req6+ testing.

This script uses the existing JSON-RPC API (no server changes) to build a
parameterized hierarchy and export a GDS.

Default profile (per user request):
- depth=5
- branch factor random range [2,4]
- arrays up to 16 instances (e.g., 4x4)

NOTE on sizes / safety:
- This generator is meant to produce *moderately* deep hierarchies.
- For TooManyResults tests, prefer calling hier.query_down with a small limit
  (e.g. limit=100) rather than making the layout enormous.

Usage:
  python3 gen_deep_hier_gds.py <port> [--out deep_hier.gds] [--depth 5] [--branch-min 2] [--branch-max 4]
                             [--array-nx 4] [--array-ny 4] [--seed 1]

Outputs a GDS under the server cwd.
"""

import argparse
import json
import random
import socket
import sys


def recv_line(s: socket.socket) -> bytes:
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf


def rpc(s: socket.socket, _id: int, method: str, params: dict):
    req = {"jsonrpc": "2.0", "id": _id, "method": method, "params": params}
    s.sendall((json.dumps(req) + "\n").encode("utf-8"))
    raw = recv_line(s)
    if not raw.endswith(b"\n"):
        raise RuntimeError(f"Response not newline-terminated: {raw!r}")
    return json.loads(raw.decode("utf-8"))


def assert_result(resp: dict):
    if "result" not in resp:
        raise RuntimeError(f"Expected result, got {resp!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("port", type=int)
    ap.add_argument("--out", default="deep_hier_d5_b2-4_a4x4.gds")
    ap.add_argument("--depth", type=int, default=5)
    ap.add_argument("--branch-min", type=int, default=2)
    ap.add_argument("--branch-max", type=int, default=4)
    ap.add_argument("--array-nx", type=int, default=4)
    ap.add_argument("--array-ny", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    if args.depth < 1:
        raise SystemExit("depth must be >= 1")
    if args.branch_min < 1 or args.branch_max < args.branch_min:
        raise SystemExit("invalid branch range")
    if args.array_nx * args.array_ny > 16:
        raise SystemExit("array size must be <= 16")

    rng = random.Random(args.seed)

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5.0)
    s.connect(("127.0.0.1", args.port))

    _id = 1

    # New layout
    r = rpc(s, _id, "layout.new", {"top_cell": "TOP", "dbu": 0.001, "clear_previous": True})
    assert_result(r)
    _id += 1

    # layers
    r = rpc(s, _id, "layer.new", {"layer": 1, "datatype": 0, "as_current": False})
    assert_result(r)
    li1 = r["result"]["layer_index"]
    _id += 1

    r = rpc(s, _id, "layer.new", {"layer": 2, "datatype": 0, "as_current": False})
    assert_result(r)
    li2 = r["result"]["layer_index"]
    _id += 1

    # Create cells by level: L{level}_{index}
    levels = []
    levels.append(["TOP"])  # level 0
    for lvl in range(1, args.depth + 1):
        bf = rng.randint(args.branch_min, args.branch_max)
        names = [f"L{lvl}_{i}" for i in range(bf)]
        levels.append(names)

    # Create all cells (skip TOP)
    for lvl in range(1, len(levels)):
        for name in levels[lvl]:
            r = rpc(s, _id, "cell.create", {"name": name})
            assert_result(r)
            _id += 1

    # Put some shapes into each cell
    for lvl in range(0, len(levels)):
        for idx, name in enumerate(levels[lvl]):
            # Two rectangles on different layers with small offsets
            x0 = lvl * 10_000 + idx * 2_000
            y0 = idx * 3_000
            r = rpc(
                s,
                _id,
                "shape.create",
                {"cell": name, "type": "box", "coords": [x0, y0, x0 + 4000, y0 + 2500], "units": "dbu", "layer_index": li1},
            )
            assert_result(r)
            _id += 1

            r = rpc(
                s,
                _id,
                "shape.create",
                {"cell": name, "type": "box", "coords": [x0 + 1000, y0 + 1000, x0 + 6000, y0 + 4500], "units": "dbu", "layer_index": li2},
            )
            assert_result(r)
            _id += 1

    # Wire hierarchy: each parent connects to a subset of next level
    # Use a mix of single instances and arrays.
    for lvl in range(0, args.depth):
        parents = levels[lvl]
        children = levels[lvl + 1]
        for p_i, p in enumerate(parents):
            # Choose up to 2 children to keep growth moderate
            k = min(2, len(children))
            chosen = rng.sample(children, k=k)

            # One single instance
            c0 = chosen[0]
            r = rpc(
                s,
                _id,
                "instance.create",
                {"cell": p, "child_cell": c0, "trans": {"x": 50_000 + lvl * 5000 + p_i * 1000, "y": 0, "rot": 0, "mirror": False}},
            )
            assert_result(r)
            _id += 1

            # One array instance (if we have another child)
            if len(chosen) > 1:
                c1 = chosen[1]
                r = rpc(
                    s,
                    _id,
                    "instance_array.create",
                    {
                        "cell": p,
                        "child_cell": c1,
                        "trans": {"x": 0, "y": 30_000 + lvl * 3000 + p_i * 500, "rot": 0, "mirror": False},
                        "array": {"nx": args.array_nx, "ny": args.array_ny, "dx": 8000, "dy": 6000},
                    },
                )
                assert_result(r)
                _id += 1

    # Export
    r = rpc(s, _id, "layout.export", {"path": args.out, "overwrite": True})
    assert_result(r)

    s.close()
    print("OK", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
