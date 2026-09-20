"""
Build the public website (site/) from the page sources in tools/site/.

The output is plain HTML, one stylesheet and one small script. Nothing here is
needed to *serve* the site - GitHub Pages just publishes the folder. This script
exists so that the navigation, footer, canonical URLs, structured data, sitemap,
search index, robots.txt and llms.txt all come from ONE set of page files and
cannot drift apart: add a page file and it is in the menu, the sitemap, the
search and llms.txt at once.

    python tools/build_site.py            rewrite site/
    python tools/build_site.py --check    exit 1 if site/ is out of date

HOW TO ADD A PAGE
-----------------
Create tools/site/pages/<path>.html. The file's path is the page's address:
`docs/writing/binder.html` is served at /docs/writing/binder/, `features.html`
at /features/, `index.html` at the top. The file starts with a front matter
comment, then the body HTML:

    <!--
    title: The binder | NovelForge docs        the <title>; 20-65 characters
    description: Learn how to ...              70-175 characters, unique
    kind: docs                                 marketing | docs | guide | template
    group: Writing                             docs only: one of DOC_GROUPS below
    order: 20                                  position inside its group (docs)
    published: 2026-09-20                      first public date (YYYY-MM-DD)
    updated: 2026-09-20                        last REAL change; becomes lastmod
    since: 2.2.0                               first app version that has this
    image: assets/screenshots/main-editor.png  social image (optional)
    -->
    <p class="lead">Learn how to ...</p>
    <h2>...</h2>

Optional keys: heading (the h1 when it differs from the title's first part), crumb
(the short name in breadcrumbs), nav and navorder (a top-menu entry), level and
dependencies (structured data).

* docs / guide / template pages get their h1, breadcrumbs, dates, contents,
  previous/next and "Linked from" from the layout: do NOT write an h1, and do not
  hand-write anything the layout adds. marketing pages write their own sections
  and exactly one h1.
* THE `since` GATE: a page whose `since` is greater than the app version
  (novelforge.APP_VERSION) is not built, not listed, not in the sitemap or the
  search index, and links to it are quietly removed from other pages (a list item
  that starts with such a link is dropped). So documentation for a feature that
  is still in a work branch can be written now, and appears the day the version
  is bumped.
* {{root}} is the path back to the top of the site (so pages work under
  /NovelForge/ and on their own domain); {{site}} the absolute address; {{repo}},
  {{version}}, {{released}}, {{author}}. {{gen:shortcuts}} is the generated table
  of keyboard shortcuts.
* h2 and h3 get ids automatically; the "On this page" list is built from them.
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urldefrag, urljoin

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "tools" / "site"
OUT = ROOT / "site"
# Files for the ROOT of the host (see root_files); kept in step with the site.
HOST_ROOT = ROOT / "tools" / "site-root"

SITE = "https://sideeffects69.github.io/NovelForge/"
REPO = "https://github.com/sideeffects69/NovelForge"
RELEASED = "2026-09-20"          # when the current VERSION was released
NAME = "NovelForge"
AUTHOR = "Om Abhyankar"
VERIFICATION = "QoWigTsy_QxyrPABYvUnfKJEMl4INe3RrdUJNUFvf2E"   # Google Search Console


def app_version() -> str:
    """The app's own version, read from the source so the site can never disagree."""
    text = (ROOT / "novelforge" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text).group(1)


VERSION = app_version()

# The order of the groups in the docs sidebar. A docs page's `group` must be one
# of these (a typo would otherwise create a stray group).
DOC_GROUPS = ["Getting started", "Writing", "Planning", "Understanding", "Maps",
              "Your files", "Reference"]

KINDS = ("marketing", "docs", "guide", "template")
FRONT_KEYS = {"title", "heading", "crumb", "description", "kind", "group", "order", "published",
              "updated", "since", "image", "nav", "navorder", "level", "dependencies"}

# Section front pages. The docs one is normally a page file (its intro is
# content); the others are made on the fly, but only once at least one page of
# their kind exists.
SECTIONS = {
    "docs/": dict(kind="docs", nav="Docs", navorder=20,
                  title="NovelForge documentation: how every feature works",
                  heading="NovelForge documentation",
                  description="Documentation for NovelForge, free novel writing software for Windows: "
                              "install, write, plan, map, and keep your files safe."),
    "guides/": dict(kind="guide", nav="Guides", navorder=30,
                    title="Guides for novelists | NovelForge",
                    heading="Guides for planning, writing and finishing a novel",
                    description="Practical guides for novelists: planning, outlining, worldbuilding, "
                                "maps and manuscript format, each tied to a tool in NovelForge."),
    "templates/": dict(kind="template", nav="", navorder=0,
                       title="Free novel outline templates | NovelForge",
                       heading="Free novel outline templates in Word format",
                       description="Free outline templates for novelists as real Word .docx files, one "
                                   "for each story framework NovelForge includes."),
}

CRAWLERS = [
    "GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-Web",
    "Claude-SearchBot", "Claude-User", "anthropic-ai", "PerplexityBot",
    "Perplexity-User", "Google-Extended", "Googlebot", "Bingbot", "Applebot",
    "Applebot-Extended", "Amazonbot", "DuckAssistBot", "CCBot", "cohere-ai",
    "Meta-ExternalAgent", "YouBot", "MistralAI-User", "Bytespider",
]

# How much of a page goes into the search index, so a large site stays small.
INDEX_BODY_CHARS = 900

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


# -- small helpers ---------------------------------------------------------


def vtuple(version: str) -> Tuple[int, int, int]:
    parts = [int(n) for n in re.findall(r"\d+", version)][:3]
    return tuple(parts + [0] * (3 - len(parts)))          # type: ignore[return-value]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"


def strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


def plain_text(fragment: str) -> str:
    """Body HTML -> one line of words (for the search index)."""
    fragment = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", fragment, flags=re.S)
    return " ".join(strip_tags(re.sub(r"<[^>]+>", " ", fragment)).split())


def pretty_date(iso: str) -> str:
    year, month, day = (int(n) for n in iso.split("-"))
    return f"{day} {MONTHS[month - 1]} {year}"


def read(name: str, source: Path = SOURCE) -> str:
    return (source / name).read_text(encoding="utf-8")


# -- page files ------------------------------------------------------------

FRONT = re.compile(r"\A\s*<!--\s*\n(.*?)\n\s*-->[ \t]*\n?", re.S)


def parse_front(text: str, label: str) -> Tuple[Dict[str, str], str]:
    match = FRONT.match(text)
    if not match:
        raise SystemExit(f"{label}: a page must start with a <!-- front matter --> comment")
    meta: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        key = key.strip()
        if not sep or key not in FRONT_KEYS:
            raise SystemExit(f"{label}: unknown or malformed front matter line {line!r}")
        meta[key] = value.strip()
    return meta, text[match.end():]


