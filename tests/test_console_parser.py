"""Console grammar: line → action, one case per grammar row, and its errors (phase-3-plan §5.10)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from builders import APPENDIX_A, DEMO, busk_rig, cue, cue_list, load_doc, show_of, speed_master
from busk.console.parser import (
    HELP,
    Context,
    Nothing,
    ParseError,
    Query,
    Quit,
    Save,
    Source,
    Submit,
    SubmitAll,
    parse,
    tokenize,
)
from busk.session.ids import CounterIds
from busk.session.library import EffectLibrary, ProfileLibrary, builtin_directory
from busk.session.programmer import Programmer, slot_key

LIBRARY = ProfileLibrary()
PROFILES = builtin_directory()


def context(path: Path = APPENDIX_A) -> Context:
    return Context(show_of(load_doc(path)), LIBRARY, CounterIds(), iface="eth9")


def command(line: str, path: Path = APPENDIX_A) -> dict[str, Any]:
    action = parse(line, context(path))
    assert isinstance(action, Submit), action
    return dict(action.command)


MH1, MH2, PAR = (
    {"fixtureId": "fx-mh1", "element": 0},
    {"fixtureId": "fx-mh2", "element": 0},
    {"fixtureId": "fx-par1", "element": 0},
)
VERSE = ["cueLists", {"id": "cl-song"}, "cues", {"id": "c-verse"}]

COMMANDS: list[tuple[str, dict[str, Any]]] = [
    # selection
    (
        "sel fixture 101 thru 102",
        {"type": "SELECT", "targets": {"kind": "targets", "refs": [MH1, MH2]}, "mode": "replace"},
    ),
    (
        "sel fixture 102 thru 101",
        {"type": "SELECT", "targets": {"kind": "targets", "refs": [MH2, MH1]}, "mode": "replace"},
    ),
    (
        "sel 201",
        {"type": "SELECT", "targets": {"kind": "targets", "refs": [PAR]}, "mode": "replace"},
    ),
    (
        "sel + group 2",
        {"type": "SELECT", "targets": {"kind": "group", "groupId": "g-par"}, "mode": "add"},
    ),
    (
        "sel - fixture 101",
        {"type": "SELECT", "targets": {"kind": "targets", "refs": [MH1]}, "mode": "remove"},
    ),
    (
        "sel group 1, fixture 201, fixture 102",
        {
            "type": "SELECT",
            "targets": {"kind": "targets", "refs": [MH1, MH2, PAR]},
            "mode": "replace",
        },
    ),
    ("sel none", {"type": "SELECT", "targets": {"kind": "targets", "refs": []}, "mode": "replace"}),
    ("sel playback 3", {"type": "SELECT_PLAYBACK", "playbackId": "pb-blue", "mode": "replace"}),
    # values
    (
        "set pan 45",
        {"type": "SET_ATTRIBUTE", "attribute": "pan", "value": {"kind": "literal", "value": 45}},
    ),
    (
        "set intensity 50%",
        {
            "type": "SET_ATTRIBUTE",
            "attribute": "intensity",
            "value": {"kind": "literal", "value": 0.5},
        },
    ),
    (
        "set Tilt -12.5",
        {
            "type": "SET_ATTRIBUTE",
            "attribute": "tilt",
            "value": {"kind": "literal", "value": -12.5},
        },
    ),
    (
        "set color 1 0.5 0 w 20%",
        {
            "type": "SET_ATTRIBUTE",
            "attribute": "color",
            "value": {"kind": "literal", "value": {"r": 1, "g": 0.5, "b": 0, "w": 0.2}},
        },
    ),
    (
        "set gobo1 breakup",
        {
            "type": "SET_ATTRIBUTE",
            "attribute": "gobo1",
            "value": {"kind": "literal", "value": {"slot": "breakup"}},
        },
    ),
    (
        "set pan spread -45 45 center",
        {
            "type": "SET_ATTRIBUTE",
            "attribute": "pan",
            "value": {"kind": "spread", "from": -45, "to": 45, "curve": "center"},
        },
    ),
    (
        "set color spread 1 0 0 to 0 0 1",
        {
            "type": "SET_ATTRIBUTE",
            "attribute": "color",
            "value": {
                "kind": "spread",
                "from": {"r": 1, "g": 0, "b": 0},
                "to": {"r": 0, "g": 0, "b": 1},
            },
        },
    ),
    (
        "set color preset color 1",
        {
            "type": "SET_ATTRIBUTE",
            "attribute": "color",
            "value": {"kind": "preset", "presetId": "pr-blue"},
        },
    ),
    ("preset position 1", {"type": "APPLY_PRESET", "presetId": "pr-aud"}),
    ("clear", {"type": "CLEAR_PROGRAMMER"}),
    ("blind on", {"type": "BLIND", "on": True}),
    ("highlight on", {"type": "HIGHLIGHT", "on": True}),
    ("highlight off", {"type": "HIGHLIGHT", "on": False}),
    # record
    ('record group 3 "Odd"', {"type": "RECORD_GROUP", "number": 3, "name": "Odd"}),
    ("record group 1 merge", {"type": "RECORD_GROUP", "number": 1, "merge": "merge"}),
    (
        'record preset color 3 "Green"',
        {"type": "RECORD_PRESET", "pool": "color", "number": 3, "scope": "global", "name": "Green"},
    ),
    (
        "record preset position 2 profile replace",
        {
            "type": "RECORD_PRESET",
            "pool": "position",
            "number": 2,
            "scope": "profile",
            "merge": "replace",
        },
    ),
    (
        "record preset beam 1",
        {"type": "RECORD_PRESET", "pool": "beam", "number": 1, "scope": "profile"},
    ),
    (
        "record preset all 1",
        {"type": "RECORD_PRESET", "pool": "all", "number": 1, "scope": "target"},
    ),
    (
        'record cue 10/2 only color position merge freeze "Two"',
        {
            "type": "RECORD_CUE",
            "cueListId": "cl-blue",
            "cueNumber": "2",
            "filter": ["color", "position"],
            "merge": "merge",
            "name": "Two",
            "freeze": True,
        },
    ),
    ("record cue 1", {"type": "RECORD_CUE", "cueListId": "cl-song"}),
    (
        "record slot 1 merge",
        {"type": "RECORD_CUE", "cueListId": "cl-song", "cueNumber": "1", "merge": "merge"},
    ),
    (
        "record slot 3 only color replace",
        {
            "type": "RECORD_CUE",
            "cueListId": "cl-blue",
            "cueNumber": "1",
            "filter": ["color"],
            "merge": "replace",
        },
    ),
    # patch
    (
        'universe add 2 "Front"',
        {
            "type": "ADD",
            "path": ["universes"],
            "value": {"id": "u-000000000001", "name": "Front", "number": 2},
        },
    ),
    (
        "universe add 3",
        {
            "type": "ADD",
            "path": ["universes"],
            "value": {"id": "u-000000000001", "name": "Universe 3", "number": 3},
        },
    ),
    (
        "fixture 201 patch 1.300",
        {
            "type": "PATCH_FIXTURE",
            "fixtureId": "fx-par1",
            "patch": {"universeId": "u1", "address": 300},
        },
    ),
    ("fixture 201 patch none", {"type": "PATCH_FIXTURE", "fixtureId": "fx-par1", "patch": None}),
    # output and surfaces
    (
        "route add 1 sacn 5",
        {
            "type": "ADD",
            "path": ["output", "routes"],
            "value": {
                "id": "r-000000000001",
                "universeId": "u1",
                "enabled": True,
                "protocol": "sacn",
                "universe": 5,
                "priority": 100,
                "destination": {"kind": "multicast", "iface": "eth9"},
            },
        },
    ),
    (
        "route add 1 sacn 5 unicast 10.0.0.2",
        {
            "type": "ADD",
            "path": ["output", "routes"],
            "value": {
                "id": "r-000000000001",
                "universeId": "u1",
                "enabled": True,
                "protocol": "sacn",
                "universe": 5,
                "priority": 100,
                "destination": {"kind": "unicast", "host": "10.0.0.2"},
            },
        },
    ),
    (
        "route add 1 artnet 0.1.2",
        {
            "type": "ADD",
            "path": ["output", "routes"],
            "value": {
                "id": "r-000000000001",
                "universeId": "u1",
                "enabled": True,
                "protocol": "artnet",
                "portAddress": {"net": 0, "subNet": 1, "universe": 2},
                "destination": {"kind": "broadcast", "iface": "eth9"},
            },
        },
    ),
    (
        "route add 1 dmxusb enttecPro /dev/ttyUSB0",
        {
            "type": "ADD",
            "path": ["output", "routes"],
            "value": {
                "id": "r-000000000001",
                "universeId": "u1",
                "enabled": True,
                "protocol": "dmxUsb",
                "device": {"driver": "enttecPro", "port": "/dev/ttyUSB0"},
                "refreshHz": 40,
            },
        },
    ),
    (
        'route add 1 DMXUSB dmxking "/dev/serial/by-id/usb-DMXking, Port 1" hz 25.5',
        {
            "type": "ADD",
            "path": ["output", "routes"],
            "value": {
                "id": "r-000000000001",
                "universeId": "u1",
                "enabled": True,
                "protocol": "dmxUsb",
                "device": {"driver": "dmxking", "port": "/dev/serial/by-id/usb-DMXking, Port 1"},
                "refreshHz": 25.5,
            },
        },
    ),
    (
        'surface add midi "Pad"',
        {
            "type": "ADD",
            "path": ["surfaces"],
            "value": {
                "id": "s-000000000001",
                "name": "Pad",
                "kind": "midi",
                "match": {"deviceName": "Pad"},
                "faderPickup": "jump",
            },
        },
    ),
    (
        'bind "MIDI Controller" cc 1 1 fader 2',
        {
            "type": "ADD",
            "path": ["bindings"],
            "value": {
                "id": "b-000000000001",
                "surfaceId": "s-midi",
                "input": {"kind": "midiCC", "channel": 1, "cc": 1},
                "action": {"kind": "playbackFader", "slot": 1},
            },
        },
    ),
    (
        'bind "nanokontrol2" note 1 40 button 3 2',
        {
            "type": "ADD",
            "path": ["bindings"],
            "value": {
                "id": "b-000000000001",
                "surfaceId": "s-midi",
                "input": {"kind": "midiNote", "channel": 1, "note": 40},
                "action": {"kind": "playbackButton", "slot": 2, "button": 1},
            },
        },
    ),
    (
        'bind "nanoKONTROL2" cc 1 23 master gm',
        {
            "type": "ADD",
            "path": ["bindings"],
            "value": {
                "id": "b-000000000001",
                "surfaceId": "s-midi",
                "input": {"kind": "midiCC", "channel": 1, "cc": 23},
                "action": {"kind": "master", "masterId": "m-gm"},
            },
        },
    ),
    (
        'bind "nanoKONTROL2" cc 1 42 blackout',
        {
            "type": "ADD",
            "path": ["bindings"],
            "value": {
                "id": "b-000000000001",
                "surfaceId": "s-midi",
                "input": {"kind": "midiCC", "channel": 1, "cc": 42},
                "action": {"kind": "blackout"},
            },
        },
    ),
    # edits
    (
        "playback 3 exclusivity color",
        {"type": "SET", "path": ["playbacks", {"id": "pb-blue"}, "exclusivity"], "value": "color"},
    ),
    (
        "cue 1/1 timing.fadeIn 2.5",
        {"type": "SET", "path": [*VERSE, "timing", "fadeIn"], "value": 2.5},
    ),
    (
        'show meta.title "Club Night 2"',
        {"type": "SET", "path": ["meta", "title"], "value": "Club Night 2"},
    ),
    (
        'playback 1 buttons ["go", "back"]  # a JSON list',
        {
            "type": "SET",
            "path": ["playbacks", {"id": "pb-song"}, "buttons"],
            "value": ["go", "back"],
        },
    ),
    (
        "playback 6 autoStart true",
        {"type": "SET", "path": ["playbacks", {"id": "pb-pulse"}, "autoStart"], "value": True},
    ),
    (
        'preset color 1 name "Navy"',
        {"type": "SET", "path": ["presets", {"id": "pr-blue"}, "name"], "value": "Navy"},
    ),
    (
        "cuelist 20 wrap true",
        {"type": "SET", "path": ["cueLists", {"id": "cl-pulse"}, "wrap"], "value": True},
    ),
    (
        "universe 1 name Front",
        {"type": "SET", "path": ["universes", {"id": "u1"}, "name"], "value": "Front"},
    ),
    (
        'rename group 1 "Heads"',
        {"type": "SET", "path": ["groups", {"id": "g-mh"}, "name"], "value": "Heads"},
    ),
    ('rename show "Late Show"', {"type": "SET", "path": ["meta", "title"], "value": "Late Show"}),
    (
        "delete cue 1/2",
        {"type": "DELETE", "path": ["cueLists", {"id": "cl-song"}, "cues", {"id": "c-chorus"}]},
    ),
    ("delete page 1", {"type": "DELETE", "path": ["pages", {"id": "page-1"}]}),
    # performance and session
    ("go 1", {"type": "GO", "playbackId": "pb-song"}),
    ("release 3", {"type": "RELEASE_PLAYBACK", "playbackId": "pb-blue"}),
    ("fader 3 75%", {"type": "SET_FADER", "playbackId": "pb-blue", "level": 0.75}),
    ("gm 0.5", {"type": "SET_MASTER", "masterId": "m-gm", "level": 0.5}),
    ("blackout off", {"type": "BLACKOUT", "on": False}),
    ("undo", {"type": "UNDO"}),
    ("REDO", {"type": "REDO"}),
]


@pytest.mark.parametrize(("line", "expected"), COMMANDS, ids=[line for line, _ in COMMANDS])
def test_lines_become_commands(line: str, expected: dict[str, Any]) -> None:
    assert command(line) == expected


def test_record_cue_into_a_new_list_adds_it_in_the_same_batch() -> None:
    batch = command('record cue 30/1 "Opening"')
    assert batch["type"] == "BATCH"
    add, record = batch["commands"]
    assert add == {
        "type": "ADD",
        "path": ["cueLists"],
        "value": {
            "id": "cl-000000000001",
            "name": "Cue list 30",
            "number": 30,
            "mode": "sequence",
            "tracking": False,
            "wrap": False,
            "releaseAtEnd": False,
            "cues": [],
        },
    }
    assert record == {
        "type": "RECORD_CUE",
        "cueListId": "cl-000000000001",
        "cueNumber": "1",
        "name": "Opening",
    }


def test_record_slot_on_an_empty_slot_creates_list_cue_playback_and_assignment() -> None:
    batch = command('record slot 2 only intensity "Look"')
    assert batch["label"] == "recorded slot 2: playback 2 'Look'"
    add_list, record, add_playback, assign = batch["commands"]
    assert add_list["value"]["number"] == 2  # free, so the slot's number
    assert record == {
        "type": "RECORD_CUE",
        "cueListId": "cl-000000000001",
        "cueNumber": "1",
        "filter": ["intensity"],
        "name": "Look",
    }
    assert add_playback["value"] == {
        "id": "pb-000000000002",
        "name": "Look",
        "number": 2,
        "cueListId": "cl-000000000001",
        "priority": 50,
        "fader": "master",
        "buttons": ["toggle", "flash"],
        "ltpFaderMode": "threshold",
        "ltpThreshold": 0.02,
        "autoStart": True,
        "autoRelease": True,
        "flash": {"level": 1, "includeLtp": True},
        "protectFromSwop": False,
        "releaseTime": 1,
    }
    assert assign == {
        "type": "ASSIGN_PLAYBACK",
        "pageId": "page-1",
        "slot": 1,
        "playbackId": "pb-000000000002",
    }
    # Slot 10 is past the page's 8 slots; cue list number 10 is taken, so the list gets 21.
    batch = command("record slot 10")
    assert (batch["commands"][0]["value"]["number"], batch["commands"][2]["value"]["number"]) == (
        21,
        10,
    )


def test_fixture_add_embeds_the_profile_once_and_advances_addresses() -> None:
    batch = command('fixture add 202 thru 203 "rgb par 3ch" mode 3CH at 1.200')
    assert [c["value"]["number"] for c in batch["commands"]] == [
        202,
        203,
    ]  # the profile is embedded
    assert [c["value"]["patch"]["address"] for c in batch["commands"]] == [200, 203]
    assert batch["commands"][0]["value"]["name"] == "Par 202"
    assert batch["commands"][0]["value"]["orientation"] == {
        "invertPan": False,
        "invertTilt": False,
        "swapPanTilt": False,
        "panOffset": 0,
        "tiltOffset": 0,
    }
    batch = command('fixture add 401 "Eurolite LED ML-56 RGBW" mode 4-channel')
    profile, fixture = batch["commands"]
    assert (profile["path"], profile["value"]["id"]) == (["profiles"], "prof-ml56")
    assert fixture["value"]["patch"] is None
    assert fixture["value"]["profileRevision"] == "1"


def test_an_embedded_profile_at_another_revision_wins_with_a_note() -> None:
    doc = load_doc(APPENDIX_A)
    doc["profiles"][1]["revision"] = "0"
    for fixture in doc["fixtures"]:
        if fixture["profileId"] == "prof-par":
            fixture["profileRevision"] = "0"
    action = parse(
        'fixture add 300 "RGB Par 3ch" mode 3ch', Context(show_of(doc), LIBRARY, CounterIds())
    )
    assert isinstance(action, Submit)
    assert action.notes == (
        "warning: the show embeds 'RGB Par 3ch' revision '0', the library has '1': "
        "using the show's copy",
    )
    assert len(action.command["commands"]) == 1  # type: ignore[typeddict-item]


def test_elements_of_multi_element_fixtures() -> None:
    bar = "fx-bar1"
    refs = command("sel fixture 301", DEMO)["targets"]["refs"]
    assert refs == [{"fixtureId": bar, "element": e} for e in range(12)]
    assert command("sel fixture 301.3", DEMO)["targets"]["refs"] == [
        {"fixtureId": bar, "element": 2}
    ]
    assert command("sel 301.4 thru 301.2", DEMO)["targets"]["refs"] == [
        {"fixtureId": bar, "element": e} for e in (3, 2, 1)
    ]


@pytest.mark.parametrize(
    ("line", "action"),
    [
        ("", Nothing()),
        ("   # just a comment", Nothing()),
        ("programmer", Query("programmer")),
        ("list groups", Query("list", "groups")),
        ("library", Query("library")),
        ("info", Query("info")),
        ("status", Query("status")),
        ("help", Query("help")),
        ("save", Save(None)),
        ('save "/tmp/my show.show"', Save(Path("/tmp/my show.show"))),
        ("source build.busk", Source(Path("build.busk"))),
        ("quit", Quit()),
        ("exit", Quit()),
    ],
)
def test_queries_and_session_actions(line: str, action: object) -> None:
    assert parse(line, context()) == action


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("frobnicate", "unknown command 'frobnicate' (try 'help')"),
        ("sel group 7", "no group 7"),
        ("sel fixture 999", "no fixture 999"),
        ("sel fixture 101.2", "fixture 101 has 1 element(s); no element 2"),
        ("sel fixture 500 thru 600", "no fixture from 500 to 600"),
        ('sel fixture 101 "unterminated', "unterminated quote at column 17"),
        ("set sparkle 1", "unknown attribute 'sparkle'"),
        ("set pan high", "expected a number, got 'high'"),
        ("set color 1 0", "expected the colour's b"),
        ("preset color 9", "no preset color 9"),
        ("record slot 1", "slot 1 is in use on page 1: add merge, replace or remove"),
        ("record slot 2 merge", "slot 2 is empty on page 1: record it without merge"),
        ("record cue 1/x", "expected a cue as L/C (e.g. 10/1), got '1/x'"),
        ("record group 1 sideways", "unexpected 'sideways'"),
        (
            "record cue 1 only",
            "expected attribute families after only "
            "(intensity, position, color, beam, focus, shutter)",
        ),
        ('fixture add 101 "RGB Par 3ch" mode 3ch', "fixture 101 exists"),
        ('fixture add 300 "Nope" mode x', "no profile 'Nope' in the library (see 'library')"),
        (
            'fixture add 300 "RGB Par 3ch" mode 9ch',
            "profile 'RGB Par 3ch' has no mode '9ch' (modes: 3ch)",
        ),
        (
            'fixture add 300 thru 299 "RGB Par 3ch" mode 3ch',
            "fixture add needs ascending numbers: N thru M with M ≥ N",
        ),
        ("fixture 201 patch 9.1", "no universe 9"),
        ("fixture 201 patch 1", "expected an address as U.A, e.g. 1.101, got '1'"),
        ("universe add 1", "universe 1 exists"),
        ('bind "Nope" cc 1 1 fader 1', "no surface 'Nope'"),
        ('bind "nanoKONTROL2" cc 1 1 fader 0', "slots are counted from 1"),
        ("route add 1 dmx 1", "expected sacn or artnet or dmxusb, got 'dmx'"),
        (
            "route add 1 dmxusb enttecOpen /dev/ttyUSB0",
            "expected enttecpro or dmxking, got 'enttecOpen'",
        ),
        ("route add 1 dmxusb enttecPro", "expected a serial port such as /dev/ttyUSB0"),
        (
            "route add 1 dmxusb enttecPro /dev/ttyUSB0 hz fast",
            "expected a refresh rate in Hz, got 'fast'",
        ),
        (
            "route add 1 artnet 1.2",
            "expected an Art-Net port address as net.sub.universe, got '1.2'",
        ),
        ("go 9", "no playback 9"),
        ("cue 1/9 timing.fadeIn 2", "no cue 1/9"),
        ("playback 3", "expected a property, e.g. name or timing.fadeIn"),
        ("playback 3 exclusivity", "expected a value"),
        ("delete show", "cannot delete 'show'"),
        ("blackout maybe", "expected on or off, got 'maybe'"),
        (
            "list everything",
            "cannot list 'everything'; try one of fixtures, groups, presets, cuelists, "
            "cues, playbacks, pages, masters, universes, routes, surfaces, bindings, profiles, "
            "effects, park",
        ),
    ],
)
def test_errors_say_what_the_operator_typed(line: str, error: str) -> None:
    with pytest.raises(ParseError) as raised:
        parse(line, context())
    assert raised.value.message == error


def test_tokens_keep_their_positions_and_comments_end_the_line() -> None:
    tokens, end = tokenize('record cue 1/2 "a \\"b\\"" , x # tail')
    assert [(t.text, t.start, t.quoted) for t in tokens] == [
        ("record", 0, False),
        ("cue", 7, False),
        ("1/2", 11, False),
        ('a "b"', 15, True),
        (",", 25, False),
        ("x", 27, False),
    ]
    assert end == 29


# ------------------------------------------------- tempo and fade (Phase 4)


def tempo_context(*names: str) -> Context:
    """A rig with a speed master per name (ids m-s1, m-s2, …) and no other."""
    doc = busk_rig(spots=1)
    for k, name in enumerate(names, 1):
        doc["masters"].append({**speed_master(f"m-s{k}"), "name": name})
    return Context(show_of(doc), LIBRARY, CounterIds(), iface="eth9")


def tempo_command(line: str, *names: str) -> dict[str, Any]:
    action = parse(line, tempo_context(*names))
    assert isinstance(action, Submit), action
    return dict(action.command)


def test_fade_sets_the_programmer_fade_time() -> None:
    assert command("fade 2.5") == {"type": "PROGRAMMER_FADE", "time": 2.5}


def test_appendix_a_taps_its_speed_master() -> None:
    assert command("tap") == {"type": "TAP", "masterId": "m-speed"}
    assert command('bpm "Speed 1" 128') == {"type": "SET_BPM", "masterId": "m-speed", "bpm": 128}


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("tap", {"type": "TAP", "masterId": "m-s1"}),
        ("bpm 128", {"type": "SET_BPM", "masterId": "m-s1", "bpm": 128}),
        ('tap "Speed"', {"type": "TAP", "masterId": "m-s1"}),
        ('bpm "Speed" 96.5', {"type": "SET_BPM", "masterId": "m-s1", "bpm": 96.5}),
    ],
)
def test_tap_and_bpm_use_the_only_speed_master_or_a_named_one(
    line: str, expected: dict[str, Any]
) -> None:
    assert tempo_command(line, "Speed") == expected


def test_a_named_speed_master_picks_one_of_several() -> None:
    assert tempo_command('bpm "Beats" 140', "Speed", "Beats") == {
        "type": "SET_BPM",
        "masterId": "m-s2",
        "bpm": 140,
    }


@pytest.mark.parametrize(
    ("line", "names", "error"),
    [
        ("tap", (), "no speed master"),
        ("bpm 120", ("Speed", "Beats"), "several speed masters: name one"),
        ('tap "Grand"', ("Speed",), "no speed master 'Grand'"),
        ("bpm", ("Speed",), "expected a tempo"),
        ("fade soon", (), "expected a time in seconds, got 'soon'"),
    ],
)
def test_tempo_errors(line: str, names: tuple[str, ...], error: str) -> None:
    with pytest.raises(ParseError, match=f"^{error}$"):
        parse(line, tempo_context(*names))


# ------------------------------------------------- the rest of §5.13 (Phase 4)

CHORUS = ["cueLists", {"id": "cl-song"}, "cues", {"id": "c-chorus"}]
SONG = ["cueLists", {"id": "cl-song"}]
HZ_2 = {"rate": {"kind": "hz", "value": 2}, "direction": "forward", "crossfade": 0}


def timing_sets(path: list[Any], **fields: Any) -> list[dict[str, Any]]:
    return [
        {"type": "SET", "path": [*path, "timing", key], "value": v} for key, v in fields.items()
    ]


def batch(*commands: dict[str, Any]) -> dict[str, Any]:
    return {"type": "BATCH", "label": "", "commands": list(commands)}


PHASE4_COMMANDS: list[tuple[str, dict[str, Any]]] = [
    # perform
    ("back 1", {"type": "BACK", "playbackId": "pb-song"}),
    ("goto 1 2", {"type": "GOTO", "playbackId": "pb-song", "cueNumber": "2"}),
    ("goto 1 2.5", {"type": "GOTO", "playbackId": "pb-song", "cueNumber": "2.5"}),
    ("release 3 2.5", {"type": "RELEASE_PLAYBACK", "playbackId": "pb-blue", "time": 2.5}),
    ("release 3 0", {"type": "RELEASE_PLAYBACK", "playbackId": "pb-blue", "time": 0}),
    # masters by name
    ('master "Speed 1" 75%', {"type": "SET_MASTER", "masterId": "m-speed", "level": 0.75}),
    ('master "grand master" 0.5', {"type": "SET_MASTER", "masterId": "m-gm", "level": 0.5}),
    # cue timing
    ("cue 1/1 time 3", batch(*timing_sets(VERSE, fadeIn=3, fadeOut=3))),
    (
        "cue 1/2 time 3/1 delay 0/2 easein",
        batch(
            *timing_sets(CHORUS, fadeIn=3, fadeOut=1, delayIn=0, delayOut=2, curve="easeIn")
        ),
    ),
    (
        "cue 1/2 time 0 delay 1",
        batch(*timing_sets(CHORUS, fadeIn=0, fadeOut=0, delayIn=1, delayOut=1)),
    ),
    (
        "cue 1/1 time 2 bezier 0.25 0.1 0.25 1",
        batch(*timing_sets(VERSE, fadeIn=2, fadeOut=2, curve={"bezier": [0.25, 0.1, 0.25, 1]})),
    ),
    (
        "cue 1/1 time color 3 delay 1 easeOut",
        {"type": "SET", "path": [*VERSE, "timing", "perFamily"],
         "value": {"color": {"fade": 3, "delay": 1, "curve": "easeOut"}}},
    ),
    (
        "cue 1/1 time position 4",
        {"type": "SET", "path": [*VERSE, "timing", "perFamily"],
         "value": {"position": {"fade": 4, "delay": 0}}},
    ),
    ("cue 1/2 follow 0",
     {"type": "SET", "path": [*CHORUS, "trigger"], "value": {"kind": "follow", "delay": 0}}),
    ("cue 1/2 wait 8",
     {"type": "SET", "path": [*CHORUS, "trigger"], "value": {"kind": "wait", "delay": 8}}),
    ("cue 1/2 go", {"type": "SET", "path": [*CHORUS, "trigger"], "value": {"kind": "go"}}),
    (
        "cue 1/2 release group 1 only pan tilt",
        {"type": "SET", "path": [*CHORUS, "releases"],
         "value": [{"targets": {"kind": "group", "groupId": "g-mh"},
                    "attributes": ["pan", "tilt"]}]},
    ),
    (
        "cue 1/2 release 201",
        {"type": "SET", "path": [*CHORUS, "releases"],
         "value": [{"targets": {"kind": "targets", "refs": [PAR]}, "attributes": "all"}]},
    ),
    # chases
    (
        "cuelist 1 chase hz 2",
        batch({"type": "SET", "path": [*SONG, "chase"], "value": HZ_2},
              {"type": "SET", "path": [*SONG, "mode"], "value": "chase"}),
    ),
    (
        "cuelist 1 chase hz 0.5 bounce crossfade 50%",
        batch({"type": "SET", "path": [*SONG, "chase"],
               "value": {"rate": {"kind": "hz", "value": 0.5}, "direction": "bounce",
                         "crossfade": 0.5}},
              {"type": "SET", "path": [*SONG, "mode"], "value": "chase"}),
    ),
    (
        "cuelist 1 chase bpm",
        batch({"type": "SET", "path": [*SONG, "chase"],
               "value": {"rate": {"kind": "bpm", "masterId": "m-speed", "multiplier": 1},
                         "direction": "forward", "crossfade": 0}},
              {"type": "SET", "path": [*SONG, "mode"], "value": "chase"}),
    ),
    (
        'cuelist 1 chase bpm "Speed 1" x 0.5 random crossfade 0.25',
        batch({"type": "SET", "path": [*SONG, "chase"],
               "value": {"rate": {"kind": "bpm", "masterId": "m-speed", "multiplier": 0.5},
                         "direction": "random", "crossfade": 0.25}},
              {"type": "SET", "path": [*SONG, "mode"], "value": "chase"}),
    ),
    ("cuelist 1 sequence", {"type": "SET", "path": [*SONG, "mode"], "value": "sequence"}),
    (  # the generic SET still takes JSON
        'cuelist 1 chase {"rate": {"kind": "hz", "value": 2}, "direction": "forward",'
        ' "crossfade": 0}',
        {"type": "SET", "path": [*SONG, "chase"], "value": HZ_2},
    ),
    ("cue 1/2 block true", {"type": "SET", "path": [*CHORUS, "block"], "value": True}),
]  # fmt: skip


@pytest.mark.parametrize(("line", "expected"), PHASE4_COMMANDS, ids=[c[0] for c in PHASE4_COMMANDS])
def test_phase_4_commands(line: str, expected: dict[str, Any]) -> None:
    assert command(line) == expected


def test_per_family_timing_merges_with_the_families_there() -> None:
    doc = load_doc(APPENDIX_A)
    doc["cueLists"][0]["cues"][0]["timing"]["perFamily"] = {"position": {"fade": 4, "delay": 0}}
    action = parse("cue 1/1 time color 3", Context(show_of(doc), LIBRARY, CounterIds()))
    assert isinstance(action, Submit)
    assert action.command == {
        "type": "SET",
        "path": [*VERSE, "timing", "perFamily"],
        "value": {"position": {"fade": 4, "delay": 0}, "color": {"fade": 3, "delay": 0}},
    }


def test_a_release_is_appended_to_the_cues_releases() -> None:
    doc = load_doc(APPENDIX_A)
    first = {"targets": {"kind": "group", "groupId": "g-par"}, "attributes": "all"}
    doc["cueLists"][0]["cues"][1]["releases"] = [first]
    action = parse(
        "cue 1/2 release 101 only intensity", Context(show_of(doc), LIBRARY, CounterIds())
    )
    assert isinstance(action, Submit)
    assert action.command == {
        "type": "SET",
        "path": [*CHORUS, "releases"],
        "value": [
            first,
            {"targets": {"kind": "targets", "refs": [MH1]}, "attributes": ["intensity"]},
        ],
    }


def test_master_add_speed() -> None:
    added = command('master add speed "Speed 2"')
    assert (added["type"], added["path"]) == ("ADD", ["masters"])
    assert added["value"] == {
        "id": added["value"]["id"],
        "kind": "speed",
        "name": "Speed 2",
        "defaultBpm": 120,
        "tap": True,
        "multiplierSteps": [0.25, 0.5, 1, 2, 4],
    }
    assert added["value"]["id"].startswith("m-")
    custom = command('master add speed "Beats" steps 0.5, 1,2 bpm 128.5')["value"]
    assert (custom["defaultBpm"], custom["multiplierSteps"]) == (128.5, [0.5, 1, 2])


@pytest.mark.parametrize(
    ("line", "action"),
    [
        ('bind "nanoKONTROL2" note 1 41 tap', {"kind": "tap", "masterId": "m-speed"}),
        ('bind "nanoKONTROL2" note 1 41 tap "Speed 1"', {"kind": "tap", "masterId": "m-speed"}),
        ('bind "nanoKONTROL2" cc 1 16 master "Speed 1"', {"kind": "master", "masterId": "m-speed"}),
        ('bind "nanoKONTROL2" cc 1 23 master gm', {"kind": "master", "masterId": "m-gm"}),
    ],
)
def test_bind_tap_and_named_masters(line: str, action: dict[str, Any]) -> None:
    assert command(line)["value"]["action"] == action


def test_list_cues_and_masters() -> None:
    assert parse("list cues 1", context()) == Query("list", "cues", 1)
    assert parse("list masters", context()) == Query("list", "masters")


def chase_context(*speed_names: str) -> Context:
    """A one-spot rig with cue list 1 (one cue) and a speed master per name."""
    doc = busk_rig(spots=1)
    doc["cueLists"].append(cue_list("cl-1", 1, cue("c-1")))
    for k, name in enumerate(speed_names, 1):
        doc["masters"].append({**speed_master(f"m-s{k}"), "name": name})
    return Context(show_of(doc), LIBRARY, CounterIds())


@pytest.mark.parametrize(
    ("line", "names", "error"),
    [
        ("cuelist 1 chase bpm", (), "no speed master"),
        ("cuelist 1 chase bpm x 2", ("A", "B"), "several speed masters: name one"),
        ('bind "x" cc 1 1 tap', (), "no surface 'x'"),
    ],
)
def test_chase_bpm_needs_a_speed_master(line: str, names: tuple[str, ...], error: str) -> None:
    with pytest.raises(ParseError, match=f"^{error}$"):
        parse(line, chase_context(*names))


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("goto 1", "expected a cue number"),
        ("goto 1 two", "expected a cue number, got 'two'"),
        ("back 9", "no playback 9"),
        ("release 3 soon", "expected a time in seconds, got 'soon'"),
        ('master "Nope" 1', "no master 'Nope'"),
        ('master "Speed 1"', "expected a level"),
        ("master 1", 'expected a master name in quotes, e.g. "Speed 1", or add'),
        ('master add speed "Speed 1"', "a master named 'Speed 1' exists"),
        ('master add speed "S" steps', "expected a multiplier step"),
        ('master add speed "S" bpm 120 bpm 90', "unexpected 'bpm'"),
        ("master add grand", "expected speed or size or group or fadetime, got 'grand'"),
        (
            "cue 1/1 time 2 wobble",
            "expected a curve (linear, easeIn, easeOut, easeInOut, snapStart, snapEnd"
            " or bezier x1 y1 x2 y2), got 'wobble'",
        ),
        ("cue 1/1 time 2 bezier 0.1 0.2", "expected a Bézier control value"),
        ("cue 1/1 time", "expected a fade time"),
        ("cue 1/1 time 2/x", "expected a fade time, got '2/x'"),
        ("cue 1/1 time color", "expected a fade time"),
        ("cue 1/1 time 1 delay", "expected a delay"),
        ("cue 1/1 wait", "expected a delay"),
        ("cue 1/1 go now", "unexpected 'now'"),
        ("cue 1/2 release group 1 only", "expected attribute names after only"),
        ("cue 1/2 release group 1 only spin", "expected attribute names after only, got 'spin'"),
        ("cuelist 1 chase hz", "expected a rate in Hz"),
        ("cuelist 1 chase hz 2 sideways", "unexpected 'sideways'"),
        ("cuelist 1 chase bpm x", "expected a multiplier"),
        ("cuelist 1 sequence now", "unexpected 'now'"),
        ("list cues", "expected a cue list number"),
        ("list cues 7", "no cue list 7"),
        ('bind "nanoKONTROL2" cc 1 16 master "Nope"', "no master 'Nope'"),
    ],
)
def test_phase_4_errors(line: str, error: str) -> None:
    with pytest.raises(ParseError, match=f"^{re.escape(error)}$"):
        parse(line, context())


# ------------------------------------------------------------ Phase 5 effects

EFFECTS = EffectLibrary()
PULSE_CUE = ["cueLists", {"id": "cl-pulse"}, "cues", {"id": "c-pulse"}]
BPM_X1 = {"kind": "bpm", "masterId": "m-speed", "multiplier": 1}


def fx_doc() -> dict[str, Any]:
    """Appendix A plus a size master "FX"."""
    doc = load_doc(APPENDIX_A)
    doc["masters"].append({"id": "m-fx", "kind": "size", "name": "FX"})
    return doc


def fx_context(doc: dict[str, Any] | None = None, programmer: Programmer | None = None) -> Context:
    """A context whose programmer selects MH 1 and MH 2, unless given."""
    return Context(
        show_of(fx_doc() if doc is None else doc),
        LIBRARY,
        CounterIds(),
        effects=EFFECTS,
        programmer=Programmer(selection=(MH1, MH2)) if programmer is None else programmer,
    )


def fx_command(line: str, doc: dict[str, Any] | None = None) -> dict[str, Any]:
    """The line's command; for a line that embeds a template first, the last one."""
    action = parse(line, fx_context(doc))
    if isinstance(action, SubmitAll):
        return dict(action.commands[-1])
    assert isinstance(action, Submit), action
    return dict(action.command)


