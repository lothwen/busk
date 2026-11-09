"""F5 Effects (spec §8.5, plan Phase 3): the cue and programmer effects
formatted alike, their state from what runs (and the stopped ones), the
sparkline and the live rate, the state and ``✕`` lines, the templates, and
the pane cursor. Headless, with a fake bridge."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

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

from busk_tui import colors
from busk_tui.commands import Line
from busk_tui.model import (
    ChaseRate,
    CueInfo,
    CueListInfo,
    EffectInfo,
    EffectsChanged,
    EffectsModel,
    EffectView,
    FixtureInfo,
    GroupInfo,
    LiveChanged,
    MasterView,
    PlaybackInfo,
    ProgrammerChanged,
    ShowChanged,
    ShowModel,
    Targets,
    TemplateInfo,
)
from busk_tui.pages.effects import EffectsPage
from busk_tui.shell import BuskApp
from busk_tui.widgets.controls import ActionButton, ButtonStrip
from busk_tui.widgets.dialogs import ConfirmDialog, TextDialog
from busk_tui.widgets.effect_panel import (
    EffectPanel,
    EffectRateDialog,
    check_count,
    check_level,
    check_seconds,
    check_size,
    check_two,
    effect_settings,
    levels_text,
    number_text,
    why_fixed,
)
from busk_tui.widgets.effects import EffectTable, FxRow, TemplateTable, effect_rows, fx_cells
from busk_tui.widgets.options import LIT

HEADS = Targets(group=GroupInfo(1, "Heads"))
CIRCLE = EffectInfo("fx1", "Circle", HEADS, rate="bpm x 0.5", size=15.0, phase=(0.0, 180.0))
RAINBOW = EffectInfo(
    "rainbow",
    "Rainbow",
    Targets(group=GroupInfo(3, "Bar")),
    rate="hz 0.25",
    direction="bounce",
    phase=(0.0, 360.0),
    wings=2,
    groups=3,
)
WAVE = EffectInfo("fx3", "Wave", HEADS, rate="bpm x 1", low=0.0, high=1.0)
SONG = CueListInfo(
    9,
    "Song",
    "sequence",
    None,
    (CueInfo("1", "Intro", ()), CueInfo("4", "Chorus", (RAINBOW,)), CueInfo("5", "Outro", ())),
)
CIRCLES = CueListInfo(11, "Circle", "sequence", None, (CueInfo("1", "Circle", (CIRCLE,)),))
SPARE = CueListInfo(21, "Spare", "sequence", None, (CueInfo("1", "Wave", (WAVE,)),))
TEMPLATES = (
    TemplateInfo("Circle", "show", "pan add sine, tilt add sine +90°", size=20.0),
    TemplateInfo("Wave", "show", "intensity absolute sine", low=0.0, high=1.0),
    TemplateInfo("Mine", "show", "intensity add sine"),
    TemplateInfo("Chase", "library", "intensity absolute square", phase=(0.0, 360.0)),
)
PROG = (
    EffectInfo("fx5", "Circle", Targets(elements=((101, 1), (102, 1))), rate="bpm x 1", size=20.0),
    EffectInfo("fx6", "Chase", HEADS, rate="bpm x 2"),
)


def fx_show(**changes: Any) -> ShowModel:
    parts: dict[str, Any] = {
        "playbacks": (PlaybackInfo(9, "Song", 9, None), PlaybackInfo(11, "Circle", 11, None)),
        "cueLists": (SONG, CIRCLES, SPARE),
        "fixtures": (FixtureInfo(101, 1), FixtureInfo(102, 1)),
        "templates": TEMPLATES,
    }
    parts.update(changes)
    return show_model(**parts)


def view(playback: int | None, cue: str | None, ident: str, **changes: Any) -> EffectView:
    parts: dict[str, Any] = {
        "playback": playback,
        "cue": cue,
        "id": ident,
        "presence": 1.0,
        "size": 1.0,
        "hz": 0.25,
        "phase": 0.0,
        "wave": (),
        "colors": (),
    }
    parts.update(changes)
    return EffectView(**parts)


RUNNING = EffectsModel(
    1,
    (
        view(9, "4", "rainbow", colors=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))),  # tracked into cue 5
        view(None, None, "fx5", presence=0.5, hz=2.0, wave=(0.0, 0.5, 1.0, 0.5)),
    ),
)


def on_f5(bridge: FakeBridge, effects: EffectsModel = RUNNING) -> BuskApp:
    bridge.events += [
        ShowChanged(fx_show()),
        LiveChanged(live_state()),
        ProgrammerChanged(programmer(effects=PROG, stopped=frozenset({"fx6"}))),
        EffectsChanged(effects),
    ]
    return make_app(bridge, page=5)


def plain(widget: Any) -> str:
    rendered = widget.content if hasattr(widget, "content") else widget.render()
    return rendered.plain if isinstance(rendered, Text) else str(rendered)


def test_rows_for_cue_and_programmer_effects_formatted_alike() -> None:
    show = fx_show()
    rows = effect_rows(show, programmer(effects=PROG, stopped=frozenset({"fx6"})), RUNNING)
    cells = [fx_cells(row, show, "256") for row in rows]
    table = [
        tuple(c[name].plain for name in ("owner", "id", "template", "targets", "rate", "size",
                                          "phase", "wings", "state", "remove"))
        for c in cells
    ]  # fmt: skip
    assert table == [
        (
            "9/4",
            "rainbow",
            "Rainbow",
            "Bar",
            "hz 0.25 bounce",
            "1",
            "0→360",
            "2 g3 b1",
            "[RUN]",
            "✕",
        ),
        ("11/1", "fx1", "Circle", "Heads", "bpm x 0.5", "15", "0→180", "1", "[off]", "✕"),
        ("21/1", "fx3", "Wave", "Heads", "bpm x 1", "0–1", "0→0", "1", "—", "✕"),
        ("prog", "fx5", "Circle", "101 thru 102", "bpm x 1", "20", "0→0", "1", "[RUN]", "✕"),
        ("prog", "fx6", "Chase", "Heads", "bpm x 2", "1", "0→0", "1", "[off]", "✕"),
    ]
    assert [c["hz"].plain for c in cells] == ["0.25", "·", "·", "2.00", "·"]
    assert [None if row.toggle is None else row.toggle.text for row in rows] == [
        "release 9",
        "goto 11 1",
        None,  # no playback runs list 21
        "effect stop fx5",
        "effect run fx6",
    ]
    assert [row.remove.text for row in rows] == [
        "cue 9/4 effect rainbow remove",
        "cue 11/1 effect fx1 remove",
        "cue 21/1 effect fx3 remove",
        "effect remove fx5",
        "effect remove fx6",
    ]


def test_the_state_and_the_wave() -> None:
    show = fx_show()
    rows = effect_rows(show, programmer(effects=PROG, stopped=frozenset({"fx6"})), RUNNING)
    rainbow, circle, _, fx5, fx6 = (fx_cells(row, show, "256") for row in rows)
    assert str(rainbow["state"].spans[0].style) == colors.GREEN
    assert str(fx5["state"].spans[0].style) == f"{colors.GREEN} dim"  # fading in
    assert str(fx6["state"].spans[0].style) == colors.DIM
    assert fx5["wave"].plain == "▁▁▁▁▁▅▅▅▅▅█████▅▅▅▅▅"
    assert rainbow["wave"].plain == "█" * 20  # a colour cycle: its hues at full height
    hues = {str(span.style) for span in rainbow["wave"].spans}
    assert hues == {"color(196)", "color(46)"}
    assert circle["wave"].plain == "▁" * 20  # not running: flat
    assert fx6["wave"].plain == "▁" * 20


def test_a_cue_effect_runs_while_its_playback_holds_it() -> None:
    """A tracked effect keeps the cue that defines it; another playback's
    effect with the same id is not this row's."""
    show = fx_show()
    elsewhere = EffectsModel(2, (view(11, "1", "rainbow"), view(9, "5", "rainbow")))
    rows = effect_rows(show, None, elsewhere)
    assert [row.running for row in rows] == [False, False, False]
    assert rows[0].toggle is not None
    assert rows[0].toggle.text == "goto 9 4"


