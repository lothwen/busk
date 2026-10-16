"""Recording: programmer → groups, presets and cues (spec §15.3, phase-3-plan §5.5).

Recording turns programmer values into show data that keeps the operator's
*intent*: cue entries reference groups and presets wherever they can (the
§5.9 busking recommendation), so editing a group or retouching a preset
later updates every look recorded with it.

All three record commands are pure functions of the show, the programmer
and the command, returning an :class:`~busk.commands.edits.Edit`. They read
only programmer values whose slot exists in the compiled show; if nothing
in the programmer matches the command's filter, the command fails.

``merge`` decides what happens to an existing destination: absent means
*create* (and fail if it exists, so a typo cannot overwrite anything);
``replace``, ``merge`` and ``remove`` need an existing destination.

**Families.** A preset pool records the families of :data:`POOL_FAMILIES`
(``shutter`` goes with ``beam``; ``control`` never goes anywhere).
``RECORD_CUE.filter`` lists families; without it, every family but
``control`` is recorded.

**RECORD_GROUP.** Members are the selection, in order. ``replace`` sets the
members, ``merge`` appends the selected targets that are not members yet,
``remove`` drops the selected ones. A ``layout`` follows its members to
their new positions, and is dropped (with a warning) if it pointed at a
member that is gone.

**RECORD_PRESET.**

1. Collect each programmer ``(target, attribute) → value`` in the pool's
   families. Preset references are resolved to literal values for their
   target, because presets cannot reference presets (§5.8).
2. Cascade from the requested scope. ``global``: one global value per
   attribute if every target agrees, else fall back to ``profile`` for that
   attribute. ``profile``: one value per (profile, attribute) if that
   profile's targets agree, else fall back to ``target`` values. The message
   reports every fallback (``pan: 4 target values (values differ)``).
3. Write. *create*: a new preset. *replace*: the values become the new
   values. *merge*: new values replace entries with the same (scope,
   attribute); then every *narrower* entry that would shadow a new value for
   a programmer target is removed (target entries of those targets, and
   their profiles' entries when the new value is global); narrower entries
   of other fixtures stay. *remove*: deletes every entry, of any scope, that
   a programmer target sees for a programmer attribute.
4. Values are sorted: registry attribute order, then scope (global,
   profile, target), then profile id or fixture number and element.

**RECORD_CUE.**

1. Collect each programmer ``(target, attribute) → source`` in the filter.
2. Per attribute (registry order), bucket the targets: one bucket per preset
   id, one for literal values (buckets in order of first appearance).
3. Unless ``freeze``, run a **group cover** on each bucket: a group is a
   candidate when its members *that have the attribute* are a non-empty
   subset of the bucket's remaining targets; repeatedly take the candidate
   covering the most targets (ties: fewest members, then lowest number).
   Whatever remains becomes one ``targets`` entry, in programmer order.
4. Sources: ``preset`` for preset buckets; ``literal`` when every target of
   the entry has the same value, ``perTarget`` otherwise.
5. Write into cue ``cueNumber`` (default: the next whole number after the
   last cue, ``"3.5"`` → ``"4"``, or ``"1"``). *create* inserts a new cue in
   number order (named ``Cue <n>``, timing 0 s ``linear``, trigger ``go``);
   *replace* swaps the entries and keeps everything else; *merge* and
   *remove* first **restrict** each existing entry to the targets the
   programmer does not cover for its attribute, then *merge* appends the new
   entries. Restricting leaves an entry alone if none of its targets is
   covered and drops it if all are; otherwise it becomes a ``targets`` entry
   of the uncovered targets: ``literal`` and ``preset`` sources unchanged,
   ``perTarget`` filtered, and a ``spread`` flattened to ``perTarget``
   values computed with each target's index in the *original* expansion, so
   those targets keep exactly the values they had.

**Tracking lists** (phase-4-plan decision 17, §5.12). A cue of a tracking
list stores changes only. Before step 2, the collected values equal to what
the cue would *inherit* are set aside: the same preset reference, or
literals that encode to the same (clamped) lanes. A preset and a literal of
the same colour are not equal, so the reference is kept. What a cue
inherits (:func:`inherited`) is the tracked state of the cue before it,
minus the cue's own ``releases``; a ``block`` cue, a non-tracking list and
the first cue inherit nothing. *merge* still restricts the cue's entries
over every collected value, the set-aside ones included, so an own entry
that now equals the inherited value goes and the slot tracks. The message
counts them: ``recorded cue 9/2: 3 entries; 4 values tracked from cue 9/1``.
*remove* is unchanged.

**Effects** (phase-5-plan §5.11). ``RECORD_CUE`` also copies the
programmer's effect instances into the cue's ``effects``:

- An instance is recorded if any layer of its template is in a filtered
  family; one that no longer validates against the show (dormant) is not.
- Its targets become a ``group`` reference when they are exactly a group's
  members, in order (the lowest group number if several are); a ``group``
  reference stays as it is. Otherwise, and always with ``freeze``, they
  become a ``targets`` list.
- *create* and *replace*: the cue's effects are the programmer's. *merge*:
  by ``id``, an instance replaces the cue's instance in place, or is
  appended. *remove*: the cue's instances whose ``id`` the programmer holds
  are deleted.
- In a tracking list, an instance that compiles to exactly what the cue
  inherits under its ``id`` (the cue before's tracked instance, trimmed by
  the cue's own ``releases``) is left out, and *merge* deletes the cue's own
  instance with that ``id``, so it tracks.

The message counts the cue's effects once any are involved (recorded, or in
the cue before or after the record): ``recorded cue 9/4: 0
entries, 1 effect; 1 effect tracked from cue 9/3``. A record fails only when
neither a value nor an effect matches the filter. ``RECORD_PRESET``
ignores effects.

The cue list must exist; the console creates it in the same ``BATCH``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

from busk.commands.edits import Edit, cue_insert_index, cue_number_key
from busk.commands.errors import CommandError
from busk.commands.patch import Op
from busk.commands.types import RecordCueCmd, RecordGroupCmd, RecordPresetCmd
from busk.compiler.cues import CueCompiler, clamp_lanes, spread_fraction, spread_value
from busk.compiler.effects import CompiledEffect
from busk.compiler.lanes import EncodeError
from busk.compiler.slots import Slot
from busk.model.attributes import ATTRIBUTES, AttributeValue
from busk.model.common import AttributeId, TargetKey, TargetRef, target_key
from busk.model.cue import Cue, CueList, CueRelease
from busk.model.effect import EffectInstance
from busk.model.entry import LiteralSource, PresetSource, TargetSpec, ValueEntry, ValueSource
from busk.model.preset import PresetPool, PresetValue
from busk.model.show import Show
from busk.model.validate import Issue, validate_effect
from busk.session.ids import IdFactory
from busk.session.programmer import Programmer, ProgSource, SlotKey, slot_key, split_slot_key
from busk.session.state import ShowState

_BUSKED: Final = frozenset(
    definition.family for definition in ATTRIBUTES.values() if definition.family != "control"
)

POOL_FAMILIES: Final[Mapping[PresetPool, frozenset[str]]] = {
    "intensity": frozenset({"intensity"}),
    "position": frozenset({"position"}),
    "color": frozenset({"color"}),
    "beam": frozenset({"beam", "shutter"}),
    "focus": frozenset({"focus"}),
    "all": _BUSKED,
}
"""The families each preset pool records (phase-3-plan §5.5; §9 "pools vs families")."""

_ORDER: Final = {attribute: index for index, attribute in enumerate(ATTRIBUTES)}


@dataclass(frozen=True, slots=True)
class _Value:
    """One programmer value whose slot exists."""

    target: TargetRef
    attribute: AttributeId
    source: ProgSource
    slot: Slot

    @property
    def key(self) -> TargetKey:
        return target_key(self.target)


def _collect(state: ShowState, programmer: Programmer, families: Iterable[str]) -> list[_Value]:
    """The programmer's values in ``families`` whose slot exists, in programmer order."""
    wanted = set(families)
    found: list[_Value] = []
    for key, source in programmer.values.items():
        split = split_slot_key(key)
        if split is None:
            continue
        target, attribute = split
        if ATTRIBUTES[attribute].family not in wanted:
            continue
        slot = state.compiled.slots.find(target, attribute)
        if slot is not None:
            found.append(_Value(target, attribute, source, slot))
    return found


