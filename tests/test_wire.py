"""The wire format between busk's processes (phase-7-plan §5.2, §5.3, step 6).

Framing over socket pairs (partial reads, empty and 64 MiB messages, end of
file, descriptors), raw frames, and the compiled-show codec: the engine
view, structural sharing (an unchanged cue list or rig arrives as the very
object the engine already holds), chunks, and the end-to-end check that an
engine fed through encoder → bytes → decoder makes byte-identical frames to
one fed directly, over the Phase 3 build and its undo.
"""

from __future__ import annotations

import copy
import os
import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, cast

import numpy as np
import pytest

from builders import APPENDIX_A, ROOT, busking_benchmark_rig, compile_doc, load_doc, show_of
from busk.commands.bus import CommandBus
from busk.commands.types import Command, CommandEnvelope, CommandOrigin
from busk.compiler.compile import CompiledShow, compile_show
from busk.console.console import Console
from busk.engine.clock import Clock, FakeClock
from busk.engine.install import EMPTY_FRAME, Install
from busk.engine.loop import Engine, Frame
from busk.model.show import Show
from busk.persistence.show_file import new_show
from busk.process.wire import (
    HEADER,
    Kind,
    LinkClosed,
    ShowDecoder,
    ShowEncoder,
    components,
    decode_frame,
    dumps,
    encode_frame,
    engine_view,
    loads,
    pack,
    receive,
    send,
)
from busk.session.ids import CounterIds
from busk.session.library import ProfileLibrary
from busk.session.session import Session


@pytest.fixture
def pair() -> Iterator[tuple[socket.socket, socket.socket]]:
    left, right = socket.socketpair()
    yield left, right
    left.close()
    right.close()


def in_thread(target: Any, *args: Any) -> threading.Thread:
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()
    return thread


# ------------------------------------------------------------- framing


def test_a_message_round_trips(pair: tuple[socket.socket, socket.socket]) -> None:
    left, right = pair
    send(left, Kind.COMMAND, b"hello")
    message = receive(right)
    assert message is not None
    assert (message.kind, bytes(message.payload), message.fds) == (Kind.COMMAND, b"hello", ())


def test_an_empty_message_has_an_empty_payload(pair: tuple[socket.socket, socket.socket]) -> None:
    left, right = pair
    send(left, Kind.STOP)
    send(left, Kind.HELLO, b"x")
    first, second = receive(right), receive(right)
    assert first is not None
    assert second is not None
    assert (first.kind, bytes(first.payload)) == (Kind.STOP, b"")
    assert (second.kind, bytes(second.payload)) == (Kind.HELLO, b"x")


def test_a_message_sent_in_pieces_is_read_whole(pair: tuple[socket.socket, socket.socket]) -> None:
    left, right = pair
    data = pack(Kind.SNAPSHOT, bytes(range(256)) * 4) + pack(Kind.STATS, b"next")

    def dribble() -> None:
        for start in range(0, len(data), 7):
            left.sendall(data[start : start + 7])
            time.sleep(0.0005)

    thread = in_thread(dribble)
    first, second = receive(right), receive(right)
    thread.join()
    assert first is not None
    assert second is not None
    assert (first.kind, bytes(first.payload)) == (Kind.SNAPSHOT, bytes(range(256)) * 4)
    assert (second.kind, bytes(second.payload)) == (Kind.STATS, b"next")


def test_a_64_mib_message_round_trips(pair: tuple[socket.socket, socket.socket]) -> None:
    left, right = pair
    payload = os.urandom(1024) * (64 * 1024)
    thread = in_thread(send, left, Kind.CHUNK, payload)
    message = receive(right)
    thread.join()
    assert message is not None
    assert message.kind == Kind.CHUNK
    assert len(message.payload) == 64 * 1024 * 1024
    assert message.payload == payload


def test_end_of_file_between_messages_is_none(pair: tuple[socket.socket, socket.socket]) -> None:
    left, right = pair
    send(left, Kind.STOP)
    left.close()
    assert receive(right) is not None
    assert receive(right) is None


@pytest.mark.parametrize("cut", [2, HEADER.size + 3])  # in the header; in the payload
def test_end_of_file_mid_message_raises(
    pair: tuple[socket.socket, socket.socket], cut: int
) -> None:
    left, right = pair
    left.sendall(pack(Kind.COMMAND, b"0123456789")[:cut])
    left.close()
    with pytest.raises(LinkClosed):
        receive(right)


