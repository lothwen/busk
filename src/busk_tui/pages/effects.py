"""F5 Effects (spec §8.5, plan Phase 3): the show's effects and the
programmer's, with their live state and wave, and the templates to add one.

EFFECTS has a row per effect a cue holds and per programmer effect
(:func:`~busk_tui.widgets.effects.effect_rows`): its cue (``9/4``) or
``prog``, its id, template, fixtures, rate and direction (``bpm x 1``,
``hz 0.25 bounce``: forward is left out), its rate now in Hz while it runs,
size (or an absolute layer's ``low–high``), phase, wings (with ``g3 b2``,
its groups and blocks, when they are not 1), a sparkline of its next cycle,
its state and ``✕``. A click on the state: a programmer effect stops or runs
again (``effect stop|run <id>``); a cue effect that runs releases its playback
(``release N``), one that does not goes to its cue (``goto N C``) on the
playback that runs its list. ``✕`` runs ``effect remove <id>``, or for a cue's
effect ``cue L/C effect <id> remove``, after the TUI's own question. A click
anywhere else on a row chooses it, and opens the EFFECT panel
(:mod:`busk_tui.widgets.effect_panel`) in the place of the templates, until its
``[done]``. ``[clear]`` runs ``effect clear``, after the same kind of question.

TEMPLATES lists every template ``effect add`` takes: the show's, then the
library's the show has no copy of (``effect add`` copies one in), with the
defaults the library gives an instance. A click adds one to the selection,
with those defaults (``effect add "<name>"``; the spec's ``bpm x1 size 0.6``
would invent values busk refuses). Its ``[edit]``, or ``[view]`` for one only
the library has, opens the TEMPLATE panel
(:mod:`busk_tui.widgets.template_panel`) in the same place, until its
``[done]``. ``[+ template…]`` makes a new one, and opens it once the show has it.

The page reads the running effects while it shows. Below 132 columns the
templates go under the effects.
"""

from __future__ import annotations

from functools import partial
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
from busk_tui.widgets.controls import ActionButton, RunLine
from busk_tui.widgets.effect_panel import EffectPanel
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
from busk_tui.widgets.template_panel import FIRST_LAYERS, NewTemplateDialog, TemplatePanel

SIDE_BY_SIDE: Final = 132
"""From this many columns the templates sit beside the effects."""

NO_EFFECTS: Final = 'no effects · select fixtures and click a template, or effect add "<name>"'

FOOTER: Final = (
    "state: a cue effect goes to its cue, or releases its playback while it runs · "
    "a programmer effect stops and runs again · ✕ removes it · any other click opens its "
    "settings · a template adds one to the selection, and its edit button opens its layers"
)


