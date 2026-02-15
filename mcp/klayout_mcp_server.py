"""KLayout MCP Server (v0) - Model Context Protocol server for KLayout.

This server exposes MCP tools (stdio transport) that proxy to KLayout's JSON-RPC server.

Usage (stdio MCP server for Cline/Cursor/etc):
    python3 mcp/klayout_mcp_server.py

You can also import this module and call the helper functions directly
(see mcp_selftest.py).

Environment:
    KLAYOUT_ENDPOINT: Override endpoint (e.g., "127.0.0.1:5055")
    KLAYOUT_PROJECT_DIR: Target project directory (default: cwd)
    KLAYOUT_SERVER_REGISTRY_PATH: Override registry path
    KLAYOUT_MCP_TRACES_DIR: Traces output directory (default: ./traces)
    KLAYOUT_MCP_ARTIFACTS_DIR: Artifacts output directory (default: ./artifacts)
"""

import json
import os
import socket
import getpass
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

TRACES_DIR = Path(os.environ.get("KLAYOUT_MCP_TRACES_DIR", "./traces"))
ARTIFACTS_DIR = Path(os.environ.get("KLAYOUT_MCP_ARTIFACTS_DIR", "./artifacts"))


# Ensure directories exist
def _ensure_dirs():
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


# -----------------------------------------------------------------------------
# Global lock for single in-flight RPC
# -----------------------------------------------------------------------------

_RPC_LOCK = threading.Lock()


# -----------------------------------------------------------------------------
# Registry resolution
# -----------------------------------------------------------------------------


def _get_registry_path() -> str:
    """Get registry path from env or default."""
    return os.environ.get(
        "KLAYOUT_SERVER_REGISTRY_PATH",
        os.path.expanduser("~/.klayout/klayout_server_registry.jsonl"),
    )


def _read_registry_entries(registry_path: str) -> List[Dict[str, Any]]:
    """Read registry entries, skipping malformed lines."""
    entries = []
    if not os.path.exists(registry_path):
        return entries

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    # Validate required fields
                    if all(
                        k in entry
                        for k in ("ts_utc", "user", "pid", "port", "project_dir")
                    ):
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"[MCP] WARN: could not read registry: {e}")

    return entries


def _is_pid_alive(pid: int) -> bool:
    """Check if a process is alive (POSIX)."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _ping_endpoint(host: str, port: int, timeout: float = 2.0) -> bool:
    """Ping an endpoint to check if it's alive."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        try:
            # Send ping
            req = json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
            )
            sock.sendall((req + "\n").encode("utf-8"))

            # Receive response
            sock.settimeout(timeout)
            response = b""
            while b"\n" not in response:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk

            if b"\n" in response:
                line = response.split(b"\n", 1)[0]
                resp = json.loads(line.decode("utf-8"))
                result = resp.get("result", {})
                return result.get("pong", False)
        finally:
            sock.close()
    except Exception:
        pass
    return False


def _resolve_endpoint() -> Tuple[str, int, Optional[Dict[str, Any]]]:
    """Resolve KLayout endpoint.

    Order:
    1) KLAYOUT_ENDPOINT env var
    2) Registry lookup: match user + realpath(project_dir), newest first, ping each

    Returns: (host, port, registry_match) or raises RuntimeError
    """
    # 1) Check KLAYOUT_ENDPOINT override
    endpoint_env = os.environ.get("KLAYOUT_ENDPOINT")
    if endpoint_env:
        try:
            host, port_str = endpoint_env.rsplit(":", 1)
            return host, int(port_str), None
        except ValueError:
            raise RuntimeError(f"Invalid KLAYOUT_ENDPOINT format: {endpoint_env}")

    # 2) Registry lookup
    registry_path = _get_registry_path()
    entries = _read_registry_entries(registry_path)

    if not entries:
        raise RuntimeError(
            f"No registry entries found. "
            f"Start KLayout server first or set KLAYOUT_ENDPOINT."
        )

    # Get target project dir
    project_dir = os.environ.get("KLAYOUT_PROJECT_DIR", os.getcwd())
    project_dir_real = os.path.realpath(project_dir)
    current_user = getpass.getuser()

    # Filter by user and project_dir, sort by ts_utc desc
    candidates = []
    for entry in entries:
        if entry.get("user") != current_user:
            continue
        entry_project_real = os.path.realpath(entry.get("project_dir", ""))
        if entry_project_real != project_dir_real:
            continue
        candidates.append(entry)

    # Sort by ts_utc descending (newest first)
    candidates.sort(key=lambda e: e.get("ts_utc", ""), reverse=True)

    # Try each candidate
    for entry in candidates:
        pid = entry.get("pid")
        port = entry.get("port")

        # Skip stale entries (optional check)
        if pid and not _is_pid_alive(pid):
            print(f"[MCP] Skipping stale entry (pid {pid} not alive)")
            continue

        # Ping test
        if _ping_endpoint("127.0.0.1", port):
            return "127.0.0.1", port, entry

    raise RuntimeError(
        f"No available KLayout endpoint found for user={current_user}, "
        f"project_dir={project_dir_real}. "
        f"Check that KLayout server is running and registered."
    )


