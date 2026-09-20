"""
The public website: is it current, complete, linkable, and true?

Nothing here opens a window. The site is generated (`tools/build_site.py`), so
these tests check the *output* the way a search engine, an AI crawler and a
first-time visitor would meet it: the right words in the right tags, every link
alive, the machine-readable files consistent with the pages, and the claims the
pages make matching the app they describe.
"""

import json
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

from tests import require_isolation

require_isolation()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import build_site as site  # noqa: E402

OUT = site.OUT


class Page(HTMLParser):
    """The bits of a page a crawler cares about."""

    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta = {}            # name or property -> content
        self.links = []           # (rel, href, extra attrs)
        self.h1 = []
        self.headings = []        # (level, text)
        self.images = []          # attrs dicts
        self.anchors = []         # hrefs of <a>
        self.ids = set()
        self.jsonld = []
        self.canonical = ""
        self.lang = ""
        self.words = 0
        self._stack = []
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
        elif tag == "link":
            self.links.append((a.get("rel", ""), a.get("href", ""), a))
            if a.get("rel") == "canonical":
                self.canonical = a.get("href", "")
        elif tag == "img":
            self.images.append(a)
        elif tag == "a" and a.get("href") is not None:
            self.anchors.append(a["href"])
        elif tag == "script" and a.get("type") == "application/ld+json":
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


class Fresh(unittest.TestCase):
    def test_the_site_matches_what_the_generator_would_write(self):
        stale = [str(p.relative_to(ROOT)) for p, text in site.outputs().items()
                 if not p.exists() or p.read_text(encoding="utf-8") != text]
        self.assertEqual(stale, [], "site/ is out of date: run python tools/build_site.py")

    def test_the_version_on_the_site_is_the_apps_version(self):
        from novelforge import APP_VERSION

        self.assertEqual(site.VERSION, APP_VERSION)


class EveryPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parsed = {p["slug"]: (p, parse(path)) for p, path in pages()}

    def each(self):
        return self.parsed.items()

    def test_each_page_has_one_h1_and_a_sane_heading_order(self):
        for slug, (_p, page) in self.each():
            self.assertEqual(len(page.h1), 1, f"{slug}: {page.h1}")
            self.assertGreater(len(page.h1[0]), 12, slug)
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
            "art styles": ("four", len(mapmaker.STYLES)),
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
        full = (OUT / "llms-full.txt").read_text(encoding="utf-8")
        for slug, entry in ((p["slug"], p) for p in site.PAGES):
            h1 = parse(OUT / entry["path"] / "index.html" if entry["path"]
                       else OUT / "index.html").h1[0]
            self.assertIn(h1.split("<")[0][:20], full, f"{slug}'s heading is not in llms-full.txt")
        self.assertNotIn("<div", full)
        self.assertNotIn("{{", full)

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
            self.assertTrue(href.startswith("http"), f"404 has a relative link: {href}")

    def test_scripting_off_still_shows_the_page(self):
        css = (OUT / "style.css").read_text(encoding="utf-8")
        self.assertIn(".js [data-reveal]", css)
        self.assertNotRegex(css, r"(?m)^\[data-reveal\]\s*\{")
        self.assertIn('classList.add("js")', (OUT / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
