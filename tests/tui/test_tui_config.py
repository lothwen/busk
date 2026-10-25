"""Options, ``config.toml`` and ``state.json`` (``busk_tui.config``)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from busk_tui import config
from busk_tui.config import Options, Settings


def test_the_defaults() -> None:
    options = config.parse_arguments(["show.show"])
    assert options == Options(show=Path("show.show"))


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
    assert config.read_state(blocked / "state.json") == {}
