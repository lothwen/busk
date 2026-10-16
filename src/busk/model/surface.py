"""Control surfaces and bindings (spec §5.15).

A binding maps one physical input (a MIDI CC, an OSC path, …) on a surface to
an action. ``CommandAction`` embeds any command from ``busk.commands.types``,
which is why that module's types are part of the show schema.

Phase 6 adds three optional pieces (phase-6-plan §9), so ``schemaVersion``
stays 1: ``SurfaceMatch.feedbackPort`` (where an OSC surface's feedback
goes), the :class:`MidiClock` input (one press per beat of an external MIDI
clock) and ``BlackoutAction.momentary`` (hold-to-blackout; a blackout
binding toggles otherwise).
"""

from __future__ import annotations

from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import Field, with_config

from busk.commands.types import Command
from busk.model.common import STRICT, EntityBase, MasterId, NonNegativeInt, PlaybackId, SurfaceId


@with_config(STRICT)
class SurfaceMatch(TypedDict, total=False):
    """How to recognise the physical device of a surface.

    Which fields apply depends on the surface's kind: ``deviceName`` for
    MIDI; ``port``, ``host`` and ``feedbackPort`` for OSC (the port to listen
    on, and where feedback goes); ``port`` and ``host`` (the address to bind)
    for the web remote.
    """

    deviceName: str
    port: int
    host: str
    feedbackPort: int  # OSC: the port feedback goes to (Phase 6)


@with_config(STRICT)
class ControlSurface(EntityBase[SurfaceId]):
    """A control surface: MIDI controller, OSC app, web remote, …"""

    kind: Literal["midi", "osc", "hid", "web", "internal"]
    match: SurfaceMatch
    faderPickup: Literal["jump", "soft"]  # soft takeover for non-motorised faders


# -------------------------------------------------------------------- inputs
# The spec uses the functional TypedDict syntax; class syntax lets each type
# carry the strict config decorator. Field names and types are unchanged.


@with_config(STRICT)
class MidiCC(TypedDict):
    """A MIDI control change."""

    kind: Literal["midiCC"]
    channel: int
    cc: int


@with_config(STRICT)
class MidiNote(TypedDict):
    """A MIDI note (buttons)."""

    kind: Literal["midiNote"]
    channel: int
    note: int


@with_config(STRICT)
class MidiPitchBend(TypedDict):
    """MIDI pitch bend: 14-bit faders."""

    kind: Literal["midiPitchBend"]
    channel: int


@with_config(STRICT)
class MidiClock(TypedDict):
    """An external MIDI clock: a press on every beat (24 clocks), Phase 6.

    It drives a ``tap`` action, so a speed master follows the clock's tempo
    and beat grid. A Start message makes the next clock a downbeat.
    """

    kind: Literal["midiClock"]


@with_config(STRICT)
class OscInput(TypedDict):
    """An OSC address."""

    kind: Literal["osc"]
    path: str


@with_config(STRICT)
class HwInput(TypedDict):
    """A control of built-in hardware."""

    kind: Literal["hw"]
    controlId: str


type InputAddress = Annotated[
    MidiCC | MidiNote | MidiPitchBend | MidiClock | OscInput | HwInput,
    Field(discriminator="kind"),
]

# ------------------------------------------------------------------- actions


@with_config(STRICT)
class FaderAction(TypedDict):
    """Drive the fader of a page-relative playback slot."""

    kind: Literal["playbackFader"]
    slot: NonNegativeInt


@with_config(STRICT)
class ButtonAction(TypedDict):
    """Press a button of a page-relative playback slot."""

    kind: Literal["playbackButton"]
    slot: NonNegativeInt
    button: NonNegativeInt


@with_config(STRICT)
class FaderAbsAction(TypedDict):
    """Drive the fader of one specific playback, whatever the page."""

    kind: Literal["playbackFaderAbs"]
    playbackId: PlaybackId


@with_config(STRICT)
class MasterAction(TypedDict):
    """Drive a master's level."""

    kind: Literal["master"]
    masterId: MasterId


@with_config(STRICT)
class TapAction(TypedDict):
    """Tap tempo."""

    kind: Literal["tap"]
    masterId: MasterId  # must name a speed master


@with_config(STRICT)
class PageAction(TypedDict):
    """Move ``delta`` pages forward or back."""

    kind: Literal["page"]
    delta: int


@with_config(STRICT)
class PageAbsAction(TypedDict):
    """Go to a page by number."""

    kind: Literal["pageAbs"]
    number: int


@with_config(STRICT)
class BlackoutAction(TypedDict):
    """Toggle blackout on each press; with ``momentary``, blackout while held."""

    kind: Literal["blackout"]
    momentary: NotRequired[bool]  # Phase 6: hold-to-blackout, as Phases 2–5 did


@with_config(STRICT)
class CommandAction(TypedDict):
    """Issue an arbitrary command."""

    kind: Literal["command"]
    command: Command


type Action = Annotated[
    FaderAction | ButtonAction | FaderAbsAction | MasterAction | TapAction
    | PageAction | PageAbsAction | BlackoutAction | CommandAction,
    Field(discriminator="kind"),
]  # fmt: skip

# ------------------------------------------------------------------ bindings


type FeedbackKind = Literal["led", "motorFader", "display"]
"""What a binding's feedback drives (:attr:`BindingFeedback.kind`)."""


@with_config(STRICT)
class BindingFeedback(TypedDict):
    """Where to send feedback (LEDs, motor faders, displays) for a binding."""

    kind: Literal["led", "motorFader", "display"]
    address: InputAddress


@with_config(STRICT)
class Binding(TypedDict):
    """One input on one surface mapped to one action."""

    id: str
    surfaceId: SurfaceId
    input: InputAddress
    action: Action
    feedback: NotRequired[BindingFeedback]
