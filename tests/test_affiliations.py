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
