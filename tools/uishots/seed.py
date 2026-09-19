"""
Make a throwaway install: a demo novel plus the settings file that points at it.

    python seed.py <sandbox folder> <theme> [empty]

Run in its OWN process, before anything imports novelforge: `config.settings` is
a module-level singleton read once at import, so the settings file has to exist
(and NOVELFORGE_SETTINGS has to point at it) before the first import of the
package. `run.py` does that ordering for you.

`build_demo_novel()` is also what the tests use, so the pictures and the tests
work on the same novel.
"""

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def build_demo_novel(parent: Path, title: str = "The Ashfall Crown"):
    """Create a small but complete novel under `parent` and return the Project."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from novelforge.project import Project

    project = Project.create(
        title=title, author="J. R. Marlowe", genre="Epic Fantasy",
        structure="three_act", target_words=110000, daily_words=1200,
        parent=parent, packs=["fantasy"],
    )
    # create() makes "Chapter One" with "Opening Scene"; reuse them.
    first_chapter = project.data.chapters[0]
    project.rename_chapter(first_chapter.id, "The Iron Gate")
    opening = project.data.scenes_in(first_chapter.id)[0]
    project.rename_scene(opening.id, "A Stranger at the Gate")
    project.save_scene_text(opening.id, (
        "The gates of Vaelmoor had not opened for a stranger in eleven years, "
        "and Kessa Ren intended to be the twelfth.\n\n"
        "She had walked three hundred miles on the promise of a dying man's "
        "map, and the guards on the wall were already reaching for their bows. "
        "The wind smelled of iron and old smoke. Behind her, the road she had "
        "come by had vanished into the ash-coloured dusk, and ahead the great "
        "doors stood shut like a held breath.\n\n"
        "\"State your business,\" a voice called down, flat with boredom.\n\n"
        "\"I've come for the Warden,\" Kessa said. \"Tell him the debt is "
        "due.\"\n\nNobody moved. Then, slowly, with a groan that she felt in "
        "her teeth, the gate began to rise."), snapshot=False)
    opening.synopsis = "Kessa arrives at the fortress city seeking the Emberblade."
    opening.status = "Revised"

    second = project.add_chapter("Ashes of the Old Kingdom")
    third = project.add_chapter("The Long March North")
    warden = project.add_scene(
        first_chapter.id, "The Warden's Price",
        synopsis="The Warden agrees to help, for a price Kessa cannot refuse.",
        body=("\"Everyone wants the Emberblade,\" the Warden said, \"and every "
              "one of them dies wanting it. What makes you different?\"\n\n"
              "\"I don't want it,\" Kessa said. \"I want to destroy it.\""))
    warden.status = "Draft"
    memory = project.add_scene(
        second.id, "What the Fire Remembers", synopsis="A memory of the burning.",
        body=("The old kingdom had burned twice - once by war, once by the "
              "thing that ended the war."))
    memory.status = "Draft"
    project.add_scene(second.id, "The Ember Road",
                      synopsis="Kessa and Tholve set out; the Legion is close.")
    snow = project.add_scene(third.id, "Snow on the Ember Road",
                             synopsis="The first snow, and the first betrayal.")
    snow.status = "Needs Work"

    kessa = project.add_entity("character", "Kessa Ren", role="Protagonist")
    tholve = project.add_entity("character", "Warden Tholve", role="Ally")
    king = project.add_entity("character", "The Ember King", role="Antagonist")
    project.add_entity("character", "Mara Voss", role="Mentor")
    vaelmoor = project.add_entity("location", "Vaelmoor")
    project.add_entity("location", "The Ember Road")
    project.add_entity("item", "The Emberblade")
    legion = project.add_entity("faction", "The Ashfall Legion")
    project.add_entity("thread", "The Emberblade's true origin")
    project.add_note("Research: siege engines", kind="research",
                     body="Trebuchets, counterweights, boiling oil.")
    project.add_idea("What if the Warden knew Kessa's father?")
    project.add_idea("A scene where the road itself is on fire.")
    project.add_event("The burning of the old kingdom", story_date="Year 0")
    project.add_event("Kessa reaches Vaelmoor", story_date="Year 211")

    for scene in (opening, warden, memory):
        scene.pov_id = kessa.id
        scene.character_ids = [kessa.id, tholve.id]
        scene.location_ids = [vaelmoor.id]
    memory.character_ids = [kessa.id, king.id]
    memory.faction_ids = [legion.id]

    project.mark_dirty()
    project.save(force=True)
    return project


def main() -> None:
    sandbox = Path(sys.argv[1])
    theme = sys.argv[2]
    empty = len(sys.argv) > 3 and sys.argv[3] == "empty"

    os.environ["NOVELFORGE_PROJECTS"] = str(sandbox / "projects")
    os.environ["NOVELFORGE_SETTINGS"] = str(sandbox / "settings.json")
    sandbox.mkdir(parents=True, exist_ok=True)
    settings = {"theme": theme, "backup_on_open": False, "backup_on_close": False}
    if not empty:
        project = build_demo_novel(sandbox / "projects")
        settings["last_project"] = str(project.root)
    (sandbox / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    print("seeded", sandbox, "theme =", theme, "(empty)" if empty else "")


if __name__ == "__main__":
    main()
