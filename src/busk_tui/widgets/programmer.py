"""The PROGRAMMER CONTENTS table (spec §8.2; layout A reuses it).

A row per fixture the programmer holds a value for, in the order it got
its first one: number, name, intensity, the colour as a swatch and its
components (two decimals), pan, tilt, zoom, and the other attributes it
holds (``strobeRate 10Hz · gobo1 breakup``). A value from a preset shows the
preset's name. A fixture whose elements hold different values shows
``mixed``; ``·`` is a value it does not hold. Values are magenta: the
programmer's colour.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from rich.text import Text
from textual.widgets import Static

from busk_tui import attributes, colors
from busk_tui.colors import ColorMode
from busk_tui.model import HeldValue, ProgrammerModel, ShowModel

COLUMNS: Final = (("#", 5), ("name", 18), ("intensity", 10), ("colour", 25), ("pan", 8),
                  ("tilt", 8), ("zoom", 8), ("other", 0))  # fmt: skip
"""The columns and their widths (0: the rest of the line)."""

MAIN: Final = ("intensity", "color", "pan", "tilt", "zoom")
"""The attributes with a column of their own."""

EMPTY: Final = "programmer empty · select fixtures, then set attributes or apply presets"


def held_text(values: Sequence[HeldValue]) -> tuple[str, HeldValue | None]:
    """One fixture's values of one attribute, one per element it holds: the
    text shown (the preset's name, the value, ``mixed``), and the one value
    when they agree."""
    first = values[0]
    if any(value.value != first.value or value.preset != first.preset for value in values[1:]):
        return "mixed", None
    if first.preset is not None:
        return first.preset, first
    value = first.value
    if isinstance(value, tuple):
        return attributes.rgb_text(value), first
    return attributes.summary_text(first.attribute, value), first


def contents(
    programmer: ProgrammerModel | None, show: ShowModel | None, mode: ColorMode
) -> list[Text]:
    """The table's lines: the header, then a row per fixture."""
    values = () if programmer is None else programmer.values
    by_fixture: dict[int, dict[str, list[HeldValue]]] = {}
    for value in values:
        by_fixture.setdefault(value.number, {}).setdefault(value.attribute, []).append(value)
    header = Text()
    for title, width in COLUMNS:
        header.append(title.ljust(width) if width else title, style=colors.DIM)
    lines = [header]
    for number, held in by_fixture.items():
        fixture = None if show is None else show.fixture(number)
        line = Text()
        line.append(str(number).ljust(5), style=colors.MAGENTA)
        name = "" if fixture is None else fixture.name
        line.append(_cell(name, 18), style=colors.FG)
        for attribute, width in (("intensity", 10), ("color", 25), ("pan", 8), ("tilt", 8),
                                 ("zoom", 8)):  # fmt: skip
            if attribute not in held:
                line.append("·".ljust(width), style=colors.BORDER)
                continue
            text, one = held_text(held[attribute])
            if attribute == "color":
                swatch = (
                    "color(236)"
                    if one is None or not isinstance(one.value, tuple)
                    else colors.swatch(attributes.rgb(one.value), 1.0, mode)
                )
                line.append("██ ", style=swatch)
                width -= 3
            line.append(_cell(text, width), style=colors.MAGENTA)
        other = [
            f"{attribute} {held_text(group)[0]}"
            for attribute, group in held.items()
            if attribute not in MAIN
        ]
        line.append(" · ".join(other), style=colors.MAGENTA)
        lines.append(line)
    return lines


def _cell(text: str, width: int) -> str:
    """``text`` in a column ``width`` wide, cut with ``…``, a space after it."""
    room = width - 1
    if len(text) > room:
        text = text[: room - 1] + "…"
    return text.ljust(width)


class ProgrammerTable(Static):
    """The table (see the module docs); empty, it says how to fill it."""

    DEFAULT_CSS = "ProgrammerTable { height: auto; }"

    def __init__(self) -> None:
        super().__init__(Text(EMPTY, style=colors.DIM))
        self.shown: list[Text] | None = None

    def show(
        self, programmer: ProgrammerModel | None, show: ShowModel | None, mode: ColorMode
    ) -> None:
        lines = contents(programmer, show, mode)
        if lines == self.shown:
            return
        self.shown = lines
        if len(lines) == 1:
            self.update(Text(EMPTY, style=colors.DIM))
        else:
            self.update(Text("\n").join(lines))
