"""Soft takeover (phase-6-plan §5.4, decision 6): a soft fader never jumps.

``Pickup`` is tested on its own, then through the engine, which applies it
to ``SET_FADER`` and ``SET_MASTER`` by the control in each command's origin:
attaching by tolerance and by crossing, ignoring moves while detached,
detaching on a move from anywhere else, page changes, masters, ``jump``
surfaces and a live switch between the two. A hypothesis test checks the
rule over random interleavings of every kind of source.
"""

from __future__ import annotations

import copy
import functools
import json
from typing import Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from builders import compile_doc
from busk.commands.types import Command, CommandOrigin
from busk.compiler.compile import CompiledShow
from busk.engine.install import EMPTY_FRAME, Install
from busk.engine.surfaces import PICKUP_TOLERANCE, Knob, Pickup
from busk.model.common import MasterId, PlaybackId
from conftest import APPENDIX_A
from harness import Harness, fader, master

SONG: Knob = ("fader", "pb-song")
BLUE: Knob = ("fader", "pb-blue")

# ------------------------------------------------------------------- Pickup


def test_a_jump_source_always_applies() -> None:
    pickup = Pickup()
    assert pickup.accept(None, False, SONG, 0.0, 0.9) is True
    assert pickup.setter[SONG] is None
    assert pickup.last == {}  # a jump source has no hardware position


def test_the_first_message_attaches_only_within_the_tolerance() -> None:
    pickup = Pickup()
    assert pickup.accept("b1", True, SONG, 0.5, 0.515) is True
    assert pickup.attached["b1"] == SONG
    assert pickup.setter[SONG] == "b1"
    other = Pickup()
    assert other.accept("b1", True, SONG, 0.5, 0.53) is False  # no previous value to cross from
    assert other.attached["b1"] is None
    assert other.last["b1"] == 0.53


@pytest.mark.parametrize(("previous", "value"), [(0.2, 0.7), (0.7, 0.2), (0.2, 0.5), (0.5, 0.7)])
def test_a_move_that_crosses_the_level_attaches(previous: float, value: float) -> None:
    pickup = Pickup()
    assert pickup.accept("b1", True, SONG, 0.5, previous) is (previous == 0.5)
    assert pickup.accept("b1", True, SONG, 0.5, value) is True
    assert pickup.attached["b1"] == SONG


def test_moves_are_ignored_until_they_meet_the_level() -> None:
    pickup = Pickup()
    for value in (0.9, 0.8, 0.6, 0.53, 0.7):  # all above 0.5 + tolerance
        assert pickup.accept("b1", True, SONG, 0.5, value) is False
    assert pickup.accept("b1", True, SONG, 0.5, 0.45) is True  # crosses on the way down


def test_an_attached_control_applies_any_move() -> None:
    pickup = Pickup()
    pickup.accept("b1", True, SONG, 0.0, 0.0)
    assert pickup.accept("b1", True, SONG, 0.0, 1.0) is True  # the level it set is 0.0 still
    assert pickup.accept("b1", True, SONG, 1.0, 0.1) is True


@pytest.mark.parametrize("other", [None, "j1", "b9"])
def test_any_other_source_detaches(other: str | None) -> None:
    """The console or the phone (no control), a jump control or another soft one."""
    pickup = Pickup()
    pickup.accept("b1", True, SONG, 0.7, 0.7)
    if other == "b9":
        pickup.accept("b9", True, SONG, 0.7, 0.7)  # b9 picks the level up first
    assert pickup.accept(other, other == "b9", SONG, 0.7, 0.3) is True
    assert pickup.accept("b1", True, SONG, 0.3, 0.75) is False  # 0.7 → 0.75 misses 0.3
    assert pickup.accept("b1", True, SONG, 0.3, 0.25) is True


def test_a_move_on_another_knob_detaches_from_the_first() -> None:
    pickup = Pickup()
    pickup.accept("b1", True, SONG, 0.4, 0.4)
    pickup.accept("b1", True, BLUE, 0.7, 0.7)  # a page change: the control drives pb-blue
    assert pickup.attached["b1"] == BLUE
    assert pickup.accept("b1", True, SONG, 0.4, 0.8) is False  # no crossing of 0.4 (0.7 → 0.8)


