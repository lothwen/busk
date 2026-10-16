"""The limitation report: every show feature this build accepts but ignores."""

from __future__ import annotations

from typing import Any, cast

import pytest

from builders import DEMO, Doc, compile_doc, load_doc
from busk.compiler.limitations import collect_limitations
from busk.model.show import Show


def report(doc: Doc) -> list[str]:
    compiled = compile_doc(doc)
    return [str(limitation) for limitation in collect_limitations(cast(Show, doc), compiled)]


APPENDIX_A_REPORT: list[str] = []  # its effect, size fader, soft pickup and limits all work

SIZE_MASTER = {"id": "m-size", "kind": "size", "name": "Size"}
GROUP_MASTER = {"id": "m-group", "kind": "group", "name": "Heads", "groupId": "g-mh"}
FADE_MASTER = {"id": "m-fade", "kind": "fadeTime", "name": "Fade"}


def test_appendix_a_has_no_limitations(appendix_a: dict[str, Any]) -> None:
    assert report(appendix_a) == APPENDIX_A_REPORT


def test_the_phase_1_demo_has_none() -> None:
    assert report(load_doc(DEMO)) == []


def edit(doc: Doc, path: str, value: Any) -> None:
    """Set ``doc[a][b]…`` for a dotted path with integer list indices."""
    keys: list[Any] = [int(key) if key.isdigit() else key for key in path.split(".")]
    node = doc
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = value


def test_a_stall_that_darkens_the_stage_is_not_listed(appendix_a: dict[str, Any]) -> None:
    """``holdLastFrameOnEngineStall: false`` works since Phase 7 step 5."""
    edit(appendix_a, "output.holdLastFrameOnEngineStall", False)
    assert report(appendix_a) == APPENDIX_A_REPORT


def test_what_phase_4_plays_is_not_listed(appendix_a: dict[str, Any]) -> None:
    """Sequences, curves, per-family and per-entry timing, back buttons,
    chases and rate faders all work now."""
    timing = appendix_a["cueLists"][1]["cues"][0]["timing"]
    timing.update(curve={"bezier": [0.4, 0, 0.2, 1]}, perFamily={"color": {"fade": 3, "delay": 0}})
    appendix_a["cueLists"][1]["cues"][0]["entries"][0]["timing"] = {"fade": 3}
    appendix_a["cueLists"][1].update(
        mode="chase",
        chase={"rate": {"kind": "bpm", "masterId": "m-speed", "multiplier": 1},
               "direction": "forward", "crossfade": 0},
    )  # fmt: skip
    appendix_a["playbacks"][1].update(fader="rate", buttons=["go", "back"])
    assert report(appendix_a) == APPENDIX_A_REPORT


def test_what_phase_5_plays_is_not_listed(appendix_a: dict[str, Any]) -> None:
    """Effects in any cue, ``size`` faders, and size and group masters (bound
    to a control or set by a command) all work now."""
    (effect,) = appendix_a["cueLists"][2]["cues"][0]["effects"]
    appendix_a["cueLists"][0]["cues"][1]["effects"] = [
        {**effect, "id": "ei-2"},
        {**effect, "id": "ei-3", "sizeMasterId": "m-size"},
    ]
    appendix_a["masters"] += [SIZE_MASTER, GROUP_MASTER]
    midi = {"surfaceId": "s-midi", "input": {"kind": "midiCC", "channel": 1, "cc": 9}}
    appendix_a["bindings"].extend(
        [
            {"id": "b7", **midi, "action": {"kind": "master", "masterId": "m-size"}},
            {"id": "b8", **midi,
             "action": {"kind": "command",
                        "command": {"type": "SET_MASTER", "masterId": "m-size", "level": 1}}},
            {"id": "b9", **midi, "action": {"kind": "master", "masterId": "m-group"}},
            {"id": "b10", **midi,
             "action": {"kind": "command",
                        "command": {"type": "SET_MASTER", "masterId": "m-group", "level": 1}}},
        ]
    )  # fmt: skip
    assert report(appendix_a) == APPENDIX_A_REPORT


