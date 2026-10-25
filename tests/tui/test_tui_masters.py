"""F7 Masters (spec §8.7, plan Phase 1): the grand master, the speed
masters, the size and group masters, the fade-time masters and panic.
Headless, with a fake bridge (and the club-night show's questions)."""

from __future__ import annotations

from typing import Any

import pytest
from rich.text import Text
from textual.pilot import Pilot
from textual.widgets import Static
from tui_fakes import FakeBridge, drive, live_state, make_app, settle, show_model

import busk
from busk_tui import colors
from busk_tui.model import (
    Beat,
    GroupInfo,
    LiveChanged,
    MasterLevel,
    MasterView,
    ShowChanged,
    SpeedView,
)
from busk_tui.pages.masters import MastersPage
from busk_tui.shell import BuskApp
from busk_tui.widgets.controls import CommandButton
from busk_tui.widgets.dialogs import ConfirmDialog
from busk_tui.widgets.log import LogView
from busk_tui.widgets.masters import BlackoutButton, MasterBar
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.tempo import Tempo

MASTERS = (
    MasterView("Grand Master", "grand", None, ()),
    MasterView("Speed 1", "speed", None, (0.5, 1.0, 2.0)),
    MasterView("Slow", "speed", None, (1.0,)),
    MasterView("FX", "size", None, ()),
    MasterView("Wash level", "group", GroupInfo(2, "Washes"), ()),
    MasterView("Fade", "fadeTime", None, ()),
)


def live(**changes: Any) -> Any:
    parts: dict[str, Any] = {
        "masters": (
            MasterLevel("Grand Master", "grand", 0.8),
            MasterLevel("Speed 1", "speed", 0.5),
            MasterLevel("Slow", "speed", 0.0),
            MasterLevel("FX", "size", 0.6),
            MasterLevel("Wash level", "group", 0.3),
            MasterLevel("Fade", "fadeTime", 0.4),
        ),
        "speed": (SpeedView("Speed 1", 128.0, 1.0, 0.5), SpeedView("Slow", 60.0, 1.0, 0.0)),
        "fadeTime": 1.6,
        "gm": 0.8,
    }
    parts.update(changes)
    return live_state(**parts)


def on_f7(bridge: FakeBridge, **changes: Any) -> BuskApp:
    bridge.events += [ShowChanged(show_model(masters=MASTERS)), LiveChanged(live(**changes))]
    return make_app(bridge, page=7)


def page(app: BuskApp) -> MastersPage:
    return app.query_one(MastersPage)


def plain(widget: Any) -> str:
    rendered = widget.render()
    return rendered.plain if isinstance(rendered, Text) else str(rendered)


