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
      "args": []
    }
  }
}
```

> **`env` に `UE_REMOTE_DEVELOPER_ID` などを書かないこと。** 上記の
> `config.toml` があれば環境変数は不要（実機で確認済み）。登録側にも書くと
> 設定が2箇所に分散し、食い違ったときに監査ログの主体が変わってしまう。
> 環境変数は一時的な上書き（別のプロジェクトへ一度だけ繋ぐなど）に留める。

Claude CodeではCLIからも登録できます。

```bash
claude mcp add -s user --transport stdio ue-remote -- \
  /absolute/path/to/UE-remote/.venv/bin/ue-remote-mcp
```

> **`-s user` を付けること。** 省略するとプロジェクトスコープ（起動した
> ディレクトリ）に登録され、**別のディレクトリから Claude Code を起動すると
> ツールが現れない**。実際にこれを踏んだ: `UE-remote/` で登録したが、
> セッションは親の `remote-ue-dev/` で起動していたため見えなかった。
> `claude mcp list` は `✔ Connected` と出るのに、AI からはツールが見えない
> という分かりにくい形で失敗する。

登録できたかは、**実際に使うディレクトリで**次を実行して確認する。
`✔ Connected` と出れば成功。

```bash
claude mcp list
```

登録・変更した後は **Claude Code を再起動する**こと。MCP サーバはセッション
開始時に読み込まれるため、起動中のセッションには反映されない。

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
