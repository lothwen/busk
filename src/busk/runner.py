"""Running a show from Python (phase-8-plan §5.4–§5.5).

:class:`OfflineShow` is a session over an engine on a clock the caller
drives: no threads, no sockets, and no files unless asked (a ``path`` to
save to, a script to read). It is what ``tests/session_harness.py`` and the
Phase 3–7 build tests wire by hand.

**Commands happen now** (decision 20). The engine applies commands and live
edits at its next tick, so after every :meth:`~OfflineShow.submit`, every
:meth:`~OfflineShow.execute` and every script line the facade ticks at the
current engine time. Time does not move, so a fade or a chase is where it
was, and the command has taken effect when the call returns. Only
:meth:`~OfflineShow.tick` moves time.

Frames are :class:`DmxFrame`\\ s: the engine's frame by universe *number*,
without its compiled show and output layout, which are internal.

Errors (§5.8): constructing a facade raises
:class:`~busk.persistence.show_file.ShowLoadError` for an invalid show and
:class:`~busk.compiler.compile.UnsupportedFeature` for a show busk cannot
run yet. ``submit``, ``execute`` and ``save`` never raise: they return a
result whose ``ok`` is ``False``. ``run_script`` raises
:class:`~busk.errors.ScriptError` at the first failing line, and
:class:`OSError` if the script cannot be read.

**Ctrl+C.** The console holds SIGINT back while a line runs, so a command is
never split (see :mod:`busk.console.console`). The facade then raises
:class:`KeyboardInterrupt` once the line is done, as Python would have.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from busk.commands.types import Command
from busk.compiler.compile import CompiledShow, compile_show
from busk.console.console import Console, Reply
from busk.engine.clock import FakeClock
from busk.engine.loop import Engine, Frame
from busk.engine.snapshot import EngineSnapshot
from busk.errors import ScriptError
from busk.model.show import Show
from busk.model.validate import Issue, has_errors, validate_show
from busk.persistence.show_file import ShowLoadError, show_json
from busk.session.ids import IdFactory
from busk.session.library import ProfileLibrary
from busk.session.session import CommandResult, Session


@dataclass(frozen=True, kw_only=True)
class DmxFrame:
    """One engine output: 512 DMX bytes per universe.

    ``universes`` maps each universe's *number* (as the show numbers it, not
    its row in the engine) to its bytes, in ascending number order. ``seq``
    counts the engine's ticks from 1, and ``time`` is the engine time of the
    tick that made the frame, in seconds.
    """

    seq: int
    time: float
    universes: Mapping[int, bytes]


def _dmx_frame(frame: Frame) -> DmxFrame:
    """The public form of an engine frame."""
    assert frame.compiled is not None  # only hand-built test frames lack it
    numbers = (universe.number for universe in frame.compiled.universes)
    return DmxFrame(
        seq=frame.seq,
        time=frame.time,
        universes=MappingProxyType(dict(zip(numbers, frame.universes, strict=True))),
    )


def _checked(show: Show) -> tuple[Show, CompiledShow]:
    """``show`` validated in full and compiled.

    The whole document is validated, not just its semantics: a ``Show``
    built by hand has never been through the structural checks. Raises
    :class:`ShowLoadError` for any validation error, and
    :class:`~busk.compiler.compile.UnsupportedFeature` from compiling.
    """
    checked, issues = validate_show(show_json(show))
    if checked is None or has_errors(issues):
        raise ShowLoadError(issues)
    return checked, compile_show(checked)


def _optional_path(path: str | os.PathLike[str] | None) -> Path | None:
    return None if path is None else Path(path)


class OfflineShow:
    """A show on a clock you drive: a session, its console and an engine.

    Use it to build shows from console lines or command dicts, and to render
    frames deterministically (tests, previews, offline rendering). It
    starts no thread and opens no socket; it writes only the files it is
    asked to (``save``, a script's ``save`` line).

    ``path`` is where :meth:`save` and a ``save`` line write when they are
    given no path. ``library`` is the profile library ``fixture add`` uses
    (the built-in profiles by default). ``ids`` makes the ids of new
    entities: random by default, :class:`~busk.session.ids.CounterIds` for
    reproducible shows.

    Raises :class:`~busk.persistence.show_file.ShowLoadError` if ``show``
    does not validate, and :class:`~busk.compiler.compile.UnsupportedFeature`
    if it uses a feature busk cannot run yet.
    """

    def __init__(
        self,
        show: Show,
        *,
        path: str | os.PathLike[str] | None = None,
        library: ProfileLibrary | None = None,
        ids: IdFactory | None = None,
    ) -> None:
        show, compiled = _checked(show)
        self._clock = FakeClock()
        self._engine = Engine(compiled, self._clock)
        engine = self._engine
        self._session = Session(
            show,
            engine.bus,
            compiled=compiled,
            path=_optional_path(path),
            ids=ids,
            engine_state=lambda: engine.snapshot,
        )
        self._console = Console(
            self._session,
            library if library is not None else ProfileLibrary(),
            settle=self._settle,
        )
        self._time = 0.0
        self._frame = self._tick(0.0)

    # ----------------------------------------------------------- reading

    @property
    def show(self) -> Show:
        """The committed show document, with every edit so far."""
        return self._session.show

    @property
    def warnings(self) -> tuple[Issue, ...]:
        """The compiler's warnings about :attr:`show` (cue values it drops,
        unpatched fixtures …), in document order."""
        return self._session.compiled.warnings

    @property
    def snapshot(self) -> EngineSnapshot:
        """The engine's published state: playbacks, masters, page, tempo."""
        snapshot = self._engine.snapshot
        assert snapshot is not None  # the constructor's tick published one
        return snapshot

    @property
    def time(self) -> float:
        """The engine time of the last tick, in seconds (0.0 at first)."""
        return self._time

    # ---------------------------------------------------------- commands

    def submit(self, command: Command) -> CommandResult:
        """Carry out one command (any of :data:`~busk.commands.types.Command`)
        at the current engine time. Never raises: a refused command has
        ``ok=False``."""
        result = self._session.submit(command)
        self._settle()
        return result

    def execute(self, line: str) -> Reply:
        """Run one console line at the current engine time. Never raises
        (apart from :class:`KeyboardInterrupt`, see the module docs): a
        failed line has ``ok=False`` and says why in its text."""
        reply = self._console.execute(line)
        self._interrupted()
        return reply

    def run_script(self, path: str | os.PathLike[str]) -> list[str]:
        """Run the console script at ``path``, line by line, and return the
        lines it wrote. A ``quit`` line ends it early.

        Raises :class:`~busk.errors.ScriptError` at the first line that
        fails (the lines after it do not run; the edits before it stay),
        and :class:`OSError` if the file cannot be read.
        """
        path = Path(path)
        lines = path.read_text(encoding="utf-8").splitlines()
        output: list[str] = []
        failure: list[tuple[int, str]] = []
        ok = self._console.run_lines(
            path,
            lines,
            lambda text: output.extend(text.splitlines()),
            failed=lambda number, line: failure.append((number, line)),
        )
        self._console.quit_requested = False  # `quit` ends the script, not the show
        self._interrupted()
        if not ok:
            number, line = failure[0]
            raise ScriptError(path, number, line, output)
        return output

    def save(self, path: str | os.PathLike[str] | None = None) -> CommandResult:
        """Save the show to ``path`` (default: the facade's ``path``, then
        wherever it was last saved). Sets ``meta.modified`` and backs up the
        file it replaces. Never raises: a failure has ``ok=False``."""
        return self._session.save(_optional_path(path))

    # -------------------------------------------------------------- time

    def tick(self, t: float) -> DmxFrame:
        """Move engine time to ``t`` seconds and run one tick; return its
        frame. Fades, chases and effects advance by the time that passed.
        Raises :class:`ValueError` if ``t`` is before :attr:`time`."""
        if t < self._time:
            raise ValueError(f"time cannot go back: {t} is before {self._time}")
        self._frame = self._tick(t)
        return self._frame

    # ----------------------------------------------------------- helpers

    def _tick(self, t: float) -> DmxFrame:
        self._clock.sleep_until(t)
        self._engine.tick(t)
        self._time = t
        latest = self._engine.latest
        assert latest is not None
        return _dmx_frame(latest)

    def _settle(self) -> None:
        """Let the engine apply what was just submitted, without moving time."""
        self._frame = self._tick(self._time)

    def _interrupted(self) -> None:
        """Raise the Ctrl+C the console held back while a line ran."""
        if self._console.interrupted:
            self._console.interrupted = False
            raise KeyboardInterrupt
