"""The help overlay (spec §8.10, plan step 0.5)."""

from __future__ import annotations

from textual.pilot import Pilot
from tui_fakes import HELP, FakeBridge, drive, make_app, settle

from busk_tui.widgets.help import KEYS, HelpOverlay, key_grid
from busk_tui.widgets.prompt import Prompt


def test_it_holds_the_engines_help_then_the_keys() -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        overlay = app.query_one(HelpOverlay)
        assert not overlay.is_open
        await pilot.press("f10")
        assert overlay.is_open
        assert overlay.text == "\n".join(HELP)
        assert app.query_one("#upper").has_class("help-open")  # the pages are dimmed
        keys = key_grid().plain.splitlines()
        assert len(keys) == len(KEYS)
        assert keys[0].startswith("F1–F9")
        await pilot.press("escape")
        assert not overlay.is_open
        assert not app.query_one("#upper").has_class("help-open")

    drive(app, body)


def test_the_prompt_works_while_it_is_open() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await pilot.press("question_mark")
        assert app.query_one(HelpOverlay).is_open
        await pilot.press("g", "m", "space", "5", "0", "%")
        assert app.query_one(Prompt).value == "gm 50%"
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.lines() == ["gm 50%"]
        assert app.query_one(HelpOverlay).is_open
        await pilot.press("escape")  # Esc closes help first, then clears
        assert not app.query_one(HelpOverlay).is_open

    drive(app, body)


def test_a_click_outside_closes_it_and_inside_does_not() -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        overlay = app.query_one(HelpOverlay)
        await pilot.press("f10")
        await pilot.click(HelpOverlay, offset=(5, 3))
        assert overlay.is_open
        await pilot.click("#log", offset=(2, 3))
        assert not overlay.is_open

    drive(app, body)


def test_page_keys_scroll_it_while_it_is_open() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        overlay = app.query_one(HelpOverlay)
        overlay.open([f"    line {n}" for n in range(200)])
        await pilot.pause()
        assert overlay.scroll_y == 0
        await pilot.press("pagedown")
        await pilot.pause()
        assert overlay.scroll_y > 0
        await pilot.press("pageup")
        await pilot.pause()
        assert overlay.scroll_y == 0

    drive(app, body, size=(120, 30))


def test_before_the_engine_answers_it_says_so() -> None:
    class Silent(FakeBridge):
        @property
        def help_lines(self) -> tuple[str, ...]:
            return ()

    app = make_app(Silent())

    async def body(pilot: Pilot[int]) -> None:
        await pilot.press("f10")
        assert app.query_one(HelpOverlay).text == "(the engine has not answered help yet)"

    drive(app, body)
