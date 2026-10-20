"""Fixture effects end to end (fixture-effects-plan step 2).

``effect`` is a discrete attribute whose options are every slot and function
capability of its channel, as the colour macros' are; ``effectRate`` and
``soundSensitivity`` are scalars that start at their channel's own default
(Q2) and also parameterise an option's range. The rig
(:func:`builders.effects_rig`) has an LED-bar-like fixture (fixture 1, at 1),
a blinder-like one (fixture 2, at 11) and a wash with a sound sensitivity
channel (fixture 3, at 21).
"""

from __future__ import annotations

import pytest

from builders import effects_rig, show_of
from busk.console.prompt import hints
from busk.runner import DmxFrame, OfflineShow

# 0-based bytes of universe 1
A_DIMMER, A_EFFECT, A_RATE, A_DIRECTION = 0, 1, 2, 3
B_EFFECT, B_RATE = 11, 12
C_EFFECT, C_RATE, C_SOUND = 21, 22, 23


def dmx(frame: DmxFrame, *addresses: int) -> list[int]:
    return [frame.universes[1][address] for address in addresses]


@pytest.fixture
def offline() -> OfflineShow:
    return OfflineShow(show_of(effects_rig()))


def run(offline: OfflineShow, *lines: str) -> DmxFrame:
    for line in lines:
        reply = offline.execute(line)
        assert reply.ok, (line, reply.text)
    return offline.tick(offline.time)


def test_unprogrammed_fixtures_output_their_own_defaults(offline: OfflineShow) -> None:
    frame = offline.tick(0.0)
    # The bar: "on" (0–3) holds its defaultDmx 0, its speed stays at 255 and
    # the direction control at 0. The blinder: off (0–9), speed 0. The wash:
    # off (0–16), speed 0, sound off (the dead band's DMX 0).
    assert dmx(frame, A_EFFECT, A_RATE, A_DIRECTION) == [1, 255, 0]
    assert dmx(frame, B_EFFECT, B_RATE) == [4, 0]
    assert dmx(frame, C_EFFECT, C_RATE, C_SOUND) == [8, 0, 0]


def test_each_option_outputs_the_centre_of_its_range(offline: OfflineShow) -> None:
    frame = run(offline, "sel fixture 1", "set effect fuego")
    assert dmx(frame, A_EFFECT) == [69]  # 68–71
    frame = run(offline, "set effect off", "set effectRate 0.5")
    assert dmx(frame, A_EFFECT, A_RATE) == [197, 128]  # 140–255; 127.5, half to even
    reply = offline.execute("set effect autoProgram")
    assert not reply.ok
    assert "not offered" in reply.text


def test_one_rate_drives_a_programs_range_and_the_speed_channel(offline: OfflineShow) -> None:
    frame = run(offline, "sel fixture 2", "set effect autoProgram")
    assert dmx(frame, B_EFFECT, B_RATE) == [10, 0]  # the rate follows its channel: 0
    frame = run(offline, "set effectRate 0.5")
    assert dmx(frame, B_EFFECT, B_RATE) == [130, 128]  # 10 + 0.5 × 239 = 129.5, half to even
    frame = run(offline, "set effectRate 1")
    assert dmx(frame, B_EFFECT, B_RATE) == [249, 255]


def test_a_dead_band_and_a_repeated_range(offline: OfflineShow) -> None:
    frame = run(offline, "sel fixture 3", "set soundSensitivity 0.5", "set effectRate 0.5")
    # 6 + 0.5 × 249 = 130.5; the speed's first slow…fast range only (0–127).
    assert dmx(frame, C_SOUND, C_RATE) == [130, 64]
    frame = run(offline, "set soundSensitivity 0", "set effectRate 1")
    assert dmx(frame, C_SOUND, C_RATE) == [0, 127]


