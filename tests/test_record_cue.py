"""RECORD_CUE: group cover, preset references, merge restriction (phase-3-plan §5.5),
and recording changes only into a tracking list (phase-4-plan decision 17)."""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any, cast

import numpy as np
import pytest

from builders import (
    APPENDIX_A,
    effect_instance,
    effect_layer,
    effect_template,
    load_doc,
    slot_of,
    state_of,
)
from busk.commands.errors import CommandError
from busk.commands.record import record_cue
from busk.commands.types import RecordCueCmd
from busk.compiler.compile import compile_show
from busk.compiler.cues import CompiledCue
from busk.session.ids import CounterIds
from busk.session.programmer import Programmer
from busk.session.state import ShowState
from record_helpers import (
    add_effect,
    applied,
    apply_preset,
    ids,
    program,
    select,
    select_group,
    set_literal,
    set_source,
)

BLUE = {"kind": "preset", "presetId": "pr-blue"}


def group(ident: str) -> dict[str, Any]:
    return {"kind": "group", "groupId": ident}


def refs(*fixture_ids: str) -> dict[str, Any]:
    return {"kind": "targets", "refs": [{"fixtureId": f, "element": 0} for f in fixture_ids]}


def cmd(cue_list: str = "cl-new", **fields: Any) -> RecordCueCmd:
    return cast(RecordCueCmd, {"type": "RECORD_CUE", "cueListId": cue_list, **fields})


@pytest.fixture
def appendix() -> dict[str, Any]:
    """Appendix A plus an empty cue list ``cl-new`` (number 30)."""
    doc = load_doc(APPENDIX_A)
    doc["cueLists"].append(
        {
            "id": "cl-new",
            "number": 30,
            "name": "New",
            "mode": "sequence",
            "tracking": False,
            "wrap": False,
            "releaseAtEnd": False,
            "cues": [],
        }
    )
    return doc


@pytest.fixture
def state(appendix: dict[str, Any]) -> ShowState:
    return state_of(appendix)


def record(state: ShowState, programmer: Programmer, command: RecordCueCmd) -> dict[str, Any]:
    """Record; return the touched cue list of the resulting (validated) show."""
    edit = record_cue(state, state.show, programmer, command, CounterIds())
    show = applied(state, edit)
    return cast(
        dict[str, Any], next(cl for cl in show["cueLists"] if cl["id"] == command["cueListId"])
    )


# ------------------------------------------------------------- worked cases


def test_rebuilding_appendix_a_blue_cue_keeps_group_and_preset_references(state: ShowState) -> None:
    programmer = program(
        state, select_group("g-mh"), select_group("g-par", "add"), apply_preset("pr-blue")
    )
    cue = record(state, programmer, cmd())["cues"][0]
    assert cue["entries"] == [
        {"targets": group("g-mh"), "attribute": "color", "value": BLUE},
        {"targets": group("g-par"), "attribute": "color", "value": BLUE},
    ]
    # Exactly the two entries of Appendix A's Blue cue.
    blue = next(cl for cl in state.show["cueLists"] if cl["id"] == "cl-blue")["cues"][0]
    assert cue["entries"] == blue["entries"]
    assert (cue["number"], cue["name"], cue["effects"], cue["trigger"]) == (
        "1",
        "Cue 1",
        [],
        {"kind": "go"},
    )
    assert cue["timing"] == {
        "fadeIn": 0,
        "fadeOut": 0,
        "delayIn": 0,
        "delayOut": 0,
        "curve": "linear",
    }


def test_merging_into_the_blue_cue_splits_the_overridden_group(state: ShowState) -> None:
    programmer = program(state, select("fx-mh1"), set_literal("color", {"r": 1, "g": 0, "b": 0}))
    cue = record(state, programmer, cmd("cl-blue", cueNumber="1", merge="merge"))["cues"][0]
    assert cue["entries"] == [
        {"targets": refs("fx-mh2"), "attribute": "color", "value": BLUE},
        {"targets": group("g-par"), "attribute": "color", "value": BLUE},
        {
            "targets": refs("fx-mh1"),
            "attribute": "color",
            "value": {"kind": "literal", "value": {"r": 1, "g": 0, "b": 0}},
        },
    ]
    assert (cue["id"], cue["name"], cue["timing"]["fadeIn"]) == ("c-blue", "Blue", 1)


# ------------------------------------------------------------------ entries


def test_literals_that_differ_become_per_target(state: ShowState) -> None:
    programmer = program(
        state, select_group("g-mh"), set_source("pan", {"kind": "spread", "from": -10, "to": 10})
    )
    cue = record(state, programmer, cmd())["cues"][0]
    assert cue["entries"] == [
        {
            "targets": group("g-mh"),
            "attribute": "pan",
            "value": {"kind": "perTarget", "values": {"fx-mh1:0": -10, "fx-mh2:0": 10}},
        },
    ]


