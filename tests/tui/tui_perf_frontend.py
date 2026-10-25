"""``tui_perf_frontend:main``: a ``busk run --frontend`` for ``test_tui_perf.py``.

``$BUSK_TUI_PERF`` is a JSON object: ``mode`` ``"bare"`` (the frontend only
waits) or ``"tui"`` (the TUI, headless, on the run's show, typing a line now
and then, on the F-key ``page``), ``lines`` to run on the show first (in
both modes), ``seconds`` to run, and ``report``, where it writes the
engine's ticks and overruns over the run and the CPU time this process
used.
"""

from __future__ import annotations

import asyncio
import json
import os
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
    first = show.health
    cpu = time.process_time()
    if plan["mode"] == "tui":
        _run_tui(show, seconds, plan.get("page", 1))
    else:
        time.sleep(seconds)
    cpu = time.process_time() - cpu
    last = show.health
    Path(plan["report"]).write_text(
        json.dumps(
            {
                "ticks": last.ticks - first.ticks,
                "overruns": last.overruns - first.overruns,
                "cpu": cpu,
                "seconds": seconds,
            }
        )
    )


def _run_tui(show: Any, seconds: float, page: int) -> None:
    from busk_tui import config
    from busk_tui.bridge import Bridge
    from busk_tui.shell import BuskApp

    bridge = Bridge.attached(show)
    app = BuskApp(bridge, config.Settings(page=page))

    async def drive() -> None:
        async with app.run_test(size=(150, 48)) as pilot:
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                for key in ("g", "m", "space", "8", "0", "%", "enter"):
                    await pilot.press(key)
                await pilot.pause(0.5)

    try:
        asyncio.run(drive())
    finally:
        bridge.stop()
