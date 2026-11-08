"""Deletes that cascade (GAP-24 and GAP-36 of ``docs/dev/tui/engine-gaps.md``).

``delete fixture N cascade`` takes the fixture out of everything that names
it, and ``delete universe N cascade`` unpatches its fixtures and removes its
routes. ``preset``, ``group``, ``cuelist``, ``playback`` and ``page`` cascade
too, each in one undo step. A plain ``delete`` is refused in one line while
anything uses what it deletes. A cascade asks first, always, and says what
would go (``OfflineShow.confirmation``).

The rig below has three pars, 1 to 3, and 1 is the one that goes.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from builders import APPENDIX_A, ROOT, load_doc, localhost_route, show_of
from busk import LiveShow, OfflineShow, load_show, new_show
from busk.commands.types import Command
from busk.console.console import interact
from busk.model.show import Show
from sacn_receiver import Receiver

CLUB_NIGHT = ROOT / "examples" / "club-night.busk"
TUPPER_DEMO = ROOT / "examples" / "tupperdmx" / "tupper-demo.show"
FIXTURE_LINE = "delete fixture 1 cascade"


def run(show: OfflineShow, *lines: str) -> None:
    for line in lines:
        reply = show.execute(line)
        assert reply.ok, (line, reply.text)


def fx(ident: str) -> dict[str, Any]:
    return {"fixtureId": ident, "element": 0}


@pytest.fixture
def rig() -> OfflineShow:
    show = OfflineShow(new_show("Rig"))
    run(
        show,
        'universe add 1 "Stage"',
        'fixture add 1 thru 3 "RGB Par 3ch" mode 3ch at 1.1',
        'surface add midi "Pad"',
    )
    return show


@pytest.fixture
def ids(rig: OfflineShow) -> dict[int, str]:
    """Fixture number → id."""
    return {f["number"]: f["id"] for f in rig.show["fixtures"]}


def submit(show: OfflineShow, command: dict[str, Any]) -> None:
    result = show.submit(cast(Command, command))
    assert result.ok, result.message


def bind_action(show: OfflineShow, ident: str, action: dict[str, Any]) -> None:
    surface = show.show["surfaces"][0]["id"]
    binding = {
        "id": ident,
        "surfaceId": surface,
        "input": {"kind": "midiNote", "channel": 1, "note": len(show.show["bindings"])},
        "action": action,
    }
    submit(show, {"type": "ADD", "path": ["bindings"], "value": binding})


def bind(show: OfflineShow, ident: str, command: dict[str, Any]) -> None:
    bind_action(show, ident, {"kind": "command", "command": command})


def cascade(show: OfflineShow, line: str = FIXTURE_LINE) -> Any:
    """Run ``line``; check that one ``undo`` gives the document back and that
    ``redo`` does it again. The document after it."""
    before = copy.deepcopy(show.show)
    run(show, line)
    after = copy.deepcopy(show.show)
    run(show, "undo")
    assert show.show == before
    run(show, "redo")
    assert show.show == after
    return show.show


def numbers(show: OfflineShow) -> list[int]:
    return [fixture["number"] for fixture in show.show["fixtures"]]


def cue(doc: Any, list_number: int = 10) -> Any:
    return next(c for c in doc["cueLists"] if c["number"] == list_number)["cues"][0]


def preset(doc: Any, number: int = 1) -> Any:
    return next(p for p in doc["presets"] if p["number"] == number)


# ---------------------------------------------- the fixture leaves, the others stay


def test_it_leaves_a_group_and_the_others_stay(rig: OfflineShow, ids: dict[int, str]) -> None:
    run(rig, "sel fixture 1 thru 3", 'record group 1 "Pars"')
    assert not rig.execute("delete fixture 1").ok
    doc = cascade(rig)
    assert numbers(rig) == [2, 3]
    assert doc["groups"][0]["members"] == [fx(ids[2]), fx(ids[3])]


def test_it_leaves_a_presets_target_values(rig: OfflineShow, ids: dict[int, str]) -> None:
    run(rig, "sel fixture 1 thru 2", "set intensity 50%", "record preset intensity 1 target")
    run(rig, "clear", "sel none")
    assert not rig.execute("delete fixture 1").ok
    doc = cascade(rig)
    assert [value["scope"]["target"] for value in preset(doc)["values"]] == [fx(ids[2])]


def test_it_keeps_a_presets_other_scopes(rig: OfflineShow) -> None:
    run(rig, "sel fixture 1 thru 2", "set intensity 50%", "record preset intensity 1 global")
    run(rig, "clear", "sel none")
    assert [v["scope"] for v in preset(cascade(rig))["values"]] == [{"kind": "global"}]


def test_it_leaves_a_cue_entrys_targets(rig: OfflineShow, ids: dict[int, str]) -> None:
    run(rig, "sel fixture 1 thru 2", "set intensity 50%", "record cue 10/1", "clear", "sel none")
    assert not rig.execute("delete fixture 1").ok
    [entry] = cue(cascade(rig))["entries"]
    assert entry["targets"] == {"kind": "targets", "refs": [fx(ids[2])]}
    assert entry["value"] == {"kind": "literal", "value": 0.5}


def test_it_leaves_a_cue_entrys_per_target_values(rig: OfflineShow, ids: dict[int, str]) -> None:
    run(rig, "sel fixture 1", "set intensity 20%", "sel fixture 2", "set intensity 80%")
    run(rig, "record cue 10/1", "clear", "sel none")
    assert cue(rig.show)["entries"][0]["value"]["kind"] == "perTarget"
    assert not rig.execute("delete fixture 1").ok
    [entry] = cue(cascade(rig))["entries"]
    assert entry["targets"]["refs"] == [fx(ids[2])]
    assert entry["value"] == {"kind": "perTarget", "values": {f"{ids[2]}:0": 0.8}}


def test_it_leaves_a_cue_effect(rig: OfflineShow, ids: dict[int, str]) -> None:
    run(rig, "sel fixture 1 thru 2", 'effect add "Pulse"', "record cue 10/1", "clear", "sel none")
    assert not rig.execute("delete fixture 1").ok
    [effect] = cue(cascade(rig))["effects"]
    assert effect["targets"]["refs"] == [fx(ids[2])]


def test_it_leaves_a_cue_release(rig: OfflineShow, ids: dict[int, str]) -> None:
    run(rig, "sel fixture 3", "set intensity 50%", "record cue 10/1", "clear", "sel none")
    run(rig, "cuelist 10 tracking true", "cue 10/1 release fixture 1 thru 2")
    assert not rig.execute("delete fixture 1").ok
    [release] = cue(cascade(rig))["releases"]
    assert release["targets"]["refs"] == [fx(ids[2])]


def test_it_leaves_the_park(rig: OfflineShow, ids: dict[int, str]) -> None:
    run(rig, "park fixture 1 thru 2 intensity 0")
    assert not rig.execute("delete fixture 1").ok
    doc = cascade(rig)
    assert [entry["slot"]["target"] for entry in doc["park"]] == [fx(ids[2])]


def select(*refs: dict[str, Any]) -> dict[str, Any]:
    return {"type": "SELECT", "mode": "replace", "targets": {"kind": "targets", "refs": list(refs)}}


def test_it_leaves_a_bindings_select(rig: OfflineShow, ids: dict[int, str]) -> None:
    bind(rig, "b1", select(fx(ids[1]), fx(ids[2])))
    assert not rig.execute("delete fixture 1").ok
    [binding] = cascade(rig)["bindings"]
    assert binding["action"]["command"]["targets"]["refs"] == [fx(ids[2])]


def test_a_cue_that_has_it_through_a_group_is_not_touched(rig: OfflineShow) -> None:
    run(rig, "sel fixture 1 thru 2", 'record group 1 "Pair"', "clear", "sel none")
    run(rig, "sel group 1", "set intensity 50%", 'effect add "Pulse"', "record cue 10/1")
    run(rig, "clear", "sel none")
    held = cue(rig.show)
    assert held["entries"][0]["targets"]["kind"] == "group"
    doc = cascade(rig)
    assert cue(doc) == held


def test_every_element_of_a_fixture_leaves(rig: OfflineShow) -> None:
    """A pixel bar is one member per cell in a group."""
    run(rig, 'fixture add 7 "Chauvet DJ COLORband PiX" mode 36-CH at 1.20')
    run(rig, "sel fixture 7", 'record group 1 "Bar"', "clear", "sel none")
    assert len(rig.show["groups"][0]["members"]) == 12
    assert cascade(rig, "delete fixture 7 cascade")["groups"][0]["members"] == []


# ------------------------------------------- what goes with it, and what stays


def test_a_group_a_preset_and_a_cue_left_empty_stay(rig: OfflineShow) -> None:
    run(
        rig,
        "sel fixture 1",
        "set intensity 50%",
        "record preset intensity 1 target",
        "record cue 10/1",  # before the group: a cue would target the group
        'record group 1 "One"',
        "clear",
        "sel none",
    )
    doc = cascade(rig)
    assert doc["groups"][0]["members"] == []
    assert preset(doc)["values"] == []
    assert [cue(doc)["entries"], cue(doc)["effects"]] == [[], []]


def test_an_entry_an_effect_and_a_release_left_with_no_target_go(rig: OfflineShow) -> None:
    run(rig, "sel fixture 1", "set intensity 50%", 'effect add "Pulse"', "record cue 10/1")
    run(rig, "clear", "sel fixture 2", "set intensity 50%", 'effect add "Pulse"')
    run(rig, "record cue 10/1 merge", "clear", "sel none")
    run(rig, "cuelist 10 tracking true", "cue 10/1 release fixture 1", "cue 10/1 release fixture 2")
    assert len(cue(rig.show)["entries"]) == 2
    assert len(cue(rig.show)["effects"]) == 2
    held = cue(cascade(rig))
    two = rig.show["fixtures"][0]["id"]
    assert [entry["targets"]["refs"] for entry in held["entries"]] == [[fx(two)]]
    assert [effect["targets"]["refs"] for effect in held["effects"]] == [[fx(two)]]
    assert [release["targets"]["refs"] for release in held["releases"]] == [[fx(two)]]


def test_an_entry_left_with_no_per_target_value_goes(rig: OfflineShow, ids: dict[int, str]) -> None:
    """Targets by group, values by fixture: nothing is left for it to say."""
    run(rig, "sel fixture 1 thru 2", 'record group 1 "Pair"', "clear", "sel none")
    run(rig, "sel fixture 3", "set intensity 50%", "record cue 10/1", "clear", "sel none")
    [cue_list] = rig.show["cueLists"]
    [only] = cue_list["cues"]
    entry = {
        "targets": {"kind": "group", "groupId": rig.show["groups"][0]["id"]},
        "attribute": "intensity",
        "value": {"kind": "perTarget", "values": {f"{ids[1]}:0": 0.5}},
    }
    path = ["cueLists", {"id": cue_list["id"]}, "cues", {"id": only["id"]}, "entries"]
    submit(rig, {"type": "SET", "path": path, "value": [*only["entries"], entry]})
    assert [e["targets"]["kind"] for e in cue(cascade(rig))["entries"]] == ["targets"]


def test_a_binding_left_with_no_target_goes(rig: OfflineShow, ids: dict[int, str]) -> None:
    bind(rig, "b1", select(fx(ids[1])))
    bind(rig, "b2", select(fx(ids[2])))
    assert [binding["id"] for binding in cascade(rig)["bindings"]] == ["b2"]


def set_attribute(values: dict[str, float]) -> dict[str, Any]:
    return {
        "type": "SET_ATTRIBUTE",
        "attribute": "intensity",
        "value": {"kind": "perTarget", "values": values},
    }


def test_it_leaves_a_bindings_per_target_values(rig: OfflineShow, ids: dict[int, str]) -> None:
    bind(rig, "b1", set_attribute({f"{ids[1]}:0": 0.5, f"{ids[2]}:0": 0.5}))
    bind(rig, "b2", set_attribute({f"{ids[1]}:0": 0.5}))
    assert not rig.execute("delete fixture 1").ok
    [binding] = cascade(rig)["bindings"]
    assert binding["id"] == "b1"
    assert binding["action"]["command"]["value"]["values"] == {f"{ids[2]}:0": 0.5}


def test_a_binding_that_patches_it_goes(rig: OfflineShow, ids: dict[int, str]) -> None:
    def patch(number: int) -> dict[str, Any]:
        return {"type": "PATCH_FIXTURE", "fixtureId": ids[number], "patch": None}

    bind(rig, "alone", patch(1))
    bind(rig, "batch", {"type": "BATCH", "label": "two", "commands": [patch(1), patch(2)]})
    bind(rig, "batch of it", {"type": "BATCH", "label": "one", "commands": [patch(1)]})
    assert not rig.execute("delete fixture 1").ok
    [binding] = cascade(rig)["bindings"]
    assert binding["id"] == "batch"
    assert binding["action"]["command"]["commands"] == [patch(2)]


def test_a_binding_that_adds_an_effect_leaves_it(rig: OfflineShow, ids: dict[int, str]) -> None:
    run(rig, "sel fixture 1 thru 2", 'effect add "Pulse"')
    effect = copy.deepcopy(rig.programmer.effects[0])
    run(rig, "clear", "sel none")
    bind(rig, "b1", {"type": "ADD_EFFECT", "effect": effect})
    bind(rig, "b2", {"type": "ADD_EFFECT", "effect": {**effect, "targets": {
        "kind": "targets", "refs": [fx(ids[1])]}}})  # fmt: skip
    [binding] = cascade(rig)["bindings"]
    assert binding["id"] == "b1"
    assert binding["action"]["command"]["effect"]["targets"]["refs"] == [fx(ids[2])]


def test_other_bindings_stay_as_they_are(rig: OfflineShow, ids: dict[int, str]) -> None:
    run(rig, 'bind "Pad" cc 1 2 master gm')
    bind(rig, "b1", select(fx(ids[2])))
    before = copy.deepcopy(rig.show["bindings"])
    assert cascade(rig)["bindings"] == before


# ----------------------------------------------------------- a group's layout


def layout(rig: OfflineShow, cells: list[int | None], width: int, height: int) -> None:
    group = rig.show["groups"][0]
    submit(
        rig,
        {
            "type": "SET",
            "path": ["groups", {"id": group["id"]}, "layout"],
            "value": {"width": width, "height": height, "cells": cells},
        },
    )


def test_a_layout_keeps_its_shape_and_its_cells_follow_their_members(rig: OfflineShow) -> None:
    run(rig, "sel fixture 1 thru 3", 'record group 1 "Pars"', "clear", "sel none")
    layout(rig, [0, None, 1, 2], 2, 2)
    assert cascade(rig)["groups"][0]["layout"] == {
        "width": 2,
        "height": 2,
        "cells": [None, None, 0, 1],
    }


def test_a_layout_with_its_last_member_gone_stays_empty(rig: OfflineShow) -> None:
    run(rig, "sel fixture 1", 'record group 1 "One"', "clear", "sel none")
    layout(rig, [0, None], 2, 1)
    assert cascade(rig)["groups"][0]["layout"]["cells"] == [None, None]


# ------------------------------------------------------------------- a universe


@pytest.fixture
def universe(rig: OfflineShow) -> OfflineShow:
    """Universe 2 with fixtures 2 and 3, and two routes. 1 stays in universe 1."""
    run(
        rig,
        'universe add 2 "Balcony"',
        "fixture 2 patch 2.1",
        "fixture 3 patch 2.4",
        "route add 1 sacn 1",
        "route add 2 sacn 2",
        "route add 2 artnet 0.0.2",
    )
    return rig


def test_a_universe_unpatches_its_fixtures_and_takes_its_routes(universe: OfflineShow) -> None:
    assert not universe.execute("delete universe 2").ok
    doc = cascade(universe, "delete universe 2 cascade")
    assert [u["number"] for u in doc["universes"]] == [1]
    assert numbers(universe) == [1, 2, 3]
    assert [f["patch"] is None for f in doc["fixtures"]] == [False, True, True]
    assert [route["universe"] for route in doc["output"]["routes"]] == [1]


def test_a_universe_without_fixtures_or_routes_goes_too(rig: OfflineShow) -> None:
    run(rig, 'universe add 2 "Spare"')
    assert [u["number"] for u in cascade(rig, "delete universe 2 cascade")["universes"]] == [1]


def test_a_binding_that_patches_into_the_universe_goes(
    universe: OfflineShow, ids: dict[int, str]
) -> None:
    second = universe.show["universes"][1]["id"]
    first = universe.show["universes"][0]["id"]

    def patch(where: str) -> dict[str, Any]:
        return {
            "type": "PATCH_FIXTURE",
            "fixtureId": ids[1],
            "patch": {"universeId": where, "address": 100},
        }

    bind(universe, "there", patch(second))
    bind(universe, "here", patch(first))
    bind(universe, "out", {"type": "PATCH_FIXTURE", "fixtureId": ids[1], "patch": None})
    assert not universe.execute("delete universe 2").ok
    doc = cascade(universe, "delete universe 2 cascade")
    assert [binding["id"] for binding in doc["bindings"]] == ["here", "out"]


# ------------------------------------------------------------------- a preset


@pytest.fixture
def colours(rig: OfflineShow) -> OfflineShow:
    """Colour presets 1 and 2. Cue 10/1 uses both, and holds a level of 3."""
    run(
        rig,
        "sel fixture 1",
        "set color 1 0 0",
        "record preset color 1",
        "set color 0 1 0",
        "record preset color 2",
        "clear",
        "sel fixture 1",
        "set color preset color 1",
        "sel fixture 2",
        "set color preset color 2",
        "sel fixture 3",
        "set intensity 50%",
        "record cue 10/1",
        "clear",
        "sel none",
    )
    return rig


def preset_id(show: OfflineShow, number: int = 1) -> str:
    return str(preset(show.show, number)["id"])


def palette(*entries: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"attribute": "color", "palette": list(entries), "blend": "fade", "mode": "absolute"}]


def template(show: OfflineShow, name: str, layers: list[dict[str, Any]]) -> None:
    run(show, f'effect template add "{name}" {json.dumps(layers)}')


def template_named(doc: Any, name: str) -> Any:
    return next(t for t in doc["effects"] if t["name"] == name)


def test_a_preset_takes_the_entries_that_use_it(colours: OfflineShow) -> None:
    other = preset_id(colours, 2)
    assert not colours.execute("delete preset color 1").ok
    doc = cascade(colours, "delete preset color 1 cascade")
    values = [entry["value"] for entry in cue(doc)["entries"]]
    assert {"kind": "preset", "presetId": other} in values
    assert {"kind": "literal", "value": 0.5} in values
    assert len(values) == 2
    assert [p["number"] for p in doc["presets"]] == [2]


def test_a_cue_left_with_no_entry_stays(rig: OfflineShow) -> None:
    run(rig, "sel fixture 1", "set color 1 0 0", "record preset color 1", "clear", "sel fixture 1")
    run(rig, "set color preset color 1", "record cue 10/1", "clear", "sel none")
    held = cue(cascade(rig, "delete preset color 1 cascade"))
    assert held["entries"] == []


def test_a_preset_leaves_a_palette_and_the_other_colours_stay(colours: OfflineShow) -> None:
    gone, kept = preset_id(colours, 1), preset_id(colours, 2)
    red = {"r": 1.0, "g": 0.0, "b": 0.0}
    template(colours, "Mix", palette({"presetId": gone}, red, {"presetId": kept}))
    assert not colours.execute("delete preset color 1").ok
    doc = cascade(colours, "delete preset color 1 cascade")
    assert template_named(doc, "Mix")["layers"][0]["palette"] == [red, {"presetId": kept}]


def test_a_preset_a_palette_does_not_name_leaves_it_alone(colours: OfflineShow) -> None:
    template(colours, "Mix", palette({"presetId": preset_id(colours, 2)}))
    before = copy.deepcopy(template_named(colours.show, "Mix"))
    doc = cascade(colours, "delete preset color 1 cascade")
    assert template_named(doc, "Mix") == before


@pytest.mark.parametrize("line", ["delete preset color 1 cascade", "delete preset color 1"])
def test_a_palette_left_with_no_colour_refuses_the_line_whole(
    colours: OfflineShow, line: str
) -> None:
    """A colour layer needs a colour, and a used template is not cascaded."""
    template(colours, "Solid", palette({"presetId": preset_id(colours)}))
    before = copy.deepcopy(colours.show)
    reply = colours.execute(line)
    assert not reply.ok
    assert "\n" not in reply.text
    assert colours.show == before
    assert colours.confirmation(line) is None


def test_the_refusal_names_the_palette_it_would_empty(colours: OfflineShow) -> None:
    template(colours, "Solid", palette({"presetId": preset_id(colours)}))
    assert colours.execute("delete preset color 1 cascade").text == (
        'error: preset color 1 is the last colour of a palette of effect template "Solid": '
        "change the template first"
    )
    assert colours.execute("delete preset color 1").text == (
        "error: preset color 1 is used by 1 cue and 1 effect template: add cascade"
    )


def test_a_preset_takes_the_bindings_that_apply_it(colours: OfflineShow) -> None:
    gone, kept = preset_id(colours, 1), preset_id(colours, 2)

    def source(preset: str) -> dict[str, Any]:
        return {"kind": "preset", "presetId": preset}

    bind(colours, "apply", {"type": "APPLY_PRESET", "presetId": gone})
    bind(colours, "set", {"type": "SET_ATTRIBUTE", "attribute": "color", "value": source(gone)})
    bind(colours, "other", {"type": "APPLY_PRESET", "presetId": kept})
    bind(
        colours, "other set", {"type": "SET_ATTRIBUTE", "attribute": "color", "value": source(kept)}
    )
    doc = cascade(colours, "delete preset color 1 cascade")
    assert [binding["id"] for binding in doc["bindings"]] == ["other", "other set"]


# ------------------------------------------------------------------- a group


@pytest.fixture
def grouped(rig: OfflineShow) -> OfflineShow:
    """Group 1 of fixtures 1 and 2, group 2 of 3. Cue 10/1 has an entry and an
    effect on each, and releases each."""
    run(
        rig,
        "sel fixture 1 thru 2",
        'record group 1 "Pair"',
        "sel fixture 3",
        'record group 2 "One"',
        "clear",
        "sel group 1",
        "set intensity 50%",
        'effect add "Pulse"',
        "sel group 2",
        "set intensity 20%",
        'effect add "Pulse"',
        "record cue 10/1",
        "clear",
        "sel none",
        "cuelist 10 tracking true",
        "cue 10/1 release group 1",
        "cue 10/1 release group 2",
    )
    return rig


def group_id(show: OfflineShow, number: int = 1) -> str:
    return str(next(g for g in show.show["groups"] if g["number"] == number)["id"])


def test_a_group_takes_what_targets_it_and_the_other_group_stays(grouped: OfflineShow) -> None:
    other = {"kind": "group", "groupId": group_id(grouped, 2)}
    assert not grouped.execute("delete group 1").ok
    doc = cascade(grouped, "delete group 1 cascade")
    held = cue(doc)
    assert [item["targets"] for item in held["entries"]] == [other]
    assert [item["targets"] for item in held["effects"]] == [other]
    assert [item["targets"] for item in held["releases"]] == [other]
    assert [g["number"] for g in doc["groups"]] == [2]


def test_a_cue_with_only_the_group_stays_empty(rig: OfflineShow) -> None:
    run(rig, "sel fixture 1", 'record group 1 "One"', "set intensity 50%")
    run(rig, "record cue 10/1", "clear", "sel none")
    held = cue(cascade(rig, "delete group 1 cascade"))
    assert (held["entries"], held["effects"]) == ([], [])


def test_a_group_takes_its_group_master_and_what_drives_it(grouped: OfflineShow) -> None:
    run(grouped, 'master add group "Pair level" group 1', 'master add group "One level" group 2')
    pair, one, grand = [
        next(m["id"] for m in grouped.show["masters"] if m["name"] == name)
        for name in ("Pair level", "One level", "Grand Master")
    ]
    bind_action(grouped, "drive", {"kind": "master", "masterId": pair})
    bind(grouped, "set", {"type": "SET_MASTER", "masterId": pair, "level": 1})
    bind_action(grouped, "other", {"kind": "master", "masterId": one})
    bind(grouped, "grand", {"type": "SET_MASTER", "masterId": grand, "level": 1})
    assert not grouped.execute("delete group 1").ok
    doc = cascade(grouped, "delete group 1 cascade")
    assert sorted(m["name"] for m in doc["masters"]) == ["Grand Master", "One level"]
    assert [binding["id"] for binding in doc["bindings"]] == ["other", "grand"]


def test_a_group_takes_the_bindings_that_target_it(grouped: OfflineShow) -> None:
    def on_group(number: int) -> dict[str, Any]:
        return {"kind": "group", "groupId": group_id(grouped, number)}

    def add_effect(targets: dict[str, Any]) -> dict[str, Any]:
        effect = copy.deepcopy(cue(grouped.show)["effects"][0])
        return {"type": "ADD_EFFECT", "effect": {**effect, "targets": targets}}

    bind(grouped, "sel", {"type": "SELECT", "mode": "replace", "targets": on_group(1)})
    bind(grouped, "fx", add_effect(on_group(1)))
    bind(grouped, "sel 2", {"type": "SELECT", "mode": "replace", "targets": on_group(2)})
    bind(grouped, "fx 2", add_effect(on_group(2)))
    assert not grouped.execute("delete group 1").ok
    doc = cascade(grouped, "delete group 1 cascade")
    assert [binding["id"] for binding in doc["bindings"]] == ["sel 2", "fx 2"]


# ------------------------------------------------------- a playback, a cue list


@pytest.fixture
def played(rig: OfflineShow) -> OfflineShow:
    """Cue list 10 runs on playbacks 1 and 2, and 11 on 3. Page 1 holds 1 and
    2; page 2 holds 3 and 1."""
    run(
        rig,
        "sel fixture 1",
        "set intensity 50%",
        "record cue 10/1",
        "record cue 11/1",
        "clear",
        "sel none",
        'page add 2 "Other"',
        'playback add 1 cuelist 10 at 1.1 "A"',
        'playback add 2 cuelist 10 at 1.2 "B"',
        'playback add 3 cuelist 11 at 2.1 "C"',
        "page 2 slot 2 playback 1",
    )
    return rig


def playback_id(show: OfflineShow, number: int) -> str:
    return str(next(p for p in show.show["playbacks"] if p["number"] == number)["id"])


def page_of(doc: Any, number: int) -> Any:
    return next(p for p in doc["pages"] if p["number"] == number)


def assign(page: str, slot: int, playback: str | None) -> dict[str, Any]:
    return {"type": "ASSIGN_PLAYBACK", "pageId": page, "slot": slot, "playbackId": playback}


def test_a_playback_empties_its_slots_and_its_list_stays(played: OfflineShow) -> None:
    two, three = playback_id(played, 2), playback_id(played, 3)
    assert not played.execute("delete playback 1").ok
    doc = cascade(played, "delete playback 1 cascade")
    assert page_of(doc, 1)["slots"] == [None, two]
    assert page_of(doc, 2)["slots"] == [three, None]
    assert [p["number"] for p in doc["playbacks"]] == [2, 3]
    assert sorted(c["number"] for c in doc["cueLists"]) == [10, 11]


def test_a_playback_takes_the_bindings_that_name_it(played: OfflineShow) -> None:
    one, two = playback_id(played, 1), playback_id(played, 2)
    page = page_of(played.show, 1)["id"]
    bind_action(played, "abs", {"kind": "playbackFaderAbs", "playbackId": one})
    bind(played, "go", {"type": "GO", "playbackId": one})
    bind(played, "fader", {"type": "SET_FADER", "playbackId": one, "level": 1})
    bind(
        played, "button", {"type": "PLAYBACK_BUTTON", "playbackId": one, "button": 0, "down": True}
    )
    bind(played, "goto", {"type": "GOTO", "playbackId": one, "cueNumber": "1"})
    bind(played, "assign", assign(page, 3, one))
    bind_action(played, "abs 2", {"kind": "playbackFaderAbs", "playbackId": two})
    bind(played, "go 2", {"type": "GO", "playbackId": two})
    bind_action(played, "by slot", {"kind": "playbackFader", "slot": 0})
    bind(played, "slot", {"type": "SET_FADER", "slot": 0, "level": 1})
    bind(played, "empty", assign(page, 3, None))
    doc = cascade(played, "delete playback 1 cascade")
    assert [binding["id"] for binding in doc["bindings"]] == [
        "abs 2",
        "go 2",
        "by slot",
        "slot",
        "empty",
    ]


def test_a_batch_binding_keeps_what_does_not_name_it(played: OfflineShow) -> None:
    one, three = playback_id(played, 1), playback_id(played, 3)
    page = page_of(played.show, 1)["id"]
    both = [assign(page, 4, one), assign(page, 5, three)]
    bind(played, "both", {"type": "BATCH", "label": "both", "commands": both})
    alone = {"type": "BATCH", "label": "one", "commands": [assign(page, 4, one)]}
    bind(played, "alone", alone)
    [binding] = cascade(played, "delete playback 1 cascade")["bindings"]
    assert binding["id"] == "both"
    assert binding["action"]["command"]["commands"] == [assign(page, 5, three)]


def test_a_cue_list_takes_every_playback_that_runs_it(played: OfflineShow) -> None:
    three = playback_id(played, 3)
    assert not played.execute("delete cuelist 10").ok
    doc = cascade(played, "delete cuelist 10 cascade")
    assert [c["number"] for c in doc["cueLists"]] == [11]
    assert [p["number"] for p in doc["playbacks"]] == [3]
    assert page_of(doc, 1)["slots"] == [None, None]
    assert page_of(doc, 2)["slots"] == [three, None]


def test_a_binding_of_two_of_its_playbacks_is_one_edit(played: OfflineShow) -> None:
    """One edit per binding, or the second would put the first's command back."""
    one, two, three = (playback_id(played, n) for n in (1, 2, 3))
    page = page_of(played.show, 1)["id"]
    mixed = [assign(page, 4, one), assign(page, 5, two), assign(page, 6, three)]
    bind(played, "mixed", {"type": "BATCH", "label": "mixed", "commands": mixed})
    gone = [assign(page, 4, one), assign(page, 5, two)]
    bind(played, "gone", {"type": "BATCH", "label": "gone", "commands": gone})
    [binding] = cascade(played, "delete cuelist 10 cascade")["bindings"]
    assert binding["id"] == "mixed"
    assert binding["action"]["command"]["commands"] == [assign(page, 6, three)]


