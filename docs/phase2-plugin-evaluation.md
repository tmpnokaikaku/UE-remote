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

### 実測: UE 5.5.4 でコンパイルは通る

大学PC で `RunUAT BuildPlugin` を実行した結果、**コンパイルエラーはゼロ**。
約50個のソースファイルがすべて処理された（Intermediate に `.dep.json` が生成済み）。

**バージョン適合性の問いには答えが出た。5.5 で使える。**

## ビルドを阻んでいるもの（エンジン側の不備）

```
CompilationResultException: FailedDueToEngineChange
UnrealEditor-CaptureDataUtils.dll: Produced item ... was produced by outdated attributes.
Building would modify the following engine files:
  ...\UE_5.5\Engine\Plugins\VirtualProduction\CaptureData\...  （CaptureDataUtils の成果物のみ）
Please rebuild from an IDE instead.
```

Epic の既知不具合 [UE-230848](https://issues.unrealengine.com/issue/UE-230848) と一致する
（報告にも「VirtualProduction プラグインを指すエラーが出る」とある）。

### 原因

エンジン同梱プラグインの Intermediate ディレクトリを比較した。

| モジュール | Intermediate 内のファイル数 |
|---|---|
| ControlRig | 2 |
| Paper2D | 2 |
| **CaptureDataUtils** | **22**（`.obj` / `.lib` / `.dep.json` / `.sarif`） |

通常は事前ビルド済みの印だけを持つところ、**`CaptureDataUtils` だけがビルド中間生成物
一式を抱えたまま出荷されている**。UBT がそれらのアクションを再評価し、
「属性が古い」と判断して再ビルドしようとするが、インストール版エンジンなので
Program Files に書き込めず停止する。

エラーが列挙したファイル群は、この 22 ファイルと一致する。

### 重要な含意

- **プラグイン側では回避できない。** どの候補を選んでも同じ場所で止まる
- エンジン同梱プラグインのどれも `CaptureData` を参照しておらず、
  `EnabledByDefault` でもない。それでもビルドグラフに入る
- 大学PC のエンジン全体は正常（502 プラグインすべて 2025-04-15 の同一日付）。
  異常なのは `CaptureDataUtils` の出荷状態だけ

## 未解決 — 次の選択肢

| 案 | 内容 | 影響 |
|---|---|---|
| A | エンジンの `CaptureDataUtils/Intermediate` をリネーム後、再ビルド | Program Files を変更。Launcher の Verify で復元可 |
| B | Epic Games Launcher でエンジンを検証・修復 | 非破壊だが再ダウンロードで時間がかかる |
| C | 手元PC に UE 5.5 を入れてビルドし、成果物だけ大学PC へ | **大学PC に一切触れない**。手元のディスクと時間を要する |

C は「大学PC にコンパイラを要求しない」構成になるため、長期的には最も筋がよい。
共用機にビルド環境を依存させないという点で、本プロジェクトの方針とも合う。

## Blueprint 専用プロジェクトの問題（別件・確認済み）

Blueprint 専用プロジェクトに C++ プラグインを置いて UE を起動すると、
プラグインのビルド以前に次で止まる。

```
Engine modules are out of date, and cannot be compiled while the engine is running.
Please build through your IDE.
```

これも UE-230848。**今年の新規プロジェクトは最初から C++ プロジェクトとして作れば
この経路自体を回避できる。**
