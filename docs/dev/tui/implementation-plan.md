# busk TUI: implementation plan

A terminal UI for busk, in a new package `src/busk_tui/`, shipped in the busk distribution
behind the `tui` extra (`pip install busk[tui]`) with its own command, `busk-tui`. Tests in
`tests/tui/`. Written 2026-10-21 against busk 0.1.0 (`3176f99`).

**Updated 2026-10-24** for the engine work the first version asked for: GAP-01 … GAP-21 of
[`engine-gaps.md`](engine-gaps.md), built from `f0e0289` to `dc5922c`. 18 of the 21 gaps are
closed, and the plan now uses what they built. Three are open: GAP-03 (session state), GAP-06
(one undo step for a gesture) and GAP-13 (control input monitor). Each phase's **Deferred** list
names what they still block.

Inputs: the TUI specification and the HTML mockup (`busk_tui-specification.md` and
`Busk_TUI_mockup.html`, next to this plan; the spec's `images/` are not in the repo) and the
engine as it is. Companion document: [`docs/dev/tui/engine-gaps.md`](engine-gaps.md), with each
gap and, for a closed one, a **Done** note on what was built.

**The engine comes first.** The spec and the HTML prototype describe the intended look and
workflow. Where they differ from busk (command syntax, attribute names, how cues, pages, effects
and presets work), the TUI follows busk, and §3 lists each adaptation. The prototype's own logic
(undo snapshots, tap tempo, the output computation, a MIDI echo) belongs to its fake engine. The
TUI gets all of that from busk.

How to use this plan: phases are built in order, one at a time. When a step is done, add a
**Done** note under it with the deviations, as the other plans in `docs/plans/` do. Questions
for the user are in §9. Answers may change the phases.

---

## 1. Ground rules

### 1.1 What the brief means in busk terms

- **"The engine"** is the `busk` package. **Its public interface** is `busk.__all__` (39
  names; 28 at 0.1.0) and the `TypedDict`s of `busk.model.*` and `busk.commands.types`
  (`docs/library.md`, "What is public").
- **`execute(command)`** is `LiveShow.execute(line: str) -> Reply`. busk has no type named
  `Result`: `execute` returns `Reply(text, ok, quit)` and never raises. A refused line has
  `ok=False` and text starting `error: `. Performance lines (`go`, `fader`, `gm`, …) succeed with
  empty text. `quit` is true when the line asked to end the run: `quit`, `exit`, or a `source`
  whose script stops at one (GAP-18). `execute` is safe from several threads, and a performance
  line never waits for another thread's line (GAP-12). `submit(command) -> CommandResult(ok,
  message, issues)` also exists, but the TUI does not use it: every action is a console line,
  echoed in the log, so the UI teaches the CLI (spec §2.1).
- **Reads.** The brief says the engine only offers request and response through `execute()`. It
  also has typed, read-only public state, published by reference and safe to read from any
  thread:
  - `LiveShow.snapshot -> EngineSnapshot`: playbacks (with the colour of their current cue,
    GAP-17), masters, tempo anchors, page, blackout, output on/off, fade-time override. It is
    republished on every change, chase steps included.
  - `LiveShow.frame -> DmxFrame`: the newest frame, with its engine `time` and `seq`.
  - `LiveShow.output -> OutputSnapshot` (GAP-01): each fixture element's intensity, colour, pan,
    tilt and zoom, and what drives each family, every tick.
  - `LiveShow.effects -> EffectSnapshot` (GAP-09): the effects that run at a tick, with their
    presence, size, rate, phase and the samples of their next cycle.
  - `LiveShow.programmer -> ProgrammerStatus` (GAP-02, GAP-14): selection, blind, highlight,
    fade time, values (a preset with its value), effects and which of them are stopped, with a
    `version`.
  - `LiveShow.routes -> tuple[RouteStatus, ...]` (GAP-07) and `LiveShow.surfaces ->
    tuple[SurfaceStatus, ...]` (GAP-08): the state of each output route and control surface.
  - `LiveShow.health -> EngineHealth` (GAP-21): `starting`, `running`, `stalled`, `stopped`, and
    under `busk run` also `restarting` and `failed`, with tick and overrun counts.
  - `LiveShow.show -> Show`: the committed show document, profile categories included (GAP-16).
    It is replaced, not mutated, on every edit. With it, `LiveShow.effect_templates` (GAP-15):
    every template `effect add` takes, the show's and the library's.
  - Two questions about a line, answered from published state without running it:
    `LiveShow.confirmation(line)` (GAP-10), the question to ask before it, and
    `LiveShow.expected(line)` (GAP-20), what may come where the word being typed starts.
  - `LiveShow.warnings`, and the `busk.*` loggers for route, surface and run news.

  `output` and `effects`, and under `busk run` also `frame`, are captured once someone reads
  them: the first read returns `None`, like a read before the first tick.

  The plan reads these instead of polling text commands (question Q1). Read-only commands
  (`programmer`, `info`, `list …`, `library`, `status`) can also be run through `execute()`, but
  their replies are text. `docs/library.md` says message text may change in any release, so **the
  TUI never parses reply text**. It shows it verbatim where that is useful (`help`, a typed
  query), and treats data only available as text as a gap. Since GAP-02, that leaves only the
  session state that `info` prints: undo depth and unsaved edits (GAP-03, question Q2).
- **The host.** The TUI runs under `busk run SHOW --frontend busk_tui.app:frontend` (GAP-11).
  `busk run` keeps the engine and the output in processes of their own, with the watchdog,
  autosave, crash recovery and the event log, and calls the TUI on its console process's main
  thread with the run's `LiveShow`, already started. `busk-tui SHOW` starts that run. For
  development and rehearsal, `busk-tui --standalone SHOW` builds a `LiveShow` in the TUI's own
  process instead (question Q5). The bridge gets the same `LiveShow` API either way.

### 1.2 The boundary

- `src/busk_tui/bridge.py` is the only module that imports `busk`, and it imports only names in
  `busk.__all__`. `app.py` starts `busk run` as a command and hands the show it is given to the
  bridge, without importing busk. A test checks this (Phase 0).
- The bridge turns engine objects into the TUI's own frozen view models (`model.py`, no busk
  types). Pages and widgets see only those, and talk to the bridge through a small protocol, so
  tests can swap in a fake.
- **No engine logic in the TUI.** The TUI may format public data, look things up by id or
  number (a `RouteStatus` to its route, an `EffectStatus` to its cue's entry), and do arithmetic
  on public data (a fixture's DMX footprint is `address … address + footprint − 1`; a packet
  rate from two `packets` counts). It may compute a command's argument from a displayed value
  (fader +5 %). It must not resolve looks (priorities, presets per fixture, tracking), decode
  DMX, compute waveforms or tap tempo, or extract data from reply text. A display that needs one
  of those is a gap.
- Outside `src/busk_tui/`, `tests/tui/` and docs, the only change is `pyproject.toml`: the `tui`
  extra and the `busk-tui` script. Packaging needs one more table (question Q3). Nothing in
  `src/busk/` or the engine tests changes. What the TUI needs from the engine is a gap in
  `engine-gaps.md`, built as engine work of its own, as GAP-01 … GAP-21 were.

---

## 2. Engine capability mapping

Every feature, control and displayed value of the spec, mapped to busk. Each one was checked
against `OfflineShow` with `examples/club-night.busk` on 2026-10-21. The rows the closed gaps
changed follow their **Done** notes: the GAP-NN in a busk cell names the gap that added it. The
Gap column lists only open gaps.

**Class:** **S** supported, **P** partially supported, **N** not supported.
**Live source:** where a changing value comes from, and so how it is polled:

| Source | How it is read | Rate | Change detection |
|---|---|---|---|
| `snap` | `LiveShow.snapshot` (typed) | 20 Hz | `seq` |
| `frame` | `LiveShow.frame` (typed): engine `time`, `seq` | 20 Hz | `seq` |
| `out` | `LiveShow.output` (typed), only while a page that shows it is visible | 10 Hz (Phase 2) | `seq` |
| `fx` | `LiveShow.effects` (typed), only while a page that shows it is visible | 20 Hz | `seq` |
| `prog` | `LiveShow.programmer` (typed) | 20 Hz | `version` |
| `route` | `LiveShow.routes` (typed); `None` without output | 20 Hz | identity; `packets` for the blink |
| `surf` | `LiveShow.surfaces` (typed); `None` without surfaces | 20 Hz | identity |
| `health` | `LiveShow.health` (typed) | 20 Hz | `state`; counts compared over ≥ 1 s |
| `doc` | `LiveShow.show` (typed document), and `LiveShow.effect_templates` with it | identity check at 20 Hz, and after every successful line | identity |
| `ask` | `LiveShow.confirmation(line)`, before a line is sent | per line | n/a |
| `exp` | `LiveShow.expected(line)`, with the line up to the cursor | on Tab and as the line changes | n/a |
| `reply` | the `Reply` of a line the TUI sent | per line | n/a |
| `query` | a read-only line through `execute()` (`help`, once at start); text only, never parsed | on demand | n/a |
| `log` | records of the `busk.*` loggers (`busk.run` under `busk run`) | pushed | n/a |
| `UI` | the TUI's own state | n/a | n/a |
| — | not available | n/a | n/a |

A new `seq` is one that differs from the last, not a greater one: after an engine restart under
`busk run`, `seq` counts from 1 again (GAP-11). `out` and `fx` are read only while a page shows
them, because building the `FixtureOutput`s costs the reading thread 10–11 ms on the reference
rig's 8 192 elements (GAP-01).

### 2.1 Frame, prompt and global input (spec §5–§7)

| Spec item | busk | Class | Live source | Gap |
|---|---|---|---|---|
| Show name | `show.meta.title` | S | `doc` | |
| Network TX per route | `LiveShow.routes` (GAP-07): `state` (ok, failed, disabled, ignored), `detail`, and `packets`, which grows while the route sends; matched to `show.output.routes` by `id` | S | `route` | |
| `GM %` (amber < 100) | `EngineSnapshot.grandMaster` | S | `snap` | |
| `BPM` and beat dot | `SpeedStatus.bpm`; beat = `SpeedStatus.beats(frame.time)` (public method) | S | `snap` + `frame` | |
| `FADE` | the programmer's fade, `ProgrammerStatus.fadeTime` (GAP-02). The fade-time master override, `EngineSnapshot.fadeTime`, shows on F7 | S | `prog` | |
| `PROG n` | the fixtures with a value: distinct numbers in `ProgrammerStatus.values` (GAP-02) | S | `prog` | |
| BLIND chip | `ProgrammerStatus.blind` (GAP-02) | S | `prog` | |
| BLACKOUT chip | `EngineSnapshot.blackout` | S | `snap` | |
| *(busk)* output off (panic) | `EngineSnapshot.outputEnabled` | S | `snap` | |
| *(busk)* current page | `EngineSnapshot.page` | S | `snap` | |
| *(busk)* engine health | `LiveShow.health` (GAP-21): the state, and the overruns of two reads ≥ 1 s apart | S | `health` | |
| Clock | n/a | S | `UI` | |
| Log: `busk>` / `ui>` echo | n/a | S | `UI` | |
| Log: result and error lines | `Reply.text`, `Reply.ok` | S | `reply` | |
| Log: info lines | TUI messages, plus `busk.*` log records shown verbatim (under `busk run`, `busk.run`: what it would print, GAP-11) | S | `log` | |
| Prompt context `sel n` | `len(ProgrammerStatus.selection)` (GAP-02) | S | `prog` | |
| Prompt context `P1` | selected playback, TUI state | S | `UI` | |
| Prompt context `undo n` | `info` text only | P | — | GAP-03 |
| Syntax hint (§7.2) | the `help` lines of the first word (top-level lines have a 4-space indent), and `expected(line)` (GAP-20): the next words, `<values>`, `<Enter>` or `error: …`, as `busk run`'s `?` shows them | S | `query` once, `exp` | |
| Tab completion | `expected(line)` (GAP-20): one word replaces `line[start:]`, followed by a space; several go to the log | S | `exp` | |
| History ↑ ↓, Esc, Enter | n/a | S | `UI` | |
| Space → `go N` | `go N` | S | | |
| ← → select playback | the current page's slots | S | `snap`, `doc` | |
| `[` `]` → fader ±5 % | `fader N 72%`, current level `PlaybackStatus.faderLevel` | S | `snap` | |
| Shift-click toggles in/out | `sel + fixture N` or `sel - fixture N`, by whether the fixture is in `ProgrammerStatus.selection` (GAP-02) | S | `prog` | |
| Drag faders and masters | `fader`, `gm`, `master`: performance commands, never on the undo timeline | S | | |
| Drag encoders, one undo step | each `set` is one undo step; nothing groups them | P | | GAP-06 |
| Wheel on faders and masters | `fader`/`master` with the current level | S | `snap` | |
| Wheel and `[−]`/`[+]` on encoders | `set <attr> by <change>`, `set color.r by <change>` (GAP-05), where the programmer holds the attribute (question Q11) | S | `prog` | |
| FLASH (momentary) | `flash N on` on mouse down, `flash N off` on mouse up (GAP-04) | S | | |
| Undo / redo (§6.3) | `undo`, `redo` (the engine keeps 1000 steps) | S | | |
| `quit` | any line whose `Reply.quit` is true (GAP-18): `quit`, `exit`, a sourced script's `quit` | S | `reply` | |
| Confirmation before `output off` | `confirmation(line)` (GAP-10), asked before each line the TUI sends (§4.3) | S | `ask` | |
| Help overlay content (§8.10) | `help` | S | once | |

### 2.2 F1 Busk (spec §8.1)

| Spec item | busk | Class | Live source | Gap |
|---|---|---|---|---|
| Header `page 1` | `EngineSnapshot.page` (number, name) | S | `snap` | |
| `playbacks 1–N` (4–20) | the slots of the current page (`show.pages[].slots`), playbacks by number when the show has no page | S | `doc`, `snap` | |
| Header `sel …` | `ProgrammerStatus.selection` (GAP-02), compressed as the spec shows it (`1 thru 8, 17.3`) | S | `prog` | |
| `Pn`, name | `PlaybackStatus.number`, `.name` | S | `snap` | |
| Cue position `cur/total`, or `chase n` | `.cue`, `.cueCount`, `.chase`; position = index of the cue number in its list | S | `snap`, `doc` | |
| Current cue name | `.cueName` | S | `snap` | |
| Next cue name | `.next` (cue number), name from the list | S | `snap`, `doc` | |
| Chase rate and direction | `cueList.chase` (`bpm` master × multiplier, or Hz; direction) | S | `doc` | |
| Level | `.faderLevel`, meaning given by `.fader` (master, crossfade, rate, size, temp, none) | S | `snap` | |
| Colour = current cue colour | `PlaybackStatus.color` (GAP-17); `playback.uiColor` while it is `None` | S | `snap`, `doc` | |
| Empty slots `·` `—` | `None` in `page.slots` | S | `doc` | |
| Fader drag, wheel, `[ ]` | `fader N <p>%` | S | | |
| GO, ◂ | `go N`, `back N` | S | | |
| FLASH (hold) | `flash N on\|off` (GAP-04), see §2.1 | S | | |
| `Pn` click | TUI state | S | `UI` | |
| Fixture swatch click | `sel fixture N`; Shift: `sel + fixture N` or `sel - fixture N` (§2.1) | S | `prog` | |
| Colour chip | `preset color N` | S | `doc` | |
| Group button | `sel group N`; Shift: `sel + group N` | S | `doc` | |
| Master bars | `gm <p>%`, `master "<name>" <p>%`; levels `EngineSnapshot.masterLevels` | S | `snap`, `doc` | |
| `[TAP]` | `tap "<name>"` | S | | |
| `[B.O.]` / `[BLACKOUT]` toggle | `blackout on\|off`; state `EngineSnapshot.blackout` | S | `snap` | |
| A: OUTPUT colours and levels | `LiveShow.output` (GAP-01): `FixtureOutput.intensity` and `.color`, one cell per element | S | `out` | |
| A: one row per fixture type | the profile's `category` (GAP-16); a profile with none has a row of its own | S | `doc` | |
| A: PROGRAMMER summary | `ProgrammerStatus` (GAP-02) | S | `prog` | |
| B: TEMPO `[−]` `[+]` | `bpm "<name>" <n>` | S | `snap` | |
| B: EFFECTS rows | the effects that run (GAP-09), and the programmer's stopped ones (GAP-14); settings from the cue's entry in the document or from `ProgrammerStatus.effects` (GAP-02), in the same format | S | `fx`, `prog`, `doc` | |
| B: sparkline, RUN/off | `EffectStatus.wave`, `.colors`, `.presence` (GAP-09); a programmer effect is off while its id is in `ProgrammerStatus.stopped` (GAP-14) | S | `fx`, `prog` | |
| B: RUN/off click | cue effect: its playback, `go N` / `release N`; programmer effect: `effect stop <id>` / `effect run <id>` (GAP-14) | S | | |
| C: fixture positions | `fixture N location {"x":…,"y":…,"z":…,"rx":0,"ry":0,"rz":0}`, then `fixture N location.x <m>`. The spec's `plot.row` is refused (`no key 'plot'`) | S | `doc` | |
| C: pan arrow and tilt | `FixtureOutput.pan`, `.tilt` (GAP-01), in the show's coordinates (before inversion and offsets) | S | `out` | |
| C: glyph per type | the profile's `category` (GAP-16) | S | `doc` | |

### 2.3 F2 Program (spec §8.2)

| Spec item | busk | Class | Live source | Gap |
|---|---|---|---|---|
| Selection text and count | `ProgrammerStatus.selection` (GAP-02) | S | `prog` | |
| `[N Name]` group buttons, `[none]` | `sel group N`, `sel + group N`, `sel none` | S | `doc` | |
| Encoder families | busk attributes, by the families of its registry: `intensity`; `pan`, `tilt`; `color` by component (`color.r`, `.g`, `.b`, `.w`, GAP-05), `cto`; `zoom`, `iris`, `frost`; `focus`; `shutter`, `strobeRate`. The spec's `dim`, `red`…`white` and `strobe` are not busk attributes (`unknown attribute 'dim'`) | S | `doc` | |
| Encoder value of the first selected fixture: programmer (magenta) or output (dim) | `ProgrammerValue.value` (GAP-02; a preset counts with its value) / `FixtureOutput` (GAP-01). The output has intensity, pan, tilt and zoom, and the colour mixed as RGB, so the component rows show it as one swatch; the other attributes have no output value | S/P | `prog` / `out` | |
| `[−]` `[+]`, wheel | `set <attr> by <change>` (GAP-05): ±5 % (±15°), the wheel ±2 % (±5°); only where the programmer holds the attribute (question Q11) | S | `prog` | |
| Drag → `set` | `set <attr> <value>`, absolute; range from the profile (`physical.panRange`, `tiltRange`, `zoomRange`, `maxStrobeHz`), else 0..1 | S | `doc` | GAP-06 |
| Red, green, blue, white rows | `set color.r\|g\|b\|w <value>`, and `by <change>` (GAP-05), the other components kept | S | `prog` | |
| `quick` row | lines exist, in busk syntax (§3) | S | | |
| `blind on\|off` toggle | `blind on` or `blind off`, by `ProgrammerStatus.blind` (GAP-02) | S | `prog` | |
| PROGRAMMER CONTENTS table | `ProgrammerStatus.values` by fixture, a preset by its name (GAP-02) | S | `prog` | |

### 2.4 F3 Fixtures (spec §8.3)

| Spec item | busk | Class | Live source | Gap |
|---|---|---|---|---|
| `#`, name, profile, `×N`, mode, patch `U.A` (red `—` unpatched) | fixtures, profiles, `mode.elements`, `mode.footprint`, `patch`, `elementPatch`, universes | S | `doc` | |
| dim, colour, pan, tilt, zoom (live) | `FixtureOutput` (GAP-01) | S | `out` | |
| Source colouring, legend | `FixtureOutput.source` by family (GAP-01): programmer, playback, effect, none | S | `out` | |
| `▸` selected marker | `ProgrammerStatus.selection` (GAP-02) | S | `prog` | |
| Row click, Shift-click | `sel fixture N`; Shift: `sel + fixture N` or `sel - fixture N` | S | `prog` | |

