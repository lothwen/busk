"""The event log and ``busk replay`` (phase-7-plan §5.21, §6 step 17).

A :class:`LoggedRun` is ``busk run --threads`` inside the test: an engine on
a fake clock with its event log on, a session that puts causes on its
installs, and the operator console. It ticks on an irregular schedule and
keeps every frame it made, so replay can be held to them byte for byte.
"""

from __future__ import annotations

import json
import os
import random
import signal
import socket
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from builders import DEMO, load_doc, offline
from busk.cli import main
from busk.compiler.compile import compile_show
from busk.console.console import Console
from busk.engine.clock import FakeClock
from busk.engine.loop import RECORDS_MAX, Engine
from busk.engine.snapshot import Restore
from busk.model.show import Show
from busk.persistence.eventlog import (
    EventLog,
    LogPump,
    Record,
    encode,
    read_log,
    snapshot_from_json,
    snapshot_json,
    start_show_id,
    take,
)
from busk.persistence.show_file import new_show
from busk.process.links import start_log
from busk.replay import Replayer, ReplayError
from busk.session.ids import CounterIds
from busk.session.library import ProfileLibrary
from busk.session.session import Session
from process_harness import BuskRun

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [ROOT / "tests" / "fixtures" / f"{name}.busk" for name in ("phase3-build", "phase4-song")]
EFFECTS = ROOT / "tests" / "fixtures" / "phase5-effects.busk"
NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
CID = "0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f"
STEPS = (0.003, 0.0137, 0.021, 0.05, 0.25, 0.9)
"""The irregular tick intervals the runs pick from."""


class LoggedRun:
    """``busk run --threads`` in one test (see the module docs)."""

    def __init__(self, show: Show, *, seed: int = 17) -> None:
        compiled = compile_show(show)
        self.engine = Engine(compiled, FakeClock())
        self.records = start_log(self.engine, show)
        self.session = Session(
            show,
            self.engine.bus,
            compiled=compiled,
            ids=CounterIds(),
            causes=True,
            engine_state=lambda: self.engine.snapshot,
        )
        self.console = Console(self.session, ProfileLibrary())
        self._random = random.Random(seed)
        self.t = 100.0
        self.frames: dict[float, tuple[bytes, ...]] = {}
        """Every live frame, by its tick time."""

    def tick(self, count: int = 1) -> None:
        for _ in range(count):
            self.t += self._random.choice(STEPS)
            self.engine.tick(self.t)
            assert self.engine.latest is not None
            self.frames[self.t] = self.engine.latest.universes

    def run(self, *lines: str) -> None:
        """Execute console lines (each must succeed), 0–2 ticks after each:
        several lines often land in one tick."""
        for line in lines:
            reply = self.console.execute(line)
            assert reply.ok, (line, reply.text)
            self.tick(self._random.randint(0, 2))

    def script(self, path: Path) -> None:
        self.run(*(line for line in path.read_text().splitlines() if line.strip() != "save"))

    def write(self, logs: Path) -> Path:
        """Write the records so far with a real :class:`EventLog`; its file."""
        log = EventLog(logs, wall_clock=lambda: NOW)
        for t, item in take(self.records):
            log.add(t, item)
        log.close()
        assert log.path is not None
        return log.path


def empty_show() -> Show:
    return new_show("Club Night", ids=CounterIds(), now=NOW, cid=CID)


def perform(run: LoggedRun) -> None:
    """The scenario: the Phase 3–5 builds (show edits with generated ids),
    then performance, programmer changes (GAP-05's relative ones and
    GAP-14's stopped effect too), undo and redo, and a restore."""
    run.tick()
    for script in SCRIPTS:
        run.script(script)
    early = run.engine.snapshot
    run.script(EFFECTS)
    run.run("fader 1 1", "go 9", "fader 9 1")
    run.tick(3)
    run.run("go 9", "sel playback 9", "fade 0.5", "set intensity 0.4", "set intensity by -10%")
    run.tick(4)
    run.run("sel group 2", "set color 1 0 0", "set color.g by 50%", 'effect add "Pulse" size 0.5',
            "highlight on")  # fmt: skip
    pulse = run.session.programmer.effects[-1]["id"]
    run.tick(2)
    run.run(f"effect stop {pulse}", "sel + group 1", "highlight off", "blind on", "set pan 30",
            "blind off", f"effect run {pulse}")  # fmt: skip
    run.run("record cue 10/7", "undo", "undo", "redo", "go 10", "fader 10 1")
    run.tick(3)
    run.run("gm 0.6", "blackout on", "release 1 0.4")
    run.tick(2)
    run.run("blackout off", "clear", "undo", "release all 1")
    assert early is not None
    run.engine.bus.restore(Restore(snapshot=early))  # as after an engine restart
    run.tick(2)
    run.run("go 9", "sel group 3", "set intensity 1")
    run.tick(6)


