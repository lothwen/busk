"""End to end: the real bridge and the app, headless.

* On a real show (``--standalone``, no output, no surfaces): a typed ``gm
  50%`` shows in the status bar; Space on F1 makes P1 active, and its row
  shows it; F2's group button, intensity bar and ``[+]``, and an F6 tile,
  program it.
* On a stub show whose ``save`` is held (plan §4.3): keys, page switching,
  the beat dot and a bar's drag keep working, the drag's lines run, and the
  prompt context shows the held line.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

from textual.pilot import Pilot
from tui_fakes import Stub, drive

import busk
from busk_tui import config
from busk_tui.bridge import Bridge
from busk_tui.commands import Line, percent
from busk_tui.shell import BuskApp
from busk_tui.widgets.bars import HBar
from busk_tui.widgets.encoders import EncoderRow
from busk_tui.widgets.frame import StatusBar
from busk_tui.widgets.log import LogView
from busk_tui.widgets.playbacks import PlaybackRow
from busk_tui.widgets.programmer import ProgrammerTable
from busk_tui.widgets.tiles import PresetTile

WAIT_S = 15.0


async def until(pilot: Pilot[int], test: Callable[[], bool], timeout: float = WAIT_S) -> None:
    deadline = time.monotonic() + timeout
    while not test():
        assert time.monotonic() < deadline, "timed out"
        await pilot.pause(0.05)


def test_a_typed_line_moves_the_real_engine(club_path: Path, tmp_path: Path) -> None:
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(), standalone=True)

    async def body(pilot: Pilot[int]) -> None:
        status = app.query_one(StatusBar)
        await until(pilot, lambda: status.title == "Club Night" and status.engine == "running")
        await pilot.press("g", "m", "space", "5", "0", "%", "enter")
        await until(pilot, lambda: "GM 50%" in status.left_text().plain, timeout=1.0)
        await pilot.press(*"blackout", "space", *"on", "enter")
        await until(pilot, lambda: app.live is not None and app.live.blackout, timeout=1.0)
        entries = list(app.query_one(LogView).entries)
        assert ("typed", "gm 50%") in entries
        assert ("typed", "blackout on") in entries

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_space_on_f1_runs_go_on_the_real_engine(club_path: Path, tmp_path: Path) -> None:
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(), standalone=True)

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.live is not None and app.view.show is not None)
        rows = {row.number: row for row in app.query(PlaybackRow)}
        assert sorted(n for n in rows if n is not None) == list(range(1, 14))
        await pilot.press("space")
        await until(pilot, lambda: app.live.playback(1).state == "active", timeout=1.0)  # type: ignore[union-attr]
        await pilot.press("right_square_bracket")
        await until(pilot, lambda: app.live.playback(1).level == 0.05, timeout=1.0)  # type: ignore[union-attr]
        await pilot.pause(0.1)
        assert str(rows[1].cue.render()) == "1/1 Warm"
        assert str(rows[1].level.render()) == "5"
        assert ("ui", "go 1") in app.query_one(LogView).entries

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f2_and_f6_program_the_real_engine(club_path: Path, tmp_path: Path) -> None:
    """A group button, a click on the intensity bar, ``[+]``, then a colour
    tile on F6: the programmer, its contents and the encoders follow."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=2), standalone=True)

    def held(attribute: str) -> list[object]:
        programmer = app.programmer
        values = () if programmer is None else programmer.values
        return [value.value for value in values if value.attribute == attribute]

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.programmer is not None and bool(app.query(EncoderRow)))
        await pilot.click("#program-groups", offset=(1, 0))  # [1 Heads]
        await until(pilot, lambda: app.programmer.selection == ((101, 1), (102, 1)))  # type: ignore[union-attr]
        row = next(r for r in app.query(EncoderRow) if r.encoder.attribute == "intensity")
        await pilot.click(row.bar, offset=(row.bar.size.width // 2, 0))
        await until(pilot, lambda: len(held("intensity")) == 2, timeout=1.0)
        level = held("intensity")[0]
        await until(pilot, lambda: not row.plus.inert, timeout=1.0)
        await pilot.click(row.plus)
        await until(pilot, lambda: held("intensity")[0] == round(level + 0.05, 9), timeout=1.0)  # type: ignore[operator]
        await until(pilot, lambda: row.pending is None, timeout=2.0)
        assert str(row.value.content) == f"{round((level + 0.05) * 100)}%"  # type: ignore[operator]
        await pilot.press("f6")
        await until(pilot, lambda: bool(app.query(PresetTile)))
        red = next(t for t in app.query(PresetTile) if t.line == "preset color 2")
        await pilot.click(red)
        await until(pilot, lambda: len(held("color")) == 2, timeout=1.0)
        await pilot.press("f2")  # only the page shown redraws: F2 now
        table = app.query_one(ProgrammerTable).content
        assert "Red" in str(table)
        assert ("ui", "preset color 2") in app.query_one(LogView).entries

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_a_held_line_never_freezes_the_ui() -> None:
    stub = Stub()
    gate = stub.gates["save"] = threading.Event()
    speed = busk.SpeedStatus(
        id="m-speed", name="Speed 1", bpm=60.0, multiplier=1.0, level=0.5, beatTime=0.0, beat=0.0
    )
    stub.snapshot = busk.EngineSnapshot(
        seq=1, time=0.0, grandMaster=1.0, blackout=False, playbacks=(), speed=(speed,)
    )
    bridge = Bridge(stub, None)  # type: ignore[arg-type]
    app = BuskApp(bridge, config.Settings())
    bar = HBar(command=lambda level: Line(f"gm {percent(level)}", True), key="gm", id="bar")

    async def body(pilot: Pilot[int]) -> None:
        status = app.query_one(StatusBar)
        await until(pilot, lambda: bool(bridge.help_lines))
        await app.query_one("#page-1").mount(bar)
        await pilot.press("s", "a", "v", "e", "enter")
        await until(pilot, lambda: bridge.busy is not None)
        await pilot.pause(0.4)
        app._show_context()
        assert app._context_text.startswith("⧗ save 0.")
        await pilot.press("f3")  # page switching
        assert app.page == 3
        await pilot.press("f1")
        for beat in (1.1, 1.5):  # the beat dot (engine time = beat at 60 BPM)
            stub.frame = SimpleNamespace(seq=int(beat * 100), time=beat)
            await until(pilot, lambda beat=beat: status.beats == beat, timeout=1.0)
        await pilot.press("g", "m")  # keys
        assert app.prompt.value == "gm"
        await pilot.mouse_down("#bar", offset=(0, 0))  # a drag: its lines run meanwhile
        await pilot.hover("#bar", offset=(10, 0))
        await pilot.mouse_up("#bar", offset=(20, 0))
        last = f"gm {percent(20 / (bar.size.width - 1))}"
        await until(pilot, lambda: last in stub.ran, timeout=1.0)
        assert "save" not in stub.ran
        assert ("ui", last) in app.query_one(LogView).entries  # logged once, on release
        gate.set()
        await until(pilot, lambda: "save" in stub.ran)

    try:
        drive(app, body)
    finally:
        gate.set()
        bridge.stop(timeout=1.0)
