"""Semantic validation: every rule fires with the right path and severity.

Each case mutates Appendix A in one place and asserts the *exact* set of
``(severity, path)`` pairs reported, so a rule that fires too often (or
cascades into unrelated errors) fails as surely as one that never fires.
Cases with an empty expectation are legitimate edits that must stay valid.
"""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from busk.model.validate import has_errors, validate_effect, validate_show

type Doc = dict[str, Any]
type Op = Callable[[Doc], None]

# ------------------------------------------------------------------ helpers

_TOKEN = re.compile(r'([A-Za-z_]\w*)|\[(\d+)\]|\["([^"]*)"\]')


def _keys(path: str) -> list[str | int]:
    keys: list[str | int] = []
    for name, index, quoted in _TOKEN.findall(path):
        keys.append(int(index) if index else name or quoted)
    return keys


def _node(doc: Doc, keys: list[str | int]) -> Any:
    node: Any = doc
    for key in keys:
        node = node[key]
    return node


def put(path: str, value: object) -> Op:
    """Set the value at ``path`` (e.g. ``fixtures[1].number``)."""

    def op(doc: Doc) -> None:
        keys = _keys(path)
        _node(doc, keys[:-1])[keys[-1]] = copy.deepcopy(value)

    return op


def drop(path: str) -> Op:
    def op(doc: Doc) -> None:
        keys = _keys(path)
        del _node(doc, keys[:-1])[keys[-1]]

    return op


def push(path: str, value: object) -> Op:
    def op(doc: Doc) -> None:
        _node(doc, _keys(path)).append(copy.deepcopy(value))

    return op


def clone(path: str, index: int, **changes: object) -> Op:
    """Append a copy of ``path[index]`` with some fields changed."""

    def op(doc: Doc) -> None:
        items = _node(doc, _keys(path))
        items.append({**copy.deepcopy(items[index]), **changes})

    return op


def E(path: str) -> tuple[str, str]:
    return ("error", path)


def W(path: str) -> tuple[str, str]:
    return ("warning", path)


@dataclass(frozen=True)
class Case:
    name: str
    ops: list[Op]
    expected: set[tuple[str, str]]


def case(name: str, *ops: Op, expect: set[tuple[str, str]]) -> Case:
    return Case(name, list(ops), expect)


MH = "profiles[0].modes[0]"  # the moving-head mode of Appendix A
CH = f"{MH}.channels"  # [0] pan [1] tilt [2..5] RGBW [6] dimmer [7] zoom [8] gobo1 [9] shutter
GOBO_CAPS = [
    {"kind": "slot", "dmx": [0, 9], "wheel": "gobo1", "slot": "open"},
    {"kind": "slot", "dmx": [10, 19], "wheel": "gobo1", "slot": "breakup"},
]
ENTRY = "cueLists[0].cues[0].entries"  # [0] intensity literal [1] colour literal [2] pan spread
PULSE = "cueLists[2].cues[0].effects[0]"  # the BPM-synced pulse instance


def binding_with(command: dict[str, Any]) -> Op:
    """Append a binding (bindings[3]) that issues ``command``."""
    return push(
        "bindings",
        {
            "id": "b-cmd",
            "surfaceId": "s-midi",
            "input": {"kind": "midiNote", "channel": 1, "note": 99},
            "action": {"kind": "command", "command": command},
        },
    )


CMD = "bindings[3].action.command"

# -------------------------------------------------------------------- cases

IDENTITY = [
    case("dup profile id", clone("profiles", 1), expect={E("profiles[2].id")}),
    case(
        "dup universe id",
        push("universes", {"id": "u1", "name": "Side", "number": 2}),
        expect={E("universes[1].id")},
    ),
    case(
        "dup fixture id",
        clone("fixtures", 2, number=202, patch=None),
        expect={E("fixtures[3].id")},
    ),
    case("dup group id", clone("groups", 1, number=3), expect={E("groups[2].id")}),
    case("dup preset id", clone("presets", 0, number=3), expect={E("presets[3].id")}),
    case("dup effect id", clone("effects", 0), expect={E("effects[1].id")}),
    case("dup cue list id", clone("cueLists", 1, number=11), expect={E("cueLists[3].id")}),
    case("dup playback id", clone("playbacks", 1, number=4), expect={E("playbacks[3].id")}),
    case("dup page id", clone("pages", 0, number=2), expect={E("pages[1].id")}),
    case("dup master id", clone("masters", 0), expect={E("masters[2].id")}),
    case("dup surface id", clone("surfaces", 0), expect={E("surfaces[1].id")}),
    case("dup binding id", clone("bindings", 0), expect={E("bindings[3].id")}),
    case("dup route id", clone("output.routes", 0), expect={E("output.routes[1].id")}),
    case("dup mode id", clone("profiles[0].modes", 0), expect={E("profiles[0].modes[1].id")}),
    case("dup wheel id", clone("profiles[0].wheels", 0), expect={E("profiles[0].wheels[1].id")}),
    case(
        "dup wheel slot id",
        push("profiles[0].wheels[0].slots", {"id": "open", "name": "Open again"}),
        expect={E("profiles[0].wheels[0].slots[2].id")},
    ),
    case(
        "dup cue id", put("cueLists[0].cues[1].id", "c-verse"), expect={E("cueLists[0].cues[1].id")}
    ),
    case(
        "dup effect instance id",
        clone("cueLists[2].cues[0].effects", 0),
        expect={E("cueLists[2].cues[0].effects[1].id")},
    ),
    case("ids are unique per collection only", put("output.routes[0].id", "u1"), expect=set()),
    case(
        "every duplicate is reported",
        clone("fixtures", 2, number=202, patch=None),
        clone("fixtures", 2, number=203, patch=None),
        expect={E("fixtures[3].id"), E("fixtures[4].id")},
    ),
]

NUMBERS = [
    case(
        "dup universe number",
        push("universes", {"id": "u2", "name": "Side", "number": 1}),
        expect={E("universes[1].number")},
    ),
    case("dup fixture number", put("fixtures[1].number", 101), expect={E("fixtures[1].number")}),
    case("dup group number", put("groups[1].number", 1), expect={E("groups[1].number")}),
    case("dup cue list number", put("cueLists[1].number", 1), expect={E("cueLists[1].number")}),
    case("dup playback number", put("playbacks[1].number", 1), expect={E("playbacks[1].number")}),
    case("dup page number", clone("pages", 0, id="page-2"), expect={E("pages[1].number")}),
    case(
        "dup preset number in a pool", put("presets[1].number", 1), expect={E("presets[1].number")}
    ),
    case(
        "preset numbers are per pool",
        put("presets[1].number", 1),
        put("presets[1].pool", "intensity"),
        expect=set(),
    ),
]

REFERENCES = [
    case(
        "unknown profile", put("fixtures[0].profileId", "nope"), expect={E("fixtures[0].profileId")}
    ),
    case("unknown mode", put("fixtures[0].modeId", "nope"), expect={E("fixtures[0].modeId")}),
    case(
        "mode of another profile",
        put("fixtures[0].modeId", "mode-3"),
        expect={E("fixtures[0].modeId")},
    ),
    case(
        "unknown patch universe",
        put("fixtures[0].patch.universeId", "u9"),
        expect={E("fixtures[0].patch.universeId")},
    ),
    case(
        "unknown elementPatch universe",
        put("fixtures[2].elementPatch", {"0": {"universeId": "u9", "address": 1}}),
        expect={E('fixtures[2].elementPatch["0"].universeId')},
    ),
    case(
        "unknown route universe",
        put("output.routes[0].universeId", "u9"),
        expect={E("output.routes[0].universeId")},
    ),
    case(
        "unknown group in an entry",
        put(f"{ENTRY}[0].targets.groupId", "nope"),
        expect={E(f"{ENTRY}[0].targets.groupId")},
    ),
    case(
        "unknown group of a group master",
        push("masters", {"id": "m-g", "kind": "group", "name": "G", "groupId": "nope"}),
        expect={E("masters[2].groupId")},
    ),
    case(
        "unknown preset in a source",
        put("cueLists[1].cues[0].entries[0].value.presetId", "nope"),
        expect={E("cueLists[1].cues[0].entries[0].value.presetId")},
    ),
    case(
        "unknown preset in a palette",
        push(
            "effects",
            {
                "id": "ef-colours",
                "name": "Colours",
                "layers": [
                    {
                        "attribute": "color",
                        "palette": [{"presetId": "nope"}, {"r": 1, "g": 0, "b": 0}],
                        "blend": "fade",
                        "mode": "absolute",
                    }
                ],
            },
        ),
        expect={E("effects[1].layers[0].palette[0].presetId")},
    ),
    case(
        "unknown effect template",
        put(f"{PULSE}.templateId", "nope"),
        expect={E(f"{PULSE}.templateId")},
    ),
    case(
        "unknown cue list",
        put("playbacks[0].cueListId", "nope"),
        expect={E("playbacks[0].cueListId")},
    ),
    case("unknown page slot", put("pages[0].slots[1]", "nope"), expect={E("pages[0].slots[1]")}),
    case(
        "unknown surface", put("bindings[0].surfaceId", "nope"), expect={E("bindings[0].surfaceId")}
    ),
    case(
        "unknown playback in an absolute fader action",
        put("bindings[0].action", {"kind": "playbackFaderAbs", "playbackId": "nope"}),
        expect={E("bindings[0].action.playbackId")},
    ),
    case(
        "unknown master in a master action",
        put("bindings[2].action.masterId", "nope"),
        expect={E("bindings[2].action.masterId")},
    ),
    case(
        "unknown profile in a preset scope",
        put("presets[0].values[0].scope", {"kind": "profile", "profileId": "nope"}),
        expect={E("presets[0].values[0].scope.profileId")},
    ),
    case(
        "known profile in a preset scope",
        put("presets[0].values[0].scope", {"kind": "profile", "profileId": "prof-par"}),
        expect=set(),
    ),
    # Commands embedded in bindings.
    case(
        "command: unknown playback",
        binding_with({"type": "GO", "playbackId": "nope"}),
        expect={E(f"{CMD}.playbackId")},
    ),
    case(
        "command: unknown playback (fader)",
        binding_with({"type": "SET_FADER", "playbackId": "nope", "level": 0.5}),
        expect={E(f"{CMD}.playbackId")},
    ),
    case(
        "command: unknown master",
        binding_with({"type": "SET_MASTER", "masterId": "nope", "level": 1}),
        expect={E(f"{CMD}.masterId")},
    ),
    case(
        "command: unknown preset",
        binding_with({"type": "APPLY_PRESET", "presetId": "nope"}),
        expect={E(f"{CMD}.presetId")},
    ),
    case(
        "command: unknown cue list",
        binding_with({"type": "RECORD_CUE", "cueListId": "nope", "merge": "merge"}),
        expect={E(f"{CMD}.cueListId")},
    ),
    case(
        "command: unknown fixture and universe",
        binding_with(
            {
                "type": "PATCH_FIXTURE",
                "fixtureId": "nope",
                "patch": {"universeId": "u9", "address": 1},
            }
        ),
        expect={E(f"{CMD}.fixtureId"), E(f"{CMD}.patch.universeId")},
    ),
    case(
        "command: unknown group in a selection",
        binding_with(
            {"type": "SELECT", "targets": {"kind": "group", "groupId": "nope"}, "mode": "add"}
        ),
        expect={E(f"{CMD}.targets.groupId")},
    ),
    case(
        "command: unknown preset in a set-attribute",
        binding_with(
            {
                "type": "SET_ATTRIBUTE",
                "attribute": "color",
                "value": {"kind": "preset", "presetId": "nope"},
            }
        ),
        expect={E(f"{CMD}.value.presetId")},
    ),
    case(
        "command: valid commands",
        binding_with({"type": "BLACKOUT", "on": True}),
        clone("bindings", 3, id="b-cmd2"),
        expect=set(),
    ),
]

