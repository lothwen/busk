"""The frame (spec §5, plan step 0.3): pages and their keys, reflow, and the
status bar following the engine. Headless, with a fake bridge."""

from __future__ import annotations

import time

import pytest
from rich.text import Text
from textual.pilot import Pilot
from textual.widgets import ContentSwitcher
from tui_fakes import FakeBridge, drive, live_state, make_app, programmer, settle, show_model

from busk_tui import colors
from busk_tui.model import (
    Beat,
    Busy,
    HealthChanged,
    LiveChanged,
    PageView,
    ProgrammerChanged,
    RouteView,
    SessionChanged,
    SessionState,
    ShowChanged,
)
from busk_tui.shell import BuskApp
from busk_tui.widgets.frame import PAGES, StatusBar, TabBar
from busk_tui.widgets.help import HelpOverlay
from busk_tui.widgets.log import LogView
from busk_tui.widgets.prompt import HintRow, PromptRow


def styles_at(text: Text, needle: str) -> list[str]:
    """The styles of the spans over the first character of ``needle``."""
    index = text.plain.index(needle)
    return [str(span.style) for span in text.spans if span.start <= index < span.end]


def route(
    state: str | None, packets: int = 0, protocol: str = "sACN", universe: int = 1
) -> RouteView:
    return RouteView(protocol, universe, state != "disabled", state, "", packets)  # type: ignore[arg-type]


@pytest.mark.parametrize("number", [n for n, _ in PAGES])
def test_each_page_by_its_f_key_and_alt_digit(number: int) -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        await pilot.press(f"f{number}")
        assert app.query_one(ContentSwitcher).current == f"page-{number}"
        assert app.page == number
        assert app.query_one(TabBar).current == number
        await pilot.press("f1" if number != 1 else "f2")
        await pilot.press(f"alt+{number}")
        assert app.query_one(ContentSwitcher).current == f"page-{number}"

    drive(app, body)


def test_f10_and_alt_0_toggle_help() -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        help_overlay = app.query_one(HelpOverlay)
        await pilot.press("f10")
        assert help_overlay.is_open
        assert app.query_one(TabBar).help_open
        await pilot.press("f10")
        assert not help_overlay.is_open
        await pilot.press("alt+0")
        assert help_overlay.is_open
        await pilot.press("f3")  # a page closes help
        assert not help_overlay.is_open
        assert app.page == 3

    drive(app, body)


def test_a_tab_click_switches_the_page() -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        tabs = app.query_one(TabBar)
        x = tabs.render().plain.index("F4") + 1  # padding: 1 cell
        await pilot.click(TabBar, offset=(x + 1, 0))
        assert app.page == 4

    drive(app, body)


def test_the_last_page_is_where_it_starts() -> None:
    app = make_app(page=6)

    async def body(pilot: Pilot[int]) -> None:
        assert app.query_one(ContentSwitcher).current == "page-6"
        assert app.query_one(TabBar).current == 6

    drive(app, body)


@pytest.mark.parametrize(
    ("size", "narrow"), [((99, 30), True), ((100, 30), False), ((150, 48), False)]
)
def test_the_frame_fits_and_reflows(size: tuple[int, int], narrow: bool) -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        width, height = size
        assert app.screen.has_class("narrow") is narrow
        assert app.query_one(StatusBar).region.y == 0
        assert app.query_one("#legend").region.y == height - 1
        assert app.query_one("#hint").region.y == height - 2
        assert app.query_one(PromptRow).region.y == height - 3
        log = app.query_one(LogView)
        assert log.region.height == 7
        assert log.region.bottom == height - 3
        assert app.query_one(ContentSwitcher).region.height > 0
        assert all(widget.region.right <= width for widget in app.query("*") if widget.display)

    drive(app, body, size=size)


def test_the_tabs_wrap_when_narrow() -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        tabs = app.query_one(TabBar)
        assert tabs.region.height == 3  # two rows and the border
        assert "F9\u00a0Surfaces" in tabs.render().plain

    drive(app, body, size=(80, 30))


def test_the_status_bar_follows_the_engine() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        status = app.query_one(StatusBar)
        bridge.events += [
            ShowChanged(show_model()),
            LiveChanged(live_state(gm=0.8, blackout=True, page=PageView(2, "Washes"))),
            ProgrammerChanged(programmer(fixtures=3, blind=True, fadeTime=2.5)),
            SessionChanged(SessionState(4, 0, dirty=True)),
            HealthChanged("running", False),
        ]
        await settle(pilot, app)
        text = status.left_text()
        plain = text.plain
        assert "show Club Night *" in plain
        assert "GM 80%" in plain
        assert colors.AMBER in styles_at(text, "80%")[0]
        assert "BPM 120.0 ●" in plain
        assert "FADE 2.5s" in plain
        assert "PROG 3" in plain
        assert f"on {colors.MAGENTA}" in styles_at(text, "BLIND")[0]
        assert f"on {colors.RED}" in styles_at(text, "BLACKOUT")[0]
        assert "PAGE 2 Washes" in plain
        assert "ENGINE" not in plain
        assert "OUTPUT OFF" not in plain
        bridge.events.append(LiveChanged(live_state(gm=1.0, outputEnabled=False)))
        await settle(pilot, app)
        text = status.left_text()
        assert colors.FG in styles_at(text, "100%")[0]
        assert f"on {colors.RED}" in styles_at(text, "OUTPUT OFF")[0]
        assert colors.BORDER in styles_at(text, "BLACKOUT")[0]  # off now
        assert f"on {colors.MAGENTA}" in styles_at(text, "BLIND")[0]  # as it was

    drive(app, body)


