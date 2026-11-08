"""``delete … cascade`` (GAP-24 and GAP-36 of ``docs/dev/tui/engine-gaps.md``):
the edits of one undo step, and the words for them. A pure function of the
show, like the parser that calls it. The same walk gives the one line a plain
``delete`` of something in use is refused with.

Fixtures leave everything that names them, in one walk however many there are
(``thru``), so a group, a cue or a binding that names several gets one edit. A
later edit would put back what an earlier one took.

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

A preset takes the cue entries that use it and leaves the palettes that name
it, and a cue stays with what is left. It does not write its value into them.
A palette it would leave with no colour stops the line: the validator refuses
such a layer, and a used template is not cascaded.

A group takes the cue entries, effects and releases that target it, and its
group masters. A cue list takes the playbacks that run it, each as ``delete
playback`` does, and leaves their page slots empty. A playback leaves the
slots that hold it, and its cue list stays. A page goes alone: its playbacks
stay. A binding or a command that names what goes, goes too, whichever of
these it is.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from busk.commands.patch import deep_copy
from busk.commands.types import EditPath
from busk.model.common import parse_target_key
from busk.model.show import Show
from busk.session.programmer import Programmer, split_slot_key

type _Doc = Mapping[str, Any]
"""A part of the show document, or a command."""
type _Change[T] = Callable[[_Doc, T], _Doc | None]
"""What an edit does to one item, given what leaves (an id, or several): the
item as it was when it does not name that, or ``None`` when nothing of it is
left."""


@dataclass(frozen=True)
class Cascade:
    """The edits of a delete that cascades, and what to say about them."""

    commands: tuple[_Doc, ...]
    """The edits for one ``BATCH``, the delete last."""
    label: str
    """What the line replies: what it took, counted."""
    question: str
    """What a prompt asks first: what it would take, named."""
    refusal: str | None
    """What a plain ``delete`` says, ``None`` when nothing uses it."""
    blocked: str | None = None
    """Why not even the cascade can run, ``None`` when it can."""


def fixture_cascade(show: Show, fixtures: Sequence[_Doc], programmer: Programmer) -> Cascade:
    """``fixtures``, in number order, leave ``show``. The question says when
    ``programmer`` holds any."""
    gone = {fixture["id"] for fixture in fixtures}
    commands: list[_Doc] = []
    groups = _leave_groups(show, gone, commands)
    presets = _leave_presets(show, gone, commands)
    changes = (("entries", _entry), ("effects", _targeted), ("releases", _targeted))
    cues = _leave_cues(show, gone, commands, changes)
    park = [entry for entry in show["park"] if entry["slot"]["target"]["fixtureId"] not in gone]
    parked = len(show["park"]) - len(park)
    if parked:
        commands.append(_set(["park"], park))
    bindings = _binding_edits(show, _fixture_command, gone)
    commands += bindings
    commands += [_delete(["fixtures", {"id": fixture["id"]}]) for fixture in fixtures]

    several = len(fixtures) > 1
    first, last = fixtures[0]["number"], fixtures[-1]["number"]
    subject = f"{len(fixtures)} fixtures from {first} to {last}" if several else f"fixture {first}"
    others = [_count(parked, "parked value"), _count(len(bindings), "binding")]
    named = [_named("group", sorted(groups)), _named_presets(presets), _named("cue", cues), *others]
    counted = [
        _count(len(groups), "group"),
        _count(len(presets), "preset"),
        _count(len(cues), "cue"),
        *others,
    ]
    question = (
        f"Delete {subject}?{_sentence('They leave ' if several else 'It leaves ', named, '; ')}"
    )
    held = _held(programmer)
    count = sum(fixture["id"] in held for fixture in fixtures)
    if count:
        question += f" The programmer holds {f'{count} of them' if several else 'it'}."
    return Cascade(
        tuple(commands), _reply(subject, "left ", counted), question, _refused(subject, counted)
    )


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
    subject = f"universe {universe['number']} {_quoted(universe['name'])}"
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
    uses = [
        _count(len(fixtures), "fixture"),
        _count(len(routes), "route"),
        _count(len(bindings), "binding"),
    ]
    return Cascade(
        tuple(commands),
        _reply(subject, "", counted),
        question,
        _refused(f"universe {universe['number']}", uses),
    )


def preset_cascade(show: Show, preset: _Doc) -> Cascade:
    """``preset`` goes from ``show``, and from what uses it."""
    ident = preset["id"]
    who = f"preset {preset['pool']} {preset['number']}"
    commands: list[_Doc] = []
    cues = _leave_cues(show, ident, commands, (("entries", _off_preset),))
    templates, blocked = _leave_palettes(show, who, ident, commands)
    bindings = _binding_edits(show, _preset_command, ident)
    commands += bindings
    commands.append(_delete(["presets", {"id": ident}]))
    named = [
        _named("cue", cues),
        _named("effect template", templates),
        _count(len(bindings), "binding"),
    ]
    counted = [
        _count(len(cues), "cue"),
        _count(len(templates), "effect template"),
        _count(len(bindings), "binding"),
    ]
    return _leaves(commands, who, preset, named, counted, blocked=blocked)


def group_cascade(show: Show, group: _Doc) -> Cascade:
    """``group`` goes from ``show``, with what targets it and its masters."""
    ident = group["id"]
    masters = [m for m in show["masters"] if m["kind"] == "group" and m["groupId"] == ident]
    gone = [master["id"] for master in masters]
    commands: list[_Doc] = []
    changes = (("entries", _off_group), ("effects", _off_group), ("releases", _off_group))
    cues = _leave_cues(show, ident, commands, changes)
    bindings = [
        *_binding_edits(show, _group_command(gone), ident),
        *_action_edits(show, lambda a: a["kind"] == "master" and a["masterId"] in gone),
    ]
    commands += bindings
    commands += [_delete(["masters", {"id": master}]) for master in gone]
    commands.append(_delete(["groups", {"id": ident}]))
    named = [
        _named("cue", cues),
        _named("master", [_quoted(master["name"]) for master in masters]),
        _count(len(bindings), "binding"),
    ]
    counted = [
        _count(len(cues), "cue"),
        _count(len(masters), "master"),
        _count(len(bindings), "binding"),
    ]
    return _leaves(commands, f"group {group['number']}", group, named, counted)


def cue_list_cascade(show: Show, cue_list: _Doc, running: Collection[str]) -> Cascade:
    """``cue_list`` goes from ``show``, with the playbacks that run it."""
    ident = cue_list["id"]
    runs = [p for p in show["playbacks"] if p["cueListId"] == ident]
    gone = [playback["id"] for playback in runs]
    numbers = [playback["number"] for playback in runs]
    commands: list[_Doc] = []
    pages, bindings = _leave_playbacks(show, gone, _list_command(gone), ident, commands)
    commands.append(_delete(["cueLists", {"id": ident}]))

    who = f"cue list {cue_list['number']}"
    subject = f"{who} {_quoted(cue_list['name'])}"
    taken = f" and {_named('playback', numbers)}" if numbers else ""
    start = "They leave " if len(numbers) > 1 else "It leaves "
    named = [_named("page", pages), _count(bindings, "binding")]
    counted = [_count(len(pages), "page"), _count(bindings, "binding")]
    uses = [_count(len(runs), "playback"), *counted]
    question = f"Delete {subject}{taken}?{_sentence(start, named, '; ')}{_running(runs, running)}"
    with_them = f"{subject} and {_count(len(runs), 'playback')}" if runs else subject
    return Cascade(
        tuple(commands), _reply(with_them, "left ", counted), question, _refused(who, uses)
    )


def playback_cascade(show: Show, playback: _Doc, running: Collection[str]) -> Cascade:
    """``playback`` goes from ``show``, and its cue list stays."""
    ident = playback["id"]
    commands: list[_Doc] = []
    pages, bindings = _leave_playbacks(show, [ident], _playback_command([ident]), ident, commands)
    named = [_named("page", pages), _count(bindings, "binding")]
    counted = [_count(len(pages), "page"), _count(bindings, "binding")]
    after = _running([playback], running)
    return _leaves(commands, f"playback {playback['number']}", playback, named, counted, after)


def page_cascade(show: Show, page: _Doc) -> Cascade:
    """``page`` goes from ``show``, and its playbacks stay."""
    ident, number = page["id"], page["number"]
    bindings = [
        *_binding_edits(show, _page_command(number), ident),
        *_action_edits(show, lambda a: a["kind"] == "pageAbs" and a["number"] == number),
    ]
    commands = [*bindings, _delete(["pages", {"id": ident}])]
    said = [_count(len(bindings), "binding")]
    return _leaves(commands, f"page {number}", page, said, said)


# ------------------------------------------------------------- a fixture leaves


def _leave_groups(show: Show, gone: Collection[str], commands: list[_Doc]) -> list[int]:
    """Edit each group with a member in ``gone``; their numbers."""
    numbers: list[int] = []
    for group in show["groups"]:
        members = group["members"]
        moved: dict[int, int] = {}  # a kept member's old position → its new one
        for k, member in enumerate(members):
            if member["fixtureId"] not in gone:
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


def _leave_presets(
    show: Show, gone: Collection[str], commands: list[_Doc]
) -> list[tuple[str, int]]:
    """Edit each preset with a value for a target in ``gone``; their pools and numbers."""
    found: list[tuple[str, int]] = []
    for preset in show["presets"]:
        values = preset["values"]
        kept = [
            value
            for value in values
            if value["scope"]["kind"] != "target"
            or value["scope"]["target"]["fixtureId"] not in gone
        ]
        if len(kept) < len(values):
            found.append((preset["pool"], preset["number"]))
            commands.append(_set(["presets", {"id": preset["id"]}, "values"], kept))
    return found


def _leave_cues[T](
    show: Show, ident: T, commands: list[_Doc], changes: Sequence[tuple[str, _Change[T]]]
) -> list[str]:
    """Edit each cue that ``changes`` change, each a key of the cue and what to
    do to its items; their numbers as ``L/C``."""
    found: list[str] = []
    for cue_list in show["cueLists"]:
        for cue in cue_list["cues"]:
            doc = cast(_Doc, cue)
            path: EditPath = ["cueLists", {"id": cue_list["id"]}, "cues", {"id": cue["id"]}]
            edits = [
                _set([*path, key], kept)
                for key, change in changes
                if (kept := _edited(doc.get(key, ()), change, ident)) is not None
            ]
            if edits:
                found.append(f"{cue_list['number']}/{cue['number']}")
                commands += edits
    return found


def _entry(entry: _Doc, gone: Collection[str]) -> _Doc | None:
    targeted = _targeted(entry, gone)
    return None if targeted is None else _with(targeted, "value", _source(entry["value"], gone))


def _targeted(item: _Doc, gone: Collection[str]) -> _Doc | None:
    """``item``, with ``targets``, left by the fixtures ``gone``."""
    return _with(item, "targets", _spec(item["targets"], gone))


def _spec(spec: _Doc, gone: Collection[str]) -> _Doc | None:
    if spec["kind"] == "group":
        return spec  # it follows the group
    refs = [ref for ref in spec["refs"] if ref["fixtureId"] not in gone]
    if len(refs) == len(spec["refs"]):
        return spec
    return {**spec, "refs": refs} if refs else None


def _source(source: _Doc, gone: Collection[str]) -> _Doc | None:
    if source["kind"] != "perTarget":
        return source
    values = {
        key: value
        for key, value in source["values"].items()
        if (ref := parse_target_key(key)) is None or ref["fixtureId"] not in gone
    }
    if len(values) == len(source["values"]):
        return source
    return {**source, "values": values} if values else None


def _fixture_command(command: _Doc, gone: Collection[str]) -> _Doc | None:
    """A binding's command, left by the fixtures ``gone``."""
    if command["type"] == "SELECT":
        return _targeted(command, gone)
    if command["type"] == "ADD_EFFECT":
        return _with(command, "effect", _targeted(command["effect"], gone))
    if command["type"] == "SET_ATTRIBUTE":
        return _with(command, "value", _source(command["value"], gone))
    if command["type"] == "PATCH_FIXTURE" and command["fixtureId"] in gone:
        return None
    return command


