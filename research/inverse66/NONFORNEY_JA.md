# Forney以外の逆元計算：888箇所の監査と拡張候補

調査元は `55869a29227b065f9e8c57a2ee103a9b694bbbac`。
既存の完全Forney候補（SHA-256
`ea0d6717e7b37fb386a0d99730eebf150c0e78de1cc8547f0727c2f6845a99bc`）を出発点とする。
Release v1.0、既存の候補バイナリ、既存PRはこの調査では変更しない。
Kaggleへの提出は行わない。

## INFO_TAGを数え直した結果

`audit_nonforney.py` は全タグをスタックで解析し、開始・終了名と順序を検査する。
基準回路の3,257,126タグ、既存Forney版の2,495,456タグはいずれも整合し、最大深さは9。
祖先と包含区間から次のように分類できた。単なる回数の差による推定ではない。

| 逆元計算の祖先 | 件数 | 基準での逆元計算／清掃 |
|---|---:|---:|
| chien_forney_mbuc → forney_step | 4,095 | 315 / 0 |
| forward_eea → eea_step → multiply_and_add_or_sub → quotient_div → gf_div | 444 | 315 / 0 |
| reverse_eea → eea_step → multiply_and_add_or_sub → quotient_div → gf_div | 444 | 315 / 0 |

4,983箇所すべてで、同じ所有ブロック内の逆元計算と対応する清掃を1対1に確認した。
既存Forney版は外側の `gf_inverse_chain` タグを保持しているため、タグ数だけでは
旧315演算と新66演算を区別できない。実命令でForney 4,095箇所は66、残り888箇所は315と確認した。

全位置の包含区間は `nested-inverse-inventory.json.gz`、残る888箇所の入力・出力・
作業量子ビットと古典ビットの実対応は `nonforney-site-map.json.gz` に保存する。
いずれもgzip圧縮したJSONで、生成器は非圧縮版も出力する。
これらの区間は0始まり・終端を含まない。inventoryは両側タグを含み、
site-mapの置換区間は所有ブロックの両側タグを含まない。

## 呼出し契約と適用条件

対象はEEAの制御付き商加算である。体は多項式 `0x1053` による GF(2^12)、inv(0)=0。

\[
|a,b,t,c,0\rangle\longmapsto
|a,b,t\oplus c\,[a\,\operatorname{inv}(b)],c,0\rangle.
\]

分子a・分母b・XOR先tは各12量子ビット、制御cは1量子ビット。
tは任意の初期値、cは重ね合わせを許す。外部とのエンタングルメントも許す。
制御cは測定しない。

最初のforward位置では、a=q1740..1751、b=q828..839、t=q1809..1820、c=q1805。
積はq1821..1832、逆元はq1833..1844、旧scaffoldはq1845..1892。
逆向きを含む各位置は配線順が異なるため、全位置の実命令を単射なオペランド対応で照合した。

旧生成器は乗算へscaffoldをdirty workspaceとして提示するが、実際の888呼出しでは
その48量子ビットへのアクセスはゼロだった。一方、逆元出力には各呼出しで84回の
一時的な書込みがある。したがってForneyの「対角位相だけ・入力とscaffoldを変えない」
証明だけを、この呼出しへそのまま適用したとは主張しない。

採用した構成は既存の `eea_quotient_dqi.py` による商加算ブロック全体の置換。
inverse66 forwardで逆元と中間値を保持し、積を計算し、cで制御してtへ加算する。
積を測定と位相補正で清掃した後、inverse66 eraseで逆元・中間値を清掃する。
既存66+0の部品自体は変更しない。

| 区分 | 今回の888箇所での判定 |
|---|---|
| 66+0を保持中間値とともに使う | 全888箇所で商加算全体の契約として検査・適用 |
| 66+66が必要 | 該当なし。保持中間値を途中で捨てる設計なら代案だが今回の実装では不要 |
| どちらも適用できない | 該当なし |
| 逆元部分だけを機械的に置換 | 今回は採用せず。元の呼出しの一時的書込みまで含む契約が必要 |

