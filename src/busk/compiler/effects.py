"""Compiled effects (spec §5.10, §10; phase-5-plan §5.2).

An effect *instance* in a cue names a template, its targets, a rate, a size
and a phase spread. The compiler turns each one into a
:class:`CompiledEffect`: per template layer, the lanes it drives, each
member's phase offset and the waveform or palette, as read-only arrays. The
engine's effect runtimes evaluate those every tick without looking at show
data again.

* :func:`compile_wave` turns a template layer's waveform into a
  :class:`CompiledWave`, the form :func:`busk.engine.waveforms.evaluate`
  evaluates: parameters as floats, step levels as an array, curve points
  already extended by one period so the evaluation is a single ``np.interp``.
* :func:`spread_positions` and :func:`member_offsets` are the §10.2 phase
  spread (decision 5), computed once over the instance's ordered targets.
* :func:`compile_effect` builds a whole instance (the steps are in its
  docstring); :meth:`CompiledEffect.without` and
  :meth:`CompiledEffect.remapped` derive trimmed and moved copies for
  tracking releases and live swaps.

The compiler never imports the engine; the engine reads these structures.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final, Literal, cast

import numpy as np
from numpy.typing import NDArray

from busk.compiler.slots import Slot, SlotIndex, SlotTable
from busk.model.attributes import ATTRIBUTES, ColorValue, ScalarRange
from busk.model.common import AttributeId, MasterId, TargetRef, target_key
from busk.model.effect import (
    ColorLayer,
    EffectInstance,
    EffectPhase,
    PaletteEntry,
    PresetRef,
    ScalarLayer,
    Waveform,
)
from busk.model.validate import Issue

if TYPE_CHECKING:
    from busk.compiler.cues import CueCompiler

type WaveKind = Literal[
    "sine", "triangle", "square", "sawUp", "sawDown", "pulse", "step", "random", "curve"
]
"""The nine waveforms of §10.3."""


def _readonly(values: list[float]) -> NDArray[np.float64]:
    array = np.array(values, dtype=np.float64)
    array.flags.writeable = False
    return array


def _none() -> NDArray[np.float64]:
    """The empty array of the fields a wave's kind does not use."""
    return _readonly([])


@dataclass(frozen=True, kw_only=True)
class CompiledWave:
    """A waveform in the form its formula wants (phase-5-plan §5.1, decision 3).

    Only the fields of its ``kind`` are meaningful:

    * ``square``: ``duty``, the fraction of the cycle at 1;
    * ``pulse``: ``attack``, ``width`` and ``decay``, fractions of a cycle
      (validated ≥ 0 and summing to at most 1);
    * ``step``: ``steps``, the levels, each held for an equal share of the cycle;
    * ``random``: ``seed`` (reduced to 64 bits) and ``smooth``;
    * ``curve``: ``xs``/``ys``, the points extended periodically so they
      cover ``[0, 1]`` (see :func:`compile_wave`).
    """

    kind: WaveKind
    duty: float = 0.5
    attack: float = 0.0
    width: float = 0.0
    decay: float = 0.0
    steps: NDArray[np.float64] = field(default_factory=_none)
    seed: int = 0
    smooth: bool = False
    xs: NDArray[np.float64] = field(default_factory=_none)
    ys: NDArray[np.float64] = field(default_factory=_none)


_SEED_MASK: Final = (1 << 64) - 1


def compile_wave(wave: Waveform) -> CompiledWave:
    """Compile a validated waveform.

    A curve is piecewise-linear through its points and periodic. Its points
    are extended by one period on each open side: when the first point is
    after ``x = 0``, the last point is repeated one cycle earlier; when the
    last point is before ``x = 1``, the first is repeated one cycle later. The
    wave is then continuous across the cycle boundary, unless the points
    themselves put different values at ``x = 0`` and ``x = 1`` (a saw drawn
    as a curve jumps where it says it does). No ``x`` repeats, so
    ``np.interp`` is exact on every phase in ``[0, 1]``.
    """
    match wave["kind"]:
        case "square":
            return CompiledWave(kind="square", duty=wave["duty"])
        case "pulse":
            return CompiledWave(
                kind="pulse", attack=wave["attack"], width=wave["width"], decay=wave["decay"]
            )
        case "step":
            return CompiledWave(kind="step", steps=_readonly(wave["steps"]))
        case "random":
            return CompiledWave(
                kind="random", seed=wave["seed"] & _SEED_MASK, smooth=wave["smooth"]
            )
        case "curve":
            points = [(float(x), float(y)) for x, y in wave["points"]]
            (x0, y0), (xn, yn) = points[0], points[-1]
            if x0 > 0.0:
                points.insert(0, (xn - 1.0, yn))
            if xn < 1.0:
                points.append((x0 + 1.0, y0))
            return CompiledWave(
                kind="curve",
                xs=_readonly([x for x, _ in points]),
                ys=_readonly([y for _, y in points]),
            )
        case kind:
            return CompiledWave(kind=kind)


