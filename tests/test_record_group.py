"""RECORD_GROUP: create, replace, merge, remove, layouts (phase-3-plan §5.5)."""

from __future__ import annotations

from typing import Any, cast

import pytest

from builders import APPENDIX_A, load_doc, state_of
from busk.commands.errors import CommandError
from busk.commands.record import record_group
from busk.commands.types import RecordGroupCmd
from busk.session.ids import CounterIds
from busk.session.programmer import Programmer
from busk.session.state import ShowState
from record_helpers import applied, program, select

MH1, MH2, PAR = (
    {"fixtureId": "fx-mh1", "element": 0},
    {"fixtureId": "fx-mh2", "element": 0},
    {"fixtureId": "fx-par1", "element": 0},
)


def cmd(number: int, **fields: Any) -> RecordGroupCmd:
    return cast(RecordGroupCmd, {"type": "RECORD_GROUP", "number": number, **fields})


def record(state: ShowState, programmer: Programmer, command: RecordGroupCmd) -> dict[str, Any]:
    show = applied(state, record_group(state.show, programmer, command, CounterIds()))
    return cast(dict[str, Any], next(g for g in show["groups"] if g["number"] == command["number"]))


@pytest.fixture
def state() -> ShowState:
    return state_of(load_doc(APPENDIX_A))


def test_create_takes_the_selection_in_order(state: ShowState) -> None:
    group = record(state, program(state, select("fx-par1", "fx-mh2")), cmd(5))
    assert group == {"id": "g-000000000001", "name": "Group 5", "number": 5, "members": [PAR, MH2]}
    named = record(state, program(state, select("fx-mh1")), cmd(6, name="Solo"))
    assert named["name"] == "Solo"


@pytest.mark.parametrize(
    ("merge", "members"),
    [("replace", [PAR, MH2]), ("merge", [MH1, MH2, PAR]), ("remove", [MH1])],
)
def test_merge_modes(state: ShowState, merge: str, members: list[dict[str, Any]]) -> None:
    group = record(state, program(state, select("fx-par1", "fx-mh2")), cmd(1, merge=merge))
    assert group["members"] == members
    assert (group["id"], group["name"]) == ("g-mh", "Moving Heads")


@pytest.mark.parametrize(
    ("programmer_commands", "command", "error"),
    [
        ([select("fx-mh1")], cmd(1), "^group 1 exists: add merge or replace$"),
        ([select("fx-mh1")], cmd(9, merge="merge"), "^no group 9$"),
        ([], cmd(9), "^nothing selected$"),
    ],
)
def test_errors(
    state: ShowState, programmer_commands: list[dict[str, Any]], command: RecordGroupCmd, error: str
) -> None:
    with pytest.raises(CommandError, match=error):
        record_group(state.show, program(state, *programmer_commands), command, CounterIds())


def with_layout() -> ShowState:
    doc = load_doc(APPENDIX_A)
    doc["groups"][0]["layout"] = {"width": 2, "height": 1, "cells": [1, 0]}  # MH 2, MH 1
    return state_of(doc)


def test_a_layout_follows_its_members() -> None:
    state = with_layout()
    group = record(state, program(state, select("fx-mh2", "fx-mh1")), cmd(1, merge="replace"))
    assert group["layout"]["cells"] == [0, 1]  # still MH 2, MH 1
    group = record(state, program(state, select("fx-par1")), cmd(1, merge="merge"))
    assert group["layout"]["cells"] == [1, 0]


def test_a_layout_pointing_at_a_removed_member_is_dropped_with_a_warning() -> None:
    state = with_layout()
    edit = record_group(
        state.show, program(state, select("fx-mh1")), cmd(1, merge="remove"), CounterIds()
    )
    group = applied(state, edit)["groups"][0]
    assert "layout" not in group
    assert [(w.path, w.message) for w in edit.warnings] == [
        (
            "groups[0].layout",
            "layout dropped: it pointed at members that are no longer in the group",
        )
    ]
