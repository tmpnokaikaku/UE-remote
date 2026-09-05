"""Unreal Engine Remote Control 用 MCP stdio サーバ。"""

from __future__ import annotations

import logging
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import tools as core_tools
from .config import load_config
from .session import Session


_INSTRUCTIONS = (
    "Unreal Editor を Remote Control API 経由で操作します。参照系ツールは自由に使えますが、"
    "変更系ツールは大学PC上の排他ロックを遅延取得します。複数要素の処理は "
    "ue_execute_python の1本のスクリプトにまとめ、/remote/batch は使用しないでください。"
)

app = MCPServer("ue-remote-mcp", instructions=_INSTRUCTIONS)
_session: Session | None = None
_startup_error: str | None = None


def _initialise() -> None:
    global _session, _startup_error
    try:
        _session = Session(load_config())
    except Exception as exc:
        _startup_error = f"設定の読み込みに失敗しました: {type(exc).__name__}: {exc}"
        logging.getLogger(__name__).error(_startup_error)


def _run(function: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    if _session is None:
        return {
            "ok": False,
            "text": _startup_error or "MCP セッションを初期化できませんでした",
        }
    result = function(_session, *args, **kwargs)
    return {"ok": result.ok, "text": result.text}


@app.tool(description=core_tools.EXECUTE_PYTHON_DESCRIPTION)
def ue_execute_python(script: str) -> dict[str, Any]:
    """Unreal Editor 内で Python を実行する。"""

    return _run(core_tools.ue_execute_python, script)


@app.tool()
def ue_call_function(
    object_path: str,
    function_name: str,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """UObject の関数を呼び出します。変更系のためロックが必要です。"""

    return _run(core_tools.ue_call_function, object_path, function_name, parameters)


@app.tool()
def ue_set_property(
    object_path: str,
    property_name: str,
    value: Any,
) -> dict[str, Any]:
    """UObject のプロパティを書き込みます。変更系のためロックが必要です。"""

    return _run(core_tools.ue_set_property, object_path, property_name, value)


@app.tool()
def ue_get_property(object_path: str, property_name: str) -> dict[str, Any]:
    """UObject のプロパティをロックなしで読み取ります。"""

    return _run(core_tools.ue_get_property, object_path, property_name)


@app.tool()
def ue_describe_object(object_path: str) -> dict[str, Any]:
    """UObject のメタデータをロックなしで取得します。"""

    return _run(core_tools.ue_describe_object, object_path)


@app.tool()
def ue_search_assets(query: str, limit: int = 50) -> dict[str, Any]:
    """Asset Registry をロックなしで検索します。"""

    return _run(core_tools.ue_search_assets, query, limit)


@app.tool()
def ue_session_status() -> dict[str, Any]:
    """ガードで拒否せず、ロック・プロジェクト・監査の現況を返します。"""

    return _run(core_tools.ue_session_status)


@app.tool()
def ue_release_lock() -> dict[str, Any]:
    """このセッションが保持しているロックを明示的に解放します。"""

    return _run(core_tools.ue_release_lock)


def main() -> None:
    """MCP stdio サーバを起動し、終了時にセッションを閉じる。"""

    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    _initialise()
    try:
        app.run(transport="stdio")
    finally:
        if _session is not None:
            _session.close()


if __name__ == "__main__":
    main()
