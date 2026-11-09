"""F5's TEMPLATE panel (plan Phase 8): a template's layers, a control per
setting and a line per change, a library template read-only, what uses one, and
what a refused line says in the panel and the log. Headless, with a fake bridge."""

from __future__ import annotations

from typing import Any, get_args, get_type_hints

import pytest
from rich.text import Text
from textual.pilot import Pilot
from textual.widgets import Input
from tui_fakes import (
    FakeBridge,
    click_cell,
    column,
    drive,
    live_state,
    make_app,
    programmer,
    settle,
    show_model,
)

import busk
from busk.model.attributes import ATTRIBUTES as BUSK_ATTRIBUTES
from busk.model.effect import (
    CurveWave,
    PulseWave,
    RandomWave,
    SawDownWave,
    SawUpWave,
    SineWave,
    SquareWave,
    StepWave,
    TriangleWave,
)
from busk_tui import commands
from busk_tui.model import (
    CommandDone,
    CueInfo,
    CueListInfo,
    EffectInfo,
    Layer,
    LiveChanged,
    PresetInfo,
    ProgrammerChanged,
    ShowChanged,
    ShowModel,
    Targets,
    TemplateInfo,
)
from busk_tui.shell import BuskApp
from busk_tui.widgets.controls import ActionButton, ButtonStrip
from busk_tui.widgets.dialogs import ConfirmDialog, FormDialog, TextDialog
from busk_tui.widgets.effect_panel import EffectPanel
from busk_tui.widgets.effects import EffectTable, TemplateTable
from busk_tui.widgets.log import LogView
from busk_tui.widgets.route_dialog import PickRow
from busk_tui.widgets.template_panel import (
    ATTRIBUTES,
    NEW_COLOUR,
    NEW_WAVE,
    WAVES,
    NewTemplateDialog,
    TemplatePanel,
    check_degrees,
    check_points,
    check_rgb,
    check_seed,
    check_steps,
    check_template_name,
    check_unit,
    layer_text,
    read_points,
    read_steps,
    refusal_reason,
)

SINE: Layer = {
    "attribute": "pan",
    "waveform": {"kind": "sine"},
    "phaseOffset": 90.0,
    "mode": "add",
}
COLOUR: Layer = {
    "attribute": "color",
    "palette": [{"r": 1.0, "g": 0.5, "b": 0.0, "w": 0.25}, {"presetId": "pr-blue"}],
    "blend": "fade",
    "mode": "absolute",
}
BEAT = TemplateInfo("Beat", "show", "pan add sine +90°", id="ef-beat", layers=(SINE, COLOUR))
SOLO = TemplateInfo("Solo", "show", "intensity multiply sine", id="ef-solo", layers=(NEW_WAVE,))
BOUGHT = TemplateInfo("Chase", "library", "intensity absolute square", id="ef-chase")
BLUE = PresetInfo("color", 1, "Blue", (0.0, 0.0, 1.0), id="pr-blue")
RED = PresetInfo("color", 2, "Red", (1.0, 0.0, 0.0), id="pr-red")
AIM = PresetInfo("position", 1, "Aim", None, id="pr-aim")


def wave_layer(wave: dict[str, Any], **changes: Any) -> Layer:
    return {"attribute": "intensity", "waveform": wave, "phaseOffset": 0.0, "mode": "add"} | changes


def template_show(*templates: TemplateInfo, **changes: Any) -> ShowModel:
    parts: dict[str, Any] = {
        "templates": templates or (BEAT, SOLO, BOUGHT),
        "presets": (BLUE, RED, AIM),
    }
    return show_model(**(parts | changes))


def update(layers: list[Layer], name: str = "Beat") -> str:
    return commands.effect_template_update(name, layers).text


def on_f5(bridge: FakeBridge, *templates: TemplateInfo, **changes: Any) -> BuskApp:
    bridge.events += [
        ShowChanged(template_show(*templates, **changes)),
        LiveChanged(live_state()),
        ProgrammerChanged(programmer()),
    ]
    return make_app(bridge, page=5)


def panel_of(app: BuskApp) -> TemplatePanel:
    return app.query_one(TemplatePanel)


def plain(widget: Any) -> str:
    return widget.content.plain if isinstance(widget.content, Text) else str(widget.content)


async def open_template(pilot: Pilot[int], app: BuskApp, row: int = 0) -> TemplatePanel:
    await settle(pilot, app)
    await click_cell(pilot, app.query_one(TemplateTable), row, "edit")
    await settle(pilot, app)
    return panel_of(app)


