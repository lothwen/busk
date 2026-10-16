"""The Phase 7 done criterion A (phase-7-plan §5.24, step 18): limits, park,
a strobe cap, highlight and the panic commands added to the surfaces show
with console commands only, on the show that ``examples/phase3-build.busk``,
``examples/phase4-song.busk``, ``examples/phase5-effects.busk`` and
``examples/phase6-surfaces.busk`` saved.

The build runs the five scripts against a session and a real engine on a
fake clock, with counter ids, a fixed wall clock and a fixed installation
CID, so the saved show is deterministic. The performance runs the §5.24
timeline on a fresh engine built from the saved file, ticking at 100 Hz
plus the checkpoint times: the nanoKONTROL2 through the binding resolver,
programmer and show commands as console lines through a session on that
engine, each before the tick at its time. "Speed 1" runs at 120 BPM from
t = 0. Each checkpoint's logical values were computed by hand; the DMX
frames are compared with ``tests/golden/phase7_frames.json``, which was
reviewed against them. Regenerate the goldens with ``BUSK_REGOLDEN=1``
after a deliberate change, then review the diff.

Where the effects make a value hard to compute by hand (the Circle on the
heads), a *twin* gives it: the same timeline on a show without the heads'
limits, or without some of the inputs.

What the hand computations use:

- Warm (slot 1, ``base``) is every fixture at 0.8 in (1, .75, .45). The
  Song (playback 9, ``base``, release time 3 s) on its Chorus is every
  fixture at full white over 0.5 s, with a Rainbow on the bar; MH 1's
  Audience position tracks from the Verse: pan −30°, tilt 40°. Starting
  the Song releases Warm over Warm's 1 s release time. The Fade master
  starts at 0: the programmed times.
- The Outro follows 4 s after the Chorus landed, at 6.5: the heads dim
  from 1.0 to 0.2 over 6 s, and their pan and tilt are released over 6 s.
- Safety: the heads' tilt at most 10°, the bar at most 0.5, wash 4 (204)
  parked at intensity 0, wash 3 (203) parked on red, strobe at most 3 Hz.
  The stage order is masters, highlight, park, blackout, limits, cap.
- Strobe (playback 19, page 2 slot 5) is the heads at full, shutter
  ``strobe`` at 10 Hz; Fast pulse (playback 20, slot 6) an 8 Hz pulse on
  the washes. Both have 0 s cues and the default 1 s release time.

Two corrections to §5.24's table. At 3 s MH 1 is at pan −30°, tilt 10°
(its tracked tilt is 40°): §5.24 took (−15°, 20°) from Phase 6, which
measured them halfway into a 2.5 s Chorus. After marker SET the stage is
at its defaults after 3 s, the Song's release time (§5.24: 2 s, Appendix
A's). Marker SET toggled the Bar wave in Phase 5; the script unbinds it
before binding ``release all``, or the panic button would start the wave.
"""

from __future__ import annotations

import copy
import json
import os
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from numpy.typing import NDArray

from builders import ROOT, localhost_route
from busk.cli import main, status_line
from busk.compiler.compile import CompiledShow, compile_show
from busk.console.console import Console
from busk.engine.clock import FakeClock
from busk.engine.loop import Engine
from busk.engine.snapshot import EngineSnapshot, PlaybackStatus
from busk.io.bindings import BindingResolver
from busk.io.events import InputEvent
from busk.model.common import FixtureId, SurfaceId, TargetRef
from busk.model.show import Show
from busk.model.surface import InputAddress
from busk.model.validate import validate_show
from busk.output.artnet import ArtNetNetwork
from busk.output.sacn import Sequences
from busk.output.scheduler import OutputScheduler, build_routes
from busk.persistence.paths import installation_cid
from busk.persistence.show_file import load_show, new_show, read_show_bytes
from busk.session.ids import CounterIds
from busk.session.library import ProfileLibrary
from busk.session.session import Session
from harness import Harness, Observation
from sacn_receiver import Receiver

SCRIPTS = [
    ROOT / "examples" / name
    for name in (
        "phase3-build.busk",
        "phase4-song.busk",
        "phase5-effects.busk",
        "phase6-surfaces.busk",
    )
]
SAFETY = ROOT / "examples" / "phase7-safety.busk"
GOLDEN = Path(__file__).parent / "golden"
NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
CID = "0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f"
REGOLDEN = os.environ.get("BUSK_REGOLDEN") == "1"


