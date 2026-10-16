"""Cue compiler (§6.3): group expansion, value sources, drops, clamping, lane
partitions; and the compiled playbacks, first page and masters."""

from __future__ import annotations

import copy
import math
from typing import Any

import numpy as np
import pytest

from builders import (
    Doc,
    busk_rig,
    compile_doc,
    cue,
    cue_list,
    entry,
    grand_master,
    group,
    in_group,
    lane_kinds_rig,
    literal,
    look,
    page,
    per_target,
    playback,
    preset,
    preset_source,
    preset_value,
    rgb,
    slot_of,
    spread,
    targets,
)
from busk.compiler.compile import CompiledShow
from busk.compiler.cues import (
    EMPTY_CUE,
    SNAP_START,
    CompiledCue,
    SlotTiming,
    spread_fraction,
)
from busk.compiler.playbacks import CompiledPage
from busk.model.validate import Issue

NAN = math.nan


def cue_lanes(
    compiled: CompiledShow, compiled_cue: CompiledCue
) -> dict[tuple[str, str], list[float]]:
    """A compiled cue's arrays read back per ``(fixtureId, attribute)``."""
    lanes: dict[int, float] = {}
    for position, value in zip(compiled_cue.htpPos, compiled_cue.htpValues, strict=True):
        lanes[int(compiled.slots.intensityLanes[position])] = float(value)
    for lane, value in zip(compiled_cue.ltpLanes, compiled_cue.ltpValues, strict=True):
        lanes[int(lane)] = float(value)
    for lane, value in zip(compiled_cue.snapLanes, compiled_cue.snapValues, strict=True):
        lanes[int(lane)] = float(value)
    result: dict[tuple[str, str], list[float]] = {}
    for slot_ in compiled.slots.slots:
        own = range(slot_.laneOffset, slot_.laneOffset + slot_.laneCount)
        present = [lane in lanes for lane in own]
        if any(present):
            assert all(present), f"{slot_.target}/{slot_.attribute.id} is partial"
            result[(slot_.target["fixtureId"], slot_.attribute.id)] = [lanes[lane] for lane in own]
    return result


def approx(values: dict[tuple[str, str], list[float]]) -> Any:
    return {key: pytest.approx(lanes, nan_ok=True) for key, lanes in values.items()}


def single_cue(doc: Doc, *entries: Doc) -> tuple[CompiledShow, CompiledCue]:
    """Compile ``doc`` with one look holding ``entries``; return it and its cue."""
    look(doc, "pb", 1, *entries)
    compiled = compile_doc(doc)
    return compiled, compiled.playbacks["pb"].cueList.first


# ------------------------------------------------------------- Appendix A


def test_appendix_a_verse(appendix_a: dict[str, Any]) -> None:
    compiled = compile_doc(appendix_a)
    verse = compiled.cueLists["cl-song"].cues[0]
    assert (verse.id, verse.number, verse.name) == ("c-verse", "1", "Verse")
    assert cue_lanes(compiled, verse) == approx(
        {
            ("fx-mh1", "intensity"): [0.4],
            ("fx-mh2", "intensity"): [0.4],
            ("fx-mh1", "color"): [1, 0.8, 0.6, NAN],
            ("fx-mh2", "color"): [1, 0.8, 0.6, NAN],
            ("fx-mh1", "pan"): [-20],  # spread: first member at `from`
            ("fx-mh2", "pan"): [20],  # … last at `to`
        }
    )
    assert verse.targets == (
        {"fixtureId": "fx-mh1", "element": 0},
        {"fixtureId": "fx-mh2", "element": 0},
    )


def test_appendix_a_blue_is_a_global_preset_on_heads_and_par(appendix_a: dict[str, Any]) -> None:
    compiled = compile_doc(appendix_a)
    blue = compiled.playbacks["pb-blue"].cueList.first
    assert cue_lanes(compiled, blue) == approx(
        {
            ("fx-mh1", "color"): [0, 0, 1, NAN],  # w derives at conversion
            ("fx-mh2", "color"): [0, 0, 1, NAN],
            ("fx-par1", "color"): [0, 0, 1],  # RGB only: no extras
        }
    )
    assert compiled.warnings == ()


