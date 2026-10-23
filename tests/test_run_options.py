"""``RunOptions``: the options of ``busk run``, typed (phase-8-plan step 9).

The parser and the dataclass describe the same options twice, so these
tests tie them together: one field per option, with the option's default,
and each option of a full command line lands in its field.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from busk.cli import _parser
from busk.process.options import RunOptions


def parse(*argv: str) -> RunOptions:
    """The options of ``busk run argv…``."""
    return RunOptions.from_arguments(_parser().parse_args(["run", *argv]))


def test_there_is_one_field_per_option() -> None:
    parsed = vars(_parser().parse_args(["run", "x.show"]))
    del parsed["command"]
    assert {field.name for field in dataclasses.fields(RunOptions)} == set(parsed)


def test_the_defaults_are_the_parsers() -> None:
    assert parse("x.show") == RunOptions(show=Path("x.show"))


def test_every_option_lands_in_its_field() -> None:
    options = parse(
        "x.show",
        "--values", "v.json",
        "--duration", "2.5",
        "--console",
        "--script", "s.busk",
        "--no-console",
        "--iface", "lo",
        "--state-dir", "state",
        "--library", "a",
        "--library", "b",
        "--no-recover",
        "--threads",
        "--stats", "stats.jsonl",
        "--no-log",
        "--frontend", "tui:run",
    )  # fmt: skip
    assert options == RunOptions(
        show=Path("x.show"),
        values=Path("v.json"),
        duration=2.5,
        console=True,
        script=Path("s.busk"),
        no_console=True,
        iface="lo",
        state_dir=Path("state"),
        library=(Path("a"), Path("b")),
        no_recover=True,
        threads=True,
        stats=Path("stats.jsonl"),
        no_log=True,
        frontend="tui:run",
    )


def test_options_are_frozen() -> None:
    options = RunOptions(show=Path("x.show"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        options.duration = 1.0  # type: ignore[misc]