class Build:
    """``busk new``, the four earlier scripts and the safety script, on a
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
        self.ok = console.run_script(SAFETY, self.output.append)


@pytest.fixture(scope="module")
def build(tmp_path_factory: pytest.TempPathFactory) -> Build:
    return Build(tmp_path_factory.mktemp("safety"))


def golden(name: str, actual: Any) -> Any:
    path = GOLDEN / name
    if REGOLDEN:
        path.write_text(json.dumps(actual, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- the build


def test_every_line_of_the_five_scripts_succeeds(build: Build) -> None:
    assert build.earlier == [True, True, True, True]
    assert build.ok, build.output
    assert build.output[-1] == f"saved {build.path}"
    # record slot's numbers (§5.24): the slot's if free, else one above the highest.
    for line in (
        "recorded slot 2.5: playback 19 'Strobe'",
        "recorded slot 2.6: playback 20 'Fast pulse'",
        "unbound 1 binding",
    ):
        assert line in build.output
    assert not any(line.startswith("warning") for line in build.output)


def test_the_saved_show_matches_the_golden_and_validates(
    build: Build, capsys: pytest.CaptureFixture[str]
) -> None:
    saved = json.loads(read_show_bytes(build.path))
    assert saved == golden("phase7_safety_show.json", saved)
    show, issues = validate_show(read_show_bytes(build.path))
    assert show is not None
    assert issues == []
    assert main(["validate", str(build.path)]) == 0
    assert capsys.readouterr().out == "0 errors, 0 warnings\n"

    fixtures = {f["number"]: f for f in saved["fixtures"]}
    assert fixtures[101]["limits"] == {"tilt": [-90, 10]}
    assert fixtures[102]["limits"] == {"tilt": [-90, 10]}
    assert fixtures[301]["limits"] == {"intensityMax": 0.5}
    assert saved["safety"] == {"strobeMaxHz": 3}
    by_id = {f["id"]: f["number"] for f in saved["fixtures"]}
    parked = [
        (by_id[p["slot"]["target"]["fixtureId"]], p["slot"]["attribute"], p["value"])
        for p in saved["park"]
    ]
    assert parked == [(204, "intensity", 0), (203, "color", {"r": 1, "g": 0, "b": 0})]
    numbers = {p["number"]: p for p in saved["playbacks"]}
    pages = {page["number"]: page for page in saved["pages"]}
    assert pages[2]["slots"][4:6] == [numbers[19]["id"], numbers[20]["id"]]
    nano = next(s["id"] for s in saved["surfaces"] if s["name"] == "nanoKONTROL2")
    marker_set = [
        b["action"]
        for b in saved["bindings"]
        if b["surfaceId"] == nano and b["input"] == {"kind": "midiCC", "channel": 1, "cc": 60}
    ]
    assert marker_set == [{"kind": "command", "command": {"type": "RELEASE_ALL"}}]


# ---------------------------------------------------------- the performance

type Rgb = tuple[float, float, float]
WARM: Rgb = (1.0, 0.75, 0.45)
WHITE: Rgb = (1.0, 1.0, 1.0)
RED: Rgb = (1.0, 0.0, 0.0)
HEADS, WASHES, BAR = (101, 102), (201, 202, 203, 204), 301
CELLS = 12  # the bar's elements
TILT_MAX = 10.0


@dataclass(frozen=True)
class Stage:
    """Ids of a saved show the performance drives and reads."""

    show: Show
    compiled: CompiledShow

    def playback(self, number: int) -> str:
        return next(p["id"] for p in self.show["playbacks"] if p["number"] == number)

    def surface(self, name: str) -> SurfaceId:
        return next(s["id"] for s in self.show["surfaces"] if s["name"] == name)

    def fixture(self, number: int) -> FixtureId:
        return next(f["id"] for f in self.show["fixtures"] if f["number"] == number)

    def lanes(
        self, logical: NDArray[np.float64], number: int, attribute: str, element: int = 0
    ) -> list[float]:
        """The lanes of one element's ``attribute``."""
        target = TargetRef(fixtureId=self.fixture(number), element=element)
        slot = self.compiled.slots.find(target, attribute)
        assert slot is not None, (number, attribute)
        return [float(v) for v in logical[slot.lanes]]

    def every(self, logical: NDArray[np.float64], number: int, attribute: str) -> list[list[float]]:
        """The lanes of ``attribute`` of every element (the bar: every cell)."""
        cells = CELLS if number == BAR else 1
        return [self.lanes(logical, number, attribute, element) for element in range(cells)]

    def option(self, number: int, attribute: str, name: str) -> float:
        """The lane value of a discrete attribute's option (``shutter``'s ``strobe``)."""
        target = TargetRef(fixtureId=self.fixture(number), element=0)
        slot = self.compiled.slots.find(target, attribute)
        assert slot is not None, (number, attribute)
        return float(slot.options.index(name))

    def without_head_limits(self) -> Stage:
        """This show without the heads' limits: the Circle's own path."""
        show = copy.deepcopy(self.show)
        for fixture in show["fixtures"]:
            if fixture["number"] in HEADS:
                del fixture["limits"]
        return Stage(show, compile_show(show))


