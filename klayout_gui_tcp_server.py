"""KLayout Python macro: minimal TCP server (localhost) to validate request/response.

Goal (需求1 / TDD step 1):
- Start a TCP server inside KLayout's event loop.
- Accept one client connection.
- For each line-based request, respond.

Protocol (v0):
- Client sends:  ping\n
- Server replies: pong\n
Notes:
- Server binds to localhost only (127.0.0.1).
- Single-client only: extra connections are rejected.
- Keep global references so Qt objects won't be GC'd.
- Intended run modes:
  - GUI: run from Macro IDE
  - Headless: /home/istale/klayout-build/0.30.5-qt5/klayout -e -rm <this_file>
"""

import os
import pya

# Keep globals to prevent garbage collection of Qt objects/callbacks
_SERVER = None
_CLIENT = None          # QTcpSocket (single client)
_CLIENT_STATE = None    # _ClientState (single client)


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
    """Handle a single request line (without trailing \n)."""
    cmd = line_bytes.decode("utf-8", errors="replace").strip()

    if cmd == "ping":
        sock.write(b"pong\n")
        return

    sock.write(("err unknown_command: %s\n" % cmd).encode("utf-8"))


def _on_client_ready_read(state):
    sock = state.sock

    data = _bytes_to_py(sock.readAll())
    if not data:
        return

    state.buf += data

    while b"\n" in state.buf:
        line, state.buf = state.buf.split(b"\n", 1)
        _handle_line(sock, line)


def _on_client_disconnected(sock):
    global _CLIENT, _CLIENT_STATE
    if sock is _CLIENT:
        _CLIENT = None
        _CLIENT_STATE = None


def _on_new_connection():
    global _SERVER, _CLIENT, _CLIENT_STATE

    # Single-client policy: accept only the first active client.
    while _SERVER.hasPendingConnections():
        sock = _SERVER.nextPendingConnection()

        if _CLIENT is not None:
            # Reject additional clients.
            try:
                sock.close()
            except Exception:
                try:
                    sock.disconnectFromHost()
                except Exception:
                    pass
            continue

        _CLIENT = sock
        _CLIENT_STATE = _ClientState(sock)

        # Bind signals (KLayout Qt binding exposes signals as assignable attributes)
        sock.readyRead = lambda st=_CLIENT_STATE: _on_client_ready_read(st)
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

    app = pya.Application.instance()
    mw = None
    try:
        mw = app.main_window()
    except Exception:
        mw = None

    # Parent to main window in GUI; otherwise parent to app instance (headless)
    _SERVER = pya.QTcpServer(mw if mw is not None else app)

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
    if mw is not None:
        try:
            mw.message(msg)
        except Exception:
            pass

    return actual_port


def stop_server():
    global _SERVER, _CLIENT, _CLIENT_STATE
    if _SERVER is None:
        return
    try:
        _SERVER.close()
    except Exception:
        pass
    _SERVER = None
    _CLIENT = None
    _CLIENT_STATE = None
    print("[klayout-gui-server] stopped")


# Auto-start when macro runs
_env_port = int(os.environ.get("KLAYOUT_SERVER_PORT", "0"))
PORT = start_server(_env_port)
print("[klayout-gui-server] PORT=", PORT, flush=True)
