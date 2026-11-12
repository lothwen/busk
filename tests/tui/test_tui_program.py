"""F2 Program (spec §8.2, plan Phase 2): which encoders show, what they show
and send, the pending value, the selection and group buttons, the quick
lines and toggles, and PROGRAMMER CONTENTS; the option rows (pending plan
Phase 36). The rules first (no Textual), then headless, with a fake bridge
(and, for the options, busk's own completion on the example shows)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from rich.text import Text
from textual import events
from textual.pilot import Pilot
from textual.widget import Widget
from tui_fakes import FakeBridge, drive, make_app, programmer, settle, show_model

import busk
from busk_tui import attributes, colors, config
from busk_tui.attributes import Encoder, Reading, selected
from busk_tui.bridge import selection_options
from busk_tui.bridge import show_model as model_of
from busk_tui.model import (
    ElementOutput,
    FixtureInfo,
    GroupInfo,
    HeldValue,
    OutputChanged,
    OutputModel,
    PresetInfo,
    ProfileInfo,
    ProgrammerChanged,
    ProgrammerModel,
    ShowChanged,
    ShowModel,
)
from busk_tui.pages.program import EncoderPanel, ProgramPage, quick_buttons
from busk_tui.shell import BuskApp
from busk_tui.widgets import encoders
from busk_tui.widgets.controls import ButtonStrip
from busk_tui.widgets.encoders import EncoderRow
from busk_tui.widgets.log import LogView
from busk_tui.widgets.options import LIT, OptionRow
from busk_tui.widgets.programmer import (
    EMPTY,
    OTHER_AT,
    OTHER_MIN,
    ProgrammerTable,
    contents,
    other_lines,
)

SPOT = ProfileInfo(
    "Spot",
    frozenset({"intensity", "pan", "tilt", "color", "color.w", "zoom", "shutter", "strobeRate"}),
    (("pan", -270.0, 270.0), ("tilt", -135.0, 135.0), ("zoom", 12.0, 30.0),
     ("strobeRate", 1.0, 20.0)),
)  # fmt: skip
PAR = ProfileInfo("Par", frozenset({"intensity", "color"}), ())
WIDE = ProfileInfo("Wide", frozenset({"pan"}), (("pan", -320.0, 320.0),))


def rig(**changes: Any) -> ShowModel:
    """Two spots, a par and a four-cell bar of pars; two colour presets."""
    parts: dict[str, Any] = {
        "fixtures": (
            FixtureInfo(101, 1, "Spot 101", "Spot"),
            FixtureInfo(102, 1, "Spot 102", "Spot"),
            FixtureInfo(201, 1, "Par 201", "Par"),
            FixtureInfo(301, 4, "Bar 301", "Par"),
        ),
        "profiles": (SPOT, PAR),
        "groups": (GroupInfo(1, "Heads"), GroupInfo(2, "Washes")),
        "presets": (
            PresetInfo("color", 1, "Blue", (0.0, 0.0, 1.0)),
            PresetInfo("color", 2, "Red", (1.0, 0.0, 0.0)),
        ),
    }
    parts.update(changes)
    return show_model(**parts)


HEADS = ((101, 1), (102, 1))


def held(number: int, attribute: str, value: Any, preset: str | None = None) -> HeldValue:
    return HeldValue(number, 1, attribute, value, preset)


def heads(*values: HeldValue, **changes: Any) -> ProgrammerModel:
    """The heads selected, holding ``values``."""
    parts: dict[str, Any] = {
        "selection": HEADS,
        "values": values,
        "fixtures": len({value.number for value in values}),
    }
    parts.update(changes)
    return programmer(**parts)


def output(*elements: ElementOutput, seq: int = 1) -> OutputModel:
    return OutputModel(seq, elements)


def head_out(number: int = 101, **changes: Any) -> ElementOutput:
    parts: dict[str, Any] = {"intensity": 0.4, "color": (1.0, 0.5, 0.0), "pan": 30.0,
                             "tilt": -20.0, "zoom": 21.0}  # fmt: skip
    parts.update(changes)
    return ElementOutput(number, 1, **parts)


def encoder(attribute: str) -> Encoder:
    return next(e for _, rows in attributes.FAMILIES for e in rows if e.attribute == attribute)


def reading(
    attribute: str, prog: ProgrammerModel | None, out: OutputModel | None = None
) -> Reading:
    show = rig()
    return attributes.reading(encoder(attribute), show, selected(show, prog, out))


RED = (("r", 1.0), ("g", 0.0), ("b", 0.0))


# ----------------------------------------------------------------- rules


def test_the_panels_follow_the_profiles_of_the_rig() -> None:
    names = [
        (family, [e.attribute for e in rows], options)
        for family, rows, options in attributes.shown(rig())
    ]
    assert names == [
        ("intensity", ["intensity"], ()),
        ("position", ["pan", "tilt"], ()),
        ("color", ["color.r", "color.g", "color.b", "color.w"], ()),
        ("beam", ["zoom"], ()),
        ("shutter", ["strobeRate"], ("shutter",)),
    ]
    pars_only = rig(fixtures=(FixtureInfo(201, 1, "Par 201", "Par"),))
    assert [family for family, _, _ in attributes.shown(pars_only)] == ["intensity", "color"]
    colors_rows = {family: rows for family, rows, _ in attributes.shown(pars_only)}["color"]
    assert [e.attribute for e in colors_rows] == ["color.r", "color.g", "color.b"]  # no white
    assert attributes.shown(None) == []


def test_a_bars_range_is_the_first_selected_fixtures_profile_else_the_widest() -> None:
    show = rig(profiles=(SPOT, PAR, WIDE))
    pan = encoder("pan")
    assert attributes.value_range(pan, show, SPOT) == (-270.0, 270.0)
    assert attributes.value_range(pan, show, PAR) == (-320.0, 320.0)  # no pan: the widest
    assert attributes.value_range(pan, show, None) == (-320.0, 320.0)
    assert attributes.value_range(encoder("intensity"), show, SPOT) == (0.0, 1.0)
    assert attributes.value_range(encoder("strobeRate"), show, SPOT) == (1.0, 20.0)
    assert selected(show, heads(), None).profile == SPOT  # the first selected fixture's
    on_par = selected(show, programmer(selection=((301, 2), (101, 1))), None)
    assert (on_par.first, on_par.profile) == ((301, 2), PAR)


def test_levels_and_values_and_the_lines_they_send() -> None:
    assert attributes.to_value(0.5, (-270.0, 270.0), "degrees") == 0.0
    assert attributes.to_value(0.4167, (-270.0, 270.0), "degrees") == -45.0
    assert attributes.to_value(0.333, (12.0, 30.0), "degrees") == 18.0  # a tenth under 60°
    assert attributes.to_value(0.7234, (0.0, 1.0), "level") == 0.72
    assert attributes.to_value(0.5, (1.0, 20.0), "hz") == 10.5
    assert attributes.to_level(-45.0, (-270.0, 270.0)) == pytest.approx(0.41667, abs=1e-4)
    assert attributes.to_level(5.0, (5.0, 5.0)) == 0.0
    assert attributes.set_line(encoder("pan"), -45.0).text == "set pan -45"
    assert attributes.set_line(encoder("intensity"), 0.72).text == "set intensity 72%"
    assert attributes.set_line(encoder("color.r"), 0.5).text == "set color.r 50%"
    assert attributes.set_line(encoder("strobeRate"), 10.5).text == "set strobeRate 10.5"
    assert attributes.step_line(encoder("intensity"), 0.05).text == "set intensity by 5%"
    assert attributes.step_line(encoder("pan"), -15.0).text == "set pan by -15"
    assert attributes.step_line(encoder("color.w"), -0.02).text == "set color.w by -2%"


def test_a_reading_from_the_programmer_with_a_preset_its_value() -> None:
    held_pan = heads(held(101, "pan", -45.0), held(101, "color", RED, "Red"))
    pan = reading("pan", held_pan, output(head_out()))
    assert (pan.value, pan.source, pan.settable, pan.steps) == (-45.0, "programmer", True, True)
    red = reading("color.r", held_pan, None)
    assert (red.value, red.source, red.preset) == (1.0, "programmer", "Red")
    white = reading("color.w", held_pan, None)  # a colour without w: 0
    assert (white.value, white.source) == (0.0, "programmer")


def test_a_reading_from_the_output_is_dim_and_its_steps_inert() -> None:
    nothing_held = heads()
    out = output(head_out())
    intensity = reading("intensity", nothing_held, out)
    assert (intensity.value, intensity.source) == (0.4, "output")
    assert (intensity.settable, intensity.steps) == (True, False)
    assert reading("zoom", nothing_held, out).value == 21.0
    strobe = reading("strobeRate", nothing_held, out)  # no output value
    assert (strobe.value, strobe.source) == (None, None)
    red = reading("color.r", nothing_held, out)  # the colour is one swatch
    assert (red.value, red.settable, red.steps) == (None, False, False)


def test_steps_act_where_a_selected_element_holds_the_attribute() -> None:
    other = heads(held(201, "intensity", 0.5))  # held, but not by the selection
    assert not reading("intensity", other, None).steps
    second = heads(held(102, "intensity", 0.5))  # the second selected holds it
    shown = reading("intensity", second, None)
    assert shown.steps
    assert shown.value is None  # the encoders show the first selected
    nothing = programmer()
    assert not reading("intensity", nothing).settable


def test_units_as_shown() -> None:
    assert attributes.number_text("intensity", 0.55) == "55%"
    assert attributes.number_text("pan", -45.0) == "-45°"
    assert attributes.number_text("zoom", 12.5) == "12.5°"
    assert attributes.number_text("strobeRate", 10.0) == "10Hz"
    assert attributes.number_text("gobo1Rotation", 90.0) == "90°/s"
    assert attributes.summary_text("pan", None) == "mixed"
    assert attributes.summary_text("gobo1", "breakup") == "breakup"
    assert attributes.rgb_text(RED) == "1.00 0.00 0.00"
    assert attributes.rgb_text((("r", 0.5), ("g", 0.0), ("b", 0.0), ("w", 0.25))) == (
        "0.50 0.00 0.00 w0.25"
    )
    assert attributes.rgb((("r", 0.5), ("g", 0.0), ("b", 0.0), ("w", 0.25))) == (0.75, 0.25, 0.25)


def test_the_programmer_table() -> None:
    values = (
        held(101, "intensity", 0.5),
        held(101, "color", RED, "Red"),
        held(101, "pan", -45.0),
        held(101, "strobeRate", 10.0),
        held(101, "shutter", "strobe"),
        HeldValue(301, 1, "color", RED, None),
        HeldValue(301, 2, "color", (("r", 0.0), ("g", 0.0), ("b", 1.0)), None),
        HeldValue(301, 1, "intensity", 1.0, None),
        HeldValue(301, 2, "intensity", 1.0, None),
    )
    lines = [line.plain for line in contents(heads(*values), rig(), "256")]
    header, spot, bar = lines
    assert header.split() == ["#", "name", "intensity", "colour", "pan", "tilt", "zoom", "other"]
    assert spot.split() == ["101", "Spot", "101", "50%", "██", "Red", "-45°", "·", "·",
                            "strobeRate", "10Hz", "·", "shutter", "strobe"]  # fmt: skip
    assert bar.split() == ["301", "Bar", "301", "100%", "██", "mixed", "·", "·", "·"]
    assert len(contents(None, rig(), "256")) == 1  # the header alone


def test_other_attributes_wrap_in_their_column() -> None:
    items = ["strobeRate 10Hz", "gobo1 breakup", "shutter strobe", "prism off"]
    assert other_lines(items, None) == [" · ".join(items)]
    assert other_lines(items, 100) == [" · ".join(items)]
    assert other_lines(items, 32) == [
        "strobeRate 10Hz · gobo1 breakup",
        "shutter strobe · prism off",
    ]
    assert other_lines(items, 14) == [
        "strobeRate", "10Hz", "gobo1 breakup", "shutter strobe", "prism off",
    ]  # fmt: skip
    assert other_lines(["gobo1 breakup", "zoom"], 11) == ["gobo1", "breakup", "zoom"]
    assert other_lines(["strobeRate 10Hz", "zoom"], 14) == ["strobeRate", "10Hz", "zoom"]
    assert other_lines(["gobo1 open", "frost 0%"], 18) == ["gobo1 open", "frost 0%"]  # 21 with ·
    assert other_lines(items, OTHER_MIN - 1) == [" · ".join(items)]  # the screen wraps it
    assert other_lines([], 20) == []
    values = (held(101, "strobeRate", 10.0), held(101, "gobo1", "breakup"))
    _, spot = contents(heads(*values), rig(), "256", cells=OTHER_AT + 11)
    first, *rest = spot.plain.split("\n")
    assert first.split()[-1] == "strobeRate"
    assert rest == [" " * OTHER_AT + part for part in ("10Hz", "gobo1", "breakup")]


# ------------------------------------------------------------------ the page


def sent(bridge: FakeBridge) -> list[tuple[str, str, str | None]]:
    return [(s.line, s.origin, s.key) for s in bridge.sent]


def started(bridge: FakeBridge, show: ShowModel | None = None, **live: Any) -> None:
    bridge.events += [ShowChanged(show or rig()), ProgrammerChanged(live.get("prog", heads()))]
    if "out" in live:
        bridge.events.append(OutputChanged(live["out"]))


def rows(app: BuskApp) -> dict[str, EncoderRow]:
    return {row.encoder.attribute: row for row in app.query(EncoderRow)}


def plain(widget: Any) -> str:
    """What a widget shows: a Static's content, else what it renders."""
    rendered = widget.content if hasattr(widget, "content") else widget.render()
    return rendered.plain if isinstance(rendered, Text) else str(rendered)


