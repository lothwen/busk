"""The console's side of the engine (phase-7-plan §5.5, decisions 5–8, step 7).

:class:`RemoteBus` against engine hosts running in this process (threads,
the real clock), with the test playing the root: commands queued while no
engine is attached, the fresh-engine reconnect (show, restore, queued
commands), a skipped restore, a second console adopting a running engine
(whose remap the engine computes from slot keys, or which keeps its show
when the stamps are equal), live installs over the link, and the queue
bound. Then :class:`LocalEngine` and ``keys_remap``.
"""

from __future__ import annotations

import copy
import socket
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any, cast

import numpy as np
import pytest

from builders import APPENDIX_A, fixture, load_doc, show_of
from busk.commands.types import Command
from busk.compiler.compile import CompiledShow, compile_show
from busk.engine.clock import FakeClock, MonotonicClock
from busk.engine.install import EMPTY_FRAME, Install, keys_remap
from busk.engine.link import LocalEngine
from busk.engine.loop import Engine
from busk.engine.snapshot import EngineSnapshot
from busk.model.show import Show
from busk.process.engine_host import EngineHost
from busk.process.links import QUEUE_MAX, RemoteBus
from busk.process.wire import Attach, Kind, dumps, receive, send

TIMEOUT = 5.0


def command(**fields: Any) -> Command:
    return cast(Command, fields)


def state(snapshot: EngineSnapshot | None, ident: str) -> str | None:
    if snapshot is None:
        return None
    return next(status.state for status in snapshot.playbacks if status.id == ident)


def until(test: Callable[[], bool], timeout: float = TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while not test():
        assert time.monotonic() < deadline, "not in time"
        time.sleep(0.01)


class Host:
    """An :class:`EngineHost` in a thread; the test is its root and drains
    what it publishes."""

    def __init__(self) -> None:
        self.root, end = socket.socketpair()
        self.end = end
        self.host = EngineHost(end, freeze=False)
        self.codes: list[int] = []
        self.thread = threading.Thread(target=lambda: self.codes.append(self.host.run()))
        self.thread.daemon = True
        self.thread.start()
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self) -> None:
        try:
            while receive(self.root) is not None:
                pass
        except OSError:
            pass

    def attach(self, bus: RemoteBus, restore: bool = True) -> None:
        console, engine = socket.socketpair()
        send(self.root, Kind.ATTACH, dumps(Attach()), fds=[engine.fileno()])
        engine.close()
        bus.attach(console, Attach(reason="test", restore=restore))

    @property
    def engine(self) -> Engine:
        assert self.host.engine is not None
        return self.host.engine

    def stop(self) -> None:
        send(self.root, Kind.STOP)
        self.thread.join(timeout=TIMEOUT)
        assert self.codes == [0]
        self.root.close()
        self.end.close()


@pytest.fixture
def hosts() -> Iterator[list[Host]]:
    made: list[Host] = []
    yield made
    for host in made:
        if host.thread.is_alive():
            host.stop()


def appendix() -> tuple[Show, CompiledShow]:
    show = show_of(load_doc(APPENDIX_A))
    return show, compile_show(show)


def remote(compiled: CompiledShow, **options: Any) -> RemoteBus:
    return RemoteBus(compiled, MonotonicClock(), sessionId="console-1", **options)


def test_a_remote_bus_reaches_a_fresh_engine_and_follows_it(hosts: list[Host]) -> None:
    _, compiled = appendix()
    bus = remote(compiled)
    bus.submit(command(type="TRIGGER_PLAYBACK", playbackId="pb-blue"))
    assert not bus.attached  # queued
    hosts.append(host := Host())
    host.attach(bus)
    until(lambda: state(bus.snapshot, "pb-blue") == "active")
    assert bus.attached
    assert bus.reconnects == 1
    bus.submit(command(type="BLACKOUT", on=True))
    until(lambda: bus.snapshot is not None and bus.snapshot.blackout)
    until(lambda: bus.stats.commandsApplied == 2, timeout=2.5)  # statistics every second


def test_sync_waits_until_the_snapshot_shows_what_was_sent(hosts: list[Host]) -> None:
    _, compiled = appendix()
    bus = remote(compiled)
    assert not bus.sync(0.05)  # no engine attached
    bus.submit(command(type="TRIGGER_PLAYBACK", playbackId="pb-blue"))
    hosts.append(host := Host())
    host.attach(bus)
    assert bus.sync(TIMEOUT)  # waits for the reconnect, then for the queued command
    assert state(bus.snapshot, "pb-blue") == "active"
    for on in (True, False, True):
        bus.submit(command(type="BLACKOUT", on=on))
        assert bus.sync(TIMEOUT)
        assert bus.snapshot is not None
        assert bus.snapshot.blackout is on
    # A restarted console numbers its syncs from 1 again: still answered.
    again = remote(compiled, restarted=True)
    host.attach(again)
    assert again.sync(TIMEOUT)
    assert again.snapshot is not None
    assert again.snapshot.blackout


