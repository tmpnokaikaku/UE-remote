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

`/remote/batch` を呼んだ直後に接続がリセットされ、**エディタがクラッシュした**
（NetBird の疎通は正常なまま、ping 6ms）。クラッシュレポーターの内容:

```
Assertion failed: Pair != nullptr
[File:D:\build\++UE5\Sync\Engine\Source\Runtime\Core\Public\Containers\Map.h] [Line: 690]
```

`TMap` の要素引きが `nullptr` を返した箇所での assert であり、**エンジン側の不具合**。
リクエストの内容が不正だったわけではない。

`GET /remote/info` のルート一覧には `Put /remote/batch` が載っているが、**使ってはいけない。**
往復削減は Python スクリプト側にループを寄せる方法だけで行う。

> プローブは `/remote/batch` を検査項目から外すか、`--skip-batch` のような
> 明示的なオプトインに変更する必要がある（Phase 1 で対応）。

### レイテンシ（再測定済み）

エディタ再起動後、batch を避けて `GET /remote/info` を7回測定した。

```
        TCP connect   HTTP total
1回目     587 ms        822 ms     ← コールドスタート
2回目       9 ms        328 ms
3回目       6 ms        333 ms
4回目       6 ms        318 ms
5回目       7 ms        325 ms
6回目       9 ms        329 ms
7回目       6 ms        337 ms
```

**TCP は 6〜9 ms、HTTP は一貫して 320 ms 前後。** 回線は速く、UE 側で 320 ms 使っている。

320 ms は約 3 FPS に相当する。原因は**エディタの CPU スロットリング**とみられる。
Remote Control の HTTP 処理はゲームスレッド上で行われるため、
エディタのフレームレートがそのまま応答遅延になる。大学PC は誰も操作していない＝
常に非フォーカスなので、既定設定では常時スロットリングされた状態になる。

対処は Editor Preferences > Performance > **Use Less CPU when in Background** を
無効にすること。設定キーは `[/Script/UnrealEd.EditorPerProjectUserSettings]` の
`bThrottleCPUWhenNotForeground`（`EditorPerProjectUserSettings.ini`）。

**未検証**: 実際に無効化してどこまで縮むかは要測定。仮説の段階。

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

- `bThrottleCPUWhenNotForeground` を無効にした場合のレイテンシ改善幅
- `K2Node` 経由でノード追加・ピン配線が可能かの実地確認

## 決着した論点

- **対象プロジェクト**: `hitotsubashi_2025_3` で確定。`DefaultEngine.ini` の
  `GameName=MyProject6` は複製元の名残であり、識別子にならない。
  詳細と他プロジェクトの棚卸しは [projects.md](projects.md) を参照。
