"""The generator registry: fields that validate themselves, presets, and safe discovery."""

import importlib
import importlib.machinery
import importlib.util
import sys
import types
import unittest
from unittest import mock

from novelforge import mapregistry as reg
from novelforge.mapregistry import Field, GeneratorSpec


def make_spec(key="demo", map_kind="dungeon"):
    def build(values, seed, name):
        return {"values": dict(values), "seed": seed, "name": name}

    return GeneratorSpec(
        key=key, map_kind=map_kind, label="Demo", blurb="A demo.",
        fields=(Field("rooms", "Rooms", "int", 12, lo=4, hi=40),
                Field("density", "Density", "float", 0.5, lo=0.0, hi=1.0),
                Field("mode", "Kind", "choice", "rooms", choices=("rooms", "cave")),
                Field("secret", "Secret doors", "bool", True),
                Field("title", "Title", "text", "")),
        presets={"Small": {"rooms": 6}, "Huge": {"rooms": 999, "mode": "nonsense"}},
        build=build)


class FieldClamping(unittest.TestCase):
    def test_numbers_are_limited_and_typed(self):
        f = Field("rooms", "Rooms", "int", 12, lo=4, hi=40)
        self.assertEqual(f.clamp(999), 40)
        self.assertEqual(f.clamp(-3), 4)
        self.assertEqual(f.clamp("17"), 17)
        self.assertIsInstance(f.clamp(9.9), int)
        g = Field("d", "D", "float", 0.5, lo=0.0, hi=1.0)
        self.assertEqual(g.clamp(7), 1.0)
        self.assertIsInstance(g.clamp(1), float)

    def test_rubbish_falls_back_to_the_default_and_never_raises(self):
        self.assertEqual(Field("r", "R", "int", 12, lo=4, hi=40).clamp("many"), 12)
        self.assertEqual(Field("r", "R", "int", 12).clamp(None), 12)
        self.assertEqual(Field("m", "M", "choice", "a", choices=("a", "b")).clamp("z"), "a")
        self.assertEqual(Field("m", "M", "choice", "a", choices=("a", "b")).clamp("b"), "b")

    def test_bad_definitions_are_refused_up_front(self):
        with self.assertRaises(ValueError):
            Field("x", "X", "colour")
        with self.assertRaises(ValueError):
            Field("x", "X", "choice", "a")


class SpecValues(unittest.TestCase):
    def test_defaults_then_preset_then_the_writers_choices(self):
        spec = make_spec()
        self.assertEqual(spec.values_for()["rooms"], 12)
        self.assertEqual(spec.values_for("Small")["rooms"], 6)
        self.assertEqual(spec.values_for("Small", {"rooms": 20})["rooms"], 20)

    def test_every_value_is_made_valid_and_unknown_names_are_dropped(self):
        values = make_spec().values_for("Huge", {"colour": "red"})
        self.assertEqual(values["rooms"], 40)
        self.assertEqual(values["mode"], "rooms")          # "nonsense" is not a choice
        self.assertNotIn("colour", values)

    def test_generate_passes_valid_values_seed_and_name(self):
        made = make_spec().generate({"rooms": 8}, seed="5", name="Crypt")
        self.assertEqual(made["seed"], 5)
        self.assertEqual(made["name"], "Crypt")
        self.assertEqual(made["values"]["rooms"], 8)
        self.assertEqual(made["values"]["secret"], True)    # default filled in


class Discovery(unittest.TestCase):
    def setUp(self):
        self._errors = list(reg.ERRORS)
        reg.ERRORS.clear()
        self._planted = []

    def tearDown(self):
        for name in self._planted:
            sys.modules.pop(name, None)
        reg.ERRORS[:] = self._errors

    def _plant(self, name, **attrs):
        """A fake generator module that importlib treats as real."""
        module = types.ModuleType(name)
        module.__spec__ = importlib.machinery.ModuleSpec(name, None)
        module.__dict__.update(attrs)
        sys.modules[name] = module
        self._planted.append(name)
        return module

    def test_a_module_that_is_not_there_yet_is_skipped_quietly(self):
        self.assertEqual(reg.discover(("definitely_not_a_module",)), [])
        self.assertEqual(reg.ERRORS, [])

    def test_a_module_without_generators_is_fine(self):
        self.assertEqual(reg.discover(("novelforge.mapkit",)), [])
        self.assertEqual(reg.ERRORS, [])

    def test_generators_are_collected_in_module_order(self):
        self._plant("novelforge.fake_a", GENERATORS=[make_spec("one")])
        self._plant("novelforge.fake_b", GENERATORS=[make_spec("two", "city")])
        modules = ("novelforge.fake_a", "novelforge.fake_b")
        self.assertEqual([s.key for s in reg.discover(modules)], ["one", "two"])
        self.assertEqual([s.key for s in reg.specs_for("city", modules)], ["two"])
        self.assertEqual(reg.ERRORS, [])

    def test_a_broken_module_is_recorded_and_never_raised(self):
        real_find = importlib.util.find_spec

        def find(name, *args, **kwargs):
            return object() if name == "novelforge.fake_broken" else real_find(name, *args, **kwargs)

        def broken(name, *args, **kwargs):
            raise RuntimeError("boom")

        with mock.patch.object(importlib.util, "find_spec", find), \
                mock.patch.object(importlib, "import_module", broken):
            self.assertEqual(reg.discover(("novelforge.fake_broken",)), [])
        self.assertEqual(len(reg.ERRORS), 1)
        self.assertIn("fake_broken", reg.ERRORS[0][0])
        self.assertIn("boom", reg.ERRORS[0][1])

    def test_a_duplicate_key_is_reported_and_not_offered_twice(self):
        self._plant("novelforge.fake_c", GENERATORS=[make_spec("same"), make_spec("same")])
        self.assertEqual(len(reg.discover(("novelforge.fake_c",))), 1)
        self.assertTrue(any("duplicate" in message for _m, message in reg.ERRORS))

    def test_the_real_generators_that_exist_load_without_errors(self):
        reg.discover()
        self.assertEqual(reg.ERRORS, [], "a generator module fails to import")


if __name__ == "__main__":
    unittest.main()
