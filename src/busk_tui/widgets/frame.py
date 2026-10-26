"""The frame around every page (spec §5): the status bar, the tabs and the
key legend."""

from __future__ import annotations

import time

from rich.style import Style
from rich.text import Text
from textual.widget import Widget

from busk_tui import colors
from busk_tui.model import (
    EngineState,
    LiveState,
    ProgrammerModel,
    RouteView,
    SessionState,
)
from busk_tui.widgets.controls import chip

PAGES: tuple[tuple[int, str], ...] = (
    (1, "Busk"),
    (2, "Program"),
    (3, "Fixtures"),
    (4, "Cues"),
    (5, "Effects"),
    (6, "Presets"),
    (7, "Masters"),
    (8, "Patch"),
    (9, "Surfaces"),
)
"""The pages by F-key (F9 is "Surfaces": MIDI, OSC and the web remote)."""

HELP_KEY = 10

NBSP = "\u00a0"  # keeps a tab's key and name together when the tabs wrap

BLINK_S = 0.25
"""A route's light changes at most this often while it sends."""

_ENGINE_WARNINGS: dict[EngineState, bool] = {
    "starting": False,
    "stalled": True,
    "restarting": True,
    "failed": True,
    "stopped": False,
}  # the state → whether its chip is red (else dim); "running" has none


class RouteLights:
    """Each route's light: lit while it does not send, blinking while its
    ``packets`` grow, at most every :data:`BLINK_S`."""

    def __init__(self) -> None:
        self._lights: list[tuple[int, bool, float]] = []  # per route: packets, on, when it changed

    def update(self, routes: tuple[RouteView, ...], now: float) -> tuple[bool, ...]:
        """Whether each light is on, given the routes as they are ``now``."""
        lights: list[tuple[int, bool, float]] = []
        for index, route in enumerate(routes):
            packets, on, changed = (
                self._lights[index] if index < len(self._lights) else (route.packets, True, now)
            )
            if route.packets != packets and now - changed >= BLINK_S:
                on, changed = not on, now
            elif route.packets == packets and not on and now - changed >= BLINK_S:
                on, changed = True, now  # it stopped sending: steady
            lights.append((route.packets, on, changed))
        self._lights = lights
        return tuple(on for _, on, _ in lights)


class StatusBar(Widget):
    """Row 1: what the show and the engine are doing (spec §5, plan §3 15).

    The app hands it each piece as it changes; it draws them all in one line,
    the clock right-aligned, and cuts what does not fit."""

    DEFAULT_CSS = f"StatusBar {{ height: 1; background: {colors.BAR}; }}"

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.title = ""
        self.session: SessionState | None = None
        self.live: LiveState | None = None
        self.programmer: ProgrammerModel | None = None
        self.routes: tuple[RouteView, ...] = ()
        self.engine: EngineState = "starting"
        self.late = False
        self.beats: float | None = None
        self._lights = RouteLights()
        self._on: tuple[bool, ...] = ()

    # ------------------------------------------------------------- input

    def set_routes(self, routes: tuple[RouteView, ...], now: float | None = None) -> None:
        """New route states: a route whose packets grew blinks."""
        now = time.monotonic() if now is None else now
        self._on = self._lights.update(routes, now)
        self.routes = routes
        self.refresh()

    def tick(self, now: float | None = None) -> None:
        """Each second: the clock, and the lights of routes that stopped
        sending (no new routes come while nothing changes)."""
        self._on = self._lights.update(self.routes, time.monotonic() if now is None else now)
        self.refresh()

    def set_beats(self, beats: float | None) -> None:
        """The first speed master's beat count; redraws only when the dot changes."""
        before = _on_beat(self.beats)
        self.beats = beats
        if _on_beat(beats) != before:
            self.refresh()

    # ----------------------------------------------------------- drawing

    def left_text(self) -> Text:
        """Everything but the clock."""
        text = Text()
        text.append(" busk ", style=f"bold {colors.BG} on {colors.CYAN}")
        text.append("  show ", style=colors.DIM)
        title = self.title if len(self.title) <= 24 else self.title[:23] + "…"
        text.append(title or "—", style=colors.FG)
        if self.session is not None and self.session.dirty:
            text.append(" *", style=colors.AMBER)
        if self.engine != "running":
            red = _ENGINE_WARNINGS[self.engine]
            text.append("  ")
            text.append_text(
                chip(f"ENGINE {self.engine.upper()}", True, colors.RED)
                if red
                else Text(f" ENGINE {self.engine.upper()} ", style=colors.DIM)
            )
        if self.late:
            text.append("  LATE", style=colors.DIM)
        live = self.live
        if live is not None and not live.outputEnabled:
            text.append("  ")
            text.append_text(chip("OUTPUT OFF", True, colors.RED))
        for route, on in zip(self.routes, self._on, strict=False):
            text.append("  ")
            text.append_text(route_light(route, on))
        gm = 1.0 if live is None else live.gm
        text.append("  GM ", style=colors.DIM)
        text.append(f"{round(gm * 100)}%", style=colors.AMBER if gm < 0.995 else colors.FG)
        speed = live.speed[0] if live is not None and live.speed else None
        if speed is not None:
            text.append("  BPM ", style=colors.DIM)
            text.append(f"{speed.bpm:.1f}", style=colors.AMBER)
            text.append(" ●", style=colors.AMBER if _on_beat(self.beats) else colors.TRACK)
        programmer = self.programmer
        text.append("  FADE ", style=colors.DIM)
        fade = 0.0 if programmer is None else programmer.fadeTime
        text.append(f"{fade:.1f}s", style=colors.FG)
        text.append("  PROG ", style=colors.DIM)
        text.append(str(0 if programmer is None else programmer.fixtures), style=colors.MAGENTA)
        text.append("  ")
        text.append_text(chip("BLIND", programmer is not None and programmer.blind, colors.MAGENTA))
        text.append(" ")
        text.append_text(chip("BLACKOUT", live is not None and live.blackout, colors.RED))
        if live is not None and live.page is not None:
            text.append("  PAGE ", style=colors.DIM)
            text.append(f"{live.page.number} {live.page.name}", style=colors.FG)
        return text

    def render(self) -> Text:
        clock = time.strftime("%H:%M:%S") + " "
        left = self.left_text()
        room = max(0, self.size.width - len(clock) - 1)
        if left.cell_len > room:
            left.truncate(room, overflow="ellipsis")
        left.pad_right(self.size.width - left.cell_len - len(clock))
        left.append(clock, style=colors.MID)
        return left