def test_end_of_file_before_the_payload_raises(pair: tuple[socket.socket, socket.socket]) -> None:
    left, right = pair
    left.sendall(pack(Kind.COMMAND, b"0123456789")[: HEADER.size])
    left.close()
    with pytest.raises(LinkClosed):
        receive(right)


def test_a_descriptor_travels_with_its_message(pair: tuple[socket.socket, socket.socket]) -> None:
    left, right = pair
    near, far = socket.socketpair()
    send(left, Kind.HELLO, b"before")
    send(left, Kind.ATTACH, b"start", fds=[far.fileno()])
    far.close()
    before, attach = receive(right), receive(right)
    assert before is not None
    assert attach is not None
    assert before.fds == ()
    assert (attach.kind, bytes(attach.payload), len(attach.fds)) == (Kind.ATTACH, b"start", 1)
    received = socket.socket(fileno=attach.fds[0])
    near.sendall(b"through")
    assert received.recv(16) == b"through"
    received.close()
    near.close()


def test_pickles_carry_read_only_mappings_and_arrays() -> None:
    array = np.arange(4.0)
    array.flags.writeable = False
    loaded = loads(dumps({"proxy": MappingProxyType({"a": 1}), "array": array}))
    assert isinstance(loaded["proxy"], MappingProxyType)
    assert dict(loaded["proxy"]) == {"a": 1}
    assert not loaded["array"].flags.writeable
    assert loaded["array"].tolist() == [0.0, 1.0, 2.0, 3.0]


def test_an_envelope_round_trips() -> None:
    envelope = CommandEnvelope(
        id="7", issuedAt=1.5, origin=CommandOrigin(), command=cast(Command, {"type": "GO"})
    )
    assert loads(dumps(envelope)) == envelope


# ------------------------------------------------------------- frames


def test_a_frame_round_trips_with_its_header(pair: tuple[socket.socket, socket.socket]) -> None:
    left, right = pair
    compiled = compile_doc(load_doc(APPENDIX_A))
    frame = Frame(
        seq=12345678901,
        time=42.25,
        universes=(bytes(range(256)) * 2, bytes(512)),
        compiled=compiled,
        layout=compiled.layout,
        outputEnabled=False,
    )
    send(left, Kind.FRAME, encode_frame(frame, 3))
    message = receive(right)
    assert message is not None
    assert message.kind == Kind.FRAME
    decoded = decode_frame(message.payload, {3: compiled.layout})
    assert (decoded.seq, decoded.time, decoded.universes) == (frame.seq, 42.25, frame.universes)
    assert decoded.layout is compiled.layout
    assert decoded.outputEnabled is False
    assert decoded.compiled is None
    assert all(type(universe) is bytes for universe in decoded.universes)


def test_a_frame_of_the_wrong_size_is_refused() -> None:
    payload = encode_frame(Frame(seq=1, time=0.0, universes=(bytes(512),)), 0)
    with pytest.raises(ValueError, match="cannot be"):
        decode_frame(payload[:-1], {})


# ------------------------------------------------------------- the codec


def appendix() -> tuple[Show, CompiledShow]:
    show = show_of(load_doc(APPENDIX_A))
    return show, compile_show(show)


def edit_list(show: Show, index: int) -> Show:
    """A copy-on-write edit of one cue list's name, as a live edit makes it."""
    lists = list(show["cueLists"])
    edited = copy.deepcopy(lists[index])
    edited["name"] = "edited"
    lists[index] = edited
    return cast(Show, {**show, "cueLists": lists})


def roundtrip(encoder: ShowEncoder, decoder: ShowDecoder, install: Install) -> Install:
    """Encode, then feed every chunk; only the last one completes the install."""
    chunks = encoder.encode(install)
    for chunk in chunks[:-1]:
        assert decoder.feed(chunk) is None
    result = decoder.feed(chunks[-1])
    assert result is not None
    return result


def install(compiled: CompiledShow, remap: Any = None) -> Install:
    return Install(compiled=compiled, remap=remap, programmer=EMPTY_FRAME)


def test_the_engine_view_drops_what_the_engine_never_reads() -> None:
    _, compiled = appendix()
    view = engine_view(compiled)
    assert compiled.channels
    assert compiled.memo is not None
    assert (view.channels, view.memo, view.warnings) == ((), None, ())
    assert view.slots.slots == ()
    assert dict(view.slots.byKey) == {}
    assert view.slots.keys == tuple(compiled.slots.byKey) != ()
    assert view.slots.defaultFrame is compiled.slots.defaultFrame
    assert view.plan is compiled.plan
    assert view.cueLists is compiled.cueLists
    assert engine_view(compiled) is view  # memoised by identity


