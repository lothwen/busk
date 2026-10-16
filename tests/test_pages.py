"""Pages (phase-6-plan §5.1, decisions 1–2): the engine owns one current page.

``PageState`` is tested on its own, then through the engine: ``PAGE`` and
``SET_FADER {slot}`` are applied in queue order, a page change leaves running
playbacks alone, and a live edit keeps the current page by id.
"""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import pytest

from builders import compile_doc
from busk.commands.types import Command
from busk.compiler.compile import CompiledShow
from busk.compiler.playbacks import CompiledPage
from busk.engine.install import EMPTY_FRAME, Install
from busk.engine.snapshot import PageStatus
from busk.engine.surfaces import PageState
from busk.model.common import PlaybackId
from harness import Harness, fader, trigger


def page(ident: str, number: int, *slots: str | None) -> CompiledPage:
    return CompiledPage(
        id=ident,
        number=number,
        name=ident.title(),
        slots=tuple(cast(PlaybackId | None, slot) for slot in slots),
    )


ONE = page("one", 1, "pb-a", None)
TWO = page("two", 2, "pb-b")
FIVE = page("five", 5)

# ------------------------------------------------------------------ PageState


def test_the_lowest_numbered_page_is_current_at_start() -> None:
    state = PageState((ONE, TWO, FIVE))
    assert state.current is ONE
    assert state.index == 0


def test_go_to_a_number() -> None:
    state = PageState((ONE, TWO, FIVE))
    assert state.go(number=5) is True
    assert state.current is FIVE
    assert state.go(number=5) is False  # already there
    assert state.go(number=3) is False  # no page 3 (deleted after the bus checked it)
    assert state.current is FIVE


def test_delta_moves_in_number_order_and_stops_at_the_ends() -> None:
    state = PageState((ONE, TWO, FIVE))
    assert state.go(delta=1) is True
    assert state.current is TWO
    assert state.go(delta=1) is True
    assert state.current is FIVE
    assert state.go(delta=1) is False  # never wraps to the first page
    assert state.current is FIVE
    assert state.go(delta=-7) is True
    assert state.current is ONE
    assert state.go(delta=-1) is False
    assert state.go(delta=0) is False


def test_slots_resolve_on_the_current_page() -> None:
    state = PageState((ONE, TWO))
    assert state.playback(0) == "pb-a"
    assert state.playback(1) is None  # an empty slot
    assert state.playback(2) is None  # beyond the page
    state.go(number=2)
    assert state.playback(0) == "pb-b"
    assert state.playback(1) is None


def test_a_show_without_pages() -> None:
    state = PageState(())
    assert state.current is None
    assert state.index is None
    assert state.go(delta=1) is False
    assert state.go(number=1) is False
    assert state.playback(0) is None


@pytest.mark.parametrize(
    ("pages", "current"),
    [
        ((ONE, page("two", 2, "pb-x")), "two"),  # slots edited: kept by id
        ((ONE, page("two", 9)), "two"),  # renumbered: kept by id
        ((page("two", 0), ONE), "two"),  # renumbered first: still kept
        ((ONE, FIVE), "five"),  # deleted: the next page by number
        ((ONE, page("new", 2), FIVE), "new"),  # replaced: the page that took its number
        ((ONE, page("zero", 0)), "one"),  # deleted, nothing after it: the last page
        ((ONE,), "one"),
    ],
)
def test_a_live_edit_keeps_the_current_page_by_id(
    pages: tuple[CompiledPage, ...], current: str
) -> None:
    state = PageState((ONE, TWO, FIVE))
    state.go(number=2)
    state.rebind(tuple(sorted(pages, key=lambda p: p.number)))
    assert state.current is not None
    assert state.current.id == current


def test_rebinding_to_and_from_no_pages() -> None:
    state = PageState((ONE, TWO))
    state.rebind(())
    assert state.current is None
    state.rebind((TWO, FIVE))
    assert state.current is TWO  # pages again: the lowest-numbered one


# --------------------------------------------------------------- the engine
#
# Appendix A's page 1 holds pb-song on slot 0 and pb-blue on slot 2. Page 2
# ("Washes") swaps them: pb-blue on slot 0, pb-song on slot 1.


def _command(**fields: Any) -> Command:
    return cast(Command, fields)


def page_cmd(**fields: int) -> Command:
    return _command(type="PAGE", **fields)


def slot_fader(slot: int, level: float) -> Command:
    return _command(type="SET_FADER", slot=slot, level=level)


@pytest.fixture
def doc(appendix_a: dict[str, Any]) -> dict[str, Any]:
    appendix_a["pages"].append(
        {"id": "page-2", "number": 2, "name": "Washes", "slots": ["pb-blue", "pb-song"]}
    )
    return appendix_a


