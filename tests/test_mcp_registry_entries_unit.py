"""Unit tests for MCP registry parsing.

These tests do NOT require a running KLayout server.

Run:
  python3 -m unittest -q tests.test_mcp_registry_entries_unit
"""

import json
import tempfile
import unittest
from pathlib import Path

from mcp.klayout_mcp_server import _read_registry_entries


class TestReadRegistryEntries(unittest.TestCase):
    def test_skips_malformed_and_incomplete_lines(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "registry.jsonl"
            p.write_text(
                "\n".join(
                    [
                        "not-json",
                        json.dumps({"ts_utc": "2026-01-01T00:00:00Z"}),  # missing keys
                        json.dumps(
                            {
                                "ts_utc": "2026-01-01T00:00:00Z",
                                "user": "u",
                                "pid": 123,
                                "port": 5055,
                                "project_dir": "/tmp/x",
                            }
                        ),
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            entries = _read_registry_entries(str(p))
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["port"], 5055)

    def test_coerces_numeric_pid_and_port(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "registry.jsonl"
            p.write_text(
                json.dumps(
                    {
                        "ts_utc": "2026-01-01T00:00:00Z",
                        "user": "u",
                        "pid": "999",
                        "port": "5055",
                        "project_dir": "/tmp/x",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            entries = _read_registry_entries(str(p))
            self.assertEqual(len(entries), 1)
            self.assertIsInstance(entries[0]["pid"], int)
            self.assertIsInstance(entries[0]["port"], int)
            self.assertEqual(entries[0]["pid"], 999)
            self.assertEqual(entries[0]["port"], 5055)

    def test_skips_non_numeric_pid_or_port(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "registry.jsonl"
            p.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "ts_utc": "2026-01-01T00:00:00Z",
                                "user": "u",
                                "pid": "nope",
                                "port": 5055,
                                "project_dir": "/tmp/x",
                            }
                        ),
                        json.dumps(
                            {
                                "ts_utc": "2026-01-01T00:00:00Z",
                                "user": "u",
                                "pid": 123,
                                "port": "nope",
                                "project_dir": "/tmp/x",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            entries = _read_registry_entries(str(p))
            self.assertEqual(entries, [])


if __name__ == "__main__":
    unittest.main()