def test_shows_that_share_a_slot_table_share_its_view() -> None:
    show, compiled = appendix()
    edited = compile_show(edit_list(show, 0), previous=compiled)
    assert edited.slots is compiled.slots
    assert engine_view(edited).slots is engine_view(compiled).slots


def test_the_first_install_is_the_rig_then_each_list_then_the_install() -> None:
    _, compiled = appendix()
    chunks = ShowEncoder().encode(install(compiled))
    assert len(chunks) == 1 + len(compiled.cueLists) + 1
    decoder = ShowDecoder()
    result = None
    for chunk in chunks:
        result = decoder.feed(chunk)
    assert result is not None
    assert result.compiled is not None
    received = result.compiled
    assert isinstance(received.cueLists, MappingProxyType)  # no MappingProxyType failure
    assert isinstance(received.playbacks, MappingProxyType)
    # In-install references resolve: each playback's list is the list sent before it.
    for playback in received.playbacks.values():
        assert playback.cueList is received.cueLists[playback.cueList.id]
    assert received.layout == compiled.layout
    assert received.slots.keys == compiled.slots.keys
    assert not received.baseImages.flags.writeable


def test_an_unchanged_list_and_rig_arrive_as_the_same_objects() -> None:
    show, compiled = appendix()
    encoder, decoder = ShowEncoder(), ShowDecoder()
    first = roundtrip(encoder, decoder, install(compiled)).compiled
    edited = compile_show(edit_list(show, 1), previous=compiled)
    chunks = encoder.encode(install(edited))
    assert len(chunks) == 2  # the edited list, then the install
    result = None
    for chunk in chunks:
        result = decoder.feed(chunk)
    assert result is not None
    assert result.compiled is not None
    assert first is not None
    second = result.compiled
    assert second.slots is first.slots
    assert second.plan is first.plan
    assert second.baseImages is first.baseImages
    assert second.layout is first.layout
    ids = list(compiled.cueLists)
    assert second.cueLists[ids[0]] is first.cueLists[ids[0]]  # unchanged: the same object
    assert second.cueLists[ids[1]] is not first.cueLists[ids[1]]  # edited: a new one
    for playback in second.playbacks.values():
        assert playback.cueList is second.cueLists[playback.cueList.id]


def test_a_seeded_encoder_and_decoder_share_the_show_both_ends_hold() -> None:
    """A restarted console whose show has the engine's stamp (decision 8):
    its encoder and the engine's decoder for the new link start from that
    show, so an edit sends only what changed, and the rest arrives as the
    engine's own objects (the live swap compares by identity)."""
    show, compiled = appendix()
    held = roundtrip(ShowEncoder(), ShowDecoder(), install(compiled)).compiled  # the engine's
    assert held is not None
    recovered = compile_show(show)  # the new console's: equal, but other objects
    assert recovered.slots is not compiled.slots
    encoder, decoder = ShowEncoder(recovered), ShowDecoder(held)
    edited = compile_show(edit_list(show, 1), previous=recovered)
    chunks = encoder.encode(install(edited))
    assert len(chunks) == 2  # the edited list, then the install
    assert decoder.feed(chunks[0]) is None
    result = decoder.feed(chunks[1])
    assert result is not None
    assert result.compiled is not None
    second = result.compiled
    assert second.slots is held.slots
    assert second.plan is held.plan
    assert second.layout is held.layout
    ids = list(compiled.cueLists)
    assert second.cueLists[ids[0]] is held.cueLists[ids[0]]
    assert second.cueLists[ids[1]] is not held.cueLists[ids[1]]
    for playback in second.playbacks.values():
        assert playback.cueList is second.cueLists[playback.cueList.id]


def test_a_programmer_only_install_and_a_resent_show_are_one_chunk() -> None:
    _, compiled = appendix()
    encoder, decoder = ShowEncoder(), ShowDecoder()
    first = roundtrip(encoder, decoder, install(compiled)).compiled
    only = encoder.encode(Install(compiled=None, remap=None, programmer=EMPTY_FRAME))
    assert len(only) == 1
    result = decoder.feed(only[0])
    assert result is not None
    assert result.compiled is None
    again = encoder.encode(install(compiled))
    assert len(again) == 1
    result = decoder.feed(again[0])
    assert result is not None
    assert result.compiled is first


