"""F4's tables (spec §8.4, plan Phase 3): the cue lists, and the cues of one.

CUELISTS has a row per cue list: number, name, kind (``seq`` or ``chase``),
how many cues, and the playback that runs it (``P9``; ``—``: none).

The cue table has a row per cue, as the show stores it: ``▶`` on the cue
the list's playback is on, ``L/C``, the name, the fade times (``1/3``, and
a family's own: ``2, position 4``), the delays, the curve, the trigger's
delay under ``follow`` or ``wait`` (``—`` for a GO), the intensity and
colour entries (a value, a preset's name, ``spread``, ``per target``; a
colour with its swatch), and the cue's effects by id. Cells that are edits
(time, delay, curve, follow, wait) name a pre-fill (:func:`edit_prefill`).
"""

from __future__ import annotations

from typing import Final

from rich.text import Text

from busk_tui import colors, commands
from busk_tui.colors import ColorMode
from busk_tui.formats import delay_text, pair_text, seconds, stored_text, time_text
from busk_tui.model import CueInfo, CueListInfo, StoredValue
from busk_tui.widgets.rows import Cells, Column, RowTable, cell

NONE: Final = "—"

EDITS: Final = ("time", "delay", "curve", "follow", "wait")
"""The cue table's cells whose click puts an edit in the prompt."""


class CueListTable(RowTable):
    COLUMNS = (
        Column("number", "#", 3, right=True),
        Column("name", "name", 8, flex=True),
        Column("kind", "kind", 5),
        Column("cues", "cues", 4, right=True),
        Column("playback", "pb", 4, drop=1),
    )


class CueTable(RowTable):
    COLUMNS = (
        Column("marker", "", 1),
        Column("cue", "cue", 6),
        Column("name", "name", 10, flex=True),
        Column("time", "time", 13, drop=1),  # never dropped before the trigger's two
        Column("delay", "delay", 6, drop=5),
        Column("curve", "curve", 9, drop=6),
        Column("follow", "follow", 6),
        Column("wait", "wait", 6),
        Column("intensity", "intensity", 10, drop=3),
        Column("color", "colour", 17, drop=4),
        Column("fx", "fx", 8, drop=2),
    )


def list_cells(cue_list: CueListInfo, runs: tuple[int, ...]) -> Cells:
    return {
        "number": cell(str(cue_list.number), colors.MID),
        "name": cell(cue_list.name, colors.FG),
        "kind": cell("chase" if cue_list.mode == "chase" else "seq", colors.DIM),
        "cues": cell(str(len(cue_list.cues)), colors.MID),
        "playback": cell(f"P{runs[0]}" if runs else NONE, colors.DIM if runs else colors.BORDER),
    }


def cue_cells(cue_list: CueListInfo, cue: CueInfo, current: bool, mode: ColorMode) -> Cells:
    trigger_delay = seconds(cue.delay)
    delays = delay_text(cue)
    return {
        "marker": cell("▶" if current else "", colors.GREEN),
        "cue": cell(f"{cue_list.number}/{cue.number}", colors.CYAN if current else colors.MID),
        "name": cell(cue.name, colors.FG) if cue.name else cell(NONE, colors.BORDER),
        "time": cell(time_text(cue), colors.FG),
        "delay": cell(delays, colors.FG) if delays else cell(NONE, colors.BORDER),
        "curve": cell(cue.curve, colors.MID),
        "follow": _trigger(cue, "follow", trigger_delay),
        "wait": _trigger(cue, "wait", trigger_delay),
        "intensity": _values(cue, "intensity", mode),
        "color": _values(cue, "color", mode),
        "fx": (
            cell(", ".join(effect.id for effect in cue.effects), colors.GREEN)
            if cue.effects
            else cell("", colors.BORDER)
        ),
    }


def _trigger(cue: CueInfo, kind: str, delay: str) -> Text:
    return cell(delay, colors.AMBER) if cue.trigger == kind else cell(NONE, colors.BORDER)


def _values(cue: CueInfo, attribute: str, mode: ColorMode) -> Text:
    """The cue's entries of ``attribute``: each value as stored; a colour
    with its swatch."""
    found = [value for value in cue.values if value.attribute == attribute]
    if not found:
        return cell(NONE, colors.BORDER)
    text = Text()
    for index, value in enumerate(found):
        if index:
            text.append(", ", style=colors.DIM)
        if attribute == "color":
            text.append_text(_swatch(value, mode))
        text.append(stored_text(value), style=colors.FG)
    return text


def _swatch(value: StoredValue, mode: ColorMode) -> Text:
    if value.color is None:
        return Text.assemble(("░░ ", colors.MID))
    return Text.assemble(("██", colors.swatch(value.color, 1.0, mode)), " ")


def edit_prefill(cue_list: int, cue: CueInfo, name: str) -> str | None:
    """What a click on the cell ``name`` of a cue puts in the prompt: ``cue
    9/3 time ``, ``cue 9/3 time 1/3 delay `` (the fade times kept), ``cue
    9/3 time 1/3 `` (a curve next), ``cue 9/3 follow ``, ``cue 9/3 wait ``;
    ``None`` for the other cells."""
    times = pair_text(cue.fadeIn, cue.fadeOut)
    match name:
        case "time" | "follow" | "wait":
            return commands.cue_prefill(cue_list, cue.number, name)
        case "delay":
            return commands.cue_time_prefill(cue_list, cue.number, times, "delay")
        case "curve":
            return commands.cue_time_prefill(cue_list, cue.number, times)
    return None
