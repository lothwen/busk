"""The TUI's colours (``busk_tui.colors``, spec §4.1, §4.2)."""

from __future__ import annotations

import pytest

from busk_tui import colors


@pytest.mark.parametrize("name", sorted(colors.PALETTE))
def test_each_token_is_its_xterm_colour(name: str) -> None:
    token = colors.PALETTE[name]
    red, green, blue = colors.xterm_rgb(token.xterm)
    assert token.hex == f"#{red:02x}{green:02x}{blue:02x}"


def test_below_one_and_a_half_percent_is_unlit() -> None:
    assert colors.displayed((1.0, 1.0, 1.0), 0.014) is None
    assert colors.swatch((1.0, 0.0, 0.0), 0.0, "256") == "color(236)"
    assert colors.swatch((1.0, 0.0, 0.0), 0.01, "truecolor") == "color(236)"
    assert colors.displayed((1.0, 1.0, 1.0), 0.015) is not None


def test_low_levels_stay_visible() -> None:
    assert colors.displayed((1.0, 0.0, 0.0), 1.0) == (255, 0, 0)
    assert colors.displayed((1.0, 0.0, 0.0), 0.5) == (150, 0, 0)  # 0.18 + 0.82 × 0.5
    assert colors.displayed((0.0, 1.0, 0.0), 0.02) == (0, 50, 0)


def test_256_takes_the_cube_or_the_grey_ramp_whichever_is_closer() -> None:
    assert colors.nearest_256((255, 0, 0)) == 196
    assert colors.nearest_256((95, 95, 95)) == 59  # exact in the cube
    assert colors.nearest_256((100, 100, 100)) == 241  # ramp (98) beats cube (95)
    assert colors.nearest_256((128, 128, 128)) == 244
    assert colors.nearest_256((0, 0, 0)) == 16
    assert colors.nearest_256((255, 135, 0)) == 208


def test_16_takes_the_nearest_ansi_colour() -> None:
    assert colors.nearest_16((250, 10, 10)) == 9
    assert colors.nearest_16((128, 128, 128)) == 8
    assert colors.nearest_16((10, 10, 10)) == 0
    assert colors.nearest_16((0, 0, 230)) == 4


def test_a_swatch_in_each_mode() -> None:
    red = (1.0, 0.0, 0.0)
    assert colors.swatch(red, 1.0, "truecolor") == "#ff0000"
    assert colors.swatch(red, 1.0, "256") == "color(196)"
    assert colors.swatch(red, 1.0, "16") == "color(9)"