async def click_chip(pilot: Pilot[int], strip: ButtonStrip, label: str) -> None:
    lines = [line.plain for line in strip.lines(strip.size.width)]
    for y, line in enumerate(lines):
        if f"[{label}]" in line:
            await pilot.click(strip, offset=(line.index(f"[{label}]") + 1, y))
            await pilot.pause()
            return
    raise AssertionError(f"no {label!r} in {lines}")


def button_named(panel: TemplatePanel, label: str) -> ActionButton:
    return next(button for button in panel.query(ActionButton) if button.label == label)


async def press_button(pilot: Pilot[int], panel: TemplatePanel, label: str) -> None:
    await pilot.click(button_named(panel, label))
    await pilot.pause()


async def type_in(pilot: Pilot[int], app: BuskApp, text: str) -> None:
    field = app.screen.query_one(Input)
    field.value = text
    await pilot.press("enter")
    await settle(pilot, app)


async def fill_form(pilot: Pilot[int], app: BuskApp, *values: str) -> None:
    fields = list(app.screen.query(Input))
    assert len(fields) == len(values)
    for field, value in zip(fields, values, strict=True):
        field.value = value
    fields[0].focus()
    await pilot.press("enter")
    await settle(pilot, app)


# ------------------------------------------------------------- the words


def test_the_attributes_are_the_ones_busk_lets_a_wave_drive() -> None:
    assert (
        tuple(
            attribute
            for attribute, definition in BUSK_ATTRIBUTES.items()
            if definition.kind == "scalar" and definition.fade == "fade"
        )
        == ATTRIBUTES
    )


@pytest.mark.parametrize(
    "wave",
    [
        SineWave,
        TriangleWave,
        SquareWave,
        SawUpWave,
        SawDownWave,
        PulseWave,
        StepWave,
        RandomWave,
        CurveWave,
    ],
)
def test_each_waveform_starts_with_what_busk_needs_of_it(wave: type) -> None:
    hints = get_type_hints(wave)
    kind = get_args(hints.pop("kind"))[0]
    assert set(WAVES[kind]) == set(hints)


def test_every_waveform_of_busk_is_offered() -> None:
    assert set(WAVES) == {
        "sine", "triangle", "square", "sawUp", "sawDown", "pulse", "step", "random", "curve",
    }  # fmt: skip


def test_a_layer_is_worded_as_busk_words_it() -> None:
    assert layer_text(SINE) == "pan add sine +90°"
    assert layer_text(COLOUR) == "color fade 2 colours"
    assert layer_text(COLOUR | {"palette": [{"r": 1.0, "g": 1.0, "b": 1.0}]}) == (
        "color fade 1 colour"
    )
    assert layer_text(wave_layer({"kind": "square", "duty": 0.5}, phaseOffset=-30.0)) == (
        "intensity add square -30°"
    )


@pytest.mark.parametrize(
    ("text", "problem"), [("0", False), ("1", False), ("0.25", False), ("1.5", True), ("-1", True)]
)
def test_a_level_is_from_0_to_1(text: str, problem: bool) -> None:
    assert bool(check_unit(text)) is problem


def test_the_checks_of_the_other_values() -> None:
    assert check_degrees("-90.5") is None
    assert check_degrees("x")
    assert check_seed("7") is None
    assert check_seed("-1")
    assert check_seed("1.5")
    assert check_rgb(("1", "0", "0.5")) is None
    assert check_rgb(("1", "0", "2"))


def test_steps_and_points_are_read_as_typed() -> None:
    assert read_steps("0 0.5, 1") == [0.0, 0.5, 1.0]
    assert read_steps("") is None
    assert read_steps("0 2") is None
    assert read_points("0 0, 0.5 1, 1 0") == [[0.0, 0.0], [0.5, 1.0], [1.0, 0.0]]
    assert read_points("0 0, 1") is None
    assert read_points("0 2") is None
    assert check_steps("0 1") is None
    assert check_steps("")
    assert check_points("0 0, 1 1") is None
    assert check_points("0 0 0")


def test_a_template_name_is_checked_by_busks_rule() -> None:
    check = check_template_name(["Beat", "Solo"], "Beat")
    assert check("New") is None
    assert check("BEAT") is None  # its own name, in another case
    assert check("solo")
    assert check("SOLO")
    assert check("  ")
    assert check_template_name(["Beat"])("beat")


