"""F4 Cues (spec §8.4, plan Phase 3): browse the cue lists, go to a cue,
record, switch sequence and chase, edit a cue's timing in dialogs.

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
cell chooses the row and opens that edit's dialog instead (pending plan
Phase 15, which reverses adaptation 7). The edits under the table act on the
chosen cue: the chosen row (bg 235), else the cue the playback is on, else
the first.

**A cue's edits.** ``[time…]`` and ``[curve…]`` open the forms of
:mod:`busk_tui.widgets.cue_dialogs`; ``[delay…]`` the in and out delays
(``cue 9/3 time 1/3 delay 0/1``, the fade times kept), ``[follow…]`` and
``[wait…]`` the seconds of an automatic GO (``cue 9/3 follow 4``), and
``[rename…]`` the name. Each is filled in with what the cue holds and sends
one line, nothing when it is left as it was. ``[go…]`` puts ``cue 9/3 go``,
a whole line, in the prompt: back to a manual GO.

**Buttons.** ``[GO]`` and ``[BACK]`` (``go N``, ``back N``), ``[record cue
9]`` (the programmer as a new cue at the end), and the mode toggle:
``cuelist 9 sequence``, or ``cuelist 9 chase …`` with the chase settings the
list keeps, else ``bpm x 1`` (busk refuses the spec's ``x1``).

**The list's row.** ``[tracking on|off]``, ``[chase…]`` (the form of
:mod:`busk_tui.widgets.chase_dialog`), ``[rename…]`` and ``[delete]``
(``delete cuelist 9 cascade``, after busk's question). ``[+ list…]``, under
CUELISTS, adds one and shows it.

**The cue's row**, after those: ``[release…]`` (targets and attributes
in a form, ``cue 9/3 release group 1 only pan``), ``[record at…]`` (a free
number and a name; the new cue is chosen), ``[merge]``, ``[replace]`` and
``[remove]`` (``record cue 9/3 merge``) and ``[delete]`` (``delete cue 9/3``).
The last three of those ask the TUI's own question, since busk asks none, and
the delete's says when a playback is on the cue: it leaves it at once. Those
that record are grey while the programmer has nothing to record. On a list
with no cues the row is only ``[record at…]``.

The pane cursor stops on the cues first (Enter goes to one), then the
buttons and the two rows, then the lists (Enter chooses one) and ``[+ list…]``.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Final

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.commands import Line, exact, exact_pair
from busk_tui.formats import numbers_text, selection_text
from busk_tui.model import CueInfo, CueListInfo, LiveState, ShowModel
from busk_tui.nav import Item, Stop
from busk_tui.pages.base import Page, Part, View
from busk_tui.widgets.chase_dialog import ChaseDialog
from busk_tui.widgets.controls import ButtonStrip, RunLine, StripButton, button_label
from busk_tui.widgets.cue_dialogs import (
    CurveDialog,
    TimeDialog,
    check_seconds,
    check_times,
    pair_words,
)
from busk_tui.widgets.cuetable import EDITS, CueListTable, CueTable, cue_cells, list_cells
from busk_tui.widgets.dialogs import (
    FormDialog,
    TextDialog,
    check_cue,
    check_name,
    check_number,
    next_cue,
    next_number,
)
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


def ask(label: str, action: Callable[[], None], color: str = colors.MID) -> StripButton:
    """A button that calls ``action`` (one callable per button: equal buttons
    compare equal)."""
    return StripButton(button_label(label, color), Line(""), action=action)


def grey(label: str) -> StripButton:
    """A button with nothing to do yet: no click, no pane cursor."""
    return StripButton(Text(f"[{label}]", style=colors.BORDER), Line(""), note=True)


def cue_words(cue_list: int, cue: CueInfo) -> str:
    """``cue 9/3 "Pre"``, for a question."""
    return f"cue {cue_list}/{cue.number}" + (f' "{cue.name}"' if cue.name else "")


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
    CuesPage #cuelist-add { margin-top: 1; }
    CuesPage .cue-row { height: auto; }
    CuesPage .cue-row-label { width: auto; max-width: 40%; padding-right: 1; }
    CuesPage .cue-row-strip { width: 1fr; }
    """

    def __init__(self, number: int, title: str) -> None:
        super().__init__(number, title)
        self.lists = CueListTable(Text(NO_LISTS, style=colors.DIM), id="cuelist-table")
        self.meta = Static("", id="cuelist-meta")
        self.cues = CueTable(id="cue-table")
        self.buttons = ButtonStrip(id="cue-buttons")
        self.list_label = Static("", id="cue-list-label", classes="cue-row-label")
        self.list_edits = ButtonStrip(id="cue-list-edits", classes="cue-row-strip")
        self.edit_label = Static("", id="cue-edit-label", classes="cue-row-label")
        self.edits = ButtonStrip(id="cue-edits", classes="cue-row-strip")
        self.list_add = ButtonStrip([ask("+ list…", self.ask_add_list)], id="cuelist-add")
        self.panel = Panel("cuelist", id="cuelist")
        self.browser = Panel("cuelists", self.lists, self.list_add, id="cuelists")
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
                with Horizontal(id="cue-list-row", classes="cue-row"):
                    yield self.list_label
                    yield self.list_edits
                with Horizontal(id="cue-edit-row", classes="cue-row"):
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
        if changed & {"show", "live", "playback", "programmer"}:
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

    def picked(self) -> tuple[int, CueInfo] | None:
        """The chosen list's number and :meth:`chosen_cue`."""
        cue = self.chosen_cue()
        return None if self.list is None or cue is None else (self.list, cue)

    def playing(self, cue: str) -> list[int]:
        """The numbers of the playbacks of the chosen list that are on ``cue``."""
        show, live = self._view.show, self._view.live
        if show is None or live is None or self.list is None:
            return []
        views = [live.playback(number) for number in show.runs(self.list)]
        return [view.number for view in views if view is not None and view.cue == cue]

    def recordable(self) -> bool:
        """Whether the programmer has what ``record cue`` takes."""
        programmer = self._view.programmer
        return programmer is not None and programmer.recordable()

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
        self._draw_list_edits(cue_list)
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

    def _draw_list_edits(self, cue_list: CueListInfo) -> None:
        label = Text("list ", style=colors.DIM)
        label.append(str(cue_list.number), style=colors.CYAN)
        if cue_list.name:
            label.append(f" {cue_list.name}", style=colors.FG)
        self._update(self.list_label, label)
        tracking = commands.cuelist_tracking(cue_list.number, not cue_list.tracking)
        words = f"tracking {'off' if cue_list.tracking else 'on'}"
        self.list_edits.show(
            [
                StripButton(button_label(words, colors.AMBER), tracking),
                ask("chase…", self.ask_chase, colors.AMBER),
                ask("rename…", self.ask_rename_list),
                StripButton(
                    button_label("delete", colors.RED), commands.delete_cuelist(cue_list.number)
                ),
            ]
        )

    def _draw_edits(self, cue_list: int, cue: CueInfo | None) -> None:
        recordable = self.recordable()
        record_at = (
            ask("record at…", self.ask_record_at, colors.MAGENTA)
            if recordable
            else grey("record at…")
        )
        if cue is None:
            self._update(self.edit_label, Text())
            self.edits.show([record_at])
            return
        label = Text("edit ", style=colors.DIM)
        label.append(f"cue {cue_list}/{cue.number}", style=colors.CYAN)
        if cue.name:
            label.append(f" {cue.name}", style=colors.FG)
        self._update(self.edit_label, label)
        go = commands.cue_prefill(cue_list, cue.number, "go")
        merge = commands.record_cue(cue_list, cue.number, "merge")
        writes = (
            [
                StripButton(button_label("merge", colors.MAGENTA), merge),
                ask("replace", self.ask_replace, colors.MAGENTA),
                ask("remove", self.ask_remove, colors.MAGENTA),
            ]
            if recordable
            else [grey("merge"), grey("replace"), grey("remove")]
        )
        self.edits.show(
            [
                ask("time…", self.ask_time),
                ask("delay…", self.ask_delay),
                ask("curve…", self.ask_curve),
                StripButton(button_label("go…", colors.MID), Line(go), prefill=go),
                ask("follow…", self.ask_follow),
                ask("wait…", self.ask_wait),
                ask("rename…", self.ask_rename),
                ask("release…", self.ask_release),
                record_at,
                *writes,
                ask("delete", self.ask_delete, colors.RED),
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
            cell = message.cell if message.cell in EDITS else None
            self.choose_cue(self._shown_cues[message.row].number, go=cell is None)
            if cell is not None:
                self.ask_edit(cell)

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

    # --------------------------------------------------- a cue's controls

    def ask_delete(self) -> None:
        """``[delete]``: ``delete cue 9/3``, after the TUI's question, which
        says when a playback is on the cue: it leaves it at once."""
        found = self.picked()
        if found is None:
            return
        cue_list, cue = found
        question = f"Delete {cue_words(cue_list, cue)}?"
        on = self.playing(cue.number)
        if on:
            who = ", ".join(f"P{number}" for number in on)
            question += (
                f"\n{who} {'is' if len(on) == 1 else 'are'} on it, and will leave it at once."
            )
        self.post_message(RunLine(commands.delete_cue(cue_list, cue.number), ask=question))

    def ask_replace(self) -> None:
        """``[replace]``: ``record cue 9/3 replace``, after the TUI's question."""
        found = self.picked()
        if found is not None:
            cue_list, cue = found
            question = f"Replace what {cue_words(cue_list, cue)} holds with the programmer?"
            line = commands.record_cue(cue_list, cue.number, "replace")
            self.post_message(RunLine(line, ask=question))

    def ask_remove(self) -> None:
        """``[remove]``: ``record cue 9/3 remove``, after the TUI's question."""
        found = self.picked()
        if found is not None:
            cue_list, cue = found
            question = f"Remove the programmer's attributes from {cue_words(cue_list, cue)}?"
            line = commands.record_cue(cue_list, cue.number, "remove")
            self.post_message(RunLine(line, ask=question))

    def ask_record_at(self) -> None:
        """``[record at…]``: ``record cue 9/2.5 "Bridge"``, a number that is
        free and a name; once it has run, the new cue is the one chosen."""
        cue_list = self.list
        if cue_list is None or not self.recordable():
            return
        taken = [cue.number for cue in self._shown_cues]
        check = check_cue(taken)

        def given(values: tuple[str, ...] | None) -> None:
            if values is not None:
                number, name = (value.strip() for value in values)
                line = commands.record_cue(cue_list, number, name=name or None)
                self.post_message(RunLine(line, done=partial(self._recorded, cue_list, number)))

        note = "2.5 goes between 2 and 3\nno name: busk names it Cue <number>"
        fields = (("number", next_cue(taken)), ("name", ""))
        dialog = FormDialog(
            f"RECORD AT · cuelist {cue_list}", fields, lambda values: check(values[0]), note
        )
        self.app.push_screen(dialog, given)

    def _recorded(self, cue_list: int, number: str, ok: bool) -> None:
        if ok and self.list == cue_list:
            self.choose_cue(number, go=False)

    def ask_release(self) -> None:
        """``[release…]``: ``cue 9/3 release group 1 only pan tilt``. The
        targets start at the selection. What only busk can tell (a word it
        does not read) is refused in the log."""
        found, show, programmer = self.picked(), self._view.show, self._view.programmer
        if found is None:
            return
        cue_list, cue = found
        selection = () if programmer is None else programmer.selection
        start = selection_text(selection, () if show is None else show.fixtures)

        def given(values: tuple[str, ...] | None) -> None:
            if values is not None:
                targets, only = values[0].strip(), values[1].split()
                self.post_message(
                    RunLine(commands.cue_release(cue_list, cue.number, targets, only))
                )

        def check(values: tuple[str, ...]) -> str | None:
            return None if values[0].strip() else "the targets: group 1, or 101 thru 104"

        note = "targets: group 1, or 101 thru 104\nonly: attribute names; empty: all of them"
        fields = (("targets", start), ("only", ""))
        dialog = FormDialog(f"RELEASE · cue {cue_list}/{cue.number}", fields, check, note)
        self.app.push_screen(dialog, given)

    # ------------------------------------------- a cue's timing and name

    def ask_edit(self, cell: str) -> None:
        """A click on one of the cue table's :data:`EDITS` cells."""
        asks = {
            "time": self.ask_time,
            "delay": self.ask_delay,
            "curve": self.ask_curve,
            "follow": self.ask_follow,
            "wait": self.ask_wait,
        }
        asks[cell]()

    def _run(self, line: Line | None) -> None:
        if line is not None:
            self.post_message(RunLine(line))

    def ask_time(self) -> None:
        """``[time…]``: ``cue 9/3 time 1/3``, or a family's own, ``cue 9/3
        time position 4``."""
        found = self.picked()
        if found is not None:
            self.app.push_screen(TimeDialog(*found), self._run)

    def ask_curve(self) -> None:
        """``[curve…]``: ``cue 9/3 time 1/3 easeIn``, the fade times kept."""
        found = self.picked()
        if found is not None:
            self.app.push_screen(CurveDialog(*found), self._run)

    def ask_delay(self) -> None:
        """``[delay…]``: ``cue 9/3 time 1/3 delay 0/1``, the fade times kept."""
        found = self.picked()
        if found is None:
            return
        cue_list, cue = found

        def given(values: tuple[str, ...] | None) -> None:
            if values is not None and tuple(map(float, values)) != (cue.delayIn, cue.delayOut):
                times = exact_pair(cue.fadeIn, cue.fadeOut)
                self._run(commands.cue_time(cue_list, cue.number, times, delay=pair_words(*values)))

        fields = (("in", exact(cue.delayIn)), ("out", exact(cue.delayOut)))
        note = "in: before intensity rises and the rest move\nout: before intensity falls"
        title = f"DELAY · cue {cue_list}/{cue.number}"
        self.app.push_screen(FormDialog(title, fields, check_times, note), given)

    def ask_follow(self) -> None:
        """``[follow…]``: ``cue 9/3 follow 4``."""
        self.ask_trigger("follow")

    def ask_wait(self) -> None:
        """``[wait…]``: ``cue 9/3 wait 8``."""
        self.ask_trigger("wait")

    def ask_trigger(self, kind: str) -> None:
        """A GO by itself, ``kind`` seconds after the cue before has finished
        (``follow``) or started (``wait``). The dialog says what the cue
        has while it is another trigger."""
        found = self.picked()
        if found is None:
            return
        cue_list, cue = found
        before = cue.delay if cue.trigger == kind else None

        def given(text: str | None) -> None:
            if text is not None and float(text) != before:
                self._run(commands.cue_trigger(cue_list, cue.number, kind, text.strip()))

        after = "finished" if kind == "follow" else "started"
        note = f"it goes by itself this many seconds\nafter the cue before has {after}"
        if cue.trigger != kind:
            now = "a manual GO" if cue.trigger == "go" else f"{cue.trigger} {exact(cue.delay)}"
            note += f"\nnow: {now}"
        title = f"{kind.upper()} · cue {cue_list}/{cue.number}"
        self.app.push_screen(TextDialog(title, exact(before or 0), check_seconds, note), given)

    def ask_rename(self) -> None:
        """``[rename…]``: ``rename cue 9/3 "Pre"``."""
        found = self.picked()
        if found is None:
            return
        cue_list, cue = found

        def given(text: str | None) -> None:
            if text is not None and text.strip() != cue.name:
                self._run(commands.rename_cue(cue_list, cue.number, text.strip()))

        title = f"RENAME · cue {cue_list}/{cue.number}"
        self.app.push_screen(TextDialog(title, cue.name, check_name(True)), given)

    # -------------------------------------------------- a list's controls

    def ask_add_list(self) -> None:
        """``[+ list…]``: ``cuelist add 30 "Encore"``; once it has run, the
        new list shows."""
        taken = frozenset(cue_list.number for cue_list in self._shown_lists)
        check = check_number(taken, None)

        def given(values: tuple[str, ...] | None) -> None:
            if values is not None:
                number, name = int(values[0].strip()), values[1].strip()
                line = commands.cuelist_add(number, name or None)
                self.post_message(RunLine(line, done=partial(self._added, number)))

        note = "no name: busk names it Cue list <number>"
        if taken:
            note = f"taken: {numbers_text(sorted(taken))}\n{note}"
        fields = (("number", str(next_number(taken))), ("name", ""))
        dialog = FormDialog("NEW CUE LIST", fields, lambda values: check(values[0]), note)
        self.app.push_screen(dialog, given)

    def _added(self, number: int, ok: bool) -> None:
        if ok:
            self.choose_list(number)

    def _chosen_list(self) -> CueListInfo | None:
        show = self._view.show
        return None if show is None or self.list is None else show.cue_list(self.list)

    def ask_rename_list(self) -> None:
        """``[rename…]``: ``rename cuelist 9 "Encore"``."""
        cue_list = self._chosen_list()
        if cue_list is None:
            return

        def given(text: str | None) -> None:
            if text is not None and text.strip() != cue_list.name:
                self.post_message(RunLine(commands.rename_cuelist(cue_list.number, text.strip())))

        title = f"RENAME · cuelist {cue_list.number}"
        self.app.push_screen(TextDialog(title, cue_list.name, check_name(True)), given)

    def ask_chase(self) -> None:
        """``[chase…]``: the form, whose line also makes the list a chase."""
        show, cue_list = self._view.show, self._chosen_list()
        if show is None or cue_list is None:
            return

        def given(line: Line | None) -> None:
            if line is not None:
                self.post_message(RunLine(line))

        speeds = [master.name for master in show.masters if master.kind == "speed"]
        self.app.push_screen(ChaseDialog(cue_list, speeds), given)

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
        if self.panel.display:
            stops += strip_stops(self.buttons)
            stops += strip_stops(self.list_edits)
            stops += strip_stops(self.edits)
        self.lists.spots = [(row, None) for row in range(len(self._shown_lists))]
        for row, cue_list in enumerate(self._shown_lists):
            choose_list = partial(self.choose_list, cue_list.number)
            label = f"cuelist {cue_list.number} {cue_list.name}"
            stops.append(Stop(Item(label, action=choose_list), self.lists, row))
        stops += strip_stops(self.list_add)
        return stops
