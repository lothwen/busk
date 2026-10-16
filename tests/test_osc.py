"""OSC (phase-6-plan §5.11, decision 14): the codec, value mapping, the
surface's socket, a localhost round trip to the bus, and feedback.

The golden packets are the two examples of the OSC 1.0 specification.
Network tests use 127.0.0.1 and ephemeral ports only.
"""

from __future__ import annotations

import math
import socket
import struct
import time
from collections.abc import Iterator
from typing import Any, cast

import pytest

from builders import APPENDIX_A, compile_doc, load_doc
from busk.commands.bus import CommandBus
from busk.commands.types import Command
from busk.engine.clock import FakeClock
from busk.io.bindings import BindingResolver
from busk.io.events import InputEvent
from busk.io.feedback import FeedbackWorker
from busk.io.osc import BUNDLE, MAX_DEPTH, OscArg, OscError, OscSurface, decode, encode, values
from busk.io.surfaces import SurfaceManager
from busk.model.show import Show
from busk.model.surface import ControlSurface, InputAddress
from harness import Harness

# OSC 1.0 specification, "Examples": the two messages and their bytes.
FREQUENCY = bytes.fromhex(
    "2f6f7363 696c6c61 746f722f 342f6672 65717565 6e637900 2c660000 43dc0000".replace(" ", "")
)
FOO = bytes.fromhex(
    "2f666f6f 00000000 2c696973 66660000 000003e8 ffffffff 68656c6c 6f000000"
    " 3f9df3b6 40b5b22d".replace(" ", "")
)


def bundle(*elements: bytes) -> bytes:
    """A bundle with the "immediately" time tag."""
    sized = b"".join(struct.pack(">i", len(element)) + element for element in elements)
    return BUNDLE + struct.pack(">Q", 1) + sized


# ------------------------------------------------------------------- codec


def test_the_specification_examples_encode() -> None:
    assert encode("/oscillator/4/frequency", 440.0) == FREQUENCY
    assert encode("/foo", 1000, -1, "hello", 1.234, 5.678) == FOO


def test_the_specification_examples_decode() -> None:
    assert decode(FREQUENCY) == [("/oscillator/4/frequency", (440.0,))]
    [(address, args)] = decode(FOO)
    assert (address, args[:3]) == ("/foo", (1000, -1, "hello"))
    assert args[3:] == (pytest.approx(1.234), pytest.approx(5.678))  # float32


def test_every_type_tag() -> None:
    packet = (
        b"/all\0\0\0\0,ifdhsbTFNI\0"
        + struct.pack(">i", 7) + struct.pack(">f", 0.5) + struct.pack(">d", 0.1)
        + struct.pack(">q", 2**40) + b"hi\0\0" + struct.pack(">i", 3) + b"\1\2\3\0"
    )  # fmt: skip
    assert decode(packet) == [
        ("/all", (7, 0.5, 0.1, 2**40, "hi", b"\1\2\3", True, False, None, None))
    ]


@pytest.mark.parametrize(
    "args",
    [(), (1, -2), (0.25,), ("",), ("abc",), ("abcd",), (b"",), (b"\xff" * 5,), (True, False, None)],
)
def test_encode_round_trips(args: tuple[OscArg, ...]) -> None:
    packet = encode("/x/y", *args)
    assert len(packet) % 4 == 0
    assert decode(packet) == [("/x/y", args)]


def test_booleans_and_nil_have_no_payload() -> None:
    """``True == 1`` in Python, so round trips cannot tell ``T`` from ``i``."""
    assert encode("/t", True, False, None) == b"/t\0\0,TFN\0\0\0\0"


def test_a_message_without_type_tags_has_no_arguments() -> None:
    assert decode(b"/go\0") == [("/go", ())]


def test_bundles_inside_bundles_keep_their_order() -> None:
    packet = bundle(bundle(encode("/a", 1), encode("/b", 2)), encode("/c", 3), bundle())
    assert decode(packet) == [("/a", (1,)), ("/b", (2,)), ("/c", (3,))]


