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
        self.layout_filename = None      # string | None (best-effort source filename)
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


def _guardrail_too_many_results(_id, kind: str, limit: int, got_so_far: int, message: str, data: dict | None = None):
    """Guardrail helper.

    'Guardrail' here means an intentional safety limit to prevent accidental
    blow-ups (huge JSON responses, memory pressure, UI stalls) when querying
    deep hierarchies or expanded arrays.

    This is a design choice and not necessarily an indication that typical
    layouts are risky.
    """
    payload = {"type": "TooManyResults", "kind": str(kind), "limit": int(limit), "got_so_far": int(got_so_far)}
    if isinstance(data, dict):
        payload.update(data)
    return _err(
        _id,
        -32030,
        message,
        "TooManyResults",
        payload,
    )


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


def _trans_to_dict(t: "pya.Trans"):
    """Convert KLayout Trans to our JSON-friendly trans dict.

    Note: angle is in units of 90 degrees in KLayout.
    """
    try:
        disp = t.disp
        x = int(disp.x)
        y = int(disp.y)
    except Exception:
        x = 0
        y = 0

    try:
        rot = int(t.angle) * 90
    except Exception:
        rot = 0

    try:
        mirror = bool(t.is_mirror())
    except Exception:
        try:
            mirror = bool(t.mirror)
        except Exception:
            mirror = False

    return {"x": x, "y": y, "rot": rot, "mirror": mirror}


def _box_to_dict(b: "pya.Box"):
    try:
        return {"x1": int(b.left), "y1": int(b.bottom), "x2": int(b.right), "y2": int(b.top)}
    except Exception:
        # Fallback: try p1/p2.
        try:
            p1 = b.p1
            p2 = b.p2
            return {"x1": int(p1.x), "y1": int(p1.y), "x2": int(p2.x), "y2": int(p2.y)}
        except Exception:
            return None


# -----------------------------------------------------------------------------
# GUI refresh helper
# -----------------------------------------------------------------------------


def _gui_refresh(reason=None):
    """Best-effort refresh of KLayout GUI after DB changes.

    Problem:
      When we modify a Layout via the scripting API (insert shapes/instances,
      create layers, etc.), the visible GUI may not repaint immediately.

    Strategy:
      - If a MainWindow/current_view exists, ask it to refresh/redraw.
      - Always wrap in try/except to avoid breaking headless runs.

    Notes:
      - This is intentionally best-effort: KLayout API/Qt bindings differ across
        versions and environments.
      - In headless mode, main_window/current_view are typically unavailable and
        this becomes a no-op.
    """
    try:
        app = pya.Application.instance()
    except Exception:
        return

    mw = None
    try:
        mw = app.main_window()
    except Exception:
        mw = None

    # Process pending GUI events first (helps in some cases)
    try:
        app.process_events()
    except Exception:
        pass

    if mw is None:
        return

    view = None
    try:
        view = mw.current_view()
    except Exception:
        view = None

    if view is not None:
        for meth in ("add_missing_layers", "refresh", "redraw", "update"):
            try:
                fn = getattr(view, meth, None)
                if callable(fn):
                    fn()
            except Exception:
                pass

        # Qt widget repaint fallback
        try:
            vp = getattr(view, "viewport", None)
            if callable(vp):
                vp = vp()
            if vp is not None:
                upd = getattr(vp, "update", None)
                if callable(upd):
                    upd()
        except Exception:
            pass

    # MainWindow message is optional; avoid spamming.
    if reason:
        try:
            mw.message(f"[openclaw] refreshed: {reason}")
        except Exception:
            pass


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
    _STATE.layout_filename = None
    _STATE.top_cell = top_cell
    _STATE.top_cell_name = top_cell_name
    _STATE.current_layer_index = None

    _gui_refresh("layout.new")

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

    _gui_refresh("layer.new")

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
    _gui_refresh("cell.create")
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
        _gui_refresh("shape.create(box)")
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
        # Use SimplePolygon for better compatibility with RecursiveShapeIterator
        cell.shapes(li).insert(pya.SimplePolygon(pts))
        _gui_refresh("shape.create(polygon)")
        return _jsonrpc_result(
            _id,
            {"inserted": True, "type": "polygon", "cell": cell_name, "layer_index": int(li)},
        )

    if shape_type == "path":
        if not (isinstance(coords, list) and len(coords) >= 2):
            return _err_std(
                _id,
                -32602,
                "Invalid params: path coords must be [[x,y],...] with >=2 points",
                "InvalidParams",
                {"field": "coords"},
            )
        width = params.get("width", None)
        if not isinstance(width, int) or width <= 0:
            return _err_std(
                _id,
                -32602,
                "Invalid params: path width must be a positive int (DBU)",
                "InvalidParams",
                {"field": "width"},
            )
        pts = []
        for p in coords:
            if not (isinstance(p, list) and len(p) == 2 and isinstance(p[0], int) and isinstance(p[1], int)):
                return _err_std(
                    _id,
                    -32602,
                    "Invalid params: path point must be [x,y] (int DBU)",
                    "InvalidParams",
                    {"field": "coords"},
                )
            pts.append(pya.Point(p[0], p[1]))
        cell.shapes(li).insert(pya.Path(pts, width))
        _gui_refresh("shape.create(path)")
        return _jsonrpc_result(
            _id,
            {"inserted": True, "type": "path", "cell": cell_name, "layer_index": int(li), "width": int(width)},
        )

    return _err_std(
        _id,
        -32602,
        f"Invalid params: unsupported shape type: {shape_type}",
        "InvalidParams",
        {"field": "type"},
    )


def _resolve_screenshot_path(_id, path):
    """Resolve screenshot output path.

    - If path is relative, it is interpreted relative to server cwd.
    - For safety, path must stay within server cwd.
    - Default extension is .png (if not provided).
    """
    if path is None:
        return None, _err_std(_id, -32602, "Invalid params: path is required", "InvalidParams", {"field": "path"})
    if not isinstance(path, str) or not path:
        return None, _err_std(_id, -32602, "Invalid params: path must be a non-empty string", "InvalidParams", {"field": "path"})

    rel = path
    if not rel.lower().endswith(".png"):
        rel = rel + ".png"

    abs_p = os.path.abspath(os.path.join(os.getcwd(), rel))
    cwd = os.path.abspath(os.getcwd())
    if os.path.commonpath([abs_p, cwd]) != cwd:
        return None, _err(_id, -32015, f"Invalid path (outside cwd): {rel}", "InvalidPath", {"path": rel})

    # ensure parent dir exists
    try:
        os.makedirs(os.path.dirname(abs_p) or cwd, exist_ok=True)
    except Exception as e:
        return None, _err(_id, -32099, f"Failed to create directory: {e}", "InternalError")

    return {"rel": rel, "abs": abs_p}, None


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


def _to_um(layout, v, units):
    """Convert value to micron (um)."""
    if units == "um":
        return float(v)
    # dbu -> um
    return float(v) * float(layout.dbu)


def _make_dbox(layout, units, box=None, center=None, size=None):
    """Build a DBox in micron units from either box=[x1,y1,x2,y2] or center/size."""
    if box is not None:
        x1, y1, x2, y2 = box
        return pya.DBox(_to_um(layout, x1, units), _to_um(layout, y1, units), _to_um(layout, x2, units), _to_um(layout, y2, units))
    if center is not None and size is not None:
        cx, cy = center
        w, h = size
        cxu = _to_um(layout, cx, units)
        cyu = _to_um(layout, cy, units)
        wu = _to_um(layout, w, units)
        hu = _to_um(layout, h, units)
        return pya.DBox(cxu - wu / 2.0, cyu - hu / 2.0, cxu + wu / 2.0, cyu + hu / 2.0)
    return pya.DBox()


