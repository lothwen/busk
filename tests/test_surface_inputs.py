"""What comes in from the control surfaces (GAP-13 of ``docs/dev/tui/engine-gaps.md``).

``LiveShow.inputs`` gives the newest 64 inputs, oldest first, bound or not:
each with a sequence number, its surface, its control as ``bind`` takes it,
the number the device sent, the value the bindings got and what they drive,
as ``list bindings`` prints it. The binding resolver hands every event to the
log (:class:`busk.console.inputs.InputLog`) after its commands.

The resolver tests feed mido messages through ``MidiInput``'s callback, as
rtmidi would; the ``LiveShow`` tests send OSC to a surface on localhost; the
``busk run`` tests run a frontend in the console process, with processes and
with ``--threads``.
"""

from __future__ import annotations

import copy
import json
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import mido
import pytest

from builders import compile_doc, localhost_route
from busk.commands.types import Command, CommandOrigin
from busk.console.inputs import INPUTS_KEPT, InputLog, SurfaceInput
from busk.io import midi
from busk.io.bindings import BindingResolver
from busk.io.osc import encode
from busk.model.show import Show
from busk.model.surface import ControlSurface
from busk.runner import LiveShow, OfflineShow
from process_harness import BuskRun
from sacn_receiver import Receiver

MIDI = "s-midi"  # Appendix A's surface, "MIDI Controller"


class Sink:
    """The commands the bindings send."""

    def __init__(self) -> None:
        self.commands: list[Command] = []

    def submit(self, command: Command, origin: CommandOrigin | None = None) -> object:
        self.commands.append(command)
        return None


class Rig:
    """Appendix A with more bindings, its resolver recording into a log, and
    the MIDI callback rtmidi would call."""

    def __init__(self, appendix_a: dict[str, Any], *bindings: dict[str, Any]) -> None:
        appendix_a["bindings"] += list(bindings)
        self.doc = appendix_a
        self.sink = Sink()
        self.reports: list[str] = []
        self.log = InputLog(lambda: cast(Show, self.doc))
        self.resolver = BindingResolver(
            cast(Show, appendix_a),
            compile_doc(appendix_a),
            self.sink,
            self.reports.append,
            record=self.log.record,
        )
        surface = cast(ControlSurface, appendix_a["surfaces"][0])
        self.port = midi.MidiInput(surface, self.resolver.handle)

    def send(self, *messages: Any) -> None:
        for message in messages:
            self.port._callback(message)

    def seen(self) -> list[tuple[str, int | None, float, tuple[str, ...]]]:
        return [(i.input, i.raw, i.value, i.drives) for i in self.log.inputs]