def load_pages(source: Path = SOURCE) -> List[Dict]:
    """Every page file, parsed and checked, gated or not. The 404 page is not one."""
    folder = source / "pages"
    pages: List[Dict] = []
    for file in sorted(folder.rglob("*.html")):
        relative = file.relative_to(folder)
        if relative.as_posix() == "404.html":
            continue
        label = relative.as_posix()
        meta, body = parse_front(file.read_text(encoding="utf-8"), label)
        parts = list(relative.with_suffix("").parts)
        if parts[-1] == "index":
            parts.pop()
        path = "/".join(parts) + "/" if parts else ""
        for key in ("title", "description", "kind", "published", "updated"):
            if not meta.get(key):
                raise SystemExit(f"{label}: front matter needs `{key}`")
        if meta["kind"] not in KINDS:
            raise SystemExit(f"{label}: kind must be one of {KINDS}")
        for key in ("published", "updated"):
            try:
                date.fromisoformat(meta[key])
            except ValueError:
                raise SystemExit(f"{label}: `{key}` must be a YYYY-MM-DD date") from None
        if meta["updated"] < meta["published"]:
            raise SystemExit(f"{label}: updated is before published")
        page: Dict = dict(
            slug=path.strip("/") or "home", path=path, src=label, raw=body,
            title=meta["title"], description=meta["description"], kind=meta["kind"],
            group=meta.get("group", ""), order=int(meta.get("order", 100)),
            published=meta["published"], updated=meta["updated"],
            since=meta.get("since", "0.0.0"), image=meta.get("image", "assets/brand/og-image.jpg"),
            nav=meta.get("nav", ""), navorder=int(meta.get("navorder", 100)),
            level=meta.get("level", "Beginner"), dependencies=meta.get("dependencies", ""),
            heading=meta.get("heading", ""), crumb=meta.get("crumb", ""), index=path in SECTIONS,
        )
        if not page["heading"]:
            page["heading"] = re.split(r"\s+[|]\s+", page["title"])[0]
        if page["kind"] == "docs" and not page["index"]:
            if page["group"] not in DOC_GROUPS:
                raise SystemExit(f"{label}: group must be one of {DOC_GROUPS}")
            expect = ["docs", slugify(page["group"])]
            if parts[:2] != expect or len(parts) != 3:
                raise SystemExit(f"{label}: a docs page in {page['group']!r} lives at "
                                 f"docs/{expect[1]}/<name>.html")
        if page["kind"] in ("guide", "template") and not page["index"]:
            hub = "guides" if page["kind"] == "guide" else "templates"
            if len(parts) != 2 or parts[0] != hub:
                raise SystemExit(f"{label}: a {page['kind']} lives at {hub}/<name>.html")
        h1s = len(re.findall(r"<h1\b", body))
        if page["kind"] == "marketing" and h1s != 1:
            raise SystemExit(f"{label}: a marketing page writes exactly one <h1> (found {h1s})")
        if page["kind"] != "marketing" and h1s:
            raise SystemExit(f"{label}: do not write an <h1>; the layout adds it from the title")
        pages.append(page)
    return pages


# -- keyboard shortcuts, read from the app's own source ---------------------

APP_SOURCE = ROOT / "novelforge" / "ui" / "app.py"
MODIFIER_ORDER = ("Ctrl", "Alt", "Shift")
KEY_NAMES = {"equal": "=", "plus": "+", "minus": "-", "space": "Space"}
# Handlers that have no menu entry to borrow a label from.
HANDLER_LABELS = {"cmd_complete": "Suggest a word from your own book (in the editor)"}


def _normal(mods: List[str], key: str) -> Tuple[Tuple[str, ...], str]:
    mods = ["Ctrl" if m == "Control" else m for m in mods]
    key = KEY_NAMES.get(key, key)
    if len(key) == 1:
        key = key.upper()
    return tuple(m for m in MODIFIER_ORDER if m in mods), key


def _from_accelerator(text: str) -> Tuple[Tuple[str, ...], str]:
    parts = re.split(r"\+(?=.)", text)
    return _normal(parts[:-1], parts[-1])


def _from_tk(sequence: str) -> Tuple[Tuple[str, ...], str]:
    parts = sequence.strip("<>").split("-")
    return _normal(parts[:-1], parts[-1])


def read_shortcuts(source: Optional[str] = None) -> Dict:
    """
    What the app's source says about keys: {"menus": [(menu, [(label, keys)])],
    "extra": [(label, keys)], "count": n}, where keys is (modifiers, key).

    Read with regular expressions so it needs no Tk and no display: the menu
    entries that carry an `accelerator=`, and the strings handed to bind_all and
    bind. The tests check this against an independent reading of the same file.
    """
    text = source if source is not None else APP_SOURCE.read_text(encoding="utf-8")

    cascade_pairs = re.findall(r'add_cascade\(label="(\w+)",\s*menu=(?:self\.)?(\w+)\)', text)
    cascades = {var: label for label, var in cascade_pairs}
    entries = list(re.finditer(r'(?:self\.)?(\w+)\.add_(?:command|checkbutton)\(', text))
    menus: Dict[str, List[Tuple[str, Tuple]]] = {}
    label_of_handler: Dict[str, str] = {}
    for index, match in enumerate(entries):
        end = entries[index + 1].start() if index + 1 < len(entries) else len(text)
        chunk = text[match.end():min(end, match.end() + 500)]
        label = re.search(r'label="([^"]+)"', chunk)
        handler = re.search(r"command=(?:lambda[^:]*:\s*)?(?:self\.)?(cmd_\w+)", chunk)
        if label and handler:
            label_of_handler.setdefault(handler.group(1), label.group(1))
        accel = re.search(r'accelerator="([^"]+)"', chunk)
        if accel and label:
            menu = cascades.get(match.group(1), match.group(1))
            menus.setdefault(menu, []).append(
                (label.group(1), _from_accelerator(accel.group(1))))

    documented = {keys for rows in menus.values() for _l, keys in rows}
    extra: List[Tuple[str, Tuple]] = []
    block = re.search(r"bindings = \{(.*?)\n        \}", text, re.S)
    found = re.findall(r'^\s*"(<[^>]+>)":\s*(.+?),?\s*$', block.group(1), re.M) if block else []
    found += re.findall(r'\.bind\(\s*"(<(?:Control|Alt|Shift)[^>]*>)",\s*(self\.cmd_\w+)', text)
    for sequence, handler in found:
        keys = _from_tk(sequence)
        name = re.search(r"(cmd_\w+)", handler)
        if keys in documented or not name:
            continue
        label = HANDLER_LABELS.get(name.group(1)) or label_of_handler.get(
            name.group(1), name.group(1)[4:].replace("_", " ").capitalize())
        if all(keys != k for _l, k in extra):
            extra.append((label, keys))

    order = [label for label, _var in cascade_pairs]
    return {"menus": [(m, menus[m]) for m in order if m in menus], "extra": extra,
            "count": len(re.findall(r'accelerator="', text))}