def test_a_message_with_an_unknown_type_tag_is_dropped() -> None:
    rgba = b"/color\0\0,r\0\0\x01\x02\x03\x04"
    assert decode(rgba) == []
    assert decode(bundle(rgba, encode("/ok", 1))) == [("/ok", (1,))]


def nested(depth: int) -> bytes:
    packet = encode("/deep")
    for _ in range(depth):
        packet = bundle(packet)
    return packet


@pytest.mark.parametrize(
    "packet",
    [
        b"",
        b"foo\0",
        b"/foo",  # unterminated address
        b"/foo\0\0\0\0x\0\0\0",  # no comma
        b"/foo\0\0\0\0,i\0\0\0\0",  # a truncated int
        b"/foo\0\0\0\0,d\0\0\0\0\0\0\0\0",  # a truncated double
        b"/foo\0\0\0\0,s\0\0abc",  # an unterminated string
        b"/foo\0\0\0\0,b\0\0" + struct.pack(">i", 8) + b"1234",  # a blob past the end
        b"/foo\0\0\0\0,b\0\0" + struct.pack(">i", -1),
        b"/f\xffo\0\0\0\0\0",  # not UTF-8
        b"#bundle\0\0\0\0\0",  # a truncated time tag
        b"#bundlx\0" + bytes(8),
        BUNDLE + bytes(8) + struct.pack(">i", 12) + encode("/a"),  # an element past the end
        BUNDLE + bytes(8) + b"\0\0",  # a truncated element size
        nested(MAX_DEPTH + 1),
    ],
)
def test_malformed_packets_raise_osc_errors(packet: bytes) -> None:
    with pytest.raises(OscError):
        decode(packet)


def test_nesting_up_to_the_limit_decodes() -> None:
    assert decode(nested(MAX_DEPTH)) == [("/deep", ())]


# ------------------------------------------------------------ value mapping


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ((), (1.0, 0.0)),  # a bare message: press and release
        ((None,), (1.0, 0.0)),
        ((True,), (1.0,)),
        ((False,), (0.0,)),
        ((0.5,), (0.5,)),
        ((0.25, "label"), (0.25,)),  # the first argument only
        ((2,), (1.0,)),
        ((1,), (1.0,)),
        ((0,), (0.0,)),
        ((-3.0,), (0.0,)),
        ((math.inf,), (1.0,)),
        ((math.nan,), ()),
        (("text",), ()),
        ((b"blob",), ()),
    ],
)
def test_values(args: tuple[OscArg, ...], expected: tuple[float, ...]) -> None:
    assert values(args) == expected


# ------------------------------------------------------------- the surface


def osc_surface(port: int, **match: Any) -> ControlSurface:
    return cast(
        ControlSurface,
        {"id": "s-osc", "name": "Phone", "kind": "osc", "match": {"port": port, **match},
         "faderPickup": "jump"},
    )  # fmt: skip


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