def _by_attribute(values: Iterable[_Value]) -> dict[AttributeId, list[_Value]]:
    """Values grouped by attribute, attributes in registry order."""
    grouped: dict[AttributeId, list[_Value]] = {}
    for value in values:
        grouped.setdefault(value.attribute, []).append(value)
    return {attribute: grouped[attribute] for attribute in sorted(grouped, key=_ORDER.__getitem__)}


# --------------------------------------------------------------------- group


def record_group(
    show: Show, programmer: Programmer, command: RecordGroupCmd, ids: IdFactory
) -> Edit:
    """``RECORD_GROUP``: the selection becomes (or edits) group ``number``."""
    number, merge, name = command["number"], command.get("merge"), command.get("name")
    groups = show["groups"]
    index = next((i for i, group in enumerate(groups) if group["number"] == number), None)
    selection = list(programmer.selection)
    if not selection:
        raise CommandError("nothing selected")
    if merge is None:
        if index is not None:
            raise CommandError(f"group {number} exists: add merge or replace")
        group = {
            "id": ids.new("g", {g["id"] for g in groups}),
            "name": name or f"Group {number}",
            "number": number,
            "members": [dict(target) for target in selection],
        }
        message = f"recorded group {number} {group['name']!r}: {_plural(len(selection), 'member')}"
        return Edit(ops=(Op("add", ("groups", len(groups)), group),), message=message)
    if index is None:
        raise CommandError(f"no group {number}")
    current = groups[index]
    old = list(current["members"])
    chosen = {target_key(target) for target in selection}
    if merge == "replace":
        members = selection
    elif merge == "merge":
        present = {target_key(member) for member in old}
        members = old + [t for t in selection if target_key(t) not in present]
    else:
        members = [member for member in old if target_key(member) not in chosen]
    pointer = ("groups", index)
    ops = [Op("replace", (*pointer, "members"), [dict(member) for member in members])]
    if name is not None:
        ops.append(Op("replace", (*pointer, "name"), name))
    warnings: list[Issue] = []
    if "layout" in current:
        layout_op, warning = _relayout(current["layout"], old, members, pointer)
        ops += layout_op
        warnings += warning
    label = current["name"] if name is None else name
    message = f"recorded group {number} {label!r}: {_plural(len(members), 'member')}"
    return Edit(ops=tuple(ops), message=message, warnings=tuple(warnings))


