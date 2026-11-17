"""GAP-06 of ``docs/dev/tui/engine-gaps.md``: one undo step for a gesture.

``undo group "<label>"`` opens a group, and the programmer steps after it
are one step on the timeline, labelled ``<label>``; ``undo group end``
closes it. A show step, ``undo``, ``redo``, another group, or a programmer
step more than 2 s after the group's last one closes it first. A group that
took no step leaves nothing; one never closed takes nothing after its gap.
Steps from another thread join it; performance lines and modes never do.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from builders import APPENDIX_A, load_doc, show_of
from busk import LiveShow, OfflineShow
from busk.commands.patch import Op
from busk.session import timeline as timeline_module
from busk.session.programmer import EMPTY, Programmer
from busk.session.timeline import GROUP_GAP, Group, ProgrammerStep, ShowStep, Timeline

# ------------------------------------------------------------- the timeline


class Clock:
    """A clock the test moves."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def programmer(n: int) -> Programmer:
    """A programmer told apart by its fade time."""
    return replace(EMPTY, fadeTime=float(n))


def step(n: int) -> ProgrammerStep:
    """The step from programmer ``n - 1`` to ``n``."""
    return ProgrammerStep(before=programmer(n - 1), after=programmer(n), label=f"step {n}")


def show_step(label: str) -> ShowStep:
    op = Op("replace", ("meta", "title"), label)
    return ShowStep(forward=(op,), inverse=(op,), label=label)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def timeline(clock: Clock) -> Timeline:
    return Timeline(clock=clock)


def undo_all(timeline: Timeline) -> list[str]:
    labels = []
    while (last := timeline.next_undo()) is not None:
        labels.append(last.label)
        timeline.undone()
    return labels


def test_the_steps_of_a_group_are_one_from_the_first_before_to_the_last_after(
    timeline: Timeline, clock: Clock
) -> None:
    timeline.push(step(1))
    assert timeline.open_group("pan drag") is None
    for n in range(2, 32):
        clock.now += 0.1
        timeline.push(step(n))
    assert timeline.undo_count == 2
    grouped = timeline.next_undo()
    assert grouped == ProgrammerStep(before=programmer(1), after=programmer(31), label="pan drag")
    assert timeline.group == Group(label="pan drag", steps=30, last=pytest.approx(3.0))
    assert timeline.close_group() == Group(label="pan drag", steps=30, last=pytest.approx(3.0))
    assert timeline.group is None
    timeline.push(step(32))
    assert undo_all(timeline) == ["step 32", "pan drag", "step 1"]


def test_a_group_that_took_no_step_leaves_nothing(timeline: Timeline) -> None:
    timeline.push(step(1))
    timeline.open_group("empty")
    assert timeline.close_group() == Group(label="empty", steps=0, last=0.0)
    assert undo_all(timeline) == ["step 1"]


def test_opening_a_group_closes_the_open_one(timeline: Timeline) -> None:
    timeline.open_group("first")
    timeline.push(step(1))
    timeline.push(step(2))
    assert timeline.open_group("second") == Group(label="first", steps=2, last=0.0)
    timeline.push(step(3))
    assert undo_all(timeline) == ["second", "first"]


def test_a_show_step_closes_the_group_and_stands_alone(timeline: Timeline) -> None:
    timeline.open_group("drag")
    timeline.push(step(1))
    timeline.push(show_step("record"))
    assert timeline.group is None
    timeline.push(step(2))
    assert undo_all(timeline) == ["step 2", "record", "drag"]


def test_undo_and_redo_close_the_group(timeline: Timeline) -> None:
    timeline.open_group("drag")
    timeline.push(step(1))
    timeline.undone()
    assert timeline.group is None
    timeline.open_group("again")
    timeline.redone()
    assert timeline.group is None
    timeline.push(step(2))
    assert undo_all(timeline) == ["step 2", "drag"]


def test_a_step_after_the_gap_closes_the_group_and_stands_alone(
    timeline: Timeline, clock: Clock
) -> None:
    timeline.open_group("drag")
    clock.now = GROUP_GAP  # from the opening: still in
    timeline.push(step(1))
    clock.now += GROUP_GAP
    timeline.push(step(2))  # exactly the gap: still in
    clock.now += GROUP_GAP + 0.001
    timeline.push(step(3))
    assert timeline.group is None
    timeline.push(step(4))  # a group never closed takes nothing more
    assert undo_all(timeline) == ["step 4", "step 3", "drag"]


