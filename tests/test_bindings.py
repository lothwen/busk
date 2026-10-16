"""Bindings: input events → commands, for every action and button function."""

from __future__ import annotations

from typing import Any, cast

import mido
import pytest

from builders import Doc, compile_doc
from busk.commands.bus import CommandBus
from busk.commands.types import Command, CommandOrigin
from busk.engine.clock import FakeClock
from busk.io.bindings import BindingResolver
from busk.io.events import InputEvent
from busk.io.midi import translate
from busk.model.common import SurfaceId
from busk.model.show import Show
from busk.model.surface import InputAddress

SURFACE = SurfaceId("s-midi")


def cc(number: int, channel: int = 1) -> Doc:
    return {"kind": "midiCC", "channel": channel, "cc": number}


def note(number: int, channel: int = 1) -> Doc:
    return {"kind": "midiNote", "channel": channel, "note": number}


def binding(ident: str, address: Doc, action: Doc, surface: str = "s-midi") -> Doc:
    return {"id": ident, "surfaceId": surface, "input": address, "action": action}


class Rig:
    """Appendix A with the given bindings, a real bus and collected reports.

    Its first page is ``pb-song, None, pb-blue, None, None, pb-pulse, None,
    None``; pb-blue's buttons are widened to ``toggle, flash, release, none,
    back`` and pb-song's are ``go, back``.
    """

    def __init__(self, appendix_a: dict[str, Any], *bindings: Doc) -> None:
        appendix_a["playbacks"][1]["buttons"] = ["toggle", "flash", "release", "none", "back"]
        appendix_a["bindings"] = list(bindings)
        compiled = compile_doc(appendix_a)
        self.bus = CommandBus(compiled, FakeClock())
        self.reports: list[str] = []
        self.resolver = BindingResolver(
            cast(Show, appendix_a), compiled, self.bus, self.reports.append
        )

    def send(self, address: Doc, *values: float, surface: str = "s-midi") -> list[Command]:
        """Feed events with ``values``; return the commands they submitted."""
        for value in values:
            self.resolver.handle(InputEvent(SurfaceId(surface), cast(InputAddress, address), value))
        return [envelope["command"] for envelope in self.bus.drain()]


def test_a_page_fader_sets_the_fader_of_its_slot(appendix_a: dict[str, Any]) -> None:
    """Phase 6: the engine resolves the slot on its current page, so empty
    slots and slots beyond the page are sent too (the engine ignores them)."""
    rig = Rig(
        appendix_a,
        binding("b0", cc(0), {"kind": "playbackFader", "slot": 0}),
        binding("b1", cc(1), {"kind": "playbackFader", "slot": 1}),  # empty slot
        binding("b9", cc(9), {"kind": "playbackFader", "slot": 9}),  # off the page
    )
    assert rig.send(cc(0), 64 / 127) == [{"type": "SET_FADER", "slot": 0, "level": 64 / 127}]
    assert rig.send(cc(1), 1.0) == [{"type": "SET_FADER", "slot": 1, "level": 1.0}]
    assert rig.send(cc(9), 1.0) == [{"type": "SET_FADER", "slot": 9, "level": 1.0}]
    assert rig.reports == []


def test_an_absolute_fader(appendix_a: dict[str, Any]) -> None:
    rig = Rig(
        appendix_a, binding("b", cc(3), {"kind": "playbackFaderAbs", "playbackId": "pb-blue"})
    )
    assert rig.send(cc(3), 0.25, 0.5) == [
        {"type": "SET_FADER", "playbackId": "pb-blue", "level": 0.25},
        {"type": "SET_FADER", "playbackId": "pb-blue", "level": 0.5},
    ]


def button(slot: int, index: int) -> Doc:
    return {"kind": "playbackButton", "slot": slot, "button": index}


def pb_button(slot: int, index: int, down: bool) -> Command:
    return cast(Command, {"type": "PLAYBACK_BUTTON", "slot": slot, "button": index, "down": down})


