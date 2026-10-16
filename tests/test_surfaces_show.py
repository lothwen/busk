"""The Phase 6 done criterion (phase-6-plan §5.19, step 15): pages, a phone
remote and controller LEDs added to the effects show with console commands
only, on the show that ``tests/fixtures/phase3-build.busk``,
``tests/fixtures/phase4-song.busk`` and ``tests/fixtures/phase5-effects.busk`` saved.

The build runs the four scripts against a session and a real engine on a
fake clock, with counter ids, a fixed wall clock and a fixed installation
CID, so the saved show is deterministic. The performance runs the §5.19
timeline on a fresh engine built from the saved file, ticking at 100 Hz
plus the checkpoint times: the nanoKONTROL2 through the binding resolver,
the phone through the web API, each before the tick at its time. "Speed 1"
runs at 120 BPM from t = 0, so beats = 2t. Each checkpoint's values were
computed by hand; the DMX frames are compared with
``tests/golden/phase6_frames.json``, which was reviewed against them.
Regenerate the goldens with ``BUSK_REGOLDEN=1`` after a deliberate change,
then review the diff.

What the hand computations use:

- Warm (slot 1, ``base``) is every fixture at 0.8 in (1, .75, .45). The
  wash looks (page 2, slots 1–4, ``wash``) are the four ML-56s at full in a
  preset colour, Manual (page 2, slot 8) the bar's 12 cells at full in blue,
  red, green; every cue has 0 s timing.
- Intensity is HTP; a newer LTP source fades over the older ones, and a
  released one fades towards what lies under it (here the default white).
- Manual's crossfade fader: the transition's progress is how far the fader
  went from its rest end; a 0 s cue crosses linearly.
- The Fade master at 0.5 makes every time 10 s × 0.5² = 2.5 s.
"""

from __future__ import annotations

import json
import os
import random
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from numpy.typing import NDArray

from builders import ROOT
from busk.cli import main, status_line
from busk.commands.bus import CommandRejected
from busk.commands.types import Command, CommandOrigin
from busk.compiler.compile import CompiledShow, compile_show
from busk.console.console import Console
from busk.engine.clock import FakeClock
from busk.engine.loop import Engine
from busk.engine.snapshot import EngineSnapshot, PlaybackStatus
from busk.io.bindings import BindingResolver
from busk.io.events import InputEvent
from busk.io.feedback import FeedbackValue, feedback_values
from busk.model.common import FixtureId, SurfaceId, TargetRef
from busk.model.show import Show
from busk.model.surface import ControlSurface, InputAddress
from busk.model.validate import validate_show
from busk.persistence.paths import installation_cid
from busk.persistence.show_file import load_show, new_show, read_show_bytes
from busk.session.ids import CounterIds
from busk.session.library import ProfileLibrary
from busk.session.session import CommandResult, Session
from busk.web.api import WebApi, WebLink, WebSurface
from busk.web.websocket import WebSocket
from harness import Harness, Observation
from ws_client import WsClient, request, upgrade_headers

SCRIPTS = [
    ROOT / "tests" / "fixtures" / name
    for name in ("phase3-build.busk", "phase4-song.busk", "phase5-effects.busk")
]
SURFACES = ROOT / "tests" / "fixtures" / "phase6-surfaces.busk"
GOLDEN = Path(__file__).parent / "golden"
NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)
CID = "0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f"
REGOLDEN = os.environ.get("BUSK_REGOLDEN") == "1"


