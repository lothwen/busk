"""End to end: the real bridge and the app, headless.

* On a real show (``--standalone``, no output, no surfaces): a typed ``gm
  50%`` shows in the status bar; Space on F1 makes P1 active, and its row
  shows it; F2's group button, intensity bar and ``[+]``, and an F6 tile,
  program it; F6's PRESET panel records presets and changes them, asking
  before a replace or a remove, and
  on the TupperDMX show records a colour from its picker and a beam preset
  from its option chips and bars; F1 greys a goto its new list lacks; F4
  goes to a cue, builds and deletes cues and lists from its controls,
  edits a cue's timing, trigger and name in its dialogs, and toggles a
  list back to the chase busk stored, and
  F5 adds, stops and removes an effect and builds a template; F3 and F1's
  layouts A and C show the output, and select from it; F3's FIXTURE panel
  renames, renumbers and deletes a fixture, sets a profile's category, a
  fixture's mode, its limits, orientation and location, patches it, changes
  its profile and adds new ones from the library, patches and deletes a run of
  fixtures in one line each, imports a profile through the picker and brings
  a profile to the library's revision; F8 adds, renames, renumbers and deletes
  universes, edits a route through every protocol, and patches and adds at a
  place on its map; F7 makes a master of each kind, renames one, shows busk's
  refusal of one in use and deletes one a binding drives; a new show gets a rig
  from controls alone.
* On a running show with its output open (``--standalone``): F8 adds a route to
  a new universe, a fixture patched in it reaches a real receiver, and the route
  goes off, on and away.
* On a stub show whose ``save`` is held (plan §4.3): keys, page switching,
  the beat dot and a bar's drag keep working, the drag's lines run, and the
  prompt context shows the held line.
"""

from __future__ import annotations

import copy
import json
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from rich.text import Text
from textual import events
from textual.pilot import Pilot
from textual.widget import Widget
from textual.widgets import Input
from tui_fakes import Stub, click_cell, column, drive

import busk
from builders import channel, fixture, mode, profile, show_of
from builders import show as show_doc
from busk_tui import attributes, colors, commands, config
from busk_tui.bridge import Bridge
from busk_tui.commands import Line, percent
from busk_tui.model import (
    ChaseRate,
    CueInfo,
    CueListInfo,
    EffectInfo,
    EffectView,
    FamilyTiming,
    FixtureInfo,
    Orientation,
)
from busk_tui.pages.busk_console import OutputGrid
from busk_tui.pages.busk_stack import StackLayout
from busk_tui.pages.busk_stage import StageLayout, StagePlot
from busk_tui.pages.cues import CuesPage
from busk_tui.pages.fixtures import FixturesPage
from busk_tui.pages.masters import MastersPage
from busk_tui.pages.patch import (
    NO_CHANNELS,
    ChannelTable,
    PatchPage,
    RoutesTable,
    UniverseTable,
)
from busk_tui.pages.presets import PresetsPage
from busk_tui.pages.program import EncoderPanel
from busk_tui.shell import BuskApp
from busk_tui.widgets.bars import HBar
from busk_tui.widgets.chase_dialog import ChaseDialog
from busk_tui.widgets.colorpicker import cell_color, rgb_of
from busk_tui.widgets.controls import ActionButton, ButtonStrip, CommandButton
from busk_tui.widgets.cue_dialogs import CurveDialog, TimeDialog
from busk_tui.widgets.cuetable import CueTable
from busk_tui.widgets.dialogs import ConfirmDialog, FormDialog, TextDialog
from busk_tui.widgets.dmxmap import DmxMap
from busk_tui.widgets.effect_panel import EffectPanel, EffectRateDialog
from busk_tui.widgets.effects import EffectTable, TemplateTable
from busk_tui.widgets.encoders import EncoderBar, EncoderRow
from busk_tui.widgets.fixturetable import FixtureTable
from busk_tui.widgets.frame import StatusBar
from busk_tui.widgets.log import LogView
from busk_tui.widgets.master_panel import MasterDialog
from busk_tui.widgets.options import LIT, OptionRow
from busk_tui.widgets.playback_panel import (
    CueListDialog,
    PickDialog,
    PlaybackDialog,
    PlaybackEditor,
    PlaybackPanel,
)
from busk_tui.widgets.playbacks import PlaybackRow
from busk_tui.widgets.preset_panel import Chosen
from busk_tui.widgets.profile_picker import ProfileDialog
from busk_tui.widgets.programmer import ProgrammerTable
from busk_tui.widgets.prompt import HintRow
from busk_tui.widgets.route_dialog import RouteDialog
from busk_tui.widgets.template_panel import NewTemplateDialog, TemplatePanel
from busk_tui.widgets.tiles import PresetTile
from sacn_receiver import Receiver

WAIT_S = 15.0


def plain_of(widget: Widget) -> str:
    """The text a ``Static`` shows."""
    content = widget.content  # type: ignore[attr-defined]
    return content.plain if isinstance(content, Text) else str(content)


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


