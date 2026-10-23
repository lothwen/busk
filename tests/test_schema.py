"""Structural validation: Appendix A validates, and strictness is enforced everywhere."""

from __future__ import annotations

import importlib
import json
import pkgutil
import typing
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import busk.commands
import busk.model
from busk.model.validate import SHOW_ADAPTER, validate_show

type Mutation = Callable[[dict[str, Any]], object]


def test_appendix_a_validates_structurally(appendix_a_text: str) -> None:
    show = SHOW_ADAPTER.validate_json(appendix_a_text, strict=True)
    # JSON arrays become tuples where the schema says tuple, ints are accepted for floats.
    pan = show["profiles"][0]["modes"][0]["channels"][0]
    assert pan["capabilities"][0]["dmx"] == (0, 65535)
    assert show["profiles"][0]["physical"]["zoomRange"] == (12.0, 30.0)


def _channel(show: dict[str, Any], index: int) -> dict[str, Any]:
    channel: dict[str, Any] = show["profiles"][0]["modes"][0]["channels"][index]
    return channel


def _set(container_of: Callable[[dict[str, Any]], Any], key: str | int, value: object) -> Mutation:
    def mutate(show: dict[str, Any]) -> None:
        container_of(show)[key] = value

    return mutate


def _delete(container_of: Callable[[dict[str, Any]], Any], key: str) -> Mutation:
    def mutate(show: dict[str, Any]) -> None:
        del container_of(show)[key]

    return mutate


REJECTIONS: list[tuple[str, Mutation, str]] = [
    ("unknown key at depth 1", _set(lambda s: s, "bogus", 1), "bogus"),
    (
        "unknown key at depth 3",
        _set(lambda s: s["fixtures"][0]["patch"], "bogus", 1),
        "fixtures[0].patch.bogus",
    ),
    (
        "unknown key at depth 5 (inside a tagged union member)",
        _set(lambda s: _channel(s, 0)["capabilities"][0], "bogus", 1),
        "profiles[0].modes[0].channels[0].capabilities[0].bogus",
    ),
    (
        "unknown key in a 'slot' capability, which also has a 'slot' key",
        _set(lambda s: _channel(s, 8)["capabilities"][1], "bogus", 1),
        "profiles[0].modes[0].channels[8].capabilities[1].bogus",
    ),
    (
        "unknown key in a functional TypedDict (spread)",
        _set(lambda s: s["cueLists"][0]["cues"][0]["entries"][2]["value"], "bogus", 1),
        "cueLists[0].cues[0].entries[2].value.bogus",
    ),
    (
        "unknown key in a command embedded in a binding",
        lambda s: s["bindings"].append(
            {
                "id": "b9",
                "surfaceId": "s-midi",
                "input": {"kind": "osc", "path": "/go"},
                "action": {
                    "kind": "command",
                    "command": {"type": "GO", "playbackId": "pb-song", "bogus": 1},
                },
            }
        ),
        "bindings[3].action.command.bogus",
    ),
    (
        "bad discriminator",
        _set(lambda s: s["output"]["routes"][0], "protocol", "dmx"),
        "output.routes[0].protocol",
    ),
    (
        "missing discriminator",
        _delete(lambda s: s["cueLists"][0]["cues"][0]["trigger"], "kind"),
        "cueLists[0].cues[0].trigger.kind",
    ),
    (
        "string where a float is expected",
        _set(lambda s: s["fixtures"][0]["orientation"], "panOffset", "1.5"),
        "fixtures[0].orientation.panOffset",
    ),
    (
        "bool where a float is expected",
        _set(lambda s: s["masters"][1], "defaultBpm", True),
        "masters[1].defaultBpm",
    ),
    (
        "int where a bool is expected",
        _set(lambda s: s["output"], "holdLastFrameOnEngineStall", 1),
        "output.holdLastFrameOnEngineStall",
    ),
    (
        "int cue number",
        _set(lambda s: s["cueLists"][0]["cues"][0], "number", 1),
        "cueLists[0].cues[0].number",
    ),
    (
        "integer id (the generic EntityBase id must still be a string)",
        _set(lambda s: s["fixtures"][0], "id", 5),
        "fixtures[0].id",
    ),
    ("missing required key", _delete(lambda s: s["fixtures"][0], "modeId"), "fixtures[0].modeId"),
    (
        "missing inherited key",
        _delete(lambda s: s["profiles"][1], "name"),
        "profiles[1].name",
    ),
    (
        "NaN",
        _set(lambda s: s["fixtures"][0]["orientation"], "panOffset", float("nan")),
        "fixtures[0].orientation.panOffset",
    ),
    (
        "Infinity",
        _set(lambda s: s["fixtures"][0]["orientation"], "tiltOffset", float("inf")),
        "fixtures[0].orientation.tiltOffset",
    ),
    (
        "address 0",
        _set(lambda s: s["fixtures"][0]["patch"], "address", 0),
        "fixtures[0].patch.address",
    ),
    (
        "address 513",
        _set(lambda s: s["fixtures"][0]["patch"], "address", 513),
        "fixtures[0].patch.address",
    ),
    (
        "colour component above 1",
        _set(lambda s: s["presets"][0]["values"][0]["value"], "b", 1.5),
        "presets[0].values[0].value.b",
    ),
    (
        "malformed colour reports only the colour shape's error",
        _delete(lambda s: s["presets"][0]["values"][0]["value"], "b"),
        "presets[0].values[0].value.b",
    ),
    (
        "value that is no attribute value at all",
        _set(lambda s: s["cueLists"][0]["cues"][0]["entries"][0]["value"], "value", "bright"),
        "cueLists[0].cues[0].entries[0].value.value",
    ),
    (
        "effect layer with neither waveform nor palette",
        _delete(lambda s: s["effects"][0]["layers"][0], "waveform"),
        "effects[0].layers[0]",
    ),
    ("engineHz 0", _set(lambda s: s["output"], "engineHz", 0), "output.engineHz"),
    (
        "negative fade time",
        _set(lambda s: s["cueLists"][0]["cues"][0]["timing"], "fadeIn", -1),
        "cueLists[0].cues[0].timing.fadeIn",
    ),
    (
        "unknown attribute family in perFamily",
        _set(
            lambda s: s["cueLists"][0]["cues"][0]["timing"],
            "perFamily",
            {"sparkle": {"fade": 1, "delay": 0}},
        ),
        "cueLists[0].cues[0].timing.perFamily.sparkle",
    ),
    (
        "sACN universe 0",
        _set(lambda s: s["output"]["routes"][0], "universe", 0),
        "output.routes[0].universe",
    ),
]