@pytest.mark.parametrize(
    ("slot", "index"),
    [(0, 0), (2, 1), (2, 3), (2, 9), (1, 0), (40, 0)],
    ids=["song go", "blue flash", "blue none", "button 9", "empty slot", "beyond the page"],
)
def test_playback_buttons_send_playback_button_on_each_edge(
    appendix_a: dict[str, Any], slot: int, index: int
) -> None:
    """Phase 6: the engine applies the button's function on its current page,
    so the resolver sends both edges of every button but ``select``."""
    rig = Rig(appendix_a, binding("b", note(32), button(slot, index)))
    assert rig.send(note(32), 1.0) == [pb_button(slot, index, True)]
    assert rig.send(note(32), 0.0) == [pb_button(slot, index, False)]
    assert rig.reports == []


def test_button_edges(appendix_a: dict[str, Any]) -> None:
    rig = Rig(appendix_a, binding("b", cc(32), button(2, 1)))
    down, up = pb_button(2, 1, True), pb_button(2, 1, False)
    assert rig.send(cc(32), 1.0, 1.0) == [down]  # a repeated CC 127 is one press
    assert rig.send(cc(32), 0.0, 0.0) == [up]
    assert rig.send(cc(32), 0.4) == []  # below the press point
    assert rig.send(cc(32), 0.5, 0.49) == [down, up]


class Recorder:
    """A sink that records every command, as the session's input sink takes
    ``SELECT_PLAYBACK`` (the bus would reject it)."""

    def __init__(self) -> None:
        self.commands: list[Command] = []

    def submit(self, command: Command, origin: CommandOrigin | None = None) -> None:
        self.commands.append(command)


@pytest.mark.parametrize(
    ("page", "slot", "expected"),
    [
        (None, 0, "pb-song"),  # no snapshot yet: the first page, as the engine starts
        ("page-1", 0, "pb-song"),
        ("page-2", 0, "pb-blue"),
        ("page-2", 2, "pb-song"),
        ("page-gone", 0, "pb-song"),  # deleted by an edit: the first page
    ],
)
def test_a_select_button_is_looked_up_on_the_snapshots_page(
    appendix_a: dict[str, Any], page: str | None, slot: int, expected: str
) -> None:
    """``select`` changes the programmer, so the resolver sends
    ``SELECT_PLAYBACK`` to the session, on press only (decision 4)."""
    appendix_a["playbacks"][0]["buttons"] = ["select"]
    appendix_a["playbacks"][1]["buttons"] = ["select"]
    appendix_a["pages"].append(
        {"id": "page-2", "number": 2, "name": "Two", "slots": ["pb-blue", None, "pb-song"]}
    )
    appendix_a["bindings"] = [binding("sel", note(5), button(slot, 0))]
    sink = Recorder()
    resolver = BindingResolver(
        cast(Show, appendix_a), compile_doc(appendix_a), sink, page=lambda: page
    )
    for value in (1.0, 0.0):
        resolver.handle(InputEvent(SURFACE, cast(InputAddress, note(5)), value))
    assert sink.commands == [{"type": "SELECT_PLAYBACK", "playbackId": expected, "mode": "replace"}]


def test_a_select_button_on_another_page_sends_playback_button(
    appendix_a: dict[str, Any],
) -> None:
    """Slot 0 holds a ``select`` on page 2 only: on page 1 it is pb-song's ``go``."""
    appendix_a["playbacks"][1]["buttons"] = ["select"]
    appendix_a["pages"].append({"id": "page-2", "number": 2, "name": "Two", "slots": ["pb-blue"]})
    appendix_a["bindings"] = [binding("b", note(5), button(0, 0))]
    sink = Recorder()
    resolver = BindingResolver(
        cast(Show, appendix_a), compile_doc(appendix_a), sink, page=lambda: "page-1"
    )
    resolver.handle(InputEvent(SURFACE, cast(InputAddress, note(5)), 1.0))
    assert sink.commands == [pb_button(0, 0, True)]


def test_masters(appendix_a: dict[str, Any]) -> None:
    rig = Rig(
        appendix_a,
        binding("gm", cc(7), {"kind": "master", "masterId": "m-gm"}),
        binding("speed", cc(8), {"kind": "master", "masterId": "m-speed"}),
    )
    assert rig.send(cc(7), 0.75) == [{"type": "SET_MASTER", "masterId": "m-gm", "level": 0.75}]
    assert rig.send(cc(8), 0.75) == [{"type": "SET_MASTER", "masterId": "m-speed", "level": 0.75}]


