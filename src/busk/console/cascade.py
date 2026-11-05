"""``delete fixture N cascade`` and ``delete universe N cascade`` (GAP-24 of
``docs/dev/tui/engine-gaps.md``): the edits of one undo step, and the words
for them. A pure function of the show, like the parser that calls it.

A fixture leaves everything that names it: every group's members, every
preset's target values, every cue entry's targets and per-target values,
every cue effect's and release's targets, every park entry and every
binding's command. What that leaves with no target goes too, since it would
mean nothing: an entry, an effect, a release or a binding. A group, a preset
or a cue left empty stays: each is valid, and whether it is still wanted is
the operator's call. What reaches the fixture through a group changes only
as the group does.

A group's layout points at its members by position, so the cells of the
fixture's members go empty and the others follow their members.

A universe unpatches its fixtures, which stay in the show, and takes its
routes with it. A binding that patches a fixture into it goes.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from busk.commands.patch import deep_copy
from busk.commands.types import EditPath
from busk.model.common import parse_target_key
from busk.model.show import Show
from busk.session.programmer import Programmer, split_slot_key

type _Doc = Mapping[str, Any]
"""A part of the show document, or a command."""
type _Change = Callable[[_Doc, str], _Doc | None]
"""What an edit does to one item, given the id that leaves: the item as it
was when it does not name the id, or ``None`` when nothing of it is left."""


@dataclass(frozen=True)
class Cascade:
    """The edits of a delete that cascades, and what to say about them."""

    commands: tuple[_Doc, ...]
    """The edits for one ``BATCH``, the delete last."""
    label: str
    """What the line replies: what it took, counted."""
    question: str
    """What a prompt asks first: what it would take, named."""


def fixture_cascade(show: Show, fixture: _Doc, programmer: Programmer) -> Cascade:
    """``fixture`` leaves ``show``. The question says when ``programmer`` holds it."""
    ident = fixture["id"]
    commands: list[_Doc] = []
    groups = _leave_groups(show, ident, commands)
    presets = _leave_presets(show, ident, commands)
    cues = _leave_cues(show, ident, commands)
    park = [entry for entry in show["park"] if entry["slot"]["target"]["fixtureId"] != ident]
    parked = len(show["park"]) - len(park)
    if parked:
        commands.append(_set(["park"], park))
    bindings = _binding_edits(show, _fixture_command, ident)
    commands += bindings
    commands.append(_delete(["fixtures", {"id": ident}]))

    subject = f"fixture {fixture['number']}"
    others = [_count(parked, "parked value"), _count(len(bindings), "binding")]
    named = [_named("group", sorted(groups)), _named_presets(presets), _named("cue", cues), *others]
    counted = [
        _count(len(groups), "group"),
        _count(len(presets), "preset"),
        _count(len(cues), "cue"),
        *others,
    ]
    question = f"Delete {subject}?{_sentence('It leaves ', named, '; ')}"
    if _held(programmer, ident):
        question += " The programmer holds it."
    return Cascade(tuple(commands), _reply(subject, "left ", counted), question)


def universe_cascade(show: Show, universe: _Doc) -> Cascade:
    """``universe`` goes from ``show``, and its fixtures stay, unpatched."""
    ident = universe["id"]
    fixtures = [
        fixture
        for fixture in show["fixtures"]
        if fixture["patch"] is not None and fixture["patch"]["universeId"] == ident
    ]
    routes = [route for route in show["output"]["routes"] if route["universeId"] == ident]
    bindings = _binding_edits(show, _universe_command, ident)
    commands: list[_Doc] = [
        *({"type": "PATCH_FIXTURE", "fixtureId": f["id"], "patch": None} for f in fixtures),
        *(_delete(["output", "routes", {"id": route["id"]}]) for route in routes),
        *bindings,
        _delete(["universes", {"id": ident}]),
    ]
    subject = f"universe {universe['number']} {json.dumps(universe['name'], ensure_ascii=False)}"
    said = [
        _count(len(fixtures), "fixture loses its patch", "fixtures lose their patch"),
        _count(len(routes), "route goes", "routes go"),
        _count(len(bindings), "binding goes", "bindings go"),
    ]
    counted = [
        _count(len(fixtures), "fixture unpatched", "fixtures unpatched"),
        _count(len(routes), "route gone", "routes gone"),
        _count(len(bindings), "binding gone", "bindings gone"),
    ]
    question = f"Delete {subject}?{_sentence('', said, ', ')}"
    return Cascade(tuple(commands), _reply(subject, "", counted), question)


# ------------------------------------------------------------- a fixture leaves


def _leave_groups(show: Show, ident: str, commands: list[_Doc]) -> list[int]:
    """Edit each group that has ``ident`` for a member; their numbers."""
    numbers: list[int] = []
    for group in show["groups"]:
        members = group["members"]
        moved: dict[int, int] = {}  # a kept member's old position → its new one
        for k, member in enumerate(members):
            if member["fixtureId"] != ident:
                moved[k] = len(moved)
        if len(moved) == len(members):
            continue
        numbers.append(group["number"])
        path: EditPath = ["groups", {"id": group["id"]}]
        commands.append(_set([*path, "members"], [members[k] for k in moved]))
        if "layout" in group:
            cells = [None if c is None else moved.get(c) for c in group["layout"]["cells"]]
            commands.append(_set([*path, "layout", "cells"], cells))
    return numbers


def _leave_presets(show: Show, ident: str, commands: list[_Doc]) -> list[tuple[str, int]]:
    """Edit each preset with a value for a target of ``ident``; their pools and numbers."""
    found: list[tuple[str, int]] = []
    for preset in show["presets"]:
        values = preset["values"]
        kept = [
            value
            for value in values
            if value["scope"]["kind"] != "target" or value["scope"]["target"]["fixtureId"] != ident
        ]
        if len(kept) < len(values):
            found.append((preset["pool"], preset["number"]))
            commands.append(_set(["presets", {"id": preset["id"]}, "values"], kept))
    return found


def _leave_cues(show: Show, ident: str, commands: list[_Doc]) -> list[str]:
    """Edit each cue that names ``ident``; their numbers as ``L/C``."""
    found: list[str] = []
    for cue_list in show["cueLists"]:
        for cue in cue_list["cues"]:
            doc = cast(_Doc, cue)
            path: EditPath = ["cueLists", {"id": cue_list["id"]}, "cues", {"id": cue["id"]}]
            edits = [
                _set([*path, key], kept)
                for key, change in (
                    ("entries", _entry),
                    ("effects", _targeted),
                    ("releases", _targeted),
                )
                if (kept := _edited(doc.get(key, ()), change, ident)) is not None
            ]
            if edits:
                found.append(f"{cue_list['number']}/{cue['number']}")
                commands += edits
    return found


def _entry(entry: _Doc, ident: str) -> _Doc | None:
    targeted = _targeted(entry, ident)
    return None if targeted is None else _with(targeted, "value", _source(entry["value"], ident))


def _targeted(item: _Doc, ident: str) -> _Doc | None:
    """``item``, with ``targets``, left by ``ident``."""
    return _with(item, "targets", _spec(item["targets"], ident))


def _spec(spec: _Doc, ident: str) -> _Doc | None:
    if spec["kind"] == "group":
        return spec  # it follows the group
    refs = [ref for ref in spec["refs"] if ref["fixtureId"] != ident]
    if len(refs) == len(spec["refs"]):
        return spec
    return {**spec, "refs": refs} if refs else None


def _source(source: _Doc, ident: str) -> _Doc | None:
    if source["kind"] != "perTarget":
        return source
    values = {
        key: value
        for key, value in source["values"].items()
        if (ref := parse_target_key(key)) is None or ref["fixtureId"] != ident
    }
    if len(values) == len(source["values"]):
        return source
    return {**source, "values": values} if values else None


def _fixture_command(command: _Doc, ident: str) -> _Doc | None:
    """A binding's command, left by ``ident``."""
    if command["type"] == "SELECT":
        return _targeted(command, ident)
    if command["type"] == "ADD_EFFECT":
        return _with(command, "effect", _targeted(command["effect"], ident))
    if command["type"] == "SET_ATTRIBUTE":
        return _with(command, "value", _source(command["value"], ident))
    if command["type"] == "PATCH_FIXTURE" and command["fixtureId"] == ident:
        return None
    return command


