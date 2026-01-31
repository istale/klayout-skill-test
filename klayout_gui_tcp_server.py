"""KLayout Python macro: TCP server (localhost) using JSON-RPC 2.0.

This macro is the server for the project.

Transport:
- newline-delimited JSON (one JSON-RPC request per line)
- newline-delimited JSON (one response per line)

Single-client only.

Run modes:
- GUI: Macro IDE -> Python -> run this file
- Headless: /home/istale/klayout-build/0.30.5-qt5/klayout -e -rm <this_file>

"""

import json
import os
import pya

# --- Globals (keep references to prevent GC) ---
_SERVER = None
_CLIENT = None          # QTcpSocket (single client)
_CLIENT_STATE = None    # _ClientState (single client)

# Server state for JSON-RPC methods (需求2)
_STATE = {
    "layout": None,
    "top_cell": None,
    "top_cell_name": None,
    "current_layer_index": None,
}


def _bytes_to_py(b):
    """Best-effort convert KLayout Qt byte container to Python bytes."""
    try:
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


# --- JSON-RPC helpers ---

def _jsonrpc_error(_id, code, message, data=None):
    err = {"code": int(code), "message": str(message)}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": _id, "error": err}


def _jsonrpc_result(_id, result):
    return {"jsonrpc": "2.0", "id": _id, "result": result}


def _send_obj(sock, obj):
    line = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")
    sock.write(line)


def _handle_request(req):
    # Basic validation
    if not isinstance(req, dict):
        return _jsonrpc_error(None, -32600, "Invalid Request: request must be an object")

    if req.get("jsonrpc") != "2.0":
        return _jsonrpc_error(req.get("id", None), -32600, "Invalid Request: jsonrpc must be '2.0'")

    _id = req.get("id", None)
    method = req.get("method", None)
    params = req.get("params", {})

    if not isinstance(method, str) or not method:
        return _jsonrpc_error(_id, -32600, "Invalid Request: method must be a non-empty string")

    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _jsonrpc_error(_id, -32602, "Invalid params: params must be an object")

    # --- Methods (TDD T1) ---
    if method == "ping":
        return _jsonrpc_result(_id, {"pong": True})

    # Unknown
    return _jsonrpc_error(_id, -32601, f"Method not found: {method}")


def _on_client_ready_read(state):
    sock = state.sock

    data = _bytes_to_py(sock.readAll())
    if not data:
        return

    state.buf += data

    while b"\n" in state.buf:
        raw_line, state.buf = state.buf.split(b"\n", 1)
        if not raw_line.strip():
            continue

        try:
            req = json.loads(raw_line.decode("utf-8"))
        except Exception as e:
            # JSON parse error: provide a concrete reason
            resp = _jsonrpc_error(None, -32700, f"Parse error: {e}")
            _send_obj(sock, resp)
            continue

        resp = _handle_request(req)
        # Notification: id is omitted -> no response
        if isinstance(req, dict) and ("id" not in req):
            continue
        _send_obj(sock, resp)


def _on_client_disconnected(sock):
    global _CLIENT, _CLIENT_STATE
    if sock is _CLIENT:
        _CLIENT = None
        _CLIENT_STATE = None


def _on_new_connection():
    global _SERVER, _CLIENT, _CLIENT_STATE

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

    _SERVER = pya.QTcpServer(mw if mw is not None else app)
    _SERVER.newConnection = _on_new_connection

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


# Auto-start when macro runs
_env_port = int(os.environ.get("KLAYOUT_SERVER_PORT", "0"))
PORT = start_server(_env_port)
print("[klayout-gui-server] PORT=", PORT, flush=True)
