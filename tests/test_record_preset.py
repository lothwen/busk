"""RECORD_PRESET: pools, the scope cascade, merge modes, entry order (phase-3-plan §5.5)."""

from __future__ import annotations

from typing import Any, cast

import pytest

from builders import APPENDIX_A, load_doc, preset, preset_value, state_of
from busk.commands.errors import CommandError
from busk.commands.record import record_preset
from busk.commands.types import RecordPresetCmd
from busk.session.ids import CounterIds
from busk.session.programmer import Programmer
from busk.session.state import ShowState
from record_helpers import (
    applied,
    apply_preset,
    program,
    select,
    select_group,
    set_literal,
    set_source,
)

RED = {"r": 1.0, "g": 0.0, "b": 0.0}
GREEN = {"r": 0.0, "g": 1.0, "b": 0.0}


def cmd(pool: str, number: int, scope: str, **fields: Any) -> RecordPresetCmd:
    return cast(
        RecordPresetCmd,
        {"type": "RECORD_PRESET", "pool": pool, "number": number, "scope": scope, **fields},
    )


def three_heads() -> dict[str, Any]:
    """Appendix A with a third spot (fx-mh3, number 103) in the heads group."""
    doc = load_doc(APPENDIX_A)
    mh3 = {**doc["fixtures"][1], "id": "fx-mh3", "number": 103, "name": "MH 3"}
    mh3["patch"] = {"universeId": "u1", "address": 33}
    doc["fixtures"].insert(2, mh3)
    doc["groups"][0]["members"].append({"fixtureId": "fx-mh3", "element": 0})
    return doc


@pytest.fixture
def state() -> ShowState:
    return state_of(three_heads())


def record(
    state: ShowState, programmer: Programmer, command: RecordPresetCmd
) -> tuple[dict[str, Any], str]:
    edit = record_preset(state, state.show, programmer, command, CounterIds())
    show = applied(state, edit)
    found = next(
        p
        for p in show["presets"]
        if p["pool"] == command["pool"] and p["number"] == command["number"]
    )
    return cast(dict[str, Any], found), edit.message