def value_of(row: EncoderRow) -> Text:
    content = row.value.content
    assert isinstance(content, Text)
    return content


def program_app(bridge: FakeBridge, **settings: Any) -> BuskApp:
    return make_app(bridge, page=2, **settings)


def scroll(widget: Widget, *, up: bool) -> events.MouseEvent:
    kind = events.MouseScrollUp if up else events.MouseScrollDown
    return kind(widget, 0, 0, 0, 0, 0, False, False, False)


def test_f2_watches_the_output_and_shows_the_rigs_panels() -> None:
    bridge = FakeBridge()
    app = program_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        assert bridge.watching == (True, False)
        started(bridge)
        await settle(pilot, app)
        panels = [panel.family for panel in app.query(EncoderPanel)]
        assert panels == ["intensity", "position", "color", "beam", "shutter"]
        await pilot.press("f1")
        assert bridge.watching == (False, True)

    drive(app, body)


def test_values_magenta_from_the_programmer_dim_from_the_output() -> None:
    bridge = FakeBridge()
    app = program_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, prog=heads(held(101, "pan", -45.0)), out=output(head_out()))
        await settle(pilot, app)
        found = rows(app)
        pan = value_of(found["pan"])
        assert (pan.plain, str(pan.style)) == ("-45°", colors.MAGENTA)
        intensity = value_of(found["intensity"])
        assert (intensity.plain, str(intensity.style)) == ("40%", colors.DIM)
        assert value_of(found["strobeRate"]).plain == "—"
        assert found["pan"].bar.color == colors.CYAN
        assert found["intensity"].bar.color == f"{colors.FG} dim"
        assert not found["pan"].minus.inert
        assert found["intensity"].minus.inert

    drive(app, body)


