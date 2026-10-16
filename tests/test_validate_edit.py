"""Per-edit validation agrees with full validation (phase-3-plan §5.3)."""

from __future__ import annotations

import copy
import json
from typing import Any, cast

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from builders import APPENDIX_A, load_doc
from busk.commands.patch import Op, apply
from busk.model.show import Show
from busk.model.validate import Issue, has_errors, validate_edit, validate_show


def appendix() -> Show:
    show, issues = validate_show(APPENDIX_A.read_bytes())
    assert show is not None
    assert not issues
    return show


def key(issues: list[Issue]) -> list[tuple[str, str, str]]:
    return sorted((issue.severity, issue.path, issue.message) for issue in issues)


def test_structural_errors_carry_show_level_paths() -> None:
    before = appendix()
    after, _ = apply(before, [Op("replace", ("fixtures", 2, "patch", "address"), 0)])
    show, issues = validate_edit(before, after)
    assert show is None
    assert key(issues) == [
        ("error", "fixtures[2].patch.address", "Input should be greater than or equal to 1")
    ]


def test_deep_structural_errors_inside_unions() -> None:
    before = appendix()
    after, _ = apply(
        before,
        [Op("add", ("presets", 0, "values", 0, "value", "bogus"), 1)],
    )
    show, issues = validate_edit(before, after)
    assert show is None
    assert key(issues) == [
        ("error", "presets[0].values[0].value.bogus", "Extra inputs are not permitted")
    ]


def test_touched_entities_are_normalised_and_untouched_ones_kept() -> None:
    before = appendix()
    timing = ("cueLists", 0, "cues", 0, "timing", "fadeIn")
    after, _ = apply(
        before,
        [Op("replace", timing, 3), Op("add", ("fixtures", 0, "notes"), "rigged")],
    )
    show, issues = validate_edit(before, after)
    assert show is not None
    assert issues == []
    fade = show["cueLists"][0]["cues"][0]["timing"]["fadeIn"]
    assert (fade, type(fade)) == (3.0, float)
    assert list(show["fixtures"][0])[-3:] == ["patch", "orientation", "limits"]  # schema order
    assert show["fixtures"][0]["notes"] == "rigged"
    assert show["fixtures"][1] is before["fixtures"][1]
    assert show["groups"] is before["groups"]
    assert show["cueLists"][1] is before["cueLists"][1]


def test_semantic_errors_are_reported_on_the_whole_show() -> None:
    before = appendix()
    after, _ = apply(before, [Op("remove", ("fixtures", 0))])
    show, issues = validate_edit(before, after)
    assert show is not None
    assert has_errors(issues)
    assert ("error", "groups[0].members[0].fixtureId", "Unknown fixture 'fx-mh1'") in key(issues)


def test_root_keys_are_checked() -> None:
    before = appendix()
    after, _ = apply(before, [Op("remove", ("park",)), Op("add", ("bogus",), 1)])
    show, issues = validate_edit(before, after)
    assert show is None
    assert key(issues) == [
        ("error", "bogus", "Extra inputs are not permitted"),
        ("error", "park", "Field required"),
    ]


def test_safety_is_an_optional_root_key() -> None:
    """Phase 7: ``safety`` may be added, edited and removed; a show without it
    is not missing a field."""
    before = appendix()
    added, _ = apply(before, [Op("add", ("safety",), {"strobeMaxHz": 8})])
    show, issues = validate_edit(before, added)
    assert show is not None
    assert issues == []
    assert show["safety"] == {"strobeMaxHz": 8.0}
    bad, _ = apply(show, [Op("replace", ("safety", "strobeMaxHz"), 0)])
    rejected, issues = validate_edit(show, bad)
    assert rejected is None
    assert key(issues) == [("error", "safety.strobeMaxHz", "Input should be greater than 0")]
    removed, _ = apply(show, [Op("remove", ("safety",))])
    show, issues = validate_edit(show, removed)
    assert show is not None
    assert issues == []
    assert "safety" not in show


