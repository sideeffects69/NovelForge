"""
The public website: is it current, complete, linkable, fast, readable and true?

Nothing here opens a window. The site is generated (`tools/build_site.py`), so
these tests check the *output* the way a search engine, an AI crawler and a
first-time visitor would meet it: the right words in the right tags, every link
alive, the machine-readable files consistent with the pages, the budgets kept,
the colours readable in both schemes, and the claims the pages make matching the
app they describe.

Several checks build a small throwaway site (a copy of the page files plus a few
made-up pages) to prove a mechanism - the `since` gate, real per-page dates, the
guide layout - that the real site cannot show yet.
"""

import ast
import gzip
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

from tests import require_isolation

require_isolation()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import build_site as site  # noqa: E402

OUT = site.OUT

# The budgets the redesign promised (docs/research/website.md, section 4d).
HTML_GZ_BUDGET = 30 * 1024        # per page
CSS_GZ_BUDGET = 30 * 1024
JS_BUDGET = 10 * 1024             # raw, stricter than gzipped
FONT_BUDGET = 100 * 1024          # all font files together
SPRITE_BUDGET = 3 * 1024          # the inline icon sprite
INDEX_RAW_BUDGET = 150 * 1024
INDEX_GZ_BUDGET = 40 * 1024


class Page(HTMLParser):
    """The bits of a page a crawler cares about."""

    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta = {}            # name or property -> content
        self.theme_colors = []    # (content, media) for every theme-color meta
        self.links = []           # (rel, href, extra attrs)
        self.h1 = []
        self.headings = []        # (level, text)
        self.images = []          # attrs dicts
        self.anchors = []         # hrefs of <a>
        self.anchor_info = []     # (href, attrs, class of the enclosing <nav>, or "")
        self.resources = []       # (tag, url) for everything the browser would fetch
        self.uses = []            # <use href="#..."> targets
        self.ids = set()
        self.jsonld = []
        self.canonical = ""
        self.lang = ""
        self.words = 0
        self._stack = []
        self._navs = []
        self._buffer = ""
        self._json = False
        self._skip = 0
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "meta":
            key = a.get("name") or a.get("property")
            if key:
                self.meta[key] = a.get("content", "")
            if key == "theme-color":
                self.theme_colors.append((a.get("content", ""), a.get("media", "")))
        elif tag == "link":
            self.links.append((a.get("rel", ""), a.get("href", ""), a))
            self.resources.append(("link", a.get("href", "")))
            if a.get("rel") == "canonical":
                self.canonical = a.get("href", "")
        elif tag == "img":
            self.images.append(a)
            self.resources.append(("img", a.get("src", "")))
        elif tag in ("script", "iframe", "source", "video", "audio", "embed") and a.get("src"):
            self.resources.append((tag, a["src"]))
        elif tag == "object" and a.get("data"):
            self.resources.append((tag, a["data"]))
        elif tag == "use":
            self.uses.append(a.get("href", ""))
        elif tag == "a" and a.get("href") is not None:
            self.anchors.append(a["href"])
            self.anchor_info.append((a["href"], a, self._navs[-1] if self._navs else ""))
        elif tag == "nav":
            self._navs.append(a.get("class", ""))
        if tag == "script" and a.get("type") == "application/ld+json":
            self._json = True
            self._buffer = ""
        elif tag in ("script", "style"):
            self._skip += 1
        self._stack.append(tag)
        if tag in ("h1", "h2", "h3"):
            self._buffer = ""

    def handle_endtag(self, tag):
        if tag == "script" and self._json:
            self._json = False
            self.jsonld.append(self._buffer)
        elif tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self.title = self._buffer.strip()
        elif tag == "nav" and self._navs:
            self._navs.pop()
        elif tag in ("h1", "h2", "h3"):
            text = " ".join(self._buffer.split())
            self.headings.append((int(tag[1]), text))
            if tag == "h1":
                self.h1.append(text)
        if self._stack:
            self._stack.pop()

    def handle_data(self, data):
        if self._json:
            self._buffer += data
        elif not self._skip:
            self._buffer += data
            if "body" in self._stack or "main" in self._stack:
                self.words += len(data.split())


def pages():
    return [(p, OUT / p["path"] / "index.html" if p["path"] else OUT / "index.html")
            for p in site.PAGES]


def parse(path: Path) -> Page:
    return Page(path.read_text(encoding="utf-8"))


def to_file(url: str, base_url: str):
    """The file in site/ a link points at, or None for links that leave the site."""
    absolute = urljoin(base_url, url)
    if not absolute.startswith(site.SITE):
        return None
    relative = urlparse(absolute).path[len(urlparse(site.SITE).path):]
    target = OUT / relative
    if relative == "" or relative.endswith("/"):
        target = target / "index.html"
    return target


def path_of(url: str, base_url: str):
    """The site-relative page path a link points at ('' for home), or None if it leaves the site."""
    absolute = urldefrag(urljoin(base_url, url))[0]
    return absolute[len(site.SITE):] if absolute.startswith(site.SITE) else None


def gz(text) -> int:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return len(gzip.compress(data, 9))


# -- colour maths, for the contrast checks ----------------------------------


def _linear(channel: float) -> float:
    channel /= 255
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    r, g, b = (int(colour.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def css_tokens(css: str):
    """(light, dark): the hex colour tokens of each scheme, as the browser would resolve them."""
    root = re.search(r":root\s*\{(.*?)\n\}", css, re.S).group(1)
    dark = re.search(r"@media \(prefers-color-scheme: dark\)\s*\{\s*:root\s*\{(.*?)\n  \}", css, re.S).group(1)
    grab = lambda block: dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})\b", block))   # noqa: E731
    light = grab(root)
    return light, {**light, **grab(dark)}


# -- a throwaway site, to prove mechanisms the real one cannot show yet ------

FRONT = """<!--
title: {title}
description: {description}
kind: {kind}
{extra}published: {published}
updated: {updated}
since: {since}
-->
"""


def make_source(pages_to_add: dict) -> Path:
    """A copy of the page files with extras: {relative path: (front matter fields, body)}."""
    temp = Path(tempfile.mkdtemp(prefix="nf_site_"))
    shutil.copytree(site.SOURCE / "pages", temp / "pages")
    for relative, (fields, body) in pages_to_add.items():
        fields = dict(dict(published="2026-09-01", updated="2026-09-10", since="0.0.0", extra=""), **fields)
        target = temp / "pages" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(FRONT.format(**fields) + body, encoding="utf-8")
    return temp


LONG = "A description that is comfortably long enough to be a real one for a made-up page."