def test_a_click_on_a_bar_sends_one_set_in_its_unit() -> None:
    bridge = FakeBridge()
    app = program_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        found = rows(app)
        pan = found["pan"].bar
        await pilot.click(pan, offset=(0, 0))
        intensity = found["intensity"].bar
        await pilot.click(intensity, offset=(intensity.size.width - 1, 0))
        assert sent(bridge) == [
            ("set pan -270", "ui", "set:pan"),
            ("set intensity 100%", "ui", "set:intensity"),
        ]
        log = [text for kind, text in app.query_one(LogView).entries if kind == "ui"]
        assert log == ["set pan -270", "set intensity 100%"]

    drive(app, body)


def test_a_drag_sends_at_most_every_drag_s_and_logs_the_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Moves within ``DRAG_S`` of the last line wait for a timer, which sends
    the newest; moves after it send at once; the release logs the last."""
    bridge = FakeBridge()
    app = program_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        bar = rows(app)["intensity"].bar
        width = bar.size.width
        monkeypatch.setattr(encoders, "DRAG_S", 60.0)
        await pilot.mouse_down(bar, offset=(0, 0))
        for x in range(1, 6):
            await pilot.hover(bar, offset=(x, 0))
        assert bridge.sent == []  # a click sends on release only; the moves wait
        assert bar._later is not None
        bar._report()  # the timer: the newest level
        await pilot.pause()
        monkeypatch.setattr(encoders, "DRAG_S", 0.0)
        await pilot.hover(bar, offset=(width // 2, 0))
        await pilot.mouse_up(bar, offset=(width - 1, 0))
        lines = sent(bridge)
        assert {origin for _, origin, _ in lines[:-1]} == {"internal"}  # (the pilot moves first)
        assert len(lines) >= 3
        assert lines[0][0] == f"set intensity {round(5 / (width - 1) * 100)}%"
        assert lines[-1] == ("set intensity 100%", "ui", "set:intensity")
        logged = [text for kind, text in app.query_one(LogView).entries if kind == "ui"]
        assert logged == ["set intensity 100%"]

    drive(app, body)


def test_steps_and_the_wheel_act_where_the_programmer_holds_the_attribute() -> None:
    bridge = FakeBridge()
    app = program_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, prog=heads(held(101, "intensity", 0.5), held(101, "pan", 10.0)))
        await settle(pilot, app)
        found = rows(app)
        await pilot.click(found["intensity"].plus)
        await pilot.click(found["intensity"].minus)
        await pilot.click(found["pan"].plus)
        await pilot.click(found["tilt"].plus)  # not held: inert
        found["intensity"].bar.post_message(scroll(found["intensity"].bar, up=True))
        found["pan"].bar.post_message(scroll(found["pan"].bar, up=False))
        found["tilt"].bar.post_message(scroll(found["tilt"].bar, up=True))  # inert
        await pilot.pause()
        assert sent(bridge) == [
            ("set intensity by 5%", "ui", None),
            ("set intensity by -5%", "ui", None),
            ("set pan by 15", "ui", None),
            ("set intensity by 2%", "internal", None),
            ("set pan by -5", "internal", None),
        ]
        logged = [text for kind, text in app.query_one(LogView).entries if kind == "ui"]
        assert "set intensity by 2%" not in logged  # the wheel is not logged

    drive(app, body)


def test_a_colour_components_bar_sets_only_while_the_programmer_holds_a_colour() -> None:
    bridge = FakeBridge()
    app = program_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        red = rows(app)["color.r"].bar
        await pilot.click(red, offset=(3, 0))
        assert bridge.sent == []
        assert "set a colour first" in plain(app.query_one(".enc-swatches"))
        bridge.events.append(ProgrammerChanged(heads(held(101, "color", RED, "Red"), version=2)))
        await settle(pilot, app)
        assert "programmer ███ Red" in plain(app.query_one(".enc-swatches"))
        await pilot.click(red, offset=(red.size.width - 1, 0))
        assert sent(bridge) == [("set color.r 100%", "ui", "set:color.r")]

    drive(app, body)


def test_the_value_sent_shows_until_the_programmer_shows_it() -> None:
    bridge = FakeBridge(auto_reply=False)
    app = program_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, prog=heads(held(101, "intensity", 0.5)))
        await settle(pilot, app)
        row = rows(app)["intensity"]
        await pilot.click(row.bar, offset=(row.bar.size.width - 1, 0))
        assert value_of(row).plain == "100%"  # pending, before busk has run it
        (line,) = bridge.sent
        bridge.events.append(done(line.ticket, line.line, ok=True))
        await settle(pilot, app)
        assert value_of(row).plain == "100%"  # done, but the programmer has not shown it yet
        bridge.events.append(ProgrammerChanged(heads(held(101, "intensity", 0.9), version=2)))
        await settle(pilot, app)
        assert value_of(row).plain == "90%"  # what busk holds
        await pilot.click(row.bar, offset=(0, 0))
        failed = bridge.sent[-1]
        bridge.events.append(done(failed.ticket, failed.line, ok=False))
        await settle(pilot, app)
        assert value_of(row).plain == "90%"  # refused: back at once

    drive(app, body)


def done(ticket: int, line: str, *, ok: bool) -> Any:
    from busk_tui.model import CommandDone

    return CommandDone(ticket, line, "ui", ok, () if ok else ("error: no",), 0.0, False)


def test_a_click_on_the_name_and_enter_on_the_pane_cursor_prefill() -> None:
    bridge = FakeBridge()
    app = program_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, prog=heads(held(101, "intensity", 0.5)))
        await settle(pilot, app)
        await pilot.click(rows(app)["pan"].name_text)
        assert app.prompt.value == "set pan "
        await pilot.press("escape", "tab")  # into the page: the first group button
        assert app.cursor.current is not None
        assert app.cursor.current.line == "sel group 1"
        await pilot.press("down", "down", "down")  # [2 Washes], [none], intensity's name
        assert app.cursor.current.prefill == "set intensity "
        await pilot.press("down")  # its [−]: runs, the cursor stays
        await pilot.press("enter", "enter")
        assert [s.line for s in bridge.sent] == ["set intensity by -5%"] * 2
        await pilot.press("up", "enter")
        assert app.prompt.value == "set intensity "

    drive(app, body)


def test_the_selection_and_the_group_buttons() -> None:
    bridge = FakeBridge()
    app = program_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, prog=programmer(selection=((301, 2), (301, 3), (101, 1))))
        await settle(pilot, app)
        page = app.query_one(ProgramPage)
        assert plain(page.selection) == "301.2 thru 301.3, 101 (3 · encoders show 301.2)"
        groups = app.query_one("#program-groups", ButtonStrip)
        assert plain(groups) == "[1 Heads] [2 Washes] [none]"
        await pilot.click(groups, offset=(1, 0))
        await pilot.click(groups, offset=(12, 0), shift=True)
        await pilot.click(groups, offset=(23, 0))
        assert [s.line for s in bridge.sent] == ["sel group 1", "sel + group 2", "sel none"]
        bridge.events.append(ProgrammerChanged(programmer(version=2)))
        await settle(pilot, app)
        assert plain(page.selection) == "nothing selected"

    drive(app, body)


def test_the_quick_lines_come_from_the_settings_and_the_toggles_follow_the_programmer() -> None:
    assert [b.label.plain for b in quick_buttons(("clear",), None)] == [
        "[clear]", "[highlight on]", "[blind on]", "[fade 0s…]",
    ]  # fmt: skip
    lit = quick_buttons((), programmer(blind=True, highlight=True, fadeTime=1.5))
    assert [b.line.text for b in lit[:2]] == ["highlight off", "blind off"]
    assert [b.label.plain for b in lit] == ["[highlight off]", "[blind off]", "[fade 1.5s…]"]
    assert lit[2].prefill == "fade "
    bridge = FakeBridge()
    app = program_app(bridge, quick=("sel group 2", "record cue 1"))

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        strip = app.query_one("#quick", ButtonStrip)
        assert plain(strip).startswith("[sel group 2] [record cue 1] [highlight on] [blind on]")
        await pilot.click(strip, offset=(1, 0))
        await pilot.click(strip, offset=(plain(strip).index("[blind") + 1, 0))
        assert [s.line for s in bridge.sent] == ["sel group 2", "blind on"]
        bridge.events.append(ProgrammerChanged(heads(blind=True, version=2)))
        await settle(pilot, app)
        assert "[blind off]" in plain(strip)
        await pilot.click(strip, offset=(plain(strip).index("[fade") + 1, 0))
        assert app.prompt.value == "fade "

    drive(app, body)
    assert config.Settings().quick == config.QUICK


def test_the_colour_panel_has_the_presets_and_a_prefill() -> None:
    bridge = FakeBridge()
    app = program_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        chips = app.query_one(".enc-chips", ButtonStrip)
        assert plain(chips) == "██ ██ [set color…]"
        await pilot.click(chips, offset=(3, 0))
        assert [s.line for s in bridge.sent] == ["preset color 2"]
        await pilot.click(chips, offset=(7, 0))
        assert app.prompt.value == "set color "

    drive(app, body)


def test_programmer_contents_follow_the_programmer() -> None:
    bridge = FakeBridge()
    app = program_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, prog=programmer())
        await settle(pilot, app)
        table = app.query_one(ProgrammerTable)
        assert plain(table) == EMPTY
        page = app.query_one(ProgramPage)
        assert page.contents.border_title is not None
        assert str(page.contents.border_title) == "PROGRAMMER CONTENTS · 0 fixtures"
        bridge.events.append(
            ProgrammerChanged(heads(held(101, "intensity", 0.5), held(102, "pan", 5.0), version=2))
        )
        await settle(pilot, app)
        lines = plain(table).splitlines()
        assert [line.split()[0] for line in lines[1:]] == ["101", "102"]
        assert str(page.contents.border_title) == "PROGRAMMER CONTENTS · 2 fixtures"

    drive(app, body)


def test_at_99_columns_the_other_attributes_stay_in_their_column() -> None:
    """The table is laid out again when the screen narrows: no value starts a
    line under ``#`` (pending plan §7, 2026-11-12)."""
    bridge = FakeBridge()
    app = program_app(bridge)
    values = (held(101, "gobo1", "breakup"), held(101, "shutter", "strobe"))

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, prog=heads(*values))
        await settle(pilot, app)
        table = app.query_one(ProgrammerTable)
        assert plain(table).splitlines()[1].endswith("gobo1 breakup · shutter strobe")
        await pilot.resize_terminal(99, 60)
        await settle(pilot, app)
        room = table.size.width - OTHER_AT
        assert OTHER_MIN <= room < len("gobo1 breakup")
        rows = plain(table).splitlines()[1:]
        assert rows[0].startswith("101 ")
        assert all(row.startswith(" " * OTHER_AT) for row in rows[1:])
        assert [row.strip() for row in rows[1:]] == ["breakup", "shutter", "strobe"]
        assert rows[0].split()[-1] == "gobo1"
        assert table.region.height == len(rows) + 1

    drive(app, body)


