"""Effect runtimes and banks, without the engine (phase-5-plan §5.5,
decisions 4, 6, 9–12; step 6).

The rig is two Appendix A spots (RGBW colour) and two RGB pars. Each test
compiles a cue list whose cues hold effect instances, then drives an
:class:`EffectBank` with those cues' compiled effects directly. Effects run
at 1 Hz unless a test says otherwise, so the clock's position is the time
since the instance entered, in cycles.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from builders import busk_rig, compile_doc, cue, cue_list, rgb, slot_of, speed_master, targets
from busk.compiler.compile import CompiledShow
from busk.compiler.effects import CompiledEffect
from busk.engine.effects import (
    EffectBank,
    EffectScalars,
    EffectTiming,
    base_phase,
    timing_of,
)
from busk.engine.fades import SeqRule, Timing
from busk.engine.masters import SpeedMasterRuntime

type Doc = dict[str, Any]

STEP = EffectTiming.uniform(Timing())  # every fade a step: the steady state at once
SPOTS = targets("fx-mh1", "fx-mh2")


def scalar(attribute: str, kind: str, mode: str = "absolute", offset: float = 0.0) -> Doc:
    return {
        "attribute": attribute,
        "waveform": {"kind": kind},
        "phaseOffset": offset,
        "mode": mode,
    }


def template(template_id: str, *layers: Doc) -> Doc:
    return {"id": template_id, "name": template_id, "layers": list(layers)}


def colours(blend: str) -> Doc:
    return {
        "attribute": "color",
        "palette": [rgb(1, 0, 0), rgb(0, 1, 0), rgb(0, 0, 1)],
        "blend": blend,
        "mode": "absolute",
    }


TEMPLATES = [
    template("t-saw", scalar("intensity", "sawUp")),
    template("t-circle", scalar("pan", "sine", "add"), scalar("tilt", "sine", "add", 90.0)),
    template("t-pulse", scalar("intensity", "sine", "multiply")),
    template("t-fade", colours("fade")),
    template("t-snap", colours("snap")),
]


def instance(instance_id: str, template_id: str, spec: Doc = SPOTS, **fields: Any) -> Doc:
    doc: Doc = {
        "id": instance_id,
        "templateId": template_id,
        "targets": spec,
        "rate": {"kind": "hz", "value": 1.0},
        "direction": "forward",
        "size": 1.0,
        "phase": {"start": 0, "end": 0},
        "groups": 1,
        "blocks": 1,
        "wings": 1,
    }
    doc.update(fields)
    return doc


def compile_cues(*cues: list[Doc]) -> tuple[CompiledShow, list[tuple[CompiledEffect, ...]]]:
    """A show whose cue list ``cl`` has one cue per argument, holding those
    instances; returns it and each cue's compiled effects."""
    doc = busk_rig(2, 2)
    doc["effects"] = TEMPLATES
    doc["masters"] = [speed_master(), {"id": "m-size", "kind": "size", "name": "FX"}]
    built = []
    for k, instances in enumerate(cues, start=1):
        each = cue(f"c{k}", number=str(k))
        each["effects"] = instances
        built.append(each)
    doc["cueLists"] = [cue_list("cl", 1, *built)]
    compiled = compile_doc(doc)
    return compiled, [c.effects for c in compiled.cueLists["cl"].cues]


def bank(compiled: CompiledShow | None = None, now: float = 0.0) -> EffectBank:
    speed = {}
    if compiled is not None:
        speed = {"m-speed": SpeedMasterRuntime(compiled.masters["m-speed"], now)}  # type: ignore[index]
    return EffectBank("pb", 50, speed)


def lane(compiled: CompiledShow, fixture_id: str, attribute: str) -> int:
    return int(slot_of(compiled, fixture_id, attribute).laneOffset)


def position(compiled: CompiledShow, fixture_id: str) -> int:
    lanes = compiled.slots.intensityLanes
    return int(np.searchsorted(lanes, lane(compiled, fixture_id, "intensity")))