def test_size_group_and_fade_time_masters_are_bound(appendix_a: dict[str, Any]) -> None:
    """Size and group masters work since Phase 5 (steps 7 and 9), fade-time
    masters since Phase 6 (step 7)."""
    appendix_a["masters"] += [
        {"id": "m-size", "kind": "size", "name": "FX"},
        {"id": "m-group", "kind": "group", "name": "Heads", "groupId": "g-mh"},
        {"id": "m-fade", "kind": "fadeTime", "name": "Fade"},
    ]
    rig = Rig(
        appendix_a,
        binding("size", cc(9), {"kind": "master", "masterId": "m-size"}),
        binding("group", cc(11), {"kind": "master", "masterId": "m-group"}),
        binding("fade", cc(10), {"kind": "master", "masterId": "m-fade"}),
    )
    assert rig.send(cc(9), 0.5) == [{"type": "SET_MASTER", "masterId": "m-size", "level": 0.5}]
    assert rig.send(cc(11), 0.5) == [{"type": "SET_MASTER", "masterId": "m-group", "level": 0.5}]
    assert rig.send(cc(10), 0.5) == [{"type": "SET_MASTER", "masterId": "m-fade", "level": 0.5}]


def test_tap_sends_tap_on_press(appendix_a: dict[str, Any]) -> None:
    rig = Rig(appendix_a, binding("tap", note(1), {"kind": "tap", "masterId": "m-speed"}))
    tap = {"type": "TAP", "masterId": "m-speed"}
    assert rig.send(note(1), 1.0, 0.0, 1.0, 1.0, 0.0) == [tap, tap]


def test_blackout_latches(appendix_a: dict[str, Any]) -> None:
    """Phase 6 (decision 8): a press toggles blackout, in the engine."""
    rig = Rig(appendix_a, binding("bo", cc(42), {"kind": "blackout"}))
    assert rig.send(cc(42), 1.0, 1.0) == [{"type": "BLACKOUT"}]
    assert rig.send(cc(42), 0.0) == []
    assert rig.send(cc(42), 1.0, 0.0) == [{"type": "BLACKOUT"}]


def test_a_momentary_blackout_holds(appendix_a: dict[str, Any]) -> None:
    rig = Rig(appendix_a, binding("bo", cc(42), {"kind": "blackout", "momentary": True}))
    assert rig.send(cc(42), 1.0) == [{"type": "BLACKOUT", "on": True}]
    assert rig.send(cc(42), 0.0) == [{"type": "BLACKOUT", "on": False}]


def test_an_embedded_command_is_submitted_on_press(appendix_a: dict[str, Any]) -> None:
    command = {"type": "TOGGLE_PLAYBACK", "playbackId": "pb-pulse"}
    rig = Rig(appendix_a, binding("b", note(1), {"kind": "command", "command": command}))
    assert rig.send(note(1), 1.0, 0.0) == [command]


def test_page_actions_send_page_on_press(appendix_a: dict[str, Any]) -> None:
    appendix_a["pages"].append({"id": "page-2", "number": 2, "name": "Two", "slots": []})
    rig = Rig(
        appendix_a,
        binding("next", note(2), {"kind": "page", "delta": 1}),
        binding("prev", note(3), {"kind": "page", "delta": -1}),
        binding("two", note(4), {"kind": "pageAbs", "number": 2}),
    )
    assert rig.send(note(2), 1.0, 1.0, 0.0) == [{"type": "PAGE", "delta": 1}]
    assert rig.send(note(3), 1.0, 0.0) == [{"type": "PAGE", "delta": -1}]
    assert rig.send(note(4), 1.0, 0.0) == [{"type": "PAGE", "number": 2}]
    assert rig.reports == []


def test_a_page_number_no_page_has_is_reported(appendix_a: dict[str, Any]) -> None:
    rig = Rig(appendix_a, binding("nine", note(4), {"kind": "pageAbs", "number": 9}))
    assert rig.send(note(4), 1.0, 0.0, 1.0) == []
    assert rig.reports == ["binding nine: no page 9"]


