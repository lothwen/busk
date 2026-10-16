"""Output configuration: routes from universes to transports (spec §5.16).

One universe may have several routes (e.g. Art-Net to a node *and* a USB
backup). Every route is validated. Enabled sACN routes are sent since
Phase 1.5 (:mod:`busk.output.sacn`), Art-Net and DMX-USB routes since Phase 6
(:mod:`busk.output.artnet`, :mod:`busk.output.dmxusb`); ``busk run`` lists
``enttecOpen`` routes as ignored.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from pydantic import Field, with_config

from busk.model.common import STRICT, UniverseId


@with_config(STRICT)
class DmxUsbDevice(TypedDict):
    """A USB DMX interface."""

    driver: Literal["enttecPro", "enttecOpen", "dmxking"] | str
    port: str


@with_config(STRICT)
class DmxUsbRoute(TypedDict):
    """Send a universe to a USB DMX interface (§14.2)."""

    id: str
    universeId: UniverseId
    enabled: bool
    protocol: Literal["dmxUsb"]
    device: DmxUsbDevice
    refreshHz: float  # ≤ 44 for full 512-slot frames


@with_config(STRICT)
class ArtNetPortAddress(TypedDict):
    """The 15-bit Art-Net Port-Address: Net (7 bits), Sub-Net (4), Universe (4)."""

    net: Annotated[int, Field(ge=0, le=127)]
    subNet: Annotated[int, Field(ge=0, le=15)]
    universe: Annotated[int, Field(ge=0, le=15)]


@with_config(STRICT)
class BroadcastDestination(TypedDict):
    """Broadcast on a network interface."""

    kind: Literal["broadcast"]
    iface: str


@with_config(STRICT)
class MulticastDestination(TypedDict):
    """Multicast on a network interface (sACN: 239.255.hi.lo)."""

    kind: Literal["multicast"]
    iface: str


@with_config(STRICT)
class UnicastDestination(TypedDict):
    """Send to one host."""

    kind: Literal["unicast"]
    host: str


@with_config(STRICT)
class ArtNetRoute(TypedDict):
    """Send a universe as ArtDmx packets (§14.3)."""

    id: str
    universeId: UniverseId
    enabled: bool
    protocol: Literal["artnet"]
    portAddress: ArtNetPortAddress
    destination: Annotated[BroadcastDestination | UnicastDestination, Field(discriminator="kind")]


@with_config(STRICT)
class SacnRoute(TypedDict):
    """Send a universe as sACN / ANSI E1.31 (§14.4)."""

    id: str
    universeId: UniverseId
    enabled: bool
    protocol: Literal["sacn"]
    universe: Annotated[int, Field(ge=1, le=63999)]
    priority: Annotated[int, Field(ge=0, le=200)]  # default 100
    destination: Annotated[MulticastDestination | UnicastDestination, Field(discriminator="kind")]


type OutputRoute = Annotated[DmxUsbRoute | ArtNetRoute | SacnRoute, Field(discriminator="protocol")]


@with_config(STRICT)
class OutputSettings(TypedDict):
    """Engine rate and transport settings."""

    engineHz: Annotated[float, Field(gt=0)]  # engine tick rate (§11)
    sacnSourceName: str  # at most 63 UTF-8 bytes
    sacnCid: str  # UUID, persistent per installation
    holdLastFrameOnEngineStall: bool  # §18
    routes: list[OutputRoute]