def test_f8_builds_and_deletes_a_universe_from_controls_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=8), standalone=True)

    def universes() -> list[tuple[int, str]]:
        show = app.view.show
        return [] if show is None else [(u.number, u.name) for u in show.universes]

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: universes() == [(1, "Stage")])
        page = app.query_one(PatchPage)
        table = app.query_one(UniverseTable)
        await until(pilot, lambda: len(table.rows) == 1)
        strip = page.universe_edits

        await tap_button(pilot, strip, "+ universe…")
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        assert isinstance(app.screen, FormDialog)
        assert app.screen.inputs[0].value == "2"
        await pilot.press("tab", *"Balcony", "enter")
        await until(pilot, lambda: universes() == [(1, "Stage"), (2, "Balcony")])
        await until(pilot, lambda: column(table, "name") == ["Stage", "Balcony"])
        assert len(app.query(DmxMap)) == 2

        await click_cell(pilot, table, 1, "name")
        await until(pilot, lambda: page.chosen == 2)
        await tap_button(pilot, strip, "rename…")
        await until(pilot, lambda: isinstance(app.screen, TextDialog))
        await pilot.press(*'The "Roof"', "enter")
        await until(pilot, lambda: universes()[1] == (2, 'The "Roof"'))

        await tap_button(pilot, strip, "number…")
        await until(pilot, lambda: isinstance(app.screen, TextDialog))
        await pilot.press("7", "enter")
        await until(pilot, lambda: universes()[1] == (7, 'The "Roof"'))
        await until(pilot, lambda: [m.universe for m in app.query(DmxMap)] == [1, 7])
        await until(pilot, lambda: column(table, "number") == ["1", "7"])
        assert page.chosen == 7  # the choice followed
        assert table.chosen == 1

        await tap_button(pilot, strip, "delete")
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        assert isinstance(app.screen, ConfirmDialog)
        assert app.screen.question == r"""Delete universe 7 "The \"Roof\""?"""
        await pilot.press("y")
        await until(pilot, lambda: universes() == [(1, "Stage")])
        await until(pilot, lambda: len(app.query(DmxMap)) == 1)
        assert page.chosen is None
        assert [button.label.plain for button in strip.buttons] == ["[+ universe…]"]

        await click_cell(pilot, table, 0, "name")  # the one the rig and the route are on
        await until(pilot, lambda: page.chosen == 1)
        await tap_button(pilot, strip, "delete")
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        assert isinstance(app.screen, ConfirmDialog)
        assert "7 fixtures lose their patch and 1 route goes" in app.screen.question
        await pilot.press("y")
        await until(pilot, lambda: universes() == [])
        await until(pilot, lambda: len(app.query(DmxMap)) == 0)
        show = app.view.show
        assert show is not None
        assert all(fixture.patch is None for fixture in show.fixtures)
        await until(pilot, lambda: app.view.routes == ())
        await pilot.press(*"undo", "enter")  # one step takes it all back
        await until(pilot, lambda: universes() == [(1, "Stage")])
        await until(pilot, lambda: len(app.view.routes) == 1)
        show = app.view.show
        assert show is not None
        assert all(fixture.patch is not None for fixture in show.fixtures)
        await until(pilot, lambda: len(app.query(DmxMap)) == 1)
        assert app.query_one(DmxMap).prints

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f3_renames_renumbers_recategorises_and_deletes_from_controls_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=3), standalone=True)

    def numbers() -> list[int]:
        show = app.view.show
        return [] if show is None else [f.number for f in show.fixtures]

    def stored(number: int) -> FixtureInfo | None:
        return None if app.view.show is None else app.view.show.fixture(number)

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: 101 in numbers())
        page = app.query_one(FixturesPage)
        panel = page.panel
        await tap(pilot, page.edit)
        await until(pilot, lambda: page.editing and len(page.rig.rows) == 7)
        await click_cell(pilot, page.rig, 0, "name")
        await until(pilot, lambda: panel.fixture() is not None and panel.selected == {101})
        assert ("ui", "sel fixture 101") in app.query_one(LogView).entries

        await tap(pilot, panel.rename)
        await until(pilot, lambda: isinstance(app.screen, TextDialog))
        await pilot.press(*'The "Left" one', "enter")
        await until(pilot, lambda: stored(101).name == 'The "Left" one')  # type: ignore[union-attr]
        await until(pilot, lambda: column(page.rig, "name")[0] == 'The "Left" one')

        await tap(pilot, panel.renumber)
        await until(pilot, lambda: isinstance(app.screen, TextDialog))
        await pilot.press(*"150", "enter")
        await until(pilot, lambda: 150 in numbers())
        await until(pilot, lambda: column(page.rig, "number")[1] == "150")  # by number: after 102
        await until(pilot, lambda: panel.chosen == 150)  # the choice followed
        await until(pilot, lambda: "150" in str(panel.border_title))

        await tap_button(pilot, panel.categories, "wash")
        await until(pilot, lambda: column(page.rig, "category")[:2] == ["wash", "wash"])
        assert str(panel.categories.buttons[2].label.spans[0].style) == LIT

        await tap(pilot, panel.delete)
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        assert isinstance(app.screen, ConfirmDialog)
        assert "Delete fixture 150?" in app.screen.question
        assert "groups 1, 4" in app.screen.question
        await pilot.press("n")
        await until(pilot, lambda: not isinstance(app.screen, ConfirmDialog))
        await pilot.pause(0.2)
        assert 150 in numbers()
        await tap(pilot, panel.delete)
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.press("y")
        await until(pilot, lambda: 150 not in numbers())
        await until(pilot, lambda: panel.chosen is None)
        assert panel.hint.display
        await until(pilot, lambda: len(page.rig.rows) == 6)

        await pilot.press(*"undo", "enter")  # one step takes it all back
        await until(pilot, lambda: 150 in numbers())
        await until(pilot, lambda: len(page.rig.rows) == 7)
        assert panel.chosen is None
        await tap(pilot, panel.done)
        await until(pilot, lambda: page.table.display and len(page.table.rows) == 7)

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f3_and_f7_record_groups_park_and_unpark_from_controls_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """GROUPS records, merges, removes, renames, renumbers and deletes; PARK
    holds two pixels of the bar; F3's source column reads park; F7 unparks
    one row, then everything; ``undo`` brings it back (pending plan Phase 12)."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=3), standalone=True)

    def group(number: int) -> Any:
        return None if app.view.show is None else app.view.show.group(number)

    def parked() -> list[tuple[int, int, str]]:
        show = app.view.show
        return [] if show is None else [(p.number, p.element, p.attribute) for p in show.park]

    async def answer(pilot: Pilot[int], key: str) -> None:
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.press(key)
        await until(pilot, lambda: not isinstance(app.screen, ConfirmDialog))

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: group(4) is not None)
        page = app.query_one(FixturesPage)
        await until(pilot, lambda: column(page.table, "source")[5:6] == ["park"])  # wash 4

        await tap(pilot, page.edit)
        await until(pilot, lambda: page.editing and len(page.groups.table.rows) == 4)
        groups, panel = page.groups, page.panel
        assert column(groups.table, "members")[3] == "101 thru 102, 201 thru 204, 301"
        await click_cell(pilot, page.rig, 6, "name")  # the bar, all of it
        await until(pilot, lambda: not groups.record.inert)
        await tap(pilot, groups.record)
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await pilot.press("tab", *"Pixels", "enter")
        await until(pilot, lambda: group(5) is not None and groups.chosen == 5)
        assert group(5).members == tuple((301, element) for element in range(1, 13))
        await until(pilot, lambda: str(groups.label.content) == "group 5 Pixels")

        await pilot.click(page.rig, offset=(10, 1), shift=True)  # and 101
        await until(pilot, lambda: not groups.writes["merge"].inert)
        await tap(pilot, groups.writes["merge"])
        await until(pilot, lambda: len(group(5).members) == 13)
        await click_cell(pilot, page.rig, 0, "name")  # 101 alone
        await until(pilot, lambda: groups.writes["merge"].inert)
        await tap(pilot, groups.writes["remove"])
        await answer(pilot, "y")
        await until(pilot, lambda: len(group(5).members) == 12)

        await tap(pilot, groups.rename)
        await until(pilot, lambda: isinstance(app.screen, TextDialog))
        await pilot.press("ctrl+u", *"Bar too", "enter")
        await until(pilot, lambda: group(5).name == "Bar too")
        await tap(pilot, groups.renumber)
        await until(pilot, lambda: isinstance(app.screen, TextDialog))
        await pilot.press("ctrl+u", "7", "enter")
        await until(pilot, lambda: group(7) is not None and groups.chosen == 7)
        await until(pilot, lambda: str(groups.label.content) == "group 7 Bar too")
        await tap(pilot, groups.delete)
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        assert app.screen.question == 'Delete group 7 "Bar too"?'  # type: ignore[attr-defined]
        await answer(pilot, "y")
        await until(pilot, lambda: group(7) is None and groups.chosen is None)
        await pilot.press(*"delete fixture 301 cascade", "enter")  # Bar left with no members
        await answer(pilot, "y")
        await until(pilot, lambda: column(groups.table, "members")[2] == "—")
        await pilot.press(*"undo", "enter")
        await until(pilot, lambda: column(groups.table, "members")[2] == "301")

        await click_cell(pilot, page.rig, 6, "name")  # the bar chosen,
        await pilot.press(*"sel fixture 301.2 thru 301.3", "enter")  # two of its pixels selected
        await until(pilot, lambda: panel.park_where() == "301.2 thru 301.3")
        await tap(pilot, panel.park)
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await pilot.press("enter")  # intensity 0
        await until(pilot, lambda: (301, 3, "intensity") in parked())
        assert parked() == [
            (204, 1, "intensity"), (203, 1, "color"), (301, 2, "intensity"), (301, 3, "intensity"),
        ]  # fmt: skip
        await until(pilot, lambda: "intensity 0% · 301.2 thru 301.3" in str(panel.parked.content))
        await tap(pilot, panel.done)
        await until(pilot, lambda: column(page.table, "source")[6:7] == ["park"])

        await pilot.press("f7")
        masters = app.query_one(MastersPage)
        await until(pilot, lambda: len(masters.parked.unparks) == 3)
        assert [b.line.text for b in masters.parked.unparks] == [
            "unpark fixture 203 color",
            "unpark fixture 204 intensity",
            "unpark fixture 301.2 thru 301.3 intensity",
        ]
        await tap(pilot, masters.parked.unparks[2])
        await until(pilot, lambda: len(parked()) == 2)
        await until(pilot, lambda: len(masters.parked.unparks) == 2)
        await tap(pilot, masters.parked.unpark_all)
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        assert app.screen.question == "Unpark everything? Park holds 2 values."  # type: ignore[attr-defined]
        await answer(pilot, "y")
        await until(pilot, lambda: parked() == [] and masters.parked.unpark_all.inert)
        await pilot.press(*"undo", "enter")
        await until(pilot, lambda: len(parked()) == 2 and len(masters.parked.unparks) == 2)
        await pilot.press("f3")
        await until(pilot, lambda: column(page.table, "source")[5:6] == ["park"])
        assert str(page.table.rows[0]["pan"].spans[0].style) != colors.AMBER
        await pilot.press(*"park fixture 101 tilt 0", "enter")  # one attribute: all the position
        await until(pilot, lambda: str(page.table.rows[0]["pan"].spans[0].style) == colors.AMBER)

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f7_makes_renames_and_deletes_masters_from_controls_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """MASTERS adds one of each kind through its form, renames one, shows busk's
    refusal of a master a chase and effects use, and deletes one a binding
    drives, after busk's question; ``undo`` brings it back (pending plan Phase
    35)."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=7), standalone=True)

    def masters() -> dict[str, Any]:
        show = app.view.show
        return {} if show is None else {master.name: master for master in show.masters}

    def bound() -> int:
        show = app.view.show
        return 0 if show is None else sum(b.what == 'master "Huge"' for b in show.bindings)

    def tempo(name: str) -> float | None:
        live = app.view.live
        return None if live is None else next((s.bpm for s in live.speed if s.name == name), None)

    async def control(pilot: Pilot[int], name: str, kind: str) -> None:
        """A click on master ``name``'s ``[rename…]`` or ``[delete]``."""
        page = app.query_one(MastersPage)
        await until(pilot, lambda: name in [m.name for m in page.setup.masters])
        index = [m.name for m in page.setup.masters].index(name)
        buttons = page.setup.renames if kind == "rename" else page.setup.deletes
        await tap(pilot, buttons[index])

    async def add(pilot: Pilot[int], kind: str, *keys: str) -> None:
        await tap(pilot, app.query_one(MastersPage).setup.add)
        await until(pilot, lambda: isinstance(app.screen, MasterDialog))
        app.screen.kind.pick(kind)  # type: ignore[attr-defined]
        await pilot.press(*keys)

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: "Speed 1" in masters())
        await add(pilot, "speed", *"Beat", "tab", "end", "ctrl+u", *"128", "enter")
        await until(pilot, lambda: "Beat" in masters())
        await add(pilot, "size", *"Big", "enter")
        await add(pilot, "group", *"Pair level", "tab", "right", "enter")  # group 2
        await add(pilot, "fadetime", *"Slow fades", "enter")
        await until(pilot, lambda: {"Big", "Pair level", "Slow fades"} <= set(masters()))
        made = {name: masters()[name] for name in ("Beat", "Big", "Pair level", "Slow fades")}
        assert [(m.kind, m.steps) for m in made.values()] == [
            ("speed", (0.25, 0.5, 1.0, 2.0, 4.0)), ("size", ()), ("group", ()), ("fadeTime", ()),
        ]  # fmt: skip
        assert made["Pair level"].group is not None
        assert made["Pair level"].group.number == 2
        await until(pilot, lambda: tempo("Beat") == 128)

        await control(pilot, "Big", "rename")
        await until(pilot, lambda: isinstance(app.screen, TextDialog))
        await pilot.press("ctrl+u", *"Huge", "enter")
        await until(pilot, lambda: "Huge" in masters() and "Big" not in masters())

        log = app.query_one(LogView)
        await control(pilot, "Speed 1", "delete")
        refusal = (
            'error: master "Speed 1" is used by the chase of cue list 10 and effects in cues '
            "11/1, 12/1, 13/1: change them first"
        )
        await until(pilot, lambda: ("error", refusal.removeprefix("error: ")) in log.entries)
        assert not isinstance(app.screen, ConfirmDialog)
        assert "Speed 1" in masters()

        await pilot.press(*'bind "nanoKONTROL2" cc 1 99 master "Huge"', "enter")
        await until(pilot, lambda: bound() == 1)
        await control(pilot, "Huge", "delete")
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        question = 'Delete master "Huge"? It leaves 1 binding.'
        assert app.screen.question == question  # type: ignore[attr-defined]
        await pilot.press("y")
        await until(pilot, lambda: "Huge" not in masters() and bound() == 0)
        await pilot.press(*"undo", "enter")
        await until(pilot, lambda: "Huge" in masters() and bound() == 1)
        setup = app.query_one(MastersPage).setup
        await until(pilot, lambda: "Huge" in [m.name for m in setup.masters])

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f3_changes_a_mode_and_shows_busks_refusal_on_the_real_engine(tmp_path: Path) -> None:
    """No shipped profile has two modes, so this rig has its own: fixture 2
    sits near the end of the universe, where the wide mode does not fit."""
    small = {**mode([channel(0, "intensity")], mode_id="mode-1"), "name": "One Channel"}
    wide = {**mode([channel(0, "intensity")], mode_id="mode-20", footprint=20), "name": "20ch"}
    doc = show_doc(
        [{**profile("prof-two", small, wide), "name": "Two Mode Par"}],
        [
            fixture("fx-1", 1, "prof-two", 1, mode_id="mode-1"),
            fixture("fx-2", 2, "prof-two", 505, mode_id="mode-1"),
        ],
    )
    path = tmp_path / "two.show"
    assert busk.OfflineShow(show_of(doc), path=path).execute("save").ok
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=3), standalone=True)

    def mode_of(number: int) -> str:
        show = app.view.show
        found = None if show is None else show.fixture(number)
        return "" if found is None else found.mode

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: mode_of(1) == "One Channel")
        page = app.query_one(FixturesPage)
        panel = page.panel
        await tap(pilot, page.edit)
        await until(pilot, lambda: page.editing and len(page.rig.rows) == 2)
        await click_cell(pilot, page.rig, 1, "name")
        await until(pilot, lambda: panel.modes.display)
        await tap_button(pilot, panel.modes, "20ch")
        log = app.query_one(LogView)
        await until(pilot, lambda: any(kind == "error" for kind, _ in log.entries))
        assert any(kind == "error" and "512" in text for kind, text in log.entries)
        assert mode_of(2) == "One Channel"
        await click_cell(pilot, page.rig, 0, "name")
        await until(pilot, lambda: panel.chosen == 1)
        await tap_button(pilot, panel.modes, "20ch")
        await until(pilot, lambda: mode_of(1) == "20ch")
        await until(pilot, lambda: "20 channels" in str(panel.what.content))

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f3_sets_limits_orientation_and_location_from_controls_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """Heads 101 and 102 selected: one limit line, a line per fixture for
    orientation; then each stored value, and the place on F1 C's plot."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=3), standalone=True)

    def stored(number: int) -> FixtureInfo:
        show = app.view.show
        found = None if show is None else show.fixture(number)
        assert found is not None
        return found

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.view.show is not None)
        page = app.query_one(FixturesPage)
        panel = page.panel
        log = app.query_one(LogView)
        await tap(pilot, page.edit)
        await until(pilot, lambda: page.editing and len(page.rig.rows) == 7)
        await click_cell(pilot, page.rig, 0, "name")
        await until(pilot, lambda: panel.selected == {101})
        await pilot.click(page.rig, offset=(10, 2), shift=True)
        await until(pilot, lambda: panel.selected == {101, 102})
        assert panel.chosen == 102
        assert str(panel.limits_heading.content) == "LIMITS · 101 thru 102 (2)"

        ask, drop = panel.limits["pan"].buttons
        await tap(pilot, ask)
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        assert isinstance(app.screen, FormDialog)
        low, high = (float(field.value) for field in app.screen.inputs)
        assert (low, high) == (-270.0, 270.0)  # the profile's: none set here yet
        await pilot.press(*"-100", "tab", *"100", "enter")
        await until(pilot, lambda: stored(102).limits.pan == (-100.0, 100.0))
        assert stored(101).limits.pan == (-100.0, 100.0)
        assert stored(101).limits.tilt == (-90.0, 10.0)  # the others stay
        assert ("ui", "fixture 101 thru 102 limits pan -100 100") in log.entries

        await tap(pilot, panel.limits["intensity"].buttons[0])
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await pilot.press(*"60", "enter")
        await until(pilot, lambda: stored(101).limits.intensity == 0.6)
        await until(pilot, lambda: column(page.rig, "limits")[:2] == ["pan tilt int"] * 2)

        await until(pilot, lambda: drop.display)
        await tap(pilot, drop)
        await until(pilot, lambda: stored(102).limits.pan is None)
        assert stored(101).limits.tilt == (-90.0, 10.0)
        assert stored(101).limits.intensity == 0.6
        await tap(pilot, panel.no_limits)
        await until(pilot, lambda: column(page.rig, "limits")[:2] == ["", ""])

        await tap(pilot, panel.toggles["invertPan"])
        await until(pilot, lambda: stored(102).orientation.invertPan)
        await until(pilot, lambda: stored(101).orientation.invertPan)
        await until(pilot, lambda: panel.toggles["invertPan"].reverse)
        await tap(pilot, panel.toggles["swapPanTilt"])
        await until(pilot, lambda: stored(101).orientation.swapPanTilt)
        await tap(pilot, panel.offsets["tiltOffset"].buttons[0])
        await until(pilot, lambda: isinstance(app.screen, TextDialog))
        await pilot.press(*"15.5", "enter")
        await until(pilot, lambda: stored(101).orientation.tiltOffset == 15.5)
        assert stored(102).orientation.tiltOffset == 15.5
        assert stored(201).orientation == Orientation()

        await tap(pilot, panel.locate)
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await pilot.press(*"1", "tab", *"2", "tab", *"5", "enter")
        await until(pilot, lambda: stored(102).location == (1.0, 2.0, 5.0, 0.0, 0.0, 0.0))
        assert stored(101).location is None  # the chosen one only
        await until(pilot, lambda: panel.no_place.display)
        await until(pilot, lambda: column(page.rig, "place")[:2] == ["·", "●"])

        app.action_layout("C")
        await pilot.press("f1")
        plot = app.query_one(StagePlot)
        await until(pilot, lambda: [row.y for row in plot.rows] == [2.0])
        await pilot.press("f3")
        await tap(pilot, panel.locate)
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await pilot.press("tab", "ctrl+u", *"-3", "enter")
        await until(pilot, lambda: stored(102).location == (1.0, -3.0, 5.0, 0.0, 0.0, 0.0))
        await pilot.press("f1")
        await until(pilot, lambda: [row.y for row in plot.rows] == [-3.0])  # the plot follows
        await pilot.press("f3")
        await tap(pilot, panel.no_place)
        await until(pilot, lambda: stored(102).location is None)
        await pilot.press("f1")
        await until(pilot, lambda: plot.rows == [])

        await pilot.press("f3")
        await click_cell(pilot, page.rig, 2, "name")  # 201
        await until(pilot, lambda: panel.selected == {201})
        await pilot.click(page.rig, offset=(10, 5), shift=True)  # 203, with 202 between
        await until(pilot, lambda: panel.selected == {201, 203})
        await tap(pilot, panel.limits["intensity"].buttons[0])
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await pilot.press(*"70", "enter")
        await until(pilot, lambda: stored(203).limits.intensity == 0.7)
        assert stored(201).limits.intensity == 0.7
        assert stored(202).limits.intensity is None  # thru would have covered it

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f3_and_f8_patch_a_fixture_and_add_one_at_a_place_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """F3's PATCH moves 102 and unpatches it; F8's map places it again, and adds a
    library profile at a place, which embeds it; ``[change]`` takes it elsewhere."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=3), standalone=True)

    def stored(number: int) -> FixtureInfo | None:
        show = app.view.show
        return None if show is None else show.fixture(number)

    def patch_of(number: int) -> tuple[int, int] | None:
        found = stored(number)
        assert found is not None
        return found.patch

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.view.show is not None)
        page = app.query_one(FixturesPage)
        panel = page.panel
        chooser = panel.patching
        await tap(pilot, page.edit)
        await until(pilot, lambda: page.editing and len(page.rig.rows) == 7)
        await click_cell(pilot, page.rig, 1, "name")
        await until(pilot, lambda: panel.selected == {102})
        assert str(panel.patch_words.content) == "PATCH 1.17–1.32"

        await tap(pilot, chooser.next_free)
        assert chooser.at == (1, 85)  # as the plan's picture has it
        assert str(chooser.takes.content) == "takes 1.85–1.100 · free"
        await tap(pilot, panel.send_patch)
        await until(pilot, lambda: patch_of(102) == (1, 85))
        await until(pilot, lambda: panel.send_patch.inert)

        await tap_button(pilot, chooser.chips, "none")
        await tap(pilot, panel.send_patch)
        await until(pilot, lambda: patch_of(102) is None)
        await until(pilot, lambda: str(panel.patch_words.content) == "PATCH none")

        await pilot.press("f8")
        await until(pilot, lambda: app.page == 8)
        patch_page = app.query_one(PatchPage)
        dmx_map = app.query_one(DmxMap)
        await pilot.click(dmx_map, offset=(5 + 99 - 64, 1))  # 1.100
        await until(pilot, lambda: patch_page.place == (1, 100))
        await tap_button(pilot, patch_page.place_strip, "patch 102 here")
        await until(pilot, lambda: patch_of(102) == (1, 100))
        await until(pilot, lambda: patch_page.place is None)
        await until(pilot, lambda: any(p.fixture == 102 for p in dmx_map.prints))

        await pilot.click(dmx_map, offset=(5 + 56, 7))  # 1.505
        await until(pilot, lambda: patch_page.place == (1, 505))
        await tap_button(pilot, patch_page.place_strip, "add fixture here…")
        await until(pilot, lambda: app.page == 3 and panel.adding)
        form = panel.form
        assert form.patching.at == (1, 505)
        await tap(pilot, form.choose)
        await until(pilot, lambda: isinstance(app.screen, ProfileDialog))
        assert isinstance(app.screen, ProfileDialog)
        assert [c.source for c in app.screen.shown if c.name == "RGB Par 3ch"] == ["library"]
        await pilot.press(*"rgb par", "enter")
        await until(pilot, lambda: form.profile == "RGB Par 3ch")
        assert str(form.patching.takes.content) == "takes 1.505–1.507 · free"
        await tap(pilot, form.send)
        await until(pilot, lambda: stored(302) is not None)
        assert patch_of(302) == (1, 505)
        show = app.view.show
        assert show is not None
        assert show.profile("RGB Par 3ch") is not None  # embedded by the add
        assert [c.source for c in show.choices if c.name == "RGB Par 3ch"] == ["show"]
        await until(pilot, lambda: form.number == 303)
        await tap(pilot, form.done)
        assert not panel.adding

        await tap(pilot, panel.ask_swap)
        await until(pilot, lambda: isinstance(app.screen, ProfileDialog))
        await pilot.press(*"rgb par", "enter")
        await until(pilot, lambda: panel.swapping.display)
        await tap(pilot, panel.swap_send)

        def changed() -> bool:
            found = stored(102)
            return found is not None and found.profile == "RGB Par 3ch" and found.footprint == 3

        await until(pilot, changed)
        await until(pilot, lambda: not panel.swapping.display)
        await until(pilot, lambda: str(panel.patch_words.content) == "PATCH 1.100–1.102")
        await pilot.press(*"undo", "enter")  # takes the profile back
        await until(pilot, lambda: not changed())

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_a_new_show_gets_its_rig_from_controls_on_the_real_engine(tmp_path: Path) -> None:
    """A universe, four pars with ``thru`` at an address, a rename, limits on
    two, one deleted, then ``undo``."""
    path = tmp_path / "new.show"
    busk.save_show(busk.new_show("New"), path, backups=False)
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=8), standalone=True)

    def rig() -> list[FixtureInfo]:
        show = app.view.show
        return [] if show is None else sorted(show.fixtures, key=lambda f: f.number)

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.view.show is not None)
        await tap_button(pilot, app.query_one(PatchPage).universe_edits, "+ universe…")
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await pilot.press("tab", *"Stage", "enter")
        await until(pilot, lambda: app.view.show is not None and len(app.view.show.universes) == 1)

        await pilot.press("f3")
        await until(pilot, lambda: app.page == 3)
        page = app.query_one(FixturesPage)
        panel = page.panel
        form = panel.form
        await tap(pilot, page.add_button)
        await until(pilot, lambda: panel.adding)
        assert form.number == 1
        assert form.patching.at == (1, 1)
        await tap(pilot, form.choose)
        await until(pilot, lambda: isinstance(app.screen, ProfileDialog))
        await pilot.press(*"rgb par", "enter")
        await until(pilot, lambda: form.profile == "RGB Par 3ch")
        for _ in range(3):
            await tap(pilot, form.more)
        assert form.count == 4
        assert str(form.range.content) == "1 thru 4"
        await tap(pilot, form.patching.ask)
        await until(pilot, lambda: isinstance(app.screen, TextDialog))
        await pilot.press(*"10", "enter")
        await until(pilot, lambda: form.patching.at == (1, 10))
        assert str(form.patching.takes.content) == "takes 1.10–1.21 · free"
        await tap(pilot, form.send)
        await until(pilot, lambda: len(rig()) == 4)
        assert [f.patch for f in rig()] == [(1, 10), (1, 13), (1, 16), (1, 19)]
        await until(pilot, lambda: form.number == 5)
        await until(pilot, lambda: form.patching.at == (1, 22))  # twelve more do not fit 1–9
        await tap(pilot, form.done)

        await click_cell(pilot, page.rig, 0, "name")
        await until(pilot, lambda: panel.chosen == 1 and panel.selected == {1})
        await tap(pilot, panel.rename)
        await until(pilot, lambda: isinstance(app.screen, TextDialog))
        await pilot.press(*"Left", "enter")
        await until(pilot, lambda: rig()[0].name == "Left")

        await pilot.click(page.rig, offset=(10, 2), shift=True)
        await until(pilot, lambda: panel.selected == {1, 2})
        await tap(pilot, panel.limits["intensity"].buttons[0])
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await pilot.press(*"50", "enter")
        await until(pilot, lambda: rig()[1].limits.intensity == 0.5)
        assert [f.limits.intensity for f in rig()] == [0.5, 0.5, None, None]

        await click_cell(pilot, page.rig, 2, "name")
        await until(pilot, lambda: panel.chosen == 3)
        await tap(pilot, panel.delete)
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.press("y")
        await until(pilot, lambda: [f.number for f in rig()] == [1, 2, 4])
        await pilot.press(*"undo", "enter")
        await until(pilot, lambda: [f.number for f in rig()] == [1, 2, 3, 4])

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f8_sends_a_new_universe_through_a_new_route_from_controls(
    tmp_path: Path, receiver: Receiver
) -> None:
    """On a running show: a universe, a route that opens, a spot patched in it
    and seen in the frame and on the wire. Off greys the light, on brings it
    back, and delete takes the row away; ``undo``, then the universe, deleted
    with both."""
    path = tmp_path / "new.show"
    busk.save_show(busk.new_show("New"), path, backups=False)
    bridge = Bridge.standalone(path, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=8), standalone=True)

    def universes() -> list[int]:
        show = app.view.show
        return [] if show is None else [universe.number for universe in show.universes]

    def frames() -> dict[int, bytes]:
        frame = bridge._show.frame  # type: ignore[union-attr]
        return {} if frame is None else frame.universes

    def lit(universe: int) -> list[int]:
        """The slots of ``universe`` that are up in the engine's newest frame."""
        return [slot for slot, value in enumerate(frames().get(universe, b""), 1) if value]

    def wire() -> list[int] | None:
        """The slots that are up in the newest packet, if one came. The app
        shares this thread, so it does not wait."""
        packets = receiver.drain(quiet=0.001)
        if not packets:
            return None
        assert {packet.universe for packet in packets} == {1}
        return [slot for slot, value in enumerate(packets[-1].data, 1) if value]

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.view.show is not None)
        page = app.query_one(PatchPage)
        table = app.query_one(RoutesTable)
        strip = page.route_edits
        await tap_button(pilot, page.universe_edits, "+ universe…")
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await pilot.press("tab", *"Stage", "enter")
        await until(pilot, lambda: universes() == [1])

        await until(pilot, lambda: "[+ route…]" in [b.label.plain for b in strip.buttons])
        await tap_button(pilot, strip, "+ route…")
        await until(pilot, lambda: isinstance(app.screen, RouteDialog))
        assert isinstance(app.screen, RouteDialog)
        app.screen.where.value = "127.0.0.1"
        await pilot.press("tab", "tab", "right", "enter")
        await until(pilot, lambda: column(table, "state") == ["open"])
        (route,) = app.view.routes
        assert route.id.startswith("r-")
        assert (route.protocol, route.address) == ("sACN", "1")
        assert route.destination == "unicast 127.0.0.1"
        assert table.rows[0]["tx"].style == colors.GREEN
        await until(pilot, lambda: wire() == [])  # it sends the universe, dark

        await pilot.press("f3")
        await until(pilot, lambda: app.page == 3)
        fixtures = app.query_one(FixturesPage)
        form = fixtures.panel.form
        await tap(pilot, fixtures.add_button)
        await until(pilot, lambda: fixtures.panel.adding)
        await tap(pilot, form.choose)
        await until(pilot, lambda: isinstance(app.screen, ProfileDialog))
        await pilot.press(*"generic spot", "enter")
        await until(pilot, lambda: form.profile == "Generic Spot 16ch")
        await tap(pilot, form.patching.ask)
        await until(pilot, lambda: isinstance(app.screen, TextDialog))
        await pilot.press(*"101", "enter")
        await until(pilot, lambda: form.patching.at == (1, 101))
        await tap(pilot, form.send)
        await until(pilot, lambda: app.view.show is not None and len(app.view.show.fixtures) == 1)
        await tap(pilot, form.done)
        await tap(pilot, fixtures.panel.done)

        await pilot.press("f8")
        await until(pilot, lambda: app.page == 8)
        dmx_map = app.query_one(DmxMap)
        await until(pilot, lambda: bool(dmx_map.prints))
        await pilot.click(dmx_map, offset=(5 + 100 % 64, 100 // 64))  # 1.101, the spot
        await until(pilot, lambda: app.programmer is not None and bool(app.programmer.selection))
        await pilot.press("f2")
        await until(pilot, lambda: app.page == 2 and bool(app.query(EncoderRow)))
        row = next(r for r in app.query(EncoderRow) if r.encoder.attribute == "intensity")
        await pilot.click(row.bar, offset=(row.bar.size.width // 2, 0))
        await until(pilot, lambda: bool(lit(1)))
        assert all(101 <= slot <= 116 for slot in lit(1))
        await until(pilot, lambda: wire() == lit(1))

        await pilot.press("f8")
        await until(pilot, lambda: app.page == 8)
        await click_cell(pilot, table, 0, "protocol")
        await until(pilot, lambda: page.route_id == route.id)
        await tap_button(pilot, strip, "off")
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.press("y")
        await until(pilot, lambda: column(table, "state") == ["disabled"])
        assert table.rows[0]["tx"].style == colors.BORDER

        await tap_button(pilot, strip, "on")
        await until(pilot, lambda: column(table, "state") == ["open"])
        assert table.rows[0]["tx"].style == colors.GREEN
        await until(pilot, lambda: wire() == lit(1))

        await tap_button(pilot, strip, "delete")
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.press("y")
        await until(pilot, lambda: table.rows == ())
        assert page.route_id is None
        assert [b.label.plain for b in strip.buttons] == ["[+ route…]"]
        await pilot.press(*"undo", "enter")
        await until(pilot, lambda: column(table, "state") == ["open"])

        await click_cell(pilot, app.query_one(UniverseTable), 0, "name")
        await until(pilot, lambda: page.chosen == 1)
        await tap_button(pilot, page.universe_edits, "delete")
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        assert isinstance(app.screen, ConfirmDialog)
        assert "1 fixture loses its patch and 1 route goes" in app.screen.question
        await pilot.press("y")
        await until(pilot, lambda: universes() == [])
        await until(pilot, lambda: table.rows == ())
        await until(pilot, lambda: 1 not in frames())

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_busk_refuses_a_route_in_the_log_and_the_table_stays(
    club_path: Path, tmp_path: Path
) -> None:
    """The form cannot tell which sACN universes are taken: busk can."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=8), standalone=True)

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: len(app.view.routes) == 1)
        page = app.query_one(PatchPage)
        await tap_button(pilot, page.universe_edits, "+ universe…")
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await pilot.press("enter")
        table = app.query_one(UniverseTable)
        await until(pilot, lambda: len(table.rows) == 2)
        await click_cell(pilot, table, 1, "name")
        await until(pilot, lambda: page.chosen == 2)
        await tap_button(pilot, page.route_edits, "+ route…")
        await until(pilot, lambda: isinstance(app.screen, RouteDialog))
        await pilot.press("tab", "1", "enter")  # the sACN universe universe 1 sends
        log = app.query_one(LogView)
        await until(pilot, lambda: ("ui", "route add 2 sacn 1") in log.entries)
        await until(pilot, lambda: any("is already sent by route" in e[1] for e in log.entries))
        assert any(kind == "error" and "sACN universe 1" in text for kind, text in log.entries)
        assert len(app.view.routes) == 1
        assert len(app.query_one(RoutesTable).rows) == 1

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f8_edits_a_route_through_its_filled_form_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """The club's route, from its own words: unchanged sends nothing; then
    sACN 9, Art-Net to a host, DMX-USB, and sACN again, each one ``route <id>
    change`` line that keeps the id; ``undo`` takes the last back."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=8), standalone=True)

    def now() -> tuple[str, str, str, float | None]:
        (route,) = app.view.routes
        return route.protocol, route.address, route.destination, route.rate

    async def edit(pilot: Pilot[int], page: PatchPage) -> RouteDialog:
        await tap_button(pilot, page.route_edits, "edit…")
        await until(pilot, lambda: isinstance(app.screen, RouteDialog))
        assert isinstance(app.screen, RouteDialog)
        return app.screen

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: len(app.view.routes) == 1)
        page = app.query_one(PatchPage)
        log = app.query_one(LogView)
        (route,) = app.view.routes
        await click_cell(pilot, app.query_one(RoutesTable), 0, "protocol")
        await until(pilot, lambda: page.route_id == route.id)
        dialog = await edit(pilot, page)
        assert dialog.title_text.plain == f"EDIT ROUTE {route.id} · U1 Stage"
        assert (dialog.protocol.chosen, dialog.sacn.value) == ("sacn", "1")
        assert (dialog.way.chosen, dialog.where.value) == ("open", "eth0")
        await pilot.press("enter")
        await until(pilot, lambda: not isinstance(app.screen, RouteDialog))
        assert not any("change" in text for kind, text in log.entries if kind == "ui")

        await edit(pilot, page)
        await pilot.press("tab", *"9", "enter")
        await until(pilot, lambda: now() == ("sACN", "9", "multicast eth0", None))
        assert ("ui", f"route {route.id} change 1 sacn 9 multicast eth0") in log.entries

        await edit(pilot, page)
        await pilot.press("right", "tab", "tab", "right", "tab", *"10.0.0.50", "enter")
        await until(pilot, lambda: now() == ("ArtNet", "0.0.0", "unicast 10.0.0.50", None))

        dialog = await edit(pilot, page)
        assert (dialog.protocol.chosen, dialog.artnet.value) == ("artnet", "0.0.0")
        assert (dialog.way.chosen, dialog.where.value) == ("unicast", "10.0.0.50")
        await pilot.press("right", "tab", "tab", *"/dev/ttyUSB9", "tab", *"25", "enter")
        await until(pilot, lambda: now() == ("DMX-USB", "enttecPro", "/dev/ttyUSB9", 25.0))

        dialog = await edit(pilot, page)
        assert (dialog.driver.chosen, dialog.port.value, dialog.rate.value) == (
            "enttecPro", "/dev/ttyUSB9", "25"
        )  # fmt: skip
        await pilot.press("left", "left", "enter")
        await until(pilot, lambda: now() == ("sACN", "1", "multicast eth0", None))
        assert [r.id for r in app.view.routes] == [route.id]

        await pilot.press(*"undo", "enter")
        await until(pilot, lambda: now() == ("DMX-USB", "enttecPro", "/dev/ttyUSB9", 25.0))
        assert not [text for kind, text in log.entries if kind == "error"]

    try:
        drive(app, body)
    finally:
        bridge.stop()


OFL_DIMMER = {
    "name": "Test",
    "meta": {"lastModifyDate": "2026-01-02"},
    "availableChannels": {"Dimmer": {"capability": {"type": "Intensity"}}},
    "modes": [{"name": "All", "channels": ["Dimmer"]}],
}


def test_f3_patches_and_deletes_a_run_and_imports_and_updates_profiles_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """The spots' copy of their profile at revision 7: ``[update profile]``
    brings the library's. The pars, 201 thru 204, patched in one line and
    deleted in one; a hole between them greys both. The picker imports a
    profile, after a missing path and a file busk refuses."""
    document, _ = busk.load_show(club_path)
    document = copy.deepcopy(document)
    document["profiles"][0]["revision"] = "7"
    path = tmp_path / "club.show"
    busk.save_show(document, path, backups=False)
    (tmp_path / "acme").mkdir()
    good = tmp_path / "acme" / "dim.json"
    good.write_text(json.dumps(OFL_DIMMER))
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=3), standalone=True)
    pars = [201, 202, 203, 204]

    def patches() -> list[tuple[int, int] | None]:
        show = app.view.show
        assert show is not None
        return [f.patch for f in show.fixtures if f.number in pars]

    def outdated() -> bool:
        show = app.view.show
        assert show is not None
        return next(c for c in show.choices if c.name == "Generic Spot 16ch").outdated()

    async def typed(pilot: Pilot[int], line: str) -> None:
        await pilot.press(*line, "enter")

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.view.show is not None)
        page = app.query_one(FixturesPage)
        panel = page.panel
        log = app.query_one(LogView)
        await tap(pilot, page.edit)
        await until(pilot, lambda: page.editing and len(page.rig.rows) == 7)

        await click_cell(pilot, page.rig, 0, "name")  # 101, a spot
        await until(pilot, lambda: panel.chosen == 101 and not panel.update_profile.inert)
        await tap(pilot, panel.update_profile)
        await until(pilot, lambda: not outdated() and panel.update_profile.inert)
        assert ("ui", 'profile update "Generic Spot 16ch"') in log.entries

        await click_cell(pilot, page.rig, 2, "name")  # 201
        for y in (4, 5, 6):  # 202 thru 204
            await pilot.click(page.rig, offset=(10, y), shift=True)
        await until(pilot, lambda: panel.selected == set(pars))
        assert panel.delete.label == "delete 201 thru 204"
        assert str(panel.patch_words.content) == "PATCH · 201 thru 204 (4) · 1.33–1.48"
        await tap(pilot, panel.patching.next_free)
        assert panel.patching.at == (1, 85)
        await tap(pilot, panel.send_patch)
        await until(pilot, lambda: patches() == [(1, 85), (1, 89), (1, 93), (1, 97)])
        assert ("ui", "fixture 201 thru 204 patch 1.85") in log.entries

        await typed(pilot, "sel fixture 201, fixture 203 thru 204")
        await until(pilot, lambda: panel.selected == {201, 203, 204})
        assert (panel.delete.label, panel.delete.inert) == ("delete", True)
        assert str(panel.patch_note.content) == "not one run: thru would take 202 too"
        assert panel.send_patch.inert

        await typed(pilot, "sel fixture 201 thru 204")
        await until(pilot, lambda: not panel.delete.inert)
        await tap(pilot, panel.delete)
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        assert isinstance(app.screen, ConfirmDialog)
        assert app.screen.question.startswith("Delete 4 fixtures from 201 to 204?")
        await pilot.press("y")
        await until(pilot, lambda: len(page.rig.rows) == 3)
        assert panel.chosen is None
        await typed(pilot, "undo")
        await until(pilot, lambda: len(page.rig.rows) == 7)
        assert patches() == [(1, 85), (1, 89), (1, 93), (1, 97)]

        await click_cell(pilot, page.rig, 0, "name")
        await until(pilot, lambda: panel.chosen == 101)
        await tap(pilot, panel.ask_swap)
        await until(pilot, lambda: isinstance(app.screen, ProfileDialog))
        picker = app.screen
        assert isinstance(picker, ProfileDialog)
        await pilot.press("ctrl+o")
        await answer_field(pilot, app, str(tmp_path / "none.json"))
        await until(pilot, lambda: "no file at" in str(app.screen.query_one(".error").content))
        await answer_field(pilot, app, str(bad))
        await until(pilot, lambda: picker.error.display)
        assert str(picker.error.content).startswith(f"cannot import {str(bad)!r}")
        await pilot.press("ctrl+o")
        await answer_field(pilot, app, str(good))
        await until(pilot, lambda: picker.list.highlighted is not None and
                    picker.shown[picker.list.highlighted].name == "acme Test")  # fmt: skip
        assert app.screen is picker
        assert not picker.error.display
        await pilot.press("enter")
        await until(pilot, lambda: panel.swap == ("acme Test", None))
        await until(pilot, lambda: str(panel.swap_words.content) == "to acme Test · 1 channel")
        await tap(pilot, panel.swap_keep)
        assert ("ui", f"profile import {json.dumps(str(good))}") in log.entries
        errors = [text for kind, text in log.entries if kind == "error"]
        (error,) = errors
        assert error.startswith("cannot import")

    try:
        drive(app, body)
    finally:
        bridge.stop()


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
        show = app.view.show
        assert show is not None
        name = next(p.name for p in show.presets if (p.pool, p.number) == ("position", 3))
        words = f'preset position 3 "{name}"'

        async def answer(key: str, question: str) -> None:
            await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
            assert isinstance(app.screen, ConfirmDialog)
            assert app.screen.question == question
            await pilot.press(key)
            await until(pilot, lambda: not isinstance(app.screen, ConfirmDialog))

        removes = f"Remove the programmer's attributes from {words}?"
        await tap(pilot, panel.writes["remove"])
        await answer("n", removes)
        assert ("info", "cancelled: record preset position 3 remove") in (
            app.query_one(LogView).entries
        )
        assert [e[2] for e in stored("position", 3)] == ["pan", "pan", "tilt", "tilt"]
        await tap(pilot, panel.writes["remove"])
        await answer("y", removes)
        await until(pilot, lambda: [e[2] for e in stored("position", 3)] == ["pan", "pan"])
        await tap(pilot, panel.writes["replace"])
        await answer("y", f"Replace what {words} holds with the programmer?")
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


