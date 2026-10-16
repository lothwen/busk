"""The soak: done criterion B (phase-7-plan §5.25, decisions 23 and 24).

::

    uv run python bench/soak.py [--hours H] [--seed S] [--chaos standard|fast|none]
                                [--report FILE]

**The show.** A fresh show from the Phase 3–7 scripts (``busk new``, then
``busk run --threads --script … --duration 1`` for each), as the earlier
done criteria build it. Its route is then replaced by three on universe 1:
sACN unicast to 127.0.0.1, Art-Net unicast to 127.0.0.2, and DMX-USB to a
pseudo-terminal behind a symlink (:mod:`dmx_widget`). The web surface moves
to a free port and an OSC surface on another drives faders 1–8 and the "Wash
level" master. A virtual ALSA port named "nanoKONTROL2" stands in for the
MIDI controller; without ``/dev/snd/seq`` MIDI is off and the report says
so.

**The run.** ``busk run SHOW --stats stats.jsonl`` in process mode, with
stdin a pipe. The harness raises the FX master and the Circle (playback 11)
first, so universe 1 changes every output cycle (decision 23), then starts

* the **receiver** (``bench/soak_receiver.py``, normal priority): it
  timestamps every packet of the three routes and writes gaps and missing
  sequence numbers;
* the **load** (``bench/soak_load.py``, ``nice 10``, seeded): MIDI, OSC, a
  phone and console commands, at §5.25's rates;

and runs the **chaos** schedule (:data:`CHAOS`): engine ``SIGKILL``, engine
``SIGSTOP`` for :data:`STALL_HOLD_S` (the watchdog kills it at 3 s), console
``SIGKILL`` and DMX-USB unplug for :data:`UNPLUG_HOLD_S` and replug. At the
end the load stops and stdin closes, which quits the console and the run.

**The report** (``soak-<UTC>.json``, checkpointed every
:data:`CHECKPOINT_S`, plus a printed summary) is :func:`analyse`'s. The
files the run wrote, the event log under ``state/logs`` among them, stay in
the directory next to the report (``soak-<UTC>/``): with the seed they
reproduce what the engine saw (``busk replay``).

**Drops** (decision 23). Outside engine outages every gap longer than two
output cycles between packets is a drop. An outage runs from a kill or a
stop to the first ``--stats`` line with a new running engine, plus
:data:`WINDOW_SLACK_S` for that line's 1 s granularity; a gap overlapping
one is a drop only if it is longer than the protocol's keep-alive plus
250 ms. A missing sequence number, a packet that does not parse and a route
that falls silent are drops anywhere. The DMX-USB route is not measured
while it is unplugged.

**Pass** (decision 24, the hard criteria): zero drops; every chaos action
recovered within :data:`RECOVER_S`; as many restarts as kills; each
process's RSS at the end within 10 % + 20 MB of its value after the first
hour (half the run, for runs under two hours); no tick or install errors;
every route delivered; ``busk run`` exited 0. Engine overruns outside
outages above 0.1 % of the ticks are a warning (soft).
"""

from __future__ import annotations

import argparse
import contextlib
import heapq
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(ROOT / "src"))

from busk.output.artnet import KEEPALIVE_S as ARTNET_KEEPALIVE_S  # noqa: E402
from busk.output.dmxusb import KEEPALIVE_S as DMXUSB_KEEPALIVE_S  # noqa: E402
from busk.output.sacn import KEEPALIVE_S as SACN_KEEPALIVE_S  # noqa: E402
from busk.output.scheduler import OUTPUT_HZ  # noqa: E402
from busk.persistence.show_file import load_show, save_show, utc_now  # noqa: E402

SCRIPTS = [
    ROOT / "tests" / "fixtures" / f"{name}.busk"
    for name in (
        "phase3-build",
        "phase4-song",
        "phase5-effects",
        "phase6-surfaces",
        "phase7-safety",
    )
]

CHAOS: dict[str, dict[str, tuple[float, float]]] = {
    "standard": {
        "engineKill": (600.0, 1800.0),
        "engineStop": (1200.0, 7200.0),
        "consoleKill": (3000.0, 10800.0),
        "unplug": (300.0, 1200.0),
    },
    "fast": {
        "engineKill": (15.0, 300.0),
        "engineStop": (210.0, 1200.0),
        "consoleKill": (40.0, 1200.0),
        "unplug": (25.0, 300.0),
    },
    "none": {},
}
"""Each chaos mode's actions: ``(first, period)`` in seconds from the load's
start. §5.25's periods; the first times put one of each in a 1-hour
``standard`` run and the first kills of ``fast`` inside its first minute
(``tests/test_soak.py``)."""

STALL_HOLD_S = 4.0
"""How long an engine is stopped (``SIGSTOP`` … ``SIGCONT``)."""

