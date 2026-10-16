"""Helpers shared by the recording tests: run a record command against a show
state and a programmer, apply its ops and validate the result."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from busk.commands.edits import Edit
from busk.commands.patch import apply
from busk.commands.types import Command
from busk.model.show import Show
from busk.model.validate import has_errors, validate_edit
from busk.session.ids import CounterIds
from busk.session.programmer import EMPTY, Programmer, handle
from busk.session.state import ShowState

type Recorder = Callable[..., Edit]


def program(state: ShowState, *commands: dict[str, Any]) -> Programmer:
    """A programmer built by running programmer commands from empty."""
    programmer = EMPTY
    for command in commands:
        programmer = handle(state, programmer, cast(Command, command)).programmer
    return programmer


def applied(state: ShowState, edit: Edit) -> Show:
    """The show after ``edit``, which must validate without errors."""
    after, _ = apply(state.show, edit.ops)
    show, issues = validate_edit(state.show, after)
    assert show is not None, issues
    assert not has_errors(issues), issues
    return show


def select(*fixture_ids: str) -> dict[str, Any]:
    refs = [{"fixtureId": f, "element": 0} for f in fixture_ids]
    return {"type": "SELECT", "targets": {"kind": "targets", "refs": refs}, "mode": "replace"}


def select_group(ident: str, mode: str = "replace") -> dict[str, Any]:
    return {"type": "SELECT", "targets": {"kind": "group", "groupId": ident}, "mode": mode}


def set_literal(attribute: str, value: Any) -> dict[str, Any]:
    return {
        "type": "SET_ATTRIBUTE",
        "attribute": attribute,
        "value": {"kind": "literal", "value": value},
    }


def set_source(attribute: str, source: dict[str, Any]) -> dict[str, Any]:
    return {"type": "SET_ATTRIBUTE", "attribute": attribute, "value": source}


def apply_preset(ident: str) -> dict[str, Any]:
    return {"type": "APPLY_PRESET", "presetId": ident}


def ids() -> CounterIds:
    return CounterIds()


def add_effect(instance: dict[str, Any]) -> dict[str, Any]:
    return {"type": "ADD_EFFECT", "effect": instance}