def test_a_cue_list_takes_the_bindings_of_its_playbacks_and_its_own(played: OfflineShow) -> None:
    one, three = playback_id(played, 1), playback_id(played, 3)
    ten, eleven = (
        next(c["id"] for c in played.show["cueLists"] if c["number"] == n) for n in (10, 11)
    )
    bind_action(played, "abs", {"kind": "playbackFaderAbs", "playbackId": one})
    bind(played, "go", {"type": "GO", "playbackId": one})
    bind(played, "record", {"type": "RECORD_CUE", "cueListId": ten})
    bind(played, "go 3", {"type": "GO", "playbackId": three})
    bind(played, "record 11", {"type": "RECORD_CUE", "cueListId": eleven})
    doc = cascade(played, "delete cuelist 10 cascade")
    assert [binding["id"] for binding in doc["bindings"]] == ["go 3", "record 11"]


def test_a_cue_list_only_a_binding_names_needs_the_cascade(played: OfflineShow) -> None:
    run(played, "cuelist add 12")
    ident = next(c["id"] for c in played.show["cueLists"] if c["number"] == 12)
    bind(played, "record", {"type": "RECORD_CUE", "cueListId": ident})
    assert played.execute("delete cuelist 12").text == (
        "error: cue list 12 is used by 1 binding: add cascade"
    )
    assert cascade(played, "delete cuelist 12 cascade")["bindings"] == []


