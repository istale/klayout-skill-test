"""KLayout Python macro: TCP server (localhost) using JSON-RPC 2.0.

Transport:
- newline-delimited JSON (one JSON-RPC request per line)
- newline-delimited JSON (one response per line)

Single-client only.

Headless run (pinned):
- /home/istale/klayout-build/0.30.5-qt5/klayout -e -rm <this_file>

Spec: see README.md (需求2 spec v0)
"""

import json
import os
import pya

# --- Globals (keep references to prevent GC) ---
_SERVER = None
_CLIENT = None          # QTcpSocket (single client)
_CLIENT_STATE = None    # _ClientState (single client)

# Server start directory (for path restrictions)
_SERVER_CWD = os.getcwd()
_SERVER_CWD_REAL = os.path.realpath(_SERVER_CWD)

# Server state for JSON-RPC methods (需求2)
_STATE = {
    "layout": None,               # pya.Layout
    "layout_id": None,            # string
    "top_cell": None,             # pya.Cell
    "top_cell_name": None,        # string
    "current_layer_index": None,  # int
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


def _require_active_layout(_id):
    if _STATE.get("layout") is None:
        return _jsonrpc_error(_id, -32001, "No active layout: call layout.new first")
    return None


def _layer_index_from_params(layout, params, _id):
    """Resolve layer index per spec.

    Priority:
    1) layer_index
    2) layer object
    3) current layer
    """
    if "layer_index" in params and params["layer_index"] is not None:
        li = params["layer_index"]
        if not isinstance(li, int):
            return None, _jsonrpc_error(_id, -32602, f"Invalid params: layer_index must be int, got {type(li).__name__}")
        return li, None

    layer_obj = params.get("layer", None)
    if layer_obj is not None:
        if not isinstance(layer_obj, dict):
            return None, _jsonrpc_error(_id, -32602, "Invalid params: layer must be an object")
        ln = layer_obj.get("layer", 1)
        dt = layer_obj.get("datatype", 0)
        nm = layer_obj.get("name", None)
        if not isinstance(ln, int) or not isinstance(dt, int):
            return None, _jsonrpc_error(_id, -32602, "Invalid params: layer.layer and layer.datatype must be int")
        if nm is None:
            info = pya.LayerInfo(ln, dt)
        else:
            if not isinstance(nm, str):
                return None, _jsonrpc_error(_id, -32602, "Invalid params: layer.name must be string or null")
            info = pya.LayerInfo(ln, dt, nm)
        li = int(layout.layer(info))
        return li, None

    if _STATE.get("current_layer_index") is not None:
        return int(_STATE["current_layer_index"]), None

    return None, _jsonrpc_error(
        _id,
        -32003,
        "Layer not available: specify layer_index or layer, or call layer.new first to set current layer",
    )


def _resolve_export_path(_id, path):
    if not isinstance(path, str) or not path:
        return None, _jsonrpc_error(_id, -32602, "Invalid params: path must be a non-empty string")

    # Resolve against server cwd
    if os.path.isabs(path):
        full = path
    else:
        full = os.path.join(_SERVER_CWD, path)

    full_real = os.path.realpath(full)

    allowed_prefix = _SERVER_CWD_REAL + os.sep
    if not (full_real == _SERVER_CWD_REAL or full_real.startswith(allowed_prefix)):
        return None, _jsonrpc_error(_id, -32010, f"Path not allowed (escapes server cwd): {path}")

    # Return as given (relative preferred) and resolved absolute
    return (path, full_real), None


# --- Method handlers ---

def _m_ping(_id, params):
    return _jsonrpc_result(_id, {"pong": True})


def _m_layout_new(_id, params):
    if not isinstance(params, dict):
        return _jsonrpc_error(_id, -32602, "Invalid params: params must be an object")

    dbu = params.get("dbu", 0.0005)
    top_cell_name = params.get("top_cell", "TOP")
    clear_previous = params.get("clear_previous", True)

    if not isinstance(dbu, (int, float)):
        return _jsonrpc_error(_id, -32602, f"Invalid params: dbu must be number, got {type(dbu).__name__}")
    dbu = float(dbu)
    if dbu <= 0:
        return _jsonrpc_error(_id, -32602, "Invalid params: dbu must be > 0")

    if not isinstance(top_cell_name, str) or not top_cell_name:
        return _jsonrpc_error(_id, -32602, "Invalid params: top_cell must be a non-empty string")

    if not isinstance(clear_previous, bool):
        return _jsonrpc_error(_id, -32602, "Invalid params: clear_previous must be boolean")

    if _STATE.get("layout") is not None and not clear_previous:
        # Keep existing layout
        return _jsonrpc_result(
            _id,
            {"layout_id": _STATE.get("layout_id"), "dbu": float(_STATE["layout"].dbu), "top_cell": _STATE.get("top_cell_name")},
        )

    layout = pya.Layout()
    layout.dbu = dbu
    top_cell = layout.create_cell(top_cell_name)

    _STATE["layout"] = layout
    _STATE["layout_id"] = "L1"
    _STATE["top_cell"] = top_cell
    _STATE["top_cell_name"] = top_cell_name
    _STATE["current_layer_index"] = None

    return _jsonrpc_result(_id, {"layout_id": "L1", "dbu": dbu, "top_cell": top_cell_name})


def _m_layer_new(_id, params):
    err = _require_active_layout(_id)
    if err:
        return err

    if not isinstance(params, dict):
        return _jsonrpc_error(_id, -32602, "Invalid params: params must be an object")

    ln = params.get("layer", 1)
    dt = params.get("datatype", 0)
    nm = params.get("name", None)
    as_current = params.get("as_current", True)

    if not isinstance(ln, int) or not isinstance(dt, int):
        return _jsonrpc_error(_id, -32602, "Invalid params: layer and datatype must be int")
    if nm is not None and not isinstance(nm, str):
        return _jsonrpc_error(_id, -32602, "Invalid params: name must be string or null")
    if not isinstance(as_current, bool):
        return _jsonrpc_error(_id, -32602, "Invalid params: as_current must be boolean")

    layout = _STATE["layout"]

    if nm is None:
        info = pya.LayerInfo(ln, dt)
    else:
        info = pya.LayerInfo(ln, dt, nm)

    li = int(layout.layer(info))

    if as_current:
        _STATE["current_layer_index"] = li

    return _jsonrpc_result(_id, {"layer_index": li, "layer": ln, "datatype": dt, "name": nm})


def _m_shape_create(_id, params):
    err = _require_active_layout(_id)
    if err:
        return err

    if not isinstance(params, dict):
        return _jsonrpc_error(_id, -32602, "Invalid params: params must be an object")

    layout = _STATE["layout"]

    cell_name = params.get("cell", "TOP")
    if not isinstance(cell_name, str) or not cell_name:
        return _jsonrpc_error(_id, -32602, "Invalid params: cell must be a non-empty string")

    if not layout.has_cell(cell_name):
        return _jsonrpc_error(_id, -32002, f"Cell not found: {cell_name}")

    cell = layout.cell(cell_name)

    units = params.get("units", "dbu")
    if units != "dbu":
        return _jsonrpc_error(_id, -32602, f"Invalid params: units must be 'dbu' (got {units!r})")

    li, li_err = _layer_index_from_params(layout, params, _id)
    if li_err:
        return li_err

    shape_type = params.get("type", "box")
    coords = params.get("coords", None)

    if shape_type == "box":
        if not (isinstance(coords, list) and len(coords) == 4 and all(isinstance(v, int) for v in coords)):
            return _jsonrpc_error(_id, -32602, "Invalid params: box coords must be [x1,y1,x2,y2] (int DBU)")
        x1, y1, x2, y2 = coords
        box = pya.Box(x1, y1, x2, y2)
        cell.shapes(li).insert(box)
        return _jsonrpc_result(_id, {"inserted": True, "type": "box", "cell": cell_name, "layer_index": int(li)})

    if shape_type == "polygon":
        if not (isinstance(coords, list) and len(coords) >= 3):
            return _jsonrpc_error(_id, -32602, "Invalid params: polygon coords must be [[x,y],...] with >=3 points")
        pts = []
        for p in coords:
            if not (isinstance(p, list) and len(p) == 2 and isinstance(p[0], int) and isinstance(p[1], int)):
                return _jsonrpc_error(_id, -32602, "Invalid params: polygon point must be [x,y] (int DBU)")
            pts.append(pya.Point(p[0], p[1]))
        poly = pya.Polygon(pts)
        cell.shapes(li).insert(poly)
        return _jsonrpc_result(_id, {"inserted": True, "type": "polygon", "cell": cell_name, "layer_index": int(li)})

    return _jsonrpc_error(_id, -32602, f"Invalid params: unsupported shape type: {shape_type}")


def _m_layout_export(_id, params):
    err = _require_active_layout(_id)
    if err:
        return err

    if not isinstance(params, dict):
        return _jsonrpc_error(_id, -32602, "Invalid params: params must be an object")

    path = params.get("path", None)
    overwrite = params.get("overwrite", True)

    if not isinstance(overwrite, bool):
        return _jsonrpc_error(_id, -32602, "Invalid params: overwrite must be boolean")

    resolved, perr = _resolve_export_path(_id, path)
    if perr:
        return perr

    rel_path, full_real = resolved

    if os.path.exists(full_real) and not overwrite:
        return _jsonrpc_error(_id, -32011, f"File exists and overwrite=false: {rel_path}")

    try:
        _STATE["layout"].write(full_real)
    except Exception as e:
        return _jsonrpc_error(_id, -32099, f"Internal error during export: {e}")

    return _jsonrpc_result(_id, {"written": True, "path": rel_path})


_METHODS = {
    "ping": _m_ping,
    "layout.new": _m_layout_new,
    "layer.new": _m_layer_new,
    "shape.create": _m_shape_create,
    "layout.export": _m_layout_export,
}


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

    fn = _METHODS.get(method)
    if fn is None:
        return _jsonrpc_error(_id, -32601, f"Method not found: {method}")

    return fn(_id, params)


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
            # JSON parse error: provide concrete reason
            resp = _jsonrpc_error(None, -32700, f"Parse error: {e}")
            _send_obj(sock, resp)
            continue

        resp = _handle_request(req)

        # Notification: if id is omitted -> no response
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
