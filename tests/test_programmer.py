"""The programmer: selection, the four value sources, presets, skips, blind (phase-3-plan §5.4)."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, cast

import pytest

from builders import APPENDIX_A, effect_instance, load_doc, state_of, targets
from busk.commands.errors import CommandError
from busk.commands.types import Command
from busk.session.frame import build_frame, programmer_effects
from busk.session.programmer import (
    EMPTY,
    Programmer,
    drop_invalid_effects,
    from_json,
    handle,
    slot_key,
    split_slot_key,
    to_json,
)
from busk.session.state import ShowState

MH1, MH2, PAR = (
    {"fixtureId": "fx-mh1", "element": 0},
    {"fixtureId": "fx-mh2", "element": 0},
    {"fixtureId": "fx-par1", "element": 0},
)


@pytest.fixture(scope="module")
def state() -> ShowState:
    return state_of(load_doc(APPENDIX_A))


def run(state: ShowState, programmer: Programmer, *commands: dict[str, Any]) -> Programmer:
    for command in commands:
        programmer = handle(state, programmer, cast(Command, command)).programmer
    return programmer


def message(state: ShowState, programmer: Programmer, command: dict[str, Any]) -> str:
    return handle(state, programmer, cast(Command, command)).message


def select(*refs: dict[str, Any], mode: str = "replace") -> dict[str, Any]:
    return {"type": "SELECT", "targets": {"kind": "targets", "refs": list(refs)}, "mode": mode}


def group(ident: str, mode: str = "replace") -> dict[str, Any]:
    return {"type": "SELECT", "targets": {"kind": "group", "groupId": ident}, "mode": mode}


def set_attr(attribute: str, source: dict[str, Any]) -> dict[str, Any]:
    return {"type": "SET_ATTRIBUTE", "attribute": attribute, "value": source}


def literal(value: Any) -> dict[str, Any]:
    return {"kind": "literal", "value": value}


def values(programmer: Programmer) -> dict[str, Any]:
    return {key: dict(source) for key, source in programmer.values.items()}


# ----------------------------------------------------------------- selection


def test_selection_keeps_order_under_add_and_remove(state: ShowState) -> None:
    p = run(state, EMPTY, select(MH2, MH1))
    assert p.selection == (MH2, MH1)
    p = run(state, p, select(PAR, MH1, mode="add"))  # MH1 is already selected
    assert p.selection == (MH2, MH1, PAR)
    p = run(state, p, select(MH2, mode="remove"))
    assert p.selection == (MH1, PAR)
    p = run(state, p, group("g-mh", mode="add"))  # appends MH2 only
    assert p.selection == (MH1, PAR, MH2)
    assert message(state, p, select(MH1, MH1)) == "1 target selected"


def test_a_group_expands_to_its_members_in_order(state: ShowState) -> None:
    assert run(state, EMPTY, group("g-mh")).selection == (MH1, MH2)


def test_select_playback_selects_its_first_cue_targets(state: ShowState) -> None:
    p = run(state, EMPTY, {"type": "SELECT_PLAYBACK", "playbackId": "pb-blue", "mode": "replace"})
    assert p.selection == (MH1, MH2, PAR)
    p = run(state, p, {"type": "SELECT_PLAYBACK", "playbackId": "pb-pulse", "mode": "remove"})
    assert p.selection == (PAR,)  # Pulse's cue has no entries, but its effect drives the heads


@pytest.mark.parametrize(
    ("command", "error"),
    [
        (group("g-nope"), "no group 'g-nope'"),
        (select({"fixtureId": "fx-9", "element": 0}), "no fixture 'fx-9'"),
        (select({"fixtureId": "fx-mh1", "element": 1}), "fixture 'fx-mh1' has no element 1"),
        (
            {"type": "SELECT_PLAYBACK", "playbackId": "pb-9", "mode": "add"},
            "no playback 'pb-9'",
        ),
    ],
)
def test_selection_errors(state: ShowState, command: dict[str, Any], error: str) -> None:
    with pytest.raises(CommandError, match=f"^{error}$"):
        handle(state, EMPTY, cast(Command, command))


# ------------------------------------------------------------------- values


def test_a_literal_is_stored_for_every_target_that_has_the_slot(state: ShowState) -> None:
    p = run(state, EMPTY, select(MH1, PAR, MH2))
    assert message(state, p, set_attr("pan", literal(30))) == "pan: 2 targets; skipped 1 no pan"
    p = run(state, p, set_attr("pan", literal(30)))
    assert values(p) == {
        "fx-mh1:0/pan": {"kind": "literal", "value": 30},
        "fx-mh2:0/pan": {"kind": "literal", "value": 30},
    }
    # Setting again keeps each key's position (the programmer's target order).
    p = run(state, p, select(MH2), set_attr("pan", literal(-5)))
    assert list(values(p)) == ["fx-mh1:0/pan", "fx-mh2:0/pan"]
    assert values(p)["fx-mh2:0/pan"]["value"] == -5


def test_a_colour_reaches_every_colour_target(state: ShowState) -> None:
    p = run(state, EMPTY, group("g-mh"), group("g-par", "add"))
    p = run(state, p, set_attr("color", literal({"r": 0, "g": 0, "b": 1})))
    assert sorted(values(p)) == ["fx-mh1:0/color", "fx-mh2:0/color", "fx-par1:0/color"]


def test_a_spread_is_evaluated_per_target_by_selection_index(state: ShowState) -> None:
    # n = 3 selected: u = 0, 0.5, 1. The par has no pan but keeps its position.
    p = run(state, EMPTY, select(MH1, PAR, MH2))
    p = run(state, p, set_attr("pan", {"kind": "spread", "from": -45, "to": 45}))
    assert values(p) == {
        "fx-mh1:0/pan": {"kind": "literal", "value": -45},
        "fx-mh2:0/pan": {"kind": "literal", "value": 45},
    }
    p = run(state, p, set_attr("pan", {"kind": "spread", "from": -45, "to": 45, "curve": "center"}))
    assert [v["value"] for v in values(p).values()] == [-45, -45]
    p = run(state, EMPTY, select(MH1, MH2, PAR))
    p = run(
        state,
        p,
        set_attr(
            "color",
            {
                "kind": "spread",
                "from": {"r": 1, "g": 0, "b": 0},
                "to": {"r": 0, "g": 0, "b": 1, "w": 1},
            },
        ),
    )
    assert values(p)["fx-mh2:0/color"]["value"] == {
        "r": 0.5,
        "g": 0.0,
        "b": 0.5,
    }  # no w: one end lacks it
    assert values(p)["fx-par1:0/color"]["value"] == {"r": 0.0, "g": 0.0, "b": 1.0}


def test_a_per_target_source_stores_each_targets_own_value(state: ShowState) -> None:
    p = run(state, EMPTY, group("g-mh"))
    msg = message(state, p, set_attr("tilt", {"kind": "perTarget", "values": {"fx-mh2:0": 12}}))
    assert msg == "tilt: 1 target; skipped 1 no value"
    p = run(state, p, set_attr("tilt", {"kind": "perTarget", "values": {"fx-mh2:0": 12}}))
    assert values(p) == {"fx-mh2:0/tilt": {"kind": "literal", "value": 12}}


def test_a_preset_source_is_kept_as_a_reference(state: ShowState) -> None:
    p = run(state, EMPTY, select(MH1, PAR))
    msg = message(state, p, set_attr("pan", {"kind": "preset", "presetId": "pr-aud"}))
    assert msg == "pan: 1 target; skipped 1 no pan"
    p = run(state, p, set_attr("pan", {"kind": "preset", "presetId": "pr-aud"}))
    assert values(p) == {"fx-mh1:0/pan": {"kind": "preset", "presetId": "pr-aud"}}


def test_discrete_values_skip_targets_without_the_option(state: ShowState) -> None:
    p = run(state, EMPTY, select(MH1, PAR))
    assert message(state, p, set_attr("gobo1", literal({"slot": "breakup"}))) == (
        "gobo1: 1 target; skipped 1 no gobo1"
    )
    with pytest.raises(
        CommandError,
        match=r"no selected target takes this gobo1 \(1 no gobo1, 1 option not offered\)",
    ):
        handle(state, p, cast(Command, set_attr("gobo1", literal({"slot": "dots"}))))
    with pytest.raises(CommandError, match="option not offered"):
        handle(state, p, cast(Command, set_attr("gobo1", literal({"wheel": "w9", "slot": "open"}))))


@pytest.mark.parametrize(
    ("command", "error"),
    [
        (set_attr("intensity", literal(1.2)), "intensity must be within 0..1, got 1.2"),
        (set_attr("intensity", literal(math.nan)), "intensity: Input should be a finite number"),
        (set_attr("pan", literal(math.inf)), "pan: Input should be a finite number"),
        (
            set_attr("color", literal({"r": 1.5, "g": 0, "b": 0})),
            "color: Input should be less than or equal to 1",
        ),
        (set_attr("color", literal(0.5)), "color needs a colour {r, g, b}"),
        (
            set_attr("gobo1", {"kind": "spread", "from": {"slot": "open"}, "to": {"slot": "open"}}),
            "gobo1 is discrete and cannot be spread",
        ),
        (
            set_attr("control", literal({"slot": "none"})),
            r"control attributes cannot be programmed \(§5.5\)",
        ),
        (set_attr("sparkle", literal(1)), "unknown attribute 'sparkle'"),
        (set_attr("pan", {"kind": "preset", "presetId": "pr-9"}), "no preset 'pr-9'"),
    ],
)
def test_invalid_values_are_errors(state: ShowState, command: dict[str, Any], error: str) -> None:
    p = run(state, EMPTY, group("g-mh"))
    with pytest.raises(CommandError, match=f"^{error}$"):
        handle(state, p, cast(Command, command))


def test_nothing_selected_is_an_error(state: ShowState) -> None:
    with pytest.raises(CommandError, match=r"^nothing selected$"):
        handle(state, EMPTY, cast(Command, set_attr("pan", literal(1))))
    with pytest.raises(CommandError, match=r"^nothing selected$"):
        handle(state, EMPTY, cast(Command, {"type": "APPLY_PRESET", "presetId": "pr-blue"}))


# ------------------------------------------------------------------- presets


def test_apply_preset_references_what_the_preset_defines_per_target(state: ShowState) -> None:
    # Audience defines pan and tilt for the heads only; the par gets nothing.
    p = run(state, EMPTY, select(MH1, PAR, MH2))
    assert message(state, p, {"type": "APPLY_PRESET", "presetId": "pr-aud"}) == (
        "Audience: 4 values on 2 targets"
    )
    p = run(state, p, {"type": "APPLY_PRESET", "presetId": "pr-aud"})
    ref = {"kind": "preset", "presetId": "pr-aud"}
    assert values(p) == {
        "fx-mh1:0/pan": ref,
        "fx-mh1:0/tilt": ref,
        "fx-mh2:0/pan": ref,
        "fx-mh2:0/tilt": ref,
    }


def test_apply_preset_that_defines_nothing_is_an_error(state: ShowState) -> None:
    p = run(state, EMPTY, select(PAR))
    with pytest.raises(
        CommandError, match=r"^preset 'Audience' defines nothing for the selection$"
    ):
        handle(state, p, cast(Command, {"type": "APPLY_PRESET", "presetId": "pr-aud"}))


# --------------------------------------------------------------- clear, blind


def test_clear_keeps_blind_and_blind_keeps_values(state: ShowState) -> None:
    p = run(state, EMPTY, group("g-mh"), set_attr("pan", literal(1)), {"type": "BLIND", "on": True})
    assert p.blind
    assert values(p)
    p = run(state, p, {"type": "CLEAR_PROGRAMMER"})
    assert p == Programmer(blind=True)
    assert run(state, p, {"type": "BLIND", "on": False}) == EMPTY


def test_values_on_other_fixtures_are_kept(state: ShowState) -> None:
    """A value whose slot no longer exists stays (dormant) until cleared."""
    p = Programmer(values={"fx-gone:0/pan": {"kind": "literal", "value": 3}})  # type: ignore[arg-type]
    p = run(state, p, group("g-mh"), set_attr("pan", literal(1)))
    assert list(values(p)) == ["fx-gone:0/pan", "fx-mh1:0/pan", "fx-mh2:0/pan"]


# ---------------------------------------------------------------- keys, JSON


def test_slot_keys() -> None:
    assert slot_key({"fixtureId": "a:b/c", "element": 2}, "pan") == "a:b/c:2/pan"  # type: ignore[typeddict-item]
    assert split_slot_key("a:b/c:2/pan") == ({"fixtureId": "a:b/c", "element": 2}, "pan")
    assert split_slot_key("fx:0/sparkle") is None
    assert split_slot_key("fx/pan") is None


def test_json_round_trip_and_lenient_restore(state: ShowState) -> None:
    p = run(
        state, EMPTY, group("g-mh"), set_attr("pan", literal(10)), {"type": "BLIND", "on": True}
    )
    assert from_json(to_json(p)) == (p, [])
    data = to_json(p)
    data["values"]["fx-mh1:0/tilt"] = {"kind": "spread"}  # not storable
    data["values"]["nonsense"] = {"kind": "literal", "value": 1}
    restored, dropped = from_json(data)
    assert restored == p
    assert dropped == ["programmer.values['fx-mh1:0/tilt']", "programmer.values['nonsense']"]


def test_the_fade_time_round_trips_and_old_or_bad_values_fall_back(state: ShowState) -> None:
    p = run(state, EMPTY, group("g-mh"), {"type": "PROGRAMMER_FADE", "time": 2.5})
    assert p.fadeTime == 2.5
    assert p.same_content(replace(p, fadeTime=0.0))  # a mode, not content
    assert from_json(to_json(p)) == (p, [])
    data = to_json(p)
    del data["fadeTime"]  # a file from before Phase 4
    assert from_json(data) == (replace(p, fadeTime=0.0), [])
    for bad in (-1, True, "2", float("inf")):
        data["fadeTime"] = bad
        assert from_json(data) == (replace(p, fadeTime=0.0), ["programmer.fadeTime"])


# ------------------------------------------------------------ effects (Phase 5)

MH = {"kind": "group", "groupId": "g-mh"}


def pulse(ident: str = "fx1", **fields: Any) -> dict[str, Any]:
    """Appendix A's pulse template on the heads at size 0.5."""
    return effect_instance(ident, "ef-pulse", MH, **{"size": 0.5, **fields})


