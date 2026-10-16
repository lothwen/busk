"""Panic commands: ``RELEASE_ALL`` and ``OUTPUT`` (phase-7-plan decision 15,
§5.13, step 5).

``RELEASE_ALL`` releases every active playback with its own release time,
or ``time`` when given (which also cuts releases already running short);
held flashes and swops are dropped; the programmer is left alone.
``OUTPUT {on: false}`` silences every route: sACN streams terminate at
once, and start again (with continuing sequence numbers) when output is
back on. Appendix A's Song releases over 2 s, Blue over 1 s.
"""

from __future__ import annotations

from typing import Any

import pytest

from builders import APPENDIX_A, Doc, compile_doc, load_doc, localhost_route
from busk.cli import status_line
from busk.engine.clock import FakeClock
from busk.output.artnet import ArtNetNetwork
from busk.output.sacn import Sequences
from busk.output.scheduler import OutputScheduler, build_routes
from harness import Harness, _command, flash, release, trigger
from sacn_receiver import Receiver
from session_harness import Live, put, sel


def release_all(time: float | None = None) -> Any:
    return _command(type="RELEASE_ALL") if time is None else _command(type="RELEASE_ALL", time=time)


def output(on: bool) -> Any:
    return _command(type="OUTPUT", on=on)


def states(harness: Harness, now: float) -> dict[str, str]:
    snapshot = harness.tick(now).snapshot
    assert snapshot is not None
    return {status.id: status.state for status in snapshot.playbacks}


def appendix() -> Doc:
    doc = load_doc(APPENDIX_A)
    doc["playbacks"][0]["buttons"] = ["go", "swop"]  # Song gets a swop button
    return doc


# ------------------------------------------------------------- RELEASE_ALL


def test_release_all_uses_each_playbacks_release_time() -> None:
    harness = Harness(compile_doc(appendix()))
    harness.submit(trigger("pb-song"), trigger("pb-blue"))
    harness.tick(0.0)
    harness.submit(release_all())
    assert states(harness, 1.0) == {"pb-song": "releasing", "pb-blue": "releasing",
                                    "pb-pulse": "idle"}  # fmt: skip
    assert states(harness, 2.05) == {"pb-song": "releasing", "pb-blue": "idle", "pb-pulse": "idle"}
    assert states(harness, 3.05)["pb-song"] == "idle"


def test_release_all_with_a_time_cuts_running_releases_short() -> None:
    harness = Harness(compile_doc(appendix()))
    harness.submit(trigger("pb-song"), trigger("pb-blue"))
    harness.tick(0.0)
    harness.submit(release("pb-blue", 10.0))
    harness.tick(0.5)
    harness.submit(release_all(0.25))
    assert set(states(harness, 1.0).values()) == {"releasing", "idle"}
    assert set(states(harness, 1.3).values()) == {"idle"}


def test_release_all_with_time_zero_goes_dark_at_once() -> None:
    harness = Harness(compile_doc(appendix()))
    harness.submit(trigger("pb-song"), trigger("pb-blue"))
    lit = harness.tick(0.0).logical
    harness.submit(release_all(0))
    observed = harness.tick(0.01)
    assert set(states(harness, 0.01).values()) == {"idle"}
    assert observed.logical.tolist() != lit.tolist()
    assert observed.logical.tolist() == pytest.approx(
        Harness(compile_doc(appendix())).tick(0.0).logical.tolist(), nan_ok=True
    )


def test_release_all_drops_held_flashes_and_swops() -> None:
    harness = Harness(compile_doc(appendix()))
    swop = _command(type="PLAYBACK_BUTTON", playbackId="pb-song", button=1, down=True)
    harness.submit(flash("pb-blue", True), swop)
    harness.tick(0.0)
    runtimes = harness.engine.runtime.playbacks.runtimes
    assert runtimes["pb-blue"].flashPresent
    assert runtimes["pb-song"].flashPresent
    harness.submit(release_all())
    harness.tick(0.01)
    assert not runtimes["pb-blue"].flashPresent
    assert not runtimes["pb-song"].flashPresent
    assert harness.engine.runtime.playbacks.swopping == {}
    # The buttons' later releases do nothing.
    harness.submit(flash("pb-blue", False), {**swop, "down": False})
    harness.tick(0.02)
    assert not runtimes["pb-song"].flashPresent


def test_release_all_leaves_the_programmer_alone() -> None:
    live = Live(appendix())
    live.do(sel("fx-par1"), put("intensity", 0.6))
    live.engine.bus.submit(release_all(0))
    live.tick()
    assert live.lanes("fx-par1", "intensity") == [0.6]


# ------------------------------------------------------------------ OUTPUT


def test_output_off_shows_on_the_snapshot_and_status_line() -> None:
    harness = Harness(compile_doc(appendix()))
    harness.submit(output(False))
    snapshot = harness.tick(0.0).snapshot
    assert snapshot is not None
    assert snapshot.outputEnabled is False
    assert status_line(snapshot).startswith("GM 100% | BO off | OUT off | ")
    frame = harness.engine.latest
    assert frame is not None
    assert frame.outputEnabled is False
    harness.submit(output(True))
    snapshot = harness.tick(0.01).snapshot
    assert snapshot is not None
    assert snapshot.outputEnabled is True
    assert "OUT" not in status_line(snapshot)


def test_output_off_terminates_sacn_and_on_starts_a_new_stream(receiver: Receiver) -> None:
    compiled = compile_doc(localhost_route(appendix()))
    harness = Harness(compiled)
    sequences, artnet = Sequences(), ArtNetNetwork()
    routes, _ = build_routes(compiled.output, compiled.universes, sequences, artnet=artnet)
    scheduler = OutputScheduler(
        harness.engine,
        routes,
        FakeClock(),
        layout=compiled.layout,
        sequences=sequences,
        artnet=artnet,
    )
    try:
        harness.submit(trigger("pb-blue"))
        harness.tick(0.0)
        scheduler.service(0.0)
        first = receiver.receive()
        assert not first.terminated
        receiver.drain(0.05)

        harness.submit(output(False))
        harness.tick(0.01)
        scheduler.service(0.03)
        stopped = receiver.drain(0.1)
        assert stopped
        assert all(packet.terminated for packet in stopped)
        for k in range(2, 50):  # nothing while off, keep-alive time included
            harness.tick(k / 100)
            scheduler.service(k / 40)
        assert receiver.drain(0.1) == []

        harness.submit(output(True))
        harness.tick(0.5)
        scheduler.service(1.3)
        again = receiver.receive()
        assert not again.terminated
        assert again.sequence == (stopped[-1].sequence + 1) % 256
        assert again.data == harness.engine.latest.universes[0]  # type: ignore[union-attr]
    finally:
        scheduler.close()