def effective(fx: EffectBank) -> dict[tuple[str, str, int], tuple[float | None, float]]:
    """Every lane the bank drives, by ``(instance, output, lane)``: its value
    (``None`` for NaN, "derive") and its effective weight, scalar × per lane.
    Lanes at weight 0 are left out: their values do not matter."""
    out: dict[tuple[str, str, int], tuple[float | None, float]] = {}

    def add(key: str, kind: str, lanes: Any, values: Any, weights: Any, scalar: float) -> None:
        for i, at in enumerate(lanes):
            weight = scalar * (1.0 if weights is None else float(weights[i]))
            if weight > 0.0:
                value = float(values[i])
                out[key, kind, int(at)] = (None if math.isnan(value) else value, weight)

    for rt in fx.runtimes.values():
        s = rt.source
        add(rt.key, "htp", s.htpPos, s.htpValues, s.htpWeights, s.htpWeight * s.intensityScale)
        add(rt.key, "ltp", s.ltpLanes, s.ltpValues, s.ltpWeights, s.ltpWeight)
        add(rt.key, "snap", s.snapLanes, s.snapValues, s.snapWeights, s.ltpWeight)
        for rel in rt.relatives:
            add(rt.key, rel.op, rel.lanes, rel.amounts, rel.weights, rel.weight)
    return out


def same_outputs(a: dict[Any, Any], b: dict[Any, Any]) -> bool:
    if a.keys() != b.keys():
        return False
    for key, (value, weight) in a.items():
        other, other_weight = b[key]
        if abs(weight - other_weight) > 1e-9:
            return False
        if (value is None) != (other is None):
            return False
        if value is not None and abs(value - other) > 1e-9 * max(1.0, abs(value)):
            return False
    return True


# ------------------------------------------------------------------- outputs


def test_an_absolute_layer_sweeps_from_low_to_high_at_each_members_phase() -> None:
    compiled, (effects,) = compile_cues([instance("e", "t-saw", phase={"start": 0, "end": 360})])
    fx = bank()
    assert fx.retarget(0.0, effects, STEP, SeqRule.all(7)) == 0.0
    fx.update(0.25, EffectScalars())
    (rt,) = fx.runtimes.values()
    source = rt.source
    assert source.htpPos.tolist() == [position(compiled, "fx-mh1"), position(compiled, "fx-mh2")]
    assert source.htpValues.tolist() == [0.25, 0.75]  # mh2 is half a cycle on
    assert (source.htpWeight, source.ltpWeight, source.seq, source.seqs) == (1.0, 0.0, 7, ())
    assert source.htpWeights is None


def test_dynamics_scale_an_absolute_layers_presence_not_its_values() -> None:
    _, (effects,) = compile_cues([instance("e", "t-saw", sizeMasterId="m-size")])
    fx = bank()
    fx.retarget(0.0, effects, STEP, SeqRule.all(1))
    scalars = EffectScalars(htpWeight=0.8, intensityScale=0.5, size=0.5, sizeLevels={"m-size": 0.5})
    fx.update(0.25, scalars)
    source = fx.runtimes["e"].source
    assert source.htpValues.tolist() == [0.25, 0.25]
    assert (source.htpWeight, source.intensityScale) == (0.8 * 0.25, 0.5)


def test_relative_amounts_carry_size_and_dynamics() -> None:
    compiled, (effects,) = compile_cues(
        [instance("c", "t-circle", size=15.0), instance("p", "t-pulse", size=0.6)]
    )
    fx = bank()
    fx.retarget(0.0, effects, STEP, SeqRule.all(1))
    fx.update(0.25, EffectScalars(size=0.5))
    pan, tilt = fx.runtimes["c"].relatives
    assert (pan.op, tilt.op) == ("add", "add")
    assert pan.lanes.tolist() == [lane(compiled, f, "pan") for f in ("fx-mh1", "fx-mh2")]
    assert pan.amounts.tolist() == pytest.approx([0.0, 0.0])  # sine at ¼: w = ½
    assert tilt.amounts.tolist() == pytest.approx([7.5, 7.5])  # 90° on: the crest, size 15·½
    assert pan.clamp is None
    (pulse,) = fx.runtimes["p"].relatives
    assert pulse.op == "multiply"
    assert pulse.amounts.tolist() == pytest.approx([1 - 0.3 * 0.5] * 2)  # 1 − size·d·(1 − w)
    assert not fx.runtimes["c"].source.present  # relative layers only: absent