def test_the_page_shows_the_rows_and_its_clicks_run_their_lines() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        assert bridge.watching == (False, True)
        table = app.query_one(EffectTable)
        assert column(table, "owner") == ["9/4", "11/1", "21/1", "prog", "prog"]
        panel = app.query_one("#effects-panel")
        assert str(panel.border_title) == "EFFECTS · 3 in cues · 2 in the programmer"
        await click_cell(pilot, table, 0, "state")
        await click_cell(pilot, table, 1, "state")
        await click_cell(pilot, table, 2, "state")  # no playback: nothing
        await click_cell(pilot, table, 3, "state")
        await click_cell(pilot, table, 4, "remove")
        await click_cell(pilot, table, 1, "template")  # opens its settings, sends nothing
        assert [(s.line, s.origin, s.performance) for s in bridge.sent] == [
            ("release 9", "ui", True),
            ("goto 11 1", "ui", True),
            ("effect stop fx5", "ui", False),
            ("effect remove fx6", "ui", False),
        ]

    drive(app, body)


def test_the_rows_follow_what_runs() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        table = app.query_one(EffectTable)
        assert column(table, "state")[:2] == ["[RUN]", "[off]"]
        bridge.events.append(EffectsChanged(EffectsModel(2, (view(11, "1", "fx1", hz=1.0),))))
        await settle(pilot, app)
        assert column(table, "state")[:2] == ["[off]", "[RUN]"]
        assert column(table, "hz")[:2] == ["·", "1.00"]
        bridge.events.append(ProgrammerChanged(programmer(version=2)))
        await settle(pilot, app)
        assert column(table, "owner") == ["9/4", "11/1", "21/1"]

    drive(app, body)


def test_the_templates_and_what_they_add_to() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        templates = app.query_one(TemplateTable)
        assert column(templates, "name") == ["Circle", "Wave", "Mine", "Chase"]
        assert column(templates, "defaults") == ["size 20", "low 0 high 1", "", "phase 0 360"]
        assert column(templates, "source") == ["show", "show", "show", "library"]
        header = app.query_one("#templates-header")
        assert plain(header) == "adds to nothing: select fixtures first"
        bridge.events.append(
            ProgrammerChanged(programmer(version=2, selection=((101, 1), (102, 1))))
        )
        await settle(pilot, app)
        assert plain(header) == "adds to 101 thru 102 (2)"
        await click_cell(pilot, templates, 3, "name")
        assert [s.line for s in bridge.sent] == ['effect add "Chase"']

    drive(app, body)


def test_the_pane_cursor_reaches_the_rows_the_states_the_removes_and_the_templates() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        assert [item.label for item in app.current_page.items()] == [
            "9/4 rainbow settings", "9/4 rainbow release 9",
            "9/4 rainbow cue 9/4 effect rainbow remove",
            "11/1 fx1 settings", "11/1 fx1 goto 11 1", "11/1 fx1 cue 11/1 effect fx1 remove",
            "21/1 fx3 settings", "21/1 fx3 cue 21/1 effect fx3 remove",
            "prog fx5 settings", "prog fx5 effect stop fx5", "prog fx5 effect remove fx5",
            "prog fx6 settings", "prog fx6 effect run fx6", "prog fx6 effect remove fx6",
            "clear",
            'effect add "Circle"', 'effect add "Wave"', 'effect add "Mine"', 'effect add "Chase"',
        ]  # fmt: skip
        await pilot.press("tab", *["down"] * 9, "enter")
        assert app.cursor.active
        assert [s.line for s in bridge.sent] == ["effect stop fx5"]
        table = app.query_one(EffectTable)
        assert table._marked == (3, "state")
        await pilot.press(*["down"] * 6, "enter")
        assert bridge.sent[-1].line == 'effect add "Circle"'
        assert app.query_one(TemplateTable)._marked == (0, None)

    drive(app, body)