def instance(**fields: Any) -> dict[str, Any]:
    """The console's instance on the selection with every default; ``fields`` override."""
    return {
        "id": "fx1",
        "templateId": "ef-pulse",
        "targets": {"kind": "targets", "refs": [MH1, MH2]},
        "rate": BPM_X1,
        "direction": "forward",
        "size": 0.7,
        "phase": {"start": 0, "end": 0},
        "groups": 1,
        "blocks": 1,
        "wings": 1,
        **fields,
    }


def test_effect_add_embeds_a_library_template_first() -> None:
    action = parse('effect add "Circle"', fx_context())
    circle = EFFECTS.find("Circle")
    assert circle is not None
    assert action == SubmitAll(
        (
            {"type": "ADD", "path": ["effects"], "value": dict(circle.template)},  # type: ignore[arg-type]
            {
                "type": "ADD_EFFECT",
                "effect": instance(templateId="ef-circle", size=20),  # type: ignore[typeddict-item]
            },
        )
    )


def test_effect_add_uses_the_shows_template_with_the_library_defaults() -> None:
    # Appendix A embeds the library's Pulse (same id): only the effect is added.
    assert fx_command('effect add "pulse"') == {"type": "ADD_EFFECT", "effect": instance()}


def test_the_shows_copy_of_a_library_template_is_found_by_the_library_id() -> None:
    doc = fx_doc()
    doc["effects"][0]["name"] = "Throb"  # still ef-pulse, the library's Pulse
    action = parse('effect add "Pulse"', fx_context(doc))  # nothing to embed
    assert action == Submit({"type": "ADD_EFFECT", "effect": instance()})  # type: ignore[typeddict-item]


