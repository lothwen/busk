"""The Phase 5 done criterion (phase-5-plan §5.14, step 17): effects added to
the song show with console commands only, on the show that
``tests/fixtures/phase3-build.busk`` and ``tests/fixtures/phase4-song.busk`` saved, then
played.

The build runs the three scripts against a session and a real engine on a
fake clock, with counter ids, a fixed wall clock and a fixed installation
CID, so the saved show is deterministic. The performance runs the §5.14
timeline on a fresh :class:`Harness` built from the saved file, ticking at
100 Hz plus the checkpoint times. "Speed 1" starts at 120 BPM on the first
tick (t = 0), so beats = 2t until the taps. Each checkpoint's logical values
were computed by hand from the effect data; the DMX frames are compared with
``tests/golden/phase5_frames.json``, which was reviewed against those
values. Regenerate the goldens with ``BUSK_REGOLDEN=1`` after a deliberate
change, then review the diff.

What the hand computations use (§5.1, §5.2): ``sine`` is
``w = 0.5 − 0.5·cos(2πp)`` at ``p = P + offset``; an ``add`` layer adds
``size·d·(2w − 1)``, a ``multiply`` layer scales by ``1 − size·d·(1 − w)``,
an ``absolute`` one sets ``lerp(low, high, w)``; ``d`` is the fader (a
``size`` fader) times the size master "FX" times the presence.

- Heads are the two spots (101–102, group 1). The Audience preset (slot 6,
  2 s, ``followFader``) puts MH 1 at pan −30°, tilt 40° and MH 2 at +30°, 40°.
  The circle (slot 11, size 15°, ×0.5: ``P = t``) offsets MH 2 a quarter
  cycle, and its tilt layer a quarter cycle from its pan layer.
- Washes are the four ML-56s (201–204, group 2), under Warm (slot 1, 0.8).
  The pulse (slot 12, size 0.8, ×1) offsets them 0, ¼, ½, ¾ of a cycle.
- The bar is the PiX (301, group 3, 12 cells). The wave (slot 13, ×1,
  0..1) offsets the cells 0 1 2 3 4 5 5 4 3 2 1 0 sixths of a cycle (wings
  2); the Chorus's colour cycle (0.25 Hz, red, green, blue) offsets them
  twelfths.
"""

from __future__ import annotations

import json
import os
import random
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from builders import ROOT, lanes_of
from busk.cli import main
from busk.commands.types import Command
from busk.compiler.compile import CompiledShow, compile_show
from busk.console.console import Console
from busk.engine.clock import FakeClock
from busk.engine.effects import EffectClock
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
from session_harness import CLEAR, Live, put, sel

SCRIPTS = [ROOT / "tests" / "fixtures" / name for name in ("phase3-build.busk", "phase4-song.busk")]
EFFECTS = ROOT / "tests" / "fixtures" / "phase5-effects.busk"
GOLDEN = Path(__file__).parent / "golden"
NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)
CID = "0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f"
REGOLDEN = os.environ.get("BUSK_REGOLDEN") == "1"
END = 29.0  # the performance ends after the last checkpoint
HUNDRED_HZ = [k / 100 for k in range(int(END * 100) + 1)]
TAPS = (10.0, 10.46875, 10.9375, 11.40625)  # 128 BPM: 0.46875 s apart


class Build:
    """``busk new``, the Phase 3 build, the song and the effects script, on a
    session with an engine."""

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
        self.earlier = [console.run_script(script, lambda _: None) for script in SCRIPTS]
        self.output: list[str] = []
        self.ok = console.run_script(EFFECTS, self.output.append)


@pytest.fixture(scope="module")
def build(tmp_path_factory: pytest.TempPathFactory) -> Build:
    return Build(tmp_path_factory.mktemp("effects"))


