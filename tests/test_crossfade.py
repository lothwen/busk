"""Crossfade faders (phase-6-plan §5.6, decision 11).

A ``crossfade`` fader plays a sequence by hand: leaving its rest end starts
the next transition, whose fades run on a virtual clock ``started +
progress × span``; reaching the far end completes it. Most tests compare
the crossfade rig with its *twin*, the same cues on a ``none`` fader played
by GO buttons:

* a fader moved in step with the clock (its travel at ``t`` is ``(t −
  start) / span``) plays exactly like a GO at ``start``, effects included,
  since the virtual clock is then real time;
* without effects nothing moves in real time, so a fader at progress ``p``
  shows the twin's frame ``p × span`` after its GO, whenever it got there.
"""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from builders import (
    busk_rig,
    compile_doc,
    cue,
    cue_list,
    entry,
    lanes_of,
    literal,
    playback,
    rgb,
    show_of,
    targets,
)
from busk.cli import status_line
from busk.compiler.compile import CompiledShow, compile_show
from busk.engine.effects import EffectBank, EffectTiming
from busk.engine.fades import SeqRule, Timing
from busk.engine.install import EMPTY_FRAME, Install
from busk.engine.playback_runtime import Manual, PlaybackRuntime
from busk.model.show import Show
from harness import Harness, Script, back, fader, go, master, release

PB = "pb-x"
S1, S2, S3 = 8.0, 4.0, 1.0  # the spans: into cue 1, cue 2 and cue 3
TICKS = [round(0.05 * k, 2) for k in range(361)]  # 0 … 18 s

# ---------------------------------------------------------------- the rigs


def _instance(ident: str, mode: str, fade_in: float | None) -> dict[str, Any]:
    instance = {
        "id": ident,
        "templateId": f"t-{mode}",
        "targets": targets("fx-mh3"),
        "rate": {"kind": "hz", "value": 0.5},
        "direction": "forward",
        "size": 0.3,
        "phase": {"start": 0, "end": 0},
        "groups": 1,
        "blocks": 1,
        "wings": 1,
    }
    if fade_in is not None:
        instance["sizeFadeIn"] = fade_in
    return instance


def rig(
    *,
    twin: bool = False,
    effects: bool = True,
    auto_start: bool = True,
    wrap: bool = False,
) -> dict[str, Any]:
    """The crossfade rig, or its ``twin``: the same cues on a ``none`` fader,
    with cue 3's 0 s timing as 1 s linear (what the fader plays it with).

    pb-x plays three cues:

    * c1: MH 1 at 50 % red, in 4 s after 1 s, its colour in 6 s after 2 s,
      out 2 s: span 8 s;
    * c2: MH 1 at 100 % blue and MH 2 at 80 %, in 2 s after 0.5 s (easeIn),
      out 3 s after 1 s: span 4 s. With ``effects``, two effects on MH 3:
      e-in enters over a 1.5 s ``sizeFadeIn``, e-cue with the cue's timing;
    * c3: MH 1 at 20 % green, no timing: by hand, 1 s linear.
    """
    doc = busk_rig(spots=3)
    doc["masters"].append({"id": "m-fade", "kind": "fadeTime", "name": "Fade"})
    doc["effects"] = [
        {
            "id": f"t-{mode}",
            "name": mode,
            "layers": [
                {"attribute": "intensity", "waveform": {"kind": "sine"}, "phaseOffset": 0,
                 "mode": mode}
            ],
        }
        for mode in ("add", "absolute")
    ]  # fmt: skip

    def mh(k: int, level: float, color: tuple[float, float, float] | None = None) -> list[Any]:
        values = [entry(targets(f"fx-mh{k}"), "intensity", literal(level))]
        if color is not None:
            values.append(entry(targets(f"fx-mh{k}"), "color", literal(rgb(*color))))
        return values

    c1 = cue("c1", *mh(1, 0.5, (1, 0, 0)), number="1", fade_in=4, delay_in=1, fade_out=2)
    c1["timing"]["perFamily"] = {"color": {"fade": 6.0, "delay": 2.0}}
    c2 = cue(
        "c2",
        *mh(1, 1.0, (0, 0, 1)),
        *mh(2, 0.8),
        number="2",
        fade_in=2,
        delay_in=0.5,
        fade_out=3,
        delay_out=1,
        curve="easeIn",
    )
    if effects:
        c2["effects"] = [_instance("e-in", "absolute", 1.5), _instance("e-cue", "add", None)]
    c3 = cue("c3", *mh(1, 0.2, (0, 1, 0)), number="3", fade_in=S3 if twin else 0.0)
    if twin:
        c3["timing"]["fadeOut"] = S3
    cues = cue_list("cl-x", 1, c1, c2, c3)
    cues["wrap"] = wrap
    doc["cueLists"].append(cues)
    doc["playbacks"].append(
        playback(
            PB,
            1,
            "cl-x",
            fader="none" if twin else "crossfade",
            buttons=("go", "back", "release"),
            auto_start=auto_start,
        )
    )
    return doc


