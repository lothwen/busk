"""The programmer as a band-100 source: override, blind, sequence order (phase-3-plan §5.7),
and its fades over ``fadeTime`` (phase-4-plan §5.10)."""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any

import pytest

from builders import (
    busk_rig,
    effect_instance,
    effect_layer,
    effect_template,
    entry,
    grand_master,
    group,
    in_group,
    literal,
    look,
    speed_master,
    targets,
)
from busk.engine.install import Install
from busk.session.frame import build_frame
from busk.session.programmer import Programmer, ProgSource
from session_harness import CLEAR, UNDO, Live, blind, fader, put, sel, trigger

BLACKOUT_ON = {"type": "BLACKOUT", "on": True}


@pytest.fixture
def live() -> Live:
    """Two spots; pb-base (band 50): intensity 0.8, pan 10, tilt 10 on both;
    pb-over (band 100, idle): pan 30, tilt 30 on both."""
    doc = busk_rig(spots=2)
    doc["groups"].append(group("g-heads", 1, "fx-mh1", "fx-mh2"))
    doc["masters"].append(grand_master())
    heads = in_group("g-heads")
    look(
        doc,
        "pb-base",
        1,
        entry(heads, "intensity", literal(0.8)),
        entry(heads, "pan", literal(10)),
        entry(heads, "tilt", literal(10)),
    )
    look(
        doc,
        "pb-over",
        2,
        entry(targets("fx-mh1", "fx-mh2"), "pan", literal(30)),
        entry(targets("fx-mh1", "fx-mh2"), "tilt", literal(30)),
        priority=100,
        fader="none",
    )
    live = Live(doc)
    live.do(fader("pb-base", 1.0))
    live.tick()
    return live


def test_programmer_intensity_overrides_playbacks_even_when_lower(live: Live) -> None:
    assert live.lanes("fx-mh1", "intensity") == [0.8]
    live.do(sel("fx-mh1"), put("intensity", 0.3), put("pan", -45))
    live.tick()
    assert live.lanes("fx-mh1", "intensity") == [0.3]  # band 100 beats band 50, even lower
    assert live.lanes("fx-mh1", "pan") == [-45.0]
    assert live.lanes("fx-mh2", "intensity") == [0.8]  # untouched
    assert live.lanes("fx-mh2", "pan") == [10.0]


def test_blind_excludes_the_programmer_and_leaving_it_retouches(live: Live) -> None:
    live.do(sel("fx-mh1"), put("pan", 20))
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [20.0]
    live.do(blind(True))
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [10.0]  # the playback again
    live.do(put("tilt", -5))  # programming blind: nothing reaches the stage
    live.tick()
    assert live.lanes("fx-mh1", "tilt") == [10.0]
    live.do(trigger("pb-over"))  # band 100, newer than the programmer's pan
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [30.0]
    live.do(blind(False))  # leaving blind touches every slot: the programmer is newest
    live.tick()
    assert (live.lanes("fx-mh1", "pan"), live.lanes("fx-mh1", "tilt")) == ([20.0], [-5.0])


def test_band_100_order_follows_each_slots_sequence(live: Live) -> None:
    live.do(sel("fx-mh1"), put("pan", 20))  # touched first
    live.do(trigger("pb-over"))  # then the band-100 playback
    live.do(put("tilt", 5))  # then a newer programmer touch
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [30.0]  # pb-over is newer than the pan touch
    assert live.lanes("fx-mh1", "tilt") == [5.0]  # the tilt touch is newer than pb-over
    live.do(put("pan", 21))  # touching pan again moves it on top
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [21.0]
    assert live.lanes("fx-mh2", "pan") == [30.0]


def test_selection_changes_do_not_retouch_values(live: Live) -> None:
    live.do(sel("fx-mh1"), put("pan", 20), trigger("pb-over"), sel("fx-mh2"))
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [30.0]


def test_grand_master_and_blackout_still_apply(live: Live) -> None:
    live.do(sel("fx-mh1"), put("intensity", 0.5))
    live.do({"type": "SET_MASTER", "masterId": "m-gm", "level": 0.5})
    live.tick()
    assert live.lanes("fx-mh1", "intensity") == [0.25]
    live.do(BLACKOUT_ON)
    live.tick()
    assert live.lanes("fx-mh1", "intensity") == [0.0]


