"""Autosave and crash recovery (spec §5.14, §17, §18; phase-3-plan §5.9).

Each show gets its own folder, ``<stateDir>/autosave/<meta.id>/``, holding:

``show-<UTC timestamp>.show``
    The show, written only while it has unsaved edits: :data:`SHOW_DELAY`
    seconds after the last show edit (the end of a burst), or every
    :data:`SHOW_PERIOD` seconds during a long burst. The newest
    :data:`SHOWS_KEPT` are kept.
``session.json``
    What a restart needs to pick up where the operator was: the programmer
    (selection, values, effects, blind, fade time, highlight), the masters' levels
    (``masterLevels``: grand, group, size, speed and fade time), the speed masters'
    tempos (``speedBpm``), the current page's id (``page``, Phase 6), the
    show's path, ``showAutosave`` (the newest autosave since the last save,
    or ``null``), ``showStamp`` (the stamp of the newest show on disk: that
    autosave, else the show file; Phase 7) and ``cleanExit``. Written at most once per
    :data:`SESSION_PERIOD` seconds when any of that changed, and on a clean
    exit.

An :class:`AutosaveWorker` thread calls :meth:`AutosaveWorker.service` every
:data:`SERVICE_PERIOD` seconds (testable on a fake clock, like the output
scheduler). It reads the session's published
:class:`~busk.session.session.SessionSnapshot` and never takes the session
lock, so it never blocks an edit.

**Recovery** (:func:`read_recovery`): on startup, ``busk run SHOW`` looks
for the show's ``session.json``. Missing, or ``cleanExit: true``: a normal
start. ``cleanExit: false``: the last run crashed, so the programmer
(including its effects, blind, its fade time and highlight), the master levels, then
the tempos and then the current page are restored, and ``showAutosave`` is loaded instead of the
show file when it is newer, marked as unsaved. Files written before Phase 4
have no ``speedBpm`` or ``fadeTime``, before Phase 5 no programmer
effects (nor group and size levels), before Phase 6 no ``page`` and before
Phase 7 no ``showStamp``; they still load.

A console that the root of ``busk run`` restarts after a crash recovers
whether or not the last exit was clean (``force``: a console that exits 70
wrote a clean exit on its way out), and compares ``showStamp`` with the
stamp of the show the engine runs (phase-7-plan decision 8).
"""

from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from busk.engine.clock import Clock
from busk.engine.install import Stamp
from busk.model.master import MAX_BPM
from busk.persistence.paths import autosave_directory
from busk.persistence.show_file import (
    WallClock,
    atomic_write,
    encode_show,
    file_stamp,
)
from busk.session.programmer import Programmer, from_json, to_json
from busk.session.session import Session

SHOW_DELAY: Final = 5.0
"""Seconds after the last show edit before the burst is autosaved."""

SHOW_PERIOD: Final = 180.0
"""During a burst of edits, autosave at least this often."""

SHOWS_KEPT: Final = 20
"""Show autosaves kept per show."""

SESSION_PERIOD: Final = 1.0
"""``session.json`` is written at most this often."""

SERVICE_PERIOD: Final = 0.5
"""How often the worker thread looks at the session."""

SESSION_FILE: Final = "session.json"

type MasterLevels = Callable[[], Mapping[str, float]]
"""The masters' current levels (from the engine snapshot)."""

type Tempos = Callable[[], Mapping[str, float]]
"""The speed masters' current BPMs (from the engine snapshot)."""

type CurrentPage = Callable[[], str | None]
"""The current page's id (from the engine snapshot); ``None`` without pages."""