class Fresh(unittest.TestCase):
    def test_the_site_matches_what_the_generator_would_write(self):
        files = site.outputs()
        stale = [str(p.relative_to(ROOT)) for p, text in files.items()
                 if not p.exists() or p.read_text(encoding="utf-8") != text]
        self.assertEqual(stale, [], "site/ is out of date: run python tools/build_site.py")
        self.assertEqual(site.stale_files(files), [], "site/ holds a page no page file produces")

    def test_check_mode_agrees(self):
        self.assertEqual(site.main(["--check"]), 0)

    def test_the_version_on_the_site_is_the_apps_version(self):
        from novelforge import APP_VERSION

        self.assertEqual(site.VERSION, APP_VERSION)

    def test_the_changelog_has_an_entry_for_the_current_version(self):
        text = (OUT / "changelog" / "index.html").read_text(encoding="utf-8")
        first = re.search(r"<h2>Version ([\d.]+)</h2>\s*<time datetime=\"([\d-]+)\"", text)
        self.assertEqual(first.group(1), site.VERSION, "write the changelog entry for this version")
        self.assertEqual(first.group(2), site.RELEASED)


class EveryPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parsed = {p["slug"]: (p, parse(path)) for p, path in pages()}

    def each(self):
        return self.parsed.items()

    def test_each_page_has_one_h1_and_a_sane_heading_order(self):
        for slug, (_p, page) in self.each():
            self.assertEqual(len(page.h1), 1, f"{slug}: {page.h1}")
            self.assertGreater(len(page.h1[0]), 8, slug)
            level = 1
            for depth, text in page.headings:
                self.assertLessEqual(depth, level + 1,
                                     f"{slug}: h{depth} {text!r} skips a level")
                level = depth

    def test_titles_and_descriptions_fit_a_search_result_and_are_unique(self):
        titles, descriptions = set(), set()
        for slug, (entry, page) in self.each():
            title, desc = page.title, page.meta.get("description", "")
            self.assertTrue(20 <= len(title) <= 65, f"{slug}: title is {len(title)} long: {title!r}")
            self.assertTrue(70 <= len(desc) <= 175, f"{slug}: description is {len(desc)} long")
            self.assertNotIn(title, titles, f"{slug}: duplicate title")
            self.assertNotIn(desc, descriptions, f"{slug}: duplicate description")
            titles.add(title)
            descriptions.add(desc)
            self.assertEqual(title, entry["title"])

    def test_canonical_social_and_icon_tags_are_all_there(self):
        for slug, (entry, page) in self.each():
            self.assertEqual(page.canonical, site.page_url(entry), slug)
            self.assertEqual(page.lang, "en", slug)
            self.assertIn("width=device-width", page.meta.get("viewport", ""), slug)
            self.assertIn("index,follow", page.meta.get("robots", ""), slug)
            for key in ("og:title", "og:description", "og:image", "og:url",
                        "og:type", "twitter:card", "twitter:image"):
                self.assertTrue(page.meta.get(key), f"{slug}: missing {key}")
            self.assertEqual(page.meta["og:url"], site.page_url(entry))
            self.assertTrue(page.meta["og:image"].startswith(site.SITE), slug)
            rels = {rel for rel, _h, _a in page.links}
            for rel in ("icon", "apple-touch-icon", "manifest", "sitemap", "stylesheet", "canonical"):
                self.assertIn(rel, rels, f"{slug}: no <link rel={rel}>")

    def test_the_google_verification_tag_is_on_the_home_page_exactly(self):
        home = self.parsed["home"][1]
        self.assertEqual(home.meta.get("google-site-verification"),
                         "QoWigTsy_QxyrPABYvUnfKJEMl4INe3RrdUJNUFvf2E")
        raw = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn('<meta name="google-site-verification" content="QoWigTsy_QxyrPABYvUnfKJEMl4INe3RrdUJNUFvf2E" />', raw)
        for slug, (_entry, page) in self.each():
            if slug != "home":
                self.assertNotIn("google-site-verification", page.meta, slug)

    def test_structured_data_parses_and_says_the_right_things(self):
        for slug, (_entry, page) in self.each():
            self.assertEqual(len(page.jsonld), 1, slug)
            data = json.loads(page.jsonld[0])
            self.assertEqual(data["@context"], "https://schema.org")
            kinds = {node["@type"] for node in data["@graph"]}
            self.assertIn("BreadcrumbList", kinds, slug)
            self.assertIn("WebSite", kinds, slug)
        graph = json.loads(self.parsed["home"][1].jsonld[0])["@graph"]
        software = next(n for n in graph if n["@type"] == "SoftwareApplication")
        self.assertEqual(software["offers"]["price"], "0")
        self.assertEqual(software["softwareVersion"], site.VERSION)
        self.assertIn("Windows", software["operatingSystem"])
        self.assertTrue(software["downloadUrl"].endswith("/releases/latest"))
        self.assertNotIn("aggregateRating", software, "no invented ratings")
        self.assertNotIn("review", software, "no invented reviews")

    def test_each_kind_of_page_says_what_it_is_in_its_structured_data(self):
        expect = {"marketing": "WebPage", "docs": "TechArticle", "guide": "Article",
                  "template": "CreativeWork"}
        forbidden = {"Review", "AggregateRating", "Rating", "HowTo", "Question"}
        for slug, (entry, page) in self.each():
            graph = json.loads(page.jsonld[0])["@graph"]
            kinds = [node["@type"] for node in graph]
            if slug == "home":
                self.assertNotIn("FAQPage", kinds, "the home page repeats the FAQ page's answers")
                self.assertIn("SoftwareApplication", kinds)
            elif entry["index"]:
                self.assertIn("CollectionPage", kinds, slug)
            else:
                self.assertIn(expect[entry["kind"]], kinds, slug)
            if slug != "faq":
                self.assertNotIn("FAQPage", kinds, slug)
                self.assertNotIn("Question", kinds, slug)
            self.assertFalse(forbidden & set(kinds), slug)
            text = page.jsonld[0]
            self.assertNotIn('"aggregateRating"', text, slug)
            self.assertNotIn('"review"', text, slug)
            self.assertNotIn("speakable", text, slug)
            for node in graph:
                if node["@type"] in ("TechArticle", "Article", "WebPage", "CollectionPage", "CreativeWork"):
                    self.assertEqual(node["datePublished"], entry["published"], slug)
                    self.assertEqual(node["dateModified"], entry["updated"], slug)

    def test_the_faq_page_becomes_faq_data_that_matches_its_text(self):
        page = self.parsed["faq"][1]
        graph = json.loads(page.jsonld[0])["@graph"]
        faq = next(n for n in graph if n["@type"] == "FAQPage")
        questions = [q["name"] for q in faq["mainEntity"]]
        self.assertGreaterEqual(len(questions), 12)
        text = (OUT / "faq" / "index.html").read_text(encoding="utf-8")
        for q in faq["mainEntity"]:
            self.assertTrue(q["acceptedAnswer"]["text"].strip())
            self.assertIn(q["name"].replace("&", "&amp;"), text.replace("’", "'").replace("&#x27;", "'")
                          .replace("&quot;", '"') or text)
        self.assertEqual(len(questions), len(set(questions)))

    def test_no_page_is_thin_and_no_placeholder_leaked(self):
        shortest = {"support": 150}                 # a donate page is meant to be brief
        for slug, (_entry, page) in self.each():
            floor = shortest.get(slug, 250)
            self.assertGreater(page.words, floor, f"{slug} has only {page.words} words")
        for path in OUT.rglob("*.html"):
            self.assertNotIn("{{", path.read_text(encoding="utf-8"), path.name)

    def test_every_image_has_alt_text_a_real_file_and_the_right_size(self):
        from PIL import Image

        for slug, (entry, page) in self.each():
            base = site.page_url(entry)
            for img in page.images:
                src = img.get("src", "")
                target = to_file(src, base)
                self.assertIsNotNone(target, f"{slug}: {src}")
                self.assertTrue(target.is_file(), f"{slug}: missing image {src}")
                if "brand/icon" not in src:               # the header logo is decorative
                    self.assertTrue(img.get("alt", "").strip(), f"{slug}: {src} has no alt text")
                with Image.open(target) as real:
                    stated = (int(img["width"]), int(img["height"]))
                    # A logo may be shown smaller than its (sharper) file; what
                    # must never happen is a stated shape that is not the picture's.
                    self.assertAlmostEqual(stated[0] / stated[1], real.size[0] / real.size[1],
                                           delta=0.01, msg=f"{slug}: {src} would be distorted")
                    self.assertLessEqual(stated[0], real.size[0], f"{slug}: {src} is upscaled")
                    if "brand/icon" not in src:
                        self.assertEqual(stated, real.size, f"{slug}: {src} has the wrong stated size")

    def test_every_internal_link_and_anchor_leads_somewhere(self):
        ids = {}
        for path in OUT.rglob("*.html"):
            ids[path] = parse(path).ids
        problems = []
        for slug, (entry, page) in self.each():
            base = site.page_url(entry)
            for href in page.anchors:
                if href.startswith(("mailto:", "tel:", "javascript:")):
                    continue
                target = to_file(href, base)
                if target is None:
                    continue                              # an external site
                url, fragment = urldefrag(urljoin(base, href))
                if not target.is_file():
                    problems.append(f"{slug}: {href} -> no such page")
                elif fragment and fragment not in ids.get(target, set()):
                    problems.append(f"{slug}: {href} -> no #{fragment}")
            for use in page.uses:
                if use.strip() and use not in {"#" + i for i in page.ids}:
                    problems.append(f"{slug}: icon {use} is not in the page's sprite")
        self.assertEqual(problems, [])

    def test_the_page_claims_match_the_app(self):
        from novelforge import mapmaker, structures

        text = " ".join(path.read_text(encoding="utf-8")
                        for path in OUT.rglob("*.html")).replace("&#x27;", "'")
        # Every place a page states how many of something there are must agree
        # with the app - not merely one of them.
        counts = {
            "outline frameworks": ("nine", len(structures.framework_names())),
            "terrain types": ("thirteen", len(mapmaker.TERRAIN_ORDER)),
            "kinds of pin": ("twenty", len(mapmaker.PIN_KINDS)),
            "art styles": ("five", len(mapmaker.STYLES)),
        }
        numbers = {"nine": 9, "thirteen": 13, "twenty": 20, "four": 4, "ten": 10,
                   "twelve": 12, "eight": 8, "seven": 7, "six": 6, "five": 5,
                   "three": 3, "eleven": 11, "fifteen": 15, "eighteen": 18}
        for phrase, (_word, real) in counts.items():
            found = re.findall(rf"(?i)\b(\w+) {re.escape(phrase)}", text)
            stated = [numbers[w.lower()] for w in found if w.lower() in numbers]
            self.assertTrue(stated, f"no page states how many {phrase} there are")
            self.assertEqual(set(stated), {real}, f"the pages disagree about {phrase}: {found}")
        features = (OUT / "features" / "index.html").read_text(encoding="utf-8").replace("&#x27;", "'")
        for name in ("Three-Act", "Save the Cat", "Snowflake", "Seven-Point",
                     "Story Circle", "Hero's Journey", "Romancing the Beat", "Freytag"):
            self.assertIn(name, features, name)

    def test_the_docs_numbers_match_the_code(self):
        """The documentation states numbers (retention, delays, defaults); each must be the code's."""
        from novelforge.config import DEFAULT_SETTINGS, THEMES

        def docs(name):
            return re.sub(r"<[^>]+>", "", (OUT / "docs" / name / "index.html").read_text(encoding="utf-8"))

        backups = docs("your-files/backups-and-snapshots")
        self.assertIn(f"keeps the newest {DEFAULT_SETTINGS['backup_retention']} backups", backups)
        self.assertIn(f"keeps the newest {DEFAULT_SETTINGS['snapshot_retention_per_doc']} versions", backups)
        self.assertEqual(DEFAULT_SETTINGS["autosave_seconds"], 30)
        self.assertIn("thirty seconds after you stop typing", backups)
        app = (ROOT / "novelforge" / "ui" / "app.py").read_text(encoding="utf-8")
        self.assertIn("self.after(1500, self._write_journal)", app)
        self.assertIn("a second and a half", backups)
        self.assertIn("if days >= 7:", (ROOT / "novelforge" / "backup.py").read_text(encoding="utf-8"))
        self.assertIn("a week or more old", backups)
        self.assertTrue(DEFAULT_SETTINGS["backup_on_open"] and DEFAULT_SETTINGS["backup_on_close"])

        install = docs("getting-started/install-and-first-launch")
        self.assertIn(f"{DEFAULT_SETTINGS['default_target_words']:,} and "
                      f"{DEFAULT_SETTINGS['default_daily_target']:,} words", install)
        wanted = {line.split(">=")[0].strip().lower()
                  for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").split() if line.strip()}
        for library in wanted:
            self.assertIn(library, install.lower())

        tour = docs("getting-started/tour-of-the-window")
        self.assertEqual(len(THEMES), 4)
        self.assertIn("four themes", tour)
        self.assertEqual(len(re.findall(r"\bmenubar\.add_cascade\(", app)), 8)
        for name in ("File", "Add", "Edit", "Manuscript", "Tools", "Plan", "View", "Help"):
            self.assertIn(f'menubar.add_cascade(label="{name}"', app)
            self.assertIn(name, tour)

        binder = docs("writing/the-binder")
        block = re.search(r"GROUP_ORDER = \[(.*?)\n\]", app, re.S).group(1)
        self.assertEqual(len(re.findall(r'\("\w+", "[^"]+"\)', block)), 12)
        self.assertIn("twelve groups", binder)
        self.assertIn("SCENE_STATUSES = [", (ROOT / "novelforge" / "model.py").read_text(encoding="utf-8"))
        from novelforge.model import SCENE_STATUSES

        for status in SCENE_STATUSES:
            self.assertIn(status, binder)


class HomePage(unittest.TestCase):
    """What the home page shows must be what the program does."""

    def test_the_folder_listing_is_what_a_new_novel_really_contains(self):
        """Every name in the 'your novel is just Word files' listing is created by Project.create()."""
        import html as _html
        from novelforge.project import Project

        text = (OUT / "index.html").read_text(encoding="utf-8")
        block = re.search(r'<pre class="tree">(.*?)</pre>', text, re.S).group(1)
        lines = []
        for raw in block.split("\n"):
            raw = re.sub(r"<i>.*?</i>", "", raw)                       # the little notes
            raw = _html.unescape(re.sub(r"</?b>", "", raw)).rstrip()
            if raw.strip():
                lines.append(raw)
        self.assertGreater(len(lines), 12)
        temp = Path(tempfile.mkdtemp(prefix="nf_files_"))
        self.addCleanup(shutil.rmtree, temp, True)
        project = Project.create("The Ashfall Crown", author="Om Abhyankar", parent=temp)
        self.assertEqual(lines[0].strip(), project.root.name + "/")
        self.assertTrue(any(line.strip().endswith(".docx") for line in lines))
        stack = []
        for line in lines[1:]:
            depth = (len(line) - len(line.lstrip())) // 2
            name = line.strip()
            del stack[depth - 1:]
            found = project.root.joinpath(*stack, name.rstrip("/"))
            self.assertTrue(found.exists(), f"{'/'.join(stack + [name])} is not created for a new novel")
            self.assertEqual(name.endswith("/"), found.is_dir(), name)
            if name.endswith("/"):
                stack.append(name.rstrip("/"))

    def test_the_feature_grid_has_eight_tiles_each_with_one_link_to_a_real_page(self):
        raw = (OUT / "index.html").read_text(encoding="utf-8")
        grid = re.search(r'<div class="bento">(.*?)</section>', raw, re.S).group(1)
        tiles = re.split(r'<div class="tile(?: [wh]2)?">', grid)[1:]
        self.assertEqual(len(tiles), 8)
        for tile in tiles:
            links = re.findall(r'<h3><a href="([^"]+)"', tile)
            self.assertEqual(len(links), 1, tile[:80])
            self.assertTrue(to_file(links[0], site.SITE).is_file(), links[0])
        self.assertIn("nine outline frameworks", re.sub(r"<[^>]+>", "", grid).lower())

    def test_the_hero_states_the_five_facts_and_the_download_button_is_readable(self):
        raw = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"<dt>", raw)), 5)
        self.assertIn(f"Version {site.VERSION}", raw)
        self.assertIn('class="btn btn-primary"', raw)
        for banned in ('class="pill"', "stats-bar", "hero-badges"):
            self.assertNotIn(banned, raw, "no badge pills or round-number stat bar")

    def test_the_comparison_on_home_is_three_rows_and_every_competitor_column_is_dated(self):
        for name in ("index", "compare"):
            path = OUT / "index.html" if name == "index" else OUT / "compare" / "index.html"
            raw = path.read_text(encoding="utf-8")
            head = re.search(r"<thead>(.*?)</thead>", raw, re.S).group(1)
            competitors = re.findall(r"<th[^>]*>([A-Za-z ]+)<small>checked (\d{4}-\d{2}-\d{2})</small>", head)
            self.assertGreaterEqual(len(competitors), 3, name)
            for _who, checked in competitors:
                date.fromisoformat(checked)
        home = (OUT / "index.html").read_text(encoding="utf-8")
        body = re.search(r"<tbody>(.*?)</tbody>", home, re.S).group(1)
        self.assertEqual(body.count("<tr>"), 3)


