"""F6's PRESET panel (``docs/plans/tui-presets-plan.md`` §5.3–§5.6): the
preset chosen in edit mode, or a new one to record.

* Nothing chosen: how to choose one.
* A preset of the show: ``[rename…]`` and ``[number…]``, each a dialog and
  then one line (``rename preset color 2 "…"``, ``preset color 2 number
  9``); ``[delete]``, after a question, and inert while cues or effect
  palettes take the preset; what it HOLDS, a line per stored value; and
  the cues that use it.
* A new preset (the ``+ record`` tile): its number, which ``[−]`` ``[+]``
  step over the pool's free numbers and ``[number…]`` types, and its name
  (``[name…]``). These send nothing.

Then, for either, the editors, which work through the programmer as busk
does:

* scope: ``[global]`` ``[profile]`` ``[target]``, what ``[record]``,
  ``[merge]`` and ``[replace]`` record at. A new preset starts at the
  pool's default; a preset of the show at the scope its values share, else
  the pool's default.
* SELECTION: the selection, what the scope lit keeps of it
  (:data:`KEEPS`), a button per group, ``[none]``, and for a preset of the
  show ``[its fixtures]``: ``sel fixture 101, fixture 102``, the fixtures
  it gives a value to.
* A section per family the pool records, with an encoder row
  (:mod:`busk_tui.widgets.encoders`) per attribute the rig takes; a
  rotation's bar is signed. Where the rig takes a colour, the colour
  section starts with the colour picker
  (:mod:`busk_tui.widgets.colorpicker`): a hue × saturation field, named
  chips and the programmer's colour, above the component rows. After the
  encoder rows, ``spread [pan] [tilt] …`` (:mod:`busk_tui.widgets.spread`):
  a row toggled on shows as two bars, ``from`` and ``to``, with
  ``[centre]`` and ``[edges]`` (``set pan spread -30 30``). Then an option
  row (:mod:`busk_tui.widgets.options`) per discrete attribute the rig
  takes: a chip per option the selection offers (``set gobo1 star``).
  Last, dimmed, a line per attribute of the family that no profile of the
  show takes: it does nothing, and shows what a preset could hold.
* RECORDS: what a record takes now, the programmer's values in the pool's
  families, and how many of their elements are not selected (busk records
  them too).
* A new preset: ``[record]``, ``record preset color 5 global "Crimson"``
  (the name only when one was given); once the show has it, the panel
  shows it. A preset of the show: ``[load]`` (``preset color 2``),
  ``[merge]``, ``[replace]`` and ``[remove]`` (``record preset color 2
  global merge``; ``remove`` takes every scope, so it names none). Each
  is inert while there is nothing to record (``[load]``: nothing
  selected).
* ``[clear]``, ``[blind on|off]`` (a toggle that follows the programmer),
  and ``[done]``, which leaves edit mode.

A name or a number is typed in a :class:`~busk_tui.widgets.dialogs.TextDialog`,
which refuses an empty name for a preset of the show, and a number that is
taken.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from functools import partial
from typing import Final, Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from busk_tui import attributes, colors, commands
from busk_tui.attributes import Records, Section, Selected
from busk_tui.colors import ColorMode
from busk_tui.commands import Line
from busk_tui.formats import cues_text, numbers_text, selection_text
from busk_tui.model import (
    FixtureInfo,
    OutputModel,
    PresetEntry,
    PresetInfo,
    ProgrammerModel,
    ShowModel,
    Value,
)
from busk_tui.nav import Item, Stop
from busk_tui.widgets.colorpicker import ColorPicker, components_text
from busk_tui.widgets.controls import (
    ActionButton,
    ButtonStrip,
    CommandButton,
    RunLine,
    StripButton,
    button_label,
)
from busk_tui.widgets.dialogs import TextDialog, check_name, check_number, free_step
from busk_tui.widgets.encoders import EncoderRow
from busk_tui.widgets.options import OptionRow
from busk_tui.widgets.quick import group_buttons, strip_stops
from busk_tui.widgets.spread import SpreadLine, SpreadRow

PANEL_WIDTH: Final = 52
"""The panel's width beside the pools (the plan's §4 call 15)."""

SCOPES: Final = ("global", "profile", "target")

type Write = Literal["merge", "replace", "remove"]
type Part = EncoderRow | ColorPicker | SpreadRow | SpreadLine | OptionRow

HINTS: Final[dict[str, str]] = {
    "load": "the preset on the selection: the editors show its values",
    "merge": "adds the programmer's values; a value of the same scope and attribute is replaced",
    "replace": "the programmer's values become the preset's",
    "remove": "removes what the programmer's fixtures see, for the attributes the programmer holds",
}
"""What the mouse on a button shows in the hint row."""

_VALUES: Final = "the selection only gives the values: if they agree, the preset keeps"

KEEPS: Final[dict[str, str]] = {
    "global": f"{_VALUES} no fixtures",
    "profile": f"{_VALUES} one per profile",
    "target": "the preset keeps a value per fixture: only those fixtures can take it",
}
"""What a preset keeps of the selection at each scope. Values that differ
fall back to a narrower scope, so ``global`` and ``profile`` hold only where
they agree (``_cascade`` in ``busk.commands.record``)."""


@dataclass(frozen=True, slots=True)
class Chosen:
    """What the panel shows: a preset of the show, or (``new``) one to
    record, with the name given it (``""``: busk names it)."""

    pool: str
    number: int
    new: bool = False
    name: str = ""


def default_name(pool: str, number: int) -> str:
    """The name busk gives a preset recorded without one: ``Color 5``."""
    return f"{pool.capitalize()} {number}"


def default_scope(pool: str, preset: PresetInfo | None) -> str:
    """The scope the panel starts at: the one a preset's values share, else
    the pool's default (``attributes.DEFAULT_SCOPE``)."""
    scopes = {entry.scope for entry in preset.entries} if preset is not None else set()
    return scopes.pop() if len(scopes) == 1 else attributes.DEFAULT_SCOPE[pool]