def test_a_cue_snaps_the_program_fades_the_rate_and_release_restores_defaults(
    offline: OfflineShow,
) -> None:
    run(offline, "page add 1", "sel fixture 1 thru 3", "set intensity 1", "set effect off")
    run(offline, 'record slot 1 "FX"', "clear")
    run(offline, "sel fixture 1", "set effect fuego", "set effectRate 0.25", "record cue 1/2")
    run(offline, "clear", "cue 1/2 time 2", "fader 1 1")
    frame = offline.tick(0.0)
    assert dmx(frame, A_DIMMER, A_EFFECT, A_RATE, B_EFFECT, C_EFFECT) == [255, 197, 255, 4, 8]
    offline.execute("go 1")
    frame = offline.tick(0.5)
    # fuego at once; the rate a quarter of the way from 1 to 0.25: 0.8125 × 255.
    assert dmx(frame, A_EFFECT, A_RATE) == [69, 207]
    frame = offline.tick(2.5)
    assert dmx(frame, A_EFFECT, A_RATE) == [69, 64]  # 0.25 × 255 = 63.75
    offline.execute("release 1 0")
    frame = offline.tick(3.0)
    assert dmx(frame, A_DIMMER, A_EFFECT, A_RATE) == [0, 1, 255]


def test_park_holds_a_program_over_the_programmer(offline: OfflineShow) -> None:
    frame = run(
        offline, "park fixture 2 effect soundActive", "sel fixture 2", "set effect autoProgram"
    )
    assert dmx(frame, B_EFFECT) == [252]  # 250–255
    frame = run(offline, "unpark all")
    assert dmx(frame, B_EFFECT) == [10]


def test_highlight_writes_the_effect_channels_highlight_dmx(offline: OfflineShow) -> None:
    frame = run(offline, "sel fixture 1", "set effect fuego", "set effectRate 0.5", "highlight on")
    # The effect channel's highlightDmx 1 ("on"); the speed has none and keeps
    # the programmer's value.
    assert dmx(frame, A_DIMMER, A_EFFECT, A_RATE) == [255, 1, 128]


def test_a_beam_preset_carries_a_program_across_fixture_types(offline: OfflineShow) -> None:
    run(offline, "sel fixture 1", "set effect off", "set effectRate 0.5")
    # Beam presets are per profile unless asked otherwise (gobo slots differ).
    run(offline, 'record preset beam 1 global "Stop"', "clear")
    frame = run(offline, "sel fixture 2 thru 3", "preset beam 1")
    assert dmx(frame, B_EFFECT, B_RATE, C_EFFECT, C_RATE) == [4, 128, 8, 64]


def test_a_busk_effect_moves_the_rate(offline: OfflineShow) -> None:
    layer = (
        '[{"attribute": "effectRate", "waveform": {"kind": "sine"}, "phaseOffset": 0, '
        '"mode": "absolute"}]'
    )
    run(offline, f'effect template add "Rate wave" {layer}', "sel fixture 2")
    run(offline, "set effect autoProgram", 'effect add "Rate wave" hz 1 low 0 high 1')
    # 0.5 − 0.5·cos(2πt) at 1 Hz: 0, ¼ (10 + 59.75; 63.75), 1.
    assert dmx(offline.tick(0.0), B_EFFECT, B_RATE) == [10, 0]
    assert dmx(offline.tick(1 / 6), B_EFFECT, B_RATE) == [70, 64]
    assert dmx(offline.tick(0.5), B_EFFECT, B_RATE) == [249, 255]


def test_tab_and_question_mark_offer_the_selections_programs(offline: OfflineShow) -> None:
    run(offline, "sel fixture 1 thru 3")
    console = offline._console
    assert console.expected("set effect ").words == (
        "spread", "preset", "on", "strobo", "fade", "fuego", "off", "autoProgram",
        "soundActive", "dimmerPattern1", "dimmerPattern2",
    )  # fmt: skip
    assert hints(console, "set effect dim", 80)[0] == "next: dimmerPattern1  dimmerPattern2"
    assert console.expected("park fixture 2 effect ").words == (
        "off", "autoProgram", "soundActive",
    )  # fmt: skip