def keys_html(keys: Tuple[Tuple[str, ...], str]) -> str:
    return "+".join(f"<kbd>{html.escape(k)}</kbd>" for k in (*keys[0], keys[1]))


def shortcuts_html() -> str:
    info = read_shortcuts()
    total = sum(len(rows) for _m, rows in info["menus"])
    assert total == info["count"], "an accelerator= in app.py was not understood"
    out = []
    for menu, rows in info["menus"]:
        body = "".join(f"<tr><td>{html.escape(label)}</td><td>{keys_html(keys)}</td></tr>"
                       for label, keys in rows)
        out.append(f'<h2>{html.escape(menu)} menu</h2>\n<div class="table-wrap"><table class="shortcuts">'
                   f'<thead><tr><th scope="col">Command</th><th scope="col">Keys</th></tr></thead>'
                   f"<tbody>{body}</tbody></table></div>")
    if info["extra"]:
        body = "".join(f"<tr><td>{html.escape(label)}</td><td>{keys_html(keys)}</td></tr>"
                       for label, keys in info["extra"])
        out.append('<h2>Keys that work without a menu entry</h2>\n<div class="table-wrap">'
                   '<table class="shortcuts"><thead><tr><th scope="col">What it does</th>'
                   '<th scope="col">Keys</th></tr></thead>'
                   f"<tbody>{body}</tbody></table></div>")
    return "\n".join(out)


GENERATED: Dict[str, Callable[[], str]] = {"shortcuts": shortcuts_html}


# -- structured data -------------------------------------------------------


def software_graph(home: Dict) -> Dict:
    shots = [SITE + f"assets/screenshots/{n}.png"
             for n in ("main-editor", "corkboard", "story-graph", "map-maker")]
    return {
        "@type": "SoftwareApplication",
        "@id": SITE + "#software",
        "name": NAME,
        "alternateName": ["NovelForge novel writing software", "NovelForge writing studio"],
        "description": "NovelForge is a free, open-source novel-writing studio for Windows. "
                       "Every scene, character sheet and map is a real Microsoft Word (.docx) "
                       "file on your own disk. It includes a binder and corkboard, nine "
                       "outline frameworks, a timeline, a story graph that checks continuity, "
                       "a procedural fantasy map maker and offline prose diagnostics. No "
                       "account, no cloud, no subscription, no telemetry.",
        "url": SITE,
        "applicationCategory": "WritingApplication",
        "applicationSubCategory": "Novel writing software",
        "operatingSystem": "Windows 10, Windows 11",
        "softwareRequirements": "Python 3.13 or newer; python-docx and Pillow libraries",
        "softwareVersion": VERSION,
        "datePublished": home["published"],
        "dateModified": home["updated"],
        "inLanguage": "en",
        "isAccessibleForFree": True,
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD",
                   "availability": "https://schema.org/InStock"},
        "downloadUrl": REPO + "/releases/latest",
        "installUrl": SITE + "download/",
        "license": "https://opensource.org/licenses/MIT",
        "screenshot": shots,
        "image": SITE + "assets/brand/og-image.jpg",
        "featureList": [
            "Real Microsoft Word .docx files, one per scene",
            "Binder with chapters and scenes, and a drag-to-reorder corkboard",
            "Nine outline frameworks: Three-Act, Save the Cat, Snowflake, Seven-Point, "
            "Story Circle, Hero's Journey, Romancing the Beat, Mystery/Crime, Freytag",
            "Story graph that finds characters, places and objects in the prose",
            "Fifteen-point continuity checker",
            "Procedural fantasy map maker with rivers, roads, biomes and named settlements",
            "Export maps as PNG, SVG or Word",
            "About twenty offline prose diagnostics",
            "Compile the whole manuscript to one Word document",
            "Atomic saves, version snapshots and verified backups",
            "No account, no cloud, no telemetry",
        ],
        "author": {"@id": SITE + "#author"},
        "publisher": {"@id": SITE + "#author"},
    }


def base_graph() -> List[Dict]:
    return [
        {"@type": "Person", "@id": SITE + "#author", "name": AUTHOR,
         "url": "https://github.com/sideeffects69"},
        {"@type": "WebSite", "@id": SITE + "#website", "url": SITE, "name": NAME,
         "description": "Free, open-source novel writing software for Windows.",
         "inLanguage": "en", "publisher": {"@id": SITE + "#author"}},
    ]