def _relayout(
    layout: Mapping[str, Any],
    old: Sequence[TargetRef],
    new: Sequence[TargetRef],
    pointer: tuple[str | int, ...],
) -> tuple[list[Op], list[Issue]]:
    """Point a group layout's cells at the members' new positions; drop the
    layout if a cell points at a member that is gone."""
    position = {target_key(member): k for k, member in enumerate(new)}
    cells: list[int | None] = []
    for cell in layout["cells"]:
        if cell is None:
            cells.append(None)
            continue
        moved = position.get(target_key(old[cell])) if cell < len(old) else None
        if moved is None:
            path = f"groups[{pointer[1]}].layout"
            message = "layout dropped: it pointed at members that are no longer in the group"
            return [Op("remove", (*pointer, "layout"))], [Issue("warning", path, message)]
        cells.append(moved)
    if cells == list(layout["cells"]):
        return [], []
    return [Op("replace", (*pointer, "layout", "cells"), cells)], []


# -------------------------------------------------------------------- preset


def record_preset(
    state: ShowState,
    show: Show,
    programmer: Programmer,
    command: RecordPresetCmd,
    ids: IdFactory,
) -> Edit:
    """``RECORD_PRESET``: programmer values → a scoped preset (see module docs)."""
    pool, number = command["pool"], command["number"]
    merge, name = command.get("merge"), command.get("name")
    presets = show["presets"]
    index = next(
        (i for i, p in enumerate(presets) if p["pool"] == pool and p["number"] == number), None
    )
    label = f"preset {pool} {number}"
    collected = _collect(state, programmer, POOL_FAMILIES[pool])
    if not collected:
        raise CommandError(
            f"the programmer has no {pool} values"
            if pool != "all"
            else "the programmer has no values"
        )
    profile_of: dict[str, str] = {f["id"]: f["profileId"] for f in show["fixtures"]}
    numbers: dict[str, int] = {f["id"]: f["number"] for f in show["fixtures"]}
    if merge is None and index is not None:
        raise CommandError(f"{label} exists: add merge or replace")
    if merge is not None and index is None:
        raise CommandError(f"no {label}")
    if merge == "remove":
        assert index is not None
        values = _remove_seen(presets[index]["values"], collected, profile_of)
        removed = len(presets[index]["values"]) - len(values)
        ops = [Op("replace", ("presets", index, "values"), values)]
        if name is not None:
            ops.append(Op("replace", ("presets", index, "name"), name))
        return Edit(ops=tuple(ops), message=f"removed {_plural(removed, 'value')} from {label}")
    new_values, notes = _cascade(state, collected, command["scope"], profile_of)
    if not new_values:
        raise CommandError(f"the programmer's {pool} presets define nothing for its targets")

    def order(value: PresetValue) -> tuple[Any, ...]:
        return _preset_order(value, profile_of, numbers)

    if index is None:
        preset = {
            "id": ids.new("pr", {p["id"] for p in presets}),
            "name": name or f"{pool.capitalize()} {number}",
            "number": number,
            "pool": pool,
            "values": sorted(new_values, key=order),
        }
        ops = [Op("add", ("presets", len(presets)), preset)]
        shown = cast(str, preset["name"])
    else:
        existing = presets[index]["values"]
        if merge == "merge":
            merged = _merge_values(existing, new_values, collected, profile_of)
        else:
            merged = new_values
        ops = [Op("replace", ("presets", index, "values"), sorted(merged, key=order))]
        if name is not None:
            ops.append(Op("replace", ("presets", index, "name"), name))
        shown = presets[index]["name"] if name is None else name
    message = f"recorded {label} {shown!r}: {_plural(len(new_values), 'value')}"
    if notes:
        message += "; " + "; ".join(notes)
    return Edit(ops=tuple(ops), message=message)