def test_a_panel_per_kind_of_master() -> None:
    bridge = FakeBridge()
    app = on_f7(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        titles = [str(panel.border_title) for panel in page(app).query(Panel)]
        assert titles == [
            "GRAND MASTER",
            "SPEED · Speed 1",
            "SPEED · Slow",
            "SIZE & GROUP MASTERS",
            "FADE TIME",
            "PANIC",
        ]
        bars = {bar.master.name: bar for bar in page(app).query(MasterBar)}
        assert [(name, bar.level, bar.bar.color) for name, bar in bars.items()] == [
            ("Grand Master", 0.8, colors.FG),
            ("Speed 1", 0.5, colors.AMBER),
            ("Slow", 0.0, colors.AMBER),
            ("FX", 0.6, colors.GREEN),
            ("Wash level", 0.3, colors.AMBER),
            ("Fade", 0.4, colors.FG),
        ]
        subs = [plain(s) for s in page(app).query(".sub").results(Static)]
        assert subs == ["size · scales its effects", "group · 2 Washes"]
        assert plain(page(app).fade_now) == "override now 1.6 s"
        assert plain(page(app).output_state) == "output on"

    drive(app, body)


def test_the_grand_master_digits_are_red_during_blackout() -> None:
    bridge = FakeBridge()
    app = on_f7(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        digits = page(app).gm_digits
        assert (digits.text, digits.color) == ("80", colors.FG)
        blackout = page(app).query_one(BlackoutButton)
        assert blackout.label == "BLACKOUT off"
        bridge.events.append(LiveChanged(live(seq=2, blackout=True)))
        await settle(pilot, app)
        assert (digits.text, digits.color) == ("80", colors.RED)
        assert (blackout.label, blackout.reverse, blackout.line.text) == (
            "BLACKOUT on",
            True,
            "blackout off",
        )

    drive(app, body)


def test_speed_panels_tap_step_and_beat() -> None:
    bridge = FakeBridge()
    app = on_f7(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        first, slow = page(app).query(Tempo)
        assert (first.digits.text, slow.digits.text) == ("128.0", "60.0")
        assert first.tap.reverse
        assert first.tap.intent == "tempo"
        steps = first.steps.content
        assert isinstance(steps, Text)
        assert steps.plain == "steps x 0.5  x 1  x 2 "
        lit = [s for s in steps.spans if f"on {colors.AMBER}" in str(s.style)]
        assert [steps.plain[s.start : s.end] for s in lit] == [" x 1 "]
        for button in (first.tap, first.slower, first.faster, slow.tap):
            await pilot.click(button)
        assert bridge.lines() == [
            'tap "Speed 1"',
            'bpm "Speed 1" 127',
            'bpm "Speed 1" 129',
            'tap "Slow"',
        ]
        bridge.events.append(Beat(1.0, (5.1, 2.6)))
        await settle(pilot, app)
        assert (first.dots.beats, slow.dots.beats) == (5.1, 2.6)

    drive(app, body)


def test_a_master_bar_sets_its_master() -> None:
    bridge = FakeBridge()
    app = on_f7(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        bars = {bar.master.name: bar for bar in page(app).query(MasterBar)}
        for name in ("Grand Master", "FX", "Fade"):
            bar = bars[name].bar
            await pilot.click(bar, offset=(bar.size.width - 1, 0))
        logged = [text for kind, text in app.query_one(LogView).entries if kind == "ui"]
        assert logged == ["gm 100%", 'master "FX" 100%', 'master "Fade" 100%']
        keys = {sent.key for sent in bridge.sent}
        assert keys == {"gm", "master:FX", "master:Fade"}

    drive(app, body)


def test_panic_asks_before_output_off(club: busk.OfflineShow) -> None:
    bridge = FakeBridge(show=club)
    app = on_f7(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click(page(app).release_all)
        await pilot.click(page(app).output_on)
        await pilot.click(page(app).gm_full)
        assert bridge.lines() == ["release all", "output on", "gm 100%"]
        await pilot.click(page(app).output_off)
        assert isinstance(app.screen, ConfirmDialog)
        await pilot.press("n")
        assert ("info", "cancelled: output off") in app.query_one(LogView).entries
        await pilot.click(page(app).output_off)
        await pilot.press("y")
        assert bridge.lines()[-1] == "output off"
        bridge.events.append(LiveChanged(live(seq=2, outputEnabled=False)))
        await settle(pilot, app)
        assert plain(page(app).output_state) == "output  OUTPUT OFF "

    drive(app, body)


@pytest.mark.parametrize(("width", "columns"), [(150, 3), (100, 2), (99, 1)])
def test_the_panels_columns_by_width(width: int, columns: int) -> None:
    bridge = FakeBridge()
    app = on_f7(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        panels = list(page(app).query(Panel))
        lefts = sorted({panel.region.x for panel in panels})
        assert len(lefts) == columns
        assert all(panel.region.right <= width for panel in panels)

    drive(app, body, size=(width, 48))


def test_a_new_master_rebuilds_the_page_and_keyboard_reaches_each_control() -> None:
    bridge = FakeBridge()
    app = on_f7(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        bridge.events.append(
            ShowChanged(show_model(masters=(*MASTERS[:1], MasterView("Big", "size", None, ()))))
        )
        await settle(pilot, app)
        assert [b.master.name for b in page(app).query(MasterBar)] == ["Grand Master", "Big"]
        assert not page(app).query(Tempo)
        items = [item.line or item.prefill for item in page(app).items()]
        assert items == [
            "gm ", "blackout on", "gm 100%", 'master "Big" ',
            "release all", "output off", "output on",
        ]  # fmt: skip
        await pilot.press("tab", "down", "down", "enter")
        assert bridge.lines() == ["gm 100%"]
        assert isinstance(page(app).query_one("#masters-grid").children[0], Panel)
        assert all(
            isinstance(b, CommandButton) for b in (page(app).release_all, page(app).output_on)
        )

    drive(app, body)