def test_nothing_to_show() -> None:
    bridge = FakeBridge()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(ShowChanged(show_model()))
        await settle(pilot, app)
        assert "no effects" in app.query_one(EffectTable).render().plain
        assert app.query_one(TemplateTable).render().plain == "no templates"

    drive(app, body)


def test_the_templates_go_under_the_effects_below_132_columns() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        effects, templates = app.query_one("#effects-panel"), app.query_one("#templates-panel")
        assert templates.region.x > effects.region.x
        await pilot.resize_terminal(120, 40)
        await pilot.pause()
        assert templates.region.y > effects.region.y
        assert templates.region.width == effects.region.width

    drive(app, body)


def test_the_page_is_on_the_effects_page() -> None:
    app = make_app(page=5)

    async def body(pilot: Pilot[int]) -> None:
        assert isinstance(app.current_page, EffectsPage)

    drive(app, body)


# ------------------------------------------------------- the EFFECT panel


FX = (
    MasterView("Grand Master", "grand", None, (), "m-gm"),
    MasterView("Speed 1", "speed", None, (0.5, 1.0), "m-s1"),
    MasterView("FX", "size", None, (), "m-fx"),
)
TWO_SPEEDS = (*FX, MasterView("Speed 2", "speed", None, (), "m-s2"))
ON_101 = Targets(elements=((101, 1), (102, 1)))
RICH = EffectInfo(
    "fx5",
    "Circle",
    ON_101,
    rate="bpm x 2",
    direction="bounce",
    size=20.5,
    low=-1.25,
    high=0.00001,
    phase=(-90.0, 90.5),
    groups=2,
    blocks=3,
    wings=4,
    pace=ChaseRate(None, None, 2.0, "bounce"),
    fadeIn=1.5,
    sizeMaster="FX",
    speedMaster="Speed 1",
)
RICH_LINE = (
    'effect add "Circle" id fx5 bpm x 2 bounce size 20.5 low -1.25 high 0.00001 '
    'phase -90 90.5 groups 2 blocks 3 wings 4 fadein 1.5 sizemaster "FX" speedmaster "Speed 1"'
)
PLAIN_FX = EffectInfo(
    "fx5", "Circle", ON_101, rate="hz 0.25", size=15.0, pace=ChaseRate(0.25, None, 1.0, "forward")
)
PLAIN_LINE = (
    'effect add "Circle" id fx5 hz 0.25 forward size 15 phase 0 0 groups 1 blocks 1 wings 1'
)
ON_CUE = CueListInfo(
    9,
    "Song",
    "sequence",
    None,
    (
        CueInfo(
            "4",
            "Chorus",
            (
                EffectInfo(
                    "rainbow",
                    "Rainbow",
                    Targets(group=GroupInfo(3, "Bar")),
                    rate="hz 0.25",
                    size=1.0,
                    low=0.0,
                    high=1.0,
                    phase=(0.0, 360.0),
                    pace=ChaseRate(0.25, None, 1.0, "forward"),
                ),
            ),
        ),
    ),
)
SELECTED = ((101, 1), (102, 1))


def on_cue(masters: tuple[MasterView, ...] = FX, cue_list: CueListInfo = ON_CUE) -> FakeBridge:
    """F5's bridge: one cue effect."""
    bridge = FakeBridge()
    bridge.events += [
        ShowChanged(fx_show(cueLists=(cue_list,), masters=masters)),
        LiveChanged(live_state()),
        ProgrammerChanged(programmer()),
    ]
    return bridge


def on_prog(
    effect: EffectInfo = PLAIN_FX,
    selection: tuple[tuple[int, int], ...] = SELECTED,
    masters: tuple[MasterView, ...] = FX,
) -> FakeBridge:
    """F5's bridge: one programmer effect."""
    bridge = FakeBridge()
    bridge.events += [
        ShowChanged(fx_show(cueLists=(), masters=masters)),
        LiveChanged(live_state()),
        ProgrammerChanged(programmer(effects=(effect,), selection=selection)),
    ]
    return bridge


def panel_of(app: BuskApp) -> EffectPanel:
    return app.query_one(EffectPanel)


async def open_row(pilot: Pilot[int], app: BuskApp, row: int = 0) -> EffectPanel:
    await settle(pilot, app)
    await click_cell(pilot, app.query_one(EffectTable), row, "template")
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


def button_named(panel: EffectPanel, label: str) -> ActionButton:
    return next(button for button in panel.query(ActionButton) if button.label == label)


async def press_button(pilot: Pilot[int], panel: EffectPanel, label: str) -> None:
    await pilot.click(button_named(panel, label))
    await pilot.pause()


async def type_in(pilot: Pilot[int], app: BuskApp, text: str) -> None:
    """Replace what the dialog's first field holds, and press Enter."""
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


def test_every_setting_is_restated_exactly() -> None:
    assert " ".join(
        word for word in effect_settings(RICH).values() if word is not None
    ) == RICH_LINE.removeprefix('effect add "Circle" id fx5 ')


