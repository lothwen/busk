"""Phase spread across an effect's ordered members (spec §10.2, phase-5-plan decision 5)."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from busk.compiler.effects import member_offsets, spread_positions
from busk.model.effect import EffectPhase

FULL = EffectPhase(start=0.0, end=360.0)


def positions(count: int, **spread: int) -> list[int]:
    return spread_positions(count, **spread).tolist()


@pytest.mark.parametrize(
    ("count", "spread", "expected"),
    [
        # No spread: every member its own position.
        (4, {}, [0, 1, 2, 3]),
        # Wings, even N: two mirrored halves.
        (8, {"wings": 2}, [0, 1, 2, 3, 3, 2, 1, 0]),
        # Wings, uneven N: the short last wing is the start of its mirror.
        (5, {"wings": 2}, [0, 1, 2, 2, 1]),
        (7, {"wings": 3}, [0, 1, 2, 2, 1, 0, 0]),
        # Three wings mirror back and forth.
        (9, {"wings": 3}, [0, 1, 2, 2, 1, 0, 0, 1, 2]),
        # More wings than members: every member is position 0.
        (3, {"wings": 4}, [0, 0, 0]),
        # Blocks: neighbours share a position.
        (6, {"blocks": 2}, [0, 0, 1, 1, 2, 2]),
        (5, {"blocks": 2}, [0, 0, 1, 1, 2]),
        # Groups: members cycle through a few positions.
        (6, {"groups": 3}, [0, 1, 2, 0, 1, 2]),
        (6, {"groups": 1}, [0, 1, 2, 3, 4, 5]),
        (2, {"groups": 5}, [0, 1]),
        # The steps compose in order: wings, then blocks, then groups.
        (8, {"wings": 2, "blocks": 2}, [0, 0, 1, 1, 1, 1, 0, 0]),
        (12, {"wings": 2, "groups": 3}, [0, 1, 2, 0, 1, 2, 2, 1, 0, 2, 1, 0]),
        # N = 1 and N = 0.
        (1, {"wings": 2, "blocks": 3, "groups": 4}, [0]),
        (0, {"wings": 2}, []),
    ],
)
def test_positions(count: int, spread: dict[str, int], expected: list[int]) -> None:
    assert positions(count, **spread) == expected


def test_a_full_turn_spreads_members_evenly_around_the_cycle() -> None:
    """§10.2 divides by M, not M − 1: four members land a quarter apart, and
    the last does not repeat the first."""
    np.testing.assert_allclose(member_offsets(4, FULL), [0.0, 0.25, 0.5, 0.75])


def test_the_bar_mirrored_with_wings() -> None:
    """The 12 cells of the §5.14 bar with ``wings`` 2: the wave runs out from
    the middle (or in to it) symmetrically."""
    expected = np.array([0, 1, 2, 3, 4, 5, 5, 4, 3, 2, 1, 0]) / 6
    np.testing.assert_allclose(member_offsets(12, FULL, wings=2), expected)


def test_offsets_are_in_cycles_from_start_to_end() -> None:
    offsets = member_offsets(3, EffectPhase(start=90.0, end=0.0))
    np.testing.assert_allclose(offsets * 360, [90.0, 60.0, 30.0])


def test_a_single_member_sits_at_the_start() -> None:
    np.testing.assert_allclose(member_offsets(1, EffectPhase(start=45.0, end=360.0)), [0.125])
    assert member_offsets(0, FULL).shape == (0,)


@given(
    count=st.integers(1, 40),
    wings=st.integers(1, 6),
    blocks=st.integers(1, 6),
    groups=st.integers(1, 6),
    start=st.floats(-720, 720),
    end=st.floats(-720, 720),
)
def test_offsets_are_evenly_spaced_over_start_to_end(
    count: int, wings: int, blocks: int, groups: int, start: float, end: float
) -> None:
    spread = {"wings": wings, "blocks": blocks, "groups": groups}
    k = spread_positions(count, **spread)
    used = sorted(set(k.tolist()))
    assert used == list(range(len(used)))  # exactly 0 … M − 1
    offsets = member_offsets(count, EffectPhase(start=start, end=end), **spread) * 360
    m = len(used)
    np.testing.assert_allclose(offsets, start + (end - start) * k / m, atol=1e-9)
    assert offsets[0] == pytest.approx(start)
