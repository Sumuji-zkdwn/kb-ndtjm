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
| candidate | 0 | Generate the complete inverse66 DQI after one-site checks (or use candidate_release), then check its register contract |
| smoke | 0 | Use published standalone DQI verifier with a batch-aligned budget satisfying its unchanged confidence requirement (currently 1,536 shots) |
| full-package | 0 | Smoke, full default-shot verifier, compare against baseline with local salt, then package complete candidate ZIP |

Integration pushes run candidate → smoke → full-package in order. If official verifier assets cannot be downloaded, smoke/full-package are recorded as NOT_RUN. Manual stage selection remains available. The workflow has NO Kaggle submission command.

現在の候補は [inverse66統合](research/inverse66/INTEGRATION_JA.md) です。`quantum/inverse66_dqi.py` が元の完全DQIのForney逆元計算と後始末を置換します。1箇所版と4,095箇所版を生成し、どちらもローカルのcandidate・smoke検査を通過しました。Q=1,893を維持し、全箇所版の静的Toffoli数は5,725,461 → 4,705,806です。[Actionsのcandidate → smoke → full-packageが成功しました](../../actions/runs/40200104339)。公開公式verifierのfull検証は候補・基準とも102,400ショット、値・位相の誤り0。実測コストは24,439,472,802,075.414 → 20,087,809,297,947.793（17.805881%低減）です。Kaggle公式採点は未実施です。

以前の局所WFS位相核1箇所置換は [別の検証記録](quantum/WFS_DQI_INTEGRATION.md) として保持しています。その候補はfull検証の正当性検査を通過しましたが、コスト低減はありませんでした。局所.kmx単体は完全提出物ではありません。

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

**実装済み:** WFS位相核の1箇所置換と、inverse66の1箇所・4,095箇所組み込み。レジスタ・測定マスク対応、局所の厳密ANF証明、範囲外バイナリ保存、完全KMB生成、公開公式verifierのsmoke検証。
**確認済み:** inverse66全体版の公開公式verifierによるfull検証・実測コスト低減、13ファイルの候補ZIP生成と残り12ファイルの同一性。
**未確認:** Kaggle公式採点。提出は自動実行しません。
局所ANF一致やKickmix構文解析を「全体の公式検証合格」とみなさないこと。

Actionsの dqi-inverse66-unscored に完全候補、dqi-checkpoint-full-package に各段階の結果を保存します。
緑のworkflowでも stages.json の all_requested_gates_passed=false、smoke/full-package=NOT_RUN なら公式検証合格ではありません。


最終の[統合・full検証・ZIP照合記録](checkpoints/inverse66-full-package-20261025.json)に、検証対象コミット、回路・ZIPのSHA-256、全段階の結果と各ファイルのハッシュを保存しています。