class Build:
    """``busk new``, the three earlier scripts and the surfaces script, on a
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
        self.ok = console.run_script(SURFACES, self.output.append)


@pytest.fixture(scope="module")
def build(tmp_path_factory: pytest.TempPathFactory) -> Build:
    return Build(tmp_path_factory.mktemp("surfaces"))


def golden(name: str, actual: Any) -> Any:
    path = GOLDEN / name
    if REGOLDEN:
        path.write_text(json.dumps(actual, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- the build


def test_every_line_of_the_four_scripts_succeeds(build: Build) -> None:
    assert build.earlier == [True, True, True]
    assert build.ok, build.output
    assert build.output[-1] == f"saved {build.path}"
    # record slot's numbers (§5.19): the slot's if free, else one above the highest.
    for line in (
        "recorded slot 2.1: playback 14 'Wash Blue'",
        "recorded slot 2.4: playback 17 'Wash Amber'",
        "recorded slot 2.8: playback 18 'Manual'",
        "recorded cue 18/3: 2 entries",
    ):
        assert line in build.output
    assert not any(line.startswith("warning") for line in build.output)


def test_the_saved_show_matches_the_golden_and_validates(
    build: Build, capsys: pytest.CaptureFixture[str]
) -> None:
    saved = json.loads(read_show_bytes(build.path))
    assert saved == golden("phase6_surfaces_show.json", saved)
    show, issues = validate_show(read_show_bytes(build.path))
    assert show is not None
    assert issues == []
    assert main(["validate", str(build.path)]) == 0
    assert capsys.readouterr().out == "0 errors, 0 warnings\n"

    playbacks = {p["id"]: p for p in saved["playbacks"]}
    numbers = {p["number"]: p for p in saved["playbacks"]}
    pages = {page["number"]: page for page in saved["pages"]}
    assert pages[2]["name"] == "Washes"
    assert [None if s is None else playbacks[s]["number"] for s in pages[2]["slots"]] == [
        14, 15, 16, 17, None, None, None, 18, 9, 10, 11, 12, 13
    ]  # fmt: skip
    assert {numbers[n]["exclusivity"] for n in (14, 15, 16, 17)} == {"wash"}
    assert numbers[14]["buttons"] == ["toggle", "swop", "release"]
    assert (numbers[18]["fader"], numbers[18]["buttons"]) == (
        "crossfade",
        ["go", "back", "release"],
    )
    assert (numbers[9]["gotoCue"], numbers[9]["buttons"][-1]) == ("4", "goto")
    surfaces = {s["name"]: s for s in saved["surfaces"]}
    assert surfaces["nanoKONTROL2"]["faderPickup"] == "soft"
    assert surfaces["Phone"]["match"] == {"port": 8080}
    assert {m["name"]: m["kind"] for m in saved["masters"]}["Fade"] == "fadeTime"
    nano = surfaces["nanoKONTROL2"]["id"]
    lit = sorted(
        b["input"]["cc"] for b in saved["bindings"] if b["surfaceId"] == nano and "feedback" in b
    )
    assert lit == [*range(32, 40), *range(41, 47), *range(48, 56), *range(64, 72)]


# ---------------------------------------------------------- the performance

type Rgb = tuple[float, float, float]
WARM: Rgb = (1.0, 0.75, 0.45)
RED: Rgb = (1.0, 0.0, 0.0)
BLUE: Rgb = (0.0, 0.0, 1.0)
GROUPS = {"heads": (101, 102), "washes": (201, 202, 203, 204), "bar": (301,)}
CELLS = 12  # the bar's elements


@dataclass(frozen=True)
class Stage:
    """Ids of the saved show the performance drives and reads."""

    show: Show
    compiled: CompiledShow

    def playback(self, number: int) -> str:
        return next(p["id"] for p in self.show["playbacks"] if p["number"] == number)

    def master(self, name: str) -> str:
        return next(m["id"] for m in self.show["masters"] if m["name"] == name)

    def surface(self, name: str) -> SurfaceId:
        return next(s["id"] for s in self.show["surfaces"] if s["name"] == name)

    def binding(self, cc: int) -> str:
        """The nanoKONTROL2 binding of CC ``cc`` (channel 1)."""
        nano = self.surface("nanoKONTROL2")
        return next(
            b["id"]
            for b in self.show["bindings"]
            if b["surfaceId"] == nano and b["input"] == {"kind": "midiCC", "channel": 1, "cc": cc}
        )

    def lanes(self, logical: NDArray[np.float64], group: str, attribute: str) -> list[list[float]]:
        """The lanes of ``attribute`` of every fixture (the bar: every cell) of a group."""
        found = []
        for number in GROUPS[group]:
            fixture = next(f["id"] for f in self.show["fixtures"] if f["number"] == number)
            for element in range(CELLS if group == "bar" else 1):
                target = TargetRef(fixtureId=FixtureId(fixture), element=element)
                slot = self.compiled.slots.find(target, attribute)
                assert slot is not None
                found.append([float(v) for v in logical[slot.lanes]])
        return found


@dataclass(frozen=True)
class Seen:
    """One tick: what the engine published, the value each binding's
    feedback shows, and the phone's latest state message."""

    observation: Observation
    feedback: dict[str, FeedbackValue]
    phone: dict[str, Any] | None

    @property
    def snapshot(self) -> EngineSnapshot:
        assert self.observation.snapshot is not None
        return self.observation.snapshot

    def playback(self, ident: str) -> PlaybackStatus:
        return next(p for p in self.snapshot.playbacks if p.id == ident)


