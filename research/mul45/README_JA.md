# 45-Toffoli乗算の完全DQIへの適用

出発点はPR #2の検証済み完全候補、SHA-256
`655e83ab2ee40d65688e01c883a3804765080c1e47ee4e53f9d7b01bb6621177`。
既存Forney 4,095箇所とEEA商加算888箇所のinverse66置換を含む。
既存候補、既存PR、Release v1.0は変更しない。Kaggle提出は行わない。

## 置換対象

現在の回路のINFO_TAG解析では、制御付き乗算 `c_gf_mul` が32,408回ある。
内部の `gf_mul` は各63 Toffoli-like、制御付き加算が各12で計75。
前進EEA・逆進EEAに各16,204箇所で、計2,430,600演算を占める。

対象はこの内部 `gf_mul` だけ。呼出し側のreset、制御付き加算、積の測定清掃、
古典記録、条件分岐はすべて保存する。888箇所の商加算の内部乗算は
その置換時にタグを除いており、今回の32,408箇所には含まない。

## 45個の双線形積

体は多項式0x1053によるGF(2^12)。既存inverse66の出典を持つアーカイブにある
GF(2^6)の15項乗算表KT6と体の基底変換を再利用する。
表と基底の帰属は `andigu/uncompute`、Apache-2.0。
元ソース・ライセンス・定数を含む `research/inverse66/tower_inverse66_probe.zip` を保持し、
ハッシュ `25c74454ef8c00b44bb42177f491c196743f3dedd24e3ec5f096fbb60e6c19c3` を検査する。
この表自体を今回発見したとは主張しない。

GF(2^12)=GF(2^6)[t]/(t²+t+δ)とし、使用基底でδ=11。
x=a0+t a1、y=b0+t b1に対し、

\[
p_0=a_0b_0,\quad p_1=a_1b_1,\quad
p_2=(a_0+a_1)(b_0+b_1),
\]
\[
xy=(p_0+\delta p_1)+t(p_2+p_0).
\]

したがって非線形な積は3×15=45個。定数乗算・基底変換・和はGF(2)線形操作である。
144組の標準基底入力で独立した多項式乗算と一致を確認し、双線形性により全入力に拡張する。

## 追加の作業領域を使わない回路

局所契約は `|a,b,z> -> |a,b,z XOR a*b>`。a,b,zは各12量子ビットで、zは任意。
各双線形項の入力パリティを、入力レジスタ自身への可逆CX変換で一時的に作る。
出力マスクへの加算は、XOR先の1ビットを支点にするCX変換でCCXを共役して実現する。
最後に入力変換を戻す。どのレジスタにもゼロ初期値を仮定しない。

全ゲートはCX/CCXのみ。測定、位相ゲート、追加の量子・古典ビットはない。
正の置換行列なので、基底状態上の写像の完全一致は相対位相も含むユニタリの一致を意味する。
従って外部レジスタとのエンタングルメントや、呼出し側の量子制御も保持される。
測定による積の清掃は、従来と同じ入力・積を受け取るため変更しない。

36個の独立Boolean変数を使い、新回路と旧回路の双方について、
全入力の積、入力復元、任意のXOR先を厳密ANFで検査した。
CCXを1個削除した負例は拒否される。これはPythonによる有限代数検査であり、Lean証明ではない。

| 局所量 | 旧回路 | 新回路 |
|---|---:|---:|
| 量子ビット | 36 | 36 |
| 古典ビット・測定 | 0 | 0 |
| CCX | 63 | 45 |
| CX | 481 | 1,258 |
| SWAP | 21 | 0 |
| 制御付き呼出し全体のToffoli-like | 75 | 57 |

CX数は増える。評価対象のQとToffoli-likeが改善しても、ファイルサイズや
古典シミュレーション時間の短縮を意味しない。

## 完全回路への対応と検証

