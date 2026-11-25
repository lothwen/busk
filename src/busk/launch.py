"""The ``busk`` command, and ``python -m busk``: busk's banner, then the
command line (:mod:`busk.cli`).

Before an interactive ``busk run`` (the console reads commands from a
terminal, stdout is one, and no ``--frontend``), it starts busk's banner
(:func:`busk.banner.play_banner`), and only then imports the command line,
which takes about a second. The banner plays on a thread of its own while
busk imports, starts its processes and loads the show, and nothing waits for
it: the first line any of them prints brings it to rest, its last frame
drawn at once. Ctrl+C before the run starts ends it with 130.

It imports nothing heavy before the banner: :mod:`busk.process.options`
reads the options as the command line does.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import NoReturn

from busk.banner import play_banner
from busk.process.options import RunOptions, add_run_arguments, is_interactive


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line with ``argv`` (default: ``sys.argv[1:]``), the
    banner playing meanwhile where it belongs; return the exit code."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    finish = play_banner() if prompts(arguments) else None
    try:
        from busk.cli import main as command_line

        return command_line(arguments)
    except KeyboardInterrupt:
        if finish is None:
            raise
        return 130  # before the run started, which takes Ctrl+C from there on
    finally:
        if finish is not None:
            finish()


def prompts(argv: Sequence[str]) -> bool:
    """Whether ``argv`` runs a show at the interactive prompt on a terminal:
    ``busk run``, its console reading commands from a terminal, stdout one,
    and no ``--frontend``. Arguments the command line would refuse, or
    ``--help``, are not."""
    if not argv or argv[0] != "run":  # only --version may come before it, and runs nothing
        return False
    parser = _Quiet(add_help=False)
    add_run_arguments(parser)
    try:
        args, unknown = parser.parse_known_args(argv[1:])
    except _Refused:
        return False
    if unknown:
        return False
    options = RunOptions.from_arguments(args)
    return options.frontend is None and is_interactive(options) and sys.stdout.isatty()


class _Refused(Exception):
    """Arguments the command line refuses: it says why, not :func:`prompts`."""


class _Quiet(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _Refused(message)