def test_entries_follow_registry_order_whatever_the_programmer_order(state: ShowState) -> None:
    programmer = program(
        state,
        select_group("g-mh"),
        set_literal("gobo1", {"slot": "breakup"}),
        set_literal("pan", 5),
        set_literal("intensity", 1),
    )
    cue = record(state, programmer, cmd())["cues"][0]
    assert [entry["attribute"] for entry in cue["entries"]] == ["intensity", "pan", "gobo1"]


def test_freeze_records_explicit_targets(state: ShowState) -> None:
    programmer = program(state, select_group("g-mh"), set_literal("intensity", 0.5))
    cue = record(state, programmer, cmd(freeze=True))["cues"][0]
    assert cue["entries"] == [
        {
            "targets": refs("fx-mh1", "fx-mh2"),
            "attribute": "intensity",
            "value": {"kind": "literal", "value": 0.5},
        }
    ]


def test_preset_and_literal_buckets_are_covered_separately(state: ShowState) -> None:
    programmer = program(
        state,
        select("fx-mh1", "fx-par1"),
        apply_preset("pr-blue"),
        select("fx-mh2"),
        set_literal("color", {"r": 0, "g": 1, "b": 0}),
    )
    cue = record(state, programmer, cmd())["cues"][0]
    assert cue["entries"] == [
        {"targets": group("g-par"), "attribute": "color", "value": BLUE},
        {"targets": refs("fx-mh1"), "attribute": "color", "value": BLUE},
        {
            "targets": refs("fx-mh2"),
            "attribute": "color",
            "value": {"kind": "literal", "value": {"r": 0, "g": 1, "b": 0}},
        },
    ]


def test_group_cover_ties_prefer_fewest_members_then_lowest_number(
    appendix: dict[str, Any],
) -> None:
    members = [{"fixtureId": f, "element": 0} for f in ("fx-mh1", "fx-mh2")]
    appendix["groups"] += [
        # "All" covers both heads too (the par has no pan), but has more members.
        {
            "id": "g-all",
            "number": 3,
            "name": "All",
            "members": [*members, {"fixtureId": "fx-par1", "element": 0}],
        },
        # Same members as g-mh, but a lower number than g-twin: g-mh (1) wins.
        {"id": "g-twin", "number": 7, "name": "Twin", "members": list(reversed(members))},
    ]
    state = state_of(appendix)
    programmer = program(state, select_group("g-all"), set_literal("pan", 0))
    assert record(state, programmer, cmd())["cues"][0]["entries"] == [
        {"targets": group("g-mh"), "attribute": "pan", "value": {"kind": "literal", "value": 0}}
    ]
    # Intensity: g-all covers all three and is the biggest cover.
    programmer = program(state, select_group("g-all"), set_literal("intensity", 1))
    assert record(state, programmer, cmd())["cues"][0]["entries"] == [
        {
            "targets": group("g-all"),
            "attribute": "intensity",
            "value": {"kind": "literal", "value": 1},
        }
    ]


def test_a_filter_records_only_its_families(state: ShowState) -> None:
    programmer = program(
        state, select_group("g-mh"), set_literal("pan", 3), set_literal("intensity", 1)
    )
    cue = record(state, programmer, cmd(filter=["position"]))["cues"][0]
    assert [entry["attribute"] for entry in cue["entries"]] == ["pan"]
    with pytest.raises(
        CommandError, match=r"^the programmer has no beam values or effects to record$"
    ):
        record_cue(state, state.show, programmer, cmd(filter=["beam"]), CounterIds())


# --------------------------------------------------------------- numbering


def test_cue_numbers_default_to_the_next_whole_number(state: ShowState) -> None:
    programmer = program(state, select_group("g-mh"), set_literal("intensity", 1))
    assert record(state, programmer, cmd())["cues"][0]["number"] == "1"
    song = record(state, programmer, cmd("cl-song"))  # cues "1", "2"
    assert [c["number"] for c in song["cues"]] == ["1", "2", "3"]


def test_after_cue_3_5_comes_4(appendix: dict[str, Any]) -> None:
    appendix["cueLists"][0]["cues"][1]["number"] = "3.5"
    state = state_of(appendix)
    programmer = program(state, select_group("g-mh"), set_literal("intensity", 1))
    song = record(state, programmer, cmd("cl-song"))
    assert [c["number"] for c in song["cues"]] == ["1", "3.5", "4"]


def test_a_new_cue_is_inserted_in_number_order(state: ShowState) -> None:
    programmer = program(state, select_group("g-mh"), set_literal("intensity", 1))
    edit = record_cue(
        state, state.show, programmer, cmd("cl-song", cueNumber="1.5", name="Bridge"), CounterIds()
    )
    song = next(cl for cl in applied(state, edit)["cueLists"] if cl["id"] == "cl-song")
    assert [(c["number"], c["name"]) for c in song["cues"]] == [
        ("1", "Verse"),
        ("1.5", "Bridge"),
        ("2", "Chorus"),
    ]
    assert edit.message == "recorded cue 1/1.5: 1 entry"
    assert edit.warnings == ()  # Phase 3 warned that only the first cue plays