def test_relative_weights_follow_their_kind_of_lane() -> None:
    _, (effects,) = compile_cues([instance("c", "t-circle"), instance("p", "t-pulse")])
    fx = bank()
    fx.retarget(0.0, effects, EffectTiming.uniform(Timing(duration=2.0)), SeqRule.all(1))
    fx.update(1.0, EffectScalars(htpWeight=0.8, intensityScale=0.5, ltpWeight=0.6))
    (pan, tilt), (pulse,) = fx.runtimes["c"].relatives, fx.runtimes["p"].relatives
    assert (pan.weight, tilt.weight) == (0.6 * 0.5, 0.6 * 0.5)  # ltpWeight × presence
    assert pulse.weight == 0.8 * 0.5 * 0.5  # env × intensityScale × presence
    assert pan.weights is None


@pytest.mark.parametrize(
    ("blend", "expected"), [("fade", [0.0, 0.5, 0.5]), ("snap", [0.0, 1.0, 0.0])]
)
def test_a_palette_cycles_and_holds_the_extras_at_derive(blend: str, expected: list[float]) -> None:
    compiled, (effects,) = compile_cues([instance("e", f"t-{blend}", targets("fx-mh1"))])
    fx = bank()
    fx.retarget(0.0, effects, STEP, SeqRule.all(3))
    fx.update(0.5, EffectScalars(ltpWeight=0.9))  # x = 1.5 between green and blue
    source = fx.runtimes["e"].source
    red = lane(compiled, "fx-mh1", "color")
    assert source.ltpLanes.tolist() == [red, red + 1, red + 2]
    assert source.ltpValues.tolist() == expected
    assert source.snapLanes.tolist() == [red + 3]  # W
    assert np.isnan(source.snapValues).all()
    assert source.snapThresholds.tolist() == [0.5]
    assert (source.ltpWeight, source.seqs) == (0.9, (3,))


def test_a_palette_wraps_back_to_its_first_colour() -> None:
    _, (effects,) = compile_cues([instance("e", "t-fade", targets("fx-mh1"))])
    fx = bank()
    fx.retarget(0.0, effects, STEP, SeqRule.all(1))
    fx.update(0.875, EffectScalars())  # x = 2.625: blue → red
    assert fx.runtimes["e"].source.ltpValues.tolist() == pytest.approx([0.625, 0.0, 0.375])


@pytest.mark.parametrize(
    ("direction", "positions", "phases"),
    [
        ("forward", [0.25, 1.75], [0.25, 1.75]),
        ("reverse", [0.25, 1.75], [-0.25, -1.75]),
        ("bounce", [0.25, 1.0, 1.25, 2.0, 2.5, -0.5], [0.25, 1.0, 0.75, 0.0, 0.5, 0.5]),
    ],
)
def test_base_phase_by_direction(
    direction: Any, positions: list[float], phases: list[float]
) -> None:
    assert [base_phase(direction, p) for p in positions] == phases


def test_reverse_runs_the_saw_backwards() -> None:
    _, (effects,) = compile_cues([instance("e", "t-saw", targets("fx-mh1"), direction="reverse")])
    fx = bank()
    fx.retarget(0.0, effects, STEP, SeqRule.all(1))
    fx.update(0.25, EffectScalars())
    assert fx.runtimes["e"].source.htpValues.tolist() == [0.75]


# --------------------------------------------------------------- transitions


def test_enter_fades_in_with_size_fade_in_else_the_in_timing() -> None:
    _, (effects,) = compile_cues(
        [instance("a", "t-saw", sizeFadeIn=2.0), instance("b", "t-circle")]
    )
    fx = bank()
    timing = EffectTiming(change=Timing(duration=4.0, delay=1.0), leave=Timing())
    assert fx.retarget(10.0, effects, timing, SeqRule.all(1)) == 15.0
    fx.update(11.0, EffectScalars())
    assert fx.runtimes["a"].source.htpWeight == 0.5  # sizeFadeIn: linear, no delay
    assert fx.runtimes["b"].relatives[0].weight == 0.0  # still in its delay
    fx.update(13.0, EffectScalars())
    assert fx.runtimes["b"].relatives[0].weight == 0.5