def test_numbers_are_restated_with_every_digit_and_no_exponent() -> None:
    effect = EffectInfo(
        "fx5",
        "Circle",
        ON_101,
        size=0.1234567891,
        pace=ChaseRate(0.00001, None, 1.0, "forward"),
        phase=(1e22, 0.1),
    )
    settings = effect_settings(effect)
    assert settings["rate"] == "hz 0.00001"
    assert settings["size"] == "size 0.1234567891"
    assert settings["phase"] == "phase 10000000000000000000000 0.1"


def test_a_setting_it_does_not_have_is_not_restated() -> None:
    settings = effect_settings(PLAIN_FX)
    assert settings["low"] is None
    assert "fadein" not in settings
    assert "sizemaster" not in settings
    assert "speedmaster" not in settings


def test_a_named_master_is_quoted() -> None:
    effect = EffectInfo(
        "fx5", "Circle", ON_101, pace=ChaseRate(None, 'The "Big" one', 0.5, "forward")
    )
    assert effect_settings(effect)["rate"] == r'bpm "The \"Big\" one" x 0.5'


CUE_ROW = FxRow("9/4", PLAIN_FX, False, None, None, Line("x"), (9, "4"))
PROG_ROW = FxRow("prog", PLAIN_FX, True, None, None, Line("x"))


def test_why_a_programmer_effect_cannot_change() -> None:
    assert why_fixed(CUE_ROW, ()) is None  # a cue's does not use the selection
    assert why_fixed(PROG_ROW, SELECTED) is None
    assert why_fixed(PROG_ROW, ((102, 1), (101, 1))) is not None  # another order: another spread
    assert why_fixed(PROG_ROW, ((101, 1),)) is not None
    assert why_fixed(PROG_ROW, ()) is not None
    gone = FxRow("prog", replace(PLAIN_FX, targets=Targets()), True, None, None, Line("x"))
    assert why_fixed(gone, ()) is not None  # its fixtures are gone: busk would refuse it
    on_group = FxRow("prog", replace(PLAIN_FX, targets=HEADS), True, None, None, Line("x"))
    assert why_fixed(on_group, SELECTED) == "no line can restate this effect"
    lone = FxRow("prog", replace(PLAIN_FX, low=0.5), True, None, None, Line("x"))
    assert why_fixed(lone, SELECTED) == "no line can restate this effect"


def test_what_the_panel_writes() -> None:
    assert levels_text(None, None).plain == "none"
    assert levels_text(0.0, 1.0).plain == "0 to 1"
    assert levels_text(0.5, None).plain == "0.5 to none"
    assert number_text(None).plain == "none"
    assert number_text(2.5).plain == "2.5"


@pytest.mark.parametrize(
    ("check", "good", "bad"),
    [
        (check_size, ["0", "1.5", "1e2"], ["-1", "x", "", "nan", "inf"]),
        (check_seconds, ["0", "2.5"], ["-0.5", "x", ""]),
        (check_count, ["1", " 12 "], ["0", "-1", "1.5", "x", "", "²"]),
        (check_level, ["-1.25", "0"], ["x", "", "nan"]),
    ],
)
def test_the_checks_of_a_number(check: Any, good: list[str], bad: list[str]) -> None:
    assert [check(text) for text in good] == [None] * len(good)
    assert all(check(text) is not None for text in bad)


def test_the_check_of_two_numbers() -> None:
    assert check_two(("-90", "90.5")) is None
    assert check_two(("x", "1")) is not None
    assert check_two(("1", "")) is not None


def test_a_click_on_a_row_opens_its_panel_in_the_place_of_the_templates() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        panel, table = panel_of(app), app.query_one(EffectTable)
        templates = app.query_one("#templates-panel")
        assert (panel.display, templates.display) == (False, True)
        await click_cell(pilot, table, 1, "targets")
        await settle(pilot, app)
        assert (panel.display, templates.display) == (True, False)
        assert str(panel.border_title) == "EFFECT · 11/1 fx1"
        assert table.chosen == 1
        await click_cell(pilot, table, 0, "rate")
        await settle(pilot, app)
        assert str(panel.border_title) == "EFFECT · 9/4 rainbow"
        assert table.chosen == 0
        await press_button(pilot, panel, "done")
        await settle(pilot, app)
        assert (panel.display, templates.display, table.chosen) == (False, True, None)
        assert bridge.sent == []

    drive(app, body)


def test_a_click_on_the_state_or_the_cross_does_not_open_the_panel() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        table = app.query_one(EffectTable)
        await click_cell(pilot, table, 2, "state")  # no playback: nothing at all
        await click_cell(pilot, table, 3, "state")
        await click_cell(pilot, table, 4, "remove")
        await settle(pilot, app)
        assert not panel_of(app).display

    drive(app, body)


def test_the_panel_goes_when_its_effect_goes() -> None:
    bridge = on_prog()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        assert panel.display
        bridge.events.append(ProgrammerChanged(programmer(version=2)))
        await settle(pilot, app)
        assert not panel.display
        assert app.query_one("#templates-panel").display
        assert app.current_page.chosen is None

    drive(app, body)


def test_the_panel_shows_a_cue_effect() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        assert plain(panel.what) == "Rainbow · Bar"
        assert plain(panel.rate.value) == "hz 0.25"
        assert plain(panel.levels.value) == "0 to 1"
        assert plain(panel.phase.value) == "0→360"
        assert plain(panel.numbers["size"].value) == "1"
        assert plain(panel.numbers["fade-in"].value) == "none"
        assert (panel.low.display, panel.high.display, panel.both.display) == (True, True, False)
        assert not panel.why.display
        assert not panel.its.display
        assert not panel.note.display  # a rate in Hz takes a speed master

    drive(app, body)


