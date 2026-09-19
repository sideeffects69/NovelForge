"""
The interface on a scaled Windows display (125%, 150%).

The developer's own screen is 100%, so this is where a downloaded copy is most
likely to differ from what was tested. The app is DPI-aware: sizes are real
pixels while text and controls grow with the scale, so any window sized in fixed
pixels is too small for its contents. That is exactly what the sprint timer and
the corkboard did until window sizes were scaled in `center_window`.

The scale is simulated by telling Tk what Windows would (`tk scaling`) before
the window is built. The real screen does not change, so windows are still
limited to it - which is why the map maker (fifteen toolbar buttons) is left out:
it needs a wider desktop than a small laptop at 125% can offer.
"""

import sys
import tkinter as tk
import unittest

from tests import require_isolation

require_isolation()

from tests.gui_support import Sandbox  # noqa: E402
from tools.uishots.clipping import clipped_content  # noqa: E402


@unittest.skipUnless(sys.platform == "win32", "NovelForge is Windows-only")
class ScaledDisplay(unittest.TestCase):
    SCALE = 1.25

    @classmethod
    def setUpClass(cls):
        import novelforge.ui.app as app_module

        # `tk scaling` belongs to the display, not to one window, so a value set
        # by this class would leak into every test that runs after it (a
        # simulated 125% made the map maker's toolbar overflow in unrelated
        # tests). Remember the real one and put it back.
        probe = tk.Tk()
        cls._real_scaling = probe.tk.call("tk", "scaling")
        probe.destroy()

        cls.app_module = app_module
        cls._original = app_module._apply_scaling
        scale = cls.SCALE

        def simulated(root):
            root.tk.call("tk", "scaling", scale * 96 / 72)      # what Windows reports
            return cls._original(root)

        app_module._apply_scaling = simulated
        try:
            cls.box = Sandbox(title="Scaled Novel", name="scaled").start()
        except BaseException:
            app_module._apply_scaling = cls._original
            raise
        cls.app = cls.box.app

    @classmethod
    def tearDownClass(cls):
        try:
            cls.box.stop()
        finally:
            cls.app_module._apply_scaling = cls._original
            probe = tk.Tk()
            probe.tk.call("tk", "scaling", cls._real_scaling)
            probe.destroy()

    def test_the_app_noticed_the_scale(self):
        self.assertAlmostEqual(self.app.ui_scale, self.SCALE, delta=0.05)

    def test_the_main_window_fits(self):
        self.assertEqual(clipped_content(self.app), [])

    def test_windows_grow_with_the_display_and_still_fit(self):
        app, box = self.app, self.box
        scene = next(s for s in app.project.data.scenes if s.word_count)
        app.tree.selection_set(f"scene:{scene.id}")
        box.pump(0.4)
        problems, sizes = {}, {}
        openers = [
            ("sprint", app.cmd_sprint),
            ("preferences", app.cmd_preferences),
            ("corkboard", app.cmd_corkboard),
            ("outline", app.cmd_outline_window),
            ("search", app.cmd_search),
            ("story graph", app.cmd_story_graph),
            ("new novel", app.cmd_new_project),
            ("project settings", app.cmd_project_settings),
        ]
        for name, opener in openers:
            before = set(box.toplevels())

            def inspect(name=name, before=before):
                for window in box.toplevels():
                    if window not in before:
                        window.update_idletasks()
                        sizes[name] = window.winfo_width()
                        found = clipped_content(window)
                        if found:
                            problems[name] = found[:3]
                        window.destroy()
                        return
                problems[name] = ["no window appeared"]

            app.after(700, inspect)
            opener()
            box.pump(1.0)
            for window in box.toplevels():
                if window not in before:
                    window.destroy()
        self.assertEqual(problems, {})
        # 320px at 100% - it must have grown, not just avoided clipping.
        self.assertGreaterEqual(sizes["sprint"], int(320 * self.SCALE) - 2, sizes)
        self.assertEqual(box.errors, [])


@unittest.skipUnless(sys.platform == "win32", "NovelForge is Windows-only")
class ScalingDoesNotLeak(unittest.TestCase):
    """Runs after ScaledDisplay (classes run in alphabetical order)."""

    def test_the_display_is_back_to_its_real_scaling(self):
        probe = tk.Tk()
        try:
            self.assertEqual(
                round(float(probe.tk.call("tk", "scaling")), 3),
                round(float(ScaledDisplay._real_scaling), 3),
                "the simulated display scaling was left behind for later tests")
        finally:
            probe.destroy()


if __name__ == "__main__":
    unittest.main()
