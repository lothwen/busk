"""The strobe-rate cap (phase-7-plan decision 13, §5.11, step 4).

``safety.strobeMaxHz`` caps how fast intensity may flash. Effects with an
intensity layer run no faster than the cap allows, counted in flashes per
second: an Hz effect is clamped, a BPM effect halves its cycles per beat
until it is under the cap (staying on the beat grid, and re-rated without a
jump when the tempo or the step changes). ``strobeRate`` lanes are clamped
in the safety stage. Without ``safety`` nothing is capped.

Appendix A's speed master starts at 120 BPM on its 1× step (level 0.5);
``beats(t) = 2t`` until the first event.
"""

from __future__ import annotations

import copy
import math
from typing import Any

import numpy as np
import pytest

from builders import APPENDIX_A, Doc, load_doc
from busk.compiler.effects import CompiledLayer, compile_wave
from busk.engine.effects import EffectClock, flashes_per_cycle
from session_harness import Live, put, sel, trigger

CAP = 1.5
STEPS = {  # two rises per cycle
    "id": "ef-steps",
    "name": "Steps",
    "layers": [{"attribute": "intensity", "mode": "absolute", "phaseOffset": 0,
                "waveform": {"kind": "step", "steps": [0, 1, 0, 1]}}],
}  # fmt: skip
THIRDS = [[0, 0], [1 / 6, 1], [2 / 6, 0], [3 / 6, 1], [4 / 6, 0], [5 / 6, 1]]
PEAKS = {  # three peaks per cycle
    "id": "ef-peaks",
    "name": "Peaks",
    "layers": [{"attribute": "intensity", "mode": "absolute", "phaseOffset": 0,
                "waveform": {"kind": "curve", "points": THIRDS}}],
}  # fmt: skip
SWEEP = {  # no intensity layer
    "id": "ef-sweep",
    "name": "Sweep",
    "layers": [{"attribute": "pan", "mode": "add", "phaseOffset": 0,
                "waveform": {"kind": "sine"}}],
}  # fmt: skip


def appendix(cap: float | None = CAP) -> Doc:
    """Appendix A with three more templates and, unless ``cap`` is None, a
    strobe cap."""
    doc = load_doc(APPENDIX_A)
    doc["effects"] += copy.deepcopy([STEPS, PEAKS, SWEEP])
    if cap is not None:
        doc["safety"] = {"strobeMaxHz": cap}
    return doc


def add_effect(template: str, rate: dict[str, Any]) -> dict[str, Any]:
    """ADD_EFFECT of ``template`` on the moving heads, as instance ``ei-x``."""
    instance = {
        "id": "ei-x",
        "templateId": template,
        "targets": {"kind": "group", "groupId": "g-mh"},
        "rate": rate,
        "direction": "forward",
        "size": 1,
        "phase": {"start": 0, "end": 0},
        "groups": 1,
        "blocks": 1,
        "wings": 1,
    }
    return {"type": "ADD_EFFECT", "effect": instance}


def hz(value: float) -> dict[str, Any]:
    return {"kind": "hz", "value": value}


def bpm(multiplier: float) -> dict[str, Any]:
    return {"kind": "bpm", "masterId": "m-speed", "multiplier": multiplier}


def programmer_clock(live: Live) -> EffectClock:
    return live.engine._programmer.bank.runtimes["ei-x"].clock


def running(template: str, rate: dict[str, Any], cap: float | None = CAP) -> Live:
    live = Live(appendix(cap))
    live.do(add_effect(template, rate))
    live.tick()
    return live


# ------------------------------------------------------- flashes per cycle


def layer(wave: dict[str, Any]) -> CompiledLayer:
    none = np.zeros(0, dtype=np.intp)
    return CompiledLayer(
        attribute="intensity",
        mode="absolute",
        htp=True,
        lanes=none,
        member=none,
        phase=np.zeros(0),
        wave=compile_wave(wave),  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("wave", "flashes"),
    [
        ({"kind": "sine"}, 1),
        ({"kind": "square", "duty": 0.1}, 1),
        ({"kind": "random", "seed": 3, "smooth": False}, 1),
        ({"kind": "step", "steps": [0, 1, 0, 1]}, 2),
        ({"kind": "step", "steps": [0, 0.5, 1]}, 2),  # each rise of the staircase
        ({"kind": "step", "steps": [1, 0]}, 1),  # the rise is at the cycle boundary
        ({"kind": "step", "steps": [0.5, 0.5]}, 0),  # constant: never flashes
        ({"kind": "curve", "points": THIRDS}, 3),
        ({"kind": "curve", "points": [[0, 0], [1, 1]]}, 1),  # a saw: one peak at the jump
        ({"kind": "curve", "points": [[0, 0], [0.5, 1], [1, 0]]}, 1),
        ({"kind": "curve", "points": [[0, 0], [0.2, 1], [0.4, 1], [0.6, 0]]}, 1),  # a plateau
        ({"kind": "curve", "points": [[0.2, 1], [0.7, 1]]}, 0),
    ],
)
def test_flashes_per_cycle(wave: dict[str, Any], flashes: int) -> None:
    assert flashes_per_cycle(layer(wave)) == flashes


# ------------------------------------------------------------------- Hz


@pytest.mark.parametrize(
    ("template", "rate"),
    [("ef-pulse", CAP), ("ef-steps", CAP / 2), ("ef-peaks", CAP / 3)],
)
def test_an_hz_effect_is_clamped_to_the_cap_in_flashes(template: str, rate: float) -> None:
    assert programmer_clock(running(template, hz(10))).rate == pytest.approx(rate)


