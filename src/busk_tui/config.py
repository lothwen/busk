"""Options, ``config.toml`` and ``state.json`` (plan step 0.7).

``busk-tui SHOW`` runs ``busk run SHOW --frontend busk_tui.app:frontend``
with the ``busk run`` options it was given. busk hands the frontend only the
show, so the TUI's own options travel in the environment, as JSON in
``BUSK_TUI_OPTIONS`` (:func:`to_environment`, :func:`from_environment`).
``--standalone`` runs the show in the TUI's own process instead, and takes
``--no-output`` and ``--no-surfaces``, which ``busk run`` lacks.

``$XDG_CONFIG_HOME/busk-tui/config.toml`` (or ``--config FILE``) holds
defaults (``[defaults]``) and F2's quick lines (``[program] quick``); it is
only read. ``$XDG_STATE_HOME/busk-tui/state.json`` remembers
the last page and layout; a state file that cannot be read or written is
ignored.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Literal, cast

type Layout = Literal["A", "B", "C"]
type Colors = Literal["auto", "256", "16", "truecolor"]

ENVIRONMENT: Final = "BUSK_TUI_OPTIONS"
FRONTEND: Final = "busk_tui.app:frontend"
LAYOUTS: Final = ("A", "B", "C")
COLORS: Final = ("auto", "256", "16", "truecolor")
FADERS: Final = (4, 20)

_RUN_ONLY: Final = ("values", "script", "iface", "no_recover", "threads", "stats", "no_log")
"""The ``busk run`` options ``--standalone`` has no use for."""

QUICK: Final = (
    "set intensity spread 0 to 1",
    "set intensity spread 0 to 1 center",
    "set pan spread -90 to 90",
    "set tilt 45",
    "record cue 1",
    "clear",
)
"""F2's quick lines (spec §8.2 in busk's words, plan §3 17); ``[program]
quick`` in the config file replaces them. BLIND and HIGHLIGHT are toggles of
their own beside them."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Options:
    """What ``busk-tui`` was asked to do. ``layout``, ``faders`` and ``colors``
    are ``None`` when not given: the config file and the state decide."""

    show: Path | None = None  # None under busk run, which has it
    standalone: bool = False
    no_output: bool = False
    no_surfaces: bool = False
    state_dir: Path | None = None
    library: tuple[Path, ...] = ()
    run: tuple[str, ...] = ()  # the other busk run options, as given
    layout: Layout | None = None
    faders: int | None = None
    colors: Colors | None = None
    config: Path | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Settings:
    """The TUI's settings once the options, the config file and the state
    are put together; ``problems`` say what in the files was not used."""

    layout: Layout = "B"
    faders: int = 20
    colors: Colors = "auto"
    page: int = 1
    quick: tuple[str, ...] = QUICK
    problems: tuple[str, ...] = field(default=())


def parse_arguments(argv: Sequence[str] | None = None) -> Options:
    """``busk-tui``'s command line; exits 2 with a usage message when it is
    wrong, as argparse does."""
    from busk_tui import __version__

    parser = argparse.ArgumentParser(
        prog="busk-tui",
        description="Terminal UI for busk. Runs SHOW under busk run, or by itself "
        "with --standalone.",
    )
    parser.add_argument("--version", action="version", version=f"busk-tui {__version__}")
    parser.add_argument("show", type=Path, help="path to a .show or .json show file")
    tui = parser.add_argument_group("the TUI")
    tui.add_argument("--layout", choices=LAYOUTS, help="the F1 layout (default: the last one, B)")
    tui.add_argument("--faders", type=_faders, metavar="N", help="playbacks shown on F1, 4-20")
    tui.add_argument("--colors", choices=COLORS, help="the terminal's colours (default: auto)")
    tui.add_argument("--config", type=Path, metavar="FILE", help="the config file to read")
    host = parser.add_argument_group("the show")
    host.add_argument(
        "--standalone",
        action="store_true",
        help="run the show in this process, without busk run's watchdog, autosave "
        "and recovery: for development and rehearsal, not for a show",
    )
    host.add_argument("--no-output", action="store_true", help="(--standalone) open no route")
    host.add_argument(
        "--no-surfaces", action="store_true", help="(--standalone) open no control surface"
    )
    host.add_argument("--state-dir", type=Path, metavar="D", help="busk's state directory")
    host.add_argument(
        "--library",
        type=Path,
        action="append",
        default=[],
        metavar="D",
        help="another directory of fixture profiles (repeatable)",
    )
    run = parser.add_argument_group("busk run options, passed on (not with --standalone)")
    run.add_argument("--values", metavar="FILE")
    run.add_argument("--script", metavar="FILE")
    run.add_argument("--iface", metavar="IF")
    run.add_argument("--no-recover", action="store_true")
    run.add_argument("--threads", action="store_true")
    run.add_argument("--stats", metavar="FILE")
    run.add_argument("--no-log", action="store_true")
    args = parser.parse_args(argv)
    if args.standalone:
        given = [name for name in _RUN_ONLY if getattr(args, name) not in (None, False)]
        if given:
            flags = ", ".join("--" + name.replace("_", "-") for name in given)
            parser.error(f"--standalone runs no busk run: {flags} cannot be used with it")
    else:
        local = [flag for flag, on in (("--no-output", args.no_output),
                                       ("--no-surfaces", args.no_surfaces)) if on]  # fmt: skip
        if local:
            parser.error(f"{', '.join(local)} needs --standalone (busk run has no such option)")
    run_options: list[str] = []
    for name in _RUN_ONLY:
        value = getattr(args, name)
        flag = "--" + name.replace("_", "-")
        if value is True:
            run_options.append(flag)
        elif value not in (None, False):
            run_options += [flag, str(value)]
    return Options(
        show=args.show,
        standalone=args.standalone,
        no_output=args.no_output,
        no_surfaces=args.no_surfaces,
        state_dir=args.state_dir,
        library=tuple(args.library),
        run=tuple(run_options),
        layout=args.layout,
        faders=args.faders,
        colors=args.colors,
        config=args.config,
    )