def test_panels_go_one_under_the_other_below_100_columns() -> None:
    bridge = FakeBridge()
    app = program_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        page = app.query_one(ProgramPage)
        assert page.grid.styles.grid_size_columns == 3
        await pilot.resize_terminal(99, 40)
        await pilot.pause()
        assert page.grid.styles.grid_size_columns == 1

    drive(app, body)


# ---------------------------------------- option rows (pending plan Phase 36)

TUPPER = Path(__file__).resolve().parents[2] / "examples" / "tupperdmx" / "tupper-demo.show"


@pytest.fixture
def tupper() -> busk.OfflineShow:
    """The TupperDMX demo show, to select on (not saved)."""
    document, _ = busk.load_show(TUPPER)
    return busk.OfflineShow(document)


def selecting(
    show: busk.OfflineShow, line: str | None, values: tuple[HeldValue, ...] = (), version: int = 1
) -> ProgrammerModel:
    """The programmer after ``line`` (``None``: nothing selected), holding
    ``values``, with the options busk's completion offers the selection."""
    if line is not None:
        assert show.execute(line).ok
    selection = () if line is None else show.programmer.selection
    rig = attributes.taken(model_of(show.show))
    options = selection_options(show.expected, selection, rig)
    return programmer(selection=selection, options=options, values=values, version=version)


