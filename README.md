# Applied DS Research DB

企業のデータサイエンス/計算機科学の応用事例(学会論文・テックブログ・自社論文)を収集・タグ付けして検索できるようにするプロジェクト。
全体設計は [DESIGN.md](DESIGN.md) を参照。

## ディレクトリ

| パス | 内容 |
|---|---|
| `schemas/` | 記事・企業・ソースのJSON Schema |
| `taxonomy/` | タグの統制語彙(task / domain / method / data_type)と新タグ提案キュー |
| `companies/` | 企業マスタ(リスト形式。`aliases` で所属名を名寄せ) |
| `sources/` | 収集元の定義(1ソース=1ファイル、ファイル名=id) |
| `data/articles/` | 記事(1件=1ファイル、ファイル名=id) |
| `data/rejected.jsonl` | 不採用URLと理由(再取得防止) |
| `pipeline/` | 収集(`collect.py`)・検証(`validate.py`)と、Claude向け指示書(`prompts/`) |
| `site/` | Astro + Pagefind の静的サイト |
| `tests/` | テストと、サイト表示確認用のダミー記事(`fixtures/`) |

## 検証

```bash
pip install -r requirements-dev.txt
python pipeline/validate.py   # スキーマ・語彙・参照整合性・URL重複
pytest -q
```

PR時にCI(`.github/workflows/validate.yml`)で同じ検証が走る。

## タグ・企業の追加ルール

- 記事のタグは `taxonomy/*.yml` に存在するidのみ使用可。ない場合は `taxonomy/proposals.yml` に提案する。
- 記事の企業は `companies/*.yml` のidのみ使用可。
- 別名(`aliases`)は軸内で一意。衝突するとvalidateが失敗する。

## 収集(週次)

```bash
python pipeline/collect.py --limit 50          # work/candidates.jsonl を出力(既知URLは除外)
python pipeline/collect.py --only <source_id> --since 2023-01-01   # 単一ソース・期間指定
```

その後の判定・要約・タグ付け・PR作成は Claude が `pipeline/prompts/weekly-run.md` に従って行う
(定期タスクの実行内容。過去分の取り込みは `backfill.md`)。
ソース定義は初期状態で `enabled: false`。実フィードで `--only` 実行して確認してから `true` にする。

### 定期タスクの実行環境で許可が必要なホスト
クラウド実行ではネットワークがホワイトリスト制。有効にしたソースのホストを環境の許可リストに追加する。
`export.arxiv.org`、`api.jstage.jst.go.jp`、各 `sources/**/*.yml` の `feed`/`url` のホスト。

## サイト

```bash
cd site && npm ci
ARTICLES_DIR=../tests/fixtures/articles npm run build   # ダミー記事でビルド(dist/ + 検索インデックス)
npm run dev                                             # 開発サーバー(検索は build 後のみ動作)
```

- 公開: `main` へのマージで `.github/workflows/deploy.yml` が GitHub Pages にデプロイする。
  リポジトリ設定の Pages → Source を **GitHub Actions** にしておくこと。
- ページ: トップ / 検索(Pagefind: 企業・タスク・分野・手法・データ種別・年・種別・信頼度・本番検証で絞り込み) / 企業 / タグ / 統計 / Atomフィード。
