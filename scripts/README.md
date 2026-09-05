# Unreal Engine Remote Control API 能力プローブ

`probe.py` は、Unreal Engine 5.5.4 の Remote Control API で実際に利用できる機能を、1 回の実行で記録するための標準ライブラリのみのスクリプトです。接続先が停止中でも例外で中断せず、到達不能を結果として報告します。

## 実行方法

Python 3.10 以降で、リポジトリのルートから実行します。

```bash
python3 scripts/probe.py --host 100.71.174.134 --port 30010 --timeout 5 \
  --json probe-result.json --md probe-result.md
```

`--host` の既定値は `127.0.0.1`、`--port` は `30010`、`--timeout` は 5 秒です。環境変数 `UE_REMOTE_HOST` と `UE_REMOTE_PORT` も既定値として使え、CLI 引数が優先されます。`--json` には機械可読な全結果と各 HTTP 応答の生 body、`--md` には閲覧用レポートを保存します。body が 20,000 文字を超える場合だけ先頭部分を保存し、`response_body_truncated` を `true` にします。

終了コードは、TCP 到達性または `/remote/info` が失敗した場合だけ `1`、それ以外は `0` です。Python など個別機能の `FAIL` は、その機能が使えないという測定結果なので終了コードを変えません。

## 検査内容

1. TCP で接続できるか
2. `GET /remote/info` から Remote Control のルート一覧を取得できるか
3. `ExecutePythonCommandEx` が Python を実行し、確認用文字列を返すか
4. Python で UE・プロジェクト・プラグイン・公開シンボルの情報を取得できるか、および `Saved` 配下で排他的な一時ファイルの作成と削除ができるか
5. `/remote/search/assets` で Asset Registry を検索できるか
6. `/remote/object/describe` で UObject のメタデータを取得できるか
7. `/remote/batch` の 1 往復で 2 件の応答を取得できるか
8. `/remote/info` 5 回の min / median / max レイテンシ

Python が利用できない場合、Python に依存する環境情報の検査だけは `SKIP` になります。TCP 接続不能の場合は `/remote/info` まで実際に試し、それ以降は重複するタイムアウトを避けて `SKIP` にします。

## 失敗時に大学 PC 側で確認すること

- UE プロジェクトが起動中で、Remote Control API の HTTP サーバが port `30010` で開始しているか
- Remote Control の bind address が大学 PC の NetBird VPN IP になっているか（外部へ広く公開しないこと）
- 手元 WSL と大学 PC の両方で NetBird が接続済みか、対象 IP へ到達できるか
- Windows Defender Firewall などが NetBird 側からの TCP 接続を遮断していないか
- **Remote Control API** と **Python Editor Script Plugin** が有効か
- Remote Control の remote Python execution を許可する設定が有効か
- `/remote/info` に必要なルートが現れているか
- UE のログに Remote Control、Python、権限、ファイル書き込みに関するエラーがないか

Python 実行だけが失敗する場合は、Python Editor Script Plugin と remote Python execution 許可設定を最初に確認してください。`Saved` 書き込みだけが失敗する場合は、プロジェクトディレクトリの権限、セキュリティソフト、残留ファイルやロックを確認してください。
