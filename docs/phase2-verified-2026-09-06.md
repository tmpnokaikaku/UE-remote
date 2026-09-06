# Phase 2 実機検証: ノード追加とピン配線（2026-09-06）

手元PC から NetBird 越しに、大学PC の Unreal Editor で Blueprint のロジックを組めることを確認した。

## 結果

| 操作 | エンドポイント | 結果 |
|---|---|---|
| Blueprint 作成 | `POST /api/create-blueprint` | ✅ |
| イベントノード追加 | `POST /api/add-node` (`OverrideEvent` / `ReceiveBeginPlay`) | ✅ |
| 関数呼び出しノード追加 | `POST /api/add-node` (`CallFunction` / `PrintString`) | ✅ |
| **実行ピンの配線** | `POST /api/connect-pins` | ✅ |
| グラフの読み戻し | `GET /api/graph` | ✅ |

配線の確認（読み戻した実データ）:

```json
// BeginPlay
{ "name": "then", "direction": "Output", "type": "exec",
  "connections": [{ "nodeId": "FACEC5CF...", "pinName": "execute" }] }

// PrintString
{ "name": "execute", "direction": "Input", "type": "exec",
  "connections": [{ "nodeId": "CC198305...", "pinName": "then" }] }
```

双方向に整合している。**[Python では原理的に不可能](blueprint-python-limits-2026-09-06.md)
だったピンの配線が、C++ プラグイン経由で成立した。**

プラグインの索引状況（`GET /api/health`）:

```json
{"status":"ok","mode":"editor","blueprintCount":521,"mapCount":18,
 "materialCount":892,"materialInstanceCount":440,"materialFunctionCount":858}
```

## 構成

```text
手元PC                     NetBird P2P            大学PC (UE 5.5.4)
ue-remote-mcp  ──────────────────────────────▶  :30010 Remote Control API
                                                    （任意 Python 実行、アクタ操作）
（今後ここに統合）──────────────────────────▶  :9847  BlueprintMCP
                                                    （ノード追加・ピン配線、117 ルート）
```

**どちらのポートも `[HTTPServer.Listeners] DefaultBindAddress` により
NetBird 仮想 IP にしか bind しない。** BlueprintMCP は独自 TCP リスナーを持たず
UE の `FHttpServerModule` を共有するため、この設定を自動的に継承する。

## 到達までに解決した問題

1. **Python でノードグラフに触れない**（[限界の実測](blueprint-python-limits-2026-09-06.md)）
   → C++ プラグインが不可避と確定
2. **既存プラグインの調査・選定**（[評価](phase2-plugin-evaluation.md)）
   → 自作を回避、`mirno-ehf/ue5-mcp` を選定
3. **UE 5.5 でビルドが通らない**（4ファイル）
   → [移植パッチ](../plugins/README.md)で解決。機能は1つも削っていない
4. **プラグインが Remote Control を巻き添えで落とす**
   → 起動確認が `127.0.0.1` 決め打ちで `DefaultBindAddress` を無視していた。
     失敗時に共有モジュールの全 listener を停止していた。同パッチで修正

## 残置物（要削除）

検証で作ったアセットが残っている。`EditorAssetLibrary.delete_asset` は
[エディタをクラッシュさせた実績](blueprint-python-limits-2026-09-06.md)があるため、
**UE を閉じた状態でファイルを削除するのが安全**。

- `Content/__ue_remote_probe_bp.uasset`
- `Content/__ue_remote_test/BP_ue_remote_phase2_test.uasset`

## 次にやること（Phase 3）

MCP サーバに BlueprintMCP のツールを統合する。ロック・監査ログ・プロジェクトガードは
[実装済み](mcp-design.md)なので、その上に乗せる形になる。

- `:9847` 用のクライアントを `mcp-server/ue_remote/` に追加
- 117 ルートすべてを MCP ツールとして公開する必要はない。
  Blueprint グラフ操作を中心に、実際に使うものを選んで公開する
- 変更系はロック必須、参照系はロック不要という既存の区別をそのまま適用する
- 監査ログの対象に含める（誰がどのノードを足したかまで残る）