@pytest.mark.parametrize(
    ("label", "typed", "line"),
    [
        ("size…", "0.5", "cue 9/4 effect rainbow size 0.5"),
        ("size…", ".5", "cue 9/4 effect rainbow size 0.5"),  # JSON has no ".5"
        ("size…", "1e-05", "cue 9/4 effect rainbow size 0.00001"),
        ("groups…", "3", "cue 9/4 effect rainbow groups 3"),
        ("blocks…", "2", "cue 9/4 effect rainbow blocks 2"),
        ("wings…", "4", "cue 9/4 effect rainbow wings 4"),
        ("fade-in…", "1.5", "cue 9/4 effect rainbow sizeFadeIn 1.5"),
        ("low…", "-0.25", "cue 9/4 effect rainbow low -0.25"),
        ("high…", "0.75", "cue 9/4 effect rainbow high 0.75"),
    ],
)
def test_a_cue_effect_changes_by_one_line(label: str, typed: str, line: str) -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, label)
        await type_in(pilot, app, typed)
        assert bridge.lines() == [line]

    drive(app, body)


def test_a_number_left_as_it_was_sends_nothing() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        for label, text in (("size…", "1"), ("low…", "0.0"), ("high…", "1"), ("groups…", "1")):
            await press_button(pilot, panel, label)
            await type_in(pilot, app, text)
        assert bridge.lines() == []

    drive(app, body)


def test_escape_changes_nothing() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "size…")
        await pilot.press("escape")
        await settle(pilot, app)
        assert bridge.lines() == []

    drive(app, body)


def test_a_dialog_refuses_what_is_not_a_number_and_stays() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "groups…")
        await type_in(pilot, app, "0")
        assert isinstance(app.screen, TextDialog)
        assert "whole number" in plain(app.screen.error)
        assert bridge.lines() == []

    drive(app, body)


def test_a_dialog_says_what_its_number_means() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "fade-in…")
        assert isinstance(app.screen, TextDialog)
        assert app.screen.note == "seconds its size takes to come in"

    drive(app, body)


def test_a_dialog_starts_at_the_number_with_every_digit() -> None:
    effect = replace(ON_CUE.cues[0].effects[0], size=0.1234567891)
    cue_list = replace(ON_CUE, cues=(replace(ON_CUE.cues[0], effects=(effect,)),))
    bridge = on_cue(cue_list=cue_list)
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "size…")
        assert app.screen.query_one(Input).value == "0.1234567891"

    drive(app, body)


def test_a_cue_effect_changes_direction_by_a_chip() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await click_chip(pilot, panel.direction, "forward")  # lit: nothing
        assert bridge.lines() == []
        await click_chip(pilot, panel.direction, "bounce")
        assert bridge.lines() == ["cue 9/4 effect rainbow direction bounce"]

    drive(app, body)


def test_a_cue_effect_takes_a_phase_in_one_line() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "phase…")
        await fill_form(pilot, app, "-10", "20.5")
        assert bridge.lines() == ['cue 9/4 effect rainbow phase {"start": -10, "end": 20.5}']

    drive(app, body)


def test_a_phase_left_as_it_was_sends_nothing() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "phase…")
        await fill_form(pilot, app, "0", "360")
        assert bridge.lines() == []

    drive(app, body)


def test_a_cue_effect_takes_a_master_by_its_id() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await click_chip(pilot, panel.size_masters, "FX")
        await click_chip(pilot, panel.speed_masters, "Speed 1")
        assert bridge.lines() == [
            'cue 9/4 effect rainbow sizeMasterId "m-fx"',
            'cue 9/4 effect rainbow speedMasterId "m-s1"',
        ]

    drive(app, body)


def test_no_line_takes_a_master_from_a_cue_effect() -> None:
    effect = replace(ON_CUE.cues[0].effects[0], sizeMaster="FX")
    cue_list = replace(ON_CUE, cues=(replace(ON_CUE.cues[0], effects=(effect,)),))
    bridge = on_cue(cue_list=cue_list)
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        none, fx = panel.size_masters.buttons
        assert none.note
        assert str(none.label.spans[0].style) == colors.BORDER
        assert fx.note
        assert str(fx.label.spans[0].style) == LIT
        await click_chip(pilot, panel.size_masters, "none")
        assert bridge.lines() == []

    drive(app, body)


def test_a_cue_effect_takes_a_rate_in_hz() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "rate…")
        assert isinstance(app.screen, EffectRateDialog)
        assert app.screen.hz.value == "0.25"
        app.screen.hz.value = ".5"
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.lines() == ['cue 9/4 effect rainbow rate {"kind": "hz", "value": 0.5}']

    drive(app, body)


def test_a_multiplier_left_blank_does_not_stop_a_rate_in_hz() -> None:
    """Hidden by the chip, the field is not checked: it must not be read."""
    bridge = on_prog(RICH)
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "rate…")
        assert isinstance(app.screen, EffectRateDialog)
        app.screen.multiplier.value = ""
        app.screen.kind.pick("hz")
        app.screen.hz.value = "3"
        app.screen.action_ok()
        await settle(pilot, app)
        assert bridge.lines() == [RICH_LINE.replace("bpm x 2", "hz 3")]

    drive(app, body)


def test_a_cue_effect_goes_on_the_beat_of_the_only_master() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "rate…")
        assert isinstance(app.screen, EffectRateDialog)
        app.screen.kind.pick("bpm")
        app.screen.multiplier.value = "0.5"
        app.screen.action_ok()
        await settle(pilot, app)
        assert bridge.lines() == [
            'cue 9/4 effect rainbow rate {"kind": "bpm", "masterId": "m-s1", "multiplier": 0.5}'
        ]

    drive(app, body)


def test_a_cue_effect_goes_on_the_beat_of_the_master_chosen() -> None:
    bridge = on_cue(TWO_SPEEDS)
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "rate…")
        dialog = app.screen
        assert isinstance(dialog, EffectRateDialog)
        assert dialog.master is not None
        dialog.kind.pick("bpm")
        dialog.master.pick("Speed 2")
        dialog.action_ok()
        await settle(pilot, app)
        assert bridge.lines() == [
            'cue 9/4 effect rainbow rate {"kind": "bpm", "masterId": "m-s2", "multiplier": 1}'
        ]

    drive(app, body)