def test_a_rejected_command_is_reported_once_per_binding(appendix_a: dict[str, Any]) -> None:
    goto = {"type": "GOTO", "playbackId": "pb-song", "cueNumber": "7"}
    rig = Rig(appendix_a, binding("b", note(1), {"kind": "command", "command": goto}))
    assert rig.send(note(1), 1.0, 0.0, 1.0, 0.0) == []
    assert rig.reports == ["binding b: no cue 7 in cue list 1"]


def test_exceptions_never_escape(
    appendix_a: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(appendix_a, binding("b", cc(0), {"kind": "playbackFader", "slot": 0}))

    def broken(*args: Any) -> None:
        raise RuntimeError("queue on fire")

    monkeypatch.setattr(rig.bus, "submit", broken)
    rig.send(cc(0), 0.5, 0.6)
    assert rig.reports == ["binding b: RuntimeError: queue on fire"]


def test_events_match_surface_and_address(appendix_a: dict[str, Any]) -> None:
    rig = Rig(
        appendix_a,
        binding("a", cc(0), {"kind": "playbackFader", "slot": 0}),
        binding("b", cc(0), {"kind": "master", "masterId": "m-gm"}),  # same input: both fire
    )
    assert len(rig.send(cc(0), 1.0)) == 2
    assert rig.send(cc(0, channel=2), 1.0) == []  # another channel
    assert rig.send(note(0), 1.0) == []  # a note, not a CC
    assert rig.send(cc(0), 1.0, surface="s-other") == []


def test_commands_carry_their_surface_and_control_as_origin(appendix_a: dict[str, Any]) -> None:
    """Phase 6: the control is the binding's id (decision 5)."""
    rig = Rig(
        appendix_a,
        binding("b-fader", cc(0), {"kind": "playbackFader", "slot": 0}),
        binding("b-button", note(0), button(0, 0)),
    )
    rig.resolver.handle(InputEvent(SURFACE, cast(InputAddress, cc(0)), 1.0))
    rig.resolver.handle(InputEvent(SURFACE, cast(InputAddress, note(0)), 1.0))
    fader, pressed = rig.bus.drain()
    assert fader["origin"] == {"surfaceId": "s-midi", "control": "b-fader"}
    assert pressed["origin"] == {"surfaceId": "s-midi", "control": "b-button"}


def test_midi_channels_are_one_based(appendix_a: dict[str, Any]) -> None:
    """Appendix A's b1 (CC 0 on channel 1) answers mido channel 0."""
    rig = Rig(appendix_a, *appendix_a["bindings"])
    event = translate(SURFACE, mido.Message("control_change", channel=0, control=0, value=127))
    assert event is not None
    rig.resolver.handle(event)
    assert [e["command"] for e in rig.bus.drain()] == [
        {"type": "SET_FADER", "slot": 0, "level": 1.0}
    ]
    note_on = translate(SURFACE, mido.Message("note_on", channel=0, note=32, velocity=1))
    assert note_on is not None
    rig.resolver.handle(note_on)  # b2: any velocity presses slot 0's button 0
    assert [e["command"] for e in rig.bus.drain()] == [pb_button(0, 0, True)]


def test_the_resolver_records_when_each_binding_last_received_input(
    appendix_a: dict[str, Any],
) -> None:
    """For the feedback thread's echo hold (phase-6-plan §5.8): every binding
    of the event, at the resolver's clock."""
    appendix_a["bindings"] = [
        binding("b0", cc(0), {"kind": "playbackFader", "slot": 0}),
        binding("b1", cc(0), {"kind": "master", "masterId": "m-gm"}),
        binding("b2", cc(1), {"kind": "playbackFaderAbs", "playbackId": "pb-blue"}),
    ]
    compiled = compile_doc(appendix_a)
    clock = FakeClock(3.0)
    resolver = BindingResolver(
        cast(Show, appendix_a), compiled, CommandBus(compiled, clock), clock=clock.now
    )
    resolver.handle(InputEvent(SURFACE, cast(InputAddress, cc(0)), 0.5))
    assert resolver.lastInput == {"b0": 3.0, "b1": 3.0}
    clock.advance(1.0)
    resolver.handle(InputEvent(SURFACE, cast(InputAddress, cc(1)), 1.0))
    resolver.handle(InputEvent(SURFACE, cast(InputAddress, cc(5)), 1.0))  # bound to nothing
    assert resolver.lastInput == {"b0": 3.0, "b1": 3.0, "b2": 4.0}