def _held(programmer: Programmer, ident: str) -> bool:
    """Whether ``ident`` is selected, holds a value or is an effect's target."""
    slots = (split_slot_key(key) for key in programmer.values)
    refs = [
        *programmer.selection,
        *(slot[0] for slot in slots if slot is not None),
        *(
            ref
            for effect in programmer.effects
            if effect["targets"]["kind"] == "targets"
            for ref in effect["targets"]["refs"]
        ),
    ]
    return any(ref["fixtureId"] == ident for ref in refs)


# ------------------------------------------------------------- a universe goes


def _universe_command(command: _Doc, ident: str) -> _Doc | None:
    """A binding's command, without a patch into ``ident``."""
    patch = command["patch"] if command["type"] == "PATCH_FIXTURE" else None
    return None if patch is not None and patch["universeId"] == ident else command


# ------------------------------------------------------------------- both


def _binding_edits(show: Show, change: _Change, ident: str) -> list[_Doc]:
    """One edit per binding that ``change`` changes: it goes when nothing of
    its command is left."""
    edits: list[_Doc] = []
    for binding in show["bindings"]:
        action = cast(_Doc, binding["action"])
        if action["kind"] != "command":
            continue
        before = action["command"]
        after = _batched(before, change, ident)
        path: EditPath = ["bindings", {"id": binding["id"]}]
        if after is None:
            edits.append(_delete(path))
        elif after is not before:
            edits.append(_set([*path, "action", "command"], after))
    return edits


