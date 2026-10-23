"""Performance lines from one thread while another edits (GAP-12 of
``docs/dev/tui/engine-gaps.md``).

A frontend sends its controls' lines (``go``, ``fader`` …) from a thread of
their own, so they never wait for another thread's line. They still share the
interpreter with it. This benchmark measures what that costs on the §19-sized
rig of ``bench/edit_latency.py`` (400 fixtures over 64 universes, 100 cue
lists), with 20 playbacks up: one thread sends ``fader 1 …`` every 3 ms while
another runs 40 rounds of five lines (select a group, set a colour, record a
cue with merge, unpatch a fixture, rename it). It reports the time from when
each fader line was due to when ``execute`` returned, which includes waiting
for the interpreter, and the edit lines' own time.

Two layouts, each at Python's default switch interval and at the 0.1 ms one
of :data:`busk.cli.SWITCH_INTERVAL` (``tune_interpreter=True``):

* **LiveShow**: the engine is a thread of the bench, as in a library frontend;
* **busk run** (``--run``): the console of ``busk run``, where ``--frontend``
  runs: a session and its console on a ``RemoteBus`` to a real engine
  process (``bench/engines.py``). ``busk run``'s console process keeps
  Python's default.

Run it with ``uv run python bench/thread_latency.py [--run] [--tune]``.
"""

from __future__ import annotations

import argparse
import gc
import statistics
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "bench"))

from busk.cli import SWITCH_INTERVAL  # noqa: E402
from busk.compiler.compile import compile_show  # noqa: E402
from busk.console.console import Console, Reply  # noqa: E402
from busk.engine.clock import MonotonicClock  # noqa: E402
from busk.process.report import warn  # noqa: E402
from busk.runner import LiveShow  # noqa: E402
from busk.session.library import ProfileLibrary  # noqa: E402
from busk.session.session import Session  # noqa: E402
from edit_latency import reference_show  # noqa: E402
from engines import make_engine  # noqa: E402

PERIOD = 0.003
"""Seconds between two fader lines."""

ROUNDS = 40


def measure(execute: Callable[[str], Reply]) -> str:
    """Fader lines on a thread of their own while this thread edits."""
    for number in range(1, 21):
        assert execute(f"fader {number} 100%").ok
    stop = threading.Event()
    late: list[float] = []

    def faders() -> None:
        start = time.perf_counter()
        k = 0
        while not stop.is_set():
            due = start + k * PERIOD
            while time.perf_counter() < due - 0.0005:
                time.sleep(0.0002)
            while time.perf_counter() < due:
                pass
            reply = execute(f"fader 1 {k % 10 * 10}%")
            late.append(time.perf_counter() - due)
            assert reply.ok, reply
            k += 1

    thread = threading.Thread(target=faders, daemon=True)
    thread.start()
    time.sleep(0.3)
    first = len(late)
    edits: list[float] = []
    for k in range(ROUNDS):
        for line in (
            f"sel group {k % 40 + 1}",
            f"set color {k % 10 / 10} 0.5 1",
            f"record cue {k % 100 + 1}/1 merge",
            f"fixture {1000 + k} patch none",
            f'fixture {1000 + k} name "edited {k}"',
        ):
            started = time.perf_counter()
            reply = execute(line)
            edits.append(time.perf_counter() - started)
            assert reply.ok, (line, reply)
        time.sleep(0.005)  # an operator does not type at 1 kHz
    stop.set()
    thread.join()
    lines, edited = sorted(late[first:]), sorted(edits)
    return (
        f"{len(lines)} fader lines done after they were due: p50 "
        f"{statistics.median(lines) * 1000:.2f} ms, p99 {lines[len(lines) * 99 // 100] * 1000:.1f}"
        f" ms, max {lines[-1] * 1000:.1f} ms; edit lines p50 "
        f"{statistics.median(edited) * 1000:.1f} ms, max {edited[-1] * 1000:.0f} ms"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Performance lines while another thread edits.")
    parser.add_argument("--run", action="store_true",
                        help="busk run's console, the engine in an engine process")  # fmt: skip
    parser.add_argument("--tune", action="store_true",
                        help="the 0.1 ms switch interval (tune_interpreter=True)")  # fmt: skip
    args = parser.parse_args()
    show = reference_show()
    gc.collect()
    gc.freeze()  # as busk run does after loading
    if not args.run:
        with LiveShow(show, output=False, tune_interpreter=args.tune) as live:
            interval = sys.getswitchinterval()
            result = measure(live.execute)
    else:
        if args.tune:
            sys.setswitchinterval(SWITCH_INTERVAL)
        compiled = compile_show(show)
        engine = make_engine(compiled, MonotonicClock(), processes=True)
        session = Session(
            show, engine.bus, compiled=compiled, report=warn, engine_state=lambda: engine.snapshot
        )
        engine.start()
        interval = sys.getswitchinterval()
        try:
            result = measure(Console(session, ProfileLibrary()).execute)
        finally:
            engine.stop()
    layout = "busk run's console" if args.run else "LiveShow"
    print(f"{layout}, switch interval {interval * 1000:g} ms: {result}")


if __name__ == "__main__":
    main()
