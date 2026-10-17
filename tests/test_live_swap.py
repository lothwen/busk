"""Live swap: edits reach a running engine, output and input (phase-3-plan §5.7).

Every case checks bytes on the wire-to-be, and most also check that the live
engine equals a *fresh* engine started on the edited show with the same
performance commands: a live swap must never leave a trace of the old show.
"""

from __future__ import annotations

import math
import socket
from typing import Any, cast

import pytest

from artnet_node import ArtNetReceiver
from builders import (
    busk_rig,
    compile_doc,
    cue,
    cue_list,
    effect_instance,
    effect_layer,
    effect_template,
    entry,
    group,
    in_group,
    literal,
    look,
    page,
    playback,
    preset,
    preset_source,
    preset_value,
    size_master,
    speed_master,
    targets,
)
from busk.commands.types import Command
from busk.compiler.compile import compile_show
from busk.engine.clock import FakeClock
from busk.engine.loop import Engine
from busk.engine.playback_runtime import PlaybackRuntime
from busk.io.bindings import BindingResolver
from busk.io.events import InputEvent
from busk.model.common import SurfaceId
from busk.model.surface import InputAddress
from busk.output.artnet import ArtNetNetwork
from busk.output.sacn import Sequences
from busk.output.scheduler import OutputScheduler, build_routes
from busk.session.session import InputSink, Session
from sacn_receiver import Receiver
from session_harness import CLEAR, Live, fader, put, sel, trigger

BLUE = (0, 0, 255, 0)
RED, GREEN = (255, 0, 0), (0, 255, 0)


def rig() -> dict[str, Any]:
    """Spots fx-mh1 (address 1) and fx-mh2 (17), RGB pars fx-par1 (33) and
    fx-par2 (36). pb-a: heads at full, colour preset Blue. pb-b: pars at full,
    red. pb-over (band 100, no fader): pars green. Page 1 holds pb-a, pb-b."""
    doc = busk_rig(spots=2, pars=2)
    doc["groups"] += [
        group("g-heads", 1, "fx-mh1", "fx-mh2"),
        group("g-pars", 2, "fx-par1", "fx-par2"),
    ]
    doc["presets"].append(
        preset("pr-blue", 1, "color", preset_value("color", {"r": 0, "g": 0, "b": 1}))
    )
    heads, pars = in_group("g-heads"), in_group("g-pars")
    look(
        doc,
        "pb-a",
        1,
        entry(heads, "intensity", literal(1.0)),
        entry(heads, "color", preset_source("pr-blue")),
        buttons=("toggle", "flash", "release", "select"),
    )
    look(
        doc,
        "pb-b",
        2,
        entry(pars, "intensity", literal(1.0)),
        entry(pars, "color", literal({"r": 1, "g": 0, "b": 0})),
    )
    look(
        doc,
        "pb-over",
        3,
        entry(pars, "color", literal({"r": 0, "g": 1, "b": 0})),
        priority=100,
        fader="none",
    )
    doc["pages"].append(page("page-1", 1, "pb-a", "pb-b"))
    return doc


@pytest.fixture
def live() -> Live:
    return Live(rig())


DROP_MH2: dict[str, Any] = {
    "type": "BATCH",
    "label": "drop MH 2",
    "commands": [
        {
            "type": "SET",
            "path": ["groups", {"id": "g-heads"}, "members"],
            "value": [{"fixtureId": "fx-mh1", "element": 0}],
        },
        {"type": "DELETE", "path": ["fixtures", {"id": "fx-mh2"}]},
    ],
}
"""Deleting MH 2 moves every later slot (the pars') to a new index."""


def rgbw(universe: bytes, address: int) -> tuple[int, ...]:
    """A spot's R G B W bytes (offsets 4–7)."""
    return tuple(universe[address + 3 : address + 7])


def rgb(universe: bytes, address: int) -> tuple[int, ...]:
    return tuple(universe[address - 1 : address + 2])


def fresh(live: Live, *performance: dict[str, Any]) -> tuple[bytes, ...]:
    """The frame of a fresh engine on the live session's show, after
    ``performance`` commands and with the live programmer restored."""
    engine = Engine(compile_show(live.session.show), FakeClock())
    for command in performance:
        engine.bus.submit(cast(Command, command))
    if live.session.programmer.values:
        Session(live.session.show, engine.bus).restore_programmer(live.session.programmer)
    engine.tick(0.0)
    assert engine.latest is not None
    return engine.latest.universes


def test_recording_into_a_live_cue(live: Live) -> None:
    live.do(fader("pb-a", 1.0))
    universe = bytes(live.tick() is not None and live.universe())
    assert rgbw(universe, 1) == rgbw(universe, 17) == BLUE
    live.do(sel("fx-mh1"), put("color", {"r": 1, "g": 0, "b": 0}))
    live.do(
        {"type": "RECORD_CUE", "cueListId": "cl-pb-a", "cueNumber": "1", "merge": "merge"}, CLEAR
    )
    live.tick()
    assert rgbw(live.universe(), 1) == (255, 0, 0, 0)  # from the cue, not the programmer
    assert rgbw(live.universe(), 17) == BLUE
    assert live.engine.latest is not None
    assert live.engine.latest.universes == fresh(live, fader("pb-a", 1.0))


