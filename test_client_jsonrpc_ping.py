#!/usr/bin/env python3
"""JSON-RPC client smoke test for KLayout TCP server.

Usage:
  python3 /home/istale/.openclaw/workspace/klayout_skill_test/test_client_jsonrpc_ping.py <port>

Sends:
  {"jsonrpc":"2.0","id":1,"method":"ping","params":{}}

Expects:
  {"jsonrpc":"2.0","id":1,"result":{"pong":true}}
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


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_client_jsonrpc_ping.py <port>", file=sys.stderr)
        return 2

    port = int(sys.argv[1])

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.0)
    s.connect(("127.0.0.1", port))

    req = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
    s.sendall((json.dumps(req) + "\n").encode("utf-8"))

    raw = recv_line(s)
    s.close()

    if not raw.endswith(b"\n"):
        print(f"FAIL: expected newline-terminated response, got {raw!r}", file=sys.stderr)
        return 1

    try:
        resp = json.loads(raw.decode("utf-8"))
    except Exception as e:
        print(f"FAIL: response is not valid JSON: {e}: {raw!r}", file=sys.stderr)
        return 1

    expected = {"jsonrpc": "2.0", "id": 1, "result": {"pong": True}}
    if resp != expected:
        print(f"FAIL: expected {expected!r}, got {resp!r}", file=sys.stderr)
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
