# NovelForge website: research and redesign proposal (2026-09-20)

Real fetches were made on 2026-09-20; "(unverified)" marks anything not confirmed by a fetch. No code was changed.

## Summary

1. The site is honest, fast and well tested, but it is eight marketing pages and nothing else. The biggest gap is **documentation and guides**: nothing can rank for "how to" queries, and an AI assistant has nothing to cite about how NovelForge works.
2. What measurably helps in 2026 is ordinary: static text, named crawlers allowed, real dates, fast pages, and being **mentioned by third-party roundups**. `llms.txt`, FAQ markup and "AI-only" tricks are folklore (data below).
3. Concrete defects to fix first: the primary button fails contrast (2.93:1), Google Fonts contradict "no tracking", every `lastmod` is the release date, and the home page repeats the features and FAQ pages.
4. Proposal: keep the brand, add light and dark, a docs section modelled on Obsidian's help (sidebar, contents, search over a generated index, under 10 KB of JS), 12 real guides (four written first), downloadable .docx outline templates, and a `/word-files/` page for our one unique claim. Docs for unfinished 2.3 features are gated by a `since` version so they cannot go live early.

## 1. Benchmark

"HTML" is compressed bytes of the document only, measured with curl.

| Site | Hero (verbatim) and IA | Proof of quality | Weight and JS |
|---|---|---|---|
| obsidian.md | "Sharpen your thinking." / "The free and flexible app for your private thoughts." OS-detected "Get Obsidian for Windows". Nav is five items: Download, Pricing, Sync, Publish, Enterprise | No logo wall. A privacy block ("No one else can read them, not even us"), plugin count, the Help site itself. About page is a five-word manifesto (Yours, Durable, Private, Malleable, Independent: "supported by our users, not investors") | 20 KB HTML, 9 scripts, no JSON-LD, no llms.txt |
| obsidian.md/download, /changelog | Download is a bare per-OS list. Changelog is dated weekly, split Desktop/Mobile/Early access, headings "New", "Improvements", "No longer broken" | Real dates; no screenshots | small |
| obsidian.md/help (was help.obsidian.md, now a 301) | Landing groups: Get started, Extend Obsidian, Add-on services, Contribute. Source repo folders: Getting started, User interface, Editing and formatting, Linking notes and files, Files and folders, Import notes, Plugins, Sync, Publish and others. Pages open "Learn how to ...", then task headings, code, note/tip/warning callouts, screenshots. Publish adds backlinks, hover previews, graph; its built-in search UI was not inspected (unverified) | Public repo anyone can fix | Browser gets a 1 KB shell that boots `app.js`; Googlebot and GPTBot user agents get about 5 KB (title and bootstrap data, not the article) |
| Scrivener (literatureandlatte.com) | "See the forest or the trees." Nav: Products, Community, Store, Help | Forum, blog, free webinars; no numbers | 28 KB, 53 scripts, JSON-LD |
| atticus.io | "Write and Format Stunning Books"; header is just Log In and Buy Now ($147) | Six named author quotes, 30-day guarantee, a table against Vellum with numbers (1,500+ fonts) | 28 KB, 41 scripts, 97 images |
| ulysses.app | "The Ultimate Writing App for Mac, iPad and iPhone" | Two Apple Design Awards, press logos, three creator stories | 10 KB, 7 scripts |
| linear.app | "The product development system for teams and agents"; screenshots sit inside the feature they explain | "Powers over 40,000 product teams", three quotes under 125 characters | 174 KB, 183 scripts (Next.js), but has llms.txt and a `.md` copy of each docs page |
| zettlr.com (open-source writing app, closest peer) | "Your One-Stop Publication Workbench"; leads with "Privacy First: no cloud sync or telemetry" | 40+ named universities; donations | 11 KB, 16 scripts |
| docs.zettlr.com | Sidebar groups: Getting started, First Time Users, Interface, Writing, Guides, Reference; Ctrl/Cmd+K search, "on this page" contents, previous/next, Edit on GitHub, 8 languages | The docs are the proof | 9 KB, 4 scripts (VuePress) |
| Us | "Free novel writing software that keeps your book in real Word files" | Honesty | 8 KB, one external script |