def test_the_phase_7_list(appendix_a: dict[str, Any]) -> None:
    """Everything still ignored after Phase 7 (phase-7-plan §5.22), all in one
    show next to every Phase 6 and Phase 7 feature, reported in document
    order: park, limits, the strobe cap, a darkening stall, and the panic
    and highlight commands on bindings are not listed."""
    appendix_a["playbacks"][1].update(fader="crossfade", buttons=["goto", "swop"], gotoCue="1")
    appendix_a["pages"].append({"id": "page-2", "number": 2, "name": "Two", "slots": []})
    appendix_a["masters"].append(FADE_MASTER)
    appendix_a["surfaces"].extend(
        [
            {"id": "s-osc", "name": "TouchOSC", "kind": "osc", "match": {"port": 9000},
             "faderPickup": "soft"},
            {"id": "s-web", "name": "Phone", "kind": "web", "match": {"port": 8080},
             "faderPickup": "jump"},
            {"id": "s-int", "name": "Panel", "kind": "internal", "match": {},
             "faderPickup": "jump"},
        ]
    )  # fmt: skip
    cc = {"kind": "midiCC", "channel": 1, "cc": 9}
    label = {"kind": "osc", "path": "/1/label"}
    appendix_a["bindings"].extend(
        [
            {"id": "b4", "surfaceId": "s-midi", "input": cc,
             "action": {"kind": "page", "delta": 1},
             "feedback": {"kind": "led", "address": cc}},
            {"id": "b5", "surfaceId": "s-midi", "input": {"kind": "hw", "controlId": "f1"},
             "action": {"kind": "blackout"}},
            {"id": "b6", "surfaceId": "s-midi", "input": {"kind": "midiClock"},
             "action": {"kind": "tap", "masterId": "m-speed"}},
            {"id": "b7", "surfaceId": "s-midi", "input": cc,
             "action": {"kind": "playbackFaderAbs", "playbackId": "pb-blue"},
             "feedback": {"kind": "display", "address": cc}},
            {"id": "b8", "surfaceId": "s-osc", "input": {"kind": "osc", "path": "/1/fader"},
             "action": {"kind": "playbackFader", "slot": 0},
             "feedback": {"kind": "display", "address": label}},
            {"id": "b9", "surfaceId": "s-osc", "input": {"kind": "osc", "path": "/1/go"},
             "action": {"kind": "command",
                        "command": {"type": "PLAYBACK_BUTTON", "slot": 0, "button": 0,
                                    "down": True}},
             "feedback": {"kind": "led", "address": label}},
            *({"id": f"b{10 + k}", "surfaceId": "s-midi",
               "input": {"kind": "midiNote", "channel": 1, "note": 60 + k},
               "action": {"kind": "command", "command": command}}
              for k, command in enumerate([{"type": "RELEASE_ALL", "time": 1},
                                           {"type": "OUTPUT", "on": False},
                                           {"type": "HIGHLIGHT", "on": True}])),
        ]
    )  # fmt: skip
    appendix_a["output"]["holdLastFrameOnEngineStall"] = False
    appendix_a["fixtures"][1]["limits"] = {"pan": [-90, 90], "intensityMax": 0.5}
    appendix_a["safety"] = {"strobeMaxHz": 3}
    appendix_a["park"] = [
        {"slot": {"target": {"fixtureId": "fx-mh1", "element": 0}, "attribute": "pan"},
         "value": 0}
    ]  # fmt: skip
    assert report(appendix_a) == [
        "surfaces[3].kind: internal surfaces are not implemented",
        "bindings[4].input: hw inputs are not implemented",
        "bindings[6].feedback: MIDI surfaces cannot show display feedback",
        "bindings[8].feedback: a command action has no state to show",
    ]