def option_rows(app: BuskApp) -> dict[str, OptionRow]:
    return {row.attribute: row for row in app.query(OptionRow)}


def shown_rows(app: BuskApp) -> list[str]:
    return [row.attribute for row in app.query(OptionRow) if row.display]


def chips_of(row: OptionRow) -> list[str]:
    """A row's chips, ``*`` before the lit one: ``["open", "*star"]``."""
    return [
        ("*" if str(button.label.spans[0].style) == LIT else "") + button.label.plain[1:-1]
        for button in row.chips.buttons
    ]


async def tap_label(pilot: Pilot[int], strip: ButtonStrip, label: str) -> None:
    """A click on the button of ``strip`` that reads ``label``."""
    await pilot.pause()
    strip.scroll_visible(animate=False)
    await pilot.pause()
    for y, line in enumerate(strip.lines(strip.size.width)):
        x = line.plain.find(label)
        if x >= 0:
            await pilot.click(strip, offset=(x + 1, y))
            return
    raise AssertionError(f"no button {label}")


def test_a_family_with_options_and_no_encoder_rows_has_a_panel() -> None:
    gobos = ProfileInfo("Gobos", frozenset({"intensity", "gobo1", "prism"}), ())
    show = rig(fixtures=(FixtureInfo(501, 1, "Gobo 501", "Gobos"),), profiles=(gobos,))
    assert [(family, rows, options) for family, rows, options in attributes.shown(show)] == [
        ("intensity", (encoder("intensity"),), ()),
        ("beam", (), ("gobo1", "prism")),
    ]


