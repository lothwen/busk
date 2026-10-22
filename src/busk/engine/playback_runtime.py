"""Playback runtimes: what each playback is doing right now (spec §5.18, §8).

A playback is up to **two contributors** (phase-2-plan decision 2):

* **main** holds the latched state: it is present from activation until its
  release has faded out. Its values are a
  :class:`~busk.engine.fades.ContributionSet`, the per-slot fades of the
  cue it plays (phase-4-plan §5.5), handed to the resolver as a
  :class:`~busk.engine.contributions.SequencedSource`: each slot carries
  its own sequence number;
* **flash** is present while the flash button is held, or while a ``temp``
  fader is above 0. It is a plain source with its own ``seq`` and its own
  band, ``priority + flash.priorityBoost``, playing the cue's static values
  at full weight. Releasing a flash removes only the flash source, so the
  stack below it is exactly as before: "the underlying state was never
  touched" (§8.1), even for flashes that bring LTP values.

Weights
-------
The slots fade in on their own (per lane, with the cue's timing and curve).
On top of that each playback has two scalar envelopes
(:class:`~busk.engine.fades.Envelope`):

* ``env`` is the **release**: 1 while active, from 1 to 0 over the release
  time when released;
* ``ltpEnv`` is the **LTP gate**. It is 1 while active, except in
  ``threshold`` mode when the fader activated the playback below
  ``ltpThreshold``: it then stays at 0 until the fader crosses the
  threshold, fades in with the cue's in timing and curve, and stays latched
  until release. It also fades out with the release.

Per tick the sources get (the per-lane weights of main multiply these):

======  ===========  =====================================  ============================
Source  htpWeight    intensityScale                         ltpWeight
======  ===========  =====================================  ============================
main    ``env``      ``faderLevel`` for a ``master`` fader,  ``ltpEnv``, × ``faderLevel``
                     else 1                                 in ``followFader`` mode
flash   1            max(``flash.level`` while held,         1 with ``includeLtp``, else 0
                     ``faderLevel`` of a ``temp`` fader)
======  ===========  =====================================  ============================

A suppressed playback (see *Swop* below) gets ``htpWeight`` 0 on both.

``ltpFaderMode`` applies to ``master`` faders only (decision 6), and
``autoStart`` and ``autoRelease`` to ``master`` and ``size`` faders. A
``rate`` fader rests at 0.5 and scales the rate of a chase (phase-4-plan
decision 12) and of the effects (phase-5-plan decision 14). A ``crossfade``
fader scales nothing: it drives the next transition by hand (below).

Crossfade faders (phase-6-plan §5.6)
------------------------------------
A ``crossfade`` fader plays a sequence the classic A/B way (decision 11).
It rests at either end, at 0 to begin with (:attr:`PlaybackRuntime.crossRest`).
Leaving the rest end starts the *pending* transition, with a fresh number as
GO takes: an active playback moves to its next cue (wrapping when the list
does), an idle or releasing one with ``autoStart`` activates at its first
cue (with exclusivity). A chase, the last cue of a list that does not wrap
and an idle playback without ``autoStart`` have none.

The transition (:class:`Manual`) fades with the cue's timing (or the
fade-time override), but on a virtual clock: ``started + progress × span``,
where ``span`` is its programmed length (1 s linear when it has none) and
``progress`` the furthest the fader has travelled from the rest end. So
delays and per-family times keep their proportions, and the fader can pause
a transition but never reverse it. The main bank's presences follow the
same clock; its effects keep moving in real time. Reaching the far end
completes the transition and makes that end the rest end. Cue triggers are
ignored: no auto-GO is ever armed on such a playback.

Anything else that moves the playback during a manual transition (``GO``,
``BACK``, ``GOTO``, a release, a re-activation, an edit that retargets it)
first *materialises* it: the slots and presences hold where the fader left
them, then the command proceeds from there, so nothing jumps. The fader
then drives nothing until it reaches an end (``crossRest`` is ``None``).

Beyond the plan, a fader that leaves its rest end with nothing pending
lets go of it too, and rests again at the first end it reaches: a
transition can only start from an end, so a later one never jumps to where
the fader happens to be. Running fades of an earlier transition are stopped
where they are when the fader starts one, and finish with it.

Swop (phase-6-plan §5.3)
------------------------
A swop button is a flash that also suppresses the other playbacks
(decision 9). :attr:`Playbacks.swopping` counts the swop presses held per
playback; a swopped playback's flash is up like a held flash button's. While
any swop is held, every live playback that is neither swopped nor
``protectFromSwop`` is *suppressed*: main and flash get ``htpWeight`` 0, and
so do their effects. Their intensity then has no presence in its band (an
override band no longer holds the swopped playback at 0), and their relative
intensity layers no weight. LTP weights are untouched, nothing fades, and
no exclusivity applies, so the last release gives back the exact frame.

Fade-time override (phase-6-plan §5.5)
--------------------------------------
While a fade-time master is up, :attr:`Playbacks.fade` holds its time
``T`` (:func:`~busk.engine.masters.fade_override`), shared with every
runtime. Every transition that *starts* then takes ``T`` instead of the
cue's timing: an activation, ``GO``, ``BACK``, ``GOTO`` and an auto-GO fade
every slot over ``T`` with no delay and the cue's in curve, and the main
bank's instances likewise (``sizeFadeIn`` still applies); a release that
names no time (a button, ``autoRelease``, exclusivity, ``GO`` past the
end) fades over ``T`` instead of ``releaseTime``
(:meth:`PlaybackRuntime.release_time`). An explicit ``RELEASE_PLAYBACK
{time}`` wins. Chase steps, flashes, swops and live edits keep their own
timing, and fades already running are left alone. An auto-GO reads the
override when it fires; due events fire before the tick's commands, so
that does not depend on the tick schedule.

Effects (phase-5-plan §5.7)
---------------------------
Main also runs the effects of its cue in a **main bank**
(:class:`~busk.engine.effects.EffectBank`): each running instance is one
more contributor of the playback's band, after its values, so an effect
wins a tie with its own playback's values (decision 7). Every retarget of
the slots retargets the bank with the same cue and numbering rule, with
the cue's in and out timing (a chase: the step cross-fade):

=====================  ==============================================
Event                  Main bank
=====================  ==============================================
activate               every instance takes the new ``seq``; a release
                       level is folded into the presences, as into the
                       slots
re-assert              every instance is renumbered; nothing fades
GO, BACK, GOTO         entering and changed instances take a fresh ``seq``
auto-GO, chase step    numbers are kept; a new instance takes the latest
=====================  ==============================================

A release changes nothing in the bank, which keeps moving under the
fading envelope (decision 11), and going idle clears it. The bank's
completion time joins the slots', so a transition (and a ``follow``
trigger) completes when both have.

Per tick the bank gets main's weights (decision 12) and the dynamics ``d``:
the ``size`` fader's level (1 for other faders) × the instance's size
master, read live from the shared :attr:`Playbacks.sizeLevels`.

The flash plays the cue's effects in a **flash bank** (decision 16) while
the flash is present and main is idle, so an effect is never applied twice:
while main runs (active or releasing) the flash adds only static values.
The flash bank runs in the flash band at the flash's number, with the flash
source's weights (LTP and relative non-intensity layers only with
``includeLtp``), at full dynamics: ``d`` is the size master's level alone.
Its instances enter at once (``sizeFadeIn`` still applies) on new clocks:

* it starts when the flash appears on an idle playback, and (beyond the
  plan) when main goes idle under a held flash, at the time the release
  ended, so frames do not depend on the tick schedule;
* it stops at once when the flash goes away, or when main activates. Main's
  bank then starts its own clocks: BPM effects land on the same beat grid.

A ``rate`` fader, taps and speed-master steps re-time both banks.

Main state machine (plan §5.5)
------------------------------
States are ``idle``, ``active`` and ``releasing``. Each event does:

* ``TRIGGER_PLAYBACK``: activate at the first cue; re-assert when active.
* ``TOGGLE_PLAYBACK``: release when active; activate at the first cue
  otherwise.
* ``GO``: activate at the first cue; when active, **move** to the next cue,
  and at the last one wrap, release or re-assert
  (:func:`~busk.engine.cue_engine.next_cue`).
* ``BACK``: when active, move to the previous cue (or wrap to the last);
  nothing otherwise. It cancels the auto-GO and schedules none.
* ``GOTO``: activate at the cue, or move there; at the current cue,
  re-assert.
* ``RELEASE_PLAYBACK``: release when active; nothing otherwise.
* fader leaves 0, with ``autoStart``: activate *by fader* unless active.
* fader reaches 0, with ``autoRelease``: release when active.
* fader ≥ ``ltpThreshold`` while active with LTP unlatched: latch LTP.
* an **auto-GO** is due: move to the next cue, keeping sequence numbers.
* ``releasing`` with both envelopes settled at 0: → ``idle``.

Auto-GOs and finished releases are *due events*: :meth:`Playbacks.advance`
fires them at their own times before each tick's commands and again after
them, so a command sees the state it would see on any tick schedule
(phase-4-plan decision 2).

* **activate** takes a fresh ``seq`` from the global counter (§8.1: this is
  what LTP's "latest" means) and aims the slots at the cue: they fade in
  with its timing and all take the new number. A releasing playback first
  folds its release level into its slots (``env`` and, when LTP latches,
  ``ltpEnv``), which then fade back in from where they are (decision 8);
  both envelopes return to 1, except ``ltpEnv`` when the fader activated
  it below the threshold in ``threshold`` mode. Activation then releases
  every other *active* playback with the same exclusivity key, each with its
  own release time (§8.3).
  An activation starts a *transition* (``started``, ``completes``: the
  latest end among the fades it started) and schedules the next cue's
  auto-GO from it (:func:`~busk.engine.cue_engine.schedule`).
* **re-assert** is a button activation of an active playback at its
  current cue: a fresh ``seq`` moves its LTP values back on top; nothing
  changes value, and the transition and its auto-GO carry on.
* **move** retargets the slots to another cue with that cue's timing.
  Unchanged slots keep their running fades (decision 5). A manual move
  (GO, BACK, GOTO) gives a fresh ``seq`` to the slots it changes; an
  auto-GO gives none (decision 4). The transition restarts and the next
  auto-GO is scheduled.
* **release** *freezes* the slots where they are and fades both envelopes
  from their current values to 0 over the command's ``time``, else the
  playback's ``releaseTime`` (decision 4; or the fade-time override, see
  below), so a release in the middle of a
  fade-in glides down from where it is (§7.8). It cancels the auto-GO. A
  release in 0 s goes straight to idle, removing the source in the same
  tick.

The flash source plays the cue main is at (the first cue while idle).

Chases (phase-4-plan §5.7)
--------------------------
A list in ``chase`` mode plays as a chase: activation starts a
:class:`~busk.engine.chase.ChaseRuntime` (a clock and a cue order) at the
first cue of its direction, and each step boundary is a due event, fired at
its own time like an auto-GO. Every move of a chase (activation, a
boundary, GO, BACK, GOTO) fades every slot over ``crossfade`` × the step
length with the destination cue's curve; cue timing and triggers are
ignored, and chases always loop. GO and BACK step once along the cue order
at once, and GOTO jumps, all without moving the boundary grid (decision
10). A releasing chase is not frozen: it keeps stepping while it fades out.
Taps, the speed master's step and the ``rate`` fader re-time the clock
(:meth:`Playbacks.tap`, :meth:`Playbacks.set_speed_level`,
:meth:`Playbacks.set_fader`), and the effect clocks of the main banks
with it (phase-5-plan §5.4).

Only latching activations and re-asserts apply exclusivity (decision 5):
trigger, toggle, GO, GOTO and ``autoStart``. Moves between cues do not: the
playback is already active. A flash never does, or a momentary flash would
permanently release the colour it covered.

Live swap (phase-4-plan decision 14)
------------------------------------
When a recompiled show is installed, :meth:`Playbacks.rebind` re-points
every runtime at its new :class:`~busk.compiler.playbacks.CompiledPlayback`
(found by id). The slots follow the new slot table (their running fades
carry on, on their new lanes). A running playback is re-pointed at its cue
by :class:`~busk.model.common.CueId`; if that cue was deleted it moves to
the cue that now follows its number, or to the last cue. It then fades to
that cue's new state with the cue's timing (a chase: the step crossfade),
without taking a sequence number, so an edit never reorders the stack:
slots the edit did not change keep their running fades. A releasing
playback keeps its frozen slots (decision 8): a release fades out what was
on stage; a releasing chase, which is not frozen, takes the edit like an
active one. State, fader level, sequence numbers and envelopes continue
unchanged.

The auto-GO is re-derived from the edited list, from the kept ``started``
and ``completes``, unless BACK or a release cancelled it: a next cue edited
from ``go`` to ``wait`` arms one, and one the edit made overdue fires at
the install. A chase's clock carries on at its edited rate when its rate
kind and master are the same; a list that became a chase starts a clock
as on activation, and one that stopped being a chase drops it. A runtime
whose playback is gone is dropped; one whose cue list is now empty goes
idle at once.

Effects follow a live swap too (phase-5-plan §5.10). Both banks move their
running versions onto a new slot table (lanes that are gone are dropped).
Whenever the slots are retargeted to the edited cue, the main bank is
retargeted with them, keeping numbers, with the cue's in and out timing (a
chase: the step cross-fade): an edited size or template cross-fades on the
instance's own clock, an edited rate re-rates it without a jump, an
instance deleted from the cue fades out with the out timing, and an
unchanged one (:meth:`~busk.compiler.effects.CompiledEffect.same`) runs on
untouched. A releasing playback whose slots are frozen keeps its effects as
they were. A running flash bank moves to the edited cue at once. Every
clock then re-rates, so an edited speed master's steps take effect and
BPM effects stay on its beat grid.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from itertools import chain
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from busk.compiler.cues import CompiledCue
from busk.compiler.playbacks import CompiledCueList, CompiledPlayback
from busk.compiler.slots import SlotTable
from busk.engine.chase import ChaseRuntime, chase_seed
from busk.engine.contributions import Contributor, Origin, Relative, SequencedSource, Source, wire
from busk.engine.cue_engine import CueTiming, next_cue, previous_cue, schedule
from busk.engine.curves import curve_of
from busk.engine.effects import EffectBank, EffectScalars, EffectTiming, StrobeCap
from busk.engine.fades import (
    ContributionSet,
    Envelope,
    SeqRule,
    Timing,
    TimingRule,
    Uniform,
)
from busk.engine.masters import FadeOverride, SpeedMasterRuntime
from busk.model.common import MasterId, PlaybackId
from busk.model.cue import cue_number_key
from busk.model.playback import ButtonFunction

type PlaybackState = Literal["idle", "active", "releasing"]
type ActivatedBy = Literal["button", "fader"]


def _empty_source(sourceId: str, priority: int, origin: Origin) -> Source:
    """A source without lanes, absent until filled."""
    lanes, values = np.zeros(0, dtype=np.intp), np.zeros(0, dtype=np.float64)
    return Source(
        sourceId=sourceId,
        priority=priority,
        seq=0,
        htpPos=lanes,
        htpValues=values,
        ltpLanes=lanes,
        ltpValues=values,
        snapLanes=lanes,
        snapValues=values,
        snapThresholds=values,
        origin=origin,
    )


def _repoint(cues: CompiledCueList, was: CompiledCue) -> int:
    """The index of cue ``was`` in the edited list ``cues`` (not empty): found
    by id; if it was deleted, the cue that now follows its number, or the
    last cue (decision 14). Cue numbers are strictly ascending."""
    index = cues.byId.get(was.id)
    if index is not None:
        return index
    key = cue_number_key(was.number)
    later = (i for number, i in cues.byNumber.items() if key is not None and number > key)
    return min(later, default=len(cues.cues) - 1)


@dataclass(slots=True)
class Manual:
    """A transition driven by a ``crossfade`` fader (phase-6-plan §5.6): its
    fades started at ``started`` and run on the virtual clock :attr:`time`."""

    started: float  # the real time it started: its fades start here
    end: float  # when every fade it started has ended, on its clock
    rest: float  # the end the fader left: 0.0 or 1.0
    progress: float = 0.0  # the furthest |level − rest| so far; never decreases

    @property
    def time(self) -> float:
        """The virtual time its fades are at: ``started + progress × span``,
        exactly :attr:`end` once complete. It never decreases."""
        if self.progress >= 1.0:
            return self.end
        return self.started + self.progress * (self.end - self.started)


class PlaybackRuntime:
    """The runtime state of one playback and its two contributors.

    Transitions that need the global sequence counter or other playbacks
    (exclusivity) are driven by :class:`Playbacks`; this class keeps the
    per-playback rules.
    """

    def __init__(
        self,
        playback: CompiledPlayback,
        slots: SlotTable,
        speed: Mapping[MasterId, SpeedMasterRuntime] | None = None,
        sizeLevels: Mapping[MasterId, float] | None = None,
        fade: FadeOverride | None = None,
        cap: StrobeCap | None = None,
    ) -> None:
        """``speed`` is the engine's speed masters, ``sizeLevels`` the size
        masters' levels, ``fade`` the fade-time override and ``cap`` the
        strobe cap (all shared, kept current by :class:`Playbacks`): a BPM
        chase or effect follows a speed master, an effect's dynamics read
        its size master, a transition that starts while a fade-time master
        is up takes its time (Phase 6), and an effect with an intensity
        layer runs under the cap (Phase 7)."""
        self.playback = playback
        self.speed: Mapping[MasterId, SpeedMasterRuntime] = {} if speed is None else speed
        self.sizeLevels: Mapping[MasterId, float] = {} if sizeLevels is None else sizeLevels
        self.fade = FadeOverride() if fade is None else fade
        self.cap = StrobeCap() if cap is None else cap
        self.state: PlaybackState = "idle"
        # Faders start at 0 (phase-2-plan decision 6), a rate fader at ×1 (decision 12).
        self.faderLevel = 0.5 if playback.fader == "rate" else 0.0
        self.activationSeq = 0
        self.env = Envelope()
        self.ltpEnv = Envelope()
        self.ltpLatched = False
        self.flashButton = False
        self.swopButton = False  # a swop button holds the flash up (Phase 6)
        self.flashSeq = 0
        self.cue = -1  # the index of the cue main plays; −1 when idle
        self.started = 0.0  # when the transition into the current cue started …
        self.completes = 0.0  # … and when the last fade it started ends
        self.auto: float | None = None  # when the next auto-GO fires, if one is due
        self.armed = False  # whether the cue's auto-GO stands (BACK and release cancel it)
        self.chase: ChaseRuntime | None = None  # while a chase list plays (§5.7)
        self.manual: Manual | None = None  # while a crossfade fader drives a transition
        self.crossRest: float | None = 0.0
        """The end a ``crossfade`` fader rests at (0.0 or 1.0), or ``None``
        while it is not resting at one (Phase 6)."""
        self._lap = (-1.0, 0)  # (tick time, auto-GOs fired at it): one lap per tick
        self.contributions = ContributionSet(slots.laneSlot)
        self.laneFamily = slots.laneFamily
        own, effects = Origin("playback", playback.id), Origin("effect", playback.id)
        self.main = SequencedSource(_empty_source(playback.id, playback.priority, own))
        self._wired = -1  # the contributions version main's arrays point at
        self.flash = Source.of_cue(
            f"{playback.id}/flash",
            playback.priority + playback.flashPriorityBoost,
            playback.cueList.first,
            own,
        )
        self.bank = EffectBank(
            playback.id, playback.priority, self.speed, self.rateLevel, self.cap, effects
        )
        """Main's effects: the instances of the cue main plays (§5.7)."""
        self.scalars = EffectScalars(sizeLevels=self.sizeLevels)  # refilled per tick
        self.flashBank = EffectBank(
            self.flash.sourceId, self.flash.priority, self.speed, self.rateLevel, self.cap, effects
        )
        """The flash's effects, while the flash is present and main is idle (decision 16)."""
        self.flashScalars = EffectScalars(sizeLevels=self.sizeLevels)  # refilled per tick
        self._modes()

    def _modes(self) -> None:
        master = self.playback.fader == "master"
        self.masterFader = master
        self.followFader = master and self.playback.ltpFaderMode == "followFader"
        self.thresholdMode = master and self.playback.ltpFaderMode == "threshold"

    @property
    def current(self) -> CompiledCue:
        """The cue main is at; the first cue while idle (what a flash plays)."""
        cues = self.playback.cueList.cues
        return cues[self.cue] if 0 <= self.cue < len(cues) else self.playback.cueList.first

    @property
    def rateLevel(self) -> float | None:
        """The ``rate`` fader's level, or ``None`` when the fader is not one."""
        return self.faderLevel if self.playback.fader == "rate" else None

    def first_cue(self) -> int:
        """The cue an activation starts at: the last for a ``reverse`` chase,
        else the first."""
        cues = self.playback.cueList
        if cues.chasing and cues.chase is not None and cues.chase.direction == "reverse":
            return len(cues.cues) - 1
        return 0

    def go_target(self) -> int | None:
        """The cue index GO moves to (the snapshot's ``next``).

        While not active, GO starts at :meth:`first_cue`. An active sequence
        goes to its next cue; at the end of a list that does not wrap GO
        releases or re-asserts, so there is none (``None``). A chase goes to
        its order's next step, ``None`` for a random chase. A list an edit
        emptied has none either.
        """
        if not self.playback.cueList.cues:
            return None
        if self.state != "active":
            return self.first_cue()
        if self.chase is not None:
            return self.chase.order.peek(self.cue)
        after = next_cue(self.playback.cueList, self.cue)
        return None if isinstance(after, str) else after

    def _timing(self, target: CompiledCue, override: bool = True) -> TimingRule:
        """How the slots fade into ``target``: the cue's own timing, or for a
        chase one fade for every slot: ``crossfade`` × the step length, with
        the cue's curve (decision 10). While a fade-time master is up (and
        ``override``), a cue's timing gives way to one fade for every slot
        over the override's time, with no delay and the cue's in curve
        (phase-6-plan decision 12); a chase keeps its step cross-fade."""
        curve = curve_of(target.inTiming.curve)
        if self.chase is not None:
            return Uniform(Timing(self.chase.crossfade(), 0.0, curve))
        if override and self.fade.time is not None:
            return Uniform(Timing(self.fade.time, 0.0, curve))
        return CueTiming(target, self.laneFamily)

    def _effect_timing(self, target: CompiledCue, override: bool = True) -> EffectTiming:
        """How the main bank's instances fade into ``target``: the cue's in and
        out timing, or for a chase the step cross-fade, or the fade-time
        override, as the slots do (``sizeFadeIn`` still applies)."""
        curve = curve_of(target.inTiming.curve)
        if self.chase is not None:
            return EffectTiming.uniform(Timing(self.chase.crossfade(), 0.0, curve))
        if override and self.fade.time is not None:
            return EffectTiming.uniform(Timing(self.fade.time, 0.0, curve))
        return EffectTiming.of_cue(target)

    def _timings(self, target: CompiledCue, manual: bool) -> tuple[TimingRule, EffectTiming, float]:
        """The slots' and the main bank's timing into ``target``
        (:meth:`_timing`, :meth:`_effect_timing`), and for a ``manual``
        transition its span: the programmed length, the longest delay plus
        fade it may use. A manual transition with no length fades linearly
        over 1 s (decision 11)."""
        timing, effects = self._timing(target), self._effect_timing(target)
        if not manual:
            return timing, effects, 0.0
        lengths = chain(
            timing.timings, (effects.change, effects.leave), map(effects.enter, target.effects)
        )
        span = max(t.delay + t.duration for t in lengths)
        if span > 0.0:
            return timing, effects, span
        linear = Timing(1.0)
        return Uniform(linear), EffectTiming.uniform(linear), 1.0

    def release_time(self) -> float:
        """How long a release takes that names no time: the fade-time
        override while a fade-time master is up, else ``releaseTime``."""
        time = self.fade.time
        return self.playback.releaseTime if time is None else time

    def _settle(self, at: float) -> None:
        """Stop the slots' fades and the main bank's presences where they are
        at ``at``: they hold those values from now on."""
        self.contributions.freeze(at)
        self.bank.hold(at)

    def _materialise(self) -> None:
        """Let go of a manual transition where the fader left it, before a
        button, a release or an edit moves the playback (decision 11): the
        slots and presences hold their values at its virtual time, and the
        fader drives again once it has reached an end."""
        if self.manual is not None:
            self._settle(self.manual.time)
            self.manual = None
            self.crossRest = None

    def complete_manual(self) -> None:
        """The fader reached the far end: every fade of the manual transition
        has ended on its clock, and that end is where the fader rests now."""
        manual = self.manual
        assert manual is not None
        self._settle(manual.end)
        self.manual = None
        self.crossRest = 1.0 - manual.rest

    def _start_chase(self, now: float, seq: int) -> None:
        """Start a chase clock and cue order at ``now`` if the list is a
        chase, as on activation; drop any chase otherwise."""
        cues = self.playback.cueList
        if not cues.chasing or cues.chase is None:
            self.chase = None
            return
        settings = cues.chase
        master = None if settings.masterId is None else self.speed[settings.masterId]
        self.chase = ChaseRuntime(
            settings,
            master,
            self.rateLevel,
            len(cues.cues),
            chase_seed(self.playback.id, seq),
            now,
        )

    def rebind(
        self,
        playback: CompiledPlayback,
        now: float,
        slots: SlotTable,
        maps: tuple[NDArray[np.intp], NDArray[np.intp]] | None,
    ) -> None:
        """Follow a recompiled playback (see the module docs). ``maps`` are the
        lane and intensity-position maps of a new slot table, or ``None``
        when the slot table is the same."""
        was, edited = self.current, playback.cueList is not self.playback.cueList
        if edited or maps is not None or playback.fader != "crossfade":
            self._materialise()  # the edit retargets, or the fader drives no more
        if playback.fader == "crossfade" and self.playback.fader != "crossfade":
            level = self.faderLevel  # a fader that became a crossfader rests where it is
            self.crossRest = level if level in (0.0, 1.0) else None
        self.playback = playback
        if maps is not None:
            self.contributions.remap(slots.laneSlot, *maps)
            self.bank.remap(*maps)
            self.flashBank.remap(*maps)
        self.laneFamily = slots.laneFamily
        self.main.whole.priority = playback.priority
        self.bank.priority = playback.priority
        if self.state != "idle" and playback.cueList.cues:
            self.cue = _repoint(playback.cueList, was)
            if self.state == "active" or self.chase is not None:
                self._rebind_chase(now)
            if self.state == "releasing" and self.chase is None:
                self.contributions.freeze(now)  # a release holds its slots (decision 8)
            elif edited or maps is not None:  # fade to the edited cue, keeping every
                # slot's number (decision 14). A list the edit left alone (the
                # memoised compile reuses it) on the same slots has the same
                # states: its fades run on untouched, and the engine thread is
                # spared a retarget per running playback on every edit.
                target = self.current
                rule = SeqRule.keep(self.activationSeq)
                timing = self._timing(target, override=False)  # edits keep their own timing
                self.contributions.retarget(now, target, timing, rule)
                self.bank.retarget(now, target.effects, self._effect_timing(target, False), rule)
            if self.armed:
                self._schedule()
                if self.auto is not None:
                    self.auto = max(self.auto, now)  # made overdue by the edit: fire now
        self.flash.priority = playback.priority + playback.flashPriorityBoost
        self.flashBank.priority = self.flash.priority
        self._point_flash()
        self._modes()
        self._rebind_flash_effects(now)
        # An edited speed master's steps, or a fader that is a rate fader no
        # longer (or now), re-rate the clocks the retargets left alone.
        self.bank.rerate(now, self.rateLevel)
        self.flashBank.rerate(now, self.rateLevel)

    def _rebind_flash_effects(self, now: float) -> None:
        """Keep the flash bank on the edited cue through a live swap: while the
        flash is present on an idle playback it moves to :attr:`current`'s
        effects at once, as a flash enters, keeping its numbers; otherwise
        (an edit can turn a ``temp`` fader into another kind) it stops."""
        if self.flashPresent and self.state == "idle":
            self.flashBank.retarget(
                now,
                self.current.effects,
                EffectTiming.uniform(Timing()),
                SeqRule.keep(self.flashSeq),
            )
        else:
            self.flashBank.clear()

    def _rebind_chase(self, now: float) -> None:
        """Keep a running chase going through a live edit. Its clock carries
        on when its rate kind and master are the same, at its edited rate
        and cue count; otherwise, or when the list just became a chase, a
        new clock starts now. A list that is no longer a chase drops it. A
        step that the new rate makes due is left to the next boundary."""
        cues = self.playback.cueList
        chase, settings = self.chase, cues.chase
        if chase is None or not cues.chasing or settings is None:
            self._start_chase(now, self.activationSeq)
            return
        master = None if settings.masterId is None else self.speed[settings.masterId]
        if master is not chase.master:
            self._start_chase(now, self.activationSeq)
            return
        chase.settings = settings
        chase.order.direction = settings.direction
        chase.order.count = len(cues.cues)
        chase.rerate(now, self.rateLevel)  # a step it owes now is left to the next boundary

    def drop(self) -> None:
        """Stop at once, without a release fade: nothing is left to play."""
        self._materialise()
        self.state = "idle"
        self.cue = -1
        self.cancel_auto()
        self.chase = None
        self.env = Envelope()
        self.ltpEnv = Envelope()
        self.ltpLatched = False
        self.flashButton = False
        self.contributions.clear()
        self.bank.clear()
        self.flashBank.clear()
        self._point_flash()

    @property
    def flashPresent(self) -> bool:
        """Whether the flash source is present: a flash or swop button held, or
        a ``temp`` fader up."""
        return (
            self.flashButton
            or self.swopButton
            or (self.playback.fader == "temp" and self.faderLevel > 0.0)
        )

    @property
    def live(self) -> bool:
        """Whether either contributor may contribute: the engine updates only
        live runtimes."""
        return self.state != "idle" or self.flashPresent

    def activate(
        self, now: float, seq: int, by: ActivatedBy, cue: int, manual: float | None = None
    ) -> None:
        """Activate at cue index ``cue``, or re-assert an active playback
        (``cue`` is then its current one), with sequence number ``seq`` on
        every slot and effect instance. An activation starts a transition and
        schedules the auto-GO after it; a re-assert lets both carry on. A
        running flash bank stops: main's bank plays the effects now.
        Exclusivity is the caller's job.

        With ``manual`` (the rest end a crossfade fader left) the fader drives
        the activation (:meth:`_drive`); otherwise a manual transition that
        runs is materialised first."""
        self._materialise()
        reassert = self.state == "active" and cue == self.cue
        self.flashBank.clear()  # main's bank takes over (decision 16)
        latch = not (
            by == "fader" and self.thresholdMode and self.faderLevel < self.playback.ltpThreshold
        )
        scale = self.env.value(now)  # the release level (1 while active)
        ltp_scale = self.ltpEnv.value(now) if latch else 1.0
        if not reassert:
            self._start_chase(now, seq)
        self.cue = cue
        target = self.current
        if manual is not None:
            self._settle(now)  # the fader takes everything on from where it is
        timing, effect_timing, span = self._timings(target, manual is not None)
        completes = self.contributions.retarget(
            now,
            target,
            timing,
            SeqRule.all(seq),
            scale=scale,
            ltpScale=ltp_scale,
        )
        effects = self.bank.retarget(
            now, target.effects, effect_timing, SeqRule.all(seq), scale=scale
        )
        completes = max(completes, effects)
        if manual is not None:
            self._drive(now, manual, span, completes)
        self.env.retarget(now, 1.0, 0.0)
        if latch:
            self.ltpEnv.retarget(now, 1.0, 0.0)
            self.ltpLatched = True
        self.activationSeq = seq
        self.state = "active"
        if not reassert:
            self.started, self.completes = now, completes
            self._schedule()
            self._point_flash()

    def move(self, now: float, cue: int, seqs: SeqRule, manual: float | None = None) -> None:
        """Move an active playback to cue index ``cue`` at ``now``.

        Changed slots fade from where they are with the destination's timing;
        unchanged ones keep their running fades (decisions 5–6). The main
        bank moves to the cue's effects the same way: entering and changed
        instances fade in with its in timing, leaving ones out with its out
        timing (a chase: the step cross-fade), unchanged ones carry on.
        ``seqs`` numbers slots and instances: ``fresh`` for a manual move,
        ``keep`` for an auto-GO or a chase step (decision 4). The transition
        completes when both have; the auto-GO after the new cue is
        scheduled from it, and BACK cancels it again.

        With ``manual`` (the rest end a crossfade fader left) the fader drives
        the move (:meth:`_drive`); otherwise a manual transition that runs is
        materialised first.
        """
        self._materialise()
        if manual is not None:
            self._settle(now)  # the fader takes everything on from where it is
        self.cue = cue
        target = self.current
        timing, effect_timing, span = self._timings(target, manual is not None)
        slots = self.contributions.retarget(now, target, timing, seqs)
        effects = self.bank.retarget(now, target.effects, effect_timing, seqs)
        self.completes = max(slots, effects)
        self.started = now
        self.activationSeq = seqs.seq  # a fresh number is the newest; `keep` passes the current one
        self._schedule()
        self._point_flash()
        if manual is not None:
            self._drive(now, manual, span, self.completes)

    def _drive(self, now: float, rest: float, span: float, completes: float) -> None:
        """Hand the transition that just started at ``now`` to the crossfade
        fader that left ``rest``. Its clock runs over ``span``, or to the
        completion the fades reported if that is later (the two are summed
        in another order, so they may differ in the last bit)."""
        self.manual = Manual(started=now, end=max(now + span, completes), rest=rest)

    def _schedule(self) -> None:
        """Schedule the auto-GO after the current cue's transition; a chase
        has none (its triggers are ignored, decision 10), nor a playback
        with a ``crossfade`` fader: the fader is its GO (Phase 6)."""
        self.armed = True
        if self.chase is None and self.playback.fader != "crossfade":
            self.auto = schedule(self.playback.cueList, self.cue, self.started, self.completes)
        else:
            self.auto = None

    def cancel_auto(self) -> None:
        """Cancel the auto-GO, and keep live edits from re-deriving it until
        the next move schedules one (BACK, a release)."""
        self.auto = None
        self.armed = False

    def fire(self, until: float) -> bool:
        """Fire every auto-GO due by ``until``, each at its own time, so a
        chain of auto-GOs lands where it would on any tick schedule
        (decision 1). At most one lap of the list fires per tick (decision
        9), counted across the tick's calls (``until`` is the tick's time);
        the rest stays due. Returns whether any fired.

        A chase fires its step boundaries instead (:meth:`_fire_chase`).
        """
        if self.chase is not None:
            return self._fire_chase(until)
        cues = self.playback.cueList
        at, fired = self._lap
        if at != until:
            fired = 0
        moved = False
        while self.auto is not None and self.auto <= until and fired < len(cues.cues):
            after = next_cue(cues, self.cue)
            assert isinstance(after, int)  # schedule() only plans moves to another cue
            self.move(self.auto, after, SeqRule.keep(self.activationSeq))
            fired += 1
            moved = True
        self._lap = (until, fired)
        return moved

    def _fire_chase(self, until: float) -> bool:
        """Step at every boundary due by ``until``, each at its own time, with
        one fade for every slot and no fresh numbers (decisions 4 and 10).

        At most one lap of steps is retargeted per call. Earlier ones only
        advance the cue order: each step's fade ends by the next boundary,
        so the last two steps alone decide the slots, and the frames are
        the same as if every step had been processed. Effects are the
        exception: an instance's clock starts at the step it entered, which
        may be one of the skipped steps. Only more than a lap of steps in
        one tick (an engine stall) can skip one. Returns whether any step
        fired.
        """
        chase = self.chase
        assert chase is not None
        clock, order = chase.clock, chase.order
        last = clock.last_due(until)
        if last <= clock.done:
            return False
        first = clock.done + 1
        lap = max(len(self.playback.cueList.cues), 2)
        for _ in range(first, last - lap + 1):  # only when the steps outrun the ticks
            self.cue = order.step(self.cue)
        for k in range(max(first, last - lap + 1), last + 1):
            clock.done = k
            at = clock.boundary_time(k)
            self.move(at, order.step(self.cue), SeqRule.keep(self.activationSeq))
        return True

    def step_now(self, now: float) -> None:
        """A step a chase owes at ``now``, after a re-alignment moved it past
        a boundary: an automatic advance, so no fresh numbers."""
        assert self.chase is not None
        self.move(now, self.chase.order.step(self.cue), SeqRule.keep(self.activationSeq))

    def latch_ltp(self, now: float) -> None:
        """Fade the LTP gate in with the cue's in timing, and keep it until release."""
        timing = self.current.inTiming
        self.ltpEnv.retarget(now, 1.0, timing.fade, timing.delay, curve_of(timing.curve))
        self.ltpLatched = True

    def release(self, now: float, time: float) -> None:
        """Freeze the slots and fade both envelopes from their current values
        to 0 over ``time`` seconds. A chase is not frozen: it keeps stepping
        while it fades out. A manual transition is materialised first."""
        self._materialise()
        if self.chase is None:
            self.contributions.freeze(now)
        self.cancel_auto()
        self.env.retarget(now, 0.0, time)
        self.ltpEnv.retarget(now, 0.0, time)
        self.ltpLatched = False
        if time <= 0.0:
            self._idle(now)
        else:
            self.state = "releasing"

    def _idle(self, at: float) -> None:
        """Go idle at time ``at``: main stops, and a held flash's bank takes
        over its effects from ``at``."""
        self.state = "idle"
        self.cue = -1
        self.chase = None
        self.contributions.clear()
        self.bank.clear()
        self._point_flash()
        self.flash_effects(at)

    def flash_effects(self, now: float) -> None:
        """Start or stop the flash bank at ``now`` so that it runs exactly
        while the flash is present and main is idle (decision 16). A
        starting bank plays the current cue's effects at the flash's number,
        entering at once; a running one is left alone."""
        if not (self.flashPresent and self.state == "idle"):
            self.flashBank.clear()
        elif not self.flashBank.active:
            self.flashBank.retarget(
                now,
                self.current.effects,
                EffectTiming.uniform(Timing()),
                SeqRule.all(self.flashSeq),
            )

    def _point_flash(self) -> None:
        """Aim the flash source at :attr:`current`: the cue main is at, or
        the first cue while idle."""
        cue, flash = self.current, self.flash
        flash.htpPos, flash.htpValues = cue.htpPos, cue.htpValues
        flash.ltpLanes, flash.ltpValues = cue.ltpLanes, cue.ltpValues
        flash.snapLanes, flash.snapValues = cue.snapLanes, cue.snapValues
        flash.snapThresholds = cue.snapThresholds

    def finish_release(self, now: float) -> bool:
        """Go idle if a release has faded out by ``now``. Returns whether it did.

        Like an auto-GO, this is an event due at its own time: a command at
        ``now`` must find the playback idle whether or not a tick ran in
        between (decision 2).
        """
        if self.state == "releasing" and self.env.settled(now) and self.ltpEnv.settled(now):
            self._idle(min(now, max(self.env.end, self.ltpEnv.end)))
            return True
        return False

    def update(self, now: float, suppressed: bool = False) -> bool:
        """Advance to ``now`` and fill both contributors, and both banks'
        effects, for this tick. A ``suppressed`` playback (another one swops)
        gets no HTP weight. During a manual transition the slots and main's
        presences are taken at its virtual time.

        Returns whether the state changed (a finished release went idle).
        """
        changed = self.finish_release(now)

        main = self.main.whole
        if self.state == "idle":
            main.htpWeight = main.ltpWeight = 0.0
        else:
            fade_at = now if self.manual is None else self.manual.time
            contributions = self.contributions
            contributions.evaluate(fade_at)
            if contributions.version != self._wired:
                self._wire()
            main.htpWeight = 0.0 if suppressed else self.env.value(now)
            main.intensityScale = self.faderLevel if self.masterFader else 1.0
            ltp = self.ltpEnv.value(now)
            main.ltpWeight = ltp * self.faderLevel if self.followFader else ltp
            if self.bank.active:  # the effects take main's weights (decision 12)
                scalars = self.scalars
                scalars.htpWeight = main.htpWeight
                scalars.intensityScale = main.intensityScale
                scalars.ltpWeight = main.ltpWeight
                scalars.size = self.faderLevel if self.playback.fader == "size" else 1.0
                self.bank.update(now, scalars, fade_at)

        flash = self.flash
        if self.flashPresent:
            playback = self.playback
            flash.seq = self.flashSeq
            flash.htpWeight = 0.0 if suppressed else 1.0
            flash.intensityScale = max(
                playback.flashLevel if self.flashButton or self.swopButton else 0.0,
                self.faderLevel if playback.fader == "temp" else 0.0,
            )
            flash.ltpWeight = 1.0 if playback.flashIncludeLtp else 0.0
            if self.flashBank.active:  # the flash's weights, full dynamics (decision 16)
                scalars = self.flashScalars
                scalars.htpWeight = flash.htpWeight
                scalars.intensityScale = flash.intensityScale
                scalars.ltpWeight = flash.ltpWeight
                self.flashBank.update(now, scalars)
        else:
            flash.htpWeight = flash.ltpWeight = 0.0
        return changed

    def _wire(self) -> None:
        """Point main at the contributions' partitions (:func:`wire`)."""
        wire(self.main, self.contributions, self.activationSeq)
        self._wired = self.contributions.version


