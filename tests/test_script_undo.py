"""GAP-56 and GAP-57 of ``docs/dev/tui/engine-gaps.md``: a script is one undo
step, and ``run_script`` reports each line as it runs.

* **One step.** What a script changes, the show and the programmer, is one
  step on the timeline, labelled as the line that runs it (``source
  build.busk``), wherever it runs: ``source`` at the prompt, ``busk run
  --script``, ``run_script`` on either facade. One ``undo`` puts the show and
  the programmer back in one published change, and one ``redo`` brings both
  back. A nested ``source`` joins the outer step; a script that fails leaves
  one step for the lines that ran; one that changes nothing leaves none; an
  ``undo`` or ``redo`` line closes the step so far. The steps from before a
  script longer than the timeline stay.
* **Beside it.** A performance line from another thread runs while a script
  holds the console and pushes no step; a command another thread submits to
  the session meanwhile joins the script's step, as it joins an undo group.
* **Each line.** ``run_script(path, each=…)`` calls ``each(number, total,
  line, reply)`` after each line of the file, in order, on the thread that
  runs it, as the lines run; a failing line before ``ScriptError``, a nested
  ``source`` as one call.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from builders import APPENDIX_A, ROOT, load_doc, show_of
from busk import LiveShow, OfflineShow, ScriptError, new_show
from busk.commands.patch import Op
from busk.commands.types import Command
from busk.console.console import Reply
from busk.session.programmer import EMPTY, Programmer
from busk.session.session import SessionSnapshot
from busk.session.timeline import (
    LIMIT,
    ProgrammerStep,
    ScriptStep,
    ShowStep,
    Timeline,
)

# ------------------------------------------------------------- the timeline


def programmer(n: int) -> Programmer:
    """A programmer told apart by its fade time."""
    return replace(EMPTY, fadeTime=float(n))


def step(n: int) -> ProgrammerStep:
    """The step from programmer ``n - 1`` to ``n``."""
    return ProgrammerStep(before=programmer(n - 1), after=programmer(n), label=f"step {n}")


def op(value: str) -> Op:
    return Op("replace", ("meta", "title"), value)


def show_step(n: int) -> ShowStep:
    """Title ``t{n}``, from ``t{n - 1}``."""
    return ShowStep(forward=(op(f"t{n}"),), inverse=(op(f"t{n - 1}"),), label=f"edit {n}")


def labels(timeline: Timeline) -> list[str]:
    """The labels ``undo`` would walk, newest first (the timeline is left as it was)."""
    found = []
    while (last := timeline.next_undo()) is not None:
        found.append(last.label)
        timeline.undone()
    while timeline.next_redo() is not None:
        timeline.redone()
    return found


def test_a_scripts_steps_are_one_its_ops_in_order_and_its_programmer_from_first_to_last() -> None:
    timeline = Timeline()
    timeline.push(show_step(1))
    timeline.open_script("source build.busk")
    for pushed in (show_step(2), step(1), show_step(3), step(2), step(3)):
        timeline.push(pushed)
    timeline.close_script()
    assert timeline.undo_count == 2
    assert timeline.next_undo() == ScriptStep(
        forward=(op("t2"), op("t3")),
        inverse=(op("t2"), op("t1")),  # the last step's first
        before=programmer(0),
        after=programmer(3),
        label="source build.busk",
    )


def test_a_script_of_show_steps_only_keeps_no_programmer() -> None:
    timeline = Timeline()
    timeline.open_script("source edits.busk")
    timeline.push(show_step(1))
    timeline.close_script()
    script = timeline.next_undo()
    assert isinstance(script, ScriptStep)
    assert (script.before, script.after) == (None, None)


def test_a_script_inside_a_script_joins_it_and_the_outer_one_ends_it() -> None:
    timeline = Timeline()
    timeline.open_script("source outer.busk")
    timeline.push(show_step(1))
    timeline.open_script("source inner.busk")
    timeline.push(show_step(2))
    timeline.close_script()
    timeline.push(show_step(3))
    timeline.close_script()
    timeline.push(show_step(4))  # after the script: a step of its own
    assert labels(timeline) == ["edit 4", "source outer.busk"]


def test_a_script_that_pushes_nothing_leaves_nothing_and_its_step_clears_redo() -> None:
    timeline = Timeline()
    timeline.push(show_step(1))
    timeline.undone()
    timeline.open_script("source nothing.busk")
    timeline.close_script()
    assert (timeline.undo_count, timeline.redo_count) == (0, 1)
    timeline.open_script("source something.busk")
    timeline.push(step(1))
    timeline.close_script()
    assert (timeline.undo_count, timeline.redo_count) == (1, 0)


@pytest.mark.parametrize("move", ["undone", "redone"])
def test_undo_and_redo_in_a_script_close_its_step_so_far(move: str) -> None:
    timeline = Timeline()
    timeline.push(show_step(1))
    if move == "redone":
        timeline.undone()
    timeline.open_script("source s.busk")
    if move == "undone":
        timeline.push(show_step(2))
    getattr(timeline, move)()
    timeline.push(show_step(3))
    timeline.push(show_step(4))
    timeline.close_script()
    script = timeline.next_undo()
    assert isinstance(script, ScriptStep)
    assert script.forward == (op("t3"), op("t4"))  # the lines after the undo or redo
    assert labels(timeline) == ["source s.busk", "edit 1"]


def test_a_script_closes_the_open_group_and_a_group_inside_it_only_counts() -> None:
    timeline = Timeline()
    timeline.open_group("pan drag")
    timeline.push(step(1))
    timeline.open_script("source s.busk")
    assert timeline.group is None
    timeline.push(step(2))
    timeline.open_group("inside")
    timeline.push(step(3))
    timeline.push(step(4))
    group = timeline.group
    assert group is not None
    assert group.steps == 2
    timeline.close_script()
    assert timeline.group is None  # left open by the script: closed with it
    timeline.push(step(5))
    assert labels(timeline) == ["step 5", "source s.busk", "pan drag"]


def test_clearing_the_timeline_in_a_script_starts_its_step_again() -> None:
    timeline = Timeline()
    timeline.open_script("source s.busk")
    timeline.push(show_step(1))
    timeline.clear()
    timeline.push(show_step(2))
    timeline.close_script()
    assert labels(timeline) == ["source s.busk"]


def test_a_script_longer_than_the_timeline_is_one_step() -> None:
    timeline = Timeline()
    timeline.push(show_step(1))
    timeline.open_script("source long.busk")
    for n in range(1, LIMIT + 10):
        timeline.push(step(n))
    timeline.close_script()
    assert labels(timeline) == ["source long.busk", "edit 1"]


# ----------------------------------------------- one undo, wherever it runs

SCRIPT = (
    "# a par, programmed and recorded\n"
    'fixture add 301 "RGB Par 3ch" mode 3ch at 1.200\n'
    "\n"
    "  sel fixture 301  \n"
    "set intensity 50%\n"
    "record cue 30/1\n"
)


@pytest.fixture
def script(tmp_path: Path) -> Path:
    path = tmp_path / "par.busk"
    path.write_text(SCRIPT)
    return path


RENAME = 'fixture 201 name "Front"'
"""The step before the script, labelled :data:`RENAMED`."""

RENAMED = 'set fixtures[2].name to "Front"'


@pytest.fixture
def offline() -> OfflineShow:
    """Appendix A, with a step before the script."""
    show = OfflineShow(show_of(load_doc(APPENDIX_A)))
    assert show.execute(RENAME).text == RENAMED
    return show


@pytest.fixture
def live() -> Iterator[LiveShow]:
    """Appendix A, running, without output, with a step before the script."""
    with LiveShow(show_of(load_doc(APPENDIX_A)), output=False) as show:
        assert show.execute(RENAME).text == RENAMED
        yield show


def numbers(show: OfflineShow | LiveShow) -> list[int]:
    return [fixture["number"] for fixture in show.show["fixtures"]]


def selected(show: OfflineShow | LiveShow) -> list[tuple[int, int]]:
    return list(show.programmer.selection)


def published(show: OfflineShow | LiveShow, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """The snapshots the show's session publishes from now on."""
    session = show._session
    snapshots: list[SessionSnapshot] = []
    original = session._publish

    def publish() -> None:
        original()
        snapshots.append(session.snapshot)

    monkeypatch.setattr(session, "_publish", publish)
    return snapshots


