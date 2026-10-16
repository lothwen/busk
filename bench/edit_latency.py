"""Edit latency and engine stalls during live edits (phase-3-plan §5.11, step 13).

Every live edit validates, compiles and builds a programmer frame on the
caller's thread, and the autosave thread serialises the show. In CPython all
of that holds the GIL and can delay the engine's ticks. This benchmark
measures it on two rigs:

* **demo**: the show ``examples/phase3-build.busk`` builds (7 fixtures);
* **reference**: §19's scale: 400 fixtures over 64 universes (Phase 1
  profiles), 40 groups, 100 presets, 100 cue lists with playbacks (20 of them
  running).

For each rig the engine runs at 100 Hz on the real clock, with the autosave
worker running, while 50 edits of each kind are submitted through the
session: ``RECORD_CUE`` (merge), ``RECORD_PRESET`` (merge), ``PATCH_FIXTURE``
and ``SET``. It reports edit latency (p50, p95, max), engine overruns and the
longest tick.

It runs with the settings ``busk run`` uses (the GIL switch interval of
:data:`busk.cli.SWITCH_INTERVAL` and ``gc.freeze()`` after loading); give a
switch interval in seconds as the argument to try another one.

With ``--processes`` (Phase 7, phase-7-plan §5.26) the engine runs in a real
engine host process, as ``busk run`` runs it now: the session submits and
installs through a ``RemoteBus``, the autosave worker stays in the bench (the
console process), and overruns come from the engine's ``STATS``. Without it,
the engine is a thread of the bench, as ``busk run --threads`` runs it.

Run it with ``uv run python bench/edit_latency.py [--processes] [interval]``.
Targets: demo rig 0 overruns and p95 ≤ 50 ms (hard); reference rig 0
overruns and p95 ≤ 250 ms in threads, ≤ 1 % of ticks overrun across
processes (hard).
"""

from __future__ import annotations

import argparse
import gc
import json
import random
import statistics
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "bench"))

from busk.cli import SWITCH_INTERVAL  # noqa: E402
from busk.commands.types import Command  # noqa: E402
from busk.compiler.compile import compile_show  # noqa: E402
from busk.console.console import Console  # noqa: E402
from busk.engine.clock import MonotonicClock  # noqa: E402
from busk.engine.loop import Engine  # noqa: E402
from busk.model.show import Show  # noqa: E402
from busk.model.validate import has_errors, validate_show  # noqa: E402
from busk.persistence.autosave import AutosaveWorker  # noqa: E402
from busk.persistence.show_file import new_show  # noqa: E402
from busk.session.ids import CounterIds  # noqa: E402
from busk.session.library import ProfileLibrary  # noqa: E402
from busk.session.session import Session  # noqa: E402
from engines import make_engine  # noqa: E402

EDITS = 50
NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)
CID = "0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f"

type Edit = Callable[[int], list[dict[str, Any]]]


def demo_show() -> Show:
    """The show the Phase 3 build script makes."""
    ids = CounterIds()
    show = new_show("Club Night", ids=ids, now=NOW, cid=CID)
    compiled = compile_show(show)
    session = Session(show, Engine(compiled, MonotonicClock()).bus, compiled=compiled, ids=ids)
    console = Console(session, ProfileLibrary())
    lines = (ROOT / "examples" / "phase3-build.busk").read_text().splitlines()
    for line in lines:
        if line.strip() != "save":
            reply = console.execute(line)
            assert reply.ok, (line, reply.text)
    return session.show


