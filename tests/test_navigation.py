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

from novelforge import (backlinks, docxio, mentionindex, navindex,  # noqa: E402
                        storygraph, tags)
from novelforge.project import Project  # noqa: E402
from novelforge.navindex import make_target, parse_query, rank  # noqa: E402
from tools.uishots.seed import build_demo_novel  # noqa: E402


def keys(targets):
    return [t.key for t in targets]


class GoToRanking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.project = demo("Nav Test Novel")
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


# ==========================================================================
# Connections
# ==========================================================================


_TEMPLATE = {}


def demo(title="Demo Novel"):
    """
    A fresh copy of the demo novel, so a test may change it freely.

    Building one takes about four seconds (it writes every reference document); a
    copy of the folder takes a twentieth of a second, so the novel is built once.
    """
    if "root" not in _TEMPLATE:
        _TEMPLATE["root"] = Path(tempfile.mkdtemp(prefix="tpl_", dir=SANDBOX))
        _TEMPLATE["project"] = build_demo_novel(_TEMPLATE["root"], "Template Novel")
    copy = Path(tempfile.mkdtemp(prefix="conn_", dir=SANDBOX))
    shutil.rmtree(copy)
    shutil.copytree(_TEMPLATE["project"].root, copy)
    project = Project.open(copy)
    project.data.title = title
    mentionindex.forget(project)
    return copy, project


def entity(project, name):
    return next(e for e in project.data.entities if e.name == name)


def scene_named(project, title):
    return next(s for s in project.data.scenes if s.title == title)


class no_documents_opened:
    """Inside this, opening any Word document fails the test."""

    def __enter__(self):
        boom = AssertionError("a Word document was opened")
        self._patches = [mock.patch.object(docxio, "read_prose", side_effect=boom),
                         mock.patch.object(docxio, "Document", side_effect=boom)]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()
        return False


class counting_reads:
    """Counts how many documents `read_prose` is asked to open (it still works)."""

    def __enter__(self):
        self.patch = mock.patch.object(docxio, "read_prose",
                                       wraps=docxio.read_prose)
        self.mock = self.patch.start()
        return self

    def __exit__(self, *exc):
        self.patch.stop()
        return False

    @property
    def count(self):
        return self.mock.call_count