@pytest.mark.parametrize("how", ["source", "OfflineShow.run_script", "LiveShow.run_script"])
def test_one_undo_puts_back_the_show_and_the_programmer_and_one_redo_brings_both(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    script: Path,
    how: str,
) -> None:
    show: OfflineShow | LiveShow = request.getfixturevalue(
        "live" if how.startswith("Live") else "offline"
    )
    before, steps = show.show, show.session.undoSteps
    if how == "source":
        assert show.execute(f"source {script}").ok
    else:
        show.run_script(script)
    after, label = show.show, f"source {script}"
    assert 301 in numbers(show)
    assert selected(show) == [(301, 1)]
    assert show.session.undoSteps == steps + 1
    assert show.session.nextUndo == label

    snapshots = published(show, monkeypatch)
    assert show.execute("undo").text == f"undid: {label}"
    assert len(snapshots) == 1  # the show and the programmer, in one change
    assert snapshots[0].show == before
    assert snapshots[0].programmer.selection == ()
    assert dict(snapshots[0].programmer.values) == {}
    assert show.session.nextUndo == RENAMED

    snapshots.clear()
    assert show.execute("redo").text == f"redid: {label}"
    assert len(snapshots) == 1
    assert show.show == after
    assert selected(show) == [(301, 1)]  # restored once 301 is back in the show
    assert [v.attribute for v in show.programmer.values] == ["intensity"]