def test_f5_stops_runs_and_removes_an_effect_of_two_words_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """An id of two words, which only ``id "my fx"`` makes: F5's state and ✕
    send it in quotes, and busk takes each line."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=5), standalone=True)

    def stopped() -> tuple[str, ...]:
        return () if app.programmer is None else tuple(app.programmer.stopped)

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.live is not None and app.view.show is not None)
        await pilot.press(*"sel group 1", "enter")
        await until(pilot, lambda: bool(app.programmer and app.programmer.selection))
        await pilot.press(*'effect add "Circle" id "my fx"', "enter")
        table = app.query_one(EffectTable)
        await until(pilot, lambda: column(table, "owner")[-1:] == ["prog"])
        row = len(table.rows) - 1
        await click_cell(pilot, table, row, "state")
        await until(pilot, lambda: stopped() == ("my fx",), timeout=1.0)
        await until(pilot, lambda: column(table, "state")[row] == "[off]", timeout=1.0)
        await click_cell(pilot, table, row, "state")
        await until(pilot, lambda: stopped() == (), timeout=1.0)
        await click_cell(pilot, table, row, "remove")
        await until(pilot, lambda: not app.programmer or not app.programmer.effects, timeout=1.0)
        log = app.query_one(LogView).entries
        for line in ('effect stop "my fx"', 'effect run "my fx"', 'effect remove "my fx"'):
            assert ("ui", line) in log
        assert not [text for kind, text in log if kind == "error"]

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f4_and_f6_build_and_delete_cues_and_lists_from_controls_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """F4 from controls alone: a new list, a cue at a number, merged into and
    released, tracking, a chase from its form, a rename, the cue and the list
    deleted after their questions. F6's ``[delete]`` of a preset in use leaves
    the cues that took it."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=4), standalone=True)

    def cue_list() -> CueListInfo | None:
        return None if app.view.show is None else app.view.show.cue_list(30)

    async def form(pilot: Pilot[int], *values: str) -> None:
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        for field, value in zip(dialog.inputs, values, strict=True):
            field.value = value
        await pilot.press("enter")

    def blue_gone() -> bool:
        assert app.view.show is not None
        return all((p.pool, p.number) != ("color", 1) for p in app.view.show.presets)

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.live is not None and app.view.show is not None)
        page = app.query_one(CuesPage)
        await until(pilot, lambda: page.list is not None)
        await tap_button(pilot, page.list_add, "+ list…")
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await form(pilot, "30", "Encore")
        await until(pilot, lambda: cue_list() is not None and page.list == 30)
        assert page.edits.buttons[0].note  # nothing to record yet: [record at…] is grey

        await pilot.press(*"sel group 1", "enter")
        await pilot.press(*"set intensity 50%", "enter")
        await until(pilot, page.recordable)
        await tap_button(pilot, page.edits, "record at…")
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await form(pilot, "2.5", "Bridge")
        cues = app.query_one(CueTable)
        await until(pilot, lambda: column(cues, "cue") == ["30/2.5"])
        await until(pilot, lambda: page.cue == "2.5")
        assert plain_of(page.edit_label) == "edit cue 30/2.5 Bridge"

        await tap_button(pilot, page.edits, "merge")
        await tap_button(pilot, page.edits, "release…")
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await form(pilot, "group 2", "intensity")
        await tap_button(pilot, page.list_edits, "tracking on")
        await until(pilot, lambda: cue_list() is not None and cue_list().tracking)  # type: ignore[union-attr]
        log = app.query_one(LogView).entries
        await until(pilot, lambda: ("ui", "cue 30/2.5 release group 2 only intensity") in log)
        assert ("ui", "record cue 30/2.5 merge") in log

        await tap_button(pilot, page.list_edits, "chase…")
        await until(pilot, lambda: isinstance(app.screen, ChaseDialog))
        dialog = app.screen
        assert isinstance(dialog, ChaseDialog)
        dialog.kind.pick("hz")
        dialog.hz.value = "4"
        dialog.direction.pick("bounce")
        dialog.crossfade.value = "0.25"
        await pilot.press("enter")
        await until(pilot, lambda: cue_list() is not None and cue_list().mode == "chase")  # type: ignore[union-attr]
        assert cue_list().chase == "hz 4 bounce"  # type: ignore[union-attr]
        assert cue_list().crossfade == 0.25  # type: ignore[union-attr]

        await tap_button(pilot, page.list_edits, "rename…")
        await until(pilot, lambda: isinstance(app.screen, TextDialog))
        renamed = app.screen
        assert isinstance(renamed, TextDialog)
        renamed.query_one(Input).value = "Last"
        await pilot.press("enter")
        await until(pilot, lambda: cue_list() is not None and cue_list().name == "Last")  # type: ignore[union-attr]

        await tap_button(pilot, page.edits, "delete")
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        question = app.screen
        assert isinstance(question, ConfirmDialog)
        assert question.question == 'Delete cue 30/2.5 "Bridge"?'
        await pilot.press("y")
        await until(pilot, lambda: cue_list() is not None and cue_list().cues == ())  # type: ignore[union-attr]

        await tap_button(pilot, page.list_edits, "delete")
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        question = app.screen
        assert isinstance(question, ConfirmDialog)
        assert question.question == 'Delete cue list 30 "Last"?'
        await pilot.press("y")
        await until(pilot, lambda: cue_list() is None and page.list is not None)
        assert app.view.show is not None
        assert app.view.show.cue_list(page.list) is not None

        await pilot.press("f6")
        await pilot.pause()
        presets = app.query_one(PresetsPage)
        blue = next(t for t in presets.tiles if t.pool == "color" and t.number == 1)
        presets.choose(blue)
        await pilot.pause()
        assert presets.panel.preset() is not None
        users = presets.panel.preset().used_by  # type: ignore[union-attr]
        assert users
        presets.panel.delete.scroll_visible(animate=False)
        await pilot.pause()
        await pilot.click(presets.panel.delete)
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        question = app.screen
        assert isinstance(question, ConfirmDialog)
        assert " It leaves cues " in question.question
        await pilot.press("y")
        await until(pilot, blue_gone)
        assert presets.panel.chosen is None
        await pilot.press(*"undo", "enter")
        await until(pilot, lambda: not blue_gone())
        errors = [text for kind, text in app.query_one(LogView).entries if kind == "error"]
        assert errors == []

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f4_toggles_a_list_back_to_the_chase_busk_stored_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """Song, never chased, goes on the beat. A list chased on a master named
    with a quote, at a multiplier of many digits and a crossfade of 0.125,
    then made a sequence: the toggle makes it that chase again."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=4), standalone=True)
    say = 'Say "hi"'
    chased = ChaseRate(None, say, 1.23456789, "random")

    def chase_of(number: int) -> tuple[str, ChaseRate | None, float] | None:
        found = None if app.view.show is None else app.view.show.cue_list(number)
        return None if found is None else (found.mode, found.rate, found.crossfade)

    def toggle(page: CuesPage) -> str:
        return page.buttons.buttons[-1].line.text

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.live is not None and app.view.show is not None)
        page = app.query_one(CuesPage)
        page.choose_list(9)
        await until(pilot, lambda: toggle(page) == "cuelist 9 chase bpm x 1")
        await tap_button(pilot, page.buttons, "cuelist 9 chase bpm x 1")
        await until(
            pilot, lambda: chase_of(9) == ("chase", ChaseRate(None, None, 1.0, "forward"), 0)
        )

        for line in (
            'master add speed "Say \\"hi\\"" bpm 90',
            'cuelist 10 chase bpm "Say \\"hi\\"" x 1.23456789 random crossfade 0.125',
            "cuelist 10 sequence",
        ):
            await pilot.press(*line, "enter")
        await until(pilot, lambda: chase_of(10) == ("sequence", chased, 0.125), timeout=1.0)
        page.choose_list(10)
        line = 'cuelist 10 chase bpm "Say \\"hi\\"" x 1.23456789 random crossfade 0.125'
        await until(pilot, lambda: toggle(page) == line)
        await tap_button(pilot, page.buttons, line)
        await until(pilot, lambda: chase_of(10) == ("chase", chased, 0.125), timeout=1.0)
        log = app.query_one(LogView).entries
        assert [text for kind, text in log if kind == "error"] == []
        await until(pilot, lambda: toggle(page) == "cuelist 10 sequence")

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f4_edits_a_cues_timing_trigger_and_name_in_dialogs_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """F4's cells and edits open dialogs filled in with the cue: the fade
    times, a family's own (its curve kept), the delays (the fades kept), a
    Bézier, a wait in place of a follow and the name reach the show; Esc and
    an unchanged form send nothing, and ``undo`` takes the last back."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=4), standalone=True)

    def cue(number: str) -> CueInfo:
        song = None if app.view.show is None else app.view.show.cue_list(9)
        assert song is not None
        return next(found for found in song.cues if found.number == number)

    async def dialog_of[D](pilot: Pilot[int], kind: type[D]) -> D:
        await until(pilot, lambda: isinstance(app.screen, kind))
        dialog = app.screen
        assert isinstance(dialog, kind)
        return dialog

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.live is not None and app.view.show is not None)
        app._select_playback(9)
        page = app.query_one(CuesPage)
        cues = app.query_one(CueTable)
        await until(pilot, lambda: column(cues, "cue")[:1] == ["9/1"])
        log = app.query_one(LogView).entries
        assert (cue("3").fadeIn, cue("3").fadeOut, cue("3").delayIn) == (1, 3, 0)

        await click_cell(pilot, cues, 2, "time")
        dialog = await dialog_of(pilot, TimeDialog)
        assert (dialog.fade_in.value, dialog.fade_out.value) == ("1", "3")
        await pilot.press("escape")
        await click_cell(pilot, cues, 2, "time")
        await dialog_of(pilot, TimeDialog)
        await pilot.press("enter")  # unchanged
        await until(pilot, lambda: not isinstance(app.screen, TimeDialog))
        await click_cell(pilot, cues, 2, "time")
        await dialog_of(pilot, TimeDialog)
        await pilot.press("2", "tab", "2", "enter")  # a field's text is selected: typed over
        await until(pilot, lambda: (cue("3").fadeIn, cue("3").fadeOut) == (2, 2))
        assert [line for kind, line in log if kind == "ui"] == ["cue 9/3 time 2"]  # no goto

        await pilot.press(*"cue 9/2 time position 4 delay 1 snapEnd", "enter")
        own = FamilyTiming("position", 4.0, 1.0, "snapEnd")
        await until(pilot, lambda: cue("2").families == (own,))
        await click_cell(pilot, cues, 1, "time")
        dialog = await dialog_of(pilot, TimeDialog)
        dialog.target.pick("position")
        await pilot.pause()
        dialog.fade.value = "6"
        await pilot.press("enter")
        changed = FamilyTiming("position", 6.0, 1.0, "snapEnd")
        await until(pilot, lambda: cue("2").families == (changed,))

        await click_cell(pilot, cues, 2, "delay")
        form = await dialog_of(pilot, FormDialog)
        form.inputs[0].value = "0.5"
        await pilot.press("enter")
        await until(pilot, lambda: (cue("3").delayIn, cue("3").delayOut) == (0.5, 0))
        assert (cue("3").fadeIn, cue("3").fadeOut) == (2, 2)

        await click_cell(pilot, cues, 2, "curve")
        curve = await dialog_of(pilot, CurveDialog)
        curve.curve.pick("bezier")
        await pilot.pause()
        curve.points.value = "0.42 0 0.58 1"
        await pilot.press("enter")
        await until(pilot, lambda: cue("3").curve == "bezier 0.42 0 0.58 1")
        assert (cue("3").fadeIn, cue("3").delayIn) == (2, 0.5)

        assert (cue("5").trigger, cue("5").delay) == ("follow", 4)
        page.choose_cue("5", go=False)
        await pilot.pause()
        await tap_button(pilot, page.edits, "wait…")
        text = await dialog_of(pilot, TextDialog)
        assert str(text.query(".note").first().render()).endswith("\nnow: follow 4")
        text.query_one(Input).value = "3"
        await pilot.press("enter")
        await until(pilot, lambda: (cue("5").trigger, cue("5").delay) == ("wait", 3))

        await tap_button(pilot, page.edits, "rename…")
        text = await dialog_of(pilot, TextDialog)
        assert text.query_one(Input).value == "Outro"
        text.query_one(Input).value = "Coda"
        await pilot.press("enter")
        await until(pilot, lambda: cue("5").name == "Coda")
        await pilot.press(*"undo", "enter")
        await until(pilot, lambda: cue("5").name == "Outro")
        assert (cue("5").trigger, cue("5").delay) == ("wait", 3)
        errors = [text for kind, text in log if kind == "error"]
        assert errors == []

    try:
        drive(app, body, size=(160, 48))  # every column: at 150 ``also`` takes the curve's room
    finally:
        bridge.stop()