def test_a_custom_template_has_no_defaults() -> None:
    doc = fx_doc()
    doc["effects"][0]["id"] = "ef-mine"  # no longer the library's Pulse
    doc["cueLists"][2]["cues"][0]["effects"][0]["templateId"] = "ef-mine"
    added = fx_command('effect add "Pulse"', doc)["effect"]
    assert (added["templateId"], added["size"], added["phase"]) == (
        "ef-mine",
        1,
        {"start": 0, "end": 0},
    )


@pytest.mark.parametrize(
    ("line", "fields"),
    [
        (
            'effect add "Wave"',  # library defaults low/high
            {"templateId": "ef-wave", "size": 1, "low": 0, "high": 1},
        ),
        (
            'effect add "Rainbow"',
            {"templateId": "ef-rainbow", "size": 1, "phase": {"start": 0, "end": 360}},
        ),
        ('effect add "Pulse" bpm x 0.5', {"rate": {**BPM_X1, "multiplier": 0.5}}),
        ('effect add "Pulse" bpm "speed 1" x 2', {"rate": {**BPM_X1, "multiplier": 2}}),
        ('effect add "Pulse" hz 0.25', {"rate": {"kind": "hz", "value": 0.25}}),
        ('effect add "Pulse" size 50%', {"size": 0.5}),
        ('effect add "Pulse" bounce', {"direction": "bounce"}),
        (
            'effect add "Wave" id w1 wings 2 reverse low 0.2 high 0.9 phase 0 360 groups 2 '
            'blocks 3 fadein 1.5 sizemaster "fx" speedmaster "Speed 1" hz 2 size 0.5',
            {
                "id": "w1",
                "templateId": "ef-wave",
                "rate": {"kind": "hz", "value": 2},
                "direction": "reverse",
                "size": 0.5,
                "low": 0.2,
                "high": 0.9,
                "phase": {"start": 0, "end": 360},
                "groups": 2,
                "blocks": 3,
                "wings": 2,
                "sizeFadeIn": 1.5,
                "sizeMasterId": "m-fx",
                "speedMasterId": "m-speed",
            },
        ),
    ],
)
def test_effect_add_options(line: str, fields: dict[str, Any]) -> None:
    assert fx_command(line)["effect"] == instance(**fields)