def test_the_cue_timing_of_an_effect_transition() -> None:
    doc_cue = cue("c", fade_in=3.0, delay_in=1.0, fade_out=2.0, delay_out=0.5, curve="easeIn")
    timing = EffectTiming.of_cue(compile_cue_of(doc_cue))
    assert (timing.change.duration, timing.change.delay) == (3.0, 1.0)
    assert (timing.leave.duration, timing.leave.delay) == (2.0, 0.5)
    assert timing.change.curve is timing.leave.curve
    assert timing_of(compile_cue_of(cue("d")).inTiming) == Timing()


def compile_cue_of(doc_cue: Doc) -> Any:
    doc = busk_rig(1)
    doc["cueLists"] = [cue_list("cl", 1, doc_cue)]
    return compile_doc(doc).cueLists["cl"].cues[0]


def test_leave_fades_out_with_the_out_timing_while_still_moving() -> None:
    _, (effects,) = compile_cues([instance("e", "t-saw", targets("fx-mh1"))])
    fx = bank()
    fx.retarget(0.0, effects, STEP, SeqRule.all(1))
    leave = EffectTiming(change=Timing(), leave=Timing(duration=2.0))
    assert fx.retarget(1.0, (), leave, SeqRule.fresh(2)) == 3.0
    fx.update(1.5, EffectScalars())
    source = fx.runtimes["e"].source
    assert (source.htpValues.tolist(), source.htpWeight) == ([0.5], 0.75)
    fx.update(2.25, EffectScalars())
    assert (source.htpValues.tolist(), source.htpWeight) == ([0.25], 0.375)
    assert fx.runtimes["e"].seq == 1  # leaving keeps its number
    fx.update(3.0, EffectScalars())
    assert not fx.active  # faded out: the runtime and its clock are gone


def test_a_change_crossfades_on_the_same_clock() -> None:
    _, (small, large) = compile_cues(
        [instance("c", "t-circle", targets("fx-mh1"), size=10.0)],
        [instance("c", "t-circle", targets("fx-mh1"), size=20.0)],
    )
    fx = bank()
    fx.retarget(0.0, small, STEP, SeqRule.all(1))
    clock = fx.runtimes["c"].clock
    change = EffectTiming(change=Timing(duration=1.0), leave=Timing())
    assert fx.retarget(0.5, large, change, SeqRule.fresh(2)) == 1.5
    rt = fx.runtimes["c"]
    assert rt.clock is clock
    assert len(rt.versions) == 2
    fx.update(0.875, EffectScalars())  # P = 0.875, f = 0.375
    tilt = rt.relatives[1]
    crest = 2 * (0.5 - 0.5 * math.cos(2 * math.pi * (0.875 + 0.25))) - 1
    assert tilt.amounts.tolist() == pytest.approx([(10 + 10 * 0.375) * crest])  # an exact morph
    assert tilt.weights is not None
    assert tilt.weights.tolist() == pytest.approx([1.0])
    fx.update(1.5, EffectScalars())  # the old version is gone: the steady state again
    assert len(rt.versions) == 1
    assert rt.relatives[1].weights is None


def test_a_change_of_rate_follows_the_new_version_without_a_jump() -> None:
    _, (slow, fast) = compile_cues(
        [instance("e", "t-saw", targets("fx-mh1"))],
        [instance("e", "t-saw", targets("fx-mh1"), rate={"kind": "hz", "value": 2.0})],
    )
    fx = bank()
    fx.retarget(0.0, slow, STEP, SeqRule.all(1))
    fx.retarget(0.25, fast, EffectTiming.uniform(Timing(duration=1.0)), SeqRule.fresh(2))
    clock = fx.runtimes["e"].clock
    assert (clock.rate, clock.position(0.25), clock.position(0.5)) == (2.0, 0.25, 0.75)