def test_re_recording_a_preset_a_live_cue_references(live: Live) -> None:
    live.do(fader("pb-a", 1.0))
    live.tick()
    live.do(sel("fx-mh1", "fx-mh2"), put("color", {"r": 0, "g": 1, "b": 0}))
    live.do(
        {"type": "RECORD_PRESET", "pool": "color", "number": 1, "scope": "global", "merge": "merge"}
    )
    live.do(CLEAR)
    live.tick()
    assert rgbw(live.universe(), 1) == rgbw(live.universe(), 17) == (0, 255, 0, 0)
    cue = live.session.show["cueLists"][0]["cues"][0]
    assert cue["entries"][1]["value"] == {
        "kind": "preset",
        "presetId": "pr-blue",
    }  # still a reference
    assert live.engine.latest is not None
    assert live.engine.latest.universes == fresh(live, fader("pb-a", 1.0))


def test_moving_a_fixtures_patch(live: Live) -> None:
    live.do(fader("pb-b", 1.0))
    live.tick()
    assert rgb(live.universe(), 33) == RED
    live.do(
        {
            "type": "PATCH_FIXTURE",
            "fixtureId": "fx-par1",
            "patch": {"universeId": "u1", "address": 100},
        }
    )
    live.tick()
    assert rgb(live.universe(), 33) == (0, 0, 0)
    assert rgb(live.universe(), 100) == RED
    assert live.engine.latest is not None
    assert live.engine.latest.universes == fresh(live, fader("pb-b", 1.0))


def test_a_slot_remap_keeps_programmer_order(live: Live) -> None:
    live.do(fader("pb-b", 1.0), sel("fx-par2"), put("color", {"r": 0, "g": 0, "b": 1}))
    live.do(trigger("pb-over"))  # band 100, newer than the programmer's touch
    live.tick()
    assert rgb(live.universe(), 36) == GREEN
    # Deleting MH 2 moves every later slot to a new index.
    live.do(DROP_MH2)
    live.tick()
    assert rgb(live.universe(), 36) == GREEN  # pb-over is still the newer one
    assert rgbw(live.universe(), 17) == (0, 0, 0, 0)  # MH 2 is gone
    live.do(put("color", {"r": 0, "g": 0, "b": 1}))  # touching again puts it on top
    live.tick()
    assert rgb(live.universe(), 36) == (0, 0, 255)
    assert live.engine.stats.installErrors == 0


def test_a_slot_remap_carries_a_running_programmer_fade(live: Live) -> None:
    live.do(fader("pb-b", 1.0))  # pars red
    live.do({"type": "PROGRAMMER_FADE", "time": 2.0}, sel("fx-par2"))
    live.do(put("color", {"r": 0, "g": 0, "b": 1}))
    live.tick()  # the fade to blue starts
    live.tick(1.0)
    assert live.lanes("fx-par2", "color") == pytest.approx([0.5, 0.0, 0.5])
    live.do(DROP_MH2)  # the fade's lanes move; the frame keeps the same value
    live.tick(0.5)
    assert live.lanes("fx-par2", "color") == pytest.approx([0.25, 0.0, 0.75], abs=0.01)
    live.tick(1.0)
    assert live.lanes("fx-par2", "color") == [0.0, 0.0, 1.0]
    assert live.lanes("fx-par1", "color") == [1.0, 0.0, 0.0]
    assert live.engine.stats.installErrors == 0


def test_deleting_a_running_playback(live: Live) -> None:
    live.do(fader("pb-b", 1.0))
    live.tick()
    live.do(
        {
            "type": "BATCH",
            "label": "drop pb-b",
            "commands": [
                {"type": "ASSIGN_PLAYBACK", "pageId": "page-1", "slot": 1, "playbackId": None},
                {"type": "DELETE", "path": ["playbacks", {"id": "pb-b"}]},
            ],
        }
    )
    live.tick()
    assert rgb(live.universe(), 33) == rgb(live.universe(), 36) == (0, 0, 0)
    assert "pb-b" not in live.engine.runtime.playbacks.runtimes
    result = live.session.submit(cast(Command, fader("pb-b", 1.0)))
    assert (result.ok, result.message) == (False, "unknown playback 'pb-b'")
    assert live.engine.latest is not None
    assert live.engine.latest.universes == fresh(live)


def test_emptying_a_running_playbacks_cue_list_stops_it(live: Live) -> None:
    live.do(fader("pb-b", 1.0))
    live.tick()
    live.do({"type": "DELETE", "path": ["cueLists", {"id": "cl-pb-b"}, "cues", {"id": "c-pb-b"}]})
    live.tick()
    assert live.engine.runtime.playbacks.runtimes["pb-b"].state == "idle"
    assert rgb(live.universe(), 33) == (0, 0, 0)


