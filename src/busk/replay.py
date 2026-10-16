"""``busk replay LOG… [--until T] [--frames OUT.json] [--at T …]`` (phase-7-plan §5.21).

Rebuilds a run from its event log (:mod:`busk.persistence.eventlog`) on a
:class:`~busk.engine.clock.FakeClock` and gives the frames the engine made.

**How.** Records are taken in order, grouped by their time: the records of
one tick are queued as the live engine drained them, then the engine ticks
at that time. A record is queued the way the live run made it:

* ``start``: a session built from the logged show and programmer (without
  an undo history: every record replay needs carries its own content). A
  ``fresh`` connection builds a new engine from that show (with the
  ``--values`` base frame), as a new engine process or ``busk run
  --threads`` did; ``kept`` and ``replaced`` keep the engine running, as a
  restarted console did. Then the connection's install: the programmer
  frame the console sent (its touched slots as logged), and for
  ``replaced`` the show too, with a remap from slot keys;
* ``c``: the envelope, onto the engine's queue as it is;
* ``e``: the patch ops, through :meth:`Session.apply_ops
  <busk.session.session.Session.apply_ops>`;
* ``p``: the programmer command, through :meth:`Session.submit
  <busk.session.session.Session.submit>`;
* ``programmer``: the programmer state, through :meth:`Session.restore_programmer
  <busk.session.session.Session.restore_programmer>`;
* ``r``: the snapshot, as a :class:`~busk.engine.snapshot.Restore`.

The engine does not depend on its tick schedule (§2.7), so the frames at
the logged times are the ones the live engine made then, byte for byte.
``--at T`` ticks at more times (after the last record before ``T``).

**Output.** One line per record (``12.345  e  recorded cue 1/2``), and with
``--frames`` a JSON file of every frame replay made: ``{"frames": [{"t":
…, "universes": {"1": "<1024 hex digits>", …}}]}``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from busk.compiler.compile import CompiledShow, UnsupportedFeature, compile_show
from busk.engine.clock import FakeClock
from busk.engine.install import Install, keys_remap
from busk.engine.loop import Engine, Frame
from busk.engine.snapshot import Restore
from busk.model.validate import has_errors, validate_show
from busk.persistence.eventlog import LogError, Record, op_from_json, read_log, snapshot_from_json
from busk.session.frame import build_frame
from busk.session.programmer import from_json
from busk.session.session import Session
from busk.session.state import ShowState


class ReplayError(Exception):
    """The log does not replay: a record failed, or it does not start with a ``start``."""


@dataclass(frozen=True, slots=True)
class Tick:
    """One tick of the replay: its time, the frame and the records applied in it
    (none for an ``--at`` time)."""

    t: float
    frame: Frame
    records: tuple[Record, ...]


class Replayer:
    """Replays records into a session and an engine (see the module docs)."""

    def __init__(self) -> None:
        self.clock = FakeClock()
        self.engine: Engine | None = None
        self.session: Session | None = None
        self._last: float | None = None  # the engine's last tick time

    def run(
        self, records: Iterable[Record], *, until: float | None = None, at: Iterable[float] = ()
    ) -> Iterator[Tick]:
        """Replay ``records`` (up to ``until``), yielding each tick: one per
        logged time, and one per ``at`` time."""
        extra = sorted(at)
        group: list[Record] = []
        for record in records:
            if until is not None and record.t > until:
                break
            if group and record.t != group[0].t:
                yield from self._tick_group(group, extra)
                group = []
            group.append(record)
        if group:
            yield from self._tick_group(group, extra)
        for t in extra:
            if until is None or t <= until:
                yield from self._tick_at(t)

    def _tick_group(self, group: Sequence[Record], extra: list[float]) -> Iterator[Tick]:
        t = group[0].t
        while extra and extra[0] < t:
            yield from self._tick_at(extra.pop(0))
        for record in group:
            self.apply(record)
        engine = self._engine(group[-1])
        engine.tick(t)
        self._last = t
        assert engine.latest is not None
        yield Tick(t=t, frame=engine.latest, records=tuple(group))

    def _tick_at(self, t: float) -> Iterator[Tick]:
        """An ``--at`` tick, unless the engine is past it (or has none yet)."""
        engine = self.engine
        if engine is None or (self._last is not None and t <= self._last):
            return
        engine.tick(t)
        self._last = t
        assert engine.latest is not None
        yield Tick(t=t, frame=engine.latest, records=())

    def _engine(self, record: Record) -> Engine:
        if self.engine is None:
            raise ReplayError(f"line {record.line}: the log does not begin with a 'start' record")
        return self.engine

    def _session(self, record: Record) -> Session:
        if self.session is None:
            raise ReplayError(f"line {record.line}: the log does not begin with a 'start' record")
        return self.session

    # ---------------------------------------------------------------- records

    def apply(self, record: Record) -> None:
        """Queue one record (see the module docs). Raises :class:`ReplayError`."""
        body = record.body
        if record.kind == "start":
            self._start(record)
        elif record.kind == "c":
            self._engine(record).bus.enqueue(body)
        elif record.kind == "e":
            ops = [op_from_json(op) for op in body["ops"]]
            result = self._session(record).apply_ops(ops, body["label"])
            if not result.ok:
                raise ReplayError(f"line {record.line}: {body['label']}: {result.message}")
        elif record.kind == "p":
            result = self._session(record).submit(body)
            if not result.ok:
                raise ReplayError(f"line {record.line}: {body.get('type')}: {result.message}")
        elif record.kind == "programmer":
            programmer, _ = from_json(body["state"])
            self._session(record).restore_programmer(programmer)
        elif record.kind == "r":
            self._engine(record).bus.restore(Restore(snapshot=snapshot_from_json(body)))
        elif record.kind != "rotated":
            raise ReplayError(f"line {record.line}: unknown record {record.kind!r}")

    def _start(self, record: Record) -> None:
        """A connection: a new session, maybe a new engine, and its install."""
        body = record.body
        show, issues = validate_show(json.dumps(body["show"]))
        if show is None or has_errors(issues):
            raise ReplayError(f"line {record.line}: the logged show does not validate")
        try:
            compiled = compile_show(show)
        except UnsupportedFeature as exc:
            message = f"line {record.line}: the logged show does not compile: {exc}"
            raise ReplayError(message) from None
        programmer, _ = from_json(body["programmer"])
        connect = body["connect"]
        shown: CompiledShow | None = None if self.session is None else self.session.compiled
        if connect == "fresh":
            base = None if body.get("base") is None else np.asarray(body["base"], dtype=np.float64)
            self.engine = Engine(compiled, self.clock, base)
            self._last = None
        elif self.engine is None:
            raise ReplayError(
                f"line {record.line}: the log begins on a running engine ({connect!r});"
                " replay it after the files before it"
            )
        engine = self.engine
        self.session = Session(
            show,
            engine.bus,
            compiled=compiled,
            programmer=programmer,
            engine_state=lambda: engine.snapshot,
        )
        frame = build_frame(
            ShowState(show=show, compiled=compiled),
            programmer,
            programmer.values,
            previous_effects=programmer.effects,
        )
        frame = replace(
            frame,
            touched=np.asarray(body["touched"], dtype=np.int32),
            touchedEffects=frozenset(body["touchedEffects"]),
        )
        install = Install(compiled=None, remap=None, programmer=frame)
        if connect == "replaced":  # the engine host's remap from slot keys
            remap = None if shown is None else keys_remap(shown.slots, compiled.slots)
            install = replace(install, compiled=compiled, remap=remap)
        engine.bus.install(install)


# --------------------------------------------------------------------- the CLI


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The options of ``busk replay``."""
    parser.add_argument("log", type=Path, nargs="+", help="event-log files, oldest first")
    parser.add_argument("--until", type=float, metavar="T", help="stop after engine time T")
    parser.add_argument(
        "--frames", type=Path, metavar="OUT", help="write every frame to OUT as JSON"
    )
    parser.add_argument(
        "--at",
        type=float,
        action="append",
        default=[],
        metavar="T",
        help="also tick at engine time T (repeatable)",
    )


