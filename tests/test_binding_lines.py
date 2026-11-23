"""One binding at a time (GAP-63 of ``docs/dev/tui/engine-gaps.md``), and what
``bind`` refuses (Phase 40 of ``docs/plans/tui-pending-plan.md``).

``delete binding <id>`` takes one binding, whatever its control, and asks
nothing. ``binding <id> change <what bind takes after the surface>`` gives
the binding whole, keeping its id and its surface, in one undo step.
``unbind "<s>" clock`` takes a clock's bindings. ``bind`` and ``change``
refuse in words what the surface could not use: a MIDI channel outside 1 to
16, a number above 127, a control of another kind than the surface sends,
``display`` on MIDI, any binding on a web remote or a surface busk does not
open; ``unbind`` and ``feedback`` refuse the ranges too. A show file that
holds one still loads, with the validator's warning.

The rig below has one surface of each kind, two bindings on one control and a
clock's.
"""

from __future__ import annotations

import copy
import json
import socket
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from builders import localhost_route
from busk import LiveShow, OfflineShow, load_show, new_show
from busk.commands.types import Command
from busk.io import midi
from busk.io.osc import decode, encode
from busk.persistence.show_file import save_show
from process_harness import BuskRun
from sacn_receiver import Receiver
from test_hotplug import Ports


def run(show: OfflineShow | LiveShow, *lines: str) -> None:
    for line in lines:
        reply = show.execute(line)
        assert reply.ok, (line, reply.text)


def said(show: OfflineShow | LiveShow, line: str) -> str:
    """The reply to ``line``, which must go through."""
    reply = show.execute(line)
    assert reply.ok, (line, reply.text)
    return reply.text


def refused(show: OfflineShow, line: str) -> str:
    """The reply to ``line``, which must be refused."""
    reply = show.execute(line)
    assert not reply.ok, (line, reply.text)
    return reply.text


def one_step(show: OfflineShow, line: str) -> str:
    """Run ``line``; check that one ``undo`` gives the document back and that
    ``redo`` does it again. The reply to it."""
    before = copy.deepcopy(show.show)
    reply = said(show, line)
    after = copy.deepcopy(show.show)
    run(show, "undo")
    assert show.show == before
    run(show, "redo")
    assert show.show == after
    return reply


def ids(show: OfflineShow | LiveShow) -> list[str]:
    return [binding["id"] for binding in show.show["bindings"]]


def binding(show: OfflineShow | LiveShow, ident: str) -> dict[str, Any]:
    return cast(dict[str, Any], next(b for b in show.show["bindings"] if b["id"] == ident))


def surface_id(show: OfflineShow | LiveShow, name: str) -> str:
    return str(next(s["id"] for s in show.show["surfaces"] if s["name"] == name))


def add(show: OfflineShow, collection: str, value: dict[str, Any]) -> None:
    """``value`` added through ``submit()``: what a show file can hold and no
    line makes."""
    result = show.submit(cast(Command, {"type": "ADD", "path": [collection], "value": value}))
    assert result.ok, result.message


def cc_1_1(surface: str) -> dict[str, Any]:
    """Binding ``b-odd``: ``cc 1 1`` on ``surface`` to a blackout."""
    control = {"kind": "midiCC", "channel": 1, "cc": 1}
    return {"id": "b-odd", "surfaceId": surface, "input": control, "action": {"kind": "blackout"}}


@pytest.fixture
def rig() -> OfflineShow:
    show = OfflineShow(new_show("Rig"))
    run(
        show,
        'universe add 1 "Stage"',
        'fixture add 1 thru 2 "RGB Par 3ch" mode 3ch at 1.1',
        "sel fixture 1",
        "set intensity 100%",
        "record slot 1",
        "sel fixture 2",
        "set intensity 100%",
        "record slot 2",
        "clear",
        'master add speed "Speed 1"',
        'surface add midi "Pad"',
        'surface add osc "Touch" port 9000',
        'surface add web "Phone" port 8080',
        'bind "Pad" cc 1 0 fader 1',
        'bind "Pad" cc 1 48 button 1 1 led',
        'bind "Pad" cc 1 48 blackout',
        'bind "Pad" clock tap',
        'bind "Touch" osc "/fader/1" fader 1 display osc "/label/1"',
    )
    keys = {"id": "s-keys", "name": "Keys", "kind": "hid", "match": {}, "faderPickup": "jump"}
    add(show, "surfaces", keys)
    return show


