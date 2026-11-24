"""F9 Surfaces (spec §8.9, plan Phase 4, adaptation 13): the control
surfaces (MIDI, OSC, the web remote) with their state, what comes in from
them, and the bindings.

SURFACES: the light (green open, red failed, grey ignored or while no
surface is open), name, kind, how busk finds it (``"nanoKONTROL2"``, ``port
8000``), its fader pickup, how many bindings it has, and its state
(``open``, ``failed``, ``ignored``, ``not open``). Under the table, why a
surface failed or is ignored, in busk's words (``unplugged; waiting for
it``), and an open web remote's addresses, with their key.

MONITOR (busk's GAP-13, pending plan Phase 37): the newest inputs that came
in, newest at the bottom, each with its control as ``bind`` takes it, the
number the device sent, what it drives (``→ fader 1``; ``→ —``, dim, when
nothing) and its surface. Inputs in a row from one control replace its line
(spec §8.9), so a fader sweep is one line that moves. busk keeps the newest
64; the page keeps its own :data:`MONITOR_LINES`, read only while it shows.

BINDINGS: the surface, the input as ``bind`` takes it (``cc 1 48``), what it
drives (``fader 1``, ``master gm``, ``release all``), its feedback, the last
number its control sent (``in``) and the level of what it drives (``val``):
a fader slot's playback on the current page, a playback, a master
(``72%``). With soft pickup the two differ until the fader picks up.

A click on a row chooses it, and the strips under the tables act on it.
SURFACES' (pending plan Phase 39): ``[+ surface…]``, the surface form
(:mod:`busk_tui.widgets.surface_dialog`), which sends ``surface add …``;
then for the chosen surface its pickup, ``[soft]`` ``[jump]``, its own lit,
a click sending ``surface "Touch" pickup soft``; ``[edit…]``, the form
filled in, its kind fixed, which sends ``surface "Touch" change …``;
``[rename…]``; ``[delete]``, ``delete surface "Touch" cascade``, after
busk's question, which counts the bindings that go; and ``[+ binding…]``
(Phase 41), the binding form (:mod:`busk_tui.widgets.binding_dialog`), which
sends ``bind "Touch" …``. A surface busk does not open (``hid``,
``internal``) has ``[rename…]`` and ``[delete]`` alone, and a web remote,
which sends commands of its own, no ``[learn]``: their ``[+ binding…]`` is
grey, and says why under the mouse. The choice follows a surface renamed,
and goes to one just added.

BINDINGS' strip (Phase 41), for the chosen binding: ``[edit…]``, the form
filled in, which sends ``binding <id> change …`` (busk's GAP-63), and
nothing when nothing changed; ``[learn]``, which moves it (below); and
``[delete]``, ``delete binding <id>``, after the TUI's question, since busk
asks none. A binding the form cannot word, one from a show file (a pitch
bend's, a command but ``release all`` and ``output``, one on a web remote),
has ``[delete]`` alone that works: its ``[edit…]`` and ``[learn]`` are grey,
and say why under the mouse. The choice follows the binding through its
edits, by its id.

**Learn mode**: ``[learn]`` among the surface's edits arms it, lit amber;
the next input from that surface puts ``bind "<surface>" cc 1 48 `` in the
prompt, for the operator to finish with what it drives, and disarms. A
control that has bindings says so in the hint row, since ``bind`` adds
beside them. A pitch bend, which ``bind`` cannot take, and the clock, which
a device sends on its own, are passed over. Esc, a second click, another
surface or another page disarms it. A binding's ``[learn]`` arms the same
way, and the next control from its surface other than its own moves the
binding there, in one line, what it drives and its feedback kept (the
spec's learn mode on a binding row). One learn mode is armed at a time. The
binding form's ``[learn]`` hears through the page, which reads the inputs
while the form is open over it.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Final

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.commands import Line
from busk_tui.model import BindingInfo, InputView, LiveState, ShowModel, SurfaceView
from busk_tui.nav import Item, Stop
from busk_tui.pages.base import Page, Part, View
from busk_tui.widgets.binding_dialog import (
    CONTROLS,
    LEARN_LIT,
    PASSED_OVER,
    BindingDialog,
    binding_words,
    control_parts,
    unworded,
)
from busk_tui.widgets.controls import (
    ButtonStrip,
    FillPrompt,
    RunLine,
    StripButton,
    button_label,
)
from busk_tui.widgets.dialogs import TextDialog
from busk_tui.widgets.fixture_panel import chips
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.quick import strip_stops
from busk_tui.widgets.rows import Cells, Column, RowTable, cell
from busk_tui.widgets.surface_dialog import SurfaceDialog, check_surface_name

SIDE_BY_SIDE: Final = 132
"""From this many columns the bindings sit beside the surfaces."""

NO_SURFACES: Final = "no surfaces · [+ surface…]"
NO_BINDINGS: Final = "no bindings · a surface's [+ binding…] adds one"

NONE: Final = "—"

MONITOR_LINES: Final = 14
"""How many lines MONITOR keeps (spec §8.9)."""

NO_INPUTS: Final = "messages show here as they come in"
NOT_OPEN: Final = f"no surface is open: {NO_INPUTS}"

UNBOUND: Final = {
    "web": "a web remote sends commands of its own: a binding on it does nothing",
    "hid": "busk does not open a hid surface: a binding on it does nothing",
    "internal": "busk does not open an internal surface: a binding on it does nothing",
}
"""Why a surface of each kind that takes no binding has ``[+ binding…]`` grey."""

IGNORED: Final = frozenset({"hid", "internal"})
"""The kinds of surface busk does not open: renamed and deleted alone."""

PICKUPS: Final = ("soft", "jump")


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


class MonitorTable(RowTable):
    COLUMNS = (
        Column("input", "input", 9, flex=True),
        Column("sent", "in", 5, right=True),
        Column("drives", "drives", 12, flex=True),
        Column("surface", "surface", 10, flex=True, drop=1),
    )


class BindingTable(RowTable):
    COLUMNS = (
        Column("surface", "surface", 10, flex=True, drop=3),
        Column("input", "input", 9, flex=True),
        Column("what", "what", 12, flex=True),
        Column("feedback", "feedback", 8, drop=2),
        Column("sent", "in", 5, right=True, drop=1),
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


def binding_cells(binding: BindingInfo, level: float | None, sent: InputView | None) -> Cells:
    """A binding's row; ``sent`` is the last input from its control."""
    return {
        "surface": cell(binding.surface, colors.MID),
        "input": cell(binding.input, colors.FG),
        "what": cell(binding.what, colors.AMBER),
        "feedback": cell(binding.feedback, colors.DIM)
        if binding.feedback
        else cell("", colors.DIM),
        "sent": cell(NONE if sent is None else sent.sent, colors.MID),
        "level": cell(NONE if level is None else f"{round(level * 100)}%", colors.DIM),
    }