@pytest.fixture(scope="module")
def shows() -> dict[str, CompiledShow]:
    """The rigs, compiled once: with effects, plain, and both twins."""
    return {
        "fx": compile_doc(rig()),
        "fx-twin": compile_doc(rig(twin=True)),
        "plain": compile_doc(rig(effects=False)),
        "plain-twin": compile_doc(rig(twin=True, effects=False)),
    }


def runtime_of(harness: Harness) -> PlaybackRuntime:
    return harness.engine.runtime.playbacks.runtimes[cast(Any, PB)]


def drive(start: float, span: float, rest: float, ticks: list[float] = TICKS) -> Script:
    """A fader leaving ``rest`` at ``start`` in step with the clock: its
    travel at each tick ``t`` is ``(t − start) / span`` until it arrives. The
    first move travels 1e-9, as a fader cannot leave its end by nothing."""
    toward = 1.0 if rest == 0.0 else -1.0
    script: Script = [(start, fader(PB, rest + toward * 1e-9))]
    for t in ticks:
        if start < t <= start + span:
            script.append((t, fader(PB, rest + toward * min(1.0, (t - start) / span))))
    return script


def frames(show: CompiledShow, script: Script, ticks: list[float] = TICKS) -> Any:
    observed = Harness(show).run(script, ticks)
    return np.array([observed[t].logical for t in ticks])


# ---------------------------------------------------------------- the twin oracle


def test_a_fader_in_step_with_the_clock_plays_like_go(shows: dict[str, CompiledShow]) -> None:
    """Idle → cue 1 (autoStart), 1 → 2 with effects entering, and 2 → 3,
    whose 0 s timing the fader plays as 1 s linear: delays, per-family
    times, curves and effects all land where the twin's GOs put them."""
    by_hand = [*drive(1.0, S1, 0.0), *drive(10.0, S2, 1.0), *drive(15.0, S3, 0.0)]
    by_go: Script = [(1.0, go(PB)), (10.0, go(PB)), (15.0, go(PB))]
    np.testing.assert_allclose(
        frames(shows["fx"], by_hand), frames(shows["fx-twin"], by_go), rtol=0, atol=1e-6
    )


@settings(max_examples=40, deadline=None)
@given(
    st.lists(
        st.tuples(st.floats(0.0, 1.0), st.floats(0.01, 3.0)),
        min_size=1,
        max_size=10,
    )
)
def test_the_frame_follows_the_furthest_travel(moves: list[tuple[float, float]]) -> None:
    """Cue 1 → 2 by hand, the fader resting at 1: after any moves, at any
    times, the frame is the twin's ``progress × 4 s`` after its GO, where
    ``progress`` is the furthest the fader has gone from 1. It pauses, never
    reverses, and completes at 0."""
    plain, twin = _plain()
    manual = Harness(plain)
    manual.submit(fader(PB, 1.0))  # idle → cue 1, completed at once
    manual.tick(0.1)
    reference = Harness(twin)
    reference.run([(0.1, go(PB)), (20.0, go(PB))], [0.1, 19.0])
    now, progress = 1.0, 0.0
    for level, gap in moves:
        now += gap
        progress = max(progress, 1.0 - level)
        manual.submit(fader(PB, level))
        observed = manual.tick(now).logical
        expected = reference.tick(20.0 + progress * S2).logical
        np.testing.assert_allclose(observed, expected, rtol=0, atol=1e-12)
        status = manual.engine.snapshot.playbacks[0]
        assert status.progress == (progress if 0.0 < progress < 1.0 else None)
        if progress >= 1.0:
            assert runtime_of(manual).crossRest == 0.0
            break