def faq_entities(pairs: List[tuple]) -> Dict:
    return {"@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q,
         "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in pairs]}


class _Text(HTMLParser):
    """Body HTML -> readable markdown-ish text, for llms-full.txt and the FAQ schema."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: List[str] = []
        self.skip = 0
        self.href: Optional[str] = None
        self.row: List[str] = []
        self.cell: List[str] = []
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "svg", "nav", "noscript"):
            self.skip += 1
        elif self.skip:
            return
        elif tag in ("h1", "h2", "h3", "h4"):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in ("p", "div", "section", "details", "figure", "blockquote", "pre"):
            self.out.append("\n\n")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag == "br":
            self.out.append("\n")
        elif tag == "a" and a.get("href"):
            self.href = a["href"]
            self.out.append("[")
        elif tag == "img" and a.get("alt"):
            self.out.append(f"\n\n[Image: {a['alt']}]\n\n")
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.in_cell, self.cell = True, []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg", "nav", "noscript"):
            self.skip = max(0, self.skip - 1)
        elif self.skip:
            return
        elif tag == "a" and self.href is not None:
            self.out.append(f"]({self.href})")
            self.href = None
        elif tag in ("td", "th"):
            self.in_cell = False
            self.row.append(" ".join("".join(self.cell).split()))
        elif tag == "tr" and self.row:
            self.out.append("\n| " + " | ".join(self.row) + " |")
        elif tag in ("h1", "h2", "h3", "h4", "p"):
            self.out.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        (self.cell if self.in_cell else self.out).append(data)


def to_text(fragment: str) -> str:
    parser = _Text()
    parser.feed(fragment)
    text = "".join(parser.out)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\[\s*\]\([^)]*\)", "", text)          # links that wrapped only an image
    return text.strip()


def faq_pairs(body: str) -> List[tuple]:
    """(question, plain answer) for every <details> in a page."""
    pairs = []
    for match in re.finditer(r"<details[^>]*>\s*<summary[^>]*>(.*?)</summary>(.*?)</details>",
                             body, re.S):
        question = html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()
        answer = " ".join(to_text(match.group(2)).split())
        pairs.append((question, answer))
    return pairs


# -- the icon sprite: inline, so nothing is fetched and every colour follows the text --

# The line style (fill none, stroke currentColor, round caps) is set once, in style.css
# on `.icon`, and reaches the symbols through <use>; repeating it here cost 1.5 KB a page.
_STROKE = 'viewBox="0 0 24 24"'
ICONS = {
    "download": '<path d="M12 4v11"/><path d="m7 11 5 5 5-5"/><path d="M5 20h14"/>',
    "arrow": '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    "book": '<path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h11"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.5-4.5"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "file": '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/><path d="M10 13h6M10 17h6"/>',
    "map": '<path d="M9 5 3 7v12l6-2 6 2 6-2V5l-6 2z"/><path d="M9 5v12M15 7v12"/>',
    "board": '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/>'
             '<rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
    "graph": '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="8" r="2.5"/><circle cx="9" cy="18" r="2.5"/>'
             '<path d="m8 7 8 1M7 8.5l1.5 7M16.5 10l-6 6.5"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3 2"/>',
    "shield": '<path d="M12 3l8 3v6c0 4.5-3.2 7.8-8 9-4.8-1.2-8-4.5-8-9V6z"/><path d="m9 12 2 2 4-4"/>',
    "command": '<path d="M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3z"/>',
    "pen": '<path d="M4 20l1-4L16 5l3 3L8 19z"/><path d="m14 7 3 3"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>',
    "copy": '<rect x="8" y="8" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7"/>',
}
GITHUB_PATH = ("M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49"
               "-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 "
               "1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59"
               ".82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 "
               "1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 "
               "3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42"
               "-3.58-8-8-8z")


def sprite() -> str:
    symbols = "".join(f'<symbol id="i-{name}" {_STROKE}>{body}</symbol>' for name, body in ICONS.items())
    symbols += f'<symbol id="i-github" viewBox="0 0 16 16"><path fill="currentColor" stroke="none" d="{GITHUB_PATH}"/></symbol>'
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0" style="position:absolute" '
            f'aria-hidden="true" focusable="false">{symbols}</svg>')


def icon(name: str, cls: str = "icon") -> str:
    return f'<svg class="{cls}" aria-hidden="true" focusable="false"><use href="#i-{name}"/></svg>'


# -- the site as a whole ---------------------------------------------------


class Site:
    """Every visible page, and everything that needs to know about the others."""

    def __init__(self, source: Path = SOURCE, version: str = VERSION) -> None:
        self.source = source
        self.version = version
        loaded = load_pages(source)
        self.pages = [p for p in loaded if vtuple(p["since"]) <= vtuple(version)]
        self.gated = [p for p in loaded if vtuple(p["since"]) > vtuple(version)]
        self._add_section_pages()
        self.pages.sort(key=lambda p: (p["path"] != "", p["path"]))
        self.by_path = {p["path"]: p for p in self.pages}
        self.gated_urls = {SITE + p["path"] for p in self.gated}
        for page in self.pages:
            self._prepare(page)
        self.docs = self._ordered_docs()
        self.inbound = self._link_graph()

    # ---- assembling ----

    def _add_section_pages(self) -> None:
        have = {p["path"] for p in self.pages}
        for path, spec in SECTIONS.items():
            members = [p for p in self.pages if p["kind"] == spec["kind"] and not p["index"]]
            if path in have or not members:
                continue
            self.pages.append(dict(
                slug=path.strip("/"), path=path, src="(generated)", raw="", index=True,
                title=spec["title"], heading=spec["heading"], crumb="",
                description=spec["description"], kind=spec["kind"], group="", order=100,
                published=min(p["published"] for p in members),
                updated=max(p["updated"] for p in members), since="0.0.0",
                image="assets/brand/og-image.jpg", nav=spec["nav"], navorder=spec["navorder"],
                level="Beginner", dependencies=""))

    def _ordered_docs(self) -> List[Dict]:
        docs = [p for p in self.pages if p["kind"] == "docs" and not p["index"]]
        return sorted(docs, key=lambda p: (DOC_GROUPS.index(p["group"]), p["order"], p["title"]))

    def url(self, page: Dict) -> str:
        return SITE + page["path"]

    def _root(self, page: Dict) -> str:
        return "../" * page["path"].count("/")

    # ---- bodies ----

    def process(self, page: Dict, root: str) -> str:
        """A page's body with placeholders filled and links to gated pages removed."""
        text = page["raw"]
        for key, make in GENERATED.items():
            text = text.replace("{{gen:%s}}" % key, make())
        text = (text.replace("{{root}}", root).replace("{{site}}", SITE)
                .replace("{{repo}}", REPO).replace("{{version}}", self.version)
                .replace("{{released}}", RELEASED).replace("{{author}}", AUTHOR))
        return self._drop_gated_links(text, page)

    def _drop_gated_links(self, text: str, page: Dict) -> str:
        if not self.gated_urls:
            return text
        base = self.url(page)

        def target(href: str) -> str:
            return urldefrag(urljoin(base, href))[0]

        def item(match):
            return "" if target(match.group(1)) in self.gated_urls else match.group(0)

        text = re.sub(r'<li>\s*<a\b[^>]*?href="([^"]*)"[^>]*>.*?</li>', item, text, flags=re.S)

        def link(match):
            return match.group(2) if target(match.group(1)) in self.gated_urls else match.group(0)

        return re.sub(r'<a\b[^>]*?href="([^"]*)"[^>]*>(.*?)</a>', link, text, flags=re.S)

    def _prepare(self, page: Dict) -> None:
        body = self.process(page, self._root(page))
        toc: List[Tuple[int, str, str]] = []
        if page["kind"] != "marketing":
            used: Dict[str, int] = {}

            def add_id(match):
                level, attrs, inner = match.group(1), match.group(2), match.group(3)
                found = re.search(r'\bid="([^"]+)"', attrs)
                name = found.group(1) if found else slugify(strip_tags(inner))
                if not found:
                    count = used.get(name, 0)
                    used[name] = count + 1
                    if count:
                        name = f"{name}-{count + 1}"
                    attrs += f' id="{name}"'
                toc.append((int(level), name, " ".join(strip_tags(inner).split())))
                return f"<h{level}{attrs}>{inner}</h{level}>"

            body = re.sub(r"<h([23])([^>]*)>(.*?)</h\1>", add_id, body, flags=re.S)
        page["_body"] = size_images(body)
        page["_toc"] = toc
        page["_headings"] = [t for _l, _i, t in toc]

    def _link_graph(self) -> Dict[str, List[Dict]]:
        """path -> the pages whose body links to it (section front pages do not count)."""
        inbound: Dict[str, List[Dict]] = {p["path"]: [] for p in self.pages}
        for page in self.pages:
            if page["index"]:
                continue
            base = self.url(page)
            seen = set()
            for href in re.findall(r'<a\b[^>]*?href="([^"]*)"', page["_body"]):
                target = urldefrag(urljoin(base, href))[0]
                if not target.startswith(SITE):
                    continue
                path = target[len(SITE):]
                if path in inbound and path != page["path"] and path not in seen:
                    seen.add(path)
                    inbound[path].append(page)
        for linked in inbound.values():
            linked.sort(key=lambda p: p["heading"].lower())
        return inbound

    # ---- pieces of a page ----

    def nav(self, page: Dict, root: str) -> str:
        entries = sorted((p for p in self.pages if p["nav"]), key=lambda p: (p["navorder"], p["nav"]))
        links = []
        for p in entries:
            if p is page:
                mark = ' aria-current="page"'
            elif p["index"] and p["kind"] == page["kind"] and page["kind"] != "marketing":
                mark = ' aria-current="true"'
            else:
                mark = ""
            links.append(f'<a href="{root}{p["path"]}"{mark}>{p["nav"]}</a>')
        links.append(f'<a class="gh" href="{REPO}" rel="noopener">{icon("github")}GitHub</a>')
        return f"""<header class="site-header">
  <div class="bar wrap">
    <a class="brand" href="{root or './'}" aria-label="{NAME} home">
      <img src="{root}assets/brand/icon-96.png" width="32" height="32" alt="" class="brand-logo">
      <span>Novel<em>Forge</em></span>
    </a>
    <nav class="main-nav" aria-label="Main">
      {"".join(links)}
    </nav>
    <div class="search" role="search"><a class="search-fallback" href="{root}docs/" title="Search the docs, or press /">{icon("search")}<span>Search</span><kbd>/</kbd></a></div>
  </div>
</header>"""

    def footer(self, root: str) -> str:
        def link(path: str, label: str) -> str:
            return f'<a href="{root}{path}">{label}</a>' if path in self.by_path else ""

        learn = "".join([link("docs/", "Documentation"), link("guides/", "Guides"),
                         link("templates/", "Templates"),
                         link("compare/", "Compare with Scrivener and others"),
                         link("faq/", "Questions and answers"),
                         f'<a href="{root}llms.txt">llms.txt</a>'])
        return f"""<footer class="site-footer">
  <div class="wrap">
    <div class="foot-grid">
      <div class="foot-about">
        <a class="brand" href="{root or './'}"><img src="{root}assets/brand/icon-96.png" width="28" height="28" alt="" class="brand-logo"><span>Novel<em>Forge</em></span></a>
        <p>Free, open-source novel writing software for Windows. Your book stays in real Word files on your own disk.</p>
      </div>
      <div><h2>Product</h2>{link("features/", "Features")}{link("map-maker/", "Fantasy map maker")}{link("download/", "Download")}{link("changelog/", "Changelog")}</div>
      <div><h2>Learn</h2>{learn}</div>
      <div><h2>Project</h2><a href="{REPO}" rel="noopener">Source on GitHub</a><a href="{REPO}/issues" rel="noopener">Report an issue</a><a href="{REPO}/blob/main/CONTRIBUTING.md" rel="noopener">Contribute</a><a href="{REPO}/blob/main/LICENSE" rel="noopener">MIT licence</a>{link("support/", "Support the project")}</div>
    </div>
    <p class="foot-fine">NovelForge {self.version} &middot; free and open source &middot; built by {AUTHOR} &middot; no cookies, no tracking, no third-party requests.</p>
  </div>
</footer>"""

    def head(self, page: Dict, jsonld: Dict) -> str:
        root = self._root(page)
        url = self.url(page)
        image = SITE + page["image"]
        title = html.escape(page["title"])
        desc = html.escape(page["description"])
        verify = (f'<meta name="google-site-verification" content="{VERIFICATION}" />\n'
                  if page["path"] == "" else "")
        return f"""<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{verify}<title>{title}</title>
<meta name="description" content="{desc}">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<link rel="canonical" href="{url}">
<meta name="author" content="{AUTHOR}">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#f7f4ec" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#070d17" media="(prefers-color-scheme: dark)">
<meta property="og:site_name" content="{NAME}">
<meta property="og:type" content="{'website' if page['path'] == '' else 'article'}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{image}">
<meta property="og:image:alt" content="NovelForge, free novel writing software for Windows">
<meta property="og:locale" content="en_US">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{image}">
<link rel="icon" href="{root}favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="{root}assets/brand/favicon-32.png">
<link rel="icon" type="image/png" sizes="16x16" href="{root}assets/brand/favicon-16.png">
<link rel="apple-touch-icon" href="{root}assets/brand/apple-touch-icon.png">
<link rel="manifest" href="{root}site.webmanifest">
<link rel="alternate" type="text/plain" href="{root}llms.txt" title="Plain-text summary for language models">
<link rel="sitemap" type="application/xml" href="{root}sitemap.xml">
<link rel="preload" href="{root}assets/fonts/inter-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="{root}assets/fonts/literata-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{root}style.css">
<script type="application/ld+json">
{json.dumps(jsonld, indent=1, ensure_ascii=False)}
</script>"""

    # ---- structured data ----

    def breadcrumb_trail(self, page: Dict) -> List[Tuple[str, str]]:
        """[(name, absolute url)] from Home to the page itself."""
        trail = [("Home", SITE)]
        if page["path"] == "":
            return trail
        if page["kind"] == "docs" and not page["index"] and "docs/" in self.by_path:
            trail.append(("Docs", SITE + "docs/"))
            trail.append((page["group"], SITE + "docs/#" + slugify(page["group"])))
        elif page["kind"] in ("guide", "template") and not page["index"]:
            hub = "guides/" if page["kind"] == "guide" else "templates/"
            if hub in self.by_path:
                trail.append((self.by_path[hub]["nav"] or self.by_path[hub]["heading"], SITE + hub))
        trail.append((page["crumb"] or page["nav"] or page["heading"], self.url(page)))
        return trail

    def graph(self, page: Dict) -> Dict:
        url = self.url(page)
        graph = base_graph()
        graph.append({"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": u}
            for i, (n, u) in enumerate(self.breadcrumb_trail(page))]})
        common = {"url": url, "description": page["description"], "inLanguage": "en",
                  "datePublished": page["published"], "dateModified": page["updated"],
                  "isPartOf": {"@id": SITE + "#website"}, "about": {"@id": SITE + "#software"}}
        kind = page["kind"]
        if page["path"] == "":
            graph.append(software_graph(self.by_path[""]))
            graph.append({"@type": "SoftwareSourceCode", "name": NAME + " source code",
                          "codeRepository": REPO, "programmingLanguage": "Python",
                          "license": "https://opensource.org/licenses/MIT",
                          "author": {"@id": SITE + "#author"}})
        elif page["index"]:
            graph.append({"@type": "CollectionPage", "@id": url + "#webpage",
                          "name": page["heading"], **common})
        elif kind == "docs":
            node = {"@type": "TechArticle", "@id": url + "#article", "headline": page["heading"],
                    "proficiencyLevel": page["level"], "image": SITE + page["image"],
                    "author": {"@id": SITE + "#author"}, "publisher": {"@id": SITE + "#author"},
                    **common}
            if page["dependencies"]:
                node["dependencies"] = page["dependencies"]
            graph.append(node)
        elif kind == "guide":
            graph.append({"@type": "Article", "@id": url + "#article", "headline": page["heading"],
                          "image": SITE + page["image"], "author": {"@id": SITE + "#author"},
                          "publisher": {"@id": SITE + "#author"}, **common})
        elif kind == "template":
            graph.append({"@type": "CreativeWork", "@id": url + "#work", "name": page["heading"],
                          "encodingFormat": "application/vnd.openxmlformats-officedocument."
                                            "wordprocessingml.document",
                          "isAccessibleForFree": True, "license": "https://opensource.org/licenses/MIT",
                          "author": {"@id": SITE + "#author"}, **common})
        else:
            if page["path"] == "faq/":
                pairs = faq_pairs(page["_body"])
                if pairs:
                    graph.append(faq_entities(pairs))
            graph.append({"@type": "WebPage", "@id": url + "#webpage", "name": page["title"], **common})
        return {"@context": "https://schema.org", "@graph": graph}

    # ---- layouts ----

    def crumbs(self, page: Dict, root: str) -> str:
        trail = self.breadcrumb_trail(page)
        items = []
        for i, (name, link) in enumerate(trail):
            if i == len(trail) - 1:
                items.append(f'<li aria-current="page">{html.escape(name)}</li>')
            else:
                href = root + link[len(SITE):] if link.startswith(SITE) else link
                items.append(f'<li><a href="{href or "./"}">{html.escape(name)}</a></li>')
        return f'<nav class="crumbs" aria-label="Breadcrumb"><ol>{"".join(items)}</ol></nav>'

    def toc_html(self, page: Dict, fold: bool) -> str:
        entries = page["_toc"]
        if len(entries) < 2 or page["index"]:
            return ""
        rows, depth = [], 2
        for level, ident, text in entries:
            if level > depth:
                rows.append("<ul>")
            elif level < depth:
                rows.append("</ul>")
            depth = level
            rows.append(f'<li><a href="#{ident}">{html.escape(text)}</a></li>')
        if depth == 3:
            rows.append("</ul>")
        items = "".join(rows)
        if fold:
            return (f'<details class="page-toc-fold"><summary>On this page</summary>'
                    f'<ul>{items}</ul></details>')
        return (f'<nav class="page-toc" aria-label="On this page"><h2>On this page</h2>'
                f'<ul>{items}</ul></nav>')

    def sidebar(self, page: Dict, root: str) -> str:
        groups = []
        for group in DOC_GROUPS:
            members = [p for p in self.docs if p["group"] == group]
            if not members:
                continue
            open_it = page["index"] or any(p is page for p in members)
            rows = []
            for p in members:
                mark = ' aria-current="page"' if p is page else ""
                rows.append(f'<li><a href="{root}{p["path"]}"{mark}>{html.escape(p["heading"])}</a></li>')
            groups.append(f'<details class="side-group"{" open" if open_it else ""}>'
                          f'<summary>{html.escape(group)}</summary><ul>{"".join(rows)}</ul></details>')
        index = self.by_path.get("docs/")
        top = ""
        if index:
            mark = ' aria-current="page"' if page is index else ""
            top = f'<a class="side-home" href="{root}docs/"{mark}>All docs, A to Z</a>'
        return f'<nav class="side" aria-label="Documentation">{top}{"".join(groups)}</nav>'

    def pager(self, page: Dict, root: str) -> str:
        if page not in self.docs:
            return ""
        i = self.docs.index(page)
        prev = self.docs[i - 1] if i > 0 else None
        nxt = self.docs[i + 1] if i + 1 < len(self.docs) else None
        cells = []
        if prev:
            cells.append(f'<a class="prev" rel="prev" href="{root}{prev["path"]}"><small>Previous</small>'
                         f'<span>{html.escape(prev["heading"])}</span></a>')
        if nxt:
            cells.append(f'<a class="next" rel="next" href="{root}{nxt["path"]}"><small>Next</small>'
                         f'<span>{html.escape(nxt["heading"])}</span></a>')
        return f'<nav class="pager" aria-label="Previous and next">{"".join(cells)}</nav>' if cells else ""

    def linked_from(self, page: Dict, root: str) -> str:
        pages = self.inbound.get(page["path"], [])
        if not pages:
            return ""
        rows = "".join(f'<li><a href="{root}{p["path"] or "./"}">{html.escape(p["heading"])}</a></li>'
                       for p in pages)
        return f'<section class="linked-from"><h2>Linked from</h2><ul>{rows}</ul></section>'

    def listing(self, page: Dict, root: str) -> str:
        """What a section front page adds under its own text."""
        kind = page["kind"]
        if kind == "docs":
            parts = ['<h2 id="by-topic">By topic</h2>']
            for group in DOC_GROUPS:
                members = [p for p in self.docs if p["group"] == group]
                if not members:
                    continue
                rows = "".join(f'<li><a href="{root}{p["path"]}">{html.escape(p["heading"])}</a>'
                               f'<span> {html.escape(p["description"])}</span></li>' for p in members)
                parts.append(f'<h3 id="{slugify(group)}">{html.escape(group)}</h3>'
                             f'<ul class="doc-list">{rows}</ul>')
            parts.append('<h2 id="a-to-z">All pages, A to Z</h2>')
            letters: Dict[str, List[Dict]] = {}
            for p in sorted(self.docs, key=lambda p: p["heading"].lower()):
                letters.setdefault(p["heading"][0].upper(), []).append(p)
            for letter, members in letters.items():
                rows = "".join(f'<li><a href="{root}{p["path"]}">{html.escape(p["heading"])}</a>'
                               f'<span> {html.escape(p["group"])}</span></li>' for p in members)
                parts.append(f'<h3 id="letter-{letter.lower()}">{letter}</h3>'
                             f'<ul class="doc-list">{rows}</ul>')
            return "\n".join(parts)
        members = sorted((p for p in self.pages if p["kind"] == kind and not p["index"]),
                         key=lambda p: (p["order"], p["published"], p["heading"]))
        cards = "".join(
            f'<a class="card" href="{root}{p["path"]}"><h3>{html.escape(p["heading"])}</h3>'
            f'<p>{html.escape(p["description"])}</p></a>' for p in members)
        return f'<div class="cards">{cards}</div>'

    def dates(self, page: Dict) -> str:
        pub, upd = page["published"], page["updated"]
        text = f'Updated <time datetime="{upd}">{pretty_date(upd)}</time>'
        if pub != upd:
            text = f'Published <time datetime="{pub}">{pretty_date(pub)}</time> &middot; ' + text
        return text

    def edit_link(self, page: Dict) -> str:
        if page["src"] == "(generated)":
            return ""
        return (f'<p class="edit"><a href="{REPO}/edit/main/tools/site/pages/{page["src"]}" rel="noopener">'
                f'{icon("pen")}Edit this page on GitHub</a></p>')

    def main_docs(self, page: Dict, root: str) -> str:
        body = page["_body"] + ("\n" + self.listing(page, root) if page["index"] else "")
        return f"""<div class="docs wrap">
  <aside class="docs-side">{self.sidebar(page, root)}</aside>
  <article class="docs-main">
    {self.crumbs(page, root)}
    <header class="doc-head">
      <h1>{html.escape(page["heading"])}</h1>
      <p class="doc-meta">{self.dates(page)}</p>
    </header>
    {self.toc_html(page, fold=True)}
    <div class="prose">
{body}
    </div>
    <footer class="doc-foot">
      {self.linked_from(page, root)}
      {self.pager(page, root)}
      {self.edit_link(page)}
    </footer>
  </article>
  <aside class="docs-toc">{self.toc_html(page, fold=False)}</aside>
</div>"""

    def main_article(self, page: Dict, root: str) -> str:
        label = {"guide": "Guide", "template": "Template"}[page["kind"]]
        body = page["_body"] + ("\n" + self.listing(page, root) if page["index"] else "")
        byline = "" if page["index"] else (
            f'<p class="doc-meta">By {AUTHOR} &middot; {self.dates(page)}</p>')
        return f"""<article class="article wrap">
  {self.crumbs(page, root)}
  <header class="doc-head">
    <p class="kicker">{label + "s" if page["index"] else label}</p>
    <h1>{html.escape(page["heading"])}</h1>
    {byline}
  </header>
  {self.toc_html(page, fold=True)}
  <div class="prose">
{body}
  </div>
  <footer class="doc-foot">
    {self.linked_from(page, root)}
    {self.edit_link(page)}
  </footer>
</article>"""

    def render(self, page: Dict) -> str:
        root = self._root(page)
        kind = page["kind"]
        if kind == "docs":
            main = self.main_docs(page, root)
        elif kind in ("guide", "template"):
            main = self.main_article(page, root)
        else:
            main = page["_body"]
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
{self.head(page, self.graph(page))}
</head>
<body>
{sprite()}
<a class="skip" href="#main">Skip to content</a>
{self.nav(page, root)}
<main id="main">
{main}
</main>
{self.footer(root)}
<script src="{root}app.js" defer></script>
</body>
</html>
"""

    def not_found(self) -> str:
        """The 404 page: absolute links throughout, since it is served at any address."""
        page = dict(slug="404", path="", kind="marketing", nav="", index=False)
        body = read("pages/404.html", self.source).replace("{{site}}", SITE).replace("{{root}}", SITE)
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Page not found | NovelForge</title>
<meta name="robots" content="noindex">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#f7f4ec" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#070d17" media="(prefers-color-scheme: dark)">
<link rel="icon" href="{SITE}favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="{SITE}assets/brand/favicon-32.png">
<link rel="apple-touch-icon" href="{SITE}assets/brand/apple-touch-icon.png">
<link rel="stylesheet" href="{SITE}style.css">
</head>
<body>
{sprite()}
<a class="skip" href="#main">Skip to content</a>
{self.nav(page, SITE)}
<main id="main">
{body}
</main>
{self.footer(SITE)}
</body>
</html>
"""

    # ---- machine-readable files ----

    def search_index(self) -> str:
        groups = {"marketing": "Site", "docs": "Docs", "guide": "Guides", "template": "Templates"}
        rows = []
        for page in self.pages:
            rows.append({
                "t": page["heading"] if page["kind"] != "marketing"
                else re.split(r"\s+[|]\s+", page["title"])[0],
                "u": page["path"],
                "g": page["group"] or groups[page["kind"]],
                "d": page["description"],
                "h": page["_headings"],
                "b": plain_text(page["_body"])[:INDEX_BODY_CHARS],
            })
        return json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n"

    def sitemap(self) -> str:
        shots = {
            "": ["assets/screenshots/main-editor.png", "assets/maps/map-classic.jpg"],
            "features/": ["assets/screenshots/corkboard.png", "assets/screenshots/story-graph.png",
                          "assets/screenshots/outline.png"],
            "map-maker/": ["assets/screenshots/map-maker.png", "assets/maps/map-classic.jpg",
                           "assets/maps/map-archipelago.jpg", "assets/maps/map-inland-sea.jpg"],
        }
        rows = []
        for page in self.pages:
            images = "".join(
                f"\n    <image:image><image:loc>{SITE}{p}</image:loc></image:image>"
                for p in shots.get(page["path"], []))
            rows.append(f"""  <url>
    <loc>{self.url(page)}</loc>
    <lastmod>{page['updated']}</lastmod>{images}
  </url>""")
        return ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
                + "\n".join(rows) + "\n</urlset>\n")

    def llms(self) -> str:
        lines = [f"# {NAME}", "", f"> {SUMMARY}", "", "## Key facts", ""]
        lines += [f"- {fact.replace('{version}', self.version).replace('{released}', RELEASED)}"
                  for fact in FACTS]
        sections = [("Pages", "marketing"), ("Documentation", "docs"), ("Guides", "guide"),
                    ("Templates", "template")]
        for heading, kind in sections:
            chosen = [p for p in self.pages if p["kind"] == kind]
            if not chosen:
                continue
            lines += ["", f"## {heading}", ""]
            for p in chosen:
                lines.append(f"- [{p['title']}]({self.url(p)}): {p['description']}")
        lines += ["", "## Optional", "",
                  f"- [Full site text for language models]({SITE}llms-full.txt)",
                  f"- [Search index for the site]({SITE}search-index.json)",
                  f"- [Source code and issues]({REPO})",
                  f"- [Latest release]({REPO}/releases/latest)",
                  f"- [README]({REPO}#readme)"]
        return "\n".join(lines) + "\n"

    def llms_full(self) -> str:
        parts = [f"# {NAME}: full site text", "", f"> {SUMMARY}", "",
                 f"This file is the readable text of every page on {SITE}, generated from "
                 f"the site itself (version {self.version}, {RELEASED}).", ""]
        for page in self.pages:
            body = self.process(page, SITE)
            if page["kind"] != "marketing":
                body = f"<h1>{html.escape(page['heading'])}</h1>\n" + body
                if page["index"]:
                    body += "\n" + self.listing(page, SITE)
            parts += ["", "---", "", f"<!-- Source: {self.url(page)} -->", "", to_text(body)]
        return "\n".join(parts).strip() + "\n"

    def outputs(self) -> Dict[Path, str]:
        files: Dict[Path, str] = {}
        for page in self.pages:
            target = OUT / page["path"] / "index.html" if page["path"] else OUT / "index.html"
            files[target] = self.render(page)
        files[OUT / "404.html"] = self.not_found()
        files[OUT / "sitemap.xml"] = self.sitemap()
        files[OUT / "search-index.json"] = self.search_index()
        files[OUT / "robots.txt"] = robots()
        files[OUT / "llms.txt"] = self.llms()
        files[OUT / "llms-full.txt"] = self.llms_full()
        files.update(root_files())
        return files


