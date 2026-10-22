"""Resolver: each §7.3 (LTP) and §7.4 (HTP) behaviour, the snap thresholds,
the per-lane weights of slot-by-slot fades, the §7.5 relative pass with
continuous suppression (phase-5-plan §5.6), and the attribution of each lane
to what drives it (GAP-01).

Every resolve and attribution here is also checked against the per-slot
oracle (``reference_resolver.py``).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

import numpy as np
import pytest
from numpy.typing import NDArray

from builders import busk_rig, compile_doc, lanes_of, slot_of
from busk.compiler.compile import CompiledShow
from busk.compiler.cues import cue_from_values
from busk.engine.contributions import SORT_KEY, Relative, Source, gather, gather_relatives
from busk.engine.resolver import Resolver
from reference_resolver import reference_attribute, reference_resolve

type Values = dict[tuple[str, str], list[float]]


@pytest.fixture(scope="module")
def compiled() -> CompiledShow:
    """Two Appendix A spots (``fx-mh1``, ``fx-mh2``)."""
    return compile_doc(busk_rig(spots=2))


def source(
    compiled: CompiledShow,
    values: Values,
    *,
    seq: int,
    priority: int = 50,
    htp: float = 1.0,
    scale: float = 1.0,
    ltp: float = 1.0,
) -> Source:
    """A source playing ``values`` (``(fixture, attribute) → lanes``) at the given weights."""
    by_slot = {slot_of(compiled, f, a).index: lanes for (f, a), lanes in values.items()}
    made = Source.of_cue(f"s{seq}", priority, cue_from_values(compiled.slots, by_slot))
    made.seq, made.htpWeight, made.intensityScale, made.ltpWeight = seq, htp, scale, ltp
    return made


def weigh(compiled: CompiledShow, made: Source, weights: dict[tuple[str, str], float]) -> Source:
    """Give ``made`` per-lane weights: ``(fixture, attribute) → weight`` for the
    named slots, 1 for its other lanes."""
    slots = compiled.slots
    by_slot = {slot_of(compiled, f, a).index: w for (f, a), w in weights.items()}

    def per_lane(lanes: NDArray[np.intp]) -> NDArray[np.float64]:
        return np.array([by_slot.get(int(slots.laneSlot[lane]), 1.0) for lane in lanes])

    made.htpWeights = per_lane(slots.intensityLanes[made.htpPos])
    made.ltpWeights = per_lane(made.ltpLanes)
    made.snapWeights = per_lane(made.snapLanes)
    return made


def resolve(
    compiled: CompiledShow, *sources: Source, relatives: Sequence[Relative] = ()
) -> NDArray[np.float64]:
    """Resolve over the defaults with the production resolver, checked against the oracle."""
    ordered = sorted(sources, key=SORT_KEY)
    frame = np.empty(compiled.slots.laneCount)
    present = gather_relatives(relatives, [])
    Resolver(compiled.slots).resolve(ordered, compiled.slots.defaultFrame, frame, present)
    expected = reference_resolve(compiled.slots, ordered, compiled.slots.defaultFrame, relatives)
    np.testing.assert_allclose(frame, expected, rtol=0, atol=1e-12, equal_nan=True)
    return frame


def relative(
    compiled: CompiledShow,
    op: Literal["add", "multiply"],
    amounts: dict[tuple[str, str], float],
    *,
    seq: int,
    priority: int = 50,
    order: int = 0,
    weight: float = 1.0,
    weights: list[float] | None = None,
    clamp: tuple[float, float] | None = None,
) -> Relative:
    """A relative contribution: ``(fixture, attribute) → amount`` on each
    slot's (first) lane."""
    lanes = [slot_of(compiled, f, a).laneOffset for f, a in amounts]
    return Relative(
        priority=priority,
        seq=seq,
        order=order,
        op=op,
        lanes=np.array(lanes, dtype=np.intp),
        amounts=np.array(list(amounts.values()), dtype=np.float64),
        weights=None if weights is None else np.array(weights, dtype=np.float64),
        weight=weight,
        clamp=clamp,
    )


