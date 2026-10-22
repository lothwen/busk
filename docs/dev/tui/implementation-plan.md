# busk TUI: implementation plan

A terminal UI for busk, in a new package `src/busk_tui/`, shipped in the busk distribution
behind the `tui` extra (`pip install busk[tui]`) with its own command, `busk-tui`. Tests in
`tests/tui/`. Written 2026-10-21 against busk 0.1.0 (`3176f99`).

Inputs: the TUI specification and mockups (`busk_tui-specification.md`, `images/`,
`Busk_TUI.html`, outside the repo) and the engine as it is. Companion document:
[`docs/tui/engine-gaps.md`](engine-gaps.md) (GAP-01 … GAP-21).

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

- **"The engine"** is the `busk` package. **Its public interface** is `busk.__all__` (28
  names) and the `TypedDict`s of `busk.model.*` and `busk.commands.types`
  (`docs/library.md`, "What is public").
- **`execute(command)`** is `LiveShow.execute(line: str) -> Reply`. busk has no type named
  `Result`: `execute` returns `Reply(text: str, ok: bool)` and never raises. A refused line has
  `ok=False` and text starting `error: `. Performance lines (`go`, `fader`, `gm`, …) succeed with
  empty text. `submit(command) -> CommandResult(ok, message, issues)` also exists, but the TUI does
  not use it: every action is a console line, echoed in the log, so the UI teaches the CLI
  (spec §2.1).
- **Reads.** The brief says the engine only offers request and response through `execute()`. It
  also has typed, read-only public state, published by reference and safe to read from any
  thread:
  - `LiveShow.snapshot -> EngineSnapshot`: playbacks, masters, tempo anchors, page, blackout,
    output on/off, fade-time override. It is republished on every change, chase steps included.
  - `LiveShow.frame -> DmxFrame`: the newest frame, with its engine `time` and `seq`.
  - `LiveShow.show -> Show`: the committed show document. It is replaced, not mutated, on every
    edit.
  - `LiveShow.warnings`, and the `busk.*` loggers for route and surface news.

  The plan reads these instead of polling text commands (question Q1). Read-only commands
  (`programmer`, `info`, `list …`, `library`, `status`) can also be polled through `execute()`, but
  their replies are text. `docs/library.md` says message text may change in any release, so **the
  TUI never parses reply text**. It shows it verbatim where that is useful (`help`, the F2
  programmer panel), and treats data only available as text as a gap (question Q2).

### 1.2 The boundary

- `src/busk_tui/bridge.py` is the only module that imports `busk`, and it imports only names in
  `busk.__all__`. A test checks this (Phase 0).
- The bridge turns engine objects into the TUI's own frozen view models (`model.py`, no busk
  types). Pages and widgets see only those, and talk to the bridge through a small protocol, so
  tests can swap in a fake.
- **No engine logic in the TUI.** The TUI may format public data, look things up by id or
  number, and do arithmetic on the show document (a fixture's DMX footprint is
  `address … address + footprint − 1`). It may compute a command's argument from a displayed
  value (fader +5 %). It must not resolve looks (priorities, presets per fixture, tracking),
  decode DMX, compute waveforms or tap tempo, or extract data from reply text. A display that
  needs one of those is a gap.
- Outside `src/busk_tui/`, `tests/tui/` and docs, the only change is `pyproject.toml`: the `tui`
  extra and the `busk-tui` script. Packaging needs one more table (question Q3). Nothing in
  `src/busk/` or the engine tests changes.

---

## 2. Engine capability mapping

Every feature, control and displayed value of the spec, mapped to busk. Each one was checked
against `OfflineShow` with `examples/club-night.busk`.

**Class:** **S** supported, **P** partially supported, **N** not supported.
**Live source:** where a changing value comes from, and so how it is polled:

| Source | How it is read | Rate | Change detection |
|---|---|---|---|
| `snap` | `LiveShow.snapshot` (typed) | 20 Hz | `seq` |
| `frame` | `LiveShow.frame` (typed): engine `time`, `seq` | 20 Hz | `seq` |
| `doc` | `LiveShow.show` (typed document) | identity check at 20 Hz, and after every successful line | identity |
| `query` | a read-only line through `execute()`; text only, never parsed | on demand | text equality |
| `log` | records of the `busk.*` loggers | pushed | n/a |
| `UI` | the TUI's own state | n/a | n/a |
| — | not available | n/a | n/a |

### 2.1 Frame, prompt and global input (spec §5–§7)

| Spec item | busk | Class | Live source | Gap |
|---|---|---|---|---|
| Show name | `show.meta.title` | S | `doc` | |
| Network TX per route | routes listed in `show.output.routes`; their state only as log records | P | `doc`, `log` | GAP-07 |
| `GM %` (amber < 100) | `EngineSnapshot.grandMaster` | S | `snap` | |
| `BPM` and beat dot | `SpeedStatus.bpm`; beat = `SpeedStatus.beats(frame.time)` (public method) | S | `snap` + `frame` | |
| `FADE` | programmer fade: `programmer` text only. busk also has a fade-time master override: `EngineSnapshot.fadeTime` | P | `query` / `snap` | GAP-02 |
| `PROG n` | `programmer`, `info` text | P | `query` | GAP-02 |
| BLIND chip | `programmer`, `info` text | P | `query` | GAP-02 |
| BLACKOUT chip | `EngineSnapshot.blackout` | S | `snap` | |
| *(busk)* output off (panic) | `EngineSnapshot.outputEnabled` | S | `snap` | |
| *(busk)* current page | `EngineSnapshot.page` | S | `snap` | |
| Clock | n/a | S | `UI` | |
| Log: `busk>` / `ui>` echo | n/a | S | `UI` | |
| Log: result and error lines | `Reply.text`, `Reply.ok` | S | per line | |
| Log: info lines | TUI messages, plus `busk.*` log records shown verbatim | S | `log` | |
| Prompt context `sel n` | `programmer` text | P | `query` | GAP-02 |
| Prompt context `P1` | selected playback, TUI state | S | `UI` | |
| Prompt context `undo n` | `info` text | P | `query` | GAP-03 |
| Syntax hint (§7.2) | text of `help`: top-level lines have a 4-space indent | S | once, at start | (GAP-20) |
| Tab completion, first word | the same index | S | | (GAP-20) |
| History ↑ ↓, Esc, Enter | n/a | S | `UI` | |
| Space → `go N` | `go N` | S | | |
| ← → select playback | the current page's slots | S | `snap`, `doc` | |
| `[` `]` → fader ±5 % | `fader N 72%`, current level `PlaybackStatus.faderLevel` | S | `snap` | |
| Shift-click toggles in/out | `sel + fixture N`, `sel - fixture N`; choosing which one needs the selection | P | `query` | GAP-02 |
| Drag faders and masters | `fader`, `gm`, `master`: performance commands, never on the undo timeline | S | | |
| Drag encoders, one undo step | each `set` is one undo step; nothing groups them | P | | GAP-06 |
| Wheel on faders and masters | `fader`/`master` with the current level | S | `snap` | |
| Wheel and `[−]`/`[+]` on encoders | needs the current value; `set intensity +5%` stores an absolute 5 % | N | | GAP-05, GAP-02 |
| FLASH (momentary) | typed `FLASH` command through `submit()` only; no console line | P | | GAP-04 |
| Undo / redo (§6.3) | `undo`, `redo` (the engine keeps 1000 steps) | S | | |
| `quit` | `execute("quit")` returns empty text; no public signal | P | | GAP-18 |
| Confirmation before `output off` | internal (`Console.confirmation`) | N | | GAP-10 |
| Help overlay content (§8.10) | `help` | S | once | |

