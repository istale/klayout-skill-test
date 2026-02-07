#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test for hier.query_down_stats

Asserts that counts are grouped by child_cell and arrays are expanded.

Layout:
  TOP -> instance cell_a (single)
  TOP -> instance_array cell_b (nx=3, ny=2)

Expected stats (depth=1):
  cell_a: 1
  cell_b: 6
  total: 7
"""

import json
import socket
import sys


def recv_line(sock):
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    line, _, _ = buf.partition(b"\n")
    return line


def rpc(sock, _id, method, params=None, verbose=False):
    req = {"jsonrpc": "2.0", "id": _id, "method": method, "params": params or {}}
    if verbose:
        print(">>>", json.dumps(req))
    sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
    resp = json.loads(recv_line(sock).decode("utf-8"))
    if verbose:
        print("<<<", resp)
    return resp


def assert_result(resp):
    if "error" in resp:
        raise AssertionError(f"Expected result, got error: {resp}")


def main() -> int:
    verbose = False
    args = list(sys.argv[1:])
    if "--verbose" in args:
        verbose = True
        args.remove("--verbose")

    if len(args) != 1:
        print("usage: test_client_jsonrpc_req6_hier_query_down_stats.py [--verbose] <port>", file=sys.stderr)
        return 2

    port = int(args[0])

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5.0)
    s.connect(("127.0.0.1", port))

    _id = 1
    r = rpc(s, _id, "layout.new", {"dbu": 0.001, "top_cell": "TOP", "clear_previous": True}, verbose)
    assert_result(r)
    _id += 1

    r = rpc(s, _id, "layer.new", {"layer": 1, "datatype": 0, "as_current": True}, verbose)
    assert_result(r)
    li = int(r["result"]["layer_index"])
    _id += 1

    # cells
    for nm in ("cell_a", "cell_b"):
        r = rpc(s, _id, "cell.create", {"name": nm}, verbose)
        assert_result(r)
        _id += 1

    # Give child cells some geometry so bbox logic (if any) has something.
    r = rpc(s, _id, "shape.create", {"cell": "cell_a", "layer_index": li, "type": "box", "coords": [0, 0, 1000, 1000]}, verbose)
    assert_result(r)
    _id += 1
    r = rpc(s, _id, "shape.create", {"cell": "cell_b", "layer_index": li, "type": "box", "coords": [0, 0, 1000, 1000]}, verbose)
    assert_result(r)
    _id += 1

    # TOP instances
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

    r = rpc(s, _id, "hier.query_down_stats", {"cell": "TOP", "depth": 1}, verbose)
    assert_result(r)

    stats = r["result"].get("by_child_cell")
    total = r["result"].get("total")
    if stats is None or not isinstance(stats, dict):
        raise AssertionError(f"Expected by_child_cell dict, got {r!r}")

    if int(stats.get("cell_a", -1)) != 1:
        raise AssertionError(f"Expected cell_a=1, got {stats}")
    if int(stats.get("cell_b", -1)) != 6:
        raise AssertionError(f"Expected cell_b=6, got {stats}")
    if int(total) != 7:
        raise AssertionError(f"Expected total=7, got {total} ({stats})")

    s.close()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
