# 能力プローブ実測結果（2026-09-05）

初回の実機接続。手元PC(WSL) → NetBird P2P → 大学PC の Unreal Editor。

- 接続先: `100.71.174.134:30010`
- スクリプト: `scripts/probe.py`
- 結果: **OK=6 / FAIL=2**

## 判明した事実

### エンジンは 5.5.4 だった（5.4.4 ではない）

```
5.5.4-40574608+++UE5+Release-5.5
```

当初の想定より1マイナーバージョン新しい。Phase 2 で既存プラグインを評価する際の
対応バージョン条件が変わるため、**5.5 系を前提に探すこと**。
なお Epic 公式のビルトイン Unreal MCP は 5.8 専用なので、依然として使えない。

### 動いたもの

| 検査 | 結果 | 所要 |
|---|---|---|
| TCP 到達性 | OK | 10 ms |
| `GET /remote/info` | OK | 411 ms |
| `ExecutePythonCommandEx`（任意 Python 実行） | **OK** | 339 ms |
| 環境情報の取得 | OK | 360 ms |
| `PUT /remote/search/assets` | OK | 346 ms |
| `PUT /remote/object/describe` | OK | 281 ms |

**任意 Python 実行が通った。** これが本構成の生命線なので、設計の前提が実測で裏付けられた。

`Saved/` 配下への排他的な一時ファイル作成と削除も成功（`saved_write_test.ok = true`）。
**セッションロックをロックファイルで実装する方式が成立する**ことが確認できた。

Python から見えるシンボルは以下がすべて存在。

```
K2Node, BlueprintEditorLibrary, EditorAssetLibrary, EditorLevelLibrary,
EditorActorSubsystem, PluginBlueprintLibrary, PythonScriptLibrary
```

ただし `K2Node` の存在は `hasattr` レベルの確認であり、**ノード追加・ピン配線が
できることを意味しない**。Phase 2 の必要性は依然として残る。

有効なプラグインには `PythonScriptPlugin` / `RemoteControl` /
`RemoteControlInterception` / `EditorScriptingUtilities` が含まれている。

### 壊れたもの: `PUT /remote/batch`

```
[FAIL] PUT /remote/batch: ConnectionResetError: [Errno 104] Connection reset by peer
[FAIL] レイテンシ測定: 成功した測定は 0/5 回
```

`/remote/batch` を呼んだ直後に接続がリセットされ、**以降エディタが一切応答しなくなった**
（NetBird の疎通は正常なまま、ping 6ms）。実質的にエディタをクラッシュさせている。

`GET /remote/info` のルート一覧には `Put /remote/batch` が載っているが、**使ってはいけない。**
往復削減は Python スクリプト側にループを寄せる方法だけで行う。

> プローブは `/remote/batch` を検査項目から外すか、`--skip-batch` のような
> 明示的なオプトインに変更する必要がある（Phase 1 で対応）。

### レイテンシ

個別リクエストは 280〜410 ms。NetBird の RTT は 6〜10 ms なので、**遅延の大半は
UE 側の処理とコネクション確立**であり、回線ではない。往復回数の削減が効く。

（5回連続測定は上記クラッシュの後だったため取得できていない。再測定が必要。）

## 利用可能なエンドポイント（`/remote/info` より抜粋）

```
Get      /remote/info
Put      /remote/object/call
Put      /remote/object/property        (+ append / insert / remove)
Put      /remote/object/describe
Put      /remote/search/assets
Put      /remote/object/thumbnail
Get      /remote/passphrase
Put      /remote/batch                  ← 存在するが使用禁止
（ほか /remote/preset/* 系）
```

`Get /remote/passphrase` が存在する。パスフレーズ要求の有無をクライアントが
問い合わせる口と思われる。Phase 1 でパスフレーズ採用を再検討する際の手がかりになる。

## 未確認・要確認

- **対象プロジェクトの取り違えの可能性。** 実行中のプロジェクトは
  `hitotsubashi_2025_3` だが、事前に共有された `DefaultEngine.ini` は
  `GameName=MyProject6` だった。どちらが本番の対象かを確定させる必要がある。
- レイテンシの再測定（クラッシュにより未取得）
- `K2Node` 経由でノード追加・ピン配線が可能かの実地確認
