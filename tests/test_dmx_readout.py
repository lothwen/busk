"""The DMX readout (GAP-52 of ``docs/dev/tui/engine-gaps.md``).

``list dmx U [A [thru B]]`` prints a universe's channels as the engine's last
frame has them, which is what goes out after the masters, park, blackout and
limits, 16 values to a line after the address of the first. ``list dmx fixture
N`` prints each channel of a fixture's footprint with its function in its mode
and its value. ``list universes`` counts the channels that fixtures take and the
pairs of them that overlap, as F8 does.

The club show: heads 101 and 102 (Generic Spot 16ch) at 1.1 and 1.17, washes
201 to 204 (4 channels) from 1.33, the pixel bar 301 (12 cells of RGB) at 1.49.
Wash 204 is parked dark, and the bar never runs above half.
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest

from builders import ROOT
from busk import LiveShow, OfflineShow, load_show, new_show
from busk.model.show import Show

CLUB_NIGHT = ROOT / "examples" / "club-night.busk"


@pytest.fixture(scope="module")
def club_show(tmp_path_factory: pytest.TempPathFactory) -> Show:
    path = tmp_path_factory.mktemp("club") / "club.show"
    OfflineShow(new_show("Club Night"), path=path).run_script(CLUB_NIGHT)
    return load_show(path)[0]


@pytest.fixture
def club(club_show: Show) -> OfflineShow:
    return OfflineShow(copy.deepcopy(club_show))


def run(show: OfflineShow | LiveShow, *lines: str) -> list[str]:
    texts = []
    for line in lines:
        reply = show.execute(line)
        assert reply.ok, f"{line}: {reply.text}"
        texts.append(reply.text)
    return texts


def listed(text: str) -> dict[int, int]:
    """The values ``list dmx U …`` printed, by channel."""
    values: dict[int, int] = {}
    for line in text.splitlines():
        address, *numbers = line.split()
        start = int(address.split(".")[1])
        values.update((start + k, int(value)) for k, value in enumerate(numbers))
    return values


def channels(text: str) -> list[tuple[str, str, int]]:
    """``list dmx fixture N``'s lines: address, function and value."""
    found = []
    for line in text.splitlines():
        address, *function, value = line.split()
        found.append((address, " ".join(function), int(value)))
    return found


def spot(*lines: str) -> OfflineShow:
    """A show with one universe and the lines given."""
    show = OfflineShow(new_show("Spot"))
    run(show, 'universe add 1 "Stage"', *lines)
    return show


# ------------------------------------------------------------------ a universe


def test_a_universe_is_the_frame_16_to_a_line(club: OfflineShow) -> None:
    run(club, "go 1", "go 5")  # the song's first cue and the chase
    frame = club.tick(1.5)
    text = run(club, "list dmx 1")[0]
    lines = text.splitlines()
    assert len(lines) == 32
    assert [line.split()[0] for line in lines[:3]] == ["1.1", "1.17", "1.33"]
    assert lines[-1].split()[0] == "1.497"
    assert all(len(line.split()) == 17 for line in lines)
    assert listed(text) == dict(enumerate(frame.universes[1], start=1))
    assert any(listed(text).values())


def test_one_channel_and_a_span_either_way(club: OfflineShow) -> None:
    run(club, "go 1")
    values = listed(run(club, "list dmx 1")[0])
    one = run(club, "list dmx 1 9")[0]
    assert one == f"1.9 {values[9]:>3}"
    span = run(club, "list dmx 1 20 thru 40")[0]
    assert run(club, "list dmx 1 40 thru 20")[0] == span
    assert [line.split()[0] for line in span.splitlines()] == ["1.20", "1.36"]
    assert listed(span) == {channel: values[channel] for channel in range(20, 41)}
    assert run(club, "list dmx 1 512")[0] == "1.512   0"


def test_the_columns_line_up_past_100() -> None:
    show = spot()
    lines = run(show, "list dmx 1 90 thru 130")[0].splitlines()
    assert [line[:6] for line in lines] == ["1.90  ", "1.106 ", "1.122 "]
    assert {len(line) for line in lines[:2]} == {5 + 16 * 4}


def test_a_universe_with_no_fixtures_is_dark(club: OfflineShow) -> None:
    run(club, 'universe add 2 "Balcony"', "go 1")
    text = run(club, "list dmx 2")[0]
    assert len(text.splitlines()) == 32
    assert set(listed(text).values()) == {0}
    assert run(club, "list universes")[0].splitlines()[1] == "    2  Balcony                0/512"


# ------------------------------------------------------------------ a fixture


