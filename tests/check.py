#!/usr/bin/env python3
"""Static checks for the site. Standard library only: python3 tests/check.py"""

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://responsibilities.dev/"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

failures = []


def check(ok, message):
    if not ok:
        failures.append(message)


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.ids, self.links, self.headings, self.meta = [], [], [], [], {}
        self.html_lang = self.title = self.canonical = None
        self.text_of = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag not in VOID:
            self.stack.append((tag, self.getpos()[0]))
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "html":
            self.html_lang = a.get("lang")
        if tag == "meta":
            key = a.get("name") or a.get("property") or ("charset" if "charset" in a else None)
            if key:
                self.meta.setdefault(key, []).append(a.get("content", a.get("charset")))
        if tag == "link" and a.get("rel") == "canonical":
            self.canonical = a.get("href")
        for attr in ("href", "src"):
            if attr in a:
                self.links.append((tag, a.get("rel"), a[attr]))
        if re.fullmatch(r"h[1-6]", tag):
            self.headings.append(int(tag[1]))
        if tag == "title":
            self.text_of = "title"

    def handle_data(self, data):
        if self.text_of == "title":
            self.title = (self.title or "") + data

    def handle_endtag(self, tag):
        if tag == "title":
            self.text_of = None
        if tag in VOID:
            return
        if not self.stack or self.stack[-1][0] != tag:
            opened = self.stack[-1] if self.stack else None
            failures.append(f"index.html:{self.getpos()[0]}: </{tag}> does not close {opened}")
            return
        self.stack.pop()


def luminance(hex_color):
    rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


html = (ROOT / "index.html").read_text(encoding="utf-8")
css = (ROOT / "styles.css").read_text(encoding="utf-8")

# Document structure
check(html.startswith("<!doctype html>"), "index.html must start with <!doctype html>")
page = Page()
page.feed(html)
page.close()
check(not page.stack, f"unclosed elements: {page.stack}")
check(page.html_lang == "en", "<html lang> must be en")
check(len(page.ids) == len(set(page.ids)), "duplicate ids")

# SEO / meta
check(page.meta.get("charset") == ["utf-8"], "meta charset utf-8")
check(page.meta.get("viewport") == ["width=device-width, initial-scale=1"], "meta viewport")
check(page.title and "responsibilities" in page.title.lower() and len(page.title) <= 70, f"title: {page.title!r}")
description = (page.meta.get("description") or [""])[0]
check(70 <= len(description) <= 200, f"meta description length {len(description)}")
check(page.canonical == SITE, f"canonical must be {SITE}")
for key in ("og:type", "og:site_name", "og:url", "og:title", "og:description", "twitter:card"):
    check(key in page.meta, f"missing meta {key}")
check(page.meta.get("og:url") == [SITE], f"og:url must be {SITE}")

# Headings: one h1, no skipped levels
check(page.headings.count(1) == 1, "exactly one h1")
for prev, cur in zip(page.headings, page.headings[1:]):
    check(cur <= prev + 1, f"heading level jumps from h{prev} to h{cur}")

# Required content
for phrase in (
    "Give AI agents responsibilities, not just&nbsp;tasks.",
    "Observe deterministically.",
    "Judge probabilistically.",
    "Remember persistently.",
    "Signals",
    "Case instructions",
    "Persistent cases",
    "Work in progress for days",
    "early experiment, not a finished product",
):
    check(phrase in html, f"missing text: {phrase}")

# Links: in-page anchors resolve; local URLs are relative and exist; the only absolute URLs
# are the canonical and og:url of the site itself.
for tag, rel, url in page.links:
    if url.startswith("#"):
        check(url[1:] in page.ids, f"anchor {url} has no target")
    elif re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I) or url.startswith("//"):
        check(url == SITE and rel == "canonical", f"unexpected absolute URL: {url}")
    else:
        check(not url.startswith("/"), f"root-relative URL breaks on a subpath: {url}")
        target = (ROOT / url.split("#")[0].split("?")[0])
        check(target.exists(), f"missing local file: {url}")
absolute = re.findall(r"https?://[^\s\"'<>)]+", html)
check(set(absolute) <= {SITE}, f"external references in index.html: {sorted(set(absolute) - {SITE})}")
check(not re.search(r"https?://|@import", css), "styles.css must not load anything external")

# CSS: balanced braces, every var() defined, and WCAG AA contrast in both colour schemes
check(css.count("{") == css.count("}"), "unbalanced braces in styles.css")
defined = set(re.findall(r"(--[\w-]+)\s*:", css))
for name in set(re.findall(r"var\((--[\w-]+)\)", css)):
    check(name in defined, f"undefined custom property {name}")

light_block = re.search(r":root\s*{(.*?)}", css, re.S).group(1)
dark_block = re.search(r"prefers-color-scheme:\s*dark\)\s*{\s*:root\s*{(.*?)}", css, re.S).group(1)
light = dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", light_block))
themes = {"light": light, "dark": {**light, **dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", dark_block))}}
pairs = [
    ("--ink", "--bg"), ("--ink", "--surface"), ("--ink", "--code-bg"),
    ("--muted", "--bg"), ("--muted", "--surface"),
    ("--accent", "--bg"), ("--accent", "--surface"), ("--accent", "--accent-soft"),
    ("--bg", "--ink"),  # skip link
]
for theme, colours in themes.items():
    for fg, bg in pairs:
        ratio = contrast(colours[fg], colours[bg])
        check(ratio >= 4.5, f"{theme}: {fg} on {bg} contrast {ratio:.2f} < 4.5")

# Publishing
check((ROOT / "CNAME").read_text().strip() == "responsibilities.dev", "CNAME must be responsibilities.dev")
check((ROOT / ".nojekyll").exists(), ".nojekyll missing")

if failures:
    print("\n".join(f"FAIL {f}" for f in failures))
    sys.exit(1)
print("OK")