def test_new_universes_and_routes_reconcile_output_and_input(receiver: Receiver) -> None:
    doc = rig()
    doc["universes"][0]["number"] = 2
    doc["output"]["routes"].append(
        {
            "id": "r1",
            "universeId": "u1",
            "enabled": True,
            "protocol": "sacn",
            "universe": 2,
            "priority": 100,
            "destination": {"kind": "unicast", "host": "127.0.0.1"},
        }
    )
    live = Live(doc)
    compiled = live.engine.compiled
    sequences = Sequences()
    routes, _ = build_routes(compiled.output, compiled.universes, sequences)
    output = OutputScheduler(
        live.engine, routes, FakeClock(), layout=compiled.layout, sequences=sequences
    )
    live.do(fader("pb-a", 1.0), fader("pb-b", 1.0))
    live.tick()
    output.service(0.0)
    first = receiver.receive()
    assert (first.universe, rgbw(first.data, 1), rgb(first.data, 33)) == (2, BLUE, RED)

    # Universe 1 arrives before universe 2: rows reorder. Par 1 moves onto it, with a route.
    live.do(
        {
            "type": "BATCH",
            "label": "front",
            "commands": [
                {
                    "type": "ADD",
                    "path": ["universes"],
                    "value": {"id": "u-front", "name": "Front", "number": 1},
                },
                {
                    "type": "ADD",
                    "path": ["output", "routes"],
                    "value": {
                        "id": "r2",
                        "universeId": "u-front",
                        "enabled": True,
                        "protocol": "sacn",
                        "universe": 7,
                        "priority": 100,
                        "destination": {"kind": "unicast", "host": "127.0.0.1"},
                    },
                },
                {
                    "type": "PATCH_FIXTURE",
                    "fixtureId": "fx-par1",
                    "patch": {"universeId": "u-front", "address": 1},
                },
                {
                    "type": "ADD",
                    "path": ["surfaces"],
                    "value": {
                        "id": "s-new",
                        "name": "pad",
                        "kind": "midi",
                        "match": {"deviceName": "pad"},
                        "faderPickup": "jump",
                    },
                },
                {
                    "type": "ADD",
                    "path": ["bindings"],
                    "value": {
                        "id": "b-new",
                        "surfaceId": "s-new",
                        "input": {"kind": "midiCC", "channel": 1, "cc": 9},
                        "action": {"kind": "playbackFader", "slot": 0},
                    },
                },
                {
                    "type": "ADD",
                    "path": ["bindings"],
                    "value": {
                        "id": "b-select",
                        "surfaceId": "s-new",
                        "input": {"kind": "midiNote", "channel": 1, "note": 9},
                        "action": {"kind": "playbackButton", "slot": 0, "button": 3},
                    },
                },
            ],
        }
    )
    live.tick()
    receiver.drain()
    output.service(1.0)
    packets = {p.universe: p for p in receiver.drain()}
    assert sorted(packets) == [2, 7]
    assert rgb(packets[7].data, 1) == RED  # par 1, now on universe "Front"
    assert rgb(packets[2].data, 33) == (0, 0, 0)  # …and gone from its old address
    assert rgbw(packets[2].data, 1) == BLUE  # universe 2's route still sends universe 2
    notices = []
    while not output.notices.empty():
        notices.append(output.notices.get().text)
    assert notices == ["sACN r2: U1 Front → universe 7, unicast 127.0.0.1, priority 100"]
    assert discovered(output) == [2, 7]  # universe discovery lists the new route

    # Removing a route terminates its stream.
    live.do({"type": "DELETE", "path": ["output", "routes", {"id": "r1"}]})
    live.tick()
    output.service(2.0)
    closing = [p for p in receiver.drain() if p.universe == 2]
    assert [p.terminated for p in closing] == [True, True, True]
    assert output.notices.get().text == "sACN r1: closed"
    assert discovered(output) == [7]

    # Input follows the live bindings: the new fader drives pb-a, the new
    # select button selects its targets through the session.
    session = live.session
    resolver = BindingResolver(
        session.show, compiled, InputSink(session), live=lambda: live.engine.bus.compiled
    )
    resolver.handle(
        InputEvent(
            SurfaceId("s-new"), cast(InputAddress, {"kind": "midiCC", "channel": 1, "cc": 9}), 0.5
        )
    )
    resolver.handle(
        InputEvent(
            SurfaceId("s-new"),
            cast(InputAddress, {"kind": "midiNote", "channel": 1, "note": 9}),
            1.0,
        )
    )
    session.stop()
    commands = [item["command"] for item in live.engine.bus.drain() if isinstance(item, dict)]
    assert commands == [{"type": "SET_FADER", "slot": 0, "level": 0.5}]
    assert session.programmer.selection == (
        {"fixtureId": "fx-mh1", "element": 0},
        {"fixtureId": "fx-mh2", "element": 0},
    )
    output.close()


def art_net_route(ident: str) -> dict[str, Any]:
    return {
        "id": ident,
        "universeId": "u1",
        "enabled": True,
        "protocol": "artnet",
        "portAddress": {"net": 0, "subNet": 0, "universe": 3},
        "destination": {"kind": "unicast", "host": "127.0.0.1"},
    }


def discovered(output: OutputScheduler) -> list[int]:
    """The sACN universes the scheduler's universe discovery lists."""
    [packet] = output._discovery.packets
    return [int.from_bytes(packet[k : k + 2]) for k in range(120, len(packet), 2)]


def test_art_net_routes_follow_live_edits(artnet_receiver: ArtNetReceiver) -> None:
    live = Live(rig())
    compiled = live.engine.compiled
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other:  # another Art-Net program
        other.bind(("", 0))
        network = ArtNetNetwork(port=other.getsockname()[1])
        routes, _ = build_routes(compiled.output, compiled.universes, artnet=network)
        output = OutputScheduler(
            live.engine, routes, FakeClock(), layout=compiled.layout, artnet=network
        )
        live.do(fader("pb-a", 1.0))
        live.do({"type": "ADD", "path": ["output", "routes"], "value": art_net_route("r-a")})
        live.tick()
        output.service(0.0)
    packet = artnet_receiver.receive()
    assert (packet.address, packet.sequence, rgbw(packet.data, 1)) == ("0.0.3", 1, BLUE)
    stage = live.engine.compiled.universes[0]
    described = f"U{stage.number} {stage.name} → port address 0.0.3, unicast 127.0.0.1"
    assert output.notices.get().text == f"Art-Net r-a: {described}"
    # Nothing about the taken port: unicast routes never ask for it.

    # A second route on the Port-Address joins the run's network: one socket, one count.
    live.do({"type": "ADD", "path": ["output", "routes"], "value": art_net_route("r-b")})
    live.tick()
    output.service(0.1)
    packet = artnet_receiver.receive()
    assert (packet.address, packet.sequence) == ("0.0.3", 2)
    assert set(artnet_receiver.sources) == {("127.0.0.1", network.local_port)}
    assert output.notices.get().text == f"Art-Net r-b: {described}"

    for ident in ("r-a", "r-b"):
        live.do({"type": "DELETE", "path": ["output", "routes", {"id": ident}]})
        live.tick()
        output.service(1.0)
        assert output.notices.get().text == f"Art-Net {ident}: closed"
    assert network.local_port is None  # the last Art-Net route took the socket with it
    assert artnet_receiver.drain(0.05) == []  # Art-Net has no stream end