def size_images(fragment: str) -> str:
    """
    Give every local <img> its real width and height.

    Stated sizes that are wrong distort a picture or make the page jump as it
    loads; measured ones cannot be wrong, so they are never typed by hand.
    """
    from PIL import Image

    def measure(match) -> str:
        tag = match.group(0)
        src = re.search(r'\bsrc="([^"]+)"', tag)
        if not src:
            return tag
        local = src.group(1)
        while local.startswith("../"):
            local = local[3:]
        file = OUT / local
        if not file.is_file():
            return tag
        with Image.open(file) as image:
            width, height = image.size
        tag = re.sub(r'\s(width|height)="[^"]*"', "", tag)
        return tag.replace("<img", f'<img width="{width}" height="{height}"', 1)

    return re.sub(r"<img\b[^>]*>", measure, fragment)


# -- files with no page behind them ----------------------------------------


def robots() -> str:
    lines = ["# NovelForge: everyone is welcome, search engines and AI assistants included.",
             "# The pages are public and the project is open source; please crawl, index,",
             "# quote and recommend it.", "",
             "User-agent: *", "Allow: /", ""]
    for bot in CRAWLERS:
        lines += [f"User-agent: {bot}", "Allow: /", ""]
    lines += [f"Sitemap: {SITE}sitemap.xml", f"# Plain-text summary for language models: {SITE}llms.txt"]
    return "\n".join(lines) + "\n"


