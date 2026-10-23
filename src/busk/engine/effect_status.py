"""Reading the running effects back (GAP-09 of ``docs/dev/tui/engine-gaps.md``).

A display that shows effects (a table of them with a running state and a
sparkline of each) needs what only the engine knows: which instances run,
how far each has faded in, its rate and phase now, and its waveform or
colours. As with the output readout (:mod:`busk.engine.readout`), the read
has two halves:

* :func:`capture_effects`, on the engine thread at the end of a tick: per
  running instance, its newest compiled form (immutable) and what its last
  :meth:`~busk.engine.effects.EffectRuntime.update` evaluated: the clock's
  position, the presences and the dynamics. It allocates a small record per
  instance, so the engine captures only while someone reads the effects
  (:attr:`Engine.captureEffects <busk.engine.loop.Engine.captureEffects>`).
* :func:`read_effects`, on any thread: the public
  :class:`~busk.engine.snapshot.EffectSnapshot` of a capture. The samples
  of the next cycle are the engine's own functions
  (:func:`~busk.engine.effects.base_phase`,
  :func:`~busk.engine.waveforms.evaluate`,
  :func:`~busk.engine.effects.palette_colours`) at the clock positions
  ``P + k / WAVE_SAMPLES``, so sample ``k`` is what the first member does
  ``k / (WAVE_SAMPLES · hz)`` seconds from the tick, while the rate holds.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

import numpy as np

from busk.compiler.compile import CompiledShow
from busk.compiler.effects import CompiledEffect
from busk.engine.contributions import Origin
from busk.engine.effects import EffectBank, base_phase, palette_colours
from busk.engine.snapshot import EffectSnapshot, EffectStatus
from busk.engine.waveforms import evaluate

WAVE_SAMPLES: Final = 20
"""Samples of the next cycle in :attr:`EffectStatus.wave
<busk.engine.snapshot.EffectStatus.wave>` and ``colors``: a sparkline's cells."""

_STEPS: Final = tuple(k / WAVE_SAMPLES for k in range(WAVE_SAMPLES))


@dataclass(frozen=True, slots=True, kw_only=True)
class RunningEffect:
    """One running instance at the capturing tick, raw."""

    origin: Origin | None  # its bank's: the playback whose effect it is, or none
    effect: CompiledEffect  # its newest version
    position: float  # the clock's, in cycles
    presence: float  # Σ of its versions' presences, at most 1
    dynamics: float  # d of its newest version
    hz: float


@dataclass(frozen=True, slots=True, kw_only=True)
class EffectCapture:
    """The effects running at one tick, raw: what :func:`read_effects` reads."""

    seq: int  # the tick's, as in its Frame
    time: float
    compiled: CompiledShow  # the show the tick ran
    effects: tuple[RunningEffect, ...]


def capture_effects(
    *, seq: int, time: float, compiled: CompiledShow, banks: Iterable[EffectBank]
) -> EffectCapture:
    """Capture every running instance of ``banks``, as the tick that just
    ran with ``compiled`` evaluated them. Engine thread only, before the next
    tick changes them."""
    return EffectCapture(
        seq=seq,
        time=time,
        compiled=compiled,
        effects=tuple(
            RunningEffect(
                origin=bank.origin,
                effect=runtime.newest.effect,
                position=runtime.position,
                presence=min(1.0, sum(runtime.presences)),
                dynamics=runtime.dynamics[-1],
                hz=runtime.clock.hz,
            )
            for bank in banks
            for runtime in bank.runtimes.values()
        ),
    )


def read_effects(captured: EffectCapture) -> EffectSnapshot:
    """The public form of ``captured`` (see :class:`~busk.engine.snapshot.EffectStatus`)."""
    playbacks = captured.compiled.playbacks
    statuses: list[EffectStatus] = []
    for running in captured.effects:
        origin, effect = running.origin, running.effect
        ident = None if origin is None else origin.playback
        playback = None if ident is None else playbacks.get(ident)
        wave, colors = _next_cycle(effect, running.position)
        statuses.append(
            EffectStatus(
                playback=None if playback is None else playback.number,
                cue=effect.cue,
                id=effect.key,
                presence=running.presence,
                size=effect.size * running.dynamics,
                hz=running.hz,
                phase=base_phase(effect.direction, running.position) % 1.0,
                wave=wave,
                colors=colors,
            )
        )
    return EffectSnapshot(seq=captured.seq, time=captured.time, effects=tuple(statuses))


def _next_cycle(
    effect: CompiledEffect, position: float
) -> tuple[tuple[float, ...], tuple[tuple[float, float, float], ...]]:
    """The next cycle of ``effect`` from clock position ``position``: the
    wave of its first layer with one and the colours of its first colour
    layer, for each layer's first member, at :data:`WAVE_SAMPLES` steps."""
    bases = np.array([base_phase(effect.direction, position + step) for step in _STEPS])
    wave: tuple[float, ...] = ()
    colors: tuple[tuple[float, float, float], ...] = ()
    for layer in effect.layers:
        phase = bases + layer.phase[0]
        if layer.wave is not None and not wave:
            member = np.full(WAVE_SAMPLES, layer.member[0], dtype=np.intp)
            wave = tuple(evaluate(layer.wave, phase, member, np.empty(WAVE_SAMPLES)).tolist())
        elif layer.palette is not None and not colors:
            first = np.broadcast_to(layer.palette[:1], (WAVE_SAMPLES, *layer.palette.shape[1:]))
            out = np.empty((WAVE_SAMPLES, 3))
            palette_colours(first, phase, layer.blend == "snap", out)
            colors = tuple((r, g, b) for r, g, b in out.tolist())
    return wave, colors
