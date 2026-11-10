"""collect.py のテスト。ネットワークは使わず、手書きのフィードで検証する。"""
import re
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
import collect  # noqa: E402

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Post A</title><link>https://blog.example.com/a?utm_source=x</link>
<pubDate>Mon, 05 Jan 2026 09:00:00 +0000</pubDate><description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description></item>
<item><title>Old post</title><link>https://blog.example.com/old</link>
<pubDate>Mon, 05 Jan 2020 09:00:00 +0000</pubDate></item>
<item><title>Known post</title><link>https://blog.example.com/known/</link>
<pubDate>Tue, 06 Jan 2026 09:00:00 +0000</pubDate></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
<entry><id>http://arxiv.org/abs/2601.00001v1</id><title>Paper  X</title>
<published>2026-01-08T10:00:00Z</published><summary>Abstract text</summary>
<author><name>Alice</name><arxiv:affiliation>ExampleCorp</arxiv:affiliation></author><author><name>Bob</name></author>
<link rel="alternate" href="http://arxiv.org/abs/2601.00001v1"/></entry></feed>"""

HTML = '<a href="/papers/1">Paper One</a><a href="/about">About</a><a href="https://x.org/papers/2">Paper Two</a>'


def test_parse_rss():
    items = collect.parse_feed(RSS)
    assert items[0]["title"] == "Post A"
    assert items[0]["published"] == "2026-01-05"
    assert items[0]["summary"] == "Hello world"


def test_parse_atom_with_affiliation():
    (it,) = collect.parse_feed(ATOM)
    assert it["title"] == "Paper X"
    assert it["authors"] == ["Alice (ExampleCorp)", "Bob"]
    assert it["published"] == "2026-01-08"


def test_parse_html_links():
    items = collect.parse_html_links(HTML, "https://conf.example.org/", r"/papers/")
    assert [i["url"] for i in items] == ["https://conf.example.org/papers/1", "https://x.org/papers/2"]


@pytest.fixture
def root(tmp_path):
    for d in ("schemas", "taxonomy", "companies"):
        shutil.copytree(REPO / d, tmp_path / d)
    (tmp_path / "sources").mkdir()
    (tmp_path / "data" / "articles" / "2026").mkdir(parents=True)
    (tmp_path / "data" / "rejected.jsonl").write_text(
        json.dumps({"url": "https://blog.example.com/known", "reason": "x", "date": "2026-01-01"}) + "\n"
    )
    for sid, feed in [("good", "https://blog.example.com/feed"), ("bad", "https://bad.example.com/feed")]:
        (tmp_path / "sources" / f"{sid}.yml").write_text(
            yaml.safe_dump({"id": sid, "type": "techblog", "company": "mercari", "feed": feed,
                            "method": "rss", "lang": "en", "schedule": "weekly", "enabled": True})
        )
    (tmp_path / "sources" / "off.yml").write_text(
        yaml.safe_dump({"id": "off", "type": "techblog", "feed": "https://off.example.com/f",
                        "lang": "en", "schedule": "weekly", "enabled": False})
    )
    return tmp_path


def fake_fetcher(url, timeout=30):
    if "bad.example.com" in url:
        raise OSError("boom")
    return RSS


def test_run_dedupe_since_and_isolation(root):
    rep = collect.run(root, date(2025, 1, 1), 50, fetcher=fake_fetcher)
    status = {s["id"]: s["status"] for s in rep["sources"]}
    assert status == {"good": "ok", "bad": "error"}  # off は対象外、bad の失敗は隔離される
    rows = [json.loads(l) for l in (root / "work" / "candidates.jsonl").read_text().splitlines()]
    assert [r["title"] for r in rows] == ["Post A"]  # Old=since除外 / Known=rejected済み
    assert rows[0]["company_hint"] == "mercari"


def test_limit_and_carry_over(root):
    rep = collect.run(root, date(2019, 1, 1), 1, fetcher=fake_fetcher)
    assert rep["total_new"] == 2 and rep["truncated"] == 1


def test_build_request_url():
    u = collect.build_request_url({"method": "arxiv_api", "query": "all:foo", "id": "a", "lang": "en"}, date(2026, 1, 1))
    assert u.startswith("https://export.arxiv.org/api/query?") and "all%3Afoo" in u


DOI_HTML = """<table><tbody>
<tr><td><strong>Paper One</strong><br/>DOI: https://doi.org/10.1145/1</td></tr>
<tr><td>Alice (ExampleCorp); Bob (Univ X)</td></tr>
<tr><td><strong>Paper Two</strong><br/>DOI: https://doi.org/10.1145/2</td></tr>
<tr><td>Carol (Corp Y)</td></tr>
<tr><td><strong>No DOI yet</strong></td></tr>
</tbody></table>"""


def test_parse_doi_table():
    items = collect.parse_doi_table(DOI_HTML)
    assert [i["url"] for i in items] == ["https://doi.org/10.1145/1", "https://doi.org/10.1145/2"]
    assert items[0]["title"] == "Paper One"
    assert items[0]["summary"] == "Alice (ExampleCorp); Bob (Univ X)"


JSTAGE = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>T</title>
<author><en><name>Taro YAMADA</name></en><ja><name>\xe5\xb1\xb1\xe7\x94\xb0 \xe5\xa4\xaa\xe9\x83\x8e</name><name>\xe4\xbd\x90\xe8\x97\xa4 \xe8\x8a\xb1\xe5\xad\x90</name></ja></author>
<link href="https://www.jstage.jst.go.jp/article/x"/><updated>2026-01-01T09:00+09:00</updated></entry></feed>"""


