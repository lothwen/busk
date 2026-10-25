"""F4 Cues (spec §8.4, plan Phase 3): browse the cue lists, go to a cue,
record, switch sequence and chase, edit a cue's timing at the prompt.

CUELISTS on the left lists every cue list; the panel on the right shows the
chosen one: a meta line (its mode, the playbacks that run it with their
level, the groups and fixtures its cues set), its cues
(:mod:`busk_tui.widgets.cuetable`), its buttons and the edits of one cue.

**Which list.** The list of the selected playback (Space, ``[ ]``, ``P9`` in
the prompt): ← → on an empty prompt step through the lists of the page's
playbacks. A click on a list chooses it, and selects the playback that runs
it, if one does. **Its playback** is the selected one when that runs it,
else the first that does; GO, BACK and going to a cue act on it.

**A cue row.** A click goes to that cue (``goto 9 3``; busk's ``cue L/C go``
would set its trigger) and chooses the row; a list no playback runs has no
go-to, its rows only choose. A click on a time, delay, curve, follow or wait
cell puts that edit in the prompt instead (spec open question 4, adaptation
7). The edits under the table pre-fill the chosen cue's lines: the chosen
row (bg 235), else the cue the playback is on, else the first.

**Buttons.** ``[GO]`` and ``[BACK]`` (``go N``, ``back N``), ``[record cue
9]`` (the programmer as a new cue at the end), and the mode toggle:
``cuelist 9 sequence``, or ``cuelist 9 chase …`` with the chase settings the
list keeps, else ``bpm x 1`` (busk refuses the spec's ``x1``).

The pane cursor stops on the cues first (Enter goes to one), then the
buttons and the edits, then the lists (Enter chooses one).
"""

from __future__ import annotations

from functools import partial
from typing import Final

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.commands import Line
from busk_tui.formats import selection_text
from busk_tui.model import CueInfo, CueListInfo, LiveState, ShowModel
from busk_tui.nav import Item, Stop
from busk_tui.pages.base import Page, Part, View
from busk_tui.widgets.controls import ButtonStrip, FillPrompt, RunLine, StripButton, button_label
from busk_tui.widgets.cuetable import CueListTable, CueTable, cue_cells, edit_prefill, list_cells
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.playbacks import LEVEL_COLORS, PlaybackRow
from busk_tui.widgets.quick import strip_stops
from busk_tui.widgets.rows import RowTable

NARROW: Final = 100
"""Below this many columns the panels go one under the other (spec §3)."""

NO_LISTS: Final = "no cue lists · select fixtures, set a look, then record cue 1"
NO_CUES: Final = "no cues · record cue {} records the programmer as one"


def meta_text(cue_list: CueListInfo, show: ShowModel, live: LiveState | None) -> Text:
    """``mode sequence · tracking   playback P9 @ 80%   groups Heads, Washes``."""
    text = Text("mode ", style=colors.DIM)
    if cue_list.mode == "chase":
        text.append(f"chase {cue_list.chase or ''}".rstrip(), style=colors.AMBER)
        if cue_list.crossfade:
            text.append(f" crossfade {cue_list.crossfade:g}", style=colors.AMBER)
    else:
        text.append("sequence", style=colors.AMBER)
    if cue_list.tracking:
        text.append(" · tracking", style=colors.AMBER)
    runs = show.runs(cue_list.number)
    text.append("   ")
    if not runs:
        text.append("no playback: assign the list to a playback first", style=colors.DIM)
    else:
        text.append("playback ", style=colors.DIM)
        for index, number in enumerate(runs):
            view = None if live is None else live.playback(number)
            level = 0.0 if view is None else view.level
            state = "idle" if view is None else view.state
            if index:
                text.append(", ", style=colors.DIM)
            text.append(
                f"P{number} @ {round(level * 100)}%", style=LEVEL_COLORS.get(state, colors.DIM)
            )
    groups: list[str] = []
    elements: set[tuple[int, int]] = set()
    for cue in cue_list.cues:
        for targets in [value.targets for value in cue.values] + [e.targets for e in cue.effects]:
            if targets.group is not None and targets.group.name not in groups:
                groups.append(targets.group.name)
            elements.update(targets.elements)
    if groups:
        text.append("   groups ", style=colors.DIM)
        text.append(", ".join(groups), style=colors.CYAN)
    if elements:
        text.append("   fixtures ", style=colors.DIM)
        text.append(selection_text(sorted(elements), show.fixtures), style=colors.CYAN)
    return text


def mode_line(cue_list: CueListInfo) -> Line:
    """The toggle: back to a sequence, or a chase with the settings it keeps."""
    if cue_list.mode == "chase":
        return commands.cuelist_sequence(cue_list.number)
    return commands.cuelist_chase(cue_list.number, cue_list.chase, cue_list.crossfade)