class MentionIndex(unittest.TestCase):
    def setUp(self):
        self.root, self.project = demo("Index Novel")
        # Some prose that exercises aliases and a name two entities share ("Ember").
        kessa = entity(self.project, "Kessa Ren")
        kessa.aliases = ["the Ashen Wolf"]
        self.text = ("The Ashen Wolf crossed the Ember Road. Kessa Ren did not look "
                     "back; Kessa knew the Ember King waited. Warden Tholve said "
                     "nothing about the Emberblade.")
        self.scene = scene_named(self.project, "The Ember Road")
        self.project.save_scene_text(self.scene.id, self.text, snapshot=False)

    def tearDown(self):
        mentionindex.forget(self.project)
        shutil.rmtree(self.root, ignore_errors=True)

    def graph_table(self):
        graph = storygraph.build(self.project, use_cache=False)
        table = {}
        for edge in graph.edges:
            if edge.kind == "mentions":
                table.setdefault(edge.source, {})[edge.target] = edge.weight
        return table

    def test_nothing_is_known_before_the_first_scan(self):
        table, source = mentionindex.mention_counts(self.project)
        self.assertEqual((table, source), ({}, "none"))
        fresh = mentionindex.freshness(self.project)
        self.assertTrue(fresh.unscanned)
        self.assertFalse(fresh.current)
        self.assertFalse(mentionindex.path_for(self.project).exists())

    def test_counts_equal_the_story_graph_count_for_count(self):
        mentionindex.refresh(self.project)
        table, source = mentionindex.mention_counts(self.project)
        self.assertEqual(source, "index")
        expected = self.graph_table()
        self.assertTrue(expected, "the demo novel should name somebody")
        self.assertEqual(table, expected)
        # The name two entities share counts for both, exactly as the graph does.
        both = table[self.scene.id]
        self.assertIn(entity(self.project, "The Ember King").id, both)
        self.assertIn(entity(self.project, "The Ember Road").id, both)
        # An alias counts for its character.
        self.assertGreaterEqual(both[entity(self.project, "Kessa Ren").id], 3)

    def test_a_current_graph_and_the_index_give_the_same_numbers(self):
        mentionindex.refresh(self.project)
        graph = storygraph.build(self.project, use_cache=False)
        self.assertEqual(mentionindex.mention_counts(self.project, graph)[0],
                         mentionindex.mention_counts(self.project)[0])
        self.assertEqual(mentionindex.mention_counts(self.project, graph)[1], "graph")

    def test_no_prose_is_stored_only_counts_and_offsets(self):
        mentionindex.refresh(self.project)
        raw = mentionindex.path_for(self.project).read_text(encoding="utf-8")
        for fragment in ("Ashen Wolf crossed", "did not look back",
                         "had not opened for a stranger", "Warden agrees"):
            self.assertNotIn(fragment, raw)
        import json

        data = json.loads(raw)
        row = data["scenes"][self.scene.id]
        self.assertEqual(set(row), {"mtime", "counts", "at"})
        for offsets in row["at"].values():
            self.assertLessEqual(len(offsets), mentionindex.MAX_OFFSETS)
            self.assertTrue(all(isinstance(o, int) for o in offsets))

    def test_offsets_are_capped_at_twenty_per_name(self):
        self.project.save_scene_text(
            self.scene.id, " ".join(["Kessa"] * 60), snapshot=False)
        mentionindex.refresh(self.project)
        entry = mentionindex.get(self.project).scenes[self.scene.id]
        kessa = entity(self.project, "Kessa Ren").id
        self.assertEqual(entry.counts[kessa], 60)
        self.assertEqual(len(entry.at[kessa]), 20)

    def test_a_restart_reuses_the_index_and_opens_nothing(self):
        first, total = mentionindex.refresh(self.project)
        self.assertEqual(first, total)                    # the first scan reads them all
        mentionindex.forget(self.project)                 # as if the app had restarted
        with counting_reads() as reads:
            read, _total = mentionindex.refresh(self.project)
        self.assertEqual((read, reads.count), (0, 0))
        self.assertTrue(mentionindex.freshness(self.project).current)

    def test_only_a_scene_that_changed_is_read_again(self):
        mentionindex.refresh(self.project)
        time.sleep(0.05)
        self.project.save_scene_text(
            self.scene.id, "Kessa Ren met the Ember King at dusk.", snapshot=False)
        self.assertEqual(mentionindex.freshness(self.project).changed_scenes, 1)
        with counting_reads() as reads:
            read, _ = mentionindex.refresh(self.project)
        self.assertEqual((read, reads.count), (1, 1))
        self.assertTrue(mentionindex.freshness(self.project).current)
        counts = mentionindex.mention_counts(self.project)[0][self.scene.id]
        self.assertEqual(counts, self.graph_table()[self.scene.id])

    def test_a_change_to_the_cast_re_reads_everything_and_says_so_first(self):
        mentionindex.refresh(self.project)
        entity(self.project, "Warden Tholve").aliases = ["Old Iron"]
        fresh = mentionindex.freshness(self.project)
        self.assertTrue(fresh.names_changed)
        self.assertFalse(fresh.current)
        with counting_reads() as reads:
            mentionindex.refresh(self.project)
        self.assertEqual(reads.count, len(self.project.data.scenes))
        self.assertTrue(mentionindex.freshness(self.project).current)

    def test_update_scene_recounts_the_saved_text_without_reading(self):
        mentionindex.refresh(self.project)
        text = "Mara Voss and Mara Voss again, then Kessa."
        time.sleep(0.05)
        self.project.save_scene_text(self.scene.id, text, snapshot=False)
        with no_documents_opened():
            self.assertTrue(mentionindex.update_scene(self.project, self.scene.id, text))
            self.assertTrue(mentionindex.freshness(self.project).current)
        counts = mentionindex.mention_counts(self.project)[0][self.scene.id]
        mara = entity(self.project, "Mara Voss").id
        self.assertEqual(counts[mara], 2)
        with counting_reads() as reads:                    # and the next scan is free
            mentionindex.refresh(self.project)
        self.assertEqual(reads.count, 0)

    def test_update_scene_does_nothing_before_a_scan_or_after_the_cast_changed(self):
        self.assertFalse(mentionindex.update_scene(self.project, self.scene.id, "Kessa"))
        self.assertFalse(mentionindex.path_for(self.project).exists())
        mentionindex.refresh(self.project)
        entity(self.project, "Mara Voss").aliases = ["The Grey Lady"]
        self.assertFalse(mentionindex.update_scene(self.project, self.scene.id, "Kessa"))

    def test_the_file_is_only_rewritten_now_and_then_but_always_on_flush(self):
        mentionindex.refresh(self.project)
        path = mentionindex.path_for(self.project)
        before = path.stat().st_mtime
        time.sleep(0.05)
        mentionindex.update_scene(self.project, self.scene.id, "Kessa " * 3)
        self.assertEqual(path.stat().st_mtime, before, "written on every save")
        mentionindex.flush(self.project)
        self.assertGreater(path.stat().st_mtime, before)
        mentionindex.forget(self.project)
        counts = mentionindex.mention_counts(self.project)[0][self.scene.id]
        self.assertEqual(counts[entity(self.project, "Kessa Ren").id], 3)

    def test_a_scene_that_cannot_be_read_keeps_what_was_known(self):
        mentionindex.refresh(self.project)
        before = dict(mentionindex.get(self.project).scenes[self.scene.id].counts)
        self.assertTrue(before)
        time.sleep(0.05)
        self.project.save_scene_text(self.scene.id, "Kessa", snapshot=False)
        # Locked by Word: read_prose gives "" and the document will not open.
        with mock.patch.object(docxio, "read_prose", return_value=""), \
                mock.patch.object(docxio, "prose_readable", return_value=False):
            mentionindex.refresh(self.project)
        self.assertEqual(mentionindex.get(self.project).scenes[self.scene.id].counts,
                         before)

    def test_deleted_scenes_leave_the_index(self):
        mentionindex.refresh(self.project)
        self.project.delete_scene(self.scene.id)
        mentionindex.refresh(self.project)
        self.assertNotIn(self.scene.id, mentionindex.get(self.project).scenes)

    def test_a_damaged_or_foreign_file_is_just_unscanned(self):
        path = mentionindex.path_for(self.project)
        for junk in ("{not json", "[]", '{"version": 999, "scenes": {}}',
                     '{"version": 1, "scenes": {"a": 5, "b": {"counts": "x"}}}'):
            path.write_text(junk, encoding="utf-8")
            mentionindex.forget(self.project)
            fresh = mentionindex.freshness(self.project)          # must not raise
            self.assertIsInstance(fresh, mentionindex.Freshness, junk)
            mentionindex.refresh(self.project)                    # and can be repaired
            self.assertTrue(mentionindex.freshness(self.project).current, junk)

    def test_freshness_and_counts_never_open_a_document(self):
        mentionindex.refresh(self.project)
        mentionindex.forget(self.project)
        with no_documents_opened():
            mentionindex.freshness(self.project)
            mentionindex.mention_counts(self.project)

    def test_a_snippet_reads_only_the_one_scene_and_shows_the_name(self):
        mentionindex.refresh(self.project)
        kessa = entity(self.project, "Kessa Ren")
        with counting_reads() as reads:
            found = mentionindex.snippet(self.project, self.scene.id, kessa.id)
        self.assertEqual(reads.count, 1)
        self.assertIn("Ashen Wolf", found)
        # A current graph already holds the text: nothing at all is read.
        graph = storygraph.build(self.project, use_cache=False)
        with no_documents_opened():
            self.assertIn("Ashen Wolf", mentionindex.snippet(
                self.project, self.scene.id, kessa.id, graph))

    def test_a_snippet_survives_the_scene_having_changed_since(self):
        mentionindex.refresh(self.project)
        self.project.save_scene_text(
            self.scene.id, "A long new opening paragraph, and then Kessa Ren.",
            snapshot=False)
        found = mentionindex.snippet(self.project, self.scene.id,
                                     entity(self.project, "Kessa Ren").id)
        self.assertIn("Kessa Ren", found)                 # the stale offset was not trusted

    def test_the_scan_reports_progress(self):
        seen = []
        mentionindex.refresh(self.project, lambda done, total: seen.append((done, total)))
        self.assertEqual(seen[-1][0], seen[-1][1])
        self.assertTrue(all(total == len(self.project.data.scenes) for _d, total in seen))