def pan(compiled: CompiledShow, frame: NDArray[np.float64], fixture: str = "fx-mh1") -> float:
    return lanes_of(compiled, frame, fixture, "pan")[0]


def intensity(compiled: CompiledShow, frame: NDArray[np.float64], fixture: str = "fx-mh1") -> float:
    return lanes_of(compiled, frame, fixture, "intensity")[0]


def test_no_sources_gives_the_defaults(compiled: CompiledShow) -> None:
    np.testing.assert_array_equal(resolve(compiled), compiled.slots.defaultFrame)


# ----------------------------------------------------------------- §7.3 LTP


def test_the_newest_source_wins(compiled: CompiledShow) -> None:
    a = {("fx-mh1", "pan"): [10.0]}
    b = {("fx-mh1", "pan"): [20.0]}
    assert (
        pan(compiled, resolve(compiled, source(compiled, a, seq=1), source(compiled, b, seq=2)))
        == 20
    )
    assert (
        pan(compiled, resolve(compiled, source(compiled, a, seq=2), source(compiled, b, seq=1)))
        == 10
    )


def test_a_source_at_a_quarter_sits_a_quarter_of_the_way(compiled: CompiledShow) -> None:
    below = source(compiled, {("fx-mh1", "pan"): [40.0]}, seq=1)
    fading = source(compiled, {("fx-mh1", "pan"): [80.0]}, seq=2, ltp=0.25)
    assert pan(compiled, resolve(compiled, below, fading)) == 50.0


def test_a_release_glides_back_to_the_next_source_down(compiled: CompiledShow) -> None:
    below = source(compiled, {("fx-mh1", "pan"): [40.0]}, seq=1)
    released = [
        pan(
            compiled,
            resolve(compiled, below, source(compiled, {("fx-mh1", "pan"): [80.0]}, seq=2, ltp=w)),
        )
        for w in (1.0, 0.75, 0.5, 0.25, 0.0)
    ]
    assert released == [80.0, 70.0, 60.0, 50.0, 40.0]


def test_a_higher_band_beats_a_newer_lower_one(compiled: CompiledShow) -> None:
    override = source(compiled, {("fx-mh1", "pan"): [10.0]}, seq=1, priority=200)
    newer = source(compiled, {("fx-mh1", "pan"): [20.0]}, seq=2, priority=50)
    assert pan(compiled, resolve(compiled, override, newer)) == 10.0


def test_partial_state_leaves_other_slots_alone(compiled: CompiledShow) -> None:
    frame = resolve(compiled, source(compiled, {("fx-mh1", "pan"): [33.0]}, seq=1))
    changed = np.flatnonzero(~np.isclose(frame, compiled.slots.defaultFrame, equal_nan=True))
    assert changed.tolist() == [slot_of(compiled, "fx-mh1", "pan").laneOffset]


# ----------------------------------------------------------------- snapping


def test_discrete_lanes_snap_at_start(compiled: CompiledShow) -> None:
    breakup = {("fx-mh1", "gobo1"): [1.0]}
    assert lanes_of(
        compiled, resolve(compiled, source(compiled, breakup, seq=1, ltp=0.0)), "fx-mh1", "gobo1"
    ) == [0.0]
    for weight in (1e-9, 0.5, 1.0):
        frame = resolve(compiled, source(compiled, breakup, seq=1, ltp=weight))
        assert lanes_of(compiled, frame, "fx-mh1", "gobo1") == [1.0]


@pytest.mark.parametrize(("weight", "w_lane"), [(0.49, math.nan), (0.5, 0.25), (0.9, 0.25)])
def test_colour_extras_snap_at_the_middle(
    compiled: CompiledShow, weight: float, w_lane: float
) -> None:
    frame = resolve(
        compiled, source(compiled, {("fx-mh1", "color"): [0.0, 0.0, 1.0, 0.25]}, seq=1, ltp=weight)
    )
    r, g, b, w = lanes_of(compiled, frame, "fx-mh1", "color")
    assert (r, g, b) == pytest.approx((1 - weight, 1 - weight, 1.0))  # from white
    assert w == pytest.approx(w_lane, nan_ok=True)


