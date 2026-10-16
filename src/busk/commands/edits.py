"""Generic show edits → patch ops (phase-3-plan §3 decision 5, §5.1–§5.2).

Recording and patching need real logic and get their own commands; every
other change of the show is one of three generic edits on an id-addressed
:data:`~busk.commands.types.EditPath`, checked afterwards by the validator:

``ADD path value``
    Append an entity (an object with a string ``id``) to the id'd list at
    ``path``. Cues are inserted in cue-number order instead, because a cue
    list's cues must stay sorted.
``SET path value``
    Set the object key that ``path`` ends with. An absent key is added, so
    ``SET`` creates optional keys (``exclusivity``, ``notes``…).
``DELETE path``
    Remove the id'd list element or the object key that ``path`` ends with.
    Removing a required key is caught by validation; references to a deleted
    entity are reported with every path that still uses it (no cascading
    deletes in Phase 3).

Lists without ids (group ``members``, playback ``buttons``, page ``slots``,
preset ``values``, cue ``entries``) are replaced whole, with ``SET``. Ids,
``schemaVersion``, ``meta.id`` and ``meta.created`` are protected
(:func:`~busk.commands.patch.protected_reason`), and the top-level
collections themselves cannot be replaced or deleted.

Two small semantic edits live here too: ``PATCH_FIXTURE`` and
``ASSIGN_PLAYBACK``. Every handler is a pure function of the current show and
the command, returning an :class:`Edit`; the session applies, validates,
compiles and commits it (or rejects it, changing nothing).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from busk.commands.errors import CommandError
from busk.commands.patch import Op, exists, get, pointer_text, protected_reason, resolve
from busk.commands.types import (
    AddCmd,
    AssignPlaybackCmd,
    DeleteCmd,
    IdSegment,
    PatchFixtureCmd,
    SetCmd,
)
from busk.model.show import Show
from busk.model.validate import Issue

COLLECTIONS: Final = frozenset(
    {
        "profiles", "universes", "fixtures", "groups", "presets", "effects", "cueLists",
        "playbacks", "pages", "masters", "surfaces", "bindings", "park",
    }
)  # fmt: skip
"""The show's top-level lists."""


@dataclass(frozen=True, kw_only=True)
class Edit:
    """What a show-edit handler produces: the ops, and how to report them.

    ``message`` is the one-line result (``Recorded cue 10/1: 2 entries``),
    also used as the undo step's label; ``warnings`` are reported with it
    when the edit is committed.
    """

    ops: tuple[Op, ...]
    message: str
    warnings: tuple[Issue, ...] = ()


def add(show: Show, command: AddCmd) -> Edit:
    """``ADD``: append an entity to the id'd list at ``path``."""
    path = command["path"]
    pointer = resolve(show, path)
    if not exists(show, pointer):
        raise CommandError(f"{pointer_text(pointer)} does not exist")
    items = get(show, pointer)
    if not isinstance(items, list):
        raise CommandError(f"{pointer_text(pointer)} is not a list")
    value = command["value"]
    if not isinstance(value, dict) or not isinstance(value.get("id"), str):
        raise CommandError("ADD needs an object with a string 'id'")
    index = len(items)
    if pointer[-1] == "cues" and len(pointer) == 3 and pointer[0] == "cueLists":
        index = cue_insert_index(items, value.get("number"))
    what = _SINGULAR.get(str(pointer[-1]), f"an element to {pointer_text(pointer)}")
    name = value.get("name")
    label = repr(name) if isinstance(name, str) and name else value["id"]
    return Edit(ops=(Op("add", (*pointer, index), value),), message=f"added {what} {label}")


def set_(show: Show, command: SetCmd) -> Edit:
    """``SET``: set (or create) the object key that ``path`` ends with."""
    path = command["path"]
    _check_key_path(path, "SET")
    pointer = resolve(show, path)
    if exists(show, pointer):
        op = Op("replace", pointer, command["value"])
    else:
        op = Op("add", pointer, command["value"])  # resolve() checked the parent is an object
    return Edit(ops=(op,), message=f"set {pointer_text(pointer)} to {_short(command['value'])}")


