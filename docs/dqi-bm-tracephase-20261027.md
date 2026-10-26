# DQIに集中した次の改善：Forneyの逆元と位相を有限体トレースで融合

基準はPR #5のQ=2482、Toffoli-like=756736の検証済み候補。独立ブランチ `wfs/dqi-bm-tracephase-20261027`、[PR #6](https://github.com/Sumuji-zkdwn/kb-ndtjm/pull/6)で進める。①InvSqrtと③DFTHC-SOS、既存のDQI候補、PR #5、Release v1.0は変更しない。Kaggle公式提出は行わない。

## 計算の置換

旧Forneyは4095の評価点それぞれで、逆元66・根判定11・位相核12の計89 Toffoli-like演算を使う。逆元単体の66を削る代わりに、逆元と直後の位相をまとめる。

\(F=\mathrm{GF}(2^{12}), K=\mathrm{GF}(2^6)\) とする。分母を \(D\)、分子を \(N\)、Eマスクを線形汎関数 \(L_m(x)=\operatorname{parity}(m\mathbin{\&}x)\)、根判定を \(r\) と置く。トレース対の非退化性から、各マスクに対して \(L_m(x)=\operatorname{Tr}_{F/\mathrm{GF}(2)}(C_mx)\) を満たす \(C_m\) が一意に決まる。

\[
\bar D=D^{64},\qquad \nu(D)=D\bar D\in K,\qquad Y=\nu(D)^{-1},\qquad D^{-1}=\bar D Y.
\]

逆元はゼロでゼロと定義する。この式はD=0を含む4096入力すべてで検査した。トレースの合成則で、必要な位相指数は

\[
rL_m(ND^{-1})
=r\operatorname{Tr}_{K/\mathrm{GF}(2)}\left(\operatorname{Tr}_{F/K}(C_mN\bar D)Y\right).
\]

原典の二次拡大基底 \(\beta\) は \(\beta^{64}=\beta+1\) を満たす。\(D=d_0+d_1\beta, U=C_mN=u_0+u_1\beta\) とすると、

\[
\operatorname{Tr}_{F/K}(U\bar D)=u_0d_1+u_1d_0.
\]

Uは実行時の古典Eマスクを条件とするCXだけで構成する。右辺は既存のGF64乗算2回、各15積で作れる。最後のトレース対は6次元なので、根で制御された位相ゲート6個で済む。

| 局所部分 | 旧版 | 新候補 |
| --- | ---: | ---: |
| ノルム逆元までの中間処理 | 36 | 36 |
| 最後の2回のGF64乗算 | 30（12ビット逆元出力を作る） | 30（6ビットのトレース係数を作る） |
| 根制御の位相 | 12 | 6 |
| 根判定 | 11 | 11 |
| 1評価点の計 | 89 | 83 |
| 全4095点 | 364455 | 339885 |
| 完全DQI | 756736 | 732166（生成・全体検証で確認予定） |

**単独のinverse66を66未満にしたという主張ではない。** 逆元の出力を位相へ利用するForney境界に特化した融合である。Qを2482に保てるなら、Tおよび評価費用の削減見込みは3.2468390561569684%。費用推定は5,373,037,115,324.774。新回路の公開検証器による実測とは区別する。

## 生存期間・清掃・証明

81本のForney論理作業領域と、前候補の清掃済みEm補助3本の借用を維持する。12ビットの旧逆元出力領域をUに使う。分子NをomegaからCXで評価し、Uへ変換した後、N領域をゼロに戻す。その先頭6本をトレース係数の保存に利用する。位相付与後、係数を測定清掃・位相返済し、Nを再評価してUをCXで消し、Nを再度ゼロへ戻す。最後にノルム逆元の中間領域を清掃する。新しい量子領域の確保や不正なリセットは追加しない。

証明は二つの正確なBoolean ANF等式と代入による合成からなる。Python検査器の意味論を信頼するもので、Leanでの形式証明ではない。

1. ノルム逆元の前処理：Dの全4096入力の独立な有限体計算からANFを得て、回路の6ビットYと照合。任意の独立した6個のコヒーレントな位相係数を付けても、対応する測定清掃が入力と作業領域を復元し位相を保存することを検査。54個の測定変数を独立として扱う。
2. 中間のトレース位相：D12、N12、Y6、root1、mask12の43変数と36個の測定変数を独立に扱い、10368個の基底テンソル成分から独立に作った理想位相と厳密比較。すべての量子入力を復元し作業領域をゼロへ戻す。実際の組込みemitterと証明済み命令列の一致も回帰テストで検査。
3. 中間位相のYに依存する係数はD/N/root/maskだけから作られ、ノルムの中間値には依存しない。1の任意係数へ代入することで、正しいinverse phaseと清掃が従う。

位相ゲートまたは測定後の補正を抜いた負例は拒否された。36テストが合格。マスクの固定、係数の経験的切り捨て、35スロットの履歴の省略はない。

## 再現と段階検証

```sh
python -m unittest discover -s quantum -p 'test_*.py' -v
python research/bm_port/trace_phase_probe.py --out build/trace-phase-local
python research/bm_port/build_dqi.py --out build/bm-tracephase --trace-allocations --trace-phase
python research/bm_port/build_dqi.py --out build/bm-tracephase --parse
python quantum/bm_trace_phase_audit.py --reference build/input/bm-scratch3/dqi.kmb --candidate build/bm-tracephase/dqi.kmb --out build/report/trace-phase-correspondence.json
```

`--trace-phase` を付けなければ従来のForneyを生成する。全KMBの比較では、Forneyの境界外の命令・量子配線・古典測定先と条件・名前付きレジスタを厳密照合し、BMの前進・逆進・履歴処理に変更がないことを検査する。

[Actions run 40396549680](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/40396549680)でcandidate→smoke→full-package、深い履歴・可変Eマスク、13ファイルZIP照合を実行中。検証対象ソースは `0b747a9eb18f351c2b88e7126e665611ad0786f6`。現時点で全体検証合格は未確認。

比較元のQ2482候補は直前の成功した全件測定を再利用する。checkpointのSHA-256を `9a7036ef69e46788ab20542e0a22dc21f54ba9ee4c99d2e7b03f4bd28f65bda5` に固定し、取得した実回路のハッシュ・ヘッダ、検証器のハッシュ、seed、102400試行、batch_size=1024、log2_delta=-128、誤り率の上限、費用の再計算を照合してから使用する。**新候補は必ず新規に全件測定する。** 旧候補やv1.0を再度重く検証する処理は起動しない。

## 次のBM側の調査対象

現行のソースと完全なCAPSから数えると、履歴押し出しの条件付きSWAPは順計算21495個、SIG/BBバンクの条件付きSWAPは22632個。逆再生にも同数あるため計88254 Toffoli-like演算、現行756736の約11.66%である。これはその全部が除去可能という意味ではない。35スロットと可逆清掃を維持した別候補として調べる対象であり、今回のForney融合には混ぜていない。