class EffectsPage(Page):
    """F5 (see the module docs)."""

    WATCH_EFFECTS: ClassVar[bool] = True

    DEFAULT_CSS = f"""
    EffectsPage #effects-row {{ height: auto; }}
    EffectsPage #effects-panel {{ width: 5fr; }}
    EffectsPage #templates-panel {{ width: 2fr; min-width: 36; }}
    EffectsPage #effects-row.stacked {{ layout: vertical; }}
    EffectsPage #effects-row.stacked > Panel {{ width: 100%; margin-left: 0; }}
    EffectsPage #effects-clear {{ margin-top: 1; }}
    EffectsPage #templates-add {{ margin-top: 1; }}
    EffectsPage #effects-footer {{ margin-top: 1; color: {colors.DIM}; }}
    EffectsPage #templates-header {{ margin-bottom: 1; }}
    """

    def __init__(self, number: int, title: str) -> None:
        super().__init__(number, title)
        self.effects = EffectTable(Text(NO_EFFECTS, style=colors.DIM), id="effect-table")
        self.templates = TemplateTable(Text("no templates", style=colors.DIM), id="template-table")
        self.header = Static("", id="templates-header")
        self.effects_panel = Panel("effects", id="effects-panel")
        self.templates_panel = Panel("templates", id="templates-panel")
        self.clear = ActionButton("clear", self.ask_clear, "danger", inert=True, id="effects-clear")
        self.add_template = ActionButton(
            "+ template…", self.ask_add_template, "go", id="templates-add"
        )
        self.panel = EffectPanel(self.close_panel)
        self.panel.display = False
        self.template_panel = TemplatePanel(self.close_panel)
        self.template_panel.display = False
        self.rows: list[FxRow] = []
        self.shown_templates: tuple[TemplateInfo, ...] = ()
        self.chosen: tuple[str, str] | None = None  # the key of the effect the panel shows
        self.chosen_template: str | None = None  # the id of the template the panel shows
        self.wanted_template: str | None = None  # a new one's name, to open once the show has it
        self._view = View()

    def compose(self) -> ComposeResult:
        with Horizontal(id="effects-row"):
            with self.effects_panel:
                yield self.effects
                yield self.clear
                yield Static(FOOTER, id="effects-footer")
            with self.templates_panel:
                yield self.header
                yield self.templates
                yield self.add_template
            yield self.panel
            yield self.template_panel

    def on_resize(self, event: events.Resize) -> None:
        self.query_one("#effects-row").set_class(event.size.width < SIDE_BY_SIDE, "stacked")

    def update_view(self, view: View, changed: frozenset[Part]) -> None:
        self._view = view
        show, programmer = view.show, view.programmer
        if changed & {"show", "programmer", "effects"}:
            self.rows = effect_rows(show, programmer, view.effects)
            self.effects.show(
                [fx_cells(row, show, view.mode) for row in self.rows], self._chosen_index()
            )
            in_cues = sum(1 for row in self.rows if row.cue is not None)
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
            self.clear.change(inert=programmer is None or not programmer.effects)
            self._draw_panel()

    # -------------------------------------------------------- the panel

    def _chosen_index(self) -> int | None:
        return next((i for i, row in enumerate(self.rows) if row.key == self.chosen), None)

    def _template_shown(self) -> TemplateInfo | None:
        """The template the panel shows; a new one, as soon as the show has it."""
        wanted = self.wanted_template
        if wanted is not None:
            for template in self.shown_templates:
                if template.name == wanted and template.source == "show":
                    self.chosen_template, self.wanted_template = template.id, None
        return next((t for t in self.shown_templates if t.id == self.chosen_template), None)

    def _draw_panel(self) -> None:
        """The chosen effect's or template's panel in the templates' place,
        or, once it is gone or the panel left, the templates."""
        index = self._chosen_index()
        row = None if index is None else self.rows[index]
        self.chosen = None if row is None else row.key
        template = self._template_shown()
        self.chosen_template = None if template is None else template.id
        self.panel.display = row is not None
        self.template_panel.display = template is not None
        self.templates_panel.display = row is None and template is None
        programmer = self._view.programmer
        selection = () if programmer is None else programmer.selection
        self.panel.show_view(row, self._view.show, selection)
        self.template_panel.show_view(template, self._view.show, programmer, self._view.mode)
        self.effects.show(self.effects.rows, index)

    def open_panel(self, key: tuple[str, str]) -> None:
        """Choose an effect. Under the effects (below :data:`SIDE_BY_SIDE`
        columns), the panel scrolls into sight."""
        self.chosen, self.chosen_template, self.wanted_template = key, None, None
        self._draw_panel()
        if self.size.width < SIDE_BY_SIDE:
            self.call_after_refresh(self.scroll_to_widget, self.panel, animate=False, top=True)

    def open_template(self, template: TemplateInfo) -> None:
        """Choose a template, as :meth:`open_panel` chooses an effect."""
        self.chosen, self.chosen_template, self.wanted_template = None, template.id, None
        self._draw_panel()
        if self.size.width < SIDE_BY_SIDE:
            self.call_after_refresh(
                self.scroll_to_widget, self.template_panel, animate=False, top=True
            )

    def close_panel(self) -> None:
        self.chosen, self.chosen_template, self.wanted_template = None, None, None
        self._draw_panel()

    # -------------------------------------------------------- the lines

    def ask_remove(self, row: FxRow) -> None:
        """``✕``: a programmer effect goes at once, a cue's after a question."""
        question = None
        if row.cue is not None:
            question = f"Remove effect {row.info.id} from cue {row.owner}?"
            if row.live is not None:
                question += " It is running, and will stop at once."
        self.post_message(RunLine(row.remove, ask=question))

    def ask_clear(self) -> None:
        """``[clear]``: every programmer effect, stopped ones too."""
        programmer = self._view.programmer
        count = 0 if programmer is None else len(programmer.effects)
        question = f"Remove {count} programmer effect{'' if count == 1 else 's'}?"
        self.post_message(RunLine(commands.effect_clear(), ask=question))

    def ask_add_template(self) -> None:
        """``[+ template…]``: ``effect template add "Beat" [{…}]``, a name and
        what its first layer is; once the show has it, its panel opens."""
        taken = [found.name for found in self.shown_templates if found.source == "show"]

        def given(found: tuple[str, str] | None) -> None:
            if found is not None:
                name, kind = found
                line = commands.effect_template_add(name, [FIRST_LAYERS[kind]])
                self.post_message(RunLine(line, done=partial(self._template_added, name)))

        self.app.push_screen(NewTemplateDialog(taken), given)

    def _template_added(self, name: str, ok: bool) -> None:
        if ok:
            self.chosen, self.chosen_template, self.wanted_template = None, None, name
            self._draw_panel()

    def on_row_table_clicked(self, message: RowTable.Clicked) -> None:
        message.stop()
        if message.table is self.effects and message.row < len(self.rows):
            row = self.rows[message.row]
            if message.cell == "state":
                if row.toggle is not None:
                    self.post_message(RunLine(row.toggle))
            elif message.cell == "remove":
                self.ask_remove(row)
            else:
                self.open_panel(row.key)
        elif message.table is self.templates and message.row < len(self.shown_templates):
            template = self.shown_templates[message.row]
            if message.cell == "edit":
                self.open_template(template)
            else:
                self.post_message(RunLine(commands.effect_add(template.name)))

    # ------------------------------------------------------ pane cursor

    def stops(self) -> list[Stop]:
        stops: list[Stop] = []
        spots: list[tuple[int, str | None]] = []
        for index, row in enumerate(self.rows):
            label = f"{row.owner} {row.info.id} settings"
            item = Item(label, action=partial(self.open_panel, row.key))
            stops.append(Stop(item, self.effects, len(spots)))
            spots.append((index, "id"))
            for name, line in (("state", row.toggle), ("remove", row.remove)):
                if line is None:
                    continue
                label = f"{row.owner} {row.info.id} {line.text}"
                if name == "remove" and row.cue is not None:
                    item = Item(label, action=partial(self.ask_remove, row))
                else:
                    item = Item(label, line=line.text)
                stops.append(Stop(item, self.effects, len(spots)))
                spots.append((index, name))
        self.effects.spots = spots
        if not self.clear.inert:
            stops.append(Stop(Item("clear", action=self.ask_clear), self.clear))
        if self.chosen is not None:
            return stops + self.panel.stops()
        if self.chosen_template is not None:
            return stops + self.template_panel.stops()
        template_spots: list[tuple[int, str | None]] = []
        for index, template in enumerate(self.shown_templates):
            line = commands.effect_add(template.name)
            item = Item(line.text, line=line.text)
            stops.append(Stop(item, self.templates, len(template_spots)))
            template_spots.append((index, None))
            word = "edit" if template.source == "show" else "view"
            item = Item(f"{word} {template.name}", action=partial(self.open_template, template))
            stops.append(Stop(item, self.templates, len(template_spots)))
            template_spots.append((index, "edit"))
        self.templates.spots = template_spots
        stops.append(
            Stop(Item(self.add_template.label, action=self.ask_add_template), self.add_template)
        )
        return stops