MASTER_KINDS = [
    case(
        "bpm rate on a grand master",
        put(f"{PULSE}.rate.masterId", "m-gm"),
        expect={E(f"{PULSE}.rate.masterId")},
    ),
    case(
        "bpm rate on an unknown master",
        put(f"{PULSE}.rate.masterId", "nope"),
        expect={E(f"{PULSE}.rate.masterId")},
    ),
    case(
        "speedMasterId on a grand master",
        put(f"{PULSE}.speedMasterId", "m-gm"),
        expect={E(f"{PULSE}.speedMasterId")},
    ),
    case(
        "sizeMasterId on a speed master",
        put(f"{PULSE}.sizeMasterId", "m-speed"),
        expect={E(f"{PULSE}.sizeMasterId")},
    ),
    case(
        "sizeMasterId on a size master",
        push("masters", {"id": "m-size", "kind": "size", "name": "Size"}),
        put(f"{PULSE}.sizeMasterId", "m-size"),
        expect=set(),
    ),
    case(
        "tap action on a grand master",
        put("bindings[2].action", {"kind": "tap", "masterId": "m-gm"}),
        expect={E("bindings[2].action.masterId")},
    ),
    case(
        "tap action on a speed master",
        put("bindings[2].action", {"kind": "tap", "masterId": "m-speed"}),
        expect=set(),
    ),
    case(
        "tap command on a grand master",
        binding_with({"type": "TAP", "masterId": "m-gm"}),
        expect={E(f"{CMD}.masterId")},
    ),
    case(
        "set_bpm command on a speed master",
        binding_with({"type": "SET_BPM", "masterId": "m-speed", "bpm": 999}),
        expect=set(),
    ),
    case(
        "set_bpm command on a grand master",
        binding_with({"type": "SET_BPM", "masterId": "m-gm", "bpm": 120}),
        expect={E(f"{CMD}.masterId")},
    ),
    case(
        "set_bpm command with a tempo out of range",
        binding_with({"type": "SET_BPM", "masterId": "m-speed", "bpm": 1000}),
        expect={E(f"{CMD}.bpm")},
    ),
    case(
        "set_bpm command with no tempo",
        binding_with({"type": "SET_BPM", "masterId": "m-speed", "bpm": 0}),
        expect={E(f"{CMD}.bpm")},
    ),
    case(
        "chase rate on a grand master",
        put("cueLists[0].mode", "chase"),
        put(
            "cueLists[0].chase",
            {
                "rate": {"kind": "bpm", "masterId": "m-gm", "multiplier": 1},
                "direction": "forward",
                "crossfade": 0.5,
            },
        ),
        expect={E("cueLists[0].chase.rate.masterId")},
    ),
]

TARGETS = [
    case(
        "group member: unknown fixture",
        put("groups[0].members[1].fixtureId", "nope"),
        expect={E("groups[0].members[1].fixtureId")},
    ),
    case(
        "group member: element out of range",
        put("groups[0].members[1].element", 1),
        expect={E("groups[0].members[1].element")},
    ),
    case(
        "target list: element out of range",
        put(
            f"{ENTRY}[0].targets",
            {
                "kind": "targets",
                "refs": [
                    {"fixtureId": "fx-mh1", "element": 0},
                    {"fixtureId": "fx-par1", "element": 2},
                ],
            },
        ),
        expect={E(f"{ENTRY}[0].targets.refs[1].element")},
    ),
    case(
        "preset target scope: element out of range",
        put("presets[2].values[0].scope.target.element", 3),
        expect={E("presets[2].values[0].scope.target.element")},
    ),
    case(
        "per-target keys: unknown fixture, bad element, malformed, non-canonical",
        put(
            f"{ENTRY}[0].value",
            {
                "kind": "perTarget",
                "values": {
                    "fx-mh1:0": 0.5,
                    "nope:0": 1,
                    "fx-mh2:1": 1,
                    "fx-mh1": 1,
                    "fx-mh1:01": 1,
                },
            },
        ),
        expect={
            E(f'{ENTRY}[0].value.values["nope:0"]'),
            E(f'{ENTRY}[0].value.values["fx-mh2:1"]'),
            E(f'{ENTRY}[0].value.values["fx-mh1"]'),
            E(f'{ENTRY}[0].value.values["fx-mh1:01"]'),
        },
    ),
    case(
        "effect instance targets",
        put(
            f"{PULSE}.targets",
            {"kind": "targets", "refs": [{"fixtureId": "nope", "element": 0}]},
        ),
        expect={E(f"{PULSE}.targets.refs[0].fixtureId")},
    ),
    case(
        "release targets",
        put(
            "cueLists[0].cues[1].releases",
            [
                {
                    "targets": {"kind": "targets", "refs": [{"fixtureId": "nope", "element": 0}]},
                    "attributes": "all",
                }
            ],
        ),
        expect={E("cueLists[0].cues[1].releases[0].targets.refs[0].fixtureId")},
    ),
    case(
        "park target: element out of range",
        put(
            "park",
            [
                {
                    "slot": {
                        "target": {"fixtureId": "fx-mh1", "element": 1},
                        "attribute": "intensity",
                    },
                    "value": 1,
                }
            ],
        ),
        expect={E("park[0].slot.target.element")},
    ),
    case(
        "valid park entry",
        put(
            "park",
            [
                {
                    "slot": {"target": {"fixtureId": "fx-mh1", "element": 0}, "attribute": "gobo1"},
                    "value": {"slot": "breakup"},
                }
            ],
        ),
        expect=set(),
    ),
]

REVISIONS = [
    case(
        "profile revision drift is a warning",
        put("fixtures[0].profileRevision", "0"),
        expect={W("fixtures[0].profileRevision")},
    ),
]

RELEASE_PAN_NOPE = [
    {"targets": {"kind": "group", "groupId": "g-mh"}, "attributes": ["pan", "nope"]}
]
RELEASE_CONTROL = [{"targets": {"kind": "group", "groupId": "g-mh"}, "attributes": ["control"]}]
PARK_GOBO_SCALAR = [
    {"slot": {"target": {"fixtureId": "fx-mh1", "element": 0}, "attribute": "gobo1"}, "value": 1}
]
PARK_CONTROL = [
    {
        "slot": {"target": {"fixtureId": "fx-mh1", "element": 0}, "attribute": "control"},
        "value": {"slot": "reset"},
    }
]
PARK_UNKNOWN = [
    {"slot": {"target": {"fixtureId": "fx-mh1", "element": 0}, "attribute": "nope"}, "value": 1}
]

