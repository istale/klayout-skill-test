#!/usr/bin/env python3
"""Client test for klayout_gui_tcp_server.py

Usage:
  python3 test_client_ping.py <port>

Expected:
  - Connects to 127.0.0.1:<port>
  - Sends 'ping\n'
  - Receives 'pong\n'
  - Exits 0 on success
"""

import socket
import sys


def main():
    if len(sys.argv) != 2:
        print("usage: test_client_ping.py <port>", file=sys.stderr)
        return 2

    port = int(sys.argv[1])

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.0)
    s.connect(("127.0.0.1", port))

    s.sendall(b"ping\n")

    data = b""
    while not data.endswith(b"\n"):
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk

    s.close()

    if data != b"pong\n":
        print("FAIL: expected 'pong\\n', got %r" % data, file=sys.stderr)
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
