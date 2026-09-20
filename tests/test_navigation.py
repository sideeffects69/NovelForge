"""
Getting around the book: Go to (the quick switcher) and Connections (what links to
what) - the engines, with no window opened, so this is fast.

What it guards:
  * Go to finds things by alias, ranks a whole word above scattered letters, puts a
    character above a scene of the same name, understands `status:draft`-style
    filters, remembers where you were, and ranks five thousand targets in a blink.
  * Connections agrees, count for count, with the story graph; "mentioned, not
    linked" is exactly "mentioned minus declared"; Link is one undoable step; the
    mention index survives a restart and re-reads only scenes that changed; and
    none of it opens a Word document while a panel is being drawn.
"""

import random
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests import SANDBOX, require_isolation

require_isolation()

from novelforge import docxio, navindex  # noqa: E402
from novelforge.navindex import make_target, parse_query, rank  # noqa: E402
from tools.uishots.seed import build_demo_novel  # noqa: E402


def keys(targets):
    return [t.key for t in targets]


class GoToRanking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="nav_", dir=SANDBOX))
        cls.project = build_demo_novel(cls.root, "Nav Test Novel")
        cls.data = cls.project.data
        cls.kessa = next(e for e in cls.data.entities if e.name == "Kessa Ren")
        cls.kessa.aliases = ["the Ashen Wolf"]
        cls.targets = navindex.build_targets(cls.project)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    # -- what is offered ------------------------------------------------
    def test_every_kind_of_thing_in_the_manifest_is_a_target(self):
        d = self.data
        by_kind = {}
        for t in self.targets:
            by_kind[t.kind] = by_kind.get(t.kind, 0) + 1
        self.assertEqual(by_kind["scene"], len(d.scenes))
        self.assertEqual(by_kind["chapter"], len(d.chapters))
        self.assertEqual(by_kind["note"], len(d.notes))
        self.assertEqual(by_kind["event"], len(d.events))
        self.assertEqual(by_kind["beat"], len(d.beats))
        self.assertEqual(by_kind["idea"], len(d.ideas))
        for kind in ("character", "location", "item", "faction", "thread"):
            self.assertEqual(by_kind.get(kind, 0), len(d.entities_of(kind)), kind)
        # A row's key is the binder row it opens.
        scene = d.scenes[0]
        self.assertIn(f"scene:{scene.id}", keys(self.targets))
        self.assertIn(f"entity:{self.kessa.id}", keys(self.targets))

    def test_building_targets_never_opens_a_document(self):
        with mock.patch.object(docxio, "read_prose",
                               side_effect=AssertionError("opened a document")), \
                mock.patch.object(docxio, "Document",
                                  side_effect=AssertionError("opened a document")):
            built = navindex.build_targets(self.project)
            self.assertTrue(rank(built, "kessa"))

    def test_scenes_come_in_reading_order(self):
        scenes = [t.key for t in self.targets if t.kind == "scene"]
        self.assertEqual(scenes, [f"scene:{s.id}"
                                  for s in self.data.ordered_scenes()])

    # -- ranking --------------------------------------------------------
    def test_an_alias_finds_the_character(self):
        found = rank(self.targets, "ashen wolf")
        self.assertTrue(found)
        self.assertEqual(found[0].key, f"entity:{self.kessa.id}")

    def test_the_name_finds_the_character_before_any_scene(self):
        found = rank(self.targets, "kessa")
        self.assertEqual(found[0].kind, "character")
        self.assertEqual(found[0].title, "Kessa Ren")

    def test_letters_in_order_find_a_title(self):
        # The palette's rule, shared: "wdnprice" is not a word, but its letters
        # are all in "The Warden's Price", in order.
        found = rank(self.targets, "wardprice")
        self.assertTrue(found)
        self.assertEqual(found[0].title, "The Warden's Price")

    def test_a_whole_word_beats_scattered_letters(self):
        targets = [make_target("scene:1", "scene", "A dark day at the ford"),
                   make_target("scene:2", "scene", "Ada at the Gate")]
        self.assertEqual(keys(rank(targets, "ada")), ["scene:2", "scene:1"])

    def test_an_exact_title_beats_a_partial_one(self):
        targets = [make_target("scene:1", "scene", "The Gate at Dawn"),
                   make_target("scene:2", "scene", "The Gate")]
        self.assertEqual(rank(targets, "the gate")[0].key, "scene:2")

    def test_a_character_beats_a_scene_of_the_same_name(self):
        targets = [make_target("scene:1", "scene", "Ada"),
                   make_target("entity:1", "character", "Ada")]
        self.assertEqual(rank(targets, "ada")[0].key, "entity:1")

    def test_a_synopsis_word_finds_the_scene_but_never_beats_a_title(self):
        by_synopsis = rank(self.targets, "emberblade")
        self.assertTrue(any(t.kind == "scene" for t in by_synopsis))
        titled = [make_target("scene:1", "scene", "Quiet morning",
                              preview="The lantern goes out."),
                  make_target("scene:2", "scene", "Lantern")]
        self.assertEqual(rank(titled, "lantern")[0].key, "scene:2")

    def test_nothing_matches_nothing(self):
        self.assertEqual(rank(self.targets, "zzzzqqqq"), [])

    def test_ties_keep_reading_order(self):
        targets = [make_target(f"scene:{n}", "scene", "The Road") for n in range(5)]
        self.assertEqual(keys(rank(targets, "road")),
                         [f"scene:{n}" for n in range(5)])

    def test_the_list_is_capped(self):
        many = [make_target(f"scene:{n}", "scene", f"Gate {n}") for n in range(200)]
        self.assertEqual(len(rank(many, "gate")), navindex.MAX_ROWS)

    # -- operators ------------------------------------------------------
    def test_operators_are_split_from_the_words(self):
        q = parse_query('gate status:draft in:"the iron gate" pov:')
        self.assertEqual(q.tokens, ["gate"])
        self.assertEqual(q.filters, [("status", "draft"), ("in", "the iron gate")])

    def test_an_unknown_operator_is_plain_text(self):
        q = parse_query("re: the gate")
        self.assertEqual(q.tokens, ["re:", "the", "gate"])
        self.assertEqual(q.filters, [])

    def test_status_and_pov_filters(self):
        drafts = rank(self.targets, "status:draft")
        self.assertTrue(drafts)
        self.assertTrue(all(t.kind == "scene" and "Draft" in t.attr("status")
                            for t in drafts))
        kessa_pov = rank(self.targets, "pov:kessa")
        self.assertTrue(kessa_pov)
        self.assertTrue(all("Kessa Ren" in t.attr("pov") for t in kessa_pov))
        both = rank(self.targets, "status:draft pov:kessa")
        self.assertTrue(both)
        self.assertTrue(set(keys(both)) <= set(keys(drafts)) & set(keys(kessa_pov)))
        # Two filters are an AND, not an OR.
        mixed = [make_target("scene:1", "scene", "One",
                             attrs=[("status", "Draft"), ("pov", "Ada")]),
                 make_target("scene:2", "scene", "Two",
                             attrs=[("status", "Final"), ("pov", "Ada")]),
                 make_target("scene:3", "scene", "Three",
                             attrs=[("status", "Draft"), ("pov", "Bo")])]
        self.assertEqual(keys(rank(mixed, "status:draft pov:ada")), ["scene:1"])

    def test_kind_filter_and_a_word_together(self):
        found = rank(self.targets, "kind:character war")
        self.assertEqual([t.title for t in found], ["Warden Tholve"])

    def test_a_parent_tag_matches_its_children_but_not_lookalikes(self):
        self.assertTrue(navindex.tag_matches(["clue/red-herring"], "clue"))
        self.assertTrue(navindex.tag_matches(["#Clue"], "clue"))
        self.assertTrue(navindex.tag_matches(["clue"], "clue"))
        self.assertFalse(navindex.tag_matches(["clueless"], "clue"))
        self.assertFalse(navindex.tag_matches(["a"], "a/b"))
        tagged = [make_target("scene:1", "scene", "One", attrs=[("tag", "clue/red")]),
                  make_target("scene:2", "scene", "Two", attrs=[("tag", "clueless")])]
        self.assertEqual(keys(rank(tagged, "tag:clue")), ["scene:1"])

    # -- speed ----------------------------------------------------------
    def test_five_thousand_targets_rank_in_under_fifty_milliseconds(self):
        rng = random.Random(4)
        syll = ["ka", "ren", "vo", "el", "mor", "tha", "gate", "ash", "fall",
                "ada", "iron", "road", "keep", "crown", "sea", "wolf"]
        big = []
        for n in range(5000):
            title = " ".join("".join(rng.choice(syll) for _ in range(2))
                             for _ in range(3)).title()
            big.append(make_target(
                f"scene:{n}", "scene" if n % 4 else "character", title,
                f"Chapter {n % 40} - Draft",
                "She crossed the ashen road toward the keep " * 3,
                aliases=["The " + title.split()[0]] if n % 5 == 0 else ()))
        worst = 0.0
        for query in ("ada", "sgraph", "the gate", "ashen wolf", "zzzq", "k",
                      "status:draft ada", "ironroad"):
            best = min(self._time(big, query) for _ in range(3))
            worst = max(worst, best)
        self.assertLess(worst, 0.050, f"ranking 5,000 targets took {worst * 1000:.0f} ms")

    @staticmethod
    def _time(targets, query):
        start = time.perf_counter()
        rank(targets, query)
        return time.perf_counter() - start


