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

## Step 5. K2 ノード操作プラグインの配置（Phase 2 以降）

Blueprint のノードグラフ編集用の C++ プラグインを、UE プロジェクトの `Plugins/` 配下に置いてビルドする。

> **Phase 2 は既存プラグインの調査から始める。** 自作ありきにしない。
> K2 ノード操作を実装済みの UE 用 MCP プラグインが複数公開されているため、
> UE 5.4 で動きライセンスが適合するものがあれば、それを流用する方が速い。
> 判断基準は [architecture.md の 4-1](architecture.md) を参照。
>
> Step 4 までで Python 経由の操作は動くので、ここは後回しでよい。

---

## Step 6. 疎通確認とプローブ

Remote Control が「何をどこまで通すか」を機械的に測る。ここで得た実測が Phase 1 の設計根拠になる。

### 6-1. 大学PC 自身から（ローカル疎通）

```powershell
curl.exe http://127.0.0.1:30010/remote/info
```

ルート一覧の JSON が返れば Remote Control 自体は動いている。返らなければ Step 2/3 に戻る。

```powershell
curl.exe http://100.71.168.109:30010/remote/info
```

こちらも返れば NetBird IP への bind も成功している。**IP は Step 1-3 で確認した実際の値に置き換える。**

### 6-2. 手元PC（WSL）から

前提を順に満たす。**この順序が重要。**

1. 大学PC で NetBird 接続済み（`netbird status` が `Management: Connected`）
2. 大学PC で **その後に** Unreal Editor を起動し、プロジェクトを開いたまま放置
3. 手元PC で NetBird 接続済み（`netbird status` で相手ピアが `Connected` と出ること）

到達性だけ先に確認する。

```bash
netbird status --detail | grep -A3 univ-ue-pc
curl -m 5 http://100.71.168.109:30010/remote/info
```

プローブを実行する。Python 3.10 以降、外部パッケージ不要。

```bash
cd UE-remote
python3 scripts/probe.py \
  --host 100.71.168.109 \
  --port 30010 \
  --timeout 5 \
  --md probe-result.md \
  --json probe-result.json
```

| オプション | 既定値 | 備考 |
|---|---|---|
| `--host` | `127.0.0.1` | 環境変数 `UE_REMOTE_HOST` でも指定可 |
| `--port` | `30010` | 環境変数 `UE_REMOTE_PORT` でも指定可 |
| `--timeout` | `5`（秒） | 回線が不安定なら 10 程度に |
| `--md` / `--json` | 省略時は標準出力のみ | `--json` には各 HTTP 応答の生 body も入る |

毎回同じ相手を叩くなら環境変数にしておくと楽。

```bash
export UE_REMOTE_HOST=100.71.168.109
export UE_REMOTE_PORT=30010
python3 scripts/probe.py --md probe-result.md --json probe-result.json
```

### 6-3. 結果の読み方

終了コードは **TCP 到達性か `/remote/info` が落ちたときだけ `1`**。個別機能の `FAIL` は
「その機能が使えない」という測定結果なので `0` のまま。つまり `exit 0` でも中身は必ず見る。

| 検査 | FAIL のとき疑うもの |
|---|---|
| TCP 到達性 | NetBird の接続状態、bind アドレス、UE 起動順 |
| `GET /remote/info` | Remote Control API プラグイン、Auto Start Web Server |
| Python 実行 | Python Editor Script Plugin、Step 3 のリモート Python 実行許可 |
| 環境情報 | Python 実行が FAIL なら自動的に `SKIP` |
| `search/assets` / `describe` / `batch` | ルート一覧に該当エンドポイントがあるか |
| レイテンシ | P2P か Relayed か（`netbird status --detail` の `Connection type`） |

環境情報の検査は、UE バージョン・プロジェクトパス・有効プラグイン一覧に加えて
`unreal.K2Node` などの**シンボル有無**を返す。**Phase 2 で既存プラグインを評価する際の
前提条件がここで確定する**ため、この項目の出力は特に重要。

`probe-result.md` を共有すれば、Phase 1 以降の実装方針を実測に基づいて確定できる。
`probe-result.*` は生成物なのでコミットしない。

---

## トラブルシューティング

| 症状 | 確認すること |
|---|---|
| 手元から繋がらない | 両側で `netbird status` が `Connected` か。`Connection type` が `P2P` か `Relayed` か |
| `127.0.0.1:30010` も返らない | Remote Control API プラグインが有効か。Auto Start Web Server が ON か。エディタを再起動したか |
| `127.0.0.1` は返るが NetBird IP は返らない | `DefaultBindAddress` の IP が現在の NetBird IP と一致しているか。UE 起動時に NetBird が繋がっていたか |
| Python 実行だけ失敗する | Python Editor Script Plugin が有効か。Step 3 のリモート Python 実行許可が ON か |
| NetBird IP が変わった | `DefaultEngine.ini` の `DefaultBindAddress` を更新してエディタ再起動 |
