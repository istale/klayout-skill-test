# klayout_skill_test – GUI TCP server smoke test

## Goal
Validate that a **KLayout Python macro** can host a **TCP server** (localhost only) and respond to a simple request.

## Files
- `klayout_gui_tcp_server.py`: KLayout macro. Starts a TCP server on 127.0.0.1. By default it uses an OS-assigned port; you can also force a port via env `KLAYOUT_SERVER_PORT`.
- `test_client_ping.py`: external client test. Sends `ping\n`, expects `pong\n`.

## Run (GUI)
1) Open KLayout GUI (executable: `/home/istale/klayout-build/0.30.5-qt5/klayout`)
2) Macro IDE → Python → run `klayout_gui_tcp_server.py`
3) In the macro console, note the printed port line:
   - `[klayout-gui-server] PORT= <port>`
4) From a terminal:

```bash
python3 /home/istale/.openclaw/workspace/klayout_skill_test/test_client_ping.py <port>
```

Expect `OK`.

## Run (headless smoke test)
This keeps running until you stop the process.

Prereq (dynamic linker):
- If you are running from a fresh shell, ensure `LD_LIBRARY_PATH` includes the KLayout build directory.
- Recommended one-time setup: add to `~/.profile`:
  - `export KLAYOUT_HOME="/home/istale/klayout-build/0.30.5-qt5"`
  - `export LD_LIBRARY_PATH="$KLAYOUT_HOME${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"`

Terminal A:
```bash
cd /home/istale/.openclaw/workspace/klayout_skill_test
KLAYOUT_SERVER_PORT=5055 /home/istale/klayout-build/0.30.5-qt5/klayout -e -rm klayout_gui_tcp_server.py
```

Terminal B:
```bash
python3 /home/istale/.openclaw/workspace/klayout_skill_test/test_client_ping.py 5055
```

## Protocol v0 (JSON-RPC 2.0)
Transport:
- One JSON-RPC request per line (newline-delimited JSON)
- One JSON-RPC response per line

Single-client only:
- Only one client connection is supported at a time.
- Additional connections are rejected.

### Common error codes (JSON-RPC 2.0)
Errors must include the *real reason* (not only generic text) when the cause is determined by server logic.

- `-32600` Invalid Request
- `-32601` Method not found
- `-32602` Invalid params
- `-32001` No active layout (layout.new not called yet)
- `-32002` Cell not found (requested cell name does not exist)
- `-32003` Layer not available (no layer specified and no current layer set)
- `-32010` Path not allowed (export path escapes server cwd)
- `-32011` File exists (overwrite=false and file already exists)
- `-32099` Internal error

### Methods (需求2 spec v0)
#### `layout.new`
Create a new layout and top cell.

Params (defaults shown):
```json
{"dbu":0.0005,"top_cell":"TOP","clear_previous":true}
```

Result:
```json
{"layout_id":"L1","dbu":0.0005,"top_cell":"TOP"}
```

#### `layer.new`
Create or get a layer in the current layout.

Params:
```json
{"layer":1,"datatype":0,"name":null,"as_current":true}
```

Result:
```json
{"layer_index":3,"layer":1,"datatype":0,"name":null}
```

#### `shape.create`
Insert a shape into a cell+layer (v0 supports `box` and `polygon`).

Params:
```json
{
  "cell":"TOP",
  "layer_index":null,
  "layer":null,
  "type":"box",
  "coords":[0,0,1000,1000],
  "units":"dbu"
}
```

Behavior rules:
- If `cell` does not exist: return `-32002` with message like `Cell not found: TOP`.
- Layer selection priority:
  1) `layer_index` if provided
  2) `layer` object if provided
  3) current layer from last `layer.new`
  Otherwise: return `-32003` with message explaining what's missing.

Result:
```json
{"inserted":true,"type":"box","cell":"TOP","layer_index":3}
```

#### `layout.export`
Write current layout to a file under the server's start directory.

Params:
```json
{"path":"out.gds","overwrite":true}
```

Behavior rules:
- If resolved `path` escapes the server cwd: return `-32010` with message like `Path not allowed (escapes server cwd): ../out.gds`.
- If file exists and `overwrite=false`: return `-32011` with message like `File exists and overwrite=false: out.gds`.

Result:
```json
{"written":true,"path":"out.gds"}
```
