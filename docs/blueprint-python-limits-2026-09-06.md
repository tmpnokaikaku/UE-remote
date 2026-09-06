# Blueprint 操作における Python の限界（実測 2026-09-06）

Phase 2 で C++ プラグインが本当に必要かを、文献ではなく実機で確かめた記録。
対象は大学PC の UE 5.5.4、サンドボックスプロジェクト `hitotsubashi_2025_3`。

## 結論

**C++ プラグインは回避不能。** Python では Blueprint のノードグラフに一切触れない。
ただし必要な範囲は当初想定より狭い。**グラフ以外は Python で足りている。**

## Python でできること（実機で成功を確認）

| 操作 | API |
|---|---|
| Blueprint アセットの作成 | `BlueprintEditorLibrary.create_blueprint_asset_with_parent` |
| メンバ変数の追加 | `add_member_variable` |
| 関数グラフの追加・削除・改名 | `add_function_graph` / `remove_function_graph` / `rename_graph` |
| イベントグラフ・任意グラフの取得 | `find_event_graph` / `find_graph` |
| コンパイル | `compile_blueprint` |
| 変数参照の一括置換 | `replace_variable_references` |
| 未使用ノード・変数の削除 | `remove_unused_nodes` / `remove_unused_variables` |

アクタ操作も問題ない。**63 アクタ全件の位置取得が UE 内で 1.2 ms**。
1アクタ1往復なら 63 × 23ms ≈ 1.4 秒かかるところなので、
「ループは Python 側に寄せる」方針の効果が実測で確認できた。

## できないこと

### ノードの列挙すらできない

```
Exception: EdGraph: Property 'Nodes' for attribute 'nodes' on 'EdGraph'
is protected and cannot be read
```

追加・配線以前に、グラフの中身を読むことができない。

### ピンは Python に存在しない

`unreal` モジュール内で `Pin` を含むシンボルを全列挙した結果、
Blueprint のピンに相当するものは無い。`EdGraphPinType`（型の記述子）だけが存在し、
**ピンの実体 `EdGraphPin` は無い**。

UE のピンは `FEdGraphPin` という **UObject ではないプレーンな C++ 構造体**であり、
Python の公開機構（UObject / UStruct のリフレクション）に乗らない。
「まだ公開されていない」ではなく「この仕組みでは公開されえない」性質のもの。

### K2Node 系はほぼ空

Python に公開されている K2Node 系クラスは **`K2Node` と `K2Node_CallFunction` の2つだけ**。
`K2Node_CallFunction` にも、対象関数を設定するメソッドもピンにアクセスするメソッドも無い
（`get_editor_property` 等の汎用 UObject メソッドのみ）。

`EdGraphNode` も同様に、ノード固有のメンバを一つも公開していない。

### ノード生成・接続の関数はどこにも無い

`unreal` の全 `*Library` / `*Utilities` / `*Subsystem` を横断し、
`add_node` / `create_node` / `spawn_node` / `connect_pin` / `link_pin` 等を含む
メソッドを検索した。**Blueprint K2 グラフ向けのものは1件も無い。**

## 決定的な対比

他のグラフ系統は Python に公開されている。

| グラフ系統 | ノード操作の公開 |
|---|---|
| **Blueprint (K2 / EdGraph)** | **無し** |
| Material | あり（生成・接続・位置） |
| MetaSound | あり（`MetaSoundEditorSubsystem.set_node_location` 等） |
| RigVM / Control Rig | あり（`RigVMPin` 含む完全な API） |
| Niagara / Optimus / MovieGraph / MVVM | あり（各々ピン型を公開） |

**他は全部公開されているのに Blueprint だけ無い。** 実装漏れではなく意図的な線引きと
見るのが自然であり、近い将来に埋まることを前提にした計画は立てられない。

## Phase 2 への含意

C++ プラグインが担うべき範囲が絞れた。**以下だけでよい。**

- グラフ内のノード列挙
- ノードの追加（関数呼び出し / 変数取得・設定 / 分岐 / イベント等）
- **ピンの配線**
- ノード位置の設定

Blueprint の作成・変数・関数グラフ・コンパイルは Python で足りているので、
プラグイン側で作り直す必要はない。

**既存プラグインの評価基準として最も重要なのは「ピンの配線まで実装されているか」。**
そこが無いものは、我々にとって価値がほとんど無い。

## 副産物: アセット削除は危険

`EditorAssetLibrary.delete_asset`（および直前の `save_asset`）を呼んだところ、
**エディタがクラッシュした**。

```
Fatal error: Casts.cpp Line 10
Cast of UI_MovieRenderPipelineInfoTableRow_C
  /MovieRenderPipeline/Blueprints/... .Default__..._C to UserWidget failed

PythonScriptPlugin → EditorScriptingUtilities → UnrealEd
  → Kismet → KismetCompiler → UMGEditor → 失敗
```

削除しようとしたのは、直前に作った空の Actor Blueprint で、参照は一切無い。
しかしスタックのとおり、**削除処理が依存関係の走査のために無関係な Blueprint を
広範にロード・コンパイルし**、その過程で MovieRenderPipeline プラグインの
ウィジェット Blueprint の CDO キャストに失敗して落ちている。

対象アセットのレジストリ上のメタデータは正常だった
（`ParentClass` / `NativeParentClass` ともに `/Script/UMG.UserWidget`）。
アセット自体が壊れているのではなく、**ロード途中の状態でキャストが走る**
エンジン側の脆さと見られる。

### 運用上の指針

- **Remote Control 経由で `delete_asset` / `save_asset` を安易に呼ばない。**
  プロジェクト全体の Blueprint ロードを誘発しうる
- 一時アセットを作る検証は、**そもそも作らない**か、
  **UE を閉じた状態でファイルを消す**前提で行う
- MCP のツールとして「アセット削除」を提供する場合、この危険性を説明文に含めること

> 本検証で作った `/Game/__ue_remote_probe_bp` は削除に失敗して残っている。
> UE を閉じた状態で `Content/__ue_remote_probe_bp.uasset` を削除するのが安全。