def _held(programmer: Programmer) -> set[str]:
    """The fixtures selected, holding a value or the target of an effect."""
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
    return {ref["fixtureId"] for ref in refs}


# ------------------------------------------------------------- a universe goes


def _universe_command(command: _Doc, ident: str) -> _Doc | None:
    """A binding's command, without a patch into ``ident``."""
    patch = command["patch"] if command["type"] == "PATCH_FIXTURE" else None
    return None if patch is not None and patch["universeId"] == ident else command


# ------------------------------------------------------------- a preset goes


def _is_preset(source: _Doc, ident: str) -> bool:
    return bool(source["kind"] == "preset" and source["presetId"] == ident)


def _off_preset(entry: _Doc, ident: str) -> _Doc | None:
    """A cue entry, gone when its value is preset ``ident``."""
    return None if _is_preset(entry["value"], ident) else entry


def _palette(layer: _Doc, ident: str) -> _Doc | None:
    """A template's layer without preset ``ident``; ``None`` when that leaves
    its palette no colour."""
    palette = layer.get("palette")
    if palette is None:
        return layer
    kept = [colour for colour in palette if colour.get("presetId") != ident]
    if len(kept) == len(palette):
        return layer
    return {**layer, "palette": kept} if kept else None


def _leave_palettes(
    show: Show, who: str, ident: str, commands: list[_Doc]
) -> tuple[list[str], str | None]:
    """Edit each template with ``ident`` in a palette; their names, quoted, and
    why the line must stop when a palette would have no colour left."""
    names: list[str] = []
    blocked = None
    for template in show["effects"]:
        layers = _edited(cast(Sequence[_Doc], template["layers"]), _palette, ident)
        if layers is None:
            continue
        name = _quoted(template["name"])
        names.append(name)
        if len(layers) < len(template["layers"]):
            blocked = f"{who} is the last colour of a palette of effect template {name}: "
            blocked += "change the template first"
        commands.append(_set(["effects", {"id": template["id"]}, "layers"], layers))
    return names, blocked


