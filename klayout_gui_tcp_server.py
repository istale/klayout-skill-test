"""KLayout Python macro: TCP server (localhost) using JSON-RPC 2.0.

Transport:
- newline-delimited JSON (one JSON-RPC request per line)
- newline-delimited JSON (one response per line)

Single-client only.

Headless run (pinned):
- /home/istale/klayout-build/0.30.5-qt5/klayout -e -rm <this_file>

Spec: see README.md (需求2 spec v0)

Refactor note:
- This file is organized into: transport -> JSON-RPC core -> method handlers.
- Behavior/spec should remain unchanged; use tests to validate.
"""

import json
import os
import pya

# -----------------------------------------------------------------------------
# Globals (keep references to prevent GC)
# -----------------------------------------------------------------------------

_SERVER = None
_CLIENT = None          # QTcpSocket (single client)
_CLIENT_STATE = None    # _ClientState (single client)

# Server start directory (for path restrictions)
_SERVER_CWD = os.getcwd()
_SERVER_CWD_REAL = os.path.realpath(_SERVER_CWD)


class SessionState:
    """Server-side session state (single client, single in-memory layout)."""

    def __init__(self):
        self.layout = None               # pya.Layout
        self.layout_id = None            # string (v0 uses "L1")
        self.top_cell = None             # pya.Cell
        self.top_cell_name = None        # string
        self.current_layer_index = None  # int


_STATE = SessionState()


# -----------------------------------------------------------------------------
# Transport helpers
# -----------------------------------------------------------------------------


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


def _send_obj(sock, obj):
    line = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")
    sock.write(line)


# -----------------------------------------------------------------------------
# JSON-RPC core
# -----------------------------------------------------------------------------


def _jsonrpc_error(_id, code, message, data=None):
    """Create a JSON-RPC 2.0 error object.

    NOTE: As of req3, all errors should carry a machine-readable type in
    error.data.type (even when we keep legacy error.code values).
    """
    err = {"code": int(code), "message": str(message)}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": _id, "error": err}


# From req3 onward, error classification is done via strings:
# - error.code is kept only to satisfy JSON-RPC 2.0 (legacy tests may still assert it)
# - error.message must contain the concrete reason
# - error.data.type provides a machine-readable error type

def _err(_id, code, message, etype, data=None):
    d = {"type": str(etype)}
    if isinstance(data, dict):
        d.update(data)
    return _jsonrpc_error(_id, code, message, d)


def _err_std(_id, code, message, etype, data=None):
    """Standard JSON-RPC errors (-326xx/-32700) but with req3-style type."""
    return _err(_id, code, message, etype, data)


def _jsonrpc_result(_id, result):
    return {"jsonrpc": "2.0", "id": _id, "result": result}


def _require_active_layout(_id):
    if _STATE.layout is None:
        return _err(_id, -32001, "No active layout: call layout.new first", "NoActiveLayout")
    return None


def _require_active_layout_str(_id):
    # Backwards-compatible alias used by req3 handlers.
    return _require_active_layout(_id)


def _ensure_params_object(_id, params):
    if params is None:
        return {}, None
    if not isinstance(params, dict):
        return None, _err_std(_id, -32602, "Invalid params: params must be an object", "InvalidParams")
    return params, None


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
            return None, _err_std(
                _id,
                -32602,
                f"Invalid params: layer_index must be int, got {type(li).__name__}",
                "InvalidParams",
                {"field": "layer_index"},
            )
        return li, None

    layer_obj = params.get("layer", None)
    if layer_obj is not None:
        if not isinstance(layer_obj, dict):
            return None, _err_std(_id, -32602, "Invalid params: layer must be an object", "InvalidParams", {"field": "layer"})

        ln = layer_obj.get("layer", 1)
        dt = layer_obj.get("datatype", 0)
        nm = layer_obj.get("name", None)

        if not isinstance(ln, int) or not isinstance(dt, int):
            return None, _err_std(
                _id,
                -32602,
                "Invalid params: layer.layer and layer.datatype must be int",
                "InvalidParams",
                {"field": "layer"},
            )

        if nm is None:
            info = pya.LayerInfo(ln, dt)
        else:
            if not isinstance(nm, str):
                return None, _err_std(
                    _id,
                    -32602,
                    "Invalid params: layer.name must be string or null",
                    "InvalidParams",
                    {"field": "layer.name"},
                )
            info = pya.LayerInfo(ln, dt, nm)

        li = int(layout.layer(info))
        return li, None

    if _STATE.current_layer_index is not None:
        return int(_STATE.current_layer_index), None

    return None, _err(
        _id,
        -32003,
        "Layer not available: specify layer_index or layer, or call layer.new first to set current layer",
        "LayerNotAvailable",
    )