# ---------------------------------------------------------- merge modes


@pytest.mark.parametrize(
    ("command", "error"),
    [
        (cmd("cl-blue", cueNumber="1"), "^cue 10/1 exists: add merge or replace$"),
        (cmd("cl-blue", cueNumber="2", merge="merge"), "^no cue 10/2$"),
        (cmd("cl-nope"), "^no cue list 'cl-nope'$"),
        (cmd(cueNumber="1.x"), "^invalid cue number '1.x'"),
    ],
)
def test_record_errors(state: ShowState, command: RecordCueCmd, error: str) -> None:
    programmer = program(state, select_group("g-mh"), set_literal("intensity", 1))
    with pytest.raises(CommandError, match=error):
        record_cue(state, state.show, programmer, command, CounterIds())


def test_an_empty_programmer_cannot_record(state: ShowState) -> None:
    with pytest.raises(CommandError, match=r"^the programmer has no values or effects to record$"):
        record_cue(state, state.show, Programmer(), cmd(), CounterIds())


def test_replace_swaps_entries_and_keeps_the_rest(state: ShowState) -> None:
    programmer = program(state, select("fx-mh1"), set_literal("intensity", 1))
    cue = record(
        state, programmer, cmd("cl-song", cueNumber="1", merge="replace", name="New verse")
    )["cues"][0]
    assert cue["entries"] == [
        {
            "targets": refs("fx-mh1"),
            "attribute": "intensity",
            "value": {"kind": "literal", "value": 1},
        }
    ]
    assert (cue["id"], cue["number"], cue["name"], cue["timing"]["fadeIn"]) == (
        "c-verse",
        "1",
        "New verse",
        2,
    )


def test_remove_restricts_without_appending(state: ShowState) -> None:
    programmer = program(state, select("fx-mh2"), set_literal("color", {"r": 0, "g": 0, "b": 0}))
    cue = record(state, programmer, cmd("cl-blue", cueNumber="1", merge="remove"))["cues"][0]
    assert cue["entries"] == [
        {"targets": refs("fx-mh1"), "attribute": "color", "value": BLUE},
        {"targets": group("g-par"), "attribute": "color", "value": BLUE},
    ]


def test_an_entry_whose_targets_are_all_covered_is_dropped(state: ShowState) -> None:
    programmer = program(
        state, select_group("g-par"), set_literal("color", {"r": 1, "g": 1, "b": 0})
    )
    cue = record(state, programmer, cmd("cl-blue", cueNumber="1", merge="merge"))["cues"][0]
    assert cue["entries"] == [
        {"targets": group("g-mh"), "attribute": "color", "value": BLUE},
        {
            "targets": group("g-par"),
            "attribute": "color",
            "value": {"kind": "literal", "value": {"r": 1, "g": 1, "b": 0}},
        },
    ]


def test_restricting_a_spread_keeps_the_exact_values(state: ShowState) -> None:
    """Verse spreads pan −20 → 20 over the heads; overriding MH 1 leaves MH 2
    with a per-target value whose lanes are bit-identical to the spread's."""
    programmer = program(state, select("fx-mh1"), set_literal("pan", 0.5))
    before = state.compiled
    song = record(state, programmer, cmd("cl-song", cueNumber="1", merge="merge"))
    entries = song["cues"][0]["entries"]
    assert entries[2] == {
        "targets": refs("fx-mh2"),
        "attribute": "pan",
        "value": {"kind": "perTarget", "values": {"fx-mh2:0": 20.0}},
    }
    assert entries[-1] == {
        "targets": refs("fx-mh1"),
        "attribute": "pan",
        "value": {"kind": "literal", "value": 0.5},
    }
    doc = cast(dict[str, Any], dict(state.show))
    doc["cueLists"] = [song, *state.show["cueLists"][1:]]
    after = compile_show(doc)  # type: ignore[arg-type]
    lane = slot_of(before, "fx-mh2", "pan").laneOffset
    old, new = before.cueLists["cl-song"].cues[0], after.cueLists["cl-song"].cues[0]
    assert (
        new.ltpValues[np.searchsorted(new.ltpLanes, lane)]
        == old.ltpValues[np.searchsorted(old.ltpLanes, lane)]
    )


