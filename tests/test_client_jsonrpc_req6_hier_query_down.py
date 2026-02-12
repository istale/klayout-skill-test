#!/usr/bin/env python3
"""Req6-1 integration test: hier.query_down (structural).

Covers:
- basic down query with path + bbox
- TooManyResults when limit is exceeded

Usage:
  python3 test_client_jsonrpc_req6_hier_query_down.py [--verbose] <port>

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
        print("usage: test_client_jsonrpc_req6_hier_query_down.py [--verbose] <port>", file=sys.stderr)
        return 2

    port = int(args[0])

    out = "req6_demo.gds"
    try:
        os.remove(out)
    except FileNotFoundError:
        pass

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3.0)
    s.connect(("127.0.0.1", port))

    _id = 1

    # Create layout and a small hierarchy similar to req4.
    r = rpc(s, _id, "layout.new", {"top_cell": "TOP", "dbu": 0.001, "clear_previous": True}, verbose)
    assert_result(r)
    _id += 1

    r = rpc(s, _id, "layer.new", {"layer": 1, "datatype": 0, "as_current": False}, verbose)
    assert_result(r)
    li1 = r["result"]["layer_index"]
    _id += 1

    for name in ("cell_a", "cell_b"):
        r = rpc(s, _id, "cell.create", {"name": name}, verbose)
        assert_result(r)
        _id += 1

    # shapes
    r = rpc(
        s,
        _id,
        "shape.create",
        {"cell": "cell_a", "type": "box", "coords": [0, 0, 10_000, 6_000], "units": "dbu", "layer_index": li1},
        verbose,
    )
    assert_result(r)
    _id += 1

    r = rpc(
        s,
        _id,
        "shape.create",
        {"cell": "cell_b", "type": "box", "coords": [0, 0, 8_000, 4_000], "units": "dbu", "layer_index": li1},
        verbose,
    )
    assert_result(r)
    _id += 1

    # instances
    r = rpc(
        s,
        _id,
        "instance.create",
        {"cell": "TOP", "child_cell": "cell_a", "trans": {"x": 0, "y": 0, "rot": 0, "mirror": False}},
        verbose,
    )
    assert_result(r)
    _id += 1

    r = rpc(
        s,
        _id,
        "instance_array.create",
        {
            "cell": "TOP",
            "child_cell": "cell_b",
            "trans": {"x": 50_000, "y": 0, "rot": 0, "mirror": False},
            "array": {"nx": 3, "ny": 2, "dx": 20_000, "dy": 15_000},
        },
        verbose,
    )
    assert_result(r)
    _id += 1

    # Query down from TOP depth=1
    r = rpc(s, _id, "hier.query_down", {"cell": "TOP", "depth": 1, "include_bbox": True}, verbose)
    assert_result(r)
    insts = r["result"].get("instances")
    if not isinstance(insts, list) or len(insts) != 2:
        raise AssertionError(f"Expected 2 instances, got {r!r}")

    for rec in insts:
        if rec.get("path") != ["TOP"]:
            raise AssertionError(f"Expected path=['TOP'], got {rec!r}")
        if not isinstance(rec.get("bbox"), dict):
            raise AssertionError(f"Expected bbox dict, got {rec!r}")
        if not isinstance(rec.get("trans"), dict):
            raise AssertionError(f"Expected trans dict, got {rec!r}")

    _id += 1

    # Limit exceeded -> TooManyResults
    r = rpc(
        s,
        _id,
        "hier.query_down",
        {"cell": "TOP", "depth": 1, "max_results": 1, "include_bbox": True},
        verbose,
    )
    assert_error_type(r, "TooManyResults", "Too many results")

    s.close()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