class ConnectionsData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.project = demo("Connections Novel")
        d = cls.project.data
        # A scene that names people without linking them.
        cls.ledger = cls.project.add_scene(
            d.chapters[0].id, "The Ledger", synopsis="Kessa finds the ledger.",
            body=("Kessa Ren slid the key across the desk. Warden Tholve watched "
                  "her, and Vaelmoor slept. Kessa said nothing of the Emberblade."))
        cls.kessa = entity(cls.project, "Kessa Ren")
        cls.tholve = entity(cls.project, "Warden Tholve")
        cls.vaelmoor = entity(cls.project, "Vaelmoor")
        cls.blade = entity(cls.project, "The Emberblade")
        note = d.notes[0]
        cls.project.set_note_links(note.id, [cls.kessa.id, cls.ledger.id])
        cls.note = note
        cls.event = next(e for e in d.events if "reaches" in e.title)
        cls.event.scene_id = cls.ledger.id
        cls.event.character_ids = [cls.kessa.id]
        cls.event.description = "Kessa arrives; Warden Tholve is waiting at the gate."
        d.beats[0].scene_ids = [cls.ledger.id]
        cls.project.mark_dirty()
        mentionindex.refresh(cls.project)
        cls.graph = storygraph.build(cls.project, use_cache=False)

    @classmethod
    def tearDownClass(cls):
        mentionindex.forget(cls.project)
        shutil.rmtree(cls.root, ignore_errors=True)

    # -- what the graph says, computed independently ---------------------------
    def expected(self):
        """{entity: (declared scene ids, mentioned-but-not-declared scene ids)}."""
        out = {}
        for e in self.project.data.entities:
            declared = {edge.source for edge in self.graph.in_edges(e.id, ("linked", "pov"))}
            mentioned = {edge.source for edge in self.graph.in_edges(e.id, ("mentions",))}
            out[e.id] = (declared, mentioned - declared)
        return out

    def check_entities(self, graph):
        expected = self.expected()
        for e in self.project.data.entities:
            declared, unlinked = expected[e.id]
            info = backlinks.connections(self.project, "entity", e.id, graph=graph)
            self.assertEqual({r.id for r in info.rows("linked")}, declared, e.name)
            self.assertEqual({r.id for r in info.rows("unlinked")}, unlinked, e.name)

    def test_for_every_entity_unlinked_is_mentioned_minus_declared_from_the_index(self):
        self.check_entities(None)

    def test_and_the_same_when_a_current_graph_is_passed_in(self):
        self.check_entities(self.graph)

    def test_the_ledger_is_mentioned_but_not_linked_to_the_people_in_it(self):
        info = backlinks.connections(self.project, "entity", self.kessa.id)
        rows = {r.id: r for r in info.rows("unlinked")}
        self.assertIn(self.ledger.id, rows)
        row = rows[self.ledger.id]
        self.assertEqual(row.count, 2)
        self.assertEqual(row.detail, "named 2x")
        self.assertTrue(row.can_link)
        self.assertEqual((row.link_kind, row.link_target, row.entity_id),
                         ("scene", self.ledger.id, self.kessa.id))

    def test_a_scene_lists_what_it_links_and_what_it_only_names(self):
        opening = scene_named(self.project, "A Stranger at the Gate")
        info = backlinks.connections(self.project, "scene", opening.id)
        linked = {r.title: r.detail for r in info.rows("linked")}
        self.assertEqual(linked["Kessa Ren"], "POV")
        self.assertEqual(linked["Warden Tholve"], "Character")
        self.assertEqual(linked["Vaelmoor"], "Location")
        ledger = backlinks.connections(self.project, "scene", self.ledger.id)
        self.assertEqual(ledger.rows("linked"), [])
        named = {r.title: r.count for r in ledger.rows("unlinked")}
        self.assertEqual(named, {"Kessa Ren": 2, "Warden Tholve": 1, "Vaelmoor": 1,
                                 "The Emberblade": 1})
        self.assertEqual([r.title for r in ledger.rows("unlinked")][0], "Kessa Ren")
        self.assertTrue(all(r.can_link and r.link_target == self.ledger.id
                            for r in ledger.rows("unlinked")))

    def test_research_timeline_and_outline_sections(self):
        kessa = backlinks.connections(self.project, "entity", self.kessa.id)
        self.assertEqual([r.title for r in kessa.rows("research")], [self.note.title])
        self.assertEqual([r.id for r in kessa.rows("timeline")], [self.event.id])
        scene = backlinks.connections(self.project, "scene", self.ledger.id)
        self.assertEqual([r.id for r in scene.rows("research")], [self.note.id])
        self.assertEqual([r.id for r in scene.rows("timeline")], [self.event.id])
        self.assertEqual([r.id for r in scene.rows("outline")],
                         [self.project.data.beats[0].key])
        self.assertEqual(scene.rows("outline")[0].kind, "beat")

    def test_a_note_lists_what_it_is_attached_to(self):
        info = backlinks.connections(self.project, "note", self.note.id)
        self.assertEqual([(r.kind, r.id) for r in info.rows("linked")],
                         [("entity", self.kessa.id), ("scene", self.ledger.id)])
        self.assertEqual(info.rows("unlinked"), [])

    def test_an_event_lists_its_scene_people_and_place_and_who_its_words_name(self):
        info = backlinks.connections(self.project, "event", self.event.id)
        self.assertEqual([(r.kind, r.detail) for r in info.rows("linked")],
                         [("scene", "covers"), ("entity", "about")])
        # The title names Vaelmoor and the description names the Warden; the
        # character already linked (Kessa) is not offered again.
        named = info.rows("unlinked")
        self.assertEqual([r.title for r in named], ["Vaelmoor", "Warden Tholve"])
        self.assertTrue(all((r.link_kind, r.link_target) == ("event", self.event.id)
                            for r in named))

    def test_an_unscanned_novel_says_so_and_still_shows_declared_links(self):
        root, project = demo("Unscanned Novel")
        try:
            kessa = entity(project, "Kessa Ren")
            info = backlinks.connections(project, "entity", kessa.id)
            self.assertEqual(info.source, "none")
            self.assertTrue(info.freshness.unscanned)
            self.assertTrue(info.rows("linked"))
            self.assertEqual(info.rows("unlinked"), [])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_dangling_ids_and_unknown_things_are_not_a_crash(self):
        scene = self.project.data.scene(self.ledger.id)
        scene.character_ids.append("char_gone")
        try:
            info = backlinks.connections(self.project, "scene", scene.id)
            self.assertNotIn("char_gone", [r.id for r in info.rows("linked")])
        finally:
            scene.character_ids.remove("char_gone")
        gone = backlinks.connections(self.project, "entity", "nope")
        self.assertEqual((gone.total, gone.name), (0, ""))
        self.assertEqual(backlinks.connections(self.project, "chapter", "x").total, 0)

    def test_building_connections_never_opens_a_document(self):
        with no_documents_opened():
            for e in self.project.data.entities:
                backlinks.connections(self.project, "entity", e.id)
            for s in self.project.data.scenes:
                backlinks.connections(self.project, "scene", s.id)
            backlinks.connections(self.project, "note", self.note.id)
            backlinks.connections(self.project, "event", self.event.id)
            backlinks.connections(self.project, "entity", self.kessa.id,
                                  graph=self.graph)

    def test_rows_name_the_binder_row_they_open(self):
        info = backlinks.connections(self.project, "entity", self.kessa.id)
        for section in info.sections:
            for row in section.rows:
                self.assertRegex(row.iid, r"^(scene|entity|note|event|beat|chapter):.+")
        first = info.rows("linked")[0]
        self.assertEqual(first.iid, f"scene:{first.id}")