### 2.2 F1 Busk (spec §8.1)

| Spec item | busk | Class | Live source | Gap |
|---|---|---|---|---|
| Header `page 1` | `EngineSnapshot.page` (number, name) | S | `snap` | |
| `playbacks 1–N` (4–20) | the slots of the current page (`show.pages[].slots`), playbacks by number when the show has no page | S | `doc`, `snap` | |
| Header `sel …` | `programmer` text | P | `query` | GAP-02 |
| `Pn`, name | `PlaybackStatus.number`, `.name` | S | `snap` | |
| Cue position `cur/total`, or `chase n` | `.cue`, `.cueCount`, `.chase`; position = index of the cue number in its list | S | `snap`, `doc` | |
| Current cue name | `.cueName` | S | `snap` | |
| Next cue name | `.next` (cue number), name from the list | S | `snap`, `doc` | |
| Chase rate and direction | `cueList.chase` (`bpm` master × multiplier, or Hz; direction) | S | `doc` | |
| Level | `.faderLevel`, meaning given by `.fader` (master, crossfade, rate, size, temp, none) | S | `snap` | |
| Colour = current cue colour | not available; `playback.uiColor` (static) exists | P | `doc` | GAP-17 |
| Empty slots `·` `—` | `None` in `page.slots` | S | `doc` | |
| Fader drag, wheel, `[ ]` | `fader N <p>%` | S | | |
| GO, ◂ | `go N`, `back N` | S | | |
| FLASH (hold) | see §2.1 | P | | GAP-04 |
| `Pn` click | TUI state | S | `UI` | |
| Fixture swatch click | `sel fixture N`; Shift: `sel + fixture N` | S/P | | GAP-02 |
| Colour chip | `preset color N` | S | `doc` | |
| Group button | `sel group N`; Shift: `sel + group N` | S | `doc` | |
| Master bars | `gm <p>%`, `master "<name>" <p>%`; levels `EngineSnapshot.masterLevels` | S | `snap`, `doc` | |
| `[TAP]` | `tap "<name>"` | S | | |
| `[B.O.]` / `[BLACKOUT]` toggle | `blackout on\|off`; state `EngineSnapshot.blackout` | S | `snap` | |
| A: OUTPUT colours and levels | not available | N | — | GAP-01 |
| A: one row per fixture type | profiles have no category; rows by profile | P | `doc` | GAP-16 |
| A: PROGRAMMER summary | `programmer` text | P | `query` | GAP-02 |
| B: TEMPO `[−]` `[+]` | `bpm "<name>" <n>` | S | `snap` | |
| B: EFFECTS rows | cue effects in the document; programmer effects only as text | P | `doc`, `query` | GAP-02 |
| B: sparkline, RUN/off | not available | N | — | GAP-09 |
| B: RUN/off click | cue effect: its playback, `go N` / `release N`; programmer effect: no stop | P | | GAP-14 |
| C: fixture positions | `fixture N location {"x":…,"y":…,"z":…,"rx":0,"ry":0,"rz":0}`, then `fixture N location.x <m>`. The spec's `plot.row` is refused (`no key 'plot'`) | S | `doc` | |
| C: pan arrow and tilt | not available | N | — | GAP-01 |
| C: glyph per type | no category | P | `doc` | GAP-16 |

### 2.3 F2 Program (spec §8.2)

| Spec item | busk | Class | Live source | Gap |
|---|---|---|---|---|
| Selection text and count | `programmer` text | P | `query` | GAP-02 |
| `[N Name]` group buttons, `[none]` | `sel group N`, `sel + group N`, `sel none` | S | `doc` | |
| Encoder families | busk attributes, by the families of its registry: `intensity`; `pan`, `tilt`; `color` (set whole), `cto`; `zoom`, `iris`, `frost`; `focus`; `shutter`, `strobeRate`. The spec's `dim`, `red`…`white` and `strobe` are not busk attributes (`unknown attribute 'dim'`) | S | `doc` | |
| Encoder value: programmer (magenta) or output (dim) | `programmer` text / not available | P/N | `query` / — | GAP-02, GAP-01 |
| `[−]` `[+]`, wheel | no relative values | N | | GAP-05 |
| Drag → `set` | `set <attr> <value>`, absolute; range from the profile (`physical.panRange`, `tiltRange`, `zoomRange`, `maxStrobeHz`), else 0..1 | S | `doc` | GAP-06 |
| Red, green, blue, white rows | colour is set whole: `set color r g b [w x]` | P | | GAP-05 |
| `quick` row | lines exist, in busk syntax (§3) | S | | |
| `blind on\|off` toggle | `blind on`, `blind off`; a single toggle needs the state | P | `query` | GAP-02 |
| PROGRAMMER CONTENTS table | `programmer` text | P | `query` | GAP-02 |

### 2.4 F3 Fixtures (spec §8.3)

| Spec item | busk | Class | Live source | Gap |
|---|---|---|---|---|
| `#`, name, profile, `×N`, mode, patch `U.A` (red `—` unpatched) | fixtures, profiles, `mode.elements`, `mode.footprint`, `patch`, `elementPatch`, universes | S | `doc` | |
| dim, colour, pan, tilt, zoom (live) | not available | N | — | GAP-01 |
| Source colouring, legend | not available | N | — | GAP-01 |
| `▸` selected marker | `programmer` text | P | `query` | GAP-02 |
| Row click, Shift-click | `sel fixture N`, `sel + fixture N` | S/P | | GAP-02 |

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
| Programmer effects (ids like `fx5`) | `programmer` text | P | `query` | GAP-02 |
| `wave` sparkline, `state` | not available | N | — | GAP-09 |
| State click | cue effect: its playback `go N` / `release N`; programmer effect: none | P | `snap` | GAP-14 |
| `✕` | `effect remove <id>` (programmer effects) | S | | |
| TEMPLATES: the show's | `show.effects` (name, layers) | S | `doc` | |
| TEMPLATES: built-in library | `library` text only | P | `query` | GAP-15 |
| Template click | `effect add "<name>"`, with the library's defaults (the spec's `bpm x1 size 0.6` is refused and invents values) | S | | |

