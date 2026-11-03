"""F6 Presets (spec §8.6, plan Phase 2, ``docs/plans/tui-presets-plan.md``):
the preset pools as tiles, and the PRESET panel of edit mode.

A header says what a preset applies to, the selection, and has the
``[edit]`` toggle. Then a panel per pool, in the order COLOR, POSITION,
BEAM, INTENSITY, FOCUS, ALL (busk's six pools): every pool the rig can
record into (some profile of the show takes an attribute of the pool's
families), and every pool that holds presets. Each has a tile per preset
(:mod:`busk_tui.widgets.tiles`) and a last tile, ``+ record``.

Out of edit mode, a click on a tile runs ``preset <pool> N``. In edit mode
(``[edit]``, or a click on ``+ record``) a click chooses the preset for the
PRESET panel (:mod:`busk_tui.widgets.preset_panel`), which sits to the
right of the pools at 100 columns or more, else under them; ``[done]``
leaves edit mode. A preset recorded at the prompt shows at once. The page
reads the output only in edit mode (the panel's encoders' dim values).
"""

from __future__ import annotations

from functools import partial
from typing import Final

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical
from textual.widgets import Static

from busk_tui import attributes, colors
from busk_tui.colors import ColorMode
from busk_tui.formats import selection_text
from busk_tui.model import PresetInfo
from busk_tui.nav import Item, Stop
from busk_tui.pages.base import Page, Part, View
from busk_tui.widgets.controls import ActionButton
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.preset_panel import PANEL_WIDTH, Chosen, PresetPanel
from busk_tui.widgets.tiles import TILE_WIDTH, PresetTile

CHROME: Final = 6
"""The cells of a pool's width that hold no tile: the page's padding, the
panel's border and padding."""

NARROW: Final = 100
"""Below this many columns the PRESET panel goes under the pools (spec §3)."""

ABOVE: Final = 3
"""The page's rows above the PRESET panel: its padding, the header and the
gap after it."""