def test_a_cue_list_with_no_playback_goes_plainly(rig: OfflineShow) -> None:
    run(rig, "cuelist add 12")
    assert rig.confirmation("delete cuelist 12") is None
    assert rig.execute("delete cuelist 12").ok
    assert rig.show["cueLists"] == []


# -------------------------------------------------------------------- a page


def test_a_page_takes_what_names_it_and_its_playbacks_stay(played: OfflineShow) -> None:
    three = playback_id(played, 3)
    first, second = page_of(played.show, 1)["id"], page_of(played.show, 2)["id"]
    bind_action(played, "abs", {"kind": "pageAbs", "number": 2})
    bind(played, "number", {"type": "PAGE", "number": 2})
    bind(played, "assign", assign(second, 1, three))
    bind_action(played, "abs 1", {"kind": "pageAbs", "number": 1})
    bind(played, "number 1", {"type": "PAGE", "number": 1})
    bind(played, "assign 1", assign(first, 3, three))
    bind_action(played, "relative", {"kind": "page", "delta": 1})
    bind(played, "delta", {"type": "PAGE", "delta": 1})
    doc = cascade(played, "delete page 2 cascade")
    assert [page["number"] for page in doc["pages"]] == [1]
    assert [p["number"] for p in doc["playbacks"]] == [1, 2, 3]
    assert [binding["id"] for binding in doc["bindings"]] == [
        "abs 1",
        "number 1",
        "assign 1",
        "relative",
        "delta",
    ]


