# ARC-AGI-2: symbolic candidate

ARC-AGI-2 の各問題に含まれる入出力例から、有限の変換規則を探索する CPU 用候補です。
Python と NumPy の探索に、Johan S. Wind 氏の C++ 製 DSL 探索器を組み合わせます。
外部 API、モデル重み、インターネット接続を推論に使いません。
このフォルダーだけで実行でき、Kaggle 用 Notebook はライセンスとソースを内蔵します。

## 実行

ローカル実行は Python 3.11 以上を想定し、今回の検証は Python 3.12.14 / NumPy 2.3.5 です。

```bash
python -m pip install -r requirements.txt
python -m arc2 solve --challenges challenges.json --output submission.json --diagnostics diagnostics.json --seconds-per-task 8 --max-states 4000
```

`challenges.json` は `{task_id: {train: [...], test: [...]}}` 形式です。
Python API では `arc2.solver.solve_task(task)` を呼べます。戻り値の `attempts` を
既存の `dual_arc` に取り込むこともできます。`test` に答えが入っていても、推論に渡すのは
入力のみです。既存 v3 のコードは今回取得できていないため、v3 の改修・再現とは扱いません。

CLI の既定は `--backend hybrid` です。POSIX 環境で C++17 対応の `g++` があれば、最初に
一度だけ同梱ソースをコンパイルします。利用できない場合は理由を記録して Python 探索に戻ります。
Python だけで動かす指定は `--backend python` です。Python API の既定は Python のみです。

## Kaggle

1. `arc2_kaggle.ipynb` を ARC Prize 2026 – ARC-AGI-2 の Notebook として読み込みます。
2. 競技データを追加し、CPU、インターネット無効で実行します。
3. 実行完了後の `/kaggle/working/submission.json` を確認します。

Notebook は `arc-agi_test_challenges.json` / `arc_agi_test_challenges.json` を既知の競技マウントから
探します。複数候補が見つかった場合は勝手に選ばず、`ARC2_CHALLENGES` に正しいパスを指定します。
Notebook の生成や実行だけでは、競技への公式提出は行いません。

問題ごとの上限、総時間上限、探索状態数、beam 幅、深さを変更できます。総時間の既定上限は
11 時間です。各問題を別プロセスに分け、時間超過や例外があっても全 task ID と全 test 入力に
対する有効な JSON を残します。その場合の保険は入力のコピーであり、正解の保証ではありません。

検証と Notebook の既定条件は、1 問 8 秒、Python の最大 4000 状態、beam 幅 32、深さ 3、
C++ への時間配分 0.6、C++ プロセスの仮想メモリ上限 768 MiB です。Python が早く終了した分の
残時間も C++ に使います。C++ は深さ 1、2、3 と進め、途中で時間切れになっても、完了した深さの
候補を保持します。

同じコードで 32 秒条件も測定しました。公開評価は 8 秒で 0/167 出力、32 秒で 1/167 出力
（0.60%）でした。競争力のある精度にはまだ達していません。詳しくは `RESULTS.md` を参照してください。
32 秒条件で動かすには CLI に `--seconds-per-task 32` を渡します。Notebook は実行セルより前に
次を追加してください。

```python
import os
os.environ["ARC2_SECONDS_PER_TASK"] = "32"
```

## 探索の構成

| 部品 | 役割 |
|---|---|
| 幾何・色・寸法 | 回転、反転、転置、切り出し、拡大縮小、繰返し、余白、色置換 |
| 物体 | 連結成分の選択、形・大きさ・接触関係による色変更、穴・矩形の充填、重力、型の複製 |
| 局所・構造 | 近傍の色や個数、行列の文脈、対称性・周期の復元、パネルの合成、マーカーの接続 |
| 合成探索 | 中間盤面を保持し、複数の変換と最後の色置換を組み合わせる |
| C++ DSL | 汎用の盤面部品を列挙・合成する別系統の探索。元の学習例への一致数を出力 |
| 候補選択 | 全学習例への完全一致を優先し、テスト入力ごとに異なる予測を最大 2 つ残す |

「学習例に完全一致する」と「未知の出力が正しい」は別です。十分な完全一致候補がない場合は、
学習例への一致度を使った仮説を返し、診断にその区別を残します。順位づけの重みは校正済みの
正解確率ではありません。

## 同値性と既存の形式化との接点

Python 側では、同じ中間盤面に到達した探索経路をまとめます。比較するのは、学習入力だけでなく
**今回の全テスト入力にも適用した結果**です。学習例では同じでもテスト入力で異なる候補を
早まって捨てません。色や形の粗い特徴量による同一視も行いません。

既存の `primitive-lean` にある将来観測同値の議論との対応と、その適用範囲は
`DESIGN.md` に記載しています。今回の Python 実装を Lean から抽出したわけではなく、
Python 実装全体の形式検証が完了したという主張もしません。

## 再評価

```bash
python tools/fetch_data.py --help
python -m arc2 evaluate --tasks /path/to/ARC-AGI-2/data/training --output reports/training/report.json --limit 100 --seconds-per-task 8 --max-states 4000
python -m arc2 evaluate --tasks /path/to/ARC-AGI-2/data/evaluation --output reports/evaluation/report.json --seconds-per-task 8 --max-states 4000
python -m unittest discover -s tests -v
```

公開評価は開発用の調整に使わず、コードと設定を固定して実行してください。
評価器は答えを推論プロセスに渡さず、予測の書出し後に採点します。
Kaggle に対応する「test 出力単位の完全一致 pass@2」と、より厳しい「全 test 出力が正しい問題数」を
両方記録します。データ・コード・予測の SHA-256、設定、処理時間、例外・打切り状況も保存します。

最新の実測値と限界は `RESULTS.md` を参照してください。

## 由来とライセンス

新規に作成した Python ソースは MIT-0 です。`vendor/icecuber` は MIT ライセンスで、
Johan S. Wind 氏の [DSL solution to the ARC challenge](https://github.com/top-quarks/ARC-solution)
（2020 年）の汎用探索コードを使っています。固定コミット、除外ファイル、変更箇所は
`vendor/icecuber/PROVENANCE.md` に記録しています。
元の `dual_arc` の索引と既存結果は
`Sumuji-zkdwn/research-integration-hub` の `hub/arc-map.json` で確認しました。
元コード・元の個別評価レポートはここには含めていません。

評価データは [arcprize/ARC-AGI-2](https://github.com/arcprize/ARC-AGI-2)、
固定コミット `f3283f727488ad98fe575ea6a5ac981e4a188e49`（Apache-2.0）です。
Notebook に公開評価の問題・答え・予測結果は埋め込んでいません。

仕様の根拠:

- https://www.kaggle.com/competitions/arc-prize-2026-arc-agi-2/
- https://arcprize.org/competitions/2026/arc-agi-2
- https://github.com/arcprize/ARC-AGI-2