def test_no_button_function_is_listed(appendix_a: dict[str, Any]) -> None:
    """Every button function works since Phase 6 step 5 (swop)."""
    appendix_a["playbacks"][1]["buttons"] = [
        "go", "back", "goto", "flash", "toggle", "release", "select", "swop", "none"
    ]  # fmt: skip
    assert report(appendix_a) == APPENDIX_A_REPORT


@pytest.mark.parametrize("kind", ["master", "temp", "rate", "size", "crossfade", "none"])
def test_no_fader_function_is_listed(appendix_a: dict[str, Any], kind: str) -> None:
    """Every fader function works since Phase 6 step 8 (crossfade)."""
    appendix_a["playbacks"][1]["fader"] = kind
    assert report(appendix_a) == APPENDIX_A_REPORT


def test_pages_and_page_actions_are_not_listed(appendix_a: dict[str, Any]) -> None:
    """The engine switches pages since Phase 6."""
    appendix_a["pages"].append({"id": "page-2", "number": 2, "name": "Two", "slots": ["pb-blue"]})
    appendix_a["bindings"] += [
        {"id": "b4", "surfaceId": "s-midi", "input": {"kind": "midiCC", "channel": 1, "cc": 9},
         "action": {"kind": "page", "delta": 1}},
        {"id": "b5", "surfaceId": "s-midi", "input": {"kind": "midiCC", "channel": 1, "cc": 10},
         "action": {"kind": "pageAbs", "number": 2}},
        {"id": "b6", "surfaceId": "s-midi", "input": {"kind": "midiCC", "channel": 1, "cc": 11},
         "action": {"kind": "command", "command": {"type": "PAGE", "delta": -1}}},
    ]  # fmt: skip
    assert report(appendix_a) == APPENDIX_A_REPORT


def test_feedback_is_listed_only_where_it_shows_nothing(appendix_a: dict[str, Any]) -> None:
    """LEDs and motor faders work since Phase 6 step 10; a MIDI surface has no
    display, and a command action no state to show."""
    cc = {"kind": "midiCC", "channel": 1, "cc": 9}
    appendix_a["bindings"][0]["feedback"] = {"kind": "motorFader", "address": cc}
    appendix_a["bindings"][1]["feedback"] = {"kind": "led", "address": cc}
    appendix_a["bindings"][2]["feedback"] = {"kind": "display", "address": cc}
    appendix_a["bindings"].append(
        {"id": "b4", "surfaceId": "s-midi", "input": {"kind": "midiCC", "channel": 1, "cc": 10},
         "action": {"kind": "command", "command": {"type": "BLACKOUT"}},
         "feedback": {"kind": "led", "address": cc}}
    )  # fmt: skip
    assert report(appendix_a) == [
        *APPENDIX_A_REPORT,
        "bindings[2].feedback: MIDI surfaces cannot show display feedback",
        "bindings[3].feedback: a command action has no state to show",
    ]


def test_goto_buttons_and_playback_button_commands_are_not_listed(
    appendix_a: dict[str, Any],
) -> None:
    """The engine applies playback buttons since Phase 6 step 4."""
    appendix_a["playbacks"][0].update(buttons=["goto"], gotoCue="2")
    appendix_a["bindings"].append(
        {"id": "b4", "surfaceId": "s-midi", "input": {"kind": "midiCC", "channel": 1, "cc": 9},
         "action": {"kind": "command", "command": {
             "type": "PLAYBACK_BUTTON", "slot": 0, "button": 0, "down": True}}}
    )  # fmt: skip
    assert report(appendix_a) == APPENDIX_A_REPORT