def test_a_refusal_says_what_is_wrong_without_the_place_in_the_document() -> None:
    reply = (
        "updated effect template 'T1': 1 layer: rejected, the show would not be valid\n"
        "  effects[4].layers[0].waveform: A pulse's sum must be at most 1\n"
        "  effects[4].layers[0].attribute: No such attribute"
    )
    assert refusal_reason(reply) == "A pulse's sum must be at most 1\nNo such attribute"
    assert refusal_reason("a template named 'Circle' exists") == "a template named 'Circle' exists"


# -------------------------------------------------------- opening the panel


def test_edit_opens_the_panel_in_the_place_of_the_templates() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        templates_panel = app.query_one("#templates-panel")
        panel = await open_template(pilot, app)
        assert (panel.display, templates_panel.display) == (True, False)
        assert panel.border_title is not None
        assert "Beat" in str(panel.border_title)
        assert column(panel.layer_table, "what") == ["pan add sine +90°", "color fade 2 colours"]
        assert bridge.sent == []
        await press_button(pilot, panel, "done")
        await settle(pilot, app)
        assert (panel.display, templates_panel.display) == (False, True)

    drive(app, body)


def test_a_click_anywhere_else_on_a_template_still_adds_it() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        templates = app.query_one(TemplateTable)
        assert column(templates, "edit") == ["[edit]", "[edit]", "[view]"]
        await click_cell(pilot, templates, 1, "name")
        assert [s.line for s in bridge.sent] == ['effect add "Solo"']

    drive(app, body)


def test_the_effect_panel_and_the_template_panel_take_turns() -> None:
    bridge = FakeBridge()
    effect = EffectInfo("fx1", "Solo", Targets(elements=((101, 1),)), rate="hz 1")
    cue_list = CueListInfo(1, "L", "sequence", None, (CueInfo("1", "C", (effect,)),))
    app = on_f5(bridge, BEAT, SOLO, cueLists=(cue_list,))

    async def body(pilot: Pilot[int]) -> None:
        template = await open_template(pilot, app)
        effect_panel = app.query_one(EffectPanel)
        await click_cell(pilot, app.query_one(EffectTable), 0, "template")
        await settle(pilot, app)
        assert (effect_panel.display, template.display) == (True, False)

    drive(app, body)


def test_a_library_template_shows_its_layers_and_cannot_change() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app, 2)
        assert plain(panel.what) == "intensity absolute square"
        assert "the library's" in plain(panel.used)
        assert not panel.editing.display
        assert [stop.item.label for stop in panel.stops()] == ["done"]
        assert bridge.sent == []

    drive(app, body)


def test_a_library_template_becomes_editable_once_the_show_holds_it() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app, 2)
        copied = TemplateInfo(
            "Chase", "show", "intensity add sine", id="ef-chase", layers=(NEW_WAVE,)
        )
        bridge.events.append(ShowChanged(template_show(BEAT, SOLO, copied)))
        await settle(pilot, app)
        assert panel.display
        assert panel.editing.display
        assert column(panel.layer_table, "what") == ["intensity multiply sine"]

    drive(app, body)


# -------------------------------------------------------------- the layers


def test_a_wave_layer_has_a_chip_per_choice_and_each_is_one_line() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        assert panel.scalar.display
        assert not panel.colour.display
        await click_chip(pilot, panel.attribute, "tilt")
        await click_chip(pilot, panel.modes, "multiply")
        await click_chip(pilot, panel.wave, "triangle")
        assert [s.line for s in bridge.sent] == [
            update([SINE | {"attribute": "tilt"}, COLOUR]),
            update([SINE | {"mode": "multiply"}, COLOUR]),
            update([SINE | {"waveform": {"kind": "triangle"}}, COLOUR]),
        ]

    drive(app, body)


def test_the_lit_chip_sends_nothing() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await click_chip(pilot, panel.attribute, "pan")
        await click_chip(pilot, panel.modes, "add")
        await click_chip(pilot, panel.wave, "sine")
        assert bridge.sent == []

    drive(app, body)


@pytest.mark.parametrize(
    ("wave", "shown"),
    [
        ({"kind": "square", "duty": 0.5}, ("duty",)),
        (
            {"kind": "pulse", "width": 0.2, "attack": 0.1, "decay": 0.1},
            ("width", "attack", "decay"),
        ),
        ({"kind": "step", "steps": [0.0, 1.0]}, ("steps",)),
        ({"kind": "random", "smooth": True, "seed": 3}, ("seed", "smooth")),
        ({"kind": "curve", "points": [[0.0, 0.0], [1.0, 1.0]]}, ("points",)),
        ({"kind": "sine"}, ()),
    ],
)
def test_a_waveform_shows_what_it_takes(wave: dict[str, Any], shown: tuple[str, ...]) -> None:
    template = TemplateInfo("W", "show", "w", id="w", layers=(wave_layer(wave),))
    app = on_f5(FakeBridge(), template)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        settings = {**panel.numbers, "steps": panel.steps, "points": panel.points}
        settings["smooth"] = panel.smooth_row
        assert {name for name, row in settings.items() if row.display} == set(shown)

    drive(app, body)


