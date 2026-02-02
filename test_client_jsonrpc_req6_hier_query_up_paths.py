#!/usr/bin/env python3
"""Req6-2 integration test: hier.query_up_paths.

Covers:
- export+open to set gds filename
- query paths for a cell used in hierarchy
- multiple top cells -> error

Usage:
  python3 test_client_jsonrpc_req6_hier_query_up_paths.py [--verbose] <port>

Assumes fresh server state (restart server before running).
"""

import json
import os
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


def assert_error_type(resp: dict, type_is: str, msg_contains: str | None = None):
    if "error" not in resp:
        raise AssertionError(f"Expected error, got {resp!r}")
    err = resp["error"]
    data = err.get("data")
    if not isinstance(data, dict) or data.get("type") != type_is:
        raise AssertionError(f"Expected error.data.type={type_is!r}, got {resp!r}")
    if msg_contains is not None and msg_contains not in err.get("message", ""):
        raise AssertionError(f"Expected error.message contain {msg_contains!r}, got {resp!r}")


def main() -> int:
    verbose = False
    args = list(sys.argv[1:])
    if "--verbose" in args:
        verbose = True
        args.remove("--verbose")

    if len(args) != 1:
        print("usage: test_client_jsonrpc_req6_hier_query_up_paths.py [--verbose] <port>", file=sys.stderr)
        return 2

    port = int(args[0])

    gds = "req6_paths_demo.gds"
    try:
        os.remove(gds)
    except FileNotFoundError:
        pass

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5.0)
    s.connect(("127.0.0.1", port))

    _id = 1

    # Build a small hierarchy: TOP -> A, TOP -> B, A -> C
    r = rpc(s, _id, "layout.new", {"top_cell": "TOP", "dbu": 0.001, "clear_previous": True}, verbose)
    assert_result(r)
    _id += 1

    r = rpc(s, _id, "layer.new", {"layer": 1, "datatype": 0, "as_current": True}, verbose)
    assert_result(r)
    _id += 1

    for name in ("A", "B", "C"):
        r = rpc(s, _id, "cell.create", {"name": name}, verbose)
        assert_result(r)
        _id += 1

    r = rpc(
        s,
        _id,
        "shape.create",
        {"cell": "C", "type": "box", "coords": [0, 0, 1000, 1000], "units": "dbu"},
        verbose,
    )
    assert_result(r)
    _id += 1

    r = rpc(s, _id, "instance.create", {"cell": "TOP", "child_cell": "A", "trans": {"x": 0, "y": 0, "rot": 0, "mirror": False}}, verbose)
    assert_result(r)
    _id += 1

    r = rpc(s, _id, "instance.create", {"cell": "TOP", "child_cell": "B", "trans": {"x": 2000, "y": 0, "rot": 0, "mirror": False}}, verbose)
    assert_result(r)
    _id += 1

    r = rpc(s, _id, "instance.create", {"cell": "A", "child_cell": "C", "trans": {"x": 0, "y": 3000, "rot": 0, "mirror": False}}, verbose)
    assert_result(r)
    _id += 1

    # Export and reopen to set filename in server state
    r = rpc(s, _id, "layout.export", {"path": gds, "overwrite": True}, verbose)
    assert_result(r)
    _id += 1

    r = rpc(s, _id, "layout.open", {"path": gds, "mode": 0}, verbose)
    assert_result(r)
    _id += 1

    # Query up paths for C
    r = rpc(s, _id, "hier.query_up_paths", {"cell": "C"}, verbose)
    assert_result(r)
    paths = r["result"].get("paths")
    if not isinstance(paths, list) or len(paths) < 1:
        raise AssertionError(f"Expected at least 1 path, got {r!r}")

    p0 = paths[0]
    if not (isinstance(p0, list) and len(p0) >= 3):
        raise AssertionError(f"Expected path segments list, got {r!r}")
    if p0[0] != gds:
        raise AssertionError(f"Expected first segment to be gds filename {gds!r}, got {p0!r}")
    if p0[1] != "TOP":
        raise AssertionError(f"Expected second segment TOP, got {p0!r}")
    if p0[-1] != "C":
        raise AssertionError(f"Expected last segment C, got {p0!r}")

    _id += 1

    # Create an orphan cell -> multiple top cells
    r = rpc(s, _id, "cell.create", {"name": "ORPHAN"}, verbose)
    assert_result(r)
    _id += 1

    r = rpc(s, _id, "hier.query_up_paths", {"cell": "C"}, verbose)
    assert_error_type(r, "MultipleTopCells", "Multiple top cells")

    s.close()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
