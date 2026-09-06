"""Unreal Engine Remote Control 用 MCP stdio サーバ。"""

from __future__ import annotations

import logging
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import bp_tools
from . import tools as core_tools
from .config import load_config
from .session import Session


_INSTRUCTIONS = (
    "Unreal Editor を Remote Control API 経由で操作します。参照系ツールは自由に使えますが、"
    "変更系ツールは大学PC上の排他ロックを遅延取得します。複数要素の処理は "
    "ue_execute_python の1本のスクリプトにまとめ、/remote/batch は使用しないでください。"
    "Blueprint のノードグラフ操作は ue_bp_* を使用してください。この操作は "
    "ue_execute_python では原理的に不可能です。明示ツールにない操作は ue_bp_routes で "
    "一覧を確認してから ue_bp_call を使用し、変更系は Remote Control 側と同じ排他ロックを共有します。"
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


@app.tool(description=bp_tools.ROUTES_DESCRIPTION)
def ue_bp_routes() -> dict[str, Any]:
    """BlueprintMCP の許可済みルート一覧を取得します。"""

    return _run(bp_tools.ue_bp_routes)


@app.tool()
def ue_bp_call(
    route: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """許可済みの BlueprintMCP ルートを直接呼び出します。"""

    return _run(bp_tools.ue_bp_call, route, payload)


@app.tool()
def ue_bp_health() -> dict[str, Any]:
    """BlueprintMCP の稼働状態をロックなしで取得します。"""

    return _run(bp_tools.ue_bp_health)


@app.tool()
def ue_bp_list_blueprints(
    filter: str | None = None,
    parent_class: str | None = None,
    type: str = "all",
) -> dict[str, Any]:
    """Blueprint アセットの一覧をロックなしで取得します。"""

    return _run(bp_tools.ue_bp_list_blueprints, filter, parent_class, type)


@app.tool()
def ue_bp_get_blueprint(name: str) -> dict[str, Any]:
    """Blueprint の詳細をロックなしで取得します。"""

    return _run(bp_tools.ue_bp_get_blueprint, name)


@app.tool()
def ue_bp_get_graph(name: str, graph: str) -> dict[str, Any]:
    """Blueprint の指定グラフをロックなしで取得します。"""

    return _run(bp_tools.ue_bp_get_graph, name, graph)


@app.tool()
def ue_bp_search(
    query: str,
    path: str | None = None,
    max_results: int = 50,
) -> dict[str, Any]:
    """Blueprint 内のノードをロックなしで検索します。"""

    return _run(bp_tools.ue_bp_search, query, path, max_results)


@app.tool()
def ue_bp_get_pin_info(
    blueprint: str,
    node_id: str,
    pin_name: str,
) -> dict[str, Any]:
    """Blueprint ノードのピン情報をロックなしで取得します。"""

    return _run(bp_tools.ue_bp_get_pin_info, blueprint, node_id, pin_name)


@app.tool()
def ue_bp_list_functions(
    class_name: str,
    filter: str | None = None,
) -> dict[str, Any]:
    """クラスの Blueprint 呼び出し可能関数をロックなしで取得します。"""

    return _run(bp_tools.ue_bp_list_functions, class_name, filter)


@app.tool()
def ue_bp_create_blueprint(
    blueprint_name: str,
    package_path: str,
    parent_class: str,
    blueprint_type: str = "Normal",
) -> dict[str, Any]:
    """Blueprint アセットを作成します。変更系のためロックが必要です。"""

    return _run(
        bp_tools.ue_bp_create_blueprint,
        blueprint_name,
        package_path,
        parent_class,
        blueprint_type,
    )


@app.tool()
def ue_bp_create_graph(
    blueprint: str,
    graph_name: str,
    graph_type: str,
) -> dict[str, Any]:
    """Blueprint にグラフを作成します。変更系のためロックが必要です。"""

    return _run(bp_tools.ue_bp_create_graph, blueprint, graph_name, graph_type)


@app.tool()
def ue_bp_add_node(
    blueprint: str,
    graph: str,
    node_type: str,
    type_name: str | None = None,
    function_name: str | None = None,
    class_name: str | None = None,
    variable_name: str | None = None,
    cast_target: str | None = None,
    event_name: str | None = None,
    actor_class: str | None = None,
    comment: str | None = None,
    width: int | None = None,
    height: int | None = None,
    pos_x: int | None = None,
    pos_y: int | None = None,
) -> dict[str, Any]:
    """Blueprint グラフにノードを追加します。変更系のためロックが必要です。"""

    return _run(
        bp_tools.ue_bp_add_node,
        blueprint,
        graph,
        node_type,
        type_name,
        function_name,
        class_name,
        variable_name,
        cast_target,
        event_name,
        actor_class,
        comment,
        width,
        height,
        pos_x,
        pos_y,
    )


@app.tool()
def ue_bp_delete_node(blueprint: str, node_id: str) -> dict[str, Any]:
    """Blueprint グラフからノードを削除します。変更系のためロックが必要です。"""

    return _run(bp_tools.ue_bp_delete_node, blueprint, node_id)


@app.tool()
def ue_bp_connect_pins(
    blueprint: str,
    source_node_id: str,
    source_pin_name: str,
    target_node_id: str,
    target_pin_name: str,
) -> dict[str, Any]:
    """Blueprint ノード間のピンを接続します。変更系のためロックが必要です。"""

    return _run(
        bp_tools.ue_bp_connect_pins,
        blueprint,
        source_node_id,
        source_pin_name,
        target_node_id,
        target_pin_name,
    )


@app.tool()
def ue_bp_disconnect_pin(
    blueprint: str,
    node_id: str,
    pin_name: str,
    target_node_id: str | None = None,
    target_pin_name: str | None = None,
) -> dict[str, Any]:
    """Blueprint ノードのピン接続を解除します。変更系のためロックが必要です。"""

    return _run(
        bp_tools.ue_bp_disconnect_pin,
        blueprint,
        node_id,
        pin_name,
        target_node_id,
        target_pin_name,
    )


@app.tool()
def ue_bp_set_pin_default(
    blueprint: str,
    node_id: str,
    pin_name: str,
    value: str = "",
) -> dict[str, Any]:
    """入力ピンの既定値を設定します。変更系のためロックが必要です。"""

    return _run(bp_tools.ue_bp_set_pin_default, blueprint, node_id, pin_name, value)


@app.tool()
def ue_bp_add_variable(
    blueprint: str,
    variable_name: str,
    variable_type: str,
    category: str | None = None,
    is_array: bool = False,
    default_value: str | None = None,
) -> dict[str, Any]:
    """Blueprint に変数を追加します。変更系のためロックが必要です。"""

    return _run(
        bp_tools.ue_bp_add_variable,
        blueprint,
        variable_name,
        variable_type,
        category,
        is_array,
        default_value,
    )


@app.tool()
def ue_bp_validate_blueprint(blueprint: str) -> dict[str, Any]:
    """Blueprint をコンパイル検証します。変更系のためロックが必要です。"""

    return _run(bp_tools.ue_bp_validate_blueprint, blueprint)


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
