"""The effect template library (phase-5-plan §5.12): loading and its
problems, lookups, and every built-in template on Appendix A's rig."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, cast

import pytest

from builders import APPENDIX_A, ROOT, load_doc, state_of
from busk import OfflineShow, new_show
from busk.compiler.cues import CueCompiler
from busk.console.parser import Context, Submit, SubmitAll, parse
from busk.engine.snapshot import FixtureOutput
from busk.model.validate import validate_effect, validate_show
from busk.session.ids import CounterIds
from busk.session.library import EffectLibrary, ProfileLibrary
from busk.session.programmer import Programmer

NAMES = [
    "Circle", "Pulse", "Wave", "Chase", "Saw", "Sweep", "Flicker", "Rainbow",
    "Figure eight", "Tilt sweep", "Wander", "Square", "Alternate",
]  # fmt: skip
HEADS = ({"fixtureId": "fx-mh1", "element": 0}, {"fixtureId": "fx-mh2", "element": 0})


def item(ident: str, name: str, **defaults: Any) -> dict[str, Any]:
    """A library item: a pan sweep template and its defaults."""
    layer = {"attribute": "pan", "waveform": {"kind": "triangle"}, "phaseOffset": 0, "mode": "add"}
    return {"template": {"id": ident, "name": name, "layers": [layer]}, "defaults": defaults}


def test_the_builtin_library_loads_every_template() -> None:
    library = EffectLibrary()
    assert library.problems == []
    assert [effect.template["name"] for effect in library] == NAMES
    assert len(library) == 13


def test_templates_are_found_by_id_or_by_name_ignoring_case() -> None:
    library = EffectLibrary()
    circle = library.get("ef-circle")
    assert circle is not None
    assert library.find("CIRCLE") is circle
    assert library.find("ef-circle") is circle
    assert (library.get("Circle"), library.find("Zigzag")) == (None, None)
    assert circle.defaults == {"size": 20}


def test_bad_items_are_skipped_and_reported(tmp_path: Path) -> None:
    empty = item("ef-b", "Empty")
    empty["template"]["layers"] = []
    items = [
        item("ef-a", "Swing", size=10),
        empty,
        item("ef-a", "Again"),  # the id of an item already loaded
        item("ef-c", "SWING"),  # the name, in another case
        item("ef-d", "Big", size="big"),
        item("ef-e", "Half", phase={"start": 0}),
        {"template": item("ef-f", "Odd")["template"]},  # no defaults
        [1],
    ]
    path = tmp_path / "effects.json"
    path.write_text(json.dumps(items))
    library = EffectLibrary([path], builtin=False)
    assert [effect.template["id"] for effect in library] == ["ef-a"]
    assert library.problems == [
        f"{path}[1]: template.layers: An effect template needs at least one layer",
        f"{path}[2]: template id 'ef-a' is already loaded",
        f"{path}[3]: template name 'SWING' is already loaded",
        f"{path}[4]: defaults.size: Input should be a valid number",
        f"{path}[5]: defaults.phase.end: Field required",
        f'{path}[6]: expected {{"template": {{…}}, "defaults": {{…}}}}',
        f'{path}[7]: expected {{"template": {{…}}, "defaults": {{…}}}}',
    ]


def test_unreadable_files_are_reported(tmp_path: Path) -> None:
    broken, scalar, missing = tmp_path / "a.json", tmp_path / "b.json", tmp_path / "c.json"
    broken.write_text("[")
    scalar.write_text("{}")
    library = EffectLibrary([broken, scalar, missing], builtin=False)
    assert len(library) == 0
    assert [problem.split(": ", 1)[0] for problem in library.problems] == [
        str(broken),
        str(scalar),
        str(missing),
    ]
    assert library.problems[1] == f"{scalar}: expected a list of effect templates"


@pytest.mark.parametrize("name", NAMES)
def test_every_library_template_validates_and_compiles_on_appendix_a(name: str) -> None:
    """The console's instance of each template, on the two moving heads,
    with every default (BPM ×1 on Speed 1)."""
    doc = load_doc(APPENDIX_A)
    state = state_of(doc)
    context = Context(
        state.show, ProfileLibrary(), CounterIds(), programmer=Programmer(selection=HEADS)
    )
    action = parse(f'effect add "{name}"', context)
    if isinstance(action, SubmitAll):
        embedding, adding = action.commands
        doc["effects"].append(embedding["value"])  # type: ignore[typeddict-item]
    else:
        assert isinstance(action, Submit)  # Appendix A embeds the library's Pulse
        adding = action.command
    instance = adding["effect"]  # type: ignore[typeddict-item]
    show, issues = validate_show(json.dumps(doc))
    assert show is not None
    assert issues == []
    assert validate_effect(show, instance) == []
    state = state_of(doc)
    compiler = CueCompiler(state.show, state.compiled.slots)
    assert compiler.effect(instance, "programmer.effects[0]") is not None
    assert compiler.warnings == []


# ------------------------------------- the shapes of Phase 32, on the club show


@pytest.fixture
def club(tmp_path: Path) -> OfflineShow:
    """The club show as its script builds it, nothing running, with washes
    203 and 204 unparked. Its heads tilt from -90° to 10° (a low truss)."""
    show = OfflineShow(new_show("Club Night"), path=tmp_path / "club.show", ids=CounterIds())
    show.run_script(ROOT / "examples" / "club-night.busk")
    assert show.execute("unpark all").ok
    return show


BASE = ("set pan 0", "set tilt -40")
"""The heads' look under an effect: inside their tilt limits, with ±20° to spare."""