def test_a_page_named_only_by_number_needs_the_cascade(played: OfflineShow) -> None:
    bind_action(played, "abs", {"kind": "pageAbs", "number": 2})
    assert played.execute("delete page 2").text == (
        "error: page 2 is used by 1 binding: add cascade"
    )
    assert page_of(played.show, 2)


def test_a_page_nothing_names_goes_plainly_with_its_playbacks_on_it(played: OfflineShow) -> None:
    assert played.confirmation("delete page 2") is None
    assert played.execute("delete page 2").ok
    assert [p["number"] for p in played.show["playbacks"]] == [1, 2, 3]


def test_the_last_page_can_go(played: OfflineShow) -> None:
    run(played, "delete page 2 cascade")
    assert cascade(played, "delete page 1 cascade")["pages"] == []


# ---------------------------------------------------------- a refusal in words


USED_REFUSALS = [
    ("delete fixture 1", "fixture 1 is used by 1 group and 1 preset: add cascade"),
    ("delete universe 1", "universe 1 is used by 3 fixtures and 1 route: add cascade"),
    ("delete preset intensity 1", "preset intensity 1 is used by 1 cue: add cascade"),
    ("delete group 1", "group 1 is used by 1 cue: add cascade"),
    ("delete cuelist 10", "cue list 10 is used by 1 playback and 1 page: add cascade"),
    ("delete playback 1", "playback 1 is used by 1 page: add cascade"),
]


