# 対象プロジェクトの特定

大学PC には**紛らわしい名前の UE プロジェクトが複数存在する**。
どれを操作するかを取り違えると、本番データを壊しかねない。

## 現状の棚卸し（2026-09-05 時点）

**3つとも去年の先輩からの引き継ぎ。今年のプロジェクトはまだ存在しない。**

| フォルダ名 | エンジン | プロジェクトブラウザ上の表示 | 位置づけ |
|---|---|---|---|
| `hitotsubashi_2025_3/` | 5.5 | `hitotsubashi_2025_3` | 本番用ではなさそうなので**検証用サンドボックスとして使用中**。本仕組みの現在の接続先 |
| `MyProject6 本番用 扱い注意 5.5-2/` | 5.5 | `MyProject6` | 去年の本番用と思われる。**触らない** |
| `MyProject6 本番用 扱い注意/` | 5.4 | `MyProject6` | 去年の本番用と思われる。**触らない** |

**プロジェクトブラウザ上は 2 つが同じ `MyProject6` に見える。** 表示名では区別できない。

> `hitotsubashi_2025_3` は「壊しても問題なさそう」という判断で選んだ検証用であり、
> 今年の成果物を置く場所ではない。**今年分は別途新規作成し、
> 去年のデータを一部流用する予定。**

## 名前で判別してはいけない理由

`hitotsubashi_2025_3/Config/DefaultEngine.ini` には、フォルダ名と食い違う記述が残っている。

```ini
[URL]
GameName=MyProject6

[/Script/Engine.Engine]
+ActiveGameNameRedirects=(OldGameName="TP_VehicleAdvBP",NewGameName="/Script/MyProject6")
```

これは `MyProject6`（さらに元をたどると Vehicle Advanced テンプレート）を
**フォルダごとコピーして作られた**名残。`GameName` は複製時に追従しないため、
中身を見ても元の名前が出てくる。

つまり **`.ini` の記述も、ブラウザの表示名も、識別子として信用できない。**
信用できるのは**フォルダの絶対パス**だけ。

## 機械的な識別方法

Remote Control 経由で、いま繋がっているエディタが何を開いているかを直接問い合わせられる。
プローブの環境情報検査がこれを返す。

```python
unreal.Paths.get_project_file_path()
# -> .../Users/<user>/Documents/Unreal Projects/hitotsubashi_2025_3/hitotsubashi_2025_3.uproject
```

**判定にはこのパスを使う。**

## MCP サーバのプロジェクトガード（Phase 1 要件）

上記の状況を踏まえ、MCP サーバには以下を必須要件として入れる。

- 設定ファイルに**接続先プロジェクトの `.uproject` パスを明示的に固定する**
- ツールを実行する前に `unreal.Paths.get_project_file_path()` を問い合わせ、
  **固定値と一致しなければ全ツールの実行を拒否する**
- 拒否時は「期待したプロジェクトと違うものが開かれている」と明示し、
  実際に開かれているパスを表示する

ロックや監査ログと同格の安全機構として扱う。誰かが誤って
`MyProject6 本番用 扱い注意` を開いたまま放置した状態で、
別の開発者の AI エージェントが Python を流し込む事故を防ぐ。

## 今年のプロジェクトを新規作成するときに必要な作業

**この仕組みの設定はすべてプロジェクト単位**なので、新しいプロジェクトを作ったら
そのプロジェクトに対して同じ設定をやり直す必要がある。エンジン全体の設定ではない。

やり直しが要るもの（すべて対象プロジェクトの `Config/` 配下）:

| 設定 | ファイル | 手順 |
|---|---|---|
| Remote Control API / Python Editor Script Plugin の有効化 | `.uproject` | [setup-university-pc.md](setup-university-pc.md) Step 2 |
| Remote Control のセキュリティ設定 | `Config/DefaultRemoteControl.ini` | 同 Step 3 |
| bind アドレス | `Config/DefaultEngine.ini` | 同 Step 4 |
| CPU スロットリング無効化 | `Config/DefaultEditorSettings.ini` | 同 Step 3-7 |

検証用サンドボックス（`hitotsubashi_2025_3`）の `Config/` から該当セクションを
コピーするのが早い。**ただし `DefaultEngine.ini` の `[URL] GameName` は
コピーしないこと**（複製由来の名前の混乱がまた再生産される）。

新規作成時に決めておきたいこと。

1. **フォルダ名とプロジェクト名を一致させ、空白と日本語を使わない**
   （空白入りパスはツールチェーンで事故る。`MyProject6 本番用 扱い注意 5.5-2` は
   その典型）
2. **去年の3つは `archive/` 配下へ移す** — 現役ディレクトリには今年のものだけを置く。
   流用したいアセットは、移した先から明示的にインポートする
3. **バージョン管理** — 有効プラグインに `GitSourceControl` が含まれている。
   少なくとも `Config/` と `Source/` は Git で追えるようにする
   （`Content/` のバイナリアセットの扱いは別途検討）

## MCP サーバのプロジェクトガード（再掲）

上記のとおり接続先プロジェクトは**今後変わる**。プロジェクトガードの
固定値は設定ファイルで差し替えられる形にしておくこと。ハードコードしない。
