"""実機の Unreal Editor に対して Phase 3 の BlueprintMCP 統合を検証する。

ユニットテストは偽の HTTP を使うため、リクエストの形が本物の UE に
通るかを確認できない。これはそこを埋めるためのスクリプト。

設定は ``~/.config/ue-remote/config.toml`` から ``load_config()`` で読む。
``UE_REMOTE_HOST``、``UE_REMOTE_BLUEPRINT_PORT`` などの環境変数による
上書きも有効。

    # 参照系のみ
    python3 mcp-server/bp_smoke_live.py

    # 変更系も実行（大学PC のロックを取得し、使い捨て BP を書き換える）
    python3 mcp-server/bp_smoke_live.py --write

変更系は Phase 2 で作成済みの使い捨て Blueprint のノードコメントだけを
書き換え、**確認後に元の値へ戻す**。新しいアセットの作成と Blueprint の
コンパイルは行わない。
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ue_remote import bp_tools
from ue_remote.config import load_config
from ue_remote.session import Session
from ue_remote.tools import ToolResult


# 対象アセット: /Game/__ue_remote_test/BP_ue_remote_phase2_test
BLUEPRINT_NAME = "BP_ue_remote_phase2_test"
GRAPH_NAME = "EventGraph"

results: list[bool] = []


def check(name, fn, show=None):
    started = time.perf_counter()
    try:
        value = fn()
    except Exception as exc:
        print(f"[FAIL] {name} ({(time.perf_counter()-started)*1000:.0f} ms)")
        print(f"        {type(exc).__name__}: {exc}")
        results.append(False)
        return None
    print(f"[OK  ] {name} ({(time.perf_counter()-started)*1000:.0f} ms)")
    if show:
        print(f"        {show(value)}")
    results.append(True)
    return value


def expect(condition: bool, message: str) -> None:
    if not condition:
        print(f"        !! {message}")
        results.append(False)


def result_json(result: ToolResult) -> Any:
    """ToolResult の先頭メッセージを除き、JSON 部分を返す。"""

    _, separator, body = result.text.partition("\n")
    if not separator:
        raise ValueError("ToolResult に JSON 本文がありません")
    return json.loads(body)


def run_read_phase(session: Session) -> None:
    """ロックを取らずに参照系とルート拒否を検証する。"""

    print("--- フェーズ1: 参照系とルート制御 ---")

    routes_result = check(
        "ue_bp_routes()",
        lambda: bp_tools.ue_bp_routes(session),
        lambda v: f"ok={v.ok} routes={len(result_json(v)) if v.ok else 0}",
    )
    if routes_result is not None:
        expect(routes_result.ok, routes_result.text)
        if routes_result.ok:
            expect(len(result_json(routes_result)) == 57, "許可ルートが 57 件ではない")

    health_result = check(
        "ue_bp_health()",
        lambda: bp_tools.ue_bp_health(session),
        lambda v: v.text.splitlines()[0],
    )
    if health_result is not None:
        expect(health_result.ok, health_result.text)
        if health_result.ok:
            health = result_json(health_result)
            expect(health.get("status") == "ok", "status が ok ではない")
            expect(health.get("mode") == "editor", "mode が editor ではない")
            expect(health.get("blueprintCount", 0) > 0, "blueprintCount が 0 以下")

    list_result = check(
        "ue_bp_list_blueprints()",
        lambda: bp_tools.ue_bp_list_blueprints(session),
        lambda v: v.text.splitlines()[0],
    )
    if list_result is not None:
        expect(list_result.ok, list_result.text)
        if list_result.ok:
            blueprints = result_json(list_result).get("blueprints", [])
            expect(len(blueprints) >= 1, "Blueprint が 1 件も返らなかった")

    shutdown_result = check(
        "ue_bp_call(/api/shutdown) の HTTP 前拒否",
        lambda: bp_tools.ue_bp_call(session, "/api/shutdown", {}),
        lambda v: f"ok={v.ok} message={v.text}",
    )
    if shutdown_result is not None:
        expect(shutdown_result.ok is False, "/api/shutdown を拒否しなかった")
        expect(
            "呼び出せません" in shutdown_result.text
            or "使用できません" in shutdown_result.text,
            "使用できない理由が結果に含まれていない",
        )

    material_result = check(
        "ue_bp_call(/api/create-material) の対象外拒否",
        lambda: bp_tools.ue_bp_call(session, "/api/create-material", {}),
        lambda v: f"ok={v.ok} message={v.text}",
    )
    if material_result is not None:
        expect(material_result.ok is False, "/api/create-material を拒否しなかった")
        expect("Phase 3 の対象外" in material_result.text, "対象外の理由が含まれていない")

    classes_result = check(
        "ue_bp_call(/api/list-classes)",
        lambda: bp_tools.ue_bp_call(
            session, "/api/list-classes", {"filter": "Actor"}
        ),
        lambda v: v.text.splitlines()[0],
    )
    if classes_result is not None:
        expect(classes_result.ok, classes_result.text)


def run_write_phase(session: Session) -> None:
    """使い捨て Blueprint のコメント変更とロック保持を検証する。"""

    print("\n--- フェーズ2: 変更系 ---")
    comment = (
        "ue-remote Phase 3 smoke "
        + datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    graph_result = check(
        "ue_bp_get_graph()（変更前）",
        lambda: bp_tools.ue_bp_get_graph(session, BLUEPRINT_NAME, GRAPH_NAME),
        lambda v: v.text.splitlines()[0],
    )
    node_id: str | None = None
    original_comment = ""
    if graph_result is not None:
        expect(graph_result.ok, graph_result.text)
        if graph_result.ok:
            nodes = result_json(graph_result).get("nodes", [])
            expect(len(nodes) >= 2, "EventGraph のノードが 2 件未満")
            if nodes:
                # /api/graph はノード ID を "id" で返す（実機で確認）。
                # 書き込み側の引数名が "nodeId" なので取り違えやすい。
                node_id = nodes[0].get("id")
                expect(bool(node_id), "先頭ノードに id がない")
                original_comment = nodes[0].get("comment", "")

    if node_id:
        set_result = check(
            "ue_bp_call(/api/set-node-comment)",
            lambda: bp_tools.ue_bp_call(
                session,
                "/api/set-node-comment",
                {
                    "blueprint": BLUEPRINT_NAME,
                    "nodeId": node_id,
                    "comment": comment,
                },
            ),
            lambda v: v.text.splitlines()[0],
        )
        if set_result is not None:
            expect(set_result.ok, set_result.text)

        reread_result = check(
            "ue_bp_get_graph()（コメント読み戻し）",
            lambda: bp_tools.ue_bp_get_graph(session, BLUEPRINT_NAME, GRAPH_NAME),
            lambda v: v.text.splitlines()[0],
        )
        if reread_result is not None:
            expect(reread_result.ok, reread_result.text)
            if reread_result.ok:
                reread_nodes = result_json(reread_result).get("nodes", [])
                matching = [node for node in reread_nodes if node.get("id") == node_id]
                expect(bool(matching), "変更対象のノードが読み戻し結果にない")
                if matching:
                    expect(
                        matching[0].get("comment") == comment,
                        "設定したコメントが読み戻し結果に反映されていない",
                    )

        # 検証用のコメントを共用プロジェクトに残さない。実行のたびに
        # 実態とずれたコメントが積もると、次に読む人が混乱する。
        restore_result = check(
            "ue_bp_call(/api/set-node-comment)（元に戻す）",
            lambda: bp_tools.ue_bp_call(
                session,
                "/api/set-node-comment",
                {
                    "blueprint": BLUEPRINT_NAME,
                    "nodeId": node_id,
                    "comment": original_comment,
                },
            ),
            lambda v: v.text.splitlines()[0],
        )
        if restore_result is not None:
            expect(restore_result.ok, restore_result.text)

    status = check(
        "session.status()（ロック保持確認）",
        session.status,
        lambda v: json.dumps(v, ensure_ascii=False),
    )
    if status is not None:
        expect(status["lock"]["owned"] is True, "セッションがロックを保持していない")


def main() -> int:
    config = load_config()
    write = "--write" in sys.argv[1:]
    print(
        f"接続先: {config.host}:{config.blueprint_port}  "
        f"expected_project={config.expected_project}\n"
    )
    session = Session(config)

    try:
        run_read_phase(session)
        if write:
            try:
                run_write_phase(session)
            finally:
                released = check(
                    "session.release_lock()",
                    session.release_lock,
                    lambda v: f"ok={v.ok} message={v.message}",
                )
                if released is not None:
                    expect(released.ok, released.message)
                session.close()
        else:
            print("\nフェーズ2は省略しました（実行するには --write を指定）")
    finally:
        # 参照系のみの場合と、フェーズ2の終了処理自体が失敗した場合も閉じる。
        session.close()

    failed = len(results) - sum(results)
    print(f"\nSummary: OK={sum(results)} FAIL={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
