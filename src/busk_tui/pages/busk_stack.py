"""F1 layout B, the stack (spec §8.1, plan Phase 1 "Layout B as built").

PLAYBACKS on the left, one row per slot. On the right: TEMPO for the
show's first speed master, MASTERS (the grand master, size and group
masters, and ``[BLACKOUT]``), EFFECTS (the cue effects that run and the
programmer's), and SELECTION (the selection, group buttons, colour chips).
Below 100 columns the right column goes under the playbacks.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from busk_tui import colors
from busk_tui.formats import selection_text
from busk_tui.model import MasterView
from busk_tui.nav import Item, Stop
from busk_tui.pages.base import Part, View
from busk_tui.widgets.controls import ButtonStrip
from busk_tui.widgets.effects import EffectList, effect_lines
from busk_tui.widgets.masters import BlackoutButton, MasterBar, master_item
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.playbacks import PlaybackHeader, PlaybackRow
from busk_tui.widgets.quick import color_chips, group_buttons, strip_stops
from busk_tui.widgets.tempo import Tempo

BAR_MASTERS = ("grand", "size", "group")
"""The masters that have a bar in MASTERS (speed masters have TEMPO, and
fade-time masters are on F7)."""


class StackLayout(Horizontal):
    """Layout B (see the module docs)."""

    DEFAULT_CSS = """
    StackLayout { height: auto; }
    StackLayout > #playbacks { width: 5fr; }
    StackLayout > #busk-side { width: 2fr; min-width: 40; height: auto; }
    StackLayout #playback-rows, StackLayout #master-bars, StackLayout #tempo-body { height: auto; }
    StackLayout #blackout-row { height: 1; align-horizontal: right; }
    StackLayout #selection-text { margin-bottom: 1; }
    StackLayout #group-buttons { margin-bottom: 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.slots: tuple[int | None, ...] | None = None
        self.rows: list[PlaybackRow] = []
        self.tempo: Tempo | None = None
        self.tempo_for: tuple[MasterView | None] | None = (
            None  # the speed master TEMPO was built for
        )
        self.masters: tuple[MasterView, ...] | None = None
        self.bars: list[MasterBar] = []
        self.blackout = BlackoutButton()
        self.effects = EffectList()
        self.selection = Static("", id="selection-text")
        self.groups = ButtonStrip(id="group-buttons")
        self.chips = ButtonStrip(id="color-chips")
        self.rows_box = Vertical(id="playback-rows")
        self.tempo_body = Vertical(id="tempo-body")
        self.tempo_panel = Panel("tempo", self.tempo_body, id="tempo-panel")
        self.bars_box = Vertical(id="master-bars")

    def compose(self) -> ComposeResult:
        with Panel("playbacks", id="playbacks"):
            yield PlaybackHeader()
            yield self.rows_box
        with Vertical(id="busk-side"):
            yield self.tempo_panel
            with Panel("masters"):
                yield self.bars_box
                with Horizontal(id="blackout-row"):
                    yield self.blackout
            with Panel("effects"):
                yield self.effects
            with Panel("selection"):
                yield self.selection
                yield self.groups
                yield self.chips

    def update_view(
        self, view: View, changed: frozenset[Part], slots: tuple[int | None, ...]
    ) -> None:
        show, live = view.show, view.live
        if slots != self.slots:
            self.slots = slots
            self.rows = [PlaybackRow(index + 1, number) for index, number in enumerate(slots)]
            self.rows_box.remove_children()
            self.rows_box.mount_all(self.rows)
        if changed & {"show", "live", "playback"}:
            for row in self.rows:
                if row.number is None:
                    continue
                info = None if show is None else show.playback(row.number)
                cue_list = None if show is None or info is None else show.cue_list(info.cueList)
                playback = None if live is None else live.playback(row.number)
                row.show(playback, info, cue_list, row.number == view.playback, view.mode)
        if "show" in changed:
            self._build_tempo(view)
            self._build_masters(view)
        if changed & {"show", "live"} and self.tempo is not None:
            speeds = () if live is None else live.speed
            self.tempo.show(next((s for s in speeds if s.name == self.tempo.master.name), None))
        if changed & {"live", "beats"} and self.tempo is not None and live is not None:
            index = next(
                (i for i, s in enumerate(live.speed) if s.name == self.tempo.master.name), None
            )
            self.tempo.show_beats(
                None if index is None or index >= len(view.beats) else view.beats[index]
            )
        if changed & {"show", "live"} and live is not None:
            levels = {master.name: master.level for master in live.masters}
            for bar in self.bars:
                bar.show(levels.get(bar.master.name, 0.0))
            self.blackout.show(live.blackout)
        if changed & {"show", "programmer", "effects"}:
            self.effects.show(effect_lines(show, view.programmer, view.effects), view.mode)
        if changed & {"show", "programmer"}:
            self._show_selection(view)

    def _build_tempo(self, view: View) -> None:
        show = view.show
        first = None if show is None else next((m for m in show.masters if m.kind == "speed"), None)
        if self.tempo_for == (first,):
            return
        self.tempo_for = (first,)
        self.tempo_body.remove_children()
        self.tempo = None if first is None else Tempo(first)
        self.tempo_panel.set_title("tempo", None if first is None else first.name)
        if self.tempo is None:
            no_speed = Text('no speed master · master add speed "<name>"', style=colors.DIM)
            self.tempo_body.mount(Static(no_speed))
        else:
            self.tempo_body.mount(self.tempo)

    def _build_masters(self, view: View) -> None:
        show = view.show
        masters = () if show is None else tuple(m for m in show.masters if m.kind in BAR_MASTERS)
        if masters == self.masters:
            return
        self.masters = masters
        levels = {} if view.live is None else {m.name: m.level for m in view.live.masters}
        self.bars = [
            MasterBar(
                master, levels.get(master.name, 0.0), label="GM" if master.kind == "grand" else None
            )
            for master in masters
        ]
        self.bars_box.remove_children()
        self.bars_box.mount_all(self.bars)

    def _show_selection(self, view: View) -> None:
        show, programmer = view.show, view.programmer
        selection = () if programmer is None else programmer.selection
        text = Text()
        compressed = "" if show is None else selection_text(selection, show.fixtures)
        text.append(
            compressed or "nothing selected", style=colors.CYAN if compressed else colors.DIM
        )
        if selection:
            text.append(f" ({len(selection)})", style=colors.DIM)
        self.selection.update(text)
        self.groups.show(group_buttons(() if show is None else show.groups))
        self.chips.show(color_chips(() if show is None else show.presets, view.mode))

    def stops(self) -> list[Stop]:
        stops: list[Stop] = []
        for row in self.rows:
            for button in row.buttons:
                stops.append(Stop(Item(button.line.text, line=button.line.text), button))
        if self.tempo is not None:
            stops += self.tempo.stops()
        stops += [Stop(master_item(bar.master), bar) for bar in self.bars]
        stops.append(Stop(Item("blackout", line=self.blackout.line.text), self.blackout))
        stops += self.effects.stops()
        stops += strip_stops(self.groups)
        stops += strip_stops(self.chips)
        return stops