FADER, BUTTON, BLACKOUT, CLOCK, TOUCH = range(5)
"""The rig's bindings, in order."""


# ------------------------------------------------------------ delete binding


def test_one_of_two_bindings_on_a_control_goes_alone_in_one_step(rig: OfflineShow) -> None:
    button, blackout = ids(rig)[BUTTON], ids(rig)[BLACKOUT]
    reply = one_step(rig, f"delete binding {blackout}")
    assert reply == f"deleted binding {blackout}: cc 1 48 → blackout"
    assert blackout not in ids(rig)
    assert binding(rig, button)["action"] == {"kind": "playbackButton", "slot": 0, "button": 0}


def test_a_delete_asks_nothing_and_undo_brings_it_back_in_its_place(rig: OfflineShow) -> None:
    before = ids(rig)
    assert rig.confirmation(f"delete binding {before[BUTTON]}") is None
    run(rig, f"delete binding {before[BUTTON]}", "undo")
    assert ids(rig) == before


def test_a_clocks_binding_is_changed_and_deleted(rig: OfflineShow) -> None:
    clock = ids(rig)[CLOCK]
    reply = one_step(rig, f'binding {clock} change clock tap "Speed 1" led cc 1 46')
    assert reply == f"changed binding {clock}: clock → tap 'Speed 1' [led cc 1 46]"
    assert binding(rig, clock)["feedback"] == {
        "kind": "led",
        "address": {"kind": "midiCC", "channel": 1, "cc": 46},
    }
    assert one_step(rig, f"delete binding {clock}").startswith(f"deleted binding {clock}: clock")
    assert clock not in ids(rig)


def test_unbind_takes_a_clocks_bindings(rig: OfflineShow) -> None:
    clock = ids(rig)[CLOCK]
    assert one_step(rig, 'unbind "Pad" clock') == "unbound 1 binding"
    assert clock not in ids(rig)
    assert refused(rig, 'unbind "Pad" clock') == "error: 'Pad' has no binding on clock"


def test_unbind_offers_no_thru_after_clock(rig: OfflineShow) -> None:
    found = rig.expected('unbind "Pad" clock ')
    assert (found.words, found.runnable) == ((), True)


def test_a_pitch_bend_and_a_hardware_control_from_a_show_file_go_by_their_id(
    rig: OfflineShow,
) -> None:
    pad = surface_id(rig, "Pad")
    bend = {"kind": "midiPitchBend", "channel": 1}
    add(rig, "bindings", {"id": "b-bend", "surfaceId": pad, "input": bend,
                          "action": {"kind": "playbackFader", "slot": 1}})  # fmt: skip
    hardware = {"kind": "hw", "controlId": "k1"}
    add(rig, "bindings", {"id": "b-hw", "surfaceId": "s-keys", "input": hardware,
                          "action": {"kind": "blackout"}})  # fmt: skip
    assert one_step(rig, "delete binding b-bend") == "deleted binding b-bend: bend 1 → fader 2"
    assert one_step(rig, "delete binding b-hw") == "deleted binding b-hw: hw k1 → blackout"


# ---------------------------------------------------------- binding change


def test_a_change_gives_the_control_what_it_drives_and_its_feedback(rig: OfflineShow) -> None:
    button = ids(rig)[BUTTON]
    reply = one_step(rig, f"binding {button} change note 2 60 fader 2 motor")
    assert reply == f"changed binding {button}: note 2 60 → fader 2 [motor]"
    assert ids(rig)[BUTTON] == button  # its id, and its place in the list
    assert binding(rig, button) == {
        "id": button,
        "surfaceId": surface_id(rig, "Pad"),
        "input": {"kind": "midiNote", "channel": 2, "note": 60},
        "action": {"kind": "playbackFader", "slot": 1},
        "feedback": {"kind": "motorFader", "address": {"kind": "midiNote", "channel": 2,
                                                       "note": 60}},
    }  # fmt: skip