type _ScopeKey = tuple[str, ...]


def _scope_key(value: PresetValue) -> tuple[_ScopeKey, AttributeId]:
    scope = value["scope"]
    if scope["kind"] == "profile":
        return ("profile", scope["profileId"]), value["attribute"]
    if scope["kind"] == "target":
        return ("target", target_key(scope["target"])), value["attribute"]
    return ("global",), value["attribute"]


def _cascade(
    state: ShowState,
    collected: Sequence[_Value],
    scope: str,
    profile_of: Mapping[str, str],
) -> tuple[list[PresetValue], list[str]]:
    """Steps 1–2: the preset values for ``collected``, cascading from
    ``scope``, and a note for every attribute that fell back."""
    values: list[PresetValue] = []
    notes: list[str] = []
    for attribute, group in _by_attribute(collected).items():
        pairs = [
            (value.target, literal)
            for value in group
            if (literal := _literal(state, value)) is not None
        ]
        if not pairs:
            continue
        if scope == "global" and _agree(value for _, value in pairs):
            values.append(_preset_value({"kind": "global"}, attribute, pairs[0][1]))
            continue
        by_profile: dict[str, list[tuple[TargetRef, AttributeValue]]] = {}
        for target, value in pairs:
            by_profile.setdefault(profile_of[target["fixtureId"]], []).append((target, value))
        profiles = targets = 0
        for profile, members in by_profile.items():
            if scope != "target" and _agree(value for _, value in members):
                values.append(
                    _preset_value(
                        {"kind": "profile", "profileId": profile}, attribute, members[0][1]
                    )
                )
                profiles += 1
                continue
            for target, value in members:
                values.append(
                    _preset_value({"kind": "target", "target": dict(target)}, attribute, value)
                )
                targets += 1
        if scope != "target":
            parts = [
                _plural(count, f"{kind} value")
                for count, kind in ((profiles, "profile"), (targets, "target"))
                if count
            ]
            notes.append(f"{attribute}: {', '.join(parts)} (values differ)")
    return values, notes


def _literal(state: ShowState, value: _Value) -> AttributeValue | None:
    """A programmer value as a literal: preset references resolve for their target."""
    source = value.source
    if source["kind"] == "literal":
        return source["value"]
    return state.values.preset_value(source["presetId"], value.slot)


def _merge_values(
    existing: Sequence[PresetValue],
    new: Sequence[PresetValue],
    collected: Sequence[_Value],
    profile_of: Mapping[str, str],
) -> list[PresetValue]:
    """``merge``: new values win; narrower entries that would shadow a new
    value for a programmer target go."""
    replaced = {_scope_key(value) for value in new}
    targets: dict[AttributeId, list[TargetRef]] = {}
    for value in collected:
        targets.setdefault(value.attribute, []).append(value.target)
    shadowing: set[tuple[_ScopeKey, AttributeId]] = set()
    for written in new:
        attribute, (scope, *rest) = written["attribute"], _scope_key(written)[0]
        for target in targets.get(attribute, []):
            profile = profile_of[target["fixtureId"]]
            if scope == "global":
                shadowing.add((("target", target_key(target)), attribute))
                shadowing.add((("profile", profile), attribute))
            elif scope == "profile" and rest == [profile]:
                shadowing.add((("target", target_key(target)), attribute))
    kept = [
        old
        for old in existing
        if _scope_key(old) not in replaced and _scope_key(old) not in shadowing
    ]
    return kept + list(new)


def _remove_seen(
    existing: Sequence[PresetValue], collected: Sequence[_Value], profile_of: Mapping[str, str]
) -> list[PresetValue]:
    """``remove``: drop every entry a programmer target sees for a programmer attribute."""
    seen: set[tuple[_ScopeKey, AttributeId]] = set()
    for value in collected:
        attribute, target = value.attribute, value.target
        seen.add((("target", target_key(target)), attribute))
        seen.add((("profile", profile_of[target["fixtureId"]]), attribute))
        seen.add((("global",), attribute))
    return [value for value in existing if _scope_key(value) not in seen]


_SCOPE_RANK: Final = {"global": 0, "profile": 1, "target": 2}


def _preset_order(
    value: PresetValue, profile_of: Mapping[str, str], numbers: Mapping[str, int]
) -> tuple[Any, ...]:
    """Step 4: attribute (registry order), scope, then profile id or fixture number and element."""
    scope = value["scope"]
    rank = _SCOPE_RANK[scope["kind"]]
    attribute = _ORDER.get(value["attribute"], len(_ORDER))
    if scope["kind"] == "profile":
        return (attribute, rank, scope["profileId"], 0, 0)
    if scope["kind"] == "target":
        fixture = scope["target"]["fixtureId"]
        return (attribute, rank, "", numbers.get(fixture, 0), scope["target"]["element"])
    return (attribute, rank, "", 0, 0)


