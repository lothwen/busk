"""The session: the command bus of spec §15 and the single writer of editing state
(phase-3-plan §3 decisions 2–4, §5.6).

Every command enters through :meth:`Session.submit` (synchronous, returns a
:class:`CommandResult`) or :meth:`Session.post` (fire and forget, for input
threads). The session routes it by class
(:mod:`busk.commands.classes`):

* **performance** commands go straight onto the engine's queue
  (:meth:`CommandBus.submit <busk.commands.bus.CommandBus.submit>`). No lock
  is taken, so performance never waits for an edit;
* **programmer** commands, under the session lock: the handler returns a new
  :class:`~busk.session.programmer.Programmer`, a programmer frame is built
  and installed in the engine, and a step goes on the undo timeline (not
  for ``BLIND``, ``PROGRAMMER_FADE`` and ``HIGHLIGHT``: modes are never
  undone). A fade time installs nothing: the next frame carries it. While
  highlight is on, a selection change installs a frame too, since the
  highlight follows the selection;
* **show edits**, under the session lock: the handler's patch ops are
  applied copy-on-write to a candidate show, which is validated
  (:func:`~busk.model.validate.validate_edit`) and compiled; only then is it
  committed and installed in the engine, with a slot remap when the slot
  keys changed. Any error rejects the whole edit and nothing changes
  anywhere: **the session only ever holds a show that validates and
  compiles** (decision 4);
* ``UNDO`` / ``REDO`` walk the one timeline; a show step goes through the
  same validate → compile → install path. ``UNDO_GROUP`` and
  ``UNDO_GROUP_END`` open and close an undo group (GAP-06 of
  ``docs/dev/tui/engine-gaps.md``): the programmer steps between them are
  one step on the timeline (:mod:`busk.session.timeline`), whichever thread
  or surface sent them. A line that is refused changes nothing, the group
  included. While a script runs (:meth:`Session.script`, GAP-56), every
  step joins one, and undoing it puts back its show edits and its
  programmer in one change.

**Ordering.** Installs and performance commands share the engine's FIFO
queue, and installs are queued while the lock is held, so the engine sees
edits in commit order and a programmer frame always arrives after the
compiled show it was built against. Right after queueing a compiled show the
session points the bus at it, so a command naming a new playback is
validated against the show that has it and queued behind the install.

**The event log** (Phase 7, phase-7-plan §5.21). With ``causes`` on, each
install carries its cause for the engine to record
(:mod:`busk.persistence.eventlog`): a show edit, undo or redo its forward
patch ops, a programmer command the command (``SELECT_PLAYBACK`` as the
``SELECT`` it resolved to), and a programmer undo, redo or recovery the
programmer it set. A programmer change that installs nothing (a selection,
a fade time) still matters to the commands after it: its cause waits for
the next install and goes before that install's own. Every install also
carries ``(show, programmer)`` as its ``source``, which a console's bus
keeps for the record of a reconnect.
``busk replay`` applies the ops with :meth:`Session.apply_ops`.

**Readers.** Other threads (the autosave worker, the console) read
:attr:`Session.snapshot`, an immutable :class:`SessionSnapshot` published by
one reference assignment after every change: they never take the lock.
"""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import secrets
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, cast

from busk.commands import edits, record
from busk.commands.bus import CommandBus, CommandRejected
from busk.commands.classes import command_class
from busk.commands.edits import short
from busk.commands.errors import CommandError
from busk.commands.patch import Op, apply
from busk.commands.types import Command, CommandOrigin
from busk.compiler.compile import CompiledShow, UnsupportedFeature, compile_show
from busk.engine.install import Install, Stamp
from busk.engine.snapshot import EngineSnapshot
from busk.model.show import Show
from busk.model.validate import Issue, validate_edit
from busk.persistence import eventlog
from busk.persistence.show_file import WallClock, iso_time, save_show, utc_now
from busk.session.frame import build_frame, slot_remap
from busk.session.ids import IdFactory, RandomIds
from busk.session.programmer import (
    EMPTY,
    Programmer,
    drop_invalid_effects,
    drop_missing,
    handle,
    playback_targets,
    to_json,
)
from busk.session.state import ShowState
from busk.session.timeline import Group, ProgrammerStep, ShowStep, Timeline


