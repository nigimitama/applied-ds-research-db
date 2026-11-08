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
| `pipeline/` | 収集・検証スクリプト |

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