def _preset_command(command: _Doc, ident: str) -> _Doc | None:
    if command["type"] == "APPLY_PRESET" and command["presetId"] == ident:
        return None
    if command["type"] == "SET_ATTRIBUTE" and _is_preset(command["value"], ident):
        return None
    return command


# -------------------------------------------------------------- a group goes


def _is_group(spec: _Doc, ident: str) -> bool:
    return bool(spec["kind"] == "group" and spec["groupId"] == ident)


def _off_group(item: _Doc, ident: str) -> _Doc | None:
    """A cue's entry, effect or release, gone when it targets group ``ident``."""
    return None if _is_group(item["targets"], ident) else item


def _group_command(masters: Collection[str]) -> _Change[str]:
    """What a binding's command does when a group and ``masters`` go."""

    def change(command: _Doc, ident: str) -> _Doc | None:
        kind = command["type"]
        if kind == "SELECT" and _is_group(command["targets"], ident):
            return None
        if kind == "ADD_EFFECT" and _is_group(command["effect"]["targets"], ident):
            return None
        return None if kind == "SET_MASTER" and command["masterId"] in masters else command

    return change


# -------------------------------------------------- a cue list, a playback goes


def _playback_command(playbacks: Collection[str]) -> _Change[str]:
    """What a binding's command does when ``playbacks`` go."""

    def change(command: _Doc, ident: str) -> _Doc | None:
        return None if command.get("playbackId") in playbacks else command

    return change