def reference_show(seed: int = 3) -> Show:
    """400 fixtures over 64 universes, 40 groups, 100 presets, 100 cue lists."""
    rng = random.Random(seed)
    library = ProfileLibrary()
    profiles = [library.find(name) for name in (
        "Generic Spot 16ch", "Stairville MH-X25 LED Spot", "Eurolite LED ML-56 RGBW",
        "Chauvet DJ COLORband PiX")]  # fmt: skip
    assert all(profiles)
    show: dict[str, Any] = dict(new_show("Reference", ids=CounterIds(), now=NOW, cid=CID))
    show["profiles"] = profiles
    show["universes"] = [{"id": f"u{u}", "name": f"U{u}", "number": u} for u in range(1, 65)]
    fixtures = []
    universe, address = 1, 1
    for k in range(400):
        profile = cast(dict[str, Any], profiles[k % 4])
        mode = profile["modes"][0]
        if address + mode["footprint"] - 1 > 512:
            universe, address = universe + 1, 1
        fixtures.append({
            "id": f"fx{k}", "name": f"F{k}", "number": 1000 + k, "profileId": profile["id"],
            "profileRevision": profile["revision"], "modeId": mode["id"],
            "patch": {"universeId": f"u{universe}", "address": address},
            "orientation": {"invertPan": False, "invertTilt": False, "swapPanTilt": False,
                            "panOffset": 0, "tiltOffset": 0}})  # fmt: skip
        address += mode["footprint"]
    assert universe <= 64
    show["fixtures"] = fixtures
    heads = [f for f in fixtures if f["profileId"] in ("prof-mh", "prof-mhx25")]
    colour = [f for f in fixtures if f["profileId"] != "prof-mhx25"]
    show["groups"] = [
        {"id": f"g{g}", "name": f"G{g}", "number": g + 1,
         "members": [{"fixtureId": f["id"], "element": 0}
                     for f in rng.sample(heads if g % 2 else colour, 20)]}
        for g in range(40)
    ]  # fmt: skip
    presets = []
    for p in range(100):
        if p < 60:
            color = {"r": rng.random(), "g": rng.random(), "b": rng.random()}
            values = [{"scope": {"kind": "global"}, "attribute": "color", "value": color}]
            pool, number = "color", p + 1
        else:
            values = [
                {
                    "scope": {"kind": "target", "target": {"fixtureId": f["id"], "element": 0}},
                    "attribute": "pan",
                    "value": rng.uniform(-90, 90),
                }
                for f in heads[:40]
            ]
            pool, number = "position", p - 59
        presets.append(
            {"id": f"pr{p}", "name": f"P{p}", "number": number, "pool": pool, "values": values}
        )
    show["presets"] = presets
    show["cueLists"], show["playbacks"] = [], []
    for c in range(100):
        group = f"g{rng.randrange(40)}"
        entries = [
            {"targets": {"kind": "group", "groupId": group}, "attribute": "intensity",
             "value": {"kind": "literal", "value": rng.random()}},
            {"targets": {"kind": "group", "groupId": group}, "attribute": "color",
             "value": {"kind": "preset", "presetId": f"pr{rng.randrange(60)}"}},
        ]  # fmt: skip
        timing = {"fadeIn": 0, "fadeOut": 0, "delayIn": 0, "delayOut": 0, "curve": "linear"}
        cue = {"id": f"c{c}", "number": "1", "name": "1", "entries": entries, "effects": [],
               "timing": timing, "trigger": {"kind": "go"}}  # fmt: skip
        show["cueLists"].append({
            "id": f"cl{c}", "name": f"L{c}", "number": c + 1, "mode": "sequence",
            "tracking": False, "wrap": False, "releaseAtEnd": False, "cues": [cue]})  # fmt: skip
        show["playbacks"].append({
            "id": f"pb{c}", "name": f"PB{c}", "number": c + 1, "cueListId": f"cl{c}",
            "priority": 50, "fader": "master", "buttons": ["toggle"],
            "ltpFaderMode": "ignoreFader", "ltpThreshold": 0.02, "autoStart": True,
            "autoRelease": True, "flash": {"level": 1, "includeLtp": False},
            "protectFromSwop": False, "releaseTime": 1})  # fmt: skip

    checked, issues = validate_show(json.dumps(show))
    assert checked is not None, issues[:5]
    assert not has_errors(issues), issues[:5]
    return checked


