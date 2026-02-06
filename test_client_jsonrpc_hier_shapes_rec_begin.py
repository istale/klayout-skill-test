#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test for hier.shapes_rec (begin_shapes_rec based).

Creates:
  - TOP cell
  - CHILD cell with a box on layer 0
  - Instance CHILD in TOP with trans (x=1000, y=2000)

Then calls hier.shapes_rec(start_cell="TOP") and asserts >=1 shape.

Note: This is a functional smoke test; exact hierarchy_path formatting may vary
across KLayout bindings, so we check for presence of "CHILD".
"""

import argparse
import json
import socket


def recv_line(sock):
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    if not buf:
        return b""
    line, _, _rest = buf.partition(b"\n")
    return line


def rpc(sock, _id, method, params=None, verbose=False):
    req = {"jsonrpc": "2.0", "id": _id, "method": method, "params": params or {}}
    if verbose:
        print(">>>", json.dumps(req))
    sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
    resp = json.loads(recv_line(sock))
    if verbose:
        print("<<<", resp)
    if "error" in resp:
        raise RuntimeError(resp["error"])
    return resp["result"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", type=int)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    s = socket.create_connection(("127.0.0.1", args.port), timeout=5)
    s.settimeout(5)

    # Fresh in-memory layout
    rpc(s, 1, "layout.new", {"dbu": 0.001, "top_cell": "TOP", "clear_previous": True}, args.verbose)

    # Layer 1/0 as current -> should be layer_index 0 in a fresh layout.
    layer = rpc(s, 2, "layer.new", {"layer": 1, "datatype": 0, "as_current": True}, args.verbose)
    li = int(layer["layer_index"])

    rpc(s, 3, "cell.create", {"name": "CHILD"}, args.verbose)

    # Insert one box in CHILD: (0,0)-(100,200) DBU
    rpc(
        s,
        4,
        "shape.create",
        {"cell": "CHILD", "layer_index": li, "type": "box", "coords": [0, 0, 100, 200]},
        args.verbose,
    )

    # Instance CHILD in TOP with translation (1000,2000) DBU
    rpc(
        s,
        5,
        "instance.create",
        {"cell": "TOP", "child_cell": "CHILD", "trans": {"x": 1000, "y": 2000, "rot": 0, "mirror": False}},
        args.verbose,
    )

    # Query shapes recursively
    out = rpc(
        s,
        6,
        "hier.shapes_rec",
        {"start_cell": "TOP", "unit": "um", "shape_types": ["box", "polygon", "path"], "max_results": 1000},
        args.verbose,
    )

    shapes = out.get("shapes", [])
    if len(shapes) < 1:
        raise AssertionError(f"expected >=1 shapes, got {len(shapes)}")

    # At least one shape should come from CHILD.
    any_child = any(("CHILD" in (rec.get("hierarchy_path") or [])) for rec in shapes)
    if not any_child:
        raise AssertionError(f"expected some hierarchy_path containing 'CHILD', got first={shapes[0].get('hierarchy_path')}")

    # Basic bbox sanity for the inserted box (translated):
    # Original bbox in DBU: [0,0,100,200]
    # After translation: [1000,2000,1100,2200]
    # In um with dbu=0.001: [1.0,2.0,1.1,2.2]
    bb = None
    for rec in shapes:
        if rec.get("shape_type") == "box" and rec.get("bbox_um") is not None:
            bb = rec["bbox_um"]
            break
    if bb is None:
        raise AssertionError("expected at least one box record with bbox_um")

    exp = [1.0, 2.0, 1.1, 2.2]
    # allow tiny float errors
    for got, ex in zip(bb, exp):
        if abs(float(got) - float(ex)) > 1e-6:
            raise AssertionError(f"bbox mismatch: got={bb}, expected={exp}")

    print("OK hier.shapes_rec count=", len(shapes))


if __name__ == "__main__":
    main()