@pytest.mark.parametrize("kind", sorted(WAVES))
def test_changing_to_a_waveform_gives_it_what_it_takes(kind: str) -> None:
    bridge = FakeBridge()
    app = on_f5(bridge, SOLO)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        if kind == "sine":
            return
        await click_chip(pilot, panel.wave, kind)
        layer = NEW_WAVE | {"waveform": {"kind": kind} | WAVES[kind]}
        assert [s.line for s in bridge.sent] == [update([layer], "Solo")]

    drive(app, body)


@pytest.mark.parametrize(
    ("button", "wave", "typed", "changed"),
    [
        ("duty…", {"kind": "square", "duty": 0.5}, "0.75", {"duty": 0.75}),
        ("seed…", {"kind": "random", "smooth": True, "seed": 3}, "9", {"seed": 9}),
        ("steps…", {"kind": "step", "steps": [0.0, 1.0]}, "0 0.5, 1", {"steps": [0.0, 0.5, 1.0]}),
        (
            "points…",
            {"kind": "curve", "points": [[0.0, 0.0], [1.0, 1.0]]},
            "0 1, 1 0",
            {"points": [[0.0, 1.0], [1.0, 0.0]]},
        ),
    ],
)
def test_a_waveforms_number_is_one_line(
    button: str, wave: dict[str, Any], typed: str, changed: dict[str, Any]
) -> None:
    bridge = FakeBridge()
    layer = wave_layer(wave)
    template = TemplateInfo("W", "show", "w", id="w", layers=(layer,))
    app = on_f5(bridge, template)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await press_button(pilot, panel, button)
        assert isinstance(app.screen, TextDialog)
        await type_in(pilot, app, typed)
        assert [s.line for s in bridge.sent] == [
            update([layer | {"waveform": wave | changed}], "W")
        ]

    drive(app, body)


@pytest.mark.parametrize(
    ("button", "wave", "start"),
    [
        ("duty…", {"kind": "square", "duty": 0.5}, "0.5"),
        ("seed…", {"kind": "random", "smooth": True, "seed": 3}, "3"),
        ("steps…", {"kind": "step", "steps": [0.0, 1.0]}, "0 1"),
        ("points…", {"kind": "curve", "points": [[0.0, 0.0], [1.0, 1.0]]}, "0 0, 1 1"),
    ],
)
def test_a_value_left_as_it_was_sends_nothing(
    button: str, wave: dict[str, Any], start: str
) -> None:
    bridge = FakeBridge()
    template = TemplateInfo("W", "show", "w", id="w", layers=(wave_layer(wave),))
    app = on_f5(bridge, template)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await press_button(pilot, panel, button)
        assert app.screen.query_one(Input).value == start
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.sent == []

    drive(app, body)


def test_a_pulse_has_a_row_for_each_part() -> None:
    bridge = FakeBridge()
    wave = {"kind": "pulse", "width": 0.2, "attack": 0.1, "decay": 0.1}
    layer = wave_layer(wave)
    template = TemplateInfo("W", "show", "w", id="w", layers=(layer,))
    app = on_f5(bridge, template)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await press_button(pilot, panel, "attack…")
        await type_in(pilot, app, "0.3")
        assert [s.line for s in bridge.sent] == [
            update([layer | {"waveform": wave | {"attack": 0.3}}], "W")
        ]

    drive(app, body)


def test_a_dialog_refuses_what_could_not_be_sent() -> None:
    bridge = FakeBridge()
    template = TemplateInfo(
        "W", "show", "w", id="w", layers=(wave_layer({"kind": "square", "duty": 0.5}),)
    )
    app = on_f5(bridge, template)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await press_button(pilot, panel, "duty…")
        await type_in(pilot, app, "2")
        assert isinstance(app.screen, TextDialog)
        assert bridge.sent == []

    drive(app, body)


