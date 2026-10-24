"""busk-tui — a terminal UI for busk.

The TUI runs a show under ``busk run`` (``busk-tui SHOW``) or by itself
(``busk-tui --standalone SHOW``), and does everything through the engine's
console lines: every click is the line it runs, echoed in the log. Its user
guide is ``docs/tui/guide.md``, its plan ``docs/dev/tui/implementation-plan.md``.

Only :mod:`busk_tui.bridge` imports ``busk``; this package's other modules
see the engine through the bridge's view models (:mod:`busk_tui.model`).
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("busk")
except PackageNotFoundError:  # a source tree that was never installed
    __version__ = "0+unknown"