def _list_command(playbacks: Collection[str]) -> _Change[str]:
    """What a binding's command does when a cue list and ``playbacks`` go."""
    of_playbacks = _playback_command(playbacks)

    def change(command: _Doc, ident: str) -> _Doc | None:
        if command["type"] == "RECORD_CUE" and command["cueListId"] == ident:
            return None
        return of_playbacks(command, ident)

    return change


def _leave_playbacks(
    show: Show, gone: Sequence[str], change: _Change[str], ident: str, commands: list[_Doc]
) -> tuple[list[int], int]:
    """Take ``gone`` off the pages and the bindings, ``change`` deciding for a
    binding's command, and delete them; the numbers of the pages they leave and
    how many bindings change. One edit per page and per binding, whatever
    number of ``gone`` it names."""
    pages: list[int] = []
    for page in show["pages"]:
        if any(slot in gone for slot in page["slots"]):
            pages.append(page["number"])
            slots = [None if slot in gone else slot for slot in page["slots"]]
            commands.append(_set(["pages", {"id": page["id"]}, "slots"], slots))
    bindings = [
        *_binding_edits(show, change, ident),
        *_action_edits(show, lambda a: a["kind"] == "playbackFaderAbs" and a["playbackId"] in gone),
    ]
    commands += bindings
    commands += [_delete(["playbacks", {"id": playback}]) for playback in gone]
    return pages, len(bindings)


