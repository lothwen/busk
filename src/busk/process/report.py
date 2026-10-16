"""What ``busk run`` prints about the output and the engine (Phase 2–7).

Used by whichever process runs the output scheduler: the root, or the one
process of ``busk run --threads``.

* :class:`RouteReporter` prints, on each :meth:`~RouteReporter.poll`, the
  scheduler's notices (routes opened or closed by live edits, discovery,
  engine stalls) and each route whose status changed (``sACN r1: send
  failed: …``, then ``sACN r1: sending again``);
* :func:`print_statistics` prints the final ``engine:`` line and each
  route's counts.
"""

from __future__ import annotations

import sys

from busk.engine.loop import EngineStats
from busk.output.scheduler import OutputScheduler


class RouteReporter:
    """Prints what the output scheduler reports (see the module docs)."""

    def __init__(self, scheduler: OutputScheduler) -> None:
        self._scheduler = scheduler
        self._reported: dict[str, tuple[bool, str]] = {}  # route id → (ok, detail)

    def poll(self) -> None:
        notices = self._scheduler.notices
        while not notices.empty():
            notice = notices.get()
            print(notice.text, file=sys.stderr if notice.failed else sys.stdout, flush=True)
        for route in self._scheduler.routes:
            status = route.driver.status()
            state = (status.ok, status.detail)
            if state == self._reported.get(route.id, (True, "")):
                continue
            self._reported[route.id] = state
            change = "sending again" if status.ok else f"send failed: {status.detail}"
            print(f"{route.label}: {change}", file=sys.stderr, flush=True)


def print_statistics(
    stats: EngineStats | None, engine_hz: float, scheduler: OutputScheduler, *, restarts: int = 0
) -> None:
    """The ``engine:`` line (when there are statistics; ``, N restarts`` when
    the watchdog restarted it), then one line per route opened during the run."""
    if stats is not None:
        line = (
            f"engine: {stats.ticks} ticks @ {engine_hz:g} Hz, "
            f"{stats.overruns} overruns, "
            f"max tick {stats.maxTickSeconds * 1000:.3f} ms, "
            f"{plural(stats.commandsApplied, 'command')}, "
            f"{plural(stats.commandErrors, 'command error')}"
        )
        if restarts:
            line += f", {plural(restarts, 'restart')}"
        print(line)
    for route in scheduler.opened:
        status = route.driver.status()
        counts = f"{plural(status.packets, 'packet')}, {plural(status.errors, 'error')}"
        line = f"{route.label}: {counts}"
        if status.dropped:
            line += f", {plural(status.dropped, 'frame')} dropped"
        if route.faults:
            line += f", {plural(route.faults, 'fault')}"
        print(line)


def plural(count: int, word: str) -> str:
    """``1 packet``, ``2 packets``."""
    return f"{count} {word}{'' if count == 1 else 's'}"
