"""``busk-tui``'s entry points (plan step 0.1).

* :func:`main` is the ``busk-tui`` command. It checks the options, then
  replaces itself with ``python -m busk run SHOW --frontend
  busk_tui.app:frontend`` and the ``busk run`` options it was given, with the
  TUI's own options in ``BUSK_TUI_OPTIONS``. With ``--standalone`` it runs
  the show in this process instead, and stops it when the TUI ends.
* :func:`frontend` is what ``busk run`` calls, on its console process's main
  thread, with the run's show, already started. The run ends when it returns.

This module imports neither busk nor Textual at the top: the bridge is the
only module that imports busk, and Textual must be imported after
``TEXTUAL_COLOR_SYSTEM`` is set (``--colors``).
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Sequence

from busk_tui import config


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``busk-tui`` with ``argv`` (default: ``sys.argv[1:]``); return the
    exit code. Under ``busk run`` it does not return: busk run's code is the
    command's."""
    options = config.parse_arguments(argv)
    settings = config.settings(
        options, config=options.config or config.config_path(), state=config.state_path()
    )
    system = config.color_system(settings.colors)
    if system is not None:
        os.environ["TEXTUAL_COLOR_SYSTEM"] = system
    if options.standalone:
        return _standalone(options, settings)
    command, environment = run_command(options)
    sys.stdout.flush()
    sys.stderr.flush()
    os.execve(command[0], command, environment)  # replaces this process
    return 0  # not reached


def run_command(options: config.Options) -> tuple[list[str], dict[str, str]]:
    """The ``busk run`` command line and environment :func:`main` runs."""
    environment = {**os.environ, config.ENVIRONMENT: config.to_environment(options)}
    return config.busk_run_command(options), environment


def frontend(show: object) -> None:
    """Run the TUI on ``busk run``'s show (``busk run --frontend
    busk_tui.app:frontend``). It neither starts nor stops the show: the run
    ends when this returns. An exception is a console crash, after which
    ``busk run`` starts a new console that calls this again."""
    from busk_tui.bridge import Bridge
    from busk_tui.shell import BuskApp

    _debug_log()
    options = config.from_environment()
    settings = config.settings(
        options, config=options.config or config.config_path(), state=config.state_path()
    )
    bridge = Bridge.attached(show)
    app = BuskApp(bridge, settings)
    try:
        app.run()
    finally:
        bridge.stop()
        config.write_state(config.state_path(), page=app.page, layout=app.view.layout)


def _standalone(options: config.Options, settings: config.Settings) -> int:
    from busk_tui.bridge import Bridge
    from busk_tui.model import ShowLoadFailed

    assert options.show is not None
    try:
        bridge = Bridge.standalone(
            options.show,
            library=options.library,
            output=not options.no_output,
            surfaces=not options.no_surfaces,
            state_dir=options.state_dir,
        )
    except ShowLoadFailed as exc:
        for message in exc.messages:
            print(f"busk-tui: {message}", file=sys.stderr)
        return 2
    from busk_tui.shell import BuskApp

    _debug_log()
    app = BuskApp(bridge, settings, standalone=True)
    try:
        code = app.run()
    finally:
        bridge.stop()  # the show stops whatever ended the app: its output is terminated
        config.write_state(config.state_path(), page=app.page, layout=app.view.layout)
    return 0 if code is None else code


def _debug_log() -> None:
    """Tracebacks the TUI catches go to ``$XDG_STATE_HOME/busk-tui/debug.log``
    (nowhere, if it cannot be written)."""
    path = config.state_path().with_name("debug.log")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8", delay=True)
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger = logging.getLogger("busk_tui")
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    logger.propagate = False
