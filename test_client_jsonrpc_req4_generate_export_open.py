#!/usr/bin/env python3
"""Req4 integration test:

4-1) Use existing RPCs to generate and export a GDS.
4-2) Open that GDS in KLayout (layout.open) with mode=0 and switch server state,
     then export again to confirm open+state switch works.

Usage:
  python3 test_client_jsonrpc_req4_generate_export_open.py [--verbose] <port>

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


def main() -> int:
    verbose = False
    args = list(sys.argv[1:])
    if "--verbose" in args:
        verbose = True
        args.remove("--verbose")

    if len(args) != 1:
        print("usage: test_client_jsonrpc_req4_generate_export_open.py [--verbose] <port>", file=sys.stderr)
        return 2

    port = int(args[0])

    out1 = "req4_demo.gds"
    out2 = "req4_demo_roundtrip.gds"
    for p in (out1, out2):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3.0)
    s.connect(("127.0.0.1", port))

    _id = 1

    # Create new layout
    r = rpc(s, _id, "layout.new", {"top_cell": "TOP", "dbu": 0.001, "clear_previous": True}, verbose)
    assert_result(r)
    _id += 1

    # Create layer 1/0 and 2/0
    r = rpc(s, _id, "layer.new", {"layer": 1, "datatype": 0, "as_current": False}, verbose)
    assert_result(r)
    li1 = r["result"]["layer_index"]
    _id += 1

    r = rpc(s, _id, "layer.new", {"layer": 2, "datatype": 0, "as_current": False}, verbose)
    assert_result(r)
    li2 = r["result"]["layer_index"]
    _id += 1

    # Create cells
    for name in ("cell_a", "cell_b"):
        r = rpc(s, _id, "cell.create", {"name": name}, verbose)
        assert_result(r)
        _id += 1

    # cell_a: one rect on 1/0
    r = rpc(
        s,
        _id,
        "shape.create",
        {"cell": "cell_a", "type": "box", "coords": [0, 0, 10000, 6000], "units": "dbu", "layer_index": li1},
        verbose,
    )
    assert_result(r)
    _id += 1

    # cell_b: two rects on 1/0 and 2/0
    r = rpc(
        s,
        _id,
        "shape.create",
        {"cell": "cell_b", "type": "box", "coords": [0, 0, 8000, 4000], "units": "dbu", "layer_index": li1},
        verbose,
    )
    assert_result(r)
    _id += 1

    r = rpc(
        s,
        _id,
        "shape.create",
        {"cell": "cell_b", "type": "box", "coords": [2000, 2000, 12000, 9000], "units": "dbu", "layer_index": li2},
        verbose,
    )
    assert_result(r)
    _id += 1

    # TOP: one instance of cell_a, and an array of cell_b
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
            "trans": {"x": 50000, "y": 0, "rot": 0, "mirror": False},
            "array": {"nx": 3, "ny": 2, "dx": 20000, "dy": 15000},
        },
        verbose,
    )
    assert_result(r)
    _id += 1

    # Export
    r = rpc(s, _id, "layout.export", {"path": out1, "overwrite": True}, verbose)
    assert_result(r)
    _id += 1

    if not os.path.exists(out1):
        raise AssertionError(f"Expected exported GDS to exist: {out1}")

    # Reset state (ensure layout.open really switches active layout)
    r = rpc(s, _id, "layout.new", {"top_cell": "EMPTY", "dbu": 0.001, "clear_previous": True}, verbose)
    assert_result(r)
    _id += 1

    # Open in KLayout (mode=0 default)
    r = rpc(s, _id, "layout.open", {"path": out1}, verbose)
    assert_result(r)
    if r["result"].get("opened") is not True:
        raise AssertionError(f"Expected opened=true, got {r!r}")
    _id += 1

    # Export again to confirm server state is now the loaded layout
    r = rpc(s, _id, "layout.export", {"path": out2, "overwrite": True}, verbose)
    assert_result(r)
    _id += 1

    if not os.path.exists(out2):
        raise AssertionError(f"Expected roundtrip export to exist: {out2}")

    s.close()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
