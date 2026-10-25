"""Playback rows (spec §8.1, layout B; plan §2.2).

A row shows one slot of the current page: ``Pn``, the name, the level as a
bar in the current cue's colour, the level, the cue and the next one (or a
chase's rate and direction), and ``[GO] [◂] [FL]``. The bar sets the fader
(``fader N p%``, a click, a drag or the wheel), GO and ◂ run ``go N`` and
``back N``, and FLASH is held while the mouse button is down (``flash N
on``, then ``flash N off``). A click on ``Pn`` or the name selects the
playback for Space and ``[ ]``. An empty slot shows ``·`` and ``—``.
"""

from __future__ import annotations

from functools import partial
from typing import Final

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.colors import ColorMode
from busk_tui.model import CueListInfo, PlaybackInfo, PlaybackView
from busk_tui.widgets.bars import HBar
from busk_tui.widgets.controls import CommandButton, RunLine

FADER_TAGS: Final = {
    "crossfade": "xfade",
    "rate": "rate",
    "size": "size",
    "temp": "temp",
    "none": "no fader",
}
"""How a row names a fader that is not a master (busk's ``fader`` function)."""

LEVEL_COLORS: Final = {"active": colors.FG, "releasing": colors.AMBER}  # idle: dim

COLUMNS = """
    .pb-label { width: 4; }
    .pb-name { width: 16; padding-right: 1; text-wrap: nowrap; text-overflow: ellipsis; }
    .pb-bar { width: 3fr; min-width: 12; }
    .pb-level { width: 5; text-align: right; padding-right: 1; }
    .pb-cue { width: 2fr; text-wrap: nowrap; text-overflow: ellipsis; }
    .pb-buttons { width: 14; }
"""
"""The columns of :class:`PlaybackRow` and of the header above the rows."""


def playback_color(view: PlaybackView | None, info: PlaybackInfo | None, mode: ColorMode) -> str:
    """The colour a playback is drawn in: its current cue's, else its
    ``uiColor``, else the foreground (plan §3, 9)."""
    color = view.color if view is not None and view.color is not None else None
    if color is None and info is not None:
        color = info.uiColor
    return colors.FG if color is None else colors.swatch(color, 1.0, mode)


def cue_text(view: PlaybackView, cue_list: CueListInfo | None) -> Text:
    """Where the playback is in its list: ``2/5 Verse → Pre``; a chase,
    ``chase 4 Step 2 bpm x 1 bounce``; idle, ``—/5 → Intro``."""
    order = [] if cue_list is None else [cue.number for cue in cue_list.cues]

    def name(number: str) -> str:
        if number == view.cue and view.cueName:
            return view.cueName
        cue = (
            None
            if cue_list is None
            else next((c for c in cue_list.cues if c.number == number), None)
        )
        return cue.name if cue is not None and cue.name else f"cue {number}"

    text = Text()
    if view.chase:
        text.append(f"chase {view.cueCount}", style=colors.FG)
        if view.cue is not None:
            text.append(f" {name(view.cue)}", style=colors.FG)
        if cue_list is not None and cue_list.chase is not None:
            text.append(f" {cue_list.chase}", style=colors.DIM)
        return text
    if view.cue is None:
        text.append(f"—/{view.cueCount}", style=colors.DIM)
    else:
        position = order.index(view.cue) + 1 if view.cue in order else "?"
        text.append(f"{position}/{view.cueCount} {name(view.cue)}", style=colors.FG)
        if view.progress is not None:
            text.append(f" {round(view.progress * 100)}%", style=colors.AMBER)
    if view.next is not None and view.next != view.cue:
        text.append(f" → {name(view.next)}", style=colors.DIM)
    return text


class FlashButton(Static):
    """``[FL]``: ``flash N on`` while the mouse button is down on it, ``flash
    N off`` when it comes up or the pointer leaves. Lit while held, here or
    elsewhere (a surface, a flash this TUI held before it restarted)."""

    DEFAULT_CSS = "FlashButton { width: auto; height: 1; }"

    def __init__(self, number: int) -> None:
        self.number = number
        self.held = False
        self.lit = False
        super().__init__(self._text())

    def show(self, lit: bool) -> None:
        if lit != self.lit:
            self.lit = lit
            self.update(self._text())

    def _text(self) -> Text:
        if self.held or self.lit:
            return Text("[FL]", style=f"bold {colors.BG} on {colors.AMBER}")
        return Text("[FL]", style=colors.AMBER)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        event.stop()
        if not self.held:
            self.held = True
            self.capture_mouse()
            self.update(self._text())
            self.post_message(RunLine(commands.flash(self.number, True)))

    def on_mouse_up(self, event: events.MouseUp) -> None:
        event.stop()
        self._let_go()

    def on_leave(self, event: events.Leave) -> None:
        self._let_go()

    def on_click(self, event: events.Click) -> None:
        event.stop()

    def _let_go(self) -> None:
        if self.held:
            self.held = False
            self.release_mouse()
            self.update(self._text())
            self.post_message(RunLine(commands.flash(self.number, False)))


