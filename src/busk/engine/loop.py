"""The engine loop (spec §4.2, §11.2).

The engine ticks at a fixed rate (``output.engineHz``). Each tick runs the
§4.2 pipeline and publishes an immutable :class:`Frame`. Phases 2–3 run
these stages:

==========================  ==================================================
§4.2 stage                  Phases 2–3
==========================  ==================================================
1 Due events, commands      :meth:`Playbacks.advance
                            <busk.engine.playback_runtime.Playbacks.advance>`
                            fires every auto-GO and chase step due by
                            ``now`` at its own time (Phase 4, decision 2);
                            then
                            :meth:`CommandBus.drain <busk.commands.bus.CommandBus.drain>`
                            → apply each command at the tick's time, and
                            each :class:`~busk.engine.install.Install` (a
                            live edit: a swapped-in compiled show and/or a
                            programmer frame), guarded: an exception is
                            counted and the tick goes on
2 Clocks                    ``now`` only (effects are functions of it too)
3–4 Playbacks, fades        ``advance`` again (the events the commands
                            made due at ``now``), then :meth:`Playbacks.update
                            <busk.engine.playback_runtime.Playbacks.update>`:
                            finished releases go idle, sources get weights;
                            the programmer's fades are evaluated
5 Effects                   inside the playbacks' and the programmer's
                            updates: each bank (main, flash, programmer)
                            evaluates its clocks, waveforms and versions
                            (:class:`~busk.engine.effects.EffectBank`)
6–7 Gather, resolve         :func:`~busk.engine.contributions.gather` (the
                            playbacks and their effects, plus the
                            programmer at band 100 while it holds lanes,
                            and its effects),
                            and :func:`~busk.engine.contributions.
                            gather_relatives`, then the
                            :class:`~busk.engine.resolver.Resolver`'s
                            absolute pass
8 Relative pass             the resolver's relative pass and its clamps
                            (phase-5-plan §5.6)
9–10 Masters                :func:`~busk.engine.masters.apply_masters`:
                            group masters (their factor is recomputed only
                            when a level or the show changes), then the
                            grand master
11 Safety                   :func:`~busk.engine.safety.apply_safety`
                            (Phase 7): the programmer's highlight, park
                            (intensity), blackout, park (every other
                            lane), limits, the strobe cap
12 Profile conversion       the :class:`~busk.convert.converter.Converter`
                            writes every slot-driven channel over a copy of
                            the base images, so untouched channels keep their
                            ``defaultDmx`` (§13.5); then the highlight's
                            ``highlightDmx`` bytes, unless in blackout
13 Publish                  a :class:`Frame` of ``bytes``, by one reference
                            assignment (Python's §14.1 double-buffer swap:
                            readers never see a half-written frame, and no
                            lock is needed); an :class:`EngineSnapshot` when
                            the state changed; while :attr:`Engine.captureOutput`
                            is set, a :class:`~busk.engine.readout.Capture`
                            of the stage 11 frame (GAP-01), and while
                            :attr:`Engine.captureEffects` is set, an
                            :class:`~busk.engine.effect_status.EffectCapture`
                            of the running effects (GAP-09)
==========================  ==================================================

**Determinism** (§2.7). Every runtime value is a function of the commands
applied and of ``now``: commands take effect at the time of the tick that
drains them, auto-GOs and chase steps at the exact time they are due, and
fades, chase positions and beat counts are pure functions of time. The same commands at the
same tick times on a :class:`~busk.engine.clock.FakeClock` produce
byte-identical frames, whatever ticks run in between.

**The event log** (Phase 7, phase-7-plan §5.21). While :attr:`Engine.records`
is a deque, the tick appends ``(now, item)`` to it for each command envelope
it drains, each cause an install carries (its bytes) and each restore, at
the time of the tick that applies them. A writer elsewhere takes them
(:mod:`busk.persistence.eventlog`); a full deque drops the record and counts
it (``EngineStats.logDropped``).

**Real-time rules** (§19). The tick does no I/O or logging. It allocates
only the published ``bytes`` and :class:`Frame` objects, a snapshot when the
state changed, captures while the output or the effects are read, and numpy
temporaries;
none of the per-tick ones are tracked by the cyclic garbage collector, so
they add no GC pauses.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import chain
from typing import Final

import numpy as np
from numpy.typing import NDArray

from busk.commands.bus import CommandBus
from busk.commands.types import (
    Command,
    CommandEnvelope,
    CommandOrigin,
    PlaybackButtonCmd,
    SetFaderCmd,
)
from busk.compiler.compile import CompiledShow, OutputLayout
from busk.compiler.playbacks import MasterKind
from busk.convert.converter import Converter
from busk.engine.clock import Clock, FixedRateSchedule
from busk.engine.contributions import Relative, Source, gather, gather_relatives
from busk.engine.effect_status import EffectCapture, capture_effects
from busk.engine.install import Install, ProgrammerRuntime, lane_maps, remap_lanes
from busk.engine.masters import (
    SpeedMasterRuntime,
    apply_masters,
    fade_override,
    grand_master_level,
    group_factor,
    speed_masters,
)
from busk.engine.playback_runtime import PlaybackRuntime, Playbacks
from busk.engine.readout import Capture, capture
from busk.engine.resolver import Resolver
from busk.engine.safety import apply_safety
from busk.engine.snapshot import (
    EngineSnapshot,
    PageStatus,
    PlaybackStatus,
    Restore,
    SpeedStatus,
    Sync,
)
from busk.engine.surfaces import HELD, HeldButtons, Knob, PageState, Pickup
from busk.model.common import MasterId, PlaybackId

RECORDS_MAX: Final = 1 << 16
"""Event-log records :attr:`Engine.records` holds at most: a writer that
falls this far behind loses records rather than the engine memory."""

type Record = tuple[float, CommandEnvelope | bytes | Restore]
"""An event-log record as the tick appends it: the tick's time, and the
envelope it applied, the cause of an install, or a restore."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Frame:
    """One published engine output: a DMX image per universe.

    ``compiled`` is the compiled show the frame was made with. Its
    ``universes`` name the rows of :attr:`universes`, and when it changes (a
    live edit, Phase 3) the output thread reconciles its routes and the
    input layer its bindings. It is ``None`` only for frames built by hand in
    tests.

    ``layout`` (Phase 7) is what the output needs of that show
    (:class:`~busk.compiler.compile.OutputLayout`: the dark bytes of a
    stall), and ``outputEnabled`` the engine's ``OUTPUT`` state: while it
    is off, routes send nothing (decision 15).
    """

    seq: int  # 1 for the first frame, +1 per tick
    time: float  # engine time of the tick that produced the frame
    universes: tuple[bytes, ...]  # 512 bytes each, in compiled.universes order
    compiled: CompiledShow | None = None
    layout: OutputLayout | None = None
    outputEnabled: bool = True