def merged(lines: tuple[InputView, ...], new: list[InputView]) -> tuple[InputView, ...]:
    """MONITOR's lines with ``new`` inputs after them: an input from the
    control of the last line replaces it (spec §8.9); the newest
    :data:`MONITOR_LINES`."""
    kept = list(lines)
    for heard in new:
        if kept and (kept[-1].surface, kept[-1].input) == (heard.surface, heard.input):
            kept[-1] = heard
        else:
            kept.append(heard)
    return tuple(kept[-MONITOR_LINES:])


def monitor_cells(heard: InputView) -> Cells:
    """``cc 1 48  102  → fader 1  APC mini mk2``; an unbound control's
    ``→ —`` dim."""
    drives = (
        cell(f"→ {', '.join(heard.drives)}", colors.AMBER)
        if heard.drives
        else cell(f"→ {NONE}", colors.DIM)
    )
    return {
        "input": cell(heard.input, colors.FG),
        "sent": cell(heard.sent, colors.MID),
        "drives": drives,
        "surface": cell(heard.surface, colors.DIM),
    }


def learnable(
    new: list[InputView], surface: str, own: tuple[str, int | None, str] | None = None
) -> InputView | None:
    """The first of ``new`` that learn mode takes from ``surface``: not one
    it passes over, nor the control ``own`` (a binding's: it moves
    elsewhere)."""
    return next(
        (
            heard
            for heard in new
            if heard.surface == surface
            and heard.input.split()[0] not in PASSED_OVER
            and (own is None or control_parts(heard.input) != own)
        ),
        None,
    )


