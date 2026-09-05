# MCP サーバ設計（Phase 1）

手元PC で動く MCP サーバ `ue-remote-mcp`。AI エージェント（Claude Code / Codex）から
stdio で接続し、NetBird 越しに大学PC の Remote Control API を叩く。

## 構成

```text
Claude Code / Codex
   │ stdio (MCP)
   ▼
ue-remote-mcp
   ├ ProjectGuard  … 接続先プロジェクトが期待どおりか
   ├ SessionLock   … 同時編集の排他（大学PCのロックファイル）
   ├ AuditLog      … 誰がどれだけ作業したか
   └ RemoteControlClient … HTTP
        │ NetBird P2P
        ▼
   Unreal Editor 5.5.4 の Remote Control API :30010
```

## 実測を踏まえた前提

| 事実 | 設計への影響 |
|---|---|
| 1往復あたり median 約 23ms | 往復を無闇に増やさない。毎ツール呼び出しでのガード再確認はしない |
| `/remote/batch` がエディタを落とす | **使わない**。まとめたい処理は Python 1本に寄せる |
| 任意 Python 実行が可能 | ロック・監査ログのファイル操作もこれで行う。追加の口を開けない |
| `Saved/` へ排他的な作成・削除ができる | ロックの原子性を `O_CREAT|O_EXCL` で担保できる |

## 設定

`~/.config/ue-remote/config.toml`（環境変数で上書き可）。

```toml
host = "100.71.174.134"          # UE_REMOTE_HOST
port = 30010                     # UE_REMOTE_PORT
timeout_seconds = 15.0

developer_id = "ls"              # UE_REMOTE_DEVELOPER_ID  監査ログの主体
expected_project = "hitotsubashi_2025_3"   # UE_REMOTE_PROJECT  プロジェクトガードの期待値

[lock]
ttl_seconds = 300                # これを超えたハートビートは stale
heartbeat_seconds = 60

[audit]
local_dir = "~/.local/share/ue-remote/audit"
remote_flush_every = 20          # N 件ごとに大学PC側へ要約を送る
```

`developer_id` は**手元PC にのみ**置く。大学PC には監査ログの中身として現れるだけ。
`expected_project` は**ハードコードしない**（今年のプロジェクトは新規作成予定のため）。

## RemoteControlClient

唯一の HTTP 境界。他のコンポーネントはこれ以外から通信しない。

```python
class RemoteControlClient(Protocol):
    def call_object(self, object_path: str, function_name: str,
                    parameters: dict | None = None) -> dict: ...
    def execute_python(self, script: str) -> PythonResult: ...
    def get_property(self, object_path: str, property_name: str) -> dict: ...
    def set_property(self, object_path: str, property_name: str, value) -> dict: ...
    def search_assets(self, query: str, limit: int = 50) -> dict: ...
    def describe_object(self, object_path: str) -> dict: ...
    def info(self) -> dict: ...

@dataclass
class PythonResult:
    ok: bool
    log_output: list[str]
    command_result: str | None
    raw: dict
```

- `execute_python` は `exec(<script の repr>)` で1行に包んで送る
  （Remote Control のコマンドモード差異を回避するため。probe.py で実証済み）
- **`/remote/batch` は実装しない。** 呼べてしまう口を作らない
- 例外は `RemoteControlError` に正規化する（到達不能 / HTTP エラー / Python 実行失敗）

### マーカ方式で構造化データを取り出す

Python 実行の戻り値は UE のログ形式に依存するため、スクリプト側で
`print(MARKER + json.dumps(...))` し、応答文字列全体からマーカを検索して取り出す。
probe.py と同じ手法。

## ProjectGuard

**接続先が期待したプロジェクトかを確認し、違えば全ツールを拒否する。**

大学PC には紛らわしい名前のプロジェクトが複数ある（[projects.md](projects.md)）。
「扱い注意」と名付けられた去年の本番プロジェクトが開かれたまま放置されている横で、
AI エージェントが Python を流し込む事故を防ぐ。

- 確認方法: `unreal.Paths.get_project_file_path()` の**ベース名**と `expected_project` を比較
- 確認タイミング: **セッション開始時**と**ロックのハートビートごと**
  （毎ツール呼び出しでは行わない。往復が倍になるため）
- **失敗した確認結果はキャッシュしない。成功だけを TTL 付きでキャッシュする**
  （TTL はハートビート間隔）