def test_f4_names_the_other_families_a_cue_holds_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """F4's ``also`` at 150 columns, where the curve was: the Verse's pan
    and tilt are ``position 2``; a zoom merged into the Intro makes it
    ``beam 1``, and ``undo`` takes it away."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=4), standalone=True)

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.live is not None and app.view.show is not None)
        app._select_playback(9)
        cues = app.query_one(CueTable)
        await until(pilot, lambda: column(cues, "cue")[:1] == ["9/1"])
        assert column(cues, "also") == ["—", "position 2", "—", "—", "—"]
        lines = [line.plain for line in cues.lines(cues.size.width)]
        assert "also" in lines[0].split()
        assert "curve" not in lines[0].split()
        assert lines[2].split()[:2] == ["9/2", "Verse"]
        assert "position 2" in lines[2]

        for line in ("sel fixture 101", "set zoom 50", "record cue 9/1 merge"):
            await pilot.press(*line, "enter")
        await until(pilot, lambda: column(cues, "also")[0] == "beam 1")
        assert "beam 1" in cues.lines(cues.size.width)[1].plain
        await pilot.press(*"undo", "enter")
        await until(pilot, lambda: column(cues, "also")[0] == "—")
        log = app.query_one(LogView).entries
        assert [text for kind, text in log if kind == "error"] == []

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f4_takes_a_familys_own_timing_away_in_the_time_dialog_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """Cue 9/2 fades position over 4 s of its own: TIME's ``[none]`` on
    ``position`` takes it away, the time cell drops it (``2, position 4``
    becomes ``2``), and ``undo`` brings it back. Esc sends nothing."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=4), standalone=True)

    def verse() -> CueInfo:
        song = None if app.view.show is None else app.view.show.cue_list(9)
        assert song is not None
        return next(found for found in song.cues if found.number == "2")

    async def time_dialog(pilot: Pilot[int], cues: CueTable) -> TimeDialog:
        await click_cell(pilot, cues, 1, "time")
        await until(pilot, lambda: isinstance(app.screen, TimeDialog))
        dialog = app.screen
        assert isinstance(dialog, TimeDialog)
        dialog.target.pick("position")
        await pilot.pause()
        assert dialog.none_row.display
        return dialog

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.live is not None and app.view.show is not None)
        app._select_playback(9)
        cues = app.query_one(CueTable)
        await until(pilot, lambda: column(cues, "time")[:2] == ["3", "2, position 4"])
        log = app.query_one(LogView).entries
        assert verse().families == (FamilyTiming("position", 4.0, 0.0, None),)

        await time_dialog(pilot, cues)
        await pilot.press("escape")
        await until(pilot, lambda: not isinstance(app.screen, TimeDialog))
        dialog = await time_dialog(pilot, cues)
        await pilot.click(dialog.none)
        await until(pilot, lambda: column(cues, "time")[1] == "2")
        assert verse().families == ()
        assert [line for kind, line in log if kind == "ui"] == ["cue 9/2 time position none"]
        assert "cue 9/2 fades position with the cue again" in [text for _, text in log]

        await pilot.press(*"undo", "enter")
        await until(pilot, lambda: column(cues, "time")[1] == "2, position 4")
        errors = [text for kind, text in log if kind == "error"]
        assert errors == []

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f4_moves_copies_and_renumbers_from_controls_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """Cue 9/4, the goto cue of P9: ``[number…]`` refuses 3 and moves it to 7,
    past cue 5, and it stays chosen; ``[copy…]`` copies it to list 10 and
    into its own list; the list's ``[number…]`` makes list 9 list 30, still
    shown. P9's ``[GT]`` is grey then, since no cue 4 is left. Esc sends
    nothing, and ``undo`` takes each step back."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=4), standalone=True)

    def numbers(cue_list: int) -> list[str] | None:
        found = None if app.view.show is None else app.view.show.cue_list(cue_list)
        return None if found is None else [cue.number for cue in found.cues]

    def goto() -> CommandButton | None:
        rows = app.query_one(StackLayout).rows
        row = next((row for row in rows if row.number == 9), None)
        button = None if row is None else row.buttons[3]
        return button if isinstance(button, CommandButton) else None

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.live is not None and app.view.show is not None)
        app._select_playback(9)
        page = app.query_one(CuesPage)
        cues = app.query_one(CueTable)
        await until(pilot, lambda: column(cues, "cue")[:1] == ["9/1"])
        page.choose_cue("4", go=False)
        log = app.query_one(LogView).entries

        await tap_button(pilot, page.edits, "number…")
        await until(pilot, lambda: isinstance(app.screen, TextDialog))
        await pilot.press("escape")
        await until(pilot, lambda: not isinstance(app.screen, TextDialog))
        await tap_button(pilot, page.edits, "number…")
        await answer_field(pilot, app, "3")
        await pilot.pause()
        assert isinstance(app.screen, TextDialog)  # cue 3 exists: the dialog stays
        await answer_field(pilot, app, "7")
        await until(pilot, lambda: column(cues, "cue") == ["9/1", "9/2", "9/3", "9/5", "9/7"])
        await until(pilot, lambda: plain_of(page.edit_label) == "edit cue 9/7 Chorus")
        assert cues.chosen == 4

        await tap_button(pilot, page.edits, "copy…")
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await pilot.press("escape")
        await until(pilot, lambda: not isinstance(app.screen, FormDialog))
        await tap_button(pilot, page.edits, "copy…")
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert [field.value for field in dialog.inputs] == ["9", "8"]
        dialog.inputs[0].value, dialog.inputs[1].value = "10", "2.5"
        await pilot.press("enter")
        await until(pilot, lambda: numbers(10) == ["1", "2", "2.5", "3", "4"])
        assert page.cue == "7"
        await tap_button(pilot, page.edits, "copy…")
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await pilot.press("enter")  # as it opens: list 9, cue 8
        await until(pilot, lambda: column(cues, "cue")[-1] == "9/8")
        await until(pilot, lambda: page.cue == "8")

        await tap_button(pilot, page.list_edits, "number…")
        await answer_field(pilot, app, "10")
        await pilot.pause()
        assert isinstance(app.screen, TextDialog)  # list 10 exists
        await answer_field(pilot, app, "30")
        await until(pilot, lambda: numbers(30) is not None and page.list == 30)
        await until(pilot, lambda: column(cues, "cue")[:1] == ["30/1"])
        assert (page.cue, plain_of(page.edit_label)) == ("8", "edit cue 30/8 Chorus")
        assert [line for kind, line in log if kind == "ui"] == [
            "cue 9/4 number 7",
            "cue 9/7 copy 10/2.5",
            "cue 9/7 copy 8",
            "cuelist 9 number 30",
        ]
        assert [text for kind, text in log if kind == "result"] == [
            "cue 9/4 is now cue 9/7",
            "warning playbacks[8].gotoCue: Cue list 'Song' has no cue '4'",  # busk's check
            'copied cue 9/7 "Chorus" to cue 10/2.5',
            'copied cue 9/7 "Chorus" to cue 9/8',
            "cue list 9 is now cue list 30",
        ]

        await pilot.press("f1")
        await until(pilot, lambda: goto() is not None and goto().inert)  # type: ignore[union-attr]
        assert goto().hint == "goto: cue list 30 has no cue 4"  # type: ignore[union-attr]
        for _ in range(4):
            await pilot.press(*"undo", "enter")
        await until(pilot, lambda: numbers(9) == ["1", "2", "3", "4", "5"])
        await until(pilot, lambda: goto() is not None and not goto().inert)  # type: ignore[union-attr]
        assert numbers(10) == ["1", "2", "3", "4"]
        assert [text for kind, text in log if kind == "error"] == []

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f4_loads_a_cue_edits_it_and_records_it_back_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """With a value of 201 in the programmer, ``[load]`` on cue 9/2 asks
    first: no sends nothing, yes loads the Verse and selects the heads. One
    value changed at the prompt, ``[replace]`` records it back: the cue holds
    the change and the rest as it was. ``undo`` takes the record back."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=4), standalone=True)

    def verse() -> CueInfo:
        song = None if app.view.show is None else app.view.show.cue_list(9)
        assert song is not None
        return next(found for found in song.cues if found.number == "2")

    def holds() -> set[tuple[int, str, Any]]:
        values = () if app.programmer is None else app.programmer.values
        return {(value.number, value.attribute, value.value) for value in values}

    async def confirm(pilot: Pilot[int], label: str, answer: str) -> None:
        await tap_button(pilot, app.query_one(CuesPage).edits, label)
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.press(answer)
        await until(pilot, lambda: not isinstance(app.screen, ConfirmDialog))

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.live is not None and app.view.show is not None)
        for line in ("sel fixture 201", "set intensity 50%"):
            await pilot.press(*line, "enter")
        await until(pilot, lambda: (201, "intensity", 0.5) in holds())
        app._select_playback(9)
        page = app.query_one(CuesPage)
        await until(pilot, lambda: column(app.query_one(CueTable), "cue")[:1] == ["9/1"])
        page.choose_cue("2", go=False)
        await until(pilot, lambda: plain_of(page.edit_label) == "edit cue 9/2 Verse")
        stored = verse().values
        log = app.query_one(LogView).entries

        await tap_button(pilot, page.edits, "load")
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        assert dialog.question == (
            'Load cue 9/2 "Verse" into the programmer?\nIt replaces what the programmer holds.'
        )
        await pilot.press("n")
        await until(pilot, lambda: ("info", "cancelled: load cue 9/2") in log)
        await confirm(pilot, "load", "y")
        await until(pilot, lambda: app.programmer.selection == ((101, 1), (102, 1)))  # type: ignore[union-attr]
        assert {(n, a) for n, a, _ in holds()} >= {(101, "intensity"), (102, "intensity")}
        assert {n for n, _, _ in holds()} == {101, 102}  # 201's value is gone
        assert (101, "intensity", 0.7) in holds()

        await pilot.press(*"set intensity 30%", "enter")
        await until(pilot, lambda: (102, "intensity", 0.3) in holds())
        await confirm(pilot, "replace", "y")
        changed = tuple(
            replace(value, value=0.3) if value.attribute == "intensity" else value
            for value in stored
        )
        await until(pilot, lambda: verse().values == changed)
        assert changed != stored
        assert [line for kind, line in log if kind == "ui"] == [
            "load cue 9/2",
            "record cue 9/2 replace",
        ]
        loaded = [text for kind, text in log if text.startswith("loaded cue 9/2")]
        assert len(loaded) == 1
        assert loaded[0].startswith('loaded cue 9/2 "Verse": ')
        assert loaded[0].endswith(" on 2 fixtures")

        await pilot.press(*"undo", "enter")
        await until(pilot, lambda: verse().values == stored)
        assert [text for kind, text in log if kind == "error"] == []

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f5_builds_a_template_from_controls(club_path: Path, tmp_path: Path) -> None:
    """F5 makes a template, changes its layers, shows a refusal in the panel
    and the log, renames and deletes it; and F5 names what uses Circle."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=5), standalone=True)

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.live is not None and app.view.show is not None)
        panel = app.query_one(TemplatePanel)
        table = app.query_one(TemplateTable)

        def layers() -> tuple[Any, ...]:
            return () if panel.template is None else panel.template.layers

        await tap(pilot, app.query_one("#templates-add"))
        await until(pilot, lambda: isinstance(app.screen, NewTemplateDialog))
        await answer_field(pilot, app, "Fresh")
        await until(pilot, lambda: panel.display and "Fresh" in str(panel.border_title))
        await tap_button(pilot, panel.attribute, "zoom")
        await until(pilot, lambda: layers()[0]["attribute"] == "zoom")
        await tap_button(pilot, panel.wave, "pulse")
        await until(pilot, lambda: layers()[0]["waveform"]["kind"] == "pulse")
        width = next(b for b in panel.query(ActionButton) if b.label == "width…")
        await tap(pilot, width)
        await answer_field(pilot, app, "0.9")  # width + attack + decay is past one cycle
        await until(pilot, lambda: panel.refusal.display)
        log = app.query_one(LogView).entries
        assert any(kind == "error" and "at most 1" in text for kind, text in log)
        assert "at most 1" in str(panel.refusal.content)
        assert "effects[" not in str(panel.refusal.content)
        assert layers()[0]["waveform"]["width"] == 0.25
        await tap_button(pilot, panel.modes, "add")
        await until(pilot, lambda: not panel.refusal.display)
        rename = next(b for b in panel.query(ActionButton) if b.label == "rename…")
        await tap(pilot, rename)
        await answer_field(pilot, app, "Circle")  # the show has one
        assert isinstance(app.screen, TextDialog)
        await answer_field(pilot, app, "Again")
        await until(pilot, lambda: "Again" in str(panel.border_title))
        delete = next(b for b in panel.query(ActionButton) if b.label == "delete")
        await tap(pilot, delete)
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.press("y")
        await until(pilot, lambda: not panel.display)
        await click_cell(pilot, table, 0, "edit")
        await until(pilot, lambda: panel.display)
        assert "11/1" in str(panel.used.content)
        assert panel.delete.inert

    drive(app, body)


def running_effect(app: BuskApp, playback: int | None, ident: str) -> EffectView | None:
    effects = app.view.effects
    found = () if effects is None else effects.effects
    return next((e for e in found if e.playback == playback and e.id == ident), None)


async def answer_field(pilot: Pilot[int], app: BuskApp, text: str) -> None:
    """Give the open dialog's first field ``text``, and press Enter."""
    await until(pilot, lambda: bool(app.screen.query(Input)))
    app.screen.query_one(Input).value = text
    await pilot.press("enter")