class Docs(unittest.TestCase):
    """The documentation section: sidebar, previous/next, linking, and the generated shortcuts page."""

    @classmethod
    def setUpClass(cls):
        cls.docs = [p for p in site.PAGES if p["kind"] == "docs" and not p["index"]]
        cls.index = next(p for p in site.PAGES if p["path"] == "docs/")
        cls.parsed = {p["path"]: parse(path) for p, path in pages()}
        cls.entries = {p["path"]: p for p in site.PAGES}

    def sidebar(self, path):
        page = self.parsed[path]
        return [(path_of(h, site.page_url(self.entries[path])), attrs) for h, attrs, nav in page.anchor_info
                if nav == "side"]

    def test_there_is_documentation_and_it_has_every_group_it_uses(self):
        self.assertGreaterEqual(len(self.docs), 5)
        for entry in self.docs:
            self.assertIn(entry["group"], site.DOC_GROUPS)
            self.assertTrue(entry["path"].startswith("docs/" + site.slugify(entry["group"]) + "/"))

    def test_every_docs_page_is_in_the_sidebar_exactly_once_and_marks_itself(self):
        wanted = sorted(p["path"] for p in self.docs)
        for path in [self.index["path"]] + [p["path"] for p in self.docs]:
            rows = self.sidebar(path)
            listed = [p for p, _a in rows if p != "docs/"]
            self.assertEqual(sorted(listed), wanted, f"{path}: the sidebar lists the wrong pages")
            self.assertEqual(len(listed), len(set(listed)), f"{path}: a page is listed twice")
            current = [p for p, a in rows if a.get("aria-current") == "page"]
            self.assertEqual(current, [path], f"{path}: the sidebar should mark exactly this page")

    def test_the_docs_index_lists_every_page_twice_by_topic_and_a_to_z(self):
        page = self.parsed["docs/"]
        base = site.page_url(self.index)
        linked = [path_of(h, base) for h in page.anchors]
        for entry in self.docs:
            self.assertGreaterEqual(linked.count(entry["path"]), 3, f"{entry['path']}: sidebar + topic + A to Z")
        text = (OUT / "docs" / "index.html").read_text(encoding="utf-8")
        for needle in ('id="by-topic"', 'id="a-to-z"'):
            self.assertIn(needle, text)

    def test_no_page_is_an_orphan_and_docs_are_close_to_home(self):
        graph = {}
        for path, page in self.parsed.items():
            base = site.page_url(self.entries[path])
            graph[path] = {p for p in (path_of(h, base) for h in page.anchors) if p is not None}
        seen, frontier = {""}, [""]
        while frontier:
            for target in graph.get(frontier.pop(), ()):
                if target in graph and target not in seen:
                    seen.add(target)
                    frontier.append(target)
        self.assertEqual(sorted(set(graph) - seen), [], "unreachable pages")
        self.assertIn("docs/", graph[""], "the docs are one click from home")
        for entry in self.docs:
            self.assertIn(entry["path"], graph["docs/"], "and every docs page one click from the docs index")

    def test_previous_and_next_form_one_closed_chain_in_sidebar_order(self):
        order = [p for p, _a in self.sidebar("docs/") if p != "docs/"]
        prev_of, next_of = {}, {}
        for entry in self.docs:
            page = self.parsed[entry["path"]]
            base = site.page_url(entry)
            for href, attrs, _nav in page.anchor_info:
                if attrs.get("rel") == "prev":
                    prev_of[entry["path"]] = path_of(href, base)
                elif attrs.get("rel") == "next":
                    next_of[entry["path"]] = path_of(href, base)
        starts = [p["path"] for p in self.docs if p["path"] not in prev_of]
        self.assertEqual(len(starts), 1, "exactly one page has no previous")
        chain, current = [], starts[0]
        while current:
            self.assertNotIn(current, chain, "the chain loops")
            chain.append(current)
            following = next_of.get(current)
            if following:
                self.assertEqual(prev_of.get(following), current, "next and previous disagree")
            current = following
        self.assertEqual(chain, order, "the chain visits every page once, in the sidebar's order")

    def test_linked_from_lists_the_pages_that_really_link_here(self):
        """Compared with the page SOURCES, which are read here without any of the generator's code."""
        raw = {}
        for file in (site.SOURCE / "pages").rglob("*.html"):
            relative = file.relative_to(site.SOURCE / "pages").as_posix()
            if relative == "404.html":
                continue
            raw[relative] = file.read_text(encoding="utf-8")
        by_src = {p["src"]: p for p in site.PAGES}
        for entry in self.docs + [self.entries[p] for p in self.entries if self.entries[p]["kind"] != "docs"
                                  and self.entries[p]["kind"] != "marketing"]:
            expected = set()
            for src, page in by_src.items():
                if page is entry or page["index"]:
                    continue
                for target in re.findall(r'href="\{\{(?:root|site)\}\}([^"#]*)', raw[src]):
                    if target == entry["path"]:
                        expected.add(page["heading"])
            html_text = (OUT / entry["path"] / "index.html").read_text(encoding="utf-8")
            section = re.search(r'<section class="linked-from">(.*?)</section>', html_text, re.S)
            listed = set(re.findall(r"<a href=[^>]*>(.*?)</a>", section.group(1))) if section else set()
            listed = {re.sub(r"&amp;", "&", t) for t in listed}
            self.assertEqual(listed, {re.sub(r"&amp;", "&", t) for t in expected}, entry["path"])

    def test_docs_pages_have_dates_a_breadcrumb_and_an_edit_link(self):
        for entry in self.docs:
            text = (OUT / entry["path"] / "index.html").read_text(encoding="utf-8")
            self.assertIn(f'<time datetime="{entry["updated"]}">', text, entry["path"])
            self.assertIn('aria-label="Breadcrumb"', text)
            self.assertIn(f"{site.REPO}/edit/main/tools/site/pages/{entry['src']}", text)
            self.assertTrue((ROOT / "tools" / "site" / "pages" / entry["src"]).is_file())
            self.assertIn('aria-label="On this page"', text, f"{entry['path']}: contents")

    def test_the_shortcuts_page_equals_the_code(self):
        """Read the app's source with `ast` (the generator uses regular expressions) and compare."""
        tree = ast.parse((ROOT / "novelforge" / "ui" / "app.py").read_text(encoding="utf-8"))

        def name_of(node):
            return node.id if isinstance(node, ast.Name) else node.attr

        def handler(node):
            if isinstance(node, ast.Lambda):
                node = node.body
            if isinstance(node, ast.Call):
                node = node.func
            return node.attr if isinstance(node, ast.Attribute) else None

        def text_keys(mods, key):
            key = {"equal": "=", "plus": "+", "minus": "-", "space": "Space"}.get(key, key)
            key = key.upper() if len(key) == 1 else key
            mods = ["Ctrl" if m == "Control" else m for m in mods]
            return "+".join([m for m in ("Ctrl", "Alt", "Shift") if m in mods] + [key])

        def from_accelerator(text):
            parts = re.split(r"\+(?=.)", text)
            return text_keys(parts[:-1], parts[-1])

        def from_tk(sequence):
            parts = sequence.strip("<>").split("-")
            return text_keys(parts[:-1], parts[-1])

        cascades, entries, labels, binds = {}, [], {}, []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                kw = {k.arg: k.value for k in node.keywords if k.arg}
                if node.func.attr == "add_cascade" and isinstance(kw.get("label"), ast.Constant) \
                        and name_of(node.func.value) == "menubar":
                    cascades[name_of(kw["menu"])] = (node.lineno, kw["label"].value)
                if node.func.attr in ("add_command", "add_checkbutton") and isinstance(kw.get("label"), ast.Constant):
                    labels.setdefault(handler(kw.get("command")), kw["label"].value)
                    if "accelerator" in kw:
                        entries.append((node.lineno, name_of(node.func.value), kw["label"].value,
                                        from_accelerator(kw["accelerator"].value)))
                if node.func.attr == "bind" and node.args and isinstance(node.args[0], ast.Constant) \
                        and str(node.args[0].value).startswith(("<Control", "<Alt", "<Shift")) \
                        and len(node.args) > 1:
                    binds.append((from_tk(node.args[0].value), handler(node.args[1])))
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) \
                    and any(getattr(t, "id", "") == "bindings" for t in node.targets):
                for key, value in zip(node.value.keys, node.value.values):
                    binds.append((from_tk(key.value), handler(value)))

        expected = {}
        for _line, var, label, keys in sorted(entries):
            expected.setdefault(cascades[var][1], []).append((label, keys))
        menu_order = [label for _l, label in sorted(cascades.values()) if label in expected]
        documented = {keys for rows in expected.values() for _l, keys in rows}
        extra = {}
        for keys, name in binds:
            if keys in documented:
                continue
            extra[keys] = ("Suggest a word from your own book (in the editor)"
                           if name == "cmd_complete" else labels[name])

        page = (OUT / "docs" / "reference" / "keyboard-shortcuts" / "index.html").read_text(encoding="utf-8")
        tables = re.findall(r'<h2[^>]*>([^<]*)</h2>\s*<div class="table-wrap"><table class="shortcuts">.*?'
                            r"<tbody>(.*?)</tbody>", page, re.S)

        def rows(fragment):
            import html as _html

            return [(_html.unescape(label), "+".join(re.findall(r"<kbd>(.*?)</kbd>", keys)))
                    for label, keys in re.findall(r"<tr><td>(.*?)</td><td>(.*?)</td></tr>", fragment)]

        shown = [(re.sub(r" menu$", "", heading), rows(body)) for heading, body in tables
                 if heading.endswith(" menu")]
        self.assertEqual([m for m, _r in shown], menu_order)
        for menu, table in shown:
            self.assertEqual(table, expected[menu], f"the {menu} menu's shortcuts differ from app.py")
        total = sum(len(r) for _m, r in shown)
        self.assertEqual(total, sum(len(r) for r in expected.values()))
        self.assertGreaterEqual(total, 30, "the accelerator parse found suspiciously few")
        more = [(label, keys) for heading, body in tables if not heading.endswith(" menu")
                for label, keys in rows(body)]
        self.assertEqual(sorted((k, l) for l, k in more), sorted(extra.items()))
        self.assertTrue(extra, "the page should list the keys that are not in a menu")