def _preset_value(
    scope: dict[str, Any], attribute: AttributeId, value: AttributeValue
) -> PresetValue:
    return cast(PresetValue, {"scope": scope, "attribute": attribute, "value": value})


# ----------------------------------------------------------------------- cue


def record_cue(
    state: ShowState,
    show: Show,
    programmer: Programmer,
    command: RecordCueCmd,
    ids: IdFactory,
) -> Edit:
    """``RECORD_CUE``: programmer values and effects → cue entries and
    effects (see module docs)."""
    lists = show["cueLists"]
    list_index = next((i for i, cl in enumerate(lists) if cl["id"] == command["cueListId"]), None)
    if list_index is None:
        raise CommandError(f"no cue list {command['cueListId']!r}")
    cue_list = lists[list_index]
    cues = cue_list["cues"]
    families = set(command.get("filter", _BUSKED)) - {"control"}
    collected = _collect(state, programmer, families)
    instances = _collect_effects(state, programmer, families)
    if not collected and not instances:
        only = "" if "filter" not in command else " " + "/".join(sorted(families))
        raise CommandError(f"the programmer has no{only} values or effects to record")
    number = command.get("cueNumber") or _next_number(cues)
    key = cue_number_key(number)
    if key is None:
        raise CommandError(f"invalid cue number {number!r}; expected digits like '1' or '1.5'")
    label = f"cue {cue_list['number']}/{number}"
    index = next((i for i, cue in enumerate(cues) if cue_number_key(cue["number"]) == key), None)
    merge, name = command.get("merge"), command.get("name")
    if merge is None and index is not None:
        raise CommandError(f"{label} exists: add merge or replace")
    if merge is not None and index is None:
        raise CommandError(f"no {label}")
    groups = show["groups"]
    freeze = command.get("freeze", False)
    position = cue_insert_index(cues, number) if index is None else index
    existing = None if index is None else cues[index]
    tracked: list[_Value] = []  # values equal to the inherited ones: not stored
    entries: list[ValueEntry] = []
    tracks: set[str] = set()  # ids of instances equal to the inherited ones: not stored
    effects: list[EffectInstance] = []  # the instances to store, targets recorded
    if merge != "remove":
        inherit = _inherits(state, cue_list, position, existing)
        stored: list[_Value] = []
        for value in collected:
            (tracked if _same(state, value, inherit) else stored).append(value)
        entries = build_entries(state, groups, stored, freeze)
        tracks = _equal_effects(
            state, instances, _inherited_effects(state, cue_list, position, existing)
        )
        effects = [
            _recorded_effect(state, groups, instance, freeze)
            for instance in instances
            if instance["id"] not in tracks
        ]
    pointer: tuple[str | int, ...] = ("cueLists", list_index, "cues")
    if existing is None:
        cue = {
            "id": ids.new("c", {c["id"] for cl in lists for c in cl["cues"]}),
            "number": number,
            "name": name or f"Cue {number}",
            "entries": entries,
            "effects": effects,
            "timing": {"fadeIn": 0, "fadeOut": 0, "delayIn": 0, "delayOut": 0, "curve": "linear"},
            "trigger": {"kind": "go"},
        }
        ops = [Op("add", (*pointer, position), cue)]
        count, held = len(entries), effects
    else:
        assert index is not None
        if merge == "replace":
            result, held = entries, effects
        else:
            covers = {(value.key, value.attribute) for value in collected}
            expand = _expander(groups)
            result = [
                kept for entry in existing["entries"] for kept in restrict(entry, covers, expand)
            ] + entries
            held = _merge_effects(existing["effects"], instances, effects)
        ops = [Op("replace", (*pointer, index, "entries"), result)]
        if held != existing["effects"]:
            ops.append(Op("replace", (*pointer, index, "effects"), held))
        if name is not None:
            ops.append(Op("replace", (*pointer, index, "name"), name))
        count = len(result)
    verb = "removed from" if merge == "remove" else "recorded"
    message = f"{verb} {label}: {_plural(count, 'entry', 'entries')}"
    if instances or held or (existing is not None and existing["effects"]):
        message += f", {_plural(len(held), 'effect')}"
    if tracked or tracks:
        source = f"cue {cue_list['number']}/{cues[position - 1]['number']}"
        counts = [
            _plural(n, word) for n, word in ((len(tracked), "value"), (len(tracks), "effect")) if n
        ]
        message += f"; {', '.join(counts)} tracked from {source}"
    return Edit(ops=tuple(ops), message=message)