def test_f5_changes_a_running_cue_effect_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """While its cue runs, a cue effect's size and rate change at once, and
    ``undo`` puts them back. ``✕`` asks, the effect leaves, the cue stays, and
    ``undo`` brings it back."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=5), standalone=True)

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.live is not None and app.view.show is not None)
        table, panel = app.query_one(EffectTable), app.query_one(EffectPanel)
        await pilot.press(*"go 11", "enter")
        await until(pilot, lambda: app.live.playback(11).state == "active")  # type: ignore[union-attr]
        await pilot.press(*"fader 11 100%", "enter")

        def fx1() -> EffectView | None:
            return running_effect(app, 11, "fx1")

        await until(pilot, lambda: fx1() is not None and fx1().size == 15)  # type: ignore[union-attr]
        await until(pilot, lambda: fx1().presence == 1.0)  # type: ignore[union-attr]
        hz = fx1().hz  # type: ignore[union-attr]
        row = column(table, "id").index("fx1")
        await click_cell(pilot, table, row, "template")
        await until(pilot, lambda: panel.display)
        size = next(b for b in panel.query(ActionButton) if b.label == "size…")
        await tap(pilot, size)
        await until(pilot, lambda: isinstance(app.screen, TextDialog))
        await answer_field(pilot, app, "30")
        await until(pilot, lambda: fx1() is not None and fx1().size == 30)  # type: ignore[union-attr]
        assert ("ui", "cue 11/1 effect fx1 size 30") in app.query_one(LogView).entries

        await tap(pilot, next(b for b in panel.query(ActionButton) if b.label == "rate…"))
        await until(pilot, lambda: isinstance(app.screen, EffectRateDialog))
        dialog = app.screen
        assert isinstance(dialog, EffectRateDialog)
        assert dialog.kind.chosen == "bpm"
        dialog.multiplier.value = "1"
        dialog.action_ok()
        await until(pilot, lambda: fx1() is not None and fx1().hz == pytest.approx(hz * 2))  # type: ignore[union-attr]
        assert plain_of(panel.rate.value) == "bpm x 1"

        await pilot.press(*"undo", "enter")
        await until(pilot, lambda: fx1() is not None and fx1().hz == pytest.approx(hz))  # type: ignore[union-attr]
        await until(pilot, lambda: plain_of(panel.rate.value) == "bpm x 0.5")
        await pilot.press(*"undo", "enter")
        await until(pilot, lambda: fx1() is not None and fx1().size == 15)  # type: ignore[union-attr]

        await click_cell(pilot, table, row, "remove")
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        assert isinstance(app.screen, ConfirmDialog)
        assert "It is running" in app.screen.question
        await pilot.press("y")
        await until(pilot, lambda: "fx1" not in column(table, "id"))
        await until(pilot, lambda: not panel.display)
        assert app.live.playback(11).state == "active"  # type: ignore[union-attr]
        await pilot.press(*"undo", "enter")
        await until(pilot, lambda: "fx1" in column(table, "id"))
        assert not [line for kind, line in app.query_one(LogView).entries if kind == "error"]

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f5_restates_a_programmer_effect_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """A change leaves the effect on its fixtures, running. With another
    selection nothing can move it; ``[its fixtures]`` comes back to them. The
    number busk stores is the number typed. ``[clear]`` asks."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=5), standalone=True)

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.live is not None and app.view.show is not None)
        table, panel = app.query_one(EffectTable), app.query_one(EffectPanel)
        await pilot.press(*"sel group 1", "enter")
        await until(pilot, lambda: bool(app.programmer and app.programmer.selection))
        await pilot.press(*'effect add "Circle" id fx5 size 15', "enter")
        await until(pilot, lambda: bool(app.programmer and app.programmer.effects))
        targets = app.programmer.effects[0].targets  # type: ignore[union-attr]

        def effect() -> EffectInfo:
            assert app.programmer is not None
            return app.programmer.effects[0]

        await until(pilot, lambda: column(table, "id")[-1:] == ["fx5"])
        row = len(table.rows) - 1
        await click_cell(pilot, table, row, "template")
        await until(pilot, lambda: panel.display)
        size = next(b for b in panel.query(ActionButton) if b.label == "size…")
        await tap(pilot, size)
        await answer_field(pilot, app, "0.00001")
        await until(pilot, lambda: effect().size == 0.00001)  # busk reads no exponent
        await tap_button(pilot, panel.direction, "bounce")
        await until(pilot, lambda: effect().direction == "bounce")
        assert effect().size == 0.00001  # the unchanged setting stayed
        assert effect().targets == targets
        await until(pilot, lambda: running_effect(app, None, "fx5") is not None)

        await pilot.press(*"sel fixture 301", "enter")
        await until(pilot, lambda: panel.why.display)
        assert size.inert
        assert effect().targets == targets
        await tap(pilot, panel.its)
        await until(pilot, lambda: not panel.why.display)
        assert app.programmer.selection == targets.elements  # type: ignore[union-attr]
        assert not size.inert

        clear = app.query_one("#effects-clear", ActionButton)
        await tap(pilot, clear)
        await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.press("y")
        await until(pilot, lambda: not app.programmer or not app.programmer.effects)
        await until(pilot, lambda: not panel.display)
        assert not [line for kind, line in app.query_one(LogView).entries if kind == "error"]

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


