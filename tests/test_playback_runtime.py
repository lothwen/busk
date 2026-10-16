"""Playback runtimes: the §5.5 state machine, weights per fader mode, the threshold
latch, autoStart/autoRelease, flash, temp faders, exclusivity and release timing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

from builders import Doc, busk_rig, compile_doc, entry, literal, look, rgb, targets
from busk.engine.playback_runtime import PlaybackRuntime, Playbacks
from busk.model.common import PlaybackId

PB = PlaybackId("pb")
FADE_IN = 2.0
RELEASE = 1.0


def rig(**options: Any) -> Doc:
    """One spot and a look ``pb``: intensity 0.8 and red, 2 s fade-in, 1 s
    release, threshold mode; ``options`` override the playback's settings."""
    settings: dict[str, Any] = {"fade_in": FADE_IN, "release_time": RELEASE, **options}
    return look(
        busk_rig(spots=1),
        "pb",
        1,
        entry(targets("fx-mh1"), "intensity", literal(0.8)),
        entry(targets("fx-mh1"), "color", literal(rgb(1, 0, 0))),
        **settings,
    )


def playbacks(doc: Doc | None = None, **options: Any) -> Playbacks:
    compiled = compile_doc(rig(**options) if doc is None else doc)
    return Playbacks(compiled.playbacks, compiled.slots)


def weights(runtime: PlaybackRuntime, now: float) -> tuple[float, float, float]:
    """``(htpWeight, intensityScale, ltpWeight)`` of the main source at ``now``:
    each scalar weight times the slots' own presence (every slot of the
    look fades alike)."""
    runtime.update(now)
    main = runtime.main.whole
    return (
        main.htpWeight * _presence(main.htpWeights),
        main.intensityScale,
        main.ltpWeight * _presence(main.ltpWeights),
    )


def _presence(weights: NDArray[np.float64] | None) -> float:
    """The slots' presence: 1 on the fast path (no per-lane weights)."""
    return 1.0 if weights is None or weights.size == 0 else float(weights.max())


# ------------------------------------------------------------- state table

type Step = Callable[[Playbacks], None]


def trigger(p: Playbacks) -> None:
    p.trigger(PB, 0.0)


def fader(level: float) -> Step:
    return lambda p: p.set_fader(PB, level, 0.0)


def release(time: float | None = None) -> Step:
    return lambda p: p.release(PB, 0.0, time)


IDLE: list[Step] = []
ACTIVE: list[Step] = [trigger]
RELEASING: list[Step] = [trigger, release()]
IDLE_FADER_UP: list[Step] = [fader(0.5), release(0.0)]  # autoStart, then released at once
ACTIVE_FADER_UP: list[Step] = [fader(0.5)]
RELEASING_FADER_UP: list[Step] = [fader(0.5), release()]

EVENTS: dict[str, Step] = {
    "TRIGGER": trigger,
    "TOGGLE": lambda p: p.toggle(PB, 0.0),
    "GO": lambda p: p.go(PB, 0.0),
    "RELEASE": release(),
    "fader leaves 0": fader(0.5),
    "fader reaches 0": fader(0.0),
}

STATE_TABLE = [
    # (event, setup, state before, state after, takes a fresh seq)
    ("TRIGGER", IDLE, "idle", "active", True),
    ("TRIGGER", ACTIVE, "active", "active", True),  # re-assert
    ("TRIGGER", RELEASING, "releasing", "active", True),
    ("TOGGLE", IDLE, "idle", "active", True),
    ("TOGGLE", ACTIVE, "active", "releasing", False),
    ("TOGGLE", RELEASING, "releasing", "active", True),
    ("GO", IDLE, "idle", "active", True),
    ("GO", ACTIVE, "active", "active", True),  # re-assert without releaseAtEnd
    ("GO", RELEASING, "releasing", "active", True),
    ("RELEASE", IDLE, "idle", "idle", False),
    ("RELEASE", ACTIVE, "active", "releasing", False),
    ("RELEASE", RELEASING, "releasing", "releasing", False),
    ("fader leaves 0", IDLE, "idle", "active", True),  # autoStart
    ("fader leaves 0", ACTIVE, "active", "active", False),
    ("fader leaves 0", RELEASING, "releasing", "active", True),
    ("fader reaches 0", IDLE_FADER_UP, "idle", "idle", False),
    ("fader reaches 0", ACTIVE_FADER_UP, "active", "releasing", False),  # autoRelease
    ("fader reaches 0", RELEASING_FADER_UP, "releasing", "releasing", False),
]