_PLAIN: list[CompiledShow] = []


def _plain() -> tuple[CompiledShow, CompiledShow]:
    """The plain rig and its twin, compiled once (hypothesis bypasses fixtures)."""
    if not _PLAIN:
        _PLAIN.extend([compile_doc(rig(effects=False)), compile_doc(rig(twin=True, effects=False))])
    return _PLAIN[0], _PLAIN[1]


def test_the_span_is_the_programmed_length(shows: dict[str, CompiledShow]) -> None:
    """8 s into cue 1 (its colour's delay and fade), 4 s into cue 2 (its out
    timing), 1 s into cue 3 (no timing), and the fade-time override's time
    while a fade-time master is up."""
    harness = Harness(shows["fx"])
    rt = runtime_of(harness)
    spans = []
    for t, level in ((1.0, 0.5), (2.0, 1.0), (3.0, 0.5), (4.0, 0.0), (5.0, 0.5)):
        harness.submit(fader(PB, level))
        harness.tick(t)
        if rt.manual is not None:
            spans.append(rt.manual.end - rt.manual.started)
    assert spans == [S1, S2, S3]

    harness = Harness(shows["fx"])
    harness.submit(master("m-fade", 0.5), fader(PB, 0.5))
    harness.tick(1.0)
    manual = runtime_of(harness).manual
    assert manual is not None
    assert manual.end - manual.started == 2.5


# ---------------------------------------------------------------- rest ends and completion


def test_the_fader_rests_at_either_end(shows: dict[str, CompiledShow]) -> None:
    """A/B: each transition completes at the far end, which becomes the rest
    end; slammed across, the frame is at once the twin's settled cue."""
    harness = Harness(shows["plain"])
    rt = runtime_of(harness)
    assert rt.crossRest == 0.0
    rests = []
    for t, level in ((1.0, 1.0), (2.0, 0.0), (3.0, 1.0)):
        harness.submit(fader(PB, level))
        harness.tick(t)
        rests.append((rt.cue, rt.crossRest, rt.manual))
    assert rests == [(0, 1.0, None), (1, 0.0, None), (2, 1.0, None)]
    settled = Harness(shows["plain-twin"]).run(
        [(1.0, go(PB)), (2.0, go(PB)), (3.0, go(PB))], [30.0]
    )[30.0]
    np.testing.assert_array_equal(harness.tick(3.01).logical, settled.logical)
    np.testing.assert_array_equal(harness.tick(30.0).logical, settled.logical)


def test_completion_ignores_real_time(shows: dict[str, CompiledShow]) -> None:
    """A transition completed by hand is complete, even before its programmed
    length has passed in real time: nothing moves afterwards."""
    harness = Harness(shows["plain"])
    harness.run([(1.0, fader(PB, 1.0)), (1.5, fader(PB, 0.3)), (1.6, fader(PB, 0.0))])
    done = harness.tick(1.6).logical
    for t in (2.0, 5.0, 20.0):
        np.testing.assert_array_equal(harness.tick(t).logical, done)


def test_no_reversal(shows: dict[str, CompiledShow]) -> None:
    """Back towards the rest end the fader holds the transition where it was."""
    harness = Harness(shows["plain"])
    observed = harness.run(
        [(0.5, fader(PB, 1.0)), (1.0, fader(PB, 0.4)), (2.0, fader(PB, 0.8)), (3.0, fader(PB, 0.6))]
    )
    np.testing.assert_array_equal(observed[2.0].logical, observed[1.0].logical)
    np.testing.assert_array_equal(observed[3.0].logical, observed[1.0].logical)
    assert observed[3.0].snapshot.playbacks[0].progress == pytest.approx(0.6)