def test_restricting_a_mid_list_spread_uses_original_indices(appendix: dict[str, Any]) -> None:
    three = [{"fixtureId": f, "element": 0} for f in ("fx-mh1", "fx-par1", "fx-mh2")]
    appendix["groups"].append({"id": "g-3", "number": 3, "name": "Three", "members": three})
    appendix["cueLists"][2]["cues"][0]["entries"] = [
        {
            "targets": group("g-3"),
            "attribute": "pan",
            "value": {"kind": "spread", "from": 0, "to": 90},
        },
        {
            "targets": group("g-3"),
            "attribute": "tilt",
            "value": {"kind": "perTarget", "values": {"fx-mh1:0": 1, "fx-mh2:0": 2}},
        },
    ]
    state = state_of(appendix)
    programmer = program(state, select("fx-mh1"), set_literal("pan", 7), set_literal("tilt", 7))
    cue = record(state, programmer, cmd("cl-pulse", cueNumber="1", merge="remove"))["cues"][0]
    # The par (index 1 of 3, no pan) keeps its position: MH 2 is k = 2 → 90.
    assert cue["entries"] == [
        {
            "targets": refs("fx-par1", "fx-mh2"),
            "attribute": "pan",
            "value": {"kind": "perTarget", "values": {"fx-par1:0": 45.0, "fx-mh2:0": 90.0}},
        },
        {
            "targets": refs("fx-par1", "fx-mh2"),
            "attribute": "tilt",
            "value": {"kind": "perTarget", "values": {"fx-mh2:0": 2}},
        },
    ]


# ------------------------------------------------- tracking (decision 17)
#
# Appendix A's cl-song tracks: Verse (1) sets the heads to intensity 0.4,
# colour {1, 0.8, 0.6} and a pan spread −20 → 20; Chorus (2) sets intensity
# 1.0 and colour white, and tracks Verse's pan.

WHITE = {"r": 1.0, "g": 1.0, "b": 1.0}
SPREAD_PAN = {"kind": "perTarget", "values": {"fx-mh1:0": -20.0, "fx-mh2:0": 20.0}}


def song_list(show: Any) -> dict[str, Any]:
    return cast(dict[str, Any], next(cl for cl in show["cueLists"] if cl["id"] == "cl-song"))


def same_state(a: CompiledCue, b: CompiledCue) -> bool:
    """Whether two compiled cues hold the same tracked state (lanes and values)."""
    pairs = [
        (a.htpPos, b.htpPos),
        (a.htpValues, b.htpValues),
        (a.ltpLanes, b.ltpLanes),
        (a.ltpValues, b.ltpValues),
        (a.snapLanes, b.snapLanes),
        (a.snapValues, b.snapValues),
    ]
    return all(np.array_equal(x, y, equal_nan=True) for x, y in pairs)


def test_values_equal_to_the_inherited_ones_are_not_stored(appendix: dict[str, Any]) -> None:
    state = state_of(appendix)
    programmer = program(
        state,
        select_group("g-mh"),
        set_literal("intensity", 1.0),  # Chorus's
        set_literal("color", WHITE),  # Chorus's, encoded with NaN extras
        set_source("pan", SPREAD_PAN),  # Verse's spread, tracked through Chorus
        set_literal("tilt", 30),  # new
    )
    edit = record_cue(state, state.show, programmer, cmd("cl-song"), CounterIds())
    assert edit.message == "recorded cue 1/3: 1 entry; 6 values tracked from cue 1/2"
    after = applied(state, edit)
    assert song_list(after)["cues"][2]["entries"] == [
        {"targets": group("g-mh"), "attribute": "tilt", "value": {"kind": "literal", "value": 30}}
    ]
    # The cue holds exactly what it would hold had every value been stored.
    appendix["cueLists"][0]["tracking"] = False  # a non-tracking list stores everything
    flat = state_of(appendix)
    every = song_list(applied(flat, record_cue(flat, flat.show, programmer, cmd("cl-song"), ids())))
    assert len(every["cues"][2]["entries"]) == 4
    every["tracking"] = True
    full = cast(dict[str, Any], dict(after))
    full["cueLists"] = [every, *after["cueLists"][1:]]
    tracked = compile_show(after).cueLists["cl-song"].cues[2]
    stored = compile_show(full).cueLists["cl-song"].cues[2]  # type: ignore[arg-type]
    assert same_state(tracked, stored)


def test_a_cue_whose_values_all_track_is_recorded_without_entries(state: ShowState) -> None:
    programmer = program(state, select_group("g-mh"), set_literal("intensity", 1.0))
    edit = record_cue(state, state.show, programmer, cmd("cl-song"), CounterIds())
    assert edit.message == "recorded cue 1/3: 0 entries; 2 values tracked from cue 1/2"
    assert song_list(applied(state, edit))["cues"][2]["entries"] == []


def test_merge_removes_the_cues_own_entry_for_an_inherited_value(state: ShowState) -> None:
    programmer = program(state, select_group("g-mh"), set_literal("intensity", 0.4))
    edit = record_cue(
        state, state.show, programmer, cmd("cl-song", cueNumber="2", merge="merge"), ids()
    )
    # Chorus's own intensity entry goes: the heads track Verse's 0.4.
    assert edit.message == "recorded cue 1/2: 1 entry; 2 values tracked from cue 1/1"
    assert song_list(applied(state, edit))["cues"][1]["entries"] == [
        {
            "targets": group("g-mh"),
            "attribute": "color",
            "value": {"kind": "literal", "value": WHITE},
        }
    ]


