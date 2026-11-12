"""F7 Masters (spec §8.7, adaptation 14).

* GRAND MASTER: its level in big digits (red while blackout is on), its
  bar, ``[BLACKOUT on|off]`` and ``[gm 100]``.
* SPEED · name, one panel per speed master: BPM, beat dots, TAP, ``[−1]
  [+1]``, its level bar and its multiplier steps.
* SIZE & GROUP MASTERS: a bar per master, with what it scales.
* FADE TIME (busk's): a bar per fade-time master, and the fade-time
  override that transitions starting now take.
* PANIC (busk's): ``[release all]``, ``[OUTPUT OFF]`` (busk asks first),
  ``[OUTPUT ON]``; the strobe cap (``strobe cap 3 Hz``, or ``off``), with
  ``[cap…]``, a rate dialog and then ``safety strobe 3``, and ``[off]``,
  ``safety strobe off`` (pending plan Phase 36).
* PARKED (busk's): a row per value park holds, with ``[unpark]``, and
  ``[unpark all]`` (:mod:`busk_tui.widgets.parked`).
* MASTERS (busk's): a row per master but the grand master, with
  ``[rename…]`` and ``[delete]``, and ``[+ master…]``
  (:mod:`busk_tui.widgets.master_panel`).

Panels are laid out three across from 132 columns, two from 100, and one
under the other below that.
"""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal
from textual.widget import Widget
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.model import LiveState, MasterView, ShowModel
from busk_tui.nav import Item, Stop
from busk_tui.pages.base import Page, Part, View
from busk_tui.widgets.chase_dialog import check_rate, plain_number
from busk_tui.widgets.controls import ActionButton, CommandButton, RunLine, chip
from busk_tui.widgets.dialogs import TextDialog
from busk_tui.widgets.digits import BigDigits
from busk_tui.widgets.master_panel import MasterPanel
from busk_tui.widgets.masters import BlackoutButton, MasterBar, master_item
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.parked import ParkedPanel, ParkedRow, parked_rows
from busk_tui.widgets.tempo import Tempo

PANEL_WIDTH = 44
"""The narrowest a panel is laid out (a speed panel's digits and buttons fit)."""

CAP_NOTE = "The fastest any fixture strobes, in Hz."


def what_it_scales(master: MasterView) -> str:
    if master.kind == "group" and master.group is not None:
        return f"group · {master.group.number} {master.group.name}"
    if master.kind == "size":
        return "size · scales its effects"
    return master.kind