Lessons:

1. **Local-first tools sell one sentence about ownership and show the file format.** "Your novel is just Word files" is our equivalent and deserves its own section and page.
2. **Docs are a product surface.** Obsidian and Zettlr both have a sidebar tree, contents list, cross-links and an editable source. We have no documentation at all.
3. **For a free tool, proof is transparency:** a dated changelog, the source, real screenshots, a "what it does not do" list. No logos, ratings or quotes we cannot honestly show.
4. **Weight does not track quality** (20 KB to 174 KB). We are at the light end; keep it.
5. **Copy Obsidian's docs design, not its implementation.** Its help site sends crawlers almost no article text. Ours must be pre-rendered static HTML, with search as an enhancement.
6. Cheap wins: Obsidian's friendly "No longer broken"; Linear's per-page `.md`; Zettlr's "Edit on GitHub"; a static "Linked from" list (Obsidian's backlinks) built at generation time.

## 2. Search and answer-engine optimisation in 2026

### What measurably helps

1. **Plain server-rendered text.** Vercel's crawler analysis: no major AI crawler (OAI-SearchBot, ChatGPT-User, GPTBot, ClaudeBot) renders JavaScript; ChatGPT spent 34.8% of fetches on 404s. We are static; keep pages complete without scripts and never rename URLs (GitHub Pages cannot redirect).
2. **Allow the right bots.** OpenAI: OAI-SearchBot controls inclusion in ChatGPT search; GPTBot is training only; ChatGPT-User is user-triggered, robots.txt "may not apply"; changes take about 24 hours. Anthropic: ClaudeBot (training), Claude-SearchBot (search), Claude-User (fetches). Perplexity: allow PerplexityBot; Perplexity-User generally ignores robots.txt. Our robots.txt names them all.
3. **Ordinary SEO is the AI-search strategy.** Google: "There are no additional requirements to appear in AI Overviews or AI Mode"; no new files, AI text files or special schema; crawlable, internally linked, text content, structured data matching visible text.
4. **People-first, signed, dated content.** Google's who/how/why test; it warns against publishing lots of pieces in the hope some rank, and against changing dates without real updates.
5. **Core Web Vitals:** LCP 2.5 s, INP 200 ms, CLS 0.1 at the 75th percentile (web.dev). Lighthouse's new Agentic Browsing category (13.3.0, May 2026, per secondary reports) audits CLS, the accessibility tree, WebMCP and an optional llms.txt.
6. **Bing and Copilot.** Bing Webmaster Tools' AI Performance report (11 Feb 2026) shows citations and grounding queries; Bing's advice: clear headings, tables, FAQ sections, cited examples, freshness, IndexNow.
7. **Being named elsewhere.** A synthesis of six citation studies (5WPR, a PR firm: directional only) has Reddit and Wikipedia dominating and only about 11% of domains cited by both ChatGPT and Perplexity. Every result for our target queries is a third-party roundup. Inclusion in those lists beats any markup, and it is outreach, not code.
8. **Concrete, sourced facts.** The GEO paper (KDD 2024) reports up to a 40% visibility gain on its benchmark, varying by domain (abstract only read; methods unverified).

### Folklore or weak

