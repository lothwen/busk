"""What park holds (the show's ``park``), as F7's PARKED panel and F3's FIXTURE
panel show it: a row per fixture, attribute and value, with the elements it
holds there written as busk's targets take them (``204``, ``301.2 thru
301.5``; a fixture parked whole is its number).

F7's PARKED panel: a row per value, each with ``[unpark]`` (``unpark fixture
204 intensity``), and ``[unpark all]``, after the TUI's question (busk asks
none).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rich.text import Text
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.formats import selection_text, value_text
from busk_tui.model import FixtureInfo, Parked, Value
from busk_tui.nav import Item, Stop
from busk_tui.widgets.controls import ActionButton, CommandButton, RunLine
from busk_tui.widgets.panel import Panel


@dataclass(frozen=True, slots=True)
class ParkedRow:
    """One value park holds on some elements of one fixture."""

    number: int  # the fixture's
    where: str  # its elements, compressed: ``204``, ``301.2 thru 301.5``
    attribute: str
    value: Value

    def whole(self) -> bool:
        """Whether it holds every element of the fixture (``where`` is its number)."""
        return self.where == str(self.number)


def parked_rows(park: Sequence[Parked], fixtures: Sequence[FixtureInfo]) -> tuple[ParkedRow, ...]:
    """A row per fixture, attribute and value of ``park``, by fixture number,
    then in the order the show parked them."""
    found: dict[tuple[int, str, Value], list[int]] = {}
    for entry in park:
        found.setdefault((entry.number, entry.attribute, entry.value), []).append(entry.element)
    rows = []
    for (number, attribute, value), elements in sorted(found.items(), key=lambda kv: kv[0][0]):
        where = selection_text([(number, element) for element in sorted(elements)], fixtures)
        rows.append(ParkedRow(number, where, attribute, value))
    return tuple(rows)


def held_text(row: ParkedRow) -> Text:
    """``intensity 0%``: the attribute and its value."""
    text = Text(row.attribute, style=colors.MID)
    text.append(f" {value_text(row.attribute, row.value)}", style=colors.AMBER)
    return text


def row_text(row: ParkedRow) -> Text:
    """``204 intensity 0%``."""
    text = Text(f"{row.where} ", style=colors.FG)
    text.append_text(held_text(row))
    return text


class ParkedPanel(Panel):
    """F7's PARKED panel (see the module docs), built with the rows it shows:
    the page builds it again when they change."""

    DEFAULT_CSS = f"""
    ParkedPanel .pk-row {{ height: 1; }}
    ParkedPanel .pk-text {{ width: 1fr; text-wrap: nowrap; text-overflow: ellipsis; }}
    ParkedPanel .pk-empty {{ color: {colors.DIM}; }}
    ParkedPanel .pk-all {{ height: 1; margin-top: 1; }}
    """

    def __init__(self, rows: Sequence[ParkedRow], count: int) -> None:
        """``count``: how many values park holds (an element's attribute each)."""
        self.rows = tuple(rows)
        self.count = count
        self.unparks = [
            CommandButton("unpark", commands.unpark(row.where, row.attribute)) for row in rows
        ]
        self.unpark_all = ActionButton("unpark all", self.ask_unpark_all, "danger", inert=not rows)
        children: list[Widget] = [
            Horizontal(Static(row_text(row), classes="pk-text"), button, classes="pk-row")
            for row, button in zip(self.rows, self.unparks, strict=True)
        ]
        if not rows:
            children.append(
                Static(Text("nothing parked · [park…] on F3, in edit mode"), classes="pk-empty")
            )
        children.append(Horizontal(self.unpark_all, classes="pk-all"))
        super().__init__("parked", *children)

    def ask_unpark_all(self) -> None:
        """``[unpark all]``, after the TUI's question."""
        if self.rows:
            values = f"{self.count} value{'' if self.count == 1 else 's'}"
            question = f"Unpark everything? Park holds {values}."
            self.post_message(RunLine(commands.unpark_all(), ask=question))

    def stops(self) -> list[Stop]:
        """Each ``[unpark]``, then ``[unpark all]``."""
        stops = [
            Stop(Item(f"unpark {row.where} {row.attribute}", line=button.line.text), button)
            for row, button in zip(self.rows, self.unparks, strict=True)
        ]
        if not self.unpark_all.inert:
            stops.append(Stop(Item("unpark all", action=self.ask_unpark_all), self.unpark_all))
        return stops
