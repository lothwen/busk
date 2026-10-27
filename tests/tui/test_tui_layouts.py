"""F1 layouts A (console) and C (stage), and switching layouts (spec §8.1,
plan Phase 5): the vertical fader, the fixture cells, OUTPUT's rows, the
stage rows and their places, the playback columns and compact rows, the
programmer summary, the tempo row, what each layout reads, the switch from
the header and the pane cursor, and the layout remembered at exit.
Headless, with a fake bridge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from rich.text import Text
from test_tui_busk import club, live, scroll, started
from textual.pilot import Pilot
from tui_fakes import FakeBridge, drive, make_app, playback, programmer, settle

from busk_tui import app as tui_app
from busk_tui import colors, config
from busk_tui.model import (
    EffectInfo,
    ElementOutput,
    FixtureInfo,
    HeldValue,
    LiveChanged,
    OutputChanged,
    OutputModel,
    ProfileInfo,
    ProgrammerChanged,
    ShowModel,
)
from busk_tui.pages.busk import BuskHeader, BuskPage
from busk_tui.pages.busk_console import (
    ConsoleLayout,
    OutputGrid,
    output_rows,
    programmer_summary,
)
from busk_tui.pages.busk_stack import StackLayout
from busk_tui.pages.busk_stage import (
    NO_PLACES,
    StageLayout,
    StagePlot,
    pan_text,
    place,
    stage_rows,
)
from busk_tui.shell import BuskApp
from busk_tui.widgets.fixture_palette import UNLIT, element_cells, select_line
from busk_tui.widgets.log import LogView
from busk_tui.widgets.playbacks import PlaybackColumn, PlaybackRow
from busk_tui.widgets.tempo import TempoRow
from busk_tui.widgets.vfader import VFader, fader_text

HEAD_A = FixtureInfo(101, 1, "Spot 1", "Spot", location=(-2.0, -1.0, 5.0, 0, 0, 0))
HEAD_B = FixtureInfo(102, 1, "Spot 2", "Spot", location=(2.0, -1.04, 5.0, 0, 0, 0))
WASH_A = FixtureInfo(201, 1, "Wash 1", "Wash", location=(-3.0, 1.0, 4.0, 0, 0, 0))
WASH_B = FixtureInfo(202, 1, "Wash 2", "Wash", location=(3.0, 1.0, 4.0, 0, 0, 0))
FLOOR = FixtureInfo(203, 1, "Floor", "Wash", location=(0.0, 1.0, 0.0, 0, 0, 0))
BAR = FixtureInfo(301, 12, "Bar", "Pixel Bar")
SMOKE = FixtureInfo(401, 1, "Smoke", "Smoke Machine")
FIXTURES = (HEAD_A, HEAD_B, WASH_A, WASH_B, FLOOR, BAR, SMOKE)
PROFILES = (
    ProfileInfo("Spot", frozenset({"intensity", "pan", "tilt"}), (), "spot"),
    ProfileInfo("Wash", frozenset({"intensity", "color"}), (), "par"),
    ProfileInfo("Pixel Bar", frozenset({"intensity", "color"}), (), "pixel"),
    ProfileInfo("Smoke Machine", frozenset({"intensity"}), ()),
)


def rig(**changes: Any) -> ShowModel:
    return club(**{"fixtures": FIXTURES, "profiles": PROFILES, **changes})


def out(number: int, element: int = 1, **parts: Any) -> ElementOutput:
    given: dict[str, Any] = {
        "intensity": 1.0,
        "color": (1.0, 0.0, 0.0),
        "pan": None,
        "tilt": None,
        "zoom": None,
    }
    given.update(parts)
    return ElementOutput(number, element, **given)


OUTPUT = OutputModel(
    1,
    (
        out(101, color=None, pan=90.0, tilt=30.4),
        out(102, intensity=0.0, color=None, pan=-45.0, tilt=-10.0),
        out(201, color=(0.0, 0.0, 1.0)),
        *(out(301, element, intensity=element / 12) for element in range(1, 13)),
    ),
)


def started_on(bridge: FakeBridge, layout_show: ShowModel | None = None, **live: Any) -> None:
    started(bridge, layout_show or rig(), **live)
    bridge.events.append(OutputChanged(OUTPUT))


def sent(bridge: FakeBridge) -> list[tuple[str, str]]:
    return [(item.line, item.origin) for item in bridge.sent]


def plain_lines(widget: OutputGrid | StagePlot) -> list[str]:
    return [line.plain.rstrip() for line in widget.lines]


def style_at(line: Text, x: int) -> str:
    return " ".join(str(span.style) for span in line.spans if span.start <= x < span.end)


# ------------------------------------------------------------ the vertical fader


def test_the_fader_is_ten_rows_of_four_with_a_partial_top_row() -> None:
    assert fader_text(0.0, "red").plain.split("\n") == ["░░░░"] * 10
    assert fader_text(1.0, "red").plain.split("\n") == ["████"] * 10
    lines = fader_text(0.55, "red").plain.split("\n")  # 44 eighths: 5 rows and a half
    assert lines == ["░░░░"] * 4 + ["▄▄▄▄"] + ["████"] * 5
    assert fader_text(0.01, "red").plain.split("\n")[-1] == "▁▁▁▁"
    text = fader_text(0.55, "red")
    assert style_at(text, 0) == colors.TRACK
    assert style_at(text, text.plain.index("█")) == "red"


def test_the_fader_sets_from_the_row() -> None:
    bridge = FakeBridge()
    app = make_app(bridge, layout="A")

    async def body(pilot: Pilot[int]) -> None:
        started_on(bridge)
        await settle(pilot, app)
        fader = next(c for c in app.query(PlaybackColumn) if c.number == 2).fader
        assert fader.level_at(0) == 1.0
        assert fader.level_at(9) == 0.0
        await pilot.mouse_down(fader, offset=(1, 2))
        await pilot.hover(fader, offset=(1, 4))
        await pilot.mouse_up(fader, offset=(1, 4))
        await pilot.pause()
        lines = sent(bridge)
        assert lines[0] == ("fader 2 78%", "internal")
        assert lines[-1] == ("fader 2 56%", "ui")
        assert all(item.key == "fader:2" for item in bridge.sent)
        assert [e for e in app.query_one(LogView).entries if e[0] == "ui"] == [
            ("ui", "fader 2 56%")
        ]
        bridge.sent.clear()
        fader.post_message(scroll(fader, up=True))  # the wheel: sent, not logged
        await pilot.pause()
        assert sent(bridge)[-1] == ("fader 2 61%", "internal")

    drive(app, body)


# ---------------------------------------------------------------- fixture cells


def test_a_fixture_is_a_glyph_or_a_cell_per_element_in_its_output() -> None:
    red = out(1, intensity=1.0, color=(1.0, 0.0, 0.0))
    assert element_cells([red], 1, "███", 12, "256") == [
        ("███", colors.swatch((1, 0, 0), 1, "256"))
    ]
    assert element_cells([], 1, "■", 12, "256") == [("■", UNLIT)]
    white = out(1, intensity=0.5, color=None)
    assert element_cells([white], 1, "◆", 12, "256")[0][1] == colors.swatch((1, 1, 1), 0.5, "256")
    bar = [out(301, n, intensity=n / 12, color=(0.0, 1.0, 0.0)) for n in range(1, 13)]
    cells = element_cells(bar, 12, "■", 12, "256")
    assert [cell for cell, _ in cells] == ["█"] * 12
    assert cells[0][1] == colors.swatch((0, 1, 0), 1 / 12, "256")
    assert cells[-1][1] == colors.swatch((0, 1, 0), 1.0, "256")
    sampled = element_cells(bar, 12, "■", 4, "256")  # evenly spaced: elements 1, 4, 7, 10
    assert [style for _, style in sampled] == [cells[i][1] for i in (0, 3, 6, 9)]
    assert element_cells(bar[:3], 12, "■", 12, "256")[5] == ("█", UNLIT)  # not read yet


def test_a_click_selects_and_a_shift_click_adds_or_takes_out() -> None:
    assert select_line(101, False, True).text == "sel fixture 101"
    assert select_line(101, True, False).text == "sel + fixture 101"
    assert select_line(101, True, True).text == "sel - fixture 101"


# ------------------------------------------------------------------- layout A


def test_output_has_a_row_per_category_then_per_profile_without_one() -> None:
    rows = output_rows(rig())
    assert [(label, [f.number for f in fixtures]) for label, fixtures in rows] == [
        ("PARS", [201, 202, 203]),
        ("SPOTS", [101, 102]),
        ("PIXELS", [301]),
        ("Smoke Machine", [401]),
    ]
    assert output_rows(None) == []


def test_the_programmer_summary() -> None:
    assert programmer_summary(None).plain == "programmer empty"
    assert programmer_summary(programmer()).plain == "programmer empty"
    held = (
        HeldValue(101, 1, "intensity", 0.5, None),
        HeldValue(101, 1, "color", (1.0, 0.0, 0.0), None),
        HeldValue(102, 1, "intensity", 0.5, None),
        HeldValue(102, 1, "pan", 10.0, None),
    )
    summary = programmer_summary(
        programmer(values=held, fixtures=2, effects=(EffectInfo("fx1", "Circle"),), blind=True)
    )
    assert summary.plain == "2 fixtures · intensity color pan · 1 effect · BLIND"
    assert programmer_summary(programmer(blind=True)).plain == "programmer empty · BLIND"


def test_output_draws_each_fixture_in_its_output_and_the_selection() -> None:
    bridge = FakeBridge()
    app = make_app(bridge, layout="A")

    async def body(pilot: Pilot[int]) -> None:
        started_on(bridge)
        bridge.events.append(ProgrammerChanged(programmer(selection=((101, 1),))))
        await settle(pilot, app)
        grid = app.query_one(OutputGrid)
        lines = plain_lines(grid)
        assert lines[0].split() == ["PARS", "███", "███", "███"]
        assert lines[1].split() == ["201", "202", "203"]
        assert lines[3].split() == ["SPOTS", "███", "███"]
        assert lines[6] == "PIXELS".ljust(14) + "█" * 12
        assert lines[9].startswith("Smoke Machine")  # a profile's name: a wider label column
        spot = next(s for s in grid.spots if s.number == 201)
        mode = app.view.mode
        assert style_at(grid.lines[spot.y], spot.x) == colors.swatch((0, 0, 1), 1, mode)
        assert UNLIT in style_at(grid.lines[spot.y], spot.x + 4)  # 202: no output read
        head = next(s for s in grid.spots if s.number == 101)
        assert f"on {colors.SEL}" in style_at(grid.lines[head.y], head.x)
        assert colors.CYAN in style_at(grid.lines[head.y + 1], head.x + 1)
        other = next(s for s in grid.spots if s.number == 102)
        assert colors.DIM in style_at(grid.lines[other.y + 1], other.x + 1)
        await pilot.click(grid, offset=(spot.x, spot.y))
        await pilot.click(grid, offset=(head.x, head.y + 1), shift=True)
        await pilot.click(grid, offset=(other.x, other.y), shift=True)
        assert sent(bridge) == [
            ("sel fixture 201", "ui"),
            ("sel - fixture 101", "ui"),
            ("sel + fixture 102", "ui"),
        ]
        bridge.events.append(OutputChanged(OutputModel(2, (out(202, color=(0.0, 1.0, 0.0)),))))
        await settle(pilot, app)
        assert style_at(grid.lines[spot.y], spot.x + 4) == colors.swatch((0, 1, 0), 1, mode)

    drive(app, body)


def test_a_show_without_fixtures_says_how_to_add_one() -> None:
    bridge = FakeBridge()
    app = make_app(bridge, layout="A")

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, club(fixtures=()))
        await settle(pilot, app)
        assert plain_lines(app.query_one(OutputGrid))[0].startswith("no fixtures · fixture add")

    drive(app, body)


def test_the_playback_columns() -> None:
    bridge = FakeBridge()
    app = make_app(bridge, layout="A")

    async def body(pilot: Pilot[int]) -> None:
        started_on(bridge)
        await settle(pilot, app)
        columns = list(app.query(PlaybackColumn))
        assert [c.number for c in columns] == [1, 2, 3, None]  # page 1's slots
        first, song, chase, empty = columns
        assert first.has_class("-selected")
        assert not song.has_class("-selected")
        assert str(first.label.content) == "P1"
        assert str(first.name_text.content) == "Warm"
        assert str(first.cue.content) == "1/1"
        assert str(song.cue.content) == "—/3"
        assert str(chase.cue.content) == "chase 2"
        assert str(first.level.content) == "80"
        assert first.fader.level == 0.8
        mode = app.view.mode
        assert first.fader.color == colors.swatch((1.0, 0.75, 0.45), 1.0, mode)
        assert chase.fader.color == colors.swatch((1.0, 0.5, 0.0), 1.0, mode)  # its uiColor
        assert str(empty.label.content) == "·"
        assert str(empty.name_text.content) == "—"
        assert empty.buttons == []
        assert empty.flash is None
        await pilot.click(song.buttons[0])
        await pilot.click(song.buttons[1])
        assert sent(bridge) == [("go 2", "ui"), ("back 2", "ui")]
        flash = song.flash
        assert flash is not None
        assert str(flash.content) == "[FLASH]"
        await pilot.mouse_down(flash)
        await pilot.mouse_up(flash)
        assert sent(bridge)[-2:] == [("flash 2 on", "ui"), ("flash 2 off", "ui")]
        await pilot.click(song.label)
        assert app.view.playback == 2
        assert song.has_class("-selected")
        assert not first.has_class("-selected")
        await pilot.press("space")
        assert sent(bridge)[-1] == ("go 2", "ui")

    drive(app, body)


def test_a_column_names_a_fader_that_is_not_a_master() -> None:
    bridge = FakeBridge()
    app = make_app(bridge, layout="A")

    async def body(pilot: Pilot[int]) -> None:
        started_on(bridge)
        bridge.events.append(
            LiveChanged(
                live(
                    playbacks=(
                        playback(1, "Warm", fader="size", level=0.4),
                        playback(2, "Song", fader="none", state="active"),
                    )
                )
            )
        )
        await settle(pilot, app)
        columns = {c.number: c for c in app.query(PlaybackColumn)}
        assert str(columns[1].level.content) == "40 size"
        assert str(columns[2].level.content) == "—"
        assert columns[2].fader.command is None

    drive(app, body)


def test_the_programmer_panel() -> None:
    bridge = FakeBridge()
    app = make_app(bridge, layout="A")

    async def body(pilot: Pilot[int]) -> None:
        started_on(bridge)
        bridge.events.append(ProgrammerChanged(programmer(selection=((101, 1), (102, 1)))))
        await settle(pilot, app)
        layout = app.query_one(ConsoleLayout)
        assert str(layout.selection.content) == "sel 101 thru 102 (2)"
        assert str(layout.summary.content) == "programmer empty"
        assert [b.line.text for b in layout.chips.buttons] == ["preset color 1", "preset color 2"]
        assert [bar.label for bar in layout.bars.bars] == ["GM", "FX", "Washes"]
        tempo = app.query_one(TempoRow)
        assert tempo.master is not None
        assert tempo.master.name == "Speed 1"
        assert str(tempo.bpm.content) == "120.0"
        assert tempo.tap is not None
        await pilot.click(tempo.tap)
        await pilot.click(tempo.blackout)
        assert sent(bridge) == [('tap "Speed 1"', "ui"), ("blackout on", "ui")]
        bridge.events.append(LiveChanged(live(seq=2, blackout=True)))
        await settle(pilot, app)
        assert tempo.blackout.line.text == "blackout off"
        assert tempo.blackout.reverse
        bars = layout.bars.bars
        assert [bar.level for bar in bars] == [1.0, 0.6, 0.3]

    drive(app, body)


def test_a_show_without_a_speed_master_has_only_blackout_in_the_tempo_row() -> None:
    bridge = FakeBridge()
    app = make_app(bridge, layout="A")

    async def body(pilot: Pilot[int]) -> None:
        masters = tuple(m for m in rig().masters if m.kind != "speed")
        started_on(bridge, rig(masters=masters))
        await settle(pilot, app)
        tempo = app.query_one(TempoRow)
        assert tempo.master is None
        assert tempo.tap is None
        assert str(tempo.name_text.content) == "no speed master"
        assert [stop.item.line for stop in tempo.stops()] == ["blackout on"]

    drive(app, body)


# ------------------------------------------------------------------- layout C


def test_stage_rows_by_depth_and_height_upstage_first() -> None:
    rows, unplaced = stage_rows(FIXTURES)
    assert [(row.y, row.z, [f.number for _, f in row.fixtures]) for row in rows] == [
        (-1.0, 5.0, [101, 102]),  # 102 at -1.04: the same depth to 0.1 m
        (1.0, 4.0, [201, 202]),
        (1.0, 0.0, [203]),  # the same depth, lower: under the truss
    ]
    assert [f.number for f in unplaced] == [301, 401]
    assert stage_rows(()) == ([], [])


def test_places_keep_their_order_and_a_cell_between_two() -> None:
    assert place([3, 3], [10.0, 50.0], 60) == [[(0, 8), (1, 48)]]
    assert place([3, 3], [10.0, 10.0], 60) == [[(0, 8), (1, 12)]]  # pushed apart
    assert place([3, 3], [59.0, 59.0], 60) == [[(0, 53), (1, 57)]]  # pushed back in
    assert place([4], [0.0], 60) == [[(0, 0)]]
    lines = place([5] * 5, [1.0] * 5, 12)  # two fit on a line: spread over three
    assert [[index for index, _ in line] for line in lines] == [[0, 1], [2, 3], [4]]
    assert lines[0] == [(0, 0), (1, 6)]
    assert place([], [], 10) == []


def test_pan_as_an_arrow_and_tilt_in_degrees() -> None:
    def text(pan: float | None, tilt: float | None) -> str:
        return pan_text([out(1, pan=pan, tilt=tilt)])

    assert text(0.0, 0.0) == "↑ 0°"
    assert text(45.0, 30.4) == "↗ 30°"
    assert text(90.0, -10.0) == "→ -10°"
    assert text(180.0, None) == "↓"
    assert text(-90.0, 5.0) == "← 5°"
    assert text(None, None) == "·"
    assert pan_text([]) == "·"


def test_the_stage_plot() -> None:
    bridge = FakeBridge()
    app = make_app(bridge, layout="C")

    async def body(pilot: Pilot[int]) -> None:
        started_on(bridge)
        bridge.events.append(ProgrammerChanged(programmer(selection=((102, 1),))))
        await settle(pilot, app)
        plot = app.query_one(StagePlot)
        lines = plain_lines(plot)
        assert lines[0].startswith("y -1.0")
        assert "◆" in lines[0]
        assert "┄" in lines[0]
        assert lines[1].split() == ["z", "5.0", "101", "102"]
        assert lines[2].split() == ["→", "30°", "↖", "-10°"]  # the movers' pan and tilt
        assert lines[4].startswith("y 1.0")
        assert lines[4].count("■") == 2
        assert lines[5].split() == ["z", "4.0", "201", "202"]
        assert lines[7].startswith("y 1.0")
        assert lines[8].split() == ["z", "0.0", "203"]
        audience = lines.index(next(line for line in lines if "AUDIENCE" in line))
        assert audience == 10
        assert lines[12].startswith("no place")
        assert "█" * 12 in lines[12]
        assert "◇" in lines[12]
        spots = {spot.number: spot for spot in plot.spots}
        assert [spot.number for spot in plot.spots] == [101, 102, 201, 202, 203, 301, 401]
        assert spots[101].x < spots[102].x
        assert spots[201].x < spots[203].x < spots[202].x
        assert spots[201].x < spots[101].x  # x = -3 is left of x = -2, on every row
        assert spots[101].height == 3
        assert spots[201].height == 2
        wash = spots[201]
        blue = colors.swatch((0, 0, 1), 1, app.view.mode)
        assert style_at(plot.lines[wash.y], wash.x + 1) == blue
        selected = spots[102]
        assert f"on {colors.SEL}" in style_at(plot.lines[selected.y + 2], selected.x)
        await pilot.click(plot, offset=(wash.x, wash.y + 1))
        await pilot.click(plot, offset=(selected.x, selected.y), shift=True)
        assert sent(bridge) == [("sel fixture 201", "ui"), ("sel - fixture 102", "ui")]

    drive(app, body)


def test_the_location_prefill_and_a_rig_with_no_places() -> None:
    bridge = FakeBridge()
    app = make_app(bridge, layout="C")
    loose = tuple(FixtureInfo(f.number, f.elements, f.name, f.profile) for f in FIXTURES)

    async def body(pilot: Pilot[int]) -> None:
        started_on(bridge, rig(fixtures=loose))
        await settle(pilot, app)
        layout = app.query_one(StageLayout)
        lines = plain_lines(layout.plot)
        assert lines[0].strip() == NO_PLACES
        assert "AUDIENCE" in lines[2]
        assert lines[4].startswith("no place")
        assert str(layout.edit_label.content) == "place fixture 101 Spot 1"
        await pilot.click(layout.edits, offset=(1, 0))
        assert app.prompt.value == (
            'fixture 101 location {"x": 0, "y": 0, "z": 0, "rx": 0, "ry": 0, "rz": 0}'
        )
        bridge.events.append(ProgrammerChanged(programmer(selection=((202, 1),))))
        await settle(pilot, app)
        assert str(layout.edit_label.content) == "place fixture 202 Wash 2"

    drive(app, body)


def test_the_location_prefill_starts_from_the_fixtures_place() -> None:
    bridge = FakeBridge()
    app = make_app(bridge, layout="C")

    async def body(pilot: Pilot[int]) -> None:
        started_on(bridge)
        await settle(pilot, app)
        layout = app.query_one(StageLayout)
        assert str(layout.edit_label.content) == "place fixture 301 Bar"  # the first unplaced
        bridge.events.append(ProgrammerChanged(programmer(selection=((101, 1),))))
        await settle(pilot, app)
        assert layout.edits.buttons[0].prefill == (
            'fixture 101 location {"x": -2, "y": -1, "z": 5, "rx": 0, "ry": 0, "rz": 0}'
        )

    drive(app, body)


def test_compact_rows_masters_and_quick() -> None:
    bridge = FakeBridge()
    app = make_app(bridge, layout="C")

    async def body(pilot: Pilot[int]) -> None:
        started_on(bridge)
        await settle(pilot, app)
        layout = app.query_one(StageLayout)
        rows = {row.number: row for row in layout.rows}
        assert set(rows) == {1, 2, 3, None}
        first = rows[1]
        assert first.compact
        assert first.has_class("-selected")
        assert [b.line.text for b in first.buttons] == ["go 1"]
        assert first.flash is None
        assert not first.cue.is_mounted
        assert str(first.level.content) == "80"
        assert first.bar.color == colors.swatch((1.0, 0.75, 0.45), 1.0, app.view.mode)
        await pilot.click(rows[2].buttons[0])
        assert sent(bridge) == [("go 2", "ui")]
        assert [bar.label for bar in layout.bars.bars] == ["GM", "FX", "Washes"]
        assert [b.line.text for b in layout.groups.buttons] == ["sel group 1", "sel group 2"]
        assert [b.shift.text for b in layout.groups.buttons if b.shift] == [
            "sel + group 1",
            "sel + group 2",
        ]
        assert [b.line.text for b in layout.chips.buttons] == ["preset color 1", "preset color 2"]
        assert layout.tempo is not None
        assert layout.tempo.master is not None

    drive(app, body, size=(150, 48))


# ------------------------------------------------------------ switching layouts


def test_the_header_switches_the_layout_and_the_reads_follow() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started_on(bridge)
        await settle(pilot, app)
        page = app.query_one(BuskPage)
        assert page.shown == "B"
        assert app.query_one(StackLayout).display
        assert bridge.watching == (False, True)  # B's effects
        await pilot.press("right")
        assert app.view.playback == 2
        header = app.query_one(BuskHeader)
        await pilot.click(header, offset=(header.size.width - 25, 0))  # " A console "
        assert app.view.layout == "A"
        assert page.shown == "A"
        assert app.query_one(ConsoleLayout).display
        assert not app.query_one(StackLayout).display
        assert header.shown_layout == "A"
        assert bridge.watching == (True, False)  # A's output
        assert app.view.playback == 2
        assert next(c for c in app.query(PlaybackColumn) if c.number == 2).has_class("-selected")
        assert app.query_one(OutputGrid).lines  # drawn as it showed
        app.action_layout("C")
        await pilot.pause()
        assert app.query_one(StageLayout).display
        assert bridge.watching == (True, False)
        assert next(r for r in app.query_one(StageLayout).rows if r.number == 2).has_class(
            "-selected"
        )
        await pilot.press("f7")
        assert bridge.watching == (False, False)
        await pilot.press("f1")
        assert bridge.watching == (True, False)
        assert page.shown == "C"

    drive(app, body)


def test_layout_a_starts_from_the_settings() -> None:
    bridge = FakeBridge()
    app = make_app(bridge, layout="A")

    async def body(pilot: Pilot[int]) -> None:
        started_on(bridge)
        await settle(pilot, app)
        assert app.query_one(BuskPage).shown == "A"
        assert bridge.watching == (True, False)
        assert not app.query_one(StageLayout).display

    drive(app, body)


def test_the_pane_cursor_reaches_each_layout_and_switches_them() -> None:
    bridge = FakeBridge()
    app = make_app(bridge, layout="A")

    async def body(pilot: Pilot[int]) -> None:
        started_on(bridge)
        await settle(pilot, app)
        items = app.current_page.items()
        labels = [item.line or item.prefill or item.label for item in items]
        assert labels[:6] == ["go 1", "back 1", "go 2", "back 2", "go 3", "back 3"]
        assert labels[6:8] == ["preset color 1", "preset color 2"]
        assert labels[8:11] == ["gm ", 'master "FX" ', 'master "Washes" ']
        assert labels[11:13] == ['tap "Speed 1"', "blackout on"]
        assert labels[13:20] == [f"sel fixture {n}" for n in (201, 202, 203, 101, 102, 301, 401)]
        assert labels[20:] == ["layout A console", "layout B stack", "layout C stage"]
        await pilot.press("tab", *["down"] * 22, "enter")  # layout C
        await pilot.pause()
        assert app.view.layout == "C"
        assert app.cursor.active
        assert app.cursor.current is not None
        assert app.cursor.current.label == "layout C stage"
        assert app.query_one(BuskHeader).marked == 2
        items = app.current_page.items()
        labels = [item.line or item.prefill or item.label for item in items]
        assert labels[:3] == ["go 1", "go 2", "go 3"]
        assert "sel fixture 401" in labels
        assert labels[-4] == (
            'fixture 301 location {"x": 0, "y": 0, "z": 0, "rx": 0, "ry": 0, "rz": 0}'
        )
        await pilot.press("up", "up", "enter")  # layout A
        await pilot.pause()
        assert app.view.layout == "A"
        await pilot.press("escape")
        assert not app.cursor.active
        assert app.query_one(BuskHeader).marked is None

    drive(app, body)


def test_the_layout_chosen_is_remembered_at_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    show = tmp_path / "club.show"
    show.write_text("")

    def standalone(*args: Any, **kwargs: Any) -> FakeBridge:
        return FakeBridge()

    def run(self: BuskApp) -> int:
        assert self.view.layout == "B"
        self.view.layout = "C"
        return 0

    monkeypatch.setattr("busk_tui.bridge.Bridge.standalone", staticmethod(standalone))
    monkeypatch.setattr(tui_app, "_debug_log", lambda: None)  # no handler left behind
    monkeypatch.setattr(BuskApp, "run", run)
    assert tui_app.main([str(show), "--standalone"]) == 0
    state = json.loads((tmp_path / "busk-tui" / "state.json").read_text())
    assert state["layout"] == "C"
    assert config.settings(config.Options(), config=tmp_path / "none.toml",
                           state=tmp_path / "busk-tui" / "state.json").layout == "C"  # fmt: skip


def test_layouts_a_and_c_stack_below_100_columns() -> None:
    bridge = FakeBridge()
    app = make_app(bridge, layout="A")

    async def body(pilot: Pilot[int]) -> None:
        started_on(bridge)
        await settle(pilot, app)
        output = app.query_one("#console-output")
        programmer_panel = app.query_one("#console-programmer")
        assert programmer_panel.region.y > output.region.y
        assert programmer_panel.region.width == output.region.width
        app.action_layout("C")
        await pilot.pause()
        stage, side = app.query_one("#stage-panel"), app.query_one("#stage-side")
        assert side.region.y > stage.region.y
        assert side.region.width == stage.region.width

    drive(app, body, size=(99, 40))


def test_side_by_side_from_100_columns() -> None:
    bridge = FakeBridge()
    app = make_app(bridge, layout="A")

    async def body(pilot: Pilot[int]) -> None:
        started_on(bridge)
        await settle(pilot, app)
        output = app.query_one("#console-output")
        programmer_panel = app.query_one("#console-programmer")
        assert programmer_panel.region.y == output.region.y
        assert programmer_panel.region.width >= 38
        columns = list(app.query(PlaybackColumn))
        assert all(c.region.width >= 11 for c in columns)
        assert len({c.region.y for c in columns}) == 1  # four columns on one line
        assert all(isinstance(c.fader, VFader) and c.fader.region.width == 4 for c in columns)

    drive(app, body, size=(100, 40))


def test_rows_in_b_are_untouched_by_the_compact_ones() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started_on(bridge)
        await settle(pilot, app)
        row = next(r for r in app.query_one(StackLayout).rows if r.number == 1)
        assert not row.compact
        assert row.cue.is_mounted
        assert row.flash is not None
        assert isinstance(row, PlaybackRow)

    drive(app, body)