- **llms.txt.** Proposed Sept 2024; llmstxt.org v2 (Aug 2026) says labs publish their own, and I confirmed stripe.com, vercel.com, linear.app, developers.openai.com and platform.claude.com do, while obsidian.md, Scrivener, Ulysses and Zettlr return 404. Ahrefs (137,210 domains, May 2026): 28% have one, **97% got zero requests that month**, no AI bot looked for a missing one, no link to AI citations. Google staff say it is not used for search (secondary, 2025). Keep our free one; do not invest.
- **FAQ and HowTo markup.** Google stopped showing FAQ rich results on 7 May 2026 (markup harmless, no effect); HowTo since 2023. Keep visible FAQs for readers and Bing; add no HowTo.
- **SoftwareApplication stars.** Google's Software app result requires `aggregateRating` or `review`. We will never qualify honestly; the markup is for clarity only.
- **"AI markup", hidden bot text, keyword-stuffed "GEO" copy, date-bumping, word-count targets:** undocumented by any provider.

### Target queries: intent and answering page

| Query | Intent; who ranks now | Our page | Odds |
|---|---|---|---|
| free novel writing software | Compare; roundups (Write Practice, Kindlepreneur, Reedsy), Reedsy Studio, Novlr | Home plus honest roundup `/compare/free-novel-writing-software/` | Slow; win through lists |
| Scrivener alternative for Windows | Compare; Dabble, Novel Factory, Storyflow, AlternativeTo | `/compare/scrivener-alternative/` (Scrivener runs on Windows too; say so) | Moderate |
| fantasy map maker for authors | Compare; Book Designer, Reedsy, Azgaar, Nortantis, Inkarnate | `/map-maker/` | Moderate |
| novel outline templates | Wants a download; Bransford, Novel Factory, WordLayouts | `/templates/` with real .docx files | Good |
| how to plan a novel | Learn; blogs | `/guides/how-to-plan-a-novel/` | Slow |
| how to draw a fantasy map for a book | Tutorial; Medium, Instructables, Inksorcery | `/guides/how-to-draw-a-fantasy-map/` | Good with strong images |
| novel writing software that saves to Word docx | Specific need; only generic lists match | `/word-files/` | Best; our unique claim |

## 3. Audit of our site

**Keep:** the honesty (comparison with "when to pick something else", "See vendor", no ratings, test-enforced); static pages that work without JavaScript; one h1, alt text and measured image sizes (no layout shift); canonical/OG/JSON-LD graph, named-bot robots.txt, llms.txt; claim-versus-code tests; brand tokens and window-chrome screenshots.

**Fix:**
1. **No documentation or guides.** Nothing can rank for "how to" queries and an assistant asked "how do I do X in NovelForge" has nothing to cite. Largest gap.
2. **One comparison page for four rivals;** "Scrivener alternative for Windows" has no page.
3. **Repetition.** Home repeats features, seven comparison rows, seven FAQ entries (FAQPage data on two pages) and the install steps; every page ends in a similar CTA band.
4. **False freshness.** Every sitemap `lastmod` and JSON-LD `dateModified` is the release date, and we emit `priority` and `changefreq`, which Google ignores. Google uses `lastmod` only if "consistently and verifiably" accurate.
5. **Third-party fonts** (Google Fonts) on every page, while the footer says "no cookies, no tracking".
6. **Contrast failure:** the primary button is white on `#2b9cf4`, **2.93:1**, under the 4.5:1 AA minimum (WCAG formula, computed).
7. **Dark only,** no `prefers-color-scheme`; long reading pages want light.
8. **Unicode glyph icons** (◆ ⛨ ⬇) render as emoji or tofu on some systems.
9. **No visible author or About page;** the author is only in JSON-LD.
10. **One social image** on 6 of 8 pages; changelog lists "The website" as a product change.
11. **The install (Python, zip, .bat) is the leakiest step;** a short screen recording would help (assumption).
12. **Test gaps:** page weight, third-party requests, contrast, `lastmod` honesty, orphan pages, shortcut table versus the 32 `accelerator=` strings in `ui/app.py`.

## 4. Proposal

Three page families: **marketing** (convince in ten seconds), **docs** (what an assistant cites about the product), **guides and templates** (the only pages that can win queries not containing our name). All generated static HTML: no cookies, analytics or third-party requests.

### 4a. Site map

