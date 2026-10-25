# 42-Toffoli乗算の完全DQIへの組み込み

基準は、Forney inverse66全4,095箇所とEEA商加算全888箇所を置換した検証済みDQI。
SHA-256は`655e83ab2ee40d65688e01c883a3804765080c1e47ee4e53f9d7b01bb6621177`。
Release v1.0と以前の候補は保持する。

## 置換する契約

Googleの多項式基底`0x1053`上で、36量子ビットの関数を固定する。

\[
|a,b,t\rangle\longmapsto|a,b,t\oplus ab\rangle.
\]

a、b、tは各12ビット。tの初期値は任意であり、ゼロ初期化を仮定しない。
旧回路と新回路の両方について、36個の独立入力変数を持つ厳密Boolean ANFで
出力・入力の復元・残留位相ゼロを確認する。基底状態上の置換と位相が一致するため、
重ね合わせや外部とエンタングルした入力にも同じ局所写像が作用する。
これはPythonの有限代数検査であり、Leanカーネルによる証明ではない。

| 局所命令 | 旧Kickmix | 新候補 |
|---|---:|---:|
| Toffoli / CCX | 63 | 42 |
| CNOT / CX | 481 | 482 |
| SWAP | 21 | 0 |
| 量子ビット | 36 | 36 |
| 古典ビット・測定 | 0 | 0 |

42項の双線形テンソルはandigu/uncomputeの公開定数であり、独自の発見とは主張しない。
出典、固定コミット、Apache-2.0ライセンス、Google基底への変換と局所証明は
[研究記録](../research/eea_boolean/README.md)に保存する。
実際に埋め込むKMxのSHA-256は
`32b9341a5d2096efb2cf6deb69eb44c9828e19699ad2278a10afe93222105557`。

## 実回路の対応

`c_gf_mul`に直に含まれる`gf_mul`だけを対象とする。
forward EEAとreverse EEAにそれぞれ16,204箇所、合計32,408箇所ある。
各旧区間の全命令を固定Kickmix生成器のテンプレートと照合し、36本の単射な配線対応を要求する。
命令の欠落・位相ゲートへの変更・配線の重複・古典条件の追加は拒否する。

| 役割 | 最初のforward | 最初のreverse |
|---|---|---|
| aの下位から上位ビット | q1809…q1820 | q1809…q1803、q1826…q1822 |
| bの下位から上位ビット | q828…q839 | q840…q851 |
| tの下位から上位ビット | q1871…q1860（降順） | q1832…q1843 |
| 旧命令区間（0始まり、右端を含まない） | [53913, 54490) | [67555511, 67556088) |

配線番号の昇順を仮定せず、各位置から実対応を取得する。
全位置の対応を生成物の`site-map.json`とそのSHA-256に保存する。
上の命令位置はこの基準SHAに対応し、置換後の位置ではない。

外側の制御付きXOR、入口リセット、積の測定清掃、古典マスクと条件は変更しない。
量子・古典オペランドの未編集区間、名前付きレジスタ、保持するINFO_TAGをバイト比較する。
古典ターゲットpacket 8と古典条件packet 9は全体が同一であることも確認する。
ローカル契約に古典状態・測定がないため、測定記録の寿命を変更しない。

## 段階別検証

生成器は`multiply42_dqi.py`。まず1箇所版の完全KMBを作り、既存Actionsの
candidate→smoke→full-packageを順に通す。要求した段階すべてが通過した場合に限り
全32,408箇所へ広げ、同じ段階を再実行する。公式依存ファイルがない段階はNOT_RUNとし、
全箇所への拡大を行わない。

新しい候補のfullはそれぞれ102,400試行、seed=20261025、log2_delta=-128で測定する。
比較元だけは[前回の成功記録](../checkpoints/eea-quotient-full-package-20261026.json)を再利用する。
記録そのもののSHA、実際の比較回路のSHA・サイズ・ヘッダー、公開検証器のSHA、
ショット数・seed・信頼度を照合し、誤り上界と`R(epsilon) * Q^2 * mean(T)`を再計算する。
結果には`REUSED_VERIFIED_REPORT`と元のActions URLを記載する。
新しい候補の検証を省略する機能ではない。

提出ZIPはv1.0の`dqi.kmb`だけを置換する。13ファイルの構成、残り12ファイルの
バイト一致、格納されたDQIと測定したDQIのSHA一致を確認する。
Kaggleへの提出コマンドは実行しない。

## 再現

固定Qualtranコミット`638777fac4379bc62e2a1e4a52cf1a1753895d48`のKickmixと
NumPyを用いる。前段の基準回路は既存生成器で再生成できる。

```bash
python quantum/multiply42_dqi.py --reference /path/to/verified-eea-dqi.kmb --sites 1 --output build/one-site
python quantum/multiply42_dqi.py --output build/one-site --parse
python quantum/run_wfs_gates.py --stage full-package --baseline /path/to/v1.0/submission.zip --candidate build/one-site/dqi.kmb --comparison /path/to/verified-eea-dqi.kmb --comparison-checkpoint checkpoints/eea-quotient-full-package-20261026.json --data-root /path/to/official-data --out build/one-site-gates
```

1箇所版の要求した段階がすべてPASSの後に`--sites all`を用いる。
`--comparison-checkpoint`を省略すれば、比較元も新しく全試行を実行する。

## 測定結果

[Actions 40218581338](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/40218581338)で24件のテスト、1箇所版と全32,408箇所版の
candidate→smoke→full-packageが成功した。新候補は各102,400試行で値・位相の誤り0。
Q=1,893、古典ビット49,155、名前付きレジスタ4,165を維持した。
全箇所版は静的Toffoli 3,804,126、平均Toffoli 3804024.1573828124、
公開検証器コスト16238698669232.152。追加削減15.175694%、v1.0比で累積33.555446%。

候補DQI: `252b41714f6147723e44082e4a4f75d84b34b5aa4b23e8c47ce096667caa75e9`。
13ファイルの提出用ZIP: `455b70b1988146358b1045fbc38a2c0df464d060e21d67923350ffe198599fa3`。
残り12ファイルはv1.0とバイト一致。Kaggle公式採点は未実施。
[検証・全ファイル照合記録](../checkpoints/multiply42-full-package-20261026.json)に全段階を保存した。
