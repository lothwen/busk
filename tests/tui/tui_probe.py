"""``tui_probe:main``: a ``busk run --frontend`` for ``test_tui_host.py``.

It runs where the TUI's frontend runs, on busk run's console process with the
run's show, and hands that show to the real bridge, as
``busk_tui.app:frontend`` does, without the app: it waits for the engine,
sends ``gm 50%`` from the controls worker, waits for the ``LiveChanged``
with the grand master at 50 %, stops the bridge and checks that the show
still runs. What it saw goes to the JSON file ``$BUSK_TUI_TEST_REPORT``.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from busk_tui.bridge import Bridge
from busk_tui.model import BridgeEvent, EngineRunning, LiveChanged

WAIT_S = 15.0


def main(show: Any) -> None:
    report: dict[str, Any] = {"timeout": None}
    bridge = Bridge.attached(show)
    seen: list[BridgeEvent] = []

    def until(what: str, test: Any) -> bool:
        deadline = time.monotonic() + WAIT_S
        while time.monotonic() < deadline:
            seen.extend(bridge.drain())
            if any(test(event) for event in seen):
                return True
            time.sleep(0.02)
        report["timeout"] = what
        return False

    try:
        bridge.start()
        if until("EngineRunning", lambda e: isinstance(e, EngineRunning)):
            started = time.monotonic()
            bridge.send("gm 50%", "ui", performance=True)
            if until("gm 50%", lambda e: isinstance(e, LiveChanged) and e.state.gm == 0.5):
                report["seconds"] = time.monotonic() - started
            report["help"] = len(bridge.help_lines)
    finally:
        bridge.stop()
        report["health"] = show.health.state  # the bridge left the show running
        Path(os.environ["BUSK_TUI_TEST_REPORT"]).write_text(json.dumps(report))