@pytest.fixture
def show(doc: dict[str, Any]) -> CompiledShow:
    return compile_doc(doc)


def levels(harness: Harness) -> dict[str, float]:
    runtimes = harness.engine.runtime.playbacks.runtimes
    return {ident: rt.faderLevel for ident, rt in runtimes.items()}


def test_page_then_set_fader_in_one_tick_resolves_on_the_new_page(show: CompiledShow) -> None:
    harness = Harness(show)
    harness.submit(slot_fader(0, 0.25), page_cmd(number=2), slot_fader(0, 0.5))
    harness.tick(0.0)
    # In queue order: slot 0 was pb-song before the PAGE and pb-blue after it.
    assert levels(harness) == {"pb-song": 0.25, "pb-blue": 0.5, "pb-pulse": 0.0}
    assert harness.engine.stats.commandErrors == 0


def test_an_empty_or_out_of_range_slot_does_nothing(show: CompiledShow) -> None:
    harness = Harness(show)
    harness.tick(0.0)
    before = harness.tick(0.1).universe
    harness.submit(slot_fader(1, 1.0), slot_fader(7, 1.0), slot_fader(40, 1.0))
    after = harness.tick(0.2)
    assert after.universe == before
    assert set(levels(harness).values()) == {0.0}
    assert harness.engine.stats.commandErrors == 0
    assert harness.engine.stats.commandsApplied == 3


def test_a_page_change_leaves_running_playbacks_and_faders_alone(show: CompiledShow) -> None:
    harness = Harness(show)
    harness.run([(0.0, trigger("pb-song")), (0.0, slot_fader(0, 0.8))], [0.0])
    settled = harness.tick(10.0)
    harness.submit(page_cmd(delta=1))
    moved = harness.tick(10.01)
    np.testing.assert_array_equal(moved.logical, settled.logical)
    assert moved.universe == settled.universe
    runtime = harness.engine.runtime.playbacks.runtimes[PlaybackId("pb-song")]
    assert (runtime.state, runtime.faderLevel) == ("active", 0.8)
    # The slot now names another playback; pb-song's fader is reached by id only.
    harness.submit(slot_fader(0, 0.3))
    harness.tick(10.02)
    assert levels(harness) == {"pb-song": 0.8, "pb-blue": 0.3, "pb-pulse": 0.0}


def test_the_snapshot_shows_the_current_page(show: CompiledShow) -> None:
    harness = Harness(show)
    first = harness.tick(0.0).snapshot
    assert first is not None
    assert first.page == PageStatus(id="page-1", number=1, name="Main")
    harness.submit(page_cmd(delta=1))
    second = harness.tick(0.1).snapshot
    assert second is not None
    assert second.page == PageStatus(id="page-2", number=2, name="Washes")
    assert second.seq == first.seq + 1
    harness.submit(page_cmd(delta=1))  # already on the last page: nothing changes
    third = harness.tick(0.2).snapshot
    assert third is second


def edit(doc: dict[str, Any], show: CompiledShow) -> Install:
    """A live edit that installs ``doc`` (pages only change, so no remap)."""
    compiled = compile_doc(doc)
    assert compiled.slots.byKey == show.slots.byKey
    return Install(compiled=compiled, remap=None, programmer=EMPTY_FRAME)


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"name": "Colours"}, PageStatus(id="page-2", number=2, name="Colours")),
        ({"number": 7}, PageStatus(id="page-2", number=7, name="Washes")),
        (None, PageStatus(id="page-3", number=3, name="Three")),  # deleted: the next one
    ],
    ids=["renamed", "renumbered", "deleted"],
)
def test_a_live_edit_of_the_current_page(
    doc: dict[str, Any], show: CompiledShow, change: dict[str, Any] | None, expected: PageStatus
) -> None:
    harness = Harness(show)
    harness.submit(page_cmd(number=2))
    harness.tick(0.0)
    doc["pages"].append({"id": "page-3", "number": 3, "name": "Three", "slots": ["pb-pulse"]})
    if change is None:
        del doc["pages"][1]
    else:
        doc["pages"][1].update(change)
    harness.engine.bus.install(edit(doc, show))
    observed = harness.tick(0.1).snapshot
    assert observed is not None
    assert observed.page == expected
    harness.submit(slot_fader(0, 0.6))
    harness.tick(0.2)
    slot0 = "pb-pulse" if change is None else "pb-blue"
    assert levels(harness)[slot0] == 0.6


def test_a_fader_by_id_ignores_the_page(show: CompiledShow) -> None:
    harness = Harness(show)
    harness.submit(page_cmd(number=2), fader("pb-pulse", 0.4))
    harness.tick(0.0)
    assert levels(harness)["pb-pulse"] == 0.4
