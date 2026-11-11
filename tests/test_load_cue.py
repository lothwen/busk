"""Loading a cue into the programmer (GAP-44 of ``docs/dev/tui/engine-gaps.md``).

``load cue L/C [only <family>…]`` puts what the cue stores into the
programmer, in place of what it holds, and selects their targets: its own
values, a preset kept as a reference and the rest as each target's literal,
and its effects with their ids (``LOAD_CUE``, one programmer step). A cue of
a tracking list brings its changes only (Q8 (a) of the pending plan).
``record cue L/C replace`` records it back.

Appendix A: two heads (101, 102: group 1) and a par (201: group 2). Song
(list 1, tracking): Verse sets the heads' intensity, colour and a pan spread;
Chorus their intensity and colour. Blue (10/1): preset Blue on groups 1
and 2. Slow Pulse (20/1): one effect, ``ei-1``, on group 1.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from typing import Any, cast

import pytest

from builders import APPENDIX_A, ROOT, load_doc, show_of
from busk import LiveShow, OfflineShow, load_show, new_show
from busk.commands.types import Command
from busk.compiler.compile import compile_show
from busk.model.show import Show
from busk.model.validate import validate_show

CLUB_NIGHT = ROOT / "examples" / "club-night.busk"
TUPPER_DEMO = ROOT / "examples" / "tupperdmx" / "tupper-demo.show"

MH1 = {"fixtureId": "fx-mh1", "element": 0}
MH2 = {"fixtureId": "fx-mh2", "element": 0}
PAR = {"fixtureId": "fx-par1", "element": 0}


@pytest.fixture
def offline() -> OfflineShow:
    return OfflineShow(show_of(load_doc(APPENDIX_A)))


def run(show: OfflineShow | LiveShow, *lines: str) -> list[str]:
    texts = []
    for line in lines:
        reply = show.execute(line)
        assert reply.ok, f"{line}: {reply.text}"
        texts.append(reply.text)
    return texts


def held(show: OfflineShow | LiveShow) -> list[tuple[int, str, Any, Any]]:
    """The programmer's values: fixture, attribute, value, preset."""
    return [(v.number, v.attribute, v.value, v.preset) for v in show.programmer.values]


def content(show: OfflineShow | LiveShow) -> tuple[Any, ...]:
    """What ``undo`` gives back: the selection, values, effects and stopped ones."""
    status = show.programmer
    return status.selection, status.values, status.effects, status.stopped


def cue_of(show: OfflineShow, cue_list: int, number: str) -> dict[str, Any]:
    listed = next(cl for cl in show.show["cueLists"] if cl["number"] == cue_list)
    return cast(dict[str, Any], next(c for c in listed["cues"] if c["number"] == number))


def set_entries(show: OfflineShow, cue_list: int, number: str, entries: list[Any]) -> None:
    listed = next(cl for cl in show.show["cueLists"] if cl["number"] == cue_list)
    path = ["cueLists", {"id": listed["id"]}, "cues", {"id": cue_of(show, cue_list, number)["id"]}]
    command = {"type": "SET", "path": [*path, "entries"], "value": entries}
    assert show.submit(cast(Command, command)).ok


def heads(show: OfflineShow) -> list[float]:
    """The heads' intensity on stage, after a tick."""
    show.tick(show.time + 0.05)
    return [f.intensity for f in show.output.fixtures if f.number in (101, 102)]


# ------------------------------------------------------------------ what comes


def test_a_cue_comes_as_a_value_per_target_and_selects_them(offline: OfflineShow) -> None:
    assert run(offline, "load cue 1/1") == ['loaded cue 1/1 "Verse": 6 values on 2 fixtures']
    assert offline.programmer.selection == ((101, 1), (102, 1))
    colour = {"r": 1.0, "g": 0.8, "b": 0.6}
    assert held(offline) == [
        (101, "intensity", 0.4, None),
        (102, "intensity", 0.4, None),
        (101, "color", colour, None),
        (102, "color", colour, None),
        (101, "pan", -20.0, None),  # the group's spread, target by target
        (102, "pan", 20.0, None),
    ]
    assert offline.programmer.effects == ()