# -----------------------------------------------------------------------------
# JSON-RPC client
# -----------------------------------------------------------------------------


def _jsonrpc_call(
    host: str, port: int, method: str, params: Dict[str, Any]
) -> Tuple[Dict[str, Any], float]:
    """Make a JSON-RPC call and return (result_or_error, duration_ms)."""
    start_time = time.time()

    sock = socket.create_connection((host, port), timeout=30.0)
    try:
        # Send request
        req = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        sock.sendall((json.dumps(req, separators=(",", ":")) + "\n").encode("utf-8"))

        # Receive response
        sock.settimeout(30.0)
        response = b""
        while b"\n" not in response:
            chunk = sock.recv(65536)
            if not chunk:
                break
            response += chunk

        if b"\n" not in response:
            raise RuntimeError("Incomplete response from server")

        line = response.split(b"\n", 1)[0]
        resp = json.loads(line.decode("utf-8"))

        duration_ms = (time.time() - start_time) * 1000
        return resp, duration_ms
    finally:
        sock.close()


# -----------------------------------------------------------------------------
# Trace recording
# -----------------------------------------------------------------------------

_trace_file_path: Optional[Path] = None


def _init_trace_file():
    """Initialize trace file for this run."""
    global _trace_file_path
    _ensure_dirs()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    shortid = os.urandom(4).hex()
    _trace_file_path = TRACES_DIR / f"run_{ts}_{shortid}.jsonl"


