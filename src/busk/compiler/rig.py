"""The rig: each fixture resolved against its profile and mode (spec §5.5–§5.6).

Every compile step walks the same structure (fixture → mode → element →
channels), so the lookups are done once here. The element analysis below
(colour system, extra emitters, virtual dimmer) is shared by the slot
compiler, which decides what lanes an element has, and the channel compiler,
which decides how each channel is driven.

All functions assume a show that passed validation without errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from busk.model.fixture import Fixture
from busk.model.profile import (
    COLOR_EXTRAS,
    ChannelDefinition,
    DimmerCurve,
    FixtureMode,
    FixtureProfile,
    emitter_is_subtractive,
)
from busk.model.show import Show

type ColorExtra = Literal["w", "a", "uv"]
type ColorSystem = Literal["additive", "subtractive"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ElementInfo:
    """How an element mixes colour and how it is dimmed (§13.2–§13.3)."""

    colorSystem: ColorSystem | None  # None: the element has no colour channels
    extras: tuple[ColorExtra, ...]  # colour lanes after r, g, b, in lane order
    hasDimmer: bool  # the element has its own intensity channel
    virtualIntensity: bool  # intensity scales the element's emitters


@dataclass(frozen=True, slots=True, kw_only=True)
class RigFixture:
    """A fixture with its profile and mode looked up and its elements analysed.

    ``channels[e]`` are element ``e``'s channels in mode order and
    ``elements[e]`` its :class:`ElementInfo`; both are computed once, because
    every compile step asks for them.
    """

    index: int  # position in show["fixtures"]; the later fixture wins overlaps
    fixture: Fixture
    profile: FixtureProfile
    mode: FixtureMode
    channels: tuple[tuple[ChannelDefinition, ...], ...]
    elements: tuple[ElementInfo, ...]

    @property
    def dimmer_curve(self) -> DimmerCurve:
        """The mode's intensity curve; ``linear`` when the mode names none."""
        curve = self.mode.get("dimmerCurve", "linear")
        return tuple(curve) if isinstance(curve, list) else curve


def resolve_rig(show: Show) -> tuple[RigFixture, ...]:
    """Look up every fixture's profile and mode, in show order, and analyse
    the elements of each mode once."""
    profiles = {profile["id"]: profile for profile in show["profiles"]}
    analysed: dict[
        tuple[str, str], tuple[tuple[tuple[ChannelDefinition, ...], ...], tuple[ElementInfo, ...]]
    ] = {}
    rig: list[RigFixture] = []
    for index, fixture in enumerate(show["fixtures"]):
        profile = profiles[fixture["profileId"]]
        mode = next(mode for mode in profile["modes"] if mode["id"] == fixture["modeId"])
        key = (profile["id"], mode["id"])
        if key not in analysed:
            channels = tuple(
                tuple(channel for channel in mode["channels"] if channel["element"] == element)
                for element in range(len(mode["elements"]))
            )
            analysed[key] = (
                channels,
                tuple(_element_info(profile, mode, element) for element in channels),
            )
        channels, elements = analysed[key]
        rig.append(
            RigFixture(
                index=index,
                fixture=fixture,
                profile=profile,
                mode=mode,
                channels=channels,
                elements=elements,
            )
        )
    return tuple(rig)


def _element_info(
    profile: FixtureProfile, mode: FixtureMode, channels: tuple[ChannelDefinition, ...]
) -> ElementInfo:
    """Analyse one element, given its channels.

    * The colour system is subtractive when the element's colour channels are
      CMY flags and additive otherwise; validation forbids mixing the two.
    * An additive element's extras are the ``w``/``a``/``uv`` lanes whose
      emitter (white, amber, UV) it has a channel for.
    * The element is dimmed virtually when the mode's strategy is
      ``virtual`` and the element has additive colour but no intensity
      channel of its own. The rule is per element, so a bar with a master
      dimmer and RGB cells works under either strategy.
    """
    components = [channel["component"] for channel in channels if channel["attribute"] == "color"]
    has_dimmer = any(channel["attribute"] == "intensity" for channel in channels)
    if not components:
        return ElementInfo(
            colorSystem=None, extras=(), hasDimmer=has_dimmer, virtualIntensity=False
        )
    if any(emitter_is_subtractive(profile, component) for component in components):
        return ElementInfo(
            colorSystem="subtractive", extras=(), hasDimmer=has_dimmer, virtualIntensity=False
        )
    return ElementInfo(
        colorSystem="additive",
        extras=tuple(lane for lane, emitter in COLOR_EXTRAS if emitter in components),
        hasDimmer=has_dimmer,
        virtualIntensity=mode["intensityStrategy"] == "virtual" and not has_dimmer,
    )


def byte_offsets(channel: ChannelDefinition) -> list[int]:
    """Footprint offsets of a channel's bytes, coarse byte first.

    Without ``fineOffsets``, the fine (and ultra) bytes come right after the
    coarse byte: ``offset + 1``, ``offset + 2``.
    """
    offset = channel["offset"]
    fine = channel.get("fineOffsets")
    if fine is None:
        fine = [offset + k for k in range(1, channel["bytes"])]
    return [offset, *fine]
