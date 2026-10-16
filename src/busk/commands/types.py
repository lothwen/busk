"""Command types (spec §15.2).

Commands are tagged by ``type``. They fall into four classes
(:mod:`busk.commands.classes` maps every type to exactly one):

* **Performance** (``TRIGGER_PLAYBACK`` … ``PLAYBACK_BUTTON``): not undoable,
  not persisted (only logged); applied on the next engine tick. Phase 2 adds
  ``TOGGLE_PLAYBACK`` to the spec's list.
* **Programmer** (``SELECT`` … ``BLIND``): change the programmer; undone on
  the session's one undo timeline, and autosaved (Phase 3).
* **Show edit** (``RECORD_CUE`` … ``BATCH``): validated, applied to the show
  store as copy-on-write patches, undoable and persisted.
* **Session** (``UNDO``, ``REDO``): walk the undo timeline.

Phase 3 changes to §15.2 (phase-3-plan §5.1, §9):

* ``RECORD_CUE.merge`` is optional: leaving it out means "create; error if
  the cue exists", so a typo cannot overwrite a cue. It gains ``name`` and
  ``freeze`` (record explicit targets instead of group references).
* ``RECORD_PRESET`` gains ``merge`` (replacing the spec's
  ``UPDATE_PRESET``) and ``name``.
* New: ``SELECT_PLAYBACK`` (the ``select`` button), ``BLIND`` with an ``on``
  field, ``RECORD_GROUP`` (replacing ``EDIT_GROUP``), ``ASSIGN_PLAYBACK``
  with concrete fields, the generic edits ``ADD`` / ``SET`` / ``DELETE``
  (replacing ``RENAME`` and the spec's ``DELETE``), ``BATCH``, ``UNDO`` and
  ``REDO``.

Phase 4 adds ``SET_BPM`` (performance) and ``PROGRAMMER_FADE`` (programmer,
a mode like ``BLIND``: never undone) (phase-4-plan decision 15).

Phase 5 adds ``ADD_EFFECT`` and ``REMOVE_EFFECT`` (programmer): effect
instances are programmer content, like values (phase-5-plan decision 17).

Phase 6 adds ``PAGE`` and ``PLAYBACK_BUTTON`` (performance), which the engine
resolves against its current page (phase-6-plan decisions 1–3).
``SET_FADER`` names its playback by ``playbackId`` or by ``slot`` of the
current page; ``BLACKOUT`` without ``on`` toggles; and
``CommandOrigin.control`` names the binding a command came from, for soft
takeover and held buttons (decision 5).

Phase 7 adds ``RELEASE_ALL`` and ``OUTPUT`` (performance), the panic
commands of §18, and ``HIGHLIGHT`` (programmer, a mode like ``BLIND``)
(phase-7-plan decisions 12 and 15).

Generic edits address the show with an :data:`EditPath`: a list whose
string segments are object keys and whose :class:`IdSegment` segments pick
the element of an id'd list with that ``id``, e.g.
``["cueLists", {"id": "cl-song"}, "cues", {"id": "c-verse"}, "timing",
"fadeIn"]``.

Every addition is backward compatible (new types, new optional fields), so
``schemaVersion`` stays 1: show files embed commands in bindings.

The spec writes these with the functional ``TypedDict`` syntax; class syntax
is used here so each one carries the strict config decorator. Field names and
types are unchanged.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import AfterValidator, Discriminator, Field, JsonValue, Tag, with_config
from pydantic_core import PydanticCustomError

from busk.model.attributes import AttributeFamily
from busk.model.common import (
    STRICT,
    AttributeId,
    CueListId,
    FixtureId,
    MasterId,
    NonNegativeInt,
    PlaybackId,
    PresetId,
    Seconds,
    SurfaceId,
    Unit,
)
from busk.model.effect import EffectInstance
from busk.model.entry import TargetSpec, ValueSource
from busk.model.fixture import PatchAddress
from busk.model.preset import PresetPool

# ------------------------------------------------------------- performance


@with_config(STRICT)
class TriggerPlaybackCmd(TypedDict):
    """Activate a playback."""

    type: Literal["TRIGGER_PLAYBACK"]
    playbackId: PlaybackId


@with_config(STRICT)
class ReleasePlaybackCmd(TypedDict):
    """Release a playback, optionally overriding its release time."""

    type: Literal["RELEASE_PLAYBACK"]
    playbackId: PlaybackId
    time: NotRequired[Seconds]


@with_config(STRICT)
class TogglePlaybackCmd(TypedDict):
    """Activate a playback if it is not active, release it if it is.

    Not in the spec's §15.2 list: Phase 2 adds it (phase-2-plan decision 10)
    because a ``toggle`` button needs engine state that stateless bindings
    lack. The addition is backward compatible, so ``schemaVersion`` stays 1.
    """

    type: Literal["TOGGLE_PLAYBACK"]
    playbackId: PlaybackId


@with_config(STRICT)
class FlashCmd(TypedDict):
    """Flash button pressed (``down``) or released."""

    type: Literal["FLASH"]
    playbackId: PlaybackId
    down: bool


@with_config(STRICT)
class GoCmd(TypedDict):
    """Advance a playback to its next cue."""

    type: Literal["GO"]
    playbackId: PlaybackId


@with_config(STRICT)
class BackCmd(TypedDict):
    """Step a playback back to its previous cue."""

    type: Literal["BACK"]
    playbackId: PlaybackId


@with_config(STRICT)
class GotoCmd(TypedDict):
    """Jump a playback to a cue by number."""

    type: Literal["GOTO"]
    playbackId: PlaybackId
    cueNumber: str


@with_config(STRICT)
class SetFaderCmd(TypedDict):
    """Move a playback fader.

    The playback is named by exactly one of ``playbackId`` and ``slot``, a
    0-based index into the engine's current page (Phase 6). An empty slot does
    nothing.
    """

    type: Literal["SET_FADER"]
    playbackId: NotRequired[PlaybackId]
    slot: NotRequired[NonNegativeInt]
    level: Unit


@with_config(STRICT)
class SetMasterCmd(TypedDict):
    """Set a master's level."""

    type: Literal["SET_MASTER"]
    masterId: MasterId
    level: Unit


