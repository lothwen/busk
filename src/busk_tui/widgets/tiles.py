"""Preset tiles (spec §8.6).

A tile is one preset: its number (dim) and a preview on the first line,
its name on the second, in a border that turns cyan under the mouse. A
click runs ``preset <pool> N``. The preview is what the preset stores,
where all its values of an attribute agree, else ``mixed``:

* colour: a swatch of the one colour it gives;
* position: ``pan/tilt`` (``-30°/40°``);
* intensity: a block as high as the level, and the level;
* the other pools: their first attribute and its value (``zoom 20°``).

The last tile of a pool, ``+ record``, puts ``record preset <pool> N "``
in the prompt, with the next free number.
"""

from __future__ import annotations

from typing import Final

from rich.text import Text
from textual import events
from textual.widget import Widget

from busk_tui import attributes, colors, commands
from busk_tui.colors import ColorMode
from busk_tui.model import PresetInfo, Summary
from busk_tui.widgets.controls import MARKED, FillPrompt, RunLine
from busk_tui.widgets.effects import BLOCKS

TILE_WIDTH: Final = 16
"""A tile's width with the gap after it (spec: at least 15 cells)."""


def preview(preset: PresetInfo, mode: ColorMode) -> Text:
    """The tile's preview (see the module docs)."""
    values = dict(preset.values)
    if preset.color is not None:
        return Text("████", style=colors.swatch(preset.color, 1.0, mode))
    if preset.pool == "color":
        first = next(iter(preset.values), None)
        if first is None:
            return Text("mixed", style=colors.DIM)
        return _value(*first)
    if preset.pool == "position" and ("pan" in values or "tilt" in values):
        pan = _part("pan", values)
        tilt = _part("tilt", values)
        return Text(f"{pan}/{tilt}", style=colors.CYAN)
    if "intensity" in values and preset.pool in ("intensity", "all"):
        level = values["intensity"]
        if not isinstance(level, float):
            return Text("mixed", style=colors.DIM)
        block = BLOCKS[round(max(0.0, min(1.0, level)) * (len(BLOCKS) - 1))]
        return Text(f"{block} {round(level * 100)}%", style=colors.FG)
    first = next(iter(preset.values), None)
    return Text("", style=colors.DIM) if first is None else _value(*first)


def _part(attribute: str, values: dict[str, Summary]) -> str:
    if attribute not in values:
        return "·"
    return attributes.summary_text(attribute, values[attribute])


def _value(attribute: str, value: Summary) -> Text:
    text = Text(f"{attribute} ", style=colors.DIM)
    text.append(attributes.summary_text(attribute, value), style=colors.AMBER)
    return text


class PresetTile(Widget):
    """One preset (see the module docs); ``preset`` ``None``: the record tile."""

    DEFAULT_CSS = f"""
    PresetTile {{
        height: 4; border: solid {colors.TRACK}; padding: 0 1;
    }}
    PresetTile:hover {{ border: solid {colors.CYAN}; background: {colors.BAR}; }}
    """

    def __init__(self, pool: str, preset: PresetInfo | None, number: int, mode: ColorMode) -> None:
        super().__init__()
        self.pool = pool
        self.preset = preset
        self.number = number
        self.mode: ColorMode = mode
        self.marked = False

    @property
    def line(self) -> str | None:
        """The line a click runs; ``None`` for the record tile."""
        return None if self.preset is None else commands.preset(self.pool, self.number).text

    @property
    def prefill(self) -> str | None:
        """The record tile's pre-fill."""
        if self.preset is not None:
            return None
        return commands.record_preset_prefill(self.pool, self.number)

    def mark(self, index: int | None) -> None:
        self.marked = index is not None
        self.refresh()

    def render(self) -> Text:
        width = self.size.width
        if self.preset is None:
            text = Text("+ record", style=colors.MAGENTA)
            text.append(f"\nas {self.number}", style=colors.DIM)
        else:
            number = str(self.number)
            shown = preview(self.preset, self.mode)
            shown.truncate(max(0, width - len(number) - 1), overflow="ellipsis")
            text = Text(number, style=colors.DIM)
            text.append(" " * max(1, width - len(number) - shown.cell_len))
            text.append_text(shown)
            text.append("\n")
            text.append(self.preset.name, style=colors.FG)
        if self.marked:
            text.stylize(MARKED)
        text.no_wrap = True
        text.overflow = "ellipsis"
        return text

    def on_click(self, event: events.Click) -> None:
        event.stop()
        if self.prefill is not None:
            self.post_message(FillPrompt(self.prefill))
        else:
            self.post_message(RunLine(commands.preset(self.pool, self.number)))