@pytest.fixture
def used(rig: OfflineShow) -> OfflineShow:
    run(
        rig,
        "sel fixture 1",
        "set intensity 50%",
        "record preset intensity 1 target",
        "clear",
        "sel fixture 1",
        'record group 1 "One"',
        "sel group 1",
        "set intensity preset intensity 1",
        "record cue 10/1",
        "clear",
        "sel none",
        "route add 1 sacn 1",
        'playback add 1 cuelist 10 at 1.1 "A"',
    )
    return rig


@pytest.mark.parametrize(("line", "said"), USED_REFUSALS)
def test_a_plain_delete_says_what_uses_it_in_one_line(
    used: OfflineShow, line: str, said: str
) -> None:
    before = copy.deepcopy(used.show)
    assert used.execute(line).text == f"error: {said}"
    assert used.show == before


@pytest.mark.parametrize(("line", "said"), USED_REFUSALS)
def test_a_used_plain_delete_offers_the_cascade(used: OfflineShow, line: str, said: str) -> None:
    found = used.expected(f"{line} ")
    assert found.words == ("cascade",)
    assert not found.runnable
    assert found.error is None


def test_a_plain_delete_counts_bindings_and_parked_values(rig: OfflineShow) -> None:
    ids = {f["number"]: f["id"] for f in rig.show["fixtures"]}
    run(rig, "park fixture 1 intensity 0")
    bind(rig, "b1", select(fx(ids[1])))
    assert rig.execute("delete fixture 1").text == (
        "error: fixture 1 is used by 1 parked value and 1 binding: add cascade"
    )


