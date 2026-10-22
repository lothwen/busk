"""Property tests for the resolver (hypothesis, §20).

* **Differential:** the batched resolver equals the literal per-slot
  transcription of §7.7 (``reference_resolver.py``) within 1e-12, on random
  sources over every kind of lane, in several bands, with and without
  per-lane weights.
* **Per-slot sequence numbers:** contributors whose slots carry their own
  sequence numbers and weights, handed to the resolver as one source per
  number, equal the oracle fed the per-slot contributions directly.
* **HTP within a band** is commutative (activation order does not matter)
  and never below any single ``value · intensityScale · weight``.
* **LTP hull:** every interpolated lane stays between the lowest and the
  highest of its default and its inputs.
* **Zero weight:** a source with both weights at 0 changes nothing.
* **Relative pass:** random sources with random relative contributions
  equal the oracle's §7.5 with continuous suppression.
* **Attribution** (GAP-01): what drives each lane equals the oracle's
  per-slot answer, relatives included.
"""

from __future__ import annotations

import random

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from busk.compiler.cues import cue_from_values
from busk.engine.contributions import SORT_KEY, Relative, Source, gather_relatives
from busk.engine.resolver import Resolver
from reference_resolver import reference_attribute, reference_resolve, resolve_contributions
from resolver_strategies import (
    COMPILED,
    SLOTS,
    UNIT,
    WEIGHT,
    Drawn,
    contributions_of,
    drawn_contributors,
    lanes_for,
    one_source_per_number,
    relatives,
    resolve,
    set_lane_weights,
)


@st.composite
def sources(
    draw: st.DrawFn, priorities: tuple[int, ...] = (0, 50, 200), max_size: int = 6
) -> list[Source]:
    """Random sources with unique seqs, sorted by ``(priority, seq)``."""
    count = draw(st.integers(0, max_size))
    seqs = draw(st.permutations(range(1, count + 1)))
    made = []
    for seq in seqs:
        chosen = draw(st.lists(st.sampled_from(SLOTS), unique_by=lambda s: s.index, max_size=8))
        values = {slot.index: draw(lanes_for(slot)) for slot in chosen}
        source = Source.of_cue(
            f"s{seq}", draw(st.sampled_from(priorities)), cue_from_values(COMPILED.slots, values)
        )
        source.seq = seq
        source.htpWeight = draw(WEIGHT)
        source.ltpWeight = draw(WEIGHT)
        source.intensityScale = draw(UNIT)
        if draw(st.booleans()):  # fading slot by slot
            set_lane_weights(source, {slot.index: draw(WEIGHT) for slot in chosen})
        made.append(source)
    made.sort(key=SORT_KEY)
    return made


@given(sources())
def test_the_resolver_equals_the_per_slot_oracle(ordered: list[Source]) -> None:
    expected = reference_resolve(COMPILED.slots, ordered, COMPILED.slots.defaultFrame)
    np.testing.assert_allclose(resolve(ordered), expected, rtol=0, atol=1e-12, equal_nan=True)


@given(sources(), relatives())
def test_the_relative_pass_equals_the_per_slot_oracle(
    ordered: list[Source], relative: list[Relative]
) -> None:
    expected = reference_resolve(COMPILED.slots, ordered, COMPILED.slots.defaultFrame, relative)
    np.testing.assert_allclose(
        resolve(ordered, relative), expected, rtol=0, atol=1e-12, equal_nan=True
    )


@given(sources(), relatives())
def test_the_attribution_equals_the_per_slot_oracle(
    ordered: list[Source], relative: list[Relative]
) -> None:
    present = gather_relatives(relative, [])
    owners = np.empty(COMPILED.slots.laneCount, dtype=np.intp)
    Resolver(COMPILED.slots).attribute(ordered, present, owners)
    count = len(ordered)

    def driver(k: int) -> str | int | None:
        if k < 0:
            return None
        if k < count:
            return ordered[k].sourceId
        return next(i for i, r in enumerate(relative) if r is present[k - count])

    expected = reference_attribute(COMPILED.slots, ordered, relative)
    assert [driver(k) for k in owners.tolist()] == expected


@given(drawn_contributors())
def test_per_slot_sequence_numbers_and_weights_equal_the_oracle(drawn: list[Drawn]) -> None:
    expected = resolve_contributions(
        COMPILED.slots, contributions_of(drawn), COMPILED.slots.defaultFrame
    )
    np.testing.assert_allclose(
        resolve(one_source_per_number(drawn)), expected, rtol=0, atol=1e-12, equal_nan=True
    )


@given(sources(priorities=(50,)), st.randoms(use_true_random=False))
def test_htp_within_a_band_is_commutative_and_at_least_every_input(
    ordered: list[Source], shuffler: random.Random
) -> None:
    intensity = COMPILED.slots.intensityLanes
    first = resolve(ordered)[intensity]
    # Reassign the seqs: a different activation order, same contributions.
    seqs = [source.seq for source in ordered]
    shuffler.shuffle(seqs)
    for source, seq in zip(ordered, seqs, strict=True):
        source.seq = seq
    reordered = sorted(ordered, key=SORT_KEY)
    np.testing.assert_array_equal(resolve(reordered)[intensity], first)
    for source in ordered:
        if source.htpWeight > 0:
            # §7.4 writes value · scale · weight; the resolver multiplies the scalars
            # first, so the two may differ by an ulp. Among subnormals an ulp is not
            # relative (5e-324 · 0.47 rounds to 0), hence the absolute slack.
            contribution = source.htpValues * source.intensityScale * source.htpWeight
            if source.htpWeights is not None:
                contribution = contribution * source.htpWeights
            slack = np.finfo(np.float64).tiny
            assert np.all(first[source.htpPos] >= contribution * (1 - 1e-12) - slack)


@given(sources())
def test_ltp_lanes_stay_in_the_hull_of_default_and_inputs(ordered: list[Source]) -> None:
    frame = resolve(ordered)
    default = COMPILED.slots.defaultFrame
    inputs: dict[int, list[float]] = {}
    for source in ordered:
        if source.ltpWeight > 0:
            for lane, value in zip(source.ltpLanes, source.ltpValues, strict=True):
                inputs.setdefault(int(lane), []).append(float(value))
    for lane, values in inputs.items():
        hull = [float(default[lane]), *values]
        assert min(hull) - 1e-9 <= frame[lane] <= max(hull) + 1e-9


@given(sources(), st.data(), st.booleans())
def test_a_zero_weight_source_is_a_no_op(
    ordered: list[Source], data: st.DataObject, per_lane: bool
) -> None:
    extra = data.draw(sources(max_size=1).filter(bool))[0]
    extra.seq = len(ordered) + 1
    if per_lane:  # present by its scalars, every lane at 0
        extra.htpWeight = extra.ltpWeight = 1.0
        set_lane_weights(extra, dict.fromkeys(COMPILED.slots.laneSlot.tolist(), 0.0))
    else:
        extra.htpWeight = extra.ltpWeight = 0.0
    with_extra = sorted([*ordered, extra], key=SORT_KEY)
    np.testing.assert_array_equal(resolve(with_extra), resolve(ordered))


def test_the_rig_has_every_lane_kind() -> None:
    kinds = {(slot.attribute.merge, slot.attribute.fade, slot.attribute.kind) for slot in SLOTS}
    assert {
        ("HTP", "fade", "scalar"),
        ("LTP", "fade", "scalar"),
        ("LTP", "snap", "scalar"),
        ("LTP", "snap", "discrete"),
        ("LTP", "fade", "color"),
    } <= kinds
    assert any(slot.extras == ("w", "a") for slot in SLOTS)