def _collect_effects(
    state: ShowState, programmer: Programmer, families: Iterable[str]
) -> list[EffectInstance]:
    """The programmer's effect instances with a template layer in
    ``families``, in programmer order; dormant ones (that no longer validate
    against the show) are left out."""
    wanted = set(families)
    templates = {template["id"]: template for template in state.show["effects"]}
    found: list[EffectInstance] = []
    for instance in programmer.effects:
        if any(issue.severity == "error" for issue in validate_effect(state.show, instance)):
            continue  # dormant
        layers = templates[instance["templateId"]]["layers"]
        if any(ATTRIBUTES[layer["attribute"]].family in wanted for layer in layers):
            found.append(instance)
    return found


def _recorded_effect(
    state: ShowState,
    groups: Sequence[Mapping[str, Any]],
    instance: EffectInstance,
    freeze: bool,
) -> EffectInstance:
    """``instance`` as the cue stores it: its targets a group reference when
    they are exactly a group's members, in order (and not ``freeze``), else
    a ``targets`` list."""
    spec = instance["targets"]
    if freeze or spec["kind"] != "group":
        members = list(state.values.expand(spec))
        keys = [target_key(member) for member in members]
        exact = [g for g in groups if [target_key(m) for m in g["members"]] == keys]
        if exact and not freeze:
            spec = {"kind": "group", "groupId": min(exact, key=lambda g: g["number"])["id"]}
        else:
            refs = [dict(member) for member in members]
            spec = cast(TargetSpec, {"kind": "targets", "refs": refs})
    recorded = cast(EffectInstance, dict(instance))
    recorded["targets"] = spec  # in place: the instance keeps its key order
    return recorded


def _merge_effects(
    existing: Sequence[EffectInstance],
    instances: Sequence[EffectInstance],
    stored: Sequence[EffectInstance],
) -> list[EffectInstance]:
    """*merge* and *remove*: the cue's instances without every collected
    ``id`` that is not stored (all of them for *remove*, which stores
    none), then each stored instance in place of the one with its ``id``,
    or appended."""
    stored_ids = {instance["id"] for instance in stored}
    gone = {instance["id"] for instance in instances} - stored_ids
    merged = [instance for instance in existing if instance["id"] not in gone]
    where = {instance["id"]: k for k, instance in enumerate(merged)}
    for instance in stored:
        k = where.get(instance["id"])
        if k is None:
            merged.append(instance)
        else:
            merged[k] = instance
    return merged


def _inherits(
    state: ShowState, cue_list: CueList, position: int, cue: Cue | None
) -> dict[SlotKey, ProgSource]:
    """What a cue at ``position`` of ``cue_list`` would inherit (decision 17):
    nothing in a non-tracking list or for a ``block`` cue; otherwise the
    tracked state before it, minus the cue's own ``releases``. ``cue`` is
    the existing cue there, or ``None`` for a new one."""
    if not _tracks(cue_list, cue):
        return {}
    return inherited(state, cue_list, position, () if cue is None else cue.get("releases", ()))


def _tracks(cue_list: CueList, cue: Cue | None) -> bool:
    """Whether a cue (``None``: a new one) of ``cue_list`` inherits anything."""
    return cue_list["tracking"] and not (cue is not None and cue.get("block", False))


def _inherited_effects(
    state: ShowState, cue_list: CueList, position: int, cue: Cue | None
) -> dict[str, CompiledEffect]:
    """The effect instances a cue at ``position`` would inherit, compiled and
    by ``id``, when it inherits anything (:func:`_inherits`): the tracked
    instances of the cue before it, trimmed by the cue's own ``releases`` as
    :mod:`busk.compiler.tracking` trims them."""
    if position == 0 or not _tracks(cue_list, cue):
        return {}
    compiled = state.compiled.cueLists[cue_list["id"]]
    before = compiled.cues[compiled.byId[cue_list["cues"][position - 1]["id"]]]
    releases = () if cue is None else cue.get("releases", ())
    released = frozenset(slot.index for slot in _released(state, releases).values())
    effects: dict[str, CompiledEffect] = {}
    for effect in before.effects:
        trimmed = effect.without(released, state.compiled.slots)
        if trimmed is not None:
            effects[effect.key] = trimmed
    return effects


def _equal_effects(
    state: ShowState, instances: Sequence[EffectInstance], inherit: Mapping[str, CompiledEffect]
) -> set[str]:
    """The ids of ``instances`` that compile to exactly the instance they
    inherit under their ``id`` (:meth:`CompiledEffect.same`)."""
    if not inherit:
        return set()
    compiler = CueCompiler(state.show, state.compiled.slots)  # its warnings are dropped
    equal: set[str] = set()
    for instance in instances:
        held = inherit.get(instance["id"])
        if held is None:
            continue
        compiled = compiler.effect(instance, "programmer.effects")
        if compiled is not None and held.same(compiled):
            equal.add(instance["id"])
    return equal