def test_snap_at_end(compiled: CompiledShow) -> None:
    # No registry attribute snaps at the end; a hand-made snap lane exercises it.
    lane = slot_of(compiled, "fx-mh1", "zoom").laneOffset
    made = source(compiled, {}, seq=1)
    made.snapLanes, made.snapValues = np.array([lane]), np.array([30.0])
    made.snapThresholds = np.array([1.0])
    resolver, frame = Resolver(compiled.slots), np.empty(compiled.slots.laneCount)
    for weight, zoom in ((0.999, 21.0), (1.0, 30.0)):
        made.ltpWeight = weight
        resolver.resolve([made], compiled.slots.defaultFrame, frame)
        assert frame[lane] == zoom


# ----------------------------------------------------------------- §7.4 HTP


def test_the_base_band_is_classic_htp(compiled: CompiledShow) -> None:
    verse = source(compiled, {("fx-mh1", "intensity"): [0.4]}, seq=1)
    chorus = source(compiled, {("fx-mh1", "intensity"): [1.0]}, seq=2, scale=0.6)
    assert intensity(compiled, resolve(compiled, verse, chorus)) == pytest.approx(0.6)
    fading = source(compiled, {("fx-mh1", "intensity"): [0.8]}, seq=1, htp=0.5)
    assert intensity(compiled, resolve(compiled, fading)) == pytest.approx(0.4)  # ramps from 0


def test_an_override_band_crossfades_by_its_presence(compiled: CompiledShow) -> None:
    look = source(compiled, {("fx-mh1", "intensity"): [0.8]}, seq=1)
    weights = (0.0, 0.5, 1.0)  # a 2 s override at 0, 1 and 2 s
    results = [
        intensity(
            compiled,
            resolve(
                compiled,
                look,
                source(compiled, {("fx-mh1", "intensity"): [1.0]}, seq=2, priority=200, htp=w),
            ),
        )
        for w in weights
    ]
    assert results == pytest.approx([0.8, 0.9, 1.0])


def test_a_source_fading_in_cannot_pull_below_one_fully_up(compiled: CompiledShow) -> None:
    up = source(compiled, {("fx-mh1", "intensity"): [0.8]}, seq=1)
    fading = source(compiled, {("fx-mh1", "intensity"): [0.2]}, seq=2, htp=0.3)
    assert intensity(compiled, resolve(compiled, up, fading)) == pytest.approx(0.8)


def test_an_active_override_with_its_fader_at_zero_kills_intensity(compiled: CompiledShow) -> None:
    look = source(compiled, {("fx-mh1", "intensity"): [0.8]}, seq=1)
    kill = source(compiled, {("fx-mh1", "intensity"): [1.0]}, seq=2, priority=200, scale=0.0)
    assert intensity(compiled, resolve(compiled, look, kill)) == 0.0


def test_a_band_without_intensity_keeps_the_intensity_below(compiled: CompiledShow) -> None:
    look = source(compiled, {("fx-mh1", "intensity"): [0.8]}, seq=1)
    colour = source(compiled, {("fx-mh1", "color"): [0.0, 0.0, 1.0, math.nan]}, seq=2, priority=200)
    assert intensity(compiled, resolve(compiled, look, colour)) == 0.8
    assert intensity(compiled, resolve(compiled, look, colour), "fx-mh2") == 0.0


def test_lanes_a_band_does_not_touch_keep_their_value(compiled: CompiledShow) -> None:
    mh1 = source(compiled, {("fx-mh1", "intensity"): [0.7]}, seq=1)
    mh2_override = source(compiled, {("fx-mh2", "intensity"): [0.3]}, seq=2, priority=200)
    frame = resolve(compiled, mh1, mh2_override)
    assert (intensity(compiled, frame), intensity(compiled, frame, "fx-mh2")) == (0.7, 0.3)


# --------------------------------------------------------- per-lane weights


