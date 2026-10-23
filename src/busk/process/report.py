"""What ``busk run`` prints about the output and the engine (Phase 2–7).

Used by whichever process runs the output scheduler: the root, or the one
process of ``busk run --threads``.

* :class:`RouteReporter` prints, on each :meth:`~RouteReporter.poll`, the
  scheduler's notices (routes opened or closed by live edits, discovery,
  engine stalls) and each route whose status changed (``sACN r1: send
  failed: …``, then ``sACN r1: sending again``);
* :func:`print_statistics` prints the final ``engine:`` line and each
  route's counts;
* :func:`say` and :func:`warn` are the reporters the CLI passes to the
  session, the surfaces, the feedback worker and the event log, which
  log by default (phase-8-plan §5.6): a line on stdout or stderr, at once.
  :class:`RouteReporter` and the root's news use them too.

**A frontend owns the terminal** (``busk run --frontend``, GAP-11 of
``docs/dev/tui/engine-gaps.md``): nothing may print over its screen. While
it runs, the console process hands what :func:`say` and :func:`warn` would
print to the ``busk.run`` logger instead (INFO, WARNING), and the root and
the engine send theirs to the console (``NEWS``), which does the same.
:func:`diverted` is how: each process diverts its lines while a frontend
may run, and prints those its target refuses (the root, while no console
takes them).
"""

from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import Callable, Iterator

from busk.engine.loop import EngineStats
from busk.output.scheduler import OutputScheduler

_log = logging.getLogger("busk.run")

type Divert = Callable[[bool, str], bool]
"""Takes ``(failed, text)``: a line :func:`warn` (``failed``) or :func:`say`
would print; returns whether it took the line (``False``: print it)."""

_divert: Divert | None = None


class RouteReporter:
    """Prints what the output scheduler reports (see the module docs)."""

    def __init__(self, scheduler: OutputScheduler) -> None:
        self._scheduler = scheduler
        self._reported: dict[str, tuple[bool, str]] = {}  # route id → (ok, detail)

    def poll(self) -> None:
        notices = self._scheduler.notices
        while not notices.empty():
            notice = notices.get()
            (warn if notice.failed else say)(notice.text)
        for route in self._scheduler.routes:
            status = route.driver.status()
            state = (status.ok, status.detail)
            if state == self._reported.get(route.id, (True, "")):
                continue
            self._reported[route.id] = state
            change = "sending again" if status.ok else f"send failed: {status.detail}"
            warn(f"{route.label}: {change}")


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


def say(text: str) -> None:
    """Print ``text`` on stdout at once (the CLI's INFO lines), unless it is
    diverted (:func:`diverted`)."""
    divert = _divert
    if divert is None or not divert(False, text):
        print(text, flush=True)


def warn(text: str) -> None:
    """Print ``text`` on stderr at once (the CLI's warnings), unless it is
    diverted (:func:`diverted`)."""
    divert = _divert
    if divert is None or not divert(True, text):
        print(text, file=sys.stderr, flush=True)


@contextlib.contextmanager
def diverted(to: Divert) -> Iterator[None]:
    """While the block runs, :func:`say` and :func:`warn` (from any thread)
    hand each line to ``to`` first, and print only those it does not take."""
    global _divert
    previous, _divert = _divert, to
    try:
        yield
    finally:
        _divert = previous


def logged(failed: bool, text: str) -> bool:
    """A :data:`Divert` that logs every line on ``busk.run``: a warning, or
    news at INFO (the console process, while its frontend runs)."""
    (_log.warning if failed else _log.info)(text)
    return True


def plural(count: int, word: str) -> str:
    """``1 packet``, ``2 packets``."""
    return f"{count} {word}{'' if count == 1 else 's'}"
