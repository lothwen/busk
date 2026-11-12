"""F7's MASTERS panel (``docs/plans/tui-pending-plan.md`` Phase 35): the show's
masters made, renamed and deleted.

* A row per master but the grand master, in show order: its name, in its
  bar's colour, and what it is (``speed``, ``size``, ``group · 2 Washes``,
  ``fade time``), with ``[rename…]``, a name dialog and then ``rename master
  "FX" "Size"``, and ``[delete]``: ``delete master "FX" cascade``. busk asks
  first, naming the bindings it takes, and refuses a master that an effect or
  a chase uses, which the log says.
* ``[+ master…]``: :class:`MasterDialog`, a form for the kind, the name, and
  the group of a group master or the tempo of a speed one. It sends ``master
  add group "Washes" group 2``.

The grand master has no row: busk neither renames nor deletes it.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from functools import partial
from typing import ClassVar, Final

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, Static

from busk_tui import colors, commands
from busk_tui.commands import Line
from busk_tui.model import GroupInfo, MasterView, ShowModel
from busk_tui.nav import Item, Stop
from busk_tui.widgets.chase_dialog import plain_number
from busk_tui.widgets.controls import ActionButton, RunLine
from busk_tui.widgets.dialogs import TextDialog, dialog_css
from busk_tui.widgets.masters import MASTER_COLORS
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.route_dialog import PickRow, row

KINDS: Final = {"speed": "speed", "size": "size", "group": "group", "fadetime": "fade time"}
"""Each kind as ``master add`` takes it, and its chip."""

BPM: Final = "120"
"""Where a speed master's tempo starts: busk's own default."""

MAX_BPM: Final = 999.0
"""The fastest tempo busk takes (``busk.model.master.MAX_BPM``)."""

NO_MASTERS: Final = "no masters but the grand master · [+ master…]"


def kind_text(master: MasterView) -> str:
    """What a master is: ``speed``, ``group · 2 Washes``, ``fade time``."""
    if master.kind == "group" and master.group is not None:
        return f"group · {master.group.number} {master.group.name}"
    return "fade time" if master.kind == "fadeTime" else master.kind


def master_text(master: MasterView) -> Text:
    """A row's words: the name, in its bar's colour, and what it is."""
    text = Text(master.name, style=MASTER_COLORS.get(master.kind, colors.FG))
    text.append(f" {kind_text(master)}", style=colors.DIM)
    return text


def check_master_name(taken: Collection[str], own: str | None) -> Callable[[str], str | None]:
    """A master name's check: not empty, and not a name another master has,
    in any case, as busk refuses it (``own``, the master's own, may change)."""
    folded = {name.casefold() for name in taken if name != own}

    def check(text: str) -> str | None:
        name = text.strip()
        if not name:
            return "a name cannot be empty"
        if name.casefold() in folded:
            return f"a master named {commands.quoted(name)} exists"
        return None

    return check


def _number(group: GroupInfo) -> int:
    return group.number


def check_bpm(text: str) -> str | None:
    """A speed master's tempo: above 0, up to busk's fastest."""
    value = plain_number(text.strip())
    if value is not None and 0 < value <= MAX_BPM:
        return None
    return f"a tempo above 0, up to {MAX_BPM:g} BPM"


class MasterDialog(ModalScreen[Line | None]):
    """``[+ master…]``'s form (see the module docs): closes with a ``master
    add`` line, or ``None``. The kind's chips (no group without a group),
    the name, then the group's chips or the tempo, by the kind. Tab moves
    between them, ← → move the chips; Enter, anywhere, runs the checks, and
    what is wrong shows. Esc cancels."""

    DEFAULT_CSS = (
        dialog_css("MasterDialog")
        + f"""
    MasterDialog > Vertical {{ width: 60; }}
    MasterDialog Horizontal {{ width: 100%; height: auto; margin-top: 0; }}
    MasterDialog .label {{ color: {colors.MID}; width: 11; }}
    MasterDialog Input {{ width: 1fr; }}
    MasterDialog PickRow {{ width: 1fr; }}
    MasterDialog PickRow:focus {{ background: {colors.SEL}; }}
    MasterDialog .error {{ color: {colors.RED}; width: 100%; height: auto; }}
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "ok", "OK", show=False),
    ]

    def __init__(self, masters: Sequence[MasterView], groups: Sequence[GroupInfo]) -> None:
        super().__init__()
        kinds = {key: word for key, word in KINDS.items() if groups or key != "group"}
        self.kind = PickRow(kinds)
        self.name_field = Input("", placeholder="a name, such as Washes", compact=True)
        chips = {str(g.number): f"{g.number} {g.name}" for g in sorted(groups, key=_number)}
        self.group = PickRow(chips) if chips else None
        self.bpm = Input(BPM, compact=True)
        self.check_name = check_master_name([master.name for master in masters], None)
        self.error = Static("", classes="error")
        self.group_row = None if self.group is None else row("group", self.group)
        self.bpm_row = row("tempo", self.bpm)

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = "NEW MASTER"
            yield row("kind", self.kind)
            yield row("name", self.name_field)
            if self.group_row is not None:
                yield self.group_row
            yield self.bpm_row
            yield self.error
            yield Static("Tab: next · ← →: chips · Enter: OK · Esc: cancel", classes="note")

    def on_mount(self) -> None:
        self._draw()
        self.name_field.focus()

    def _draw(self) -> None:
        """The fields of the kind chosen."""
        if self.group_row is not None:
            self.group_row.display = self.kind.chosen == "group"
        self.bpm_row.display = self.kind.chosen == "speed"

    def on_pick_row_picked(self, message: PickRow.Picked) -> None:
        message.stop()
        self.error.update("")  # it may be of a field that just went
        self._draw()

    def problem(self) -> str | None:
        """What is wrong with the fields shown, first to last."""
        found = self.check_name(self.name_field.value)
        if found is None and self.kind.chosen == "speed":
            return check_bpm(self.bpm.value)
        return found

    def line(self) -> Line:
        """The line the fields shown make, once they pass."""
        kind, name = self.kind.chosen, self.name_field.value.strip()
        if kind == "group" and self.group is not None:
            return commands.master_add(kind, name, group=int(self.group.chosen))
        if kind == "speed":
            return commands.master_add(kind, name, bpm=self.bpm.value.strip())
        return commands.master_add(kind, name)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_ok()

    def action_ok(self) -> None:
        problem = self.problem()
        if problem is None:
            self.dismiss(self.line())
        else:
            self.error.update(problem)

    def action_cancel(self) -> None:
        self.dismiss(None)


class MasterPanel(Panel):
    """F7's MASTERS panel (see the module docs), built with the show's masters:
    the page builds it again when they change, and keeps :attr:`show` current
    for the dialogs (the groups a new group master may scale)."""

    DEFAULT_CSS = f"""
    MasterPanel .ms-row {{ height: 1; }}
    MasterPanel .ms-row > CommandButton {{ margin-left: 1; }}
    MasterPanel .ms-text {{ width: 1fr; text-wrap: nowrap; text-overflow: ellipsis; }}
    MasterPanel .ms-empty {{ color: {colors.DIM}; }}
    MasterPanel .ms-add {{ height: 1; margin-top: 1; }}
    """

    def __init__(self, show: ShowModel | None) -> None:
        self.show = show
        everyone = () if show is None else show.masters
        self.masters = tuple(master for master in everyone if master.kind != "grand")
        self.renames = [ActionButton("rename…", partial(self.ask_name, m)) for m in self.masters]
        self.deletes = [
            ActionButton("delete", partial(self.delete, m), "danger") for m in self.masters
        ]
        self.add = ActionButton("+ master…", self.ask_add, "go")
        rows = zip(self.masters, self.renames, self.deletes, strict=True)
        children: list[Widget] = [
            Horizontal(Static(master_text(m), classes="ms-text"), rename, delete, classes="ms-row")
            for m, rename, delete in rows
        ]
        if not self.masters:
            children.append(Static(Text(NO_MASTERS), classes="ms-empty"))
        children.append(Horizontal(self.add, classes="ms-add"))
        super().__init__("masters", *children)

    def everyone(self) -> tuple[MasterView, ...]:
        return () if self.show is None else self.show.masters

    def ask_add(self) -> None:
        """``[+ master…]``: :class:`MasterDialog`, then its line."""

        def given(line: Line | None) -> None:
            if line is not None:
                self.post_message(RunLine(line))

        groups = () if self.show is None else self.show.groups
        self.app.push_screen(MasterDialog(self.everyone(), groups), given)

    def ask_name(self, master: MasterView) -> None:
        """``[rename…]``: ``rename master "FX" "Size"``; nothing for the name it has."""

        def given(text: str | None) -> None:
            if text is not None and text.strip() != master.name:
                self.post_message(RunLine(commands.rename_master(master.name, text.strip())))

        names = [other.name for other in self.everyone()]
        check = check_master_name(names, master.name)
        self.app.push_screen(TextDialog("RENAME MASTER", master.name, check), given)

    def delete(self, master: MasterView) -> None:
        """``[delete]``: ``delete master "FX" cascade``, after busk's question."""
        self.post_message(RunLine(commands.delete_master(master.name)))

    def stops(self) -> list[Stop]:
        """Each master's ``[rename…]`` and ``[delete]``, then ``[+ master…]``."""
        stops: list[Stop] = []
        for master, rename, delete in zip(self.masters, self.renames, self.deletes, strict=True):
            stops.append(Stop(Item(f"rename master {master.name}…", action=rename.action), rename))
            stops.append(Stop(Item(f"delete master {master.name}", action=delete.action), delete))
        stops.append(Stop(Item("+ master…", action=self.ask_add), self.add))
        return stops
