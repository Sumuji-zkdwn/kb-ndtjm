# DQI BM：GF(8)までの相対トレース位相融合

比較元はPR #6の検証済みソース `0b747a9eb18f351c2b88e7126e665611ad0786f6`、記録込みhead `8a37e482a7453908b31f943b2097ae12b4e7457e`。新しい独立ブランチで作業し、以前の候補・検証済みソース・Release v1.0は変更しない。Kaggle公式提出は行わない。

## 構成と検証前の見積もり

前候補のGF(4096)/GF(64)相対トレースを、さらにGF(64)/GF(8)へ移す。F=GF(4096)、K=GF(64)、L=GF(8)、Dは分母、Nは分子、Cは実行時Eマスクの絶対トレース双対とする。inv(0)=0を用いる。

```
A = Norm_F/K(D) = D*D^64
B = Norm_K/L(A) = A*A^8
Z = B^-1 = (B^3)^2
D^-1 = D^64 * A^8 * Z
G = Tr_F/K(C*N*D^64)
H = Tr_K/L(G*A^8)
phase = root * Tr_L/2(H*Z)
```

元のtowerでA=a0+a1*alpha、G=g0+g1*alpha、alpha^8=alpha+1なので、H=g0*a1+g1*a0。KT3の6積乗算を2回使う。前候補でA^-1を作っていた12積を削り、Hを作る12積に置き換える。最後のroot制御CCZが6個から3個へ減る。

| 指標 | PR #6 | 新候補の検証前見積もり |
| --- | ---: | ---: |
| Q | 2482 | 2482 |
| inverse phaseのToffoli-like／点 | 72 | 69 |
| 根判定11演算込み／点 | 83 | 80 |
| Forney全体 | 339885 | 327600 |
| 完全DQIのToffoli-like | 732166 | 719881 |
| 公開検証器の評価費用 | 5373037115324.774（保存済み実測） | 5282883023272.201（同じ誤り率上限での推定） |

12285演算、費用1.67789818156%減の見込み。v1.0比の累積削減は推定78.3838089181%。新候補の実測と区別する。単独のinverse66が安くなる主張ではない。

## 生存期間と清掃

Forneyの81本の論理作業領域と、清掃済みEm pivots 3本の借用を維持する。新規確保やリセットは追加しない。canonical wiringは既存のden0:12、U12:24、Norm6 24:30、Norm3 30:33、cube3 33:36、旧Y6 36:42、pivots42:45、num45:57、root57。

1. 逆元towerの最初の3段だけを実行する。Norm6・Norm3・cube3は生存したままにする。
2. omegaからnumを評価し、実行時マスク依存のCXでU=C*Nを作り、numを清掃する。
3. numの先頭6本へGを計算する。その間Norm6とcube3を保持する。
4. 使われなくなった旧Y6の先頭3本へHを計算する。
5. cube3を平方写像とGF(8)トレースGram行列で一時変換し、root/Hとの3個のCCZを適用する。逆写像でcube3を戻す。
6. Hを測定清掃・位相返済してから、Gを測定清掃・位相返済する。順序は必須。
7. numを再評価してUを消し、numを清掃する。最後にprefixを逆順の測定清掃で消す。

所有権・確保解放時点・ピークは変えない。35スロットの完全履歴、正確な全係数、任意の実行時Eマスク、入力復元は維持する。

## 局所証明と回帰検査

PythonのBoolean ANF検査器と合成論法を信頼する厳密な局所検査であり、Lean検証ではない。

- prefix：Dの4096入力を独立な有限体演算で評価してNorm6とcube3の全9ビットを照合。全18個のNorm6_i*cube3_jに独立したコヒーレント係数を付け、36個の独立測定変数を含めても清掃が位相を保存することを確認。
- middle：D12、N12、独立Norm6、独立cube3、root1、mask12の46変数と51個の独立測定変数を扱う。31104個の基底テンソル成分から独立に作った理想位相との一致を確認。全入力と作業領域を復元する。
- middleはNorm6とcube3に双線形なので、prefixの18個の独立係数へD/N/root/mask依存係数を代入できる。
- 位相ゲート、通常の測定補正、追加したHの清掃補正を抜いた負例をそれぞれ拒否。実際の組込みemitterを非自明な物理配線とマスク番号で証明済み命令列に照合。
- 既存36件と新規3件、計39回帰テストが合格。局所回路はnative Kickmix parserでも69 Toffoli-likeと確認。

## 再現と段階検証

```sh
python -m unittest discover -s quantum -p 'test_*.py' -v
python research/bm_port/trace_phase3_probe.py --out build/trace-phase3-local
python research/bm_port/build_dqi.py --out build/bm-tracephase3 --trace-allocations --trace-phase3
python research/bm_port/build_dqi.py --out build/bm-tracephase3 --parse
python quantum/bm_trace_phase_audit.py --reference build/bm-tracephase/dqi.kmb --candidate build/bm-tracephase3/dqi.kmb --nested --out build/report/trace-phase3-correspondence.json
```

