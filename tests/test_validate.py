"""validate.py のテスト。tmpに最小ルートを組み立てて検証する(実データには依存しない)。"""
import copy
import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
import validate  # noqa: E402

# テスト用のダミー記事(実在の論文ではない)
VALID = {
    "id": "test-article-1",
    "url": "https://example.com/blog/post-1",
    "title": "Dummy article for tests",
    "published": "2026-01-10",
    "collected": "2026-01-17",
    "companies": ["mercari"],
    "source": {"type": "techblog", "venue": "Example Engineering Blog"},
    "evidence": "blog",
    "lang": "ja",
    "summary_ja": "これはテスト用のダミー要約です。実在の記事ではありません。",
    "tags": {"task": ["recommendation"], "domain": ["e-commerce"], "method": ["embedding"], "data_type": ["log"]},
    "confidence": 0.9,
}


@pytest.fixture
def root(tmp_path):
    for d in ("schemas", "taxonomy", "companies"):
        shutil.copytree(REPO / d, tmp_path / d)
    (tmp_path / "data" / "articles").mkdir(parents=True)
    (tmp_path / "sources").mkdir()
    return tmp_path


def put(root, article, name=None):
    name = name or article.get("id", "x")
    p = root / "data" / "articles" / "2026" / f"{name}.yml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(article, allow_unicode=True), encoding="utf-8")


def errs(root):
    return validate.run(root)[0]


def test_repo_itself_is_valid():
    assert validate.run(REPO)[0] == []


def test_valid_article(root):
    put(root, VALID)
    e, n = validate.run(root)
    assert e == [] and n == 1


def test_unknown_tag(root):
    a = copy.deepcopy(VALID)
    a["tags"]["task"] = ["no-such-tag"]
    put(root, a)
    assert any("未登録のタグ" in e for e in errs(root))


def test_unknown_company(root):
    a = copy.deepcopy(VALID)
    a["companies"] = ["nonexistent"]
    put(root, a)
    assert any("未登録の企業" in e for e in errs(root))


def test_missing_required(root):
    a = copy.deepcopy(VALID)
    del a["summary_ja"]
    put(root, a)
    assert any("summary_ja" in e for e in errs(root))


def test_too_many_task_tags(root):
    a = copy.deepcopy(VALID)
    a["tags"]["task"] = ["recommendation", "pricing", "pricing2", "fraud-detection"]
    put(root, a)
    assert errs(root)


def test_filename_must_match_id(root):
    put(root, VALID, name="other-name")
    assert any("不一致" in e for e in errs(root))


def test_duplicate_url_after_normalization(root):
    b = copy.deepcopy(VALID)
    b["id"] = "test-article-2"
    b["url"] = "https://www.example.com/blog/post-1/?utm_source=x#frag"
    put(root, VALID)
    put(root, b)
    assert any("重複" in e for e in errs(root))


def test_evidence_consistency(root):
    a = copy.deepcopy(VALID)
    a["evidence"] = "peer_reviewed"  # techblog なのに peer_reviewed
    put(root, a)
    assert any("evidence" in e for e in errs(root))


def test_future_published(root):
    a = copy.deepcopy(VALID)
    a["published"] = "2026-02-01"
    put(root, a)
    assert any("未来" in e for e in errs(root))


def test_additional_property_rejected(root):
    a = copy.deepcopy(VALID)
    a["foo"] = 1
    put(root, a)
    assert errs(root)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("http://WWW.Example.com/a/?utm_medium=x&b=2&a=1#top", "https://example.com/a?a=1&b=2"),
        ("https://arxiv.org/abs/2401.01234v3", "https://arxiv.org/abs/2401.01234"),
        ("https://arxiv.org/pdf/2401.01234v2.pdf", "https://arxiv.org/pdf/2401.01234"),
    ],
)
def test_normalize_url(raw, expected):
    assert validate.normalize_url(raw) == expected


def test_taxonomy_duplicate_alias_detected(root):
    p = root / "taxonomy" / "tasks.yml"
    items = yaml.safe_load(p.read_text(encoding="utf-8"))
    items.append({"id": "dup-task", "ja": "重複", "en": "Dup", "aliases": ["レコメンド"]})
    p.write_text(yaml.safe_dump(items, allow_unicode=True), encoding="utf-8")
    assert any("衝突" in e for e in errs(root))


def test_fixture_articles_are_valid(root):
    shutil.copytree(REPO / "tests" / "fixtures" / "articles", root / "data" / "articles" / "fx")
    e, n = validate.run(root)
    assert e == [] and n == 3


def test_proposal_already_in_vocab_is_error(root):
    (root / "taxonomy" / "proposals.yml").write_text(
        yaml.safe_dump([{"axis": "task", "id": "recommendation", "ja": "x", "en": "x", "reason": "r"}])
    )
    assert any("既に語彙" in e for e in errs(root))


def test_valid_proposal_ok(root):
    (root / "taxonomy" / "proposals.yml").write_text(
        yaml.safe_dump([{"axis": "method", "id": "new-method", "ja": "新手法", "en": "New", "reason": "r"}])
    )
    assert errs(root) == []


def test_load_yaml_keeps_dates_as_strings(tmp_path):
    p = tmp_path / "a.yml"
    p.write_text("published: 2026-01-02\n", encoding="utf-8")
    assert validate.load_yaml(p) == {"published": "2026-01-02"}