### 2.7 F6 Presets (spec §8.6)

| Spec item | busk | Class | Live source | Gap |
|---|---|---|---|---|
| "applies to" the selection | `programmer` text | P | `query` | GAP-02 |
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
| *(busk)* panic | `release all [<s>]`, `output on\|off` | S | `snap` | GAP-10 |

### 2.9 F8 Patch (spec §8.8)

| Spec item | busk | Class | Live source | Gap |
|---|---|---|---|---|
| UNIVERSES: U, name, fixture count, used `n/512` | universes, fixture patches, `mode.footprint`, `elementPatch` | S | `doc` | |
| ROUTES: U, protocol, address, destination | `output.routes[]`: sACN, Art-Net, DMX-USB, enabled | S | `doc` | |
| TX indicator | log records only | P | `log` | GAP-07 |
| DMX MAP 8 × 64, start `█`, rest `▓`, overlap `╳` | patches and footprints | S | `doc` | |
| Colour by fixture type | no category; by profile | P | `doc` | GAP-16 |
| Hover `fixture N · ch k/fp`, click selects | `sel fixture N` | S | | |

### 2.10 F9 MIDI (spec §8.9)

| Spec item | busk | Class | Live source | Gap |
|---|---|---|---|---|
| SURFACES: name, kind, binding count | `surfaces[]` (midi, osc, web), `bindings[]` | S | `doc` | |
| Status dot | log records only | P | `log` | GAP-08 |
| MONITOR | not available | N | — | GAP-13 |
| BINDINGS: surface, type, channel, number, target | `bindings[]`: input (cc, note, osc, clock), action, feedback | S | `doc` | |
| `val` | the target's level (fader slot → the playback on the current page; master) instead of the raw MIDI value | P | `snap` | GAP-13 |
| Learn mode | not available | N | — | GAP-13 |

### 2.11 Spec §9, "Data the engine must expose"

| Data | Class | How | Gap |
|---|---|---|---|
| Fixture output, ≥ 10 Hz | N | n/a | GAP-01 |
| Playbacks (incl. chase steps) | S | `snap`, republished on every change | |
| Masters, beat phase ≥ 20 Hz | S | `snap` + `frame.time` at 20 Hz | |
| Programmer | P | text only | GAP-02 |
| Effects | P | cue effects in `doc`; programmer effects as text; runtime not available | GAP-02, GAP-09 |
| Show structure | S | `doc`; profiles: the `ProfileLibrary` the bridge creates; effect library as text only | GAP-15 |
| Events: command results | S | `Reply` of each line the TUI sends. Changes made by surfaces or the web remote are seen through polling, not as events | |
| Events: MIDI input | N | n/a | GAP-13 |
| Events: route TX status | P | log records | GAP-07 |
| Events: undo depth | P | `info` text | GAP-03 |

---

## 3. Spec adaptations

Decisions taken because the engine works differently from the mockup. Each can be vetoed. Where
they answer one of the spec's open questions (§10 of the spec), that is noted.

1. **busk names and syntax everywhere.** `intensity`, not `dim`. Colour is `set color r g b
   [w x]`. The strobe is `shutter` (discrete) and `strobeRate` (Hz). Chase and effect rates use
   `bpm x 1`, not `x1`. The UI shows the same words the operator types.
2. **Going to a cue is `goto N <cue>`**, on the playback that runs the list. In busk,
   `cue L/C go` sets the cue's trigger. F4 offers it only as an edit pre-fill. A list that no
   playback runs has no go-to action: its rows say "assign the list to a playback first".
3. **GO does not raise a fader at 0** (spec open question 5). busk activates the playback and
   leaves the level, as consoles usually do. The TUI does not add a second command.
4. **F1 shows the current engine page** (spec open question 2). The playbacks are the current
   page's slots. The page shows in the F1 header and in a status-bar slot (`PAGE 1 Main`).
   PgUp/PgDn on an empty prompt send `page prev`/`page next`. A show with no pages lists playbacks
   by number. The `faders` setting (4–20) caps how many slots show.
5. **Layout B (stack) is the default** (spec open question 1). It is the only layout busk can fill
   today: A's OUTPUT grid and C's pan arrows need GAP-01. A and C ship in Phase 5 as settings.
6. **The stage plot uses `fixture.location`** (spec open question 3): x right, y downstage, z up,
   in metres. Rows are fixtures with the same depth (y, rounded to 0.1 m), upstage at the top,
   with x along the row. Rows are labelled by position (`y 2.0 · z 5.0`), because busk has no
   truss names.
7. **Cue cells are edited by prompt pre-fill only** (spec open question 4). Selecting a cell puts
   `cue L/C time ` (or `follow `, `wait `) in the prompt.
8. **Fixture types become profiles** until GAP-16: OUTPUT rows, stage glyphs and DMX-map colours
   go by profile.
9. **Playback colour is `uiColor`** until GAP-17. It is a free string (`playback 1 uiColor
   "#ff8800"`) and is used when it parses as a colour.
10. **Cue lists are `sequence` or `chase`.** There is no "flash" kind.
11. **All six preset pools** show when they have presets.
12. **Two kinds of effects.** Programmer effects (`effect add`, ids like `fx5`, removed with
    `effect remove fx5`) and cue effects (ids unique within their cue). The RUN/off click on a cue
    effect sends `go N` / `release N` to its playback, instead of `fader N 100%|0%`. A template
    click sends `effect add "<name>"` and lets the library's defaults apply.
13. **F9 is "Surfaces"**: MIDI, OSC and the web remote.
14. **F7 adds fade-time masters and the panic controls** (`release all`, `[OUTPUT OFF]` with a
    confirmation, `[OUTPUT ON]`).
15. **Status bar additions.** An `OUTPUT OFF` chip (red) and `PAGE`. An `ENGINE` chip when frames
    stop (GAP-21). `FADE` shows the fade-time master override until GAP-02 provides the programmer
    fade.
16. **Performance commands are never undone** in busk (faders, GO, masters). The spec's "one
    snapshot at drag start" only matters for encoders (GAP-06).
17. **Quick-command defaults in busk syntax.** `set intensity spread 0 to 1`, `… center`,
    `set pan spread -90 to 90`, `set tilt 45`, `highlight on`, `highlight off`, `record cue 1`,
    `clear`, `blind on`, `blind off`. The spec's `set dim breakup` is dropped: `breakup` is a gobo
    slot in busk.
18. **`help` typed at the prompt opens the overlay.** The line goes to the engine and its reply
    fills the overlay. A line that is exactly `quit` opens the TUI's quit dialog and is not sent
    (GAP-18).
19. **No result line for performance commands.** busk replies with empty text, so the spec's
    sample results (`P1 → cue 2 "Peach"`) do not appear. The engine log and the panes show the
    effect.
