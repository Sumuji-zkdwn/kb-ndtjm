# ARC3観測情報の保持監査 — 2026-11-01

## 結論と範囲

**実装上の情報欠落は再現した。実ゲームとWFSの4位相状態との対応は構成できていない。**

CPUの最終フレーム射影、GPUのアニメーション要約による順序の消失、連続同一フレームの畳込みによる重複数の消失を、固定Notebookから取り出した実際の観測関数で検査した。保存済みの実ゲームログにも、操作前後の盤面は同じだが途中の観測が変化する例がある。ただし、GPU基準版はその直後には最後のアニメーションを参照でき、モデルが実際に参照した記録もある。「GPU基準版は中間フレームを全く見ない」という結論ではない。

追加するのは、独立したオフライン監査、再生用fixture、任意導入の生パケット記録器である。既存方策へのDFT特徴・メビウス更新の適用、基準Notebookの差替え、改善サイクルの再開は行わない。情報保持テストの成功を攻略性能の向上とは扱わない。

## 固定した資料

| 資料 | 固定版・証拠 |
| --- | --- |
| primitive-lean PR #19 | `6bd74237f7b1910942988e6f542987857e9dec91` |
| Lean検査・公理監査 | [Actions 41232573849](https://github.com/Sumuji-zkdwn/primitive-lean/actions/runs/41232573849)、同SHAでsuccess。今回Leanを再実行した結果ではない |
| ARC3実装 | [PR #10](https://github.com/Sumuji-zkdwn/kb-ndtjm/pull/10)、`06ec316097d4bf22a44bfbd82dceb63f717680c4` |
| 既存サイクル | [PR #9](https://github.com/Sumuji-zkdwn/kb-ndtjm/pull/9)、`2e4e3063c22ec32220b6b95b2ec83748c1a40f15` |
| GPU基準候補 | `gpu-baseline / ready-v2 / Version 1`、公式提出ID `57751913`、保存receiptは `COMPLETE / Public Score 26.20` |
| 証拠artifact | [run 40846700062 / artifact 12885411756](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/40846700062/artifacts/12885411756)、2,128,084 bytes / 144 files |
| 停止指示の補強資料 | [PR #12](https://github.com/Sumuji-zkdwn/kb-ndtjm/pull/12) は停止中のPR #9の対象ブランチを更新しないよう明記 |

主要SHA-256:

```text
artifact ZIP:
13614fe9725bae81c244e0d89b370ab6cb3fbce85f20fb8b305a3af07273b785
GPU基準Notebook / gpu-baseline-connected.ipynb:
f74e393d583dda6a3800dfd48f7b95e399074185b1e46a2bc7e5db464a05185a
GPUコードセルのidentity:
622b51d40e2a86f54251ec0627f16067d9e99a6e42ed24940285b8d33a0c8cd4
CPU / cpu-c8b.ipynb:
03788c46195a6e48c8d865d67788f0d542472f0a29c4dffb67a9eabaf6874b8c
sc25保存prompt:
7546033b08b703b16fa2bdc33911b24121831acfd424e96dcdb5ce8cccd9debb
```

Notebookはartifact内の実提出候補とリポジトリのファイルがバイト一致する。`verification/protected_sources.json`は元の83テキストファイルのGit blob SHAを保持し、監査の前後に照合する。取得対象外の既存図版2ファイルも、リモートの元treeを継承して保持する。

## 観測経路の実読結果

| 段階 | 実装・保存内容 | 今回確認した限界 |
| --- | --- | --- |
| 公式Agent取得 | `cycle/framework/agents/agent.py` は各実操作の応答を追加し、`_convert_raw_frame_data`は全返却フレームを変換 | 固定stride=2の取得は見つからない |
| CPU方策入力 | Notebook内 `agent.Observation.from_frame` が `frame.frame[-1]` を使用 | 方策の観測キーは中間像を区別しない |
| CPU履歴 | Agentの`frames`は全応答を保持。coreのTransitionLedger等は終端から作ったObservationを使う | 生の履歴が残ることと、方策のキーがそれを使用することは異なる |
| CPU公開検証ログ | `autonomous/evaluate.py`は全返却像とlevelをSHA-256化。`record=False` | 異なるpacketの検出は可能でも、hashから像・順序を復元できない |
| GPU最新の変化 | `_animation_chain`が全返却像を読み、`last_animation_frames/timeline`が順序付き変化を公開 | 隣接同一像の重複数は`collapse_frames`で消える |
| GPU長期履歴 | 操作ごとの終端像と結果。animation要約にはフレーム数・transient数・bbox | 変化順序が要約で消える。詳細は単一`animation_record`で、次の非RESET操作により置換される |
| GPU操作バッチ | 実行された各操作ごとに`_execute_action`を呼ぶ。返却結果はbatch末尾を中心に統合 | batch終了時の単一animationだけでは、以前の詳細系列を読めない。拒否・省略操作は実操作と別扱い |
| 自動RESET | 既存実装は死亡直前のanimationを残す | 新記録器ではRESETを別イベント・境界として保持する |

CPUの埋込み`public_observer.py`には全frameを持つ別クラスもあるが、稼働中のc8b adapterに接続されていない。必要フィールドも異なるため、単純なクラス差替えは今回行わない。

GPUの4画素border除外やCPUの探索用3画素border除外は**空間的圧縮**である。モデル会話のtoken上限による切詰めは**テキスト履歴の圧縮**である。どちらも「2時刻ごとのフレーム取得」と混同しない。

通常Save VersionのGPU検証は、最大2操作/ゲーム・90秒/ゲーム・並行4ゲーム・1pass・全体5分の設定。これらは実行予算であり、等時間間隔の観測を意味しない。競技側は別予算で、`save_request_logs=False`。今回読めたpromptログは公式26.20採点時の全エピソードではない。

記憶版48イベントの`observed_cost.engine_wall_seconds`は約0.172〜4.508 msで、`executed_engine_calls`は全件1だった。これは**エンジン呼出しの所要時間**であり、操作間隔・アニメーションのフレーム間隔ではない。同イベントのmetadataには絶対操作時刻・生frameの時刻のフィールドがなく、保存物から等間隔サンプリングは確認できない。範囲はこの48イベントに限る。

## 実ログ: sc25の戻ってくる観測

通常検証の`sc25-635fd71a`、第1操作`UP`は、次を同時に記録している。

```text
board_changed=False; gameplay_changed=False; no_op=True
frame_diff_changed_cells=0
animation.frames=5; transient_pixels=36; bbox=[49,24,61,36]
```

ログに出力されたtimelineから、上・左・右・下の4つの3×3領域について、白を0、薄緑を1とする射影を復元できる。

| 順序 | 射影 | 実際の変化 |
| --- | --- | --- |
| 操作前 | `(0,0,0,0)` | 4領域とも白 |
| 1 | `(1,0,0,0)` | 上の9画素が点灯 |
| 2 | `(1,1,0,0)` | 左の9画素が点灯 |
| 3 | `(1,1,1,0)` | 右の9画素が点灯 |
| 4 | `(1,1,1,1)` | 下の9画素が点灯 |
| 5 | `(0,0,0,0)` | 36画素が消灯 |

これは**1操作の中の5変化**であり、Hを4回適用した軌道ではない。既存モデルが`last_animation_timeline`を読み、上記順序を出力しているため、この時点では情報にアクセスできた。

`fixtures/sc25_observed_projection.json`は、実ログの座標列を検査して作った射影であり、全盤面の再生データではない。重複frameはログ生成前に除かれており、持続時間は復元できない。

## 小規模反例と回帰テスト

### PR #19に一致する合成モデル

`S={-1,0,1}²`、`H(x,u)=(-u,x)`、観測`K(x,u)=x`を完全列挙する。負指数・1/4正規化DFTを有理数の実部・虚部で検査する。

| 保持内容 | 9状態から得る異なる署名数 |
| --- | ---: |
| 順序付き4連続観測 | 9 |
| 偶数位置のみ | 3 |
| packetの最終像のみ | 3 |

`(0,0)`と`(0,1)`は偶数観測で一致する。`(1,0)`と`(-1,0)`は4像packetの最後が一致し、Hによる次の像は異なる。後者を3マスのトークン位置で描画し、**実際のCPU Observationクラス**でも同じキーになることを検査した。パレット番号を座標値とみなす操作はしていない。

この特定モデルの状態復元には隣接2観測で足りる。4という数はDFT例の長さであり、ARC一般に必要十分な履歴長ではない。振幅・powerのみでは位相が消える負の対照も含める。メビウス対合は正の有理数強度から作る座標と`z>-1/2`上で厳密検査し、実数`exp(x)`の数値検査や実ゲームの強度同定とは区別する。

### 実際のGPU要約関数の衝突

次の二つの**合成**系列を既存の純粋関数へ入力する。

```text
(0,0) → (1,0) → (1,1) → (0,0)
(0,0) → (0,1) → (1,1) → (0,0)
```

最新のanimation chainは区別できるが、両方の要約は`frames=3, transient_pixels=2, bbox=[0,0,0,1]`。後続の単純な操作を行うスタブ検査でも、新記録器は以前の順序の差を保持する。これは実際のGPU要約関数の非単射性の反例であり、実ゲームで同じ行動条件から分岐する隠れ状態を2つ発見したという主張ではない。

別の負の対照では、隣接同一像が1枚多いpacketが既存`collapse_frames`で同一になる。新記録器はそれらを区別する。ただし、frame枚数を物理経過時間と読み替えない。

## 最小の任意導入観測器

`observer.py`は、`_HarnessGameSession._execute_action`に明示的に取り付ける記録専用フックを提供する。

1. 元のメソッドを1回だけ呼ぶ。
2. 各実操作の直後、次のbatch操作前に`current_state.raw.frame`をコピーする。
3. 収録session ID、操作番号、batch位置、操作ID・座標、全subframeの順序と重複、自動RESET、level、実測呼出し時間・単調時計での応答時刻を記録する。
4. 元の返却オブジェクトをそのまま返す。元の例外も再送出し、記録失敗で操作を再試行しない。

初期・RESET・level変更・ゲーム変更・観測欠落・操作番号欠落を区別する。返却像のindexはAPI応答内の順序であり、時刻の等間隔性は保証しない。単調時計は同一process内の呼出し・応答間隔を調べるための値で、UTC時刻やゲーム内tickではない。8packet/262,144cellの既定上限は資源設定であり、理論上の最小値ではない。上限ではpacket全体を削除し、削除数を表示する。任意のJSONL sinkを指定すれば、保持窓から出たpacketも保存できる。sink失敗は別に記録する。

**このフックは方策の入力に新しい特徴を渡さず、importだけでは導入されない。今回基準Notebookへ取り付けていない。** 保存・比較用の候補であり、スコア改善版Notebookではない。実際のKaggle/GPU環境ではフックの時間・メモリ費用、全upstreamとの統合が未検査である。

導入対象は、別のオフライン作業コピーのsessionクラスとする。元のharness moduleから当該クラスを読み込んだ後にだけ、次の形で明示的に利用する。

```python
from observer import install_gpu_session_observer
uninstall = install_gpu_session_observer(_HarnessGameSession)
# 既存の有限オフライン実行を行った後、session.observation_tapeを検査する。
# この操作例自体はゲームを開始しない。
uninstall()
```

## 再現

Python 3.12以上とNumPyを使用する。今回のPython版は`verification/audit_result.json`に記録する。既存Notebookは実行せず、SHA固定後に必要なASTだけを取り出す。

リポジトリrootから:

```bash
python -B experiments/arc3/observation_audit/run_audit.py --out build/observation-audit-new
```

過去artifactを再解析する場合だけ、既に取得したローカルZIPまたは展開directoryを指定する。コマンドはネットワーク取得をしない。

```bash
python -B experiments/arc3/observation_audit/run_audit.py --out build/observation-audit-with-evidence --evidence /path/to/arc3-cycle-evidence.zip
```

出力先は未存在のdirectoryを要求する。元Notebook、request、workflow、停止状態を更新しない。監査processのsocket接続を遮断して検査する。既存83テキストblobの前後照合、合成モデル、実関数の反例、保存射影、記録フックの契約を検査し、実行数・失敗・skipを結果に記す。GPU全体の実行テストとして報告しない。

保存した最終結果は**37 tests / 0 failures / 0 errors / 0 skipped**。原始モデル14件、記録器・フック16件、固定済み本番観測コード7件である。

## 実ゲームへ定理を適用するために不足する条件

必要なのは、実状態`S`から`(x,u)`への具体的な写像`φ`と、固定された更新`U`について、少なくとも検証対象範囲で`φ(U(s))=H(φ(s))`、観測`K(s)=first(φ(s))`を確認することである。行動依存なら同じ行動列または固定controllerを比較し、必要な方策記憶・乱数・時計も状態に含める。

現在不足しているもの:

- どの画面特徴が`x`、どの未観測変数が`u`か。
- 1操作、1返却subframe、定理の1更新の対応。
- RESET・levelを跨がない同条件の十分な連続記録。
- 観測上同じ終端を持ち、同じ後続行動で異なる将来へ分かれる実ゲームの対。
- WFSに用いる正強度`r=exp(x)`の意味と定義域。
- 追加の保持情報を方策が使用する方法と、同一予算の攻略性能比較。

記憶版の保存snapshotは25ゲーム・48イベント、各ゲーム最大2イベントで、中間の生frameなし、`witness_pairs=0`。この0は状態対応の不存在証明ではなく、この証拠では実例を構成できないという結果である。基準版promptで明示的なtransient注記が見つかった6ゲームも、アニメーションのあるゲームの総数ではない。

## 評価の切り分けと終了状態

| 評価項目 | 今回の到達点 |
| --- | --- |
| 合成Hモデルの位相欠落 | 厳密完全列挙・DFT検査成功 |
| 既存観測関数の情報欠落 | 具体的入力対で再現 |
| 保存された実ゲームの途中変化 | sc25の射影を出典付きで再構成 |
| 順序・重複を保つ記録器 | 容量制限・境界・失敗・返却値のオフライン回帰検査成功 |
| 実ゲームのWFS対応 | 未構成 |
| GPU全体への統合 | 未実行 |
| 実ゲーム攻略・スコア改善 | 未測定 |
| 公式提出 | 0回 |
| 停止中サイクル | 再開なし |

新規ファイルはこの`observation_audit/`以下だけに置く。既存branchへのpushやmergeをせず、独立したdraftでレビューできる状態にする。今回の終点は情報保持の検証であり、追加のゲーム探索や公式採点ではない。