def test_a_cleared_programmer_hands_back_to_the_playbacks(live: Live) -> None:
    live.do(sel("fx-mh1", "fx-mh2"), put("intensity", 1.0), put("pan", 0))
    live.tick()
    live.do({"type": "CLEAR_PROGRAMMER"})
    live.tick()
    assert live.lanes("fx-mh1", "intensity") == [0.8]
    assert live.lanes("fx-mh2", "pan") == [10.0]
    assert live.engine.stats.installErrors == 0


def test_programmer_updates_snap_and_share_one_sequence_number(live: Live) -> None:
    seq = live.engine.runtime.playbacks.seqCounter
    live.do(sel("fx-mh1", "fx-mh2"), put("pan", 1))
    live.tick()
    assert live.engine.runtime.playbacks.seqCounter == seq + 1  # one update, one number
    live.do(sel("fx-mh1"))
    live.tick()
    assert live.engine.runtime.playbacks.seqCounter == seq + 1  # selection only: no touch


def test_setting_the_same_value_again_moves_it_on_top(live: Live) -> None:
    """Setting a value is the operator's latest action, even when it does not change."""
    live.do(sel("fx-mh1"), put("pan", 20), trigger("pb-over"))
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [30.0]
    live.do(put("pan", 20))
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [20.0]
    assert live.session.timeline.undo_count == 2  # no step for an unchanged programmer


# ------------------------------------------------------------- fadeTime (Phase 4)
#
# The fixture's pb-base holds both heads at intensity 0.8, pan 10, tilt 10.
# A programmer change is applied at the tick after it is made; its fade
# starts there. Ticks past the end of a fade land exactly on the target.


def fade(time: float) -> dict[str, Any]:
    return {"type": "PROGRAMMER_FADE", "time": time}


def pan_and_intensity(live: Live) -> tuple[float, float]:
    return live.lanes("fx-mh1", "pan")[0], live.lanes("fx-mh1", "intensity")[0]


def test_a_value_change_fades_over_the_fade_time(live: Live) -> None:
    live.do(fade(2.0), sel("fx-mh1"), put("intensity", 0.3), put("pan", 20))
    live.tick()  # the fade starts: the programmer enters at weight 0
    assert pan_and_intensity(live) == (10.0, 0.8)
    live.tick(1.0)
    assert pan_and_intensity(live) == pytest.approx((15.0, 0.55))  # half way, HTP included
    live.tick(1.5)
    assert pan_and_intensity(live) == (20.0, 0.3)
    live.do(put("pan", 30))  # a change fades from where the slot is
    live.tick()
    assert pan_and_intensity(live) == (20.0, 0.3)
    live.tick(0.5)
    assert pan_and_intensity(live) == pytest.approx((22.5, 0.3))
    live.do(put("pan", 0))  # retargeting mid-fade: no jump
    live.tick()
    assert live.lanes("fx-mh1", "pan") == pytest.approx([22.5], abs=0.05)
    live.tick(1.0)
    assert live.lanes("fx-mh1", "pan") == pytest.approx([11.25], abs=0.05)
    assert live.lanes("fx-mh2", "pan") == [10.0]  # untouched


def test_a_clear_fades_out_to_the_playbacks(live: Live) -> None:
    live.do(sel("fx-mh1"), put("intensity", 0.3), put("pan", 20))  # fade time 0: snaps
    live.tick()
    assert pan_and_intensity(live) == (20.0, 0.3)
    live.do(fade(2.0), CLEAR)
    live.tick()
    assert pan_and_intensity(live) == (20.0, 0.3)
    live.tick(1.0)
    assert pan_and_intensity(live) == pytest.approx((15.0, 0.55))
    live.tick(1.5)
    assert pan_and_intensity(live) == (10.0, 0.8)


