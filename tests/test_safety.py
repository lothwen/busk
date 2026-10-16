"""The safety stage: park and limits (phase-7-plan decision 11, §5.10, step 3).

Appendix A's MH 1 is parked (pan, tilt, intensity, colour, gobo, shutter)
and every source the engine has drives both moving heads: MH 1 must stay
exactly where it is parked while MH 2 moves. Masters do not scale a parked
intensity and blackout darkens it. Limits clamp pan, tilt and intensity of
every element, after the masters, and the frames stay independent of the
tick schedule.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from builders import (
    APPENDIX_A,
    Doc,
    channel,
    compile_doc,
    fixture,
    frame,
    load_doc,
    mode,
    profile,
    rng,
    show,
)
from busk.model.common import FixtureId, TargetRef
from harness import Harness, blackout, fader, go, toggle
from session_harness import Live, put, sel


def parked(fixture_id: str, attribute: str, value: Any, element: int = 0) -> Doc:
    return {
        "slot": {"target": {"fixtureId": fixture_id, "element": element}, "attribute": attribute},
        "value": value,
    }


GREEN = {"r": 0, "g": 1, "b": 0}  # MH 1 has a white emitter: its extra is derived
PARK = [
    parked("fx-mh1", "pan", 10),
    parked("fx-mh1", "tilt", -30),
    parked("fx-mh1", "intensity", 0.5),
    parked("fx-mh1", "color", GREEN),
    parked("fx-mh1", "gobo1", {"slot": "breakup"}),
    parked("fx-mh1", "shutter", {"slot": "closed"}),
]
PARKED_VALUES = {
    ("fx-mh1", "pan"): 10,
    ("fx-mh1", "tilt"): -30,
    ("fx-mh1", "intensity"): 0.5,
    ("fx-mh1", "color"): GREEN,
    ("fx-mh1", "gobo1"): {"slot": "breakup"},
    ("fx-mh1", "shutter"): {"slot": "closed"},
}
SWEEP = {  # an absolute pan effect
    "id": "ef-sweep",
    "name": "Sweep",
    "layers": [{"attribute": "pan", "waveform": {"kind": "sine"}, "phaseOffset": 0,
                "mode": "absolute"}],
}  # fmt: skip
CIRCLE = {  # a relative one
    "id": "ef-circle",
    "name": "Circle",
    "layers": [
        {"attribute": "pan", "waveform": {"kind": "sine"}, "phaseOffset": 0, "mode": "add"},
        {"attribute": "tilt", "waveform": {"kind": "sine"}, "phaseOffset": 90, "mode": "add"},
    ],
}
BOTH = sel("fx-mh1", "fx-mh2")


def appendix(park: list[Doc] | None = None) -> Doc:
    """Appendix A with ``park`` (MH 1's six entries by default) and two more
    effect templates."""
    doc = load_doc(APPENDIX_A)
    doc["park"] = copy.deepcopy(PARK if park is None else park)
    doc["effects"] += [SWEEP, CIRCLE]
    return doc


def add_effect(template: str, size: float, **bounds: Any) -> dict[str, Any]:
    """ADD_EFFECT of ``template`` on the moving heads at 1 Hz."""
    instance = {
        "id": f"ei-{template}",
        "templateId": template,
        "targets": {"kind": "group", "groupId": "g-mh"},
        "rate": {"kind": "hz", "value": 1},
        "direction": "forward",
        "size": size,
        "phase": {"start": 0, "end": 0},
        "groups": 1,
        "blocks": 1,
        "wings": 1,
        **bounds,
    }
    return {"type": "ADD_EFFECT", "effect": instance}


def slot_lanes(live: Live, fixture_id: str) -> dict[str, list[float]]:
    """Every slot's lanes of ``fixture_id`` after the last tick."""
    slots = live.engine.compiled.slots
    target = TargetRef(fixtureId=FixtureId(fixture_id), element=0)
    return {
        slot.attribute.id: [float(v) for v in live.engine.logical[slot.lanes]]
        for slot in slots.slots
        if slot.target == target
    }


def expected_parked(live: Live) -> dict[str, list[float]]:
    """MH 1's lanes as the park entries encode them."""
    encoded = frame(live.engine.compiled, PARKED_VALUES)
    slots = live.engine.compiled.slots
    target = TargetRef(fixtureId=FixtureId("fx-mh1"), element=0)
    return {
        attribute: [float(v) for v in encoded[found.lanes]]
        for (_, attribute) in PARKED_VALUES
        if (found := slots.find(target, attribute)) is not None
    }


# ------------------------------------------------------ no source moves park

type Source = tuple[Callable[[Doc], None], list[dict[str, Any]]]


def _no_change(doc: Doc) -> None:
    pass


def _swop_button(doc: Doc) -> None:
    doc["playbacks"][1]["buttons"] = ["swop"]


def _override_band(doc: Doc) -> None:
    doc["playbacks"][0]["priority"] = 200  # above the programmer's band 100


SOURCES: dict[str, Source] = {
    "playback": (_no_change, [{"type": "SET_FADER", "playbackId": "pb-song", "level": 1}]),
    "flash": (_no_change, [{"type": "FLASH", "playbackId": "pb-blue", "down": True}]),
    "swop": (_swop_button, [
        {"type": "SET_FADER", "playbackId": "pb-song", "level": 1},
        {"type": "PLAYBACK_BUTTON", "playbackId": "pb-blue", "button": 0, "down": True},
    ]),
    "override band": (_override_band, [
        BOTH, put("pan", 45),
        {"type": "SET_FADER", "playbackId": "pb-song", "level": 1},
    ]),
    "programmer": (_no_change, [
        BOTH, put("pan", 45), put("tilt", 60), put("intensity", 1),
        put("color", {"r": 1, "g": 0, "b": 0, "w": 1}), put("gobo1", {"slot": "open"}),
        put("shutter", {"slot": "open"}),
    ]),
    "absolute effect": (_no_change, [BOTH, add_effect("ef-sweep", 1, low=-90, high=90)]),
    "relative effect": (_no_change, [BOTH, put("pan", 0), put("tilt", 0),
                                     add_effect("ef-circle", 40)]),
    "intensity effect": (_no_change, [BOTH, put("intensity", 1),
                                      {"type": "TOGGLE_PLAYBACK", "playbackId": "pb-pulse"}]),
}  # fmt: skip


@pytest.mark.parametrize("name", SOURCES)
def test_no_source_moves_a_parked_slot(name: str) -> None:
    change, commands = SOURCES[name]
    doc = appendix()
    change(doc)
    live = Live(doc)
    live.tick()
    mh2_before = slot_lanes(live, "fx-mh2")
    live.do(*commands)
    want = expected_parked(live)
    moved = False
    for _ in range(150):
        live.tick()
        lanes = slot_lanes(live, "fx-mh1")
        np.testing.assert_array_equal(
            np.concatenate([lanes[a] for a in want]),
            np.concatenate(list(want.values())),
            err_msg=f"{name} at {live.now}",
        )
        moved |= slot_lanes(live, "fx-mh2") != mh2_before
    assert moved, f"{name} did not drive MH 2"


def test_masters_do_not_scale_a_parked_intensity_and_blackout_darkens_it() -> None:
    live = Live(appendix())
    live.do(
        {"type": "SET_FADER", "playbackId": "pb-song", "level": 1},
        {"type": "SET_MASTER", "masterId": "m-gm", "level": 0.5},
    )
    for _ in range(300):  # past the cue's fade
        live.tick()
    assert live.lanes("fx-mh1", "intensity") == [0.5]
    assert live.lanes("fx-mh2", "intensity") == pytest.approx([0.2])  # 0.4 × 0.5
    live.do({"type": "BLACKOUT", "on": True})
    live.tick()
    assert live.lanes("fx-mh1", "intensity") == [0.0]
    assert live.lanes("fx-mh2", "intensity") == [0.0]
    assert live.lanes("fx-mh1", "pan") == [10.0]  # park outranks blackout off intensity
    live.do({"type": "BLACKOUT", "on": False})
    live.tick()
    assert live.lanes("fx-mh1", "intensity") == [0.5]


def test_parked_colour_gobo_and_shutter_bytes() -> None:
    """MH 1's 16 channels while parked equal what the programmer produces
    with the same values and no park, derived white included."""
    parked_live = Live(appendix())
    parked_live.do(BOTH, put("color", {"r": 1, "g": 0, "b": 1}), put("shutter", {"slot": "open"}))
    parked_live.tick()
    reference = Live(appendix(park=[]))
    reference.do(sel("fx-mh1"))
    for (_, attribute), value in PARKED_VALUES.items():
        reference.do(put(attribute, value))
    reference.tick()
    assert parked_live.universe()[:16] == reference.universe()[:16]
    white = parked_live.lanes("fx-mh1", "color")[3]
    assert white != white  # NaN: the converter derives the white extra


# ------------------------------------------------------------- live edits


def test_live_edits_park_and_unpark_at_the_next_tick_across_a_repatch() -> None:
    live = Live(appendix(park=[]))
    live.do(sel("fx-mh1"), put("pan", 45))
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [45.0]
    live.do({"type": "SET", "path": ["park"], "value": [parked("fx-mh1", "pan", 10)]})
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [10.0]
    pan_bytes = live.universe()[0:2]
    live.do(
        {"type": "PATCH_FIXTURE", "fixtureId": "fx-mh1",
         "patch": {"universeId": "u1", "address": 201}}
    )  # fmt: skip
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [10.0]
    assert live.universe()[200:202] == pan_bytes
    live.do({"type": "SET", "path": ["park"], "value": []})
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [45.0]
    live.do({"type": "UNDO"})
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [10.0]


# ----------------------------------------------------------------- limits


def limited(**limits: Any) -> Doc:
    doc = appendix(park=[])
    doc["fixtures"][0]["limits"] = limits
    return doc


@pytest.mark.parametrize(
    ("pan", "tilt", "want"),
    [(-90, -135, (-30.0, -120.0)), (90, 135, (60.0, 120.0)), (20, -5, (20.0, -5.0))],
)
def test_limits_clamp_both_ends_of_pan_and_tilt(
    pan: float, tilt: float, want: tuple[float, float]
) -> None:
    live = Live(limited(pan=[-30, 60], tilt=[-120, 120]))
    live.do(BOTH, put("pan", pan), put("tilt", tilt))
    live.tick()
    assert (live.lanes("fx-mh1", "pan")[0], live.lanes("fx-mh1", "tilt")[0]) == want
    assert (live.lanes("fx-mh2", "pan"), live.lanes("fx-mh2", "tilt")) == ([pan], [tilt])


def test_a_circle_is_flattened_at_a_limit() -> None:
    live = Live(limited(pan=[-10, 10]))
    live.do(BOTH, put("pan", 0), put("tilt", 0), add_effect("ef-circle", 40))
    mh1, mh2 = [], []
    for _ in range(200):  # two cycles
        live.tick()
        mh1.append(live.lanes("fx-mh1", "pan")[0])
        mh2.append(live.lanes("fx-mh2", "pan")[0])
    assert (min(mh2), max(mh2)) == pytest.approx((-40, 40), abs=1)  # the free head swings
    assert (min(mh1), max(mh1)) == (-10, 10)
    assert min(sum(p == -10 for p in mh1), sum(p == 10 for p in mh1)) > 20  # flat tops


def test_intensity_max_applies_after_the_grand_master() -> None:
    live = Live(limited(intensityMax=0.6))
    live.do(BOTH, put("intensity", 1))
    for level, want in [(1.0, 0.6), (0.5, 0.5), (0.8, 0.6)]:
        live.do({"type": "SET_MASTER", "masterId": "m-gm", "level": level})
        live.tick()
        assert live.lanes("fx-mh1", "intensity") == pytest.approx([want])
        assert live.lanes("fx-mh2", "intensity") == pytest.approx([level])


def test_limits_clamp_parked_values() -> None:
    doc = limited(pan=[-30, 60], intensityMax=0.4)
    doc["park"] = [parked("fx-mh1", "pan", 90), parked("fx-mh1", "intensity", 0.9)]
    live = Live(doc)  # validation warns; the limits win
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [60.0]
    assert live.lanes("fx-mh1", "intensity") == [0.4]


def test_every_element_of_a_multi_element_fixture_is_limited() -> None:
    def element(e: int) -> list[Doc]:
        return [
            channel(3 * e, "pan", rng(0, 255, -90, 90), element=e),
            channel(3 * e + 1, "tilt", rng(0, 255, -90, 90), element=e),
            channel(3 * e + 2, "intensity", element=e),
        ]

    bar = profile(
        "bar", mode(element(0) + element(1), elements=2),
        physical={"panRange": 180, "tiltRange": 180},
    )  # fmt: skip
    doc = show([bar], [fixture("fx-bar", 1, "bar", 1)])
    doc["fixtures"][0]["limits"] = {"pan": [-10, 20], "tilt": [0, 45], "intensityMax": 0.25}
    compiled = compile_doc(doc)
    base = frame(
        compiled,
        {("fx-bar", 0, "pan"): 90, ("fx-bar", 0, "tilt"): -45, ("fx-bar", 0, "intensity"): 1,
         ("fx-bar", 1, "pan"): -90, ("fx-bar", 1, "tilt"): 90, ("fx-bar", 1, "intensity"): 0.1},
    )  # fmt: skip
    logical = Harness(compiled, base).tick(0.0).logical
    lanes = {
        (slot.target["element"], slot.attribute.id): float(logical[slot.laneOffset])
        for slot in compiled.slots.slots
    }
    assert lanes == {
        (0, "pan"): 20, (0, "tilt"): 0, (0, "intensity"): 0.25,
        (1, "pan"): -10, (1, "tilt"): 45, (1, "intensity"): 0.1,
    }  # fmt: skip


# ------------------------------------------------------------ determinism


def test_frames_do_not_depend_on_the_tick_schedule() -> None:
    doc = appendix()
    doc["fixtures"][1]["limits"] = {"pan": [-5, 5], "intensityMax": 0.3}
    compiled = compile_doc(doc)
    script = [
        (0.05, fader("pb-song", 1.0)),
        (0.3, toggle("pb-pulse")),
        (0.6, go("pb-song")),
        (0.9, blackout(True)),
        (1.2, blackout(False)),
    ]
    regular = Harness(compiled).run(script, ticks=[i / 100 for i in range(200)])
    times = [i / 100 for i in (0, 5, 13, 30, 31, 60, 77, 90, 120, 150, 199)]
    irregular = Harness(compiled).run(script, ticks=times)
    for t in times:
        assert regular[t].frame.universes == irregular[t].frame.universes, t
