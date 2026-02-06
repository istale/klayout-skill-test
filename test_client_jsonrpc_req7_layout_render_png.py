#!/usr/bin/env python3
"""Req7: headless-friendly screenshot via layout.render_png.

This should work even when no GUI current_view exists.
"""

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

    r = rpc(
        s,
        _id,
        "shape.create",
        {"cell": "TOP", "type": "box", "coords": [0, 0, 10_000, 6_000], "units": "dbu", "layer_index": li},
    )
    assert_result(r)
    _id += 1

    out_rel = "test_out_req7_layout_render_png.png"
    try:
        os.remove(out_rel)
    except FileNotFoundError:
        pass

    r = rpc(
        s,
        _id,
        "layout.render_png",
        {
            "path": out_rel,
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

    if args.verbose:
        print("render_png result:", r)

    time.sleep(0.2)

    if not os.path.exists(out_rel):
        raise AssertionError(f"Expected output file: {out_rel}")

    if os.path.getsize(out_rel) < 100:
        raise AssertionError(f"Output file too small: {out_rel}")

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