@dataclass(frozen=True, kw_only=True)
class CommandResult:
    """The outcome of one command.

    ``message`` is one line for the operator (``recorded cue 10/1: 2
    entries``); ``issues`` are the errors when not ``ok`` and new warnings
    when ``ok``, with their paths.
    """

    ok: bool
    message: str
    issues: tuple[Issue, ...] = ()


@dataclass(frozen=True, kw_only=True)
class SessionSnapshot:
    """What lock-free readers see of the session; replaced, never mutated."""

    show: Show
    compiled: CompiledShow
    state: ShowState  # the show, compiled, with its lookups (GAP-02's programmer status reads it)
    programmer: Programmer
    dirty: bool  # the show has edits that are not saved
    showVersion: int  # +1 per committed show change (edit, undo, redo, save)
    programmerVersion: int  # +1 per programmer change (blind included)
    saves: int  # +1 per successful save
    savedVersion: int  # the showVersion the last save wrote (an edit may have come since)
    savedStamp: Stamp  # and its stamp
    path: Path | None  # where `save` writes by default
    stamp: Stamp  # the stamp of `compiled`, the show the engine was last given (Phase 7)
    undoSteps: int  # the timeline's, as it was when the change above was made (GAP-03)
    redoSteps: int
    nextUndo: str | None  # the label of the step `undo` would undo
    nextRedo: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionStatus:
    """The session as a display reads it: the change counters, unsaved
    edits, the show's file and the undo timeline (GAP-03 of
    ``docs/dev/tui/engine-gaps.md``).

    ``showVersion`` grows by one with each change to the show: an edit, an
    undo or redo of one, a save. ``programmerVersion`` grows with each
    change to the programmer, a mode (blind, highlight, the fade time)
    included. ``dirty`` says the show has edits that are not saved. ``path``
    is the absolute path of the file ``save`` writes when given none, or
    ``None`` when the show has none yet. ``undoSteps`` and ``redoSteps``
    count the steps ``undo`` and ``redo`` can take, and ``nextUndo`` and
    ``nextRedo`` are the labels of the next ones, as ``undo`` and ``redo``
    print them after ``undid:`` and ``redid:`` (``None`` when there is
    none). An open undo group is not a step until a change joins it.
    """

    showVersion: int
    programmerVersion: int
    dirty: bool
    path: str | None
    undoSteps: int
    redoSteps: int
    nextUndo: str | None
    nextRedo: str | None


def session_status(snapshot: SessionSnapshot) -> SessionStatus:
    """The :class:`SessionStatus` of ``snapshot``."""
    return SessionStatus(
        showVersion=snapshot.showVersion,
        programmerVersion=snapshot.programmerVersion,
        dirty=snapshot.dirty,
        path=None if snapshot.path is None else os.path.abspath(snapshot.path),
        undoSteps=snapshot.undoSteps,
        redoSteps=snapshot.redoSteps,
        nextUndo=snapshot.nextUndo,
        nextRedo=snapshot.nextRedo,
    )


type Report = Callable[[str], None]


_MODES: Final = frozenset({"BLIND", "PROGRAMMER_FADE", "HIGHLIGHT"})
"""Programmer commands that switch a mode: no undo step."""


_log = logging.getLogger("busk.session")