def test_one_of_two_bindings_on_a_control_changes_alone(rig: OfflineShow) -> None:
    button, blackout = ids(rig)[BUTTON], ids(rig)[BLACKOUT]
    run(rig, f"binding {blackout} change cc 1 49 blackout momentary")
    assert binding(rig, blackout)["input"] == {"kind": "midiCC", "channel": 1, "cc": 49}
    assert binding(rig, button)["input"] == {"kind": "midiCC", "channel": 1, "cc": 48}


def test_a_feedback_left_out_goes(rig: OfflineShow) -> None:
    button = ids(rig)[BUTTON]
    reply = one_step(rig, f"binding {button} change cc 1 48 button 1 1")
    assert reply == f"changed binding {button}: cc 1 48 → button 1 1"
    assert "feedback" not in binding(rig, button)


def test_an_osc_binding_changes_its_path_and_its_feedback(rig: OfflineShow) -> None:
    touch = ids(rig)[TOUCH]
    reply = one_step(rig, f'binding {touch} change osc "/fader/2" fader 2 display')
    assert reply == f'changed binding {touch}: osc "/fader/2" → fader 2 [display]'
    assert binding(rig, touch)["feedback"] == {
        "kind": "display",
        "address": {"kind": "osc", "path": "/fader/2"},
    }


def test_a_pitch_bends_binding_from_a_show_file_changes_to_a_control_bind_takes(
    rig: OfflineShow,
) -> None:
    bend = {"kind": "midiPitchBend", "channel": 1}
    add(rig, "bindings", {"id": "b-bend", "surfaceId": surface_id(rig, "Pad"), "input": bend,
                          "action": {"kind": "playbackFader", "slot": 1}})  # fmt: skip
    assert said(rig, "binding b-bend change cc 1 7 fader 2") == (
        "changed binding b-bend: cc 1 7 → fader 2"
    )


def test_a_change_that_changes_nothing_is_refused_and_tab_says_so(rig: OfflineShow) -> None:
    touch = ids(rig)[TOUCH]
    line = f'binding {touch} change osc "/fader/1" fader 1 display osc "/label/1"'
    error = f"binding {touch} is set up that way already"
    assert refused(rig, line) == f"error: {error}"
    found = rig.expected(line + " ")
    assert (found.runnable, found.error) == (False, error)


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("binding b-nope change cc 1 1 fader 1", "no binding b-nope"),
        ("binding {pad}", "expected change"),
        ("binding {pad} move", "expected change, got 'move'"),
        ("binding {pad} change cc 0 0 fader 1", "expected a MIDI channel (1–16), got '0'"),
        ("binding {pad} change cc 1 128 fader 1", "expected a CC number (0–127), got '128'"),
        ('binding {pad} change osc "/x" fader 1',
         "surface \"Pad\" is a MIDI surface: expected cc, note or clock, got 'osc'"),
        ("binding {pad} change cc 1 0 fader 1 display",
         "surface \"Pad\" is a MIDI surface: expected led or motor, got 'display'"),
        ("binding {touch} change cc 1 0 fader 1",
         "surface \"Touch\" is an OSC surface: expected osc, got 'cc'"),
        ("binding {pad} change cc 1 0 fader 1 now", "expected led, motor or display, got 'now'"),
        ("binding {pad} change cc 1 0 fader 1 led cc 1 1 now", "unexpected 'now'"),
    ],
)  # fmt: skip
def test_what_change_refuses(rig: OfflineShow, line: str, error: str) -> None:
    line = line.format(pad=ids(rig)[FADER], touch=ids(rig)[TOUCH])
    assert refused(rig, line) == f"error: {error}"