def test_an_unused_entity_deletes_plainly_and_asks_nothing(rig: OfflineShow) -> None:
    run(rig, "sel fixture 1", 'record group 1 "One"', "set intensity 50%")
    run(rig, "record preset intensity 1 target", "clear", "sel none", "cuelist add 9")
    run(rig, "page add 2", "universe add 2")
    for line in (
        "delete group 1",
        "delete preset intensity 1",
        "delete cuelist 9",
        "delete page 2",
        "delete universe 2",
    ):
        assert rig.confirmation(line) is None, line
        assert rig.expected(f"{line} ").runnable, line
        reply = rig.execute(line)
        assert reply.ok, (line, reply.text)
    assert "universe 2" not in {f"universe {u['number']}" for u in rig.show["universes"]}


def test_a_word_after_the_number_is_still_refused_first(used: OfflineShow) -> None:
    assert used.execute("delete group 1 now").text == "error: unexpected 'now'"


def test_the_cue_keeps_its_plain_delete(rig: OfflineShow) -> None:
    run(rig, "sel fixture 1", "set intensity 50%", "record cue 10/1", "clear", "sel none")
    assert rig.expected("delete cue 10/1 ").words == ()
    assert rig.execute("delete cue 10/1 cascade").text == "error: unexpected 'cascade'"
    assert rig.execute("delete cue 10/1").ok


# -------------------------------------------------------------- the two shows


@pytest.fixture(scope="module")
def club_show(tmp_path_factory: pytest.TempPathFactory) -> Show:
    path = tmp_path_factory.mktemp("club") / "club.show"
    OfflineShow(new_show("Club Night"), path=path).run_script(CLUB_NIGHT)
    return load_show(path)[0]


def club(club_show: Show) -> OfflineShow:
    return OfflineShow(copy.deepcopy(club_show))


def tupper(club_show: Show) -> OfflineShow:
    return OfflineShow(load_show(TUPPER_DEMO)[0])


CLUB_FIXTURES = [101, 102, 201, 202, 203, 204, 301]
TUPPER_FIXTURES = [101, 201, 202, 301, 401, 402, 403, 501, 502, 503, 504]
SHOWS = [(club, n) for n in CLUB_FIXTURES] + [(tupper, n) for n in TUPPER_FIXTURES]


def test_those_are_the_fixtures_of_the_two_shows(club_show: Show) -> None:
    assert numbers(club(club_show)) == CLUB_FIXTURES
    assert numbers(tupper(club_show)) == TUPPER_FIXTURES


@pytest.mark.parametrize(("make", "number"), SHOWS)
def test_every_fixture_of_the_shows_can_go_and_come_back(
    make: Callable[[Show], OfflineShow], number: int, club_show: Show
) -> None:
    show = make(club_show)
    assert not show.execute(f"delete fixture {number}").ok  # all of them are in use
    cascade(show, f"delete fixture {number} cascade")
    assert number not in numbers(show)


@pytest.mark.parametrize("make", [club, tupper])
def test_all_of_them_in_a_row_leave_a_show_that_saves_and_reloads(
    make: Callable[[Show], OfflineShow], club_show: Show, tmp_path: Path
) -> None:
    show = make(club_show)
    for number in numbers(show):
        run(show, f"delete fixture {number} cascade")
    assert numbers(show) == []
    assert show.show["cueLists"]  # they stay, empty
    path = tmp_path / "empty.show"
    run(show, f"save {path}")
    assert load_show(path)[0]["fixtures"] == []


@pytest.mark.parametrize("make", [club, tupper])
def test_universe_1_of_each_show_can_go_and_come_back(
    make: Callable[[Show], OfflineShow], club_show: Show
) -> None:
    show = make(club_show)
    assert not show.execute("delete universe 1").ok
    doc = cascade(show, "delete universe 1 cascade")
    assert doc["universes"] == []
    assert doc["output"]["routes"] == []
    assert all(fixture["patch"] is None for fixture in doc["fixtures"])


# ---------------------------------------------------------------- what it says


OTHERS = ("groups", "presets", "cueLists", "playbacks", "pages")


def other_lines(doc: Any, order: tuple[str, ...] = OTHERS) -> list[str]:
    """``delete …`` of every group, preset, cue list, playback and page."""
    words = {
        "groups": lambda item: f"delete group {item['number']}",
        "presets": lambda item: f"delete preset {item['pool']} {item['number']}",
        "cueLists": lambda item: f"delete cuelist {item['number']}",
        "playbacks": lambda item: f"delete playback {item['number']}",
        "pages": lambda item: f"delete page {item['number']}",
    }
    return [words[kind](item) for kind in order for item in doc[kind]]


@pytest.mark.parametrize("make", [club, tupper])
def test_every_other_entity_of_the_shows_can_go_and_come_back(
    make: Callable[[Show], OfflineShow], club_show: Show
) -> None:
    show = make(club_show)
    before = copy.deepcopy(show.show)
    for line in other_lines(show.show):
        cascade(show, f"{line} cascade")
        run(show, "undo")
        assert show.show == before, line


@pytest.mark.parametrize("make", [club, tupper])
@pytest.mark.parametrize(
    "order",
    [
        ("playbacks", "cueLists", "groups", "presets", "pages"),
        ("cueLists", "pages", "presets", "groups"),
    ],
)
def test_the_others_in_a_row_leave_a_show_that_saves_and_reloads(
    make: Callable[[Show], OfflineShow],
    order: tuple[str, ...],
    club_show: Show,
    tmp_path: Path,
) -> None:
    show = make(club_show)
    for line in other_lines(show.show, order):
        run(show, f"{line} cascade")
    for kind in order:
        assert show.show[kind] == [], kind  # type: ignore[literal-required]
    assert show.show["playbacks"] == []
    path = tmp_path / "empty.show"
    run(show, f"save {path}")
    assert load_show(path)[0]["cueLists"] == []


# ---------------------------------------------------------------- what it says


def test_with_nothing_to_cascade_it_still_asks(rig: OfflineShow) -> None:
    assert rig.confirmation(FIXTURE_LINE) == "Delete fixture 1?"
    assert rig.execute(FIXTURE_LINE).text == "deleted fixture 1"


def test_a_plain_delete_does_not_ask(rig: OfflineShow) -> None:
    assert rig.confirmation("delete fixture 1") is None
    assert rig.confirmation("delete universe 1") is None


