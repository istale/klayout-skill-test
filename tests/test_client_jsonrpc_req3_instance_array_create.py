#!/usr/bin/env python3
"""T3-3 integration test: instance_array.create (需求3).

Usage:
  python3 /home/istale/.openclaw/workspace/klayout_skill_test/test_client_jsonrpc_req3_instance_array_create.py [--verbose] <port>

Assumes fresh server state (or restart server) so first call can verify
"No active layout" error behavior.

Covers:
1) instance_array.create without layout.new -> error (message + data.type)
2) layout.new then missing child -> error
3) cell.create CHILD then instance_array.create -> success
4) invalid nx -> error
"""

import json
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


def assert_error(resp: dict, msg_contains: str, type_is: str):
    if "error" not in resp:
        raise AssertionError(f"Expected error, got {resp!r}")
    err = resp["error"]
    msg = err.get("message", "")
    if msg_contains not in msg:
        raise AssertionError(f"Expected error.message to contain {msg_contains!r}, got {msg!r}")
    data = err.get("data")
    if not isinstance(data, dict):
        raise AssertionError(f"Expected error.data object, got {err!r}")
    if data.get("type") != type_is:
        raise AssertionError(f"Expected error.data.type={type_is!r}, got {data!r}")


def assert_result(resp: dict):
    if "result" not in resp:
        raise AssertionError(f"Expected result, got {resp!r}")


def main() -> int:
    verbose = False
    args = list(sys.argv[1:])
    if "--verbose" in args:
        verbose = True
        args.remove("--verbose")

    if len(args) != 1:
        print("usage: test_client_jsonrpc_req3_instance_array_create.py [--verbose] <port>", file=sys.stderr)
        return 2

    port = int(args[0])

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3.0)
    s.connect(("127.0.0.1", port))

    params = {
        "cell": "TOP",
        "child_cell": "CHILD",
        "trans": {"x": 0, "y": 0, "rot": 0, "mirror": False},
        "array": {"nx": 2, "ny": 3, "dx": 1000, "dy": 2000},
    }

    # 1) No active layout
    r1 = rpc(s, 1, "instance_array.create", params, verbose)
    assert_error(r1, "No active layout", "NoActiveLayout")

    # 2) Create layout, but child doesn't exist
    r2 = rpc(s, 2, "layout.new", {}, verbose)
    assert_result(r2)

    r3 = rpc(s, 3, "instance_array.create", params, verbose)
    assert_error(r3, "Child cell not found", "ChildCellNotFound")

    # 3) Create child, then instance_array.create succeeds
    r4 = rpc(s, 4, "cell.create", {"name": "CHILD"}, verbose)
    assert_result(r4)

    r5 = rpc(s, 5, "instance_array.create", params, verbose)
    assert_result(r5)
    if r5["result"].get("inserted") is not True:
        raise AssertionError(f"Unexpected result for instance_array.create: {r5!r}")

    # 4) Invalid nx
    bad = dict(params)
    bad["array"] = {"nx": 0, "ny": 1, "dx": 1000, "dy": 1000}
    r6 = rpc(s, 6, "instance_array.create", bad, verbose)
    assert_error(r6, "nx must be", "InvalidParams")

    s.close()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
