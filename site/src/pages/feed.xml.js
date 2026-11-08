import { loadArticles, loadCompanies } from "../lib/data.mjs";

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export function GET({ site }) {
  const base = import.meta.env.BASE_URL.replace(/\/$/, "");
  const origin = (site?.origin ?? "") + base;
  const companies = loadCompanies();
  const items = loadArticles().slice(0, 50);
  const updated = items[0]?.collected ?? new Date().toISOString().slice(0, 10);
  const entries = items
    .map((a) => {
      const names = a.companies.map((c) => companies[c]?.name_ja ?? companies[c]?.name ?? c).join("、");
      return `<entry>
  <id>${esc(origin)}/articles/${esc(a.id)}/</id>
  <title>${esc(`[${names}] ${a.title_ja ?? a.title}`)}</title>
  <link href="${esc(origin)}/articles/${esc(a.id)}/"/>
  <updated>${esc(a.collected)}T00:00:00Z</updated>
  <summary>${esc(a.summary_ja)}</summary>
</entry>`;
    })
    .join("\n");
  const xml = `<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>${esc(origin)}/</id>
  <title>Applied DS Research DB 新着</title>
  <link href="${esc(origin)}/"/>
  <updated>${esc(updated)}T00:00:00Z</updated>
${entries}
</feed>`;
  return new Response(xml, { headers: { "Content-Type": "application/atom+xml; charset=utf-8" } });
}
