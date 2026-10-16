"""Compiled playbacks, the playback pages and the masters (spec §5.12–§5.13).

The engine's playback runtimes and the input bindings read these frozen
records instead of the show's dicts:

* :class:`CompiledCueList` holds a cue list's settings and its compiled
  cues, with an index by cue id (live swaps re-point a running playback by
  :class:`~busk.model.common.CueId`) and one by cue number (``GOTO``), and
  its :class:`CompiledChase` settings;
* :class:`CompiledPlayback` holds the :class:`~busk.model.playback.Playback`
  fields the runtime uses, flattened (``flash.level`` → ``flashLevel``), with
  the cue list it plays;
* :class:`CompiledPage`: the pages in number order. The engine owns the
  current page and resolves page-relative commands against it (Phase 6,
  phase-6-plan decisions 1–2);
* :class:`CompiledMaster`: every master with its kind and initial level, a
  speed master's tempo settings, and a group master's intensity positions.
  Phase 5 drives every kind but fade-time masters.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, cast

import numpy as np

from busk.compiler.cues import EMPTY_CUE, CompiledCue
from busk.compiler.slots import SlotTable
from busk.model.common import CueId, CueListId, MasterId, PlaybackId
from busk.model.cue import ChaseSettings, CueList, cue_number_key
from busk.model.master import Master
from busk.model.playback import ButtonFunction, FaderFunction
from busk.model.show import Show

type MasterKind = Literal["grand", "group", "speed", "size", "fadeTime"]
type LtpFaderMode = Literal["followFader", "threshold", "ignoreFader"]


@dataclass(frozen=True, kw_only=True)
class CompiledChase:
    """How a ``chase`` list steps (phase-4-plan §5.7): its rate, flattened
    from the show's ``Rate`` union, its direction and its crossfade."""

    rate: Literal["hz", "bpm"]
    hz: float  # steps per second (hz)
    masterId: MasterId | None  # the speed master (bpm)
    multiplier: float  # steps per beat (bpm)
    direction: Literal["forward", "reverse", "bounce", "random"]
    crossfade: float  # the fraction of a step spent fading into it


def compile_chase(settings: ChaseSettings) -> CompiledChase:
    """A list's ``chase`` settings, flattened."""
    rate = settings["rate"]
    return CompiledChase(
        rate=rate["kind"],
        hz=rate["value"] if rate["kind"] == "hz" else 0.0,
        masterId=rate["masterId"] if rate["kind"] == "bpm" else None,
        multiplier=rate["multiplier"] if rate["kind"] == "bpm" else 0.0,
        direction=settings["direction"],
        crossfade=settings["crossfade"],
    )


@dataclass(frozen=True, kw_only=True)
class CompiledCueList:
    """A cue list as the engine plays it: its settings and its cues, in order."""

    id: CueListId
    number: int
    mode: Literal["sequence", "chase"]
    tracking: bool
    wrap: bool
    releaseAtEnd: bool  # GO past the last cue releases the playback
    cues: tuple[CompiledCue, ...]
    byId: Mapping[CueId, int]  # cue id → index into ``cues``
    byNumber: Mapping[tuple[int, ...], int]  # cue number key → index (GOTO)
    chase: CompiledChase | None = None  # set whenever the list has chase settings

    @property
    def chasing(self) -> bool:
        """Whether the list plays as a chase: ``chase`` mode with settings
        (validation requires them) and at least one cue."""
        return self.mode == "chase" and self.chase is not None and bool(self.cues)

    def find(self, number: str) -> int | None:
        """The index of the cue numbered ``number``, or ``None``. Numbers
        compare as integer parts, so ``"01.5"`` finds cue ``"1.5"``."""
        key = cue_number_key(number)
        return None if key is None else self.byNumber.get(key)

    @property
    def first(self) -> CompiledCue:
        """The first cue, or :data:`~busk.compiler.cues.EMPTY_CUE` for an empty list."""
        return self.cues[0] if self.cues else EMPTY_CUE


