# Windows source publication — 2026-10-19

## 収録範囲

稼働中の Fravenir `47450e38842dffee9ce245fa250cdc9493a9ef16` と、作業ツリーに残っていた掲示板の変更を隔離したコピーに収録した。検索関連性の改善、episode 間のグラフ探索、グラフ UI、Activity、掲示板の編集・アーカイブ・ゴミ箱操作を含む。既存の未コミット変更は本番で保存したまま、配布用コピーで記録する。

Planet OAuth は [`planet-oauth/`](planet-oauth/README.md) に、Fravenir の Windows サービス・認証ブリッジ・認証ゲートは [`windows/`](windows/README.md) に収録した。OAuth の `app.py`、`bootstrap.py`、運用スクリプト、実行時 `requirements.txt` は稼働環境の原本をコピーしている。設定例、依存関係ファイル、テスト、説明を配布用に追加した。

既存の GitHub 公開コミット `9177de915656a6fee3fcdb8117cb6b17ee428dc0` を親とする、`feature/windows-source-20261019` のソーススナップショットとして配布する。ローカル専用の Git 履歴は送信せず、既存の GitHub の `main` と `feature/graph-board-foundation` は進めない。本番の HEAD、作業ツリー、Git リモート設定も変更しない。

## 配布前の確認

- ソースと文書を対象に許可リストでコピー。DB・ベクトル・メモリー本文・掲示板データ・アクセス履歴・環境ファイル・署名鍵・TOTP 登録情報・QR・ログ・バックアップ・実行ファイル・venv は含めない。
- 一般的なトークン・秘密鍵パターンに加え、OAuth サーバーと MCP ブリッジの実設定に含まれる秘密値との完全一致を検査した。値をログに出力せず、該当なしを確認した。
- 本番の追跡済みファイルおよび OAuth の原本と配布用コピーを比較した。本番には書き込んでいない。
- Git の改行正規化に従い、Windows の C# と認証ゲートの末尾余剰空行だけを除去した。
- `.gitignore` に OAuth の環境ファイル、登録情報、SQLite、ログ、バックアップ、鍵などの除外を追加した。
- Fravenir と OAuth のテストはそれぞれ独立した依存関係で実行する。Fravenir の通常の pytest 探索を `tests/` に限定し、OAuth 用の独立した CI ジョブを追加した。

## 検証結果

Windows / Python 3.12 の隔離環境で実行した。

| 確認 | 結果 |
|---|---|
| Fravenir `pytest tests -q --timeout=90` | 557 passed, 10 skipped, 25 deselected / 562.17秒 |
| 検索スナップショットの10クエリを明示指定して再実行 | 10 passed / 55.06秒。DBハッシュの不変性も各テストで確認 |
| Planet OAuth の独立venv + `requirements-test.txt` | 4 passed / 7.54秒 |
| Node `tests/ui/activity.test.cjs` / `graph-model.test.cjs` | 6 passed |
| Ruff `src tests scripts` と新規 OAuth テスト | 成功 |
| mypy `src` | 50ソースファイルで問題なし |
| Python ソースの構文確認、PowerShell の静的構文解析、`git diff --cached --check` | 成功 |
| 配布対象の機密情報検査、コピー元の変化検出 | 該当なし |

通常実行の skip 10件は、実データのパスを自動で選択しない検索回帰テスト。その10件も既存の隔離 DB とクエリ埋め込みキャッシュを明示して成功した。25件の deselect は既存設定の `slow` / `golden_llm` であり、今回実行していない。時間制限にはローカル検証環境の pytest-timeout を使用した。

OAuth の検証には FastAPI 0.117.1、Uvicorn 0.36.0、python-dotenv 1.1.1、PyJWT 2.14.0 を新規の隔離 venv にインストールした。FastAPI `on_event` と Starlette / AnyIO の非推奨警告が9件出たが、テストの失敗はない。この配布では稼働コードのライフサイクル処理を変更していない。

GitHub Actions 自体の実行結果は、このローカル検証結果には含めていない。

## 運用上の制限

この作業はソースの配布のみ。サービスの停止・再起動、DB の変更、デプロイは行っていない。Windows のスクリプトは環境固有の固定パスやサービス名を含むため、別環境でそのまま実行するものではない。

検索評価文書は既存の隔離スナップショットでの結果であり、実 DB や記憶本文は配布していない。実データを使う回帰テストには、別途読み取り用スナップショットとクエリ埋め込みキャッシュが必要になる。