def test_smooth_toggles_and_reads_what_a_click_does() -> None:
    bridge = FakeBridge()
    wave = {"kind": "random", "smooth": True, "seed": 3}
    layer = wave_layer(wave)
    template = TemplateInfo("W", "show", "w", id="w", layers=(layer,))
    app = on_f5(bridge, template)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        assert panel.smooth.label == "smooth off"
        assert plain(panel.smooth_row.value) == "on"
        await pilot.click(panel.smooth)
        await pilot.pause()
        assert bridge.sent[-1].line == update([layer | {"waveform": wave | {"smooth": False}}], "W")
        off = TemplateInfo("W", "show", "w", id="w", layers=(wave_layer(wave | {"smooth": False}),))
        bridge.events.append(ShowChanged(template_show(off)))
        await settle(pilot, app)
        assert panel.smooth.label == "smooth on"
        assert plain(panel.smooth_row.value) == "off"

    drive(app, body)


def test_a_phase_offset_left_as_it_was_sends_nothing() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await press_button(pilot, panel, "offset…")
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.sent == []

    drive(app, body)


def test_the_phase_offset_is_one_line() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        assert plain(panel.offset_row.value) == "90°"
        await press_button(pilot, panel, "offset…")
        await type_in(pilot, app, "-45.5")
        assert [s.line for s in bridge.sent] == [update([SINE | {"phaseOffset": -45.5}, COLOUR])]

    drive(app, body)


def test_the_chosen_layer_moves_up_when_it_is_gone() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        panel.choose_layer(1)
        single = TemplateInfo("Beat", "show", "s", id="ef-beat", layers=(SINE,))
        bridge.events.append(ShowChanged(template_show(single)))
        await settle(pilot, app)
        assert panel.layer_table.chosen == 0
        assert panel.scalar.display

    drive(app, body)


def test_a_click_on_a_layer_chooses_it_for_the_controls() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await click_cell(pilot, panel.layer_table, 1, "what")
        await pilot.pause()
        assert panel.layer_table.chosen == 1
        assert panel.colour.display
        assert not panel.scalar.display
        assert bridge.sent == []

    drive(app, body)


def test_the_x_takes_a_layer_out_and_the_last_has_none() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await click_cell(pilot, panel.layer_table, 0, "remove")
        await pilot.pause()
        assert [s.line for s in bridge.sent] == [update([COLOUR])]
        single = TemplateInfo("Beat", "show", "s", id="ef-beat", layers=(COLOUR,))
        bridge.events.append(ShowChanged(template_show(single)))
        await settle(pilot, app)
        assert "remove" not in panel.layer_table.rows[0]
        await click_cell(pilot, panel.layer_table, 0, "remove")
        await pilot.pause()
        assert len(bridge.sent) == 1

    drive(app, body)


@pytest.mark.parametrize("show_first", [False, True])
def test_a_layer_is_added_last_and_chosen_once_it_has_run(show_first: bool) -> None:
    bridge = FakeBridge()
    app = on_f5(bridge, SOLO)
    added = (NEW_WAVE, NEW_COLOUR)
    grown = ShowChanged(
        template_show(TemplateInfo("Solo", "show", "s", id="ef-solo", layers=added))
    )

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        bridge.auto_reply = False
        await press_button(pilot, panel, "+ colour")
        assert bridge.sent[-1].line == update([NEW_WAVE, NEW_COLOUR], "Solo")
        ticket = bridge.sent[-1].ticket
        done = CommandDone(ticket, bridge.sent[-1].line, "ui", True, (), 0.0, False)
        bridge.events += [grown, done] if show_first else [done, grown]
        await settle(pilot, app)
        assert panel.layer_table.chosen == 1
        assert panel.colour.display

    drive(app, body)


def test_a_second_colour_layer_is_grey() -> None:
    app = on_f5(FakeBridge())

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        assert button_named(panel, "+ colour").inert
        assert not button_named(panel, "+ wave").inert

    drive(app, body)


def test_a_colour_layer_has_its_blend_and_palette() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await click_cell(pilot, panel.layer_table, 1, "what")
        await pilot.pause()
        assert column(panel.palette, "what") == ["1 0.5 0", "preset Blue"]
        await click_chip(pilot, panel.blend, "snap")
        assert [s.line for s in bridge.sent] == [update([SINE, COLOUR | {"blend": "snap"}])]

    drive(app, body)


def test_a_colour_of_the_palette_is_edited_and_keeps_its_extra_emitters() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await click_cell(pilot, panel.layer_table, 1, "what")
        await pilot.pause()
        await click_cell(pilot, panel.palette, 0, "what")
        await pilot.pause()
        assert isinstance(app.screen, FormDialog)
        assert [field.value for field in app.screen.query(Input)] == ["1", "0.5", "0"]
        await fill_form(pilot, app, "0", "0.5", "1")
        entry = {"r": 0.0, "g": 0.5, "b": 1.0, "w": 0.25}
        palette = [entry, {"presetId": "pr-blue"}]
        assert [s.line for s in bridge.sent] == [update([SINE, COLOUR | {"palette": palette}])]

    drive(app, body)