class MastersPage(Page):
    """F7 (see the module docs)."""

    DEFAULT_CSS = """
    MastersPage > #masters-grid {
        layout: grid; grid-size: 3; grid-columns: 1fr 1fr 1fr; grid-rows: auto;
        grid-gutter: 0 1; height: auto;
    }
    MastersPage .buttons { height: 1; margin-top: 1; }
    MastersPage .buttons > CommandButton { margin-right: 2; }
    MastersPage .buttons > .strobe-cap { width: auto; margin-right: 2; }
    MastersPage .sub { color: #767676; padding-left: 9; margin-bottom: 1; }
    MastersPage .gm-digits { margin-bottom: 1; }
    """

    def __init__(self, number: int, title: str) -> None:
        super().__init__(number, title)
        self.grid = Grid(id="masters-grid")
        self.shape: tuple[tuple[MasterView, ...], tuple[ParkedRow, ...]] | None = None
        self.cap_hz: float | None = None  # the show's strobe cap, as last shown
        self._widgets()

    def _widgets(self) -> None:
        """The panels' widgets, new (a widget once removed is not mounted again)."""
        self.gm_digits = BigDigits("100", classes="gm-digits")
        self.gm_bar: MasterBar | None = None
        self.blackout = BlackoutButton(words=True)
        self.gm_full = CommandButton("gm 100", commands.gm(1.0))
        self.tempos: list[Tempo] = []
        self.bars: list[MasterBar] = []
        self.fade_now = Static("")
        self.output_state = Static("")
        self.release_all = CommandButton("release all", commands.release_all(), "tempo")
        self.output_off = CommandButton("OUTPUT OFF", commands.output(False), "danger")
        self.output_on = CommandButton("OUTPUT ON", commands.output(True), "go")
        self.strobe_cap = Static("", classes="strobe-cap")
        self.cap = ActionButton("cap…", self.ask_cap)
        self.cap_off = CommandButton("off", commands.no_strobe_cap(), inert=True)
        self.parked = ParkedPanel((), 0)
        self.setup = MasterPanel(None)

    def compose(self) -> ComposeResult:
        yield self.grid

    def on_resize(self, event: events.Resize) -> None:
        width = event.size.width
        columns = 1 if width < 100 else max(1, min(3, width // PANEL_WIDTH))
        self.grid.styles.grid_size_columns = columns
        self.grid.styles.grid_columns = " ".join(["1fr"] * columns)

    def update_view(self, view: View, changed: frozenset[Part]) -> None:
        show, live = view.show, view.live
        if "show" in changed and show is not None:
            if self._shape(show) != self.shape:
                self.shape = self._shape(show)
                self._build(show, live)
            self.setup.show = show  # its dialogs read the groups and the masters' names
            self._show_cap(show.strobeMaxHz)
        if changed & {"show", "live"} and live is not None:
            self._show_levels(live)
        if changed & {"live", "beats"} and live is not None:
            names = [speed.name for speed in live.speed]
            for tempo in self.tempos:
                index = names.index(tempo.master.name) if tempo.master.name in names else None
                beats = None if index is None or index >= len(view.beats) else view.beats[index]
                tempo.show_beats(beats)

    @staticmethod
    def _shape(show: ShowModel) -> tuple[tuple[MasterView, ...], tuple[ParkedRow, ...]]:
        """What the panels are built from: the masters, and what park holds."""
        return show.masters, parked_rows(show.park, show.fixtures)

    def _build(self, show: ShowModel, live: LiveState | None) -> None:
        self._widgets()
        masters = show.masters
        levels = {} if live is None else {m.name: m.level for m in live.masters}
        panels: list[Widget] = []
        grand = next((m for m in masters if m.kind == "grand"), None)
        if grand is not None:
            self.gm_bar = MasterBar(grand, levels.get(grand.name, 1.0), label="GM")
            buttons = Horizontal(self.blackout, self.gm_full, classes="buttons")
            panels.append(Panel("grand master", self.gm_digits, self.gm_bar, buttons))
        self.tempos = [Tempo(m, full=True) for m in masters if m.kind == "speed"]
        panels += [Panel("speed", tempo, meta=tempo.master.name) for tempo in self.tempos]
        scaled = [m for m in masters if m.kind in ("size", "group")]
        if scaled:
            rows: list[Widget] = []
            for master in scaled:
                bar = MasterBar(master, levels.get(master.name, 0.0))
                self.bars.append(bar)
                rows += [bar, Static(what_it_scales(master), classes="sub")]
            panels.append(Panel("size & group masters", *rows))
        fades = [m for m in masters if m.kind == "fadeTime"]
        if fades:
            fade_bars = [MasterBar(m, levels.get(m.name, 0.0)) for m in fades]
            self.bars += fade_bars
            panels.append(Panel("fade time", *fade_bars, self.fade_now))
        buttons = Horizontal(self.release_all, self.output_off, self.output_on, classes="buttons")
        strobe = Horizontal(self.strobe_cap, self.cap, self.cap_off, classes="buttons")
        panels.append(Panel("panic", self.output_state, buttons, strobe))
        self.parked = ParkedPanel(parked_rows(show.park, show.fixtures), len(show.park))
        panels.append(self.parked)
        self.setup = MasterPanel(show)
        panels.append(self.setup)
        self.grid.remove_children()
        self.grid.mount_all(panels)

    def _show_levels(self, live: LiveState) -> None:
        levels = {master.name: master.level for master in live.masters}
        if self.gm_bar is not None:
            level = levels.get(self.gm_bar.master.name, live.gm)
            self.gm_bar.show(level)
            self.gm_digits.show(str(round(level * 100)), colors.RED if live.blackout else colors.FG)
        self.blackout.show(live.blackout)
        speeds = {speed.name: speed for speed in live.speed}
        for tempo in self.tempos:
            tempo.show(speeds.get(tempo.master.name))
        for bar in self.bars:
            bar.show(levels.get(bar.master.name, 0.0))
        fade = Text("override now ", style=colors.DIM)
        fade.append("off" if live.fadeTime is None else f"{live.fadeTime:.1f} s", style=colors.FG)
        self.fade_now.update(fade)
        state = Text("output ", style=colors.DIM)
        if live.outputEnabled:
            state.append("on", style=colors.GREEN)
        else:
            state.append_text(chip("OUTPUT OFF", True, colors.RED))
        self.output_state.update(state)

    def _show_cap(self, hz: float | None) -> None:
        """The strobe cap, and ``[off]`` grey without one (busk refuses it)."""
        self.cap_hz = hz
        text = Text("strobe cap ", style=colors.DIM)
        text.append("off" if hz is None else f"{hz:g} Hz", style=colors.FG)
        if text != self.strobe_cap.content:
            self.strobe_cap.update(text)
        self.cap_off.change(inert=hz is None)

    def ask_cap(self) -> None:
        """``[cap…]``: a rate dialog, then ``safety strobe 3``; nothing for
        the cap there is."""
        hz = self.cap_hz

        def given(text: str | None) -> None:
            if text is not None and plain_number(text.strip()) != hz:
                self.post_message(RunLine(commands.strobe_cap(text.strip())))

        start = "" if hz is None else commands.exact(hz)
        self.app.push_screen(TextDialog("STROBE CAP", start, check_rate, CAP_NOTE), given)

    def stops(self) -> list[Stop]:
        stops: list[Stop] = []
        if self.gm_bar is not None:
            stops.append(Stop(master_item(self.gm_bar.master), self.gm_bar))
            stops.append(Stop(Item("blackout", line=self.blackout.line.text), self.blackout))
            stops.append(Stop(Item("gm 100", line=self.gm_full.line.text), self.gm_full))
        for tempo in self.tempos:
            stops += tempo.stops()
        stops += [Stop(master_item(bar.master), bar) for bar in self.bars]
        for button in (self.release_all, self.output_off, self.output_on):
            stops.append(Stop(Item(button.label, line=button.line.text), button))
        stops.append(Stop(Item("strobe cap…", action=self.ask_cap), self.cap))
        if not self.cap_off.inert:
            stops.append(Stop(Item("strobe cap off", line=self.cap_off.line.text), self.cap_off))
        return stops + self.parked.stops() + self.setup.stops()