class PlaybackRow(Horizontal):
    """One slot: playback ``number``, or ``None`` for an empty one (see the
    module docs). The page redraws it with :meth:`show`."""

    DEFAULT_CSS = f"""
    PlaybackRow {{ height: 1; }}
    PlaybackRow.-selected {{ background: {colors.BAR}; }}
    PlaybackRow > .pb-buttons {{ height: 1; }}
    PlaybackRow CommandButton, PlaybackRow FlashButton {{ margin-left: 1; }}
    {COLUMNS}
    """

    class Chosen(Message):
        """The operator chose this row's playback (a click on ``Pn``)."""

        def __init__(self, number: int) -> None:
            super().__init__()
            self.number = number

    def __init__(self, slot: int, number: int | None) -> None:
        super().__init__()
        self.slot = slot
        self.number = number
        self._shown: object = None
        empty = number is None
        self.label = Static(
            Text("·" if empty else f"P{number}", style=colors.BORDER), classes="pb-label"
        )
        self.name_text = Static(Text("—", style=colors.BORDER) if empty else "", classes="pb-name")
        command = None if number is None else partial(commands.fader, number)
        self.bar = HBar(command=command, key=f"fader:{number}", classes="pb-bar")
        self.level = Static("", classes="pb-level")
        self.cue = Static("", classes="pb-cue")
        self.buttons: list[CommandButton] = []
        self.flash: FlashButton | None = None
        if number is not None:
            self.buttons = [
                CommandButton("GO", commands.go(number), "go"),
                CommandButton("◂", commands.back(number)),
            ]
            self.flash = FlashButton(number)

    def compose(self) -> ComposeResult:
        yield self.label
        yield self.name_text
        yield self.bar
        yield self.level
        yield self.cue
        with Horizontal(classes="pb-buttons"):
            yield from self.buttons
            if self.flash is not None:
                yield self.flash

    def show(
        self,
        view: PlaybackView | None,
        info: PlaybackInfo | None,
        cue_list: CueListInfo | None,
        selected: bool,
        mode: ColorMode,
    ) -> None:
        """Draw the playback as ``view`` (live) and ``info`` (the show) have it."""
        number = self.number
        if number is None or (view, info, cue_list, selected, mode) == self._shown:
            return
        self._shown = (view, info, cue_list, selected, mode)
        self.set_class(selected, "-selected")
        self.label.update(Text(f"P{number}", style=colors.CYAN if selected else colors.DIM))
        state = "idle" if view is None else view.state
        name = Text(
            view.name if view is not None else info.name if info is not None else "",
            style=colors.MID if state == "idle" else colors.FG,
        )
        if view is not None and view.fader in FADER_TAGS:
            name.append(f" {FADER_TAGS[view.fader]}", style=colors.DIM)
        self.name_text.update(name)
        level = 0.0 if view is None else view.level
        no_fader = view is not None and view.fader == "none"
        self.bar.command = None if no_fader else partial(commands.fader, number)
        self.bar.show_level(0.0 if no_fader else level, playback_color(view, info, mode))
        self.level.update(
            Text(
                "—" if no_fader else str(round(level * 100)),
                style=LEVEL_COLORS.get(state, colors.DIM),
            )
        )
        self.cue.update(Text() if view is None else cue_text(view, cue_list))
        if self.flash is not None:
            self.flash.show(view is not None and view.flash)

    def on_click(self, event: events.Click) -> None:
        widget = event.widget
        if self.number is None or widget is None:
            return
        if widget.has_class("pb-label") or widget.has_class("pb-name"):
            event.stop()
            self.post_message(self.Chosen(self.number))


class PlaybackHeader(Horizontal):
    """The column names over the rows (dim)."""

    DEFAULT_CSS = f"""
    PlaybackHeader {{ height: 1; color: {colors.DIM}; }}
    {COLUMNS}
    """

    def compose(self) -> ComposeResult:
        yield Static("#", classes="pb-label")
        yield Static("name", classes="pb-name")
        yield Static("level", classes="pb-bar")
        yield Static("", classes="pb-level")
        yield Static("cue → next", classes="pb-cue")
        yield Static("", classes="pb-buttons")
