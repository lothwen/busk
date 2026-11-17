"""A layer's cycles (GAP-50 of ``docs/dev/tui/engine-gaps.md``; Phase 32 of
``docs/plans/tui-pending-plan.md``).

A scalar layer's ``cycles`` is how many of its waves it runs in one cycle of
the effect, a whole number from 1 to 100; left out, it is 1. Its
``phaseOffset`` is in degrees of its own wave, and the instance's phase spread
in degrees of the effect's cycle, so every member traces the same shape. The
strobe cap counts every wave, and the effect status shows them. The rig has
four moving heads (pan ±270°, tilt ±135°) and two dimmers; effects run at a
rate in Hz from engine time 0, so the clock's position is ``hz × t``.
"""

from __future__ import annotations

import json
import math
import time
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from builders import Doc, channel, fixture, grand_master, mode, profile, rng, show, show_of
from busk import LiveShow, OfflineShow, load_show
from busk.compiler.effects import CompiledLayer, compile_wave
from busk.engine.effect_status import WAVE_SAMPLES
from busk.engine.effects import flashes_per_cycle
from busk.engine.snapshot import FixtureOutput, OutputSnapshot
from busk.model.effect import MAX_CYCLES


def rig() -> Doc:
    """Heads 101 to 104 and dimmers 301 and 302, with a page and a grand master."""
    head = profile(
        "p-head",
        mode(
            [
                channel(0, "intensity"),
                channel(1, "pan", rng(0, 255, -270, 270)),
                channel(2, "tilt", rng(0, 255, -135, 135)),
            ]
        ),
    )
    dimmer = profile("p-dim", mode([channel(0, "intensity")]))
    heads = [fixture(f"f-h{k}", 100 + k, "p-head", 10 * k) for k in range(1, 5)]
    dimmers = [fixture(f"f-d{k}", 300 + k, "p-dim", 100 + k) for k in range(1, 3)]
    doc = show([head, dimmer], heads + dimmers)
    doc["pages"] = [{"id": "pg-1", "number": 1, "name": "Main", "slots": []}]
    doc["masters"] = [grand_master()]
    return doc


def layer(
    attribute: str, kind: str, mode_: str = "add", offset: float = 0, cycles: Any = None
) -> Doc:
    found: Doc = {
        "attribute": attribute,
        "waveform": {"kind": kind},
        "phaseOffset": offset,
        "mode": mode_,
    }
    if cycles is not None:
        found["cycles"] = cycles
    return found


def template_line(name: str, *layers: Doc) -> str:
    return f'effect template add "{name}" {json.dumps(list(layers))}'


def run(show_: OfflineShow | LiveShow, *lines: str) -> None:
    for line in lines:
        reply = show_.execute(line)
        assert reply.ok, f"{line}: {reply.text}"


def of(output: OutputSnapshot | None, number: int) -> FixtureOutput:
    assert output is not None
    return next(f for f in output.fixtures if f.number == number)


def frac(x: float) -> float:
    return x - math.floor(x)


def sine(p: float) -> float:
    return 0.5 - 0.5 * math.cos(2 * math.pi * p)


@pytest.fixture
def offline() -> OfflineShow:
    return OfflineShow(show_of(rig()))


def at(offline: OfflineShow, t: float, number: int) -> FixtureOutput:
    offline.tick(t)
    return of(offline.output, number)


# ------------------------------------------------------------ the waveform


@pytest.mark.parametrize("cycles", [None, 1, 2, 3])
def test_a_layer_runs_its_cycles_in_one_cycle_of_the_effect(
    offline: OfflineShow, cycles: int | None
) -> None:
    run(offline, template_line("Ramp", layer("intensity", "sawUp", "absolute", cycles=cycles)))
    run(offline, "sel fixture 301", 'effect add "Ramp" hz 0.5')
    n = cycles or 1
    for t in (0.1, 0.7, 1.3, 1.9, 3.3):
        assert at(offline, t, 301).intensity == pytest.approx(frac(n * 0.5 * t))


