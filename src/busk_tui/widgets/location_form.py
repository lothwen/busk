"""The form of a fixture's place on stage: F3's FIXTURE panel and F1 C open it."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from textual.widget import Widget

from busk_tui import commands
from busk_tui.model import FixtureInfo
from busk_tui.widgets.controls import RunLine
from busk_tui.widgets.dialogs import FormDialog, read_number

PLACE: Final = ("x", "y", "z", "rx", "ry", "rz")
"""The fields of a location, in :data:`busk_tui.model.Location`'s order."""


def check_place(values: tuple[str, ...]) -> str | None:
    if all(read_number(value) is not None for value in values):
        return None
    return "six numbers"


def open_location_form(
    widget: Widget, fixture: FixtureInfo, still: Callable[[], bool] | None = None
) -> None:
    """``[location…]``: ``fixture 101 location {"x": 1, …}``, all six at once
    (``location.x`` fails until a location exists), from ``widget``. Nothing
    is sent for a place the fixture has, nor when ``still`` says the form no
    longer applies."""

    def given(values: tuple[str, ...] | None) -> None:
        if values is None or (still is not None and not still()):
            return
        place = tuple(float(value) for value in values)
        if place != fixture.location:
            widget.post_message(RunLine(commands.location(fixture.number, place)))

    starts = fixture.location or (0.0,) * len(PLACE)
    fields = tuple((key, commands.number(v)) for key, v in zip(PLACE, starts, strict=True))
    note = "x, y, z in metres · rx, ry, rz in degrees"
    title = f"LOCATION · fixture {fixture.number}"
    widget.app.push_screen(FormDialog(title, fields, check_place, note), given)
