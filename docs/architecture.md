# UE-remote アーキテクチャ

手元PCの AI エージェント（Claude Code / Codex）から、大学にある共用 Windows PC の
Unreal Engine を操作するための構成。

## 全体像

```text
手元PC (Windows + WSL) — 開発者ごとに1台             大学PC (Windows, 共用)
┌────────────────────────────────────┐              ┌──────────────────────────────────┐
│ Claude Code / Codex                │              │ NetBird (Windows サービス)       │
│  ├ 個人の AI アカウント認証        │              │  setup key で機械として登録       │
│  └ MCP Client                      │              │  NetBird IP: 100.71.174.134      │
│         │ stdio                    │              │                                  │
│         ▼                          │              │ Unreal Editor 5.5.4              │
│ ue-remote-mcp (本リポジトリ)       │   NetBird    │  ├ Remote Control API            │
│  ├ セッションロック取得/解放       │   P2P        │  │   bind 100.71.174.134:30010   │
│  ├ 監査ログ (誰が何をしたか)       │──WireGuard──▶│  ├ Python Editor Script Plugin   │
│  └ Remote Control HTTP クライアント│   8〜9ms     │  └ UEBlueprintBridge (C++, 自作) │
│                                    │              │      K2 ノードグラフ操作          │
│ NetBird IP: 100.71.232.171         │              │                                  │
└────────────────────────────────────┘              └──────────────────────────────────┘
```

大学PC で外部に開くポートは **Remote Control API の 30010 一本だけ**。しかもそれは
NetBird の仮想 IP にしか bind しないため、大学の LAN からもインターネットからも見えない。

## 確定した設計判断とその理由

### 1. MCP サーバは手元PC 側で動かす（大学PC 側では動かさない）

UE 5.8 には Epic 公式のビルトイン Unreal MCP プラグインがあり、エディタプロセス内で
`127.0.0.1:8000/mcp` を待ち受ける。しかし本プロジェクトは以下の理由でこれを採らない。

- **大学PC の UE は 5.5.4** であり、公式 MCP は 5.8 専用。採用するには UE のメジャー
  アップグレードと、使用中プラグインの 5.8 対応確認、VR コンテンツの移行検証が必要になる。
- **公式 MCP には任意 Python / コンソールコマンドを実行するツールが存在しない。**
  Epic が用意したツールセットに無い操作は、C++ で自前ツールセットを書かない限り実現できない。
  エスケープハッチが無い構成は、AI エージェントに作業させる用途では致命的に不便。
- 公式 MCP は非ループバックの `Origin` ヘッダを拒否し、ドキュメント上も
  "not designed for remote use" と明記されている。リモート利用は仕様外の使い方になる。

対して Remote Control API は、Epic の表現で「Blueprint と Python に公開されている
あらゆる関数」を呼べる。Python 実行を許可すれば **Unreal Python API 全体**が使えるため、
できることの上限が事実上無い。

**MCP サーバが手元にあることの副次的な利点**として、セッションロックと監査ログを
MCP サーバ内に自然に実装できる。大学PC 側に MCP を置く構成だと、ロックとログのために
手元に SSE 中継プロキシを別途書く必要があり（SSE のストリーミング中継はバッファリング
事故を起こしやすい）、結局手元の常駐プロセスは減らない。

### 2. トンネル（SSH / OpenSSH Server）を使わない

当初は「NetBird 上で SSH ポートフォワード」を想定していたが、不要になった。

- Remote Control API は `DefaultEngine.ini` の `[HTTPServer.Listeners] DefaultBindAddress`
  で bind アドレスを指定できる。ここに NetBird IP を書けば、NetBird のピアからのみ
  到達できる状態になる。Epic 自身が「Web Remote Control は LAN 内、または安全な VPN
  経由でのみ使うことを想定」としており、**これは公式が想定している使い方そのもの**。
- 結果として、大学PC 側の変更は **UE プロジェクトの .ini とプラグイン有効化だけ**に収まる。
  Windows のサービス・レジストリ・Firewall 設定には一切触らない。共用機を預かっている
  立場としてこれは大きい。

なお、NetBird には内蔵 SSH サーバ（`netbird up --allow-server-ssh`）があるが、
**Windows 上の SSH サーバはポートフォワードのリクエストを受け付けられない**という
制限が公式ドキュメントに明記されている。仮に SSH 方式を採るなら Windows OpenSSH Server
の導入が必須だった。

### 3. NetBird を使う（Cloudflare Tunnel を使わない）

| 方式 | 判定 |
|---|---|
| TryCloudflare（クイックトンネル） | URL が全世界に公開され認証が無い。加えて公式に「testing and development only」「Server-Sent Events 非対応」と明記 |
| Named Tunnel + Cloudflare Access | 認証は付くが Cloudflare 上に自前ドメイン（ゾーン）が必須。「有料ドメイン前提不可」の制約に抵触 |
| WARP-to-Tunnel（私設ネットワーク） | ドメインは不要だがクライアントに WARP が必須で、WSL2 での運用が現実的でない |