def test_an_unchanged_colour_sends_nothing_and_a_preset_opens_no_form() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await click_cell(pilot, panel.layer_table, 1, "what")
        await pilot.pause()
        await click_cell(pilot, panel.palette, 1, "what")
        await pilot.pause()
        assert not isinstance(app.screen, FormDialog)
        await click_cell(pilot, panel.palette, 0, "what")
        await pilot.pause()
        await fill_form(pilot, app, "1", "0.5", "0")
        assert bridge.sent == []

    drive(app, body)


def test_a_colour_is_added_and_a_preset_by_its_chip() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await click_cell(pilot, panel.layer_table, 1, "what")
        await pilot.pause()
        await press_button(pilot, panel, "+ colour…")
        await fill_form(pilot, app, "0", "1", "0")
        await click_chip(pilot, panel.preset_chips, "Red")
        assert [s.line for s in bridge.sent] == [
            update(
                [SINE, COLOUR | {"palette": [*COLOUR["palette"], {"r": 0.0, "g": 1.0, "b": 0.0}]}]
            ),
            update([SINE, COLOUR | {"palette": [*COLOUR["palette"], {"presetId": "pr-red"}]}]),
        ]

    drive(app, body)


def test_only_a_colour_preset_is_offered() -> None:
    app = on_f5(FakeBridge())

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await click_cell(pilot, panel.layer_table, 1, "what")
        await pilot.pause()
        assert [button.label.plain for button in panel.preset_chips.buttons] == ["[Blue]", "[Red]"]

    drive(app, body)


def test_the_palette_keeps_its_last_colour() -> None:
    bridge = FakeBridge()
    only = COLOUR | {"palette": [{"r": 1.0, "g": 1.0, "b": 1.0}]}
    template = TemplateInfo("Beat", "show", "b", id="ef-beat", layers=(only,))
    app = on_f5(bridge, template)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        assert "remove" not in panel.palette.rows[0]
        await click_cell(pilot, panel.palette, 0, "remove")
        await pilot.pause()
        assert bridge.sent == []

    drive(app, body)


def test_a_palette_entry_is_taken_out() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await click_cell(pilot, panel.layer_table, 1, "what")
        await pilot.pause()
        await click_cell(pilot, panel.palette, 0, "remove")
        await pilot.pause()
        palette = [{"presetId": "pr-blue"}]
        assert [s.line for s in bridge.sent] == [update([SINE, COLOUR | {"palette": palette}])]

    drive(app, body)


# ---------------------------------------------------------------- refusals


def test_a_refusal_shows_in_the_panel_and_the_log_until_the_next_line() -> None:
    bridge = FakeBridge()
    line = update([SINE | {"mode": "absolute"}, COLOUR])
    reply = (
        "error: updated effect template 'Beat': 2 layers: rejected, the show would not be valid\n"
        "  cueLists[0].cues[0].effects[0].low: low is required: 'pan' has no fixed range to sweep"
    )
    bridge.replies[line] = busk.Reply(reply, ok=False)
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        assert not panel.refusal.display
        await click_chip(pilot, panel.modes, "absolute")
        await settle(pilot, app)
        assert panel.refusal.display
        assert plain(panel.refusal) == "low is required: 'pan' has no fixed range to sweep"
        log = app.query_one(LogView).entries
        kinds = [kind for kind, text in log if "low is required" in text]
        assert kinds == ["error"]
        await click_chip(pilot, panel.modes, "multiply")
        assert not panel.refusal.display

    drive(app, body)


def test_a_refusal_in_another_template_does_not_show() -> None:
    bridge = FakeBridge()
    line = update([SINE | {"attribute": "tilt"}, COLOUR])
    bridge.replies[line] = busk.Reply("error: no", ok=False)
    bridge.auto_reply = False
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await click_chip(pilot, panel.attribute, "tilt")
        await press_button(pilot, panel, "done")
        panel = await open_template(pilot, app, 1)
        ticket = bridge.sent[0].ticket
        app._refusals[ticket]("error: no")
        await pilot.pause()
        assert not panel.refusal.display

    drive(app, body)


