"""Renaming and deleting a master (GAP-53 of ``docs/dev/tui/engine-gaps.md``).

``rename master "<name>" "<new name>"`` and ``delete master "<name>"
[cascade]``, each one undo step with a reply in words. The grand master is
neither renamed nor deleted. A delete is refused while a cue's effect, a cue
list's chase or an effect in the programmer names the master, even with
``cascade``, and the refusal names them. A binding that names it is refused
by a plain delete, and goes with ``cascade``, after the question.

The rig below has three pars in a group, and one master of each kind.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from builders import ROOT
from busk import LiveShow, OfflineShow, load_show, new_show
from busk.commands.types import Command
from busk.persistence.show_file import save_show

CLUB_NIGHT = ROOT / "examples" / "club-night.busk"
KINDS = {"Tempo": "speed", "FX": "size", "Pars level": "group", "Fade": "fadeTime"}


def run(show: OfflineShow, *lines: str) -> None:
    for line in lines:
        reply = show.execute(line)
        assert reply.ok, (line, reply.text)


def said(show: OfflineShow, line: str) -> str:
    """The reply to ``line``, which must be refused."""
    reply = show.execute(line)
    assert not reply.ok, (line, reply.text)
    return reply.text


@pytest.fixture
def rig() -> OfflineShow:
    show = OfflineShow(new_show("Rig"))
    run(
        show,
        'universe add 1 "Stage"',
        'fixture add 1 thru 3 "RGB Par 3ch" mode 3ch at 1.1',
        "sel fixture 1 thru 3",
        'record group 1 "Pars"',
        "sel none",
        'master add speed "Tempo"',
        'master add size "FX"',
        'master add group "Pars level" group 1',
        'master add fadetime "Fade"',
        'surface add midi "Pad"',
    )
    return show


def master_id(show: OfflineShow, name: str) -> str:
    return str(next(m["id"] for m in show.show["masters"] if m["name"] == name))


def names(show: OfflineShow) -> list[str]:
    return [m["name"] for m in show.show["masters"]]


def submit(show: OfflineShow, command: dict[str, Any]) -> None:
    result = show.submit(cast(Command, command))
    assert result.ok, result.message


def bind_action(show: OfflineShow, ident: str, action: dict[str, Any]) -> None:
    surface = show.show["surfaces"][0]["id"]
    binding = {
        "id": ident,
        "surfaceId": surface,
        "input": {"kind": "midiNote", "channel": 1, "note": len(show.show["bindings"])},
        "action": action,
    }
    submit(show, {"type": "ADD", "path": ["bindings"], "value": binding})


def bind(show: OfflineShow, ident: str, command: dict[str, Any]) -> None:
    bind_action(show, ident, {"kind": "command", "command": command})


def one_step(show: OfflineShow, line: str) -> Any:
    """Run ``line``; check that one ``undo`` gives the document back and that
    ``redo`` does it again. The document after it."""
    before = copy.deepcopy(show.show)
    run(show, line)
    after = copy.deepcopy(show.show)
    run(show, "undo")
    assert show.show == before
    run(show, "redo")
    assert show.show == after
    return show.show


def an_effect(show: OfflineShow, *options: str) -> dict[str, Any]:
    """An effect of the library's Pulse on the pars, with ``options``, as the
    programmer makes it; the programmer is cleared after."""
    run(show, "sel group 1", f'effect add "Pulse" id probe {" ".join(options)}'.rstrip())
    effect = copy.deepcopy(dict(next(e for e in show.programmer.effects if e["id"] == "probe")))
    run(show, "clear", "sel none")
    return effect


# ----------------------------------------------------------------- rename


@pytest.mark.parametrize("name", list(KINDS))
def test_each_kind_is_renamed_in_one_step(rig: OfflineShow, name: str) -> None:
    ident = master_id(rig, name)
    reply = rig.execute(f'rename master "{name}" "New name"')
    assert reply.ok, reply.text
    assert reply.text == f'renamed master "{name}" to "New name"'
    run(rig, "undo")
    assert master_id(rig, name) == ident
    run(rig, "redo")
    master = next(m for m in rig.show["masters"] if m["id"] == ident)
    assert (master["name"], master["kind"]) == ("New name", KINDS[name])


def test_a_master_is_named_in_any_case(rig: OfflineShow) -> None:
    run(rig, 'rename master "tempo" "Beat"')
    assert "Beat" in names(rig)


def test_a_master_may_change_the_case_of_its_own_name(rig: OfflineShow) -> None:
    run(rig, 'rename master "FX" "fx"')
    assert "fx" in names(rig)


def test_a_name_another_master_has_is_refused_in_any_case(rig: OfflineShow) -> None:
    assert said(rig, 'rename master "FX" "tempo"') == "error: a master named 'tempo' exists"
    assert said(rig, 'rename master "FX" "grand master"') == (
        "error: a master named 'grand master' exists"
    )


def test_what_uses_a_master_follows_its_new_name(rig: OfflineShow) -> None:
    run(rig, "sel group 1", 'effect add "Pulse" bpm "Tempo" sizemaster "FX"', "record cue 5/1")
    run(rig, 'rename master "Tempo" "Beat"', 'rename master "FX" "Size"')
    run(rig, 'cuelist 5 chase bpm "beat" x 2', 'master "size" 50%', 'bpm "Beat" 128')
    assert "bpm 'Beat'" in rig.execute("programmer").text


@pytest.mark.parametrize("verb", ["rename", "delete"])
def test_the_grand_master_is_neither_renamed_nor_deleted(rig: OfflineShow, verb: str) -> None:
    line = f'{verb} master "Grand Master"' + (' "GM"' if verb == "rename" else "")
    past = "renamed" if verb == "rename" else "deleted"
    assert said(rig, line) == f"error: the grand master cannot be {past}"
    assert said(rig, 'delete master "grand master" cascade') == (
        "error: the grand master cannot be deleted"
    )


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ('rename master "Nope" "X"', "no master 'Nope'"),
        ('delete master "Nope"', "no master 'Nope'"),
        ("rename master FX X", 'expected a master name in quotes, e.g. "Speed 1"'),
        ("delete master FX", 'expected a master name in quotes, e.g. "Speed 1"'),
        ('rename master "FX"', "expected a name in quotes"),
        ('rename master "FX" Size', "expected a name in quotes"),
        ('rename master "FX" "Size" now', "unexpected 'now'"),
        ('delete master "FX" now', "unexpected 'now'"),
        ('delete master "FX" cascade now', "unexpected 'now'"),
    ],
)
def test_what_is_refused(rig: OfflineShow, line: str, error: str) -> None:
    assert said(rig, line) == f"error: {error}"


def test_tab_offers_every_master_but_the_grand_one(rig: OfflineShow) -> None:
    offered = ('"Tempo"', '"FX"', '"Pars level"', '"Fade"')
    assert rig.expected("rename master ").words == offered
    assert rig.expected("delete master ").words == offered
    assert rig.expected('delete master "F').words == ('"FX"', '"Fade"')
    assert rig.expected('delete master "Fade" ').words == ("cascade",)
    assert "master" in rig.expected("rename ").words
    assert "master" in rig.expected("delete ").words


# ----------------------------------------------------------------- delete


@pytest.mark.parametrize("name", list(KINDS))
def test_each_kind_nothing_uses_goes_plainly_in_one_step(rig: OfflineShow, name: str) -> None:
    assert rig.confirmation(f'delete master "{name}"') is None
    doc = one_step(rig, f'delete master "{name}"')
    assert name not in [m["name"] for m in doc["masters"]]
    run(rig, "undo")
    assert rig.execute(f'delete master "{name}"').text == f'deleted master "{name}"'


def test_with_nothing_to_cascade_it_still_asks(rig: OfflineShow) -> None:
    assert rig.confirmation('delete master "FX" cascade') == 'Delete master "FX"?'
    assert rig.execute('delete master "FX" cascade').text == 'deleted master "FX"'


def test_a_cues_effect_on_its_beat_keeps_it(rig: OfflineShow) -> None:
    run(rig, "sel group 1", 'effect add "Pulse" bpm "Tempo"', "record cue 5/1", "clear")
    refusal = 'error: master "Tempo" is used by effects in cue 5/1: change them first'
    assert said(rig, 'delete master "Tempo"') == refusal
    assert said(rig, 'delete master "Tempo" cascade') == refusal
    assert rig.confirmation('delete master "Tempo" cascade') is None
    found = rig.expected('delete master "Tempo" ')
    assert (found.words, found.error) == ((), refusal.removeprefix("error: "))  # no cascade


@pytest.mark.parametrize(
    ("name", "options"),
    [("Tempo", 'hz 2 speedmaster "Tempo"'), ("FX", 'sizemaster "FX"')],
    ids=["speedmaster", "sizemaster"],
)
def test_a_cues_effect_that_names_it_otherwise_keeps_it(
    rig: OfflineShow, name: str, options: str
) -> None:
    run(rig, "sel group 1", f'effect add "Pulse" {options}', "record cue 5/1")
    run(rig, "clear", "sel group 1", f'effect add "Pulse" {options}', "record cue 6/1", "clear")
    assert said(rig, f'delete master "{name}" cascade') == (
        f'error: master "{name}" is used by effects in cues 5/1, 6/1: change them first'
    )


def test_a_chase_keeps_its_master(rig: OfflineShow) -> None:
    run(rig, "sel group 1", "set intensity 100%", "record cue 5/1", "record cue 5/2", "clear")
    run(rig, 'cuelist 5 chase bpm "Tempo"')
    assert said(rig, 'delete master "Tempo"') == (
        'error: master "Tempo" is used by the chase of cue list 5: change them first'
    )
    run(rig, "cuelist 5 sequence")  # it keeps its chase settings, which the validator reads
    assert said(rig, 'delete master "Tempo" cascade') == (
        'error: master "Tempo" is used by the chase of cue list 5: change them first'
    )
    run(rig, "cuelist 5 chase none")
    run(rig, 'delete master "Tempo"')


def test_the_refusal_names_every_chase_and_cue(rig: OfflineShow) -> None:
    run(rig, "sel group 1", "set intensity 100%", "record cue 5/1", "record cue 6/1", "clear")
    run(rig, 'cuelist 5 chase bpm "Tempo"', 'cuelist 6 chase bpm "Tempo" x 2')
    run(rig, "sel group 1", 'effect add "Pulse" bpm "Tempo"', "record cue 7/1", "clear")
    run(rig, "sel group 1", 'effect add "Pulse" bpm "Tempo"')
    assert said(rig, 'delete master "Tempo"') == (
        'error: master "Tempo" is used by the chases of cue lists 5, 6, effects in cue 7/1 and '
        "the programmer: change them first"
    )


def test_the_programmers_effect_keeps_it(rig: OfflineShow) -> None:
    run(rig, "sel group 1", 'effect add "Pulse" sizemaster "FX"')
    refusal = 'error: master "FX" is used by the programmer: change them first'
    assert said(rig, 'delete master "FX" cascade') == refusal
    run(rig, "effect clear")
    run(rig, 'delete master "FX"')


def test_a_chase_or_an_effect_on_another_master_does_not_keep_it(rig: OfflineShow) -> None:
    run(rig, 'master add speed "Other"', "sel group 1", "set intensity 100%", "record cue 5/1")
    run(rig, "clear", 'cuelist 5 chase bpm "Other"', "sel group 1")
    run(rig, 'effect add "Pulse" bpm "Other"', "record cue 6/1", 'effect add "Pulse" hz 2')
    run(rig, 'delete master "Tempo"', 'delete master "FX"')


def test_a_binding_that_names_it_needs_the_cascade(rig: OfflineShow) -> None:
    bind_action(rig, "level", {"kind": "master", "masterId": master_id(rig, "FX")})
    assert said(rig, 'delete master "FX"') == (
        'error: master "FX" is used by 1 binding: add cascade'
    )
    assert rig.expected('delete master "FX"').error is None
    doc = one_step(rig, 'delete master "FX" cascade')
    assert doc["bindings"] == []


def test_the_bindings_that_name_it_go_and_the_others_stay(rig: OfflineShow) -> None:
    tempo, fx, grand = (master_id(rig, name) for name in ("Tempo", "FX", "Grand Master"))
    on_tempo = an_effect(rig, 'bpm "Tempo"')
    on_hz = an_effect(rig, "hz 2")
    bind_action(rig, "drive", {"kind": "master", "masterId": tempo})
    bind_action(rig, "tap", {"kind": "tap", "masterId": tempo})
    bind(rig, "set", {"type": "SET_MASTER", "masterId": tempo, "level": 1})
    bind(rig, "tap2", {"type": "TAP", "masterId": tempo})
    bind(rig, "bpm", {"type": "SET_BPM", "masterId": tempo, "bpm": 128})
    bind(rig, "fx", {"type": "ADD_EFFECT", "effect": on_tempo})
    bind_action(rig, "fx level", {"kind": "master", "masterId": fx})
    bind(rig, "grand", {"type": "SET_MASTER", "masterId": grand, "level": 1})
    bind(rig, "other fx", {"type": "ADD_EFFECT", "effect": on_hz})
    assert said(rig, 'delete master "Tempo"') == (
        'error: master "Tempo" is used by 6 bindings: add cascade'
    )
    assert rig.confirmation('delete master "Tempo" cascade') == (
        'Delete master "Tempo"? It leaves 6 bindings.'
    )
    doc = one_step(rig, 'delete master "Tempo" cascade')
    assert [b["id"] for b in doc["bindings"]] == ["fx level", "grand", "other fx"]
    run(rig, "undo")
    assert rig.execute('delete master "Tempo" cascade').text == (
        'deleted master "Tempo": left 6 bindings'
    )


def test_a_midi_clock_that_taps_it_goes(rig: OfflineShow) -> None:
    run(rig, 'bind "Pad" clock tap "Tempo"')
    assert said(rig, 'delete master "Tempo"') == (
        'error: master "Tempo" is used by 1 binding: add cascade'
    )
    run(rig, 'delete master "Tempo" cascade')
    assert rig.show["bindings"] == []


def test_the_question_says_one_binding_in_the_singular(rig: OfflineShow) -> None:
    run(rig, 'bind "Pad" cc 1 7 master "Pars level"')
    assert rig.confirmation('delete master "Pars level" cascade') == (
        'Delete master "Pars level"? It leaves 1 binding.'
    )
    assert rig.execute('delete master "Pars level" cascade').text == (
        'deleted master "Pars level": left 1 binding'
    )


def test_a_name_with_a_quote_is_written_as_it_is_typed(rig: OfflineShow) -> None:
    run(rig, 'rename master "FX" "The \\"FX\\""')
    assert rig.confirmation('delete master "the \\"fx\\"" cascade') == (
        'Delete master "The \\"FX\\""?'
    )


def test_a_group_still_takes_its_group_master(rig: OfflineShow) -> None:
    run(rig, "delete group 1 cascade")
    assert "Pars level" not in names(rig)


def test_a_script_does_not_ask(rig: OfflineShow, tmp_path: Path) -> None:
    run(rig, 'bind "Pad" cc 1 7 master "FX"')
    script = tmp_path / "masters.busk"
    script.write_text('delete master "FX" cascade\nrename master "Tempo" "Beat"\n')
    rig.run_script(script)
    assert names(rig) == ["Grand Master", "Beat", "Pars level", "Fade"]


# ----------------------------------------------------------- the club show


@pytest.fixture(scope="module")
def club_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("club") / "club.show"
    show = OfflineShow(new_show("Club Night"), path=path)
    show.run_script(CLUB_NIGHT)
    return path


@pytest.fixture
def club(club_path: Path) -> OfflineShow:
    show, _ = load_show(club_path)
    return OfflineShow(show)


def test_the_club_shows_masters_in_use_stay(club: OfflineShow) -> None:
    assert said(club, 'delete master "Speed 1" cascade') == (
        'error: master "Speed 1" is used by the chase of cue list 10 and effects in cues 11/1, '
        "12/1, 13/1: change them first"
    )
    assert said(club, 'delete master "FX" cascade') == (
        'error: master "FX" is used by effects in cues 11/1, 12/1: change them first'
    )


def test_the_club_shows_other_masters_go_and_the_show_saves_and_reloads(
    club: OfflineShow, tmp_path: Path
) -> None:
    before = copy.deepcopy(club.show)
    run(club, 'delete master "Wash level" cascade', 'delete master "Fade" cascade')
    run(club, 'rename master "Speed 1" "Tempo"', 'rename master "FX" "Size"')
    path = tmp_path / "after.show"
    save_show(club.show, path)
    reloaded, issues = load_show(path)
    assert [m["name"] for m in reloaded["masters"]] == ["Grand Master", "Tempo", "Size"]
    assert not [issue for issue in issues if issue.severity == "error"]
    run(club, "undo", "undo", "undo", "undo")
    assert club.show == before


# --------------------------------------------------------- a running show


def eventually(condition: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_a_master_at_a_level_goes_from_a_running_show(rig: OfflineShow) -> None:
    with LiveShow(rig.show, output=False) as live:
        pars, fade = master_id(rig, "Pars level"), master_id(rig, "Fade")

        def intensities() -> list[float]:
            output = live.output
            return [] if output is None else [round(f.intensity, 3) for f in output.fixtures]

        def levels() -> dict[str, float]:
            snapshot = live.snapshot
            return {} if snapshot is None else dict(snapshot.masterLevels)

        def fade_time() -> float | None:
            snapshot = live.snapshot
            return None if snapshot is None else snapshot.fadeTime

        for line in ("sel group 1", "set intensity 100%", 'master "Pars level" 0%'):
            assert live.execute(line).ok, line
        assert live.execute('master "Fade" 50%').ok
        eventually(lambda: intensities() == [0.0, 0.0, 0.0] and fade_time() is not None)
        reply = live.execute('delete master "Pars level"')
        assert reply.ok, reply.text
        eventually(lambda: intensities() == [1.0, 1.0, 1.0] and pars not in levels())
        assert live.execute('delete master "Fade"').ok
        eventually(lambda: fade_time() is None and fade not in levels())
        assert live.execute("undo").ok
        assert live.execute("undo").ok
        eventually(lambda: levels().get(pars) == 1.0 and fade in levels())
        assert intensities() == [1.0, 1.0, 1.0]  # back at its initial level, not at 0%
        assert live.show == rig.show


def test_a_master_is_renamed_on_a_running_show(rig: OfflineShow) -> None:
    with LiveShow(rig.show, output=False) as live:

        def speed() -> list[str]:
            snapshot = live.snapshot
            return [] if snapshot is None else [s.name for s in snapshot.speed]

        eventually(lambda: speed() == ["Tempo"])
        assert live.execute('rename master "Tempo" "Beat"').ok
        eventually(lambda: speed() == ["Beat"])
        assert live.execute('bpm "Beat" 90').ok
        assert live.execute("undo").ok
        eventually(lambda: speed() == ["Tempo"])
