from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

from ue_remote.audit import AuditLog, PARAMS_PREVIEW_CHARS


class _FakeClient:
    def __init__(self, saved_dir: str) -> None:
        self.saved_dir = saved_dir
        self.calls = 0

    def execute_python(self, script: str) -> object:
        self.calls += 1
        unreal = types.ModuleType("unreal")

        class Paths:
            @staticmethod
            def project_saved_dir() -> str:
                return self.saved_dir + os.sep

        unreal.Paths = Paths
        previous = sys.modules.get("unreal")
        sys.modules["unreal"] = unreal
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                exec(script, {"__name__": "__main__"})
        except Exception as exc:
            return types.SimpleNamespace(ok=False, log_output=[str(exc)], command_result=None)
        finally:
            if previous is None:
                sys.modules.pop("unreal", None)
            else:
                sys.modules["unreal"] = previous
        return types.SimpleNamespace(ok=True, log_output=[], command_result=None)


class AuditLogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = _FakeClient(str(self.root / "Saved"))

    def test_jsonl_has_truncated_preview_and_sha256(self) -> None:
        audit = AuditLog(
            self.client,
            "alice",
            "session-a",
            local_dir=self.root / "local",
            remote_flush_every=20,
        )
        params = "あ" * (PARAMS_PREVIEW_CHARS + 10)

        result = audit.record_tool_call("ue_execute_python", params, 12.5, True)

        self.assertTrue(result.ok)
        files = list((self.root / "local").glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        lines = files[0].read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        event = json.loads(lines[0])
        self.assertEqual(len(event["params_preview"]), PARAMS_PREVIEW_CHARS)
        self.assertNotEqual(event["params_digest"], params)
        self.assertEqual(len(event["params_digest"]), 64)

    def test_local_write_failure_does_not_escape(self) -> None:
        unusable = self.root / "not-a-directory"
        unusable.write_text("file", encoding="utf-8")
        audit = AuditLog(
            self.client,
            "alice",
            "session-a",
            local_dir=unusable,
            remote_flush_every=20,
        )

        result = audit.record_tool_call("ue_get_property", {"x": 1}, 1.0, True)

        self.assertFalse(result.ok)
        self.assertFalse(result.local_written)
        self.assertIsNotNone(audit.last_error)

    def test_remote_summary_is_batched_and_close_flushes_remainder(self) -> None:
        audit = AuditLog(
            self.client,
            "alice",
            "session-a",
            local_dir=self.root / "local",
            remote_flush_every=2,
        )
        audit.record_tool_call("one", {}, 1.0, True, ts="2026-09-05T00:00:00Z")
        self.assertEqual(self.client.calls, 0)
        audit.record_tool_call("two", {}, 1.0, False, ts="2026-09-05T00:00:03Z")
        self.assertEqual(self.client.calls, 1)
        audit.record_tool_call("three", {}, 1.0, True, ts="2026-09-05T00:00:05Z")
        self.assertEqual(self.client.calls, 1)
        self.assertTrue(audit.close().ok)
        self.assertEqual(self.client.calls, 2)

        path = self.root / "Saved" / "ue-remote" / "audit-summary.jsonl"
        summaries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([item["tool_calls"] for item in summaries], [2, 1])
        self.assertEqual(summaries[0]["errors"], 1)
        self.assertEqual(summaries[0]["active_seconds"], 3.0)


if __name__ == "__main__":
    unittest.main()