def test_merge_compares_with_the_cue_before_not_the_cues_own_values(state: ShowState) -> None:
    programmer = program(state, select_group("g-mh"), set_literal("intensity", 1.0))
    edit = record_cue(
        state, state.show, programmer, cmd("cl-song", cueNumber="2", merge="merge"), ids()
    )
    assert edit.message == "recorded cue 1/2: 2 entries"
    entries = song_list(applied(state, edit))["cues"][1]["entries"]
    assert [e["attribute"] for e in entries] == ["color", "intensity"]


def test_a_released_slot_is_stored(appendix: dict[str, Any]) -> None:
    pan_release = {"targets": group("g-mh"), "attributes": ["pan"]}
    appendix["cueLists"][0]["cues"][1]["releases"] = [pan_release]  # Chorus releases pan
    state = state_of(appendix)
    programmer = program(state, select_group("g-mh"), set_source("pan", SPREAD_PAN))
    # Into Chorus: its own releases are taken out of what it inherits.
    merged = record_cue(
        state, state.show, programmer, cmd("cl-song", cueNumber="2", merge="merge"), ids()
    )
    assert merged.message == "recorded cue 1/2: 3 entries"
    # After Chorus: the pan was released, so cue 3 does not inherit it.
    created = record_cue(state, state.show, programmer, cmd("cl-song"), ids())
    assert created.message == "recorded cue 1/3: 1 entry"
    assert song_list(applied(state, created))["cues"][2]["entries"] == [
        {"targets": group("g-mh"), "attribute": "pan", "value": SPREAD_PAN}
    ]


def test_a_release_of_all_attributes_is_taken_out_too(appendix: dict[str, Any]) -> None:
    release = {"targets": refs("fx-mh1"), "attributes": "all"}
    appendix["cueLists"][0]["cues"][1]["releases"] = [release]
    state = state_of(appendix)
    programmer = program(state, select_group("g-mh"), set_source("pan", SPREAD_PAN))
    edit = record_cue(state, state.show, programmer, cmd("cl-song"), ids())
    # MH 1's pan was released by Chorus and is stored; MH 2's still tracks.
    assert edit.message == "recorded cue 1/3: 1 entry; 1 value tracked from cue 1/2"


@pytest.mark.parametrize("change", ["block", "not tracking"])
def test_block_cues_and_non_tracking_lists_store_every_value(
    appendix: dict[str, Any], change: str
) -> None:
    if change == "block":
        appendix["cueLists"][0]["cues"][1]["block"] = True
    else:
        appendix["cueLists"][0]["tracking"] = False
    state = state_of(appendix)
    programmer = program(state, select_group("g-mh"), set_literal("intensity", 0.4))
    edit = record_cue(
        state, state.show, programmer, cmd("cl-song", cueNumber="2", merge="merge"), ids()
    )
    assert edit.message == "recorded cue 1/2: 2 entries"


def test_a_cue_after_a_block_inherits_only_the_block_state(appendix: dict[str, Any]) -> None:
    appendix["cueLists"][0]["cues"][1]["block"] = True  # Chorus drops Verse's pan
    state = state_of(appendix)
    programmer = program(
        state, select_group("g-mh"), set_literal("intensity", 1.0), set_source("pan", SPREAD_PAN)
    )
    edit = record_cue(state, state.show, programmer, cmd("cl-song"), ids())
    assert edit.message == "recorded cue 1/3: 1 entry; 2 values tracked from cue 1/2"


def test_a_preset_reference_and_a_literal_of_the_same_value_differ(
    appendix: dict[str, Any],
) -> None:
    chorus = appendix["cueLists"][0]["cues"][1]
    chorus["entries"][1]["value"] = BLUE  # Chorus: colour pr-blue, {0, 0, 1}
    state = state_of(appendix)
    as_preset = program(state, select_group("g-mh"), apply_preset("pr-blue"))
    edit = record_cue(state, state.show, as_preset, cmd("cl-song"), ids())
    assert edit.message == "recorded cue 1/3: 0 entries; 2 values tracked from cue 1/2"
    as_literal = program(
        state, select_group("g-mh"), set_literal("color", {"r": 0, "g": 0, "b": 1})
    )
    edit = record_cue(state, state.show, as_literal, cmd("cl-song"), ids())
    assert edit.message == "recorded cue 1/3: 1 entry"
    # … and the other way round: Verse's literal colour against a preset.
    edit = record_cue(
        state, state.show, as_preset, cmd("cl-song", cueNumber="2", merge="merge"), ids()
    )
    assert edit.message == "recorded cue 1/2: 2 entries"


def test_recording_at_an_insertion_point_inherits_from_the_cue_before(state: ShowState) -> None:
    programmer = program(
        state, select_group("g-mh"), set_literal("intensity", 0.4), set_literal("color", WHITE)
    )
    edit = record_cue(state, state.show, programmer, cmd("cl-song", cueNumber="1.5"), ids())
    # Verse's 0.4 tracks; white is Chorus's, after the insertion point, so it is stored.
    assert edit.message == "recorded cue 1/1.5: 1 entry; 2 values tracked from cue 1/1"
    cues = song_list(applied(state, edit))["cues"]
    assert [c["number"] for c in cues] == ["1", "1.5", "2"]
    assert [e["attribute"] for e in cues[1]["entries"]] == ["color"]