Nav (7): Features, Docs, Guides, Map Maker, Compare, Download, GitHub. Footer: Templates, FAQ, Changelog, About, Support, llms.txt. **Keep every current URL** and fix the scheme now. P1 ships with 2.3.

| URL | Purpose and target query | H2 outline |
|---|---|---|
| `/` P1 | Convert; "novel writing software that saves to Word docx" | Hero (H1 unchanged) with screenshot; At a glance (free, MIT, Windows 10/11, offline, version and date); One window, everything (bento); Your novel is just Word files; Maps; Versus Scrivener, Atticus, Obsidian (3 rows); Four steps; Four questions |
| `/features/` P1 | Hub linking to docs | Write; Plan; Understand; Build worlds; Compile; Protect; What it does not do |
| `/word-files/` P1 new | "saves to Word docx" | What real Word files means (text folder listing); Edit in Word, press F2; Bring in a manuscript; Compile; Why not a database; What you give up |
| `/map-maker/` P1 | "fantasy map maker for authors" | One-click worlds; Draw by hand; Pins linked to Location sheets; Map kinds (only shipped ones); Export; Versus web map makers, honestly; Guides |
| `/compare/`, `/compare/scrivener-alternative/` P1 new | "Scrivener alternative for Windows" | Who should stay; What we do differently; What you lose (no .scriv import, no iOS, no ebook compile); Moving via .docx |
| `/compare/free-novel-writing-software/` P2 | "free novel writing software" | Selection rules; eight options with us last; table; how to choose |
| `/templates/`, `/templates/<framework>/` P2 (three first) | "novel outline templates"; real .docx from the app's own outline writer | The beats (table); a filled example; Download .docx; Use it in NovelForge |
| `/download/`, `/faq/`, `/changelog/`, `/support/` | Keep; dedupe home; changelog "New / Better / No longer broken", no website entries | as now |
| `/about/` P1 new | The visible byline Google's "who" test wants | Why this exists; Who; Principles in our own words; Funding; What it will not do; Contribute |

**Docs** at `/docs/<group>/<slug>/`: 24 pages in P1, about 40 at full build. Each opens "Learn how to ...", then task headings, callouts, one screenshot, Related, and a static "Linked from" list.

| Group | Pages |
|---|---|
| Getting started | Install and first launch; Create your first novel; Tour of the window; Upgrade and move PCs |
| Writing | Binder; Editor; Scene inspector; Find and replace; Spelling, grammar, your vocabulary; Themes and distraction-free; Counts, targets, sprints |
| Planning | Outline frameworks (nine); Corkboard; Timeline and invented calendars; Characters and locations; Relationship web |
| Understanding | Story graph; Continuity checker (15 points); Prose diagnostics; **on release of 2.3:** Mentions and backlinks; Plot canvas; Quick switcher |
| Maps | Overview; Generate a world; Draw by hand; Link pins; Export; **2.3:** Town, dungeon, star maps; Realm maps; Travel time |
| Your files | Folder on disk; Round-tripping with Word; Import loose .docx; Compile; Backups and snapshots; Crash recovery; Undo |
| Reference | Keyboard shortcuts (generated); Command palette; Settings; Troubleshooting |

**Guides** (`/guides/<slug>/`, signed, dated, 1,200 to 2,000 words; write the first four first):
1. `how-to-plan-a-novel` (pillar): premise, structure, cast, world, scene list; plotter versus pantser without dogma.
2. `how-to-draw-a-fantasy-map`: scope, believable coastlines, rivers run downhill to the sea, mountain chains, names, scale; hand-drawn versus generated.
3. `plan-a-novel-with-a-beat-sheet`: beats in plain words, a worked example, when it hurts.
4. `standard-manuscript-format-in-word`: what agents expect and how Compile produces it (cite a named public source).
5. `three-act-structure-for-novels`; 6. `how-to-outline-a-novel` (snowflake, beat sheet, scene list compared); 7. `story-bible-for-a-fantasy-novel`; 8. `keep-continuity-in-a-long-novel`; 9. `timelines-and-invented-calendars`; 10. `how-to-back-up-your-novel` (3-2-1, OneDrive conflict pitfalls); 11. `moving-from-scrivener-to-word-files`; 12. `travel-time-on-a-fantasy-map` (cited speeds; only after the tool ships).

