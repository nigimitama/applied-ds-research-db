# Applied DS Research DB 設計書

企業のデータサイエンス/計算機科学の応用事例(学会論文・テックブログ・自社の未査読論文など)を自動収集し、
タグ付けして、企業・タスク・分野・手法で検索できるWebサイトにする。

## 1. 設計方針

| 方針 | 理由 |
|---|---|
| **Git = データベース**(1記事 = 1ファイル) | サーバー/DB不要。収集結果が差分レビューでき、履歴も残る。Claudeの定期タスクと相性が良い |
| **静的サイト + クライアント検索** | 運用費ゼロ(GitHub Pages等)。数千〜数万件規模ならブラウザ内検索で十分 |
| **決定的な処理はスクリプト、判断はClaude** | 取得・重複排除・ビルドはコード。関連性判定・要約・タグ付けだけLLM。再現性とコストを両立 |
| **タグは統制語彙** | LLMの自由記述だと表記ゆれで検索が壊れる。許可リストから選ばせ、新語は「提案」として別管理 |
| **更新はPR経由** | 誤収集・誤タグを人間が最終確認できる。確信度が高いものだけ自動マージも可 |

## 2. 全体アーキテクチャ

```
 ┌────────────── Claude 定期タスク (週1回) ──────────────┐
 │                                                          │
 │ ① collect   sources/*.yml を読み、各ソースから新着候補を取得    │
 │      (スクリプト: RSS / arXiv API / 学会プログラムページ)       │
 │ ② dedupe    URL正規化・DOI・タイトル類似で既存と重複排除        │
 │ ③ triage    Claudeが「企業の応用事例か」を判定(不採用は理由付き記録)│
 │ ④ enrich    Claudeが要約・タグ・企業名寄せ・エビデンス区分を付与   │
 │ ⑤ validate  スキーマ/語彙チェック(スクリプト)              │
 │ ⑥ PR作成    data/articles/*.yml を追加 → レビュー → merge      │
 └──────────────────────────────────────────────────────────┘
                         │ merge
                         ▼
   CI: build (Astro) → Pagefind索引生成 → GitHub Pages デプロイ
```

## 3. リポジトリ構成

```
applied-ds-research-db/
├── DESIGN.md
├── sources/                 # 収集元レジストリ(1ソース=1ファイル)
│   ├── conferences/kdd-ads.yml
│   ├── conferences/jsai.yml
│   └── blogs/mercari.yml ...
├── companies/               # 企業マスタ(別名・業種・ブログURL)
│   └── mercari.yml
├── taxonomy/                # 統制語彙(別名つき)
│   ├── tasks.yml  domains.yml  methods.yml  data_types.yml
│   └── proposals.yml        # Claudeが提案した新タグ(要承認)
├── data/
│   ├── articles/2026/xxxx.yml   # 記事 1件=1ファイル
│   └── rejected.jsonl           # 不採用URL+理由(再取得防止)
├── pipeline/                # 収集・検証スクリプト(Python)
│   ├── collect.py dedupe.py validate.py
│   └── prompts/triage.md enrich.md   # Claudeへの指示書
├── site/                    # Astro サイト
└── .github/workflows/       # validate(PR時) / deploy(main)
```

## 4. データモデル(記事)

```yaml
id: 2026-kdd-ads-xxxx            # 年-ソース-slug
url: https://...                 # 正規化済み・一意キー
title: "..."
title_ja: "..."                  # 英語記事のみ
published: 2026-08-10
collected: 2026-11-08
companies: [google, mercari]     # companies/ のID。共同研究は複数
source:
  type: conference | techblog | preprint | company_paper | journal
  venue: "KDD 2026 ADS Track"   # ブログなら媒体名
evidence: peer_reviewed | industry_paper | preprint | blog   # 信頼度の区分
lang: en | ja
summary_ja: "2〜3文の独自要約"       # 原文の転載はしない
problem: "解決したい課題(背景・既存手法の限界を含む、1000字以内)"
approach: "方法: 使った技術とその解き方(1000字以内)"
result: "報告されている成果(あれば。数値は原文のまま)"
tags:
  task: [recommendation, demand-forecasting]
  domain: [e-commerce, logistics]
  method: [two-tower, bandit]
  data_type: [tabular, text]
has_online_experiment: true      # A/Bテスト等の本番検証の有無
confidence: 0.86                 # 収集時のClaude確信度(低いものはPRで要確認)
```

ポイント:
- **evidence区分**でフィルタできるようにする(「査読済みだけ」「ブログ含む」)。
- **has_online_experiment / result** は応用事例DBとしての価値が高い(実運用での効果)。
- `summary_ja` は自前の要約のみ。全文や図の転載は著作権上避ける(リンク+メタデータ+短い要約)。

## 5. タグ体系(統制語彙)

| 軸 | 例 |
|---|---|
| **task** | 推薦 / 需要予測 / 広告配信最適化 / 不正検知 / 検索ランキング / 価格最適化 / 異常検知 / 要約 / 対話 |
| **domain** | EC / 金融 / 製造 / 物流 / 広告 / 医療 / 通信 / 人材 / ゲーム / 小売 |
| **method** | 因果推論 / バンディット / 強化学習 / GNN / LLM / 時系列 / 最適化 / A/Bテスト基盤 |
| **data_type** | 表形式 / テキスト / 画像 / 時系列 / グラフ / ログ |

運用ルール:
- `taxonomy/*.yml` に `id / 表示名(ja,en) / aliases` を持たせ、Claudeはここからのみ選択。
- 合致がない場合は `proposals.yml` に追加提案 → 人間が承認して語彙化。承認後に過去記事を再タグ付け。
- 1記事あたり task 1〜3、method 0〜4 程度に制限してノイズを抑える。

