# Phase 8 — busk as a library: implementation plan

> Source: the user's request of 2026-10-16. Other developers should be able to install busk and import it as a library, through a small, clean public API, and the CLI should become a thin wrapper over that API. This plan builds on the code as it stands after Phase 7 (3175 tests). The spec (`busking-console-architecture-python.md`) says nothing about packaging, and its §21 package map stays as it is. The user answered the plan's questions on 2026-10-16. §3 records the answers as decisions marked *(user)*. Calls marked *(plan)* are open to veto.

## Context

Phase 7 completed the spec's roadmap. busk is a working console, but it can only be used through its command line:

- `busk run` is the only code that puts a show on stage. Its wiring, `run_console` (190 lines in `process/console_host.py`), mixes the show with the terminal:
  - it prints, recovers from crashes, autosaves, runs the prompt and decides exit codes;
  - it reads its configuration from an `argparse.Namespace`.
- Core modules print. The session's default reporter, the bindings, feedback, OSC and the surface manager write to stdout and stderr.
- The CLI changes process-wide state (the GIL switch interval, `gc.freeze()`, signal handlers), and it writes to `~/.local/state/busk` unless told otherwise.
- `mido` is loaded by anything that touches the console or the surfaces, because of one type alias and two module-level imports. Its C backend, `python-rtmidi`, is a hard dependency.
- `busk/__init__.py` exports nothing but `__version__`, and its docstring describes Phase 3.
- The exceptions have no common base.
- The project is not under version control.

Much is already in good shape (§2):
- show I/O, validation, compilation and import are pure functions;
- `Session.submit` and `Console.execute` never raise;
- the engine runs on any clock;
- the wheel already builds with `py.typed` and its package data.

Four things make this phase harder than adding an `__init__`:

1. **Tests and benches import 87 internal modules, over 633 import lines.** Renaming internals to `_private` modules would rewrite every one of those lines. It would also change the `-m busk.process.engine_host` command line that starts the engine. So the boundary has to be drawn without moving modules.
2. **The engine process imports the `busk` package first.** Eager re-exports in `busk/__init__.py` would load the session, the console, the web server and `mido` into the engine process, on every restart.
3. **The CLI's output is its interface for the user**, and test_cli, test_processes and the other process tests assert exact lines. Every step must leave that output byte-identical, so the first step records it.
4. **A library cannot give Phase 7's guarantees.** A show running inside someone else's process has no watchdog and no process isolation. `LiveShow` must say so, and `busk run` keeps the guarantees.

**Done when:**

- The project is a private GitHub repository, `lothwen/busk`, with one commit per step.
- In a fresh virtual environment, `pip install "busk @ git+https://github.com/lothwen/busk.git@v0.1.0"` gives:
  - the `busk` command;
  - `import busk` with the §5.1 API.

  `busk[midi]` adds MIDI surfaces.
- The three examples of §5.2 run as written: they are the doctests of `docs/library.md`.
- `validate`, `new`, `import` and the show wiring of `run` (in both modes) go through the public API.
- The CLI's transcripts are byte-identical to the ones recorded in step 1.
- `test_public_api.py` pins the public API, names and signatures. A strict-mypy consumer type-checks against it.
- No public call prints, exits, changes a process-wide setting, or writes outside the paths it is given.
- Every Phase 0–7 test still passes. So do the perf gates, `-m soak`, and both benches with `--processes`, within Phase 7's targets.
- The project has an MIT license and a CHANGELOG, and `v0.1.0` is tagged.

---

## 1. Scope

