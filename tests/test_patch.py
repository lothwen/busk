"""Copy-on-write JSON patches: inverses, structural sharing, id paths (phase-3-plan §5.2)."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from busk.commands.errors import CommandError
from busk.commands.patch import Op, apply, deep_copy, get, protected_reason, resolve
from busk.commands.types import IdSegment


def doc() -> dict[str, Any]:
    return {
        "meta": {"id": "show", "title": "T"},
        "fixtures": [
            {"id": "fx-1", "name": "A", "patch": {"universeId": "u1", "address": 1}},
            {"id": "fx-2", "name": "B", "patch": None},
        ],
        "cueLists": [
            {"id": "cl-1", "cues": [{"id": "c-1", "timing": {"fadeIn": 0.0}, "range": (0, 255)}]}
        ],
    }


CASES: list[tuple[str, list[Op]]] = [
    ("replace a dict key", [Op("replace", ("meta", "title"), "New")]),
    ("add a dict key", [Op("add", ("meta", "notes"), "hi")]),
    ("remove a dict key", [Op("remove", ("fixtures", 0, "patch"))]),
    ("replace a list element", [Op("replace", ("fixtures", 1), {"id": "fx-2", "name": "C"})]),
    ("insert into a list", [Op("add", ("fixtures", 1), {"id": "fx-9"})]),
    ("append to a list", [Op("add", ("fixtures", 2), {"id": "fx-9"})]),
    ("remove a list element", [Op("remove", ("fixtures", 0))]),
    (
        "several ops in one container",
        [
            Op("replace", ("fixtures", 0, "name"), "X"),
            Op("add", ("fixtures", 0, "notes"), "n"),
            Op("remove", ("fixtures", 1)),
            Op("replace", ("fixtures", 0, "patch", "address"), 5),
        ],
    ),
    (
        "an op inside a value an earlier op inserted",
        [
            Op("add", ("fixtures", 0), {"id": "fx-0", "patch": {"address": 1}}),
            Op("replace", ("fixtures", 0, "patch", "address"), 7),
            Op("remove", ("fixtures", 1, "patch")),
        ],
    ),
    (
        "a removal after an edit inside the removed node",
        [Op("replace", ("fixtures", 0, "name"), "Z"), Op("remove", ("fixtures", 0))],
    ),
]


@pytest.mark.parametrize("ops", [ops for _, ops in CASES], ids=[name for name, _ in CASES])
def test_inverse_ops_restore_the_original(ops: list[Op]) -> None:
    original = doc()
    snapshot = copy.deepcopy(original)
    edited, inverse = apply(original, ops)
    assert original == snapshot  # the input is never mutated
    assert edited != original
    restored, again = apply(edited, inverse)
    assert restored == original
    # Re-applying the inverse of the inverse redoes the edit.
    assert apply(restored, again)[0] == edited


def test_untouched_subtrees_are_the_same_objects() -> None:
    original = doc()
    edited, _ = apply(original, [Op("replace", ("fixtures", 0, "patch", "address"), 9)])
    assert edited["meta"] is original["meta"]
    assert edited["cueLists"] is original["cueLists"]
    assert edited["fixtures"] is not original["fixtures"]
    assert edited["fixtures"][1] is original["fixtures"][1]
    assert edited["fixtures"][0] is not original["fixtures"][0]
    assert edited["fixtures"][0]["patch"]["address"] == 9
    assert original["fixtures"][0]["patch"]["address"] == 1


def test_inserted_values_are_copied() -> None:
    value = {"id": "fx-9", "patch": {"address": 3}}
    edited, _ = apply(doc(), [Op("add", ("fixtures", 2), value)])
    value["patch"]["address"] = 400  # the caller mutates its dict afterwards
    assert edited["fixtures"][2]["patch"]["address"] == 3


def test_a_snapshot_is_unchanged_by_later_edits() -> None:
    first, _ = apply(doc(), [Op("replace", ("meta", "title"), "One")])
    snapshot = copy.deepcopy(first)
    second, _ = apply(first, [Op("remove", ("fixtures", 0)), Op("add", ("meta", "x"), 1)])
    assert first == snapshot
    assert second["meta"] == {"id": "show", "title": "One", "x": 1}


def test_tuples_survive_and_are_copied() -> None:
    edited, _ = apply(doc(), [Op("add", ("meta", "range"), (1, 2))])
    assert edited["meta"]["range"] == (1, 2)
    assert deep_copy({"a": [(1, [2])]}) == {"a": [(1, [2])]}


@pytest.mark.parametrize(
    ("ops", "message"),
    [
        ([Op("replace", ("meta", "nope", "x"), 1)], "meta.nope does not exist"),
        ([Op("remove", ("fixtures", 5))], "fixtures[5] does not exist"),
        ([Op("add", ("fixtures", 3), {})], "cannot insert at fixtures[3]: the list has 2 items"),
        ([Op("add", ("meta", "title"), "x")], "meta.title already exists"),
        ([Op("replace", ("meta", "title", "x"), 1)], "meta.title is not an object or a list"),
        ([Op("replace", ("fixtures", "a"), 1)], "fixtures is a list; 'a' is not an index"),
        ([Op("replace", (), 1)], "an edit cannot replace the whole show"),
    ],
)
def test_ops_that_do_not_fit_raise(ops: list[Op], message: str) -> None:
    original = doc()
    with pytest.raises(CommandError) as raised:
        apply(original, ops)
    assert raised.value.message == message
    assert original == doc()


# -------------------------------------------------------------- edit paths


def test_id_segments_resolve_to_indices() -> None:
    path = ["cueLists", IdSegment(id="cl-1"), "cues", IdSegment(id="c-1"), "timing", "fadeIn"]
    pointer = resolve(doc(), path)
    assert pointer == ("cueLists", 0, "cues", 0, "timing", "fadeIn")
    assert get(doc(), pointer) == 0.0
    assert resolve(doc(), ["fixtures", IdSegment(id="fx-2")]) == ("fixtures", 1)
    # The last key may be new: SET creates optional keys.
    assert resolve(doc(), ["fixtures", IdSegment(id="fx-2"), "notes"]) == ("fixtures", 1, "notes")


@pytest.mark.parametrize(
    ("path", "message"),
    [
        (["fixtures", IdSegment(id="fx-9")], "fixtures has no element with id 'fx-9'"),
        (["nope", "x"], "the show has no key 'nope'"),
        (["meta", IdSegment(id="x")], "meta is not a list, so it has no element with an id"),
        (["fixtures", "name"], "fixtures is not an object, so it has no key 'name'"),
        (
            ["cueLists", IdSegment(id="cl-1"), "cues", IdSegment(id="c-7"), "timing"],
            "cueLists[0].cues has no element with id 'c-7'",
        ),
    ],
)
def test_unresolvable_paths_raise(path: list[Any], message: str) -> None:
    with pytest.raises(CommandError) as raised:
        resolve(doc(), path)
    assert raised.value.message == message


@pytest.mark.parametrize(
    ("path", "protected"),
    [
        (["schemaVersion"], True),
        (["meta", "id"], True),
        (["meta", "created"], True),
        (["meta"], True),  # holds meta.id
        (["fixtures", IdSegment(id="fx-1"), "id"], True),
        (["cueLists", IdSegment(id="cl-1"), "cues", IdSegment(id="c-1"), "id"], True),
        (["meta", "title"], False),
        (["meta", "modified"], False),
        (["fixtures", IdSegment(id="fx-1"), "name"], False),
        (["fixtures", IdSegment(id="fx-1")], False),
    ],
)
def test_protected_paths(path: list[Any], protected: bool) -> None:
    assert (protected_reason(path) is not None) == protected


# -------------------------------------------------------------- properties

KEYS = ("a", "b", "c")
scalars = st.one_of(st.integers(-5, 5), st.text(max_size=2), st.none(), st.booleans())
values = st.recursive(
    scalars,
    lambda inner: st.one_of(
        st.lists(inner, max_size=3), st.dictionaries(st.sampled_from(KEYS), inner, max_size=3)
    ),
    max_leaves=8,
)


def _containers(node: Any, pointer: tuple[str | int, ...] = ()) -> list[tuple[Any, ...]]:
    found: list[tuple[Any, ...]] = [(pointer, node)]
    if isinstance(node, dict):
        for key, item in node.items():
            found += _containers(item, (*pointer, key))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found += _containers(item, (*pointer, index))
    return [item for item in found if isinstance(item[1], dict | list)]


@st.composite
def edit_sequences(draw: st.DrawFn) -> tuple[dict[str, Any], list[Op]]:
    """A random document and random ops that fit it, applied one after the other."""
    start = draw(st.dictionaries(st.sampled_from(KEYS), values, min_size=1, max_size=3))
    current: dict[str, Any] = start
    ops: list[Op] = []
    for _ in range(draw(st.integers(1, 6))):
        pointer, container = draw(st.sampled_from(_containers(current)))
        if isinstance(container, list):
            choices = ["add"] + (["remove", "replace"] if container else [])
            name = draw(st.sampled_from(choices))
            top = len(container) if name == "add" else len(container) - 1
            key: str | int = draw(st.integers(0, top))
        else:
            name = draw(st.sampled_from(["add", "remove", "replace"]))
            missing = [k for k in KEYS if k not in container]
            if name == "add":
                if not missing:
                    continue
                key = draw(st.sampled_from(missing))
            else:
                if not container:
                    continue
                key = draw(st.sampled_from(sorted(container)))
        if not pointer and name == "remove" and len(current) == 1:
            continue  # keep the root non-empty
        op = Op(name, (*pointer, key), draw(values))  # type: ignore[arg-type]
        current, _ = apply(current, [op])
        ops.append(op)
    return start, ops


@settings(max_examples=300, deadline=None)
@given(edit_sequences())
def test_random_edits_undo_exactly(case: tuple[dict[str, Any], list[Op]]) -> None:
    start, ops = case
    snapshot = copy.deepcopy(start)
    # One op at a time, then undo step by step in reverse order…
    states = [start]
    inverses = []
    for op in ops:
        state, inverse = apply(states[-1], [op])
        states.append(state)
        inverses.append(inverse)
    for k in range(len(ops), 0, -1):
        assert apply(states[k], inverses[k - 1])[0] == states[k - 1]
    # …and all ops at once, undone at once.
    edited, inverse = apply(start, ops)
    assert edited == states[-1]
    assert apply(edited, inverse)[0] == snapshot
    assert start == snapshot
