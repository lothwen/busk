"""Presets (palettes): reusable, named bundles of attribute values (spec §5.8).

Each value is *scoped* so one preset works on a heterogeneous rig. When a
target asks a preset for an attribute, the lookup order is ``target`` scope →
``profile`` scope → ``global`` scope → not defined (the entry then contributes
nothing to that target). Presets contain no timing and cannot reference other
presets.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from pydantic import Field, with_config

from busk.model.attributes import AttributeValue
from busk.model.common import STRICT, AttributeId, EntityBase, PresetId, ProfileId, TargetRef

type PresetPool = Literal["intensity", "position", "color", "beam", "focus", "all"]


@with_config(STRICT)
class Preset(EntityBase[PresetId]):
    """A preset; ``number`` is unique within its ``pool``."""

    number: int
    pool: PresetPool
    values: list[PresetValue]


@with_config(STRICT)
class GlobalScope(TypedDict):
    """Applies to any fixture that has the attribute."""

    kind: Literal["global"]


@with_config(STRICT)
class ProfileScope(TypedDict):
    """Applies to all fixtures of one model."""

    kind: Literal["profile"]
    profileId: ProfileId


@with_config(STRICT)
class TargetScope(TypedDict):
    """Applies to one specific fixture element."""

    kind: Literal["target"]
    target: TargetRef


type PresetScope = Annotated[GlobalScope | ProfileScope | TargetScope, Field(discriminator="kind")]


@with_config(STRICT)
class PresetValue(TypedDict):
    """One scoped attribute value inside a preset."""

    scope: PresetScope
    attribute: AttributeId
    value: AttributeValue
