#!/usr/bin/env python3
"""Static checks for the site. Standard library only: python3 tests/check.py"""

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://responsibilities.dev/"
PAGES = {"index.html": SITE, "impressum.html": SITE + "impressum.html"}  # page: canonical
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

failures = []


def check(ok, message):
    if not ok:
        failures.append(message)


class Page(HTMLParser):
    def __init__(self, name):
        super().__init__()
        self.name = name
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
            failures.append(f"{self.name}:{self.getpos()[0]}: </{tag}> does not close {opened}")
            return
        self.stack.pop()


def luminance(hex_color):
    rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def parse(name):
    html = (ROOT / name).read_text(encoding="utf-8")
    page = Page(name)
    page.feed(html)
    page.close()
    return html, page


pages = {name: parse(name) for name in PAGES}
css = (ROOT / "styles.css").read_text(encoding="utf-8")

for name, canonical in PAGES.items():
    html, page = pages[name]

    # Document structure
    check(html.startswith("<!doctype html>"), f"{name} must start with <!doctype html>")
    check(not page.stack, f"{name}: unclosed elements: {page.stack}")
    check(page.html_lang == "en", f"{name}: <html lang> must be en")
    check(len(page.ids) == len(set(page.ids)), f"{name}: duplicate ids")

    # SEO / meta
    check(page.meta.get("charset") == ["utf-8"], f"{name}: meta charset utf-8")
    check(page.meta.get("viewport") == ["width=device-width, initial-scale=1"], f"{name}: meta viewport")
    check(page.title and "responsibilities" in page.title.lower() and len(page.title) <= 70, f"{name}: title: {page.title!r}")
    description = (page.meta.get("description") or [""])[0]
    check(70 <= len(description) <= 200, f"{name}: meta description length {len(description)}")
    check(page.canonical == canonical, f"{name}: canonical must be {canonical}")

    # Headings: one h1, no skipped levels
    check(page.headings.count(1) == 1, f"{name}: exactly one h1")
    for prev, cur in zip(page.headings, page.headings[1:]):
        check(cur <= prev + 1, f"{name}: heading level jumps from h{prev} to h{cur}")

    # Every page links to the Impressum
    check(any(url == "impressum.html" for _, _, url in page.links), f"{name}: no link to impressum.html")

    # Links: local URLs are relative, exist and, with a fragment, point at an id that exists;
    # the only absolute URLs are mailto: and the page's own canonical.
    for tag, rel, url in page.links:
        if url.startswith("mailto:"):
            continue
        if re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I) or url.startswith("//"):
            check(url == canonical and rel == "canonical", f"{name}: unexpected absolute URL: {url}")
            continue
        path, _, fragment = url.partition("#")
        path = path.split("?")[0]
        check(not path.startswith("/"), f"{name}: root-relative URL breaks on a subpath: {url}")
        target = ROOT / (path or name)
        if target.is_dir():
            target = target / "index.html"
        check(target.exists(), f"{name}: missing local file: {url}")
        if fragment:
            linked = pages.get(target.relative_to(ROOT).as_posix())
            check(linked is not None and fragment in linked[1].ids, f"{name}: anchor {url} has no target")
    absolute = set(re.findall(r"https?://[^\s\"'<>)]+", html))
    check(absolute <= {SITE, canonical}, f"{name}: external references: {sorted(absolute - {SITE, canonical})}")

# The concept page: Open Graph and required content
html, page = pages["index.html"]
for key in ("og:type", "og:site_name", "og:url", "og:title", "og:description", "twitter:card"):
    check(key in page.meta, f"index.html: missing meta {key}")
check(page.meta.get("og:url") == [SITE], f"index.html: og:url must be {SITE}")
for phrase in (
    "Give AI agents responsibilities, not just&nbsp;tasks.",
    "Observe deterministically.",
    "Judge probabilistically.",
    "Remember persistently.",
    "Five things that should never be forgotten.",
    "The examples are illustrative, not a list of current features.",
    "How responsibilities work",
    "A responsibility keeps watching.",
    "<h3>Observe</h3>",
    "Signals identify what needs watching, using queries against your team’s data.",
    '<p class="tag">Signals</p>',
    "<h3>Judge</h3>",
    "AI evaluates what needs attention, guided by instructions and evidence.",
    '<p class="tag">AI + rules</p>',
    "<h3>Remember</h3>",
    "Persistent cases track unresolved situations and their history across runs.",
    '<p class="tag">Persistent cases</p>',
    "<span>The agent keeps watching.</span>",
    "<span>The responsibility keeps track.</span>",
    "<span>People stay accountable.</span>",
    "People define the responsibility, set the boundaries, and approve what the agent is allowed to do. "
    "The agent keeps watch and can carry out permitted actions. People remain accountable for the outcome.",
    "People are accountable.",
):
    check(phrase in html, f"index.html: missing text: {phrase}")