def test_effect_add_keeps_the_instance_field_order() -> None:
    line = 'effect add "Wave" speedmaster "Speed 1" fadein 1 low 0 high 1 id w1'
    assert list(fx_command(line)["effect"]) == [
        "id", "templateId", "targets", "rate", "direction", "size", "low", "high",
        "phase", "groups", "blocks", "wings", "sizeFadeIn", "speedMasterId",
    ]  # fmt: skip


def test_without_one_speed_master_the_default_rate_is_1_hz() -> None:
    doc = fx_doc()
    doc["masters"] = [m for m in doc["masters"] if m["kind"] != "speed"]
    doc["cueLists"][2]["cues"][0]["effects"][0]["rate"] = {"kind": "hz", "value": 1}
    assert fx_command('effect add "Pulse"', doc)["effect"]["rate"] == {"kind": "hz", "value": 1}
    doc["masters"] += [speed_master("m-a"), speed_master("m-b") | {"name": "Speed 2"}]
    assert fx_command('effect add "Pulse"', doc)["effect"]["rate"] == {"kind": "hz", "value": 1}


def test_the_default_id_is_unused_by_the_programmer_and_every_cue() -> None:
    doc = fx_doc()
    doc["cueLists"][2]["cues"][0]["effects"][0]["id"] = "fx2"
    held = Programmer(selection=(MH1,), effects=(instance(id="fx1"),))  # type: ignore[arg-type]
    action = parse('effect add "Pulse"', fx_context(doc, held))
    assert isinstance(action, Submit)
    assert action.command["effect"]["id"] == "fx3"  # type: ignore[typeddict-item]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("effect remove fx1", {"type": "REMOVE_EFFECT", "id": "fx1"}),
        ("effect stop fx1", {"type": "RUN_EFFECT", "id": "fx1", "on": False}),
        ("Effect RUN fx1", {"type": "RUN_EFFECT", "id": "fx1", "on": True}),
        ("effect clear", {"type": "REMOVE_EFFECT"}),
        (
            'effect template add "Nod" [{"attribute": "tilt", "waveform": {"kind": "sine"}, '
            '"phaseOffset": 0, "mode": "add"}]',
            {
                "type": "ADD",
                "path": ["effects"],
                "value": {
                    "id": "ef-000000000001",
                    "name": "Nod",
                    "layers": [
                        {
                            "attribute": "tilt",
                            "waveform": {"kind": "sine"},
                            "phaseOffset": 0,
                            "mode": "add",
                        }
                    ],
                },
            },
        ),
        (
            "cue 20/1 effect ei-1 size 0.5",
            {"type": "SET", "path": [*PULSE_CUE, "effects", {"id": "ei-1"}, "size"], "value": 0.5},
        ),
        (
            "cue 20/1 effect ei-1 rate.multiplier 2  # twice as fast",
            {
                "type": "SET",
                "path": [*PULSE_CUE, "effects", {"id": "ei-1"}, "rate", "multiplier"],
                "value": 2,
            },
        ),
        (
            'master add size "Wobble"',
            {
                "type": "ADD",
                "path": ["masters"],
                "value": {"id": "m-000000000001", "kind": "size", "name": "Wobble"},
            },
        ),
        (
            'master add group "Heads" group 1',
            {
                "type": "ADD",
                "path": ["masters"],
                "value": {
                    "id": "m-000000000001",
                    "kind": "group",
                    "name": "Heads",
                    "groupId": "g-mh",
                },
            },
        ),
    ],
)
def test_phase_5_commands(line: str, expected: dict[str, Any]) -> None:
    assert fx_command(line) == expected