@pytest.mark.parametrize(
    ("event", "setup", "before", "after", "fresh_seq"),
    STATE_TABLE,
    ids=[f"{row[0]} when {row[2]}" for row in STATE_TABLE],
)
def test_state_table(
    event: str, setup: list[Step], before: str, after: str, fresh_seq: bool
) -> None:
    p = playbacks()
    for step in setup:
        step(p)
    runtime = p.runtimes[PB]
    assert runtime.state == before
    seq = runtime.activationSeq
    EVENTS[event](p)
    assert runtime.state == after
    assert (runtime.activationSeq != seq) == fresh_seq
    if fresh_seq:
        assert runtime.activationSeq == p.seqCounter  # the newest


def test_go_releases_at_end_when_the_cue_list_says_so() -> None:
    p = playbacks(release_at_end=True)
    p.go(PB, 0.0)
    p.go(PB, 0.1)
    assert p.runtimes[PB].state == "releasing"


def test_a_finished_release_goes_idle() -> None:
    p = playbacks()
    p.trigger(PB, 0.0)
    p.release(PB, 3.0)
    runtime = p.runtimes[PB]
    assert not p.update(3.5)
    assert runtime.state == "releasing"
    assert p.update(4.0)  # RELEASE = 1 s: both envelopes settled at 0
    assert runtime.state == "idle"
    assert PB not in p.live
    assert weights(runtime, 4.0)[0::2] == (0.0, 0.0)


def test_without_auto_start_or_auto_release_the_fader_only_scales() -> None:
    p = playbacks(auto_start=False, auto_release=False)
    p.set_fader(PB, 0.5, 0.0)
    assert p.runtimes[PB].state == "idle"
    p.trigger(PB, 0.0)
    p.set_fader(PB, 0.0, 1.0)
    assert p.runtimes[PB].state == "active"


# ----------------------------------------------------------- fader modes


def test_threshold_mode_activated_by_a_button() -> None:
    p = playbacks(mode="threshold")
    p.trigger(PB, 0.0)
    runtime = p.runtimes[PB]
    # Fader at 0: LTP comes in with the cue's fade, intensity is scaled to nothing.
    assert weights(runtime, 1.0) == (0.5, 0.0, 0.5)
    p.set_fader(PB, 0.5, 1.0)  # active: no autoStart, LTP already latched
    assert weights(runtime, 2.0) == (1.0, 0.5, 1.0)


def test_threshold_mode_latches_ltp_when_the_fader_crosses_the_threshold() -> None:
    p = playbacks(mode="threshold", threshold=0.1)
    runtime = p.runtimes[PB]
    p.set_fader(PB, 0.05, 0.0)  # autoStart below the threshold
    assert runtime.state == "active"
    assert not runtime.ltpLatched
    assert weights(runtime, 1.0) == (0.5, 0.05, 0.0)
    p.set_fader(PB, 0.08, 1.0)
    assert not runtime.ltpLatched
    p.set_fader(PB, 0.1, 1.0)  # crossing: LTP fades in with the cue's timing from now
    assert runtime.ltpLatched
    assert weights(runtime, 2.0) == (1.0, 0.1, 0.5)
    assert weights(runtime, 3.0) == (1.0, 0.1, 1.0)
    p.set_fader(PB, 0.05, 3.0)  # stays latched below the threshold until release
    assert weights(runtime, 3.0)[2] == 1.0


def test_threshold_mode_activated_by_the_fader_above_the_threshold_latches_at_once() -> None:
    p = playbacks(mode="threshold")
    p.set_fader(PB, 1.0, 0.0)
    assert p.runtimes[PB].ltpLatched
    assert weights(p.runtimes[PB], 1.0) == (0.5, 1.0, 0.5)