def test_the_first_cue_inherits_nothing(state: ShowState) -> None:
    programmer = program(state, select_group("g-mh"), set_literal("intensity", 1.0))
    edit = record_cue(
        state, state.show, programmer, cmd("cl-song", cueNumber="0.5", name="Pre"), ids()
    )
    assert edit.message == "recorded cue 1/0.5: 1 entry"


def test_remove_reports_no_tracked_values(state: ShowState) -> None:
    programmer = program(state, select_group("g-mh"), set_literal("intensity", 0.4))
    edit = record_cue(
        state, state.show, programmer, cmd("cl-song", cueNumber="2", merge="remove"), ids()
    )
    assert edit.message == "removed from cue 1/2: 1 entry"


def test_literals_compare_as_the_compiler_clamps_them(appendix: dict[str, Any]) -> None:
    chorus = appendix["cueLists"][0]["cues"][1]
    chorus["entries"][0]["value"] = {"kind": "literal", "value": 1.5}  # compiles to 1.0
    state = state_of(appendix)
    programmer = program(state, select_group("g-mh"), set_literal("intensity", 1.0))
    edit = record_cue(state, state.show, programmer, cmd("cl-song"), ids())
    assert edit.message == "recorded cue 1/3: 0 entries; 2 values tracked from cue 1/2"


# ------------------------------------------------------- effects (Phase 5)

SWEEP = effect_template("ef-sweep", effect_layer("pan", "triangle", "add"))
RAINBOW = {
    "id": "ef-rainbow",
    "name": "Rainbow",
    "layers": [
        {
            "attribute": "color",
            "palette": [{"r": 1, "g": 0, "b": 0}, {"r": 0, "g": 0, "b": 1}],
            "blend": "fade",
            "mode": "absolute",
        }
    ],
}
BOTH = effect_template(  # a layer in each of two families
    "ef-both", effect_layer("pan", "sine", "add"), effect_layer("intensity", "sine", "multiply")
)


def cue_of(doc: Any, list_id: str, number: str) -> dict[str, Any]:
    cue_list = next(cl for cl in doc["cueLists"] if cl["id"] == list_id)
    return cast(dict[str, Any], next(c for c in cue_list["cues"] if c["number"] == number))


