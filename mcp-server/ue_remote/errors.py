"""ue-remote-mcp の HTTP クライアントで使う例外定義。"""

from __future__ import annotations

from typing import Any


class RemoteControlError(Exception):
    """Remote Control クライアントで発生する例外の基底クラス。"""


class RemoteControlUnreachable(RemoteControlError):
    """Remote Control サーバへの接続自体に失敗した。"""

    def __init__(self, host: str, port: int, cause: BaseException) -> None:
        self.host = host
        self.port = port
        self.cause = cause
        reason = getattr(cause, "reason", cause)
        super().__init__(
            f"Remote Control サーバ {host}:{port} に接続できません: "
            f"{type(reason).__name__}: {reason}"
        )


class RemoteControlHTTPError(RemoteControlError):
    """Remote Control サーバが 2xx 以外の HTTP 応答を返した。"""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        preview = body[:500]
        if len(body) > len(preview):
            preview += "…"
        detail = preview if preview else "応答本文なし"
        super().__init__(f"Remote Control API が HTTP {status_code} を返しました: {detail}")


class PythonExecutionError(RemoteControlError):
    """Remote Control には到達したが、送信した Python の実行に失敗した。"""

    def __init__(
        self,
        log_output: list[str],
        command_result: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        self.log_output = log_output
        self.command_result = command_result
        self.raw = raw
        result_detail = command_result or "結果不明"
        log_detail = " / ".join(log_output) if log_output else "ログ出力なし"
        super().__init__(
            f"Unreal Engine で Python の実行に失敗しました"
            f"（結果: {result_detail}、ログ: {log_detail}）"
        )


class RemoteControlResponseError(RemoteControlError):
    """Remote Control の成功応答を期待した形として解釈できなかった。"""


class BlueprintError(Exception):
    """BlueprintMCP クライアントで発生する例外の基底クラス。"""


class BlueprintUnreachable(BlueprintError):
    """BlueprintMCP サーバへの接続自体に失敗した。"""

    def __init__(self, host: str, port: int, cause: BaseException) -> None:
        self.host = host
        self.port = port
        self.cause = cause
        reason = getattr(cause, "reason", cause)
        super().__init__(
            f"BlueprintMCP サーバ {host}:{port} に接続できません: "
            f"{type(reason).__name__}: {reason}"
        )


class BlueprintHTTPError(BlueprintError):
    """BlueprintMCP サーバが 2xx 以外の HTTP 応答を返した。"""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        preview = body[:500]
        if len(body) > len(preview):
            preview += "…"
        detail = preview if preview else "応答本文なし"
        super().__init__(f"BlueprintMCP API が HTTP {status_code} を返しました: {detail}")


class BlueprintResponseError(BlueprintError):
    """BlueprintMCP の成功応答を JSON オブジェクトとして解釈できなかった。"""


class BlueprintRequestError(BlueprintError):
    """BlueprintMCP には到達したが、要求した処理に失敗した。"""

    def __init__(self, route: str, message: str, raw: dict[str, Any]) -> None:
        self.route = route
        self.message = message
        self.raw = raw
        super().__init__(f"BlueprintMCP の {route} が失敗しました: {message}")


class BlueprintRouteError(BlueprintError):
    """BlueprintMCP の許可リストにないルートが指定された。"""

    def __init__(self, route: str, reason: str) -> None:
        self.route = route
        self.reason = reason
        super().__init__(f"BlueprintMCP ルート {route} は使用できません: {reason}")
