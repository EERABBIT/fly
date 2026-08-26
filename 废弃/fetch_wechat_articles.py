#!/usr/bin/env python3
"""
Fetch WeChat public-account articles with curl and extract readable text.

Usage:
  python3 fetch_wechat_articles.py
  python3 fetch_wechat_articles.py URL [URL ...]

Outputs:
  wechat_articles/raw/*.html
  wechat_articles/*.md
  wechat_articles/index.json
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable


DEFAULT_URLS = [
    "https://mp.weixin.qq.com/s/YkGSeQv_n-3Xupt9WE33-g",
    "https://mp.weixin.qq.com/s/NsTJgFH-fjIw4vfE5E614A",
    "https://mp.weixin.qq.com/s/aR35gfIRqvny98hk4AodfQ",
    "https://mp.weixin.qq.com/s/uQIuQmoMwBqTlWzpFyhtPw",
]

OUT_DIR = Path("wechat_articles")
RAW_DIR = OUT_DIR / "raw"


@dataclass
class Article:
    url: str
    raw_path: Path
    md_path: Path
    title: str
    author: str
    publish_time: str
    digest: str
    text: str


class WeChatContentParser(HTMLParser):
    BLOCK_TAGS = {"p", "div", "section", "br", "li", "ul", "ol", "blockquote", "h1", "h2", "h3"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_content = False
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name: value for name, value in attrs}
        if attrs_dict.get("id") == "js_content":
            self.in_content = True
            self.depth = 1
            return

        if self.in_content:
            self.depth += 1
            if tag in self.BLOCK_TAGS:
                self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self.in_content:
            return
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")
        self.depth -= 1
        if self.depth <= 0:
            self.in_content = False

    def handle_data(self, data: str) -> None:
        if self.in_content:
            text = data.strip()
            if text:
                self.parts.append(text)

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = []
        for line in raw.splitlines():
            line = re.sub(r"[ \t\u3000]+", " ", line).strip()
            if line:
                lines.append(line)
        return "\n\n".join(lines)


def run_curl(url: str) -> str:
    cmd = [
        "curl",
        "-L",
        "--http1.1",
        "--compressed",
        "--connect-timeout",
        "20",
        "--max-time",
        "60",
        "--retry",
        "2",
        "--retry-delay",
        "2",
        "-H",
        "User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.50 NetType/WIFI Language/zh_CN",
        "-H",
        "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "-H",
        "Accept-Language: zh-CN,zh-Hans;q=0.9,en;q=0.8",
        "-H",
        "Referer: https://mp.weixin.qq.com/",
        url,
    ]
    proc = subprocess.run(cmd, check=False, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"curl failed for {url}: {proc.stderr.strip()}")
    if not proc.stdout.strip():
        raise RuntimeError(f"empty response for {url}")
    return proc.stdout


def first_match(patterns: Iterable[str], source: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, source, flags=re.S)
        if match:
            return cleanup(match.group(1))
    return ""


def cleanup(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\\x26", "&").replace("\\/", "/")
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def js_string(name: str, source: str) -> str:
    pattern = rf"var\s+{re.escape(name)}\s*=\s*(['\"])(.*?)\1"
    match = re.search(pattern, source, flags=re.S)
    if not match:
        return ""
    value = match.group(2)
    try:
        value = bytes(value, "utf-8").decode("unicode_escape")
    except UnicodeDecodeError:
        pass
    return cleanup(value)


def publish_time(source: str) -> str:
    timestamp = js_string("ct", source)
    if timestamp.isdigit():
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(timestamp)))
    return first_match(
        [
            r'id="publish_time"[^>]*>(.*?)</',
            r'class="rich_media_meta rich_media_meta_text"[^>]*>(\d{4}-\d{2}-\d{2}.*?)</',
        ],
        source,
    )


def parse_article(url: str, html_text: str, raw_path: Path, md_path: Path) -> Article:
    title = first_match(
        [
            r'id="activity-name"[^>]*>(.*?)</h1>',
            r'property="og:title"\s+content="(.*?)"',
        ],
        html_text,
    ) or js_string("msg_title", html_text) or "untitled"
    author = first_match(
        [
            r'id="js_name"[^>]*>(.*?)</',
            r'id="profileBt"[^>]*>.*?<strong[^>]*>(.*?)</strong>',
        ],
        html_text,
    ) or js_string("nickname", html_text)
    digest = js_string("msg_desc", html_text)
    parser = WeChatContentParser()
    parser.feed(html_text)
    text = parser.text()
    return Article(
        url=url,
        raw_path=raw_path,
        md_path=md_path,
        title=title,
        author=author,
        publish_time=publish_time(html_text),
        digest=digest,
        text=text,
    )


def slug_for(url: str, idx: int) -> str:
    tail = url.rstrip("/").split("/")[-1]
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    safe_tail = re.sub(r"[^A-Za-z0-9_-]+", "-", tail)[:40] or "article"
    return f"{idx:02d}-{safe_tail}-{digest}"


def write_markdown(article: Article) -> None:
    body = article.text or "[正文提取为空，请查看 raw HTML]"
    markdown = (
        f"# {article.title}\n\n"
        f"- URL: {article.url}\n"
        f"- Author: {article.author or 'unknown'}\n"
        f"- Publish Time: {article.publish_time or 'unknown'}\n"
        f"- Raw HTML: {article.raw_path}\n\n"
    )
    if article.digest:
        markdown += f"## Digest\n\n{article.digest}\n\n"
    markdown += f"## Content\n\n{body}\n"
    article.md_path.write_text(markdown, encoding="utf-8")


def fetch_all(urls: list[str]) -> list[Article]:
    OUT_DIR.mkdir(exist_ok=True)
    RAW_DIR.mkdir(exist_ok=True)
    articles = []
    for idx, url in enumerate(urls, start=1):
        slug = slug_for(url, idx)
        raw_path = RAW_DIR / f"{slug}.html"
        md_path = OUT_DIR / f"{slug}.md"
        print(f"[{idx}/{len(urls)}] fetching {url}", file=sys.stderr)
        html_text = run_curl(url)
        raw_path.write_text(html_text, encoding="utf-8")
        article = parse_article(url, html_text, raw_path, md_path)
        write_markdown(article)
        articles.append(article)
        print(f"  -> {md_path} ({len(article.text)} chars)", file=sys.stderr)
    return articles


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("urls", nargs="*", help="WeChat article URLs")
    args = parser.parse_args()
    urls = args.urls or DEFAULT_URLS
    articles = fetch_all(urls)
    index = [
        {
            "url": item.url,
            "title": item.title,
            "author": item.author,
            "publish_time": item.publish_time,
            "digest": item.digest,
            "raw_path": str(item.raw_path),
            "md_path": str(item.md_path),
            "text_chars": len(item.text),
        }
        for item in articles
    ]
    (OUT_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(index, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