def _resolve_cwd_path(_id, path):
    """Resolve a file path under server cwd.

    Accepts relative paths (interpreted relative to server cwd) and absolute
    paths (must still be within server cwd).

    Returns: ({"rel": <original>, "abs": <realpath>}, error)
    """
    if not isinstance(path, str) or not path:
        return None, _err_std(_id, -32602, "Invalid params: path must be a non-empty string", "InvalidParams", {"field": "path"})

    if os.path.isabs(path):
        full = path
    else:
        full = os.path.join(_SERVER_CWD, path)

    full_real = os.path.realpath(full)

    allowed_prefix = _SERVER_CWD_REAL + os.sep
    if not (full_real == _SERVER_CWD_REAL or full_real.startswith(allowed_prefix)):
        return None, _err(
            _id,
            -32010,
            f"Path not allowed (escapes server cwd): {path}",
            "PathNotAllowed",
            {"path": path},
        )

    return {"rel": path, "abs": full_real}, None


def _resolve_export_path(_id, path):
    # Backward-compatible alias.
    return _resolve_cwd_path(_id, path)


def _resolve_open_path(_id, path):
    # Same restrictions as export.
    return _resolve_cwd_path(_id, path)


# -----------------------------------------------------------------------------
# Method handlers (spec v0)
# -----------------------------------------------------------------------------


def _m_ping(_id, params):
    return _jsonrpc_result(_id, {"pong": True})


def _m_layout_new(_id, params):
    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    dbu = params.get("dbu", 0.0005)
    top_cell_name = params.get("top_cell", "TOP")
    clear_previous = params.get("clear_previous", True)

    if not isinstance(dbu, (int, float)):
        return _err_std(
            _id,
            -32602,
            f"Invalid params: dbu must be number, got {type(dbu).__name__}",
            "InvalidParams",
            {"field": "dbu"},
        )
    dbu = float(dbu)
    if dbu <= 0:
        return _err_std(_id, -32602, "Invalid params: dbu must be > 0", "InvalidParams", {"field": "dbu"})

    if not isinstance(top_cell_name, str) or not top_cell_name:
        return _err_std(
            _id,
            -32602,
            "Invalid params: top_cell must be a non-empty string",
            "InvalidParams",
            {"field": "top_cell"},
        )

    if not isinstance(clear_previous, bool):
        return _err_std(
            _id,
            -32602,
            "Invalid params: clear_previous must be boolean",
            "InvalidParams",
            {"field": "clear_previous"},
        )

    if _STATE.layout is not None and not clear_previous:
        return _jsonrpc_result(
            _id,
            {
                "layout_id": _STATE.layout_id,
                "dbu": float(_STATE.layout.dbu),
                "top_cell": _STATE.top_cell_name,
            },
        )

    layout = pya.Layout()
    layout.dbu = dbu
    top_cell = layout.create_cell(top_cell_name)

    _STATE.layout = layout
    _STATE.layout_id = "L1"
    _STATE.top_cell = top_cell
    _STATE.top_cell_name = top_cell_name
    _STATE.current_layer_index = None

    return _jsonrpc_result(_id, {"layout_id": "L1", "dbu": dbu, "top_cell": top_cell_name})


