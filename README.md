# UE-remote

手元PC の AI エージェント（Claude Code / Codex）から、大学の共用 Windows PC で動く
Unreal Engine 5.5.4 を操作するための仕組み。

AI の認証情報は手元PC にのみ置き、大学PC には一切置かない。大学PC 側は NetBird VPN と
Unreal Engine の Remote Control API だけで完結し、Windows 本体の設定は変更しない。

```text
手元PC (WSL)                                 大学PC (Windows, 共用)
Claude Code / Codex                          NetBird (機械登録)
  └ ue-remote-mcp ──── NetBird P2P ────────▶ Unreal Editor 5.5.4
      ロック / 監査ログ / RC クライアント        └ Remote Control API :30010
                                                  (NetBird IP にのみ bind)
```

詳細は [docs/architecture.md](docs/architecture.md) を参照。

## 構成

| ディレクトリ | 内容 | 動く場所 |
|---|---|---|
| `docs/` | アーキテクチャと手順書 | — |
| `scripts/` | 能力プローブ等の運用スクリプト | 手元PC |
| `mcp-server/` | MCP サーバ本体 | 手元PC |
| `plugins/` | UE C++ プラグイン（K2 ノード操作。既存の流用 or 自作） | 大学PC |

## セットアップ

- 大学PC 側: [docs/setup-university-pc.md](docs/setup-university-pc.md)
- 対象プロジェクトの特定: [docs/projects.md](docs/projects.md)
- 実測結果: [docs/probe-result-2026-09-05.md](docs/probe-result-2026-09-05.md) / [docs/phase2-verified-2026-09-06.md](docs/phase2-verified-2026-09-06.md) / [docs/phase3-blueprint-integration.md](docs/phase3-blueprint-integration.md)
- UE プラグイン: [plugins/README.md](plugins/README.md)
- **[トラブルシューティングと知見](docs/troubleshooting.md)** — 症状から引ける索引つき
- 手元PC 側: [mcp-server/README.md](mcp-server/README.md)

## 進捗

| Phase | 内容 | 状態 |
|---|---|---|
| 0 | リポジトリ骨格・文書・能力プローブ | **完了**（実機で測定済み） |
| 1 | MCP サーバ本体（RC クライアント / ロック / 監査ログ / プロジェクトガード / ツール群） | **完了**（実機 E2E・MCP 登録まで確認） |
| 2 | K2 ノード操作プラグイン（既存を選定・UE 5.5 へ移植） | **完了**（実機でピン配線を確認） |
| 3 | BlueprintMCP を MCP サーバに統合 | **完了**（実機でロック・監査経由の書き込みを確認） |

## 注意

- NetBird の setup key、開発者 ID などの秘密情報は**コミットしない**
- 大学PC では **NetBird 接続 → UE 起動**の順を守ること（順序を誤ると Remote Control が
  NetBird IP に bind できず待ち受けを開始しない）