def test_f8_shows_what_busk_sends_on_each_channel_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """F8's CHANNELS: the one fixture selected, each channel as busk's ``list
    dmx fixture N`` prints it, live; the hint row the same under the mouse
    (the pending plan's Phase 34)."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=8), standalone=True)

    def rows() -> list[tuple[str, str, str]]:
        table = app.query_one(ChannelTable)
        return list(
            zip(
                column(table, "address"),
                column(table, "function"),
                column(table, "value"),
                strict=True,
            )
        )

    def printed(number: int) -> list[tuple[str, str, str]]:
        show = bridge._show
        assert show is not None
        reply = show.execute(f"list dmx fixture {number}")
        assert reply.ok, reply.text
        found = []
        for line in reply.text.splitlines():
            address, rest = line.split(None, 1)
            function, value = rest.rsplit(None, 1)
            found.append((address, function, value))
        return found

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.view.show is not None and app.view.dmx is not None)
        assert app.query_one(ChannelTable).empty.plain == NO_CHANNELS
        await pilot.press(*"sel fixture 101", "enter", *"set intensity 100%", "enter")
        await until(pilot, lambda: ("1.9", "intensity", "255") in rows())
        assert rows() == printed(101)
        await pilot.press(*"set pan 10", "enter")
        await until(pilot, lambda: rows()[0] != ("1.1", "pan", "128"))
        assert rows() == printed(101)
        dmx_map = app.query(DmxMap).first()
        await pilot.hover(dmx_map, offset=(5 + 8, 0))  # channel 9
        await until(
            pilot,
            lambda: (
                plain_of(app.query_one(HintRow)) == "1.9 · fixture 101 · ch 9/16 intensity · 255"
            ),
        )
        await pilot.press(*"set intensity 20%", "enter")  # the mouse stays where it is
        await until(pilot, lambda: plain_of(app.query_one(HintRow)).endswith("intensity · 51"))
        await pilot.press(*"sel fixture 301", "enter", *"set color 1 0 0", "enter")
        await pilot.press(*"set intensity 100%", "enter")
        await until(pilot, lambda: len(rows()) == 36 and rows()[0][2] != "0")
        assert rows()[:4] == [
            ("1.49", "Cell 1 red", "128"),  # at half: the bar's limit
            ("1.50", "Cell 1 green", "0"),
            ("1.51", "Cell 1 blue", "0"),
            ("1.52", "Cell 2 red", "128"),
        ]
        assert rows() == printed(301)
        await pilot.press(*"sel none", "enter")
        await until(pilot, lambda: rows() == [])

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


def test_f1_presses_a_playbacks_own_buttons_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """Toggle, a held flash and release on P1; P9's goto; a select button
    typed at the prompt, which redraws the strip; ``[record]`` on page 2's
    empty slot, grey until the programmer holds something."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(), standalone=True)

    def row_of(number: int | None) -> PlaybackRow | None:
        rows = app.query_one(StackLayout).rows
        return next((row for row in rows if row.number == number), None)

    def strip(number: int | None) -> PlaybackRow:
        row = row_of(number)
        assert row is not None
        return row

    def view(number: int) -> Any:
        assert app.view.live is not None
        found = app.view.live.playback(number)
        assert found is not None
        return found

    def labels(number: int) -> list[str]:
        return [plain_of(button) for button in strip(number).buttons]

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.view.live is not None and row_of(1) is not None)
        await pilot.pause(0.1)
        assert labels(1) == ["[TG]", "[FL]", "[RL]"]
        toggle, flash, release = strip(1).buttons
        await pilot.click(toggle)
        await until(pilot, lambda: view(1).state == "active")
        await pilot.mouse_down(flash)
        await until(pilot, lambda: view(1).flash)
        await pilot.mouse_up(flash)
        await until(pilot, lambda: not view(1).flash)
        await pilot.click(release)
        await until(pilot, lambda: view(1).state != "active")

        assert labels(9) == ["[GO]", "[◂]", "[RL]", "[GT]"]
        await pilot.click(strip(9).buttons[3])
        await until(pilot, lambda: view(9).cue == "4")

        await pilot.press("space")  # P1 has no go button, and Space still goes
        await until(pilot, lambda: view(1).state == "active")

        await pilot.press(*'playback 9 buttons ["select"]', "enter")
        await until(pilot, lambda: labels(9) == ["[SL]"], timeout=1.0)
        await pilot.pause(0.1)
        await pilot.click(strip(9).buttons[0])
        await until(pilot, lambda: bool(app.programmer and app.programmer.selection))

        await pilot.press("pagedown")
        await until(pilot, lambda: row_of(None) is not None, timeout=1.0)
        record = strip(None).record
        assert record is not None
        assert record.inert  # a selection is nothing to record
        await pilot.press(*"sel group 2", "enter", *"set intensity 40%", "enter")
        await until(pilot, lambda: not record.inert, timeout=1.0)
        assert record.line.text == "record slot 2.7"
        await pilot.pause(0.1)
        await pilot.click(record)
        await until(pilot, lambda: row_of(None) is None, timeout=2.0)
        assert app.view.show is not None
        page = next(p for p in app.view.show.pages if p.number == 2)
        number = page.slots[6]
        assert number is not None
        await until(pilot, lambda: row_of(number) is not None, timeout=1.0)
        assert labels(number) == ["[TG]", "[FL]"]

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f1_greys_a_goto_its_new_list_lacks_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """P9's goto cue 4, after ``playback 9 cuelist 11`` (Circle: cue 1 only):
    ``[GT]`` grey, with the reason in the hint row, and a click sends
    nothing; ``record cue 11/4`` gives it back, and a click goes there."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(), standalone=True)
    reason = "goto: cue list 11 has no cue 4"

    def goto() -> CommandButton | None:
        rows = app.query_one(StackLayout).rows
        row = next((row for row in rows if row.number == 9), None)
        button = None if row is None else row.buttons[3]
        return button if isinstance(button, CommandButton) else None

    def inert() -> bool | None:
        button = goto()
        return None if button is None else button.inert

    def cue() -> str | None:
        found = None if app.view.live is None else app.view.live.playback(9)
        return None if found is None else found.cue

    def uis() -> list[str]:
        return [text for kind, text in app.query_one(LogView).entries if kind == "ui"]

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.view.live is not None and inert() is False)
        await pilot.press(*"playback 9 cuelist 11", "enter")
        await until(pilot, lambda: inert() is True, timeout=1.0)
        grey = goto()
        assert grey is not None
        assert grey.hint == reason
        await pilot.hover(grey)
        await pilot.pause()
        assert plain_of(app.query_one(HintRow)) == reason
        before = uis()
        await pilot.click(grey)
        await pilot.pause(0.2)
        assert uis() == before
        assert cue() is None

        await pilot.press(*"sel group 2", "enter", *"set intensity 40%", "enter")
        await pilot.press(*"record cue 11/4", "enter")
        await until(pilot, lambda: inert() is False, timeout=1.0)
        live_goto = goto()
        assert live_goto is not None
        await pilot.click(live_goto)
        await until(pilot, lambda: cue() == "4", timeout=1.0)

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f1_edits_a_playback_from_controls_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """Edit mode: a chip, a dialog, a ``[none]``; a typed ``undo``, which redraws
    the panel; a setting changed while the playback runs and its list kept;
    another list once it has released; a new number; the strip it leaves."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(), standalone=True)

    def info(number: int = 9) -> Any:
        assert app.view.show is not None
        return app.view.show.playback(number)

    def state() -> Any:
        assert app.view.live is not None
        found = app.view.live.playback(9)
        assert found is not None
        return found

    def panel() -> PlaybackPanel:
        return app.query_one(PlaybackPanel)

    async def body(pilot: Pilot[int]) -> None:
        async def press(widget: Widget) -> None:
            await pilot.pause(0.1)  # the panel has drawn what changed
            await pilot.click(widget)

        async def answer(button: ActionButton, text: str) -> None:
            await press(button)
            await pilot.pause(0.1)
            assert isinstance(app.screen, TextDialog)
            await answer_field(pilot, app, text)

        await until(pilot, lambda: app.view.live is not None and info() is not None)
        await pilot.pause(0.1)
        await pilot.click("#busk-edit")
        await until(pilot, lambda: bool(app.query_one(PlaybackEditor).tiles))
        tile = next(
            t
            for t in app.query_one(PlaybackEditor).tiles
            if t.info is not None and t.info.number == 9
        )
        await press(tile)
        await until(pilot, lambda: app.view.playback == 9)
        await until(pilot, lambda: panel().chosen() == info())

        await tap_button(pilot, panel().strips["fader"], "size")
        await until(pilot, lambda: info().fader == "size", timeout=2.0)
        await answer(panel().settings["band"].buttons[0], "70")
        await until(pilot, lambda: info().priority == 70, timeout=2.0)
        await answer(panel().settings["flash level"].buttons[0], "75")
        await until(pilot, lambda: info().flashLevel == 0.75, timeout=2.0)
        assert info().exclusivity == "base"
        await press(panel().settings["exclusive"].buttons[1])
        await until(pilot, lambda: info().exclusivity is None, timeout=2.0)
        await until(pilot, lambda: plain_of(panel().settings["exclusive"].value) == "none")

        await pilot.press(*"undo", "enter")
        await until(pilot, lambda: plain_of(panel().settings["exclusive"].value) == "base")
        assert info().exclusivity == "base"

        await pilot.press(*"go 9", "enter")
        await until(pilot, lambda: state().state == "active")
        await until(pilot, lambda: panel().settings["cue list"].buttons[0].inert)
        assert panel().why.display
        await answer(panel().settings["release"].buttons[0], "0")
        await until(pilot, lambda: info().releaseTime == 0.0, timeout=2.0)
        assert state().state == "active"
        await pilot.press(*"release 9 0", "enter")
        await until(pilot, lambda: state().state == "idle")
        await until(pilot, lambda: not panel().settings["cue list"].buttons[0].inert)

        await press(panel().settings["cue list"].buttons[0])
        await pilot.pause(0.1)
        dialog = app.screen
        assert isinstance(dialog, CueListDialog)
        options = [found.number for found in dialog.lists]
        index = options.index(11)
        highlighted = dialog.options.highlighted
        assert highlighted is not None
        keys = (
            ["down"] * (index - highlighted)
            if index > highlighted
            else ["up"] * (highlighted - index)
        )
        await pilot.press(*keys, "enter")
        await until(pilot, lambda: info().cueList == 11, timeout=2.0)

        await press(panel().renumber)
        await pilot.pause(0.1)
        await answer_field(pilot, app, "77")
        await until(pilot, lambda: app.view.playback == 77, timeout=2.0)
        await until(pilot, lambda: panel().chosen() == info(77))
        assert info(9) is None

        await press(panel().done)
        await until(pilot, lambda: app.query_one(StackLayout).display)
        rows = {row.number: row for row in app.query_one(StackLayout).rows}
        assert 77 in rows
        assert 9 not in rows

    try:
        drive(app, body, size=(150, 70))
    finally:
        bridge.stop()