# ---------------------------------------------------------------- what is pending


def test_idle_without_auto_start_waits_for_go() -> None:
    """Nothing is pending: the fader drives nothing, and rests at the first
    end it reaches. After a GO, leaving that end moves on to cue 2."""
    harness = Harness(compile_doc(rig(effects=False, auto_start=False)))
    rt = runtime_of(harness)
    empty = harness.tick(0.0).logical
    harness.submit(fader(PB, 0.5))
    np.testing.assert_array_equal(harness.tick(1.0).logical, empty)
    assert (rt.state, rt.crossRest) == ("idle", None)
    harness.submit(fader(PB, 1.0))
    harness.tick(2.0)
    assert rt.crossRest == 1.0
    harness.submit(go(PB))
    harness.tick(3.0)
    assert (rt.state, rt.cue, rt.manual) == ("active", 0, None)
    harness.submit(fader(PB, 0.9))
    harness.tick(4.0)
    assert rt.cue == 1
    assert rt.manual is not None
    assert rt.manual.progress == pytest.approx(0.1)


@pytest.mark.parametrize("wrap", [False, True])
def test_the_end_of_the_list(wrap: bool) -> None:
    """At the last cue a list that does not wrap has nothing pending: the
    fader does nothing until it rests at an end again. One that wraps
    crossfades back to cue 1."""
    harness = Harness(compile_doc(rig(effects=False, wrap=wrap)))
    rt = runtime_of(harness)
    harness.submit(go(PB), go(PB), go(PB))  # cue 3; the fader rests at 0
    at_end = harness.tick(1.0).logical
    harness.submit(fader(PB, 0.5))
    moved = harness.tick(2.0).logical
    if wrap:
        assert (rt.cue, rt.manual is not None) == (0, True)
        assert not np.array_equal(moved, at_end)
        return
    np.testing.assert_array_equal(moved, at_end)
    assert (rt.cue, rt.manual, rt.crossRest) == (2, None, None)
    harness.submit(fader(PB, 1.0))
    harness.tick(3.0)
    assert rt.crossRest == 1.0


def test_triggers_are_ignored() -> None:
    """Cue 2 follows cue 1, but the fader is the GO: no auto-GO is armed,
    whether cue 1 came by hand or by a GO button."""
    doc = rig(effects=False)
    doc["cueLists"][0]["cues"][1]["trigger"] = {"kind": "follow", "delay": 0.0}
    show = compile_doc(doc)
    for first in (fader(PB, 1.0), go(PB)):
        harness = Harness(show)
        harness.submit(first)
        harness.tick(1.0)
        harness.tick(30.0)
        rt = runtime_of(harness)
        assert (rt.cue, rt.auto) == (0, None)


# ---------------------------------------------------------------- interruptions


def test_go_mid_transition_takes_over_without_a_jump(shows: dict[str, CompiledShow]) -> None:
    """GO halfway into cue 1 moves on to cue 2 from where the fader left
    cue 1. The fader then drives nothing until it reaches an end; leaving
    that end crossfades to cue 3."""
    harness = Harness(shows["plain"])
    rt = runtime_of(harness)
    harness.run([(1.0, fader(PB, 0.5))])
    held = harness.tick(2.0).logical
    harness.submit(go(PB))
    np.testing.assert_array_equal(harness.tick(2.5).logical, held)  # c2 waits 0.5 s
    assert (rt.cue, rt.manual, rt.crossRest) == (1, None, None)

    alone = Harness(shows["plain"])  # the same without the fader moves after the GO
    alone.run([(1.0, fader(PB, 0.5)), (2.5, go(PB))], [2.0])
    harness.submit(fader(PB, 0.8))
    np.testing.assert_array_equal(harness.tick(3.0).logical, alone.tick(3.0).logical)
    harness.submit(fader(PB, 1.0))
    np.testing.assert_array_equal(harness.tick(4.0).logical, alone.tick(4.0).logical)
    assert rt.crossRest == 1.0
    harness.submit(fader(PB, 0.9))
    harness.tick(5.0)
    assert rt.cue == 2
    assert rt.manual is not None


