"""What the safety stage reads (spec §12, stage 11; phase-7-plan §5.10).

The safety stage is the last thing that touches the logical frame before
conversion. Its data is compiled from the show into flat, read-only arrays,
rebuilt on every compile (it is cheap: O(fixtures with limits + park
entries)), so the engine only indexes:

* **Park** (§5.17): each ``park`` entry forces its slot's lanes to the
  entry's value, encoded the way the values file encodes it
  (:func:`~busk.compiler.lanes.encode_value`). Intensity lanes are kept
  apart, because blackout still darkens a parked intensity while it does not
  touch any other parked lane (decision 11).
* **Limits** (§5.6): the pan and tilt lanes of every element of a fixture
  with ``limits`` are clamped to ``limits.pan`` and ``limits.tilt`` (logical
  degrees, before orientation), and its intensity lanes to
  ``limits.intensityMax``.
* **The strobe cap** (decision 13, §5.11): with ``safety.strobeMaxHz`` set,
  every ``strobeRate`` lane is clamped to it. (Effects are capped where
  they run, :func:`busk.engine.effects.tempo`. A fixture that strobes no
  slower than the cap is a validation warning, not a second compile one.)

It also finds the output's **dark bytes** (decision 14, §5.13): every
byte intensity reaches and its value at intensity 0 (:func:`dark_bytes`),
which a stalled engine's last frame takes when the show does not hold it.

Compiling also reports two kinds of **warnings**:

* a park entry that cannot act: its target has no slot for the attribute,
  or no such option (§5.10 assumed validation rejects these; validation has
  no slot table, so the compiler reports them and skips the entry);
* one per **unpatched fixture** that a playback or a park entry drives
  (§18): ``fixtures[5]: 'MH 2' is not patched; playback 3 'Blue' drives
  it``. The first playback in show order is named, else the first park
  entry. The programmer is not part of the show, so its effects are not
  looked at.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from busk.compiler.channels import CompiledChannel
from busk.compiler.lanes import EncodeError, encode_value
from busk.compiler.playbacks import CompiledCueList
from busk.compiler.slots import SlotTable
from busk.convert.converter import Converter
from busk.convert.dmx import UNIVERSE_SIZE
from busk.convert.plan import ConversionPlan
from busk.model.common import CueListId, FixtureId, TargetRef
from busk.model.show import Show
from busk.model.validate import Issue


@dataclass(frozen=True, kw_only=True)
class CompiledSafety:
    """The safety stage's arrays; every one is read-only.

    ``parkIntensity`` and ``parkLanes`` are lanes of the logical frame, with
    their forced values in ``parkIntensityValues`` and ``parkValues``
    (discrete lanes hold an option index; a colour extra may be ``NaN``,
    which the converter derives). ``limitLanes`` are clamped to
    ``limitLow ..  limitHigh`` (``-inf`` below an ``intensityMax``).
    ``strobeLanes`` are clamped to ``strobeMaxHz``; without a cap there is
    none, and no strobe lanes either.
    """

    parkIntensity: NDArray[np.intp]
    parkIntensityValues: NDArray[np.float64]
    parkLanes: NDArray[np.intp]
    parkValues: NDArray[np.float64]
    limitLanes: NDArray[np.intp]
    limitLow: NDArray[np.float64]
    limitHigh: NDArray[np.float64]
    strobeLanes: NDArray[np.intp]
    strobeMaxHz: float | None


def compile_safety(show: Show, slots: SlotTable) -> tuple[CompiledSafety, list[Issue]]:
    """Compile ``show``'s park entries, fixture limits and strobe cap against
    ``slots``; return the arrays and the park entries' warnings."""
    warnings: list[Issue] = []
    park_intensity: list[int] = []  # intensity lanes, which blackout still darkens
    park_intensity_values: list[float] = []
    park_lanes: list[int] = []  # every other parked lane
    park_values: list[float] = []
    names = {fixture["id"]: fixture["name"] for fixture in show["fixtures"]} if show["park"] else {}
    for k, entry in enumerate(show["park"]):
        target, attribute = entry["slot"]["target"], entry["slot"]["attribute"]
        slot = slots.find(target, attribute)
        name = names.get(target["fixtureId"], target["fixtureId"])
        if slot is None:
            warnings.append(
                Issue(
                    "warning",
                    f"park[{k}].slot.attribute",
                    f"{name!r} element {target['element']} has no {attribute!r}; "
                    "this entry does nothing",
                )
            )
            continue
        try:
            values = encode_value(slot, entry["value"])
        except EncodeError as exc:
            warnings.append(
                Issue("warning", f"park[{k}].value.slot", f"{exc}; this entry does nothing")
            )
            continue
        lanes = range(slot.laneOffset, slot.laneOffset + slot.laneCount)
        if slot.attribute.merge == "HTP":
            park_intensity.extend(lanes)
            park_intensity_values.extend(values)
        else:
            park_lanes.extend(lanes)
            park_values.extend(values)

    limit_lanes: list[int] = []
    low: list[float] = []
    high: list[float] = []
    modes = _element_counts(show)
    for fixture in show["fixtures"]:
        limits = fixture.get("limits")
        if not limits:
            continue
        clamps: list[tuple[str, float, float]] = []
        if "pan" in limits:
            clamps.append(("pan", *limits["pan"]))
        if "tilt" in limits:
            clamps.append(("tilt", *limits["tilt"]))
        if "intensityMax" in limits:
            clamps.append(("intensity", -math.inf, limits["intensityMax"]))
        for element in range(modes.get(fixture["id"], 0)):
            target = TargetRef(fixtureId=FixtureId(fixture["id"]), element=element)
            for attribute, lo, hi in clamps:
                slot = slots.find(target, attribute)
                if slot is not None:
                    limit_lanes.append(slot.laneOffset)
                    low.append(lo)
                    high.append(hi)

    cap = show.get("safety", {}).get("strobeMaxHz")
    strobe = (
        [] if cap is None else [s.laneOffset for s in slots.slots if s.attribute.id == "strobeRate"]
    )

    safety = CompiledSafety(
        parkIntensity=_lanes(park_intensity),
        parkIntensityValues=_values(park_intensity_values),
        parkLanes=_lanes(park_lanes),
        parkValues=_values(park_values),
        limitLanes=_lanes(limit_lanes),
        limitLow=_values(low),
        limitHigh=_values(high),
        strobeLanes=_lanes(strobe),
        strobeMaxHz=cap,
    )
    return safety, warnings


