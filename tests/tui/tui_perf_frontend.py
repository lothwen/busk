"""``tui_perf_frontend:main``: a ``busk run --frontend`` for ``test_tui_perf.py``.

``$BUSK_TUI_PERF`` is a JSON object: ``mode`` ``"bare"`` (the frontend only
waits) or ``"tui"`` (the TUI, headless, on the run's show, typing a line now
and then, on the F-key ``page``, F1 in ``layout``, F6 with the PRESET panel
open on a new preset of the pool ``edit``), ``lines`` to run on the show
first (in both modes), ``osc``, a port on localhost to send a fader sweep
to while it runs (100 messages a second, ``/fader/1`` and ``/fader/2`` by
turns each half second: F9's MONITOR), ``seconds`` to run, and ``report``, where it writes
the engine's ticks and overruns over the run, and the CPU time this process
used and the wall time over the steady part of it: the TUI's imports and its
start-up are left out, and ``seconds`` is how long that part really ran.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any


def main(show: Any) -> None:
    plan = json.loads(os.environ["BUSK_TUI_PERF"])
    seconds: float = plan["seconds"]
    deadline = time.monotonic() + 15.0
    while (show.health is None or show.health.ticks == 0) and time.monotonic() < deadline:
        time.sleep(0.05)  # the engine process sends its counts once a second
    for line in plan.get("lines", ()):
        assert show.execute(line).ok, line
    stop = threading.Event()
    if (port := plan.get("osc")) is not None:
        threading.Thread(target=_sweep, args=(port, stop), daemon=True).start()
    first = show.health
    if plan["mode"] == "tui":
        cpu, wall = _run_tui(
            show, seconds, plan.get("page", 1), plan.get("layout", "B"), plan.get("edit")
        )
    else:
        cpu, wall = time.process_time(), time.monotonic()
        time.sleep(seconds)
        cpu, wall = time.process_time() - cpu, time.monotonic() - wall
    stop.set()
    last = show.health
    Path(plan["report"]).write_text(
        json.dumps(
            {
                "ticks": last.ticks - first.ticks,
                "overruns": last.overruns - first.overruns,
                "cpu": cpu,
                "seconds": wall,
            }
        )
    )


def _sweep(port: int, stop: threading.Event) -> None:
    """A fader sweep to an OSC surface on localhost (see the module docs)."""
    from busk.io.osc import encode

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        count = 0
        while not stop.wait(0.01):
            fader = 1 + count // 50 % 2
            client.sendto(encode(f"/fader/{fader}", count % 50 / 49), ("127.0.0.1", port))
            count += 1


def _run_tui(
    show: Any, seconds: float, page: int, layout: str, edit: str | None
) -> tuple[float, float]:
    """The CPU and wall time of the steady loop, after the start-up."""
    from busk_tui import config
    from busk_tui.bridge import Bridge
    from busk_tui.pages.presets import PresetsPage
    from busk_tui.shell import BuskApp

    bridge = Bridge.attached(show)
    app = BuskApp(bridge, config.Settings(page=page, layout=layout))  # type: ignore[arg-type]
    steady: list[float] = []

    async def drive() -> None:
        async with app.run_test(size=(150, 48)) as pilot:
            if edit is not None:
                presets = app.query_one(PresetsPage)
                while not any(t.pool == edit for t in presets.tiles):
                    await pilot.pause(0.05)
                tiles = presets.tiles
                presets.choose(next(t for t in tiles if t.pool == edit and t.preset is None))
            cpu, start = time.process_time(), time.monotonic()
            while time.monotonic() < start + seconds:
                for key in ("g", "m", "space", "8", "0", "%", "enter"):
                    await pilot.press(key)
                await pilot.pause(0.5)
            steady.extend((time.process_time() - cpu, time.monotonic() - start))

    try:
        asyncio.run(drive())
    finally:
        bridge.stop()
    cpu, wall = steady
    return cpu, wall
