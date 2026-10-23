"""Links between busk's processes: framing, message kinds, raw frames and
the compiled-show codec (phase-7-plan §5.2, §5.3).

**Framing.** Every message on a link is a header, ``struct "<IB"``: the
length of the payload and its :class:`Kind`. The payload follows: a pickle,
or for :attr:`Kind.FRAME` a fixed header and the raw universes
(:func:`encode_frame`). A message may carry file descriptors (the root hands
out link ends with :attr:`Kind.ATTACH`); they travel as ``SCM_RIGHTS`` with
the message's first byte. :func:`receive` reads exactly one message and
never past it, so descriptors always arrive with the message they belong to.

**Pickle is used only between busk's own processes**, over socket pairs the
root made, which nothing outside the process tree can reach (decision 2).
The web remote and OSC stay JSON and OSC: nothing from the network is ever
unpickled. :func:`dumps` also handles the read-only mappings
(``MappingProxyType``) compiled objects use, which plain pickle refuses.

**The compiled-show codec** (decision 3). Installs travel as chunks:

* **The engine view** (:func:`engine_view`). A compiled show is sent
  without what the engine never reads: its compiled channels, its compile
  memo, its warnings, and the slot table's per-slot records and key map
  (the table keeps its arrays and :attr:`~busk.compiler.slots.SlotTable.keys`).
  Views are memoised by identity, so the same compiled show always gives the
  same view object, and a slot table that two shows share gives one view.
* **Structural sharing.** :func:`components` names the objects installs
  share: the show, its rig (slot table, conversion plan, base images,
  universes, output layout) and each compiled cue list, keyed by path. A
  :class:`ShowEncoder` sends any object that *is* one of the components of
  the previous show it sent as that component's token; the
  :class:`ShowDecoder` resolves the token to the object it decoded then. An
  edit therefore sends only what the incremental compile changed, and the
  engine sees an unchanged cue list as the very same object, which its live
  swap relies on (a re-pointed playback compares cue lists by identity).
* **Chunks.** A changed rig is one chunk and each changed cue list another;
  the last chunk is the :class:`~busk.engine.install.Install` itself, whose
  playbacks reference the cue lists sent before it by ``("new", k)``
  tokens. The decoder loads one chunk per call, so the engine's link thread
  can yield between chunks and no single load holds the GIL for long.
"""

from __future__ import annotations

import array
import contextlib
import io
import pickle
import socket
import struct
import threading
import weakref
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import IntEnum
from types import MappingProxyType
from typing import IO, Any, Final

import numpy as np
from numpy.typing import NDArray

from busk.compiler.compile import CompiledShow, OutputLayout
from busk.compiler.readout import EMPTY_READOUT
from busk.compiler.slots import SlotTable
from busk.convert.dmx import UNIVERSE_SIZE
from busk.engine.install import Install
from busk.engine.loop import EngineStats, Frame
from busk.engine.snapshot import EngineSnapshot

__all__ = [
    "FRAME_HEADER",
    "HEADER",
    "Attach",
    "Endpoint",
    "EngineReport",
    "Hello",
    "Kind",
    "LinkClosed",
    "Message",
    "ShowDecoder",
    "ShowEncoder",
    "Welcome",
    "components",
    "decode_frame",
    "dumps",
    "encode_frame",
    "engine_view",
    "loads",
    "pack",
    "receive",
    "send",
]

HEADER: Final = struct.Struct("<IB")
"""Every message's header: the payload's length, and its :class:`Kind`."""

FRAME_HEADER: Final = struct.Struct("<QdIH?")
"""A frame's header: seq, engine time, layout id, universe count, output enabled."""

PROTOCOL: Final = 5
"""The pickle protocol: read-only NumPy arrays come back read-only."""

MAX_FDS: Final = 4
"""The most descriptors one message may carry."""

_ANCILLARY: Final = (
    socket.CMSG_SPACE(MAX_FDS * array.array("i").itemsize) if hasattr(socket, "CMSG_SPACE") else 0
)

