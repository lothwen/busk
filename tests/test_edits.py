"""Generic edits, patching and page assignment (phase-3-plan §5.1–§5.2)."""

from __future__ import annotations

from typing import Any, cast

import pytest

from builders import APPENDIX_A, load_doc, show_of
from busk.commands import edits
from busk.commands.errors import CommandError
from busk.commands.patch import Op
from busk.commands.types import AddCmd, AssignPlaybackCmd, DeleteCmd, PatchFixtureCmd, SetCmd
from busk.model.show import Show
from session_harness import Live


@pytest.fixture(scope="module")
def show() -> Show:
    return show_of(load_doc(APPENDIX_A))


VERSE = ["cueLists", {"id": "cl-song"}, "cues", {"id": "c-verse"}]
NEW_CUE = {
    "id": "c-x",
    "number": "1.5",
    "name": "x",
    "entries": [],
    "effects": [],
    "timing": {"fadeIn": 0, "fadeOut": 0, "delayIn": 0, "delayOut": 0, "curve": "linear"},
    "trigger": {"kind": "go"},
}

OPS: list[tuple[str, dict[str, Any], list[Op]]] = [
    (
        "SET replaces an existing key",
        {"type": "SET", "path": [*VERSE, "timing", "fadeIn"], "value": 3},
        [Op("replace", ("cueLists", 0, "cues", 0, "timing", "fadeIn"), 3)],
    ),
    (
        "SET adds an optional key",
        {"type": "SET", "path": ["playbacks", {"id": "pb-pulse"}, "exclusivity"], "value": "fx"},
        [Op("add", ("playbacks", 2, "exclusivity"), "fx")],
    ),
    (
        "SET replaces a list without ids whole",
        {"type": "SET", "path": ["playbacks", {"id": "pb-song"}, "buttons"], "value": ["go"]},
        [Op("replace", ("playbacks", 0, "buttons"), ["go"])],
    ),
    (
        "ADD appends to an id'd list",
        {"type": "ADD", "path": ["universes"], "value": {"id": "u2", "name": "Two", "number": 2}},
        [Op("add", ("universes", 1), {"id": "u2", "name": "Two", "number": 2})],
    ),
    (
        "ADD inserts a cue in number order",
        {"type": "ADD", "path": ["cueLists", {"id": "cl-song"}, "cues"], "value": NEW_CUE},
        [Op("add", ("cueLists", 0, "cues", 1), NEW_CUE)],
    ),
    (
        "DELETE removes an id'd element",
        {"type": "DELETE", "path": ["presets", {"id": "pr-red"}]},
        [Op("remove", ("presets", 1))],
    ),
    (
        "DELETE removes an optional key",
        {"type": "DELETE", "path": ["fixtures", {"id": "fx-mh1"}, "limits"]},
        [Op("remove", ("fixtures", 0, "limits"))],
    ),
    (
        "PATCH_FIXTURE replaces the patch",
        {
            "type": "PATCH_FIXTURE",
            "fixtureId": "fx-par1",
            "patch": {"universeId": "u1", "address": 300},
        },
        [Op("replace", ("fixtures", 2, "patch"), {"universeId": "u1", "address": 300})],
    ),
    (
        "PATCH_FIXTURE unpatches",
        {"type": "PATCH_FIXTURE", "fixtureId": "fx-par1", "patch": None},
        [Op("replace", ("fixtures", 2, "patch"), None)],
    ),
    (
        "ASSIGN_PLAYBACK fills a slot",
        {"type": "ASSIGN_PLAYBACK", "pageId": "page-1", "slot": 1, "playbackId": "pb-pulse"},
        [
            Op(
                "replace",
                ("pages", 0, "slots"),
                ["pb-song", "pb-pulse", "pb-blue", None, None, "pb-pulse", None, None],
            )
        ],
    ),
    (
        "ASSIGN_PLAYBACK extends the slots",
        {"type": "ASSIGN_PLAYBACK", "pageId": "page-1", "slot": 10, "playbackId": "pb-blue"},
        [
            Op(
                "replace",
                ("pages", 0, "slots"),
                [
                    "pb-song",
                    None,
                    "pb-blue",
                    None,
                    None,
                    "pb-pulse",
                    None,
                    None,
                    None,
                    None,
                    "pb-blue",
                ],
            )
        ],
    ),
    (
        "SET replaces the park list, whose entries have no ids (Phase 7)",
        {"type": "SET", "path": ["park"], "value": []},
        [Op("replace", ("park",), [])],
    ),
    (
        "ASSIGN_PLAYBACK empties a slot",
        {"type": "ASSIGN_PLAYBACK", "pageId": "page-1", "slot": 0, "playbackId": None},
        [
            Op(
                "replace",
                ("pages", 0, "slots"),
                [None, None, "pb-blue", None, None, "pb-pulse", None, None],
            )
        ],
    ),
]

HANDLERS: dict[str, Any] = {
    "ADD": lambda s, c: edits.add(s, cast(AddCmd, c)),
    "SET": lambda s, c: edits.set_(s, cast(SetCmd, c)),
    "DELETE": lambda s, c: edits.delete(s, cast(DeleteCmd, c)),
    "PATCH_FIXTURE": lambda s, c: edits.patch_fixture(s, cast(PatchFixtureCmd, c)),
    "ASSIGN_PLAYBACK": lambda s, c: edits.assign_playback(s, cast(AssignPlaybackCmd, c)),
}