def pulse(appendix: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """Appendix A's pulse instance ``ei-1`` (cue 20/1), with ``fields`` changed."""
    return {**copy.deepcopy(cue_of(appendix, "cl-pulse", "1")["effects"][0]), **fields}


def sweep(ident: str = "ei-2", size: float = 10.0) -> dict[str, Any]:
    return effect_instance(ident, "ef-sweep", group("g-mh"), size=size)


def rainbow(ident: str = "ei-3") -> dict[str, Any]:
    return effect_instance(ident, "ef-rainbow", group("g-mh"))


@pytest.fixture
def fx(appendix: dict[str, Any]) -> dict[str, Any]:
    """Appendix A plus ``cl-new``, three more templates, and a sweep ``ei-2``
    after the pulse in cue 20/1."""
    appendix["effects"] += [SWEEP, RAINBOW, BOTH]
    cue_of(appendix, "cl-pulse", "1")["effects"].append(sweep())
    return appendix


def recorded(state: ShowState, programmer: Programmer, command: RecordCueCmd) -> Any:
    """Record; return the edit's message and the resulting show."""
    edit = record_cue(state, state.show, programmer, command, ids())
    return edit.message, applied(state, edit)


def test_appendix_a_pulse_cue_is_rebuilt_from_the_programmer(
    appendix: dict[str, Any], state: ShowState
) -> None:
    # The console adds an effect on the selection, as a list of targets.
    programmer = program(state, add_effect(pulse(appendix, targets=refs("fx-mh1", "fx-mh2"))))
    message, show = recorded(state, programmer, cmd())
    assert message == "recorded cue 30/1: 0 entries, 1 effect"
    cue, original = cue_of(show, "cl-new", "1"), cue_of(appendix, "cl-pulse", "1")
    assert (cue["entries"], cue["effects"]) == (original["entries"], original["effects"])


@pytest.mark.parametrize(
    ("targets", "freeze", "stored"),
    [
        (refs("fx-mh1", "fx-mh2"), False, group("g-mh")),
        (refs("fx-mh2", "fx-mh1"), False, refs("fx-mh2", "fx-mh1")),  # not in member order
        (refs("fx-mh1"), False, refs("fx-mh1")),  # not every member
        (refs("fx-mh1", "fx-mh2", "fx-par1"), False, refs("fx-mh1", "fx-mh2", "fx-par1")),
        (refs("fx-par1"), False, group("g-par")),
        (group("g-mh"), False, group("g-mh")),
        (refs("fx-mh1", "fx-mh2"), True, refs("fx-mh1", "fx-mh2")),
        (group("g-mh"), True, refs("fx-mh1", "fx-mh2")),
    ],
)
def test_effect_targets_name_a_group_only_for_its_exact_ordered_members(
    appendix: dict[str, Any],
    state: ShowState,
    targets: dict[str, Any],
    freeze: bool,
    stored: dict[str, Any],
) -> None:
    programmer = program(state, add_effect(pulse(appendix, targets=targets)))
    _, show = recorded(state, programmer, cmd(freeze=freeze))
    assert cue_of(show, "cl-new", "1")["effects"] == [pulse(appendix, targets=stored)]


def test_of_two_groups_with_the_same_members_the_lowest_number_is_named(
    appendix: dict[str, Any],
) -> None:
    heads = {"id": "g-heads", "number": 7, "name": "Heads", "members": []}
    heads["members"] = copy.deepcopy(appendix["groups"][0]["members"])  # g-mh's, number 1
    appendix["groups"].insert(0, heads)
    state = state_of(appendix)
    programmer = program(state, add_effect(pulse(appendix, targets=refs("fx-mh1", "fx-mh2"))))
    _, show = recorded(state, programmer, cmd())
    assert cue_of(show, "cl-new", "1")["effects"][0]["targets"] == group("g-mh")


def test_merge_replaces_instances_by_id_in_place_and_appends_new_ones(
    fx: dict[str, Any],
) -> None:
    state = state_of(fx)
    smaller = pulse(fx, size=0.5)
    programmer = program(state, add_effect(rainbow()), add_effect(smaller))
    message, show = recorded(state, programmer, cmd("cl-pulse", cueNumber="1", merge="merge"))
    assert message == "recorded cue 20/1: 0 entries, 3 effects"
    assert cue_of(show, "cl-pulse", "1")["effects"] == [smaller, sweep(), rainbow()]


def test_replace_makes_the_cue_effects_the_programmers(fx: dict[str, Any]) -> None:
    state = state_of(fx)
    command = cmd("cl-pulse", cueNumber="1", merge="replace")
    message, show = recorded(state, program(state, add_effect(rainbow())), command)
    assert message == "recorded cue 20/1: 0 entries, 1 effect"
    assert cue_of(show, "cl-pulse", "1")["effects"] == [rainbow()]
    values = program(state, select_group("g-mh"), set_literal("intensity", 1))
    message, show = recorded(state, values, command)
    assert message == "recorded cue 20/1: 1 entry, 0 effects"  # the effects it dropped count
    assert cue_of(show, "cl-pulse", "1")["effects"] == []


def test_remove_deletes_the_instances_whose_id_the_programmer_holds(fx: dict[str, Any]) -> None:
    state = state_of(fx)
    # Only the id matters; ei-9 is not in the cue.
    programmer = program(state, add_effect(sweep(size=1.0)), add_effect(sweep("ei-9")))
    message, show = recorded(state, programmer, cmd("cl-pulse", cueNumber="1", merge="remove"))
    assert message == "removed from cue 20/1: 0 entries, 1 effect"
    assert cue_of(show, "cl-pulse", "1")["effects"] == [pulse(fx)]


def test_an_unchanged_effect_list_is_not_rewritten(fx: dict[str, Any]) -> None:
    state = state_of(fx)
    programmer = program(state, select_group("g-mh"), set_literal("intensity", 1))
    edit = record_cue(
        state, state.show, programmer, cmd("cl-pulse", cueNumber="1", merge="merge"), ids()
    )
    assert [op.path[-1] for op in edit.ops] == ["entries"]
    assert edit.message == "recorded cue 20/1: 1 entry, 2 effects"


@pytest.mark.parametrize(
    ("families", "stored"),
    [
        (["intensity"], ["ei-1", "ei-4"]),
        (["position"], ["ei-2", "ei-4"]),
        (["color"], ["ei-3"]),
        (["color", "intensity"], ["ei-1", "ei-3", "ei-4"]),
    ],
)
def test_the_filter_records_effects_with_a_layer_in_its_families(
    fx: dict[str, Any], families: list[str], stored: list[str]
) -> None:
    state = state_of(fx)
    both = effect_instance("ei-4", "ef-both", group("g-mh"), size=0.5)
    effects = [pulse(fx), sweep(), rainbow(), both]
    programmer = program(state, *map(add_effect, effects))
    _, show = recorded(state, programmer, cmd(filter=families))
    assert [effect["id"] for effect in cue_of(show, "cl-new", "1")["effects"]] == stored
    with pytest.raises(CommandError, match=r"^the programmer has no beam values or effects"):
        record_cue(state, state.show, programmer, cmd(filter=["beam"]), ids())


def test_values_and_effects_are_counted(fx: dict[str, Any]) -> None:
    state = state_of(fx)
    programmer = program(
        state,
        select_group("g-mh"),
        set_literal("tilt", 10),
        add_effect(sweep()),
        add_effect(rainbow()),
    )
    message, show = recorded(state, programmer, cmd())
    assert message == "recorded cue 30/1: 1 entry, 2 effects"
    assert len(cue_of(show, "cl-new", "1")["entries"]) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"templateId": "ef-gone"},
        {"rate": {"kind": "bpm", "masterId": "m-gone", "multiplier": 1}},
        {"targets": refs("fx-gone")},
    ],
    ids=["template", "master", "fixture"],
)
def test_a_dormant_effect_is_not_recorded(
    appendix: dict[str, Any], state: ShowState, change: dict[str, Any]
) -> None:
    # Added before the show lost what it names.
    gone = Programmer(effects=(cast(Any, pulse(appendix, **change)),))
    with pytest.raises(CommandError, match=r"^the programmer has no values or effects to record$"):
        record_cue(state, state.show, gone, cmd(), ids())
    with_value = program(state, select_group("g-mh"), set_literal("intensity", 1))
    message, _ = recorded(state, replace(with_value, effects=gone.effects), cmd())
    assert message == "recorded cue 30/1: 1 entry"