def test_a_leaving_instance_that_returns_fades_back_in_on_its_clock() -> None:
    _, (effects,) = compile_cues([instance("e", "t-saw", targets("fx-mh1"))])
    fx = bank()
    fade = EffectTiming.uniform(Timing(duration=2.0))
    fx.retarget(0.0, effects, STEP, SeqRule.all(1))
    clock = fx.runtimes["e"].clock
    fx.retarget(1.0, (), fade, SeqRule.fresh(2))  # leaving: presence 1 → 0 over 2 s
    assert fx.retarget(2.0, effects, fade, SeqRule.fresh(3)) == 4.0  # back from 0.5
    rt = fx.runtimes["e"]
    assert (rt.clock, rt.seq, len(rt.versions)) == (clock, 3, 1)
    fx.update(3.0, EffectScalars())
    assert rt.source.htpWeight == 0.75


def test_an_unchanged_instance_keeps_its_fades() -> None:
    _, (effects, again) = compile_cues(
        [instance("e", "t-saw", targets("fx-mh1"))], [instance("e", "t-saw", targets("fx-mh1"))]
    )
    assert effects[0] is not again[0]
    assert effects[0].same(again[0])
    fx = bank()
    fx.retarget(0.0, effects, EffectTiming.uniform(Timing(duration=2.0)), SeqRule.all(1))
    assert fx.retarget(1.0, again, STEP, SeqRule.fresh(2)) == 1.0  # no fade started
    fx.update(1.0, EffectScalars())
    rt = fx.runtimes["e"]
    assert (rt.source.htpWeight, rt.seq, len(rt.versions)) == (0.5, 1, 1)


# ----------------------------------------------------------- sequence numbers


def seq_cues() -> tuple[tuple[CompiledEffect, ...], tuple[CompiledEffect, ...]]:
    """Cue 1: a, b, c. Cue 2: a unchanged, b changed, c gone, d new."""
    _, (one, two) = compile_cues(
        [instance("a", "t-saw"), instance("b", "t-circle"), instance("c", "t-pulse")],
        [instance("a", "t-saw"), instance("b", "t-circle", size=2.0), instance("d", "t-fade")],
    )
    return one, two


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        (SeqRule.all(9), {"c": 9, "a": 9, "b": 9, "d": 9}),
        (SeqRule.fresh(9), {"c": 5, "a": 5, "b": 9, "d": 9}),
        (SeqRule.keep(9), {"c": 5, "a": 5, "b": 5, "d": 9}),
        (SeqRule.mask(9, np.zeros(0, dtype=np.intp)), {"c": 5, "a": 9, "b": 5, "d": 9}),
    ],
)
def test_sequence_rules(rule: SeqRule, expected: dict[str, int]) -> None:
    one, two = seq_cues()
    fx = bank()
    fx.retarget(0.0, one, STEP, SeqRule.all(5))
    fade = EffectTiming.uniform(Timing(duration=1.0))
    fx.retarget(1.0, two, fade, rule, touched=frozenset({"a"}))
    assert {key: rt.seq for key, rt in fx.runtimes.items()} == expected
    assert list(fx.runtimes) == ["c", "a", "b", "d"]  # leaving first, then in cue order
    assert [rt.place for rt in fx.runtimes.values()] == [0, 1, 2, 3]


def test_relatives_are_ordered_by_place_then_layer() -> None:
    one, _ = seq_cues()
    fx = bank()
    fx.retarget(0.0, one, STEP, SeqRule.all(5))
    fx.update(0.0, EffectScalars())
    orders = [rel.order for rel in fx.relatives()]
    assert orders == sorted(orders)
    assert len(set(orders)) == 3
    assert {rel.seq for rel in fx.relatives()} == {5}
    assert {rel.priority for rel in fx.relatives()} == {50}


# --------------------------------------------------------- completion, scale


def test_completion_is_the_latest_fade_started() -> None:
    one, two = seq_cues()
    fx = bank()
    fx.retarget(0.0, one, STEP, SeqRule.all(1))
    timing = EffectTiming(change=Timing(duration=2.0, delay=1.0), leave=Timing(duration=5.0))
    assert fx.retarget(10.0, two, timing, SeqRule.fresh(2)) == 15.0  # c leaves over 5 s
    assert fx.retarget(11.0, two, timing, SeqRule.fresh(3)) == 11.0  # nothing new


