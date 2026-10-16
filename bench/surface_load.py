"""Surface load: the engine with every Phase 6 surface busy (phase-6-plan §5.20, step 19).

For each rig the engine runs at 100 Hz on the real clock for 20 s, wired as
``busk run`` wires it (session, binding resolver, surface manager with the
web link, feedback worker), while:

* a WebSocket client, the phone, sends 60 ``SET_FADER`` a second to the web
  surface and reads every message it is sent;
* 100 MIDI events a second go through the
  :class:`~busk.io.bindings.BindingResolver`: moves of the MIDI controller's
  fader bindings;
* an OSC client sends 60 messages a second to an OSC surface, whose
  ``/bench/fader/N`` bindings move the faders of the current page;
* the feedback worker runs at its 30 Hz into a fake MIDI output;
* a probe submits ``SET_FADER`` to a playback nothing else touches, 10 times
  a second, and waits until the engine's snapshot shows it.

Rigs:

* **demo**: the Phase 6 done-criterion show, as the four example scripts
  save it (``tests/golden/phase6_surfaces_show.json``): 18 playbacks, two
  pages, the nanoKONTROL2 bindings with LEDs and the phone;
* **reference**: ``tests/builders.surface_benchmark_rig``: §19's 64
  universes, 61 playbacks on 3 pages and a MIDI controller with 200
  bindings, all with feedback.

Both get an OSC surface, and their web surface listens on 127.0.0.1, so no
packet leaves the machine. MIDI controllers are not opened (input events are
injected); the feedback worker reports their missing output ports, which
the run collects.

It reports engine overruns, tick p99 and max, state messages a second at the
phone, the phone's round trip (sent → a state shows it), and command latency
(probe submit → applied, as seen in the snapshot), with ``busk run``'s
settings (the GIL switch interval and ``gc.freeze()``).

With ``--processes`` (Phase 7, phase-7-plan §5.26) the engine runs in a real
engine host process and the bench is the console: the session, the
surfaces, the web and the feedback worker read the engine's snapshot over
the link, and overruns come from the engine's ``STATS``. Tick p99 is then
not measured (the bench cannot time the engine's ticks); the longest tick
is.

Run it with ``uv run python bench/surface_load.py [--processes] [seconds]``.
Targets: demo rig 0 overruns (hard); reference rig under 1 % of ticks
overrun (soft in threads; hard across processes, phase-7-plan §5.26). If
the demo rig overruns, phase-6-plan §5.20 lists what to try, in order.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import socket
import statistics
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "bench"))

from builders import surface_benchmark_rig  # noqa: E402
from busk.cli import SWITCH_INTERVAL  # noqa: E402
from busk.commands.types import Command  # noqa: E402
from busk.compiler.compile import compile_show  # noqa: E402
from busk.engine.clock import MonotonicClock  # noqa: E402
from busk.engine.snapshot import EngineSnapshot  # noqa: E402
from busk.io import osc  # noqa: E402
from busk.io.bindings import BindingResolver  # noqa: E402
from busk.io.events import InputEvent  # noqa: E402
from busk.io.feedback import FeedbackWorker  # noqa: E402
from busk.io.surfaces import SurfaceManager  # noqa: E402
from busk.model.common import PlaybackId, SurfaceId  # noqa: E402
from busk.model.show import Show  # noqa: E402
from busk.model.surface import InputAddress  # noqa: E402
from busk.model.validate import has_errors, validate_show  # noqa: E402
from busk.process.report import say, warn  # noqa: E402
from busk.session.ids import CounterIds  # noqa: E402
from busk.session.session import InputSink, Session  # noqa: E402
from busk.web.api import WebLink  # noqa: E402
from engines import ThreadEngine, make_engine  # noqa: E402
from ws_client import WsClient  # noqa: E402

DURATION = 20.0
WEB_RATE, MIDI_RATE, OSC_RATE, PROBE_RATE = 60.0, 100.0, 60.0, 10.0
WEB_PLAYBACKS = 4  # the playbacks the phone moves
OSC_FADERS = 8  # /bench/fader/1 … 8: slots 1–8 of the current page
KEY = "bench-key"
OSC_SURFACE = SurfaceId("s-osc-bench")


def demo_show() -> Show:
    """The show ``tests/fixtures/phase6-surfaces.busk`` and the scripts before it save."""
    path = ROOT / "tests" / "golden" / "phase6_surfaces_show.json"
    return cast(Show, json.loads(path.read_text()))


def reference_show() -> Show:
    return cast(Show, surface_benchmark_rig())


def free_port(kind: socket.SocketKind) -> int:
    """A port nothing on 127.0.0.1 uses now (for a surface to bind)."""
    with socket.socket(socket.AF_INET, kind) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


@dataclass
class Plan:
    """What the load generators drive in one rig."""

    web_port: int
    osc_port: int
    midi: list[tuple[SurfaceId, InputAddress]]  # the controller's fader inputs
    web: list[PlaybackId]  # the playbacks the phone moves
    probe: PlaybackId  # the playback only the probe moves


def prepare(show: Show) -> Plan:
    """Point the show's web surface at 127.0.0.1 (adding one if it has none),
    add the OSC surface and its bindings, and choose what each generator
    moves."""
    web_port, osc_port = free_port(socket.SOCK_STREAM), free_port(socket.SOCK_DGRAM)
    web = next((s for s in show["surfaces"] if s["kind"] == "web"), None)
    if web is None:
        web = cast(Any, {"id": "s-web-bench", "name": "Phone", "kind": "web",
                         "faderPickup": "jump"})  # fmt: skip
        show["surfaces"].append(web)
    web["match"] = {"port": web_port, "host": "127.0.0.1"}
    show["surfaces"].append(
        cast(Any, {"id": OSC_SURFACE, "name": "Bench OSC", "kind": "osc",
                   "match": {"port": osc_port, "host": "127.0.0.1"}, "faderPickup": "jump"})
    )  # fmt: skip
    for n in range(1, OSC_FADERS + 1):
        show["bindings"].append(
            cast(Any, {"id": f"b-osc-bench-{n}", "surfaceId": OSC_SURFACE,
                       "input": {"kind": "osc", "path": f"/bench/fader/{n}"},
                       "action": {"kind": "playbackFader", "slot": n - 1}})
        )  # fmt: skip
    first_page = min(show["pages"], key=lambda page: page["number"])
    on_page = {ident for ident in first_page["slots"] if ident is not None}
    others = [
        playback["id"]
        for playback in sorted(show["playbacks"], key=lambda p: p["number"])
        if playback["id"] not in on_page
    ]
    assert len(others) > WEB_PLAYBACKS, "every playback is on the first page"
    phone, probe = others[-WEB_PLAYBACKS:], others[0]
    # The controller's faders: the page's, and absolute ones on any playback
    # but the phone's and the probe's, so each measurement sees its own moves.
    midi_surfaces = {s["id"] for s in show["surfaces"] if s["kind"] == "midi"}
    measured = {*phone, probe}
    midi = []
    for binding in show["bindings"]:
        action = binding["action"]
        if binding["surfaceId"] in midi_surfaces and (
            action["kind"] == "playbackFader"
            or (action["kind"] == "playbackFaderAbs" and action["playbackId"] not in measured)
        ):
            midi.append((binding["surfaceId"], binding["input"]))
    return Plan(web_port, osc_port, midi, phone, probe)


def paced(rate: float, stop: threading.Event) -> Iterator[int]:
    """Yield 0, 1, 2… at ``rate`` per second until ``stop`` is set (late
    iterations catch up at once, as a busy client would)."""
    start = time.perf_counter()
    k = 0
    while not stop.is_set():
        yield k
        k += 1
        delay = start + k / rate - time.perf_counter()
        if delay > 0:
            time.sleep(delay)


def level(k: int) -> float:
    """A fader level that differs from its neighbours and survives JSON."""
    return ((k * 37) % 1000) / 1000


class FakeMidiOut:
    """Stands in for a controller's MIDI output: counts what it is sent."""

    def __init__(self) -> None:
        self.sent = 0

    def send(self, address: object, kind: object, value: object) -> None:
        self.sent += 1


