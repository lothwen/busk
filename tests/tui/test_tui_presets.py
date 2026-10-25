"""F6 Presets (spec §8.6, plan Phase 2): what presets apply to, a panel per
pool that has presets, the tiles' previews, their lines, the record tile,
and new presets showing at once. Headless, with a fake bridge."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.pilot import Pilot
from tui_fakes import FakeBridge, drive, make_app, programmer, settle, show_model

from busk_tui.model import FixtureInfo, PresetInfo, ProgrammerChanged, ShowChanged, ShowModel
from busk_tui.pages.presets import PresetsPage
from busk_tui.shell import BuskApp
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.tiles import PresetTile, preview

PRESETS = (
    PresetInfo("position", 2, "Centre", None, (("pan", 15.0), ("tilt", 10.0))),
    PresetInfo("color", 2, "Red", (1.0, 0.0, 0.0)),
    PresetInfo("color", 1, "Blue", (0.0, 0.0, 1.0)),
    PresetInfo("position", 1, "Audience", None, (("pan", None), ("tilt", 40.0))),
    PresetInfo("intensity", 1, "Half", None, (("intensity", 0.5),)),
)


def presets_show(*presets: PresetInfo) -> ShowModel:
    return show_model(
        presets=presets or PRESETS,
        fixtures=(FixtureInfo(101, 1, "Spot 101", "Spot"), FixtureInfo(102, 1, "Spot 102", "Spot")),
    )


def presets_app(bridge: FakeBridge) -> BuskApp:
    return make_app(bridge, page=6)


def started(bridge: FakeBridge, show: ShowModel | None = None, **changes: Any) -> None:
    bridge.events += [ShowChanged(show or presets_show()), ProgrammerChanged(programmer(**changes))]


def tiles(app: BuskApp) -> list[PresetTile]:
    return list(app.query(PresetTile))


def plain(widget: Any) -> str:
    rendered = widget.content if hasattr(widget, "content") else widget.render()
    return rendered.plain if isinstance(rendered, Text) else str(rendered)


def test_previews() -> None:
    red = preview(PRESETS[1], "256")
    assert red.plain == "████"
    assert str(red.style) == "color(196)"
    assert preview(PresetInfo("color", 3, "Two", None), "256").plain == "mixed"
    wheel = PresetInfo("color", 4, "Wheel", None, (("colorWheel", "red"),))
    assert preview(wheel, "256").plain == "colorWheel red"
    assert preview(PRESETS[0], "256").plain == "15°/10°"
    assert preview(PRESETS[3], "256").plain == "mixed/40°"
    assert preview(PresetInfo("position", 3, "Pan", None, (("pan", -30.0),)), "256").plain == (
        "-30°/·"
    )
    assert preview(PRESETS[4], "256").plain == "▅ 50%"
    assert preview(
        PresetInfo("intensity", 2, "Full", None, (("intensity", 1.0),)), "256"
    ).plain == ("█ 100%")
    assert preview(PresetInfo("intensity", 3, "?", None, (("intensity", None),)), "256").plain == (
        "mixed"
    )
    beam = PresetInfo("beam", 1, "Narrow", None, (("zoom", 20.0), ("iris", 0.5)))
    assert preview(beam, "256").plain == "zoom 20°"
    assert preview(PresetInfo("focus", 1, "Sharp", None, (("focus", 0.3),)), "256").plain == (
        "focus 30%"
    )
    everything = PresetInfo("all", 1, "Look", (1.0, 0.0, 0.0), (("intensity", 1.0),))
    assert preview(everything, "256").plain == "████"


def test_a_panel_per_pool_with_presets_in_busks_order() -> None:
    bridge = FakeBridge()
    app = presets_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        titles = [str(panel.border_title) for panel in app.query_one(PresetsPage).query(Panel)]
        assert titles == ["COLOR", "POSITION", "INTENSITY"]
        assert [(t.pool, t.number, t.preset is None) for t in tiles(app)] == [
            ("color", 1, False),
            ("color", 2, False),
            ("color", 3, True),
            ("position", 1, False),
            ("position", 2, False),
            ("position", 3, True),
            ("intensity", 1, False),
            ("intensity", 2, True),
        ]
        first = plain(tiles(app)[0]).splitlines()
        assert first[0].startswith("1 ")
        assert first[0].endswith("████")
        assert first[1] == "Blue"

    drive(app, body)


def test_a_tile_runs_its_preset_and_the_last_prefills_a_record() -> None:
    bridge = FakeBridge()
    app = presets_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        found = tiles(app)
        await pilot.click(found[1])
        await pilot.click(found[3])
        assert [(s.line, s.origin) for s in bridge.sent] == [
            ("preset color 2", "ui"),
            ("preset position 1", "ui"),
        ]
        await pilot.click(found[5])
        assert app.prompt.value == 'record preset position 3 "'

    drive(app, body)


def test_what_presets_apply_to() -> None:
    bridge = FakeBridge()
    app = presets_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        header = app.query_one("#presets-header")
        assert plain(header) == (
            "applies to nothing: select fixtures first · click = preset <pool> N"
        )
        bridge.events.append(
            ProgrammerChanged(programmer(version=2, selection=((101, 1), (102, 1))))
        )
        await settle(pilot, app)
        assert plain(header) == "applies to 101 thru 102 (2) · click = preset <pool> N"

    drive(app, body)


def test_a_new_preset_shows_at_once_and_an_empty_show_says_how() -> None:
    bridge = FakeBridge()
    app = presets_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, presets_show(PresetInfo("beam", 1, "Narrow", None, (("zoom", 20.0),))))
        await settle(pilot, app)
        assert [t.number for t in tiles(app)] == [1, 2]
        beam = PresetInfo("beam", 2, "Wide", None, (("zoom", 30.0),))
        narrow = PresetInfo("beam", 1, "Narrow", None, (("zoom", 20.0),))
        bridge.events.append(ShowChanged(presets_show(narrow, beam)))
        await settle(pilot, app)
        assert [(t.number, t.preset is None) for t in tiles(app)] == [
            (1, False),
            (2, False),
            (3, True),
        ]
        bridge.events.append(ShowChanged(show_model()))
        await settle(pilot, app)
        assert tiles(app) == []
        assert "no presets yet" in plain(app.query_one("#pools").children[0])

    drive(app, body)


def test_the_pane_cursor_runs_a_tile_and_prefills_a_record() -> None:
    bridge = FakeBridge()
    app = presets_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        await pilot.press("tab", "right", "enter")  # Red: runs, the cursor stays
        assert [s.line for s in bridge.sent] == ["preset color 2"]
        assert tiles(app)[1].marked
        await pilot.press("right", "enter")  # the record tile: to the prompt
        assert app.prompt.value == 'record preset color 3 "'
        assert not app.cursor.active

    drive(app, body)


def test_tiles_go_as_many_across_as_fit() -> None:
    bridge = FakeBridge()
    app = presets_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        page = app.query_one(PresetsPage)
        assert page.grids[0].styles.grid_size_columns == (150 - 6 + 1) // 16
        await pilot.resize_terminal(60, 40)
        await pilot.pause()
        assert page.grids[0].styles.grid_size_columns == 3

    drive(app, body)
