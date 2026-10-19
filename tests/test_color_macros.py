"""Colour macros and colour effects end to end (color-macros-plan step 2).

``colorMacro`` and ``colorEffect`` are discrete attributes whose options are
every slot and function capability of their channel; ``colorMacroRate`` is the
speed of a program, a channel of its own or the parameter of a program's
range. Nothing controls them: the channel's own default option. The rig
(:func:`builders.macro_rig`) has two RGB pars with macro, rate and effect
channels (fixtures 1 and 2, at 1 and 11) and a macro-only fixture whose
default is a black preset (fixture 3, at 21), like the Wild Wash Pro 648 in
its 5Ch mode.
"""

from __future__ import annotations

import pytest

from builders import macro_rig, show_of
from busk.runner import DmxFrame, OfflineShow

# 0-based bytes of universe 1
A_DIMMER, A_MACRO, A_RATE, A_EFFECT = 0, 4, 5, 6
B_MACRO = 14
C_DIMMER, C_MACRO = 20, 21


def dmx(frame: DmxFrame, *addresses: int) -> list[int]:
    return [frame.universes[1][address] for address in addresses]


@pytest.fixture
def offline() -> OfflineShow:
    return OfflineShow(show_of(macro_rig()))


def run(offline: OfflineShow, *lines: str) -> DmxFrame:
    for line in lines:
        reply = offline.execute(line)
        assert reply.ok, (line, reply.text)
    return offline.tick(offline.time)


def test_uncontrolled_macros_output_the_option_of_their_default(offline: OfflineShow) -> None:
    frame = offline.tick(0.0)
    # off (0–9), the rate at its default 0.5, the effect off (0–9); fixture
    # 3's default selects its black preset (0–5), as its own chart says.
    assert dmx(frame, A_MACRO, A_RATE, A_EFFECT, B_MACRO, C_MACRO) == [4, 128, 4, 4, 2]


def test_an_option_goes_to_every_selected_fixture_that_offers_it(offline: OfflineShow) -> None:
    frame = run(offline, "sel fixture 1 thru 3", "set colorMacro red")
    assert dmx(frame, A_MACRO, B_MACRO, C_MACRO) == [14, 14, 9]  # red: 10–19, 6–13
    reply = offline.execute("set colorMacro soundActive")
    assert "1 option not offered" in reply.text
    frame = offline.tick(0.0)
    assert dmx(frame, A_MACRO, B_MACRO, C_MACRO) == [227, 227, 9]


def test_a_program_takes_its_speed_from_the_rate(offline: OfflineShow) -> None:
    frame = run(offline, "sel fixture 1, fixture 3", "set colorMacro colourChange")
    # The rate's default 0.5 through 40–199 and 22–255, half to even.
    assert dmx(frame, A_MACRO, A_RATE, C_MACRO) == [120, 128, 138]
    frame = run(offline, "set colorMacroRate 1")
    assert dmx(frame, A_MACRO, A_RATE, C_MACRO) == [199, 255, 255]
    frame = run(offline, "set colorMacroRate 0")
    assert dmx(frame, A_MACRO, A_RATE, C_MACRO) == [40, 0, 22]


def test_a_colour_effect_shares_the_rate(offline: OfflineShow) -> None:
    frame = run(offline, "sel fixture 1", "set colorEffect colorFade", "set colorMacroRate 0.5")
    assert dmx(frame, A_EFFECT) == [192]  # 128 + 0.5 × 127 = 191.5, half to even
    frame = run(offline, "set colorEffect colorJump")
    assert dmx(frame, A_EFFECT) == [68]  # 10 + 0.5 × 117 = 68.5


def test_a_cue_snaps_its_macro_at_the_start_and_release_restores_the_default(
    offline: OfflineShow,
) -> None:
    run(offline, "page add 1", "sel fixture 1", "set intensity 1", "set colorMacro green")
    run(offline, 'record slot 1 "G"')
    run(offline, "clear", "cue 1/1 time 2")
    offline.execute("fader 1 1")
    frame = offline.tick(0.5)
    assert dmx(frame, A_MACRO) == [24]  # green (20–29) at once, the dimmer still fading
    assert 0 < dmx(frame, A_DIMMER)[0] < 255
    frame = offline.tick(2.5)
    assert dmx(frame, A_DIMMER, A_MACRO) == [255, 24]
    offline.execute("release 1 0")
    frame = offline.tick(3.0)
    assert dmx(frame, A_DIMMER, A_MACRO) == [0, 4]


def test_park_holds_a_macro_over_the_programmer(offline: OfflineShow) -> None:
    frame = run(offline, "park fixture 3 colorMacro white", "sel fixture 3", "set colorMacro red")
    assert dmx(frame, C_MACRO) == [17]  # white: 14–21
    frame = run(offline, "unpark all")
    assert dmx(frame, C_MACRO) == [9]


def test_a_colour_preset_carries_a_macro_across_fixture_types(offline: OfflineShow) -> None:
    run(offline, "sel fixture 1", "set colorMacro red", 'record preset color 1 "Red macro"')
    run(offline, "clear")
    frame = run(offline, "sel fixture 2 thru 3", "preset color 1")
    assert dmx(frame, B_MACRO, C_MACRO) == [14, 9]


def test_highlight_writes_the_macro_channels_highlight_dmx(offline: OfflineShow) -> None:
    frame = run(offline, "sel fixture 1", "set colorEffect colorFade", "highlight on")
    # The macro channel's highlightDmx 35 (white); the effect has none and
    # keeps the programmer's value.
    assert dmx(frame, A_DIMMER, A_MACRO, A_EFFECT) == [255, 35, 192]
