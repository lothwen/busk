"""Real ``busk run`` process trees for the Phase 7 process tests (phase-7-plan §6 step 8).

:class:`BuskRun` starts ``python -m busk run SHOW …`` with piped stdin,
stdout and stderr, collects the output lines as they come (so a test can
wait for one while the run goes on), finds the root's engine and console
children in ``/proc``, and kills whatever is left when it closes.

With ``sacn_port``, every process of the tree sends its sACN routes to that
port (``tests/process_site/sitecustomize.py``), so a localhost receiver
gets them, as the in-process ``receiver`` fixture arranges with
``monkeypatch``. With ``midi_ports``, every process sees that MIDI input
port list instead of the machine's. A :class:`Collector` timestamps what
the receiver gets.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO, Self

from sacn_receiver import DataPacket, Receiver

SITE = Path(__file__).parent / "process_site"
"""The directory of the tests' ``sitecustomize.py``."""

ROLES = {"busk.process.engine_host": "engine", "busk.process.console_host": "console"}
"""The module each child runs → its role."""


class BuskRun:
    """One ``busk run`` process tree (see the module docs)."""

    def __init__(
        self,
        show: Path,
        *args: str,
        sacn_port: int | None = None,
        midi_ports: list[str] | None = None,
    ) -> None:
        paths = [str(SITE), os.environ.get("PYTHONPATH", "")]
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in paths if p)}
        if sacn_port is not None:
            env["BUSK_TEST_SACN_PORT"] = str(sacn_port)
        if midi_ports is not None:
            env["BUSK_TEST_MIDI_PORTS"] = json.dumps(midi_ports)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "busk", "run", str(show), *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self.out: list[str] = []
        """stdout lines so far (without their newlines)."""
        self.err: list[str] = []
        """stderr lines so far."""
        self._seen: set[int] = set()  # every child pid found, for the clean-up
        self._changed = threading.Condition()
        assert self.process.stdout is not None
        assert self.process.stderr is not None
        self._readers = [
            threading.Thread(target=self._collect, args=(stream, lines), daemon=True)
            for stream, lines in ((self.process.stdout, self.out), (self.process.stderr, self.err))
        ]
        for reader in self._readers:
            reader.start()

    @property
    def pid(self) -> int:
        """The root's process id."""
        return self.process.pid

    def send(self, text: str) -> None:
        """Type ``text`` on the console's stdin."""
        assert self.process.stdin is not None
        self.process.stdin.write(text)
        self.process.stdin.flush()

    def close_stdin(self) -> None:
        """End the console's stdin (which quits a run without ``--duration``)."""
        assert self.process.stdin is not None
        with contextlib.suppress(BrokenPipeError):
            self.process.stdin.close()

    def mark(self) -> int:
        """How many stdout lines there are now (for ``wait_for(since=…)``)."""
        with self._changed:
            return len(self.out)

    def wait_for(
        self,
        wanted: str | Callable[[str], bool],
        *,
        stderr: bool = False,
        since: int = 0,
        timeout: float = 20.0,
    ) -> str:
        """The first line (of stdout from line ``since`` on, or of stderr) equal
        to ``wanted`` or for which it is true; :class:`TimeoutError` after
        ``timeout`` seconds."""
        test = wanted if callable(wanted) else (lambda line: line == wanted)
        lines = self.err if stderr else self.out
        deadline = time.monotonic() + timeout
        with self._changed:
            while True:
                for line in lines[0 if stderr else since :]:
                    if test(line):
                        return line
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"no line {wanted!r}; stdout {self.out}, stderr {self.err}")
                self._changed.wait(remaining)

    def status_until(self, wanted: str | Callable[[str], bool], timeout: float = 20.0) -> str:
        """Type ``status`` every 0.2 s until a new status line matches ``wanted``."""
        deadline = time.monotonic() + timeout
        while True:
            since = self.mark()
            self.send("status\n")
            try:
                return self.wait_for(wanted, since=since, timeout=0.2)
            except TimeoutError:
                if time.monotonic() > deadline:
                    raise

    def children(self, timeout: float = 20.0, *, besides: int | None = None) -> dict[str, int]:
        """The live engine's and console's process ids (``{"engine": …,
        "console": …}``), once both run; with ``besides``, once neither is
        that process (a restarted engine or console)."""
        deadline = time.monotonic() + timeout
        while True:
            found = {}
            for pid in _children(self.pid):
                if (role := _role(pid)) is not None:
                    found[role] = pid
                    self._seen.add(pid)
            if len(found) == len(ROLES) and besides not in found.values():
                return found
            if time.monotonic() > deadline:
                raise TimeoutError(f"children of {self.pid}: {found}")
            time.sleep(0.02)

    def wait(self, timeout: float = 30.0) -> int:
        """Wait for the root to exit and for its output to be read; its exit code."""
        code = self.process.wait(timeout)
        for reader in self._readers:
            reader.join(timeout)
        return code

    def signal(self, number: int) -> None:
        """Send signal ``number`` to the root."""
        self.process.send_signal(number)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        """Kill whatever of the tree still runs."""
        for pid in [*self._seen, *_children(self.pid)]:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()

    def _collect(self, stream: IO[str], lines: list[str]) -> None:
        for line in stream:
            with self._changed:
                lines.append(line.rstrip("\n"))
                self._changed.notify_all()


class Collector:
    """Every packet a receiver gets, with its arrival time, on a thread."""

    def __init__(self, receiver: Receiver) -> None:
        self._receiver = receiver
        self.packets: list[tuple[float, DataPacket]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                packet = self._receiver.receive(0.1)
            except TimeoutError:
                continue
            self.packets.append((time.monotonic(), packet))

    def latest(self) -> bytes:
        return self.packets[-1][1].data

    def settle(self, quiet: float = 0.5, timeout: float = 10.0) -> bytes:
        """The data once it has not changed for ``quiet`` seconds."""
        deadline = time.monotonic() + timeout
        while True:
            data, since = self.latest(), time.monotonic()
            while time.monotonic() - since < quiet:
                time.sleep(0.05)
                if self.latest() != data:
                    break
            else:
                return data
            assert time.monotonic() < deadline, "the frames never settle"

    def stop(self) -> list[tuple[float, DataPacket]]:
        self._stop.set()
        self._thread.join()
        return self.packets


def alive(pid: int) -> bool:
    """Whether process ``pid`` exists and is not a zombie."""
    state = _stat(pid)
    return state is not None and state[0] != "Z"


def wait_gone(pids: list[int], timeout: float) -> bool:
    """Whether every process in ``pids`` is gone within ``timeout`` seconds."""
    deadline = time.monotonic() + timeout
    while any(alive(pid) for pid in pids):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def _stat(pid: int) -> list[str] | None:
    """The fields of ``/proc/<pid>/stat`` after the command name (state, ppid, …)."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return text.rsplit(")", 1)[1].split()


def _children(parent: int) -> list[int]:
    """The live processes whose parent is ``parent``."""
    found = []
    for entry in os.listdir("/proc"):
        fields = _stat(int(entry)) if entry.isdigit() else None
        if fields is not None and int(fields[1]) == parent and fields[0] != "Z":
            found.append(int(entry))
    return found


def _role(pid: int) -> str | None:
    """``engine`` or ``console`` from the module the process runs."""
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return None
    for module, role in ROLES.items():
        if module.encode() in argv:
            return role
    return None