def _on_beat(beats: float | None) -> bool:
    """Whether the beat dot is lit: the first quarter of each beat."""
    return beats is not None and beats % 1.0 < 0.25


def route_light(route: RouteView, on: bool, label: str | None = None) -> Text:
    """``● sACN·U1``: green while open (``○`` while a blink is off), red
    when it fails, grey otherwise; ``label`` instead of the route's name."""
    label = f"{route.protocol}·U{route.universe}" if label is None else label
    if route.state == "ok":
        return Text(("● " if on else "○ ") + label, style=colors.GREEN)
    if route.state == "failed":
        return Text("● " + label, style=colors.RED)
    return Text("○ " + label, style=colors.BORDER)  # disabled, ignored, or no output


class TabBar(Widget):
    """F1 … F10, the current one in reverse video; wraps when narrow."""

    DEFAULT_CSS = f"""
    TabBar {{
        height: auto; border-bottom: solid {colors.BORDER}; padding: 0 1;
        link-style: none; link-style-hover: none; link-background-hover: {colors.SEL};
        link-color-hover: {colors.FG};
    }}
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.current = 1
        self.help_open = False

    def show(self, current: int, help_open: bool) -> None:
        if (current, help_open) != (self.current, self.help_open):
            self.current, self.help_open = current, help_open
            self.refresh(layout=True)

    def render(self) -> Text:
        text = Text()
        for number, name in (*PAGES, (HELP_KEY, "Help")):
            action = "app.toggle_help" if number == HELP_KEY else f"app.page({number})"
            click = Style(meta={"@click": action})
            if text:
                text.append("  ")
            active = self.help_open if number == HELP_KEY else number == self.current
            if active and (number == HELP_KEY or not self.help_open):
                text.append(
                    f" F{number}{NBSP}{name} ",
                    style=Style(color=colors.BG, bgcolor=colors.CYAN) + click,
                )
            else:
                text.append(f" F{number}", style=Style(color=colors.CYAN) + click)
                text.append(f"{NBSP}{name} ", style=Style(color=colors.MID) + click)
        return text


class KeyLegend(Widget):
    """The last row: the keys that work everywhere."""

    DEFAULT_CSS = "KeyLegend { height: 1; }"

    KEYS: tuple[tuple[str, str], ...] = (
        ("F1–F9", "pages"),
        ("F10 ?", "help"),
        ("space", "GO"),
        ("← →", "playback"),
        ("[ ]", "fader"),
        ("PgUp PgDn", "page"),
        ("↑ ↓", "history"),
        ("tab", "complete"),
        ("esc", "clear"),
        ("ctrl+c ×2", "quit"),
    )

    def render(self) -> Text:
        text = Text()
        for key, action in self.KEYS:
            if text:
                text.append("  ")
            text.append(key, style=colors.CYAN)
            text.append(" " + action, style=colors.DIM)
        return text