def learned_note(heard: InputView) -> str | None:
    """What the hint row says when learn mode takes a control that has
    bindings: ``bind`` adds beside them."""
    if not heard.drives:
        return None
    return f"{heard.input} drives {', '.join(heard.drives)}: unbind it to replace it"


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
    SurfacesPage #surfaces-column { width: 2fr; height: auto; }
    SurfacesPage #bindings-panel { width: 3fr; }
    SurfacesPage #surfaces-row.stacked { layout: vertical; }
    SurfacesPage #surfaces-row.stacked > * { width: 100%; }
    SurfacesPage #surface-notes { margin-top: 1; height: auto; }
    SurfacesPage .edit-row { height: auto; margin-top: 1; }
    SurfacesPage .edit-label { width: auto; padding-right: 1; }
    SurfacesPage .edit-strip { width: 1fr; }
    """

    WATCH_INPUTS = True

    def __init__(self, number: int, title: str) -> None:
        super().__init__(number, title)
        self.surfaces = SurfaceTable(Text(NO_SURFACES, style=colors.DIM), id="surface-table")
        self.monitor = MonitorTable(Text(NOT_OPEN, style=colors.DIM), id="monitor-table")
        self.bindings = BindingTable(Text(NO_BINDINGS, style=colors.DIM), id="binding-table")
        self.notes = Static("", id="surface-notes")
        self.surface_edits = ButtonStrip(id="surface-edits", classes="edit-strip")
        self.binding_label = Static("", classes="edit-label")
        self.binding_edits = ButtonStrip(id="binding-edits", classes="edit-strip")
        self.surfaces_panel = Panel("surfaces", id="surfaces-panel")
        self.monitor_panel = Panel("monitor", id="monitor-panel")
        self.bindings_panel = Panel("bindings", id="bindings-panel")
        self.surface: str | None = None  # the chosen surface's name
        self.binding: int | None = None  # the chosen binding's row
        self.shown_surfaces: tuple[SurfaceView, ...] = ()
        self.shown_bindings: tuple[BindingInfo, ...] = ()
        self.heard: tuple[InputView, ...] = ()  # MONITOR's lines, oldest first
        self.last_sent: dict[tuple[str, str], InputView] = {}  # (surface, input) → the newest
        self.learning = False  # learn mode, armed on the chosen surface
        self.moving = False  # learn mode, armed on the chosen binding: it moves
        self.form: BindingDialog | None = None  # the binding form, while it is open
        self._seq = 0  # the newest input taken
        self._view = View()

    def compose(self) -> ComposeResult:
        with Horizontal(id="surfaces-row"):
            with Vertical(id="surfaces-column"):
                with self.surfaces_panel:
                    yield self.surfaces
                    yield self.notes
                    with Horizontal(classes="edit-row"):
                        yield self.surface_edits
                with self.monitor_panel:
                    yield self.monitor
            with self.bindings_panel:
                yield self.bindings
                with Horizontal(classes="edit-row"):
                    yield self.binding_label
                    yield self.binding_edits

    def on_resize(self, event: events.Resize) -> None:
        self.query_one("#surfaces-row").set_class(event.size.width < SIDE_BY_SIDE, "stacked")

    def update_view(self, view: View, changed: frozenset[Part]) -> None:
        self._view = view
        if "inputs" in changed:
            self._take_inputs()
        if changed & {"show", "surfaces"}:
            self._draw_surfaces()
        if changed & {"surfaces", "inputs"}:
            self._draw_monitor()
        if changed & {"show", "live", "inputs"}:
            self._draw_bindings()

    def _take_inputs(self) -> None:
        """The inputs past the newest taken: MONITOR's lines, each
        control's last, and learn mode's control."""
        new = [heard for heard in self._view.inputs if heard.seq > self._seq]
        if not new:
            return
        self._seq = new[-1].seq
        self.heard = merged(self.heard, new)
        for heard in new:
            self.last_sent[heard.surface, heard.input] = heard
        surface, binding = self.chosen_surface(), self.chosen_binding()
        if self.learning and surface is not None:
            learned = learnable(new, surface.name)
            if learned is not None:
                self._disarm()
                text = commands.learned_prefill(surface.name, learned.input)
                self.post_message(FillPrompt(text, learned_note(learned)))
        if self.moving and binding is not None:
            own = (binding.kind, binding.channel, binding.number)
            learned = learnable(new, binding.surface, own)
            if learned is not None:
                self._disarm()
                masters = () if self._view.show is None else self._view.show.masters
                words = binding_words(binding, masters, learned.input)
                self.post_message(RunLine(commands.binding_change(binding.id, words)))
        if self.form is not None and self.form.learning:
            learned = learnable(new, self.form.surface.name)
            if learned is not None:
                self.form.learned(learned)

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
        self._draw_binding_edits()  # what the form can word depends on the surface's kind

    def _draw_monitor(self) -> None:
        open_ = any(surface.state == "ok" for surface in self._view.surfaces)
        empty = Text(NO_INPUTS if open_ else NOT_OPEN, style=colors.DIM)
        self.monitor.show([monitor_cells(heard) for heard in self.heard], empty=empty)

    def _draw_bindings(self) -> None:
        show, live = self._view.show, self._view.live
        bindings = () if show is None else show.bindings
        new = bindings != self.shown_bindings
        if new:  # the choice follows its binding by id, as an edit or a move leaves it
            chosen = self.chosen_binding()
            self.binding, self.shown_bindings = None, bindings
            if chosen is not None and chosen.id:
                ids = [binding.id for binding in bindings]
                self.binding = ids.index(chosen.id) if chosen.id in ids else None
            if self.binding is None:
                self.moving = False
        rows = [
            binding_cells(b, binding_level(b, show, live), self.last_sent.get((b.surface, b.input)))
            for b in bindings
        ]
        self.bindings.show(rows, self.binding)
        if new:  # the levels change with the live state, the rest with the show
            self.bindings_panel.set_title("bindings", str(len(bindings)))
            self._draw_binding_edits()

    def chosen_surface(self) -> SurfaceView | None:
        """The surface clicked last, else the first."""
        found = next((s for s in self.shown_surfaces if s.name == self.surface), None)
        return found or (self.shown_surfaces[0] if self.shown_surfaces else None)

    def chosen_binding(self) -> BindingInfo | None:
        return None if self.binding is None else self.shown_bindings[self.binding]

    def surface_of(self, binding: BindingInfo) -> SurfaceView | None:
        return next((s for s in self.shown_surfaces if s.name == binding.surface), None)

    def _draw_surface_edits(self) -> None:
        """``[+ surface…]``, then the chosen surface's name and edits."""
        buttons = [_ask("+ surface…", self.ask_add)]
        surface = self.chosen_surface()
        if surface is None:
            self.surface_edits.show(buttons)
            return
        name = surface.name
        buttons.append(
            StripButton(Text(commands.quoted(name), style=colors.CYAN), Line(""), note=True)
        )
        if surface.kind not in IGNORED:
            buttons += chips(PICKUPS, surface.pickup, partial(commands.surface_pickup, name))
            buttons.append(_ask("edit…", self.ask_edit))
        buttons += [
            _ask("rename…", self.ask_name),
            StripButton(button_label("delete", colors.RED), commands.delete_surface(name)),
        ]
        if surface.kind in CONTROLS:
            buttons += [
                _ask("+ binding…", self.ask_bind),
                _learn(self.learning, self.toggle_learn),
            ]
        else:
            buttons.append(_grey("+ binding…", UNBOUND.get(surface.kind, "")))
        self.surface_edits.show(buttons)

    # ------------------------------------------------------------ forms

    def ask_add(self) -> None:
        """``[+ surface…]``: the form, then ``surface add …``; the new surface
        is chosen once busk has it."""
        dialog = SurfaceDialog(self.shown_surfaces)

        def given(line: Line | None) -> None:
            if line is not None:
                self.post_message(RunLine(line, done=partial(self._follow, dialog.new_name())))

        self.app.push_screen(dialog, given)

    def ask_edit(self) -> None:
        """``[edit…]``: the form, filled in with how busk finds the chosen
        surface: ``surface "Touch" change …``. A form that changes nothing
        sends nothing."""
        surface = self.chosen_surface()
        if surface is None:
            return

        def given(line: Line | None) -> None:
            if line is not None:
                self.post_message(RunLine(line))

        self.app.push_screen(SurfaceDialog(self.shown_surfaces, surface), given)

    def ask_name(self) -> None:
        """``[rename…]``: ``rename surface "Touch" "Pad"``; nothing for the
        name it has. The choice follows it."""
        surface = self.chosen_surface()
        if surface is None:
            return

        def given(text: str | None) -> None:
            name = None if text is None else text.strip()
            if name is not None and name != surface.name:
                line = commands.rename_surface(surface.name, name)
                self.post_message(RunLine(line, done=partial(self._follow, name)))

        names = [other.name for other in self.shown_surfaces]
        check = check_surface_name(names, surface.name)
        self.app.push_screen(TextDialog("RENAME SURFACE", surface.name, check), given)

    def _follow(self, name: str, ok: bool) -> None:
        """Choose the surface a line named, once busk took the line."""
        if ok:
            self.choose_surface(name)

    def ask_bind(self) -> None:
        """``[+ binding…]``: the binding form on the chosen surface, then
        ``bind "Touch" …``."""
        surface = self.chosen_surface()
        if surface is not None:
            self._open_form(BindingDialog(surface, self._view.show))

    def ask_edit_binding(self) -> None:
        """A binding's ``[edit…]``: the form, filled in with the chosen
        binding: ``binding <id> change …``. A form that changes nothing sends
        nothing."""
        binding = self.chosen_binding()
        surface = None if binding is None else self.surface_of(binding)
        if binding is not None and surface is not None:
            self._open_form(BindingDialog(surface, self._view.show, binding))

    def _open_form(self, dialog: BindingDialog) -> None:
        """The binding form, which hears the inputs through the page while it
        is open; one learn mode at a time."""
        self._disarm()
        self.form = dialog

        def given(line: Line | None) -> None:
            self.form = None
            if line is not None:
                self.post_message(RunLine(line))

        self.app.push_screen(dialog, given)

    def ask_delete_binding(self) -> None:
        """A binding's ``[delete]``: ``delete binding <id>``, after the TUI's
        question, since busk asks none."""
        binding = self.chosen_binding()
        if binding is None:
            return
        on = commands.quoted(binding.surface)
        question = f"Delete binding {binding.input} → {binding.what} on {on}?"
        self.post_message(RunLine(commands.delete_binding(binding.id), ask=question))

    # ------------------------------------------------------------ learn

    def toggle_learn(self) -> None:
        """The surface's ``[learn]``: arm learn mode on the chosen surface,
        or disarm it."""
        if self.learning:
            self._disarm()
        elif self.chosen_surface() is not None:
            self._disarm()
            self.learning = True
            self._draw_surface_edits()

    def toggle_move(self) -> None:
        """A binding's ``[learn]``: arm learn mode on the chosen binding, to
        move it, or disarm it."""
        if self.moving:
            self._disarm()
        elif self.chosen_binding() is not None:
            self._disarm()
            self.moving = True
            self._draw_binding_edits()

    def _disarm(self) -> None:
        """Both learn modes off (the form's is its own)."""
        if self.learning:
            self.learning = False
            self._draw_surface_edits()
        if self.moving:
            self.moving = False
            self._draw_binding_edits()

    def escape(self) -> bool:
        """Esc disarms learn mode, with nothing in the prompt."""
        if not (self.learning or self.moving):
            return False
        self._disarm()
        return True

    def on_hide(self) -> None:
        """Another page: learn mode disarms (MONITOR is not read there)."""
        self._disarm()

    def _draw_binding_edits(self) -> None:
        """The chosen binding's ``[edit…]``, ``[learn]`` and ``[delete]``;
        the first two grey, saying why, on one the form cannot word."""
        binding = self.chosen_binding()
        label = Text()
        buttons: list[StripButton] = []
        if binding is not None:
            label = Text.assemble(
                ("edit ", colors.DIM), (binding.input, colors.CYAN), (" on ", colors.DIM),
                (f'"{binding.surface}"', colors.FG),
            )  # fmt: skip
            why = unworded(binding, self.surface_of(binding))
            if why is None:
                buttons += [
                    _ask("edit…", self.ask_edit_binding),
                    _learn(self.moving, self.toggle_move),
                ]
            else:
                buttons += [_grey("edit…", why), _grey("learn", why)]
            delete = button_label("delete", colors.RED)
            buttons.append(StripButton(delete, Line(""), action=self.ask_delete_binding))
        _update(self.binding_label, label)
        self.binding_edits.show(buttons)

    # ----------------------------------------------------------- clicks

    def on_row_table_clicked(self, message: RowTable.Clicked) -> None:
        message.stop()
        if message.table is self.surfaces and message.row < len(self.shown_surfaces):
            self.choose_surface(self.shown_surfaces[message.row].name)
        elif message.table is self.bindings and message.row < len(self.shown_bindings):
            self.choose_binding(message.row)

    def choose_surface(self, name: str) -> None:
        if name != self.surface:
            self.learning = False  # it was armed on the surface chosen before
        self.surface = name
        self._draw_surface_edits()

    def choose_binding(self, row: int) -> None:
        if row != self.binding:
            self.moving = False  # it was armed on the binding chosen before
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


def _ask(label: str, action: Callable[[], None]) -> StripButton:
    """A button that opens a dialog of the page's."""
    return StripButton(button_label(label, colors.MID), Line(""), action=action)


def _learn(lit: bool, action: Callable[[], None]) -> StripButton:
    """``[learn]``, lit while armed (a span: lit and not compare different)."""
    return StripButton(cell("[learn]", LEARN_LIT if lit else colors.MID), Line(""), action=action)


def _grey(label: str, why: str) -> StripButton:
    """A button that does nothing here, and says why under the mouse."""
    return StripButton(Text(f"[{label}]", style=colors.BORDER), Line(""), note=True, hint=why)


def _update(widget: Static, text: Text) -> None:
    if text != widget.content:
        widget.update(text)