def test_scale_folds_into_every_presence_and_fades_back() -> None:
    one, _ = seq_cues()
    fx = bank()
    fx.retarget(0.0, one, STEP, SeqRule.all(1))
    back = EffectTiming.uniform(Timing(duration=1.0))
    assert fx.retarget(5.0, one, back, SeqRule.all(2), scale=0.4) == 6.0
    fx.update(5.0, EffectScalars())
    assert fx.runtimes["a"].source.htpWeight == pytest.approx(0.4)
    fx.update(5.5, EffectScalars())
    assert fx.runtimes["a"].source.htpWeight == pytest.approx(0.7)
    assert fx.runtimes["b"].relatives[0].weight == pytest.approx(0.7)


# ------------------------------------------------------- steady state, remap


def test_one_version_has_no_per_lane_weights() -> None:
    one, two = seq_cues()
    fx = bank()
    fx.retarget(0.0, one, STEP, SeqRule.all(1))
    fx.update(0.0, EffectScalars())
    for rt in fx.runtimes.values():
        source = rt.source
        assert (source.htpWeights, source.ltpWeights, source.snapWeights) == (None, None, None)
        assert all(rel.weights is None for rel in rt.relatives)
    fx.retarget(1.0, two, EffectTiming.uniform(Timing(duration=1.0)), SeqRule.fresh(2))
    fx.update(1.5, EffectScalars())
    assert fx.runtimes["b"].relatives[0].weights is not None  # two versions mix
    assert fx.runtimes["a"].relatives == []
    assert fx.runtimes["a"].source.htpWeights is None


def test_remap_moves_every_version_and_drops_lost_members() -> None:
    compiled, (effects,) = compile_cues([instance("e", "t-fade")])
    fx = bank()
    fx.retarget(0.0, effects, STEP, SeqRule.all(1))
    lanes = compiled.slots.laneCount
    lane_map = np.arange(lanes, dtype=np.intp) + 1000
    mh1 = lane(compiled, "fx-mh1", "color")
    lane_map[mh1 : mh1 + 4] = -1  # mh1's colour slot is gone
    pos_map = np.arange(compiled.slots.intensityLanes.size, dtype=np.intp)
    fx.remap(lane_map, pos_map)
    fx.update(0.0, EffectScalars())
    mh2 = lane(compiled, "fx-mh2", "color") + 1000
    source = fx.runtimes["e"].source
    assert source.ltpLanes.tolist() == [mh2, mh2 + 1, mh2 + 2]
    assert source.snapLanes.tolist() == [mh2 + 3]
    fx.remap(np.full(lanes + 1000, -1, dtype=np.intp), pos_map)  # then every lane is
    assert not fx.active


def test_clear_and_locked_clocks() -> None:
    compiled, (effects,) = compile_cues(
        [instance("b", "t-saw", rate={"kind": "bpm", "masterId": "m-speed", "multiplier": 1.0})],
    )
    fx = bank(compiled)
    fx.retarget(0.0, effects, STEP, SeqRule.all(1))
    master = fx.speed["m-speed"]
    assert fx.locked(master) == [fx.runtimes["b"].clock]
    fx.clear()
    assert not fx.active
    assert fx.locked(master) == []


def test_rerate_follows_the_rate_fader() -> None:
    _, (effects,) = compile_cues([instance("e", "t-saw", targets("fx-mh1"))])
    fx = bank()
    fx.retarget(0.0, effects, STEP, SeqRule.all(1))
    fx.rerate(0.5, 1.0)  # ×4 from position 0.5
    assert fx.rateLevel == 1.0
    assert fx.runtimes["e"].clock.position(0.75) == pytest.approx(1.5)
    fx.retarget(1.0, (), STEP, SeqRule.fresh(2))
    fx.retarget(1.0, effects, STEP, SeqRule.fresh(3))  # a new clock takes the fader too
    assert fx.runtimes["e"].clock.rate == 4.0


# ------------------------------------------------------------ the invariants


