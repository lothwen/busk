"""The shared widgets (spec §4.3, plan step 0.6): buttons, chips, the bar
with its click, drag and wheel, big digits, beat dots and swatches."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.pilot import Pilot

from busk_tui import colors
from busk_tui.commands import Line, percent
from busk_tui.widgets.bars import HBar, bar_text, signed_bar_text
from busk_tui.widgets.controls import (
    ButtonStrip,
    Chip,
    CommandButton,
    RunLine,
    StripButton,
    button_label,
    chip,
)
from busk_tui.widgets.dialogs import (
    ConfirmDialog,
    FormDialog,
    check_name,
    check_number,
    free_step,
    next_number,
    read_whole,
)
from busk_tui.widgets.digits import BeatDots, BigDigits, beat_dots, big
from busk_tui.widgets.legend import Legend
from busk_tui.widgets.quick import strip_stops
from busk_tui.widgets.swatch import Swatch, swatch_text


class Bench(App[None]):
    """One widget on a screen, and the lines it asked for."""

    def __init__(self, *widgets: object) -> None:
        super().__init__()
        self.widgets = widgets
        self.lines: list[tuple[str, str, str | None]] = []

    def compose(self) -> ComposeResult:
        yield from self.widgets  # type: ignore[misc]

    def on_run_line(self, message: RunLine) -> None:
        self.lines.append((message.line.text, message.origin, message.key))


def bench(
    app: Bench,
    body: Callable[[Pilot[None]], Awaitable[None]],
    size: tuple[int, int] = (40, 10),
) -> None:
    async def main() -> None:
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await body(pilot)

    asyncio.run(main())


def gm(level: float) -> Line:
    return Line(f"gm {percent(level)}", performance=True)


def form(app: Bench, closed: list[tuple[str, ...] | None]) -> FormDialog:
    """A two-field form on ``app``: ``first`` must be ``ok``."""

    def check(values: tuple[str, ...]) -> str | None:
        return None if values[0] == "ok" else f"not {values[0]}"

    dialog = FormDialog("FORM", (("first", "no"), ("second one", "b")), check, "a note")
    app.push_screen(dialog, closed.append)
    return dialog


def test_a_form_moves_with_tab_and_closes_with_its_values_on_enter() -> None:
    app = Bench()
    closed: list[tuple[str, ...] | None] = []

    async def body(pilot: Pilot[None]) -> None:
        dialog = form(app, closed)
        await pilot.pause()
        first, second = dialog.inputs
        assert first.has_focus
        assert (first.value, second.value) == ("no", "b")
        await pilot.press("tab")
        assert second.has_focus
        await pilot.press("c")  # a field's value starts selected: typing replaces it
        await pilot.press("shift+tab")
        assert first.has_focus
        first.value = "ok"
        await pilot.press("tab")
        await pilot.press("enter")  # from any field
        await pilot.pause()
        assert closed == [("ok", "c")]
        assert app.screen is not dialog

    bench(app, body)


def test_a_refused_value_stays_in_the_form_and_esc_cancels() -> None:
    app = Bench()
    closed: list[tuple[str, ...] | None] = []

    async def body(pilot: Pilot[None]) -> None:
        dialog = form(app, closed)
        await pilot.pause()
        await pilot.press("enter")
        assert app.screen is dialog
        assert str(dialog.error.render()) == "not no"
        assert closed == []
        await pilot.press("x")  # still typing
        await pilot.press("enter")
        assert str(dialog.error.render()) == "not x"
        await pilot.press("escape")
        await pilot.pause()
        assert closed == [None]
        assert app.screen is not dialog

    bench(app, body)


def test_a_forms_labels_line_up_and_its_note_shows() -> None:
    app = Bench()

    async def body(pilot: Pilot[None]) -> None:
        dialog = form(app, [])
        await pilot.pause()
        first, second = dialog.inputs
        assert first.region.x == second.region.x
        assert second.region.y == first.region.y + 1
        assert str(dialog.query(".note").first().render()) == "a note"

    bench(app, body, (80, 24))


def test_a_name_in_a_question_is_not_markup() -> None:
    """busk's question names the universe: ``[/]`` in a name is only words."""
    app = Bench()

    async def body(pilot: Pilot[None]) -> None:
        question = 'Delete universe 1 "x[/]y [red]z"?'
        await app.push_screen(ConfirmDialog(question, "delete universe 1 cascade"))
        await pilot.pause()
        assert str(app.screen.query_one(".question").render()) == question

    bench(app, body)


