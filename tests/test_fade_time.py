"""Fade-time masters (phase-6-plan §5.5, decision 12).

While a fade-time master is up, every playback transition that *starts*
takes ``T = 10 s × level²`` instead of its programmed timing: every slot
fades over ``T`` with no delay and the cue's in curve, effects enter and
leave over it (``sizeFadeIn`` still applies), and releases that name no time
take it instead of ``releaseTime``.

Most tests compare two engines. The *timed* rig programs varied timing
(delays, per-family times, out times, release times); its *twin* programs
every cue and release as ``T`` with no delay. Under the override the timed
rig must play exactly like the twin. Chases, flashes, live edits and fades
already running must play exactly as without the override.
"""

from __future__ import annotations

import copy
from typing import Any, cast

import numpy as np
import pytest

from builders import busk_rig, compile_doc, cue, cue_list, entry, literal, playback, rgb, targets
from busk.cli import status_line
from busk.commands.types import Command
from busk.compiler.compile import CompiledShow
from busk.compiler.playbacks import compile_masters
from busk.engine.install import EMPTY_FRAME, Install
from busk.engine.masters import fade_override
from busk.model.common import MasterId
from busk.model.show import Show
from harness import Harness, Script, back, fader, flash, go, goto, master, release, toggle, trigger

T = 2.5  # the fade master at 0.5
FADE = {"id": "m-fade", "kind": "fadeTime", "name": "Fade"}
FADE_2 = {"id": "m-fade2", "kind": "fadeTime", "name": "Fade 2"}

# ---------------------------------------------------------------- the rigs


def _timing(fade_in: float, delay_in: float, fade_out: float, delay_out: float) -> dict[str, Any]:
    return {
        "fadeIn": fade_in,
        "delayIn": delay_in,
        "fadeOut": fade_out,
        "delayOut": delay_out,
    }