def _m_view_screenshot(_id, params):
    """程式化截圖：將目前 LayoutView 匯出成 PNG。

    依賴 KLayout GUI：需要 MainWindow 與 current_view。

    Params:
      path: string (required) - output path under server cwd. ".png" is appended if missing.
      width: int (default 1200)
      height: int (default 800)

      viewport_mode: "fit" | "box" | "center_size" | "relative" (default: fit)
      units: "um" | "dbu" (default: dbu)
      box: [x1,y1,x2,y2] (required when viewport_mode=box)
      center: [cx,cy] (required when viewport_mode=center_size)
      size: [w,h] (required when viewport_mode=center_size)
      steps: int (optional, used when viewport_mode=relative)

      oversampling: int (default 0) - passed to save_image_with_options
      resolution: float (default 0)
      linewidth: int (default 0)
      monochrome: bool (default false)
      overwrite: bool (default true)

    Notes:
      - Uses LayoutView.save_image_with_options (writes PNG synchronously).
      - This captures the current scene (layout + annotations etc.).
    """
    err = _require_active_layout(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    path = params.get("path", None)
    width = params.get("width", 1200)
    height = params.get("height", 800)

    viewport_mode = params.get("viewport_mode", "fit")
    units = params.get("units", "dbu")
    box = params.get("box", None)
    center = params.get("center", None)
    size = params.get("size", None)
    steps = params.get("steps", 0)
    oversampling = params.get("oversampling", 0)
    resolution = params.get("resolution", 0)
    linewidth = params.get("linewidth", 0)
    monochrome = params.get("monochrome", False)
    overwrite = params.get("overwrite", True)

    if viewport_mode not in ("fit", "box", "center_size", "relative"):
        return _err_std(_id, -32602, "Invalid params: viewport_mode must be fit|box|center_size|relative", "InvalidParams", {"field": "viewport_mode", "got": viewport_mode})
    if units not in ("um", "dbu"):
        return _err_std(_id, -32602, "Invalid params: units must be um|dbu", "InvalidParams", {"field": "units", "got": units})

    if not isinstance(width, int) or width < 1:
        return _err_std(_id, -32602, "Invalid params: width must be int >= 1", "InvalidParams", {"field": "width", "got": width})
    if not isinstance(height, int) or height < 1:
        return _err_std(_id, -32602, "Invalid params: height must be int >= 1", "InvalidParams", {"field": "height", "got": height})

    if viewport_mode == "box":
        if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)):
            return _err_std(_id, -32602, "Invalid params: box must be [x1,y1,x2,y2]", "InvalidParams", {"field": "box", "got": box})
    if viewport_mode == "center_size":
        if not (isinstance(center, list) and len(center) == 2 and all(isinstance(v, (int, float)) for v in center)):
            return _err_std(_id, -32602, "Invalid params: center must be [cx,cy]", "InvalidParams", {"field": "center", "got": center})
        if not (isinstance(size, list) and len(size) == 2 and all(isinstance(v, (int, float)) for v in size)):
            return _err_std(_id, -32602, "Invalid params: size must be [w,h]", "InvalidParams", {"field": "size", "got": size})
    if viewport_mode == "relative":
        if not isinstance(steps, int):
            return _err_std(_id, -32602, "Invalid params: steps must be int", "InvalidParams", {"field": "steps", "got": steps})

    if not isinstance(oversampling, int) or oversampling < 0:
        return _err_std(_id, -32602, "Invalid params: oversampling must be int >= 0", "InvalidParams", {"field": "oversampling", "got": oversampling})
    if not isinstance(resolution, (int, float)):
        return _err_std(_id, -32602, "Invalid params: resolution must be number", "InvalidParams", {"field": "resolution", "got": resolution})
    if not isinstance(linewidth, int) or linewidth < 0:
        return _err_std(_id, -32602, "Invalid params: linewidth must be int >= 0", "InvalidParams", {"field": "linewidth", "got": linewidth})
    if not isinstance(monochrome, bool):
        return _err_std(_id, -32602, "Invalid params: monochrome must be boolean", "InvalidParams", {"field": "monochrome", "got": monochrome})
    if not isinstance(overwrite, bool):
        return _err_std(_id, -32602, "Invalid params: overwrite must be boolean", "InvalidParams", {"field": "overwrite", "got": overwrite})

    resolved, perr = _resolve_screenshot_path(_id, path)
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

    app = pya.Application.instance()
    mw = None
    try:
        mw = app.main_window()
    except Exception:
        mw = None

    if mw is None:
        return _err(_id, -32013, "MainWindow not available: cannot screenshot", "MainWindowUnavailable")

    view = None
    try:
        view = mw.current_view()
    except Exception:
        view = None

    if view is None:
        return _err(_id, -32016, "No current view: cannot screenshot", "NoCurrentView")

    # Best-effort: ensure GUI updates before capture
    _gui_refresh("pre-screenshot")

    # Apply viewport controls
    _apply_viewport(view, _STATE.layout, viewport_mode, units, box, center, size, steps)

    try:
        # target=DBox() (empty) uses current/default
        try:
            target = pya.DBox()
        except Exception:
            target = None

        if target is None:
            view.save_image(resolved["abs"], int(width), int(height))
        else:
            view.save_image_with_options(
                resolved["abs"],
                int(width),
                int(height),
                int(linewidth),
                int(oversampling),
                float(resolution),
                target,
                bool(monochrome),
            )
    except Exception as e:
        return _err(_id, -32099, f"Failed to save screenshot: {e}", "InternalError")

    return _jsonrpc_result(
        _id,
        {
            "written": True,
            "path": resolved["rel"],
            "width": int(width),
            "height": int(height),
            "viewport_mode": viewport_mode,
            "units": units,
        },
    )



def _apply_viewport(view, layout, viewport_mode, units, box, center, size, steps):
    """Apply viewport controls to a LayoutView (best-effort)."""
    try:
        if viewport_mode == "fit":
            view.zoom_fit()
        elif viewport_mode == "box":
            view.zoom_box(_make_dbox(layout, units, box=box))
        elif viewport_mode == "center_size":
            view.zoom_box(_make_dbox(layout, units, center=center, size=size))
        else:
            if steps > 0:
                for _ in range(steps):
                    view.zoom_in()
            elif steps < 0:
                for _ in range(-steps):
                    view.zoom_out()
    except Exception:
        pass


def _get_main_window():
    try:
        app = pya.Application.instance()
    except Exception:
        return None
    try:
        return app.main_window()
    except Exception:
        return None


def _get_current_view():
    mw = _get_main_window()
    if mw is None:
        return None, "MainWindowUnavailable"
    try:
        v = mw.current_view()
    except Exception:
        v = None
    if v is None:
        return None, "NoCurrentView"
    return v, None


def _ensure_current_view(layout):
    """Ensure a GUI LayoutView exists and is current, then show given layout.

    Returns: (view, err_type)
      err_type: None | "MainWindowUnavailable" | "NoCurrentView" | "InternalError"
    """
    mw = _get_main_window()
    if mw is None:
        return None, "MainWindowUnavailable"

    # If a current view exists, reuse it.
    try:
        v = mw.current_view()
    except Exception:
        v = None

    # Otherwise create a new empty view and select it.
    if v is None:
        try:
            vidx = mw.create_view()
            try:
                mw.current_view_index = int(vidx)
            except Exception:
                try:
                    mw.current_view_index = int(vidx)  # attribute setter
                except Exception:
                    pass
            try:
                v = mw.view(int(vidx))
            except Exception:
                v = None
        except Exception:
            v = None

    if v is None:
        return None, "NoCurrentView"

    # Show layout in the view (create a cellview) so GUI operations have target.
    try:
        v.show_layout(layout, True)
    except Exception:
        # Some versions use named args or expect bool add_cellview.
        try:
            v.show_layout(layout, add_cellview=True)
        except Exception as e:
            return None, "InternalError"

    return v, None