def test_a_long_question_wraps_in_its_box() -> None:
    """busk's question is what says what a delete takes: none of it is cut."""
    app = Bench()

    async def body(pilot: Pilot[None]) -> None:
        question = "Delete fixture 101? It leaves " + ", ".join(f"group {n}" for n in range(1, 30))
        await app.push_screen(ConfirmDialog(question, "delete fixture 101 cascade"))
        await pilot.pause()
        shown = app.screen.query_one(".question")
        box = app.screen.query_one(Vertical)
        assert shown.region.height > 1
        assert box.region.contains_region(shown.region)
        assert box.region.width <= 80

    bench(app, body, (100, 30))


def test_the_checks_of_names_and_numbers() -> None:
    assert check_name(True)("  ") == "a name cannot be empty"
    assert check_name(True)('Say "hi" \\') is None
    assert check_name(False)("") is None
    check = check_number({1, 2, 4}, 2)
    assert check("3") is None
    assert check(" 9 ") is None
    assert check("2") is None  # its own number
    assert check("4") == "4 is taken"
    for refused in ("0", "-1", "x", "", "1.5", "²", "7" * 301, "7" * 5000):
        assert check(refused) == "a whole number from 1"
    assert check_number({1}, None)("1") == "1 is taken"
    assert free_step(2, 1, {3, 4}) == 5
    assert free_step(2, -1, {1}) == 2
    assert next_number({1, 2, 7}) == 8
    assert next_number(()) == 1


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("0", 0),
        ("12", 12),
        ("\u0663", 3),
        ("7" * 300, int("7" * 300)),
        ("7" * 301, None),
        ("7" * 5000, None),  # past what int reads
        ("", None),
        ("-1", None),
        ("+1", None),
        ("1.5", None),
        (" 1", None),
        ("1_000", None),
        ("²", None),
    ],
    ids=lambda value: str(value)[:12],
)
def test_a_whole_number_as_typed(text: str, number: int | None) -> None:
    assert read_whole(text) == number


def test_a_note_in_a_strip_is_no_button() -> None:
    strip = ButtonStrip(
        [
            StripButton(Text("[a]"), Line("first")),
            StripButton(Text("U1 Stage"), Line(""), note=True),
            StripButton(Text("[b]"), Line("second")),
        ]
    )
    app = Bench(strip)

    async def body(pilot: Pilot[None]) -> None:
        assert strip.lines(40)[0].plain == "[a] U1 Stage [b]"
        await pilot.click(strip, offset=(6, 0))  # the words
        assert app.lines == []
        await pilot.click(strip, offset=(14, 0))
        assert [line for line, _, _ in app.lines] == ["second"]
        assert [stop.index for stop in strip_stops(strip)] == [0, 2]

    bench(app, body)


def test_bars_fill_in_eighths_of_a_cell() -> None:
    assert bar_text(0.5, 10, colors.FG).plain == "█████░░░░░"
    assert bar_text(0.55, 10, colors.FG).plain == "█████▌░░░░"
    assert bar_text(0.0, 4, colors.FG).plain == "░░░░"
    assert bar_text(1.0, 4, colors.FG).plain == "████"
    assert bar_text(1.7, 4, colors.FG).plain == "████"
    text = bar_text(0.5, 4, colors.GREEN)
    assert colors.GREEN in str(text.spans[0].style)
    assert colors.TRACK in str(text.spans[-1].style)


def test_a_signed_bar_fills_from_its_centre() -> None:
    assert signed_bar_text(0.5, 10, colors.FG).plain == "░░░░░│░░░░"  # 0: the centre marked
    assert signed_bar_text(0.8, 10, colors.FG).plain == "░░░░░███░░"
    assert signed_bar_text(0.2, 10, colors.FG).plain == "░░███░░░░░"
    assert signed_bar_text(0.0, 4, colors.FG).plain == "██░░"
    assert signed_bar_text(1.7, 4, colors.FG).plain == "░░██"
    assert signed_bar_text(0.5, 1, colors.FG).plain == "│"
    assert signed_bar_text(0.5, 0, colors.FG).plain == ""
    text = signed_bar_text(1.0, 4, colors.AMBER)
    assert colors.AMBER in str(text.spans[1].style)