ATTRIBUTES_CASES = [
    case(
        "unknown attribute in an entry",
        put(f"{ENTRY}[0].attribute", "brightness"),
        expect={E(f"{ENTRY}[0].attribute")},
    ),
    case(
        "unknown attribute in a channel",
        put(f"{CH}[7].attribute", "zoomz"),
        expect={E(f"{CH}[7].attribute")},
    ),
    case(
        "unknown attribute in a capability parameter",
        put(f"{CH}[9].capabilities[2].param.attribute", "strobe"),
        expect={E(f"{CH}[9].capabilities[2].param.attribute")},
    ),
    case(
        "unknown attribute in a preset",
        put("presets[0].values[0].attribute", "colour"),
        expect={E("presets[0].values[0].attribute")},
    ),
    case(
        "unknown attribute in an effect layer",
        put("effects[0].layers[0].attribute", "sparkle"),
        expect={E("effects[0].layers[0].attribute")},
    ),
    case(
        "unknown attribute in a release",
        put("cueLists[0].cues[1].releases", RELEASE_PAN_NOPE),
        expect={E("cueLists[0].cues[1].releases[0].attributes[1]")},
    ),
    case(
        "unknown attribute in park",
        put("park", PARK_UNKNOWN),
        expect={E("park[0].slot.attribute")},
    ),
    case(
        "literal shape: colour for intensity",
        put(f"{ENTRY}[0].value.value", {"r": 1, "g": 1, "b": 1}),
        expect={E(f"{ENTRY}[0].value.value")},
    ),
    case(
        "per-target shape: discrete for pan",
        put(
            f"{ENTRY}[2].value",
            {"kind": "perTarget", "values": {"fx-mh1:0": {"slot": "open"}, "fx-mh2:0": 10}},
        ),
        expect={E(f'{ENTRY}[2].value.values["fx-mh1:0"]')},
    ),
    case(
        "preset shape: number for colour",
        put("presets[0].values[0].value", 0.5),
        expect={E("presets[0].values[0].value")},
    ),
    case("park shape: number for gobo", put("park", PARK_GOBO_SCALAR), expect={E("park[0].value")}),
    case(
        "spread on a discrete attribute",
        put(f"{ENTRY}[2].attribute", "gobo1"),
        put(
            f"{ENTRY}[2].value",
            {"kind": "spread", "from": {"slot": "open"}, "to": {"slot": "breakup"}},
        ),
        expect={E(f"{ENTRY}[2].value")},
    ),
    case(
        "spread shape",
        put(f"{ENTRY}[2].value.from", {"r": 1, "g": 0, "b": 0}),
        expect={E(f"{ENTRY}[2].value.from")},
    ),
    case(
        "spread on colour is allowed",
        put(
            f"{ENTRY}[1].value",
            {"kind": "spread", "from": {"r": 1, "g": 0, "b": 0}, "to": {"r": 0, "g": 0, "b": 1}},
        ),
        expect=set(),
    ),
    case(
        "scalar layer on colour",
        put("effects[0].layers[0].attribute", "color"),
        expect={E("effects[0].layers[0].attribute")},
    ),
    case(
        "scalar layer on a discrete attribute",
        put("effects[0].layers[0].attribute", "gobo1"),
        expect={E("effects[0].layers[0].attribute")},
    ),
    case(
        "control in a preset",
        put(
            "presets[0].values[0]",
            {"scope": {"kind": "global"}, "attribute": "control", "value": {"slot": "reset"}},
        ),
        expect={E("presets[0].values[0].attribute")},
    ),
    case(
        "control in a cue entry",
        put(f"{ENTRY}[0].attribute", "control"),
        put(f"{ENTRY}[0].value.value", {"slot": "lampOn"}),
        expect={E(f"{ENTRY}[0].attribute")},
    ),
    case(
        "control in a release",
        put("cueLists[0].cues[1].releases", RELEASE_CONTROL),
        expect={E("cueLists[0].cues[1].releases[0].attributes[0]")},
    ),
    case(
        "control in an effect",
        put("effects[0].layers[0].attribute", "control"),
        expect={E("effects[0].layers[0].attribute")},
    ),
    case("control in park", put("park", PARK_CONTROL), expect={E("park[0].slot.attribute")}),
    case(
        "control channels are fine in a profile",
        push(
            CH,
            {
                "offset": 13,
                "element": 0,
                "attribute": "control",
                "bytes": 1,
                "defaultDmx": 0,
                "capabilities": [
                    {"kind": "function", "dmx": [0, 127], "fn": "lampOff"},
                    {"kind": "function", "dmx": [128, 255], "fn": "lampOn"},
                ],
            },
        ),
        expect=set(),
    ),
]

PROFILES = [
    case(
        "element indices start at 0",
        put(f"{MH}.elements[0].index", 1),
        expect={E(f"{MH}.elements[0].index")},
    ),
    case(
        "element indices have no gaps",
        push(f"{MH}.elements", {"index": 2, "name": "Cell"}),
        expect={E(f"{MH}.elements[1].index")},
    ),
    case(
        "channel element out of range", put(f"{CH}[0].element", 1), expect={E(f"{CH}[0].element")}
    ),
    case("offset outside the footprint", put(f"{CH}[8].offset", 16), expect={E(f"{CH}[8].offset")}),
    case(
        "fine offset outside the footprint",
        put(f"{CH}[0].fineOffsets", [16]),
        expect={E(f"{CH}[0].fineOffsets[0]")},
    ),
    case(
        "implied fine offset outside the footprint",
        put("profiles[1].modes[0].channels[2].bytes", 2),
        expect={E("profiles[1].modes[0].channels[2].bytes")},
    ),
    case("two channels share an offset", put(f"{CH}[3].offset", 4), expect={E(f"{CH}[3].offset")}),
    case(
        "a fine offset takes another channel's offset",
        put(f"{CH}[0].fineOffsets", [2]),
        expect={E(f"{CH}[1].offset")},
    ),
    case(
        "fine offset count must be bytes − 1",
        put(f"{CH}[0].fineOffsets", [1, 13]),
        expect={E(f"{CH}[0].fineOffsets")},
    ),
    case("defaultDmx too big", put(f"{CH}[7].defaultDmx", 256), expect={E(f"{CH}[7].defaultDmx")}),
    case("16-bit defaultDmx at its maximum", put(f"{CH}[0].defaultDmx", 65535), expect=set()),
    case(
        "highlightDmx too big",
        put(f"{CH}[0].highlightDmx", 65536),
        expect={E(f"{CH}[0].highlightDmx")},
    ),
    case(
        "capability range too big",
        put(f"{CH}[7].capabilities[0].dmx", [0, 256]),
        expect={E(f"{CH}[7].capabilities[0].dmx")},
    ),
    case(
        "capability range reversed",
        put(f"{CH}[8].capabilities[0].dmx", [9, 0]),
        expect={E(f"{CH}[8].capabilities[0].dmx")},
    ),
    case(
        "capability ranges overlap",
        put(f"{CH}[8].capabilities[1].dmx", [9, 19]),
        expect={E(f"{CH}[8].capabilities[1].dmx")},
    ),
    case(
        "capability ranges out of order",
        put(f"{CH}[8].capabilities", GOBO_CAPS[::-1]),
        expect={E(f"{CH}[8].capabilities[1].dmx")},
    ),
    case(
        "colour channel without a component",
        drop(f"{CH}[2].component"),
        expect={E(f"{CH}[2].component")},
    ),
    case(
        "non-colour channel with a component",
        put(f"{CH}[7].component", "red"),
        expect={E(f"{CH}[7].component")},
    ),
    case(
        "duplicate (element, attribute, component)",
        put(f"{CH}[3].component", "red"),
        expect={E(f"{CH}[3]")},
    ),
    case(
        "slot capability: unknown wheel",
        put(f"{CH}[8].capabilities[0].wheel", "gobo9"),
        expect={E(f"{CH}[8].capabilities[0].wheel")},
    ),
    case(
        "slot capability: unknown slot",
        put(f"{CH}[8].capabilities[1].slot", "flower"),
        expect={E(f"{CH}[8].capabilities[1].slot")},
    ),
]

PATCH = [
    case(
        "footprint past channel 512",
        put("fixtures[1].patch.address", 500),
        expect={E("fixtures[1].patch.address")},
    ),
    case("footprint ending exactly at 512", put("fixtures[1].patch.address", 497), expect=set()),
    case(
        "overlapping footprints are a warning",
        put("fixtures[2].patch.address", 10),
        expect={W("fixtures[2].patch.address")},
    ),
    case(
        "same addresses in different universes do not overlap",
        push("universes", {"id": "u2", "name": "Side", "number": 2}),
        put("fixtures[2].patch", {"universeId": "u2", "address": 10}),
        expect=set(),
    ),
    case("unpatched fixture", put("fixtures[2].patch", None), expect=set()),
]

CUES = [
    case(
        "cue number not a decimal",
        put("cueLists[0].cues[1].number", "2a"),
        expect={E("cueLists[0].cues[1].number")},
    ),
    *[
        case(
            f"cue number {bad!r}",
            put("cueLists[0].cues[1].number", bad),
            expect={E("cueLists[0].cues[1].number")},
        )
        for bad in ["2.", ".5", "-2", "1.2.3", "", " 2", "٢"]
    ],
    case(
        "duplicate cue number",
        put("cueLists[0].cues[1].number", "1"),
        expect={E("cueLists[0].cues[1].number")},
    ),
    case(
        "duplicate cue number with a leading zero",
        put("cueLists[0].cues[1].number", "01"),
        expect={E("cueLists[0].cues[1].number")},
    ),
    case(
        "cue numbers descending",
        put("cueLists[0].cues[0].number", "3"),
        expect={E("cueLists[0].cues[1].number")},
    ),
    case(
        "1.10 comes after 1.9",
        put("cueLists[0].cues[0].number", "1.9"),
        put("cueLists[0].cues[1].number", "1.10"),
        expect=set(),
    ),
    case(
        "1.9 does not come after 1.10",
        put("cueLists[0].cues[0].number", "1.10"),
        put("cueLists[0].cues[1].number", "1.9"),
        expect={E("cueLists[0].cues[1].number")},
    ),
    case(
        "chase mode needs chase settings",
        put("cueLists[0].mode", "chase"),
        expect={E("cueLists[0].chase")},
    ),
    case(
        "chase mode with chase settings",
        put("cueLists[0].mode", "chase"),
        put(
            "cueLists[0].chase",
            {"rate": {"kind": "hz", "value": 2}, "direction": "bounce", "crossfade": 0.25},
        ),
        expect=set(),
    ),
]

GROUPS = [
    case(
        "layout cell count must be width × height",
        put("groups[0].layout", {"width": 2, "height": 2, "cells": [0, 1, None]}),
        expect={E("groups[0].layout.cells")},
    ),
    case(
        "layout cell index out of range",
        put("groups[0].layout", {"width": 2, "height": 1, "cells": [0, 2]}),
        expect={E("groups[0].layout.cells[1]")},
    ),
    case(
        "valid layout",
        put("groups[0].layout", {"width": 3, "height": 1, "cells": [1, None, 0]}),
        expect=set(),
    ),
]

