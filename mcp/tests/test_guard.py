from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import types
import unittest

from mcp.ue_remote.guard import verify


class _FakeClient:
    def __init__(self, project_path: str) -> None:
        self.project_path = project_path

    def run_python_json(self, script: str, marker: str) -> dict[str, object] | None:
        unreal = types.ModuleType("unreal")

        class Paths:
            @staticmethod
            def get_project_file_path() -> str:
                return self.project_path

        unreal.Paths = Paths
        previous = sys.modules.get("unreal")
        sys.modules["unreal"] = unreal
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                exec(script, {"__name__": "__main__"})
        finally:
            if previous is None:
                sys.modules.pop("unreal", None)
            else:
                sys.modules["unreal"] = previous
        text = output.getvalue()
        position = text.find(marker)
        if position < 0:
            return None
        return json.loads(text[position + len(marker) :])


class ProjectGuardTest(unittest.TestCase):
    def test_matching_project_is_allowed(self) -> None:
        client = _FakeClient("/projects/Sandbox/Sandbox.uproject")
        result = verify(client, "Sandbox")
        self.assertTrue(result.ok)
        self.assertEqual(result.actual_project, "Sandbox")

    def test_mismatch_returns_actual_name_and_path(self) -> None:
        path = "/projects/DangerProject/DangerProject.uproject"
        result = verify(_FakeClient(path), "ExpectedProject")

        self.assertFalse(result.ok)
        self.assertEqual(result.actual_project, "DangerProject")
        self.assertEqual(result.project_path, path)
        self.assertIn("DangerProject", result.message)
        self.assertIn(path, result.message)

    def test_missing_expectation_is_allowed_with_warning(self) -> None:
        result = verify(_FakeClient("C:\\Projects\\Setup\\Setup.uproject"), None)

        self.assertTrue(result.ok)
        self.assertEqual(result.actual_project, "Setup")
        self.assertIsNotNone(result.warning)


if __name__ == "__main__":
    unittest.main()