def add(effect: dict[str, Any]) -> dict[str, Any]:
    return {"type": "ADD_EFFECT", "effect": effect}


def remove(ident: str | None = None) -> dict[str, Any]:
    return {"type": "REMOVE_EFFECT"} if ident is None else {"type": "REMOVE_EFFECT", "id": ident}


def ids(programmer: Programmer) -> list[str]:
    return [effect["id"] for effect in programmer.effects]


def test_add_effect_appends_and_replaces_by_id_in_place(state: ShowState) -> None:
    p = run(state, EMPTY, add(pulse("fx1")), add(pulse("fx2")))
    assert ids(p) == ["fx1", "fx2"]
    assert not p.same_content(EMPTY)  # effects are content
    change = handle(state, p, cast(Command, add(pulse("fx1", size=0.9))))
    assert [(e["id"], e["size"]) for e in change.programmer.effects] == [("fx1", 0.9), ("fx2", 0.5)]
    assert (change.message, change.writtenEffects) == (
        "replaced effect 'fx1' on 2 targets",
        frozenset({"fx1"}),
    )
    assert message(state, EMPTY, add(pulse())) == "added effect 'fx1' on 2 targets"
    command = add(pulse("fx3", targets=targets("fx-par1")))
    stored = run(state, EMPTY, command)
    command["effect"]["size"] = 0.1  # the programmer keeps its own copy
    assert stored.effects[0]["size"] == 0.5


