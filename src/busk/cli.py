"""The ``busk`` command line.

``busk validate SHOW``
    Validate a show file (``.show`` or ``.json``) and print one line per
    issue, then a summary. Exits 0 when there are no errors (warnings are
    fine) and 1 otherwise.

``busk new PATH [--title T] [--state-dir D]``
    Write the template show (§17, phase-3-plan §5.8): one grand master, one
    empty page ``Main``, no fixtures, and the installation's sACN CID. Refuses
    to overwrite an existing file.

``busk import ofl FILE… [--manufacturer M] [--out DIR] [--report]``
    Import Open Fixture Library fixture files (Phase 7,
    :mod:`busk.importers.ofl`) and write each as a busk profile,
    ``DIR/<profile id>.json`` (default: the current directory), for
    ``busk run --library DIR``. The manufacturer is ``M``, else the OFL
    repository layout's directory name. It prints one line per file, and
    with ``--report`` every import note (unmapped channels, estimates,
    skipped modes). Exits 1 if any file cannot be imported.

``busk import gdtf FILE… [--manufacturer M] [--out DIR] [--report]``
    The same for GDTF files (``.gdtf``, :mod:`busk.importers.gdtf`). The
    manufacturer is ``M``, else the file's own.

``busk replay LOG… [--until T] [--frames OUT.json] [--at T …]``
    Rebuild a run from its event log (Phase 7, :mod:`busk.replay`): print
    each record at its engine time, and with ``--frames`` write the frames
    the engine made then. Exits 1 if the log does not replay.

``busk run SHOW [options]``
    Load, validate and compile the show, open its output routes and control
    surfaces, run the engine, output and feedback threads, and open the
    **operator console** (Phase 3): line commands that program, record and
    edit the show live (see :mod:`busk.console.parser` for the grammar).
    Exits 1 if the show cannot be loaded or compiled, or if ``--script``
    fails.

    * **Processes** (Phase 7, :mod:`busk.process`): the command starts the
      *root*, which runs the output and starts an *engine* process and a
      *console* process (session, prompt, surfaces, autosave). The root
      prints the route lines, the ``--console`` frame lines and the final
      statistics; the console everything else. ``--threads`` runs all of it
      in one process instead, as in Phase 6 (the default where Unix
      descriptors cannot be passed between processes). ``--stats FILE``
      appends one JSON line of process statistics per second (processes
      only). ``SIGTERM`` and ``SIGHUP`` quit like the end of stdin. Unless
      ``--no-log``, the run writes an **event log** (Phase 7,
      :mod:`busk.persistence.eventlog`) to
      ``<stateDir>/logs/<show id>/<UTC start>.log``; ``info`` names the file.

    * On a terminal the console prompt opens, with Tab completion and ``?``
      (Ctrl+C clears the line; a second one in a row, ``quit`` or Ctrl+D ends
      the run and offers to save unsaved edits). When stdin is
      not a terminal, commands are read from it line by line, and its end
      quits (unless ``--duration`` is given). ``--no-console`` reads no
      commands: the run busks until Ctrl+C, as in Phase 2.
    * ``--script FILE`` runs a console script first and stops at the first
      error, ending the run with exit code 1.
    * **Surfaces** (Phase 6): MIDI controllers, OSC apps and the web remote
      each print one start-up line (a web remote one per address, with its
      key: ``<stateDir>/web-key``, made once). Their feedback (LEDs, motor
      faders, OSC labels) runs on its own thread, from the engine's
      snapshots.
    * **Live edits** reach the engine at the next tick; new routes open and
      removed ones send Stream_Terminated, new surfaces open, and new
      bindings work at once.
    * **Autosave** (``--state-dir``, default ``$XDG_STATE_HOME/busk``): the
      programmer and master levels at most once per second, the show 5 s after
      a burst of edits. After a crash (``kill -9``), the next ``busk run`` of the
      same show restores the programmer, the master levels and the unsaved
      edits, unless ``--no-recover`` is given.
    * ``--iface IF`` is the network interface ``route add`` uses for multicast
      and broadcast (default ``eth0``); ``--library D`` adds a profile
      directory to the built-in library.

    Before running it prints compile warnings and, under ``Ignored in Phase
    6:``, every feature the show uses that this build ignores. While running it
    prints a status line whenever the engine's state changes (except at an
    interactive prompt, where ``status`` prints it), route changes and send
    failures. On exit it prints the engine's statistics and each route's
    counts. ``--values FILE``, ``--duration SECONDS`` and ``--console`` work as
    in Phase 2 (``--console`` frame lines are off at an interactive prompt).

``validate``, ``new`` and ``import`` use only the public API (``busk.load_show``,
``busk.new_show``, ``busk.read_ofl`` …), and ``run`` runs its show on
:class:`busk.LiveShow`'s wiring (phase-8-plan step 10); only the state
directory, the process split, autosave and recovery, the event log, replay
and the status lines are the CLI's own.

Route, surface, limitation, status, frame and statistics lines go to
stdout. Issues, warnings, routes and surfaces that cannot open, send
failures and other diagnostics go to stderr, except for ``validate``, whose
report *is* its output.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from busk import (
    ImportFailed,
    ImportReport,
    ShowLoadError,
    __version__,
    load_show,
    new_show,
    read_gdtf,
    read_ofl,
    replay,
    save_show,
)
from busk.engine.clock import SWITCH_INTERVAL
from busk.persistence.paths import installation_cid, state_directory
from busk.persistence.show_file import utc_now
from busk.process.console_host import (
    ThreadsBackend,
    add_run_arguments,
    cannot_read,
    print_issues,
    run_console,
    status_line,
)
from busk.process.options import RunOptions
from busk.process.report import plural
from busk.process.root import Root

__all__ = ["SWITCH_INTERVAL", "main", "status_line"]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line with ``argv`` (default: ``sys.argv[1:]``); return the exit code."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = _parser().parse_args(arguments)
    if args.command == "validate":
        return _validate(args.show)
    if args.command == "new":
        return _new(args.path, args.title, args.state_dir)
    if args.command == "import":
        reader = read_gdtf if args.format == "gdtf" else read_ofl
        return _import(reader, args.files, args.manufacturer, args.out, report=args.report)
    if args.command == "replay":
        return replay.main(args.log, until=args.until, at=args.at, frames=args.frames)
    options = RunOptions.from_arguments(args)
    if options.threads or not hasattr(socket, "send_fds"):
        return run_console(options, ThreadsBackend(options))
    # Only --version may come before the subcommand: the first "run" is it.
    return Root(options, arguments[arguments.index("run") + 1 :]).run()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="busk", description="Busking lighting console.")
    parser.add_argument("--version", action="version", version=f"busk {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="check a show file and report every issue")
    validate.add_argument("show", type=Path, help="path to a .show or .json show file")

    new = commands.add_parser("new", help="write a new, empty show")
    new.add_argument("path", type=Path, help="where to write it (.show or .json)")
    new.add_argument("--title", help="the show's title (default: the file name)")
    new.add_argument("--state-dir", type=Path, metavar="D", help="busk's state directory")

    importing = commands.add_parser("import", help="import fixture profiles from another format")
    formats = importing.add_subparsers(dest="format", required=True)
    for name, what, files, manufacturer in (
        ("ofl", "Open Fixture Library fixture files (.json)", "OFL fixture files",
         "from the OFL repository layout"),
        ("gdtf", "GDTF fixture type files (.gdtf)", "GDTF files", "the file's own"),
    ):  # fmt: skip
        source = formats.add_parser(name, help=what)
        source.add_argument("files", nargs="+", type=Path, metavar="FILE", help=files)
        source.add_argument("--manufacturer", metavar="M",
                            help=f"the manufacturer (default: {manufacturer})")  # fmt: skip
        source.add_argument("--out", type=Path, metavar="DIR", default=Path(),
                            help="where to write the profiles (default: here)")  # fmt: skip
        source.add_argument("--report", action="store_true", help="print every import note")

    replaying = commands.add_parser("replay", help="rebuild a run from its event log")
    replay.add_arguments(replaying)

    run = commands.add_parser("run", help="run the engine, the console and the DMX output")
    add_run_arguments(run)
    return parser


# ------------------------------------------------------------------ validate


def _validate(path: Path) -> int:
    try:
        _, issues = load_show(path)
    except ShowLoadError as exc:
        issues = exc.issues
    except OSError as exc:
        return cannot_read(path, exc)
    print_issues(issues, sys.stdout)
    errors = sum(issue.severity == "error" for issue in issues)
    print(f"{plural(errors, 'error')}, {plural(len(issues) - errors, 'warning')}")
    return 1 if errors else 0


# -------------------------------------------------------------------- import


def _import(
    reader: Callable[..., ImportReport],
    files: Sequence[Path],
    manufacturer: str | None,
    out: Path,
    *,
    report: bool,
) -> int:
    failed = False
    for path in files:
        try:
            imported = reader(path, manufacturer=manufacturer)
        except ImportFailed as exc:
            print(f"busk: {path}: {exc}", file=sys.stderr)
            failed = True
            continue
        profile = imported.profile
        target = out / f"{profile['id']}.json"
        try:
            out.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", "utf-8")
        except OSError as exc:
            print(f"busk: cannot write {str(target)!r}: {exc}", file=sys.stderr)
            failed = True
            continue
        modes = ", ".join(mode["name"] for mode in profile["modes"])
        notes = imported.notes
        print(
            f"{path}: {profile['name']!r} (modes {modes}) → {target}"
            + ("" if report or not notes else f"; {plural(len(notes), 'note')} (--report)")
        )
        if report:
            for note in notes:
                print(f"  {note}")
    return 1 if failed else 0


# ----------------------------------------------------------------------- new


def _new(path: Path, title: str | None, state_dir: Path | None) -> int:
    if path.exists():
        print(f"busk: {str(path)!r} exists; not overwriting it", file=sys.stderr)
        return 1
    now = utc_now()
    cid = installation_cid(state_directory(state_dir))
    show = new_show(title or path.stem, now=now, cid=cid)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        save_show(show, path, now=now, backups=False)
    except (OSError, ValueError) as exc:
        print(f"busk: cannot write {str(path)!r}: {exc}", file=sys.stderr)
        return 1
    print(f"created {path}")
    return 0