def test_a_fixture_lists_its_channels_and_their_functions(club: OfflineShow) -> None:
    run(club, "sel fixture 101", "set intensity 50%", "set pan 10")
    found = channels(run(club, "list dmx fixture 101")[0])
    assert [(address, function) for address, function, _ in found] == [
        ("1.1", "pan"),
        ("1.2", "pan fine"),
        ("1.3", "tilt"),
        ("1.4", "tilt fine"),
        ("1.5", "red"),
        ("1.6", "green"),
        ("1.7", "blue"),
        ("1.8", "white"),
        ("1.9", "intensity"),
        ("1.10", "intensity fine"),
        ("1.11", "zoom"),
        ("1.12", "gobo1"),
        ("1.13", "shutter"),
        ("1.14", "unused"),
        ("1.15", "unused"),
        ("1.16", "unused"),
    ]
    values = listed(run(club, "list dmx 1 1 thru 16")[0])
    assert [value for _, _, value in found] == [values[channel] for channel in range(1, 17)]
    assert found[8][2] == 128  # intensity at half: 0x8000 coarse
    assert (found[0][2], found[1][2]) != (128, 0)  # pan moved off the centre, fine byte too


def test_the_lines_line_up() -> None:
    show = spot('fixture add 101 "Generic Spot 16ch" mode 16ch at 1.95')
    lines = run(show, "list dmx fixture 101")[0].splitlines()
    assert lines[0] == "1.95   pan            128"
    assert lines[5] == "1.100  green            0"
    assert lines[9] == "1.104  intensity fine   0"


def test_fine_bytes_where_the_profile_puts_them() -> None:
    """The MH-X25's pan and tilt fine bytes are not next to their coarse ones."""
    show = spot('fixture add 1 "Stairville MH-X25 LED Spot" mode 12-channel at 1.1')
    run(show, "sel fixture 1", "set pan 33.3", "set tilt -20")
    found = channels(run(show, "list dmx fixture 1")[0])
    assert [function for _, function, _ in found] == [
        "pan", "tilt", "pan fine", "tilt fine", "positionSpeed", "colorWheel", "shutter",
        "intensity", "gobo1", "gobo1Rotation", "control", "control",
    ]  # fmt: skip
    frame = show.tick(0.5)
    assert [value for _, _, value in found] == list(frame.universes[1][:12])
    assert found[2][2] != 0  # the fine bytes carry something
    assert found[3][2] != 0


def test_a_fixture_of_several_elements_names_each(club: OfflineShow) -> None:
    run(club, "sel fixture 301.2", "set color 1 0 0", "set intensity 100%")
    found = channels(run(club, "list dmx fixture 301")[0])
    assert len(found) == 36
    assert found[0][:2] == ("1.49", "Cell 1 red")
    assert found[3][:2] == ("1.52", "Cell 2 red")
    assert found[35][:2] == ("1.84", "Cell 12 blue")
    assert [value > 0 for _, _, value in found[:6]] == [False, False, False, True, False, False]


def test_an_unpatched_fixture_is_refused_in_words(club: OfflineShow) -> None:
    run(club, "fixture 101 patch none")
    reply = club.execute("list dmx fixture 101")
    assert (reply.ok, reply.text) == (False, "error: fixture 101 is not patched")


# ------------------------------------------------------------------ what goes out


def test_park_blackout_and_limits_are_in_it(club: OfflineShow) -> None:
    run(club, "park fixture 101 intensity 1", "park fixture 101 pan 0")
    found = channels(run(club, "list dmx fixture 101")[0])
    assert (found[8][2], found[9][2]) == (255, 255)  # parked at full
    run(club, "blackout on")
    found = channels(run(club, "list dmx fixture 101")[0])
    assert (found[8][2], found[9][2]) == (0, 0)  # blackout wins over a parked intensity
    assert (found[0][2], found[1][2]) == (128, 0)  # but not over a parked pan
    run(club, "blackout off", "sel fixture 301", "set intensity 100%", "set color 1 1 1")
    bar = [value for _, _, value in channels(run(club, "list dmx fixture 301")[0])]
    assert set(bar) == {128}  # the bar never runs above half
    wash = channels(run(club, "list dmx fixture 204")[0])
    assert [value for _, _, value in wash] == [0, 0, 0, 0]  # parked dark


def test_output_off_says_no_route_sends_it(club: OfflineShow) -> None:
    run(club, "output off")
    lines = run(club, "list dmx 1 1 thru 16")[0].splitlines()
    assert lines[0] == "output is off: no route sends these"
    assert len(lines) == 2
    assert run(club, "list dmx fixture 204")[0].splitlines()[0] == lines[0]
    run(club, "output on")
    assert len(run(club, "list dmx 1 1 thru 16")[0].splitlines()) == 1


