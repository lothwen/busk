"""The programmer: the operator's editing buffer (spec §5.14, phase-3-plan §5.4).

The programmer holds an ordered **selection** of targets and **values** per
slot. Values are what the operator set and what recording reads; while the
programmer is not blind, they also reach the stage, above every normal
playback (band 100, §7.6).

Values are stored per slot (``SlotKey = "fixtureId:element/attribute"``),
and only in two forms (decision 7):

* a **literal** value, or
* a **preset reference**, kept as a reference (§5.14): recording a cue then
  stores ``{"kind": "preset"}``, not the colour numbers, and editing the
  preset later changes every look that uses it.

A spread or a per-target map is evaluated for each target when it is set and
stored as that target's literal (one source per slot cannot hold a fan; see
phase-3-plan §9). The spread rule is the compiler's: member ``k`` of the
``n`` selected targets, curve ``linear`` / ``center`` / ``edges``.

A :class:`Programmer` is an immutable value: every handler returns a new one
(copy-on-write values), which is what lets the undo timeline keep before and
after states for free.

``ADJUST_ATTRIBUTE`` (GAP-05 of ``docs/dev/tui/engine-gaps.md``) changes
values the programmer holds: by a delta, or one colour component, on each
selected target that has a value (a preset reference turns into the literal
it gave, changed). It never sets a target that has none: the programmer
does not know what the stage shows there.

A value whose slot no longer exists (its fixture was deleted, say) is kept
but ignored by output and recording; undoing the delete makes it live again.

Targets: a :class:`~busk.model.common.TargetRef` means exactly its own element.
(The console's ``fixture N`` expands to every element of fixture ``N``.)

From Phase 5 the programmer also holds **effect instances**
(phase-5-plan decision 17): ``ADD_EFFECT`` adds one or replaces the one
with the same ``id`` in place, ``REMOVE_EFFECT`` removes one or all, and
``CLEAR_PROGRAMMER`` clears them with the values. They are content: undone,
recorded and autosaved like values. An instance is checked against the show
when it is added; one whose template or targets vanish later stays,
dormant, like a value whose slot is gone.

``RUN_EFFECT`` (GAP-14 of ``docs/dev/tui/engine-gaps.md``) stops an effect
and runs it again: a stopped effect keeps its place and settings in the
programmer (``stopped`` holds its id), but the frame leaves it out, so it
fades out as if removed and starts again as if added, and recording leaves
it out too. Stopping is content: undone and autosaved like the effects.
Replacing a stopped effect (``ADD_EFFECT`` with its id) keeps it stopped.

Three **modes** sit beside the content: ``blind``, from Phase 4 the
``fadeTime`` that live programmer changes fade over (phase-4-plan §5.10),
and from Phase 7 ``highlight``, which lights the selection full, white and
open whether or not the programmer is blind (phase-7-plan §5.12; the
session builds it into each frame, :func:`busk.session.frame.highlight_of`).
Modes are not content: undo never changes them.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Final, NamedTuple, cast

from pydantic import TypeAdapter, ValidationError

from busk.commands.errors import CommandError
from busk.commands.patch import deep_copy
from busk.commands.types import AdjustAttributeCmd, Command
from busk.compiler.cues import spread_fraction, spread_value
from busk.compiler.slots import Slot
from busk.engine.snapshot import EngineSnapshot
from busk.model.attributes import (
    ATTRIBUTES,
    AttributeDefinition,
    AttributeValue,
    ColorValue,
    DiscreteValue,
    ScalarRange,
    value_kind,
)
from busk.model.common import (
    STRICT,
    AttributeId,
    PlaybackId,
    TargetKey,
    TargetRef,
    parse_target_key,
    target_key,
)
from busk.model.effect import EffectInstance
from busk.model.entry import LiteralSource, PresetSource, TargetSpec, ValueSource
from busk.model.validate import adjustment_problem, validate_effect
from busk.session.state import ShowState

type SlotKey = str
"""``f"{TargetKey}/{AttributeId}"``, e.g. ``"fx-mh1:0/pan"`` (§5.14)."""

type ProgSource = LiteralSource | PresetSource
"""What the programmer stores for one slot."""


def slot_key(target: TargetRef, attribute: AttributeId) -> SlotKey:
    """The programmer key of ``attribute`` on ``target``."""
    return f"{target_key(target)}/{attribute}"


def split_slot_key(key: SlotKey) -> tuple[TargetRef, AttributeId] | None:
    """``(target, attribute)`` of a slot key, or ``None`` if it is malformed.

    Attribute ids never contain ``/``, so the attribute is what follows the
    last one (fixture ids may contain anything).
    """
    target_text, slash, attribute = key.rpartition("/")
    target = parse_target_key(target_text) if slash else None
    return None if target is None or attribute not in ATTRIBUTES else (target, attribute)


@dataclass(frozen=True, kw_only=True)
class Programmer:
    """The programmer's state. Immutable: handlers build a new one.

    ``values`` keeps insertion order, and that order is the programmer's
    *target order* (each target where it first got a value): recording lists
    remaining targets in it. ``effects`` are the effect instances, in the
    order they were added, with unique ids; ``stopped`` the ids of those that
    are stopped (GAP-14).
    """

    selection: tuple[TargetRef, ...] = ()
    values: Mapping[SlotKey, ProgSource] = field(default_factory=lambda: MappingProxyType({}))
    effects: tuple[EffectInstance, ...] = ()
    stopped: frozenset[str] = frozenset()
    blind: bool = False
    fadeTime: float = 0.0  # seconds; value changes, clears and blind switches fade over it
    highlight: bool = False

    def same_content(self, other: Programmer) -> bool:
        """Equal selection, values, effects and stopped effects (``blind``,
        ``fadeTime`` and ``highlight`` are modes, not content)."""
        return (
            self.selection == other.selection
            and dict(self.values) == dict(other.values)
            and self.effects == other.effects
            and self.stopped == other.stopped
        )


EMPTY: Final = Programmer()


class Change(NamedTuple):
    """What a programmer command did.

    ``written`` are the keys the command set. Setting a value is the
    operator's latest action even when the value does not change, so the
    session counts these slots as touched: they move on top of any newer
    band-100 source (§8.1, "latest" means the latest action).
    ``writtenEffects`` are the ids of the effect instances it added or
    replaced, touched the same way.
    """

    programmer: Programmer
    message: str
    written: frozenset[SlotKey] = frozenset()
    writtenEffects: frozenset[str] = frozenset()


# ------------------------------------------------------------------ handlers


def handle(
    state: ShowState,
    programmer: Programmer,
    command: Command,
    engine: EngineSnapshot | None = None,
) -> Change:
    """Apply a programmer-class command. Raises
    :class:`~busk.commands.errors.CommandError`.

    ``engine`` is the engine's latest snapshot, if any: ``SELECT_PLAYBACK``
    reads the playback's current cue from it.
    """
    if command["type"] == "SELECT":
        targets = expand(state, command["targets"])
        return _select(programmer, targets, command["mode"])
    if command["type"] == "SELECT_PLAYBACK":
        targets = playback_targets(state, command["playbackId"], engine)
        return _select(programmer, targets, command["mode"])
    if command["type"] == "SET_ATTRIBUTE":
        return _set_attribute(state, programmer, command["attribute"], command["value"])
    if command["type"] == "ADJUST_ATTRIBUTE":
        return _adjust_attribute(state, programmer, command)
    if command["type"] == "APPLY_PRESET":
        return _apply_preset(state, programmer, command["presetId"])
    if command["type"] == "CLEAR_PROGRAMMER":
        cleared = replace(
            programmer, selection=(), values=MappingProxyType({}), effects=(), stopped=frozenset()
        )
        return Change(cleared, "programmer cleared")
    if command["type"] == "ADD_EFFECT":
        return _add_effect(state, programmer, command["effect"])
    if command["type"] == "REMOVE_EFFECT":
        return _remove_effect(programmer, command.get("id"))
    if command["type"] == "RUN_EFFECT":
        return _run_effect(programmer, command["id"], command["on"])
    if command["type"] == "BLIND":
        on = command["on"]
        return Change(replace(programmer, blind=on), f"blind {'on' if on else 'off'}")
    if command["type"] == "PROGRAMMER_FADE":
        time = command["time"]
        return Change(replace(programmer, fadeTime=time), f"programmer fade {time:g} s")
    if command["type"] == "HIGHLIGHT":
        on = command["on"]
        return Change(replace(programmer, highlight=on), f"highlight {'on' if on else 'off'}")
    raise CommandError(f"{command['type']} is not a programmer command")


def expand(state: ShowState, spec: TargetSpec) -> tuple[TargetRef, ...]:
    """A target spec's targets: a group's members in order, or the listed
    targets. Every target must exist."""
    if spec["kind"] == "group":
        group = next((g for g in state.show["groups"] if g["id"] == spec["groupId"]), None)
        if group is None:
            raise CommandError(f"no group {spec['groupId']!r}")
        return tuple(group["members"])
    for target in spec["refs"]:
        problem = state.target_problem(target)
        if problem is not None:
            raise CommandError(problem)
    return tuple(spec["refs"])


def playback_targets(
    state: ShowState, playback_id: PlaybackId, engine: EngineSnapshot | None
) -> tuple[TargetRef, ...]:
    """The targets of a playback's current cue: its tracked state's targets
    (phase-4-plan §5.10).

    The current cue is the one the engine ``snapshot`` shows for the
    playback. An idle playback, a missing snapshot, or a cue number the
    session's show no longer has (the snapshot predates an edit) give the
    first cue's targets, as in Phase 3.
    """
    playback = state.compiled.playbacks.get(playback_id)
    if playback is None:
        raise CommandError(f"no playback {playback_id!r}")
    cue_list = playback.cueList
    status = (
        None if engine is None else next((s for s in engine.playbacks if s.id == playback_id), None)
    )
    index = None if status is None or status.cue is None else cue_list.find(status.cue)
    return cue_list.first.targets if index is None else cue_list.cues[index].targets


def _select(programmer: Programmer, targets: Iterable[TargetRef], mode: str) -> Change:
    """``replace`` sets the selection, ``add`` appends targets not yet
    selected, ``remove`` drops targets; order is kept and duplicates go."""
    if mode == "replace":
        selection = _unique(targets)
    elif mode == "add":
        selection = _unique([*programmer.selection, *targets])
    else:
        dropped = {target_key(target) for target in targets}
        selection = tuple(t for t in programmer.selection if target_key(t) not in dropped)
    count = len(selection)
    return Change(replace(programmer, selection=selection), f"{_plural(count, 'target')} selected")


def _set_attribute(
    state: ShowState, programmer: Programmer, attribute: AttributeId, source: ValueSource
) -> Change:
    definition = _programmable(attribute)
    if not programmer.selection:
        raise CommandError("nothing selected")
    _check_source(state, definition, source)
    values = dict(programmer.values)
    written: set[SlotKey] = set()
    count = len(programmer.selection)
    stored = no_slot = no_value = no_option = 0
    for k, target in enumerate(programmer.selection):
        slot = state.compiled.slots.find(target, attribute)
        if slot is None:
            no_slot += 1
            continue
        if source["kind"] == "preset":
            if state.values.preset_value(source["presetId"], slot) is None:
                no_value += 1
                continue
            values[slot_key(target, attribute)] = PresetSource(
                kind="preset", presetId=source["presetId"]
            )
            written.add(slot_key(target, attribute))
            stored += 1
            continue
        value: AttributeValue | None
        if source["kind"] == "literal":
            value = source["value"]
        elif source["kind"] == "perTarget":
            value = source["values"].get(target_key(target))
        else:
            fraction = spread_fraction(source.get("curve", "linear"), k, count)
            value = spread_value(source["from"], source["to"], fraction)
        if value is None:
            no_value += 1
        elif definition.kind == "discrete" and not offers(slot, cast(DiscreteValue, value)):
            no_option += 1
        else:
            values[slot_key(target, attribute)] = LiteralSource(
                kind="literal", value=deep_copy(value)
            )
            written.add(slot_key(target, attribute))
            stored += 1
    skipped = [
        (no_slot, f"no {attribute}"),
        (no_option, "option not offered"),
        (no_value, "no value"),
    ]
    reasons = ", ".join(f"{n} {why}" for n, why in skipped if n)
    if not stored:
        raise CommandError(f"no selected target takes this {attribute} ({reasons})")
    message = f"{attribute}: {_plural(stored, 'target')}"
    if reasons:
        message += f"; skipped {reasons}"
    return Change(replace(programmer, values=MappingProxyType(values)), message, frozenset(written))


def _adjust_attribute(
    state: ShowState, programmer: Programmer, command: AdjustAttributeCmd
) -> Change:
    """Change the programmer's value of an attribute on each selected target
    that has one: a scalar by ``delta``, within the attribute's range if it
    has one; a colour ``component`` by ``delta`` (from 0 when the colour has
    none, within ``0..1``) or to ``value``, the other components kept. A
    preset reference becomes the literal the preset gives that target,
    changed. Targets without the attribute, or without a value for it, are
    skipped."""
    definition = _programmable(command["attribute"])
    problem = adjustment_problem(definition, command)
    if problem is not None:
        raise CommandError(problem)
    if not programmer.selection:
        raise CommandError("nothing selected")
    attribute = definition.id
    values = dict(programmer.values)
    written: set[SlotKey] = set()
    stored = no_slot = unset = no_value = 0
    for target in programmer.selection:
        slot = state.compiled.slots.find(target, attribute)
        key = slot_key(target, attribute)
        source = programmer.values.get(key)
        if slot is None:
            no_slot += 1
            continue
        if source is None:
            unset += 1
            continue
        if source["kind"] == "literal":
            base: AttributeValue | None = source["value"]
        else:
            base = state.values.preset_value(source["presetId"], slot)
        if base is None:
            no_value += 1  # dormant: the preset no longer defines it here
            continue
        values[key] = LiteralSource(kind="literal", value=_adjusted(definition, base, command))
        written.add(key)
        stored += 1
    skipped = [
        (no_slot, f"no {attribute}"),
        (unset, "not in the programmer"),
        (no_value, "no value"),
    ]
    reasons = ", ".join(f"{n} {why}" for n, why in skipped if n)
    if not stored:
        raise CommandError(f"no selected target has {attribute} to change ({reasons})")
    component = command.get("component")
    name = attribute if component is None else f"{attribute}.{component}"
    message = f"{name}: {_plural(stored, 'target')}"
    if reasons:
        message += f"; skipped {reasons}"
    return Change(replace(programmer, values=MappingProxyType(values)), message, frozenset(written))


_UNIT: Final = ScalarRange(min=0.0, max=1.0)


def _adjusted(
    definition: AttributeDefinition, base: AttributeValue, command: AdjustAttributeCmd
) -> AttributeValue:
    """``base`` changed as ``command`` says (:func:`_adjust_attribute`)."""
    component = command.get("component")
    if component is None:
        return _bounded(cast(float, base) + command["delta"], definition.range)
    color = cast(dict[str, float], deep_copy(base))
    if "value" in command:
        color[component] = command["value"]
    else:
        color[component] = _bounded(color.get(component, 0.0) + command["delta"], _UNIT)
    return cast(ColorValue, color)


def _bounded(number: float, bounds: ScalarRange | None) -> float:
    """``number`` within ``bounds``, if any, and rounded to 9 decimals, so
    that changes in steps record what they add up to (0.35 + 0.05 is 0.4,
    not 0.39999999999999997)."""
    if bounds is not None:
        number = min(max(number, bounds.min), bounds.max)
    return round(number, 9)


def _apply_preset(state: ShowState, programmer: Programmer, preset_id: str) -> Change:
    """Every attribute the preset defines for a selected target (§5.8 lookup)
    becomes a preset reference on that target."""
    preset = next((p for p in state.show["presets"] if p["id"] == preset_id), None)
    if preset is None:
        raise CommandError(f"no preset {preset_id!r}")
    if not programmer.selection:
        raise CommandError("nothing selected")
    defined = {value["attribute"] for value in preset["values"]}
    attributes = [a for a in ATTRIBUTES if a in defined and ATTRIBUTES[a].family != "control"]
    values = dict(programmer.values)
    written: set[SlotKey] = set()
    reached: set[TargetKey] = set()
    for target in programmer.selection:
        for attribute in attributes:
            slot = state.compiled.slots.find(target, attribute)
            if slot is None or state.values.preset_value(preset["id"], slot) is None:
                continue
            values[slot_key(target, attribute)] = PresetSource(kind="preset", presetId=preset["id"])
            written.add(slot_key(target, attribute))
            reached.add(target_key(target))
    stored = len(written)
    if not stored:
        raise CommandError(f"preset {preset['name']!r} defines nothing for the selection")
    message = f"{preset['name']}: {_plural(stored, 'value')} on {_plural(len(reached), 'target')}"
    return Change(replace(programmer, values=MappingProxyType(values)), message, frozenset(written))


def _add_effect(state: ShowState, programmer: Programmer, instance: EffectInstance) -> Change:
    """Add ``instance``, or replace the programmer effect with its ``id`` in
    place (a stopped one stays stopped). It must pass the validator's
    instance rules against the show (template, targets, masters, rate, size,
    range) and have targets."""
    ident = instance["id"]
    errors = [issue for issue in validate_effect(state.show, instance) if issue.severity == "error"]
    if errors:
        raise CommandError(f"effect {ident!r}: {errors[0].message}", errors)
    count = len(expand(state, instance["targets"]))
    if not count:
        raise CommandError(f"effect {ident!r} has no targets")
    effects = list(programmer.effects)
    index = next((i for i, effect in enumerate(effects) if effect["id"] == ident), None)
    stored = cast(EffectInstance, deep_copy(instance))
    if index is None:
        effects.append(stored)
        verb = "added"
    else:
        effects[index] = stored
        verb = "replaced"
    message = f"{verb} effect {ident!r} on {_plural(count, 'target')}"
    if ident in programmer.stopped:
        message += " (stopped)"
    return Change(
        replace(programmer, effects=tuple(effects)), message, writtenEffects=frozenset({ident})
    )


def _remove_effect(programmer: Programmer, ident: str | None) -> Change:
    """Remove the programmer effect ``ident``, or every one when ``None``."""
    if ident is None:
        count = len(programmer.effects)
        cleared = replace(programmer, effects=(), stopped=frozenset())
        return Change(cleared, f"removed {_plural(count, 'effect')}")
    kept = tuple(effect for effect in programmer.effects if effect["id"] != ident)
    if len(kept) == len(programmer.effects):
        raise CommandError(f"the programmer has no effect {ident!r}")
    removed = replace(programmer, effects=kept, stopped=programmer.stopped - {ident})
    return Change(removed, f"removed effect {ident!r}")


def _run_effect(programmer: Programmer, ident: str, on: bool) -> Change:
    """Run the programmer effect ``ident`` again (``on``), or stop it. Either
    one when it already is changes nothing. A started effect counts as
    touched, as an added one does."""
    if not any(effect["id"] == ident for effect in programmer.effects):
        raise CommandError(f"the programmer has no effect {ident!r}")
    stopped = ident in programmer.stopped
    if on != stopped:
        return Change(programmer, f"effect {ident!r} is already {'running' if on else 'stopped'}")
    if on:
        started = replace(programmer, stopped=programmer.stopped - {ident})
        return Change(started, f"started effect {ident!r}", writtenEffects=frozenset({ident}))
    return Change(
        replace(programmer, stopped=programmer.stopped | {ident}), f"stopped effect {ident!r}"
    )


# ------------------------------------------------------------------ checks

_VALUE: Final = TypeAdapter[AttributeValue](AttributeValue, config=STRICT)
_KIND_TEXT: Final = {
    "scalar": "a number",
    "color": "a colour {r, g, b}",
    "discrete": "a discrete value {slot}",
}


def _programmable(attribute: AttributeId) -> AttributeDefinition:
    definition = ATTRIBUTES.get(attribute)
    if definition is None:
        raise CommandError(f"unknown attribute {attribute!r}")
    if definition.family == "control":
        raise CommandError("control attributes cannot be programmed (§5.5)")
    return definition


def check_value(definition: AttributeDefinition, value: object) -> AttributeValue:
    """``value`` if it is a valid value of ``definition``, else a readable error:
    the attribute's shape, finite numbers, normalised scalars and colour
    components within ``0..1``."""
    try:
        checked = _VALUE.validate_json(json.dumps(value), strict=True)
    except (ValidationError, TypeError, ValueError) as exc:
        detail = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
        raise CommandError(f"{definition.id}: {detail}") from None
    if value_kind(checked) != definition.kind:
        raise CommandError(f"{definition.id} needs {_KIND_TEXT[definition.kind]}")
    if definition.kind == "scalar":
        number = cast(float, checked)
        if not math.isfinite(number):
            raise CommandError(f"{definition.id}: Input should be a finite number")
        bounds = definition.range
        if bounds is not None and not bounds.min <= number <= bounds.max:
            raise CommandError(
                f"{definition.id} must be within {bounds.min:g}..{bounds.max:g}, got {number:g}"
            )
    return checked


def _check_source(state: ShowState, definition: AttributeDefinition, source: ValueSource) -> None:
    if source["kind"] == "literal":
        check_value(definition, source["value"])
    elif source["kind"] == "perTarget":
        for value in source["values"].values():
            check_value(definition, value)
    elif source["kind"] == "preset":
        if not any(p["id"] == source["presetId"] for p in state.show["presets"]):
            raise CommandError(f"no preset {source['presetId']!r}")
    else:
        if definition.kind == "discrete":
            raise CommandError(f"{definition.id} is discrete and cannot be spread")
        check_value(definition, source["from"])
        check_value(definition, source["to"])


def offers(slot: Slot, value: DiscreteValue) -> bool:
    """Whether a discrete slot offers ``value`` (its option and, if given, its wheel)."""
    wheel = value.get("wheel")
    return value["slot"] in slot.options and (wheel is None or wheel in slot.wheels)


# --------------------------------------------------------------------- JSON


def to_json(programmer: Programmer) -> dict[str, Any]:
    """The programmer as JSON-shaped data (autosave, ``session.json``)."""
    return {
        "selection": [dict(target) for target in programmer.selection],
        "values": {key: deep_copy(source) for key, source in programmer.values.items()},
        "effects": [deep_copy(effect) for effect in programmer.effects],
        "stopped": [e["id"] for e in programmer.effects if e["id"] in programmer.stopped],
        "blind": programmer.blind,
        "fadeTime": programmer.fadeTime,
        "highlight": programmer.highlight,
    }


_SOURCE: Final = TypeAdapter[ProgSource](ProgSource)
_TARGETS: Final = TypeAdapter(list[TargetRef])
_EFFECT: Final = TypeAdapter[EffectInstance](EffectInstance)


def from_json(data: Any) -> tuple[Programmer, list[str]]:
    """A programmer from :func:`to_json` data, and what had to be dropped.

    Entries that are malformed (a recovered file may come from another
    version) are dropped one by one, never the whole programmer; so is an
    effect whose ``id`` an earlier one has. ``stopped`` keeps the ids of
    the effects kept. Whether the effects still fit the show is the
    caller's check (:func:`drop_invalid_effects`).
    """
    dropped: list[str] = []
    if not isinstance(data, dict):
        return EMPTY, ["programmer: not an object"]
    try:
        selection = _TARGETS.validate_json(json.dumps(data.get("selection", [])), strict=True)
    except (ValidationError, TypeError, ValueError):
        selection, dropped = [], ["programmer.selection"]
    values: dict[SlotKey, ProgSource] = {}
    raw = data.get("values", {})
    for key, source in raw.items() if isinstance(raw, dict) else ():
        try:
            if split_slot_key(key) is None:
                raise ValueError(key)
            values[key] = _SOURCE.validate_json(json.dumps(source), strict=True)
        except (ValidationError, TypeError, ValueError):
            dropped.append(f"programmer.values[{key!r}]")
    effects: dict[str, EffectInstance] = {}
    listed = data.get("effects", [])  # files from before Phase 5 have none
    for i, raw_effect in enumerate(listed if isinstance(listed, list) else ()):
        try:
            effect = _EFFECT.validate_json(json.dumps(raw_effect), strict=True)
        except (ValidationError, TypeError, ValueError):
            dropped.append(f"programmer.effects[{i}]")
            continue
        if effect["id"] in effects:
            dropped.append(f"programmer.effects[{i}] (a second {effect['id']!r})")
        else:
            effects[effect["id"]] = effect
    if not isinstance(listed, list):
        dropped.append("programmer.effects")
    stopped = data.get("stopped", [])  # files from before GAP-14 have none
    if not isinstance(stopped, list) or not all(isinstance(i, str) for i in stopped):
        stopped, dropped = [], [*dropped, "programmer.stopped"]
    blind = data.get("blind") is True
    fade = data.get("fadeTime", 0.0)  # files from before Phase 4 have none
    if not _is_seconds(fade):
        fade, dropped = 0.0, [*dropped, "programmer.fadeTime"]
    programmer = Programmer(
        selection=_unique(selection),
        values=MappingProxyType(values),
        effects=tuple(effects.values()),
        stopped=frozenset(ident for ident in stopped if ident in effects),
        blind=blind,
        fadeTime=float(fade),
        highlight=data.get("highlight") is True,  # files from before Phase 7 have none
    )
    return programmer, dropped


def drop_invalid_effects(state: ShowState, programmer: Programmer) -> tuple[Programmer, list[str]]:
    """``programmer`` without the effects that do not validate against
    ``state``'s show (crash recovery: the show may have changed since), and
    one message per effect dropped, naming its first error. A dropped
    effect is no longer stopped either."""
    kept: list[EffectInstance] = []
    dropped: list[str] = []
    for effect in programmer.effects:
        errors = [i for i in validate_effect(state.show, effect) if i.severity == "error"]
        if errors:
            dropped.append(f"programmer effect {effect['id']!r}: {errors[0].message}")
        else:
            kept.append(effect)
    ids = {effect["id"] for effect in kept}
    return replace(programmer, effects=tuple(kept), stopped=programmer.stopped & ids), dropped


# ------------------------------------------------------------------ helpers


def _is_seconds(value: object) -> bool:
    """Whether ``value`` is a finite, non-negative number of seconds (not a bool)."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _unique(targets: Iterable[TargetRef]) -> tuple[TargetRef, ...]:
    """Targets without duplicates, first occurrence kept."""
    seen: dict[TargetKey, TargetRef] = {}
    for target in targets:
        seen.setdefault(target_key(target), target)
    return tuple(seen.values())


def programmer_targets(values: Iterable[SlotKey]) -> list[TargetRef]:
    """The programmer's target order: each target where it first has a value."""
    seen: dict[TargetKey, TargetRef] = {}
    for key in values:
        split = split_slot_key(key)
        if split is not None:
            seen.setdefault(target_key(split[0]), split[0])
    return list(seen.values())


def drop_missing(state: ShowState, selection: Sequence[TargetRef]) -> tuple[TargetRef, ...]:
    """The selection without targets that no longer exist (after an undo)."""
    return tuple(target for target in selection if state.target_problem(target) is None)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"