def test_list_effects_is_a_query() -> None:
    assert parse("list effects", fx_context()) == Query("list", "effects")


@pytest.mark.parametrize(
    ("programmer", "fader"),
    [
        (Programmer(selection=(MH1,), effects=(instance(),)), "size"),  # type: ignore[arg-type]
        (Programmer(selection=(MH1,)), "master"),
    ],
    ids=["effects only", "nothing"],
)
def test_record_slot_gives_an_effect_only_cue_a_size_fader(
    programmer: Programmer, fader: str
) -> None:
    action = parse('record slot 2 "Pulse"', fx_context(programmer=programmer))
    assert isinstance(action, Submit)
    playback = action.command["commands"][2]["value"]  # type: ignore[typeddict-item]
    assert playback["fader"] == fader


def test_record_slot_weighs_values_and_effects_through_the_filter() -> None:
    values = {slot_key(MH1, "pan"): {"kind": "literal", "value": 0}}  # type: ignore[arg-type]
    programmer = Programmer(selection=(MH1,), values=values, effects=(instance(),))  # type: ignore[arg-type]
    faders = []
    for line in (
        'record slot 2 "X"',
        'record slot 2 only intensity "X"',
        'record slot 2 only color "X"',
    ):
        action = parse(line, fx_context(programmer=programmer))
        assert isinstance(action, Submit)
        faders.append(action.command["commands"][2]["value"]["fader"])  # type: ignore[typeddict-item]
    # A pan value is recorded too; only the pulse's family; neither (nothing to record).
    assert faders == ["master", "size", "master"]


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ('effect add "Nope"', "no template 'Nope' in the library (see 'library')"),
        ('effect add "Pulse" size 1 size 0.5', "unexpected 'size'"),
        ('effect add "Pulse" hz 1 bpm', "unexpected 'bpm'"),
        ('effect add "Pulse" forward reverse', "unexpected 'reverse'"),
        ('effect add "Pulse" low 0 0.5', "expected high, got '0.5'"),
        ('effect add "Pulse" sizemaster "Speed 1"', "no size master 'Speed 1'"),
        ('effect add "Pulse" speedmaster FX', "expected a speed master name in quotes"),
        ('effect add "Pulse" bpm "Nope"', "no speed master 'Nope'"),
        ('effect add "Pulse" groups 1.5', "expected a number of groups, got '1.5'"),
        ('effect add "Pulse" wobble', "unexpected 'wobble'"),
        (
            "effect wobble",
            "expected add or remove or clear or template or stop or run, got 'wobble'",
        ),
        ('effect template add "Pulse" []', "a template named 'Pulse' exists"),
        (
            'effect template add "Nod" [{"attribute": "tilt",',
            'expected the layers as a JSON list, e.g. [{"attribute": "pan", …}]: '
            "Expecting property name enclosed in double quotes: line 1 column 23 (char 22)",
        ),
        (
            'effect template add "Nod" {"attribute": "tilt"}',
            'expected the layers as a JSON list, e.g. [{"attribute": "pan", …}]',
        ),
        (
            'effect template add "Nod"',
            'expected the layers as a JSON list, e.g. [{"attribute": "pan", …}]',
        ),
        ("cue 20/1 effect nope size 1", "cue 20/1 has no effect 'nope'"),
        ('master add group "Heads"', "expected group N: the group the master scales"),
        ('master add group "Heads" group 9', "no group 9"),
        ('master add size "fx"', "a master named 'fx' exists"),
    ],
)
def test_phase_5_errors(line: str, error: str) -> None:
    with pytest.raises(ParseError) as raised:
        parse(line, fx_context())
    assert raised.value.message == error


def test_effect_add_needs_a_selection_and_bpm_a_speed_master() -> None:
    with pytest.raises(ParseError, match=r"^nothing selected$"):
        parse('effect add "Pulse"', fx_context(programmer=Programmer()))
    doc = fx_doc()
    doc["masters"] = [m for m in doc["masters"] if m["kind"] != "speed"]
    doc["cueLists"][2]["cues"][0]["effects"][0]["rate"] = {"kind": "hz", "value": 1}
    with pytest.raises(ParseError, match=r"^no speed master$"):
        parse('effect add "Pulse" bpm', fx_context(doc))


# ------------------------------------------------------------------ Phase 6 (phase-6-plan §5.17)


def p6_doc() -> dict[str, Any]:
    """Appendix A with a second page ("Washes": Blue in slot 2) and an OSC
    surface on port 8000."""
    doc = load_doc(APPENDIX_A)
    doc["pages"].append({"id": "page-2", "name": "Washes", "number": 2, "slots": [None, "pb-blue"]})
    doc["surfaces"].append(
        {"id": "s-osc", "name": "TouchOSC", "kind": "osc", "match": {"port": 8000},
         "faderPickup": "jump"}
    )  # fmt: skip
    return doc


def p6_context(doc: dict[str, Any] | None = None, page: str | None = None) -> Context:
    return Context(show_of(doc or p6_doc()), LIBRARY, CounterIds(), iface="eth9", page=page)


def p6_command(line: str, doc: dict[str, Any] | None = None, page: str | None = None) -> Any:
    action = parse(line, p6_context(doc, page))
    assert isinstance(action, Submit), action
    return dict(action.command)


CC0 = {"kind": "midiCC", "channel": 1, "cc": 0}
NOTE32 = {"kind": "midiNote", "channel": 1, "note": 32}
OSC_FADER = {"kind": "osc", "path": "/1/fader1"}


def binding(ident: str, surface: str, address: dict[str, Any], action: dict[str, Any],
            **extra: Any) -> dict[str, Any]:  # fmt: skip
    return {"id": ident, "surfaceId": surface, "input": address, "action": action, **extra}


def add_binding(value: dict[str, Any]) -> dict[str, Any]:
    return {"type": "ADD", "path": ["bindings"], "value": value}


def add_surface(ident: str, name: str, kind: str, match: dict[str, Any]) -> dict[str, Any]:
    value = {"id": ident, "name": name, "kind": kind, "match": match, "faderPickup": "jump"}
    return {"type": "ADD", "path": ["surfaces"], "value": value}


