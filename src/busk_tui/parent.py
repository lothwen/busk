"""``busk-tui``'s parent process (file-menu plan D3, calls 9 and 11): it
starts ``busk run`` on one show after another.

``busk-tui SHOW`` stays as this parent instead of replacing itself with
``busk run``:

* it makes a private temporary folder and sets :data:`NEXT`
  (``BUSK_TUI_NEXT``) to ``<folder>/next.json`` for the run; the environment
  reaches the console process, where the TUI runs;
* to change shows, the TUI writes ``{"open": "<absolute path>"}`` there
  (:func:`hand_off`) and quits, and the run ends;
* the parent reads the file, deletes it, and starts the next run on that
  show (:func:`run`). Without the file, or after a run that did not end
  with 0, it exits with the run's code;
* to close the show (file-menu plan call 25), the TUI writes
  ``{"close": true}`` instead, and :func:`run` returns :data:`CLOSE`, for
  ``busk-tui`` to run the launcher, then :func:`run` again on the show
  chosen there.

While a run goes, the parent ignores SIGINT: the TUI reads Ctrl+C as a key,
and a run that is not full-screen yet takes it itself. (A handler that does
nothing, not ``SIG_IGN``, which the run would inherit.) It passes SIGTERM
and SIGHUP on to the run, waits for it, and then starts nothing more.
``busk run`` takes a second one as the first, so a hang-up that reached both
processes, and is passed on, is harmless. It exits with the run's code, or
128 + N when a signal N killed the run.

It imports neither busk nor Textual.
"""

from __future__ import annotations

import contextlib
import enum
import json
import os
import signal
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from types import FrameType
from typing import Final, Protocol

NEXT: Final = "BUSK_TUI_NEXT"
"""The variable that names the file the TUI hands the next show over in."""

PASSED_ON: Final = (signal.SIGTERM, signal.SIGHUP)


class Close(enum.Enum):
    """The launcher, handed over in place of a show."""

    CLOSE = "close"


CLOSE: Final = Close.CLOSE
"""What the TUI hands over to close the show, and what :func:`run` returns then."""


class Run(Protocol):
    """A ``busk run`` started: a :class:`subprocess.Popen`, or a test's fake."""

    def wait(self) -> int: ...

    def send_signal(self, number: int) -> None: ...


type Start = Callable[[list[str], dict[str, str]], Run]
"""Starts a command with an environment."""


def popen(command: list[str], environment: dict[str, str]) -> Run:
    return subprocess.Popen(command, env=environment)


def run(
    first: list[str],
    then: Callable[[Path], list[str]],
    environment: Mapping[str, str],
    start: Start = popen,
) -> int | Close:
    """Run ``first``, the ``busk run`` of the show given, then ``then(show)``
    for each show the TUI hands over; return the last run's exit code, or
    128 + N if a signal N killed it, or :data:`CLOSE` after a run that
    closed its show and ended with 0 (see the module docs). Main thread only:
    it sets signal handlers, and puts the old ones back when it returns."""
    stopping: list[int] = []  # the signals passed on: nothing more starts
    running: list[Run] = []

    def pass_on(number: int, frame: FrameType | None) -> None:
        stopping.append(number)
        for child in running:
            with contextlib.suppress(ProcessLookupError):
                child.send_signal(number)

    previous = {number: signal.signal(number, pass_on) for number in PASSED_ON}
    previous[signal.SIGINT] = signal.signal(signal.SIGINT, _ignore)
    try:
        with tempfile.TemporaryDirectory(prefix="busk-tui-", ignore_cleanup_errors=True) as folder:
            next_file = Path(folder) / "next.json"
            given = {**environment, NEXT: str(next_file)}
            command = first
            while True:
                child = start(command, given)
                running.append(child)
                if stopping:  # it came while the run started
                    with contextlib.suppress(ProcessLookupError):
                        child.send_signal(stopping[-1])
                code = child.wait()
                running.clear()
                show = read_next(next_file)
                if show is None or code != 0 or stopping:
                    return 128 - code if code < 0 else code
                if show is CLOSE:
                    return CLOSE
                command = then(show)
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def _ignore(number: int, frame: FrameType | None) -> None:
    pass


def read_next(file: Path) -> Path | Close | None:
    """The show the TUI handed over in ``file``, which is deleted, or
    :data:`CLOSE`; ``None`` if there is none, or it cannot be read."""
    try:
        text = file.read_text(encoding="utf-8")
    except OSError:
        return None
    with contextlib.suppress(OSError):
        file.unlink()
    try:
        given = json.loads(text)
    except ValueError:
        return None
    if not isinstance(given, dict):
        return None
    if given.get("close") is True:
        return CLOSE
    show = given.get("open")
    return Path(show) if isinstance(show, str) and show else None


def hand_off(show: Path | Close, environ: Mapping[str, str] | None = None) -> bool:
    """Ask the parent to start ``show`` (an absolute path) once this run
    ends, or the launcher (:data:`CLOSE`): ``{"open": …}`` or ``{"close":
    true}`` in :data:`NEXT`'s file, written whole. ``False`` without a
    parent, or if it cannot be written."""
    target = (os.environ if environ is None else environ).get(NEXT)
    if not target:
        return False
    file = Path(target)
    temporary = file.with_name(file.name + ".tmp")
    try:
        given = {"close": True} if show is CLOSE else {"open": str(show)}
        temporary.write_text(json.dumps(given), encoding="utf-8")
        temporary.replace(file)
    except OSError:
        return False
    return True
