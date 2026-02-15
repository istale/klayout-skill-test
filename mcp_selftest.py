#!/usr/bin/env python3
"""MCP Selftest - Tests the MCP server functionality.

Assumes KLayout server is already running.

Usage:
    python mcp_selftest.py

Environment:
    KLAYOUT_ENDPOINT: Override endpoint
    KLAYOUT_PROJECT_DIR: Target project directory
"""

import json
import sys
import os

# Add mcp to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "mcp"))

from klayout_mcp_server import (
    klayout_ping,
    klayout_layout_new,
    klayout_layer_new,
    klayout_shape_create,
    klayout_layout_export,
    klayout_layout_render_png,
)


def test_ping():
    """Test 1: Ping the KLayout server via MCP."""
    print("=" * 60)
    print("TEST 1: klayout_ping")
    print("=" * 60)

    result = klayout_ping()
    print(f"Result: {json.dumps(result, indent=2)}")

    if result.get("ok"):
        print("✓ PASS: Ping successful")
        return True
    else:
        print("✗ FAIL: Ping failed")
        print(f"  Error: {result.get('error', {}).get('message', 'Unknown')}")
        return False


def test_layout_flow():
    """Test 2: Create layout, layer, shape, export, render."""
    print("\n" + "=" * 60)
    print("TEST 2: Layout creation flow")
    print("=" * 60)

    # Create layout
    print("\n2a. Creating layout...")
    result = klayout_layout_new(dbu=0.001, top_cell="TEST_TOP")
    print(f"Result: {json.dumps(result, indent=2)}")
    if not result.get("ok"):
        print("✗ FAIL: layout.new failed")
        return False
    print("✓ Layout created")

    # Create layer
    print("\n2b. Creating layer...")
    result = klayout_layer_new(layer=10, datatype=0, as_current=True)
    print(f"Result: {json.dumps(result, indent=2)}")
    if not result.get("ok"):
        print("✗ FAIL: layer.new failed")
        return False
    print("✓ Layer created")

    # Create box shape
    print("\n2c. Creating box shape...")
    result = klayout_shape_create(
        cell="TEST_TOP", type="box", coords=[0, 0, 10000, 5000], units="dbu"
    )
    print(f"Result: {json.dumps(result, indent=2)}")
    if not result.get("ok"):
        print("✗ FAIL: shape.create (box) failed")
        return False
    print("✓ Box shape created")

    # Create polygon shape
    print("\n2d. Creating polygon shape...")
    result = klayout_shape_create(
        cell="TEST_TOP",
        type="polygon",
        coords=[[10000, 0], [15000, 0], [15000, 5000], [10000, 5000]],
        units="dbu",
    )
    print(f"Result: {json.dumps(result, indent=2)}")
    if not result.get("ok"):
        print("✗ FAIL: shape.create (polygon) failed")
        return False
    print("✓ Polygon shape created")

    # Export layout
    print("\n2e. Exporting layout to GDS...")
    result = klayout_layout_export(path="test_export.gds")
    print(f"Result: {json.dumps(result, indent=2)}")
    if not result.get("ok"):
        print("✗ FAIL: layout.export failed")
        return False

    # Check file was created
    if os.path.exists("test_export.gds"):
        print("✓ GDS file exported")
    else:
        print("✗ FAIL: GDS file not found")
        return False

    # Render PNG (headless)
    print("\n2f. Rendering PNG (headless)...")
    result = klayout_layout_render_png(
        path="test_render.png", width=800, height=600, viewport_mode="fit"
    )
    print(f"Result: {json.dumps(result, indent=2)}")
    if not result.get("ok"):
        print("✗ FAIL: layout.render_png failed")
        return False

    # Check file was created
    if os.path.exists("test_render.png"):
        print("✓ PNG file rendered")
    else:
        print("✗ FAIL: PNG file not found")
        return False

    return True


def test_traces():
    """Test 3: Verify traces were written."""
    print("\n" + "=" * 60)
    print("TEST 3: Verify traces")
    print("=" * 60)

    traces_dir = os.environ.get("KLAYOUT_MCP_TRACES_DIR", "./traces")

    if not os.path.exists(traces_dir):
        print(f"✗ FAIL: Traces directory not found: {traces_dir}")
        return False

    trace_files = [f for f in os.listdir(traces_dir) if f.endswith(".jsonl")]

    if not trace_files:
        print("✗ FAIL: No trace files found")
        return False

    # Check most recent trace file
    latest_trace = max(
        trace_files, key=lambda f: os.path.getmtime(os.path.join(traces_dir, f))
    )
    trace_path = os.path.join(traces_dir, latest_trace)

    with open(trace_path, "r") as f:
        lines = f.readlines()

    print(f"Trace file: {latest_trace}")
    print(f"Trace entries: {len(lines)}")

    # Validate trace format
    for i, line in enumerate(lines):
        try:
            entry = json.loads(line)
            required_fields = [
                "ts_utc",
                "run_id",
                "tool",
                "endpoint",
                "mcp_params",
                "rpc_request",
                "rpc_response",
                "duration_ms",
                "artifacts",
            ]
            for field in required_fields:
                if field not in entry:
                    print(f"✗ FAIL: Trace entry {i} missing field: {field}")
                    return False
        except json.JSONDecodeError as e:
            print(f"✗ FAIL: Invalid JSON in trace entry {i}: {e}")
            return False

    print(f"✓ All {len(lines)} trace entries valid")
    return True


def cleanup():
    """Clean up test artifacts."""
    print("\n" + "=" * 60)
    print("Cleanup")
    print("=" * 60)

    files_to_remove = ["test_export.gds", "test_render.png"]
    for f in files_to_remove:
        if os.path.exists(f):
            os.remove(f)
            print(f"Removed: {f}")


def main():
    """Run all tests."""
    print("MCP Selftest - KLayout MCP Server")
    print("=" * 60)
    print("Assuming KLayout server is already running...")
    print()

    try:
        # Run tests
        results = []
        results.append(("ping", test_ping()))
        results.append(("layout_flow", test_layout_flow()))
        results.append(("traces", test_traces()))

        # Summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)

        passed = sum(1 for _, r in results if r)
        total = len(results)

        for name, result in results:
            status = "✓ PASS" if result else "✗ FAIL"
            print(f"  {status}: {name}")

        print(f"\nTotal: {passed}/{total} tests passed")

        if passed == total:
            print("\n🎉 All tests passed!")
            return 0
        else:
            print(f"\n⚠️ {total - passed} test(s) failed")
            return 1

    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
