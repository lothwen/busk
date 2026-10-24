# Changelog

All notable changes to busk are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and busk follows 0.x
[semantic versioning](https://semver.org/): a patch release only fixes, and a minor
release may break the public API, after a deprecation wherever possible. What counts as
the public API, and as a breaking change, is in [the library guide](docs/library.md#stability).

## [Unreleased]

### Added

- `OfflineShow.output` and `LiveShow.output`: the engine's output read back per fixture
  element, as two new public types, `OutputSnapshot` and `FixtureOutput`
  ([the library guide](docs/library.md#2-build-a-show-and-render-it-offlineshow)). Each
  element has its intensity, colour, pan, tilt and zoom in the show's units, after the
  masters and the safety stage, what drives each family of its attributes (the
  programmer, a playback, an effect or nothing) and the playback that drives its
  intensity. A `LiveShow`'s engine reads its output back only once `output` has been read.
- `OfflineShow.effects` and `LiveShow.effects`: the effect instances the engine runs, the
  playbacks' and the programmer's, as two new public types, `EffectSnapshot` and
  `EffectStatus` ([the library guide](docs/library.md#2-build-a-show-and-render-it-offlineshow)).
  Each instance has its playback, the cue that defines it and its id, how far it has
  faded in, its size and rate now, its phase, and the next cycle of its waveform or its
  colours in 20 samples, for a sparkline. As with `output`, a `LiveShow`'s engine reads
  its effects back only once `effects` has been read.
- `OfflineShow.programmer` and `LiveShow.programmer`: the programmer as a display shows it,
  as two new public types, `ProgrammerStatus` and `ProgrammerValue`
  ([the library guide](docs/library.md#2-build-a-show-and-render-it-offlineshow)): the
  selection as fixture numbers and elements, each value in the show's units (a preset
  reference with the preset's value for that element, and its pool, number and name), the
  effects, blind, highlight and the fade time, and a `version` that grows when any of
  them changes.
- `LiveShow.routes`: the show's output routes as a display shows them, as a new public
  type, `RouteStatus` ([the library guide](docs/library.md#3-live-inside-your-own-application-liveshow)):
  each route's state (`ok`, `failed`, `disabled` or `ignored`), why it failed or is
  ignored, and the packets and errors it has counted. The same news as the `sACN r1: …`
  log lines, as data.
- `LiveShow.surfaces`: the show's control surfaces as a display shows them, as a new
  public type, `SurfaceStatus` ([the library guide](docs/library.md#3-live-inside-your-own-application-liveshow)):
  each surface's state (`ok`, `failed` or `ignored`), why it is not open (a MIDI device
  unplugged, a port in use, the `midi` extra missing), and a web remote's addresses. The
  same news as the `MIDI s-nano: …` log lines, as data.
- `OfflineShow.confirmation(line)` and `LiveShow.confirmation(line)`: the question the
  `busk run` prompt asks before a dangerous line (`Turn all DMX output off?` before
  `output off`), or `None` for a line that runs at once
  ([the library guide](docs/library.md#3-live-inside-your-own-application-liveshow)). A
  frontend asks the same without parsing the line; `execute` never asks.
- `OfflineShow.effect_templates` and `LiveShow.effect_templates`: the effect templates
  `effect add` takes, as a new public type, `EffectTemplateInfo`
  ([the library guide](docs/library.md#2-build-a-show-and-render-it-offlineshow)): the
  show's, then the built-in library's that the show has no copy of yet, each with the
  name `effect add` takes, its layers in one line and the library's defaults (size,
  low/high, phase). Before, the library's templates were only in the text of `library`.
- Fixture categories ([profiles](docs/profiles.md#categories)): a profile's optional
  `category` (`par`, `spot`, `wash`, `beam`, `pixel`, `strobe`, `blinder`, `dimmer`,
  `effect`, `fog` or `other`), for displays that group fixtures by kind. The built-in
  profiles have one, the OFL import takes the fixture's OFL category (a moving head is a
  `spot` with a gobo wheel, else a `wash`), and `profile "<name>" category <category>|none`
  sets or removes it in a show; `list profiles` shows it. It is a label: no profile gets a
  new revision for it, and `profile update` keeps the show's. GDTF files have no category.
- `PlaybackStatus.color` ([the library guide](docs/library.md#reference)): the colour of the
  cue a playback is at, for displays that draw a playback in the colour of its look. It is
  linear RGB, mixed as `FixtureOutput.color` is, of the brightest element whose colour the
  cue holds, tracked colours included; `None` while idle or when the cue holds no colour.
  The compiler works it out once per cue, so the fader, the masters and effects do not
  change it. The web remote's `state` messages have it too.
- `Reply.quit` ([the library guide](docs/library.md#3-live-inside-your-own-application-liveshow)):
  `True` in the reply of `quit` or `exit`, and of a `source` whose script stops at a `quit`,
  the lines after which the `busk run` prompt ends. `execute` still stops nothing, so a
  frontend ends when its user quits, or asks first, without matching the typed line.
- `busk run --frontend MODULE:FUNCTION` ([Running a show](docs/running.md#frontends)):
  your own frontend instead of the prompt, called with the run's `LiveShow` in the
  console process, with `busk run`'s safety net (the engine in its own process, the
  watchdog, autosave and recovery). The run ends when the function returns; one that
  raises is restarted with the console while the output runs on. While it runs, busk
  prints nothing over it: its lines are records of the new `busk.run` logger.
- `busk run`'s show now has `frame`, `output` and `effects` too, from the engine process,
  which captures the output and effects only while they are read, at most 25 times a
  second.
- A `LiveShow` may be used from several threads at once, as documented
  ([the library guide](docs/library.md#3-live-inside-your-own-application-liveshow)).
  Lines from different threads run as if one after the other, a script whole, except
  performance lines (`go`, `fader`, `gm` …), which never wait for another thread's line:
  a frontend's controls are not held up by an edit, a `save` or a script.
- Console lines for playback buttons ([the console](docs/console.md#notes)): `flash N
  on|off` holds a playback's flash until it is released, `button N B on|off` presses and
  releases its button B as a bound control does, and `toggle N` activates or releases it.
  A frontend's buttons, and the `busk run` prompt, no longer need a controller or the
  web remote for these.
- Relative and per-component values ([the console](docs/console.md#notes)): `set
  <attribute> by <change>` adds to what the programmer holds for each selected target
  (`set intensity by 5%`, `set pan by -15`), and `set color.r 50%` or `set color.r by 10%`
  sets or changes one colour component, keeping the others. Targets with nothing in the
  programmer for that attribute are skipped. Library users and bindings have the new
  command type `ADJUST_ATTRIBUTE`.
- Stopping a programmer effect ([the console](docs/console.md#notes)): `effect stop fx1`
  stops it and keeps it in the programmer, with its settings, and `effect run fx1` runs it
  again. It fades out and back in over the programmer's fade time, as removing and adding
  it would, and `record cue` leaves a stopped effect out. `programmer` marks it
  `(stopped)`, and `ProgrammerStatus.stopped` lists the stopped ids. Library users and
  bindings have the new command type `RUN_EFFECT`.
- Tab completion and `?` at the console prompt ([the prompt](docs/console.md#the-prompt)).
  Tab completes commands, keywords and names in quotes, and lists what may come next. `?`
  prints that and the forms of the command. Both follow the parser, the show and the
  libraries.
- The web remote ([the web remote](docs/surfaces.md#the-web-remote)): tap the page name to
  choose a page from a list; a stack's strip shows the cue GO goes to next; a red OUTPUT
  OFF bar shows while `output off` holds. The `show` message lists each playback's `cues`
  (number and name).
- Colour macros: the attributes `colorMacro` (a fixture's built-in colour presets and
  programs), `colorEffect` (its colour effects) and `colorMacroRate` (how fast they run),
  in the `color` family ([attributes](docs/console.md#attributes)). Uncontrolled, a
  fixture outputs the option its own default selects.
- Tab completes the options of a discrete attribute after `set` and `park`, from the
  selected or named fixtures.
- Fixture effects: the attributes `effect` and `effect2` (the programs built into a
  fixture: an LED bar's animations, a blinder's auto program), `effectRate`,
  `effectFade`, `effectAdjust`, `effectRotation`, `effectSync` and `soundSensitivity`, in
  the `beam` family ([attributes](docs/console.md#attributes)). Uncontrolled, a fixture
  outputs the program its own default selects, and its own speed and parameters.

### Changed

- The OFL import maps `ColorPreset` to `colorMacro` and `ColorJump`/`ColorFade` programs
  to `colorEffect`; the GDTF import maps `ColorMacro1`, `ColorMacro1Rate` and
  `ColorEffects1` ([importing](docs/profiles.md#importing-ofl-and-gdtf-files)). These
  channels were `control` channels held at their default. A few channels change
  attribute: three OFL "Color Macro / Temperature" channels were `cto`, and GDTF
  channels whose logical attribute is `ColorMacro1` but whose functions are a colour
  wheel's (Robe's virtual colour wheels) were `colorWheel`.
- The OFL import maps `Effect`, `EffectSpeed`, `EffectDuration`, `EffectParameter` and
  `SoundSensitivity` on channels where nothing else maps; the GDTF import maps
  `Effects1`, `Effects2`, `Effects1Rate`, `Effects1Fade`, `Effects1Adjust1`,
  `Effects1PosRotate` and `EffectsSync` ([importing](docs/profiles.md#importing-ofl-and-gdtf-files)).
  These channels were `control` channels held at their default.
- Maintenance ranges (resets, lamp switching, settings) are never an option: colour macro
  and effect channels drop them (Fun Generation's Pico macros lose `reset`), and such a
  channel whose default selects one stays `control`.
- `colorMacroRate` starts at its channel's own default instead of 0.5, as the new rates
  do; a rate that is only a program's parameter still starts at 0.5.
- Imported profiles get a new revision: the importer's version is part of it (version 3
  with the fixture effects), so a show that embeds an older import can take the new one
  with `profile update`.

- Ctrl+C at the console prompt: on an empty line it now says how to quit, and a second
  Ctrl+C in a row quits like `quit`. Ctrl+C on a typed line still only clears it.
- `set <attribute> +5%`, with a plus sign, is refused, and the error shows the two lines
  you may have meant. It used to set 5%, a near blackout for someone who meant a change.

### Fixed

- Lines from two threads: a line parsed while another thread's edit was still being
  made could fail where it would have worked a moment later (two `effect add` of a
  template the show did not have yet), `list masters` and `list cues` could raise when
  another thread deleted what they listed, and a Ctrl+C on the main thread could be raised
  in another thread whose line ended first, or stop that thread's script.
- After a `quit` line on an `OfflineShow` or a `LiveShow`, the next `source` line or
  `run_script` ran only the first line of its script, and said nothing about it.
- The web remote on a phone held sideways: the strips were squeezed until their names
  vanished and their buttons spilled out. The header now takes one row, each fader sits
  beside its buttons, and the masters open with a **Masters** button.
- The web remote showed a TAP button that did nothing in a show without a speed master
  that takes taps.

## [0.1.0] - Unreleased

The first release with a public API. Phases 0–7 built the console and its `busk` command
line; Phase 8 ([plan](docs/plans/phase-8-plan.md)) made it a library too.

### Added

- **The public API**: 28 names, all importable from `busk` (see `busk.__all__` and
  [`docs/library.md`](docs/library.md)):
  - show documents: `load_show`, `save_show`, `new_show`, `validate_show`;
  - fixture profiles: `read_ofl`, `read_gdtf`, `ProfileLibrary`;
  - running a show: `OfflineShow` (frames on a clock the caller drives) and `LiveShow`
    (the engine, the DMX output and optionally the surfaces as threads in the caller's
    process), with `DmxFrame`;
  - data types: `Show`, `FixtureProfile`, `Command`, `Issue`, `CommandResult`, `Reply`,
    `ImportReport`, `EngineSnapshot`, `PlaybackStatus`, `SpeedStatus`, `PageStatus`,
    `IdFactory`, `CounterIds`;
  - errors: `BuskError`, the base of `ShowLoadError`, `UnsupportedFeature`,
    `ImportFailed` and the new `ScriptError`.
- `import busk` is cheap: the public names load lazily, on first use.
- The library prints nothing: it reports through the `busk.*` loggers, and `busk` has a
  `NullHandler`.
- The `midi` extra, `busk[midi]`, for MIDI surfaces (`mido`, `python-rtmidi`).
- The MIT license.
- The library guide, [`docs/library.md`](docs/library.md), whose examples are tested.
- [`examples/club-night.busk`](examples/club-night.busk): the demo show in one script (the
  rig, looks, a song, a chase, effects, two pages, a phone remote, LEDs and safety), with
  the controller's layout in its header.

### Changed

- `mido` and `python-rtmidi` are no longer installed by default. Without the `midi`
  extra, each MIDI surface reports `MIDI s-…: unavailable: install busk[midi]` once and
  stays closed; everything else works.
- `ShowLoadError`, `UnsupportedFeature` and `ImportFailed` now derive from `BuskError`.
  Their names, modules and attributes are unchanged, and `ImportFailed` is still a
  `ValueError`.
- Friendlier signatures, all additive: `save_show`'s `now` and every keyword of
  `new_show` (`cid`, `now`, `ids`) have defaults, and `new_show` with no `cid` touches no
  state directory. Path parameters take `str` as well as `os.PathLike`.
- The lowest supported dependency versions were lowered to what the test suite passes
  with: `numpy>=2.3.2`, `pydantic>=2.12.4`, `mido>=1.3.0`.
- The per-phase example scripts (`phase3-build.busk` … `phase7-safety.busk`), the Phase 1
  values file and the Phase 2 demo moved from `examples/` to `tests/fixtures/`;
  `examples/phase1-demo.json` is now `examples/real-fixtures.json`.
- Art-Net binds UDP 6454 only while a broadcast route is open, since only broadcast routes
  use discovery. A show whose Art-Net routes are all unicast sends from another port, so
  a receiver on the same machine, such as a visualiser, can start before or after busk;
  it no longer prints `Art-Net: cannot listen on UDP port 6454 …`, and it answers no
  ArtPolls.

The command line is otherwise unchanged: every command, flag, exit code and output line
is the same as before Phase 8.

[Unreleased]: https://github.com/lothwen/busk/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/lothwen/busk/releases/tag/v0.1.0