def test_option_rows_show_what_the_selection_offers(tupper: busk.OfflineShow) -> None:
    bridge = FakeBridge()
    app = program_app(bridge)
    show = model_of(tupper.show)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, show, prog=selecting(tupper, "sel group 4"))  # the heads
        await settle(pilot, app)
        beam = next(panel for panel in app.query(EncoderPanel) if panel.family == "beam")
        assert [type(child).__name__ for child in beam.children] == [
            "EncoderRow", "OptionRow", "OptionRow", "OptionRow",
        ]  # fmt: skip
        assert shown_rows(app) == ["gobo1", "prism", "shutter"]  # no effect on a head
        rows = option_rows(app)
        assert chips_of(rows["prism"]) == ["off", "prism3"]
        assert chips_of(rows["shutter"]) == ["closed", "open", "strobe", "pulse", "random"]
        shutter = next(panel for panel in app.query(EncoderPanel) if panel.family == "shutter")
        assert shutter.chips is None  # its row took [set shutter…]'s place
        assert "set shutter" not in plain(shutter.query_one(OptionRow).chips)
        await tap_label(pilot, rows["gobo1"].chips, "[star]")
        await tap_label(pilot, rows["shutter"].chips, "[strobe]")
        assert bridge.lines() == ["set gobo1 star", "set shutter strobe"]

        blinders = selecting(tupper, "sel group 2", version=2)
        bridge.events.append(ProgrammerChanged(blinders))
        await settle(pilot, app)
        assert shown_rows(app) == ["effect", "shutter"]
        assert chips_of(rows["effect"]) == ["off", "autoProgram", "soundActive"]
        assert chips_of(rows["shutter"]) == ["open", "strobe"]

    drive(app, body, size=(150, 60))