def test_the_question_names_what_it_leaves_and_the_reply_counts_it(rig: OfflineShow) -> None:
    run(
        rig,
        "sel fixture 1",
        "set intensity 50%",
        "record preset intensity 1 target",
        "record preset intensity 2 target",
        "record preset all 7 target",
        "record cue 10/1",
        "record cue 10/2",
        'record group 4 "A"',
        'record group 2 "B"',
        "park fixture 1 intensity 0",
        "park fixture 1 color 1 0 0",
        "clear",
        "sel none",
    )
    bind(rig, "b1", select(fx(rig.show["fixtures"][0]["id"])))
    assert rig.confirmation(FIXTURE_LINE) == (
        "Delete fixture 1? It leaves groups 2, 4; presets all 7, intensity 1, 2; "
        "cues 10/1, 10/2; 2 parked values and 1 binding."
    )
    assert rig.execute(FIXTURE_LINE).text == (
        "deleted fixture 1: left 2 groups, 3 presets, 2 cues, 2 parked values, 1 binding"
    )


@pytest.mark.parametrize(
    ("lines", "question", "reply"),
    [
        (("sel fixture 1", 'record group 1 "A"'), "It leaves group 1.", "left 1 group"),
        (
            (
                "sel fixture 1",
                'record group 1 "A"',
                "set intensity 1",
                "record preset all 3 target",
            ),
            "It leaves group 1 and preset all 3.",
            "left 1 group, 1 preset",
        ),
        (
            ("sel fixture 1", "set intensity 1", "record cue 9/1"),
            "It leaves cue 9/1.",
            "left 1 cue",
        ),
        (("park fixture 1 intensity 0",), "It leaves 1 parked value.", "left 1 parked value"),
    ],
)
def test_one_of_a_kind_is_said_in_the_singular(
    rig: OfflineShow, lines: tuple[str, ...], question: str, reply: str
) -> None:
    run(rig, *lines, "clear", "sel none")
    assert rig.confirmation(FIXTURE_LINE) == f"Delete fixture 1? {question}"
    assert rig.execute(FIXTURE_LINE).text == f"deleted fixture 1: {reply}"


@pytest.mark.parametrize(
    "lines",
    [
        ("sel fixture 1",),
        ("sel fixture 1", "set intensity 50%", "sel none"),
        ("sel fixture 1", 'effect add "Pulse"', "sel none"),
    ],
)
def test_the_question_says_when_the_programmer_holds_it(
    rig: OfflineShow, lines: tuple[str, ...]
) -> None:
    run(rig, *lines)
    assert rig.confirmation(FIXTURE_LINE) == "Delete fixture 1? The programmer holds it."
    assert rig.execute(FIXTURE_LINE).ok


def test_the_programmer_holding_another_fixture_is_not_said(rig: OfflineShow) -> None:
    run(rig, "sel fixture 2", "set intensity 50%", 'effect add "Pulse"')
    assert rig.confirmation(FIXTURE_LINE) == "Delete fixture 1?"


def test_the_questions_for_a_universe(universe: OfflineShow) -> None:
    assert universe.confirmation("delete universe 2 cascade") == (
        'Delete universe 2 "Balcony"? 2 fixtures lose their patch and 2 routes go.'
    )
    assert universe.confirmation("delete universe 1 cascade") == (
        'Delete universe 1 "Stage"? 1 fixture loses its patch and 1 route goes.'
    )
    run(universe, 'universe add 3 "Spare"')
    assert universe.confirmation("delete universe 3 cascade") == 'Delete universe 3 "Spare"?'


def test_the_question_for_a_universe_says_when_a_binding_goes(
    universe: OfflineShow, ids: dict[int, str]
) -> None:
    where = universe.show["universes"][1]["id"]
    patch = {"universeId": where, "address": 100}
    bind(universe, "b1", {"type": "PATCH_FIXTURE", "fixtureId": ids[1], "patch": patch})
    assert universe.confirmation("delete universe 2 cascade") == (
        'Delete universe 2 "Balcony"? 2 fixtures lose their patch, 2 routes go and 1 binding goes.'
    )


def test_the_reply_for_a_universe_counts_what_it_took(universe: OfflineShow) -> None:
    reply = universe.execute("delete universe 2 cascade")
    assert reply.ok
    assert reply.text.splitlines()[0] == (
        'deleted universe 2 "Balcony": 2 fixtures unpatched, 2 routes gone'
    )


def test_a_name_with_a_quote_is_written_as_it_is_typed(rig: OfflineShow) -> None:
    run(rig, r'universe add 2 "The \"Roof\""')
    assert rig.confirmation("delete universe 2 cascade") == r'Delete universe 2 "The \"Roof\""?'


def test_asking_changes_nothing(rig: OfflineShow) -> None:
    run(rig, "sel fixture 1 thru 2", 'record group 1 "Pair"')
    show, programmer = rig.show, rig.programmer
    rig.confirmation(FIXTURE_LINE)
    assert rig.show is show
    assert rig.programmer is programmer


def test_the_prompt_asks_and_no_sends_nothing(rig: OfflineShow) -> None:
    lines = iter([FIXTURE_LINE, "n", FIXTURE_LINE, "y", "quit", ""])  # "": do not save
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return next(lines)

    written: list[str] = []
    interact(rig._console, ask=ask, write=written.append)
    assert asked.count("Delete fixture 1? [y/N] ") == 2
    assert written[:2] == ["cancelled", "deleted fixture 1"]
    assert numbers(rig) == [2, 3]


def test_a_script_does_not_ask(rig: OfflineShow, tmp_path: Path) -> None:
    script = tmp_path / "strike.busk"
    script.write_text(f"{FIXTURE_LINE}\ndelete universe 1 cascade\n", encoding="utf-8")
    assert rig.confirmation(f"source {script}") is None
    run(rig, f"source {script}")
    assert numbers(rig) == [2, 3]
    assert rig.show["universes"] == []


def test_the_question_and_the_reply_of_a_preset(colours: OfflineShow) -> None:
    template(colours, "Mix", palette({"presetId": preset_id(colours)}, {"r": 1, "g": 0, "b": 0}))
    bind(colours, "b1", {"type": "APPLY_PRESET", "presetId": preset_id(colours)})
    line = "delete preset color 1 cascade"
    assert colours.confirmation(line) == (
        'Delete preset color 1 "Color 1"? It leaves cue 10/1; effect template "Mix" and 1 binding.'
    )
    assert colours.execute(line).text == (
        'deleted preset color 1 "Color 1": left 1 cue, 1 effect template, 1 binding'
    )


def test_a_preset_nothing_uses_still_asks(rig: OfflineShow) -> None:
    run(rig, "sel fixture 1", "set color 1 0 0", 'record preset color 1 "Red"', "clear", "sel none")
    assert rig.confirmation("delete preset color 1 cascade") == 'Delete preset color 1 "Red"?'
    assert rig.execute("delete preset color 1 cascade").text == 'deleted preset color 1 "Red"'


def test_the_question_and_the_reply_of_a_group(grouped: OfflineShow) -> None:
    run(grouped, 'master add group "Pair level" group 1')
    assert grouped.confirmation("delete group 1 cascade") == (
        'Delete group 1 "Pair"? It leaves cue 10/1 and master "Pair level".'
    )
    assert grouped.execute("delete group 1 cascade").text == (
        'deleted group 1 "Pair": left 1 cue, 1 master'
    )