class Performance:
    """A fresh engine from the saved show on a fake clock. The nanoKONTROL2
    plays through a :class:`BindingResolver` (CC values written as levels);
    console lines run on a :class:`Console` whose session drives the same
    engine. Both act before the tick at their time, so the engine applies
    them at that tick."""

    def __init__(self, stage: Stage) -> None:
        self.stage = stage
        self.harness = Harness(stage.compiled)
        engine = self.harness.engine
        self.now = 0.0

        def page() -> str | None:
            snapshot = engine.snapshot
            return None if snapshot is None or snapshot.page is None else snapshot.page.id

        self.resolver = BindingResolver(
            stage.show,
            stage.compiled,
            engine.bus,
            page=page,
            clock=lambda: self.now,
        )
        session = Session(
            stage.show,
            engine.bus,
            compiled=stage.compiled,
            ids=CounterIds(),
            wall_clock=lambda: NOW,
            engine_state=lambda: engine.snapshot,
        )
        self.console = Console(session, ProfileLibrary())

    def run(
        self,
        script: Moves,
        ticks: Iterable[float],
        each: Callable[[float], None] | None = None,
    ) -> dict[float, Observation]:
        """Tick at ``ticks`` and at every move's time, making each move
        before the tick at its time; return what every tick showed.
        ``each`` is called with the time after every tick."""
        pending = sorted(script, key=lambda item: item[0])  # stable: same-time order kept
        seen: dict[float, Observation] = {}
        k = 0
        for now in sorted({*ticks, *(t for t, _ in pending)}):
            self.now = now
            while k < len(pending) and pending[k][0] <= now:
                pending[k][1](self)
                k += 1
            seen[now] = self.harness.tick(now)
            if each is not None:
                each(now)
        return seen


type Move = Callable[[Performance], None]
type Moves = Sequence[tuple[float, Move]]


def cc(control: int, level: float) -> Move:
    """A nanoKONTROL2 control on channel 1 moved to ``level``."""

    def move(performance: Performance) -> None:
        address = cast(InputAddress, {"kind": "midiCC", "channel": 1, "cc": control})
        nano = performance.stage.surface("nanoKONTROL2")
        performance.resolver.handle(InputEvent(nano, address, level))

    return move


def say(line: str) -> Move:
    """A console line; it must succeed."""

    def move(performance: Performance) -> None:
        reply = performance.console.execute(line)
        assert reply.ok, (line, reply.text)

    return move


def press(control: int, at: float, up: float | None = None) -> list[tuple[float, Move]]:
    """A nanoKONTROL2 button pressed at ``at`` and released at ``up``."""
    return [(at, cc(control, 1.0)), (at if up is None else up, cc(control, 0.0))]


def sweep(control: int, at: float, *levels: float) -> list[tuple[float, Move]]:
    """A soft-takeover control moved through ``levels`` at one time: the
    first meets the level the playback or master has, the rest move it."""
    return [(at, cc(control, level)) for level in levels]


FADER_1, FADER_5, FADER_6 = 0, 4, 5
KNOB_SONG, KNOB_CIRCLE, KNOB_GRAND = 16, 19, 23  # knobs 1, 4 and 8: slots 9, 11, the GM
STOP, MARKER_SET, MARKER_NEXT = 42, 60, 62