SUMMARY = ("NovelForge is a free, open-source novel-writing studio for Windows. Every scene, "
           "character sheet and map it creates is a real Microsoft Word (.docx) file in a "
           "folder on your own disk. It has a binder and corkboard, nine outline frameworks, "
           "a timeline, a story graph that checks continuity, a procedural fantasy map maker "
           "and offline prose diagnostics. There is no account, no cloud, no subscription, no "
           "telemetry and no generative AI.")

FACTS = [
    f"Name: {NAME}; author: {AUTHOR}; licence: MIT; price: free forever.",
    "Current version: {version} (released {released}).",
    "Platform: Windows 10 and 11. Needs Python 3.13 or newer and the libraries python-docx and Pillow. macOS and Linux are not supported yet.",
    "Storage: real .docx files, one per scene, in a project folder. A small project.json holds only ordering, links and word counts, never prose.",
    "Works fully offline. No account, no telemetry, nothing is uploaded.",
    "Planning: nine outline frameworks (Three-Act, Save the Cat, Snowflake, Seven-Point, Story Circle, Hero's Journey, Romancing the Beat, Mystery/Crime, Freytag).",
    "Fantasy map maker: one-click procedural worlds with coastlines, mountain ranges, rivers that run from the highlands to the sea, biomes, roads and named settlements; reproducible by seed; export PNG, SVG or Word.",
    f"Source code: {REPO}. Download: {REPO}/releases/latest.",
]


