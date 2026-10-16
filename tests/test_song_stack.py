"""The Phase 4 done criterion (phase-4-plan §5.15, step 19): a song as a
tracking cue stack and a BPM-locked chase, built with console commands only
on the show ``examples/phase3-build.busk`` saved, then played.

The build runs both scripts against a session and a real engine on a fake
clock, with counter ids, a fixed wall clock and a fixed installation CID, so
the saved show is deterministic. The performance runs the §5.15 timeline on a
fresh :class:`Harness` built from the saved file, ticking at 100 Hz plus the
checkpoint times (the speed master counts beats from the first tick, t = 0).
Each checkpoint's logical values were computed by hand from the cue data;
the DMX frames are compared with ``tests/golden/phase4_frames.json``, which
was reviewed against those values. Regenerate the goldens with
``BUSK_REGOLDEN=1`` after a deliberate change, then review the diff.

Washes are the four ML-56s (fixtures 201–204, group 2), heads the two spots
(101–102, group 1; the Audience preset puts MH 1 at pan −30°, tilt 40°) and
the bar the PiX (301, group 3, 12 cells).
"""

from __future__ import annotations

import json
import os
import random
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from builders import ROOT, lanes_of
from busk.cli import status_line
from busk.commands.types import Command
from busk.compiler.compile import CompiledShow, compile_show
from busk.console.console import Console
from busk.engine.clock import FakeClock
from busk.engine.loop import Engine
from busk.model.common import FixtureId, TargetRef
from busk.model.show import Show
from busk.model.validate import validate_show
from busk.persistence.paths import installation_cid
from busk.persistence.show_file import load_show, new_show, read_show_bytes
from busk.session.ids import CounterIds
from busk.session.library import ProfileLibrary
from busk.session.session import Session
from harness import Harness, Observation, Script

BUILD = ROOT / "examples" / "phase3-build.busk"
SONG = ROOT / "examples" / "phase4-song.busk"
GOLDEN = Path(__file__).parent / "golden"
NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)
CID = "0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f"
REGOLDEN = os.environ.get("BUSK_REGOLDEN") == "1"
END = 81.0  # the performance ends after the last checkpoint
HUNDRED_HZ = [k / 100 for k in range(int(END * 100) + 1)]


class Song:
    """``busk new``, the Phase 3 build and the song script, on a session with
    an engine."""

    def __init__(self, tmp_path: Path) -> None:
        state = tmp_path / "state"
        state.mkdir()
        (state / "cid").write_text(CID + "\n")  # an installation with a known CID
        ids = CounterIds()
        template = new_show("Club Night", ids=ids, now=NOW, cid=installation_cid(state))
        self.path = tmp_path / "club.show"
        compiled = compile_show(template)
        self.engine = Engine(compiled, FakeClock())
        self.session = Session(
            template,
            self.engine.bus,
            compiled=compiled,
            path=self.path,
            ids=ids,
            wall_clock=lambda: NOW,
        )
        console = Console(self.session, ProfileLibrary())
        self.output: list[str] = []
        self.built = console.run_script(BUILD, self.output.append)
        self.songOutput: list[str] = []
        self.ok = console.run_script(SONG, self.songOutput.append)


@pytest.fixture(scope="module")
def song(tmp_path_factory: pytest.TempPathFactory) -> Song:
    return Song(tmp_path_factory.mktemp("song"))


