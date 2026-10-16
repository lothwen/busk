"""Playback buttons (phase-6-plan §5.2, decisions 3, 8 and 10).

``PLAYBACK_BUTTON`` applies the function in the playback's ``buttons[button]``
in the engine: each function does what its command does, a flash pressed
through a slot is released on its own playback whatever the page is by then,
``goto`` buttons go to the playback's ``gotoCue``, and ``BLACKOUT`` without
``on`` toggles in the engine.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from builders import compile_doc
from busk.commands.types import Command, CommandOrigin
from busk.compiler.compile import CompiledShow
from busk.engine.install import EMPTY_FRAME, Install
from busk.engine.snapshot import PlaybackStatus
from busk.model.common import PlaybackId
from harness import Harness, Observation, back, fader, flash, go, goto, release, toggle, trigger

# pb-song carries every function. Page 1 holds pb-song on slot 0 and pb-blue
# (toggle, flash) on slot 2; page 2 holds pb-blue, pb-song and pb-pulse.
BUTTONS = ["go", "back", "goto", "flash", "toggle", "release", "select", "none", "swop"]
GO, BACK, GOTO, FLASH = 0, 1, 2, 3
BLUE_FLASH = 1


@pytest.fixture
def doc(appendix_a: dict[str, Any]) -> dict[str, Any]:
    song = appendix_a["playbacks"][0]
    song.update(buttons=BUTTONS, gotoCue="2", autoStart=False)
    appendix_a["pages"].append(
        {"id": "page-2", "number": 2, "name": "Two", "slots": ["pb-blue", "pb-song", "pb-pulse"]}
    )
    return appendix_a


@pytest.fixture
def show(doc: dict[str, Any]) -> CompiledShow:
    return compile_doc(doc)


def _command(**fields: Any) -> Command:
    return cast(Command, fields)


def button(index: int, down: bool, **target: Any) -> Command:
    """A ``PLAYBACK_BUTTON`` naming ``playbackId=`` or ``slot=``."""
    return _command(type="PLAYBACK_BUTTON", button=index, down=down, **target)


def press(harness: Harness, command: Command, control: str | None = None) -> None:
    """Submit ``command`` as a MIDI binding ``control`` would (no control: a jump source)."""
    origin = CommandOrigin(surfaceId=cast(Any, "s-midi"))
    if control is not None:
        origin["control"] = control
    harness.engine.bus.submit(command, origin)


def status(observed: Observation, ident: str) -> PlaybackStatus:
    assert observed.snapshot is not None
    return next(p for p in observed.snapshot.playbacks if p.id == ident)


def flashing(harness: Harness) -> set[str]:
    runtimes = harness.engine.runtime.playbacks.runtimes
    return {ident for ident, runtime in runtimes.items() if runtime.flashButton}


def same(left: Observation, right: Observation) -> bool:
    assert left.snapshot is not None
    assert right.snapshot is not None
    return (left.snapshot.playbacks, left.universe) == (right.snapshot.playbacks, right.universe)


# ----------------------------------------------------------- every function

PRE_STATES: dict[str, list[Command]] = {
    "idle": [],
    "on cue 1": [trigger("pb-song")],
    "on cue 2": [trigger("pb-song"), go("pb-song")],
}


@pytest.mark.parametrize(
    ("index", "on_down", "on_up"),
    [
        (GO, [go("pb-song")], []),
        (BACK, [back("pb-song")], []),
        (GOTO, [goto("pb-song", "2")], []),
        (FLASH, [flash("pb-song", True)], [flash("pb-song", False)]),
        (4, [toggle("pb-song")], []),
        (5, [release("pb-song")], []),
        (6, [], []),  # select: a programmer command, which the binding resolver sends
        (7, [], []),  # none
        (9, [], []),  # beyond the playback's buttons
    ],
    ids=["go", "back", "goto", "flash", "toggle", "release", "select", "none", "button 9"],
)
@pytest.mark.parametrize("pre", list(PRE_STATES))
def test_each_function_does_what_its_command_does(
    show: CompiledShow, pre: str, index: int, on_down: list[Command], on_up: list[Command]
) -> None:
    pressed, direct = Harness(show), Harness(show)
    for harness in (pressed, direct):
        harness.submit(fader("pb-song", 1.0), *PRE_STATES[pre])
        harness.tick(0.0)
        harness.tick(5.0)  # every fade settled
    pressed.submit(button(index, True, playbackId="pb-song"))
    direct.submit(*on_down)
    assert same(pressed.tick(5.1), direct.tick(5.1))
    pressed.submit(button(index, False, playbackId="pb-song"))
    direct.submit(*on_up)
    assert same(pressed.tick(5.2), direct.tick(5.2))
    assert same(pressed.tick(20.0), direct.tick(20.0))
    assert pressed.engine.stats.commandErrors == 0


def test_a_slot_resolves_on_the_current_page(show: CompiledShow) -> None:
    harness = Harness(show)
    harness.submit(button(GO, True, slot=0))
    assert status(harness.tick(0.0), "pb-song").state == "active"
    harness.submit(_command(type="PAGE", number=2), button(0, True, slot=0))  # pb-blue: toggle
    observed = harness.tick(0.1)
    assert status(observed, "pb-blue").state == "active"
    assert status(observed, "pb-song").cue == "1"  # untouched by the second press


def test_an_empty_slot_or_a_missing_button_does_nothing(show: CompiledShow) -> None:
    harness = Harness(show)
    before = harness.tick(0.0)
    harness.submit(
        button(GO, True, slot=1),  # empty on page 1
        button(GO, True, slot=40),  # beyond the page
        button(4, True, slot=2),  # pb-blue has two buttons
    )
    assert same(harness.tick(0.1), before)
    assert harness.engine.stats.commandErrors == 0
    assert harness.engine.stats.commandsApplied == 3


# ------------------------------------------------------------- held buttons


def test_a_flash_held_across_a_page_change_is_released_on_its_own_playback(
    show: CompiledShow,
) -> None:
    harness = Harness(show)
    press(harness, button(FLASH, True, slot=0), control="b-flash")
    press(harness, button(BLUE_FLASH, True, slot=2), control="b-blue")
    harness.tick(0.0)
    assert flashing(harness) == {"pb-song", "pb-blue"}
    # On page 2, slot 0 is pb-blue (no button 3) and slot 2 is pb-pulse.
    harness.submit(_command(type="PAGE", number=2))
    harness.tick(0.1)
    press(harness, button(FLASH, False, slot=0), control="b-flash")
    harness.tick(0.2)
    assert flashing(harness) == {"pb-blue"}
    press(harness, button(BLUE_FLASH, False, slot=2), control="b-blue")
    harness.tick(0.3)
    assert flashing(harness) == set()
    assert harness.engine.stats.commandErrors == 0


def test_held_flashes_are_kept_per_control(show: CompiledShow) -> None:
    """Two controls on the same slot of two pages each release their own flash."""
    harness = Harness(show)
    press(harness, button(FLASH, True, slot=0), control="a")  # pb-song
    harness.submit(_command(type="PAGE", number=2))
    press(harness, button(BLUE_FLASH, True, slot=0), control="b")  # pb-blue
    harness.tick(0.0)
    assert flashing(harness) == {"pb-song", "pb-blue"}
    press(harness, button(FLASH, False, slot=0), control="a")  # pb-blue has no button 3
    harness.tick(0.1)
    assert flashing(harness) == {"pb-blue"}  # a's release went to pb-song
    press(harness, button(BLUE_FLASH, False, slot=0), control="b")
    harness.tick(0.2)
    assert flashing(harness) == set()


def test_a_release_with_nothing_held_resolves_its_slot(show: CompiledShow) -> None:
    harness = Harness(show)
    harness.submit(flash("pb-song", True))  # by id: nothing is recorded
    harness.tick(0.0)
    press(harness, button(FLASH, False, slot=0), control="b-flash")
    harness.tick(0.1)
    assert flashing(harness) == set()


def test_a_release_applies_the_function_that_was_pressed(
    doc: dict[str, Any], show: CompiledShow
) -> None:
    """A live edit turning the held flash button into ``go`` still lets the
    flash go, and does not GO."""
    harness = Harness(show)
    press(harness, button(FLASH, True, slot=0), control="b-flash")
    harness.tick(0.0)
    doc["playbacks"][0]["buttons"][FLASH] = "go"
    harness.engine.bus.install(
        Install(compiled=compile_doc(doc), remap=None, programmer=EMPTY_FRAME)
    )
    harness.tick(0.1)
    press(harness, button(FLASH, False, slot=0), control="b-flash")
    observed = harness.tick(0.2)
    assert flashing(harness) == set()
    assert status(observed, "pb-song").state == "idle"
    assert harness.engine.stats.commandErrors == 0


# ------------------------------------------------------------------- goto


def test_the_compiler_finds_the_goto_cue(doc: dict[str, Any]) -> None:
    def goto_cue(number: str | None) -> int | None:
        if number is None:
            doc["playbacks"][0].pop("gotoCue", None)
        else:
            doc["playbacks"][0]["gotoCue"] = number
        return compile_doc(doc).playbacks[PlaybackId("pb-song")].gotoCue

    assert goto_cue("2") == 1
    assert goto_cue("02") == 1  # numbers compare as integer parts
    assert goto_cue("1") == 0
    assert goto_cue("7") is None  # validation warns
    assert goto_cue(None) is None


@pytest.mark.parametrize("active", [False, True], ids=["idle", "active"])
def test_goto_goes_to_the_goto_cue(show: CompiledShow, active: bool) -> None:
    harness = Harness(show)
    if active:
        harness.submit(trigger("pb-song"))
    harness.submit(button(GOTO, True, slot=0))
    observed = harness.tick(0.0)
    assert (status(observed, "pb-song").state, status(observed, "pb-song").cue) == ("active", "2")


@pytest.mark.parametrize("active", [False, True], ids=["idle", "active"])
def test_goto_without_a_goto_cue_does_nothing(doc: dict[str, Any], active: bool) -> None:
    del doc["playbacks"][0]["gotoCue"]
    show = compile_doc(doc)
    harness, untouched = Harness(show), Harness(show)
    for engine in (harness, untouched):
        engine.submit(fader("pb-song", 1.0), *([trigger("pb-song")] if active else []))
        engine.tick(0.0)
    harness.submit(button(GOTO, True, slot=0))
    after = harness.tick(0.1)
    assert same(after, untouched.tick(0.1))
    expected = ("active", "1") if active else ("idle", None)
    assert (status(after, "pb-song").state, status(after, "pb-song").cue) == expected
    assert harness.engine.stats.commandErrors == 0


# --------------------------------------------------------------- blackout


def test_blackout_toggles_in_the_engine_whatever_the_source(show: CompiledShow) -> None:
    harness = Harness(show)
    toggle_bo = _command(type="BLACKOUT")

    def blackout_after(*sources: str) -> bool:
        for source in sources:
            harness.engine.bus.submit(toggle_bo, CommandOrigin(surfaceId=cast(Any, source)))
        harness.tick(harness.clock.now() + 0.1)
        assert harness.engine.snapshot is not None
        return harness.engine.snapshot.blackout

    assert blackout_after("s-midi") is True
    assert blackout_after("s-web") is False  # another surface toggles the same state
    assert blackout_after("s-midi", "s-web") is False  # two toggles in one tick
    harness.submit(_command(type="BLACKOUT", on=True))
    assert blackout_after() is True
    harness.submit(_command(type="BLACKOUT", on=True))
    assert blackout_after() is True  # `on` sets, it does not toggle
    assert blackout_after("s-web") is False