def golden(name: str, actual: Any) -> Any:
    path = GOLDEN / name
    if REGOLDEN:
        path.write_text(json.dumps(actual, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def channels(universe: bytes) -> dict[str, int]:
    """Non-zero channels, 1-based (JSON keys are strings)."""
    return {str(k + 1): value for k, value in enumerate(universe) if value}


# ---------------------------------------------------------------- the build


def test_every_line_of_the_three_scripts_succeeds(build: Build) -> None:
    assert build.earlier == [True, True]
    assert build.ok, build.output
    assert build.output[-1] == f"saved {build.path}"
    # A library template is embedded on first use, by the same line.
    assert "added effect template 'Circle'\nadded effect 'fx1' on 2 targets" in build.output
    assert "recorded slot 11: playback 11 'Circle'" in build.output
    # The merge keeps the Chorus's three entries and adds the cycle.
    assert "recorded cue 9/4: 3 entries, 1 effect" in build.output


def test_the_saved_show_matches_the_golden_and_validates(
    build: Build, capsys: pytest.CaptureFixture[str]
) -> None:
    saved = json.loads(read_show_bytes(build.path))
    assert saved == golden("phase5_effects_show.json", saved)
    show, issues = validate_show(read_show_bytes(build.path))
    assert show is not None
    assert issues == []
    assert main(["validate", str(build.path)]) == 0
    assert capsys.readouterr().out == "0 errors, 0 warnings\n"

    masters = {m["name"]: m for m in saved["masters"]}
    groups = {g["number"]: g["id"] for g in saved["groups"]}
    assert masters["FX"]["kind"] == "size"
    assert masters["Wash level"] == {
        "id": masters["Wash level"]["id"],
        "name": "Wash level",
        "kind": "group",
        "groupId": groups[2],
    }
    assert [t["name"] for t in saved["effects"]] == ["Circle", "Pulse", "Wave", "Rainbow"]
    playbacks = {p["number"]: p for p in saved["playbacks"]}
    lists = {cl["id"]: cl for cl in saved["cueLists"]}
    circle, pulse, wave = (lists[playbacks[n]["cueListId"]]["cues"] for n in (11, 12, 13))
    assert all(playbacks[n]["fader"] == "size" for n in (11, 12, 13))
    assert [len(cues[0]["entries"]) for cues in (circle, pulse, wave)] == [0, 0, 0]
    assert circle[0]["effects"] == [
        {
            "id": "fx1",
            "templateId": "ef-circle",
            "targets": {"kind": "group", "groupId": groups[1]},
            "rate": {"kind": "bpm", "masterId": masters["Speed 1"]["id"], "multiplier": 0.5},
            "direction": "forward",
            "size": 15.0,
            "phase": {"start": 0.0, "end": 180.0},
            "groups": 1,
            "blocks": 1,
            "wings": 1,
            "sizeFadeIn": 1.0,
            "sizeMasterId": masters["FX"]["id"],
        }
    ]
    assert wave[0]["effects"][0]["wings"] == 2
    chorus = lists[playbacks[9]["cueListId"]]["cues"][3]
    assert chorus["name"] == "Chorus"
    assert len(chorus["entries"]) == 3
    assert [(e["id"], e["rate"]) for e in chorus["effects"]] == [
        ("rainbow", {"kind": "hz", "value": 0.25})
    ]
    knobs = {b["input"]["cc"]: b["action"] for b in saved["bindings"]}
    assert (knobs[19], knobs[22]) == (
        {"kind": "playbackFader", "slot": 10},
        {"kind": "master", "masterId": masters["FX"]["id"]},
    )


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

    def master(self, name: str) -> str:
        return next(m["id"] for m in self.show["masters"] if m["name"] == name)

    def lanes(self, seen: Observation, number: int, attribute: str) -> list[float]:
        return lanes_of(self.compiled, seen.logical, self.fixture(number), attribute)

    def cell(self, seen: Observation, element: int, attribute: str) -> list[float]:
        """The lanes of one of the bar's cells (``element`` from 0)."""
        target = TargetRef(fixtureId=FixtureId(self.fixture(301)), element=element)
        found = self.compiled.slots.find(target, attribute)
        assert found is not None
        return [float(v) for v in seen.logical[found.lanes]]

    def cue(self, seen: Observation, number: int) -> str | None:
        """The current cue number of playback ``number``; ``None`` when idle."""
        assert seen.snapshot is not None
        ident = self.playback(number)
        return next(p.cue for p in seen.snapshot.playbacks if p.id == ident)


def stage_of(show: Show) -> Stage:
    return Stage(show, compile_show(show))


def command(**fields: Any) -> Command:
    return cast(Command, fields)


def timeline(stage: Stage, *, group: bool = True, taps: int = 4) -> Script:
    """The §5.14 performance; without ``group`` the two "Wash level" moves
    are left out, and only the first ``taps`` taps are made."""

    def fader(number: int, level: float = 1.0) -> Command:
        return command(type="SET_FADER", playbackId=stage.playback(number), level=level)

    def master(name: str, level: float) -> Command:
        return command(type="SET_MASTER", masterId=stage.master(name), level=level)

    def release(number: int) -> Command:
        return command(type="RELEASE_PLAYBACK", playbackId=stage.playback(number))

    script: list[tuple[float, Command]] = [
        (0.0, fader(1)),
        (0.0, fader(6)),
        (0.0, fader(11)),
        (3.0, fader(12)),
        (4.0, master("FX", 0.5)),
        (6.0, fader(13)),
        (7.0, release(1)),
        *((t, command(type="TAP", masterId=stage.master("Speed 1"))) for t in TAPS[:taps]),
        (12.8125, release(11)),
        (15.0, command(type="GOTO", playbackId=stage.playback(9), cueNumber="4")),
        (15.0, fader(9)),
        (25.0, release(9)),
    ]
    if group:
        script += [(5.0, master("Wash level", 0.5)), (5.5, master("Wash level", 1.0))]
    return script


type Pair = tuple[float, float]
type Rgb = tuple[float, float, float]


@dataclass(frozen=True)
class Checkpoint:
    """What §5.14 expects at ``time``: MH 1's and MH 2's pan and tilt, the
    wash (201–204) and head (101–102) intensities, the bar's 12 cell
    intensities, some cell colours (by cell number, from 1) and the song's
    current cue. ``None`` is not checked; a cue of ``""`` means idle."""

    time: float
    what: str
    mh1: Pair | None = None
    mh2: Pair | None = None
    washes: tuple[float, float, float, float] | None = None
    heads: Pair | None = None
    bar: tuple[float, ...] | None = None
    colours: dict[int, Rgb] | None = None
    song: str | None = None


WARM = (0.8,) * 12
# The wave at a whole P (the bar's cells from 1 to 12), and half a cycle on.
CREST = (0.0, 0.25, 0.75, 1.0, 0.75, 0.25, 0.25, 0.75, 1.0, 0.75, 0.25, 0.0)  # fmt: skip
TROUGH = tuple(1.0 - w for w in CREST)
RED, GREEN, BLUE, WHITE = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 1.0, 1.0)

CHECKPOINTS = [
    Checkpoint(0.0, "Warm at once, the circle starts on the grid at size 0",
               (0.0, 0.0), (0.0, 0.0), (0.8, 0.8, 0.8, 0.8), (0.8, 0.8), WARM),
    # Audience a quarter in (−7.5, 10 / 7.5, 10); the circle at half size, P = 0.5.
    Checkpoint(0.5, "circle growing", (0.0, 10.0), (7.5, 2.5)),
    Checkpoint(2.0, "Audience in, circle at full size", (-45.0, 40.0), (30.0, 55.0)),
    Checkpoint(2.25, "a quarter circle on", (-30.0, 55.0), (45.0, 40.0)),
    # The pulse starts at beat 6: P = 2t − 6; each wash 0.8 × (1 − 0.8·(1 − w)).
    Checkpoint(3.0, "the pulse starts on the beat", washes=(0.16, 0.48, 0.8, 0.48)),
    Checkpoint(3.125, "an eighth of a beat on", washes=(0.48, 0.8, 0.48, 0.16)),
    Checkpoint(4.0, "FX at half size", (-37.5, 40.0), (30.0, 47.5), (0.48, 0.64, 0.8, 0.64)),
    Checkpoint(5.0, "Wash level halves the washes", washes=(0.24, 0.32, 0.4, 0.32),
               heads=(0.8, 0.8), bar=WARM),
    Checkpoint(5.75, "Wash level back", washes=(0.8, 0.64, 0.48, 0.64)),
    # The wave starts at beat 12: P = 2t − 12; under Warm's 0.8 (HTP) but the crest.
    Checkpoint(6.25, "the wave's crest at both ends", bar=(1.0, *(0.8,) * 10, 1.0)),
    Checkpoint(8.5, "Warm released: the wave alone; the pulse has nothing to scale",
               washes=(0.0, 0.0, 0.0, 0.0), heads=(0.0, 0.0), bar=CREST),
    Checkpoint(10.0, "first tap, beat 20", (-37.5, 40.0), (30.0, 47.5), bar=CREST),
    Checkpoint(10.46875, "second tap: 128 BPM, nothing moves"),
    Checkpoint(10.9375, "beat 22: the nudge has closed", (-37.5, 40.0), (30.0, 47.5), bar=CREST),
    Checkpoint(11.171875, "beat 22.5 on the 128 BPM grid", (-30.0, 47.5), (37.5, 40.0),
               bar=TROUGH),
    Checkpoint(11.40625, "fourth tap, beat 23", (-22.5, 40.0), (30.0, 32.5), bar=CREST),
    Checkpoint(11.875, "beat 24", (-37.5, 40.0), (30.0, 47.5), bar=CREST),
    Checkpoint(12.8125, "beat 26: the circle releases over 1 s", (-37.5, 40.0), (30.0, 47.5)),
    Checkpoint(13.28125, "beat 27: the crest at 0.53125", (-26.015625, 40.0),
               (30.0, 36.015625)),
    # The Chorus with the cycle, P = (t − 15)/4, fading in over 0.5 s from
    # the bar's white; cell 1 at P: x = 3·frac(P) along red → green → blue.
    Checkpoint(15.0, "goto the Chorus: the cycle at presence 0", (-30.0, 40.0), (30.0, 40.0),
               colours={1: WHITE}, song="4"),
    Checkpoint(15.25, "fading in: halfway to (.8125, .1875, 0)",
               colours={1: (0.90625, 0.59375, 0.5)}),
    Checkpoint(15.5, "the Chorus lands", colours={1: (0.625, 0.375, 0.0)}),
    Checkpoint(19.0, "a cycle round the bar", heads=(1.0, 1.0), bar=(1.0,) * 12,
               colours={1: RED, 3: (0.5, 0.5, 0.0), 5: GREEN, 7: (0.0, 0.5, 0.5), 9: BLUE,
                        11: (0.5, 0.0, 0.5)}, song="4"),
    Checkpoint(19.5, "the Outro follows; the cycle tracks", colours={1: (0.625, 0.375, 0.0)},
               song="5"),
    Checkpoint(21.0, "the cycle's clock did not restart", colours={1: (0.0, 0.5, 0.5)},
               song="5"),
    Checkpoint(25.0, "release over 3 s", colours={1: (0.0, 0.5, 0.5)}),
    # Halfway: the cycle at (.625, 0, .375) half over the released white.
    Checkpoint(26.5, "fading out, still moving", colours={1: (0.8125, 0.5, 0.6875)}),
    Checkpoint(28.01, "released", colours={1: WHITE, 7: WHITE}, song=""),
]  # fmt: skip


def perform(
    stage: Stage, script: Script, ticks: Iterable[float] = HUNDRED_HZ
) -> dict[float, Observation]:
    """Run ``script`` on a fresh engine, ticking at ``ticks`` and at every
    checkpoint and command time."""
    return Harness(stage.compiled).run(script, [*ticks, *(c.time for c in CHECKPOINTS)])


@pytest.fixture(scope="module")
def stage(build: Build) -> Stage:
    loaded, warnings = load_show(build.path)
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
    for number, position in ((101, point.mh1), (102, point.mh2)):
        if position is not None:
            actual = stage.lanes(seen, number, "pan") + stage.lanes(seen, number, "tilt")
            assert actual == pytest.approx(position), number
    if point.washes is not None:
        levels = [stage.lanes(seen, n, "intensity")[0] for n in (201, 202, 203, 204)]
        assert levels == pytest.approx(point.washes)
    if point.heads is not None:
        levels = [stage.lanes(seen, n, "intensity")[0] for n in (101, 102)]
        assert levels == pytest.approx(point.heads)
    if point.bar is not None:
        levels = [stage.cell(seen, k, "intensity")[0] for k in range(12)]
        assert levels == pytest.approx(point.bar)
    for number, rgb in (point.colours or {}).items():
        assert stage.cell(seen, number - 1, "color")[:3] == pytest.approx(rgb), number
    if point.song is not None:
        assert stage.cue(seen, 9) == (point.song or None)


def test_the_checkpoint_frames_match_the_golden(run: dict[float, Observation]) -> None:
    frames = {f"{c.time:g}": channels(run[c.time].universe) for c in CHECKPOINTS}
    assert frames == golden("phase5_frames.json", frames)
    # Reviewed by hand. Spot 1 from 1 and spot 2 from 17: 16-bit pan (540°)
    # and tilt (270°). The ML-56s (4-channel, from 33) are RGBW with a
    # virtual dimmer; Warm (1, .75, .45) sends .45 to W. The PiX's 12 RGB
    # cells start at 49.

    def angle(degrees: float, span: float) -> bytes:
        value = round((0.5 + degrees / span) * 65535)
        return bytes([value >> 8, value & 255])

    def byte(value: float) -> int:
        return round(value * 255)

    circling = run[2.0].universe
    assert circling[0:4] == angle(-45, 540) + angle(40, 270)
    assert circling[16:20] == angle(30, 540) + angle(55, 270)
    pulsing = run[3.125].universe
    for k, level in enumerate((0.48, 0.8, 0.48, 0.16)):
        warm = [byte(level * c) for c in (0.55, 0.3, 0.0, 0.45)]
        assert pulsing[32 + 4 * k : 36 + 4 * k] == bytes(warm), k
    wave = run[8.5].universe
    assert wave[32:48] == bytes(16)  # the pulse alone gives nothing
    assert wave[48:84] == bytes(byte(level) for level in CREST for _ in range(3))
    cycle = run[19.0].universe  # cells 1, 5 and 9 (the halves are 127 or 128)
    assert cycle[48:51] + cycle[60:63] + cycle[72:75] == bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])