def inherited(
    state: ShowState, cue_list: CueList, position: int, releases: Sequence[CueRelease]
) -> dict[SlotKey, ProgSource]:
    """The source each slot inherits at ``position`` of a tracking list: the
    tracked state of cues ``0 … position − 1`` minus ``releases``
    (phase-4-plan §5.12).

    It runs the compiler's tracking rule (:mod:`busk.compiler.tracking`) on
    show data instead of compiled lanes, so preset references survive: each
    entry is flattened to one source per slot, literals, ``perTarget``
    values and spreads as literals, presets as references. A value the
    compiler would drop (no slot, no value for the target, a discrete value
    the target does not offer) is not held. For a cue that does not exist
    yet, ``position`` is its insertion point.
    """
    held: dict[SlotKey, ProgSource] = {}
    for n, cue in enumerate(cue_list["cues"][:position]):
        own = _own_sources(state, cue)
        if n > 0 and not cue.get("block", False):
            gone = _released(state, cue.get("releases", ()))
            own = {key: source for key, source in held.items() if key not in gone} | own
        held = own
    gone = _released(state, releases)
    return {key: source for key, source in held.items() if key not in gone}


def _own_sources(state: ShowState, cue: Cue) -> dict[SlotKey, ProgSource]:
    """A cue's own values as one source per slot; a later entry wins."""
    values = state.values
    own: dict[SlotKey, ProgSource] = {}
    for entry in cue["entries"]:
        attribute, source = entry["attribute"], entry["value"]
        members = values.expand(entry["targets"])
        for k, target in enumerate(members):
            slot = state.compiled.slots.find(target, attribute)
            if slot is None:
                continue
            try:
                if values.resolve(source, slot, k, len(members)) is None:
                    continue  # no value for this target
            except EncodeError:
                continue  # the compiler drops it with a warning
            flat: ProgSource
            if source["kind"] == "preset":
                flat = PresetSource(kind="preset", presetId=source["presetId"])
            elif source["kind"] == "literal":
                flat = LiteralSource(kind="literal", value=source["value"])
            elif source["kind"] == "perTarget":
                flat = LiteralSource(kind="literal", value=source["values"][target_key(target)])
            else:
                fraction = spread_fraction(source.get("curve", "linear"), k, len(members))
                value = spread_value(source["from"], source["to"], fraction)
                flat = LiteralSource(kind="literal", value=value)
            own[slot_key(target, attribute)] = flat
    return own


def _released(state: ShowState, releases: Iterable[CueRelease]) -> dict[SlotKey, Slot]:
    """The slots ``releases`` name, by key, as the compiler expands them
    (:meth:`~busk.compiler.cues.CueCompiler.released`)."""
    slots: dict[SlotKey, Slot] = {}
    for release in releases:
        attributes = release["attributes"]
        names = list(ATTRIBUTES) if attributes == "all" else attributes
        for target in state.values.expand(release["targets"]):
            for attribute in names:
                slot = state.compiled.slots.find(target, attribute)
                if slot is not None:
                    slots[slot_key(target, attribute)] = slot
    return slots


def _same(state: ShowState, value: _Value, inherit: Mapping[SlotKey, ProgSource]) -> bool:
    """Whether a programmer value equals what its slot inherits: the same
    preset, or literals that encode to the same lanes."""
    held = inherit.get(slot_key(value.target, value.attribute))
    if held is None or held["kind"] != value.source["kind"]:
        return False
    if held["kind"] == "preset":
        return held["presetId"] == cast(PresetSource, value.source)["presetId"]
    return _same_lanes(_lanes(state, value.slot, held), _lanes(state, value.slot, value.source))


def _lanes(state: ShowState, slot: Slot, source: ProgSource) -> tuple[float, ...]:
    """The clamped lanes a literal gives ``slot``, as the compiler stores them."""
    lanes = state.values.resolve(source, slot, 0, 1)
    assert lanes is not None  # a literal always has a value
    return clamp_lanes(slot, lanes)


def _same_lanes(a: Sequence[float], b: Sequence[float]) -> bool:
    """Lane-wise equality where ``NaN`` (a colour extra left to derive) equals ``NaN``."""
    return len(a) == len(b) and all(
        x == y or (math.isnan(x) and math.isnan(y)) for x, y in zip(a, b, strict=True)
    )


def _next_number(cues: Sequence[Mapping[str, Any]]) -> str:
    """The next whole number after the last cue (``"3.5"`` → ``"4"``), or ``"1"``."""
    if not cues:
        return "1"
    last = cue_number_key(cues[-1]["number"])
    return str((last[0] if last else 0) + 1)