20. **Bindings `val` is the target's level in %**, not the raw MIDI value (GAP-13).

---

## 4. Architecture

### 4.1 Threads and data flow

```
 terminal ─ Textual app (UI thread, asyncio): frame, pages, widgets
              │ send(line, origin, key)        ▲ drain() every 25 ms (non-blocking)
              ▼                                │ BridgeEvents
     ┌──────────────────────── bridge.py ─────┴────────────────────────┐
     │ command worker thread : runs LiveShow.execute(line), one at a  │
     │                         time, in order; coalesces control moves │
     │ reader thread, 20 Hz  : reads snapshot, frame, show, warnings;  │
     │                         converts to view models only on change  │
     │ logging handler       : on the "busk" logger, INFO and up       │
     │ event queue           : SimpleQueue → drained by the UI         │
     └──────────────────────────────┬──────────────────────────────────┘
                                    ▼
          busk.LiveShow: engine, output, monitor, feedback and surface threads
```

- The UI thread never calls the engine and never waits for the bridge. `send()` queues and
  returns a ticket. `drain()` returns what has arrived. Reading a few references and comparing a
  `seq` is all the polling costs the UI.
- The bridge has no Textual import. It is tested on its own.
- Rendering is change-driven: a widget refreshes only when its slice of the view model changes.
  The exceptions are the beat dots and the busy indicator (20 Hz) and the clock (1 Hz). This
  keeps the interpreter free for the engine thread (risk R1).

### 4.2 Package layout

```
src/busk_tui/
  __init__.py        version (importlib.metadata "busk"); no busk import
  __main__.py        python -m busk_tui
  app.py             main(): arguments, load errors, BuskApp (Textual App): frame, pages, keys, drain timer
  bridge.py          the engine boundary: lifecycle, command worker, reader, conversion, log capture
  model.py           frozen view models, BridgeEvent types, the BridgeLike protocol (no busk, no Textual)
  commands.py        builders for every line the UI sends (fader(3, 0.72) → "fader 3 72%")
  hints.py           help index: hint row, first-word completion
  colors.py          palette (§4.1) and output-colour quantisation (§4.2)
  config.py          options, config.toml (read-only), state.json (last page, layout)
  nav.py             the pane cursor (keyboard navigation inside a page, §4.5)
  busk.tcss          styles
  widgets/           frame.py (StatusBar, TabBar, KeyLegend), prompt.py (Prompt, HintRow),
                     log.py, help.py, controls.py (CommandButton, Chip), bars.py (HBar),
                     digits.py (BigDigits, BeatDots), swatch.py, then per phase
  pages/             base.py (Page), placeholder.py, then one module per page
```

### 4.3 The bridge

**UI-facing API** (`BridgeLike` protocol in `model.py`; the real `Bridge` and the tests'
`FakeBridge` implement it):

| Member | What it does |
|---|---|
| `start()` | Starts the threads. The worker constructs the `LiveShow`, starts it (up to 15 s, `SETTLE_S`) and runs `help` once. Never blocks the caller. |
| `stop(timeout=5.0)` | Idempotent. Stops the reader, lets the worker finish its current line, drops queued lines, calls `LiveShow.stop()` (routes send their last frame and terminate the streams). Gives up after `timeout` with a warning. |
| `send(line, origin, key=None) -> int` | Queues a line. `origin`: `typed`, `ui` or `internal` (internal lines are not echoed). With a `key` (`fader:3`), a newer line replaces a queued, unsent line with the same key. |
| `drain() -> list[BridgeEvent]` | Everything that arrived since the last call, in order. Only the newest `LiveChanged` of a batch is kept. |
| `busy -> Busy \| None` | The line running now and when it started. |
| `help_lines -> tuple[str, …]` | The text of `help`, once known. |

**Events** (`model.py`): `EngineStarting`, `EngineRunning(title, warnings)`,
`EngineFailed(message)`, `EngineStopped`, `CommandDone(ticket, line, origin, ok, lines, seconds)`,
`LiveChanged(LiveState)`, `Beat(time, beats)` (20 Hz), `ShowChanged(ShowModel)`,
`EngineNews(level, text)` (log records), `EngineStalled(stalled: bool)`, `QueryText(name, text)`
(the verbatim `programmer` panel).

**View models.** `LiveState` has `seq`, `gm`, `blackout`, `outputEnabled`, `page`, `fadeTime`, the
playbacks (number, name, state, level, flash, fader function, chase, cue, cue name, next, cue
count, progress), master levels by name, and speed masters (name, bpm, multiplier, level).
`ShowModel` has the parts each phase needs, keyed by user-facing numbers and names, never ids:
title, universes, routes, fixtures, profiles, groups, presets, cue lists, playbacks, pages,
masters, surfaces, bindings and effect templates. Each phase adds the fields it uses.

**Failure handling.** The UI is never frozen and never crashed by the engine side:

| Situation | Behaviour |
|---|---|
| A line takes long (`save`, `source`, a big edit) | Prompt context shows `⧗ <line> 1.4s` after 0.3 s. Input, tab switching and the live panes keep working. Later lines queue, and control moves coalesce. |
| `execute()` raises (it should not) | `CommandDone(ok=False)` with `internal error: <type>: <message>`. The traceback goes to the TUI's debug log file. The worker carries on. |
| The show does not load | `main()` prints the issues (`path: message`) to stderr and exits 2, before Textual starts. |
| `LiveShow()` or `start()` fails | `EngineFailed`: a full-screen message with the reason and `q` to quit. |
| No new frame for 0.5 s | `EngineStalled(True)`: a red `ENGINE` chip. It clears when frames resume. |
| `stop()` hangs | After the timeout, a warning on stderr and exit anyway (the threads are daemons). |
| The UI raises | `main()` runs the app inside `try/finally: bridge.stop()`, so the output is always terminated. SIGTERM and SIGHUP quit the same way. |
| Ctrl+C | Clears a typed line. On an empty prompt it says how to quit, and a second Ctrl+C opens the quit dialog, as in `busk run`. |

### 4.4 The frame and global keys

The frame follows spec §5. The prompt always has text focus. Global keys act only on an empty
prompt, except the F-keys, Alt+digits and Esc.

| Key | Action | Origin |
|---|---|---|
| F1–F9, Alt+1–9 | switch page, close help | spec |
| F10, Alt+0, `?` (empty prompt) | toggle help | spec |
| Esc | close help, else leave the pane cursor, else clear the prompt | spec + §4.5 |
| Enter, ↑ ↓, Tab | run, history, complete the first word | spec |
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

- **Pure units, no Textual:** `hints.py`, `commands.py`, `colors.py`, `config.py` and the bridge's
  conversion (fed with real busk objects from `OfflineShow`; tests may import busk).
