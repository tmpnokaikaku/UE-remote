# ue-remote-mcp

手元PCで動作し、NetBird越しに大学PCの Unreal Engine Remote Control API を操作する
stdio MCPサーバです。参照系ツールはロックなしで利用でき、変更系ツールの初回実行時に
大学PC上のセッションロックを取得します。

## 前提: NetBird の接続

大学PC に届かないと何も動かない。**まず NetBird が繋がっていることを確認する。**

```bash
netbird status
```

`Management: Connected` かつ相手ピアが見えていればよい。

### `Daemon status: NeedsLogin` と出たら

手元PC の NetBird は **SSO ログインで、セッションが 8〜24 時間で切れる**。
切れると MCP のツールが次のようなエラーを返す。

```
RemoteControlUnreachable: Remote Control サーバ 100.71.174.134:30010 に接続できません: TimeoutError
```

対処は再ログイン。**対話的な SSO なので、端末で自分で実行する必要がある。**

```bash
netbird up
```

### 毎日ログインし直したくない場合

NetBird ダッシュボードの **Peers → 該当ピア → Login expiration を無効化**する。
SSO の身元は保ったまま、期限だけ外せる。AI エージェントに継続的に作業させる
用途では実質必須。

> 大学PC 側は setup key による機械登録に切り替え済みなので、この問題は起きない
> （[setup-university-pc.md](../docs/setup-university-pc.md) Step 1）。
> 手元PC は個人の端末なので、身元の残る SSO のまま期限だけ外すほうが望ましい。

### 大学PC 側の前提

- NetBird が接続済みで、**その後に** Unreal Editor が起動していること（起動順が逆だと
  Remote Control が NetBird IP に bind できない）
- 対象プロジェクトが開かれたままであること

## インストール

Python 3.10以上の仮想環境へインストールします。

```bash
cd /absolute/path/to/UE-remote
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e ./mcp-server
```

> **`-e`（編集可能インストール）を付けること。** 省略すると `site-packages` へ
> ファイルがコピーされ、**ソースを直しても `ue-remote-mcp` の挙動は変わらない**。
> 実際にこれを踏んだ: 不具合を修正したのに直っていないように見え、原因の切り分けに
> 時間を使った。`git pull` で更新する運用でも同じ問題が起きる。
>
> 読み込み元は次で確認できる。リポジトリ内のパスが出ればよい。
>
> ```bash
> .venv/bin/python -c "import ue_remote, os; print(os.path.dirname(ue_remote.__file__))"
> ```

インストール後は `ue-remote-mcp` コマンドでstdioサーバを起動できます。標準出力は
MCP通信専用で、ログは標準エラーへ出力されます。

## 設定

手元PCの `~/.config/ue-remote/config.toml` に次の内容を保存します。環境変数名を
コメントに併記した項目は環境変数で上書きできます。

```toml
host = "100.71.174.134"          # UE_REMOTE_HOST
port = 30010                     # UE_REMOTE_PORT
timeout_seconds = 15.0

blueprint_port = 9847            # UE_REMOTE_BLUEPRINT_PORT  BlueprintMCP プラグイン
blueprint_timeout_seconds = 120.0

developer_id = "your-id"         # UE_REMOTE_DEVELOPER_ID
expected_project = "hitotsubashi_2025_3" # UE_REMOTE_PROJECT

[lock]
ttl_seconds = 300
heartbeat_seconds = 60

[audit]
local_dir = "~/.local/share/ue-remote/audit"
remote_flush_every = 20
```

> **`blueprint_timeout_seconds` を `timeout_seconds` と分けている理由。**
> Remote Control の1往復は median 約 23ms だが、BlueprintMCP の変更系は
> **Blueprint のコンパイルと保存を同期で行う**ため1リクエストが数十秒に達する。
> 同じ 15 秒を使うと正常な操作がタイムアウトする。

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

### Blueprint ノードグラフ（BlueprintMCP `:9847`）

Blueprint のノード追加とピン配線は **Python からは原理的に不可能**なため
（[根拠](../docs/blueprint-python-limits-2026-09-06.md)）、C++ プラグイン
BlueprintMCP 経由で行います。設計は
[phase3-blueprint-integration.md](../docs/phase3-blueprint-integration.md)。

| ツール | ロック | 用途 |
|---|---:|---|
| `ue_bp_routes` | 不要 | 呼び出せるルートの一覧（`ue_bp_call` の前に引く） |
| `ue_bp_call` | ルート次第 | 許可リストにあるルートを直接呼ぶエスケープハッチ |
| `ue_bp_health` | 不要 | プラグインの稼働状態と索引件数 |
| `ue_bp_list_blueprints` | 不要 | Blueprint の一覧 |
| `ue_bp_get_blueprint` | 不要 | Blueprint の構造 |
| `ue_bp_get_graph` | 不要 | ノードグラフ（ノード ID・ピン・接続） |
| `ue_bp_search` | 不要 | グラフ内のノード検索 |
| `ue_bp_get_pin_info` | 不要 | ピンの詳細 |
| `ue_bp_list_functions` | 不要 | クラスの Blueprint 呼び出し可能関数 |
| `ue_bp_create_blueprint` | 必要 | Blueprint アセットの作成 |
| `ue_bp_create_graph` | 必要 | 関数 / マクロ / カスタムイベントの作成 |
| `ue_bp_add_node` | 必要 | ノードの追加 |
| `ue_bp_delete_node` | 必要 | ノードの削除 |
| `ue_bp_connect_pins` | 必要 | ピンの配線 |
| `ue_bp_disconnect_pin` | 必要 | 配線の解除 |
| `ue_bp_set_pin_default` | 必要 | 入力ピンの既定値 |
| `ue_bp_add_variable` | 必要 | メンバー変数の追加 |
| `ue_bp_validate_blueprint` | 必要 | コンパイル検証 |

**ロックとプロジェクトガードは Remote Control 側と共有します。** BlueprintMCP は
別プロセスではなく同じエディタ内のプラグインなので、排他すべき資源は
「大学PC のエディタ」1つです。`ue_execute_python` でアクタを動かす作業と
`ue_bp_add_node` でノードを足す作業は、同じロックを取り合います。

明示ツールに無い操作は `ue_bp_routes` で一覧（全 57 ルート）を引いてから
`ue_bp_call(route, payload)` で呼びます。`/api/shutdown` や `/api/exec` など
共用PCで叩いてはいけないルートは、**HTTP を出す前に**理由付きで拒否されます。

> **ノード ID のキー名に注意。** `/api/graph` の応答はノード ID を `id` で返すが、
> 書き込み系ルートの引数名は `nodeId` である。取り違えやすい。

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

BlueprintMCP 側は専用のスモークがあります。既定では参照系とルート制御だけを試し、
`--write` を付けたときだけ実際にロックを取得して Blueprint を書き換えます。

```bash
python3 mcp-server/bp_smoke_live.py           # 参照系のみ
python3 mcp-server/bp_smoke_live.py --write   # 変更系も実行
```