@with_config(STRICT)
class TapCmd(TypedDict):
    """Tap tempo on a speed master."""

    type: Literal["TAP"]
    masterId: MasterId  # must name a speed master


@with_config(STRICT)
class SetBpmCmd(TypedDict):
    """Set a speed master's tempo, keeping its beat phase (Phase 4)."""

    type: Literal["SET_BPM"]
    masterId: MasterId  # must name a speed master
    bpm: float  # 0 < bpm ≤ 999


@with_config(STRICT)
class BlackoutCmd(TypedDict):
    """Switch blackout on or off; toggle it when ``on`` is left out (Phase 6).

    The engine does the toggling, so two surfaces cannot disagree about the
    state they toggle from.
    """

    type: Literal["BLACKOUT"]
    on: NotRequired[bool]


@with_config(STRICT)
class PageCmd(TypedDict):
    """Change the engine's current page (Phase 6), shared by every surface.

    Exactly one of ``number`` (go to that page) and ``delta`` (move through
    the pages in number order, stopping at the first and last).
    """

    type: Literal["PAGE"]
    number: NotRequired[int]
    delta: NotRequired[int]


@with_config(STRICT)
class PlaybackButtonCmd(TypedDict):
    """Press (``down``) or release a playback's button (Phase 6).

    The engine applies the function in the playback's ``buttons[button]``
    (spec §8.1). The playback is named by exactly one of ``playbackId`` and
    ``slot`` of the current page. A flash or swop pressed through a slot is
    released on the playback it was pressed on, even after a page change.
    """

    type: Literal["PLAYBACK_BUTTON"]
    playbackId: NotRequired[PlaybackId]
    slot: NotRequired[NonNegativeInt]
    button: NonNegativeInt  # index into the playback's buttons
    down: bool


@with_config(STRICT)
class ReleaseAllCmd(TypedDict):
    """Release every active, releasing or flashing playback (Phase 7, §18 panic).

    Each playback releases over its own release time, or over ``time`` when
    given. Held flashes and swops are dropped; the programmer is left alone.
    """

    type: Literal["RELEASE_ALL"]
    time: NotRequired[Seconds]


@with_config(STRICT)
class OutputCmd(TypedDict):
    """Switch the output on or off (Phase 7, §18 panic).

    While it is off, routes send nothing; sACN receivers are told the stream
    has terminated. It is engine state, so every surface sees it.
    """

    type: Literal["OUTPUT"]
    on: bool


# -------------------------------------------------------------- programmer


@with_config(STRICT)
class SelectCmd(TypedDict):
    """Change the programmer selection."""

    type: Literal["SELECT"]
    targets: TargetSpec
    mode: Literal["replace", "add", "remove"]


@with_config(STRICT)
class SetAttributeCmd(TypedDict):
    """Set an attribute on the current selection."""

    type: Literal["SET_ATTRIBUTE"]
    attribute: AttributeId
    value: ValueSource


