"""MCP SDK に依存しない Unreal Engine 操作ツール群。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from .errors import PythonExecutionError, RemoteControlUnreachable
from .session import AccessResult, Session


EXECUTE_PYTHON_DESCRIPTION = (
    "Unreal Editor 内で任意の Python を実行します。変更の有無にかかわらずロックが必要です。"
    "複数要素のループ処理は呼び出しを分けず、1本の Python スクリプトにまとめてください。"
    "UE 5.5.4 の不具合を避けるため /remote/batch は使用できません。"
)


@dataclass(frozen=True)
class ToolResult:
    """エージェントが次の行動を判断できるツール結果。"""

    text: str
    ok: bool


def ue_execute_python(session: Session, script: str) -> ToolResult:
    """ロックを取得して Unreal Editor 内で Python を実行する。"""

    def execute() -> ToolResult:
        result = session.client.execute_python(script)
        if not bool(getattr(result, "ok", False)):
            logs = list(getattr(result, "log_output", []) or [])
            return ToolResult(
                "Python の実行に失敗しました。log_output: "
                + json.dumps(logs, ensure_ascii=False, default=str),
                False,
            )
        data = {
            "command_result": getattr(result, "command_result", None),
            "log_output": getattr(result, "log_output", []),
            "raw": getattr(result, "raw", {}),
        }
        return _success("Python を実行しました", data)

    return _invoke(
        session,
        "ue_execute_python",
        {"script": script},
        write=True,
        action=execute,
    )


def ue_call_function(
    session: Session,
    object_path: str,
    function_name: str,
    parameters: dict[str, Any] | None = None,
) -> ToolResult:
    """ロックを取得して UObject の関数を呼び出す。"""

    params = {} if parameters is None else parameters
    return _invoke(
        session,
        "ue_call_function",
        {
            "object_path": object_path,
            "function_name": function_name,
            "parameters": params,
        },
        write=True,
        action=lambda: _success(
            "UObject の関数を呼び出しました",
            session.client.call_object(object_path, function_name, params),
        ),
    )


def ue_get_property(
    session: Session,
    object_path: str,
    property_name: str,
) -> ToolResult:
    """ロックなしで UObject のプロパティを読み取る。"""

    return _invoke(
        session,
        "ue_get_property",
        {"object_path": object_path, "property_name": property_name},
        write=False,
        action=lambda: _success(
            "プロパティを取得しました",
            session.client.get_property(object_path, property_name),
        ),
    )


def ue_set_property(
    session: Session,
    object_path: str,
    property_name: str,
    value: Any,
) -> ToolResult:
    """ロックを取得して UObject のプロパティを書き込む。"""

    return _invoke(
        session,
        "ue_set_property",
        {"object_path": object_path, "property_name": property_name, "value": value},
        write=True,
        action=lambda: _success(
            "プロパティを設定しました",
            session.client.set_property(object_path, property_name, value),
        ),
    )


def ue_describe_object(session: Session, object_path: str) -> ToolResult:
    """ロックなしで UObject のメタデータを取得する。"""

    return _invoke(
        session,
        "ue_describe_object",
        {"object_path": object_path},
        write=False,
        action=lambda: _success(
            "UObject の情報を取得しました",
            session.client.describe_object(object_path),
        ),
    )


def ue_search_assets(session: Session, query: str, limit: int = 50) -> ToolResult:
    """ロックなしで Asset Registry を検索する。"""

    return _invoke(
        session,
        "ue_search_assets",
        {"query": query, "limit": limit},
        write=False,
        action=lambda: _success(
            "アセットを検索しました",
            session.client.search_assets(query, limit),
        ),
    )


def ue_session_status(session: Session) -> ToolResult:
    """ガードで拒否せず、セッションの現況を返す。"""

    return _invoke(
        session,
        "ue_session_status",
        {},
        write=False,
        action=lambda: _success("セッション状態", session.status()),
        check_access=False,
    )


def ue_release_lock(session: Session) -> ToolResult:
    """このセッションが保持しているロックを明示的に解放する。"""

    def release() -> ToolResult:
        result = session.release_lock()
        if result.ok:
            return ToolResult(result.message, True)
        return ToolResult(f"ロックを解放できませんでした。{result.message}", False)

    return _invoke(
        session,
        "ue_release_lock",
        {},
        write=False,
        action=release,
    )


def _invoke(
    session: Session,
    tool: str,
    params: Any,
    *,
    write: bool,
    action: Callable[[], ToolResult],
    check_access: bool = True,
) -> ToolResult:
    """前提条件、例外の正規化、監査を全ツールで統一する。"""

    started = time.perf_counter()
    error_type: str | None = None
    try:
        if check_access:
            access = session.require_write() if write else session.require_read()
            if not access.ok:
                error_type = _access_error_type(access)
                result = ToolResult(access.message, False)
            else:
                result = action()
        else:
            result = action()
    except Exception as exc:
        error_type = type(exc).__name__
        result = ToolResult(_exception_text(exc), False)

    duration_ms = round((time.perf_counter() - started) * 1000.0, 3)
    if not result.ok and error_type is None:
        error_type = "ToolError"
    audit_result = session.record_tool_call(
        tool,
        params,
        duration_ms,
        result.ok,
        error_type=error_type,
        error_message=None if result.ok else result.text,
    )
    if not audit_result.ok:
        result = ToolResult(
            result.text + f"\n監査ログ警告: {audit_result.message}",
            result.ok,
        )
    return result


def _success(message: str, value: Any) -> ToolResult:
    return ToolResult(
        message + "。\n" + json.dumps(value, ensure_ascii=False, indent=2, default=str),
        True,
    )


def _access_error_type(result: AccessResult) -> str:
    return {
        "guard": "GuardRejected",
        "lock": "LockRejected",
        "health": "SessionUnhealthy",
        "session": "SessionClosed",
    }.get(result.kind, "AccessRejected")


def _exception_text(exc: Exception) -> str:
    if isinstance(exc, RemoteControlUnreachable):
        return (
            f"Remote Control に到達できません。{exc}。"
            "NetBird が接続済みであることを確認し、その後に Unreal Editor と "
            "Remote Control Web Server を起動した順序を確認してください。"
        )
    if isinstance(exc, PythonExecutionError):
        return (
            "Python の実行に失敗しました。log_output: "
            + json.dumps(exc.log_output, ensure_ascii=False, default=str)
            + (f"、command_result: {exc.command_result}" if exc.command_result else "")
        )
    return f"ツールの実行に失敗しました: {type(exc).__name__}: {exc}"
