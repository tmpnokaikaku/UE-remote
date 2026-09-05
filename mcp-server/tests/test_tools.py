from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from ue_remote.config import AuditConfig, Config, LockConfig
from ue_remote.errors import PythonExecutionError, RemoteControlUnreachable
from ue_remote.session import Session
from ue_remote.tools import (
    EXECUTE_PYTHON_DESCRIPTION,
    ue_call_function,
    ue_describe_object,
    ue_execute_python,
    ue_get_property,
    ue_release_lock,
    ue_search_assets,
    ue_session_status,
    ue_set_property,
)

from .test_session import FakeClient


class ToolsTest(unittest.TestCase):
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
            lock=LockConfig(ttl_seconds=60, heartbeat_seconds=60),
            audit=AuditConfig(local_dir=self.root / "audit", remote_flush_every=100),
        )
        self.client = FakeClient(self.root / "Saved")
        self.sessions: list[Session] = []
        self.addCleanup(self._close_sessions)

    def _session(self, client: FakeClient | None = None) -> Session:
        session = Session(self.config, client=client or self.client)
        self.sessions.append(session)
        return session

    def _close_sessions(self) -> None:
        for session in self.sessions:
            session.close()

    def _audit_events(self) -> list[dict[str, Any]]:
        files = list((self.root / "audit").glob("*.jsonl"))
        return [
            json.loads(line)
            for path in files
            for line in path.read_text(encoding="utf-8").splitlines()
        ]

    def test_read_tools_do_not_acquire_lock(self) -> None:
        session = self._session()

        results = [
            ue_get_property(session, "/Object", "Value"),
            ue_describe_object(session, "/Object"),
            ue_search_assets(session, "Cube", 3),
        ]

        self.assertTrue(all(result.ok for result in results))
        self.assertEqual(self.client.acquire_calls, 0)

    def test_first_write_tool_acquires_lock(self) -> None:
        session = self._session()

        first = ue_set_property(session, "/Object", "Value", 2)
        second = ue_call_function(session, "/Object", "Run", {})

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual(self.client.acquire_calls, 1)

    def test_foreign_lock_rejection_is_audited_with_holder(self) -> None:
        path = self.root / "Saved" / "ue-remote" / "session.lock"
        path.parent.mkdir(parents=True)
        now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        path.write_text(
            json.dumps(
                {
                    "developer_id": "bob",
                    "hostname": "lab-host",
                    "session_id": "other",
                    "acquired_at": now,
                    "heartbeat_at": now,
                }
            ),
            encoding="utf-8",
        )
        session = self._session()

        result = ue_execute_python(session, "print('never runs')")

        self.assertFalse(result.ok)
        self.assertIn("bob", result.text)
        self.assertIn("lab-host", result.text)
        events = self._audit_events()
        self.assertEqual(len(events), 1)
        self.assertFalse(events[0]["ok"])
        self.assertEqual(events[0]["error_type"], "LockRejected")

    def test_project_mismatch_rejects_every_tool_except_status(self) -> None:
        client = FakeClient(self.root / "Saved", project="WrongProject")
        session = self._session(client)

        rejected = [
            ue_execute_python(session, "pass"),
            ue_call_function(session, "/Object", "Run"),
            ue_set_property(session, "/Object", "Value", 1),
            ue_get_property(session, "/Object", "Value"),
            ue_describe_object(session, "/Object"),
            ue_search_assets(session, ""),
            ue_release_lock(session),
        ]
        status = ue_session_status(session)

        self.assertTrue(all(not result.ok for result in rejected))
        self.assertTrue(all("WrongProject" in result.text for result in rejected))
        self.assertTrue(status.ok)
        self.assertIn("WrongProject", status.text)
        self.assertEqual(client.acquire_calls, 0)
        events = self._audit_events()
        self.assertEqual(len(events), 8)
        self.assertEqual(sum(not event["ok"] for event in events), 7)

    def test_python_failure_includes_log_output(self) -> None:
        class FailingClient(FakeClient):
            def execute_python(self, script: str):  # type: ignore[no-untyped-def]
                if script == "bad script":
                    raise PythonExecutionError(["Traceback: boom"], "Failure")
                return super().execute_python(script)

        client = FailingClient(self.root / "Saved")
        session = self._session(client)

        result = ue_execute_python(session, "bad script")

        self.assertFalse(result.ok)
        self.assertIn("log_output", result.text)
        self.assertIn("Traceback: boom", result.text)

    def test_unreachable_error_has_recovery_guidance(self) -> None:
        class UnreachableClient(FakeClient):
            def get_property(self, object_path: str, property_name: str) -> dict[str, Any]:
                raise RemoteControlUnreachable("100.0.0.1", 30010, OSError("offline"))

        client = UnreachableClient(self.root / "Saved")
        session = self._session(client)

        result = ue_get_property(session, "/Object", "Value")

        self.assertFalse(result.ok)
        self.assertIn("NetBird", result.text)
        self.assertIn("Unreal Editor", result.text)

    def test_python_description_warns_about_loop_and_batch(self) -> None:
        self.assertIn("1本", EXECUTE_PYTHON_DESCRIPTION)
        self.assertIn("/remote/batch", EXECUTE_PYTHON_DESCRIPTION)


if __name__ == "__main__":
    unittest.main()