def _m_view_ensure(_id, params):
    """確保 GUI current_view 存在，並將目前 active layout 顯示到 view。

    這是為了符合「客戶端→控制 GUI 行為」：view.* 類 RPC 需要可操作的 current_view。

    Params:
      zoom_fit: bool (default true) - after showing the layout, do zoom_fit.

    """
    err = _require_active_layout(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    zoom_fit = params.get("zoom_fit", True)
    if not isinstance(zoom_fit, bool):
        return _err_std(_id, -32602, "Invalid params: zoom_fit must be boolean", "InvalidParams", {"field": "zoom_fit"})

    view, e = _ensure_current_view(_STATE.layout)
    if e == "MainWindowUnavailable":
        return _err(_id, -32013, "MainWindow not available: cannot ensure view", "MainWindowUnavailable")
    if e == "NoCurrentView":
        return _err(_id, -32016, "Cannot create/obtain current view", "NoCurrentView")
    if e == "InternalError":
        return _err(_id, -32099, "Failed to show layout in view", "InternalError")

    _gui_refresh("view.ensure")
    if zoom_fit:
        try:
            view.zoom_fit()
        except Exception:
            pass
    _gui_refresh("view.ensure.post")

    # Report view counts/index
    mw = _get_main_window()
    try:
        views_n = int(mw.views())
    except Exception:
        views_n = None
    try:
        cur_idx = int(mw.current_view_index)
    except Exception:
        cur_idx = None

    return _jsonrpc_result(_id, {"ok": True, "views": views_n, "current_view_index": cur_idx})



def _m_view_set_viewport(_id, params):
    """只改視圖、不截圖：控制 GUI current_view 的 viewport。

    Params:
      viewport_mode: "fit" | "box" | "center_size" | "relative" (default: fit)
      units: "um" | "dbu" (default: dbu)
      box: [x1,y1,x2,y2] (required when viewport_mode=box)
      center: [cx,cy] (required when viewport_mode=center_size)
      size: [w,h] (required when viewport_mode=center_size)
      steps: int (optional, used when viewport_mode=relative)

    Requires:
      - MainWindow + current_view
    """
    err = _require_active_layout(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    viewport_mode = params.get("viewport_mode", "fit")
    units = params.get("units", "dbu")
    box = params.get("box", None)
    center = params.get("center", None)
    size = params.get("size", None)
    steps = params.get("steps", 0)

    if viewport_mode not in ("fit", "box", "center_size", "relative"):
        return _err_std(_id, -32602, "Invalid params: viewport_mode must be fit|box|center_size|relative", "InvalidParams", {"field": "viewport_mode", "got": viewport_mode})
    if units not in ("um", "dbu"):
        return _err_std(_id, -32602, "Invalid params: units must be um|dbu", "InvalidParams", {"field": "units", "got": units})

    if viewport_mode == "box":
        if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)):
            return _err_std(_id, -32602, "Invalid params: box must be [x1,y1,x2,y2]", "InvalidParams", {"field": "box", "got": box})
    if viewport_mode == "center_size":
        if not (isinstance(center, list) and len(center) == 2 and all(isinstance(v, (int, float)) for v in center)):
            return _err_std(_id, -32602, "Invalid params: center must be [cx,cy]", "InvalidParams", {"field": "center", "got": center})
        if not (isinstance(size, list) and len(size) == 2 and all(isinstance(v, (int, float)) for v in size)):
            return _err_std(_id, -32602, "Invalid params: size must be [w,h]", "InvalidParams", {"field": "size", "got": size})
    if viewport_mode == "relative":
        if not isinstance(steps, int):
            return _err_std(_id, -32602, "Invalid params: steps must be int", "InvalidParams", {"field": "steps", "got": steps})

    view, v_err = _get_current_view()
    if v_err == "MainWindowUnavailable":
        return _err(_id, -32013, "MainWindow not available: cannot set viewport", "MainWindowUnavailable")
    if v_err == "NoCurrentView":
        return _err(_id, -32016, "No current view: cannot set viewport", "NoCurrentView")

    _gui_refresh("pre-viewport")
    _apply_viewport(view, _STATE.layout, viewport_mode, units, box, center, size, steps)
    _gui_refresh("post-viewport")

    return _jsonrpc_result(
        _id,
        {
            "ok": True,
            "viewport_mode": viewport_mode,
            "units": units,
        },
    )


def _m_view_set_hier_levels(_id, params):
    """控制 view 的 hierarchy geometry 顯示深度（不是展開 tree widget）。

    這個對應 KLayout 的 min_hier_levels / max_hier_levels（以及 max_hier()）。

    Params:
      mode: "max" | "set" (default: max)
      min_level: int (optional, only for mode=set)
      max_level: int (optional, only for mode=set)

    Notes:
      - mode=max 會呼叫 view.max_hier()（顯示所有 hierarchy levels）
      - 這是 API 層級的顯示深度控制，較穩；
        不是去操作 Hierarchy browser UI 的展開節點。
    """
    err = _require_active_layout(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    mode = params.get("mode", "max")
    min_level = params.get("min_level", None)
    max_level = params.get("max_level", None)

    if mode not in ("max", "set"):
        return _err_std(_id, -32602, "Invalid params: mode must be max|set", "InvalidParams", {"field": "mode", "got": mode})
    if mode == "set":
        if min_level is not None and (not isinstance(min_level, int) or min_level < 0):
            return _err_std(_id, -32602, "Invalid params: min_level must be int >= 0", "InvalidParams", {"field": "min_level", "got": min_level})
        if max_level is not None and (not isinstance(max_level, int) or max_level < 0):
            return _err_std(_id, -32602, "Invalid params: max_level must be int >= 0", "InvalidParams", {"field": "max_level", "got": max_level})

    view, v_err = _get_current_view()
    if v_err == "MainWindowUnavailable":
        return _err(_id, -32013, "MainWindow not available: cannot set hier levels", "MainWindowUnavailable")
    if v_err == "NoCurrentView":
        return _err(_id, -32016, "No current view: cannot set hier levels", "NoCurrentView")

    _gui_refresh("pre-hier-levels")

    try:
        if mode == "max":
            view.max_hier()
        else:
            if min_level is not None:
                view.min_hier_levels = int(min_level)
            if max_level is not None:
                view.max_hier_levels = int(max_level)
    except Exception as e:
        return _err(_id, -32099, f"Failed to set hierarchy levels: {e}", "InternalError")

    _gui_refresh("post-hier-levels")

    try:
        cur_min = int(view.min_hier_levels)
        cur_max = int(view.max_hier_levels)
    except Exception:
        cur_min = None
        cur_max = None

    return _jsonrpc_result(
        _id,
        {
            "ok": True,
            "mode": mode,
            "min_hier_levels": cur_min,
            "max_hier_levels": cur_max,
        },
    )



def _m_layout_render_png(_id, params):
    """Headless-friendly render: create a standalone LayoutView and export PNG.

    Params:
      path: string (required)
      width: int (default 1200)
      height: int (default 800)
      viewport_mode: "fit" | "box" | "center_size" | "relative" (default: fit)
      units: "um" | "dbu" (default: dbu)
      box: [x1,y1,x2,y2] (required when viewport_mode=box)
      center: [cx,cy] (required when viewport_mode=center_size)
      size: [w,h] (required when viewport_mode=center_size)
      steps: int (optional, used when viewport_mode=relative)

      oversampling: int (default 0)
      resolution: float (default 0)
      linewidth: int (default 0)
      monochrome: bool (default false)
      overwrite: bool (default true)

    Notes:
      - Uses LayoutView.new + LayoutView.show_layout to render even if there is
        no current GUI view.
      - If KLayout build lacks GUI/Qt support, this may fail.
    """
    err = _require_active_layout(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    path = params.get("path", None)
    width = params.get("width", 1200)
    height = params.get("height", 800)
    viewport_mode = params.get("viewport_mode", "fit")
    units = params.get("units", "dbu")

    box = params.get("box", None)
    center = params.get("center", None)
    size = params.get("size", None)
    steps = params.get("steps", 0)

    oversampling = params.get("oversampling", 0)
    resolution = params.get("resolution", 0)
    linewidth = params.get("linewidth", 0)
    monochrome = params.get("monochrome", False)
    overwrite = params.get("overwrite", True)

    if viewport_mode not in ("fit", "box", "center_size", "relative"):
        return _err_std(_id, -32602, "Invalid params: viewport_mode must be fit|box|center_size|relative", "InvalidParams", {"field": "viewport_mode", "got": viewport_mode})
    if units not in ("um", "dbu"):
        return _err_std(_id, -32602, "Invalid params: units must be um|dbu", "InvalidParams", {"field": "units", "got": units})

    if not isinstance(width, int) or width < 1:
        return _err_std(_id, -32602, "Invalid params: width must be int >= 1", "InvalidParams", {"field": "width", "got": width})
    if not isinstance(height, int) or height < 1:
        return _err_std(_id, -32602, "Invalid params: height must be int >= 1", "InvalidParams", {"field": "height", "got": height})

    if viewport_mode == "box":
        if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)):
            return _err_std(_id, -32602, "Invalid params: box must be [x1,y1,x2,y2]", "InvalidParams", {"field": "box", "got": box})
    if viewport_mode == "center_size":
        if not (isinstance(center, list) and len(center) == 2 and all(isinstance(v, (int, float)) for v in center)):
            return _err_std(_id, -32602, "Invalid params: center must be [cx,cy]", "InvalidParams", {"field": "center", "got": center})
        if not (isinstance(size, list) and len(size) == 2 and all(isinstance(v, (int, float)) for v in size)):
            return _err_std(_id, -32602, "Invalid params: size must be [w,h]", "InvalidParams", {"field": "size", "got": size})
    if viewport_mode == "relative":
        if not isinstance(steps, int):
            return _err_std(_id, -32602, "Invalid params: steps must be int", "InvalidParams", {"field": "steps", "got": steps})

    resolved, perr = _resolve_screenshot_path(_id, path)
    if perr:
        return perr
    if os.path.exists(resolved["abs"]) and not overwrite:
        return _err(_id, -32011, f"File exists and overwrite=false: {resolved['rel']}", "FileExists", {"path": resolved["rel"]})

    # Create a standalone view and attach the active layout.
    try:
        view = pya.LayoutView.new(False)
    except Exception as e:
        return _err(_id, -32017, f"Failed to create LayoutView: {e}", "LayoutViewUnavailable")

    try:
        # init_layers=True to populate layer properties automatically
        view.show_layout(_STATE.layout, "", True, True)
    except Exception as e:
        return _err(_id, -32099, f"Failed to show layout in view: {e}", "InternalError")

    # Apply viewport
    _apply_viewport(view, _STATE.layout, viewport_mode, units, box, center, size, steps)

    # Render synchronously
    try:
        target = pya.DBox()  # empty -> current
        view.save_image_with_options(
            resolved["abs"],
            int(width),
            int(height),
            int(linewidth),
            int(oversampling),
            float(resolution),
            target,
            bool(monochrome),
        )
    except Exception as e:
        return _err(_id, -32099, f"Failed to render PNG: {e}", "InternalError")

    return _jsonrpc_result(
        _id,
        {
            "written": True,
            "path": resolved["rel"],
            "width": int(width),
            "height": int(height),
            "viewport_mode": viewport_mode,
            "units": units,
        },
    )



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
    _STATE.layout_filename = resolved["rel"]
    _STATE.current_layer_index = None

    _gui_refresh("layout.open")

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


