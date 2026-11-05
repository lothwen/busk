"""Deletes that cascade (GAP-24 of ``docs/dev/tui/engine-gaps.md``).

``delete fixture N cascade`` takes the fixture out of everything that names
it, and ``delete universe N cascade`` unpatches its fixtures and removes its
routes, each in one undo step. A plain ``delete`` stays refused while
anything uses what it deletes. Both ask first, always, and say what would go
(``OfflineShow.confirmation``).

The rig below has three pars, 1 to 3, and 1 is the one that goes.
"""

from __future__ import annotations

import copy
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


def bind(show: OfflineShow, ident: str, command: dict[str, Any]) -> None:
    surface = show.show["surfaces"][0]["id"]
    binding = {
        "id": ident,
        "surfaceId": surface,
        "input": {"kind": "midiNote", "channel": 1, "note": len(show.show["bindings"])},
        "action": {"kind": "command", "command": command},
    }
    submit(show, {"type": "ADD", "path": ["bindings"], "value": binding})


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
