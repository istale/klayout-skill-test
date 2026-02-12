#!/usr/bin/env python3
"""Minimal JSON-RPC/TCP client for klayout_gui_tcp_server.py.

Protocol:
- TCP
- newline-delimited JSON (request per line, response per line)

This script is intentionally tiny so an agent (or human) can follow SKILL.md
without relying on repo test programs.

Examples:
  python klayout-python/scripts/jsonrpc_client.py ping --port 5055

  python klayout-python/scripts/jsonrpc_client.py layout.new --params '{"dbu":0.001,"top_cell":"TOP","clear_previous":true}' --port 5055

  python klayout-python/scripts/jsonrpc_client.py layout.export --params '{"path":"out.gds","overwrite":true}' --port 5055
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from typing import Any, Dict, Tuple


def _json_loads(s: str) -> Any:
    return json.loads(s)


def _recv_line(sock: socket.socket, timeout_s: float) -> str:
    sock.settimeout(timeout_s)
    buf = b""
    while True:
        b = sock.recv(1)
        if not b:
            raise ConnectionError("socket closed")
        if b == b"\n":
            return buf.decode("utf-8", errors="replace")
        buf += b


def call_jsonrpc(
    host: str,
    port: int,
    method: str,
    params: Dict[str, Any] | None,
    request_id: int = 1,
    connect_timeout_s: float = 3.0,
    read_timeout_s: float = 30.0,
    retries: int = 30,
    retry_sleep_s: float = 0.2,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return (request_obj, response_obj)."""

    req: Dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        req["params"] = params

    last_err: Exception | None = None
    for _ in range(max(1, retries)):
        try:
            with socket.create_connection((host, port), timeout=connect_timeout_s) as sock:
                line = (json.dumps(req, separators=(",", ":")) + "\n").encode("utf-8")
                sock.sendall(line)
                resp_line = _recv_line(sock, timeout_s=read_timeout_s)
                resp = _json_loads(resp_line)
                if not isinstance(resp, dict):
                    raise ValueError(f"response is not an object: {type(resp).__name__}")
                return req, resp
        except Exception as e:
            last_err = e
            time.sleep(retry_sleep_s)

    raise RuntimeError(f"failed to call {method} after retries: {last_err}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("method", help="JSON-RPC method, e.g. ping / layout.new / view.ensure")
    ap.add_argument("--params", default=None, help="JSON object string for params")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--id", type=int, default=1)
    ap.add_argument("--connect-timeout", type=float, default=3.0)
    ap.add_argument("--read-timeout", type=float, default=30.0)
    ap.add_argument("--retries", type=int, default=30)
    ap.add_argument("--retry-sleep", type=float, default=0.2)
    args = ap.parse_args()

    params = None
    if args.params is not None:
        try:
            params = _json_loads(args.params)
        except Exception as e:
            print(f"Invalid --params JSON: {e}", file=sys.stderr)
            return 2
        if not isinstance(params, dict):
            print("--params must be a JSON object", file=sys.stderr)
            return 2

    req, resp = call_jsonrpc(
        host=args.host,
        port=args.port,
        method=args.method,
        params=params,
        request_id=args.id,
        connect_timeout_s=args.connect_timeout,
        read_timeout_s=args.read_timeout,
        retries=args.retries,
        retry_sleep_s=args.retry_sleep,
    )

    print(json.dumps({"request": req, "response": resp}, ensure_ascii=False, indent=2))

    # exit code: 0 if result present, 1 if error present
    if "error" in resp:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