class CuesPage(Page):
    """F4 (see the module docs)."""

    DEFAULT_CSS = """
    CuesPage #cues-row { height: auto; }
    CuesPage #cuelists { width: 38; }
    CuesPage #cuelist { width: 1fr; }
    CuesPage #cues-row.stacked { layout: vertical; }
    CuesPage #cues-row.stacked > Panel { width: 100%; }
    CuesPage #cuelist-meta { margin-bottom: 1; }
    CuesPage #cue-buttons { margin-top: 1; }
    CuesPage #cue-edit-row { height: auto; }
    CuesPage #cue-edit-label { width: auto; padding-right: 1; }
    CuesPage #cue-edits { width: 1fr; }
    """

    def __init__(self, number: int, title: str) -> None:
        super().__init__(number, title)
        self.lists = CueListTable(Text(NO_LISTS, style=colors.DIM), id="cuelist-table")
        self.meta = Static("", id="cuelist-meta")
        self.cues = CueTable(id="cue-table")
        self.buttons = ButtonStrip(id="cue-buttons")
        self.edit_label = Static("", id="cue-edit-label")
        self.edits = ButtonStrip(id="cue-edits")
        self.panel = Panel("cuelist", id="cuelist")
        self.browser = Panel("cuelists", self.lists, id="cuelists")
        self.list: int | None = None  # the chosen list's number
        self.cue: str | None = None  # the chosen cue's number, until the list changes
        self._followed: int | None = None  # the selected playback the list last followed
        self._view = View()
        self._shown_lists: tuple[CueListInfo, ...] = ()
        self._shown_cues: tuple[CueInfo, ...] = ()

    def compose(self) -> ComposeResult:
        with Horizontal(id="cues-row"):
            yield self.browser
            with self.panel:
                yield self.meta
                yield self.cues
                yield self.buttons
                with Horizontal(id="cue-edit-row"):
                    yield self.edit_label
                    yield self.edits

    def on_resize(self, event: events.Resize) -> None:
        """Below :data:`NARROW` the chosen list goes on top, the lists under it."""
        row = self.query_one("#cues-row")
        stacked = event.size.width < NARROW
        if stacked != row.has_class("stacked"):
            row.set_class(stacked, "stacked")
            if stacked:
                row.move_child(self.panel, before=self.browser)
            else:
                row.move_child(self.browser, before=self.panel)

    # ------------------------------------------------------------ state

    def update_view(self, view: View, changed: frozenset[Part]) -> None:
        self._view = view
        if changed & {"show", "playback"}:
            self._follow()
        if changed & {"show", "live", "playback"}:
            self._draw()

    def _follow(self) -> None:
        """Choose the selected playback's list when the selection changes;
        a list the show no longer has gives way to the first."""
        view, show = self._view, self._view.show
        if show is None:
            return
        if view.playback != self._followed:
            self._followed = view.playback
            info = show.playback(view.playback)
            if info is not None and show.cue_list(info.cueList) is not None:
                self._choose(info.cueList)
        if self.list is None or show.cue_list(self.list) is None:
            self._choose(show.cueLists[0].number if show.cueLists else None)

    def _choose(self, number: int | None) -> None:
        if number != self.list:
            self.list, self.cue = number, None

    def runner(self) -> int | None:
        """The chosen list's playback: the selected one if it runs the list,
        else the first that does."""
        show = self._view.show
        if show is None or self.list is None:
            return None
        runs = show.runs(self.list)
        return self._view.playback if self._view.playback in runs else (runs[0] if runs else None)

    def current(self) -> str | None:
        """The cue the list's playback is on."""
        live, runner = self._view.live, self.runner()
        playback = None if live is None or runner is None else live.playback(runner)
        return None if playback is None else playback.cue

    def chosen_cue(self) -> CueInfo | None:
        """The chosen row's cue, else the current one, else the first."""
        cues = self._shown_cues
        for number in (self.cue, self.current()):
            found = next((cue for cue in cues if cue.number == number), None)
            if found is not None:
                return found
        return cues[0] if cues else None

    # ------------------------------------------------------------- draw

    def _draw(self) -> None:
        view, show = self._view, self._view.show
        lists = () if show is None else show.cueLists
        self._shown_lists = lists
        chosen = next((i for i, c in enumerate(lists) if c.number == self.list), None)
        self.lists.show(
            [list_cells(c, () if show is None else show.runs(c.number)) for c in lists], chosen
        )
        cue_list = None if show is None or self.list is None else show.cue_list(self.list)
        self.panel.display = cue_list is not None
        if show is None or cue_list is None:
            self._shown_cues = ()
            return
        self.panel.set_title(f"cuelist {cue_list.number}", cue_list.name)
        self._update(self.meta, meta_text(cue_list, show, view.live))
        self._shown_cues = cue_list.cues
        current = self.current()
        rows = [cue_cells(cue_list, cue, cue.number == current, view.mode) for cue in cue_list.cues]
        picked = self.chosen_cue()
        empty = Text(NO_CUES.format(cue_list.number), style=colors.DIM)
        self.cues.show(rows, None if picked is None else cue_list.cues.index(picked), empty)
        self.buttons.show(self._buttons(cue_list))
        self._draw_edits(cue_list.number, picked)

    def _buttons(self, cue_list: CueListInfo) -> list[StripButton]:
        runner = self.runner()
        buttons = []
        if runner is not None:
            buttons += [
                StripButton(button_label("GO", colors.GREEN), commands.go(runner)),
                StripButton(button_label("BACK", colors.MID), commands.back(runner)),
            ]
        record = commands.record_cue(cue_list.number)
        toggle = mode_line(cue_list)
        buttons += [
            StripButton(button_label(record.text, colors.MAGENTA), record),
            StripButton(button_label(toggle.text, colors.AMBER), toggle),
        ]
        return buttons

    def _draw_edits(self, cue_list: int, cue: CueInfo | None) -> None:
        if cue is None:
            self._update(self.edit_label, Text())
            self.edits.show([])
            return
        label = Text("edit ", style=colors.DIM)
        label.append(f"cue {cue_list}/{cue.number}", style=colors.CYAN)
        if cue.name:
            label.append(f" {cue.name}", style=colors.FG)
        self._update(self.edit_label, label)
        prefills = [
            ("time", edit_prefill(cue_list, cue, "time")),
            ("delay", edit_prefill(cue_list, cue, "delay")),
            ("curve", edit_prefill(cue_list, cue, "curve")),
            ("go", commands.cue_prefill(cue_list, cue.number, "go")),
            ("follow", edit_prefill(cue_list, cue, "follow")),
            ("wait", edit_prefill(cue_list, cue, "wait")),
            ("rename", commands.rename_cue_prefill(cue_list, cue.number)),
        ]
        self.edits.show(
            [
                StripButton(button_label(f"{name}…", colors.MID), Line(text), prefill=text)
                for name, text in prefills
                if text is not None
            ]
        )

    @staticmethod
    def _update(widget: Static, text: Text) -> None:
        if text != widget.content:
            widget.update(text)

    # ----------------------------------------------------------- clicks

    def on_row_table_clicked(self, message: RowTable.Clicked) -> None:
        message.stop()
        if message.table is self.lists:
            if message.row < len(self._shown_lists):
                self.choose_list(self._shown_lists[message.row].number)
        elif message.table is self.cues and message.row < len(self._shown_cues):
            cue = self._shown_cues[message.row]
            prefill = (
                None
                if self.list is None or message.cell is None
                else edit_prefill(self.list, cue, message.cell)
            )
            self.choose_cue(cue.number, go=prefill is None)
            if prefill is not None:
                self.post_message(FillPrompt(prefill))

    def choose_list(self, number: int) -> None:
        """A list chosen by a click or the pane cursor; the playback that
        runs it becomes the selected one."""
        self._choose(number)
        runner = self.runner()
        if runner is not None and runner != self._view.playback:
            self._followed = runner
            self.post_message(PlaybackRow.Chosen(runner))
        self._draw()

    def choose_cue(self, number: str, *, go: bool) -> None:
        """A cue row chosen; with ``go``, the list's playback goes to it."""
        self.cue = number
        runner = self.runner()
        if go and runner is not None:
            self.post_message(RunLine(commands.goto(runner, number)))
        self._draw()

    # ----------------------------------------------------- pane cursor

    def stops(self) -> list[Stop]:
        stops: list[Stop] = []
        runner = self.runner()
        cue_spots: list[tuple[int, str | None]] = []
        if self.list is not None:
            for row, cue in enumerate(self._shown_cues):
                cue_spots.append((row, None))
                line = None if runner is None else commands.goto(runner, cue.number).text
                label = f"cue {self.list}/{cue.number} {cue.name}".rstrip()
                choose = partial(self.choose_cue, cue.number, go=False)  # the line goes
                stops.append(Stop(Item(label, line=line, action=choose), self.cues, row))
        self.cues.spots = cue_spots
        stops += strip_stops(self.buttons)
        stops += strip_stops(self.edits)
        self.lists.spots = [(row, None) for row in range(len(self._shown_lists))]
        for row, cue_list in enumerate(self._shown_lists):
            choose_list = partial(self.choose_list, cue_list.number)
            label = f"cuelist {cue_list.number} {cue_list.name}"
            stops.append(Stop(Item(label, action=choose_list), self.lists, row))
        return stops