def test_parse_jstage_authors():
    (it,) = collect.parse_feed(JSTAGE)
    assert it["authors"] == ["山田 太郎", "佐藤 花子"]


def test_check_jstage_error():
    with pytest.raises(RuntimeError):
        collect.check_jstage(b"<result><status>ERR_001</status></result>")
    collect.check_jstage(b"<result><status>WARN_002</status></result>")


def test_jstage_url_uses_text_and_cdjournal():
    url = collect.build_request_url(
        {"method": "jstage_api", "cdjournal": "pjsai", "lang": "ja"}, date(2025, 1, 1)
    )
    assert "cdjournal=pjsai" in url and "keyword" not in url


def test_collect_jstage_pages_and_normalizes_url():
    def page(n, start):
        entries = "".join(
            f'<entry><title>T{start+i}</title><link href="https://www.jstage.jst.go.jp/article/p/{start+i}/_article/-char/ja/"/>'
            f"<updated>2025-07-01T09:00+09:00</updated></entry>"
            for i in range(n)
        )
        return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'.encode()

    calls = []

    def fetcher(url):
        start = int(re.search(r"start=(\d+)", url).group(1))
        calls.append(start)
        return page(collect.JSTAGE_PAGE if start == 1 else 3, start)

    src = {"id": "j", "type": "conference", "method": "jstage_api", "lang": "ja", "max_items": 10000}
    items = collect.collect_source(src, date(2025, 1, 1), fetcher)
    assert calls == [1, collect.JSTAGE_PAGE + 1]
    assert len(items) == collect.JSTAGE_PAGE + 3
    assert items[0]["url"].endswith("/1/_article")


def test_parse_title_author_table_and_resolve_dois():
    html = (
        "<table><tr><td><strong>Foo Bar Baz<strong></strong></strong></td></tr>"
        "<tr><td>A (Acme Inc.); B (MIT)</td></tr>"
        "<tr><td><strong>Other Paper<strong></strong></strong></td></tr>"
        "<tr><td>C (Univ X)</td></tr></table>"
    )
    items = collect.parse_title_author_table(html, "https://x.example/p/")
    assert [i["title"] for i in items] == ["Foo Bar Baz", "Other Paper"]
    assert items[0]["summary"] == "A (Acme Inc.); B (MIT)"
    assert items[0]["url"] == "https://x.example/p/?paper=foo-bar-baz"

    def fake(url):
        assert "S1" in url and "2024" in url
        return json.dumps({"results": [{"doi": "https://doi.org/10.1145/1", "title": "Foo bar baz"},
                                       {"doi": "https://doi.org/10.1145/2", "title": "Different"}],
                           "meta": {"next_cursor": None}}).encode()

    src = {"openalex_source": "S1", "openalex_year": 2024}
    assert collect.resolve_dois(items, src, fake) == 1
    assert items[0]["url"] == "https://doi.org/10.1145/1"
    assert items[1]["url"].startswith("https://x.example/p/?paper=")


def test_resolve_dois_survives_rate_limit():
    items = [{"title": "T", "url": "u"}]

    def boom(url):
        raise OSError("HTTP Error 429")

    assert collect.resolve_dois(items, {"openalex_source": "S1", "openalex_year": 2024}, boom) == 0
    assert items[0]["url"] == "u"
