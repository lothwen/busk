"""Group buttons and colour chips (spec §8.1 SELECTION and QUICK).

A group button ``[Washes]`` runs ``sel group N``, and on a Shift-click
``sel + group N``. A colour chip ``██``, in the colour the preset gives,
runs ``preset color N``; a preset with no single colour (one per profile,
or none) is a grey ``░░``.
"""

from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text

from busk_tui import colors, commands
from busk_tui.colors import ColorMode
from busk_tui.model import GroupInfo, PresetInfo
from busk_tui.nav import Item, Stop
from busk_tui.widgets.controls import ButtonStrip, StripButton, button_label


def group_buttons(groups: Sequence[GroupInfo]) -> list[StripButton]:
    return [
        StripButton(
            button_label(group.name, colors.MID),
            commands.sel_group(group.number),
            commands.sel_group(group.number, add=True),
        )
        for group in groups
    ]


def color_chips(presets: Sequence[PresetInfo], mode: ColorMode) -> list[StripButton]:
    return [
        StripButton(
            Text("░░", style=colors.MID)
            if preset.color is None
            else Text("██", style=colors.swatch(preset.color, 1.0, mode)),
            commands.preset("color", preset.number),
        )
        for preset in presets
        if preset.pool == "color"
    ]


def strip_stops(strip: ButtonStrip) -> list[Stop]:
    """The pane cursor's stops on each button of ``strip``."""
    return [
        Stop(Item(button.line.text, line=button.line.text), strip, index)
        for index, button in enumerate(strip.buttons)
    ]
