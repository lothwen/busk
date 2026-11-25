"""busk's banner (:mod:`busk.banner`): shown while ``busk run`` starts for
its interactive prompt (:mod:`busk.launch`), animated on a colour terminal
on a thread of its own until the first line busk prints, and given to
frontends as frames (``busk.banner_frames``)."""

from __future__ import annotations

import io
import math
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

import busk
import busk.cli
from busk import banner, launch

ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
REST = banner.render_frame() + "\n\x1b[?25h"
"""The end of an animation: the last frame, and the cursor shown again."""


class Terminal(io.StringIO):
    """A stream that says it is a terminal."""

    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def colour_terminal(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A wide 24-bit terminal, not under CI, whatever runs the tests; and
    no stream left held after each test."""
    for name in ("NO_COLOR", "CI", "BUSK_NO_ANIM"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setattr(banner, "_playing", None)
    yield
    assert not isinstance(sys.stdout, banner._Held)
    assert not isinstance(sys.stderr, banner._Held)


def plain(text: str) -> str:
    return ESCAPE.sub("", text)


# ------------------------------------------------------------- at rest at once


def test_a_stream_that_is_not_a_terminal_gets_the_banner_at_rest_without_colour() -> None:
    out = io.StringIO()
    banner.play_banner(out)()
    text = out.getvalue()
    assert "\x1b" not in text
    lines = text.splitlines()
    assert len(lines) == banner.HEIGHT
    assert lines[-1].endswith("live     lighting console engine")
    assert text == banner.render_frame(color=None) + "\n"


def test_a_terminal_with_no_animation_gets_the_last_frame_in_colour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BUSK_NO_ANIM", "1")
    out = Terminal()
    finish = banner.play_banner(out)
    assert out.getvalue() == banner.render_frame() + "\n"  # before the function
    assert "\x1b[38;2;" in out.getvalue()
    assert banner.child_hold() == ((), None)  # nothing for a child to wait for
    finish()


def test_without_colorterm_it_uses_xterm_256_colours(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.delenv("COLORTERM")
    out = Terminal()
    banner.play_banner(out)()
    assert "\x1b[38;5;" in out.getvalue()
    assert "\x1b[38;2;" not in out.getvalue()


def test_no_color_gives_plain_characters_on_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    out = Terminal()
    banner.play_banner(out)()
    assert out.getvalue() == banner.render_frame(color=None) + "\n"


def test_a_narrow_terminal_gets_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", str(banner.WIDTH - 1))
    out = Terminal()
    banner.play_banner(out)()
    assert plain(out.getvalue()) == "busk · lighting console engine\n"


def test_an_encoding_without_block_characters_gets_a_plain_line() -> None:
    out = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    banner.play_banner(out)()
    out.seek(0)
    assert out.read() == "busk - lighting console engine\n"


# ------------------------------------------------------------- animated


def wait_for(test: Callable[[], object]) -> None:
    deadline = time.monotonic() + 5
    while not test():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_the_first_write_brings_it_to_rest_at_once_and_goes_on() -> None:
    out = Terminal()
    started = time.monotonic()
    finish = banner.play_banner(out)
    wait_for(lambda: out.getvalue().count(f"\x1b[{banner.HEIGHT}F") >= 2)  # a few frames in
    assert not out.getvalue().endswith(REST)
    print("busk console: …")  # held until the banner is at rest
    assert out.getvalue().endswith(REST)
    assert time.monotonic() - started < 1.5  # it did not play to its end: it came to rest
    assert out.getvalue().startswith("\x1b[?25l" + banner.render_frame(0.0) + "\n")
    finish()


def test_stderr_brings_it_to_rest_too_and_finish_alone_does() -> None:
    out = Terminal()
    finish = banner.play_banner(out)
    print("a warning", file=sys.stderr)
    assert out.getvalue().endswith(REST)
    finish()

    out = Terminal()
    finish = banner.play_banner(out)
    finish()  # nothing printed: the streams go back all the same
    assert out.getvalue().endswith(REST)


def test_left_alone_it_plays_to_its_end(monkeypatch: pytest.MonkeyPatch) -> None:
    now = iter(range(1000))
    monkeypatch.setattr(
        banner, "time", SimpleNamespace(monotonic=lambda: next(now) * 0.5)
    )  # half a second a frame
    out = Terminal()
    finish = banner.play_banner(out)
    wait_for(lambda: out.getvalue().endswith(REST))
    frames = math.ceil(banner.DURATION / 0.5)  # at 0.5 s, 1 s, 1.5 s and the end
    assert out.getvalue().count(f"\x1b[{banner.HEIGHT}F") == frames - 1  # each over the last
    finish()  # at rest already: it returns at once


CHILD = """
import sys, time
sys.path.insert(0, {src!r})
from busk.banner import hold_output
hold_output()
started = time.monotonic()
print("child", flush=True)
print(f"{{time.monotonic() - started:.3f}}", flush=True)
"""


def child(src: Path) -> subprocess.Popen[str]:
    held, environment = banner.child_hold()
    return subprocess.Popen(
        [sys.executable, "-c", CHILD.format(src=str(src))],
        pass_fds=held,
        env=environment,
        stdout=subprocess.PIPE,
        text=True,
    )


def test_a_child_that_holds_its_output_brings_it_to_rest_before_its_first_line() -> None:
    src = Path(busk.__file__).parents[1]
    out = Terminal()
    finish = banner.play_banner(out)
    try:
        held, environment = banner.child_hold()
        assert len(held) == 2
        assert environment is not None
        assert environment["BUSK_BANNER"] == f"{held[0]},{held[1]}"
        assert "BUSK_BANNER" not in os.environ  # only for the children given the pipes
        process = child(src)
        assert process.stdout is not None
        assert process.stdout.readline() == "child\n"
        assert out.getvalue().endswith(REST)  # at rest before the child's line came
        process.wait(5)

        late = child(src)  # after it rested: no wait
        output, _ = late.communicate(timeout=5)
        assert float(output.split()[1]) < 0.5
    finally:
        finish()


def test_a_child_without_the_pipes_holds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BUSK_BANNER", raising=False)
    out = sys.stdout
    banner.hold_output()
    assert sys.stdout is out


def test_the_frames_play_the_animation_and_end_at_rest() -> None:
    frames = busk.banner_frames()
    assert len(frames) == math.ceil(banner.DURATION * 30) + 1
    assert frames[0] == banner.render_frame(0.0)
    assert frames[15] == banner.render_frame(0.5)
    assert frames[-1] == banner.render_frame()
    for frame in (frames[0], frames[-1]):
        lines = plain(frame).split("\n")
        assert len(lines) == banner.HEIGHT
        assert {len(line) for line in lines} == {banner.WIDTH}
    assert len(busk.banner_frames(10)) == math.ceil(banner.DURATION * 10) + 1


@pytest.mark.parametrize("rate", [0, -30])
def test_the_frames_need_a_positive_rate(rate: float) -> None:
    with pytest.raises(ValueError, match="rate must be positive"):
        busk.banner_frames(rate)


# ------------------------------------------------------------------ busk run


def on_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """stdin and stdout are terminals (in the test: pytest's capture sets
    them again after the fixtures)."""
    monkeypatch.setattr("sys.stdin", Terminal())
    monkeypatch.setattr("sys.stdout", Terminal())


@pytest.mark.parametrize(
    ("argv", "plays"),
    [
        (["run", "club.show"], True),
        (["run", "club.show", "--threads", "--iface", "eth1"], True),
        (["run", "club.show", "--script", "warm-up.txt"], True),
        (["run", "club.show", "--frontend", "busk_tui.app:frontend"], False),
        (["run", "club.show", "--front", "busk_tui.app:frontend"], False),  # as argparse reads it
        (["run", "club.show", "--no-console"], False),
        (["run", "club.show", "--duration", "5"], False),
        (["run", "club.show", "--duration", "-5"], False),  # refused
        (["run", "club.show", "--bogus"], False),
        (["run", "club.show", "-h"], False),
        (["run"], False),
        (["--version", "run", "club.show"], False),
        (["validate", "club.show"], False),
        ([], False),
    ],
)
def test_the_banner_plays_for_busk_run_at_a_prompt_alone(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], plays: bool
) -> None:
    on_terminal(monkeypatch)
    assert launch.prompts(argv) is plays


def test_not_on_a_terminal_it_does_not_play(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", Terminal())
    monkeypatch.setattr("sys.stdout", io.StringIO())  # piped
    assert not launch.prompts(["run", "club.show"])
    monkeypatch.setattr("sys.stdin", io.StringIO())
    monkeypatch.setattr("sys.stdout", Terminal())
    assert not launch.prompts(["run", "club.show"])


def test_busk_runs_while_the_banner_plays_and_ends_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(launch, "prompts", lambda argv: True)
    monkeypatch.setattr(launch, "play_banner", lambda: lambda: calls.append("rest"))
    monkeypatch.setattr(busk.cli, "main", lambda argv: calls.append(f"run {argv}") or 0)
    assert launch.main(["run", "club.show"]) == 0
    assert calls == ["run ['run', 'club.show']", "rest"]  # it did not wait for the banner


def test_ctrl_c_before_the_run_starts_ends_it_with_130(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def interrupted(argv: list[str]) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(launch, "prompts", lambda argv: True)
    monkeypatch.setattr(launch, "play_banner", lambda: lambda: calls.append("rest"))
    monkeypatch.setattr(busk.cli, "main", interrupted)
    assert launch.main(["run", "club.show"]) == 130
    assert calls == ["rest"]
    monkeypatch.setattr(launch, "prompts", lambda argv: False)  # no banner: as Python does
    with pytest.raises(KeyboardInterrupt):
        launch.main(["validate", "club.show"])


def test_without_a_prompt_busk_starts_no_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    played: list[bool] = []
    monkeypatch.setattr(launch, "play_banner", lambda: played.append(True))
    monkeypatch.setattr(busk.cli, "main", lambda argv: 0)
    assert launch.main(["validate", "club.show"]) == 0
    assert not played
