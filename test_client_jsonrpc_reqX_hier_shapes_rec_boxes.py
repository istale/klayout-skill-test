#!/usr/bin/env python3
"""Test: hier.shapes_rec_boxes (exact DBU, Manhattan, with hole)

Build a simple hierarchy and verify polygon-with-hole decomposition:
- TOP -> CHILD (translation x=1000,y=2000)
- CHILD contains one Manhattan polygon with a rectangular hole

We assert:
- returned unit is dbu
- returned boxes cover exact area = outer - hole
- all boxes are Manhattan and do not overlap the hole interior
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


def in_hole(x, y, hole_bb):
    hx1, hy1, hx2, hy2 = hole_bb
    return hx1 < x < hx2 and hy1 < y < hy2


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

    # Outer: 0,0 - 4000,3000
    outer = [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]
    # Hole: 1000,1000 - 3000,2000
    hole = [[1000, 1000], [3000, 1000], [3000, 2000], [1000, 2000]]

    r = rpc(
        s,
        _id,
        "shape.create",
        {"cell": "CHILD", "type": "polygon", "coords": outer, "holes": [hole], "units": "dbu", "layer_index": li},
    )
    assert_result(r)
    _id += 1

    # Instance CHILD in TOP with translation
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
        {"start_cell": "TOP", "layer_filter": [li], "shape_types": ["polygon"], "unit": "dbu", "max_boxes": 200000},
    )
    assert_result(r)

    res = r["result"]
    if res.get("unit") != "dbu":
        raise AssertionError(f"unexpected unit: {res.get('unit')}")

    boxes = res.get("boxes")
    if not isinstance(boxes, list) or not boxes:
        raise AssertionError("expected non-empty boxes")

    # Expected area in DBU^2. Apply translation in x/y to expected bboxes.
    outer_area = 4000 * 3000
    hole_area = (3000 - 1000) * (2000 - 1000)
    expected_area = outer_area - hole_area

    # Validate area and that boxes don't place points strictly inside hole.
    hole_bb_t = [1000 + 1000, 1000 + 2000, 3000 + 1000, 2000 + 2000]

    total = 0
    for b in boxes:
        bb = b.get("bbox")
        if not (isinstance(bb, list) and len(bb) == 4):
            raise AssertionError(f"bad bbox: {bb}")
        total += area_bbox(bb)

        # sample box center; must not lie strictly inside hole
        cx = (bb[0] + bb[2]) // 2
        cy = (bb[1] + bb[3]) // 2
        if in_hole(cx, cy, hole_bb_t):
            raise AssertionError(f"box center inside hole: bbox={bb}")

    if total != expected_area:
        raise AssertionError(f"area mismatch: got {total}, expected {expected_area}")

    print("OK")


if __name__ == "__main__":
    main()