def test_the_group_master_leaves_no_trace(stage: Stage, run: dict[float, Observation]) -> None:
    """``Wash level`` back at full at 5.5: from then on the frames equal a
    run where it never moved."""
    unmoved = perform(stage, timeline(stage, group=False), [t for t in HUNDRED_HZ if t <= 6.0])
    assert unmoved[5.0].universe != run[5.0].universe
    for t in (5.5, 5.75, 6.0):
        assert unmoved[t].universe == run[t].universe, t
        assert np.array_equal(unmoved[t].logical, run[t].logical, equal_nan=True), t


def test_a_tap_moves_nothing_and_locks_one_beat_later(
    stage: Stage, run: dict[float, Observation]
) -> None:
    """At each tap the frame equals the frame of a run without it (the nudge
    starts at 0); the frames one beat after the second and the fourth taps
    are on the 128 BPM grid (the checkpoints at 10.9375 and 11.875). The
    pulse's clock follows §5.4's worked example."""
    for k, at in enumerate(TAPS):
        earlier = perform(stage, timeline(stage, taps=k), [t for t in HUNDRED_HZ if t <= at])
        assert earlier[at].universe == run[at].universe, at
        assert np.array_equal(earlier[at].logical, run[at].logical, equal_nan=True), at

    def pulse_clock(taps: int) -> EffectClock:
        harness = Harness(stage.compiled)
        script = [(t, c) for t, c in timeline(stage, taps=taps) if t <= TAPS[taps - 1]]
        harness.run(script, [t for t in HUNDRED_HZ if t <= TAPS[taps - 1]])
        bank = harness.engine.runtime.playbacks.runtimes[stage.playback(12)].bank
        return bank.runtimes["fx2"].clock

    first, second, third = pulse_clock(1), pulse_clock(2), pulse_clock(3)
    assert first.position(10.0) == pytest.approx(14.0)
    assert first.error == 0.0
    assert second.position(10.46875) == pytest.approx(14.9375)
    assert (second.p0, second.error) == pytest.approx((15.0, -0.0625))
    assert second.position(10.9375) == pytest.approx(16.0)  # the nudge closes by beat 22
    assert third.position(10.9375) == pytest.approx(16.0)
    assert third.error == pytest.approx(0.0)


