"""The effect status: the effect instances the engine runs (GAP-09 of
``docs/dev/tui/engine-gaps.md``).

``OfflineShow.effects`` and ``LiveShow.effects`` list, at one tick, every
running instance, the playbacks' and the programmer's: where it is defined
(playback, cue, id), how far it has faded in, its size and rate now, its
phase, and the next cycle of its wave or its colours. The rig has two moving
heads, two RGB pars and two dimmers; the effects come from the built-in
library through ``effect add``.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from builders import Doc, channel, color, fixture, grand_master, mode, profile, rng, show, show_of
from busk.compiler.compile import compile_show
from busk.engine.clock import FakeClock
from busk.engine.effect_status import WAVE_SAMPLES
from busk.engine.link import LocalEngine
from busk.engine.loop import Engine
from busk.engine.snapshot import EffectSnapshot, EffectStatus, FixtureOutput, OutputSnapshot
from busk.runner import LiveShow, OfflineShow
from busk.session.ids import CounterIds
from busk.session.library import ProfileLibrary


def status_rig() -> Doc:
    """Heads 101 and 102, RGB pars 201 and 202, dimmers 301 and 302; one
    page and a grand master."""
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
    par = profile(
        "p-par",
        mode([channel(0, "intensity"), color(1, "red"), color(2, "green"), color(3, "blue")]),
    )
    dimmer = profile("p-dim", mode([channel(0, "intensity")]))
    doc = show(
        [head, par, dimmer],
        [
            fixture("f-h1", 101, "p-head", 1),
            fixture("f-h2", 102, "p-head", 10),
            fixture("f-par", 201, "p-par", 20),
            fixture("f-par2", 202, "p-par", 24),
            fixture("f-d1", 301, "p-dim", 30),
            fixture("f-d2", 302, "p-dim", 31),
        ],
    )
    doc["pages"] = [{"id": "pg-1", "number": 1, "name": "Main", "slots": []}]
    doc["masters"] = [grand_master()]
    return doc


@pytest.fixture
def offline() -> OfflineShow:
    return OfflineShow(show_of(status_rig()))


def run(show_: OfflineShow | LiveShow, *lines: str) -> None:
    for line in lines:
        reply = show_.execute(line)
        assert reply.ok, f"{line}: {reply.text}"


def only(effects: EffectSnapshot) -> EffectStatus:
    (effect,) = effects.effects
    return effect


def keys(effects: EffectSnapshot) -> list[tuple[int | None, str | None, str]]:
    return [(e.playback, e.cue, e.id) for e in effects.effects]


def of(output: OutputSnapshot, number: int) -> FixtureOutput:
    return next(f for f in output.fixtures if f.number == number)


def record_circle(offline: OfflineShow, slot: int, *options: str) -> None:
    """Playback ``slot``: one cue with 101 at 50 % and a Circle on it."""
    add = " ".join(('effect add "Circle"', *options))
    run(offline, "sel fixture 101", "set intensity 50%", add)
    run(offline, f"record slot {slot}", "clear")


# ------------------------------------------------------------------ the list


def test_nothing_runs_at_first_and_a_status_is_made_once_per_tick(offline: OfflineShow) -> None:
    first = offline.effects
    assert first.effects == ()
    assert offline.effects is first
    frame = offline.tick(1.5)
    effects = offline.effects
    assert effects is not first
    assert (effects.seq, effects.time) == (frame.seq, frame.time)


def test_a_programmer_effect_has_no_playback_and_no_cue(offline: OfflineShow) -> None:
    run(offline, "sel fixture 101 thru 102", 'effect add "Circle" hz 0.5')
    offline.tick(0.5)
    effect = only(offline.effects)
    assert (effect.playback, effect.cue, effect.id) == (None, None, "fx1")
    assert (effect.presence, effect.size, effect.hz, effect.phase) == (1.0, 20.0, 0.5, 0.25)
    run(offline, "effect remove fx1")
    assert offline.effects.effects == ()  # the programmer's fade time is 0


def test_a_cue_effect_names_its_playback_and_its_cue(offline: OfflineShow) -> None:
    record_circle(offline, 1, "hz 1")
    assert offline.effects.effects == ()  # recorded, not running
    run(offline, "go 1")
    assert keys(offline.effects) == [(1, "1", "fx1")]
    run(offline, "release 1 0")
    assert offline.effects.effects == ()


def test_playbacks_in_show_order_then_the_programmer(offline: OfflineShow) -> None:
    record_circle(offline, 1, "id a")
    run(offline, "sel fixture 102", "set intensity 50%", 'effect add "Sweep" id b')
    run(offline, 'effect add "Circle" id c', "record slot 2", "clear")
    run(offline, "sel fixture 301", 'effect add "Wave"')
    run(offline, "go 2", "go 1")  # playback 2 goes live first
    expected = [(1, "1", "a"), (2, "1", "b"), (2, "1", "c"), (None, None, "fx1")]
    assert keys(offline.effects) == expected


def test_a_flash_runs_the_cue_effects_of_its_playback(offline: OfflineShow) -> None:
    record_circle(offline, 1)
    run(offline, "flash 1 on")
    assert keys(offline.effects) == [(1, "1", "fx1")]
    run(offline, "flash 1 off")
    assert offline.effects.effects == ()


# ----------------------------------------------------------------- the cue


def test_a_tracked_effect_keeps_the_cue_that_defines_it(offline: OfflineShow) -> None:
    run(offline, "sel fixture 101", "set intensity 50%", 'effect add "Circle" id c size 10')
    run(offline, "record slot 1", "clear", "cuelist 1 tracking true")
    run(offline, "sel fixture 102", "set intensity 50%", "record cue 1/2", "clear")
    run(offline, "sel fixture 101", 'effect add "Circle" id c size 30', "record cue 1/3", "clear")
    run(offline, "cue 1/3 time 2", "go 1")
    assert (only(offline.effects).cue, only(offline.effects).size) == ("1", 10.0)
    run(offline, "go 1")
    assert (only(offline.effects).cue, only(offline.effects).size) == ("1", 10.0)  # tracked
    run(offline, "go 1")  # cue 3 changes it: the new settings fade in over 2 s
    offline.tick(1.0)
    changing = only(offline.effects)
    assert (changing.cue, changing.size, changing.presence) == ("3", 30.0, 1.0)  # ½ + ½


def test_renumbering_a_cue_renames_the_running_effects(offline: OfflineShow) -> None:
    record_circle(offline, 1)
    run(offline, "go 1", 'cue 1/1 number "0.5"')
    assert keys(offline.effects) == [(1, "0.5", "fx1")]


# ---------------------------------------------------------------- presence


def test_presence_rises_over_the_fade_in(offline: OfflineShow) -> None:
    record_circle(offline, 1, "fadein 2")
    run(offline, "go 1")
    presences = []
    for t in (0.0, 1.0, 2.0, 3.0):
        offline.tick(t)
        presences.append(only(offline.effects).presence)
    assert presences == [0.0, 0.5, 1.0, 1.0]


def test_presence_falls_while_an_effect_leaves(offline: OfflineShow) -> None:
    record_circle(offline, 1)
    run(offline, "sel fixture 102", "set intensity 50%", "record cue 1/2", "clear")
    run(offline, "cue 1/2 time 2", "go 1", "go 1")  # cue 2 does not hold it: out over 2 s
    offline.tick(1.0)
    assert only(offline.effects).presence == 0.5
    offline.tick(2.0)
    assert offline.effects.effects == ()


def test_a_programmer_effect_leaves_over_the_fade_time(offline: OfflineShow) -> None:
    run(offline, "fade 2", "sel fixture 101", 'effect add "Circle"')
    offline.tick(2.0)
    assert only(offline.effects).presence == 1.0
    run(offline, "effect remove fx1")
    offline.tick(3.0)
    assert only(offline.effects).presence == 0.5
    offline.tick(4.0)
    assert offline.effects.effects == ()


def test_a_release_scales_the_output_not_the_presence(offline: OfflineShow) -> None:
    record_circle(offline, 1)
    run(offline, "go 1", "release 1 2")
    offline.tick(1.0)
    assert offline.snapshot.playbacks[0].state == "releasing"
    assert only(offline.effects).presence == 1.0
    offline.tick(2.0)
    assert offline.effects.effects == ()


# ------------------------------------------------------------ size and rate


def test_size_follows_the_size_master_and_a_size_fader(offline: OfflineShow) -> None:
    run(offline, 'master add size "FX"', "sel fixture 101", 'effect add "Circle" sizemaster "FX"')
    run(offline, "record slot 1", "clear")  # effects only: a size fader
    run(offline, "fader 1 40%", 'master "FX" 50%')
    assert only(offline.effects).size == pytest.approx(20 * 0.5 * 0.4)


def test_hz_is_the_rate_now(offline: OfflineShow) -> None:
    run(offline, 'master add speed "Speed 1" bpm 120', "sel fixture 101")
    run(offline, 'effect add "Circle" bpm x 0.5', "sel fixture 301", 'effect add "Chase" hz 5')
    assert [e.hz for e in offline.effects.effects] == [1.0, 5.0]
    run(offline, "bpm 90", "safety strobe 3")  # a tempo; a cap on the flashing chase
    assert [e.hz for e in offline.effects.effects] == [0.75, 3.0]


# ------------------------------------------------- phase and the next cycle


@pytest.mark.parametrize("direction", ["forward", "reverse", "bounce"])
def test_the_wave_is_the_next_cycle_of_the_first_member(
    offline: OfflineShow, direction: str
) -> None:
    hz = 0.8
    run(offline, "sel fixture 301 thru 302")
    run(offline, f'effect add "Wave" hz {hz} phase 90 270 {direction}')  # 301 at 90°
    start = 0.33  # the clock at 0.264 cycles: no sample on a cycle boundary
    offline.tick(start)
    effect = only(offline.effects)
    phase = {"forward": 0.264, "reverse": 0.736, "bounce": 0.264}[direction]  # members' offsets out
    assert effect.phase == pytest.approx(phase)
    assert len(effect.wave) == WAVE_SAMPLES
    assert effect.colors == ()
    seen = []
    for k in range(WAVE_SAMPLES):
        offline.tick(start + k / (WAVE_SAMPLES * hz))
        seen.append(of(offline.output, 301).intensity)  # low 0, high 1: the wave itself
    assert effect.wave == pytest.approx(seen, abs=1e-9)


def test_a_random_wave_shows_the_cycle_it_runs_into(offline: OfflineShow) -> None:
    layer = '{"attribute": "pan", "waveform": {"kind": "random", "seed": 7, "smooth": false}'
    run(offline, f'effect template add "Dice" [{layer}, "phaseOffset": 0, "mode": "absolute"}}]')
    run(offline, "sel fixture 301, fixture 101")  # the dimmer has no pan: 101 is the second member
    run(offline, 'effect add "Dice" hz 2 low -90 high 90 phase 0 0')
    start = 0.37  # 0.74 cycles: the next cycle crosses into the cycle after
    offline.tick(start)
    effect = only(offline.effects)
    seen = []
    for k in range(WAVE_SAMPLES):
        offline.tick(start + k / (WAVE_SAMPLES * 2))
        pan = of(offline.output, 101).pan
        assert pan is not None
        seen.append((pan + 90) / 180)
    assert effect.wave == pytest.approx(seen, abs=1e-9)
    assert len(set(effect.wave)) == 2  # two cycles, one random level each


def test_colours_are_the_next_cycle_of_the_first_colour_layer(offline: OfflineShow) -> None:
    hz = 0.4
    run(offline, "sel fixture 101, fixture 201")  # the head has no colour: 201 is at 180°
    run(offline, f'effect add "Rainbow" hz {hz}')
    start = 0.6
    offline.tick(start)
    effect = only(offline.effects)
    assert effect.wave == ()
    assert len(effect.colors) == WAVE_SAMPLES
    seen = []
    for k in range(WAVE_SAMPLES):
        offline.tick(start + k / (WAVE_SAMPLES * hz))
        color_ = of(offline.output, 201).color
        assert color_ is not None
        seen.append(color_)
    for sample, out in zip(effect.colors, seen, strict=True):
        assert sample == pytest.approx(out, abs=1e-9)


def test_the_wave_is_the_first_layers_with_one(offline: OfflineShow) -> None:
    run(offline, "sel fixture 101", 'effect add "Circle" hz 1 size 20')
    offline.tick(0.1)
    effect = only(offline.effects)
    pan = of(offline.output, 101).pan
    assert pan is not None
    assert effect.wave[0] == pytest.approx((pan / 20 + 1) / 2)  # pan's, not tilt's (+90°)
    assert effect.colors == ()


def test_colours_are_those_of_the_first_members_palette() -> None:
    offline = OfflineShow(show_of(status_rig()), ids=CounterIds())
    run(offline, "sel fixture 201", "set color 1 0 0", "sel fixture 202", "set color 0 0 1")
    run(offline, "sel fixture 201 thru 202", 'record preset color 1 "Mix"', "clear")
    palette = f'[{{"presetId": "{offline.show["presets"][0]["id"]}"}}, {{"r": 0, "g": 1, "b": 0}}]'
    layer = f'{{"attribute": "color", "palette": {palette}, "blend": "snap", "mode": "absolute"}}'
    run(offline, f'effect template add "Mix" [{layer}]')
    run(offline, "sel fixture 201 thru 202", 'effect add "Mix" hz 1 phase 0 0')
    colors = only(offline.effects).colors
    assert colors == ((1.0, 0.0, 0.0),) * 10 + ((0.0, 1.0, 0.0),) * 10  # 201's preset colour


# --------------------------------------------------------------- LiveShow


def test_a_live_show_captures_its_effects_once_they_are_read() -> None:
    with LiveShow(show_of(status_rig()), output=False) as live:
        run(live, "sel fixture 101", 'effect add "Circle" hz 1')
        time.sleep(0.2)
        engine = live._engine
        assert engine is not None
        assert engine.effects is None  # nobody asked: no capture
        assert live.effects is None  # the first read asks …
        deadline = time.monotonic() + 2.0
        while live.effects is None and time.monotonic() < deadline:
            time.sleep(0.02)  # … and the engine's next tick captures
        effects = live.effects
        assert effects is not None
        assert keys(effects) == [(None, None, "fx1")]
        assert live.effects is effects or live.effects.seq > effects.seq
        time.sleep(0.1)
        newer = live.effects
        assert newer is not None
        assert newer.seq > effects.seq  # every tick from then on
        assert engine.output is None  # reading the effects does not capture the output


def test_busk_runs_show_reads_the_effects_through_its_link(tmp_path: Path) -> None:
    """With ``--threads`` the link is the engine's own; the console process's
    (GAP-11) is in ``tests/test_frontend.py``."""
    shown = show_of(status_rig())
    compiled = compile_show(shown)
    clock = FakeClock()
    engine = Engine(compiled, clock)
    live = LiveShow._attached(
        shown,
        compiled,
        LocalEngine(engine),
        clock,
        path=tmp_path / "unused.show",
        library=ProfileLibrary(),
        state_dir=tmp_path,
        dirty=False,
        stamp=("s", 0),
        causes=False,
        iface="lo",
        status=lambda: "",
        about=lambda: (),
        poll=lambda: None,
        routes=lambda: None,
        say=lambda text: None,
        warn=lambda text: None,
    )
    run(live, "sel fixture 101", 'effect add "Circle"')
    assert live.effects is None  # the first read asks …
    engine.tick(0.0)
    effects = live.effects
    assert effects is not None  # … and the engine's next tick captures them
    assert keys(effects) == [(None, None, "fx1")]