class Performance:
    """A fresh engine from the saved show on a fake clock. The nanoKONTROL2
    plays through a :class:`BindingResolver` (CC values written as levels),
    the phone through a :class:`WebApi` with one client; both submit before
    the tick at their time, so the engine applies them at that tick."""

    def __init__(self, stage: Stage) -> None:
        self.stage = stage
        self.harness = Harness(stage.compiled)
        engine = self.harness.engine
        self.now = 0.0
        self.resolver = BindingResolver(
            stage.show,
            stage.compiled,
            engine.bus,
            page=lambda: None if engine.snapshot is None else engine.snapshot.page.id,
            clock=lambda: self.now,
        )
        link = WebLink(
            snapshot=lambda: engine.snapshot,
            compiled=lambda: engine.bus.compiled,
            submit=self.submit,
            clock=lambda: self.now,
            key="key",
        )
        self.api = WebApi(stage.surface("Phone"), link)
        self.phone = PhoneClient()
        self.api.connected(cast(WebSocket, self.phone))

    def submit(self, command: Command, origin: CommandOrigin) -> CommandResult:
        """What :meth:`Session.submit` does with a performance command."""
        try:
            self.harness.engine.bus.submit(command, origin)
        except CommandRejected as exc:
            return CommandResult(ok=False, message=exc.reason)
        return CommandResult(ok=True, message="")

    def run(self, script: Moves, ticks: Iterable[float]) -> dict[float, Seen]:
        """Tick at ``ticks`` and at every move's time, making each move
        before the tick at its time; return what every tick showed."""
        pending = sorted(script, key=lambda item: item[0])  # stable: same-time order kept
        seen: dict[float, Seen] = {}
        k = 0
        for now in sorted({*ticks, *(t for t, _ in pending)}):
            self.now = now
            while k < len(pending) and pending[k][0] <= now:
                pending[k][1](self)
                k += 1
            observation = self.harness.tick(now)
            self.api.broadcast()
            assert observation.snapshot is not None
            values = feedback_values(self.stage.compiled, observation.snapshot, now)
            seen[now] = Seen(observation, values, self.phone.slots.get("state"))
        return seen


class PhoneClient:
    """What the API uses of a :class:`WebSocket`: it keeps the latest show
    and state, and every reply."""

    remote = "10.0.0.7:50000"

    def __init__(self) -> None:
        self.replies: list[dict[str, Any]] = []
        self.slots: dict[str, dict[str, Any]] = {}

    def send(self, text: str) -> None:
        self.replies.append(json.loads(text))

    def publish(self, slot: str, text: str) -> None:
        self.slots[slot] = json.loads(text)


type Move = Callable[[Performance], None]
type Moves = Sequence[tuple[float, Move]]


def cc(control: int, level: float) -> Move:
    """A nanoKONTROL2 control on channel 1 moved to ``level``."""

    def move(performance: Performance) -> None:
        address = cast(InputAddress, {"kind": "midiCC", "channel": 1, "cc": control})
        nano = performance.stage.surface("nanoKONTROL2")
        performance.resolver.handle(InputEvent(nano, address, level))

    return move


def phone(**command: Any) -> Move:
    """A command from the phone's page."""

    def move(performance: Performance) -> None:
        replies = performance.phone.replies
        before = len(replies)
        text = json.dumps({"id": "p", "command": command})
        performance.api.received(cast(WebSocket, performance.phone), text)
        assert replies[before:] == []  # no error

    return move


