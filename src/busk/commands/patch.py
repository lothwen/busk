"""JSON patches on the show tree, copy-on-write (spec §15.4, phase-3-plan §5.2).

Every show edit becomes a list of :class:`Op`\\ s, the three JSON Patch
operations the edits need:

==========  =====================================  ==========================
op          does                                   inverse
==========  =====================================  ==========================
``add``     inserts into a list at an index (the   ``remove`` at that pointer
            end is ``len``), or adds a *new* key
``remove``  removes a list element or a key        ``add`` of the old value
``replace`` replaces a list element or a key's     ``replace`` with the old
            value                                  value
==========  =====================================  ==========================

A **pointer** addresses a node by keys and list indices from the root,
e.g. ``("cueLists", 0, "cues", 1, "timing", "fadeIn")``. Pointers are what
ops carry; commands address the show with id-based
:data:`~busk.commands.types.EditPath`\\ s instead, which :func:`resolve`
turns into pointers against the current show.

**Copy-on-write.** :func:`apply` never mutates its input. It shallow-copies
only the containers on each op's path (each container at most once per call)
and leaves every other subtree in place, so an untouched subtree of the new
show *is* the corresponding object of the old show. That makes an edit cheap
however big the show is, lets the validator find the touched entities by
identity, and makes a snapshot taken before an edit stay valid after it.
Inserted values are deep-copied, so a caller cannot reach into the store
afterwards.

**Inverses** are captured while applying, from the values actually replaced
or removed, and returned in reverse order: applying them to exactly the show
the forward ops produced gives back a show deep-equal to the original. The
session's linear undo timeline guarantees that "exactly".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from busk.commands.errors import CommandError
from busk.commands.types import IdSegment
from busk.model.validate import join_path

type Pointer = tuple[str | int, ...]
"""Keys and list indices from the show root to a node."""

type OpName = Literal["add", "remove", "replace"]


@dataclass(frozen=True, slots=True)
class Op:
    """One patch operation. ``value`` is unused by ``remove``."""

    op: OpName
    path: Pointer
    value: Any = None


def pointer_text(pointer: Sequence[str | int]) -> str:
    """A pointer written like an issue path: ``cueLists[0].cues[1].timing``."""
    text = ""
    for segment in pointer:
        text = join_path(text, segment)
    return text or "the show"


def resolve(doc: Mapping[str, Any], path: Sequence[str | IdSegment]) -> Pointer:
    """Turn an edit path into a pointer against ``doc``.

    A string segment must be a key of the object it is applied to, except the
    last one, which may name a key that does not exist yet (``SET`` creates
    optional keys; the caller decides). An :class:`IdSegment` must be applied
    to a list and match exactly one element's ``id`` (the first one if ids
    repeat, which validation forbids).

    Raises :class:`~busk.commands.errors.CommandError` naming the path where
    the walk failed.
    """
    pointer: list[str | int] = []
    node: Any = doc
    for position, segment in enumerate(path):
        where = pointer_text(pointer)
        if isinstance(segment, str):
            if not isinstance(node, dict):
                raise CommandError(f"{where} is not an object, so it has no key {segment!r}")
            pointer.append(segment)
            if segment not in node:
                if position == len(path) - 1:
                    return tuple(pointer)
                raise CommandError(f"{where} has no key {segment!r}")
            node = node[segment]
        else:
            if not isinstance(node, list):
                raise CommandError(f"{where} is not a list, so it has no element with an id")
            ident = segment["id"]
            matches = (k for k, item in enumerate(node) if _id_of(item) == ident)
            index = next(matches, None)
            if index is None:
                raise CommandError(f"{where} has no element with id {ident!r}")
            pointer.append(index)
            node = node[index]
    return tuple(pointer)


_PROTECTED: tuple[tuple[str, ...], ...] = (("schemaVersion",), ("meta", "id"), ("meta", "created"))


def protected_reason(path: Sequence[str | IdSegment]) -> str | None:
    """Why ``SET``/``DELETE`` may not touch ``path``, or ``None`` if they may.

    Protected are ids (any path ending at an ``id`` key: ids are immutable,
    §5.1), ``schemaVersion`` (only migrations change it, §17), ``meta.id``
    (it names the show's autosave folder) and ``meta.created``, plus any
    container holding one of them, so ``SET ["meta"]`` cannot sidestep the
    rule.
    """
    if path and path[-1] == "id":
        return "ids cannot be changed"
    if all(isinstance(segment, str) for segment in path):
        keys = tuple(cast(str, segment) for segment in path)
        for protected in _PROTECTED:
            if protected[: len(keys)] == keys:
                return f"{'.'.join(protected)} cannot be changed"
    return None


def get(doc: Any, pointer: Sequence[str | int]) -> Any:
    """The node at ``pointer`` (``KeyError`` / ``IndexError`` if it is not there)."""
    node = doc
    for segment in pointer:
        node = node[segment]
    return node


def exists(doc: Any, pointer: Sequence[str | int]) -> bool:
    """Whether ``pointer`` names a node of ``doc``."""
    node = doc
    for segment in pointer:
        node = _lookup(node, segment)
        if node is _MISSING:
            return False
    return True


def apply[T: Mapping[str, Any]](doc: T, ops: Sequence[Op]) -> tuple[T, list[Op]]:
    """Apply ``ops`` in order to a copy-on-write copy of ``doc``.

    Returns the new document and the inverse ops (already in reverse order).
    ``doc`` itself is never mutated. Raises
    :class:`~busk.commands.errors.CommandError` when an op does not fit the
    document (a missing key, an index out of range, an ``add`` of a key that
    exists); the caller then discards the partial result, so nothing changes.
    """
    root: dict[str, Any] = dict(doc)
    fresh = {id(root)}  # containers created by this call: mutable in place
    inverse: list[Op] = []
    for op in ops:
        if not op.path:
            raise CommandError("an edit cannot replace the whole show")
        parent: Any = root
        for depth, segment in enumerate(op.path[:-1]):
            child = _child(parent, segment, op.path[: depth + 1])
            if id(child) not in fresh:
                child = _shallow(child, op.path[: depth + 1])
                parent[segment] = child
                fresh.add(id(child))
            parent = child
        inverse.append(_apply_one(parent, op))
    inverse.reverse()
    return cast(T, root), inverse


def deep_copy(value: Any) -> Any:
    """A deep copy of JSON-shaped data (dicts, lists, tuples, scalars)."""
    if isinstance(value, dict):
        return {key: deep_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [deep_copy(item) for item in value]
    if isinstance(value, tuple):
        return tuple(deep_copy(item) for item in value)
    return value


# ------------------------------------------------------------------ helpers


_MISSING: Any = object()


def _lookup(node: Any, segment: str | int) -> Any:
    """``node[segment]`` for a key of a dict or an index of a list, else :data:`_MISSING`."""
    if isinstance(node, dict) and isinstance(segment, str):
        return node.get(segment, _MISSING)
    if isinstance(node, list) and isinstance(segment, int) and 0 <= segment < len(node):
        return node[segment]
    return _MISSING


def _id_of(item: Any) -> Any:
    return item.get("id") if isinstance(item, dict) else None


def _child(parent: Any, segment: str | int, pointer: Pointer) -> Any:
    """The child of ``parent`` at ``segment``, or a readable error."""
    child = _lookup(parent, segment)
    if child is _MISSING:
        raise CommandError(f"{pointer_text(pointer)} does not exist")
    return child


def _shallow(container: Any, pointer: Pointer) -> Any:
    """A shallow copy of a container on an op's path."""
    if isinstance(container, dict):
        return dict(container)
    if isinstance(container, list):
        return list(container)
    raise CommandError(f"{pointer_text(pointer)} is not an object or a list")


def _apply_one(parent: Any, op: Op) -> Op:
    """Apply ``op`` to its (fresh) parent container; return its inverse."""
    key = op.path[-1]
    where = pointer_text(op.path)
    if isinstance(parent, list):
        if not isinstance(key, int):
            raise CommandError(f"{pointer_text(op.path[:-1])} is a list; {key!r} is not an index")
        if op.op == "add":
            if not 0 <= key <= len(parent):
                raise CommandError(f"cannot insert at {where}: the list has {len(parent)} items")
            parent.insert(key, deep_copy(op.value))
            return Op("remove", op.path)
        if not 0 <= key < len(parent):
            raise CommandError(f"{where} does not exist")
        if op.op == "remove":
            return Op("add", op.path, parent.pop(key))
        old = parent[key]
        parent[key] = deep_copy(op.value)
        return Op("replace", op.path, old)
    if not isinstance(parent, dict) or not isinstance(key, str):
        raise CommandError(f"{pointer_text(op.path[:-1])} is not an object")
    if op.op == "add":
        if key in parent:
            raise CommandError(f"{where} already exists")
        parent[key] = deep_copy(op.value)
        return Op("remove", op.path)
    if key not in parent:
        raise CommandError(f"{where} does not exist")
    if op.op == "remove":
        return Op("add", op.path, parent.pop(key))
    old = parent[key]
    parent[key] = deep_copy(op.value)
    return Op("replace", op.path, old)
