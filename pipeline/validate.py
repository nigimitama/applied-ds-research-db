#!/usr/bin/env python3
"""データ検証。スキーマ・語彙・参照整合性・重複をチェックする。

使い方:
    python pipeline/validate.py            # リポジトリ全体
    python pipeline/validate.py --root DIR # 別ルート(テスト用)
終了コード: 0=OK, 1=エラーあり
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml
from jsonschema import Draft202012Validator

TAXONOMY_AXES = {"task": "tasks", "domain": "domains", "method": "methods", "data_type": "data_types"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
TRACKING_PARAMS = {"fbclid", "gclid", "ref", "ref_src", "source", "mc_cid", "mc_eid"}


def normalize_url(url: str) -> str:
    """重複判定用にURLを正規化する(スキーム/ホスト小文字化、追跡パラメータ・フラグメント・末尾スラッシュ除去、arXivのバージョン除去)。"""
    p = urlsplit(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    path = p.path.rstrip("/") or "/"
    if host.endswith("arxiv.org"):
        path = re.sub(r"(/(?:abs|pdf)/[^/]+?)(?:v\d+)?(?:\.pdf)?$", r"\1", path)
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(p.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
        )
    )
    return urlunsplit(("https", host, path, query, ""))


class _StrDateLoader(yaml.SafeLoader):
    """日付(2026-01-02)を date ではなく文字列のまま読む。スキーマは日付を string で定義しているため。"""


_StrDateLoader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_yaml(path: Path):
    with path.open(encoding="utf-8") as f:
        return yaml.load(f, Loader=_StrDateLoader)


def load_schema(root: Path, name: str) -> Draft202012Validator:
    schema = json.loads((root / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def schema_errors(validator: Draft202012Validator, data, label: str) -> list[str]:
    return [
        f"{label}: {'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.absolute_path)))
    ]


def load_taxonomy(root: Path, errors: list[str]) -> dict[str, set[str]]:
    vocab: dict[str, set[str]] = {}
    for axis, fname in TAXONOMY_AXES.items():
        path = root / "taxonomy" / f"{fname}.yml"
        ids: set[str] = set()
        seen_labels: dict[str, str] = {}
        for i, item in enumerate(load_yaml(path) or []):
            label = f"{path.relative_to(root)}[{i}]"
            if not isinstance(item, dict) or not {"id", "ja", "en"} <= item.keys():
                errors.append(f"{label}: id/ja/en が必要")
                continue
            if not ID_RE.match(str(item["id"])):
                errors.append(f"{label}: id '{item['id']}' はkebab-case(小文字英数とハイフン)")
            if item["id"] in ids:
                errors.append(f"{label}: id '{item['id']}' が重複")
            ids.add(item["id"])
            for name in [item["id"], item["ja"], item["en"], *item.get("aliases", [])]:
                key = str(name).lower()
                if key in seen_labels and seen_labels[key] != item["id"]:
                    errors.append(f"{label}: 名称/別名 '{name}' が '{seen_labels[key]}' と衝突")
                seen_labels[key] = item["id"]
        vocab[axis] = ids
    return vocab


def load_companies(root: Path, errors: list[str]) -> set[str]:
    validator = load_schema(root, "company")
    ids: set[str] = set()
    for path in sorted((root / "companies").glob("*.yml")):
        for i, item in enumerate(load_yaml(path) or []):
            label = f"{path.relative_to(root)}[{i}]"
            errs = schema_errors(validator, item, label)
            errors.extend(errs)
            if errs:
                continue
            if item["id"] in ids:
                errors.append(f"{label}: 企業id '{item['id']}' が重複")
            ids.add(item["id"])
    return ids


def validate_sources(root: Path, companies: set[str], errors: list[str]) -> None:
    validator = load_schema(root, "source")
    seen: set[str] = set()
    for path in sorted((root / "sources").rglob("*.yml")):
        label = str(path.relative_to(root))
        data = load_yaml(path)
        errs = schema_errors(validator, data, label)
        errors.extend(errs)
        if errs:
            continue
        if data["id"] in seen:
            errors.append(f"{label}: ソースid '{data['id']}' が重複")
        seen.add(data["id"])
        if path.stem != data["id"]:
            errors.append(f"{label}: ファイル名とid('{data['id']}')が不一致")
        if data.get("company") and data["company"] not in companies:
            errors.append(f"{label}: 未登録の企業 '{data['company']}'")


def validate_articles(root: Path, vocab: dict[str, set[str]], companies: set[str], errors: list[str]) -> int:
    validator = load_schema(root, "article")
    ids: dict[str, str] = {}
    urls: dict[str, str] = {}
    count = 0
    for path in sorted((root / "data" / "articles").rglob("*.yml")):
        count += 1
        label = str(path.relative_to(root))
        data = load_yaml(path)
        errs = schema_errors(validator, data, label)
        errors.extend(errs)
        if errs:
            continue
        if path.stem != data["id"]:
            errors.append(f"{label}: ファイル名とid('{data['id']}')が不一致")
        if data["id"] in ids:
            errors.append(f"{label}: id '{data['id']}' が {ids[data['id']]} と重複")
        ids[data["id"]] = label
        for u in [data["url"], *data.get("alt_urls", [])]:
            n = normalize_url(u)
            if n in urls and urls[n] != label:
                errors.append(f"{label}: URL '{u}' が {urls[n]} と重複")
            urls[n] = label
        for c in data["companies"]:
            if c not in companies:
                errors.append(f"{label}: 未登録の企業 '{c}' (companies/ に追加してください)")
        for axis, tags in data["tags"].items():
            for t in tags:
                if t not in vocab[axis]:
                    errors.append(f"{label}: 未登録のタグ {axis}:'{t}' (taxonomy/ か proposals.yml へ)")
        if data["published"] > data["collected"]:
            errors.append(f"{label}: published が collected より未来")
        if data["source"]["type"] in ("conference", "journal") and data["evidence"] != "peer_reviewed":
            errors.append(f"{label}: conference/journal は evidence=peer_reviewed のはず")
        if data["source"]["type"] == "techblog" and data["evidence"] != "blog":
            errors.append(f"{label}: techblog は evidence=blog のはず")
    return count


def validate_rejected(root: Path, errors: list[str]) -> None:
    path = root / "data" / "rejected.jsonl"
    if not path.exists():
        return
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"data/rejected.jsonl:{n}: JSONとして不正 ({e})")
            continue
        if not {"url", "reason", "date"} <= row.keys():
            errors.append(f"data/rejected.jsonl:{n}: url/reason/date が必要")


def validate_proposals(root: Path, vocab: dict[str, set[str]], errors: list[str]) -> None:
    path = root / "taxonomy" / "proposals.yml"
    if not path.exists():
        return
    seen: set[tuple[str, str]] = set()
    for i, item in enumerate(load_yaml(path) or []):
        label = f"taxonomy/proposals.yml[{i}]"
        if not isinstance(item, dict) or not {"axis", "id", "ja", "en", "reason"} <= item.keys():
            errors.append(f"{label}: axis/id/ja/en/reason が必要")
            continue
        if item["axis"] not in vocab:
            errors.append(f"{label}: axis '{item['axis']}' が不正")
            continue
        if not ID_RE.match(str(item["id"])):
            errors.append(f"{label}: id '{item['id']}' はkebab-case")
        if item["id"] in vocab[item["axis"]]:
            errors.append(f"{label}: '{item['id']}' は既に語彙にある(提案を削除してください)")
        if (item["axis"], item["id"]) in seen:
            errors.append(f"{label}: 提案が重複")
        seen.add((item["axis"], item["id"]))


def run(root: Path) -> tuple[list[str], int]:
    errors: list[str] = []
    vocab = load_taxonomy(root, errors)
    companies = load_companies(root, errors)
    validate_sources(root, companies, errors)
    n = validate_articles(root, vocab, companies, errors)
    validate_rejected(root, errors)
    validate_proposals(root, vocab, errors)
    return errors, n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = ap.parse_args()
    errors, n = run(args.root)
    if errors:
        print(f"NG: {len(errors)} 件のエラー", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"OK: 記事 {n} 件を検証しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