def test_a_missed_move_counts_as_the_hardware_position() -> None:
    pickup = Pickup()
    pickup.accept("b1", True, SONG, 0.2, 0.2)
    pickup.missed("b1", 0.9)  # an empty slot on another page
    assert pickup.attached["b1"] is None
    assert pickup.accept("b1", True, SONG, 0.2, 0.92) is False  # 0.9 → 0.92 misses 0.2
    pickup.missed(None, 0.5)  # a jump source has no position to keep
    assert None not in pickup.last


def test_a_jump_control_records_its_position() -> None:
    pickup = Pickup()
    assert pickup.accept("j1", False, SONG, 0.0, 0.9) is True
    assert (pickup.last["j1"], pickup.attached["j1"], pickup.setter[SONG]) == (0.9, SONG, "j1")


# --------------------------------------------------------------- the engine
#
# Appendix A's MIDI controller (s-midi) is soft: b1 is its fader on slot 0 and
# b3 its grand master fader. b9 is a second soft fader on slot 0, and the
# jump surface s-jump has j1 on slot 0. Page 2 ("Washes") puts pb-blue on
# slot 0; page 1 has pb-blue on slot 2 and page 2 has no slot 2.


def build_doc(appendix: dict[str, Any]) -> dict[str, Any]:
    doc = copy.deepcopy(appendix)
    doc["pages"].append(
        {"id": "page-2", "number": 2, "name": "Washes", "slots": ["pb-blue", "pb-song"]}
    )
    doc["masters"].extend(
        [
            {"id": "m-size", "kind": "size", "name": "Size"},
            {"id": "m-par", "kind": "group", "name": "Pars", "groupId": "g-par"},
        ]
    )
    doc["surfaces"].append(
        {"id": "s-jump", "name": "Jump", "kind": "midi", "match": {}, "faderPickup": "jump"}
    )
    cc = {"kind": "midiCC", "channel": 1}
    doc["bindings"].extend(
        [
         {"id": "b9", "surfaceId": "s-midi", "input": {**cc, "cc": 9},
          "action": {"kind": "playbackFader", "slot": 0}},
         {"id": "b-s2", "surfaceId": "s-midi", "input": {**cc, "cc": 2},
          "action": {"kind": "playbackFader", "slot": 2}},
         {"id": "j1", "surfaceId": "s-jump", "input": {**cc, "cc": 0},
          "action": {"kind": "playbackFader", "slot": 0}},
        ]
    )  # fmt: skip
    return doc


@pytest.fixture
def doc(appendix_a: dict[str, Any]) -> dict[str, Any]:
    return build_doc(appendix_a)


@pytest.fixture
def show(doc: dict[str, Any]) -> CompiledShow:
    return compile_doc(doc)


def _command(**fields: Any) -> Command:
    return cast(Command, fields)


def slot_fader(slot: int, level: float) -> Command:
    return _command(type="SET_FADER", slot=slot, level=level)


def page_cmd(**fields: int) -> Command:
    return _command(type="PAGE", **fields)


def send(harness: Harness, command: Command, control: str | None = None) -> None:
    """Submit ``command`` from binding ``control`` (``None``: the console)."""
    origin = CommandOrigin(surfaceId=cast(Any, "s-jump" if control == "j1" else "s-midi"))
    if control is not None:
        origin["control"] = control
    harness.engine.bus.submit(command, origin)


class Driver:
    """A harness that ticks after every command, 10 ms apart."""

    def __init__(self, show: CompiledShow) -> None:
        self.harness = Harness(show)
        self.now = 0.0
        self.harness.tick(self.now)

    def send(self, command: Command, control: str | None = None) -> None:
        send(self.harness, command, control)
        self.now += 0.01
        self.harness.tick(self.now)

    def level(self, playback: str) -> float:
        return self.harness.engine.runtime.playbacks.runtimes[PlaybackId(playback)].faderLevel

    def master(self, ident: str) -> float:
        return self.harness.engine._master_level(MasterId(ident))


def test_the_soft_controls_are_compiled(show: CompiledShow) -> None:
    assert show.softControls == frozenset({"b1", "b2", "b3", "b9", "b-s2"})


def test_a_soft_fader_never_jumps(show: CompiledShow) -> None:
    driver = Driver(show)
    driver.send(slot_fader(0, 0.7), "b1")  # the hardware sits at 0.7; pb-song is at 0
    assert driver.level("pb-song") == 0.0
    driver.send(slot_fader(0, 0.3), "b1")
    assert driver.level("pb-song") == 0.0
    driver.send(slot_fader(0, 0.01), "b1")  # within the tolerance of 0
    assert driver.level("pb-song") == 0.01
    driver.send(slot_fader(0, 0.8), "b1")  # attached: every move applies
    assert driver.level("pb-song") == 0.8
    assert driver.harness.engine.stats.commandErrors == 0


