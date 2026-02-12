#!/usr/bin/env python3
"""Integration smoke test for JSON-RPC spec v0.

Usage:
  python3 /home/istale/.openclaw/workspace/klayout_skill_test/test_client_jsonrpc_spec_v0.py <port>

This test expects the server to implement:
- layout.new
- layer.new
- shape.create (box)
- layout.export

And enforce:
- cell not found -> JSON-RPC error -32002 with concrete reason
- export path escape -> error -32010 with concrete reason
- overwrite=false when file exists -> error -32011

NOTE: This is a simple script test (no pytest) to keep deps minimal.
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
    if verbose:
        print("<<<", raw.decode("utf-8", errors="replace").rstrip("\n"))
    if not raw.endswith(b"\n"):
        raise AssertionError(f"Response not newline-terminated: {raw!r}")
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise AssertionError(f"Response not valid JSON: {e}: {raw!r}")


def assert_is_error(resp: dict, code: int, contains: str | None = None):
    if "error" not in resp:
        raise AssertionError(f"Expected error response, got: {resp!r}")
    err = resp["error"]
    if err.get("code") != code:
        raise AssertionError(f"Expected error.code={code}, got {err!r}")
    msg = err.get("message", "")
    if contains is not None and contains not in msg:
        raise AssertionError(f"Expected error.message to contain {contains!r}, got {msg!r}")


def assert_is_result(resp: dict):
    if "result" not in resp:
        raise AssertionError(f"Expected result response, got: {resp!r}")


def main() -> int:
    verbose = False
    args = list(sys.argv[1:])
    if "--verbose" in args:
        verbose = True
        args.remove("--verbose")

    if len(args) != 1:
        print("usage: test_client_jsonrpc_spec_v0.py [--verbose] <port>", file=sys.stderr)
        return 2

    port = int(args[0])

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3.0)
    s.connect(("127.0.0.1", port))

    # T2: layout.new
    r1 = rpc(s, 1, "layout.new", {}, verbose)
    assert_is_result(r1)
    if r1["result"].get("dbu") != 0.0005:
        raise AssertionError(f"Expected dbu=0.0005, got {r1!r}")

    # T3: layer.new (default 1/0)
    r2 = rpc(s, 2, "layer.new", {}, verbose)
    assert_is_result(r2)
    li = r2["result"].get("layer_index")
    if not isinstance(li, int):
        raise AssertionError(f"Expected integer layer_index, got {r2!r}")

    # T4: shape.create box in TOP using current layer
    r3 = rpc(
        s,
        3,
        "shape.create",
        {"cell": "TOP", "type": "box", "coords": [0, 0, 1000, 1000], "units": "dbu"},
        verbose,
    )
    assert_is_result(r3)
    if r3["result"].get("inserted") is not True:
        raise AssertionError(f"Expected inserted=true, got {r3!r}")

    # Cell not found -> -32002 with concrete reason
    r4 = rpc(
        s,
        4,
        "shape.create",
        {"cell": "NO_SUCH", "type": "box", "coords": [0, 0, 10, 10], "units": "dbu"},
        verbose,
    )
    assert_is_error(r4, -32002, "Cell not found")

    # T5: export path escape -> -32010
    r5 = rpc(s, 5, "layout.export", {"path": "../out.gds", "overwrite": True}, verbose)
    assert_is_error(r5, -32010, "Path not allowed")

    # export ok under cwd
    out_name = "test_out.gds"
    try:
        os.remove(out_name)
    except FileNotFoundError:
        pass

    r6 = rpc(s, 6, "layout.export", {"path": out_name, "overwrite": True}, verbose)
    assert_is_result(r6)
    if r6["result"].get("written") is not True:
        raise AssertionError(f"Expected written=true, got {r6!r}")

    if not os.path.exists(out_name):
        raise AssertionError(f"Expected file to exist after export: {out_name}")

    # export overwrite=false when exists -> -32011
    r7 = rpc(s, 7, "layout.export", {"path": out_name, "overwrite": False}, verbose)
    assert_is_error(r7, -32011, "overwrite=false")

    s.close()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
