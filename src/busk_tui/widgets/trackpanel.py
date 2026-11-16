"""F4's TRACK panel (pending plan Phase 28, Q10 (a)): what the chosen cue
puts on stage, from busk's ``tracking(L)``, and where each value comes from.

A row per fixture the cue gives a value, or takes one away from, by number.
Then a column per family the list's cues use (``intensity``, ``colour``,
``position``, ``beam``, ``focus``, ``shutter``), the same for every cue of
the list, so the columns stay while the operator moves from cue to cue. A
cell is what the cue puts on stage in that family when the list plays by GO
from its first cue:

* a value the cue stores, bright; one it tracks from a cue before, dim, with
  the cue it comes from: ``Blue ← 9/1``;
* a preset by its name, a colour with its swatch and its components, a
  number in its unit (``70%``, ``-30°``);
* each attribute by its name where the family has several (``pan -30° tilt
  40°``), once where a preset gives them all (``Audience``);
* ``mixed`` where the fixture's elements differ, as F2's PROGRAMMER
  CONTENTS has it;
* ``✕`` where the cue releases the attribute (``released`` when it releases
  all of them); ``·`` where it has nothing.

With the mouse on a cell, the hint row says it in words (``201 color Blue,
tracked from 9/1``). When the table is narrower than its columns, the last
families go first.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from rich.text import Text
from textual import events

from busk_tui import attributes, colors
from busk_tui.colors import ColorMode
from busk_tui.model import TrackCue, TrackSheet, TrackValue
from busk_tui.widgets.controls import ShowHint
from busk_tui.widgets.rows import Cells, Column, RowTable, cell

FAMILIES: Final = ("intensity", "color", "position", "beam", "focus", "shutter")
"""The families with a column, in this order."""

COLUMNS: Final = {
    "intensity": Column("intensity", "intensity", 14, drop=1),
    "color": Column("color", "colour", 24, drop=2),
    "position": Column("position", "position", 22, drop=3),
    "beam": Column("beam", "beam", 22, drop=4),
    "focus": Column("focus", "focus", 12, drop=5),
    "shutter": Column("shutter", "shutter", 16, drop=6),
}
"""Each family's column at its least; the last one shown takes the room left."""

FIXTURE: Final = Column("fixture", "#", 5)

UNNAMED: Final = frozenset({"intensity", "color", "focus", "shutter"})
"""The attributes a cell gives without their name: each is its family's own."""

NOTHING: Final = "·"
RELEASED: Final = "✕"

_ORDER: Final = {attribute: index for index, attribute in enumerate(attributes.FAMILY_OF)}
"""busk's registry order of the attributes, as the read lists them."""


@dataclass(frozen=True, slots=True)
class Track:
    """What the panel draws of one cue: its columns, a row per fixture,
    and each cell's hint by column name."""

    columns: tuple[Column, ...]
    rows: tuple[Cells, ...]
    hints: tuple[Mapping[str, str], ...]


def families(sheet: TrackSheet) -> tuple[str, ...]:
    """The families the list's cues give a value of, or release, in the
    panel's order."""
    found = {attributes.family_of(value.attribute) for cue in sheet.cues for value in cue.values}
    found |= {attributes.family_of(slot[2]) for cue in sheet.cues for slot in cue.released}
    return tuple(family for family in FAMILIES if family in found)


def track(cue: TrackCue, cue_list: int, shown: Sequence[str], mode: ColorMode) -> Track:
    """The panel's table for ``cue`` of list ``cue_list``, a column for each
    of the families ``shown``."""
    held: dict[int, dict[str, dict[str, list[TrackValue]]]] = {}  # fixture → family → attribute
    for value in cue.values:
        family = attributes.family_of(value.attribute)
        if family is not None and family in shown:
            by_family = held.setdefault(value.number, {}).setdefault(family, {})
            by_family.setdefault(value.attribute, []).append(value)
    gone: dict[int, dict[str, set[str]]] = {}
    for number, _, attribute in cue.released:
        family = attributes.family_of(attribute)
        if family is not None and family in shown:
            gone.setdefault(number, {}).setdefault(family, set()).add(attribute)
    rows: list[Cells] = []
    hints: list[dict[str, str]] = []
    for number in sorted(held.keys() | gone.keys()):
        row: dict[str, Text] = {"fixture": cell(str(number), colors.CYAN)}
        said: dict[str, str] = {}
        for family in shown:
            values = held.get(number, {}).get(family, {})
            released = gone.get(number, {}).get(family, set())
            if values or released:
                row[family], hint = family_cell(values, released, cue_list, mode)
                said[family] = f"{number} {hint}"
            else:
                row[family] = cell(NOTHING, colors.BORDER)
        rows.append(row)
        hints.append(said)
    columns = [COLUMNS[family] for family in shown]
    if columns:
        last = columns[-1]
        columns[-1] = Column(last.name, last.title, last.width, last.drop, flex=True)
    return Track((FIXTURE, *columns), tuple(rows), tuple(hints))


