"""ローカル詳細監査と Unreal 側の集計監査。"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import textwrap
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PARAMS_PREVIEW_CHARS = 200


@dataclass(frozen=True)
class AuditResult:
    """監査処理の成否。失敗は例外にせず、この値で通知する。"""

    ok: bool
    local_written: bool = True
    remote_flushed: bool = False
    message: str = "監査ログを記録しました"


class AuditLog:
    """ツール呼び出しを記録し、一定件数ごとに要約を送る。"""

    def __init__(
        self,
        client: Any,
        developer_id: str,
        session_id: str,
        *,
        local_dir: str | os.PathLike[str] = "~/.local/share/ue-remote/audit",
        remote_flush_every: int = 20,
    ) -> None:
        if not developer_id:
            raise ValueError("developer_id は空にできません")
        if not session_id:
            raise ValueError("session_id は空にできません")
        if remote_flush_every <= 0:
            raise ValueError("remote_flush_every は正の値にしてください")
        self.client = client
        self.developer_id = developer_id
        self.session_id = session_id
        self.local_dir = Path(local_dir).expanduser()
        self.remote_flush_every = remote_flush_every
        self.last_error: str | None = None
        self._pending: list[dict[str, Any]] = []
        self._mutex = threading.Lock()

    def record_tool_call(
        self,
        tool: str,
        params: Any,
        duration_ms: float,
        ok: bool,
        *,
        error_type: str | None = None,
        error_message: str | None = None,
        ts: str | None = None,
    ) -> AuditResult:
        """ツール呼び出しを詳細ログへ記録する。監査失敗は送出しない。"""

        try:
            params_text = _params_text(params)
            event_ts = ts or _utc_now()
            event: dict[str, Any] = {
                "ts": event_ts,
                "developer_id": self.developer_id,
                "session_id": self.session_id,
                "event": "tool_call",
                "tool": tool,
                "duration_ms": float(duration_ms),
                "ok": bool(ok),
                "params_digest": hashlib.sha256(params_text.encode("utf-8")).hexdigest(),
                "params_preview": params_text[:PARAMS_PREVIEW_CHARS],
            }
            if not ok:
                if error_type is not None:
                    event["error_type"] = error_type
                if error_message is not None:
                    event["error_message"] = error_message
        except Exception as exc:
            return self._failure(f"監査イベントを作成できませんでした: {type(exc).__name__}: {exc}")

        with self._mutex:
            local_written = self._append_local(event)
            self._pending.append(event)
            remote_flushed = False
            remote_ok = True
            if len(self._pending) >= self.remote_flush_every:
                remote_ok = self._flush_remote_locked()
                remote_flushed = remote_ok

            if local_written and remote_ok:
                self.last_error = None
                return AuditResult(True, True, remote_flushed)
            messages: list[str] = []
            if not local_written:
                messages.append("ローカル監査ログの追記に失敗しました")
            if not remote_ok:
                messages.append("大学PC側の監査要約の追記に失敗しました")
            message = "。".join(messages)
            self.last_error = message
            return AuditResult(False, local_written, False, message)

    def log_tool_call(
        self,
        tool: str,
        params: Any,
        duration_ms: float,
        ok: bool,
        **error: Any,
    ) -> AuditResult:
        """``record_tool_call`` の呼びやすい別名。"""

        return self.record_tool_call(tool, params, duration_ms, ok, **error)

    def flush(self) -> AuditResult:
        """未送信の要約を大学PCへ送る。"""

        with self._mutex:
            if not self._pending:
                return AuditResult(True, True, False, "送信待ちの監査要約はありません")
            if self._flush_remote_locked():
                self.last_error = None
                return AuditResult(True, True, True, "監査要約を送信しました")
            return self._failure("大学PC側の監査要約の追記に失敗しました")

    def close(self) -> AuditResult:
        """セッション終了時に残りの要約を送る。"""

        return self.flush()

    def __enter__(self) -> AuditLog:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def _append_local(self, event: dict[str, Any]) -> bool:
        try:
            self.local_dir.mkdir(parents=True, exist_ok=True)
            date = _parse_timestamp(event["ts"]).date().isoformat()
            path = self.local_dir / f"{date}.jsonl"
            line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line)
            return True
        except Exception as exc:
            self.last_error = f"ローカル監査ログの追記に失敗しました: {type(exc).__name__}: {exc}"
            return False

    def _flush_remote_locked(self) -> bool:
        if not self._pending:
            return True
        summary = _summarize(self._pending, self.developer_id, self.session_id)
        line = json.dumps(summary, ensure_ascii=False, separators=(",", ":")) + "\n"
        script = textwrap.dedent(
            f"""
            import os
            import unreal

            _directory = os.path.join(unreal.Paths.project_saved_dir(), "ue-remote")
            os.makedirs(_directory, exist_ok=True)
            _path = os.path.join(_directory, "audit-summary.jsonl")
            with open(_path, "a", encoding="utf-8", newline="\\n") as _stream:
                _stream.write({line!r})
            """
        )
        try:
            response = self.client.execute_python(script)
            if not bool(getattr(response, "ok", False)):
                self.last_error = "大学PC側の監査要約の Python 実行に失敗しました"
                return False
        except Exception as exc:
            self.last_error = f"大学PC側の監査要約の送信に失敗しました: {type(exc).__name__}: {exc}"
            return False
        self._pending.clear()
        return True

    def _failure(self, message: str) -> AuditResult:
        self.last_error = message
        return AuditResult(False, False, False, message)


def _params_text(params: Any) -> str:
    if isinstance(params, str):
        return params
    if isinstance(params, bytes):
        return params.decode("utf-8", errors="replace")
    return json.dumps(
        params,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _summarize(
    events: list[dict[str, Any]], developer_id: str, session_id: str
) -> dict[str, Any]:
    start = _parse_timestamp(str(events[0]["ts"]))
    end = _parse_timestamp(str(events[-1]["ts"]))
    return {
        "ts": _utc_now(),
        "developer_id": developer_id,
        "session_id": session_id,
        "window_start": start.isoformat().replace("+00:00", "Z"),
        "window_end": end.isoformat().replace("+00:00", "Z"),
        "tool_calls": len(events),
        "errors": sum(1 for event in events if not event.get("ok", False)),
        "active_seconds": max(0.0, (end - start).total_seconds()),
    }
