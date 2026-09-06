# Phase 2: 既存プラグインの調査と評価（2026-09-06）

方針どおり自作より先に既存を探した。[architecture.md 4-1](architecture.md) の基準で評価。

## 候補の比較

ソースを実際に取得して読んだ結果。

| | UE 対応 | ライセンス | 最終コミット | ピン配線の実装 | C++ 規模 | 通信 |
|---|---|---|---|---|---|---|
| **mirno-ehf/ue5-mcp** (BlueprintMCP) | 記載なし → **5.5 で実証** | MIT | 2026-05 | **9箇所** | 23,897行 | `FHttpServerModule` :9847 |
| GenOrca/unreal-mcp | 5.6 | Apache-2.0 | 2026-07 | 9箇所 | 4,696行 | Python 経由 |
| ZiggyMar/unreal-mcp | 5.6 / 5.8 | MIT | 2026-09 | 2箇所 | 19,209行 | 独自 TCP :8765 |
| chongdashu/unreal-mcp | 5.5 明記 | MIT | 2025-04（停止） | 2箇所 | 5,053行 | 独自 TCP :55557 |

4件とも `TryCreateConnection` / `MakeLinkTo` を実際に呼んでおり、**ピン配線は実装済み**。
自作の必要はない。

## 第一候補: mirno-ehf/ue5-mcp

### 選定理由

**ピン配線が本物で広い。** `TryCreateConnection` が Blueprint グラフだけでなく
マテリアルグラフ・アニムグラフにも実装されている。Phase 2 で必要な範囲を満たす。

**独自 TCP リスナーを持たない。** UE の `FHttpServerModule` を使う。

```cpp
FHttpServerModule& HttpModule = FModuleManager::LoadModuleChecked<FHttpServerModule>("HTTPServer");
TSharedPtr<IHttpRouter> Router = HttpModule.GetHttpRouter(Port);
```

Remote Control と同じ基盤なので、**設定済みの `[HTTPServer.Listeners] DefaultBindAddress`
をそのまま継承し、NetBird IP にしか bind しない**。当初計画していた
「リスナーを剥がして 1 ポートに寄せる」改造が不要になる。
ポートは 30010 と 9847 の2つになるが、どちらも NetBird 越しにしか到達できない。

`.uplugin` に `EngineVersion` の指定が無いため、UE がバージョンで弾くこともない。

### 実測: UE 5.5.4 でのコンパイル結果

大学PC で `RunUAT BuildPlugin` を実行した。中間生成物を数えた結果:

```
ソース .cpp : 41 個
コンパイル済 : 38 個
.lib / .dll  : 生成なし（リンクまで到達していない）
```

**通らなかったファイルには明確な偏りがある。**

| 通らなかったファイル | 領域 | 我々に必要か |
|---|---|---|
| `BlueprintMCPHandlers_Groom.cpp` | Groom / HairStrands | 不要 |
| `BlueprintMCPHandlers_MaterialMutation.cpp` | マテリアルグラフ | 不要 |
| `BlueprintMCPHandlers_MaterialRead.cpp` | マテリアルグラフ | 不要 |
| `BlueprintMCPEditorSubsystem.cpp` | サブシステム | 必要 |

**必要な部分は通っている。**

- `BlueprintMCPHandlers_Mutation.cpp` — Blueprint グラフのノード追加とピン配線の本体
  （`TryCreateConnection` の呼び出し箇所）。**コンパイル成功**
- `BlueprintMCPHandlers_Graphs.cpp` / `_Variables.cpp` / `_AnimMutation.cpp` なども成功

5.5 と 5.6 以降の API 差分は、**マテリアルと Groom に集中している**とみられる。
`BlueprintMCPEditorSubsystem.cpp` はそれらのヘッダを取り込んでいる可能性が高い。

> **未確定**: 具体的なコンパイルエラーの内容は未取得。BuildPlugin のログが、
> その後のエディタ起動時に走った Turnkey に上書きされて失われたため。
> ログを保存した状態での再実行が必要。

## ビルドが完了しない原因（要再確認）

エディタ起動時のビルドは、以下で停止した。

```
CompilationResultException: FailedDueToEngineChange
UnrealEditor-CaptureDataUtils.dll: Produced item ... was produced by outdated attributes.
Building would modify the following engine files: （CaptureDataUtils の成果物のみ）
```

エンジン同梱プラグインの Intermediate を比較すると、`CaptureDataUtils` だけが
中間生成物 22 ファイルを抱えている（ControlRig / Paper2D は 2 ファイル）。
Epic の既知不具合 [UE-230848](https://issues.unrealengine.com/issue/UE-230848) と一致する。

> **注意**: これは**エディタ起動時のビルド**の失敗理由であり、
> `RunUAT BuildPlugin` の失敗理由とは限らない。両者を混同しないこと。
> BuildPlugin は 38 ファイルまでコンパイルを進めており、
> 別の原因（個別のコンパイルエラー）で止まった可能性が高い。

なお、エンジン同梱の 1,888 個の `.Build.cs` を走査したが、
`CaptureData` 配下以外に `CaptureDataUtils` を参照するモジュールは存在しない。
どの経路でビルドグラフに入るかは未解明。

## 次にやること

1. **ログを保存した状態で BuildPlugin を再実行し、4ファイルの実際のエラーを得る**
2. エラーが 5.5 の API 差分であれば、**その3領域だけを 5.5 向けに移植する**
   （マテリアルと Groom は我々の用途に不要なので、移植が困難なら
   ハンドラごと無効化して依存 `MaterialEditor` / `HairStrandsCore` を外す選択もある）
3. ビルドが通ったら成果物を配布する（下記）

## 長期方針: ビルド済みバイナリの配布

UE のプラグインは一度ビルドすれば `Binaries/Win64/*.dll` を置くだけでロードできる。
**日常的にはコンパイラが不要。** 再ビルドが要るのは、プラグインのソースを変えたときと
エンジンを更新したときだけ。

- 大学PC の日常運用: DLL を配置済み → ビルドなしで動く
- バイナリは Git に直接入れず **GitHub Releases に添付**する（無料・リポジトリが膨らまない）
- ビルドは**専用の最小 C++ プロジェクト**で行う。`.uproject` で不要なプラグインを
  無効化できるため、`RunUAT BuildPlugin` の合成ホストプロジェクトより制御しやすい

共用機にコンパイラを常時依存させない構成になり、本プロジェクトの方針と整合する。

## Blueprint 専用プロジェクトの問題（別件・確認済み）

Blueprint 専用プロジェクトに C++ プラグインを置いて UE を起動すると、
プラグインのビルド以前に次で止まる。

```
Engine modules are out of date, and cannot be compiled while the engine is running.
Please build through your IDE.
```

これも UE-230848。**今年の新規プロジェクトは最初から C++ プロジェクトとして作れば
この経路自体を回避できる。**