def test_per_lane_ltp_weights_fade_each_slot_on_its_own(compiled: CompiledShow) -> None:
    look = {("fx-mh1", "pan"): [40.0], ("fx-mh1", "tilt"): [40.0]}
    below = source(compiled, look, seq=1)
    move = {("fx-mh1", "pan"): [80.0], ("fx-mh1", "tilt"): [80.0]}
    fading = weigh(compiled, source(compiled, move, seq=2), {("fx-mh1", "pan"): 0.25})
    frame = resolve(compiled, below, fading)
    assert (pan(compiled, frame), lanes_of(compiled, frame, "fx-mh1", "tilt")[0]) == (50.0, 80.0)
    fading.ltpWeight = 0.5  # the scalar multiplies: pan at 0.125, tilt at 0.5
    frame = resolve(compiled, below, fading)
    assert (pan(compiled, frame), lanes_of(compiled, frame, "fx-mh1", "tilt")[0]) == (45.0, 60.0)


@pytest.mark.parametrize(("weight", "red"), [(0.0, 0.3), (1.0, 0.9)])
def test_per_lane_ltp_weights_are_exact_at_both_ends(
    compiled: CompiledShow, weight: float, red: float
) -> None:
    # 0.3 + (0.9 − 0.3) · 1 is 0.9000000000000001; a settled slot must output 0.9.
    below = source(compiled, {("fx-mh1", "color"): [0.3, 0.3, 0.3, 0.0]}, seq=1)
    above = source(compiled, {("fx-mh1", "color"): [0.9, 0.9, 0.9, 0.0]}, seq=2)
    weigh(compiled, above, {("fx-mh1", "color"): weight})
    assert lanes_of(compiled, resolve(compiled, below, above), "fx-mh1", "color")[0] == red


@pytest.mark.parametrize(
    ("scalar", "lane", "gobo", "w_lane"),
    [(1.0, 0.0, 0.0, math.nan), (1.0, 1e-9, 1.0, math.nan), (1.0, 0.5, 1.0, 0.25),
     (0.5, 0.99, 1.0, math.nan), (0.5, 1.0, 1.0, 0.25)],
)  # fmt: skip
def test_per_lane_snap_weights_reach_each_lanes_threshold(
    compiled: CompiledShow, scalar: float, lane: float, gobo: float, w_lane: float
) -> None:
    values = {("fx-mh1", "gobo1"): [1.0], ("fx-mh1", "color"): [0.0, 0.0, 1.0, 0.25]}
    made = source(compiled, values, seq=1, ltp=scalar)
    weigh(compiled, made, {("fx-mh1", "gobo1"): lane, ("fx-mh1", "color"): lane})
    frame = resolve(compiled, made)
    assert lanes_of(compiled, frame, "fx-mh1", "gobo1") == [gobo]  # snaps at start
    assert lanes_of(compiled, frame, "fx-mh1", "color")[3] == pytest.approx(w_lane, nan_ok=True)


def test_per_lane_htp_weights_are_presence_per_lane(compiled: CompiledShow) -> None:
    both = {("fx-mh1", "intensity"): [0.8], ("fx-mh2", "intensity"): [0.8]}
    fading = weigh(compiled, source(compiled, both, seq=1), {("fx-mh1", "intensity"): 0.5})
    frame = resolve(compiled, fading)
    assert (intensity(compiled, frame), intensity(compiled, frame, "fx-mh2")) == (0.4, 0.8)


def test_a_lane_at_zero_in_a_higher_band_keeps_what_is_below(compiled: CompiledShow) -> None:
    look = source(compiled, {("fx-mh1", "intensity"): [0.8], ("fx-mh2", "intensity"): [0.8]}, seq=1)
    override = source(
        compiled,
        {("fx-mh1", "intensity"): [1.0], ("fx-mh2", "intensity"): [0.0]},
        seq=2,
        priority=200,
    )
    weigh(compiled, override, {("fx-mh1", "intensity"): 0.5, ("fx-mh2", "intensity"): 0.0})
    frame = resolve(compiled, look, override)
    assert intensity(compiled, frame) == pytest.approx(0.9)
    assert intensity(compiled, frame, "fx-mh2") == 0.8