def test_the_lit_option_is_the_first_selected_elements(tupper: busk.OfflineShow) -> None:
    bridge = FakeBridge()
    app = program_app(bridge)
    show = model_of(tupper.show)

    def holding(*numbers: int, value: str) -> tuple[HeldValue, ...]:
        return tuple(HeldValue(number, 1, "gobo1", value, None) for number in numbers)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, show, prog=selecting(tupper, "sel group 4"))
        await settle(pilot, app)
        gobo = option_rows(app)["gobo1"]
        assert not [chip for chip in chips_of(gobo) if chip.startswith("*")]
        heads = selecting(tupper, "sel group 4", holding(501, 502, 503, 504, value="star"), 2)
        bridge.events.append(ProgrammerChanged(heads))
        await settle(pilot, app)
        assert [chip for chip in chips_of(gobo) if chip.startswith("*")] == ["*star"]
        spiral = selecting(tupper, "sel group 4", holding(502, value="spiral"), 3)
        bridge.events.append(ProgrammerChanged(spiral))  # 502's, not the first's
        await settle(pilot, app)
        assert not [chip for chip in chips_of(gobo) if chip.startswith("*")]

    drive(app, body, size=(150, 60))


def test_no_option_row_shows_with_nothing_selected(tupper: busk.OfflineShow) -> None:
    bridge = FakeBridge()
    app = program_app(bridge)
    show = model_of(tupper.show)

    def gobo_stops() -> list[str]:
        items = app.query_one(ProgramPage).items()
        return [item.label for item in items if "gobo1" in item.label]

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, show, prog=selecting(tupper, "sel group 4"))
        await settle(pilot, app)
        assert len(gobo_stops()) == 8
        bridge.events.append(ProgrammerChanged(selecting(tupper, None, version=2)))
        await settle(pilot, app)
        assert list(option_rows(app)) == ["gobo1", "prism", "effect", "shutter"]
        assert shown_rows(app) == []
        assert gobo_stops() == []
        bridge.events.append(ProgrammerChanged(selecting(tupper, "sel group 3", version=3)))
        await settle(pilot, app)
        assert shown_rows(app) == ["shutter"]  # the pars

    drive(app, body, size=(150, 60))