### 2.5 F4 Cues (spec §8.4)

| Spec item | busk | Class | Live source | Gap |
|---|---|---|---|---|
| CUELISTS: number, name, kind, cue count | `cueLists[]`: kind is `sequence` or `chase` (flash is a playback button, not a list kind) | S | `doc` | |
| Meta: mode | `mode`, `chase` (rate, direction, crossfade) | S | `doc` | |
| Meta: playback and level | playbacks with this `cueListId`, level from the snapshot | S | `doc`, `snap` | |
| Meta: groups | the groups and fixtures the cues' entries target | S | `doc` | |
| `▶` current cue | `PlaybackStatus.cue` of the list's playback | S | `snap` | |
| L/C, name, in/out, delay, curve, follow, wait | `cue.number`, `name`, `timing`, `trigger` | S | `doc` | |
| dim, colour | the cue's own entries as stored: literal value, preset name, `spread`, `per target` | S | `doc` | |
| fx | `cue.effects[].id` | S | `doc` | |
| Row click → go to that cue | spec: `cue L/C go`. In busk that line **sets the cue's trigger to GO** (a show edit). Going to a cue is `goto N <cue>` on the list's playback | S | | |
| `[GO]` `[BACK]` | `go N`, `back N` | S | | |
| `[record cue L]` | `record cue L` (appends a cue) | S | | |
| Sequence/chase toggle | `cuelist L sequence`, `cuelist L chase bpm x 1`. The spec's `x1` is refused (`unexpected 'x1'`) | S | | |
| Cell editing | prompt pre-fill: `cue L/C time `, `follow `, `wait `, `go` | S | | |

### 2.6 F5 Effects (spec §8.5)

| Spec item | busk | Class | Live source | Gap |
|---|---|---|---|---|
| Table: template, fixtures, rate, size, phase, wings, direction (cue effects) | `cue.effects[]`: `templateId`, `targets`, `rate`, `size`, `phase`, `groups`, `blocks`, `wings`, `direction` | S | `doc` | |
| Programmer effects (ids like `fx5`) | `ProgrammerStatus.effects` (GAP-02), in the format of a cue's `effects`, so one formatter serves both | S | `prog` | |
| `wave` sparkline, `state` | `LiveShow.effects` (GAP-09): `RUN` when the row's `(playback, cue, id)` or programmer `id` is listed, dimmed while `presence` < 1, else `off`; heights from `wave`, hues from `colors`; the live rate `hz` | S | `fx` | |
| State click | cue effect: its playback `go N` / `release N`; programmer effect: `effect stop <id>` / `effect run <id>` (GAP-14), `off` while its id is in `ProgrammerStatus.stopped` | S | `snap`, `prog` | |
| `✕` | `effect remove <id>` (programmer effects) | S | | |
| TEMPLATES: the show's | `LiveShow.effect_templates` (GAP-15), `source` `"show"`: name, `summary`, the defaults it has | S | `doc` | |
| TEMPLATES: built-in library | the same tuple, `source` `"library"`: the library's templates the show has no copy of | S | `doc` | |
| Template click | `effect add "<name>"`, with the library's defaults (the spec's `bpm x1 size 0.6` is refused and invents values) | S | | |

### 2.7 F6 Presets (spec §8.6)

| Spec item | busk | Class | Live source | Gap |
|---|---|---|---|---|
| "applies to" the selection | `ProgrammerStatus.selection` (GAP-02) | S | `prog` | |
| Pools | `presets[]`, six pools: intensity, position, color, beam, focus, all | S | `doc` | |
| Tile preview | the preset's stored values: shown when every value of that attribute is the same, else `mixed` | S | `doc` | |
| Tile click | `preset <pool> N` | S | | |
| Recording, new tiles at once | `record preset <pool> N "name"`; the document changes | S | `doc` | |

### 2.8 F7 Masters (spec §8.7)