def test_follow_fader_mode_scales_ltp_by_the_fader() -> None:
    p = playbacks(mode="followFader")
    runtime = p.runtimes[PB]
    p.set_fader(PB, 0.5, 0.0)
    assert weights(runtime, 1.0) == (0.5, 0.5, 0.25)  # ltpEnv 0.5 × fader 0.5
    assert weights(runtime, 2.0) == (1.0, 0.5, 0.5)
    p.set_fader(PB, 0.25, 2.0)
    assert weights(runtime, 2.0) == (1.0, 0.25, 0.25)


def test_ignore_fader_mode_keeps_ltp_fully_present() -> None:
    p = playbacks(mode="ignoreFader")
    runtime = p.runtimes[PB]
    p.set_fader(PB, 0.2, 0.0)
    assert weights(runtime, 2.0) == (1.0, 0.2, 1.0)


def test_other_faders_do_not_scale_or_auto_start() -> None:
    p = playbacks(fader="none", mode="followFader")
    runtime = p.runtimes[PB]
    p.set_fader(PB, 0.5, 0.0)
    assert runtime.state == "idle"
    p.trigger(PB, 0.0)
    assert weights(runtime, 2.0) == (1.0, 1.0, 1.0)


def test_a_size_fader_starts_and_releases_without_scaling_the_values() -> None:
    """Phase 5 decision 14: a ``size`` fader is an effect playback's level. It
    honours ``autoStart`` and ``autoRelease`` like a ``master`` fader, without
    the threshold latch, and leaves the cue's own values at full weight."""
    p = playbacks(fader="size", mode="threshold", threshold=0.9)
    runtime = p.runtimes[PB]
    p.set_fader(PB, 0.5, 0.0)
    assert runtime.state == "active"
    assert weights(runtime, 2.0) == (1.0, 1.0, 1.0)  # LTP latched below the threshold
    p.set_fader(PB, 0.0, 3.0)
    assert runtime.state == "releasing"


# ------------------------------------------------------------ flash, temp


def test_flash_on_an_idle_playback_is_its_own_source() -> None:
    p = playbacks(flash_level=0.7, include_ltp=True, boost=250)
    runtime = p.runtimes[PB]
    p.flash(PB, True, 0.0)
    assert runtime.state == "idle"
    assert PB in p.live
    runtime.update(0.0)
    flash = runtime.flash
    assert (flash.priority, flash.seq) == (300, p.seqCounter)
    assert (flash.htpWeight, flash.intensityScale, flash.ltpWeight) == (1.0, 0.7, 1.0)
    assert (runtime.main.whole.htpWeight, runtime.main.whole.ltpWeight) == (0.0, 0.0)
    p.flash(PB, False, 0.5)
    p.update(0.5)
    assert (flash.htpWeight, flash.ltpWeight) == (0.0, 0.0)
    assert PB not in p.live


def test_flash_without_include_ltp_brings_intensity_only() -> None:
    p = playbacks()
    p.flash(PB, True, 0.0)
    p.update(0.0)
    flash = p.runtimes[PB].flash
    assert (flash.priority, flash.htpWeight, flash.intensityScale, flash.ltpWeight) == (
        50,
        1.0,
        1.0,
        0.0,
    )


def test_flash_on_an_active_playback_leaves_the_main_source_alone() -> None:
    p = playbacks()
    p.trigger(PB, 0.0)
    runtime = p.runtimes[PB]
    before = weights(runtime, 1.0)
    p.flash(PB, True, 1.0)
    assert runtime.flashSeq > runtime.activationSeq
    assert weights(runtime, 1.0) == before
    p.flash(PB, False, 1.5)
    assert runtime.state == "active"
    assert weights(runtime, 1.5)[2] == 0.75


def test_a_held_flash_keeps_its_seq() -> None:
    p = playbacks()
    p.flash(PB, True, 0.0)
    seq = p.runtimes[PB].flashSeq
    p.flash(PB, True, 0.1)  # a repeated "down" is not a new flash
    assert p.runtimes[PB].flashSeq == seq