HIGHLIGHT_INPUTS: Moves = [  # 7.5–8.5: the twin at 8.5 leaves these out
    (7.5, say("sel fixture 102")),
    (7.5, say("highlight on")),
    (7.5, cc(KNOB_GRAND, 0.5)),
    *press(STOP, 8.0, 8.05),  # ■: blackout on
    *press(STOP, 8.5),  # ■: off
    (8.5, say("highlight off")),
    (8.5, cc(KNOB_GRAND, 1.0)),
]
PARK_INPUTS: Moves = [
    (9.0, say("park fixture 101 pan 0")),
    (9.5, say("unpark fixture 101 pan")),
]


def timeline(highlight: bool = True, park: bool = True) -> Moves:
    """The §5.24 performance; a twin leaves out the highlight inputs
    (7.5–8.5) or the live park (9–9.5)."""
    return [
        (0.0, cc(FADER_1, 0.0)),  # fader 1 attaches to Warm
        (0.1, cc(FADER_1, 0.5)),
        (0.2, cc(FADER_1, 1.0)),
        *sweep(KNOB_GRAND, 1.0, 1.0, 0.5),  # knob 8 meets the grand master at full
        (1.5, cc(KNOB_GRAND, 1.0)),
        (2.0, say("goto 9 4")),  # the Chorus: the press first, as in Phase 6
        *sweep(KNOB_SONG, 2.0, 0.0, 1.0),
        *sweep(KNOB_CIRCLE, 3.5, 0.0, 1.0),
        *press(MARKER_NEXT, 5.0),  # page 2
        *sweep(FADER_5, 5.0, 0.0, 1.0),  # Strobe
        *sweep(FADER_6, 6.0, 0.0, 1.0),  # Fast pulse
        (6.2, cc(FADER_5, 0.0)),
        *(HIGHLIGHT_INPUTS if highlight else []),
        *(PARK_INPUTS if park else []),
        *press(MARKER_SET, 10.0),  # RELEASE_ALL
        (13.0, say("output off")),
        (14.0, say("output on")),
    ]


# The Fast pulse at 6: the washes repeat every 1/3 s (the cap), not 1/8 s.
PULSE = [6.5, 6.5 + 1 / 8, 6.5 + 1 / 3, 6.5 + 2 / 3]


@dataclass(frozen=True)
class Checkpoint:
    """What §5.24 expects at ``time``. ``levels`` and ``colours`` are by
    fixture number (the bar: every cell alike); ``mh1`` is MH 1's pan and
    tilt; ``shutter`` by head, its option and strobe rate (``None``: not
    checked);
    ``states`` playback number → state (every other playback idle).
    ``None`` is not checked."""

    time: float
    what: str
    levels: dict[int, float] | None = None
    colours: dict[int, Rgb] | None = None
    mh1: tuple[float, float] | None = None
    shutter: dict[int, tuple[str, float | None]] | None = None
    states: dict[int, str] | None = None


def at(**levels: float) -> dict[int, float]:
    """Levels by group: ``heads``, ``washes`` (204 parked at 0) and ``bar``."""
    found: dict[int, float] = {}
    for group, level in levels.items():
        numbers = {"heads": HEADS, "washes": WASHES, "bar": (BAR,)}[group]
        found |= dict.fromkeys(numbers, level)
    return found | {204: 0.0}


def lit(heads: Rgb, washes: Rgb, bar: Rgb | None = None) -> dict[int, Rgb]:
    """Colours by group (the bar's unless ``None``); 203 is parked on red."""
    colours = dict.fromkeys(HEADS, heads) | dict.fromkeys(WASHES, washes) | {203: RED}
    return colours if bar is None else colours | {BAR: bar}


