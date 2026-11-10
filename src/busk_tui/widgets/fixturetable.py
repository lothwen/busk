"""F3's fixture sheet (spec §8.3, plan Phase 4): a row per fixture, with its
live output.

A row: ``▸`` while any of the fixture's elements is selected, its number,
name, profile (``×12`` for a fixture of twelve elements), type (the
profile's category), mode, patch (``1.49``; ``—`` in red while unpatched),
and from the output: intensity (``20–80%`` while its elements differ), one
swatch per element in its colour at its intensity (twelve at most), pan,
tilt and zoom (on fixtures that have them), and what drives its intensity
(``park``, ``prog``, ``P9``, ``fx P11``, ``fx``; ``—``: nothing).

Source colouring: intensity and the source by what drives the intensity,
pan and tilt by what drives the position, zoom by what drives the beam
(amber park, magenta programmer, foreground playback, green effect, dim
nothing).

In edit mode :class:`RigTable` takes its place: the same row up to the patch,
then what the FIXTURE panel sets, the limits (``pan tilt int``) and the place
(``●``), and the chosen fixture's number lit. It reads no output.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from rich.text import Text

from busk_tui import colors
from busk_tui.colors import ColorMode
from busk_tui.model import ElementOutput, FixtureInfo, Limits, OutputModel, Source
from busk_tui.widgets.options import LIT
from busk_tui.widgets.rows import Cells, Column, RowTable, cell

COLOR_CELLS: Final = 12
"""At most this many swatches per fixture: one per element, evenly spaced
when it has more."""

NONE: Final = "—"
UNKNOWN: Final = "·"  # no output read yet; no place

_RANK: Final[dict[Source, int]] = {
    "park": 4, "programmer": 3, "effect": 2, "playback": 1, "none": 0,
}  # fmt: skip


class FixtureTable(RowTable):
    COLUMNS = (
        Column("marker", "", 1),
        Column("number", "#", 4, right=True),
        Column("name", "name", 10, flex=True),
        Column("profile", "profile", 12, drop=3, flex=True),
        Column("category", "type", 6, drop=6),
        Column("mode", "mode", 9, drop=5),
        Column("patch", "patch", 7),
        Column("intensity", "intensity", 9, right=True),
        Column("color", "colour", COLOR_CELLS),
        Column("pan", "pan", 5, right=True),
        Column("tilt", "tilt", 5, right=True),
        Column("zoom", "zoom", 4, right=True, drop=4),
        Column("source", "src", 7),
    )


class RigTable(RowTable):
    COLUMNS = (
        Column("marker", "", 1),
        Column("number", "#", 4, right=True),
        Column("name", "name", 10, flex=True),
        Column("profile", "profile", 12, drop=3, flex=True),
        Column("category", "type", 6, drop=6),
        Column("mode", "mode", 9, drop=5),
        Column("patch", "patch", 7),
        Column("limits", "limits", 12),
        Column("place", "place", 5, drop=4),
    )


def by_fixture(output: OutputModel | None) -> dict[int, tuple[ElementOutput, ...]]:
    """The output's elements, by fixture number."""
    found: dict[int, list[ElementOutput]] = {}
    for out in () if output is None else output.fixtures:
        found.setdefault(out.number, []).append(out)
    return {number: tuple(elements) for number, elements in found.items()}


def patch_text(fixture: FixtureInfo) -> Text:
    """``1.49``, ``1.49 split`` (an element patch, which busk does not run
    yet), or a red ``—``."""
    if fixture.patch is None:
        return cell(NONE, colors.RED)
    universe, address = fixture.patch
    text = cell(f"{universe}.{address}", colors.FG)
    if fixture.split:
        text.append(" split", style=colors.AMBER)
    return text


def profile_text(fixture: FixtureInfo) -> str:
    """Its profile's name, with ``×12`` for a fixture of twelve elements."""
    return fixture.profile + (f" ×{fixture.elements}" if fixture.elements > 1 else "")


def identity_cells(fixture: FixtureInfo, selected: bool, category: str | None) -> dict[str, Text]:
    """What a row of either table starts with: the fixture, up to its patch."""
    return {
        "marker": cell("▸" if selected else "", colors.CYAN),
        "number": cell(str(fixture.number), colors.CYAN if selected else colors.MID),
        "name": cell(fixture.name, colors.FG) if fixture.name else cell(NONE, colors.BORDER),
        "profile": cell(profile_text(fixture), colors.MID),
        "category": cell(category, colors.DIM) if category else cell(NONE, colors.BORDER),
        "mode": cell(fixture.mode, colors.DIM),
        "patch": patch_text(fixture),
    }


