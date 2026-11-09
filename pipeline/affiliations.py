#!/usr/bin/env python3
"""arXiv・J-STAGE(人工知能学会全国大会) 候補に著者所属を補完し、企業所属のない論文を除外する。

arXiv API は所属を返さない。Semantic Scholar / OpenAlex は新着論文を数週間インデックスしない
(2026-11 時点の実測で新着は 404 / null)ため、arXiv 自身の HTML 版(arxiv.org/html/<id>)の
著者ブロックを読む。

- 所属を取得できた候補: `authors` と `summary` に所属を付与。企業シグナルがなければ
  data/rejected.jsonl に `no-company-author` で記録して候補から除く(再取得防止)
- 取得できない候補(HTML版なし・失敗): そのまま残す(triage 側で判断。誤って落とさない)

使い方: python pipeline/affiliations.py [--delay 1.0]   (collect.py の後に実行)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import yaml
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect import UA  # noqa: E402

# 企業と確定できる語・名称。
CORP_RX = re.compile(
    r"\b(Inc\.?|Corp\.?|Corporation|Ltd\.?|LLC|GmbH|S\.A\.|Co\.|Company|Labs|Technologies|Holdings)\b|株式会社|有限会社",
    re.I,
)
# 大学・公的機関と確定できる語。企業の取りこぼしを避けるため、「全所属がこれに該当」したときだけ除外する
# (実測: 企業語の有無で判定すると Wildberries / eBay を落とした)。
ACADEMIC_RX = re.compile(
    r"Universit|Université|Universidad|Università|Univ\.|Institut|College|School|Department|Dept\.|Faculty|Academy|"
    r"Hochschule|Polytechnic|Laborator|Max Planck|CNRS|INRIA|CSIRO|RIKEN|KAIST|POSTECH|\bMIT\b|\bETH\b|\bEPFL\b|"
    r"National |Ministry|Hospital|Observatory|Centre for|Center for|大学|研究所|研究科",
    re.I,
)


class _AuthorBlock(HTMLParser):
    """class に ltx_authors を持つ要素の中のテキストを集める(ネスト深さで終端を判定)。"""

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if self.depth:
            if tag not in ("br", "img", "meta", "link", "input", "hr"):
                self.depth += 1
        elif "ltx_authors" in (dict(attrs).get("class") or "").split():
            self.depth = 1

    def handle_endtag(self, tag):
        if self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)


def parse_author_block(html: str) -> str:
    p = _AuthorBlock()
    p.feed(html)
    text = re.sub(r"\s+", " ", " ".join(p.parts)).strip()
    text = re.sub(r"[\w.+-]+@[\w.-]+", "", text)  # メールアドレスは持ち込まない
    return re.sub(r"\s+", " ", text).strip()


def load_company_terms(root: Path) -> list[str]:
    terms: list[str] = []
    for p in sorted((root / "companies").glob("*.yml")):
        for c in yaml.safe_load(p.read_text(encoding="utf-8")) or []:
            terms += [c.get("name"), c.get("name_ja"), *c.get("aliases", [])]
    return [t for t in terms if t and len(t) >= 3]


def split_affiliations(text: str) -> list[str]:
    """"Affiliation: X Email: ..." 形式の各所属文字列を取り出す。"""
    parts = re.findall(r"Affiliation:\s*(.*?)(?=\s+Email|\s+E-mail|\s*Affiliation:|\s+[A-Z][\w.'-]+ [A-Z][\w.'-]+ (?:†|\d)|$)", text)
    return [p.strip(" ,;") for p in parts if p.strip(" ,;")]


def has_company_signal(text: str, terms: list[str]) -> bool:
    """企業所属の可能性があるか。確実に大学・公的機関のみと言えるときだけ False。"""
    affs = split_affiliations(text)
    if not affs:
        return True  # 所属を読み取れない → 残して triage に任せる
    for a in affs:
        if CORP_RX.search(a):
            return True
        low = a.lower()
        if any(re.search(r"(?<![a-z])" + re.escape(t.lower()) + r"(?![a-z])", low) for t in terms):
            return True
        if not ACADEMIC_RX.search(a):
            return True  # 大学らしさがない所属は企業の可能性あり
    return False


# J-STAGE(日本語所属)用。「研究所」は企業研究所を含むので大学語に入れない(企業の取りこぼし防止)。
ACADEMIC_JA_RX = re.compile(
    r"大学|学院|高等専門学校|高専|学校法人|国立研究開発法人|理化学研究所|産業技術総合研究所|情報通信研究機構|"
    r"防衛装備庁|病院|Universit|Institute of Technology|National ",
    re.I,
)


class _MetaParser(HTMLParser):
    """<meta name=citation_author_institution ...> などを集める。"""

    def __init__(self):
        super().__init__()
        self.meta: dict[str, list[str]] = {}

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            a = dict(attrs)
            if a.get("name") and a.get("content") is not None:
                self.meta.setdefault(a["name"], []).append(a["content"])


def parse_jstage_meta(html: str) -> dict:
    """J-STAGE 論文ページから所属・キーワード・抄録を取り出す。所属は重複を除いて順序維持。"""
    p = _MetaParser()
    p.feed(html)
    affs = list(dict.fromkeys(a.strip() for a in p.meta.get("citation_author_institution", []) if a.strip()))
    return {
        "affiliations": affs,
        "keywords": p.meta.get("citation_keywords", []),
        "abstract": (p.meta.get("abstract") or [""])[0].strip(),
    }


def has_company_signal_list(affs: list[str], terms: list[str]) -> bool:
    """所属文字列のリスト版。全所属が大学・公的機関と確定できるときだけ False。"""
    if not affs:
        return True  # 読み取れない → 残す
    for a in affs:
        if CORP_RX.search(a):
            return True
        low = a.lower()
        if any(re.search(r"(?<![a-z])" + re.escape(t.lower()) + r"(?![a-z])", low) for t in terms):
            return True
        if not ACADEMIC_JA_RX.search(a):
            return True
    return False


def jstage_article_url(url: str) -> str:
    return re.sub(r"/_article/-char/\w+/?$", "/_article", url)


def fetch_page(url: str, timeout: int = 30) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def arxiv_id(url: str) -> str | None:
    m = re.search(r"arxiv\.org/abs/([\w.\-/]+?)(?:v\d+)?$", url)
    return m.group(1) if m else None


def fetch_html(aid: str, timeout: int = 30) -> str | None:
    req = urllib.request.Request(f"https://arxiv.org/html/{aid}", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        return None


def run(root: Path, fetcher=fetch_html, delay: float = 1.0, today: date | None = None, jstage_fetcher=None, workers: int = 4) -> dict:
    cand_path = root / "work" / "candidates.jsonl"
    cands = [json.loads(l) for l in cand_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    terms = load_company_terms(root)
    kept, dropped, stats = [], [], {"checked": 0, "unavailable": 0, "dropped": 0, "with_signal": 0}
    jfetch = jstage_fetcher or fetch_page
    jcands = [c for c in cands if c.get("source_id") == "jsai-jstage"]
    jhtml: dict[str, str | None] = {}
    if jcands:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            def _get(c):
                h = jfetch(jstage_article_url(c["url"]))
                if jfetch is fetch_page:
                    time.sleep(delay)
                return c["url"], h
            jhtml = dict(ex.map(_get, jcands))
    for c in cands:
        if c.get("source_id") == "jsai-jstage":
            stats["checked"] += 1
            meta = parse_jstage_meta(jhtml.get(c["url"]) or "")
            if not meta["affiliations"]:
                stats["unavailable"] += 1
                kept.append(c)
                continue
            if not has_company_signal_list(meta["affiliations"], terms):
                stats["dropped"] += 1
                dropped.append(c)
                continue
            stats["with_signal"] += 1
            aff = " / ".join(meta["affiliations"])[:400]
            kw = ", ".join(meta["keywords"])[:200]
            c["summary"] = f"[所属] {aff}\n[KW] {kw}\n{meta['abstract']}"[:1800]
            kept.append(c)
            continue
        aid = arxiv_id(c["url"]) if c.get("source_id") == "arxiv-industry" else None
        if not aid:
            kept.append(c)
            continue
        stats["checked"] += 1
        html = fetcher(aid)
        if fetcher is fetch_html:
            time.sleep(delay)
        block = parse_author_block(html) if html else ""
        if not block:
            stats["unavailable"] += 1
            kept.append(c)
            continue
        if not has_company_signal(block, terms):
            stats["dropped"] += 1
            dropped.append(c)
            continue
        stats["with_signal"] += 1
        c["authors"] = [block[:600]]
        c["summary"] = f"[所属] {block[:600]}\n{c['summary']}"[:1800]
        kept.append(c)
    cand_path.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in kept), encoding="utf-8")
    if dropped:
        d = (today or date.today()).isoformat()
        with (root / "data" / "rejected.jsonl").open("a", encoding="utf-8") as f:
            for c in dropped:
                f.write(
                    json.dumps(
                        {"url": c["url"], "reason": "no-company-author: " + ("J-STAGE論文ページ" if c.get("source_id") == "jsai-jstage" else "arXiv HTML版") + "の著者所属に企業が見当たらない(自動判定)", "date": d},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--workers", type=int, default=4, help="J-STAGE の並列数")
    args = ap.parse_args()
    s = run(args.root, delay=args.delay, workers=args.workers)
    print(f"所属確認 {s['checked']} 件: 企業所属あり {s['with_signal']} / 除外 {s['dropped']} / 所属取得不可(残す) {s['unavailable']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