VARIANTS: list[list[Doc]] = [
    [],
    [instance("x", "t-saw", sizeMasterId="m-size")],
    [instance("x", "t-saw", low=0.2, high=0.6)],
    [instance("x", "t-circle", size=10.0), instance("y", "t-pulse", size=0.5)],
    [instance("x", "t-circle", size=20.0, rate={"kind": "hz", "value": 2.0})],
    [instance("y", "t-pulse", size=0.9), instance("z", "t-fade", direction="bounce")],
    [instance("z", "t-snap", sizeFadeIn=0.5), instance("x", "t-saw", direction="reverse")],
]
_, CUES = compile_cues(*VARIANTS)

event = st.tuples(
    st.floats(0.01, 2.0),  # time since the previous event
    st.integers(0, len(VARIANTS) - 1),  # the target cue
    st.floats(0.05, 1.5),  # change timing
    st.floats(0.0, 0.5),  # its delay
    st.floats(0.05, 1.5),  # leave timing
    st.sampled_from(["all", "fresh", "keep"]),
)


def run_events(events: list[Any], ticks: int) -> tuple[EffectBank, float]:
    """Apply ``events``, updating ``ticks`` times between each; returns the
    bank and the last event's time."""
    fx = bank()
    scalars = EffectScalars(sizeLevels={"m-size": 0.5})
    now = 0.0
    for k, (gap, target, change, delay, leave, rule) in enumerate(events):
        for i in range(1, ticks + 1):
            fx.update(now + gap * i / (ticks + 1), scalars)
        now += gap
        timing = EffectTiming(Timing(duration=change, delay=delay), Timing(duration=leave))
        fx.retarget(now, CUES[target], timing, getattr(SeqRule, rule)(k + 1))
    return fx, now


@settings(max_examples=150, deadline=None)
@given(events=st.lists(event, min_size=1, max_size=6), after=st.floats(0.0, 3.0))
def test_frames_are_a_pure_function_of_time_between_events(events: list[Any], after: float) -> None:
    scalars = EffectScalars(sizeLevels={"m-size": 0.5})
    ticked, now = run_events(events, ticks=5)
    alone, _ = run_events(events, ticks=0)
    for fx in (ticked, alone):
        fx.update(now + after, scalars)
    assert same_outputs(effective(ticked), effective(alone))


@settings(max_examples=150, deadline=None)
@given(events=st.lists(event, min_size=2, max_size=6))
def test_a_retarget_never_changes_an_output_at_its_own_time(events: list[Any]) -> None:
    scalars = EffectScalars(sizeLevels={"m-size": 0.5})
    fx, now = run_events(events[:-1], ticks=2)
    gap, target, change, delay, leave, rule = events[-1]
    now += gap
    fx.update(now, scalars)
    before = effective(fx)
    timing = EffectTiming(Timing(duration=change, delay=delay), Timing(duration=leave))
    fx.retarget(now, CUES[target], timing, getattr(SeqRule, rule)(99))
    fx.update(now, scalars)
    assert same_outputs(before, effective(fx))


@settings(max_examples=150, deadline=None)
@given(events=st.lists(event, min_size=1, max_size=6), after=st.floats(0.0, 3.0))
def test_values_stay_in_range_and_weights_in_0_1(events: list[Any], after: float) -> None:
    """Intensities, colours and multiply factors are all in 0..1 here, and
    stay there through every mix of versions."""
    fx, now = run_events(events, ticks=1)
    fx.update(now + after, EffectScalars(sizeLevels={"m-size": 0.5}))
    for (_, kind, _), (value, weight) in effective(fx).items():
        assert 0.0 <= weight <= 1.0 + 1e-12
        if kind == "snap":
            assert value is None  # derive
        elif kind != "add":
            assert value is not None
            assert -1e-12 <= value <= 1.0 + 1e-12