@pytest.mark.parametrize(
    ("mutation", "path"),
    [(mutation, path) for _, mutation, path in REJECTIONS],
    ids=[name for name, _, _ in REJECTIONS],
)
def test_rejected_with_exact_path(
    appendix_a: dict[str, Any], mutation: Mutation, path: str
) -> None:
    mutation(appendix_a)
    show, issues = validate_show(json.dumps(appendix_a))
    assert show is None
    assert [(issue.severity, issue.path) for issue in issues] == [("error", path)]


def _show_typed_dicts() -> list[type]:
    """Every TypedDict defined in busk.model and busk.commands."""
    found: list[type] = []
    for package in (busk.model, busk.commands):
        for info in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
            module = importlib.import_module(info.name)
            for value in vars(module).values():
                if typing.is_typeddict(value) and value.__module__ == module.__name__:
                    found.append(value)
    return found


def test_every_typed_dict_forbids_extra_keys_and_non_finite_numbers() -> None:
    typed_dicts = _show_typed_dicts()
    assert len(typed_dicts) > 80  # the walk really found the schema
    missing = [
        td.__qualname__
        for td in typed_dicts
        if getattr(td, "__pydantic_config__", {}).get("extra") != "forbid"
        or getattr(td, "__pydantic_config__", {}).get("allow_inf_nan") is not False
    ]
    assert missing == []


# ------------------------------------------------------- Phase 3 commands


def _command_types() -> list[str]:
    """The ``type`` tag of every member of the ``Command`` union."""
    from busk.commands.types import Command

    union = typing.get_args(Command.__value__)[0]  # Annotated[Union, Field] → Union
    tags = []
    for member in typing.get_args(union):
        tags.extend(typing.get_args(typing.get_type_hints(member)["type"]))
    return tags


def test_every_command_type_has_exactly_one_class() -> None:
    from busk.commands.classes import COMMAND_CLASSES

    types = _command_types()
    assert len(types) == len(set(types)) == 39  # GAP-05: ADJUST_ATTRIBUTE, GAP-14: RUN_EFFECT
    assert sorted(types) == sorted(COMMAND_CLASSES)
    assert {COMMAND_CLASSES[t] for t in types} == {"performance", "programmer", "show", "session"}