Each ends with one relevant, honest tie-in, not a sales band.

### 4b. Design direction

Keep navy `#070d17`, blue `#2b9cf4`/`#56c8ff`, ivory `#f4f1e8`, Literata and Inter, window-chrome shots. Change:
- **Light and dark from the OS** (`prefers-color-scheme`, `color-scheme`, two `theme-color`s). Light: ivory `#f7f4ec` page, white cards, navy `#0a1220` text (17.1:1), links `#176fc1` (4.7:1). `#2b9cf4` on ivory is 2.7:1: fills and rings only.
- **Primary button:** navy on `#2b9cf4` (6.64:1) or white on `#176fc1` (5.15:1). `--text-disabled` (3.15:1) never carries content.
- **Type:** ratio 1.2, fluid `clamp()`; body 17 to 18px at 68 to 72 characters, line height 1.65; H1 `clamp(2rem, 1.3rem + 3vw, 3.4rem)`. Spacing tokens on a 4px grid; sections `clamp(3rem, 6vw, 6rem)`; 16px phone gutters.
- **Hero:** left-aligned H1 and one sentence, two buttons (Download, Read the docs), a five-fact strip, a real screenshot in window chrome, light or dark via `<picture media>`. No badge pills or round-number stat bar.
- **Bento grid,** 8 mixed tiles (Binder and editor wide, Map tall with a real map, Corkboard, nine frameworks as chips, Story graph, Timeline, Backups, Palette), each one link to its docs page; CSS grid only.
- **"Just Word files":** a real text folder listing in `<pre>` beside a Word screenshot of the same scene. Verify names against `Project.create()` (scenes are `01-02 Title.docx`).
- **Gallery:** four themes, three or four maps, plain links to full images. **Comparison:** 3 rows on home, full tables on compare pages, each stamped "checked 2026-09-20", sticky first column on phones.
- **Docs layout:** 250px sidebar (`<nav aria-label>`, `<details>` groups, `aria-current`), article 72ch, 200px "On this page", breadcrumbs, updated date, previous/next, Edit on GitHub, callouts, `kbd`. Under 1100px contents fold into `<details>`; under 800px so does the sidebar.
- **Accessibility and motion:** skip link (exists), 2px focus ring at 3:1 in both schemes, 44px touch targets, reduced motion honoured. **Drop scroll-reveal:** content invisible until scripted conflicts with "nothing hidden without JS" and costs bytes.
- **Icons:** inline SVG sprite (about 12, under 3 KB). **Fonts:** self-host Latin-subset variable woff2 of Inter and Literata (both SIL OFL, licence unverified), `font-display: swap`, budget 100 KB (subset sizes unmeasured).

### 4c. JavaScript: under 10 KB, no framework, nothing depends on it

One hand-written `app.js` (target 6 KB): (1) **search**: on first focus fetch `search-index.json`, AND-match with title and heading weights, top 8, arrows, Enter, Esc, `/` and Ctrl+K; injected by JS; without JS the sidebar links "All docs A to Z" (`/docs/`, a full static index that also serves crawlers). (2) **Scroll-spy** for the contents, via one IntersectionObserver. (3) **Copy buttons** on code. Menus are `<details>`. Index entry `{t,u,g,d,h[],b}`; about 60 pages is roughly 60 KB raw, 15 to 20 KB gzipped (estimate, unverified), fetched only on use.

### 4d. Structured data, budgets, linking

One `@graph` script per page (the existing test expects one).