class AutosaveWorker:
    """Writes the show and ``session.json`` autosaves of one session."""

    def __init__(
        self,
        session: Session,
        state_dir: Path,
        *,
        clock: Clock,
        wall_clock: WallClock,
        masters: MasterLevels = dict,
        tempos: Tempos = dict,
        page: CurrentPage = lambda: None,
    ) -> None:
        self._session = session
        self.folder = autosave_directory(state_dir, session.show["meta"]["id"])
        self._clock = clock
        self._wall_clock = wall_clock
        self._masters = masters
        self._tempos = tempos
        self._page = page
        snapshot = session.snapshot
        self._seen_version = snapshot.showVersion
        self._written_version = snapshot.showVersion  # the show on disk is current
        self._stamp = snapshot.stamp  # … and this is its stamp
        self._saves = snapshot.saves
        self._last_edit: float | None = None
        self._burst_start: float | None = None
        self._last_show_write: float | None = None
        self.showAutosave: Path | None = None
        """The newest show autosave since the last save, if any."""
        self._written_state: Any = None  # what session.json last held
        self._last_session_write: float | None = None

    def mark_recovered(self, path: Path) -> None:
        """The session was recovered from ``path``: it is the current autosave."""
        self.showAutosave = path

    def service(self, now: float) -> None:
        """Write whatever autosave is due at time ``now`` (worker thread)."""
        snapshot = self._session.snapshot  # one read: consistent and lock-free
        if snapshot.saves != self._saves:  # saved: the file on disk is current
            self._saves = snapshot.saves
            self._written_version = snapshot.showVersion
            self._stamp = snapshot.stamp
            self.showAutosave = None
            self._burst_start = None
        if snapshot.showVersion != self._seen_version:
            self._seen_version = snapshot.showVersion
            if snapshot.showVersion != self._written_version:
                self._last_edit = now
                if self._burst_start is None:
                    self._burst_start = now
        if snapshot.dirty and snapshot.showVersion != self._written_version:
            assert self._last_edit is not None
            assert self._burst_start is not None
            quiet = now - self._last_edit >= SHOW_DELAY
            since = (
                self._burst_start
                if self._last_show_write is None
                else max(self._burst_start, self._last_show_write)
            )
            if quiet or now - since >= SHOW_PERIOD:
                self._write_show(snapshot.show, snapshot.showVersion, snapshot.stamp, now)
                self._burst_start = None if quiet else now
        state = self._session_state(clean=False)
        due = self._last_session_write is None or now - self._last_session_write >= SESSION_PERIOD
        if state != self._written_state and due:
            self._write_session(state, now)

    def finish(self, now: float) -> Path | None:
        """A clean exit: autosave unsaved edits now, then mark the exit clean.

        Returns the newest show autosave when the show has unsaved edits (the
        quit message names it), else ``None``.
        """
        snapshot = self._session.snapshot
        if snapshot.dirty and snapshot.showVersion != self._written_version:
            self._write_show(snapshot.show, snapshot.showVersion, snapshot.stamp, now)
        self._write_session(self._session_state(clean=True), now)
        return self.showAutosave if snapshot.dirty else None

    def run(self, stop: threading.Event) -> None:
        """Call :meth:`service` every :data:`SERVICE_PERIOD` seconds until ``stop``.

        A failing write (a full disk) must not end the worker: it is retried
        on the next service.
        """
        while not stop.wait(SERVICE_PERIOD):
            with contextlib.suppress(OSError):
                self.service(self._clock.now())

    # ------------------------------------------------------------- writes

    def _write_show(self, show: Any, version: int, stamp: Stamp, now: float) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"show-{file_stamp(self._wall_clock())}.show"
        counter = 1
        while path.exists():
            path = self.folder / f"show-{file_stamp(self._wall_clock())}-{counter}.show"
            counter += 1
        atomic_write(path, encode_show(show, path))
        self._written_version = version
        self._stamp = stamp
        self._last_show_write = now
        self.showAutosave = path
        for old in sorted(self.folder.glob("show-*.show"))[:-SHOWS_KEPT]:
            old.unlink(missing_ok=True)

    def _session_state(self, *, clean: bool) -> dict[str, Any]:
        snapshot = self._session.snapshot
        return {
            "programmer": to_json(snapshot.programmer),
            "masterLevels": dict(self._masters()),
            "speedBpm": dict(self._tempos()),
            "page": self._page(),
            "showPath": None if snapshot.path is None else str(snapshot.path),
            "showAutosave": None if self.showAutosave is None else str(self.showAutosave),
            "showStamp": list(self._stamp),
            "cleanExit": clean,
        }

    def _write_session(self, state: dict[str, Any], now: float) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(state, indent=2) + "\n").encode("utf-8")
        atomic_write(self.folder / SESSION_FILE, data)
        self._written_state = state
        self._last_session_write = now


# ------------------------------------------------------------------ recovery


@dataclass(frozen=True, kw_only=True)
class Recovery:
    """What a crashed session left behind."""

    programmer: Programmer
    masterLevels: Mapping[str, float]
    speedBpm: Mapping[str, float]  # restored after the levels
    page: str | None  # the current page's id, restored last (Phase 6)
    showAutosave: Path | None  # newer than the show file: load it instead
    showStamp: Stamp | None  # the stamp of the show to load (None: unknown; Phase 7)
    dropped: tuple[str, ...]  # malformed entries that were left out


def read_recovery(
    state_dir: Path, show_id: str, show_path: Path, *, force: bool = False
) -> Recovery | None:
    """The recovery for the show ``show_id`` loaded from ``show_path``, or
    ``None`` for a normal start (no ``session.json``, a clean exit unless
    ``force``, or a file that cannot be read).

    ``showStamp`` describes the show the recovery loads: ``None`` when the
    file has none, or when its autosave is not used (older than the show
    file, which was then saved outside this session).
    """
    path = autosave_directory(state_dir, show_id) / SESSION_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or (data.get("cleanExit") is not False and not force):
        return None
    programmer, dropped = from_json(data.get("programmer", {}))
    levels = data.get("masterLevels")
    masters = {
        str(ident): float(level)
        for ident, level in (levels.items() if isinstance(levels, dict) else ())
        if _is_number(level) and 0 <= level <= 1
    }
    tempos = data.get("speedBpm")  # missing in files written before Phase 4
    bpms = {
        str(ident): float(bpm)
        for ident, bpm in (tempos.items() if isinstance(tempos, dict) else ())
        if _is_number(bpm) and 0 < bpm <= MAX_BPM
    }
    page = data.get("page")  # missing in files written before Phase 6
    autosave = data.get("showAutosave")
    newer: Path | None = None
    if isinstance(autosave, str):
        candidate = Path(autosave)
        try:
            if candidate.stat().st_mtime > show_path.stat().st_mtime:
                newer = candidate
        except OSError:
            pass
    stamp = _stamp(data.get("showStamp"))  # missing in files written before Phase 7
    return Recovery(
        programmer=programmer,
        masterLevels=masters,
        speedBpm=bpms,
        page=page if isinstance(page, str) else None,
        showAutosave=newer,
        showStamp=None if isinstance(autosave, str) and newer is None else stamp,
        dropped=tuple(dropped),
    )


def _stamp(value: object) -> Stamp | None:
    """A ``[sessionId, n]`` pair as a :data:`Stamp`, or ``None``."""
    if isinstance(value, list) and len(value) == 2:
        ident, n = value
        if isinstance(ident, str) and isinstance(n, int) and not isinstance(n, bool):
            return (ident, n)
    return None


def _is_number(value: object) -> bool:
    """An ``int`` or ``float`` that is not a ``bool``."""
    return isinstance(value, int | float) and not isinstance(value, bool)