加えて Cloudflare 経由は edge で TLS が終端されるため、第三者が平文を見得る構造になる。
NetBird の P2P は end-to-end の WireGuard で第三者を経由せず、実測 8〜9ms。

### 4. C++ プラグイン `UEBlueprintBridge` を追加する

Remote Control + Python で大半の操作は賄えるが、**Blueprint のノードグラフ編集**だけは
穴が残る。`unreal.K2Node` は Python API に存在するものの実質読み取り止まりで、
ノードの追加とピンの配線は公開されていない。Blueprint アセットの作成・変数追加・
コンポーネント追加・コンパイルはできるが、ロジックの配線ができない。

そこで、K2 ノード操作を `BlueprintCallable` な UFUNCTION として公開する
エディタ専用 C++ プラグインを大学PC の UE プロジェクトに置く。

**重要な設計点**: このプラグインは独自の TCP リスナーを持たない。`BlueprintCallable`
な UFUNCTION は、クラスデフォルトオブジェクト経由で Remote Control から直接呼べる。

```json
{
  "objectPath": "/Script/UEBlueprintBridge.Default__UEBlueprintBridgeLibrary",
  "functionName": "AddCallFunctionNode",
  "parameters": { "...": "..." }
}
```

同時に Python からも `unreal.UEBlueprintBridgeLibrary.add_call_function_node(...)` として
見えるため、Python スクリプトの中に混ぜて使える。**開くポートは 30010 のままで増えない。**

### 4-1. まず既存プラグインを探し、無ければ書く

`UEBlueprintBridge` は**自作ありきにしない**。Phase 2 は「探索 → 評価 → 判断」から入る。
K2 ノード操作を扱う UE 用 MCP プラグインは既に複数公開されており（`chongdashu/unreal-mcp` など）、
ノード生成・ピン配線まで実装済みのものがあれば、そこを起点にしたほうが速く、実績もある。

評価基準は以下。

| 観点 | 見るところ |
|---|---|
| UE 5.5 対応 | `.uplugin` の `EngineVersion`、実際のビルド可否。5.5+ 専用 API に依存していないか |
| ライセンス | MIT / Apache-2.0 など、改変・再配布できるか |
| K2 ノード操作の実装範囲 | ノード追加・ピン配線・変数参照・コンパイルまで到達しているか。ここが薄いなら採用価値は低い |
| 通信方式 | **独自 TCP リスナーを持つものが多い**（例: 55557）。本構成は開くポートを 30010 一本に保ちたいので、リスナー部分を捨てて `BlueprintCallable` UFUNCTION だけ残せる設計か |
| メンテ状況 | 直近のコミット、Issue の放置具合 |

判断は3択。

1. **そのまま採用** — 基準を満たす。ただし独自リスナーは無効化し、Remote Control 経由に寄せる
2. **fork して削る** — ノード操作ロジックは流用し、通信層を落とす（最も現実的と見ている）
3. **自作** — 5.5 で動かない、ライセンスが不適合、実装が薄い、のいずれか

いずれの場合も、Remote Control の CDO 経由で呼べる形（上記 JSON の呼び出し形式）に揃える点は変えない。

## Remote Control API の使い方

### 任意 Python 実行（この仕組みの生命線）

```json
PUT /remote/object/call
{
  "objectPath": "/Script/PythonScriptPlugin.Default__PythonScriptLibrary",
  "functionName": "ExecutePythonCommandEx",
  "parameters": { "PythonCommand": "import unreal\nprint(unreal.SystemLibrary.get_engine_version())" }
}
```

実行可否・ログ出力・コマンド結果が返るため、MCP のツール結果としてそのまま利用できる。

### 往復回数の削減

素朴に「アクターを1体ずつ操作」すると呼び出し回数だけ往復が発生し、8〜9ms × N が積もる。
**`PUT /remote/batch` は使わない。** 実機（5.5.4）で `/remote/batch` を呼んだところ
`Connection reset by peer` が返り、**そのままエディタが応答不能になった**。
`/remote/info` のルート一覧には存在するが、コミュニティでも同じ症状が報告されている。

したがって往復削減の手段は1つに絞る。

- **Python にまとめる** — ループ処理は Python スクリプト側で回し、1往復で完結させる

実測では1リクエストあたり 280〜410ms かかっており（NetBird の RTT は 6〜10ms なので
大半は UE 側の処理とコネクション確立）、往復回数の削減は想像以上に効く。
N 個のアクターを操作するなら、N 回呼ぶのではなく Python スクリプトを1本投げる。

### 主なエンドポイント

| エンドポイント | 用途 |
|---|---|
| `GET /remote/info` | 利用可能なルート一覧。疎通確認にも使う |
| `PUT /remote/object/call` | UObject の関数呼び出し |
| `PUT /remote/object/property` | プロパティの read / write |
| `PUT /remote/object/describe` | UObject のプロパティ・関数のメタデータ |
| `PUT /remote/search/assets` | Asset Registry 検索 |
| ~~`PUT /remote/batch`~~ | **使用禁止**。エディタを応答不能にする（実機で再現） |