def added(club: OfflineShow, selection: str, *lines: str) -> float:
    """``lines`` on ``selection``, at :data:`BASE` on the heads; returns the
    engine time the effect started at."""
    for each in (selection, *(BASE if "group 1" in selection else ()), *lines):
        reply = club.execute(each)
        assert reply.ok, f"{each}: {reply.text}"
    return club.time


def output(club: OfflineShow, t: float) -> dict[int, FixtureOutput]:
    club.tick(t)
    assert club.output is not None
    return {f.number: f for f in club.output.fixtures if f.element == 1}


def test_the_library_prints_the_five_new_shapes(club: OfflineShow) -> None:
    lines = club.execute("library").text.splitlines()
    assert lines[-5:] == [
        "effect Figure eight: pan add sine, tilt add sine ×2 +90° (size 20)",
        "effect Tilt sweep: tilt add triangle (size 20)",
        "effect Wander: pan add random, tilt add random (size 20)",
        "effect Square: intensity absolute square (phase 0 360)",
        "effect Alternate: color snap 2 colours (phase 0 360, groups 2)",
    ]


def test_figure_eight_draws_an_eight_on_the_heads(club: OfflineShow) -> None:
    """Pan ``-cos θ`` and tilt ``sin 2θ``, size 20: tilt is at its base at
    both ends of the pan sweep and at its middle, and up on one side, down on
    the other."""
    start = added(club, "sel group 1", 'effect add "Figure eight" hz 1')
    for k in range(16):
        theta = 2 * math.pi * k / 16
        at = output(club, start + k / 16)
        for head in at[101], at[102]:
            assert head.pan == pytest.approx(-20 * math.cos(theta), abs=1e-6)
            assert head.tilt == pytest.approx(-40 + 20 * math.sin(2 * theta), abs=1e-6)


def test_tilt_sweep_moves_tilt_and_leaves_pan(club: OfflineShow) -> None:
    start = added(club, "sel group 1", 'effect add "Tilt sweep" hz 1')
    for k in range(8):
        head = output(club, start + k / 8)[101]
        p = k / 8
        triangle = 2 * p if p < 0.5 else 2 - 2 * p
        assert (head.pan, head.tilt) == pytest.approx((0, -40 + 20 * (2 * triangle - 1)), abs=1e-6)


def test_wander_moves_pan_and_tilt_apart_within_its_size(club: OfflineShow) -> None:
    start = added(club, "sel group 1", 'effect add "Wander" hz 1')
    seen = [output(club, start + k / 10) for k in range(40)]
    for at in seen:
        for head in at[101], at[102]:
            assert head.pan is not None
            assert head.tilt is not None
            assert abs(head.pan) <= 20
            assert abs(head.tilt + 40) <= 20
    pans = [cast(float, at[101].pan) for at in seen]
    tilts = [cast(float, at[101].tilt) + 40 for at in seen]
    others = [cast(float, at[102].pan) for at in seen]
    assert len(set(pans)) > 30  # smooth: it moves all the time
    assert max(abs(a - b) for a, b in zip(pans, tilts, strict=True)) > 5  # another seed
    assert max(abs(a - b) for a, b in zip(pans, others, strict=True)) > 5  # another member


def test_square_lights_half_the_washes_at_a_time(club: OfflineShow) -> None:
    start = added(club, "sel group 2", 'effect add "Square" hz 0.5')
    lit = {201: 0, 202: 0, 203: 0, 204: 0}
    for k in range(16):
        at = output(club, start + 0.05 + k / 8)  # off the edges of the square
        levels = [at[n].intensity for n in lit]
        assert sorted(levels) == [0.0, 0.0, 1.0, 1.0]
        for n in lit:
            lit[n] += at[n].intensity == 1.0
    assert lit == {201: 8, 202: 8, 203: 8, 204: 8}


def test_alternate_gives_each_wash_the_other_colour_from_its_neighbour(club: OfflineShow) -> None:
    start = added(club, "sel group 2", "set intensity 100%", 'effect add "Alternate" hz 0.5')
    red, blue = (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    for t, first in ((0.2, red), (0.8, red), (1.2, blue), (1.8, blue), (2.2, red)):
        at = output(club, start + t)
        second = blue if first == red else red
        colours = [at[n].color for n in (201, 202, 203, 204)]
        assert colours == [first, second, first, second]


def test_alternate_brings_groups_2_and_the_line_wins(club: OfflineShow) -> None:
    added(club, "sel group 2", 'effect add "Alternate" id a')
    added(club, "sel group 2", 'effect add "Alternate" id b groups 3')
    added(club, "sel group 2", 'effect add "Square" id c')
    groups = {e["id"]: e["groups"] for e in club.programmer.effects}
    assert groups == {"a": 2, "b": 3, "c": 1}