def edits(show: Show) -> dict[str, Edit]:
    """Command makers per edit kind, for edit number ``k``."""
    groups = [g["id"] for g in show["groups"]]
    lists = [cl["id"] for cl in show["cueLists"]]
    colour = [p for p in show["presets"] if p["pool"] == "color"]
    fixtures = [f for f in show["fixtures"] if f["patch"] is not None]
    playbacks = [p["id"] for p in show["playbacks"]]

    def program(k: int) -> list[dict[str, Any]]:
        return [
            {"type": "SELECT", "mode": "replace",
             "targets": {"kind": "group", "groupId": groups[k % len(groups)]}},
            {"type": "SET_ATTRIBUTE", "attribute": "color",
             "value": {"kind": "literal", "value": {"r": (k % 10) / 10, "g": 0.5, "b": 1}}},
        ]  # fmt: skip

    def record_cue(k: int) -> list[dict[str, Any]]:
        cue_list = lists[k % len(lists)]
        number = next(cl for cl in show["cueLists"] if cl["id"] == cue_list)["cues"][0]["number"]
        return [
            *program(k),
            {"type": "RECORD_CUE", "cueListId": cue_list, "cueNumber": number, "merge": "merge"},
        ]

    def record_preset(k: int) -> list[dict[str, Any]]:
        preset = colour[k % len(colour)]
        return [*program(k), {"type": "RECORD_PRESET", "pool": "color", "number": preset["number"],
                              "scope": "global", "merge": "merge"}]  # fmt: skip

    def patch(k: int) -> list[dict[str, Any]]:
        fixture = fixtures[(k // 2) % len(fixtures)]
        return [{"type": "PATCH_FIXTURE", "fixtureId": fixture["id"],
                 "patch": None if k % 2 == 0 else fixture["patch"]}]  # fmt: skip

    def set_(k: int) -> list[dict[str, Any]]:
        playback = playbacks[k % len(playbacks)]
        return [
            {"type": "SET", "path": ["playbacks", {"id": playback}, "name"], "value": f"edited {k}"}
        ]

    return {"record cue": record_cue, "record preset": record_preset, "patch": patch, "set": set_}


def measure(name: str, show: Show, running: int, *, processes: bool) -> dict[str, Any]:
    clock = MonotonicClock()
    compiled = compile_show(show)
    engine = make_engine(compiled, clock, processes=processes)
    session = Session(show, engine.bus, compiled=compiled, ids=CounterIds(10_000))
    engine.start()
    for playback in list(show["playbacks"])[:running]:
        session.submit(
            cast(Command, {"type": "SET_FADER", "playbackId": playback["id"], "level": 1.0})
        )
    with tempfile.TemporaryDirectory() as state:
        autosave = AutosaveWorker(
            session, Path(state), clock=clock, wall_clock=lambda: datetime.now(UTC)
        )
        stop = threading.Event()
        thread = threading.Thread(target=autosave.run, args=(stop,), daemon=True)
        thread.start()
        time.sleep(0.5)
        before = engine.stats()
        latencies: dict[str, list[float]] = {}
        for kind, make in edits(session.show).items():
            for k in range(EDITS):
                commands = make(k)
                started = time.perf_counter()
                for command in commands:
                    result = session.submit(cast(Command, command))
                    assert result.ok, (kind, command, result)
                latencies.setdefault(kind, []).append(time.perf_counter() - started)
                time.sleep(0.005)  # an operator does not type at 1 kHz
        time.sleep(6.0)  # let the burst's show autosave happen
        after = engine.stats()
        stop.set()
        thread.join()
        session.stop()
        engine.stop()
        written = len(list(autosave.folder.glob("show-*.show")))
    every = [t for values in latencies.values() for t in values]
    return {
        "rig": name,
        "fixtures": len(show["fixtures"]),
        "slots": len(compiled.slots.slots),
        "latencies": latencies,
        "p50": statistics.median(every),
        "p95": statistics.quantiles(every, n=20)[18],
        "max": max(every),
        "overruns": after.overruns - before.overruns,
        "ticks": after.ticks - before.ticks,
        "maxTick": after.maxTickSeconds,
        "gcPause": engine.gcPause,
        "autosaves": written,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Edit latency and engine overruns.")
    parser.add_argument("interval", nargs="?", type=float, default=SWITCH_INTERVAL,
                        help="the GIL switch interval in seconds")  # fmt: skip
    parser.add_argument("--processes", action="store_true",
                        help="run the engine in an engine process (Phase 7's layout)")  # fmt: skip
    args = parser.parse_args()
    sys.setswitchinterval(args.interval)
    layout = "engine process" if args.processes else "engine thread"
    print(f"{layout}, GIL switch interval {sys.getswitchinterval() * 1000:g} ms")
    for name, make, running in (("demo", demo_show, 3), ("reference", reference_show, 20)):
        show = make()
        gc.collect()
        gc.freeze()  # as busk run does after loading
        result = measure(name, show, running, processes=args.processes)
        gc.unfreeze()
        share = result["overruns"] / max(1, result["ticks"])
        gc_pause = result["gcPause"]
        print(
            f"{result['rig']}: {result['fixtures']} fixtures, {result['slots']} slots; "
            f"edit p50 {result['p50'] * 1000:.1f} ms, p95 {result['p95'] * 1000:.1f} ms, "
            f"max {result['max'] * 1000:.1f} ms; {result['overruns']} overruns in "
            f"{result['ticks']} ticks ({share:.2%}), max tick {result['maxTick'] * 1000:.1f} ms"
            + ("" if gc_pause is None else f", engine GC pause {gc_pause * 1000:.1f} ms")
            + f"; {result['autosaves']} show autosave(s)"
        )
        for kind, values in result["latencies"].items():
            ordered = sorted(values)
            print(
                f"  {kind:<14} p50 {statistics.median(ordered) * 1000:6.1f} ms   "
                f"p95 {statistics.quantiles(ordered, n=20)[18] * 1000:6.1f} ms   "
                f"max {ordered[-1] * 1000:6.1f} ms"
            )


if __name__ == "__main__":
    main()
