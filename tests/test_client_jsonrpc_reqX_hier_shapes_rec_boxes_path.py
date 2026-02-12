#!/usr/bin/env python3
"""Test: hier.shapes_rec_boxes with Manhattan path

- TOP -> CHILD (translation x=1000,y=2000)
- CHILD contains a Manhattan path from (0,0) to (0,1000) with width=200

Expected filled area is a rectangle of width 200 and height 1000.
We check returned boxes total area equals 200*1000.
"""

import json
import socket


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


def area_bbox(bb):
    x1, y1, x2, y2 = bb
    return max(0, x2 - x1) * max(0, y2 - y1)


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("port", type=int)
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

    r = rpc(s, _id, "cell.create", {"name": "CHILD"})
    assert_result(r)
    _id += 1

    r = rpc(
        s,
        _id,
        "shape.create",
        {
            "cell": "CHILD",
            "type": "path",
            "coords": [[0, 0], [0, 1000]],
            "width": 200,
            "units": "dbu",
            "layer_index": li,
        },
    )
    assert_result(r)
    _id += 1

    r = rpc(
        s,
        _id,
        "instance.create",
        {"cell": "TOP", "child_cell": "CHILD", "trans": {"x": 1000, "y": 2000, "rot": 0, "mirror": False}},
    )
    assert_result(r)
    _id += 1

    r = rpc(
        s,
        _id,
        "hier.shapes_rec_boxes",
        {"start_cell": "TOP", "layer_filter": [li], "shape_types": ["path"], "unit": "dbu"},
    )
    assert_result(r)

    boxes = r["result"].get("boxes")
    if not isinstance(boxes, list) or not boxes:
        raise AssertionError("expected non-empty boxes")

    total = 0
    for b in boxes:
        bb = b.get("bbox")
        total += area_bbox(bb)

    if total != 200 * 1000:
        raise AssertionError(f"area mismatch: got {total}, expected {200*1000}")

    print("OK")


if __name__ == "__main__":
    main()