| Page kind | Nodes |
|---|---|
| Home | WebSite, Person, SoftwareApplication (no rating), SoftwareSourceCode, BreadcrumbList; drop FAQPage |
| Docs | TechArticle (`proficiencyLevel`, `dependencies` when real), true dates, `isPartOf`, `about` |
| Guide | Article with Person author, dates, image; no HowTo |
| Template | CreativeWork or DigitalDocument (`encodingFormat`, `isAccessibleForFree`, `license`) |
| Compare | Article plus ItemList of SoftwareApplication (name, url, OS only) |
| FAQ, About | FAQPage (for readers and Bing); AboutPage |

No Review, AggregateRating, testimonials or `speakable`.

**Budgets, enforced by tests:** HTML 30 KB gz per page, CSS 30 KB, JS 10 KB, fonts 100 KB, zero third-party requests, hero image 150 KB (WebP via Pillow; unmeasured), every image with width, height, alt. Phone targets: LCP under 2.0 s, INP under 100 ms, CLS 0. WCAG 2.2 AA in both schemes.

**Linking:** hub and spoke; every docs page has 2 to 4 Related links, previous/next and a feature-tile inbound link; every guide links 2 to 3 docs pages and a template or map; docs reachable from `/docs/` in one click, from home in two; no orphans; descriptive link text.

### 4e. Screenshots (demo novel "Ashfall Crown" only, premium theme for dark, light theme for light)

- **Have:** main-editor, corkboard, outline, story-graph, dashboard, command-palette, map-maker.
- **Light twins:** `main-editor-light`, `map-maker-light`, `corkboard-light`.
- **New, shipped features:** `binder-context-menu`, `inspector-fields`, `timeline`, `relationship-web`, `diagnostics-report`, `compile-dialog`, `backups-dialog`, `themes-grid`, `sprint-timer`, `distraction-free`, `spelling-marks`.
- **Word round trip:** `word-scene-side-by-side`, `folder-in-explorer` (real OS captures).
- **2.3, capture only from merged builds:** `quick-switcher`, `mentions-panel` (a character and the scenes naming them), `plot-canvas`, `map-town`, `map-dungeon`, `map-starmap`, `map-realms` (political borders), `travel-time` (route, distance, days).
- **Guides:** existing three map JPEGs plus one per art style and a "same seed, three styles" strip.
- **Social cards** 1200x630, one per section, generated by `tools/site_assets.py`.

### 4f. Changes to `tools/build_site.py` and `tests/test_site.py`

**Generator:**
1. Replace flat `PAGES` with page files carrying an HTML-comment front matter (`title, description, kind, group, order, published, updated, since, image`) and nested paths.
2. **`since` gate:** pages whose `since` exceeds `VERSION` are neither built nor listed, so 2.3 docs can be written now and appear on release.
3. Layouts per kind (docs, guide, marketing); auto ids on h2/h3 for the contents; static "Linked from" lists.
4. Emit `search-index.json` and `/docs/` A to Z; `lastmod` from `updated` (drop `priority`, `changefreq`); true JSON-LD dates; `llms.txt` gains Docs, Guides, Templates sections.
5. Self-hosted fonts, colour-scheme meta, SVG sprite; remove Google Fonts.
6. Shortcuts page generated by regex over `accelerator=` in `ui/app.py` (no Tk needed).
7. Optional `.md` twin per docs page.

**New tests (each mutation-checked, as CLAUDE.md requires):** no third-party origin; byte budgets; every docs page in the sidebar once, no orphans, closed prev/next chain; `lastmod` equals `updated` and dates differ; search index parses, covers every page, within budget; contrast computed from the CSS variables in both schemes; shortcuts page equals the code; guides have byline, dates, 900+ words, an image with alt, and no percentage without an adjacent source link; JSON-LD kind per page; nothing with `since` above `VERSION` in any output. Keep all current checks and the Google verification tag.

### Suggested order of work

