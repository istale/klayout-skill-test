---
name: klayout-layout
description: Create, modify, and export KLayout layouts via the project MCP server (KLayout JSON-RPC). Use when a user describes their layout “做法/recipe/flow”, wants shapes/layers/cells created, needs export (GDS) or render (PNG), or asks to automate KLayout operations. Requires MCP server 'klayout' to be configured and a KLayout JSON-RPC server running (registry or KLAYOUT_ENDPOINT).
---

# KLayout Layout Authoring (via MCP)

This skill standardizes how to implement user-provided layout recipes using the **KLayout MCP tools** (server name: `klayout`).

## 0) Preconditions (must verify)
- KLayout JSON-RPC server is running for this repo’s `project_dir`.
- MCP server `klayout` is enabled in `cline_mcp_settings.json`.
- Always start with a connectivity check:
  - Call tool: `ping`.

If `ping` fails:
- Do NOT proceed with any layout operations.
- Ask for the endpoint or instruct to start the KLayout server.

## 1) Canonical workflow (common case)
Follow this order unless the user explicitly needs something different:
1. `ping`
2. `layout_new` (set `dbu`, `top_cell`, and usually `clear_previous=true`)
3. `layer_new` for each (layer/datatype) pair you will draw on
4. `shape_create` to draw geometry
5. Export/render artifacts:
   - `layout_export` → **GDS**
   - `layout_render_png` → **PNG** (headless-friendly)

### Recommended defaults
- `dbu`: **0.001** unless user specifies otherwise.
- `top_cell`: **"TOP"** unless user specifies otherwise.

## 2) Artifact path rules (important)
When writing outputs, always place them under `artifacts/` and pass **relative paths**:
- GDS: `artifacts/<name>.gds`
- PNG: `artifacts/<name>.png`

Never write absolute paths.

## 3) How to translate a user “layout 做法” into tool calls
When a user describes a recipe, convert it into:
- A list of required layers (layer/datatype)
- A list of shapes per layer, each shape with:
  - target cell (default: TOP)
  - type: box | polygon (and any supported types in server)
  - coords in **dbu units** unless user says otherwise

### Box example
- Tool: `shape_create`
- Arguments:
  - `cell`: "TOP"
  - `type`: "box"
  - `coords`: `[x1, y1, x2, y2]`
  - `units`: "dbu"

### Polygon example
- `coords`: `[[x1,y1],[x2,y2],...]`

## 4) Verification checklist (must do)
After executing the recipe:
- Ensure export succeeded (`layout_export` result.written == true)
- Ensure render succeeded (`layout_render_png` result.written == true)
- Return final outputs as **paths under artifacts/**.

## 5) What to ask the user (only if missing)
Ask minimal clarifying questions only when necessary:
- dbu (0.001 ok?)
- exact layers (layer/datatype) mapping
- coordinate units (dbu vs micron)
- expected output filenames

## 6) Safety + repeatability
- Keep tool calls **serial** (one at a time).
- Prefer deterministic filenames (include a short prefix + timestamp if needed).

## Quick smoke prompt (for maintainers)
If you need to validate the integration end-to-end, run a simple task:
- ping → layout_new(dbu=0.001) → layer_new(1/0) → shape_create(box) → layout_export("artifacts/smoke.gds") → layout_render_png("artifacts/smoke.png")
