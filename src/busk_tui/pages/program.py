"""F2 Program (spec §8.2, plan Phase 2): select, set, apply presets.

* SELECTION: the selection (``101 thru 104, 301.2``), how many elements,
  which one the encoders show, and a button per group (``sel group N``;
  Shift-click ``sel + group N``) and ``[none]`` (``sel none``).
* The encoder panels, by busk's families: INTENSITY, POSITION, COLOR
  (with the output's colour and the programmer's as swatches, the colour
  presets and ``set color …``), BEAM, FOCUS and SHUTTER (with ``set
  shutter …``). A row shows when the rig takes its attribute
  (:mod:`busk_tui.attributes`, :mod:`busk_tui.widgets.encoders`).
* quick: the configured lines, ``[highlight on|off]`` and ``[blind
  on|off]``, each a toggle that follows the programmer, and ``[fade …]``.
* PROGRAMMER CONTENTS: a row per fixture with a value
  (:mod:`busk_tui.widgets.programmer`).

The page reads the output while it shows (the encoders' dim values).
Panels go side by side at 42 columns each or more, and one under the
other below 100 columns.
"""

from __future__ import annotations

from typing import ClassVar, Final

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal
from textual.widget import Widget
from textual.widgets import Static

from busk_tui import attributes, colors, commands
from busk_tui.attributes import Encoder, Selected
from busk_tui.colors import ColorMode
from busk_tui.commands import Line
from busk_tui.formats import selection_text
from busk_tui.model import ProgrammerModel
from busk_tui.nav import Stop
from busk_tui.pages.base import Page, Part, View
from busk_tui.widgets.controls import ButtonStrip, StripButton, button_label
from busk_tui.widgets.encoders import EncoderRow
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.programmer import ProgrammerTable
from busk_tui.widgets.quick import color_chips, group_buttons, strip_stops

PANEL_WIDTH: Final = 42
"""The narrowest an encoder panel is laid out (spec §8.2)."""

NARROW: Final = 100
"""Below this many columns the panels go one under the other (spec §3)."""

SHUTTER_PREFILL: Final = commands.set_prefill("shutter")
COLOR_PREFILL: Final = commands.set_prefill("color")


def prefill_button(text: str, label: str | None = None) -> StripButton:
    """``[set color…]``: a button that puts ``text`` in the prompt."""
    shown = (text.strip() if label is None else label) + "…"
    return StripButton(button_label(shown, colors.MID), Line(text), prefill=text)


def quick_buttons(lines: tuple[str, ...], programmer: ProgrammerModel | None) -> list[StripButton]:
    """The quick lines, then the highlight and blind toggles and the fade."""
    buttons = [StripButton(button_label(line, colors.MID), Line(line)) for line in lines]
    for name, on, line in (
        ("highlight", programmer is not None and programmer.highlight, commands.highlight),
        ("blind", programmer is not None and programmer.blind, commands.blind),
    ):
        label = f"{name} {'off' if on else 'on'}"
        style = f"bold {colors.BG} on {colors.MAGENTA}" if on else colors.MAGENTA
        buttons.append(StripButton(button_label(label, style), line(not on)))
    fade = 0.0 if programmer is None else programmer.fadeTime
    buttons.append(prefill_button(commands.FADE_PREFILL, f"fade {fade:g}s"))
    return buttons


class EncoderPanel(Panel):
    """One family's encoders, and its extras (see the module docs)."""

    def __init__(self, family: str, encoders: tuple[Encoder, ...]) -> None:
        self.family = family
        self.rows = [EncoderRow(encoder) for encoder in encoders]
        children: list[Widget] = list(self.rows)
        self.swatches: Static | None = None
        self.chips: ButtonStrip | None = None
        if family == "color":
            self.swatches = Static("", classes="enc-swatches")
            self.chips = ButtonStrip(classes="enc-chips")
            children += [self.swatches, self.chips]
        elif family == "shutter":
            self.chips = ButtonStrip([prefill_button(SHUTTER_PREFILL)], classes="enc-chips")
            children.append(self.chips)
        super().__init__(family, *children)

    def show(self, view: View, chosen: Selected) -> None:
        version = None if view.programmer is None else view.programmer.version
        for row in self.rows:
            row.show(attributes.reading(row.encoder, view.show, chosen), version)
        if self.swatches is not None:
            line = color_line(chosen, view.mode)
            if line != self.swatches.content:
                self.swatches.update(line)

    def show_chips(self, view: View) -> None:
        if self.family == "color" and self.chips is not None:
            presets = () if view.show is None else view.show.presets
            self.chips.show([*color_chips(presets, view.mode), prefill_button(COLOR_PREFILL)])

    def stops(self) -> list[Stop]:
        stops: list[Stop] = []
        for row in self.rows:
            stops += row.stops()
        if self.chips is not None:
            stops += strip_stops(self.chips)
        return stops