def timeline(stage: Stage) -> Moves:
    """The §5.19 performance. Beyond §5.19: the phone raises the song's fader
    at 11, right after its goto button. A playback's fader starts at 0, so
    without it the Chorus would show nothing. The press starts the song on
    the Chorus; raised first, the fader would start it on the Intro
    (``autoStart``), and the goto would move on from there."""
    song, wash_blue = stage.playback(9), stage.playback(14)

    def press(control: int, at: float, up: float | None = None) -> list[tuple[float, Move]]:
        return [(at, cc(control, 1.0)), (at if up is None else up, cc(control, 0.0))]

    def goto(down: bool) -> Move:
        return phone(type="PLAYBACK_BUTTON", playbackId=song, button=3, down=down)

    return [
        (0.0, cc(0, 0.0)),  # fader 1 attaches to Warm
        (0.1, cc(0, 0.5)),
        (0.2, cc(0, 1.0)),
        *press(62, 1.0),  # marker ▶: page 2
        (1.5, cc(0, 0.9)),  # fader 1 is detached: Wash Blue is at 0
        (2.0, cc(0, 0.0)),
        (2.5, cc(0, 0.6)),
        (3.0, phone(type="SET_FADER", playbackId=wash_blue, level=0.3)),
        (3.5, cc(0, 0.65)),
        (4.0, cc(0, 0.25)),
        (5.0, cc(7, 0.0)),  # fader 8: Manual's crossfade
        (5.5, cc(7, 0.25)),
        (6.0, cc(7, 1.0)),
        (6.5, cc(7, 0.5)),
        (6.7, cc(7, 0.6)),
        (7.0, cc(7, 0.0)),
        *press(49, 8.0, 8.5),  # M2: swop Wash Red
        *press(42, 9.0, 9.05),  # ■: blackout on
        *press(42, 9.5, 9.55),  # ■: off
        *press(61, 10.0),  # marker ◀: page 1
        (10.5, phone(type="SET_MASTER", masterId=stage.master("Fade"), level=0.5)),
        (11.0, goto(True)),
        (11.0, goto(False)),
        (11.0, phone(type="SET_FADER", playbackId=song, level=1.0)),
    ]


@dataclass(frozen=True)
class Checkpoint:
    """What §5.19 expects at ``time``. ``levels`` and ``colours`` are per
    group (every fixture of it, every cell of the bar, alike); ``leds`` by
    CC; ``faders`` playback number → fader level; ``progress`` Manual's;
    ``status`` a part of the status line; ``page`` the page number the
    phone's state shows; ``same_as`` an earlier time whose frame this one
    equals byte for byte. ``None`` is not checked."""

    time: float
    what: str
    levels: dict[str, float] | None = None
    colours: dict[str, Rgb] | None = None
    mh1: tuple[float, float] | None = None
    leds: dict[int, float] | None = None
    faders: dict[int, float] | None = None
    active: dict[int, bool] | None = None
    progress: float | None = None
    status: str | None = None
    page: int | None = None
    same_as: float | None = None


ALL_WARM = {"heads": 0.8, "washes": 0.8, "bar": 0.8}
S1, M2, PLAY, STOP, CYCLE = 32, 49, 41, 42, 46