> **なぜこの規則が要るか（実運用で踏んだ）**
>
> 当初は「一度確認したらキャッシュ」としていたが、**失敗もキャッシュしていた**。
> 起動時に大学PC へ到達できないとガードが失敗状態で固定され、その後 NetBird や
> UE が復旧しても二度と再確認されず、全ツールが永久に拒否され続けた。
>
> 「ハートビートで再確認する」という逃げ道は機能しない。**ハートビートは
> ロック取得後にしか動かず、ロック取得はガードを通らないと行われない**ため、
> 失敗状態から抜ける経路が存在しなかった。
>
> NetBird のセッション切れ、UE の再起動、ラップトップのスリープはいずれも
> 日常的に起きる。**失敗を状態として持たない**ことが必要。
- 不一致なら全ツールを拒否し、実際に開かれているプロジェクト名を明示する
- `expected_project` が未設定なら、起動時に実際の値を報告して**警告付きで通す**
  （初回セットアップを妨げないため）

## SessionLock

大学PC の `<Saved>/ue-remote/session.lock`（JSON）。

```json
{
  "developer_id": "ls",
  "hostname": "ls-laptop",
  "session_id": "<uuid>",
  "acquired_at": "2026-09-05T17:00:00Z",
  "heartbeat_at": "2026-09-05T17:04:00Z"
}
```

**ロックファイルに開発者 ID を含める。** 個人識別は排他制御そのものには不要だが、
残留ロックを見つけたとき誰に確認すればよいか分からないと運用が詰まる。
監査ログのために ID はどのみち必要なので追加コストはゼロ。

### 取得

Python 1本で完結させる（往復1回）。

1. `os.open(path, O_CREAT|O_EXCL|O_WRONLY)` を試す → 成功なら取得
2. `EEXIST` なら既存を読む
   - 自分の `session_id` → 再取得（冪等）
   - `heartbeat_at` が TTL 内 → **拒否**。保持者の ID・ホスト名・経過時間を返す
   - TTL 超過（stale）→ 奪取可能。ただし**既定では奪わない**。
     `force=True` を明示されたときだけ奪い、監査ログに `lock_stolen` を残す

### 維持・解放

- ハートビート: `heartbeat_seconds` ごとに `heartbeat_at` を更新。同時に ProjectGuard を再確認
- 解放: サーバ終了時に、**自分の `session_id` と一致する場合のみ**削除する
  （他人のロックを消さない）
- 書き込みは一時ファイル + `os.replace` で原子的に行う

## AuditLog

**目的は「誰がどれだけ作業したか」を測ること。** したがって個人が特定できる必要がある。

### 手元PC（詳細）

`~/.local/share/ue-remote/audit/YYYY-MM-DD.jsonl` に1行1イベント。

```json
{"ts":"...","developer_id":"ls","session_id":"...","event":"tool_call",
 "tool":"ue_execute_python","duration_ms":31.2,"ok":true,
 "params_digest":"...","params_preview":"import unreal…"}
```

- 入力は全文ではなく**先頭 N 文字のプレビュー + ハッシュ**を残す
  （ログの肥大と、うっかり秘密が混ざるのを避ける）
- 失敗時はエラー種別とメッセージを残す

### 大学PC（要約）

`<Saved>/ue-remote/audit-summary.jsonl` に追記。集計を大学PC 側で完結させるため。

```json
{"ts":"...","developer_id":"ls","session_id":"...",
 "window_start":"...","window_end":"...",
 "tool_calls":20,"errors":1,"active_seconds":312}
```

- `remote_flush_every` 件ごと、およびセッション終了時に送る
- **ツール呼び出しごとに往復を増やさない**
- 追記は Python 側で `"a"` モード + 1回の write

## ツール

| ツール | 用途 |
|---|---|
| `ue_execute_python` | 任意 Python 実行。**エスケープハッチ**。ループ処理はここに寄せる |
| `ue_call_function` | UObject の関数呼び出し |
| `ue_get_property` / `ue_set_property` | プロパティの読み書き |
| `ue_search_assets` | Asset Registry 検索 |
| `ue_describe_object` | UObject のメタデータ |
| `ue_session_status` | ロック保持者・プロジェクト・レイテンシの現況 |

すべてのツールは実行前に「ロックを保持しているか」「ProjectGuard を通過しているか」を
確認し、満たさなければ理由を添えて拒否する。

## 非目標（Phase 1 では作らない）

- `/remote/batch` のサポート — エンジンの不具合により使用禁止
- K2 ノードグラフの操作 — Phase 2
- 認証（Remote Control のパスフレーズ）— ヘッダ形式が公式非公開。
  NetBird ACL / bind 限定 / AllowlistedClients の三層で代替する
