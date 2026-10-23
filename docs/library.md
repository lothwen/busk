# busk as a library

busk is a real-time busking lighting console: the `busk` command line, and a Python
library that does the same things from your own code. With the library you can:

- load, validate and save show files;
- import fixture profiles from Open Fixture Library and GDTF files;
- build shows from console lines or command dicts;
- render DMX frames on a clock you drive, for tests, previews and offline rendering;
- run a show live inside your own application: the engine and the DMX output as threads,
  optionally with the show's control surfaces (MIDI, OSC, the web remote).

Everything public is importable from `busk` itself. This guide covers [installing](#installing),
[the three uses](#1-tooling-validate-a-show-import-a-profile) with examples, a
[reference](#reference) of the 36 public names, [the errors](#errors),
[logging](#logging), [what is public](#what-is-public) and [the stability promise](#stability).
The [README](../README.md) covers the command line and links the other guides: the
[console's commands](console.md), [running a show](running.md) and [how busk works inside](dev/internals.md).

## Installing

busk is not on PyPI. Install it from a checkout of its repository, at a release tag (or
without `--branch`, for `main`):

```bash
git clone --branch v0.1.0 https://github.com/lothwen/busk.git
uv add ./busk                       # into your uv project
uv add ./busk --extra midi          # with MIDI surfaces
pip install "./busk[midi]"
```

- **An install from a checkout builds busk from source**, so it fetches the build backend (`uv_build`)
  from the package index. On a machine without network access, install a wheel instead:
  `uv build` in a checkout writes `dist/busk-0.1.0-py3-none-any.whl`, and
  `pip install busk-0.1.0-py3-none-any.whl` installs it.
- **The `midi` extra** adds [`mido`](https://mido.readthedocs.io/) and `python-rtmidi`, for
  MIDI surfaces. Without it, busk works as before, except that each MIDI surface reports
  `MIDI s-…: unavailable: install busk[midi]` once and stays closed. On Linux, MIDI needs
  the ALSA sequencer (`/dev/snd/seq`). python-rtmidi 1.5.8 has wheels up to Python 3.12;
  on 3.13 and later, installing it builds it from source, which needs a C++ compiler and
  the ALSA headers.
- **Requirements:** Python 3.12 or later, `numpy` and `pydantic`. busk is tested on Linux
  with Python 3.12, 3.13 and 3.14. Other POSIX systems should work but are untested.
  Windows is not supported: the USB DMX driver needs `termios`.

The package also installs the `busk` command: `busk --version` prints `busk 0.1.0`.

## The examples

The examples below are tested: `tests/test_docs.py` runs every `>>>` line of this file.
They run in a checkout of the repository, where they read the show scripts in
`examples/` and the OFL files in `tests/fixtures/ofl/`, and write `club.show` in the
current directory.

## 1. Tooling: validate a show, import a profile

`load_show` reads a `.show` or `.json` file and validates it. It returns the show, a
`Show` (a `TypedDict` of the file format), and the validation warnings:

```python
>>> import busk
>>> show, warnings = busk.load_show("tests/fixtures/appendix_a.json")
>>> show["meta"]["title"], len(show["fixtures"]), warnings
('Club Night', 3, [])

```

An invalid show raises `ShowLoadError`, whose `issues` say what is wrong and where.
`validate_show` checks a document held in memory, and returns the issues instead:

```python
>>> from pathlib import Path
>>> _ = Path("broken.json").write_text('{"schemaVersion": 1, "meta": {"title": 7}}')
>>> try:
...     busk.load_show("broken.json")
... except busk.ShowLoadError as exc:
...     print(exc.issues[1])
meta.title: Input should be a valid string
>>> show, issues = busk.validate_show(Path("broken.json").read_text())
>>> show is None, issues[1].severity, issues[1].path
(True, 'error', 'meta.title')

```

`read_ofl` and `read_gdtf` convert a fixture profile to busk's format, as
`busk import` does. The report has the profile and notes about what the conversion
dropped or guessed:

```python
>>> report = busk.read_ofl("tests/fixtures/ofl/tupperdmx/moving-head.json", manufacturer="TupperDMX")
>>> report.profile["name"], [mode["name"] for mode in report.profile["modes"]]
('TupperDMX moving-head', ['12ch', '18ch'])
>>> len(report.notes)
4

```

`fixture add` finds profiles in a `ProfileLibrary`: the built-in profiles, plus any
directories of busk, OFL and GDTF profiles you give it. `find` takes an id or a name,
ignoring case. Files it cannot read are skipped, with one line each in `problems`:

```python
>>> library = busk.ProfileLibrary(["examples/tupperdmx/profiles"])
>>> library.find("tupperdmx moving head")["id"]
'prof-tdmx-mhead'
>>> len(library), library.problems
(10, [])

```

## 2. Build a show and render it: `OfflineShow`

`OfflineShow` runs a show on a clock you drive. It starts no thread, opens no socket
and writes only the files it is asked to. It takes console lines (`execute`), scripts
of console lines (`run_script`) and command dicts (`submit`), and `tick(t)` moves the
engine to time `t` and returns the frame it made.

```python
>>> busk.save_show(busk.new_show("Club Night"), "club.show")   # what `busk new` does
>>> show, _ = busk.load_show("club.show")
>>> offline = busk.OfflineShow(show, path="club.show", ids=busk.CounterIds())
>>> lines = offline.run_script("examples/club-night.busk")     # its last line, `save`, writes club.show
>>> lines[-1]
'saved club.show'
>>> offline.execute("fader 1 1")
Reply(text='', ok=True)
>>> frame = offline.tick(3.0)                                   # 3 s later
>>> list(frame.universes[1][:16])                               # universe 1's first 16 bytes
[128, 0, 128, 0, 140, 76, 0, 115, 204, 204, 128, 4, 11, 0, 0, 0]

```

`output` is the same tick read back per fixture element, in the show's units instead of DMX
bytes: intensity, colour, pan, tilt and zoom after the masters and the safety stage, and
what drives each family of attributes (`"programmer"`, `"playback"`, `"effect"` or
`"none"`). It lists every element of every fixture by number, a bar's cells one by one:

```python
>>> output = offline.output                                     # the tick above, per element
>>> output.seq == frame.seq, len(output.fixtures)               # 2 heads, 4 washes, 12 cells
(True, 18)
>>> head = output.fixtures[0]
>>> head.number, head.intensity, head.color, head.pan, head.zoom
(101, 0.8, (1.0, 0.75, 0.45), 0.0, 21.0)
>>> head.source["color"], head.source["position"], head.playback  # playback 1 drives it
('playback', 'none', 1)

```

`effects` lists the effect instances the tick ran, the playbacks' and the programmer's.
Each has the playback, cue and id that find it in the show (the programmer's have no
playback and no cue), how far it has faded in (`presence`), its `size` and its rate in
`hz` now, its `phase`, and the next cycle of its waveform (`wave`) or its colour cycle
(`colors`), sampled 20 times from now, for a sparkline:

```python
>>> _ = offline.execute("fader 11 1")                           # slot 11: the heads circle
>>> _ = offline.tick(3.5)                                       # half-way through its 1 s fade-in
>>> circle = offline.effects.effects[0]
>>> circle.playback, circle.cue, circle.id, circle.presence, circle.size, circle.hz
(11, '1', 'fx1', 0.5, 15.0, 1.0)
>>> [round(w, 2) for w in circle.wave[:6]], circle.colors
([1.0, 0.98, 0.9, 0.79, 0.65, 0.5], ())

```

`programmer` is the programmer as a display shows it: the selection as `(number, element)`
pairs in selection order, each value in the show's units (a preset reference with the
preset's value for that element, and the preset's pool, number and name), the effects as
the show file holds them, and `blind`, `highlight` and `fadeTime`. Its `version` grows
whenever any of that changes:

```python
>>> _ = offline.execute("sel fixture 101 thru 102, fixture 301.3")
>>> _ = offline.execute("preset color 2")                       # "Red", a global preset
>>> programmer = offline.programmer
>>> programmer.selection, programmer.blind
(((101, 1), (102, 1), (301, 3)), False)
>>> value = programmer.values[2]
>>> value.number, value.element, value.attribute, value.value, value.preset
(301, 3, 'color', {'r': 1.0, 'g': 0.0, 'b': 0.0}, ('color', 2, 'Red'))

```

**Commands happen now.** Each `execute`, `submit` and script line has taken effect when
the call returns, at the current engine time. Time moves only with `tick`, so a fade or
a chase stays where it was until then. `ids=busk.CounterIds()` makes the ids of new
universes, fixtures, cues and so on count up (`u-000000000001`, …) instead of being
random, so the same script builds the same show every time, which a golden test needs.

A refused command is not an exception: `execute` returns a `Reply` and `submit` a
`CommandResult`, whose `ok` is `False`:

```python
>>> offline.execute("go 99")
Reply(text='error: no playback 99', ok=False)
>>> result = offline.submit({"type": "BLACKOUT", "on": True})
>>> result.ok, offline.snapshot.blackout
(True, True)

```

`run_script` is the exception: it raises `ScriptError` at the first failing line. The
lines before it have run, and the ones after it have not:

```python
>>> _ = Path("broken.busk").write_text("gm 0.5\nfader 99 1\ngm 1\n")
>>> try:
...     offline.run_script("broken.busk")
... except busk.ScriptError as exc:
...     print(exc.line, exc.text)
2 fader 99 1

```

`show` is the document after the edits, and `save()` writes it (to `path`, unless given
another): it sets `meta.modified` and backs up the file it replaces.

## 3. Live, inside your own application: `LiveShow`

`LiveShow` runs the show in real time in your process: the engine and the DMX output as
threads, and, with `surfaces=True`, the show's control surfaces. It takes commands
like `OfflineShow`, but its engine ticks on its own (`engineHz` times a second), and
`snapshot`, `frame`, `output` and `effects` follow it. The engine reads its output back
only once something has read `output`: the first read turns that on and returns `None`,
and from the next tick on `output` is the newest tick's. `effects` works the same way, on
its own. A display polls them 10 to 20 times a second. `programmer` is not the engine's: a command has changed it when `execute`
returns, and a display polls it with the others.

`routes` is the show's output routes, in show order, each with what it does: `"ok"`
(open), `"failed"` (it does not open, or its sends fail; busk keeps trying), `"disabled"`
or `"ignored"` (a DMX-USB interface busk does not drive), with `detail` saying why, and
the packets and errors counted since it opened. It is `None` before `start()` and with
`output=False`. A display polls it with the others, shows a failed route in red and blinks
a route's light when `packets` changed; while nothing changes, the same object comes back:

```python
for route in live.routes or ():
    light = "red" if route.state == "failed" else "green" if route.state == "ok" else "grey"
    print(route.label, f"U{route.universe}", light, route.detail)   # sACN r1 U1 green
```

`surfaces` is the show's control surfaces, in show order, each with what it does: `"ok"`
(open: a MIDI controller connected, an OSC surface listening, a web remote serving),
`"failed"` (it is not open; a MIDI surface opens once its device is plugged in, the others
when an edit changes them), or `"ignored"` (`hid` and `internal` surfaces, which busk does
not implement), with `detail` saying why. An open web remote has the addresses to open on a
phone, key included, in `urls`. It is `None` before `start()` and with `surfaces=False`. It
follows live edits and MIDI devices plugged in and out; while nothing changes, the same
object comes back:

```python
for surface in live.surfaces or ():
    print(surface.name, surface.kind, surface.state, surface.detail, *surface.urls)
# nanoKONTROL2 midi failed unplugged; waiting for it
# Phone web ok  http://10.0.0.5:8080/?k=…
```

`confirmation(line)` is the yes/no question to ask before running `line`, the one `busk
run`'s prompt asks: `"Turn all DMX output off?"` before `output off`. It is `None` for a
line that runs at once: every other line, and a line that does not parse (`execute` says
why). `execute` never asks, as in a script, so a frontend asks first. The question is
text to show as it is. Asking changes nothing, and a frontend may ask from its own
thread:

```python
question = live.confirmation(line)
if question is None or dialog.yes_no(question):     # the frontend's own dialog
    reply = live.execute(line)
```

```python
show, _ = busk.load_show("club.show")
with busk.LiveShow(show, path="club.show", surfaces=True) as live:   # routes and surfaces open
    live.execute("gm 0.8")
    live.execute("go 1")
    ...                                       # the host application's own loop
# Leaving the block closes the surfaces, stops the engine, and the routes send Stream_Terminated.
```

`start()` (or entering the `with` block) opens the show's output routes and returns once
the engine has published its first snapshot. `stop()` (or leaving the block) closes the
surfaces, stops the engine, and the output sends the last frame and then ends the
streams. A `LiveShow` runs once. The example below is the tested one: `output=False`
opens no route, so nothing goes to the network; the frames are made all the same.

```python
>>> import time
>>> show, _ = busk.load_show("club.show")
>>> with busk.LiveShow(show, output=False) as live:
...     reply = live.execute("go 1")
...     time.sleep(0.5)                       # the engine applies it at its next tick
...     playback = live.snapshot.playbacks[0]
...     universe = live.frame.universes[1]
>>> reply.ok, playback.number, playback.state, len(universe)
(True, 1, 'active', 512)

```

> **`LiveShow` is not `busk run`.** It has no watchdog and no process isolation, so a crash
> or a long pause in your process stops or stalls the DMX output. It has no autosave, no
> crash recovery and no event log: save with `save()`. And it shares the interpreter with
> your code: on the reference rig, busk in one process overran 10 % of its engine ticks
> while the show was being edited, against 0.05 % in `busk run`'s three processes. For a
> show on stage, use `busk run`. `tune_interpreter=True` sets the interpreter's switch
> interval as `busk run` does (and restores it on `stop()`); it is off by default, because
> it changes a process-wide setting.

## Reference

The 36 names of `busk.__all__`. Each has a docstring with the details; path parameters
take `str` or `os.PathLike`.

| Name | What it is |
|---|---|
| `load_show` | `load_show(path) -> (Show, warnings)`: read and validate a `.show` or `.json` file |
| `save_show` | `save_show(show, path, *, now=None, backups=True) -> backup path or None`: write atomically, backing up the file it replaces |
| `new_show` | `new_show(title, *, cid=None, now=None, ids=None) -> Show`: the `busk new` template |
| `validate_show` | `validate_show(text) -> (Show or None, issues)`: validate a document held in memory |
| `read_ofl` | `read_ofl(path, *, manufacturer=None) -> ImportReport`: convert an Open Fixture Library profile |
| `read_gdtf` | `read_gdtf(path, *, manufacturer=None) -> ImportReport`: convert a GDTF file |
| `ProfileLibrary` | The built-in profiles plus directories of profiles, for `fixture add`: `get(id)`, `find(id or name)`, iteration, `problems` |
| `OfflineShow` | A show on a clock you drive: `submit`, `execute`, `confirmation`, `run_script`, `save`, `tick`; `show`, `warnings`, `snapshot`, `output`, `effects`, `programmer`, `time` |
| `LiveShow` | A show in real time in your process: as `OfflineShow`, with `start`, `stop` and `with`, `frame` instead of `tick`, `routes` and `surfaces` |
| `DmxFrame` | One engine output: `seq`, `time`, and `universes`, a mapping of universe number to 512 bytes |
| `Show` | The show file format, a `TypedDict` |
| `FixtureProfile` | The fixture profile format, a `TypedDict` |
| `Command` | The union of the command `TypedDict`s that `submit` takes, tagged by `type` |
| `Issue` | One validation finding: `severity` (`"error"` or `"warning"`), `path`, `message` |
| `CommandResult` | What `submit` and `save` return: `ok`, `message`, `issues` |
| `Reply` | What `execute` returns: `text`, `ok` |
| `ImportReport` | What `read_ofl` and `read_gdtf` return: `profile`, `notes` |
| `EngineSnapshot` | The engine's published state: grand master, blackout, playbacks, masters, page, tempo |
| `PlaybackStatus` | One playback in a snapshot: number, name, state, fader level, current cue |
| `SpeedStatus` | One speed master in a snapshot: BPM, multiplier, beat |
| `PageStatus` | The current page in a snapshot |
| `OutputSnapshot` | The output of one tick per fixture element: `seq`, `time`, `fixtures` |
| `FixtureOutput` | One element in it: `number`, `element`, `intensity`, `color`, `pan`, `tilt`, `zoom`, `source` (what drives each family), `playback` |
| `EffectSnapshot` | The effect instances one tick ran: `seq`, `time`, `effects` |
| `EffectStatus` | One instance in it: `playback`, `cue`, `id` (where it is defined), `presence`, `size`, `hz`, `phase`, `wave` and `colors` (its next cycle, 20 samples) |
| `ProgrammerStatus` | The programmer: `version`, `selection` (`(number, element)` pairs), `blind`, `highlight`, `fadeTime`, `values`, `effects` (as the show file holds them) |
| `ProgrammerValue` | One value in it: `number`, `element`, `attribute`, `value` (in the show's units), `preset` (`(pool, number, name)`, or `None`) |
| `RouteStatus` | One output route of a `LiveShow`: `id`, `label`, `universe` (its number), `state` (`"ok"`, `"failed"`, `"disabled"`, `"ignored"`), `detail` (why), `packets`, `errors` |
| `SurfaceStatus` | One control surface of a `LiveShow`: `id`, `name`, `kind`, `state` (`"ok"`, `"failed"`, `"ignored"`), `detail` (why), `urls` (a web remote's addresses) |
| `IdFactory` | The protocol that makes new entity ids |
| `CounterIds` | An `IdFactory` that counts: reproducible shows |
| `BuskError` | The base of every error the API raises on purpose |
| `ShowLoadError` | A show that is not a show, or does not validate: `issues` |
| `UnsupportedFeature` | A show that uses a feature busk cannot run yet |
| `ImportFailed` | A profile that cannot be imported (also a `ValueError`) |
| `ScriptError` | A script line that failed: `path`, `line`, `text`, `output` |

`busk.__version__` is the version, `"0.1.0"`.

## Errors

Every error the API raises on purpose is a `BuskError`:

```
BuskError(Exception)
├── ShowLoadError       .issues
├── UnsupportedFeature
├── ImportFailed        (also a ValueError)
└── ScriptError         .path .line .text .output
```

| Call | Raises |
|---|---|
| `load_show` | `ShowLoadError` (not a show, or validation errors), `OSError` |
| `save_show` | `OSError`; `ValueError` (the extension is not `.show` or `.json`) |
| `read_ofl`, `read_gdtf` | `ImportFailed`, also for a file that cannot be read |
| `validate_show`, `new_show`, `ProfileLibrary()` | nothing: issues and problems are returned |
| `OfflineShow()`, `LiveShow()` | `ShowLoadError`, `UnsupportedFeature` |
| `submit`, `execute`, `save` | nothing: the result has `ok=False` |
| `run_script` | `ScriptError`, `OSError` |
| `OfflineShow.tick` | `ValueError` (time going back) |
| `LiveShow.start` | `RuntimeError` (started before). Routes and surfaces that fail to open are logged and retried, as in `busk run` |

Wrong arguments raise `ValueError` or `TypeError`, never a `BuskError`.

## Logging

The library prints nothing. It reports through the loggers under `busk`: `busk.output`
(route lines such as `sACN r1: …`; `LiveShow.routes` has the same news as data),
`busk.surfaces` (surface lines, the web remote's
URL among them; `LiveShow.surfaces` has the same news as data), `busk.session` and `busk.eventlog`. News is INFO and failures are
WARNING. `busk` has a `logging.NullHandler`, so a program that configures no logging
sees none of it; `logging.basicConfig(level=logging.INFO)` shows it all.

## What is public

Public means:

- the names in `busk.__all__`, with their documented attributes and methods;
- the `TypedDict`s and type aliases of `busk.model.*` and `busk.commands.types`, which
  describe the show file and the commands.

Everything else is internal, whether or not its name starts with an underscore. The
internal modules stay where they are, and the `busk` command line uses them, but they
may change in any release. `import busk` itself is cheap: each public name is imported
the first time it is used.

## Stability

busk follows 0.x semantic versioning: a patch release (0.1.1) only fixes, and a minor
release (0.2.0) may break the public API, after a deprecation wherever possible.
Version 1.0 comes once another project has used busk through a release with no
breaking change. The changes are listed in [`CHANGELOG.md`](../CHANGELOG.md).

**Breaking**, within the public API:

- removing or renaming a public name;
- removing or renaming a parameter, reordering positional parameters, or removing a
  default;
- accepting narrower types, or changing a return type or its shape;
- raising an exception that is not a subclass of a documented one;
- removing or renaming a field of a public dataclass;
- removing a key from a show or command `TypedDict`, or making an optional key required
  (that also changes the file format: it comes with a `schemaVersion` bump and a
  migration);
- removing a command-line command or flag, or changing an exit code.

**Not breaking:** new names, new keyword arguments with defaults, new optional keys and
command types; any message text (command-line output, `Issue.message`, `Reply.text`,
log records); anything internal.

**Deprecating:** the old name or parameter warns with a `DeprecationWarning` and keeps
working for at least one minor release, with a "Deprecated" entry in the changelog.