def test_a_group_opened_and_left_takes_no_late_step(timeline: Timeline, clock: Clock) -> None:
    timeline.open_group("forgotten")
    clock.now = GROUP_GAP + 1
    timeline.push(step(1))
    assert timeline.group is None
    assert undo_all(timeline) == ["step 1"]


def test_the_redo_stack_goes_with_the_groups_first_step_not_its_opening(
    timeline: Timeline,
) -> None:
    timeline.push(step(1))
    timeline.undone()
    timeline.open_group("drag")
    assert timeline.redo_count == 1
    timeline.push(step(1))
    assert timeline.redo_count == 0


def test_a_group_is_one_step_of_the_limit(clock: Clock) -> None:
    timeline = Timeline(limit=3, clock=clock)
    timeline.push(step(1))
    timeline.push(step(2))
    timeline.open_group("drag")
    for n in range(3, 2003):
        timeline.push(step(n))
    assert undo_all(timeline) == ["drag", "step 2", "step 1"]
    timeline.push(step(1))
    timeline.push(step(2))
    timeline.push(step(3))
    timeline.push(step(4))  # the limit forgets the oldest, as before
    assert undo_all(timeline) == ["step 4", "step 3", "step 2"]


def test_clearing_closes_the_group(timeline: Timeline) -> None:
    timeline.open_group("drag")
    timeline.clear()
    assert timeline.group is None


# ------------------------------------------------------------------ lines


@pytest.fixture
def offline() -> OfflineShow:
    """Appendix A, on its fake clock."""
    return OfflineShow(show_of(load_doc(APPENDIX_A)))


def run(show: OfflineShow | LiveShow, *lines: str) -> str:
    """Run ``lines``; each must work. The last reply."""
    text = ""
    for line in lines:
        reply = show.execute(line)
        assert reply.ok, (line, reply.text)
        text = reply.text
    return text


def pans(show: OfflineShow | LiveShow) -> list[float | None]:
    programmer = show.programmer
    values = {(entry.number, entry.attribute): entry.value for entry in programmer.values}
    return [values.get((fixture, "pan")) for fixture in (101, 102)]


def test_thirty_set_lines_in_a_group_are_one_undo_and_one_redo(offline: OfflineShow) -> None:
    run(offline, "sel group 1", "set pan 0")
    assert run(offline, 'undo group "pan drag"') == 'undo group "pan drag" is open'
    for value in range(1, 31):
        run(offline, f"set pan {value}")
    assert run(offline, "undo group end") == (
        'closed undo group "pan drag": 30 steps, undone as one'
    )
    assert run(offline, "undo") == "undid: pan drag"
    assert pans(offline) == [0, 0]
    assert run(offline, "redo") == "redid: pan drag"
    assert pans(offline) == [30, 30]
    run(offline, "undo", "undo")
    assert pans(offline) == [None, None]


def test_every_way_a_group_closes(offline: OfflineShow) -> None:
    run(offline, "sel group 1")
    run(offline, 'undo group "a"', "set pan 1")
    assert run(offline, 'undo group "b"') == 'closed undo group "a": 1 step; undo group "b" is open'
    run(offline, "set pan 2", 'show meta.title "Edited"')  # a show step closes "b"
    run(offline, "set pan 3")
    run(offline, 'undo group "c"', "set pan 4", "undo")  # undo closes "c", and takes it
    run(offline, "set pan 5")
    run(offline, 'undo group "d"')
    assert not offline.execute("redo").ok  # nothing to redo: refused, and "d" stays open
    run(offline, "set pan 6")
    offline.tick(offline.time + GROUP_GAP + 0.5)
    run(offline, "set pan 7")  # after the gap: closes "d", and stands alone
    run(offline, "set pan 8")
    reply = offline.execute("undo group end")
    assert (reply.ok, reply.text) == (False, "error: no undo group is open")
    undone = [run(offline, "undo") for _ in range(8)]
    assert undone == [
        "undid: pan: 2 targets",  # 8
        "undid: pan: 2 targets",  # 7
        "undid: d",
        "undid: pan: 2 targets",  # 5
        "undid: pan: 2 targets",  # 3
        'undid: set meta.title to "Edited"',
        "undid: b",
        "undid: a",
    ]


