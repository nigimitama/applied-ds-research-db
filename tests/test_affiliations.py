"""affiliations.py のテスト。ネットワークは使わない。"""
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
import affiliations as af  # noqa: E402

HTML = (
    '<html><body><div class="ltx_authors"><span class="ltx_creator">Ann <span>Affiliation: Foo Labs Inc.</span>'
    '<br/>mail: ann@foo.com</span></div><div class="ltx_abstract">Abstract text</div></body></html>'
)


def test_parse_author_block_stops_at_block_end_and_drops_email():
    t = af.parse_author_block(HTML)
    assert "Foo Labs Inc." in t and "Abstract" not in t and "@" not in t


def test_company_signal():
    terms = ["Meta", "Mercari", "メルカリ"]
    assert af.has_company_signal("Ann Affiliation: Foo Labs Inc.", terms)
    assert af.has_company_signal("Ann Affiliation: Meta Bob Affiliation: University of Tokyo", terms)
    assert af.has_company_signal("Ann Affiliation: eBay Email: a@b.com", terms)  # 大学語なし → 残す
    assert af.has_company_signal("Ann Affiliation: Wildberries and Russ , Russia", terms)
    assert af.has_company_signal("Ann Bob", terms)  # 所属が読めない → 残す
    assert not af.has_company_signal(
        "Ann Affiliation: University of Oxford Email: x Bob Affiliation: KAIST Email: y", terms
    )
    assert not af.has_company_signal("Ann Affiliation: Department of Physics, Univ X", terms)


def test_arxiv_id():
    assert af.arxiv_id("https://arxiv.org/abs/2611.09728v1") == "2611.09728"
    assert af.arxiv_id("https://example.com/x") is None


def test_run_keeps_unavailable_and_drops_academic(tmp_path):
    (tmp_path / "work").mkdir()
    (tmp_path / "data").mkdir()
    shutil.copytree(REPO / "companies", tmp_path / "companies")
    rows = [
        {"url": "https://arxiv.org/abs/1.1v1", "source_id": "arxiv-industry", "summary": "a", "authors": []},
        {"url": "https://arxiv.org/abs/2.2v1", "source_id": "arxiv-industry", "summary": "b", "authors": []},
        {"url": "https://arxiv.org/abs/3.3v1", "source_id": "arxiv-industry", "summary": "c", "authors": []},
        {"url": "https://blog.example.com/x", "source_id": "mercari-engineering", "summary": "d", "authors": []},
    ]
    (tmp_path / "work" / "candidates.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    pages = {
        "1.1": HTML,
        "2.2": '<div class="ltx_authors">Bob Affiliation: University of Tokyo</div>',
        "3.3": None,
    }
    s = af.run(tmp_path, fetcher=lambda aid: pages[aid], today=__import__("datetime").date(2026, 1, 1))
    assert s == {"checked": 3, "unavailable": 1, "dropped": 1, "with_signal": 1}
    out = [json.loads(l) for l in (tmp_path / "work" / "candidates.jsonl").read_text().splitlines()]
    assert [o["url"] for o in out] == ["https://arxiv.org/abs/1.1v1", "https://arxiv.org/abs/3.3v1", "https://blog.example.com/x"]
    assert out[0]["summary"].startswith("[所属] ")
    rej = (tmp_path / "data" / "rejected.jsonl").read_text()
    assert "2.2v1" in rej and "no-company-author" in rej


JHTML = (
    '<meta name="citation_author_institution" content="株式会社Foo">'
    '<meta name="citation_author_institution" content="東京大学">'
    '<meta name="citation_author_institution" content="東京大学">'
    '<meta name="citation_keywords" content="推薦"><meta name="abstract" content="要旨です">'
)


def test_parse_jstage_meta_dedups_affiliations():
    m = af.parse_jstage_meta(JHTML)
    assert m["affiliations"] == ["株式会社Foo", "東京大学"]
    assert m["keywords"] == ["推薦"] and m["abstract"] == "要旨です"


def test_company_signal_list_ja():
    terms = ["メルカリ"]
    assert af.has_company_signal_list(["東京大学", "株式会社Foo"], terms)
    assert af.has_company_signal_list(["ソニーCSL研究所"], terms)  # 「研究所」だけでは落とさない
    assert af.has_company_signal_list(["メルカリ R4D"], terms)
    assert af.has_company_signal_list([], terms)
    assert not af.has_company_signal_list(["東京大学", "産業技術総合研究所"], terms)


def test_run_jstage_filters(tmp_path):
    (tmp_path / "work").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "companies").mkdir()
    rows = [
        {"url": f"https://www.jstage.jst.go.jp/article/pjsai/{k}/_article/-char/ja/", "title": k, "summary": "", "source_id": "jsai-jstage"}
        for k in ("corp", "univ")
    ]
    (tmp_path / "work" / "candidates.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def fake(url):
        assert url.endswith("/_article")
        return JHTML if "corp" in url else '<meta name="citation_author_institution" content="京都大学">'

    s = af.run(tmp_path, jstage_fetcher=fake, workers=1)
    assert s["dropped"] == 1 and s["with_signal"] == 1
    kept = [json.loads(l) for l in (tmp_path / "work" / "candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [k["title"] for k in kept] == ["corp"] and "[所属]" in kept[0]["summary"]
    assert "J-STAGE" in (tmp_path / "data" / "rejected.jsonl").read_text(encoding="utf-8")
