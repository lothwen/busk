"""``frontend_probe:main``: a ``busk run --frontend`` for ``tests/test_frontend.py``.

It runs where a frontend runs, on the console process's main thread with the
attached show, and follows the plan in the JSON file ``$BUSK_TEST_FRONTEND``:

* ``crash``: raise on the first call, and run the plan on the next one (a
  file next to the plan says the first call was made);
* ``lines``: console lines to run, once the show's frame, output and effects
  have come (reading them asks for them);
* ``effectOf``: then wait until that playback's effect runs;
* ``records``: then wait until a ``busk.run`` record contains each text;
* ``routes``: then wait until the show has that many routes;
* ``sleep``: then sleep that long, after writing a ``.sleeping`` file next to
  the plan (a signal may end the sleep: the report is written all the same);
* ``report``: where to write what it saw, as JSON, before it returns.

Every wait gives up after :data:`WAIT_S`, and the report says what it was
waiting for (``timeout``).
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

WAIT_S = 15.0


class Records(logging.Handler):
    """Every record of the ``busk`` loggers, as a frontend's log pane gets them."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.seen: list[tuple[str, str, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.seen.append((record.name, record.levelname, record.getMessage()))


def main(show: Any) -> None:
    plan_path = Path(os.environ["BUSK_TEST_FRONTEND"])
    plan = json.loads(plan_path.read_text())
    calls = plan_path.with_suffix(".calls")
    count = int(calls.read_text()) + 1 if calls.exists() else 1
    calls.write_text(str(count))
    if plan.get("crash") and count == 1:
        raise RuntimeError("the probe crashes on its first call")
    records = Records()
    logger = logging.getLogger("busk")
    logger.addHandler(records)
    logger.setLevel(logging.INFO)
    report: dict[str, Any] = {"calls": count, "timeout": None}
    try:
        run(show, plan, records, report)
        if sleep := plan.get("sleep"):
            plan_path.with_suffix(".sleeping").touch()
            time.sleep(sleep)
    finally:
        logger.removeHandler(records)
        report["records"] = records.seen
        Path(plan["report"]).write_text(json.dumps(report))


def run(show: Any, plan: dict[str, Any], records: Records, report: dict[str, Any]) -> None:
    def wait(what: str, test: Callable[[], bool]) -> bool:
        deadline = time.monotonic() + WAIT_S
        while not test():
            if time.monotonic() > deadline:
                report["timeout"] = what
                return False
            time.sleep(0.02)
        return True

    if not wait("reads", lambda: None not in (show.frame, show.output, show.effects)):
        return
    report["replies"] = [[line, *_reply(show.execute(line))] for line in plan.get("lines", [])]
    effect_of = plan.get("effectOf")

    def running() -> bool:
        return any(effect.playback == effect_of for effect in show.effects.effects)

    if effect_of is not None and not wait(f"the effect of playback {effect_of}", running):
        return
    for text in plan.get("records", []):

        def said(text: str = text) -> bool:
            return any(name == "busk.run" and text in message for name, _, message in records.seen)

        if not wait(f"a busk.run record with {text!r}", said):
            return
    routes = plan.get("routes", 0)
    if not wait(f"{routes} routes", lambda: len(show.routes or ()) >= routes):
        return
    frame, output, effects = show.frame, show.output, show.effects
    report["frame"] = {
        "seq": frame.seq,
        "universes": {str(n): len(data) for n, data in frame.universes.items()},
    }
    report["output"] = {
        "seq": output.seq,
        "fixtures": [[f.number, f.element, f.intensity] for f in output.fixtures],
    }
    report["effects"] = [[e.playback, e.cue, e.id] for e in effects.effects]
    report["routes"] = [[r.id, r.state] for r in show.routes or ()]
    report["selection"] = [list(target) for target in show.programmer.selection]


def _reply(reply: Any) -> list[Any]:
    return [reply.text, reply.ok]