def test_back_mid_transition_takes_over_without_a_jump(shows: dict[str, CompiledShow]) -> None:
    harness = Harness(shows["plain"])
    harness.run([(0.5, fader(PB, 1.0)), (1.0, fader(PB, 0.5))])
    held = harness.tick(2.0).logical
    harness.submit(back(PB))
    np.testing.assert_array_equal(harness.tick(2.0).logical, held)
    assert runtime_of(harness).cue == 0


def test_a_release_mid_transition_glides_down_from_where_it_is(
    shows: dict[str, CompiledShow],
) -> None:
    """The release fades out what the fader left on stage; moving the fader
    does not bring the playback back until it has rested at an end."""
    harness = Harness(shows["plain"])
    rt = runtime_of(harness)
    harness.run([(1.0, fader(PB, 0.5))])
    held = harness.tick(5.0).logical  # 4 s of 8: MH 1's 4 s fade is 3 s in, after 1 s
    harness.submit(release(PB))
    np.testing.assert_array_equal(harness.tick(5.0).logical, held)
    assert (rt.state, rt.manual, rt.crossRest) == ("releasing", None, None)
    harness.submit(fader(PB, 0.7))
    halfway = harness.tick(5.5).logical  # the release time is 1 s
    assert rt.state == "releasing"
    show = shows["plain"]
    (was,) = lanes_of(show, held, "fx-mh1", "intensity")
    assert lanes_of(show, halfway, "fx-mh1", "intensity") == [pytest.approx(was / 2)]
    assert was == pytest.approx(0.5 * 0.75)
    harness.submit(fader(PB, 1.0), fader(PB, 0.9))  # rest at 1, then leave it: autoStart
    harness.tick(7.0)
    assert (rt.state, rt.cue, rt.manual is not None) == ("active", 0, True)


def test_a_live_edit_mid_transition_takes_over_without_a_jump(
    shows: dict[str, CompiledShow],
) -> None:
    """An edit re-targets the running cue with its own timing from where the
    fader left it; the fader then waits for an end."""
    doc = rig(effects=False)
    doc["cueLists"][0]["cues"][1]["entries"][0]["value"] = literal(0.6)
    edited = compile_doc(doc)
    harness = Harness(shows["plain"])
    rt = runtime_of(harness)
    harness.run([(0.5, fader(PB, 1.0)), (1.0, fader(PB, 0.5))])
    held = harness.tick(2.0).logical
    harness.engine.bus.install(Install(compiled=edited, remap=None, programmer=EMPTY_FRAME))
    np.testing.assert_array_equal(harness.tick(2.0).logical, held)
    assert (rt.cue, rt.manual, rt.crossRest) == (1, None, None)
    harness.submit(fader(PB, 0.2))
    later = harness.tick(20.0).logical
    alone = Harness(shows["plain"])
    alone.run([(0.5, fader(PB, 1.0)), (1.0, fader(PB, 0.5))], [2.0])
    alone.engine.bus.install(Install(compiled=edited, remap=None, programmer=EMPTY_FRAME))
    alone.tick(2.0)
    np.testing.assert_array_equal(later, alone.tick(20.0).logical)


# ---------------------------------------------------------------- effects and ticks


def test_effects_enter_by_hand(shows: dict[str, CompiledShow]) -> None:
    """Paused a quarter into cue 2 (1 s of its 4 s), e-in's presence holds at
    1 s of its 1.5 s ``sizeFadeIn`` while the effect keeps moving."""
    harness = Harness(shows["fx"])
    harness.run([(0.5, fader(PB, 1.0)), (1.0, fader(PB, 0.75))])
    rt = runtime_of(harness)
    seen = []
    for t in (1.5, 2.0, 2.5):
        seen.append(harness.tick(t).logical)
        assert rt.bank.runtimes["e-in"].source.htpWeight == pytest.approx(1.0 / 1.5)
    assert not np.array_equal(seen[0], seen[1])  # the effect moves in real time


