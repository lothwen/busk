"""End to end: the real bridge and the app, headless.

* On a real show (``--standalone``, no output, no surfaces): a typed ``gm
  50%`` shows in the status bar; Space on F1 makes P1 active, and its row
  shows it; F2's group button, intensity bar and ``[+]``, and an F6 tile,
  program it; F6's PRESET panel records presets and changes them, and
  on the TupperDMX show records a colour from its picker and a beam preset
  from its option chips and bars; F4
  goes to a cue, and F5 adds, stops and removes an effect; F3 and F1's
  layouts A and C show the output, and select from it.
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

from textual import events
from textual.pilot import Pilot
from textual.widget import Widget
from tui_fakes import Stub, click_cell, column, drive

import busk
from busk_tui import attributes, colors, commands, config
from busk_tui.bridge import Bridge
from busk_tui.commands import Line, percent
from busk_tui.pages.busk_console import OutputGrid
from busk_tui.pages.busk_stack import StackLayout
from busk_tui.pages.busk_stage import StagePlot
from busk_tui.pages.presets import PresetsPage
from busk_tui.pages.program import EncoderPanel
from busk_tui.shell import BuskApp
from busk_tui.widgets.bars import HBar
from busk_tui.widgets.colorpicker import cell_color, rgb_of
from busk_tui.widgets.controls import ButtonStrip
from busk_tui.widgets.cuetable import CueTable
from busk_tui.widgets.dmxmap import DmxMap
from busk_tui.widgets.effects import EffectTable, TemplateTable
from busk_tui.widgets.encoders import EncoderBar, EncoderRow
from busk_tui.widgets.fixturetable import FixtureTable
from busk_tui.widgets.frame import StatusBar
from busk_tui.widgets.log import LogView
from busk_tui.widgets.options import LIT, OptionRow
from busk_tui.widgets.playbacks import PlaybackRow
from busk_tui.widgets.preset_panel import Chosen
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


async def tap(pilot: Pilot[int], widget: Widget, x: int = 0) -> None:
    """A click on ``widget`` (at cell ``x``), scrolled into sight first."""
    widget.scroll_visible(animate=False)
    await pilot.pause()
    await pilot.click(widget, offset=(x, 0))


async def tap_button(pilot: Pilot[int], strip: ButtonStrip, label: str) -> None:
    """A click on the button ``[label]`` of ``strip``."""
    strip.scroll_visible(animate=False)
    await pilot.pause()
    for y, line in enumerate(strip.lines(strip.size.width)):
        x = line.plain.find(f"[{label}]")
        if x >= 0:
            await pilot.click(strip, offset=(x + 1, y))
            return
    raise AssertionError(f"no button [{label}]")


def test_f6_records_and_changes_presets_from_controls_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """The PRESET panel only: an intensity preset (Heads, the bar,
    ``[record]``), a position preset at ``target`` (pan and tilt); then on
    it ``[its fixtures]``, ``[load]``, ``[+]`` and ``[merge]``; ``[remove]``
    with only tilt held; and ``[replace]``."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=6), standalone=True)

    def stored(pool: str, number: int) -> list[tuple[str, object, str, object]]:
        show = app.view.show
        presets = () if show is None else show.presets
        found = next((p for p in presets if p.pool == pool and p.number == number), None)
        return [] if found is None else [
            (e.scope, e.where, e.attribute, e.value) for e in found.entries
        ]  # fmt: skip

    def held(attribute: str) -> list[object]:
        values = () if app.programmer is None else app.programmer.values
        return [value.value for value in values if value.attribute == attribute]

    async def body(pilot: Pilot[int]) -> None:
        panel = app.query_one(PresetsPage).panel

        def row(attribute: str) -> EncoderRow:
            return next(r for r in panel.rows if r.encoder.attribute == attribute)

        await until(pilot, lambda: app.programmer is not None and bool(app.query(PresetTile)))
        record = next(t for t in app.query(PresetTile) if t.pool == "intensity")
        await pilot.click(record)
        await tap_button(pilot, panel.groups, "Heads")
        await until(pilot, lambda: app.programmer.selection == ((101, 1), (102, 1)))  # type: ignore[union-attr]
        bar = row("intensity").bar
        await tap(pilot, bar, bar.size.width // 2)
        await until(pilot, lambda: len(held("intensity")) == 2 and not panel.record.inert)
        level = held("intensity")[0]
        await tap(pilot, panel.record)
        await until(pilot, lambda: panel.chosen == Chosen("intensity", 1))
        assert stored("intensity", 1) == [("global", None, "intensity", level)]

        tiles = app.query(PresetTile)
        await pilot.click(next(t for t in tiles if t.pool == "position" and t.preset is None))
        assert panel.chosen == Chosen("position", 3, new=True)
        assert panel.scope() == "target"
        for attribute, x in (("pan", 3 / 4), ("tilt", 1 / 4)):
            bar = row(attribute).bar
            await tap(pilot, bar, round((bar.size.width - 1) * x))
        await until(pilot, lambda: len(held("pan")) == 2 and len(held("tilt")) == 2)
        pan, tilt = held("pan")[0], held("tilt")[0]
        await until(pilot, lambda: not panel.record.inert)
        await tap(pilot, panel.record)
        await until(pilot, lambda: panel.chosen == Chosen("position", 3))
        heads = ((101, 1), (102, 1))
        assert stored("position", 3) == [
            *(("target", head, "pan", pan) for head in heads),
            *(("target", head, "tilt", tilt) for head in heads),
        ]

        await tap(pilot, panel.clear)
        await until(pilot, lambda: not held("pan") and not app.programmer.selection)  # type: ignore[union-attr]
        await tap_button(pilot, panel.groups, "its fixtures")
        await until(pilot, lambda: app.programmer.selection == heads)  # type: ignore[union-attr]
        await tap(pilot, panel.load)
        await until(pilot, lambda: held("pan") == [pan, pan] and not row("pan").plus.inert)
        await tap(pilot, row("pan").plus)
        await until(pilot, lambda: held("pan") == [pan + 15, pan + 15])  # type: ignore[operator]
        await tap(pilot, panel.writes["merge"])
        await until(pilot, lambda: ("target", heads[0], "pan", pan + 15) in stored("position", 3))  # type: ignore[operator]
        assert [e[2] for e in stored("position", 3)] == ["pan", "pan", "tilt", "tilt"]

        await tap(pilot, panel.clear)
        await tap_button(pilot, panel.groups, "its fixtures")
        await until(pilot, lambda: app.programmer.selection == heads)  # type: ignore[union-attr]
        bar = row("tilt").bar
        await tap(pilot, bar, bar.size.width - 1)
        await until(pilot, lambda: len(held("tilt")) == 2 and not held("pan"))
        await tap(pilot, panel.writes["remove"])
        await until(pilot, lambda: [e[2] for e in stored("position", 3)] == ["pan", "pan"])
        await tap(pilot, panel.writes["replace"])
        top = held("tilt")[0]
        await until(pilot, lambda: [e[2] for e in stored("position", 3)] == ["tilt", "tilt"])
        assert stored("position", 3)[0] == ("target", heads[0], "tilt", top)
        log = [line for kind, line in app.query_one(LogView).entries if kind == "ui"]
        assert [line for line in log if line.startswith("record ")] == [
            "record preset intensity 1 global",
            "record preset position 3 target",
            "record preset position 3 target merge",
            "record preset position 3 remove",
            "record preset position 3 target replace",
        ]

    try:
        drive(app, body)
    finally:
        bridge.stop()


TUPPER = Path(__file__).resolve().parents[2] / "examples" / "tupperdmx" / "tupper-demo.show"


def test_f6_records_a_colour_from_the_picker_on_the_real_engine(tmp_path: Path) -> None:
    """TupperDMX, the PRESET panel only: ``[Pars]``, a click on the colour
    field, ``[record]``; the new preset then shows on F2's chips and F1's."""
    path = tmp_path / "tupper.show"
    path.write_bytes(TUPPER.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=6), standalone=True)

    def held() -> list[tuple[float, float, float]]:
        values = () if app.programmer is None else app.programmer.values
        return [rgb_of(v.value) for v in values if v.attribute == "color"]  # type: ignore[arg-type]

    def chip(strip: ButtonStrip) -> str | None:
        """The style of the chip of colour 5, if ``strip`` has one."""
        found = [b for b in strip.buttons if b.line.text == "preset color 5"]
        return str(found[0].label.style) if found else None

    async def body(pilot: Pilot[int]) -> None:
        panel = app.query_one(PresetsPage).panel
        await until(pilot, lambda: app.programmer is not None and bool(app.query(PresetTile)))
        tiles = app.query(PresetTile)
        await pilot.click(next(t for t in tiles if t.pool == "color" and t.preset is None))
        assert panel.chosen == Chosen("color", 5, new=True)
        await tap_button(pilot, panel.groups, "Pars")
        pars = ((401, 1), (402, 1), (403, 1))
        await until(pilot, lambda: app.programmer.selection == pars)  # type: ignore[union-attr]
        (picker,) = panel.pickers
        field = picker.field
        field.scroll_visible(animate=False)
        await pilot.pause()
        x = field.size.width // 3
        await pilot.click(field, offset=(x, 3))
        rgb = cell_color(x, 3, field.size.width)
        await until(pilot, lambda: held() == [rgb] * 3 and not panel.record.inert)
        await tap(pilot, panel.record)
        await until(pilot, lambda: panel.chosen == Chosen("color", 5))
        show = app.view.show
        assert show is not None
        preset = next(p for p in show.presets if p.pool == "color" and p.number == 5)
        assert [(e.scope, e.where, e.attribute, rgb_of(e.value)) for e in preset.entries] == [  # type: ignore[arg-type]
            ("global", None, "color", rgb)
        ]
        swatch = colors.swatch(rgb, 1.0, app.view.mode)
        await pilot.press("f2")
        f2 = next(p for p in app.query(EncoderPanel) if p.family == "color")
        assert f2.chips is not None
        await until(pilot, lambda: chip(f2.chips) == swatch)  # type: ignore[arg-type]
        await pilot.press("f1")
        await until(pilot, lambda: chip(app.query_one(StackLayout).chips) == swatch)
        log = [line for kind, line in app.query_one(LogView).entries if kind == "ui"]
        assert log == ["sel group 3", commands.set_color(*rgb).text, "record preset color 5 global"]

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f6_records_a_beam_preset_with_a_gobo_on_the_real_engine(tmp_path: Path) -> None:
    """TupperDMX, the PRESET panel only: the heads, ``[star]``, the zoom
    and rotation bars, ``[record]`` at the beam pool's ``profile``; then the
    blinders' ``[soundActive]`` and their effect rate."""
    path = tmp_path / "tupper.show"
    path.write_bytes(TUPPER.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=6), standalone=True)

    def held(attribute: str) -> list[object]:
        values = () if app.programmer is None else app.programmer.values
        return [value.value for value in values if value.attribute == attribute]

    async def body(pilot: Pilot[int]) -> None:
        panel = app.query_one(PresetsPage).panel

        def row(attribute: str) -> EncoderRow:
            return next(r for r in panel.rows if r.encoder.attribute == attribute)

        def options(attribute: str) -> OptionRow:
            return next(r for r in panel.options if r.attribute == attribute)

        def lit(found: OptionRow) -> list[str]:
            buttons = found.chips.buttons
            return [b.label.plain for b in buttons if str(b.label.spans[0].style) == LIT]

        await until(pilot, lambda: app.programmer is not None and bool(app.query(PresetTile)))
        tiles = app.query(PresetTile)
        await pilot.click(next(t for t in tiles if t.pool == "beam" and t.preset is None))
        assert panel.scope() == "profile"
        await tap_button(pilot, panel.groups, "Heads")
        heads = ((501, 1), (502, 1), (503, 1), (504, 1))
        await until(pilot, lambda: app.programmer.selection == heads)  # type: ignore[union-attr]
        await until(pilot, lambda: bool(options("gobo1").chips.buttons))
        await tap_button(pilot, options("gobo1").chips, "star")
        await until(pilot, lambda: held("gobo1") == ["star"] * 4)
        await until(pilot, lambda: lit(options("gobo1")) == ["[star]"])
        for attribute, x in (("zoom", 1 / 2), ("gobo1Rotation", 3 / 4)):
            bar = row(attribute).bar
            await tap(pilot, bar, round((bar.size.width - 1) * x))
        await until(pilot, lambda: len(held("zoom")) == 4 and len(held("gobo1Rotation")) == 4)
        zoom, turn = held("zoom")[0], held("gobo1Rotation")[0]
        assert turn > 0  # type: ignore[operator]
        await tap(pilot, panel.record)
        await until(pilot, lambda: panel.chosen == Chosen("beam", 1))
        show = app.view.show
        assert show is not None
        preset = next(p for p in show.presets if p.pool == "beam" and p.number == 1)
        head = "TupperDMX Moving Head"
        assert sorted((e.scope, e.where, e.attribute, e.value) for e in preset.entries) == [
            ("profile", head, "gobo1", "star"),
            ("profile", head, "gobo1Rotation", turn),
            ("profile", head, "zoom", zoom),
        ]

        await tap_button(pilot, panel.groups, "Blinders")
        await until(pilot, lambda: len(app.programmer.selection) == 8)  # type: ignore[union-attr]
        await until(pilot, lambda: bool(options("effect").chips.buttons))
        await tap_button(pilot, options("effect").chips, "soundActive")
        await until(pilot, lambda: held("effect") == ["soundActive"] * 2)  # one cell of each
        bar = row("effectRate").bar
        await until(pilot, lambda: bar.settable)
        await tap(pilot, bar, bar.size.width - 1)
        await until(pilot, lambda: held("effectRate") == [1.0] * 2)
        log = [line for kind, line in app.query_one(LogView).entries if kind == "ui"]
        assert log == [
            "sel group 4",
            "set gobo1 star",
            f"set zoom {commands.number(zoom)}",  # type: ignore[arg-type]
            f"set gobo1Rotation {commands.number(turn)}",  # type: ignore[arg-type]
            "record preset beam 1 profile",
            "sel group 2",
            "set effect soundActive",
            "set effectRate 100%",
        ]

    try:
        drive(app, body)
    finally:
        bridge.stop()


