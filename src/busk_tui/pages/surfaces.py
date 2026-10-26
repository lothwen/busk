"""F9 Surfaces (spec §8.9, plan Phase 4, adaptation 13): the control
surfaces (MIDI, OSC, the web remote) with their state, and the bindings.

SURFACES: the light (green open, red failed, grey ignored or while no
surface is open), name, kind, how busk finds it (``"nanoKONTROL2"``, ``port
8000``), its fader pickup, how many bindings it has, and its state
(``open``, ``failed``, ``ignored``, ``not open``). Under the table, why a
surface failed or is ignored, in busk's words (``unplugged; waiting for
it``), and an open web remote's addresses, with their key.

BINDINGS: the surface, the input as ``bind`` takes it (``cc 1 48``), what it
drives (``fader 1``, ``master gm``, ``release all``), its feedback, and the
level of what it drives: a fader slot's playback on the current page, a
playback, a master (``72%``). busk does not publish the messages that come
in (GAP-13), so there is no monitor, no learn mode and no raw value.

A click on a row chooses it, and the edits under each table act on the
chosen surface (``bind "<surface>" ``, ``surface "<surface>" pickup ``) and
binding (``unbind "<surface>" cc 1 48``, whole, and ``feedback …``), put
in the prompt to finish.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Final

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.commands import Line
from busk_tui.model import BindingInfo, LiveState, ShowModel, SurfaceView
from busk_tui.nav import Item, Stop
from busk_tui.pages.base import Page, Part, View
from busk_tui.widgets.controls import ButtonStrip, StripButton, button_label
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.quick import strip_stops
from busk_tui.widgets.rows import Cells, Column, RowTable, cell

SIDE_BY_SIDE: Final = 132
"""From this many columns the bindings sit beside the surfaces."""

NO_SURFACES: Final = 'no surfaces · surface add midi "<device>", or surface add web "Phone"'
NO_BINDINGS: Final = 'no bindings · bind "<surface>" cc 1 0 fader 1'

NONE: Final = "—"


class SurfaceTable(RowTable):
    COLUMNS = (
        Column("light", "", 1),
        Column("name", "name", 10, flex=True),
        Column("kind", "kind", 4),
        Column("device", "device", 14, drop=3),
        Column("pickup", "pickup", 6, drop=4),
        Column("binds", "binds", 5, right=True),
        Column("state", "state", 8, flex=True),
    )


class BindingTable(RowTable):
    COLUMNS = (
        Column("surface", "surface", 10, flex=True, drop=3),
        Column("input", "input", 9, flex=True),
        Column("what", "what", 12, flex=True),
        Column("feedback", "feedback", 8, drop=2),
        Column("level", "val", 4, right=True, drop=1),
    )


def surface_cells(surface: SurfaceView, bindings: int) -> Cells:
    if surface.state == "ok":
        light, state = cell("●", colors.GREEN), cell("open", colors.GREEN)
    elif surface.state == "failed":
        light, state = cell("●", colors.RED), cell("failed", colors.RED)
    else:  # ignored, or no surface is open
        light, state = cell("○", colors.BORDER), cell(surface.state or "not open", colors.DIM)
    return {
        "light": light,
        "name": cell(surface.name, colors.FG),
        "kind": cell(surface.kind, colors.DIM),
        "device": cell(surface.device, colors.MID),
        "pickup": cell(surface.pickup, colors.MID),
        "binds": cell(str(bindings), colors.MID),
        "state": state,
    }


def binding_level(
    binding: BindingInfo, show: ShowModel | None, live: LiveState | None
) -> float | None:
    """The level of what ``binding`` drives: the playback in its fader slot
    on the current page, its playback, its master; ``None`` for the rest."""
    if binding.target is None or show is None or live is None:
        return None
    kind, which = binding.target
    if kind == "master":
        return next((m.level for m in live.masters if m.name == which), None)
    number = which if kind == "playback" and isinstance(which, int) else None
    if kind == "slot" and isinstance(which, int):
        current = None if live.page is None else live.page.number
        page = next((page for page in show.pages if page.number == current), None)
        number = None if page is None or which >= len(page.slots) else page.slots[which]
    playback = None if number is None else live.playback(number)
    return None if playback is None else playback.level


def binding_cells(binding: BindingInfo, level: float | None) -> Cells:
    return {
        "surface": cell(binding.surface, colors.MID),
        "input": cell(binding.input, colors.FG),
        "what": cell(binding.what, colors.AMBER),
        "feedback": cell(binding.feedback, colors.DIM)
        if binding.feedback
        else cell("", colors.DIM),
        "level": cell(NONE if level is None else f"{round(level * 100)}%", colors.DIM),
    }


def notes_text(surfaces: tuple[SurfaceView, ...]) -> Text:
    """Why a surface failed (red) or is ignored, as busk says it, and each
    open web remote's addresses, to open on a phone."""
    lines: list[Text] = []
    for surface in surfaces:
        if surface.detail:
            style = colors.RED if surface.state == "failed" else colors.DIM
            lines.append(Text.assemble((f"{surface.name}  ", colors.DIM), (surface.detail, style)))
        lines += [
            Text.assemble((f"{surface.name}  ", colors.DIM), (url, colors.CYAN))
            for url in surface.urls
        ]
    return Text("\n").join(lines)


