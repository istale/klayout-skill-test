#!/usr/bin/env python3
"""T3-1 integration test: cell.create (需求3).

Usage:
  python3 /home/istale/.openclaw/workspace/klayout_skill_test/test_client_jsonrpc_req3_cell_create.py <port>

Covers:
1) cell.create without layout.new -> error.message + error.data.type
2) layout.new then cell.create -> success
3) cell.create same name again -> error.message + error.data.type

Error style requirement (需求3+):
- error.code may be present but is NOT used for classification
- error.message must contain the concrete reason
- error.data.type must be present
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
        print("usage: test_client_jsonrpc_req3_cell_create.py [--verbose] <port>", file=sys.stderr)
        return 2

    port = int(args[0])

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3.0)
    s.connect(("127.0.0.1", port))

    # 1) No active layout
    r1 = rpc(s, 1, "cell.create", {"name": "CHILD"}, verbose)
    assert_error(r1, "No active layout", "NoActiveLayout")

    # 2) Create layout then create cell
    r2 = rpc(s, 2, "layout.new", {}, verbose)
    assert_result(r2)

    r3 = rpc(s, 3, "cell.create", {"name": "CHILD"}, verbose)
    assert_result(r3)
    if r3["result"].get("created") is not True or r3["result"].get("name") != "CHILD":
        raise AssertionError(f"Unexpected result for cell.create: {r3!r}")

    # 3) Create same cell again -> error
    r4 = rpc(s, 4, "cell.create", {"name": "CHILD"}, verbose)
    assert_error(r4, "Cell already exists: CHILD", "CellAlreadyExists")

    s.close()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