def _command_issues(appendix_a: dict[str, Any], command: dict[str, Any]) -> list[tuple[str, str]]:
    """Embed ``command`` in a new binding and return the issues' ``(severity, path)``."""
    appendix_a["bindings"].append(
        {
            "id": "b9",
            "surfaceId": "s-midi",
            "input": {"kind": "midiNote", "channel": 1, "note": 9},
            "action": {"kind": "command", "command": command},
        }
    )
    _, issues = validate_show(json.dumps(appendix_a))
    return [(issue.severity, issue.path) for issue in issues]


PHASE_3_COMMANDS: list[dict[str, Any]] = [
    {"type": "SELECT_PLAYBACK", "playbackId": "pb-blue", "mode": "replace"},
    {"type": "BLIND", "on": True},
    {"type": "RECORD_CUE", "cueListId": "cl-blue", "cueNumber": "2", "filter": ["color"],
     "merge": "merge", "name": "Two", "freeze": True},
    {"type": "RECORD_CUE", "cueListId": "cl-blue"},
    {"type": "RECORD_PRESET", "pool": "color", "number": 3, "scope": "global", "merge": "replace",
     "name": "Green"},
    {"type": "RECORD_GROUP", "number": 4, "merge": "remove", "name": "Odd"},
    {"type": "ASSIGN_PLAYBACK", "pageId": "page-1", "slot": 9, "playbackId": None},
    {"type": "ADD", "path": ["groups"], "value": {"id": "g", "number": 9, "name": "g",
                                                   "members": []}},
    {"type": "SET", "path": ["cueLists", {"id": "cl-song"}, "cues", {"id": "c-verse"}, "timing",
                             "fadeIn"], "value": 2.5},
    {"type": "DELETE", "path": ["presets", {"id": "pr-red"}]},
    {"type": "BATCH", "label": "two", "commands": [
        {"type": "SET", "path": ["meta", "title"], "value": "x"},
        {"type": "ASSIGN_PLAYBACK", "pageId": "page-1", "slot": 1, "playbackId": "pb-blue"}]},
    {"type": "UNDO"},
    {"type": "REDO"},
]  # fmt: skip


@pytest.mark.parametrize("command", PHASE_3_COMMANDS, ids=lambda c: str(c["type"]))
def test_phase_3_commands_validate_in_bindings(
    appendix_a: dict[str, Any], command: dict[str, Any]
) -> None:
    assert _command_issues(appendix_a, command) == []