B = "b-000000000001"
PHASE6_COMMANDS: list[tuple[str, dict[str, Any]]] = [
    # pages
    ("page 2", {"type": "PAGE", "number": 2}),
    ("page next", {"type": "PAGE", "delta": 1}),
    ("page prev", {"type": "PAGE", "delta": -1}),
    (
        'page add 3 "Songs"',
        {"type": "ADD", "path": ["pages"],
         "value": {"id": "page-000000000001", "name": "Songs", "number": 3, "slots": []}},
    ),
    (
        "page add 4",
        {"type": "ADD", "path": ["pages"],
         "value": {"id": "page-000000000001", "name": "Page 4", "number": 4, "slots": []}},
    ),
    (
        "page 2 slot 3 playback 1",
        {"type": "ASSIGN_PLAYBACK", "pageId": "page-2", "slot": 2, "playbackId": "pb-song"},
    ),
    (
        "page 2 slot 2 clear",
        {"type": "ASSIGN_PLAYBACK", "pageId": "page-2", "slot": 1, "playbackId": None},
    ),
    ('page 2 name "Looks"', {"type": "SET", "path": ["pages", {"id": "page-2"}, "name"],
                             "value": "Looks"}),
    # surfaces
    (
        'surface add osc "Lemur" port 9000 feedback 10.0.0.9:9001',
        add_surface("s-000000000001", "Lemur", "osc",
                    {"port": 9000, "host": "10.0.0.9", "feedbackPort": 9001}),
    ),
    (
        'surface add osc "Lemur" feedback phone.local port 9000',
        add_surface("s-000000000001", "Lemur", "osc", {"port": 9000, "host": "phone.local"}),
    ),
    (
        'surface add osc "Lemur" port 9000 feedback :9001',
        add_surface("s-000000000001", "Lemur", "osc", {"port": 9000, "feedbackPort": 9001}),
    ),
    ('surface add web "Phone"', add_surface("s-000000000001", "Phone", "web", {"port": 8080})),
    (
        'surface add web "Phone" port 8081 on 127.0.0.1',
        add_surface("s-000000000001", "Phone", "web", {"port": 8081, "host": "127.0.0.1"}),
    ),
    (
        'surface "touchosc" pickup soft',
        {"type": "SET", "path": ["surfaces", {"id": "s-osc"}, "faderPickup"], "value": "soft"},
    ),
    # bindings
    (
        'bind "TouchOSC" osc "/1/fader1" fader 1',
        add_binding(binding(B, "s-osc", OSC_FADER, {"kind": "playbackFader", "slot": 0})),
    ),
    (
        'bind "MIDI Controller" clock tap',
        add_binding(binding(B, "s-midi", {"kind": "midiClock"},
                            {"kind": "tap", "masterId": "m-speed"})),
    ),
    (
        'bind "MIDI Controller" cc 1 61 page -1',
        add_binding(binding(B, "s-midi", {"kind": "midiCC", "channel": 1, "cc": 61},
                            {"kind": "page", "delta": -1})),
    ),
    (
        'bind "MIDI Controller" cc 1 62 page +1',
        add_binding(binding(B, "s-midi", {"kind": "midiCC", "channel": 1, "cc": 62},
                            {"kind": "page", "delta": 1})),
    ),
    (
        'bind "MIDI Controller" note 1 40 page 2',
        add_binding(binding(B, "s-midi", {"kind": "midiNote", "channel": 1, "note": 40},
                            {"kind": "pageAbs", "number": 2})),
    ),
    (
        'bind "MIDI Controller" cc 1 16 fader playback 3',
        add_binding(binding(B, "s-midi", {"kind": "midiCC", "channel": 1, "cc": 16},
                            {"kind": "playbackFaderAbs", "playbackId": "pb-blue"})),
    ),
    (
        'bind "MIDI Controller" cc 1 42 blackout momentary',
        add_binding(binding(B, "s-midi", {"kind": "midiCC", "channel": 1, "cc": 42},
                            {"kind": "blackout", "momentary": True})),
    ),
    (
        'bind "MIDI Controller" note 1 32 button 1 1 led',
        add_binding(binding(B, "s-midi", NOTE32, {"kind": "playbackButton", "slot": 0, "button": 0},
                            feedback={"kind": "led", "address": NOTE32})),
    ),
    (
        'bind "MIDI Controller" cc 1 0 fader 1 motor',
        add_binding(binding(B, "s-midi", CC0, {"kind": "playbackFader", "slot": 0},
                            feedback={"kind": "motorFader", "address": CC0})),
    ),
    (
        'bind "MIDI Controller" note 1 32 button 1 1 led cc 1 64',
        add_binding(binding(B, "s-midi", NOTE32, {"kind": "playbackButton", "slot": 0, "button": 0},
                            feedback={"kind": "led",
                                      "address": {"kind": "midiCC", "channel": 1, "cc": 64}})),
    ),
    (
        'bind "TouchOSC" osc "/1/fader1" fader 1 display osc "/1/label1"',
        add_binding(binding(B, "s-osc", OSC_FADER, {"kind": "playbackFader", "slot": 0},
                            feedback={"kind": "display",
                                      "address": {"kind": "osc", "path": "/1/label1"}})),
    ),
    (
        'bind "MIDI Controller" clock tap "Speed 1" led note 1 46',
        add_binding(binding(B, "s-midi", {"kind": "midiClock"},
                            {"kind": "tap", "masterId": "m-speed"},
                            feedback={"kind": "led",
                                      "address": {"kind": "midiNote", "channel": 1, "note": 46}})),
    ),
    # feedback on existing bindings
    (
        'feedback "MIDI Controller" cc 1 0 motor',
        {"type": "BATCH", "label": "feedback on 1 binding",
         "commands": [{"type": "SET", "path": ["bindings", {"id": "b1"}, "feedback"],
                       "value": {"kind": "motorFader", "address": CC0}}]},
    ),
    (
        'feedback "MIDI Controller" note 1 32 led',
        {"type": "BATCH", "label": "feedback on 1 binding",
         "commands": [{"type": "SET", "path": ["bindings", {"id": "b2"}, "feedback"],
                       "value": {"kind": "led", "address": NOTE32}}]},
    ),
    # playbacks and masters
    (
        "playback 1 goto 2",
        {"type": "SET", "path": ["playbacks", {"id": "pb-song"}, "gotoCue"], "value": "2"},
    ),
    (
        'master add fadetime "Fade"',
        {"type": "ADD", "path": ["masters"],
         "value": {"id": "m-000000000001", "kind": "fadeTime", "name": "Fade"}},
    ),
]  # fmt: skip


@pytest.mark.parametrize(("line", "expected"), PHASE6_COMMANDS, ids=[c[0] for c in PHASE6_COMMANDS])
def test_phase_6_commands(line: str, expected: dict[str, Any]) -> None:
    assert p6_command(line) == expected


def test_feedback_covers_a_range_and_none_removes_it() -> None:
    doc = p6_doc()
    cc = [{"kind": "midiCC", "channel": 1, "cc": n} for n in (32, 33, 34)]
    doc["bindings"] = [
        binding("k1", "s-midi", cc[0], {"kind": "playbackButton", "slot": 0, "button": 0}),
        binding("k2", "s-midi", cc[1], {"kind": "playbackButton", "slot": 1, "button": 0}),
        binding("k3", "s-midi", cc[2], {"kind": "blackout"},
                feedback={"kind": "led", "address": cc[2]}),
        binding("k4", "s-midi", cc[2], {"kind": "tap", "masterId": "m-speed"}),  # same input
        binding("k5", "s-osc", OSC_FADER, {"kind": "playbackFader", "slot": 0}),
    ]  # fmt: skip
    batch = p6_command('feedback "MIDI Controller" cc 1 32 thru 34 led', doc)
    assert batch["label"] == "feedback on 4 bindings"
    assert [(c["path"][1]["id"], c["value"]["address"]) for c in batch["commands"]] == [
        ("k1", cc[0]),
        ("k2", cc[1]),
        ("k3", cc[2]),
        ("k4", cc[2]),
    ]
    assert {c["value"]["kind"] for c in batch["commands"]} == {"led"}
    assert p6_command('feedback "MIDI Controller" cc 1 34 thru 32 none', doc) == {
        "type": "BATCH",
        "label": "feedback removed from 1 binding",
        "commands": [{"type": "DELETE", "path": ["bindings", {"id": "k3"}, "feedback"]}],
    }
    assert p6_command('feedback "TouchOSC" osc "/1/fader1" display', doc)["commands"] == [
        {"type": "SET", "path": ["bindings", {"id": "k5"}, "feedback"],
         "value": {"kind": "display", "address": OSC_FADER}}
    ]  # fmt: skip


def test_osc_and_web_ports_default_to_8000_and_8080() -> None:
    assert p6_command('surface add osc "TouchOSC"', load_doc(APPENDIX_A)) == add_surface(
        "s-000000000001", "TouchOSC", "osc", {"port": 8000}
    )
    # Another kind's port does not count: OSC listens on UDP, the web remote on TCP.
    assert p6_command('surface add web "Phone" port 8000')["value"]["match"] == {"port": 8000}


OSC_PATH = 'expected an OSC path in quotes, e.g. "/1/fader1"'


def test_record_slot_names_its_page_or_uses_the_current_one() -> None:
    batch = p6_command('record slot 2.1 "Wash Blue"')
    assert batch["label"] == "recorded slot 2.1: playback 7 'Wash Blue'"
    assert batch["commands"][3] == {
        "type": "ASSIGN_PLAYBACK",
        "pageId": "page-2",
        "slot": 0,
        "playbackId": "pb-000000000002",
    }
    # Without a page: the engine's current page …
    assign = p6_command("record slot 3", page="page-2")["commands"][3]
    assert (assign["pageId"], assign["slot"]) == ("page-2", 2)
    # … else (no engine, or a page the show no longer has) the first page.
    for page in (None, "page-gone"):
        batch = p6_command("record slot 2", page=page)
        assert batch["label"] == "recorded slot 2: playback 2 'Playback 2'"
        assert batch["commands"][3]["pageId"] == "page-1"
    # A slot in use on the named page is merged into, as on the first page.
    record = p6_command("record slot 2.2 merge")
    assert (record["type"], record["cueListId"]) == ("RECORD_CUE", "cl-blue")


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("page 3", "no page 3"),
        ("page add 2", "page 2 exists"),
        ("page add", "expected a page number"),
        ("page 2 slot 0 clear", "slots are counted from 1"),
        ("page 2 slot 1 playback 99", "no playback 99"),
        ("page 2 slot 1 empty", "expected playback or clear, got 'empty'"),
        ("record slot 2.2", "slot 2 is in use on page 2: add merge, replace or remove"),
        ("record slot 2.3 merge", "slot 3 is empty on page 2: record it without merge"),
        ("record slot 3.1", "no page 3"),
        ("record slot 2.x", "expected a slot number, as S or P.S, got '2.x'"),
        ("record slot 2.0", "slots are counted from 1"),
        ('surface add osc "Lemur" port 8000', "port 8000 is in use by surface 'TouchOSC'"),
        ('surface add osc "Lemur"', "port 8000 is in use by surface 'TouchOSC'"),
        ('surface add osc "Lemur" port 70000', "expected a port (1–65535), got '70000'"),
        ('surface add web "Phone" port 0', "expected a port (1–65535), got '0'"),
        ('surface add osc "Lemur" feedback :', "expected <host>[:<port>], got ':'"),
        ('surface add osc "Lemur" port 9000 port 9001', "unexpected 'port'"),
        ('surface add osc "Lemur" feedback 10.0.0.9:x',
         "expected <host>[:<port>], got '10.0.0.9:x'"),
        ('surface add osc "touchosc" port 9000', "a surface named 'touchosc' exists"),
        ('surface add hid "Pad"', "expected midi or osc or web, got 'hid'"),
        ('surface add web "Phone" on', "expected a host"),
        ('surface "Nope" pickup soft', "no surface 'Nope'"),
        ('surface "TouchOSC" pickup sometimes', "expected soft or jump, got 'sometimes'"),
        ('bind "MIDI Controller" cc 1 0 fader 1 blink',
         "expected led, motor or display, got 'blink'"),
        ('bind "MIDI Controller" cc 1 0 fader 1 led cc 1', "expected a CC or note number"),
        ('bind "MIDI Controller" clock fader 1', "expected tap, got 'fader'"),
        ('bind "MIDI Controller" clock tap led',
         "a clock input has no feedback address: give one"),
        ('bind "MIDI Controller" cc 1 61 page 3', "no page 3"),
        ('bind "MIDI Controller" cc 1 61 page next',
         "expected +N, -N or a page number, got 'next'"),
        ('bind "MIDI Controller" cc 1 16 fader playback 99', "no playback 99"),
        ('bind "TouchOSC" osc fader1 fader 1', OSC_PATH),
        ('bind "TouchOSC" osc "1/fader1" fader 1', OSC_PATH),
        ('feedback "MIDI Controller" cc 1 99 led',
         "'MIDI Controller' has no binding on cc 1 99"),
        ('feedback "MIDI Controller" cc 1 0 none', "no feedback to remove"),
        ('feedback "MIDI Controller" cc 1 0 blink',
         "expected led, motor, display or none, got 'blink'"),
        ('feedback "Nope" cc 1 0 led', "no surface 'Nope'"),
        ("playback 1 goto 7", "no cue 1/7"),
        ("playback 1 goto x", "expected a cue number, got 'x'"),
        ('master add fadetime "grand master"', "a master named 'grand master' exists"),
    ],
)  # fmt: skip
def test_phase_6_errors(line: str, error: str) -> None:
    with pytest.raises(ParseError) as raised:
        parse(line, p6_context())
    assert raised.value.message == error


# ------------------------------------------------------------------ Phase 7 (phase-7-plan §5.22)