def test_a_temp_fader_is_a_variable_level_flash() -> None:
    p = playbacks(fader="temp", flash_level=0.9)
    runtime = p.runtimes[PB]
    p.set_fader(PB, 0.4, 0.0)
    assert runtime.state == "idle"  # never latches
    runtime.update(0.0)
    assert (runtime.flash.htpWeight, runtime.flash.intensityScale) == (1.0, 0.4)
    seq = runtime.flashSeq
    p.flash(PB, True, 0.1)  # the button raises it to the flash level
    runtime.update(0.1)
    assert runtime.flash.intensityScale == 0.9
    assert runtime.flashSeq == seq  # already present: same seq
    p.flash(PB, False, 0.2)
    p.set_fader(PB, 0.0, 0.2)
    p.update(0.2)
    assert PB not in p.live


def effect_rig(**options: Any) -> Doc:
    """:func:`rig` whose cue also runs a 1 Hz ``sawUp`` on fx-mh1's intensity."""
    doc = rig(**options)
    layer = {
        "attribute": "intensity",
        "waveform": {"kind": "sawUp"},
        "phaseOffset": 0,
        "mode": "absolute",
    }
    doc["effects"] = [{"id": "t-saw", "name": "Saw", "layers": [layer]}]
    doc["cueLists"][0]["cues"][0]["effects"] = [
        {
            "id": "e",
            "templateId": "t-saw",
            "targets": targets("fx-mh1"),
            "rate": {"kind": "hz", "value": 1.0},
            "direction": "forward",
            "size": 1.0,
            "phase": {"start": 0, "end": 0},
            "groups": 1,
            "blocks": 1,
            "wings": 1,
        }
    ]
    return doc  # fmt: skip


def test_the_flash_bank_runs_while_the_flash_is_present_and_main_is_idle() -> None:
    """Phase 5 decision 16: the flash bank starts when the flash appears on
    an idle playback (in the flash band, at the flash's number), stops when
    main activates, starts again when main goes idle under the held flash,
    and stops when the flash goes away. Its instances enter at once, not
    with the cue's 2 s fade-in."""
    p = playbacks(effect_rig(boost=30))
    runtime = p.runtimes[PB]
    p.flash(PB, True, 0.0)
    runtime.update(0.0)
    (flashed,) = runtime.flashBank.runtimes.values()
    assert (flashed.source.priority, flashed.seq) == (80, runtime.flashSeq)
    assert flashed.newest.presence.value(0.0) == 1.0
    assert not runtime.bank.active
    p.trigger(PB, 1.0)
    assert (runtime.bank.active, runtime.flashBank.active) == (True, False)
    p.release(PB, 2.0, 0.0)  # idle at once, under the held flash
    (again,) = runtime.flashBank.runtimes.values()
    assert again.clock.position(2.5) == 0.5  # a new clock from 2.0
    assert not runtime.bank.active
    p.flash(PB, False, 3.0)
    assert not runtime.flashBank.active
    p.update(3.0)
    assert PB not in p.live


def test_a_temp_fader_runs_the_flash_bank_and_a_rate_fader_rerates_it() -> None:
    p = playbacks(effect_rig(fader="temp", fade_in=0.0))
    runtime = p.runtimes[PB]
    p.set_fader(PB, 0.4, 0.0)
    assert runtime.flashBank.active
    p.set_fader(PB, 0.0, 1.0)
    assert not runtime.flashBank.active
    p = playbacks(effect_rig(fader="rate", buttons=("flash",), fade_in=0.0))
    runtime = p.runtimes[PB]
    p.flash(PB, True, 0.0)
    p.set_fader(PB, 0.75, 1.0)  # ×2 from 1 s on (Hz: 4^0.5)
    (flashed,) = runtime.flashBank.runtimes.values()
    assert flashed.clock.position(1.5) == pytest.approx(2.0)


# ------------------------------------------------------------ exclusivity


def exclusive_rig() -> Doc:
    doc = busk_rig(spots=1)
    for number, name in enumerate(["red", "blue", "green"], start=1):
        look(
            doc,
            name,
            number,
            entry(targets("fx-mh1"), "color", literal(rgb(1, 0, 0))),
            exclusivity="color",
            release_time=number,  # 1, 2 and 3 s
        )
    look(doc, "other", 4, entry(targets("fx-mh1"), "pan", literal(10)))
    return doc


