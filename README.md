# Quantum / WFS (mobile cloud workflow)

この非公開リポジトリは Google Quantum AI Kaggle Verifiable Quantum Circuit Compilation
に向けた実装用です。

## 現在の基準提出

元の submission.zip は **GitHub Release v1.0** に保存済みです。

- [Release v1.0 / submission.zip](../../releases/tag/v1.0)
- ZIPサイズ: 73,818,680 bytes
- SHA-256: 04cf2fc7518e9cc2f9207f61b9421448a0b02368756c6b342fb4cea8c47b0f43
- 収録: dqi.kmb / invsqrt.kmb / dfthcsos/...

以前のZIP分割・復元用の manifest.json と restore.py は互換性のため残していますが、
**ZIP自体はReleaseにアップロード済みなので分割する必要はありません**。

## スマホからWFSを検証

1. [Actions: Quantum WFS phase kernel (phone/cloud)](../../actions/workflows/wfs-local.yml) を開く
2. Run workflow をタップする（GitHub Mobileアプリまたはブラウザー）
3. Build and prove local kernel と Parse KMx with Kickmix の実行結果を見る
4. 成果物 wfs-local-kmx-and-report / wfs-kickmix-parser-report を取得する

手元のスマホでPythonをインストールする必要はありません。
WorkflowはGitHub ActionsクラウドCPU上で動きます。

**Job 1 — Build and prove local kernel:**
- quantum/wfs_mobile_ci.py から3種の可変位相核 .kmx を生成
- GF(2)のANFで位相・量子レジスタ保存・作業ビット清掃をすべての入力について記号検証
- 固定乱数列による軌跡確認
- Release v1.0の元ZIPをダウンロードしSHA-256とファイル構成を検証（元ZIPは変更しない）

**Job 2 — Parse KMx with Kickmix:**
- Google公開の quantumlib/Qualtran/kickmix を固定コミットからインストール
- 3種の局所核を公式KickmixのKMxパーサで読み込み
- Q/b/Toffoli相当数をチェック

## 構成

- quantum/wfs_mobile_ci.py — 位相核のコンパイラ兼独立検証器
- .github/workflows/wfs-local.yml — クラウド自動検証
- Release v1.0 — 元の完全提出ZIP（無改変）
- manifest.json, restore.py — 旧4分割形式からの復元器

## 実装と検証の境界

現状のWFSは **DQI内の局所位相演算候補**です。

- Google基底 0x1053: 12 CCZ, 288 conditional CX, 132 CX, 合計432命令
- 公開基底 0x10eb: 12 CCZ, 288 conditional CX, 220 CX, 合計520命令
- 固定非零スケール 0x52: 12 CCZ, 288 conditional CX, 210 CX, 12 SWAP, 合計522命令

**未実施:** DQI全体のレジスタ対応を取った置換、古典マスクの結線、
全DQI公式verifierの実行、正答率・Q/T・Kaggle採点、提出。
局所ANF一致やKickmix構文解析を「全体の公式検証合格」とみなさないこと。

次の作業はこの局所カーネルを既存DQIの実際の位相演算1箇所に
埋め込み、保存した基準ZIPと動作を比較することです。
