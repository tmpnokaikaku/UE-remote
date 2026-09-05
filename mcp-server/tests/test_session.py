from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from ue_remote.config import AuditConfig, Config, LockConfig
from ue_remote.guard import GuardResult
from ue_remote.interfaces import PythonResult
from ue_remote.session import Session


class FakeClient:
    """Savedディレクトリとuprojectをローカルで模す偽クライアント。"""

    def __init__(self, saved_dir: Path, project: str = "ExpectedProject") -> None:
        self.saved_dir = saved_dir
        self.project = project
        self.execute_calls = 0
        self.acquire_calls = 0
        self.heartbeat_calls = 0
        self.release_calls = 0

    def execute_python(self, script: str) -> PythonResult:
        self.execute_calls += 1
        if "os.O_CREAT | os.O_EXCL" in script:
            self.acquire_calls += 1
        if '"action": "heartbeat"' in script:
            self.heartbeat_calls += 1
        if '"action": "release"' in script:
            self.release_calls += 1

        unreal = types.ModuleType("unreal")
        saved_dir = self.saved_dir
        project = self.project

        class Paths:
            @staticmethod
            def project_saved_dir() -> str:
                return str(saved_dir) + os.sep

            @staticmethod
            def get_project_file_path() -> str:
                return f"/projects/{project}/{project}.uproject"

        unreal.Paths = Paths
        previous = sys.modules.get("unreal")
        sys.modules["unreal"] = unreal
        output = io.StringIO()

        def capture_print(
            *values: object, sep: str = " ", end: str = "\n", **_: object
        ) -> None:
            output.write(sep.join(str(value) for value in values) + end)

        try:
            exec(script, {"__name__": "__main__", "print": capture_print})
        except Exception as exc:
            return PythonResult(False, [str(exc)], output.getvalue(), {})
        finally:
            if previous is None:
                sys.modules.pop("unreal", None)
            else:
                sys.modules["unreal"] = previous
        text = output.getvalue()
        return PythonResult(True, [text] if text else [], None, {"LogOutput": [text]})

    def run_python_json(self, script: str, marker: str) -> Any:
        result = self.execute_python(script)
        for text in result.log_output:
            position = text.find(marker)
            if position >= 0:
                return json.loads(text[position + len(marker) :])
        return None

    def call_object(
        self, object_path: str, function_name: str, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {"object_path": object_path, "function_name": function_name}

    def get_property(self, object_path: str, property_name: str) -> dict[str, Any]:
        return {"value": 1}

    def set_property(
        self, object_path: str, property_name: str, value: Any
    ) -> dict[str, Any]:
        return {"value": value}

    def search_assets(self, query: str, limit: int = 50) -> dict[str, Any]:
        return {"query": query, "limit": limit}

    def describe_object(self, object_path: str) -> dict[str, Any]:
        return {"object_path": object_path}


class FakeGuard:
    """指定した順番で結果を返す偽ガード。"""

    def __init__(self, results: list[GuardResult]) -> None:
        self.results = results
        self.verify_calls = 0

    def verify(self) -> GuardResult:
        result = self.results[min(self.verify_calls, len(self.results) - 1)]
        self.verify_calls += 1
        return result


class SessionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = Config(
            host="127.0.0.1",
            port=30010,
            timeout_seconds=1.0,
            developer_id="alice",
            expected_project="ExpectedProject",
            lock=LockConfig(ttl_seconds=60, heartbeat_seconds=0.05),  # type: ignore[arg-type]
            audit=AuditConfig(local_dir=self.root / "audit", remote_flush_every=100),
        )
        self.client = FakeClient(self.root / "Saved")
        self.sessions: list[Session] = []
        self.addCleanup(self._close_sessions)

    def _session(
        self, *, client: FakeClient | None = None, guard: FakeGuard | None = None
    ) -> Session:
        session = Session(self.config, client=client or self.client, guard=guard)
        self.sessions.append(session)
        return session

    def _guard_result(self, ok: bool) -> GuardResult:
        actual = "ExpectedProject" if ok else None
        return GuardResult(
            ok,
            "確認できました" if ok else "TimeoutError: 接続できません",
            "ExpectedProject",
            actual,
            f"/projects/{actual}/{actual}.uproject" if actual else None,
        )

    def _close_sessions(self) -> None:
        for session in self.sessions:
            session.close()

    def test_lock_is_acquired_lazily_only_for_write(self) -> None:
        session = self._session()

        self.assertTrue(session.require_read().ok)
        self.assertEqual(self.client.acquire_calls, 0)
        self.assertTrue(session.require_write().ok)
        self.assertEqual(self.client.acquire_calls, 1)
        self.assertTrue(session.require_write().ok)
        self.assertEqual(self.client.acquire_calls, 1)

    def test_foreign_lock_rejection_contains_holder_details(self) -> None:
        path = self.root / "Saved" / "ue-remote" / "session.lock"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "developer_id": "bob",
                    "hostname": "lab-pc",
                    "session_id": "other-session",
                    "acquired_at": "2099-01-01T00:00:00Z",
                    "heartbeat_at": "2099-01-01T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        session = self._session()

        result = session.require_write()

        self.assertFalse(result.ok)
        self.assertIn("bob", result.message)
        self.assertIn("lab-pc", result.message)
        self.assertIn("経過時間", result.message)

    def test_project_mismatch_rejects_read_and_write(self) -> None:
        client = FakeClient(self.root / "Saved", project="WrongProject")
        session = self._session(client=client)

        read = session.require_read()
        write = session.require_write()

        self.assertFalse(read.ok)
        self.assertFalse(write.ok)
        self.assertIn("WrongProject", read.message)
        self.assertEqual(client.acquire_calls, 0)
        self.assertEqual(session.status()["project"]["actual"], "WrongProject")

    def test_failed_guard_result_is_not_cached(self) -> None:
        guard = FakeGuard([self._guard_result(False), self._guard_result(True)])
        session = self._session(guard=guard)

        result = session.require_read()

        self.assertTrue(result.ok)
        self.assertEqual(guard.verify_calls, 2)

    def test_successful_guard_result_is_cached_within_ttl(self) -> None:
        guard = FakeGuard([self._guard_result(True)])
        session = self._session(guard=guard)

        self.assertTrue(session.require_read().ok)
        self.assertTrue(session.require_read().ok)

        self.assertEqual(guard.verify_calls, 1)

    def test_successful_guard_result_is_refreshed_after_ttl(self) -> None:
        guard = FakeGuard([self._guard_result(True)])
        with mock.patch("ue_remote.session.time.monotonic", return_value=100.0) as clock:
            session = self._session(guard=guard)
            self.assertTrue(session.require_read().ok)
            self.assertEqual(guard.verify_calls, 1)

            clock.return_value = 100.051
            self.assertTrue(session.require_read().ok)

        self.assertEqual(guard.verify_calls, 2)

    def test_status_rechecks_after_failed_guard_result(self) -> None:
        guard = FakeGuard([self._guard_result(False), self._guard_result(True)])
        session = self._session(guard=guard)

        status = session.status()

        self.assertTrue(status["project"]["ok"])
        self.assertEqual(status["project"]["actual"], "ExpectedProject")
        self.assertEqual(guard.verify_calls, 2)

    def test_close_releases_lock_and_stops_heartbeat(self) -> None:
        session = self._session()
        self.assertTrue(session.require_write().ok)
        path = self.root / "Saved" / "ue-remote" / "session.lock"
        self.assertTrue(path.exists())
        time.sleep(0.12)
        self.assertGreaterEqual(self.client.heartbeat_calls, 1)

        session.close()
        count_after_close = self.client.heartbeat_calls
        time.sleep(0.12)

        self.assertFalse(path.exists())
        self.assertEqual(self.client.heartbeat_calls, count_after_close)
        self.assertFalse(session.status()["lock"]["heartbeat_running"])
        self.assertEqual(self.client.release_calls, 1)


if __name__ == "__main__":
    unittest.main()