@pytest.mark.parametrize(
    ("name", "error"),
    [
        ("Phone", 'surface "Phone" is a web remote, which sends commands of its own: '
                  "it takes no binding"),
        ("Keys", 'surface "Keys" is a hid surface, which busk does not open'),
    ],
)  # fmt: skip
def test_a_binding_on_a_surface_that_sends_none_goes_but_does_not_change(
    rig: OfflineShow, name: str, error: str
) -> None:
    add(rig, "bindings", cc_1_1(surface_id(rig, name)))
    assert refused(rig, "binding b-odd change cc 1 1 fader 1") == f"error: {error}"
    run(rig, "delete binding b-odd")


# -------------------------------------------------------------- bind refuses


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ('bind "Pad" cc 0 0 fader 1', "expected a MIDI channel (1–16), got '0'"),
        ('bind "Pad" cc 17 0 fader 1', "expected a MIDI channel (1–16), got '17'"),
        ('bind "Pad" note -1 0 fader 1', "expected a MIDI channel (1–16), got '-1'"),
        ('bind "Pad" cc 1 128 fader 1', "expected a CC number (0–127), got '128'"),
        ('bind "Pad" note 1 128 fader 1', "expected a note number (0–127), got '128'"),
        ('bind "Pad" note 1 -1 fader 1', "expected a note number (0–127), got '-1'"),
        ('bind "Pad" cc 1 0 fader 1 led note 1 200',
         "expected a note number (0–127), got '200'"),
        ('bind "Pad" osc "/x" fader 1',
         "surface \"Pad\" is a MIDI surface: expected cc, note or clock, got 'osc'"),
        ('bind "Pad" cc 1 0 fader 1 display',
         "surface \"Pad\" is a MIDI surface: expected led or motor, got 'display'"),
        ('bind "Pad" cc 1 0 fader 1 led osc "/x"',
         "surface \"Pad\" is a MIDI surface: expected cc or note, got 'osc'"),
        ('bind "Pad" clock tap led', "a clock input has no feedback address: give one"),
        ('bind "Pad" clock tap led clock', "surface \"Pad\" is a MIDI surface: "
                                           "expected cc or note, got 'clock'"),
        ('bind "Touch" cc 1 0 fader 1', "surface \"Touch\" is an OSC surface: expected osc, "
                                        "got 'cc'"),
        ('bind "Touch" note 1 0 fader 1', "surface \"Touch\" is an OSC surface: expected osc, "
                                          "got 'note'"),
        ('bind "Touch" clock tap', "surface \"Touch\" is an OSC surface: expected osc, "
                                   "got 'clock'"),
        ('bind "Touch" osc "/x" fader 1 led cc 1 0', "surface \"Touch\" is an OSC surface: "
                                                     "expected osc, got 'cc'"),
        ('bind "Touch" knob 1', "expected osc, got 'knob'"),
        ('bind "Phone" osc "/x" fader 1', 'surface "Phone" is a web remote, which sends '
                                          "commands of its own: it takes no binding"),
        ('bind "Keys" cc 1 0 fader 1', 'surface "Keys" is a hid surface, which busk does not '
                                       "open"),
    ],
)  # fmt: skip
def test_what_bind_refuses(rig: OfflineShow, line: str, error: str) -> None:
    before = copy.deepcopy(rig.show)
    assert refused(rig, line) == f"error: {error}"
    assert rig.show == before


@pytest.mark.parametrize(
    "line",
    [
        'bind "Pad" cc 1 0 fader 1',
        'bind "Pad" cc 16 127 fader 1',
        'bind "Pad" note 1 0 master gm motor',
        'bind "Pad" clock tap led note 1 1',
        'bind "Touch" osc "/x" fader 1 display',
        'bind "Touch" osc "/x" fader 1 led osc "/y"',
    ],
)
def test_what_bind_takes_still(rig: OfflineShow, line: str) -> None:
    assert said(rig, line).startswith("added binding b-")


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ('unbind "Pad" cc 17 0', "expected a MIDI channel (1–16), got '17'"),
        ('unbind "Pad" cc 1 0 thru 128', "expected a CC number (0–127) after thru, got '128'"),
        ('feedback "Pad" note 1 200 led', "expected a note number (0–127), got '200'"),
        ('feedback "Pad" cc 1 48 display',
         "surface \"Pad\" is a MIDI surface: expected led, motor or none, got 'display'"),
    ],
)  # fmt: skip
def test_unbind_and_feedback_refuse_the_ranges(rig: OfflineShow, line: str, error: str) -> None:
    assert refused(rig, line) == f"error: {error}"


