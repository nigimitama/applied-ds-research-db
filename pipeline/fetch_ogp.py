"""記事YAMLに OGP 画像URL(`image:`)を追加する。

og:image / twitter:image を記事ページから取得し、`url:` 行の直後に挿入する。
取得できない記事はスキップ(画像なしでカード表示)。既に `image:` がある記事は触らない。
YAMLは再シリアライズせず、テキスト挿入のみ行う(整形を保つ)。

使い方: python pipeline/fetch_ogp.py [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import yaml

ROOT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (compatible; snaggletooth-bot/1.0)"
KEYS = ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src")


class _Meta(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        a = dict(attrs)
        key = (a.get("property") or a.get("name") or "").lower()
        if key in KEYS and a.get("content"):
            self.found.setdefault(key, a["content"].strip())


def extract_image(html: str, base_url: str) -> str | None:
    p = _Meta()
    p.feed(html)
    for k in KEYS:
        if k in p.found:
            u = urljoin(base_url, p.found[k])
            if u.startswith(("http://", "https://")):
                return u
    return None


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(500_000).decode("utf-8", errors="replace")


def insert_image(text: str, image: str) -> str:
    out, done = [], False
    for line in text.splitlines(keepends=True):
        out.append(line)
        if not done and line.startswith("url:"):
            out.append(f'image: "{image}"\n')
            done = True
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delay", type=float, default=1.0)
    args = ap.parse_args()
    n = 0
    for path in sorted((ROOT / "data" / "articles").rglob("*.yml")):
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        if data.get("image"):
            continue
        if args.limit and n >= args.limit:
            break
        n += 1
        try:
            img = extract_image(fetch_html(data["url"]), data["url"])
        except Exception as e:  # noqa: BLE001
            print(f"SKIP {path.name}: {e}", file=sys.stderr)
            continue
        if not img:
            print(f"none {path.name}")
            continue
        print(f"{'would add' if args.dry_run else 'add'} {path.name}: {img}")
        if not args.dry_run:
            path.write_text(insert_image(text, img), encoding="utf-8")
        time.sleep(args.delay)
    return 0


if __name__ == "__main__":
    sys.exit(main())