SIDE = {"id": "u2", "name": "Side", "number": 2}
NODE = {"kind": "unicast", "host": "10.0.0.20"}
ARTNET_ROUTE = {
    "id": "r2",
    "universeId": "u2",
    "enabled": True,
    "protocol": "artnet",
    "portAddress": {"net": 0, "subNet": 0, "universe": 1},
    "destination": {"kind": "broadcast", "iface": "eth0"},
}

OUTPUT = [
    case("sACN CID not a UUID", put("output.sacnCid", "not-a-uuid"), expect={E("output.sacnCid")}),
    case(
        "sACN source name over 63 bytes",
        put("output.sacnSourceName", "x" * 64),
        expect={E("output.sacnSourceName")},
    ),
    case("sACN source name of 63 bytes", put("output.sacnSourceName", "x" * 63), expect=set()),
    case(
        "sACN source name counted in UTF-8 bytes",
        put("output.sacnSourceName", "é" * 32),
        expect={E("output.sacnSourceName")},
    ),
    case(
        "two show universes on one sACN universe",
        push("universes", SIDE),
        clone("output.routes", 0, id="r2", universeId="u2"),
        expect={E("output.routes[1].universe")},
    ),
    case(
        "one show universe sent twice on one sACN universe (multicast + unicast)",
        clone("output.routes", 0, id="r2", destination=NODE),
        expect=set(),
    ),
    case(
        "a disabled route on a taken sACN universe",
        push("universes", SIDE),
        clone("output.routes", 0, id="r2", universeId="u2", enabled=False),
        expect=set(),
    ),
    case(
        "a disabled route does not take its sACN universe",
        push("universes", SIDE),
        put("output.routes[0].enabled", False),
        clone("output.routes", 0, id="r2", universeId="u2", enabled=True),
        expect=set(),
    ),
    case(
        "sACN universes are not Art-Net port addresses",
        push("universes", SIDE),
        push("output.routes", ARTNET_ROUTE),
        expect=set(),
    ),
]

# Phase 1 profile rules (conversion depends on them).
PAR = "profiles[1].modes[0]"  # the virtual RGB par: [0] red [1] green [2] blue


def fn(lo: int, hi: int, name: str) -> dict[str, Any]:
    return {"kind": "function", "dmx": [lo, hi], "fn": name}


def extra_channel(offset: int, attribute: str, capabilities: list[Any], **more: Any) -> Op:
    """Append a 1-byte channel to the moving-head mode (offsets 13–15 are free)."""
    return push(
        CH,
        {
            "offset": offset,
            "element": 0,
            "attribute": attribute,
            "bytes": 1,
            "defaultDmx": 0,
            "capabilities": capabilities,
            **more,
        },
    )


PAR_CHANNEL = {
    "offset": 3,
    "element": 0,
    "bytes": 1,
    "defaultDmx": 0,
    "capabilities": [{"kind": "range", "dmx": [0, 255], "value": [0, 1]}],
}

PHASE1 = [
    # Capabilities by kind.
    case(
        "scalar channel without a range capability",
        put(f"{CH}[7].capabilities", [fn(0, 255, "zoomMacro")]),
        expect={E(f"{CH}[7].capabilities")},
    ),
    case(
        "colour channel without a range capability",
        put(f"{CH}[2].capabilities", [fn(0, 255, "redMacro")]),
        expect={E(f"{CH}[2].capabilities")},
    ),
    case(
        "wheel channel without a slot capability",
        put(f"{CH}[8].capabilities", [fn(0, 255, "wheelSpin")]),
        expect={E(f"{CH}[8].capabilities")},
    ),
    case(
        "shutter channel without a shutter function",
        put(f"{CH}[9].capabilities", [fn(0, 127, "lampOff"), fn(128, 255, "lampOn")]),
        expect={E(f"{CH}[9].capabilities")},
    ),
    # Default options: the shutter guard.
    case(
        "gobo channel without its default 'open'",
        put(f"{CH}[8].capabilities", GOBO_CAPS[1:]),
        expect={E(f"{CH}[8].capabilities")},
    ),
    case(
        "shutter channel without 'open'",
        drop(f"{CH}[9].capabilities[1]"),
        expect={E(f"{CH}[9].capabilities")},
    ),
    case(
        "prism channel without 'off'",
        extra_channel(13, "prism", [{"kind": "slot", "dmx": [0, 255], "slot": "on"}]),
        expect={E(f"{CH}[10].capabilities")},
    ),
    case(
        "prism channel with 'off'",
        extra_channel(
            13,
            "prism",
            [
                {"kind": "slot", "dmx": [0, 127], "slot": "off"},
                {"kind": "slot", "dmx": [128, 255], "slot": "on"},
            ],
        ),
        expect=set(),
    ),
    case(
        "colour macro channel without an option",
        extra_channel(13, "colorMacro", [{"kind": "range", "dmx": [0, 255], "value": [0, 1]}]),
        expect={E(f"{CH}[10].capabilities")},
    ),
    case(
        "colour macro channel needs no 'off' (its default is its own)",
        extra_channel(
            13,
            "colorMacro",
            [{"kind": "slot", "dmx": [0, 127], "slot": "red"}, fn(128, 255, "fade")],
            defaultDmx=200,
        ),
        expect=set(),
    ),
    case(
        "colour effect channel of functions",
        extra_channel(13, "colorEffect", [fn(0, 127, "jump"), fn(128, 255, "fade")]),
        expect=set(),
    ),
    case(
        "a duplicate 'open' range is fine (the first one wins)",
        push(f"{CH}[9].capabilities", fn(132, 255, "open")),
        expect=set(),
    ),
    # Function parameters.
    case(
        "function parameter on a discrete attribute",
        put(f"{CH}[9].capabilities[2].param.attribute", "gobo1"),
        expect={E(f"{CH}[9].capabilities[2].param.attribute")},
    ),
    case(
        "function parameter on colour",
        put(f"{CH}[9].capabilities[2].param.attribute", "color"),
        expect={E(f"{CH}[9].capabilities[2].param.attribute")},
    ),
    # Colour systems.
    case(
        "unknown emitter",
        put(f"{CH}[5].component", "infrared"),
        expect={E(f"{CH}[5].component")},
    ),
    case(
        "an undeclared custom emitter",
        put(f"{PAR}.footprint", 4),
        push(f"{PAR}.channels", {**PAR_CHANNEL, "attribute": "color", "component": "mint"}),
        expect={E(f"{PAR}.channels[3].component")},
    ),
    case(
        "a declared custom emitter",
        put(f"{PAR}.footprint", 4),
        push(f"{PAR}.channels", {**PAR_CHANNEL, "attribute": "color", "component": "mint"}),
        put("profiles[1].emitters", [{"id": "mint", "color": {"r": 0.6, "g": 1, "b": 0.8}}]),
        expect=set(),
    ),
    case(
        "additive and subtractive mixed on one element",
        put(f"{CH}[5].component", "cyanFlag"),
        expect={E(f"{CH}[5].component")},
    ),
    case(
        "additive without blue",
        put(f"{PAR}.channels[2].component", "white"),
        expect={E(f"{PAR}.elements[0]")},
    ),
    case(
        "subtractive without the yellow flag (no cascade into the strategy rule)",
        put(f"{PAR}.channels[0].component", "cyanFlag"),
        put(f"{PAR}.channels[1].component", "magentaFlag"),
        put(f"{PAR}.channels[2].attribute", "frost"),
        drop(f"{PAR}.channels[2].component"),
        expect={E(f"{PAR}.elements[0]")},
    ),
    case(
        "a valid CMY moving head",
        put(f"{CH}[2].component", "cyanFlag"),
        put(f"{CH}[3].component", "magentaFlag"),
        put(f"{CH}[4].component", "yellowFlag"),
        put(f"{CH}[5].attribute", "frost"),
        drop(f"{CH}[5].component"),
        expect=set(),
    ),
    # Intensity strategy.
    case(
        "dimmerChannel without an intensity channel",
        put(f"{CH}[6].attribute", "iris"),
        expect={E(f"{MH}.intensityStrategy")},
    ),
    case(
        "virtual on a fixture whose colour element has a dimmer",
        put(f"{MH}.intensityStrategy", "virtual"),
        expect={E(f"{MH}.intensityStrategy")},
    ),
    case(
        "dimmerChannel on the RGB par",
        put(f"{PAR}.intensityStrategy", "dimmerChannel"),
        expect={E(f"{PAR}.intensityStrategy")},
    ),
    case(
        "virtual with only subtractive colour",
        put(f"{PAR}.channels[0].component", "cyanFlag"),
        put(f"{PAR}.channels[1].component", "magentaFlag"),
        put(f"{PAR}.channels[2].component", "yellowFlag"),
        expect={E(f"{PAR}.intensityStrategy")},
    ),
    # Dimmer table.
    case(
        "a one-point dimmer table",
        put(f"{MH}.dimmerCurve", [0.5]),
        expect={E(f"{MH}.dimmerCurve")},
    ),
    case("a two-point dimmer table", put(f"{MH}.dimmerCurve", [0, 1]), expect=set()),
    # Orientation.
    case(
        "swapPanTilt with pan and tilt",
        put("fixtures[0].orientation.swapPanTilt", True),
        expect=set(),
    ),
    case(
        "swapPanTilt on an element with only pan",
        put("fixtures[0].orientation.swapPanTilt", True),
        put(f"{CH}[1].attribute", "frost"),
        # Phase 7: MH 1's tilt limits now have no tilt to act on
        expect={E("fixtures[0].orientation.swapPanTilt"), W("fixtures[0].limits.tilt")},
    ),
    case(
        "swapPanTilt on a fixture without pan or tilt",
        put("fixtures[2].orientation.swapPanTilt", True),
        expect=set(),
    ),
    # Control channels are untouched, so several per element are fine.
    case(
        "two control channels on one element",
        extra_channel(13, "control", [fn(0, 255, "reset")]),
        extra_channel(14, "control", [fn(0, 255, "program1")]),
        expect=set(),
    ),
]