def scroll(widget: Widget, *, up: bool) -> events.MouseEvent:
    """A wheel notch on ``widget``."""
    kind = events.MouseScrollUp if up else events.MouseScrollDown
    return kind(widget, 0, 0, 0, 0, 0, False, False, False)


async def reach(
    pilot: Pilot[int],
    bar: EncoderBar,
    steps: tuple[Widget, Widget],
    span: tuple[float, float],
    target: float,
    now: Callable[[], float | None],
) -> None:
    """``target`` (degrees) from controls only: the bar's nearest cell that
    is a whole number of wheel notches (5°) away, then ``[−]`` or ``[+]``
    (15°), then the wheel; ``now`` reads the value the programmer holds."""

    def value_at(x: int) -> float:
        return attributes.to_value(bar.level_at(x), span, "degrees")

    cells = [x for x in range(bar.size.width) if (target - value_at(x)) % 5 == 0]
    x = min(cells, key=lambda x: abs(target - value_at(x)))
    await tap(pilot, bar, x)
    await until(pilot, lambda: now() == value_at(x))
    change = round(target - value_at(x))
    minus, plus = steps
    for _ in range(abs(change) // 15):
        await tap(pilot, plus if change > 0 else minus)
    for _ in range(abs(change) % 15 // 5):
        bar.post_message(scroll(bar, up=change > 0))
    await until(pilot, lambda: now() == target)


def test_f6_rebuilds_the_audience_fan_from_controls_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """The club script's Audience (``set pan spread -30 30``, ``set tilt
    40``, recorded per target) rebuilt from the PRESET panel only: Heads,
    pan as a spread (its two bars and steps), tilt's bar, steps and wheel,
    then ``[record]``: the same stored values."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=6), standalone=True)

    def stored(number: int) -> list[tuple[str, object, str, object]]:
        show = app.view.show
        presets = () if show is None else show.presets
        found = next(p for p in presets if p.pool == "position" and p.number == number)
        return [(e.scope, e.where, e.attribute, e.value) for e in found.entries]

    def held_on(attribute: str, number: int) -> float | None:
        values = () if app.programmer is None else app.programmer.values
        found = (v.value for v in values if v.attribute == attribute and v.number == number)
        value = next(found, None)
        return value if isinstance(value, float) else None

    async def body(pilot: Pilot[int]) -> None:
        panel = app.query_one(PresetsPage).panel
        await until(pilot, lambda: app.programmer is not None and bool(app.query(PresetTile)))
        tiles = app.query(PresetTile)
        await pilot.click(next(t for t in tiles if t.pool == "position" and t.preset is None))
        assert panel.chosen == Chosen("position", 3, new=True)
        assert panel.scope() == "target"
        await tap_button(pilot, panel.groups, "Heads")
        await until(pilot, lambda: app.programmer.selection == ((101, 1), (102, 1)))
        await tap_button(pilot, panel.spread_lines[0].chips, "pan")
        fan = next(row for row in panel.spreads if row.encoder.attribute == "pan")
        await until(pilot, lambda: fan.display and fan.reading is not None)
        assert fan.reading is not None
        for end, target, number in ((0, -30.0, 101), (1, 30.0, 102)):
            part = fan.ends[end]
            await reach(pilot, part.bar, (part.minus, part.plus), fan.reading.span, target,
                        lambda number=number: held_on("pan", number))  # type: ignore[misc]  # fmt: skip
        tilt = next(row for row in panel.rows if row.encoder.attribute == "tilt")
        assert tilt.reading is not None
        await reach(pilot, tilt.bar, (tilt.minus, tilt.plus), tilt.reading.span, 40.0,
                    lambda: held_on("tilt", 102))  # fmt: skip
        assert [end.shown.plain for end in fan.ends] == ["-30°", "30°"]
        await until(pilot, lambda: not panel.record.inert)
        await tap(pilot, panel.record)
        await until(pilot, lambda: panel.chosen == Chosen("position", 3))
        assert sorted(stored(3), key=str) == sorted(stored(1), key=str)  # Audience's
        log = [line for kind, line in app.query_one(LogView).entries if kind == "ui"]
        assert "record preset position 3 target" in log
        assert any(line.startswith("set pan spread ") for line in log)

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f4_and_f5_run_cues_and_effects_on_the_real_engine(club_path: Path, tmp_path: Path) -> None:
    """F4: a cue row goes to that cue, and ``▶`` follows. F5: a template
    adds a programmer effect to the selection, its state stops it, and ✕
    removes it."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=4), standalone=True)

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.live is not None and app.view.show is not None)
        app._select_playback(9)
        cues = app.query_one(CueTable)
        await until(pilot, lambda: column(cues, "cue")[:1] == ["9/1"])
        await click_cell(pilot, cues, 2, "name")
        await until(pilot, lambda: app.live.playback(9).cue == "3", timeout=1.0)  # type: ignore[union-attr]
        await until(pilot, lambda: column(cues, "marker")[2] == "▶", timeout=1.0)
        assert ("ui", "goto 9 3") in app.query_one(LogView).entries
        await pilot.press("f5", *"sel group 1", "enter")
        await until(pilot, lambda: bool(app.programmer and app.programmer.selection))
        templates = app.query_one(TemplateTable)
        await click_cell(pilot, templates, 0, "name")  # Circle
        await until(pilot, lambda: bool(app.programmer and app.programmer.effects), timeout=1.0)
        table = app.query_one(EffectTable)
        await until(pilot, lambda: column(table, "owner")[-1:] == ["prog"], timeout=1.0)
        row = len(table.rows) - 1
        await click_cell(pilot, table, row, "state")
        await until(pilot, lambda: bool(app.programmer and app.programmer.stopped), timeout=1.0)
        await until(pilot, lambda: column(table, "state")[row] == "[off]", timeout=1.0)
        await click_cell(pilot, table, row, "remove")
        await until(pilot, lambda: not app.programmer or not app.programmer.effects, timeout=1.0)
        log = app.query_one(LogView).entries
        assert ("ui", 'effect add "Circle"') in log
        assert any(kind == "ui" and line.startswith("effect stop ") for kind, line in log)

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f3_shows_the_real_output_and_f8_selects_from_the_map(
    club_path: Path, tmp_path: Path
) -> None:
    """F3: the programmer's level shows in the sheet, magenta, and a row
    click selects. F8: a click on a fixture's channels selects it."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=3), standalone=True)

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.view.show is not None and app.view.output is not None)
        await pilot.press(*"sel group 2", "enter", *"set intensity 40%", "enter")
        table = app.query_one(FixtureTable)
        await until(pilot, lambda: column(table, "intensity")[2:5] == ["40%"] * 3, timeout=1.0)
        assert column(table, "source")[2] == "prog"
        assert column(table, "marker")[2:6] == ["▸"] * 4
        await click_cell(pilot, table, 0, "name")
        await until(pilot, lambda: bool(app.programmer and app.programmer.selection == ((101, 1),)))
        await pilot.press("f8")
        await pilot.click(app.query(DmxMap).first(), offset=(5 + 32, 0))  # channel 33: 201
        await until(pilot, lambda: bool(app.programmer and app.programmer.selection == ((201, 1),)))
        assert ("ui", "sel fixture 201") in app.query_one(LogView).entries

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_layouts_a_and_c_show_the_real_output(club_path: Path, tmp_path: Path) -> None:
    """A: the programmer's level lights the washes in OUTPUT, and a click
    selects. C: a place typed at the prompt puts the fixture on the stage."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(layout="A"), standalone=True)

    def lit(grid: OutputGrid | StagePlot, number: int) -> bool:
        spot = next(spot for spot in grid.spots if spot.number == number)
        line = grid.lines[spot.y]
        styles = [str(s.style) for s in line.spans if spot.x <= s.start < spot.x + spot.width]
        return bool(styles) and f"color({colors.UNLIT})" not in styles

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.view.show is not None and app.view.output is not None)
        grid = app.query_one(OutputGrid)
        await until(pilot, lambda: bool(grid.spots))
        assert not lit(grid, 201)
        await pilot.press(*"sel group 2", "enter", *"set intensity 40%", "enter")
        await until(pilot, lambda: lit(grid, 201) and lit(grid, 202), timeout=1.0)
        assert not lit(grid, 204)  # parked dark
        spot = next(spot for spot in grid.spots if spot.number == 101)
        await pilot.click(grid, offset=(spot.x, spot.y))
        await until(pilot, lambda: bool(app.programmer and app.programmer.selection == ((101, 1),)))
        app.action_layout("C")
        place = '{"x": 1, "y": 2, "z": 5, "rx": 0, "ry": 0, "rz": 0}'
        await pilot.press(*f"fixture 202 location {place}", "enter")
        plot = app.query_one(StagePlot)
        await until(pilot, lambda: [row.y for row in plot.rows] == [2.0], timeout=1.0)
        assert plot.lines[0].plain.startswith("y 2.0")
        assert lit(plot, 202)
        assert "sel fixture 202" in [item.line for item in app.current_page.items()]

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