def test_surfaces_and_bindings(appendix_a: dict[str, Any]) -> None:
    surfaces, bindings = appendix_a["surfaces"], appendix_a["bindings"]
    appendix_a["masters"].append(FADE_MASTER)
    surfaces[0]["faderPickup"] = "jump"
    surfaces.append(
        {"id": "s-hid", "name": "Keys", "kind": "hid", "match": {}, "faderPickup": "jump"}
    )
    midi = {"surfaceId": "s-midi", "input": {"kind": "midiCC", "channel": 1, "cc": 9}}
    bindings.extend(
        [
            # Bindings on a reported surface are not listed again.
            {"id": "b4", "surfaceId": "s-hid", "input": {"kind": "hw", "controlId": "k1"},
             "action": {"kind": "blackout"}},
            # Tap actions and speed masters work since Phase 4: not listed.
            {"id": "b5", **midi, "action": {"kind": "tap", "masterId": "m-speed"}},
            {"id": "b6", **midi, "action": {"kind": "pageAbs", "number": 2}},
            # Fade-time masters work since Phase 6: not listed.
            {"id": "b7", **midi, "action": {"kind": "master", "masterId": "m-fade"}},
            {"id": "b8", **midi,
             "action": {"kind": "command",
                        "command": {"type": "SET_MASTER", "masterId": "m-fade", "level": 1}}},
            {"id": "b11", **midi, "action": {"kind": "master", "masterId": "m-speed"}},
            {"id": "b9", **midi,
             "action": {"kind": "command", "command": {"type": "GO", "playbackId": "pb-song"}},
             "feedback": {"kind": "led", "address": {"kind": "midiCC", "channel": 1, "cc": 9}}},
            {"id": "b10", "surfaceId": "s-midi", "input": {"kind": "hw", "controlId": "f2"},
             "action": {"kind": "blackout"}},
        ]
    )  # fmt: skip
    assert report(appendix_a)[-3:] == [
        "surfaces[1].kind: hid surfaces are not implemented",
        "bindings[9].feedback: a command action has no state to show",
        "bindings[10].input: hw inputs are not implemented",
    ]


def test_web_surfaces_are_not_listed(appendix_a: dict[str, Any]) -> None:
    """The web remote works since Phase 6 step 13. A binding on it does
    nothing, but validation already warns about that."""
    appendix_a["surfaces"].append(
        {"id": "s-web", "name": "Phone", "kind": "web", "match": {"port": 8080},
         "faderPickup": "jump"}
    )  # fmt: skip
    appendix_a["bindings"].append(
        {"id": "b4", "surfaceId": "s-web", "input": {"kind": "midiCC", "channel": 1, "cc": 1},
         "action": {"kind": "blackout"},
         "feedback": {"kind": "led", "address": {"kind": "midiCC", "channel": 1, "cc": 1}}}
    )  # fmt: skip
    assert report(appendix_a) == APPENDIX_A_REPORT


def test_osc_surfaces_and_inputs_are_not_listed(appendix_a: dict[str, Any]) -> None:
    """OSC works since Phase 6 step 11, display feedback included; feedback
    on a command action still shows nothing."""
    appendix_a["surfaces"].append(
        {"id": "s-osc", "name": "Phone", "kind": "osc", "match": {"port": 9000},
         "faderPickup": "jump"}
    )  # fmt: skip
    path = {"kind": "osc", "path": "/1/fader1"}
    appendix_a["bindings"] += [
        {"id": "b4", "surfaceId": "s-osc", "input": path,
         "action": {"kind": "playbackFader", "slot": 0},
         "feedback": {"kind": "display", "address": {"kind": "osc", "path": "/1/label1"}}},
        {"id": "b5", "surfaceId": "s-osc", "input": {"kind": "osc", "path": "/go"},
         "action": {"kind": "command", "command": {"type": "GO", "playbackId": "pb-song"}},
         "feedback": {"kind": "led", "address": {"kind": "osc", "path": "/go/led"}}},
    ]  # fmt: skip
    assert report(appendix_a) == [
        *APPENDIX_A_REPORT,
        "bindings[4].feedback: a command action has no state to show",
    ]
