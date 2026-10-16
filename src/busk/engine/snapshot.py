"""The engine's UI snapshot: what a display shows about the running state (§4.2 stage 13).

The engine publishes an immutable :class:`EngineSnapshot` by reference
assignment, like a :class:`~busk.engine.loop.Frame`, but only when the state
it shows changed: a command was applied or a release finished. Other threads
(the CLI's status line now, the Phase 6 API later) read
:attr:`Engine.snapshot <busk.engine.loop.Engine.snapshot>` and never see a
half-built one.
"""

from __future__ import annotations

from dataclasses import dataclass

from busk.engine.playback_runtime import PlaybackState
from busk.model.common import MasterId, PlaybackId
from busk.model.playback import FaderFunction


@dataclass(frozen=True, slots=True, kw_only=True)
class PlaybackStatus:
    """One playback as a display shows it.

    The cue fields change only at events: a GO, BACK, GOTO, auto-GO, chase
    step, release or edit. ``fader``, ``chase`` and ``cueCount`` tell a
    display what the fader level means (a ``rate`` fader rests at 0.5),
    whether the cue is a chase step, which changes several times a second,
    and whether the list is a stack at all (phase-4-plan §5.11). While a
    ``crossfade`` fader drives a transition, ``cue`` is the cue it goes to
    and ``progress`` how far it is (phase-6-plan §5.6). ``seq`` (Phase 7)
    is the playback's newest activation number: a restore after an engine
    restart activates playbacks in this order, so the LTP stack comes back
    as it was.
    """

    id: PlaybackId
    number: int
    name: str
    state: PlaybackState
    faderLevel: float
    flash: bool  # the flash source is present (button held, or a temp fader up)
    swop: bool = False  # a swop button is held on it (Phase 6)
    progress: float | None = None  # a crossfade fader's manual transition, 0..1 (Phase 6)
    fader: FaderFunction = "master"
    chase: bool = False  # the list plays as a chase
    cueCount: int = 1  # the cues in the list
    cue: str | None = None  # the current cue's number (a chase: its current step); None when idle
    cueName: str | None = None  # its name; None when idle or unnamed
    next: str | None = None  # the cue GO goes to; None at the end without wrap (or random chase)
    seq: int = 0  # the newest activation number (Phase 7); 0: never activated


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeedStatus:
    """One speed master's tempo (phase-4-plan §5.11).

    The beat phase is left out on purpose: it changes every tick, and a
    snapshot is only published on change. Its *anchor* is in instead
    (phase-6-plan §5.7): ``beatTime`` and ``beat`` change only at taps and
    tempo changes, and a display (a tap LED, a remote) derives the beat count
    at any engine time ``t`` as ``beat + (t − beatTime) · bpm / 60``.
    """

    id: MasterId
    name: str
    bpm: float
    multiplier: float  # the step its level picks (×0.25 … ×4)
    level: float
    beatTime: float  # the engine time of the anchor (the runtime's T0), Phase 6
    beat: float  # the beat count at beatTime (B0), Phase 6

    def beats(self, t: float) -> float:
        """The beat count at engine time ``t``, at the published tempo."""
        return self.beat + (t - self.beatTime) * self.bpm / 60.0


@dataclass(frozen=True, slots=True, kw_only=True)
class PageStatus:
    """The current playback page (Phase 6): what page-relative controls drive."""

    id: str
    number: int
    name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class EngineSnapshot:
    """The published state: masters, blackout and every playback in show order.

    ``masterLevels`` holds each master's own level (grand, group, size,
    speed and fade time; Phase 5 added group and size, Phase 6 fade time),
    in show order, and ``speed`` each
    speed master's tempo; the session autosave persists both for crash
    recovery (§17), and ``page`` (Phase 6) the current page. ``fadeTime``
    (Phase 6) is the fade-time override that transitions starting now
    take, ``None`` while no fade-time master is up. ``time`` (Phase 6) is
    the engine time of the tick that published it. ``outputEnabled``
    (Phase 7) is ``False`` while ``OUTPUT`` has turned all DMX output off.
    """

    seq: int  # 1 for the first snapshot, +1 per published change
    time: float  # the publishing tick's engine time
    grandMaster: float  # the combined grand master level
    blackout: bool
    playbacks: tuple[PlaybackStatus, ...]
    masterLevels: tuple[tuple[MasterId, float], ...] = ()
    speed: tuple[SpeedStatus, ...] = ()
    page: PageStatus | None = None  # the current page; None when the show has none
    fadeTime: float | None = None  # seconds
    outputEnabled: bool = True


@dataclass(frozen=True, kw_only=True)
class Restore:
    """A queue item, like an :class:`~busk.engine.install.Install`: put the
    look of ``snapshot`` back after an engine restart (phase-7-plan decision
    5, §5.7). The console sends it after the restarted engine's first
    install; the engine applies it at stage 1 of the next tick."""

    snapshot: EngineSnapshot


@dataclass(frozen=True, kw_only=True)
class Sync:
    """A queue item that marks a point in the queue (Phase 7): the engine
    sets :attr:`Engine.synced <busk.engine.loop.Engine.synced>` to ``token``
    at the end of the tick that drains it, after that tick's snapshot is
    published. A console waits for it to know that everything it sent
    before has been applied and shows in the snapshot it holds
    (:meth:`RemoteBus.sync <busk.process.links.RemoteBus.sync>`)."""

    token: int