def test_the_question_and_the_reply_of_a_playback(played: OfflineShow) -> None:
    bind(played, "go", {"type": "GO", "playbackId": playback_id(played, 1)})
    assert played.confirmation("delete playback 1 cascade") == (
        'Delete playback 1 "A"? It leaves pages 1, 2 and 1 binding.'
    )
    assert played.execute("delete playback 1 cascade").text == (
        'deleted playback 1 "A": left 2 pages, 1 binding'
    )


def test_the_question_and_the_reply_of_a_cue_list(played: OfflineShow) -> None:
    bind(played, "go", {"type": "GO", "playbackId": playback_id(played, 1)})
    assert played.confirmation("delete cuelist 10 cascade") == (
        'Delete cue list 10 "Cue list 10" and playbacks 1, 2? They leave pages 1, 2 and 1 binding.'
    )
    assert played.execute("delete cuelist 10 cascade").text == (
        'deleted cue list 10 "Cue list 10" and 2 playbacks: left 2 pages, 1 binding'
    )


def test_a_cue_list_with_one_playback_says_it_leaves(played: OfflineShow) -> None:
    assert played.confirmation("delete cuelist 11 cascade") == (
        'Delete cue list 11 "Cue list 11" and playback 3? It leaves page 2.'
    )


def test_the_question_and_the_reply_of_a_page(played: OfflineShow) -> None:
    bind_action(played, "abs", {"kind": "pageAbs", "number": 2})
    assert played.confirmation("delete page 2 cascade") == (
        'Delete page 2 "Other"? It leaves 1 binding.'
    )
    assert played.execute("delete page 2 cascade").text == 'deleted page 2 "Other": left 1 binding'
    assert played.confirmation("delete page 1 cascade") == 'Delete page 1 "Main"?'


def test_the_question_says_a_playback_is_running(played: OfflineShow) -> None:
    run(played, "go 1")
    played.tick(0.1)
    assert played.confirmation("delete playback 1 cascade") == (
        'Delete playback 1 "A"? It leaves pages 1, 2. Playback 1 is running.'
    )
    assert played.confirmation("delete playback 2 cascade") == (
        'Delete playback 2 "B"? It leaves page 1.'
    )
    assert played.confirmation("delete cuelist 10 cascade") == (
        'Delete cue list 10 "Cue list 10" and playbacks 1, 2? They leave pages 1, 2. '
        "Playback 1 is running."
    )
    run(played, "go 2")
    played.tick(0.2)
    assert played.confirmation("delete cuelist 10 cascade") == (
        'Delete cue list 10 "Cue list 10" and playbacks 1, 2? They leave pages 1, 2. '
        "Playbacks 1, 2 are running."
    )


def test_a_prompt_refuses_a_used_plain_delete_without_asking(used: OfflineShow) -> None:
    lines = iter(["delete group 1", "quit", ""])  # "": do not save
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return next(lines)

    written: list[str] = []
    interact(used._console, ask=ask, write=written.append)
    assert written[0] == "error: group 1 is used by 1 cue: add cascade"
    assert not any("Delete" in prompt for prompt in asked)


# --------------------------------------------------------------- a running show


def eventually(condition: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def quiet(receiver: Receiver) -> bool:
    """Nothing came for 0.2 s, after what was on its way when a route closed."""
    receiver.drain()
    time.sleep(0.2)
    return receiver.drain() == []


@pytest.fixture
def running(receiver: Receiver) -> Show:
    return show_of(localhost_route(load_doc(APPENDIX_A)))


def test_a_universe_goes_from_a_running_show_and_comes_back(
    running: Show, receiver: Receiver
) -> None:
    with LiveShow(running) as live:

        def universes() -> list[int]:
            frame = live.frame
            return [] if frame is None else list(frame.universes)

        def routes() -> list[str]:
            return [route.state for route in live.routes or ()]

        eventually(lambda: universes() == [1] and routes() == ["ok"])
        eventually(lambda: receiver.drain() != [])
        reply = live.execute("delete universe 1 cascade")
        assert reply.ok, reply.text
        eventually(lambda: universes() == [] and routes() == [])
        assert all(fixture["patch"] is None for fixture in live.show["fixtures"])
        eventually(lambda: quiet(receiver))
        assert live.execute("undo").ok
        eventually(lambda: universes() == [1] and routes() == ["ok"])
        eventually(lambda: receiver.drain() != [])
        assert live.show == running


def test_a_fixture_goes_from_a_running_show_and_comes_back(running: Show) -> None:
    with LiveShow(running, output=False) as live:

        def seen() -> set[int]:
            output = live.output
            return set() if output is None else {fixture.number for fixture in output.fixtures}

        eventually(lambda: seen() == {101, 102, 201})
        assert live.execute("delete fixture 101 cascade").ok
        eventually(lambda: seen() == {102, 201})
        assert live.execute("undo").ok
        eventually(lambda: seen() == {101, 102, 201})
        assert live.show == running


def test_a_running_playback_goes_and_comes_back_idle(running: Show) -> None:
    with LiveShow(running, output=False) as live:

        def states() -> dict[int, str]:
            snapshot = live.snapshot
            return {} if snapshot is None else {p.number: p.state for p in snapshot.playbacks}

        eventually(lambda: 1 in states())
        assert live.execute("go 1").ok
        eventually(lambda: states()[1] == "active")
        assert "Playback 1 is running." in (live.confirmation("delete playback 1 cascade") or "")
        reply = live.execute("delete playback 1 cascade")
        assert reply.ok, reply.text
        eventually(lambda: 1 not in states())
        assert live.execute("undo").ok
        eventually(lambda: states().get(1) == "idle")
        assert live.show == running


def test_a_running_cue_list_goes_with_its_playback(running: Show) -> None:
    with LiveShow(running, output=False) as live:

        def states() -> dict[int, str]:
            snapshot = live.snapshot
            return {} if snapshot is None else {p.number: p.state for p in snapshot.playbacks}

        eventually(lambda: 1 in states())
        assert live.execute("go 1").ok
        eventually(lambda: states()[1] == "active")
        lists = {p["number"]: p["cueListId"] for p in running["playbacks"]}
        number = next(c["number"] for c in running["cueLists"] if c["id"] == lists[1])
        reply = live.execute(f"delete cuelist {number} cascade")
        assert reply.ok, reply.text
        eventually(lambda: 1 not in states())
        assert live.execute("undo").ok
        eventually(lambda: states().get(1) == "idle")
        assert live.show == running


def test_the_page_on_show_can_go_from_a_running_show(running: Show) -> None:
    with LiveShow(running, output=False) as live:

        def page() -> int | None:
            snapshot = live.snapshot
            return None if snapshot is None or snapshot.page is None else snapshot.page.number

        eventually(lambda: page() is not None)
        first = page()
        assert live.execute(f"delete page {first} cascade").ok
        eventually(lambda: page() != first)
        assert live.execute("undo").ok
        assert live.show == running


def test_a_group_and_a_preset_go_from_a_running_show(running: Show) -> None:
    group, preset = running["groups"][0], running["presets"][0]
    with LiveShow(running, output=False) as live:
        eventually(lambda: live.snapshot is not None)
        for line in (
            f"delete group {group['number']} cascade",
            f"delete preset {preset['pool']} {preset['number']} cascade",
        ):
            reply = live.execute(line)
            assert reply.ok, reply.text
            assert live.execute("undo").ok
        assert live.show == running
        assert live.health is None or live.health.state == "running"
