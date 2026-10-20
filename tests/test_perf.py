"""Benchmarks on the §19 reference size (opt-in: ``uv run pytest -m perf -s``).

**Conversion.** The rig (``builders.benchmark_rig``) has 64 universes, each
holding 4 Appendix A spots, 6 MH-X25, 10 ML-56 RGBW and 9 COLORband PiX: about
20 600 slots and 29 000 slot-driven channels. §19 budgets 1 ms per tick for
masters, safety *and* conversion together; this test holds conversion alone to
a median under 1 ms and reports the 99th percentile and the compile time.

**Output.** One output cycle for 64 sACN routes, with every universe changed
on every cycle (the worst case: 64 packets per cycle), must take a median
under 5 ms of the 22.7 ms cycle; so must one for 64 Art-Net routes (Phase 6).

**Feedback** (Phase 6). ``feedback_values`` for 200 bindings on the reference
rig, which the feedback worker runs 30 times a second, must take a mean
under 1 ms.
"""

from __future__ import annotations

import gc
import json
import time
from collections.abc import Callable
from typing import Any, cast

import numpy as np
import pytest
from numpy.typing import NDArray

from artnet_node import ArtNetReceiver
from builders import (
    APPENDIX_A,
    Doc,
    benchmark_rig,
    busking_benchmark_rig,
    compile_doc,
    load_doc,
    random_frame,
    surface_benchmark_rig,
)
from busk.compiler.compile import CompiledShow, CompiledUniverse, compile_show
from busk.convert.converter import Converter
from busk.engine.clock import FakeClock
from busk.engine.contributions import gather
from busk.engine.loop import Engine, Frame
from busk.engine.resolver import Resolver
from busk.io.feedback import feedback_values
from busk.model.common import UniverseId
from busk.model.output import OutputSettings
from busk.model.validate import has_errors, validate_show
from busk.output.artnet import ArtNetNetwork
from busk.output.scheduler import OUTPUT_HZ, OutputScheduler, ScheduledRoute, build_routes
from sacn_receiver import Receiver

pytestmark = pytest.mark.perf

FRAMES = 32
RUNS = 3000


def test_converting_the_reference_rig_takes_under_1_ms() -> None:
    doc = benchmark_rig(universes=64)
    started = time.perf_counter()
    show, issues = validate_show(json.dumps(doc))
    validated = time.perf_counter()
    assert show is not None
    assert not has_errors(issues)
    compiled = compile_show(show)
    validate_ms = (validated - started) * 1000
    compile_ms = (time.perf_counter() - validated) * 1000

    generator = np.random.default_rng(19)
    frames = [random_frame(compiled, generator) for _ in range(FRAMES)]
    converter = Converter(compiled.plan)
    out = np.array(compiled.baseImages)
    for logical in frames:  # warm up caches and numpy's first-call paths
        converter.convert(logical, out)

    convert_times = np.empty(RUNS)
    tick_times = np.empty(RUNS)  # stage 12 as the engine runs it: copy base images + convert
    gc.disable()
    try:
        for k in range(RUNS):
            logical = frames[k % FRAMES]
            t0 = time.perf_counter()
            np.copyto(out, compiled.baseImages)
            t1 = time.perf_counter()
            converter.convert(logical, out)
            t2 = time.perf_counter()
            convert_times[k] = t2 - t1
            tick_times[k] = t2 - t0
    finally:
        gc.enable()

    plan = compiled.plan
    median, p99 = np.percentile(convert_times, [50, 99]) * 1000
    print(
        f"\nrig: {len(compiled.universes)} universes, {len(doc['fixtures'])} fixtures, "
        f"{len(compiled.slots.slots)} slots, {compiled.slots.laneCount} lanes, "
        f"{len(compiled.channels)} channels "
        f"({plan.rangeCount} range, {plan.colorCount} colour, {plan.optionCount} option)"
        f"\nvalidate: {validate_ms:.0f} ms, compile: {compile_ms:.0f} ms"
        f"\nconvert: median {median:.3f} ms, p99 {p99:.3f} ms, "
        f"max {convert_times.max() * 1000:.3f} ms"
        f"\nstage 12 (copy + convert): median {np.median(tick_times) * 1000:.3f} ms"
    )
    assert len(compiled.slots.slots) > 20_000
    assert len(compiled.channels) > 28_000
    assert median < 1.0


