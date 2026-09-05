"""Unreal Editor 側のファイルを使うセッション排他制御。"""

from __future__ import annotations

import json
import socket
import textwrap
import uuid
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any


_RESULT_MARKER = "UE_REMOTE_LOCK_RESULT:"


@dataclass(frozen=True)
class LockResult:
    """セッションロック操作の結果。"""

    acquired: bool
    message: str
    stolen: bool = False
    idempotent: bool = False
    developer_id: str | None = None
    hostname: str | None = None
    session_id: str | None = None
    heartbeat_at: str | None = None
    age_seconds: float | None = None

    @property
    def ok(self) -> bool:
        """呼び出し側で統一的に扱える成功フラグ。"""

        return self.acquired


class SessionLock:
    """``<Saved>/ue-remote/session.lock`` の所有権を管理する。"""

    def __init__(
        self,
        client: Any,
        developer_id: str,
        session_id: str | None = None,
        *,
        hostname: str | None = None,
        ttl_seconds: float = 300.0,
    ) -> None:
        if not developer_id:
            raise ValueError("developer_id は空にできません")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds は正の値にしてください")
        self.client = client
        self.developer_id = developer_id
        self.session_id = session_id or str(uuid.uuid4())
        self.hostname = hostname or socket.gethostname()
        self.ttl_seconds = float(ttl_seconds)

    def acquire(self, force: bool = False) -> LockResult:
        """ロックを1回のリモート Python 実行で取得する。"""

        script = self._acquire_script(force)
        return self._execute(script, default_message="ロックの取得結果を取得できませんでした")

    def heartbeat(self) -> LockResult:
        """自分が所有している場合に限りハートビートを更新する。"""

        script = self._maintenance_script("heartbeat")
        return self._execute(script, default_message="ハートビートを更新できませんでした")

    def release(self) -> LockResult:
        """自分が所有している場合に限りロックを削除する。"""

        script = self._maintenance_script("release")
        return self._execute(script, default_message="ロックを解放できませんでした")

    def _execute(self, script: str, *, default_message: str) -> LockResult:
        try:
            response = self.client.execute_python(script)
        except Exception as exc:  # 通信境界の例外をロック結果へ正規化する
            return LockResult(False, f"{default_message}: {type(exc).__name__}: {exc}")

        payload = _extract_payload(response, _RESULT_MARKER)
        if payload is None:
            detail = ""
            if not getattr(response, "ok", False):
                detail = "（リモート Python 実行に失敗しました）"
            return LockResult(False, default_message + detail)
        return LockResult(
            acquired=bool(payload.get("acquired", False)),
            message=str(payload.get("message", default_message)),
            stolen=bool(payload.get("stolen", False)),
            idempotent=bool(payload.get("idempotent", False)),
            developer_id=_optional_str(payload.get("developer_id")),
            hostname=_optional_str(payload.get("hostname")),
            session_id=_optional_str(payload.get("session_id")),
            heartbeat_at=_optional_str(payload.get("heartbeat_at")),
            age_seconds=_optional_float(payload.get("age_seconds")),
        )

    def _acquire_script(self, force: bool) -> str:
        values = {
            "developer_id": self.developer_id,
            "hostname": self.hostname,
            "session_id": self.session_id,
            "ttl_seconds": self.ttl_seconds,
            "force": bool(force),
            "marker": _RESULT_MARKER,
        }
        encoded = repr(json.dumps(values, ensure_ascii=False))
        return textwrap.dedent(
            f"""
            import datetime
            import errno
            import json
            import os
            import uuid
            import unreal

            _cfg = json.loads({encoded})
            _lock_dir = os.path.join(unreal.Paths.project_saved_dir(), "ue-remote")
            _lock_path = os.path.join(_lock_dir, "session.lock")
            os.makedirs(_lock_dir, exist_ok=True)

            def _iso_now():
                return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

            def _atomic_write(value):
                temp_path = _lock_path + ".tmp." + _cfg["session_id"] + "." + uuid.uuid4().hex
                try:
                    with open(temp_path, "w", encoding="utf-8", newline="\\n") as stream:
                        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temp_path, _lock_path)
                finally:
                    try:
                        os.unlink(temp_path)
                    except FileNotFoundError:
                        pass

            def _result(acquired, message, **extra):
                value = {{"acquired": acquired, "message": message}}
                value.update(extra)
                print(_cfg["marker"] + json.dumps(value, ensure_ascii=False, separators=(",", ":")))

            _now = _iso_now()
            _new_lock = {{
                "developer_id": _cfg["developer_id"],
                "hostname": _cfg["hostname"],
                "session_id": _cfg["session_id"],
                "acquired_at": _now,
                "heartbeat_at": _now,
            }}

            try:
                _fd = os.open(_lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except OSError as exc:
                if exc.errno != errno.EEXIST:
                    _result(False, "ロックファイルを作成できませんでした: " + str(exc))
                else:
                    try:
                        with open(_lock_path, "r", encoding="utf-8") as stream:
                            _current = json.load(stream)
                    except Exception as read_exc:
                        _result(False, "既存のロックファイルを読み取れませんでした: " + str(read_exc))
                    else:
                        _owner = _current.get("session_id")
                        if _owner == _cfg["session_id"]:
                            _result(
                                True,
                                "同じセッションがすでにロックを保持しています",
                                idempotent=True,
                                developer_id=_current.get("developer_id"),
                                hostname=_current.get("hostname"),
                                session_id=_owner,
                                heartbeat_at=_current.get("heartbeat_at"),
                                age_seconds=0.0,
                            )
                        else:
                            try:
                                _heartbeat = str(_current["heartbeat_at"])
                                _parsed = datetime.datetime.fromisoformat(_heartbeat.replace("Z", "+00:00"))
                                if _parsed.tzinfo is None:
                                    _parsed = _parsed.replace(tzinfo=datetime.timezone.utc)
                                _age = max(0.0, (datetime.datetime.now(datetime.timezone.utc) - _parsed).total_seconds())
                            except Exception as time_exc:
                                _result(False, "既存ロックの heartbeat_at が不正です: " + str(time_exc))
                            else:
                                _holder = {{
                                    "developer_id": _current.get("developer_id"),
                                    "hostname": _current.get("hostname"),
                                    "session_id": _owner,
                                    "heartbeat_at": _current.get("heartbeat_at"),
                                    "age_seconds": round(_age, 3),
                                }}
                                if _age <= _cfg["ttl_seconds"]:
                                    _result(False, "別のセッションがロックを保持しています", **_holder)
                                elif not _cfg["force"]:
                                    _result(False, "ロックは期限切れですが、奪取には force=True が必要です", **_holder)
                                else:
                                    _atomic_write(_new_lock)
                                    _result(
                                        True,
                                        "期限切れのロックを奪取しました",
                                        stolen=True,
                                        developer_id=_current.get("developer_id"),
                                        hostname=_current.get("hostname"),
                                        session_id=_cfg["session_id"],
                                        heartbeat_at=_now,
                                        age_seconds=round(_age, 3),
                                    )
            else:
                os.close(_fd)
                try:
                    _atomic_write(_new_lock)
                except Exception:
                    try:
                        os.unlink(_lock_path)
                    except FileNotFoundError:
                        pass
                    raise
                _result(
                    True,
                    "セッションロックを取得しました",
                    developer_id=_cfg["developer_id"],
                    hostname=_cfg["hostname"],
                    session_id=_cfg["session_id"],
                    heartbeat_at=_now,
                    age_seconds=0.0,
                )
            """
        )

    def _maintenance_script(self, action: str) -> str:
        values = {
            "session_id": self.session_id,
            "action": action,
            "marker": _RESULT_MARKER,
        }
        encoded = repr(json.dumps(values, ensure_ascii=False))
        return textwrap.dedent(
            f"""
            import datetime
            import json
            import os
            import uuid
            import unreal

            _cfg = json.loads({encoded})
            _lock_path = os.path.join(unreal.Paths.project_saved_dir(), "ue-remote", "session.lock")

            def _result(acquired, message, **extra):
                value = {{"acquired": acquired, "message": message}}
                value.update(extra)
                print(_cfg["marker"] + json.dumps(value, ensure_ascii=False, separators=(",", ":")))

            try:
                with open(_lock_path, "r", encoding="utf-8") as stream:
                    _current = json.load(stream)
            except FileNotFoundError:
                _result(False, "セッションロックが存在しません")
            except Exception as exc:
                _result(False, "セッションロックを読み取れませんでした: " + str(exc))
            else:
                if _current.get("session_id") != _cfg["session_id"]:
                    _result(
                        False,
                        "別のセッションのロックなので操作しませんでした",
                        developer_id=_current.get("developer_id"),
                        hostname=_current.get("hostname"),
                        session_id=_current.get("session_id"),
                        heartbeat_at=_current.get("heartbeat_at"),
                    )
                elif _cfg["action"] == "release":
                    os.unlink(_lock_path)
                    _result(True, "セッションロックを解放しました", session_id=_cfg["session_id"])
                else:
                    _now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
                    _current["heartbeat_at"] = _now
                    _temp_path = _lock_path + ".tmp." + _cfg["session_id"] + "." + uuid.uuid4().hex
                    try:
                        with open(_temp_path, "w", encoding="utf-8", newline="\\n") as stream:
                            stream.write(json.dumps(_current, ensure_ascii=False, separators=(",", ":")))
                            stream.flush()
                            os.fsync(stream.fileno())
                        os.replace(_temp_path, _lock_path)
                    finally:
                        try:
                            os.unlink(_temp_path)
                        except FileNotFoundError:
                            pass
                    _result(
                        True,
                        "ハートビートを更新しました",
                        developer_id=_current.get("developer_id"),
                        hostname=_current.get("hostname"),
                        session_id=_current.get("session_id"),
                        heartbeat_at=_now,
                    )
            """
        )


def _extract_payload(response: Any, marker: str) -> dict[str, Any] | None:
    parts: list[str] = []
    command_result = getattr(response, "command_result", None)
    if command_result is not None:
        parts.append(str(command_result))
    log_output = getattr(response, "log_output", None) or []
    if isinstance(log_output, str):
        parts.append(log_output)
    else:
        parts.extend(str(item) for item in log_output)

    decoder = json.JSONDecoder()
    for text in parts:
        start = 0
        while True:
            position = text.find(marker, start)
            if position < 0:
                break
            try:
                value, _ = decoder.raw_decode(text[position + len(marker) :].lstrip())
            except JSONDecodeError:
                start = position + len(marker)
                continue
            if isinstance(value, dict):
                return value
            start = position + len(marker)
    return None


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
