"""What reading the output back needs of the rig (GAP-01 of ``docs/dev/tui/engine-gaps.md``).

The engine's output readout (:mod:`busk.engine.readout`) turns a logical
frame into one :class:`~busk.engine.snapshot.FixtureOutput` per fixture
element. The lookups it needs depend only on the rig, so they are made here,
once per rig, as arrays with one entry per element, ``-1`` standing for "no
such lane":

* the element's fixture number, and its element number counted from 1, as
  the console counts them (``301.3``);
* the lanes of its ``intensity``, ``pan``, ``tilt`` and ``zoom`` slots, and of
  its ``color`` slot's ``r, g, b`` and ``w``;
* ``master``, the lane that dims it besides its own: element 0's intensity,
  for an element without a dimmer channel of its own when element 0 has one.
  That is a bar's master dimmer (the OFL import puts the channels outside a
  matrix on element 0, the first pixel);
* its ``colorWheel`` lane, and the colour of each of that slot's options as
  the profile's wheels give it (``NaN``: the wheel slot has no colour);
* the runs of lanes each family of each element takes, so the readout tells
  what drives a family with one ``reduceat``.

Elements are listed by fixture number, then element: the order of the
readout. Unpatched fixtures are listed too: they are programmable.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

from busk.compiler.rig import RigFixture
from busk.compiler.slots import FAMILY_CODES, Slot, SlotTable
from busk.model.common import FixtureId, TargetRef
from busk.model.profile import ChannelDefinition, FixtureProfile, option_capabilities

type IntArray = NDArray[np.intp]


@dataclass(frozen=True, kw_only=True, eq=False)
class ReadoutLayout:
    """The per-element lookups of the readout (see the module docs). Every
    array is read-only; ``E`` is the number of elements of the rig."""

    numbers: tuple[int, ...]  # per element: its fixture's number
    elements: tuple[int, ...]  # per element: its index + 1
    intensity: IntArray  # (E,) its intensity lane
    master: IntArray  # (E,) element 0's intensity lane, when it dims this element too
    rgb: IntArray  # (E, 3) its colour slot's r, g, b lanes
    white: IntArray  # (E,) its colour slot's w lane
    wheel: IntArray  # (E,) its colorWheel lane
    wheelStart: IntArray  # (E,) its first row in wheelColors
    wheelCount: IntArray  # (E,) its colorWheel options; 0: no wheel
    wheelColors: NDArray[np.float64]  # (rows, 3) each option's colour, NaN: none
    colored: NDArray[np.bool_]  # (E,) it has a color or a colorWheel slot
    pan: IntArray  # (E,)
    tilt: IntArray  # (E,)
    zoom: IntArray  # (E,)
    runStart: IntArray  # (R,) the first lane of each run, ascending: the runs cover every lane
    runElement: IntArray  # (R,) the element (its position here) each run belongs to
    runFamily: IntArray  # (R,) the family code of each run (FAMILY_CODES)


def _readonly[T: np.generic](array: NDArray[T]) -> NDArray[T]:
    array.flags.writeable = False
    return array


def _lanes(values: Sequence[int]) -> IntArray:
    return _readonly(np.array(values, dtype=np.intp).reshape(len(values)))


EMPTY_READOUT: Final = ReadoutLayout(
    numbers=(),
    elements=(),
    intensity=_lanes([]),
    master=_lanes([]),
    rgb=_readonly(np.zeros((0, 3), dtype=np.intp)),
    white=_lanes([]),
    wheel=_lanes([]),
    wheelStart=_lanes([]),
    wheelCount=_lanes([]),
    wheelColors=_readonly(np.zeros((0, 3))),
    colored=_readonly(np.zeros(0, dtype=np.bool_)),
    pan=_lanes([]),
    tilt=_lanes([]),
    zoom=_lanes([]),
    runStart=_lanes([]),
    runElement=_lanes([]),
    runFamily=_lanes([]),
)
"""The readout of a rig without fixtures; also what the engine process's view
of a compiled show carries (:func:`busk.process.wire.engine_view`)."""


def build_readout(rig: Sequence[RigFixture], slots: SlotTable) -> ReadoutLayout:
    """The readout lookups of ``rig``, whose slots are ``slots``."""
    order = sorted(
        ((fixture, element) for fixture in rig for element in range(len(fixture.elements))),
        key=lambda pair: (pair[0].fixture["number"], pair[1]),
    )
    position = {(fixture.fixture["id"], element): k for k, (fixture, element) in enumerate(order)}

    def lane(target: TargetRef, attribute: str, offset: int = 0) -> int:
        found = slots.find(target, attribute)
        return -1 if found is None else found.laneOffset + offset

    intensity, master, white, wheel, pan, tilt, zoom = ([] for _ in range(7))
    rgb: list[tuple[int, int, int]] = []
    starts: list[int] = []
    counts: list[int] = []
    colors: list[tuple[float, float, float]] = []
    colored: list[bool] = []
    for fixture, element in order:
        target = TargetRef(fixtureId=FixtureId(fixture.fixture["id"]), element=element)
        info, main = fixture.elements[element], fixture.elements[0]
        intensity.append(lane(target, "intensity"))
        dims = element != 0 and not info.hasDimmer and main.hasDimmer
        main_target = TargetRef(fixtureId=target["fixtureId"], element=0)
        master.append(lane(main_target, "intensity") if dims else -1)
        color = slots.find(target, "color")
        if color is None:
            rgb.append((-1, -1, -1))
            white.append(-1)
        else:
            rgb.append((color.laneOffset, color.laneOffset + 1, color.laneOffset + 2))
            extras = color.extras
            white.append(color.laneOffset + 3 + extras.index("w") if "w" in extras else -1)
        found = slots.find(target, "colorWheel")
        starts.append(len(colors))
        if found is None:
            wheel.append(-1)
            counts.append(0)
        else:
            wheel.append(found.laneOffset)
            options = _wheel_colors(fixture.profile, fixture.channels[element], found)
            counts.append(len(options))
            colors.extend(options)
        colored.append(color is not None or found is not None)
        pan.append(lane(target, "pan"))
        tilt.append(lane(target, "tilt"))
        zoom.append(lane(target, "zoom"))
    run_start: list[int] = []
    run_element: list[int] = []
    run_family: list[int] = []
    for slot in slots.slots:
        at = position[(slot.target["fixtureId"], slot.target["element"])]
        family = FAMILY_CODES[slot.attribute.family]
        if not run_start or run_element[-1] != at or run_family[-1] != family:
            run_start.append(slot.laneOffset)
            run_element.append(at)
            run_family.append(family)
    return ReadoutLayout(
        numbers=tuple(fixture.fixture["number"] for fixture, _ in order),
        elements=tuple(element + 1 for _, element in order),
        intensity=_lanes(intensity),
        master=_lanes(master),
        rgb=_readonly(np.array(rgb, dtype=np.intp).reshape(len(rgb), 3)),
        white=_lanes(white),
        wheel=_lanes(wheel),
        wheelStart=_lanes(starts),
        wheelCount=_lanes(counts),
        wheelColors=_readonly(np.array(colors, dtype=np.float64).reshape(len(colors), 3)),
        colored=_readonly(np.array(colored, dtype=np.bool_)),
        pan=_lanes(pan),
        tilt=_lanes(tilt),
        zoom=_lanes(zoom),
        runStart=_lanes(run_start),
        runElement=_lanes(run_element),
        runFamily=_lanes(run_family),
    )


def _wheel_colors(
    profile: FixtureProfile, channels: Sequence[ChannelDefinition], slot: Slot
) -> list[tuple[float, float, float]]:
    """The colour of each of ``slot``'s options (a colorWheel slot), in its
    order: the wheel slot's ``color``, looked up in the wheel its capability
    names, else in the profile's colour wheels; ``NaN`` where it has none."""
    channel = next(c for c in channels if c["attribute"] == "colorWheel")
    named: dict[str, str | None] = {
        option: capability.get("wheel") if capability["kind"] == "slot" else None
        for option, capability in option_capabilities(channel)
    }
    colors: list[tuple[float, float, float]] = []
    for option in slot.options:
        wheel_id = named[option]
        found = next(
            (
                wheel_slot["color"]
                for wheel in profile["wheels"]
                if wheel["id"] == wheel_id or (wheel_id is None and wheel["kind"] == "color")
                for wheel_slot in wheel["slots"]
                if wheel_slot["id"] == option and "color" in wheel_slot
            ),
            None,
        )
        colors.append(
            (math.nan, math.nan, math.nan)
            if found is None
            else (float(found["r"]), float(found["g"]), float(found["b"]))
        )
    return colors