def preset_fixtures(preset: PresetInfo, show: ShowModel) -> tuple[int, ...]:
    """The fixtures a preset gives a value to, by number: a target value's
    fixture, every fixture of a profile value's profile, and for a global
    value every fixture whose profile takes the attribute."""
    found: set[int] = set()
    for entry in preset.entries:
        if isinstance(entry.where, tuple):
            found.add(entry.where[0])
            continue
        for fixture in show.fixtures:
            if entry.where is not None:
                if fixture.profile == entry.where:
                    found.add(fixture.number)
            else:
                profile = show.profile(fixture.profile)
                if profile is not None and entry.attribute in profile.attributes:
                    found.add(fixture.number)
    return tuple(sorted(found))


def value_text(attribute: str, value: Value, mode: ColorMode) -> Text:
    """A stored value: a colour as a swatch and its components as ``set
    color`` takes them (``████ 1 0.5 0 w 0.25``), a number in its unit, a
    discrete value's option."""
    if isinstance(value, tuple):
        text = Text("████", style=colors.swatch(attributes.rgb(value), 1.0, mode))
        text.append(f" {components_text(value)}", style=colors.FG)
        return text
    if isinstance(value, float):
        return Text(attributes.number_text(attribute, value), style=colors.FG)
    return Text(value, style=colors.FG)


def where_text(entry: PresetEntry, fixtures: Sequence[FixtureInfo]) -> str:
    """An entry's scope: ``global``, ``profile Generic Spot 16ch``, ``target 301.2``."""
    if isinstance(entry.where, tuple):
        return f"target {selection_text([entry.where], fixtures)}"
    if entry.where is not None:
        return f"profile {entry.where}"
    return entry.scope


