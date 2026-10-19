# 関連性優先の memory_search

## 検索モデル

`memory_search` は入力引数と既存の返却キーを維持する。追加の
`score_components`、`graph_paths`、`episode_sources` で順位と出典を検査できる。
スコアの数値自体は旧式と互換ではなく、旧スコアの閾値は流用しない。

1. 有効期間・抑制・kindの既存条件を適用する。`min_importance` は従来どおり
   抑制された記憶を明示的に含める場合に適用する。
2. ベクトルKNNと語彙BM25からそれぞれ `max(20, limit*4)` 件を取る。
   KNNは除外候補で枠が埋まれば探索窓を広げる（sqlite-vec上限4096件）。
3. 語彙検索はNFKC・casefoldした英数字識別子と、日本語の連続文字列の重なり2文字を
   使用する。空白による分かち書きや固有名詞別の特例には依存しない。
   BM25はk1=1.2、b=.75、クエリIDF総和で正規化する。
   今回は読み取り専用の一時索引とし、FTS5用の永続スキーマを追加しない。
4. 初期候補の関連性上位8件からepisode間を最大2ホップ探索する。
   1ノードあたり12近傍、追加候補64件まで。抑制・除外ノードを経由しない。
   エッジ本数を加算せず、最強の経路を一つ保持するのでハブや循環は増幅しない。
5. 追加候補は自身の保存ベクトルでcosineを再計算する。ベクトル欠損をseedの類似度で
   埋めない。グラフだけで追加された候補は、関連性が最良seedの半分未満なら除外する。
6. 関連性と、上限を持つ文脈補助を合成して並べ、IDで同点を安定化する。

```text
relevance = (1 - lexical_weight) * cosine + lexical_weight * normalized_BM25
score = relevance + context
0 <= context <= context_budget
```

既定値は `lexical_weight=.35`、`context_budget=.02`。
ACT-R・重要度・グラフ・自己キューはこの合計補助枠を共有する。
したがって関連性に `.02` を超える差があれば、履歴や重要度では逆転できない。
意味検索は既定で65%を占め、識別子の正確な一致を語彙検索が補完する。

ACT-Rの既存計算は保持し、検索で使うときだけ旧検索表示由来の
`direct`、`associative`、`self_boost`、`search_impression` を除く。
除外は履歴件数のLIMITより前に行い、`memory_explore` の明示参照を残す。
古い履歴・カウンターは変更しない。検索自体も以後は履歴・カウンターを書き込まない。
compact/exploreの既存の減衰計算は今回変更していない。

`activation` は互換診断値（ACT-R＋entity連想）であり、順位そのものではない。
`score_components` にcosine、ベクトル有無、語彙、関連性、ACT-R、正規化重要度、
グラフ補助、文脈補助、各候補生成経路を分けて返す。
旧 `act_r.alpha_similarity` は設定として受け付け続けるが、新検索の混合比には
`search.lexical_weight` を使う。`final_score` は旧計算の互換関数として保持する。

## 関係と出典

| predicate | 元方向 | 逆方向 | 解釈 |
|---|---:|---:|---|
| part_of | .8 | .4 | 上位文脈を辿り、詳細への展開は弱める |
| related_to | .6 | .6 | 関連の探索は両方向、元エッジ方向は保持 |
| derived_from | .8 | 0 | 派生物から原典へ辿る |

これらは学習済み確率ではなく探索方針である。各ホップでエッジ強度（0〜1へ制限）を
乗算する。未知のpredicateは自動で無向化しない。episode以外の原典は
`episode_sources` と既存の掲示板・グラフAPIで参照する。
entity/self-hub候補も従来の仕組みから合流するが、最終順位は同じ関連性モデルを使う。

`graph_paths` はrelation ID、src/dst、predicate、元強度、description、valid_from、
supersedesと探索方向を保持する。`episode_sources` は原典IDとrevisionを保持する。
既存DBのエッジを変更したり、出典を新たに推測して書き戻したりしない。

## 同条件での品質評価

私的スナップショットとキャッシュは `reports/` に置きGitへ含めない。
`tests/golden/search_relevance.json` は本文を含まない手動の段階評価で、
3=質問の意図への回答、2=直接の主題、1=背景、未指定=0。
Hit/MRRは2以上、厳密回答Hit@1は3を条件とする。nDCGは段階評価を使う。
評価は開発者による判定であり、独立した利用者による評価や未見質問での性能保証ではない。