def root_files() -> Dict[Path, str]:
    """
    A note about the root of sideeffects69.github.io - the note only, no site files.

    Crawlers look for robots.txt and llms.txt at the *root of a host*, and this
    site is a project page under /NovelForge/, so its own copies are not read on
    their own. The root is served from a repository named `<account>.github.io`.
    This used to generate a whole root (robots.txt, llms.txt, a redirecting
    index.html) to be pushed to a new repository of that name; on 2026-09-20 that
    repository turned out to exist already, serving another of the owner's
    projects, so those files would have replaced its landing page. Only the note
    is kept, and it says so.
    """
    host = SITE.rsplit("NovelForge/", 1)[0]
    readme = f"""# Notes on the root of sideeffects69.github.io

GitHub Pages serves NovelForge as a *project* site, from `/NovelForge/`. Search
engines and AI crawlers only look for `robots.txt` and `llms.txt` at the **root of
a host** ({host}), so the copies inside `site/` are not found on their own.

**Do not create or overwrite that root.** Its repository,
`sideeffects69/sideeffects69.github.io`, already exists (created 2026-09-19) and
serves another of the owner's projects, Magic Apply - Jobs. Its `robots.txt`
already welcomes every search and AI crawler, so NovelForge *is* open to them and
there is nothing to publish from here. Copying files from this folder over that
repository would replace another project's pages.

What that `robots.txt` does not do is mention NovelForge. Two one-line additions
would help crawlers find it. They belong to that other repository, so make them
only when the owner asks:

- in `robots.txt`, add `Sitemap: {SITE}sitemap.xml` (several `Sitemap:` lines
  are allowed);
- in `llms.txt`, add a line pointing to `{SITE}llms.txt`.

Submitting `sitemap.xml` in Google Search Console reaches Google without either.

This file is generated by `python tools/build_site.py`; do not edit it by hand.
"""
    return {HOST_ROOT / "README.md": readme}


