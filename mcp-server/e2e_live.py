"""MCP サーバを stdio で実際に起動し、実機の Unreal Editor を操作できるか確認する。

ユニットテストは MCP レイヤを一切通らない。実際、SDK が v1 から v2 になった際の
API 変更（FastMCP -> MCPServer）は、このテストでしか検出できなかった。

    UE_REMOTE_HOST=... UE_REMOTE_DEVELOPER_ID=... UE_REMOTE_PROJECT=... \\
        python3 mcp-server/e2e_live.py

MCP SDK が入った環境で実行すること（`pip install -e mcp-server`）。
"""
import asyncio, os, sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = str(Path(__file__).resolve().parent.parent)
ok = fail = 0

def report(name, passed, detail=""):
    global ok, fail
    print(f"[{'OK  ' if passed else 'FAIL'}] {name}")
    if detail: print(f"        {detail}")
    if passed: ok += 1
    else: fail += 1

def text_of(res):
    parts = []
    for c in res.content:
        parts.append(getattr(c, "text", str(c)))
    return " ".join(parts)

async def main():
    env = dict(os.environ)
    env.update({
        "UE_REMOTE_HOST": os.environ.get("UE_REMOTE_HOST", "127.0.0.1"),
        "UE_REMOTE_PORT": os.environ.get("UE_REMOTE_PORT", "30010"),
        "UE_REMOTE_DEVELOPER_ID": os.environ.get("UE_REMOTE_DEVELOPER_ID", "e2e-test"),
        "UE_REMOTE_PROJECT": os.environ.get("UE_REMOTE_PROJECT", ""),
        "PYTHONPATH": f"{REPO}/mcp-server",
    })
    params = StdioServerParameters(command=sys.executable, args=["-m", "ue_remote.server"], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            report("initialize（stdio ハンドシェイク）", True)

            tools = await s.list_tools()
            names = sorted(t.name for t in tools.tools)
            report("list_tools", len(names) == 8, f"{len(names)} tools: {names}")

            st = await s.call_tool("ue_session_status", {})
            report("ue_session_status", True, text_of(st)[:300])

            # 参照系はロック無しで通るはず
            sa = await s.call_tool("ue_search_assets", {"query": "", "limit": 2})
            report("ue_search_assets（ロック不要）", not sa.is_error, text_of(sa)[:160])

            # 変更系 -> ここで初めてロックが取得されるはず
            ep = await s.call_tool("ue_execute_python", {
                "script": "import unreal\nprint('E2E:' + unreal.SystemLibrary.get_engine_version())"})
            body = text_of(ep)
            report("ue_execute_python（遅延ロック取得）", "5.5.4" in body, body[:200])

            st2 = await s.call_tool("ue_session_status", {})
            body2 = text_of(st2)
            report("status がロック保持を示す", env["UE_REMOTE_DEVELOPER_ID"] in body2, body2[:300])

            rl = await s.call_tool("ue_release_lock", {})
            report("ue_release_lock", not rl.is_error, text_of(rl)[:160])

    # 終了後にロックファイルが残っていないこと
    sys.path.insert(0, f"{REPO}/mcp-server")
    from ue_remote.config import Config
    from ue_remote.rc_client import RemoteControlClient
    c = RemoteControlClient(Config(host=env["UE_REMOTE_HOST"], port=int(env["UE_REMOTE_PORT"]), timeout_seconds=20.0,
                                   developer_id="check", expected_project=None))
    left = c.run_python_json(
        'import unreal, os, json\n'
        'd = os.path.join(unreal.Paths.project_saved_dir(), "ue-remote")\n'
        'print("__LS__" + json.dumps(sorted(os.listdir(d)) if os.path.isdir(d) else []))', "__LS__")
    report("終了後にロックが残留しない", "session.lock" not in left, f"Saved/ue-remote/ = {left}")

    print(f"\nSummary: OK={ok} FAIL={fail}")
    return 0 if fail == 0 else 1

sys.exit(asyncio.run(main()))