def test_a_source_with_every_lane_weight_at_zero_is_a_no_op(compiled: CompiledShow) -> None:
    values = {
        ("fx-mh1", "intensity"): [1.0],
        ("fx-mh1", "pan"): [80.0],
        ("fx-mh1", "gobo1"): [1.0],
        ("fx-mh1", "color"): [0.0, 0.0, 1.0, 0.25],
    }
    made = source(compiled, values, seq=1, priority=200)
    weigh(compiled, made, dict.fromkeys(values, 0.0))
    np.testing.assert_array_equal(resolve(compiled, made), compiled.slots.defaultFrame)


# ------------------------------------------------------------------- gather


def test_gather_keeps_present_sources_in_priority_then_seq_order(compiled: CompiledShow) -> None:
    a = source(compiled, {}, seq=3, priority=50)
    b = source(compiled, {}, seq=1, priority=200)
    c = source(compiled, {}, seq=2, priority=50)
    absent = source(compiled, {}, seq=4, htp=0.0, ltp=0.0)
    htp_only = source(compiled, {}, seq=5, ltp=0.0, scale=0.0)  # presence without intensity
    out: list[Source] = [absent]
    assert gather([a, b, absent, c, htp_only], out) is out
    assert [s.seq for s in out] == [2, 3, 5, 1]


# ---------------------------------------------------------- the relative pass

BASE_PAN = {("fx-mh1", "pan"): [-30.0]}
CREST = {("fx-mh1", "pan"): 15.0}  # a circle's add at its crest


def test_add_offsets_the_resolved_value(compiled: CompiledShow) -> None:
    base = source(compiled, BASE_PAN, seq=1)
    assert (
        pan(compiled, resolve(compiled, base, relatives=[relative(compiled, "add", CREST, seq=2)]))
        == -15.0
    )
    half = relative(compiled, "add", CREST, seq=2, weight=0.5)
    assert pan(compiled, resolve(compiled, base, relatives=[half])) == -22.5


def test_multiply_scales_the_resolved_value(compiled: CompiledShow) -> None:
    look = source(compiled, {("fx-mh1", "intensity"): [0.8]}, seq=1)
    dip = {("fx-mh1", "intensity"): 0.5}
    full = relative(compiled, "multiply", dip, seq=2)
    assert intensity(compiled, resolve(compiled, look, relatives=[full])) == pytest.approx(0.4)
    half = relative(compiled, "multiply", dip, seq=2, weight=0.5)  # 0.8 · lerp(1, 0.5, 0.5)
    assert intensity(compiled, resolve(compiled, look, relatives=[half])) == pytest.approx(0.6)


def test_relatives_apply_in_priority_seq_order(compiled: CompiledShow) -> None:
    base = source(compiled, BASE_PAN, seq=1)
    halve = {("fx-mh1", "pan"): 0.5}
    add_first = [
        relative(compiled, "add", {("fx-mh1", "pan"): 10.0}, seq=2),
        relative(compiled, "multiply", halve, seq=3),
    ]
    assert pan(compiled, resolve(compiled, base, relatives=add_first)) == -10.0  # (−30 + 10)·½
    multiply_first = [
        relative(compiled, "add", {("fx-mh1", "pan"): 10.0}, seq=3),
        relative(compiled, "multiply", halve, seq=2),
    ]
    assert pan(compiled, resolve(compiled, base, relatives=multiply_first)) == -5.0  # −30·½ + 10
    # Within one number, the layer's place in its cue decides.
    by_order = [
        relative(compiled, "multiply", halve, seq=2, order=1),
        relative(compiled, "add", {("fx-mh1", "pan"): 10.0}, seq=2, order=0),
    ]
    assert pan(compiled, resolve(compiled, base, relatives=by_order)) == -10.0
    # A higher band applies later, whatever its number.
    by_band = [
        relative(compiled, "add", {("fx-mh1", "pan"): 10.0}, seq=2, priority=100),
        relative(compiled, "multiply", halve, seq=3),
    ]
    assert pan(compiled, resolve(compiled, base, relatives=by_band)) == -5.0


