#!/usr/bin/env python3
"""Req5 integration test: basic layout info queries.

Covers:
- layout.get_topcell: errors on multiple top cells
- layout.get_layers
- layout.get_dbu
- layout.get_cells
- layout.get_hierarchy_depth (top=0 definition)

Usage:
  python3 test_client_jsonrpc_req5_layout_info.py [--verbose] <port>

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
        print("usage: test_client_jsonrpc_req5_layout_info.py [--verbose] <port>", file=sys.stderr)
        return 2

    port = int(args[0])

    out = "req5_demo.gds"
    try:
        os.remove(out)
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

    # Create layers 1/0 and 2/0
    r = rpc(s, _id, "layer.new", {"layer": 1, "datatype": 0, "as_current": False}, verbose)
    assert_result(r)
    li1 = r["result"]["layer_index"]
    _id += 1

    r = rpc(s, _id, "layer.new", {"layer": 2, "datatype": 0, "as_current": False}, verbose)
    assert_result(r)
    li2 = r["result"]["layer_index"]
    _id += 1

    # Create child cells
    for name in ("cell_a", "cell_b"):
        r = rpc(s, _id, "cell.create", {"name": name}, verbose)
        assert_result(r)
        _id += 1

    # Shapes
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

    r = rpc(
        s,
        _id,
        "shape.create",
        {"cell": "cell_b", "type": "box", "coords": [2_000, 2_000, 12_000, 9_000], "units": "dbu", "layer_index": li2},
        verbose,
    )
    assert_result(r)
    _id += 1

    # Instances under TOP
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

    # Export & reopen (ensure methods work after layout.open too)
    r = rpc(s, _id, "layout.export", {"path": out, "overwrite": True}, verbose)
    assert_result(r)
    _id += 1

    r = rpc(s, _id, "layout.open", {"path": out, "mode": 0}, verbose)
    assert_result(r)
    _id += 1

    # 5-1 top cell should be TOP now
    r = rpc(s, _id, "layout.get_topcell", {}, verbose)
    assert_result(r)
    if r["result"].get("top_cell") != "TOP":
        raise AssertionError(f"Expected top_cell=TOP, got {r!r}")
    _id += 1

    # 5-2 layers
    r = rpc(s, _id, "layout.get_layers", {}, verbose)
    assert_result(r)
    layers = r["result"].get("layers")
    if not isinstance(layers, list):
        raise AssertionError(f"Expected layers list, got {r!r}")
    _id += 1

    # 5-3 dbu
    r = rpc(s, _id, "layout.get_dbu", {}, verbose)
    assert_result(r)
    if abs(float(r["result"].get("dbu")) - 0.001) > 1e-12:
        raise AssertionError(f"Expected dbu=0.001, got {r!r}")
    _id += 1

    # 5-4 cells
    r = rpc(s, _id, "layout.get_cells", {}, verbose)
    assert_result(r)
    cells = r["result"].get("cells")
    if not isinstance(cells, list) or not {"TOP", "cell_a", "cell_b"}.issubset(set(cells)):
        raise AssertionError(f"Expected cells to include TOP/cell_a/cell_b, got {r!r}")
    _id += 1

    # 5-5 hierarchy depth: top=0, top has direct children only => depth 1
    r = rpc(s, _id, "layout.get_hierarchy_depth", {}, verbose)
    assert_result(r)
    if r["result"].get("depth") != 1:
        raise AssertionError(f"Expected depth=1, got {r!r}")
    if "top=0" not in str(r["result"].get("depth_definition")):
        raise AssertionError(f"Expected depth_definition mention top=0, got {r!r}")
    _id += 1

    # Multiple top cells -> error
    r = rpc(s, _id, "cell.create", {"name": "ORPHAN"}, verbose)
    assert_result(r)
    _id += 1

    r = rpc(s, _id, "layout.get_topcell", {}, verbose)
    assert_error_type(r, "MultipleTopCells", "Multiple top cells")
    _id += 1

    s.close()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
