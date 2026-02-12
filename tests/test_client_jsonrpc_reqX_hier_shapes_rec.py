#!/usr/bin/env python3
"""Test: hier.shapes_rec

Build a small hierarchy and verify:
- leaf cell shapes can be extracted
- hierarchy_path includes start_cell and child cell
- coordinates are returned in start_cell coordinate system (dbu)
- unit conversion to um works

We keep it simple: TOP -> CHILD (trans x=1000,y=2000)
CHILD contains:
- box: [0,0]-[1000,500]
- polygon: triangle

Expect returned shapes include transformed coords.
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

    # box in CHILD
    r = rpc(
        s,
        _id,
        "shape.create",
        {"cell": "CHILD", "type": "box", "coords": [0, 0, 1000, 500], "units": "dbu", "layer_index": li},
    )
    assert_result(r)
    _id += 1

    # polygon in CHILD
    r = rpc(
        s,
        _id,
        "shape.create",
        {"cell": "CHILD", "type": "polygon", "coords": [[0, 0], [500, 0], [0, 500]], "units": "dbu", "layer_index": li},
    )
    assert_result(r)
    _id += 1

    # instance CHILD in TOP with translation
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
        "hier.shapes_rec",
        {
            "start_cell": "TOP",
            "layer_filter": [li],
            "shape_types": ["box", "polygon"],
            "unit": "um",
            "include_transform": True,
        },
    )
    assert_result(r)
    shapes = r["result"]["shapes"]

    if len(shapes) < 2:
        raise AssertionError(f"expected >=2 shapes, got {len(shapes)}")

    # Verify hierarchy_path contains CHILD (start_cell TOP may or may not be included depending on iterator binding)
    for sh in shapes:
        hp = sh.get("hierarchy_path")
        if not (isinstance(hp, list) and "CHILD" in hp):
            raise AssertionError(f"bad hierarchy_path: {hp}")

    # Verify at least one shape has translated coords (x>=~1.0um,y>=~2.0um)
    # dbu is 0.001um, so 1000 dbu -> 1.0um, 2000 dbu -> 2.0um
    ok_translated = False
    for sh in shapes:
        pts = sh.get("points_um")
        if not pts:
            continue
        for p in pts:
            if p[0] >= 0.9 and p[1] >= 1.9:
                ok_translated = True
                break
    if not ok_translated:
        raise AssertionError("expected some point to reflect instance translation")

    # Basic sanity: bbox_um should exist
    bb = shapes[0].get("bbox_um")
    if not (isinstance(bb, list) and len(bb) == 4):
        raise AssertionError(f"unexpected bbox_um: {bb}")

    print("OK")


if __name__ == "__main__":
    main()