PHASE2 = [
    case(
        "dup (scope, attribute) in a preset",
        clone("presets[2].values", 0),  # Audience: MH 1 pan, twice
        expect={E("presets[2].values[4].attribute")},
    ),
    case(
        "dup global value in a preset",
        clone("presets[0].values", 0, value={"r": 0, "g": 0, "b": 0.5}),
        expect={E("presets[0].values[1].attribute")},
    ),
    case(
        "one attribute in several scopes",
        push(
            "presets[0].values",
            {
                "scope": {"kind": "profile", "profileId": "prof-par"},
                "attribute": "color",
                "value": {"r": 0, "g": 0.2, "b": 1},
            },
        ),
        push(
            "presets[0].values",
            {
                "scope": {"kind": "target", "target": {"fixtureId": "fx-par1", "element": 0}},
                "attribute": "color",
                "value": {"r": 0, "g": 0.1, "b": 1},
            },
        ),
        expect=set(),
    ),
    case(
        "command: toggle",
        binding_with({"type": "TOGGLE_PLAYBACK", "playbackId": "pb-blue"}),
        expect=set(),
    ),
    case(
        "command: unknown playback (toggle)",
        binding_with({"type": "TOGGLE_PLAYBACK", "playbackId": "nope"}),
        expect={E(f"{CMD}.playbackId")},
    ),
]

SPEED = "masters[1]"  # Appendix A's speed master
TIMING = "cueLists[0].cues[0].timing"  # the Verse (tracking list)
RELEASE_ALL = [{"targets": {"kind": "group", "groupId": "g-mh"}, "attributes": "all"}]


def chase(rate: dict[str, Any]) -> list[Op]:
    """Turn the Song list into a chase with ``rate``."""
    settings = {"rate": rate, "direction": "forward", "crossfade": 0.25}
    return [put("cueLists[0].mode", "chase"), put("cueLists[0].chase", settings)]


def goto(number: str, playback: str = "pb-song") -> Op:
    return binding_with({"type": "GOTO", "playbackId": playback, "cueNumber": number})


PHASE4 = [
    # rates, in effects and chases
    case("effect rate: 0 Hz", put(f"{PULSE}.rate", {"kind": "hz", "value": 0}),
         expect={E(f"{PULSE}.rate.value")}),
    case("effect rate: negative Hz", put(f"{PULSE}.rate", {"kind": "hz", "value": -2}),
         expect={E(f"{PULSE}.rate.value")}),
    case("effect rate: 2 Hz", put(f"{PULSE}.rate", {"kind": "hz", "value": 2}), expect=set()),
    case("effect rate: multiplier 0", put(f"{PULSE}.rate.multiplier", 0),
         expect={E(f"{PULSE}.rate.multiplier")}),
    case("chase rate: 0 Hz", *chase({"kind": "hz", "value": 0}),
         expect={E("cueLists[0].chase.rate.value")}),
    case("chase rate: negative multiplier",
         *chase({"kind": "bpm", "masterId": "m-speed", "multiplier": -1}),
         expect={E("cueLists[0].chase.rate.multiplier")}),
    case("chase rate: ×0.25 on a speed master",
         *chase({"kind": "bpm", "masterId": "m-speed", "multiplier": 0.25}), expect=set()),
    # speed masters
    case("speed master: 0 BPM", put(f"{SPEED}.defaultBpm", 0),
         expect={E(f"{SPEED}.defaultBpm")}),
    case("speed master: 1000 BPM", put(f"{SPEED}.defaultBpm", 1000),
         expect={E(f"{SPEED}.defaultBpm")}),
    case("speed master: 999 BPM", put(f"{SPEED}.defaultBpm", 999), expect=set()),
    case("speed master: no steps", put(f"{SPEED}.multiplierSteps", []),
         expect={E(f"{SPEED}.multiplierSteps")}),
    case("speed master: a zero and a negative step",
         put(f"{SPEED}.multiplierSteps", [0.5, 0, 1, -2]),
         expect={E(f"{SPEED}.multiplierSteps[1]"), E(f"{SPEED}.multiplierSteps[3]")}),
    case("speed master: one step", put(f"{SPEED}.multiplierSteps", [1]), expect=set()),
    # Bézier curves: cue, family and entry timing
    case("bezier: cue curve within 0..1", put(f"{TIMING}.curve", {"bezier": [0, 0.1, 1, 1]}),
         expect=set()),
    case("bezier: cue curve outside 0..1",
         put(f"{TIMING}.curve", {"bezier": [0.4, -0.1, 0.2, 1.2]}),
         expect={E(f"{TIMING}.curve.bezier[1]"), E(f"{TIMING}.curve.bezier[3]")}),
    case("bezier: family curve",
         put(f"{TIMING}.perFamily",
             {"color": {"fade": 1, "delay": 0, "curve": {"bezier": [1.5, 0, 0, 1]}},
              "position": {"fade": 4, "delay": 0, "curve": "easeIn"}}),
         expect={E(f"{TIMING}.perFamily.color.curve.bezier[0]")}),
    case("bezier: entry curve", put(f"{ENTRY}[0].timing", {"curve": {"bezier": [0, 0, 1, 2]}}),
         expect={E(f"{ENTRY}[0].timing.curve.bezier[3]")}),
    # tracking-only fields
    case("releases without tracking", put("cueLists[1].cues[0].releases", RELEASE_ALL),
         expect={W("cueLists[1].cues[0].releases")}),
    case("empty releases without tracking", put("cueLists[1].cues[0].releases", []),
         expect=set()),
    case("block without tracking", put("cueLists[1].cues[0].block", True),
         expect={W("cueLists[1].cues[0].block")}),
    case("block false without tracking", put("cueLists[1].cues[0].block", False),
         expect=set()),
    case("releases and block with tracking",
         put("cueLists[0].cues[1].releases", RELEASE_ALL), put("cueLists[0].cues[1].block", True),
         expect=set()),
    # GOTO cue numbers
    case("goto command: an existing cue", goto("2"), expect=set()),
    case("goto command: a cue the list does not have", goto("7"),
         expect={W(f"{CMD}.cueNumber")}),
    case("goto command: not a cue number", goto("two"), expect={W(f"{CMD}.cueNumber")}),
    case("goto command: unknown playback", goto("2", "nope"), expect={E(f"{CMD}.playbackId")}),
]  # fmt: skip

LAYER = "effects[0].layers[0]"  # Appendix A's pulse: intensity, sine, multiply
WAVE = f"{LAYER}.waveform"
SPEED2 = {
    "id": "m-speed2",
    "kind": "speed",
    "name": "Speed 2",
    "defaultBpm": 90,
    "tap": True,
    "multiplierSteps": [1],
}


def layer(attribute: str, mode: str = "absolute", kind: str = "sine") -> dict[str, Any]:
    return {"attribute": attribute, "waveform": {"kind": kind}, "phaseOffset": 0, "mode": mode}


def colours(*palette: dict[str, Any]) -> Op:
    """Append a colour-cycle template (effects[1])."""
    return push(
        "effects",
        {
            "id": "ef-colours",
            "name": "Colours",
            "layers": [
                {
                    "attribute": "color",
                    "palette": list(palette),
                    "blend": "fade",
                    "mode": "absolute",
                }
            ],
        },
    )