def test_a_console_or_phone_move_detaches(show: CompiledShow) -> None:
    driver = Driver(show)
    driver.send(slot_fader(0, 0.0), "b1")
    driver.send(slot_fader(0, 0.5), "b1")
    driver.send(fader("pb-song", 0.8))  # the console, or the phone: no control
    assert driver.level("pb-song") == 0.8
    driver.send(slot_fader(0, 0.55), "b1")  # ignored: 0.5 → 0.55 misses 0.8
    assert driver.level("pb-song") == 0.8
    driver.send(slot_fader(0, 0.85), "b1")  # 0.55 → 0.85 crosses 0.8
    assert driver.level("pb-song") == 0.85


def test_after_a_page_change_a_fader_reattaches_only_by_crossing(show: CompiledShow) -> None:
    driver = Driver(show)
    driver.send(slot_fader(0, 0.0), "b1")
    driver.send(slot_fader(0, 0.6), "b1")  # pb-song at 0.6
    driver.send(fader("pb-blue", 0.3))
    driver.send(page_cmd(number=2))  # slot 0 is pb-blue now
    driver.send(slot_fader(0, 0.62), "b1")
    assert (driver.level("pb-blue"), driver.level("pb-song")) == (0.3, 0.6)
    driver.send(slot_fader(0, 0.25), "b1")  # crosses 0.3
    assert driver.level("pb-blue") == 0.25
    driver.send(page_cmd(number=1))
    driver.send(slot_fader(0, 0.27), "b1")  # pb-song is still at 0.6: not crossed
    assert driver.level("pb-song") == 0.6
    driver.send(slot_fader(0, 0.7), "b1")
    assert (driver.level("pb-song"), driver.level("pb-blue")) == (0.7, 0.25)


def test_a_move_on_an_empty_slot_still_moves_the_hardware(show: CompiledShow) -> None:
    driver = Driver(show)
    driver.send(slot_fader(2, 0.0), "b-s2")
    driver.send(slot_fader(2, 0.2), "b-s2")  # pb-blue at 0.2
    driver.send(page_cmd(number=2))  # page 2 has no slot 2
    driver.send(slot_fader(2, 0.9), "b-s2")
    driver.send(page_cmd(number=1))
    driver.send(slot_fader(2, 0.92), "b-s2")  # 0.9 → 0.92 misses 0.2: no jump
    assert driver.level("pb-blue") == 0.2
    driver.send(slot_fader(2, 0.1), "b-s2")
    assert driver.level("pb-blue") == 0.1


@pytest.mark.parametrize("ident", ["m-gm", "m-speed", "m-size", "m-par"])
def test_masters_pick_up_softly(show: CompiledShow, ident: str) -> None:
    """Every master kind, through a soft control (b3 stands for any master binding)."""
    driver = Driver(show)
    start = driver.master(ident)
    far = 0.0 if start > 0.5 else 1.0
    driver.send(master(ident, far), "b3")
    assert driver.master(ident) == start
    driver.send(master(ident, start), "b3")
    driver.send(master(ident, 0.4), "b3")
    assert driver.master(ident) == 0.4
    driver.send(master(ident, 0.9))  # the console detaches it
    driver.send(master(ident, 0.45), "b3")
    assert driver.master(ident) == 0.9


def test_a_jump_surface_always_applies_and_detaches_soft_controls(show: CompiledShow) -> None:
    driver = Driver(show)
    driver.send(slot_fader(0, 0.0), "b1")
    driver.send(slot_fader(0, 0.4), "b1")
    driver.send(slot_fader(0, 0.9), "j1")  # a jump control applies wherever it is
    assert driver.level("pb-song") == 0.9
    driver.send(slot_fader(0, 0.5), "b1")
    assert driver.level("pb-song") == 0.9
    driver.send(slot_fader(0, 0.1), "j1")
    assert driver.level("pb-song") == 0.1