def color_line(chosen: Selected, mode: ColorMode) -> Text:
    """The first selected element's colour: the output's, and the programmer's."""
    text = Text("output ", style=colors.DIM)
    text.append_text(_swatch(None if chosen.out is None else chosen.out.color, mode))
    text.append("  programmer ", style=colors.DIM)
    held = chosen.values.get("color")
    if held is None or not isinstance(held.value, tuple):
        text.append_text(_swatch(None, mode))
    else:
        text.append_text(_swatch(attributes.rgb(held.value), mode))
        if held.preset is not None:
            text.append(f" {held.preset}", style=colors.MAGENTA)
    if chosen.first is not None and "color" not in chosen.held:
        text.append("\nset a colour first: a chip, or set color", style=colors.DIM)
    return text


def _swatch(color: tuple[float, float, float] | None, mode: ColorMode) -> Text:
    if color is None:
        return Text("—", style=colors.DIM)
    return Text("███", style=colors.swatch(color, 1.0, mode))


class ProgramPage(Page):
    """F2 (see the module docs)."""

    WATCH_OUTPUT: ClassVar[bool] = True

    DEFAULT_CSS = f"""
    ProgramPage #program-selection {{ margin-bottom: 1; }}
    ProgramPage #encoders {{
        layout: grid; grid-size: 4; grid-columns: 1fr 1fr 1fr 1fr; grid-rows: auto;
        grid-gutter: 0 1; height: auto;
    }}
    ProgramPage #quick-row {{ height: auto; margin: 1 0; }}
    ProgramPage #quick-label {{ width: 6; color: {colors.DIM}; }}
    ProgramPage #quick {{ width: 1fr; }}
    ProgramPage .enc-swatches {{ margin-top: 1; }}
    ProgramPage .enc-chips {{ margin-top: 1; }}
    """

    def __init__(self, number: int, title: str) -> None:
        super().__init__(number, title)
        self.selection = Static("", id="program-selection")
        self.groups = ButtonStrip(id="program-groups")
        self.grid = Grid(id="encoders")
        self.panels: list[EncoderPanel] = []
        self.shape: list[tuple[str, tuple[Encoder, ...]]] | None = None
        self.quick = ButtonStrip(id="quick")
        self.table = ProgrammerTable()
        self.contents = Panel("programmer contents", self.table, id="contents")
        self.contents.styles.border_title_color = colors.MAGENTA
        self._width = 0

    def compose(self) -> ComposeResult:
        with Panel("selection"):
            yield self.selection
            yield self.groups
        yield self.grid
        with Horizontal(id="quick-row"):
            yield Static("quick", id="quick-label")
            yield self.quick
        yield self.contents

    def on_resize(self, event: events.Resize) -> None:
        self._width = event.size.width
        self._columns()

    def _columns(self) -> None:
        count = max(1, len(self.panels))
        columns = 1 if self._width < NARROW else max(1, min(count, self._width // PANEL_WIDTH))
        self.grid.styles.grid_size_columns = columns
        self.grid.styles.grid_columns = " ".join(["1fr"] * columns)

    def update_view(self, view: View, changed: frozenset[Part]) -> None:
        show, programmer = view.show, view.programmer
        if "show" in changed:
            shape = attributes.shown(show)
            if shape != self.shape:
                self.shape = shape
                self.panels = [EncoderPanel(family, rows) for family, rows in shape]
                self.grid.remove_children()
                if self.panels:
                    self.grid.mount_all(self.panels)
                else:
                    self.grid.mount(Static(Text("no fixtures to set", style=colors.DIM)))
                self._columns()
                changed = changed | {"programmer", "output"}
            for panel in self.panels:
                panel.show_chips(view)
        if changed & {"show", "programmer"}:
            self._show_selection(view)
            self.quick.show(quick_buttons(view.quick, programmer))
            self.table.show(programmer, show, view.mode)
            count = 0 if programmer is None else programmer.fixtures
            self.contents.set_title(
                "programmer contents", f"{count} fixture{'' if count == 1 else 's'}"
            )
        if changed & {"show", "programmer", "output"}:
            chosen = attributes.selected(show, programmer, view.output)
            for panel in self.panels:
                panel.show(view, chosen)

    def _show_selection(self, view: View) -> None:
        show, programmer = view.show, view.programmer
        selection = () if programmer is None else programmer.selection
        fixtures = () if show is None else show.fixtures
        text = Text()
        compressed = selection_text(selection, fixtures)
        text.append(
            compressed or "nothing selected", style=colors.CYAN if compressed else colors.DIM
        )
        if selection:
            text.append(f" ({len(selection)}", style=colors.DIM)
            text.append(" · encoders show ", style=colors.DIM)
            text.append(selection_text(selection[:1], fixtures), style=colors.CYAN)
            text.append(")", style=colors.DIM)
        self.selection.update(text)
        groups = group_buttons(() if show is None else show.groups, numbered=True)
        none = StripButton(button_label("none", colors.DIM), commands.sel_none())
        self.groups.show([*groups, none])

    def stops(self) -> list[Stop]:
        stops = strip_stops(self.groups)
        for panel in self.panels:
            stops += panel.stops()
        return stops + strip_stops(self.quick)
