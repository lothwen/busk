"""The cue engine's pure sequence rules (phase-4-plan §5.6, decision 9)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from busk.compiler.cues import EMPTY_CUE, TriggerKind
from busk.compiler.playbacks import CompiledCueList, compile_cue_list
from busk.engine.cue_engine import next_cue, previous_cue, schedule
from busk.model.common import CueId, CueListId
from busk.model.cue import CueList

GO: tuple[TriggerKind, float] = ("go", 0.0)


def cues(
    *triggers: tuple[TriggerKind, float], wrap: bool = False, release_at_end: bool = False
) -> CompiledCueList:
    """A list of cues numbered 1, 2, …, entered by ``triggers``."""
    settings = CueList(
        id=CueListId("cl"),
        number=1,
        name="cl",
        mode="sequence",
        tracking=True,
        wrap=wrap,
        releaseAtEnd=release_at_end,
        cues=[],
    )
    compiled = tuple(
        replace(EMPTY_CUE, id=CueId(f"c{n}"), number=str(n), trigger=kind, triggerDelay=delay)
        for n, (kind, delay) in enumerate(triggers, start=1)
    )
    return compile_cue_list(settings, compiled)


# ----------------------------------------------------------------- next_cue


@pytest.mark.parametrize(
    ("wrap", "release_at_end", "at_end"),
    [
        (False, False, "reassert"),
        (False, True, "release"),
        (True, False, 0),
        (True, True, 0),  # wrap wins
    ],
)
def test_next_cue(wrap: bool, release_at_end: bool, at_end: int | str) -> None:
    three = cues(GO, GO, GO, wrap=wrap, release_at_end=release_at_end)
    assert [next_cue(three, c) for c in range(3)] == [1, 2, at_end]


def test_a_one_cue_list_that_wraps_lands_on_itself() -> None:
    assert next_cue(cues(GO, wrap=True), 0) == 0


def test_an_empty_list_has_no_next_cue() -> None:
    assert next_cue(cues(wrap=True), 0) == "reassert"
    assert next_cue(cues(release_at_end=True), 0) == "release"


# ------------------------------------------------------------- previous_cue


def test_previous_cue() -> None:
    assert [previous_cue(cues(GO, GO, GO), c) for c in range(3)] == [None, 0, 1]
    assert previous_cue(cues(GO, GO, GO, wrap=True), 0) == 2
    assert previous_cue(cues(GO, wrap=True), 0) == 0


# ----------------------------------------------------------------- schedule


def test_wait_counts_from_the_start_and_follow_from_the_completion() -> None:
    song = cues(GO, ("wait", 2.0), ("follow", 1.5), GO)
    assert schedule(song, 0, started=10.0, completes=13.0) == 12.0  # cue 2 waits
    assert schedule(song, 1, started=10.0, completes=13.0) == 14.5  # cue 3 follows
    assert schedule(song, 2, started=10.0, completes=13.0) is None  # cue 4 waits for GO


def test_no_schedule_without_a_next_cue() -> None:
    assert schedule(cues(GO, ("follow", 0.0)), 1, 0.0, 0.0) is None
    assert schedule(cues(("follow", 0.0), wrap=True), 0, 0.0, 0.0) is None  # lands on itself


def test_a_wrapping_list_schedules_its_first_cue() -> None:
    loop = cues(("wait", 1.0), ("follow", 0.0), wrap=True)
    assert schedule(loop, 1, started=5.0, completes=6.0) == 6.0


# --------------------------------------------------------------------- find


def test_cues_are_found_by_number() -> None:
    song = cues(GO, GO)
    assert (song.find("1"), song.find("2"), song.find("02")) == (0, 1, 1)
    assert (song.find("3"), song.find("two"), song.find("")) == (None, None, None)