def _instance(ident: str, fixture: str, mode: str, fade_in: float | None) -> dict[str, Any]:
    instance = {
        "id": ident,
        "templateId": f"t-{mode}",
        "targets": targets(fixture),
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


def rig(uniform: float | None = None) -> dict[str, Any]:
    """The timed rig, or with ``uniform`` its twin: every cue timed ``uniform``
    in and out with no delay and no per-family times, and every release
    time ``uniform``.

    * pb-seq (MH 1) plays three cues: GO, BACK and GOTO; cue 3 follows cue
      2 after 0.5 s (an auto-GO), and GO past it releases (``releaseAtEnd``);
    * pb-x1 and pb-x2 (MH 2) are exclusive;
    * pb-fx (MH 3, MH 4) runs an effect with ``sizeFadeIn`` and one without;
    * pb-chase (MH 5) is a chase with a 0.25 s cross-fade.
    """
    doc = busk_rig(spots=5)
    doc["masters"] += [copy.deepcopy(FADE), copy.deepcopy(FADE_2)]
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

    def timed(cue_doc: dict[str, Any], timing: dict[str, Any], **extra: Any) -> dict[str, Any]:
        if uniform is None:
            cue_doc["timing"].update(timing, **extra)
        else:
            cue_doc["timing"].update(_timing(uniform, 0.0, uniform, 0.0))
        return cue_doc

    def mh(k: int, level: float, color: tuple[float, float, float] | None = None) -> list[Any]:
        values = [entry(targets(f"fx-mh{k}"), "intensity", literal(level))]
        if color is not None:
            values.append(entry(targets(f"fx-mh{k}"), "color", literal(rgb(*color))))
        return values

    color_late = {"color": {"fade": 7.0, "delay": 2.0}}
    seq = cue_list(
        "cl-seq",
        1,
        timed(cue("c1", *mh(1, 0.5, (1, 0, 0)), number="1"), _timing(4, 1, 3, 0.5),
              perFamily=color_late),
        timed(cue("c2", *mh(1, 1.0, (0, 0, 1)), number="2", curve="easeIn"), _timing(6, 0.5, 2, 0)),
        timed(cue("c3", *mh(1, 0.2, (0, 1, 0)), number="3"), _timing(1, 0, 5, 1)),
        release_at_end=True,
    )  # fmt: skip
    seq["cues"][2]["trigger"] = {"kind": "follow", "delay": 0.5}
    x1 = cue_list("cl-x1", 2, timed(cue("x1", *mh(2, 0.6)), _timing(3, 1, 3, 1)))
    x2 = cue_list("cl-x2", 3, timed(cue("x2", *mh(2, 0.9, (0, 1, 1))), _timing(3, 1, 3, 1)))
    fx = cue_list("cl-fx", 4, timed(cue("fx", *mh(3, 0.5)), _timing(5, 0, 2, 0)))
    fx["cues"][0]["effects"] = [
        _instance("e-slow", "fx-mh3", "add", 1.5),
        _instance("e-plain", "fx-mh4", "absolute", None),
    ]
    chase = cue_list(
        "cl-chase",
        5,
        *(cue(f"s{k}", *mh(5, 0.25 * k), number=str(k), fade_in=7.0) for k in (1, 2, 3)),
    )
    chase.update(
        mode="chase", chase={"rate": {"kind": "hz", "value": 2}, "direction": "forward",
                             "crossfade": 0.25}
    )  # fmt: skip
    doc["cueLists"] += [seq, x1, x2, fx, chase]
    release_time = 4.0 if uniform is None else uniform
    unscaled: dict[str, Any] = {"fader": "none", "release_time": release_time}  # full intensity
    buttons = ("go", "flash", "release")
    doc["playbacks"] += [
        playback("pb-seq", 1, "cl-seq", **unscaled, buttons=buttons),
        playback("pb-x1", 2, "cl-x1", **unscaled, exclusivity="wash"),
        playback("pb-x2", 3, "cl-x2", **unscaled, exclusivity="wash"),
        playback("pb-fx", 4, "cl-fx", fader="size", release_time=release_time),
        playback("pb-chase", 5, "cl-chase", fader="none", release_time=release_time),
    ]
    return doc


@pytest.fixture(scope="module")
def timed() -> CompiledShow:
    return compile_doc(rig())


@pytest.fixture(scope="module")
def twin() -> CompiledShow:
    return compile_doc(rig(uniform=T))


def _command(**fields: Any) -> Command:
    return cast(Command, fields)


TICKS = [round(0.05 * k, 2) for k in range(401)]  # 0 … 20 s

# Every kind of transition the override replaces, on every playback but the chase.
SCRIPT: Script = [
    (0.1, go("pb-seq")),  # activation at cue 1
    (0.2, fader("pb-fx", 1.0)),  # activation by fader: the effects enter
    (1.0, trigger("pb-x1")),
    (3.0, go("pb-seq")),  # cue 2; cue 3 follows 0.5 s after it completes
    (4.0, trigger("pb-x2")),  # exclusivity releases pb-x1
    (7.0, back("pb-seq")),
    (8.0, goto("pb-seq", "1")),
    (9.0, release("pb-fx")),  # the effects leave
    (10.0, toggle("pb-x2")),
    (11.0, go("pb-seq")),
    (16.0, go("pb-seq")),  # past the end: releaseAtEnd
    (16.5, fader("pb-fx", 0.0)),
    (17.0, fader("pb-fx", 1.0)),
    (18.0, fader("pb-fx", 0.0)),  # autoRelease
]


def play(show: CompiledShow, script: Script, *, levels: dict[str, float] | None = None) -> Any:
    """The logical frames of ``script`` (after the fade masters' ``levels`` at
    t = 0), by tick."""
    setup: Script = [(0.0, master(ident, level)) for ident, level in (levels or {}).items()]
    observed = Harness(show).run([*setup, *script], TICKS)
    return np.array([observed[t].logical for t in TICKS])


def test_the_override_replaces_every_programmed_timing(
    timed: CompiledShow, twin: CompiledShow
) -> None:
    """GO, BACK, GOTO, an auto-GO, an activation by fader, a release by
    command, by toggle, by exclusivity, past the end and by ``autoRelease``;
    delays and per-family times; effects entering and leaving, with
    ``sizeFadeIn`` kept."""
    overridden = play(timed, SCRIPT, levels={"m-fade": 0.5})
    np.testing.assert_allclose(overridden, play(twin, SCRIPT), rtol=0, atol=1e-12)
    # Not vacuous: without the override the timed rig plays differently.
    assert not np.allclose(play(timed, SCRIPT), overridden)


def test_the_largest_of_two_masters_applies(timed: CompiledShow, twin: CompiledShow) -> None:
    overridden = play(timed, SCRIPT, levels={"m-fade": 0.3, "m-fade2": 0.5})
    np.testing.assert_allclose(overridden, play(twin, SCRIPT), rtol=0, atol=1e-12)


def test_level_0_means_programmed_times(timed: CompiledShow) -> None:
    script: Script = [(0.05, master("m-fade", 0.0)), *SCRIPT]
    lowered = play(timed, script, levels={"m-fade": 0.8, "m-fade2": 0.0})
    np.testing.assert_array_equal(lowered, play(timed, SCRIPT))


def test_an_explicit_release_time_wins(timed: CompiledShow, twin: CompiledShow) -> None:
    script: Script = [
        (0.1, trigger("pb-x1")),
        (3.0, release("pb-x1", 0.5)),
        (5.0, go("pb-seq")),
        (9.0, release("pb-seq", 6.0)),
    ]
    overridden = play(timed, script, levels={"m-fade": 0.5})
    np.testing.assert_allclose(overridden, play(twin, script), rtol=0, atol=1e-12)


def test_chases_and_flashes_keep_their_timing(timed: CompiledShow) -> None:
    script: Script = [
        (0.1, trigger("pb-chase")),  # its steps cross-fade over 0.25 s regardless
        (1.0, flash("pb-x1", True)),  # a flash is instant
        (1.5, flash("pb-x1", False)),
        (2.0, flash("pb-seq", True)),
        (2.2, flash("pb-seq", False)),
        (6.0, go("pb-chase")),  # a manual step keeps the grid's cross-fade
        (8.0, release("pb-chase", 0.0)),
    ]
    np.testing.assert_array_equal(play(timed, script, levels={"m-fade": 0.5}), play(timed, script))


def test_running_fades_are_not_changed_when_the_level_moves(timed: CompiledShow) -> None:
    script: Script = [
        (0.1, go("pb-seq")),
        (0.2, trigger("pb-x1")),
        (0.3, release("pb-x1")),  # a release fading over 2.5 s
    ]
    steady = play(timed, script, levels={"m-fade": 0.5})
    for level in (1.0, 0.0, 0.1):
        moved = play(timed, [*script, (1.0, master("m-fade", level))], levels={"m-fade": 0.5})
        np.testing.assert_array_equal(moved, steady)


def test_an_auto_go_reads_the_override_when_it_fires(timed: CompiledShow) -> None:
    """Cue 2 fades in over 2.5 s (completing at 5.5); the master drops to 0
    before cue 3's auto-GO at 6.0, so cue 3 takes its own timing."""
    script: Script = [(0.1, go("pb-seq")), (3.0, go("pb-seq")), (5.8, master("m-fade", 0.0))]
    harness = Harness(timed)
    harness.run([(0.0, master("m-fade", 0.5)), *script], [0.0, 5.9, 6.0])
    runtime = harness.engine.runtime.playbacks.runtimes[cast(Any, "pb-seq")]
    assert runtime.cue == 2
    assert (runtime.started, runtime.completes) == (6.0, 12.0)  # fadeOut 5 + delayOut 1


def test_live_edits_keep_their_own_timing(timed: CompiledShow) -> None:
    """A live edit retargets running cues and effects with their programmed timing."""
    doc = rig()
    doc["cueLists"][0]["cues"][0]["entries"][0]["value"] = literal(0.9)
    doc["cueLists"][3]["cues"][0]["effects"][1]["size"] = 0.6  # e-plain changes: 5 s in
    edited = compile_doc(doc)

    def run(levels: dict[str, float]) -> Any:
        harness = Harness(timed)
        frames = []
        for ident, level in levels.items():
            harness.submit(master(ident, level))
        harness.submit(go("pb-seq"), fader("pb-fx", 1.0))
        harness.tick(0.0)
        harness.tick(20.0)  # settled, with or without the override
        harness.engine.bus.install(Install(compiled=edited, remap=None, programmer=EMPTY_FRAME))
        for k in range(1, 200):
            frames.append(harness.tick(20.0 + 0.05 * k).logical)
        return np.array(frames)

    np.testing.assert_array_equal(run({"m-fade": 0.0}), run({"m-fade": 0.5}))


# -------------------------------------------------------------- the masters


@pytest.mark.parametrize(
    ("levels", "expected"),
    [
        ({}, None),
        ({"m-fade": 0.0, "m-fade2": 0.0}, None),
        ({"m-fade": 0.3}, 0.9),
        ({"m-fade": 0.5}, 2.5),
        ({"m-fade": 1.0}, 10.0),
        ({"m-fade": 0.3, "m-fade2": 0.5}, 2.5),
        ({"m-gm": 1.0}, None),  # only fade-time masters count
    ],
)
def test_fade_override(timed: CompiledShow, levels: dict[str, float], expected: float) -> None:
    found = fade_override(timed.masters, {MasterId(k): v for k, v in levels.items()})
    assert found == pytest.approx(expected)


def test_fade_time_masters_start_at_0_unless_the_show_says(timed: CompiledShow) -> None:
    assert timed.masters[MasterId("m-fade")].initialLevel == 0.0
    doc = rig()
    doc["masters"][-1]["initialLevel"] = 0.5
    masters = compile_masters(cast(Show, doc), timed.slots)
    assert masters[MasterId("m-fade2")].initialLevel == 0.5
    harness = Harness(compile_doc(doc))
    snapshot = harness.tick(0.0).snapshot
    assert snapshot is not None
    assert snapshot.fadeTime == pytest.approx(2.5)  # an initial level counts from the start


def test_the_snapshot_and_status_line_show_the_fade_time(timed: CompiledShow) -> None:
    harness = Harness(timed)
    first = harness.tick(0.0).snapshot
    assert first is not None
    assert first.fadeTime is None
    assert dict(first.masterLevels)[MasterId("m-fade")] == 0.0
    assert "Fade" not in status_line(first)
    harness.submit(master("m-fade", 0.5))
    second = harness.tick(0.1).snapshot
    assert second is not None
    assert second.fadeTime == 2.5
    assert dict(second.masterLevels)[MasterId("m-fade")] == 0.5
    assert status_line(second) == "GM 100% | BO off | Fade 2.5 s"
    harness.submit(master("m-fade", 64 / 127))  # a MIDI CC at 64
    third = harness.tick(0.2).snapshot
    assert third is not None
    assert status_line(third).endswith("| Fade 2.5 s")  # 2.5397…, rounded


def test_a_live_edit_keeps_the_levels_and_recomputes_the_override(timed: CompiledShow) -> None:
    harness = Harness(timed)
    harness.submit(master("m-fade", 0.3), master("m-fade2", 0.5))
    harness.tick(0.0)
    doc = rig()
    doc["masters"] = [m for m in doc["masters"] if m["id"] != "m-fade2"]
    harness.engine.bus.install(
        Install(compiled=compile_doc(doc), remap=None, programmer=EMPTY_FRAME)
    )
    snapshot = harness.tick(0.1).snapshot
    assert snapshot is not None
    assert harness.engine.runtime.fadeLevels == {"m-fade": 0.3}
    assert snapshot.fadeTime == pytest.approx(0.9)  # the deleted master no longer counts
