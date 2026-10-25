"""F6 Presets (spec §8.6, plan Phase 2): the preset pools as tiles.

A header says what a preset applies to: the selection. Then a panel per
pool that has presets, in the order COLOR, POSITION, BEAM, INTENSITY,
FOCUS, ALL (busk's six pools), with a tile per preset
(:mod:`busk_tui.widgets.tiles`) and a last tile to record the next one.
A click on a tile runs ``preset <pool> N``. A preset recorded at the prompt
shows at once.
"""

from __future__ import annotations

from typing import Final

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Grid, Vertical
from textual.widgets import Static

from busk_tui import colors
from busk_tui.colors import ColorMode
from busk_tui.formats import selection_text
from busk_tui.model import PresetInfo
from busk_tui.nav import Item, Stop
from busk_tui.pages.base import Page, Part, View
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.tiles import TILE_WIDTH, PresetTile

POOLS: Final = ("color", "position", "beam", "intensity", "focus", "all")
"""busk's preset pools, in the order shown (spec §8.6's four first)."""

CHROME: Final = 6
"""The cells of a pool's width that hold no tile: the page's padding, the
panel's border and padding."""


class PresetsPage(Page):
    """F6 (see the module docs)."""

    DEFAULT_CSS = """
    PresetsPage #presets-header { margin-bottom: 1; }
    PresetsPage #pools { height: auto; }
    PresetsPage .tiles {
        layout: grid; grid-size: 6; grid-columns: 1fr; grid-rows: 4; grid-gutter: 0 1;
        height: auto;
    }
    """

    def __init__(self, number: int, title: str) -> None:
        super().__init__(number, title)
        self.header = Static("", id="presets-header")
        self.pools = Vertical(id="pools")
        self.grids: list[Grid] = []
        self.tiles: list[PresetTile] = []
        self.shape: tuple[tuple[PresetInfo, ...], ColorMode] | None = None
        self._width = 0

    def compose(self) -> ComposeResult:
        yield self.header
        yield self.pools

    def on_resize(self, event: events.Resize) -> None:
        self._width = event.size.width
        self._columns()

    def _columns(self) -> None:
        columns = max(1, (self._width - CHROME + 1) // TILE_WIDTH)
        for grid in self.grids:
            grid.styles.grid_size_columns = columns
            grid.styles.grid_columns = " ".join(["1fr"] * columns)

    def update_view(self, view: View, changed: frozenset[Part]) -> None:
        show, programmer = view.show, view.programmer
        if changed & {"show", "programmer"}:
            selection = () if programmer is None else programmer.selection
            compressed = selection_text(selection, () if show is None else show.fixtures)
            text = Text("applies to ", style=colors.DIM)
            if compressed:
                text.append(compressed, style=colors.CYAN)
                text.append(f" ({len(selection)})", style=colors.DIM)
            else:
                text.append("nothing: select fixtures first", style=colors.DIM)
            text.append(" · click = preset <pool> N", style=colors.DIM)
            self.header.update(text)
        if "show" in changed:
            presets = () if show is None else show.presets
            shape = (presets, view.mode)
            if shape != self.shape:
                self.shape = shape
                self._build(presets, view.mode)

    def _build(self, presets: tuple[PresetInfo, ...], mode: ColorMode) -> None:
        self.grids, self.tiles = [], []
        panels: list[Panel] = []
        for pool in POOLS:
            found = sorted((p for p in presets if p.pool == pool), key=lambda p: p.number)
            if not found:
                continue
            tiles = [PresetTile(pool, preset, preset.number, mode) for preset in found]
            tiles.append(PresetTile(pool, None, found[-1].number + 1, mode))
            self.tiles += tiles
            grid = Grid(*tiles, classes="tiles")
            self.grids.append(grid)
            panels.append(Panel(pool, grid))
        self.pools.remove_children()
        if panels:
            self.pools.mount_all(panels)
        else:
            self.pools.mount(
                Static(
                    Text(
                        "no presets yet · select fixtures, set a look, then record preset "
                        '<pool> N "name"',
                        style=colors.DIM,
                    )
                )
            )
        self._columns()

    def stops(self) -> list[Stop]:
        stops: list[Stop] = []
        for tile in self.tiles:
            if tile.line is not None:
                stops.append(Stop(Item(tile.line, line=tile.line), tile))
            elif tile.prefill is not None:
                stops.append(Stop(Item(tile.prefill.strip(), prefill=tile.prefill), tile))
        return stops