def test_engine_rate_changes_with_a_live_edit(live: Live) -> None:
    live.do({"type": "SET", "path": ["output", "engineHz"], "value": 50})
    live.tick()
    assert live.engine.compiled.engineHz == 50


def test_a_values_base_frame_follows_a_remap() -> None:
    doc = rig()
    compiled = compile_doc(doc)
    base = compiled.slots.defaultFrame.copy()
    slot = compiled.slots.find({"fixtureId": "fx-par2", "element": 0}, "color")  # type: ignore[typeddict-item]
    assert slot is not None
    base[slot.lanes] = (0.0, 0.0, 1.0)
    intensity = compiled.slots.find({"fixtureId": "fx-par2", "element": 0}, "intensity")  # type: ignore[typeddict-item]
    assert intensity is not None
    base[intensity.lanes] = 1.0
    live = Live(doc)
    live.engine = Engine(compiled, live.clock, base)
    live.session = Session(live.session.show, live.engine.bus, compiled=compiled)
    live.tick()
    assert rgb(live.universe(), 36) == (0, 0, 255)
    live.do(
        {
            "type": "BATCH",
            "label": "drop MH 1",
            "commands": [
                {
                    "type": "SET",
                    "path": ["groups", {"id": "g-heads"}, "members"],
                    "value": [{"fixtureId": "fx-mh2", "element": 0}],
                },
                {"type": "DELETE", "path": ["fixtures", {"id": "fx-mh1"}]},
            ],
        }
    )
    live.tick()
    assert rgb(live.universe(), 36) == (0, 0, 255)  # the values frame moved with its slots


# --------------------------------------------- Phase 4: live edits fade (decision 14)


def at(fixture: str, attribute: str, value: Any) -> dict[str, Any]:
    return entry(targets(fixture), attribute, literal(value))


def song_cue(number: int, *entries: dict[str, Any]) -> dict[str, Any]:
    """Cue ``c<number>``, fading in and out over 2 s, triggered by GO."""
    return cue(f"c{number}", *entries, number=str(number), fade_in=2.0, fade_out=2.0)


def song_rig() -> dict[str, Any]:
    """Three spots and the 120-BPM speed master m-speed. The tracking list
    cl-song on pb-song (band 50, no fader): 1 "MH 1 at 0.5, pan 0", 2 "MH 1
    pan 90", 3 "MH 3 at full". pb-bump (band 50, no fader): MH 1 pan 45."""
    doc = busk_rig(spots=3)
    doc["masters"].append(speed_master())
    songs = cue_list(
        "cl-song",
        1,
        song_cue(1, at("fx-mh1", "intensity", 0.5), at("fx-mh1", "pan", 0)),
        song_cue(2, at("fx-mh1", "pan", 90)),
        song_cue(3, at("fx-mh3", "intensity", 1.0)),
    )
    songs["tracking"] = True
    doc["cueLists"] += [songs, cue_list("cl-bump", 2, cue("c-bump", at("fx-mh1", "pan", 45)))]
    doc["playbacks"] += [
        playback("pb-song", 1, "cl-song", fader="none"),
        playback("pb-bump", 2, "cl-bump", fader="none"),
    ]
    return doc


def chase_rig() -> dict[str, Any]:
    """Three spots; cl-chase (1 Hz, forward, no crossfade) on pb-chase steps
    MH 1, MH 2, MH 3 at full."""
    doc = busk_rig(spots=3)
    steps = [cue(f"s{k}", at(f"fx-mh{k}", "intensity", 1.0), number=str(k)) for k in (1, 2, 3)]
    chase = cue_list("cl-chase", 1, *steps)
    chase.update(
        mode="chase",
        chase={"rate": {"kind": "hz", "value": 1.0}, "direction": "forward", "crossfade": 0.0},
    )
    doc["cueLists"].append(chase)
    doc["playbacks"].append(playback("pb-chase", 1, "cl-chase", fader="none"))
    return doc


def edit(path: list[Any], value: Any) -> dict[str, Any]:
    return {"type": "SET", "path": path, "value": value}


def song(*rest: Any) -> list[Any]:
    """An edit path into cl-song's cues."""
    return ["cueLists", {"id": "cl-song"}, "cues", *rest]


def chase(*rest: Any) -> list[Any]:
    """An edit path into cl-chase."""
    return ["cueLists", {"id": "cl-chase"}, *rest]


def goto(playback_id: str, number: str) -> dict[str, Any]:
    return {"type": "GOTO", "playbackId": playback_id, "cueNumber": number}


def runtime(live: Live, playback_id: str) -> PlaybackRuntime:
    return live.engine.runtime.playbacks.runtimes[playback_id]


def until(live: Live, time: float) -> None:
    """Tick at absolute engine time ``time``."""
    live.tick(time - live.now)