PHASE5 = [
    # templates
    case("template without layers", put("effects[0].layers", []),
         expect={E("effects[0].layers")}),
    case("two absolute layers on one attribute",
         put("effects[0].layers", [layer("intensity"), layer("intensity", kind="triangle")]),
         expect={E("effects[0].layers[1].attribute")}),
    case("an absolute and an add layer on one attribute",
         put("effects[0].layers", [layer("intensity"), layer("intensity", "add")]), expect=set()),
    case("two add layers on one attribute",
         put("effects[0].layers", [layer("pan", "add"), layer("pan", "add")]), expect=set()),
    case("scalar layer on an attribute that snaps", put(f"{LAYER}.attribute", "positionSpeed"),
         expect={E(f"{LAYER}.attribute")}),
    # waveforms
    case("pulse: negative parts",
         put(WAVE, {"kind": "pulse", "attack": -0.1, "width": 0.2, "decay": -0.3}),
         expect={E(f"{WAVE}.attack"), E(f"{WAVE}.decay")}),
    case("pulse: longer than a cycle",
         put(WAVE, {"kind": "pulse", "attack": 0.5, "width": 0.4, "decay": 0.2}),
         expect={E(WAVE)}),
    case("pulse: exactly a cycle, with rounding",
         put(WAVE, {"kind": "pulse", "attack": 0.1, "width": 0.2, "decay": 0.7}), expect=set()),
    case("pulse: zero-length ramps",
         put(WAVE, {"kind": "pulse", "attack": 0, "width": 0.5, "decay": 0}), expect=set()),
    case("step without steps", put(WAVE, {"kind": "step", "steps": []}),
         expect={E(f"{WAVE}.steps")}),
    case("step with one step", put(WAVE, {"kind": "step", "steps": [0.5]}), expect=set()),
    case("curve without points", put(WAVE, {"kind": "curve", "points": []}),
         expect={E(f"{WAVE}.points")}),
    case("curve with one point", put(WAVE, {"kind": "curve", "points": [[0.5, 1]]}),
         expect=set()),
    case("curve: repeated and descending x",
         put(WAVE, {"kind": "curve", "points": [[0, 0], [0.5, 1], [0.5, 0], [1, 1], [0.8, 0]]}),
         expect={E(f"{WAVE}.points[2]"), E(f"{WAVE}.points[4]")}),
    case("curve: ascending x from 0 to 1",
         put(WAVE, {"kind": "curve", "points": [[0, 0], [0.5, 1], [1, 0]]}), expect=set()),
    # palettes
    case("colour layer: empty palette", colours(), expect={E("effects[1].layers[0].palette")}),
    case("colour layer: extras in a palette colour",
         colours({"r": 1, "g": 0, "b": 0}, {"r": 0, "g": 0, "b": 1, "w": 0.5, "uv": 1}),
         expect={W("effects[1].layers[0].palette[1]")}),
    case("two colour layers", colours({"r": 1, "g": 0, "b": 0}),
         push("effects[1].layers", {"attribute": "color", "palette": [{"r": 0, "g": 1, "b": 0}],
                                    "blend": "snap", "mode": "absolute"}),
         expect={E("effects[1].layers[1].attribute")}),
    # instances: size
    case("size: negative", put(f"{PULSE}.size", -0.1), expect={E(f"{PULSE}.size")}),
    case("size: above 1 with a multiply layer", put(f"{PULSE}.size", 1.5),
         expect={E(f"{PULSE}.size")}),
    case("size: 1 with a multiply layer", put(f"{PULSE}.size", 1), expect=set()),
    case("size: above 1 with an add layer", put(f"{LAYER}.mode", "add"),
         put(f"{PULSE}.size", 30), expect=set()),
    # instances: low and high
    case("low: not a number", put(f"{PULSE}.low", {"r": 1, "g": 0, "b": 0}),
         put(f"{PULSE}.high", {"slot": "open"}), expect={E(f"{PULSE}.low"), E(f"{PULSE}.high")}),
    case("absolute pan without low and high", put(LAYER, layer("pan")),
         expect={E(f"{PULSE}.low"), E(f"{PULSE}.high")}),
    case("absolute pan without high", put(LAYER, layer("pan")), put(f"{PULSE}.low", -90),
         expect={E(f"{PULSE}.high")}),
    case("absolute pan with low and high", put(LAYER, layer("pan")), put(f"{PULSE}.low", -90),
         put(f"{PULSE}.high", 90), expect=set()),
    case("absolute intensity without low and high", put(f"{LAYER}.mode", "absolute"),
         expect=set()),
    case("add pan without low and high", put(LAYER, layer("pan", "add")), expect=set()),
    case("absolute zoom on an unknown template",
         put(f"{PULSE}.templateId", "nope"), put(LAYER, layer("zoom")),
         expect={E(f"{PULSE}.templateId")}),
    # instances: speedMasterId
    case("speedMasterId on a BPM effect naming another master", push("masters", SPEED2),
         put(f"{PULSE}.speedMasterId", "m-speed2"), expect={W(f"{PULSE}.speedMasterId")}),
    case("speedMasterId on a BPM effect naming its own master",
         put(f"{PULSE}.speedMasterId", "m-speed"), expect=set()),
    case("speedMasterId on an Hz effect", push("masters", SPEED2),
         put(f"{PULSE}.rate", {"kind": "hz", "value": 1}),
         put(f"{PULSE}.speedMasterId", "m-speed2"), expect=set()),
    case("speedMasterId on a BPM effect naming no master", put(f"{PULSE}.speedMasterId", "nope"),
         expect={E(f"{PULSE}.speedMasterId")}),
]  # fmt: skip

OSC = {
    "id": "s-osc",
    "name": "TouchOSC",
    "kind": "osc",
    "match": {"port": 9000},
    "faderPickup": "jump",
}
WEB = {
    "id": "s-web",
    "name": "Phone",
    "kind": "web",
    "match": {"port": 8080},
    "faderPickup": "jump",
}
CC9 = {"kind": "midiCC", "channel": 1, "cc": 9}
CLOCK = {"kind": "midiClock"}
TAP = {"kind": "tap", "masterId": "m-speed"}
BLACKOUT = {"kind": "blackout"}
NEW = "bindings[3]"  # the binding `bind` appends


def bind(surface: str, input: dict[str, Any], action: dict[str, Any], **more: Any) -> Op:
    """Append a binding (bindings[3]) on ``surface``."""
    binding = {"id": "b-new", "surfaceId": surface, "input": input, "action": action}
    return push("bindings", {**binding, **more})


PHASE6 = [
    # surfaces: OSC and web surfaces listen on a port
    case("osc surface with a port", push("surfaces", OSC), expect=set()),
    case("osc surface without a port", push("surfaces", {**OSC, "match": {}}),
         expect={E("surfaces[1].match.port")}),
    case("web surface on port 0", push("surfaces", {**WEB, "match": {"port": 0}}),
         expect={E("surfaces[1].match.port")}),
    case("web surface on port 65536", push("surfaces", {**WEB, "match": {"port": 65536}}),
         expect={E("surfaces[1].match.port")}),
    case("two osc surfaces on one port", push("surfaces", OSC), clone("surfaces", 1, id="s-2"),
         expect={E("surfaces[2].match.port")}),
    case("an osc and a web surface on one port (UDP and TCP)", push("surfaces", OSC),
         push("surfaces", {**WEB, "match": {"port": 9000}}), expect=set()),
    case("osc feedback port", push("surfaces", {**OSC, "match": {"port": 1, "feedbackPort": 9001}}),
         expect=set()),
    case("osc feedback port out of range",
         push("surfaces", {**OSC, "match": {"port": 9000, "feedbackPort": 70000}}),
         expect={E("surfaces[1].match.feedbackPort")}),
    # inputs per surface kind
    case("osc input on an osc surface", push("surfaces", OSC),
         bind("s-osc", {"kind": "osc", "path": "/go"}, BLACKOUT), expect=set()),
    case("osc input on a midi surface", bind("s-midi", {"kind": "osc", "path": "/go"}, BLACKOUT),
         expect={W(f"{NEW}.input")}),
    case("midi input on an osc surface", push("surfaces", OSC), bind("s-osc", CC9, BLACKOUT),
         expect={W(f"{NEW}.input")}),
    case("hw input on a midi surface (reported as a limitation)",
         bind("s-midi", {"kind": "hw", "controlId": "f1"}, BLACKOUT), expect=set()),
    case("binding on a web surface", push("surfaces", WEB), bind("s-web", CC9, BLACKOUT),
         expect={W(f"{NEW}.surfaceId")}),
    case("feedback on a web surface", push("surfaces", WEB),
         bind("s-web", CC9, BLACKOUT, feedback={"kind": "led", "address": CC9}),
         expect={W(f"{NEW}.surfaceId"), W(f"{NEW}.feedback")}),
    case("binding on an unknown surface: no input warning", bind("nope", CC9, BLACKOUT),
         expect={E(f"{NEW}.surfaceId")}),
    # MIDI clock
    case("midi clock driving a tap", bind("s-midi", CLOCK, TAP), expect=set()),
    case("midi clock driving a blackout", bind("s-midi", CLOCK, BLACKOUT),
         expect={W(f"{NEW}.action")}),
    case("feedback to a midi clock",
         put("bindings[0].feedback", {"kind": "led", "address": CLOCK}),
         expect={E("bindings[0].feedback.address")}),
    # actions
    case("momentary blackout", bind("s-midi", CC9, {**BLACKOUT, "momentary": True}),
         expect=set()),
    case("pageAbs naming a page", bind("s-midi", CC9, {"kind": "pageAbs", "number": 1}),
         expect=set()),
    case("pageAbs naming no page", bind("s-midi", CC9, {"kind": "pageAbs", "number": 2}),
         expect={W(f"{NEW}.action.number")}),
    # goto buttons
    case("gotoCue naming a cue", put("playbacks[0].buttons", ["go", "goto"]),
         put("playbacks[0].gotoCue", "2"), expect=set()),
    case("gotoCue naming no cue", put("playbacks[0].gotoCue", "7"),
         expect={W("playbacks[0].gotoCue")}),
    case("goto button without gotoCue", put("playbacks[0].buttons", ["goto", "go", "goto"]),
         expect={W("playbacks[0].buttons[0]"), W("playbacks[0].buttons[2]")}),
    # embedded page-relative commands
    case("SET_FADER by slot", binding_with({"type": "SET_FADER", "slot": 7, "level": 1}),
         expect=set()),
    case("SET_FADER by neither", binding_with({"type": "SET_FADER", "level": 1}),
         expect={E(CMD)}),
    case("SET_FADER by both",
         binding_with({"type": "SET_FADER", "playbackId": "pb-song", "slot": 0, "level": 1}),
         expect={E(CMD)}),
    case("SET_FADER naming no playback",
         binding_with({"type": "SET_FADER", "playbackId": "nope", "level": 1}),
         expect={E(f"{CMD}.playbackId")}),
    case("PLAYBACK_BUTTON by slot",
         binding_with({"type": "PLAYBACK_BUTTON", "slot": 0, "button": 1, "down": True}),
         expect=set()),
    case("PLAYBACK_BUTTON by playback",
         binding_with({"type": "PLAYBACK_BUTTON", "playbackId": "pb-song", "button": 0,
                       "down": False}), expect=set()),
    case("PLAYBACK_BUTTON by neither",
         binding_with({"type": "PLAYBACK_BUTTON", "button": 0, "down": True}), expect={E(CMD)}),
    case("PLAYBACK_BUTTON naming no playback",
         binding_with({"type": "PLAYBACK_BUTTON", "playbackId": "x", "button": 0, "down": True}),
         expect={E(f"{CMD}.playbackId")}),
    case("PAGE by number", binding_with({"type": "PAGE", "number": 1}), expect=set()),
    case("PAGE by delta", binding_with({"type": "PAGE", "delta": -1}), expect=set()),
    case("PAGE by both", binding_with({"type": "PAGE", "number": 1, "delta": 1}),
         expect={E(CMD)}),
    case("PAGE by neither", binding_with({"type": "PAGE"}), expect={E(CMD)}),
    case("PAGE naming no page", binding_with({"type": "PAGE", "number": 3}),
         expect={W(f"{CMD}.number")}),
    case("BLACKOUT toggle", binding_with({"type": "BLACKOUT"}), expect=set()),
]  # fmt: skip