PARK_PAN = {"slot": {"target": MH1, "attribute": "pan"}, "value": 0}
PARK_TILT = {"slot": {"target": MH1, "attribute": "tilt"}, "value": 10}
PARK_RED = {"slot": {"target": MH2, "attribute": "color"}, "value": {"r": 1, "g": 0, "b": 0}}


def p7_doc() -> dict[str, Any]:
    """Appendix A (MH 1 has a tilt limit) with MH 1's pan and tilt and MH
    2's colour parked, and a strobe cap."""
    doc = load_doc(APPENDIX_A)
    doc["park"] = [PARK_PAN, PARK_TILT, PARK_RED]
    doc["safety"] = {"strobeMaxHz": 3}
    return doc


def p7_context(doc: dict[str, Any] | None = None, library: ProfileLibrary = LIBRARY) -> Context:
    return Context(show_of(doc or p7_doc()), library, CounterIds(), iface="eth9")


def p7_command(line: str, doc: dict[str, Any] | None = None) -> Any:
    action = parse(line, p7_context(doc))
    assert isinstance(action, Submit), action
    return dict(action.command)


def set_park(label: str, *entries: dict[str, Any]) -> dict[str, Any]:
    return {"type": "BATCH", "label": label,
            "commands": [{"type": "SET", "path": ["park"], "value": list(entries)}]}  # fmt: skip


def labelled(label: str, *commands: dict[str, Any]) -> dict[str, Any]:
    return {"type": "BATCH", "label": label, "commands": list(commands)}


def limits(fixture: str, value: dict[str, Any]) -> dict[str, Any]:
    return {"type": "SET", "path": ["fixtures", {"id": fixture}, "limits"], "value": value}


def command_binding(note: int, command: dict[str, Any], **extra: Any) -> dict[str, Any]:
    address = {"kind": "midiNote", "channel": 1, "note": note}
    return add_binding(binding(B, "s-midi", address, {"kind": "command", "command": command},
                               **extra))  # fmt: skip


PHASE7_COMMANDS: list[tuple[str, dict[str, Any]]] = [
    # park: new slots at the end, parked slots replaced in place
    ("park fixture 201 intensity 0",
     set_park("parked fixture 201 intensity at 0", PARK_PAN, PARK_TILT, PARK_RED,
              {"slot": {"target": PAR, "attribute": "intensity"}, "value": 0})),
    ("park group 1 pan 15",
     set_park("parked group 1 pan at 15", {**PARK_PAN, "value": 15}, PARK_TILT, PARK_RED,
              {"slot": {"target": MH2, "attribute": "pan"}, "value": 15})),
    ("park 102 color 0 0 1 w 0.5",
     set_park("parked 102 color at 0 0 1 w 0.5", PARK_PAN, PARK_TILT,
              {**PARK_RED, "value": {"r": 0, "g": 0, "b": 1, "w": 0.5}})),
    ("park fixture 101, fixture 201 shutter closed",
     set_park("parked fixture 101 , fixture 201 shutter at closed", PARK_PAN, PARK_TILT, PARK_RED,
              {"slot": {"target": MH1, "attribute": "shutter"}, "value": {"slot": "closed"}},
              {"slot": {"target": PAR, "attribute": "shutter"}, "value": {"slot": "closed"}})),
    # unpark: one attribute, every attribute of the targets, everything
    ("unpark fixture 101 pan", set_park("unparked fixture 101 pan", PARK_TILT, PARK_RED)),
    ("unpark fixture 101", set_park("unparked fixture 101", PARK_RED)),
    ("unpark group 1 color", set_park("unparked group 1 color", PARK_PAN, PARK_TILT)),
    ("unpark all", set_park("unparked everything (3 parked)")),
    # limits: each fixture's limits set whole, keeping the keys not named
    ("fixture 101 limits pan -90 90",
     labelled("limited fixture 101: pan -90° to 90°",
              limits("fx-mh1", {"tilt": (-120.0, 120.0), "pan": [-90, 90]}))),
    ("fixture 101 thru 102 limits tilt -90 10",
     labelled("limited fixture 101 thru 102: tilt -90° to 10°",
              limits("fx-mh1", {"tilt": [-90, 10]}), limits("fx-mh2", {"tilt": [-90, 10]}))),
    ("fixture 201 limits intensity 50%",
     labelled("limited fixture 201: intensity at most 0.5",
              limits("fx-par1", {"intensityMax": 0.5}))),
    ("fixture 201 thru 101 limits none",  # only MH 1 has limits
     labelled("removed the limits of fixture 201 thru 101",
              {"type": "DELETE", "path": ["fixtures", {"id": "fx-mh1"}, "limits"]})),
    # the strobe cap
    ("safety strobe 2.5",
     labelled("strobe cap 2.5 Hz",
              {"type": "SET", "path": ["safety"], "value": {"strobeMaxHz": 2.5}})),
    ("safety strobe off",
     labelled("removed the strobe cap", {"type": "DELETE", "path": ["safety", "strobeMaxHz"]})),
    # panic
    ("release all", {"type": "RELEASE_ALL"}),
    ("release all 0.5", {"type": "RELEASE_ALL", "time": 0.5}),
    ("output on", {"type": "OUTPUT", "on": True}),
    ("output off", {"type": "OUTPUT", "on": False}),
    # bindings
    ('bind "MIDI Controller" note 1 60 release all', command_binding(60, {"type": "RELEASE_ALL"})),
    ('bind "MIDI Controller" note 1 61 release all 2 led',
     command_binding(61, {"type": "RELEASE_ALL", "time": 2},
                     feedback={"kind": "led",
                               "address": {"kind": "midiNote", "channel": 1, "note": 61}})),
    ('bind "MIDI Controller" note 1 62 output off',
     command_binding(62, {"type": "OUTPUT", "on": False})),
    ('bind "MIDI Controller" note 1 63 output on',
     command_binding(63, {"type": "OUTPUT", "on": True})),
]  # fmt: skip


@pytest.mark.parametrize(("line", "expected"), PHASE7_COMMANDS, ids=[c[0] for c in PHASE7_COMMANDS])
def test_phase_7_commands(line: str, expected: dict[str, Any]) -> None:
    assert p7_command(line) == expected


def test_park_and_limits_on_a_show_without_any() -> None:
    """Appendix A parks nothing and has no strobe cap: the first entry and
    the first ``safety`` come from nothing."""
    assert p7_command("park 201 intensity 0", load_doc(APPENDIX_A)) == set_park(
        "parked 201 intensity at 0", {"slot": {"target": PAR, "attribute": "intensity"}, "value": 0}
    )
    assert p7_command("safety strobe 3", load_doc(APPENDIX_A))["commands"] == [
        {"type": "SET", "path": ["safety"], "value": {"strobeMaxHz": 3}}
    ]


def test_park_gives_every_element_of_a_fixture_an_entry() -> None:
    action = parse("park fixture 301 intensity 0", context(DEMO))
    assert isinstance(action, Submit)
    entries = dict(action.command)["commands"][0]["value"]
    fixture = next(f for f in load_doc(DEMO)["fixtures"] if f["number"] == 301)
    assert len(entries) > 1
    assert [e["slot"]["target"] for e in entries] == [
        {"fixtureId": fixture["id"], "element": k} for k in range(len(entries))
    ]


def test_only_output_off_asks_first() -> None:
    questions = {
        line: action.confirm
        for line in ("output off", "output on", "release all", "unpark all", "blackout on")
        if isinstance(action := parse(line, p7_context()), Submit)
    }
    assert questions == {
        "output off": "Turn all DMX output off?",
        "output on": None,
        "release all": None,
        "unpark all": None,
        "blackout on": None,
    }


def test_list_park_and_profiles_are_queries() -> None:
    assert parse("list park", p7_context()) == Query("list", "park")
    assert parse("list profiles", p7_context()) == Query("list", "profiles")


# profile update (§5.20): the show embeds 'Generic Spot 16ch' revision 1


def spot_library(tmp_path: Path, **changes: Any) -> ProfileLibrary:
    """A library holding only a copy of the built-in spot with ``changes``."""
    profile = json.loads((PROFILES / "generic-spot-16ch.json").read_text(encoding="utf-8"))
    profile.update(changes)
    (tmp_path / "spot.json").write_text(json.dumps(profile), encoding="utf-8")
    library = ProfileLibrary([tmp_path], builtin=False)
    assert not library.problems, library.problems
    return library


def test_profile_update_sets_what_changed_and_moves_the_fixtures(tmp_path: Path) -> None:
    library = spot_library(
        tmp_path, revision="2", physical={"panRange": 540, "tiltRange": 270, "maxStrobeHz": 25}
    )
    doc = load_doc(APPENDIX_A)
    doc["profiles"][0]["notes"] = "hand-edited"  # the library's copy has no notes
    action = parse('profile update "generic spot 16CH"', p7_context(doc, library))
    assert isinstance(action, Submit)
    spot = ["profiles", {"id": "prof-mh"}]
    assert dict(action.command) == labelled(
        "updated profile 'Generic Spot 16ch' to revision '2' (2 fixtures)",
        {"type": "SET", "path": [*spot, "revision"], "value": "2"},
        {"type": "SET", "path": [*spot, "category"], "value": "spot"},  # the show has none
        {"type": "SET", "path": [*spot, "physical"],
         "value": {"panRange": 540, "tiltRange": 270, "maxStrobeHz": 25}},
        {"type": "DELETE", "path": [*spot, "notes"]},
        {"type": "SET", "path": ["fixtures", {"id": "fx-mh1"}, "profileRevision"], "value": "2"},
        {"type": "SET", "path": ["fixtures", {"id": "fx-mh2"}, "profileRevision"], "value": "2"},
    )  # fmt: skip


def test_profile_update_finds_a_renamed_copy_by_the_library_name(tmp_path: Path) -> None:
    library = spot_library(tmp_path, revision="2")
    doc = load_doc(APPENDIX_A)
    doc["profiles"][0]["name"] = "Our spots"
    action = parse('profile update "Generic Spot 16ch"', p7_context(doc, library))
    assert isinstance(action, Submit)
    assert [c["path"][-1] for c in dict(action.command)["commands"]][:2] == ["name", "revision"]


