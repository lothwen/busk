"""The options of ``busk run``, typed (phase-8-plan step 9).

:func:`~busk.process.console_host.add_run_arguments` declares them on the
command line, and :meth:`RunOptions.from_arguments` reads its parse. The
root (:class:`~busk.process.root.Root`), the console
(:func:`~busk.process.console_host.run_console`) and the threads backend
take a :class:`RunOptions`, never the parse itself.

The options cross into the console process as arguments, not as an object:
the root starts the console with the run's own argument list, which the
console parses again and turns into a :class:`RunOptions` of its own.

This is the CLI's plumbing, so it is internal (decision 19), not part of
busk's public API.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    import argparse


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

    @classmethod
    def from_arguments(cls, args: argparse.Namespace) -> Self:
        """The options in ``args``, a parse of the arguments that
        :func:`~busk.process.console_host.add_run_arguments` declares. Other
        attributes of ``args``, such as the subcommand or the console
        process's descriptors, are ignored."""
        values = {field.name: getattr(args, field.name) for field in fields(cls)}
        values["library"] = tuple(values["library"])
        return cls(**values)