def compile_cue_list(cue_list: CueList, cues: tuple[CompiledCue, ...]) -> CompiledCueList:
    """``cue_list``'s settings with its compiled ``cues``."""
    return CompiledCueList(
        id=cue_list["id"],
        number=cue_list["number"],
        mode=cue_list["mode"],
        tracking=cue_list["tracking"],
        wrap=cue_list["wrap"],
        releaseAtEnd=cue_list["releaseAtEnd"],
        cues=cues,
        byId=MappingProxyType({cue.id: i for i, cue in enumerate(cues)}),
        byNumber=MappingProxyType(
            {cast(tuple[int, ...], cue_number_key(cue.number)): i for i, cue in enumerate(cues)}
        ),
        chase=compile_chase(cue_list["chase"]) if "chase" in cue_list else None,
    )


@dataclass(frozen=True, kw_only=True)
class CompiledPlayback:
    """A playback as the engine runs it.

    ``gotoCue`` is the index in ``cueList`` of the cue its ``goto`` buttons
    go to (Phase 6): the cue the playback's ``gotoCue`` number names, or
    ``None`` when it has none or the number names no cue (validation warns).
    """

    id: PlaybackId
    number: int
    name: str
    priority: int  # band (§7.2)
    fader: FaderFunction
    buttons: tuple[ButtonFunction, ...]
    gotoCue: int | None
    ltpFaderMode: LtpFaderMode
    ltpThreshold: float
    autoStart: bool
    autoRelease: bool
    flashLevel: float
    flashIncludeLtp: bool
    flashPriorityBoost: int  # added to `priority` for the flash source (0 without a boost)
    protectFromSwop: bool  # keeps its intensity while another playback swops (Phase 6)
    exclusivity: str | None
    releaseTime: float
    cueList: CompiledCueList


@dataclass(frozen=True, kw_only=True)
class CompiledMaster:
    """A master: its kind, and the level it starts at.

    That is ``initialLevel`` if the show has one. Otherwise it is full, except
    for a speed master, which starts at its ×1 step (:func:`unit_step_level`),
    and a fade-time master, which starts at 0 (Phase 6).
    The speed fields are set for speed masters only, and ``positions`` for
    group masters only.

    A group master's ``positions`` index the slot table's ``intensityLanes``:
    one per member of its group with an intensity slot, ascending and
    without repeats (phase-5-plan §5.8). A member is exactly its element, as
    everywhere since Phase 3. They are a tuple, so masters compare with
    ``==``; the engine turns them into an index array only when a level
    changes (:func:`~busk.engine.masters.group_factor`).
    """

    id: MasterId
    kind: MasterKind
    name: str
    initialLevel: float
    defaultBpm: float = 0.0  # the tempo the beat count starts at
    tap: bool = False  # TAP is accepted
    multiplierSteps: tuple[float, ...] = ()  # the level selects one (decision 11)
    positions: tuple[int, ...] = ()  # group masters: indices into intensityLanes

    def multiplier(self, level: float) -> float:
        """The step a speed master's ``level`` (0..1) selects: step
        ``round(level · (n − 1))`` of ``n``, halves rounding up (decision 11)."""
        steps = self.multiplierSteps
        return steps[math.floor(level * (len(steps) - 1) + 0.5)]


def compile_playbacks(
    show: Show, cue_lists: Mapping[CueListId, CompiledCueList]
) -> Mapping[PlaybackId, CompiledPlayback]:
    """Every playback of a validated show, by id, in show order."""
    playbacks: dict[PlaybackId, CompiledPlayback] = {}
    for playback in show["playbacks"]:
        flash = playback["flash"]
        cue_list = cue_lists[playback["cueListId"]]
        goto = playback.get("gotoCue")
        playbacks[playback["id"]] = CompiledPlayback(
            id=playback["id"],
            number=playback["number"],
            name=playback["name"],
            priority=playback["priority"],
            fader=playback["fader"],
            buttons=tuple(playback["buttons"]),
            gotoCue=None if goto is None else cue_list.find(goto),
            ltpFaderMode=playback["ltpFaderMode"],
            ltpThreshold=playback["ltpThreshold"],
            autoStart=playback["autoStart"],
            autoRelease=playback["autoRelease"],
            flashLevel=flash["level"],
            flashIncludeLtp=flash["includeLtp"],
            flashPriorityBoost=flash.get("priorityBoost", 0),
            protectFromSwop=playback["protectFromSwop"],
            exclusivity=playback.get("exclusivity"),
            releaseTime=playback["releaseTime"],
            cueList=cue_list,
        )
    return MappingProxyType(playbacks)


