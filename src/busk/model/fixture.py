"""Patch: universes and fixtures (spec §5.6).

Patch rules (checked by ``busk.model.validate``): the footprint must fit in
the universe (``address + footprint − 1 ≤ 512``); overlapping footprints are
only a *warning*, because double-patching is legitimate for some setups; and a
``profileRevision`` that differs from the embedded profile's ``revision`` is
reported, never silently applied (§17).
"""

from __future__ import annotations

from typing import NotRequired, TypedDict

from pydantic import with_config

from busk.model.common import (
    STRICT,
    DmxAddress,
    EntityBase,
    FixtureId,
    ModeId,
    PositiveInt,
    ProfileId,
    Unit,
    UniverseId,
)


@with_config(STRICT)
class Universe(EntityBase[UniverseId]):
    """A logical DMX universe of 512 channels."""

    number: PositiveInt  # logical universe number, 1-based


@with_config(STRICT)
class Orientation(TypedDict):
    """How a fixture is hung, applied to pan/tilt before conversion (§13.1)."""

    invertPan: bool
    invertTilt: bool
    swapPanTilt: bool
    panOffset: float  # degrees added before conversion
    tiltOffset: float


@with_config(STRICT)
class FixtureLimits(TypedDict, total=False):
    """Safety limits enforced at the safety stage (§12)."""

    pan: tuple[float, float]  # degrees
    tilt: tuple[float, float]
    intensityMax: Unit


@with_config(STRICT)
class Location(TypedDict):
    """Stage position in metres (x right, y downstage, z up) and rotation."""

    x: float
    y: float
    z: float
    rx: float
    ry: float
    rz: float


@with_config(STRICT)
class Fixture(EntityBase[FixtureId]):
    """A patched instance of a fixture profile mode."""

    number: int  # user-facing fixture number (e.g. 101)
    profileId: ProfileId
    profileRevision: str  # detects library drift
    modeId: ModeId
    patch: PatchAddress | None  # None = unpatched (still programmable)
    elementPatch: NotRequired[dict[int, PatchAddress]]  # per-element split patch (pixel bars)
    orientation: Orientation
    limits: NotRequired[FixtureLimits]
    location: NotRequired[Location]


@with_config(STRICT)
class PatchAddress(TypedDict):
    """Where a fixture (or element) starts: a universe and a 1-based channel."""

    universeId: UniverseId
    address: DmxAddress  # 1..512, start channel