class Playbacks:
    """Every playback runtime, the global activation sequence (§5.18
    ``seqCounter``) and exclusivity (§8.3).

    The engine thread is the only caller. Each method applies one
    performance command at time ``now``; ids have been validated by the
    command bus.
    """

    def __init__(self, playbacks: Mapping[PlaybackId, CompiledPlayback], slots: SlotTable) -> None:
        self.speed: dict[MasterId, SpeedMasterRuntime] = {}
        """The speed masters, shared with every runtime (:meth:`set_speed`)."""
        self.sizeLevels: dict[MasterId, float] = {}
        """The size masters' levels, shared with every runtime's effects
        (:meth:`set_size_levels`; ``SET_MASTER`` writes them in place)."""
        self.fade = FadeOverride()
        """The fade-time override, shared with every runtime (Phase 6; the
        engine sets it)."""
        self.cap = StrobeCap()
        """The strobe cap, shared with every runtime's effects (Phase 7; the
        engine sets it, before :meth:`rebind` on a live swap)."""
        self.runtimes = {
            ident: PlaybackRuntime(
                playback, slots, self.speed, self.sizeLevels, self.fade, self.cap
            )
            for ident, playback in playbacks.items()
        }
        self.seqCounter = 0
        self.swopping: dict[PlaybackId, int] = {}
        """The swop presses held, per swopped playback (Phase 6)."""
        # Live runtimes (not idle, or flashing), in the order they went live.
        self.live: dict[PlaybackId, PlaybackRuntime] = {}
        self._exclusive: dict[str, list[PlaybackRuntime]] = {}
        self._index_exclusivity()

    def rebind(
        self,
        playbacks: Mapping[PlaybackId, CompiledPlayback],
        now: float,
        slots: SlotTable,
        maps: tuple[NDArray[np.intp], NDArray[np.intp]] | None = None,
    ) -> None:
        """Follow a recompiled show (Phase 3 live swap; see the module docs).

        Runtimes are matched by playback id: kept ones are re-pointed, new
        playbacks get idle runtimes, and runtimes of deleted playbacks are
        dropped, with their swops. A playback whose cue list is now empty
        goes idle at once.
        ``maps`` carry the slots of running fades to a new slot table.
        """
        runtimes: dict[PlaybackId, PlaybackRuntime] = {}
        for ident, playback in playbacks.items():
            runtime = self.runtimes.get(ident)
            if runtime is None:
                runtime = PlaybackRuntime(
                    playback, slots, self.speed, self.sizeLevels, self.fade, self.cap
                )
            else:
                runtime.rebind(playback, now, slots, maps)
                if not playback.cueList.cues:
                    runtime.drop()
            runtimes[ident] = runtime
        self.runtimes = runtimes
        self.live = {
            ident: runtime
            for ident, runtime in self.live.items()
            if runtimes.get(ident) is runtime and runtime.live
        }
        self.swopping = {ident: n for ident, n in self.swopping.items() if ident in runtimes}
        self._index_exclusivity()

    def _index_exclusivity(self) -> None:
        self._exclusive = {}
        for runtime in self.runtimes.values():
            if runtime.playback.exclusivity is not None:
                self._exclusive.setdefault(runtime.playback.exclusivity, []).append(runtime)

    def next_seq(self) -> int:
        """A fresh activation sequence number: higher means newer."""
        self.seqCounter += 1
        return self.seqCounter

    def set_speed(self, speed: Mapping[MasterId, SpeedMasterRuntime]) -> None:
        """Install the engine's speed masters (at the first tick, and on a
        live swap before :meth:`rebind`). The dict is updated in place: every
        runtime shares it."""
        self.speed.clear()
        self.speed.update(speed)

    def set_size_levels(self, levels: Mapping[MasterId, float]) -> None:
        """Install the size masters' levels (at start, and on a live swap). The
        dict is updated in place: every runtime's effects read it."""
        self.sizeLevels.clear()
        self.sizeLevels.update(levels)

    # -- commands

    def trigger(self, ident: PlaybackId, now: float) -> None:
        """``TRIGGER_PLAYBACK``: activate at the first cue, or re-assert an
        active playback."""
        self._activate(self.runtimes[ident], now, "button")

    def toggle(self, ident: PlaybackId, now: float) -> None:
        """``TOGGLE_PLAYBACK``: release an active playback, activate any other."""
        runtime = self.runtimes[ident]
        if runtime.state == "active":
            runtime.release(now, runtime.release_time())
        else:
            self._activate(runtime, now, "button")

    def go(self, ident: PlaybackId, now: float) -> None:
        """``GO``: activate an idle or releasing playback at its first cue;
        move an active one to its next cue, and at the last cue wrap, release
        or re-assert (decision 9)."""
        runtime = self.runtimes[ident]
        if runtime.state != "active":
            self._activate(runtime, now, "button")
            return
        if runtime.chase is not None:  # one step on, keeping the grid (decision 10)
            self._move(runtime, now, runtime.chase.order.step(runtime.cue))
            return
        after = next_cue(runtime.playback.cueList, runtime.cue)
        if after == "release":
            runtime.release(now, runtime.release_time())
        else:
            self._move(runtime, now, runtime.cue if after == "reassert" else after)

    def back(self, ident: PlaybackId, now: float) -> None:
        """``BACK``: move an active playback to its previous cue (or wrap to
        the last), with that cue's timing. It schedules no auto-GO, or a
        ``follow 0`` cue would undo it at once. Otherwise nothing happens."""
        runtime = self.runtimes[ident]
        if runtime.state != "active":
            return
        if runtime.chase is not None:  # one step back, keeping the grid (decision 10)
            self._move(runtime, now, runtime.chase.order.back(runtime.cue))
            return
        before = previous_cue(runtime.playback.cueList, runtime.cue)
        if before is not None:
            self._move(runtime, now, before)
            runtime.cancel_auto()

    def goto(self, ident: PlaybackId, number: str, now: float) -> None:
        """``GOTO``: activate at the cue numbered ``number``, or move an active
        playback there; GOTO to the current cue re-asserts it.

        Raises :class:`KeyError` when the list has no such cue (the bus
        checks, but a live edit may have deleted it since).
        """
        runtime = self.runtimes[ident]
        index = runtime.playback.cueList.find(number)
        if index is None:
            raise KeyError(f"no cue {number}")
        self._goto(runtime, index, now)

    def _goto(self, runtime: PlaybackRuntime, index: int, now: float) -> None:
        """Activate at cue ``index``, or move an active playback there."""
        if runtime.state != "active":
            self._activate(runtime, now, "button", index)
        else:
            self._move(runtime, now, index)

    def release(self, ident: PlaybackId, now: float, time: float | None = None) -> None:
        """``RELEASE_PLAYBACK``: release an active playback over ``time``, or its
        :meth:`~PlaybackRuntime.release_time`. Idle and releasing playbacks
        are left alone."""
        runtime = self.runtimes[ident]
        if runtime.state == "active":
            runtime.release(now, runtime.release_time() if time is None else time)

    def release_all(self, now: float, time: float | None = None) -> None:
        """``RELEASE_ALL`` (phase-7-plan decision 15), the panic release.

        Held flash and swop buttons are dropped first: their later releases
        do nothing. Then every active playback releases over its
        :meth:`~PlaybackRuntime.release_time`, or over ``time`` when given;
        with ``time``, releases already running are cut to it too, so
        ``RELEASE_ALL {time: 0}`` is dark at once. A ``temp`` fader that is
        up keeps its flash: the fader is where the operator's hand left it.
        The programmer is not a playback and is left alone."""
        self.swopping.clear()
        for runtime in list(self.live.values()):
            if runtime.flashButton or runtime.swopButton:
                was_present = runtime.flashPresent
                runtime.flashButton = runtime.swopButton = False
                self._flash_changed(runtime, was_present, now)
            if runtime.state == "active":
                runtime.release(now, runtime.release_time() if time is None else time)
            elif runtime.state == "releasing" and time is not None:
                runtime.release(now, time)

    def restore(self, ident: PlaybackId, cue: int | None, level: float, now: float) -> None:
        """Put a playback back as an engine snapshot showed it, after an
        engine restart (phase-7-plan §5.7). The caller restores playbacks in
        ascending activation order and forces the fade-time override to 0,
        so every activation snaps.

        The fader goes to ``level`` first, with no ``autoStart``,
        ``autoRelease`` or takeover: a ``temp`` fader that is up flashes, a
        ``rate`` fader sets the rate the chase and effects start at, and a
        ``crossfade`` fader rests at the end it is at, or detached until it
        reaches one. Then, unless ``cue`` is ``None`` (the playback was not
        active), the playback activates at cue index ``cue`` with a fresh
        number, as a fader would (a threshold-mode playback below its
        threshold leaves its LTP values unlatched) when its fader is a
        ``master`` or ``size`` one and up, else as a button. A chase then
        takes its next step at the next boundary of its clock: an
        activation would count the nearest one as passed, which lags a
        step when the snapshot was taken late in one. A BPM chase whose
        steps are at least a beat apart keeps its beat but not which beats
        it steps on (its phase is not in the snapshot).
        """
        runtime = self.runtimes[ident]
        fader = runtime.playback.fader
        was_present = runtime.flashPresent
        runtime.faderLevel = level
        self._flash_changed(runtime, was_present, now)
        if fader == "crossfade":
            runtime.crossRest = level if level in (0.0, 1.0) else None
        if cue is None:
            return
        by: ActivatedBy = (
            "fader" if level > 0.0 and (runtime.masterFader or fader == "size") else "button"
        )
        self._activate(runtime, now, by, cue)
        if runtime.chase is not None:
            clock = runtime.chase.clock
            clock.done = math.floor(clock.position(now))
        if fader == "rate":
            runtime.bank.rerate(now, level)

    def flash(self, ident: PlaybackId, down: bool, now: float) -> None:
        """``FLASH``: the flash button went down or up."""
        runtime = self.runtimes[ident]
        was_present = runtime.flashPresent
        runtime.flashButton = down
        self._flash_changed(runtime, was_present, now)

    def button(self, ident: PlaybackId, function: ButtonFunction, down: bool, now: float) -> None:
        """``PLAYBACK_BUTTON``: a button with ``function`` went down or up
        (phase-6-plan decision 3).

        ``go``, ``back``, ``toggle`` and ``release`` act on press, as their
        commands do; ``goto`` goes to the playback's ``gotoCue`` on press,
        and does nothing without one; ``flash`` acts on both edges.
        ``swop`` acts on both edges too (:meth:`swop`). ``select`` changes
        the programmer, so the binding resolver sends it to the session; it
        and ``none`` do nothing here.
        """
        if function == "flash":
            self.flash(ident, down, now)
        elif function == "swop":
            self.swop(ident, down, now)
        elif not down:
            return
        elif function == "go":
            self.go(ident, now)
        elif function == "back":
            self.back(ident, now)
        elif function == "toggle":
            self.toggle(ident, now)
        elif function == "release":
            self.release(ident, now)
        elif function == "goto":
            runtime = self.runtimes[ident]
            if runtime.playback.gotoCue is not None:
                self._goto(runtime, runtime.playback.gotoCue, now)

    def swop(self, ident: PlaybackId, down: bool, now: float) -> None:
        """A swop button went down or up (decision 9): it holds the
        playback's flash up, and while any swop is held :meth:`update`
        suppresses the other playbacks. Presses are counted per playback, so
        the swop holds until its last release; a release without a press
        does nothing."""
        held = self.swopping.get(ident, 0) + (1 if down else -1)
        if held < 0:
            return
        if held:
            self.swopping[ident] = held
        else:
            self.swopping.pop(ident, None)
        runtime = self.runtimes[ident]
        was_present = runtime.flashPresent
        runtime.swopButton = held > 0
        self._flash_changed(runtime, was_present, now)

    def set_fader(self, ident: PlaybackId, level: float, now: float) -> None:
        """``SET_FADER``: move the fader, with ``autoStart``, ``autoRelease``, the
        threshold latch and ``temp`` flashes. A ``rate`` fader re-rates the
        chase and both banks' effects; a ``size`` fader starts and releases like a
        ``master`` one, without the threshold latch (decision 14); a
        ``crossfade`` fader drives the next transition (:meth:`_crossfade`)."""
        runtime = self.runtimes[ident]
        playback = runtime.playback
        previous = runtime.faderLevel
        was_present = runtime.flashPresent
        runtime.faderLevel = level
        self._flash_changed(runtime, was_present, now)
        if playback.fader == "rate":
            runtime.bank.rerate(now, level)
            runtime.flashBank.rerate(now, level)
            if runtime.chase is not None and runtime.chase.rerate(now, level):
                runtime.step_now(now)
            return
        if playback.fader == "crossfade":
            self._crossfade(runtime, level, now)
            return
        if not (runtime.masterFader or playback.fader == "size"):
            return
        active = runtime.state == "active"
        if previous == 0.0 and level > 0.0 and playback.autoStart and not active:
            self._activate(runtime, now, "fader")
        elif previous > 0.0 and level == 0.0 and playback.autoRelease and active:
            runtime.release(now, runtime.release_time())
        elif (
            active
            and runtime.thresholdMode
            and not runtime.ltpLatched
            and level >= playback.ltpThreshold
        ):
            runtime.latch_ltp(now)

    def _crossfade(self, runtime: PlaybackRuntime, level: float, now: float) -> None:
        """A ``crossfade`` fader moved to ``level`` (decision 11; see the
        module docs). During a manual transition the progress follows the
        fader's travel from the rest end, and the far end completes it.
        Otherwise a fader leaving its rest end starts the pending transition;
        a fader that rests at no end, or leaves it with nothing pending,
        drives nothing until it reaches an end, where it rests again."""
        manual = runtime.manual
        if manual is None:
            rest = runtime.crossRest
            if rest is None or level == rest or not self._cross_start(runtime, rest, now):
                runtime.crossRest = level if level in (0.0, 1.0) else None
                return
            manual = runtime.manual
            assert manual is not None
        manual.progress = max(manual.progress, abs(level - manual.rest))
        if manual.progress >= 1.0:
            runtime.complete_manual()

    def _cross_start(self, runtime: PlaybackRuntime, rest: float, now: float) -> bool:
        """Start the transition of a crossfade fader that left its rest end
        ``rest``, with a fresh number: an active playback's move to its next
        cue, or the activation of an idle or releasing one at its first cue
        with ``autoStart`` (and exclusivity). Returns whether there was one:
        a chase, the last cue of a list that does not wrap and an idle
        playback without ``autoStart`` have none."""
        cues = runtime.playback.cueList
        if cues.chasing or not cues.cues:
            return False
        if runtime.state == "active":
            after = next_cue(cues, runtime.cue)
            if not isinstance(after, int) or after == runtime.cue:
                return False
            runtime.move(now, after, SeqRule.fresh(self.next_seq()), manual=rest)
        elif runtime.playback.autoStart:
            self._activate(runtime, now, "fader", runtime.first_cue(), manual=rest)
        else:
            return False
        return True

    # -- speed masters

    def tap(self, ident: MasterId, now: float, banks: Iterable[EffectBank] = ()) -> None:
        """``TAP``: tap the master's tempo, then re-align every chase and effect
        clock locked to it near where it was before the master's phase moved
        (phase-4-plan decision 11, phase-5-plan §5.4). An effect clock nudges
        the difference away over a beat, so nothing moves at the tap.
        ``banks`` are other effect banks to re-align (the programmer's).
        While a strobe cap is set, the new tempo may move a capped effect's
        cycles per beat: every bank then re-rates (:meth:`_follow_cap`)."""
        master = self.speed[ident]
        locked = self._locked(master)
        banks = list(banks)
        clocks = [clock for bank in chain(self._banks(), banks) for clock in bank.locked(master)]
        before = [chase.clock.position(now) for _, chase in locked]
        positions = [clock.position(now) for clock in clocks]
        master.tap(now)
        for clock, p_ref in zip(clocks, positions, strict=True):
            clock.align(now, p_ref)
        for (runtime, chase), p_ref in zip(locked, before, strict=True):
            if chase.clock.align(now, chase.clock.rate, p_ref):
                runtime.step_now(now)
        self._follow_cap(now, banks)

    def set_bpm(
        self, ident: MasterId, bpm: float, now: float, banks: Iterable[EffectBank] = ()
    ) -> None:
        """``SET_BPM``: a new tempo at the same phase. Locked chases and
        effects follow the beat count, so their positions need no change,
        except capped effects (:meth:`_follow_cap`); ``banks`` are other
        effect banks (the programmer's)."""
        self.speed[ident].set_bpm(now, bpm)
        self._follow_cap(now, banks)

    def _follow_cap(self, now: float, banks: Iterable[EffectBank]) -> None:
        """After a tempo change, while a strobe cap is set: re-rate every
        live bank and ``banks``, so a capped BPM effect halves its cycles
        per beat for the new tempo (phase-7-plan §5.11). Clocks whose rate
        did not change are left alone, so this only aligns the capped ones;
        it runs on a tap or ``SET_BPM``, never per tick."""
        if self.cap.hz is None:
            return
        for bank in chain(self._banks(), banks):
            bank.rerate(now, bank.rateLevel)

    def set_speed_level(
        self, ident: MasterId, level: float, now: float, banks: Iterable[EffectBank] = ()
    ) -> None:
        """``SET_MASTER`` on a speed master: a new level and multiplier step,
        then every chase locked to it re-aligns to its new rate, and so do
        the effects that follow it (BPM effects locked to it, Hz effects
        naming it in ``speedMasterId``), ``banks`` (the programmer's)
        included. Effects whose rate did not change are left alone."""
        master = self.speed[ident]
        master.set_level(level)
        for runtime in self.live.values():
            runtime.bank.rerate(now, runtime.rateLevel)
            runtime.flashBank.rerate(now, runtime.rateLevel)
        for bank in banks:
            bank.rerate(now, bank.rateLevel)
        for runtime, chase in self._locked(master):
            if chase.rerate(now, runtime.rateLevel):
                runtime.step_now(now)

    def _banks(self) -> Iterator[EffectBank]:
        """Every live runtime's main and flash banks."""
        for runtime in self.live.values():
            yield runtime.bank
            yield runtime.flashBank

    def _locked(self, master: SpeedMasterRuntime) -> list[tuple[PlaybackRuntime, ChaseRuntime]]:
        """The live runtimes playing a chase locked to ``master``, with their chases."""
        return [
            (runtime, runtime.chase)
            for runtime in self.live.values()
            if runtime.chase is not None and runtime.chase.master is master
        ]

    # -- ticking

    def advance(self, now: float) -> bool:
        """Fire the events due by ``now`` (stages 1 and 3, decision 2):
        finished releases go idle, and auto-GOs and chase steps fire at
        their own times. Returns whether any state changed."""
        changed = False
        for runtime in self.live.values():
            changed |= runtime.finish_release(now)
            if runtime.auto is not None or runtime.chase is not None:
                changed |= runtime.fire(now)
        return changed

    def update(self, now: float) -> bool:
        """Advance every live runtime to ``now`` (stages 3–4) and drop the ones
        that are no longer live. While a swop is held, every runtime that is
        neither swopped nor protected is suppressed. Returns whether any
        state changed."""
        changed = False
        dead = False
        swopping = self.swopping
        for runtime in self.live.values():
            playback = runtime.playback
            suppressed = (
                bool(swopping) and playback.id not in swopping and not playback.protectFromSwop
            )
            changed |= runtime.update(now, suppressed)
            dead |= not runtime.live
        if dead:
            self.live = {ident: rt for ident, rt in self.live.items() if rt.live}
        return changed

    def sources(self) -> Iterator[Contributor]:
        """The contributors of every live runtime, as filled by the last
        :meth:`update`: main, flash, main's effect instances, then the flash
        bank's. Effects come after their playback's values, so the stable
        sort of :func:`~busk.engine.contributions.gather` hands them ties
        (decision 7)."""
        for runtime in self.live.values():
            yield runtime.main
            yield runtime.flash
            yield from runtime.bank.contributors()
            yield from runtime.flashBank.contributors()

    def relatives(self) -> Iterator[Relative]:
        """The relative layers of every live runtime's effects (both banks),
        as filled by the last :meth:`update`."""
        for runtime in self.live.values():
            yield from runtime.bank.relatives()
            yield from runtime.flashBank.relatives()

    # -- helpers

    def _move(self, runtime: PlaybackRuntime, now: float, cue: int) -> None:
        """A manual move (GO, BACK, GOTO) of an active playback: changed slots
        take a fresh number (decision 4). Moving to the current cue
        re-asserts it."""
        if cue == runtime.cue:
            self._activate(runtime, now, "button", cue)
        else:
            runtime.move(now, cue, SeqRule.fresh(self.next_seq()))

    def _activate(
        self,
        runtime: PlaybackRuntime,
        now: float,
        by: ActivatedBy,
        cue: int | None = None,
        manual: float | None = None,
    ) -> None:
        """A latching activation at cue index ``cue`` (default: the first cue,
        or the current one of an active playback, a re-assert): fresh seq,
        activate (driven by a crossfade fader that left ``manual``, if
        given), then exclusivity."""
        if cue is None:
            cue = runtime.cue if runtime.state == "active" else runtime.first_cue()
        runtime.activate(now, self.next_seq(), by, cue, manual)
        self.live[runtime.playback.id] = runtime
        key = runtime.playback.exclusivity
        if key is None:
            return
        for other in self._exclusive[key]:
            if other is not runtime and other.state == "active":
                other.release(now, other.release_time())

    def _flash_changed(self, runtime: PlaybackRuntime, was_present: bool, now: float) -> None:
        """A flash source that appears takes a fresh seq and makes the runtime
        live; then the flash bank starts or stops with it."""
        if runtime.flashPresent and not was_present:
            runtime.flashSeq = self.next_seq()
            self.live[runtime.playback.id] = runtime
        runtime.flash_effects(now)