class Session:
    """The single writer of the show, the programmer and the undo timeline."""

    def __init__(
        self,
        show: Show,
        bus: CommandBus,
        *,
        compiled: CompiledShow | None = None,
        path: Path | None = None,
        ids: IdFactory | None = None,
        wall_clock: WallClock = utc_now,
        dirty: bool = False,
        report: Report = _log.warning,
        engine_state: Callable[[], EngineSnapshot | None] | None = None,
        stamp: Stamp | None = None,
        programmer: Programmer = EMPTY,
        causes: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """``show`` must be valid; ``compiled`` is its compiled form if the
        caller has it already. The bus's compiled show is replaced by this
        session's from now on.

        ``stamp`` is the stamp of ``show`` (phase-7-plan decision 8): a
        restarted console passes the one its recovered show had, so it can
        tell whether the engine still runs that show. By default it is
        ``(sessionId, 0)``. Each show the session installs is stamped
        ``(sessionId, n)``, with a session id of its own.

        ``engine_state`` reads the engine's latest snapshot (``busk run``
        passes ``lambda: engine.snapshot``): ``SELECT_PLAYBACK`` selects the
        targets of the playback's current cue from it. Without it, the first
        cue's targets are selected.

        ``programmer`` is the programmer the session starts with, installed
        nowhere (``busk replay``: the engine has its frame already).
        ``causes`` puts the event-log cause on every install (see the
        module docs). ``clock`` (seconds, monotonic) is what an undo group's
        gap is measured on: the engine's clock, so an ``OfflineShow``'s
        groups follow its fake time.
        """
        self._lock = threading.Lock()
        self._bus = bus
        self._ids: IdFactory = RandomIds() if ids is None else ids
        self._wall_clock = wall_clock
        self._report = report
        self._engine_state = engine_state
        compiled = compile_show(show) if compiled is None else compiled
        self._state = ShowState(show=show, compiled=compiled)
        self._known = _warning_keys(self._state, validate_edit(show, show)[1])
        self._programmer = programmer
        self._causes = causes
        self._pending: list[bytes] = []  # causes of changes that installed nothing yet
        self._dirty = dirty
        self._path = path
        self._versions = [0, 0, 0]  # show, programmer, saves
        self._sessionId = secrets.token_hex(8)
        self._installs = 0  # shows installed: the n of the next stamp is one more
        self._stamp: Stamp = (self._sessionId, 0) if stamp is None else stamp
        self._saved = (0, self._stamp)  # the show version and stamp the last save wrote
        self.timeline = Timeline(clock=clock)
        bus.compiled = compiled
        self._worker: threading.Thread | None = None
        self._posted: queue.SimpleQueue[tuple[Command, CommandOrigin] | None] = queue.SimpleQueue()
        self.snapshot: SessionSnapshot
        self._publish()

    # ----------------------------------------------------------- reading

    @property
    def show(self) -> Show:
        return self._state.show

    @property
    def compiled(self) -> CompiledShow:
        return self._state.compiled

    @property
    def state(self) -> ShowState:
        return self._state

    @property
    def programmer(self) -> Programmer:
        return self._programmer

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def ids(self) -> IdFactory:
        return self._ids

    # --------------------------------------------------------- commands

    def submit(self, command: Command, origin: CommandOrigin | None = None) -> CommandResult:
        """Carry out ``command`` and say how it went. Never raises."""
        kind = command_class(cast(Mapping[str, object], command))
        if kind == "performance":
            try:
                self._bus.submit(command, origin)
            except CommandRejected as exc:
                return CommandResult(ok=False, message=exc.reason)
            return CommandResult(ok=True, message="")
        if kind is None:
            return CommandResult(ok=False, message=f"unknown command type {command.get('type')!r}")
        with self._lock:
            try:
                if kind == "programmer":
                    return self._programmer_command(command)
                if kind == "show":
                    return self._show_command(command)
                return self._session_command(command)
            except CommandError as exc:
                return CommandResult(ok=False, message=exc.message, issues=exc.issues)
            except Exception as exc:  # a bug must not take the console down
                return CommandResult(
                    ok=False, message=f"internal error: {type(exc).__name__}: {exc}"
                )

    def post(self, command: Command, origin: CommandOrigin | None = None) -> None:
        """Submit from an input thread without waiting.

        Performance commands go straight to the engine queue (a rejection
        raises :class:`~busk.commands.bus.CommandRejected`, as the bus does).
        Every other command is handed to one worker thread that submits them
        in arrival order, so an input thread never blocks behind a long edit;
        failures are reported through ``report`` (by default a ``busk.session``
        warning; the CLI prints them on stderr).
        """
        if command_class(cast(Mapping[str, object], command)) == "performance":
            self._bus.submit(command, origin)
            return
        self.start()
        self._posted.put((command, CommandOrigin() if origin is None else origin))

    def start(self) -> None:
        """Start the worker thread of :meth:`post` (idempotent)."""
        with self._lock:
            if self._worker is None:
                self._worker = threading.Thread(target=self._work, name="busk-session", daemon=True)
                self._worker.start()

    def stop(self) -> None:
        """Finish the posted commands, then stop the worker."""
        worker = self._worker
        if worker is not None:
            self._posted.put(None)
            worker.join()
            self._worker = None

    def _work(self) -> None:
        while (item := self._posted.get()) is not None:
            command, origin = item
            result = self.submit(command, origin)
            if not result.ok:
                self._report(f"{command['type']}: {result.message}")

    # -------------------------------------------------------- programmer

    def engine_snapshot(self) -> EngineSnapshot | None:
        """The engine's latest snapshot, or ``None`` without an engine (or
        before its first tick)."""
        return None if self._engine_state is None else self._engine_state()

    def _programmer_command(self, command: Command) -> CommandResult:
        engine = self.engine_snapshot()
        change = handle(self._state, self._programmer, command, engine)
        cause = None
        if self._causes:
            logged: Mapping[str, object] = command
            if command["type"] == "SELECT_PLAYBACK":  # what it selected, not what it read
                targets = playback_targets(self._state, command["playbackId"], engine)
                logged = {
                    "type": "SELECT",
                    "targets": {"kind": "targets", "refs": [dict(t) for t in targets]},
                    "mode": command["mode"],
                }
            cause = eventlog.programmer_cause(logged)
        self._set_programmer(
            change.programmer,
            label=change.message,
            step=command["type"] not in _MODES,
            written=change.written,
            written_effects=change.writtenEffects,
            cause=cause,
        )
        return CommandResult(ok=True, message=change.message)

    def _set_programmer(
        self,
        new: Programmer,
        *,
        label: str,
        step: bool,
        written: frozenset[str] = frozenset(),
        written_effects: frozenset[str] = frozenset(),
        cause: bytes | None = None,
        then: Callable[[], object] | None = None,
        publish: bool = True,
    ) -> None:
        """Install ``new`` in the engine and, for content changes, record a step.

        ``written`` slots and ``written_effects`` effect ids count as touched
        even if their value or instance did not change. ``cause`` is the
        install's event-log cause; ``None`` with causes on means the whole
        programmer is logged (an undo, redo or recovery). ``then`` moves the
        timeline (an undo or redo) before the snapshot is published, so the
        snapshot shows both. Without ``publish``, the caller publishes (a
        script's step: its show and its programmer as one change).
        """
        old = self._programmer
        installs = bool(
            written
            or written_effects
            or dict(old.values) != dict(new.values)
            or old.effects != new.effects
            or old.stopped != new.stopped
            or old.blind != new.blind
            or old.highlight != new.highlight
            or (new.highlight and old.selection != new.selection)  # highlight follows it
        )
        if self._causes and (installs or old != new):
            if cause is None:  # an undo, redo or recovery: the whole programmer
                cause = eventlog.state_cause(label, to_json(new))
            self._pending.append(cause)
        if installs:
            frame = build_frame(
                self._state,
                new,
                old.values,
                previous_effects=old.effects,
                written=written,
                written_effects=written_effects,
                touch_all=old.blind and not new.blind,
            )
            self._bus.install(
                Install(
                    compiled=None,
                    remap=None,
                    programmer=frame,
                    causes=self._take_causes(),
                    source=(self._state.show, new),
                )
            )
        if step and not old.same_content(new):
            self.timeline.push(ProgrammerStep(before=old, after=new, label=label))
        if then is not None:
            then()
        self._programmer = new
        self._versions[1] += 1
        if publish:
            self._publish()

    def _take_causes(self) -> tuple[bytes, ...]:
        """The causes waiting for an install, now on one (the lock is held)."""
        causes, self._pending = tuple(self._pending), []
        return causes

    def restore_programmer(self, programmer: Programmer) -> list[str]:
        """Replace the programmer without an undo step (crash recovery).

        Selected targets that no longer exist are dropped, and so are effects
        that no longer validate against the show; returns one message per
        effect dropped.
        """
        with self._lock:
            restored, dropped = drop_invalid_effects(self._state, programmer)
            restored = replace(restored, selection=drop_missing(self._state, restored.selection))
            self._set_programmer(restored, label="recovered programmer", step=False)
            return dropped

    # ------------------------------------------------------------- show

    def _show_command(self, command: Command) -> CommandResult:
        if command["type"] == "BATCH":
            commands: Sequence[Command] = command["commands"]
            if not commands:
                raise CommandError("BATCH holds no commands")
        else:
            commands = [command]
        working = self._state.show
        forward: list[Op] = []
        inverse: list[Op] = []
        messages: list[str] = []
        warnings: list[Issue] = []
        for inner in commands:
            if (
                inner["type"] == "BATCH"
                or command_class(cast(Mapping[str, object], inner)) != "show"
            ):
                raise CommandError(f"a BATCH can only hold show edits, not {inner['type']}")
            edit = self._edit(working, inner)
            working, undo = apply(working, edit.ops)
            forward += edit.ops
            inverse[:0] = undo
            messages.append(edit.message)
            warnings += edit.warnings
        label = (
            command["label"]
            if command["type"] == "BATCH" and command["label"]
            else "; ".join(messages)
        )
        step = ShowStep(forward=tuple(forward), inverse=tuple(inverse), label=label)
        new_warnings = self._commit(working, label, forward, then=lambda: self.timeline.push(step))
        return CommandResult(ok=True, message=label, issues=(*warnings, *new_warnings))

    def _edit(self, show: Show, command: Command) -> edits.Edit:
        """One show-edit handler, against ``show`` (ahead of the committed one in a batch)."""
        state, programmer, ids = self._state, self._programmer, self._ids
        if command["type"] == "RECORD_CUE":
            return record.record_cue(state, show, programmer, command, ids)
        if command["type"] == "RECORD_PRESET":
            return record.record_preset(state, show, programmer, command, ids)
        if command["type"] == "RECORD_GROUP":
            return record.record_group(show, programmer, command, ids)
        if command["type"] == "PATCH_FIXTURE":
            return edits.patch_fixture(show, command)
        if command["type"] == "ASSIGN_PLAYBACK":
            return edits.assign_playback(show, command)
        if command["type"] == "ADD":
            return edits.add(show, command)
        if command["type"] == "SET":
            return edits.set_(show, command)
        if command["type"] == "DELETE":
            return edits.delete(show, command)
        raise CommandError(f"{command['type']} is not a show edit")

    def _commit(
        self,
        candidate: Show,
        label: str,
        ops: Sequence[Op],
        then: Callable[[], object] | None = None,
    ) -> list[Issue]:
        """Validate, compile, install and commit ``candidate``; return the
        warnings it introduced. Raises :class:`CommandError` (nothing changes)
        if it does not validate or compile. ``ops`` made it from the
        committed show: the install's event-log cause. ``then`` changes the
        timeline once nothing can fail, before the snapshot is published, so
        the snapshot shows the show and its undo step together."""
        before = self._state
        show, issues = validate_edit(before.show, candidate)
        errors = [issue for issue in issues if issue.severity == "error"]
        if show is None or errors:
            raise CommandError(f"{label}: rejected, the show would not be valid", errors or issues)
        try:
            compiled = compile_show(show, previous=before.compiled)
        except UnsupportedFeature as exc:
            raise CommandError(f"{label}: rejected, {exc}") from None
        state = ShowState(show=show, compiled=compiled)
        remap = slot_remap(before.compiled.slots, compiled.slots)
        programmer = self._programmer
        frame = build_frame(  # unchanged sources: no touch
            state, programmer, programmer.values, previous_effects=programmer.effects
        )
        known = _warning_keys(state, issues)
        fresh = [w for w in (*issues, *compiled.warnings) if (w.path, w.message) not in self._known]
        self._installs += 1
        stamp = (self._sessionId, self._installs)
        # Nothing below can fail: once the engine has the install, the session commits.
        if self._causes:
            self._pending.append(eventlog.edit_cause(label, ops))
        self._bus.install(
            Install(
                compiled=compiled,
                remap=remap,
                programmer=frame,
                stamp=stamp,
                causes=self._take_causes(),
                source=(show, programmer),
            )
        )
        self._bus.compiled = compiled
        self._state, self._known, self._stamp = state, known, stamp
        self._dirty = True
        self._versions[0] += 1
        if then is not None:
            then()
        self._publish()
        return fresh

    def apply_ops(self, ops: Sequence[Op], label: str) -> CommandResult:
        """Apply patch ops to the show through the validate → compile →
        install path of an undo (``busk replay``: a logged edit). No undo
        step is recorded. Never raises."""
        with self._lock:
            try:
                candidate, _ = apply(self._state.show, ops)
                issues = self._commit(candidate, label, ops)
            except CommandError as exc:
                return CommandResult(ok=False, message=exc.message, issues=exc.issues)
            except Exception as exc:  # a bug must not take the caller down
                return CommandResult(
                    ok=False, message=f"internal error: {type(exc).__name__}: {exc}"
                )
            return CommandResult(ok=True, message=label, issues=tuple(issues))

    # -------------------------------------------------------- undo, redo

    def _session_command(self, command: Command) -> CommandResult:
        if command["type"] == "UNDO":
            return self._undo()
        if command["type"] == "REDO":
            return self._redo()
        if command["type"] == "UNDO_GROUP":
            label = command["label"]
            if not label.strip():
                raise CommandError("an undo group needs a label")
            closed = self.timeline.open_group(label)
            opened = f"undo group {short(label)} is open"
            return CommandResult(
                ok=True, message=opened if closed is None else f"{_closed(closed)}; {opened}"
            )
        closed = self.timeline.close_group()
        if closed is None:
            raise CommandError("no undo group is open")
        return CommandResult(ok=True, message=_closed(closed))

    def _undo(self) -> CommandResult:
        step = self.timeline.next_undo()
        if step is None:
            raise CommandError("nothing to undo")
        label, moved = f"undo {step.label}", self.timeline.undone
        if isinstance(step, ShowStep):
            self._commit(apply(self._state.show, step.inverse)[0], label, step.inverse, moved)
        elif isinstance(step, ProgrammerStep):
            self._restore(step.before, label, moved)
        else:
            self._script_step(step.inverse, step.before, label, moved)
        return CommandResult(ok=True, message=f"undid: {step.label}")

    def _redo(self) -> CommandResult:
        step = self.timeline.next_redo()
        if step is None:
            raise CommandError("nothing to redo")
        label, moved = f"redo {step.label}", self.timeline.redone
        if isinstance(step, ShowStep):
            self._commit(apply(self._state.show, step.forward)[0], label, step.forward, moved)
        elif isinstance(step, ProgrammerStep):
            self._restore(step.after, label, moved)
        else:
            self._script_step(step.forward, step.after, label, moved)
        return CommandResult(ok=True, message=f"redid: {step.label}")

    def _script_step(
        self,
        ops: Sequence[Op],
        programmer: Programmer | None,
        label: str,
        moved: Callable[[], object],
    ) -> None:
        """Undo or redo a :class:`~busk.session.timeline.ScriptStep`: its
        show ops, then its programmer (``None``: the script changed none),
        published as one change. Nothing changes if the show would not
        validate or compile."""
        if programmer is None:
            self._commit(apply(self._state.show, ops)[0], label, ops, moved)
        elif not ops:
            self._restore(programmer, label, moved)
        else:
            self._commit(
                apply(self._state.show, ops)[0],
                label,
                ops,
                lambda: self._restore(programmer, label, moved, publish=False),
            )

    def _restore(
        self,
        target: Programmer,
        label: str,
        then: Callable[[], object],
        *,
        publish: bool = True,
    ) -> None:
        """Restore a programmer step's selection and values; the modes (blind,
        the fade time, highlight) keep their state. Selected targets that no longer exist
        are dropped. ``then`` moves the timeline, as for :meth:`_commit`;
        ``publish`` is :meth:`_set_programmer`'s."""
        selection = drop_missing(self._state, target.selection)
        current = self._programmer
        restored = replace(
            target,
            selection=selection,
            blind=current.blind,
            fadeTime=current.fadeTime,
            highlight=current.highlight,
        )
        self._set_programmer(restored, label=label, step=False, then=then, publish=publish)

    @contextlib.contextmanager
    def script(self, label: str) -> Iterator[None]:
        """Make the steps of the block one, labelled ``label`` (``source
        rig.busk``), while a script runs in it (GAP-56 of
        ``docs/dev/tui/engine-gaps.md``; :mod:`busk.session.timeline`). A
        script run inside it joins its step. Steps another thread pushes
        meanwhile join it too, as they join an undo group."""
        with self._lock:
            self.timeline.open_script(label)
        try:
            yield
        finally:
            with self._lock:
                self.timeline.close_script()

    # -------------------------------------------------------------- save

    def save(self, path: Path | None = None) -> CommandResult:
        """Write the show (default: where it was loaded from), backing up the
        file it replaces. Sets ``meta.modified``; not an undo step.

        Saving to another file than the show's own makes a new show (GAP-55
        of ``docs/dev/tui/engine-gaps.md``): the copy gets a new ``meta.id``,
        and ``meta.created`` is now, so its autosaves and crash recovery are
        its own. The two paths are compared resolved. A show without a file
        keeps its id on its first save. The show's file is ``path`` from now
        on."""
        with self._lock:
            target = path if path is not None else self._path
            if target is None:
                return CommandResult(ok=False, message="no file to save to: give a path")
            now = self._wall_clock()
            stamp = iso_time(now)
            original = self._path
            copy = original is not None and target.resolve() != original.resolve()
            ops = [Op("replace", ("meta", "modified"), stamp)]
            if copy:
                taken = {self._state.show["meta"]["id"]}
                ops += [
                    Op("replace", ("meta", "id"), self._ids.new("show", taken)),
                    Op("replace", ("meta", "created"), stamp),
                ]
            show, _ = apply(self._state.show, ops)
            try:
                save_show(show, target, now=now)
            except (OSError, ValueError) as exc:
                return CommandResult(ok=False, message=f"cannot save {str(target)!r}: {exc}")
            self._state = ShowState(show=show, compiled=self._state.compiled)
            self._path = target
            self._dirty = False
            self._versions[0] += 1
            self._versions[2] += 1
            self._saved = (self._versions[0], self._stamp)
            self._publish()
            if copy:
                said = f"saved {target} as a new show; {original} stays as it was saved"
                return CommandResult(ok=True, message=said)
            return CommandResult(ok=True, message=f"saved {target}")

    # ----------------------------------------------------------- helpers

    def _publish(self) -> None:
        state, timeline = self._state, self.timeline
        undo, redo = timeline.next_undo(), timeline.next_redo()
        self.snapshot = SessionSnapshot(
            show=state.show,
            compiled=state.compiled,
            state=state,
            programmer=self._programmer,
            dirty=self._dirty,
            showVersion=self._versions[0],
            programmerVersion=self._versions[1],
            saves=self._versions[2],
            savedVersion=self._saved[0],
            savedStamp=self._saved[1],
            path=self._path,
            stamp=self._stamp,
            undoSteps=timeline.undo_count,
            redoSteps=timeline.redo_count,
            nextUndo=None if undo is None else undo.label,
            nextRedo=None if redo is None else redo.label,
        )


def _closed(group: Group) -> str:
    """``closed undo group "pan drag": 30 steps, undone as one``."""
    said = f"closed undo group {short(group.label)}"
    if group.steps == 0:
        return f"{said}, which took no step"
    if group.steps == 1:
        return f"{said}: 1 step"
    return f"{said}: {group.steps} steps, undone as one"


def _warning_keys(state: ShowState, issues: Sequence[Issue]) -> set[tuple[str, str]]:
    """The warnings a committed show has, validation's and the compiler's."""
    return {
        (issue.path, issue.message)
        for issue in (*issues, *state.compiled.warnings)
        if issue.severity == "warning"
    }


class InputSink:
    """What input bindings submit to: :meth:`Session.post` behind the bus's
    ``submit(command, origin)`` signature, so a binding works the same with a
    bare bus (Phase 2) or a session (programmer and show-edit commands too)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def submit(self, command: Command, origin: CommandOrigin | None = None) -> None:
        self._session.post(command, origin)