@pytest.mark.parametrize(
    ("command", "ops"), [(c, o) for _, c, o in OPS], ids=[n for n, _, _ in OPS]
)
def test_the_ops_each_edit_produces(show: Show, command: dict[str, Any], ops: list[Op]) -> None:
    assert list(HANDLERS[command["type"]](show, command).ops) == ops


@pytest.mark.parametrize(
    ("command", "error"),
    [
        (
            {"type": "SET", "path": ["fixtures", {"id": "fx-mh1"}, "id"], "value": "x"},
            "ids cannot be changed",
        ),
        ({"type": "SET", "path": ["schemaVersion"], "value": 2}, "schemaVersion cannot be changed"),
        (
            {"type": "SET", "path": ["meta", "created"], "value": ""},
            "meta.created cannot be changed",
        ),
        ({"type": "SET", "path": ["meta"], "value": {}}, "meta.id cannot be changed"),
        ({"type": "DELETE", "path": ["meta", "id"]}, "ids cannot be changed"),
        (
            {"type": "SET", "path": ["fixtures"], "value": []},
            "the fixtures list cannot be replaced; ADD or DELETE its elements",
        ),
        ({"type": "DELETE", "path": ["output"]}, "the show's 'output' cannot be deleted"),
        (
            {"type": "SET", "path": ["fixtures", {"id": "fx-mh1"}], "value": {}},
            "SET needs a path that ends with an object key",
        ),
        (
            {"type": "SET", "path": ["fixtures", {"id": "fx-9"}, "name"], "value": "x"},
            "fixtures has no element with id 'fx-9'",
        ),
        (
            {"type": "DELETE", "path": ["fixtures", {"id": "fx-mh2"}, "limits"]},
            "fixtures[1].limits does not exist",
        ),
        ({"type": "ADD", "path": ["meta"], "value": {"id": "x"}}, "meta is not a list"),
        (
            {"type": "ADD", "path": ["groups"], "value": {"name": "no id"}},
            "ADD needs an object with a string 'id'",
        ),
        ({"type": "PATCH_FIXTURE", "fixtureId": "fx-9", "patch": None}, "no fixture 'fx-9'"),
        (
            {"type": "ASSIGN_PLAYBACK", "pageId": "p-9", "slot": 0, "playbackId": None},
            "no page 'p-9'",
        ),
    ],
)
def test_rejected_before_validation(show: Show, command: dict[str, Any], error: str) -> None:
    with pytest.raises(CommandError) as raised:
        HANDLERS[command["type"]](show, command)
    assert raised.value.message == error


# ------------------------------------------------- rejected by validation


@pytest.fixture
def live() -> Live:
    return Live(load_doc(APPENDIX_A))


def rejected(live: Live, command: dict[str, Any]) -> list[tuple[str, str]]:
    result = live.session.submit(cast(Any, command))
    assert not result.ok
    return [(issue.path, issue.message) for issue in result.issues]


def test_deleting_a_referenced_entity_lists_every_reference(live: Live) -> None:
    assert rejected(live, {"type": "DELETE", "path": ["groups", {"id": "g-mh"}]}) == [
        ("cueLists[0].cues[0].entries[0].targets.groupId", "Unknown group 'g-mh'"),
        ("cueLists[0].cues[0].entries[1].targets.groupId", "Unknown group 'g-mh'"),
        ("cueLists[0].cues[0].entries[2].targets.groupId", "Unknown group 'g-mh'"),
        ("cueLists[0].cues[1].entries[0].targets.groupId", "Unknown group 'g-mh'"),
        ("cueLists[0].cues[1].entries[1].targets.groupId", "Unknown group 'g-mh'"),
        ("cueLists[1].cues[0].entries[0].targets.groupId", "Unknown group 'g-mh'"),
        ("cueLists[2].cues[0].effects[0].targets.groupId", "Unknown group 'g-mh'"),
    ]


def test_a_duplicate_number_is_rejected(live: Live) -> None:
    command = {
        "type": "ADD",
        "path": ["groups"],
        "value": {"id": "g-x", "name": "X", "number": 1, "members": []},
    }
    assert rejected(live, command) == [
        ("groups[2].number", "Duplicate number 1 (first used at groups[0])")
    ]


def test_a_structural_error_carries_its_path(live: Live) -> None:
    command = {"type": "SET", "path": ["playbacks", {"id": "pb-song"}, "priority"], "value": "high"}
    assert rejected(live, command) == [("playbacks[0].priority", "Input should be a valid integer")]


def test_an_edit_that_cannot_compile_is_rejected(live: Live) -> None:
    command = {
        "type": "SET",
        "path": ["fixtures", {"id": "fx-par1"}, "elementPatch"],
        "value": {"0": {"universeId": "u1", "address": 400}},
    }
    result = live.session.submit(cast(Any, command))
    assert not result.ok
    assert result.message.endswith("split patches are not supported yet")