def test_a_click_sets_the_level_and_logs_once() -> None:
    bar = HBar(command=gm, key="gm")
    app = Bench(bar)

    async def body(pilot: Pilot[None]) -> None:
        width = bar.size.width
        await pilot.click(HBar, offset=(width - 1, 0))
        assert bar.level == 1.0
        assert app.lines == [("gm 100%", "internal", "gm"), ("gm 100%", "ui", "gm")]
        app.lines.clear()
        await pilot.click(HBar, offset=(0, 0))
        assert app.lines[-1] == ("gm 0%", "ui", "gm")

    bench(app, body)


def test_a_drag_sends_each_move_unlogged_and_the_release_logged() -> None:
    bar = HBar(command=gm, key="gm")
    app = Bench(bar)

    async def body(pilot: Pilot[None]) -> None:
        width = bar.size.width
        await pilot.mouse_down(HBar, offset=(0, 0))
        assert bar.dragging
        bar.show_level(0.9)  # the engine's level does not fight the drag
        assert bar.level == 0.0
        for x in (10, 20, 30):
            await pilot.hover(HBar, offset=(x, 0))
        await pilot.mouse_up(HBar, offset=(width // 2, 0))
        assert not bar.dragging
        origins = [origin for _, origin, _ in app.lines]
        assert origins == ["internal"] * (len(origins) - 1) + ["ui"]
        assert len(origins) >= 4
        assert {key for _, _, key in app.lines} == {"gm"}
        assert app.lines[-1][0] == f"gm {percent((width // 2) / (width - 1))}"
        bar.show_level(0.25)
        assert bar.level == 0.25

    bench(app, body)


def test_the_wheel_steps_and_is_not_logged() -> None:
    bar = HBar(0.5, command=gm, key="gm", step=0.05)
    app = Bench(bar)

    async def body(pilot: Pilot[None]) -> None:
        await pilot.hover(HBar, offset=(3, 0))
        bar.post_message(_scroll(bar, up=True))
        await pilot.pause()
        assert bar.level == 0.55
        bar.post_message(_scroll(bar, up=False))
        bar.post_message(_scroll(bar, up=False))
        await pilot.pause()
        assert bar.level == 0.45
        assert [line for line, _, _ in app.lines] == ["gm 55%", "gm 50%", "gm 45%"]
        assert {origin for _, origin, _ in app.lines} == {"internal"}

    bench(app, body)


def _scroll(widget: HBar, *, up: bool) -> object:
    from textual import events

    kind = events.MouseScrollUp if up else events.MouseScrollDown
    return kind(widget, 3, 0, 0, 0, 0, False, False, False)


def test_a_bar_without_a_command_is_a_display() -> None:
    bar = HBar(0.3)
    app = Bench(bar)

    async def body(pilot: Pilot[None]) -> None:
        await pilot.click(HBar, offset=(5, 0))
        assert bar.level == 0.3
        assert app.lines == []

    bench(app, body)


def test_a_button_runs_its_line() -> None:
    button = CommandButton("TAP", Line("tap", performance=True), "tempo")
    app = Bench(button)

    async def body(pilot: Pilot[None]) -> None:
        assert str(button.render()) == "[TAP]"
        await pilot.click(CommandButton)
        assert app.lines == [("tap", "ui", None)]

    bench(app, body)


def test_an_inert_button_runs_nothing() -> None:
    button = CommandButton("+", Line("set intensity by 5%"), inert=True)
    app = Bench(button)

    async def body(pilot: Pilot[None]) -> None:
        await pilot.click(CommandButton)
        assert app.lines == []
        assert str(button.content.style) == colors.BORDER  # type: ignore[union-attr]
        button.change(inert=False)
        await pilot.click(CommandButton)
        assert app.lines == [("set intensity by 5%", "ui", None)]

    bench(app, body)


def test_a_change_of_look_alone_redraws_a_button() -> None:
    """Rich's ``Text`` equality ignores the style: a button that changes
    only its look (lit, inert, intent) must still be drawn again."""
    button = CommandButton("target", Line(""), inert=True)
    app = Bench(button)

    def drawn() -> str:
        return str(button.content.style)  # type: ignore[union-attr]

    async def body(pilot: Pilot[None]) -> None:
        assert drawn() == colors.BORDER
        button.change(inert=False)
        assert drawn() == colors.MID
        button.change(intent="record", reverse=True)
        assert drawn() == f"bold {colors.BG} on {colors.MAGENTA}"
        button.change(intent="neutral", reverse=False)
        assert drawn() == colors.MID

    bench(app, body)


def test_a_strip_wraps_between_buttons_never_inside_one() -> None:
    labels = ["set intensity spread 0 to 1", "highlight on", "blind on", "fade 0s…"]
    strip = ButtonStrip(
        [StripButton(button_label(label, colors.MID), Line(label)) for label in labels]
    )
    app = Bench(strip)

    async def body(pilot: Pilot[None]) -> None:  # 40 columns wide
        assert strip.size.height == 2
        assert str(strip.render()).splitlines() == [
            "[set intensity spread 0 to 1]",
            "[highlight on] [blind on] [fade 0s…]",
        ]
        assert strip.lines(20)[0].plain == "[set intensity spread 0 to 1]"  # too long: alone
        assert len(strip.lines(20)) == 4
        await pilot.click(ButtonStrip, offset=(16, 1))
        assert app.lines == [("blind on", "ui", None)]

    bench(app, body)


def test_chips_on_and_off() -> None:
    on = chip("BLIND", True, colors.MAGENTA)
    assert on.plain == " BLIND "
    assert f"on {colors.MAGENTA}" in str(on.style)
    off = chip("BLIND", False, colors.MAGENTA)
    assert str(off.style) == colors.BORDER
    widget = Chip("BLACKOUT", colors.RED)

    async def body(pilot: Pilot[None]) -> None:
        widget.show(True)
        assert widget.on

    bench(Bench(widget), body)


def test_big_digits() -> None:
    assert big("128.0") == (
        "▀█  ▀▀█ █▀█   █▀█",
        " █  █▀▀ █▀█   █ █",
        "▀▀▀ ▀▀▀ ▀▀▀ ▀ ▀▀▀",
    )
    assert big("100") == ("▀█  █▀█ █▀█", " █  █ █ █ █", "▀▀▀ ▀▀▀ ▀▀▀")
    widget = BigDigits("12", colors.AMBER)

    async def body(pilot: Pilot[None]) -> None:
        assert widget.region.height == 3
        widget.show("7", colors.RED)
        assert (widget.text, widget.color) == ("7", colors.RED)

    bench(Bench(widget), body)


def test_beat_dots_follow_the_beat() -> None:
    first = beat_dots(8.2)  # beat 8 is the first of its bar
    assert first.plain == "● ● ● ●"
    assert colors.MAGENTA in str(first.spans[0].style)
    third = beat_dots(10.9)
    assert colors.AMBER in str(third.spans[2].style)
    assert colors.TRACK in str(third.spans[0].style)
    assert all(colors.TRACK in str(span.style) for span in beat_dots(None).spans)
    dots = BeatDots()

    async def body(pilot: Pilot[None]) -> None:
        dots.show(3.5)
        assert dots.beats == 3.5

    bench(Bench(dots), body)


def test_swatches() -> None:
    assert swatch_text("#ff0000").plain == "███"
    assert str(swatch_text(None).style) == "color(236)"
    assert swatch_text("color(196)", 2).plain == "██"
    assert Swatch("color(196)", width=2).width == 2


def test_a_legend_wraps_between_keys_never_inside_one() -> None:
    legend = Legend([Text("■ programmer"), Text("■ playback"), Text("— unpatched")])
    assert [line.plain for line in legend.lines(30)] == ["■ programmer   ■ playback", "— unpatched"]
    assert [line.plain for line in legend.lines(80)] == ["■ programmer   ■ playback   — unpatched"]