@dataclass(frozen=True, slots=True)
class _Piece:
    attribute: str
    text: str  # the value as drawn; empty for a release
    since: str | None  # the cue it comes from; None: this cue's own
    several: bool = False  # its elements' values come from different cues
    swatch: str | None = None  # a colour's, as drawn
    preset: str | None = None


def family_cell(
    held: Mapping[str, Sequence[TrackValue]],
    released: set[str],
    cue_list: int,
    mode: ColorMode,
) -> tuple[Text, str]:
    """One fixture's cell in one family, and its hint: each attribute it
    has values of (``held``, by attribute, one per element) or ``released``,
    in busk's order."""
    pieces = [
        _piece(attribute, held.get(attribute, ()), mode)
        for attribute in sorted(held.keys() | released, key=lambda name: _ORDER.get(name, 0))
    ]
    words = " · ".join(_words(piece, cue_list) for piece in pieces)
    text = Text()
    if all(not piece.text for piece in pieces):
        text.append(f"{RELEASED} released", style=colors.AMBER)
        return text, words
    first = pieces[0]
    same = all(
        (piece.since, piece.several, piece.preset) == (first.since, first.several, first.preset)
        for piece in pieces
    )
    if same and first.preset is not None:  # one preset gives them all
        pieces = [_Piece(first.attribute, first.preset, first.since, first.several, first.swatch)]
        named = False
    else:
        named = len(pieces) > 1 or first.attribute not in UNNAMED
    for index, piece in enumerate(pieces):
        if index:
            text.append(" " if same else " · ", style=colors.DIM)
        if named and piece.attribute not in UNNAMED:
            text.append(f"{piece.attribute} ", style=colors.MID)
        if not piece.text:
            text.append(RELEASED, style=colors.AMBER)
            continue
        if piece.swatch is not None:
            text.append("██ ", style=piece.swatch)
        text.append(piece.text, style=colors.FG if piece.since is None else colors.DIM)
        if not same:
            text.append_text(_from(piece, cue_list))
    if same:
        text.append_text(_from(first, cue_list))
    return text, words


def _piece(attribute: str, values: Sequence[TrackValue], mode: ColorMode) -> _Piece:
    """One attribute's values on a fixture's elements (none: released)."""
    if not values:
        return _Piece(attribute, "", None)
    first = values[0]
    since = {value.since for value in values}
    several = len(since) > 1
    origin = None if several or None in since else first.since
    if any(value.value != first.value or value.preset != first.preset for value in values[1:]):
        return _Piece(attribute, "mixed", origin, several)
    value = first.value
    swatch = None
    if isinstance(value, tuple):
        swatch = colors.swatch(attributes.rgb(value), 1.0, mode)
    if first.preset is not None:
        return _Piece(attribute, first.preset, origin, several, swatch, first.preset)
    if isinstance(value, tuple):
        return _Piece(attribute, attributes.rgb_text(value), origin, several, swatch)
    return _Piece(attribute, attributes.summary_text(attribute, value), origin, several)


def _from(piece: _Piece, cue_list: int) -> Text:
    """`` ← 9/1`` after a tracked value; nothing after the cue's own."""
    if piece.several:
        return Text(" ← several cues", style=colors.MID)
    if piece.since is None:
        return Text()
    return Text(f" ← {cue_list}/{piece.since}", style=colors.MID)


def _words(piece: _Piece, cue_list: int) -> str:
    """The hint's words for one attribute."""
    if not piece.text:
        return f"{piece.attribute} released"
    if piece.several:
        source = "from several cues"
    elif piece.since is None:
        source = "stored in this cue"
    else:
        source = f"tracked from {cue_list}/{piece.since}"
    return f"{piece.attribute} {piece.text}, {source}"


class TrackTable(RowTable):
    """The panel's table (see the module docs): its columns are its own,
    and the hint row says what the cell under the mouse is."""

    COLUMNS = (FIXTURE,)

    def __init__(self, empty: Text | None = None, *, id: str | None = None) -> None:
        super().__init__(empty, id=id)
        self._columns: tuple[Column, ...] = self.COLUMNS
        self.hints: tuple[Mapping[str, str], ...] = ()
        self._hint: str | None = None

    def columns(self) -> tuple[Column, ...]:
        return self._columns

    def show_track(self, shown: Track | None, empty: Text) -> None:
        """A cue's table (``None``: none, ``empty`` instead); drawn again
        whole when the columns change."""
        columns = self.COLUMNS if shown is None else shown.columns
        if columns != self._columns:
            self._columns = columns
            self._strips.clear()
            self.refresh()
        self.hints = () if shown is None else shown.hints
        self.show(() if shown is None else shown.rows, None, empty)

    def on_mouse_move(self, event: events.MouseMove) -> None:
        super().on_mouse_move(event)
        row, name = self._under(event)
        hint = None
        if row is not None and name is not None and row < len(self.hints):
            hint = self.hints[row].get(name)
        self._tell(hint)

    def on_leave(self, event: events.Leave) -> None:
        super().on_leave(event)
        self._tell(None)

    def _tell(self, hint: str | None) -> None:
        if hint != self._hint:
            self._hint = hint
            self.post_message(ShowHint(hint))