新フラグ `--trace-phase3` のみが本候補を選択する。従来フラグと既定の旧実装は引き続き再現できる。全KMBのForney境界外のopcode・配線・古典条件と測定先・名前付きレジスタを一致検査する。

candidate→smoke→full-packageの順に公開検証器で検証する。比較元の再測定はせず、記録 `checkpoints/bm-tracephase-20261027.json` のSHA-256を `8b80aec2341c3b016b5dbd0ac74a8b78a8c1b353407766370df7c7b5ce39414d` に固定し、実回路ハッシュ・ヘッダ・検証器ハッシュ・設定・誤り上限・費用を再照合して保存済み実測を再利用する。新候補は新たに102400試行で検証する。追加の深い履歴・可変Eマスクと、v1.0との全13ファイルのZIP照合も実行する。

完全DQIの公開検証器による確定結果は次節に記す。上記の検証前見積もりと区別する。

## EEA商加算案との関係

旧EEAの141→120 Toffoli案の商加算呼出し箇所はBMで不要になっている。共通する42積GF(4096)乗算はBMで既に使われており、再度削減として数えない。本変更はEEA局所置換ではなく、Forneyの逆元出力を最後の位相へまとめる部分体トレース処理である。


## 公開検証器の確定結果

**費用1.67789818156%減を実測で確認した。v1.0比では累積78.3838089181%減。** [Actions run 40414437653](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/40414437653)はsuccess。検証ソースは `240ba77a94e01e4d35bc82d936833ae2fbae783f`。後続コミットは記録のみとし、同じ重い検証を再実行しない。

| 指標 | 比較元PR #6 | 新候補PR #7 |
| --- | ---: | ---: |
| Q／ピーク生存数 | 2482 | 2482 |
| 静的・実測平均Toffoli-like | 732166 | 719881 |
| ForneyのToffoli-like | 339885 | 327600 |
| 総命令数 | 91240005 | 90986115 |
| 完全DQIのバイト数 | 857042827 | 854708677 |
| 評価費用 | 5373037115324.774（保存済み実測） | 5282883023272.201（今回の新規実測） |
| fullの値／位相エラー | 0 / 0 | 0 / 0 |
| 提出ZIPのバイト数 | 83375624 | 83310332 |

新規102400ショット、seed=20261025、batch_size=1024、max_workers=1、log2_delta=-128。誤り率上限は0.0008660587301657926、公開検証器SHA-256は `f14274bc0943fb9769ddb01131be6063191a15009fe1caf1d4bdd9fd25194e65`。全件測定457.68秒。計算機・計測条件の変動があるため、単発の経過時間をCPU高速化の証拠とはしない。比較元の再測定は行っていない。

candidate、smoke、full-packageが順にPASS。追加の55種類の誤り配置・1536試行も値／位相エラー0/0で、weight35かつ最初の34シンドロームがゼロのケース、zero/all/single/randomのEマスクを含む。全13ファイルのZIP CRC・ハッシュ検査がPASSで、①InvSqrtと③DFTHC-SOSを含む他12ファイルはv1.0とバイト一致する。

ローカルとCIの生成記録・完全回路ハッシュ・局所証明・6257件の割当ログが一致した。前候補との割当イベント比較では、op_index以外の確保・解放・所有者・配線・フェーズ境界がすべて同一。ピーク所有数はsyn840、held23、sig432、bb444、stk665、forney78の計2482。Forney確保はop13971812、Forney本体はop13971812–67366519、その後78本を解放。最終生存領域は外部Sの840本のみ。ログは状態のゼロ性の証明ではなく、局所清掃の正確性は上記ANF検査で確認する。

[証拠一式](../checkpoints/bm-tracephase3-20261027.json)、[完全割当ログの圧縮JSON](../checkpoints/bm-tracephase3-allocations-20261027.json.gz)を保存した。圧縮ログSHA-256は `3097423fbe8923820a3c8a92e04944614185fc991d90a58085afeea90203ad2f`。検証記録アーティファクトをダウンロードし、SHA-256 `a3f18374e63d87b00fa85d32766ebda8ebca845ff8d177c70b4ec86c6cfed8b4` を照合した。

DQI SHA-256: `a5b128745d2a5bd76ab67faf1f141103de3c0e8c8d54535753bdc7716aaefc06`。

[検証済み候補アーティファクト](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/40414437653/artifacts/12694318660)の内側の `submission-candidate.zip` は83310332 bytes、SHA-256 `24d4a4f91127227959b01fd073e526ec2a80cd68f68bba59410ae46a01b8c246`。提出ZIPのローカル再ダウンロードは行っていない。Actionsアーティファクトは2026年11月25日に期限が来るが、ソースと検証記録は本ブランチに残る。

PR #4・#5・#6、以前の検証済みソース・候補、Release v1.0は変更していない。Kaggle公式提出および公式スコア測定はNOT_RUN。評価費用の比較は公開検証器のDQI単体についての結果である。