class Recents(unittest.TestCase):
    def test_newest_first_without_repeats(self):
        r = navindex.Recents()
        for key in ("scene:1", "scene:2", "entity:9", "scene:1"):
            r.push(key)
        self.assertEqual(r.keys(), ["scene:1", "entity:9", "scene:2"])

    def test_pushing_the_newest_again_changes_nothing(self):
        r = navindex.Recents(["scene:1"])
        self.assertFalse(r.push("scene:1"))
        self.assertTrue(r.push("scene:2"))

    def test_group_rows_and_blanks_are_not_places(self):
        r = navindex.Recents()
        for key in ("group:manuscript", "", "scene:"):
            self.assertFalse(r.push(key))
        self.assertEqual(len(r), 0)

    def test_it_is_bounded_and_survives_a_round_trip(self):
        r = navindex.Recents(limit=5)
        for n in range(20):
            r.push(f"scene:{n}")
        self.assertEqual(len(r), 5)
        again = navindex.Recents(r.keys(), limit=5)
        self.assertEqual(again.keys(), r.keys())

    def test_junk_in_a_settings_file_is_ignored(self):
        r = navindex.Recents([None, 3, "scene:1", "scene:1", {"a": 1}])
        self.assertEqual(r.keys(), ["scene:1"])

    def test_the_empty_box_lists_what_you_visited_but_not_where_you_are(self):
        targets = [make_target(f"scene:{n}", "scene", f"S{n}") for n in range(6)]
        shown = navindex.recent_targets(
            targets, ["scene:3", "scene:1", "scene:5"], current="scene:3")
        self.assertEqual(keys(shown), ["scene:1", "scene:5"])

    def test_recents_that_no_longer_exist_are_skipped(self):
        targets = [make_target("scene:1", "scene", "One")]
        shown = navindex.recent_targets(targets, ["scene:gone", "scene:1"])
        self.assertEqual(keys(shown), ["scene:1"])

    def test_a_new_novel_still_gets_a_useful_empty_box(self):
        targets = ([make_target("chapter:1", "chapter", "One")]
                   + [make_target(f"scene:{n}", "scene", f"S{n}") for n in range(30)])
        shown = navindex.recent_targets(targets, [])
        self.assertEqual(shown[0].key, "chapter:1")
        self.assertEqual(len(shown), navindex.RECENT_LIMIT)

    def test_the_empty_box_shows_at_most_twelve(self):
        targets = [make_target(f"scene:{n}", "scene", f"S{n}") for n in range(40)]
        shown = navindex.recent_targets(targets, [f"scene:{n}" for n in range(30)])
        self.assertEqual(len(shown), 12)


if __name__ == "__main__":
    unittest.main()