class Mechanisms(unittest.TestCase):
    """Made-up sites, to prove what the real one cannot show yet."""

    def build(self, extra, version=None):
        source = make_source(extra)
        self.addCleanup(shutil.rmtree, source, True)
        return site.Site(source=source, version=version or site.VERSION)

    def test_a_page_for_a_later_version_is_built_nowhere_listed_nowhere_and_linked_from_nowhere(self):
        future = ("docs/writing/quick-switcher.html",
                  (dict(title="Quick switcher | NovelForge docs", kind="docs", since="99.0.0",
                        description=LONG + " Gated.", extra="group: Writing\norder: 50\n"),
                   "<p>Secret plans for a future release, keyword zyxwvut.</p><h2>How</h2><p>zyxwvut.</p>"))
        visible = ("docs/writing/notes-on-links.html",
                   (dict(title="Notes on links | NovelForge docs", kind="docs",
                         description=LONG + " Links.", extra="group: Writing\norder: 60\n"),
                    '<p>Read the <a href="{{root}}docs/writing/quick-switcher/">quick switcher</a> soon.</p>'
                    '<ul><li><a href="{{root}}docs/writing/the-binder/">The binder</a></li>'
                    '<li><a href="{{root}}docs/writing/quick-switcher/">Quick switcher</a> (later)</li></ul>'))
        gated = self.build(dict([future, visible]))
        files = {str(p.relative_to(OUT)).replace("\\", "/"): text for p, text in gated.outputs().items()
                 if OUT in p.parents}
        for name, text in files.items():
            self.assertNotIn("quick-switcher", name)
            self.assertNotIn("zyxwvut", text, name)
            self.assertNotIn("Quick switcher", text.replace("quick switcher", ""), name)
        self.assertEqual([p["path"] for p in gated.gated], ["docs/writing/quick-switcher/"])
        page = files["docs/writing/notes-on-links/index.html"]
        self.assertNotIn("quick-switcher", page)
        self.assertIn("Read the quick switcher soon.", page, "an inline link is unwrapped, its words kept")
        self.assertIn("The binder</a>", page)
        index = json.loads(files["search-index.json"])
        self.assertNotIn("docs/writing/quick-switcher/", [e["u"] for e in index])
        # The control: the very same pages, once the version has arrived, DO appear.
        opened = self.build(dict([future, visible]), version="99.0.0")
        opened_files = {str(p.relative_to(OUT)).replace("\\", "/"): t for p, t in opened.outputs().items()
                        if OUT in p.parents}
        self.assertIn("docs/writing/quick-switcher/index.html", opened_files)
        self.assertIn("docs/writing/quick-switcher/", opened_files["sitemap.xml"])
        self.assertIn("zyxwvut", opened_files["search-index.json"])
        self.assertIn("quick-switcher", opened_files["docs/writing/notes-on-links/index.html"])

    def test_lastmod_and_dates_come_from_each_page_not_from_one_constant(self):
        a = ("docs/writing/older.html", (dict(title="An older page | NovelForge docs", kind="docs",
             description=LONG + " Older.", published="2026-01-05", updated="2026-02-11",
             extra="group: Writing\norder: 70\n"), "<p>Older page text.</p>"))
        b = ("docs/writing/newer.html", (dict(title="A newer page | NovelForge docs", kind="docs",
             description=LONG + " Newer.", published="2026-03-01", updated="2026-08-30",
             extra="group: Writing\norder: 71\n"), "<p>Newer page text.</p>"))
        built = self.build(dict([a, b]))
        root = ET.fromstring(built.sitemap())
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        dates = {u.find("s:loc", ns).text: u.find("s:lastmod", ns).text for u in root.findall("s:url", ns)}
        self.assertEqual(dates[site.SITE + "docs/writing/older/"], "2026-02-11")
        self.assertEqual(dates[site.SITE + "docs/writing/newer/"], "2026-08-30")
        self.assertGreater(len(set(dates.values())), 1)
        html_text = built.render(built.by_path["docs/writing/older/"])
        self.assertIn('"dateModified": "2026-02-11"', html_text)
        self.assertIn('"datePublished": "2026-01-05"', html_text)
        self.assertIn("Published <time", html_text)

    def test_real_dates_are_sane(self):
        today = date.today().isoformat()
        for entry in site.PAGES:
            self.assertRegex(entry["updated"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertGreaterEqual(entry["updated"], entry["published"], entry["path"])
            self.assertLessEqual(entry["updated"], today, f"{entry['path']} claims a date in the future")

    def test_guides_and_templates_get_their_own_layout_hub_and_menu_entry(self):
        guide = ("guides/plan-a-book.html", (dict(title="How to plan a book | NovelForge", kind="guide",
                 description=LONG + " Guide."), "<p>Start.</p><h2>Premise</h2><p>x</p><h2>Cast</h2><p>y</p>"))
        template = ("templates/three-act.html", (dict(title="Three-act outline template | NovelForge",
                    kind="template", description=LONG + " Template."), "<p>Beats.</p><h2>The beats</h2>"))
        built = self.build(dict([guide, template]))
        self.assertIn("guides/", built.by_path)
        self.assertIn("templates/", built.by_path)
        page = built.render(built.by_path["guides/plan-a-book/"])
        self.assertIn(f"By {site.AUTHOR}", page)
        self.assertIn('href="../../guides/"', page)
        self.assertIn('"@type": "Article"', page)
        self.assertNotIn('"HowTo"', page)
        self.assertIn("Guides</a>", built.render(built.by_path[""]))
        hub = built.render(built.by_path["guides/"])
        self.assertIn("plan-a-book", hub)
        self.assertIn("CollectionPage", hub)
        self.assertIn('"@type": "CreativeWork"', built.render(built.by_path["templates/three-act/"]))
        real = site.SITE_MODEL
        self.assertNotIn("guides/", real.by_path, "the real site has no guides yet, so no empty hub")
        self.assertNotIn(">Guides</a>", (OUT / "index.html").read_text(encoding="utf-8"))

    def test_a_badly_written_page_stops_the_build_with_a_clear_message(self):
        for label, extra, body in (
                ("wrong group", dict(title="Bad group | NovelForge docs", kind="docs", description=LONG + "1",
                                     extra="group: Sorcery\n"), "<p>x</p>"),
                ("h1 in a docs body", dict(title="Bad h1 page | NovelForge docs", kind="docs",
                                           description=LONG + "2", extra="group: Writing\n"), "<h1>Nope</h1>"),
                ("no h1 in a marketing page", dict(title="A marketing page | NovelForge", kind="marketing",
                                                   description=LONG + "3"), "<p>no heading</p>"),
                ("bad date", dict(title="Bad date | NovelForge docs", kind="docs", description=LONG + "4",
                                  published="20-09-2026", extra="group: Writing\n"), "<p>x</p>"),
        ):
            source = make_source({f"docs/writing/{label.split()[0]}-x.html": (extra, body)})
            self.addCleanup(shutil.rmtree, source, True)
            with self.assertRaises(SystemExit, msg=label):
                site.load_pages(source)


class Speed(unittest.TestCase):
    """Byte budgets: the site stays as light as it was promised to be."""

    def test_every_page_is_small_when_compressed(self):
        for entry, path in pages():
            size = gz(path.read_text(encoding="utf-8"))
            self.assertLessEqual(size, HTML_GZ_BUDGET, f"{entry['path'] or 'home'} is {size} bytes gzipped")
        self.assertLessEqual(gz((OUT / "404.html").read_text(encoding="utf-8")), HTML_GZ_BUDGET)

    def test_stylesheet_script_fonts_and_icons_stay_in_budget(self):
        css = (OUT / "style.css").read_bytes()
        js = (OUT / "app.js").read_bytes()
        self.assertLessEqual(gz(css), CSS_GZ_BUDGET)
        self.assertLessEqual(len(js), JS_BUDGET, "app.js is over its 10 KB budget")
        fonts = sorted((OUT / "assets" / "fonts").glob("*.woff2"))
        self.assertGreaterEqual(len(fonts), 2)
        self.assertLessEqual(sum(f.stat().st_size for f in fonts), FONT_BUDGET)
        self.assertLessEqual(len(site.sprite().encode("utf-8")), SPRITE_BUDGET)

    def test_the_search_index_parses_covers_every_page_and_stays_small(self):
        raw = (OUT / "search-index.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        self.assertLessEqual(len(raw.encode("utf-8")), INDEX_RAW_BUDGET)
        self.assertLessEqual(gz(raw), INDEX_GZ_BUDGET)
        self.assertEqual(sorted(e["u"] for e in data), sorted(p["path"] for p in site.PAGES))
        for entry in data:
            self.assertEqual(set(entry), {"t", "u", "g", "d", "h", "b"})
            self.assertTrue(entry["t"].strip() and entry["d"].strip())
            self.assertLessEqual(len(entry["b"]), site.INDEX_BODY_CHARS)
            self.assertTrue(to_file(entry["u"], site.SITE).is_file(), entry["u"])
        home = next(e for e in data if e["u"] == "")
        self.assertTrue(home["b"], "the home page is searchable by its text")


class NoThirdParties(unittest.TestCase):
    """The footer says 'no cookies, no tracking, no third-party requests': prove the last one."""

    @staticmethod
    def foreign(url: str) -> bool:
        return bool(urlparse(url).netloc) and not url.startswith(site.SITE)

    def test_no_page_loads_anything_from_another_origin(self):
        for entry, path in pages():
            page = parse(path)
            for tag, url in page.resources:
                self.assertFalse(self.foreign(url), f"{entry['path'] or 'home'}: <{tag}> loads {url}")
            raw = path.read_text(encoding="utf-8")
            for match in re.findall(r"""(?:src|srcset|data|poster)=["']([^"']+)""", raw):
                self.assertFalse(self.foreign(match.split()[0]), f"{entry['path']}: {match}")
        notfound = parse(OUT / "404.html")
        for tag, url in notfound.resources:
            self.assertFalse(self.foreign(url), f"404: <{tag}> loads {url}")

    def test_the_stylesheet_and_the_script_ask_for_nothing_outside_the_site(self):
        css = (OUT / "style.css").read_text(encoding="utf-8")
        for url in re.findall(r"url\(\s*['\"]?([^)'\"]+)", css):
            self.assertFalse(self.foreign(url) or url.startswith("//"), f"style.css loads {url}")
            if not url.startswith("data:"):
                self.assertTrue((OUT / url).is_file(), f"style.css points at a missing {url}")
        self.assertNotIn("@import", css)
        js = re.sub(r"/\*.*?\*/", "", (OUT / "app.js").read_text(encoding="utf-8"), flags=re.S)
        self.assertNotRegex(js, r"https?://")
        self.assertNotRegex(js, r"\b(localStorage|sessionStorage|document\.cookie)\b")

    def test_no_font_comes_from_google_and_the_ones_we_ship_are_preloaded_and_licensed(self):
        home = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("googleapis", home)
        self.assertNotIn("gstatic", home)
        css = (OUT / "style.css").read_text(encoding="utf-8")
        faces = re.findall(r'@font-face\s*\{[^}]*url\("([^"]+)"\)', css)
        self.assertEqual(len(faces), 2)
        for face in faces:
            self.assertTrue((OUT / face).is_file(), face)
            self.assertIn(f'href="{face}"', home, "preloaded")
        licence = (OUT / "assets" / "fonts" / "LICENSE.txt").read_text(encoding="utf-8")
        self.assertIn("SIL OPEN FONT LICENSE", licence.upper())


class Design(unittest.TestCase):
    """Light and dark, readable in both; keyboard, touch and motion respected."""

    @classmethod
    def setUpClass(cls):
        cls.css = (OUT / "style.css").read_text(encoding="utf-8")
        cls.light, cls.dark = css_tokens(cls.css)

    def test_text_links_and_buttons_read_well_in_both_schemes(self):
        text = ("text", "text-2", "text-muted", "link")
        surfaces = ("bg", "bg-alt", "surface", "surface-2", "code-bg")
        for scheme, tokens in (("light", self.light), ("dark", self.dark)):
            for name in text + surfaces + ("focus", "border-strong", "brand", "brand-bright", "on-brand",
                                           "ok", "warn", "danger"):
                self.assertIn(name, tokens, f"--{name} is not defined in the {scheme} scheme")
            for fg in text:
                for bg in surfaces:
                    ratio = contrast(tokens[fg], tokens[bg])
                    self.assertGreaterEqual(ratio, 4.5, f"{scheme}: --{fg} on --{bg} is {ratio:.2f}:1")
            for fill in ("brand", "brand-bright"):
                ratio = contrast(tokens["on-brand"], tokens[fill])
                self.assertGreaterEqual(ratio, 4.5, f"{scheme}: the primary button text on --{fill} is {ratio:.2f}:1")

    def test_focus_rings_borders_and_status_colours_reach_three_to_one(self):
        for scheme, tokens in (("light", self.light), ("dark", self.dark)):
            for fg in ("focus", "border-strong", "ok", "warn", "danger"):
                for bg in ("bg", "surface"):
                    ratio = contrast(tokens[fg], tokens[bg])
                    self.assertGreaterEqual(ratio, 3.0, f"{scheme}: --{fg} on --{bg} is {ratio:.2f}:1")

    def test_every_variable_the_stylesheet_uses_is_defined(self):
        defined = set(re.findall(r"--([\w-]+)\s*:", self.css))
        used = set(re.findall(r"var\(--([\w-]+)", self.css))
        self.assertEqual(sorted(used - defined), [])
        for name in set(self.dark) - set(self.light):
            self.fail(f"--{name} exists only in the dark scheme")

    def test_light_and_dark_both_follow_the_system_and_say_so(self):
        self.assertIn("color-scheme: light dark", self.css)
        self.assertIn("@media (prefers-color-scheme: dark)", self.css)
        for entry, path in pages():
            page = parse(path)
            self.assertEqual(page.meta.get("color-scheme"), "light dark", entry["path"])
            self.assertEqual(sorted(m for _c, m in page.theme_colors),
                             ["(prefers-color-scheme: dark)", "(prefers-color-scheme: light)"], entry["path"])
        self.assertNotIn("data-theme", self.css, "there is no manual switch to get out of step")

    def test_keyboard_touch_and_motion_are_looked_after(self):
        self.assertRegex(self.css, r":focus-visible\s*\{[^}]*outline:\s*2px solid")
        for selector in (r"\.btn", r"\.main-nav a", r"\.search-fallback, \.search\.live"):
            block = re.search(selector + r"\s*\{[^}]*\}", self.css)
            self.assertIsNotNone(block, selector)
            self.assertIn("min-height: 44px", block.group(0), f"{selector} is under 44px tall")
        self.assertIn("prefers-reduced-motion", self.css)
        self.assertIn("scroll-behavior: auto", self.css)
        self.assertNotIn("data-reveal", self.css)
        self.assertNotRegex(self.css, r"(?m)^\s*\.js\b", "nothing may wait for a script to be visible")

    def test_every_page_has_a_skip_link_a_main_landmark_and_no_scripted_hiding(self):
        for entry, path in pages():
            page = parse(path)
            self.assertEqual(page.anchors[0], "#main", entry["path"])
            self.assertIn("main", page.ids)
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("data-reveal", raw)
            self.assertNotIn("<noscript", raw)
            self.assertNotIn('classList.add("js")', raw)
            self.assertEqual(raw.count("<script"), raw.count('<script type="application/ld+json">') + 1,
                             "one JSON-LD block and the one enhancing script, nothing else")

    def test_the_script_is_only_an_enhancement_and_is_valid(self):
        js = (OUT / "app.js").read_text(encoding="utf-8")
        for feature in ("search-index.json", "IntersectionObserver", "clipboard", '"/"'):
            self.assertIn(feature, js)
        self.assertNotIn("document.write", js)
        node = shutil.which("node")
        if node:
            done = subprocess.run([node, "--check", str(OUT / "app.js")], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)

    def test_search_finds_pages_by_title_first_and_needs_every_word(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is not installed")
        js = (OUT / "app.js").read_text(encoding="utf-8")
        score = re.search(r"  function score\(page, terms\) \{.*?\n  \}\n", js, re.S).group(0)
        index = json.loads((OUT / "search-index.json").read_text(encoding="utf-8"))

        def search(query):
            harness = score + ("\nconst pages = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
                               "const terms = process.argv[1].toLowerCase().split(/\\s+/).filter(Boolean);\n"
                               "const hits = pages.map(p => ({u: p.u, s: score(p, terms)})).filter(h => h.s)"
                               ".sort((a, b) => b.s - a.s).slice(0, 8);\n"
                               "console.log(JSON.stringify(hits.map(h => h.u)));")
            done = subprocess.run([node, "-e", harness, query], input=json.dumps(index),
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            return json.loads(done.stdout)

        self.assertEqual(search("binder")[0], "docs/writing/the-binder/")
        self.assertEqual(search("keyboard shortcuts")[0], "docs/reference/keyboard-shortcuts/")
        self.assertEqual(search("backups snapshots")[0], "docs/your-files/backups-and-snapshots/")
        self.assertEqual(search("binder zzzzqqqq"), [], "every word has to match")
        self.assertLessEqual(len(search("the")), 8)
        for entry in index:
            self.assertIn(entry["u"], search(entry["t"]), f"{entry['t']!r} cannot be found by its own title")


class MachineReadableFiles(unittest.TestCase):
    def test_the_sitemap_lists_every_page_once_with_real_dates(self):
        root = ET.parse(OUT / "sitemap.xml").getroot()
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = [u.find("s:loc", ns).text for u in root.findall("s:url", ns)]
        self.assertEqual(sorted(urls), sorted(site.page_url(p) for p in site.PAGES))
        self.assertEqual(len(urls), len(set(urls)))
        by_url = {site.page_url(p): p for p in site.PAGES}
        for u in root.findall("s:url", ns):
            lastmod = u.find("s:lastmod", ns).text
            self.assertRegex(lastmod, r"^\d{4}-\d{2}-\d{2}$")
            # The date is the page's own "updated", never the release date.
            self.assertEqual(lastmod, by_url[u.find("s:loc", ns).text]["updated"])
            # Google ignores these two; emitting them only suggests precision.
            self.assertIsNone(u.find("s:priority", ns))
            self.assertIsNone(u.find("s:changefreq", ns))
        raw = (OUT / "sitemap.xml").read_text(encoding="utf-8")
        for match in re.findall(r"<image:loc>([^<]+)</image:loc>", raw):
            self.assertTrue(to_file(match, site.SITE).is_file(), match)

    def test_robots_txt_welcomes_search_engines_and_ai_crawlers(self):
        text = (OUT / "robots.txt").read_text(encoding="utf-8")
        self.assertIn(f"Sitemap: {site.SITE}sitemap.xml", text)
        self.assertNotRegex(text, r"(?im)^Disallow:\s*/\s*$", "the whole site must not be blocked")
        agents = re.findall(r"(?im)^User-agent:\s*(.+)$", text)
        for bot in ("*", "GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot",
                    "PerplexityBot", "Google-Extended", "Googlebot", "Bingbot",
                    "Applebot-Extended", "CCBot"):
            self.assertIn(bot, agents, f"robots.txt never mentions {bot}")
        blocks = text.split("User-agent:")[1:]
        for block in blocks:
            self.assertIn("Allow: /", block)

    def test_llms_txt_describes_the_project_and_links_every_page(self):
        text = (OUT / "llms.txt").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# NovelForge"))
        self.assertRegex(text, r"(?m)^> .+free.+Windows")
        for entry in site.PAGES:
            self.assertIn(site.page_url(entry), text)
        self.assertIn(site.SITE + "llms-full.txt", text)
        self.assertIn("## Documentation", text)
        full = (OUT / "llms-full.txt").read_text(encoding="utf-8")
        for slug, entry in ((p["slug"], p) for p in site.PAGES):
            h1 = parse(OUT / entry["path"] / "index.html" if entry["path"]
                       else OUT / "index.html").h1[0]
            self.assertIn(h1.split("<")[0][:20], full, f"{slug}'s heading is not in llms-full.txt")
        self.assertNotIn("<div", full)
        self.assertNotIn("{{", full)
        self.assertIn("| Command | Keys |", full, "the generated tables reach llms-full.txt")

    def test_the_web_manifest_and_favicons_exist(self):
        manifest = json.loads((OUT / "site.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "NovelForge")
        for icon in manifest["icons"]:
            self.assertTrue((OUT / icon["src"]).is_file(), icon["src"])
        for name in ("favicon.ico", "assets/brand/favicon-16.png", "assets/brand/favicon-32.png",
                     "assets/brand/apple-touch-icon.png", "assets/brand/og-image.jpg"):
            self.assertTrue((OUT / name).is_file(), name)

    def test_the_404_page_is_not_indexed_and_links_absolutely(self):
        page = parse(OUT / "404.html")
        self.assertEqual(page.meta.get("robots"), "noindex")
        for href in page.anchors:
            if href.startswith("#"):
                continue
            self.assertTrue(href.startswith("http"), f"404 has a relative link: {href}")

    def test_scripting_off_still_shows_the_page(self):
        css = (OUT / "style.css").read_text(encoding="utf-8")
        self.assertNotIn("[data-reveal]", css)
        for entry, path in pages():
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("data-reveal", raw)
            self.assertNotIn('classList.add("js")', raw)
        # The search box is put in by the script; the server sends a working link instead.
        home = (OUT / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="search-fallback" href="', home)


if __name__ == "__main__":
    unittest.main()
