#!/usr/bin/env bash
set -euo pipefail

# Run all integration tests against the KLayout JSON-RPC server.
#
# This script starts/stops the KLayout macro server per test to avoid
# cross-test contamination (req3 tests assume fresh state).
#
# Usage:
#   ./run_all_tests.sh [--port 5055] [--klayout /path/to/klayout]
#
# Environment overrides:
#   KLAYOUT_BIN         path to klayout binary
#   KLAYOUT_HOME        directory that contains KLayout libs (for LD_LIBRARY_PATH)
#   KLAYOUT_SERVER_PORT port to bind

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="5055"

KLAYOUT_BIN_DEFAULT="/home/istale/klayout-build/0.30.5-qt5/klayout"
KLAYOUT_HOME_DEFAULT="/home/istale/klayout-build/0.30.5-qt5"

KLAYOUT_BIN="${KLAYOUT_BIN:-$KLAYOUT_BIN_DEFAULT}"
KLAYOUT_HOME="${KLAYOUT_HOME:-$KLAYOUT_HOME_DEFAULT}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      PORT="$2"; shift 2;;
    --klayout)
      KLAYOUT_BIN="$2"; shift 2;;
    -h|--help)
      sed -n '1,120p' "$0"; exit 0;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2;;
  esac
done

export LD_LIBRARY_PATH="$KLAYOUT_HOME${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

start_server() {
  echo "[run_all_tests] starting server on port $PORT"
  # Start in background. We expect to kill it after a test.
  (cd "$ROOT_DIR" && KLAYOUT_SERVER_PORT="$PORT" "$KLAYOUT_BIN" -e -rm klayout_gui_tcp_server.py) &
  SERVER_PID=$!

  # Wait until port is accepting connections.
  python3 - <<'PY'
import socket, os, time, sys
port = int(os.environ.get('KLAYOUT_SERVER_PORT','5055'))
deadline = time.time() + 5.0
while time.time() < deadline:
    try:
        s = socket.create_connection(('127.0.0.1', port), timeout=0.2)
        s.close()
        sys.exit(0)
    except Exception:
        time.sleep(0.1)
print('server did not become ready in time', file=sys.stderr)
sys.exit(1)
PY
}

stop_server() {
  if [[ -n "${SERVER_PID:-}" ]]; then
    echo "[run_all_tests] stopping server pid=$SERVER_PID"

    # Try graceful stop first.
    kill "$SERVER_PID" 2>/dev/null || true

    # Wait up to ~2s for exit.
    for _ in {1..20}; do
      if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        unset SERVER_PID
        return 0
      fi
      sleep 0.1
    done

    # Force kill if still alive.
    kill -9 "$SERVER_PID" 2>/dev/null || true

    for _ in {1..20}; do
      if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        unset SERVER_PID
        return 0
      fi
      sleep 0.1
    done

    echo "[run_all_tests] WARN: server pid still alive after SIGKILL: $SERVER_PID" >&2
    unset SERVER_PID
  fi
}

run_one() {
  local test_py="$1"
  echo "[run_all_tests] === $test_py ==="
  start_server
  (cd "$ROOT_DIR" && python3 "$test_py" "$PORT")
  stop_server
}

trap stop_server EXIT

# Order: spec v0 first, then req3 tests.
run_one test_client_jsonrpc_spec_v0.py
run_one test_client_jsonrpc_req3_cell_create.py
run_one test_client_jsonrpc_req3_instance_create.py
run_one test_client_jsonrpc_req3_instance_array_create.py
run_one test_client_jsonrpc_req4_generate_export_open.py
run_one test_client_jsonrpc_req5_layout_info.py
run_one test_client_jsonrpc_req6_hier_query_down.py
run_one test_client_jsonrpc_req6_hier_query_down_deep.py
run_one test_client_jsonrpc_req6_hier_query_up_paths.py
run_one test_client_jsonrpc_req6_hier_query_down_expanded.py
run_one test_client_jsonrpc_req7_view_screenshot.py
run_one test_client_jsonrpc_req7_view_set_viewport.py
run_one test_client_jsonrpc_req7_layout_render_png.py
run_one test_client_jsonrpc_hier_shapes_rec_begin.py

echo "[run_all_tests] ALL OK"