| Spec item | busk | Class | Live source | Gap |
|---|---|---|---|---|
| GRAND MASTER digits, bar, red on blackout | `masterLevels` (the grand master's own level), `blackout` | S | `snap` | |
| `[BLACKOUT on\|off]`, `[gm 100]` | `blackout on\|off`, `gm 100%` | S | | |
| SPEED: BPM, beat dots | `speed[]` + `beats(frame.time)` | S | `snap`, `frame` | |
| TAP | `tap "<name>"` (tap tempo is the engine's) | S | | |
| `[−1]` `[+1]` | `bpm "<name>" <n>` | S | `snap` | |
| Step list | `multiplierSteps`; current `SpeedStatus.multiplier`, `.level` | S | `doc`, `snap` | |
| SIZE and GROUP masters | masters of kind `size`, `group` (target group); `master "<name>" <p>%` | S | `doc`, `snap` | |
| *(busk)* fade-time masters | kind `fadeTime`; `EngineSnapshot.fadeTime` | S | `doc`, `snap` | |
| *(busk)* panic | `release all [<s>]`, `output on\|off`; `output off` after its `confirmation` question (GAP-10) | S | `snap`, `ask` | |

### 2.9 F8 Patch (spec §8.8)

| Spec item | busk | Class | Live source | Gap |
|---|---|---|---|---|
| UNIVERSES: U, name, fixture count, used `n/512` | universes, fixture patches, `mode.footprint`, `elementPatch` | S | `doc` | |
| ROUTES: U, protocol, address, destination | `output.routes[]`: sACN, Art-Net, DMX-USB, enabled | S | `doc` | |
| TX indicator | `LiveShow.routes` (GAP-07): `state`, `detail`, a packet rate from `packets` over the poll interval | S | `route` | |
| DMX MAP 8 × 64, start `█`, rest `▓`, overlap `╳` | patches and footprints | S | `doc` | |
| Colour by fixture type | the profile's `category` (GAP-16) | S | `doc` | |
| Hover `fixture N · ch k/fp`, click selects | `sel fixture N` | S | | |

### 2.10 F9 MIDI (spec §8.9)

| Spec item | busk | Class | Live source | Gap |
|---|---|---|---|---|
| SURFACES: name, kind, binding count | `surfaces[]` (midi, osc, web), `bindings[]` | S | `doc` | |
| Status dot | `LiveShow.surfaces` (GAP-08): `state`, `detail`; an open web remote's `urls` | S | `surf` | |
| MONITOR | not available | N | — | GAP-13 |
| BINDINGS: surface, type, channel, number, target | `bindings[]`: input (cc, note, osc, clock), action, feedback | S | `doc` | |
| `val` | the target's level (fader slot → the playback on the current page; master) instead of the raw MIDI value | P | `snap` | GAP-13 |
| Learn mode | not available | N | — | GAP-13 |

### 2.11 Spec §9, "Data the engine must expose"

| Data | Class | How | Gap |
|---|---|---|---|
| Fixture output, ≥ 10 Hz | S | `out` (GAP-01): every tick, polled at 20 Hz | |
| Playbacks (incl. chase steps) | S | `snap`, republished on every change | |
| Masters, beat phase ≥ 20 Hz | S | `snap` + `frame.time` at 20 Hz | |
| Programmer | S | `prog` (GAP-02, GAP-14) | |
| Effects | S | cue effects in `doc`, programmer effects in `prog`, what runs in `fx` (GAP-09) | |
| Show structure | S | `doc`, profiles with their category (GAP-16), templates from `effect_templates` (GAP-15) | |
| Events: command results | S | `Reply` of each line the TUI sends. Changes made by surfaces or the web remote are seen through polling, not as events | |
| Events: MIDI input | N | n/a | GAP-13 |
| Events: route TX status | S | `route` (GAP-07) | |
| Events: undo depth | P | `info` text | GAP-03 |

---

## 3. Spec adaptations

Decisions taken because the engine works differently from the mockup. Each can be vetoed. Where
they answer one of the spec's open questions (§10 of the spec), that is noted.

1. **busk names and syntax everywhere.** `intensity`, not `dim`. Colour is `set color r g b
   [w x]`, or one component, `set color.r <value>`. A step is `set <attribute> by <change>`
   (`by -5%`): a signed value without `by` is absolute (`set pan -45`), and `set intensity +5%`
   is refused (GAP-05). The strobe is `shutter` (discrete) and `strobeRate` (Hz). Chase and
   effect rates use `bpm x 1`, not `x1`. The UI shows the same words the operator types.
2. **Going to a cue is `goto N <cue>`**, on the playback that runs the list. In busk,
   `cue L/C go` sets the cue's trigger. F4 offers it only as an edit pre-fill. A list that no
   playback runs has no go-to action: its rows say "assign the list to a playback first".
3. **GO does not raise a fader at 0** (spec open question 5). busk activates the playback and
   leaves the level, as consoles usually do. The TUI does not add a second command.
4. **F1 shows the current engine page** (spec open question 2). The playbacks are the current
   page's slots. The page shows in the F1 header and in a status-bar slot (`PAGE 1 Main`).
   PgUp/PgDn on an empty prompt send `page prev`/`page next`. A show with no pages lists playbacks
   by number. The `faders` setting (4–20) caps how many slots show.
5. **Layout B (stack) is the default** (spec open question 1). It is built first (Phase 1) and
   covers a show on its own. A and C ship in Phase 5 as settings, chosen with `--layout` or from
   the header, and remembered.
6. **The stage plot uses `fixture.location`** (spec open question 3): x right, y downstage, z up,
   in metres. Rows are fixtures with the same depth (y, rounded to 0.1 m), upstage at the top,
   with x along the row. Rows are labelled by position (`y 2.0 · z 5.0`), because busk has no
   truss names.
7. **Cue cells are edited by prompt pre-fill only** (spec open question 4). Selecting a cell puts
   `cue L/C time ` (or `follow `, `wait `) in the prompt.
8. **Fixture types are profile categories** (GAP-16). A small table in the TUI turns busk's
   eleven categories (`par`, `spot`, `wash`, `beam`, `pixel`, `strobe`, `blinder`, `dimmer`,
   `effect`, `fog`, `other`) into layout A's rows (PARS, SPOTS, WASHES, PIXELS, STROBES, …),
   layout C's glyphs (`■` par, `◆` spot, `●` wash, `▲` strobe, `█` pixel, one glyph for the
   rest) and F8's map colours (par amber, spot cyan, wash magenta, pixel green, strobe the
   foreground). A profile with no category has a row of its own, named after it, and a colour
   by profile in show order. F3 offers the pre-fill `profile "<name>" category `.
9. **Playback colour is the current cue's colour** (`PlaybackStatus.color`, GAP-17), then
   `uiColor` when it is set and parses as a colour (`playback 1 uiColor "#ff8800"`), then the
   neutral foreground. It is the cue's colour, not the live output's: the fader, the masters
   and effects do not change it.
10. **Cue lists are `sequence` or `chase`.** There is no "flash" kind.
11. **All six preset pools** show when they have presets.
12. **Two kinds of effects.** Programmer effects (`effect add`, ids like `fx5`, stopped and run
    again with `effect stop fx5` / `effect run fx5`, removed with `effect remove fx5`) and cue
    effects (ids unique within their cue). The RUN/off click on a cue effect sends `go N` /
    `release N` to its playback, instead of `fader N 100%|0%`. On a programmer effect it sends
    `effect stop` / `effect run`: each is one undo step, and a stopped effect is not recorded into
    a cue (GAP-14). A template click sends `effect add "<name>"` and lets the library's defaults
    apply.
13. **F9 is "Surfaces"**: MIDI, OSC and the web remote.
14. **F7 adds fade-time masters and the panic controls** (`release all`, `[OUTPUT OFF]`,
    `[OUTPUT ON]`). `[OUTPUT OFF]` asks the engine's question first, as a typed `output off`
    does (§4.3).
15. **Status bar additions.** An `OUTPUT OFF` chip (red) and `PAGE`. An `ENGINE` chip that names
    the engine's state while it is not running (`ENGINE STALLED`, `ENGINE RESTARTING`, `ENGINE
    FAILED` in red, a dim `ENGINE STARTING`), and a dim `LATE` while overruns grow (GAP-21).
    `FADE` is the programmer's fade time (GAP-02); the fade-time master override shows on F7.
16. **Performance commands are never undone** in busk (faders, GO, masters). The spec's "one
    snapshot at drag start" only matters for encoders (GAP-06).
17. **Quick-command defaults in busk syntax.** `set intensity spread 0 to 1`, `… center`,
    `set pan spread -90 to 90`, `set tilt 45`, `highlight on`, `highlight off`, `record cue 1`,
    `clear`, `blind on`, `blind off`. The spec's `set dim breakup` is dropped: `breakup` is a gobo
    slot in busk.
18. **`help` typed at the prompt opens the overlay.** The line goes to the engine and its reply
    fills the overlay. A line whose reply has `quit` (GAP-18) opens the TUI's quit dialog, so
    `quit`, `exit` and a sourced script's `quit` all do. No line is intercepted.
19. **No result line for performance commands.** busk replies with empty text, so the spec's
    sample results (`P1 → cue 2 "Peach"`) do not appear. The engine log and the panes show the
    effect.
20. **Bindings `val` is the target's level in %**, not the raw MIDI value (GAP-13).

---

## 4. Architecture

### 4.1 Threads and data flow

```
 terminal ─ Textual app (UI thread, asyncio): frame, pages, widgets
              │ send(line, origin, key, …)          ▲ drain() every 25 ms
              │ confirmation(), expected()          │ BridgeEvents
              ▼                                     │
     ┌───────────────── bridge.py ──────────────────┴─────────────────────┐
     │ ordered worker  : typed lines, edits, programmer lines; one at a   │
     │                   time, in order                                   │
     │ controls worker : the performance lines of the TUI's own controls, │
     │                   in order; coalesces control moves (GAP-12)       │
     │ reader, 20 Hz   : snapshot, programmer, routes, surfaces, health,  │
     │                   frame, show, effect_templates, warnings; output  │
     │                   and effects while a page shows them; converts to │
     │                   view models only on change                       │
     │ logging handler : on the "busk" logger, INFO and up                │
     │ event queue     : SimpleQueue → drained by the UI                  │
     └──────────────────────────────────┬─────────────────────────────────┘
                                        ▼
   busk.LiveShow: busk run's, with the engine and the output in processes of
   their own (GAP-11), or, with --standalone, one the bridge starts here
```

- The UI thread never runs a line and never waits for the bridge. `send()` queues and returns a
  ticket. `drain()` returns what has arrived. Reading a few references and comparing a `seq` is
  all the polling costs the UI.
- `confirmation(line)` and `expected(line)` are the two calls the UI thread makes into the
  engine, through the bridge. They read published state, take no lock and change nothing: 4–16 µs
  on the club-night show (GAP-10, GAP-20), and up to 6.4 ms for `expected` on a discrete
  attribute with 7 795 elements selected.
- Under `busk run`, the Textual app runs on the console process's main thread, where `busk run`
  calls `frontend(show)`. The engine and the output are in other processes. The session, the
  surfaces and the building of `FixtureOutput`s share the console process with the TUI.
- The bridge has no Textual import. It is tested on its own.
- Rendering is change-driven: a widget refreshes only when its slice of the view model changes.
  The exceptions are the beat dots, the sparklines and the busy indicator (20 Hz) and the clock
  (1 Hz). This keeps the interpreter free for the session and the engine (risk R1).

### 4.2 Package layout

```
src/busk_tui/
  __init__.py        version (importlib.metadata "busk"); no busk import
  __main__.py        python -m busk_tui
  app.py             main(): arguments, then busk run SHOW --frontend busk_tui.app:frontend
                     (or --standalone); frontend(show), the function busk run calls; BuskApp
                     (Textual App): frame, pages, keys, drain timer
  bridge.py          the engine boundary: lifecycle, the two workers, reader, conversion, log capture
  model.py           frozen view models, BridgeEvent types, the BridgeLike protocol (no busk, no Textual)
  commands.py        builders for every line the UI sends (fader(3, 0.72) → "fader 3 72%"), each
                     marked as a performance line or not
  hints.py           the hint row: the help index by first word, and the expected() line
  colors.py          palette (§4.1), output-colour quantisation (§4.2), the category table (§3, 8)
  config.py          options, config.toml (read-only), state.json (last page, layout)
  nav.py             the pane cursor (keyboard navigation inside a page, §4.5)
  busk.tcss          styles
  widgets/           frame.py (StatusBar, TabBar, KeyLegend), prompt.py (Prompt, HintRow),
                     log.py, help.py, dialogs.py (quit, confirmation), controls.py (CommandButton,
                     Chip), bars.py (HBar), digits.py (BigDigits, BeatDots), swatch.py, then per
                     phase
  pages/             base.py (Page), placeholder.py, then one module per page
