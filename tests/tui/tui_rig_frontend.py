"""``tui_rig_frontend:main``: a ``busk run --frontend`` for ``test_tui_host.py``.

The real app, headless, on busk run's show: a par at full in the programmer,
moved by F3's PATCH and then by a place on F8's map, then a route added, switched
off and on, and deleted from F8's strip. What the frames hold after each patch
and the route's state after each step go to the JSON file
``$BUSK_TUI_TEST_REPORT``.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from textual.pilot import Pilot

from busk_tui import config
from busk_tui.bridge import Bridge
from busk_tui.pages.fixtures import FixturesPage
from busk_tui.pages.patch import PatchPage
from busk_tui.shell import BuskApp
from busk_tui.widgets.controls import ButtonStrip
from busk_tui.widgets.dialogs import ConfirmDialog, TextDialog
from busk_tui.widgets.dmxmap import DmxMap
from busk_tui.widgets.route_dialog import RouteDialog

WAIT_S = 15.0


def main(show: Any) -> None:
    report: dict[str, Any] = {"timeout": None, "frames": [], "routes": []}
    bridge = Bridge.attached(show)
    app = BuskApp(bridge, config.Settings(page=3))

    def lit() -> list[int]:
        """The channels of universe 1 the frame has up."""
        frame = show.frame
        data = b"" if frame is None else frame.universes.get(1, b"")
        return [channel for channel, value in enumerate(data, 1) if value]

    async def until(pilot: Pilot[int], what: str, test: Callable[[], bool]) -> None:
        deadline = time.monotonic() + WAIT_S
        while not test():
            if time.monotonic() > deadline:
                report["timeout"] = what
                raise TimeoutError(what)
            await pilot.pause(0.05)

    async def tap(pilot: Pilot[int], strip: ButtonStrip, label: str) -> None:
        await pilot.pause()
        x = strip.lines(strip.size.width)[0].plain.find(f"[{label}]")
        await pilot.click(strip, offset=(x + 1, 0))

    def state() -> str | None:
        return app.view.routes[0].state if app.view.routes else None

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, "the show", lambda: app.view.show is not None)
        for line in ("sel fixture 1", "set intensity 100%", "set color 1 1 1"):
            assert show.execute(line).ok, line
        await until(pilot, "the par up at 1.1", lambda: lit() == [1, 2, 3])
        report["frames"].append(lit())

        page = app.query_one(FixturesPage)
        await pilot.click(page.edit)
        await until(pilot, "the rig's table", lambda: len(page.rig.rows) == 1)
        await pilot.click(page.rig, offset=(10, 1))
        await until(pilot, "the choice", lambda: page.panel.fixture() is not None)
        await pilot.pause()
        await pilot.click(page.panel.patching.ask)
        await until(pilot, "the dialog", lambda: isinstance(app.screen, TextDialog))
        await pilot.press(*"101", "enter")
        await until(pilot, "the address", lambda: page.panel.patching.at == (1, 101))
        await pilot.pause()
        await pilot.click(page.panel.send_patch)
        await until(pilot, "the par at 1.101", lambda: lit() == [101, 102, 103])
        report["frames"].append(lit())

        await pilot.press("f8")
        await until(pilot, "F8", lambda: app.page == 8)
        patch = app.query_one(PatchPage)
        await pilot.pause()
        await pilot.click(app.query_one(DmxMap), offset=(5 + 8, 3))  # 1.201
        await until(pilot, "the place", lambda: patch.place == (1, 201))
        await pilot.pause()
        await tap(pilot, patch.place_strip, "patch 1 here")
        await until(pilot, "the par at 1.201", lambda: lit() == [201, 202, 203])
        report["frames"].append(lit())

        await tap(pilot, patch.route_edits, "+ route…")
        await until(pilot, "the form", lambda: isinstance(app.screen, RouteDialog))
        await pilot.press("tab", "tab", "right", "tab", *"127.0.0.1", "enter")
        await until(pilot, "the route open", lambda: state() == "ok")
        report["routes"].append(state())
        await pilot.pause()
        await pilot.click(patch.routes, offset=(10, 1))
        await until(pilot, "the choice", lambda: patch.chosen_route() is not None)
        await tap(pilot, patch.route_edits, "off")
        await until(pilot, "the question", lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.press("y")
        await until(pilot, "the route off", lambda: state() == "disabled")
        report["routes"].append(state())
        await tap(pilot, patch.route_edits, "on")
        await until(pilot, "the route on", lambda: state() == "ok")
        report["routes"].append(state())
        await tap(pilot, patch.route_edits, "delete")
        await until(pilot, "the question", lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.press("y")
        await until(pilot, "the route gone", lambda: not app.view.routes)
        report["routes"].append(state())

    async def drive() -> None:
        async with app.run_test(size=(150, 48)) as pilot:
            await body(pilot)

    try:
        asyncio.run(drive())
    finally:
        bridge.stop()
        Path(os.environ["BUSK_TUI_TEST_REPORT"]).write_text(json.dumps(report))