def test_a_fully_present_higher_band_suspends_a_relative_effect(compiled: CompiledShow) -> None:
    """§7.5: a band-150 look on the head's pan and intensity suspends a
    band-50 circle and pulse on them; the other head keeps both."""
    base = source(
        compiled,
        {
            **BASE_PAN,
            ("fx-mh2", "pan"): [-30.0],
            ("fx-mh1", "intensity"): [0.8],
            ("fx-mh2", "intensity"): [0.8],
        },
        seq=1,
    )
    look = source(
        compiled, {("fx-mh1", "pan"): [0.0], ("fx-mh1", "intensity"): [0.6]}, seq=5, priority=150
    )
    circle = relative(compiled, "add", {("fx-mh1", "pan"): 15.0, ("fx-mh2", "pan"): 15.0}, seq=2)
    pulse = relative(
        compiled, "multiply", {("fx-mh1", "intensity"): 0.5, ("fx-mh2", "intensity"): 0.5}, seq=3
    )
    frame = resolve(compiled, base, look, relatives=[circle, pulse])
    assert (pan(compiled, frame), intensity(compiled, frame)) == (0.0, pytest.approx(0.6))
    assert (pan(compiled, frame, "fx-mh2"), intensity(compiled, frame, "fx-mh2")) == (
        -15.0,
        pytest.approx(0.4),
    )


@pytest.mark.parametrize(("presence", "expected"), [(0.0, -15.0), (0.5, -7.5), (1.0, 0.0)])
def test_suppression_is_continuous_while_a_higher_band_fades_in(
    compiled: CompiledShow, presence: float, expected: float
) -> None:
    """The phase-5-plan §5.6 table: a band-150 position look (pan 0°) fading
    in over a band-50 circle (base −30°, crest +15°)."""
    base = source(compiled, BASE_PAN, seq=1)
    circle = relative(compiled, "add", CREST, seq=2)
    look = source(compiled, {("fx-mh1", "pan"): [0.0]}, seq=5, priority=150, ltp=presence)
    assert pan(compiled, resolve(compiled, base, look, relatives=[circle])) == pytest.approx(
        expected
    )
    # The same presence as a per-lane weight (a slot fading in on its own).
    fading = weigh(
        compiled,
        source(compiled, {("fx-mh1", "pan"): [0.0]}, seq=5, priority=150),
        {("fx-mh1", "pan"): presence},
    )
    assert pan(compiled, resolve(compiled, base, fading, relatives=[circle])) == pytest.approx(
        expected
    )


def test_an_htp_band_above_suppresses_by_its_presence(compiled: CompiledShow) -> None:
    look = source(compiled, {("fx-mh1", "intensity"): [0.8]}, seq=1)
    above = weigh(
        compiled,
        source(compiled, {("fx-mh1", "intensity"): [0.8]}, seq=5, priority=150),
        {("fx-mh1", "intensity"): 0.5},
    )
    pulse = relative(compiled, "multiply", {("fx-mh1", "intensity"): 0.5}, seq=2)
    # Absolute 0.8 either way; the pulse at weight 1 − 0.5: 0.8 · lerp(1, 0.5, 0.5).
    assert intensity(compiled, resolve(compiled, look, above, relatives=[pulse])) == pytest.approx(
        0.6
    )


def test_the_same_band_and_lower_bands_do_not_suppress(compiled: CompiledShow) -> None:
    base = source(compiled, BASE_PAN, seq=1)
    later = source(compiled, {("fx-mh1", "pan"): [0.0]}, seq=3)  # same band, newer
    lower = source(compiled, {("fx-mh1", "pan"): [40.0]}, seq=4, priority=0)
    circle = relative(compiled, "add", CREST, seq=2)
    assert pan(compiled, resolve(compiled, base, later, lower, relatives=[circle])) == 15.0


def test_relatives_in_two_bands_each_see_the_bands_above_them(compiled: CompiledShow) -> None:
    base = source(compiled, {**BASE_PAN, ("fx-mh2", "pan"): [-30.0]}, seq=1)
    middle = source(compiled, {("fx-mh2", "pan"): [0.0]}, seq=4, priority=80, ltp=0.5)
    top = source(compiled, {("fx-mh1", "pan"): [0.0]}, seq=5, priority=150, ltp=0.25)
    both = {("fx-mh1", "pan"): 10.0, ("fx-mh2", "pan"): 10.0}
    low_band = relative(compiled, "add", both, seq=2)
    high_band = relative(compiled, "add", both, seq=3, priority=100)
    frame = resolve(compiled, base, middle, top, relatives=[low_band, high_band])
    # MH 1: absolute −30 + 30·¼ = −22.5; band 50 sees the top (¼), band 100 too.
    assert pan(compiled, frame) == pytest.approx(-22.5 + 10 * 0.75 + 10 * 0.75)
    # MH 2: absolute −15; band 50 sees the middle (½), band 100 sees nothing above.
    assert pan(compiled, frame, "fx-mh2") == pytest.approx(-15.0 + 10 * 0.5 + 10)