def test_a_refused_new_layer_is_not_chosen() -> None:
    bridge = FakeBridge()
    line = update([NEW_WAVE, NEW_COLOUR], "Solo")
    bridge.replies[line] = busk.Reply("error: no", ok=False)
    app = on_f5(bridge, SOLO)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await press_button(pilot, panel, "+ colour")
        await settle(pilot, app)
        assert panel.layer_table.chosen == 0
        assert panel.scalar.display
        grown = TemplateInfo("Solo", "show", "s", id="ef-solo", layers=(NEW_WAVE, NEW_COLOUR))
        bridge.events.append(ShowChanged(template_show(grown)))  # another line added one
        await settle(pilot, app)
        assert panel.layer_table.chosen == 0

    drive(app, body)


# ------------------------------------------------- rename, delete, new ones


def test_rename_is_one_line_and_refuses_a_name_the_show_has() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await press_button(pilot, panel, "rename…")
        await type_in(pilot, app, "solo")
        assert isinstance(app.screen, TextDialog)
        assert bridge.sent == []
        await type_in(pilot, app, "Pulse 2")
        assert [s.line for s in bridge.sent] == ['effect template rename "Beat" "Pulse 2"']

    drive(app, body)


def test_a_rename_to_a_library_templates_name_is_left_to_busk() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await press_button(pilot, panel, "rename…")
        await type_in(pilot, app, "Chase")
        assert [s.line for s in bridge.sent] == ['effect template rename "Beat" "Chase"']

    drive(app, body)


def test_a_name_left_as_it_was_sends_nothing() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        await press_button(pilot, panel, "rename…")
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.sent == []

    drive(app, body)


def test_the_panel_stays_on_a_template_through_a_rename() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge, BEAT, SOLO)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        renamed = TemplateInfo("Pulse", "show", "p", id="ef-beat", layers=(SINE, COLOUR))
        bridge.events.append(ShowChanged(template_show(renamed, SOLO)))
        await settle(pilot, app)
        assert panel.display
        assert "Pulse" in str(panel.border_title)

    drive(app, body)


def test_the_panel_closes_once_the_template_is_gone() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge, BEAT, SOLO)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        bridge.events.append(ShowChanged(template_show(SOLO)))
        await settle(pilot, app)
        assert not panel.display
        assert app.query_one("#templates-panel").display

    drive(app, body)


def test_delete_asks_first_and_goes_grey_while_it_is_used() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge, BEAT, SOLO)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        assert plain(panel.used) == "used by nothing"
        assert not panel.delete.inert
        await press_button(pilot, panel, "delete")
        assert isinstance(app.screen, ConfirmDialog)
        assert app.screen.question == 'Delete effect template "Beat"?'
        await pilot.press("y")
        await settle(pilot, app)
        assert [s.line for s in bridge.sent] == ['effect template delete "Beat"']

    drive(app, body)


@pytest.mark.parametrize(
    ("changes", "words"),
    [
        ({"used_by": ((9, "1"), (9, "2"))}, "cue 9/1–9/2"),
        ({"bindings": 2}, "2 bindings"),
        ({"bindings": 1}, "1 binding"),
    ],
)
def test_the_panel_names_what_uses_the_template(changes: dict[str, Any], words: str) -> None:
    used = TemplateInfo("Beat", "show", "b", id="ef-beat", layers=(SINE,), **changes)
    lists = (CueListInfo(9, "L", "sequence", None, (CueInfo("1", "A", ()), CueInfo("2", "B", ()))),)
    app = on_f5(FakeBridge(), used, cueLists=lists)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        assert plain(panel.used).startswith(f"used by {words}\n")
        assert panel.delete.inert

    drive(app, body)


def test_the_programmer_counts_as_a_user() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        effect = EffectInfo("fx1", "Beat", Targets(elements=((101, 1),)), rate="hz 1")
        bridge.events.append(ProgrammerChanged(programmer(version=2, effects=(effect,))))
        await settle(pilot, app)
        assert plain(panel.used).startswith("used by the programmer\n")
        assert panel.delete.inert

    drive(app, body)


def test_a_new_template_is_named_and_starts_with_its_first_layer() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click("#templates-add")
        await pilot.pause()
        assert isinstance(app.screen, NewTemplateDialog)
        await type_in(pilot, app, "Fresh")
        assert [s.line for s in bridge.sent] == [
            commands.effect_template_add("Fresh", [NEW_WAVE]).text
        ]

    drive(app, body)


def test_a_new_template_can_start_with_a_colour() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click("#templates-add")
        await pilot.pause()
        app.screen.query_one(PickRow).pick("colour")
        await type_in(pilot, app, "Fresh")
        assert [s.line for s in bridge.sent] == [
            commands.effect_template_add("Fresh", [NEW_COLOUR]).text
        ]

    drive(app, body)


