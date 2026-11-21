"""``busk-tui``'s entry points (plan step 0.1).

* :func:`main` is the ``busk-tui`` command. It checks the options, then
  runs ``python -m busk run SHOW --frontend busk_tui.app:frontend`` and the
  ``busk run`` options it was given, with the TUI's own options in
  ``BUSK_TUI_OPTIONS``, and stays as its parent (:mod:`busk_tui.parent`): when
  the TUI opens another show, the run ends and the parent starts the next.
  With ``--standalone`` it runs the show in this process instead, and stops
  it when the TUI ends, or starts the next show the TUI opens. Given no
  show, it runs the launcher first (:mod:`busk_tui.launcher`), and the show
  chosen there is the show given.
* :func:`frontend` is what ``busk run`` calls, on its console process's main
  thread, with the run's show, already started. The run ends when it returns,
  after it has handed the next show, if any, to the parent.

This module imports neither busk nor Textual at the top: the bridge is the
only module that imports busk, and Textual must be imported after
``TEXTUAL_COLOR_SYSTEM`` is set (``--colors``).
"""

from __future__ import annotations

import functools
import logging
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from busk_tui import config, parent

if TYPE_CHECKING:
    from busk_tui.model import Recovery


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``busk-tui`` with ``argv`` (default: ``sys.argv[1:]``); return the
    exit code: the last ``busk run``'s (:func:`busk_tui.parent.run`)."""
    options = config.parse_arguments(argv)
    settings = config.settings(
        options, config=options.config or config.config_path(), state=config.state_path()
    )
    system = config.color_system(settings.colors)
    if system is not None:
        os.environ["TEXTUAL_COLOR_SYSTEM"] = system
    if options.show is None:  # the launcher chooses it (file-menu plan call 15)
        from busk_tui.bridge import show_read
        from busk_tui.launcher import Launcher

        _debug_log()
        launcher = Launcher(show_read, recovery=recovery(options), state_dir=options.state_dir)
        show = launcher.run()
        if show is None:  # quit, or it crashed
            return launcher.return_code or 0
        options = replace(options, show=show)
    if options.standalone:
        return _standalone(options, settings)
    command, environment = run_command(options)
    sys.stdout.flush()
    sys.stderr.flush()
    return parent.run(command, lambda show: config.busk_run_command(options, show), environment)


def run_command(options: config.Options) -> tuple[list[str], dict[str, str]]:
    """The ``busk run`` command line and environment of the show given."""
    environment = {**os.environ, config.ENVIRONMENT: config.to_environment(options)}
    return config.busk_run_command(options), environment


def frontend(show: object) -> None:
    """Run the TUI on ``busk run``'s show (``busk run --frontend
    busk_tui.app:frontend``). It neither starts nor stops the show: the run
    ends when this returns, and the parent starts the show the TUI opened, if
    it opened one. An exception is a console crash, after which ``busk run``
    starts a new console that calls this again."""
    from busk_tui.bridge import Bridge
    from busk_tui.shell import BuskApp

    _debug_log()
    options = config.from_environment()
    settings = config.settings(
        options, config=options.config or config.config_path(), state=config.state_path()
    )
    bridge = Bridge.attached(show)
    opens = parent.NEXT in os.environ  # busk-tui is the parent
    app = BuskApp(
        bridge, settings, opens=opens, state_dir=options.state_dir, recovery=recovery(options)
    )
    try:
        app.run()
    finally:
        bridge.stop()
        config.write_state(config.state_path(), page=app.page, layout=app.view.layout)
    if app.next_show is not None and not parent.hand_off(app.next_show):
        print(f"busk-tui: cannot hand {app.next_show} over to open it", file=sys.stderr)


def recovery(options: config.Options) -> Callable[[Path], Recovery | None] | None:
    """busk's reading of what ``busk run`` would recover of a show, with the
    state directory given, for the recent shows' marks (file-menu plan call
    24); ``None`` when the shows opened recover nothing (``--no-recover``,
    ``--standalone``)."""
    if not options.recovers:
        return None
    from busk_tui.bridge import recovery_read

    return functools.partial(recovery_read, state_dir=options.state_dir)


def _standalone(options: config.Options, settings: config.Settings) -> int:
    """Run the show given in this process, then each show the TUI opens
    (file-menu plan call 16): a new bridge and a new app on it."""
    from busk_tui.bridge import Bridge
    from busk_tui.model import ShowLoadFailed

    assert options.show is not None
    show = options.show
    _debug_log()
    while True:
        try:
            bridge = Bridge.standalone(
                show,
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

        app = BuskApp(bridge, settings, standalone=True, state_dir=options.state_dir)
        try:
            code = app.run()
        finally:
            bridge.stop()  # the show stops whatever ended the app: its output is terminated
            config.write_state(config.state_path(), page=app.page, layout=app.view.layout)
        if app.next_show is None:
            return 0 if code is None else code
        show = app.next_show
        settings = config.settings(  # the page and layout the last show left
            options, config=options.config or config.config_path(), state=config.state_path()
        )


def _debug_log() -> None:
    """Tracebacks the TUI catches go to ``$XDG_STATE_HOME/busk-tui/debug.log``
    (nowhere, if it cannot be written)."""
    logger = logging.getLogger("busk_tui")
    if logger.handlers:  # the launcher's, then --standalone's
        return
    path = config.state_path().with_name("debug.log")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8", delay=True)
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    logger.propagate = False