# ------------------------------------------------------------------ list universes


def test_universes_count_channels_and_overlaps(club: OfflineShow) -> None:
    assert run(club, "list universes") == ["    1  Stage                 84/512"]
    run(club, "fixture 102 patch 1.10")  # over 101's last seven channels
    assert run(club, "list universes") == ["    1  Stage                 77/512  1 overlap"]
    run(club, "fixture 201 patch 1.12")  # over both: 1.33 to 1.36 go free
    assert run(club, "list universes") == ["    1  Stage                 73/512  3 overlaps"]
    run(club, "fixture 101 thru 301 patch none")
    assert run(club, "list universes") == ["    1  Stage                  0/512"]


# ------------------------------------------------------------------ the line


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("list dmx", "expected a universe number or fixture N"),
        ("list dmx 2", "no universe 2"),
        ("list dmx one", "expected a universe number or fixture N, got 'one'"),
        ("list dmx 1 0", "expected a channel from 1 to 512, got '0'"),
        ("list dmx 1 513", "expected a channel from 1 to 512, got '513'"),
        ("list dmx 1 1.5", "expected a channel from 1 to 512, got '1.5'"),
        ("list dmx 1 1 thru", "expected a channel from 1 to 512"),
        ("list dmx 1 1 thru 600", "expected a channel from 1 to 512, got '600'"),
        ("list dmx 1 1 2", "unexpected '2'"),
        ("list dmx fixture", "expected a fixture number"),
        ("list dmx fixture 999", "no fixture 999"),
        ("list dmx fixture 101 102", "unexpected '102'"),
    ],
)
def test_a_line_that_cannot_run_says_why(club: OfflineShow, line: str, error: str) -> None:
    reply = club.execute(line)
    assert (reply.ok, reply.text) == (False, f"error: {error}")


@pytest.mark.parametrize(
    ("line", "words", "values", "runnable"),
    [
        ("list d", ("dmx",), (), False),
        ("list dmx ", ("fixture",), ("a universe number",), False),
        ("list dmx 1 ", (), ("a channel from 1 to 512",), True),
        ("list dmx 1 20 ", ("thru",), (), True),
        ("list dmx 1 20 thru ", (), ("a channel from 1 to 512",), False),
        ("list dmx fixture ", (), ("a fixture number",), False),
    ],
)
def test_tab_offers_its_words(
    club: OfflineShow, line: str, words: tuple[str, ...], values: tuple[str, ...], runnable: bool
) -> None:
    found = club.expected(line)
    assert (found.words, found.values, found.runnable, found.error) == (
        words,
        values,
        runnable,
        None,
    )


def test_help_names_it(club: OfflineShow) -> None:
    assert "    list dmx U [A [thru B]] | list dmx fixture N" in run(club, "help")[0].splitlines()


# ------------------------------------------------------------------ live


def test_a_live_show_shows_what_the_line_before_did(club_show: Show) -> None:
    live = LiveShow(copy.deepcopy(club_show), output=False)
    assert run(live, "list dmx 1 1") == ["no frame yet: the engine has not run"]
    with live:
        for level, byte in (("100%", 255), ("50%", 128), ("0", 0)):
            run(live, "sel fixture 101", f"set intensity {level}")
            assert run(live, "list dmx 1 9") == [f"1.9 {byte:>3}"]
    assert run(live, "list dmx 1 9") == ["1.9   0"]  # stopped: its last frame


@pytest.mark.parametrize("backend", ["processes", "threads"])
def test_busk_run_prints_it(club_show: Show, tmp_path: Path, backend: str) -> None:
    """Under ``busk run``, with its engine in another process too: the
    console process has no frame until ``list dmx`` asks for them."""
    path = tmp_path / "club.show"
    doc = copy.deepcopy(club_show)
    for route in doc["output"]["routes"]:
        route["enabled"] = False  # sends nothing
    assert OfflineShow(doc, path=path).save().ok
    lines = [
        "list dmx 1 9",
        "sel fixture 101",
        "set intensity 100%",
        "list dmx fixture 101",
        "set intensity 50%",
        "list dmx 1 9 thru 10",
        "quit",
    ]
    result = subprocess.run(
        [
            sys.executable, "-m", "busk", "run", str(path),
            *(["--threads"] if backend == "threads" else []),
            "--state-dir", str(tmp_path / "state"),
        ],
        input="".join(f"{line}\n" for line in lines),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "XDG_STATE_HOME": str(tmp_path / "xdg")},
        check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    out = result.stdout.splitlines()
    assert "1.9   0" in out
    assert "1.9   intensity      255" in out
    assert "1.10  intensity fine 255" in out
    assert "1.9  128   0" in out
