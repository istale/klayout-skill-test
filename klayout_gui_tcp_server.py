"""KLayout Python macro: minimal TCP server (localhost) to validate request/response.

Goal (需求1 / TDD step 1):
- Start a TCP server inside KLayout GUI event loop.
- Accept client connections.
- For each line-based request, respond.

Protocol (v0):
- Client sends:  ping\n
- Server replies: pong\n

How to run:
- In KLayout: Macro IDE -> Python -> load/run this file.
- Watch the Macro console for the chosen port.
- Run client: python3 test_client_ping.py <port>

Notes:
- Server binds to localhost only (127.0.0.1).
- We keep global references so objects won't be GC'd.
"""

import os
import pya

# Keep globals to prevent garbage collection of Qt objects/callbacks
_SERVER = None
_CLIENTS = []  # list[QTcpSocket]
_EXIT_TIMER = None


def _bytes_to_py(b):
    """Best-effort convert KLayout Qt byte container to Python bytes."""
    try:
        # QByteArray in KLayout often converts to Python bytes via bytes(...)
        return bytes(b)
    except Exception:
        try:
            return str(b).encode("utf-8", errors="replace")
        except Exception:
            return b""


class _ClientState:
    def __init__(self, sock):
        self.sock = sock
        self.buf = b""


def _handle_line(sock, line_bytes):
    # line_bytes includes no trailing \n
    cmd = line_bytes.decode("utf-8", errors="replace").strip()

    if cmd == "ping":
        sock.write(b"pong\n")
        return

    if cmd == "quit":
        sock.write(b"bye\n")
        sock.disconnectFromHost()
        return

    sock.write(("err unknown_command: %s\n" % cmd).encode("utf-8"))


def _on_client_ready_read(state):
    sock = state.sock

    # Read all available
    data = _bytes_to_py(sock.readAll())
    if not data:
        return

    state.buf += data

    while b"\n" in state.buf:
        line, state.buf = state.buf.split(b"\n", 1)
        _handle_line(sock, line)


def _on_client_disconnected(sock):
    global _CLIENTS
    _CLIENTS = [c for c in _CLIENTS if c is not sock]


def _on_new_connection():
    global _SERVER, _CLIENTS

    while _SERVER.hasPendingConnections():
        sock = _SERVER.nextPendingConnection()
        _CLIENTS.append(sock)

        state = _ClientState(sock)

        # Bind signals (KLayout Qt binding exposes signals as assignable attributes)
        sock.readyRead = lambda st=state: _on_client_ready_read(st)
        sock.disconnected = lambda s=sock: _on_client_disconnected(s)

        try:
            peer = "%s:%s" % (sock.peerAddress().toString(), sock.peerPort())
        except Exception:
            peer = "(peer unknown)"
        print("[klayout-gui-server] client connected", peer)


def start_server(port=0):
    """Start server. port=0 lets OS pick a free port."""
    global _SERVER

    if _SERVER is not None and _SERVER.isListening():
        print("[klayout-gui-server] already listening on", _SERVER.serverPort())
        return int(_SERVER.serverPort())

    # Parent to main window so lifetime is tied to GUI
    mw = pya.Application.instance().main_window()
    _SERVER = pya.QTcpServer(mw)

    # Bind signal
    _SERVER.newConnection = _on_new_connection

    # Note: listen() expects a QHostAddress object, not the SpecialAddress enum.
    addr = pya.QHostAddress.new_special(pya.QHostAddress.LocalHost)
    ok = _SERVER.listen(addr, int(port))
    if not ok:
        err = "unknown"
        try:
            err = _SERVER.errorString()
        except Exception:
            pass
        raise RuntimeError("QTcpServer.listen failed: %s" % err)

    actual_port = int(_SERVER.serverPort())

    msg = "[klayout-gui-server] listening on 127.0.0.1:%d" % actual_port
    print(msg)
    try:
        mw.message(msg)
    except Exception:
        pass

    return actual_port


def stop_server():
    global _SERVER, _CLIENTS
    if _SERVER is None:
        return
    try:
        _SERVER.close()
    except Exception:
        pass
    _SERVER = None
    _CLIENTS = []
    print("[klayout-gui-server] stopped")


def _schedule_exit(lifetime_ms: int):
    """Exit the application after lifetime_ms (for headless test runs)."""
    global _EXIT_TIMER

    if lifetime_ms <= 0:
        return

    _EXIT_TIMER = pya.QTimer(pya.Application.instance().main_window())
    _EXIT_TIMER.singleShot = True
    _EXIT_TIMER.timeout = lambda: pya.Application.instance().exit(0)
    _EXIT_TIMER.start(int(lifetime_ms))


# Auto-start when macro runs
_env_port = int(os.environ.get("KLAYOUT_SERVER_PORT", "0"))
_env_life = int(os.environ.get("KLAYOUT_SERVER_LIFETIME_MS", "0"))

PORT = start_server(_env_port)
print("[klayout-gui-server] PORT=", PORT, flush=True)
_schedule_exit(_env_life)