def test_per_lane_weights_scale_a_relative(compiled: CompiledShow) -> None:
    base = source(compiled, {**BASE_PAN, ("fx-mh2", "pan"): [-30.0]}, seq=1)
    mixed = relative(
        compiled,
        "add",
        {("fx-mh1", "pan"): 10.0, ("fx-mh2", "pan"): 10.0},
        seq=2,
        weight=0.5,
        weights=[1.0, 0.5],
    )
    frame = resolve(compiled, base, relatives=[mixed])
    assert (pan(compiled, frame), pan(compiled, frame, "fx-mh2")) == (-25.0, -27.5)


def test_add_results_are_clamped_once_after_the_pass(compiled: CompiledShow) -> None:
    look = source(compiled, {("fx-mh1", "intensity"): [0.9], ("fx-mh2", "intensity"): [0.1]}, seq=1)
    swing = relative(
        compiled,
        "add",
        {("fx-mh1", "intensity"): 0.3, ("fx-mh2", "intensity"): -0.3},
        seq=2,
        clamp=(0.0, 1.0),
    )
    frame = resolve(compiled, look, relatives=[swing])
    assert (intensity(compiled, frame), intensity(compiled, frame, "fx-mh2")) == (1.0, 0.0)
    # The clamp comes last: a multiply after the add sees 1.2, not 1.
    halve = relative(compiled, "multiply", {("fx-mh1", "intensity"): 0.5}, seq=3)
    assert intensity(compiled, resolve(compiled, look, relatives=[swing, halve])) == pytest.approx(
        0.6
    )
    # Unranged attributes are left to conversion.
    far = relative(compiled, "add", {("fx-mh1", "pan"): -200.0}, seq=2)
    assert (
        pan(compiled, resolve(compiled, source(compiled, BASE_PAN, seq=1), relatives=[far]))
        == -230.0
    )


def test_without_relatives_the_resolver_is_the_absolute_pass(compiled: CompiledShow) -> None:
    base = source(compiled, {**BASE_PAN, ("fx-mh1", "intensity"): [0.7]}, seq=1)
    plain = resolve(compiled, base)
    idle = [
        relative(compiled, "add", CREST, seq=2, weight=0.0),
        relative(compiled, "multiply", {("fx-mh1", "intensity"): 0.0}, seq=3, weight=0.0),
    ]
    np.testing.assert_array_equal(resolve(compiled, base, relatives=idle), plain)


def test_gather_relatives_keeps_the_present_ones_in_order(compiled: CompiledShow) -> None:
    a = relative(compiled, "add", CREST, seq=4)
    b = relative(compiled, "add", CREST, seq=2, order=1)
    c = relative(compiled, "add", CREST, seq=2, order=0)
    d = relative(compiled, "add", CREST, seq=1, priority=100)
    idle = relative(compiled, "add", CREST, seq=3, weight=0.0)
    empty = Relative(
        priority=50,
        seq=5,
        order=0,
        op="add",
        lanes=np.zeros(0, dtype=np.intp),
        amounts=np.zeros(0),
        weight=1.0,
    )
    out = [idle]
    assert gather_relatives([a, b, idle, c, d, empty], out) is out
    assert out == [c, b, a, d]