def test_profile_update_errors(tmp_path: Path) -> None:
    def error(line: str, library: ProfileLibrary) -> str:
        with pytest.raises(ParseError) as raised:
            parse(line, p7_context(load_doc(APPENDIX_A), library))
        return raised.value.message

    assert error('profile update "Generic Spot 16ch"', LIBRARY) == (
        "'Generic Spot 16ch' is already at the library's revision '1'"
    )
    assert error('profile update "RGB Par 3ch"', spot_library(tmp_path, revision="2")) == (
        "no library profile named 'RGB Par 3ch' (see 'library')"
    )
    assert error('profile update "Nope"', LIBRARY) == (
        "the show has no profile 'Nope' (see 'list profiles')"
    )
    assert error("profile update spot", LIBRARY) == (
        'expected a profile name in quotes, e.g. "Generic Spot 16ch"'
    )
    profile = json.loads((PROFILES / "generic-spot-16ch.json").read_text(encoding="utf-8"))
    renamed = [{**profile["modes"][0], "id": "mode-16b"}]
    assert error('profile update "Generic Spot 16ch"',
                 spot_library(tmp_path, revision="2", modes=renamed)) == (
        "fixture 101 'MH 1' runs mode '16ch', which revision '2' of 'Generic Spot 16ch' lacks"
    )  # fmt: skip


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("park fixture 999 intensity 0", "no fixture 999"),
        ("park fixture 201 sparkle 1", "unknown attribute 'sparkle'"),
        ("park fixture 201 intensity", "expected a number"),
        ("park fixture 201 intensity 0 1", "unexpected '1'"),
        ("unpark fixture 201", "nothing parked on fixture 201"),
        ("unpark fixture 101 color", "nothing parked on fixture 101 color"),
        ("unpark all now", "unexpected 'now'"),
        ("fixture 999 limits none", "no fixture 999"),
        ("fixture 400 thru 500 limits none", "no fixture from 400 to 500"),
        ("fixture 101 limits pan 20 10", "min 20 above max 10"),
        ("fixture 101 limits pan 20", "expected the highest pan in degrees"),
        ("fixture 101 limits zoom 1 2", "expected pan or tilt or intensity or none, got 'zoom'"),
        ("fixture 102 limits none", "fixture 102 has no limits"),
        ("fixture 101.1 limits none", "expected a fixture number, got '101.1'"),
        ("safety strobe", "expected a rate in Hz, or off"),
        ("safety flash 3", "expected strobe, got 'flash'"),
        ("release all soon", "unexpected 'soon'"),
        ("output maybe", "expected on or off, got 'maybe'"),
        ("output", "expected on or off"),
        ('bind "MIDI Controller" note 1 60 release everything', "expected all, got 'everything'"),
        ('bind "MIDI Controller" note 1 60 output', "expected on or off"),
    ],
)  # fmt: skip
def test_phase_7_errors(line: str, error: str) -> None:
    with pytest.raises(ParseError) as raised:
        parse(line, p7_context())
    assert raised.value.message == error


def test_unbind_removes_every_binding_of_the_inputs() -> None:
    """``unbind`` frees inputs to bind anew (the §5.24 script moves marker
    SET from a playback button to ``release all``)."""
    doc = p6_doc()
    cc = [{"kind": "midiCC", "channel": 1, "cc": n} for n in (32, 33, 34)]
    doc["bindings"] = [
        binding("k1", "s-midi", cc[0], {"kind": "playbackButton", "slot": 0, "button": 0}),
        binding("k2", "s-midi", cc[2], {"kind": "blackout"}),
        binding("k3", "s-midi", cc[2], {"kind": "tap", "masterId": "m-speed"}),  # same input
        binding("k4", "s-osc", OSC_FADER, {"kind": "playbackFader", "slot": 0}),
    ]  # fmt: skip

    def deleted(*ids: str) -> list[dict[str, Any]]:
        return [{"type": "DELETE", "path": ["bindings", {"id": i}]} for i in ids]

    assert p6_command('unbind "MIDI Controller" cc 1 34', doc) == {
        "type": "BATCH", "label": "unbound 2 bindings", "commands": deleted("k2", "k3")
    }  # fmt: skip
    assert p6_command('unbind "TouchOSC" osc "/1/fader1"', doc) == {
        "type": "BATCH", "label": "unbound 1 binding", "commands": deleted("k4")
    }  # fmt: skip
    with pytest.raises(ParseError) as raised:  # cc 33 is free: nothing half done
        parse('unbind "MIDI Controller" cc 1 32 thru 34', p6_context(doc))
    assert raised.value.message == "'MIDI Controller' has no binding on cc 1 33"
    with pytest.raises(ParseError) as raised:
        parse('unbind "MIDI Controller" cc 1 32 led', p6_context(doc))
    assert raised.value.message == "unexpected 'led'"


def test_no_strobe_cap_to_remove() -> None:
    with pytest.raises(ParseError) as raised:
        parse("safety strobe off", p7_context(load_doc(APPENDIX_A)))
    assert raised.value.message == "no strobe cap is set"
    with pytest.raises(ParseError) as raised:
        parse("unpark all", p7_context(load_doc(APPENDIX_A)))
    assert raised.value.message == "nothing is parked"


def test_help_lists_the_phase_7_commands() -> None:
    assert parse("help", p7_context()) == Query("help")
    rows = [line.strip() for line in HELP]
    for row in (
        "release all [<seconds>] | output on|off",
        "park <targets> <attribute> <value> | unpark <targets> [<attribute>] | unpark all",
        "fixture N [thru M] limits pan|tilt <min> <max>",
        "safety strobe <hz> | safety strobe off",
        'profile update "<name>" | profile "<name>" category <category>|none',
    ):
        assert row in rows


# ------------------------------------------- playback buttons (GAP-04, engine-gaps.md)

BUTTON_COMMANDS: list[tuple[str, dict[str, Any]]] = [
    ("flash 3 on", {"type": "FLASH", "playbackId": "pb-blue", "down": True}),
    ("FLASH 3 OFF", {"type": "FLASH", "playbackId": "pb-blue", "down": False}),
    ("flash 1 on", {"type": "FLASH", "playbackId": "pb-song", "down": True}),  # no flash button
    ("toggle 3", {"type": "TOGGLE_PLAYBACK", "playbackId": "pb-blue"}),
    ("button 3 1 on",
     {"type": "PLAYBACK_BUTTON", "playbackId": "pb-blue", "button": 0, "down": True}),
    ("button 3 2 off",
     {"type": "PLAYBACK_BUTTON", "playbackId": "pb-blue", "button": 1, "down": False}),
]  # fmt: skip


@pytest.mark.parametrize(("line", "expected"), BUTTON_COMMANDS, ids=[c[0] for c in BUTTON_COMMANDS])
def test_playback_button_lines(line: str, expected: dict[str, Any]) -> None:
    assert command(line) == expected


def test_a_select_buttons_press_selects_as_a_binding_does() -> None:
    """Its press is the programmer's ``SELECT_PLAYBACK``; its release goes to
    the engine, which does nothing with it."""
    doc = load_doc(APPENDIX_A)
    doc["playbacks"][1]["buttons"] = ["toggle", "select"]
    ctx = Context(show_of(doc), LIBRARY, CounterIds())
    assert parse("button 3 2 on", ctx) == Submit(
        {"type": "SELECT_PLAYBACK", "playbackId": "pb-blue", "mode": "replace"}
    )
    assert parse("button 3 2 off", ctx) == Submit(
        {"type": "PLAYBACK_BUTTON", "playbackId": "pb-blue", "button": 1, "down": False}
    )


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("flash 9 on", "no playback 9"),
        ("flash 3", "expected on or off"),
        ("flash 3 down", "expected on or off, got 'down'"),
        ("flash 3 on now", "unexpected 'now'"),
        ("toggle 9", "no playback 9"),
        ("toggle 3 on", "unexpected 'on'"),
        ("button 9 1 on", "no playback 9"),
        ("button 3", "expected a button number (from 1)"),
        ("button 3 flash on", "expected a button number (from 1), got 'flash'"),
        ("button 3 0 on", "buttons are counted from 1"),
        ("button 3 3 on", "playback 3 has 2 button(s); no button 3"),
        ("button 3 1", "expected on or off"),
    ],
)
def test_playback_button_errors(line: str, error: str) -> None:
    with pytest.raises(ParseError) as raised:
        parse(line, context())
    assert raised.value.message == error


def test_help_lists_the_playback_button_lines() -> None:
    assert "flash N on|off | toggle N | button N <b> on|off" in [line.strip() for line in HELP]


# -------------------------- relative and per-component values (GAP-05, engine-gaps.md)

ADJUST_COMMANDS: list[tuple[str, dict[str, Any]]] = [
    ("set intensity by 5%", {"type": "ADJUST_ATTRIBUTE", "attribute": "intensity", "delta": 0.05}),
    ("set pan by -15", {"type": "ADJUST_ATTRIBUTE", "attribute": "pan", "delta": -15}),
    ("set Tilt BY +12.5", {"type": "ADJUST_ATTRIBUTE", "attribute": "tilt", "delta": 12.5}),
    ("set color.r 50%",
     {"type": "ADJUST_ATTRIBUTE", "attribute": "color", "component": "r", "value": 0.5}),
    ("set COLOR.UV by -10%",
     {"type": "ADJUST_ATTRIBUTE", "attribute": "color", "component": "uv", "delta": -0.1}),
    ("set color.w by 0",
     {"type": "ADJUST_ATTRIBUTE", "attribute": "color", "component": "w", "delta": 0}),
    ("set pan -45",  # a negative value is still a value: pan and tilt have them
     {"type": "SET_ATTRIBUTE", "attribute": "pan", "value": {"kind": "literal", "value": -45}}),
]  # fmt: skip


@pytest.mark.parametrize(("line", "expected"), ADJUST_COMMANDS, ids=[c[0] for c in ADJUST_COMMANDS])
def test_relative_and_component_lines(line: str, expected: dict[str, Any]) -> None:
    assert command(line) == expected


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("set intensity +5%",
         "'+5%' has a plus sign: 'set intensity by +5%' changes intensity by 5%, "
         "'set intensity 5%' sets it"),
        ("set pan +45",
         "'+45' has a plus sign: 'set pan by +45' changes pan by 45, 'set pan 45' sets it"),
        ("set color.r +5%",
         "'+5%' has a plus sign: 'set color.r by +5%' changes color.r by 5%, "
         "'set color.r 5%' sets it"),
        ("set color by 5%",
         "a colour changes by component: set color.r by 5% (r, g, b, w, a or uv)"),
        ("set gobo1 by 1", "gobo1 is discrete: it has no relative values"),
        ("set color.x 1", "a colour has no component 'x' (r, g, b, w, a, uv)"),
        ("set color.r", "expected the colour's r"),
        ("set color.r spread 0 1", "expected the colour's r, got 'spread'"),
        ("set color.r 1 0 0", "unexpected '0'"),
        ("set intensity by", "expected a change, e.g. 5% or -15"),
        ("set intensity by fast", "expected a change, e.g. 5% or -15, got 'fast'"),
        ("set intensity by 5% 3", "unexpected '3'"),
        ("park fixture 101 color.r 1", "unknown attribute 'color.r'"),
    ],
)  # fmt: skip
def test_relative_and_component_errors(line: str, error: str) -> None:
    with pytest.raises(ParseError) as raised:
        parse(line, context())
    assert raised.value.message == error


def test_help_lists_the_relative_and_component_lines() -> None:
    stripped = [line.strip() for line in HELP]
    assert "set <attribute> <value> | set <attribute> by <change>" in stripped
    assert "set color.r|g|b|w|a|uv <value> | set color.r|g|b|w|a|uv by <change>" in stripped


# ------------------------------- stopping a programmer effect (GAP-14, engine-gaps.md)


def test_help_lists_the_stop_and_run_lines() -> None:
    stripped = [line.strip() for line in HELP]
    assert "effect remove <id> | effect clear | effect stop <id> | effect run <id>" in stripped