class Linking(unittest.TestCase):
    def setUp(self):
        self.root, self.project = demo("Linking Novel")
        d = self.project.data
        self.scene = self.project.add_scene(
            d.chapters[0].id, "The Ledger",
            body="Kessa Ren, Warden Tholve, Vaelmoor and the Emberblade.")
        self.kessa = entity(self.project, "Kessa Ren")
        self.tholve = entity(self.project, "Warden Tholve")
        self.vaelmoor = entity(self.project, "Vaelmoor")
        self.blade = entity(self.project, "The Emberblade")
        self.project.save(force=True)
        mentionindex.refresh(self.project)

    def tearDown(self):
        mentionindex.forget(self.project)
        shutil.rmtree(self.root, ignore_errors=True)

    def current(self):
        return self.project.data.scene(self.scene.id)

    def test_link_adds_the_entity_to_the_right_list_and_moves_the_row(self):
        before = backlinks.connections(self.project, "scene", self.scene.id)
        self.assertEqual(len(before.rows("unlinked")), 4)
        for who, attr in ((self.tholve, "character_ids"), (self.vaelmoor, "location_ids"),
                          (self.blade, "item_ids")):
            self.assertTrue(backlinks.link_mention(
                self.project, "scene", self.scene.id, who.id), who.name)
            self.assertIn(who.id, getattr(self.current(), attr))
        after = backlinks.connections(self.project, "scene", self.scene.id)
        self.assertEqual({r.title for r in after.rows("linked")},
                         {"Warden Tholve", "Vaelmoor", "The Emberblade"})
        self.assertEqual([r.title for r in after.rows("unlinked")], ["Kessa Ren"])
        # From the character's side the same fact has moved too.
        row_ids = {r.id for r in backlinks.connections(
            self.project, "entity", self.tholve.id).rows("linked")}
        self.assertIn(self.scene.id, row_ids)

    def test_link_then_undo_restores_and_redo_reapplies(self):
        history = self.project.history
        depth = len(history)
        self.assertTrue(backlinks.link_mention(
            self.project, "scene", self.scene.id, self.tholve.id))
        self.assertEqual(len(history), depth + 1, "one step, not several")
        self.assertEqual(history.undo_label(), "Link mention")
        self.project.undo()
        self.assertNotIn(self.tholve.id, self.current().character_ids)
        info = backlinks.connections(self.project, "scene", self.scene.id)
        self.assertIn("Warden Tholve", [r.title for r in info.rows("unlinked")])
        self.project.redo()
        self.assertIn(self.tholve.id, self.current().character_ids)

    def test_it_survives_a_save_and_reopen(self):
        backlinks.link_mention(self.project, "scene", self.scene.id, self.vaelmoor.id)
        self.project.save()
        reopened = Project.open(self.project.root)
        self.assertIn(self.vaelmoor.id, reopened.data.scene(self.scene.id).location_ids)

    def test_there_is_nothing_to_do_when_it_is_already_linked_or_wrong(self):
        pov = self.project.data.scene(scene_named(self.project, "A Stranger at the Gate").id)
        depth = len(self.project.history)
        self.assertFalse(backlinks.link_mention(         # already the POV
            self.project, "scene", pov.id, self.kessa.id))
        self.assertFalse(backlinks.link_mention(         # already present
            self.project, "scene", pov.id, self.tholve.id))
        self.assertFalse(backlinks.link_mention(self.project, "scene", "nope", self.kessa.id))
        self.assertFalse(backlinks.link_mention(self.project, "scene", pov.id, "nope"))
        self.assertFalse(backlinks.link_mention(self.project, "chapter", pov.id, self.kessa.id))
        self.assertEqual(len(self.project.history), depth, "nothing to undo was recorded")
        self.assertTrue(backlinks.link_mention(
            self.project, "scene", self.scene.id, self.tholve.id))
        self.assertFalse(backlinks.link_mention(         # a second click
            self.project, "scene", self.scene.id, self.tholve.id))
        self.assertEqual(self.current().character_ids.count(self.tholve.id), 1)

    def test_an_event_can_gain_a_character_and_an_empty_place(self):
        event = self.project.add_event("Arrival", "Year 1")
        event.description = "Kessa Ren rides into Vaelmoor."
        self.project.mark_dirty()
        info = backlinks.connections(self.project, "event", event.id)
        self.assertEqual({r.title for r in info.rows("unlinked")},
                         {"Kessa Ren", "Vaelmoor"})
        self.assertTrue(backlinks.link_mention(
            self.project, "event", event.id, self.kessa.id))
        self.assertTrue(backlinks.link_mention(
            self.project, "event", event.id, self.vaelmoor.id))
        now = next(e for e in self.project.data.events if e.id == event.id)
        self.assertEqual(now.character_ids, [self.kessa.id])
        self.assertEqual(now.location_id, self.vaelmoor.id)
        self.project.undo()
        self.project.undo()
        again = next(e for e in self.project.data.events if e.id == event.id)
        self.assertEqual((again.character_ids, again.location_id), ([], ""))