@dataclass(kw_only=True)
class EngineStats:
    """Counters kept by the engine thread. Read them once :meth:`Engine.run`
    has returned; while it runs they are updated without synchronisation."""

    ticks: int = 0
    overruns: int = 0  # ticks that finished after the next tick was due
    maxTickSeconds: float = 0.0  # longest tick, measured on the engine clock
    commandsApplied: int = 0
    commandErrors: int = 0  # commands whose application raised
    installs: int = 0  # live edits applied (Phase 3)
    installErrors: int = 0  # installs (and restores, Phase 7) whose application raised
    tickErrors: int = 0  # ticks that raised (Phase 7); the schedule goes on
    consecutiveTickErrors: int = 0  # since the last good tick (an engine host exits at 10)
    logDropped: int = 0  # event-log records dropped: the writer fell behind (Phase 7)


@dataclass(kw_only=True)
class EngineRuntime:
    """The engine's runtime state (§5.18), owned by the engine thread.

    ``playbacks`` holds every playback runtime, the global ``seqCounter``,
    the speed masters' runtimes (Phase 4), which chases and effects follow,
    and the size masters' levels (Phase 5), which effects read.
    ``masterLevels`` holds the grand masters' levels and ``groupLevels`` the
    group masters' levels (Phase 5), and ``fadeLevels`` the fade-time
    masters' levels (Phase 6), each in show order. ``page`` is the
    current playback page, shared by every surface, ``held`` the flash
    and swop buttons held down through a slot, and ``pickup`` the soft
    takeover state of every control (Phase 6). ``outputEnabled`` is the
    ``OUTPUT`` state (Phase 7), carried in every frame.
    """

    now: float = 0.0
    playbacks: Playbacks
    page: PageState
    held: HeldButtons = field(default_factory=HeldButtons)
    pickup: Pickup = field(default_factory=Pickup)
    masterLevels: dict[MasterId, float] = field(default_factory=dict)
    groupLevels: dict[MasterId, float] = field(default_factory=dict)
    fadeLevels: dict[MasterId, float] = field(default_factory=dict)
    blackout: bool = False
    outputEnabled: bool = True

    @property
    def speed(self) -> dict[MasterId, SpeedMasterRuntime]:
        """The speed masters' runtimes, by id, in show order."""
        return self.playbacks.speed

    @property
    def sizeLevels(self) -> dict[MasterId, float]:
        """The size masters' levels, by id, in show order (shared with every
        effect bank)."""
        return self.playbacks.sizeLevels

    @property
    def grandMaster(self) -> float:
        """The combined grand master level."""
        return grand_master_level(self.masterLevels.values())