def build_entries(
    state: ShowState,
    groups: Sequence[Mapping[str, Any]],
    collected: Sequence[_Value],
    freeze: bool,
) -> list[ValueEntry]:
    """Steps 2–4: cue entries for ``collected``, referencing groups and presets."""
    entries: list[ValueEntry] = []
    for attribute, values in _by_attribute(collected).items():
        buckets: dict[str, list[_Value]] = {}
        for value in values:
            source = value.source
            name = f"preset:{source['presetId']}" if source["kind"] == "preset" else "literal"
            buckets.setdefault(name, []).append(value)
        for bucket in buckets.values():
            by_key = {value.key: value for value in bucket}
            remaining = list(by_key)
            chosen = [] if freeze else _group_cover(state, groups, attribute, remaining)
            for group, covered in chosen:
                spec: TargetSpec = {"kind": "group", "groupId": group["id"]}
                entries.append(_entry(spec, attribute, [by_key[k] for k in covered]))
                remaining = [k for k in remaining if k not in covered]
            if remaining:
                refs = [dict(by_key[k].target) for k in remaining]
                spec = cast(TargetSpec, {"kind": "targets", "refs": refs})
                entries.append(_entry(spec, attribute, [by_key[k] for k in remaining]))
    return entries


def _group_cover(
    state: ShowState,
    groups: Sequence[Mapping[str, Any]],
    attribute: AttributeId,
    remaining: Sequence[TargetKey],
) -> list[tuple[Mapping[str, Any], list[TargetKey]]]:
    """Step 3: greedily cover ``remaining`` with groups (see module docs).
    Returns each chosen group with the targets it covers, in member order."""
    left = set(remaining)
    candidates = []
    for group in groups:
        keys: list[TargetKey] = []
        for member in group["members"]:
            key = target_key(member)
            if key not in keys and state.compiled.slots.find(member, attribute) is not None:
                keys.append(key)
        if keys:
            candidates.append((group, keys))
    chosen: list[tuple[Mapping[str, Any], list[TargetKey]]] = []
    while True:
        fitting = [(g, keys) for g, keys in candidates if set(keys) <= left]
        if not fitting:
            return chosen
        group, keys = min(fitting, key=lambda c: (-len(c[1]), len(c[0]["members"]), c[0]["number"]))
        chosen.append((group, keys))
        left -= set(keys)


def _entry(spec: TargetSpec, attribute: AttributeId, values: Sequence[_Value]) -> ValueEntry:
    """Step 4: one entry with a preset, literal or per-target source."""
    first = values[0].source
    source: ValueSource
    if first["kind"] == "preset":
        source = {"kind": "preset", "presetId": first["presetId"]}
    else:
        literals = [cast(AttributeValue, v.source["value"]) for v in values]  # type: ignore[typeddict-item]
        if _agree(literals):
            source = {"kind": "literal", "value": literals[0]}
        else:
            source = {
                "kind": "perTarget",
                "values": {v.key: lit for v, lit in zip(values, literals, strict=True)},
            }
    return {"targets": spec, "attribute": attribute, "value": source}


def _expander(groups: Sequence[Mapping[str, Any]]) -> Callable[[TargetSpec], list[TargetRef]]:
    members = {group["id"]: list(group["members"]) for group in groups}

    def expand(spec: TargetSpec) -> list[TargetRef]:
        if spec["kind"] == "group":
            return members.get(spec["groupId"], [])
        return list(spec["refs"])

    return expand


def restrict(
    entry: ValueEntry,
    covers: set[tuple[TargetKey, AttributeId]],
    expand: Callable[[TargetSpec], list[TargetRef]],
) -> list[ValueEntry]:
    """Restrict an existing entry to the targets the programmer does not cover
    for its attribute: the entry itself, nothing, or a ``targets`` entry."""
    attribute = entry["attribute"]
    targets = expand(entry["targets"])
    covered = [(target_key(t), attribute) in covers for t in targets]
    if not any(covered):
        return [entry]
    if all(covered):
        return []
    uncovered = [t for t, hit in zip(targets, covered, strict=True) if not hit]
    keys = {target_key(t) for t in uncovered}
    source = entry["value"]
    if source["kind"] == "perTarget":
        source = {
            "kind": "perTarget",
            "values": {k: v for k, v in source["values"].items() if k in keys},
        }
    elif source["kind"] == "spread":
        curve, count = source.get("curve", "linear"), len(targets)
        source = {
            "kind": "perTarget",
            "values": {
                target_key(t): spread_value(
                    source["from"], source["to"], spread_fraction(curve, k, count)
                )
                for k, (t, hit) in enumerate(zip(targets, covered, strict=True))
                if not hit
            },
        }
    restricted: dict[str, Any] = {
        "targets": {"kind": "targets", "refs": [dict(t) for t in uncovered]},
        "attribute": attribute,
        "value": source,
    }
    if "timing" in entry:
        restricted["timing"] = entry["timing"]
    return [cast(ValueEntry, restricted)]


# ------------------------------------------------------------------ helpers


def _agree(values: Iterable[AttributeValue]) -> bool:
    """Whether every value equals the first."""
    iterator = iter(values)
    first = next(iterator, None)
    return all(value == first for value in iterator)


def _plural(count: int, word: str, many: str | None = None) -> str:
    return f"{count} {word if count == 1 else many or word + 's'}"
