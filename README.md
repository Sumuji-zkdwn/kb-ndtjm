# Quantum / WFS (mobile cloud workflow)

この非公開リポジトリは Google Quantum AI Kaggle Verifiable Quantum Circuit Compilation
に向けた実装用です。

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
| candidate | 0 | Generate the complete Forney inverse66 + quotient120 + 42-Toffoli multiply DQI after one-site checks (or use candidate_release), then check its register contract |
| smoke | 0 | Use published standalone DQI verifier with a batch-aligned budget satisfying its unchanged confidence requirement (currently 1,536 shots) |
| full-package | 0 | Smoke, full default-shot verifier, compare against the prior validated DQI (or v1.0) with local salt, then package complete candidate ZIP |

Integration pushes run candidate → smoke → full-package in order. If official verifier assets cannot be downloaded, smoke/full-package are recorded as NOT_RUN. Manual stage selection remains available. The workflow has NO Kaggle submission command.

現在の候補は、検証済み42-Toffoli乗算統合版を基準に、EEA商加算888箇所を141→120 Toffoliへ更新した完全DQIです。[Actions 40253571134](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/40253571134)で、1箇所版のcandidate → smoke → full-packageをすべて通過してから888箇所へ拡張し、全箇所版も同じ順で成功しました。各候補を新しく102,400ショットで検査し、値・位相の誤りはともに0です。

静的Toffoliは3,804,126 → **3,785,478**（追加18,648削減）。Q=1,893、古典ビット49,155、名前付きレジスタ4,165を維持しました。公開検証器の費用は16,238,698,669,232.152 → **16,159,093,692,960.87**（追加0.490218%減、v1.0比の累積33.881169%減）です。full検証時間は基準版571.56秒（過去の記録を再利用）、1箇所版554.97秒、888箇所版562.39秒。ホストが異なるため厳密な速度比較ではありません。**新候補のKaggle公式スコアは未測定で、提出回数は消費していません。**

[120-Toffoli統合・全体検証・ZIP照合記録](checkpoints/quotient120-full-package-20261026.json)と[配線・制御・清掃の仕様](quantum/QUOTIENT120_DQI_INTEGRATION.md)を参照できます。比較元の42-Toffoli統合版、以前の各候補、Release v1.0と既存提出ZIPを保持しました。

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

**実装済み:** WFS位相核の1箇所置換と、inverse66の1箇所・4,095箇所組み込み、EEA商加算の1箇所・888箇所組み込み、42-Toffoli乗算の1箇所・32,408箇所組み込み、120-Toffoli商加算の1箇所・888箇所組み込み。レジスタ・測定マスク対応、局所の厳密ANF証明、範囲外バイナリ保存、完全KMB生成、公開公式verifierのsmoke検証。
**確認済み:** inverse66・EEA商加算・42-Toffoli乗算・120-Toffoli商加算の各全体版の公開公式verifierによるfull検証・実測コスト低減、13ファイルの候補ZIP生成と残り12ファイルの同一性。
**未確認:** 新しい120-Toffoli商加算候補のKaggle公式採点。提出は自動実行しません。
局所ANF一致やKickmix構文解析を「全体の公式検証合格」とみなさないこと。

Actionsの dqi-quotient120-unscored に完全候補、dqi-checkpoint-full-package に各段階の結果を保存します。
緑のworkflowでも stages.json の all_requested_gates_passed=false、smoke/full-package=NOT_RUN なら公式検証合格ではありません。


前回の[統合・full検証・ZIP照合記録](checkpoints/inverse66-full-package-20261025.json)に、検証対象コミット、回路・ZIPのSHA-256、全段階の結果と各ファイルのハッシュを保存しています。

前回の[EEA商加算記録](checkpoints/eea-quotient-full-package-20261026.json)を保持し、今回の[42-Toffoli乗算・full検証・ZIP照合記録](checkpoints/multiply42-full-package-20261026.json)に新候補のハッシュと全段階の結果を保存しました。[組み込み仕様とレジスタ対応](quantum/MULTIPLY42_DQI_INTEGRATION.md)も参照できます。

Actionsの`dqi-candidate-for-human-review`から取得するZIPは外側の成果物アーカイブです。手動提出に使うのは、その中の`submission-candidate.zip`（13ファイル入り）です。今回のZIPは72,066,634 bytes、SHA-256は`218fc644c3bd2fff54d863b30a1135799ff1091416df74f730beddeb49fe4b10`です。

今回の[候補ZIP成果物](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/40253571134/artifacts/12622805553)には`submission-candidate.zip`が入っています。13ファイルのハッシュをダウンロード後にも再照合しました。