def test_f1_follows_every_slot_in_edit_mode_past_faders_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """``--faders 8`` on Main, whose 13 slots hold P1 to P13: ← → reach slot 13
    in edit mode and stop at 8 out of it, a change of slots keeps P10 chosen
    in edit mode, and leaving edit mode on it moves the selection to P1."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(faders=8), standalone=True)

    async def body(pilot: Pilot[int]) -> None:
        async def arrow(key: str) -> int:
            await pilot.press(key)
            await pilot.pause()
            return app.view.playback

        await until(pilot, lambda: app.view.live is not None and app.view.show is not None)
        await pilot.pause(0.1)
        assert app.view.playback == 1
        assert await arrow("left") == 8
        assert await arrow("right") == 1
        await pilot.click("#busk-edit")
        await until(pilot, lambda: bool(app.query_one(PlaybackEditor).tiles))
        assert await arrow("left") == 13
        assert await arrow("left") == 12
        assert await arrow("left") == 11
        assert await arrow("left") == 10
        await pilot.press(*"page 1 slot 3 clear", "enter")
        await until(
            pilot, lambda: app.view.show is not None and app.view.show.pages[0].slots[2] is None
        )
        await pilot.pause(0.1)
        assert app.view.playback == 10
        assert app.query_one(PlaybackPanel).chosen() == app.view.show.playback(10)
        await pilot.click("#pp-done")
        await pilot.pause(0.1)
        assert app.view.playback == 1
        assert await arrow("left") == 8
        log = app.query_one(LogView).entries
        assert not [text for kind, text in log if kind == "error"]

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_f1_adds_places_and_deletes_playbacks_and_pages_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    """A new playback on an empty slot; another placed on two pages and taken
    off one; a playback deleted, with busk's question, the bindings by slot
    left alone; a new page; the page shown deleted, and the engine on another;
    the last page deleted, and F1 with none; ``undo``."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(), standalone=True)

    def show() -> Any:
        assert app.view.show is not None
        return app.view.show

    def editor() -> PlaybackEditor:
        return app.query_one(PlaybackEditor)

    def on_page() -> int | None:
        assert app.view.live is not None
        return None if app.view.live.page is None else app.view.live.page.number

    def page_slots(number: int) -> tuple[int | None, ...]:
        return next(page.slots for page in show().pages if page.number == number)

    def page_gone(number: int) -> bool:
        return all(page.number != number for page in show().pages)

    async def body(pilot: Pilot[int]) -> None:
        async def tile(slot: int) -> None:
            await pilot.pause(0.1)
            await pilot.click(editor().tiles[slot - 1])
            await until(pilot, lambda: editor().slot == slot)
            await pilot.pause(0.1)

        async def picked(dialog: type[PickDialog], number: int) -> None:
            await until(pilot, lambda: isinstance(app.screen, dialog))
            await pilot.pause(0.1)
            screen = app.screen
            assert isinstance(screen, PickDialog)
            screen.options.highlighted = screen.numbers.index(number)
            await pilot.pause(0.1)
            await pilot.press("enter")

        async def tap(strip: ButtonStrip, label: str) -> None:
            await pilot.pause(0.1)
            await tap_button(pilot, strip, label)

        async def yes(question: str) -> None:
            await until(pilot, lambda: isinstance(app.screen, ConfirmDialog))
            screen = app.screen
            assert isinstance(screen, ConfirmDialog)
            assert question in screen.question
            await pilot.press("y")

        await until(pilot, lambda: app.view.live is not None and app.view.show is not None)
        await pilot.pause(0.1)
        await pilot.click("#busk-edit")
        await until(pilot, lambda: bool(editor().tiles))
        await tap(editor().tabs, "2 Washes")
        await until(pilot, lambda: on_page() == 2)
        await until(pilot, lambda: editor().page is not None and editor().page.number == 2)
        bindings = show().bindings

        await tile(7)
        await tap(editor().slot_edits, "new playback…")
        await picked(CueListDialog, 11)
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await pilot.press("ctrl+u", *"30", "tab", "ctrl+u", *"Encore", "enter")
        await until(pilot, lambda: page_slots(2)[6] == 30, timeout=2.0)
        assert show().playback(30).name == "Encore"
        assert show().playback(30).cueList == 11
        await until(pilot, lambda: app.view.playback == 30, timeout=2.0)

        await tile(14)  # the empty tile past the last slot
        await tap(editor().slot_edits, "place…")
        await picked(PlaybackDialog, 9)
        await until(pilot, lambda: len(page_slots(2)) == 14 and page_slots(2)[13] == 9, timeout=2.0)
        assert page_slots(1)[8] == 9  # a playback on two pages
        await until(pilot, lambda: app.view.playback == 9, timeout=2.0)
        await tap(editor().slot_edits, "clear")
        await until(pilot, lambda: page_slots(2)[13] is None, timeout=2.0)
        assert page_slots(1)[8] == 9  # the other page keeps it

        await tile(7)
        await until(pilot, lambda: app.view.playback == 30)
        await pilot.click(app.query_one(PlaybackPanel).delete)
        await yes('Delete playback 30 "Encore"?')
        await until(pilot, lambda: page_slots(2)[6] is None, timeout=2.0)
        assert show().playback(30) is None
        assert any(binding.what == "fader 7" for binding in bindings)  # its slot, bound
        assert show().bindings == bindings  # those by slot, and the others
        assert app.view.playback != 30

        await tap(editor().tabs, "+ page…")
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await pilot.press("tab", "ctrl+u", *"Encore", "enter")
        await until(pilot, lambda: any(page.number == 3 for page in show().pages), timeout=2.0)
        assert on_page() == 2  # it stays on the page it was on
        await tap(editor().tabs, "3 Encore")
        await until(pilot, lambda: on_page() == 3)
        await until(pilot, lambda: len(editor().tiles) == 1)  # a tile to start on
        await tap(editor().page_edits, "rename…")
        await answer_field(pilot, app, "Last")
        await until(pilot, lambda: page_slots(3) == () and "3 Last" in plain_tabs(editor()))

        await tap(editor().page_edits, "delete")
        await yes('Delete page 3 "Last"?')
        await until(pilot, lambda: on_page() == 2, timeout=2.0)  # the engine moved on
        await until(pilot, lambda: editor().page is not None and editor().page.number == 2)
        assert "3 Last" not in plain_tabs(editor())

        for number, word in ((2, "Washes"), (1, "Main")):
            await tap(editor().page_edits, "delete")
            await yes(f'Delete page {number} "{word}"?')
            await until(pilot, partial(page_gone, number), timeout=2.0)
        await until(pilot, lambda: on_page() is None, timeout=2.0)
        await until(pilot, lambda: editor().page is None)
        await until(pilot, lambda: not editor().page_row.display)
        assert plain_tabs(editor()) == ["+ page…"]
        numbers = [tile.info.number for tile in editor().tiles if tile.info is not None]
        assert numbers == [info.number for info in show().playbacks]  # by number

        await pilot.press(*"undo", "enter")
        await until(pilot, lambda: bool(show().pages), timeout=2.0)
        await until(pilot, lambda: editor().page is not None and editor().page.number == 1)
        assert editor().page_row.display

    try:
        drive(app, body, size=(150, 70))
    finally:
        bridge.stop()