def test_a_repatch_sends_a_new_rig_and_the_remap() -> None:
    show, compiled = appendix()
    encoder, decoder = ShowEncoder(), ShowDecoder()
    first = roundtrip(encoder, decoder, install(compiled)).compiled
    fixtures = list(show["fixtures"])
    fixtures[0] = {**fixtures[0], "patch": None}
    repatched = compile_show(cast(Show, {**show, "fixtures": fixtures}), previous=compiled)
    remap = np.arange(len(compiled.slots.slots), dtype=np.int32)
    result = roundtrip(encoder, decoder, install(repatched, remap))
    assert result.compiled is not None
    assert first is not None
    assert result.compiled.slots is not first.slots
    assert result.compiled.plan is not first.plan
    assert result.remap is not None
    assert result.remap.tolist() == remap.tolist()
    assert components(result.compiled).keys() == components(engine_view(repatched)).keys()


# ------------------------------------------------------------- the Phase 3 build, both ways

NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)
CID = "0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f"


class Tee(CommandBus):
    """Engine A's bus, which also feeds engine B as a link would: envelopes
    pickled, installs through the codec (bytes in between)."""

    def __init__(self, compiled: CompiledShow, clock: Clock) -> None:
        super().__init__(compiled, clock)
        self.encoder, self.decoder = ShowEncoder(), ShowDecoder()
        self.other: CommandBus | None = None
        self.chunks = 0

    def submit(self, command: Command, origin: CommandOrigin | None = None) -> CommandEnvelope:
        envelope = super().submit(command, origin)
        assert self.other is not None
        self.other.enqueue(loads(dumps(envelope)))
        return envelope

    def install(self, item: Install) -> None:
        super().install(item)
        assert self.other is not None
        self.other.install(self.through(item))

    def through(self, item: Install) -> Install:
        result = None
        for chunk in self.encoder.encode(item):
            assert result is None
            result = self.decoder.feed(bytes(chunk))
            self.chunks += 1
        assert result is not None
        return result


def test_the_phase_3_build_and_its_undo_give_the_same_frames_through_the_codec() -> None:
    ids = CounterIds()
    template = new_show("Club Night", ids=ids, now=NOW, cid=CID)
    compiled = compile_show(template)
    clock = FakeClock()
    direct = Engine(compiled, clock)
    tee = Tee(compiled, clock)
    direct.bus = tee
    first = tee.through(install(compiled))
    assert first.compiled is not None
    remote = Engine(first.compiled, clock)
    tee.other = remote.bus
    session = Session(template, tee, compiled=compiled, ids=ids, wall_clock=lambda: NOW)
    console = Console(session, ProfileLibrary())
    now = 0.0

    def step(line: str) -> None:
        nonlocal now
        reply = console.execute(line)
        assert reply.ok, (line, reply.text)
        for _ in range(3):  # three ticks per step, so fades run in between
            now += 0.2
            clock.sleep_until(now)
            direct.tick(now)
            remote.tick(now)
            assert direct.latest is not None
            assert remote.latest is not None
            assert remote.latest.universes == direct.latest.universes, (line, now)

    script = (ROOT / "examples" / "phase3-build.busk").read_text(encoding="utf-8").splitlines()
    lines = [line for line in script if line.strip() and not line.lstrip().startswith("#")]
    assert len(lines) >= 120
    for line in lines:
        if line.strip() != "save":
            step(line)
    for line in ("fader 1 1", "fader 3 1", "go 2", "blackout on", "blackout off"):
        step(line)
    lit = sum(any(universe) for universe in direct.latest.universes) if direct.latest else 0
    assert lit  # the comparison saw a lit stage
    for _ in range(session.timeline.undo_count):
        step("undo")
    assert tee.chunks > len(lines)


# ------------------------------------------------------------- the reference rig


@pytest.mark.perf
def test_no_chunk_of_the_reference_rig_takes_over_5_ms_to_load() -> None:
    compiled = compile_doc(busking_benchmark_rig())
    chunks = ShowEncoder().encode(install(compiled))
    best = [float("inf")] * len(chunks)
    for _ in range(5):
        decoder = ShowDecoder()
        for k, chunk in enumerate(chunks):
            started = time.perf_counter()
            decoder.feed(chunk)
            best[k] = min(best[k], time.perf_counter() - started)
    sizes = [len(chunk) for chunk in chunks]
    print(
        f"\nreference rig install: {len(chunks)} chunks, {sum(sizes) / 1e6:.1f} MB; "
        f"slowest chunk {max(best) * 1000:.2f} ms ({sizes[best.index(max(best))] / 1e6:.2f} MB)"
    )
    assert max(best) < 0.005