def test_exclusivity_releases_the_others_with_their_own_release_time() -> None:
    p = playbacks(exclusive_rig())
    red, blue = p.runtimes[PlaybackId("red")], p.runtimes[PlaybackId("blue")]
    p.trigger(PlaybackId("other"), 0.0)
    p.trigger(PlaybackId("red"), 0.0)
    p.trigger(PlaybackId("blue"), 1.0)
    assert (red.state, blue.state) == ("releasing", "active")
    assert red.env.duration == 1.0  # red's own release time
    assert p.runtimes[PlaybackId("other")].state == "active"  # no key: untouched
    p.set_fader(PlaybackId("green"), 1.0, 2.0)  # autoStart is latching too
    assert blue.state == "releasing"
    assert blue.env.duration == 2.0


def test_flashes_never_apply_exclusivity() -> None:
    p = playbacks(exclusive_rig())
    p.trigger(PlaybackId("red"), 0.0)
    p.flash(PlaybackId("blue"), True, 0.5)
    assert p.runtimes[PlaybackId("red")].state == "active"


def test_reasserting_does_not_release_itself() -> None:
    p = playbacks(exclusive_rig())
    p.trigger(PlaybackId("red"), 0.0)
    p.trigger(PlaybackId("red"), 0.5)
    assert p.runtimes[PlaybackId("red")].state == "active"


# ---------------------------------------------------------- release timing


def test_a_release_from_mid_fade_lasts_exactly_the_release_time() -> None:
    p = playbacks()
    runtime = p.runtimes[PB]
    p.set_fader(PB, 1.0, 10.0)
    assert weights(runtime, 10.5) == (0.25, 1.0, 0.25)
    p.release(PB, 10.5)
    assert weights(runtime, 11.0) == (0.125, 1.0, 0.125)
    assert runtime.state == "releasing"
    assert weights(runtime, 11.5) == (0.0, 1.0, 0.0)
    assert runtime.state == "idle"


def test_a_release_time_overrides_the_playback_release_time() -> None:
    p = playbacks()
    p.trigger(PB, 0.0)
    p.update(2.0)
    p.release(PB, 2.0, 4.0)
    assert weights(p.runtimes[PB], 3.0)[2] == 0.75


def test_a_release_in_zero_seconds_goes_idle_at_once() -> None:
    p = playbacks()
    runtime = p.runtimes[PB]
    p.trigger(PB, 0.0)
    p.update(0.5)
    p.release(PB, 0.5, 0.0)
    assert runtime.state == "idle"
    p.update(0.5)
    assert (runtime.main.whole.htpWeight, runtime.main.whole.ltpWeight) == (0.0, 0.0)
    assert list(p.sources()) == []


def test_activating_while_releasing_fades_up_from_the_current_weight() -> None:
    p = playbacks()
    runtime = p.runtimes[PB]
    p.trigger(PB, 0.0)
    p.release(PB, 2.0)  # weight 1 → 0 over 1 s
    assert weights(runtime, 2.5)[0] == 0.5
    p.trigger(PB, 2.5)  # back up over the 2 s fade-in, from 0.5
    assert weights(runtime, 3.5)[0] == 0.75
    assert weights(runtime, 4.5)[0] == 1.0


def test_slots_fade_in_along_the_cues_curve() -> None:
    """Phase 4: an activation fades each slot in with the cue's curve (here
    easeIn, t²), not just linearly."""
    doc = rig()
    doc["cueLists"][0]["cues"][0]["timing"]["curve"] = "easeIn"
    p = playbacks(doc)
    p.trigger(PB, 0.0)
    htp, _, ltp = weights(p.runtimes[PB], FADE_IN / 2)
    assert (htp, ltp) == (pytest.approx(0.25), pytest.approx(0.25))
    htp, _, ltp = weights(p.runtimes[PB], FADE_IN)
    assert (htp, ltp) == (1.0, 1.0)
    assert p.runtimes[PB].main.whole.htpWeights is None  # settled: the fast path