def test_a_recorded_change_fades_with_the_cues_timing_and_keeps_the_stack_order() -> None:
    live = Live(song_rig())
    live.do(trigger("pb-song"))
    live.tick()
    live.tick(2.5)
    live.do(trigger("pb-bump"))  # newer: its pan sits on top
    live.tick()
    assert (live.lanes("fx-mh1", "intensity"), live.lanes("fx-mh1", "pan")) == ([0.5], [45.0])
    record = {"type": "RECORD_CUE", "cueListId": "cl-song", "cueNumber": "1", "merge": "merge"}
    live.do(sel("fx-mh1"), put("intensity", 1.0), put("pan", 20), record, CLEAR)
    seq = live.engine.runtime.playbacks.seqCounter
    live.tick()  # the edit starts fading with cue 1's 2-s timing
    assert live.engine.runtime.playbacks.seqCounter == seq + 2  # the two touches; the edit none
    assert (live.lanes("fx-mh1", "intensity"), live.lanes("fx-mh1", "pan")) == ([0.5], [45.0])
    live.tick(1.0)
    assert live.lanes("fx-mh1", "intensity") == pytest.approx([0.75])
    assert live.lanes("fx-mh1", "pan") == [45.0]  # the song's pan fades under the bump
    live.tick(1.5)
    assert (live.lanes("fx-mh1", "intensity"), live.lanes("fx-mh1", "pan")) == ([1.0], [45.0])
    live.do({"type": "RELEASE_PLAYBACK", "playbackId": "pb-bump", "time": 0.0})
    live.tick()
    assert live.lanes("fx-mh1", "pan") == [20.0]  # the recorded value was there all along


def test_a_slot_remap_carries_a_running_cue_fade() -> None:
    live = Live(song_rig())
    live.do(goto("pb-song", "3"))
    live.tick()
    live.tick(1.0)
    assert live.lanes("fx-mh3", "intensity") == pytest.approx([0.5])
    live.do({"type": "DELETE", "path": ["fixtures", {"id": "fx-mh2"}]})  # moves MH 3's slots
    live.tick(0.5)
    assert live.lanes("fx-mh3", "intensity") == pytest.approx([0.75], abs=0.01)
    live.tick(1.0)
    assert live.lanes("fx-mh3", "intensity") == [1.0]
    assert (live.lanes("fx-mh1", "intensity"), live.lanes("fx-mh1", "pan")) == ([0.5], [90.0])
    assert live.engine.stats.installErrors == 0


def test_deleting_the_current_cue_moves_to_the_cue_after_its_number() -> None:
    live = Live(song_rig())
    live.do({"type": "ADD", "path": song(), "value": song_cue(4, at("fx-mh3", "pan", 30))})
    live.do(goto("pb-song", "2"))
    live.tick()
    live.tick(2.5)
    pb = runtime(live, "pb-song")
    drop = [{"type": "DELETE", "path": song({"id": c})} for c in ("c1", "c2")]
    live.do({"type": "BATCH", "label": "drop 1 and 2", "commands": drop})
    live.tick()  # cue 3, the first number after 2 (not cue 4, at cue 2's old index)
    assert pb.current.number == "3"
    assert live.lanes("fx-mh1", "pan") == [90.0]  # cue 3 fades with its own timing
    live.tick(1.0)
    assert live.lanes("fx-mh1", "pan") == pytest.approx([45.0])  # tracked from nothing now
    assert live.lanes("fx-mh3", "intensity") == pytest.approx([0.5])
    live.tick(1.5)
    assert (live.lanes("fx-mh1", "pan"), live.lanes("fx-mh3", "intensity")) == ([0.0], [1.0])
    live.do(goto("pb-song", "4"))
    live.tick()
    live.do({"type": "DELETE", "path": song({"id": "c4"})})  # no cue after it: the last cue
    live.tick()
    assert pb.current.number == "3"


def test_editing_the_next_cues_trigger_rederives_the_auto_go() -> None:
    live = Live(song_rig())
    live.do(trigger("pb-song"))
    live.tick()
    t0, pb = live.now, runtime(live, "pb-song")
    assert pb.auto is None  # cue 2 waits for GO
    live.do(edit(song({"id": "c2"}, "trigger"), {"kind": "wait", "delay": 3.0}))
    live.tick()
    assert pb.auto == pytest.approx(t0 + 3.0)
    live.do(edit(song({"id": "c2"}, "trigger"), {"kind": "follow", "delay": 0.5}))
    live.tick()
    assert pb.auto == pytest.approx(t0 + 2.5)  # cue 1's fades complete at t0 + 2
    live.do(edit(song({"id": "c2"}, "trigger"), {"kind": "go"}))
    live.tick()
    assert pb.auto is None
    until(live, t0 + 5.0)
    live.do(edit(song({"id": "c2"}, "trigger"), {"kind": "wait", "delay": 1.0}))
    live.tick()  # overdue since t0 + 1: it fires at the install
    assert (pb.current.number, pb.started) == ("2", live.now)
    live.do({"type": "BACK", "playbackId": "pb-song"})
    live.tick()
    live.do(edit(song({"id": "c2"}, "trigger"), {"kind": "wait", "delay": 2.0}))
    live.tick()
    assert (pb.current.number, pb.auto) == ("1", None)  # BACK cancelled it for good


def test_editing_the_goto_cue_retargets_goto_buttons() -> None:
    """Phase 6: a ``goto`` button follows ``gotoCue`` and the cue numbers
    as edited; a number that names no cue makes it do nothing."""
    doc = song_rig()
    next(p for p in doc["playbacks"] if p["id"] == "pb-song")["buttons"] = ["goto"]
    live = Live(doc)
    press = {"type": "PLAYBACK_BUTTON", "playbackId": "pb-song", "button": 0, "down": True}
    goto_cue = ["playbacks", {"id": "pb-song"}, "gotoCue"]
    pb = runtime(live, "pb-song")
    live.do(press)
    live.tick()
    assert pb.state == "idle"  # no gotoCue yet
    live.do(edit(goto_cue, "3"))
    live.tick()
    live.do(press)
    live.tick()
    assert (pb.state, pb.current.number) == ("active", "3")
    live.do(edit(goto_cue, "2"), press)
    live.tick()
    assert pb.current.number == "2"
    live.do(goto("pb-song", "1"), edit(song({"id": "c2"}, "number"), "2.5"))
    live.tick()
    live.do(press)  # gotoCue 2 names no cue now
    live.tick()
    assert pb.current.number == "1"
    live.do(edit(goto_cue, "2.5"), press)
    live.tick()
    assert pb.current.number == "2.5"
    assert live.engine.stats.commandErrors == 0


