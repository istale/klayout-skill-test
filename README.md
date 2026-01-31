# klayout_skill_test – GUI TCP server smoke test

## Goal
Validate that a **KLayout Python macro** can host a **TCP server** (localhost only) and respond to a simple request.

## Files
- `klayout_gui_tcp_server.py`: KLayout macro. Starts a TCP server on 127.0.0.1. By default it uses an OS-assigned port; you can also force a port via env `KLAYOUT_SERVER_PORT`.
- `test_client_ping.py`: external client test. Sends `ping\n`, expects `pong\n`.

## Run (GUI)
1) Open KLayout GUI
2) Macro IDE → Python → run `klayout_gui_tcp_server.py`
3) In the macro console, note the printed port line:
   - `[klayout-gui-server] PORT= <port>`
4) From a terminal:

```bash
python3 test_client_ping.py <port>
```

Expect `OK`.

## Run (headless smoke test)
This keeps running until you stop the process.

Terminal A:
```bash
cd /home/istale/.openclaw/workspace/klayout_skill_test
KLAYOUT_SERVER_PORT=5055 klayout -e -rm klayout_gui_tcp_server.py
```

Terminal B:
```bash
python3 test_client_ping.py 5055
```

## Protocol v0
Line-based UTF-8-ish (best effort):
- `ping` → `pong`
- `quit` → `bye` then disconnect
- unknown → `err unknown_command: ...`
