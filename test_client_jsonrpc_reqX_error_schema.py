#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test: JSON-RPC error.data schema includes {type, details}.

We intentionally send an invalid request and assert:
- response.error.data.type exists
- response.error.data.details exists (may be object or null)
- legacy flattened fields are NOT required
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


def rpc_raw(sock, _id, method, params=None):
    req = {"jsonrpc": "2.0", "id": _id, "method": method, "params": params or {}}
    sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
    return json.loads(recv_line(sock))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", type=int)
    args = ap.parse_args()

    s = socket.create_connection(("127.0.0.1", args.port), timeout=5)
    s.settimeout(5)

    # Fresh layout
    r = rpc_raw(s, 1, "layout.new", {"dbu": 0.001, "top_cell": "TOP", "clear_previous": True})
    if "error" in r:
        raise AssertionError(f"layout.new failed unexpectedly: {r}")

    # Make a deterministic invalid params error: coords must be list; pass string.
    r = rpc_raw(
        s,
        2,
        "shape.create",
        {"cell": "TOP", "type": "box", "coords": "not-a-list"},
    )

    if "error" not in r:
        raise AssertionError(f"expected error, got result: {r}")

    err = r["error"]
    data = err.get("data")
    if not isinstance(data, dict):
        raise AssertionError(f"expected error.data dict, got {data!r}")

    if not isinstance(data.get("type"), str) or not data.get("type"):
        raise AssertionError(f"expected error.data.type string, got {data.get('type')!r}")

    # details should exist (object or null)
    if "details" not in data:
        raise AssertionError(f"expected error.data.details field, got keys={list(data.keys())}")

    # and must be dict or None
    if not (data["details"] is None or isinstance(data["details"], dict)):
        raise AssertionError(f"expected error.data.details dict|null, got {type(data['details'])}")

    print("OK")


if __name__ == "__main__":
    main()