def test_frames_do_not_depend_on_the_tick_schedule(shows: dict[str, CompiledShow]) -> None:
    """The same fader moves, ticked every 10 ms or only at the moves."""
    moves = [t for t in TICKS if 1.0 <= t <= 9.0 and round(t * 4) == t * 4]  # every 0.25 s
    script = [*drive(1.0, S1, 0.0, moves), *drive(10.0, S2, 1.0, [10.0, 11.0, 12.5, 14.0])]
    sparse = sorted({t for t, _ in script})
    dense = sorted({*sparse, *(round(0.01 * k, 2) for k in range(1500))})
    every = Harness(shows["fx"]).run(script, dense)
    only = Harness(shows["fx"]).run(script, sparse)
    for t in sparse:
        np.testing.assert_array_equal(every[t].logical, only[t].logical)


# ---------------------------------------------------------------- the snapshot


def test_the_status_line_shows_the_progress(shows: dict[str, CompiledShow]) -> None:
    harness = Harness(shows["plain"])
    observed = harness.run([(0.5, fader(PB, 1.0)), (1.0, fader(PB, 0.5))])
    status = observed[1.0].snapshot.playbacks[0]
    assert (status.cue, status.progress) == ("2", 0.5)
    assert status_line(observed[1.0].snapshot).endswith(f"1 {PB} on → 2 c2 50%")
    assert status_line(observed[0.5].snapshot).endswith(f"1 {PB} on 1 c1")


# ---------------------------------------------------------------- edges


def test_a_move_to_the_rest_end_starts_nothing(shows: dict[str, CompiledShow]) -> None:
    """Hardware resends its value: a fader 'moved' to where it rests is not
    leaving it."""
    harness = Harness(shows["plain"])
    rt = runtime_of(harness)
    harness.submit(fader(PB, 0.0))
    harness.tick(1.0)
    assert (rt.state, rt.manual, rt.crossRest) == ("idle", None, 0.0)
    harness.submit(fader(PB, 1.0), fader(PB, 1.0))
    harness.tick(2.0)
    assert (rt.cue, rt.manual, rt.crossRest) == (0, None, 1.0)


def test_a_chase_has_nothing_pending() -> None:
    """A chase steps by itself: its crossfade fader neither starts it nor
    steps it."""
    doc = rig(effects=False)
    doc["cueLists"][0].update(
        mode="chase",
        chase={"rate": {"kind": "hz", "value": 2}, "direction": "forward", "crossfade": 0},
    )
    harness = Harness(compile_doc(doc))
    rt = runtime_of(harness)
    harness.submit(fader(PB, 0.5))
    harness.tick(1.0)
    assert (rt.state, rt.manual) == ("idle", None)
    harness.submit(fader(PB, 0.0), go(PB))
    harness.tick(2.0)
    harness.submit(fader(PB, 0.5))
    harness.tick(2.1)
    assert (rt.state, rt.manual, rt.chase is not None) == ("active", None, True)


def k_rig() -> dict[str, Any]:
    """Three cues on MH 1 at 100 % and an effect e-a on MH 2:

    * k1: e-a at size 0.3, in 6 s;
    * k2: MH 2 at 50 % too, e-a at size 0.6, in 1 s;
    * k3: as k2 (e-a the same), in 2 s.
    """
    doc = rig(effects=False)
    doc["effects"] = [
        {
            "id": "t-abs",
            "name": "abs",
            "layers": [
                {"attribute": "intensity", "waveform": {"kind": "sine"}, "phaseOffset": 0,
                 "mode": "absolute"}
            ],
        }
    ]  # fmt: skip

    def effect(size: float) -> dict[str, Any]:
        instance = _instance("e-a", "abs", None)
        instance.update(templateId="t-abs", targets=targets("fx-mh2"), size=size)
        return instance

    mh1 = entry(targets("fx-mh1"), "intensity", literal(1.0))
    mh2 = entry(targets("fx-mh2"), "intensity", literal(0.5))
    k1 = cue("k1", mh1, number="1", fade_in=6)
    k2 = cue("k2", mh1, mh2, number="2", fade_in=1)
    k3 = cue("k3", mh1, mh2, number="3", fade_in=2)
    for c, size in ((k1, 0.3), (k2, 0.6), (k3, 0.6)):
        c["effects"] = [effect(size)]
    doc["cueLists"][0]["cues"] = [k1, k2, k3]
    return doc


