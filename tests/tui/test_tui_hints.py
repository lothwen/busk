"""The hint row and Tab completion (``busk_tui.hints``), against busk's real
``help`` text and real ``expected`` answers on the club-night show."""

from __future__ import annotations

import pytest

import busk
from busk_tui.hints import EMPTY_HINT, Completed, HelpIndex, complete, hint, next_words
from busk_tui.model import Completion


@pytest.fixture(scope="module")
def index(club: busk.OfflineShow) -> HelpIndex:
    return HelpIndex(club.execute("help").text.splitlines())


def asked(show: busk.OfflineShow, line: str) -> Completion:
    answer = show.expected(line)
    return Completion(answer.words, answer.values, answer.runnable, answer.error, answer.start)


def test_alternatives_are_indexed_by_their_first_word(index: HelpIndex) -> None:
    (form,) = index.syntax("blind")
    assert form.startswith("clear | blind on|off | highlight on|off")
    assert index.syntax("redo") == index.syntax("undo")
    assert index.syntax("goto 1 2")[0].startswith("go N | back N | goto N <cue>")


def test_the_notes_under_a_form_are_not_forms(index: HelpIndex) -> None:
    assert index.syntax("hz") == []  # "(hz: the widget's output rate …)" is a note
    assert all(not form.startswith("<") for form in index.syntax("set"))


def test_up_to_two_forms_those_naming_the_words_typed_first(index: HelpIndex) -> None:
    assert len(index.syntax("set")) == 2
    assert index.syntax("set")[0].startswith("set <attribute> <value>")
    spread = index.syntax("set intensity spread")
    assert spread[0].startswith("set <attribute> spread <from>")
    assert len(spread) == 2


def test_an_empty_prompt_says_what_to_do(index: HelpIndex) -> None:
    assert hint(index, "", None).syntax == EMPTY_HINT
    assert hint(index, "   ", None).syntax == EMPTY_HINT


def test_a_first_word_shows_its_syntax(index: HelpIndex, club: busk.OfflineShow) -> None:
    shown = hint(index, "blackout", asked(club, "blackout"))
    assert shown.syntax.startswith("gm <level> | master")
    assert shown.expected == ""


def test_a_prefix_lists_the_commands_it_starts(index: HelpIndex, club: busk.OfflineShow) -> None:
    assert hint(index, "se", asked(club, "se")).syntax == "sel · set"
    assert hint(index, "u", asked(club, "u")).syntax == "unbind · undo · universe · unpark"


def test_a_word_that_starts_nothing_is_an_unknown_command(
    index: HelpIndex, club: busk.OfflineShow
) -> None:
    assert hint(index, "xyz", asked(club, "xyz")).syntax == "unknown command"


def test_after_the_first_word_what_may_come_then_the_syntax(
    index: HelpIndex, club: busk.OfflineShow
) -> None:
    shown = hint(index, "blind ", asked(club, "blind "))
    assert shown.expected == "next: off on"
    assert shown.syntax.startswith("clear | blind on|off")
    values = hint(index, "set intensity ", asked(club, "set intensity "))
    assert values.expected == "next: by preset spread <a number>"


def test_enter_is_offered_only_with_nothing_typed_of_the_word(club: busk.OfflineShow) -> None:
    assert next_words("clear ", asked(club, "clear ")) == "next: <Enter>"
    assert "<Enter>" not in next_words("fade 2", asked(club, "fade 2"))
    assert next_words("fade 2", asked(club, "fade 2")) == "next: <a time in seconds>"


def test_the_mistake_that_stops_the_line(index: HelpIndex, club: busk.OfflineShow) -> None:
    shown = hint(index, "fixture 999 ", asked(club, "fixture 999 "))
    assert shown.error
    assert shown.expected == "error: no fixture 999"


def test_nothing_typed_matches(club: busk.OfflineShow) -> None:
    assert next_words("blind x", asked(club, "blind x")) == "nothing here starts with 'x'"


def test_without_the_engines_answer_only_the_syntax(index: HelpIndex) -> None:
    assert hint(index, "set intensity ", None).expected == ""
    assert hint(None, "set intensity ", None).syntax == ""


@pytest.mark.parametrize(
    ("line", "completed"),
    [
        ("route add 1 sa", "route add 1 sacn "),
        ('master "Grand M', 'master "Grand Master" '),
        ("reco", "record "),
        ("blind of", "blind off "),
    ],
)
def test_one_word_completes_the_word_and_a_space(
    club: busk.OfflineShow, line: str, completed: str
) -> None:
    done = complete(line, len(line), asked(club, line))
    assert done == Completed(completed, len(completed))


def test_several_words_extend_what_they_share_and_are_listed(club: busk.OfflineShow) -> None:
    done = complete("u", 1, asked(club, "u"))
    assert done.line == "un"
    assert done.cursor == 2
    assert done.candidates == ("unbind", "undo", "universe", "unpark")
    same = complete("se", 2, asked(club, "se"))
    assert (same.line, same.cursor, same.candidates) == ("se", 2, ("sel", "set"))


def test_completion_in_the_middle_of_a_line_keeps_the_rest(club: busk.OfflineShow) -> None:
    line = "blind of  # the rest"
    done = complete(line, 8, asked(club, line[:8]))
    assert done.line == "blind off  # the rest"
    assert done.cursor == 9  # after the word: the space was there already


def test_nothing_to_complete_changes_nothing(club: busk.OfflineShow) -> None:
    assert complete("fade 2", 6, asked(club, "fade 2")) == Completed("fade 2", 6)