def test_a_preset_stays_a_reference(offline: OfflineShow) -> None:
    assert run(offline, "load cue 10/1") == ['loaded cue 10/1 "Blue": 3 values on 3 fixtures']
    assert offline.programmer.selection == ((101, 1), (102, 1), (201, 1))
    assert {v.preset for v in offline.programmer.values} == {("color", 1, "Blue")}
    green = [{"scope": {"kind": "global"}, "attribute": "color", "value": {"r": 0, "g": 1, "b": 0}}]
    edit = {"type": "SET", "path": ["presets", {"id": "pr-blue"}, "values"], "value": green}
    assert offline.submit(cast(Command, edit)).ok  # the preset changes: the programmer follows
    assert [v.value for v in offline.programmer.values] == [{"r": 0, "g": 1, "b": 0}] * 3


def test_per_target_values_and_a_list_of_targets_come_as_they_are(offline: OfflineShow) -> None:
    run(
        offline,
        "sel fixture 101",
        "set intensity 20%",
        "sel fixture 102",
        "set intensity 70%",
        "sel fixture 201",
        "set color 1 0 0",
        "record cue 30/1 freeze",
        "clear",
    )
    entries = cue_of(offline, 30, "1")["entries"]
    assert [(e["targets"]["kind"], e["value"]["kind"]) for e in entries] == [
        ("targets", "perTarget"),
        ("targets", "literal"),
    ]
    assert run(offline, "load cue 30/1") == ['loaded cue 30/1 "Cue 1": 3 values on 3 fixtures']
    assert held(offline) == [
        (101, "intensity", 0.2, None),
        (102, "intensity", 0.7, None),
        (201, "color", {"r": 1.0, "g": 0.0, "b": 0.0}, None),
    ]
    assert offline.programmer.selection == ((101, 1), (102, 1), (201, 1))


def test_a_target_without_the_attribute_comes_without_it(offline: OfflineShow) -> None:
    pan = {"kind": "literal", "value": 30}
    set_entries(offline, 10, "1", [{"targets": {"kind": "targets", "refs": [MH1, PAR]},
                                    "attribute": "pan", "value": pan}])  # fmt: skip
    assert run(offline, "load cue 10/1") == ['loaded cue 10/1 "Blue": 1 value on 1 fixture']
    assert held(offline) == [(101, "pan", 30.0, None)]
    assert offline.programmer.selection == ((101, 1),)


def test_effects_come_with_their_ids_and_targets(offline: OfflineShow) -> None:
    assert run(offline, "load cue 20/1") == ['loaded cue 20/1 "Pulse": 1 effect']
    assert [dict(e) for e in offline.programmer.effects] == cue_of(offline, 20, "1")["effects"]
    assert offline.programmer.effects[0]["targets"] == {"kind": "group", "groupId": "g-mh"}
    assert offline.programmer.selection == ((101, 1), (102, 1))
    offline.tick(offline.time + 0.05)
    assert [effect.id for effect in offline.effects.effects] == ["ei-1"]