class Engine:
    """Runs the per-tick pipeline and publishes frames and snapshots.

    Only the engine thread mutates engine state (§16). Other threads submit
    commands through :attr:`bus` and read :attr:`latest` and
    :attr:`snapshot`, which always refer to complete, immutable objects.
    """

    def __init__(
        self,
        compiled: CompiledShow,
        clock: Clock,
        base: NDArray[np.float64] | None = None,
    ) -> None:
        """``base`` is the logical frame that uncontrolled slots output: the
        slot defaults (``compiled.slots.defaultFrame``) unless given, for
        example by ``busk run --values``."""
        self._compiled = compiled
        self._clock = clock
        self._custom_base = base is not None  # a --values frame, remapped on live swaps
        if base is None:
            base = compiled.slots.defaultFrame
        if base.shape != (compiled.slots.laneCount,):
            raise ValueError(
                f"base logical frame has shape {base.shape}; expected ({compiled.slots.laneCount},)"
            )
        self._base = base
        self.bus = CommandBus(compiled, clock)
        self.runtime = EngineRuntime(
            playbacks=Playbacks(compiled.playbacks, compiled.slots),
            page=PageState(compiled.pages),
            masterLevels={master.id: master.initialLevel for master in compiled.grandMasters},
            groupLevels=_levels(compiled, "group"),
            fadeLevels=_levels(compiled, "fadeTime"),
        )
        self.runtime.playbacks.set_size_levels(_levels(compiled, "size"))
        self.runtime.playbacks.cap.hz = compiled.safety.strobeMaxHz
        self._refresh_fade()
        self._group: NDArray[np.float64] | None = None  # the group masters' factor
        self._refresh_group_factor()
        # Buffers are allocated once: the working logical frame, the gathered
        # sources and relatives, the back buffer and its per-universe row
        # views, and the resolver's and converter's scratch.
        self._work = np.empty(compiled.slots.laneCount, dtype=np.float64)
        self._sources: list[Source] = []
        self._relatives: list[Relative] = []
        self._back = np.zeros_like(compiled.baseImages)
        self._rows = tuple(self._back)
        self._resolver = Resolver(compiled.slots)
        self._converter = Converter(compiled.plan)
        playbacks = self.runtime.playbacks
        self._programmer = ProgrammerRuntime(
            compiled.slots, playbacks.speed, playbacks.sizeLevels, playbacks.cap
        )
        self._dirty = True  # the snapshot is stale; the first tick publishes one
        self.latest: Frame | None = None
        self.snapshot: EngineSnapshot | None = None
        self.stats = EngineStats()
        self.synced = 0
        """The token of the newest :class:`~busk.engine.snapshot.Sync` drained,
        set once the tick that drained it has published its snapshot."""
        self.records: deque[Record] | None = None
        """The event log's records (see the module docs); ``None``: no log.
        Set it before the first tick; the tick appends, a writer pops from
        the left."""
        self.captureOutput = False
        """Whether each tick publishes :attr:`output` (GAP-01). Any thread
        may set it; the engine never does, so an engine nobody reads the
        output of pays nothing for it."""
        self.output: Capture | None = None
        """The output of the newest tick that captured it, for
        :func:`~busk.engine.readout.read_output`; ``None`` before."""
        self.captureEffects = False
        """Whether each tick publishes :attr:`effects` (GAP-09); like
        :attr:`captureOutput`, any thread may set it."""
        self.effects: EffectCapture | None = None
        """The running effects of the newest tick that captured them, for
        :func:`~busk.engine.effect_status.read_effects`; ``None`` before."""

    @property
    def compiled(self) -> CompiledShow:
        """The compiled show the engine runs now (engine thread; others read
        :attr:`Frame.compiled` of :attr:`latest`)."""
        return self._compiled

    @property
    def logical(self) -> NDArray[np.float64]:
        """The logical frame of the last tick, after masters (read-only view).

        For tests and diagnostics on the engine thread: the next tick
        overwrites it.
        """
        view = self._work.view()
        view.flags.writeable = False
        return view

    def tick(self, now: float) -> None:
        """Run one pass of the §4.2 pipeline for engine time ``now``."""
        runtime = self.runtime
        runtime.now = now
        if not self.stats.ticks:  # speed masters count beats from the first tick (§5.8)
            runtime.playbacks.set_speed(speed_masters(self._compiled.masters.values(), now))

        # Stage 1 — fire the auto-GOs due by `now`, each at its own time, so
        # commands see the state they would see on any tick schedule; then
        # drain the command queue: each command is applied at `now`, each
        # live edit (Install) in the order the session committed it.
        if runtime.playbacks.advance(now):
            self._dirty = True
        synced: Sync | None = None
        records = self.records
        for item in self.bus.drain():
            if isinstance(item, Sync):  # a marker: published after this tick (Phase 7)
                synced = item
                continue
            if isinstance(item, Install):
                if records is not None:
                    for cause in item.causes:
                        self._record(records, now, cause)
                try:
                    self._install(item)
                except Exception:  # live-safe (§1.1): count it, keep ticking
                    self.stats.installErrors += 1
                else:
                    self.stats.installs += 1
                self._dirty = True
                continue
            if isinstance(item, Restore):  # after an engine restart (Phase 7)
                if records is not None:
                    self._record(records, now, item)
                try:
                    self._restore(item.snapshot, now)
                except Exception:  # live-safe (§1.1): count it, keep ticking
                    self.stats.installErrors += 1
                self._dirty = True
                continue
            if records is not None:
                self._record(records, now, item)
            try:
                self._apply(item["command"], now, item["origin"])
            except Exception:  # live-safe (§1.1): count it, keep ticking
                self.stats.commandErrors += 1
            else:
                self.stats.commandsApplied += 1
            self._dirty = True

        # Stages 3–4 — fire what the commands made due at `now`, then advance
        # playbacks and their presence fades.
        if runtime.playbacks.advance(now):
            self._dirty = True
        if runtime.playbacks.update(now):
            self._dirty = True
        self._programmer.update(now)

        # Stages 6–8 — gather the present sources, split into sequence runs,
        # and the effects' relative layers, then resolve: the absolute pass,
        # then the relative pass. The programmer is one more contributor (band
        # 100), present while it holds lanes (fading out after a clear or
        # blind on), and so is each of its effects.
        programmer = self._programmer
        sources = gather(
            chain(runtime.playbacks.sources(), (programmer,), programmer.bank.contributors()),
            self._sources,
        )
        relatives = gather_relatives(
            chain(runtime.playbacks.relatives(), programmer.bank.relatives()), self._relatives
        )
        self._resolver.resolve(sources, self._base, self._work, relatives)

        # Stages 9–10 — group masters and the grand master, on the output
        # frame only. Stage 11 — the safety stage: highlight, park, blackout
        # (which moved here in Phase 7, so it darkens a parked intensity but
        # no other parked lane), limits, the strobe cap.
        intensity = self._compiled.slots.intensityLanes
        highlight = programmer.highlight
        apply_masters(self._work, intensity, runtime.grandMaster, False, self._group)
        apply_safety(
            self._work,
            self._compiled.safety,
            intensity,
            blackout=runtime.blackout,
            highlight=highlight,
        )

        # Stage 12 — profile conversion: untouched channels keep their base
        # value (§13.5), slot-driven channels are converted over it. Then the
        # highlight's highlightDmx bytes, except in blackout, which wins.
        np.copyto(self._back, self._compiled.baseImages)
        self._converter.convert(self._work, self._back)
        if highlight is not None and highlight.bytes.size and not runtime.blackout:
            np.put(self._back, highlight.bytes, highlight.byteValues)

        # Stage 13 — publish immutable snapshots with one reference assignment each.
        self.stats.ticks += 1
        self.latest = Frame(
            seq=self.stats.ticks,
            time=now,
            universes=tuple(row.tobytes() for row in self._rows),
            compiled=self._compiled,
            layout=self._compiled.layout,
            outputEnabled=runtime.outputEnabled,
        )
        if self.captureOutput:
            self.output = self.capture()
        if self.captureEffects:
            self.effects = self.capture_effects()
        if self._dirty:
            self._dirty = False
            self._publish_snapshot(now)
        if synced is not None:
            self.synced = synced.token

    def capture(self) -> Capture:
        """The output of the last tick, with what drives each lane (GAP-01,
        :mod:`busk.engine.readout`). Engine thread only, between two ticks:
        it reads the last tick's sources. The tick calls it while
        :attr:`captureOutput` is set; an engine ticked by its caller
        (:class:`~busk.runner.OfflineShow`) may call it whenever it likes."""
        return capture(
            seq=self.stats.ticks,
            time=self.runtime.now,
            compiled=self._compiled,
            frame=self._work,
            resolver=self._resolver,
            sources=self._sources,
            relatives=self._relatives,
            highlight=self._programmer.highlight,
        )

    def capture_effects(self) -> EffectCapture:
        """The effects of the last tick (GAP-09, :mod:`busk.engine.effect_status`):
        the playbacks' banks in show order, main then flash, then the
        programmer's. Engine thread only, between two ticks, as
        :meth:`capture`."""
        playbacks = self.runtime.playbacks.runtimes.values()
        return capture_effects(
            seq=self.stats.ticks,
            time=self.runtime.now,
            compiled=self._compiled,
            banks=chain(
                chain.from_iterable((rt.bank, rt.flashBank) for rt in playbacks),
                (self._programmer.bank,),
            ),
        )

    def run(self, stop: threading.Event, after_tick: Callable[[], None] | None = None) -> None:
        """Tick at ``engineHz`` until ``stop`` is set (§11.2).

        The first tick runs at once. A tick that ends after the next one was
        due counts as an overrun, and the schedule restarts from the current
        time instead of catching up (drop, don't spiral; see
        :class:`~busk.engine.clock.FixedRateSchedule`).

        A tick that raises (a bug) is counted in ``tickErrors`` and
        ``consecutiveTickErrors`` and the schedule goes on: the output keeps
        the last frame meanwhile (phase-7-plan §5.14). A good tick resets the
        consecutive count; deciding to give up is the engine host's.

        ``after_tick`` (Phase 7) is called after every tick, good or not,
        before the wait: the engine host wakes its publishers there and
        counts tick errors. It must be quick; it runs on the engine thread.
        """
        clock = self._clock
        hz = self._compiled.engineHz
        schedule = FixedRateSchedule(clock, hz)
        stats = self.stats
        while not stop.is_set():
            started = clock.now()
            try:
                self.tick(started)
            except Exception:  # live-safe (§1.1): count it, keep the schedule
                stats.tickErrors += 1
                stats.consecutiveTickErrors += 1
            else:
                stats.consecutiveTickErrors = 0
            self.stats.maxTickSeconds = max(self.stats.maxTickSeconds, clock.now() - started)
            if after_tick is not None:
                after_tick()
            if self._compiled.engineHz != hz:  # a live edit changed the rate
                hz = self._compiled.engineHz
                schedule = FixedRateSchedule(clock, hz)
            if schedule.wait_next():
                self.stats.overruns += 1

    def _apply(self, command: Command, now: float, origin: CommandOrigin) -> None:
        """Apply one validated performance command (stage 1), sent from ``origin``.

        ``SET_FADER`` and ``SET_MASTER`` pass soft takeover first
        (:meth:`_takes_over`): a soft control's move that has not met the
        level yet is ignored.
        """
        playbacks = self.runtime.playbacks
        if command["type"] == "TRIGGER_PLAYBACK":
            playbacks.trigger(command["playbackId"], now)
        elif command["type"] == "RELEASE_PLAYBACK":
            playbacks.release(command["playbackId"], now, command.get("time"))
        elif command["type"] == "TOGGLE_PLAYBACK":
            playbacks.toggle(command["playbackId"], now)
        elif command["type"] == "FLASH":
            playbacks.flash(command["playbackId"], command["down"], now)
        elif command["type"] == "GO":
            playbacks.go(command["playbackId"], now)
        elif command["type"] == "BACK":
            playbacks.back(command["playbackId"], now)
        elif command["type"] == "GOTO":
            playbacks.goto(command["playbackId"], command["cueNumber"], now)
        elif command["type"] == "SET_FADER":
            playback, level = self._playback_of(command), command["level"]
            if playback is None:  # an empty slot does nothing, but the hardware moved
                self.runtime.pickup.missed(origin.get("control"), level)
            elif self._takes_over(
                origin, ("fader", playback), playbacks.runtimes[playback].faderLevel, level
            ):
                playbacks.set_fader(playback, level, now)
        elif command["type"] == "PLAYBACK_BUTTON":
            self._button(command, now, origin.get("control"))
        elif command["type"] == "PAGE":
            self.runtime.page.go(number=command.get("number"), delta=command.get("delta"))
        elif command["type"] == "SET_MASTER":
            ident, level = command["masterId"], command["level"]
            if self._takes_over(origin, ("master", ident), self._master_level(ident), level):
                self._set_master(ident, level, now)
        elif command["type"] == "TAP":
            playbacks.tap(command["masterId"], now, (self._programmer.bank,))
        elif command["type"] == "SET_BPM":
            playbacks.set_bpm(command["masterId"], command["bpm"], now, (self._programmer.bank,))
        elif command["type"] == "BLACKOUT":  # without `on`, a toggle (Phase 6)
            self.runtime.blackout = command.get("on", not self.runtime.blackout)
        elif command["type"] == "RELEASE_ALL":  # Phase 7 panic
            playbacks.release_all(now, command.get("time"))
        elif command["type"] == "OUTPUT":  # Phase 7: the output reads it from each frame
            self.runtime.outputEnabled = command["on"]
        else:  # the bus rejects every other type
            raise ValueError(f"unsupported command {command['type']}")

    def _button(self, command: PlaybackButtonCmd, now: float, control: str | None) -> None:
        """Apply ``PLAYBACK_BUTTON`` (phase-6-plan decision 3).

        The function is the playback's ``buttons[button]``; an empty slot or
        a button the playback does not have does nothing. A flash or swop
        pressed through a slot by a ``control`` is held for that control
        (:class:`~busk.engine.surfaces.HeldButtons`), and the control's
        release goes to the same playback and function.
        """
        down, held = command["down"], self.runtime.held
        record = None if down or control is None else held.release(control)
        if record is not None:
            playback, function = record
        else:
            found = self._playback_of(command)
            if found is None:
                return
            playback, buttons = found, self._compiled.playbacks[found].buttons
            if command["button"] >= len(buttons):
                return
            function = buttons[command["button"]]
            if down and control is not None and "slot" in command and function in HELD:
                held.press(control, playback, function)
        self.runtime.playbacks.button(playback, function, down, now)

    def _takes_over(self, origin: CommandOrigin, knob: Knob, level: float, value: float) -> bool:
        """Whether a move to ``value`` from ``origin`` applies to ``knob``, now
        at ``level`` (soft takeover, :class:`~busk.engine.surfaces.Pickup`).
        Soft are the controls bound on a ``faderPickup: "soft"`` surface."""
        control = origin.get("control")
        soft = control is not None and control in self._compiled.softControls
        return self.runtime.pickup.accept(control, soft, knob, level, value)

    def _master_level(self, ident: MasterId) -> float:
        """The current level of master ``ident``, whatever its kind (a
        ``KeyError`` if an edit deleted it)."""
        runtime = self.runtime
        kind = self._compiled.masters[ident].kind
        if kind == "grand":
            return runtime.masterLevels[ident]
        if kind == "group":
            return runtime.groupLevels[ident]
        if kind == "size":
            return runtime.sizeLevels[ident]
        if kind == "speed":
            return runtime.speed[ident].level
        if kind == "fadeTime":
            return runtime.fadeLevels[ident]
        raise ValueError(f"unsupported master kind {kind}")

    def _set_master(self, ident: MasterId, level: float, now: float) -> None:
        """``SET_MASTER``: set master ``ident``'s level, by its kind."""
        runtime = self.runtime
        kind = self._compiled.masters[ident].kind
        if kind == "grand":
            runtime.masterLevels[ident] = level
        elif kind == "group":
            runtime.groupLevels[ident] = level
            self._refresh_group_factor()
        elif kind == "size":  # read live by the effects that name it
            runtime.sizeLevels[ident] = level
        elif kind == "speed":
            runtime.playbacks.set_speed_level(ident, level, now, (self._programmer.bank,))
        elif kind == "fadeTime":  # read by the transitions that start from now on
            runtime.fadeLevels[ident] = level
            self._refresh_fade()
        else:
            raise ValueError(f"unsupported master kind {kind}")

    def _playback_of(self, command: SetFaderCmd | PlaybackButtonCmd) -> PlaybackId | None:
        """The playback a page-relative command names: its ``playbackId``, or
        the playback on its ``slot`` of the current page (``None``: empty)."""
        if "slot" in command:
            return self.runtime.page.playback(command["slot"])
        return command["playbackId"]

    def _record(
        self, records: deque[Record], now: float, item: CommandEnvelope | bytes | Restore
    ) -> None:
        """Append one event-log record, or count it dropped when the deque is full."""
        if len(records) < RECORDS_MAX:
            records.append((now, item))
        else:
            self.stats.logDropped += 1

    def _install(self, item: Install) -> None:
        """Apply a live edit (stage 1): swap the compiled show if there is one,
        then install the programmer frame built against it."""
        if item.compiled is not None:
            self._swap(item.compiled, item.remap)
        runtime = self.runtime
        self._programmer.install(item.programmer, runtime.now, runtime.playbacks.next_seq)

    def _restore(self, snapshot: EngineSnapshot, now: float) -> None:
        """Put back the look of ``snapshot``, which an engine that ran the
        same show published before it was restarted (phase-7-plan decision
        5, §5.7). Applied at stage 1, after the first install:

        1. **Masters.** Every level in ``masterLevels``, with no takeover;
           each speed master its tempo, level and beat anchor ``(beatTime,
           beat)`` as ``(T0, B0)``. Every process reads the same monotonic
           clock, so chases and effects land back on the same beat grid.
        2. **State.** Blackout, output enabled, and the page by id.
        3. **Playbacks.** In ascending ``seq``, so the LTP stack is rebuilt
           in activation order: each fader at its level, and each active
           playback at its cue (chases at that step), all with the fade-time
           override forced to 0 s, so they snap
           (:meth:`~busk.engine.playback_runtime.Playbacks.restore`).

        Not restored: fades in progress (they snap to their target), Hz
        effect phases, releasing playbacks, held flashes and swops, and
        soft-takeover attachments. Masters, playbacks and pages the show no
        longer has are skipped.
        """
        runtime, compiled = self.runtime, self._compiled
        playbacks = runtime.playbacks
        for ident, level in snapshot.masterLevels:
            master = compiled.masters.get(ident)
            if master is not None and master.kind != "speed":
                self._set_master(ident, level, now)
        for speed in snapshot.speed:
            clock = runtime.speed.get(speed.id)
            if clock is not None:
                clock.bpm, clock.T0, clock.B0 = speed.bpm, speed.beatTime, speed.beat
                playbacks.set_speed_level(speed.id, speed.level, now, (self._programmer.bank,))
        runtime.blackout = snapshot.blackout
        runtime.outputEnabled = snapshot.outputEnabled
        if snapshot.page is not None:
            page = next((p for p in compiled.pages if p.id == snapshot.page.id), None)
            if page is not None:
                runtime.page.go(number=page.number)
        playbacks.fade.time = 0.0
        try:
            for status in sorted(snapshot.playbacks, key=lambda status: status.seq):
                rt = playbacks.runtimes.get(status.id)
                if rt is None:
                    continue
                cue = None
                if status.state == "active":
                    found = None if status.cue is None else rt.playback.cueList.find(status.cue)
                    cue = rt.first_cue() if found is None else found
                playbacks.restore(status.id, cue, status.faderLevel, now)
        finally:
            self._refresh_fade()

    def _swap(self, compiled: CompiledShow, remap: NDArray[np.int32] | None) -> None:
        """Swap in a recompiled show at a tick boundary (§6.4), keeping the runtime state.

        Per-slot runtime arrays follow ``remap``; running playbacks are
        re-pointed at their new cues; grand, group and size masters keep
        their levels (new ones start at their initial level) and speed
        masters their tempo, phase and level (new ones start counting now);
        the group factor is rebuilt, since a group or the patch may have
        changed; the current page is kept by id (Phase 6); buffers are
        reallocated only when their size changed.
        """
        old = self._compiled
        self._compiled = compiled
        if self._custom_base:
            self._base = remap_lanes(self._base, old.slots, compiled.slots, remap)
        else:
            self._base = compiled.slots.defaultFrame
        if compiled.slots.laneCount != old.slots.laneCount:
            self._work = np.empty(compiled.slots.laneCount, dtype=np.float64)
        if compiled.baseImages.shape != self._back.shape:
            self._back = np.zeros_like(compiled.baseImages)
            self._rows = tuple(self._back)
        self._resolver = Resolver(compiled.slots)
        self._converter = Converter(compiled.plan)
        runtime = self.runtime
        maps = None if compiled.slots is old.slots else lane_maps(old.slots, compiled.slots, remap)
        self._programmer.swap(compiled.slots, maps)
        speed = speed_masters(compiled.masters.values(), runtime.now, runtime.speed)
        runtime.playbacks.set_speed(speed)  # before the chases rebind to their masters
        runtime.playbacks.set_size_levels(_levels(compiled, "size", runtime.sizeLevels))
        runtime.playbacks.cap.hz = compiled.safety.strobeMaxHz  # the rebind re-rates under it
        runtime.playbacks.rebind(compiled.playbacks, runtime.now, compiled.slots, maps)
        runtime.masterLevels = {
            master.id: runtime.masterLevels.get(master.id, master.initialLevel)
            for master in compiled.grandMasters
        }
        runtime.groupLevels = _levels(compiled, "group", runtime.groupLevels)
        self._refresh_group_factor()
        runtime.fadeLevels = _levels(compiled, "fadeTime", runtime.fadeLevels)
        self._refresh_fade()
        runtime.page.rebind(compiled.pages)

    def _refresh_fade(self) -> None:
        """Recompute the fade-time override from the fade-time masters'
        levels: after one's ``SET_MASTER`` and after a swap."""
        self.runtime.playbacks.fade.time = fade_override(
            self._compiled.masters, self.runtime.fadeLevels
        )

    def _refresh_group_factor(self) -> None:
        """Recompute the group masters' factor from their levels: after a
        group master's ``SET_MASTER`` and after a swap, never per tick."""
        compiled = self._compiled
        self._group = group_factor(
            compiled.masters, self.runtime.groupLevels, compiled.slots.intensityLanes.size
        )

    @staticmethod
    def _playback_status(ident: PlaybackId, rt: PlaybackRuntime) -> PlaybackStatus:
        """What the snapshot shows of one playback."""
        cues = rt.playback.cueList
        after = rt.go_target()
        return PlaybackStatus(
            id=ident,
            number=rt.playback.number,
            name=rt.playback.name,
            state=rt.state,
            faderLevel=rt.faderLevel,
            flash=rt.flashPresent,
            swop=rt.swopButton,
            progress=None if rt.manual is None else rt.manual.progress,
            fader=rt.playback.fader,
            chase=cues.chasing,
            cueCount=len(cues.cues),
            cue=None if rt.cue < 0 else rt.current.number,
            cueName=None if rt.cue < 0 else rt.current.name or None,
            next=None if after is None else cues.cues[after].number,
            seq=rt.activationSeq,
            color=None if rt.cue < 0 else rt.current.color,
        )

    def _publish_snapshot(self, now: float) -> None:
        """Publish an :class:`EngineSnapshot` if what it shows changed (its
        ``time`` alone is no change)."""
        runtime = self.runtime
        playbacks = tuple(
            self._playback_status(ident, rt) for ident, rt in runtime.playbacks.runtimes.items()
        )
        speed = tuple(
            SpeedStatus(
                id=ident,
                name=rt.master.name,
                bpm=rt.bpm,
                multiplier=rt.multiplier,
                level=rt.level,
                beatTime=rt.T0,
                beat=rt.B0,
            )
            for ident, rt in runtime.speed.items()
        )
        own = {
            **runtime.masterLevels,
            **runtime.groupLevels,
            **runtime.sizeLevels,
            **runtime.fadeLevels,
            **{status.id: status.level for status in speed},
        }
        levels = tuple((ident, own[ident]) for ident in self._compiled.masters if ident in own)
        current = runtime.page.current
        page = (
            None
            if current is None
            else PageStatus(id=current.id, number=current.number, name=current.name)
        )
        previous = self.snapshot
        if (
            previous is not None
            and previous.masterLevels == levels
            and previous.speed == speed
            and previous.blackout == runtime.blackout
            and previous.outputEnabled == runtime.outputEnabled
            and previous.page == page
            and previous.fadeTime == runtime.playbacks.fade.time
            and previous.playbacks == playbacks
        ):
            return
        self.snapshot = EngineSnapshot(
            seq=1 if previous is None else previous.seq + 1,
            time=now,
            grandMaster=runtime.grandMaster,
            blackout=runtime.blackout,
            playbacks=playbacks,
            masterLevels=levels,
            speed=speed,
            page=page,
            fadeTime=runtime.playbacks.fade.time,
            outputEnabled=runtime.outputEnabled,
        )


def _levels(
    compiled: CompiledShow, kind: MasterKind, running: dict[MasterId, float] | None = None
) -> dict[MasterId, float]:
    """The level of every ``kind`` master of ``compiled`` (group, size or fade time), in
    show order: its ``running`` level if it had one before a live edit, else
    its initial level."""
    levels = {} if running is None else running
    return {
        master.id: levels.get(master.id, master.initialLevel)
        for master in compiled.masters.values()
        if master.kind == kind
    }