def test_a_sine_at_three_cycles(offline: OfflineShow) -> None:
    run(offline, template_line("Fast", layer("intensity", "sine", "absolute", cycles=3)))
    run(offline, "sel fixture 301", 'effect add "Fast" hz 0.25')
    for t in (0.2, 0.9, 1.7, 3.1):
        assert at(offline, t, 301).intensity == pytest.approx(sine(3 * 0.25 * t))


def test_the_phase_offset_is_in_degrees_of_the_layers_own_wave(offline: OfflineShow) -> None:
    """90° is a quarter of the layer's own wave: an eighth of the effect's
    cycle at ×2, not a quarter."""
    run(offline, template_line("Late", layer("intensity", "sawUp", "absolute", 90, cycles=2)))
    run(offline, "sel fixture 301", 'effect add "Late" hz 0.5')
    for t in (0.2, 0.6, 1.1):
        assert at(offline, t, 301).intensity == pytest.approx(frac(2 * 0.5 * t + 0.25))


def eight(offline: OfflineShow, spread: str) -> None:
    """Heads 101 to 104 at pan 0 tilt 0, with pan sine and tilt sine ×2
    +90° of size 20 on them, at 1 Hz."""
    pan, tilt = layer("pan", "sine"), layer("tilt", "sine", offset=90, cycles=2)
    run(offline, template_line("Eight", pan, tilt))
    run(offline, "sel fixture 101 thru 104", "set pan 0", "set tilt 0")
    run(offline, f'effect add "Eight" hz 1 size 20 phase {spread}')


def test_every_member_traces_the_same_shape_shifted_in_the_effects_cycle(
    offline: OfflineShow,
) -> None:
    """The spread is in degrees of the effect's cycle, so head 10k at ``t``
    is where head 101 is a k-th of a quarter cycle later: the same eight."""
    eight(offline, "0 360")
    seen: dict[tuple[int, float], tuple[float | None, float | None]] = {}
    times = [round(k / 16, 4) for k in range(48)]
    for t in times:
        offline.tick(t)
        for number in (101, 102, 103, 104):
            head = of(offline.output, number)
            seen[number, t] = (head.pan, head.tilt)
    for k, number in enumerate((102, 103, 104), start=1):
        for t in times[:32]:
            later = seen[101, round(t + k / 4, 4)]
            assert seen[number, t] == pytest.approx(later, abs=1e-9)


def test_pan_at_one_and_tilt_at_two_cycles_with_90_degrees_draw_an_eight(
    offline: OfflineShow,
) -> None:
    """busk's sine is ``-cos`` as an add layer: pan ``-cos θ`` and tilt
    ``-cos(2θ + 90°)``, which is ``sin 2θ``. Tilt is 0 at both ends of the pan
    sweep and at its middle, and its crests are on either side of the middle."""
    eight(offline, "0 0")
    for k in range(16):
        t = k / 16
        head = at(offline, t, 101)
        theta = 2 * math.pi * t
        assert head.pan == pytest.approx(-20 * math.cos(theta), abs=1e-9)
        assert head.tilt == pytest.approx(20 * math.sin(2 * theta), abs=1e-9)


@pytest.mark.parametrize(
    ("direction", "t", "phase"),
    [
        ("forward", 0.2, 0.2),
        ("reverse", 0.2, 0.8),  # b = -0.1, ×2 = -0.2
        ("bounce", 0.6, 0.6),  # b = 0.3 on the way up
        ("bounce", 2.6, 0.4),  # P = 1.3: b = 0.7 on the way down, ×2 = 1.4
    ],
)
def test_reverse_and_bounce_run_each_wave_back(
    offline: OfflineShow, direction: str, t: float, phase: float
) -> None:
    run(offline, template_line("Ramp", layer("intensity", "sawUp", "absolute", cycles=2)))
    run(offline, "sel fixture 301", f'effect add "Ramp" hz 0.5 {direction}')
    assert at(offline, t, 301).intensity == pytest.approx(phase)