LIMITS = "fixtures[0].limits"  # MH 1: tilt -120..120; the profile travels ±270° pan, ±135° tilt
PARK_PAN = {
    "slot": {"target": {"fixtureId": "fx-mh1", "element": 0}, "attribute": "pan"},
    "value": 0,
}
PARK_TILT = {
    "slot": {"target": {"fixtureId": "fx-mh1", "element": 0}, "attribute": "tilt"},
    "value": 100,
}
PARK_DIM2 = {
    "slot": {"target": {"fixtureId": "fx-mh2", "element": 0}, "attribute": "intensity"},
    "value": 0.8,
}
USB = {
    "id": "r-usb",
    "universeId": "u1",
    "enabled": True,
    "protocol": "dmxUsb",
    "device": {"driver": "enttecPro", "port": "/dev/ttyUSB0"},
    "refreshHz": 40,
}
OUTPUT_OFF = {"kind": "command", "command": {"type": "OUTPUT", "on": False}}
NOTE9 = {"kind": "midiNote", "channel": 1, "note": 9}

PHASE7 = [
    # limits: order, travel, attributes
    case("pan limits", put(f"{LIMITS}.pan", [-90, 90]), expect=set()),
    case("pan limits of one point", put(f"{LIMITS}.pan", [30, 30]), expect=set()),
    case("pan minimum above its maximum", put(f"{LIMITS}.pan", [90, -90]),
         expect={E(f"{LIMITS}.pan")}),
    case("tilt minimum above its maximum", put(f"{LIMITS}.tilt", [10, -10]),
         expect={E(f"{LIMITS}.tilt")}),
    case("pan limits at the travel's ends", put(f"{LIMITS}.pan", [-270, 270]), expect=set()),
    case("pan limit past the travel", put(f"{LIMITS}.pan", [-300, 0]),
         expect={W(f"{LIMITS}.pan")}),
    case("tilt limit past the travel", put(f"{LIMITS}.tilt", [-120, 140]),
         expect={W(f"{LIMITS}.tilt")}),
    case("travel unknown: no warning", drop("profiles[0].physical.panRange"),
         put(f"{LIMITS}.pan", [-300, 0]), expect=set()),
    case("pan limits on a fixture without pan", put("fixtures[2].limits", {"pan": [-10, 10]}),
         expect={W("fixtures[2].limits.pan")}),
    case("tilt limits on a fixture without tilt", put("fixtures[2].limits", {"tilt": [-10, 10]}),
         expect={W("fixtures[2].limits.tilt")}),
    case("intensityMax on a virtual dimmer", put("fixtures[2].limits", {"intensityMax": 0.5}),
         expect=set()),
    case("intensityMax on a dimmer channel", put(f"{LIMITS}.intensityMax", 0.7), expect=set()),
    # park
    case("park pan and tilt", push("park", PARK_PAN), push("park", PARK_TILT), expect=set()),
    case("two park entries for one slot", push("park", PARK_PAN),
         push("park", {**PARK_PAN, "value": 10}), expect={E("park[1].slot")}),
    case("one attribute parked on two fixtures", push("park", PARK_PAN),
         push("park", {**PARK_PAN, "slot": {**PARK_PAN["slot"],
                                            "target": {"fixtureId": "fx-mh2", "element": 0}}}),
         expect=set()),
    case("parked tilt beyond the limits", push("park", {**PARK_TILT, "value": 130}),
         expect={W("park[0].value")}),
    case("parked tilt at the limit", push("park", {**PARK_TILT, "value": -120}), expect=set()),
    case("parked intensity above intensityMax", put("fixtures[1].limits", {"intensityMax": 0.5}),
         push("park", PARK_DIM2), expect={W("park[0].value")}),
    case("parked intensity under intensityMax", put("fixtures[1].limits", {"intensityMax": 0.9}),
         push("park", PARK_DIM2), expect=set()),
    # DMX-USB ports
    case("one DMX-USB route", push("output.routes", USB), expect=set()),
    case("two DMX-USB routes on one port", push("output.routes", USB),
         push("output.routes", {**USB, "id": "r-usb2"}),
         expect={E("output.routes[2].device.port")}),
    case("a disabled DMX-USB route on a used port", push("output.routes", USB),
         push("output.routes", {**USB, "id": "r-usb2", "enabled": False}), expect=set()),
    case("two DMX-USB routes on two ports", push("output.routes", USB),
         push("output.routes", {**USB, "id": "r-usb2",
                                "device": {"driver": "enttecPro", "port": "/dev/ttyUSB1"}}),
         expect=set()),
    # the strobe cap: both moving heads strobe at 1..20 Hz
    case("strobe cap above the slowest strobe", put("safety", {"strobeMaxHz": 10}), expect=set()),
    case("strobe cap at the slowest strobe", put("safety", {"strobeMaxHz": 1}), expect=set()),
    case("strobe cap below the slowest strobe", put("safety", {"strobeMaxHz": 0.5}),
         expect={W("fixtures[0]"), W("fixtures[1]")}),
    case("no cap", put("safety", {}), expect=set()),
    # output off on a fader
    case("output off on a note", bind("s-midi", NOTE9, OUTPUT_OFF), expect=set()),
    case("output off on a CC", bind("s-midi", CC9, OUTPUT_OFF), expect={W(f"{NEW}.input")}),
    case("output off on a CC button with an LED", bind(
        "s-midi", CC9, OUTPUT_OFF, feedback={"kind": "led", "address": CC9}), expect=set()),
    case("output off on pitch bend",
         bind("s-midi", {"kind": "midiPitchBend", "channel": 1}, OUTPUT_OFF),
         expect={W(f"{NEW}.input")}),
    case("output on on a CC",
         bind("s-midi", CC9, {"kind": "command", "command": {"type": "OUTPUT", "on": True}}),
         expect=set()),
    case("output off on an OSC path", push("surfaces", OSC),
         bind("s-osc", {"kind": "osc", "path": "/out"}, OUTPUT_OFF), expect=set()),
]  # fmt: skip

ALL_CASES = [
    *IDENTITY,
    *NUMBERS,
    *REFERENCES,
    *MASTER_KINDS,
    *TARGETS,
    *REVISIONS,
    *ATTRIBUTES_CASES,
    *PROFILES,
    *PATCH,
    *CUES,
    *GROUPS,
    *OUTPUT,
    *PHASE1,
    *PHASE2,
    *PHASE4,
    *PHASE5,
    *PHASE6,
    *PHASE7,
]


def _issues(doc: Doc) -> set[tuple[str, str]]:
    show, issues = validate_show(json.dumps(doc))
    assert show is not None, f"structurally invalid: {issues}"
    return {(issue.severity, issue.path) for issue in issues}


@pytest.mark.parametrize("rule", ALL_CASES, ids=[c.name for c in ALL_CASES])
def test_semantic_rule(appendix_a: Doc, rule: Case) -> None:
    for op in rule.ops:
        op(appendix_a)
    assert _issues(appendix_a) == rule.expected


def test_unmodified_appendix_a_has_no_issues(appendix_a: Doc) -> None:
    assert _issues(appendix_a) == set()


def test_demo_show_has_no_issues(demo_path: Path) -> None:
    show, issues = validate_show(demo_path.read_bytes())
    assert show is not None
    assert issues == []


def test_every_issue_is_collected(appendix_a: Doc) -> None:
    for op in (
        put("fixtures[0].profileId", "nope"),
        put("groups[0].members[1].element", 5),
        put("cueLists[0].cues[1].number", "1"),
        put("output.sacnCid", "nope"),
        put("fixtures[2].patch.address", 20),
    ):
        op(appendix_a)
    assert _issues(appendix_a) == {
        E("fixtures[0].profileId"),
        E("groups[0].members[1].element"),
        E("cueLists[0].cues[1].number"),
        E("output.sacnCid"),
        W("fixtures[2].patch.address"),
    }


def test_issues_carry_readable_messages(appendix_a: Doc) -> None:
    put("cueLists[2].cues[0].effects[0].rate.masterId", "m-gm")(appendix_a)
    _, issues = validate_show(json.dumps(appendix_a))
    assert [str(issue) for issue in issues] == [
        f"{PULSE}.rate.masterId: Master 'm-gm' is a grand master; expected a speed master"
    ]


def test_phase_4_messages(appendix_a: Doc) -> None:
    for op in (
        put(f"{PULSE}.rate", {"kind": "hz", "value": 0}),
        put(f"{SPEED}.defaultBpm", 1200),
        put(f"{TIMING}.curve", {"bezier": [0.4, 0, 1.25, 1]}),
        put("cueLists[1].cues[0].block", True),
        goto("7"),
    ):
        op(appendix_a)
    _, issues = validate_show(json.dumps(appendix_a))
    assert [str(issue) for issue in issues] == [
        f"{TIMING}.curve.bezier[2]: Bézier control values must be within 0..1, got 1.25",
        "cueLists[1].cues[0].block: block has no effect without tracking",
        f"{PULSE}.rate.value: A rate must be greater than 0 Hz, got 0",
        f"{SPEED}.defaultBpm: The tempo must be greater than 0 and at most 999 BPM, got 1200",
        f"{CMD}.cueNumber: Cue list 'Song' has no cue '7'",
    ]


