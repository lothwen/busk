"""F5 Effects (spec §8.5, plan Phase 3): the show's effects and the
programmer's, with their live state and wave, and the templates to add one.

EFFECTS has a row per effect a cue holds and per programmer effect
(:func:`~busk_tui.widgets.effects.effect_rows`): its cue (``9/4``) or
``prog``, its id, template, fixtures, rate and direction (``bpm x 1``,
``hz 0.25 bounce``: forward is left out), its rate now in Hz while it runs,
size (or an absolute layer's ``low–high``), phase, wings (with ``g3 b2``,
its groups and blocks, when they are not 1), a sparkline of its next cycle,
its state and, for a programmer effect, ``✕``. A click on the state: a programmer effect stops
or runs again (``effect stop|run <id>``); a cue effect that runs releases
its playback (``release N``), one that does not goes to its cue (``goto N
C``) on the playback that runs its list. ``✕`` runs ``effect remove <id>``.

TEMPLATES lists every template ``effect add`` takes: the show's, then the
library's the show has no copy of (``effect add`` copies one in), with the
defaults the library gives an instance. A click adds one to the selection,
with those defaults (``effect add "<name>"``; the spec's ``bpm x1 size 0.6``
would invent values busk refuses).

The page reads the running effects while it shows. Below 132 columns the
templates go under the effects.
"""

from __future__ import annotations

from typing import ClassVar, Final

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.formats import selection_text
from busk_tui.model import TemplateInfo
from busk_tui.nav import Item, Stop
from busk_tui.pages.base import Page, Part, View
from busk_tui.widgets.controls import RunLine
from busk_tui.widgets.effects import (
    EffectTable,
    FxRow,
    TemplateTable,
    effect_rows,
    fx_cells,
    template_cells,
)
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.rows import RowTable

SIDE_BY_SIDE: Final = 132
"""From this many columns the templates sit beside the effects."""

NO_EFFECTS: Final = 'no effects · select fixtures and click a template, or effect add "<name>"'

FOOTER: Final = (
    "state: a cue effect goes to its cue, or releases its playback while it runs · "
    "a programmer effect stops and runs again · ✕ removes it · a template adds one to the "
    "selection"
)


class EffectsPage(Page):
    """F5 (see the module docs)."""

    WATCH_EFFECTS: ClassVar[bool] = True

    DEFAULT_CSS = f"""
    EffectsPage #effects-row {{ height: auto; }}
    EffectsPage #effects-panel {{ width: 5fr; }}
    EffectsPage #templates-panel {{ width: 2fr; min-width: 36; }}
    EffectsPage #effects-row.stacked {{ layout: vertical; }}
    EffectsPage #effects-row.stacked > Panel {{ width: 100%; }}
    EffectsPage #effects-footer {{ margin-top: 1; color: {colors.DIM}; }}
    EffectsPage #templates-header {{ margin-bottom: 1; }}
    """

    def __init__(self, number: int, title: str) -> None:
        super().__init__(number, title)
        self.effects = EffectTable(Text(NO_EFFECTS, style=colors.DIM), id="effect-table")
        self.templates = TemplateTable(Text("no templates", style=colors.DIM), id="template-table")
        self.header = Static("", id="templates-header")
        self.effects_panel = Panel("effects", id="effects-panel")
        self.rows: list[FxRow] = []
        self.shown_templates: tuple[TemplateInfo, ...] = ()

    def compose(self) -> ComposeResult:
        with Horizontal(id="effects-row"):
            with self.effects_panel:
                yield self.effects
                yield Static(FOOTER, id="effects-footer")
            with Panel("templates", id="templates-panel"):
                yield self.header
                yield self.templates

    def on_resize(self, event: events.Resize) -> None:
        self.query_one("#effects-row").set_class(event.size.width < SIDE_BY_SIDE, "stacked")

    def update_view(self, view: View, changed: frozenset[Part]) -> None:
        show, programmer = view.show, view.programmer
        if changed & {"show", "programmer", "effects"}:
            self.rows = effect_rows(show, programmer, view.effects)
            self.effects.show([fx_cells(row, show, view.mode) for row in self.rows])
            in_cues = sum(1 for row in self.rows if row.remove is None)
            meta = f"{in_cues} in cues · {len(self.rows) - in_cues} in the programmer"
            self.effects_panel.set_title("effects", meta)
        if "show" in changed:
            self.shown_templates = () if show is None else show.templates
            self.templates.show([template_cells(t) for t in self.shown_templates])
        if changed & {"show", "programmer"}:
            selection = () if programmer is None else programmer.selection
            compressed = selection_text(selection, () if show is None else show.fixtures)
            text = Text("adds to ", style=colors.DIM)
            if compressed:
                text.append(compressed, style=colors.CYAN)
                text.append(f" ({len(selection)})", style=colors.DIM)
            else:
                text.append("nothing: select fixtures first", style=colors.DIM)
            if text != self.header.content:
                self.header.update(text)

    def on_row_table_clicked(self, message: RowTable.Clicked) -> None:
        message.stop()
        if message.table is self.effects and message.row < len(self.rows):
            row = self.rows[message.row]
            if message.cell == "state" and row.toggle is not None:
                self.post_message(RunLine(row.toggle))
            elif message.cell == "remove" and row.remove is not None:
                self.post_message(RunLine(row.remove))
        elif message.table is self.templates and message.row < len(self.shown_templates):
            line = _add_line(self.shown_templates[message.row])
            if line is not None:
                self.post_message(RunLine(line))

    def stops(self) -> list[Stop]:
        stops: list[Stop] = []
        spots: list[tuple[int, str | None]] = []
        for index, row in enumerate(self.rows):
            for name, line in (("state", row.toggle), ("remove", row.remove)):
                if line is None:
                    continue
                label = f"{row.owner} {row.info.id} {line.text}"
                stops.append(Stop(Item(label, line=line.text), self.effects, len(spots)))
                spots.append((index, name))
        self.effects.spots = spots
        template_spots: list[tuple[int, str | None]] = []
        for index, template in enumerate(self.shown_templates):
            line = _add_line(template)
            if line is not None:
                item = Item(line.text, line=line.text)
                stops.append(Stop(item, self.templates, len(template_spots)))
                template_spots.append((index, None))
        self.templates.spots = template_spots
        return stops


def _add_line(template: TemplateInfo) -> commands.Line | None:
    """``effect add "<name>"``; ``None`` for a name busk cannot read (a
    double quote in it)."""
    try:
        return commands.effect_add(template.name)
    except ValueError:
        return None