# -------------------------------------------------------------- phase spread


def spread_positions(
    count: int, *, wings: int = 1, blocks: int = 1, groups: int = 1
) -> NDArray[np.intp]:
    """The position of each of ``count`` ordered members after §10.2 steps
    1–3 (phase-5-plan decision 5):

    1. **wings**: the members split into ``wings`` sections of
       ``S = ceil(count / wings)``; member ``k`` takes its place in its
       section, ``k mod S``, reversed (``S − 1 − …``) in odd sections, so
       the pattern mirrors. A short last section is the start of its mirror;
    2. **blocks**: ``k := floor(k / blocks)``, so neighbours share a position;
    3. **groups**: ``k := k mod groups`` when ``groups > 1``, so members
       cycle through a few positions.

    The positions used are exactly ``0 … M − 1`` for some ``M``.
    """
    k = np.arange(count, dtype=np.intp)
    if count == 0:
        return k
    size = -(-count // wings)
    place = k % size
    k = np.where((k // size) % 2 == 1, size - 1 - place, place).astype(np.intp)
    k //= blocks
    if groups > 1:
        k %= groups
    return k


def member_offsets(
    count: int, phase: EffectPhase, *, wings: int = 1, blocks: int = 1, groups: int = 1
) -> NDArray[np.float64]:
    """Each member's phase offset **in cycles** (§10.2 step 4):
    ``(start + (end − start)·k / M) / 360``, with ``k`` the member's
    :func:`spread_positions` position and ``M`` the number of positions.

    Dividing by ``M``, not ``M − 1``, spreads a 0°→360° phase evenly around
    the cycle: the first and last positions do not land on the same phase.
    """
    k = spread_positions(count, wings=wings, blocks=blocks, groups=groups)
    if count == 0:
        return np.zeros(0, dtype=np.float64)
    positions = int(k.max()) + 1
    start, end = float(phase["start"]), float(phase["end"])
    return (start + (end - start) * k / positions) / 360.0


# ----------------------------------------------------------- compiled forms

type LayerMode = Literal["absolute", "add", "multiply"]
"""How a layer applies (§10.4): it *is* the value, or offsets or scales it."""

type EffectDirection = Literal["forward", "reverse", "bounce"]
"""How the effect's position maps to its base phase (decision 4)."""


def _frozen[T: np.generic](array: NDArray[T]) -> NDArray[T]:
    array.flags.writeable = False
    return array


def _no_lanes() -> NDArray[np.intp]:
    return _frozen(np.zeros(0, dtype=np.intp))


@dataclass(frozen=True, kw_only=True, eq=False)
class CompiledLayer:
    """One template layer of one instance, over the members that have its
    attribute. Members without it are skipped, keeping their phase.

    ``lanes`` say where the layer writes, one row per member:

    * an ``absolute`` intensity layer (``htp``): positions in
      ``SlotTable.intensityLanes``, merged HTP like a cue's intensities;
    * any other scalar layer: frame lanes (``add`` and ``multiply`` layers
      on intensity too: the relative pass works on the frame);
    * a colour layer: shape ``(members, 3)``, each member's ``r, g, b``
      lanes. ``extras`` lists every member's other emitter lanes, which the
      layer holds at ``NaN`` ("derive", decision 6).

    ``member`` is each row's index in the instance's targets (the random
    wave hashes it) and ``phase`` its offset in cycles: the member's spread
    offset plus the layer's ``phaseOffset``.

    A scalar layer is driven by ``wave``; an absolute one sweeps from
    ``low`` (``w = 0``) to ``high`` (``w = 1``). A colour layer cycles
    through ``palette``, shape ``(members, K, 3)``: each member's colours,
    resolved (presets by scope) and clamped to ``0..1``, blended per
    ``blend``. ``clamp`` is the registry range an ``add`` layer's result is
    clipped to, when its attribute has one.

    Compare layers with :meth:`CompiledEffect.same`; ``==`` is identity.
    """

    attribute: AttributeId
    mode: LayerMode
    htp: bool
    lanes: NDArray[np.intp]
    member: NDArray[np.intp]
    phase: NDArray[np.float64]
    wave: CompiledWave | None = None
    low: float = 0.0
    high: float = 1.0
    palette: NDArray[np.float64] | None = None
    blend: Literal["fade", "snap"] = "fade"
    extras: NDArray[np.intp] = field(default_factory=_no_lanes)
    clamp: tuple[float, float] | None = None

    def frame_lanes(self, table: SlotTable) -> NDArray[np.intp]:
        """Each row's (first) lane in the frame of ``table``, the table the
        layer was compiled against: HTP positions resolved, a colour row's
        ``r`` lane."""
        if self.htp:
            return table.intensityLanes[self.lanes]
        return self.lanes[:, 0] if self.lanes.ndim == 2 else self.lanes

    def rows(
        self, keep: NDArray[np.bool_], lanes: NDArray[np.intp], extras: NDArray[np.intp]
    ) -> CompiledLayer | None:
        """This layer with only the rows ``keep`` selects, on ``lanes`` (one row
        per current row) and ``extras``; ``None`` when no row is left."""
        if not keep.any():
            return None
        return replace(
            self,
            lanes=_frozen(lanes[keep]),
            member=_frozen(self.member[keep]),
            phase=_frozen(self.phase[keep]),
            palette=None if self.palette is None else _frozen(self.palette[keep]),
            extras=_frozen(extras),
        )


@dataclass(frozen=True, kw_only=True, eq=False)
class CompiledEffect:
    """One effect instance, compiled (phase-5-plan §5.2).

    ``key`` is the instance id, its identity across the cues of a list
    (tracking, decision 8). The rate is either ``hz`` cycles per second
    (scaled by the step of ``speedMasterId``, if any), or ``multiplier``
    cycles per beat of speed master ``masterId`` (``bpm``; a BPM effect
    follows its rate's master, so ``speedMasterId`` is ``None``).

    ``size`` is the amplitude of relative layers (attribute units for
    ``add``, ``0..1`` for ``multiply``), scaled at run time by the size
    master ``sizeMasterId`` and the playback's ``size`` fader.
    ``sizeFadeIn`` is how long the instance takes to fade in when it starts.

    ``layers`` hold the template's layers that drive at least one lane, in
    template order; ``targets`` the expanded targets in order. A layer row's
    ``member`` indexes ``targets``, which stay whole when :meth:`without`
    or :meth:`remapped` drop rows, so the remaining members keep their
    phases and random values.

    Compare effects with :meth:`same`; ``==`` is identity, which is what
    the engine checks first (within one compile, a tracked instance is the
    same object in every cue that holds it).
    """

    key: str
    rate: Literal["hz", "bpm"]
    hz: float
    masterId: MasterId | None
    multiplier: float
    speedMasterId: MasterId | None
    direction: EffectDirection
    size: float
    sizeFadeIn: float | None
    sizeMasterId: MasterId | None
    layers: tuple[CompiledLayer, ...]
    targets: tuple[TargetRef, ...]

    def same(self, other: CompiledEffect) -> bool:
        """Whether ``other`` is structurally equal: every field equal, every
        array of the same shape and values. A live edit that leaves an
        instance alone recompiles it to a new object that is the same."""
        return _same(self, other)

    @property
    def driven(self) -> tuple[TargetRef, ...]:
        """The targets that have a row in some layer, in target order: the
        members the instance drives (a playback's ``select`` button). A
        member without any layer's attribute, or one whose every row a
        release trimmed, is left out."""
        members = set[int]()
        for layer in self.layers:
            members.update(layer.member.tolist())
        return tuple(target for k, target in enumerate(self.targets) if k in members)

    def without(self, slots: AbstractSet[SlotIndex], table: SlotTable) -> CompiledEffect | None:
        """This effect without any lane of ``slots`` (a tracked instance
        trimmed by a cue's releases); ``self`` when it drives none of them,
        ``None`` when no lane is left. ``table`` is the slot table it was
        compiled against."""
        if not slots:
            return self
        released = np.fromiter(slots, dtype=np.intp, count=len(slots))
        layers: list[CompiledLayer] = []
        for layer in self.layers:
            keep = ~np.isin(table.laneSlot[layer.frame_lanes(table)], released)
            extras = layer.extras[~np.isin(table.laneSlot[layer.extras], released)]
            if keep.all() and extras.size == layer.extras.size:
                layers.append(layer)
                continue
            trimmed = layer.rows(keep, layer.lanes, extras)
            if trimmed is not None:
                layers.append(trimmed)
        return self._with(layers)

    def remapped(
        self, laneMap: NDArray[np.integer[Any]], posMap: NDArray[np.integer[Any]]
    ) -> CompiledEffect | None:
        """This effect on a new slot table (a live swap that moved slots).

        ``laneMap`` maps each old frame lane to its new lane and ``posMap``
        each old intensity position to its new one, −1 where it is gone
        (:func:`busk.engine.install.lane_maps`). Rows whose lanes are gone
        are dropped; ``self`` when nothing moved, ``None`` when no lane is
        left."""
        layers: list[CompiledLayer] = []
        for layer in self.layers:
            moved = (posMap if layer.htp else laneMap)[layer.lanes].astype(np.intp)
            keep = moved >= 0 if moved.ndim == 1 else (moved >= 0).all(axis=1)
            extras = laneMap[layer.extras].astype(np.intp)
            extras = extras[extras >= 0]
            if np.array_equal(moved, layer.lanes) and np.array_equal(extras, layer.extras):
                layers.append(layer)
                continue
            new = layer.rows(keep, moved, extras)
            if new is not None:
                layers.append(new)
        return self._with(layers)

    def _with(self, layers: list[CompiledLayer]) -> CompiledEffect | None:
        """``self`` if ``layers`` are its own layers, else a copy with them;
        ``None`` without any."""
        if len(layers) == len(self.layers) and all(
            new is old for new, old in zip(layers, self.layers, strict=True)
        ):
            return self
        return replace(self, layers=tuple(layers)) if layers else None


def _same(a: object, b: object) -> bool:
    """Structural equality: arrays exactly (shape and values), tuples item by
    item, dataclasses field by field, anything else by ``==``."""
    if a is b:
        return True
    if isinstance(a, np.ndarray):
        return isinstance(b, np.ndarray) and bool(np.array_equal(a, b))
    if isinstance(a, tuple):
        return isinstance(b, tuple) and len(a) == len(b) and all(map(_same, a, b))
    if dataclasses.is_dataclass(a) and not isinstance(a, type):
        return type(a) is type(b) and all(
            _same(getattr(a, f.name), getattr(b, f.name)) for f in dataclasses.fields(a)
        )
    return bool(a == b)


# ---------------------------------------------------------------- compiling


def compile_effect(
    compiler: CueCompiler, instance: EffectInstance, path: str
) -> CompiledEffect | None:
    """Compile one validated effect instance, found at ``path`` in the show.

    1. Look up the template and expand the targets (a group follows its
       members). ``compiler`` notes both, and every palette preset, so the
       incremental recompile knows what the cue list read.
    2. Compute the members' phase offsets (:func:`member_offsets`).
    3. Per layer, keep the members with a slot for its attribute.
    4. Resolve colour palettes per member: a literal colour as is, a preset
       through the §5.8 scope lookup. Colours are clamped to ``0..1`` and
       their extras dropped (decision 6). A member for which a palette preset
       has no colour is left out of the layer, with a compile warning.
    5. Absolute scalar layers sweep ``low``..``high``: by default the
       attribute's registry range, and always clamped to it. ``add`` layers
       on a ranged attribute get that range as their clamp.
    6. Layers without members are dropped. An instance left without layers
       compiles to ``None``, with a compile warning: it would do nothing.
    """
    template = compiler.template(instance["templateId"])
    targets = tuple(compiler.targets(instance["targets"]))
    offsets = member_offsets(
        len(targets),
        instance["phase"],
        wings=instance["wings"],
        blocks=instance["blocks"],
        groups=instance["groups"],
    )
    layers: list[CompiledLayer] = []
    for layer in template["layers"]:
        compiled = (
            _color_layer(compiler, cast(ColorLayer, layer), targets, offsets, path)
            if "palette" in layer
            else _scalar_layer(compiler.slots, layer, instance, targets, offsets)
        )
        if compiled is not None:
            layers.append(compiled)
    if not layers:
        names = list(dict.fromkeys(layer["attribute"] for layer in template["layers"]))
        compiler.warnings.append(
            Issue("warning", path, f"no target has {_either(names)}: the effect does nothing")
        )
        return None
    rate = instance["rate"]
    if rate["kind"] == "hz":
        hz, master, multiplier = float(rate["value"]), None, 1.0
        speed = instance.get("speedMasterId")
    else:
        hz, master, multiplier, speed = 0.0, rate["masterId"], float(rate["multiplier"]), None
    fade_in = instance.get("sizeFadeIn")
    return CompiledEffect(
        key=instance["id"],
        rate=rate["kind"],
        hz=hz,
        masterId=master,
        multiplier=multiplier,
        speedMasterId=speed,
        direction=instance["direction"],
        size=float(instance["size"]),
        sizeFadeIn=None if fade_in is None else float(fade_in),
        sizeMasterId=instance.get("sizeMasterId"),
        layers=tuple(layers),
        targets=targets,
    )


def _either(names: Sequence[str]) -> str:
    """``pan``, ``pan or tilt``, ``pan, tilt or zoom``."""
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} or {names[-1]}"


def _scalar_layer(
    slots: SlotTable,
    layer: ScalarLayer,
    instance: EffectInstance,
    targets: Sequence[TargetRef],
    offsets: NDArray[np.float64],
) -> CompiledLayer | None:
    """Steps 3 and 5 for a scalar layer; ``None`` when no member has its attribute."""
    attribute = layer["attribute"]
    found = [
        (k, slot) for k, t in enumerate(targets) if (slot := slots.find(t, attribute)) is not None
    ]
    if not found:
        return None
    definition = ATTRIBUTES[attribute]
    mode = layer["mode"]
    htp = mode == "absolute" and definition.merge == "HTP"
    lanes = np.array([slot.laneOffset for _, slot in found], dtype=np.intp)
    if htp:
        lanes = np.searchsorted(slots.intensityLanes, lanes).astype(np.intp)
    member = np.array([k for k, _ in found], dtype=np.intp)
    low, high = _bounds(instance, definition.range) if mode == "absolute" else (0.0, 1.0)
    ranged = definition.range
    return CompiledLayer(
        attribute=attribute,
        mode=mode,
        htp=htp,
        lanes=_frozen(lanes),
        member=_frozen(member),
        phase=_frozen(offsets[member] + layer["phaseOffset"] / 360.0),
        wave=compile_wave(layer["waveform"]),
        low=low,
        high=high,
        clamp=(ranged.min, ranged.max) if mode == "add" and ranged is not None else None,
    )


def _bounds(instance: EffectInstance, ranged: ScalarRange | None) -> tuple[float, float]:
    """An absolute layer's ``low`` and ``high``: the instance's, defaulting to
    the attribute's range and clamped to it. Validation requires both for an
    attribute without a range."""
    if ranged is None:
        return float(cast(float, instance["low"])), float(cast(float, instance["high"]))
    low = float(cast(float, instance.get("low", ranged.min)))
    high = float(cast(float, instance.get("high", ranged.max)))
    return min(max(low, ranged.min), ranged.max), min(max(high, ranged.min), ranged.max)


def _color_layer(
    compiler: CueCompiler,
    layer: ColorLayer,
    targets: Sequence[TargetRef],
    offsets: NDArray[np.float64],
    path: str,
) -> CompiledLayer | None:
    """Steps 3–4 for a colour layer; ``None`` when no member keeps a colour slot."""
    for entry in layer["palette"]:
        if "presetId" in entry:
            compiler.readPresets.add(cast(PresetRef, entry)["presetId"])
    rows: list[list[int]] = []
    members: list[int] = []
    palettes: list[list[tuple[float, float, float]]] = []
    extras: list[int] = []
    for k, target in enumerate(targets):
        slot = compiler.slots.find(target, "color")
        if slot is None:
            continue
        colours = _palette(compiler, layer["palette"], slot, path)
        if colours is None:
            continue
        first = slot.laneOffset
        rows.append([first, first + 1, first + 2])
        members.append(k)
        palettes.append(colours)
        extras.extend(range(first + 3, first + slot.laneCount))
    if not members:
        return None
    member = np.array(members, dtype=np.intp)
    return CompiledLayer(
        attribute="color",
        mode="absolute",
        htp=False,
        lanes=_frozen(np.array(rows, dtype=np.intp)),
        member=_frozen(member),
        phase=_frozen(offsets[member]),
        palette=_frozen(np.array(palettes, dtype=np.float64)),
        blend=layer["blend"],
        extras=_frozen(np.array(extras, dtype=np.intp)),
    )


def _palette(
    compiler: CueCompiler, entries: Sequence[PaletteEntry], slot: Slot, path: str
) -> list[tuple[float, float, float]] | None:
    """One member's palette as clamped ``(r, g, b)`` s, or ``None`` (with a
    compile warning) when a palette preset has no colour for it."""
    colours: list[tuple[float, float, float]] = []
    for entry in entries:
        if "presetId" in entry:
            preset = cast(PresetRef, entry)["presetId"]
            value = compiler.preset_value(preset, slot)
            if value is None:
                compiler.warnings.append(
                    Issue(
                        "warning",
                        path,
                        f"palette preset {preset!r} has no colour for "
                        f"{target_key(slot.target)}; it is left out of the effect",
                    )
                )
                return None
            colour = cast(ColorValue, value)
        else:
            colour = entry
        r, g, b = (min(max(float(c), 0.0), 1.0) for c in (colour["r"], colour["g"], colour["b"]))
        colours.append((r, g, b))
    return colours