def _running(playbacks: Sequence[_Doc], running: Collection[str]) -> str:
    """`` Playbacks 1, 2 are running.``, of those the engine has going, or nothing."""
    numbers = [playback["number"] for playback in playbacks if playback["id"] in running]
    if not numbers:
        return ""
    return f" {_named('Playback', numbers)} {'is' if len(numbers) == 1 else 'are'} running."


# -------------------------------------------------------------- a page goes


def _page_command(number: int) -> _Change[str]:
    """What a binding's command does when page ``number`` goes."""

    def change(command: _Doc, ident: str) -> _Doc | None:
        if command["type"] == "ASSIGN_PLAYBACK" and command["pageId"] == ident:
            return None
        return None if command["type"] == "PAGE" and command.get("number") == number else command

    return change


# ------------------------------------------------------------------- all


def _action_edits(show: Show, goes: Callable[[_Doc], bool]) -> list[_Doc]:
    """One delete per binding whose action ``goes`` says so."""
    return [
        _delete(["bindings", {"id": binding["id"]}])
        for binding in show["bindings"]
        if goes(cast(_Doc, binding["action"]))
    ]


def _binding_edits[T](show: Show, change: _Change[T], ident: T) -> list[_Doc]:
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


def _batched[T](command: _Doc, change: _Change[T], ident: T) -> _Doc | None:
    """``change`` on ``command``, or on each command of a ``BATCH``."""
    if command["type"] != "BATCH":
        return change(command, ident)
    commands = _edited(command["commands"], change, ident)
    if commands is None:
        return command
    return {**command, "commands": commands} if commands else None


def _edited[T](items: Sequence[_Doc], change: _Change[T], ident: T) -> list[_Doc] | None:
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


def _quoted(name: str) -> str:
    return json.dumps(name, ensure_ascii=False)


def _joined(parts: Iterable[str], separator: str) -> str:
    """``a; b and c``, of the parts that say something."""
    said = [part for part in parts if part]
    if not said:
        return ""
    head = separator.join(said[:-1])
    return f"{f'{head} and ' if head else ''}{said[-1]}"


def _sentence(start: str, parts: Iterable[str], separator: str) -> str:
    """`` It leaves a; b and c.``, of the parts that say something, or nothing."""
    joined = _joined(parts, separator)
    return f" {start}{joined}." if joined else ""


def _refused(who: str, uses: Iterable[str]) -> str | None:
    """``group 1 is used by 2 cues and 1 binding: add cascade``, or ``None``."""
    joined = _joined(uses, ", ")
    return f"{who} is used by {joined}: add cascade" if joined else None


def _leaves(
    commands: Sequence[_Doc],
    who: str,
    item: _Doc,
    named: Iterable[str],
    counted: Iterable[str],
    after: str = "",
    *,
    blocked: str | None = None,
) -> Cascade:
    """The words for ``who`` going, named ``item``'s name, and leaving what uses it."""
    counts = list(counted)
    subject = f"{who} {_quoted(item['name'])}"
    question = f"Delete {subject}?{_sentence('It leaves ', named, '; ')}{after}"
    return Cascade(
        tuple(commands), _reply(subject, "left ", counts), question, _refused(who, counts), blocked
    )


def _reply(subject: str, start: str, counted: Iterable[str]) -> str:
    """``deleted fixture 101: left 2 groups, 1 cue``, or just the first words."""
    said = ", ".join(part for part in counted if part)
    return f"deleted {subject}: {start}{said}" if said else f"deleted {subject}"