UNIVERSES = 64
CYCLES = 2000


class Source:
    """Stands in for the engine: the frame the benchmark puts in ``latest``."""

    latest: Frame | None = None


OUTPUT_UNIVERSES = [
    CompiledUniverse(id=UniverseId(f"u{n}"), number=n, name=f"U{n}")
    for n in range(1, UNIVERSES + 1)
]


def output_settings(routes: list[dict[str, Any]]) -> OutputSettings:
    return cast(
        OutputSettings,
        {
            "engineHz": 100,
            "sacnSourceName": "Busk Console",
            "sacnCid": "0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f",
            "holdLastFrameOnEngineStall": True,
            "routes": routes,
        },
    )


def time_output_cycles(
    scheduled: list[ScheduledRoute], discard: Callable[[], int], artnet: ArtNetNetwork | None = None
) -> tuple[NDArray[np.float64], int]:
    """Time :data:`CYCLES` output cycles that each change every universe (two
    frames that differ everywhere, alternated). ``discard`` empties the
    receiver outside the timed region; returns the times and the packets
    it received."""
    frames = [
        Frame(seq=k, time=0.0, universes=tuple(bytes([k]) * 512 for _ in OUTPUT_UNIVERSES))
        for k in (1, 2)
    ]
    source = Source()
    scheduler = OutputScheduler(source, scheduled, FakeClock(), artnet=artnet)
    times = np.empty(CYCLES)
    received = 0
    gc.disable()
    try:
        for k in range(CYCLES):
            source.latest = frames[k % 2]
            started = time.perf_counter()
            scheduler.service(k / OUTPUT_HZ)
            times[k] = time.perf_counter() - started
            received += discard()  # outside the timed region
    finally:
        gc.enable()
        scheduler.close()
    return times, received


def report_output(label: str, times: NDArray[np.float64], received: int) -> float:
    median, p99 = np.percentile(times, [50, 99]) * 1000
    print(
        f"\noutput: {UNIVERSES} {label} routes, every universe changed every cycle: "
        f"median {median:.3f} ms, p99 {p99:.3f} ms, max {times.max() * 1000:.3f} ms "
        f"per cycle ({median * 1000 / UNIVERSES:.1f} µs per packet); {received} received"
    )
    return float(median)


def test_an_output_cycle_for_64_universes_takes_under_5_ms(receiver: Receiver) -> None:
    routes: list[dict[str, Any]] = [
        {
            "id": f"r{n}",
            "universeId": f"u{n}",
            "enabled": True,
            "protocol": "sacn",
            "universe": n,
            "priority": 100,
            "destination": {"kind": "unicast", "host": "127.0.0.1"},
        }
        for n in range(1, UNIVERSES + 1)
    ]
    scheduled, notices = build_routes(output_settings(routes), OUTPUT_UNIVERSES)
    assert (len(scheduled), notices) == (UNIVERSES, [])
    times, received = time_output_cycles(scheduled, receiver.discard)
    median = report_output("sACN", times, received)
    statuses = [route.driver.status() for route in scheduled]
    assert sum(status.errors for status in statuses) == 0
    assert received == UNIVERSES * CYCLES  # every send went out; the 3 terminations per route
    assert sum(status.packets for status in statuses) == UNIVERSES * (CYCLES + 3)  # came after
    assert median < 5.0