def test_redo_closes_a_group(offline: OfflineShow) -> None:
    run(offline, "sel group 1", "set pan 1", "undo", 'undo group "drag"', "redo", "set pan 2")
    assert offline.execute("undo group end").text == "error: no undo group is open"


def test_an_empty_group_leaves_nothing_and_says_so(offline: OfflineShow) -> None:
    run(offline, "sel group 1")
    run(offline, 'undo group "drag"', "blind on", "fade 2", "blind off")  # modes take no step
    assert run(offline, "undo group end") == 'closed undo group "drag", which took no step'
    assert run(offline, "undo") == "undid: 2 targets selected"


def test_a_refused_line_changes_nothing_the_group_included(offline: OfflineShow) -> None:
    run(offline, "sel group 1", 'undo group "drag"', "set pan 1")
    assert not offline.execute("delete fixture 101").ok  # in use: refused
    assert not offline.execute("set nonsense 1").ok
    run(offline, "set pan 2")
    assert run(offline, "undo group end") == 'closed undo group "drag": 2 steps, undone as one'


def test_performance_lines_neither_join_nor_close_a_group(offline: OfflineShow) -> None:
    run(offline, "sel group 1", 'undo group "drag"', "set pan 1", "go 1", "fader 3 50%")
    run(offline, "gm 50%", "set pan 2")
    assert run(offline, "undo group end") == 'closed undo group "drag": 2 steps, undone as one'
    assert run(offline, "undo") == "undid: drag"


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ('undo group ""', "an undo group needs a label"),
        ('undo group "  "', "an undo group needs a label"),
        ("undo group drag", "expected a label in quotes or end, got 'drag'"),
        ("undo group", 'expected a label in quotes, e.g. "pan drag", or end'),
        ('undo group "a" end', "unexpected 'end'"),
        ("undo group end now", "unexpected 'now'"),
        ("undo group end", "no undo group is open"),
    ],
)
def test_refused_group_lines(offline: OfflineShow, line: str, error: str) -> None:
    reply = offline.execute(line)
    assert (reply.ok, reply.text) == (False, f"error: {error}")


def test_a_long_label_is_cut_in_the_replies(offline: OfflineShow) -> None:
    label = "x" * 80
    assert run(offline, f'undo group "{label}"') == f'undo group "{"x" * 58}… is open'


# --------------------------------------------------------------- LiveShow


@pytest.fixture
def live() -> Iterator[LiveShow]:
    """Appendix A, running, without output."""
    with LiveShow(show_of(load_doc(APPENDIX_A)), output=False) as show:
        yield show


def test_a_group_on_a_running_show(live: LiveShow) -> None:
    run(live, "sel group 1", 'undo group "pan drag"')
    for value in range(1, 31):
        run(live, f"set pan {value}")
    run(live, "undo group end")
    assert run(live, "undo") == "undid: pan drag"
    assert run(live, "redo") == "redid: pan drag"
    assert pans(live) == [30, 30]


def test_a_running_shows_gap_is_real_time(live: LiveShow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timeline_module, "GROUP_GAP", 0.05)
    run(live, "sel group 1", 'undo group "drag"', "set pan 1")
    time.sleep(0.1)
    run(live, "set pan 2")
    assert live.execute("undo group end").text == "error: no undo group is open"
    assert [run(live, "undo") for _ in range(2)] == ["undid: pan: 2 targets", "undid: drag"]


def test_lines_from_other_threads_join_the_group(live: LiveShow) -> None:
    """The group is the session's: a surface or the web remote sending
    programmer lines while a drag runs joins it."""
    run(live, "sel group 1", 'undo group "drag"')
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(live.execute, [f"set tilt {n}" for n in range(40)]))
    assert all(reply.ok for reply in replies)
    assert run(live, "undo group end") == 'closed undo group "drag": 40 steps, undone as one'
    assert run(live, "undo") == "undid: drag"
    assert run(live, "undo") == "undid: 2 targets selected"