# -----------------------------------------------------------------------------
# Hierarchy queries (Req6)
# -----------------------------------------------------------------------------


def _maybe_call(x):
    try:
        return x() if callable(x) else x
    except Exception:
        return None


def _inst_path_to_cell_names(inst_path):
    """Convert InstancePath -> [cell_name, ...] (best-effort).

    In KLayout Python, elements in inst_path typically expose `.cell` directly
    (see reference script: `inst.cell.name`). Some bindings may expose `.inst`.
    We support both.
    """
    names = []
    try:
        for el in inst_path or []:
            # Preferred: el.cell
            c = _maybe_call(getattr(el, "cell", None))
            if c is None:
                # Fallback: el.inst.cell
                inst = _maybe_call(getattr(el, "inst", None))
                if inst is not None:
                    c = _maybe_call(getattr(inst, "cell", None))
                    if c is None:
                        c = _maybe_call(getattr(inst, "cell_", None))
            if c is None:
                continue
            nm = _maybe_call(getattr(c, "name", None))
            if nm is not None:
                names.append(str(nm))
    except Exception:
        pass
    return names


def _hierarchy_path_from_iter(layout, start_cell_name, it):
    """Best-effort hierarchy path from RecursiveShapeIterator.

    Per docs, `it.path` returns InstElement[] describing the instance path from
    the initial cell to the current cell containing the current shape.

    We return [start_cell_name, ...cell names along the path..., owner_cell_name].
    """
    hp = [str(start_cell_name)] if start_cell_name else []

    path = _maybe_call(getattr(it, "path", None))
    if path is None:
        path = []

    for el in path or []:
        c = None

        # Common case: InstElement.inst -> Instance
        inst = _maybe_call(getattr(el, "inst", None))
        if inst is not None:
            c = _maybe_call(getattr(inst, "cell", None))
            if c is None:
                c = _maybe_call(getattr(inst, "cell_", None))

        # Alternative: InstElement.cell directly
        if c is None:
            c = _maybe_call(getattr(el, "cell", None))

        # Fallback: cell_index
        if c is None:
            try:
                ci = _maybe_call(getattr(el, "cell_index", None))
                if ci is not None:
                    c = layout.cell(int(ci))
            except Exception:
                c = None

        if c is None:
            continue

        nm = _maybe_call(getattr(c, "name", None))
        if nm is None:
            continue

        nm = str(nm)
        if not hp or hp[-1] != nm:
            hp.append(nm)

    # Append owner cell of current shape if available
    c2 = _maybe_call(getattr(it, "cell", None))
    if c2 is None:
        c2 = _maybe_call(getattr(it, "cell_", None))
    if c2 is not None:
        nm2 = _maybe_call(getattr(c2, "name", None))
        if nm2 is not None:
            nm2 = str(nm2)
            if not hp or hp[-1] != nm2:
                hp.append(nm2)

    return hp


def _shape_points_um_and_bbox(shape, trans, dbu):
    """Return (kind, payload_dict) or (None, None) if unsupported."""
    # Polygon / SimplePolygon
    try:
        # Be permissive across KLayout versions: try to obtain polygon-like geometry
        # even when is_polygon/is_simple_polygon is unavailable or unreliable.
        poly = None
        try:
            poly = _maybe_call(getattr(shape, "polygon", None))
        except Exception:
            poly = None
        if poly is None:
            try:
                poly = _maybe_call(getattr(shape, "simple_polygon", None))
            except Exception:
                poly = None

        pts = []
        if poly is not None:
            try:
                for p in poly.each_point():
                    tp = trans * p
                    pts.append([float(tp.x) * dbu, float(tp.y) * dbu])
            except Exception:
                pts = []

        # Fallback: derive a bbox if polygon point iteration isn't available.
        if not pts:
            try:
                bb = _maybe_call(getattr(shape, "bbox", None))
                if bb is not None:
                    bbt = bb.transformed(trans)
                    pts = [
                        [float(bbt.left) * dbu, float(bbt.bottom) * dbu],
                        [float(bbt.right) * dbu, float(bbt.bottom) * dbu],
                        [float(bbt.right) * dbu, float(bbt.top) * dbu],
                        [float(bbt.left) * dbu, float(bbt.top) * dbu],
                    ]
            except Exception:
                pts = []

        if pts:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            return "polygon", {"points_um": pts, "bbox_um": [min(xs), min(ys), max(xs), max(ys)]}
    except Exception:
        pass

    # Box
    try:
        if callable(getattr(shape, "is_box", None)) and shape.is_box():
            box = _maybe_call(getattr(shape, "box", None))
            if box is None:
                return None, None
            b = box.transformed(trans)
            pts = [
                [float(b.left) * dbu, float(b.bottom) * dbu],
                [float(b.right) * dbu, float(b.bottom) * dbu],
                [float(b.right) * dbu, float(b.top) * dbu],
                [float(b.left) * dbu, float(b.top) * dbu],
            ]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            return "box", {"points_um": pts, "bbox_um": [min(xs), min(ys), max(xs), max(ys)]}
    except Exception:
        pass

    # Path
    try:
        if callable(getattr(shape, "is_path", None)) and shape.is_path():
            path = _maybe_call(getattr(shape, "path", None))
            if path is None:
                return None, None

            pts = []
            # KLayout API varies a bit across versions; try multiple ways to get points.
            try:
                it = path.each_point()
                for p in it:
                    tp = trans * p
                    pts.append([float(tp.x) * dbu, float(tp.y) * dbu])
            except Exception:
                try:
                    n = int(_maybe_call(getattr(path, "num_points", None)) or 0)
                    for i in range(n):
                        p = _maybe_call(getattr(path, "point", None), i)
                        tp = trans * p
                        pts.append([float(tp.x) * dbu, float(tp.y) * dbu])
                except Exception:
                    pts = []

            if not pts:
                return None, None
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            width_um = float(_maybe_call(getattr(path, "width", None)) or 0.0) * dbu
            return "path", {"points_um": pts, "width_um": width_um, "bbox_um": [min(xs), min(ys), max(xs), max(ys)]}
    except Exception:
        pass

    return None, None