```

### 4.3 The bridge

**UI-facing API** (`BridgeLike` protocol in `model.py`; the real `Bridge` and the tests'
`FakeBridge` implement it):

| Member | What it does |
|---|---|
| `start()` | Starts the threads. Under `busk run`, the show it was given runs already, and the ordered worker runs `help` once. Standalone, the ordered worker constructs the `LiveShow`, starts it (up to 15 s, `SETTLE_S`) and runs `help`. Never blocks the caller. |
| `stop(timeout=5.0)` | Idempotent. Stops the reader, lets each worker finish its current line and drops queued lines. Standalone, it then calls `LiveShow.stop()` (routes send their last frame and terminate the streams), and gives up after `timeout` with a warning. Under `busk run` it never stops the show: the run does, when `frontend` returns. |
| `send(line, origin, key=None, performance=False) -> int` | Queues a line. `origin`: `typed`, `ui` or `internal` (internal lines are not echoed). `performance` comes from the `commands.py` builder that made the line, and sends it to the controls worker; typed lines always go to the ordered worker. With a `key` (`fader:3`), a newer line replaces a queued, unsent line with the same key. |
| `confirmation(line) -> str \| None` | The engine's question before `line` (GAP-10), or `None`. Safe on the UI thread. |
| `expected(line) -> Completion` | `expected(line)` (GAP-20) as a view model: `words`, `values`, `runnable`, `error`, `start`. Safe on the UI thread. |
| `watch(output, effects)` | Which of `output` and `effects` the reader polls, set by the visible page. |
| `drain() -> list[BridgeEvent]` | Everything that arrived since the last call, in order. Of each kind of state event, only the newest of a batch is kept. |
| `busy -> Busy \| None` | The ordered worker's line running now and when it started. |
| `help_lines -> tuple[str, …]` | The text of `help`, once known. |

**Events** (`model.py`): `EngineStarting`, `EngineRunning(title, warnings)`,
`EngineFailed(message)` (standalone only), `EngineStopped`, `CommandDone(ticket, line, origin,
ok, lines, seconds, quit)`, `LiveChanged(LiveState)`, `Beat(time, beats)` (20 Hz),
`ShowChanged(ShowModel)`, `ProgrammerChanged(ProgrammerModel)`, `OutputChanged(OutputModel)`,
`EffectsChanged(EffectsModel)`, `RoutesChanged(routes)`, `SurfacesChanged(surfaces)`,
`HealthChanged(state, late)`, `EngineNews(level, text)` (log records).

**View models.** `LiveState` has `seq`, `gm`, `blackout`, `outputEnabled`, `page`, `fadeTime`, the
playbacks (number, name, state, level, flash, fader function, chase, cue, cue name, next, cue
count, progress, colour), master levels by name, and speed masters (name, bpm, multiplier, level).
`ProgrammerModel` has `version`, the selection as `(number, element)` pairs, blind, highlight,
fade time, the values by fixture (attribute, value, preset name), the effects, formatted as cue
effects are, and the stopped ids. `OutputModel` has `seq` and, per element, intensity, colour,
pan, tilt, zoom and the source by family. `EffectsModel` has `seq` and, per `(playback, cue,
id)`, presence, size, hz, phase, wave and colours. Routes and surfaces are tuples of their
status (label or name, state, detail, and packets or URLs). `ShowModel` has the parts each phase
needs, keyed by user-facing numbers and names, never ids: title, universes, routes, fixtures,
profiles (with category), groups, presets, cue lists, playbacks, pages, masters, surfaces,
bindings and effect templates. The bridge matches route and surface statuses to the document by
id, so pages never see one. Each phase adds the fields it uses.

**Asking first.** Before the TUI sends a line (typed, from history, a pre-fill or a button; not
the coalesced moves of faders and masters), it calls `confirmation(line)`. A question opens a
yes/no dialog with the engine's text, and the line is sent only on yes. No, Esc and closing the
dialog cancel, and the log shows `cancelled`, as `busk run` prints it. Today only `output off`
asks. `execute` itself never asks.

**Quitting.** A reply with `quit` and a second Ctrl+C open the quit dialog: *Save and quit / Quit
without saving / Cancel*. It cannot tell whether there are unsaved edits (GAP-03), and says so.
Under `busk run` the autosave keeps them either way. After it, `frontend` returns and the run
ends; standalone, the bridge stops the `LiveShow`.

**Failure handling.** The UI is never frozen and never crashed by the engine side:

| Situation | Behaviour |
|---|---|
| A line takes long (`save`, `source`, a big edit) | Prompt context shows `⧗ <line> 1.4s` after 0.3 s (the ordered worker). Input, tab switching, the live panes and the TUI's controls keep working: their performance lines go on the controls worker and never wait for the edit (GAP-12). Later typed lines queue, and control moves coalesce. |
| `execute()` raises (it should not) | `CommandDone(ok=False)` with `internal error: <type>: <message>`. The traceback goes to the TUI's debug log file. The worker carries on. |
| The show does not load | Under `busk run`, `busk run` prints the issues and exits before it calls the TUI. Standalone, `main()` prints them (`path: message`) to stderr and exits 2, before Textual starts. |
| Standalone, `LiveShow()` or `start()` fails | `EngineFailed`: a full-screen message with the reason and `q` to quit. |
| The engine does not run | `health.state` is not `running` (GAP-21): `HealthChanged`, and the `ENGINE` chip names the state. It clears when the engine runs again. Under `busk run` the watchdog restarts a stalled or dead engine (`restarting`), and after it the first reads of `frame`, `output` and `effects` return `None` again. |
| The engine runs late | The overruns of two `health` reads ≥ 1 s apart grow: a dim `LATE` chip while they do. |
| Standalone, `stop()` hangs | After the timeout, a warning on stderr and exit anyway (the threads are daemons). |
| The UI raises | Standalone, `main()` runs the app inside `try/finally: bridge.stop()`, so the output is always terminated. Under `busk run`, Textual restores the terminal and the exception leaves `frontend`: a console crash. `busk run` starts a new console, which recovers the show from the autosave and calls `frontend` again, while the engine and the output run on (GAP-11). A flash the TUI held stays held, and shows as held (`PlaybackStatus.flash`). |
| SIGTERM, SIGHUP | Under `busk run` with processes, busk raises its own exception on the TUI's thread; the TUI lets it through, and the run ends as after `quit`. Standalone, the TUI quits as on `quit`, without the dialog. |
| Ctrl+C | Clears a typed line. On an empty prompt it says how to quit, and a second Ctrl+C opens the quit dialog, as in `busk run`. Textual reads it as a key, so busk's `KeyboardInterrupt` does not reach the TUI. |

### 4.4 The frame and global keys

The frame follows spec §5. The prompt always has text focus. Global keys act only on an empty
prompt, except the F-keys, Alt+digits and Esc.

| Key | Action | Origin |
|---|---|---|
| F1–F9, Alt+1–9 | switch page, close help | spec |
| F10, Alt+0, `?` (empty prompt) | toggle help | spec |
| Esc | close a dialog or help, else leave the pane cursor, else clear the prompt | spec + §4.5 |
| Enter, ↑ ↓, Tab | run (after asking, §4.3), history, complete the word at the cursor | spec, GAP-10, GAP-20 |
| Space, ← →, `[` `]` | GO, select playback, fader ±5 % (F1 and anywhere the selected playback applies) | spec |
| PgUp, PgDn | `page prev`, `page next` | adaptation 4 |
| Tab on an empty prompt | enter the pane cursor | addition, Q8 |
| Ctrl+C | see §4.3 | `busk run` |

Help is an overlay layer inside the main screen, not a modal screen, so the prompt stays usable
while it is open (spec §8.10).

### 4.5 The pane cursor (keyboard reach)

With the prompt always focused, the spec reaches table rows and tiles by mouse or by typing the
command. For keyboard-first operation, Tab on an empty prompt moves a cursor into the page. The
arrows move it over the page's items (rows, tiles, buttons), Enter runs the item's line (echoed
`ui>`), Esc or any printable key returns to the prompt. Each page declares its items as
`(label, line or pre-fill)`, so the cursor adds no logic of its own. This is an addition to the
spec (question Q8).

### 4.6 Testing

- **Pure units, no Textual:** `hints.py`, `commands.py`, `colors.py`, `config.py`, the `busk run`
  command line and environment `main()` builds, and the bridge's conversion (fed with real busk
  objects from `OfflineShow`: snapshot, programmer, output, effects, effect templates, `expected`
  answers; tests may import busk).
- **Bridge:** against a stub show object whose `execute` can sleep, fail or raise, for the two
  workers (a controls line runs while an ordered line sleeps), coalescing, ordering within each
  worker, busy, health and shutdown in both hosts. A few tests use a real `LiveShow(output=False,
  surfaces=False)` on the club-night show built in a temporary directory.
- **Host:** `busk run SHOW --frontend` with a probe frontend in `tests/tui/` (on `PYTHONPATH`)
  that hands the run's show to the real `Bridge`, sends `fader 1 50%`, waits for the
  `LiveChanged`, and returns. The run ends with exit 0, and the bridge never stopped the show.
  With `--threads` and with processes, as the engine's `tests/test_frontend.py` does.
- **UI:** Textual's `App.run_test()` and `Pilot` with `FakeBridge`. Press keys, click, then
  assert the lines sent and the text widgets render.
- **Command contract:** every line `commands.py` can build runs on an `OfflineShow` of
  `examples/club-night.busk` and must be accepted. This catches spec-versus-engine drift such as
  `x1` and `dim`. A builder's performance mark must match GAP-12's list of performance lines (a
  table in the test). Each phase adds its builders to the table.
- **Boundary:** an AST scan checks that only `bridge.py` imports `busk`, only names in
  `busk.__all__`, and that `app.py`, `model.py`, `commands.py`, `hints.py`, `colors.py` and
  `config.py` import no busk, and the last five no Textual either.
- **End to end:** the real bridge and the app, headless, on a real `LiveShow(output=False)`:
  type `fader 1 50%` and see the playback row show 50.
- **Performance** (opt-in, `-m perf`), with the TUI running headless at full refresh on F3
  (output) and F5 (effects): standalone, the engine's frame rate (`frame.seq` over wall time)
  against a bare `LiveShow`; under `busk run`, the engine's overruns (`health`) and the console
  process's CPU against a bare frontend. The gates are set in Phase 0 from measurements (risk
  R1).
- Layout: `tests/tui/` has no `__init__.py`, like `tests/`. Files are named `test_tui_*.py` so no
  basename clashes with `tests/`. `tests/tui/conftest.py` skips collection when Textual is not
  installed, so `uv run python -m pytest` keeps working without the extra.

Commands (see Q4 for the dev environment; `python -m` because the venv's console scripts have
stale shebangs):

```
uv run --extra tui python -m pytest tests/tui           # TUI tests
uv run python -m pytest                                 # the engine suite, unchanged
uv run --extra tui python -m mypy                       # --strict on src/, now with busk_tui
uv run ruff check . && uv run ruff format --check .
uv run --extra tui python -m busk_tui examples/tupperdmx/tupper-demo.show               # under busk run
uv run --extra tui python -m busk_tui --standalone examples/tupperdmx/tupper-demo.show  # standalone
```

---

## 5. Phases

| Phase | Pages | Theme |
|---|---|---|
| 0 | frame, F10 | Foundation |
| 1 | F1 (layout B), F7 | Perform |
| 2 | F2, F6 | Program |
| 3 | F4, F5 | Cues and effects |
| 4 | F3, F8, F9 | Rig |
| 5 | F1 layouts A and C | The other Busk layouts |

Every phase ends with the app runnable, the TUI and engine suites green, ruff, format and mypy
clean, the user guide (`docs/tui/guide.md`) updated, and `engine-gaps.md` updated if the phase
found a new gap. Pages not built yet are placeholders that name their phase and list the lines to
type meanwhile.

### Phase 0: Foundation

**Goal and scope.** `busk-tui SHOW` opens the full frame on a live engine under `busk run`:
status bar, tabs, log, prompt with hints and completion, confirmation and quit dialogs, help
overlay, placeholder pages. It has the bridge, the two hosts, the shared widgets, configuration,
and the test harness. Spec §2, §3, §4.1, §4.3 (panel, button, tab, horizontal bar, status chip,
big digits, beat dots, table styling), §5, §6.1, §6.2 (click, drag and wheel plumbing), §6.3
(through `undo`/`redo` lines), §7, §8.10, §9 (polling).

**Steps.**

0.1 **Skeleton, packaging and host.** `pyproject.toml`: `tui = ["textual>=8.2"]` (floor confirmed
with `--resolution lowest-direct`, as Phase 8 did), `busk-tui = "busk_tui.app:main"`, and the
build-backend `module-name` list (Q3). `__init__.py`, `__main__.py`, `app.py` with `--version`,
`main()` and `frontend(show)`. `main()` checks the TUI's options, then replaces itself with
`python -m busk run SHOW --frontend busk_tui.app:frontend` and the `busk run` options it was
given, with the TUI's own options in `BUSK_TUI_OPTIONS` (JSON), because `frontend` gets only the
show (GAP-11). `--standalone` runs the app in this process instead. *Verify:* `uv build --wheel`
contains `busk_tui/` and the script; `tests/test_packaging.py` still passes; the host unit tests.


   **Done** (2026-10-24).
   - `pyproject.toml`: the `tui` extra, the `busk-tui` script, `[tool.uv.build-backend]
     module-name = ["busk", "busk_tui"]` (Q3: without it `busk_tui` is not in the wheel), and
     `busk[tui]` in the `dev` group (Q4). `uv.lock` follows.
   - **`--standalone`, not `--in-process`** (Q5: you kept the host but not the name). One flag
     in `config.py`; easy to rename again.
   - **`BuskApp` is in `shell.py`, not `app.py`.** Textual reads `TEXTUAL_COLOR_SYSTEM` when it
     is imported, so `app.py` imports neither busk nor Textual at the top: `main()` sets the
     colour system from `--colors` (and the config file), then imports the shell, or puts it in
     the environment `busk run` inherits. The boundary test checks both.
   - `main()` replaces itself with `os.execve` (the exit code is `busk run`'s), after
     `run_command(options)`, which the tests call.

0.2 **Bridge core.** `model.py`, `bridge.py`: both hosts (under `busk run`, the given
`LiveShow`, never started or stopped by the bridge; standalone, load errors,
`ProfileLibrary(--library dirs)` and `LiveShow(show, path=…, library=…, output=…, surfaces=…,
state_dir=…, tune_interpreter=True)`), the ordered and controls workers, the reader, the log
handler, `confirmation`, `expected`, the events of §4.3. Phase 0's conversion: title, routes and
their status, universes, masters, pages, speed masters, health, and the programmer's selection,
blind, fade time and fixture count. *Verify:* the bridge tests, stub and live, and the host test.


   **Done** (2026-10-24).
   - As §4.3, with: a keyed line that replaces a queued one goes to the end of its queue (after
     the lines sent before it) and the replaced line has no `CommandDone`; the bridge's own
     lines (`help` at start, `info`) send no `CommandDone` and do not show as busy; before the
     show runs, `confirmation` is `None`, `expected` empty and the health `starting`.
   - **The temporary `info` parser** (Q2): `session_from_info` reads `undo: N steps, redo: M
     steps` and `file: …, saved|unsaved edits`. The ordered worker runs `info` after each line it
     ran that succeeded, and the reader queues one (deduplicated) when the document or the
     programmer changes, which covers surfaces and the web remote. New event
     `SessionChanged(SessionState(undo, redo, dirty))`. Remove when GAP-03 closes (its section
     says so).
   - The reader marks each part seen only once it is converted, so a conversion that raises is
     tried again at the next look (and logged to the debug log).
   - `RouteView` is the document's route (protocol as the operator reads it, `sACN`, `ArtNet`,
     `DMX-USB`; universe number; enabled) with its status matched by id; `state` is `None`
     while nothing runs the output (`--no-output`).
   - `Bridge.attached(show: object)` checks it got a `LiveShow`, so `app.py` needs no busk type.
   - Phase 0's `LiveState` has no playbacks (Phase 1 adds them): the host probe and the live
     tests send `gm 50%` instead of `fader 1 50%`.

0.3 **App shell.** Frame layout, `busk.tcss` with the palette, `StatusBar`, `TabBar`,
`KeyLegend`, `Page` base and placeholders, F-keys and Alt+digits, reflow below 100 columns.
*Verify:* Pilot tests switch every page. Manual check at 100×30 and 150×48.


   **Done** (2026-10-24).
   - The status bar puts the `ENGINE …` and `OUTPUT OFF` chips before the routes, so a narrow
     terminal cuts the clock-side end, not a warning. The title is cut at 24 cells, with `*`
     after it while there are unsaved edits (Q2). A route's light changes at most every
     0.25 s while its `packets` grow.
   - The tabs are one text with click actions; a key and its name never split when they wrap.
   - Checked in a real pseudo-terminal (pyte), under `busk run` at 150×48 and standalone at
     100×30, besides the Pilot tests at 99, 100 and 150 columns.

0.4 **Command line.** `Prompt` (history, Esc, Tab completion from `expected`), `HintRow` (the
`help` lines of the first word, and the `expected` line: next words, `<values>`, `<Enter>`,
`error: …`), `LogView` (line types of spec §7.3, `busk.*` records as info and warning lines,
bounded to 2000 lines, auto-scroll), prompt context (`P<n>`, `sel n`, page, busy), the
confirmation dialog, and the quit dialog on a reply with `quit` (§4.3). *Verify:* the prompt
tests.


   **Done** (2026-10-24).
   - **Keys that depend on the prompt go through it.** Tab, Esc, Ctrl+C, `?` (empty prompt),
     the pane cursor's Enter and arrows, and PgUp/PgDn over help are offered by `Prompt._on_key`
     to `BuskApp.prompt_key`, in typing order. As app priority bindings (the first build) they
     ran before the keys typed just before them: in a real terminal, `blind of` and Tab in one
     burst completed a stale line. (Textual also skips an app's binding for a printable key a
     focused input would type.) F1–F10, Alt+digits and Ctrl+Q stay app-wide. A test posts a
     burst of keys.
   - Ctrl+Q opens the quit dialog (Textual's own quits at once). On an empty prompt, Ctrl+C's
     "press Ctrl+C again to quit" is in the hint row; any other key starts again.
   - Space, ← →, `[` `]` and PgUp/PgDn's `page prev|next` come with F1 in Phase 1 (they need
     its playbacks); the key legend lists only the keys that work.
   - The hint row: what may come at the cursor (`next: …`, or `error: …` in red), then up to
     two `help` forms, those naming more of the typed words first. While the first word is
     typed and has no form, the commands it starts are the engine's (`expected`), so `group`
     and `show` are not "unknown". Tab with several candidates also completes what they share,
     as readline does.
   - A refused line's `error: ` (the documented mark of `Reply`) is left out after ` ✗ `; the
     lines after the first are indented.
   - The quit dialog knows about unsaved edits (Q2): with them, *Save and quit / Quit without
     saving / Cancel*; without, *Quit / Cancel*; unknown, the three and a note. Save and quit
     waits for the `save` and stays if it fails.

0.5 **Help overlay.** F10, `?`, typed `help`, Esc and outside click close it. It holds the `help`
text and the key grid. *Verify:* Pilot tests, prompt usable while it is open.


   **Done** (2026-10-24). The overlay is the panel itself, centred on a layer of its own:
   Textual paints a full-size layer over what is under it, so the pages are dimmed with a
   `tint` instead. PgUp/PgDn scroll it.

0.6 **Shared widgets.** `CommandButton` (`[LABEL]`, intent colour, runs a line), `Chip`, `HBar`
(click, drag with coalesced sends and one log line on release, wheel, ⅛ cells), `BigDigits`,
`BeatDots`, `Swatch`, `colors.py`, `commands.py` (Phase 0 builders: `help`, `undo`, `redo`; each
builder says whether its line is a performance line), `nav.py`. *Verify:* widget and colour
tests.


   **Done** (2026-10-24). Also `commands.save()` (the quit dialog's). Widgets post `RunLine`
   messages and the app sends them, so no widget sees the bridge. The category table of
   adaptation 8 comes with its first page (Phase 4), not in `colors.py` now.

0.7 **Configuration.** Options: `SHOW`; `--state-dir` and `--library DIR` (repeatable), for
`busk run` or the standalone `LiveShow`; the other `busk run` options that combine with
`--frontend` (all but `--console`, `--no-console` and `--duration`), passed on as they are;
`--standalone`, and with it `--no-output` and `--no-surfaces`; the TUI's own `--layout A|B|C`,
`--faders N`, `--colors auto|256|16|truecolor`, `--config FILE`. Also
`$XDG_CONFIG_HOME/busk-tui/config.toml` (quick commands, defaults) and
`$XDG_STATE_HOME/busk-tui/state.json` (last page and layout; unreadable or unwritable is
ignored). *Verify:* config tests.


   **Done** (2026-10-24). The config file has `[defaults]` `layout`, `faders`, `colors` (the
   quick commands come with Phase 2). Order: options, then the remembered layout and page, then
   the config file. `--standalone` refuses the `busk run`-only options, and `--no-output` /
   `--no-surfaces` need it (exit 2). Standalone opens the surfaces unless `--no-surfaces`, as
   `busk run` does. `--layout` and `--faders` are taken and remembered; F1 uses them from
   Phase 1.

0.8 **Hardening and docs.** The failure behaviours of §4.3, signals, the perf check, and
`docs/tui/guide.md` (install, start, the two hosts, frame, keys; `--standalone` is for
development and rehearsal, not for a show). *Verify:* the failure tests and the manual check
below.


   **Done** (2026-10-24). `docs/tui/guide.md`, a README line and table row (Q10: assumed yes),
   a CHANGELOG entry, `docs/dev/development.md` (setup, commands, layout). Signals: under `busk
   run`, SIGTERM and SIGHUP end the run with the terminal restored (checked in a pty);
   standalone, they exit the app, and `main()` stops the show. Tracebacks the TUI catches go
   to `$XDG_STATE_HOME/busk-tui/debug.log`. Perf gates below.

**Files.** `pyproject.toml`; `src/busk_tui/{__init__,__main__,app,bridge,model,commands,hints,
colors,config,nav}.py`, `busk.tcss`; `widgets/{__init__,frame,prompt,log,help,dialogs,controls,
bars,digits,swatch}.py`; `pages/{__init__,base,placeholder}.py`; `tests/tui/{conftest,tui_fakes,
tui_probe}.py`, `tests/tui/test_tui_{boundary,host,bridge,bridge_live,hints,commands,colors,
widgets,frame,prompt,help,config,e2e,perf}.py`; `docs/tui/guide.md`.

**Engine lines used.** Any typed line, asked about with `confirmation` first; `help`; `undo` and
`redo` (typed). **Reads:** `snapshot` (grandMaster, blackout, outputEnabled, page, speed,
fadeTime), `frame` (time, seq), `show` (meta.title, output.routes, universes, masters, pages),
`programmer` (selection, blind, fadeTime, values), `routes`, `health`, `warnings`, `busk.*` logs;
`confirmation(line)`, `expected(line)`, `Reply.quit`.

**Deferred.** Nothing: `undo n`, the unsaved marker and a quit dialog that knows come from
the temporary `info` parser (Q2) until GAP-03 gives them typed.

**Tests.**
- Boundary scan (§4.6).
- Host: the `busk run` command line and `BUSK_TUI_OPTIONS` for each option; `--standalone` and
  its options; the probe frontend under `busk run`, with `--threads` and with processes (§4.6).
- Bridge, stub: lines run in order on each worker; a controls line runs while an ordered line
  sleeps 5 s; `send()` returns at once; `busy` follows the ordered worker only; a raising
  `execute` gives `internal error` and the next line still runs; coalescing keeps only the newest
  unsent `fader:3`; `LiveChanged` only on a new `seq` (a smaller one counts, as after a restart);
  `ProgrammerChanged` only on a new `version`; `ShowChanged` only on a new document;
  `HealthChanged` on a new state, and `late` while the overruns grow over ≥ 1 s. Under `busk
  run`, `stop()` never stops the show. Standalone, `stop()` twice is harmless, `stop()` honours
  its timeout, and a failing `start()` gives `EngineFailed`.
- Bridge, live: standalone `start()` reaches `EngineRunning`; `fader 1 50%` gives a `LiveChanged`
  with 0.5 within 1 s, and `sel group 1` a `ProgrammerChanged`; `help_lines` is not empty;
  `health` goes `running`; after `stop()` no `busk-*` thread is alive.
- Hints, against the real `help` text and real `expected` answers: alternatives split on `|`
  (`clear | blind on|off | …` indexes `blind`), up to two lines, a prefix lists candidates,
  `unknown command`, the empty-prompt text; the `expected` line (next words, `<values>`,
  `<Enter>` only at the line's end, `error: …`); completion of a unique word anywhere in a line
  (`route add 1 sa` gives `sacn`, `master "Grand M` gives `"Grand Master"`) and of an ambiguous
  one (the candidates go to the log as info).
