"""Compile a validated show into what the engine reads every tick (spec §6).

The compiled show holds:

* the **universe table**: the show's universes sorted by user number. A
  universe's position in the table is its row in every per-universe array;
* the **base images**: one 512-byte image per universe. Every channel of a
  patched fixture holds its profile's ``defaultDmx`` and every other address
  is 0. Each tick starts from a copy of them, so channels that no slot
  drives (control channels) keep their ``defaultDmx`` (§13.5);
* the **slot table** and its default logical frame (§6.1–§6.2,
  :mod:`busk.compiler.slots`);
* the **readout** lookups that read the logical frame back per fixture
  element (GAP-01, :mod:`busk.compiler.readout`);
* the **compiled channels**, one readable record per slot-driven channel
  (:mod:`busk.compiler.channels`);
* the **conversion plan**, the same channels flattened into arrays for the
  vectorised converter (:mod:`busk.convert.plan`);
* the **compiled cues** of every cue list, each the cue's tracked state
  with per-slot timing (:mod:`busk.compiler.cues`,
  :mod:`busk.compiler.tracking`) and the colour a display shows for it
  (GAP-17, read with the readout lookups), and
  the **playbacks**, the **pages** and the **masters** the engine and
  the bindings run on (:mod:`busk.compiler.playbacks`);
* the **safety** data: park entries and fixture limits as lane arrays
  (Phase 7, :mod:`busk.compiler.safety`);
* **warnings** found while compiling: cue values dropped for a target that
  does not offer them; unpatched fixtures that something drives, and park
  entries that cannot act (Phase 7). The show is still valid; the CLI
  prints them;
* the show's **output settings**, **surfaces** and **bindings**, unchanged.
  They are references into the show, which is never mutated in place
  (Phase 3 edits are copy-on-write), so the output and input threads can
  reconcile their routes and bindings from whichever compiled show the
  engine last published; and **softControls**, the ids of the bindings
  whose surface picks faders up softly, for the engine's soft takeover
  (Phase 6).

**Incremental recompile** (§6.4, phase-3-plan §5.11). Live edits are
copy-on-write, so an entity the edit did not touch is the very same object
in the new show. :func:`compile_show` with ``previous`` uses that instead of
the spec's reverse dependency index:

* the rig (universes, slots, channels, conversion plan, base images,
  readout) is reused when ``profiles``, ``fixtures`` and ``universes`` are
  the same lists as before;
* a compiled cue list is reused when, on top of that, the cue list is the
  same object at the same position and every group, preset and effect
  template its entries, releases and effects read is the same object as
  before.

Everything else (playbacks, pages, masters, safety) is cheap and always
rebuilt. The result equals a full compile; a test checks it after every
step of the Phase 3 build.

Everything is immutable (frozen dataclasses, tuples, read-only arrays and
mappings), so one compiled show can be shared by every thread.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

import numpy as np
from numpy.typing import NDArray

from busk.compiler.channels import CompiledChannel, build_channels
from busk.compiler.cues import CueCompiler
from busk.compiler.playbacks import (
    CompiledCueList,
    CompiledMaster,
    CompiledPage,
    CompiledPlayback,
    compile_cue_list,
    compile_masters,
    compile_pages,
    compile_playbacks,
)
from busk.compiler.readout import ReadoutLayout, build_readout
from busk.compiler.rig import RigFixture, byte_offsets, resolve_rig
from busk.compiler.safety import CompiledSafety, compile_safety, dark_bytes, unpatched_warnings
from busk.compiler.slots import SlotTable, build_slots
from busk.compiler.tracking import compile_cue_states
from busk.convert.dmx import UNIVERSE_SIZE, split_raw
from busk.convert.plan import ConversionPlan, build_plan
from busk.errors import BuskError
from busk.model.common import CueListId, MasterId, PlaybackId, UniverseId
from busk.model.output import OutputSettings
from busk.model.show import Show
from busk.model.surface import Binding, ControlSurface
from busk.model.validate import Issue

__all__ = [
    "UNIVERSE_SIZE",
    "CompiledShow",
    "CompiledUniverse",
    "UnsupportedFeature",
    "compile_show",
]


class UnsupportedFeature(BuskError):
    """The show is valid, but uses a feature this build cannot compile yet."""


@dataclass(frozen=True, kw_only=True)
class CompiledUniverse:
    """A universe as the engine and output threads see it."""

    id: UniverseId
    number: int
    name: str


@dataclass(frozen=True, kw_only=True, eq=False)
class OutputLayout:
    """What the output needs of a compiled show (phase-7-plan §5.13): its
    universes (the rows of a frame), its output settings and engine rate,
    and the **dark bytes**: the flat positions (``row × 512 + address``)
    that intensity reaches (dimmer channels' coarse, fine and ultra bytes;
    the emitter channels of virtual-intensity fixtures), with their values
    at intensity 0 (255 for an inverted dimmer). A stalled engine with
    ``holdLastFrameOnEngineStall: false`` sends the last frame with these
    bytes set (decision 14).

    Layouts compare equal by value; a recompile that changes none of it
    hands on the previous layout object.
    """

    universes: tuple[CompiledUniverse, ...]
    output: OutputSettings
    engineHz: float
    darkPositions: NDArray[np.intp]  # read-only
    darkValues: NDArray[np.uint8]  # read-only

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OutputLayout):
            return NotImplemented
        return (
            self.universes == other.universes
            and self.output == other.output
            and self.engineHz == other.engineHz
            and np.array_equal(self.darkPositions, other.darkPositions)
            and np.array_equal(self.darkValues, other.darkValues)
        )

    __hash__ = None  # type: ignore[assignment]  # mutable-looking fields: unhashable


@dataclass(frozen=True, kw_only=True)
class CompiledShow:
    """Immutable compiled show, shared read-only between threads."""

    engineHz: float
    universes: tuple[CompiledUniverse, ...]  # sorted by number; index = row of baseImages
    baseImages: NDArray[np.uint8]  # shape (len(universes), 512); read-only
    slots: SlotTable
    readout: ReadoutLayout  # GAP-01: the output readout's per-element lookups
    channels: tuple[CompiledChannel, ...]
    plan: ConversionPlan
    cueLists: Mapping[CueListId, CompiledCueList]
    playbacks: Mapping[PlaybackId, CompiledPlayback]  # show order
    pages: tuple[CompiledPage, ...]  # sorted by number
    masters: Mapping[MasterId, CompiledMaster]  # show order
    safety: CompiledSafety  # Phase 7
    warnings: tuple[Issue, ...]  # in document order
    output: OutputSettings  # the show's own settings: never mutated
    surfaces: tuple[ControlSurface, ...]
    bindings: tuple[Binding, ...]
    softControls: frozenset[str]  # ids of the bindings on faderPickup "soft" surfaces
    layout: OutputLayout  # Phase 7: what the output reads
    memo: CompileMemo | None = field(default=None, compare=False, repr=False)

    @property
    def grandMasters(self) -> tuple[CompiledMaster, ...]:
        """The grand masters; their levels multiply (phase-2-plan §9)."""
        return tuple(master for master in self.masters.values() if master.kind == "grand")


@dataclass(frozen=True, kw_only=True)
class _ListMemo:
    """A compiled cue list and what it was compiled from."""

    source: object  # the cue list dict, compared by identity
    index: int  # its position in show["cueLists"] (warning paths name it)
    groups: frozenset[str]  # ids of the groups its entries read
    presets: frozenset[str]  # ids of the presets its entries read
    templates: frozenset[str]  # ids of the effect templates its effects read
    cueList: CompiledCueList
    warnings: tuple[Issue, ...]


@dataclass(frozen=True, kw_only=True)
class CompileMemo:
    """What a later :func:`compile_show` may reuse, keyed by object identity."""

    profiles: object
    fixtures: object
    universes: object
    groups: Mapping[str, object]  # group id → the group dict compiled against
    presets: Mapping[str, object]
    templates: Mapping[str, object]
    cueLists: Mapping[CueListId, _ListMemo]


def compile_show(show: Show, previous: CompiledShow | None = None) -> CompiledShow:
    """Compile ``show``, which must have passed validation without errors.

    With ``previous`` (the compiled form of the show this one was edited
    from), whatever provably did not change is reused (see the module docs);
    the result is the same as a full compile.

    On overlapping patches, the fixture later in ``show["fixtures"]`` wins
    each shared byte. Unpatched fixtures get slots but no channels.

    Raises :class:`UnsupportedFeature` for a fixture with an ``elementPatch``:
    the spec does not yet define whether a split element's channel offsets
    are relative to the element's own address or to the mode start.
    """
    memo = previous.memo if previous is not None else None
    same_rig = (
        previous is not None
        and memo is not None
        and show["profiles"] is memo.profiles
        and show["fixtures"] is memo.fixtures
        and show["universes"] is memo.universes
    )
    if same_rig:
        assert previous is not None
        universes, slots, channels = previous.universes, previous.slots, previous.channels
        base_images, plan, readout = previous.baseImages, previous.plan, previous.readout
    else:
        for index, fixture in enumerate(show["fixtures"]):
            if fixture.get("elementPatch"):
                raise UnsupportedFeature(
                    f"fixtures[{index}].elementPatch: split patches are not supported yet"
                )
        universes = tuple(
            CompiledUniverse(id=u["id"], number=u["number"], name=u["name"])
            for u in sorted(show["universes"], key=lambda u: u["number"])
        )
        rows = {universe.id: row for row, universe in enumerate(universes)}
        rig = resolve_rig(show)
        slots = build_slots(rig)
        readout = build_readout(rig, slots)
        channels = build_channels(rig, slots, rows)
        base_images = _base_images(rig, rows, len(universes))
        plan = build_plan(channels, slots, len(universes))
    groups: dict[str, object] = {group["id"]: group for group in show["groups"]}
    presets: dict[str, object] = {preset["id"]: preset for preset in show["presets"]}
    templates: dict[str, object] = {template["id"]: template for template in show["effects"]}
    # Every cue is compiled, so errors surface uniformly.
    cues = CueCompiler(show, slots)
    lists: dict[CueListId, _ListMemo] = {}
    for i, cue_list in enumerate(show["cueLists"]):
        old = memo.cueLists.get(cue_list["id"]) if same_rig and memo is not None else None
        if (
            old is not None
            and memo is not None
            and _still_valid(old, cue_list, i, memo, groups, presets, templates)
        ):
            lists[cue_list["id"]] = old
            continue
        cues.readGroups.clear()
        cues.readPresets.clear()
        cues.readTemplates.clear()
        before = len(cues.warnings)
        compiled_cues = compile_cue_states(cues, cue_list, f"cueLists[{i}]", readout)
        lists[cue_list["id"]] = _ListMemo(
            source=cue_list,
            index=i,
            groups=frozenset(cues.readGroups),
            presets=frozenset(cues.readPresets),
            templates=frozenset(cues.readTemplates),
            cueList=compile_cue_list(cue_list, compiled_cues),
            warnings=tuple(cues.warnings[before:]),
        )
    cue_lists = MappingProxyType({ident: entry.cueList for ident, entry in lists.items()})
    safety, park_warnings = compile_safety(show, slots)
    if same_rig:
        assert previous is not None
        dark = previous.layout.darkPositions, previous.layout.darkValues
    else:
        dark = dark_bytes(slots, channels, plan, base_images)
    layout = OutputLayout(
        universes=universes,
        output=show["output"],
        engineHz=show["output"]["engineHz"],
        darkPositions=dark[0],
        darkValues=dark[1],
    )
    if previous is not None and previous.layout == layout:
        layout = previous.layout  # unchanged: the output compares it by identity first
    return CompiledShow(
        engineHz=show["output"]["engineHz"],
        universes=universes,
        baseImages=base_images,
        slots=slots,
        readout=readout,
        channels=channels,
        plan=plan,
        cueLists=cue_lists,
        playbacks=compile_playbacks(show, cue_lists),
        pages=compile_pages(show),
        masters=compile_masters(show, slots),
        safety=safety,
        warnings=(
            *unpatched_warnings(show, cue_lists),
            *(warning for entry in lists.values() for warning in entry.warnings),
            *park_warnings,
        ),
        output=show["output"],
        surfaces=tuple(show["surfaces"]),
        bindings=tuple(show["bindings"]),
        softControls=_soft_controls(show),
        layout=layout,
        memo=CompileMemo(
            profiles=show["profiles"],
            fixtures=show["fixtures"],
            universes=show["universes"],
            groups=groups,
            presets=presets,
            templates=templates,
            cueLists=lists,
        ),
    )


def _soft_controls(show: Show) -> frozenset[str]:
    """The ids of the bindings on a ``faderPickup: "soft"`` surface: the
    controls the engine's soft takeover applies to (phase-6-plan §5.4)."""
    soft = {surface["id"] for surface in show["surfaces"] if surface["faderPickup"] == "soft"}
    return frozenset(binding["id"] for binding in show["bindings"] if binding["surfaceId"] in soft)