def _m_hier_shapes_rec(_id, params):
    """需求(新): 透過 begin_shapes_rec() 遞迴走訪 hierarchy shapes。

    參考腳本: get_shape_hier_path.py

    Params:
      start_cell: string (required)
      unit: "um" (optional, default "um")
      shape_types: ["polygon","box","path"] (optional, default all)
      layer_filter: int[] (optional) - layer index list
      max_results: int (optional, default 200000)

    Returns:
      {"shapes": [...], "unit": "um", "count": N, "truncated": bool}

    Shape record:
      {
        shape_type: "polygon"|"box"|"path",
        hierarchy_path: string[],
        layer_index: int,
        layer: {layer:int, datatype:int} | null,
        points_um: [[x,y],...],
        bbox_um: [x1,y1,x2,y2],
        width_um: number (path only),
        unit: "um"
      }

    NOTE:
      - begin_shapes_rec() 的 trans 是把 shape 轉到 start_cell 座標系。
      - unit 目前只支援 "um"（與參考腳本一致）。
    """
    err = _require_active_layout(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    start_cell = params.get("start_cell", None)
    unit = params.get("unit", "um")
    shape_types = params.get("shape_types", None)
    layer_filter = params.get("layer_filter", None)
    max_results = params.get("max_results", 200000)

    if not isinstance(start_cell, str) or not start_cell:
        return _err_std(_id, -32602, "Invalid params: start_cell must be non-empty string", "InvalidParams", {"field": "start_cell"})

    if unit != "um":
        return _err_std(_id, -32602, "Invalid params: unit must be 'um'", "InvalidParams", {"field": "unit", "got": unit})

    allowed_types = ("polygon", "box", "path")
    if shape_types is None:
        shape_types = list(allowed_types)
    if not (isinstance(shape_types, list) and all(isinstance(x, str) and x in allowed_types for x in shape_types)):
        return _err_std(
            _id,
            -32602,
            "Invalid params: shape_types must be a list of polygon|box|path",
            "InvalidParams",
            {"field": "shape_types", "allowed": list(allowed_types), "got": shape_types},
        )

    if layer_filter is not None:
        if not (isinstance(layer_filter, list) and all(isinstance(x, int) and x >= 0 for x in layer_filter)):
            return _err_std(_id, -32602, "Invalid params: layer_filter must be int[]", "InvalidParams", {"field": "layer_filter"})

    if not isinstance(max_results, int) or max_results < 1:
        return _err_std(_id, -32602, "Invalid params: max_results must be int >= 1", "InvalidParams", {"field": "max_results"})

    if not _STATE.layout.has_cell(start_cell):
        return _err(_id, -32002, f"Cell not found: {start_cell}", "CellNotFound", {"name": start_cell})

    cell = _STATE.layout.cell(start_cell)
    dbu = float(_STATE.layout.dbu)

    # default: all layers
    if layer_filter is None:
        try:
            layer_filter = list(range(int(_STATE.layout.layers())))
        except Exception:
            layer_filter = []
    layer_filter_set = set(int(x) for x in layer_filter)

    shapes_out = []
    truncated = False

    debug = bool(params.get("debug", False))
    dbg = {
        "seen": 0,
        "is_box": 0,
        "is_polygon": 0,
        "is_simple_polygon": 0,
        "is_path": 0,
    }

    # NOTE: Some KLayout builds require begin_shapes_rec(layer) argument.
    # We iterate per layer index for portability.
    try:
        for lyr in layer_filter:
            if len(shapes_out) >= max_results:
                truncated = True
                break

            try:
                # Prefer explicit RecursiveShapeIterator for better portability and inst_path support.
                it = pya.RecursiveShapeIterator(_STATE.layout, cell, int(lyr))
            except Exception:
                try:
                    it = cell.begin_shapes_rec(int(lyr))
                except Exception as e:
                    return _err(_id, -32099, f"Internal error: begin_shapes_rec({lyr}) failed: {e}", "InternalError")

            while not it.at_end():
                if len(shapes_out) >= max_results:
                    truncated = True
                    break

                layer_idx = int(lyr)

                shape = _maybe_call(getattr(it, "shape", None))
                trans = _maybe_call(getattr(it, "trans", None))
                inst_path = _maybe_call(getattr(it, "inst_path", None))

                if shape is None or trans is None:
                    it.next()
                    continue

                if debug:
                    dbg["seen"] += 1
                    try:
                        if callable(getattr(shape, "is_box", None)) and shape.is_box():
                            dbg["is_box"] += 1
                    except Exception:
                        pass
                    try:
                        if callable(getattr(shape, "is_polygon", None)) and shape.is_polygon():
                            dbg["is_polygon"] += 1
                    except Exception:
                        pass
                    try:
                        if callable(getattr(shape, "is_simple_polygon", None)) and shape.is_simple_polygon():
                            dbg["is_simple_polygon"] += 1
                    except Exception:
                        pass
                    try:
                        if callable(getattr(shape, "is_path", None)) and shape.is_path():
                            dbg["is_path"] += 1
                    except Exception:
                        pass

                kind, payload = _shape_points_um_and_bbox(shape, trans, dbu)
                if kind is None or kind not in shape_types:
                    it.next()
                    continue

                layer_info = None
                try:
                    li = _STATE.layout.get_info(layer_idx)
                    layer_info = {"layer": int(li.layer), "datatype": int(li.datatype)}
                except Exception:
                    layer_info = None

                hp = _inst_path_to_cell_names(inst_path)
                if not hp:
                    try:
                        hp2 = _hierarchy_path_from_iter(_STATE.layout, start_cell, it)
                        # drop the start cell prefix if present
                        if hp2 and hp2[0] == start_cell:
                            hp2 = hp2[1:]
                        hp = hp2
                    except Exception:
                        hp = []

                rec = {
                    "shape_type": kind,
                    "hierarchy_path": hp,
                    "layer_index": int(layer_idx),
                    "layer": layer_info,
                    "unit": "um",
                }
                rec.update(payload)

                shapes_out.append(rec)
                it.next()

    except Exception as e:
        return _err(_id, -32099, f"Internal error: shapes_rec iteration failed: {e}", "InternalError")

    out = {"shapes": shapes_out, "unit": "um", "count": int(len(shapes_out)), "truncated": bool(truncated)}
    if debug:
        out["debug"] = dbg
    return _jsonrpc_result(_id, out)


def _m_hier_query_up_paths(_id, params):
    """需求6-2: query parent paths (from the single top cell) to a target cell.

    Output format:
    - Returns paths as **segments** (list of strings), similar to filesystem
      components: [gds_filename, top_cell, ..., target_cell].

    Important constraints:
    - If the layout has multiple top cells, we return an error (per spec).

    Guardrail (IMPORTANT DESIGN NOTE):
    - The number of distinct paths can grow quickly with branching.
    - We enforce a max_paths limit (default 10000). If exceeded, we return
      TooManyResults with a clear message.

    Params:
      cell: string (required)
      max_paths: int (default 10000)
    """
    err = _require_active_layout(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    target = params.get("cell", None)
    max_paths = params.get("max_paths", 10000)

    if not isinstance(target, str) or not target:
        return _err_std(_id, -32602, "Invalid params: cell must be a non-empty string", "InvalidParams", {"field": "cell"})

    if not isinstance(max_paths, int) or max_paths < 1:
        return _err_std(_id, -32602, "Invalid params: max_paths must be int >= 1", "InvalidParams", {"field": "max_paths"})

    if not _STATE.layout.has_cell(target):
        return _err(_id, -32000, f"Cell not found: {target}", "CellNotFound", {"name": target})

    # Enforce single top cell
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

    top = tops[0]

    gds_name = _STATE.layout_filename if _STATE.layout_filename else "<in-memory>"

    paths = []

    def push_path(seg):
        if len(paths) >= max_paths:
            return _guardrail_too_many_results(
                _id,
                "paths",
                max_paths,
                len(paths) + 1,
                (
                    f"Too many results: hier.query_up_paths would return more than {max_paths} paths "
                    "(safety limit). Narrow the query or reduce max_paths."
                ),
                {"target": target, "method": "hier.query_up_paths"},
            )
        paths.append(seg)
        return None

    memo_reachable = {}

    def cell_key(cell):
        try:
            return int(cell.cell_index())
        except Exception:
            try:
                return int(cell.cell_index)
            except Exception:
                return id(cell)

    def dfs(cell_obj, segs, stack):
        """Depth-first traversal.

        Returns:
          (reachable, err)
          - reachable: bool, whether target is reachable from this node
          - err: JSON-RPC error object if we hit TooManyResults etc.

        NOTE: We return reachability explicitly so that path enumeration remains
        correct for deep targets (not just direct children).
        """
        ck = cell_key(cell_obj)
        if ck in stack:
            # Cycle protection (shouldn't happen in valid GDS hierarchy)
            return False, None

        if ck in memo_reachable:
            return bool(memo_reachable[ck]), None

        stack.add(ck)

        if cell_obj.name == target:
            err2 = push_path(list(segs))
            stack.remove(ck)
            if err2:
                return True, err2
            memo_reachable[ck] = True
            return True, None

        reachable = False

        try:
            it = cell_obj.each_inst()
        except Exception:
            it = []

        for inst in it:
            try:
                child = inst.cell
            except Exception:
                try:
                    child = inst.cell_()
                except Exception:
                    child = None
            if child is None:
                continue

            child_reach, err3 = dfs(child, segs + [child.name], stack)
            if err3:
                stack.remove(ck)
                return True, err3
            if child_reach:
                reachable = True

        stack.remove(ck)
        memo_reachable[ck] = bool(reachable)
        return bool(reachable), None

    reachable, err4 = dfs(top, [gds_name, top.name], set())
    if err4:
        return err4

    # reachable is not currently returned; paths list is the primary output.
    # It can be used later for fast "no-path" detection.

    return _jsonrpc_result(
        _id,
        {
            "cell": target,
            "max_paths": int(max_paths),
            "path_format": "segments",
            "paths": paths,
        },
    )



def _m_hier_query_down_stats(_id, params):
    """需求(新): query instance counts grouped by child_cell.

    This method returns statistics only (no instance list).

    Semantics:
      - Counts are EXPANDED (array instances count as nx*ny).
      - Grouping key is the child cell name (inst_cell.name).

    Params:
      cell: string (required)
      depth: int >= 0 (required)
      max_results: int (optional, default 20000000)
        - Guardrail on total counted instance elements.

    Returns:
      {
        root: string,
        depth: int,
        expanded: true,
        total: int,
        by_child_cell: { [cell_name]: count, ... },
        truncated: bool
      }

    Implementation:
      Uses RecursiveInstanceIterator (Cell.begin_instances_rec) which iterates
      instance *elements* (array members) and provides inst_cell/inst_trans.
    """
    err = _require_active_layout(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    root = params.get("cell", None)
    depth = params.get("depth", None)
    max_results = params.get("max_results", 20_000_000)

    if not isinstance(root, str) or not root:
        return _err_std(_id, -32602, "Invalid params: cell must be a non-empty string", "InvalidParams", {"field": "cell"})

    if not isinstance(depth, int) or depth < 0:
        return _err_std(_id, -32602, "Invalid params: depth must be int >= 0", "InvalidParams", {"field": "depth"})

    if not isinstance(max_results, int) or max_results < 1:
        return _err_std(_id, -32602, "Invalid params: max_results must be int >= 1", "InvalidParams", {"field": "max_results"})

    if not _STATE.layout.has_cell(root):
        return _err(_id, -32000, f"Cell not found: {root}", "CellNotFound", {"name": root})

    root_cell_obj = _STATE.layout.cell(root)

    by = {}
    total = 0
    truncated = False

    # If depth==0, there are no child instances.
    if depth == 0:
        return _jsonrpc_result(
            _id,
            {
                "root": root,
                "depth": int(depth),
                "expanded": True,
                "total": 0,
                "by_child_cell": {},
                "truncated": False,
            },
        )

    # Create recursive iterator
    itrec = None
    try:
        itrec = pya.RecursiveInstanceIterator(_STATE.layout, root_cell_obj)
    except Exception:
        itrec = None
    if itrec is None:
        try:
            itrec = root_cell_obj.begin_instances_rec()
        except Exception as e:
            return _err(_id, -32099, f"Internal error: begin_instances_rec failed: {e}", "InternalError")

    # Configure depth: iterator depth applies to the PARENT cell of delivered instances.
    try:
        itrec.min_depth = 0
        itrec.max_depth = max(0, int(depth) - 1)
    except Exception:
        pass

    try:
        while not itrec.at_end():
            c = _maybe_call(getattr(itrec, "inst_cell", None))
            if c is None:
                # Fallback: obtain instance then its cell
                inst = _maybe_call(getattr(itrec, "inst", None))
                if inst is None:
                    inst = _maybe_call(getattr(itrec, "instance", None))
                if inst is not None:
                    try:
                        c = inst.cell
                        if callable(c):
                            c = c()
                    except Exception:
                        try:
                            c = inst.cell_()
                        except Exception:
                            c = None

            if c is not None:
                try:
                    nm = str(_maybe_call(getattr(c, "name", None)) or "")
                except Exception:
                    nm = ""
                if nm:
                    by[nm] = int(by.get(nm, 0)) + 1
                    total += 1

            if total >= max_results:
                truncated = True
                break

            itrec.next()

    except Exception as e:
        return _err(_id, -32099, f"Internal error: hier.query_down_stats iteration failed: {e}", "InternalError")

    return _jsonrpc_result(
        _id,
        {
            "root": root,
            "depth": int(depth),
            "expanded": True,
            "total": int(total),
            "by_child_cell": by,
            "truncated": bool(truncated),
            "max_results": int(max_results),
        },
    )



def _m_hier_query_down(_id, params):
    """需求6-3: query instances downward from a given root cell.

    Modes:
    - structural: each Instance object (including arrays) is reported as ONE record.
    - expanded: regular arrays are expanded into per-element records.

    Bounding box:
    - bbox is computed as DEEP bbox (includes child hierarchy) over ALL layers.

    Result limiting (IMPORTANT DESIGN NOTE):
    - This API can easily produce huge outputs (deep hierarchies, arrays, etc.).
    - To keep the server responsive and avoid memory/time blowups, we enforce a
      hard maximum number of returned records. This is a "guardrail" design
      choice, not necessarily an indication that typical designs are risky.
    - If the limit would be exceeded, we return a clear TooManyResults error with
      a message that explains *what* safety limit was hit and *how* to mitigate.

    Params:
      cell: string (required)
      depth: int >= 0 (required)
      mode: "structural" | "expanded" (default: structural)
      include_bbox: bool (default: false)
        - If false, bbox is NOT computed and is not returned.
      max_results: int (default: 1000000)
        - Safety guardrail. If the number of records would exceed this value,
          returns TooManyResults.

      Backward-compat:
        - "limit" is accepted as an alias of max_results.
    """
    err = _require_active_layout(_id)
    if err:
        return err

    params, perr = _ensure_params_object(_id, params)
    if perr:
        return perr

    root = params.get("cell", None)
    depth = params.get("depth", None)
    mode = params.get("mode", "structural")
    engine = params.get("engine", "iterator")

    include_bbox = params.get("include_bbox", False)
    max_results = params.get("max_results", None)

    # Backward-compat alias
    if max_results is None and "limit" in params:
        max_results = params.get("limit")

    if not isinstance(root, str) or not root:
        return _err_std(_id, -32602, "Invalid params: cell must be a non-empty string", "InvalidParams", {"field": "cell"})

    if not isinstance(depth, int) or depth < 0:
        return _err_std(_id, -32602, "Invalid params: depth must be int >= 0", "InvalidParams", {"field": "depth"})

    if mode not in ("structural", "expanded"):
        return _err_std(
            _id,
            -32602,
            "Invalid params: mode must be 'structural' or 'expanded'",
            "InvalidParams",
            {"field": "mode", "allowed": ["structural", "expanded"], "got": mode},
        )

    if engine not in ("iterator", "dfs"):
        return _err_std(
            _id,
            -32602,
            "Invalid params: engine must be 'iterator' or 'dfs'",
            "InvalidParams",
            {"field": "engine", "allowed": ["iterator", "dfs"], "got": engine},
        )

    # mode='expanded' is supported (arrays expand into per-element records)

    if not isinstance(include_bbox, bool):
        return _err_std(
            _id,
            -32602,
            "Invalid params: include_bbox must be boolean",
            "InvalidParams",
            {"field": "include_bbox", "got": include_bbox},
        )

    if max_results is None:
        max_results = 1_000_000

    if not isinstance(max_results, int) or max_results < 1:
        return _err_std(
            _id,
            -32602,
            "Invalid params: max_results must be int >= 1",
            "InvalidParams",
            {"field": "max_results", "got": max_results},
        )

    if not _STATE.layout.has_cell(root):
        return _err(_id, -32000, f"Cell not found: {root}", "CellNotFound", {"name": root})

    results = []

    def push_record(rec):
        # Enforce result limit as a guardrail.
        if len(results) >= max_results:
            return _guardrail_too_many_results(
                _id,
                "instance_records",
                int(max_results),
                len(results) + 1,
                (
                    f"Too many results: hier.query_down would return more than {max_results} instance records "
                    "(safety limit). Reduce depth, switch to structural mode, or narrow the query."
                ),
                {
                    "depth": int(depth),
                    "mode": mode,
                    "root": root,
                    "method": "hier.query_down",
                    "include_bbox": bool(include_bbox),
                },
            )
        results.append(rec)
        return None

    def inst_kind_and_array(inst):
        # Detect regular array vs single instance using the underlying CellInstArray.
        try:
            cia = inst.cell_inst
        except Exception:
            try:
                cia = inst.cell_inst_()
            except Exception:
                cia = None

        if cia is None:
            return "single", None, None

        try:
            is_array = bool(cia.is_regular_array())
        except Exception:
            # KLayout Python should provide is_regular_array() method.
            is_array = False

        if not is_array:
            return "single", cia, None

        nx = int(getattr(cia, "na", 0))
        ny = int(getattr(cia, "nb", 0))

        try:
            a = cia.a
            b = cia.b
            ax, ay = int(a.x), int(a.y)
            bx, by = int(b.x), int(b.y)
        except Exception:
            ax = ay = bx = by = None

        arr = {"nx": nx, "ny": ny, "a": {"x": ax, "y": ay}, "b": {"x": bx, "y": by}}
        # Provide dx/dy when it matches our current simplified array model.
        if ay == 0 and bx == 0 and ax is not None and by is not None:
            arr["dx"] = ax
            arr["dy"] = by

        return "array", cia, arr

    def inst_trans(inst, cia):
        # Use CellInstArray#trans (first element) to get a simple Trans.
        try:
            t = cia.trans
        except Exception:
            try:
                t = inst.trans
            except Exception:
                t = None
        if t is None:
            return {"x": 0, "y": 0, "rot": 0, "mirror": False}
        return _trans_to_dict(t)

    def inst_bbox(inst):
        # Deep bbox over all layers.
        try:
            b = inst.bbox()
        except Exception:
            try:
                b = inst.bbox
            except Exception:
                b = None
        return b

    # Memoized deep bbox for child cells (used for expanded arrays)
    # Only used when include_bbox=true.
    _deep_bbox_memo = {}

    def deep_bbox_cell(cell_obj):
        """Compute a deep bbox (all layers) for a cell.

        Only used when include_bbox=true.
        We memoize per cell_index to keep expanded mode efficient.
        """
        try:
            key = int(cell_obj.cell_index())
        except Exception:
            key = id(cell_obj)

        if key in _deep_bbox_memo:
            return _deep_bbox_memo[key]

        # Start with the cell's own bbox.
        try:
            b = cell_obj.bbox()
        except Exception:
            try:
                b = cell_obj.bbox
            except Exception:
                b = None

        # Expand bbox with children's deep bboxes via instances.
        try:
            it = cell_obj.each_inst()
        except Exception:
            it = []

        for inst in it:
            try:
                child = inst.cell
            except Exception:
                try:
                    child = inst.cell_()
                except Exception:
                    child = None
            if child is None:
                continue

            kind, cia, _arr = inst_kind_and_array(inst)
            if cia is None:
                continue

            if kind == "single":
                t = cia.trans
                cb = deep_bbox_cell(child)
                if cb is not None:
                    try:
                        tb = cb.transformed(t)
                    except Exception:
                        tb = None
                    if tb is not None:
                        if b is None:
                            b = tb
                        else:
                            b = b + tb
            else:
                # For arrays, Instance#bbox already reports the overall extension
                # of the *array* in the parent cell, including hierarchy below the
                # child cell (deep). Using Instance#bbox here is both correct and
                # significantly faster than expanding the array.
                ib = inst_bbox(inst)
                if ib is not None:
                    if b is None:
                        b = ib
                    else:
                        b = b + ib

        _deep_bbox_memo[key] = b
        return b

    def _iter_inst_path_cells(itrec, root_name):
        """Return (path_cells, parent_cell_name, parent_depth).

        path_cells aims to match the existing DFS semantics: [root, ..., parent].

        For RecursiveInstanceIterator, we try:
          - itrec.cell (parent cell)
          - itrec.path (InstElement[] from initial cell to parent cell)
        """
        parent_cell_name = None
        try:
            c = _maybe_call(getattr(itrec, "cell", None))
            if c is not None:
                parent_cell_name = str(_maybe_call(getattr(c, "name", None)) or "")
        except Exception:
            parent_cell_name = None

        path_cells = [str(root_name)]

        try:
            path = _maybe_call(getattr(itrec, "path", None))
        except Exception:
            path = None

        # Best-effort parse InstElement[] -> cell names
        try:
            for el in path or []:
                nm = None
                c2 = _maybe_call(getattr(el, "cell", None))
                if c2 is not None:
                    nm = _maybe_call(getattr(c2, "name", None))
                if nm is None:
                    inst0 = _maybe_call(getattr(el, "inst", None))
                    if inst0 is not None:
                        cc0 = _maybe_call(getattr(inst0, "cell", None))
                        if cc0 is None:
                            cc0 = _maybe_call(getattr(inst0, "cell_", None))
                        if cc0 is not None:
                            nm = _maybe_call(getattr(cc0, "name", None))
                if nm is not None:
                    s = str(nm)
                    if s and (not path_cells or path_cells[-1] != s):
                        path_cells.append(s)
        except Exception:
            pass

        if parent_cell_name:
            if not path_cells or path_cells[-1] != parent_cell_name:
                path_cells.append(parent_cell_name)

        parent_depth = max(0, len(path_cells) - 1)
        return path_cells, parent_cell_name or str(path_cells[-1]), parent_depth

    def run_iterator_engine():
        root_cell_obj = _STATE.layout.cell(root)

        # Create recursive iterator
        itrec = None
        try:
            itrec = pya.RecursiveInstanceIterator(_STATE.layout, root_cell_obj)
        except Exception:
            itrec = None
        if itrec is None:
            try:
                itrec = root_cell_obj.begin_instances_rec()
            except Exception as e:
                return _err(_id, -32099, f"Internal error: begin_instances_rec failed: {e}", "InternalError")

        # Configure depth on iterator (depth counts instance-edges from root; parent depth = depth-1)
        try:
            itrec.min_depth = 0
            itrec.max_depth = max(0, int(depth) - 1)
        except Exception:
            pass

        seen_array_instances = set()

        try:
            while not itrec.at_end():
                el = _maybe_call(getattr(itrec, "current_inst_element", None))
                inst = None
                if el is not None:
                    inst = _maybe_call(getattr(el, "inst", None))
                if inst is None:
                    # Fallbacks
                    inst = _maybe_call(getattr(itrec, "inst", None))
                    if inst is None:
                        inst = _maybe_call(getattr(itrec, "instance", None))

                if inst is None:
                    itrec.next()
                    continue

                # Parent cell
                path_cells, parent_cell_name, parent_depth = _iter_inst_path_cells(itrec, root)

                # Child cell (target cell)
                child_cell = _maybe_call(getattr(itrec, "inst_cell", None))
                if child_cell is None:
                    try:
                        child_cell = inst.cell
                        if callable(child_cell):
                            child_cell = child_cell()
                    except Exception:
                        try:
                            child_cell = inst.cell_()
                        except Exception:
                            child_cell = None

                if child_cell is None:
                    itrec.next()
                    continue

                kind, cia, arr = inst_kind_and_array(inst)

                # Expanded mode: each iterator step corresponds to one physical instance element.
                # We always return kind='single' records (matching existing expanded mode output).
                t = _maybe_call(getattr(itrec, "inst_trans", None))
                tdict = _trans_to_dict(t) if t is not None else (inst_trans(inst, cia) if cia is not None else {"x": 0, "y": 0, "rot": 0, "mirror": False})

                expanded_index = None
                if el is not None and arr is not None:
                    try:
                        # InstElement provides ia/ib for array members.
                        expanded_index = {"ix": int(_maybe_call(getattr(el, "ia", None)) or 0), "iy": int(_maybe_call(getattr(el, "ib", None)) or 0)}
                    except Exception:
                        expanded_index = None

                rec = {
                    "kind": "single",
                    "parent_cell": parent_cell_name,
                    "child_cell": child_cell.name,
                    "trans": tdict,
                    "array": arr,
                    "path": list(path_cells),
                }
                if expanded_index is not None:
                    rec["expanded_index"] = expanded_index

                if include_bbox:
                    bbox_elem = None
                    try:
                        cb = deep_bbox_cell(child_cell)
                        if cb is not None and t is not None:
                            bbox_elem = cb.transformed(t)
                    except Exception:
                        bbox_elem = None
                    rec["bbox"] = _box_to_dict(bbox_elem)

                err2 = push_record(rec)
                if err2:
                    return err2

                itrec.next()

        except Exception as e:
            return _err(_id, -32099, f"Internal error: hier.query_down iteration failed: {e}", "InternalError")

        return None

    def dfs(cell_obj, depth_left, path_cells):
        if depth_left <= 0:
            return None
        try:
            it = cell_obj.each_inst()
        except Exception as e:
            return _err(_id, -32099, f"Internal error: {e}", "InternalError")

        for inst in it:
            try:
                child_cell = inst.cell
            except Exception:
                try:
                    child_cell = inst.cell_()
                except Exception:
                    child_cell = None

            if child_cell is None:
                continue

            kind, cia, arr = inst_kind_and_array(inst)

            if mode == "structural" or kind == "single":
                tdict = inst_trans(inst, cia) if cia is not None else {"x": 0, "y": 0, "rot": 0, "mirror": False}

                rec = {
                    "kind": kind,
                    "parent_cell": cell_obj.name,
                    "child_cell": child_cell.name,
                    "trans": tdict,
                    "array": arr,
                    "path": list(path_cells),
                }

                if include_bbox:
                    rec["bbox"] = _box_to_dict(inst_bbox(inst))

                err2 = push_record(rec)
                if err2:
                    return err2

            else:
                # Expanded mode: expand regular arrays to per-element records.
                # For each element we compute:
                # - element Trans = base trans + ix*a + iy*b
                # - element bbox = deep_bbox(child_cell).transformed(element_trans)
                #
                # NOTE: bbox is optional. If include_bbox=false, we skip all bbox
                # computations for speed.
                cb = None
                if include_bbox:
                    cb = deep_bbox_cell(child_cell)

                try:
                    base_t = cia.trans
                except Exception:
                    base_t = None

                a = cia.a
                b = cia.b
                nx = int(cia.na)
                ny = int(cia.nb)

                for iy in range(ny):
                    for ix in range(nx):
                        dx = int(a.x) * ix + int(b.x) * iy
                        dy = int(a.y) * ix + int(b.y) * iy

                        if base_t is None:
                            t_elem = pya.Trans(0, False, dx, dy)
                        else:
                            # Create from base + additional displacement.
                            t_elem = pya.Trans(base_t, dx, dy)

                        bbox_elem = None
                        if include_bbox and cb is not None:
                            try:
                                bbox_elem = cb.transformed(t_elem)
                            except Exception:
                                bbox_elem = None

                        # In expanded mode, each returned record represents ONE
                        # physical element of the original array instance.
                        # - kind='single' means this record is a single element.
                        # - array field carries the *origin array instance* metadata.
                        rec = {
                            "kind": "single",
                            "parent_cell": cell_obj.name,
                            "child_cell": child_cell.name,
                            "trans": _trans_to_dict(t_elem),
                            "array": arr,
                            "expanded_index": {"ix": int(ix), "iy": int(iy)},
                            "path": list(path_cells),
                        }
                        if include_bbox:
                            rec["bbox"] = _box_to_dict(bbox_elem)

                        err2 = push_record(rec)
                        if err2:
                            return err2

            # Recurse
            err3 = dfs(child_cell, depth_left - 1, path_cells + [child_cell.name])
            if err3:
                return err3

        return None

    # Engine selection: prefer official iterator, with fallback to DFS on iterator InternalError.
    err4 = None

    if engine == "iterator" and mode == "expanded":
        err4 = run_iterator_engine()
        if err4:
            # Only fall back on iterator-specific internal failures.
            et = None
            try:
                et = (err4.get("error", {}) or {}).get("data", {}).get("type")
            except Exception:
                et = None
            if et == "InternalError":
                root_cell_obj = _STATE.layout.cell(root)
                err4 = dfs(root_cell_obj, depth, [root])

    else:
        # DFS engine is used for:
        # - engine='dfs'
        # - engine='iterator' + mode='structural' (avoid per-array-element iteration blowup)
        root_cell_obj = _STATE.layout.cell(root)
        err4 = dfs(root_cell_obj, depth, [root])

    if err4:
        return err4

    def _sort_key(rec):
        # Stable ordering for diffs/tests.
        t = rec.get("trans") or {}
        ei = rec.get("expanded_index") or {}
        return (
            str(rec.get("parent_cell", "")),
            str(rec.get("child_cell", "")),
            str(rec.get("kind", "")),
            int(t.get("x", 0) or 0),
            int(t.get("y", 0) or 0),
            int(t.get("rot", 0) or 0),
            bool(t.get("mirror", False)),
            int(ei.get("ix", -1) or -1),
            int(ei.get("iy", -1) or -1),
        )

    results.sort(key=_sort_key)

    return _jsonrpc_result(
        _id,
        {
            "root": root,
            "depth": int(depth),
            "mode": mode,
            "include_bbox": bool(include_bbox),
            "max_results": int(max_results),
            # Backward-compat echo (deprecated)
            "limit": int(max_results),
            "dbu": float(_STATE.layout.dbu),
            "instances": results,
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

    _gui_refresh("instance.create")

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

    _gui_refresh("instance_array.create")

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
        "view.screenshot": _m_view_screenshot,
        "view.ensure": _m_view_ensure,
        "view.set_viewport": _m_view_set_viewport,
        "view.set_hier_levels": _m_view_set_hier_levels,
        "layout.render_png": _m_layout_render_png,
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

        "hier.query_down": _m_hier_query_down,
        "hier.query_down_stats": _m_hier_query_down_stats,
        "hier.query_up_paths": _m_hier_query_up_paths,
        "hier.shapes_rec": _m_hier_shapes_rec,
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