@pytest.fixture
def client() -> Iterator[socket.socket]:
    """A UDP socket on an ephemeral localhost port, as a phone app would be."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(2.0)
    yield sock
    sock.close()


@pytest.fixture
def opened() -> Iterator[list[OscSurface]]:
    """Surfaces to close after the test."""
    surfaces: list[OscSurface] = []
    yield surfaces
    for surface in surfaces:
        surface.close()


def listen(opened: list[OscSurface], events: list[InputEvent], **match: Any) -> OscSurface:
    surface = OscSurface(osc_surface(0, **match), events.append)
    assert surface.open() is None
    opened.append(surface)
    return surface


def wait_for(condition: Any, timeout: float = 2.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.005)


def test_datagrams_become_events_and_malformed_ones_are_counted() -> None:
    events: list[InputEvent] = []
    surface = OscSurface(osc_surface(0), events.append)  # not opened: no feedback to follow
    source = ("127.0.0.1", 9)
    surface.datagram(encode("/1/fader1", 0.75), source)
    surface.datagram(bundle(encode("/go"), encode("/1/toggle1", True)), source)
    surface.datagram(b"/bad", source)
    surface.datagram(encode("/name", "text"), source)  # nothing to act on
    assert [(e.surfaceId, e.address, e.value) for e in events] == [
        ("s-osc", {"kind": "osc", "path": "/1/fader1"}, 0.75),
        ("s-osc", {"kind": "osc", "path": "/go"}, 1.0),
        ("s-osc", {"kind": "osc", "path": "/go"}, 0.0),
        ("s-osc", {"kind": "osc", "path": "/1/toggle1"}, 1.0),
    ]
    assert (surface.malformed, surface.errors) == (1, 0)
    assert surface.feedback is None


def test_a_failing_handler_is_counted() -> None:
    def broken(event: InputEvent) -> None:
        raise RuntimeError("bug")

    surface = OscSurface(osc_surface(0), broken)
    surface.datagram(encode("/go"), ("127.0.0.1", 9))
    assert surface.errors == 2


def test_a_taken_port_cannot_listen(client: socket.socket) -> None:
    port = client.getsockname()[1]
    surface = OscSurface(osc_surface(port), lambda event: None)
    assert surface.open() == f"cannot listen on udp {port}: Address already in use"
    surface.close()


def test_an_unknown_feedback_host_cannot_open(monkeypatch: pytest.MonkeyPatch) -> None:
    def unknown(host: str) -> str:
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(socket, "gethostbyname", unknown)
    surface = OscSurface(osc_surface(0, host="console.local"), lambda event: None)
    assert surface.open() == (
        "cannot resolve feedback host 'console.local': [Errno -2] Name or service not known"
    )


@pytest.mark.parametrize(
    ("match", "target"),
    [
        ({}, "the sender"),
        ({"feedbackPort": 9000}, "the sender at port 9000"),
        ({"host": "127.0.0.1"}, "127.0.0.1 at the sender's port"),
        ({"host": "127.0.0.1", "feedbackPort": 9000}, "127.0.0.1:9000"),
    ],
)
def test_describe(opened: list[OscSurface], match: dict[str, Any], target: str) -> None:
    surface = listen(opened, [], **match)
    assert surface.describe() == f"listening on udp {surface.port}, feedback to {target}"


def test_messages_over_udp_and_feedback_to_the_sender(
    opened: list[OscSurface], client: socket.socket
) -> None:
    events: list[InputEvent] = []
    surface = listen(opened, events)
    assert surface.feedback is None  # nowhere to send yet
    client.sendto(encode("/1/fader1", 0.5), ("127.0.0.1", surface.port))
    wait_for(lambda: events)
    assert (events[0].address, events[0].value) == ({"kind": "osc", "path": "/1/fader1"}, 0.5)
    feedback = surface.feedback
    assert feedback is not None
    assert feedback.destination == client.getsockname()
    label = cast(InputAddress, {"kind": "osc", "path": "/1/label1"})
    feedback.send(label, "display", "Song")
    data, source = client.recvfrom(1024)
    assert decode(data) == [("/1/label1", ("Song",))]
    assert source[1] == surface.port  # from the port the client sends to
    feedback.send(cast(InputAddress, {"kind": "midiCC", "channel": 1, "cc": 1}), "led", 1.0)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other:  # a second phone
        other.bind(("127.0.0.1", 0))
        other.sendto(encode("/go"), ("127.0.0.1", surface.port))
        wait_for(lambda: len(events) == 3)
        moved = surface.feedback
        assert moved is not None
        assert moved is not feedback  # a new sender: the feedback worker sends everything
        assert moved.destination == other.getsockname()
    surface.close()
    surface.close()  # idempotent
    assert surface.feedback is None
    feedback.send(label, "display", "late")  # closed: nothing, no error
    client.settimeout(0.1)
    with pytest.raises(TimeoutError):
        client.recvfrom(1024)  # neither the MIDI address nor the late label was sent


def test_feedback_to_a_configured_host_and_port(
    opened: list[OscSurface], client: socket.socket
) -> None:
    receiver = client.getsockname()[1]
    surface = listen(opened, [], host="127.0.0.1", feedbackPort=receiver)
    feedback = surface.feedback
    assert feedback is not None  # known from the start
    feedback.send(cast(InputAddress, {"kind": "osc", "path": "/led"}), "led", 1.0)
    data, _ = client.recvfrom(1024)
    assert decode(data) == [("/led", (1.0,))]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other:  # input from elsewhere
        other.sendto(encode("/go"), ("127.0.0.1", surface.port))
        time.sleep(0.05)
    assert surface.feedback is feedback  # the destination stays


def test_half_configured_feedback_follows_the_sender(
    opened: list[OscSurface], client: socket.socket
) -> None:
    events: list[InputEvent] = []
    by_port = listen(opened, events, feedbackPort=9000)
    by_host = listen(opened, events, host="127.0.0.2")  # not the sender's address
    for surface in (by_port, by_host):
        client.sendto(encode("/go"), ("127.0.0.1", surface.port))
    wait_for(lambda: len(events) == 4)
    port = client.getsockname()[1]
    assert by_port.feedback is not None
    assert by_port.feedback.destination == ("127.0.0.1", 9000)
    assert by_host.feedback is not None
    assert by_host.feedback.destination == ("127.0.0.2", port)


# ------------------------------------------------------- through the show


def show_with_osc(port: int) -> dict[str, Any]:
    doc = load_doc(APPENDIX_A)
    doc["surfaces"].append(osc_surface(port))
    doc["bindings"] += [
        {"id": "o-fader", "surfaceId": "s-osc", "input": {"kind": "osc", "path": "/1/fader1"},
         "action": {"kind": "playbackFader", "slot": 0},
         "feedback": {"kind": "display", "address": {"kind": "osc", "path": "/1/label1"}}},
        {"id": "o-go", "surfaceId": "s-osc", "input": {"kind": "osc", "path": "/go"},
         "action": {"kind": "playbackButton", "slot": 0, "button": 0}},
    ]  # fmt: skip
    return doc


def test_a_message_reaches_the_bus_through_a_binding(
    client: socket.socket, capsys: pytest.CaptureFixture[str]
) -> None:
    port = free_port()
    doc = show_with_osc(port)
    compiled = compile_doc(doc)
    bus = CommandBus(compiled, FakeClock())
    resolver = BindingResolver(cast(Show, doc), compiled, bus)
    manager = SurfaceManager(resolver.handle)
    manager.reconcile(compiled)
    try:
        out = capsys.readouterr().out
        assert f"OSC s-osc: listening on udp {port}, feedback to the sender\n" in out
        assert manager.senders() == {}
        commands: list[Command] = []

        def drained(count: int) -> bool:
            commands.extend(envelope["command"] for envelope in bus.drain())
            return len(commands) >= count

        client.sendto(encode("/1/fader1", 0.75), ("127.0.0.1", port))
        wait_for(lambda: drained(1))
        client.sendto(encode("/go"), ("127.0.0.1", port))
        wait_for(lambda: drained(3))
        assert commands == [
            {"type": "SET_FADER", "slot": 0, "level": 0.75},
            {"type": "PLAYBACK_BUTTON", "slot": 0, "button": 0, "down": True},
            {"type": "PLAYBACK_BUTTON", "slot": 0, "button": 0, "down": False},
        ]
        senders = manager.senders()
        assert list(senders) == ["s-osc"]
        assert senders["s-osc"].destination == client.getsockname()

        # The feedback worker sends the label to the phone.
        harness = Harness(compiled)
        snapshot = harness.tick(0.0).snapshot
        worker = FeedbackWorker(
            lambda: compiled, lambda: snapshot, resolver.lastInput, senders=manager.senders
        )
        worker.service(0.0)
        data, _ = client.recvfrom(1024)
        assert decode(data) == [("/1/label1", ("Song",))]
    finally:
        manager.close()
    assert manager.senders() == {}


def test_the_manager_reports_a_taken_port(
    client: socket.socket, capsys: pytest.CaptureFixture[str]
) -> None:
    port = client.getsockname()[1]
    manager = SurfaceManager(lambda event: None)
    manager.reconcile(compile_doc(show_with_osc(port)))
    manager.close()
    assert f"OSC s-osc: cannot listen on udp {port}: Address already in use\n" in (
        capsys.readouterr().err
    )
