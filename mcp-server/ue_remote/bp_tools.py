"""MCP SDK に依存しない BlueprintMCP 操作ツール群。"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from . import bp_routes
from .errors import (
    BlueprintHTTPError,
    BlueprintRequestError,
    BlueprintResponseError,
    BlueprintRouteError,
    BlueprintUnreachable,
)
from .session import AccessResult, Session
from .tools import ToolResult, _success


ROUTES_DESCRIPTION = (
    "BlueprintMCP で呼び出せる許可済みルートの一覧を返します。"
    "明示的な ue_bp_* ツールがない操作では、ue_bp_call を使う前にこの一覧で "
    "route・HTTP verb・ロック要否・説明を確認してください。"
)


def ue_bp_routes(session: Session) -> ToolResult:
    """ロックなしで BlueprintMCP の許可済みルート一覧を返す。"""

    return _invoke(
        session,
        "ue_bp_routes",
        {},
        write=False,
        action=lambda: _success("BlueprintMCP の許可済みルート一覧", bp_routes.describe()),
        # 静的な許可リストを返すだけなので、大学PC へ到達できない状況でも答える。
        # ここでガードに拒否させると、エージェントが「何が呼べるか」を
        # 知りたいときに限って一覧が見えなくなる。
        check_access=False,
    )


def ue_bp_call(
    session: Session,
    route: str,
    payload: dict[str, Any] | None = None,
) -> ToolResult:
    """許可リストにある BlueprintMCP ルートを直接呼び出す。"""

    return _call_route(session, "ue_bp_call", route, payload)


def ue_bp_health(session: Session) -> ToolResult:
    """ロックなしで BlueprintMCP の稼働状態を取得する。"""

    return _call_route(session, "ue_bp_health", "/api/health", None)


def ue_bp_list_blueprints(
    session: Session,
    filter: str | None = None,
    parent_class: str | None = None,
    type: str = "all",
) -> ToolResult:
    """ロックなしで Blueprint アセットの一覧を取得する。"""

    return _call_route(
        session,
        "ue_bp_list_blueprints",
        "/api/list",
        {"filter": filter, "parentClass": parent_class, "type": type},
    )


def ue_bp_get_blueprint(session: Session, name: str) -> ToolResult:
    """ロックなしで Blueprint の詳細を取得する。"""

    return _call_route(
        session,
        "ue_bp_get_blueprint",
        "/api/blueprint",
        {"name": name},
    )


def ue_bp_get_graph(session: Session, name: str, graph: str) -> ToolResult:
    """ロックなしで Blueprint の指定グラフを取得する。"""

    return _call_route(
        session,
        "ue_bp_get_graph",
        "/api/graph",
        {"name": name, "graph": graph},
    )


def ue_bp_search(
    session: Session,
    query: str,
    path: str | None = None,
    max_results: int = 50,
) -> ToolResult:
    """ロックなしで Blueprint 内のノードを検索する。"""

    return _call_route(
        session,
        "ue_bp_search",
        "/api/search",
        {"query": query, "path": path, "maxResults": max_results},
    )


def ue_bp_get_pin_info(
    session: Session,
    blueprint: str,
    node_id: str,
    pin_name: str,
) -> ToolResult:
    """ロックなしで Blueprint ノードのピン情報を取得する。"""

    return _call_route(
        session,
        "ue_bp_get_pin_info",
        "/api/get-pin-info",
        {"blueprint": blueprint, "nodeId": node_id, "pinName": pin_name},
    )


def ue_bp_list_functions(
    session: Session,
    class_name: str,
    filter: str | None = None,
) -> ToolResult:
    """ロックなしでクラスの Blueprint 呼び出し可能関数を取得する。"""

    return _call_route(
        session,
        "ue_bp_list_functions",
        "/api/list-functions",
        {"className": class_name, "filter": filter},
    )


def ue_bp_create_blueprint(
    session: Session,
    blueprint_name: str,
    package_path: str,
    parent_class: str,
    blueprint_type: str = "Normal",
) -> ToolResult:
    """ロックを取得して Blueprint アセットを作成する。"""

    return _call_route(
        session,
        "ue_bp_create_blueprint",
        "/api/create-blueprint",
        {
            "blueprintName": blueprint_name,
            "packagePath": package_path,
            "parentClass": parent_class,
            "blueprintType": blueprint_type,
        },
    )


def ue_bp_create_graph(
    session: Session,
    blueprint: str,
    graph_name: str,
    graph_type: str,
) -> ToolResult:
    """ロックを取得して Blueprint にグラフを作成する。"""

    return _call_route(
        session,
        "ue_bp_create_graph",
        "/api/create-graph",
        {"blueprint": blueprint, "graphName": graph_name, "graphType": graph_type},
    )


def ue_bp_add_node(
    session: Session,
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
) -> ToolResult:
    """ロックを取得して Blueprint グラフにノードを追加する。"""

    return _call_route(
        session,
        "ue_bp_add_node",
        "/api/add-node",
        {
            "blueprint": blueprint,
            "graph": graph,
            "nodeType": node_type,
            "typeName": type_name,
            "functionName": function_name,
            "className": class_name,
            "variableName": variable_name,
            "castTarget": cast_target,
            "eventName": event_name,
            "actorClass": actor_class,
            "comment": comment,
            "width": width,
            "height": height,
            "posX": pos_x,
            "posY": pos_y,
        },
    )


def ue_bp_delete_node(session: Session, blueprint: str, node_id: str) -> ToolResult:
    """ロックを取得して Blueprint グラフからノードを削除する。"""

    return _call_route(
        session,
        "ue_bp_delete_node",
        "/api/delete-node",
        {"blueprint": blueprint, "nodeId": node_id},
    )


def ue_bp_connect_pins(
    session: Session,
    blueprint: str,
    source_node_id: str,
    source_pin_name: str,
    target_node_id: str,
    target_pin_name: str,
) -> ToolResult:
    """ロックを取得して Blueprint ノード間のピンを接続する。"""

    return _call_route(
        session,
        "ue_bp_connect_pins",
        "/api/connect-pins",
        {
            "blueprint": blueprint,
            "sourceNodeId": source_node_id,
            "sourcePinName": source_pin_name,
            "targetNodeId": target_node_id,
            "targetPinName": target_pin_name,
        },
    )


def ue_bp_disconnect_pin(
    session: Session,
    blueprint: str,
    node_id: str,
    pin_name: str,
    target_node_id: str | None = None,
    target_pin_name: str | None = None,
) -> ToolResult:
    """ロックを取得して Blueprint ノードのピン接続を解除する。"""

    return _call_route(
        session,
        "ue_bp_disconnect_pin",
        "/api/disconnect-pin",
        {
            "blueprint": blueprint,
            "nodeId": node_id,
            "pinName": pin_name,
            "targetNodeId": target_node_id,
            "targetPinName": target_pin_name,
        },
    )


def ue_bp_set_pin_default(
    session: Session,
    blueprint: str,
    node_id: str,
    pin_name: str,
    value: str = "",
) -> ToolResult:
    """ロックを取得して Blueprint ノードの入力ピン既定値を設定する。"""

    return _call_route(
        session,
        "ue_bp_set_pin_default",
        "/api/set-pin-default",
        {
            "blueprint": blueprint,
            "nodeId": node_id,
            "pinName": pin_name,
            "value": value,
        },
    )


def ue_bp_add_variable(
    session: Session,
    blueprint: str,
    variable_name: str,
    variable_type: str,
    category: str | None = None,
    is_array: bool = False,
    default_value: str | None = None,
) -> ToolResult:
    """ロックを取得して Blueprint にメンバー変数を追加する。"""

    return _call_route(
        session,
        "ue_bp_add_variable",
        "/api/add-variable",
        {
            "blueprint": blueprint,
            "variableName": variable_name,
            "variableType": variable_type,
            "category": category,
            "isArray": is_array,
            "defaultValue": default_value,
        },
    )


def ue_bp_validate_blueprint(session: Session, blueprint: str) -> ToolResult:
    """ロックを取得して Blueprint をコンパイル検証する。"""

    return _call_route(
        session,
        "ue_bp_validate_blueprint",
        "/api/validate-blueprint",
        {"blueprint": blueprint},
    )


def _call_route(
    session: Session,
    tool_name: str,
    path: str,
    payload: dict[str, Any] | None,
) -> ToolResult:
    """許可リストを引き、read/write を判定し、BlueprintClient を叩いて監査に残す。"""

    cleaned = None
    if payload is not None:
        cleaned = {key: value for key, value in payload.items() if value is not None}

    started = time.perf_counter()
    error_type: str | None = None
    try:
        route = bp_routes.lookup(path)
        access = session.require_write() if route.write else session.require_read()
        if not access.ok:
            error_type = _access_error_type(access)
            result = ToolResult(access.message, False)
        else:
            result = _success(
                "BlueprintMCP のルートを呼び出しました",
                session.bp_client.request(route.path, route.verb, cleaned),
            )
    except Exception as exc:
        error_type = type(exc).__name__
        result = ToolResult(_exception_text(exc), False)

    duration_ms = round((time.perf_counter() - started) * 1000.0, 3)
    if not result.ok and error_type is None:
        error_type = "ToolError"
    audit_result = session.record_tool_call(
        tool_name,
        {"route": path, "payload": cleaned},
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


def _invoke(
    session: Session,
    tool: str,
    params: Any,
    *,
    write: bool,
    action: Callable[[], ToolResult],
    check_access: bool = True,
) -> ToolResult:
    """前提条件、例外の正規化、監査を BlueprintMCP ツールで統一する。"""

    started = time.perf_counter()
    error_type: str | None = None
    try:
        if not check_access:
            result = action()
        else:
            access = session.require_write() if write else session.require_read()
            if not access.ok:
                error_type = _access_error_type(access)
                result = ToolResult(access.message, False)
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


def _access_error_type(result: AccessResult) -> str:
    return {
        "guard": "GuardRejected",
        "lock": "LockRejected",
        "health": "SessionUnhealthy",
        "session": "SessionClosed",
    }.get(result.kind, "AccessRejected")


def _exception_text(exc: Exception) -> str:
    """BlueprintMCP 例外を次の行動が分かる日本語に整形する。"""

    if isinstance(exc, BlueprintUnreachable):
        return (
            f"BlueprintMCP に到達できません。{exc}。"
            "NetBird が接続済みか、Unreal Editor が起動しているか、"
            "BlueprintMCP プラグインが有効かを確認してください。"
        )
    if isinstance(exc, BlueprintRouteError):
        route = getattr(exc, "route", "不明")
        reason = getattr(exc, "reason", str(exc))
        return (
            f"BlueprintMCP ルート '{route}' は呼び出せません。{reason}。"
            "ue_bp_routes で許可済みルートを確認してください。"
        )
    if isinstance(exc, BlueprintRequestError):
        route = getattr(exc, "route", "不明")
        message = getattr(exc, "message", str(exc))
        raw = getattr(exc, "raw", None)
        detail = json.dumps(raw, ensure_ascii=False, default=str)
        return (
            f"BlueprintMCP がルート '{route}' の要求を拒否しました。{message}。"
            f"送信引数を確認してください。応答: {detail}"
        )
    if isinstance(exc, BlueprintHTTPError):
        return (
            f"BlueprintMCP との HTTP 通信に失敗しました。{exc}。"
            "Unreal Editor と BlueprintMCP プラグインの状態を確認してください。"
        )
    if isinstance(exc, BlueprintResponseError):
        return (
            f"BlueprintMCP の応答を解釈できませんでした。{exc}。"
            "プラグインのログとバージョンを確認してください。"
        )
    return f"ツールの実行に失敗しました: {type(exc).__name__}: {exc}"