def test_the_same_rate_sends_nothing() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "rate…")
        assert isinstance(app.screen, EffectRateDialog)
        app.screen.action_ok()
        await settle(pilot, app)
        assert bridge.lines() == []

    drive(app, body)


def test_the_same_beat_sends_nothing_and_another_master_is_another_beat() -> None:
    effect = replace(
        PLAIN_FX, rate='bpm "Speed 2" x 2', pace=ChaseRate(None, "Speed 2", 2.0, "forward")
    )
    bridge = on_prog(effect, masters=TWO_SPEEDS)
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "rate…")
        assert isinstance(app.screen, EffectRateDialog)
        app.screen.action_ok()
        await settle(pilot, app)
        assert bridge.lines() == []
        await press_button(pilot, panel, "rate…")
        dialog = app.screen
        assert isinstance(dialog, EffectRateDialog)
        assert dialog.master is not None
        assert dialog.master.chosen == "Speed 2"
        dialog.master.pick("Speed 1")
        dialog.action_ok()
        await settle(pilot, app)
        assert bridge.lines()[0].startswith('effect add "Circle" id fx5 bpm "Speed 1" x 2 ')

    drive(app, body)


def test_a_beat_rate_says_it_follows_its_own_master() -> None:
    effect = replace(PLAIN_FX, rate="bpm x 1", pace=ChaseRate(None, None, 1.0, "forward"))
    bridge = on_prog(effect)
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        assert panel.note.display

    drive(app, body)


def test_a_show_with_no_masters_of_a_kind_has_no_row_for_them() -> None:
    bridge = on_prog(masters=(MasterView("Grand Master", "grand", None, (), "m-gm"),))
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        assert not panel.size_row.display
        assert not panel.speed_row.display
        assert not panel.note.display

    drive(app, body)


@pytest.mark.parametrize(
    ("label", "typed", "before", "after"),
    [
        ("size…", "30", "size 15", "size 30"),
        ("groups…", "2", "groups 1", "groups 2"),
        ("blocks…", "3", "blocks 1", "blocks 3"),
        ("wings…", "4", "wings 1", "wings 4"),
    ],
)
def test_a_programmer_effect_is_restated(label: str, typed: str, before: str, after: str) -> None:
    bridge = on_prog()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, label)
        await type_in(pilot, app, typed)
        assert bridge.lines() == [PLAIN_LINE.replace(before, after)]

    drive(app, body)


def test_a_change_keeps_every_other_setting() -> None:
    bridge = on_prog(RICH)
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "size…")
        await type_in(pilot, app, "1")
        assert bridge.lines() == [RICH_LINE.replace("size 20.5", "size 1")]

    drive(app, body)


def test_a_programmer_effect_takes_a_fade_in_after_the_others() -> None:
    bridge = on_prog()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "fade-in…")
        await type_in(pilot, app, "2")
        assert bridge.lines() == [f"{PLAIN_LINE} fadein 2"]

    drive(app, body)


def test_a_programmer_effect_loses_its_fade_in() -> None:
    """A fade-in of 0 is not none: without one, it comes in over the
    programmer's fade time."""
    bridge = on_prog(RICH)
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        assert not panel.no_fade.inert
        assert "fade-in none" in [stop.item.label for stop in panel.stops()]
        await pilot.click(panel.no_fade)
        await settle(pilot, app)
        assert bridge.lines() == [RICH_LINE.replace(" fadein 1.5", "")]

    drive(app, body)


def test_with_no_fade_in_there_is_nothing_to_take_away() -> None:
    bridge = on_prog()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        assert not panel.no_fade.display
        assert "fade-in none" not in [stop.item.label for stop in panel.stops()]

    drive(app, body)


def test_no_line_takes_a_fade_in_from_a_cue_effect() -> None:
    effect = replace(ON_CUE.cues[0].effects[0], fadeIn=1.5)
    cue_list = replace(ON_CUE, cues=(replace(ON_CUE.cues[0], effects=(effect,)),))
    bridge = on_cue(cue_list=cue_list)
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        assert panel.no_fade.display
        assert panel.no_fade.inert
        assert "fade-in none" not in [stop.item.label for stop in panel.stops()]
        await pilot.click(panel.no_fade)
        await settle(pilot, app)
        assert bridge.lines() == []

    drive(app, body)


def test_with_another_selection_a_fade_in_stays_too() -> None:
    bridge = on_prog(RICH, selection=((301, 1),))
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        assert panel.no_fade.display
        assert panel.no_fade.inert

    drive(app, body)


def test_a_programmer_effect_changes_direction_by_a_chip() -> None:
    bridge = on_prog()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await click_chip(pilot, panel.direction, "reverse")
        assert bridge.lines() == [PLAIN_LINE.replace(" forward ", " reverse ")]

    drive(app, body)


def test_a_programmer_effect_takes_its_two_levels_together() -> None:
    bridge = on_prog()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        assert (panel.low.display, panel.high.display, panel.both.display) == (False, False, True)
        await press_button(pilot, panel, "levels…")
        assert [field.value for field in app.screen.query(Input)] == ["0", "1"]
        await fill_form(pilot, app, "0.25", "0.75")
        assert bridge.lines() == [PLAIN_LINE.replace(" size 15 ", " size 15 low 0.25 high 0.75 ")]

    drive(app, body)