def unpatched_warnings(show: Show, cue_lists: Mapping[CueListId, CompiledCueList]) -> list[Issue]:
    """One warning per unpatched fixture that a playback's cues (their values
    or effects) or a park entry drive, in fixture order (§18)."""
    unpatched = {fixture["id"] for fixture in show["fixtures"] if fixture["patch"] is None}
    if not unpatched:
        return []
    drivers: dict[str, str] = {}  # fixture id → what drives it
    for playback in show["playbacks"]:
        if len(drivers) == len(unpatched):
            break
        cue_list = cue_lists.get(playback["cueListId"])
        if cue_list is None:
            continue
        who = f"playback {playback['number']} {playback['name']!r}"
        for cue in cue_list.cues:
            for target in cue.targets:
                if target["fixtureId"] in unpatched:
                    drivers.setdefault(target["fixtureId"], who)
    for k, entry in enumerate(show["park"]):
        fixture_id = entry["slot"]["target"]["fixtureId"]
        if fixture_id in unpatched:
            drivers.setdefault(fixture_id, f"park[{k}]")
    return [
        Issue(
            "warning",
            f"fixtures[{f}]",
            f"{fixture['name']!r} is not patched; {drivers[fixture['id']]} drives it",
        )
        for f, fixture in enumerate(show["fixtures"])
        if fixture["id"] in drivers
    ]


def dark_bytes(
    slots: SlotTable,
    channels: Sequence[CompiledChannel],
    plan: ConversionPlan,
    base_images: NDArray[np.uint8],
) -> tuple[NDArray[np.intp], NDArray[np.uint8]]:
    """The bytes intensity reaches, as flat positions (``row × 512 +
    address``) in the universe buffers, and their values at intensity 0.

    They are every owned byte of the channels driven by an intensity slot
    (coarse, fine and ultra) and of the colour channels of virtual-intensity
    fixtures. Their values come from converting the default logical frame
    with every intensity lane at 0, once per rig, so curves, ``invert`` and
    subtractive emitters give what the converter would send.
    """
    positions = sorted(
        {
            channel.universe * UNIVERSE_SIZE + address
            for channel in channels
            if channel.intensitySlot is not None
            or slots.slots[channel.slot].attribute.id == "intensity"
            for address in channel.addresses
            if address is not None
        }
    )
    frame = slots.defaultFrame.copy()
    frame[slots.intensityLanes] = 0.0
    images = base_images.copy()
    Converter(plan).convert(frame, images)
    flat = np.array(positions, dtype=np.intp)
    values = images.reshape(-1)[flat].copy()
    return _lanes(positions), _readonly(values)


def _readonly[T: np.generic](array: NDArray[T]) -> NDArray[T]:
    array.flags.writeable = False
    return array


def _element_counts(show: Show) -> dict[str, int]:
    """The element count of every fixture with limits whose mode resolves."""
    limited = [fixture for fixture in show["fixtures"] if fixture.get("limits")]
    if not limited:
        return {}
    profiles = {profile["id"]: profile for profile in show["profiles"]}
    counts: dict[str, int] = {}
    for fixture in limited:
        profile = profiles.get(fixture["profileId"])
        modes = profile["modes"] if profile is not None else []
        mode = next((m for m in modes if m["id"] == fixture["modeId"]), None)
        if mode is not None:
            counts[fixture["id"]] = len(mode["elements"])
    return counts


def _lanes(lanes: list[int]) -> NDArray[np.intp]:
    array = np.array(lanes, dtype=np.intp)
    array.flags.writeable = False
    return array


def _values(values: list[float]) -> NDArray[np.float64]:
    array = np.array(values, dtype=np.float64)
    array.flags.writeable = False
    return array