## 6. 収集ソース

| 種別 | ソース例 | 取得方法 |
|---|---|---|
| 国際会議 | KDD ADS Track, RecSys (industry), WWW, CIKM, SIGIR industry, WSDM, ICML/NeurIPS(一部) | プログラムページ/DBLP/OpenReview/ACM DL |
| 国内学会 | JSAI(人工知能学会全国大会・J-STAGE), DEIM, NLP年次大会, IBIS, 情報処理学会 | J-STAGE API, 各大会サイト |
| プレプリント | arXiv(企業所属の著者を検出) | arXiv API + 所属フィルタ |
| テックブログ | Google/Meta/Netflix/Uber/Airbnb、Mercari/LINEヤフー/CyberAgent/DeNA/リクルート/サイバーエージェント等 | RSS/Atom優先、なければサイトマップ |
| 自社発表の論文 | 企業研究所のpublicationsページ(NTT, 富士通, PFN, Sony AI等) | ページ巡回 |

`sources/*.yml` の例:
```yaml
id: mercari-engineering
type: techblog
company: mercari
feed: https://engineering.mercari.com/blog/feed.xml
filter_hint: "機械学習/データ分析に関する記事のみ。採用/イベント告知は除外"
lang: ja
schedule: weekly
```
ソースを足すのはYAML1ファイルの追加だけ、にする。取得失敗が続くソースは `health` を記録して警告。

## 7. Claudeの役割分担

| 工程 | 担当 | 備考 |
|---|---|---|
| 新着取得・重複排除・検証・ビルド | **スクリプト** | 決定的。LLM不要 |
| triage(採用可否) | **Claude** | 「企業が実データ/実サービスに適用した事例か」。理論のみ・採用告知は不採用。理由を `rejected.jsonl` に |
| enrich(要約・タグ・企業名寄せ) | **Claude** | 統制語彙内で選択、confidenceを自己申告 |
| 新タグ提案・週次サマリ | **Claude** | PR本文に「今週の件数/不採用理由/提案タグ」を出す |
| 最終承認 | **人間** | PRレビュー(初期は全件、安定後は confidence≥0.85 を自動マージ) |

定期タスクの注意点:
- クラウド実行ではネットワークがホワイトリスト制。収集対象ホストを環境に許可する必要あり(ソース追加時に更新)。
- 1回の実行量に上限(例: 新着候補50件)を設けコストと実行時間を制御。残りは翌週に繰越。
- 失敗しても部分的にPRを出せるよう、ソース単位で try/except し結果をPR本文に列挙。

## 8. Webサイト

- **技術**: Astro + Pagefind(全文検索のクライアント側索引)。GitHub Pagesでホスティング。
- **ページ**
  - トップ: 新着、企業/タスク別の件数
  - 検索: キーワード + ファセット(企業・task・domain・method・年・ソース種別・evidence)をURLクエリで共有可能に
  - 企業ページ `/company/mercari`: その企業の事例一覧・得意領域のタグ分布
  - タグページ `/task/recommendation`: 企業横断で事例を比較
  - 記事詳細: 要約・課題・成果・タグ・元リンク
  - RSS/Atom: 新着フィード(自分用の購読にも使える)
- 将来: 企業×タスクのヒートマップ、年別トレンド。

## 9. 品質・法務

- **重複**: URL正規化 + DOI + タイトル類似度。arXivと学会版は同一記事として `alt_urls` に統合。
- **企業判定**: 著者所属から判定。大学との共同研究は `companies` + `collab: academia` フラグ。
- **著作権**: 本文転載なし。要約は自分の言葉で短く。出典リンクを必ず表示。
- **robots/利用規約**: 各ソースのrobots.txtを尊重、取得間隔を空ける。RSS/API優先。
- **誤情報対策**: 数値(`result`)は原文からの抜粋と明示。confidence低はPRでフラグ。

## 10. ロードマップ

1. **Phase 0 (土台)**: スキーマ、語彙の初版、企業マスタ、validateスクリプト
2. **Phase 1 (手動+半自動)**: ソース5〜10件(KDD ADS, JSAI, 日本の主要テックブログ数社, arXiv)で収集→PR運用を回して精度を確認。過去3年分をバックフィル
3. **Phase 2 (サイト公開)**: Astro + Pagefind、ファセット検索、企業/タグページ、デプロイCI
4. **Phase 3 (拡張)**: ソース拡充、承認済みタグの再タグ付け、自動マージ、トレンド可視化
5. **Phase 4 (任意)**: 類似記事推薦(埋め込み)、週次ダイジェスト配信

## 11. 決定事項

| 項目 | 決定 |
|---|---|
| 公開範囲 | 一般公開(GitHub Pages)。本文転載なし、要約+リンクのみ |
| 対象範囲 | 実運用の適用事例に限定(理論のみ・採用告知は不採用) |
| Phase 1 のソース | 国際会議(KDD ADS / RecSys等)、国内学会(JSAI / DEIM等)、国内企業テックブログ、海外BigTechブログ+企業所属arXiv |
| マージ運用 | 当面は全件PRレビュー。精度が安定したら confidence 高のものを自動マージ |
| 言語 | 日本語のみ(英語記事にも日本語要約を付与)。*暫定* |
| バックフィル | 過去3年分。*暫定* |

## 12. 次のアクション

1. Phase 0: `schema`(記事・企業・ソース)、`taxonomy` 初版、`validate.py`
2. Phase 1: ソース定義と `collect.py`、Claude用プロンプト(`triage.md` / `enrich.md`)、定期タスク登録
3. Phase 2: Astro + Pagefind サイトとデプロイCI