局所Toffoli-like数は元の商加算390（315逆元＋75乗算・制御）から
新141（66逆元＋75）へ減少する。逆元の清掃は0。
clean inverseを2回使う代案は132＋75=207の静的試算であり、今回の生成物ではない。

37個の独立入力変数と108個の測定変数を使う厳密Boolean ANF検査により、
すべての測定分岐を記号的に扱い、上の仕様、残留位相0、作業量子ビット0を検査した。
古典一時ビットも清掃する。位相補正を1つ削除した負例は拒否される。
これはPythonの有限代数による検査であり、Leanカーネルによる証明ではない。

全888箇所が公開生成器の旧テンプレートと一致した。
パリティビットの初回使用版は1箇所、再利用前の初期化を含む版は887箇所。
13個の古典一時ビットb49140..49152は、各ブロック終了後、上書きまで参照されない。
この寿命検査は分岐を実行しない経路も含める。
外側の古典条件はなく、cによる量子制御は商のXORだけに掛かる。
入口の72個のreset、名前付きレジスタ、範囲外の命令・オペランド・残存タグを保存した。

## 完全候補と検証

1箇所候補は既存記録 `checkpoints/eea-quotient-one-site-20261026.json` を再利用した。
Q=1,893、静的Toffoli-like=4,705,557。
完全Kickmix解析と公開検証器の1,536ショットで値・位相エラー0を確認済み。
同じ費用比較は繰り返さない。

全888箇所版はこの調査で生成した。Q=1,893、古典ビット49,155、名前付きレジスタ4,165。
静的Toffoli-likeは4,705,806 → 4,484,694（追加221,112減）。
SHA-256は `655e83ab2ee40d65688e01c883a3804765080c1e47ee4e53f9d7b01bb6621177`。
完全Kickmix解析と公開検証器の1,536ショットで値・位相エラー0。

全体の102,400ショット結果と実測費用は `checkpoints/nonforney-20261026.json` を参照。
新候補は値・位相エラーともに0で合格した。

| 公開検証器の実測値 | 既存Forney版（完了済み値の再利用） | 新888箇所版 |
|---|---:|---:|
| Q | 1,893 | 1,893 |
| ショット数 | 102,400 | 102,400 |
| 値／位相エラー | 0 / 0 | 0 / 0 |
| 平均Toffoli-like | 4,705,704.157382812 | 4,484,592.157382812 |
| 評価費用 | 20,087,809,297,947.793 | 19,143,921,722,159.74 |

追加の実測費用削減率は **4.698807927674242%**、元v1.0からの合計は
**21.668025013477277%**。新候補の実行時間は504.13秒。
信頼水準log2_delta=-128、誤り率上限0.0008660587301657926で、比較側と同じ。
13ファイルZIPは66,861,303 bytes、SHA-256
`5929076f1d1b3b6d42056c985ff31209b321521ae0c3dd8384807d10906e8ba5`。
他の12ファイルがv1.0とバイト一致することも確認した。

`validate_nonforney.py` は新候補だけを実行する。比較対象はActions run
40200104339で完了済みの既存Forney版を再利用し、回路SHA、検証器SHA、Q、ショット数、
seed、信頼水準、worker数を照合する。元v1.0も既存Forney版も再測定しない。
公開検証器・非秘密saltによる費用であり、Kaggle公式スコアではない。

## 再現

既存CIと同じKickmixの固定コミット
`638777fac4379bc62e2a1e4a52cf1a1753895d48` を使用する。

```bash
python research/inverse66/audit_nonforney.py \
  --baseline /path/to/v1-dqi.kmb --reference /path/to/forney-dqi.kmb \
  --out build/nonforney-audit
python quantum/eea_quotient_dqi.py --reference /path/to/forney-dqi.kmb \
  --sites all --output build/eea-all
python quantum/eea_quotient_dqi.py --output build/eea-all --parse
python quantum/validate_nonforney.py --candidate build/eea-all/dqi.kmb \
  --integration-report build/eea-all/integration-report.json \
  --data-root /path/to/official-data \
  --reference-checkpoint checkpoints/inverse66-full-package-20261025.json \
  --out build/eea-all/full-report.json
```