def test_a_new_engine_gets_the_show_the_restore_and_the_queued_commands(
    hosts: list[Host],
) -> None:
    _, compiled = appendix()
    bus = remote(compiled)
    hosts.append(first := Host())
    first.attach(bus)
    bus.submit(command(type="TRIGGER_PLAYBACK", playbackId="pb-song"))
    bus.submit(command(type="SET_MASTER", masterId="m-gm", level=0.5))
    until(lambda: state(bus.snapshot, "pb-song") == "active")
    until(lambda: bus.snapshot is not None and bus.snapshot.grandMaster == 0.5)
    first.stop()  # the engine is gone: its link ends
    until(lambda: not bus.attached)
    bus.submit(command(type="BLACKOUT", on=True))  # pressed during the restart
    hosts.append(second := Host())
    second.attach(bus)
    until(lambda: bus.reconnects == 2)
    until(lambda: bus.snapshot is not None and bus.snapshot.blackout)
    snapshot = bus.snapshot
    assert snapshot is not None
    assert state(snapshot, "pb-song") == "active"  # restored
    assert snapshot.grandMaster == 0.5
    assert second.engine.stats.installErrors == 0


def test_a_restore_the_root_skips_leaves_the_engine_fresh(hosts: list[Host]) -> None:
    _, compiled = appendix()
    bus = remote(compiled)
    hosts.append(first := Host())
    first.attach(bus)
    bus.submit(command(type="TRIGGER_PLAYBACK", playbackId="pb-song"))
    until(lambda: state(bus.snapshot, "pb-song") == "active")
    first.stop()
    until(lambda: not bus.attached)
    bus.submit(command(type="TRIGGER_PLAYBACK", playbackId="pb-blue"))
    hosts.append(second := Host())
    second.attach(bus, restore=False)
    until(lambda: state(bus.snapshot, "pb-blue") == "active")
    assert state(bus.snapshot, "pb-song") == "idle"


def add_fixture(show: Show) -> Show:
    """The show with one more (unpatched) par: new slot keys, in the middle."""
    doc = copy.deepcopy(cast(dict[str, Any], show))
    doc["fixtures"].insert(1, fixture("fx-new", 99, "prof-par", None, mode_id="mode-3"))
    return show_of(doc)


def test_a_restarted_console_adopts_the_engine_and_its_remap_is_computed(
    hosts: list[Host],
) -> None:
    show, compiled = appendix()
    bus = remote(compiled)
    hosts.append(host := Host())
    host.attach(bus)
    bus.submit(command(type="TRIGGER_PLAYBACK", playbackId="pb-blue"))
    until(lambda: state(bus.snapshot, "pb-blue") == "active")
    time.sleep(1.2)  # Blue's 1 s fade in is over: the look is static
    before = host.engine.latest
    assert before is not None
    # A new console whose recovered show has different slot keys.
    recovered = compile_show(add_fixture(show))
    assert recovered.slots.keys != compiled.slots.keys
    again = remote(recovered, restarted=True)
    host.attach(again)
    until(lambda: again.attached)
    assert state(again.snapshot, "pb-blue") == "active"  # adopted, not pushed
    assert again.adoption == "replaced"  # unstamped shows never count as equal
    until(lambda: host.engine.stats.installs >= 2)
    assert host.engine.stats.installErrors == 0
    time.sleep(0.05)
    after = host.engine.latest
    assert after is not None
    assert after.compiled is not None
    assert len(after.compiled.slots.keys) == len(recovered.slots.keys)
    assert after.universes == before.universes  # pb-blue still plays, on its remapped lanes
    assert not bus.attached  # the old console's link was replaced


def rename_playback(show: Show, name: str) -> Show:
    """A copy-on-write edit, as the session makes it: the rig stays the same object."""
    playbacks = list(show["playbacks"])
    playbacks[1] = {**playbacks[1], "name": name}
    return cast(Show, {**show, "playbacks": playbacks})