def test_an_effect_that_comes_runs_though_one_of_its_id_was_stopped(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201", 'effect add "Pulse" id ei-1', "effect stop ei-1")
    run(offline, "load cue 20/1")
    assert offline.programmer.stopped == frozenset()
    offline.tick(offline.time + 0.05)
    assert [effect.id for effect in offline.effects.effects] == ["ei-1"]
    assert offline.programmer.effects[0]["targets"] == {"kind": "group", "groupId": "g-mh"}


def test_the_values_targets_come_first_then_the_effects(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201", "set intensity 50%", "sel group 1")
    run(offline, 'effect add "Pulse" id wave', "record cue 30/1", "clear")
    assert run(offline, "load cue 30/1") == [
        'loaded cue 30/1 "Cue 1": 1 value on 1 fixture, 1 effect'
    ]
    assert offline.programmer.selection == ((201, 1), (101, 1), (102, 1))
    assert [e["id"] for e in offline.programmer.effects] == ["wave"]


def test_only_loads_those_families(offline: OfflineShow) -> None:
    assert run(offline, "load cue 1/1 only position") == [
        'loaded cue 1/1 "Verse": 2 values on 2 fixtures'
    ]
    assert [(v.number, v.attribute) for v in offline.programmer.values] == [
        (101, "pan"),
        (102, "pan"),
    ]
    run(offline, "load cue 1/1 only color intensity")
    assert {v.attribute for v in offline.programmer.values} == {"intensity", "color"}
    run(offline, "clear", "sel fixture 201", "set color 0 0 1", "sel group 1")
    run(offline, 'effect add "Pulse" id wave', "record cue 30/1", "clear")
    assert run(offline, "load cue 30/1 only color") == [
        'loaded cue 30/1 "Cue 1": 1 value on 1 fixture'
    ]
    assert offline.programmer.effects == ()  # Pulse moves intensity
    assert run(offline, "load cue 30/1 only intensity") == ['loaded cue 30/1 "Cue 1": 1 effect']
    assert offline.execute("load cue 30/1 only position").text == (
        "error: cue 30/1 has no position values or effects to load"
    )


def test_a_cue_of_a_tracking_list_brings_its_own_changes_only(offline: OfflineShow) -> None:
    """Chorus shows Verse's pan on stage, but stores none (Q8 (a))."""
    assert run(offline, "load cue 1/2") == ['loaded cue 1/2 "Chorus": 4 values on 2 fixtures']
    assert {v.attribute for v in offline.programmer.values} == {"intensity", "color"}
    run(offline, "go 1", "go 1")
    offline.tick(offline.time + 3)
    pans = [f.pan for f in offline.output.fixtures if f.number in (101, 102)]
    assert pans == [-20.0, 20.0]  # the tracked pan, from the playback


# --------------------------------------------------------- what it replaces


def test_it_replaces_the_programmer_and_undo_gives_it_back(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201", "set intensity 30%", 'effect add "Pulse" id wave')
    run(offline, "effect stop wave", "sel fixture 101", "fade 1.5", "highlight on")
    before = content(offline)
    run(offline, "load cue 1/2")
    assert [v.number for v in offline.programmer.values] == [101, 102, 101, 102]
    assert (offline.programmer.effects, offline.programmer.stopped) == ((), frozenset())
    status = offline.programmer
    assert (status.blind, status.highlight, status.fadeTime) == (False, True, 1.5)  # modes stay
    assert run(offline, "undo") == ['undid: loaded cue 1/2 "Chorus": 4 values on 2 fixtures']
    assert content(offline) == before
    assert run(offline, "redo") == ['redid: loaded cue 1/2 "Chorus": 4 values on 2 fixtures']
    assert offline.programmer.selection == ((101, 1), (102, 1))


def test_blind_keeps_the_stage_as_it_was(offline: OfflineShow) -> None:
    run(offline, "sel group 1", "set intensity 10%", "blind on")
    shown = heads(offline)
    run(offline, "load cue 1/2")
    assert heads(offline) == shown
    run(offline, "blind off")
    assert heads(offline) == [1.0, 1.0]  # Chorus's level, from the programmer


def test_the_stage_shows_what_came(offline: OfflineShow) -> None:
    run(offline, "load cue 1/1")
    assert heads(offline) == [0.4, 0.4]
    pans = [f.pan for f in offline.output.fixtures if f.number in (101, 102)]
    assert pans == [-20.0, 20.0]


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("load cue 1/9", "no cue 1/9"),
        ("load cue 10/1 only position", "cue 10/1 has no position values or effects to load"),
        ("load cue 30/1", "cue 30/1 has no values or effects to load"),
    ],
)
def test_a_refusal_changes_nothing_and_spends_no_step(
    offline: OfflineShow, line: str, error: str
) -> None:
    run(offline, "sel group 1", "set intensity 50%", "record cue 30/1", "record cue 30/1 remove")
    assert cue_of(offline, 30, "1")["entries"] == []
    before = content(offline)
    assert offline.execute(line).text == f"error: {error}"
    assert content(offline) == before
    assert run(offline, "undo") == ["undid: removed 2 values from cue 30/1"]


def test_an_entrys_own_timing_does_not_come_and_the_reply_says_so(offline: OfflineShow) -> None:
    entries = copy.deepcopy(cue_of(offline, 1, "2")["entries"])
    entries[0]["timing"] = {"fade": 4}
    set_entries(offline, 1, "2", entries)
    assert run(offline, "load cue 1/2") == [
        'loaded cue 1/2 "Chorus": 4 values on 2 fixtures; '
        "1 entry's own timing is not loaded, and replace drops it"
    ]
    assert run(offline, "load cue 1/2 only color") == [
        'loaded cue 1/2 "Chorus": 2 values on 2 fixtures'
    ]
    entries[1]["timing"] = {"delay": 1}
    set_entries(offline, 1, "2", entries)
    assert run(offline, "load cue 1/2")[0].endswith(
        "; 2 entries' own timing is not loaded, and replace drops it"
    )
    run(offline, "record cue 1/2 replace")
    assert all("timing" not in entry for entry in cue_of(offline, 1, "2")["entries"])


# ----------------------------------------------------------- recording back


def test_an_edit_recorded_back_keeps_the_rest(offline: OfflineShow) -> None:
    run(offline, "load cue 1/2", "sel fixture 102", "set intensity 70%")
    run(offline, "record cue 1/2 replace")
    entries = cue_of(offline, 1, "2")["entries"]
    assert [(e["attribute"], e["targets"]["kind"], e["value"]["kind"]) for e in entries] == [
        ("intensity", "group", "perTarget"),
        ("color", "group", "literal"),
    ]
    assert entries[0]["value"]["values"] == {"fx-mh1:0": 1.0, "fx-mh2:0": 0.7}
    assert entries[1]["value"]["value"] == {"r": 1.0, "g": 1.0, "b": 1.0}


@pytest.fixture(scope="module")
def club_show(tmp_path_factory: pytest.TempPathFactory) -> Show:
    path = tmp_path_factory.mktemp("club") / "club.show"
    OfflineShow(new_show("Club Night"), path=path).run_script(CLUB_NIGHT)
    return load_show(path)[0]


def every_cue(show: Show) -> list[tuple[int, str, str]]:
    return [(cl["number"], cl["id"], c["number"]) for cl in show["cueLists"] for c in cl["cues"]]


@pytest.mark.parametrize(("name", "count"), [("club", 29), ("tupper", 8)])
def test_every_cue_of_the_shipped_shows_comes_back_as_it_was(
    club_show: Show, name: str, count: int
) -> None:
    """Load, then ``replace`` with nothing changed in between: the shows hold
    group and target entries of literals and presets, and effects on groups,
    in the order recording writes them, so every cue comes back unchanged,
    the club's tracking list's too."""
    shipped = club_show if name == "club" else load_show(TUPPER_DEMO)[0]
    cues = every_cue(shipped)
    assert len(cues) == count
    for cue_list, _, number in cues:
        show = OfflineShow(copy.deepcopy(shipped))
        before = copy.deepcopy(cue_of(show, cue_list, number))
        run(show, f"load cue {cue_list}/{number}", f"record cue {cue_list}/{number} replace")
        assert cue_of(show, cue_list, number) == before, f"{cue_list}/{number}"


def compiled(show: Show, ident: str) -> str:
    return repr(compile_show(show).cueLists[ident].cues)


def test_a_spread_comes_back_per_target_and_plays_the_same(offline: OfflineShow) -> None:
    before = compiled(offline.show, "cl-song")
    run(offline, "load cue 1/1", "record cue 1/1 replace")
    entries = cue_of(offline, 1, "1")["entries"]
    assert [e["attribute"] for e in entries] == ["intensity", "pan", "color"]  # recording's order
    assert entries[1]["value"] == {
        "kind": "perTarget",
        "values": {"fx-mh1:0": -20.0, "fx-mh2:0": 20.0},
    }
    assert entries[1]["targets"] == {"kind": "group", "groupId": "g-mh"}
    assert compiled(offline.show, "cl-song") == before


def test_targets_that_are_a_group_come_back_as_the_group(offline: OfflineShow) -> None:
    level = {"kind": "literal", "value": 0.5}
    set_entries(offline, 10, "1", [{"targets": {"kind": "targets", "refs": [MH1, MH2]},
                                    "attribute": "intensity", "value": level}])  # fmt: skip
    before = compiled(offline.show, "cl-blue")
    run(offline, "load cue 10/1", "record cue 10/1 replace")
    assert cue_of(offline, 10, "1")["entries"][0]["targets"] == {"kind": "group", "groupId": "g-mh"}
    assert compiled(offline.show, "cl-blue") == before


def test_a_value_equal_to_what_it_tracks_goes_on_replace(offline: OfflineShow) -> None:
    """Chorus holding Verse's pan as its own: ``replace`` leaves it to track."""
    entries = copy.deepcopy(cue_of(offline, 1, "2")["entries"])
    pans = {"kind": "perTarget", "values": {"fx-mh1:0": -20.0, "fx-mh2:0": 20.0}}
    entries.append({"targets": {"kind": "group", "groupId": "g-mh"}, "attribute": "pan",
                    "value": pans})  # fmt: skip
    set_entries(offline, 1, "2", entries)
    before = compiled(offline.show, "cl-song")
    run(offline, "load cue 1/2")
    assert run(offline, "record cue 1/2 replace") == [
        "recorded cue 1/2: 2 entries; 2 values tracked from cue 1/1"
    ]
    assert [e["attribute"] for e in cue_of(offline, 1, "2")["entries"]] == ["intensity", "color"]
    assert compiled(offline.show, "cl-song") == before


# ------------------------------------------------------------------ bindings


def binding_issues(command: dict[str, Any]) -> list[tuple[str, str, str]]:
    doc = load_doc(APPENDIX_A)
    doc["bindings"].append(
        {
            "id": "b9",
            "surfaceId": "s-midi",
            "input": {"kind": "midiNote", "channel": 1, "note": 9},
            "action": {"kind": "command", "command": command},
        }
    )
    _, issues = validate_show(json.dumps(doc))
    return [(issue.severity, issue.path, issue.message) for issue in issues]


def test_a_binding_may_load_a_cue_and_names_what_it_lacks() -> None:
    load = {"type": "LOAD_CUE", "cueListId": "cl-song", "cueNumber": "2", "filter": ["color"]}
    assert binding_issues(load) == []
    path = "bindings[3].action.command"
    assert binding_issues({**load, "cueListId": "cl-x"}) == [
        ("error", f"{path}.cueListId", "Unknown cue list 'cl-x'")
    ]
    assert binding_issues({**load, "cueNumber": "7"}) == [
        ("warning", f"{path}.cueNumber", "Cue list 'Song' has no cue '7'")
    ]
    assert binding_issues({**load, "filter": ["colour"]})[0][:2] == ("error", f"{path}.filter[0]")


def test_a_binding_that_loads_a_renumbered_cue_is_warned_of(offline: OfflineShow) -> None:
    binding = {
        "id": "b9",
        "surfaceId": "s-midi",
        "input": {"kind": "midiNote", "channel": 1, "note": 9},
        "action": {
            "kind": "command",
            "command": {"type": "LOAD_CUE", "cueListId": "cl-song", "cueNumber": "2"},
        },
    }
    assert offline.submit(cast(Command, {"type": "ADD", "path": ["bindings"], "value": binding})).ok
    reply = offline.execute("cue 1/2 number 3")
    assert reply.ok
    assert "Cue list 'Song' has no cue '2'" in reply.text


# --------------------------------------------------------------- a running show


def eventually(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_a_cue_loads_on_a_running_show() -> None:
    with LiveShow(show_of(load_doc(APPENDIX_A)), output=False) as live:
        eventually(lambda: live.output is not None)
        reply = live.execute("load cue 1/1")
        assert (reply.ok, reply.text) == (True, 'loaded cue 1/1 "Verse": 6 values on 2 fixtures')
        assert live.programmer.selection == ((101, 1), (102, 1))
        assert [v.attribute for v in live.programmer.values][::2] == ["intensity", "color", "pan"]

        def shown() -> list[float | None]:
            output = live.output
            assert output is not None
            return [f.intensity for f in output.fixtures if f.number in (101, 102)]

        eventually(lambda: shown() == [0.4, 0.4])
        assert live.execute("undo").ok
        assert (live.programmer.selection, live.programmer.values) == ((), ())
        eventually(lambda: shown() == [0.0, 0.0])
