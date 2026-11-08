#!/usr/bin/env python3
"""収集スクリプト: sources/ の有効なソースから新着候補を取得し work/candidates.jsonl に書く。

- 既知URL(data/articles, data/rejected.jsonl)は除外(dedupe)
- ソース単位で失敗を隔離し、work/collect_report.json に結果を残す
- 採用可否の判断(triage)と要約・タグ付けは Claude 側(pipeline/prompts/)で行う

使い方:
    python pipeline/collect.py [--since 2026-01-01] [--limit 50] [--only SOURCE_ID ...]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import normalize_url  # noqa: E402

UA = "applied-ds-research-db/0.1 (+https://github.com/nigimitama/applied-ds-research-db)"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
DC = "{http://purl.org/dc/elements/1.1/}"
SUMMARY_MAX = 1200


# ---------- 取得 ----------
def fetch(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ---------- パーサ(純粋関数: テスト可能) ----------
def _text(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def _parse_date(s: str) -> str | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError):
        return None


def parse_feed(data: bytes) -> list[dict]:
    """RSS 2.0 / Atom 1.0 を共通形式に変換。arXiv/J-STAGE(Atom)も同じ関数で扱える。"""
    root = ET.fromstring(data)
    items = []
    for e in root.iter("item"):  # RSS
        items.append(
            {
                "url": _text(e.find("link")),
                "title": _text(e.find("title")),
                "published": _parse_date(_text(e.find("pubDate")) or _text(e.find(f"{DC}date"))),
                "summary": _strip_html(_text(e.find("description")) or _text(e.find(f"{CONTENT}encoded"))),
                "authors": [_text(a) for a in e.findall(f"{DC}creator")],
            }
        )
    for e in root.iter(f"{ATOM}entry"):  # Atom
        link = None
        for l in e.findall(f"{ATOM}link"):
            if l.get("rel", "alternate") == "alternate":
                link = l.get("href")
                break
        link = link or _text(e.find(f"{ATOM}id"))
        authors = []
        for a in e.findall(f"{ATOM}author"):
            name = _text(a.find(f"{ATOM}name"))
            aff = _text(a.find(f"{ARXIV}affiliation"))
            authors.append(f"{name} ({aff})" if aff else name)
        items.append(
            {
                "url": link,
                "title": _text(e.find(f"{ATOM}title")),
                "published": _parse_date(_text(e.find(f"{ATOM}published")) or _text(e.find(f"{ATOM}updated"))),
                "summary": _strip_html(_text(e.find(f"{ATOM}summary")) or _text(e.find(f"{ATOM}content"))),
                "authors": authors,
            }
        )
    return [i for i in items if i["url"] and i["title"]]


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = None
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._buf = []

    def handle_data(self, data):
        if self._href is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, re.sub(r"\s+", " ", "".join(self._buf)).strip()))
            self._href = None


def parse_html_links(html: str, base_url: str, pattern: str) -> list[dict]:
    p = _LinkParser()
    p.feed(html)
    rx = re.compile(pattern)
    out, seen = [], set()
    for href, text in p.links:
        url = urllib.parse.urljoin(base_url, href)
        if rx.search(url) and text and url not in seen:
            seen.add(url)
            out.append({"url": url, "title": text, "published": None, "summary": "", "authors": []})
    return out


# ---------- ソース別の取得URL ----------
def build_request_url(src: dict, since: date) -> str:
    m = src.get("method")
    n = src.get("max_items", 50)
    if m == "arxiv_api":
        q = urllib.parse.urlencode(
            {"search_query": src["query"], "sortBy": "submittedDate", "sortOrder": "descending", "max_results": n}
        )
        return f"https://export.arxiv.org/api/query?{q}"
    if m == "jstage_api":
        q = urllib.parse.urlencode(
            {"service": 3, "keyword": src["query"], "pubyearfrom": since.year, "count": n, "lang": src["lang"]}
        )
        return f"https://api.jstage.jst.go.jp/searchapi/do?{q}"
    return src.get("feed") or src["url"]


def collect_source(src: dict, since: date, fetcher=fetch) -> list[dict]:
    m = src.get("method", "rss")
    raw = fetcher(build_request_url(src, since))
    if m == "html_list":
        items = parse_html_links(raw.decode("utf-8", "replace"), src["url"], src["link_pattern"])
    else:
        items = parse_feed(raw)
    out = []
    for it in items[: src.get("max_items", 50)]:
        if it["published"] and date.fromisoformat(it["published"]) < since:
            continue
        out.append(
            {
                **it,
                "summary": it["summary"][:SUMMARY_MAX],
                "source_id": src["id"],
                "source_type": src["type"],
                "venue": src.get("venue", ""),
                "company_hint": src.get("company"),
                "lang": src["lang"],
                "filter_hint": src.get("filter_hint", ""),
            }
        )
    return out


# ---------- 既知URL ----------
def known_urls(root: Path) -> set[str]:
    urls: set[str] = set()
    for p in (root / "data" / "articles").rglob("*.yml"):
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for u in [d.get("url"), *d.get("alt_urls", [])]:
            if u:
                urls.add(normalize_url(u))
    rej = root / "data" / "rejected.jsonl"
    if rej.exists():
        for line in rej.read_text(encoding="utf-8").splitlines():
            if line.strip():
                urls.add(normalize_url(json.loads(line)["url"]))
    return urls


def load_sources(root: Path, only: list[str] | None) -> list[dict]:
    srcs = []
    for p in sorted((root / "sources").rglob("*.yml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        if only:
            if d["id"] in only:
                srcs.append(d)
        elif d.get("enabled", True):
            srcs.append(d)
    return srcs


def run(root: Path, since: date, limit: int, only=None, fetcher=fetch, delay: float = 1.0) -> dict:
    known = known_urls(root)
    candidates, report = [], {"run_at": datetime.now(timezone.utc).isoformat(), "sources": []}
    for src in load_sources(root, only):
        entry = {"id": src["id"], "status": "ok", "fetched": 0, "new": 0}
        try:
            items = collect_source(src, since, fetcher)
            entry["fetched"] = len(items)
            for it in items:
                n = normalize_url(it["url"])
                if n in known:
                    continue
                known.add(n)  # 同一実行内の重複も除外
                candidates.append(it)
                entry["new"] += 1
        except Exception as e:  # ソース単位で隔離
            entry.update(status="error", error=f"{type(e).__name__}: {e}")
        report["sources"].append(entry)
        if fetcher is fetch:
            time.sleep(delay)
    # 公開日の新しい順に上限まで。残りは次回に繰り越される(既知にならないため再取得される)
    candidates.sort(key=lambda c: c["published"] or "", reverse=True)
    report["total_new"] = len(candidates)
    report["truncated"] = max(0, len(candidates) - limit)
    candidates = candidates[:limit]
    work = root / "work"
    work.mkdir(exist_ok=True)
    (work / "candidates.jsonl").write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in candidates), encoding="utf-8"
    )
    (work / "collect_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--since", type=date.fromisoformat, default=date.today() - timedelta(days=14))
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    rep = run(args.root, args.since, args.limit, args.only)
    for s in rep["sources"]:
        print(f"{s['id']}: {s['status']} fetched={s['fetched']} new={s['new']} {s.get('error','')}")
    print(f"候補 {rep['total_new']} 件(うち繰越 {rep['truncated']} 件) -> work/candidates.jsonl")
    return 0 if all(s["status"] == "ok" for s in rep["sources"]) else 2


if __name__ == "__main__":
    sys.exit(main())