def test_unbind_and_feedback_still_reach_a_show_files_binding_of_another_kind(
    rig: OfflineShow,
) -> None:
    add(rig, "bindings", cc_1_1(surface_id(rig, "Touch")))
    assert said(rig, 'feedback "Touch" cc 1 1 led') == "feedback on 1 binding"
    assert said(rig, 'unbind "Touch" cc 1 1') == "unbound 1 binding"


# ---------------------------------------------------------------------- Tab


def test_tab_offers_the_ids_and_the_surfaces_own_controls(rig: OfflineShow) -> None:
    every = tuple(ids(rig))
    assert "binding" in rig.expected("").words
    assert "binding" in rig.expected("delete ").words
    assert rig.expected("binding ").words == every
    assert rig.expected("delete binding ").words == every
    pad, touch = every[FADER], every[TOUCH]
    assert rig.expected(f"binding {pad} ").words == ("change",)
    assert rig.expected(f"binding {pad} change ").words == ("cc", "note", "clock")
    assert rig.expected(f"binding {touch} change ").words == ("osc",)
    assert rig.expected(f"delete binding {pad} ").runnable
    assert rig.expected('bind "Pad" ').words == ("cc", "note", "clock")
    assert rig.expected('bind "Touch" ').words == ("osc",)
    found = rig.expected('bind "Pad" cc 1 0 fader 1 ')
    assert (found.words, found.runnable) == (("led", "motor"), True)
    assert rig.expected('bind "Touch" osc "/x" fader 1 ').words == ("led", "motor", "display")
    assert rig.expected('bind "Pad" cc 1 0 fader 1 led ').words == ("cc", "note")
    assert rig.expected('bind "Pad" cc ').values == ("a MIDI channel (1–16)",)
    assert rig.expected('bind "Pad" cc 1 ').values == ("a CC number (0–127)",)
    assert rig.expected('bind "Pad" note 1 ').values == ("a note number (0–127)",)
    found = rig.expected('bind "Phone" ')
    assert found.error == (
        'surface "Phone" is a web remote, which sends commands of its own: it takes no binding'
    )
    assert rig.expected('unbind "Pad" ').words == ("cc", "note", "osc", "clock")


def test_help_names_the_lines() -> None:
    text = OfflineShow(new_show("Help")).execute("help").text
    assert "binding <id> change" in text
    assert "delete binding <id>" in text
    assert 'unbind "<surface>" clock' in text


# ------------------------------------------------------------ the validator


def test_a_show_file_holding_what_bind_refuses_loads_with_warnings(
    rig: OfflineShow, tmp_path: Path
) -> None:
    pad = surface_id(rig, "Pad")
    odd = {"kind": "midiNote", "channel": 0, "note": 200}
    add(rig, "bindings", {"id": "b-odd", "surfaceId": pad,
                          "input": {"kind": "midiCC", "channel": 17, "cc": 128},
                          "action": {"kind": "blackout"},
                          "feedback": {"kind": "display", "address": odd}})  # fmt: skip
    path = tmp_path / "rig.show"
    save_show(rig.show, path)
    show, issues = load_show(path)
    at = len(rig.show["bindings"]) - 1
    assert [(i.severity, i.path, i.message) for i in issues] == [
        ("warning", f"bindings[{at}].input.channel",
         "A MIDI channel is from 1 to 16, got 17; this binding does nothing"),
        ("warning", f"bindings[{at}].input.cc",
         "A MIDI CC number is from 0 to 127, got 128; this binding does nothing"),
        ("warning", f"bindings[{at}].feedback.address.channel",
         "A MIDI channel is from 1 to 16, got 0; this feedback is not sent"),
        ("warning", f"bindings[{at}].feedback.address.note",
         "A MIDI note number is from 0 to 127, got 200; this feedback is not sent"),
        ("warning", f"bindings[{at}].feedback.kind",
         f"MIDI surface {pad!r} has no display; this feedback is not sent"),
    ]  # fmt: skip
    assert show == rig.show