def test_running_fades_finish_with_the_fader() -> None:
    """MH 1 is still fading into k1 (6 s, by GO) when the fader starts k2,
    which leaves it unchanged: the fader takes it on from where it is, and
    completing the transition completes it."""
    show = compile_doc(k_rig())
    harness = Harness(show)
    harness.run([(0.0, go(PB)), (1.0, fader(PB, 0.5)), (1.2, fader(PB, 1.0))])
    for t in (1.3, 30.0):
        assert lanes_of(show, harness.tick(t).logical, "fx-mh1", "intensity") == [1.0]


def test_held_effect_versions_leave() -> None:
    """Halfway from k1 to k2 by hand, e-a has two versions held at half
    presence. A GO to k3 (e-a as in k2) fades the newer one in and the
    older one out."""
    harness = Harness(compile_doc(k_rig()))
    harness.run([(0.0, fader(PB, 1.0)), (1.0, fader(PB, 0.5)), (2.0, go(PB))])
    versions = runtime_of(harness).bank.runtimes["e-a"].versions
    assert [v.presence.toValue for v in versions] == [0.0, 1.0]
    harness.tick(10.0)
    assert len(runtime_of(harness).bank.runtimes["e-a"].versions) == 1


def test_an_unrelated_edit_keeps_the_transition() -> None:
    """An edit that leaves the cue list alone (the compile reuses it) does
    not stop the fader."""
    show = show_of(rig(effects=False))
    base = compile_show(show)
    renamed = cast(Show, {**show, "playbacks": [{**show["playbacks"][0], "name": "Renamed"}]})
    edited = compile_show(renamed, previous=base)
    assert edited.cueLists[cast(Any, "cl-x")] is base.cueLists[cast(Any, "cl-x")]
    harness = Harness(base)
    harness.run([(0.5, fader(PB, 1.0)), (1.0, fader(PB, 0.5))])
    harness.engine.bus.install(Install(compiled=edited, remap=None, programmer=EMPTY_FRAME))
    harness.tick(2.0)
    manual = runtime_of(harness).manual
    assert manual is not None
    assert manual.progress == 0.5


# ---------------------------------------------------------------- the last bit


def test_the_clock_ends_exactly_at_its_end() -> None:
    """``0.2 + 1.0 × (0.9 − 0.2)`` is not 0.9 in floating point."""
    assert Manual(started=0.2, end=0.9, rest=0.0, progress=1.0).time == 0.9


def test_the_clock_reaches_every_fade_end() -> None:
    """A fade started at 0.1 with 0.2 s delay and 0.5 s ends at
    ``(0.1 + 0.2) + 0.5``, one bit after ``0.1 + 0.7``, where it is one bit
    short of done: completing by hand still lands exactly on the cue."""
    doc = rig(effects=False)
    doc["cueLists"][0]["cues"][0]["timing"] = cue("c", delay_in=0.2, fade_in=0.5)["timing"]
    show = compile_doc(doc)
    harness = Harness(show)
    harness.run([(0.1, fader(PB, 0.5)), (0.2, fader(PB, 1.0))])
    assert lanes_of(show, harness.tick(0.3).logical, "fx-mh1", "intensity") == [0.5]


def test_hold_keeps_exact_targets(shows: dict[str, CompiledShow]) -> None:
    """A presence held at its end holds its target, though the envelope's
    own arithmetic lands one bit short there."""
    effect = shows["fx"].cueLists[cast(Any, "cl-x")].cues[1].effects[1]  # e-cue
    bank = EffectBank("pb", 50, {})
    bank.retarget(0.1, [effect], EffectTiming.uniform(Timing(1.0, 0.1)), SeqRule.all(1))
    presence = bank.runtimes["e-cue"].versions[0].presence
    assert presence.value(presence.end) != 1.0  # the trap
    bank.hold(presence.end)
    assert bank.runtimes["e-cue"].versions[0].presence.value(5.0) == 1.0