def test_a_programmer_effect_keeps_two_levels_left_as_they_were() -> None:
    bridge = on_prog(RICH)
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "levels…")
        assert [field.value for field in app.screen.query(Input)] == ["-1.25", "0.00001"]
        await fill_form(pilot, app, "-1.25", "0.00001")
        assert bridge.lines() == []

    drive(app, body)


def test_a_programmer_effect_takes_a_phase() -> None:
    bridge = on_prog()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "phase…")
        await fill_form(pilot, app, "0", "180")
        assert bridge.lines() == [PLAIN_LINE.replace("phase 0 0", "phase 0 180")]

    drive(app, body)


def test_a_programmer_effect_takes_a_rate_by_either_kind() -> None:
    bridge = on_prog()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "rate…")
        assert isinstance(app.screen, EffectRateDialog)
        app.screen.hz.value = "2"
        app.screen.action_ok()
        await settle(pilot, app)
        await press_button(pilot, panel, "rate…")
        assert isinstance(app.screen, EffectRateDialog)
        app.screen.kind.pick("bpm")
        app.screen.multiplier.value = "0.5"
        app.screen.action_ok()
        await settle(pilot, app)
        assert bridge.lines() == [
            PLAIN_LINE.replace("hz 0.25", "hz 2"),
            PLAIN_LINE.replace("hz 0.25", "bpm x 0.5"),
        ]

    drive(app, body)


def test_a_rate_form_starts_at_a_beat_rate() -> None:
    bridge = on_prog(RICH)
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "rate…")
        assert isinstance(app.screen, EffectRateDialog)
        assert app.screen.kind.chosen == "bpm"
        assert app.screen.multiplier.value == "2"

    drive(app, body)


def test_a_programmer_effect_takes_masters_by_name_and_loses_them() -> None:
    bridge = on_prog(RICH)
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await click_chip(pilot, panel.size_masters, "none")
        await click_chip(pilot, panel.speed_masters, "none")
        assert bridge.lines() == [
            RICH_LINE.replace(' sizemaster "FX"', ""),
            RICH_LINE.replace(' speedmaster "Speed 1"', ""),
        ]

    drive(app, body)


def test_a_programmer_effect_gets_a_master() -> None:
    bridge = on_prog()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await click_chip(pilot, panel.size_masters, "FX")
        await click_chip(pilot, panel.speed_masters, "Speed 1")
        assert bridge.lines() == [
            f'{PLAIN_LINE} sizemaster "FX"',
            f'{PLAIN_LINE} speedmaster "Speed 1"',
        ]

    drive(app, body)


def test_the_panel_follows_the_programmer() -> None:
    bridge = on_prog()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        assert plain(panel.numbers["size"].value) == "15"
        changed = replace(PLAIN_FX, size=30.0)
        bridge.events.append(
            ProgrammerChanged(programmer(version=2, effects=(changed,), selection=SELECTED))
        )
        await settle(pilot, app)
        assert plain(panel.numbers["size"].value) == "30"
        await press_button(pilot, panel, "groups…")
        await type_in(pilot, app, "2")
        assert bridge.lines() == [
            PLAIN_LINE.replace("size 15", "size 30").replace("groups 1", "groups 2")
        ]

    drive(app, body)


def test_with_another_selection_a_programmer_effect_stays_put() -> None:
    bridge = on_prog(selection=((301, 1),))
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        assert panel.why.display
        assert "select its fixtures" in plain(panel.why)
        assert panel.its.display
        assert button_named(panel, "size…").inert
        assert button_named(panel, "rate…").inert
        assert button_named(panel, "levels…").inert
        await press_button(pilot, panel, "size…")
        assert not isinstance(app.screen, TextDialog)
        assert all(button.note for button in panel.direction.buttons)
        assert all(button.note for button in panel.size_masters.buttons)
        await click_chip(pilot, panel.direction, "reverse")
        assert bridge.lines() == []
        assert [stop.item.label for stop in panel.stops()] == ["its fixtures", "done"]
        await press_button(pilot, panel, "its fixtures")
        assert bridge.lines() == ["sel fixture 101 thru 102"]

    drive(app, body)


def test_once_its_fixtures_are_selected_it_can_change() -> None:
    bridge = on_prog(selection=((301, 1),))
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        bridge.events.append(
            ProgrammerChanged(programmer(version=2, effects=(PLAIN_FX,), selection=SELECTED))
        )
        await settle(pilot, app)
        assert not panel.why.display
        assert not panel.its.display
        assert not button_named(panel, "size…").inert
        await press_button(pilot, panel, "size…")
        await type_in(pilot, app, "30")
        assert bridge.lines() == [PLAIN_LINE.replace("size 15", "size 30")]

    drive(app, body)


def test_a_selection_that_moves_under_a_dialog_sends_nothing() -> None:
    bridge = on_prog()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        await press_button(pilot, panel, "size…")
        assert isinstance(app.screen, TextDialog)
        bridge.events.append(
            ProgrammerChanged(programmer(version=2, effects=(PLAIN_FX,), selection=((301, 1),)))
        )
        await settle(pilot, app)
        await type_in(pilot, app, "30")
        assert bridge.lines() == []

    drive(app, body)


def test_a_group_effect_cannot_be_restated_and_has_no_fixtures_to_select() -> None:
    bridge = on_prog(replace(PLAIN_FX, targets=HEADS))
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        assert plain(panel.why) == "no line can restate this effect"
        assert not panel.its.display
        assert [stop.item.label for stop in panel.stops()] == ["done"]

    drive(app, body)


def test_the_cross_on_a_cue_effect_asks_and_runs() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        table = app.query_one(EffectTable)
        await click_cell(pilot, table, 1, "remove")
        await settle(pilot, app)
        assert isinstance(app.screen, ConfirmDialog)
        assert app.screen.question == "Remove effect fx1 from cue 11/1?"
        await pilot.press("n")
        await settle(pilot, app)
        assert bridge.lines() == []
        await click_cell(pilot, table, 1, "remove")
        await settle(pilot, app)
        await pilot.press("y")
        await settle(pilot, app)
        assert [(s.line, s.origin) for s in bridge.sent] == [("cue 11/1 effect fx1 remove", "ui")]

    drive(app, body)


