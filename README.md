# Quantum / WFS (mobile cloud workflow)

この非公開リポジトリは Google Quantum AI Kaggle Verifiable Quantum Circuit Compilation
に向けた実装用です。

## 最新のBM候補：盲協力からの全体実装と検証

第8版の[PR #8](https://github.com/Sumuji-zkdwn/kb-ndtjm/pull/8)は、
第7版を起点としたGeminiとの盲協力で得た位相回路を完全DQIへ組み込んだ候補です。
[Actions](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/40447516741)と
未変更の公開公式検証器を通過しました。102,400 shotsで値・位相の誤りはともに0。
Q=2,482を維持し、Toffoli相当数719,881 → 715,786、評価費用は
5,282,883,023,272.201 → 5,252,831,659,254.676（追加0.568844%減）です。

[盲協力の手続きと第7版から第8版の改善報告](docs/dqi-blindcoop-report-20261027.ja.md)、
[比較条件・実装・検証結果](docs/dqi-blindcoop-validation-20261027.md)と
[検証記録JSON](checkpoints/bm-blindcoop-20261027.json)を参照できます。
Actionsの`dqi-bm-candidate-for-human-review`に、全13ファイルを照合済みの
`submission-candidate.zip`を保存しています。2026年10月27日にKaggleへ提出し、
公式公開採点で **Complete、Public Score 1.66950** を確認しました。
第7版の1.66633から0.00317、約0.19024%向上しています。
[公式採点の比較記録](checkpoints/kaggle-pr8-public-score-20261027.json)と
[提出・採点監視のActions](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/40465609028)を参照できます。
以下の通常の`dqi-gated.yml`の説明は、従来のEEA系候補についての記録です。
最新BM候補の再現には`dqi-bm.yml`の`full-package`を使います。

## 現在の基準提出

元の submission.zip は **GitHub Release v1.0** に保存済みです。

- [Release v1.0 / submission.zip](https://github.com/Sumuji-zkdwn/kb-ndtjm/releases/tag/v1.0)
- ZIPサイズ: 73,818,680 bytes
- SHA-256: 04cf2fc7518e9cc2f9207f61b9421448a0b02368756c6b342fb4cea8c47b0f43
- 収録: dqi.kmb / invsqrt.kmb / dfthcsos/...

以前のZIP分割・復元用の manifest.json と restore.py は互換性のため残していますが、
**ZIP自体はReleaseにアップロード済みなので分割する必要はありません**。

## DQI staged validation (no Kaggle submissions)

[Run DQI staged validation](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/workflows/dqi-gated.yml)

| Stage | Kaggle daily quota? | Action |
|---|---|---|
| baseline | 0 | Validate v1.0 SHA, ZIP CRC, 13 files, DQI registers (70 S and 4095 E groups) |
| candidate | 0 | Generate the complete Forney inverse66 + EEA quotient + 42-Toffoli multiply DQI after one-site checks (or use candidate_release), then check its register contract |
| smoke | 0 | Use published standalone DQI verifier with a batch-aligned budget satisfying its unchanged confidence requirement (currently 1,536 shots) |
| full-package | 0 | Smoke, full default-shot verifier, compare against the prior validated DQI (or v1.0) with local salt, then package complete candidate ZIP |

Integration pushes run candidate → smoke → full-package in order. If official verifier assets cannot be downloaded, smoke/full-package are recorded as NOT_RUN. Manual stage selection remains available. The workflow has NO Kaggle submission command.

現在の候補はForney inverse66の4,095箇所、EEA商加算の888箇所、42-Toffoli乗算の32,408箇所を置換した完全DQIです。Q=1,893と名前付きレジスタ4,165を維持し、静的Toffoli数はv1.0の5,725,461 → Forney版4,705,806 → EEA商加算版4,484,694 → 今回3,804,126です。[Actions](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/40218581338)で1箇所版、全箇所版の順にcandidate → smoke → full-packageを通過しました。新候補はそれぞれ102,400試行、値・位相の誤り0。比較元はSHAと検証条件が一致する前回の成功記録を再利用しました。公開検証器のコストは前回19,143,921,722,159.74 → 今回16,238,698,669,232.152（追加15.175694%減、v1.0比で累積33.555446%減）です。ユーザー報告スコア1.06759がForney版のもので、他2課題が同じなら換算目安は1.14604。新候補のKaggle公式スコアは未測定です。

以前の局所WFS位相核1箇所置換は [別の検証記録](quantum/WFS_DQI_INTEGRATION.md) として保持しています。その候補はfull検証の正当性検査を通過しましたが、コスト低減はありませんでした。局所.kmx単体は完全提出物ではありません。

For smoke/full-package, download the official competition data with a Kaggle token. Create a repository secret named KAGGLE_API_TOKEN in Settings > Secrets and variables > Actions. Never put credentials in source code or logs. Your account must accept competition rules first. GitHub-hosted Linux might not exactly match the official Kaggle container; the official packaged Kickmix binary should be checked for compatibility.

The official leaderboard uses secret salts, while this workflow uses a fixed local salt. Therefore offline PASS is strong evidence but not a guarantee of passing Kaggle scoring. Generated ZIPs are saved as Actions artifacts for explicit user review; a final Kaggle submission must be performed separately by the user.

## スマホからWFSを検証

1. [Actions: Quantum WFS phase kernel (phone/cloud)](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/workflows/wfs-local.yml) を開く
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

既存の局所核3種は次の通りです。別途、Google基底核1種の完全DQIへの1箇所組み込みを実装しました。

- Google基底 0x1053: 12 CCZ, 288 conditional CX, 132 CX, 合計432命令
- 公開基底 0x10eb: 12 CCZ, 288 conditional CX, 220 CX, 合計520命令
- 固定非零スケール 0x52: 12 CCZ, 288 conditional CX, 210 CX, 12 SWAP, 合計522命令

**実装済み:** WFS位相核の1箇所置換と、inverse66の1箇所・4,095箇所組み込み、EEA商加算の1箇所・888箇所組み込み、42-Toffoli乗算の1箇所・32,408箇所組み込み。レジスタ・測定マスク対応、局所の厳密ANF証明、範囲外バイナリ保存、完全KMB生成、公開公式verifierのsmoke検証。
**確認済み:** inverse66・EEA商加算・42-Toffoli乗算の各全体版の公開公式verifierによるfull検証・実測コスト低減、13ファイルの候補ZIP生成と残り12ファイルの同一性。
**未確認:** 新しい42-Toffoli乗算候補のKaggle公式採点。提出は自動実行しません。
局所ANF一致やKickmix構文解析を「全体の公式検証合格」とみなさないこと。

Actionsの dqi-multiply42-unscored に完全候補、dqi-checkpoint-full-package に各段階の結果を保存します。
緑のworkflowでも stages.json の all_requested_gates_passed=false、smoke/full-package=NOT_RUN なら公式検証合格ではありません。


前回の[統合・full検証・ZIP照合記録](checkpoints/inverse66-full-package-20261025.json)に、検証対象コミット、回路・ZIPのSHA-256、全段階の結果と各ファイルのハッシュを保存しています。

前回の[EEA商加算記録](checkpoints/eea-quotient-full-package-20261026.json)を保持し、今回の[42-Toffoli乗算・full検証・ZIP照合記録](checkpoints/multiply42-full-package-20261026.json)に新候補のハッシュと全段階の結果を保存しました。[組み込み仕様とレジスタ対応](quantum/MULTIPLY42_DQI_INTEGRATION.md)も参照できます。

Actionsの`dqi-candidate-for-human-review`から取得するZIPは外側の成果物アーカイブです。手動提出に使うのは、その中の`submission-candidate.zip`（13ファイル入り）です。今回の配布用の別名`submission-multiply42.zip`も同一バイトのZIPです。
