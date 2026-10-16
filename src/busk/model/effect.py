"""Effects: reusable templates and their instances (spec §5.10).

A **template** is the shape (e.g. circle = pan cos + tilt sin); an
**instance** says where it is applied, how fast, how big and how it is spread
across the ordered targets.

An ``absolute`` layer *is* the value and takes part in normal merging; an
``add`` layer offsets whatever the slot resolves to and a ``multiply`` layer
scales it (§7.5).
"""

from __future__ import annotations

from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import Discriminator, Field, Tag, with_config

from busk.model.attributes import AttributeValue, ColorValue
from busk.model.common import (
    STRICT,
    AttributeId,
    EffectId,
    EntityBase,
    MasterId,
    PositiveInt,
    PresetId,
    Seconds,
    Unit,
)
from busk.model.entry import TargetSpec

# ----------------------------------------------------------------- templates


@with_config(STRICT)
class EffectTemplate(EntityBase[EffectId]):
    """A named effect shape made of one or more layers."""

    layers: list[EffectLayer]


@with_config(STRICT)
class ScalarLayer(TypedDict):
    """A waveform driving one scalar attribute."""

    attribute: AttributeId
    waveform: Waveform
    phaseOffset: float  # degrees, within the template (tilt +90° for circles)
    mode: Literal["absolute", "add", "multiply"]


@with_config(STRICT)
class PresetRef(TypedDict):
    """A colour taken from a preset, inside a colour palette."""

    presetId: PresetId


def _palette_entry_kind(entry: object) -> str | None:
    """Pydantic discriminator for :data:`PaletteEntry` (objects carry no tag)."""
    if isinstance(entry, dict):
        return "preset" if "presetId" in entry else "color"
    return None


type PaletteEntry = Annotated[
    Annotated[ColorValue, Tag("color")] | Annotated[PresetRef, Tag("preset")],
    Discriminator(
        _palette_entry_kind,
        custom_error_type="palette_entry",
        custom_error_message="Input should be a colour {r, g, b} or a preset reference {presetId}",
    ),
]


@with_config(STRICT)
class ColorLayer(TypedDict):
    """A colour cycle through a palette."""

    attribute: Literal["color"]
    palette: list[PaletteEntry]
    blend: Literal["fade", "snap"]
    mode: Literal["absolute"]


def _layer_kind(layer: object) -> str | None:
    """Pydantic discriminator for :data:`EffectLayer`: scalar layers have a
    ``waveform``, colour layers a ``palette``."""
    if isinstance(layer, dict):
        if "waveform" in layer:
            return "scalar"
        if "palette" in layer:
            return "color"
    return None


type EffectLayer = Annotated[
    Annotated[ScalarLayer, Tag("scalar")] | Annotated[ColorLayer, Tag("color")],
    Discriminator(
        _layer_kind,
        custom_error_type="effect_layer",
        custom_error_message=(
            "Input should be a scalar layer (with a waveform) or a colour layer (with a palette)"
        ),
    ),
]

# ----------------------------------------------------------------- waveforms
# Normalised: phase p ∈ [0, 1) → value w ∈ [0, 1] (§10.3). The spec uses the
# functional TypedDict syntax; class syntax lets each type carry the strict
# config decorator. Field names and types are unchanged.


@with_config(STRICT)
class SineWave(TypedDict):
    """``0.5 − 0.5·cos(2πp)``: starts at 0, smooth."""

    kind: Literal["sine"]


@with_config(STRICT)
class TriangleWave(TypedDict):
    """Linear up to 1 at p = 0.5, then down."""

    kind: Literal["triangle"]


@with_config(STRICT)
class SquareWave(TypedDict):
    """1 while p < duty, else 0."""

    kind: Literal["square"]
    duty: Unit


@with_config(STRICT)
class SawUpWave(TypedDict):
    """``w = p``."""

    kind: Literal["sawUp"]


@with_config(STRICT)
class SawDownWave(TypedDict):
    """``w = 1 − p``."""

    kind: Literal["sawDown"]


@with_config(STRICT)
class PulseWave(TypedDict):
    """Attack ramp → hold for ``width`` → decay ramp → 0."""

    kind: Literal["pulse"]
    width: float
    attack: float
    decay: float


@with_config(STRICT)
class StepWave(TypedDict):
    """Levels held for equal time each."""

    kind: Literal["step"]
    steps: list[Unit]


@with_config(STRICT)
class RandomWave(TypedDict):
    """A value per cycle from a seeded PRNG (per member); ``smooth`` interpolates."""

    kind: Literal["random"]
    smooth: bool
    seed: int


@with_config(STRICT)
class CurveWave(TypedDict):
    """Piecewise curve through ``(x, y)`` points in ``0..1``."""

    kind: Literal["curve"]
    points: list[tuple[Unit, Unit]]


type Waveform = Annotated[
    SineWave | TriangleWave | SquareWave | SawUpWave | SawDownWave
    | PulseWave | StepWave | RandomWave | CurveWave,
    Field(discriminator="kind"),
]  # fmt: skip

# --------------------------------------------------------------------- rates


@with_config(STRICT)
class HzRate(TypedDict):
    """A free-running rate in cycles per second."""

    kind: Literal["hz"]
    value: float


@with_config(STRICT)
class BpmRate(TypedDict):
    """A rate locked to a speed master's tempo."""

    kind: Literal["bpm"]
    masterId: MasterId  # must name a speed master
    multiplier: float  # 0.25 = every 4 beats


type Rate = Annotated[HzRate | BpmRate, Field(discriminator="kind")]

# ----------------------------------------------------------------- instances


@with_config(STRICT)
class EffectPhase(TypedDict):
    """Phase spread across members, in degrees (0 → 360 = one full wave)."""

    start: float
    end: float


@with_config(STRICT)
class EffectInstance(TypedDict):
    """A template applied to targets, with rate, size and phase distribution."""

    id: str  # unique within its cue
    templateId: EffectId
    targets: TargetSpec
    rate: Rate
    direction: Literal["forward", "reverse", "bounce"]
    # amplitude
    size: float  # attribute units for add; 0..1 for multiply
    low: NotRequired[AttributeValue]  # absolute mode: wave 0 → low, 1 → high
    high: NotRequired[AttributeValue]
    # distribution across ordered members (§10.2)
    phase: EffectPhase
    groups: PositiveInt  # members cycle through N phase groups
    blocks: PositiveInt  # N consecutive members share a phase
    wings: PositiveInt  # mirror the phase pattern N times
    # dynamics
    sizeFadeIn: NotRequired[Seconds]  # seconds for size to ramp up
    sizeMasterId: NotRequired[MasterId]  # must name a size master
    speedMasterId: NotRequired[MasterId]  # must name a speed master