- **Bridge:** against a stub show object whose `execute` can sleep, fail or raise, for the
  worker, coalescing, ordering, busy, stall and shutdown. A few tests use a real
  `LiveShow(output=False, surfaces=False)` on the club-night show built in a temporary directory.
- **UI:** Textual's `App.run_test()` and `Pilot` with `FakeBridge`. Press keys, click, then
  assert the lines sent and the text widgets render.
- **Command contract:** every line `commands.py` can build runs on an `OfflineShow` of
  `examples/club-night.busk` and must be accepted. This catches spec-versus-engine drift such as
  `x1` and `dim`. Each phase adds its builders to the table.
- **Boundary:** an AST scan checks that only `bridge.py` imports `busk`, only names in
  `busk.__all__`, and that `model.py`, `commands.py`, `hints.py`, `colors.py` and `config.py`
  import neither busk nor Textual.
- **End to end:** the real bridge and the app, headless, on a real `LiveShow(output=False)`:
  type `fader 1 50%` and see the playback row show 50.
- **Performance** (opt-in, `-m perf`): the engine's frame rate (`frame.seq` over wall time) with
  the TUI running headless at full refresh, against a bare `LiveShow`. The gate is set in Phase 0
  from measurements (risk R1).
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
uv run --extra tui python -m busk_tui examples/tupperdmx/tupper-demo.show
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

**Goal and scope.** `busk-tui SHOW` opens the full frame on a live engine: status bar, tabs,
log, prompt with hints and completion, help overlay, placeholder pages. It has the bridge, the
shared widgets, configuration, and the test harness. Spec §2, §3, §4.1, §4.3 (panel, button, tab,
horizontal bar, status chip, big digits, beat dots, table styling), §5, §6.1, §6.2 (click, drag
and wheel plumbing), §6.3 (through `undo`/`redo` lines), §7, §8.10, §9 (polling).

**Steps.**

0.1 **Skeleton and packaging.** `pyproject.toml`: `tui = ["textual>=8.2"]` (floor confirmed with
`--resolution lowest-direct`, as Phase 8 did), `busk-tui = "busk_tui.app:main"`, and the
build-backend `module-name` list (Q3). `__init__.py`, `__main__.py`, `app.py` with
`--version`. *Verify:* `uv build --wheel` contains `busk_tui/` and the script.
`tests/test_packaging.py` still passes.

0.2 **Bridge core.** `model.py`, `bridge.py`: load errors, `ProfileLibrary(--library dirs)`,
`LiveShow(show, path=…, library=…, output=…, surfaces=…, state_dir=…, tune_interpreter=True)`, the
worker, the reader, the log handler, the events of §4.3. Phase 0's conversion: title, routes,
universes, masters, pages, speed masters. *Verify:* the bridge tests, stub and live.

0.3 **App shell.** Frame layout, `busk.tcss` with the palette, `StatusBar`, `TabBar`,
`KeyLegend`, `Page` base and placeholders, F-keys and Alt+digits, reflow below 100 columns.
*Verify:* Pilot tests switch every page. Manual check at 100×30 and 150×48.

0.4 **Command line.** `Prompt` (history, Esc, Tab, `quit` intercept), `HintRow`, `LogView` (line
types of spec §7.3, `busk.*` records as info and warning lines, bounded to 2000 lines, auto-scroll),
prompt context (`P<n>`, page, busy). *Verify:* the prompt tests.

0.5 **Help overlay.** F10, `?`, typed `help`, Esc and outside click close it. It holds the `help`
text and the key grid. *Verify:* Pilot tests, prompt usable while it is open.

0.6 **Shared widgets.** `CommandButton` (`[LABEL]`, intent colour, runs a line), `Chip`, `HBar`
(click, drag with coalesced sends and one log line on release, wheel, ⅛ cells), `BigDigits`,
`BeatDots`, `Swatch`, `colors.py`, `commands.py` (Phase 0 builders: `help`, `undo`, `redo`),
`nav.py`. *Verify:* widget and colour tests.

0.7 **Configuration.** Options: `SHOW`, `--no-output`, `--no-surfaces`, `--library DIR`
(repeatable), `--state-dir`, `--layout A|B|C`, `--faders N`, `--colors auto|256|16|truecolor`,
`--config FILE`. Also `$XDG_CONFIG_HOME/busk-tui/config.toml` (quick commands, defaults) and
`$XDG_STATE_HOME/busk-tui/state.json` (last page and layout; unreadable or unwritable is
ignored). *Verify:* config tests.

0.8 **Hardening and docs.** The failure behaviours of §4.3, the quit dialog, signals, the perf
check, and `docs/tui/guide.md` (install, start, frame, keys, "for a show on stage use `busk run`").
*Verify:* the failure tests and the manual check below.

**Files.** `pyproject.toml`; `src/busk_tui/{__init__,__main__,app,bridge,model,commands,hints,
colors,config,nav}.py`, `busk.tcss`; `widgets/{__init__,frame,prompt,log,help,controls,bars,
digits,swatch}.py`; `pages/{__init__,base,placeholder}.py`; `tests/tui/{conftest,tui_fakes}.py`,
`tests/tui/test_tui_{boundary,bridge,bridge_live,hints,commands,colors,widgets,frame,prompt,help,
config,e2e,perf}.py`; `docs/tui/guide.md`.

**Engine lines used.** Any typed line; `help`; `undo` and `redo` (typed). `quit` is intercepted.
**Reads:** `snapshot` (grandMaster, blackout, outputEnabled, page, speed, fadeTime), `frame` (time,
seq), `show` (meta.title, output.routes, universes, masters, pages), `warnings`, `busk.*` logs.

**Deferred.** `PROG`, BLIND, programmer `FADE`, `sel n` (GAP-02); `undo n`, unsaved marker
(GAP-03); route dots (GAP-07); confirmation of typed `output off` (GAP-10); stage safety net
(GAP-11, banner instead); a second lane for performance lines (GAP-12, busy indicator instead);
the quit signal (GAP-18, intercept instead); full completion (GAP-20); engine health (GAP-21,
frame watch instead).

**Tests.**
- Boundary scan (§4.6).
- Bridge, stub: lines run in order; `send()` returns at once while a line sleeps 5 s; `busy` is
  set and cleared; a raising `execute` gives `internal error` and the next line still runs;
  coalescing keeps only the newest unsent `fader:3`; `LiveChanged` only on a new `seq`;
  `ShowChanged` only on a new document; stall after 0.5 s without frames, cleared after; `stop()`
  twice is harmless; `stop()` honours its timeout; a failing `start()` gives `EngineFailed`.
- Bridge, live: `start()` reaches `EngineRunning`; `fader 1 50%` gives a `LiveChanged` with 0.5
  within 1 s; `help_lines` is not empty; after `stop()` no `busk-*` thread is alive.