@with_config(STRICT)
class ApplyPresetCmd(TypedDict):
    """Apply a preset to the current selection."""

    type: Literal["APPLY_PRESET"]
    presetId: PresetId


@with_config(STRICT)
class ClearProgrammerCmd(TypedDict):
    """Clear the programmer's selection, values and effects (blind keeps its state)."""

    type: Literal["CLEAR_PROGRAMMER"]


@with_config(STRICT)
class SelectPlaybackCmd(TypedDict):
    """Select the targets of a playback's cue (the ``select`` button, §8.1).

    That is the current cue's tracked state, as the engine snapshot shows it;
    the first cue's when the playback is idle (phase-4-plan §5.10).
    """

    type: Literal["SELECT_PLAYBACK"]
    playbackId: PlaybackId
    mode: Literal["replace", "add", "remove"]


@with_config(STRICT)
class BlindCmd(TypedDict):
    """Switch blind on or off: programmer values stay, live output excludes them."""

    type: Literal["BLIND"]
    on: bool


@with_config(STRICT)
class HighlightCmd(TypedDict):
    """Switch highlight on or off (Phase 7): the selected targets at full
    intensity, open and white, live even when the programmer is blind. A mode
    like blind: never undone."""

    type: Literal["HIGHLIGHT"]
    on: bool


@with_config(STRICT)
class ProgrammerFadeCmd(TypedDict):
    """Set the programmer's fade time (Phase 4): later programmer changes fade
    over it. A mode like blind: never undone."""

    type: Literal["PROGRAMMER_FADE"]
    time: Seconds


@with_config(STRICT)
class AddEffectCmd(TypedDict):
    """Add an effect instance to the programmer, or replace the one with the
    same ``id`` in place (Phase 5). The console fills ``targets`` with the
    selection, in order."""

    type: Literal["ADD_EFFECT"]
    effect: EffectInstance


@with_config(STRICT)
class RemoveEffectCmd(TypedDict):
    """Remove the programmer's effect ``id``, or every programmer effect
    without one (Phase 5)."""

    type: Literal["REMOVE_EFFECT"]
    id: NotRequired[str]


# --------------------------------------------------------------- show edit


type RecordMerge = Literal["replace", "merge", "remove"]
"""How a record command treats an existing destination. Absent means
"create, and fail if it already exists"."""


@with_config(STRICT)
class RecordCueCmd(TypedDict):
    """Record programmer values into a cue (§15.3).

    Without ``cueNumber`` the cue is the next whole number after the list's
    last cue. ``filter`` lists the families to record (default: every family
    but ``control``). ``freeze`` records explicit targets instead of group
    references.
    """

    type: Literal["RECORD_CUE"]
    cueListId: CueListId
    cueNumber: NotRequired[str]
    filter: NotRequired[list[AttributeFamily]]
    merge: NotRequired[RecordMerge]
    name: NotRequired[str]
    freeze: NotRequired[bool]


@with_config(STRICT)
class RecordPresetCmd(TypedDict):
    """Record programmer values into a preset, starting the scope cascade at ``scope``."""

    type: Literal["RECORD_PRESET"]
    pool: PresetPool
    number: int
    scope: Literal["global", "profile", "target"]
    merge: NotRequired[RecordMerge]
    name: NotRequired[str]


@with_config(STRICT)
class RecordGroupCmd(TypedDict):
    """Record the programmer selection as group ``number`` (members in selection order)."""

    type: Literal["RECORD_GROUP"]
    number: int
    merge: NotRequired[RecordMerge]
    name: NotRequired[str]


@with_config(STRICT)
class PatchFixtureCmd(TypedDict):
    """Patch a fixture, or unpatch it with ``patch: null``."""

    type: Literal["PATCH_FIXTURE"]
    fixtureId: FixtureId
    patch: PatchAddress | None


@with_config(STRICT)
class AssignPlaybackCmd(TypedDict):
    """Put a playback in a page slot (0-based), or empty the slot with ``null``.

    The page's ``slots`` list is extended with empty slots as needed.
    """

    type: Literal["ASSIGN_PLAYBACK"]
    pageId: str
    slot: NonNegativeInt
    playbackId: PlaybackId | None


# --------------------------------------------------------- generic edits


@with_config(STRICT)
class IdSegment(TypedDict):
    """An :data:`EditPath` segment: the element of an id'd list with this ``id``."""

    id: str


def _segment_kind(value: object) -> str | None:
    """Pydantic discriminator of :data:`EditSegment`.

    The tags are not key names on purpose: error locations carry them, and
    the validator's path mapper must not mistake one for the ``id`` key.
    """
    if isinstance(value, str):
        return "keySegment"
    if isinstance(value, dict):
        return "idSegment"
    return None