# ------------------------------------------------------------------ property

LEAVES = st.one_of(
    st.integers(-3, 600),
    st.floats(-1, 2, allow_nan=False),
    st.sampled_from(["", "x", "fx-mh1", "fx-par1", "g-mh", "pr-blue", "u1", "cl-blue", "pb-blue"]),
    st.sampled_from(["open", "global", "group", "targets", "literal", "preset", "midiCC", "sacn"]),
    st.none(),
    st.booleans(),
)
KEYS = st.sampled_from(["kind", "id", "name", "value", "r", "g", "b", "slot", "number", "notes"])
VALUES = st.recursive(
    LEAVES,
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(KEYS, inner, max_size=3),
    max_leaves=6,
)


def _nodes(
    node: Any, pointer: tuple[str | int, ...] = ()
) -> list[tuple[tuple[str | int, ...], Any]]:
    found = [(pointer, node)]
    if isinstance(node, dict):
        for name, item in node.items():
            found += _nodes(item, (*pointer, name))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found += _nodes(item, (*pointer, index))
    return found


@st.composite
def edit(draw: st.DrawFn, show: Show) -> list[Op]:
    """One random op somewhere in ``show`` (never on ``schemaVersion``)."""
    nodes = [(p, n) for p, n in _nodes(show) if p and p[0] != "schemaVersion"]
    pointer, node = draw(st.sampled_from(nodes))
    parent_pointer, last = pointer[:-1], pointer[-1]
    choice = draw(st.sampled_from(["replace", "remove", "add", "add-copy"]))
    if choice == "replace":
        return [Op("replace", pointer, draw(VALUES))]
    if choice == "remove":
        return [Op("remove", pointer)]
    parent = show
    for segment in parent_pointer:
        parent = parent[segment]  # type: ignore[index]
    if isinstance(parent, list):
        assert isinstance(last, int)
        value = copy.deepcopy(node) if choice == "add-copy" else draw(VALUES)
        if (
            choice == "add-copy"
            and isinstance(value, dict)
            and "id" in value
            and draw(st.booleans())
        ):
            value["id"] = f"{value['id']}-copy"
        return [Op("add", (*parent_pointer, draw(st.integers(0, len(parent)))), value)]
    if isinstance(node, dict):
        name = draw(KEYS)
        if name in node:
            return [Op("replace", (*pointer, name), draw(VALUES))]
        return [Op("add", (*pointer, name), draw(VALUES))]
    return [Op("replace", pointer, draw(VALUES))]


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(st.data())
def test_validate_edit_agrees_with_validate_show(data: st.DataObject) -> None:
    show = appendix()
    for _ in range(data.draw(st.integers(1, 4))):
        ops = data.draw(edit(show))
        after, _ = apply(show, ops)
        mine, issues = validate_edit(show, after)
        theirs, expected = validate_show(json.dumps(after))
        assert key(issues) == key(expected)
        assert (mine is None) == (theirs is None)
        if mine is not None:
            assert mine == theirs  # normalised exactly as a full load would
        if mine is None or has_errors(issues):
            continue  # a rejected edit: the store keeps the previous show
        show = mine


def test_hand_written_values_normalise_like_a_load() -> None:
    before = appendix()
    raw = load_doc(APPENDIX_A)["fixtures"][0]
    raw["id"], raw["number"], raw["name"] = "fx-new", 999, "New"
    after, _ = apply(before, [Op("add", ("fixtures", 3), raw)])
    show, issues = validate_edit(before, after)
    assert show is not None
    assert [issue for issue in issues if issue.severity == "error"] == []
    theirs, _ = validate_show(json.dumps(after))
    assert show == theirs
    assert cast(dict[str, Any], show["fixtures"][3])["limits"]["tilt"] == (-120.0, 120.0)