## セッションロック

同時編集を防ぐための排他制御。個人識別は必須要件ではないが、**ロックファイルには
開発者 ID を含める**。

理由は、クラッシュや回線断でロックが残留したときに、誰に確認すれば解除してよいかが
分からないと運用が詰まるため。監査ログのために開発者 ID はどのみち必要なので、
ロックに含める追加コストはゼロ。

- 置き場所: 大学PC の UE プロジェクト `Saved/` 配下（Remote Control 経由の Python で読み書き）
- 内容: 開発者 ID、ホスト名、取得時刻、ハートビート時刻
- ハートビート: MCP サーバが定期的に更新。TTL を超えた古いロックは、警告のうえ奪取可能とする

## 監査ログ

「誰がどれだけ作業したか」を測ることが目的。したがって**個人が特定できる必要がある**。

- 開発者 ID は環境変数で各自が設定する（手元PC にのみ保存）
- 手元PC に詳細ログ（全ツール呼び出しの入出力）を JSONL で保存
- 集計可能にするため、大学PC 側にも要約を追記する。ツール呼び出しごとに往復を増やさないよう、
  一定件数ごと、またはセッション終了時にまとめて送る

## Remote Control のセキュリティ設定（UE 5.5.4 実機で確認）

Remote Control には Epic 純正のアクセス制御があり、**既定のままでは localhost 以外を全て弾く**。
設定は `[/Script/RemoteControlCommon.RemoteControlSettings]`、書き込み先は
`DefaultEngine.ini` ではなく **`RemoteControl.ini`**（`UCLASS(Config=RemoteControl)` のため）。

| 設定 | 本構成での値 | 理由 |
|---|---|---|
| `bRestrictServerAccess` | ON | 許可 IP 以外を拒否させる。NetBird に加えた第2の層 |
| `AllowlistedClients` | 手元PC の NetBird IP | 既定は `127.0.0.1` のみ。ここを足さないと繋がらない |
| `bEnforcePassphraseForRemoteClients` | OFF | 後述 |
| `bAutoStartWebSocketServer` | OFF | WebSocket(30020) は bind が `0.0.0.0` で大学 LAN に開く。本構成では不要 |
| `bEnableRemotePythonExecution` | ON | この仕組みの生命線 |
| `bAllowConsoleCommandRemoteExecution` | ON | コンソールコマンド経由の操作に使う |

### パスフレーズを使わない判断

`bEnforcePassphraseForRemoteClients` を ON にすると非 localhost クライアントに
パスフレーズを要求できる。多層防御としては望ましいが、**クライアント側がどの HTTP
ヘッダにどう符号化して送るのかが Epic の公式ドキュメントに存在しない**。
`WebRemoteControl.cpp` の実装にしか無く、コミュニティでも「ドキュメントにもエラー
メッセージにも説明が無い」と報告されている。

仕様が確定していない認証を、自由に実験できない共用機に入れると、
失敗時に「設定が悪いのか実装が悪いのか」を切り分けられなくなる。
よって Phase 0 では OFF とし、代わりに以下の三層で守る。

1. NetBird の WireGuard ACL（暗号学的に、許可ピア以外は到達不能）
2. `DefaultBindAddress` による NetBird 仮想 IP への bind 限定
3. `AllowlistedClients` による送信元 IP 制限

Phase 1 でプローブを使ってヘッダ形式を実測できたら、パスフレーズの採用を再検討する。

## 満たしている制約

| 制約 | 満たし方 |
|---|---|
| 追加費用 0 円 | NetBird Cloud Free のみ。有料 VPN / VPS / ドメイン不要 |
| 大学PC に個人 AI アカウントを置かない | MCP サーバも AI 認証も手元PC 側だけに存在する |
| 大学ネットワークを変更しない | ポート開放も Firewall 変更も不要。NetBird は outbound のみで P2P を確立する |
| MCP を認証なしでインターネット公開しない | Remote Control は NetBird 仮想 IP にのみ bind。到達できるのは NetBird ACL で許可されたピアだけ |
| GUI 操作は Chrome Remote Desktop を継続 | AI 操作経路と GUI 操作経路は独立している |

## 出典

- [Remote Control for Unreal Engine](https://dev.epicgames.com/documentation/en-us/unreal-engine/remote-control-for-unreal-engine)
- [Remote Control API HTTP Reference](https://dev.epicgames.com/documentation/en-us/unreal-engine/remote-control-api-http-reference-for-unreal-engine)
- [Unreal MCP in Unreal Editor (UE 5.8)](https://dev.epicgames.com/documentation/unreal-engine/unreal-mcp-in-unreal-editor?lang=en-US)
- [NetBird SSH](https://docs.netbird.io/how-to/ssh)
- [TryCloudflare](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)