def test_a_rate_change_keeps_the_layers_in_step(offline: OfflineShow) -> None:
    """Pan's ramp at ×1 and tilt's at ×2 share one clock: through a change
    of rate, tilt's phase stays twice pan's, and pan's goes on from where it
    was."""
    ramps = layer("pan", "sawUp"), layer("tilt", "sawUp", cycles=2)
    run(offline, template_line("Ramps", *ramps))
    run(offline, "sel fixture 101", "set pan 0", "set tilt 0")
    run(offline, 'effect add "Ramps" id fx hz 0.3 size 100')

    def phases(t: float) -> tuple[float, float]:
        head = at(offline, t, 101)
        assert head.pan is not None
        assert head.tilt is not None
        return (head.pan / 100 + 1) / 2, (head.tilt / 100 + 1) / 2  # size·(2w − 1)

    before, _ = phases(1.0)
    assert before == pytest.approx(0.3)
    run(offline, 'effect add "Ramps" id fx hz 1.1 size 100')  # the same instance, a new rate
    after, _ = phases(1.0)
    assert after == pytest.approx(before)
    for t in (1.2, 1.45, 1.9, 2.35):
        pan, tilt = phases(t)
        assert pan == pytest.approx(frac(0.3 + 1.1 * (t - 1.0)))
        assert tilt == pytest.approx(frac(2 * pan))


# ------------------------------------------------- what reads the effect


def compiled_layer(wave: dict[str, Any], cycles: int) -> CompiledLayer:
    none = np.zeros(0, dtype=np.intp)
    return CompiledLayer(
        attribute="intensity",
        mode="absolute",
        htp=True,
        lanes=none,
        member=none,
        phase=np.zeros(0),
        cycles=cycles,
        wave=compile_wave(wave),  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("wave", "cycles", "flashes"),
    [
        ({"kind": "square", "duty": 0.5}, 1, 1),
        ({"kind": "square", "duty": 0.5}, 3, 3),
        ({"kind": "step", "steps": [0, 1, 0, 1]}, 2, 4),
        ({"kind": "step", "steps": [0.5, 0.5]}, 5, 0),
    ],
)
def test_the_strobe_cap_counts_every_wave_of_a_layer(
    wave: dict[str, Any], cycles: int, flashes: int
) -> None:
    assert flashes_per_cycle(compiled_layer(wave, cycles)) == flashes


def test_a_layer_of_three_cycles_runs_at_a_third_of_the_cap(offline: OfflineShow) -> None:
    flash = {"attribute": "intensity", "waveform": {"kind": "square", "duty": 0.5},
             "phaseOffset": 0, "mode": "absolute", "cycles": 3}  # fmt: skip
    run(offline, "safety strobe 1.5", template_line("Strobe", flash))
    run(offline, "sel fixture 301", 'effect add "Strobe" hz 10')
    offline.tick(0.1)
    (effect,) = offline.effects.effects
    assert effect.hz == pytest.approx(0.5)


def test_the_effect_status_shows_each_wave_of_the_cycle(offline: OfflineShow) -> None:
    run(offline, template_line("Ramp", layer("intensity", "sawUp", "absolute", cycles=2)))
    run(offline, "sel fixture 301", 'effect add "Ramp" hz 0.8')
    start = 0.33
    offline.tick(start)
    (effect,) = offline.effects.effects
    seen = []
    for k in range(WAVE_SAMPLES):
        offline.tick(start + k / (WAVE_SAMPLES * 0.8))
        seen.append(of(offline.output, 301).intensity)
    assert effect.wave == pytest.approx(seen, abs=1e-9)
    drops = sum(1 for a, b in zip(effect.wave, effect.wave[1:], strict=False) if b < a)
    assert drops == 2  # two ramps in the effect's cycle


# --------------------------------------------------------- the show file


