from __future__ import annotations

import datetime as dt
import io
import json
import os
import sys
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ue_remote.lock import SessionLock


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
        output = io.StringIO()
        sys.modules["unreal"] = unreal

        def capture_print(*values: object, sep: str = " ", end: str = "\n", **_: object) -> None:
            output.write(sep.join(str(value) for value in values) + end)

        try:
            exec(script, {"__name__": "__main__", "print": capture_print})
        except Exception as exc:
            return types.SimpleNamespace(ok=False, log_output=[str(exc)], command_result=output.getvalue())
        return types.SimpleNamespace(ok=True, log_output=[output.getvalue()], command_result=None)


class SessionLockTest(unittest.TestCase):
    def setUp(self) -> None:
        previous_unreal = sys.modules.get("unreal")
        self.addCleanup(self._restore_unreal, previous_unreal)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.saved_dir = self.temp.name
        self.client = _FakeClient(self.saved_dir)
        self.path = Path(self.saved_dir, "ue-remote", "session.lock")

    @staticmethod
    def _restore_unreal(previous: object | None) -> None:
        if previous is None:
            sys.modules.pop("unreal", None)
        else:
            sys.modules["unreal"] = previous

    def _write_lock(self, *, session_id: str, age_seconds: float) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        heartbeat = now - dt.timedelta(seconds=age_seconds)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "developer_id": "other-developer",
                    "hostname": "other-host",
                    "session_id": session_id,
                    "acquired_at": heartbeat.isoformat().replace("+00:00", "Z"),
                    "heartbeat_at": heartbeat.isoformat().replace("+00:00", "Z"),
                }
            ),
            encoding="utf-8",
        )

    def test_acquire_without_existing_lock(self) -> None:
        lock = SessionLock(self.client, "alice", "session-a", hostname="laptop")
        result = lock.acquire()

        self.assertTrue(result.acquired)
        self.assertEqual(self.client.calls, 1)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["session_id"], "session-a")
        self.assertTrue(data["heartbeat_at"].endswith("Z"))

    def test_fresh_lock_is_rejected_with_holder_details(self) -> None:
        self._write_lock(session_id="other-session", age_seconds=1)
        lock = SessionLock(self.client, "alice", "session-a", ttl_seconds=60)

        result = lock.acquire()

        self.assertFalse(result.acquired)
        self.assertEqual(result.developer_id, "other-developer")
        self.assertEqual(result.hostname, "other-host")
        self.assertIsNotNone(result.age_seconds)
        self.assertEqual(json.loads(self.path.read_text())["session_id"], "other-session")

    def test_stale_lock_requires_force_and_can_be_stolen(self) -> None:
        self._write_lock(session_id="other-session", age_seconds=120)
        lock = SessionLock(self.client, "alice", "session-a", ttl_seconds=10)

        refused = lock.acquire()
        stolen = lock.acquire(force=True)

        self.assertFalse(refused.acquired)
        self.assertTrue(stolen.acquired)
        self.assertTrue(stolen.stolen)
        self.assertEqual(json.loads(self.path.read_text())["session_id"], "session-a")

    def test_release_never_deletes_another_sessions_lock(self) -> None:
        self._write_lock(session_id="other-session", age_seconds=1)
        lock = SessionLock(self.client, "alice", "session-a")

        result = lock.release()

        self.assertFalse(result.acquired)
        self.assertTrue(self.path.exists())
        self.assertEqual(json.loads(self.path.read_text())["session_id"], "other-session")

    def test_reacquire_by_same_session_is_idempotent(self) -> None:
        lock = SessionLock(self.client, "alice", "session-a")

        first = lock.acquire()
        second = lock.acquire()

        self.assertTrue(first.acquired)
        self.assertTrue(second.acquired)
        self.assertTrue(second.idempotent)

    def test_concurrent_acquire_has_only_one_winner(self) -> None:
        first = SessionLock(_FakeClient(self.saved_dir), "alice", "session-a")
        second = SessionLock(_FakeClient(self.saved_dir), "bob", "session-b")

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda lock: lock.acquire(), (first, second)))

        self.assertEqual(sum(result.acquired for result in results), 1)
        stored_session = json.loads(self.path.read_text(encoding="utf-8"))["session_id"]
        winner = next(result for result in results if result.acquired)
        self.assertEqual(stored_session, winner.session_id)

    def test_heartbeat_only_updates_own_lock(self) -> None:
        lock = SessionLock(self.client, "alice", "session-a")
        self.assertTrue(lock.acquire().acquired)
        before = json.loads(self.path.read_text())["heartbeat_at"]
        self.assertTrue(lock.heartbeat().acquired)
        after = json.loads(self.path.read_text())["heartbeat_at"]
        self.assertGreaterEqual(after, before)


if __name__ == "__main__":
    unittest.main()
