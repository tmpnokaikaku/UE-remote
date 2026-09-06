# UE プラグイン

## BlueprintMCP（UE 5.5 移植パッチ）

Blueprint のノードグラフ操作は Python から不可能なため、C++ プラグインが要る
（根拠: [blueprint-python-limits-2026-09-06.md](../docs/blueprint-python-limits-2026-09-06.md)）。
自作はせず、既存の [mirno-ehf/ue5-mcp](https://github.com/mirno-ehf/ue5-mcp)（MIT）を使う。
選定の経緯は [phase2-plugin-evaluation.md](../docs/phase2-plugin-evaluation.md)。

upstream は UE 5.6 以降向けで、5.5.4 では 4 ファイルがコンパイルに失敗する。
`BlueprintMCP-ue5.5.patch` がその差分を埋める。**機能は1つも削っていない。**

### 大学PC での手順

```powershell
$PRJ = "$env:USERPROFILE\Documents\Unreal Projects\<プロジェクト名>"
$UE  = "C:\Program Files\Epic Games\UE_5.5"

# 1. upstream を取得
cd "$PRJ\Plugins"
git clone https://github.com/mirno-ehf/ue5-mcp.git BlueprintMCP
cd BlueprintMCP

# 2. 5.5 向けパッチを当てる
git apply <UE-remote をクローンした場所>\plugins\BlueprintMCP-ue5.5.patch

# 3. プラグイン単体をビルド（ログを残す）
& "$UE\Engine\Build\BatchFiles\RunUAT.bat" BuildPlugin `
    -Plugin="$PRJ\Plugins\BlueprintMCP\BlueprintMCP.uplugin" `
    -Package="$env:USERPROFILE\Desktop\BlueprintMCP_Built" `
    -TargetPlatforms=Win64 2>&1 | Tee-Object -FilePath "$env:USERPROFILE\Desktop\buildplugin.log"
```

> **`-Rocket` を付けないこと。** 付けると `CaptureDataUtils` の再ビルドを試みて
> `FailedDueToEngineChange` で停止する。
>
> ログは `Tee-Object` の既定で **UTF-16** になる。読むときは注意。

ビルドが通ったら `BlueprintMCP_Built` の内容を `Plugins\BlueprintMCP\` に配置する。
**以後はビルド済みバイナリがあるためコンパイラ不要。**

### パッチの内容（すべて UE 5.5 のヘッダで存在を確認済み）

| ファイル | 修正 | 5.5 での裏付け |
|---|---|---|
| `BlueprintMCPEditorSubsystem.cpp` | `IsGathering()` → `IsLoadingAssets()` | `IAssetRegistry.h:861` |
| `BlueprintMCPHandlers_MaterialMutation.cpp` | `#include "MaterialDomain.h"` 追加 | `MaterialDomain.h:15` に `MD_Surface` |
| `BlueprintMCPHandlers_MaterialRead.cpp` | 同上 + `GMaxRHIShaderPlatform` → `GMaxRHIFeatureLevel` | `Material.h:1182` は `ERHIFeatureLevel::Type` を取る |
| `BlueprintMCPHandlers_Groom.cpp` | 完了デリゲートを廃し `Build()`（引数なし）+ `FinishCompilation()` 後に `IsValid()` で成否判定 | `GroomBindingAsset.h:444` / `:362`、`GroomBindingCompiler.h`(Public) |
| `BlueprintMCPServer.cpp` | 起動確認の接続先を `DefaultBindAddress` に従わせる。失敗時に `StopAllListeners()` を呼ばない | 下記 |

### `BlueprintMCPServer.cpp` の修正が要る理由（実機で踏んだ）

upstream の起動確認は **`127.0.0.1` 決め打ち**で listener に接続する。

```cpp
Addr->SetIp(TEXT("127.0.0.1"), bIsValid);
bool bConnected = TestSocket->Connect(*Addr);
```

しかし本構成では `[HTTPServer.Listeners] DefaultBindAddress` により
listener は **NetBird IP にしか bind していない**。localhost は応答しないので
**この確認は必ず失敗する**。

さらに失敗時の処理が破壊的だった。

```cpp
HttpModule.StopAllListeners();   // 共有モジュールの全 listener を停止
```

`FHttpServerModule` は **Remote Control と共有**されているため、
これを呼ぶと **Remote Control(:30010) まで巻き添えで停止する**。
実際に両ポートが沈黙し、原因の特定に時間を要した。実機のログ:

```
13:25:04  Created new HttpListener on 100.71.174.134:30010   ← RC は正常
13:25:05  Created new HttpListener on 100.71.174.134:9847    ← MCP も正常
13:25:07  BlueprintMCP: Bind check attempt 1/5 failed ...    ← 誤検知
13:25:20  Error: Failed to bind HTTP listener on port 9847
13:25:20  HttListener stopping listening on Port 30010       ← 巻き添え
```

修正内容:

1. 確認先を `GConfig` から読んだ `DefaultBindAddress` にする
   （未設定または `0.0.0.0` なら従来どおり `127.0.0.1`）
2. 失敗時に `StopAllListeners()` を呼ばない。他機能を巻き込まない

**この2点は upstream にとっても不具合**であり、還元する価値が高い。

`FOnGroomBindingAssetBuildCompleteNative` と `EGroomBindingAssetBuildResult` は
5.6 以降の追加で 5.5 には存在しない。5.5 の `Build()` は引数を取らず、
完了待ちは元コードにもある `FGroomBindingCompilingManager::FinishCompilation()` で行える。

### 通信経路について

このプラグインは独自 TCP リスナーを持たず、UE の `FHttpServerModule` を使う。

```cpp
FHttpServerModule& HttpModule = FModuleManager::LoadModuleChecked<FHttpServerModule>("HTTPServer");
TSharedPtr<IHttpRouter> Router = HttpModule.GetHttpRouter(Port);
```

Remote Control と同じ基盤なので、`[HTTPServer.Listeners] DefaultBindAddress`
（[setup-university-pc.md](../docs/setup-university-pc.md) Step 4）を**そのまま継承する**。
ポートは 30010 と 9847 の2つになるが、どちらも NetBird 仮想 IP にしか bind しない。

### upstream への還元

このパッチは 5.5 対応として本家に還元する価値がある。
バージョン分岐マクロを入れていないため、PR にする際は
`#if ENGINE_MINOR_VERSION` 等での分岐が別途必要になる。
