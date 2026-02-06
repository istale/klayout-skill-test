#!/usr/bin/env python3
"""Req7: view.set_viewport

This is a minimal integration test.
In no-GUI/no-current-view situations it will SKIP.
"""

import socket
import json


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

    r = rpc(
        s,
        _id,
        "view.set_viewport",
        {
            "viewport_mode": "center_size",
            "units": "dbu",
            "center": [0, 0],
            "size": [20000, 20000],
        },
    )

    if "error" in r:
        if r["error"].get("data", {}).get("type") in ("MainWindowUnavailable", "NoCurrentView"):
            print("SKIP (no GUI view):", r["error"].get("message"))
            return 0
        raise AssertionError(f"set_viewport failed: {r!r}")

    assert_result(r)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