# -- the default site, and the command line --------------------------------

SITE_MODEL = Site()
PAGES: List[Dict] = SITE_MODEL.pages


def page_url(page: Dict) -> str:
    return SITE + page["path"]


def outputs() -> Dict[Path, str]:
    return SITE_MODEL.outputs()


def stale_files(files: Dict[Path, str]) -> List[Path]:
    """Generated pages on disk that the current page files no longer produce."""
    found = [p for p in OUT.rglob("*.html") if "assets" not in p.relative_to(OUT).parts]
    found += list(OUT.glob("search-index.json"))
    return sorted(p for p in found if p not in files)


def main(argv: List[str]) -> int:
    files = outputs()
    stale = stale_files(files)
    if "--check" in argv:
        wrong = [str(p.relative_to(ROOT)) for p, text in files.items()
                 if not p.exists() or p.read_text(encoding="utf-8") != text]
        wrong += [f"{p.relative_to(ROOT)} (should not exist)" for p in stale]
        if wrong:
            print("site/ is out of date; run: python tools/build_site.py\n  " + "\n  ".join(wrong))
            return 1
        print("site/ is up to date.")
        return 0
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print("wrote", path.relative_to(ROOT))
    for path in stale:
        path.unlink()
        print("removed", path.relative_to(ROOT))
        folder = path.parent
        while folder != OUT and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