```powershell
Set-Location C:\ProgramData\Fravenir\test-envs\search-relevance-20261015
$env:PYTHONPATH = Join-Path (Get-Location) src
$env:PYTHONUTF8 = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$python = '.venv\Scripts\python.exe'
# 初回だけ --build-cache を追加する。CPU、既存の実モデルを使う。
& $python scripts/evaluate_search_relevance.py --data data/main `
  --cache reports/queries.npz --build-cache --baseline 9177de9 --output reports/before.json
& $python scripts/evaluate_search_relevance.py --data data/main `
  --cache reports/queries.npz --output reports/after.json
# 語彙比率0/.2/.5/.7/1、--no-graph も同じキャッシュで比較できる。
$env:FRAVENIR_SEARCH_SNAPSHOT = Join-Path (Get-Location) data/main
$env:FRAVENIR_QUERY_CACHE = Join-Path (Get-Location) reports/queries.npz
& $python -m pytest tests -q
& .venv\Scripts\ruff.exe check src tests scripts
& $python -m mypy src
```

評価時刻は2026-10-15 15:00 UTCで固定する。旧コードは指定Gitコミットから読み込み、
旧検索のアクセス記録のみ無効にする。すべてのDB接続は `mode=ro` に強制し、
実行前後のDB SHA256一致を検査する。新コード自身も読み取り専用接続を使う。
実モデルのquery/topicベクトルは一度だけ作り、質問順・設定・キャッシュSHA256を検査する。
テストで環境変数を指定しなければ私的DBテスト10件はskipし、通常は一時DBだけを使う。

## 承認後の本番適用とロールバック

現時点では本番への適用・停止・再起動は行わない。
DBスキーマ変更・データ移行・再埋め込みは不要。追加依存もない。

1. 適用承認後、本番HEAD・ブランチ・サービス構成・未コミット差分を再確認する。
   `git diff --binary --output=<backup>/production.patch`、ステージ済み差分、
   未追跡の `deploy/` とテスト等を別途コピーして保存する。
   DBはサービス稼働中でもSQLite backup APIで別ファイルへ整合スナップショットを作る。
   WALを含む稼働中DBの単純なファイルコピーに頼らない。
2. 最新本番HEADから別の統合用worktreeを作る。検証済みコミットと本番の未コミット変更を
   そのworktreeへ再現し、掲示板・スキーマ変更との統合テストを一時DBで行う。
   本番の現在の変更は今回の検索ブランチには取り込んでいないため、この確認が必要。
3. 検証済みコミットを確認する。
   `git -C <validation-worktree> rev-parse fix/search-relevance-20261015`。
   競合する本番変更がないことを確認して `git -C <production> cherry-pick <commit>`。
   無関係の変更は残し、reset/cleanやDBディレクトリの置換はしない。
   コンフリクトがあれば停止し、保全した変更を基に統合側で解決する。
4. 承認された保守時間内に既存のFravenirMCP監督サービスで一度だけ再起動する。
   設定・OAuth・Caddy・起動方式は変更しない。起動ログ・healthに加え、認証済みMCPで
   指定クエリと原典参照を確認する。連続検索でaccess_historyが増えないことと、
   明示的memory_exploreでは参照を記録できることを区別して確認する。
5. 不具合時は、適用直後に記録した本番側の検索コミットIDだけを
   `git revert <applied-commit>` し、既存サービスを再起動。
   無関係の未コミット変更は保持する。スキーマ不変なので通常はDBを戻さず、
   適用後に作られた新規メモリーや掲示板投稿も保持する。
   DB復元が必要な別障害なら、その時点のDBも退避して別途承認を得る。

## 残る限界

- 語彙索引は毎回メモリー本文を読むため、大規模DBでは永続索引と更新同期を検討する。
- 形態素解析や別名展開は未導入。短い日本語・表記差・意図判定には改善余地がある。
- グラフだけで無関係な記憶を押し上げず、関連性のない／ベクトル欠損のノードの
  強引な救済はしない。十分な種候補が得られない質問は改善を保証できない。
- KVと各ベクトルDBは別ファイルなので、各接続内のread transactionは整合するが、
  同時書き込みに対する全DB一括の世代保証は従来どおり存在しない。
- 本番の認証済みMCP経由での確認は適用承認後に行う。