def limits_text(limits: Limits) -> str:
    """The limits a fixture has: ``tilt``, ``pan tilt int``."""
    named = (("pan", limits.pan), ("tilt", limits.tilt), ("int", limits.intensity))
    return " ".join(name for name, limit in named if limit is not None)


def rig_cells(fixture: FixtureInfo, selected: bool, chosen: bool, category: str | None) -> Cells:
    cells = identity_cells(fixture, selected, category)
    if chosen:
        cells["number"] = cell(str(fixture.number), LIT)
    cells["limits"] = cell(limits_text(fixture.limits), colors.AMBER)
    placed = fixture.location is not None
    cells["place"] = cell("●", colors.MID) if placed else cell(UNKNOWN, colors.BORDER)
    return cells


def fixture_cells(
    fixture: FixtureInfo,
    outputs: Sequence[ElementOutput],
    selected: bool,
    category: str | None,
    mode: ColorMode,
) -> Cells:
    cells = identity_cells(fixture, selected, category)
    if not outputs:
        unknown = cell(UNKNOWN, colors.BORDER)
        cells.update(intensity=unknown, color=unknown, source=unknown)
        return cells
    source, playback = top_source(outputs, "intensity")
    style = colors.SOURCE_COLORS[source]
    low = round(min(out.intensity for out in outputs) * 100)
    high = round(max(out.intensity for out in outputs) * 100)
    cells["intensity"] = cell(f"{low}%" if low == high else f"{low}–{high}%", style)
    cells["color"] = swatches(outputs, mode)
    cells["source"] = cell(source_text(source, playback), style)
    for name, family in (("pan", "position"), ("tilt", "position"), ("zoom", "beam")):
        value = next((v for out in outputs if (v := getattr(out, name)) is not None), None)
        if value is not None:
            cells[name] = cell(
                f"{round(value)}°", colors.SOURCE_COLORS[top_source(outputs, family)[0]]
            )
    return cells


def top_source(outputs: Sequence[ElementOutput], family: str) -> tuple[Source, int | None]:
    """What drives ``family`` on the fixture: of its elements', park first,
    as busk ranks it, then the programmer, an effect, a playback; with the
    playback number busk gives for the intensity."""
    best: Source = "none"
    playback: int | None = None
    for out in outputs:
        source = out.source(family)
        if source is not None and _RANK[source] > _RANK[best]:
            best, playback = source, out.playback
    return best, playback


def source_text(source: Source, playback: int | None) -> str:
    """``park``, ``prog``, ``P9`` (a playback's cue), ``fx P11`` (its cue's
    effect), ``fx`` (the programmer's), ``—``."""
    if source == "park":
        return "park"
    if source == "programmer":
        return "prog"
    if source == "effect":
        return "fx" if playback is None else f"fx P{playback}"
    if source == "playback":
        return "pb" if playback is None else f"P{playback}"
    return NONE


def swatches(outputs: Sequence[ElementOutput], mode: ColorMode) -> Text:
    """One ``█`` per element in its colour at its intensity (``██`` for one
    element), :data:`COLOR_CELLS` at most; an element with no colour as
    white."""
    count = len(outputs)
    shown = 1 if count == 1 else min(count, COLOR_CELLS)
    parts: list[tuple[str, str]] = []
    for index in range(shown):
        out = outputs[index * count // shown]
        glyph = "██" if count == 1 else "█"
        parts.append((glyph, colors.swatch(out.color or (1.0, 1.0, 1.0), out.intensity, mode)))
    return Text.assemble(*parts)


def legend() -> list[Text]:
    """What the colours and marks of the sheet mean."""
    keys = [
        Text.assemble(("■ ", colors.SOURCE_COLORS[source]), (name, colors.DIM))
        for source, name in (("park", "park"), ("programmer", "programmer"),
                             ("playback", "playback"), ("effect", "effect"), ("none", "nothing"))
    ]  # fmt: skip
    keys.append(Text.assemble(("— ", colors.RED), ("unpatched", colors.DIM)))
    keys.append(Text.assemble(("▸ ", colors.CYAN), ("selected", colors.DIM)))
    return keys