@pytest.mark.parametrize(
    ("state", "shown", "red"),
    [
        ("starting", "ENGINE STARTING", False),
        ("stalled", "ENGINE STALLED", True),
        ("restarting", "ENGINE RESTARTING", True),
        ("failed", "ENGINE FAILED", True),
        ("stopped", "ENGINE STOPPED", False),
    ],
)
def test_the_engine_chip_by_state(state: str, shown: str, red: bool) -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(HealthChanged(state, False))  # type: ignore[arg-type]
        await settle(pilot, app)
        text = app.query_one(StatusBar).left_text()
        style = styles_at(text, shown)[0]
        assert (f"on {colors.RED}" in style) is red
        bridge.events.append(HealthChanged("running", True))
        await settle(pilot, app)
        text = app.query_one(StatusBar).left_text()
        assert "ENGINE" not in text.plain
        assert "LATE" in text.plain

    drive(app, body)


def test_route_lights_and_their_blink() -> None:
    status = StatusBar()
    routes = (
        route("ok", 10),
        route("failed", protocol="ArtNet", universe=2),
        route("disabled", universe=3),
        route(None, universe=4),
    )
    status.set_routes(routes, now=0.0)
    text = status.left_text()
    assert "● sACN·U1" in text.plain
    assert colors.GREEN in styles_at(text, "● sACN·U1")[0]
    assert colors.RED in styles_at(text, "● ArtNet·U2")[0]
    assert colors.BORDER in styles_at(text, "○ sACN·U3")[0]
    assert colors.BORDER in styles_at(text, "○ sACN·U4")[0]
    sending = (route("ok", 20), *routes[1:])
    status.set_routes(sending, now=0.1)  # too soon to change
    assert "● sACN·U1" in status.left_text().plain
    status.set_routes((route("ok", 30), *routes[1:]), now=0.3)
    assert "○ sACN·U1" in status.left_text().plain
    status.set_routes((route("ok", 40), *routes[1:]), now=0.6)
    assert "● sACN·U1" in status.left_text().plain
    status.set_routes((route("ok", 50), *routes[1:]), now=0.9)
    status.set_routes((route("ok", 50), *routes[1:]), now=1.2)  # stopped sending: steady on
    assert "● sACN·U1" in status.left_text().plain


def test_the_beat_dot_is_lit_in_the_first_quarter_of_each_beat() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        status = app.query_one(StatusBar)
        bridge.events += [LiveChanged(live_state()), Beat(1.0, (8.1,))]
        await settle(pilot, app)
        assert colors.AMBER in styles_at(status.left_text(), "●")[0]
        bridge.events.append(Beat(1.1, (8.4,)))
        await settle(pilot, app)
        assert colors.TRACK in styles_at(status.left_text(), "●")[0]

    drive(app, body)


def test_the_prompt_context() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events += [
            ProgrammerChanged(programmer(selection=((101, 1), (102, 1)))),
            LiveChanged(live_state()),
            SessionChanged(SessionState(3, 0, False)),
        ]
        await settle(pilot, app)
        app._show_context()
        assert app._context_text == "sel 2 · page 1 · P1 · undo 3"
        bridge.busy_line = Busy("save", time.monotonic() - 1.43)
        app._show_context()
        assert app._context_text.startswith("⧗ save 1.4s · sel 2")
        bridge.busy_line = Busy("save", time.monotonic() - 0.1)  # not yet
        app._show_context()
        assert not app._context_text.startswith("⧗")

    drive(app, body)


def test_the_bridge_starts_with_the_app_and_watches_nothing(tmp_path: object) -> None:
    bridge = FakeBridge()
    app: BuskApp = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        assert bridge.started
        await pilot.press("f3")
        assert bridge.watching == (False, False)
        assert isinstance(app.query_one(HintRow), HintRow)

    drive(app, body)


def test_a_closing_app_takes_nothing_in() -> None:
    """The app's timers still run while its screens are taken down: a drain
    then must not look for widgets that are gone."""
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        pass

    drive(app, body)
    bridge.events.append(LiveChanged(live_state()))
    app.drain()
    app._show_context()
    assert bridge.events  # left for a drain that never comes