- Hints, against the real `help` text: alternatives split on `|`
  (`clear | blind on|off | …` indexes `blind`), up to two lines, a prefix lists candidates,
  `unknown command`, the empty-prompt text; completion of a unique and an ambiguous word (the
  candidates go to the log as info).
- Commands: formatting (levels as whole percent, names quoted, a name containing `"` refused)
  and the contract test.
- Colours: §4.2 cases (below 1.5 % gives 236, cube against grey ramp, 16-colour nearest).
- Frame (Pilot + FakeBridge): F1–F10 and Alt+1–0; help open and close; a typed line echoed with
  `busk>` and sent; result, error and info styles; history; Esc; global keys ignored while text
  is typed; layout below 100 columns; the status bar from a `LiveState` (GM amber, blackout,
  output-off and stall chips, beat dot timing); the busy indicator; the quit dialog and Ctrl+C.
- Config: defaults, overrides, bad TOML (defaults and an info line), state round trip,
  unwritable state directory.
- End to end and perf, as in §4.6.

**Done when.**
- [ ] `busk-tui SHOW` and `python -m busk_tui SHOW` open the frame at 100×30 and 150×48, and every
      page is reachable with F-keys and with Alt+digits.
- [ ] Typed lines run, and results, errors and engine news show with the spec's prefixes. Hints,
      completion and the help overlay work, and the prompt stays usable over help.
- [ ] The status bar follows the live engine: title, routes (no dots), GM, BPM and beat dot,
      fade-time override, blackout, output off, page, clock.
- [ ] A 5 s line (stub) never freezes keys, page switching or the beat dots. No engine-side
      exception reaches the UI. Every way of quitting stops the `LiveShow`.
- [ ] The boundary, contract, TUI and engine suites are green, with ruff, format and mypy clean.
      The wheel contains `busk_tui` and `busk-tui`.
- [ ] The perf gate is recorded in this plan's Done note.
- [ ] Manual (the user): on the TupperDMX rig with the simulator, `go 1`, `gm 50%`,
      `blackout on`/`off`, then quit, by `quit` and by Ctrl+C twice: the terminal is restored and
      the simulator stops receiving.

### Phase 1: Perform (F1 layout B, F7)

**Goal and scope.** Everything needed to run a show from the TUI: playbacks on the current page,
masters, tempo, blackout and panic, with the keyboard first. Spec §8.1 (header, playback data,
control table, layout B), §8.7, and the F1 keys of §6.1. The layout switch is drawn; A and C say
"Phase 5".

**Files.** `pages/busk.py` (header, layout host, selected playback), `pages/busk_stack.py`
(layout B), `pages/masters.py`; `widgets/playbacks.py` (`PlaybackRow`, and the compact row Phase 5
reuses), `widgets/tempo.py` (digits, dots, TAP, −/+), `widgets/masters.py` (master bars,
blackout, panic), `widgets/quick.py` (group buttons, colour chips); additions to `bridge.py`,
`model.py` and `commands.py`; tests below.

**Engine lines used.** `go N`, `back N`, `fader N <p>%`, `gm <p>%`, `master "<name>" <p>%`,
`blackout on|off`, `tap "<name>"`, `bpm "<name>" <n>`, `page prev|next|N`, `sel group N`,
`sel + group N`, `preset color N`, `release N`, `release all`, `output off` (after confirming),
`output on`. **Reads:** `snapshot` playbacks, page, masterLevels, speed (+ `beats(frame.time)`),
blackout, grandMaster, fadeTime, outputEnabled; `show` pages, playbacks (cueListId, fader,
uiColor), cue lists (cue order and names, mode, chase), masters (kind, group, steps), groups,
colour presets.

**Layout B as built.** PLAYBACKS rows (`Pn`, name, level bar coloured by `uiColor`, level,
`cue/total cue → next` or `chase n rate direction`, `[GO] [◂]`, `[FL]` disabled). The right column
has TEMPO for the first speed master, then MASTERS with `[BLACKOUT]`, then EFFECTS (playbacks whose
lists hold cue effects, with the playback state and a `go`/`release` toggle), then SELECTION
(group buttons, colour chips).

**Deferred.** FLASH (GAP-04); cue colour (GAP-17, `uiColor` used); `sel …` in the header and the
SELECTION text (GAP-02); effect sparkline and RUN state (GAP-09); programmer effects (GAP-02); effect
stop (GAP-14).

**Tests.** Rows from `LiveState` fixtures: active, idle, releasing, chase, empty slot, crossfade
progress, the fader functions. Keys send exact lines: Space `go 3`; ← → wrap within the visible
slots; `[` from 0 stays at `fader 3 0%`; PgUp/PgDn. A bar drag sends coalesced lines and logs once
on release. The wheel sends lines and logs nothing. TAP and −/+ use the master's name. The
blackout toggle follows the snapshot. F7: GM digits red during blackout, colours by master kind,
step list, fade-time master, `[OUTPUT OFF]` asks first. Contract additions. End to end: Space on
P1 makes the live snapshot show P1 active.

**Done when.**
- [ ] On the club-night show, F1 shows page 1's thirteen slots with live levels, cues and next
      cues, and F7 shows every master kind with live levels and beat dots.
- [ ] Keyboard only: change page, select a playback, GO, back, fader ±, TAP, BPM ±, blackout,
      release all, every line echoed `ui>`.
- [ ] A fader moved on a MIDI surface or the web remote shows in the TUI within 100 ms.
- [ ] Suites green; guide covers F1 B and F7.
- [ ] Manual (the user): busk a song on the TupperDMX rig with the TUI only.

### Phase 2: Program (F2, F6)

**Goal and scope.** Select, set and apply presets: groups, encoders that set values, quick
commands, the programmer's contents (verbatim), preset tiles. Spec §8.2, §8.6.

**Files.** `pages/program.py`, `pages/presets.py`; `widgets/encoders.py` (`EncoderRow`: bar
sets on click or release, a pending preview until the line is done, Enter pre-fills),
`widgets/programmer_text.py` (verbatim panel), `widgets/tiles.py`; additions to `bridge.py`
(profile attributes and physical ranges, preset value summaries, the internal `programmer` query),
`model.py`, `commands.py`, `config.py` (quick list).

**Encoders.** Families as busk groups them: INTENSITY (`intensity`), POSITION (`pan`, `tilt`,
±half of `panRange`/`tiltRange`), COLOR (a `set color ` pre-fill plus the colour presets, and `cto`
when present), BEAM (`zoom` over `zoomRange`, `iris`, `frost`), FOCUS (`focus`), SHUTTER
(`strobeRate` over 0..`maxStrobeHz`, a `set shutter ` pre-fill). A row shows only when some profile
in the show has a channel for that attribute. The attribute names and units are a small table in
the TUI, as command words are.

