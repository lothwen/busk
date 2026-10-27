"""Master bars and the blackout toggle (spec §8.1, §8.7).

A :class:`MasterBar` is a master's name, its level as a bar, and the level
in whole percent. The bar sets it: ``gm p%`` for the grand master,
``master "<name>" p%`` for the others. Colours by kind: the grand master
and fade-time masters the foreground, size masters green, group and speed
masters amber.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import partial
from typing import Final

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.commands import Line
from busk_tui.model import LiveState, MasterView, ShowModel
from busk_tui.nav import Item, Stop
from busk_tui.widgets.bars import HBar
from busk_tui.widgets.controls import MARKED, CommandButton

MASTER_COLORS: Final = {
    "grand": colors.FG,
    "size": colors.GREEN,
    "group": colors.AMBER,
    "speed": colors.AMBER,
    "fadeTime": colors.FG,
}


def master_command(master: MasterView) -> Callable[[float], Line]:
    """The line that sets ``master`` to a level."""
    return commands.gm if master.kind == "grand" else partial(commands.master, master.name)


def master_item(master: MasterView) -> Item:
    """The pane cursor's item for a master bar: its line, to finish with a level."""
    line = "gm " if master.kind == "grand" else f"master {commands.quoted(master.name)} "
    return Item(master.name, prefill=line)


class MasterBar(Horizontal):
    """One master (see the module docs). ``label`` is shown instead of the
    name (``GM``)."""

    DEFAULT_CSS = """
    MasterBar { height: 1; }
    MasterBar > .master-label { width: 9; text-wrap: nowrap; text-overflow: ellipsis; }
    MasterBar > .master-value { width: 5; text-align: right; }
    """

    def __init__(self, master: MasterView, level: float, *, label: str | None = None) -> None:
        super().__init__()
        self.master = master
        self.level = level
        self.label = master.name if label is None else label
        self.marked = False
        self.name_text = Static(self._label(), classes="master-label")
        key = "gm" if master.kind == "grand" else f"master:{master.name}"
        color = MASTER_COLORS.get(master.kind, colors.FG)
        self.bar = HBar(level, color=color, command=master_command(master), key=key)
        self.value = Static(self._value(), classes="master-value")

    def compose(self) -> ComposeResult:
        yield self.name_text
        yield self.bar
        yield self.value

    def show(self, level: float) -> None:
        if level != self.level:
            self.level = level
            self.bar.show_level(level)
            self.value.update(self._value())

    def mark(self, index: int | None) -> None:
        self.marked = index is not None
        self.name_text.update(self._label())

    def _label(self) -> Text:
        return Text(self.label, style=MARKED if self.marked else colors.MID)

    def _value(self) -> Text:
        return Text(str(round(self.level * 100)), style=colors.FG)


class BlackoutButton(CommandButton):
    """``[BLACKOUT]`` (``[BLACKOUT on]``, ``[BLACKOUT off]`` with ``words``;
    ``[B.O.]`` when ``short``): ``blackout on`` or ``blackout off`` by the
    state it shows, red reversed while on."""

    def __init__(self, *, words: bool = False, short: bool = False, id: str | None = None) -> None:
        self.words = words
        self.short = short
        super().__init__(self._label(False), commands.blackout(True), "danger", id=id)

    def show(self, on: bool) -> None:
        self.change(self._label(on), commands.blackout(not on), reverse=on)

    def _label(self, on: bool) -> str:
        if self.short:
            return "B.O."
        return f"BLACKOUT {'on' if on else 'off'}" if self.words else "BLACKOUT"


class MasterBars(Vertical):
    """A bar for each of the show's masters of ``kinds``, the grand master
    as ``GM``; built again when the show's masters change."""

    DEFAULT_CSS = "MasterBars { height: auto; }"

    def __init__(self, kinds: Sequence[str], *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.kinds = tuple(kinds)
        self.masters: tuple[MasterView, ...] | None = None
        self.bars: list[MasterBar] = []

    def build(self, show: ShowModel | None, live: LiveState | None) -> None:
        masters = () if show is None else tuple(m for m in show.masters if m.kind in self.kinds)
        if masters == self.masters:
            return
        self.masters = masters
        levels = {} if live is None else {m.name: m.level for m in live.masters}
        self.bars = [
            MasterBar(
                master, levels.get(master.name, 0.0), label="GM" if master.kind == "grand" else None
            )
            for master in masters
        ]
        self.remove_children()
        self.mount_all(self.bars)

    def show_levels(self, live: LiveState) -> None:
        levels = {master.name: master.level for master in live.masters}
        for bar in self.bars:
            bar.show(levels.get(bar.master.name, 0.0))

    def stops(self) -> list[Stop]:
        return [Stop(master_item(bar.master), bar) for bar in self.bars]