@dataclass(frozen=True, kw_only=True)
class CompiledPage:
    """A playback page: which playback each physical slot of a surface drives.

    ``slots[i]`` is the playback on slot ``i`` (0-based), ``None`` for an
    empty slot. Slots beyond the tuple are empty too.
    """

    id: str
    number: int
    name: str
    slots: tuple[PlaybackId | None, ...]


def compile_pages(show: Show) -> tuple[CompiledPage, ...]:
    """Every page of a validated show, sorted by number (numbers are unique)."""
    pages = sorted(show["pages"], key=lambda page: page["number"])
    return tuple(
        CompiledPage(
            id=page["id"], number=page["number"], name=page["name"], slots=tuple(page["slots"])
        )
        for page in pages
    )


def compile_masters(show: Show, slots: SlotTable) -> Mapping[MasterId, CompiledMaster]:
    """Every master, by id, in show order. Faders start at 0 but masters start
    at their ``initialLevel`` (§5.13), or at their default level.

    Masters are cheap and always rebuilt, so an edit of a group master's
    group (or of the patch) takes effect with the next swap.
    """
    return MappingProxyType(
        {master["id"]: _compile_master(show, slots, master) for master in show["masters"]}
    )


def _compile_master(show: Show, slots: SlotTable, master: Master) -> CompiledMaster:
    if master["kind"] == "group":
        return CompiledMaster(
            id=master["id"],
            kind="group",
            name=master["name"],
            initialLevel=master.get("initialLevel", 1.0),
            positions=_group_positions(show, slots, master["groupId"]),
        )
    if master["kind"] != "speed":
        # A fade-time master starts down, so adding one changes no timing
        # until it is raised (phase-6-plan decision 12).
        full = 0.0 if master["kind"] == "fadeTime" else 1.0
        return CompiledMaster(
            id=master["id"],
            kind=master["kind"],
            name=master["name"],
            initialLevel=master.get("initialLevel", full),
        )
    steps = tuple(master["multiplierSteps"])
    return CompiledMaster(
        id=master["id"],
        kind="speed",
        name=master["name"],
        initialLevel=master.get("initialLevel", unit_step_level(steps)),
        defaultBpm=master["defaultBpm"],
        tap=master["tap"],
        multiplierSteps=steps,
    )


def _group_positions(show: Show, slots: SlotTable, group_id: str) -> tuple[int, ...]:
    """The ``intensityLanes`` positions of the intensity slots of a group's
    members, ascending (a validated show's group exists). Members without an
    intensity slot have nothing to scale and are skipped."""
    members = next(group["members"] for group in show["groups"] if group["id"] == group_id)
    lanes = [
        slot.laneOffset
        for slot in (slots.find(member, "intensity") for member in members)
        if slot is not None
    ]
    # intensityLanes is ascending and holds every intensity slot's lane.
    positions = np.searchsorted(slots.intensityLanes, np.unique(np.array(lanes, dtype=np.intp)))
    return tuple(int(position) for position in positions)


def unit_step_level(steps: Sequence[float]) -> float:
    """The level that selects the step whose value is 1: a speed master's
    default level (decision 11).

    Validation does not require such a step; without one, the step nearest
    1 by ratio is used (the first of a tie). With a single step any level
    selects it, and the level is full, like the other masters' default.
    """
    if len(steps) < 2:
        return 1.0
    nearest = min(range(len(steps)), key=lambda k: abs(math.log(steps[k])))
    return nearest / (len(steps) - 1)