def test_a_restarted_console_with_the_engines_stamp_sends_only_its_programmer(
    hosts: list[Host],
) -> None:
    show, compiled = appendix()
    bus = remote(compiled, stamp=("console-1", 0))
    hosts.append(host := Host())
    host.attach(bus)
    bus.submit(command(type="TRIGGER_PLAYBACK", playbackId="pb-blue"))
    until(lambda: state(bus.snapshot, "pb-blue") == "active")
    before = host.engine.compiled
    installs = host.engine.stats.installs
    # The new console recovered the same show: equal content and stamp.
    recovered = compile_show(show)
    again = remote(recovered, restarted=True, stamp=("console-1", 0))
    host.attach(again)
    until(lambda: again.attached)
    assert again.adoption == "kept"
    assert state(again.snapshot, "pb-blue") == "active"
    until(lambda: host.engine.stats.installs == installs + 1)  # the programmer frame
    assert host.engine.compiled is before  # no show was installed
    # Its next edit shares the engine's objects: nothing but the edit changes.
    edited = compile_show(rename_playback(show, "Renamed"), previous=recovered)
    again.install(
        Install(compiled=edited, remap=None, programmer=EMPTY_FRAME, stamp=("console-2", 1))
    )
    until(lambda: host.engine.stats.installs == installs + 2)
    after = host.engine.compiled
    assert after is not before
    assert after.slots is before.slots
    assert all(after.cueLists[k] is before.cueLists[k] for k in before.cueLists)
    assert host.engine.stats.installErrors == 0
    # The engine answers with the stamp of the show it got last.
    third = remote(edited, restarted=True, stamp=("console-2", 1))
    host.attach(third)
    until(lambda: third.attached)
    assert third.adoption == "kept"
    assert host.engine.compiled is after


def test_a_live_install_reaches_the_engine_over_the_link(hosts: list[Host]) -> None:
    show, compiled = appendix()
    bus = remote(compiled)
    hosts.append(host := Host())
    host.attach(bus)
    until(lambda: bus.attached)
    renamed = copy.deepcopy(cast(dict[str, Any], show))
    renamed["playbacks"][1]["name"] = "Renamed"
    edited = compile_show(show_of(renamed), previous=compiled)
    bus.install(Install(compiled=edited, remap=None, programmer=EMPTY_FRAME))
    bus.compiled = edited
    bus.submit(command(type="TRIGGER_PLAYBACK", playbackId="pb-blue"))
    until(lambda: state(bus.snapshot, "pb-blue") == "active")
    snapshot = bus.snapshot
    assert snapshot is not None
    assert next(s.name for s in snapshot.playbacks if s.id == "pb-blue") == "Renamed"


def test_a_detached_bus_keeps_the_oldest_commands() -> None:
    _, compiled = appendix()
    bus = remote(compiled)
    for k in range(QUEUE_MAX + 6):
        bus.submit(command(type="SET_MASTER", masterId="m-gm", level=(k % 10) / 10))
    assert bus.dropped == 6
    assert not bus.attached


def test_a_remote_bus_validates_as_the_engine_bus_does() -> None:
    from busk.commands.bus import CommandRejected

    _, compiled = appendix()
    bus = remote(compiled)
    with pytest.raises(CommandRejected):
        bus.submit(command(type="TRIGGER_PLAYBACK", playbackId="pb-nope"))
    assert bus.dropped == 0


# ------------------------------------------------------------- LocalEngine and keys_remap


def test_local_engine_is_the_engine_and_its_bus() -> None:
    _, compiled = appendix()
    clock = FakeClock()
    engine = Engine(compiled, clock)
    link = LocalEngine(engine)
    assert link.compiled is compiled
    link.submit(command(type="TRIGGER_PLAYBACK", playbackId="pb-blue"))
    engine.tick(0.0)
    assert state(link.snapshot, "pb-blue") == "active"
    assert link.stats.commandsApplied == 1
    link.compiled = compiled
    assert engine.bus.compiled is compiled


def test_local_engine_sync_waits_for_the_engine_thread() -> None:
    _, compiled = appendix()
    engine = Engine(compiled, MonotonicClock())
    link = LocalEngine(engine)
    assert not link.sync(0.05)  # nothing ticks
    stop = threading.Event()
    thread = threading.Thread(target=engine.run, args=(stop,), daemon=True)
    thread.start()
    try:
        link.submit(command(type="TRIGGER_PLAYBACK", playbackId="pb-blue"))
        assert link.sync(TIMEOUT)
        assert state(link.snapshot, "pb-blue") == "active"
    finally:
        stop.set()
        thread.join()


def test_keys_remap_matches_slots_by_key() -> None:
    show, compiled = appendix()
    recovered = compile_show(add_fixture(show))
    remap = keys_remap(compiled.slots, recovered.slots)
    assert remap is not None
    assert len(remap) == len(compiled.slots.keys)
    for old, new in enumerate(remap.tolist()):
        assert recovered.slots.keys[new] == compiled.slots.keys[old]
    assert keys_remap(compiled.slots, compiled.slots) is None
    assert not np.asarray(remap).flags.writeable