@settings(max_examples=100, deadline=None)
@given(
    old=st.floats(0.5, 30.0),
    new=st.floats(0.0, 30.0),
    duration=st.floats(0.1, 3.0),
    at=st.floats(0.0, 1.0),
)
def test_a_change_of_size_is_an_exact_morph(
    old: float, new: float, duration: float, at: float
) -> None:
    _, (before, after) = compile_cues(
        [instance("c", "t-circle", size=old)], [instance("c", "t-circle", size=new)]
    )
    fx, reference = bank(), bank()
    fx.retarget(0.0, before, STEP, SeqRule.all(1))
    fx.retarget(1.0, after, EffectTiming.uniform(Timing(duration=duration)), SeqRule.fresh(2))
    reference.retarget(0.0, before, STEP, SeqRule.all(1))
    t = 1.0 + at * duration
    fx.update(t, EffectScalars())
    reference.update(t, EffectScalars())
    f = at
    for rel, ref in zip(fx.runtimes["c"].relatives, reference.runtimes["c"].relatives, strict=True):
        unit = ref.amounts / old  # the wave at this phase, at size 1
        expected = (old + (new - old) * f) * unit  # lerp(old, new, f) at the same phase
        assert rel.amounts == pytest.approx(expected, abs=1e-9)
        assert (rel.weights if rel.weights is not None else np.ones(1)) == pytest.approx(1.0)


def test_a_change_fades_in_with_the_change_timing_not_size_fade_in() -> None:
    _, (one, two) = compile_cues(
        [instance("e", "t-saw", sizeFadeIn=4.0)], [instance("e", "t-saw", sizeFadeIn=4.0, high=0.5)]
    )
    fx = bank()
    fx.retarget(0.0, one, STEP, SeqRule.all(1))
    timing = EffectTiming.uniform(Timing(duration=1.0))
    assert fx.retarget(10.0, two, timing, SeqRule.fresh(2)) == 11.0
    old, new = fx.runtimes["e"].versions
    assert (old.presence.value(10.5), new.presence.value(10.5)) == (0.5, 0.5)


def test_scale_folds_into_leaving_instances_and_older_versions() -> None:
    one, two = seq_cues()
    fx = bank()
    fx.retarget(0.0, one, STEP, SeqRule.all(1))
    fx.retarget(1.0, two, EffectTiming.uniform(Timing(duration=2.0)), SeqRule.fresh(2))
    back = EffectTiming(change=Timing(duration=1.0), leave=Timing(duration=4.0))
    fx.retarget(2.0, two, back, SeqRule.all(3), scale=0.4)
    old, new = fx.runtimes["b"].versions
    assert old.presence.value(2.0) == pytest.approx(0.5 * 0.4)  # b's old version, half out
    assert new.presence.value(2.0) == pytest.approx(0.5 * 0.4)
    assert old.presence.value(2.5) == pytest.approx(0.1)  # on out over the change timing
    leaving = fx.runtimes["c"].newest.presence
    assert (leaving.value(2.0), leaving.value(4.0)) == pytest.approx((0.5 * 0.4, 0.1))


def test_mixed_weights_never_exceed_1() -> None:
    _, (one, two, three) = compile_cues(
        [instance("e", "t-fade", targets("fx-mh1"))],
        [instance("e", "t-snap", targets("fx-mh1"))],
        [instance("e", "t-fade", targets("fx-mh1"), direction="reverse")],
    )
    fx = bank()
    fx.retarget(0.0, one, STEP, SeqRule.all(1))
    fx.retarget(1.0, two, EffectTiming.uniform(Timing(duration=10.0)), SeqRule.fresh(2))
    fx.retarget(1.0, three, STEP, SeqRule.fresh(3))  # the first is still nearly all there
    fx.update(1.0, EffectScalars())
    source = fx.runtimes["e"].source
    assert source.ltpWeights is not None
    assert source.snapWeights is not None
    assert source.ltpWeights.tolist() == [1.0, 1.0, 1.0]
    assert source.snapWeights.tolist() == [1.0]


def test_a_phase_that_rounds_up_to_1_wraps_to_the_first_colour() -> None:
    _, (effects,) = compile_cues([instance("e", "t-fade", targets("fx-mh1"), direction="reverse")])
    fx = bank()
    fx.retarget(0.0, effects, STEP, SeqRule.all(1))
    fx.update(1e-18, EffectScalars())  # b = −1e-18: p = b − floor(b) rounds to 1.0
    assert fx.runtimes["e"].source.ltpValues.tolist() == [1.0, 0.0, 0.0]