def test_blind_on_fades_out_and_blind_off_fades_in(live: Live) -> None:
    live.do(sel("fx-mh1"), put("pan", 20))
    live.tick()
    live.do(fade(2.0), blind(True))
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [20.0]
    live.tick(1.0)
    assert live.lanes("fx-mh1", "pan") == pytest.approx([15.0])
    live.tick(1.5)
    assert live.lanes("fx-mh1", "pan") == [10.0]
    live.do(put("pan", 40))  # programming blind: nothing reaches the stage
    live.tick(3.0)
    assert live.lanes("fx-mh1", "pan") == [10.0]
    live.do(blind(False))
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [10.0]
    live.tick(1.0)
    assert live.lanes("fx-mh1", "pan") == pytest.approx([25.0])
    live.tick(1.5)
    assert live.lanes("fx-mh1", "pan") == [40.0]


def test_undo_fades(live: Live) -> None:
    live.do(sel("fx-mh1"), put("pan", 20))
    live.tick()
    live.do(fade(2.0), put("pan", 40))
    live.tick()
    live.tick(2.5)
    assert live.lanes("fx-mh1", "pan") == [40.0]
    live.do(UNDO)  # back to pan 20, over the fade time
    live.tick()
    live.tick(1.0)
    assert live.lanes("fx-mh1", "pan") == pytest.approx([30.0])
    live.tick(1.5)
    assert live.lanes("fx-mh1", "pan") == [20.0]
    live.do(UNDO)  # the programmer is empty again: pan fades back to pb-base
    live.tick()
    live.tick(1.0)
    assert live.lanes("fx-mh1", "pan") == pytest.approx([15.0])
    live.tick(1.5)
    assert live.lanes("fx-mh1", "pan") == [10.0]


def test_touched_slots_go_on_top_and_fade_from_what_is_below(live: Live) -> None:
    live.do(trigger("pb-over"))  # band 100: pan and tilt 30
    live.tick()
    live.do(fade(2.0), sel("fx-mh1"), put("pan", 20))  # newer than pb-over
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [30.0]
    live.tick(1.0)
    assert live.lanes("fx-mh1", "pan") == pytest.approx([25.0])  # from pb-over's value
    live.tick(1.5)
    assert live.lanes("fx-mh1", "pan") == [20.0]
    assert live.lanes("fx-mh1", "tilt") == [30.0]  # untouched: pb-over


def test_slots_fading_out_keep_their_place_in_the_band(live: Live) -> None:
    live.do(sel("fx-mh1"), put("pan", 20), put("tilt", 20))
    live.do(trigger("pb-over"))  # newer than both programmer values
    live.do(put("tilt", 25))  # newer than pb-over
    live.tick()
    assert (live.lanes("fx-mh1", "pan"), live.lanes("fx-mh1", "tilt")) == ([30.0], [25.0])
    live.do(fade(2.0), CLEAR)
    live.tick()
    live.tick(1.0)
    assert live.lanes("fx-mh1", "pan") == [30.0]  # still under pb-over: no jump
    assert live.lanes("fx-mh1", "tilt") == pytest.approx([27.5])  # on top, fading to pb-over
    live.tick(1.5)
    assert (live.lanes("fx-mh1", "pan"), live.lanes("fx-mh1", "tilt")) == ([30.0], [30.0])


def test_a_fade_time_change_alone_changes_nothing_on_stage(live: Live) -> None:
    live.do(sel("fx-mh1"), put("pan", 20))
    live.tick()
    installs = live.engine.stats.installs
    live.do(fade(5.0))
    live.tick()
    assert live.engine.stats.installs == installs
    assert live.lanes("fx-mh1", "pan") == [20.0]


def test_a_slot_that_enters_untouched_still_takes_a_number(live: Live) -> None:
    """A frame can bring in a slot whose source did not change (a preset
    edited under a reference that now defines it): it takes the update's
    number, so it sits above older band-100 sources."""
    live.do(trigger("pb-over"))  # pan 30
    live.tick()
    pan: ProgSource = {"kind": "literal", "value": 20}
    programmer = Programmer(values=MappingProxyType({"fx-mh1:0/pan": pan}))
    frame = build_frame(live.session.state, programmer, programmer.values)
    assert (frame.touched.size, frame.slots.size) == (0, 1)
    seq = live.engine.runtime.playbacks.seqCounter
    live.engine.bus.install(Install(compiled=None, remap=None, programmer=frame))
    live.tick()
    assert live.engine.runtime.playbacks.seqCounter == seq + 1
    assert live.lanes("fx-mh1", "pan") == [20.0]