def test_coverage_does_not_leak_from_one_tick_to_the_next(compiled: CompiledShow) -> None:
    """The resolver reuses its coverage buffer: a look that covered MH 1 last
    tick must not suppress MH 1's circle this tick."""
    resolver = Resolver(compiled.slots)
    base = source(compiled, {**BASE_PAN, ("fx-mh2", "pan"): [-30.0]}, seq=1)
    circle = relative(compiled, "add", CREST, seq=2)
    frame = np.empty(compiled.slots.laneCount)
    for covered in ("fx-mh1", "fx-mh2"):
        look = source(compiled, {(covered, "pan"): [0.0]}, seq=5, priority=150)
        resolver.resolve([base, look], compiled.slots.defaultFrame, frame, [circle])
    assert pan(compiled, frame) == -15.0


# -------------------------------------------------------------- attribution


def drivers(
    compiled: CompiledShow,
    *sources: Source,
    relatives: Sequence[Relative] = (),
    lanes: Sequence[tuple[str, str]] = (),
) -> list[str | int | None]:
    """What drives the first lane of each ``(fixture, attribute)`` of ``lanes``
    (a ``sourceId``, the index of a relative in ``relatives``, ``None``),
    with the production resolver, checked against the oracle."""
    ordered = sorted(sources, key=SORT_KEY)
    present = gather_relatives(relatives, [])
    owners = np.empty(compiled.slots.laneCount, dtype=np.intp)
    Resolver(compiled.slots).attribute(ordered, present, owners)

    def driver(k: int) -> str | int | None:
        if k < 0:
            return None
        if k < len(ordered):
            return ordered[k].sourceId
        return next(i for i, r in enumerate(relatives) if r is present[k - len(ordered)])

    found = [driver(k) for k in owners.tolist()]
    assert found == reference_attribute(compiled.slots, ordered, relatives)
    return [found[slot_of(compiled, f, a).laneOffset] for f, a in lanes]


def test_the_topmost_present_source_drives_an_ltp_lane(compiled: CompiledShow) -> None:
    below = source(compiled, {("fx-mh1", "pan"): [10.0], ("fx-mh1", "tilt"): [5.0]}, seq=1)
    fading = source(compiled, {("fx-mh1", "pan"): [20.0], ("fx-mh1", "tilt"): [9.0]}, seq=2)
    fading.ltpWeight = 0.25  # on its way in: it drives already
    weigh(compiled, fading, {("fx-mh1", "tilt"): 0.0})  # its tilt has not started yet
    lanes = [("fx-mh1", "pan"), ("fx-mh1", "tilt"), ("fx-mh2", "pan")]
    assert drivers(compiled, below, fading, lanes=lanes) == ["s2", "s1", None]


def test_the_strongest_intensity_of_the_highest_band_drives(compiled: CompiledShow) -> None:
    bright = source(compiled, {("fx-mh1", "intensity"): [0.8]}, seq=1)
    dim = source(compiled, {("fx-mh1", "intensity"): [0.3]}, seq=2)  # newer, but weaker
    lanes = [("fx-mh1", "intensity")]
    assert drivers(compiled, bright, dim, lanes=lanes) == ["s1"]
    tie = source(compiled, {("fx-mh1", "intensity"): [0.8]}, seq=3)
    assert drivers(compiled, bright, dim, tie, lanes=lanes) == ["s3"]  # a tie: the later
    above = source(compiled, {("fx-mh1", "intensity"): [0.0]}, seq=4, priority=100, htp=0.2)
    assert drivers(compiled, bright, above, lanes=lanes) == ["s4"]  # taking over, even at 0


def test_a_relative_drives_where_no_higher_band_covers_it(compiled: CompiledShow) -> None:
    base = source(compiled, {**BASE_PAN, ("fx-mh2", "pan"): [-30.0]}, seq=1)
    look = source(compiled, {("fx-mh1", "pan"): [0.0]}, seq=5, priority=150)
    circle = relative(compiled, "add", {("fx-mh1", "pan"): 15.0, ("fx-mh2", "pan"): 15.0}, seq=2)
    lanes = [("fx-mh1", "pan"), ("fx-mh2", "pan")]
    assert drivers(compiled, base, look, relatives=[circle], lanes=lanes) == ["s5", 0]
    look.ltpWeight = 0.5  # fading in: the circle still moves the pan, by half
    assert drivers(compiled, base, look, relatives=[circle], lanes=lanes) == [0, 0]