def test_a_slow_hz_effect_is_not_touched() -> None:
    assert programmer_clock(running("ef-pulse", hz(1))).rate == 1.0


def test_an_effect_without_an_intensity_layer_is_not_capped() -> None:
    assert programmer_clock(running("ef-sweep", hz(10))).rate == 10.0


def test_nothing_is_capped_without_safety() -> None:
    assert programmer_clock(running("ef-pulse", hz(10), cap=None)).rate == 10.0
    assert programmer_clock(running("ef-pulse", bpm(4), cap=None)).rate == 4.0


# ------------------------------------------------------------------- BPM


def on_grid(clock: EffectClock, t: float) -> bool:
    """Whether the clock is exactly on its master's grid at ``t``."""
    assert clock.master is not None
    beats = clock.master.beats(t)
    g = min(clock.rate, 1.0)
    offset = (clock.position(t) - clock.rate * beats) / g
    return math.isclose(offset, round(offset), abs_tol=1e-9)


def event(live: Live, command: dict[str, Any], rate: float) -> None:
    """Apply ``command`` at the next tick: the position does not jump, the
    clock runs at ``rate`` cycles per beat, and one beat (plus a tick) later
    it is on the grid."""
    clock = programmer_clock(live)
    t = live.now + 0.01
    before = clock.position(t)
    live.do(command)
    live.tick(0.01)
    assert clock.position(t) == pytest.approx(before, abs=1e-12)
    assert clock.rate == pytest.approx(rate)
    assert clock.master is not None
    live.tick(60.0 / clock.master.bpm + 0.01)
    assert on_grid(clock, live.now)


def test_a_bpm_effect_halves_its_cycles_per_beat_under_the_cap() -> None:
    # 2 cycles per beat at 120 BPM is 4 flashes per second: halved twice to 1
    live = running("ef-pulse", bpm(2))
    clock = programmer_clock(live)
    assert clock.rate == 0.5
    assert on_grid(clock, live.now)


def test_bpm_halving_follows_set_bpm_taps_and_steps_without_a_jump() -> None:
    live = running("ef-pulse", bpm(2))
    live.tick(0.37)
    # 60 BPM: 2 cycles per beat is 2 flashes per second, halved once
    event(live, {"type": "SET_BPM", "masterId": "m-speed", "bpm": 60}, 1.0)
    # the first tap only moves the phase; the second sets 180 BPM: halved twice
    clock = programmer_clock(live)
    for _ in range(2):
        t = live.now + 1 / 3
        before = clock.position(t)
        live.do({"type": "TAP", "masterId": "m-speed"})
        live.tick(1 / 3)
        assert clock.position(t) == pytest.approx(before, abs=1e-12)
    assert clock.master is not None
    assert clock.master.bpm == pytest.approx(180)
    assert clock.rate == 0.5
    live.tick(1 / 3 + 0.01)
    assert on_grid(clock, live.now)
    # back to 60 BPM (rate 1), then the 0.25× step: 0.5 per beat, under the cap
    event(live, {"type": "SET_BPM", "masterId": "m-speed", "bpm": 60}, 1.0)
    event(live, {"type": "SET_MASTER", "masterId": "m-speed", "level": 0.0}, 0.5)
    # the 4× step: 8 per beat, halved three times
    event(live, {"type": "SET_MASTER", "masterId": "m-speed", "level": 1.0}, 1.0)


def test_a_playback_effect_is_capped_too() -> None:
    # Slow Pulse: 0.5 cycles per beat at 120 BPM is one flash per second
    live = Live(appendix(cap=0.5))
    live.do(trigger("pb-pulse"))
    live.tick()
    bank = live.engine.runtime.playbacks.runtimes["pb-pulse"].bank
    assert bank.runtimes["ei-1"].clock.rate == 0.25


# ------------------------------------------------------- live edits of the cap


def test_a_live_edit_of_the_cap_re_rates_running_effects() -> None:
    live = Live(appendix(cap=0.5))
    live.do(add_effect("ef-pulse", hz(10)), trigger("pb-pulse"))
    live.tick()
    clock = programmer_clock(live)
    chase = live.engine.runtime.playbacks.runtimes["pb-pulse"].bank.runtimes["ei-1"].clock
    assert (clock.rate, chase.rate) == (0.5, 0.25)

    live.do({"type": "SET", "path": ["safety"], "value": {"strobeMaxHz": 4}})
    t = live.now + 0.01
    before = clock.position(t), chase.position(t)
    live.tick(0.01)
    assert (clock.rate, chase.rate) == (4.0, 0.5)  # Slow Pulse is under 4 Hz
    assert (clock.position(t), chase.position(t)) == pytest.approx(before, abs=1e-12)

    live.do({"type": "SET", "path": ["safety"], "value": {}})
    live.tick()
    assert (clock.rate, chase.rate) == (10.0, 0.5)


# ------------------------------------------------------------ strobe lanes


def test_strobe_rate_lanes_are_clamped_to_the_cap() -> None:
    live = Live(appendix(cap=4))
    live.do(sel("fx-mh1"), put("shutter", {"slot": "strobe"}), put("strobeRate", 15))
    live.tick()
    assert live.lanes("fx-mh1", "strobeRate") == [4.0]
    live.do(put("strobeRate", 3))
    live.tick()
    assert live.lanes("fx-mh1", "strobeRate") == [3.0]


def test_strobe_rate_lanes_are_free_without_a_cap() -> None:
    live = Live(appendix(cap=None))
    live.do(sel("fx-mh1"), put("shutter", {"slot": "strobe"}), put("strobeRate", 15))
    live.tick()
    assert live.lanes("fx-mh1", "strobeRate") == [15.0]
