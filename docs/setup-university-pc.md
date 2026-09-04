# 大学PC セットアップ手順

共用 Windows PC（Unreal Engine 5.4.4）側で一度だけ行う作業。

## この手順で触るもの / 触らないもの

**触るもの**

- NetBird の登録方式（個人ログイン → setup key による機械登録）
- UE プロジェクトの `Config/DefaultEngine.ini`
- UE プロジェクトのプラグイン有効化
- UE プロジェクトの `Plugins/` に C++ プラグインを1つ追加

**触らないもの**

- Windows のサービス設定、レジストリ、Firewall ルール
- Windows のユーザーアカウント、SSH サーバ
- ルータ、ネットワーク機器

共用機を預かっている立場なので、Windows 本体の設定は変更しない方針。

---

## 前提

- NetBird が既にインストールされている（導入済み・現在は down 状態）
- Unreal Engine 5.4.4 と対象プロジェクトがある
- 管理者権限は使える（NetBird サービスの再登録に必要）

---

## Step 1. NetBird を setup key で登録し直す

現状は個人の SSO ログインで登録されているため、セッションが約24時間で切れる。
常設ピアとして、個人アカウントに依存しない形に切り替える。

### 1-1. NetBird ダッシュボードで setup key を発行

<https://app.netbird.io> → Setup Keys → Create Setup Key

- Type: **Reusable**（PC を再セットアップする可能性を考慮）
- Expiration: 長め（1年など）
- Auto-assigned groups: 大学PC 用のグループを作って割り当てる（例: `ue-host`）
- **Ephemeral peers は OFF**（常設ピアなので、オフライン時に自動削除されると困る）

発行されたキーは秘密情報。**このリポジトリにコミットしないこと。**

### 1-2. 既存の登録を解除して再登録

管理者権限の PowerShell で実行する。

```powershell
netbird down
netbird logout

netbird up --setup-key "<発行した setup key>" --hostname "univ-ue-pc"
```

### 1-3. 状態と IP を確認

```powershell
netbird status --detail
```

確認すること:

- `Management: Connected` / `Signal: Connected`
- `NetBird IP` の値（`100.71.168.109` を想定。**変わっていたら以降の手順で読み替える**）
- `Session expires` の表示が消えている（＝ SSO セッション依存でなくなった）

### 1-4. サービスが自動起動する状態か確認

```powershell
Get-Service netbird | Select-Object Name, Status, StartType
```

`Status: Running` / `StartType: Automatic` であること。PC 再起動後も自動で繋がる状態にしておく。

---

## Step 2. UE のプラグインを有効化

Unreal Editor で対象プロジェクトを開き、`Edit > Plugins` から以下を有効化して**エディタを再起動**する。

| プラグイン | 用途 |
|---|---|
| **Remote Control API** | HTTP 経由で UE を操作する本体 |
| **Python Editor Script Plugin** | 任意 Python 実行（この仕組みの生命線） |

---

## Step 3. Remote Control の設定

`Edit > Project Settings` を開き、Plugins セクションの **Remote Control** を探して以下を設定する。

- **Remote Control HTTP Server Port**: `30010`（既定値のまま）
- **Auto Start Web Server**: ON（エディタ起動時に自動で待ち受け開始）
- **Python / コンソールコマンドのリモート実行を許可する項目**: ON

> 最後の項目は UE のバージョンによって表示名と場所が異なる。
> 「Remote Python Execution」「Allow Console Command Remote Execution」のような
> 名前の項目を探して有効にする。**見つけた実際の項目名を控えて共有すること**
> （手順書を確定させたい）。

設定後、`Config/DefaultEngine.ini` に何が書き込まれたかを確認し、その内容も共有する。
`[/Script/RemoteControl.RemoteControlSettings]` セクションあたりに追記されるはず。

---

## Step 4. bind アドレスを NetBird IP に変更

プロジェクトの `Config/DefaultEngine.ini` に以下を追記する。

```ini
[HTTPServer.Listeners]
DefaultBindAddress=100.71.168.109
```

`100.71.168.109` は Step 1-3 で確認した実際の NetBird IP に置き換える。

これにより Remote Control API は **NetBird の仮想インターフェースにしか bind しない**。
大学の LAN からも、インターネットからも到達できない。NetBird のピアからのみ届く。

> **重要な運用上の注意**
>
> UE を起動する時点で NetBird が繋がっていないと、この IP への bind に失敗し
> Remote Control が待ち受けを開始しない。
> **必ず「NetBird 接続 → UE 起動」の順にすること。**
> 接続できない場合は、まず `netbird status` を見て、UE を再起動する。

設定後、エディタを再起動する。

---

## Step 5. C++ プラグインの配置（Phase 2 以降）

Blueprint のノードグラフ編集用の C++ プラグイン `UEBlueprintBridge` を、
UE プロジェクトの `Plugins/` 配下に置いてビルドする。

> このプラグインは Phase 2 で実装する。Step 4 までで Python 経由の操作は動くので、
> ここは後回しでよい。

---

## Step 6. 疎通確認

### 大学PC 自身から

```powershell
curl.exe http://127.0.0.1:30010/remote/info
```

ルート一覧の JSON が返れば、Remote Control 自体は動いている。

```powershell
curl.exe http://100.71.168.109:30010/remote/info
```

こちらも返れば、NetBird IP への bind も成功している。

### 手元PC（WSL）から

本リポジトリの能力プローブを走らせる。何がどこまで通るかを機械的に測る。

```bash
python3 scripts/probe.py --host 100.71.168.109 --port 30010 --md report.md --json report.json
```

出力された `report.md` を共有すれば、Phase 1 以降の実装方針を実測に基づいて確定できる。

---

## トラブルシューティング

| 症状 | 確認すること |
|---|---|
| 手元から繋がらない | 両側で `netbird status` が `Connected` か。`Connection type` が `P2P` か `Relayed` か |
| `127.0.0.1:30010` も返らない | Remote Control API プラグインが有効か。Auto Start Web Server が ON か。エディタを再起動したか |
| `127.0.0.1` は返るが NetBird IP は返らない | `DefaultBindAddress` の IP が現在の NetBird IP と一致しているか。UE 起動時に NetBird が繋がっていたか |
| Python 実行だけ失敗する | Python Editor Script Plugin が有効か。Step 3 のリモート Python 実行許可が ON か |
| NetBird IP が変わった | `DefaultEngine.ini` の `DefaultBindAddress` を更新してエディタ再起動 |