# --------------------------------------------------------------- a live show


def eventually(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


@pytest.fixture
def no_midi(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake MIDI system, with nothing but Midi Through plugged in: this
    host may have a real controller."""
    system = Ports()
    monkeypatch.setattr(midi, "input_names", system.list)
    monkeypatch.setattr(midi, "output_names", system.list)
    monkeypatch.setattr(midi.mido, "open_input", system.open_input)
    monkeypatch.setattr(midi.mido, "open_output", system.open_output)


class Touch:
    """A live show with an OSC surface ``Touch`` on localhost, which picks
    faders up softly and sends feedback to :attr:`feedback`; ``/blackout``
    holds a blackout, as a marker: commands from one surface reach the
    engine in order."""

    def __init__(
        self, live: LiveShow, port: int, client: socket.socket, feedback: socket.socket
    ) -> None:
        self.live, self.port, self.client, self.feedback = live, port, client, feedback

    def send(self, path: str, value: float) -> None:
        """Send ``path`` until the show hears it, once each time it is
        called: a moved binding reads its show a moment after the line."""
        last = max((i.seq for i in self.live.inputs), default=0)
        deadline = time.monotonic() + 5.0
        while not any(
            i.seq > last and i.input == f'osc "{path}"' and i.value == value
            for i in self.live.inputs
        ):
            assert time.monotonic() < deadline, f"{path} never heard"
            self.client.sendto(encode(path, value), ("127.0.0.1", self.port))
            time.sleep(0.05)

    def settle(self) -> None:
        """Wait until the engine has applied every move sent before."""
        for value in (1.0, 0.0):
            self.send("/blackout", value)
            eventually(lambda value=value: self.snapshot().blackout == bool(value))

    def fader(self) -> str:
        """The id of the binding on ``/fader/1``."""
        path = {"kind": "osc", "path": "/fader/1"}
        return str(next(b["id"] for b in self.live.show["bindings"] if b["input"] == path))

    def snapshot(self) -> Any:
        snapshot = self.live.snapshot
        assert snapshot is not None
        return snapshot

    def level(self, number: int) -> float:
        ident = next(p["id"] for p in self.live.show["playbacks"] if p["number"] == number)
        return float(next(p.faderLevel for p in self.snapshot().playbacks if p.id == ident))

    def heard(self, timeout: float = 0.5) -> list[tuple[str, Any]]:
        """The feedback messages that come within ``timeout``."""
        messages: list[tuple[str, Any]] = []
        self.feedback.settimeout(timeout)
        try:
            while True:
                messages += [(address, *args) for address, args in decode(self.feedback.recv(4096))]
        except TimeoutError:
            return messages


@pytest.fixture
def touch(rig: OfflineShow, no_midi: None) -> Any:
    port = free_port()
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client,
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as feedback,
    ):
        feedback.bind(("127.0.0.1", 0))
        run(
            rig,
            'delete surface "Pad" cascade',
            'delete surface "Phone"',
            'delete surface "Keys"',
            f'surface "Touch" change port {port} feedback 127.0.0.1:{feedback.getsockname()[1]}',
            'surface "Touch" pickup soft',
            'bind "Touch" osc "/blackout" blackout momentary',
        )
        with LiveShow(copy.deepcopy(rig.show), output=False, surfaces=True) as live:
            yield Touch(live, port, client, feedback)


def test_a_binding_moved_to_another_path_drives_from_it_and_not_from_the_old(
    touch: Touch,
) -> None:
    fader = touch.fader()
    touch.send("/fader/1", 0.0)
    touch.send("/fader/1", 0.5)
    run(touch.live, f'binding {fader} change osc "/fader/9" fader 1')
    touch.send("/fader/9", 0.5)
    assert touch.live.inputs[-1].drives == ("fader 1",)
    touch.send("/fader/1", 0.75)
    assert touch.live.inputs[-1].drives == ()  # nothing is bound there now
    touch.settle()
    assert touch.level(1) == 0.5


def test_a_soft_fader_moved_to_another_slot_picks_its_level_up(touch: Touch) -> None:
    fader = touch.fader()
    touch.send("/fader/1", 0.0)
    touch.send("/fader/1", 0.625)
    touch.settle()
    assert (touch.level(1), touch.level(2)) == (0.625, 0.0)
    run(touch.live, f'binding {fader} change osc "/fader/1" fader 2')
    touch.send("/fader/1", 0.75)  # slot 2 is at 0: the fader has not met it
    touch.settle()
    assert (touch.level(1), touch.level(2)) == (0.625, 0.0)
    touch.send("/fader/1", 0.0)  # it meets it, and drives it from there
    touch.send("/fader/1", 0.25)
    touch.settle()
    assert (touch.level(1), touch.level(2)) == (0.625, 0.25)


def test_a_soft_fader_moved_to_another_control_picks_the_level_up(touch: Touch) -> None:
    fader = touch.fader()
    touch.send("/fader/1", 0.0)
    touch.send("/fader/1", 0.625)
    touch.settle()
    run(touch.live, f'binding {fader} change osc "/fader/2" fader 1')
    touch.send("/fader/2", 0.125)  # another fader, down at 0.125: the level must not jump
    touch.send("/fader/2", 0.25)
    touch.settle()
    assert touch.level(1) == 0.625
    touch.send("/fader/2", 0.75)  # it crosses the level, and takes it
    touch.settle()
    assert touch.level(1) == 0.75


def test_feedback_moves_to_the_new_address_and_stops_on_the_old(touch: Touch) -> None:
    fader = touch.fader()
    name = next(p["name"] for p in touch.live.show["playbacks"] if p["number"] == 1)
    eventually(lambda: ("/label/1", name) in touch.heard())
    run(touch.live, f'binding {fader} change osc "/fader/1" fader 1 display osc "/label/2"')
    eventually(lambda: ("/label/2", name) in touch.heard())
    run(touch.live, 'rename playback 1 "Renamed"')
    heard = touch.heard(1.0)
    assert ("/label/2", "Renamed") in heard
    assert all(address != "/label/1" for address, *_ in heard)


# ------------------------------------------------------------------ busk run


def test_busk_run_changes_and_deletes_a_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, receiver: Receiver, rig: OfflineShow
) -> None:
    port = free_port()
    run(rig, f'surface "Touch" change port {port}', 'delete surface "Pad" cascade')
    run(rig, 'delete surface "Phone"', 'delete surface "Keys"', 'bind "Touch" osc "/x" blackout')
    touch, blackout = ids(rig)
    show = tmp_path / "show.json"
    show.write_text(json.dumps(localhost_route(cast(Any, rig.show))))
    report = tmp_path / "report.json"
    plan = tmp_path / "plan.json"
    lines = [f'binding {touch} change osc "/fader/2" fader 2', f"delete binding {blackout}"]
    plan.write_text(
        json.dumps(
            {
                "lines": lines,
                "osc": {"port": port, "messages": [["/fader/2", 0.75]], "repeat": True},
                "report": str(report),
            }
        )
    )
    monkeypatch.setenv("BUSK_TEST_FRONTEND", str(plan))
    options = ["--frontend", "frontend_probe:main", "--state-dir", str(tmp_path / "state")]
    with BuskRun(show, *options, "--no-log", sacn_port=receiver.port) as busk_run:
        assert busk_run.wait() == 0, busk_run.err
    seen = json.loads(report.read_text())
    assert seen["timeout"] is None, seen
    assert [reply[:3] for reply in seen["replies"]] == [
        [lines[0], f'changed binding {touch}: osc "/fader/2" → fader 2', True],
        [lines[1], f'deleted binding {blackout}: osc "/x" → blackout', True],
    ]
    assert seen["inputs"][0][2:] == ["Touch", 'osc "/fader/2"', None, 0.75, ["fader 2"]]