CHECKPOINTS = [
    Checkpoint(0.3, "Warm up: 204 parked dark, 203 parked red, the bar limited to 0.5",
               at(heads=0.8, washes=0.8, bar=0.5), lit(WARM, WARM, WARM), states={1: "active"}),
    Checkpoint(1.0, "the grand master at half: the bar 0.4, under its limit",
               at(heads=0.4, washes=0.4, bar=0.4), lit(WARM, WARM, WARM)),
    Checkpoint(1.5, "the grand master back", at(heads=0.8, washes=0.8, bar=0.5)),
    Checkpoint(3.0, "the Chorus: MH 1's tracked tilt 40° is held at 10°",
               at(heads=1.0, washes=1.0, bar=0.5), lit(WHITE, WHITE), mh1=(-30.0, 10.0),
               states={9: "active"}),
    Checkpoint(5.0, "Strobe up: 10 Hz asked, 3 Hz out", at(heads=1.0, washes=1.0, bar=0.5),
               shutter={101: ("strobe", 3.0), 102: ("strobe", 3.0)},
               states={9: "active", 11: "active", 19: "active"}),
    Checkpoint(6.7, "Strobe releasing over 1 s",
               states={9: "active", 11: "active", 19: "releasing", 20: "active"}),
    Checkpoint(7.3, "Strobe released", states={9: "active", 11: "active", 20: "active"}),
    Checkpoint(7.5, "MH 2 highlighted at full white, open; MH 1 at half its Outro level",
               {101: 0.5 * (1 - 0.8 * 1 / 6), 102: 1.0, 204: 0.0}, {102: WHITE},
               shutter={102: ("open", None)}),
    Checkpoint(8.0, "blackout wins over highlight", at(heads=0.0, washes=0.0, bar=0.0)),
    Checkpoint(10.0, "marker SET: every playback releasing",
               states={9: "releasing", 11: "releasing", 20: "releasing"}),
    Checkpoint(11.5, "the Circle and the pulse released (1 s), the Song not (3 s)",
               states={9: "releasing"}),
    Checkpoint(13.0, "all released: defaults, but 203 red and 204 dark",
               at(heads=0.0, washes=0.0, bar=0.0), {203: RED}, states={}),
]  # fmt: skip
END = 14.2
HUNDRED_HZ = [k / 100 for k in range(int(END * 100) + 1)]
TIMES = [c.time for c in CHECKPOINTS] + PULSE + [9.0, 9.5, 8.5, 13.0, 14.0]


def perform(
    stage: Stage, ticks: Iterable[float] = HUNDRED_HZ, script: Moves | None = None
) -> dict[float, Observation]:
    """A timeline on a fresh engine, ticking at ``ticks`` and at every
    time a test looks at."""
    moves = timeline() if script is None else script
    return Performance(stage).run(moves, [*ticks, *TIMES])


@pytest.fixture(scope="module")
def stage(build: Build) -> Stage:
    loaded, warnings = load_show(build.path)
    assert warnings == []
    return Stage(loaded, compile_show(loaded))


@pytest.fixture(scope="module")
def run(stage: Stage) -> dict[float, Observation]:
    return perform(stage)


@pytest.fixture(scope="module")
def twin(stage: Stage) -> dict[float, Observation]:
    """The timeline without the highlight inputs and the live park."""
    return perform(stage, script=timeline(highlight=False, park=False))


def snapshot(observation: Observation) -> EngineSnapshot:
    assert observation.snapshot is not None
    return observation.snapshot


def status(observation: Observation, stage: Stage, number: int) -> PlaybackStatus:
    return next(p for p in snapshot(observation).playbacks if p.id == stage.playback(number))


