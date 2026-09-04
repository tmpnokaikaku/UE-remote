# UE-remote

手元PC の AI エージェント（Claude Code / Codex）から、大学の共用 Windows PC で動く
Unreal Engine 5.4.4 を操作するための仕組み。

AI の認証情報は手元PC にのみ置き、大学PC には一切置かない。大学PC 側は NetBird VPN と
Unreal Engine の Remote Control API だけで完結し、Windows 本体の設定は変更しない。

```text
手元PC (WSL)                                 大学PC (Windows, 共用)
Claude Code / Codex                          NetBird (機械登録)
  └ ue-remote-mcp ──── NetBird P2P ────────▶ Unreal Editor 5.4.4
      ロック / 監査ログ / RC クライアント        └ Remote Control API :30010
                                                  (NetBird IP にのみ bind)
```

詳細は [docs/architecture.md](docs/architecture.md) を参照。

## 構成

| ディレクトリ | 内容 | 動く場所 |
|---|---|---|
| `docs/` | アーキテクチャと手順書 | — |
| `scripts/` | 能力プローブ等の運用スクリプト | 手元PC |
| `mcp/` | MCP サーバ本体 | 手元PC |
| `plugins/` | UE C++ プラグイン `UEBlueprintBridge` | 大学PC |

## セットアップ

- 大学PC 側: [docs/setup-university-pc.md](docs/setup-university-pc.md)
- 手元PC 側: Phase 1 で追加予定

## 進捗

| Phase | 内容 | 状態 |
|---|---|---|
| 0 | リポジトリ骨格・文書・能力プローブ | 進行中 |
| 1 | MCP サーバ本体（RC クライアント / ロック / 監査ログ / ツール群） | 未着手 |
| 2 | C++ プラグイン `UEBlueprintBridge`（K2 ノード操作） | 未着手 |
| 3 | NetBird setup key 再登録 + 実機検証 | 未着手 |

## 注意

- NetBird の setup key、開発者 ID などの秘密情報は**コミットしない**
- 大学PC では **NetBird 接続 → UE 起動**の順を守ること（順序を誤ると Remote Control が
  NetBird IP に bind できず待ち受けを開始しない）