def test_busk_run_script_is_one_step(tmp_path: Path, script: Path) -> None:
    """``busk run --script``: the prompt's ``undo`` after it takes back the script."""
    show = tmp_path / "club.json"
    OfflineShow(show_of(load_doc(APPENDIX_A)), path=show).save()
    done = subprocess.run(
        [sys.executable, "-m", "busk", "run", str(show), "--script", str(script)],
        input="info\nundo\nlist fixtures\n",
        capture_output=True,
        text=True,
        env={**os.environ, "XDG_STATE_HOME": str(tmp_path / "state")},
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    out = done.stdout.splitlines()
    assert "undo: 1 step, redo: 0 steps" in out
    assert f"undid: source {script}" in out
    listed = [line.split()[0] for line in out if line.startswith("  ")]
    assert listed == ["101", "102", "201"]  # list fixtures, after the undo


def test_a_nested_source_joins_the_outer_step(offline: OfflineShow, tmp_path: Path) -> None:
    inner = tmp_path / "inner script.busk"
    inner.write_text('fixture 102 name "Inner"\n')
    outer = tmp_path / "outer.busk"
    outer.write_text(f'fixture 101 name "Outer"\nsource "{inner}"\nsel fixture 101\n')
    steps = offline.session.undoSteps
    offline.run_script(outer)
    assert offline.session.undoSteps == steps + 1
    assert offline.execute("undo").text == f"undid: source {outer}"
    assert [f["name"] for f in offline.show["fixtures"][:2]] == ["MH 1", "MH 2"]
    assert selected(offline) == []


def test_the_label_quotes_a_path_as_source_takes_it(offline: OfflineShow, tmp_path: Path) -> None:
    path = tmp_path / "my rig.busk"
    path.write_text("sel fixture 101\n")
    assert offline.execute(f'source "{path}"').ok
    assert offline.session.nextUndo == f'source "{path}"'


def test_a_script_that_fails_leaves_one_step_for_the_lines_that_ran(
    offline: OfflineShow, tmp_path: Path
) -> None:
    path = tmp_path / "half.busk"
    path.write_text('fixture 101 name "A"\nsel fixture 101\nfixture 999 name "No"\nclear\n')
    steps = offline.session.undoSteps
    reply = offline.execute(f"source {path}")
    assert not reply.ok
    assert offline.session.undoSteps == steps + 1
    assert selected(offline) == [(101, 1)]  # the line after the error did not run
    assert offline.execute("undo").text == f"undid: source {path}"
    assert offline.show["fixtures"][0]["name"] == "MH 1"
    assert selected(offline) == []


def test_a_script_that_changes_nothing_leaves_no_step(offline: OfflineShow, tmp_path: Path) -> None:
    path = tmp_path / "reads.busk"
    path.write_text("# only reads\n\nlist fixtures\ninfo\nblind on\nblind off\n")
    status = offline.session
    offline.run_script(path)
    assert (offline.session.undoSteps, offline.session.nextUndo) == (
        status.undoSteps,
        status.nextUndo,
    )


def test_an_undo_line_takes_back_the_step_so_far_and_the_lines_after_make_another(
    offline: OfflineShow, tmp_path: Path
) -> None:
    path = tmp_path / "undoing.busk"
    path.write_text('fixture 101 name "A"\nfixture 102 name "B"\nundo\nfixture 201 name "C"\n')
    output = offline.run_script(path)
    assert f"undid: source {path}" in output
    assert [f["name"] for f in offline.show["fixtures"]] == ["MH 1", "MH 2", "C"]
    assert offline.execute("undo").text == f"undid: source {path}"
    assert offline.show["fixtures"][2]["name"] == "Front"  # the step before the script
    assert offline.execute("undo").text == f"undid: {RENAMED}"


def test_a_quit_line_ends_the_script_and_its_step(offline: OfflineShow, tmp_path: Path) -> None:
    path = tmp_path / "quits.busk"
    path.write_text('fixture 101 name "A"\nquit\nfixture 102 name "B"\n')
    assert offline.execute(f"source {path}").quit
    assert offline.execute('fixture 102 name "Later"').ok  # a step of its own
    assert offline.execute("undo").ok
    assert offline.execute("undo").text == f"undid: source {path}"


def test_the_steps_before_a_script_longer_than_the_timeline_stay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``examples/festival.busk`` has more lines than the timeline keeps
    steps; it reads its profiles from the repository."""
    festival = Path("examples") / "festival.busk"
    monkeypatch.chdir(ROOT)
    assert len(festival.read_text().splitlines()) > LIMIT
    show = OfflineShow(new_show("Festival"), path=tmp_path / "festival.show")
    renamed = show.execute('rename show "Before"').text
    before = show.show
    show.run_script(festival)
    after = show.show
    assert show.session.undoSteps == 2
    assert show.execute("undo").text == "undid: source examples/festival.busk"
    assert unsaved(show.show) == unsaved(before)
    assert show.session.nextUndo == renamed
    assert show.execute("redo").ok
    assert show.show == after


def unsaved(show: Any) -> Any:
    """``show`` without ``meta.modified``, which the script's ``save`` sets
    outside the timeline."""
    return {**show, "meta": {**show["meta"], "modified": None}}


# ----------------------------------------------------------- beside a script

SELECT_102: Command = cast(
    Command,
    {
        "type": "SELECT",
        "targets": {"kind": "targets", "refs": [{"fixtureId": "fx-mh2", "element": 0}]},
        "mode": "replace",
    },
)


def test_a_performance_line_beside_a_script_pushes_no_step(live: LiveShow, tmp_path: Path) -> None:
    path = tmp_path / "two.busk"
    path.write_text('fixture 101 name "A"\nfixture 102 name "B"\n')
    replies: list[Reply] = []

    def beside(number: int, total: int, line: str, reply: Reply) -> None:
        if number == 1:  # the script holds the console: the line does not wait for it
            other = threading.Thread(target=lambda: replies.append(live.execute("gm 50%")))
            other.start()
            other.join(5)

    steps = live.session.undoSteps
    live.run_script(path, each=beside)
    assert replies == [Reply("")]
    assert live.session.undoSteps == steps + 1
    assert live.session.nextUndo == f"source {path}"


def test_a_command_another_thread_submits_meanwhile_joins_the_step(
    live: LiveShow, tmp_path: Path
) -> None:
    path = tmp_path / "two.busk"
    path.write_text('fixture 101 name "A"\nfixture 102 name "B"\n')

    def beside(number: int, total: int, line: str, reply: Reply) -> None:
        if number == 1:
            other = threading.Thread(target=live.submit, args=(SELECT_102,))
            other.start()
            other.join(5)

    steps = live.session.undoSteps
    live.run_script(path, each=beside)
    assert selected(live) == [(102, 1)]
    assert live.session.undoSteps == steps + 1
    assert live.execute("undo").text == f"undid: source {path}"
    assert selected(live) == []


# ------------------------------------------------------------- each line


def test_each_line_is_told_in_order_with_the_total_and_its_reply(
    offline: OfflineShow, script: Path
) -> None:
    calls: list[tuple[int, int, str, Reply]] = []
    offline.run_script(script, each=lambda *call: calls.append(call))
    assert [(n, total, line) for n, total, line, _ in calls] == [
        (1, 6, "# a par, programmed and recorded"),
        (2, 6, 'fixture add 301 "RGB Par 3ch" mode 3ch at 1.200'),
        (3, 6, ""),
        (4, 6, "sel fixture 301"),
        (5, 6, "set intensity 50%"),
        (6, 6, "record cue 30/1"),
    ]
    assert [reply.text for *_, reply in calls] == [
        "",
        "added fixture 301: RGB Par 3ch, 3ch",
        "",
        "1 target selected",
        "intensity: 1 target",
        "added cue list 'Cue list 30'; recorded cue 30/1: 1 entry",
    ]
    assert all(reply.ok for *_, reply in calls)


def test_a_failing_line_is_told_before_the_script_error(
    offline: OfflineShow, tmp_path: Path
) -> None:
    path = tmp_path / "fails.busk"
    path.write_text('sel fixture 101\nfixture 999 name "No"\nclear\n')
    calls: list[tuple[int, int, str, Reply]] = []
    with pytest.raises(ScriptError) as raised:
        offline.run_script(path, each=lambda *call: calls.append(call))
    assert [(n, total, line, reply.ok) for n, total, line, reply in calls] == [
        (1, 3, "sel fixture 101", True),
        (2, 3, 'fixture 999 name "No"', False),
    ]
    assert calls[1][3].text == "error: no fixture 999"
    assert raised.value.line == 2


def test_a_nested_source_is_one_call_with_its_whole_reply(
    offline: OfflineShow, tmp_path: Path
) -> None:
    inner = tmp_path / "inner.busk"
    inner.write_text("sel fixture 101\nsel fixture 102\n")
    outer = tmp_path / "outer.busk"
    outer.write_text(f"source {inner}\n")
    calls: list[tuple[int, int, str, Reply]] = []
    offline.run_script(outer, each=lambda *call: calls.append(call))
    assert [(n, total, line, reply.text) for n, total, line, reply in calls] == [
        (1, 1, f"source {inner}", "1 target selected\n1 target selected"),
    ]


def test_on_a_live_show_each_line_is_told_as_it_runs_on_the_scripts_thread(
    live: LiveShow, tmp_path: Path
) -> None:
    path = tmp_path / "names.busk"
    path.write_text('fixture 101 name "A"\nfixture 101 name "B"\nfixture 101 name "C"\n')
    seen: list[tuple[str, int]] = []

    def each(number: int, total: int, line: str, reply: Reply) -> None:
        seen.append((live.show["fixtures"][0]["name"], threading.get_ident()))

    worker: list[int] = []

    def run() -> None:
        worker.append(threading.get_ident())
        live.run_script(path, each=each)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(10)
    assert seen == [("A", worker[0]), ("B", worker[0]), ("C", worker[0])]


def test_an_exception_from_each_stops_the_script_and_comes_out(
    offline: OfflineShow, tmp_path: Path
) -> None:
    path = tmp_path / "names.busk"
    path.write_text('fixture 101 name "A"\nfixture 101 name "B"\n')

    def stop(number: int, total: int, line: str, reply: Reply) -> None:
        raise RuntimeError("enough")

    with pytest.raises(RuntimeError, match="enough"):
        offline.run_script(path, each=stop)
    assert offline.show["fixtures"][0]["name"] == "A"
    assert offline.execute('fixture 102 name "Later"').ok  # the script's step is closed
    assert offline.session.nextUndo == 'set fixtures[1].name to "Later"'
    assert offline.execute("undo").ok
    assert offline.execute("undo").text == f"undid: source {path}"
