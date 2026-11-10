"""F3's GROUPS panel (``docs/plans/tui-pending-plan.md`` Phase 12): the show's
groups, in F3's edit mode, under the rig's table.

* A row per group: its number, name and members (``101 thru 102, 301.2``). A
  click chooses it and sends nothing: the selection stays, for the buttons
  below, so a group can be chosen before or after the fixtures are.
* ``[record…]``: the selection as a new group, a number that is free and a
  name (``record group 5 "Floor"``); the new group is the one chosen. Grey
  while nothing is selected.
* The chosen group: ``[rename…]`` and ``[number…]``, each a dialog and then
  one line (``rename group 2 "…"``, ``group 2 number 7``), and ``[delete]``:
  ``delete group 2 cascade``, after busk's question, which names what it
  leaves.
* With the selection: ``[merge]`` adds the selected elements the group lacks,
  ``[replace]`` makes the selection its members, ``[remove]`` takes the
  selected ones out (``record group 2 merge``). The last two ask first. Each
  is grey while it would change nothing, since busk spends an undo step on
  that.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import partial
from typing import Final, Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.formats import numbers_text, selection_text
from busk_tui.model import FixtureInfo, GroupInfo, ShowModel
from busk_tui.nav import Item, Stop
from busk_tui.widgets.controls import ActionButton, RunLine
from busk_tui.widgets.dialogs import (
    FormDialog,
    TextDialog,
    check_name,
    check_number,
    next_number,
)
from busk_tui.widgets.options import LIT
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.rows import Cells, Column, RowTable, cell

type Write = Literal["merge", "replace", "remove"]

WRITES: Final[tuple[Write, ...]] = ("merge", "replace", "remove")

NO_GROUPS: Final = "no groups · select fixtures, then [record…]"

type Element = tuple[int, int]
"""A fixture number and an element, counted from 1."""


class GroupTable(RowTable):
    COLUMNS = (
        Column("number", "#", 4, right=True),
        Column("name", "name", 16),
        Column("members", "members", 16, flex=True),
    )


def group_cells(group: GroupInfo, chosen: bool, fixtures: Sequence[FixtureInfo]) -> Cells:
    """A group's row; the chosen one's number lit."""
    members = selection_text(group.members, fixtures)
    return {
        "number": cell(str(group.number), LIT if chosen else colors.MID),
        "name": cell(group.name, colors.FG),
        "members": cell(members, colors.MID) if members else cell("—", colors.BORDER),
    }


def changes(how: Write, members: Sequence[Element], selection: Sequence[Element]) -> bool:
    """Whether ``record group N <how>`` would change the members: ``merge``
    while the selection holds an element they lack, ``replace`` while it is
    not them in their order, ``remove`` while it holds one of them."""
    if not selection:
        return False
    if how == "replace":
        return tuple(selection) != tuple(members)
    have = set(members)
    if how == "merge":
        return any(element not in have for element in selection)
    return any(element in have for element in selection)


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


class GroupPanel(Panel):
    """The GROUPS panel (see the module docs). The page shows it in edit mode
    and redraws it with :meth:`show_view`."""

    DEFAULT_CSS = """
    GroupPanel { margin-top: 1; }
    GroupPanel .gp-row { height: auto; }
    GroupPanel .gp-row > CommandButton { margin-right: 1; }
    GroupPanel .gp-label { width: auto; max-width: 50%; padding-right: 1; }
    GroupPanel .gp-text { width: 1fr; }
    GroupPanel #groups-table { margin-bottom: 1; }
    """

    def __init__(self) -> None:
        super().__init__("groups", id="group-panel")
        self.show: ShowModel | None = None
        self.selection: tuple[Element, ...] = ()
        self.chosen: int | None = None  # the chosen group's number
        self.shown: tuple[GroupInfo, ...] = ()  # by number
        self.count = Static("", classes="gp-text")
        self.record = ActionButton("record…", self.ask_record, "record")
        self.table = GroupTable(Text(NO_GROUPS, style=colors.DIM), id="groups-table")
        self.label = Static("", classes="gp-label")
        self.rename = ActionButton("rename…", self.ask_name)
        self.renumber = ActionButton("number…", self.ask_number)
        self.delete = ActionButton("delete", self.ask_delete, "danger")
        self.choice = Horizontal(
            self.label, self.rename, self.renumber, self.delete, classes="gp-row"
        )
        self.with_words = Static("", classes="gp-label")
        self.writes = {how: ActionButton(how, partial(self.write, how), "record") for how in WRITES}
        self.with_row = Horizontal(self.with_words, *self.writes.values(), classes="gp-row")

    def compose(self) -> ComposeResult:
        yield Horizontal(self.count, self.record, classes="gp-row")
        yield self.table
        yield self.choice
        yield self.with_row

    # ------------------------------------------------------------ drawing

    def show_view(self, show: ShowModel | None, selection: tuple[Element, ...]) -> None:
        """Redraw with the show and the selection as they are now. A chosen
        group a new show does not have is chosen no more (only then: a
        record's or a renumber's done may come before its show)."""
        new = show is not self.show
        self.show, self.selection = show, selection
        self.shown = tuple(sorted(() if show is None else show.groups, key=lambda g: g.number))
        if new and self.group() is None:
            self.chosen = None
        self.draw()

    def group(self) -> GroupInfo | None:
        """The chosen group; ``None`` for one the show no longer has."""
        return next((group for group in self.shown if group.number == self.chosen), None)

    def fixtures(self) -> tuple[FixtureInfo, ...]:
        return () if self.show is None else self.show.fixtures

    def draw(self) -> None:
        fixtures = self.fixtures()
        count = Text(plural(len(self.shown), "group"), style=colors.DIM)
        count.append(" · click chooses, and keeps the selection", style=colors.DIM)
        if count != self.count.content:
            self.count.update(count)
        self.record.change(inert=not self.selection)
        rows = [group_cells(g, g.number == self.chosen, fixtures) for g in self.shown]
        index = next((k for k, g in enumerate(self.shown) if g.number == self.chosen), None)
        self.table.show(rows, chosen=index)
        group = self.group()
        self.choice.display = self.with_row.display = group is not None
        if group is None:
            return
        label = Text("group ", style=colors.DIM)
        label.append(f"{group.number} {group.name}", style=colors.FG)
        _put(self.label, label)
        words = Text("selection ", style=colors.DIM)
        selected = selection_text(self.selection, fixtures)
        words.append(selected or "nothing", style=colors.FG if selected else colors.DIM)
        _put(self.with_words, words)
        for how, button in self.writes.items():
            button.change(inert=not changes(how, group.members, self.selection))

    # ------------------------------------------------------------ actions

    def on_row_table_clicked(self, message: RowTable.Clicked) -> None:
        message.stop()  # not the page's: that is the rig's table
        if message.row < len(self.shown):
            self.choose(self.shown[message.row].number)

    def choose(self, number: int | None) -> None:
        """The group the buttons act on. Sends nothing."""
        self.chosen = number
        self.draw()

    def _chosen_after(self, number: int, ok: bool) -> None:
        if ok:
            self.choose(number)

    def ask_record(self) -> None:
        """``[record…]``: ``record group 5 "Floor"``, a number that is free and
        a name; the new group is the one chosen."""
        if not self.selection:
            return
        taken = frozenset(group.number for group in self.shown)
        check = check_number(taken, None)

        def given(values: tuple[str, ...] | None) -> None:
            if values is not None:
                number, name = int(values[0].strip()), values[1].strip()
                line = commands.record_group(number, name=name or None)
                self.post_message(RunLine(line, done=partial(self._chosen_after, number)))

        selected = selection_text(self.selection, self.fixtures())
        note = f"members: {selected}\nno name: busk names it Group <number>"
        if taken:
            note = f"taken: {numbers_text(sorted(taken))}\n{note}"
        fields = (("number", str(next_number(taken))), ("name", ""))
        dialog = FormDialog("RECORD GROUP", fields, lambda values: check(values[0]), note)
        self.app.push_screen(dialog, given)

    def ask_name(self) -> None:
        """``[rename…]``: ``rename group 2 "Floor washes"``."""
        group = self.group()
        if group is None:
            return

        def given(text: str | None) -> None:
            if text is not None and self.chosen == group.number and text.strip() != group.name:
                self.post_message(RunLine(commands.rename_group(group.number, text.strip())))

        title = f"RENAME · group {group.number}"
        self.app.push_screen(TextDialog(title, group.name, check_name(True)), given)

    def ask_number(self) -> None:
        """``[number…]``: ``group 2 number 7``. The choice follows it."""
        group = self.group()
        if group is None:
            return
        taken = frozenset(other.number for other in self.shown)
        others = sorted(taken - {group.number})

        def given(text: str | None) -> None:
            if text is None or self.chosen != group.number:
                return
            number = int(text.strip())
            if number != group.number:
                line = commands.renumber_group(group.number, number)
                self.post_message(RunLine(line, done=partial(self._chosen_after, number)))

        title = f"NUMBER · group {group.number}"
        note = f"taken: {numbers_text(others)}" if others else ""
        check = check_number(taken, group.number)
        self.app.push_screen(TextDialog(title, str(group.number), check, note), given)

    def ask_delete(self) -> None:
        """``[delete]``: ``delete group 2 cascade``, after busk's question.
        Once it has gone nothing is chosen."""
        group = self.group()
        if group is None:
            return

        def deleted(ok: bool) -> None:
            if ok and self.chosen == group.number:
                self.choose(None)

        self.post_message(RunLine(commands.delete_group(group.number), done=deleted))

    def write(self, how: Write) -> None:
        """``[merge]``, ``[replace]`` or ``[remove]``: ``record group 2 merge``.
        The last two ask first; none sends what would change nothing."""
        group = self.group()
        if group is None or not changes(how, group.members, self.selection):
            return
        words = f'group {group.number} "{group.name}"'
        question = None
        if how == "replace":
            question = f"Replace the members of {words} with the selection?"
        elif how == "remove":
            chosen = set(self.selection)
            left = sum(1 for member in group.members if member not in chosen)
            question = f"Take the selection out of {words}?\n" + (
                f"It keeps {left} of its {len(group.members)} members."
                if left
                else "It stays, with no members."
            )
        self.post_message(RunLine(commands.record_group(group.number, how), ask=question))

    # -------------------------------------------------------- pane cursor

    def stops(self) -> list[Stop]:
        """``[record…]``, each row, then the chosen group's controls (an inert
        one is none)."""
        stops: list[Stop] = []
        if not self.record.inert:
            stops.append(Stop(Item("record group…", action=self.ask_record), self.record))
        self.table.spots = [(row, None) for row in range(len(self.shown))]
        for row, group in enumerate(self.shown):
            item = Item(
                f"group {group.number} {group.name}", action=partial(self.choose, group.number)
            )
            stops.append(Stop(item, self.table, row))
        if self.group() is not None:
            for button in (self.rename, self.renumber, self.delete, *self.writes.values()):
                if not button.inert:
                    label = f"group {button.label}"
                    stops.append(Stop(Item(label, action=button.action), button))
        return stops


def _put(widget: Static, text: Text) -> None:
    """``text`` in ``widget``, if it is not there already (no layout for nothing)."""
    if widget.content != text:
        widget.update(text)