def holds_text(preset: PresetInfo, fixtures: Sequence[FixtureInfo], mode: ColorMode) -> Text:
    """HOLDS: a line per stored value, its attribute, value and scope. The
    scope comes last, so where the widget crops a long line (a long
    profile name), it cuts only the scope."""
    count = len(preset.entries)
    text = Text("HOLDS", style=colors.CYAN)
    text.append(f" · {count} value{'' if count == 1 else 's'}", style=colors.DIM)
    if not preset.entries:
        text.append("\nnothing", style=colors.DIM)
    names = max((len(entry.attribute) for entry in preset.entries), default=0)
    values = [value_text(entry.attribute, entry.value, mode) for entry in preset.entries]
    width = max((value.cell_len for value in values), default=0)
    for entry, value in zip(preset.entries, values, strict=True):
        text.append(f"\n{entry.attribute:<{names}}  ", style=colors.MID)
        text.append_text(value)
        text.append(" " * (width - value.cell_len) + "  ")
        text.append(where_text(entry, fixtures), style=colors.DIM)
    return text


def use_text(preset: PresetInfo, show: ShowModel) -> Text:
    """The cues (and effect palettes) that use it, or none."""
    parts = []
    if preset.used_by:
        parts.append("cue " + cues_text(preset.used_by, show.cueLists))
    if preset.palettes:
        parts.append("effect " + ", ".join(preset.palettes))
    if not parts:
        return Text("used by no cue", style=colors.DIM)
    text = Text("used by ", style=colors.DIM)
    text.append(" · ".join(parts), style=colors.AMBER)
    text.append("\nto delete it, take it out of those first", style=colors.DIM)
    return text


def selection_heading(
    selection: Sequence[tuple[int, int]], fixtures: Sequence[FixtureInfo]
) -> Text:
    """``SELECTION 101 thru 104 (4)``."""
    text = Text("SELECTION ", style=colors.CYAN)
    compressed = selection_text(selection, fixtures)
    if compressed:
        text.append(compressed, style=colors.FG)
        text.append(f" ({len(selection)})", style=colors.DIM)
    else:
        text.append("nothing selected", style=colors.DIM)
    return text


def absent_text(attribute: str) -> Text:
    """A row no profile of the show takes."""
    return Text(f"{attribute:<16} no fixture takes it", style=colors.DIM)


def records_text(found: Records, fixtures: Sequence[FixtureInfo]) -> Text:
    """RECORDS: each attribute a record takes and the elements it takes it
    for, and how many of those are not selected; or what to do first."""
    text = Text("RECORDS", style=colors.CYAN)
    if not found.attributes:
        text.append(" nothing: set a value above", style=colors.DIM)
        return text
    if found.unselected:
        text.append(f" · {found.unselected} not selected, recorded too", style=colors.AMBER)
    names = max(len(attribute) for attribute, _ in found.attributes)
    for attribute, elements in found.attributes:
        text.append(f"\n{attribute:<{names}}  ", style=colors.MID)
        text.append(f"on {selection_text(elements, fixtures)}", style=colors.FG)
        text.append(f" ({len(elements)})", style=colors.DIM)
    return text


def find(show: ShowModel | None, pool: str, number: int) -> PresetInfo | None:
    if show is None:
        return None
    return next((p for p in show.presets if p.pool == pool and p.number == number), None)


def _put(widget: Static, text: Text) -> None:
    """``text`` in ``widget``, if it is not there already (no layout for nothing)."""
    if widget.content != text:
        widget.update(text)