def delete(show: Show, command: DeleteCmd) -> Edit:
    """``DELETE``: remove the list element or the key that ``path`` ends with."""
    path = command["path"]
    if not path:
        raise CommandError("DELETE needs a path")
    if isinstance(path[-1], str):
        _check_key_path(path, "DELETE")
        if len(path) == 1:
            raise CommandError(f"the show's {path[0]!r} cannot be deleted")
    pointer = resolve(show, path)
    if not exists(show, pointer):
        raise CommandError(f"{pointer_text(pointer)} does not exist")
    return Edit(ops=(Op("remove", pointer),), message=f"deleted {pointer_text(pointer)}")


def patch_fixture(show: Show, command: PatchFixtureCmd) -> Edit:
    """``PATCH_FIXTURE``: set a fixture's patch, or unpatch it with ``null``."""
    index = _index_of(show["fixtures"], command["fixtureId"], "fixture")
    fixture = show["fixtures"][index]
    patch = command["patch"]
    if patch is None:
        message = f"unpatched fixture {fixture['number']}"
    else:
        universe = next((u for u in show["universes"] if u["id"] == patch["universeId"]), None)
        where = universe["number"] if universe is not None else repr(patch["universeId"])
        message = f"patched fixture {fixture['number']} at {where}.{patch['address']}"
    return Edit(ops=(Op("replace", ("fixtures", index, "patch"), patch),), message=message)


def assign_playback(show: Show, command: AssignPlaybackCmd) -> Edit:
    """``ASSIGN_PLAYBACK``: put a playback in a page slot, or empty the slot.

    The page's ``slots`` are extended with empty slots up to ``slot``.
    """
    index = _index_of(show["pages"], command["pageId"], "page")
    page = show["pages"][index]
    slot = command["slot"]
    slots: list[Any] = list(page["slots"])
    if len(slots) <= slot:
        slots.extend([None] * (slot + 1 - len(slots)))
    slots[slot] = command["playbackId"]
    if command["playbackId"] is None:
        message = f"emptied slot {slot + 1} of page {page['number']}"
    else:
        playback = next((p for p in show["playbacks"] if p["id"] == command["playbackId"]), None)
        name = playback["number"] if playback is not None else repr(command["playbackId"])
        message = f"playback {name} on slot {slot + 1} of page {page['number']}"
    return Edit(ops=(Op("replace", ("pages", index, "slots"), slots),), message=message)


# ------------------------------------------------------------------ helpers

_SINGULAR: Final = {
    "profiles": "profile",
    "universes": "universe",
    "fixtures": "fixture",
    "groups": "group",
    "presets": "preset",
    "effects": "effect template",
    "cueLists": "cue list",
    "cues": "cue",
    "playbacks": "playback",
    "pages": "page",
    "masters": "master",
    "surfaces": "surface",
    "bindings": "binding",
    "routes": "route",
}
"""How ``ADD`` messages name what they added, by the list's key."""

_CUE_NUMBER: Final = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def cue_number_key(number: object) -> tuple[int, ...] | None:
    """A cue number as an integer tuple (``"1.10"`` → ``(1, 10)``), or ``None``."""
    if not isinstance(number, str) or _CUE_NUMBER.fullmatch(number) is None:
        return None
    return tuple(int(part) for part in number.split("."))


def cue_insert_index(cues: Sequence[Mapping[str, Any]], number: object) -> int:
    """Where a cue numbered ``number`` goes to keep ``cues`` sorted (the end
    if the number is not a valid cue number: validation reports it)."""
    key = cue_number_key(number)
    if key is None:
        return len(cues)
    for index, cue in enumerate(cues):
        other = cue_number_key(cue.get("number"))
        if other is not None and other > key:
            return index
    return len(cues)


def _check_key_path(path: Sequence[str | IdSegment], verb: str) -> None:
    """Check a ``SET``/``DELETE`` path that ends at an object key."""
    if not path or not isinstance(path[-1], str):
        raise CommandError(f"{verb} needs a path that ends with an object key")
    reason = protected_reason(path)
    if reason is not None:
        raise CommandError(reason)
    if len(path) == 1 and path[0] in COLLECTIONS and path[0] != "park":
        # Park entries have no ids, so ADD and DELETE cannot address them: the
        # park list is replaced as a whole (Phase 7).
        raise CommandError(f"the {path[0]} list cannot be replaced; ADD or DELETE its elements")


def _short(value: Any, limit: int = 60) -> str:
    """A JSON value for a message, cut to ``limit`` characters."""
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _index_of(items: Sequence[Mapping[str, Any]], ident: str, what: str) -> int:
    for index, item in enumerate(items):
        if item["id"] == ident:
            return index
    raise CommandError(f"no {what} {ident!r}")
