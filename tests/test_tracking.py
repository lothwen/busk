"""Tracked states and per-slot timing (spec §9.1, §9.3; phase-4-plan step 8).

Each compiled cue holds its *tracked state*: what a playback holds at that
cue. These tests read the states back per ``(fixture, attribute)`` with the
timing every slot fades in (and, for intensity, out) with.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pytest

from builders import (
    Doc,
    busk_rig,
    compile_doc,
    cue,
    cue_list,
    entry,
    literal,
    playback,
    rgb,
    targets,
)
from busk.compiler.compile import CompiledShow
from busk.compiler.cues import CompiledCue, SlotTiming
from busk.compiler.slots import FAMILIES, FAMILY_CODES

NAN = math.nan


@dataclass(frozen=True)
class Held:
    """One slot of a compiled cue: its lanes and the timings it fades with."""

    lanes: list[float]
    rising: SlotTiming  # every non-intensity slot fades with this one
    falling: SlotTiming


def held(compiled: CompiledShow, compiled_cue: CompiledCue) -> dict[tuple[str, str], Held]:
    """A compiled cue read back per ``(fixtureId, attribute)``."""
    lanes: dict[int, tuple[float, int, int]] = {}
    intensity = compiled.slots.intensityLanes
    for position, value, rising, falling in zip(
        compiled_cue.htpPos,
        compiled_cue.htpValues,
        compiled_cue.htpIn,
        compiled_cue.htpOut,
        strict=True,
    ):
        lanes[int(intensity[position])] = (float(value), int(rising), int(falling))
    for lane_array, values, timing in (
        (compiled_cue.ltpLanes, compiled_cue.ltpValues, compiled_cue.ltpTiming),
        (compiled_cue.snapLanes, compiled_cue.snapValues, compiled_cue.snapTiming),
    ):
        for lane, value, index in zip(lane_array, values, timing, strict=True):
            lanes[int(lane)] = (float(value), int(index), int(index))
    result: dict[tuple[str, str], Held] = {}
    for slot in compiled.slots.slots:
        own = [lanes.get(lane) for lane in range(slot.laneOffset, slot.laneOffset + slot.laneCount)]
        if not any(own):
            continue
        assert all(own), f"{slot.target}/{slot.attribute.id} is partial"
        timings = {(lane[1], lane[2]) for lane in own if lane is not None}
        assert len(timings) == 1, f"{slot.target}/{slot.attribute.id}: lanes disagree on timing"
        ((rising, falling),) = timings
        result[(slot.target["fixtureId"], slot.attribute.id)] = Held(
            lanes=[lane[0] for lane in own if lane is not None],
            rising=compiled_cue.timings[rising],
            falling=compiled_cue.timings[falling],
        )
    return result


def values(compiled: CompiledShow, compiled_cue: CompiledCue) -> dict[tuple[str, str], list[float]]:
    """Just the lanes of :func:`held`."""
    return {key: slot.lanes for key, slot in held(compiled, compiled_cue).items()}


def expect(state: dict[tuple[str, str], list[float]]) -> dict[tuple[str, str], Any]:
    """``state`` comparable with :func:`values` (colour extras may be ``NaN``)."""
    return {key: pytest.approx(lanes, nan_ok=True) for key, lanes in state.items()}


def song(*cues: Doc, tracking: bool = True, spots: int = 3) -> CompiledShow:
    """A rig of ``spots`` heads with one cue list ``cl`` of ``cues``, compiled."""
    doc = busk_rig(spots=spots)
    doc["cueLists"].append(cue_list("cl", 1, *cues))
    doc["cueLists"][0]["tracking"] = tracking
    doc["playbacks"].append(playback("pb", 1, "cl"))
    return compile_doc(doc)


def numbered(cue_id: str, number: int, *entries: Doc, **fields: Any) -> Doc:
    """A cue numbered ``number``; ``fields`` are set on it (``block``,
    ``releases``, ``timing``, ``trigger``)."""
    made = cue(cue_id, *entries, number=str(number))
    made.update(fields)
    return made


def release(*fixture_ids: str, attributes: list[str] | str = "all") -> Doc:
    return {"targets": targets(*fixture_ids), "attributes": attributes}


def timing(
    fade_in: float = 0.0,
    delay_in: float = 0.0,
    fade_out: float = 0.0,
    delay_out: float = 0.0,
    curve: Any = "linear",
    **per_family: Doc,
) -> Doc:
    made: Doc = {
        "fadeIn": fade_in,
        "delayIn": delay_in,
        "fadeOut": fade_out,
        "delayOut": delay_out,
        "curve": curve,
    }
    if per_family:
        made["perFamily"] = per_family
    return made


def timed(spec: Doc, attribute: str, source: Doc, **override: Any) -> Doc:
    """A value entry with a per-entry timing override."""
    made = entry(spec, attribute, source)
    made["timing"] = override
    return made


RED = rgb(1, 0, 0)
RED_LANES = [1.0, 0.0, 0.0, NAN]  # the spot's colour has a white extra: derived

# ------------------------------------------------------------ tracked states

STACK = (
    numbered(
        "c1",
        1,
        entry(targets("fx-mh1", "fx-mh2", "fx-mh3"), "intensity", literal(1.0)),
        entry(targets("fx-mh1"), "pan", literal(10.0)),
    ),
    numbered(
        "c2",
        2,
        entry(targets("fx-mh1"), "color", literal(RED)),
        releases=[release("fx-mh2", attributes=["intensity"])],
    ),
    numbered(
        "c3",
        3,
        entry(targets("fx-mh1"), "intensity", literal(0.5)),
        releases=[release("fx-mh1")],  # "all": but its own intensity wins
    ),
    numbered("c4", 4, entry(targets("fx-mh3"), "pan", literal(30.0)), block=True),
    numbered("c5", 5, entry(targets("fx-mh2"), "intensity", literal(0.2))),
)


def test_tracking_states_with_releases_and_a_block() -> None:
    compiled = song(*STACK)
    states = [values(compiled, c) for c in compiled.cueLists["cl"].cues]
    assert states[0] == {
        ("fx-mh1", "intensity"): [1.0],
        ("fx-mh2", "intensity"): [1.0],
        ("fx-mh3", "intensity"): [1.0],
        ("fx-mh1", "pan"): [10.0],
    }
    assert states[1] == expect(
        {  # MH 2's intensity released, MH 1 turns red
            ("fx-mh1", "intensity"): [1.0],
            ("fx-mh3", "intensity"): [1.0],
            ("fx-mh1", "pan"): [10.0],
            ("fx-mh1", "color"): RED_LANES,
        }
    )
    assert states[2] == {  # all of MH 1 released, except the cue's own intensity
        ("fx-mh1", "intensity"): [0.5],
        ("fx-mh3", "intensity"): [1.0],
    }
    assert states[3] == {("fx-mh3", "pan"): [30.0]}  # a block holds only its own values
    assert states[4] == {  # tracking resumes after the block
        ("fx-mh3", "pan"): [30.0],
        ("fx-mh2", "intensity"): [0.2],
    }


def test_a_non_tracking_list_holds_each_cues_own_values() -> None:
    compiled = song(*STACK, tracking=False)
    states = [values(compiled, c) for c in compiled.cueLists["cl"].cues]
    assert states[1] == expect({("fx-mh1", "color"): RED_LANES})
    assert states[2] == {("fx-mh1", "intensity"): [0.5]}
    assert states[4] == {("fx-mh2", "intensity"): [0.2]}


def test_releasing_an_attribute_a_target_lacks_is_skipped() -> None:
    doc = busk_rig(spots=1, pars=1)
    doc["cueLists"].append(
        cue_list(
            "cl",
            1,
            numbered("c1", 1, entry(targets("fx-mh1", "fx-par1"), "color", literal(RED))),
            numbered("c2", 2, releases=[release("fx-mh1", "fx-par1", attributes=["pan", "color"])]),
        )
    )
    doc["cueLists"][0]["tracking"] = True
    doc["playbacks"].append(playback("pb", 1, "cl"))
    compiled = compile_doc(doc)
    assert held(compiled, compiled.cueLists["cl"].cues[1]) == {}


# ----------------------------------------------------------------- timing


def test_without_overrides_intensity_rises_in_and_falls_out() -> None:
    compiled = song(
        numbered(
            "c1",
            1,
            entry(targets("fx-mh1"), "intensity", literal(1.0)),
            entry(targets("fx-mh1"), "pan", literal(10.0)),
            entry(targets("fx-mh1"), "gobo1", literal({"slot": "open"})),
            timing=timing(2.0, 0.5, 4.0, 1.0, "easeIn"),
        )
    )
    slots = held(compiled, compiled.cueLists["cl"].first)
    fade_in = SlotTiming(fade=2.0, delay=0.5, curve="easeIn")
    fade_out = SlotTiming(fade=4.0, delay=1.0, curve="easeIn")
    assert (slots["fx-mh1", "intensity"].rising, slots["fx-mh1", "intensity"].falling) == (
        fade_in,
        fade_out,
    )
    assert slots["fx-mh1", "pan"].rising == fade_in  # LTP: always the in timing
    assert slots["fx-mh1", "gobo1"].rising == fade_in  # snap lanes too
    assert compiled.cueLists["cl"].first.inTiming == fade_in


def test_an_entry_overrides_field_by_field() -> None:
    """Fields the entry leaves out come from the cue; an entry's ``fade``
    covers both rising and falling intensity."""
    compiled = song(
        numbered(
            "c1",
            1,
            timed(targets("fx-mh1"), "intensity", literal(1.0), fade=7.0),
            timed(targets("fx-mh1"), "pan", literal(10.0), delay=3.0, curve="snapEnd"),
            entry(targets("fx-mh2"), "pan", literal(20.0)),
            timing=timing(2.0, 0.5, 4.0, 1.0, "easeIn"),
        )
    )
    slots = held(compiled, compiled.cueLists["cl"].first)
    assert slots["fx-mh1", "intensity"].rising == SlotTiming(fade=7.0, delay=0.5, curve="easeIn")
    assert slots["fx-mh1", "intensity"].falling == SlotTiming(fade=7.0, delay=1.0, curve="easeIn")
    assert slots["fx-mh1", "pan"].rising == SlotTiming(fade=2.0, delay=3.0, curve="snapEnd")
    assert slots["fx-mh2", "pan"].rising == SlotTiming(fade=2.0, delay=0.5, curve="easeIn")


def test_the_last_entry_for_a_slot_wins_with_its_timing() -> None:
    compiled = song(
        numbered(
            "c1",
            1,
            timed(targets("fx-mh1", "fx-mh2"), "pan", literal(10.0), fade=9.0),
            entry(targets("fx-mh1"), "pan", literal(20.0)),  # no timing: the cue's
            timing=timing(2.0),
        )
    )
    slots = held(compiled, compiled.cueLists["cl"].first)
    assert (slots["fx-mh1", "pan"].lanes, slots["fx-mh1", "pan"].rising.fade) == ([20.0], 2.0)
    assert (slots["fx-mh2", "pan"].lanes, slots["fx-mh2", "pan"].rising.fade) == ([10.0], 9.0)


def test_per_family_timing_and_curve_fallbacks() -> None:
    compiled = song(
        numbered(
            "c1",
            1,
            entry(targets("fx-mh1"), "intensity", literal(1.0)),
            entry(targets("fx-mh1"), "pan", literal(10.0)),
            timed(targets("fx-mh2"), "pan", literal(10.0), delay=9.0),
            entry(targets("fx-mh1"), "color", literal(RED)),
            timing=timing(
                2.0,
                0.5,
                4.0,
                1.0,
                "easeIn",
                intensity={"fade": 1.0, "delay": 0.25, "curve": "linear"},
                position={"fade": 5.0, "delay": 0.0},  # no curve: the cue's
            ),
        )
    )
    slots = held(compiled, compiled.cueLists["cl"].first)
    family_intensity = SlotTiming(fade=1.0, delay=0.25, curve="linear")
    assert slots["fx-mh1", "intensity"].rising == family_intensity  # in and out alike
    assert slots["fx-mh1", "intensity"].falling == family_intensity
    assert slots["fx-mh1", "pan"].rising == SlotTiming(fade=5.0, delay=0.0, curve="easeIn")
    # an entry override sits on top of its family's timing
    assert slots["fx-mh2", "pan"].rising == SlotTiming(fade=5.0, delay=9.0, curve="easeIn")
    # a family without its own timing uses the cue's in timing
    assert slots["fx-mh1", "color"].rising == SlotTiming(fade=2.0, delay=0.5, curve="easeIn")


def test_the_leave_table_gives_each_family_its_timing_out() -> None:
    compiled = song(
        numbered(
            "c1",
            1,
            timing=timing(2.0, 0.5, 4.0, 1.0, "easeIn", position={"fade": 5.0, "delay": 0.0}),
        )
    )
    first = compiled.cueLists["cl"].first
    leave = {family: first.timings[first.leave[code]] for family, code in FAMILY_CODES.items()}
    assert first.leave.shape == (len(FAMILIES),)
    assert leave["intensity"] == SlotTiming(fade=4.0, delay=1.0, curve="easeIn")  # falls: out
    assert leave["position"] == SlotTiming(fade=5.0, delay=0.0, curve="easeIn")
    assert leave["color"] == leave["beam"] == SlotTiming(fade=2.0, delay=0.5, curve="easeIn")


def test_tracked_slots_take_the_destination_cues_timing() -> None:
    """A tracked-in slot has no entry in the cue: its origin's override does
    not follow it."""
    compiled = song(
        numbered(
            "c1",
            1,
            timed(targets("fx-mh1"), "intensity", literal(1.0), fade=9.0),
            timing=timing(1.0, 0.0, 1.0, 0.0),
        ),
        numbered(
            "c2",
            2,
            entry(targets("fx-mh2"), "intensity", literal(1.0)),
            timing=timing(3.0, 0.0, 6.0, 0.0, "easeOut"),
        ),
    )
    tracked = held(compiled, compiled.cueLists["cl"].cues[1])["fx-mh1", "intensity"]
    assert tracked.rising == SlotTiming(fade=3.0, delay=0.0, curve="easeOut")
    assert tracked.falling == SlotTiming(fade=6.0, delay=0.0, curve="easeOut")


def test_the_trigger_is_compiled() -> None:
    compiled = song(
        numbered("c1", 1),
        numbered("c2", 2, trigger={"kind": "follow", "delay": 1.5}),
        numbered("c3", 3, trigger={"kind": "wait", "delay": 8.0}),
    )
    cues = compiled.cueLists["cl"].cues
    assert [(c.trigger, c.triggerDelay) for c in cues] == [
        ("go", 0.0),
        ("follow", 1.5),
        ("wait", 8.0),
    ]
    assert [c.name for c in cues] == ["c1", "c2", "c3"]


# ------------------------------------------------------- targets, interning


def test_targets_are_own_then_tracked_in_previous_order() -> None:
    compiled = song(
        numbered("c1", 1, entry(targets("fx-mh2", "fx-mh1"), "intensity", literal(1.0))),
        numbered("c2", 2, entry(targets("fx-mh3"), "intensity", literal(1.0))),
        numbered(
            "c3",
            3,
            entry(targets("fx-mh1"), "color", literal(RED)),
            releases=[release("fx-mh2")],  # MH 2 holds nothing any more
        ),
    )
    keys = [[t["fixtureId"] for t in c.targets] for c in compiled.cueLists["cl"].cues]
    assert keys == [["fx-mh2", "fx-mh1"], ["fx-mh3", "fx-mh2", "fx-mh1"], ["fx-mh1", "fx-mh3"]]


def test_equal_timings_are_interned() -> None:
    bezier = {"bezier": (0.25, 0.1, 0.25, 1.0)}  # validation makes it a tuple
    compiled = song(
        numbered(
            "c1",
            1,
            entry(targets("fx-mh1", "fx-mh2"), "intensity", literal(1.0)),
            entry(targets("fx-mh1", "fx-mh2"), "pan", literal(10.0)),
            timed(targets("fx-mh3"), "pan", literal(10.0), fade=2.0),  # equals the default
            timed(targets("fx-mh1"), "tilt", literal(10.0), curve=bezier),
            timed(targets("fx-mh2"), "tilt", literal(10.0), curve=dict(bezier)),
            timing=timing(2.0, 0.0, 2.0, 0.0),
        )
    )
    first = compiled.cueLists["cl"].first
    assert first.timings == (
        SlotTiming(fade=2.0, delay=0.0, curve="linear"),
        SlotTiming(fade=2.0, delay=0.0, curve=bezier),
    )
    assert first.htpIn.tolist() == first.htpOut.tolist() == [0, 0]


# ----------------------------------------------------------------- effects
# phase-5-plan decision 8, §5.3: instances track by id.

CIRCLE = {
    "id": "t-circle",
    "name": "Circle",
    "layers": [
        {"attribute": "pan", "waveform": {"kind": "sine"}, "phaseOffset": 0, "mode": "add"},
        {"attribute": "tilt", "waveform": {"kind": "sine"}, "phaseOffset": 90, "mode": "add"},
    ],
}
DIM = {
    "id": "t-dim",
    "name": "Dim",
    "layers": [
        {"attribute": "intensity", "waveform": {"kind": "sine"}, "phaseOffset": 0,
         "mode": "absolute"},
    ],
}  # fmt: skip


def fx(instance_id: str, template_id: str, *fixture_ids: str, size: float = 10.0) -> Doc:
    """An instance at 1 Hz on element 0 of ``fixture_ids``."""
    return {
        "id": instance_id,
        "templateId": template_id,
        "targets": targets(*fixture_ids),
        "rate": {"kind": "hz", "value": 1.0},
        "direction": "forward",
        "size": size,
        "phase": {"start": 0, "end": 0},
        "groups": 1,
        "blocks": 1,
        "wings": 1,
    }


def effect_song(*cues: Doc, tracking: bool = True) -> CompiledShow:
    """:func:`song` with the circle and dim templates."""
    doc = busk_rig(spots=3)
    doc["effects"] = [CIRCLE, DIM]
    doc["cueLists"].append(cue_list("cl", 1, *cues))
    doc["cueLists"][0]["tracking"] = tracking
    doc["playbacks"].append(playback("pb", 1, "cl"))
    return compile_doc(doc)


def with_effects(made: Doc, *instances: Doc) -> Doc:
    made["effects"] = list(instances)
    return made


def running(compiled: CompiledShow) -> list[list[tuple[str, Any]]]:
    """Per cue: each instance in order, as ``(id, (size, {attribute:
    fixtures}))``: which members each of its layers still drives."""
    return [
        [
            (
                effect.key,
                (
                    effect.size,
                    {
                        layer.attribute: [effect.targets[m]["fixtureId"] for m in layer.member]
                        for layer in effect.layers
                    },
                ),
            )
            for effect in c.effects
        ]
        for c in compiled.cueLists["cl"].cues
    ]


ALL3 = ["fx-mh1", "fx-mh2", "fx-mh3"]


def test_effects_track_by_id_until_replaced_released_or_blocked() -> None:
    compiled = effect_song(
        with_effects(numbered("c1", 1), fx("a", "t-circle", *ALL3), fx("b", "t-dim", "fx-mh2")),
        numbered("c2", 2, releases=[release("fx-mh2", attributes=["pan"])]),
        with_effects(  # its own `a` is not trimmed by its own release of MH 1
            numbered("c3", 3, releases=[release("fx-mh1")]),
            fx("a", "t-circle", "fx-mh1", "fx-mh3", size=20.0),
            fx("d", "t-dim", "fx-mh3"),
        ),
        numbered("c4", 4, releases=[release("fx-mh2", attributes=["intensity"])]),
        with_effects(numbered("c5", 5, block=True), fx("c", "t-dim", "fx-mh1")),
        numbered("c6", 6),
    )
    circle = {"pan": ALL3, "tilt": ALL3}
    a20 = (20.0, {"pan": ["fx-mh1", "fx-mh3"], "tilt": ["fx-mh1", "fx-mh3"]})
    b = (10.0, {"intensity": ["fx-mh2"]})
    d = (10.0, {"intensity": ["fx-mh3"]})
    c = (10.0, {"intensity": ["fx-mh1"]})
    assert running(compiled) == [
        [("a", (10.0, circle)), ("b", b)],
        [("a", (10.0, {"pan": ["fx-mh1", "fx-mh3"], "tilt": ALL3})), ("b", b)],  # trimmed
        [("a", a20), ("b", b), ("d", d)],  # replaced in place, d appended
        [("a", a20), ("d", d)],  # b lost its only lane
        [("c", c)],  # a block holds only its own
        [("c", c)],
    ]
    cues = compiled.cueLists["cl"].cues
    assert cues[1].effects[1] is cues[0].effects[1]  # untouched: the same object
    assert cues[3].effects[0] is cues[2].effects[0]


def test_a_non_tracking_list_holds_each_cues_own_effects() -> None:
    compiled = effect_song(
        with_effects(numbered("c1", 1), fx("a", "t-circle", "fx-mh1")),
        numbered("c2", 2),
        with_effects(numbered("c3", 3), fx("b", "t-dim", "fx-mh2")),
        tracking=False,
    )
    assert [[key for key, _ in cue] for cue in running(compiled)] == [["a"], [], ["b"]]


def test_targets_list_what_the_effects_drive_after_the_values() -> None:
    compiled = effect_song(
        with_effects(
            numbered("c1", 1, entry(targets("fx-mh2"), "intensity", literal(1.0))),
            fx("a", "t-circle", "fx-mh3", "fx-mh1", "fx-mh2"),
        ),
        numbered("c2", 2, releases=[release("fx-mh3")]),  # the circle no longer moves MH 3
    )
    keys = [[t["fixtureId"] for t in c.targets] for c in compiled.cueLists["cl"].cues]
    assert keys == [["fx-mh2", "fx-mh3", "fx-mh1"], ["fx-mh2", "fx-mh1"]]
