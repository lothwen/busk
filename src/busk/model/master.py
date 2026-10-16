"""Masters (spec §5.13).

Master *levels* are runtime state. The show may store a last level for
convenience on load: §5.13 calls it ``initialLevel`` (optional) in prose but
leaves it out of the type definitions, so it is added here to every master
kind. Without it, strict validation would reject the field the spec allows.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal, NotRequired

from pydantic import Field, with_config

from busk.model.common import STRICT, EntityBase, GroupId, MasterId, Unit

MAX_BPM: Final = 999.0
"""The fastest tempo a speed master takes, by validation, ``SET_BPM`` or taps."""


@with_config(STRICT)
class GrandMaster(EntityBase[MasterId]):
    """Scales the intensity of everything."""

    kind: Literal["grand"]
    initialLevel: NotRequired[Unit]


@with_config(STRICT)
class GroupMaster(EntityBase[MasterId]):
    """Scales the intensity of a group's members."""

    kind: Literal["group"]
    groupId: GroupId
    initialLevel: NotRequired[Unit]


@with_config(STRICT)
class SpeedMaster(EntityBase[MasterId]):
    """A tempo source for BPM-synced chases and effects."""

    kind: Literal["speed"]
    defaultBpm: float
    tap: bool
    multiplierSteps: list[float]  # e.g. [0.25, 0.5, 1, 2, 4]
    initialLevel: NotRequired[Unit]


@with_config(STRICT)
class SizeMaster(EntityBase[MasterId]):
    """Scales the size of effects that reference it."""

    kind: Literal["size"]
    initialLevel: NotRequired[Unit]


@with_config(STRICT)
class FadeTimeMaster(EntityBase[MasterId]):
    """A global fade-time override."""

    kind: Literal["fadeTime"]
    initialLevel: NotRequired[Unit]


type Master = Annotated[
    GrandMaster | GroupMaster | SpeedMaster | SizeMaster | FadeTimeMaster,
    Field(discriminator="kind"),
]