`quantum/mul45_dqi.py` はINFO_TAGの開始・終了をスタックで照合する。
各内部乗算が `c_gf_mul` に属することを確認し、全命令と全オペランドを
旧生成器のテンプレートに一致させる。36本の配線は単射でなければ拒否する。
量子ビット番号や並びを最初の位置から推定しない。

対象外のKMBバイト列、名前付きレジスタ、保持するINFO_TAGを照合する。
局所回路の完全なユニタリ一致により、呼出し側について新しい測定記録の寿命解析は不要。
新しい古典記録は作らない。古典条件の外側にあることも確認する。

1箇所版は `checkpoints/mul45-one-20261026.json` を参照。
Q=1,893、静的Toffoli-like=4,484,676。
完全Kickmix解析と公開検証器の1,536ショットで値・位相エラーともに0。
平均Toffoli-likeも既存の同一条件のsmoke結果から18減少した。

全箇所版の生成・検証・費用・ZIP照合は `checkpoints/mul45-all-20261026.json` に記録する。
全位置に適用した静的数は4,484,694−32,408×18=3,901,350。
完全Kickmix解析と公開検証器の102,400ショットが成功し、値・位相エラーともに0。
Q=1,893、古典ビット49,155、名前付きレジスタ4,165を維持した。

| 公開検証器の測定 | 前候補（完了済み値を再利用） | mul45全箇所版 |
|---|---:|---:|
| 平均Toffoli-like | 4,484,592.157382812 | 3,901,248.1573828124 |
| 評価費用 | 19,143,921,722,159.74 | 16,653,730,533,936.092 |

追加の実測費用削減は **13.007738040117278%**、元v1.0から合計
**31.857243121374335%**。新候補の実行時間は559.71秒。
seed=20261025、log2_delta=-128、誤り率上限0.0008660587301657926、max_workers=1。
これはローカル環境での公開検証器の結果であり、GitHub Actionsの結果やKaggle公式採点ではない。

候補KMBのSHA-256は `fc212bc49a145c2d1f3f964d3d0597f46a424604120370d54c26836fd26226dd`。
1,065,409,960 bytes、110,351,243命令。
全位置の圧縮JSON配線表は `site-map.json.gz` に保存する。
13ファイルZIPは87,828,000 bytes、SHA-256
`0c81959078c08aa809d316096565395361caa81db35c072e34a7d3a217082180`。
他の12ファイルはv1.0とバイト一致した。Qを単純な未使用配線削除で減らす余地は見つからなかった。

新候補の公開検証を実行し、既存候補の102,400ショットの結果は再利用する。
回路SHA、検証器SHA、Q、seed、ショット数、信頼水準、worker数を照合し、
旧回路の費用測定は繰り返さない。公開検証費用とKaggle公式スコアは区別する。

## 再現

既存と同じKickmix固定コミット
`638777fac4379bc62e2a1e4a52cf1a1753895d48` とNumPyを使用する。

```bash
python research/mul45/probe.py --out build/mul45-local
python -m unittest discover -s quantum -p 'test_*.py' -v
python quantum/mul45_dqi.py --reference /path/to/verified-nonforney-dqi.kmb \
  --sites 1 --output build/mul45-one
python quantum/mul45_dqi.py --output build/mul45-one --parse
python quantum/dqi_gate.py --stage smoke --baseline /path/to/v1-submission.zip \
  --candidate build/mul45-one/dqi.kmb --data-root /path/to/official-data \
  --out build/mul45-one/smoke
python quantum/mul45_dqi.py --reference /path/to/verified-nonforney-dqi.kmb \
  --sites all --output build/mul45-all
python quantum/mul45_dqi.py --output build/mul45-all --parse
python quantum/validate_mul45.py --candidate build/mul45-all/dqi.kmb \
  --integration-report build/mul45-all/integration-report.json \
  --data-root /path/to/official-data \
  --reference-checkpoint checkpoints/nonforney-20261026.json \
  --out build/mul45-all/full-report.json
```