def test_two_soft_controls_on_one_fader(show: CompiledShow) -> None:
    driver = Driver(show)
    driver.send(slot_fader(0, 0.0), "b1")
    driver.send(slot_fader(0, 0.5), "b1")
    driver.send(slot_fader(0, 0.0), "b9")  # b9 sits at 0: ignored
    assert driver.level("pb-song") == 0.5
    driver.send(slot_fader(0, 0.6), "b9")  # crosses 0.5: b9 takes over
    driver.send(slot_fader(0, 0.2), "b1")  # b1 is detached and 0.5 → 0.2 misses 0.6
    assert driver.level("pb-song") == 0.6


def install(harness: Harness, doc: dict[str, Any]) -> None:
    """A live edit that installs ``doc`` (surfaces only change, so no remap)."""
    harness.engine.bus.install(
        Install(compiled=compile_doc(doc), remap=None, programmer=EMPTY_FRAME)
    )


def test_a_live_switch_between_jump_and_soft(doc: dict[str, Any], show: CompiledShow) -> None:
    driver = Driver(show)
    driver.send(fader("pb-song", 0.3))
    driver.send(slot_fader(0, 0.9), "b1")
    assert driver.level("pb-song") == 0.3  # soft: ignored
    doc["surfaces"][0]["faderPickup"] = "jump"
    install(driver.harness, doc)
    driver.send(slot_fader(0, 0.95), "b1")  # jump from the next command on
    assert driver.level("pb-song") == 0.95
    doc["surfaces"][0]["faderPickup"] = "soft"
    install(driver.harness, doc)
    driver.send(slot_fader(0, 0.5), "b1")  # b1 set the level last: still attached
    assert driver.level("pb-song") == 0.5
    driver.send(fader("pb-song", 0.2))
    driver.send(slot_fader(0, 0.7), "b1")  # soft again: 0.5 → 0.7 misses 0.2
    assert driver.level("pb-song") == 0.2


# --------------------------------------------------------------- hypothesis
#
# Random interleavings of moves on slot 0 and on the grand master, from soft
# controls (b1, b9; b3 on the master), the jump control j1 and the console,
# and of page changes. What happened is observed, not recomputed: a move
# applied iff the level afterwards equals its value.

SOURCES = ("b1", "b9", "j1", None)
OPS = st.lists(
    st.one_of(
        st.tuples(st.just("fader"), st.sampled_from(SOURCES), st.integers(0, 20)),
        st.tuples(st.just("master"), st.sampled_from(("b3", None)), st.integers(0, 20)),
        st.tuples(st.just("page"), st.none(), st.sampled_from((-1, 1))),
    ),
    max_size=40,
)


@functools.cache
def property_show() -> CompiledShow:
    return compile_doc(build_doc(json.loads(APPENDIX_A.read_text(encoding="utf-8"))))


@settings(max_examples=150, deadline=None)
@given(OPS)
def test_soft_moves_only_apply_when_attached_crossing_or_close(
    ops: list[tuple[str, str | None, int]],
) -> None:
    show = property_show()
    driver = Driver(show)
    soft = show.softControls
    owner: dict[Knob, str | None] = {}  # who applied the last move to each knob
    on: dict[str, Knob | None] = {}  # the knob each control's last move applied to
    position: dict[str, float] = {}  # each control's last value

    def level(knob: Knob) -> float:
        kind, ident = knob
        return driver.level(ident) if kind == "fader" else driver.master(ident)

    for kind, source, number in ops:
        if kind == "page":
            driver.send(page_cmd(delta=number))
            continue
        value = number / 20
        if kind == "fader":
            page = driver.harness.engine.runtime.page.playback(0)
            assert page is not None
            knob: Knob = ("fader", page)
            command = slot_fader(0, value)
        else:
            knob = ("master", "m-gm")
            command = master("m-gm", value)
        before = level(knob)
        attached = source is not None and on.get(source) == knob and owner.get(knob) == source
        previous = None if source is None else position.get(source)
        driver.send(command, source)
        applied = level(knob) == value
        if source is None or source not in soft:
            assert applied  # jump sources always apply
        else:
            met = abs(value - before) <= PICKUP_TOLERANCE or (
                previous is not None and min(previous, value) <= before <= max(previous, value)
            )
            assert applied == (attached or met)
            if not applied:
                assert level(knob) == before
        if source is not None:
            position[source] = value
            on[source] = knob if applied else None
        if applied:
            owner[knob] = source
        # An attached control's knob is at the control's last value.
        for control, held in on.items():
            if held is not None and owner.get(held) == control:
                assert level(held) == position[control]
