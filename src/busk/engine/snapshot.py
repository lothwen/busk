"""The engine's UI snapshot: what a display shows about the running state (§4.2 stage 13).

The engine publishes an immutable :class:`EngineSnapshot` by reference
assignment, like a :class:`~busk.engine.loop.Frame`, but only when the state
it shows changed: a command was applied or a release finished. Other threads
(the CLI's status line now, the Phase 6 API later) read
:attr:`Engine.snapshot <busk.engine.loop.Engine.snapshot>` and never see a
half-built one.

An :class:`OutputSnapshot` (GAP-01) is another read: the output per
fixture element. It changes every tick, so the engine publishes only its raw
form, and only while asked (:mod:`busk.engine.readout`). So is an
:class:`EffectSnapshot` (GAP-09), the effects running at one tick
(:mod:`busk.engine.effect_status`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from busk.engine.playback_runtime import PlaybackState
from busk.model.attributes import AttributeFamily
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


type OutputSource = Literal["programmer", "playback", "effect", "none"]
"""What drives an attribute in the output: the programmer (its values and its
highlight), a playback (its cues, flash included), an effect (of a playback's
cue or of the programmer), or nothing (the default, a ``--values`` frame, or
park)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FixtureOutput:
    """One fixture element as the engine outputs it (GAP-01 of
    ``docs/dev/tui/engine-gaps.md``).

    The values are the logical ones, after the masters, blackout, park,
    limits and the highlight, and before the profile turns them into DMX.
    So they are what the fixture is asked to do, in the show's units:

    * ``intensity`` (0..1) is what the element emits: its own intensity, times
      its fixture's master dimmer when it has none of its own (a bar's cells
      on the first cell's dimmer). An element dimmed by nothing emits its
      colour as it is: 1.0;
    * ``color`` is linear RGB, 0..1, at full intensity: the colour slot's
      ``r, g, b`` plus an explicit ``w``, through the colour wheel's filter
      when the wheel slot has a colour in the profile. ``None``: the element
      has neither a colour nor a colour wheel. CTO, explicit amber and UV,
      and colour macros are not shown;
    * ``pan``, ``tilt`` and ``zoom`` are in degrees, before the fixture's
      orientation; ``None``: the element has no such attribute.

    ``source`` says what drives each family of attributes the element has
    (``"intensity"``, ``"position"``, ``"color"``, ``"beam"``, ``"focus"``,
    ``"shutter"``): of the attributes of a family, the programmer wins, then
    an effect, then a playback. ``playback`` is the number of the playback
    whose cue or effect drives the intensity; ``None`` when it is the
    programmer or nothing.
    """

    number: int  # the fixture's number (101)
    element: int  # counted from 1, as the console counts them (301.3); 1 for one element
    intensity: float
    color: tuple[float, float, float] | None
    pan: float | None
    tilt: float | None
    zoom: float | None
    source: Mapping[AttributeFamily, OutputSource]
    playback: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class OutputSnapshot:
    """The engine's output at one tick, per fixture element (GAP-01).

    ``seq`` and ``time`` are those of the tick, as in the
    :class:`~busk.runner.DmxFrame` it made. ``fixtures`` lists every
    element of every fixture, patched or not, by fixture number, then
    element.
    """

    seq: int
    time: float
    fixtures: tuple[FixtureOutput, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class EffectStatus:
    """One running effect instance (GAP-09 of ``docs/dev/tui/engine-gaps.md``).

    ``playback`` is the number of the playback whose cue runs it (on its
    main or its flash), ``None`` for the programmer's. ``id`` is the
    instance's id, unique among that playback's (or the programmer's)
    running effects. ``cue`` is the number of the cue whose ``effects`` hold
    the instance: the cue that defines it, also while it tracks into later
    cues; ``None`` for the programmer's. With them a display finds the
    instance, its template, targets and settings, in the show's cue list or
    in :attr:`ProgrammerStatus.effects <busk.session.status.ProgrammerStatus.effects>`.

    * ``presence`` (0..1) is how far in it is: rising while it enters (over
      its ``sizeFadeIn``, else the cue's in time or the programmer's fade
      time), 1 while it runs, falling while it leaves. A playback's fader and
      its release scale the effect's output as they scale the playback's
      values, not its presence;
    * ``size`` is the instance's size × its size master × its playback's
      ``size`` fader: the amplitude of its relative layers now (an absolute
      layer takes the two levels as a weight instead);
    * ``hz`` is its rate now, in cycles per second: a BPM effect's at the
      tempo now, after its master's step, a ``rate`` fader and the strobe cap;
    * ``phase`` (0..1) is where it is in its cycle, before the members'
      phase offsets;
    * ``wave`` is the next cycle of its first layer with a waveform: the wave
      (0..1) of that layer's first member at 20 equal steps, starting now
      (:data:`~busk.engine.effect_status.WAVE_SAMPLES`); ``()`` when no layer
      has a waveform (a colour cycle);
    * ``colors`` is the same for its first colour layer, as linear RGB 0..1;
      ``()`` when it has none.

    While a cue changes an instance's settings, the old ones fade out and
    the new ones in: the status shows the new ones, and ``presence`` the sum.
    """

    playback: int | None
    cue: str | None
    id: str
    presence: float
    size: float
    hz: float
    phase: float
    wave: tuple[float, ...]
    colors: tuple[tuple[float, float, float], ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class EffectSnapshot:
    """The effects running at one tick (GAP-09).

    ``seq`` and ``time`` are those of the tick, as in the
    :class:`~busk.runner.DmxFrame` it made. ``effects`` lists every running
    instance: the playbacks' in show order (one playback's leaving instances
    first, then its cue's in cue order), then the programmer's.
    """

    seq: int
    time: float
    effects: tuple[EffectStatus, ...]


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