**Engine lines used.** `sel group N`, `sel + group N`, `sel none`, `set <attr> <value>`, the quick
list (§3, 17), `blind on`, `blind off`, `highlight on|off`, `clear`, `record cue 1`, `preset <pool>
N`; pre-fills `set <attr> `, `set color `, `fade `, `record preset <pool> N "`; internal
`programmer`. **Reads:** `show` groups, profiles (modes' channel attributes, `physical`), presets.

**Deferred.** Selection text and count, encoder values, a single BLIND toggle, the "applies to"
header, PROGRAMMER CONTENTS as a table (GAP-02; the verbatim panel meanwhile); live encoder values
(GAP-01); `[−]`/`[+]`, wheel, colour components (GAP-05); live drag (GAP-06).

**Tests.** Families follow the show's profiles (no pan channel, no POSITION). A release sends one
`set` in the right unit (`set pan -45`, `set intensity 72%`). The pending preview clears on
`CommandDone`. Enter pre-fills. Quick commands from config, defaults in the contract test. The
verbatim panel refreshes after each TUI line and once a second while F2 or F5 is visible, never
while the worker is busy, and its query is not echoed. F6: only non-empty pools; preview rules
(uniform, `mixed`, preset colour swatch); tile click lines. Contract additions: encoder lines
run with a selection that has the attribute (the club-night heads take `intensity`, `pan`, `tilt`,
`zoom`, `shutter`, `strobeRate`, and refuse `iris`, `cto`, `focus`, which they lack).

**Done when.**
- [ ] On the TupperDMX show: select a group, set intensity, pan and tilt with the mouse, apply
      colour and position presets with the pane cursor, and record a cue. Each action is one
      echoed line and one undo step.
- [ ] The programmer panel follows every change, including changes made from the prompt.
- [ ] Suites green; guide covers F2 and F6 and their limits until GAP-02 and GAP-05.
- [ ] Manual (the user): build a look on the rig from F2 and F6.

### Phase 3: Cues and effects (F4, F5)

**Goal and scope.** Browse cue lists and their cues, go to a cue, record, switch sequence and
chase, edit cells through pre-fills. List effects, add them from templates, remove programmer
effects. Spec §8.4, §8.5.

**Files.** `pages/cues.py`, `pages/effects.py`; `widgets/cuetable.py`; additions to
`bridge.py` (entries as stored, timing, triggers, cue effects, templates), `model.py`,
`commands.py`.

**Engine lines used.** `goto N <cue>`, `go N`, `back N`, `record cue L`, `cuelist L chase bpm x 1`,
`cuelist L sequence`; pre-fills `cue L/C time `, `cue L/C follow `, `cue L/C wait `, `cue L/C go`,
`rename cue L/C "`; `effect add "<name>"`, `effect remove <id>`, `go N`/`release N` for a cue
effect's playback; internal `programmer`. **Reads:** `show` cue lists, playbacks by list,
presets (names for references), groups, effect templates; `snapshot` current cue, state, level.

**Deferred.** Programmer effects as rows (GAP-02; the verbatim panel on F5); effect state and
wave (GAP-09); stopping a programmer effect (GAP-14); built-in templates (GAP-15).

**Tests.** The list browser and the meta line for sequence and chase lists. `▶` follows the
snapshot. Entries as stored (literal, preset name, spread, per target). A row with a playback
sends `goto 9 3`; a list with no playback has no row action. The chase toggle sends `x 1`. Each
pre-fill. F5 rows from cue effects with targets and rates formatted. The toggle sends `go` or
`release` by playback state. Template click and `✕`. Contract additions.

**Done when.**
- [ ] On the club-night show, list 9 ("Song") shows its five cues with timing and triggers. Going
      to a cue, GO and BACK follow live. A cue can be recorded and its time edited from the
      pre-fill.
- [ ] F5 lists the show's cue effects. A template adds a programmer effect, visible in the
      verbatim panel and removable.
- [ ] Suites green; guide updated.
- [ ] Manual (the user): run a cue stack on the rig from F4.

### Phase 4: Rig (F3, F8, F9)

**Goal and scope.** The show's structure as tables: fixtures, the patch and its DMX map, the
surfaces and their bindings. These are mostly read-only, with click-to-select and pre-fills for
edits. Spec §8.3, §8.8, §8.9.

**Files.** `pages/fixtures.py`, `pages/patch.py`, `pages/surfaces.py`; `widgets/dmxmap.py`;
additions to `bridge.py` (profiles, modes, patches, element patches, routes, surfaces, bindings),
`model.py`, `commands.py`.

**Engine lines used.** `sel fixture N`, `sel + fixture N`; pre-fills `fixture N patch `,
`fixture N location `, `bind "<surface>" `, `unbind "<surface>" `, `surface "<name>" pickup `.
**Reads:** `show` fixtures, profiles, universes, routes, surfaces, bindings, pages; `snapshot` for
binding target levels.

**As built.** F3: the spec's static columns (marker blank until GAP-02). F8: universes, routes
(protocol, address, destination, enabled), an 8 × 64 map per universe coloured by profile, `╳` on
overlaps, hover text `fixture N · ch k/fp` in the hint row, click to select. F9 "Surfaces":
surfaces (kind, device or port, pickup, binding count) and bindings (input, action, feedback,
target level %).

**Deferred.** Live columns and source colours (GAP-01); selected marker and Shift toggling
(GAP-02); colours by type (GAP-16); TX dots (GAP-07); surface status (GAP-08); MONITOR and learn
(GAP-13).

**Tests.** F3 rows for single and multi-element fixtures, split patches and unpatched fixtures.
F8 footprint cells, overlaps (the TupperDMX show's double-patched heads give two), the used count,
hover text, click line. F9 rows for MIDI, OSC and web surfaces and for each input and action kind
(fader slot, button, master, tap, page, blackout, release all, output). Contract additions.

**Done when.**
- [ ] On the TupperDMX show, F3 lists every fixture, F8 shows its two overlaps, and F9 shows its
      surfaces and bindings.
- [ ] Suites green; guide updated.
- [ ] Manual (the user): check F8 against the rig's real patch.

### Phase 5: The other Busk layouts (F1 A, F1 C)

**Goal and scope.** Layout A (console: OUTPUT palette, PROGRAMMER panel, vertical faders) and
layout C (stage plot from `location`, compact playbacks, masters, QUICK) as settings next to B.
Spec §8.1, layouts A and C. Last because both are degraded until GAP-01, and they reuse the
widgets of Phases 1, 2 and 4.

**Files.** `pages/busk_console.py`, `pages/busk_stage.py`; `widgets/vfader.py` (10 rows × 4
cells, partial top row, drag and wheel), `widgets/fixture_palette.py` (shared by OUTPUT and STAGE).

**Engine lines used.** Those of Phase 1, plus `sel fixture N`, `sel + fixture N`, and the pre-fill
`fixture N location {"x": 0, "y": 0, "z": 0, "rx": 0, "ry": 0, "rz": 0}`. **Reads:** as Phase 1,
plus `show` fixtures and locations.

**As built.** A: OUTPUT with one row per profile and one cell per element, click to select, a
note that live output is not available yet; PROGRAMMER with colour chips, master bars and the
tempo row (no selection text); PLAYBACKS as vertical faders with `GO ◂` and a disabled FLASH.
C: rows by depth (adaptation 6), fixtures placed by x, a "no position" row with the `location`
pre-fill, AUDIENCE at the bottom, compact playbacks, masters with tempo, QUICK.

**Deferred.** OUTPUT colours and pan arrows (GAP-01); glyphs by type (GAP-16); selection
highlight (GAP-02); FLASH (GAP-04).

**Tests.** Faders render each level and partial rows; drag and wheel lines. Palette cells for
multi-element fixtures. Stage rows from locations (same depth, ordering, x scaling, missing
locations). Switching layouts keeps the selected playback and is saved in `state.json`.

**Done when.**
- [ ] A, B and C switch from the header and from `--layout`, and the choice survives a restart.
- [ ] With locations set on the TupperDMX show, C draws the rig in its real order.
- [ ] Suites green; guide complete for every page.
- [ ] Manual (the user): try A and C on the rig.

---

## 6. Why this order

1. **Foundation first:** every page needs the bridge, the frame, the prompt and the shared
   widgets. Because the prompt runs any line, the TUI is usable as a richer `busk run` prompt from
   Phase 0 on.
2. **Perform next (F1 B, F7):** at a gig the operator needs playbacks, masters, tempo and
   blackout before anything else. Both pages are fully supported by busk today, except FLASH.
   They also share most widgets (bars, digits, beat dots, master bars), so building them together
   avoids doing those twice.
3. **Program (F2, F6):** busking means selecting and applying presets between songs. Both pages
   centre on selection plus a pool of one-click lines. They come before cues because a cue is
   recorded from the programmer.
4. **Cues and effects (F4, F5):** both browse the show's cue data and run what it holds through
   playbacks, and both show programmer effects in the verbatim panel from Phase 2.
5. **Rig (F3, F8, F9):** setup pages, mostly read-only and used before the show. Patching and
   binding are done in scripts or at the prompt today, so these add the least on stage.
6. **Layouts A and C last:** their centrepieces (live OUTPUT colours, mover arrows) need GAP-01.
   Building them earlier would produce mostly placeholders, and they reuse widgets from Phases 1,
   2 and 4.

---

## 7. Risks

- **R1, one interpreter.** `LiveShow` runs the engine thread next to the TUI. `docs/library.md`
  measured 10 % overrun ticks in one process under edits, against 0.05 % in `busk run`. Textual
  rendering adds load. Mitigations: `tune_interpreter=True`, change-driven rendering, 20 Hz caps,
  and the Phase 0 perf gate. The real fix is GAP-11.
- **R2, message text.** Hints and completion read the text of `help`. A format change degrades
  them to nothing without breaking commands. The contract and hint tests notice it.
- **R3, command drift.** The spec already disagrees with busk (`dim`, `x1`, `cue L/C go`). All UI
  lines come from `commands.py` and run in the contract test.
- **R4, terminals.** F10 is taken by some terminals (Alt+0 is the spec's alternative). Terminals
  do not report key releases, so there is no momentary flash key. Mouse modes may be missing over
  SSH. Colours are fixed xterm-256 values, and Rich maps them to 16 colours on a 16-colour terminal.
- **R5, change detection.** Show changes are noticed by the identity of `LiveShow.show`. That is
  how the session works (copy-on-write) but not a documented promise. As a guard, the bridge also
  re-reads the document after every successful line. GAP-03's `showVersion` would make it
  explicit.
- **R6, start and stop.** `start()` can take 15 s and `stop()` can hang on a driver. Both run off
  the UI thread, with timeouts.

---

## 8. Not planned

Anything the spec marks "proposed" or "not in the prototype" that busk cannot support yet: learn
mode, the MIDI monitor. Inline cell editing (adaptation 7). A TUI of its own for `busk run`
(GAP-11). A theme editor. Mouse-only features are kept to what the spec lists, and each has a
keyboard path (prompt, pre-fill or pane cursor).

---

## 9. Open questions

- **Q1. Typed reads.** The plan reads `snapshot`, `frame`, `show` and `warnings` directly,
  through the bridge only, and sends every action through `execute()`. If you meant that even
  reads must go through `execute()`, most of §2's **S** rows would depend on parsing `list …`
  text, and would become gaps.
- **Q2. No parsing of reply text.** BLIND, `PROG n`, `sel n` and `undo n` could be scraped today
  from `programmer` and `info`. I left them out (GAP-02, GAP-03) because `docs/library.md` excludes
  message text from the API, and the brief forbids workarounds. Would you accept a temporary
  parser for these four, removed when the gaps close? BLIND matters most on stage.
- **Q3. Packaging.** `uv_build` only puts `busk` in the wheel. I checked that `busk_tui` is
  left out unless `pyproject.toml` also gets
  `[tool.uv.build-backend] module-name = ["busk", "busk_tui"]`. That is one table beyond "the
  extra and the entry point". May I add it?
- **Q4. Dev environment.** `mypy` covers all of `src/` (so `busk_tui` too), and the TUI tests need
  Textual. Either developers run `uv run --extra tui …` (no change, as planned), or the `dev` group
  gets `busk[tui]` (and `pytest-textual-snapshot`, if you want screenshot tests). The second is
  another `pyproject.toml` change. Which do you prefer?
- **Q5. Host.** The TUI runs the show in its own process with `LiveShow`: no watchdog, autosave
  or crash recovery. Is that acceptable for now, with the warning in the banner and the guide,
  until GAP-11?
- **Q6. FLASH.** busk has a typed `FLASH` command reachable through `submit()`. Should FLASH wait
  for a console line (GAP-04), or may the bridge make this one exception to "console lines only",
  logged as `ui> (flash 3 down)`?
- **Q7. Encoder drags.** Until GAP-06, I send one `set` on release (one undo step, no live light
  while dragging). The alternative is live sends at about 10 Hz, at the cost of many undo steps.
  Which do you prefer?
- **Q8. The pane cursor** (§4.5) is an addition to the spec, for keyboard-first operation on
  every page. Keep it?
- **Q9. Interim live-output view.** While GAP-01 is open, F8 could shade each DMX-map cell with its
  live channel value from `LiveShow.frame`: raw bytes, no decoding. It is not in the spec, but it is
  the only live output view busk can feed today. Want it, in Phase 4?
- **Q10. Root files.** Is a one-line install mention in `README.md` and an entry in
  `CHANGELOG.md` covered by "docs"? The plan assumes yes, in Phase 0.