UNPLUG_HOLD_S = 3.0
"""How long the DMX-USB widget stays unplugged."""

RECOVER_S = 20.0
"""A chaos action not recovered from within this long fails the soak."""

HOLD_S = {"engineStop": STALL_HOLD_S, "unplug": UNPLUG_HOLD_S}
"""An action that lasts: its recovery time counts from its end."""

SETTLE_S = 10.0
"""Overruns this long after a run start or an engine's recovery are not counted."""

WINDOW_SLACK_S = 1.5
"""Added to an outage's end: the ``--stats`` line that ends it may be 1 s late."""

STALL_ALLOWANCE_S = 0.25
"""Decision 23: during an outage a gap may be the keep-alive interval plus this."""

KEEPALIVE_S = {"sacn": SACN_KEEPALIVE_S, "artnet": ARTNET_KEEPALIVE_S, "dmxusb": DMXUSB_KEEPALIVE_S}

GAP_S = 2 / OUTPUT_HZ
"""Outside outages a gap longer than two output cycles (45.5 ms) is a drop."""

WARMUP_S = 3.0
"""Measuring starts this long after the load does (the Circle fades in over 1 s)."""

CHECKPOINT_S = 600.0
RSS_RATIO, RSS_SLACK = 1.10, 20 << 20
OVERRUN_SOFT = 0.001
EVENTS_KEPT = 200
"""The report lists at most this many drops and unexpected command errors."""

ROUTES = ("sacn", "artnet", "dmxusb")
INVALID_ERRORS = ("error: unknown command 'frobnicate'", "error: no fixture 999")
"""How the ``error:`` lines of the load's invalid commands start."""


# ------------------------------------------------------------------- the show


