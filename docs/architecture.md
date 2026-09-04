# UE-remote アーキテクチャ

手元PCの AI エージェント（Claude Code / Codex）から、大学にある共用 Windows PC の
Unreal Engine を操作するための構成。

## 全体像

```text
手元PC (Windows + WSL) — 開発者ごとに1台             大学PC (Windows, 共用)
┌────────────────────────────────────┐              ┌──────────────────────────────────┐
│ Claude Code / Codex                │              │ NetBird (Windows サービス)       │
│  ├ 個人の AI アカウント認証        │              │  setup key で機械として登録       │
│  └ MCP Client                      │              │  NetBird IP: 100.71.168.109      │
│         │ stdio                    │              │                                  │
│         ▼                          │              │ Unreal Editor 5.4.4              │
│ ue-remote-mcp (本リポジトリ)       │   NetBird    │  ├ Remote Control API            │
│  ├ セッションロック取得/解放       │   P2P        │  │   bind 100.71.168.109:30010   │
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

- **大学PC の UE は 5.4.4** であり、公式 MCP は 5.8 専用。採用するには UE のメジャー
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
これを避ける手段が2つある。

1. **`PUT /remote/batch`** — 複数リクエストを1往復に束ねる
2. **Python にまとめる** — ループ処理は Python スクリプト側で回し、1往復で完結させる

大量操作では 2 を優先する。

### 主なエンドポイント

| エンドポイント | 用途 |
|---|---|
| `GET /remote/info` | 利用可能なルート一覧。疎通確認にも使う |
| `PUT /remote/object/call` | UObject の関数呼び出し |
| `PUT /remote/object/property` | プロパティの read / write |
| `PUT /remote/object/describe` | UObject のプロパティ・関数のメタデータ |
| `PUT /remote/search/assets` | Asset Registry 検索 |
| `PUT /remote/batch` | 複数リクエストの一括実行 |

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