type Token = tuple[str | int, ...]
"""A shared object's name on a link: ``("rig", "slots")``, ``("list",
cueListId)``, ``("new", k)`` for the k-th object of the current install."""


class Kind(IntEnum):
    """What a message is (phase-7-plan §5.2).

    Root ↔ engine and root ↔ console are *control* links; console ↔ engine
    is *the link*. Payloads are pickles unless noted.
    """

    # control link, engine → root
    LAYOUT = 1  # (layout id, OutputLayout): before the first frame made with it
    FRAME = 2  # raw: FRAME_HEADER, then 512 bytes per universe
    STATS = 3  # EngineStats, every second (to the console too)
    FINAL = 4  # EngineStats, at exit
    LOG = 5  # event-log records, batched: a list of (time, envelope | cause | Restore)
    # control links, root → engine and console
    ATTACH = 10  # a link end (one descriptor), and why
    STOP = 11  # to the engine, at shutdown
    ENGINE = 12  # to the console: the watchdog's news (stalled, restarting, failed)
    READY = 13  # from the console: its command loop runs (--duration counts from here)
    PROCESSES = 14  # to the console: the pids and restarts of the run (for `info`)
    ROUTES = 15  # to the console: the output routes' RouteStatus tuple, when it changed
    # the link, console → engine
    HELLO = 20  # the console's session id; restarted or not
    COMMAND = 21  # a CommandEnvelope
    CHUNK = 22  # an install chunk (ShowEncoder)
    INSTALL = 23  # an install's last chunk, which commits it
    RESTORE = 24  # an EngineSnapshot to restore after an engine restart
    SYNC = 26  # a token: answer SYNCED once everything sent before is applied
    # the link, engine → console
    WELCOME = 30  # fresh or not, show stamp, current snapshot
    SNAPSHOT = 31  # an EngineSnapshot, when the published one changes
    SYNCED = 32  # the newest SYNC token applied, after the snapshot that shows it


class LinkClosed(EOFError):
    """The link ended in the middle of a message."""


