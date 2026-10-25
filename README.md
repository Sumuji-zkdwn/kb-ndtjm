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

## DQI staged validation (no Kaggle submissions)

[Run DQI staged validation](../../actions/workflows/dqi-gated.yml)

| Stage | Kaggle daily quota? | Action |
|---|---|---|
| baseline | 0 | Validate v1.0 SHA, ZIP CRC, 13 files, DQI registers (70 S and 4095 E groups) |
| candidate | 0 | Generate the pinned one-site WFS COMPLETE dqi.kmb (or use candidate_release), then check its register contract |
| smoke | 0 | Use published standalone DQI verifier with a batch-aligned budget satisfying its unchanged confidence requirement (currently 1,536 shots) |
| full-package | 0 | Smoke, full default-shot verifier, compare against baseline with local salt, then package complete candidate ZIP |

Integration pushes run candidate → smoke → full-package in order. If official verifier assets cannot be downloaded, smoke/full-package are recorded as NOT_RUN. Manual stage selection remains available. The workflow has NO Kaggle submission command.

The original local WFS .kmx is not a complete submission. The new quantum/wfs_dqi_single_site.py wraps its r=1 specialization and replaces one pinned baseline phase block in a COMPLETE dqi.kmb. See [the exact mapping, proof and limits](quantum/WFS_DQI_INTEGRATION.md). This is an unscored integration checkpoint, with more two-qubit operations and no cost-improvement claim.

For smoke/full-package, download the official competition data with a Kaggle token. Create a repository secret named KAGGLE_API_TOKEN in Settings > Secrets and variables > Actions. Never put credentials in source code or logs. Your account must accept competition rules first. GitHub-hosted Linux might not exactly match the official Kaggle container; the official packaged Kickmix binary should be checked for compatibility.

The official leaderboard uses secret salts, while this workflow uses a fixed local salt. Therefore offline PASS is strong evidence but not a guarantee of passing Kaggle scoring. Generated ZIPs are saved as Actions artifacts for explicit user review; a final Kaggle submission must be performed separately by the user.

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

既存の局所核3種は次の通りです。別途、Google基底核1種の完全DQIへの1箇所組み込みを実装しました。

- Google基底 0x1053: 12 CCZ, 288 conditional CX, 132 CX, 合計432命令
- 公開基底 0x10eb: 12 CCZ, 288 conditional CX, 220 CX, 合計520命令
- 固定非零スケール 0x52: 12 CCZ, 288 conditional CX, 210 CX, 12 SWAP, 合計522命令

**実装済み:** 実DQIの1箇所の位相置換、測定マスク結線、全入力ANF一致、範囲外バイナリ保存、完全KMB生成。
**公式未確認:** 全DQI公式verifier、正答率・Q/T・Kaggle採点。提出は自動実行しません。
局所ANF一致やKickmix構文解析を「全体の公式検証合格」とみなさないこと。

Actionsの dqi-wfs-one-site-unscored に完全候補、dqi-checkpoint-full-package に各段階の結果を保存します。
緑のworkflowでも stages.json の all_requested_gates_passed=false、smoke/full-package=NOT_RUN なら公式検証合格ではありません。

