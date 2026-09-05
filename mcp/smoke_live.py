"""実機の Unreal Editor に対して Phase 1 の実装を検証する。

ユニットテストは偽の HTTP サーバを使うため、**リクエストの形が本物の UE に
通るかを確認できない**。これはそこを埋めるためのスクリプト。

    UE_REMOTE_HOST=100.71.174.134 UE_REMOTE_DEVELOPER_ID=smoke \
    UE_REMOTE_PROJECT=hitotsubashi_2025_3 python3 mcp/smoke_live.py

読み取りが中心だが、SessionLock だけは実際にロックを取得・解放する
（後始末まで確認する）。エディタの状態を変更する set_property は実行しない。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ue_remote.config import load_config
from ue_remote.guard import ProjectGuard
from ue_remote.lock import SessionLock
from ue_remote.rc_client import RemoteControlClient

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


def main() -> int:
    config = load_config()
    print(f"接続先: {config.host}:{config.port}  expected_project={config.expected_project}\n")
    client = RemoteControlClient(config)

    check("info()", client.info,
          lambda v: f"{len(v.get('HttpRoutes', v.get('httpRoutes', [])))} routes")
    check("execute_python()",
          lambda: client.execute_python(
              "import unreal\nprint(unreal.SystemLibrary.get_engine_version())"),
          lambda v: f"ok={v.ok} log={v.log_output[:1]}")
    check("run_python_json()",
          lambda: client.run_python_json(
              'import json\nprint("__SMOKE__" + json.dumps({"a": 1, "b": [2, 3]}))', "__SMOKE__"),
          lambda v: json.dumps(v))
    check("search_assets()", lambda: client.search_assets("", limit=3),
          lambda v: f"keys={sorted(v)[:4]}")

    actors = check("レベル内アクタの取得", lambda: client.run_python_json(
        'import unreal, json\n'
        'actors = unreal.EditorActorSubsystem().get_all_level_actors()\n'
        'print("__A__" + json.dumps([a.get_path_name() for a in actors[:1]]))', "__A__"),
        lambda v: f"{len(v)} 件")
    if actors:
        path = actors[0]
        described = check("describe_object()", lambda: client.describe_object(path),
                          lambda v: f"{len(v.get('Properties', []))} properties")
        names = [p.get("Name") for p in (described or {}).get("Properties", [])]
        if names:
            check(f"get_property({names[0]})",
                  lambda: client.get_property(path, names[0]),
                  lambda v: json.dumps(v, ensure_ascii=False)[:120])

    print("\n--- ProjectGuard ---")
    ok_result = check("expected と一致",
                      lambda: ProjectGuard(client, config.expected_project).verify(),
                      lambda v: f"ok={v.ok} actual={v.actual_project}")
    if ok_result is not None:
        expect(ok_result.ok, "一致しているのに拒否された")
    ng_result = check("わざと不一致",
                      lambda: ProjectGuard(client, "__no_such_project__").verify(),
                      lambda v: f"ok={v.ok} message={v.message}")
    if ng_result is not None:
        expect(ng_result.ok is False, "不一致を検出できていない")
        expect(bool(ng_result.actual_project), "実際のプロジェクト名を返していない")

    print("\n--- SessionLock ---")
    mine = SessionLock(client, developer_id=config.developer_id,
                       ttl_seconds=config.lock_ttl_seconds)
    other = SessionLock(client, developer_id="__other_developer__",
                        ttl_seconds=config.lock_ttl_seconds)

    first = check("acquire()", mine.acquire, lambda v: f"ok={v.ok}")
    if first is not None:
        expect(first.ok, "ロックを取得できなかった")
    again = check("同一セッションの再取得は冪等", mine.acquire, lambda v: f"ok={v.ok}")
    if again is not None:
        expect(again.ok, "自分のロックの再取得が失敗した")
    stolen = check("別セッションからの acquire", other.acquire, lambda v: f"ok={v.ok}")
    if stolen is not None:
        expect(stolen.ok is False, "他人のロックを奪ってしまった")
    foreign = check("別セッションからの release", other.release, lambda v: f"ok={v.ok}")
    if foreign is not None:
        expect(foreign.ok is False, "他人のロックを解放してしまった")
    check("heartbeat()", mine.heartbeat, lambda v: f"ok={v.ok}")
    check("release()", mine.release, lambda v: f"ok={v.ok}")

    leftover = check("後始末の確認", lambda: client.run_python_json(
        'import unreal, os, json\n'
        'd = os.path.join(unreal.Paths.project_saved_dir(), "ue-remote")\n'
        'print("__LS__" + json.dumps(sorted(os.listdir(d)) if os.path.isdir(d) else []))',
        "__LS__"), lambda v: f"Saved/ue-remote/ = {v}")
    if leftover is not None:
        expect("session.lock" not in leftover, "ロックファイルが残留している")

    failed = len(results) - sum(results)
    print(f"\nSummary: OK={sum(results)} FAIL={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
