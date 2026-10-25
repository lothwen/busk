"""The shared widgets (spec §4.3, plan step 0.6): buttons, chips, the bar
with its click, drag and wheel, big digits, beat dots and swatches."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from textual.app import App, ComposeResult
from textual.pilot import Pilot

from busk_tui import colors
from busk_tui.commands import Line, percent
from busk_tui.widgets.bars import HBar, bar_text
from busk_tui.widgets.controls import (
    ButtonStrip,
    Chip,
    CommandButton,
    RunLine,
    StripButton,
    button_label,
    chip,
)
from busk_tui.widgets.digits import BeatDots, BigDigits, beat_dots, big
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


def bench(app: Bench, body: Callable[[Pilot[None]], Awaitable[None]]) -> None:
    async def main() -> None:
        async with app.run_test(size=(40, 10)) as pilot:
            await pilot.pause()
            await body(pilot)

    asyncio.run(main())


def gm(level: float) -> Line:
    return Line(f"gm {percent(level)}", performance=True)


def test_bars_fill_in_eighths_of_a_cell() -> None:
    assert bar_text(0.5, 10, colors.FG).plain == "█████░░░░░"
    assert bar_text(0.55, 10, colors.FG).plain == "█████▌░░░░"
    assert bar_text(0.0, 4, colors.FG).plain == "░░░░"
    assert bar_text(1.0, 4, colors.FG).plain == "████"
    assert bar_text(1.7, 4, colors.FG).plain == "████"
    text = bar_text(0.5, 4, colors.GREEN)
    assert colors.GREEN in str(text.spans[0].style)
    assert colors.TRACK in str(text.spans[-1].style)


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