# ------------------------------------------------------------ effects (Phase 5)


def sweep(ident: str, *fixtures: str) -> dict[str, Any]:
    """A 1-Hz ``add`` sine on pan of size 20: pan moves ±20° around the base."""
    return effect_instance(ident, "t-sweep", targets(*fixtures), size=20.0)


def add_effect(effect: dict[str, Any]) -> dict[str, Any]:
    return {"type": "ADD_EFFECT", "effect": effect}


def swept(base: float, position: float, weight: float = 1.0) -> float:
    """Pan under a sweep at ``position`` (cycles), ``weight`` present."""
    w = 0.5 - 0.5 * math.cos(2.0 * math.pi * position)
    return base + weight * 20.0 * (2.0 * w - 1.0)


@pytest.fixture
def fx() -> Live:
    """The :func:`live` rig, plus the 120-BPM speed master m-speed, the
    templates t-sweep and t-saw (an absolute ``sawUp`` on intensity), and
    pb-sweep (band 50, no fader, idle) running the sweep on MH 1."""
    doc = busk_rig(spots=2)
    doc["groups"].append(group("g-heads", 1, "fx-mh1", "fx-mh2"))
    doc["masters"].append(speed_master())
    doc["effects"] = [
        effect_template("t-sweep", effect_layer("pan", "sine", "add")),
        effect_template("t-saw", effect_layer("intensity", "sawUp")),
    ]
    heads = in_group("g-heads")
    look(
        doc, "pb-base", 1, entry(heads, "intensity", literal(0.8)), entry(heads, "pan", literal(10))
    )
    look(doc, "pb-over", 2, entry(heads, "pan", literal(30)), priority=100, fader="none")
    look(doc, "pb-sweep", 3, priority=50, fader="none")
    doc["cueLists"][-1]["cues"][0]["effects"] = [sweep("e-band", "fx-mh1")]
    live = Live(doc)
    live.do(fader("pb-base", 1.0))
    live.tick()
    return live


def test_a_programmer_effect_runs_at_band_100(fx: Live) -> None:
    seq = fx.engine.runtime.playbacks.seqCounter
    fx.do(add_effect(sweep("fx1", "fx-mh1")))
    fx.tick()  # the clock starts: P = t − t0
    t0 = fx.now
    assert fx.engine.runtime.playbacks.seqCounter == seq + 1  # touching only effects takes a number
    assert fx.lanes("fx-mh1", "pan") == pytest.approx([swept(10.0, 0.0)])
    fx.tick(0.4)
    assert fx.lanes("fx-mh1", "pan") == pytest.approx([swept(10.0, 0.4)])
    assert fx.lanes("fx-mh2", "pan") == [10.0]
    fx.do(trigger("pb-over"))  # band 100 does not suspend it: it is in band 100 too
    fx.tick(0.1)
    assert fx.lanes("fx-mh1", "pan") == pytest.approx([swept(30.0, fx.now - t0)])


def test_a_programmer_effect_enters_and_leaves_over_the_fade_time(fx: Live) -> None:
    fx.do(fade(2.0), add_effect(sweep("fx1", "fx-mh1")))
    fx.tick()
    t0 = fx.now
    fx.tick(1.3)
    assert fx.lanes("fx-mh1", "pan") == pytest.approx([swept(10.0, 1.3, 0.65)])
    fx.tick(1.0)
    assert fx.lanes("fx-mh1", "pan") == pytest.approx([swept(10.0, 2.3)])
    fx.do({"type": "REMOVE_EFFECT", "id": "fx1"})
    fx.tick()
    t1 = fx.now
    fx.tick(0.5)  # it keeps moving while it fades out
    assert fx.lanes("fx-mh1", "pan") == pytest.approx([swept(10.0, fx.now - t0, 0.75)])
    fx.tick(1.6)
    assert fx.now > t1 + 2.0
    assert fx.lanes("fx-mh1", "pan") == [10.0]
    assert fx.engine._programmer.bank.runtimes == {}