def scoped(values: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """``(attribute, scope…, value)`` per preset value, for compact comparison."""
    result = []
    for value in values:
        scope = value["scope"]
        where = scope.get("profileId") or (
            scope["target"]["fixtureId"] if "target" in scope else "*"
        )
        result.append((value["attribute"], scope["kind"], where, value["value"]))
    return result


def test_a_global_value_when_every_target_agrees(state: ShowState) -> None:
    programmer = program(
        state, select_group("g-mh"), select_group("g-par", "add"), set_literal("color", RED)
    )
    found, message = record(state, programmer, cmd("color", 5, "global", name="Red too"))
    assert scoped(found["values"]) == [("color", "global", "*", RED)]
    assert (found["name"], found["number"], found["pool"]) == ("Red too", 5, "color")
    assert message == "recorded preset color 5 'Red too': 1 value"


def test_global_falls_back_to_profile_then_target(state: ShowState) -> None:
    # Heads agree among themselves (red), the par differs (green): two profile values.
    programmer = program(
        state,
        select_group("g-mh"),
        set_literal("color", RED),
        select("fx-par1"),
        set_literal("color", GREEN),
    )
    found, message = record(state, programmer, cmd("color", 5, "global"))
    assert scoped(found["values"]) == [
        ("color", "profile", "prof-mh", RED),
        ("color", "profile", "prof-par", GREEN),
    ]
    assert (
        message
        == "recorded preset color 5 'Color 5': 2 values; color: 2 profile values (values differ)"
    )
    # Heads disagree too: target values for the heads, by fixture number.
    programmer = program(
        state,
        select_group("g-mh"),
        set_source("pan", {"kind": "spread", "from": -10, "to": 10}),
    )
    found, message = record(state, programmer, cmd("position", 5, "global"))
    assert scoped(found["values"]) == [
        ("pan", "target", "fx-mh1", -10.0),
        ("pan", "target", "fx-mh2", 0.0),
        ("pan", "target", "fx-mh3", 10.0),
    ]
    assert message.endswith("; pan: 3 target values (values differ)")


def test_target_scope_never_cascades(state: ShowState) -> None:
    programmer = program(state, select_group("g-mh"), set_literal("tilt", -15))
    found, message = record(state, programmer, cmd("position", 5, "target"))
    assert [v[1] for v in scoped(found["values"])] == ["target"] * 3
    assert "values differ" not in message


def test_preset_references_are_flattened_to_literals(state: ShowState) -> None:
    programmer = program(state, select_group("g-mh"), apply_preset("pr-aud"))
    found, _ = record(state, programmer, cmd("position", 5, "target"))
    # Audience defines MH 1 and MH 2 only; MH 3 has no value there.
    assert scoped(found["values"]) == [
        ("pan", "target", "fx-mh1", 45.0),
        ("pan", "target", "fx-mh2", -45.0),
        ("tilt", "target", "fx-mh1", -15.0),
        ("tilt", "target", "fx-mh2", -15.0),
    ]


def test_a_pool_records_only_its_families(state: ShowState) -> None:
    programmer = program(
        state,
        select_group("g-mh"),
        set_literal("pan", 3),
        set_literal("color", RED),
        set_literal("gobo1", {"slot": "breakup"}),
        set_literal("shutter", {"slot": "strobe"}),
    )
    found, _ = record(state, programmer, cmd("beam", 1, "profile"))
    assert [(v[0], v[1]) for v in scoped(found["values"])] == [
        ("gobo1", "profile"),
        ("shutter", "profile"),
    ]
    with pytest.raises(CommandError, match=r"^the programmer has no focus values$"):
        record_preset(state, state.show, programmer, cmd("focus", 1, "profile"), CounterIds())
    found, _ = record(state, programmer, cmd("all", 1, "global"))
    assert [v[0] for v in scoped(found["values"])] == ["pan", "color", "gobo1", "shutter"]


@pytest.mark.parametrize(
    ("command", "error"),
    [
        (cmd("color", 1, "global"), "^preset color 1 exists: add merge or replace$"),
        (cmd("color", 9, "global", merge="merge"), "^no preset color 9$"),
    ],
)
def test_record_errors(state: ShowState, command: RecordPresetCmd, error: str) -> None:
    programmer = program(state, select_group("g-mh"), set_literal("color", RED))
    with pytest.raises(CommandError, match=error):
        record_preset(state, state.show, programmer, command, CounterIds())


def test_replace_sets_the_values(state: ShowState) -> None:
    programmer = program(state, select_group("g-mh"), set_literal("color", GREEN))
    found, _ = record(state, programmer, cmd("color", 1, "global", merge="replace"))
    assert scoped(found["values"]) == [("color", "global", "*", GREEN)]
    assert (found["id"], found["name"]) == ("pr-blue", "Blue")


def layered() -> dict[str, Any]:
    """Three heads; preset color 1 holds a global blue, a profile value for the
    heads and target values for MH 1 and the par."""
    doc = three_heads()
    doc["presets"][0] = preset(
        "pr-blue",
        1,
        "color",
        preset_value("color", {"r": 0, "g": 0, "b": 1}),
        preset_value("color", {"r": 0, "g": 0, "b": 0.5}, "profile:prof-mh"),
        preset_value("color", {"r": 0, "g": 1, "b": 1}, "fx-mh1:0"),
        preset_value("color", {"r": 1, "g": 1, "b": 1}, "fx-par1:0"),
        preset_value("cto", 0.5),
    )
    doc["presets"][0]["name"] = "Blue"
    return doc


def test_merge_removes_narrower_entries_that_would_shadow_the_new_value() -> None:
    state = state_of(layered())
    # MH 2 alone, global green: the heads' profile entry would shadow it and goes;
    # MH 1's target entry is not in the programmer and stays; so does the par's.
    programmer = program(state, select("fx-mh2"), set_literal("color", GREEN))
    found, _ = record(state, programmer, cmd("color", 1, "global", merge="merge"))
    assert scoped(found["values"]) == [
        ("color", "global", "*", GREEN),
        ("color", "target", "fx-mh1", {"r": 0.0, "g": 1.0, "b": 1.0}),
        ("color", "target", "fx-par1", {"r": 1.0, "g": 1.0, "b": 1.0}),
        ("cto", "global", "*", 0.5),
    ]


def test_merge_at_profile_scope_keeps_other_profiles() -> None:
    state = state_of(layered())
    programmer = program(state, select_group("g-mh"), set_literal("color", GREEN))
    found, _ = record(state, programmer, cmd("color", 1, "profile", merge="merge"))
    assert scoped(found["values"]) == [
        ("color", "global", "*", {"r": 0.0, "g": 0.0, "b": 1.0}),
        ("color", "profile", "prof-mh", GREEN),  # replaced; MH 1's target entry went
        ("color", "target", "fx-par1", {"r": 1.0, "g": 1.0, "b": 1.0}),
        ("cto", "global", "*", 0.5),
    ]


def test_remove_deletes_every_entry_a_programmer_target_sees() -> None:
    state = state_of(layered())
    programmer = program(state, select("fx-mh2"), set_literal("color", GREEN))
    edit = record_preset(
        state, state.show, programmer, cmd("color", 1, "global", merge="remove"), CounterIds()
    )
    found = applied(state, edit)["presets"][0]
    # MH 2 sees the global and the heads' profile value: both go.
    assert scoped(cast(list[dict[str, Any]], found["values"])) == [
        ("color", "target", "fx-mh1", {"r": 0.0, "g": 1.0, "b": 1.0}),
        ("color", "target", "fx-par1", {"r": 1.0, "g": 1.0, "b": 1.0}),
        ("cto", "global", "*", 0.5),
    ]
    assert edit.message == "removed 2 values from preset color 1"


def test_entry_order_is_deterministic(state: ShowState) -> None:
    programmer = program(
        state,
        select("fx-mh3", "fx-mh1"),
        set_source("tilt", {"kind": "spread", "from": 0, "to": 9}),
        set_source("pan", {"kind": "spread", "from": 0, "to": 9}),
    )
    found, _ = record(state, programmer, cmd("position", 5, "target"))
    assert [(v[0], v[2]) for v in scoped(found["values"])] == [
        ("pan", "fx-mh1"),
        ("pan", "fx-mh3"),
        ("tilt", "fx-mh1"),
        ("tilt", "fx-mh3"),
    ]
