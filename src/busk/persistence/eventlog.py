"""The event log (spec §15.5, phase-7-plan §5.21): what the engine applied, when and why.

The engine records, at the tick that applies them, each command envelope,
each install's *cause* and each restore (:attr:`Engine.records
<busk.engine.loop.Engine.records>`). The session puts the cause on the
:class:`~busk.engine.install.Install` as ready-made JSON, so the engine never
encodes anything: it appends ``(now, item)`` to a deque and a writer
elsewhere takes it. ``busk replay`` (:mod:`busk.replay`) rebuilds the run from
the file and gives the frames the engine made at every logged time.

**Records.** A file holds JSON lines. Each is an object with ``t``, the
engine time of the tick that applied it, and one key that says what it is:

==============  ============================================================
``start``       a console connected to an engine, the cause of the first
                install on the connection (:func:`start_cause`): the show
                and the programmer the console had, how the connection went
                (``connect``: ``fresh``, a new engine; ``kept`` or
                ``replaced``, a running one, decision 8), the touched slots
                and effects of the programmer frame it sent, busk's version,
                the engine rate and the ``--values`` base frame. Every
                connection writes one, so replay starts afresh from each
                (a restarted engine or console)
``c``           a command envelope the engine applied (as the bus queued it)
``e``           a show edit, an undo or a redo: ``{"label", "ops"}``, its
                forward patch ops, which replay applies through
                :meth:`Session.apply_ops <busk.session.session.Session.apply_ops>`
                (§15.5 logs envelopes only, which cannot replay edits whose
                ids were generated)
``p``           a programmer command; ``SELECT_PLAYBACK`` is logged as the
                ``SELECT`` of the targets it resolved to, so replay never
                depends on what the engine showed the session
``programmer``  the programmer set as a whole, ``{"label", "state"}`` (the
                autosave form): an undo or redo of a programmer step, or
                crash recovery
``r``           a restore after an engine restart: the snapshot it restored
``rotated``     the first line of a file that continues another (its name)
==============  ============================================================

**Files.** :class:`EventLog` writes ``<stateDir>/logs/<show id>/<UTC start>.log``.
It opens its file at the first ``start`` record, from the show id at its
head, and a new one when a ``start`` names another show. A file is rotated
once it would pass :data:`ROTATE_BYTES`, and a directory keeps the newest
:data:`KEEP` files. The root writes the log in process mode (the engine
host sends its records in batches every :data:`FLUSH_S`), a
:class:`LogPump` thread with ``--threads``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO, Any, Final

from busk import __version__
from busk.commands.patch import Op
from busk.commands.types import CommandEnvelope
from busk.engine.snapshot import EngineSnapshot, PageStatus, PlaybackStatus, Restore, SpeedStatus
from busk.persistence.paths import log_directory
from busk.persistence.show_file import WallClock, file_stamp, utc_now

_log = logging.getLogger("busk.eventlog")

ROTATE_BYTES: Final = 64 * 1024 * 1024
"""A log file is rotated once the next line would take it past this size."""

KEEP: Final = 16
"""Log files a show's directory keeps (the oldest go first)."""

FLUSH_S: Final = 0.1
"""How often records leave the engine (in batches)."""

START_PREFIX: Final = b'{"start":{"showId":'
"""How every ``start`` cause begins: the writer finds the show id there
without parsing the whole show document."""

type Item = CommandEnvelope | bytes | Restore
"""What the engine records: an envelope, an install's cause, or a restore."""


# ------------------------------------------------------------------ causes