CHECKPOINTS = [
    Checkpoint(0.3, "fader 1 attached at 0 and brought Warm up", ALL_WARM,
               {"heads": WARM, "washes": WARM, "bar": WARM}, leds={S1: 1}, status="P1 Main",
               page=1),
    Checkpoint(1.0, "page 2: Wash Blue in slot 1 is idle", ALL_WARM, leds={S1: 0},
               status="P2 Washes", page=2),
    Checkpoint(1.5, "fader 1 ignored: no jump to 90 %", ALL_WARM, faders={14: 0.0},
               active={14: False}),
    Checkpoint(2.0, "fader 1 crosses 0: attached, nothing changes", ALL_WARM,
               faders={14: 0.0}, active={14: False}),
    Checkpoint(2.6, "Wash Blue up: Warm wins HTP, Wash Blue the newer LTP",
               {"washes": 0.8}, {"washes": BLUE, "heads": WARM}, leds={S1: 1},
               faders={14: 0.6}),
    Checkpoint(3.0, "the phone moves Wash Blue: fader 1 detaches", {"washes": 0.8},
               {"washes": BLUE}, faders={14: 0.3}),
    Checkpoint(3.5, "fader 1 ignored", faders={14: 0.3}),
    Checkpoint(4.0, "fader 1 crosses 0.3: attached", faders={14: 0.25}),
    Checkpoint(5.0, "fader 8 attaches to Manual at its rest end", {"bar": 0.8},
               {"bar": WARM}, active={18: False}),
    Checkpoint(5.5, "Manual by hand, a quarter into cue 1 (0 s: linear)", {"bar": 0.8},
               {"bar": (0.75, 0.5625, 0.5875)}, progress=0.25),
    Checkpoint(6.0, "cue 1 complete", {"bar": 1.0}, {"bar": BLUE}),
    Checkpoint(6.5, "halfway to cue 2", {"bar": 1.0}, {"bar": (0.5, 0.0, 0.5)}, progress=0.5),
    Checkpoint(6.7, "progress never goes back", {"bar": 1.0}, {"bar": (0.5, 0.0, 0.5)},
               progress=0.5),
    Checkpoint(7.0, "cue 2 complete: Manual rests at 0", {"bar": 1.0}, {"bar": RED}),
    Checkpoint(8.0, "M2 swops Wash Red: only it shows", {"washes": 1.0, "heads": 0.0, "bar": 0.0},
               {"washes": RED}, leds={M2: 1}),
    Checkpoint(8.5, "swop released", leds={M2: 0}, same_as=7.9),
    Checkpoint(9.0, "blackout latched", {"heads": 0.0, "washes": 0.0, "bar": 0.0}, leds={STOP: 1}),
    Checkpoint(9.05, "still on after the release", {"heads": 0.0, "washes": 0.0, "bar": 0.0},
               leds={STOP: 1}),
    Checkpoint(9.55, "blackout off", leds={STOP: 0}, same_as=8.9),
    Checkpoint(10.0, "page 1: Warm in slot 1 is active", leds={S1: 1}, page=1),
    Checkpoint(10.5, "the Fade master at half: 2.5 s", status="| Fade 2.5 s"),
    # The Chorus (cue 4: everything white at full; the heads' Audience
    # position tracks from the Verse) comes in over 2.5 s, and the base
    # exclusivity releases Warm over 2.5 s: halfway at 12.25. Wash Blue
    # stays (page 2) at 0.25. The heads' colour: Warm, half released over
    # the default white, (1, .875, .725), with the Chorus white half over it.
    Checkpoint(12.25, "halfway into the Chorus", {"washes": 0.5, "heads": 0.5},
               {"washes": (0.5, 0.5, 1.0), "heads": (1.0, 0.9375, 0.8625)}, mh1=(-15.0, 20.0),
               leds={PLAY: 1}, faders={9: 1.0}),
    Checkpoint(14.0, "beat 28: the cycle LED lit", leds={CYCLE: 1}),
    Checkpoint(14.2, "a fifth of a beat on: off", leds={CYCLE: 0}),
]  # fmt: skip
END = 14.3
HUNDRED_HZ = [k / 100 for k in range(int(END * 100) + 1)]


def perform(stage: Stage, ticks: Iterable[float] = HUNDRED_HZ) -> dict[float, Seen]:
    """The timeline on a fresh engine, ticking at ``ticks`` and at every
    checkpoint (and every time a checkpoint is compared with)."""
    times = [c.time for c in CHECKPOINTS] + [c.same_as for c in CHECKPOINTS if c.same_as]
    return Performance(stage).run(timeline(stage), [*ticks, *times])


@pytest.fixture(scope="module")
def stage(build: Build) -> Stage:
    loaded, warnings = load_show(build.path)
    assert warnings == []
    return Stage(loaded, compile_show(loaded))


@pytest.fixture(scope="module")
def run(stage: Stage) -> dict[float, Seen]:
    return perform(stage)