def test_remove_effect_removes_one_or_all(state: ShowState) -> None:
    p = run(state, EMPTY, add(pulse("fx1")), add(pulse("fx2")))
    assert ids(run(state, p, remove("fx1"))) == ["fx2"]
    assert message(state, p, remove("fx1")) == "removed effect 'fx1'"
    assert run(state, p, remove()).effects == ()
    assert message(state, p, remove()) == "removed 2 effects"
    with pytest.raises(CommandError, match="the programmer has no effect 'fx9'"):
        handle(state, p, cast(Command, remove("fx9")))


def test_clear_removes_the_effects_too(state: ShowState) -> None:
    p = run(state, EMPTY, group("g-mh"), set_attr("pan", literal(10)), add(pulse()))
    p = run(state, p, {"type": "BLIND", "on": True}, {"type": "CLEAR_PROGRAMMER"})
    assert (p.selection, values(p), p.effects, p.blind) == ((), {}, (), True)


@pytest.mark.parametrize(
    ("fields", "error"),
    [
        ({"templateId": "ef-nothing"}, "effect 'fx1': .*ef-nothing"),
        ({"targets": {"kind": "group", "groupId": "g-nothing"}}, "effect 'fx1': .*g-nothing"),
        ({"targets": targets("fx-ghost")}, "effect 'fx1': .*fx-ghost"),
        (
            {"rate": {"kind": "bpm", "masterId": "m-nothing", "multiplier": 1.0}},
            "effect 'fx1': .*m-nothing",
        ),
        ({"size": 1.5}, "effect 'fx1': "),  # a multiply layer's size is a fraction
        ({"targets": targets()}, "effect 'fx1' has no targets"),
    ],
)
def test_an_effect_that_does_not_fit_the_show_is_an_error(
    state: ShowState, fields: dict[str, Any], error: str
) -> None:
    with pytest.raises(CommandError, match=error) as caught:
        handle(state, EMPTY, cast(Command, add(pulse(**fields))))
    assert caught.value.issues or "no targets" in error


