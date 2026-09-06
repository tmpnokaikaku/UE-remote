"""Phase 3 で公開する BlueprintMCP ルートの許可リスト。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .errors import BlueprintRouteError


@dataclass(frozen=True)
class Route:
    """BlueprintMCP ルートの HTTP 動詞、副作用、概要を表す。"""

    path: str
    verb: str
    write: bool
    summary: str


ALLOWED: dict[str, Route] = {
    route.path: route
    for route in (
        # 参照系
        Route("/api/health", "GET", False, "プラグインの稼働状態を取得する"),
        Route("/api/list", "GET", False, "Blueprint を一覧する（filter / parentClass / type）"),
        Route("/api/blueprint", "GET", False, "Blueprint の構造を取得する（name）"),
        Route("/api/graph", "GET", False, "ノードグラフを取得する（name / graph）"),
        Route("/api/search", "GET", False, "Blueprint 内のノードを検索する（query）"),
        Route("/api/search-by-type", "GET", False, "型の使用箇所を検索する（typeName）"),
        Route("/api/references", "GET", False, "アセットの参照元を検索する（assetPath）"),
        Route("/api/get-pin-info", "POST", False, "ピンの詳細を取得する（blueprint / nodeId / pinName）"),
        Route("/api/check-pin-compatibility", "POST", False, "2つのピンの接続可否を確認する（blueprint / sourceNodeId / sourcePinName / targetNodeId / targetPinName）"),
        Route("/api/list-classes", "POST", False, "利用可能なクラスを一覧する（filter / parentClass）"),
        Route("/api/list-functions", "POST", False, "クラスの Blueprint 関数を一覧する（className）"),
        Route("/api/list-properties", "POST", False, "クラスのプロパティを一覧する（className）"),
        Route("/api/list-interfaces", "POST", False, "実装済みインターフェースを一覧する（blueprint）"),
        Route("/api/list-event-dispatchers", "POST", False, "イベントディスパッチャーを一覧する（blueprint）"),
        Route("/api/list-components", "POST", False, "コンポーネントを一覧する（blueprint）"),
        Route("/api/get-node-comment", "POST", False, "ノードのコメントを取得する（blueprint / nodeId）"),
        Route("/api/find-disconnected-pins", "POST", False, "未接続ピンを検索する（blueprint / filter / snapshotId のいずれか）"),
        Route("/api/analyze-rebuild-impact", "POST", False, "モジュール再ビルドの影響を分析する（moduleName）"),
        Route("/api/diff-graph", "POST", False, "現在のグラフとスナップショットを比較する（blueprint / snapshotId）"),
        Route("/api/diff-blueprints", "POST", False, "2つの Blueprint の構造を比較する（blueprintA / blueprintB）"),
        # 変更系
        Route("/api/create-blueprint", "POST", True, "Blueprint を作成する（blueprintName / packagePath / parentClass）"),
        Route("/api/create-graph", "POST", True, "グラフを作成する（blueprint / graphName / graphType）"),
        Route("/api/delete-graph", "POST", True, "グラフを削除する（blueprint / graphName）"),
        Route("/api/rename-graph", "POST", True, "グラフ名を変更する（blueprint / graphName / newName）"),
        Route("/api/add-node", "POST", True, "ノードを追加する（blueprint / graph / nodeType）"),
        Route("/api/delete-node", "POST", True, "ノードを削除する（blueprint / nodeId）"),
        Route("/api/duplicate-nodes", "POST", True, "ノード群を複製する（blueprint / graph / nodeIds）"),
        Route("/api/move-node", "POST", True, "ノードを移動する（blueprint / nodeId / x / y）"),
        Route("/api/set-node-comment", "POST", True, "ノードのコメントを設定する（blueprint / nodeId / comment）"),
        Route("/api/connect-pins", "POST", True, "2つのピンを接続する（blueprint / sourceNodeId / sourcePinName / targetNodeId / targetPinName）"),
        Route("/api/disconnect-pin", "POST", True, "ピンの接続を解除する（blueprint / nodeId / pinName）"),
        Route("/api/set-pin-default", "POST", True, "ピンの既定値を設定する（blueprint / nodeId / pinName / value）"),
        Route("/api/refresh-all-nodes", "POST", True, "全ノードを更新して Blueprint を再コンパイルする（blueprint）"),
        Route("/api/add-variable", "POST", True, "メンバー変数を追加する（blueprint / variableName / variableType）"),
        Route("/api/remove-variable", "POST", True, "メンバー変数を削除する（blueprint / variableName）"),
        Route("/api/set-variable-metadata", "POST", True, "変数メタデータを設定する（blueprint / variable）"),
        Route("/api/change-variable-type", "POST", True, "変数の型を変更する（blueprint / variable / newType）"),
        Route("/api/add-function-parameter", "POST", True, "関数引数を追加する（blueprint / functionName / paramName / paramType）"),
        Route("/api/remove-function-parameter", "POST", True, "関数引数を削除する（blueprint / functionName / paramName）"),
        Route("/api/change-function-param-type", "POST", True, "関数引数の型を変更する（blueprint / functionName / paramName / newType）"),
        Route("/api/add-interface", "POST", True, "インターフェースを追加する（blueprint / interfaceName）"),
        Route("/api/remove-interface", "POST", True, "インターフェースを削除する（blueprint / interfaceName）"),
        Route("/api/add-event-dispatcher", "POST", True, "イベントディスパッチャーを追加する（blueprint / dispatcherName）"),
        Route("/api/add-component", "POST", True, "コンポーネントを追加する（blueprint / componentClass / name）"),
        Route("/api/remove-component", "POST", True, "コンポーネントを削除する（blueprint / name）"),
        Route("/api/reparent-blueprint", "POST", True, "Blueprint の親クラスを変更する（blueprint / newParentClass）"),
        Route("/api/set-blueprint-default", "POST", True, "Blueprint のクラス既定値を設定する（blueprint / property / value）"),
        Route("/api/replace-function-calls", "POST", True, "関数呼び出しの所有クラスを置換する（blueprint / oldClass / newClass）"),
        Route("/api/restore-graph", "POST", True, "スナップショットからグラフ接続を復元する（blueprint / snapshotId）"),
        Route("/api/snapshot-graph", "POST", True, "グラフのスナップショットをディスクへ保存する（blueprint）"),
        Route("/api/validate-blueprint", "POST", True, "Blueprint をコンパイルして検証する（blueprint）"),
        Route("/api/change-struct-node-type", "POST", True, "構造体ノードの型を変更する（blueprint / nodeId / newType）"),
        Route("/api/create-struct", "POST", True, "ユーザー定義構造体を作成する（assetPath）"),
        Route("/api/create-enum", "POST", True, "ユーザー定義列挙型を作成する（assetPath / values）"),
        Route("/api/add-struct-property", "POST", True, "構造体にプロパティを追加する（assetPath / name / type）"),
        Route("/api/remove-struct-property", "POST", True, "構造体からプロパティを削除する（assetPath / name）"),
        Route("/api/rename-asset", "POST", True, "アセットのパスまたは名前を変更する（assetPath / newPath）"),
    )
}


DENIED: dict[str, str] = {
    "/api/shutdown": "エディタを終了させる。共用PCでは絶対に叩かない",
    "/api/exec": "任意のコンソールコマンド実行。RC 側の ue_execute_python を使うこと",
    "/api/delete-asset": "アセット削除。UE を閉じた状態でファイルを消す運用にしている",
    "/api/start-pie": "共用PCの画面と入力を占有する",
    "/api/stop-pie": "共用PCの画面と入力を占有する",
    "/api/is-pie-running": "共用PCの画面と入力を占有する",
    "/api/validate-all-blueprints": "521 個の Blueprint を一括コンパイルしエディタが長時間固まる",
    "/api/rescan": "全アセット再スキャン。エディタが長時間固まる",
    "/api/take-screenshot": "Phase 3 の対象外",
    "/api/take-high-res-screenshot": "Phase 3 の対象外",
    "/api/test-save": "副作用が不明なため対象外",
}


def _normalise(path: str) -> str:
    """先頭のスラッシュを補い、許可リスト用の形へ揃える。"""

    return "/" + path.lstrip("/")


def lookup(path: str) -> Route:
    """許可済みルートを返し、拒否または対象外のルートなら例外を送出する。"""

    normalised = _normalise(path)
    route = ALLOWED.get(normalised)
    if route is not None:
        return route
    reason = DENIED.get(normalised, "Phase 3 の対象外")
    raise BlueprintRouteError(normalised, reason)


def describe() -> list[dict[str, Any]]:
    """許可ルートを MCP ツールから表示できる辞書のリストで返す。"""

    return [asdict(route) for route in ALLOWED.values()]
