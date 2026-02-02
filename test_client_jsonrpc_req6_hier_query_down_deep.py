#!/usr/bin/env python3
"""Req6-1 deeper integration test: hier.query_down with a deeper hierarchy.

Goals:
- Use a deeper hierarchy (depth=5, branching 2..4, array<=16) to make testing
  closer to realistic cases.
- Validate TooManyResults behavior with a small limit (limit=100) and ensure
  error.message is explicit about the safety guardrail.

Usage:
  python3 test_client_jsonrpc_req6_hier_query_down_deep.py [--verbose] <port>

Assumes fresh server state (restart server before running).
"""

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


def rpc(s: socket.socket, _id: int, method: str, params: dict, verbose: bool = False):
    req = {"jsonrpc": "2.0", "id": _id, "method": method, "params": params}
    if verbose:
        print(">>>", json.dumps(req, ensure_ascii=False))
    s.sendall((json.dumps(req) + "\n").encode("utf-8"))
    raw = recv_line(s)
    if not raw.endswith(b"\n"):
        raise AssertionError(f"Response not newline-terminated: {raw!r}")
    if verbose:
        print("<<<", raw.decode("utf-8", errors="replace").rstrip("\n"))
    return json.loads(raw.decode("utf-8"))


def assert_result(resp: dict):
    if "result" not in resp:
        raise AssertionError(f"Expected result, got {resp!r}")


def assert_error(resp: dict, type_is: str, msg_contains: list[str]):
    if "error" not in resp:
        raise AssertionError(f"Expected error, got {resp!r}")
    err = resp["error"]
    data = err.get("data")
    if not isinstance(data, dict) or data.get("type") != type_is:
        raise AssertionError(f"Expected error.data.type={type_is!r}, got {resp!r}")
    msg = err.get("message", "")
    for t in msg_contains:
        if t not in msg:
            raise AssertionError(f"Expected error.message to contain {t!r}, got {msg!r}")


def build_deep_layout(s: socket.socket, verbose: bool = False):
    """Build a deterministic deep hierarchy in the active layout."""
    rng = random.Random(1)
    depth = 5
    branch_min, branch_max = 2, 4
    array_nx, array_ny = 4, 4  # 16

    _id = 1

    r = rpc(s, _id, "layout.new", {"top_cell": "TOP", "dbu": 0.001, "clear_previous": True}, verbose)
    assert_result(r)
    _id += 1

    r = rpc(s, _id, "layer.new", {"layer": 1, "datatype": 0, "as_current": False}, verbose)
    assert_result(r)
    li1 = r["result"]["layer_index"]
    _id += 1

    r = rpc(s, _id, "layer.new", {"layer": 2, "datatype": 0, "as_current": False}, verbose)
    assert_result(r)
    li2 = r["result"]["layer_index"]
    _id += 1

    levels: list[list[str]] = [["TOP"]]
    for lvl in range(1, depth + 1):
        bf = rng.randint(branch_min, branch_max)
        levels.append([f"L{lvl}_{i}" for i in range(bf)])

    for lvl in range(1, len(levels)):
        for name in levels[lvl]:
            r = rpc(s, _id, "cell.create", {"name": name}, verbose)
            assert_result(r)
            _id += 1

    # Shapes
    for lvl in range(0, len(levels)):
        for idx, name in enumerate(levels[lvl]):
            x0 = lvl * 10_000 + idx * 2_000
            y0 = idx * 3_000
            r = rpc(
                s,
                _id,
                "shape.create",
                {"cell": name, "type": "box", "coords": [x0, y0, x0 + 4000, y0 + 2500], "units": "dbu", "layer_index": li1},
                verbose,
            )
            assert_result(r)
            _id += 1

            r = rpc(
                s,
                _id,
                "shape.create",
                {"cell": name, "type": "box", "coords": [x0 + 1000, y0 + 1000, x0 + 6000, y0 + 4500], "units": "dbu", "layer_index": li2},
                verbose,
            )
            assert_result(r)
            _id += 1

    # Instances
    # To make results large enough to reliably hit limit=100, we connect each
    # parent to up to 4 children (mix of single + array).
    for lvl in range(0, depth):
        parents = levels[lvl]
        children = levels[lvl + 1]
        for p_i, p in enumerate(parents):
            # Deterministically pick up to 4 children
            k = min(4, len(children))
            chosen = rng.sample(children, k=k)

            # child 0: single
            r = rpc(
                s,
                _id,
                "instance.create",
                {"cell": p, "child_cell": chosen[0], "trans": {"x": 50_000 + lvl * 5000 + p_i * 1000, "y": 0, "rot": 0, "mirror": False}},
                verbose,
            )
            assert_result(r)
            _id += 1

            # child 1: array
            if len(chosen) > 1:
                r = rpc(
                    s,
                    _id,
                    "instance_array.create",
                    {
                        "cell": p,
                        "child_cell": chosen[1],
                        "trans": {"x": 0, "y": 30_000 + lvl * 3000 + p_i * 500, "rot": 0, "mirror": False},
                        "array": {"nx": array_nx, "ny": array_ny, "dx": 8000, "dy": 6000},
                    },
                    verbose,
                )
                assert_result(r)
                _id += 1

            # child 2: another single
            if len(chosen) > 2:
                r = rpc(
                    s,
                    _id,
                    "instance.create",
                    {"cell": p, "child_cell": chosen[2], "trans": {"x": 52_000 + lvl * 5000 + p_i * 1000, "y": 10_000, "rot": 0, "mirror": False}},
                    verbose,
                )
                assert_result(r)
                _id += 1

            # child 3: another array
            if len(chosen) > 3:
                r = rpc(
                    s,
                    _id,
                    "instance_array.create",
                    {
                        "cell": p,
                        "child_cell": chosen[3],
                        "trans": {"x": 10_000, "y": 35_000 + lvl * 3000 + p_i * 500, "rot": 0, "mirror": False},
                        "array": {"nx": array_nx, "ny": array_ny, "dx": 9000, "dy": 6500},
                    },
                    verbose,
                )
                assert_result(r)
                _id += 1

    return _id


def main() -> int:
    verbose = False
    args = list(sys.argv[1:])
    if "--verbose" in args:
        verbose = True
        args.remove("--verbose")

    if len(args) != 1:
        print("usage: test_client_jsonrpc_req6_hier_query_down_deep.py [--verbose] <port>", file=sys.stderr)
        return 2

    port = int(args[0])

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5.0)
    s.connect(("127.0.0.1", port))

    next_id = build_deep_layout(s, verbose)

    # Small limit should error with TooManyResults and clear message
    r = rpc(s, next_id, "hier.query_down", {"cell": "TOP", "depth": 5, "limit": 100}, verbose)
    assert_error(r, "TooManyResults", ["Too many results", "100", "safety limit"])
    next_id += 1

    # Default limit should succeed and return a non-trivial amount.
    r = rpc(s, next_id, "hier.query_down", {"cell": "TOP", "depth": 5}, verbose)
    assert_result(r)
    insts = r["result"].get("instances")
    if not isinstance(insts, list) or len(insts) < 10:
        raise AssertionError(f"Expected >=10 instances, got {r!r}")

    s.close()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