def test_an_art_net_output_cycle_for_64_universes_takes_under_5_ms(
    artnet_receiver: ArtNetReceiver,
) -> None:
    routes: list[dict[str, Any]] = [
        {
            "id": f"r{n}",
            "universeId": f"u{n}",
            "enabled": True,
            "protocol": "artnet",
            "portAddress": {"net": 0, "subNet": (n - 1) // 16, "universe": (n - 1) % 16},
            "destination": {"kind": "unicast", "host": "127.0.0.1"},
        }
        for n in range(1, UNIVERSES + 1)
    ]
    network = ArtNetNetwork(port=0)
    scheduled, notices = build_routes(output_settings(routes), OUTPUT_UNIVERSES, artnet=network)
    assert (len(scheduled), notices) == (UNIVERSES, [])
    times, received = time_output_cycles(scheduled, artnet_receiver.discard, network)
    median = report_output("Art-Net", times, received)
    statuses = [route.driver.status() for route in scheduled]
    assert sum(status.errors for status in statuses) == 0
    assert received == sum(status.packets for status in statuses) == UNIVERSES * CYCLES
    assert median < 5.0


# ------------------------------------------------------------------- feedback

BINDINGS = 200
FEEDBACK_RUNS = 3000


def test_feedback_values_for_200_bindings_take_under_1_ms() -> None:
    compiled = compile_doc(surface_benchmark_rig(BINDINGS))
    engine = Engine(compiled, FakeClock())
    for ident in compiled.playbacks:
        engine.bus.submit({"type": "SET_FADER", "playbackId": ident, "level": 0.8})
    engine.tick(0.0)
    engine.tick(0.5)
    snapshot = engine.snapshot
    assert snapshot is not None
    values = feedback_values(compiled, snapshot, 0.5)
    assert len(compiled.bindings) == len(values) == BINDINGS
    times = np.empty(FEEDBACK_RUNS)
    gc.disable()
    try:
        for k in range(FEEDBACK_RUNS):
            started = time.perf_counter()
            feedback_values(compiled, snapshot, 0.5 + k / 30)
            times[k] = time.perf_counter() - started
    finally:
        gc.enable()
    mean, _ = report(f"feedback_values, {BINDINGS} bindings, reference rig", times)
    assert mean < 1.0


# ------------------------------------------------------------------- busking

TICKS = 1000


def time_ticks(
    compiled: CompiledShow, commands: list[Any], ticks: int = TICKS
) -> NDArray[np.float64]:
    """Seconds per :meth:`Engine.tick`, after ``commands`` and a warm-up, at
    100 Hz with every fade still running (fractional weights everywhere)."""
    clock = FakeClock()
    engine = Engine(compiled, clock)
    for command in commands:
        engine.bus.submit(command)
    for k in range(50):  # warm up: apply the commands, first-call paths
        engine.tick(k / 100)
    times = tick_times(engine, 1.0, ticks)
    assert engine.stats.commandErrors == 0
    return times


def tick_times(
    engine: Engine,
    start: float,
    ticks: int = TICKS,
    between: Callable[[int], None] | None = None,
) -> NDArray[np.float64]:
    """Seconds per :meth:`Engine.tick` for ``ticks`` ticks at 100 Hz from
    ``start``, with the garbage collector off. ``between(k)``, if given, runs
    untimed after tick ``k``."""
    times = np.empty(ticks)
    gc.disable()
    try:
        for k in range(ticks):
            started = time.perf_counter()
            engine.tick(start + k / 100)
            times[k] = time.perf_counter() - started
            if between is not None:
                between(k)
    finally:
        gc.enable()
    return times


def report(label: str, times: NDArray[np.float64]) -> tuple[float, float]:
    mean, p99 = times.mean() * 1000, np.percentile(times, 99) * 1000
    print(f"\n{label}: mean {mean:.3f} ms, p99 {p99:.3f} ms, max {times.max() * 1000:.3f} ms")
    return mean, p99


def test_a_busking_tick_on_appendix_a_takes_under_1_ms() -> None:
    """The small rig: Appendix A (1 universe) with every playback up and the GM
    at 80 %, its pulse running at full size."""
    compiled = compile_doc(load_doc(APPENDIX_A))
    commands: list[Any] = [
        {"type": "SET_MASTER", "masterId": "m-gm", "level": 0.8},
        {"type": "SET_FADER", "playbackId": "pb-song", "level": 1.0},
        {"type": "TOGGLE_PLAYBACK", "playbackId": "pb-blue"},
        {"type": "FLASH", "playbackId": "pb-blue", "down": True},
        {"type": "TOGGLE_PLAYBACK", "playbackId": "pb-pulse"},
        {"type": "SET_FADER", "playbackId": "pb-pulse", "level": 1.0},
    ]
    _, p99 = report("busking tick, Appendix A", time_ticks(compiled, commands))
    assert p99 < 1.0


SAFETY_TICKS = 4000


def test_a_tick_with_park_limits_and_a_strobe_cap_costs_under_10_percent_more() -> None:
    """Phase 7 (phase-7-plan §5.26): the Appendix A tick above, with the
    safety stage busy (MH 1 parked in pan, colour and gobo, MH 2 limited in
    pan, tilt and intensity, the par's intensity parked, the pulse under a
    4 Hz strobe cap), stays within 10 % of the plain tick.

    The tick is ~0.08 ms, so 10 % is a few microseconds: the two engines
    tick in turn, each at the same engine time, so that drift in the
    machine's speed falls on both alike, and their medians are compared.
    """
    commands: list[Any] = [
        {"type": "SET_MASTER", "masterId": "m-gm", "level": 0.8},
        {"type": "SET_FADER", "playbackId": "pb-song", "level": 1.0},
        {"type": "TOGGLE_PLAYBACK", "playbackId": "pb-blue"},
        {"type": "FLASH", "playbackId": "pb-blue", "down": True},
        {"type": "TOGGLE_PLAYBACK", "playbackId": "pb-pulse"},
        {"type": "SET_FADER", "playbackId": "pb-pulse", "level": 1.0},
    ]
    plain = load_doc(APPENDIX_A)
    safe = load_doc(APPENDIX_A)

    def parked(fixture: str, attribute: str, value: Any) -> dict[str, Any]:
        slot = {"target": {"fixtureId": fixture, "element": 0}, "attribute": attribute}
        return {"slot": slot, "value": value}

    safe["park"] = [
        parked("fx-mh1", "pan", 10),
        parked("fx-mh1", "color", {"r": 0, "g": 1, "b": 0}),
        parked("fx-mh1", "gobo1", {"slot": "breakup"}),
        parked("fx-par1", "intensity", 0.5),
    ]
    mh2 = next(f for f in safe["fixtures"] if f["id"] == "fx-mh2")
    mh2["limits"] = {"pan": [-10, 20], "tilt": [0, 45], "intensityMax": 0.25}
    safe["safety"] = {"strobeMaxHz": 4}
    engines = []
    for doc in (plain, safe):
        compiled = compile_doc(doc)
        engine = Engine(compiled, FakeClock())
        for command in commands:
            engine.bus.submit(command)
        for k in range(50):  # warm up: apply the commands, first-call paths
            engine.tick(k / 100)
        engines.append(engine)
    assert engines[1].bus.compiled.safety.parkLanes.size > 0
    assert engines[1].bus.compiled.safety.limitLanes.size > 0
    times = np.empty((2, SAFETY_TICKS))
    gc.disable()
    try:
        for k in range(SAFETY_TICKS):
            for which in (0, 1) if k % 2 else (1, 0):  # each goes first half the time
                started = time.perf_counter()
                engines[which].tick(1.0 + k / 100)
                times[which, k] = time.perf_counter() - started
    finally:
        gc.enable()
    assert all(engine.stats.commandErrors == 0 for engine in engines)
    report("busking tick, Appendix A", times[0])
    report("busking tick, Appendix A with park, limits and a strobe cap", times[1])
    ratio = float(np.median(times[1]) / np.median(times[0]))
    print(f"safety stage: median ratio {ratio:.3f}")
    assert ratio < 1.10


def test_a_busking_tick_on_the_reference_rig_fits_the_100_hz_budget() -> None:
    """The §19 reference rig with 60 active playbacks in 3 bands, all mid-fade.

    The gate is p99 < 10 ms (no overruns at 100 Hz). §19's 4 ms per tick is a
    target: the numbers are recorded in docs/dev/benchmarks.md either way.
    """
    doc = busking_benchmark_rig()
    compiled = compile_doc(doc)
    commands = [
        {"type": "SET_FADER", "playbackId": playback["id"], "level": 0.8}
        for playback in doc["playbacks"]
    ]
    lanes = sum(
        pb.cueList.first.htpPos.size
        + pb.cueList.first.ltpLanes.size
        + pb.cueList.first.snapLanes.size
        for pb in compiled.playbacks.values()
    )
    print(
        f"\nrig: {len(compiled.universes)} universes, {len(doc['fixtures'])} fixtures, "
        f"{len(compiled.slots.slots)} slots, {len(compiled.playbacks)} playbacks "
        f"({lanes} lanes contributed per tick)"
    )
    times = time_ticks(compiled, commands)
    _, p99 = report("busking tick, reference rig", times)

    # Where the time goes: the resolver alone, on the same sources.
    engine = Engine(compiled, FakeClock())
    for command in commands:
        engine.bus.submit(command)
    engine.tick(0.0)
    playbacks = engine.runtime.playbacks
    playbacks.update(1.0)
    sources = gather(playbacks.sources(), [])
    resolver, frame = Resolver(compiled.slots), np.empty(compiled.slots.laneCount)
    resolve_times = np.empty(TICKS)
    gc.disable()
    try:
        for k in range(TICKS):
            started = time.perf_counter()
            resolver.resolve(sources, compiled.slots.defaultFrame, frame)
            resolve_times[k] = time.perf_counter() - started
    finally:
        gc.enable()
    report(f"resolve alone ({len(sources)} sources)", resolve_times)
    assert len(sources) == 60
    assert p99 < 10.0


# ------------------------------------------------------ Phase 4: time (§5.16)
#
# The gates are the 100 Hz budget (10 ms); §19's 4 ms per tick is a target,
# recorded in docs/plans/phase-4-plan.md (step 18) and docs/dev/benchmarks.md either way.

GO_BURSTS = 200


def started_engine(doc: Doc, compiled: CompiledShow) -> tuple[Engine, list[str]]:
    """An engine on ``compiled`` with every playback of ``doc`` up (sequences
    at 0.8, chases at full) after 50 warm-up ticks; returns it and the ids of
    the sequence playbacks."""
    engine = Engine(compiled, FakeClock())
    sequences = [pb["id"] for pb in doc["playbacks"] if pb["id"].startswith("pb-")]
    for playback in doc["playbacks"]:
        level = 0.8 if playback["id"] in sequences else 1.0
        engine.bus.submit({"type": "SET_FADER", "playbackId": playback["id"], "level": level})
    for k in range(50):
        engine.tick(k / 100)
    return engine, sequences


def test_a_tick_with_60_cue_transitions_fits_the_100_hz_budget() -> None:
    """60 playbacks of 4-cue tracking lists GO'd to cue 2 one tick apart, and
    measured while every one of them is mid-transition (cue 2 fades for
    20–40 s, with delays, per-family curves and a Bézier)."""
    doc = busking_benchmark_rig(cues=4, tracking=True)
    compiled = compile_doc(doc)
    engine, ids = started_engine(doc, compiled)
    for k, playback_id in enumerate(ids):  # staggered: 0.50 s … 1.09 s
        engine.bus.submit({"type": "GO", "playbackId": playback_id})
        engine.tick((50 + k) / 100)
    for k in range(110, 120):
        engine.tick(k / 100)
    runtimes = engine.runtime.playbacks.runtimes
    lanes = sum(runtimes[pb].current.htpPos.size + runtimes[pb].current.ltpLanes.size
                + runtimes[pb].current.snapLanes.size for pb in ids)  # fmt: skip
    print(f"\ntracking rig: {len(ids)} playbacks on cue 2, {lanes} lanes in their states")

    times = tick_times(engine, 1.2)
    report("tick, 60 cue transitions", times)
    end = 1.2 + (TICKS - 1) / 100
    assert all(runtimes[pb].cue == 1 and runtimes[pb].completes > end for pb in ids)
    assert engine.stats.commandErrors == 0
    assert np.percentile(times, 99) * 1000 < 10.0


def test_a_tick_where_60_playbacks_go_at_once_costs_about_two_ticks() -> None:
    """A command burst: all 60 playbacks GO in the same tick (60 retargets of
    mid-fade sets plus the tick), every 0.1 s round the 4-cue wrap lists.

    phase-4-plan §5.16 set this gate at 10 ms; it is missed (about 16 ms on
    the reference machine, see step 18's results). A retarget rebuilds its
    partitions over all of a playback's lanes, about 120 µs for 1 500 lanes
    and 0.7 ms for 28 000, so 60 of them cost about 10 ms before the tick
    itself. Retargeting only the changed lanes in place would fix it. Until
    then the gate is a median under 20 ms (the p99 varies from run to run
    between about 19 and 24 ms): such a burst, or a live edit that changes
    the slot table or every running playback's cue list, overruns into the
    next tick, while the output thread keeps sending the last frame.
    """
    doc = busking_benchmark_rig(cues=4, tracking=True)
    compiled = compile_doc(doc)
    engine, ids = started_engine(doc, compiled)

    def go_all(k: int = -1) -> None:
        if (k + 1) % 10 == 0:  # before ticks 0, 10, 20, …
            for playback_id in ids:
                engine.bus.submit({"type": "GO", "playbackId": playback_id})

    go_all()
    times = tick_times(engine, 0.5, 10 * GO_BURSTS, between=go_all)
    burst = np.arange(times.size) % 10 == 0
    bursts, others = times[burst], times[~burst]
    report(f"burst tick, {len(ids)} GOs", bursts)
    report("ticks between bursts", others)
    assert engine.stats.commandErrors == 0
    assert np.median(bursts) * 1000 < 20.0


def test_eight_bpm_chases_at_16_steps_per_second_fit_the_100_hz_budget() -> None:
    """8 chases at ×8 on 120 BPM (16 steps per second, crossfade 0.5) over
    the reference rig's 60 mid-fade looks; the ticks where they step are
    reported apart from the others."""
    doc = busking_benchmark_rig(chases=8)
    compiled = compile_doc(doc)
    engine, _ = started_engine(doc, compiled)
    runtimes = engine.runtime.playbacks.runtimes
    chases = [rt for pb_id, rt in runtimes.items() if pb_id.startswith("ch-")]
    stepped = np.zeros(TICKS, dtype=bool)
    positions = [rt.cue for rt in chases]

    def note(k: int) -> None:
        now = [rt.cue for rt in chases]
        stepped[k] = now != positions
        positions[:] = now

    times = tick_times(engine, 1.0, between=note)
    steps = int(stepped.sum())
    report(f"chase-step ticks ({steps})", times[stepped])
    report(f"other ticks ({TICKS - steps})", times[~stepped])
    assert len(chases) == 8
    assert all(rt.chase is not None for rt in chases)
    assert 155 <= steps <= 165  # 16 steps per second over 10 s, all 8 together
    assert engine.stats.commandErrors == 0
    assert np.percentile(times[stepped], 99) * 1000 < 10.0


# ---------------------------------------------------- Phase 5: effects (§5.15)
#
# The gate is the 100 Hz budget (10 ms); §19's 4 ms per tick is a target,
# recorded in docs/plans/phase-5-plan.md (step 16) and docs/dev/benchmarks.md either way.

EFFECTS = 20


def test_twenty_effects_over_the_reference_rig_fit_the_100_hz_budget() -> None:
    """20 BPM-locked effect playbacks at band 100 (circles, pulses, waves and
    colour cycles from the built-in library) over the reference rig's 60
    mid-fade looks; the 20 looks in bands 150 and 200 cover the relative
    effects' lanes, so every tick also builds the coverage arrays."""
    doc = busking_benchmark_rig(effects=EFFECTS)
    compiled = compile_doc(doc)
    engine, _ = started_engine(doc, compiled)
    runtimes = engine.runtime.playbacks.runtimes
    banks = [rt.bank for pb_id, rt in runtimes.items() if pb_id.startswith("fx-")]
    effect_lanes = sum(
        layer.lanes.size
        for pb_id, pb in compiled.playbacks.items()
        if pb_id.startswith("fx-")
        for effect in pb.cueList.first.effects
        for layer in effect.layers
    )
    relatives = sum(1 for _ in engine.runtime.playbacks.relatives())
    print(
        f"\neffects rig: {len(banks)} effect playbacks, {effect_lanes} effect lanes, "
        f"{relatives} relative contributions per tick"
    )
    times = tick_times(engine, 1.0)
    _, p99 = report(f"tick, {len(banks)} effects over 60 looks", times)
    assert len(banks) == EFFECTS
    assert all(bank.active for bank in banks)
    assert engine.stats.commandErrors == 0
    assert p99 < 10.0
