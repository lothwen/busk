"""F5's TEMPLATE panel (``docs/plans/tui-pending-plan.md``, Phase 8): the layers
of the template chosen in TEMPLATES.

A template of the show: ``[rename…]``, ``[delete]``, grey while a cue, a binding
or the programmer uses it, which the panel names, and a row per layer. A click
on a row chooses that layer for the controls under the table, and ``✕`` takes
it out. ``[+ wave]`` and ``[+ colour]`` add one; a template has at most one
colour layer, since a colour layer is always absolute. A template keeps at
least one layer, and a palette at least one colour: their last ``✕`` is not
drawn.

* A wave layer has a chip per attribute, mode and waveform, and what its
  waveform takes: ``duty``, ``width``, ``attack``, ``decay``, ``steps``,
  ``seed``, ``smooth`` or ``points``, and its phase offset.
* A colour layer has its blend, and its palette. A click on a colour opens its
  form, ``✕`` takes an entry out, ``[+ colour…]`` adds one and a chip per colour
  preset adds that preset.

Each change is one line, ``effect template update "<name>" <JSON layers>``, with
every layer as the show stores it, so a part the panel does not edit (a colour's
extra emitters) goes back as it was. A value left as it was sends nothing.

A dialog refuses what could not be sent, such as a level outside 0..1. What only
busk can tell, such as a pulse longer than its cycle or a layer an effect in a
cue cannot take, comes back as a refusal: the reason shows in the panel until
the next line, and the whole reply in the log.

A library template the show has no copy of is read-only: the panel names its
layers, and says how to get a copy.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from functools import partial
from typing import Any, ClassVar, Final

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from busk_tui import colors, commands
from busk_tui.colors import ColorMode
from busk_tui.commands import Line, exact
from busk_tui.formats import cues_text
from busk_tui.model import Layer, ProgrammerModel, Rgb, ShowModel, TemplateInfo
from busk_tui.nav import Item, Stop
from busk_tui.widgets.controls import (
    ActionButton,
    ButtonStrip,
    RunLine,
    StripButton,
    button_label,
)
from busk_tui.widgets.dialogs import FormDialog, TextDialog, dialog_css, read_number, read_whole
from busk_tui.widgets.fixture_panel import Setting, chips, put
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.preset_panel import PANEL_WIDTH
from busk_tui.widgets.quick import strip_stops
from busk_tui.widgets.route_dialog import PickRow, row
from busk_tui.widgets.rows import Cells, Column, RowTable, cell

ATTRIBUTES: Final = (
    "intensity", "pan", "tilt", "cto", "colorMacroRate", "gobo1Rotation", "gobo2Rotation",
    "prismRotation", "zoom", "iris", "frost", "effectRate", "effectAdjust", "effectRotation",
    "focus", "strobeRate",
)  # fmt: skip
"""What a wave layer can drive: the scalar attributes that fade (a test holds
it to busk's registry)."""

MODES: Final = ("absolute", "add", "multiply")
BLENDS: Final = ("fade", "snap")

WAVES: Final[dict[str, dict[str, Any]]] = {
    "sine": {},
    "triangle": {},
    "square": {"duty": 0.5},
    "sawUp": {},
    "sawDown": {},
    "pulse": {"width": 0.25, "attack": 0.25, "decay": 0.25},
    "step": {"steps": [0.0, 1.0]},
    "random": {"smooth": True, "seed": 1},
    "curve": {"points": [[0.0, 0.0], [1.0, 1.0]]},
}
"""Each waveform and what a layer gets on changing to it (a test holds the
words to busk's types)."""

NEW_WAVE: Final[Layer] = {
    "attribute": "intensity",
    "waveform": {"kind": "sine"},
    "phaseOffset": 0.0,
    "mode": "multiply",
}
"""A new wave layer: one any effect can take at its default size of 1."""

NEW_COLOUR: Final[Layer] = {
    "attribute": "color",
    "palette": [{"r": 1.0, "g": 1.0, "b": 1.0}],
    "blend": "fade",
    "mode": "absolute",
}

FIRST_LAYERS: Final[dict[str, Layer]] = {"wave": NEW_WAVE, "colour": NEW_COLOUR}
"""What a new template starts with, by the choice in its form."""

GREY_WHILE_USED: Final = "delete is grey while something uses it"
LIBRARY_NOTE: Final = "the library's: add it to a selection, and the show holds a copy to edit"


def check_unit(text: str) -> str | None:
    value = read_number(text)
    return None if value is not None and 0 <= value <= 1 else "a number from 0 to 1"


def check_degrees(text: str) -> str | None:
    return None if read_number(text) is not None else "a number of degrees"


def check_seed(text: str) -> str | None:
    return None if read_whole(text.strip()) is not None else "a whole number, 0 or more"


def check_rgb(values: tuple[str, ...]) -> str | None:
    """The three components of a colour."""
    return "three numbers from 0 to 1" if any(check_unit(value) for value in values) else None


def read_steps(text: str) -> list[float] | None:
    """Levels 0..1, apart by spaces or commas; ``None`` if ``text`` is not that."""
    words = text.replace(",", " ").split()
    if not words or any(check_unit(word) for word in words):
        return None
    return [float(word) for word in words]


def check_steps(text: str) -> str | None:
    return None if read_steps(text) is not None else "one or more numbers from 0 to 1: 0 0.5 1"


def read_points(text: str) -> list[list[float]] | None:
    """``x y`` pairs 0..1, apart by commas; ``None`` if ``text`` is not that."""
    pairs = [part.split() for part in text.split(",")]
    if any(len(pair) != 2 or any(check_unit(word) for word in pair) for pair in pairs):
        return None
    return [[float(x), float(y)] for x, y in pairs]


def check_points(text: str) -> str | None:
    return None if read_points(text) is not None else "x y pairs from 0 to 1: 0 0, 0.5 1, 1 0"


WAVE_NUMBERS: Final[dict[str, tuple[Callable[[str], str | None], str]]] = {
    "duty": (check_unit, "the part of each cycle it is on, 0 to 1"),
    "width": (check_unit, "the part of each cycle it holds, 0 to 1"),
    "attack": (check_unit, "the part of each cycle it rises in, 0 to 1"),
    "decay": (check_unit, "the part of each cycle it falls in, 0 to 1"),
    "seed": (check_seed, "which random run it gives"),
}
"""A waveform's numbers: each one's check, and the note in its dialog."""


def check_template_name(
    taken: Collection[str], own: str | None = None
) -> Callable[[str], str | None]:
    """A template name's check, by busk's rule: not empty, and in any case not
    one of ``taken`` (``own`` may change its case)."""
    folded = {name.casefold() for name in taken} - {(own or "").casefold()}

    def check(text: str) -> str | None:
        name = text.strip()
        if not name:
            return "a name cannot be empty"
        return "a template with that name exists" if name.casefold() in folded else None

    return check


def layer_text(layer: Layer) -> str:
    """A layer as busk words it: ``pan add sine +90°``, ``color fade 3 colours``."""
    if "palette" in layer:
        count = len(layer["palette"])
        return f"color {layer['blend']} {count} colour{'' if count == 1 else 's'}"
    offset = layer["phaseOffset"]
    shift = f" {offset:+g}°" if offset else ""
    return f"{layer['attribute']} {layer['mode']} {layer['waveform']['kind']}{shift}"


def number_list(values: Sequence[float]) -> str:
    return " ".join(exact(value) for value in values)


def points_text(points: Sequence[Sequence[float]]) -> str:
    return ", ".join(number_list(point) for point in points)


def users_text(template: TemplateInfo, show: ShowModel | None, programmer: bool) -> Text:
    """What uses it, or that nothing does."""
    parts = []
    if template.used_by:
        parts.append("cue " + cues_text(template.used_by, () if show is None else show.cueLists))
    if template.bindings:
        parts.append(f"{template.bindings} binding{'' if template.bindings == 1 else 's'}")
    if programmer:
        parts.append("the programmer")
    if not parts:
        return Text("used by nothing", style=colors.DIM)
    text = Text("used by ", style=colors.DIM)
    text.append(" · ".join(parts), style=colors.AMBER)
    text.append(f"\n{GREY_WHILE_USED}", style=colors.DIM)
    return text


def refusal_reason(reply: str) -> str:
    """What is wrong, from a refused line's reply: its issues, without the place
    in the document that each starts with, or the reply's own one line."""
    head, *issues = reply.splitlines()
    return "\n".join(issue.strip().partition(": ")[2] or issue.strip() for issue in issues) or head


class LayerTable(RowTable):
    COLUMNS = (
        Column("number", "", 2, right=True),
        Column("what", "layer", 10, flex=True),
        Column("remove", "", 1),
    )


class PaletteTable(RowTable):
    COLUMNS = (
        Column("swatch", "", 4),
        Column("what", "colour", 10, flex=True),
        Column("remove", "", 1),
    )


def palette_cells(entry: Mapping[str, Any], show: ShowModel | None, mode: ColorMode) -> Cells:
    """A palette entry: its colour, as a swatch where the panel can tell it, and
    its components or its preset's name."""
    rgb: Rgb | None
    if "presetId" in entry:
        presets = () if show is None else show.presets
        preset = next((found for found in presets if found.id == entry["presetId"]), None)
        rgb = None if preset is None else preset.color
        what = cell(
            entry["presetId"] if preset is None else f"preset {preset.name}",
            colors.CYAN,
        )
    else:
        rgb = (float(entry["r"]), float(entry["g"]), float(entry["b"]))
        what = cell(number_list(rgb), colors.FG)
    swatch = (
        cell("····", colors.DIM) if rgb is None else cell("████", colors.swatch(rgb, 1.0, mode))
    )
    return {"swatch": swatch, "what": what}


class NewTemplateDialog(ModalScreen[tuple[str, str] | None]):
    """A new template's name and what its first layer is. Closes with the two,
    or ``None``."""

    DEFAULT_CSS = (
        dialog_css("NewTemplateDialog")
        + f"""
    NewTemplateDialog > Vertical {{ width: 60; }}
    NewTemplateDialog Horizontal {{ width: 100%; margin-top: 0; }}
    NewTemplateDialog .label {{ color: {colors.MID}; width: 12; }}
    NewTemplateDialog Input {{ width: 1fr; }}
    NewTemplateDialog PickRow {{ width: 1fr; }}
    NewTemplateDialog PickRow:focus {{ background: {colors.SEL}; }}
    NewTemplateDialog .error {{ color: {colors.RED}; width: 100%; height: auto; }}
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "ok", "OK", show=False),
    ]

    def __init__(self, taken: Collection[str]) -> None:
        super().__init__()
        self.check = check_template_name(taken)
        self.name_field = Input(compact=True)
        self.kind = PickRow({key: key for key in FIRST_LAYERS})
        self.error = Static("", classes="error")

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = "NEW TEMPLATE"
            yield row("name", self.name_field)
            yield row("first layer", self.kind)
            yield self.error
            yield Static("Tab: next · ← →: chips · Enter: OK · Esc: cancel", classes="note")

    def on_mount(self) -> None:
        self.name_field.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_ok()

    def action_ok(self) -> None:
        problem = self.check(self.name_field.value)
        if problem is None:
            self.dismiss((self.name_field.value.strip(), self.kind.chosen))
        else:
            self.error.update(problem)

    def action_cancel(self) -> None:
        self.dismiss(None)


class TemplatePanel(Panel):
    """The TEMPLATE panel (see the module docs). The page shows it while a
    template is chosen, and redraws it with :meth:`show_view`; ``leave`` is
    ``[done]``."""

    DEFAULT_CSS = f"""
    TemplatePanel {{ width: {PANEL_WIDTH}; margin-left: 1; }}
    TemplatePanel .tp-text {{ height: auto; }}
    TemplatePanel #tp-used {{ margin-bottom: 1; }}
    TemplatePanel #tp-refusal {{ color: {colors.RED}; margin-bottom: 1; }}
    TemplatePanel .tp-buttons {{ height: 1; }}
    TemplatePanel .tp-buttons > CommandButton {{ margin-right: 1; }}
    TemplatePanel .tp-part {{ height: auto; margin-top: 1; }}
    TemplatePanel .tp-chips {{ height: auto; }}
    TemplatePanel .tp-chips > .tp-name {{ width: 13; color: {colors.MID}; }}
    TemplatePanel .tp-chips > ButtonStrip {{ width: 1fr; }}
    TemplatePanel Setting > .fp-name {{ width: 13; }}
    TemplatePanel Setting > .fp-value {{ width: 18; }}
    TemplatePanel #tp-done {{ margin-top: 1; }}
    """

    def __init__(self, leave: Callable[[], None]) -> None:
        super().__init__("template", id="template-panel")
        self.template: TemplateInfo | None = None
        self.show_model: ShowModel | None = None
        self.programmer: ProgrammerModel | None = None
        self.color_mode: ColorMode = "256"
        self.layer_index = 0  # the layer the controls change
        self.new_layer: int | None = None  # a layer that ran, to choose once the show has it
        self.what = Static("", id="tp-what", classes="tp-text")
        self.used = Static("", id="tp-used", classes="tp-text")
        self.refusal = Static("", id="tp-refusal", classes="tp-text")
        self.refusal.display = False
        self.rename = ActionButton("rename…", self.ask_rename)
        self.delete = ActionButton("delete", self.ask_delete, "danger")
        self.head = Horizontal(self.rename, self.delete, classes="tp-buttons")
        self.layer_table = LayerTable(id="tp-layers")
        self.add_wave = ActionButton("+ wave", partial(self.add_layer, NEW_WAVE), "go")
        self.add_colour = ActionButton("+ colour", partial(self.add_layer, NEW_COLOUR), "go")
        self.adds = Horizontal(self.add_wave, self.add_colour, classes="tp-buttons")
        self.attribute = ButtonStrip()
        self.modes = ButtonStrip()
        self.wave = ButtonStrip()
        self.numbers = {
            name: Setting(name, ActionButton(f"{name}…", partial(self.ask_wave_number, name)))
            for name in WAVE_NUMBERS
        }
        self.steps = Setting("steps", ActionButton("steps…", self.ask_steps))
        self.points = Setting("points", ActionButton("points…", self.ask_points))
        self.smooth = ActionButton("smooth off", self.toggle_smooth)
        self.smooth_row = Setting("smooth", self.smooth)
        self.offset_row = Setting("phase offset", ActionButton("offset…", self.ask_offset))
        self.scalar = Vertical(
            self.chip_row("attribute", self.attribute),
            self.chip_row("mode", self.modes),
            self.chip_row("wave", self.wave),
            *self.numbers.values(),
            self.steps,
            self.points,
            self.smooth_row,
            self.offset_row,
            classes="tp-part",
        )
        self.blend = ButtonStrip()
        self.palette = PaletteTable(id="tp-palette")
        self.add_entry = ActionButton("+ colour…", partial(self.ask_colour, None), "go")
        self.preset_chips = ButtonStrip()
        self.presets_row = self.chip_row("+ preset", self.preset_chips)
        self.colour = Vertical(
            self.chip_row("blend", self.blend),
            self.palette,
            Horizontal(self.add_entry, classes="tp-buttons"),
            self.presets_row,
            classes="tp-part",
        )
        self.editing = Vertical(self.head, self.layer_table, self.adds, self.scalar, self.colour)
        self.editing.styles.height = "auto"
        self.done = ActionButton("done", leave, id="tp-done")

    @staticmethod
    def chip_row(name: str, strip: ButtonStrip) -> Horizontal:
        return Horizontal(Static(name, classes="tp-name"), strip, classes="tp-chips")

    def compose(self) -> ComposeResult:
        yield self.what
        yield self.used
        yield self.refusal
        yield self.editing
        yield self.done

    # ------------------------------------------------------------ drawing

    def show_view(
        self,
        template: TemplateInfo | None,
        show: ShowModel | None,
        programmer: ProgrammerModel | None,
        mode: ColorMode,
    ) -> None:
        """Redraw with the template chosen and the show as they are now."""
        if (template and template.id) != (self.template and self.template.id):
            self.layer_index = 0
            self.new_layer = None
            self.refusal.display = False
        self.template, self.show_model, self.programmer = template, show, programmer
        self.color_mode = mode
        if template is not None:
            self.draw(template)

    def draw(self, template: TemplateInfo) -> None:
        self.set_title("template", template.name)
        put(self.what, Text(template.summary, style=colors.FG))
        effects = () if self.programmer is None else self.programmer.effects
        programmer = any(effect.template == template.name for effect in effects)
        self.editing.display = template.source == "show"
        if template.source != "show":
            put(self.used, Text(LIBRARY_NOTE, style=colors.DIM))
            return
        put(self.used, users_text(template, self.show_model, programmer))
        self.delete.change(inert=programmer or bool(template.used_by or template.bindings))
        layers = template.layers
        if self.new_layer is not None and self.new_layer < len(layers):
            self.layer_index, self.new_layer = self.new_layer, None
        self.layer_index = min(self.layer_index, max(0, len(layers) - 1))
        self.layer_table.show(
            [self._layer_cells(index) for index in range(len(layers))], self.layer_index
        )
        self.add_colour.change(inert=any("palette" in layer for layer in layers))
        layer = self.chosen_layer()
        self.scalar.display = layer is not None and "waveform" in layer
        self.colour.display = layer is not None and "palette" in layer
        if layer is None:
            return
        if "waveform" in layer:
            self._draw_scalar(layer)
        else:
            self._draw_colour(layer)

    def _layer_cells(self, index: int) -> Cells:
        assert self.template is not None
        layers = self.template.layers
        cells = {
            "number": cell(str(index + 1), colors.DIM),
            "what": cell(layer_text(layers[index]), colors.FG),
        }
        return cells | {"remove": cell("✕", colors.RED)} if len(layers) > 1 else cells

    def _draw_scalar(self, layer: Layer) -> None:
        wave = layer["waveform"]
        self.attribute.show(chips(ATTRIBUTES, layer["attribute"], self._attribute_line))
        self.modes.show(chips(MODES, layer["mode"], self._mode_line))
        self.wave.show(chips(tuple(WAVES), wave["kind"], self._kind_line))
        for name, setting in self.numbers.items():
            setting.display = name in wave
            if name in wave:
                put(setting.value, cell(f"{wave[name]:g}", colors.FG))
        self.steps.display = "steps" in wave
        if "steps" in wave:
            put(self.steps.value, cell(number_list(wave["steps"]), colors.FG))
        self.points.display = "points" in wave
        if "points" in wave:
            put(self.points.value, cell(points_text(wave["points"]), colors.FG))
        self.smooth_row.display = "smooth" in wave
        if "smooth" in wave:
            put(self.smooth_row.value, cell("on" if wave["smooth"] else "off", colors.FG))
            self.smooth.change(label="smooth off" if wave["smooth"] else "smooth on")
        put(self.offset_row.value, cell(f"{layer['phaseOffset']:g}°", colors.FG))

    def _draw_colour(self, layer: Layer) -> None:
        self.blend.show(chips(BLENDS, layer["blend"], self._blend_line))
        palette = layer["palette"]
        rows = [palette_cells(entry, self.show_model, self.color_mode) for entry in palette]
        self.palette.show(
            [
                {**entry, "remove": cell("✕", colors.RED)} if len(palette) > 1 else entry
                for entry in rows
            ]
        )
        presets = () if self.show_model is None else self.show_model.presets
        chosen = [found for found in presets if found.pool == "color"]
        self.presets_row.display = bool(chosen)
        self.preset_chips.show(
            [
                StripButton(
                    button_label(found.name, colors.MID),
                    self._palette_line([*palette, {"presetId": found.id}]),
                )
                for found in chosen
            ]
        )

    # -------------------------------------------------------------- lines

    def chosen_layer(self) -> Layer | None:
        template = self.template
        if template is None or self.layer_index >= len(template.layers):
            return None
        return template.layers[self.layer_index]

    def _update_line(self, layers: Sequence[Layer]) -> Line:
        assert self.template is not None
        return commands.effect_template_update(self.template.name, layers)

    def _layer_line(self, **changes: Any) -> Line:
        """The line that changes the chosen layer."""
        assert self.template is not None
        layers = list(self.template.layers)
        layers[self.layer_index] = dict(layers[self.layer_index]) | changes
        return self._update_line(layers)

    def _wave_line(self, **changes: Any) -> Line:
        """The line that changes the chosen layer's waveform."""
        layer = self.chosen_layer()
        assert layer is not None
        return self._layer_line(waveform=dict(layer["waveform"]) | changes)

    def _attribute_line(self, attribute: str) -> Line:
        return self._layer_line(attribute=attribute)

    def _mode_line(self, mode: str) -> Line:
        return self._layer_line(mode=mode)

    def _kind_line(self, kind: str) -> Line:
        return self._layer_line(waveform={"kind": kind} | WAVES[kind])

    def _blend_line(self, blend: str) -> Line:
        return self._layer_line(blend=blend)

    def _palette_line(self, palette: Sequence[Mapping[str, Any]]) -> Line:
        return self._layer_line(palette=list(palette))

    def _run(self, line: Line) -> None:
        self.post_message(RunLine(line))

    def on_run_line(self, message: RunLine) -> None:
        """Each line of the panel, as it bubbles up: a refusal shows here too,
        until the next line."""
        self.refusal.display = False
        if self.template is not None:
            message.refused = partial(self._say_refused, self.template.id)

    def _say_refused(self, template: str, reply: str) -> None:
        if self.template is not None and self.template.id == template:
            put(self.refusal, Text(refusal_reason(reply), style=colors.RED))
            self.refusal.display = True

    # ----------------------------------------------------------- controls

    def choose_layer(self, index: int) -> None:
        if self.template is not None and index < len(self.template.layers):
            self.layer_index = index
            self.draw(self.template)

    def add_layer(self, layer: Layer) -> None:
        """``[+ wave]``, ``[+ colour]``: the new layer, last, and chosen once
        the show has it."""
        template = self.template
        if template is None:
            return
        count = len(template.layers)

        def added(ok: bool) -> None:
            if ok and self.template is not None and self.template.id == template.id:
                self.new_layer = count
                self.draw(self.template)

        self.post_message(RunLine(self._update_line([*template.layers, layer]), done=added))

    def remove_layer(self, index: int) -> None:
        template = self.template
        if template is not None and len(template.layers) > 1:
            layers = [*template.layers[:index], *template.layers[index + 1 :]]
            self._run(self._update_line(layers))

    def remove_entry(self, index: int) -> None:
        layer = self.chosen_layer()
        if layer is not None and "palette" in layer and len(layer["palette"]) > 1:
            palette = layer["palette"]
            self._run(self._palette_line([*palette[:index], *palette[index + 1 :]]))

    def ask_rename(self) -> None:
        """``[rename…]``: ``effect template rename "Beat" "Beat 2"``."""
        template = self.template
        if template is None:
            return
        taken = () if self.show_model is None else self.show_model.templates
        names = [found.name for found in taken if found.source == "show"]

        def given(text: str | None) -> None:
            if text is not None and text.strip() != template.name:
                self._run(commands.effect_template_rename(template.name, text.strip()))

        check = check_template_name(names, template.name)
        self.app.push_screen(TextDialog("RENAME TEMPLATE", template.name, check), given)

    def ask_delete(self) -> None:
        """``[delete]``, after the TUI's question: it is grey while busk would
        refuse."""
        template = self.template
        if template is not None:
            line = commands.effect_template_delete(template.name)
            self.post_message(RunLine(line, ask=f'Delete effect template "{template.name}"?'))

    def ask_wave_number(self, name: str) -> None:
        """``[duty…]``, ``[seed…]`` and the like: one number of the waveform."""
        layer = self.chosen_layer()
        if layer is None or name not in layer["waveform"]:
            return
        before = layer["waveform"][name]
        check, note = WAVE_NUMBERS[name]

        def given(text: str | None) -> None:
            if text is None:
                return
            value = int(text) if name == "seed" else float(text)
            if value != before:
                self._run(self._wave_line(**{name: value}))

        title = f"{name.upper()} · layer {self.layer_index + 1}"
        self.app.push_screen(TextDialog(title, exact(before), check, note), given)

    def ask_steps(self) -> None:
        """``[steps…]``: the levels of a step wave."""
        layer = self.chosen_layer()
        if layer is None or "steps" not in layer["waveform"]:
            return
        before = [float(value) for value in layer["waveform"]["steps"]]

        def given(text: str | None) -> None:
            steps = None if text is None else read_steps(text)
            if steps is not None and steps != before:
                self._run(self._wave_line(steps=steps))

        title = f"STEPS · layer {self.layer_index + 1}"
        note = "levels from 0 to 1, each held for an equal time"
        self.app.push_screen(TextDialog(title, number_list(before), check_steps, note), given)

    def ask_points(self) -> None:
        """``[points…]``: the ``x y`` pairs of a curve."""
        layer = self.chosen_layer()
        if layer is None or "points" not in layer["waveform"]:
            return
        before = [[float(x), float(y)] for x, y in layer["waveform"]["points"]]

        def given(text: str | None) -> None:
            points = None if text is None else read_points(text)
            if points is not None and points != before:
                self._run(self._wave_line(points=points))

        title = f"POINTS · layer {self.layer_index + 1}"
        note = "x y pairs from 0 to 1, with x rising: 0 0, 0.5 1, 1 0"
        self.app.push_screen(TextDialog(title, points_text(before), check_points, note), given)

    def toggle_smooth(self) -> None:
        layer = self.chosen_layer()
        if layer is not None and "smooth" in layer["waveform"]:
            self._run(self._wave_line(smooth=not layer["waveform"]["smooth"]))

    def ask_offset(self) -> None:
        """``[offset…]``: where the layer sits in the cycle, in degrees."""
        layer = self.chosen_layer()
        if layer is None:
            return
        before = layer["phaseOffset"]

        def given(text: str | None) -> None:
            if text is not None and float(text) != before:
                self._run(self._layer_line(phaseOffset=float(text)))

        title = f"PHASE OFFSET · layer {self.layer_index + 1}"
        self.app.push_screen(TextDialog(title, exact(before), check_degrees, "in degrees"), given)

    def ask_colour(self, index: int | None) -> None:
        """``[+ colour…]`` (``index`` ``None``) or a click on a colour of the
        palette. The extra emitters of the colour stay."""
        layer = self.chosen_layer()
        if layer is None or "palette" not in layer:
            return
        palette = list(layer["palette"])
        entry = None if index is None else palette[index]
        if entry is not None and "presetId" in entry:
            return
        start = {key: 1.0 if entry is None else float(entry[key]) for key in "rgb"}

        def given(values: tuple[str, ...] | None) -> None:
            if values is None:
                return
            colour = {key: float(value) for key, value in zip("rgb", values, strict=True)}
            if entry is None:
                self._run(self._palette_line([*palette, colour]))
            elif index is not None and colour != start:
                self._run(
                    self._palette_line([*palette[:index], entry | colour, *palette[index + 1 :]])
                )

        title = "NEW COLOUR" if index is None else f"COLOUR {index + 1}"
        fields = tuple((key, exact(start[key])) for key in "rgb")
        self.app.push_screen(FormDialog(title, fields, check_rgb, "each from 0 to 1"), given)

    def on_row_table_clicked(self, message: RowTable.Clicked) -> None:
        message.stop()
        if message.table is self.layer_table:
            if message.cell == "remove":
                self.remove_layer(message.row)
            else:
                self.choose_layer(message.row)
        elif message.table is self.palette:
            if message.cell == "remove":
                self.remove_entry(message.row)
            else:
                self.ask_colour(message.row)

    # -------------------------------------------------------- pane cursor

    def stops(self) -> list[Stop]:
        template = self.template
        if template is None:
            return []
        done = Stop(Item(self.done.label, action=self.done.action), self.done)
        if template.source != "show":
            return [done]
        stops: list[Stop] = [Stop(Item(self.rename.label, action=self.rename.action), self.rename)]
        if not self.delete.inert:
            stops.append(Stop(Item(self.delete.label, action=self.delete.action), self.delete))
        stops += self._table_stops(
            self.layer_table, "layer", self.choose_layer, self.remove_layer, len(template.layers)
        )
        stops.append(Stop(Item(self.add_wave.label, action=self.add_wave.action), self.add_wave))
        if not self.add_colour.inert:
            stops.append(
                Stop(Item(self.add_colour.label, action=self.add_colour.action), self.add_colour)
            )
        layer = self.chosen_layer()
        if layer is not None and "waveform" in layer:
            stops += strip_stops(self.attribute) + strip_stops(self.modes) + strip_stops(self.wave)
            for name, setting in [
                *self.numbers.items(),
                ("steps", self.steps),
                ("points", self.points),
                ("smooth", self.smooth_row),
                ("offset", self.offset_row),
            ]:
                stops += setting.stops(name)
        elif layer is not None:
            stops += strip_stops(self.blend)
            stops += self._table_stops(
                self.palette, "colour", self.ask_colour, self.remove_entry, len(layer["palette"])
            )
            stops.append(
                Stop(Item(self.add_entry.label, action=self.add_entry.action), self.add_entry)
            )
            stops += strip_stops(self.preset_chips)
        return [*stops, done]

    @staticmethod
    def _table_stops(
        table: RowTable,
        name: str,
        choose: Callable[[int], None],
        remove: Callable[[int], None],
        count: int,
    ) -> list[Stop]:
        """A stop on each row of ``table``, and on its ``✕`` where it has one."""
        stops: list[Stop] = []
        spots: list[tuple[int, str | None]] = []
        for index in range(count):
            for part, act in (("what", choose), ("remove", remove)):
                if part == "remove" and count == 1:
                    continue
                label = f"{name} {index + 1}" if part == "what" else f"{name} {index + 1} ✕"
                stops.append(Stop(Item(label, action=partial(act, index)), table, len(spots)))
                spots.append((index, part))
        table.spots = spots
        return stops
