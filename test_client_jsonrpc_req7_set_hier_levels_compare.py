#!/usr/bin/env python3
"""Req7: compare screenshots with different hierarchy display depths.

Goal
----
Verify that `view.set_hier_levels` affects what is drawn by the GUI view.

We build a tiny hierarchy:
  TOP contains an instance of CHILD.
  CHILD contains a box shape.

Then we take two GUI screenshots:
  A) max_hier_levels = 0 (draw only top-level geometry)
  B) max_hier() (draw all hierarchy levels)

Expectation
-----------
Screenshot B should include CHILD geometry; screenshot A should not.
We assert that both PNGs exist and their bytes differ.

Note
----
This test requires GUI (MainWindow + current_view). In environments without
GUI view, it will SKIP.
"""

import hashlib
import os
import socket
import json
import time


def send_obj(s, obj):
    raw = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")
    s.sendall(raw)


def recv_line(s):
    buf = b""
    while b"\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            raise RuntimeError("connection closed")
        buf += chunk
    line, _rest = buf.split(b"\n", 1)
    return line.decode("utf-8")


def rpc(s, _id, method, params):
    send_obj(s, {"jsonrpc": "2.0", "id": _id, "method": method, "params": params})
    return json.loads(recv_line(s))


def assert_result(r):
    if "error" in r:
        raise AssertionError(f"Expected result, got error: {r!r}")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(65536)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("port", type=int)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    s = socket.create_connection(("127.0.0.1", args.port), timeout=5)

    _id = 1
    r = rpc(s, _id, "layout.new", {"top_cell": "TOP", "dbu": 0.001, "clear_previous": True})
    assert_result(r)
    _id += 1

    r = rpc(s, _id, "layer.new", {"layer": 1, "datatype": 0, "as_current": True})
    assert_result(r)
    li = r["result"]["layer_index"]
    _id += 1

    # Create child cell and put geometry in it.
    r = rpc(s, _id, "cell.create", {"name": "CHILD"})
    assert_result(r)
    _id += 1

    r = rpc(
        s,
        _id,
        "shape.create",
        {
            "cell": "CHILD",
            "type": "box",
            "coords": [0, 0, 10_000, 6_000],
            "units": "dbu",
            "layer_index": li,
        },
    )
    assert_result(r)
    _id += 1

    # Place child into TOP.
    r = rpc(s, _id, "instance.create", {"cell": "TOP", "child_cell": "CHILD", "trans": {"x": 0, "y": 0, "rot": 0, "mirror": False}})
    assert_result(r)
    _id += 1

    # Ensure GUI view exists and shows layout.
    r = rpc(s, _id, "view.ensure", {"zoom_fit": True})
    if "error" in r:
        if r["error"].get("data", {}).get("type") in ("MainWindowUnavailable", "NoCurrentView"):
            print("SKIP (no GUI view):", r["error"].get("message"))
            return 0
        raise AssertionError(f"view.ensure failed: {r!r}")
    _id += 1

    out_a = "test_out_req7_hier_levels_max0.png"
    out_b = "test_out_req7_hier_levels_max.png"
    for p in (out_a, out_b):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass

    # A) set max hier levels = 0
    r = rpc(s, _id, "view.set_hier_levels", {"mode": "set", "min_level": 0, "max_level": 0})
    assert_result(r)
    _id += 1

    r = rpc(
        s,
        _id,
        "view.screenshot",
        {
            "path": out_a,
            "width": 640,
            "height": 480,
            "viewport_mode": "center_size",
            "units": "dbu",
            "center": [5000, 3000],
            "size": [20000, 20000],
            "overwrite": True,
        },
    )
    assert_result(r)
    _id += 1

    # B) show all
    r = rpc(s, _id, "view.set_hier_levels", {"mode": "max"})
    assert_result(r)
    _id += 1

    r = rpc(
        s,
        _id,
        "view.screenshot",
        {
            "path": out_b,
            "width": 640,
            "height": 480,
            "viewport_mode": "center_size",
            "units": "dbu",
            "center": [5000, 3000],
            "size": [20000, 20000],
            "overwrite": True,
        },
    )
    assert_result(r)

    time.sleep(0.2)

    for p in (out_a, out_b):
        if not os.path.exists(p):
            raise AssertionError(f"Expected output file: {p}")
        if os.path.getsize(p) < 200:
            raise AssertionError(f"Output file too small: {p}")

    ha = sha256_file(out_a)
    hb = sha256_file(out_b)

    if args.verbose:
        print("A:", out_a, os.path.getsize(out_a), ha)
        print("B:", out_b, os.path.getsize(out_b), hb)

    if ha == hb:
        raise AssertionError("Expected different images for max_level=0 vs max; but hashes match")

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