def test_a_programmer_pan_suspends_a_band_50_effect_and_clear_restores_it(fx: Live) -> None:
    fx.do(trigger("pb-sweep"))
    fx.tick()
    t0 = fx.now
    fx.tick(0.3)
    assert fx.lanes("fx-mh1", "pan") == pytest.approx([swept(10.0, 0.3)])
    fx.do(sel("fx-mh1"), put("pan", -45))
    fx.tick(0.1)
    assert fx.lanes("fx-mh1", "pan") == [-45.0]  # a higher band covers the lane: suspended
    fx.do(CLEAR)
    fx.tick(0.1)
    assert fx.lanes("fx-mh1", "pan") == pytest.approx([swept(10.0, fx.now - t0)])  # same clock


def test_blind_takes_programmer_effects_off_stage_and_back(fx: Live) -> None:
    fx.do(add_effect(sweep("fx1", "fx-mh1")))
    fx.tick()
    fx.tick(0.3)
    fx.do(blind(True))
    fx.tick()
    assert fx.lanes("fx-mh1", "pan") == [10.0]
    fx.do(add_effect(sweep("fx2", "fx-mh2")))  # added blind: not on stage
    fx.tick(0.2)
    assert fx.lanes("fx-mh2", "pan") == [10.0]
    seq = fx.engine.runtime.playbacks.seqCounter
    fx.do(blind(False))  # both enter now, on new clocks, with one new number
    fx.tick()
    assert fx.lanes("fx-mh1", "pan") == fx.lanes("fx-mh2", "pan") == pytest.approx([-10.0])
    runtimes = fx.engine._programmer.bank.runtimes
    assert {key: rt.seq for key, rt in runtimes.items()} == {"fx1": seq + 1, "fx2": seq + 1}


def test_programmer_effects_follow_a_live_swap(fx: Live) -> None:
    """An edited template changes a programmer effect on its own clock, over
    the fade time (here 0: at once), without a number; a slot remap carries
    it to its target's new lanes, running on untouched (no 1-s cross-fade)."""
    fx.do(add_effect(sweep("fx1", "fx-mh2")))
    fx.tick()
    t0 = fx.now
    seq = fx.engine.runtime.playbacks.seqCounter
    shifted = effect_layer("pan", "sine", "add", phaseOffset=90)
    fx.do({"type": "SET", "path": ["effects", {"id": "t-sweep"}, "layers"], "value": [shifted]})
    fx.tick(0.3)
    assert fx.lanes("fx-mh2", "pan") == pytest.approx([swept(10.0, 0.3 + 0.25)])
    assert fx.engine.runtime.playbacks.seqCounter == seq
    sweep_cue = ["cueLists", {"id": "cl-pb-sweep"}, "cues", {"id": "c-pb-sweep"}, "effects"]
    mh2 = {"fixtureId": "fx-mh2", "element": 0}
    drop_mh1 = [
        {"type": "SET", "path": ["groups", {"id": "g-heads"}, "members"], "value": [mh2]},
        {"type": "SET", "path": sweep_cue, "value": []},
        {"type": "DELETE", "path": ["fixtures", {"id": "fx-mh1"}]},
    ]
    fx.do(fade(1.0), {"type": "BATCH", "label": "drop MH 1", "commands": drop_mh1})
    fx.tick(0.1)  # MH 2's lanes moved
    assert fx.lanes("fx-mh2", "pan") == pytest.approx([swept(10.0, fx.now - t0 + 0.25)])
    assert fx.engine.stats.installErrors == 0


def saw(ident: str, **fields: Any) -> dict[str, Any]:
    """An absolute 1-Hz ``sawUp`` on MH 2's intensity: it shows its phase."""
    return effect_instance(ident, "t-saw", targets("fx-mh2"), **fields)


