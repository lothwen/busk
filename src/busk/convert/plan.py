"""The conversion plan: compiled channels flattened into arrays (spec §13, §19).

Converting channel by channel in Python costs about 4 ms per tick for the
§19 reference rig (about 31 000 channels), four times the budget for masters,
safety and conversion together. The plan therefore flattens every
:class:`~busk.compiler.channels.CompiledChannel` into a *structure of
arrays*, and :class:`~busk.convert.converter.Converter` runs a fixed
sequence of numpy kernels over it. The Python work per tick then depends on
the number of distinct curves and resolutions, never on the size of the rig.

Layout
------
Channels are laid out in three consecutive blocks. The blocks index the
value vector ``V`` (the logical value each channel outputs) and the raw
vector (its DMX value in full resolution)::

    [ range channels | colour channels | option channels ]
      0 … R−1          R … R+C−1         R+C … R+C+O−1

``V`` covers only the first two blocks: options produce raw values directly.

Colour is computed per *colour slot* (a column) in a matrix with one row
per emitter role (:data:`COLOR_ROWS`); each colour channel then picks its
``(row, column)`` entry.

Uniform maps
------------
Every channel ends in ``raw = rint(d0 + t·(d1 − d0))`` with
``t = clip((v − v0) / (v1 − v0), 0, 1)``. The compiler folds two special
cases into that one formula, so the kernels never branch:

* a **zero-span** segment (``v0 == v1``) stores span 1, ``d0`` = its DMX
  centre and a DMX span of 0, so it always outputs the centre;
* an **option without a parameter** stores its raw value as ``d0`` with a
  DMX span of 0, reading its own (always finite) option lane.

These rewrites leave the result bit-identical to the per-channel formula:
``x + t·0 = x`` exactly for finite ``t``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from busk.compiler.channels import CompiledChannel, Segment
from busk.compiler.slots import SlotTable
from busk.convert.dmx import UNIVERSE_SIZE
from busk.model.profile import DimmerCurve

type IntArray = NDArray[np.intp]
type FloatArray = NDArray[np.float64]

ADDITIVE_ROWS: Final[Mapping[str, int]] = {
    "red": 0,
    "green": 1,
    "blue": 2,
    "white": 3,
    "amber": 4,
    "uv": 5,
}
"""Colour matrix rows of the additive emitter roles. Virtual intensity scales
rows ``0 … 5``."""
SUBTRACTIVE_ROWS: Final[Mapping[str, int]] = {"cyanFlag": 6, "magentaFlag": 7, "yellowFlag": 8}
"""Colour matrix rows of the CMY flags (``1 − r``, ``1 − g``, ``1 − b``)."""
ZERO_ROW: Final = 9
"""An always-zero row, for emitters that cannot be mixed until calibrated
mixing exists (lime, cyan, custom ids)."""
COLOR_ROWS: Final = 10


# ------------------------------------------------------------------ the plan


@dataclass(frozen=True, kw_only=True)
class DimmerGroup:
    """Intensity range channels whose mode uses ``curve``."""

    curve: DimmerCurve
    positions: IntArray  # into the range block of V


@dataclass(frozen=True, kw_only=True)
class RangeInputs:
    """Stage 1: ``V = (L[lane] + offset) · sign``, then dimmer curves."""

    lanes: IntArray
    offsets: FloatArray  # pan/tilt orientation offsets, else 0
    signs: FloatArray  # −1 for inverted pan/tilt, else 1
    dimmerGroups: tuple[DimmerGroup, ...]


@dataclass(frozen=True, kw_only=True)
class VirtualGroup:
    """Colour slots dimmed virtually through ``curve``."""

    curve: DimmerCurve
    columns: IntArray  # colour matrix columns
    lanes: IntArray  # the intensity lane of each column


@dataclass(frozen=True, kw_only=True)
class ExtraInputs:
    """The colour slots that have one extra lane (``w``, ``a`` or ``uv``)."""

    columns: IntArray  # colour matrix columns
    lanes: IntArray  # the extra's lane in each of those slots


@dataclass(frozen=True, kw_only=True)
class ColorInputs:
    """Stage 2, per colour slot (one matrix column each).

    Rows that only some slots need are computed only for those columns: the
    white, amber and UV rows for slots with that extra, the CMY rows for
    subtractive slots. The other entries of those rows stay 0 and no
    channel reads them.
    """

    rgbLanes: IntArray  # shape (3, S)
    white: ExtraInputs
    amber: ExtraInputs
    uv: ExtraInputs
    subtractiveColumns: IntArray
    virtualGroups: tuple[VirtualGroup, ...]
    pick: IntArray  # per colour channel: row · S + column

    @property
    def columns(self) -> int:
        """The number of colour slots, S."""
        return int(self.rgbLanes.shape[1])


@dataclass(frozen=True, kw_only=True)
class SegmentMaps:
    """Uniform maps ``v → raw`` (see module docs), one per value.

    Values whose channel has several range segments are listed in
    ``multiPositions``; their row in the single-segment arrays is a
    placeholder that the multi-segment kernel overwrites. The ``multi``
    tables have shape ``(M, K)``: one row per such channel, padded to the
    longest with segments that are infinitely far away.
    """

    v0: FloatArray
    span: FloatArray
    d0: FloatArray
    dspan: FloatArray
    multiPositions: IntArray
    multiLow: FloatArray
    multiHigh: FloatArray
    multiV0: FloatArray
    multiSpan: FloatArray
    multiD0: FloatArray
    multiDSpan: FloatArray


@dataclass(frozen=True, kw_only=True)
class OptionMaps:
    """Stage 4: per option channel, then per option.

    The options of all channels are concatenated; a channel's options start
    at ``first``. Each option maps a parameter lane through ``maps``; an
    option without a parameter maps to its constant raw value.
    """

    lanes: IntArray  # the option index lane of each channel
    first: IntArray
    last: FloatArray  # number of options − 1, for clipping the index
    paramLanes: IntArray  # per option
    maps: SegmentMaps  # per option; single-segment only


@dataclass(frozen=True, kw_only=True)
class ByteGroup:
    """Channels of one resolution, split together with
    :func:`~busk.convert.dmx.split_raw`.

    ``targets`` has one entry per byte, coarse first: the positions within
    ``channels`` of the channels that own that byte (``None`` when all of
    them do), and the flat address (``row · 512 + address``) each byte is
    written to. Addresses are unique across the whole plan.
    """

    bytes: int
    channels: IntArray  # positions in the raw vector
    targets: tuple[tuple[IntArray | None, IntArray], ...]


@dataclass(frozen=True, kw_only=True)
class ConversionPlan:
    """Everything the converter needs, as read-only arrays (see module docs)."""

    laneCount: int
    universeCount: int
    rangeCount: int  # R
    colorCount: int  # C
    optionCount: int  # O
    ranges: RangeInputs
    colors: ColorInputs
    segments: SegmentMaps  # over V: R + C values
    options: OptionMaps
    byteGroups: tuple[ByteGroup, ...]


# ------------------------------------------------------------------- builder


def build_plan(
    channels: Sequence[CompiledChannel], slots: SlotTable, universe_count: int
) -> ConversionPlan:
    """Flatten ``channels`` into a :class:`ConversionPlan`."""
    ranges = [channel for channel in channels if channel.kind == "range"]
    colors = [channel for channel in channels if channel.kind == "color"]
    options = [channel for channel in channels if channel.kind == "option"]
    segments = _SegmentBuilder()
    for channel in (*ranges, *colors):
        segments.add(channel.segments)
    return ConversionPlan(
        laneCount=slots.laneCount,
        universeCount=universe_count,
        rangeCount=len(ranges),
        colorCount=len(colors),
        optionCount=len(options),
        ranges=_range_inputs(ranges, slots),
        colors=_color_inputs(colors, slots),
        segments=segments.build(),
        options=_option_maps(options, slots),
        byteGroups=_byte_groups((*ranges, *colors, *options)),
    )


def color_row(channel: CompiledChannel) -> int:
    """The colour matrix row a colour channel reads, by its emitter role."""
    rows = SUBTRACTIVE_ROWS if channel.subtractive else ADDITIVE_ROWS
    return rows.get(channel.component or "", ZERO_ROW)


def _range_inputs(ranges: Sequence[CompiledChannel], slots: SlotTable) -> RangeInputs:
    curves: dict[DimmerCurve, list[int]] = {}
    for position, channel in enumerate(ranges):
        if channel.curve is not None:
            curves.setdefault(channel.curve, []).append(position)
    return RangeInputs(
        lanes=_ints([slots.slots[channel.slot].laneOffset for channel in ranges]),
        offsets=_floats([channel.offsetDeg for channel in ranges]),
        signs=_floats([channel.sign for channel in ranges]),
        dimmerGroups=tuple(
            DimmerGroup(curve=curve, positions=_ints(positions))
            for curve, positions in curves.items()
        ),
    )


def _color_inputs(colors: Sequence[CompiledChannel], slots: SlotTable) -> ColorInputs:
    columns: dict[int, int] = {}  # colour slot → column, in order of first use
    virtual: dict[DimmerCurve, dict[int, int]] = {}  # curve → {column: intensity lane}
    subtractive: dict[int, None] = {}  # columns, in order of first use
    for channel in colors:
        column = columns.setdefault(channel.slot, len(columns))
        if channel.intensitySlot is not None and channel.curve is not None:
            intensity_lane = slots.slots[channel.intensitySlot].laneOffset
            virtual.setdefault(channel.curve, {})[column] = intensity_lane
        if channel.subtractive:
            subtractive[column] = None
    rgb: list[list[int]] = [[], [], []]
    extras: dict[str, dict[int, int]] = {"w": {}, "a": {}, "uv": {}}  # extra → {column: lane}
    for slot_index, column in columns.items():
        slot = slots.slots[slot_index]
        for k in range(3):
            rgb[k].append(slot.laneOffset + k)
        for k, extra in enumerate(slot.extras):
            extras[extra][column] = slot.laneOffset + 3 + k

    def extra_inputs(extra: str) -> ExtraInputs:
        found = extras[extra]
        return ExtraInputs(columns=_ints(list(found)), lanes=_ints(list(found.values())))

    width = len(columns)
    return ColorInputs(
        rgbLanes=_ints(rgb).reshape(3, width),
        white=extra_inputs("w"),
        amber=extra_inputs("a"),
        uv=extra_inputs("uv"),
        subtractiveColumns=_ints(list(subtractive)),
        virtualGroups=tuple(
            VirtualGroup(curve=curve, columns=_ints(list(group)), lanes=_ints(list(group.values())))
            for curve, group in virtual.items()
        ),
        pick=_ints([color_row(channel) * width + columns[channel.slot] for channel in colors]),
    )


def _option_maps(options: Sequence[CompiledChannel], slots: SlotTable) -> OptionMaps:
    lanes: list[int] = []
    first: list[int] = []
    last: list[float] = []
    param_lanes: list[int] = []
    maps = _SegmentBuilder()
    for channel in options:
        own_lane = slots.slots[channel.slot].laneOffset
        lanes.append(own_lane)
        first.append(len(param_lanes))
        last.append(float(len(channel.options) - 1))
        for option in channel.options:
            if option.param is None:
                param_lanes.append(own_lane)  # finite, and multiplied by a DMX span of 0
                maps.add_constant(option.raw)
            else:
                param_slot, segment = option.param
                param_lanes.append(slots.slots[param_slot].laneOffset)
                maps.add((segment,))
    return OptionMaps(
        lanes=_ints(lanes),
        first=_ints(first),
        last=_floats(last),
        paramLanes=_ints(param_lanes),
        maps=maps.build(),
    )


def _byte_groups(channels: Sequence[CompiledChannel]) -> tuple[ByteGroup, ...]:
    by_bytes: dict[int, list[tuple[int, CompiledChannel]]] = {}
    for position, channel in enumerate(channels):
        by_bytes.setdefault(channel.bytes, []).append((position, channel))
    groups: list[ByteGroup] = []
    for nbytes, members in sorted(by_bytes.items()):
        targets: list[tuple[IntArray | None, IntArray]] = []
        for byte in range(nbytes):
            owned = [
                (j, channel.universe * UNIVERSE_SIZE + address)
                for j, (_, channel) in enumerate(members)
                if (address := channel.addresses[byte]) is not None
            ]
            subset = None if len(owned) == len(members) else _ints([j for j, _ in owned])
            targets.append((subset, _ints([address for _, address in owned])))
        groups.append(
            ByteGroup(
                bytes=nbytes,
                channels=_ints([position for position, _ in members]),
                targets=tuple(targets),
            )
        )
    return tuple(groups)


class _SegmentBuilder:
    """Collects uniform single-segment maps and padded multi-segment tables."""

    _PADDING: Final = (np.inf, np.inf, 0.0, 1.0, 0.0, 0.0)  # infinitely far; never chosen

    def __init__(self) -> None:
        self.single: list[tuple[float, float, float, float]] = []
        self.multi: list[tuple[int, tuple[Segment, ...]]] = []

    def add_constant(self, raw: int) -> None:
        """A map that always outputs ``raw``."""
        self.single.append((0.0, 1.0, float(raw), 0.0))

    def add(self, segments: tuple[Segment, ...]) -> None:
        if len(segments) > 1:
            self.multi.append((len(self.single), segments))
            self.add_constant(0)  # placeholder; the multi-segment kernel overwrites it
        else:
            self.single.append(_uniform(segments[0]))

    def build(self) -> SegmentMaps:
        single = np.array(self.single, dtype=np.float64).reshape(len(self.single), 4)
        width = max((len(segments) for _, segments in self.multi), default=0)
        table = np.array(
            [
                [(s.low, s.high, *_uniform(s)) for s in segments]
                + [self._PADDING] * (width - len(segments))
                for _, segments in self.multi
            ],
            dtype=np.float64,
        ).reshape(len(self.multi), width, 6)

        def column(array: NDArray[np.float64], k: int) -> FloatArray:
            return _frozen(np.ascontiguousarray(array[..., k]))

        return SegmentMaps(
            v0=column(single, 0),
            span=column(single, 1),
            d0=column(single, 2),
            dspan=column(single, 3),
            multiPositions=_ints([position for position, _ in self.multi]),
            multiLow=column(table, 0),
            multiHigh=column(table, 1),
            multiV0=column(table, 2),
            multiSpan=column(table, 3),
            multiD0=column(table, 4),
            multiDSpan=column(table, 5),
        )


def _uniform(segment: Segment) -> tuple[float, float, float, float]:
    """``(v0, span, d0, dspan)`` of a segment, zero-span folded to its centre."""
    if segment.v0 == segment.v1:
        return segment.v0, 1.0, float((segment.d0 + segment.d1) // 2), 0.0
    return (
        segment.v0,
        segment.v1 - segment.v0,
        float(segment.d0),
        float(segment.d1 - segment.d0),
    )


def _frozen[A: NDArray[Any]](array: A) -> A:
    """Make ``array`` read-only: the compiled show is shared between threads."""
    array.flags.writeable = False
    return array


def _ints(values: Sequence[int] | Sequence[Sequence[int]]) -> IntArray:
    return _frozen(np.array(values, dtype=np.intp))


def _floats(values: Sequence[float]) -> FloatArray:
    return _frozen(np.array(values, dtype=np.float64))