def _write_trace(
    tool: str,
    endpoint: str,
    project_dir: str,
    registry_match: Optional[Dict],
    mcp_params: Dict,
    rpc_request: Dict,
    rpc_response: Dict,
    duration_ms: float,
    artifacts: List[Dict],
):
    """Write a trace entry."""
    if _trace_file_path is None:
        _init_trace_file()

    entry = {
        "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": _trace_file_path.stem,
        "tool": tool,
        "endpoint": endpoint,
        "project_dir_realpath": os.path.realpath(project_dir),
        "registry_match": registry_match,
        "mcp_params": mcp_params,
        "rpc_request": rpc_request,
        "rpc_response": rpc_response,
        "duration_ms": round(duration_ms, 2),
        "artifacts": artifacts,
    }

    try:
        with open(_trace_file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    except Exception as e:
        print(f"[MCP] WARN: could not write trace: {e}")


# -----------------------------------------------------------------------------
# MCP Tool implementations
# -----------------------------------------------------------------------------


def _generate_artifact_path(kind: str, ext: str) -> str:
    """Generate a default artifact path."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"artifacts/{kind}_{ts}.{ext}"


def _call_tool(
    tool_name: str,
    rpc_method: str,
    mcp_params: Dict[str, Any],
    path_param: Optional[str] = None,
    path_ext: Optional[str] = None,
) -> Dict[str, Any]:
    """Generic tool caller with trace recording."""
    with _RPC_LOCK:
        # Resolve endpoint
        host, port, registry_match = _resolve_endpoint()
        endpoint = f"{host}:{port}"

        # Auto-generate path if needed
        if path_param and path_ext:
            if path_param not in mcp_params or mcp_params.get(path_param) is None:
                mcp_params[path_param] = _generate_artifact_path(
                    rpc_method.replace(".", "_")
                    .replace("layout_", "")
                    .replace("view_", ""),
                    path_ext,
                )

        # Build RPC params (copy to avoid modifying original)
        rpc_params = dict(mcp_params)

        # Make RPC call
        try:
            resp, duration_ms = _jsonrpc_call(host, port, rpc_method, rpc_params)
        except Exception as e:
            duration_ms = 0
            resp = {
                "error": {
                    "code": -32099,
                    "message": f"RPC call failed: {e}",
                    "data": {"type": "RpcCallFailed"},
                }
            }

        # Extract artifacts
        artifacts = []
        if path_param and path_param in rpc_params:
            path = rpc_params[path_param]
            result = resp.get("result", {})
            if result.get("written", False):
                artifacts.append({"kind": rpc_method.replace(".", "_"), "path": path})

        # Write trace
        project_dir = os.environ.get("KLAYOUT_PROJECT_DIR", os.getcwd())
        _write_trace(
            tool=tool_name,
            endpoint=endpoint,
            project_dir=project_dir,
            registry_match=registry_match,
            mcp_params=mcp_params,
            rpc_request={"id": 1, "method": rpc_method, "params": rpc_params},
            rpc_response=resp,
            duration_ms=duration_ms,
            artifacts=artifacts,
        )

        # Build response envelope
        result = resp.get("result")
        error = resp.get("error")

        if error:
            # Check for specific error types
            error_type = error.get("data", {}).get("type", "")
            suggestion = ""
            if error_type == "NoCurrentView" or error_type == "MainWindowUnavailable":
                suggestion = " Try using layout.render_png as fallback (headless)."

            return {
                "ok": False,
                "endpoint": endpoint,
                "duration_ms": round(duration_ms, 2),
                "error": error,
                "suggestion": suggestion,
            }

        return {
            "ok": True,
            "endpoint": endpoint,
            "duration_ms": round(duration_ms, 2),
            "result": result,
            "artifacts": artifacts,
        }


# MCP Tools


def klayout_ping() -> Dict[str, Any]:
    """Ping the KLayout server."""
    return _call_tool("klayout_ping", "ping", {})


def klayout_layout_new(
    dbu: float = 0.0005, top_cell: str = "TOP", clear_previous: bool = True
) -> Dict[str, Any]:
    """Create a new layout."""
    return _call_tool(
        "klayout_layout_new",
        "layout.new",
        {"dbu": dbu, "top_cell": top_cell, "clear_previous": clear_previous},
    )


def klayout_layer_new(
    layer: int = 1,
    datatype: int = 0,
    name: Optional[str] = None,
    as_current: bool = True,
) -> Dict[str, Any]:
    """Create or get a layer."""
    params = {"layer": layer, "datatype": datatype, "as_current": as_current}
    if name is not None:
        params["name"] = name
    return _call_tool("klayout_layer_new", "layer.new", params)


def klayout_shape_create(
    cell: str = "TOP",
    type: str = "box",
    coords: List = None,
    units: str = "dbu",
    layer_index: Optional[int] = None,
    layer: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Create a shape in a cell."""
    params = {"cell": cell, "type": type, "units": units}
    if coords is not None:
        params["coords"] = coords
    if layer_index is not None:
        params["layer_index"] = layer_index
    if layer is not None:
        params["layer"] = layer
    return _call_tool("klayout_shape_create", "shape.create", params)


def klayout_view_ensure(zoom_fit: bool = False) -> Dict[str, Any]:
    """Ensure a GUI view exists."""
    return _call_tool("klayout_view_ensure", "view.ensure", {"zoom_fit": zoom_fit})


def klayout_view_screenshot(
    path: Optional[str] = None,
    width: int = 1200,
    height: int = 800,
    viewport_mode: str = "fit",
    **kwargs,
) -> Dict[str, Any]:
    """Take a screenshot of the current view."""
    params = {
        "path": path,
        "width": width,
        "height": height,
        "viewport_mode": viewport_mode,
        **kwargs,
    }
    result = _call_tool(
        "klayout_view_screenshot", "view.screenshot", params, "path", "png"
    )

    # Suggest fallback on GUI errors
    if not result.get("ok"):
        error = result.get("error", {})
        error_type = error.get("data", {}).get("type", "")
        if error_type in ("NoCurrentView", "MainWindowUnavailable"):
            result["fallback_suggestion"] = (
                "GUI view not available. Use klayout_layout_render_png for headless rendering."
            )

    return result


def klayout_layout_export(
    path: Optional[str] = None, overwrite: bool = True
) -> Dict[str, Any]:
    """Export the current layout to GDS."""
    params = {"path": path, "overwrite": overwrite}
    return _call_tool("klayout_layout_export", "layout.export", params, "path", "gds")


def klayout_layout_render_png(
    path: Optional[str] = None,
    width: int = 1200,
    height: int = 800,
    viewport_mode: str = "fit",
    **kwargs,
) -> Dict[str, Any]:
    """Render the layout to PNG (headless-friendly)."""
    params = {
        "path": path,
        "width": width,
        "height": height,
        "viewport_mode": viewport_mode,
        **kwargs,
    }
    return _call_tool(
        "klayout_layout_render_png", "layout.render_png", params, "path", "png"
    )


# -----------------------------------------------------------------------------
# MCP Server setup (stdio mode)
# -----------------------------------------------------------------------------


def _send_mcp_message(msg: Dict):
    """Send MCP message to stdout."""
    print(json.dumps(msg), flush=True)


def _handle_mcp_request(req: Dict) -> Optional[Dict]:
    """Handle an MCP request."""
    method = req.get("method")
    _id = req.get("id")
    params = req.get("params", {})

    # Initialize
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": _id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "klayout-mcp-server", "version": "0.1.0"},
                "capabilities": {"tools": {}, "resources": {}},
            },
        }

    # tools/list
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": _id,
            "result": {
                "tools": [
                    {
                        "name": "ping",
                        "description": "Ping the KLayout server",
                        "inputSchema": {"type": "object", "additionalProperties": false},
                    },
                    {
                        "name": "layout_new",
                        "description": "Create a new layout",
                        "inputSchema": {
                            "type": "object",
                            "additionalProperties": false,
                            "properties": {
                                "dbu": {"type": "number", "default": 0.0005},
                                "top_cell": {"type": "string", "default": "TOP"},
                                "clear_previous": {"type": "boolean", "default": True}
                            }
                        }
                    },
                    {
                        "name": "layer_new",
                        "description": "Create or get a layer (layer/datatype pair)",
                        "inputSchema": {
                            "type": "object",
                            "additionalProperties": false,
                            "properties": {
                                "layer": {"type": "integer"},
                                "datatype": {"type": "integer", "default": 0},
                                "name": {"type": "string"},
                                "as_current": {"type": "boolean", "default": True}
                            },
                            "required": ["layer"]
                        }
                    },
                    {
                        "name": "shape_create",
                        "description": "Create a shape in a cell",
                        "inputSchema": {
                            "type": "object",
                            "additionalProperties": false,
                            "properties": {
                                "cell": {"type": "string", "default": "TOP"},
                                "type": {"type": "string", "default": "box"},
                                "coords": {"type": "array"},
                                "units": {"type": "string", "default": "dbu"},
                                "layer_index": {"type": "integer"},
                                "layer": {"type": "object"}
                            },
                            "required": ["coords"]
                        }
                    },
                    {
                        "name": "view_ensure",
                        "description": "Ensure a GUI view exists",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "zoom_fit": {"type": "boolean", "default": False}
                            },
                        },
                    },
                    {
                        "name": "view_screenshot",
                        "description": "Take a screenshot of the current view",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "width": {"type": "integer", "default": 1200},
                                "height": {"type": "integer", "default": 800},
                                "viewport_mode": {"type": "string", "default": "fit"},
                            },
                        },
                    },
                    {
                        "name": "layout_export",
                        "description": "Export the current layout to GDS",
                        "inputSchema": {
                            "type": "object",
                            "additionalProperties": false,
                            "properties": {
                                "path": {"type": "string"},
                                "overwrite": {"type": "boolean", "default": True}
                            },
                            "required": ["path"]
                        }
                    },
                    {
                        "name": "layout_render_png",
                        "description": "Render the layout to PNG (headless-friendly)",
                        "inputSchema": {
                            "type": "object",
                            "additionalProperties": false,
                            "properties": {
                                "path": {"type": "string"},
                                "width": {"type": "integer", "default": 1200},
                                "height": {"type": "integer", "default": 800},
                                "viewport_mode": {"type": "string", "default": "fit"}
                            },
                            "required": ["path"]
                        }
                    },
                ]
            },
        }

    # resources/list
    if method == "resources/list":
        tools_root = Path(os.environ.get("KLAYOUT_PROJECT_DIR", os.getcwd()))
        items = []
        for rel in ("docs/API.md", "docs/MCP_SPEC.md"):
            p = tools_root / rel
            if p.exists():
                items.append(
                    {
                        "uri": f"file://{p}",
                        "name": rel,
                        "mimeType": "text/markdown",
                    }
                )
        return {"jsonrpc": "2.0", "id": _id, "result": {"resources": items}}

    # resources/read
    if method == "resources/read":
        uri = params.get("uri", "")
        if uri.startswith("file://"):
            file_path = uri[len("file://") :]
            try:
                text = Path(file_path).read_text(encoding="utf-8")
                return {
                    "jsonrpc": "2.0",
                    "id": _id,
                    "result": {
                        "contents": [
                            {
                                "uri": uri,
                                "mimeType": "text/markdown",
                                "text": text,
                            }
                        ]
                    },
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": _id,
                    "error": {"code": -32001, "message": f"resources/read failed: {e}"},
                }
        return {"jsonrpc": "2.0", "id": _id, "error": {"code": -32602, "message": "Invalid uri"}}

    # tools/call
    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_params = params.get("arguments", {})

        # Support both short tool names (recommended) and legacy-prefixed names.
        tools_map = {
            # Recommended short names (Cline tends to call these)
            "ping": klayout_ping,
            "layout_new": klayout_layout_new,
            "layer_new": klayout_layer_new,
            "shape_create": klayout_shape_create,
            "view_ensure": klayout_view_ensure,
            "view_screenshot": klayout_view_screenshot,
            "layout_export": klayout_layout_export,
            "layout_render_png": klayout_layout_render_png,
            # Legacy-prefixed names
            "klayout_ping": klayout_ping,
            "klayout_layout_new": klayout_layout_new,
            "klayout_layer_new": klayout_layer_new,
            "klayout_shape_create": klayout_shape_create,
            "klayout_view_ensure": klayout_view_ensure,
            "klayout_view_screenshot": klayout_view_screenshot,
            "klayout_layout_export": klayout_layout_export,
            "klayout_layout_render_png": klayout_layout_render_png,
        }

        if tool_name not in tools_map:
            return {
                "jsonrpc": "2.0",
                "id": _id,
                "error": {"code": -32601, "message": f"Tool not found: {tool_name}"},
            }

        try:
            result = tools_map[tool_name](**tool_params)
            return {
                "jsonrpc": "2.0",
                "id": _id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, indent=2)}]
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": _id,
                "error": {"code": -32099, "message": f"Tool execution failed: {e}"},
            }

    # notifications (no response)
    if method in ("initialized", "$/cancelRequest"):
        return None

    # Unknown method
    return {
        "jsonrpc": "2.0",
        "id": _id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def run_server():
    """Run the MCP server (stdio mode)."""
    import sys

    print("[MCP] KLayout MCP Server starting...", file=sys.stderr)
    _ensure_dirs()
    _init_trace_file()
    print(f"[MCP] Traces: {_trace_file_path}", file=sys.stderr)
    print(f"[MCP] Artifacts: {ARTIFACTS_DIR}", file=sys.stderr)

    # Test endpoint resolution
    try:
        host, port, _ = _resolve_endpoint()
        print(f"[MCP] Connected to KLayout at {host}:{port}", file=sys.stderr)
    except RuntimeError as e:
        print(f"[MCP] WARN: {e}", file=sys.stderr)

    print("[MCP] Ready for MCP requests", file=sys.stderr)

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break

            req = json.loads(line.strip())
            resp = _handle_mcp_request(req)
            if resp is not None:
                _send_mcp_message(resp)
        except json.JSONDecodeError as e:
            _send_mcp_message(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": f"Parse error: {e}"},
                }
            )
        except Exception as e:
            print(f"[MCP] Error: {e}", file=sys.stderr)


if __name__ == "__main__":
    import sys

    run_server()