def test_an_edit_that_leaves_a_cue_list_alone_does_not_retarget_its_playback() -> None:
    """The memoised compile reuses an unchanged list, so its running fades
    carry on as they are: no retarget (the engine thread would otherwise run
    one per running playback on every edit)."""
    live = Live(song_rig())
    live.do(trigger("pb-song"), trigger("pb-bump"))
    live.tick()
    live.tick(1.0)
    song_set = runtime(live, "pb-song").contributions
    bump_set = runtime(live, "pb-bump").contributions
    versions = song_set.version, bump_set.version
    live.do(edit(["cueLists", {"id": "cl-bump"}, "name"], "Bump"))
    live.tick(0.5)
    assert song_set.version == versions[0]
    assert bump_set.version > versions[1]  # its list was recompiled: retargeted, a no-op
    assert live.lanes("fx-mh1", "intensity") == pytest.approx([0.375])  # cue 1's 2-s fade
    live.tick(0.5)
    assert live.lanes("fx-mh1", "intensity") == [0.5]
    assert live.engine.stats.installErrors == 0


def test_a_releasing_playback_keeps_its_frozen_slots_through_an_edit() -> None:
    live = Live(song_rig())
    live.do(trigger("pb-song"))
    live.tick()
    live.tick(2.5)
    live.do({"type": "RELEASE_PLAYBACK", "playbackId": "pb-song", "time": 2.0})
    live.tick()
    live.tick(1.0)
    assert live.lanes("fx-mh1", "intensity") == pytest.approx([0.25])
    live.do(edit(song({"id": "c1"}, "entries"), [at("fx-mh1", "intensity", 1.0)]))
    live.tick()
    until(live, live.now + 0.49)  # 1.5 s into the release
    assert live.lanes("fx-mh1", "intensity") == pytest.approx([0.125])  # from the frozen 0.5
    live.tick(1.0)
    assert (live.lanes("fx-mh1", "intensity"), runtime(live, "pb-song").state) == ([0.0], "idle")


def test_a_chase_rate_edit_keeps_its_position() -> None:
    live = Live(chase_rig())
    live.do(trigger("pb-chase"))
    live.tick()
    t0, pb = live.now, runtime(live, "pb-chase")
    until(live, t0 + 0.5)
    live.do(edit(chase("chase", "rate", "value"), 2.0))
    live.tick()  # half a step done at 1 Hz; the other half takes 0.25 s at 2 Hz
    until(live, t0 + 0.74)
    assert pb.current.number == "1"
    until(live, t0 + 0.77)
    assert pb.current.number == "2"
    assert live.lanes("fx-mh2", "intensity") == [1.0]
    until(live, t0 + 1.27)
    assert pb.current.number == "3"


def test_chase_edits_turn_it_count_its_cues_and_switch_modes() -> None:
    live = Live(chase_rig())
    live.do(trigger("pb-chase"))
    live.tick()
    t0, pb = live.now, runtime(live, "pb-chase")
    until(live, t0 + 1.5)
    assert pb.current.number == "2"
    live.do(edit(chase("chase", "direction"), "reverse"))
    live.tick()  # edits apply at the next tick
    until(live, t0 + 2.5)
    assert pb.current.number == "1"  # stepped back
    live.do(edit(chase("mode"), "sequence"))  # a sequence now: it holds its cue
    live.tick()
    until(live, t0 + 4.0)
    assert (pb.chase, pb.current.number, pb.auto) == (None, "1", None)
    live.do(edit(chase("mode"), "chase"))  # a chase again: a new clock from the install
    live.tick()
    t1 = live.now
    until(live, t1 + 0.9)
    assert pb.current.number == "1"
    until(live, t1 + 1.1)
    assert pb.current.number == "3"  # reverse wraps from the first cue
    live.do({"type": "DELETE", "path": chase("cues", {"id": "s3"})})  # the current cue
    live.tick()
    assert pb.current.number == "2"  # the last cue
    assert pb.chase is not None
    assert pb.chase.order.count == 2


def test_a_speed_masters_tempo_survives_an_edit() -> None:
    live = Live(song_rig())
    live.do({"type": "SET_BPM", "masterId": "m-speed", "bpm": 150.0})
    live.tick()
    beats = live.engine.runtime.speed["m-speed"].beats(live.now)
    live.do(edit(["masters", {"id": "m-speed"}, "name"], "Tempo"))
    live.tick(1.0)
    master = live.engine.runtime.speed["m-speed"]
    assert master.bpm == 150.0
    assert master.beats(live.now) == pytest.approx(beats + 2.5)


# --------------------------------------- Phase 5: effects through a live edit (§5.10)


