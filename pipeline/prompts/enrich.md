# 記事ファイルの作り方 (enrich)

採用した候補1件につき `data/articles/<公開年>/<id>.yml` を1つ作る。スキーマは `schemas/article.schema.json`。

## フィールドの埋め方

| フィールド | 方法 |
|---|---|
| `id` | `<公開年>-<企業id>-<題名の英語slug(3〜5語)>`。小文字英数とハイフンのみ。ファイル名と一致させる |
| `url` | 元記事の正規URL。arXivは `https://arxiv.org/abs/<id>`(バージョンなし) |
| `alt_urls` | 同一内容の別URL(arXiv版と学会版など)があれば |
| `title` / `title_ja` | 原題。英語記事は `title_ja` に日本語訳を付ける |
| `published` | 公開日(YYYY-MM-DD)。`collected` は実行日 |
| `companies` | `companies/*.yml` のid。著者所属を `aliases` で名寄せする。**未登録の企業は、必要なら `companies/` に追記してよい**(name/aliases/country を調べて正確に) |
| `collab_academia` | 大学・公的研究機関の著者がいれば true |
| `source` | `type` と `venue`。ソース定義(sources/)に合わせる |
| `evidence` | 学会/ジャーナル=`peer_reviewed`、企業の自社論文=`industry_paper`、プレプリント=`preprint`、ブログ=`blog`。validateで種別との整合を検査する |
| `lang` | 原文の言語 |
| `summary_ja` | **自分の言葉で2〜3文**(20〜600字)。何を・どう解いたか。原文の文をそのまま写さない |
| `problem` | 解決したい課題を1文(300字以内) |
| `result` | 報告された成果。**数値は原文に書かれているものだけ**。なければ省略 |
| `has_online_experiment` | 本番でのA/Bテスト等の記述が確認できれば true、明確になければ省略(falseは「ない」と確認できたときだけ) |
| `confidence` | 採用判断とタグ付けへの確信度。本文を確認できなかった・曖昧なら 0.7 未満に |

## タグ付けルール

- `tags` は `taxonomy/{tasks,domains,methods,data_types}.yml` の **id のみ**。`ja` `en` `aliases` を見て最も近いものを選ぶ。
- 件数: task 1〜3 / domain 0〜3 / method 0〜4 / data_type 0〜3。主題でないものは付けない(多すぎるより少なめ)。
- 合うタグがないとき: 最も近い既存タグを使い、さらに `taxonomy/proposals.yml` に提案を追記する(同じ提案が既にあれば追記しない):
  `{axis: method, id: new-tag, ja: ..., en: ..., reason: ..., example_url: ...}`
  提案タグは記事には使わない(validateが落ちる)。人が承認して語彙に入れた後で付与する。

## 例(形式の見本。内容は架空)

```yaml
id: 2026-examplecorp-realtime-pricing-bandit
url: https://example.com/blog/realtime-pricing
title: Realtime pricing with contextual bandits
title_ja: コンテキスト付きバンディットによるリアルタイム価格設定
published: 2026-03-02
collected: 2026-03-09
companies: [mercari]
source: {type: techblog, venue: Example Engineering Blog}
evidence: blog
lang: en
summary_ja: 出品価格の提案にコンテキスト付きバンディットを導入し、探索と活用のバランスを自動調整した。オフライン評価の後にA/Bテストで検証している。
problem: 価格提案の固定ルールでは需要変化に追随できない
result: 成約率が数%改善したと報告(具体値は原文参照)
tags: {task: [pricing], domain: [e-commerce], method: [bandit, off-policy-evaluation], data_type: [log]}
has_online_experiment: true
confidence: 0.85
```