def _dumps(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def edit_cause(label: str, ops: Sequence[Op]) -> bytes:
    """The cause of a show edit, undo or redo: its forward patch ops."""
    return _dumps({"e": {"label": label, "ops": [op_json(op) for op in ops]}})


def programmer_cause(command: Mapping[str, Any]) -> bytes:
    """The cause of a programmer command."""
    return _dumps({"p": command})


def state_cause(label: str, state: Mapping[str, Any]) -> bytes:
    """The cause of setting the whole programmer (``state``: its autosave form)."""
    return _dumps({"programmer": {"label": label, "state": state}})


def start_cause(
    *,
    show: Mapping[str, Any],
    programmer: Mapping[str, Any],
    connect: str,
    touched: Iterable[int] = (),
    touched_effects: Iterable[str] = (),
    engine_hz: float,
    base: Sequence[float] | None = None,
) -> bytes:
    """The cause of a connection's first install (see the module docs).

    ``show`` is the show document and ``programmer`` the programmer's
    autosave form, as the install shows them; ``touched`` and
    ``touched_effects`` are its programmer frame's.
    """
    body = {
        "showId": show["meta"]["id"],  # first: see START_PREFIX
        "version": __version__,
        "engineHz": engine_hz,
        "connect": connect,
        "touched": [int(slot) for slot in touched],
        "touchedEffects": sorted(touched_effects),
        "base": None if base is None else [float(value) for value in base],
        "programmer": programmer,
        "show": show,
    }
    return _dumps({"start": body})


def start_show_id(cause: bytes) -> str | None:
    """The show id of a ``start`` cause; ``None`` for any other cause."""
    if not cause.startswith(START_PREFIX):
        return None
    head = cause[len(START_PREFIX) : len(START_PREFIX) + 4096].decode("utf-8", "ignore")
    try:
        ident, _ = json.JSONDecoder().raw_decode(head)
    except json.JSONDecodeError:
        return None
    return ident if isinstance(ident, str) else None


# ---------------------------------------------------------------- encoding


def op_json(op: Op) -> dict[str, Any]:
    """A patch op as JSON-shaped data."""
    data: dict[str, Any] = {"op": op.op, "path": list(op.path)}
    if op.op != "remove":
        data["value"] = op.value
    return data


def op_from_json(data: Mapping[str, Any]) -> Op:
    """The patch op of :func:`op_json` data."""
    return Op(op=data["op"], path=tuple(data["path"]), value=data.get("value"))


def snapshot_json(snapshot: EngineSnapshot) -> dict[str, Any]:
    """An engine snapshot as JSON-shaped data."""
    return asdict(snapshot)


def snapshot_from_json(data: Mapping[str, Any]) -> EngineSnapshot:
    """The engine snapshot of :func:`snapshot_json` data."""
    page = data.get("page")
    return EngineSnapshot(
        seq=data["seq"],
        time=data["time"],
        grandMaster=data["grandMaster"],
        blackout=data["blackout"],
        playbacks=tuple(PlaybackStatus(**status) for status in data["playbacks"]),
        masterLevels=tuple((ident, level) for ident, level in data.get("masterLevels", ())),
        speed=tuple(SpeedStatus(**status) for status in data.get("speed", ())),
        page=None if page is None else PageStatus(**page),
        fadeTime=data.get("fadeTime"),
        outputEnabled=data.get("outputEnabled", True),
    )


def encode(t: float, item: Item) -> bytes:
    """One record as a line of the log file."""
    if isinstance(item, bytes):
        body = item
    elif isinstance(item, Restore):
        body = _dumps({"r": snapshot_json(item.snapshot)})
    else:
        body = _dumps({"c": item})
    return b'{"t":' + _dumps(t) + b"," + body[1:] + b"\n"


# ------------------------------------------------------------------- files


class EventLog:
    """Writes records to ``<directory>/<show id>/<UTC start>.log`` (see the
    module docs). ``directory`` is ``<stateDir>/logs``.

    Not thread-safe: one writer thread calls :meth:`add`. A write that fails
    is reported once through ``report`` (by default a ``busk.eventlog``
    warning) and the record is lost; the log goes on trying. ``opened`` is
    called with each new file's path.
    """

    def __init__(
        self,
        directory: Path,
        *,
        max_bytes: int = ROTATE_BYTES,
        keep: int = KEEP,
        wall_clock: WallClock = utc_now,
        opened: Callable[[Path], None] | None = None,
        report: Callable[[str], None] = _log.warning,
    ) -> None:
        self._directory = directory
        self._max_bytes = max_bytes
        self._keep = keep
        self._wall_clock = wall_clock
        self._opened = opened
        self._report = report
        self._file: IO[bytes] | None = None
        self._show: str | None = None
        self._size = 0
        self._failed = False
        self.path: Path | None = None
        """The file written now (``None`` before the first ``start``)."""
        self.lost = 0
        """Records not written: before the first ``start``, or a failed write."""

    def add(self, t: float, item: Item) -> None:
        """Write one record (a ``start`` for another show opens a new file)."""
        show = start_show_id(item) if isinstance(item, bytes) else None
        line = encode(t, item)
        try:
            if show is not None and show != self._show:
                self._open(show)
            if self._file is None:
                self.lost += 1
                return
            if self._size > 0 and self._size + len(line) > self._max_bytes:
                previous = self.path
                self._open(self._show or "_")
                if previous is not None:
                    self._write(encode(t, _dumps({"rotated": previous.name})))
            self._write(line)
        except OSError as exc:
            self.lost += 1
            if not self._failed:
                self._failed = True
                self._report(f"event log: cannot write: {exc}")

    def flush(self) -> None:
        """Hand what was written to the operating system."""
        if self._file is not None:
            with contextlib.suppress(OSError):
                self._file.flush()

    def close(self) -> None:
        """Close the file (at exit)."""
        if self._file is not None:
            with contextlib.suppress(OSError):
                self._file.close()
            self._file = None

    def _write(self, line: bytes) -> None:
        assert self._file is not None
        self._file.write(line)
        self._size += len(line)

    def _open(self, show: str) -> None:
        """Start a new file for ``show``; drop the oldest beyond :attr:`keep`."""
        self.close()
        directory = log_directory(self._directory, show)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = file_stamp(self._wall_clock())
        path = directory / f"{stamp}.log"
        counter = 1
        while path.exists():  # two files within one microsecond (or a frozen test clock)
            path = directory / f"{stamp}-{counter}.log"
            counter += 1
        self._file = path.open("xb")
        self._show, self.path, self._size = show, path, 0
        old = sorted(directory.glob("*.log"))
        for stale in old[: max(len(old) - self._keep, 0)]:
            stale.unlink(missing_ok=True)
        if self._opened is not None:
            self._opened(path)


def take(records: deque[tuple[float, Item]]) -> list[tuple[float, Item]]:
    """Pop every record the deque holds now, oldest first (the writer's side)."""
    batch = []
    while records:
        batch.append(records.popleft())
    return batch


class LogPump:
    """``busk run --threads``: a thread that moves the engine's records into
    an :class:`EventLog` every :data:`FLUSH_S`, and the rest at :meth:`stop`."""

    def __init__(self, records: deque[tuple[float, Item]], log: EventLog) -> None:
        self.log = log
        self._records = records
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="busk-eventlog", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        """Write what is left and close the file."""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join()
        self._pump()
        self.log.close()

    def _run(self) -> None:
        while not self._stop.wait(FLUSH_S):
            self._pump()

    def _pump(self) -> None:
        for t, item in take(self._records):
            self.log.add(t, item)
        self.log.flush()


# ----------------------------------------------------------------- reading


@dataclass(frozen=True, slots=True)
class Record:
    """One line of a log: its engine time, what it is (the key: ``start``,
    ``c``, ``e``, …) and that key's value; ``line`` counts from 1 across
    the files read."""

    t: float
    kind: str
    body: Any
    line: int


class LogError(Exception):
    """A log file that cannot be read as one."""


def read_log(paths: Sequence[Path]) -> Iterator[Record]:
    """The records of ``paths``, read in order as one log. Raises
    :class:`LogError` for a line that is not a record, and :class:`OSError`
    for a file that cannot be read."""
    number = 0
    for path in paths:
        with path.open("rb") as stream:
            for raw in stream:
                number += 1
                if not raw.strip():
                    continue
                try:
                    data = json.loads(raw)
                except ValueError as exc:
                    raise LogError(f"{path}:{number}: not JSON: {exc}") from None
                if not isinstance(data, dict) or len(data) != 2 or "t" not in data:
                    raise LogError(f"{path}:{number}: not an event-log record")
                t = data.pop("t")
                ((kind, body),) = data.items()
                if not isinstance(t, int | float):
                    raise LogError(f"{path}:{number}: its time is not a number")
                yield Record(t=float(t), kind=kind, body=body, line=number)