def summary(record: Record) -> str:
    """A record as one line of replay's output (after its time)."""
    body: Any = record.body
    if record.kind == "start":
        title = body["show"].get("meta", {}).get("title", "")
        return f"start  {title!r}, {body['connect']} engine"
    if record.kind == "c":
        command = dict(body["command"])
        kind = command.pop("type", "?")
        rest = json.dumps(command, ensure_ascii=False, separators=(",", ":"))
        return f"c      {kind} {rest}"
    if record.kind == "e":
        return f"e      {body['label']}"
    if record.kind == "p":
        return f"p      {body.get('type', '?')}"
    if record.kind == "programmer":
        return f"prog   {body['label']}"
    if record.kind == "r":
        return "r      restore"
    return record.kind


def main(args: argparse.Namespace) -> int:
    """Run ``busk replay``; 0 when the whole log replays, 1 otherwise."""
    replayer = Replayer()
    frames: list[dict[str, Any]] = []
    ticks = records = 0
    last: float | None = None
    try:
        for tick in replayer.run(read_log(args.log), until=args.until, at=args.at):
            ticks += 1
            records += len(tick.records)
            last = tick.t
            for record in tick.records:
                print(f"{tick.t:12.6f}  {summary(record)}")
            if not tick.records:
                print(f"{tick.t:12.6f}  (--at)")
            if args.frames is not None:
                frames.append(frame_json(tick.frame))
    except (LogError, ReplayError) as exc:
        print(f"error   {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error   cannot read {exc.filename}: {exc.strerror}", file=sys.stderr)
        return 1
    if args.frames is not None:
        try:
            args.frames.write_text(json.dumps({"frames": frames}) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"error   cannot write {args.frames}: {exc.strerror}", file=sys.stderr)
            return 1
    end = "" if last is None else f", up to t={last:.6f}"
    print(f"replayed {records} record(s) in {ticks} tick(s){end}")
    return 0


def frame_json(frame: Frame) -> dict[str, Any]:
    """A frame as ``{"t", "universes": {number: hex}}``."""
    compiled = frame.compiled
    numbers = (
        [str(index) for index in range(len(frame.universes))]
        if compiled is None
        else [str(universe.number) for universe in compiled.universes]
    )
    universes = zip(numbers, frame.universes, strict=True)
    return {"t": frame.time, "universes": {number: data.hex() for number, data in universes}}
