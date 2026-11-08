// データ読み込み(ビルド時のみ)。リポジトリ直下の YAML を読む。
// ARTICLES_DIR でプレビュー用に記事ディレクトリを差し替え可能(例: tests/fixtures/articles)。
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { load as yamlLoad } from "js-yaml";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const ARTICLES_DIR = process.env.ARTICLES_DIR
  ? path.resolve(process.env.ARTICLES_DIR)
  : path.join(REPO, "data", "articles");

export const AXES = {
  task: { file: "tasks", label: "タスク" },
  domain: { file: "domains", label: "分野" },
  method: { file: "methods", label: "手法" },
  data_type: { file: "data_types", label: "データ種別" },
};

export const EVIDENCE_LABEL = {
  peer_reviewed: "査読済み",
  industry_paper: "企業論文",
  preprint: "プレプリント",
  blog: "テックブログ",
};
export const SOURCE_LABEL = {
  conference: "学会",
  techblog: "テックブログ",
  preprint: "プレプリント",
  company_paper: "企業論文",
  journal: "論文誌",
};

function readYaml(p) {
  return yamlLoad(fs.readFileSync(p, "utf8"));
}
function walk(dir) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    return e.isDirectory() ? walk(p) : p.endsWith(".yml") ? [p] : [];
  });
}

export function loadTaxonomy() {
  const tax = {};
  for (const [axis, { file }] of Object.entries(AXES)) {
    const items = readYaml(path.join(REPO, "taxonomy", `${file}.yml`)) || [];
    tax[axis] = Object.fromEntries(items.map((i) => [i.id, i]));
  }
  return tax;
}

export function loadCompanies() {
  const out = {};
  for (const p of walk(path.join(REPO, "companies"))) {
    for (const c of readYaml(p) || []) out[c.id] = c;
  }
  return out;
}

export function loadArticles() {
  const iso = (v) => (v instanceof Date ? v.toISOString().slice(0, 10) : String(v));
  return walk(ARTICLES_DIR)
    .map((p) => readYaml(p))
    .map((a) => ({ ...a, published: iso(a.published), collected: iso(a.collected) }))
    .sort((a, b) => (a.published < b.published ? 1 : -1));
}

/** 軸ごと・idごとの件数 {axis: {id: n}} */
export function tagCounts(articles) {
  const c = Object.fromEntries(Object.keys(AXES).map((k) => [k, {}]));
  for (const a of articles)
    for (const [axis, ids] of Object.entries(a.tags || {}))
      for (const id of ids) c[axis][id] = (c[axis][id] || 0) + 1;
  return c;
}

export function companyCounts(articles) {
  const c = {};
  for (const a of articles) for (const id of a.companies) c[id] = (c[id] || 0) + 1;
  return c;
}