@dataclass
class Phone:
    """The WebSocket client: what it sent and what came back."""

    client: WsClient
    states: int = 0
    replies: int = 0
    errors: list[str] = field(default_factory=list)
    pending: dict[str, tuple[float, float]] = field(default_factory=dict)  # id → (level, sent at)
    round_trips: list[float] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def send(self, k: int, playback: str) -> None:
        value = level(k)
        command = {"type": "SET_FADER", "playbackId": playback, "level": value}
        with self.lock:
            self.pending[playback] = (value, time.perf_counter())
        self.client.send_text(json.dumps({"id": str(k), "command": command}))

    def read(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                message = json.loads(self.client.recv_text())
            except (OSError, ValueError, AssertionError):
                return  # closed at the end of the run
            arrived = time.perf_counter()
            if message.get("type") == "state":
                self.states += 1
                levels = {p["id"]: p["faderLevel"] for p in message["playbacks"]}
                with self.lock:
                    for playback, (value, sent) in list(self.pending.items()):
                        if levels.get(playback) == value:
                            self.round_trips.append(arrived - sent)
                            del self.pending[playback]
            elif message.get("type") == "reply":
                self.replies += 1
                if not message.get("ok", True):
                    self.errors.append(str(message))


def find(snapshot: EngineSnapshot | None, playback: PlaybackId) -> float | None:
    if snapshot is None:
        return None
    return next((p.faderLevel for p in snapshot.playbacks if p.id == playback), None)


def measure(name: str, show: Show, seconds: float, *, processes: bool) -> dict[str, Any]:
    plan = prepare(show)
    checked, issues = validate_show(json.dumps(show))
    assert checked is not None, issues
    assert not has_errors(issues), issues
    show = checked
    clock = MonotonicClock()
    compiled = compile_show(show)
    engine = make_engine(compiled, clock, processes=processes)
    session = Session(show, engine.bus, compiled=compiled, ids=CounterIds(10_000), report=warn)
    reports: list[str] = []

    def page() -> str | None:
        snapshot = engine.snapshot
        return None if snapshot is None or snapshot.page is None else snapshot.page.id

    resolver = BindingResolver(
        show,
        compiled,
        InputSink(session),
        reports.append,
        live=lambda: engine.compiled,
        page=page,
        clock=clock.now,
    )
    link = WebLink(
        snapshot=lambda: engine.snapshot,
        compiled=lambda: engine.compiled,
        submit=session.submit,
        clock=clock.now,
        key=KEY,
    )
    surfaces = SurfaceManager(resolver.handle, link, say=say, warn=warn)
    surfaces.reconcile(compiled)
    outputs = {
        binding["surfaceId"]: FakeMidiOut()
        for binding in show["bindings"]
        if "feedback" in binding and binding["surfaceId"] != OSC_SURFACE
    }
    feedback = FeedbackWorker(
        lambda: engine.compiled,
        lambda: engine.snapshot,
        resolver.lastInput,
        clock=clock.now,
        senders=lambda: {**surfaces.senders(), **outputs},
        report=reports.append,
        say=say,
        warn=warn,
    )
    feedback.open()

    tick_times: list[float] = []  # only for an engine thread
    if isinstance(engine, ThreadEngine):
        tick = engine.engine.tick

        def timed_tick(now: float) -> None:
            started = time.perf_counter()
            tick(now)
            tick_times.append(time.perf_counter() - started)

        engine.engine.tick = timed_tick  # type: ignore[method-assign]

    gc.collect()
    gc.freeze()  # as busk run does after loading
    stop_feedback, stop_load = threading.Event(), threading.Event()
    engine.start()
    worker = threading.Thread(target=feedback.run, args=(stop_feedback,), daemon=True)
    worker.start()
    time.sleep(0.5)  # the first snapshot, the web server and the OSC socket
    phone = Phone(WsClient(plan.web_port, KEY))
    # Browsers send WebSocket frames without Nagle's delay; so does the phone here.
    phone.client.connection.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    latencies: list[float] = []

    def phone_sends() -> None:
        for k in paced(WEB_RATE, stop_load):
            phone.send(k, plan.web[k % len(plan.web)])

    def midi_events() -> None:
        for k in paced(MIDI_RATE, stop_load):
            surface, address = plan.midi[k % len(plan.midi)]
            resolver.handle(InputEvent(surface, address, level(k)))

    def osc_messages() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            for k in paced(OSC_RATE, stop_load):
                path = f"/bench/fader/{k % OSC_FADERS + 1}"
                sender.sendto(osc.encode(path, level(k)), ("127.0.0.1", plan.osc_port))

    def probe() -> None:
        for k in paced(PROBE_RATE, stop_load):
            value = level(k + 1)
            command = {"type": "SET_FADER", "playbackId": plan.probe, "level": value}
            started = time.perf_counter()
            result = session.submit(cast(Command, command))
            assert result.ok, result
            while find(engine.snapshot, plan.probe) != value:
                if time.perf_counter() - started > 1.0:
                    raise AssertionError("the probe's SET_FADER never showed")
                time.sleep(0.0002)
            latencies.append(time.perf_counter() - started)

    load = [
        threading.Thread(target=phone.read, args=(stop_load,), daemon=True),
        *(
            threading.Thread(target=target, daemon=True)
            for target in (phone_sends, midi_events, osc_messages, probe)
        ),
    ]
    before = engine.stats()
    first_tick = len(tick_times)
    sent_before = sum(out.sent for out in outputs.values())
    started = time.perf_counter()
    for thread in load:
        thread.start()
    time.sleep(seconds)
    stop_load.set()
    elapsed = time.perf_counter() - started
    after = engine.stats()
    durations = sorted(tick_times[first_tick:])
    feedback_sent = sum(out.sent for out in outputs.values()) - sent_before
    for thread in load[1:]:
        thread.join()
    surfaces.close()  # also closes the phone's connection, which ends its reader
    load[0].join(timeout=2.0)
    phone.client.close()
    stop_feedback.set()
    worker.join()
    session.stop()
    engine.stop()
    gc.unfreeze()
    assert not phone.errors, phone.errors[:3]
    return {
        "rig": name,
        "playbacks": len(show["playbacks"]),
        "bindings": len(show["bindings"]),
        "ticks": after.ticks - before.ticks,
        "overruns": after.overruns - before.overruns,
        "p99": (
            durations[min(len(durations) - 1, math.ceil(len(durations) * 0.99) - 1)]
            if durations
            else None
        ),
        "max": after.maxTickSeconds,
        "gcPause": engine.gcPause,
        "states": phone.states / elapsed,
        "round_trips": sorted(phone.round_trips),
        "latencies": sorted(latencies),
        "feedback": feedback_sent / elapsed,
        "reports": reports,
    }


def percentiles(values: list[float]) -> str:
    if len(values) < 2:
        return "n/a"
    p50, p95 = statistics.median(values), statistics.quantiles(values, n=20)[18]
    return f"p50 {p50 * 1000:.1f} ms, p95 {p95 * 1000:.1f} ms, max {values[-1] * 1000:.1f} ms"


def main() -> None:
    parser = argparse.ArgumentParser(description="The engine under surface load.")
    parser.add_argument("seconds", nargs="?", type=float, default=DURATION,
                        help="how long each rig is loaded")  # fmt: skip
    parser.add_argument("--processes", action="store_true",
                        help="run the engine in an engine process (Phase 7's layout)")  # fmt: skip
    args = parser.parse_args()
    seconds = args.seconds
    sys.setswitchinterval(SWITCH_INTERVAL)
    layout = "engine process" if args.processes else "engine thread"
    print(f"{layout}, {seconds:g} s per rig, GIL switch interval {SWITCH_INTERVAL * 1000:g} ms")
    makers: tuple[tuple[str, Callable[[], Show]], ...] = (
        ("demo", demo_show),
        ("reference", reference_show),
    )
    for name, make in makers:
        result = measure(name, make(), seconds, processes=args.processes)
        share = result["overruns"] / max(1, result["ticks"])
        p99, gc_pause = result["p99"], result["gcPause"]
        print(
            f"{result['rig']}: {result['playbacks']} playbacks, {result['bindings']} bindings; "
            f"{result['overruns']} overruns in {result['ticks']} ticks ({share:.2%}), "
            + ("" if p99 is None else f"tick p99 {p99 * 1000:.2f} ms, ")
            + f"max tick {result['max'] * 1000:.2f} ms"
            + ("" if gc_pause is None else f", engine GC pause {gc_pause * 1000:.1f} ms")
        )
        print(
            f"  phone: {result['states']:.1f} states/s, round trip "
            f"{percentiles(result['round_trips'])} ({len(result['round_trips'])} seen)"
        )
        print(f"  command latency (submit → applied): {percentiles(result['latencies'])}")
        print(f"  feedback: {result['feedback']:.0f} MIDI messages/s")
        for line in sorted(set(result["reports"])):
            print(f"  reported: {line}")


if __name__ == "__main__":
    main()
