"""Options, ``config.toml`` and ``state.json`` (``busk_tui.config``)."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from busk_tui import config
from busk_tui.config import Options, Settings


def test_the_defaults() -> None:
    options = config.parse_arguments(["show.show"])
    assert options == Options(show=Path("show.show"))


def test_without_a_show_the_launcher_chooses_it_with_the_options_given() -> None:
    assert config.parse_arguments([]) == Options()
    options = config.parse_arguments(["--layout", "A", "--threads", "--script", "s.busk"])
    assert options.show is None
    assert (options.layout, options.run, options.first) == (
        "A",
        ("--threads",),
        ("--script", "s.busk"),
    )
    assert config.parse_arguments(["--standalone", "--no-output"]).show is None


def test_busk_run_gets_the_show_and_its_own_options() -> None:
    options = config.parse_arguments(
        ["s.show", "--state-dir", "st", "--library", "a", "--library", "b", "--threads",
         "--no-log", "--iface", "lo", "--values", "v.json", "--script", "x.busk", "--stats",
         "stats.jsonl", "--no-recover", "--layout", "A"]
    )  # fmt: skip
    command = config.busk_run_command(options)
    assert command[:7] == [sys.executable, "-m", "busk", "run", "s.show", "--frontend",
                           "busk_tui.app:frontend"]  # fmt: skip
    rest = command[7:]
    assert rest[:6] == ["--state-dir", "st", "--library", "a", "--library", "b"]
    assert set(rest[6:]) == {
        "--values", "v.json", "--script", "x.busk", "--iface", "lo", "--no-recover", "--threads",
        "--stats", "stats.jsonl", "--no-log",
    }  # fmt: skip
    assert "--layout" not in command  # the TUI's own: in the environment


def test_a_show_opened_from_the_tui_runs_without_the_given_shows_values_and_script() -> None:
    options = config.parse_arguments(
        ["s.show", "--state-dir", "st", "--library", "a", "--threads", "--values", "v.json",
         "--script", "x.busk", "--no-log"]
    )  # fmt: skip
    assert options.run == ("--threads", "--no-log")
    assert options.first == ("--values", "v.json", "--script", "x.busk")
    command = config.busk_run_command(options, Path("/s/b.show"))
    assert command == [sys.executable, "-m", "busk", "run", "/s/b.show", "--frontend",
                       "busk_tui.app:frontend", "--state-dir", "st", "--library", "a",
                       "--threads", "--no-log"]  # fmt: skip


def test_busk_new_writes_the_new_show() -> None:
    command = config.busk_new_command(Path("/s/new.show"), "-Late Night", None)
    assert command == [sys.executable, "-m", "busk", "new", "/s/new.show", "--title=-Late Night"]
    with_state = config.busk_new_command(Path("/s/new.show"), "N", Path("/st"))
    assert with_state[-2:] == ["--state-dir", "/st"]


def test_the_tuis_options_travel_in_the_environment(tmp_path: Path) -> None:
    options = config.parse_arguments(
        ["s.show", "--layout", "C", "--faders", "12", "--colors", "16", "--config", "c.toml"]
    )
    text = config.to_environment(options)
    back = config.from_environment({config.ENVIRONMENT: text})
    assert (back.layout, back.faders, back.colors) == ("C", 12, "16")
    assert back.config is not None
    assert back.config.is_absolute()
    assert back.config.name == "c.toml"
    assert back.state_dir is None
    with_state = config.parse_arguments(["s.show", "--state-dir", "st"])
    back = config.from_environment({config.ENVIRONMENT: config.to_environment(with_state)})
    assert back.state_dir == Path("st").absolute()  # busk new's, for the installation's CID


def test_unreadable_options_in_the_environment_are_the_defaults() -> None:
    for text in ("", "not json", "[1]", '{"layout": "Z", "faders": 99, "colors": 7}'):
        assert config.from_environment({config.ENVIRONMENT: text}) == Options()
    assert config.from_environment({}) == Options()


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["s", "--standalone", "--threads"], "--standalone runs no busk run: --threads"),
        (["s", "--standalone", "--no-log", "--iface", "x"], "--iface, --no-log"),
        (["s", "--no-output"], "--no-output needs --standalone"),
        (["s", "--no-surfaces"], "--no-surfaces needs --standalone"),
        (["s", "--faders", "3"], "must be 4-20"),
        (["s", "--layout", "D"], "invalid choice"),
    ],
)
def test_wrong_options_exit_2(
    argv: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stopped:
        config.parse_arguments(argv)
    assert stopped.value.code == 2
    assert message in capsys.readouterr().err


def test_standalone_takes_its_own_options() -> None:
    options = config.parse_arguments(
        ["s", "--standalone", "--no-output", "--no-surfaces", "--state-dir", "d", "--library", "l"]
    )
    assert options.standalone
    assert options.no_output
    assert options.no_surfaces
    assert options.state_dir == Path("d")
    assert options.library == (Path("l"),)
    assert options.run == ()


def test_the_colour_systems() -> None:
    assert config.color_system("auto") is None
    assert config.color_system("16") == "standard"
    assert config.color_system("256") == "256"
    assert config.color_system("truecolor") == "truecolor"


def test_the_files_follow_xdg() -> None:
    environ = {"XDG_CONFIG_HOME": "/c", "XDG_STATE_HOME": "/s"}
    assert config.config_path(environ) == Path("/c/busk-tui/config.toml")
    assert config.state_path(environ) == Path("/s/busk-tui/state.json")
    assert config.state_path({"XDG_STATE_HOME": "relative"}) == (
        Path.home() / ".local/state/busk-tui/state.json"
    )


def test_settings_without_files_are_the_defaults(tmp_path: Path) -> None:
    chosen = config.settings(Options(), config=tmp_path / "none.toml", state=tmp_path / "none")
    assert chosen == Settings()


def test_the_config_files_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[defaults]\nlayout = "A"\nfaders = 16\ncolors = "256"\n')
    chosen = config.settings(Options(), config=path, state=tmp_path / "none")
    assert (chosen.layout, chosen.faders, chosen.colors, chosen.problems) == ("A", 16, "256", ())


def test_wrong_values_in_the_config_file_are_said_and_not_used(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[defaults]\nlayout = "Z"\nfaders = 30\ncolors = "many"\n')
    chosen = config.settings(Options(), config=path, state=tmp_path / "none")
    assert (chosen.layout, chosen.faders, chosen.colors) == ("B", 20, "auto")
    assert len(chosen.problems) == 3


def test_the_quick_lines_come_from_the_config_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[program]\nquick = ["sel group 1", " clear "]\n')
    chosen = config.settings(Options(), config=path, state=tmp_path / "none")
    assert (chosen.quick, chosen.problems) == (("sel group 1", "clear"), ())
    assert Settings().quick == config.QUICK


@pytest.mark.parametrize(
    "table", ['[program]\nquick = "clear"\n', '[program]\nquick = ["clear", ""]\n', "program = 1\n"]
)
def test_wrong_quick_lines_are_said_and_not_used(tmp_path: Path, table: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(table)
    chosen = config.settings(Options(), config=path, state=tmp_path / "none")
    assert chosen.quick == config.QUICK
    (problem,) = chosen.problems
    assert problem.startswith(f"{path}: ")


def test_a_bad_config_file_gives_the_defaults_and_says_why(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[defaults\nlayout = ")
    chosen = config.settings(Options(), config=path, state=tmp_path / "none")
    assert chosen.layout == "B"
    (problem,) = chosen.problems
    assert problem.startswith(f"{path}: ")
    assert problem.endswith("; using the defaults")


def test_options_then_state_then_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[defaults]\nlayout = "A"\nfaders = 16\n')
    state = tmp_path / "state.json"
    assert config.write_state(state, page=7, layout="C")
    chosen = config.settings(Options(), config=path, state=state)
    assert (chosen.layout, chosen.page, chosen.faders) == ("C", 7, 16)
    given = config.settings(Options(layout="B", faders=5), config=path, state=state)
    assert (given.layout, given.page, given.faders) == ("B", 7, 5)


def test_the_state_round_trip(tmp_path: Path) -> None:
    state = tmp_path / "deep" / "state.json"
    assert config.write_state(state, page=3, layout="A")
    assert config.read_state(state) == {"page": 3, "layout": "A"}


def test_a_state_that_cannot_be_used_is_ignored(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    state.write_text("{not json")
    assert config.read_state(state) == {}
    state.write_text(json.dumps({"page": 99, "layout": "Q"}))
    assert config.settings(Options(), config=tmp_path / "c", state=state) == Settings()


def test_an_unwritable_state_directory_is_ignored(tmp_path: Path) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("")
    assert not config.write_state(blocked / "state.json", page=1, layout="B")
    assert not config.remember_show(blocked / "state.json", Path("/s/a.show"), "A")
    assert config.read_state(blocked / "state.json") == {}


OPENED = datetime(2026, 11, 20, 21, 47, 5, tzinfo=UTC)


def test_a_show_opened_goes_first_in_the_recent_shows(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    assert config.remember_show(state, Path("/s/club.show"), "Club Night", OPENED)
    later = OPENED + timedelta(minutes=5)
    assert config.remember_show(state, Path("/s/fest.show"), "Festival", later)
    (fest, club) = config.read_state(state)["recent"]
    assert fest == {
        "path": "/s/fest.show",
        "title": "Festival",
        "opened": later.astimezone().isoformat(timespec="seconds"),
    }
    assert datetime.fromisoformat(fest["opened"]) == later
    assert (club["path"], club["title"]) == ("/s/club.show", "Club Night")


def test_a_show_opened_again_moves_up_and_is_listed_once(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    for name in ("a", "b", "c"):
        config.remember_show(state, Path(f"/s/{name}.show"), name.upper(), OPENED)
    config.remember_show(state, Path("/s/a.show"), "A renamed", OPENED)
    recent = config.read_state(state)["recent"]
    assert [(e["path"], e["title"]) for e in recent] == [
        ("/s/a.show", "A renamed"),
        ("/s/c.show", "C"),
        ("/s/b.show", "B"),
    ]


def test_the_recent_shows_keep_the_newest_ten(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    for number in range(12):
        config.remember_show(state, Path(f"/s/{number}.show"), str(number), OPENED)
    recent = config.read_state(state)["recent"]
    assert [e["path"] for e in recent] == [f"/s/{n}.show" for n in range(11, 1, -1)]
    assert len(recent) == config.RECENT


def test_the_page_and_the_recent_shows_keep_each_other(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    assert config.write_state(state, page=4, layout="C")
    assert config.remember_show(state, Path("/s/club.show"), "Club Night", OPENED)
    assert config.write_state(state, page=6, layout="A")
    remembered = config.read_state(state)
    assert (remembered["page"], remembered["layout"]) == (6, "A")
    assert [e["path"] for e in remembered["recent"]] == ["/s/club.show"]
    assert config.settings(Options(), config=tmp_path / "c", state=state).page == 6


def test_an_old_state_file_reads_and_a_bad_recent_entry_is_dropped(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"page": 2, "layout": "B"}))  # before the recent shows
    assert config.settings(Options(), config=tmp_path / "c", state=state).page == 2
    assert config.remember_show(state, Path("/s/a.show"), "A", OPENED)
    assert config.read_state(state)["page"] == 2
    bad = [{"path": "/s/b.show"}, "c.show", {"path": 1, "title": "D", "opened": "x"}]
    state.write_text(json.dumps({"page": 2, "recent": bad}))
    assert config.remember_show(state, Path("/s/a.show"), "A", OPENED)
    assert [e["path"] for e in config.read_state(state)["recent"]] == ["/s/a.show"]


def test_the_recent_shows_read_back_newest_first(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    assert config.recent_shows(state) == ()
    config.remember_show(state, Path("/s/a.show"), "A", OPENED)
    config.remember_show(state, Path("/s/b.show"), "B", OPENED)
    assert config.recent_shows(state) == (
        config.RecentShow(Path("/s/b.show"), "B"),
        config.RecentShow(Path("/s/a.show"), "A"),
    )
