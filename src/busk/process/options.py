"""The options of ``busk run``, typed (phase-8-plan step 9).

:func:`add_run_arguments` declares them on the command line, and
:meth:`RunOptions.from_arguments` reads its parse. The root
(:class:`~busk.process.root.Root`), the console
(:func:`~busk.process.console_host.run_console`) and the threads backend
take a :class:`RunOptions`, never the parse itself. :func:`is_interactive`
says whether a run opens the interactive prompt.

It imports nothing of busk's, so that ``busk`` (:mod:`busk.launch`) can read
the options before the command line's imports.

The options cross into the console process as arguments, not as an object:
the root starts the console with the run's own argument list, which the
console parses again and turns into a :class:`RunOptions` of its own.

This is the CLI's plumbing, so it is internal (decision 19), not part of
busk's public API.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Final, Self


@dataclass(frozen=True, kw_only=True)
class RunOptions:
    """One run's options. Each field is the option of the same name (with
    ``-`` for ``_``), and has its default."""

    show: Path
    """The show file: a ``.show`` or ``.json``."""
    values: Path | None = None
    """``--values``: logical values for the slots no playback controls."""
    duration: float | None = None
    """``--duration``: stop after this many seconds (positive), instead of
    waiting for Ctrl+C or ``quit``."""
    console: bool = False
    """``--console``: also print each universe to stdout when its bytes change."""
    script: Path | None = None
    """``--script``: run the console commands of this file first."""
    no_console: bool = False
    """``--no-console``: read no console commands."""
    iface: str = "eth0"
    """``--iface``: the interface of new multicast and broadcast routes."""
    state_dir: Path | None = None
    """``--state-dir``: busk's state directory (``None``: the default one)."""
    library: tuple[Path, ...] = ()
    """``--library``: more directories of fixture profiles, in order."""
    no_recover: bool = False
    """``--no-recover``: ignore the last run's crash state."""
    threads: bool = False
    """``--threads``: run the engine and the output as threads of one process."""
    stats: Path | None = None
    """``--stats``: append the processes' statistics to this file."""
    no_log: bool = False
    """``--no-log``: write no event log."""
    frontend: str | None = None
    """``--frontend``: ``MODULE:FUNCTION``, which the console process calls
    with the show instead of opening its prompt."""

    @classmethod
    def from_arguments(cls, args: argparse.Namespace) -> Self:
        """The options in ``args``, a parse of the arguments that
        :func:`add_run_arguments` declares. Other
        attributes of ``args``, such as the subcommand or the console
        process's descriptors, are ignored."""
        values = {field.name: getattr(args, field.name) for field in fields(cls)}
        values["library"] = tuple(values["library"])
        return cls(**values)


def add_run_arguments(run: argparse.ArgumentParser) -> None:
    """The options of ``busk run`` (also parsed by the console process,
    which the root starts with the same arguments)."""
    run.add_argument("show", type=Path, help="path to a .show or .json show file")
    run.add_argument(
        "--values",
        type=Path,
        metavar="FILE",
        help="logical values for slots no playback controls: a JSON list of park-style entries",
    )
    run.add_argument(
        "--duration",
        type=_positive_seconds,
        metavar="SECONDS",
        help="stop after this many seconds instead of waiting for Ctrl+C or quit",
    )
    run.add_argument(
        "--console",
        action="store_true",
        help="also print each universe to stdout when its bytes change",
    )
    run.add_argument(
        "--script", type=Path, metavar="FILE", help="run console commands from FILE first"
    )
    run.add_argument("--no-console", action="store_true", help="read no console commands")
    run.add_argument(
        "--iface", default="eth0", metavar="IF", help="interface for new multicast/broadcast routes"
    )
    run.add_argument("--state-dir", type=Path, metavar="D", help="busk's state directory")
    run.add_argument(
        "--library",
        type=Path,
        action="append",
        default=[],
        metavar="D",
        help="another directory of fixture profiles (repeatable)",
    )
    run.add_argument("--no-recover", action="store_true", help="ignore the last run's crash state")
    run.add_argument(
        "--threads",
        action="store_true",
        help="run the engine and the output as threads of one process (no watchdog)",
    )
    run.add_argument(
        "--stats",
        type=Path,
        metavar="FILE",
        help="append the processes' statistics to FILE as one JSON line per second",
    )
    run.add_argument(
        "--no-log", action="store_true", help="write no event log (<stateDir>/logs, busk replay)"
    )
    run.add_argument(
        "--frontend",
        type=_frontend_name,
        metavar="MODULE:FUNCTION",
        help="call FUNCTION(show) of MODULE instead of opening the prompt; the run ends "
        "when it returns",
    )


FRONTEND_CLASHES: Final = ("console", "no_console", "duration")
"""The options ``--frontend`` cannot be combined with: a frontend owns the
terminal and the commands, and ends the run when it returns."""


def _frontend_name(text: str) -> str:
    module, colon, function = text.partition(":")
    if not (module and colon and function):
        raise argparse.ArgumentTypeError(f"expected MODULE:FUNCTION: {text!r}")
    return text


def _positive_seconds(text: str) -> float:
    try:
        seconds = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if not seconds > 0:  # also rejects NaN
        raise argparse.ArgumentTypeError(f"must be positive: {text!r}")
    return seconds


def is_interactive(options: RunOptions) -> bool:
    """Whether a run with ``options`` opens the interactive prompt: the
    console reads commands, there is no ``--duration``, and stdin is a
    terminal. (``--console`` frame lines are off at a prompt.)"""
    if options.no_console or options.duration is not None:
        return False
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError, OSError):
        return False