def fx_rig() -> dict[str, Any]:
    """Three spots, the 120-BPM speed master m-speed (at its ×1 step) and the
    size master m-size. pb-fx (band 50, no fader) plays cl-fx, whose cue 1
    fades in over 1 s and out over 4 s: MH 3 at full under e-pulse (a 1-Hz
    sine ``multiply`` of size 0.4), and e-saw (a 1-Hz absolute ``sawUp``) on
    MH 1's intensity, so MH 1 shows the saw's phase. MH 2 holds nothing."""
    doc = busk_rig(spots=3)
    doc["masters"] += [speed_master(), size_master()]
    doc["effects"] = [
        effect_template("t-pulse", effect_layer("intensity", "sine", "multiply")),
        effect_template("t-saw", effect_layer("intensity", "sawUp")),
    ]
    fx = cue("c1", at("fx-mh3", "intensity", 1.0), fade_in=1.0, fade_out=4.0)
    fx["effects"] = [
        effect_instance("e-pulse", "t-pulse", targets("fx-mh3"), size=0.4),
        effect_instance("e-saw", "t-saw", targets("fx-mh1")),
    ]
    doc["cueLists"].append(cue_list("cl-fx", 1, fx))
    doc["playbacks"].append(playback("pb-fx", 1, "cl-fx", fader="none"))
    return doc


def fx(*rest: Any) -> list[Any]:
    """An edit path into cl-fx's cue 1."""
    return ["cueLists", {"id": "cl-fx"}, "cues", {"id": "c1"}, *rest]


def sine(p: float) -> float:
    return 0.5 - 0.5 * math.cos(2.0 * math.pi * p)


def pulse(size: float, w: float) -> float:
    """MH 3's level under a full-presence pulse of ``size`` at wave value ``w``."""
    return 1.0 - size * (1.0 - w)


def saw(position: float) -> float:
    return position - math.floor(position)


def fx_live() -> tuple[Live, float, PlaybackRuntime]:
    """:func:`fx_rig` with pb-fx triggered: the live harness, the time t0 the
    effects started (P = t − t0) and pb-fx's runtime."""
    live = Live(fx_rig())
    live.do(trigger("pb-fx"))
    live.tick()
    return live, live.now, runtime(live, "pb-fx")


def test_an_edited_size_cross_fades_on_the_same_clock() -> None:
    live, t0, pb = fx_live()
    running = pb.bank.runtimes["e-pulse"]
    clock, seq = running.clock, running.seq
    until(live, t0 + 1.3)
    assert live.lanes("fx-mh3", "intensity") == pytest.approx([pulse(0.4, sine(1.3))])
    live.do(edit(fx("effects", {"id": "e-pulse"}, "size"), 0.8))
    until(live, t0 + 1.4)  # installed: size 0.8 fades in with cue 1's 1-s in timing
    until(live, t0 + 1.9)  # half-way: an exact morph of the depth
    assert live.lanes("fx-mh3", "intensity") == pytest.approx([pulse(0.6, sine(1.9))])
    until(live, t0 + 2.6)
    assert live.lanes("fx-mh3", "intensity") == pytest.approx([pulse(0.8, sine(2.6))])
    assert pb.bank.runtimes["e-pulse"] is running
    assert (running.clock, running.seq, len(running.versions)) == (clock, seq, 1)
    assert live.engine.runtime.playbacks.seqCounter == seq  # the edit took no number


def test_an_edited_template_cross_fades() -> None:
    live, t0, _ = fx_live()
    until(live, t0 + 1.3)
    layers = [effect_layer("intensity", "sawUp", "multiply")]
    live.do(edit(["effects", {"id": "t-pulse"}, "layers"], layers))
    until(live, t0 + 1.4)
    until(live, t0 + 1.9)  # the two waves' amounts mix half and half
    mixed = (sine(1.9) + saw(1.9)) / 2.0
    assert live.lanes("fx-mh3", "intensity") == pytest.approx([pulse(0.4, mixed)])
    until(live, t0 + 2.6)
    assert live.lanes("fx-mh3", "intensity") == pytest.approx([pulse(0.4, saw(2.6))])


def test_an_edited_rate_keeps_the_position_continuous() -> None:
    live, t0, _ = fx_live()
    until(live, t0 + 1.25)
    assert live.lanes("fx-mh1", "intensity") == pytest.approx([0.25])
    live.do(edit(fx("effects", {"id": "e-saw"}, "rate", "value"), 2.0))
    until(live, t0 + 1.3)  # installed at P = 1.3, from where it runs at 2 Hz
    assert live.lanes("fx-mh1", "intensity") == pytest.approx([0.3])
    until(live, t0 + 1.5)  # both versions share the clock: no step while they cross
    assert live.lanes("fx-mh1", "intensity") == pytest.approx([0.7])
    until(live, t0 + 2.6)
    assert live.lanes("fx-mh1", "intensity") == pytest.approx([saw(1.3 + 2.0 * 1.3)])


def test_an_unchanged_instance_is_not_touched() -> None:
    live, t0, pb = fx_live()
    until(live, t0 + 1.3)
    running = pb.bank.runtimes["e-pulse"]
    (version,) = running.versions
    presence, clock = version.presence, running.clock
    lists = pb.playback.cueList
    live.do(edit(fx("name"), "Pulse"))  # recompiles the list
    live.do(edit(fx("effects", {"id": "e-saw"}, "size"), 0.5))  # changes its neighbour
    until(live, t0 + 1.4)
    assert pb.playback.cueList is not lists
    assert pb.bank.runtimes["e-pulse"] is running
    assert running.versions == [version]
    assert (version.presence, running.clock) == (presence, clock)
    assert len(pb.bank.runtimes["e-saw"].versions) == 2  # the edited one cross-fades
    until(live, t0 + 1.9)
    assert live.lanes("fx-mh3", "intensity") == pytest.approx([pulse(0.4, sine(1.9))])