class SurfacesPage(Page):
    """F9 (see the module docs)."""

    DEFAULT_CSS = """
    SurfacesPage #surfaces-row { height: auto; }
    SurfacesPage #surfaces-panel { width: 2fr; }
    SurfacesPage #bindings-panel { width: 3fr; }
    SurfacesPage #surfaces-row.stacked { layout: vertical; }
    SurfacesPage #surfaces-row.stacked > Panel { width: 100%; }
    SurfacesPage #surface-notes { margin-top: 1; height: auto; }
    SurfacesPage .edit-row { height: auto; margin-top: 1; }
    SurfacesPage .edit-label { width: auto; padding-right: 1; }
    SurfacesPage .edit-strip { width: 1fr; }
    """

    def __init__(self, number: int, title: str) -> None:
        super().__init__(number, title)
        self.surfaces = SurfaceTable(Text(NO_SURFACES, style=colors.DIM), id="surface-table")
        self.bindings = BindingTable(Text(NO_BINDINGS, style=colors.DIM), id="binding-table")
        self.notes = Static("", id="surface-notes")
        self.surface_label = Static("", classes="edit-label")
        self.surface_edits = ButtonStrip(id="surface-edits", classes="edit-strip")
        self.binding_label = Static("", classes="edit-label")
        self.binding_edits = ButtonStrip(id="binding-edits", classes="edit-strip")
        self.surfaces_panel = Panel("surfaces", id="surfaces-panel")
        self.bindings_panel = Panel("bindings", id="bindings-panel")
        self.surface: str | None = None  # the chosen surface's name
        self.binding: int | None = None  # the chosen binding's row
        self.shown_surfaces: tuple[SurfaceView, ...] = ()
        self.shown_bindings: tuple[BindingInfo, ...] = ()
        self._view = View()

    def compose(self) -> ComposeResult:
        with Horizontal(id="surfaces-row"):
            with self.surfaces_panel:
                yield self.surfaces
                yield self.notes
                with Horizontal(classes="edit-row"):
                    yield self.surface_label
                    yield self.surface_edits
            with self.bindings_panel:
                yield self.bindings
                with Horizontal(classes="edit-row"):
                    yield self.binding_label
                    yield self.binding_edits

    def on_resize(self, event: events.Resize) -> None:
        self.query_one("#surfaces-row").set_class(event.size.width < SIDE_BY_SIDE, "stacked")

    def update_view(self, view: View, changed: frozenset[Part]) -> None:
        self._view = view
        if changed & {"show", "surfaces"}:
            self._draw_surfaces()
        if changed & {"show", "live"}:
            self._draw_bindings()

    # ------------------------------------------------------------- draw

    def _draw_surfaces(self) -> None:
        show = self._view.show
        bindings = () if show is None else show.bindings
        self.shown_surfaces = self._view.surfaces
        self.surfaces.show(
            [
                surface_cells(s, sum(1 for b in bindings if b.surface == s.name))
                for s in self.shown_surfaces
            ]
        )
        notes = notes_text(self.shown_surfaces)
        self.notes.display = bool(notes)
        if notes != self.notes.content:
            self.notes.update(notes)
        self.surfaces_panel.set_title("surfaces", str(len(self.shown_surfaces)))
        self._draw_surface_edits()

    def _draw_bindings(self) -> None:
        show, live = self._view.show, self._view.live
        bindings = () if show is None else show.bindings
        new = bindings != self.shown_bindings
        if new:
            self.binding, self.shown_bindings = None, bindings
        rows = [binding_cells(b, binding_level(b, show, live)) for b in bindings]
        self.bindings.show(rows, self.binding)
        if new:  # the levels change with the live state, the rest with the show
            self.bindings_panel.set_title("bindings", str(len(bindings)))
            self._draw_binding_edits()

    def chosen_surface(self) -> SurfaceView | None:
        """The surface clicked last, else the first."""
        found = next((s for s in self.shown_surfaces if s.name == self.surface), None)
        return found or (self.shown_surfaces[0] if self.shown_surfaces else None)

    def _draw_surface_edits(self) -> None:
        surface = self.chosen_surface()
        prefills = [] if surface is None else _prefills(
            ("bind", commands.bind_prefill, (surface.name,)),
            ("pickup", commands.pickup_prefill, (surface.name,)),
        )  # fmt: skip
        label = Text()
        if surface is not None and prefills:
            label = Text.assemble(("edit ", colors.DIM), (f'"{surface.name}"', colors.CYAN))
        _update(self.surface_label, label)
        self.surface_edits.show(_buttons(prefills))

    def _draw_binding_edits(self) -> None:
        binding = None if self.binding is None else self.shown_bindings[self.binding]
        prefills: list[tuple[str, str]] = []
        if binding is not None and binding.kind in ("cc", "note", "osc"):
            prefills = _prefills(
                ("unbind", commands.unbind_prefill, (binding.surface, binding.input)),
                ("feedback", commands.feedback_prefill, (binding.surface, binding.input)),
            )
        label = Text()
        if binding is not None:
            label = Text.assemble(
                ("edit ", colors.DIM), (binding.input, colors.CYAN), (" on ", colors.DIM),
                (f'"{binding.surface}"', colors.FG),
            )  # fmt: skip
        _update(self.binding_label, label)
        self.binding_edits.show(_buttons(prefills))

    # ----------------------------------------------------------- clicks

    def on_row_table_clicked(self, message: RowTable.Clicked) -> None:
        message.stop()
        if message.table is self.surfaces and message.row < len(self.shown_surfaces):
            self.choose_surface(self.shown_surfaces[message.row].name)
        elif message.table is self.bindings and message.row < len(self.shown_bindings):
            self.choose_binding(message.row)

    def choose_surface(self, name: str) -> None:
        self.surface = name
        self._draw_surface_edits()

    def choose_binding(self, row: int) -> None:
        self.binding = row
        self._draw_bindings()
        self._draw_binding_edits()

    # ----------------------------------------------------- pane cursor

    def stops(self) -> list[Stop]:
        stops: list[Stop] = []
        self.surfaces.spots = [(row, None) for row in range(len(self.shown_surfaces))]
        for row, surface in enumerate(self.shown_surfaces):
            item = Item(
                f"surface {surface.name}", action=partial(self.choose_surface, surface.name)
            )
            stops.append(Stop(item, self.surfaces, row))
        stops += strip_stops(self.surface_edits)
        self.bindings.spots = [(row, None) for row in range(len(self.shown_bindings))]
        for row, binding in enumerate(self.shown_bindings):
            label = f"binding {binding.surface} {binding.input} {binding.what}"
            stops.append(
                Stop(Item(label, action=partial(self.choose_binding, row)), self.bindings, row)
            )
        return stops + strip_stops(self.binding_edits)


def _prefills(*wanted: tuple[str, Callable[..., str], tuple[str, ...]]) -> list[tuple[str, str]]:
    """Each ``(name, builder, arguments)`` as ``(name, pre-fill)``, leaving
    out those busk cannot read (a name with a double quote)."""
    found = []
    for name, builder, arguments in wanted:
        try:
            found.append((name, builder(*arguments)))
        except ValueError:
            continue
    return found


def _buttons(prefills: list[tuple[str, str]]) -> list[StripButton]:
    return [
        StripButton(button_label(f"{name}…", colors.MID), Line(text), prefill=text)
        for name, text in prefills
    ]


def _update(widget: Static, text: Text) -> None:
    if text != widget.content:
        widget.update(text)
