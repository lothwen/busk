"""The TUI's cost to the engine (plan §4.6, risk R1): opt-in, ``-m perf -s``.

* ``--standalone``: the engine's frame rate (``frame.seq`` over wall time)
  with the TUI running headless, typing a line now and then, against a bare
  ``LiveShow`` on the same show.
* Under ``busk run``: the engine process's overruns, and the CPU time of the
  console process, with the TUI as the frontend against a frontend that only
  waits.

The TUI runs on F1, which reads the running effects (Phase 1), on F2,
which reads the output (Phase 2), and on F4 and F5 (Phase 3: F4 redraws
with the snapshot, F5 reads the effects), besides the frame, the prompt and
the reader at 20 Hz; under ``busk run`` F2 also with the selected heads
moving, so its encoders redraw with the output, and F4 and F5 with P11's
Circle running, so F5's waves move, and F3 (Phase 4: every fixture's
output) with it, so the heads' cells change, and F1's layouts A and C
(Phase 5: the output in OUTPUT and on the stage) with it too. The gates
are those of the plan's Phase 0 Done note.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest
from textual.pilot import Pilot

import busk
from busk_tui import config
from busk_tui.bridge import Bridge
from busk_tui.shell import BuskApp
from process_harness import BuskRun

pytestmark = pytest.mark.perf

HERE = Path(__file__).parent
SECONDS = 8.0

MIN_RATE = 0.97
"""Standalone: the engine's frame rate with the TUI, at least this share of
its rate without."""

MAX_OVERRUNS = 0.002
"""Under busk run: the engine's overruns with the TUI, at most this share of
its ticks."""

MAX_CPU = 0.25
"""Under busk run: the console process's CPU with the TUI, at most this many
cores more than with a frontend that only waits."""


def rate(show: Any, seconds: float) -> float:
    """The engine's frames per second over ``seconds``, from now."""
    while show.frame is None:
        time.sleep(0.01)
    first, started = show.frame.seq, time.monotonic()
    time.sleep(seconds)
    return (show.frame.seq - first) / (time.monotonic() - started)


@pytest.mark.parametrize(
    ("page", "layout"), [(1, "B"), (1, "A"), (1, "C"), (2, "B"), (3, "B"), (5, "B")]
)
def test_standalone_keeps_the_engines_rate(
    club_path: Path, tmp_path: Path, page: int, layout: config.Layout
) -> None:
    document, _ = busk.load_show(club_path)
    with busk.LiveShow(document, output=False, tune_interpreter=True) as bare:
        without = rate(bare, SECONDS)
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(page=page, layout=layout), standalone=True)
    measured: list[float] = []

    async def main() -> None:
        async with app.run_test(size=(150, 48)) as pilot:
            while not bridge.help_lines:
                await pilot.pause(0.05)
            show = bridge._show
            assert show is not None
            while show.frame is None:
                await pilot.pause(0.01)
            first, started = show.frame.seq, time.monotonic()
            while time.monotonic() - started < SECONDS:
                await type_a_line(pilot)
            measured.append((show.frame.seq - first) / (time.monotonic() - started))

    try:
        asyncio.run(main())
    finally:
        bridge.stop()
    (with_tui,) = measured
    where = f"F{page}" + (f" {layout}" if page == 1 else "")
    print(f"\nstandalone: {without:.1f} frames/s bare, {with_tui:.1f} with the TUI on {where}")
    assert with_tui >= MIN_RATE * without


async def type_a_line(pilot: Pilot[int]) -> None:
    for key in ("g", "m", "space", "8", "0", "%", "enter"):
        await pilot.press(key)
    await pilot.pause(0.5)


MOVING = ("sel group 1", "go 11", "fader 11 100%")
"""The heads selected and moving (P11's Circle): F2's encoders redraw as
the output changes."""


def run_frontend(
    mode: str,
    show: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    page: int = 1,
    lines: tuple[str, ...] = (),
    layout: str = "B",
) -> Any:
    name = f"{mode}-{page}{layout}-{len(lines)}"
    report = tmp_path / f"{name}.json"
    plan = {"mode": mode, "seconds": SECONDS, "report": str(report), "page": page,
            "layout": layout, "lines": lines}  # fmt: skip
    monkeypatch.setenv("BUSK_TUI_PERF", json.dumps(plan))
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(HERE), os.environ.get("PYTHONPATH", "")]))
    options = (
        "--frontend",
        "tui_perf_frontend:main",
        "--state-dir",
        str(tmp_path / name),
    )
    with BuskRun(show, *options, "--no-log") as run:
        assert run.wait(timeout=SECONDS + 60) == 0, run.err
    return json.loads(report.read_text())


def test_under_busk_run_the_engine_runs_on_time(
    club_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document, _ = busk.load_show(club_path)
    document["output"]["routes"] = []  # no packets on the network
    document["surfaces"] = []
    document["bindings"] = []
    show = tmp_path / "club.show"
    busk.save_show(document, show, backups=False)
    idle = run_frontend("bare", show, tmp_path, monkeypatch)
    moving = run_frontend("bare", show, tmp_path, monkeypatch, lines=MOVING)
    runs = ((1, "B", (), idle), (1, "A", MOVING, moving), (1, "C", MOVING, moving),
            (2, "B", (), idle), (2, "B", MOVING, moving), (3, "B", MOVING, moving),
            (4, "B", MOVING, moving), (5, "B", MOVING, moving))  # fmt: skip
    for page, layout, lines, bare in runs:
        tui = run_frontend("tui", show, tmp_path, monkeypatch, page, lines, layout)
        cores = (tui["cpu"] - bare["cpu"]) / SECONDS
        what = f"F{page}" + (f" {layout}" if page == 1 else "")
        what += ", P11's Circle running" if lines else ""
        print(
            f"\nbusk run, {what}: overruns {bare['overruns']}/{bare['ticks']} bare, "
            f"{tui['overruns']}/{tui['ticks']} with the TUI; "
            f"console CPU {bare['cpu'] / SECONDS:.3f} core bare, {tui['cpu'] / SECONDS:.3f} with "
            f"the TUI (+{cores:.3f})"
        )
        assert tui["ticks"] > 0
        assert tui["overruns"] <= MAX_OVERRUNS * tui["ticks"]
        assert cores <= MAX_CPU
