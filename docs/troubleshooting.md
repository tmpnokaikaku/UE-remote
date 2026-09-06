# トラブルシューティングと知見

本プロジェクトで実際に踏んだ問題と、その原因・対処。**すべて実機で確認したもの**。
推測を含む項目には明記した。

## 症状から引く

| 症状 | 原因の候補 | 節 |
|---|---|---|
| Remote Control に繋がらない | NetBird 未接続 / IP 変更 / 起動順 / プラグインの巻き添え | [1](#1-remote-control-に繋がらない) |
| ping は通るが TCP だけ timeout | 待ち受けが無い / 許可リスト / Firewall | [1-5](#1-5-ping-は通るが-tcp-だけ-timeout) |
| 設定が `DefaultEngine.ini` に現れない | 書き込み先が別ファイル | [2](#2-設定がどのiniにも見つからない) |
| リクエストが 401 / 403 になる | パスフレーズ強制 / 許可リスト / AllowedOrigin 誤用 | [3](#3-リクエストが拒否される) |
| レイテンシが 300ms を超える | エディタの CPU スロットリング | [4](#4-レイテンシが異常に大きい) |
| エディタがクラッシュする | `/remote/batch` / アセット削除 | [5](#5-エディタがクラッシュする) |
| C++ プラグインのビルドが通らない | BP 専用プロジェクト / `-Rocket` / 5.5 の API 差分 | [6](#6-c-プラグインのビルドが通らない) |
| MCP ツールが AI から見えない | 登録スコープ / セッション再起動 | [7](#7-mcp-ツールが-ai-から見えない) |
| ソースを直したのに反映されない | 編集可能インストールでない | [8](#8-ソースを直しても反映されない) |

---

## 1. Remote Control に繋がらない

### 1-1. 手元PC の NetBird のセッションが切れている

手元PC を SSO ログインで登録していると **8〜24 時間で切れる**。切れると
`Daemon status: NeedsLogin` になる。

```bash
netbird status          # 確認
netbird up              # 対話的な SSO。端末で自分で実行する必要がある
```

**恒久対策**: NetBird ダッシュボードで該当ピアの **Login expiration を無効化**する。
SSO の身元は保ったまま期限だけ外せる。または setup key で機械登録に切り替える。

> 大学PC は setup key で登録済みのため、この問題は起きない。

### 1-2. NetBird IP が変わった

**setup key で再登録するとピアが作り直され、IP が変わる。** 公開鍵が同じでも別 IP になる。

実際に2回踏んだ。大学PC は `100.71.168.109` → `100.71.174.134`、
手元PC は `100.71.232.171` → `100.71.29.94`。

`netbird status --detail` で現在の IP を確認し、`DefaultBindAddress` を更新して
エディタを再起動する。**Step 1（再登録）と Step 4（bind 設定）は必ずこの順で行う。**

### 1-3. 起動順が逆

**NetBird 接続 → UE 起動**の順を守る。逆だと `DefaultBindAddress` への bind に失敗し、
HTTP サーバが待ち受けを開始しない。

### 1-4. 相手ピアが `Status: Idle`

NetBird の lazy connection。トラフィックが流れるまでトンネルを張らない仕様なので
**異常ではない**。`ping <相手IP>` を一度打てば起きる。

### 1-5. ping は通るが TCP だけ timeout

L3 は生きているので NetBird は正常。以下を順に確認する。

1. **UE が起動して待ち受けているか** — 大学PC で
   `Get-NetTCPConnection -LocalPort 30010,9847 -State Listen`。
   **空なら待ち受けが無い**
2. `AllowlistedClients` に手元の NetBird IP が入っているか（[3-2](#3-2-allowlistedclients-の既定値は極端に広い)）
3. Windows Firewall が `UnrealEditor.exe` の受信を落としていないか

> `curl 127.0.0.1:30010` が失敗するのは**正常**。`DefaultBindAddress` を
> NetBird IP にしているので localhost では応答しない。判断材料にならない。

### 1-6. プラグインが Remote Control を巻き添えで止めた

**BlueprintMCP を入れた直後に両ポートが沈黙する場合。** 実際に踏んだ。

```
Created new HttpListener on 100.71.174.134:30010   ← RC は正常に起動
Created new HttpListener on 100.71.174.134:9847    ← MCP も正常に起動
BlueprintMCP: Bind check attempt 1/5 failed ...    ← 誤検知
Error: Failed to bind HTTP listener on port 9847
HttListener stopping listening on Port 30010       ← RC が巻き添え
```

upstream の起動確認が **`127.0.0.1` 決め打ち**で listener に接続するため、
`DefaultBindAddress` を設定していると必ず失敗する。さらに失敗時に
`StopAllListeners()` を呼び、**共有している `FHttpServerModule` の全 listener**
（Remote Control を含む）を停止する。

**対処**: [`plugins/BlueprintMCP-ue5.5.patch`](../plugins/README.md) を適用する。

### 診断の手順

UE の出力ログが最も確実。RC が落ちていても大学PC で読める。

```powershell
$PRJ = "$env:USERPROFILE\Documents\Unreal Projects\<プロジェクト>"
Select-String -Path "$PRJ\Saved\Logs\*.log" -Pattern "HTTPServer|BlueprintMCP|Bind|30010|9847" |
  Select-Object -Last 40 | Format-List Line
```

---

## 2. 設定がどのiniにも見つからない

### 2-1. Remote Control の設定は `RemoteControl.ini` に書かれる

`URemoteControlSettings` は `UCLASS(Config=RemoteControl)` なので、
**`DefaultEngine.ini` には書かれない**。

| ファイル | 役割 |
|---|---|
| `Saved/Config/WindowsEditor/RemoteControl.ini` | 変更が既定で書かれる先（**そのPCのユーザ専用**） |
| `Config/DefaultRemoteControl.ini` | プロジェクトの既定値（共有される） |

セクションは `[/Script/RemoteControlCommon.RemoteControlSettings]`。
共用機では**設定画面右上の「デフォルトとして設定」を押す**こと。押さないと
Windows ユーザが変われば消える。

### 2-2. CPU スロットリングは `DefaultEditorSettings.ini`

```ini
; <Project>/Config/DefaultEditorSettings.ini
[/Script/UnrealEd.EditorPerformanceSettings]
bThrottleCPUWhenNotForeground=False
```

> Web 上には `EditorPerProjectUserSettings.ini` / `[/Script/UnrealEd.EditorPerProjectUserSettings]`
> という情報があるが、**UE 5.5 では誤り**。実測で上記を確認した。

### 2-3. 既定値と同じ値は ini に書かれない

**UE は既定値と異なる値だけを書き出す。** したがって
「キーが1行も無い」＝「未設定」ではなく「**既定値のまま**」を意味する。

`bThrottleCPUWhenNotForeground` の既定は `True`（スロットリング有効）。
キーが無い状態はスロットリングが効いている状態。

### 2-4. 設定オブジェクトは Python からも Remote Control からも読めない

- `unreal.EditorPerformanceSettings` は Python 未公開
- `unreal.EditorPerProjectUserSettings` は存在するが throttle 系プロパティが無い
- `Default__RemoteControlSettings` は Remote Control 経由でアクセス拒否される
  （`bRestrictServerAccess` による保護）

**ini を読む以外に確認手段が無い。**

---

## 3. リクエストが拒否される

### 3-1. パスフレーズ強制がオンでパスフレーズが空

`bEnforcePassphraseForRemoteClients=True` かつ `Passphrases` が 0 件だと、
**localhost 以外からの全リクエストが拒否される**。初期状態でこうなっていた。

本構成ではパスフレーズを使わない。**クライアントがどの HTTP ヘッダにどう符号化して
送るのかが Epic の公式ドキュメントに存在しない**ため（`WebRemoteControl.cpp` の
実装にのみ存在）。仕様が不明な認証を、自由に実験できない共用機に入れると
失敗時の切り分けができなくなる。

代わりに三層で守る: NetBird の WireGuard ACL / `DefaultBindAddress` による bind 限定 /
`AllowlistedClients` による送信元 IP 制限。

### 3-2. `AllowlistedClients` の既定値は極端に広い

実機の初期値は `192.168.1.1` 〜 `255.255.255.255`。IPv4 空間のおよそ 1/3 で、
大学 LAN が `192.168.x.x` ならその全ホストが該当する。
**しかも NetBird の `100.71.x.x` は下限より小さいので範囲外**。
広すぎるのに目的のクライアントだけ入っていない状態だった。

本構成では `100.71.0.0` 〜 `100.71.255.255`（NetBird オーバーレイ）と
`127.0.0.1`（ローカル確認用）の2要素にする。

### 3-3. 「許可されたオリジン」に IP を書かない

`AllowedOrigin` は **HTTP の `Origin` ヘッダ（CORS）の照合先**であり、IP の許可リストではない。

- CORS はブラウザが自主的に守る仕組みで、**ブラウザ以外には何の制約にもならない**
- 本構成のクライアントは Python スクリプトで、`Origin` ヘッダを送らない

IP を書いてもセキュリティ上の効果はゼロで、リクエストを弾く副作用だけが残る。
**`*` のままにする。**

---

## 4. レイテンシが異常に大きい

TCP 接続は速いのに HTTP だけ 300ms 前後かかる場合、**エディタの CPU スロットリング**。

Remote Control の HTTP 処理は**ゲームスレッド上**で行われるため、
エディタのフレームレートがそのまま応答遅延になる。大学PC は無人＝常に非フォーカスなので、
既定のままだと常時スロットリングされる。

| 状態 | median | 換算 |
|---|---|---|
| スロットリング有効（既定）・非フォーカス | **約 320 ms** | 約 3 FPS |
| スロットリング無効・非フォーカス | **約 28 ms** | 約 35 FPS |

対処は [2-2](#2-2-cpu-スロットリングは-defaulteditorsettingsini)。**11 倍違う。**

---

## 5. エディタがクラッシュする

### 5-1. `PUT /remote/batch` は使用禁止

呼んだ瞬間にエディタが落ちる。

```
Assertion failed: Pair != nullptr
[File:...\Runtime\Core\Public\Containers\Map.h] [Line: 690]
```

`TMap` の要素引きが `nullptr` を返した箇所での assert であり、**エンジン側の不具合**。
リクエストの内容とは無関係。`GET /remote/info` のルート一覧には載っているが呼んではいけない。

**往復削減は「ループを Python スクリプト側に寄せる」方法だけで行う。**
実測でアクタ63件の位置取得が UE 内 1.2ms（1件1往復なら約1.4秒）なので、こちらの方が効く。

### 5-2. アセットの削除・保存は危険

`EditorAssetLibrary.delete_asset` / `save_asset` でクラッシュした。

```
Cast of UI_MovieRenderPipelineInfoTableRow_C ... to UserWidget failed
PythonScriptPlugin → EditorScriptingUtilities → UnrealEd
  → Kismet → KismetCompiler → UMGEditor → 失敗
```

削除しようとしたのは直前に作った参照ゼロの空 Blueprint。しかし**削除処理が依存関係の
走査のために無関係な Blueprint を広範にロード・コンパイルし**、その過程で
MovieRenderPipeline のウィジェット Blueprint の CDO キャストに失敗して落ちている。
対象アセットのレジストリ上のメタデータは正常だった。

**指針**: Remote Control 経由で `delete_asset` / `save_asset` を安易に呼ばない。
一時アセットの後始末は **UE を閉じた状態でファイルを削除**する。

---

## 6. C++ プラグインのビルドが通らない

### 6-1. Blueprint 専用プロジェクトに C++ プラグインを置くと詰む

```
Engine modules are out of date, and cannot be compiled while the engine is running.
Please build through your IDE.
```

Epic の既知不具合 [UE-230848](https://issues.unrealengine.com/issue/UE-230848)。
プラグインのコンパイル以前の問題で、**どのプラグインでも起きる**。

**今年の新規プロジェクトは最初から C++ プロジェクトとして作れば、この経路自体を回避できる。**

回避策は `RunUAT BuildPlugin` でプラグイン単体をビルドすること。

### 6-2. `-Rocket` を付けない

`-Rocket` を付けると、エンジン同梱の `CaptureDataUtils` を再ビルドしようとして
インストール版エンジンでは書き込めず停止する。

```
CompilationResultException: FailedDueToEngineChange
Building would modify the following engine files:
  ...\VirtualProduction\CaptureData\...
```

`CaptureDataUtils` だけが Intermediate に中間生成物 22 ファイルを抱えて出荷されている
（正常なプラグインは 2 ファイル）。**`-Rocket` を外した実行ではこの停止は起きない。**

### 6-3. ビルドコマンド

```powershell
$UE = "C:\Program Files\Epic Games\UE_5.5"
$PRJ = "$env:USERPROFILE\Documents\Unreal Projects\<プロジェクト>"

& "$UE\Engine\Build\BatchFiles\RunUAT.bat" BuildPlugin `
    -Plugin="$PRJ\Plugins\BlueprintMCP\BlueprintMCP.uplugin" `
    -Package="$env:USERPROFILE\Desktop\BlueprintMCP_Built" `
    -TargetPlatforms=Win64 2>&1 | Tee-Object -FilePath "$env:USERPROFILE\Desktop\buildplugin.log"
```

### 6-4. ログの扱い

- **`Tee-Object` の出力は UTF-16**。UTF-8 として読むとエラー行が拾えない
- **`%APPDATA%\Unreal Engine\AutomationTool\Logs\...\Log.txt` は後続の実行で上書きされる。**
  エディタを起動すると Turnkey が走って消える。**必ず別ファイルに保存すること**
- エディタ起動時のビルドと `RunUAT BuildPlugin` は**別のログに出る**。混同しない

### 6-5. どこまでコンパイルできたかを知る

ログを失っても、中間生成物の数で進捗が分かる。

```
Source の .cpp 数 と Intermediate の *.cpp.dep.json 数 を比較する
```

差分を取れば、**どのファイルが通らなかったかまで特定できる**。実際にこれで
「マテリアルと Groom に失敗が集中している」ことを掴んだ。

### 6-6. UE 5.5 と 5.6 の API 差分（実測）

| 5.6 以降 | 5.5 での正解 | 確認場所 |
|---|---|---|
| `IAssetRegistry::IsGathering()` | `IsLoadingAssets()` | `IAssetRegistry.h:861` |
| `MD_Surface` が暗黙に入る | `#include "MaterialDomain.h"` が必要 | `MaterialDomain.h:15` |
| `GetMaterialResource(ShaderPlatform)` | 引数は `ERHIFeatureLevel::Type` | `Material.h:1182` |
| `Build(FOnGroomBindingAssetBuildCompleteNative)` | `Build()`（引数なし） | `GroomBindingAsset.h:444` |

**エンジンのヘッダは大学PC 上に実物がある。** Remote Control 経由で読めるので、
API の差分は推測せず実物で確認できる。

---

## 7. MCP ツールが AI から見えない

### 7-1. 登録スコープ

`claude mcp add` を `-s user` 無しで実行すると、**起動したディレクトリの
プロジェクトスコープ**に登録される。別ディレクトリから Claude Code を起動すると
ツールが現れない。

厄介なのは、**そのディレクトリで `claude mcp list` を実行すると `✔ Connected` と出る**こと。
「登録できている」ように見えるのにツールが見えない、という分かりにくい失敗をする。

```bash
claude mcp add -s user --transport stdio ue-remote -- /path/to/.venv/bin/ue-remote-mcp
```

### 7-2. 登録後は再起動が必要

MCP サーバはセッション開始時に読み込まれる。登録・変更しても、
**起動中のセッションには反映されない。**

### 7-3. MCP SDK のバージョン

SDK 2.x で `FastMCP` は `MCPServer` に改名された。

```
ModuleNotFoundError: No module named 'mcp.server.fastmcp'.
This is mcp 2.x, where FastMCP was renamed to MCPServer
```

`mcp>=1.0` と書くと 2.x が入るため、v1 のコードは動かない。

---

## 8. ソースを直しても反映されない

`pip install ./mcp-server` は `site-packages` へ**ファイルをコピーする**ため、
ソースを直しても `ue-remote-mcp` の挙動は変わらない。`git pull` で更新する運用でも同じ。

```bash
python3 -m pip install -e ./mcp-server     # -e が必須
```

読み込み元の確認:

```bash
.venv/bin/python -c "import ue_remote, os; print(os.path.dirname(ue_remote.__file__))"
```

---

## 設計上の教訓

### 失敗を状態として持たない

**同じ根本原因で2回踏んだ。**

1. ガードの確認結果をキャッシュしていたが、**失敗もキャッシュしていた**。
   起動時に到達できないとガードが失敗で固定され、復旧しても再確認されず、
   全ツールが永久に拒否された
2. ハートビート失敗時に `_write_healthy = False` を立ててスレッドごと終了していた。
   True に戻す経路が無く、同じく復旧不能だった

「ハートビートで再確認する」という逃げ道は**機能しなかった**。ハートビートは
ロック取得後にしか動かず、ロック取得はガードを通らないと行われないため、
失敗状態から抜ける経路が存在しなかった。

**原則**: 失敗はキャッシュしない。成功だけを TTL 付きでキャッシュする。
ネットワーク断・エディタ再起動・スリープはいずれも日常的に起きる。

### 共有リソースを止めない

BlueprintMCP は自分の起動確認に失敗したとき `StopAllListeners()` を呼び、
**同じモジュールを共有する Remote Control まで止めていた**。

**原則**: 自分の失敗の後始末で、他が使っている共有リソースを止めない。

### 名前で識別しない

大学PC には紛らわしい名前の UE プロジェクトが複数ある。プロジェクトブラウザ上は
2つが同じ `MyProject6` に見え、`hitotsubashi_2025_3` の `DefaultEngine.ini` には
`GameName=MyProject6` が残っている（フォルダごと複製された名残）。

**表示名も ini の記述も識別子にならない。信用できるのは `.uproject` の絶対パスだけ。**
MCP サーバのプロジェクトガードはこれを照合する。

### 往復を減らす

1往復あたり median 約 23ms。63 アクタの位置取得は UE 内で 1.2ms なので、
**1件1往復にすると 1,000 倍以上遅くなる**。

ループは Python スクリプト側に寄せて 1 往復で完結させる。
`/remote/batch` は使えない（[5-1](#5-1-put-remotebatch-は使用禁止)）。

### 検証の層と、それぞれが捕まえられないもの

| 層 | 捕まえられないもの | 実例 |
|---|---|---|
| ユニットテスト（偽サーバ） | リクエストの形が本物に通るか | 32件全通過の状態で MCP レイヤが壊れていた |
| 実機スモーク（直接クライアント） | MCP レイヤの問題 | SDK v1/v2 の API 変更 |
| 実機 E2E（stdio 経由） | 起動時の状態遷移 | ガードの失敗キャッシュ |
| 実運用 | — | 上記すべてを通過した状態で残っていた |

**すべての層を通過しても実運用で欠陥が出る。** Phase 1 完了時点で
ユニット32件・スモーク16件・E2E 8件が全通過していたが、実際に使い始めた初手で
設計上の欠陥1つと運用上の落とし穴2つが出た。

### 他人の「直した」を検証する

Codex に委譲した修正は、**必ず修正前に戻してテストが落ちることを確認する**。
実際に、テストは通るが指摘したバグを捕まえていない実装や、
存在しない API を推測で使った実装があった（後者はヘッダの実物で確認して救済した）。
