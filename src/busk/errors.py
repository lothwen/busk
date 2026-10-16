"""The base of busk's public errors (phase-8-plan §5.8).

Every exception that a public call raises on purpose is a
:class:`BuskError`, so a caller can catch them all at once::

    BuskError(Exception)
    ├── ShowLoadError       .issues     (busk.persistence.show_file)
    ├── UnsupportedFeature              (busk.compiler.compile)
    ├── ImportFailed        also a ValueError (busk.importers)
    └── ScriptError         .path .line .text .output

The first three live next to the code that raises them, and keep the names,
modules and attributes they had before Phase 8. :class:`OSError` (a file
that cannot be read or written) passes through untouched, and wrong
arguments raise :class:`ValueError` or :class:`TypeError`, never a
:class:`BuskError`.

This module imports nothing from busk, so any module can import it.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["BuskError", "ScriptError"]


class BuskError(Exception):
    """The base of every error busk's public API raises on purpose."""


class ScriptError(BuskError):
    """A console script stopped at its first failing line.

    :attr:`path` is the script, :attr:`line` the failing line's number (from
    1) and :attr:`text` that line as written. :attr:`output` holds the lines
    the script wrote up to and including the failure, the console's error
    reply last. ``str()`` gives ``path:line: text``, as ``busk run --script``
    prints it.
    """

    def __init__(self, path: Path, line: int, text: str, output: list[str]) -> None:
        super().__init__(f"{path}:{line}: {text}")
        self.path = path
        self.line = line
        self.text = text
        self.output = output