# The five examples, in order and word for word: title, situation, responsibility
EXAMPLES = [
    ("Don’t leave customers waiting.",
     "A customer reported a problem. The team is working on it, but nobody has given the customer an update in days.",
     "Make sure customers waiting for an answer get one."),
    ("Don’t let reviews go unanswered.",
     "A developer needs a review. The pull request is ready, but nobody responds. Progress comes to a halt.",
     "Make sure work waiting for review doesn’t get stuck."),
    ("Make sure customer-reported bugs get a decision.",
     "Several customers report the same bug. The issues are logged, but nobody decides how urgently they need to be fixed.",
     "Make sure customer-reported bugs are assessed and prioritized."),
    ("Don’t lose customer-reported work.",
     "A support ticket has been handed over to development. The development issue sits in the backlog while the customer is still waiting.",
     "Make sure customer-reported development work doesn’t disappear into the backlog."),
    ("Don’t let releases stall.",
     "A release is waiting for testing. Nobody has taken ownership of the next step, and the planned release date is getting closer.",
     "Make sure releases waiting for validation keep moving."),
]
examples = re.search(r'<ol class="examples"[^>]*>(.*?)</ol>', html, re.S)
items = re.findall(r"<li>(.*?)</li>", examples.group(1), re.S) if examples else []
check(len(items) == len(EXAMPLES), f"index.html: {len(items)} examples, expected {len(EXAMPLES)}")
for item, (title, situation, responsibility) in zip(items, EXAMPLES):
    check(f"<h3>{title}</h3>" in item, f"index.html: example title not verbatim: {title}")
    check(f"<p>{situation}</p>" in item, f"index.html: situation not verbatim: {situation}")
    check(f"<span>Responsibility</span> {responsibility}</p>" in item,
          f"index.html: responsibility not verbatim: {responsibility}")

# How responsibilities work: exactly three steps, after the examples
flow = re.search(r'<ol class="flow"[^>]*>(.*?)</ol>', html, re.S)
check(flow and flow.group(1).count("<li>") == 3, "index.html: the flow must have exactly three steps")
check(html.find('id="examples"') < html.find('id="how"') < html.find('id="accountability"'),
      "index.html: sections must be ordered examples, how, accountability")

# Superseded examples stay gone
for phrase in ("Work in progress for days", "Blocked dependencies", "Recurring customer complaints", "Jira"):
    check(phrase not in html, f"index.html: superseded text: {phrase}")

# Wording: the site presents a concept, not an app, prototype or experiment, and does not name
# the internal implementation
for name in (*PAGES, "styles.css", "README.md"):
    text = (ROOT / name).read_text(encoding="utf-8")
    for word in ("rfj", "experiment", "prototype", "sketch", r"the app\b", "being tested"):
        check(not re.search(rf"\b{word}", text, re.I), f"{name}: unwanted wording: {word}")

# The Impressum: German, marked as such, with an address and a contact email
html, page = pages["impressum.html"]
for phrase in (
    '<div lang="de">',
    "Angaben gemäß § 5 DDG",
    "<address>",
    "Kontakt",
    'href="mailto:georg.schmidl@vicox.net"',
):
    check(phrase in html, f"impressum.html: missing text: {phrase}")

# CSS: nothing external, balanced braces, every var() defined, and WCAG AA contrast in both
# colour schemes
check(not re.search(r"https?://|@import", css), "styles.css must not load anything external")
check(css.count("{") == css.count("}"), "unbalanced braces in styles.css")
defined = set(re.findall(r"(--[\w-]+)\s*:", css))
for prop in set(re.findall(r"var\((--[\w-]+)\)", css)):
    check(prop in defined, f"undefined custom property {prop}")

light_block = re.search(r":root\s*{(.*?)}", css, re.S).group(1)
dark_block = re.search(r"prefers-color-scheme:\s*dark\)\s*{\s*:root\s*{(.*?)}", css, re.S).group(1)
light = dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", light_block))
themes = {"light": light, "dark": {**light, **dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", dark_block))}}
pairs = [
    ("--ink", "--bg"), ("--ink", "--surface"), ("--ink", "--code-bg"),
    ("--muted", "--bg"), ("--muted", "--surface"),
    ("--accent", "--bg"), ("--accent", "--surface"), ("--accent", "--accent-soft"), ("--ink", "--accent-soft"),
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
