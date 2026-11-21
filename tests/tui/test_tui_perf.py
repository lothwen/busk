"""The TUI's cost to the engine (plan §4.6, risk R1): opt-in, ``-m perf -s``.

* ``--standalone``: the engine's frame rate (``frame.seq`` over wall time)
  with the TUI running headless, typing a line now and then, against a bare
  ``LiveShow`` on the same show.
* Under ``busk run``: the engine process's overruns, and the CPU time of the
  console process, with the TUI as the frontend against a frontend that only
  waits: the cores each uses over its steady part, past the TUI's start-up,
  each over the time it really ran.

The TUI runs on F1, which reads the running effects (Phase 1), on F2,
which reads the output (Phase 2), and on F4 and F5 (Phase 3: F4 redraws
with the snapshot, F5 reads the effects), besides the frame, the prompt and
the reader at 20 Hz; under ``busk run`` F2 also with the selected heads
moving, so its encoders redraw with the output, and F4 and F5 with P11's
Circle running, so F5's waves move, and F3 (Phase 4: every fixture's
output) with it, so the heads' cells change, and F1's layouts A and C
(Phase 5: the output in OUTPUT and on the stage) with it too, and F6
editing a new position preset (``docs/plans/tui-presets-plan.md`` step 3:
the PRESET panel's pan and tilt rows show the output), and F8 with one head
selected (``docs/plans/tui-pending-plan.md`` Phase 34: the DMX frame at 10 Hz,
the CHANNELS panel lists the head's channels as they move), and F9 with a
fader sweep coming in on an OSC surface (that plan's Phase 37: the inputs at
10 Hz, MONITOR's line moves, BINDINGS' ``in`` with it), against a frontend
that only waits while the same sweep comes in; and while Import script… runs
``examples/festival.busk`` into a new show (``docs/plans/file-menu-plan.md``
Phase 7: each line in the log, the bar in the hint row, the reader with a show
that changes at every line), against a frontend that runs the same script.
The gates are those of the plan's Phase 0 Done note.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
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
ROOT = HERE.parents[1]
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

MAX_IMPORT = 2.5
"""Under busk run: a script imported through the TUI takes at most this many
times as long as busk's ``run_script`` alone. The script holds the GIL for
most of it, so the TUI's work comes out of the script's time: 2.9 times
before the reader looked less often and the log was written less often
while a script runs (file-menu plan Phase 7), 1.75 after."""


def rate(show: Any, seconds: float) -> float:
    """The engine's frames per second over ``seconds``, from now."""
    while show.frame is None:
        time.sleep(0.01)
    first, started = show.frame.seq, time.monotonic()
    time.sleep(seconds)
    return (show.frame.seq - first) / (time.monotonic() - started)


