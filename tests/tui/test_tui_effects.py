"""F5 Effects (spec §8.5, plan Phase 3): the cue and programmer effects
formatted alike, their state from what runs (and the stopped ones), the
sparkline and the live rate, the state and ``✕`` lines, the templates, and
the pane cursor. Headless, with a fake bridge."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.pilot import Pilot
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
from busk_tui.model import (
    CueInfo,
    CueListInfo,
    EffectInfo,
    EffectsChanged,
    EffectsModel,
    EffectView,
    FixtureInfo,
    GroupInfo,
    LiveChanged,
    PlaybackInfo,
    ProgrammerChanged,
    ShowChanged,
    ShowModel,
    Targets,
    TemplateInfo,
)
from busk_tui.pages.effects import EffectsPage
from busk_tui.shell import BuskApp
from busk_tui.widgets.effects import EffectTable, TemplateTable, effect_rows, fx_cells

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
            "",
        ),
        ("11/1", "fx1", "Circle", "Heads", "bpm x 0.5", "15", "0→180", "1", "[off]", ""),
        ("21/1", "fx3", "Wave", "Heads", "bpm x 1", "0–1", "0→0", "1", "—", ""),
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
    assert [None if row.remove is None else row.remove.text for row in rows][3:] == [
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
        await click_cell(pilot, table, 1, "template")  # not a control
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


def test_the_pane_cursor_reaches_the_states_the_removes_and_the_templates() -> None:
    bridge = FakeBridge()
    app = on_f5(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        lines = [item.line for item in app.current_page.items()]
        assert lines == [
            "release 9", "goto 11 1", "effect stop fx5", "effect remove fx5",
            "effect run fx6", "effect remove fx6",
            'effect add "Circle"', 'effect add "Wave"', 'effect add "Mine"', 'effect add "Chase"',
        ]  # fmt: skip
        await pilot.press("tab", "down", "down", "enter")
        assert app.cursor.active
        assert [s.line for s in bridge.sent] == ["effect stop fx5"]
        table = app.query_one(EffectTable)
        assert table._marked == (3, "state")
        await pilot.press("down", "down", "down", "down", "enter")
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
