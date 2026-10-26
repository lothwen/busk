"""F3 Fixtures (spec §8.3, plan Phase 4): a row per fixture, single and
multi-element, patched, split and unpatched; the live cells and their source
colours from an ``OutputModel``; the selection marker; clicks, Shift-clicks,
the edits and the pane cursor. Headless, with a fake bridge."""

from __future__ import annotations

from typing import Any

from textual.pilot import Pilot
from tui_fakes import (
    FakeBridge,
    click_cell,
    column,
    drive,
    make_app,
    programmer,
    settle,
    show_model,
)

from busk_tui import colors
from busk_tui.model import (
    ElementOutput,
    FixtureInfo,
    OutputChanged,
    OutputModel,
    ProfileInfo,
    ProgrammerChanged,
    ShowChanged,
    ShowModel,
)
from busk_tui.pages.fixtures import FixturesPage
from busk_tui.shell import BuskApp
from busk_tui.widgets.fixturetable import FixtureTable, fixture_cells, source_text, swatches
from busk_tui.widgets.legend import Legend

SPOT = FixtureInfo(
    101, 1, "Spot 101", "Spot", "16ch", 16, (1, 1), location=(1.5, 2.0, 4.0, 0, 0, 0)
)
BAR = FixtureInfo(301, 12, "Bar 301", "Pixel Bar", "36ch", 36, (1, 49))
SPLIT = FixtureInfo(302, 4, "Bar 302", "Pixel Bar", "12ch", 12, (2, 1), split=True)
LOOSE = FixtureInfo(401, 1, "", "Par", "4ch", 4, None)
PROFILES = (
    ProfileInfo("Spot", frozenset(), (), "spot"),
    ProfileInfo("Pixel Bar", frozenset(), (), "pixel"),
    ProfileInfo('Par "LED"', frozenset(), ()),
    ProfileInfo("Par", frozenset(), ()),
)


def out(number: int, element: int = 1, **parts: Any) -> ElementOutput:
    given: dict[str, Any] = {
        "intensity": 1.0,
        "color": (1.0, 0.0, 0.0),
        "pan": None,
        "tilt": None,
        "zoom": None,
        "sources": (("intensity", "playback"), ("color", "playback")),
        "playback": 9,
    }
    given.update(parts)
    return ElementOutput(number, element, **given)


HEAD = out(
    101,
    intensity=0.8,
    pan=-45.4,
    tilt=10.0,
    zoom=21.0,
    sources=(("intensity", "programmer"), ("position", "effect"), ("beam", "none")),
    playback=None,
)
BAR_OUT = tuple(
    out(301, element, intensity=element / 12, sources=(("intensity", "effect"),), playback=11)
    for element in range(1, 13)
)
OUTPUT = OutputModel(1, (HEAD, *BAR_OUT))


def rig(**changes: Any) -> ShowModel:
    parts: dict[str, Any] = {"fixtures": (SPOT, BAR, SPLIT, LOOSE), "profiles": PROFILES}
    parts.update(changes)
    return show_model(**parts)


def on_f3(bridge: FakeBridge, output: OutputModel | None = OUTPUT) -> BuskApp:
    bridge.events += [
        ShowChanged(rig()),
        ProgrammerChanged(programmer(selection=((301, 1), (301, 2)))),
    ]
    if output is not None:
        bridge.events.append(OutputChanged(output))
    return make_app(bridge, page=3)


def styles(cells: dict[str, Any], name: str) -> str:
    return str(cells[name].spans[0].style)


def test_static_cells_for_single_multi_split_and_unpatched_fixtures() -> None:
    cells = [fixture_cells(f, (), False, None, "256") for f in (SPOT, BAR, SPLIT, LOOSE)]
    table = [
        tuple(c[name].plain for name in ("number", "name", "profile", "mode", "patch"))
        for c in cells
    ]
    assert table == [
        ("101", "Spot 101", "Spot", "16ch", "1.1"),
        ("301", "Bar 301", "Pixel Bar ×12", "36ch", "1.49"),
        ("302", "Bar 302", "Pixel Bar ×4", "12ch", "2.1 split"),
        ("401", "—", "Par", "4ch", "—"),
    ]
    assert styles(cells[3], "patch") == colors.RED  # unpatched
    assert [c["intensity"].plain for c in cells] == ["·"] * 4  # no output read yet


def test_live_cells_coloured_by_what_drives_them() -> None:
    head = fixture_cells(SPOT, (HEAD,), True, "spot", "256")
    assert head["marker"].plain == "▸"
    assert (head["intensity"].plain, head["pan"].plain, head["tilt"].plain) == (
        "80%",
        "-45°",
        "10°",
    )
    assert head["zoom"].plain == "21°"
    assert head["source"].plain == "prog"
    assert styles(head, "intensity") == colors.MAGENTA  # the programmer's
    assert styles(head, "pan") == colors.GREEN  # an effect moves it
    assert styles(head, "zoom") == colors.DIM  # nothing drives the beam
    assert head["category"].plain == "spot"
    bar = fixture_cells(BAR, BAR_OUT, False, "pixel", "256")
    assert bar["intensity"].plain == "8–100%"  # its elements differ
    assert bar["source"].plain == "fx P11"
    assert styles(bar, "intensity") == colors.GREEN
    assert "pan" not in bar  # no pan: blank