def _m_layer_new(_id, params):
    err = _require_active_layout(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    ln = params.get("layer", 1)
    dt = params.get("datatype", 0)
    nm = params.get("name", None)
    as_current = params.get("as_current", True)

    if not isinstance(ln, int) or not isinstance(dt, int):
        return _err_std(
            _id,
            -32602,
            "Invalid params: layer and datatype must be int",
            "InvalidParams",
            {"field": "layer"},
        )
    if nm is not None and not isinstance(nm, str):
        return _err_std(_id, -32602, "Invalid params: name must be string or null", "InvalidParams", {"field": "name"})
    if not isinstance(as_current, bool):
        return _err_std(
            _id,
            -32602,
            "Invalid params: as_current must be boolean",
            "InvalidParams",
            {"field": "as_current"},
        )

    if nm is None:
        info = pya.LayerInfo(ln, dt)
    else:
        info = pya.LayerInfo(ln, dt, nm)

    li = int(_STATE.layout.layer(info))

    if as_current:
        _STATE.current_layer_index = li

    return _jsonrpc_result(_id, {"layer_index": li, "layer": ln, "datatype": dt, "name": nm})


def _m_cell_create(_id, params):
    """需求3-1: create a cell.

    Error classification uses string message + error.data.type.
    """
    err = _require_active_layout_str(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        # For param-shape issues we keep legacy -32602 style.
        return perr

    name = params.get("name", None)
    if not isinstance(name, str) or not name:
        return _err(_id, -32000, "Invalid params: name must be a non-empty string", "InvalidParams", {"field": "name"})

    if _STATE.layout.has_cell(name):
        return _err(_id, -32000, f"Cell already exists: {name}", "CellAlreadyExists", {"name": name})

    _STATE.layout.create_cell(name)
    return _jsonrpc_result(_id, {"created": True, "name": name})


def _m_shape_create(_id, params):
    err = _require_active_layout(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    cell_name = params.get("cell", "TOP")
    if not isinstance(cell_name, str) or not cell_name:
        return _err_std(_id, -32602, "Invalid params: cell must be a non-empty string", "InvalidParams", {"field": "cell"})

    if not _STATE.layout.has_cell(cell_name):
        return _err(_id, -32002, f"Cell not found: {cell_name}", "CellNotFound", {"name": cell_name})

    cell = _STATE.layout.cell(cell_name)

    units = params.get("units", "dbu")
    if units != "dbu":
        return _err_std(
            _id,
            -32602,
            f"Invalid params: units must be 'dbu' (got {units!r})",
            "InvalidParams",
            {"field": "units"},
        )

    li, li_err = _layer_index_from_params(_STATE.layout, params, _id)
    if li_err:
        return li_err

    shape_type = params.get("type", "box")
    coords = params.get("coords", None)

    if shape_type == "box":
        if not (isinstance(coords, list) and len(coords) == 4 and all(isinstance(v, int) for v in coords)):
            return _err_std(
                _id,
                -32602,
                "Invalid params: box coords must be [x1,y1,x2,y2] (int DBU)",
                "InvalidParams",
                {"field": "coords"},
            )
        x1, y1, x2, y2 = coords
        cell.shapes(li).insert(pya.Box(x1, y1, x2, y2))
        return _jsonrpc_result(_id, {"inserted": True, "type": "box", "cell": cell_name, "layer_index": int(li)})

    if shape_type == "polygon":
        if not (isinstance(coords, list) and len(coords) >= 3):
            return _err_std(
                _id,
                -32602,
                "Invalid params: polygon coords must be [[x,y],...] with >=3 points",
                "InvalidParams",
                {"field": "coords"},
            )
        pts = []
        for p in coords:
            if not (isinstance(p, list) and len(p) == 2 and isinstance(p[0], int) and isinstance(p[1], int)):
                return _err_std(
                    _id,
                    -32602,
                    "Invalid params: polygon point must be [x,y] (int DBU)",
                    "InvalidParams",
                    {"field": "coords"},
                )
            pts.append(pya.Point(p[0], p[1]))
        cell.shapes(li).insert(pya.Polygon(pts))
        return _jsonrpc_result(
            _id,
            {"inserted": True, "type": "polygon", "cell": cell_name, "layer_index": int(li)},
        )

    return _err_std(
        _id,
        -32602,
        f"Invalid params: unsupported shape type: {shape_type}",
        "InvalidParams",
        {"field": "type"},
    )


def _m_layout_export(_id, params):
    err = _require_active_layout(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    path = params.get("path", None)
    overwrite = params.get("overwrite", True)

    if not isinstance(overwrite, bool):
        return _err_std(_id, -32602, "Invalid params: overwrite must be boolean", "InvalidParams", {"field": "overwrite"})

    resolved, perr = _resolve_export_path(_id, path)
    if perr:
        return perr

    if os.path.exists(resolved["abs"]) and not overwrite:
        return _err(
            _id,
            -32011,
            f"File exists and overwrite=false: {resolved['rel']}",
            "FileExists",
            {"path": resolved["rel"]},
        )

    try:
        _STATE.layout.write(resolved["abs"])
    except Exception as e:
        return _err(_id, -32099, f"Internal error during export: {e}", "InternalError")

    return _jsonrpc_result(_id, {"written": True, "path": resolved["rel"]})


def _m_layout_open(_id, params):
    """需求4-2: open a layout file in KLayout and switch active server layout.

    Params:
      path: string, required, under server cwd
      mode: 0|1|2 (default 0) - passed to MainWindow.load_layout
    """
    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    path = params.get("path", None)
    mode = params.get("mode", 0)

    if not isinstance(mode, int) or mode not in (0, 1, 2):
        return _err_std(
            _id,
            -32602,
            "Invalid params: mode must be 0, 1, or 2",
            "InvalidParams",
            {"field": "mode", "allowed": [0, 1, 2], "got": mode},
        )

    resolved, perr = _resolve_open_path(_id, path)
    if perr:
        return perr

    if not os.path.exists(resolved["abs"]):
        return _err(_id, -32012, f"File not found: {resolved['rel']}", "FileNotFound", {"path": resolved["rel"]})

    app = pya.Application.instance()
    mw = None
    try:
        mw = app.main_window()
    except Exception:
        mw = None

    if mw is None:
        return _err(_id, -32013, "MainWindow not available: cannot open layout", "MainWindowUnavailable")

    try:
        cv = mw.load_layout(resolved["abs"], int(mode))
        layout = cv.layout()
    except Exception as e:
        return _err(_id, -32014, f"Failed to open layout: {e}", "OpenFailed")

    if layout is None:
        return _err(_id, -32014, "Failed to open layout: no layout returned", "OpenFailed")

    # Switch server state to this layout.
    _STATE.layout = layout
    _STATE.layout_id = "L1"
    _STATE.current_layer_index = None

    top_cell = None
    try:
        top_cell = layout.top_cell()
    except Exception:
        top_cell = None

    if top_cell is None:
        try:
            tops = layout.top_cells()
            if tops and len(tops) > 0:
                top_cell = tops[0]
        except Exception:
            top_cell = None

    _STATE.top_cell = top_cell
    _STATE.top_cell_name = top_cell.name if top_cell is not None else None

    return _jsonrpc_result(
        _id,
        {
            "opened": True,
            "path": resolved["rel"],
            "mode": int(mode),
            "top_cell": _STATE.top_cell_name,
        },
    )


def _m_layout_get_topcell(_id, params):
    """需求5-1: get the (single) top cell name.

    Errors:
      - NoActiveLayout
      - NoTopCell
      - MultipleTopCells
    """
    err = _require_active_layout(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    try:
        tops = _STATE.layout.top_cells()
    except Exception as e:
        return _err(_id, -32099, f"Internal error: {e}", "InternalError")

    if not tops or len(tops) == 0:
        return _err(_id, -32020, "No top cell in layout", "NoTopCell")

    if len(tops) != 1:
        return _err(
            _id,
            -32021,
            f"Multiple top cells in layout: {len(tops)}",
            "MultipleTopCells",
            {"count": int(len(tops)), "names": [c.name for c in tops]},
        )

    return _jsonrpc_result(_id, {"top_cell": tops[0].name})


def _m_layout_get_layers(_id, params):
    """需求5-2: get list of valid layers (definition-based)."""
    err = _require_active_layout(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    try:
        idxs = list(_STATE.layout.layer_indexes())
        infos = list(_STATE.layout.layer_infos())
    except Exception as e:
        return _err(_id, -32099, f"Internal error: {e}", "InternalError")

    layers = []
    for li, info in zip(idxs, infos):
        try:
            layer_num = int(getattr(info, "layer"))
        except Exception:
            layer_num = None
        try:
            datatype = int(getattr(info, "datatype"))
        except Exception:
            datatype = None
        try:
            name = getattr(info, "name")
        except Exception:
            name = None
        if name is not None and not isinstance(name, str):
            name = str(name)

        layers.append({"layer": layer_num, "datatype": datatype, "name": name, "layer_index": int(li)})

    return _jsonrpc_result(_id, {"layers": layers})


def _m_layout_get_dbu(_id, params):
    """需求5-3: get dbu."""
    err = _require_active_layout(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    return _jsonrpc_result(_id, {"dbu": float(_STATE.layout.dbu)})


def _m_layout_get_cells(_id, params):
    """需求5-4: get cell list."""
    err = _require_active_layout(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    cells = []
    try:
        for ci in _STATE.layout.each_cell_top_down():
            try:
                c = _STATE.layout.cell(ci)
                cells.append(c.name)
            except Exception:
                continue
    except Exception as e:
        return _err(_id, -32099, f"Internal error: {e}", "InternalError")

    return _jsonrpc_result(_id, {"cells": cells})


def _m_layout_get_hierarchy_depth(_id, params):
    """需求5-5: get hierarchy depth.

    Definition:
      - depth = max instance edges from top (top=0)
      - leaf/top with no instances -> depth 0
    """
    err = _require_active_layout(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    try:
        tops = _STATE.layout.top_cells()
    except Exception as e:
        return _err(_id, -32099, f"Internal error: {e}", "InternalError")

    if not tops or len(tops) == 0:
        return _err(_id, -32020, "No top cell in layout", "NoTopCell")

    if len(tops) != 1:
        return _err(
            _id,
            -32021,
            f"Multiple top cells in layout: {len(tops)}",
            "MultipleTopCells",
            {"count": int(len(tops)), "names": [c.name for c in tops]},
        )

    memo = {}

    def cell_key(cell):
        try:
            return int(cell.cell_index())
        except Exception:
            try:
                return int(cell.cell_index)
            except Exception:
                return id(cell)

    def depth_from(cell, stack):
        k = cell_key(cell)
        if k in memo:
            return memo[k]
        if k in stack:
            # Should not happen (recursive hierarchy), but avoid infinite loops.
            memo[k] = 0
            return 0
        stack.add(k)
        m = 0
        try:
            for inst in cell.each_inst():
                try:
                    cc = inst.cell
                except Exception:
                    try:
                        cc = inst.cell_()
                    except Exception:
                        cc = None
                if cc is None:
                    continue
                m = max(m, 1 + depth_from(cc, stack))
        except Exception:
            m = 0
        stack.remove(k)
        memo[k] = int(m)
        return int(m)

    depth = depth_from(tops[0], set())

    return _jsonrpc_result(
        _id,
        {
            "depth": int(depth),
            "depth_definition": "max instance edges from top (top=0)",
        },
    )


def _req3_parent_child_cells(_id, params):
    cell_name = params.get("cell", "TOP")
    if not isinstance(cell_name, str) or not cell_name:
        return None, _err(_id, -32000, "Invalid params: cell must be a non-empty string", "InvalidParams", {"field": "cell"})

    child_name = params.get("child_cell", None)
    if not isinstance(child_name, str) or not child_name:
        return None, _err(
            _id,
            -32000,
            "Invalid params: child_cell must be a non-empty string",
            "InvalidParams",
            {"field": "child_cell"},
        )

    if not _STATE.layout.has_cell(cell_name):
        return None, _err(_id, -32000, f"Cell not found: {cell_name}", "CellNotFound", {"name": cell_name})

    if not _STATE.layout.has_cell(child_name):
        return None, _err(
            _id,
            -32000,
            f"Child cell not found: {child_name}",
            "ChildCellNotFound",
            {"name": child_name},
        )

    parent_cell = _STATE.layout.cell(cell_name)
    child_cell = _STATE.layout.cell(child_name)

    return {
        "cell": cell_name,
        "child_cell": child_name,
        "parent_cell": parent_cell,
        "child_cell_obj": child_cell,
    }, None


def _req3_parse_trans(_id, params):
    trans = params.get("trans", {})
    if trans is None:
        trans = {}
    if not isinstance(trans, dict):
        return None, _err(_id, -32000, "Invalid params: trans must be an object", "InvalidParams", {"field": "trans"})

    x = trans.get("x", 0)
    y = trans.get("y", 0)
    rot = trans.get("rot", 0)
    mirror = trans.get("mirror", False)

    if not isinstance(x, int) or not isinstance(y, int):
        return None, _err(
            _id,
            -32000,
            "Invalid params: trans.x and trans.y must be int (DBU)",
            "InvalidParams",
            {"field": "trans"},
        )

    if not isinstance(rot, int):
        return None, _err(
            _id,
            -32000,
            "Invalid params: trans.rot must be int degrees (0/90/180/270)",
            "InvalidParams",
            {"field": "trans.rot"},
        )

    if rot not in (0, 90, 180, 270):
        return None, _err(
            _id,
            -32000,
            f"Invalid params: rot must be one of 0,90,180,270 (got {rot})",
            "InvalidParams",
            {"field": "trans.rot", "allowed": [0, 90, 180, 270], "got": rot},
        )

    if not isinstance(mirror, bool):
        return None, _err(
            _id,
            -32000,
            "Invalid params: trans.mirror must be boolean",
            "InvalidParams",
            {"field": "trans.mirror"},
        )

    rot_quadrants = rot // 90
    t = pya.Trans(rot_quadrants, mirror, x, y)

    return {"t": t, "x": x, "y": y, "rot": rot, "mirror": mirror}, None


def _req3_parse_array(_id, params):
    arr = params.get("array", None)
    if not isinstance(arr, dict):
        return None, _err(_id, -32000, "Invalid params: array must be an object", "InvalidParams", {"field": "array"})

    nx = arr.get("nx", None)
    ny = arr.get("ny", None)
    dx = arr.get("dx", None)
    dy = arr.get("dy", None)

    if not isinstance(nx, int) or nx < 1:
        return None, _err(_id, -32000, "Invalid params: nx must be int >= 1", "InvalidParams", {"field": "array.nx", "got": nx})
    if not isinstance(ny, int) or ny < 1:
        return None, _err(_id, -32000, "Invalid params: ny must be int >= 1", "InvalidParams", {"field": "array.ny", "got": ny})
    if not isinstance(dx, int) or not isinstance(dy, int):
        return None, _err(_id, -32000, "Invalid params: dx and dy must be int (DBU)", "InvalidParams", {"field": "array"})

    return {"nx": nx, "ny": ny, "dx": dx, "dy": dy}, None


def _m_instance_create(_id, params):
    """需求3-2: create a single instance."""
    err = _require_active_layout_str(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    cells, e = _req3_parent_child_cells(_id, params)
    if e:
        return e

    tr, e = _req3_parse_trans(_id, params)
    if e:
        return e

    # Create a single instance
    cia = pya.CellInstArray(cells["child_cell_obj"], tr["t"])
    cells["parent_cell"].insert(cia)

    return _jsonrpc_result(
        _id,
        {
            "inserted": True,
            "cell": cells["cell"],
            "child_cell": cells["child_cell"],
            "trans": {"x": tr["x"], "y": tr["y"], "rot": tr["rot"], "mirror": tr["mirror"]},
        },
    )


def _m_instance_array_create(_id, params):
    """需求3-3: create a regular array of instances."""
    err = _require_active_layout_str(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    cells, e = _req3_parent_child_cells(_id, params)
    if e:
        return e

    tr, e = _req3_parse_trans(_id, params)
    if e:
        return e

    arr, e = _req3_parse_array(_id, params)
    if e:
        return e

    a = pya.Vector(arr["dx"], 0)
    b = pya.Vector(0, arr["dy"])

    cia = pya.CellInstArray(cells["child_cell_obj"], tr["t"], a, b, arr["nx"], arr["ny"])
    cells["parent_cell"].insert(cia)

    return _jsonrpc_result(
        _id,
        {
            "inserted": True,
            "cell": cells["cell"],
            "child_cell": cells["child_cell"],
            "trans": {"x": tr["x"], "y": tr["y"], "rot": tr["rot"], "mirror": tr["mirror"]},
            "array": {"nx": arr["nx"], "ny": arr["ny"], "dx": arr["dx"], "dy": arr["dy"]},
        },
    )


_METHODS = {}

# Spec v0 methods
_METHODS.update(
    {
        "ping": _m_ping,
        "layout.new": _m_layout_new,
        "layer.new": _m_layer_new,
        "shape.create": _m_shape_create,
        "layout.export": _m_layout_export,
    }
)

# Req3+ methods
_METHODS.update(
    {
        "cell.create": _m_cell_create,
        "instance.create": _m_instance_create,
        "instance_array.create": _m_instance_array_create,
        "layout.open": _m_layout_open,

        "layout.get_topcell": _m_layout_get_topcell,
        "layout.get_layers": _m_layout_get_layers,
        "layout.get_dbu": _m_layout_get_dbu,
        "layout.get_cells": _m_layout_get_cells,
        "layout.get_hierarchy_depth": _m_layout_get_hierarchy_depth,
    }
)


def _handle_request(req):
    if not isinstance(req, dict):
        return _err_std(None, -32600, "Invalid Request: request must be an object", "InvalidRequest")

    if req.get("jsonrpc") != "2.0":
        return _err_std(req.get("id", None), -32600, "Invalid Request: jsonrpc must be '2.0'", "InvalidRequest")

    _id = req.get("id", None)
    method = req.get("method", None)
    params = req.get("params", {})

    if not isinstance(method, str) or not method:
        return _err_std(_id, -32600, "Invalid Request: method must be a non-empty string", "InvalidRequest")

    if params is None:
        params = {}

    fn = _METHODS.get(method)
    if fn is None:
        return _err_std(_id, -32601, f"Method not found: {method}", "MethodNotFound", {"method": method})

    try:
        return fn(_id, params)
    except Exception as e:
        # If we know the reason, methods should return a specific error already.
        return _err(_id, -32099, f"Internal error: {e}", "InternalError")


def _handle_line(sock, raw_line):
    if not raw_line.strip():
        return

    try:
        req = json.loads(raw_line.decode("utf-8"))
    except Exception as e:
        _send_obj(sock, _err_std(None, -32700, f"Parse error: {e}", "ParseError"))
        return

    # Notifications: if id is omitted -> no response
    if isinstance(req, dict) and ("id" not in req):
        _handle_request(req)
        return

    resp = _handle_request(req)
    _send_obj(sock, resp)


# -----------------------------------------------------------------------------
# Qt socket callbacks
# -----------------------------------------------------------------------------


def _on_client_ready_read(state):
    sock = state.sock

    data = _bytes_to_py(sock.readAll())
    if not data:
        return

    state.buf += data

    while b"\n" in state.buf:
        raw_line, state.buf = state.buf.split(b"\n", 1)
        _handle_line(sock, raw_line)


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


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------


_env_port = int(os.environ.get("KLAYOUT_SERVER_PORT", "0"))
PORT = start_server(_env_port)
print("[klayout-gui-server] PORT=", PORT, flush=True)