def test_the_question_says_when_the_effect_is_running() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await click_cell(pilot, app.query_one(EffectTable), 0, "remove")
        await settle(pilot, app)
        assert isinstance(app.screen, ConfirmDialog)
        assert app.screen.question == (
            "Remove effect rainbow from cue 9/4? It is running, and will stop at once."
        )

    drive(app, body)


def test_the_cross_on_a_programmer_effect_asks_nothing() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await click_cell(pilot, app.query_one(EffectTable), 3, "remove")
        await settle(pilot, app)
        assert not isinstance(app.screen, ConfirmDialog)
        assert bridge.lines() == ["effect remove fx5"]

    drive(app, body)


def test_the_panel_title_counts_the_effects_by_where_they_are() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        title = str(app.query_one("#effects-panel").border_title)
        assert title == "EFFECTS · 3 in cues · 2 in the programmer"  # ✕ on every row

    drive(app, body)


def test_clear_is_grey_with_no_programmer_effects() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        clear = app.query_one("#effects-clear", ActionButton)
        assert clear.inert
        assert "clear" not in [item.label for item in app.current_page.items()]
        await pilot.click(clear)
        await settle(pilot, app)
        assert not isinstance(app.screen, ConfirmDialog)
        assert bridge.lines() == []

    drive(app, body)


@pytest.mark.parametrize(
    ("effects", "question"),
    [
        ((PLAIN_FX,), "Remove 1 programmer effect?"),
        ((PLAIN_FX, replace(PLAIN_FX, id="fx6")), "Remove 2 programmer effects?"),
    ],
)
def test_clear_asks_first(effects: tuple[EffectInfo, ...], question: str) -> None:
    bridge = on_prog()
    bridge.events.append(ProgrammerChanged(programmer(effects=effects)))
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        clear = app.query_one("#effects-clear", ActionButton)
        assert not clear.inert
        await pilot.click(clear)
        await settle(pilot, app)
        assert isinstance(app.screen, ConfirmDialog)
        assert app.screen.question == question
        await pilot.press("n")
        await settle(pilot, app)
        assert bridge.lines() == []
        await pilot.click(clear)
        await settle(pilot, app)
        await pilot.press("y")
        await settle(pilot, app)
        assert bridge.lines() == ["effect clear"]

    drive(app, body)


def test_the_pane_cursor_reaches_the_panels_controls() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        labels = [stop.item.label for stop in panel.stops()]
        assert labels == [
            "rate rate…",
            "cue 9/4 effect rainbow direction reverse",
            "cue 9/4 effect rainbow direction bounce",
            "size size…",
            "levels low…",
            "levels high…",
            "phase phase…",
            "groups groups…",
            "blocks blocks…",
            "wings wings…",
            "fade-in fade-in…",
            'cue 9/4 effect rainbow sizeMasterId "m-fx"',
            'cue 9/4 effect rainbow speedMasterId "m-s1"',
            "done",
        ]
        assert len(set(labels)) == len(labels)  # the cursor finds its place again by the label
        page_labels = [item.label for item in app.current_page.items()]
        assert page_labels[-len(labels) :] == labels
        assert not any(label.startswith("effect add") for label in page_labels)

    drive(app, body)


def test_the_pane_cursor_opens_a_panel_and_works_it() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.press("tab", "enter")
        await settle(pilot, app)
        panel = panel_of(app)
        assert panel.display
        assert app.query_one(EffectTable)._marked == (0, "id")
        labels = [item.label for item in app.current_page.items()]
        await pilot.press(*["down"] * labels.index("size size…"), "enter")
        await settle(pilot, app)
        assert isinstance(app.screen, TextDialog)
        await type_in(pilot, app, "0.5")
        assert bridge.lines() == ["cue 9/4 effect rainbow size 0.5"]

    drive(app, body)


def test_the_pane_cursor_asks_before_a_cue_effect_goes() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        labels = [item.label for item in app.current_page.items()]
        down = labels.index("9/4 rainbow cue 9/4 effect rainbow remove")
        await pilot.press("tab", *["down"] * down, "enter")
        await settle(pilot, app)
        assert isinstance(app.screen, ConfirmDialog)
        assert bridge.lines() == []

    drive(app, body)


def test_at_99_columns_the_panel_goes_under_the_effects_in_full() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        await pilot.resize_terminal(99, 40)
        await pilot.pause()
        panel = await open_row(pilot, app)
        effects = app.query_one("#effects-panel")
        assert panel.region.y > effects.region.y
        assert panel.region.x == effects.region.x
        assert panel.region.width == effects.region.width

    drive(app, body)


def test_under_the_effects_the_panel_scrolls_into_sight() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await pilot.resize_terminal(99, 24)
        await pilot.pause()
        page = app.current_page
        await settle(pilot, app)
        assert page.scroll_y == 0
        await click_cell(pilot, app.query_one(EffectTable), 0, "template")
        await settle(pilot, app)
        await pilot.pause()
        assert page.scroll_y > 0
        assert panel_of(app).region.y <= page.region.y + page.size.height

    drive(app, body)


def test_beside_the_effects_every_control_fits_in_the_panel() -> None:
    bridge = on_cue()
    app = make_app(bridge, page=5)

    async def body(pilot: Pilot[int]) -> None:
        panel = await open_row(pilot, app)
        inner = panel.content_region.right
        for button in panel.query(ActionButton):
            if button.display:
                assert button.region.right <= inner, button.label

    drive(app, body)