def test_an_absolute_programmer_effect_overrides_lower_bands(fx: Live) -> None:
    fx.do(add_effect(saw("fx1")))
    fx.tick()
    fx.tick(0.3)
    assert fx.lanes("fx-mh2", "intensity") == pytest.approx([0.3])  # under pb-base's 0.8
    assert fx.lanes("fx-mh1", "intensity") == [0.8]


def test_adding_the_same_effect_again_renumbers_only_it(fx: Live) -> None:
    fx.do(add_effect(sweep("fx1", "fx-mh1")), add_effect(sweep("fx2", "fx-mh2")))
    fx.tick()
    runtimes = fx.engine._programmer.bank.runtimes
    first, second = runtimes["fx1"], runtimes["fx2"]
    numbers, clock = (first.seq, second.seq), first.clock
    fx.do(add_effect(sweep("fx1", "fx-mh1")))  # the latest action, though nothing changed
    fx.tick()
    seq = fx.engine.runtime.playbacks.seqCounter
    assert (first.seq, second.seq) == (seq, numbers[1])
    assert seq > max(numbers)
    assert (runtimes["fx1"], first.clock) == (first, clock)  # the same instance, clock and all


def test_an_effect_that_enters_untouched_still_takes_a_number(fx: Live) -> None:
    """A frame can bring in an effect whose instance did not change (an undo
    that restores its template): it takes the update's number."""
    instance = sweep("fx1", "fx-mh1")
    programmer = Programmer(effects=(instance,))
    frame = build_frame(fx.session.state, programmer, {}, previous_effects=(instance,))
    assert (frame.touchedEffects, len(frame.effects)) == (frozenset(), 1)
    seq = fx.engine.runtime.playbacks.seqCounter
    fx.engine.bus.install(Install(compiled=None, remap=None, programmer=frame))
    fx.tick()
    assert fx.engine.runtime.playbacks.seqCounter == seq + 1
    assert fx.engine._programmer.bank.runtimes["fx1"].seq == seq + 1
    # Gone at once (fade 0) and back before a tick dropped it: it enters again.
    gone = build_frame(fx.session.state, Programmer(), {}, previous_effects=(instance,))
    fx.engine.bus.install(Install(compiled=None, remap=None, programmer=gone))
    fx.engine.bus.install(Install(compiled=None, remap=None, programmer=frame))
    fx.tick()
    assert fx.engine.runtime.playbacks.seqCounter == seq + 2
    assert fx.engine._programmer.bank.runtimes["fx1"].seq == seq + 2


def test_taps_speed_steps_and_master_edits_reach_programmer_effects(fx: Live) -> None:
    """A BPM saw at ×1 shows the beat count B. A tap re-phases the master to
    the nearest beat, and the saw carries on without a jump; a speed step
    (×4) and an edit of the steps (×8) re-rate it onto the new grid within a
    beat (0.5 s at 120 BPM)."""
    master = fx.engine.runtime.speed["m-speed"]
    fx.do(add_effect(saw("fx1", rate={"kind": "bpm", "masterId": "m-speed", "multiplier": 1.0})))
    fx.tick()
    fx.tick(1.13)
    before = fx.lanes("fx-mh2", "intensity")
    assert before == pytest.approx([master.beats(fx.now) % 1.0])
    fx.do({"type": "TAP", "masterId": "m-speed"})
    fx.tick(0.0)
    assert master.beats(fx.now) == pytest.approx(2.0)  # the tap landed on a beat
    assert fx.lanes("fx-mh2", "intensity") == pytest.approx(before)
    fx.tick(1.0)
    fx.do({"type": "SET_MASTER", "masterId": "m-speed", "level": 1.0})
    fx.tick(0.01)  # applied here
    fx.tick(0.56)
    assert fx.lanes("fx-mh2", "intensity") == pytest.approx([(4.0 * master.beats(fx.now)) % 1.0])
    steps = ["masters", {"id": "m-speed"}, "multiplierSteps"]
    fx.do({"type": "SET", "path": steps, "value": [0.25, 0.5, 1, 2, 8]})
    fx.tick(0.01)
    fx.tick(0.53)
    assert fx.lanes("fx-mh2", "intensity") == pytest.approx([(8.0 * master.beats(fx.now)) % 1.0])