def bound(ident: str, address: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    return {"id": ident, "surfaceId": MIDI, "input": address, "action": action}


def cc(number: int, value: int, channel: int = 1) -> Any:
    return mido.Message("control_change", channel=channel - 1, control=number, value=value)


# ------------------------------------------------------------- what comes in


def test_a_cc_names_its_surface_control_value_and_what_it_drives(
    appendix_a: dict[str, Any],
) -> None:
    rig = Rig(appendix_a)
    assert rig.log.inputs == ()
    rig.send(cc(0, 102))
    assert rig.log.inputs == (
        SurfaceInput(
            seq=1,
            surfaceId=MIDI,
            surface="MIDI Controller",
            input="cc 1 0",
            raw=102,
            value=102 / 127,
            drives=("fader 1",),
        ),
    )
    assert rig.sink.commands == [{"type": "SET_FADER", "slot": 0, "level": 102 / 127}]


def test_a_note_on_and_off_keep_their_velocity(appendix_a: dict[str, Any]) -> None:
    rig = Rig(appendix_a)
    rig.send(
        mido.Message("note_on", note=32, velocity=100),
        mido.Message("note_off", note=32, velocity=64),
        mido.Message("note_on", note=32, velocity=90),
        mido.Message("note_on", note=32, velocity=0),  # a note off too
    )
    assert rig.seen() == [
        ("note 1 32", 100, 1.0, ("button 1 1",)),
        ("note 1 32", 64, 0.0, ("button 1 1",)),
        ("note 1 32", 90, 1.0, ("button 1 1",)),
        ("note 1 32", 0, 0.0, ("button 1 1",)),
    ]


def test_a_pitch_bend_reads_bend_with_its_pitch(appendix_a: dict[str, Any]) -> None:
    rig = Rig(appendix_a)
    rig.send(
        mido.Message("pitchwheel", channel=2, pitch=4096),
        mido.Message("pitchwheel", channel=2, pitch=-8192),
    )
    assert rig.seen() == [
        ("bend 3", 4096, (4096 + 8192) / 16383, ()),
        ("bend 3", -8192, 0.0, ()),
    ]


def test_the_clock_shows_its_beats_with_no_number(appendix_a: dict[str, Any]) -> None:
    rig = Rig(
        appendix_a, bound("bc", {"kind": "midiClock"}, {"kind": "tap", "masterId": "m-speed"})
    )
    rig.send(*[mido.Message("clock")] * 25)  # a beat: its press, its release, then the next
    assert rig.seen() == [
        ("clock", None, 1.0, ("tap 'Speed 1'",)),
        ("clock", None, 0.0, ("tap 'Speed 1'",)),
        ("clock", None, 1.0, ("tap 'Speed 1'",)),
    ]


def test_an_unbound_control_shows_with_nothing_it_drives(appendix_a: dict[str, Any]) -> None:
    rig = Rig(appendix_a)
    rig.send(cc(48, 127, channel=2))
    assert rig.seen() == [("cc 2 48", 127, 1.0, ())]
    assert rig.sink.commands == []


def test_a_control_with_two_bindings_names_both_in_show_order(
    appendix_a: dict[str, Any],
) -> None:
    rig = Rig(
        appendix_a,
        bound("b8", {"kind": "midiCC", "channel": 1, "cc": 7}, {"kind": "blackout"}),
        bound("b9", {"kind": "midiCC", "channel": 1, "cc": 7}, {"kind": "pageAbs", "number": 1}),
    )
    rig.send(cc(7, 127))
    assert rig.seen() == [
        ("cc 1 7", 127, 1.0, ("master 'Grand Master'", "blackout", "page 1 'Main'"))
    ]
    assert len(rig.sink.commands) == 3


@pytest.mark.parametrize(
    "message",
    [
        mido.Message("program_change", program=5),
        mido.Message("sysex", data=[1, 2, 3]),
        mido.Message("aftertouch", value=40),
        mido.Message("start"),
        mido.Message("clock"),  # the second clock of a beat: no press, no release
    ],
)
def test_a_message_busk_cannot_bind_does_not_show(appendix_a: dict[str, Any], message: Any) -> None:
    rig = Rig(appendix_a)
    rig.send(mido.Message("clock"), mido.Message("clock"))  # a beat's press and release
    rig.send(message)
    assert [i.seq for i in rig.log.inputs] == [1, 2]


def test_the_newest_64_are_kept_and_the_sequence_goes_on(appendix_a: dict[str, Any]) -> None:
    rig = Rig(appendix_a)
    rig.send(*(cc(1, n) for n in range(70)))
    inputs = rig.log.inputs
    assert len(inputs) == INPUTS_KEPT == 64
    assert [i.seq for i in inputs] == list(range(7, 71))  # oldest first
    assert [i.raw for i in inputs] == list(range(6, 70))
    assert rig.log.inputs is inputs  # nothing new: the same object


def test_names_follow_the_show_as_it_is_when_the_input_comes(
    appendix_a: dict[str, Any],
) -> None:
    rig = Rig(appendix_a)
    rig.send(cc(7, 64))
    renamed = copy.deepcopy(rig.doc)  # a live edit makes a new document
    renamed["masters"][0]["name"] = "GM"
    renamed["surfaces"][0]["name"] = "nano"
    rig.doc = renamed
    rig.send(cc(7, 65))
    assert [(i.surface, i.drives) for i in rig.log.inputs] == [
        ("MIDI Controller", ("master 'Grand Master'",)),
        ("nano", ("master 'GM'",)),
    ]


def test_inputs_from_several_threads_each_get_their_own_number(
    appendix_a: dict[str, Any],
) -> None:
    rig = Rig(appendix_a)
    gate = threading.Barrier(4)

    def sweep(channel: int) -> None:
        gate.wait()
        for value in range(100):
            rig.send(cc(9, value, channel=channel))

    threads = [threading.Thread(target=sweep, args=(channel,)) for channel in (1, 2, 3, 4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [i.seq for i in rig.log.inputs] == list(range(337, 401))


def test_a_monitor_that_fails_is_reported_once_and_the_bindings_still_work(
    appendix_a: dict[str, Any],
) -> None:
    rig = Rig(appendix_a)

    def broken(event: object, bindings: object) -> None:
        raise RuntimeError("full")

    rig.resolver._record = broken
    rig.send(cc(0, 10), cc(0, 20))
    assert rig.reports == ["input monitor: RuntimeError: full"]
    assert len(rig.sink.commands) == 2


def test_the_log_costs_an_input_thread_little(appendix_a: dict[str, Any]) -> None:
    """A fader sweep sends about 100 messages a second: the record must not
    hold the input thread up. Measured: about 3 µs an input here."""
    rig = Rig(appendix_a)
    event = midi.translate(midi.SurfaceId(MIDI), cc(0, 64))
    assert event is not None
    binding = [cast(Any, rig.doc["bindings"][0])]
    rig.log.record(event, binding)  # the names, made once per document
    count = 20_000
    started = time.perf_counter()
    for _ in range(count):
        rig.log.record(event, binding)
    each = (time.perf_counter() - started) / count
    assert each < 100e-6, f"{each * 1e6:.1f} µs an input"


# ----------------------------------------------------------------- LiveShow


def osc_show(appendix_a: dict[str, Any], port: int) -> Show:
    """Appendix A with no MIDI surface and an OSC one on ``port``, its
    ``/fader/1`` bound to slot 1."""
    appendix_a["surfaces"] = [
        {"id": "s-touch", "name": "Touch", "kind": "osc", "match": {"port": port},
         "faderPickup": "jump"}
    ]  # fmt: skip
    appendix_a["bindings"] = [
        {"id": "b1", "surfaceId": "s-touch", "input": {"kind": "osc", "path": "/fader/1"},
         "action": {"kind": "playbackFader", "slot": 0}}
    ]  # fmt: skip
    return cast(Show, appendix_a)


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def eventually(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_a_live_show_logs_what_its_osc_surface_receives(appendix_a: dict[str, Any]) -> None:
    port = free_udp_port()
    live = LiveShow(osc_show(appendix_a, port), output=False, surfaces=True)
    assert live.inputs == ()  # nothing is open before start
    with live, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        assert live.inputs == ()
        for packet in (encode("/fader/1", 0.5), encode("/go"), encode("/x", 2.0)):
            client.sendto(packet, ("127.0.0.1", port))
        eventually(lambda: len(live.inputs) == 4)
        assert [(i.seq, i.surface, i.input, i.raw, i.value, i.drives) for i in live.inputs] == [
            (1, "Touch", 'osc "/fader/1"', None, 0.5, ("fader 1",)),
            (2, "Touch", 'osc "/go"', None, 1.0, ()),  # a bare message: a press, a release
            (3, "Touch", 'osc "/go"', None, 0.0, ()),
            (4, "Touch", 'osc "/x"', None, 1.0, ()),  # clamped, as the bindings get it
        ]
        eventually(
            lambda: live.snapshot is not None and live.snapshot.playbacks[0].faderLevel == 0.5
        )
        reply = live.execute('bind "Touch" osc "/x" master gm')
        assert reply.ok, reply.text
        eventually(lambda: live.show["bindings"][-1]["input"] == {"kind": "osc", "path": "/x"})
        client.sendto(encode("/x", 0.25), ("127.0.0.1", port))
        eventually(lambda: len(live.inputs) == 5)
        assert live.inputs[-1].drives == ("master 'Grand Master'",)
    assert len(live.inputs) == 5  # after stop, as they ended


def test_a_live_show_without_surfaces_has_no_inputs(appendix_a: dict[str, Any]) -> None:
    live = LiveShow(osc_show(appendix_a, free_udp_port()), output=False)
    with live:
        assert live.inputs == ()
    assert not hasattr(OfflineShow, "inputs")  # it opens no surface


# ------------------------------------------------------------------ busk run


@pytest.mark.parametrize("threads", [False, True], ids=["processes", "threads"])
def test_busk_runs_show_has_the_inputs_its_console_process_received(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receiver: Receiver,
    appendix_a: dict[str, Any],
    threads: bool,
) -> None:
    port = free_udp_port()
    show = tmp_path / "show.json"
    show.write_text(json.dumps(localhost_route(osc_show(appendix_a, port))))
    report = tmp_path / "report.json"
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "lines": ['bind "Touch" osc "/fader/2" fader 2'],
                "osc": {"port": port, "messages": [["/fader/1", 0.75], ["/fader/2"], ["/y", 0]]},
                "report": str(report),
            }
        )
    )
    monkeypatch.setenv("BUSK_TEST_FRONTEND", str(plan))
    options = ["--frontend", "frontend_probe:main", "--state-dir", str(tmp_path / "state")]
    if threads:
        options.append("--threads")
    with BuskRun(show, *options, "--no-log", sacn_port=receiver.port) as busk:
        assert busk.wait() == 0, busk.err
    seen = json.loads(report.read_text())
    assert seen["timeout"] is None, seen
    assert seen["inputs"] == [
        [1, "s-touch", "Touch", 'osc "/fader/1"', None, 0.75, ["fader 1"]],
        [2, "s-touch", "Touch", 'osc "/fader/2"', None, 1.0, ["fader 2"]],
        [3, "s-touch", "Touch", 'osc "/fader/2"', None, 0.0, ["fader 2"]],
        [4, "s-touch", "Touch", 'osc "/y"', None, 0.0, []],
    ]