def test_a_cue_carries_its_in_and_out_timing(appendix_a: dict[str, Any]) -> None:
    """Without overrides, every lane fades in with the cue's in timing and HTP
    lanes fall with its out timing (equal timings share one index)."""
    compiled = compile_doc(appendix_a)
    verse = compiled.cueLists["cl-song"].cues[0]
    timing = appendix_a["cueLists"][0]["cues"][0]["timing"]
    fade_in = SlotTiming(fade=timing["fadeIn"], delay=timing["delayIn"], curve=timing["curve"])
    fade_out = SlotTiming(fade=timing["fadeOut"], delay=timing["delayOut"], curve=timing["curve"])
    assert verse.inTiming == fade_in
    assert {verse.timings[i] for i in verse.htpIn} == {fade_in}
    assert {verse.timings[i] for i in verse.htpOut} == {fade_out}
    assert {verse.timings[i] for i in verse.ltpTiming} == {fade_in}
    assert {verse.timings[i] for i in verse.snapTiming} <= {fade_in}


def test_every_cue_is_compiled_and_the_first_one_plays(appendix_a: dict[str, Any]) -> None:
    compiled = compile_doc(appendix_a)
    assert [c.id for c in compiled.cueLists["cl-song"].cues] == ["c-verse", "c-chorus"]
    song = compiled.playbacks["pb-song"]
    assert (song.cueList.first.id, len(song.cueList.cues)) == ("c-verse", 2)
    pulse = compiled.playbacks["pb-pulse"]
    assert pulse.cueList.first.htpPos.size == pulse.cueList.first.ltpLanes.size == 0  # effects only
    assert pulse.cueList.first.snapLanes.size == 0


def test_appendix_a_playback_record(appendix_a: dict[str, Any]) -> None:
    blue = compile_doc(appendix_a).playbacks["pb-blue"]
    assert (
        blue.priority,
        blue.fader,
        blue.buttons,
        blue.ltpFaderMode,
        blue.ltpThreshold,
        blue.autoStart,
        blue.autoRelease,
        blue.flashLevel,
        blue.flashIncludeLtp,
        blue.flashPriorityBoost,
        blue.exclusivity,
        blue.releaseTime,
        blue.cueList.releaseAtEnd,
        len(blue.cueList.cues),
    ) == (
        50,
        "master",
        ("toggle", "flash"),
        "threshold",
        0.02,
        True,
        True,
        1,
        True,
        0,
        "color",
        1,
        False,
        1,
    )


def test_intensity_lanes_are_the_htp_slots(appendix_a: dict[str, Any]) -> None:
    compiled = compile_doc(appendix_a)
    expected = [
        slot_of(compiled, f, "intensity").laneOffset for f in ("fx-mh1", "fx-mh2", "fx-par1")
    ]
    assert compiled.slots.intensityLanes.tolist() == expected
    assert not compiled.slots.intensityLanes.flags.writeable


# ---------------------------------------------------------- value sources


def test_preset_scope_precedence_is_target_then_profile_then_global() -> None:
    doc = busk_rig(spots=3, pars=1)
    doc["groups"].append(group("g-all", 1, "fx-mh1", "fx-mh2", "fx-mh3", "fx-par1"))
    doc["presets"].append(
        preset(
            "pr-c",
            1,
            "color",
            preset_value("color", rgb(0, 0, 1)),  # global, listed first on purpose
            preset_value("color", rgb(0, 1, 0), "profile:prof-mh"),
            preset_value("color", rgb(1, 0, 0), "fx-mh1:0"),
        )
    )
    compiled, compiled_cue = single_cue(
        doc,
        entry(in_group("g-all"), "color", preset_source("pr-c")),
        entry(in_group("g-all"), "pan", preset_source("pr-c")),  # the preset has no pan
    )
    assert cue_lanes(compiled, compiled_cue) == approx(
        {
            ("fx-mh1", "color"): [1, 0, 0, NAN],  # target scope
            ("fx-mh2", "color"): [0, 1, 0, NAN],  # profile scope
            ("fx-mh3", "color"): [0, 1, 0, NAN],
            ("fx-par1", "color"): [0, 0, 1],  # global scope
        }
    )


