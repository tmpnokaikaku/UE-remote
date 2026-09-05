# ue-remote-mcp

手元PCで動作し、NetBird越しに大学PCの Unreal Engine Remote Control API を操作する
stdio MCPサーバです。参照系ツールはロックなしで利用でき、変更系ツールの初回実行時に
大学PC上のセッションロックを取得します。

## インストール

Python 3.10以上の仮想環境へインストールします。

```bash
cd /absolute/path/to/UE-remote
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install ./mcp-server
```

インストール後は `ue-remote-mcp` コマンドでstdioサーバを起動できます。標準出力は
MCP通信専用で、ログは標準エラーへ出力されます。

## 設定

手元PCの `~/.config/ue-remote/config.toml` に次の内容を保存します。環境変数名を
コメントに併記した項目は環境変数で上書きできます。

```toml
host = "100.71.174.134"          # UE_REMOTE_HOST
port = 30010                     # UE_REMOTE_PORT
timeout_seconds = 15.0

developer_id = "your-id"         # UE_REMOTE_DEVELOPER_ID
expected_project = "hitotsubashi_2025_3" # UE_REMOTE_PROJECT

[lock]
ttl_seconds = 300
heartbeat_seconds = 60

[audit]
local_dir = "~/.local/share/ue-remote/audit"
remote_flush_every = 20
```

`developer_id` は個人を識別する監査主体なので、必ず手元PCだけに置いてください。
NetBirdのsetup key、トークン、パスワードなどの秘密とともに、この設定ファイルを
リポジトリへコミットしないでください。

設定が不正でもMCPプロセス自体は起動し、各ツールが設定エラーを返します。

## Claude Code / Codexへの登録

実行ファイルは仮想環境内の絶対パスを指定するのが確実です。一般的な
`mcpServers` 形式の設定JSONは次のとおりです（Claude系クライアントなどで利用できます）。
これは手元PCのユーザー設定として保存し、プロジェクトにはコミットしないでください。

```json
{
  "mcpServers": {
    "ue-remote": {
      "type": "stdio",
      "command": "/absolute/path/to/UE-remote/.venv/bin/ue-remote-mcp",
      "args": [],
      "env": {
        "UE_REMOTE_DEVELOPER_ID": "your-id",
        "UE_REMOTE_PROJECT": "hitotsubashi_2025_3"
      }
    }
  }
}
```

Claude CodeではCLIからも登録できます。

```bash
claude mcp add --transport stdio \
  --env UE_REMOTE_DEVELOPER_ID=your-id \
  --env UE_REMOTE_PROJECT=hitotsubashi_2025_3 ue-remote -- \
  /absolute/path/to/UE-remote/.venv/bin/ue-remote-mcp
```

Codexでは次のCLI登録が使えます。

```bash
codex mcp add ue-remote \
  --env UE_REMOTE_DEVELOPER_ID=your-id \
  --env UE_REMOTE_PROJECT=hitotsubashi_2025_3 -- \
  /absolute/path/to/UE-remote/.venv/bin/ue-remote-mcp
```

Codexの設定ファイルはJSONではなく `~/.codex/config.toml` です。直接編集する場合は
次のように登録します。

```toml
[mcp_servers.ue-remote]
command = "/absolute/path/to/UE-remote/.venv/bin/ue-remote-mcp"
args = []

[mcp_servers.ue-remote.env]
UE_REMOTE_DEVELOPER_ID = "your-id"
UE_REMOTE_PROJECT = "hitotsubashi_2025_3"
```

## ツール

| ツール | ロック | 用途 |
|---|---:|---|
| `ue_execute_python` | 必要 | 任意Python実行。ループは1本のスクリプトへまとめる |
| `ue_call_function` | 必要 | UObjectの関数呼び出し |
| `ue_set_property` | 必要 | プロパティ書き込み |
| `ue_get_property` | 不要 | プロパティ読み取り |
| `ue_describe_object` | 不要 | UObjectのメタデータ取得 |
| `ue_search_assets` | 不要 | Asset Registry検索 |
| `ue_session_status` | 不要 | ロック、プロジェクト、レイテンシ、監査件数の報告 |
| `ue_release_lock` | 不要 | 自分のセッションロックの明示解放 |

`ue_session_status` を除く全ツールにProjectGuardが適用されます。ガードはセッション開始時と
ロックのハートビート時に確認され、毎ツール呼び出しでは追加通信しません。
`/remote/batch` はUE 5.5.4をクラッシュさせるため使用できません。

## テスト

リポジトリルートからユニットテストを実行します。MCP SDKが未インストールでも、
`session.py` と `tools.py` を含むユニットテストは実行できます。

```bash
python3 -m unittest discover -s mcp-server/tests -t mcp-server
```

大学PCでUnreal EditorとRemote Control Web Serverを起動し、NetBird接続後に実機スモーク
テストを実行します。テストは実際のセッションロックを一時的に取得して解放します。

```bash
UE_REMOTE_HOST=100.71.174.134 \
UE_REMOTE_DEVELOPER_ID=your-id \
UE_REMOTE_PROJECT=hitotsubashi_2025_3 \
python3 mcp-server/smoke_live.py
```