def test_the_source_and_its_words() -> None:
    assert [source_text(s, p) for s, p in (("programmer", None), ("effect", None), ("effect", 11),
            ("playback", 9), ("playback", None), ("none", None))] == [
        "prog", "fx", "fx P11", "P9", "pb", "—"]  # fmt: skip


def test_one_swatch_per_element_twelve_at_most() -> None:
    assert swatches((HEAD,), "256").plain == "██"
    many = tuple(out(301, element) for element in range(1, 25))
    assert swatches(many, "256").plain == "█" * 12
    dark = swatches((out(101, intensity=0.0),), "256")
    assert str(dark.spans[0].style) == f"color({colors.UNLIT})"
    white = swatches((out(101, color=None),), "truecolor")  # no colour: white light
    assert str(white.spans[0].style) == "#ffffff"


def test_the_page_lists_every_fixture_and_lights_the_selection() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        assert bridge.watching == (True, False)
        table = app.query_one(FixtureTable)
        assert column(table, "number") == ["101", "301", "302", "401"]
        assert column(table, "marker") == ["", "▸", "", ""]
        assert table.lit == frozenset({1})
        assert column(table, "intensity") == ["80%", "8–100%", "·", "·"]
        panel = app.query_one("#fixtures-panel")
        assert "4 fixtures · 1 selected" in str(panel.border_title)
        assert "unpatched" in app.query_one("#fixtures-legend", Legend).render().plain
        bridge.events.append(OutputChanged(OutputModel(2, (out(101, intensity=0.5), *BAR_OUT))))
        await settle(pilot, app)
        assert column(table, "intensity")[0] == "50%"
        assert column(table, "source")[0] == "P9"

    drive(app, body)


def test_clicks_select_and_shift_clicks_add_or_take_out() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        table = app.query_one(FixtureTable)
        await click_cell(pilot, table, 0, "name")
        await pilot.click(table, offset=(10, 1), shift=True)  # 101, not selected: added
        await pilot.click(table, offset=(10, 2), shift=True)  # 301, selected: taken out
        assert [(s.line, s.origin, s.performance) for s in bridge.sent] == [
            ("sel fixture 101", "ui", False),
            ("sel + fixture 101", "ui", False),
            ("sel - fixture 301", "ui", False),
        ]

    drive(app, body)


def test_the_edits_act_on_the_fixture_clicked_last() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(FixturesPage)
        assert page.edited() == BAR  # the first selected
        assert "fixture 301 Bar 301" in page.edit_label.content.plain
        prefills = [button.prefill for button in page.edits.buttons]
        assert prefills == [
            "fixture 301 patch ",
            'fixture 301 location {"x": 0, "y": 0, "z": 0, "rx": 0, "ry": 0, "rz": 0}',
            'profile "Pixel Bar" category ',
            'rename fixture 301 "',
        ]
        await click_cell(pilot, app.query_one(FixtureTable), 0, "name")
        await settle(pilot, app)
        assert [button.prefill for button in page.edits.buttons][1] == (
            'fixture 101 location {"x": 1.5, "y": 2, "z": 4, "rx": 0, "ry": 0, "rz": 0}'
        )
        await pilot.click(page.edits, offset=(1, 0))
        assert app.prompt.value == "fixture 101 patch "

    drive(app, body)


def test_a_profile_name_busk_cannot_read_has_no_category_edit() -> None:
    bridge = FakeBridge()
    quoted = FixtureInfo(501, 1, "Par 501", 'Par "LED"', "4ch", 4, (1, 1))
    bridge.events.append(ShowChanged(rig(fixtures=(quoted,))))
    app = make_app(bridge, page=3)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(FixturesPage)
        assert all("category" not in (b.prefill or "") for b in page.edits.buttons)

    drive(app, body)


def test_the_pane_cursor_stops_on_the_rows_then_the_edits() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        items = app.current_page.items()
        assert [item.line for item in items[:4]] == [
            "sel fixture 101", "sel fixture 301", "sel fixture 302", "sel fixture 401"
        ]  # fmt: skip
        assert items[4].prefill == "fixture 301 patch "
        await pilot.press("tab", "down", "down", "enter")  # 302: selected, and edited
        assert bridge.lines() == ["sel fixture 302"]
        assert app.query_one(FixturesPage).edited() == SPLIT

    drive(app, body)


def test_nothing_to_show() -> None:
    bridge = FakeBridge()
    bridge.events.append(ShowChanged(show_model()))
    app = make_app(bridge, page=3)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        assert "no fixtures" in app.query_one(FixtureTable).render().plain
        assert app.query_one(FixturesPage).edits.buttons == ()

    drive(app, body)