def test_a_preset_without_a_matching_scope_contributes_nothing() -> None:
    doc = busk_rig(spots=2)
    doc["presets"].append(preset("pr-pos", 1, "position", preset_value("pan", 30, "fx-mh1:0")))
    compiled, compiled_cue = single_cue(
        doc, entry(targets("fx-mh1", "fx-mh2"), "pan", preset_source("pr-pos"))
    )
    assert cue_lanes(compiled, compiled_cue) == {("fx-mh1", "pan"): [30]}


def test_per_target_values_skip_targets_without_a_key() -> None:
    doc = busk_rig(spots=3)
    compiled, compiled_cue = single_cue(
        doc,
        entry(
            targets("fx-mh1", "fx-mh2", "fx-mh3"),
            "tilt",
            per_target({"fx-mh1:0": -10, "fx-mh3:0": 10}),
        ),
    )
    assert cue_lanes(compiled, compiled_cue) == {
        ("fx-mh1", "tilt"): [-10],
        ("fx-mh3", "tilt"): [10],
    }


@pytest.mark.parametrize(
    ("curve", "expected"),
    [
        (None, [-40, -20, 0, 20, 40]),  # linear by default
        ("linear", [-40, -20, 0, 20, 40]),
        ("center", [-40, 0, 40, 0, -40]),  # f = 1 − |2u − 1|
        ("edges", [40, 0, -40, 0, 40]),  # f = |2u − 1|
    ],
)
def test_spread_curves(curve: str | None, expected: list[float]) -> None:
    doc = busk_rig(spots=5)
    heads = [f"fx-mh{k}" for k in range(1, 6)]
    doc["groups"].append(group("g", 1, *heads))
    compiled, compiled_cue = single_cue(doc, entry(in_group("g"), "pan", spread(-40, 40, curve)))
    lanes = cue_lanes(compiled, compiled_cue)
    assert [lanes[(head, "pan")][0] for head in heads] == pytest.approx(expected)


def test_spread_fraction_with_one_member_is_zero() -> None:
    assert [spread_fraction(curve, 0, 1) for curve in ("linear", "center", "edges")] == [0, 0, 1]


def test_spread_over_one_member_takes_from() -> None:
    doc = busk_rig(spots=1)
    compiled, compiled_cue = single_cue(doc, entry(targets("fx-mh1"), "pan", spread(-40, 40)))
    assert cue_lanes(compiled, compiled_cue) == {("fx-mh1", "pan"): [-40]}


def test_spread_members_without_the_attribute_keep_their_position() -> None:
    doc = busk_rig(spots=2, pars=1)
    # The par (index 1 of 3) has no pan, but still counts: MH 2 is at u = 1.
    compiled, compiled_cue = single_cue(
        doc, entry(targets("fx-mh1", "fx-par1", "fx-mh2"), "pan", spread(0, 90))
    )
    assert cue_lanes(compiled, compiled_cue) == {("fx-mh1", "pan"): [0], ("fx-mh2", "pan"): [90]}


def test_colour_spreads_lerp_every_lane() -> None:
    doc = busk_rig(spots=3)
    compiled, compiled_cue = single_cue(
        doc,
        entry(
            targets("fx-mh1", "fx-mh2", "fx-mh3"), "color", spread(rgb(1, 0, 0), rgb(0, 0, 1, w=1))
        ),
    )
    assert cue_lanes(compiled, compiled_cue) == approx(
        {
            ("fx-mh1", "color"): [1, 0, 0, NAN],  # lerp(NaN, 1, f) stays "derive"
            ("fx-mh2", "color"): [0.5, 0, 0.5, NAN],
            ("fx-mh3", "color"): [0, 0, 1, NAN],
        }
    )


# --------------------------------------------------------- drops and rules


def test_targets_without_the_attribute_are_dropped() -> None:
    doc = busk_rig(spots=1, pars=1)
    compiled, compiled_cue = single_cue(
        doc, entry(targets("fx-mh1", "fx-par1"), "tilt", literal(30))
    )
    assert cue_lanes(compiled, compiled_cue) == {("fx-mh1", "tilt"): [30]}
    assert compiled_cue.targets == (
        {"fixtureId": "fx-mh1", "element": 0},
        {"fixtureId": "fx-par1", "element": 0},
    )