def test_a_patch_move_remaps_a_running_effect_mid_change() -> None:
    live, t0, _ = fx_live()
    until(live, t0 + 1.3)
    live.do(edit(fx("effects", {"id": "e-pulse"}, "size"), 0.8))
    until(live, t0 + 1.4)
    live.do({"type": "DELETE", "path": ["fixtures", {"id": "fx-mh2"}]})  # moves MH 3's slots
    until(live, t0 + 1.65)
    assert live.lanes("fx-mh3", "intensity") == pytest.approx([pulse(0.5, sine(1.65))])
    until(live, t0 + 1.9)
    assert live.lanes("fx-mh3", "intensity") == pytest.approx([pulse(0.6, sine(1.9))])
    until(live, t0 + 2.6)
    assert live.lanes("fx-mh3", "intensity") == pytest.approx([pulse(0.8, sine(2.6))])
    assert live.lanes("fx-mh1", "intensity") == pytest.approx([saw(2.6)])
    assert live.engine.stats.installErrors == 0


def test_deleting_an_effect_from_the_current_cue_fades_it_out_with_the_out_timing() -> None:
    live, t0, pb = fx_live()
    until(live, t0 + 1.2)
    live.do({"type": "DELETE", "path": fx("effects", {"id": "e-saw"})})
    until(live, t0 + 1.3)  # installed: it fades out over cue 1's 4 s, still moving
    until(live, t0 + 2.3)
    assert live.lanes("fx-mh1", "intensity") == pytest.approx([0.75 * saw(2.3)])
    until(live, t0 + 4.3)
    assert live.lanes("fx-mh1", "intensity") == pytest.approx([0.25 * saw(4.3)])
    until(live, t0 + 5.31)
    assert live.lanes("fx-mh1", "intensity") == [0.0]
    assert list(pb.bank.runtimes) == ["e-pulse"]


@pytest.mark.parametrize("bank", ["main", "flash"])
def test_a_speed_master_edit_keeps_bpm_effects_on_the_grid(bank: str) -> None:
    """At ×1, 120 BPM, the saw's position is the beat count B. The edited
    steps put the master at ×2: the clock moves to the grid position nearest
    where it is and nudges the difference away over one beat, so it is
    continuous and then on the grid. A held flash's bank does the same."""
    live = Live(fx_rig())
    beat = {"rate": {"kind": "bpm", "masterId": "m-speed", "multiplier": 1.0}}
    live.do(edit(fx("effects", {"id": "e-saw"}, "rate"), beat["rate"]))
    live.tick()  # the speed master starts counting
    t0 = live.now
    if bank == "main":
        live.do(trigger("pb-fx"))
    else:
        live.do({"type": "FLASH", "playbackId": "pb-fx", "down": True})
    live.tick()  # at B = 0.02: the clock starts on the grid, P = B
    master = live.engine.runtime.speed["m-speed"]
    until(live, t0 + 1.1)
    assert live.lanes("fx-mh1", "intensity") == pytest.approx([saw(master.beats(live.now))])
    live.do(edit(["masters", {"id": "m-speed"}, "multiplierSteps"], [0.5, 1, 2, 4, 8]))
    until(live, t0 + 1.2)  # installed at P = B = 2.4; the nearest ×2 grid position is 2.8
    assert master.multiplier == 2.0
    assert live.lanes("fx-mh1", "intensity") == pytest.approx([0.4])
    until(live, t0 + 1.45)  # half a beat on: 2·0.5 more, and half the 0.4 nudge closed
    assert live.lanes("fx-mh1", "intensity") == pytest.approx([saw(2.4 + 1.0 + 0.2)])
    until(live, t0 + 1.7)  # one beat on: exactly on the ×2 grid
    beats = master.beats(live.now)
    assert live.lanes("fx-mh1", "intensity") == pytest.approx([saw(2.0 * beats)])


def test_a_running_flash_bank_takes_an_edit_at_once() -> None:
    live = Live(fx_rig())
    live.do({"type": "FLASH", "playbackId": "pb-fx", "down": True})  # pb-fx stays idle
    live.tick()
    t0, pb = live.now, runtime(live, "pb-fx")
    seq = pb.flashSeq
    until(live, t0 + 1.3)
    assert live.lanes("fx-mh3", "intensity") == pytest.approx([pulse(0.4, sine(1.3))])
    live.do(edit(fx("effects", {"id": "e-pulse"}, "size"), 0.8))
    live.do({"type": "DELETE", "path": fx("effects", {"id": "e-saw"})})
    added = effect_instance("e-new", "t-saw", targets("fx-mh2"))
    live.do({"type": "ADD", "path": fx("effects"), "value": added})
    until(live, t0 + 1.4)
    assert live.lanes("fx-mh3", "intensity") == pytest.approx([pulse(0.8, sine(1.4))])
    assert live.lanes("fx-mh1", "intensity") == [0.0]
    assert live.lanes("fx-mh2", "intensity") == [0.0]  # a new clock, at position 0
    until(live, t0 + 1.65)
    assert live.lanes("fx-mh2", "intensity") == pytest.approx([0.25])
    assert {key: rt.seq for key, rt in pb.flashBank.runtimes.items()} == {
        "e-pulse": seq,
        "e-new": seq,
    }
    assert pb.bank.runtimes == {}
    live.do(trigger("pb-fx"))  # main's bank takes over under the held flash, and
    live.do(edit(fx("effects", {"id": "e-pulse"}, "size"), 0.6))  # an edit starts no flash bank
    live.tick()
    assert (list(pb.bank.runtimes), pb.flashBank.runtimes) == (["e-pulse", "e-new"], {})


def test_size_levels_are_carried_by_id_and_new_ones_start_at_their_initial_level() -> None:
    live, _, _ = fx_live()
    live.do({"type": "SET_MASTER", "masterId": "m-size", "level": 0.5})
    live.tick()
    live.do({"type": "ADD", "path": ["masters"], "value": size_master("m-new", initial=0.3)})
    live.tick()
    assert live.engine.runtime.sizeLevels == {"m-size": 0.5, "m-new": 0.3}
