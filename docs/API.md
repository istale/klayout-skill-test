# KLayout GUI TCP Server — API 規格（JSON-RPC 2.0）

本文件是 `klayout_gui_tcp_server.py` 對外提供的 **JSON-RPC 2.0** API 規格。

- 傳輸：newline-delimited JSON（每行一個 request / response）
- 連線：單一 client（第二個連線會被拒絕）
- 本文件為「規格」，測試腳本（`test_client_jsonrpc_*.py`）為可執行的行為驗證。

---

## 0. 名詞（先用一套固定術語）
- **DBU**：database unit（整數座標單位）
- **um**：micrometer（浮點座標單位）
- **層級**：hierarchy
- **陣列實例**：regular array instance（nx*ny）

（更完整的術語表會放在 `docs/GLOSSARY.md`）

---

## 1. Transport
- Request：一行 JSON（UTF-8），符合 JSON-RPC 2.0
- Response：一行 JSON（UTF-8），符合 JSON-RPC 2.0

範例：
```json
{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}
```

---

## 2. 通用錯誤格式
本 server 使用 JSON-RPC 2.0 error 物件：
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32602,
    "message": "Invalid params: ...",
    "data": {
      "type": "InvalidParams",
      "details": {"field": "..."}
    }
  }
}
```

### 2.1 標準 JSON-RPC code
- `-32700` Parse error
- `-32600` Invalid Request
- `-32601` Method not found
- `-32602` Invalid params

### 2.2 伺服器自訂 error.type（常用）
- `NoActiveLayout`（-32001）
- `CellNotFound`（-32002 或 -32000，視方法）
- `LayerNotAvailable`（-32003）
- `PathNotAllowed`（-32010）
- `FileExists`（-32011）
- `FileNotFound`（-32012）
- `MainWindowUnavailable`（-32013）
- `OpenFailed`（-32014）
- `NoCurrentView`（-32016）
- `LayoutViewUnavailable`（-32017）
- `TooManyResults`（需求6 guardrail）
- `InternalError`（-32099）

> 註：各方法實際會用到哪些 type，以方法章節為準。

---

## 3. Methods Index
目前 server 實作的方法（以 `_METHODS` 為準）：

### 基礎
- `ping`

### Layout / Layer / Shape（v0 + Req3+）
- `layout.new`
- `layout.open`
- `layout.export`
- `layout.get_topcell`
- `layout.get_layers`
- `layout.get_dbu`
- `layout.get_cells`
- `layout.get_hierarchy_depth`

- `layer.new`

- `cell.create`
- `shape.create`
- `instance.create`
- `instance_array.create`

### View / Screenshot（GUI）
- `view.ensure`
- `view.screenshot`
- `view.set_viewport`
- `view.set_hier_levels`

### Rendering（可 headless，依實作）
- `layout.render_png`

### Hierarchy（需求6 + extensions）
- `hier.query_down`
- `hier.query_down_stats`
- `hier.query_up_paths`
- `hier.shapes_rec`

---

## 4. ping
### Request
```json
{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}
```

### Result
```json
{"pong":true}
```

---

## 5. layout.new
建立新的 in-memory layout 與 top cell。

### Params
```json
{"dbu":0.0005,"top_cell":"TOP","clear_previous":true}
```

### Result
```json
{"layout_id":"L1","dbu":0.0005,"top_cell":"TOP"}
```

### Errors
- `InvalidParams`

---

## 6. layout.open
在 KLayout 內開啟 layout 檔案並切換 server 的 active layout。

### Params
```json
{"path":"demo.gds","mode":0}
```

- `path`：必填，且必須在 server cwd 底下（不可跳脫）
- `mode`：`0|1|2`（傳給 `MainWindow.load_layout`），預設 0

### Result
```json
{"opened":true,"path":"demo.gds","mode":0,"top_cell":"TOP"}
```

### Errors
- `InvalidParams`
- `PathNotAllowed`
- `FileNotFound`
- `MainWindowUnavailable`
- `OpenFailed`

---

## 7. layout.export
寫出目前 layout 到檔案（server cwd 底下）。

### Params
```json
{"path":"out.gds","overwrite":true}
```

### Result
```json
{"written":true,"path":"out.gds"}
```

### Errors
- `PathNotAllowed`
- `FileExists`

---

## 8. layout.get_topcell
取得（且要求唯一）top cell。

### Params
```json
{}
```

### Result
```json
{"top_cell":"TOP"}
```

### Errors
- `NoActiveLayout`
- `NoTopCell`
- `MultipleTopCells`

---

## 9. layout.get_layers
取得 layout 已定義的 layers（definition-based）。

### Params
```json
{}
```

### Result
```json
{"layers":[{"layer":1,"datatype":0,"name":null,"layer_index":0}]}
```

---

## 10. layout.get_dbu
取得 dbu。

### Result
```json
{"dbu":0.001}
```

---

## 11. layout.get_cells
取得 cell 名稱列表（top-down）。

### Result
```json
{"cells":["TOP","CHILD"]}
```

---

## 12. layout.get_hierarchy_depth
取得 hierarchy depth（定義：從 top 出發的最大 instance edges；top=0）。

### Result
```json
{"depth":3,"depth_definition":"max instance edges from top (top=0)"}
```

---

## 13. layer.new
在目前 layout 建立/取得一個 layer。

### Params
```json
{"layer":1,"datatype":0,"name":null,"as_current":true}
```

### Result
```json
{"layer_index":0,"layer":1,"datatype":0,"name":null}
```

---

## 14. cell.create
建立 cell。

### Params
```json
{"name":"CHILD"}
```

### Result
```json
{"created":true,"name":"CHILD"}
```

---

## 15. shape.create
插入 shape（常用：box / polygon / path）。

### Params（box）
```json
{"cell":"TOP","layer_index":0,"type":"box","coords":[0,0,1000,2000]}
```

### Params（polygon）
```json
{"cell":"TOP","layer_index":0,"type":"polygon","coords":[[0,0],[1000,0],[1000,1000]]}
```

### Params（path）
```json
{"cell":"TOP","layer_index":0,"type":"path","coords":[[0,0],[1000,0]],"width":200}
```

### Result
```json
{"inserted":true,"type":"box","cell":"TOP","layer_index":0}
```

---

## 16. instance.create
建立單一 instance。

### Params
```json
{"cell":"TOP","child_cell":"CHILD","trans":{"x":1000,"y":2000,"rot":0,"mirror":false}}
```

### Result
```json
{"inserted":true,"cell":"TOP","child_cell":"CHILD","trans":{"x":1000,"y":2000,"rot":0,"mirror":false}}
```

---

## 17. instance_array.create
建立 regular array instance。

### Params
```json
{
  "cell":"TOP",
  "child_cell":"CHILD",
  "trans":{"x":0,"y":0,"rot":0,"mirror":false},
  "array":{"nx":3,"ny":2,"dx":2000,"dy":1500}
}
```

### Result
```json
{
  "inserted":true,
  "cell":"TOP",
  "child_cell":"CHILD",
  "trans":{"x":0,"y":0,"rot":0,"mirror":false},
  "array":{"nx":3,"ny":2,"dx":2000,"dy":1500}
}
```

---

## 18. view.ensure（GUI）
確保 GUI 的 current_view 存在並 show layout。

### Params
```json
{"zoom_fit":true}
```

### Result
```json
{"ok":true,"views":1,"current_view_index":0}
```

### Errors
- `MainWindowUnavailable` (-32013)
- `NoCurrentView` (-32016)

詳細 GUI 物件模型見：`docs/GUI_MODEL.md`

---

## 19. view.screenshot（GUI）
將 current_view 匯出 PNG。

### Params（常用）
```json
{
  "path":"out.png",
  "width":1200,
  "height":800,
  "viewport_mode":"fit",
  "units":"dbu",
  "overwrite":true
}
```

### Result
```json
{"written":true,"path":"out.png"}
```

### Errors
- `MainWindowUnavailable` (-32013)
- `NoCurrentView` (-32016)

---

## 20. view.set_viewport（GUI）
只改視圖 viewport，不輸出圖片。

### Params
- `viewport_mode=fit`
```json
{"viewport_mode":"fit"}
```

- `viewport_mode=box`
```json
{"viewport_mode":"box","units":"dbu","box":[0,0,10000,10000]}
```

- `viewport_mode=center_size`
```json
{"viewport_mode":"center_size","units":"um","center":[5.0,5.0],"size":[10.0,8.0]}
```

- `viewport_mode=relative`
```json
{"viewport_mode":"relative","steps":1}
```

### Result
```json
{"ok":true,"viewport_mode":"box","units":"dbu"}
```

### Errors
- `MainWindowUnavailable` (-32013)
- `NoCurrentView` (-32016)

---

## 21. view.set_hier_levels（GUI）
控制 hierarchy geometry 顯示深度（不是 hierarchy browser widget）。

### Params
- `mode=max`：
```json
{"mode":"max"}
```

- `mode=set`：
```json
{"mode":"set","min_level":0,"max_level":3}
```

### Result
```json
{"ok":true,"mode":"max","min_hier_levels":0,"max_hier_levels":999}
```

---

## 22. layout.render_png（headless-friendly render）
建立 standalone LayoutView 來輸出 PNG（即使沒有 GUI current_view 也嘗試 render）。

### Params
```json
{
  "path":"out.png",
  "width":1200,
  "height":800,
  "viewport_mode":"fit",
  "units":"dbu",
  "overwrite":true
}
```

### Result
```json
{
  "written":true,
  "path":"out.png",
  "width":1200,
  "height":800,
  "viewport_mode":"fit",
  "units":"dbu"
}
```

### Errors
- `LayoutViewUnavailable` (-32017)
- `FileExists` / `PathNotAllowed`

---

## 23. hier.query_down（需求6-3）
向下列舉 instances。

### Params
```json
{
  "cell":"TOP",
  "depth":2,
  "mode":"structural",
  "include_bbox":false,
  "max_results":1000000,
  "engine":"iterator"
}
```

### Result（概要）
```json
{
  "root":"TOP",
  "depth":2,
  "mode":"structural",
  "instances":[
    {
      "kind":"single",
      "parent_cell":"TOP",
      "child_cell":"CHILD",
      "trans":{"x":1000,"y":2000,"rot":0,"mirror":false},
      "array":null,
      "path":["TOP"]
    }
  ]
}
```

### Notes
- `mode=structural`：陣列不展開。
- `mode=expanded`：陣列展開，回傳 `expanded_index={ix,iy}`。
- `engine`：iterator/dfs 的相容性策略見 `docs/COMPAT.md`。

---

## 24. hier.query_down_stats（統計）
只回傳統計：依 `child_cell` 分組，**陣列展開計數**。

### Params
```json
{"cell":"TOP","depth":5,"max_results":20000000}
```

### Result
```json
{
  "root":"TOP",
  "depth":5,
  "expanded":true,
  "total":12345,
  "by_child_cell":{
    "INV":12000,
    "NAND":345
  },
  "truncated":false
}
```

---

## 25. hier.query_up_paths（需求6-2）
從單一 top cell 回推到 target cell 的所有路徑（segments）。

### Params
```json
{"cell":"CHILD","max_paths":10000}
```

### Result
```json
{
  "cell":"CHILD",
  "max_paths":10000,
  "path_format":"segments",
  "paths":[
    ["<in-memory>","TOP","A","CHILD"],
    ["<in-memory>","TOP","B","CHILD"]
  ]
}
```

### Notes
- `paths[]` 每一筆都是「segments」：`[gds_filename, top_cell, ..., target_cell]`
- guardrail：若 paths 數量超過 `max_paths`，回 `TooManyResults`
- 限制：layout 必須只有一個 top cell；多 top cell 會回 `MultipleTopCells`

---

## 26. hier.shapes_rec（遞迴 shapes + hierarchy_path）
使用 `begin_shapes_rec(layer)` / `RecursiveShapeIterator.path` 遞迴列出 shapes。

### Params
```json
{
  "start_cell":"TOP",
  "unit":"um",
  "shape_types":["polygon","box","path"],
  "layer_filter":[0,1,2],
  "max_results":200000
}
```

### Result
```json
{
  "shapes":[
    {
      "shape_type":"box",
      "hierarchy_path":["CHILD"],
      "layer_index":0,
      "layer":{"layer":1,"datatype":0},
      "points_um":[[1.0,2.0],[1.1,2.0],[1.1,2.2],[1.0,2.2]],
      "bbox_um":[1.0,2.0,1.1,2.2],
      "unit":"um"
    }
  ],
  "unit":"um",
  "count":1,
  "truncated":false
}
```

### Notes
- `unit` 目前只支援 `"um"`
- `layer_filter` 是 layer index（不是 layer/datatype pair）
- `hierarchy_path` 主要來自 `RecursiveShapeIterator.path`（InstElement[]）
- `max_results` 為 guardrail：超過會 `truncated=true` 並停止收集