def _batched(command: _Doc, change: _Change, ident: str) -> _Doc | None:
    """``change`` on ``command``, or on each command of a ``BATCH``."""
    if command["type"] != "BATCH":
        return change(command, ident)
    commands = _edited(command["commands"], change, ident)
    if commands is None:
        return command
    return {**command, "commands": commands} if commands else None


def _edited(items: Sequence[_Doc], change: _Change, ident: str) -> list[_Doc] | None:
    """What ``change`` leaves of ``items``, or ``None`` when it changes none."""
    kept = [after for item in items if (after := change(item, ident)) is not None]
    same = len(kept) == len(items) and all(a is b for a, b in zip(kept, items, strict=True))
    return None if same else kept


def _with(item: _Doc, key: str, value: _Doc | None) -> _Doc | None:
    """``item`` with ``value`` at ``key``: ``item`` itself when that is what it
    holds, and ``None`` for ``None``."""
    if value is None:
        return None
    return item if value is item[key] else {**item, key: value}


def _set(path: EditPath, value: Any) -> _Doc:
    return {"type": "SET", "path": path, "value": deep_copy(value)}


def _delete(path: EditPath) -> _Doc:
    return {"type": "DELETE", "path": path}


# -------------------------------------------------------------------- words


def _count(count: int, one: str, many: str | None = None) -> str:
    """``2 groups``, ``1 group``, and nothing for none."""
    if not count:
        return ""
    return f"{count} {one if count == 1 else many or f'{one}s'}"


def _named(word: str, names: Sequence[object]) -> str:
    """``groups 1, 4``, ``group 1``, and nothing for none."""
    if not names:
        return ""
    return f"{word}{'' if len(names) == 1 else 's'} {', '.join(str(name) for name in names)}"


def _named_presets(presets: Sequence[tuple[str, int]]) -> str:
    """``presets color 3, position 1, 2``: their numbers under each pool."""
    pools: dict[str, list[int]] = {}
    for pool, number in sorted(presets):
        pools.setdefault(pool, []).append(number)
    names = [f"{pool} {', '.join(map(str, numbers))}" for pool, numbers in pools.items()]
    return f"preset{'' if len(presets) == 1 else 's'} {', '.join(names)}" if names else ""


def _sentence(start: str, parts: Iterable[str], separator: str) -> str:
    """`` It leaves a; b and c.``, of the parts that say something, or nothing."""
    said = [part for part in parts if part]
    if not said:
        return ""
    head = separator.join(said[:-1])
    return f" {start}{f'{head} and ' if head else ''}{said[-1]}."


def _reply(subject: str, start: str, counted: Iterable[str]) -> str:
    """``deleted fixture 101: left 2 groups, 1 cue``, or just the first words."""
    said = ", ".join(part for part in counted if part)
    return f"deleted {subject}: {start}{said}" if said else f"deleted {subject}"