def test_missing_discrete_options_are_dropped_and_reported() -> None:
    doc = busk_rig(spots=2)
    # MH 2 gets a copy of the spot profile without the breakup gobo.
    other = copy.deepcopy(doc["profiles"][0])
    other["id"] = "prof-mh-b"
    other["wheels"][0]["slots"].pop()
    gobo = next(c for c in other["modes"][0]["channels"] if c["attribute"] == "gobo1")
    gobo["capabilities"].pop()
    doc["profiles"].append(other)
    doc["fixtures"][1]["profileId"] = "prof-mh-b"
    compiled, compiled_cue = single_cue(
        doc,
        entry(targets("fx-mh1", "fx-mh2"), "gobo1", literal({"slot": "breakup"})),
        entry(targets("fx-mh1"), "gobo1", literal({"wheel": "gobo9", "slot": "open"})),
    )
    # MH 1 keeps breakup (the second entry is dropped), MH 2 has no breakup.
    assert cue_lanes(compiled, compiled_cue) == {("fx-mh1", "gobo1"): [1]}
    assert list(compiled.warnings) == [
        Issue(
            "warning",
            "cueLists[0].cues[0].entries[0].value",
            "fx-mh2:0 has no 'gobo1' option 'breakup'; it offers 'open'; dropped for that target",
        ),
        Issue(
            "warning",
            "cueLists[0].cues[0].entries[1].value",
            "fx-mh1:0 has no 'gobo1' on wheel 'gobo9' (its wheels: 'gobo1'); "
            "dropped for that target",
        ),
    ]


def test_a_later_entry_for_the_same_slot_wins() -> None:
    doc = busk_rig(spots=2)
    doc["groups"].append(group("g", 1, "fx-mh1", "fx-mh2"))
    compiled, compiled_cue = single_cue(
        doc,
        entry(in_group("g"), "color", literal(rgb(0, 0, 1))),
        entry(targets("fx-mh1"), "color", literal(rgb(1, 0, 0))),
    )
    assert cue_lanes(compiled, compiled_cue) == approx(
        {("fx-mh1", "color"): [1, 0, 0, NAN], ("fx-mh2", "color"): [0, 0, 1, NAN]}
    )


def test_values_are_clamped_at_compile_time() -> None:
    doc = busk_rig(spots=3)
    compiled, compiled_cue = single_cue(
        doc,
        entry(targets("fx-mh1"), "intensity", literal(1.5)),
        entry(targets("fx-mh2"), "intensity", literal(-0.5)),
        entry(targets("fx-mh3"), "pan", literal(900)),  # degrees: conversion clamps them
    )
    assert cue_lanes(compiled, compiled_cue) == {
        ("fx-mh1", "intensity"): [1.0],
        ("fx-mh2", "intensity"): [0.0],
        ("fx-mh3", "pan"): [900],
    }


def test_lanes_are_partitioned_the_way_the_resolver_merges_them() -> None:
    doc = lane_kinds_rig()
    compiled, compiled_cue = single_cue(
        doc,
        entry(targets("fx1"), "intensity", literal(0.5)),
        entry(targets("fx1"), "pan", literal(45)),
        entry(targets("fx1"), "positionSpeed", literal(0.3)),
        entry(targets("fx1"), "color", literal(rgb(1, 0.5, 0, a=0.25))),
        entry(targets("fx1"), "gobo1", literal({"slot": "dots"})),
        entry(targets("fx1"), "shutter", literal({"slot": "strobe"})),
        entry(targets("fx1"), "strobeRate", literal(10)),
    )

    def lane(attribute: str, k: int = 0) -> int:
        return int(slot_of(compiled, "fx1", attribute).laneOffset) + k

    assert compiled_cue.htpPos.tolist() == [0]
    assert compiled_cue.htpValues.tolist() == [0.5]
    assert compiled_cue.ltpLanes.tolist() == sorted(
        [lane("pan"), lane("color", 0), lane("color", 1), lane("color", 2), lane("strobeRate")]
    )
    assert np.nextafter(0.0, 1.0) == SNAP_START  # the smallest weight > 0
    snaps = {
        int(lane): (float(value), float(threshold))
        for lane, value, threshold in zip(
            compiled_cue.snapLanes,
            compiled_cue.snapValues,
            compiled_cue.snapThresholds,
            strict=True,
        )
    }
    assert compiled_cue.snapLanes.tolist() == sorted(snaps)
    start = [lane("positionSpeed"), lane("gobo1"), lane("shutter")]
    middle = [lane("color", 3), lane("color", 4)]  # w, a
    assert sorted(snaps) == sorted(start + middle)
    assert {lane_: snaps[lane_][1] for lane_ in start} == dict.fromkeys(start, SNAP_START)
    assert {lane_: snaps[lane_][1] for lane_ in middle} == dict.fromkeys(middle, 0.5)
    assert [snaps[lane_][0] for lane_ in middle] == pytest.approx([NAN, 0.25], nan_ok=True)
    for array in (
        compiled_cue.htpPos,
        compiled_cue.ltpLanes,
        compiled_cue.ltpValues,
        compiled_cue.snapLanes,
        compiled_cue.snapValues,
        compiled_cue.snapThresholds,
    ):
        assert not array.flags.writeable