# Tracking lists: Verse (1/1) runs the pulse, which Chorus (1/2) tracks.


@pytest.fixture
def song(appendix: dict[str, Any]) -> dict[str, Any]:
    cue_of(appendix, "cl-song", "1")["effects"] = [pulse(appendix)]
    return appendix


def test_an_effect_equal_to_the_inherited_one_is_left_out(song: dict[str, Any]) -> None:
    state = state_of(song)
    programmer = program(
        state,
        add_effect(pulse(song, targets=refs("fx-mh1", "fx-mh2"))),  # compiles the same
        select_group("g-mh"),
        set_literal("intensity", 1.0),  # Chorus's
    )
    message, show = recorded(state, programmer, cmd("cl-song"))
    assert (
        message == "recorded cue 1/3: 0 entries, 0 effects; 2 values, 1 effect tracked from cue 1/2"
    )
    assert cue_of(show, "cl-song", "3")["effects"] == []
    cues = compile_show(show).cueLists["cl-song"].cues
    assert [effect.key for effect in cues[2].effects] == ["ei-1"]
    assert cues[2].effects[0] is cues[0].effects[0]  # the tracked instance itself


@pytest.mark.parametrize(
    "change",
    [{"size": 0.5}, {"id": "ei-9"}, {"targets": refs("fx-mh2", "fx-mh1")}],
    ids=["size", "id", "order"],
)
def test_an_effect_that_differs_from_the_inherited_one_is_stored(
    song: dict[str, Any], change: dict[str, Any]
) -> None:
    state = state_of(song)
    programmer = program(state, add_effect(pulse(song, **change)))
    message, show = recorded(state, programmer, cmd("cl-song"))
    assert message == "recorded cue 1/3: 0 entries, 1 effect"
    assert cue_of(show, "cl-song", "3")["effects"] == [pulse(song, **change)]


def test_merge_removes_the_cues_own_instance_equal_to_the_inherited_one(
    song: dict[str, Any],
) -> None:
    cue_of(song, "cl-song", "2")["effects"] = [pulse(song)]
    state = state_of(song)
    programmer = program(state, add_effect(pulse(song)))
    message, show = recorded(state, programmer, cmd("cl-song", cueNumber="2", merge="merge"))
    assert message == "recorded cue 1/2: 2 entries, 0 effects; 1 effect tracked from cue 1/1"
    assert cue_of(show, "cl-song", "2")["effects"] == []


@pytest.mark.parametrize(("attribute", "tracks"), [("intensity", False), ("pan", True)])
def test_the_inherited_instance_is_trimmed_by_the_cues_own_releases(
    song: dict[str, Any], attribute: str, tracks: bool
) -> None:
    release = {"targets": refs("fx-mh1"), "attributes": [attribute]}
    cue_of(song, "cl-song", "2")["releases"] = [release]
    state = state_of(song)
    programmer = program(state, add_effect(pulse(song)))
    _, show = recorded(state, programmer, cmd("cl-song", cueNumber="2", merge="merge"))
    assert cue_of(show, "cl-song", "2")["effects"] == ([] if tracks else [pulse(song)])


@pytest.mark.parametrize("change", ["block", "not tracking", "first cue"])
def test_effects_are_stored_where_nothing_is_inherited(song: dict[str, Any], change: str) -> None:
    number = "3"
    if change == "block":
        song["cueLists"][0]["cues"].append(
            {**cue_of(song, "cl-song", "2"), "id": "c-3", "number": "3", "block": True}
        )
    elif change == "not tracking":
        song["cueLists"][0]["tracking"] = False
    else:
        number = "0.5"
    state = state_of(song)
    programmer = program(state, add_effect(pulse(song)))
    merge = {"merge": "merge"} if change == "block" else {}
    _, show = recorded(state, programmer, cmd("cl-song", cueNumber=number, **merge))
    assert cue_of(show, "cl-song", number)["effects"] == [pulse(song)]