def test_an_irregular_schedule_gives_the_same_frames(
    stage: Stage, run: dict[float, Observation]
) -> None:
    generator = random.Random(5)
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
    build: Build, stage: Stage, run: dict[float, Observation]
) -> None:
    assert stage.show == build.session.show
    in_memory = stage_of(build.session.show)
    fresh = perform(in_memory, timeline(in_memory))
    for point in CHECKPOINTS:
        assert fresh[point.time].universe == run[point.time].universe, point.time


# ------------------------------------------------- the programmer over effects


def test_the_programmer_holds_a_pan_under_the_circle(build: Build, stage: Stage) -> None:
    """``sel fixture 101`` and ``set pan 0`` hold MH 1's pan at exactly 0
    (the programmer, band 100, covers the circle's relative layer), while its
    tilt and MH 2 keep circling; ``clear`` brings the circle back. With no
    position under the circle, MH 1's tilt and MH 2's pan run a quarter cycle
    after MH 1's pan, and MH 2's tilt half a cycle: MH 1 pan = −MH 2 tilt."""
    live = Live(json.loads(read_show_bytes(build.path)))
    mh1, mh2 = stage.fixture(101), stage.fixture(102)
    live.do({"type": "SET_FADER", "playbackId": stage.playback(11), "level": 1.0})

    def positions() -> list[float]:
        return [
            live.lanes(fixture, attribute)[0]
            for fixture in (mh1, mh2)
            for attribute in ("pan", "tilt")
        ]

    for _ in range(120):  # past the 1 s growth
        live.tick()
    pan1, tilt1, pan2, tilt2 = positions()
    assert pan1 == pytest.approx(-tilt2)
    assert tilt1 == pytest.approx(pan2)
    assert max(abs(pan1), abs(tilt2)) > 1.0

    live.do(sel(mh1), put("pan", 0.0))
    held: list[list[float]] = []
    for _ in range(50):
        live.tick()
        held.append(positions())
    assert {pan for pan, _, _, _ in held} == {0.0}
    assert all(tilt1 == pytest.approx(pan2) for _, tilt1, pan2, _ in held)
    assert all(a[3] != b[3] for a, b in pairwise(held))  # still moving
    assert max(abs(tilt2) for _, _, _, tilt2 in held) > 7.5

    live.do(CLEAR)
    for _ in range(3):
        live.tick()
        pan1, tilt1, pan2, tilt2 = positions()
        assert pan1 == pytest.approx(-tilt2)
        assert pan1 != 0.0