# --------------------------------------------- playbacks, pages and masters


def test_an_empty_cue_list_plays_the_empty_cue() -> None:
    doc = busk_rig(spots=1)
    doc["cueLists"].append(cue_list("cl-empty", 1))
    doc["playbacks"].append(playback("pb", 1, "cl-empty"))
    compiled = compile_doc(doc)
    assert compiled.playbacks["pb"].cueList.first is EMPTY_CUE
    assert compiled.playbacks["pb"].cueList.cues == ()


def test_release_at_end_and_flash_boost_come_through() -> None:
    doc = busk_rig(spots=1)
    look(doc, "pb", 1, release_at_end=True, boost=250, exclusivity="base")
    compiled = compile_doc(doc)
    record = compiled.playbacks["pb"]
    assert (record.cueList.releaseAtEnd, record.flashPriorityBoost, record.exclusivity) == (
        True,
        250,
        "base",
    )


def test_pages_are_sorted_by_number(appendix_a: dict[str, Any]) -> None:
    (main,) = compile_doc(appendix_a).pages
    assert main == CompiledPage(
        id="page-1",
        number=1,
        name="Main",
        slots=("pb-song", None, "pb-blue", None, None, "pb-pulse", None, None),
    )
    appendix_a["pages"].insert(0, page("page-2", 2, "pb-blue"))
    assert [(p.id, p.number) for p in compile_doc(appendix_a).pages] == [
        ("page-1", 1),
        ("page-2", 2),
    ]
    appendix_a["pages"] = []
    assert compile_doc(appendix_a).pages == ()


def test_masters_start_at_their_initial_level(appendix_a: dict[str, Any]) -> None:
    compiled = compile_doc(appendix_a)
    assert [(m.id, m.kind, m.initialLevel) for m in compiled.masters.values()] == [
        ("m-gm", "grand", 1.0),
        ("m-speed", "speed", 0.5),  # the ×1 step of [0.25, 0.5, 1, 2, 4] (decision 11)
    ]
    assert [m.id for m in compiled.grandMasters] == ["m-gm"]
    appendix_a["masters"].append(grand_master("m-gm2", initial=0.5))
    assert [m.initialLevel for m in compile_doc(appendix_a).grandMasters] == [1.0, 0.5]


def test_two_compiles_produce_equal_cues(appendix_a: dict[str, Any]) -> None:
    first, second = compile_doc(appendix_a), compile_doc(appendix_a)
    for a, b in zip(first.cueLists["cl-song"].cues, second.cueLists["cl-song"].cues, strict=True):
        assert cue_lanes(first, a) == approx(cue_lanes(second, b))
        assert a.ltpLanes.tolist() == b.ltpLanes.tolist()


def test_cue_list_builder_sanity() -> None:
    # `cue_list` + `cue` produce what the schema expects (guards the builders).
    doc = busk_rig(spots=1)
    doc["cueLists"].append(cue_list("cl", 1, cue("c1"), cue("c2", number="2")))
    doc["playbacks"].append(playback("pb", 1, "cl"))
    assert len(compile_doc(doc).playbacks["pb"].cueList.cues) == 2
