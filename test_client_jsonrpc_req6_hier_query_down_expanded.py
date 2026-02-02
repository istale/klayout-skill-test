#!/usr/bin/env python3
"""Req6-3 integration test: hier.query_down expanded mode.

Covers:
- array expansion into per-element records
- expanded_index presence
- TooManyResults when expanded output exceeds limit

Usage:
  python3 test_client_jsonrpc_req6_hier_query_down_expanded.py [--verbose] <port>

Assumes fresh server state (restart server before running).
"""

import json
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


def assert_error_type(resp: dict, type_is: str, contains: str | None = None):
    if "error" not in resp:
        raise AssertionError(f"Expected error, got {resp!r}")
    err = resp["error"]
    data = err.get("data")
    if not isinstance(data, dict) or data.get("type") != type_is:
        raise AssertionError(f"Expected error.data.type={type_is!r}, got {resp!r}")
    if contains is not None and contains not in err.get("message", ""):
        raise AssertionError(f"Expected error.message contain {contains!r}, got {resp!r}")


def main() -> int:
    verbose = False
    args = list(sys.argv[1:])
    if "--verbose" in args:
        verbose = True
        args.remove("--verbose")

    if len(args) != 1:
        print("usage: test_client_jsonrpc_req6_hier_query_down_expanded.py [--verbose] <port>", file=sys.stderr)
        return 2

    port = int(args[0])

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5.0)
    s.connect(("127.0.0.1", port))

    _id = 1

    # Build simple layout
    r = rpc(s, _id, "layout.new", {"top_cell": "TOP", "dbu": 0.001, "clear_previous": True}, verbose)
    assert_result(r)
    _id += 1

    r = rpc(s, _id, "layer.new", {"layer": 1, "datatype": 0, "as_current": True}, verbose)
    assert_result(r)
    _id += 1

    for name in ("cell_a", "cell_b"):
        r = rpc(s, _id, "cell.create", {"name": name}, verbose)
        assert_result(r)
        _id += 1

    # Put minimal shapes to make bbox non-null
    r = rpc(s, _id, "shape.create", {"cell": "cell_a", "type": "box", "coords": [0, 0, 1000, 1000], "units": "dbu"}, verbose)
    assert_result(r)
    _id += 1

    r = rpc(s, _id, "shape.create", {"cell": "cell_b", "type": "box", "coords": [0, 0, 1000, 1000], "units": "dbu"}, verbose)
    assert_result(r)
    _id += 1

    # Instances: one single + one array (3x2 => 6)
    r = rpc(s, _id, "instance.create", {"cell": "TOP", "child_cell": "cell_a", "trans": {"x": 0, "y": 0, "rot": 0, "mirror": False}}, verbose)
    assert_result(r)
    _id += 1

    r = rpc(
        s,
        _id,
        "instance_array.create",
        {"cell": "TOP", "child_cell": "cell_b", "trans": {"x": 5000, "y": 0, "rot": 0, "mirror": False}, "array": {"nx": 3, "ny": 2, "dx": 2000, "dy": 1500}},
        verbose,
    )
    assert_result(r)
    _id += 1

    # Expanded query
    r = rpc(s, _id, "hier.query_down", {"cell": "TOP", "depth": 1, "mode": "expanded"}, verbose)
    assert_result(r)
    insts = r["result"].get("instances")
    if not isinstance(insts, list) or len(insts) != 7:
        raise AssertionError(f"Expected 7 records (1 single + 6 expanded), got {r!r}")

    expanded = [rec for rec in insts if rec.get("child_cell") == "cell_b"]
    if len(expanded) != 6:
        raise AssertionError(f"Expected 6 expanded cell_b records, got {len(expanded)}")

    for rec in expanded:
        ei = rec.get("expanded_index")
        if not (isinstance(ei, dict) and isinstance(ei.get("ix"), int) and isinstance(ei.get("iy"), int)):
            raise AssertionError(f"Expected expanded_index on expanded record, got {rec!r}")
        if not isinstance(rec.get("bbox"), dict):
            raise AssertionError(f"Expected bbox dict, got {rec!r}")

    _id += 1

    # TooManyResults with low limit
    r = rpc(s, _id, "hier.query_down", {"cell": "TOP", "depth": 1, "mode": "expanded", "limit": 3}, verbose)
    assert_error_type(r, "TooManyResults", "Too many results")

    s.close()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