@pytest.fixture(scope="module")
def performed() -> LoggedRun:
    run = LoggedRun(empty_show())
    perform(run)
    return run


@pytest.fixture(scope="module")
def log_file(performed: LoggedRun, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The scenario's log, written once (writing takes the records)."""
    return performed.write(tmp_path_factory.mktemp("eventlog") / "logs")


def records_of(path: Path) -> list[Record]:
    return list(read_log([path]))


# ------------------------------------------------------------------ replay


def test_a_logged_run_replays_byte_identically_at_every_logged_time(
    performed: LoggedRun, log_file: Path
) -> None:
    records = records_of(log_file)
    assert records[0].kind == "start"
    assert {record.kind for record in records} == {"start", "c", "e", "p", "programmer", "r"}
    ticks = list(Replayer().run(records))
    assert len(ticks) > 50  # ticks with records
    assert [tick.t for tick in ticks] == sorted({record.t for record in records})
    for tick in ticks:
        assert tick.frame.universes == performed.frames[tick.t], tick.t
    assert sum(len(tick.records) for tick in ticks) == len(records)


def test_ticks_between_the_logged_times_match_too(performed: LoggedRun, log_file: Path) -> None:
    """The engine does not depend on its tick schedule: replay at every
    live tick time (``--at``) gives every live frame."""
    ticks = list(Replayer().run(records_of(log_file), at=performed.frames))
    assert [tick.t for tick in ticks] == sorted(performed.frames)
    for tick in ticks:
        assert tick.frame.universes == performed.frames[tick.t], tick.t


def test_until_stops_at_a_time(performed: LoggedRun, log_file: Path) -> None:
    records = records_of(log_file)
    middle = records[len(records) // 2].t
    ticks = list(Replayer().run(records, until=middle))
    assert ticks[-1].t == middle
    assert ticks[-1].frame.universes == performed.frames[middle]


def test_busk_replay_prints_the_records_and_writes_the_frames(
    performed: LoggedRun, log_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "frames.json"
    assert main(["replay", str(log_file), "--frames", str(out)]) == 0
    printed = capsys.readouterr().out.splitlines()
    records = records_of(log_file)
    assert len(printed) == len(records) + 1
    assert printed[0].endswith("start  'Club Night', fresh engine")
    assert any(line.endswith("e      added universe 'Stage'") for line in printed)
    assert printed[-1].startswith(f"replayed {len(records)} record(s) in ")
    frames = json.loads(out.read_text())["frames"]
    assert len(frames) == len({record.t for record in records})
    for frame in frames:
        live = performed.frames[frame["t"]]
        assert list(frame["universes"].values()) == [data.hex() for data in live]


def test_a_log_must_begin_with_a_start(
    log_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tail = tmp_path / "tail.log"
    tail.write_bytes(b"".join(log_file.read_bytes().splitlines(keepends=True)[1:]))
    with pytest.raises(ReplayError, match="does not begin with a 'start' record"):
        list(Replayer().run(read_log([tail])))
    assert main(["replay", str(tail)]) == 1
    assert "does not begin with a 'start' record" in capsys.readouterr().err


def test_a_selection_rides_on_the_next_install() -> None:
    """A programmer change that installs nothing (a selection) is logged
    with the next install, before its own cause; ``sel playback`` as the
    ``SELECT`` it resolved to."""
    run = LoggedRun(empty_show())
    run.script(SCRIPTS[0])
    take(run.records)
    run.run("sel playback 1", "sel group 1", "set intensity 0.5")
    run.tick()
    kinds = [(record.kind, record.body.get("type")) for record in log_records(run)]
    assert kinds == [("p", "SELECT"), ("p", "SELECT"), ("p", "SET_ATTRIBUTE")]


def log_records(run: LoggedRun) -> list[Record]:
    """The records ``run`` holds now, read back as a file would be."""
    lines = b"".join(encode(t, item) for t, item in take(run.records))
    records = []
    for number, line in enumerate(lines.splitlines(), 1):
        data: dict[str, Any] = json.loads(line)
        t = data.pop("t")
        ((kind, body),) = data.items()
        records.append(Record(t=t, kind=kind, body=body, line=number))
    return records


def test_select_playback_is_logged_as_the_targets_it_selected() -> None:
    run = LoggedRun(empty_show())
    run.script(SCRIPTS[0])
    take(run.records)
    run.run("sel playback 1", "set intensity 0.5")
    run.tick()
    select = log_records(run)[0].body
    assert select["type"] == "SELECT"
    assert select["mode"] == "replace"
    assert select["targets"]["kind"] == "targets"
    assert [dict(t) for t in run.session.programmer.selection] == select["targets"]["refs"]


# ------------------------------------------------------------------- files


def test_rotation_keeps_the_newest_files(tmp_path: Path) -> None:
    run = LoggedRun(empty_show())
    run.script(SCRIPTS[0])
    stamps = iter(datetime(2026, 10, 16, 12, 0, second, tzinfo=UTC) for second in range(60))
    opened: list[Path] = []
    log = EventLog(
        tmp_path / "logs",
        max_bytes=4096,
        keep=3,
        wall_clock=lambda: next(stamps),
        opened=opened.append,
    )
    records = take(run.records)
    for t, item in records:
        log.add(t, item)
    log.close()
    assert len(opened) > 4
    directory = opened[0].parent
    assert directory == tmp_path / "logs" / run.session.show["meta"]["id"]
    assert sorted(directory.iterdir()) == opened[-3:]  # the newest three
    for previous, path in zip(opened[-4:-1], opened[-3:], strict=True):
        first = json.loads(path.read_text().splitlines()[0])
        assert first["rotated"] == previous.name
    lines = [line for path in opened[-3:] for line in path.read_bytes().splitlines()]
    assert all(len(path.read_bytes()) <= 4096 for path in opened[-3:-1])
    assert lines[-1] == encode(*records[-1]).rstrip(b"\n")


def test_the_start_cause_names_its_show() -> None:
    run = LoggedRun(empty_show())
    run.tick()
    ((_, start),) = take(run.records)
    assert isinstance(start, bytes)
    assert start_show_id(start) == run.session.show["meta"]["id"]
    assert start_show_id(b'{"p":{"type":"SELECT"}}') is None


def test_a_restore_snapshot_survives_json(performed: LoggedRun) -> None:
    snapshot = performed.engine.snapshot
    assert snapshot is not None
    assert snapshot_from_json(json.loads(json.dumps(snapshot_json(snapshot)))) == snapshot


# ------------------------------------------------------------- real time


def test_the_tick_does_no_io(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A writer that fails costs the engine nothing: the same frames, no
    tick errors; the records are counted lost."""
    plain = LoggedRun(empty_show())
    plain.engine.records = None
    perform(plain)

    def fail(self: EventLog, line: bytes) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(EventLog, "_write", fail)
    failing = LoggedRun(empty_show())
    pump = LogPump(failing.records, EventLog(tmp_path / "logs"))
    pump.start()
    perform(failing)
    pump.stop()
    assert failing.frames == plain.frames
    assert failing.engine.stats.tickErrors == 0
    assert pump.log.lost > 0
    assert not failing.records


def test_a_full_record_deque_drops_and_counts() -> None:
    run = LoggedRun(empty_show())
    run.records.extend((0.0, b"{}") for _ in range(RECORDS_MAX))
    run.engine.bus.submit({"type": "BLACKOUT", "on": True})
    run.tick()
    assert run.engine.stats.logDropped == 2  # the start and the command
    assert len(run.records) == RECORDS_MAX


# --------------------------------------------------------------------- CLI


def test_threads_runs_write_a_log_and_no_log_writes_none(
    tmp_path: Path, state_directory: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    show = tmp_path / "demo.json"
    show.write_text(json.dumps(offline(load_doc(DEMO))))
    assert main(["run", "--threads", str(show), "--duration", "0.2", "--no-log"]) == 0
    assert not (state_directory / "logs").exists()
    assert main(["run", "--threads", str(show), "--duration", "0.2"]) == 0
    (path,) = (state_directory / "logs").glob("*/*.log")
    records = records_of(path)
    assert records[0].kind == "start"
    assert records[0].body["connect"] == "fresh"
    capsys.readouterr()
    assert main(["replay", str(path)]) == 0


def log_path(state_directory: Path) -> Path:
    """The one log file of a run."""
    (path,) = (state_directory / "logs").glob("*/*.log")
    return path


def info_until(run: BuskRun, wanted: Callable[[str], bool], timeout: float = 20.0) -> str:
    """Type ``info`` every 0.3 s until a new line matches ``wanted``."""
    deadline = time.monotonic() + timeout
    while True:
        since = run.mark()
        run.send("info\n")
        try:
            return run.wait_for(wanted, since=since, timeout=0.3)
        except TimeoutError:
            if time.monotonic() > deadline:
                raise


@pytest.mark.skipif(
    not hasattr(socket, "send_fds") or not Path("/proc").is_dir(),
    reason="the process tree needs descriptor passing, the harness /proc",
)
def test_a_process_run_writes_start_lines_and_records(
    tmp_path: Path, state_directory: Path
) -> None:
    show = tmp_path / "demo.json"
    show.write_text(json.dumps(offline(load_doc(DEMO))))
    with BuskRun(show) as run:
        info_until(run, lambda line: line.startswith("event log: /"))
        run.send("sel fixture 101\nset intensity 0.5\nblackout on\nblackout off\n")
        run.status_until("GM 100% | BO off")
        info_until(run, lambda line: line == f"event log: {log_path(state_directory)}")
        run.close_stdin()
        assert run.wait() == 0
    path = log_path(state_directory)
    records = records_of(path)
    assert records[0].kind == "start"
    assert records[0].body["connect"] == "fresh"
    kinds = [record.kind for record in records]
    assert "p" in kinds
    assert kinds.count("c") >= 2
    assert all(isinstance(record.body, dict) for record in records)
    assert list(Replayer().run(records))


@pytest.mark.skipif(
    not hasattr(socket, "send_fds") or not Path("/proc").is_dir(),
    reason="the process tree needs descriptor passing, the harness /proc",
)
def test_an_engine_restart_writes_a_second_start_and_the_restore(
    tmp_path: Path, state_directory: Path
) -> None:
    show = tmp_path / "demo.json"
    show.write_text(json.dumps(offline(load_doc(DEMO))))
    with BuskRun(show) as run:
        pids = run.children()
        info_until(run, lambda line: line.startswith("event log: /"))
        run.send("sel fixture 101\nset intensity 0.5\nblackout on\n")
        run.status_until("GM 100% | BO on")
        os.kill(pids["engine"], signal.SIGKILL)
        run.wait_for(lambda line: "engine back" in line, timeout=20)
        run.send("set intensity 0.25\n")
        info_until(run, lambda line: line == "restarts: engine 1, console 0")
        run.send("quit\n")
        assert run.wait() == 0, run.err
    records = records_of(log_path(state_directory))
    starts = [record for record in records if record.kind == "start"]
    assert [start.body["connect"] for start in starts] == ["fresh", "fresh"]
    after = records[records.index(starts[1]) :]
    assert "r" in [record.kind for record in after]  # the look restored into the new engine
    second = starts[1].body["programmer"]
    assert second["values"]  # the programmer the console re-sent
    assert list(Replayer().run(records))


@pytest.mark.skipif(
    not hasattr(socket, "send_fds") or not Path("/proc").is_dir(),
    reason="the process tree needs descriptor passing, the harness /proc",
)
def test_a_console_restart_writes_a_start_on_the_running_engine(
    tmp_path: Path, state_directory: Path
) -> None:
    show = tmp_path / "demo.json"
    show.write_text(json.dumps(offline(load_doc(DEMO))))
    with BuskRun(show) as run:
        console = run.children()["console"]
        info_until(run, lambda line: line.startswith("event log: /"))
        run.send("sel fixture 101\nset intensity 0.5\nblackout on\n")
        run.status_until("GM 100% | BO on")
        time.sleep(1.2)  # session.json has the programmer
        since = run.mark()
        os.kill(console, signal.SIGKILL)
        run.wait_for(lambda line: line.startswith("busk console: restarted"), since=since)
        run.send("set intensity 0.25\nblackout off\n")
        run.status_until("GM 100% | BO off")
        run.send("quit\n")
        assert run.wait() == 0, run.err
    records = records_of(log_path(state_directory))
    starts = [record for record in records if record.kind == "start"]
    assert starts[0].body["connect"] == "fresh"
    assert starts[1].body["connect"] in ("kept", "replaced")  # the engine ran on
    assert list(Replayer().run(records))