@pytest.mark.parametrize(
    ("page", "layout"), [(1, "B"), (1, "A"), (1, "C"), (2, "B"), (3, "B"), (5, "B"), (8, "B")]
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

ONE_MOVING = ("sel fixture 101", *MOVING[1:])
"""One head selected, both moving: F8's CHANNELS lists 101's channels as
they change. A frontend that only waits does the same with :data:`MOVING`."""


def run_frontend(
    mode: str,
    show: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    page: int = 1,
    lines: tuple[str, ...] = (),
    layout: str = "B",
    edit: str | None = None,
    osc: int | None = None,
    script: Path | None = None,
) -> Any:
    name = f"{mode}-{page}{layout}-{len(lines)}{edit or ''}{'' if osc is None else '-osc'}"
    name += "" if script is None else "-script"
    report = tmp_path / f"{name}.json"
    plan = {"mode": mode, "seconds": SECONDS, "report": str(report), "page": page,
            "layout": layout, "lines": lines, "edit": edit, "osc": osc,
            "script": None if script is None else str(script)}  # fmt: skip
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
    runs = ((1, "B", (), idle, None), (1, "A", MOVING, moving, None),
            (1, "C", MOVING, moving, None), (2, "B", (), idle, None),
            (2, "B", MOVING, moving, None), (3, "B", MOVING, moving, None),
            (4, "B", MOVING, moving, None), (5, "B", MOVING, moving, None),
            (6, "B", MOVING, moving, "position"), (8, "B", ONE_MOVING, moving, None))  # fmt: skip
    for page, layout, lines, bare, edit in runs:
        tui = run_frontend("tui", show, tmp_path, monkeypatch, page, lines, layout, edit)
        what = f"F{page}" + (f" {layout}" if page == 1 else "")
        what += f" editing a {edit} preset" if edit else ""
        what += ", P11's Circle running" if lines else ""
        check(what, bare, tui)
    port = free_udp_port()  # F9: a fader sweep on an OSC surface, bare and with the TUI
    document["surfaces"] = [
        {"id": "s-touch", "name": "Touch", "kind": "osc", "match": {"port": port},
         "faderPickup": "jump"}
    ]  # fmt: skip
    document["bindings"] = [
        {"id": "b-1", "surfaceId": "s-touch", "input": {"kind": "osc", "path": "/fader/1"},
         "action": {"kind": "playbackFader", "slot": 0}}
    ]  # fmt: skip
    busk.save_show(document, show, backups=False)
    swept = run_frontend("bare", show, tmp_path, monkeypatch, osc=port)
    tui = run_frontend("tui", show, tmp_path, monkeypatch, 9, osc=port)
    check("F9, a fader sweep coming in", swept, tui)


def festival(folder: Path) -> Path:
    """``examples/festival.busk`` (2,189 lines), its profiles' paths made
    absolute, without its route, its surfaces and what binds them: no
    packets on the network, no port opened."""
    lines = (ROOT / "examples" / "festival.busk").read_text(encoding="utf-8").splitlines()
    kept = [
        line.replace('profile import "examples/', f'profile import "{ROOT}/examples/')
        for line in lines
        if not line.startswith(("route ", "surface ", "bind ", "feedback "))
    ]
    path = folder / "festival.busk"
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return path


def test_under_busk_run_the_engine_runs_on_time_while_a_script_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = festival(tmp_path)
    bare_show, tui_show = tmp_path / "bare.show", tmp_path / "tui.show"
    for show in (bare_show, tui_show):
        busk.save_show(busk.new_show("Festival Main Stage"), show, backups=False)
    bare = run_frontend("bare", bare_show, tmp_path, monkeypatch, script=script)
    tui = run_frontend("tui", tui_show, tmp_path, monkeypatch, script=script)
    print(
        f"\nimporting {len(script.read_text().splitlines())} lines of festival.busk took "
        f"{bare['seconds']:.1f} s with run_script, {tui['seconds']:.1f} s with the TUI"
    )
    # busk's own edits cost the engine a few overruns, with a display or
    # without (the compiled show changes at each): the TUI adds none.
    check("F1 B, festival.busk importing", bare, tui, overruns=bare["overruns"] / bare["ticks"])
    assert tui["seconds"] <= MAX_IMPORT * bare["seconds"]


def check(what: str, bare: Any, tui: Any, overruns: float = 0.0) -> None:
    """The gates, on a run with the TUI against one with a frontend that
    waits; ``overruns``, the share of ticks the engine overran without it."""
    cores = tui["cpu"] / tui["seconds"] - bare["cpu"] / bare["seconds"]
    print(
        f"\nbusk run, {what}: overruns {bare['overruns']}/{bare['ticks']} bare, "
        f"{tui['overruns']}/{tui['ticks']} with the TUI; "
        f"console CPU {bare['cpu'] / bare['seconds']:.3f} core bare, "
        f"{tui['cpu'] / tui['seconds']:.3f} with the TUI (+{cores:.3f})"
    )
    assert tui["ticks"] > 0
    assert tui["overruns"] <= (overruns + MAX_OVERRUNS) * tui["ticks"]
    assert cores <= MAX_CPU


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port