@pytest.mark.parametrize(
    ("cycles", "problem"),
    [
        (0, "Input should be greater than or equal to 1"),
        (-1, "Input should be greater than or equal to 1"),
        (MAX_CYCLES + 1, "Input should be less than or equal to 100"),
        (1.5, "Input should be a valid integer"),
        (2.0, "Input should be a valid integer"),
        ("2", "Input should be a valid integer"),
        (True, "Input should be a valid integer"),
    ],
)
def test_a_whole_number_from_1_to_100(offline: OfflineShow, cycles: Any, problem: str) -> None:
    reply = offline.execute(template_line("Bad", layer("tilt", "sine", cycles=cycles)))
    assert not reply.ok
    assert reply.text.splitlines()[1:] == [f"  effects[0].layers[0].cycles: {problem}"]


@pytest.mark.parametrize("cycles", [1, 2, MAX_CYCLES])
def test_every_whole_number_from_1_to_100_is_taken(offline: OfflineShow, cycles: int) -> None:
    run(offline, template_line("Good", layer("tilt", "sine", cycles=cycles)))


def test_list_effects_words_a_layers_cycles(offline: OfflineShow) -> None:
    run(
        offline,
        template_line("Eight", layer("pan", "sine"), layer("tilt", "sine", offset=90, cycles=2)),
        template_line("Once", layer("tilt", "sine", cycles=1)),
        template_line("Thrice", layer("intensity", "sawUp", "absolute", cycles=3)),
    )
    assert offline.execute("list effects").text.splitlines() == [
        "Eight                pan add sine, tilt add sine ×2 +90°",
        "Once                 tilt add sine",
        "Thrice               intensity absolute sawUp ×3",
    ]
    summaries = {t.name: t.summary for t in offline.effect_templates if t.source == "show"}
    assert summaries["Eight"] == "pan add sine, tilt add sine ×2 +90°"


def test_a_show_file_keeps_cycles_and_leaves_out_what_was_left_out(tmp_path: Path) -> None:
    offline = OfflineShow(show_of(rig()), path=tmp_path / "rig.show")
    run(
        offline,
        template_line("Eight", layer("pan", "sine"), layer("tilt", "sine", offset=90, cycles=2)),
        "save",
    )
    with zipfile.ZipFile(tmp_path / "rig.show") as archive:
        saved = json.loads(archive.read("show.json"))
    pan, tilt = saved["effects"][0]["layers"]
    assert "cycles" not in pan
    assert tilt["cycles"] == 2
    again = OfflineShow(load_show(tmp_path / "rig.show")[0])
    listed = again.execute("list effects").text
    assert listed == "Eight                pan add sine, tilt add sine ×2 +90°"


def test_an_update_and_its_undo_change_a_running_effect(offline: OfflineShow) -> None:
    once = layer("intensity", "sawUp", "absolute")
    run(offline, template_line("Ramp", once), "sel fixture 301", 'effect add "Ramp" hz 0.5')
    assert at(offline, 0.5, 301).intensity == pytest.approx(0.25)
    twice = json.dumps([once | {"cycles": 2}])
    run(offline, f'effect template update "Ramp" {twice}')
    assert at(offline, 0.6, 301).intensity == pytest.approx(0.6)
    run(offline, "undo")
    assert at(offline, 0.7, 301).intensity == pytest.approx(0.35)


# ------------------------------------------------------------- LiveShow


def test_a_running_live_show_runs_a_layers_cycles() -> None:
    ramp = layer("intensity", "sawUp", "absolute", cycles=2)
    with LiveShow(show_of(rig()), output=False) as live:
        run(live, template_line("Ramp", ramp), "sel fixture 301", 'effect add "Ramp" hz 0.25')
        deadline = time.monotonic() + 2.0
        while live.effects is None or not live.effects.effects:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        (effect,) = live.effects.effects
        assert effect.hz == pytest.approx(0.25)
        assert len(effect.wave) == WAVE_SAMPLES
        for k, w in enumerate(effect.wave):  # two ramps from where the clock is
            expected = frac(2 * (effect.phase + k / WAVE_SAMPLES))
            assert min(abs(w - expected), 1 - abs(w - expected)) < 1e-6