- Commands: formatting (levels as whole percent, names quoted, a name containing `"` refused),
  performance marks, and the contract test.
- Colours: §4.2 cases (below 1.5 % gives 236, cube against grey ramp, 16-colour nearest).
- Frame (Pilot + FakeBridge): F1–F10 and Alt+1–0; help open and close; a typed line echoed with
  `busk>` and sent; result, error and info styles; history; Esc; global keys ignored while text
  is typed; layout below 100 columns; the status bar from `LiveState`, `ProgrammerModel`, routes
  and health (GM amber, blackout, output off, `PROG n`, BLIND, `FADE`; route dots green,
  blinking on new `packets`, red, dim; the `ENGINE` chips by state and `LATE`; beat dot timing);
  the busy indicator; the confirmation dialog (yes sends; no, Esc and closing log `cancelled`); a
  reply with `quit` opens the quit dialog and Cancel carries on; Ctrl+C.
- Config: defaults, overrides, bad TOML (defaults and an info line), state round trip,
  unwritable state directory.
- End to end and perf, as in §4.6.

**Done when.**
- [x] `busk-tui SHOW` (under `busk run`), `busk-tui --standalone SHOW` and `python -m busk_tui
      SHOW` open the frame at 100×30 and 150×48, and every page is reachable with F-keys and
      with Alt+digits.
- [x] Typed lines run, and results, errors and engine news show with the spec's prefixes. Hints,
      completion of every word and the help overlay work, and the prompt stays usable over help.
      A typed `output off` asks first and runs only on yes.
- [x] The status bar follows the live engine: title, routes with their state, GM, BPM and beat
      dot, programmer fade, `PROG n`, BLIND, blackout, output off, page, engine state, clock.
- [x] A 5 s line (stub) never freezes keys, page switching, the beat dots or a fader drag. No
      engine-side exception reaches the UI. Every way of quitting ends the run (under `busk run`)
      or stops the `LiveShow` (standalone).
- [x] The boundary, contract, TUI and engine suites are green, with ruff, format and mypy clean.
      The wheel contains `busk_tui` and `busk-tui`.
- [x] The perf gates of both hosts are recorded in this plan's Done note.
- [ ] Manual (the user): on the TupperDMX rig with the simulator, under `busk run`: `go 1`,
      `gm 50%`, `blackout on`/`off`, `output off` (asked first) and `output on`; kill the engine
      process and see `ENGINE RESTARTING`, then the chip clear; quit by `quit` and by Ctrl+C
      twice: the terminal is restored and the simulator stops receiving.