type EditSegment = Annotated[
    Annotated[str, Tag("keySegment")] | Annotated[IdSegment, Tag("idSegment")],
    Discriminator(
        _segment_kind,
        custom_error_type="edit_segment",
        custom_error_message="Input should be an object key (a string) or an id segment {id}",
    ),
]

type EditPath = list[EditSegment]
"""Where a generic edit applies: object keys and id segments, from the show root."""


def _finite(value: JsonValue) -> JsonValue:
    """Reject ``NaN`` and infinities anywhere in a JSON value.

    ``JsonValue`` accepts them even under the strict config, and a show may
    not contain them (§5, ``STRICT``).
    """
    stack: list[JsonValue] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, float) and not math.isfinite(item):
            raise PydanticCustomError("finite_number", "Input should be a finite number")
        if isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, dict):
            stack.extend(item.values())
    return value


type EditValue = Annotated[JsonValue, AfterValidator(_finite)]
"""Any finite JSON value; the show validator checks it once it is in place."""


@with_config(STRICT)
class AddCmd(TypedDict):
    """Append an entity (an object with an ``id``) to the id'd list at ``path``.

    Cues are inserted in cue-number order instead of appended.
    """

    type: Literal["ADD"]
    path: EditPath
    value: EditValue


@with_config(STRICT)
class SetCmd(TypedDict):
    """Set the object key that ``path`` ends with; an absent optional key is created."""

    type: Literal["SET"]
    path: EditPath
    value: EditValue


@with_config(STRICT)
class DeleteCmd(TypedDict):
    """Remove the id'd list element or the optional key that ``path`` ends with."""

    type: Literal["DELETE"]
    path: EditPath


type ShowEditCommand = Annotated[
    RecordCueCmd | RecordPresetCmd | RecordGroupCmd | PatchFixtureCmd | AssignPlaybackCmd
    | AddCmd | SetCmd | DeleteCmd,
    Field(discriminator="type"),
]  # fmt: skip
"""A show edit that a :class:`BatchCmd` may hold (every one but ``BATCH``)."""


@with_config(STRICT)
class BatchCmd(TypedDict):
    """Several show edits applied atomically, as one undo step.

    Each command sees the show as the commands before it left it, so a later
    command can refer to an entity an earlier one creates (callers choose the
    ids). If any command fails, or the result does not validate, nothing
    changes.
    """

    type: Literal["BATCH"]
    label: str
    commands: list[ShowEditCommand]


# ---------------------------------------------------------------- session


@with_config(STRICT)
class UndoCmd(TypedDict):
    """Undo the last step: a show edit or a programmer change."""

    type: Literal["UNDO"]


@with_config(STRICT)
class RedoCmd(TypedDict):
    """Redo the last undone step."""

    type: Literal["REDO"]


type Command = Annotated[
    TriggerPlaybackCmd | ReleasePlaybackCmd | TogglePlaybackCmd | FlashCmd
    | GoCmd | BackCmd | GotoCmd
    | SetFaderCmd | SetMasterCmd | TapCmd | SetBpmCmd | BlackoutCmd
    | PageCmd | PlaybackButtonCmd | ReleaseAllCmd | OutputCmd
    | SelectCmd | SelectPlaybackCmd | SetAttributeCmd | ApplyPresetCmd | ClearProgrammerCmd
    | BlindCmd | ProgrammerFadeCmd | AddEffectCmd | RemoveEffectCmd | HighlightCmd
    | RecordCueCmd | RecordPresetCmd | RecordGroupCmd | PatchFixtureCmd | AssignPlaybackCmd
    | AddCmd | SetCmd | DeleteCmd | BatchCmd
    | UndoCmd | RedoCmd,
    Field(discriminator="type"),
]  # fmt: skip
"""Any command, tagged by ``type``."""

# ---------------------------------------------------------------- envelope


@with_config(STRICT)
class CommandOrigin(TypedDict, total=False):
    """Where a command came from (§15.1).

    ``control`` (Phase 6) is the id of the binding that produced the command.
    Soft takeover and held buttons belong to that control; a command without
    one (the console, the phone, embedded commands) acts as a jump source.
    """

    surfaceId: SurfaceId
    user: str
    remote: str
    control: str


@with_config(STRICT)
class CommandEnvelope(TypedDict):
    """A command as queued for the engine (§15.1).

    ``id`` is a sequential number (as a string) assigned by the bus;
    ``issuedAt`` is the bus clock's time when the command was enqueued. The
    engine applies a command at the time of the tick that drains it.
    """

    id: str
    issuedAt: float
    origin: CommandOrigin
    command: Command