class SceneTags(unittest.TestCase):
    def test_what_is_typed_becomes_a_clean_list(self):
        self.assertEqual(tags.parse("clue, Clue ; #red herring\n a//b/ ,, "),
                         ["clue", "red-herring", "a/b"])
        self.assertEqual(tags.parse(""), [])
        self.assertEqual(tags.parse(None), [])
        self.assertEqual(len(tags.parse("x" * 500)[0]), tags.MAX_LENGTH)
        self.assertEqual(tags.format(["a", "b/c"]), "a, b/c")

    def test_a_parent_matches_its_children_and_nothing_that_merely_looks_like_it(self):
        self.assertTrue(tags.matches(["clue/red-herring"], "clue"))
        self.assertTrue(tags.matches(["Clue"], "#clue"))
        self.assertTrue(tags.matches(["a/b/c"], "a/b"))
        self.assertFalse(tags.matches(["clueless"], "clue"))
        self.assertFalse(tags.matches(["a"], "a/b"))
        self.assertFalse(tags.matches([], "a"))
        self.assertFalse(tags.matches(["a"], ""))

    def test_all_tags_lists_each_spelling_once(self):
        class S:
            def __init__(self, *t):
                self.tags = list(t)
        self.assertEqual(tags.all_tags([S("b", "A"), S("a"), S()]), ["A", "b"])

    def test_the_inspector_field_reads_and_writes_the_list(self):
        class S:
            tags = ["clue", "a/b"]
        scene = S()
        field = tags.TagsField(scene)
        self.assertEqual(field.tags, "clue, a/b")
        field.tags = "one, Two ,#three"
        self.assertEqual(scene.tags, ["one", "Two", "three"])

    def test_tags_are_saved_reopened_and_undone_with_the_scene(self):
        root, project = demo("Tags Novel")
        try:
            scene = project.data.scenes[0]
            with project.action("tag it"):
                scene.tags = ["clue/red-herring", "act1"]
                project.mark_dirty()
            project.save()
            reopened = Project.open(project.root)
            self.assertEqual(reopened.data.scene(scene.id).tags,
                             ["clue/red-herring", "act1"])
            project.undo()
            self.assertEqual(project.data.scene(scene.id).tags, [])
            project.redo()
            self.assertEqual(project.data.scene(scene.id).tags,
                             ["clue/red-herring", "act1"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_an_old_manifest_without_tags_still_opens(self):
        from novelforge.model import Scene, from_dict

        scene = from_dict(Scene, {"id": "scn_old", "title": "Old"})
        self.assertEqual(scene.tags, [])

    def test_go_to_finds_scenes_by_tag_and_by_parent_tag(self):
        root, project = demo("Tag Search Novel")
        try:
            a, b = project.data.scenes[0], project.data.scenes[1]
            a.tags, b.tags = ["clue/red-herring"], ["clueless"]
            built = navindex.build_targets(project)
            found = rank(built, "tag:clue")
            self.assertEqual(keys(found), [f"scene:{a.id}"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


def tearDownModule():
    if "root" in _TEMPLATE:
        shutil.rmtree(_TEMPLATE["root"], ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
