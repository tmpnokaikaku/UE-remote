# Phase 3 設計: BlueprintMCP を MCP サーバに統合する

Phase 2 で、C++ プラグイン BlueprintMCP（`:9847`）越しに Blueprint のノード追加とピン配線が
[実機で成立した](phase2-verified-2026-09-06.md)。Phase 3 では、それを Phase 1 で作った
MCP サーバ（[設計](mcp-design.md)）の**ロック・監査・プロジェクトガードの下に置く**。

```text
Claude Code / Codex
   │ stdio (MCP)
   ▼
ue-remote-mcp
   ├ ProjectGuard  ┐
   ├ SessionLock   ├ Phase 1 で実装済み。両方の口に等しく適用する
   ├ AuditLog      ┘
   ├ RemoteControlClient ──── NetBird ───▶ :30010  Remote Control API
   └ BlueprintClient     ──── NetBird ───▶ :9847   BlueprintMCP     ← Phase 3 で追加
```

## 口が2つになっても、ガードとロックは1つでよい

BlueprintMCP は**独自プロセスではない**。UE の `FHttpServerModule` を Remote Control と
共有する、同じエディタプロセス内のプラグインである（[根拠](../plugins/README.md#通信経路について)）。

したがって:

- **ProjectGuard は `:30010` 経由の確認だけでよい。** `unreal.Paths.get_project_file_path()` が
  返すのは同じプロセスのプロジェクトなので、`:9847` に確認の口を増やす意味がない
- **SessionLock は1つを共有する。** 排他したいのは「大学PC のエディタ」という単一の資源であって、
  ポートではない。`ue_execute_python` でアクタを動かす作業と、`ue_bp_add_node` でノードを足す作業は
  同じロックを取り合う
- **AuditLog も同じ経路に乗る。** どのノードを誰が足したかまで、既存の `record_tool_call` に残る

`:30010` が落ちていて `:9847` だけ生きている場合、ガードが通らないので Blueprint 系ツールも
拒否される。**これは正しい挙動**である。プロジェクトの同一性を確認できないまま
Blueprint を書き換えるほうが危険なため。

## 設定

`~/.config/ue-remote/config.toml` に2項目を足す。`host` は共用する（同じ大学PC）。

```toml
blueprint_port = 9847              # UE_REMOTE_BLUEPRINT_PORT
blueprint_timeout_seconds = 120.0  # RC の timeout_seconds とは別に持つ
```

**タイムアウトを分ける理由**: Remote Control の1往復は
[median 約 23ms](probe-result-2026-09-05.md) なので `timeout_seconds = 15.0` で足りるが、
BlueprintMCP の変更系は **Blueprint のコンパイルと保存を同期で行う**ため、
1リクエストが数十秒に達する。同じ値を使うと正常な操作がタイムアウトする。

## 応答の規約（実機で確認）

BlueprintMCP は**失敗しても HTTP 200 を返し、body に埋め込む**。

| 応答 | 意味 |
|---|---|
| `{"error": "<メッセージ>"}` | 失敗 |
| `{"success": false, ...}` | 失敗 |
| `{"success": true, ...}` | 成功 |
| `success` キーが無い（`/api/health`, `/api/graph` 等） | 成功 |

`BlueprintMCPServer.cpp:207` の `MakeErrorJson` と各ハンドラの `SetBoolField(TEXT("success"), ...)`
がこの形を作っている。**HTTP ステータスだけを見ると全部成功に見える**ので、
クライアント側で `error` / `success` を判定して例外に正規化する。

もう一点、`POST` は **body が無いと HTTP 411**（`missing_content_length_header`）になる。
引数が無いルートでも `{}` を送る。

## 何を公開するか

実機にあるのは **117 ルート**（`BindRoute` の数。upstream の TypeScript ラッパは 172 ルートを
参照しているが、**C++ に存在しないものが 55 ある**ので当てにしない）。

Phase 3 で対象にするのは **Blueprint グラフの領域だけ**。Material / Anim Blueprint / Groom /
Skeleton / Level / Widget は許可リストに入れない。

公開の形は **「厳選した明示ツール + 許可リスト付きの汎用エスケープハッチ」**。
Remote Control 側で `ue_execute_python` をエスケープハッチに置いた設計と同じ考え方で揃える。

- **明示ツール**（16 個）— よく使う操作。引数スキーマが AI から見えるので誤用が減る
- **`ue_bp_call(route, payload)`** — 許可リストにある残りのルート。
  `ue_bp_routes()` で一覧（ルート・verb・ロックの要否・説明）を引いてから使う

許可リストは `bp_routes.py` の1箇所に持ち、**明示ツールも例外なくそこを経由して
read / write を判定する**。分類が二箇所に散ると、片方だけロックを取り忘れる事故が起きる。

### 明示ツール（16 個）

| ツール | ルート | ロック |
|---|---|---:|
| `ue_bp_health` | `GET /api/health` | 不要 |
| `ue_bp_list_blueprints` | `GET /api/list` | 不要 |
| `ue_bp_get_blueprint` | `GET /api/blueprint` | 不要 |
| `ue_bp_get_graph` | `GET /api/graph` | 不要 |
| `ue_bp_search` | `GET /api/search` | 不要 |
| `ue_bp_get_pin_info` | `POST /api/get-pin-info` | 不要 |
| `ue_bp_list_functions` | `POST /api/list-functions` | 不要 |
| `ue_bp_create_blueprint` | `POST /api/create-blueprint` | 必要 |
| `ue_bp_create_graph` | `POST /api/create-graph` | 必要 |
| `ue_bp_add_node` | `POST /api/add-node` | 必要 |
| `ue_bp_delete_node` | `POST /api/delete-node` | 必要 |
| `ue_bp_connect_pins` | `POST /api/connect-pins` | 必要 |
| `ue_bp_disconnect_pin` | `POST /api/disconnect-pin` | 必要 |
| `ue_bp_set_pin_default` | `POST /api/set-pin-default` | 必要 |
| `ue_bp_add_variable` | `POST /api/add-variable` | 必要 |
| `ue_bp_validate_blueprint` | `POST /api/validate-blueprint` | 必要 |

引数名は**すべて C++ ハンドラの `GetStringField` / `TryGetNumberField` 等から読み取って
確認した**。upstream の TypeScript ラッパは参考にしたが、根拠には使っていない。

`ue_bp_routes` だけは**ガードを通さない**。返すのは静的な許可リストなので、
大学PC へ到達できない状況でも答えられる必要がある。ここでガードに拒否させると、
エージェントが「何が呼べるか」を知りたいときに限って一覧が見えなくなる。

### 許可リスト（57 ルート）

| 種別 | 件数 | ロック |
|---|---|---|
| 参照系 | 20 | 不要 |
| 変更系 | 37 | 必須 |

> `/api/snapshot-graph` は名前に反して `FFileHelper::SaveStringToFile` で大学PC の
> ディスクに書き込む（`BlueprintMCPHandlers_Snapshot.cpp:165`）。**変更系に分類した。**

### 明示的に拒否するルート

理由を添えて拒否する。許可リストに無いだけの「対象外」とは区別し、
なぜ叩けないかがエージェントに伝わるようにする。

| ルート | 理由 |
|---|---|
| `/api/shutdown` | エディタを終了させる。**共用PCで絶対に叩かない** |
| `/api/exec` | 任意のコンソールコマンド実行。RC 側の `ue_execute_python` に一本化する |
| `/api/delete-asset` | アセット削除。[UE を閉じた状態でファイルを消す運用](phase2-verified-2026-09-06.md#残置物要削除)にしている |
| `/api/start-pie` / `/api/stop-pie` / `/api/is-pie-running` | 共用PCの画面と入力を占有する |
| `/api/validate-all-blueprints` | 521 個の Blueprint を一括コンパイルし、エディタが長時間固まる |
| `/api/rescan` | 全アセット再スキャン。同上 |
| `/api/take-screenshot` / `/api/take-high-res-screenshot` | Phase 3 の対象外 |
| `/api/test-save` | 副作用が不明 |

## 実機検証（2026-09-06）

`mcp-server/bp_smoke_live.py` を大学PC に対して実行した。**`Session` を実際に通す**ので、
ガード・遅延ロック・ハートビート・監査まで含めた経路の検証になる。

| 確認 | 結果 |
|---|---|
| `ue_bp_routes` が 57 ルートを返す | ✅ |
| `ue_bp_health`（`status=ok` / `mode=editor` / 521 BP） | ✅ 17ms |
| `ue_bp_list_blueprints` | ✅ 73ms |
| `ue_bp_call("/api/shutdown")` を **HTTP を出す前に**拒否 | ✅ 0ms |
| `ue_bp_call("/api/create-material")` を対象外として拒否 | ✅ 0ms |
| `ue_bp_call("/api/list-classes")` | ✅ 37ms |
| `ue_bp_get_graph` → `/api/set-node-comment` → 読み戻しで一致 | ✅ 75ms / 80ms |
| 変更後にコメントを元の値へ戻す | ✅ 34ms |
| 変更系の初回でロックを遅延取得し、ハートビートが動く | ✅ |
| `release_lock` で解放 | ✅ 24ms |

**スモークは書き換えたコメントを必ず元に戻す。** 共用プロジェクトに
「実態とずれた検証用コメント」が実行のたびに積もると、次に読む人が混乱するため。

MCP クライアント（Claude Code）から実際のツールとしても叩き、
`ue_bp_health` / `ue_bp_get_graph` / `ue_bp_set_pin_default` / `ue_bp_call` と
ロックの取得・解放が通ることを確認した。

> **`/api/shutdown` には二層の防御がある。** MCP 経由で試したところ、
> こちらの許可リストに届く前に Claude Code 側の分類器が止めた。
> こちらの層が単体で機能することは `bp_smoke_live.py` で確認済み（0ms・HTTP 前拒否）。

ガードの実測値:

```json
{"expected": "hitotsubashi_2025_3", "actual": "hitotsubashi_2025_3", "ok": true}
```

### 踏んだ落とし穴: ノード ID のキー名

`/api/graph` はノード ID を **`id`** で返すが、書き込み系ルートの引数名は **`nodeId`**。

```json
{"nodes": [{"id": "CC19830542CA2DB60D1CF99ECA37E974", "class": "K2Node_Event", ...}]}
```

スモークの初版は読み取り側も `nodeId` と決め打ちしていたため、ノード ID を取り出せず
**変更系が丸ごと黙って飛ばされた**（ロックも取られないので「成功」に見えてしまう）。
読み書きで名前が違う点は upstream の仕様であり、直す先はこちら側にない。

## 非目標（Phase 3 では作らない）

- Material / Anim Blueprint / Groom / Skeleton / Level / Widget 系のルート
- BlueprintMCP の headless（commandlet）モード起動 — 大学PC のエディタは人が開いている前提
- upstream の TypeScript ラッパの利用 — ロック・監査・ガードを通らないため使わない