@pytest.mark.parametrize("point", CHECKPOINTS, ids=lambda c: f"{c.time:g} {c.what}")
def test_the_checkpoints_hold(
    stage: Stage, run: dict[float, Observation], point: Checkpoint
) -> None:
    logical = run[point.time].logical
    for number, level in (point.levels or {}).items():
        levels = [lanes[0] for lanes in stage.every(logical, number, "intensity")]
        assert levels == pytest.approx([level] * len(levels)), number
    for number, rgb in (point.colours or {}).items():
        colours = [v for lanes in stage.every(logical, number, "color") for v in lanes[:3]]
        assert colours == pytest.approx(list(rgb) * (len(colours) // 3)), number
    if point.mh1 is not None:
        pan, tilt = (stage.lanes(logical, 101, a)[0] for a in ("pan", "tilt"))
        assert (pan, tilt) == pytest.approx(point.mh1)
    for number, (option, rate) in (point.shutter or {}).items():
        assert stage.lanes(logical, number, "shutter") == [stage.option(number, "shutter", option)]
        if rate is not None:
            assert stage.lanes(logical, number, "strobeRate") == pytest.approx([rate])
    if point.states is not None:
        states = {
            number: status(run[point.time], stage, number).state
            for number in (p["number"] for p in stage.show["playbacks"])
        }
        assert {n: s for n, s in states.items() if s != "idle"} == point.states


def test_the_circle_follows_its_path_under_the_tilt_limit(
    stage: Stage, run: dict[float, Observation]
) -> None:
    """MH 1's tilt follows the Circle below 10° and is flat at 10° above
    it; its pan follows the Circle throughout. The Circle's own path comes
    from a twin without the heads' limits: around tilt 40° it stays above
    10° until the Outro releases the heads' position (from 6.5), then dips
    under it."""
    free = perform(stage.without_head_limits())
    below = above = 0
    for now in HUNDRED_HZ:
        held, own = run[now].logical, free[now].logical
        pan, tilt = stage.lanes(held, 101, "pan")[0], stage.lanes(held, 101, "tilt")[0]
        circle_pan, circle_tilt = stage.lanes(own, 101, "pan")[0], stage.lanes(own, 101, "tilt")[0]
        assert pan == pytest.approx(circle_pan), now
        assert tilt == pytest.approx(min(circle_tilt, TILT_MAX)), now
        if 3.5 <= now < 11.0:  # the Circle runs (released at 10 over 1 s)
            below += circle_tilt < TILT_MAX
            above += circle_tilt > TILT_MAX
    assert below > 0
    assert above > 0
    cycle = [stage.lanes(free[k / 100].logical, 101, "tilt")[0] for k in range(450, 550)]
    assert max(cycle) - min(cycle) == pytest.approx(30.0)  # one cycle at full size: 15° each way
    assert min(cycle) > TILT_MAX  # …all above the limit


def test_the_fast_pulse_repeats_at_the_cap(stage: Stage, run: dict[float, Observation]) -> None:
    """The 8 Hz pulse runs at 3 Hz: the washes repeat every 1/3 s, not 1/8 s."""

    def wash(now: float) -> float:
        return stage.lanes(run[now].logical, 201, "intensity")[0]

    start, eighth, third, two_thirds = PULSE
    assert wash(third) == pytest.approx(wash(start), abs=1e-9)
    assert wash(two_thirds) == pytest.approx(wash(start), abs=1e-9)
    assert wash(eighth) != pytest.approx(wash(start), abs=1e-3)
    assert {stage.lanes(run[now].logical, 204, "intensity")[0] for now in PULSE} == {0.0}


def test_highlight_off_returns_to_the_live_look(
    run: dict[float, Observation], twin: dict[float, Observation]
) -> None:
    """At 8.5 (blackout off, highlight off, the grand master back) the frame
    is the twin's at the same time: the Circle and the pulse keep moving,
    so earlier frames differ."""
    assert run[8.5].universe == twin[8.5].universe
    assert run[8.4].universe != twin[8.4].universe


def test_a_live_park_holds_pan_and_unpark_brings_the_circle_back(
    stage: Stage, run: dict[float, Observation], twin: dict[float, Observation]
) -> None:
    for now in (9.0, 9.2, 9.49):
        logical, free = run[now].logical, twin[now].logical
        assert stage.lanes(logical, 101, "pan") == [0.0], now
        assert stage.lanes(logical, 101, "tilt") == stage.lanes(free, 101, "tilt"), now
        assert stage.lanes(logical, 101, "tilt")[0] <= TILT_MAX
    assert stage.lanes(twin[9.2].logical, 101, "pan") != [0.0]  # the Circle moves pan
    assert run[9.5].universe == twin[9.5].universe  # the circle's pan, at once


def test_after_release_all_the_stage_is_at_its_defaults(
    stage: Stage, run: dict[float, Observation]
) -> None:
    """Every playback released: what an engine with nothing up shows, park
    included (203 red, 204 dark)."""
    nothing = Harness(stage.compiled).tick(0.0)
    assert run[13.0].universe == nothing.universe
    assert np.array_equal(run[13.0].logical, nothing.logical, equal_nan=True)


def test_output_off_and_on(run: dict[float, Observation]) -> None:
    assert run[12.99].frame.outputEnabled is True
    off = run[13.0]
    assert off.frame.outputEnabled is False
    assert "| OUT off |" in status_line(snapshot(off))
    assert run[13.99].frame.outputEnabled is False
    assert run[14.0].frame.outputEnabled is True
    assert "OUT" not in status_line(snapshot(run[14.0]))


def test_output_off_terminates_the_stream_and_on_resends_the_frame(
    stage: Stage, receiver: Receiver
) -> None:
    """The performance with the show's route sent to a local receiver: from
    12.5 on, the scheduler services every tick. ``output off`` ends the
    stream with Stream_Terminated, then nothing; ``output on`` sends the
    current frame at once."""
    local = cast(Show, localhost_route(cast(dict[str, Any], stage.show)))
    compiled = compile_show(local)
    performance = Performance(Stage(local, compiled))
    sequences, artnet = Sequences(), ArtNetNetwork()
    routes, _ = build_routes(compiled.output, compiled.universes, sequences, artnet=artnet)
    scheduler = OutputScheduler(
        performance.harness.engine,
        routes,
        FakeClock(),
        layout=compiled.layout,
        sequences=sequences,
        artnet=artnet,
    )
    packets: dict[float, list[Any]] = {}

    def each(now: float) -> None:
        if now >= 12.5:
            scheduler.service(now)
            packets[now] = receiver.drain(0.02)

    try:
        seen = performance.run(timeline(), [k / 100 for k in range(1250, 1411)], each)
    finally:
        scheduler.close()
    before = [p for now, got in packets.items() if now < 13.0 for p in got]
    assert before
    assert not any(p.terminated for p in before)
    stopped = packets[13.0]
    assert stopped
    assert all(p.terminated for p in stopped)
    assert [p for now, got in packets.items() if 13.0 < now < 14.0 for p in got] == []
    again = packets[14.0]
    assert again
    assert not again[0].terminated
    assert again[0].data == seen[14.0].universe


# ------------------------------------------------------------- the frames


def channels(universe: bytes) -> dict[str, int]:
    """Non-zero channels, 1-based (JSON keys are strings)."""
    return {str(k + 1): value for k, value in enumerate(universe) if value}


def test_the_checkpoint_frames_match_the_golden(run: dict[float, Observation]) -> None:
    times = sorted({c.time for c in CHECKPOINTS} | {9.0, 9.5})
    frames = {f"{t:g}": channels(run[t].universe) for t in times}
    assert frames == golden("phase7_frames.json", frames)
    # Reviewed by hand. The heads are 16-channel from 1 and 17 (pan and tilt
    # 16-bit, colour RGBW, intensity 16-bit, zoom, gobo, shutter at offset
    # 12); the ML-56s 4-channel RGBW with a virtual dimmer from 33; the
    # PiX's 12 RGB cells from 49.

    def wash(seen: Observation, number: int) -> bytes:
        start = 32 + 4 * (number - 201)
        return seen.universe[start : start + 4]

    def bar(seen: Observation) -> bytes:
        return seen.universe[48:84]

    def head(seen: Observation, number: int) -> bytes:
        start = 16 * (number - 101)
        return seen.universe[start : start + 16]

    def byte(value: float) -> int:
        return round(value * 255)

    assert wash(run[0.3], 203) == bytes([byte(0.8), 0, 0, 0])  # parked red at 0.8
    assert wash(run[0.3], 204) == bytes(4)  # parked dark: every emitter 0
    assert wash(run[3.0], 201) == bytes([0, 0, 0, 255])  # white at full: the white emitter
    assert max(bar(run[3.0])) <= 128  # white at the 0.5 limit
    tilt = int.from_bytes(head(run[3.0], 101)[2:4])
    assert tilt == round((TILT_MAX + 135) / 270 * 65535)  # 10° on −135…135°
    # Strobe at 3 Hz on the shutter's 16–131 range for 1–20 Hz.
    assert head(run[5.0], 101)[12] == round(16 + (3 - 1) / (20 - 1) * (131 - 16))
    assert head(run[7.5], 102)[12] in range(8, 16)  # highlighted: open
    assert head(run[8.0], 102)[8:10] == bytes(2)  # blackout wins
    assert bar(run[8.0]) == bytes(36)


def test_an_irregular_schedule_gives_the_same_frames(
    stage: Stage, run: dict[float, Observation]
) -> None:
    generator = random.Random(7)
    ticks, now = [], 0.0
    while now < END:
        ticks.append(now)
        now += generator.uniform(0.001, 0.06)
    irregular = perform(stage, ticks)
    for time in TIMES:
        seen, expected = irregular[time], run[time]
        assert seen.universe == expected.universe, time
        assert np.array_equal(seen.logical, expected.logical, equal_nan=True), time


def test_save_load_and_a_fresh_engine_give_the_same_frames(
    build: Build, stage: Stage, run: dict[float, Observation]
) -> None:
    assert stage.show == build.session.show
    in_memory = Stage(build.session.show, compile_show(build.session.show))
    fresh = perform(in_memory)
    for time in TIMES:
        assert fresh[time].universe == run[time].universe, time