def test_options_in_a_panel_with_no_encoder_rows_always_show() -> None:
    gobos = ProfileInfo("Gobos", frozenset({"intensity", "gobo1"}), ())
    show = rig(fixtures=(FixtureInfo(501, 1, "Gobo 501", "Gobos"),), profiles=(gobos,))
    bridge = FakeBridge()
    app = program_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, show, prog=programmer())
        await settle(pilot, app)
        assert shown_rows(app) == ["gobo1"]
        gobo = option_rows(app)["gobo1"]
        assert plain(gobo.none) == "nothing selected"
        options = (("gobo1", ("open", "star")),)
        bridge.events.append(
            ProgrammerChanged(programmer(selection=((501, 1),), options=options, version=2))
        )
        await settle(pilot, app)
        assert chips_of(gobo) == ["open", "star"]

    drive(app, body)


def test_the_pane_cursor_stops_on_each_option_after_its_panels_rows(
    tupper: busk.OfflineShow,
) -> None:
    bridge = FakeBridge()
    app = program_app(bridge)
    show = model_of(tupper.show)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, show, prog=selecting(tupper, "sel group 4"))
        await settle(pilot, app)
        labels = [item.label for item in app.query_one(ProgramPage).items()]
        gobos = ("open", "breakup", "dots", "lines", "star", "spiral", "triangles", "closed")
        start = labels.index("set gobo1 open")
        assert labels[start : start + 10] == [
            *(f"set gobo1 {gobo}" for gobo in gobos), "set prism off", "set prism prism3",
        ]  # fmt: skip
        assert labels.index("zoom") < start < labels.index("strobeRate")
        assert labels.index("strobeRate") < labels.index("set shutter closed")
        await pilot.press("tab")
        for _ in range(start):
            await pilot.press("down")
        assert app.cursor.current is not None
        assert app.cursor.current.line == "set gobo1 open"
        await pilot.press("enter")
        assert bridge.lines() == ["set gobo1 open"]

    drive(app, body, size=(150, 60))


def test_f2_at_99_columns_with_a_spot_and_a_bar_selected(club_path: Path) -> None:
    """The club's spot offers a gobo and a shutter, its pixel bar neither: the
    rows show the spot's, under one another, inside the screen."""
    document, _ = busk.load_show(club_path)
    club = busk.OfflineShow(document)
    bridge = FakeBridge()
    app = program_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, model_of(club.show), prog=selecting(club, "sel fixture 101, fixture 301"))
        await settle(pilot, app)
        page = app.query_one(ProgramPage)
        assert page.grid.styles.grid_size_columns == 1
        assert shown_rows(app) == ["gobo1", "shutter"]
        rows = option_rows(app)
        assert [plain(row.chips) for row in rows.values()] == [
            "[open] [breakup]", "[closed] [open] [strobe]",
        ]  # fmt: skip
        for row in rows.values():
            assert row.region.right <= 99
            assert row.region.height == 1
            assert plain(row.name_text) == row.attribute
            assert row.name_text.region.width == 11  # under the encoders' names
        name = next(r for r in app.query(EncoderRow) if r.encoder.attribute == "zoom").name_text
        assert name.region.x == rows["gobo1"].name_text.region.x
        await tap_label(pilot, rows["gobo1"].chips, "[breakup]")
        assert bridge.lines() == ["set gobo1 breakup"]

    drive(app, body, size=(99, 60))