def test_a_new_template_refuses_a_name_the_show_has_and_an_empty_one() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click("#templates-add")
        await pilot.pause()
        await type_in(pilot, app, "beat")
        assert isinstance(app.screen, NewTemplateDialog)
        await type_in(pilot, app, "")
        assert isinstance(app.screen, NewTemplateDialog)
        assert bridge.sent == []
        await pilot.press("escape")
        await settle(pilot, app)
        assert bridge.sent == []

    drive(app, body)


def test_a_new_template_opens_once_the_show_has_it() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge, BEAT, SOLO)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click("#templates-add")
        await pilot.pause()
        await type_in(pilot, app, "Fresh")
        panel = panel_of(app)
        assert not panel.display  # the show has not got it yet
        fresh = TemplateInfo("Fresh", "show", "f", id="ef-new", layers=(NEW_WAVE,))
        bridge.events.append(ShowChanged(template_show(BEAT, SOLO, fresh)))
        await settle(pilot, app)
        assert panel.display
        assert "Fresh" in str(panel.border_title)

    drive(app, body)


def test_a_new_template_the_show_got_first_opens_too() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge, BEAT, SOLO)
    fresh = TemplateInfo("Fresh", "show", "f", id="ef-new", layers=(NEW_WAVE,))

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click("#templates-add")
        await pilot.pause()
        bridge.events.append(ShowChanged(template_show(BEAT, SOLO, fresh)))
        await type_in(pilot, app, "Fresh")
        await settle(pilot, app)
        panel = panel_of(app)
        assert panel.display
        assert "Fresh" in str(panel.border_title)

    drive(app, body)


def test_a_refused_new_template_opens_nothing() -> None:
    bridge = FakeBridge()
    line = commands.effect_template_add("Fresh", [NEW_WAVE]).text
    bridge.replies[line] = busk.Reply("error: no", ok=False)
    app = on_f5(bridge, BEAT, SOLO)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click("#templates-add")
        await pilot.pause()
        await type_in(pilot, app, "Fresh")
        assert not panel_of(app).display
        fresh = TemplateInfo("Fresh", "show", "f", id="ef-new", layers=(NEW_WAVE,))
        bridge.events.append(ShowChanged(template_show(BEAT, SOLO, fresh)))  # typed at the prompt
        await settle(pilot, app)
        assert not panel_of(app).display

    drive(app, body)


def test_a_new_template_named_as_a_library_one_waits_for_the_shows() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click("#templates-add")
        await pilot.pause()
        await type_in(pilot, app, "Chase")
        panel = panel_of(app)
        assert not panel.display  # the listed Chase is the library's
        own = TemplateInfo("Chase", "show", "f", id="ef-new", layers=(NEW_WAVE,))
        bridge.events.append(ShowChanged(template_show(BEAT, SOLO, own)))
        await settle(pilot, app)
        assert panel.display
        assert panel.editing.display

    drive(app, body)


# ------------------------------------------------------- reaching the controls


def test_the_pane_cursor_reaches_the_controls_of_a_wave_layer() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        labels = [stop.item.label for stop in panel.stops()]
        assert labels[:7] == [
            "rename…", "delete", "layer 1", "layer 1 ✕", "layer 2", "layer 2 ✕", "+ wave",
        ]  # fmt: skip
        assert "+ colour" not in labels  # grey: the template has its colour layer
        assert update([SINE | {"attribute": "tilt"}, COLOUR]) in labels
        assert labels[-2:] == ["offset offset…", "done"]

    drive(app, body)


def test_the_pane_cursor_reaches_the_controls_of_a_colour_layer() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        panel.choose_layer(1)
        await pilot.pause()
        labels = [stop.item.label for stop in panel.stops()]
        assert "colour 1" in labels
        assert "colour 2 ✕" in labels
        assert "+ colour…" in labels
        assert update([SINE, COLOUR | {"blend": "snap"}]) in labels
        assert labels[-1] == "done"

    drive(app, body)


def test_the_page_stops_on_the_panel_while_it_is_open() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await open_template(pilot, app)
        labels = [item.label for item in app.current_page.items()]
        assert "rename…" in labels
        assert not any(label.startswith('effect add "') for label in labels)

    drive(app, body)


def test_the_panel_goes_under_the_effects_below_132_columns() -> None:
    app = on_f5(FakeBridge())

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_template(pilot, app)
        effects = app.query_one("#effects-panel")
        assert panel.region.y > effects.region.y
        assert panel.region.width == effects.region.width

    drive(app, body, size=(100, 48))