def plain_tabs(editor: PlaybackEditor) -> list[str]:
    return [button.label.plain.strip("[]") for button in editor.tabs.buttons]


def test_f1_c_places_a_fixture_through_its_form_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(layout="C"), standalone=True)

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.view.show is not None and app.view.output is not None)
        layout = app.query_one(StageLayout)
        await until(pilot, lambda: layout.plot.edited() is not None)
        fixture = layout.plot.edited()
        assert fixture is not None
        await pilot.click(layout.edits, offset=(1, 0))
        await until(pilot, lambda: isinstance(app.screen, FormDialog))
        await pilot.press("ctrl+u", *"1", "tab", "ctrl+u", *"7.5", "enter")
        await until(pilot, lambda: 7.5 in [row.y for row in layout.plot.rows], timeout=1.0)
        assert app.view.show is not None
        placed = next(f for f in app.view.show.fixtures if f.number == fixture.number)
        assert placed.location is not None
        assert placed.location[:2] == (1.0, 7.5)

    try:
        drive(app, body)
    finally:
        bridge.stop()


def test_a_refusal_is_one_line_and_a_long_answer_wraps_on_the_real_engine(
    club_path: Path, tmp_path: Path
) -> None:
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(), standalone=True)

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.view.show is not None)
        log = app.query_one(LogView)
        await pilot.press(*"route add 1 sacn 0", "enter")
        message = "expected an sACN universe from 1 to 63999, got 0"
        await until(pilot, lambda: ("error", message) in log.entries)
        assert [e for e in log.entries if e[0] == "error"] == [("error", message)]
        await pilot.press(*"list groups", "enter")  # the club show's lines pass 99 columns
        await until(pilot, lambda: any(kind == "result" for kind, _ in log.entries))
        await pilot.pause()
        room = log.scrollable_content_region.width
        assert len(log.lines) > len(log.entries)
        assert log.max_scroll_x == 0
        assert all(strip.cell_length <= room for strip in log.lines)

    try:
        drive(app, body, size=(99, 40))
    finally:
        bridge.stop()


def test_a_show_from_before_the_ranges_opens_and_says_so(club_path: Path, tmp_path: Path) -> None:
    """Fixture 0 and a route at 44 Hz: a warning each in the log, on the real engine."""
    path = tmp_path / "old.json"
    show = busk.load_show(club_path)[0]
    doc = json.loads(json.dumps(show))
    doc["fixtures"][0]["number"] = 0
    doc["output"]["routes"] = [
        {
            "id": "r-usb",
            "universeId": doc["universes"][0]["id"],
            "enabled": False,
            "protocol": "dmxUsb",
            "device": {"driver": "enttecPro", "port": "/dev/null"},
            "refreshHz": 44,
        }
    ]
    path.write_text(json.dumps(doc), encoding="utf-8")
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(), standalone=True)

    async def body(pilot: Pilot[int]) -> None:
        log = app.query_one(LogView)
        status = app.query_one(StatusBar)
        await until(pilot, lambda: status.engine == "running")
        news = [text for kind, text in log.entries if kind == "warning"]
        assert any("Fixtures are numbered from 1, got 0" in text for text in news)
        assert any("44 Hz is past the widget's 40 Hz" in text for text in news)

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