def busk(*args: str, stdin: str | None = None, timeout: float = 120.0) -> str:
    """Run ``busk ARGS``; its stdout. A failure raises with its output."""
    result = subprocess.run(
        [sys.executable, "-m", "busk", *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"busk {' '.join(args)}: {result.returncode}\n{result.stdout}{result.stderr}"
        )
    return result.stdout


def free_port() -> int:
    """A TCP and UDP port nothing listens on now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp:
        tcp.bind(("127.0.0.1", 0))
        port: int = tcp.getsockname()[1]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.bind(("127.0.0.1", port))
    return port


def soak_script(link: Path, osc_port: int) -> str:
    """The console lines that give the show its soak routes and OSC surface."""
    if any(c.isspace() for c in str(link)):
        raise ValueError(f"the DMX-USB port path may not contain spaces: {link}")
    lines = [
        "route add 1 sacn 1 unicast 127.0.0.1",
        "route add 1 artnet 0.0.0 unicast 127.0.0.2",
        f"route add 1 dmxusb enttecPro {link}",
        f'surface add osc "Soak OSC" port {osc_port}',
        *(f'bind "Soak OSC" osc "/soak/fader/{n}" fader {n}' for n in range(1, 9)),
        'bind "Soak OSC" osc "/soak/master" master "Wash level"',
        "save",
    ]
    return "\n".join(lines) + "\n"


def build_show(work: Path, *, link: Path, osc_port: int, web_port: int) -> Path:
    """The soak show in ``work`` (see the module docs); its path."""
    state = work / "state"
    show = work / "club.show"
    busk("new", str(show), "--title", "Club Night", "--state-dir", str(state))
    run = ["run", str(show), "--threads", "--no-console", "--state-dir", str(state)]
    for script in SCRIPTS:
        busk(*run, "--script", str(script), "--duration", "1")
    document, _issues = load_show(show)
    document["output"]["routes"] = []
    for surface in document["surfaces"]:
        if surface["kind"] == "web":
            surface["match"]["port"] = web_port
    save_show(document, show, now=utc_now(), backups=False)
    setup = work / "soak-setup.busk"
    setup.write_text(soak_script(link, osc_port))
    busk(*run, "--script", str(setup), "--duration", "1")
    busk("validate", str(show))
    return show


def sequencer() -> str | None:
    """Why MIDI is off (no usable ALSA sequencer), or ``None``."""
    if not os.access("/dev/snd/seq", os.R_OK | os.W_OK):
        return "off: no ALSA sequencer (/dev/snd/seq)"
    return None


# -------------------------------------------------------------- the readings


@dataclass(frozen=True, slots=True)
class Sample:
    """The parts of one ``--stats`` line the analysis reads."""

    t: float
    enginePid: int | None
    state: str
    ticks: int | None
    overruns: int | None
    maxTickMs: float | None
    tickErrors: int | None
    installErrors: int | None
    commandErrors: int | None
    gcPauseMs: float | None
    engineRss: int | None
    engineRestarts: int
    consolePid: int | None
    consoleRestarts: int
    consoleRss: int | None
    rootRss: int | None
    lateCycles: int
    longestGapMs: float

    @classmethod
    def of(cls, record: dict[str, Any]) -> Sample:
        engine, console, root = record["engine"], record["console"], record["root"]
        return cls(
            t=record["time"],
            enginePid=engine["pid"],
            state=engine["state"],
            ticks=engine["ticks"],
            overruns=engine["overruns"],
            maxTickMs=engine["maxTickMs"],
            tickErrors=engine["tickErrors"],
            installErrors=engine.get("installErrors"),
            commandErrors=engine.get("commandErrors"),
            gcPauseMs=engine["gcPauseMs"],
            engineRss=engine["rss"],
            engineRestarts=engine["restarts"],
            consolePid=console["pid"],
            consoleRestarts=console["restarts"],
            consoleRss=console["rss"],
            rootRss=root["rss"],
            lateCycles=root["lateCycles"],
            longestGapMs=root["longestGapMs"],
        )

    @property
    def running(self) -> bool:
        """Whether an engine is running and has ticked."""
        return self.state == "running" and self.enginePid is not None and bool(self.ticks)


class Tail:
    """New complete JSON lines of a file that another process appends to."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._offset = 0
        self._rest = b""

    def read(self) -> list[dict[str, Any]]:
        try:
            with self._path.open("rb") as stream:
                stream.seek(self._offset)
                chunk = stream.read()
        except FileNotFoundError:
            return []
        self._offset += len(chunk)
        lines = (self._rest + chunk).split(b"\n")
        self._rest = lines.pop()  # an unfinished last line waits for the next read
        return [json.loads(line) for line in lines if line.strip()]


@dataclass
class Readings:
    """Everything the run has measured so far."""

    samples: list[Sample] = field(default_factory=list)
    receiver: list[dict[str, Any]] = field(default_factory=list)  # every event but counts
    counts: dict[str, Any] = field(default_factory=dict)  # the receiver's latest count line
    chaos: list[dict[str, Any]] = field(default_factory=list)
    load: dict[str, Any] = field(default_factory=dict)
    errorLines: Counter[str] = field(default_factory=Counter)  # console "error:" lines
    exitCode: int | None = None

    def engine_pid(self) -> int | None:
        return next((s.enginePid for s in reversed(self.samples) if s.enginePid), None)

    def console_pid(self) -> int | None:
        return next((s.consolePid for s in reversed(self.samples) if s.consolePid), None)


# ------------------------------------------------------------------- the run


@dataclass(frozen=True)
class Config:
    seconds: float
    seed: int
    chaos: str
    report: Path

    @property
    def work(self) -> Path:
        return self.report.with_suffix("")


class Soak:
    """One soak run (see the module docs)."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.work = config.work
        self.readings = Readings()
        self.midi = sequencer() or "on"
        self._stats = Tail(self.work / "stats.jsonl")
        self._receiver_events = Tail(self.work / "receiver.jsonl")
        self._processes: list[subprocess.Popen[Any]] = []
        self._stdin: int | None = None  # the harness's end of the console's stdin
        self._log_lock = threading.Lock()
        self.start = 0.0  # wall time the load started
        self.measureFrom = 0.0
        self.measureTo: float | None = None

    # ----------------------------------------------------------- lifecycle

    def run(self) -> dict[str, Any]:
        """Build, run, analyse; the final report."""
        self.work.mkdir(parents=True, exist_ok=False)
        link = self.work / "dmxusb"
        print(
            f"soak: {self.config.seconds:g} s, chaos {self.config.chaos}, seed {self.config.seed}"
        )
        print(f"soak: files in {self.work}")
        try:
            osc_port, web_port = free_port(), free_port()
            show = build_show(self.work, link=link, osc_port=osc_port, web_port=web_port)
            self._receiver = self._spawn_receiver(link)  # after the build: only the soak's packets
            self._busk = self._spawn_busk(show)
            self._wait_ready()
            self._type('master "FX" 1', "go 11", "fader 11 1")
            key = (self.work / "state" / "web-key").read_text().strip()
            self._load = self._spawn_load(osc_port, web_port, key)
            self.start = time.time()
            self.measureFrom = self.start + WARMUP_S
            self._chaos_loop()
        finally:
            self._shut_down()
        report = self.report(final=True)
        write_json(self.config.report, report)
        print_summary(report, self.config.report)
        return report

    def _spawn_receiver(self, link: Path) -> subprocess.Popen[bytes]:
        events = self.work / "receiver.jsonl"
        command = [sys.executable, str(BENCH / "soak_receiver.py"), "--out", str(events)]
        receiver = subprocess.Popen([*command, "--pty", str(link)], stdin=subprocess.PIPE)
        self._processes.append(receiver)
        deadline = time.monotonic() + 10.0
        while not any(e["event"] == "ready" for e in self._receive()):
            if receiver.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("the receiver did not start")
            time.sleep(0.05)
        return receiver

    def _spawn_busk(self, show: Path) -> subprocess.Popen[str]:
        read_end, self._stdin = os.pipe()
        command = [sys.executable, "-m", "busk", "run", str(show)]
        command += [
            "--state-dir",
            str(self.work / "state"),
            "--stats",
            str(self.work / "stats.jsonl"),
        ]
        process = subprocess.Popen(
            command,
            stdin=read_end,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        os.close(read_end)
        self._processes.append(process)
        log = (self.work / "console.log").open("a", encoding="utf-8")
        for stream, name in ((process.stdout, "out"), (process.stderr, "err")):
            assert stream is not None
            threading.Thread(target=self._drain, args=(stream, name, log), daemon=True).start()
        return process

    def _drain(self, stream: IO[str], name: str, log: IO[str]) -> None:
        """Copy ``busk run``'s output to ``console.log`` with times; count
        the ``error:`` lines."""
        for line in stream:
            text = line.rstrip("\n")
            with self._log_lock:
                log.write(f"{time.time():.3f} {name} {text}\n")
                log.flush()
                if text.startswith("error:"):
                    self.readings.errorLines[text] += 1

    def _wait_ready(self, timeout: float = 60.0) -> None:
        """Until an engine runs, a console lives and the web key exists."""
        deadline = time.monotonic() + timeout
        key = self.work / "state" / "web-key"
        while True:
            self._update()
            last = self.readings.samples[-1] if self.readings.samples else None
            if last is not None and last.running and last.consolePid and key.exists():
                return
            if self._busk.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(f"busk run did not start (exit {self._busk.poll()})")
            time.sleep(0.2)

    def _type(self, *lines: str) -> None:
        assert self._stdin is not None
        for line in lines:
            os.write(self._stdin, (line + "\n").encode())

    def _spawn_load(self, osc_port: int, web_port: int, key: str) -> subprocess.Popen[bytes]:
        assert self._stdin is not None
        fd = os.dup(self._stdin)
        command = [
            sys.executable,
            str(BENCH / "soak_load.py"),
            "--out",
            str(self.work / "load.json"),
        ]
        command += ["--seed", str(self.config.seed), "--stdin-fd", str(fd)]
        command += ["--osc-port", str(osc_port), "--web-port", str(web_port), "--web-key", key]
        if self.midi != "on":
            command.append("--no-midi")
        load = subprocess.Popen(command, pass_fds=(fd,))
        os.close(fd)
        self._processes.append(load)
        return load

    def _shut_down(self) -> None:
        """Stop the load, close stdin (the console quits, then the run),
        stop the receiver; kill whatever is left."""
        if self.measureTo is None:
            self.measureTo = time.time()
        load = getattr(self, "_load", None)
        if load is not None:
            load.send_signal(signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                load.wait(15.0)
        if self._stdin is not None:
            os.close(self._stdin)
            self._stdin = None
        process = getattr(self, "_busk", None)
        if process is not None:
            try:
                self.readings.exitCode = process.wait(60.0)
            except subprocess.TimeoutExpired:
                process.send_signal(signal.SIGTERM)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    self.readings.exitCode = process.wait(15.0)
        receiver = getattr(self, "_receiver", None)
        if receiver is not None and receiver.stdin is not None:
            with contextlib.suppress(BrokenPipeError):
                receiver.stdin.write(b"quit\n")
                receiver.stdin.close()
            with contextlib.suppress(subprocess.TimeoutExpired):
                receiver.wait(10.0)
        for child in self._processes:
            if child.poll() is None:
                child.kill()
                child.wait()
        self._update()

    # --------------------------------------------------------------- chaos

    def _chaos_loop(self) -> None:
        """Run the chaos schedule and the checkpoints until the end."""
        end = self.start + self.config.seconds
        queue: list[tuple[float, str]] = []
        for action, (first, period) in CHAOS[self.config.chaos].items():
            at = first
            while at < self.config.seconds:
                heapq.heappush(queue, (self.start + at, action))
                at += period
        checkpoint = self.start + CHECKPOINT_S
        while True:
            now = time.time()
            if now >= end:
                for _, action in sorted(queue):  # never end with the engine stopped or unplugged
                    if action in ("engineContinue", "replug"):
                        self._act(action)
                return
            if now >= checkpoint:
                checkpoint += CHECKPOINT_S
                write_json(self.config.report, self.report(final=False))
            if queue and queue[0][0] <= now:
                _, action = heapq.heappop(queue)
                follow = self._act(action)
                if follow is not None:
                    heapq.heappush(queue, (time.time() + follow[0], follow[1]))
                continue
            if self._busk.poll() is not None:
                print(f"soak: busk run ended early ({self._busk.returncode})", file=sys.stderr)
                return
            due = min([end, checkpoint, *(at for at, _ in queue[:1])])
            time.sleep(max(0.0, min(0.5, due - time.time())))

    def _act(self, action: str) -> tuple[float, str] | None:
        """Do one chaos action and log it; a follow-up ``(delay, action)``."""
        self._update()
        pid: int | None = None
        follow: tuple[float, str] | None = None
        if action in ("engineKill", "engineStop", "engineContinue"):
            pid = self.readings.engine_pid() if action != "engineContinue" else self._stopped
            if action == "engineStop":
                self._stopped = pid
                follow = (STALL_HOLD_S, "engineContinue")
            number = {"engineKill": signal.SIGKILL, "engineStop": signal.SIGSTOP}.get(
                action, signal.SIGCONT
            )
            if pid is not None:
                with contextlib.suppress(ProcessLookupError):  # the watchdog may have killed it
                    os.kill(pid, number)
        elif action == "consoleKill":
            pid = self.readings.console_pid()
            if pid is not None:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)
        elif action in ("unplug", "replug"):
            assert self._receiver.stdin is not None
            self._receiver.stdin.write(f"{action}\n".encode())
            self._receiver.stdin.flush()
            follow = (UNPLUG_HOLD_S, "replug") if action == "unplug" else None
        entry: dict[str, Any] = {"t": time.time(), "action": action, "pid": pid}
        self.readings.chaos.append(entry)
        with (self.work / "chaos.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(entry) + "\n")
        print(f"soak: {entry['t'] - self.start:8.1f} s  {action} {pid or ''}", flush=True)
        return follow

    _stopped: int | None = None

    # ------------------------------------------------------------ readings

    def _receive(self) -> list[dict[str, Any]]:
        events = self._receiver_events.read()
        for event in events:
            if event["event"] == "count":
                self.readings.counts = event
            else:
                self.readings.receiver.append(event)
        return events

    def _update(self) -> None:
        self.readings.samples.extend(Sample.of(r) for r in self._stats.read())
        self._receive()
        with contextlib.suppress(FileNotFoundError, json.JSONDecodeError):
            self.readings.load = json.loads((self.work / "load.json").read_text())

    def report(self, *, final: bool) -> dict[str, Any]:
        self._update()
        to = self.measureTo if self.measureTo is not None else time.time()
        return analyse(
            self.readings,
            start=self.start,
            measure=(self.measureFrom, to),
            final=final,
            meta={
                "seed": self.config.seed,
                "chaos": self.config.chaos,
                "plannedSeconds": self.config.seconds,
                "midi": self.midi,
                "files": str(self.work),
                "eventLog": str(self.work / "state" / "logs"),
            },
        )


# -------------------------------------------------------------- the analysis


@dataclass(frozen=True)
class Outage:
    """An engine kill or stop: from the action to the first ``--stats``
    line with a running engine after it (``None``: not recovered)."""

    action: dict[str, Any]
    recovered: float | None

    def window(self) -> tuple[float, float]:
        end = self.action["t"] + RECOVER_S if self.recovered is None else self.recovered
        return self.action["t"], end + WINDOW_SLACK_S


def outages(readings: Readings) -> list[Outage]:
    found = []
    for action in readings.chaos:
        if action["action"] not in ("engineKill", "engineStop"):
            continue
        at, pid = action["t"], action["pid"]
        recovered = None
        before = next((s.ticks for s in reversed(readings.samples) if s.t <= at), None)
        for sample in readings.samples:
            if sample.t <= at or not sample.running:
                continue
            if action["action"] == "engineKill" and sample.enginePid == pid:
                continue
            stopped = action["action"] == "engineStop" and sample.enginePid == pid
            if stopped and (sample.t < at + STALL_HOLD_S or (sample.ticks or 0) <= (before or 0)):
                continue  # the stopped engine itself: only once it ticks again
            recovered = sample.t
            break
        found.append(Outage(action, recovered))
    return found


def overlaps(t0: float, t1: float, window: tuple[float, float]) -> bool:
    return t1 > window[0] and t0 < window[1]


def unplugged(readings: Readings) -> list[tuple[float, float]]:
    """The DMX-USB route's unplugged spans: from each unplug to the first
    message after the replug (or 30 s on, if none came)."""
    spans = []
    events = readings.receiver
    for index, event in enumerate(events):
        if event["event"] != "unplug":
            continue
        first = next(
            (e["t"] for e in events[index:] if e["event"] == "first" and e["t"] > event["t"]),
            event["t"] + UNPLUG_HOLD_S + RECOVER_S,
        )
        spans.append((event["t"], first + 0.1))
    return spans


def drops(
    readings: Readings, measure: tuple[float, float], windows: list[tuple[float, float]]
) -> list[dict[str, Any]]:
    """Every output drop (decision 23) between ``measure``'s times."""
    begin, end = measure
    spans = unplugged(readings)
    found = []
    for event in readings.receiver:
        kind = event["event"]
        route = str(event.get("route"))
        if kind == "gap":
            t0, t1 = event["t0"], event["t1"]
            if t1 < begin or t0 > end:
                continue
            if route == "dmxusb" and any(overlaps(t0, t1, span) for span in spans):
                continue
            gap = t1 - t0
            if any(overlaps(t0, t1, window) for window in windows):
                if gap <= KEEPALIVE_S[route] + STALL_ALLOWANCE_S:
                    continue
                kind = "outageGap"
            found.append(
                {
                    "kind": kind,
                    "route": route,
                    "t": t0,
                    "ms": gap * 1000,
                    "changed": event["changed"],
                }
            )
        elif kind in ("sequence", "bad") and begin <= event["t"] <= end:
            found.append(
                {
                    "kind": kind,
                    "route": route,
                    "t": event["t"],
                    **{k: event[k] for k in ("expected", "got", "error") if k in event},
                }
            )
    # A route that stops for good leaves no gap: its last packet is too old.
    routes, counted = readings.counts.get("routes", {}), readings.counts.get("t", begin)
    for route in ROUTES:
        last = routes.get(route, {}).get("last")
        since = last if last is not None else begin
        if since < min(end, counted) - 1.0 and not (
            route == "dmxusb" and any(span[0] <= since <= span[1] for span in spans)
        ):
            found.append({"kind": "silent", "route": route, "t": since})
    return sorted(found, key=lambda d: d["t"])


def recoveries(readings: Readings, found: list[Outage]) -> list[dict[str, Any]]:
    """Each chaos action with whether, and how fast, it was recovered from."""
    by_action = {id(o.action): o for o in found}
    result = []
    for action in readings.chaos:
        name, at = action["action"], action["t"]
        if name in ("engineContinue", "replug"):
            continue
        recovered: float | None = None
        if name in ("engineKill", "engineStop"):
            recovered = by_action[id(action)].recovered
        elif name == "consoleKill":
            recovered = next(
                (
                    s.t
                    for s in readings.samples
                    if s.t > at and s.consolePid not in (None, action["pid"])
                ),
                None,
            )
        elif name == "unplug":
            recovered = next(
                (e["t"] for e in readings.receiver if e["event"] == "first" and e["t"] > at), None
            )
        seconds = None if recovered is None else recovered - at
        result.append(
            {
                "action": name,
                "t": at,
                "pid": action["pid"],
                "recovered": seconds is not None and seconds <= RECOVER_S + HOLD_S.get(name, 0.0),
                "seconds": seconds,
            }
        )
    return result


def engine_counts(
    samples: list[Sample], windows: list[tuple[float, float]], start: float
) -> dict[str, Any]:
    """Ticks and overruns (in all and outside outages), the longest tick and
    GC pause, and the errors, summed over the engine processes."""
    ticks = overruns = quiet_ticks = quiet_overruns = 0
    last: dict[int, Sample] = {}
    errors = Counter[str]()
    peak: dict[int, dict[str, int]] = {}
    longest_tick = longest_quiet_tick = longest_gc = 0.0
    settled = [(begin, end + SETTLE_S - WINDOW_SLACK_S) for begin, end in windows]
    for sample in samples:
        pid = sample.enginePid
        if pid is None or sample.ticks is None or sample.overruns is None:
            continue
        previous = last.get(pid)
        last[pid] = sample
        peak[pid] = {
            "tickErrors": sample.tickErrors or 0,
            "installErrors": sample.installErrors or 0,
            "commandErrors": sample.commandErrors or 0,
        }
        longest_gc = max(longest_gc, sample.gcPauseMs or 0.0)
        longest_tick = max(longest_tick, sample.maxTickMs or 0.0)
        if previous is None or previous.ticks is None or previous.overruns is None:
            continue
        dt, do = sample.ticks - previous.ticks, sample.overruns - previous.overruns
        ticks += dt
        overruns += do
        quiet = previous.t >= start + SETTLE_S and not any(
            overlaps(previous.t, sample.t, window) for window in settled
        )
        if quiet:
            quiet_ticks += dt
            quiet_overruns += do
            if (sample.maxTickMs or 0.0) > (previous.maxTickMs or 0.0):
                longest_quiet_tick = max(longest_quiet_tick, sample.maxTickMs or 0.0)
    for counts in peak.values():
        errors.update(counts)
    return {
        "ticks": ticks,
        "overruns": overruns,
        "ticksOutsideOutages": quiet_ticks,
        "overrunsOutsideOutages": quiet_overruns,
        "overrunRatio": quiet_overruns / quiet_ticks if quiet_ticks else 0.0,
        "longestTickMs": longest_tick,
        "longestTickOutsideOutagesMs": longest_quiet_tick,
        "longestGcPauseMs": longest_gc,
        "processes": len(last),
        **{name: errors[name] for name in ("tickErrors", "installErrors", "commandErrors")},
    }


def memory(samples: list[Sample], start: float, end: float) -> dict[str, Any]:
    """Each process's RSS after the first hour (half the run for shorter
    runs), at the end, the allowed end value and the slope since the baseline
    (of the process alive at the end)."""
    baseline_at = start + min(3600.0, (end - start) / 2)
    result: dict[str, Any] = {}
    roles: dict[str, Callable[[Sample], tuple[int | None, int | None]]] = {
        "engine": lambda s: (s.enginePid, s.engineRss),
        "console": lambda s: (s.consolePid, s.consoleRss),
        "root": lambda s: (0, s.rootRss),
    }
    for role, pick in roles.items():
        points: list[tuple[float, int | None, int]] = []
        for sample in samples:
            pid, rss = pick(sample)
            if sample.t <= end and rss is not None:
                points.append((sample.t, pid, rss))
        if not points:
            continue
        base = next((p for p in points if p[0] >= baseline_at), points[-1])
        final = points[-1]
        limit = base[2] * RSS_RATIO + RSS_SLACK
        tail = [(t, rss) for t, pid, rss in points if t >= base[0] and pid == final[1]]
        result[role] = {
            "baselineAt": base[0] - start,
            "baselineMB": base[2] / 2**20,
            "endMB": final[2] / 2**20,
            "limitMB": limit / 2**20,
            "ok": final[2] <= limit,
            "slopeMBPerHour": slope(tail) * 3600 / 2**20,
        }
    return result


def slope(points: list[tuple[float, int]]) -> float:
    """The least-squares slope of ``points`` (per second); 0 for fewer than two."""
    if len(points) < 2:
        return 0.0
    mean_t = sum(t for t, _ in points) / len(points)
    mean_v = sum(v for _, v in points) / len(points)
    spread = sum((t - mean_t) ** 2 for t, _ in points)
    if spread == 0:
        return 0.0
    return sum((t - mean_t) * (v - mean_v) for t, v in points) / spread


def analyse(
    readings: Readings,
    *,
    start: float,
    measure: tuple[float, float],
    final: bool,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """The soak report (see the module docs) from what has been measured."""
    found = outages(readings)
    windows = [outage.window() for outage in found]
    dropped = drops(readings, measure, windows)
    recovered = recoveries(readings, found)
    engine = engine_counts(readings.samples, windows, start)
    rss = memory(readings.samples, start, measure[1])
    last = readings.samples[-1] if readings.samples else None
    kinds = Counter(d["kind"] for d in dropped)
    routes = readings.counts.get("routes", {})
    engine_chaos = sum(a["action"] in ("engineKill", "engineStop") for a in readings.chaos)
    console_chaos = sum(a["action"] == "consoleKill" for a in readings.chaos)
    restarts = {
        "engine": {"chaos": engine_chaos, "restarts": last.engineRestarts if last else 0},
        "console": {"chaos": console_chaos, "restarts": last.consoleRestarts if last else 0},
    }
    error_lines = sum(readings.errorLines.values())
    unexpected = {
        line: n for line, n in readings.errorLines.items() if not line.startswith(INVALID_ERRORS)
    }
    load_counts = readings.load.get("counts", {})
    criteria = [
        criterion("no output drops", not dropped, f"{len(dropped)} drops"),
        criterion(
            "every chaos action recovered",
            all(r["recovered"] for r in recovered),
            f"{sum(r['recovered'] for r in recovered)} of {len(recovered)}",
        ),
        criterion(
            "restarts match kills",
            all(r["restarts"] == r["chaos"] for r in restarts.values()),
            ", ".join(f"{k} {v['restarts']}/{v['chaos']}" for k, v in restarts.items()),
        ),
        criterion(
            "memory within 10 % + 20 MB",
            all(r["ok"] for r in rss.values()),
            ", ".join(f"{k} {v['endMB']:.0f}/{v['limitMB']:.0f} MB" for k, v in rss.items()),
        ),
        criterion(
            "no tick or install errors",
            engine["tickErrors"] == 0 and engine["installErrors"] == 0,
            f"{engine['tickErrors']} tick, {engine['installErrors']} install",
        ),
        criterion(
            "every route delivered",
            all(routes.get(r, {}).get("packets", 0) > 0 for r in ROUTES),
            ", ".join(f"{r} {routes.get(r, {}).get('packets', 0)}" for r in ROUTES),
        ),
    ]
    if final:
        criteria.append(
            criterion("busk run exited 0", readings.exitCode == 0, f"exit {readings.exitCode}")
        )
    criteria.append(
        criterion(
            "overruns outside outages ≤ 0.1 %",
            engine["overrunRatio"] <= OVERRUN_SOFT,
            f"{engine['overrunsOutsideOutages']} of {engine['ticksOutsideOutages']} ticks",
            hard=False,
        )
    )
    passed = all(c["ok"] for c in criteria if c["hard"])
    return {
        "final": final,
        "result": ("pass" if passed else "fail") if final else "running",
        **meta,
        "start": datetime.fromtimestamp(start, UTC).isoformat() if start else None,
        "seconds": measure[1] - start if start else 0.0,
        "measuredFrom": measure[0] - start if start else 0.0,
        "drops": {
            "total": len(dropped),
            "byKind": dict(kinds),
            "byRoute": dict(Counter(d["route"] for d in dropped)),
            "events": [{**d, "t": d["t"] - start} for d in dropped[:EVENTS_KEPT]],
        },
        "routes": {
            r: {k: routes.get(r, {}).get(k) for k in ("packets", "changes")} for r in ROUTES
        },
        "output": {
            "lateCycles": last.lateCycles if last else None,
            "longestGapMs": last.longestGapMs if last else None,
        },
        "engine": engine,
        "restarts": restarts,
        "actions": [{**r, "t": r["t"] - start} for r in recovered],
        "rss": rss,
        "fuzz": load_counts,
        "loadNotes": readings.load.get("notes", []),
        "commands": {
            "errorLines": error_lines,
            "invalidSent": load_counts.get("consoleInvalid", 0),
            "unexpected": dict(list(unexpected.items())[:EVENTS_KEPT]),
        },
        "exitCode": readings.exitCode,
        "criteria": criteria,
        "warnings": [
            c["name"] + ": " + c["detail"] for c in criteria if not c["hard"] and not c["ok"]
        ],
    }


def criterion(name: str, ok: bool, detail: str, *, hard: bool = True) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "hard": hard, "detail": detail}


def write_json(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".new")
    temporary.write_text(json.dumps(data, indent=1) + "\n")
    temporary.replace(path)


def print_summary(report: dict[str, Any], path: Path) -> None:
    engine, drops_ = report["engine"], report["drops"]
    print(
        f"soak: {report['seconds']:.0f} s, chaos {report['chaos']}, "
        f"seed {report['seed']}, midi {report['midi']}"
    )
    print(f"  drops: {drops_['total']} {drops_['byKind'] or ''}")
    print(
        f"  engine: {engine['ticks']} ticks in {engine['processes']} processes, "
        f"{engine['overrunsOutsideOutages']} overruns outside outages "
        f"({engine['overrunRatio']:.3%}), longest tick {engine['longestTickMs']:.1f} ms, "
        f"longest GC pause {engine['longestGcPauseMs']:.1f} ms"
    )
    output = report["output"]
    print(
        f"  output: {output['lateCycles']} late cycles, longest gap {output['longestGapMs']:.1f} ms"
    )
    for action in report["actions"]:
        seconds = "never" if action["seconds"] is None else f"{action['seconds']:.1f} s"
        print(f"  {action['t']:8.1f} s  {action['action']:<12} recovered {seconds}")
    for role, rss in report["rss"].items():
        change = f"{rss['baselineMB']:.0f} → {rss['endMB']:.0f} MB"
        print(f"  rss {role}: {change} ({rss['slopeMBPerHour']:+.1f} MB/h)")
    commands = report["commands"]
    print(f"  console errors: {commands['errorLines']} (invalid sent {commands['invalidSent']})")
    for item in report["criteria"]:
        mark = "ok  " if item["ok"] else ("FAIL" if item["hard"] else "warn")
        print(f"  {mark} {item['name']}: {item['detail']}")
    print(f"soak: {report['result']} — {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The Phase 7 soak (phase-7-plan §5.25).")
    parser.add_argument("--hours", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--chaos", choices=sorted(CHAOS), default="standard")
    parser.add_argument(
        "--report", type=Path, help="the report file (default soak-<UTC>.json here)"
    )
    args = parser.parse_args(argv)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = (args.report or Path(f"soak-{stamp}.json")).resolve()
    config = Config(seconds=args.hours * 3600, seed=args.seed, chaos=args.chaos, report=report)
    result = Soak(config).run()
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