class PresetPanel(VerticalScroll):
    """The PRESET panel (see the module docs). The page shows it in edit
    mode, sets :attr:`chosen` and redraws it with :meth:`show_view`, and
    with :meth:`show_output` when only the output changed; the panel calls
    ``changed`` when it changes what is chosen itself, and ``leave`` for
    ``[done]``."""

    DEFAULT_CSS = f"""
    PresetPanel {{
        width: {PANEL_WIDTH}; height: auto; margin-left: 1;
        border: solid {colors.BORDER}; padding: 0 1;
        border-title-color: {colors.CYAN}; border-title-align: left;
        scrollbar-size-vertical: 1;
        scrollbar-background: {colors.BG}; scrollbar-color: {colors.BORDER};
        scrollbar-background-hover: {colors.BG}; scrollbar-background-active: {colors.BG};
    }}
    PresetPanel > .pp-row {{ height: auto; margin-bottom: 1; }}
    PresetPanel > .pp-row > CommandButton {{ margin-right: 1; }}
    PresetPanel > .pp-row > .pp-word {{ width: auto; color: {colors.DIM}; }}
    PresetPanel > .pp-row > .pp-number {{ width: auto; margin-right: 1; }}
    PresetPanel > .pp-text {{ height: auto; margin-bottom: 1; }}
    PresetPanel > .pp-crop {{ text-wrap: nowrap; text-overflow: ellipsis; }}
    PresetPanel > .pp-heading {{ height: auto; }}
    PresetPanel > ButtonStrip {{ margin-bottom: 1; }}
    PresetPanel > .pp-editors {{ height: auto; }}
    PresetPanel .pp-section {{ height: auto; margin-bottom: 1; }}
    PresetPanel EncoderRow > .enc-name {{ width: 16; }}
    PresetPanel > .pp-last {{ margin-bottom: 0; }}
    """

    def __init__(self, changed: Callable[[], None], leave: Callable[[], None]) -> None:
        super().__init__(id="preset-panel")
        self.can_focus = False  # the prompt keeps the keyboard
        self.changed = changed
        self.chosen: Chosen | None = None
        self.show: ShowModel | None = None
        self.programmer: ProgrammerModel | None = None
        self.output: OutputModel | None = None
        self.mode: ColorMode = "256"
        self._scope: tuple[tuple[str, int, bool], str] | None = None  # (chosen's key, scope)
        self.sections: list[Section] = []
        self.rows: list[EncoderRow] = []
        self.pickers: list[ColorPicker] = []
        self.options: list[OptionRow] = []
        self.spreads: list[SpreadRow] = []
        self.spread_lines: list[SpreadLine] = []
        self.spreading: set[str] = set()  # the rows shown as spreads, by attribute
        self.parts: list[Part] = []  # in reading order
        self.hint = Static(
            Text("click a tile to edit it, or + record to add one", style=colors.DIM),
            classes="pp-text",
        )
        self.down = ActionButton("−", partial(self.step, -1))
        self.number = Static("", classes="pp-number")
        self.up = ActionButton("+", partial(self.step, 1))
        self.number_new = ActionButton("number…", self.ask_number)
        self.name_new = ActionButton("name…", self.ask_name)
        self.new_row = Horizontal(
            Static("number ", classes="pp-word"),
            self.down,
            self.number,
            self.up,
            self.number_new,
            self.name_new,
            classes="pp-row",
        )
        self.rename = ActionButton("rename…", self.ask_name)
        self.renumber = ActionButton("number…", self.ask_number)
        self.delete = ActionButton("delete", self.ask_delete, "danger")
        self.actions = Horizontal(self.rename, self.renumber, self.delete, classes="pp-row")
        self.holds = Static("", classes="pp-text pp-crop")  # a line per value, never wrapped
        self.use = Static("", classes="pp-text")
        self.scopes = {
            scope: ActionButton(scope, partial(self.set_scope, scope)) for scope in SCOPES
        }
        self.scope_row = Horizontal(
            Static("scope  ", classes="pp-word"), *self.scopes.values(), classes="pp-row"
        )
        self.selection = Static("", classes="pp-heading")
        self.keeps = Static("", classes="pp-heading")
        self.groups = ButtonStrip()
        self.editors = Vertical(classes="pp-editors")
        self.records = Static("", classes="pp-text")
        self.record = ActionButton("record", self.record_new, "record")
        self.load = ActionButton("load", self.load_preset, hint=HINTS["load"])
        self.writes: dict[Write, ActionButton] = {
            how: ActionButton(how, partial(self.write, how), "record", hint=HINTS[how])
            for how in ("merge", "replace", "remove")
        }
        self.write_row = Horizontal(self.record, self.load, *self.writes.values(), classes="pp-row")
        self.clear = CommandButton("clear", commands.clear())
        self.blind = CommandButton("blind on", commands.blind(True), "record")
        self.done = ActionButton("done", leave)
        self.bottom = Horizontal(self.clear, self.blind, self.done, classes="pp-row pp-last")

    def compose(self) -> ComposeResult:
        yield self.hint
        yield self.new_row
        yield self.actions
        yield self.holds
        yield self.use
        yield self.scope_row
        yield self.selection
        yield self.keeps
        yield self.groups
        yield self.editors
        yield self.records
        yield self.write_row
        yield self.bottom

    # ------------------------------------------------------------ drawing

    def show_view(
        self,
        show: ShowModel | None,
        programmer: ProgrammerModel | None,
        output: OutputModel | None,
        mode: ColorMode,
    ) -> None:
        """Redraw with the show, the programmer and the output as they are
        now. A new preset whose number the show now has becomes that preset."""
        self.show, self.programmer, self.output, self.mode = show, programmer, output, mode
        chosen = self.chosen
        if chosen is not None and chosen.new and find(show, chosen.pool, chosen.number):
            self.chosen = Chosen(chosen.pool, chosen.number)
        self.draw()

    def show_output(self, output: OutputModel | None) -> None:
        """Only the output changed: the encoders' dim values."""
        self.output = output
        self._draw_encoders()

    def preset(self) -> PresetInfo | None:
        """The chosen preset of the show; ``None`` for a new one, or one the
        show no longer has (deleted, or renumbered and not shown yet)."""
        chosen = self.chosen
        if chosen is None or chosen.new:
            return None
        return find(self.show, chosen.pool, chosen.number)

    def editing(self) -> bool:
        """Whether the editors show: a new preset, or one of the show."""
        chosen = self.chosen
        return chosen is not None and (chosen.new or self.preset() is not None)

    def draw(self) -> None:
        chosen, preset, show = self.chosen, self.preset(), self.show
        new = chosen is not None and chosen.new
        if self._scope is not None and self._scope[0] != self._key():
            self._scope = None  # chosen since: the scope starts again
        if new and chosen is not None:
            title = f"PRESET · new {chosen.pool} {chosen.number}"
            _put(self.number, Text(str(chosen.number), style=colors.MAGENTA))
            name = chosen.name or default_name(chosen.pool, chosen.number)
            shown = name if len(name) <= 16 else name[:15] + "…"
            self.name_new.change(label=f"name: {shown}…")
        elif preset is not None and show is not None:
            title = f'PRESET · {preset.pool} {preset.number} "{preset.name}"'
            _put(self.holds, holds_text(preset, show.fixtures, self.mode))
            _put(self.use, use_text(preset, show))
            self.delete.change(inert=bool(preset.used_by or preset.palettes))
        else:
            title = "PRESET"
        if str(self.border_title) != title:
            self.border_title = Text(title)
        editing = self.editing()
        sections = attributes.pool_rows(chosen.pool, show) if editing and chosen else []
        if sections != self.sections:
            self._build_editors(sections)
        if editing:
            self._draw_scope()
            self._draw_selection(preset)
            self._draw_records()
            self._draw_blind()
            self._draw_spreads()
            first = self._draw_encoders()
            for picker in self.pickers:
                picker.show(first, self.mode)
            for option in self.options:
                option.show(self.programmer, first)
        self.hint.display = not editing
        self.new_row.display = self.record.display = new
        self.actions.display = self.holds.display = self.use.display = preset is not None
        self.load.display = preset is not None
        for button in self.writes.values():
            button.display = preset is not None
        for widget in (
            self.scope_row, self.selection, self.keeps, self.groups, self.editors, self.records,
        ):  # fmt: skip
            widget.display = editing
        self.write_row.display = self.clear.display = self.blind.display = editing

    def _build_editors(self, sections: list[Section]) -> None:
        """A section per family: the colour picker where the rig takes a
        colour, an encoder row per attribute, each with its spread row
        (hidden until toggled), the spread toggles, an option row per
        discrete attribute, then a dimmed line per attribute no profile
        takes (new widgets: a removed one cannot be mounted again)."""
        self.sections = sections
        self.rows, self.pickers, self.options, self.parts = [], [], [], []
        self.spreads, self.spread_lines = [], []
        blocks: list[Vertical] = []
        for section in sections:
            parts: list[Part] = []
            if any(encoder.component in ("r", "g", "b") for encoder in section.encoders):
                picker = ColorPicker()
                self.pickers.append(picker)
                parts.append(picker)
            fans: list[str] = []
            for encoder in section.encoders:
                row = EncoderRow(encoder)
                self.rows.append(row)
                parts.append(row)
                if attributes.spreads(encoder):
                    spread = SpreadRow(encoder)
                    self.spreads.append(spread)
                    parts.append(spread)
                    fans.append(encoder.attribute)
            if fans:
                line = SpreadLine(fans, self.toggle_spread)
                self.spread_lines.append(line)
                parts.append(line)
            options = [OptionRow(attribute) for attribute in section.options]
            self.options += options
            parts += options
            self.parts += parts
            heading = Static(Text(section.family.upper(), style=colors.CYAN))
            absent = [Static(absent_text(name), classes="pp-absent") for name in section.absent]
            blocks.append(Vertical(heading, *parts, *absent, classes="pp-section"))
        self.editors.remove_children()
        if blocks:
            self.editors.mount_all(blocks)

    def _draw_scope(self) -> None:
        scope = self.scope()
        for name, button in self.scopes.items():
            lit = name == scope
            button.change(intent="record" if lit else "neutral", reverse=lit)
        if scope is not None:
            _put(self.keeps, Text(KEEPS[scope], style=colors.DIM))

    def _draw_selection(self, preset: PresetInfo | None) -> None:
        show, programmer = self.show, self.programmer
        fixtures = () if show is None else show.fixtures
        selection = () if programmer is None else programmer.selection
        _put(self.selection, selection_heading(selection, fixtures))
        buttons = group_buttons(() if show is None else show.groups)
        buttons.append(StripButton(button_label("none", colors.DIM), commands.sel_none()))
        found = () if preset is None or show is None else preset_fixtures(preset, show)
        if found:
            line = commands.sel_fixtures(found)
            buttons.append(StripButton(button_label("its fixtures", colors.MID), line))
        self.groups.show(buttons)
        self.load.change(inert=not selection)

    def _draw_records(self) -> None:
        chosen, programmer = self.chosen, self.programmer
        if chosen is None:
            return
        found = attributes.records(chosen.pool, programmer)
        fixtures = () if self.show is None else self.show.fixtures
        _put(self.records, records_text(found, fixtures))
        empty = not found.attributes
        self.record.change(inert=empty)
        for button in self.writes.values():
            button.change(inert=empty)

    def _draw_blind(self) -> None:
        on = self.programmer is not None and self.programmer.blind
        label = f"blind {'off' if on else 'on'}"
        self.blind.change(label=label, line=commands.blind(not on), reverse=on)

    def _draw_encoders(self) -> Selected:
        chosen = attributes.selected(self.show, self.programmer, self.output)
        version = None if self.programmer is None else self.programmer.version
        for row in self.rows:
            if row.display:
                row.show(attributes.reading(row.encoder, self.show, chosen), version)
        for spread in self.spreads:
            if spread.display:
                spread.show(self.show, chosen, self.programmer, self.output)
        return chosen

    def _draw_spreads(self) -> None:
        """Each row that takes a spread, as one or as a plain row, and the
        toggles lit."""
        for row in self.rows:
            plain = row.encoder.attribute not in self.spreading
            if row.display != plain:
                row.display = plain
        for spread in self.spreads:
            on = spread.encoder.attribute in self.spreading
            if spread.display != on:
                spread.display = on
        for line in self.spread_lines:
            line.show(self.spreading)

    # ------------------------------------------------------------ actions

    def taken(self, pool: str) -> frozenset[int]:
        """The numbers the pool's presets have."""
        presets = () if self.show is None else self.show.presets
        return frozenset(p.number for p in presets if p.pool == pool)

    def _choose(self, chosen: Chosen | None) -> None:
        self.chosen = chosen
        self.draw()
        self.changed()

    def _key(self) -> tuple[str, int, bool] | None:
        chosen = self.chosen
        return None if chosen is None else (chosen.pool, chosen.number, chosen.new)

    def scope(self) -> str | None:
        """The scope lit: the one chosen for what is chosen, else where it
        starts (another choice forgets it)."""
        chosen = self.chosen
        if chosen is None:
            return None
        if self._scope is not None and self._scope[0] == self._key():
            return self._scope[1]
        return default_scope(chosen.pool, self.preset())

    def toggle_spread(self, attribute: str) -> None:
        """A spread toggle: the row as a spread, or plain again. Sends nothing."""
        self.spreading ^= {attribute}
        self.draw()

    def set_scope(self, scope: str) -> None:
        """A scope button: what a record, merge or replace records at. Sends nothing."""
        key = self._key()
        if key is None:
            return
        self._scope = (key, scope)
        self._draw_scope()

    def step(self, by: int) -> None:
        """``[−]`` ``[+]``: a new preset's number, to the next free one."""
        chosen = self.chosen
        if chosen is None or not chosen.new:
            return
        number = free_step(chosen.number, by, self.taken(chosen.pool))
        if number != chosen.number:
            self._choose(replace(chosen, number=number))

    def ask_number(self) -> None:
        """``[number…]``: a new preset's number, or a renumber (one line)."""
        chosen = self.chosen
        if chosen is None or (not chosen.new and self.preset() is None):
            return
        taken = self.taken(chosen.pool)
        own = None if chosen.new else chosen.number
        others = sorted(taken - {chosen.number})
        note = f"taken in {chosen.pool}: {numbers_text(others)}" if others else ""

        def given(text: str | None) -> None:
            if text is None or self.chosen != chosen:
                return
            number = int(text.strip())
            if number == chosen.number:
                return
            if chosen.new:
                self._choose(replace(chosen, number=number))
                return

            def renumbered(ok: bool) -> None:
                if ok and self.chosen in (chosen, None):
                    self._choose(Chosen(chosen.pool, number))

            line = commands.renumber_preset(chosen.pool, chosen.number, number)
            self.post_message(RunLine(line, done=renumbered))

        title = f"NUMBER · {'new ' if chosen.new else ''}{chosen.pool} {chosen.number}"
        dialog = TextDialog(title, str(chosen.number), check_number(taken, own), note)
        self.app.push_screen(dialog, given)

    def ask_name(self) -> None:
        """``[name…]`` (a new preset's, sent with its record) or
        ``[rename…]`` (one line)."""
        chosen = self.chosen
        preset = self.preset()
        if chosen is None or (not chosen.new and preset is None):
            return

        def given(text: str | None) -> None:
            if text is None or self.chosen != chosen:
                return
            name = text.strip()
            if chosen.new:
                self._choose(replace(chosen, name=name))
            elif preset is not None and name != preset.name:
                self.post_message(RunLine(commands.rename_preset(chosen.pool, chosen.number, name)))

        if chosen.new:
            title = f"NAME · new {chosen.pool} {chosen.number}"
            note = f"empty: busk names it {default_name(chosen.pool, chosen.number)}"
            dialog = TextDialog(title, chosen.name, check_name(False), note)
        else:
            assert preset is not None
            title = f"RENAME · {chosen.pool} {chosen.number}"
            dialog = TextDialog(title, preset.name, check_name(True))
        self.app.push_screen(dialog, given)

    def ask_delete(self) -> None:
        """``[delete]``: ``delete preset <pool> N``, after the TUI's question,
        which says when the programmer refers to the preset."""
        preset = self.preset()
        if preset is None or preset.used_by or preset.palettes:
            return
        key = (preset.pool, preset.number)
        question = f'Delete preset {preset.pool} {preset.number} "{preset.name}"?'
        values = () if self.programmer is None else self.programmer.values
        holders = {value.number for value in values if value.ref == key}
        if holders:
            count = len(holders)
            question += (
                f"\nThe programmer holds it on {count} fixture{'' if count == 1 else 's'}:"
                " they would show it as gone."
            )
        chosen = self.chosen

        def deleted(ok: bool) -> None:
            if ok and self.chosen == chosen:
                self._choose(None)

        line = commands.delete_preset(preset.pool, preset.number)
        self.post_message(RunLine(line, done=deleted, ask=question))

    def _something_to_record(self, pool: str) -> bool:
        return bool(attributes.records(pool, self.programmer).attributes)

    def record_line(self) -> Line | None:
        """A new preset's ``record preset`` line, at the scope lit; ``None``
        while there is nothing to record."""
        chosen = self.chosen
        if chosen is None or not chosen.new or not self._something_to_record(chosen.pool):
            return None
        name = chosen.name or None
        return commands.record_preset(chosen.pool, chosen.number, self.scope(), name=name)

    def record_new(self) -> None:
        """``[record]``: the new preset. Once the show has it, the panel shows it."""
        line = self.record_line()
        if line is not None:
            self.post_message(RunLine(line))

    def load_line(self) -> Line | None:
        """``[load]``: ``preset color 2``; ``None`` with nothing selected."""
        preset = self.preset()
        if preset is None or self.programmer is None or not self.programmer.selection:
            return None
        return commands.preset(preset.pool, preset.number)

    def load_preset(self) -> None:
        line = self.load_line()
        if line is not None:
            self.post_message(RunLine(line))

    def write_line(self, how: Write) -> Line | None:
        """``[merge]``, ``[replace]`` or ``[remove]`` on the preset of the show;
        ``None`` while there is nothing to record."""
        preset = self.preset()
        if preset is None or not self._something_to_record(preset.pool):
            return None
        scope = None if how == "remove" else self.scope()
        return commands.record_preset(preset.pool, preset.number, scope, how)

    def write(self, how: Write) -> None:
        line = self.write_line(how)
        if line is not None:
            self.post_message(RunLine(line))

    # -------------------------------------------------------- pane cursor

    def stops(self) -> list[Stop]:
        """The panel's controls, in reading order (an inert one is none)."""
        chosen, preset = self.chosen, self.preset()
        stops: list[Stop] = []
        if chosen is not None and chosen.new:
            stops += [
                Stop(Item("number down", action=partial(self.step, -1)), self.down),
                Stop(Item("number up", action=partial(self.step, 1)), self.up),
                Stop(Item("number…", action=self.ask_number), self.number_new),
                Stop(Item("name…", action=self.ask_name), self.name_new),
            ]
        elif preset is not None:
            stops += [
                Stop(Item("rename…", action=self.ask_name), self.rename),
                Stop(Item("number…", action=self.ask_number), self.renumber),
            ]
            if not self.delete.inert:
                stops.append(Stop(Item("delete", action=self.ask_delete), self.delete))
        if self.editing():
            for scope, lit in self.scopes.items():
                item = Item(f"scope {scope}", action=partial(self.set_scope, scope))
                stops.append(Stop(item, lit))
            stops += strip_stops(self.groups)
            for part in self.parts:
                if part.display:
                    stops += part.stops()
            lines: list[tuple[Line | None, CommandButton]] = [
                (self.record_line(), self.record),
                (self.load_line(), self.load),
                *((self.write_line(how), button) for how, button in self.writes.items()),
                (self.clear.line, self.clear),
                (self.blind.line, self.blind),
            ]
            for line, button in lines:
                if line is not None:
                    stops.append(Stop(Item(line.text, line=line.text), button))
        stops.append(Stop(Item("done", action=self.done.action), self.done))
        return stops