def without_the_pulse_template() -> ShowState:
    """Appendix A without ef-pulse (and the cue instance that uses it)."""
    doc = load_doc(APPENDIX_A)
    doc["effects"] = []
    for cue_list in doc["cueLists"]:
        for cue in cue_list["cues"]:
            cue["effects"] = []
    return state_of(doc)


def test_an_effect_whose_template_vanished_stays_dormant(state: ShowState) -> None:
    p = run(state, EMPTY, add(pulse("fx1")), add(pulse("fx2", targets=targets("fx-par1"))))
    assert [effect.key for effect in programmer_effects(state, p.effects)] == ["fx1", "fx2"]
    gone = without_the_pulse_template()
    frame = build_frame(gone, p, {})
    assert (frame.effects, frame.touchedEffects) == ((), frozenset())
    assert ids(p) == ["fx1", "fx2"]  # still held: undoing the delete wakes them
    kept, dropped = drop_invalid_effects(gone, p)  # what crash recovery does instead
    assert kept.effects == ()
    assert len(dropped) == 2
    assert dropped[0].startswith("programmer effect 'fx1': ")


def test_effects_round_trip_through_json_and_bad_ones_are_dropped(state: ShowState) -> None:
    p = run(state, EMPTY, add(pulse("fx1")), add(pulse("fx2", size=0.3, sizeFadeIn=1.0)))
    assert from_json(to_json(p)) == (p, [])
    data = to_json(p)
    data["effects"] += [{"id": "fx-bad"}, dict(data["effects"][0])]
    assert from_json(data) == (
        p,
        ["programmer.effects[2]", "programmer.effects[3] (a second 'fx1')"],
    )
    del data["effects"]  # a file from before Phase 5
    assert from_json(data) == (replace(p, effects=()), [])
    data["effects"] = {"fx1": pulse()}
    assert from_json(data) == (replace(p, effects=()), ["programmer.effects"])