@pytest.mark.parametrize("point", CHECKPOINTS, ids=lambda c: f"{c.time:g} {c.what}")
def test_the_checkpoints_hold(stage: Stage, run: dict[float, Seen], point: Checkpoint) -> None:
    seen = run[point.time]
    logical = seen.observation.logical
    for group, level in (point.levels or {}).items():
        levels = [lanes[0] for lanes in stage.lanes(logical, group, "intensity")]
        assert levels == pytest.approx([level] * len(levels)), group
    for group, rgb in (point.colours or {}).items():
        colours = [value for lanes in stage.lanes(logical, group, "color") for value in lanes[:3]]
        assert colours == pytest.approx(list(rgb) * (len(colours) // 3)), group
    if point.mh1 is not None:
        pan, tilt = (stage.lanes(logical, "heads", a)[0][0] for a in ("pan", "tilt"))
        assert (pan, tilt) == pytest.approx(point.mh1)
    for control, value in (point.leds or {}).items():
        assert seen.feedback[stage.binding(control)] == value, control
    for number, level in (point.faders or {}).items():
        assert seen.playback(stage.playback(number)).faderLevel == pytest.approx(level), number
        state = next(p for p in (seen.phone or {})["playbacks"] if p["number"] == number)
        assert state["faderLevel"] == pytest.approx(level), number  # what the phone shows
    for number, active in (point.active or {}).items():
        assert (seen.playback(stage.playback(number)).state != "idle") == active, number
    if point.progress is not None:
        assert seen.playback(stage.playback(18)).progress == pytest.approx(point.progress)
    if point.status is not None:
        assert point.status in status_line(seen.snapshot)
    if point.page is not None:
        assert seen.phone is not None
        assert seen.phone["page"]["number"] == point.page
    if point.same_as is not None:
        assert seen.observation.universe == run[point.same_as].observation.universe


def channels(universe: bytes) -> dict[str, int]:
    """Non-zero channels, 1-based (JSON keys are strings)."""
    return {str(k + 1): value for k, value in enumerate(universe) if value}


def test_the_checkpoint_frames_match_the_golden(run: dict[float, Seen]) -> None:
    frames = {f"{c.time:g}": channels(run[c.time].observation.universe) for c in CHECKPOINTS}
    assert frames == golden("phase6_frames.json", frames)
    # Reviewed by hand. The ML-56s (4-channel, from 33) are RGBW with a
    # virtual dimmer: white is min(r, g, b), taken out of r, g and b, and
    # every part scaled by the intensity. The PiX's 12 RGB cells start at 49.

    def washes(seen: Seen) -> bytes:
        return seen.observation.universe[32:48]

    def bar(seen: Seen) -> bytes:
        return seen.observation.universe[48:84]

    def byte(value: float) -> int:
        return round(value * 255)

    assert washes(run[2.6]) == bytes([0, 0, byte(0.8), 0] * 4)  # blue at 0.8
    assert bar(run[7.0]) == bytes([255, 0, 0] * 12)  # Manual on cue 2: red
    assert bar(run[6.5]) == bytes([byte(0.5), 0, byte(0.5)] * 12)
    assert washes(run[8.0]) == bytes([255, 0, 0, 0] * 4)  # the swop: Wash Red alone
    assert bar(run[8.0]) == bytes(36)
    assert washes(run[9.0]) + bar(run[9.0]) == bytes(52)  # blackout
    # (0.5, 0.5, 1) at 0.5: white 0.5, blue 0.5 over it.
    assert washes(run[12.25]) == bytes([0, 0, byte(0.25), byte(0.25)] * 4)


def test_an_irregular_schedule_gives_the_same_frames(stage: Stage, run: dict[float, Seen]) -> None:
    generator = random.Random(6)
    ticks, now = [], 0.0
    while now < END:
        ticks.append(now)
        now += generator.uniform(0.001, 0.06)
    irregular = perform(stage, ticks)
    for point in CHECKPOINTS:
        seen, expected = irregular[point.time].observation, run[point.time].observation
        assert seen.universe == expected.universe, point.time
        assert np.array_equal(seen.logical, expected.logical, equal_nan=True), point.time
        assert irregular[point.time].feedback == run[point.time].feedback, point.time


def test_save_load_and_a_fresh_engine_give_the_same_frames(
    build: Build, stage: Stage, run: dict[float, Seen]
) -> None:
    assert stage.show == build.session.show
    in_memory = Stage(build.session.show, compile_show(build.session.show))
    fresh = perform(in_memory)
    for point in CHECKPOINTS:
        assert fresh[point.time].observation.universe == run[point.time].observation.universe


# ------------------------------------------------------------- the network


def test_the_phone_over_a_real_websocket(stage: Stage) -> None:
    """§5.19's network test: the phone part through a real :class:`WebSurface`
    on a localhost ephemeral port, the engine ticking on the test's fake
    clock until each command lands, and ``tests/ws_client.py`` as the phone."""
    performance = Performance(stage)
    engine = performance.harness.engine
    warm, phone_id = stage.playback(1), stage.surface("Phone")

    def until(predicate: Callable[[EngineSnapshot], bool]) -> None:
        """Tick 10 ms at a time until the engine's snapshot satisfies ``predicate``."""
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            performance.now += 0.01
            performance.harness.tick(performance.now)
            snapshot = engine.snapshot
            if snapshot is not None and predicate(snapshot):
                return
            time.sleep(0.005)  # the server's threads submit meanwhile
        raise AssertionError("the engine never got there")

    def warm_status(snapshot: EngineSnapshot) -> PlaybackStatus:
        return next(p for p in snapshot.playbacks if p.id == warm)

    def receive(client: WsClient, kind: str, test: Callable[[dict[str, Any]], bool]) -> Any:
        """The first message of type ``kind`` that passes ``test``; states
        that fail it are skipped (the broadcaster may send several)."""
        while True:
            message = json.loads(client.recv_text())
            if message["type"] == kind and test(message):
                return message
            assert message["type"] == "state", message

    def send(client: WsClient, ident: str, **command: Any) -> None:
        client.send_text(json.dumps({"id": ident, "command": command}))

    link = WebLink(
        snapshot=lambda: engine.snapshot,
        compiled=lambda: engine.bus.compiled,
        submit=performance.submit,
        clock=lambda: performance.now,
        key="phone-key",
    )
    surface = next(s for s in stage.show["surfaces"] if s["id"] == phone_id)
    local = cast(ControlSurface, {**surface, "match": {"port": 0, "host": "127.0.0.1"}})
    web = WebSurface(local, link, stall=0.3, linger=0.3)
    performance.harness.tick(0.0)
    assert web.open() is None
    try:
        port = web.server.port
        assert port is not None
        for path, headers in (
            ("/ws?k=wrong", upgrade_headers()),
            ("/ws?k=phone-key", upgrade_headers() | {"Origin": "http://evil.example"}),
        ):
            connection, response = request(port, path, headers)
            connection.close()
            assert response.status == 403, path

        client = WsClient(port, "phone-key")
        hello = json.loads(client.recv_text())
        assert (hello["type"], hello["surface"]) == ("hello", phone_id)
        show = json.loads(client.recv_text())
        assert [page["name"] for page in show["pages"]] == ["Main", "Washes"]
        song = next(p for p in show["playbacks"] if p["number"] == 9)
        assert song["gotoCue"] == {"number": "4", "name": "Chorus"}
        state = json.loads(client.recv_text())
        assert (state["type"], state["page"]["number"]) == ("state", 1)

        # A fader from the phone reaches the engine, and comes back as state.
        send(client, "1", type="SET_FADER", playbackId=warm, level=0.5)
        until(lambda snapshot: warm_status(snapshot).faderLevel == 0.5)

        def warm_level(message: dict[str, Any]) -> Any:
            return next(p for p in message["playbacks"] if p["id"] == warm)["faderLevel"]

        receive(client, "state", lambda message: warm_level(message) == 0.5)

        # A page change made from the controller arrives as state.
        cc(62, 1.0)(performance)
        cc(62, 0.0)(performance)
        until(lambda snapshot: snapshot.page is not None and snapshot.page.number == 2)
        state = receive(client, "state", lambda message: message["page"]["number"] == 2)
        assert state["page"]["name"] == "Washes"

        # Show edits are refused, with the client's id.
        send(client, "edit", type="SET", path=["meta", "title"], value="Hacked")
        error = receive(client, "error", lambda message: True)
        assert error == {
            "type": "error",
            "id": "edit",
            "message": "SET is a show command; the web remote sends performance commands only",
        }
        assert stage.show["meta"]["title"] == "Club Night"

        # A flash held when the phone vanishes is released.
        send(client, "2", type="PLAYBACK_BUTTON", playbackId=warm, button=1, down=True)
        until(lambda snapshot: warm_status(snapshot).flash)
        client.close()
        until(lambda snapshot: not warm_status(snapshot).flash)
    finally:
        web.close()
