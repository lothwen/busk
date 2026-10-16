"""The show root (spec §5.17).

A show file is one :class:`Show` document. ``schemaVersion`` is an integer;
every structural change of the schema ships with a migration (§17), and the
attribute registry is part of the schema.

Phase 7 adds the optional ``safety`` object (phase-7-plan decision 13). A
show without it is unchanged, so ``schemaVersion`` stays 1.
"""

from __future__ import annotations

from typing import Annotated, Final, NotRequired, TypedDict

from pydantic import Field, with_config

from busk.model.attributes import AttributeValue
from busk.model.common import STRICT, AttributeId, TargetRef
from busk.model.cue import CueList
from busk.model.effect import EffectTemplate
from busk.model.fixture import Fixture, Universe
from busk.model.group import Group
from busk.model.master import Master
from busk.model.output import OutputSettings
from busk.model.playback import Playback, PlaybackPage
from busk.model.preset import Preset
from busk.model.profile import FixtureProfile
from busk.model.surface import Binding, ControlSurface

SCHEMA_VERSION: Final = 1
"""The show schema version this build reads and writes."""


@with_config(STRICT)
class ShowMeta(TypedDict):
    """Descriptive metadata; timestamps are ISO 8601 strings."""

    id: str
    title: str
    created: str
    modified: str
    app: str


@with_config(STRICT)
class ParkSlot(TypedDict):
    """A ``(target, attribute)`` pair to park."""

    target: TargetRef
    attribute: AttributeId


@with_config(STRICT)
class ParkEntry(TypedDict):
    """A value forced at output regardless of everything else (§12)."""

    slot: ParkSlot
    value: AttributeValue


@with_config(STRICT)
class SafetySettings(TypedDict):
    """Show-wide settings of the safety stage (§12, Phase 7).

    ``strobeMaxHz`` caps every ``strobeRate`` lane and the flash rate of every
    effect with an intensity layer (phase-7-plan decision 13). Without it
    nothing is capped, so existing shows keep their strobes.
    """

    strobeMaxHz: NotRequired[Annotated[float, Field(gt=0)]]


@with_config(STRICT)
class Show(TypedDict):
    """A complete show document."""

    schemaVersion: int
    meta: ShowMeta
    profiles: list[FixtureProfile]  # embedded copies of the used profiles
    universes: list[Universe]
    fixtures: list[Fixture]
    groups: list[Group]
    presets: list[Preset]
    effects: list[EffectTemplate]
    cueLists: list[CueList]
    playbacks: list[Playback]
    pages: list[PlaybackPage]
    masters: list[Master]
    surfaces: list[ControlSurface]
    bindings: list[Binding]
    output: OutputSettings
    park: list[ParkEntry]
    safety: NotRequired[SafetySettings]  # Phase 7