**Done** (2026-10-24), steps 0.1–0.8; the manual check is the user's.
- Suites: the TUI's 171 tests (`tests/tui`, 14 test files) and the whole suite, 4076 passed, 1
  skipped (the opt-in multicast), 15 deselected (perf and soak); ruff, format and `mypy` on
  `src/` clean. `textual>=8.2` confirmed with `uv sync --resolution lowest-direct` (Textual
  8.2.0, numpy 2.3.2, pydantic 2.12.4: the TUI's tests pass). Textual 7.5.0, 8.0.0 and 8.1.1
  pass them too today; the floor stays at 8.2 for the phases to come.
- **One engine test changed:** `tests/test_packaging.py::test_midi_is_only_an_extra` pinned
  the wheel's extras to `["midi"]`; with the `tui` extra they are `["midi", "tui"]`. Its point
  (MIDI's packages only through its extra) is unchanged. §1.2's rule and step 0.1's "still
  passes" cannot both hold once the extra exists.
- **Perf gates** (`uv run python -m pytest tests/tui -m perf -s`, `test_tui_perf.py`; club-night
  show, no routes or surfaces, the TUI headless at 150×48 typing a line every 0.6 s, 8 s each).
  Phase 0 reads neither the output nor the effects, so this is the frame, the prompt and the
  reader at 20 Hz:

  | Host | Measured | Gate |
  |---|---|---|
  | Standalone: the engine's frame rate, against a bare `LiveShow` | 100.0 vs 100.0 frames/s | ≥ 97 % of bare |
  | `busk run`: the engine's overruns | 0 of 803 ticks (bare: 0 of 703) | ≤ 0.2 % of ticks |
  | `busk run`: the console process's CPU, against a frontend that waits | 0.153 vs 0.015 core (+0.138) | ≤ +0.25 core |

  Phases 1–5 add their pages to the measurement, F3 and F5 with the output and effects read.
- Checked by hand in a pseudo-terminal (pyte): under `busk run` at 150×48, `gm 50%` in the
  status bar, `?` help, `output off` asked first, Ctrl+C twice to the quit dialog, `q`, exit 0
  and busk run's statistics; SIGTERM and SIGHUP end the run with the terminal restored
  (alternate screen left, mouse reporting off). Standalone at 100×30: the wrapped tabs, the
  remembered page, Tab completion, the pane cursor, SIGHUP. Not checked: killing the engine
  (the manual check above; the chip is unit-tested, the watchdog's states are GAP-21's tests).

### Phase 1: Perform (F1 layout B, F7)

**Goal and scope.** Everything needed to run a show from the TUI: playbacks on the current page
with GO and FLASH, masters, tempo, effects, blackout and panic, with the keyboard first. Spec
§8.1 (header, playback data, control table, layout B), §8.7, and the F1 keys of §6.1. The layout
switch is drawn; A and C say "Phase 5".

**Files.** `pages/busk.py` (header, layout host, selected playback), `pages/busk_stack.py`
(layout B), `pages/masters.py`; `widgets/playbacks.py` (`PlaybackRow`, and the compact row Phase 5
reuses), `widgets/tempo.py` (digits, dots, TAP, −/+), `widgets/masters.py` (master bars,
blackout, panic), `widgets/effects.py` (effect rows with state, sparkline and toggle, which F5
reuses), `widgets/quick.py` (group buttons, colour chips); additions to `bridge.py` (effects, and
cue and programmer effects formatted alike), `model.py` and `commands.py`; tests below.

**Engine lines used.** `go N`, `back N`, `fader N <p>%`, `flash N on|off`, `gm <p>%`,
`master "<name>" <p>%`, `blackout on|off`, `tap "<name>"`, `bpm "<name>" <n>`, `page prev|next|N`,
`sel group N`, `sel + group N`, `preset color N`, `release N`, `release all`, `effect stop <id>`,
`effect run <id>`, `output off` (after the engine's question), `output on`. **Reads:**
`snapshot` playbacks (with `color`), page, masterLevels, speed (+ `beats(frame.time)`), blackout,
grandMaster, fadeTime, outputEnabled; `programmer` selection, effects, stopped; `effects` while
F1 is visible; `show` pages, playbacks (cueListId, fader, uiColor), cue lists (cue order and
names, mode, chase, cue effects), masters (kind, group, steps), groups, colour presets, effect
templates.

**Layout B as built.** PLAYBACKS rows (`Pn`, name, level bar in the current cue's colour, level,
`cue/total cue → next` or `chase n rate direction`, `[GO] [◂] [FL]`, FLASH held while the mouse
button is down). The right column has TEMPO for the first speed master, then MASTERS with
`[BLACKOUT]`, then EFFECTS (one row per effect that runs, and per stopped programmer effect: id,
template, sparkline, RUN/off; a released cue effect leaves the panel, and GO on its playback
brings it back), then SELECTION (selection text, group buttons, colour chips).

**Deferred.** Nothing: every gap this phase needed is closed.

**Tests.** Rows from `LiveState` fixtures: active, idle, releasing, chase, empty slot, crossfade
progress, the fader functions, a held flash. Colour: the cue's `color`, else `uiColor`, else the
foreground. Keys send exact lines: Space `go 3`; ← → wrap within the visible slots; `[` from 0
stays at `fader 3 0%`; PgUp/PgDn. A bar drag sends coalesced lines on the controls worker and
logs once on release. The wheel sends lines and logs nothing. FLASH sends `flash 3 on` on mouse
down and `flash 3 off` on mouse up. TAP and −/+ use the master's name. The blackout toggle follows
the snapshot. EFFECTS rows from an `EffectsModel` and a `ProgrammerModel`: RUN, dimmed while
`presence` < 1, off while stopped; the sparkline's heights and hues; the toggle sends `release 9`
for a cue effect and `effect stop fx5` or `effect run fx5` for a programmer effect. F7: GM digits
red during blackout, colours by master kind, step list, fade-time master, `[OUTPUT OFF]` opens the
engine's question. Contract additions. End to end: Space on P1 makes the live snapshot show P1
active.

**Done when.**
- [x] On the club-night show, F1 shows page 1's thirteen slots with live levels, cue colours,
      cues and next cues, and F7 shows every master kind with live levels and beat dots.
- [x] Keyboard only: change page, select a playback, GO, back, fader ±, TAP, BPM ±, blackout,
      release all, every line echoed `ui>`. With the mouse, FLASH holds while the button is down.
- [x] The EFFECTS panel shows the running effects with their waves, and stops and runs a
      programmer effect.
- [x] A fader moved on a MIDI surface or the web remote shows in the TUI within 100 ms.
- [x] Suites green; guide covers F1 B and F7.
- [ ] Manual (the user): busk a song on the TupperDMX rig with the TUI only.

**Done** (2026-10-25); the manual check is the user's.
- Suites: the TUI's 245 tests (`tests/tui`), the whole suite 4149 passed, 1 skipped, 15
  deselected; ruff, format and `mypy` clean. **Perf gates** (`-m perf -s`; the TUI on F1, which
  reads the effects, on the club-night show with the song, chase and effects idle): standalone
  100.1 against 100.0 frames/s bare; under `busk run` 0 overruns of 907 ticks, the console
  process +0.198 core (0.212 against 0.014 bare; Phase 0: +0.138). Within the 0.25 gate, with
  less room: Phases 2–5, which read the output, should watch it.
- **Files** as planned, and: `formats.py` (the compressed selection, `101 thru 104, 301.2`;
  plain, in the boundary test's list), `widgets/panel.py` (`Panel`), `pages/base.py`'s `View`
  (what the pages draw from: the newest of each event, the selected playback, `faders`, the
  colour mode) with `Page.update_view(view, changed)`, so a page redraws only the parts that
  changed. Tests: `test_tui_busk.py`, `test_tui_masters.py`, `test_tui_conversion.py` (the
  bridge's conversion of real busk objects), and additions to the bridge, live bridge,
  commands, e2e and frame tests.
- **Model.** `LiveState.playbacks` (`PlaybackView`); `ShowModel` gains pages with their slots
  as playback numbers, playbacks (`uiColor` read only as `#rrggbb`), cue lists (cues, their
  effects, a chase's rate and direction in busk's words, `bpm x 1 bounce`, with the speed
  master's name only when the show has more than one), groups, presets (with the one colour a
  colour preset gives, white added, else `None`), fixtures with their element counts, and
  masters with their group and steps; `ProgrammerModel.effects` and `.stopped`;
  `EffectsChanged(EffectsModel)`. Cue and programmer effects are made by one function
  (`effect_info`: id and template name).
- **Bridge.** The effects are read only while the page watches them (F1), sent only when they
  change, and sent again once watched anew. A programmer model is made again on a new document
  too (a renamed template), and sent only if it changed.
- **Calls you may veto:**
  - **`faders` defaults to 20, not 10** (the spec's default), so page 1's thirteen slots show,
    as this phase's first box asks. It caps a page's slots; it does not page through them.
  - **Space, ← →, `[ ]` and PgUp/PgDn act on any page** with an empty prompt (spec §6.1), not
    only on F1. While help is open PgUp/PgDn scroll it.
  - **The selected playback follows its slot**: after a page change it is the playback in the
    same slot (else the first). ← → wrap over the page's slots and skip empty ones.
  - **`[ ]` step from the level they last sent** if that was within 0.5 s (the engine has not
    shown it yet), else from the engine's. Each press is a keyed `fader N p%` line, echoed.
  - **FLASH's two lines are echoed** (`ui> flash 3 on`, `ui> flash 3 off`). The spec logs
    nothing, but it predates GAP-04's `flash N on|off`; every other control echoes its line.
  - **Enter on a pane-cursor button runs its line and the cursor stays** (TAP, BPM ±, GO again),
    reading the line afresh (a toggle's follows its state); a pre-fill item (a master bar:
    `master "FX" `, `gm `) goes to the prompt and leaves, as in Phase 0.
  - **Rows:** an idle playback shows `—/5 → Intro`; a fader that is not a level is named after
    the name (`size`, `rate`, `xfade`, `temp`, `no fader`), and a `none` fader has no bar
    control and `—` for its level; the level is amber while the playback releases.
  - **EFFECTS rows** are `P11 fx1` (the playback) or `prog fx5`, the template, the wave and
    `[RUN]`/`[off]`. Every programmer effect is listed; one that runs but is not in `effects`
    (it has no member to drive) shows `[RUN]` dimmed with a flat wave.
  - **MASTERS on F1** has the grand, size and group masters (speed masters have TEMPO,
    fade-time masters are on F7). SELECTION has no `[none]` button (spec B).
  - **F7's panels** go three across from 132 columns, two from 100, one below (at 100 columns
    three across cut the tempo row), set from the page's width rather than the frame's `narrow`
    class. FADE TIME shows `override now 1.6 s` from `EngineSnapshot.fadeTime`; PANIC shows the
    output state.
  - A click on layout A or C logs that it comes in Phase 5.
- **A teardown race fixed.** The app's drain and prompt-context timers did nothing to stop
  them while Textual takes the screens down, so a drain could look for a widget already gone
  (`NoMatches: StatusBar`); Phase 1's busier pages made it show in a test now and then. Both
  return once the app is no longer running (a test covers it).
- **Checked in a real pseudo-terminal** (pyte) on the club-night show, standalone: F1 at
  150×48, 132×44, 100 and 99 columns (B stacks below 100), colours (P1's bar in its cue's warm
  white, the chase's red, the chips), Space, ← →, `]`, PgDn with the selection following to
  page 2's P15, the pane cursor on GO; F7 at 150, 100 and 99 columns.
- **A change made elsewhere** (a line run on the `LiveShow` directly, as a surface does) shows
  in a `LiveChanged` 26 ms after it at the median and 76 ms at most, with the app's 25 ms
  drain (40 moves; `test_a_fader_moved_elsewhere_shows`).

### Phase 2: Program (F2, F6)

**Goal and scope.** Select, set and apply presets: groups, encoders that set and step values,
quick commands, the programmer's contents, preset tiles. Spec §8.2, §8.6.

**Files.** `pages/program.py`, `pages/presets.py`; `widgets/encoders.py` (`EncoderRow`: value,
`[−]`/`[+]`, a bar that sets on click or release, a pending preview until the line is done,
Enter pre-fills), `widgets/programmer.py` (the PROGRAMMER CONTENTS table, which layout A reuses),
`widgets/tiles.py`; additions to `bridge.py` (profile attributes and physical ranges, preset value
summaries, programmer values by fixture, output values), `model.py`, `commands.py`, `config.py`
(quick list).

**Encoders.** Families as busk groups them: INTENSITY (`intensity`), POSITION (`pan`, `tilt`,
±half of `panRange`/`tiltRange`), COLOR (R, G, B and W rows on `color.r` … `color.w`, the colour
presets, and `cto` when present), BEAM (`zoom` over `zoomRange`, `iris`, `frost`), FOCUS
(`focus`), SHUTTER (`strobeRate` over 0..`maxStrobeHz`, a `set shutter ` pre-fill). A row shows
only when some profile in the show has a channel for that attribute. The attribute names and
units are a small table in the TUI, as command words are. A row shows the first selected
fixture's value (spec §8.2): magenta from `ProgrammerStatus.values` (a preset with its value),
else dim from `output` (intensity, pan, tilt, zoom; the colour as one swatch), else `—`. A click
or a release on the bar sends an absolute `set`. `[−]`/`[+]` (±5 %, ±15°) and the wheel (±2 %,
±5°) send `set <attr> by <change>`, and are enabled only while the programmer holds the
attribute for a selected target (Q11).

**Engine lines used.** `sel group N`, `sel + group N`, `sel none`, `set <attr> <value>`,
`set <attr> by <change>`, `set color.r|g|b|w <value>`, `set color.r|g|b|w by <change>`, the quick
list (§3, 17), `blind on` or `blind off` (one toggle), `highlight on|off`, `clear`,
`record cue 1`, `preset <pool> N`; pre-fills `set <attr> `, `set color `, `fade `,
`record preset <pool> N "`. **Reads:** `show` groups, profiles (modes' channel attributes,
`physical`), presets; `programmer` (selection, blind, values with their presets); `output` while
F2 is visible.

**Deferred.** A live encoder drag in one undo step (GAP-06; one `set` on release meanwhile, Q7).

**Tests.** Families follow the show's profiles (no pan channel, no POSITION). A release sends one
`set` in the right unit (`set pan -45`, `set intensity 72%`, a colour component). Values: magenta
from the programmer (a preset with its value), dim from the output, `—` with neither. `[+]` sends
`set intensity by 5%` while the programmer holds intensity and is disabled otherwise; the wheel
sends ±2 % (±5°) and logs nothing. The pending preview clears on `CommandDone`. Enter pre-fills.
Quick commands from config, defaults in the contract test. BLIND is one toggle that follows
`blind`. PROGRAMMER CONTENTS: a row per fixture, a preset by its name, `·` when unset, the empty
state. F6: "applies to" from the selection; only non-empty pools; preview rules (uniform,
`mixed`, preset colour swatch); tile click lines. Contract additions: encoder lines run with a
selection that has the attribute (the club-night heads take `intensity`, `pan`, `tilt`, `zoom`,
`shutter`, `strobeRate`, and refuse `iris`, `cto`, `focus`, which they lack), and `by` lines run
once a value is set.

**Done when.**
- [x] On the TupperDMX show: select a group, set intensity, pan, tilt and a colour component with
      the mouse, step them with `[−]`/`[+]`, apply colour and position presets with the pane
      cursor, and record a cue. Each action is one echoed line and one undo step.
- [x] The selection, the encoder values and PROGRAMMER CONTENTS follow every change, including
      changes made from the prompt and from surfaces.
- [x] Suites green; guide covers F2 and F6, and the drag limit until GAP-06.
- [ ] Manual (the user): build a look on the rig from F2 and F6.

**Done** (2026-10-25); the manual check is the user's.
- Suites: the TUI's 314 tests (`tests/tui`), the whole suite 4219 passed, 1 skipped, 16
  deselected (3 perf, the soak); ruff, format and
  `mypy` clean. The TUI's tests pass on Textual 8.2.0, the floor, too.
- **Perf gates** (`-m perf -s`; club-night show). Standalone, the engine's rate with the TUI
  on F1 and on F2: 100.0 and 99.9 against 100.0 frames/s bare. Under `busk run`, 0 overruns
  in every run, and the console process:

  | Page | Console CPU over a bare frontend |
  |---|---|
  | F1, idle | +0.227 core |
  | F2, idle | +0.180 core |
  | F2, the selected heads moving (P11's Circle) | +0.213 core (first build: +0.307) |

  F1 is unchanged by this phase: Phase 1's commit measures +0.227 today as well (it measured
  +0.198 on the day). The moving case is new in `test_tui_perf.py`: on an idle show F2's
  encoders never redraw. Two changes brought it under the 0.25 gate: the encoder's value cell
  updates without a layout pass (`Static.update(layout=False)`: each update had reflowed the
  screen, 20 times a second), and **the output is read at 10 Hz, not 20** (`OUTPUT_S`; spec
  §9's least for live output), the `out` row of §2's table now says so. On a synthetic
  8 192-element rig the TUI's conversion of one read costs 4.5 ms and its comparison 0.7 ms
  (0.05 core at 10 Hz), on top of busk's own build of the read (10–11 ms, GAP-01): Phase 4's
  F3, which shows every element, should measure it.
- **Files** as planned, and: `attributes.py` (plain, in the boundary test's list: the encoder
  table of busk's attribute words, units, colours and steps; which rows show; ranges; what a
  row reads; the lines; value formats), `pages/program.py`, `pages/presets.py`,
  `widgets/encoders.py`, `widgets/programmer.py`, `widgets/tiles.py`; `controls.py` gains
  `FillPrompt` (a pre-fill from a page), `RunLine.done` (called with the line's success once
  it ran; the app keeps the callbacks by ticket, and only the newest per key),
  `CommandButton(inert=…)` and `StripButton.prefill`. Tests: `test_tui_program.py`,
  `test_tui_presets.py`, and additions to the conversion, commands (contract), config,
  bridge, live bridge, widgets, e2e and perf tests.
- **Model.** `ShowModel.profiles` (`ProfileInfo`: the attributes `set` names, ranges),
  `FixtureInfo.name` and `.profile`, `PresetInfo.values` (each attribute but colour, its value
  where all agree, else `None`); `ProgrammerModel.values` (`HeldValue`: a colour as its
  components, a discrete value as its slot, a preset reference with the preset's name);
  `OutputChanged(OutputModel)` with `ElementOutput` (intensity, colour, pan, tilt, zoom; the
  sources come with F3). `Page.WATCH_OUTPUT`; `View.output` and `View.quick`.
- **Calls you may veto:**
  - **Rows use busk's words**: `intensity`, `color.r` … `color.w`, `cto`, `zoom`, `iris`,
    `frost`, `focus`, `strobeRate`, not the spec's `dim`, `red`, `strobe`.
  - **Which rows show**: the attributes of the channels of the profiles the show's fixtures
    use, the parameter of a function range (`strobeRate` of a strobe), `intensity` where a
    mode dims its colour virtually, `color.w` where a colour channel drives a white emitter.
    A reading of the document (`profile_info`), close to but not the engine's slot rule.
  - **Ranges**: `physical` (pan and tilt centred on 0, `zoomRange`, 0..`maxStrobeHz`), else
    the span of the channels' capabilities (the club spot has no `maxStrobeHz`: its strobe
    range's 1–20 Hz), else ±270°, ±135°, 5–60°, 0–25 Hz. The first selected fixture's
    profile's, else the widest. Bars round to whole percent, whole degrees (a tenth under a
    60° span) and tenths of a hertz.
  - **Steps**: 5 % (wheel 2 %) for levels and components, 15° (5°) for pan and tilt, 2° (1°)
    for zoom, 1 Hz (0.5 Hz) for the strobe rate.
  - **A colour component's bar sets only while the programmer holds a colour** for a selected
    element, as its steps: busk refuses `set color.r 50%` otherwise ("no selected target has
    color to change"). A dim line says so (`set a colour first: a chip, or set color`), and
    the COLOR panel shows the output's colour and the programmer's as swatches, with the
    colour chips and `[set color…]` under them. A component the programmer's colour lacks
    (`w`) reads 0, as `set color.w by` starts from 0.
  - **A click sends one line, on release**, not one on press and one on release as the
    faders do; a drag sends at most every 0.1 s (`DRAG_S`), keyed `set:<attribute>`, and
    logs the last. A `set` that changes nothing adds no undo step (checked), so the release
    line after a drag's last move costs none.
  - **The pending value** shows (magenta) from the send until the line is done and the
    programmer has changed since (or 1 s after it is done); a refused line clears it at once.
  - **BLIND and HIGHLIGHT are toggles after the quick lines**, lit while on, not two lines
    each in the list; then `[fade 0s…]`, a pre-fill. The default quick list is the rest of
    adaptation 17; `[program] quick` in `config.toml` replaces it (a wrong value is reported
    and not used).
  - **Pane cursor on F2**: the group buttons and `[none]`; per row its name (pre-fills `set
    <attribute> `), `[−]` and `[+]` (run; an inert one pre-fills too); the chips and the
    pre-fill buttons; the quick buttons. A click on a row's name pre-fills as Enter does.
  - **PROGRAMMER CONTENTS** has an `other` column (`strobeRate 10Hz · shutter strobe`), shows
    a preset's name for a value from it (with the colour's swatch), `mixed` where a fixture's
    elements differ, and the colour as `r g b` with `w0.25` when it has white. The SELECTION
    count is elements, as F1's.
  - **F6**: pools in the order colour, position, beam, intensity, focus, all; previews with
    units (`-30°/40°`, `mixed/40°` for the club's per-fixture Audience, `zoom 20°`, `▅ 50%`);
    a `+ record` tile per pool pre-fills `record preset <pool> <next> "`. A pool with no
    preset does not show; its first preset is recorded at the prompt (the guide says so).
  - Below 100 columns F2's panels go one under the other (spec §3), as F7's.
- **`ButtonStrip` lays its buttons out itself.** Textual wraps at no-break spaces too, so a
  strip that wrapped split `[highlight on]`; it now breaks only between buttons (its height
  from its own layout), and `button_label` no longer inserts no-break spaces. **Not changed,
  found:** the tab bar has the same problem: at 100 columns `F8 Patch` splits over two
  lines (Phase 0's `NBSP`; its test checks the text, not the wrap).
- **Checked in a real pseudo-terminal** (pyte), standalone: on the TupperDMX show the first
  box above, line by line, the prompt's `undo n` growing by one per action (the group, three
  bar clicks, a chip, the green bar, `[+]`, `[−]`; a position preset recorded at the prompt
  and applied with the colour one from F6's pane cursor; `[record cue 1]`); on the club show
  F2 at 150, 100 and 99 columns, a drag, and F6 with four pools.

### Phase 3: Cues and effects (F4, F5)

**Goal and scope.** Browse cue lists and their cues, go to a cue, record, switch sequence and
chase, edit cells through pre-fills. List cue and programmer effects with their live state and
wave, add them from the show's and the library's templates, stop, run and remove programmer
effects. Spec §8.4, §8.5.

**Files.** `pages/cues.py`, `pages/effects.py`; `widgets/cuetable.py`; `widgets/effects.py`
(Phase 1); additions to `bridge.py` (entries as stored, timing, triggers, cue effects, templates
from `effect_templates`), `model.py`, `commands.py`.

**Engine lines used.** `goto N <cue>`, `go N`, `back N`, `record cue L`, `cuelist L chase bpm x 1`,
`cuelist L sequence`; pre-fills `cue L/C time `, `cue L/C follow `, `cue L/C wait `, `cue L/C go`,
`rename cue L/C "`; `effect add "<name>"`, `effect stop <id>`, `effect run <id>`,
`effect remove <id>`, `go N`/`release N` for a cue effect's playback. **Reads:** `show` cue
lists, playbacks by list, presets (names for references), groups; `effect_templates`;
`programmer` effects and stopped; `effects` while F5 is visible; `snapshot` current cue, state,
level.

**Deferred.** Nothing: every gap this phase needed is closed.

**Tests.** The list browser and the meta line for sequence and chase lists. `▶` follows the
snapshot. Entries as stored (literal, preset name, spread, per target). A row with a playback
sends `goto 9 3`; a list with no playback has no row action. The chase toggle sends `x 1`. Each
pre-fill. F5 rows from cue effects and programmer effects, with targets and rates formatted by
one formatter. The state: `RUN` when `effects` lists the row by `(playback, cue, id)` (a tracked
effect keeps its defining cue) or by programmer `id`, dimmed while `presence` < 1, `off` while
stopped; the sparkline; the live `hz`. The toggle sends `go` or `release` by playback state, and
`effect stop` or `effect run` for a programmer effect. TEMPLATES from `effect_templates`: the
library's marked, defaults shown only where the template has them. Template click and `✕`.
Contract additions.

**Done when.**
- [ ] On the club-night show, list 9 ("Song") shows its five cues with timing and triggers. Going
      to a cue, GO and BACK follow live. A cue can be recorded and its time edited from the
      pre-fill.
- [ ] F5 lists the show's cue effects and the programmer's, with live state and waves. A template
      adds a programmer effect, which its row stops, runs again and removes.
- [ ] Suites green; guide updated.
- [ ] Manual (the user): run a cue stack on the rig from F4.

### Phase 4: Rig (F3, F8, F9)

**Goal and scope.** The rig as tables: fixtures with their live output, the patch and its DMX
map, the routes and surfaces with their state, and the bindings. These are mostly read-only, with
click-to-select and pre-fills for edits. Spec §8.3, §8.8, §8.9.

**Files.** `pages/fixtures.py`, `pages/patch.py`, `pages/surfaces.py`; `widgets/dmxmap.py`;
additions to `bridge.py` (profiles, modes, patches, element patches, routes, surfaces, bindings,
output by fixture), `model.py`, `commands.py`.

**Engine lines used.** `sel fixture N`, `sel + fixture N`, `sel - fixture N`; pre-fills
`fixture N patch `, `fixture N location `, `profile "<name>" category `, `bind "<surface>" `,
`unbind "<surface>" `, `surface "<name>" pickup `. **Reads:** `show` fixtures, profiles (with
category), universes, routes, surfaces, bindings, pages; `output` while F3 is visible;
`programmer` selection; `routes`; `surfaces`; `snapshot` for binding target levels.

**As built.** F3: the spec's columns: the `▸` marker from the selection, the static columns, and
dim, colour, pan, tilt and zoom from `output`, coloured by `source`, with the legend. Shift-click
toggles `sel +` and `sel -`. F8: universes, routes (protocol, address, destination, enabled, and
the state dot with its `detail` and a packet rate), an 8 × 64 map per universe coloured by
category, `╳` on overlaps, hover text `fixture N · ch k/fp` in the hint row, click to select. F9
"Surfaces": surfaces (kind, device or port, pickup, binding count, the state dot with its
`detail`, an open web remote's address) and bindings (input, action, feedback, target level %).

**Deferred.** MONITOR, learn mode and the raw `val` (GAP-13).

**Tests.** F3 rows for single and multi-element fixtures, split patches and unpatched fixtures;
live cells and source colours from an `OutputModel`; the marker and Shift toggling. F8 footprint
cells, overlaps (the TupperDMX show's double-patched heads give two), the used count, hover text,
click line; route states (ok, blinking on new `packets`; failed with its detail; disabled and
ignored dim); category colours, and a profile without a category coloured by profile. F9 rows for
MIDI, OSC and web surfaces and for each input and action kind (fader slot, button, master, tap,
page, blackout, release all, output); surface states and the web remote's address. Contract
additions.

**Done when.**
- [ ] On the TupperDMX show, F3 lists every fixture with live values, F8 shows its two overlaps
      and its route's state, and F9 shows its surfaces with their state and bindings.
- [ ] Suites green; guide updated.
- [ ] Manual (the user): check F8 against the rig's real patch, and F9 while a controller is
      unplugged and plugged in again.

### Phase 5: The other Busk layouts (F1 A, F1 C)

**Goal and scope.** Layout A (console: OUTPUT palette in live colours, PROGRAMMER panel, vertical
faders) and layout C (stage plot from `location`, in live colours with pan arrows and tilt,
compact playbacks, masters, QUICK) as settings next to B. Spec §8.1, layouts A and C. Last
because they reuse the widgets of Phases 1, 2 and 4 (the playback rows, the programmer table,
F3's live cells), and B covers a show on its own.

**Files.** `pages/busk_console.py`, `pages/busk_stage.py`; `widgets/vfader.py` (10 rows × 4
cells, partial top row, drag and wheel), `widgets/fixture_palette.py` (one cell per element in its
output colour and intensity, shared by OUTPUT and STAGE).

**Engine lines used.** Those of Phase 1, plus `sel fixture N`, `sel + fixture N`,
`sel - fixture N`, and the pre-fill
`fixture N location {"x": 0, "y": 0, "z": 0, "rx": 0, "ry": 0, "rz": 0}`. **Reads:** as Phase 1,
plus `show` fixtures, locations and categories, `output` while A or C is visible, and the
`programmer` selection.

**As built.** A: OUTPUT with one row per category (or per profile without one) and one cell per
element in its live colour and intensity, the selection highlighted, click to select; PROGRAMMER
with the selection, colour chips, master bars and the tempo row; PLAYBACKS as vertical faders in
the current cue's colour, with `GO ◂` and FLASH. C: rows by depth (adaptation 6), fixtures placed
by x, glyphs by category in their live colour, a pan arrow and tilt on movers, a "no position"
row with the `location` pre-fill, AUDIENCE at the bottom, compact playbacks, masters with tempo,
QUICK.

**Deferred.** Nothing: every gap this phase needed is closed.

**Tests.** Faders render each level and partial rows; drag, wheel and FLASH lines. Palette cells
for multi-element fixtures, in output colour and intensity, with the selection highlight.
Category rows, and a profile without a category. Stage rows from locations (same depth,
ordering, x scaling, missing locations), glyphs, pan arrows and tilt from the output. Switching
layouts keeps the selected playback and is saved in `state.json`.

**Done when.**
- [ ] A, B and C switch from the header and from `--layout`, and the choice survives a restart.
- [ ] A shows the rig's live output. With locations set on the TupperDMX show, C draws the rig in
      its real order, with the movers' arrows following their pan.
- [ ] Suites green; guide complete for every page.
- [ ] Manual (the user): try A and C on the rig.

---

## 6. Why this order

1. **Foundation first:** every page needs the bridge, the frame, the prompt and the shared
   widgets. Because the prompt runs any line, completes every word and asks before `output off`,
   and the TUI runs under `busk run`, it is usable as a richer `busk run` prompt from Phase 0 on,
   on stage too.
2. **Perform next (F1 B, F7):** at a gig the operator needs playbacks, masters, tempo and
   blackout before anything else. Both pages are fully supported by busk, FLASH included since
   GAP-04. They also share most widgets (bars, digits, beat dots, master bars), so building them
   together avoids doing those twice.
3. **Program (F2, F6):** busking means selecting and applying presets between songs. Both pages
   centre on selection plus a pool of one-click lines. They come before cues because a cue is
   recorded from the programmer.
4. **Cues and effects (F4, F5):** both browse the show's cue data and run what it holds through
   playbacks, and F5 reuses the effect rows and sparklines of Phase 1.
5. **Rig (F3, F8, F9):** setup pages, mostly read-only and used before the show. Patching and
   binding are done in scripts or at the prompt today, so these add the least on stage.
6. **Layouts A and C last:** GAP-01 now feeds their centrepieces (live OUTPUT colours, mover
   arrows), but they reuse the widgets of Phases 1, 2 and 4, and B already covers a show.

---

## 7. Risks

- **R1, the console process.** Under `busk run` the engine has a process of its own (GAP-11), so
  the TUI's rendering no longer competes with the tick. It shares the console process with the
  session, the surfaces and the building of `FixtureOutput`s. On the reference rig, a frontend
  polling `frame`, `output` and `effects` at 20 Hz costs that process 0.25 core (GAP-11). On the
  400-fixture rig, while another thread edited, a control's `fader` line was done 4.1–4.4 ms
  late at the median and 32–45 ms at the 99th percentile; a lower switch interval in the
  console process, one of two engine changes GAP-12 left for a decision, would bring that to
  0.24–0.29 and 14–15 ms. Mitigations: change-driven rendering,
  20 Hz caps, `output` and `effects` read only while a page shows them, and the Phase 0 perf
  gates. Standalone, the old risk stays: `docs/library.md` measured 10 % overrun ticks in one
  process under edits, against 0.05 % in `busk run`; `tune_interpreter=True` helps.
- **R2, message text.** The hint row's syntax lines read the text of `help`. A format change
  degrades them to nothing, but no longer completion (`expected`, GAP-20) or commands. The
  contract and hint tests notice it. The text the engine gives to be shown as it is
  (`confirmation`'s question, `RouteStatus.label` and `detail`, `SurfaceStatus.detail`,
  `EffectTemplateInfo.summary`) is shown, never parsed.
- **R3, command drift.** The spec already disagrees with busk (`dim`, `x1`, `cue L/C go`,
  `+5%`). All UI lines come from `commands.py` and run in the contract test.
- **R4, terminals.** F10 is taken by some terminals (Alt+0 is the spec's alternative). Terminals
  do not report key releases, so there is no momentary flash key: FLASH is momentary with the
  mouse only. Mouse modes may be missing over SSH. Colours are fixed xterm-256 values, and Rich
  maps them to 16 colours on a 16-colour terminal.
- **R5, change detection.** Show changes are noticed by the identity of `LiveShow.show`. That is
  how the session works (copy-on-write) but not a documented promise. As a guard, the bridge also
  re-reads the document after every successful line. GAP-03's `showVersion` would make it
  explicit. The programmer's `version` and the identity of `effect_templates` are documented.
- **R6, start and stop.** Under `busk run`, the run starts and stops the show. Standalone,
  `start()` can take 15 s and `stop()` can hang on a driver; both run off the UI thread, with
  timeouts.
- **R7, restarts under `busk run`.** A TUI that raises is a console crash: `busk run` starts a
  new console and calls `frontend` again on the recovered show, while the engine runs on
  (GAP-11). So the TUI must start cleanly on a running show, carry nothing over but
  `state.json`, and show a flash it held as held (`flash N off` releases it). After an engine
  restart, `seq` counts from 1 again and the first reads of `frame`, `output` and `effects`
  return `None` (§2).

---

## 8. Not planned

Anything the spec marks "proposed" or "not in the prototype" that busk cannot support yet: learn
mode and the MIDI monitor (GAP-13). Inline cell editing (adaptation 7). Attaching the TUI to a
`busk run` that is already running, and detaching again: GAP-11 built `--frontend` only, so the
run ends with the TUI. A theme editor. Mouse-only features are kept to what the spec lists, and
each has a keyboard path (prompt, pre-fill or pane cursor), except FLASH (R4).

---

## 9. Open questions

- **Q1. Typed reads.** The plan reads `snapshot`, `frame`, `output`, `effects`, `programmer`,
  `routes`, `surfaces`, `health`, `show` and `effect_templates` directly, and asks
  `confirmation` and `expected`, all through the bridge only, and sends every action through
  `execute()`. If you meant that even reads must go through `execute()`, most of §2's **S** rows
  would depend on parsing `list …` text, and would become gaps. ANSWER: Use typed reads, all the gaps were built to use that. DONT use execute() and a parser.
- **Q2. No parsing of reply text.** GAP-02 closed BLIND, `PROG n` and `sel n`. Only `undo n` and
  the unsaved-edits marker are left, in the text of `info` (GAP-03). Would you accept a temporary
  parser for these two, removed when GAP-03 closes, or should they wait for it (see Q12)? The plan
  waits. ANSWER: Temporary parser for these two.
- **Q3. Packaging.** `uv_build` only puts `busk` in the wheel. I checked that `busk_tui` is
  left out unless `pyproject.toml` also gets
  `[tool.uv.build-backend] module-name = ["busk", "busk_tui"]`. That is one table beyond "the
  extra and the entry point". May I add it? ANSWER: I don't know, decide by yourself the best choice.
  *(Phase 0: added; the wheel needs it.)*
- **Q4. Dev environment.** `mypy` covers all of `src/` (so `busk_tui` too), and the TUI tests need
  Textual. Either developers run `uv run --extra tui …` (no change, as planned), or the `dev` group
  gets `busk[tui]` (and `pytest-textual-snapshot`, if you want screenshot tests). The second is
  another `pyproject.toml` change. Which do you prefer? ANSWER: Go for second choice, Add busk[tui] to the dev group.
- **Q5. Host.** GAP-11 settled the old question: `busk-tui SHOW` runs under `busk run
  --frontend`, with the watchdog, autosave and recovery. The plan also keeps `busk-tui
  --in-process SHOW`, a `LiveShow` in the TUI's own process, for development and rehearsal: it is
  the only way to run with `--no-output` or `--no-surfaces`, which `busk run` lacks, and it
  starts faster. It costs a branch in `main()` and one in the bridge (start and stop the show, or
  not). Keep it, or `busk run` only? ANSWER: Keep it. But I don't like the term --in-process.
  *(Phase 0: named `--standalone`.)*
- **Q6. FLASH.** *Settled by GAP-04:* FLASH sends `flash N on|off`, a console line, so "console
  lines only" needs no exception.
- **Q7. Encoder drags.** Until GAP-06, I send one `set` on release (one undo step, no live light
  while dragging). The alternative is live sends at about 10 Hz, at the cost of many undo steps.
  Which do you prefer? ANSWER: Live sends at about 10 Hz.
- **Q8. The pane cursor** (§4.5) is an addition to the spec, for keyboard-first operation on
  every page. Keep it?  ANSWER: Yes keep it.
- **Q9. Interim live-output view.** *Dropped:* GAP-01 is closed, and F3 shows the live output
  itself.
- **Q10. Root files.** Is a one-line install mention in `README.md` and an entry in
  `CHANGELOG.md` covered by "docs"? The plan assumes yes, in Phase 0.
- **Q11. Encoder steps without a programmer value.** The spec builds `[−]`/`[+]` from the value
  shown, and GAP-05's note allows an absolute `set` built from the output value where the
  programmer has none. But the output comes after the masters and effects: with the grand master
  at 50 %, an 80 % look shows 40 %, and `[+]` would set 45 %, which is 22.5 % on stage. The plan
  follows the engine's own rule for `set … by` instead: the steps and the wheel act only where
  the programmer holds the attribute, and elsewhere the row shows the output value dim, with its
  steps disabled until a click or a drag sets a value. Agree? ANSWER: Yes agree.
- **Q12. The open gaps.** GAP-03 (Phase 0: `undo n`, the unsaved marker, a quit dialog that
  knows), GAP-06 (Phase 2: live encoder drags in one undo step) and GAP-13 (Phase 4: MONITOR,
  learn mode, the raw `val`). Build the TUI with these deferrals, or close GAP-03 before Phase 0
  and GAP-06 before Phase 2, as the other gaps were closed? ANSWER: No, build TUI with these deferrals. They will be implemented in teh future.