1. **Small fixes, no new pages:** button contrast, self-hosted fonts, honest `lastmod`, dedupe home and FAQ, per-section social images, dated compare cells.
2. **Docs machinery:** front matter, `since` gate, docs layout, contents, "Linked from", search index and `app.js`, new tests.
3. **Docs content with 2.3:** the 24 P1 pages, screenshots from the merged build, the generated shortcuts page.
4. **`/word-files/`, `/about/`, `/compare/scrivener-alternative/`.**
5. **Four guides, then templates,** then the free-software roundup and the remaining guides.
6. Submit the sitemap in Search Console and Bing Webmaster Tools; list on AlternativeTo; run the quarterly query check.

### 4g. Risks

1. **Scope:** 8 pages become about 45. Phase it, keep sources plain HTML, write docs in the release branch.
2. **Thin or machine-written guides** are what Google's scaled-content guidance warns about. Four excellent, signed, sourced guides first; any "we tested N maps" line must be a test we really ran.
3. **Documenting unshipped features:** the `since` gate; screenshots from merged builds only.
4. **Stale competitor facts:** "See vendor", dated cells, quarterly review. I did not verify Atticus's offline behaviour or current Scrivener prices.
5. **Host-root problem stands:** robots.txt and llms.txt are read only at the root, which belongs to Magic Apply. Rely on Search Console and Bing Webmaster Tools (it can import the Google property). Whether an IndexNow key file may live under `/NovelForge/` is unverified.
6. **Off-site mentions are the biggest lever and are not code.** AlternativeTo and GitHub topics are legitimate; promotional forum posts risk bans. Owner's call; no astroturfing.
7. **The install is the real barrier;** copy cannot fix Python plus zip plus .bat.
8. **No analytics by promise:** measure with Search Console, Bing impressions and a quarterly manual check of the seven queries in ChatGPT, Perplexity, Claude and Google, logged here.
9. **GitHub Pages limits:** no redirects or headers, path prefix; keep `{{root}}` templating.
10. **Automated accessibility checks are not a screen-reader pass;** do one by hand.

## Sources

- https://obsidian.md/ , /download , /about , /changelog , /help/ , /help/links , /publish
- https://github.com/obsidianmd/obsidian-help/tree/master/en
- https://www.literatureandlatte.com/ , https://www.atticus.io/ , https://ulysses.app/ , https://linear.app/ , https://linear.app/llms.txt
- https://www.zettlr.com/ , https://docs.zettlr.com/en/
- https://developers.google.com/search/docs/appearance/ai-features
- https://developers.google.com/search/docs/fundamentals/creating-helpful-content
- https://developers.google.com/search/docs/appearance/structured-data/search-gallery
- https://developers.google.com/search/docs/appearance/structured-data/software-app
- https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap
- https://www.searchenginejournal.com/google-drops-faq-rich-results-from-search/574429/
- https://web.dev/articles/vitals
- https://developer.chrome.com/docs/lighthouse/agentic-browsing/scoring and https://ppc.land/google-adds-llms-txt-to-lighthouse-as-agentic-web-standards-heat-up/
- https://developers.openai.com/api/docs/bots
- https://support.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler
- https://docs.perplexity.ai/guides/bots
- https://vercel.com/blog/the-rise-of-the-ai-crawler
- https://llmstxt.org/ and https://ahrefs.com/blog/llmstxt-study/
- https://blogs.bing.com/webmaster/February-2026/Introducing-AI-Performance-in-Bing-Webmaster-Tools-Public-Preview
- https://www.5wpr.com/research/state-of-ai-citations-2026/
- https://arxiv.org/abs/2311.09735
- https://schema.org/SoftwareApplication and https://schema.org/TechArticle
- Search result pages consulted for query intent: web searches on 2026-09-20 for the seven target queries.
- Local files read: CLAUDE.md (site section), tools/build_site.py, tools/site/pages/*.html, site/style.css, site/app.js, tests/test_site.py, novelforge/project.py.
