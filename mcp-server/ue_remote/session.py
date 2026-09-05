"""MCP セッションのガード、ロック、監査のライフサイクル管理。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from .audit import AuditLog, AuditResult
from .config import Config
from .guard import GuardResult, ProjectGuard
from .lock import LockResult, SessionLock
from .rc_client import RemoteControlClient


@dataclass(frozen=True)
class AccessResult:
    """ツールを実行してよいかと、拒否理由を表す。"""

    ok: bool
    message: str
    kind: str | None = None


class Session:
    """Remote Control への一つの接続セッションを管理する。"""

    def __init__(
        self,
        config: Config,
        *,
        client: Any | None = None,
        guard: Any | None = None,
        lock: Any | None = None,
        audit: Any | None = None,
    ) -> None:
        self.config = config
        self.client = client if client is not None else RemoteControlClient(config)
        self.guard = (
            guard
            if guard is not None
            else ProjectGuard(self.client, config.expected_project)
        )
        self.lock = (
            lock
            if lock is not None
            else SessionLock(
                self.client,
                config.developer_id,
                ttl_seconds=config.lock.ttl_seconds,
            )
        )
        self.audit = (
            audit
            if audit is not None
            else AuditLog(
                self.client,
                config.developer_id,
                self.lock.session_id,
                local_dir=config.audit.local_dir,
                remote_flush_every=config.audit.remote_flush_every,
            )
        )

        self._mutex = threading.RLock()
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._guard_result: GuardResult | None = None
        self._lock_result: LockResult | None = None
        self._owns_lock = False
        self._release_pending = False
        self._write_healthy = True
        self._health_message: str | None = None
        self._closed = False
        self._last_latency_ms: float | None = None
        self._audit_total = 0
        self._audit_ok = 0
        self._audit_errors = 0
        self._audit_write_failures = 0

        # プロジェクト確認はセッション開始時に一度だけ行い、以後は
        # ロック保持中のハートビートが結果を更新する。
        self.ensure_guard()

    def ensure_guard(self) -> GuardResult:
        """未確認ならプロジェクトを確認し、キャッシュした結果を返す。"""

        with self._mutex:
            if self._guard_result is None:
                started = time.perf_counter()
                try:
                    self._guard_result = self.guard.verify()
                except Exception as exc:
                    self._guard_result = GuardResult(
                        False,
                        f"プロジェクト確認に失敗しました: {type(exc).__name__}: {exc}",
                        self.config.expected_project,
                        None,
                        None,
                    )
                self._last_latency_ms = _elapsed_ms(started)
            return self._guard_result

    def ensure_lock(self) -> LockResult:
        """変更が必要になった時点でロックを遅延取得する。"""

        with self._mutex:
            return self._ensure_lock_locked()

    def _ensure_lock_locked(self) -> LockResult:
        if self._closed:
            return LockResult(False, "セッションはすでに終了しています")
        if not self._write_healthy:
            return LockResult(False, self._health_message or "セッションが不健全です")
        if self._owns_lock:
            assert self._lock_result is not None
            return self._lock_result

        started = time.perf_counter()
        try:
            result = self.lock.acquire()
        except Exception as exc:
            result = LockResult(
                False,
                f"ロック取得に失敗しました: {type(exc).__name__}: {exc}",
            )
        self._last_latency_ms = _elapsed_ms(started)
        self._lock_result = result
        if result.ok:
            self._owns_lock = True
            self._release_pending = True
            self._start_heartbeat_locked()
        return result

    def require_read(self) -> AccessResult:
        """参照系ツールの前提条件を確認する。"""

        with self._mutex:
            if self._closed:
                return AccessResult(False, "セッションはすでに終了しています", "session")
            guard_result = self.ensure_guard()
            if not guard_result.ok:
                return AccessResult(False, _guard_rejection(guard_result), "guard")
            return AccessResult(True, guard_result.warning or "参照を実行できます")

    def require_write(self) -> AccessResult:
        """変更系ツールのガードと遅延ロック取得を行う。"""

        with self._mutex:
            read_result = self.require_read()
            if not read_result.ok:
                return read_result
            if not self._write_healthy:
                return AccessResult(
                    False,
                    self._health_message or "ハートビート失敗後のため変更を拒否します",
                    "health",
                )
            lock_result = self._ensure_lock_locked()
            if not lock_result.ok:
                return AccessResult(False, _lock_rejection(lock_result), "lock")
            return AccessResult(True, "プロジェクトとセッションロックを確認しました")

    def record_tool_call(
        self,
        tool: str,
        params: Any,
        duration_ms: float,
        ok: bool,
        *,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> AuditResult:
        """ツール結果を監査へ記録し、セッション内の件数も更新する。"""

        with self._mutex:
            self._last_latency_ms = float(duration_ms)
            self._audit_total += 1
            if ok:
                self._audit_ok += 1
            else:
                self._audit_errors += 1
        try:
            result = self.audit.record_tool_call(
                tool,
                params,
                duration_ms,
                ok,
                error_type=error_type,
                error_message=error_message,
            )
        except Exception as exc:
            result = AuditResult(
                False,
                False,
                False,
                f"監査ログの記録に失敗しました: {type(exc).__name__}: {exc}",
            )
        if not result.ok:
            with self._mutex:
                self._audit_write_failures += 1
        return result

    def status(self) -> dict[str, Any]:
        """通信を増やさず、キャッシュ済みのセッション状態を返す。"""

        with self._mutex:
            guard_result = self._guard_result
            lock_result = self._lock_result
            heartbeat_alive = bool(
                self._heartbeat_thread and self._heartbeat_thread.is_alive()
            )
            return {
                "session_id": str(getattr(self.lock, "session_id", "")),
                "developer_id": self.config.developer_id,
                "closed": self._closed,
                "healthy_for_write": self._write_healthy and not self._closed,
                "health_message": self._health_message,
                "project": {
                    "ok": guard_result.ok if guard_result is not None else False,
                    "expected": (
                        guard_result.expected_project
                        if guard_result is not None
                        else self.config.expected_project
                    ),
                    "actual": guard_result.actual_project if guard_result else None,
                    "path": guard_result.project_path if guard_result else None,
                    "message": guard_result.message if guard_result else "未確認です",
                    "warning": guard_result.warning if guard_result else None,
                },
                "lock": {
                    "owned": self._owns_lock,
                    "heartbeat_running": heartbeat_alive,
                    "message": lock_result.message if lock_result else "まだ取得していません",
                    "developer_id": lock_result.developer_id if lock_result else None,
                    "hostname": lock_result.hostname if lock_result else None,
                    "heartbeat_at": lock_result.heartbeat_at if lock_result else None,
                    "age_seconds": lock_result.age_seconds if lock_result else None,
                },
                "last_latency_ms": self._last_latency_ms,
                "audit": {
                    "tool_calls": self._audit_total,
                    "successful": self._audit_ok,
                    "errors": self._audit_errors,
                    "write_failures": self._audit_write_failures,
                    "last_error": getattr(self.audit, "last_error", None),
                },
            }

    def release_lock(self) -> LockResult:
        """自分が保持中のロックを明示的に解放する。"""

        self._stop_heartbeat()
        with self._mutex:
            if not self._release_pending:
                result = LockResult(False, "このセッションはロックを保持していません")
                self._lock_result = result
                return result
            started = time.perf_counter()
            try:
                result = self.lock.release()
            except Exception as exc:
                result = LockResult(
                    False,
                    f"ロック解放に失敗しました: {type(exc).__name__}: {exc}",
                )
            self._last_latency_ms = _elapsed_ms(started)
            self._lock_result = result
            self._owns_lock = False
            if result.ok:
                self._release_pending = False
            return result

    def close(self) -> None:
        """ハートビートを止め、ロック解放後に監査要約を送る。"""

        with self._mutex:
            if self._closed:
                return
            self._closed = True
        self._stop_heartbeat()
        with self._mutex:
            release_pending = self._release_pending
        if release_pending:
            try:
                result = self.lock.release()
            except Exception as exc:
                result = LockResult(
                    False,
                    f"終了時のロック解放に失敗しました: {type(exc).__name__}: {exc}",
                )
            with self._mutex:
                self._lock_result = result
                self._owns_lock = False
                self._release_pending = False
        try:
            self.audit.flush()
        except Exception:
            # close は終了処理なので、監査失敗でプロセス終了を妨げない。
            pass

    def _start_heartbeat_locked(self) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="ue-remote-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        with self._mutex:
            thread = self._heartbeat_thread
            self._heartbeat_stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, float(self.config.lock.heartbeat_seconds) + 1.0))
        with self._mutex:
            if self._heartbeat_thread is thread:
                self._heartbeat_thread = None

    def _heartbeat_loop(self) -> None:
        interval = float(self.config.lock.heartbeat_seconds)
        while not self._heartbeat_stop.wait(interval):
            with self._mutex:
                if self._closed or not self._owns_lock:
                    return

                started = time.perf_counter()
                try:
                    lock_result = self.lock.heartbeat()
                except Exception as exc:
                    lock_result = LockResult(
                        False,
                        f"ハートビートに失敗しました: {type(exc).__name__}: {exc}",
                    )
                try:
                    guard_result = self.guard.verify()
                except Exception as exc:
                    guard_result = GuardResult(
                        False,
                        f"プロジェクト再確認に失敗しました: {type(exc).__name__}: {exc}",
                        self.config.expected_project,
                        None,
                        None,
                    )
                self._last_latency_ms = _elapsed_ms(started)
                self._lock_result = lock_result
                self._guard_result = guard_result
                if not lock_result.ok or not guard_result.ok:
                    self._write_healthy = False
                    details: list[str] = []
                    if not lock_result.ok:
                        details.append(_lock_rejection(lock_result))
                        self._owns_lock = False
                    if not guard_result.ok:
                        details.append(_guard_rejection(guard_result))
                    self._health_message = (
                        "ハートビート確認に失敗したため、以降の変更を拒否します。"
                        + " ".join(details)
                    )
                    return


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


def _guard_rejection(result: GuardResult) -> str:
    actual = result.actual_project or "取得不能"
    message = (
        f"プロジェクトガードが拒否しました。"
        f"実際に開かれているプロジェクト: {actual}。{result.message}"
    )
    return message + _connection_guidance(result.message)


def _lock_rejection(result: LockResult) -> str:
    holder_parts: list[str] = []
    if result.developer_id is not None:
        holder_parts.append(f"developer_id={result.developer_id}")
    if result.hostname is not None:
        holder_parts.append(f"ホスト名={result.hostname}")
    if result.age_seconds is not None:
        holder_parts.append(f"経過時間={result.age_seconds:.1f}秒")
    holder = "、".join(holder_parts)
    suffix = f" 保持者: {holder}。" if holder else ""
    message = f"セッションロックを取得できません。{suffix}{result.message}"
    return message + _connection_guidance(result.message)


def _connection_guidance(message: str) -> str:
    if "RemoteControlUnreachable" not in message and "Remote Control サーバ" not in message:
        return ""
    return (
        " NetBird が接続済みであることを確認し、その後に Unreal Editor と "
        "Remote Control Web Server を起動した順序を確認してください。"
    )