def busk_run_command(options: Options) -> list[str]:
    """The ``busk run`` command line that runs the TUI as its frontend."""
    assert options.show is not None
    command = [sys.executable, "-m", "busk", "run", str(options.show), "--frontend", FRONTEND]
    if options.state_dir is not None:
        command += ["--state-dir", str(options.state_dir)]
    for directory in options.library:
        command += ["--library", str(directory)]
    return command + list(options.run)


def to_environment(options: Options) -> str:
    """The TUI's own options, for ``BUSK_TUI_OPTIONS``. Paths are made
    absolute: ``busk run`` keeps the working directory, but a restarted
    console must find the same files."""
    config = None if options.config is None else str(options.config.absolute())
    given = {"layout": options.layout, "faders": options.faders, "colors": options.colors}
    return json.dumps({**given, "config": config})


def from_environment(environ: dict[str, str] | None = None) -> Options:
    """The options of a TUI that ``busk run`` started; the defaults if
    ``BUSK_TUI_OPTIONS`` is missing or unreadable."""
    text = (os.environ if environ is None else environ).get(ENVIRONMENT, "")
    try:
        given = json.loads(text) if text else {}
    except ValueError:
        given = {}
    if not isinstance(given, dict):
        given = {}
    layout = given.get("layout")
    faders = given.get("faders")
    colors = given.get("colors")
    config = given.get("config")
    return Options(
        layout=layout if layout in LAYOUTS else None,
        faders=faders if isinstance(faders, int) and _in_range(faders) else None,
        colors=colors if colors in COLORS else None,
        config=Path(config) if isinstance(config, str) else None,
    )


def color_system(colors: Colors) -> str | None:
    """``TEXTUAL_COLOR_SYSTEM`` for ``--colors`` (``None``: Textual decides)."""
    return {"auto": None, "256": "256", "16": "standard", "truecolor": "truecolor"}[colors]


# ------------------------------------------------------------------ files


def config_path(environ: dict[str, str] | None = None) -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config", environ) / "busk-tui" / "config.toml"


def state_path(environ: dict[str, str] | None = None) -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state", environ) / "busk-tui" / "state.json"


def settings(options: Options, *, config: Path, state: Path) -> Settings:
    """The settings: the options first, then the state (the last layout and
    page), then the config file's ``[defaults]``, then the built-in ones."""
    problems: list[str] = []
    defaults: dict[str, Any] = {}
    program: dict[str, Any] = {}
    try:
        with config.open("rb") as file:
            document = tomllib.load(file)
        table = document.get("defaults", {})
        if isinstance(table, dict):
            defaults = table
        else:
            problems.append(f"{config}: [defaults] is not a table; not used")
        table = document.get("program", {})
        if isinstance(table, dict):
            program = table
        else:
            problems.append(f"{config}: [program] is not a table; not used")
    except FileNotFoundError:
        pass
    except (OSError, tomllib.TOMLDecodeError) as exc:
        problems.append(f"{config}: {exc}; using the defaults")
    remembered = read_state(state)
    chosen = Settings()
    quick = program.get("quick")
    if isinstance(quick, list) and all(isinstance(line, str) and line.strip() for line in quick):
        chosen = replace(chosen, quick=tuple(line.strip() for line in quick))
    elif quick is not None:
        problems.append(f"{config}: quick must be a list of console lines; not {quick!r}")
    layout = defaults.get("layout")
    if layout in LAYOUTS:
        chosen = replace(chosen, layout=cast(Layout, layout))
    elif layout is not None:
        problems.append(f"{config}: layout must be one of A, B, C; not {layout!r}")
    faders = defaults.get("faders")
    if isinstance(faders, int) and _in_range(faders):
        chosen = replace(chosen, faders=faders)
    elif faders is not None:
        problems.append(f"{config}: faders must be a whole number 4-20; not {faders!r}")
    colors = defaults.get("colors")
    if colors in COLORS:
        chosen = replace(chosen, colors=cast(Colors, colors))
    elif colors is not None:
        problems.append(f"{config}: colors must be one of {', '.join(COLORS)}; not {colors!r}")
    if remembered.get("layout") in LAYOUTS:
        chosen = replace(chosen, layout=cast(Layout, remembered["layout"]))
    page = remembered.get("page")
    if isinstance(page, int) and 1 <= page <= 9:
        chosen = replace(chosen, page=page)
    if options.layout is not None:
        chosen = replace(chosen, layout=options.layout)
    if options.faders is not None:
        chosen = replace(chosen, faders=options.faders)
    if options.colors is not None:
        chosen = replace(chosen, colors=options.colors)
    return replace(chosen, problems=tuple(problems))


def read_state(path: Path) -> dict[str, Any]:
    """The remembered state; empty if it cannot be read."""
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def write_state(path: Path, *, page: int, layout: Layout) -> bool:
    """Remember the page and layout; ``False`` if it cannot be written."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"page": page, "layout": layout}), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        return False
    return True


def _xdg(variable: str, fallback: str, environ: dict[str, str] | None) -> Path:
    environment = os.environ if environ is None else environ
    value = environment.get(variable, "")
    return Path(value) if os.path.isabs(value) else Path.home() / fallback


def _in_range(faders: int) -> bool:
    return FADERS[0] <= faders <= FADERS[1]


def _faders(text: str) -> int:
    try:
        faders = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {text!r}") from None
    if not _in_range(faders):
        raise argparse.ArgumentTypeError(f"must be 4-20: {text!r}")
    return faders
