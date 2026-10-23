"""The programmer as a display reads it (GAP-02 of ``docs/dev/tui/engine-gaps.md``).

``OfflineShow.programmer`` and ``LiveShow.programmer`` return a
:class:`ProgrammerStatus`: the selection, the values, the effects and the
modes (blind, highlight, the fade time), with fixtures by number and presets
by pool, number and name, so a display needs neither the session's ids nor
the text that ``programmer`` prints.

The facades make it on the reader's thread, from one
:class:`~busk.session.session.SessionSnapshot` (a show and the programmer of
the same moment), and only when that snapshot changed. A show change alone
can change it too: a renumbered fixture, a renamed or re-recorded preset.
:func:`programmer_status` hands the previous status back when the new one
would be equal, so its ``version`` and its identity change only with its
content.

**Only what is live is listed.** A selected target whose fixture or element
the show no longer has, a value whose slot, preset value or discrete option
is gone, and an effect that no longer validates stay in the programmer,
dormant (an undo may bring back what they need), and the stage leaves them
out (:func:`~busk.session.frame.build_frame`). So does the status.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import cast

from busk.commands.patch import deep_copy
from busk.compiler.lanes import EncodeError
from busk.model.attributes import AttributeValue
from busk.model.common import AttributeId, TargetRef
from busk.model.effect import EffectInstance
from busk.model.preset import PresetPool
from busk.model.validate import validate_effect
from busk.session.programmer import Programmer, split_slot_key
from busk.session.state import ShowState


@dataclass(frozen=True, slots=True, kw_only=True)
class ProgrammerValue:
    """One value of the programmer: what it gives one attribute of one
    fixture element (GAP-02 of ``docs/dev/tui/engine-gaps.md``).

    ``value`` is in the show's units, as ``set`` takes it: a number
    (intensity 0..1, pan and tilt in degrees …), a colour ``{"r", "g", "b",
    …}`` or a discrete value ``{"slot", …}``. For a preset reference it is
    the value the preset gives this element (the target, profile and global
    scopes, in that order), and ``preset`` is the preset's ``(pool, number,
    name)``; ``None`` for a value set directly.
    """

    number: int  # the fixture's number (101)
    element: int  # counted from 1, as the console counts them (301.3); 1 for one element
    attribute: AttributeId
    value: AttributeValue
    preset: tuple[PresetPool, int, str] | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProgrammerStatus:
    """The programmer: what it selects, holds and does (GAP-02).

    ``version`` is 1 for the first status a show hands out and grows by one
    whenever the content changes: a frontend redraws when it differs.
    ``selection`` is the selected fixture elements in selection order, as
    ``(number, element)`` pairs (the ``number`` and ``element`` of a
    :class:`~busk.engine.snapshot.FixtureOutput`). ``values`` are in the
    order the programmer holds them, each target where it first got a value.
    ``effects`` are the programmer's effect instances, in the show file's
    format (as in a cue's ``effects``), in the order they were added; their
    ``id`` is what ``effect remove`` takes. ``stopped`` holds the ids of
    those that are stopped (``effect stop``, GAP-14): they stay in
    ``effects`` but do not run. ``fadeTime`` is the time, in seconds, that
    programmer changes fade over (``fade``).

    Only what is live is listed: a target whose fixture is gone, or a value
    or effect that no longer reaches the stage, stays in the programmer,
    dormant, but not here. A stopped effect is listed: the operator stopped
    it, and can run it again.
    """

    version: int
    selection: tuple[tuple[int, int], ...]
    blind: bool
    highlight: bool
    fadeTime: float
    values: tuple[ProgrammerValue, ...]
    effects: tuple[EffectInstance, ...]
    stopped: frozenset[str]


def programmer_status(
    state: ShowState, programmer: Programmer, previous: ProgrammerStatus | None = None
) -> ProgrammerStatus:
    """``programmer`` as a display reads it, against ``state``'s show.

    Returns ``previous`` itself when the status would be equal to it, and
    otherwise a new one whose ``version`` is one more than ``previous``'s
    (1 without one).
    """
    numbers = {fixture["id"]: fixture["number"] for fixture in state.show["fixtures"]}
    presets = {preset["id"]: preset for preset in state.show["presets"]}

    def element(target: TargetRef) -> tuple[int, int] | None:
        if state.target_problem(target) is not None:
            return None
        return numbers[target["fixtureId"]], target["element"] + 1

    values: list[ProgrammerValue] = []
    for key, source in programmer.values.items():
        split = split_slot_key(key)
        slot = None if split is None else state.compiled.slots.find(*split)
        if slot is None:
            continue  # dormant: the target or its attribute is gone
        try:
            if state.values.resolve(source, slot, 0, 1) is None:
                continue  # dormant: the preset no longer defines this attribute here
        except EncodeError:
            continue  # dormant: a discrete option this target no longer offers
        if source["kind"] == "preset":
            preset = presets[source["presetId"]]
            value = state.values.preset_value(preset["id"], slot)
            named = (preset["pool"], preset["number"], preset["name"])
        else:
            value, named = source["value"], None
        values.append(
            ProgrammerValue(
                number=numbers[slot.target["fixtureId"]],
                element=slot.target["element"] + 1,
                attribute=slot.attribute.id,
                value=cast(AttributeValue, deep_copy(value)),
                preset=named,
            )
        )
    effects = tuple(
        cast(EffectInstance, deep_copy(effect))
        for effect in programmer.effects
        if not any(issue.severity == "error" for issue in validate_effect(state.show, effect))
    )
    version = 0 if previous is None else previous.version
    status = ProgrammerStatus(
        version=version,
        selection=tuple(pair for pair in map(element, programmer.selection) if pair is not None),
        blind=programmer.blind,
        highlight=programmer.highlight,
        fadeTime=programmer.fadeTime,
        values=tuple(values),
        effects=effects,
        stopped=frozenset(effect["id"] for effect in effects) & programmer.stopped,
    )
    if previous is not None and status == previous:
        return previous
    return replace(status, version=version + 1)