PHASE_3_REJECTIONS: list[tuple[str, dict[str, Any], str]] = [
    ("NaN inside an edit value",
     {"type": "SET", "path": ["meta", "title"], "value": {"a": [1, float("nan")]}},
     "bindings[3].action.command.value"),
    ("an integer path segment (lists are addressed by id)",
     {"type": "DELETE", "path": ["fixtures", 0]}, "bindings[3].action.command.path[1]"),
    ("an id segment with an extra key",
     {"type": "DELETE", "path": [{"id": "x", "k": 1}]}, "bindings[3].action.command.path[0].k"),
    ("a merge mode that does not exist",
     {"type": "RECORD_GROUP", "number": 1, "merge": "append"},
     "bindings[3].action.command.merge"),
    ("a nested BATCH",
     {"type": "BATCH", "label": "", "commands": [{"type": "BATCH", "label": "", "commands": []}]},
     "bindings[3].action.command.commands[0].type"),
    ("a performance command inside a BATCH",
     {"type": "BATCH", "label": "", "commands": [{"type": "GO", "playbackId": "pb-song"}]},
     "bindings[3].action.command.commands[0].type"),
    ("a negative page slot",
     {"type": "ASSIGN_PLAYBACK", "pageId": "page-1", "slot": -1, "playbackId": None},
     "bindings[3].action.command.slot"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("command", "path"),
    [(command, path) for _, command, path in PHASE_3_REJECTIONS],
    ids=[name for name, _, _ in PHASE_3_REJECTIONS],
)
def test_phase_3_commands_are_strict(
    appendix_a: dict[str, Any], command: dict[str, Any], path: str
) -> None:
    assert _command_issues(appendix_a, command) == [("error", path)]


@pytest.mark.parametrize(
    ("command", "path"),
    [
        ({"type": "SELECT_PLAYBACK", "playbackId": "nope", "mode": "add"}, "playbackId"),
        ({"type": "ASSIGN_PLAYBACK", "pageId": "nope", "slot": 0, "playbackId": None}, "pageId"),
        ({"type": "ASSIGN_PLAYBACK", "pageId": "page-1", "slot": 0, "playbackId": "x"},
         "playbackId"),
        ({"type": "BATCH", "label": "", "commands": [
            {"type": "PATCH_FIXTURE", "fixtureId": "nope", "patch": None}]},
         "commands[0].fixtureId"),
    ],
)  # fmt: skip
def test_references_of_phase_3_commands_in_bindings_are_checked(
    appendix_a: dict[str, Any], command: dict[str, Any], path: str
) -> None:
    assert _command_issues(appendix_a, command) == [("error", f"bindings[3].action.command.{path}")]


# ------------------------------------------------------- Phase 6 additions

PHASE_6_COMMANDS: list[dict[str, Any]] = [
    {"type": "SET_FADER", "slot": 3, "level": 0.5},
    {"type": "PLAYBACK_BUTTON", "slot": 0, "button": 1, "down": True},
    {"type": "PLAYBACK_BUTTON", "playbackId": "pb-song", "button": 0, "down": False},
    {"type": "PAGE", "number": 1},
    {"type": "PAGE", "delta": -1},
    {"type": "BLACKOUT"},
]


@pytest.mark.parametrize("command", PHASE_6_COMMANDS, ids=lambda c: str(c))
def test_phase_6_commands_validate_in_bindings(
    appendix_a: dict[str, Any], command: dict[str, Any]
) -> None:
    assert _command_issues(appendix_a, command) == []


PHASE_6_REJECTIONS: list[tuple[str, dict[str, Any], str]] = [
    ("a negative slot", {"type": "SET_FADER", "slot": -1, "level": 0}, "slot"),
    ("a button without down", {"type": "PLAYBACK_BUTTON", "slot": 0, "button": 0}, "down"),
    ("a negative button",
     {"type": "PLAYBACK_BUTTON", "slot": 0, "button": -1, "down": True}, "button"),
    ("a fractional page delta", {"type": "PAGE", "delta": 0.5}, "delta"),
    ("an unknown PAGE key", {"type": "PAGE", "delta": 1, "slot": 0}, "slot"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("command", "path"),
    [(command, path) for _, command, path in PHASE_6_REJECTIONS],
    ids=[name for name, _, _ in PHASE_6_REJECTIONS],
)
def test_phase_6_commands_are_strict(
    appendix_a: dict[str, Any], command: dict[str, Any], path: str
) -> None:
    assert _command_issues(appendix_a, command) == [("error", f"bindings[3].action.command.{path}")]


def test_phase_6_fields_are_optional_and_accepted(appendix_a: dict[str, Any]) -> None:
    appendix_a["playbacks"][0].update(buttons=["go", "goto"], gotoCue="2")
    appendix_a["surfaces"].append(
        {"id": "s-osc", "name": "TouchOSC", "kind": "osc",
         "match": {"port": 9000, "host": "10.0.0.5", "feedbackPort": 9001},
         "faderPickup": "jump"}
    )  # fmt: skip
    appendix_a["bindings"] += [
        {"id": "b4", "surfaceId": "s-midi", "input": {"kind": "midiClock"},
         "action": {"kind": "tap", "masterId": "m-speed"}},
        {"id": "b5", "surfaceId": "s-midi", "input": {"kind": "midiNote", "channel": 1, "note": 9},
         "action": {"kind": "blackout", "momentary": True}},
    ]  # fmt: skip
    show, issues = validate_show(json.dumps(appendix_a))
    assert show is not None
    assert issues == []
    assert show["playbacks"][0]["gotoCue"] == "2"
    assert show["surfaces"][1]["match"]["feedbackPort"] == 9001


@pytest.mark.parametrize(
    ("mutation", "path"),
    [
        (lambda s: s["playbacks"][0].update(gotoCue=2), "playbacks[0].gotoCue"),
        (lambda s: s["surfaces"][0]["match"].update(feedbackPort="9001"),
         "surfaces[0].match.feedbackPort"),
        (lambda s: s["bindings"][2].update(action={"kind": "blackout", "momentary": 1}),
         "bindings[2].action.momentary"),
        (lambda s: s["bindings"][0].update(input={"kind": "midiClock", "channel": 1}),
         "bindings[0].input.channel"),
    ],
)  # fmt: skip
def test_phase_6_fields_are_strict(
    appendix_a: dict[str, Any], mutation: Mutation, path: str
) -> None:
    mutation(appendix_a)
    show, issues = validate_show(json.dumps(appendix_a))
    assert show is None
    assert [(issue.severity, issue.path) for issue in issues] == [("error", path)]


@pytest.mark.parametrize(
    "name",
    ["fixtures/appendix_a", "golden/phase3_built_show", "golden/phase4_song_show",
     "golden/phase5_effects_show", "golden/phase6_surfaces_show"],
)  # fmt: skip
def test_old_documents_are_unchanged_by_validation(name: str) -> None:
    """The Phase 6 and Phase 7 fields are optional: a validated show adds no
    keys to a document written before them."""
    text = (Path(__file__).parent / f"{name}.json").read_text()
    show = SHOW_ADAPTER.validate_json(text, strict=True)
    assert json.loads(SHOW_ADAPTER.dump_json(show)) == json.loads(text)


# ------------------------------------------------------- Phase 7 additions

PHASE_7_COMMANDS: list[dict[str, Any]] = [
    {"type": "RELEASE_ALL"},
    {"type": "RELEASE_ALL", "time": 0},
    {"type": "RELEASE_ALL", "time": 3.5},
    {"type": "OUTPUT", "on": True},
    {"type": "HIGHLIGHT", "on": False},
]


@pytest.mark.parametrize("command", PHASE_7_COMMANDS, ids=lambda c: str(c))
def test_phase_7_commands_validate_in_bindings(
    appendix_a: dict[str, Any], command: dict[str, Any]
) -> None:
    assert _command_issues(appendix_a, command) == []


PHASE_7_REJECTIONS: list[tuple[str, dict[str, Any], str]] = [
    ("a negative release time", {"type": "RELEASE_ALL", "time": -1}, "time"),
    ("a release time as text", {"type": "RELEASE_ALL", "time": "1"}, "time"),
    ("OUTPUT without on", {"type": "OUTPUT"}, "on"),
    ("OUTPUT with a numeric on", {"type": "OUTPUT", "on": 0}, "on"),
    ("HIGHLIGHT without on", {"type": "HIGHLIGHT"}, "on"),
    ("HIGHLIGHT with a text on", {"type": "HIGHLIGHT", "on": "yes"}, "on"),
    ("an unknown RELEASE_ALL key", {"type": "RELEASE_ALL", "playbackId": "pb-song"}, "playbackId"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("command", "path"),
    [(command, path) for _, command, path in PHASE_7_REJECTIONS],
    ids=[name for name, _, _ in PHASE_7_REJECTIONS],
)
def test_phase_7_commands_are_strict(
    appendix_a: dict[str, Any], command: dict[str, Any], path: str
) -> None:
    assert _command_issues(appendix_a, command) == [("error", f"bindings[3].action.command.{path}")]


@pytest.mark.parametrize("safety", [{"strobeMaxHz": 10}, {"strobeMaxHz": 2.5}, {}])
def test_safety_is_optional_and_accepted(appendix_a: dict[str, Any], safety: Any) -> None:
    appendix_a["safety"] = safety
    show, issues = validate_show(json.dumps(appendix_a))
    assert show is not None
    assert issues == []
    assert show["safety"] == safety
    assert json.loads(SHOW_ADAPTER.dump_json(show)) == appendix_a  # nothing added


@pytest.mark.parametrize(
    ("safety", "path"),
    [
        ({"strobeMaxHz": 0}, "safety.strobeMaxHz"),
        ({"strobeMaxHz": -2}, "safety.strobeMaxHz"),
        ({"strobeMaxHz": "10"}, "safety.strobeMaxHz"),
        ({"strobeMaxHz": 10, "strobeMinHz": 1}, "safety.strobeMinHz"),
        (None, "safety"),
    ],
)  # fmt: skip
def test_safety_is_strict(appendix_a: dict[str, Any], safety: Any, path: str) -> None:
    appendix_a["safety"] = safety
    show, issues = validate_show(json.dumps(appendix_a))
    assert show is None
    assert [(issue.severity, issue.path) for issue in issues] == [("error", path)]