| In Phase 8 | Deferred |
|---|---|
| A git repository with a private GitHub remote (step 0) | CI (GitHub Actions) |
| A small public API in `busk` (§5.1). The schema and command types are public as types | `compile_show`, `Engine`, `Session`, `Console`, `EffectLibrary`, route status: added when someone needs them |
| `OfflineShow` (a clock the caller drives) and `LiveShow` (real time, DMX output, optional surfaces) | Autosave, crash recovery and the event log in `LiveShow`. The process split and the watchdog from the library |
| `BuskError` and `ScriptError` | A `CommandResult.check()` that raises |
| Reporters and logging instead of prints. No process-wide changes by default | — |
| MIDI as the optional extra `busk[midi]` | — |
| `RunOptions` instead of `argparse.Namespace`. The CLI rebuilt on the runner | Moving the CLI into a `cli/` package |
| Packaging for git URLs and wheels: MIT license, extras, lower dependency floors, Python versions | PyPI (the user's choice: git and private only) |
| `docs/library.md` with doctested examples. A versioning policy, a CHANGELOG, the tag `v0.1.0` | Sphinx. Windows |

---

## 2. Baseline after Phase 7

Measured while planning (2026-10-16, Python 3.14.7): `uv run pytest` gives 3175 passed, 1 skipped, 13 deselected in 137 s. Phase 7's last numbers:
- 12 perf gates pass;
- edit latency with processes on the reference rig: 1 overrun in 1810 ticks;
- surface load with processes: 4 in 2011.

Step 10 compares against these.

### What busk does

A show is a JSON document, typed as `TypedDict`s and validated by pydantic. It is compiled into flat arrays. An engine ticks at a fixed rate (100 Hz by default), runs the busking pipeline and publishes DMX frames. The output sends them as sACN, Art-Net or DMX-USB.

A session takes every command. It is the single writer of the show and the programmer, and it keeps the undo timeline. A line console drives the session, and MIDI, OSC and web surfaces send commands.

The CLI has five commands: `validate`, `new`, `import ofl|gdtf`, `replay` and `run`. `run` uses three processes with a watchdog by default, and one process with `--threads`.

### Already library-shaped

- **Pure functions that raise and never print:**
  - `load_show`, `save_show` and `new_show` (`persistence/show_file.py`);
  - `validate_show` (`model/validate.py:116`);
  - `compile_show` (`compiler/compile.py:202`);
  - `read_ofl` and `read_gdtf` (`importers/`).
- **Calls that never raise:** `Session.submit` returns a `CommandResult` (`session/session.py:228`), and `Console.execute(line)` returns a `Reply` (`console/console.py:101`).
- **A deterministic engine:** `Engine` takes a `Clock`, so on a `FakeClock` its frames are deterministic. `tests/session_harness.py` (a session and an engine on a fake clock) is a library in all but name, and `OfflineShow` formalises it.
- **No hidden configuration:**
  - nothing reads an environment variable at import time: `XDG_STATE_HOME` is read only when `state_directory()` is called (`persistence/paths.py:29`);
  - there are no `global` statements;
  - nothing calls `sys.exit` outside `__main__` and the child processes' `main`. The `os._exit` calls in the child processes are deliberate.
- **Package data:** the built-in profiles, `effects.json` and the web page are found through `importlib.resources`.

### Coupled to the CLI

| # | Where | Problem |
|---|---|---|
| 1 | `process/console_host.py:555` (`run_console`), `:259` (`ThreadsBackend`), `ProcessBackend`, `process/root.py:193` (`Root`), `replay.main` | The configuration is an `argparse.Namespace` |
| 2 | `run_console` | The only place a running show is assembled. It also prints, recovers, compiles and prints warnings, reports limitations, opens routes (`ThreadsBackend.connect` prints the route lines), opens surfaces, feedback and the web key, autosaves, freezes the GC, runs the prompt, shuts down in order and reports. A show cannot run without a terminal |
| 3 | `session/session.py:145` (`report=_stderr`), `io/bindings.py:100`, `io/feedback.py:88`, `io/osc.py:366` (rate limit), `io/surfaces.py:92–227` (10 prints), `persistence/eventlog.py:253` | Core modules print. The output scheduler already does it right: it puts notices on a queue (`OutputScheduler.notices`) |
| 4 | `console_host.py:317`, `engine_host.py:458` (`sys.setswitchinterval`); `console_host.py:674`, `engine_host.py:359` (`gc.freeze()`); `root.py:250`, `console_host.py:444` (signal handlers); `console/console.py:118` | Process-wide side effects. The console only holds SIGINT on the main thread and then restores it, which is acceptable once documented |
| 5 | callers of `state_directory()` | The CID (`busk new`), autosave, the event log and the web key go to `~/.local/state/busk` by default |
| 6 | `io/midi.py:81` (`FeedbackKind`), imported by `io/osc.py:59` and `io/feedback.py:70`; `from busk.io import midi` in `io/surfaces.py:55` and `io/feedback.py:68` | `mido` is loaded by anything that imports the console, OSC, feedback or the surfaces. MIDI is a hard dependency |
| 7 | 10 exception classes | No common base. `ImportFailed` is a `ValueError` |
| 8 | `busk/__init__.py`, `pyproject.toml` | Only `__version__` is exported, and the docstring describes Phase 3. The version is written in two places. The description says "Phase 7: hardening…". There is no license |
| 9 | `output/dmxusb.py:59`, `output/netif.py:45` | POSIX only. `termios` and `tty` are imported at module load. Interface lookups use Linux ioctls, which raise `OSError` at call time elsewhere |
| 10 | tests/, bench/ | 87 internal modules imported, over 633 import lines. The benches build `Session` without a `report`, so they rely on its stderr default |

### Import costs

| `import …` | ms | loads `mido` |
|---|---|---|
| `busk` | 0.1 | no |
| `busk.model.validate` | 112 | no |
| `busk.compiler.compile` | 161 | no |
| `busk.engine.loop` | 190 | no |
| `busk.session.session` | 172 | no |
| `busk.console.console` | 193 | **yes** (through `io.osc` → `io.midi`) |
| `busk.importers.ofl` | 48 | no |
| `busk.output.scheduler` | 181 | no |
| `busk.cli` | 218 | yes |

### Packaging today

- `uv build` (run into a scratch directory) makes `busk-0.1.0-py3-none-any.whl`. It has 142 entries, including `py.typed`, the five profiles, `effects.json` and the web page. The sdist has 143 entries.
- `pyproject.toml` has:
  - version 0.1.0, also written in `__init__.py`;
  - a description that says "Phase 7…";
  - no license;
  - dependency floors equal to the locked versions (`numpy>=2.5.4`, `pydantic>=2.14.0`);
  - `requires-python = ">=3.12"`, although only 3.14 is tested;
  - `uv_build`, `busk = "busk.cli:main"`, and the src layout.
- Git and GitHub:
  - the project is not a git repository;
  - `gh` is logged in as `lothwen` (https, scope `repo`), and the global git identity is Daniel Sánchez <danillo@euskai.org>;
  - neither `lothwen/busk` nor `lothwen/dmxengine-redesign` exists;
  - 289 files would be committed, not counting caches, the virtual environment and the show backup, and a pattern search found no secrets in them. The spec and the phase plans live in `docs/`. The original, non-Python spec (`busking-console-architecture.md`) is no longer in the project, and nothing refers to it.

---

## 3. Decisions

### Answered by the user (2026-10-16)

1. **Scope: tooling, offline and live.** Library users can:
   - load, validate and save shows;
   - import OFL and GDTF profiles;
   - build shows from console lines or command dicts;
   - render frames on a clock they drive;
   - run a show live in their own process: the engine and DMX output as threads, optionally the show's surfaces.

   The three-process split and the watchdog stay in `busk run`. *(user)*
2. **Distribution: git URLs and private wheels**, no PyPI. So there is no PyPI readme and no classifiers. *(user)*
3. **Version control comes first (step 0):** `git init`, commit the current state, push to a private GitHub repository. *(user)* The name `lothwen/busk` is the plan's choice: it matches the package and the install URL.
4. **The facades are named `OfflineShow` and `LiveShow`.** "Simulator" would clash with TupperDMX-Simul. *(user)*
5. **MIDI becomes the optional extra `busk[midi]`** (`mido`, `python-rtmidi`). It is the only dependency that needs system libraries (ALSA) to build where no wheel exists. *(user)*
6. **The version stays 0.1.0.** It becomes the first release with a public API, tagged `v0.1.0` at step 13. *(user)*
7. **License: MIT.** *(user)*
8. **A refused command is a value**, `CommandResult.ok` or `Reply.ok`, as today. Only `run_script` raises. *(user)*
9. **`LiveShow` has no autosave, crash recovery or event log.** Those stay in `busk run`. Embedders save with `save()`. *(user)*
10. **`tune_interpreter` is off by default.** A library does not change process-wide settings unless asked. *(user)*
11. **Platforms:** Linux is tested. Other POSIX systems are expected to work but untested. Windows is not supported, because `dmxusb` needs `termios`. *(user)*
12. **Public types:** the `TypedDict`s and type aliases of `busk.model.*` and `busk.commands.types`. They describe file and command formats that already exist, so publishing them adds no new commitment. The event log and `busk replay` are not public. *(user)*

### The plan's calls (open to veto)

13. **The boundary is drawn by `busk.__all__`, not by renaming modules** (Context 1). Public means:
    - the names in `busk.__all__`, with their documented attributes and methods;
    - the types of decision 12.

    Everything else is internal, whether or not its name starts with an underscore. Tests enforce the boundary instead of a directory split (§5.3).
14. **`busk/__init__.py` re-exports lazily** (PEP 562 `__getattr__`), for three reasons (Context 2):
    - `import busk` stays cheap, and the engine process loads nothing it doesn't run;
    - it avoids the model ↔ commands import cycle that `model/__init__` documents;
    - the same table can later serve deprecated names.
15. **Two facades instead of `Session`, `CommandBus`, `Engine` and `Console`.**
    - Those constructors take 6–13 parameters of internal types: buses, stamps, engine state readers, event-log causes.
    - The facades do the wiring that `session_harness` and `run_console` do by hand.
    - There are two classes because `tick()` only makes sense offline, and `start()`/`stop()` only live.
16. **`DmxFrame` instead of the engine's `Frame`.**
    - `Frame` carries the compiled show and the output layout, and Phase 7 changed it twice.
    - `DmxFrame` also maps each row to its universe number, which a caller of `Frame` cannot do.
17. **`IdFactory` and `CounterIds` are public.** A golden test of a generated show needs reproducible ids, and 20 of busk's test files use `CounterIds`.
18. **Core modules report through callbacks that default to logging** (`busk.session`, `busk.surfaces`, `busk.output`, `busk.eventlog`). The `busk` logger gets a `NullHandler`. The CLI passes printers, so its output does not change.
19. **`RunOptions` is internal.** It types the CLI's plumbing, and it is not part of the API.
20. **In `OfflineShow`, commands happen now and `tick(t)` moves time.** Each `submit`, `execute` and script line is followed by a tick at the current engine time. So a command takes effect at once, and installs never pile up on the bus (§5.4).
21. **Existing exceptions keep their names, modules and attributes.** Only their base class changes (§5.8).
22. **Commits:** one per step on `main` (`Phase 8 step N: …`), pushed at the end of each session. When a step is done, a short **Done** note goes under it in this file, as in Phase 7.

---

## 4. Project layout (new and changed files)

```
.gitignore                     # caches, .venv, dist, show backups, soak output (new, step 0)
LICENSE                        # MIT (new, step 11)
CHANGELOG.md                   # (new, step 12)
docs/library.md                # the library guide; its examples are doctests (new)
pyproject.toml                 # extras, license, floors, description (changed)
README.md                      # setup with extras; "Using busk as a library"; layout (changed)
src/busk/
  __init__.py                  # lazy public namespace, __all__, NullHandler, docstring (changed)
  errors.py                    # BuskError, ScriptError (new)
  runner.py                    # OfflineShow, LiveShow, DmxFrame; the in-process run (new)
  cli.py                       # RunOptions from arguments; validate/new/import on the API (changed)
  persistence/show_file.py     # ShowLoadError(BuskError); save_show/new_show defaults (changed)
  compiler/compile.py          # UnsupportedFeature(BuskError) (changed)
  importers/__init__.py ofl.py gdtf.py   # ImportFailed(BuskError, ValueError); StrPath (changed)
  session/session.py           # report → logging (changed)
  session/library.py           # StrPath directories (changed)
  console/console.py           # run_script reports the failing line (changed)
  model/surface.py             # FeedbackKind, moved from io/midi.py (changed)
  io/midi.py osc.py feedback.py bindings.py surfaces.py   # mido imported lazily; reporters (changed)
  persistence/eventlog.py      # reporter (changed)
  process/console_host.py      # RunOptions; run_console on the runner; ThreadsBackend thin (changed)
  process/root.py replay.py    # RunOptions (changed)
  commands/__init__.py model/__init__.py   # docstrings: what is public (changed)
tests/
  test_cli_transcripts.py  golden/cli/       # step 1 (new)
  test_errors.py  test_reporting.py  test_no_midi.py  test_signatures.py   (new)
  test_offline_show.py  test_live_show.py    (new)
  test_public_api.py  golden/public_api.json  api_consumer.py   (new)
  test_packaging.py                          # version match, metadata, license (new)
  test_docs.py                               # the doctests of docs/library.md, and only that file (new)
```

Dependencies: `numpy` and `pydantic` stay, with floors lowered wherever the lowest-direct run passes. `mido` and `python-rtmidi` move to the `midi` extra. Nothing new is added.

---

## 5. Component design

### 5.1 The public API

28 names, all importable from `busk`. `StrPath = str | os.PathLike[str]`.

```python
# Show documents
def load_show(path: StrPath) -> tuple[Show, list[Issue]]
    # Read and validate a .show or .json file; return the show and its warnings.
def save_show(show: Show, path: StrPath, *, now: datetime | None = None,
              backups: bool = True) -> Path | None
    # Write atomically, backing up the file it replaces; return the backup's path.
def new_show(title: str, *, cid: str | None = None, now: datetime | None = None,
             ids: IdFactory | None = None) -> Show
    # The `busk new` template. cid=None → a fresh UUID: no state directory is touched.
def validate_show(text: str | bytes) -> tuple[Show | None, list[Issue]]
    # Validate a show document held in memory.

# Fixture profiles
def read_ofl(path: StrPath, *, manufacturer: str | None = None) -> ImportReport
def read_gdtf(path: StrPath, *, manufacturer: str | None = None) -> ImportReport
class ProfileLibrary:
    # The built-in profiles plus directories of busk, OFL and GDTF files, for `fixture add`.
    def __init__(self, directories: Sequence[StrPath] = (), *, builtin: bool = True) -> None
    def get(self, ident: str) -> FixtureProfile | None
    def find(self, name: str) -> FixtureProfile | None      # id or name, ignoring case
    def __iter__(self) -> Iterator[FixtureProfile]
    def __len__(self) -> int
    problems: list[str]                                     # one line per skipped file

# Running a show
class OfflineShow:
    # A session over an engine on a clock you drive. No threads, no sockets,
    # no files unless asked.
    def __init__(self, show: Show, *, path: StrPath | None = None,
                 library: ProfileLibrary | None = None, ids: IdFactory | None = None) -> None
    show: Show                        # the committed document, after edits
    warnings: tuple[Issue, ...]       # compile warnings of `show`
    snapshot: EngineSnapshot          # playbacks, masters, page, tempo
    time: float                       # engine time of the last tick
    def submit(self, command: Command) -> CommandResult   # any command; never raises
    def execute(self, line: str) -> Reply                 # one console line; never raises
    def run_script(self, path: StrPath) -> list[str]      # the lines it wrote; ScriptError at the first failure
    def save(self, path: StrPath | None = None) -> CommandResult   # sets meta.modified; backups
    def tick(self, t: float) -> DmxFrame                  # move engine time to t (≥ time)

class LiveShow:
    # The same, in real time: engine and DMX output threads, optionally the show's surfaces.
    def __init__(self, show: Show, *, path: StrPath | None = None,
                 library: ProfileLibrary | None = None, output: bool = True,
                 surfaces: bool = False, state_dir: StrPath | None = None,
                 tune_interpreter: bool = False) -> None
    show; warnings; submit; execute; run_script; save    # as in OfflineShow
    snapshot: EngineSnapshot | None   # None before start()
    frame: DmxFrame | None            # the newest frame
    def start(self) -> None           # open routes and surfaces; returns after the first snapshot
    def stop(self) -> None            # input, then engine, then output (Stream_Terminated); idempotent
    def __enter__(self) -> Self       # start()
    def __exit__(self, *exc: object) -> None   # stop()

# Data types
Show, FixtureProfile          # the schema TypedDicts (decision 12)
Command                       # the union of the 37 command TypedDicts
Issue                         # severity, path, message
CommandResult                 # ok, message, issues
Reply                         # text, ok
ImportReport                  # profile, notes
EngineSnapshot, PlaybackStatus, SpeedStatus, PageStatus
DmxFrame                      # NEW: seq, time, universes: Mapping[int, bytes] (universe number → 512 bytes)
IdFactory, CounterIds         # the id protocol; reproducible ids

# Errors (§5.8)
BuskError, ShowLoadError, UnsupportedFeature, ImportFailed, ScriptError
# and __version__
```

The lazy table, with the module each name comes from:

| Names | Module |
|---|---|
| `load_show`, `save_show`, `new_show`, `ShowLoadError` | `busk.persistence.show_file` |
| `validate_show`, `Issue` | `busk.model.validate` |
| `Show` | `busk.model.show` |
| `FixtureProfile` | `busk.model.profile` |
| `Command` | `busk.commands.types` |
| `read_ofl` | `busk.importers.ofl` |
| `read_gdtf` | `busk.importers.gdtf` |
| `ImportReport`, `ImportFailed` | `busk.importers` |
| `ProfileLibrary` | `busk.session.library` |
| `IdFactory`, `CounterIds` | `busk.session.ids` |
| `CommandResult` | `busk.session.session` |
| `Reply` | `busk.console.console` |
| `EngineSnapshot`, `PlaybackStatus`, `SpeedStatus`, `PageStatus` | `busk.engine.snapshot` |
| `UnsupportedFeature` | `busk.compiler.compile` |
| `OfflineShow`, `LiveShow`, `DmxFrame` | `busk.runner` |
| `BuskError`, `ScriptError` | `busk.errors` |

Why each part is in:
- **The file, validation and import functions** are what `busk validate`, `busk new` and `busk import` do, and they already work without the CLI.
- **`ProfileLibrary`**: `fixture add` needs it, and it is the only way to bring in your own profiles.
- **The facades**: decisions 15 and 20.
- **`DmxFrame`**: decision 16.
- **`IdFactory` and `CounterIds`**: decision 17.
- **The snapshot types**: they are already frozen dataclasses made for UIs (the web remote and feedback read them).

Left out, and addable later without a break: `compile_show`/`CompiledShow` (the facades compile and expose the warnings), `CommandBus`, `Engine`, `Session`, `Console`, `EffectLibrary`, route status, autosave, recovery, the event log, replay, output drivers and surface internals.

### 5.2 Usage examples

These three examples become the doctests of `docs/library.md`, run against the repository's examples.

```python
# 1. Tooling: validate a show, import a profile
import busk

try:
    show, warnings = busk.load_show("club.show")
except busk.ShowLoadError as exc:
    print("\n".join(str(issue) for issue in exc.issues))   # "fixtures[3].address: …"

report = busk.read_ofl("ofl/tupperdmx/moving-head.json", manufacturer="TupperDMX")
print(report.profile["name"], [mode["name"] for mode in report.profile["modes"]])
print("\n".join(report.notes))
```

```python
# 2. Build a show from a script and render it on a clock you drive
busk.save_show(busk.new_show("Club Night"), "club.show")    # what `busk new` does
show, _ = busk.load_show("club.show")
offline = busk.OfflineShow(show, path="club.show", ids=busk.CounterIds())
offline.run_script("examples/phase3-build.busk")            # its last line, `save`, writes club.show
offline.execute("fader 1 1")                                # happens now (t = 0)
frame = offline.tick(3.0)                                   # 3 s later
print(frame.universes[1][:16])                              # universe 1's first 16 bytes
```

```python
# 3. Live, inside your own application
show, _ = busk.load_show("club.show")
with busk.LiveShow(show, path="club.show", surfaces=True) as live:   # routes and MIDI/OSC/web open
    live.execute("gm 0.8")
    live.execute("go 9")
    if live.snapshot is not None:
        print([(p.number, p.state, p.cue) for p in live.snapshot.playbacks])
    ...                                       # the host application's own loop
# Leaving the block closes the surfaces, stops the engine, and the routes send Stream_Terminated.
```

### 5.3 The namespace and the boundary (`busk/__init__.py`)

```python
"""busk — a real-time busking lighting console. (Rewritten: the public API,
what is internal, the stability promise, a pointer to docs/library.md.)"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any

__version__ = "0.1.0"
__all__ = ["BuskError", "CommandResult", …, "validate_show"]   # sorted; pinned by a test

_EXPORTS: dict[str, str] = {"load_show": "busk.persistence.show_file", …}   # the §5.1 table

if TYPE_CHECKING:  # what mypy and pyright see as re-exports
    from busk.persistence.show_file import load_show as load_show
    …

def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'busk' has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value  # the next lookup is a plain attribute
    return value

def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})

logging.getLogger("busk").addHandler(logging.NullHandler())
```

- **What is public:** the module docstring, `docs/library.md` and the docstrings of `busk.commands` and `busk.model` all state the rule of decision 13.
- **The CLI layer** is `busk.cli`, `busk.process.*`, `replay.main` and `replay.add_arguments`, `console.interact` and `process/report.py`. The CLI may use internals for CLI-only features: the process split, autosave and recovery, the event log, replay and the status lines. Everything a library user shares with it goes through the public API: `validate`, `new`, `import`, and the show wiring of `run`.
- **The boundary is enforced by tests**, each run in a subprocess:
  - importing every public name loads neither `argparse`, `busk.cli` nor `busk.process`;
  - `import busk.process.engine_host` loads neither `busk.console`, `busk.session`, `busk.web` nor `mido`;
  - `import busk` alone loads nothing but `logging`.

### 5.4 `OfflineShow` (`runner.py`)

- **Construction:**
  - The show is checked with `validate_edit(show, show)`, which `Session` already runs to collect its warnings. Errors raise `ShowLoadError(issues)`.
  - The show is compiled; an `elementPatch` raises `UnsupportedFeature`.
  - The parts are built: an `Engine` on a `FakeClock`, and a `Session(show, engine.bus, compiled=…, path=…, ids=…, engine_state=lambda: engine.snapshot, report=<log>)`.
  - So is a `Console(session, library or ProfileLibrary())`.
  - Then a first tick at 0.0, so `snapshot` exists at once.
- **Commands happen now** (decision 20):
  - After each `submit`, each `execute` and each script line, the facade ticks at the current `time`. Engine time does not move, so the command and its install apply at once.
  - A session without a draining engine would queue every install on the bus, each holding a compiled show. `bench/edit_latency.py:82` does that today.
  - *To verify in step 6:* two ticks at the same time give the same frame, and leave a running fade and a chase step unchanged.
- **`tick(t)`:** if `t < time`, it raises `ValueError`. Otherwise it moves the clock (`FakeClock.sleep_until(t)`), ticks, and returns the `DmxFrame`.
- **`run_script`:**
  - It runs `Console.run_script` with a collecting writer.
  - `Console.run_script` gains an optional `failed(number, line)` callback, which the CLI does not pass, so its output is unchanged.
  - On failure it raises `ScriptError(path, line, text, output)`. `OSError` (an unreadable file) passes through.
- **`save()`** is `Session.save`: it sets `meta.modified`, backs up, and returns a `CommandResult`.
- **No threads:** `Session.post` is never used, so the session worker never starts.

### 5.5 `LiveShow` (`runner.py`)

- **Construction** validates and compiles, as in `OfflineShow`. It opens nothing and starts no thread.
- **`start()`:**
  1. It builds the in-process run, a private `_LocalRun` taken from `ThreadsBackend.connect` without its prints:
     - `build_routes` and an `OutputScheduler`, unless `output=False`;
     - an `Engine` on a `MonotonicClock`.

     It builds the `Session` and the `Console`.
  2. With `surfaces=True` it builds `BindingResolver`, `WebLink`, `SurfaceManager` (followed by `reconcile`) and `FeedbackWorker` (followed by `open`). The web key comes from `web_key(state_dir)` if `state_dir` is given, else a random key per run, as the CLI already does when the state directory is read-only.
  3. It starts the engine, output and feedback threads, and a monitor thread. The monitor is `Supervisor`'s loop without the status lines: it reconciles surfaces after live edits, follows MIDI hot-plug, and sends route notices to the `busk.output` logger.
  4. With `tune_interpreter=True` it sets `sys.setswitchinterval(SWITCH_INTERVAL)`.
  5. It waits for the engine's first snapshot (`link.sync(SETTLE_S)`). If none comes, it logs a warning.
- **`stop()`** keeps the CLI's order: the monitor, `surfaces.close()`, feedback (stop and join), `session.stop()`, the engine (stop and join), then the output (stop and join). The output's last pass sends the last frame, then Stream_Terminated. Then it restores the switch interval. It is idempotent, and `__exit__` calls it whatever the exception.
- **`frame`** is the `DmxFrame` of the engine's latest frame, cached by frame identity.
- **Logging:**
  - route lines (`sACN r1: …`) are INFO on `busk.output`, and failures WARNING;
  - surface lines are INFO on `busk.surfaces`, including the web remote's URLs, and failures WARNING;
  - posted-command failures are WARNING on `busk.session`.
- **What it does not do:** autosave, recovery, the event log, values files, the prompt, signals, `gc.freeze()` (decisions 9 and 10). **The docs say plainly:** no watchdog, no process isolation; a crash in the host process stops the output; for a show, use `busk run`.
- **A private seam for the CLI (step 10):** `LiveShow._attached(…)` takes an existing engine link and the options only the CLI has:
  - the link is a `LocalEngine` of a `_LocalRun` with `--threads`, or a `RemoteBus` in process mode;
  - the session's stamp and `causes` (the event log);
  - the `--values` base frame;
  - a callback for status lines.

  The public constructor builds its own `_LocalRun`.

### 5.6 Reporting and logging

| Module | Today | After step 3 |
|---|---|---|
| `session/session.py` | `report=_stderr` | `report` defaults to a `busk.session` warning |
| `io/bindings.py`, `io/feedback.py` | `_stderr()` | a `report` parameter, default `busk.surfaces` warning |
| `io/osc.py` | rate-limit `print` | `OscSurface(report=)` |
| `io/surfaces.py` | 10 prints | `SurfaceManager(say=, warn=)`, passed down to `open_midi` / `follow_midi`. `say` is INFO (stdout in the CLI), `warn` is WARNING (stderr) |
| `persistence/eventlog.py` | write-failure `print` | `EventLog(report=)` |
| `output/scheduler.py` | `notices` queue | unchanged. `LiveShow` drains it to logging, and the CLI's `RouteReporter` prints as today |
| `output/console.py` | a stream parameter | unchanged (CLI only) |

The CLI passes printers with the same stream and the same `flush=True` as today, so the transcripts do not change. The messages are the same strings in both cases. Step 3 also checks the benches, which build `Session` without a `report`.

### 5.7 MIDI decoupling

- `FeedbackKind` moves to `model/surface.py`, next to the input address types. `io/midi.py` re-exports it, so tests keep working.
- `io/surfaces.py` and `io/feedback.py` import `busk.io.midi` inside the code that opens a MIDI port, not at module load.
  - Tests that monkeypatch `midi.input_names` patch the module object, so they keep working.
  - `FeedbackWorker` follows MIDI ports only while a MIDI surface exists.
- If `mido` is missing, opening a MIDI surface warns once, `MIDI s-…: unavailable: install busk[midi]`, and the surface stays closed, as an unavailable backend does today. Nothing else changes.
- `pyproject.toml` moves `mido` and `python-rtmidi` to `[project.optional-dependencies] midi`. The development setup becomes `uv sync --all-extras`, written in the README.

### 5.8 Errors

```
BuskError(Exception)                          NEW (busk/errors.py)
├── ShowLoadError       .issues               existing; also raised by the facades for an invalid show
├── UnsupportedFeature                        existing (a fixture with elementPatch)
├── ImportFailed        (also ValueError)     existing; ValueError kept for compatibility
└── ScriptError         .path .line .text .output   NEW
```

- `OSError` passes through untouched. Wrong arguments raise `ValueError` or `TypeError`, never a `BuskError`.
- Internal exceptions are unchanged: `CommandError`, `CommandRejected`, `ParseError`, `EncodeError`, `OscError`, `LinkClosed`, the web errors, `ReplayError`, `LogError` and `Terminated`. None of them escapes a public call.

| Public call | Raises |
|---|---|
| `load_show` | `ShowLoadError` (not a show, or validation errors), `OSError` |
| `save_show` | `OSError`; `ValueError` (extension not `.show` or `.json`) |
| `read_ofl`, `read_gdtf` | `ImportFailed`, `OSError` |
| `validate_show`, `new_show`, `ProfileLibrary()` | nothing: issues and problems are returned |
| `OfflineShow()`, `LiveShow()` | `ShowLoadError`, `UnsupportedFeature` |
| `submit`, `execute`, `save` | nothing: `ok=False` |
| `run_script` | `ScriptError`, `OSError` |
| `OfflineShow.tick` | `ValueError` (time going back) |
| `LiveShow.start` | `RuntimeError` (already started). Routes and surfaces that fail are logged and retried, as today |

### 5.9 Packaging

```toml
[project]
name = "busk"
version = "0.1.0"
description = "A real-time busking lighting console: show files, fixture import, a DMX engine and its command line"
readme = "README.md"
license = "MIT"
license-files = ["LICENSE"]
authors = [{ name = "Daniel Sánchez", email = "danillo@euskai.org" }]
requires-python = ">=3.12"            # kept if 3.12 and 3.13 pass at step 11, else raised
dependencies = ["numpy>=…", "pydantic>=…"]   # floors from the lowest-direct run

[project.optional-dependencies]
midi = ["mido>=1.3.3", "python-rtmidi>=1.5.8"]

[project.urls]
Repository = "https://github.com/lothwen/busk"

[project.scripts]
busk = "busk.cli:main"
```

- **Kept as is:** the src layout, `uv_build`, `python -m busk` and `py.typed`. The mypy override for `mido` stays.
- **The version is written in two places**, `pyproject.toml` and `__version__`. `test_packaging.py` checks that they match.
- **`LICENSE`:** the MIT text, `Copyright (c) 2026 Daniel Sánchez`. Step 11 checks that the wheel's `METADATA` carries `License-Expression: MIT` and the file.
- **Installing:**
  - `pip install "busk[midi] @ git+https://github.com/lothwen/busk.git@v0.1.0"`, or the `git+ssh://git@github.com/…` form, or a wheel from `uv build`;
  - the repository is private, so other developers need read access as collaborators, plus git credentials (`gh auth setup-git` or an SSH key);
  - a git install builds from source, so it fetches `uv_build` from the package index. Offline machines need the wheel.
- **No PyPI readme or classifiers** (decision 2). The README stays the long description.

### 5.10 Typing and docs

- **mypy:** strict mypy stays on `src`. A new `tests/api_consumer.py` uses only public names (the §5.2 examples, typed). It runs under `uv run mypy --strict tests/api_consumer.py`, which proves the lazy re-exports type-check for a project that depends on busk. Optionally, one run of `pyright --verifytypes busk --ignoreexternal`, without making pyright a dependency.
- **Docstrings** keep the house style: reST prose with Sphinx roles. Every public callable states what it returns and what it raises, as `load_show` already does. They are not converted to Google or NumPy sections, which would not match the other 37k lines.
- **`docs/library.md`** has:
  - installing (git URL, wheel, the `midi` extra);
  - the three uses, with the §5.2 examples as `>>>` doctests;
  - a reference table of the 28 names;
  - the error table;
  - the boundary rule;
  - the stability policy;
  - the warning about `LiveShow` and `busk run`.

  `tests/test_docs.py` runs them with `doctest.testfile` on `docs/library.md` alone, as part of the default suite. `docs/` also holds the spec and the phase plans, so a `--doctest-glob='*.md'` over the folder would turn any `>>>` line someone writes in a plan into a test.
- **README:** a short "Using busk as a library" section that links to `docs/library.md`. The Setup section gains `--all-extras`, and the Layout section the new files.

### 5.11 Versioning and stability

- **Numbering:** `0.1.0` is the first release with a public API. 0.x semver applies:
  - patch releases (0.1.1) only fix;
  - minor releases (0.2.0) may break, with a deprecation first wherever possible.

  1.0 comes once another project has used busk through a release with no breaking change.
- **Breaking, within the public scope:**
  - removing or renaming a name in `__all__`;
  - removing or renaming a parameter, reordering positional parameters, or removing a default;
  - accepting narrower types;
  - changing a return type or its shape;
  - raising an exception that is not a subclass of a documented one;
  - removing or renaming a field of a public dataclass;
  - removing a key from a schema or command `TypedDict`, or making an optional key required. That is also a file-format change, so it needs a `schemaVersion` bump and a migration;
  - removing a CLI command or flag, or changing an exit code.
- **Not breaking:**
  - new names, keyword arguments with defaults, optional keys and command types;
  - any message text: CLI output, `Issue.message`, `Reply.text`, log records;
  - anything internal.
- **Deprecating:**
  - the old name or parameter calls `warnings.warn(…, DeprecationWarning, stacklevel=2)`, and renamed names go through the lazy table;
  - the old form stays for at least one minor release, with a "Deprecated" entry in `CHANGELOG.md`;
  - pytest turns deprecation warnings raised from busk's own modules into errors, so busk never uses its own deprecated API.
- **Every API change is a reviewed diff:** `tests/golden/public_api.json` pins `inspect.signature` of every public callable and method, and the fields of every public dataclass.
- **Releases** follow Keep a Changelog, with annotated tags `vX.Y.Z` on `main`.

### 5.12 The repository (step 0)

- **`.gitignore`:** `.venv/`, `__pycache__/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`, `.hypothesis/` (also `tests/.hypothesis/`), `dist/`, `*.backups/` (show backups written by runs) and `soak-*/` (soak output).
- **What is committed:** everything else, 290 files (289 plus the `.gitignore`). That includes `uv.lock`, `.python-version`, the spec and the plans in `docs/`, examples, goldens, fixtures and `tests/process_site/`. The 528-byte TupperDMX show backup is ignored.
- **The commit:** `git init -b main`, then one commit, authored with the global identity and ending with the `Co-Authored-By` line. The message: `busk after Phase 7 (3175 tests green), and the Phase 8 plan`.
- **The remote:** `gh repo create lothwen/busk --private --source . --remote origin --push`.

---

## 6. Implementation steps

Each step follows TDD: write the listed tests first, then make them pass. **Every step ends with the whole suite green** (pytest, ruff check, ruff format --check, mypy), **the CLI transcripts unchanged** (from step 1 on), and one commit. Steps are sized so that two fit in one working session.

Step 0 is the repository. Steps 1–5 decouple without changing behaviour, 6–8 are the API, 9–10 the CLI, 11–12 packaging and docs, and 13 is the user's.

0. **Repository** (§5.12).
   - Write `.gitignore`; `git init -b main`.
   - Check `git status --short`: 290 entries, nothing from the ignore list, and a look at anything unexpected. The README's links into `docs/` resolve.
   - Commit; `gh repo create lothwen/busk --private --source . --remote origin --push`.

   → *verify:*
   - `gh repo view lothwen/busk --json visibility` says `PRIVATE`, and `git status` is clean;
   - a fresh clone into a scratch directory passes `uv sync && uv run pytest`: 3175 passed, which proves the ignore list dropped nothing the suite needs.

   **Done** (2026-10-16). `git status` listed 290 entries, none from the ignore list; the README's links into `docs/` resolve, and a pattern search found no secrets. The commit is `busk after Phase 7 (3175 tests green), and the Phase 8 plan`, pushed to `https://github.com/lothwen/busk` (`PRIVATE`, default branch `main`). A fresh clone passed `uv sync && uv run pytest`: 3175 passed, 1 skipped, 13 deselected (141 s).
1. **CLI transcripts.** `tests/test_cli_transcripts.py` and `tests/golden/cli/`, recorded from the CLI as it is, before any change, and reviewed by hand. It covers stdout and stderr separately, with exit codes:
   - `validate` on Appendix A and on a broken copy;
   - `new` with `--state-dir`;
   - `import ofl --report` on the TupperDMX fixtures, with the hashes of the written files;
   - `import gdtf` on an archive from `gdtf_builder`;
   - `run --threads --no-console --duration 1 --iface lo --script examples/phase3-build.busk` on a `busk new` show, with the MIDI port list patched as test_cli does;
   - the same `run` in process mode, through `process_harness.BuskRun`. Root and console lines interleave, so this case compares the sorted lines, not their order.

   Masked: ids (`<prefix>-<12 hex>`), pids, times, temporary paths, and the counters of the `engine:` and route statistics lines.

   → *verify:* 3175 + N passed; three runs give identical transcripts; `-m perf` passes.

   **Done** (2026-10-16; ruff, format and mypy clean; `-m perf` 12 passed). The first full run failed one test, `test_console_restart.py::test_a_patch_not_yet_autosaved_is_undone_through_the_engines_remap`, because step 2's edits to `compile.py` landed while it ran: for a moment the file used `BuskError` before importing it, and a console child restarted in that window. That test then passed alone 3 times out of 3, and the next full run, with step 2 in place, gave 3190 passed. Eight cases in `tests/golden/cli/*.txt`: `validate` of Appendix A, of a broken copy (two errors and a warning) and of a missing file; `new`, then `new` again (refused, exit 1); `import ofl --report` of the five TupperDMX files and `import gdtf --report` of `test_gdtf.spot()` plus a broken archive (exit 1), each with the sha256 of every written profile; `run --threads` and `run` in process mode. Each transcript is the command, `exit N`, then stdout and stderr with every line indented, so it reads as written; `BUSK_REGOLDEN=1` rewrites them. Five runs gave identical transcripts. Additions to the harness: `BuskRun(midi_ports=…)` sets `BUSK_TEST_MIDI_PORTS`, and `tests/process_site/sitecustomize.py` patches `midi.input_names` with it in every process of the tree. **Found:** in process mode the root prints `no output: no route is open (add --console to print frames)` only when the engine's first layout arrives before the script has added its route, which is a race in the CLI as it stands. The process case leaves that one line out, and the module docstring says why. The CLI is unchanged.
2. **The exception base** (§5.8). Add `errors.py` (`BuskError`; `ScriptError` is defined here and raised from step 6), then re-base `ShowLoadError`, `UnsupportedFeature` and `ImportFailed` (which keeps `ValueError`). → *verify:*
   - `test_errors.py`: each class subclasses `BuskError`; `ImportFailed` is still a `ValueError`; the attributes are unchanged;
   - the transcripts are unchanged.

   **Done** (2026-10-16; 3190 passed with step 1, ruff, format and mypy clean; transcripts unchanged). `busk/errors.py` imports nothing from busk, so the three modules import `BuskError` from it without a cycle. `ScriptError(path, line, text, output)` formats as `path:line: text`, the line `busk run --script` prints. `ImportFailed` is `ImportFailed(BuskError, ValueError)`.
3. **Prints become reporters** (§5.6), and the `busk` logger gets its `NullHandler`. The CLI passes printers to `Session`, `BindingResolver`, `FeedbackWorker`, `SurfaceManager`, `OscSurface` and `EventLog`. Check the benches: they build `Session` without a `report`, so they rely on its stderr default. → *verify:*
   - `test_reporting.py`: each class built with defaults writes nothing to stdout or stderr (`capsys`), and logs the same text (`caplog`): a posted command that fails, a MIDI port not found, an OSC flood, an unwritable event log;
   - test_cli, test_hotplug and test_rate_limits, and the transcripts, are unchanged.

   **Done** (2026-10-16; 3204 passed, ruff, format and mypy clean; transcripts unchanged). Each module's default is a bound method of its logger, `logging.getLogger("busk.<area>").warning` (or `.info`), so a default's message is the very string the CLI prints. `test_reporting.py` (14 tests) covers the four cases, an OSC surface's INFO line, the NullHandler, and each default (`inspect.signature`). The CLI's printers are `say` (stdout) and `warn` (stderr) in `process/report.py`, both `flush=True`; `say` replaces `console_host._say`. `open_midi` and `follow_midi` take `say=` and `warn=` too. **Calls the user may veto:**
   - `FeedbackWorker` has `say` and `warn` for its MIDI port lines, besides `report`. Before, those lines went straight to stdout and stderr, apart from `report`, and test_feedback expects `report` to get send failures only.
   - Tests that build these classes and assert on printed lines now pass the CLI's printers: 17 tests in test_hotplug, test_rate_limits, test_surface_manager, test_osc, test_feedback and test_web_api. Their assertions are unchanged.
   - The benches pass the printers too, so their output is as before: `Session(report=warn)` in all three, plus `say` and `warn` for the surfaces and feedback in `surface_load.py`. `surface_load.py 3` printed its surface lines and ran.
4. **MIDI decoupled** (§5.7), `FeedbackKind` moved, the `midi` extra added, and the README Setup updated. → *verify:*
   - `test_no_midi.py`, in a subprocess where `sys.modules["mido"] = None` blocks the import:
     - importing `busk.console.console`, `busk.io.surfaces` and `busk.io.feedback` works;
     - a show with an OSC surface opens it;
     - a MIDI surface gives the one warning;
   - test_midi, test_hotplug and test_feedback pass with the extra installed;
   - `python -X importtime` shows no `mido` under `busk.console.console`.
5. **Library-friendly signatures, additive only:**
   - `save_show(now=None)` uses `utc_now()`;
   - `new_show(title, *, cid=None, now=None, ids=None)` gets a fresh UUID, `utc_now()` and `RandomIds()`;
   - `read_ofl`, `read_gdtf` and `ProfileLibrary` accept `StrPath`.

   → *verify:*
   - the existing tests are untouched;
   - in `test_signatures.py`, `new_show("x")` with `HOME` and `XDG_STATE_HOME` pointed at an empty directory leaves it empty, and the template still validates with 0 issues;
   - `str` paths work.
6. **`OfflineShow`, `DmxFrame`, `ScriptError`** (§5.4), plus `Console.run_script(failed=)`. → *verify:* `test_offline_show.py`:
   - building with `phase3-build.busk` and `CounterIds` gives `tests/golden/phase3_built_show.json`, apart from the `meta` timestamps;
   - busking it gives `phase3_frames.json`;
   - the Phase 4–7 scripts follow, with 0 errors;
   - a failing line raises `ScriptError` with its number, its text and the output so far;
   - `tick` going back raises `ValueError`;
   - two ticks at the same time are identical (decision 20);
   - `threading.active_count()` does not change, and nothing is written to `capsys` or `$HOME`.
7. **`LiveShow`** (§5.5). The in-process run is copied from `ThreadsBackend`, so it exists twice until step 10. → *verify:* `test_live_show.py`:
   - a localhost sACN route (with `tests/sacn_receiver.py`) receives the universes; after `stop()` the receiver sees Stream_Terminated;
   - an OSC surface on a free port: a message changes the snapshot, and its feedback comes back;
   - an exception inside the `with` block still stops everything;
   - no thread left (by name);
   - `sys.getswitchinterval()` and `gc.get_freeze_count()` are unchanged unless `tune_interpreter=True`, which is restored on stop;
   - `start()` twice raises `RuntimeError`, and `stop()` twice is fine;
   - logs are captured, and stdout and stderr stay empty.
8. **The public namespace** (§5.3). Rewrite `busk/__init__.py` and update the `busk.commands` and `busk.model` docstrings. → *verify:*
   - `test_public_api.py`:
     - `__all__` equals the §5.1 list and every name resolves;
     - `dir(busk)`;
     - `busk.__getattr__` raises `AttributeError` for anything else;
     - the signatures golden `tests/golden/public_api.json`;
     - the three subprocess boundary checks;
   - `uv run mypy --strict tests/api_consumer.py`;
   - **the user reviews the names and the signatures golden before step 9.** Names are cheapest to change now.
9. **`RunOptions`.** A frozen dataclass replaces `argparse.Namespace` in `run_console`, `ThreadsBackend`, `ProcessBackend`, `Root` and `replay.main`. `cli.py` builds it from the arguments. The console child still receives its argument list and parses it again. → *verify:*
   - the full suite;
   - test_processes, test_watchdog, test_console_restart and test_recovery, three times;
   - the transcripts are unchanged.
10. **The CLI on the runner.**
    - `run_console` becomes: options, then load and recover, then `LiveShow._attached(link from the backend, …)`, then the prompt, the script or stdin, then `stop()`, autosave's finish, and the report.
    - The CLI keeps autosave, recovery, the event log's start, `gc.freeze()`, the status lines and the limitation report.
    - `ThreadsBackend` keeps only what `_LocalRun` does not: the printed route lines, the event-log pump and the statistics.
    - `validate`, `new` and `import` call the public functions.

    → *verify:*
    - the transcripts are unchanged;
    - the full suite, and the process tests three times;
    - `-m perf`;
    - `bench/edit_latency.py --processes` and `bench/surface_load.py --processes`: reference rig ≤ 1 % overruns, demo 0;
    - `-m soak` passes;
    - the five example scripts through the real CLI in process mode;
    - the public API golden is unchanged, which proves the CLI needed no new public API.

    **Fallback:** if process mode resists, only `--threads` moves onto the runner, and process mode keeps its own wiring. That gets recorded in **Done** and in the README.
11. **Packaging** (§5.9): `LICENSE`, the `pyproject.toml` changes, and `test_packaging.py`, which checks that `__version__` matches `pyproject.toml` and that `License-Expression: MIT` is in the built wheel's metadata. → *verify*, in scratch directories only:
    - `uv build --out-dir <scratch>`;
    - a fresh virtual environment with the wheel and no extras: `busk --version` prints `busk 0.1.0`, `busk validate tests/fixtures/appendix_a.json` reports 0 errors, the docs examples run, and a MIDI surface gives the one warning;
    - the same environment with `[midi]`;
    - in a scratch clone: `uv sync --python 3.12 --all-extras && uv run pytest`, then the same with 3.13. If either fails, `requires-python` is raised to the lowest version that passes;
    - in a scratch clone: `uv sync --resolution lowest-direct --all-extras && uv run pytest`. Floors are lowered to what passes, and `uv.lock` is regenerated only in the project.
12. **Docs and the changelog** (§5.10): `docs/library.md`, the README (library section, Setup, Layout, status), `CHANGELOG.md` (`## [0.1.0]`: the public API, the `midi` extra, the MIT license), and the `busk/__init__` docstring. → *verify:*
    - `uv run pytest tests/test_docs.py` passes;
    - every name in `__all__` appears in the reference table, checked by a test;
    - push `main`.
13. **The user's checks** (§8, "Library checklist"). When they pass, tag `v0.1.0` (`git tag -a v0.1.0 -m "busk 0.1.0: the first release with a public API"`) and push the tag.

---

## 7. Acceptance tests (summary)

| Test file | Proves |
|---|---|
| `test_cli_transcripts.py` | The CLI's output and exit codes, byte for byte, from step 1 to the end |
| `test_errors.py` | The hierarchy; old bases and attributes kept |
| `test_reporting.py` | No prints from core modules; the same messages as log records |
| `test_no_midi.py` | busk works without `mido`; one clear message for MIDI surfaces |
| `test_signatures.py` | The friendlier defaults; no implicit state directory |
| `test_offline_show.py` | The Phase 3 build and frames through the facade; script errors; "commands happen now" |
| `test_live_show.py` | Real output on localhost, surfaces, clean start and stop, no process-wide changes |
| `test_public_api.py` · `api_consumer.py` | The namespace, the signatures golden, the boundary; type completeness for consumers |
| `test_packaging.py` | Version and license metadata |
| `test_docs.py` (the doctests of `docs/library.md`) | The documented examples run |
| All Phase 0–7 tests (unchanged) · `-m perf` · `-m soak` · both benches `--processes` | Nothing regressed, in either run mode |

---

## 8. Verification

```bash
uv sync --all-extras
uv run pytest                                            # all green
uv run pytest tests/test_docs.py                         # the library guide's examples (also in the run above)
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run mypy --strict tests/api_consumer.py
uv run pytest -m perf -s                                 # gates pass
uv run pytest -m soak                                    # 60 s soak with chaos: pass
uv run python bench/edit_latency.py --processes          # demo 0 overruns; reference ≤ 1 %
uv run python bench/surface_load.py --processes          # demo 0 overruns; reference ≤ 1 %
uv build --out-dir /tmp/busk-dist                        # wheel and sdist
python -m venv /tmp/busk-venv && /tmp/busk-venv/bin/pip install /tmp/busk-dist/busk-0.1.0-py3-none-any.whl
/tmp/busk-venv/bin/busk --version                        # → busk 0.1.0
/tmp/busk-venv/bin/python -c "import busk; print(len(busk.__all__))"   # → 28
```

**Library checklist (Phase 8)**, for step 13:

1. **Install from GitHub into another project.** In a new directory:
   - `uv init`, then `uv add "busk[midi] @ git+https://github.com/lothwen/busk.git@main"`;
   - `uv run busk --version` prints `busk 0.1.0`;
   - `uv run python -c "import busk; print(busk.load_show)"` works.
2. **The three guide examples** run there unchanged, from a copy of `examples/`.
3. **TupperDMX through `LiveShow`:**
   - start TupperDMX-Simul first, since it holds port 6454;
   - in Python: `show, _ = busk.load_show("examples/tupperdmx/tupper-demo.show")`, then `with busk.LiveShow(show) as live: live.execute("fader 1 1")`, and wait a few seconds inside the block;
   - the simulator shows the look, and lets go when the block ends.
4. **Without the extra:** in a second project, `uv add "busk @ git+…@main"`. Then `busk run` on the Phase 3 show prints `MIDI s-…: unavailable: install busk[midi]` and runs on.
5. **Read `docs/library.md` as a newcomer would.** Anything unclear gets fixed before the tag.
6. **Tag and push** `v0.1.0`. A collaborator account with read access installs `@v0.1.0`.

---

## 9. Risks and breaking changes for current users

- **The CLI** is designed not to change: no flag, exit code or line changes, and the transcripts enforce it.
  - The risky step is 10: it touches the shutdown order and the console in process mode.
  - It is covered by the process tests run three times, the perf gates, the benches, the soak, and the fallback.
- **Without `[midi]`**, a fresh install has no MIDI surfaces, though it gives a clear message. The development setup becomes `uv sync --all-extras`, written in the README.
- **The default reporters log instead of printing.** Code that relied on `Session`'s default stderr line, such as the benches, becomes silent unless it passes a `report`. Step 3 checks the benches.
- **`LiveShow` is not `busk run`:**
  - no watchdog and no process isolation, so a crash in the host process stops the DMX output;
  - in one process, the reference rig overran 10 % of ticks under edits (Phase 7, step 13: 163 of 1615), against 0.05 % with processes, and that was with the switch interval already set;
  - the docs say so where `LiveShow` is introduced.
- **Python 3.12 and 3.13 are untested** until step 11, which may raise `requires-python`.
- **The private repository:** other developers need read access, and git installs need credentials and network access to fetch `uv_build`. The spec, the plans and the README, which mention local paths such as `~/Documents/TupperDMX`, go to GitHub. They stay private.
- **Internal modules stay where they are,** so tests and benches keep working. Code that imports internals gets no stability promise.
- **The `pyproject.toml` description changes.** The version stays 0.1.0.

---

## 10. After Phase 8

- CI on GitHub Actions: the suite on 3.12–3.14, ruff, mypy, the doctests, building the wheel.
- Wheels attached to GitHub releases (`gh release create v0.1.0 dist/*`) for installs without git.
- On request: `compile_show`, route status, an `EffectLibrary` for custom effect templates, `CommandResult.check()`, autosave and recovery in `LiveShow`.
- PyPI, if the distribution choice changes (`busk` was free on 2026-10-16), and Sphinx docs then.
- The programming phase and the spec gaps from the README's "Next".