def golden(name: str, actual: Any) -> Any:
    path = GOLDEN / name
    if REGOLDEN:
        path.write_text(json.dumps(actual, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def channels(universe: bytes) -> dict[str, int]:
    """Non-zero channels, 1-based (JSON keys are strings)."""
    return {str(k + 1): value for k, value in enumerate(universe) if value}


# ---------------------------------------------------------------- the build


def test_every_line_of_both_scripts_succeeds(song: Song) -> None:
    assert song.built, song.output
    assert song.ok, song.songOutput
    assert song.songOutput[-1] == f"saved {song.path}"
    # Tracking-aware recording (decision 17): the Verse stores no wash values,
    # the Chorus none for the bar, which the Pre already holds at full.
    assert "recorded cue 9/2: 4 entries; 8 values tracked from cue 9/1" in song.songOutput
    assert "recorded cue 9/4: 3 entries; 12 values tracked from cue 9/3" in song.songOutput


def test_the_saved_show_matches_the_golden_and_validates(song: Song) -> None:
    saved = json.loads(read_show_bytes(song.path))
    assert saved == golden("phase4_song_show.json", saved)
    show, issues = validate_show(read_show_bytes(song.path))
    assert show is not None
    assert issues == []
    stack = next(cl for cl in saved["cueLists"] if cl["number"] == 9)
    assert stack["tracking"] is True
    assert [cue["name"] for cue in stack["cues"]] == ["Intro", "Verse", "Pre", "Chorus", "Outro"]
    verse, pre, outro = stack["cues"][1], stack["cues"][2], stack["cues"][4]
    assert verse["timing"]["perFamily"] == {"position": {"fade": 4.0, "delay": 0.0}}
    assert (pre["trigger"], outro["trigger"]) == (
        {"kind": "wait", "delay": 8.0},
        {"kind": "follow", "delay": 4.0},
    )
    assert outro["releases"][0]["attributes"] == ["pan", "tilt"]
    chase = next(cl for cl in saved["cueLists"] if cl["number"] == 10)
    speed = next(m for m in saved["masters"] if m["kind"] == "speed")
    assert chase["mode"] == "chase"
    assert chase["chase"] == {
        "rate": {"kind": "bpm", "masterId": speed["id"], "multiplier": 1.0},
        "direction": "bounce",
        "crossfade": 0.25,
    }


# ---------------------------------------------------------- the performance


@dataclass(frozen=True)
class Stage:
    """Ids of the saved show the performance drives and reads."""

    show: Show
    compiled: CompiledShow

    def playback(self, number: int) -> str:
        return next(p["id"] for p in self.show["playbacks"] if p["number"] == number)

    def fixture(self, number: int) -> str:
        return next(f["id"] for f in self.show["fixtures"] if f["number"] == number)

    @property
    def speed(self) -> str:
        return next(m["id"] for m in self.show["masters"] if m["kind"] == "speed")

    def lanes(self, seen: Observation, number: int, attribute: str) -> list[float]:
        return lanes_of(self.compiled, seen.logical, self.fixture(number), attribute)

    def cell(self, seen: Observation, number: int, attribute: str, element: int) -> float:
        target = TargetRef(fixtureId=FixtureId(self.fixture(number)), element=element)
        found = self.compiled.slots.find(target, attribute)
        assert found is not None
        return float(seen.logical[found.lanes][0])

    def cue(self, seen: Observation, number: int) -> str | None:
        """The current cue number of playback ``number``; ``None`` when idle."""
        assert seen.snapshot is not None
        ident = self.playback(number)
        return next(p.cue for p in seen.snapshot.playbacks if p.id == ident)


def stage_of(show: Show) -> Stage:
    return Stage(show, compile_show(show))


def timeline(stage: Stage, *, goto: bool = False, multiplier: bool = True) -> Script:
    """The §5.15 performance: the song (GO, BACK, release), then the chase,
    four taps at 128 BPM and the multiplier knob at ×2. With ``goto`` only
    the song's fader and a ``goto 9 4`` at t = 1."""
    song, chase, speed = stage.playback(9), stage.playback(10), stage.speed

    def command(**fields: Any) -> Command:
        return cast(Command, fields)

    fader = command(type="SET_FADER", playbackId=song, level=1.0)
    if goto:
        return [(0.0, fader), (1.0, command(type="GOTO", playbackId=song, cueNumber="4"))]
    go = command(type="GO", playbackId=song)
    tap = command(type="TAP", masterId=speed)
    script: list[tuple[float, Command]] = [
        (0.0, fader),
        (10.0, go),
        (25.0, go),
        (40.0, command(type="BACK", playbackId=song)),
        (50.0, command(type="RELEASE_PLAYBACK", playbackId=song)),
        (60.0, command(type="SET_FADER", playbackId=chase, level=1.0)),
        *((t, tap) for t in (70.0, 70.46875, 70.9375, 71.40625)),
    ]
    if multiplier:
        script.append((80.0, command(type="SET_MASTER", masterId=speed, level=0.75)))
    return script


@dataclass(frozen=True)
class Checkpoint:
    """What §5.15 expects at ``time``: wash intensities (201–204), head
    intensities (101–102), the bar's first cell, wash 201's colour, MH 1's
    pan and tilt, and the current cue of the song (9) and the chase (10).
    ``None`` is not checked; a cue of ``""`` means idle."""

    time: float
    what: str
    washes: tuple[float, float, float, float] | None = None
    heads: tuple[float, float] | None = None
    bar: float | None = None
    washColor: tuple[float, float, float] | None = None
    mh1: tuple[float, float] | None = None
    song: str | None = None
    chase: str | None = None


def washes(level: float) -> tuple[float, float, float, float]:
    return (level, level, level, level)


CHECKPOINTS = [
    # Intro: 0 → 0.6 over 3 s eased: smoothstep(0.25) = 0.15625; colour from white.
    Checkpoint(0.75, "Intro eases in", washes(0.09375), washColor=(0.84375, 0.84375, 1.0),
               song="1"),
    Checkpoint(1.5, "Intro halfway", washes(0.3), (0.0, 0.0), washColor=(0.5, 0.5, 1.0)),
    Checkpoint(10.0, "GO: Verse; the washes do not move", washes(0.6), (0.0, 0.0), song="2"),
    # Heads 0 → 0.7 over 2 s; position over 4 s from the default (0°, 0°).
    Checkpoint(11.0, "Verse: heads and position fading", washes(0.6), (0.35, 0.35),
               mh1=(-7.5, 10.0)),
    Checkpoint(17.99, "Pre not yet", song="2"),
    Checkpoint(18.0, "Pre fires by itself (wait 8 after 10)", song="3"),
    # Bar 0 → 1 rising over 1 s; washes 0.6 → 0.3 falling over 3 s.
    Checkpoint(18.5, "Pre: bar up fast, washes down slowly", washes(0.55), (0.7, 0.7), 0.5,
               mh1=(-30.0, 40.0)),
    Checkpoint(25.25, "GO: Chorus halfway (0.5 s in)", washes(0.65), (0.85, 0.85), 1.0,
               (0.5, 0.5, 1.0), song="4"),
    Checkpoint(25.5, "Chorus lands", washes(1.0), (1.0, 1.0), 1.0, (1.0, 1.0, 1.0)),
    Checkpoint(29.49, "Outro not yet", song="4"),
    Checkpoint(29.5, "Outro follows 4 s after the Chorus landed", song="5"),
    # Heads 1 → 0.2 over 6 s; pan and tilt released to the default over 6 s.
    Checkpoint(32.5, "Outro: heads dim, position released", washes(1.0), (0.6, 0.6),
               mh1=(-15.0, 20.0)),
    Checkpoint(40.25, "BACK: Chorus with its own 0.5 s", washes(1.0), (0.6, 0.6),
               mh1=(-15.0, 20.0), song="4"),
    Checkpoint(41.0, "Chorus again", (1.0, 1.0, 1.0, 1.0), (1.0, 1.0), mh1=(-30.0, 40.0)),
    Checkpoint(49.99, "nothing fires after BACK", song="4"),
    Checkpoint(51.5, "release over 3 s: halfway", washes(0.5), (0.5, 0.5), 0.5),
    Checkpoint(53.01, "released", washes(0.0), (0.0, 0.0), 0.0, song=""),
    # Chase: ×1 on 120 BPM, a step per beat (0.5 s), crossfade 0.125 s.
    Checkpoint(60.0, "chase starts on beat 120", washes(0.0), chase="1"),
    Checkpoint(60.0625, "wash 201 fading in", (0.5, 0.0, 0.0, 0.0), washColor=(1.0, 0.5, 0.5)),
    Checkpoint(60.5625, "crossfade 201 → 202 halfway", (0.5, 0.5, 0.0, 0.0), chase="2"),
    Checkpoint(61.7, "steps at 60.5, 61, 61.5", (0.0, 0.0, 0.0, 1.0), chase="4"),
    Checkpoint(62.2, "bounce", (0.0, 0.0, 1.0, 0.0), chase="3"),
    # Taps at 128 BPM (0.46875 s apart): the chase steps on the second tap,
    # 0.03 s ahead of its 120 BPM grid (70.5), then on every tap.
    Checkpoint(70.46, "before the second tap", chase="3"),
    Checkpoint(70.46875, "second tap: a step", chase="4"),
    Checkpoint(70.9375, "third tap", chase="3"),
    Checkpoint(71.40625, "fourth tap", chase="2"),
    Checkpoint(71.87, "not before the 128 BPM grid", (0.0, 1.0, 0.0, 0.0), chase="2"),
    Checkpoint(71.875, "on the grid", (0.0, 1.0, 0.0, 0.0), chase="1"),
    Checkpoint(72.34, "not before the grid", (1.0, 0.0, 0.0, 0.0), chase="1"),
    Checkpoint(72.34375, "on the grid", (1.0, 0.0, 0.0, 0.0), chase="2"),
    # ×2 at 80: no step then; steps at 80.078125 (beat 161.5), then every 0.234375 s.
    Checkpoint(80.0, "×2: no step", (0.0, 1.0, 0.0, 0.0), chase="2"),
    Checkpoint(80.07, "not yet", chase="2"),
    Checkpoint(80.078125, "a half beat", chase="1"),
    Checkpoint(80.3125, "the next", (1.0, 0.0, 0.0, 0.0), chase="2"),
]  # fmt: skip


def perform(
    stage: Stage, script: Script, ticks: Iterable[float] = HUNDRED_HZ
) -> dict[float, Observation]:
    """Run ``script`` on a fresh engine, ticking at ``ticks`` and at every
    checkpoint and command time."""
    return Harness(stage.compiled).run(script, [*ticks, *(c.time for c in CHECKPOINTS)])


@pytest.fixture(scope="module")
def stage(song: Song) -> Stage:
    loaded, warnings = load_show(song.path)
    assert warnings == []
    return stage_of(loaded)


@pytest.fixture(scope="module")
def run(stage: Stage) -> dict[float, Observation]:
    return perform(stage, timeline(stage))


@pytest.mark.parametrize("point", CHECKPOINTS, ids=lambda c: f"{c.time:g} {c.what}")
def test_the_checkpoints_hold(
    stage: Stage, run: dict[float, Observation], point: Checkpoint
) -> None:
    seen = run[point.time]
    if point.washes is not None:
        levels = [stage.lanes(seen, n, "intensity")[0] for n in (201, 202, 203, 204)]
        assert levels == pytest.approx(point.washes)
    if point.heads is not None:
        levels = [stage.lanes(seen, n, "intensity")[0] for n in (101, 102)]
        assert levels == pytest.approx(point.heads)
    if point.bar is not None:
        assert stage.cell(seen, 301, "intensity", 0) == pytest.approx(point.bar)
    if point.washColor is not None:
        assert stage.lanes(seen, 201, "color")[:3] == pytest.approx(point.washColor)
    if point.mh1 is not None:
        position = stage.lanes(seen, 101, "pan") + stage.lanes(seen, 101, "tilt")
        assert position == pytest.approx(point.mh1)
    if point.song is not None:
        assert stage.cue(seen, 9) == (point.song or None)
    if point.chase is not None:
        assert stage.cue(seen, 10) == (point.chase or None)


def test_the_checkpoint_frames_match_the_golden(run: dict[float, Observation]) -> None:
    frames = {f"{c.time:g}": channels(run[c.time].universe) for c in CHECKPOINTS}
    assert frames == golden("phase4_frames.json", frames)
    # Reviewed by hand. Spot 1 from 1: 16-bit pan (540°) and tilt (270°), RGBW,
    # 16-bit dimmer, zoom, gobo, shutter. The ML-56s (4-channel, from 33) are
    # RGBW with a virtual dimmer; RGBW "derive" sends the common white to W.
    # The PiX's 12 RGB cells start at 49.
    chorus = run[25.5].universe
    pan, tilt = round((0.5 - 30 / 540) * 65535), round((0.5 + 40 / 270) * 65535)
    assert chorus[0:4] == bytes([pan >> 8, pan & 255, tilt >> 8, tilt & 255])  # Audience
    assert chorus[4:10] == bytes([0, 0, 0, 255, 255, 255])  # white on W, dimmer at full
    assert chorus[32:48] == bytes([0, 0, 0, 255] * 4)
    assert chorus[48:84] == bytes([255] * 36)
    pre = run[18.5].universe
    assert pre[4:10] == bytes([140, 76, 0, 115, 179, 50])  # (1, .75, .45): W .45; dimmer .7
    assert pre[32:48] == bytes([0, 0, 140, 0] * 4)  # blue × 0.55
    assert pre[48:84] == bytes([128, 96, 64] * 12)  # white → amber halfway, × 0.5
    assert run[60.0625].universe[32:36] == bytes([64, 0, 0, 64])  # (1, .5, .5) × 0.5
    assert run[61.7].universe[32:48] == bytes([0] * 12 + [255, 0, 0, 0])  # 204 alone, red


def test_the_status_line_shows_the_tempo_and_the_cue(run: dict[float, Observation]) -> None:
    pre, doubled = run[18.5].snapshot, run[80.0].snapshot
    assert pre is not None
    assert doubled is not None
    assert "Speed 1 120 BPM ×1" in status_line(pre)
    assert "9 Song on 3 Pre 1.00" in status_line(pre)
    assert "Speed 1 128 BPM ×2" in status_line(doubled)


def test_a_multiplier_change_does_not_step_the_chase(
    stage: Stage, run: dict[float, Observation]
) -> None:
    unchanged = perform(stage, timeline(stage, multiplier=False), [t for t in HUNDRED_HZ if t > 75])
    assert unchanged[80.0].universe == run[80.0].universe
    assert unchanged[80.1].universe != run[80.1].universe  # ×2 crossfades from 80.078125
    assert stage.cue(unchanged[80.078125], 10) == "2"  # ×1 steps on the beat at 80.3125
    assert stage.cue(unchanged[80.3125], 10) == "1"


def test_goto_equals_stepping(stage: Stage, run: dict[float, Observation]) -> None:
    """``goto 9 4`` at t = 1 lands on the Chorus the GOs reached at 25.5 (the
    Outro follows 4 s after the Chorus lands: at 5.5 here, 29.5 there)."""
    jumped = perform(stage, timeline(stage, goto=True), [t for t in HUNDRED_HZ if t <= 5.0])
    assert stage.cue(jumped[5.0], 9) == "4"
    assert np.array_equal(jumped[5.0].logical, run[28.0].logical, equal_nan=True)
    assert jumped[5.0].universe == run[28.0].universe


def test_an_irregular_schedule_gives_the_same_frames(
    stage: Stage, run: dict[float, Observation]
) -> None:
    generator = random.Random(4)
    ticks, now = [], 0.0
    while now < END:
        ticks.append(now)
        now += generator.uniform(0.001, 0.06)
    irregular = perform(stage, timeline(stage), ticks)
    for point in CHECKPOINTS:
        assert irregular[point.time].universe == run[point.time].universe, point.time
        assert np.array_equal(
            irregular[point.time].logical, run[point.time].logical, equal_nan=True
        ), point.time


def test_save_load_and_a_fresh_engine_give_the_same_frames(
    song: Song, stage: Stage, run: dict[float, Observation]
) -> None:
    assert stage.show == song.session.show
    in_memory = stage_of(song.session.show)
    fresh = perform(in_memory, timeline(in_memory))
    for point in CHECKPOINTS:
        assert fresh[point.time].universe == run[point.time].universe, point.time