def _still_valid(
    old: _ListMemo,
    cue_list: object,
    index: int,
    memo: CompileMemo,
    groups: Mapping[str, object],
    presets: Mapping[str, object],
    templates: Mapping[str, object],
) -> bool:
    """Whether a compiled cue list can be reused: same list object at the same
    position, and every group, preset and effect template it read unchanged."""
    return (
        old.source is cue_list
        and old.index == index
        and all(groups.get(g) is memo.groups.get(g) for g in old.groups)
        and all(presets.get(p) is memo.presets.get(p) for p in old.presets)
        and all(templates.get(t) is memo.templates.get(t) for t in old.templates)
    )


def _base_images(
    rig: tuple[RigFixture, ...], rows: dict[UniverseId, int], count: int
) -> NDArray[np.uint8]:
    """Every patched channel's ``defaultDmx``, split into its bytes; the later
    fixture wins overlaps. Read-only."""
    images = np.zeros((count, UNIVERSE_SIZE), dtype=np.uint8)
    for fixture in rig:
        patch = fixture.fixture["patch"]
        if patch is None:
            continue
        image = images[rows[patch["universeId"]]]
        start = patch["address"] - 1
        for channel in fixture.mode["channels"]:
            values = split_raw(channel["defaultDmx"], channel["bytes"])
            for offset, value in zip(byte_offsets(channel), values, strict=True):
                image[start + offset] = value
    images.flags.writeable = False
    return images
