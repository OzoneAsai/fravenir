# 検索関連性修正の本番適用記録（2026-10-16 JST）

ユーザーから「本番に適用してください」と承認を受けて実施した。

## 適用内容

- 本番: `C:\ProgramData\Fravenir\app`
- ブランチ: `feature/graph-board-foundation`
- 適用前: `9177de915656a6fee3fcdb8117cb6b17ee428dc0`
- 適用した検索コミット: `fbb2bc0dd006e10704ab0221afd7fa05c89a8863`
- Gitのfast-forward限定で適用。既存の未コミット変更とは重複しないことを確認した。
- DBスキーマ移行、再埋め込み、本番venvへの依存追加、データ復元は行っていない。
- 掲示板・メモリー・グラフ・アクセス履歴を削除・初期化していない。

## 保全と統合検証

バックアップ:
`C:\ProgramData\Fravenir\backups\search-relevance-deploy-20261016-004426`

既存のtracked差分・ステージ済み差分・未追跡deploy/テスト・設定を保全。
稼働中のオンラインバックアップと、停止中の最新バックアップの両方をSQLite backup APIで作成。
4DBすべてのintegrity_checkはok。既存13ファイルは本番適用後もバイト単位のSHA256一致。
統合worktreeのGitによる改行正規化は、改行以外の内容が本番と完全一致することを確認した。

統合用worktree:
`C:\ProgramData\Fravenir\test-envs\search-deploy-20261016-004426`

検索コミットと既存の未コミット掲示板変更を組み合わせて検証した。

- pytest: **546 passed, 25 deselected / 384.84秒**。
- Ruff: `check src tests scripts` 通過。
- mypy: 47ソースファイル、問題なし。
- 実DB読み取り専用スナップショットで10問回帰が通過。
- 評価中のPythonソース・テスト・評価スクリプトはSHA256不変。
- 評価スナップショットのDB SHA256不変。

## 切り替え

FravenirMCPを一度だけ停止・起動した。
旧世代のサービス配下プロセスを記録し、全旧待受の終了を確認してから適用。
既存監督サービスの子プロセスが残る場合の確認・終了手順も準備したが、今回は追加終了は不要だった。
監督サービスやOAuth/Caddyの設定・バイナリは変更していない。

- 00:55:31: 旧サービス停止。
- 停止中: 最新4DBを`quiescent-data/main`へバックアップ。
- 00:55:37: 新サービス起動。
- 00:56:13までに: 8280/8001/8281/8282の新世代待受とbridge health 200を確認。
- 監督サービスPID: 3516 -> 10376。新MCPバックエンドPID: 8548。

## 認証済み本番MCPによる検証

接続済みFravenir MCPの認証経路を使い、10問を実モデルで検索した。
単なるhealth、未認証401、ローカル関数呼び出しだけを完了根拠とはしていない。

| 指標 | 本番結果 |
|---|---:|
| Hit@1（grade>=2、主題以上） | 1.000 |
| Hit@5 | 1.000 |
| MRR@5 | 1.000 |
| nDCG@5 | .9270 |
| 意図への直接回答Hit@1（grade=3） | .900 |

新しいscore_components、文脈補助の上限.02、スコア分解を全結果で検査。
Edge0再検索でも105,108,99,113,104を返し、型・方向・relation IDを持つ実グラフ経路5件を確認。
Episode105の原典Post1018/1023 revision1を確認した。
Post1018 revision1の原文は停止中バックアップと完全一致した。

本番検索・原典参照の前後で、アクセス履歴全行と活性化カウンターのSHA256が一致。
履歴は**4,533件のまま**。稼働中の既存利用で準備時4,491件から増えていた42件も保持した。
明示的memory_exploreの書き込み契約は隔離環境の既存テストで検証し、
本番にテスト目的の参照履歴を追加していない。

終了時データ件数:
Episode174、Entity1、関係361、Post1058、Thread108、Space10、episode_sources206。
ベクトルは174件・768次元の既存データを使用。

## ロールバック

今回はロールバック不要だった。
不具合時は本番の検索コミット`fbb2bc0`のみを`git revert`し、既存FravenirMCPサービスを
再起動する。既存の未コミット変更を保持し、DBは通常戻さない。
停止時は監督サービス配下の世代と待受を確認する。
本番の新規投稿・アクセスを失うため、古い検証DBを本番へ上書きしてはいけない。

詳細手順: [検索関連性の運用](search-relevance.md)。
既知の限界（Nicoboxの開始理由が2位、未見質問・大規模化など）は
[実装時の検証記録](search-relevance-results-20261015.md)を参照。

## 実行ログ

隔離検索worktreeの`reports/`にdeployment-state.json、integration-verification.json、
deployment-result.json、live-mcp-summary.json、live-before.json、live-after.jsonを保存。
統合worktreeの`reports/`にpytest/Ruff/mypyと品質評価の結果を保存した。
本番の既存差分と私的なDB内容・原典本文は、この記録コミットへ含めていない。