class PresetsPage(Page):
    """F6 (see the module docs)."""

    DEFAULT_CSS = """
    PresetsPage #presets-head { height: 1; margin-bottom: 1; }
    PresetsPage #presets-header { width: 1fr; }
    PresetsPage #presets-body { height: auto; }
    PresetsPage #pools { width: 1fr; height: auto; }
    PresetsPage .tiles {
        layout: grid; grid-size: 6; grid-columns: 1fr; grid-rows: 4; grid-gutter: 0 1;
        height: auto;
    }
    """

    def __init__(self, number: int, title: str) -> None:
        super().__init__(number, title)
        self.header = Static("", id="presets-header")
        self.edit = ActionButton("edit", self.toggle_edit, id="presets-edit")
        self.pools = Vertical(id="pools")
        self.panel = PresetPanel(self._panel_changed, self.leave_edit)
        self.panel.display = False
        self.editing = False
        self.grids: list[Grid] = []
        self.tiles: list[PresetTile] = []
        self.shape: tuple[tuple[PresetInfo, ...], tuple[str, ...], ColorMode] | None = None
        self.view: View | None = None
        self._width = 0
        self._height = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="presets-head"):
            yield self.header
            yield self.edit
        with Horizontal(id="presets-body"):
            yield self.pools
            yield self.panel

    def on_resize(self, event: events.Resize) -> None:
        self._width, self._height = event.size.width, event.size.height
        self._columns()

    def _columns(self) -> None:
        width = self._width
        beside = self._width >= NARROW
        if self.editing and beside:
            width -= PANEL_WIDTH + 1  # the panel and its margin
        columns = max(1, (width - CHROME + 1) // TILE_WIDTH)
        for grid in self.grids:
            grid.styles.grid_size_columns = columns
            grid.styles.grid_columns = " ".join(["1fr"] * columns)
        self.panel.styles.max_height = max(8, self._height - ABOVE) if beside else None

    # ------------------------------------------------------------ drawing

    def update_view(self, view: View, changed: frozenset[Part]) -> None:
        self.view = view
        show = view.show
        if changed & {"show", "programmer"}:
            self._show_header(view)
        if "show" in changed:
            presets = () if show is None else show.presets
            shape = (presets, attributes.recordable(show), view.mode)
            if shape != self.shape:
                self.shape = shape
                self._build(*shape)
        if self.editing and changed & {"show", "programmer"}:
            self.panel.show_view(show, view.programmer, view.output, view.mode)
            self._mark_chosen()
        elif self.editing and "output" in changed:
            self.panel.show_output(view.output)

    def watches(self, view: View) -> tuple[bool, bool]:
        """The output while the PRESET panel shows (its encoders' dim values)."""
        return self.editing, False

    def _show_header(self, view: View) -> None:
        show, programmer = view.show, view.programmer
        selection = () if programmer is None else programmer.selection
        compressed = selection_text(selection, () if show is None else show.fixtures)
        text = Text("applies to ", style=colors.DIM)
        if compressed:
            text.append(compressed, style=colors.CYAN)
            text.append(f" ({len(selection)})", style=colors.DIM)
        else:
            text.append("nothing: select fixtures first", style=colors.DIM)
        doing = "edit" if self.editing else "apply"
        text.append(f" · click a tile to {doing} it", style=colors.DIM)
        self.header.update(text)
        if self.editing:
            self.edit.change(label="edit ●", intent="record", reverse=True)
        else:
            self.edit.change(label="edit", intent="neutral", reverse=False)

    def _build(
        self, presets: tuple[PresetInfo, ...], recordable: tuple[str, ...], mode: ColorMode
    ) -> None:
        self.grids, self.tiles = [], []
        panels: list[Panel] = []
        for pool in attributes.POOLS:
            found = sorted((p for p in presets if p.pool == pool), key=lambda p: p.number)
            if not found and pool not in recordable:
                continue
            tiles = [PresetTile(pool, preset, preset.number, mode) for preset in found]
            tiles.append(PresetTile(pool, None, found[-1].number + 1 if found else 1, mode))
            for tile in tiles:
                tile.editing = self.editing
            self.tiles += tiles
            grid = Grid(*tiles, classes="tiles")
            self.grids.append(grid)
            panels.append(Panel(pool, grid))
        self.pools.remove_children()
        if panels:
            self.pools.mount_all(panels)
        else:
            self.pools.mount(
                Static(Text("no presets yet, and no fixture to record one for", style=colors.DIM))
            )
        self._columns()
        self._mark_chosen()

    def _mark_chosen(self) -> None:
        """The chosen preset's tile (a new one's: its pool's record tile)."""
        chosen = self.panel.chosen if self.editing else None
        for tile in self.tiles:
            if chosen is None or tile.pool != chosen.pool:
                tile.choose(False)
            elif chosen.new:
                tile.choose(tile.preset is None)
            else:
                tile.choose(tile.preset is not None and tile.number == chosen.number)

    # ---------------------------------------------------------- edit mode

    def toggle_edit(self) -> None:
        self.set_editing(not self.editing)

    def leave_edit(self) -> None:
        self.set_editing(False)

    def set_editing(self, on: bool, chosen: Chosen | None = None) -> None:
        """Enter edit mode with ``chosen`` in the PRESET panel, or leave it."""
        watching = self.editing != on
        self.editing = on
        self.panel.chosen = chosen if on else None
        self.panel.display = on
        for tile in self.tiles:
            tile.editing = on
        if self.view is not None:
            self._show_header(self.view)
            if on:
                view = self.view
                self.panel.show_view(view.show, view.programmer, view.output, view.mode)
        self._columns()
        self._mark_chosen()
        if watching:
            self.post_message(Page.WatchesChanged(self))

    def choose(self, tile: PresetTile) -> None:
        """A tile chosen in edit mode, or the record tile: into the panel."""
        if tile.preset is None:
            self.set_editing(True, Chosen(tile.pool, tile.number, new=True))
        else:
            self.set_editing(True, Chosen(tile.pool, tile.number))

    def on_preset_tile_chosen(self, message: PresetTile.Chosen) -> None:
        """A click: under the pools (below 100 columns), the panel scrolls
        into sight. (The pane cursor scrolls to what it marks itself.)"""
        message.stop()
        self.choose(message.tile)
        if self._width < NARROW:
            self.call_after_refresh(self.scroll_to_widget, self.panel, animate=False, top=True)

    def _panel_changed(self) -> None:
        self._mark_chosen()

    # -------------------------------------------------------- pane cursor

    def stops(self) -> list[Stop]:
        """The edit toggle, each tile, then the PRESET panel's controls."""
        stops = [Stop(Item("edit", action=self.toggle_edit), self.edit)]
        for tile in self.tiles:
            if tile.preset is None:
                label = f"record {tile.pool} {tile.number}"
                stops.append(Stop(Item(label, action=partial(self.choose, tile)), tile))
            elif self.editing:
                label = f"edit {tile.pool} {tile.number}"
                stops.append(Stop(Item(label, action=partial(self.choose, tile)), tile))
            elif tile.line is not None:
                stops.append(Stop(Item(tile.line, line=tile.line), tile))
        if self.editing:
            stops += self.panel.stops()
        return stops