def test_phase_6_messages(appendix_a: Doc) -> None:
    for op in (
        put("playbacks[0].buttons", ["goto"]),
        put("playbacks[1].gotoCue", "7"),
        push("surfaces", {**OSC, "match": {}}),
        push("surfaces", {**WEB, "match": {"port": 8080, "feedbackPort": 0}}),
        clone("surfaces", 2, id="s-web2"),
        bind("s-midi", CLOCK, {"kind": "pageAbs", "number": 2}, id="b4"),
        put("bindings[0].feedback", {"kind": "led", "address": CLOCK}),
        bind("s-osc", CC9, BLACKOUT, id="b5"),
        bind("s-web", CC9, BLACKOUT, feedback={"kind": "led", "address": CC9}, id="b6"),
        bind("s-midi", CC9, {"kind": "command", "command": {"type": "PAGE"}}, id="b7"),
        bind(
            "s-midi",
            CC9,
            {"kind": "command", "command": {"type": "SET_FADER", "level": 0}},
            id="b8",
        ),
    ):
        op(appendix_a)
    _, issues = validate_show(json.dumps(appendix_a))
    assert [str(issue) for issue in issues] == [
        "playbacks[0].buttons[0]: A goto button needs the playback's gotoCue; it does nothing",
        "playbacks[1].gotoCue: Cue list 'Blue' has no cue '7'",
        "surfaces[1].match.port: An osc surface needs a port from 1 to 65535, got None",
        "surfaces[2].match.feedbackPort: The feedback port must be from 1 to 65535, got 0",
        "surfaces[3].match.port: Port 8080 is already used by surfaces[2]",
        "surfaces[3].match.feedbackPort: The feedback port must be from 1 to 65535, got 0",
        "bindings[0].feedback.address: Feedback cannot be sent to a MIDI clock input",
        "bindings[3].action: A MIDI clock input only drives tap actions; it does nothing",
        "bindings[3].action.number: There is no page 2",
        "bindings[4].input: osc surface 's-osc' cannot send midiCC inputs; "
        "this binding does nothing",
        "bindings[5].surfaceId: Web surface 's-web' sends commands of its own; "
        "this binding does nothing",
        "bindings[5].feedback: Web surface 's-web' shows state by itself; "
        "this feedback is not sent",
        "bindings[6].action.command: PAGE needs exactly one of 'number' and 'delta'",
        "bindings[7].action.command: SET_FADER needs exactly one of 'playbackId' and 'slot'",
    ]


def test_phase_7_messages(appendix_a: Doc) -> None:
    for op in (
        put(f"{LIMITS}.pan", [90, -90]),
        put(f"{LIMITS}.tilt", [-120, 140]),
        put("fixtures[2].limits", {"pan": [-10, 10]}),
        put("fixtures[1].limits", {"intensityMax": 0.5}),
        push("park", PARK_PAN),
        push("park", {**PARK_PAN, "value": 10}),
        push("park", {**PARK_TILT, "value": 150}),
        push("park", PARK_DIM2),
        push("output.routes", USB),
        push("output.routes", {**USB, "id": "r-usb2"}),
        put("safety", {"strobeMaxHz": 0.5}),
        bind("s-midi", CC9, OUTPUT_OFF),
    ):
        op(appendix_a)
    _, issues = validate_show(json.dumps(appendix_a))
    assert [str(issue) for issue in issues] == [
        "fixtures[0].limits.pan: The minimum 90° is above the maximum -90°",
        "fixtures[0].limits.tilt: Tilt limits -120°..140° reach past the travel of profile "
        "'prof-mh' (±135°)",
        "fixtures[0]: 'MH 1' strobes no slower than 1 Hz; the cap is 0.5 Hz",
        "fixtures[1]: 'MH 2' strobes no slower than 1 Hz; the cap is 0.5 Hz",
        "fixtures[2].limits.pan: 'Par 1' has no pan; this limit does nothing",
        "bindings[3].input: OUTPUT off is sent each time this control is pushed up; "
        "bind it to a button",
        "output.routes[2].device.port: Port '/dev/ttyUSB0' is already used by route 'r-usb'",
        "park[1].slot: 'MH 1' element 0 pan is already parked by park[0]",
        "park[2].value: Parked tilt 150° is outside the fixture's limits -120°..140°; "
        "the limits win",
        "park[3].value: Parked intensity 0.8 is above the fixture's intensityMax 0.5; "
        "the limit wins",
    ]


@pytest.mark.parametrize(
    "name",
    ["phase3_built_show", "phase4_song_show", "phase5_effects_show", "phase6_surfaces_show"],
)
def test_golden_shows_have_no_issues(name: str) -> None:
    golden = Path(__file__).parent / "golden" / f"{name}.json"
    show, issues = validate_show(golden.read_bytes())
    assert show is not None
    assert issues == []


def test_phase_5_messages(appendix_a: Doc) -> None:
    for op in (
        put(f"{LAYER}.attribute", "positionSpeed"),
        put(WAVE, {"kind": "pulse", "attack": -0.25, "width": 0.75, "decay": 0.75}),
        colours({"r": 1, "g": 0, "b": 0, "w": 1, "a": 0}),
        push("masters", SPEED2),
        put(f"{PULSE}.speedMasterId", "m-speed2"),
        put(f"{PULSE}.size", 2),
    ):
        op(appendix_a)
    _, issues = validate_show(json.dumps(appendix_a))
    assert [str(issue) for issue in issues] == [
        f"{LAYER}.attribute: Effects cannot drive 'positionSpeed': it snaps instead of fading",
        f"{WAVE}.attack: A pulse's attack must be 0 or more, got -0.25",
        f"{WAVE}: A pulse's attack + width + decay is a fraction of a cycle and must be at "
        "most 1, got 1.25",
        "effects[1].layers[0].palette[0]: A colour layer sets r, g and b and derives the other "
        "emitters; 'w', 'a' ignored",
        f"{PULSE}.speedMasterId: A BPM effect follows its rate's master 'm-speed'; speed master "
        "'m-speed2' is ignored",
        f"{PULSE}.size: An effect with a multiply layer needs a size within 0..1, got 2",
    ]
    put(LAYER, layer("tilt"))(appendix_a)
    put(f"{PULSE}.low", {"slot": "open"})(appendix_a)
    put(f"{PULSE}.size", -1)(appendix_a)
    _, issues = validate_show(json.dumps(appendix_a))
    assert [str(issue) for issue in issues if issue.path.startswith(PULSE)] == [
        f"{PULSE}.speedMasterId: A BPM effect follows its rate's master 'm-speed'; speed master "
        "'m-speed2' is ignored",
        f"{PULSE}.size: The size must be a finite number of 0 or more, got -1",
        f"{PULSE}.low: low must be a number",
        f"{PULSE}.high: high is required: 'tilt' has no fixed range to sweep",
    ]
    push("effects[0].layers", layer("zoom"))(appendix_a)
    _, issues = validate_show(json.dumps(appendix_a))
    assert [str(issue) for issue in issues if issue.path == f"{PULSE}.high"] == [
        f"{PULSE}.high: high is required: 'tilt', 'zoom' have no fixed range to sweep",
    ]


def test_validate_effect_checks_an_instance_outside_the_show(appendix_a: Doc) -> None:
    show, _ = validate_show(json.dumps(appendix_a))
    assert show is not None
    pulse = copy.deepcopy(show["cueLists"][2]["cues"][0]["effects"][0])
    assert validate_effect(show, pulse) == []
    pulse["size"] = math.inf
    pulse["templateId"] = "nope"
    pulse["sizeMasterId"] = "m-gm"
    assert [str(issue) for issue in validate_effect(show, pulse, "programmer.effects[0]")] == [
        "programmer.effects[0].templateId: Unknown effect template 'nope'",
        "programmer.effects[0].sizeMasterId: Master 'm-gm' is a grand master; expected a size "
        "master",
        "programmer.effects[0].size: The size must be a finite number of 0 or more, got inf",
    ]
    pulse["templateId"] = "ef-pulse"
    pulse["size"] = 1.5
    del pulse["sizeMasterId"]
    assert [(i.severity, i.path) for i in validate_effect(show, pulse)] == [E("effect.size")]


def test_sacn_universe_conflict_message(appendix_a: Doc) -> None:
    push("universes", SIDE)(appendix_a)
    clone("output.routes", 0, id="r2", universeId="u2")(appendix_a)
    _, issues = validate_show(json.dumps(appendix_a))
    assert [str(issue) for issue in issues] == [
        "output.routes[1].universe: sACN universe 1 is already sent by route 'r1' "
        "from universe 'u1'"
    ]


def test_duplicate_preset_value_messages(appendix_a: Doc) -> None:
    clone("presets[2].values", 0)(appendix_a)
    clone("presets[0].values", 0)(appendix_a)
    _, issues = validate_show(json.dumps(appendix_a))
    assert [str(issue) for issue in issues] == [
        "presets[0].values[1].attribute: Duplicate 'color' value for the global scope "
        "(first at presets[0].values[0])",
        "presets[2].values[4].attribute: Duplicate 'pan' value for target 'fx-mh1:0' "
        "(first at presets[2].values[0])",
    ]


def test_semantic_errors_still_return_the_show(appendix_a: Doc) -> None:
    put("playbacks[0].cueListId", "nope")(appendix_a)
    show, issues = validate_show(json.dumps(appendix_a))
    assert show is not None
    assert has_errors(issues)


# ---------------------------------------------------- parse and version steps


def _only_issue(text: str | bytes) -> tuple[str, str, str]:
    show, issues = validate_show(text)
    assert show is None
    assert len(issues) == 1
    return issues[0].severity, issues[0].path, issues[0].message


def test_invalid_json_reports_line_and_column() -> None:
    severity, path, message = _only_issue('{\n  "schemaVersion": 1\n  "meta": {}\n}')
    assert (severity, path) == ("error", "")
    assert "line 3, column 3" in message


def test_invalid_utf8() -> None:
    assert _only_issue(b'{"schemaVersion": 1, "x": "\xff"}')[:2] == ("error", "")


def test_root_must_be_an_object() -> None:
    assert _only_issue("[]")[:2] == ("error", "")


def test_schema_version_is_required() -> None:
    assert _only_issue("{}")[:2] == ("error", "schemaVersion")


@pytest.mark.parametrize("version", ['"1"', "true", "1.0"])
def test_schema_version_must_be_an_integer(version: str) -> None:
    assert _only_issue(f'{{"schemaVersion": {version}}}')[:2] == ("error", "schemaVersion")


def test_other_schema_versions_are_refused_before_structural_checks() -> None:
    # Everything else about this document is wrong too, but only the version is reported.
    severity, path, message = _only_issue('{"schemaVersion": 2, "bogus": true}')
    assert (severity, path) == ("error", "schemaVersion")
    assert "Unsupported schema version 2" in message