@dataclass(frozen=True, slots=True)
class Message:
    """One message as read from a link, with the descriptors it carried."""

    kind: Kind
    payload: bytes | bytearray
    fds: tuple[int, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Attach:
    """:attr:`Kind.ATTACH` from the root: a new link end comes with it. To
    the console, ``reason`` says why (``"start"``, ``"engine restarted:
    killed by signal 9"``) and ``restore`` whether to restore the last
    snapshot into a fresh engine (decision 5: not after a crash loop)."""

    reason: str = "start"
    restore: bool = True


@dataclass(frozen=True, kw_only=True)
class Processes:
    """:attr:`Kind.PROCESSES` from the root, whenever one of its fields
    changes: the pids of the root and the engine (``None`` once the watchdog
    gave the engine up), the restarts so far and the event log's file
    (``None`` until it opens, or with ``--no-log``), which the console's
    ``info`` shows."""

    root: int
    engine: int | None
    engineRestarts: int = 0
    consoleRestarts: int = 0
    eventLog: str | None = None


@dataclass(frozen=True, kw_only=True)
class Hello:
    """:attr:`Kind.HELLO`, the console's first message on a link.

    ``base`` is the ``busk run --values`` base frame (the logical frame
    uncontrolled slots output), against the slots of the show the console
    installs first; a fresh engine builds its :class:`~busk.engine.loop.Engine`
    with it. An engine that already runs ignores it."""

    sessionId: str
    restarted: bool = False
    base: NDArray[np.float64] | None = None


@dataclass(frozen=True, kw_only=True)
class Welcome:
    """:attr:`Kind.WELCOME`, the engine's answer to :class:`Hello`.

    ``fresh``: the engine has no show yet, so the console sends its whole
    state. Otherwise ``snapshot`` is the running engine's state, which a
    restarted console adopts, and ``stamp`` the stamp of the show it runs
    (decision 8; ``None`` if that show came unstamped). The engine's
    decoder for the link is then seeded with that show
    (:class:`ShowDecoder`)."""

    fresh: bool
    stamp: tuple[str, int] | None = None
    snapshot: EngineSnapshot | None = None


@dataclass(frozen=True, kw_only=True)
class EngineReport:
    """:attr:`Kind.STATS` and :attr:`Kind.FINAL`: the engine's counters, its
    longest garbage-collection pause in seconds, and its process id."""

    stats: EngineStats
    gcPause: float = 0.0
    pid: int = 0


class Endpoint:
    """One end of a link: its socket, and the lock that serialises writers
    (§5.2), so messages from several threads never interleave. One thread
    reads it."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self._lock = threading.Lock()

    def send(self, kind: Kind, payload: bytes = b"", fds: Sequence[int] = ()) -> None:
        """Write one message (see :func:`send`)."""
        with self._lock:
            send(self.sock, kind, payload, fds)

    def send_install(self, chunks: Sequence[bytes]) -> None:
        """Write an install's chunks (:meth:`ShowEncoder.encode`) without
        anything in between: :attr:`Kind.CHUNK` s, then the committing
        :attr:`Kind.INSTALL`."""
        with self._lock:
            for chunk in chunks[:-1]:
                send(self.sock, Kind.CHUNK, chunk)
            send(self.sock, Kind.INSTALL, chunks[-1])

    def receive(self) -> Message | None:
        """Read one message (see :func:`receive`)."""
        return receive(self.sock)

    def shutdown(self) -> None:
        """End the link both ways: the peer and this end's reader see end of
        file. The reader closes the socket afterwards."""
        with contextlib.suppress(OSError):  # already shut down, or the peer is gone
            self.sock.shutdown(socket.SHUT_RDWR)


# ------------------------------------------------------------------ framing


def pack(kind: Kind, payload: bytes = b"") -> bytes:
    """One message as bytes: header and payload."""
    return HEADER.pack(len(payload), kind) + payload


def send(sock: socket.socket, kind: Kind, payload: bytes = b"", fds: Sequence[int] = ()) -> None:
    """Write one message, with ``fds`` (at most :data:`MAX_FDS`) if any.

    Not safe for concurrent writers on one socket: the caller serialises
    them (one lock per link, §5.2), or messages would interleave.
    """
    data = memoryview(pack(kind, payload))
    if fds:
        rights = array.array("i", fds)
        sent = sock.sendmsg([data], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights)])
        data = data[sent:]
    sock.sendall(data)


def receive(sock: socket.socket) -> Message | None:
    """Read one whole message, blocking; ``None`` at end of file between messages.

    Raises :class:`LinkClosed` at end of file in the middle of a message,
    and ``ValueError`` for an unknown kind. The caller owns the descriptors
    a message carries and must close those it does not keep.
    """
    fds: list[int] = []
    header = _read(sock, HEADER.size, fds)
    if header is None:
        return None
    length, kind = HEADER.unpack(header)
    payload: bytes | bytearray = b""
    if length:
        read = _read(sock, length, fds)
        if read is None:
            raise LinkClosed(f"end of file before a {length}-byte payload")
        payload = read
    return Message(Kind(kind), payload, tuple(fds))


def _read(sock: socket.socket, size: int, fds: list[int]) -> bytearray | None:
    """Exactly ``size`` bytes, adding any descriptors that arrive to ``fds``;
    ``None`` at end of file before the first byte."""
    buffer = bytearray(size)
    view = memoryview(buffer)
    got = 0
    while got < size:
        count, ancillary, _, _ = sock.recvmsg_into([view[got:]], _ANCILLARY)
        for level, kind, data in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                whole = len(data) - len(data) % array.array("i").itemsize
                fds.extend(array.array("i", data[:whole]))
        if count == 0:
            if got == 0:
                return None
            raise LinkClosed(f"end of file after {got} of {size} bytes")
        got += count
    return buffer


# ------------------------------------------------------------------ pickles


def _proxy(items: dict[Any, Any]) -> MappingProxyType[Any, Any]:
    """Rebuild a read-only mapping on load."""
    return MappingProxyType(items)


class _Pickler(pickle.Pickler):
    """A pickler for busk's objects: a ``MappingProxyType`` (which pickle
    refuses) travels as its dict and is rebuilt read-only."""

    def reducer_override(self, obj: Any) -> Any:
        if type(obj) is MappingProxyType:
            return _proxy, (dict(obj),)
        return NotImplemented


class _SharingPickler(_Pickler):
    """A :class:`_Pickler` that writes the objects in ``tokens`` (keyed by
    ``id``) as references instead of their contents."""

    def __init__(self, file: IO[bytes], tokens: Mapping[int, Token]) -> None:
        super().__init__(file, protocol=PROTOCOL)
        self._tokens = tokens

    def persistent_id(self, obj: Any) -> Token | None:
        return self._tokens.get(id(obj))


class _SharingUnpickler(pickle.Unpickler):
    """Loads what a :class:`_SharingPickler` wrote, resolving its tokens."""

    def __init__(self, file: IO[bytes], resolve: Callable[[Token], object]) -> None:
        super().__init__(file)
        self._resolve = resolve

    def persistent_load(self, pid: Any) -> object:
        return self._resolve(pid)


def dumps(obj: object) -> bytes:
    """A message payload for ``obj`` (a pickle that may hold read-only mappings)."""
    buffer = io.BytesIO()
    _Pickler(buffer, protocol=PROTOCOL).dump(obj)
    return buffer.getvalue()


def loads(payload: bytes | bytearray) -> Any:
    """The object of a :func:`dumps` payload."""
    return pickle.loads(payload)


# ------------------------------------------------------------------ frames


def encode_frame(frame: Frame, layout: int) -> bytes:
    """A :attr:`Kind.FRAME` payload: :data:`FRAME_HEADER` (seq, time, the id
    of the frame's layout, universe count, output enabled), then each
    universe's 512 bytes in row order."""
    header = FRAME_HEADER.pack(
        frame.seq, frame.time, layout, len(frame.universes), frame.outputEnabled
    )
    return header + b"".join(frame.universes)


def decode_frame(payload: bytes | bytearray, layouts: Mapping[int, OutputLayout]) -> Frame:
    """The frame of an :func:`encode_frame` payload, with its layout looked
    up in ``layouts`` (a ``KeyError`` if its ``Layout`` never came). The
    frame has no compiled show: another process made it."""
    seq, time, layout, count, enabled = FRAME_HEADER.unpack_from(payload)
    start = FRAME_HEADER.size
    if len(payload) != start + count * UNIVERSE_SIZE:
        raise ValueError(f"a frame of {count} universes cannot be {len(payload)} bytes")
    view = memoryview(payload)
    universes = tuple(
        view[start + k * UNIVERSE_SIZE : start + (k + 1) * UNIVERSE_SIZE].tobytes()
        for k in range(count)
    )
    return Frame(
        seq=seq, time=time, universes=universes, layout=layouts[layout], outputEnabled=enabled
    )


# ------------------------------------------------------------------ the compiled-show codec

_NO_KEYS: Final[Mapping[Any, int]] = MappingProxyType({})
_VIEWS: dict[int, Any] = {}  # id(original) → its view; an entry leaves with its original
_VIEWS_LOCK = threading.RLock()  # a show's view makes its slot table's view inside


def _memoised[T](original: T, make: Callable[[T], T]) -> T:
    """``make(original)``, made once per live object."""
    key = id(original)
    with _VIEWS_LOCK:
        view = _VIEWS.get(key)
        if view is None:
            view = make(original)
            _VIEWS[key] = view
            weakref.finalize(original, _VIEWS.pop, key, None)
    return view


def engine_view(compiled: CompiledShow) -> CompiledShow:
    """``compiled`` without what the engine never reads (§5.3): no channels,
    memo, warnings or readout lookups, and a slot table without its per-slot
    records and key map (it keeps ``keys``). The same object gives the same
    view."""
    return _memoised(
        compiled,
        lambda show: replace(
            show,
            slots=_slot_view(show.slots),
            readout=EMPTY_READOUT,
            channels=(),
            memo=None,
            warnings=(),
        ),
    )


def _slot_view(slots: SlotTable) -> SlotTable:
    """The engine's slot table: the arrays and ``keys``, no records."""
    return _memoised(slots, lambda table: replace(table, slots=(), byKey=_NO_KEYS))


def components(view: CompiledShow) -> dict[Token, object]:
    """The objects of a compiled show that installs share by reference,
    keyed by path: the show itself, its rig (slot table, conversion plan,
    base images, universes, output layout) and each cue list.

    Both ends of a link compute them from the last show they exchanged, so a
    token names the same object on both sides without coordination.
    """
    parts: dict[Token, object] = {
        ("show",): view,
        ("rig", "slots"): view.slots,
        ("rig", "plan"): view.plan,
        ("rig", "base"): view.baseImages,
        ("rig", "universes"): view.universes,
        ("rig", "layout"): view.layout,
    }
    for ident, cue_list in view.cueLists.items():
        parts[("list", ident)] = cue_list
    return parts


class ShowEncoder:
    """Turns installs into chunks, for one link (the console side).

    It remembers the components of the last compiled show it sent and keeps
    them alive, so an ``id`` it compares against can never be reused.

    ``shown`` seeds it with a show the other end already holds as if it had
    been sent: a restarted console whose show has the engine's stamp
    (decision 8), whose decoder is seeded with the engine's copy. Its
    unchanged parts then arrive as the engine's own objects.
    """

    def __init__(self, shown: CompiledShow | None = None) -> None:
        self._tokens: dict[int, Token] = {}
        self._held: dict[Token, object] = {}
        if shown is not None:
            self._held = components(engine_view(shown))
            self._tokens = {id(obj): token for token, obj in self._held.items()}

    def encode(self, install: Install) -> list[bytes]:
        """The chunks of ``install``, in sending order; the last one commits it.

        A programmer-only install is one chunk. Otherwise the show travels as
        its engine view: first the rig if it changed, then each changed cue
        list, then the install, which refers to all of them.
        """
        if install.compiled is None:
            return [self._dump(install, self._tokens)]
        view = engine_view(install.compiled)
        parts = components(view)
        tokens = dict(self._tokens)
        chunks: list[bytes] = []
        if id(view) not in tokens:
            fresh = [
                (token, obj)
                for token, obj in parts.items()
                if token != ("show",) and id(obj) not in tokens
            ]
            rig = tuple(obj for token, obj in fresh if token[0] == "rig")
            groups = ([rig] if rig else []) + [(obj,) for token, obj in fresh if token[0] == "list"]
            count = 0
            for group in groups:
                chunks.append(self._dump(group, tokens))
                for obj in group:
                    tokens[id(obj)] = ("new", count)
                    count += 1
        chunks.append(self._dump(replace(install, compiled=view), tokens))
        self._tokens = {id(obj): token for token, obj in parts.items()}
        self._held = parts
        return chunks

    @staticmethod
    def _dump(obj: object, tokens: Mapping[int, Token]) -> bytes:
        buffer = io.BytesIO()
        _SharingPickler(buffer, tokens).dump(obj)
        return buffer.getvalue()


class ShowDecoder:
    """Turns chunks back into installs, for one link (the engine side).

    ``shown`` seeds it with the show the engine runs, for an encoder seeded
    with the same show (see :class:`ShowEncoder`).
    """

    def __init__(self, shown: CompiledShow | None = None) -> None:
        self._shared: dict[Token, object] = {} if shown is None else components(shown)
        self._new: list[object] = []

    def feed(self, chunk: bytes | bytearray) -> Install | None:
        """Load one chunk; the install once its last chunk has come, else ``None``."""
        loaded = _SharingUnpickler(io.BytesIO(chunk), self._resolve).load()
        if isinstance(loaded, Install):
            self._new = []
            if loaded.compiled is not None:
                self._shared = components(loaded.compiled)
            return loaded
        self._new.extend(loaded)
        return None

    def _resolve(self, token: Token) -> object:
        if token[0] == "new":
            return self._new[int(token[1])]
        return self._shared[token]
