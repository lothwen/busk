# Engine gaps found while planning the TUI

This lists what the busk TUI (`busk_tui`, planned in
[`docs/dev/tui/implementation-plan.md`](implementation-plan.md)) needs from the engine
and cannot get today. It is input for future engine work. The TUI does not work around any of
these with logic of its own: until a gap is closed, the feature is hidden, disabled, or shown
read-only, as each entry says.

Written 2026-10-21 against busk 0.1.0 (`3176f99`). The facts below were checked by running the
commands on `OfflineShow` with `examples/club-night.busk`. A closed gap keeps its section, with
a **Done** note on what was built; the summary's status column says which are closed.

## How the TUI talks to busk

The TUI runs a `busk.LiveShow` in its own process, or, since GAP-11, is run by `busk run
--frontend`, which hands it the run's `LiveShow`. One module, `busk_tui/bridge.py`, imports
`busk`, and only names in `busk.__all__`:

- **Actions** go through `LiveShow.execute(line) -> Reply(text, ok)`, one console line per
  action, echoed in the TUI's log. `submit()` is not used, so the UI teaches the command line.
  Since GAP-12, `execute` may be called from several threads, and performance lines never
  wait for another thread's line.
- **Reads** use the typed public state: `LiveShow.snapshot` (`EngineSnapshot`),
  `LiveShow.frame` (`DmxFrame`, for the engine time), `LiveShow.show` (the `Show` document),
  `LiveShow.warnings`, since GAP-01 `LiveShow.output` (`OutputSnapshot`), since GAP-02
  `LiveShow.programmer` (`ProgrammerStatus`), since GAP-07 `LiveShow.routes`
  (`RouteStatus`), since GAP-08 `LiveShow.surfaces` (`SurfaceStatus`), since GAP-09
  `LiveShow.effects` (`EffectSnapshot`), since GAP-10 `LiveShow.confirmation(line)`
  (the question to ask before a line) and since GAP-15 `LiveShow.effect_templates`
  (`EffectTemplateInfo`). The `busk.*` loggers feed the TUI's log pane.
- **Text is not parsed.** `docs/library.md` says message text (`Reply.text`, CLI output, log
  records) may change in any release, so the TUI never extracts data from the output of
  `programmer`, `info`, `list …` or `library`. It may show such output verbatim.

So a gap below is one of two kinds:

- **a read**: data the TUI must display that is not in the typed public state. The suggested
  shape is a read-only `LiveShow` property returning a frozen dataclass, published by reference
  like `EngineSnapshot`, and exported in `busk.__all__`;
- **an action**: something an operator does that has no console line. The suggested shape is a
  new console line, so `execute()` covers it and the `busk run` prompt gets it too.

Every new read should also reach `busk run`'s console process, so the TUI gets it under
`busk run --frontend` ([GAP-11](#gap-11-running-the-tui-against-busk-run)) too.

## Priorities

- **blocking**: a page or a core control of the spec cannot be delivered in a useful form.
- **important**: a feature is noticeably degraded, or it is a safety or live-show concern.
- **nice-to-have**: convenience or polish.

## Summary

| Gap | Kind | Priority | Needed by | Status |
|---|---|---|---|---|
| [GAP-01](#gap-01-fixture-output-values) Fixture output values | read | blocking | F1 A/C, F2, F3 | **done** 2026-10-22 |
| [GAP-02](#gap-02-programmer-state) Programmer state | read | blocking | status bar, prompt, F1, F2, F3, F5, F6 | **done** 2026-10-22 |
| [GAP-03](#gap-03-session-state-undo-redo-unsaved-edits) Session state (undo, redo, unsaved edits) | read | important | prompt, quit | open |
| [GAP-04](#gap-04-flash-and-playback-buttons-from-the-console) Flash and playback buttons from the console | action | important | F1 | **done** 2026-10-22 |
| [GAP-05](#gap-05-relative-and-per-component-attribute-values) Relative and per-component attribute values | action | important | F2 | **done** 2026-10-22 |
| [GAP-06](#gap-06-one-undo-step-for-a-gesture) One undo step for a gesture | action | important | F2 | open |
| [GAP-07](#gap-07-output-route-status) Output route status | read | important | status bar, F8 | **done** 2026-10-23 |
| [GAP-08](#gap-08-surface-status) Surface status | read | important | F9 | **done** 2026-10-23 |
| [GAP-09](#gap-09-effect-runtime-state) Effect runtime state | read | important | F1 B, F5 | **done** 2026-10-23 |
| [GAP-10](#gap-10-confirmation-before-dangerous-lines) Confirmation before dangerous lines | read | important | prompt | **done** 2026-10-23 |
| [GAP-11](#gap-11-running-the-tui-against-busk-run) Running the TUI against `busk run` | host | important | everything, on stage | **done** 2026-10-23 |
| [GAP-12](#gap-12-concurrency-contract-of-execute) Concurrency contract of `execute()` | contract | important | responsiveness | **done** 2026-10-23 |
| [GAP-13](#gap-13-control-input-monitor) Control input monitor | read | nice-to-have | F9 | open |
| [GAP-14](#gap-14-stop-and-restart-a-programmer-effect) Stop and restart a programmer effect | action | nice-to-have | F1 B, F5 | **done** 2026-10-23 |
| [GAP-15](#gap-15-effect-template-library) Effect template library | read | nice-to-have | F5 | **done** 2026-10-23 |
| [GAP-16](#gap-16-fixture-category) Fixture category | read | nice-to-have | F1 A/C, F8 | open |
| [GAP-17](#gap-17-playback-colour) Playback colour | read | nice-to-have | F1 | open |
| [GAP-18](#gap-18-quit-signal) Quit signal | read | nice-to-have | prompt | open |
| [GAP-19](#gap-19-status-under-liveshow) `status` under `LiveShow` | action | nice-to-have | prompt | open |
| [GAP-20](#gap-20-completion-and-hints) Completion and hints | read | nice-to-have | prompt | open |
| [GAP-21](#gap-21-engine-health) Engine health | read | nice-to-have | status bar | open |

---

## GAP-01: Fixture output values

**Status:** done 2026-10-22 (see **Done** at the end of this section).

**Needed by:** F1 layout A (OUTPUT grid colours, selection), F1 layout C (pan arrow and tilt on
movers), F3 (live intensity, colour, pan, tilt, zoom and source columns), F2 (the encoders'
value when the attribute is not in the programmer). Spec §4.2, §8.1, §8.3, §9 ("Fixture output,
≥ 10 Hz").

**Today:** `EngineSnapshot` has no per-fixture data. `LiveShow.frame` has the raw DMX bytes of
each universe. Turning bytes back into logical values needs the compiled channel layout, fine
bytes, inversion, curves and colour mixing, which is engine logic, so the TUI does not do it.

**Engine should provide:** a read-only `LiveShow.output -> OutputSnapshot | None`, published by
reference at most once per tick. Frontends poll it at 10–20 Hz. It holds the resolved logical
values the engine has before conversion to DMX, after masters, blackout and limits:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class FixtureOutput:
    number: int                                  # fixture number, as typed (101)
    element: int                                 # 1-based; 1 for single-element fixtures
    intensity: float                             # 0..1, what the fixture emits
    color: tuple[float, float, float] | None     # linear RGB 0..1; None: no colour control
    pan: float | None                            # degrees; None: no pan
    tilt: float | None
    zoom: float | None                           # degrees
    source: Mapping[str, Literal["programmer", "playback", "effect", "none"]]
    # by family ("intensity", "color", "position", "beam"): what drives it now
    playback: int | None                         # number of the playback that wins intensity

@dataclass(frozen=True, slots=True, kw_only=True)
class OutputSnapshot:
    seq: int
    time: float                                  # engine time of the tick
    fixtures: tuple[FixtureOutput, ...]          # fixture number order, then element
```

**Priority:** blocking.

**TUI until then:** the OUTPUT panel (layout A) is a fixture palette with no colours: one cell
per element, click to select, and a dim note "live output not available yet". Layout C draws
fixtures without pan arrows or tilt. F3 hides the live columns and the source legend. The F2
encoders show no value (see GAP-02).

**Done** (2026-10-22). `OfflineShow.output -> OutputSnapshot` and `LiveShow.output ->
OutputSnapshot | None`, with `OutputSnapshot` and `FixtureOutput` in `busk.__all__` (now 30
names), fields as suggested above. `seq` and `time` are those of the tick, as in its
`DmxFrame`. Documented in `docs/library.md` (section 2 and the reference), the classes'
docstrings and `docs/dev/internals.md` ("The output readout"). Where it differs from the
suggestion, or settles what the suggestion left open:

- **Captured on demand.** Reading the output back costs the engine thread a copy of the frame
  and the attribution of every lane: 0.01 ms a tick on the Phase 3 show, 0.6–0.9 ms on the
  reference rig (`docs/dev/benchmarks.md`). So a `LiveShow`'s engine captures only once
  `output` has been read: **the first read returns `None`**, and from the next tick on every
  tick is captured, published by reference. `OfflineShow.output` is made on demand after its
  tick. Turning a capture into `FixtureOutput`s runs on the reader's thread (0.04 ms on the
  Phase 3 show, 10–11 ms for the reference rig's 8 192 elements).
- **Not yet under `busk run`.** The attached show's `output` is `None`, like its `frame`: the
  engine process sends the console process only snapshots. Carrying both is now part of
  [GAP-11](#gap-11-running-the-tui-against-busk-run).
- **`source`** has a key for every family the element has: `intensity`, `position`, `color`,
  `beam`, and also `focus` and `shutter`. Within a family the programmer wins, then an
  effect, then a playback. The highlight counts as the programmer; a parked attribute is
  `"none"` (park holds it, whatever drives it). Masters and blackout change the value, not
  the source. On a lane, what drives it is the topmost source present there; on an intensity
  lane, the strongest of the highest band present (so a band fading in takes over at once,
  even at 0); a relative effect (`add`, `multiply`) drives a lane it moves.
- **`intensity`** is the element's own, times its fixture's master dimmer when it has no
  dimmer of its own (a bar's cells on the first cell's dimmer, as OFL imports them); 1.0 when
  nothing dims it. **`playback`** is the playback whose cue or effect drives that intensity.
- **`color`** is the colour slot's `r, g, b` plus an explicit `w`, through the colour wheel's
  filter when the profile gives the wheel slot a colour (white for an element with only a
  wheel). CTO, explicit amber and UV, and colour macros are not shown. `None` when the
  element has neither a colour nor a colour wheel.
- **`pan`, `tilt`, `zoom`** are before the fixture's orientation (inversion, offsets, swap):
  the show's coordinates, which is what a stage plot needs.
- Unpatched fixtures are listed: they are programmable.
- Tests: `tests/test_output_readout.py` (both facades, every rule above), the attribution in
  `tests/test_resolver.py`, and a property test against a per-slot oracle
  (`reference_attribute`) in `tests/test_resolver_properties.py`.

The TUI can now fill everything this gap blocked, except the F2 encoders' programmer value
(GAP-02): layout A's OUTPUT colours, layout C's pan arrows and tilt, F3's live columns and
source colours, and the encoders' output value. The bridge polls `output` with the snapshot
and treats its first `None` like the snapshot's.

## GAP-02: Programmer state

**Status:** done 2026-10-22 (see **Done** at the end of this section).

**Needed by:** status bar (`PROG n`, BLIND chip, programmer `FADE`), prompt context (`sel n`),
F1 header and SELECTION/PROGRAMMER panels, F2 (selection text, encoder values in magenta,
PROGRAMMER CONTENTS table, a single BLIND toggle), F3 (selected-row marker), Shift-click
toggling (`sel +` versus `sel -`), F5 (programmer effects as table rows), F6 ("applies to …").
Spec §5, §8.1, §8.2, §8.3, §8.6, §9 ("Programmer: selection, per-fixture values, blind, fade").

**Today:** only as text. `programmer` prints the selection, blind, highlight, fade time, each
value (`201 color = preset color 2 'Red'`) and each effect. `info` prints counts. Neither is a
stable format.

**Engine should provide:** `LiveShow.programmer -> ProgrammerStatus`, replaced on every
programmer change, with the same content `programmer` prints:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ProgrammerValue:
    target: str                    # as typed: "101", "301.3"
    attribute: str                 # "intensity", "color", "pan", …
    value: float | Mapping[str, object] | None   # scalar, ColorValue or DiscreteValue; None for a preset
    preset: tuple[str, int, str] | None          # (pool, number, name) when the value is a preset

@dataclass(frozen=True, slots=True, kw_only=True)
class ProgrammerEffect:
    id: str                        # "fx5", what `effect remove` takes
    template: str                  # template name
    targets: str                   # as typed: "group 1" or "101, 102"
    rate: str                      # "bpm 'Speed 1' ×1" or "2 Hz"
    size: float
    phase: tuple[float, float]
    groups: int
    blocks: int
    wings: int
    direction: str

@dataclass(frozen=True, slots=True, kw_only=True)
class ProgrammerStatus:
    version: int                   # +1 per change
    selection: tuple[str, ...]     # in selection order, elements as "301.3"
    blind: bool
    highlight: bool
    fadeTime: float                # seconds
    values: tuple[ProgrammerValue, ...]
    effects: tuple[ProgrammerEffect, ...]
```

**Priority:** blocking (BLIND on or off is a live-show safety signal, and selection feedback is
the core of programming).

**TUI until then:** the status bar has no `PROG`, BLIND or programmer `FADE` slot, and the prompt
context shows no selection count. F2 shows the verbatim output of `programmer` in its
PROGRAMMER CONTENTS panel, refreshed after each command the TUI runs and once a second while F2
or F5 is visible. BLIND is two buttons (`blind on`, `blind off`) instead of a toggle.
Shift-click always adds (`sel + fixture N`); removing is typed (`sel - fixture N`).

**Done** (2026-10-22). `OfflineShow.programmer` and `LiveShow.programmer ->
ProgrammerStatus`, with `ProgrammerStatus` and `ProgrammerValue` in `busk.__all__` (now 32
names). `version`, `blind`, `highlight` and `fadeTime` are as suggested; `fadeTime` is the
programmer's own (`fade`), not the snapshot's fade-time override. Documented in
`docs/library.md` (section 2 and the reference), the classes' docstrings and
`docs/dev/internals.md` ("The programmer status"). Where it differs from the suggestion,
or settles what the suggestion left open:

- **Targets are numbers, not text.** `selection` is `(number, element)` pairs and a
  `ProgrammerValue` has `number` and `element` instead of `target: str`, the element
  counted from 1 (1 for a fixture of one element), as in `FixtureOutput`. So the TUI
  matches the selection to F3 rows, output cells and Shift-click without splitting
  `"301.3"`, and formats the text itself.
- **A preset reference has its value.** `value` is what the preset gives that element
  (the target, profile and global scopes of §5.8), not `None`, so the F2 encoders and the
  PROGRAMMER CONTENTS swatches can show it; `preset` is `(pool, number, name)`.
- **Effects are the instances**, `effects: tuple[EffectInstance, ...]` as the show file
  holds them (the format of a cue's `effects`), instead of a `ProgrammerEffect` with display
  strings. F5 lists cue effects from `show` in that format already, so one formatter serves
  both, looking the template, the speed master and the targets up by id in `show`. There
  is no `ProgrammerEffect`.
- **Made on read, not on every change.** The status is built on the reader's thread from
  one session snapshot (a show and a programmer of the same moment), and only when that
  snapshot is a new one. `version` is 1 at first and grows by one each time a read finds
  the content changed (two changes between reads count once); while nothing changed, the
  same object comes back. A show edit alone can change it (a renumbered fixture, a renamed
  or re-recorded preset), and a change that shows nothing new keeps it (`save`, a new
  universe, the same selection again).
- **Only what is live.** A selected target whose fixture or element is gone, a value whose
  slot, preset value or discrete option is gone, and an effect that no longer validates are
  left out, by the rules the programmer frame uses. They stay in the programmer, dormant,
  and come back with the undo that restores what they need. `programmer` still prints them
  (`(gone)`).
- **Under `busk run` too.** The session runs in the console process, so the attached
  show's `programmer` works, unlike its `frame` and `output` (GAP-11).
- Tests: `tests/test_programmer_status.py` (both facades and the attached show, every rule
  above), the public API golden and `tests/api_consumer.py`.

The TUI can now fill everything this gap blocked: `PROG n`, the BLIND chip and the
programmer `FADE` in the status bar, `sel n` in the prompt, the F1 header and its SELECTION
and PROGRAMMER panels, F2's selection text, programmer values in magenta (presets
included), the PROGRAMMER CONTENTS table and a single BLIND toggle, F3's `▸` marker,
Shift-click toggling between `sel +` and `sel -`, programmer effects as F5 rows, and F6's
"applies to". The verbatim `programmer` panel and its once-a-second query are no longer
needed: the bridge polls `programmer` with the snapshot and redraws when `version` changes.

## GAP-03: Session state (undo, redo, unsaved edits)

**Needed by:** prompt context (`undo 3`), the quit dialog (save only when there are unsaved
edits), and a modified marker next to the show name. Spec §5, §6.3.

**Today:** `info` prints `undo: N steps, redo: M steps` and `file: …, unsaved edits` as text.
The data exists inside the session (`SessionSnapshot.dirty`, `showVersion`,
`Timeline.undo_count`).

**Engine should provide:** `LiveShow.session -> SessionStatus`:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class SessionStatus:
    showVersion: int               # +1 per committed show change (edit, undo, redo, save)
    programmerVersion: int
    dirty: bool                    # unsaved edits
    path: str | None               # where `save` writes
    undoSteps: int
    redoSteps: int
    nextUndo: str | None           # the label `undo` would print ("added effect 'fx5' …")
    nextRedo: str | None
```

`showVersion` also gives frontends a documented change signal. Today the TUI notices show changes
by the identity of `LiveShow.show`, which works because the session replaces the document on
every commit, but that is not a documented promise.

**Priority:** important.

**TUI until then:** no undo count in the prompt context. The quit dialog always offers *Save and
quit / Quit without saving / Cancel*, and says it cannot tell whether there are unsaved edits.

## GAP-04: Flash and playback buttons from the console

**Status:** done 2026-10-22 (see **Done** at the end of this section).

**Needed by:** F1 FLASH buttons (all layouts). Spec §6.2 ("Flash buttons are momentary"),
§8.1.

**Today:** the typed commands exist (`FLASH`, `PLAYBACK_BUTTON`, `TOGGLE_PLAYBACK`, reachable
through `submit()`, surfaces and the web remote), but no console line does. The TUI sends
console lines only.

**Engine should provide:** console lines, with the same replies as `go N` (empty text, errors
like `error: no playback 99`):

```
flash N on|off              → FLASH {playbackId, down}
button N <b> on|off         → PLAYBACK_BUTTON {playbackId, button: b-1, down}
toggle N                    → TOGGLE_PLAYBACK {playbackId}
```

The engine could also release flashes a frontend still holds when that frontend stops, as the
web remote does on disconnect.

**Priority:** important.

**TUI until then:** FLASH buttons are drawn disabled with "flash: not available yet". Even after
this gap is closed, a flash is momentary only with the mouse (button down and up): terminals do
not report key releases, so there is no momentary flash key.

**Done** (2026-10-22). The three console lines, as suggested, so `execute()`, scripts and
the `busk run` prompt all take them:

```
flash N on|off              → FLASH {playbackId, down}
button N <b> on|off         → PLAYBACK_BUTTON {playbackId, button: b-1, down}
toggle N                    → TOGGLE_PLAYBACK {playbackId}
```

They reply as `go N` does: empty text, or `error: no playback 99` and the parser's other
errors (`expected on or off`). No public name was added (`busk.__all__` stays at 32).
Documented in `docs/console.md` (the Perform row and the **Buttons** note), in `help` and
in the parser's module docs. Where it differs from the suggestion, or settles what the
suggestion left open:

- **A `select` button selects.** The engine does nothing with a `select` function; a
  binding turns its press into the programmer's `SELECT_PLAYBACK`. `button N <b> on` does
  the same, so the line means what pressing that button on a controller means. Its reply
  is then `sel playback N`'s (`3 targets selected`), and it is one undo step. Its release
  goes to the engine, which ignores it.
- **A button the playback lacks is refused** (`playback 3 has 2 button(s); no button 3`,
  `buttons are counted from 1`), where the typed command would do nothing. What a button
  does is not checked further: a `goto` button without a goto cue, or a `none` button,
  does nothing, as on a controller.
- **`flash N` works on any playback**, with or without a `flash` button, as the typed
  `FLASH` does. It and a `flash` button (a controller's, the web remote's, `button N <b>`)
  hold the playback's one flash, so the first release lets it go. `release all` drops a
  held flash too; `release N` does not.
- **Nothing releases a frontend's flashes when it stops.** A `LiveShow` stops with its
  frontend (the TUI's `main()` stops it in a `finally`), and its engine with it, so no
  held flash outlives the frontend. A frontend that leaves a running engine behind comes
  with [GAP-11](#gap-11-running-the-tui-against-busk-run), so releasing its held buttons,
  as the web remote does on disconnect, belongs there.
- Tests: `tests/test_console_buttons.py` (each line on `OfflineShow`, on a `LiveShow`, and
  at a real `busk run` prompt), the grammar and its errors in `tests/test_console_parser.py`,
  and completion in `tests/test_console_prompt.py`.

The TUI can now enable its FLASH buttons: `flash N on` when the mouse button goes down on
one, `flash N off` when it comes up (spec §6.2). A playback's other buttons can be drawn
from `show.playbacks[].buttons` and sent as `button N <b> on|off`. The plan's question Q6
(an exception to "console lines only" for FLASH) is no longer needed.

## GAP-05: Relative and per-component attribute values

**Status:** done 2026-10-22 (see **Done** at the end of this section).

**Needed by:** F2 encoders: `[−]`/`[+]` (±5 %, ±15°) and the mouse wheel (±2 %, ±5°); the
colour family as separate red, green, blue and white rows. Spec §8.2.

**Today:** `set <attribute> <value>` takes absolute values only, and a colour only as a whole
(`set color r g b [w x]`). **Trap:** `set intensity +5%` is accepted and stores an absolute 5 %,
because `+5%` parses as a positive number. An operator who types it expecting a nudge gets a
near-blackout.

**Engine should provide:**

```
set <attribute> +<v> | -<v>        relative to the programmer value; for a target with no
                                   programmer value, relative to the current output value
                                   (needs GAP-01 inside the engine) or refused with an error
set color.r|g|b|w|a|uv <value>     one colour component, the others kept
```

The reply is the same as `set` today (`intensity: 4 targets`). If relative values are not
wanted, `+5%` should at least be refused instead of read as `5%`.

**Priority:** important.

**TUI until then:** no `[−]`/`[+]` buttons and no wheel on encoders. Each encoder sets an absolute
value by click or drag on its bar. With the keyboard, Enter on an encoder row pre-fills
`set <attribute> ` in the prompt. The colour family has a `set color` pre-fill and the colour
presets, not per-component rows.

**Done** (2026-10-22). Console lines on a new programmer command, `ADJUST_ATTRIBUTE`
(`AdjustAttributeCmd` in `busk.commands.types`, a new member of `Command`; `busk.__all__`
stays at 32), so `execute()`, scripts, the `busk run` prompt, `submit()` and bindings all
take it:

```
set <attribute> by <change>          → ADJUST_ATTRIBUTE {attribute, delta}
set color.r|g|b|w|a|uv <value>       → ADJUST_ATTRIBUTE {attribute: "color", component, value}
set color.r|g|b|w|a|uv by <change>   → ADJUST_ATTRIBUTE {attribute: "color", component, delta}
```

The reply is `set`'s (`intensity: 4 targets`, `color.r: 2 targets; skipped 1 not in the
programmer`), and each line is one undo step. Documented in `docs/console.md` (the Values
row, the **Relative values** note, Attributes), in `help` and the parser's module docs,
in `docs/dev/internals.md` (Programmer) and in the spec's §15.2. Where it differs from the
suggestion, or settles what the suggestion left open:

- **`by`, not a sign.** `set pan -45` is an absolute pan, and pan and tilt take negative
  values, so a leading `-` cannot also mean "lower by". The change follows the word `by`,
  with or without a sign: `set intensity by 5%`, `by -5%`, `by +5%`. Where `by` may come
  (a scalar attribute, a colour component), a value with a plus sign is refused, and the
  error gives both readings: `'+5%' has a plus sign: 'set intensity by +5%' changes
  intensity by 5%, 'set intensity 5%' sets it`. That closes the trap. A whole colour
  (`set color +1 0 0`) and a discrete attribute have no `by`, and read as before.
- **Only what the programmer holds changes.** A selected target with no value for the
  attribute in the programmer is skipped (`skipped 2 not in the programmer`), and the line
  is refused when no target has one (`no selected target has intensity to change (4 not
  in the programmer)`). It is never relative to the output value: GAP-01's readout comes
  after the masters (with the grand master at 50 %, "output + 5 %" would turn an 80 % look
  into 45 % in the programmer, 22.5 % on stage), it moves with effects, and under
  `busk run` it is in the engine process, not the console process the session runs in.
  `set color.r <value>` follows the same rule, since "the others kept" needs others.
- **A preset reference counts with its value** for that target (the §5.8 lookup that
  GAP-02's `ProgrammerValue.value` shows), and the change makes it a literal. A dormant
  reference (the preset no longer gives a value there) is skipped as `no value`.
- **Ranges.** A change stops at the ends of the attribute's registry range: 0 and 1 for
  intensity and the other normalised attributes, 0 and 1 for a colour component. Pan,
  tilt, zoom and rates have no registry range, so they go as far as `set` lets them; the
  converter clamps to what the fixture can do, as for an absolute value. Results are
  rounded to 9 decimals, so steps add up to what they look like (0.35 + 0.05 is 0.4, not
  0.39999999999999997, in what gets recorded).
- **Components.** A change of `w`, `a` or `uv` on a colour that does not have it starts
  from 0. For `w`, the fixture then stops deriving its white from r, g and b, as with
  `set color … w x`. A colour changes only by component (`set color by 5%` is refused and
  names `color.r`), and a discrete attribute not at all.
- **A typed command, not parser sugar.** The change reads the programmer under the
  session lock, so it never adds to a stale base when a surface or another thread changes
  the programmer between parsing the line and running it. It resolves presets with the
  session's lookups, and `submit()` and bindings (a button that nudges a group) get it
  too. The shape rules (`adjustment_problem` in `busk.model.validate`) are shared by the
  session and the binding validator.
- Tests: `tests/test_relative_values.py` (the command's rules, both facades, `submit`, a
  `LiveShow`, a real `busk run` prompt, bindings), the grammar and its errors in
  `tests/test_console_parser.py`, completion in `tests/test_console_prompt.py`, the replay
  scenario of `tests/test_eventlog.py` (relative lines replay byte-identically), the
  public API golden and `tests/api_consumer.py`.

The TUI can now give its F2 encoders `[−]`/`[+]` (`set <attribute> by -5%` and `by 5%`,
`by -15` and `by 15` for degrees) and the wheel (±2 %, ±5°), and split the colour family
into R, G, B and W rows (`set color.r <value>` on a click or a drag, `set color.r by …` on
`[−]`/`[+]` and the wheel). These act where the programmer holds the attribute for the
selection, which GAP-02's status shows (the magenta value). Where it does not, an encoder
shows GAP-01's output value, and `[−]`/`[+]` there send an absolute `set` built from the
value shown, as the plan allows for a command's argument. Each line is one undo step: a
drag still sends one `set` on release until GAP-06.

## GAP-06: One undo step for a gesture

**Needed by:** dragging an F2 encoder. Spec §6.2: "One undo snapshot is taken at drag start."

**Today:** every programmer command is one step on the undo timeline, and nothing groups steps.
A drag that sends 30 `set` lines needs 30 `undo`s. (Fader and master drags are performance
commands and never on the timeline, so they are fine.)

**Engine should provide:** console lines that group the steps between them:

```
undo group "<label>"     open a group: later programmer and show steps join it
undo group end           close it; the timeline now has one step, labelled "<label>"
```

A group left open is closed by the next command that is not a programmer or show command, or
after a timeout. `undo` inside a group closes it first.

**Priority:** important.

**TUI until then:** an encoder drag moves a local preview of the bar, clearly marked as pending,
and sends one `set` on release. The light does not follow the drag live.

## GAP-07: Output route status

**Status:** done 2026-10-23 (see **Done** at the end of this section).

**Needed by:** status bar TX indicators (`● sACN·U1`, blinking green while sending, red on
error) and the F8 ROUTES `tx` column. Spec §5, §8.8, §9 ("route TX status").

**Today:** the routes are in `show["output"]["routes"]`. Their state (`DriverStatus` ok/detail)
reaches the outside only as log records on `busk.output` (`sACN r1: send failed: …`,
`… sending again`).

**Engine should provide:** `LiveShow.routes -> tuple[RouteStatus, ...]`:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class RouteStatus:
    id: str
    universe: int                  # universe number
    label: str                     # "sACN r1"
    enabled: bool
    ok: bool
    detail: str                    # the failure, or ""
    lastSent: float | None         # engine time of the last packet sent
```

**Priority:** important (a failing output is the first thing an operator must see).

**TUI until then:** the status bar lists the routes without a state dot. Route failures and
recoveries appear in the log as warning and info lines, from the `busk.output` records.

**Done** (2026-10-23). `LiveShow.routes -> tuple[RouteStatus, ...] | None`, with
`RouteStatus` in `busk.__all__` (now 33 names):

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class RouteStatus:
    id: str                        # the route's id in show["output"]["routes"]
    label: str                     # "sACN r1", as the route lines name it
    universe: int                  # the number of the show universe it sends
    state: Literal["ok", "failed", "disabled", "ignored"]
    detail: str                    # why it is failed or ignored; "" otherwise
    packets: int                   # packets sent since the route opened
    errors: int                    # sends that failed since then
```

Documented in `docs/library.md` (section 3 and the reference), the class's docstring and
`docs/dev/internals.md` ("The route status"). Where it differs from the suggestion, or
settles what the suggestion left open:

- **`state` instead of `enabled` and `ok`.** A route is `"ok"` (open, and its last send
  succeeded), `"failed"` (it does not open, or its sends fail; busk keeps opening it
  again), `"disabled"`, or `"ignored"`: a DMX-USB interface busk does not drive
  (`enttecOpen`), which two booleans cannot say. `detail` is the error or the reason, as
  in the route lines.
- **`packets` and `errors` instead of `lastSent`.** They are what the drivers count
  already. A display blinks a route's light when `packets` changed since its last poll:
  a static look still sends a keep-alive about once a second, so a healthy route blinks
  about once a second, and a changing look keeps it lit. A time of the last packet would
  need every driver to note it, and a clock the reader shares. The counts start again
  when a live edit changes the route (a new driver), and go on across the reopening of a
  failing one.
- **Every route of the show**, in show order, sent or not, so the TUI matches them to
  `show.output.routes` by `id`. `universe` is the show universe's number, as `DmxFrame`
  keys it, not the sACN universe or the Art-Net port address (those are in the show).
- **`None` while nothing runs the output**: before `start()` and with `output=False`. After
  `stop()` it keeps the routes as they ended. `OfflineShow` has no `routes`: it has no
  output.
- **Made on read.** The output thread publishes its routes by reference whenever they
  change (opened, reconciled, a retry that opens one or fails with another error), and a
  read adds each open driver's status, so nothing is built while nobody reads. While
  nothing changed, the same object comes back.
- **Output off.** While `EngineSnapshot.outputEnabled` is false no route sends: the
  states stay as they were and `packets` stops. The TUI's OUTPUT OFF chip comes from the
  snapshot.
- **Under `busk run` too.** Its root runs the output, and on each pass of its main loop
  (10 Hz) sends the console process a `ROUTES` message when the statuses changed, and
  the last ones to a console that starts; `--threads` reads its own output. So the
  attached show's `routes` works, unlike its `frame` and `output`
  ([GAP-11](#gap-11-running-the-tui-against-busk-run)).
- Inside: a `RouteNotice` about a route that is not sent now names the route and why
  (`route`, `detail`), and `build_routes` hands its notices to the `OutputScheduler`.
  The route lines and their text are unchanged.
- Tests: `tests/test_route_status.py` (the scheduler's table, a `LiveShow`, `busk run
  --threads`, the root's `ROUTES` and the console process keeping them), the notices in
  `tests/test_output_scheduler.py` and `tests/test_dmxusb.py`, the public API golden and
  `tests/api_consumer.py`.

The TUI can now draw the status bar's dots: green for `"ok"`, blinking when `packets`
changed since the last poll, red for `"failed"`, dim for `"disabled"` and `"ignored"`. F8's
ROUTES `tx` column shows the same state with its `detail`, and may show a packet rate
from `packets` over its own poll interval. The bridge polls `routes` with the snapshot.
The `busk.output` records still feed the log.

## GAP-08: Surface status

**Status:** done 2026-10-23 (see **Done** at the end of this section).

**Needed by:** F9 SURFACES status dot (green connected, red missing). Spec §8.9.

**Today:** surfaces and their bindings are in the show document. Whether a MIDI device is
plugged in, an OSC port is open, or the web remote is serving (and on which URL) reaches the
outside only as `busk.surfaces` log records.

**Engine should provide:** `LiveShow.surfaces -> tuple[SurfaceStatus, ...]`:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class SurfaceStatus:
    id: str
    name: str
    kind: Literal["midi", "osc", "web"]
    open: bool                     # connected / listening
    detail: str                    # "unplugged; waiting for it", "install busk[midi]", …
    urls: tuple[str, ...]          # web remote only
```

**Priority:** important (a controller unplugged mid-show).

**TUI until then:** F9 lists surfaces without a dot. The surface lines appear in the log.

**Done** (2026-10-23). `LiveShow.surfaces -> tuple[SurfaceStatus, ...] | None`, with
`SurfaceStatus` in `busk.__all__` (now 34 names):

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class SurfaceStatus:
    id: str                        # the surface's id in show["surfaces"]
    name: str                      # its name: "nanoKONTROL2", "Phone"
    kind: Literal["midi", "osc", "hid", "web", "internal"]
    state: Literal["ok", "failed", "ignored"]
    detail: str                    # why it is failed or ignored; "" otherwise
    urls: tuple[str, ...]          # an open web remote's addresses
```

Documented in `docs/library.md` (section 3 and the reference), the class's docstring and
`docs/dev/internals.md` ("The surface status"). Where it differs from the suggestion, or
settles what the suggestion left open:

- **`state` instead of `open`.** A surface is `"ok"` (a MIDI surface's input port is
  connected, an OSC surface listens, a web remote serves), `"failed"`, or `"ignored"`: a
  `hid` or `internal` surface, which busk does not implement (`busk run` lists them under
  `Ignored in Phase 7:`), and which a boolean cannot tell from a failure. These are
  `RouteStatus`'s words, so one legend serves F8 and F9.
- **`detail` is the reason the surface's line gave**, after its label: `'nanoKONTROL2' not
  found; available: Midi Through:…`, `unplugged; waiting for it`, `unavailable: install
  busk[midi]`, `cannot listen on udp 8000: Address already in use`; for an ignored one,
  `hid surfaces are not implemented`. `""` while it is open. A missing device's list of
  available ports is the one read when the surface last tried to open.
- **What is tried again** has not changed. A failed MIDI surface opens as soon as its
  device appears (the hot-plug read, every 2 s). A failed OSC or web surface is tried again
  only when an edit changes it.
- **`urls`** are an open web remote's addresses, key included (`http://10.0.0.5:8080/?k=…`),
  as its lines printed them when it opened: one per IPv4 interface, or its `host`. Empty
  for the other kinds and while it is not open. Like the lines, they are not read again
  when the interfaces change later.
- **Every surface of the show**, in show order, so the TUI matches them to
  `show.surfaces` by `id`. `name` and `kind` are the current definition's: a renamed web
  remote keeps its server and shows its new name.
- **The MIDI feedback port is not in the status.** The feedback worker owns it, and a
  controller's input and output ports come and go together. Its lines (`MIDI s-nano
  feedback: …`) still say whether it opened.
- **`None` while no surface is open**: before `start()` and with `surfaces=False`. After
  `stop()`, the surfaces as they ended. `OfflineShow` has no `surfaces`: it opens none.
- **Published on change.** The surface manager builds the tuple when a surface opens,
  closes or fails (a reconcile, a hot-plug read that changed a port) and publishes it by
  reference only when it differs from the last one. A read costs nothing and returns the
  same object while nothing changed. A live edit shows after the monitor's next pass
  (0.1 s).
- **Under `busk run` too, with no new message.** Its surfaces run with the session in the
  console process, so the attached show's `surfaces` works, with processes and with
  `--threads`.
- Inside: `open_midi` returns why the port did not open (`None` when it opened, as
  `OscSurface.open` and `WebSurface.open` do), and the unplugged text is `UNPLUGGED` in
  `busk.io.surfaces`. The surface lines and their text are unchanged.
- Tests: `tests/test_surface_status.py` (the manager with fake MIDI ports and real OSC and
  web sockets, a `LiveShow`, `busk run`'s attached show), the missing `midi` extra in
  `tests/test_no_midi.py`, the public API golden and `tests/api_consumer.py`.

The TUI can now draw F9's SURFACES dots: green for `"ok"`, red for `"failed"` with its
`detail`, dim for `"ignored"`, and show an open web remote's address on its row. The
bridge polls `surfaces` with the snapshot. The `busk.surfaces` records still feed the log.

## GAP-09: Effect runtime state

**Status:** done 2026-10-23 (see **Done** at the end of this section).

**Needed by:** F5 `state` column (RUN/off) and `wave` sparkline, and the F1 layout B EFFECTS
panel. Spec §4.3 (sparkline), §8.5, §9 ("Effects: … running, owning playback").

**Today:** effect instances are stored in cues (`show["cueLists"][…]["cues"][…]["effects"]`) and
in the programmer (GAP-02). Whether one is running, its phase and its waveform are computed only
inside the engine. With tracking, a cue's effect can keep running after later cues, so a
frontend cannot infer "running" from the playback state.

**Engine should provide:** `LiveShow.effects -> tuple[EffectStatus, ...]`, the instances
contributing at the snapshot's tick:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class EffectStatus:
    owner: Literal["programmer", "playback"]
    playback: int | None           # playback number for a cue effect
    cue: str | None                # the cue that started it
    id: str                        # instance id (unique within its cue or the programmer)
    template: str
    size: float                    # after the size master and fade-in
    rateHz: float                  # cycles per second now
    phase: float                   # 0..1, the cycle position of the first member
    wave: tuple[float, ...]        # 20 samples of the main layer across one cycle, 0..1
```

**Priority:** important.

**TUI until then:** no `wave` or `state` column. For a cue effect, F5 shows the state of the
playback that holds it, labelled as playback state ("P9 active"), not as the effect's.

**Done** (2026-10-23). `OfflineShow.effects -> EffectSnapshot` and `LiveShow.effects ->
EffectSnapshot | None`, with `EffectSnapshot` and `EffectStatus` in `busk.__all__` (now 36
names):

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class EffectStatus:
    playback: int | None           # number of the playback whose cue runs it; None: the programmer's
    cue: str | None                # number of the cue that defines it; None: the programmer's
    id: str                        # the instance's id
    presence: float                # 0..1: rising while it enters, 1 while it runs, falling as it leaves
    size: float                    # its size × its size master × its playback's size fader
    hz: float                      # cycles per second now
    phase: float                   # 0..1: where it is in its cycle, before the members' offsets
    wave: tuple[float, ...]        # the next cycle of its first layer with a waveform: 20 samples, 0..1
    colors: tuple[tuple[float, float, float], ...]  # the same for its first colour layer, linear RGB

@dataclass(frozen=True, slots=True, kw_only=True)
class EffectSnapshot:
    seq: int                       # the tick's, as in its DmxFrame
    time: float
    effects: tuple[EffectStatus, ...]  # the playbacks' in show order, then the programmer's
```

Documented in `docs/library.md` (sections 2 and 3, and the reference), the classes'
docstrings and `docs/dev/internals.md` ("The effect status"). Where it differs from the
suggestion, or settles what the suggestion left open:

- **A snapshot of one tick**, with `seq` and `time` as in its `DmxFrame`, like
  `OutputSnapshot`, instead of a bare tuple: the phases and the samples are those of that
  tick. `effects` lists every instance that ran: the playbacks' in show order (one
  playback's leaving instances first, then its cue's in cue order), then the programmer's.
  A flash's instances are its playback's: a playback's main and its flash never run its
  effects at the same time, so `(playback, id)` is unique.
- **Captured on demand**, as GAP-01's output: a `LiveShow`'s engine captures its effects
  only once `effects` has been read (**the first read returns `None`**), then every tick,
  published by reference. Reading `effects` does not turn on the output capture, nor the
  other way round. `OfflineShow.effects` is made on demand after its tick. The capture
  costs the engine thread 0.03 ms a tick for the reference rig's 20 effects, and building
  their statuses, on the reader's thread, 0.16 ms (`docs/dev/benchmarks.md`).
- **`cue` is the cue that defines the instance**, not the one it started at: the cue
  whose `effects` hold it. In a tracking list an instance carries on, by id, into the
  later cues with that cue's settings, and a cue that gives it other settings (the same
  id) becomes its `cue`. So `(playback, cue, id)` finds, in `show["cueLists"]`, the entry
  an F5 row shows, with its template, targets, rate as typed, size, phase spread, wings
  and direction; a programmer instance is found by `id` in `programmer.effects`.
  Renumbering a cue renames its running effects at once and changes nothing on stage
  (a releasing playback's keep the number they had until they end). Inside, it is
  `CompiledEffect.cue`, which `same()` leaves out, and a retarget to a `same()` form takes
  the new object.
- **No `template`.** As GAP-02 settled for the programmer's effects, the settings are
  looked up in the show by the keys above, so one formatter serves the document and the
  status, which carries only what runs.
- **`presence` added; `size` without it.** `presence` is the instance's own fade (in over
  its `sizeFadeIn`, else the cue's in time or the programmer's fade time; out with the
  cue's out time or the programmer's fade time) and, while a cue changes its settings,
  the sum of the old and the new form's, at most 1. `size` is the amplitude its relative
  layers apply now, after the size master and the `size` fader. A playback's fader and
  its release are in neither: they scale the effect as they scale the playback's values,
  and the snapshot has them (`faderLevel`, `state`).
- **`hz`**, cycles per second now: a BPM effect's at the tempo now, after its master's
  step, a `rate` fader and the strobe cap. A beat nudge in progress is left out.
- **`phase`** is the effect's own position in its cycle, with its direction applied
  (`reverse` runs it down, `bounce` folds it), before the members' phase offsets.
- **`wave` is the next cycle, from now**, not one cycle from 0: sample `k` is what the
  first member of the first layer with a waveform (a Circle's pan, not its tilt) does
  `k / (20 · hz)` seconds after the tick, while the rate holds. That is the spec's
  sparkline "scrolling with phase" as it comes, and a random wave shows the cycle it runs
  into. The values are the waveform's 0..1, before `low`/`high` and `size`.
- **`colors` added**: the same for the first colour layer, with the first member's
  palette as the engine resolved it (presets by scope), for the spec's "Rainbow uses
  per-cell hue". `()` without a colour layer; `wave` is `()` without a waveform.
- **Not under `busk run` yet.** The attached show's `effects` is `None`, like its `frame`
  and `output`: the engine runs in another process. Carrying it is now part of
  [GAP-11](#gap-11-running-the-tui-against-busk-run).
- Tests: `tests/test_effect_status.py` (both facades and the attached show, every rule
  above, the samples checked against what the output does over the next cycle), the
  defining cue in `tests/test_effect_compile.py`, the public API golden and
  `tests/api_consumer.py`.

The TUI can now fill F5's `state` column: `RUN` for a row whose `(playback, cue, id)`
(for a cue effect, the playback that runs its list) or programmer `id` is in `effects`,
dimmed while `presence` is below 1, `off` otherwise; and its `wave` sparkline: heights
from `wave`, per-cell hue from `colors` (full cells when `wave` is empty), drawn as it
comes on each poll. The F1 layout B EFFECTS panel shows the same, and the `rate` column
may add the live `hz`. The bridge polls `effects` with `output` and treats its first
`None` like the snapshot's. The "P9 active" label is no longer needed. The RUN/off click
stays `go N` / `release N` for a cue effect; a programmer effect's waits for GAP-14.

## GAP-10: Confirmation before dangerous lines

**Status:** done 2026-10-23 (see **Done** at the end of this section).

**Needed by:** the prompt. `busk run` asks before `output off`; the TUI should too.

**Today:** the question exists (`Console.confirmation(line)`) but is internal. The TUI cannot
know which lines need confirmation without parsing them.

**Engine should provide:** `LiveShow.confirmation(line) -> str | None`, the yes/no question to
ask before running `line`, or `None`.

**Priority:** important (safety).

**TUI until then:** the TUI's own `[OUTPUT OFF]` button asks first. A typed `output off` runs at
once, as in a script. The user guide says so.

**Done** (2026-10-23). `OfflineShow.confirmation(line)` and `LiveShow.confirmation(line)
-> str | None`, as suggested: the question `busk run`'s prompt asks before running `line`,
or `None` to run it at once. No public name was added (`busk.__all__` stays at 36).
Documented in `docs/library.md` (section 3 and the reference), `docs/safety.md`, the
method's docstring and `docs/dev/internals.md` ("Panic, stalls and output off"). Where it
differs from the suggestion, or settles what the suggestion left open:

- **The question without `[y/N]`.** `output off` gives `"Turn all DMX output off?"`, and
  the `busk run` prompt adds ` [y/N] `, so what it prints has not changed. A frontend shows
  the question with its own buttons, and could not drop the suffix without parsing text.
  The question is text to show as it is, and may change in any release, like
  `Reply.text`. The contract is whether it is `None`.
- **Only `output off` asks**, as at the `busk run` prompt. It asks whatever the output is
  now: the question is about the line, so it asks even when the output is already off.
  `None` for every other line (`output on`, `release all`, `blackout on`, `clear`, `quit`
  …), and also for:
  - a binding of `output off` (`bind … output off`): the line binds, and the control never
    asks, as bindings never do;
  - `source FILE`: a script's lines never ask, at the prompt or anywhere;
  - a line that does not parse: `execute` reports its error.
- **`execute` never asks.** It runs `output off` at once, as before, so a frontend asks
  first and then sends the line. Nothing else changed for scripts, bindings and
  `submit()`.
- **Asking changes nothing.** The console used to parse the line with the session's id
  factory, so asking about `universe add …` or `fixture add …` used up an id: with
  `CounterIds`, the line then got the next one, and a script asked about line by line
  built a different show. It now parses with a throwaway factory, as completion
  (`expected`) does. Nothing is committed and no undo step is added.
- **Any thread, and cheap.** It reads only the published show, programmer and page, so a
  frontend may ask from its own thread while another runs a line. A call takes 5–15 µs on
  the club-night show.
- **On both facades and under `busk run`.** The session and the prompt run in the console
  process, so the attached show's `confirmation` works there, with processes and with
  `--threads`, and it is what that prompt asks.
- Tests: `tests/test_confirmation.py` (both facades, every rule above, `busk run`'s prompt
  asking what its attached show answers), the question in `tests/test_console.py` and
  `tests/test_console_parser.py`, the public API golden and `tests/api_consumer.py`.

The TUI can now ask before a typed line. On Enter the bridge calls `confirmation(line)`
(cheap enough for the UI thread). If it returns a question, the TUI shows it in a yes/no
dialog and sends the line only on yes. No, Esc and closing the dialog cancel, and the log
shows `cancelled`, as `busk run` prints it. The `[OUTPUT OFF]` button sends its line the
same way, so the TUI keeps no question of its own, and the guide's note that a typed
`output off` runs at once can go. A line from history or a pre-fill is asked about like a
typed one.

## GAP-11: Running the TUI against `busk run`

**Status:** done 2026-10-23 (see **Done** at the end of this section).

**Needed by:** every page, whenever the TUI is used on stage.

**Today:** the only public way to run a show live is `LiveShow`, which has no watchdog, no
process isolation, no autosave, no crash recovery and no event log (`docs/library.md`). The
engine thread shares the interpreter with the TUI's rendering. `busk run` keeps the engine in
its own process, but its console process has a line prompt, and its seam for a frontend
(`LiveShow._attached`) is private.

**Engine should provide** one of:

- `busk run --frontend MODULE:FUNCTION`: the console process calls the frontend with the
  attached `LiveShow` instead of starting its line prompt. This is the smallest change: the
  seam exists.
- a public client, `busk.attach(state_dir) -> LiveShow`-like object, for a frontend in its own
  process, talking to a running `busk run`.

Either way the TUI keeps the same bridge API (`execute`, `snapshot`, `frame`, `show`, and the
reads above). Today the attached show's `frame`, `output` ([GAP-01](#gap-01-fixture-output-values))
and `effects` ([GAP-09](#gap-09-effect-runtime-state)) are `None`: the engine process sends
the console process only snapshots, so either option must carry the frames, the output
captures and the effect captures too.

**Priority:** important.

**TUI until then:** it runs a `LiveShow` with `tune_interpreter=True`, as `busk run` tunes its
engine process. The startup banner and the user guide say that for a show on stage, `busk run`
is the safer host. The TUI shows an `ENGINE` warning chip when frames stop arriving
(see GAP-21).

**Done** (2026-10-23). The first option, `busk run SHOW --frontend MODULE:FUNCTION`, chosen
over a public `busk.attach()` client. No public name was added (`busk.__all__` stays at
36): the frontend gets a `busk.LiveShow`. Documented in `docs/running.md` (Options and
"Frontends"), `docs/library.md` (section 3 and Logging), the CLI's and the process
modules' docs, `docs/dev/internals.md` ("The processes") and `docs/dev/benchmarks.md`.
Where it differs from the suggestion, or settles what the suggestion left open:

- **The function gets the show and nothing else.** `FUNCTION(show)` runs on the console
  process's main thread, after `--script`, with the attached `LiveShow` already started;
  it calls neither `start()` nor `stop()`. The run ends when it returns, as after `quit`,
  and its return value is ignored. Its own options are not busk's: `busk run`'s
  environment and working directory reach it, so the TUI passes its own in an environment
  variable or its config file. The name is imported with `pkgutil.resolve_name`, so
  `module:object.attribute` works too.
- **A frontend that raises is a console that crashed.** The traceback is printed, the
  console exits 70, and the root starts a new one (`--restarted`), which recovers from
  autosave, adopts the running engine and calls the frontend again. The engine and the
  output never stop (decision 7). After three restarts in 60 s the root gives the console
  up and the show runs on without one, as for any console. A frontend that cannot be
  imported, or is not callable, ends the run with exit code 1 before the show loads, so a
  typo is not a restart loop.
- **Signals.** Ctrl+C (when the frontend does not read raw keys) raises
  `KeyboardInterrupt` in the frontend's thread, and with processes `SIGTERM` and `SIGHUP`
  (which the root passes on) raise the console's `Terminated`, a `BaseException`. Let
  through, they end the run as `quit` does. A Textual app reads Ctrl+C as a key.
- **Refused combinations.** `--console` (frame lines over the frontend's screen),
  `--no-console` (no commands) and `--duration`. With `--threads` nothing could stop the
  frontend's thread when the duration is over; with processes the root's `SIGTERM` could,
  but one rule covers both. `busk: error: --frontend cannot be combined with …`, exit 2.
- **The terminal is the frontend's.** While it runs, busk prints nothing on it. The
  console process's lines (surfaces, session failures, `engine back: …`, `engine: running
  on …`, and the route lines with `--threads`) become records of a new logger,
  `busk.run`: INFO for news, WARNING for failures. The root's lines (route lines and
  notices, `engine: restarted …`, the watchdog giving up, `no output: …`) and the engine
  process's stderr (a pipe to the root under `--frontend`) go to the console as `NEWS`
  and become the same records. With no console to take them (a console restart, the
  shutdown), the root prints them. Before the frontend starts (compile warnings, `Ignored
  in Phase 7:`, recovery, the surfaces' first lines, the script's output) and after it
  returns (the last route changes, the autosave, the statistics), busk prints as before.
  No status lines are printed. It is one logger, not `busk.output` and `busk.surfaces`,
  because the records are what `busk run` would print, with the same text. A route's
  `sending again` is a WARNING there, since at the prompt it goes to stderr.
- **Frames, output and effects under `busk run`** (the `None`s GAP-01 and GAP-09 left
  here). `LiveShow` now reads them through its engine link for every kind of show: its
  own engine, `--threads`' engine in the same process, and the console process's
  `RemoteBus`. The first read of each sends the engine process a `WATCH`, which every new
  engine gets again after a reconnect, so that read returns `None`, as `output` and
  `effects` already did. The engine process then sends:
  - every frame (`LAYOUT` and `FRAME`, as to the root);
  - the output capture, at most every 40 ms (`WATCH_S`), without its compiled show but
    with that show's stamp. The console reads it with its own copy of the show, because
    the engine's view has no readout lookups, so building `FixtureOutput`s costs the
    console process, not the engine. A capture of a show the console has replaced since
    is skipped;
  - the effects at the same pace, read in the engine process (0.16 ms for 20 effects),
    because a capture holds compiled effects, much larger than the snapshot.

  The engine captures the output and effects only while the console watches them, and
  only when one is due. A new console link watches nothing. After an engine restart,
  `seq` counts from 1 again.
- **Cost** (`docs/dev/benchmarks.md`). On the reference rig, a frontend polling all three
  20 times a second costs the engine process 0.015 core, with overruns at the idle
  level. Without the pacing it cost 0.13 core and doubled them. The console process
  spends 0.25 core, almost all of it building `FixtureOutput`s, as `LiveShow` does.
- **Held flashes** (GAP-04's note). A frontend lives as long as its console. When it
  returns, the run ends and the engine stops, so nothing it holds outlives it. When it
  crashes, the engine runs on, and a flash it held stays held, as one held from the
  prompt does when the console crashes (and a web remote's: its release on disconnect
  runs in the console that crashed). The restarted frontend sees it
  (`PlaybackStatus.flash`) and `flash N off` releases it. Releasing a crashed console's
  flashes would change every `busk run`, so it is left open.
- **Not built:** the second option. A frontend cannot attach to a running `busk run` and
  detach from it again; its run ends with it.
- Tests: `tests/test_frontend.py` (the publisher's watch and pacing, the `RemoteBus`
  against an engine host, the attached show with `--threads` and from the engine process,
  real `busk run --frontend` trees with `tests/process_site/frontend_probe.py`: the
  frontend's reads, lines and records, a crash and the restart, `--threads`, a frontend
  that cannot be loaded, the refused options; the lines diverted, `NEWS`, the engine's
  stderr), the attached show in `tests/test_effect_status.py` and
  `tests/test_run_options.py`.

The TUI can now run on stage under `busk run`. `busk-tui SHOW` can start `busk run SHOW
--frontend busk_tui.app:frontend` with the TUI's own options in the environment, and the
bridge takes the `LiveShow` it is given instead of building, starting and stopping one.
The rest of the bridge is unchanged: `execute`, `snapshot`, `frame`, `output`, `effects`,
`programmer`, `routes`, `surfaces`, `confirmation` and its `busk` log handler, which now
also gets `busk.run`. `status` answers with `busk run`'s status line there; GAP-19 is
about a plain `LiveShow`. This answers the plan's question Q5 and risk R1 (the engine has
a process of its own), and the startup banner's warning can go. The quit dialog stays
the TUI's own: after it, the frontend returns. The `ENGINE` chip can stay on `frame.seq`,
since frames still come every tick.

## GAP-12: Concurrency contract of `execute()`

**Status:** done 2026-10-23 (see **Done** at the end of this section).

**Needed by:** responsiveness during a show.

**Today:** `execute()` works off the main thread (the SIGINT hold is skipped there). Whether
two threads may call it at once is not documented. Inside the session, performance commands
never wait for an edit, but a frontend that sends every line through one worker still makes a
`go` wait behind a slow `save`, `source` or a large edit's compile.

**Engine should provide:** a documented contract: `LiveShow.execute()` is safe from several
threads, and performance lines (`go`, `back`, `goto`, `fader`, `gm`, `master`, `blackout`,
`tap`, `bpm`, `page`, `release`) never wait for an edit, a save or a script. Alternatively,
`LiveShow.is_performance(line) -> bool`, so a frontend can route lines to a second worker
without parsing them.

**Priority:** important.

**TUI until then:** one worker thread runs every line in order. The UI never waits: it shows
`⧗ <line> 1.4s` while a line takes longer than 0.3 s and keeps accepting input. Repeated control
moves (fader and master drags) replace their own queued, unsent line instead of piling up.

**Done** (2026-10-23). The contract, as suggested: `LiveShow.execute()` is safe from any
number of threads, and a performance line never waits for another thread's line. The
alternative, `LiveShow.is_performance(line)`, was not added (see below). No public name was
added (`busk.__all__` stays at 36). Documented in `docs/library.md` (section 3, "Several
threads", and section 2: an `OfflineShow` is for one thread at a time), the docstrings of
`busk.runner` and `busk.console.console`, `docs/dev/internals.md` ("Lines from several
threads") and `docs/dev/benchmarks.md` ("Several threads", from the new
`bench/thread_latency.py`). Where it differs from the suggestion, or settles what the
suggestion left open:

- **Lines run as if one after the other.** A line that is not a performance line runs
  whole under the console's line lock, from its parse to its reply: no other thread's line
  lands in the middle of it, and it sees what the line before it did. Lines from one thread
  run in the order it sends them. Lines from two threads have no order between them: a
  `go` sent while another thread records a cue acts on the cue list as it was.
- **The performance lines** are the lines whose command is of the performance class, the
  ones the engine carries out: `go N`, `back N`, `goto N C`, `release N`, `release all`,
  `fader N L`, `flash N on|off`, `toggle N`, `button N B on|off` (except the press of a
  `select` button, which is a programmer command), `gm L`, `master "name" L`, `blackout
  on|off`, `tap`, `bpm`, `page N|next|prev` and `output on|off`: the suggestion's list,
  with GAP-04's buttons and `output`. `playback N goto C`, `page add` and `master add` are
  edits. A blank line and a line that does not parse do not wait either.
- **Every other line waits**, queries included (`list …`, `programmer`, `info`, `help`), so
  a query answers after the edit another thread is making. Typed reads (`snapshot`,
  `programmer`, `output` …) never wait.
- **A script runs whole.** `source FILE` and `run_script` hold the line lock for all their
  lines, so another thread's edit waits for the end of the script. Another thread's
  performance lines still go at once.
- **Each line is parsed twice.** First with an id factory of its own, as `confirmation`
  parses, to tell a performance line from the others; any other line is parsed again under
  the lock, with the session's ids, so it uses up the ids of one parse (a scripted build
  with `CounterIds` gets the ids it always got). Without that second parse, a line parsed
  while another thread's edit was being made could fail: two `effect add "Saw"` both
  embedded the template, and the second was refused. A parse takes 3–6 µs on the
  club-night show and on the 400-fixture rig alike.
- **What a performance line still shares.** It takes no lock: the session has always
  queued performance commands without its own, so it never waits for an edit's validation
  and compile, a save or a script. But it shares the interpreter with them. On the
  400-fixture rig, while another thread edited, a `fader` line was done 0.1 ms after it
  was due at the median and 2.1–2.5 ms at the 99th percentile with
  `tune_interpreter=True`; 1.2–1.4 and 13–16 ms at Python's default. Under `busk run
  --frontend` it was 4.1–4.4 and 32–45 ms: the console process keeps Python's switch
  interval, and the `RemoteBus` writer lock, which keeps an install ahead of the commands
  validated against its show, is held while the install is encoded and sent (15–20 ms for
  a patch on that rig). Before, a single worker kept a control's line behind the whole
  edit (up to 190 ms there), save or script. On a small rig an edit takes a few
  milliseconds, so none of this shows.
- **Fixed on the way**, because several threads reach them:
  - Ctrl+C belongs to the main thread, the only one SIGINT reaches. Another thread whose
    line ended while the main thread's ran used to raise the main thread's
    `KeyboardInterrupt`, and its script stopped as `interrupted`.
  - `list masters` and `list cues` read the show again after the parse, and raised when a
    command that does not go through the console (`submit()` from another thread, or a
    binding's command) deleted what they listed in between. They leave it out now.
  - The parse reads the show and the programmer from one `SessionSnapshot`.
- **An `OfflineShow` is for one thread at a time**, as before: each call ticks its engine.
- **Not built** (calls the user may veto):
  - `LiveShow.is_performance(line)`. The TUI knows which of its own controls send
    performance lines, and sends typed lines in order, as the `busk run` prompt runs them,
    so it parses nothing. A typed `go` then waits behind a typed `save`. If typed
    performance lines should pass too, the first parse is already there to answer it.
  - A lower switch interval for `busk run`'s console process (`--threads` already has
    one), and encoding installs outside the `RemoteBus` writer lock. The first takes the
    `busk run` numbers above to 0.24–0.29 ms median and 14–15 ms p99; the second would cut
    that p99 to the send. Both change every `busk run`, so they are left for a decision.
- Tests: `tests/test_concurrent_lines.py` (17, each fix mutation-checked): performance lines
  applied by the engine while another thread's edit compiles, its save writes and its
  script runs; a programmer line, a query, an edit, `undo` and `save` waiting for another
  thread's edit and then seeing it; `source` and `run_script` whole; two `effect add` of
  one new template; the ids of one parse; blank lines and parse errors not waiting; Ctrl+C
  on the main thread only; the two queries against another thread's `submit`; eight
  threads at once; `busk run`'s attached show on a `RemoteBus` sending `go` to an engine
  host while an edit compiles.

The TUI can now keep a GO from waiting behind an edit. The bridge gets a second worker: the
lines of the TUI's own controls that are performance lines (Space and `[GO]`, `[◂]`, fader
and master drags and wheels, TAP, BPM ±, `[BLACKOUT]`, PgUp/PgDn, `[OUTPUT OFF]` after its
question, `release all`, FLASH) go to a controls worker, in order among themselves and with
the coalescing of control moves. Everything else (typed lines, pre-fills, edit and
programmer buttons, the internal queries) stays on the ordered worker. The busy indicator
`⧗` follows the ordered worker only. The bridge needs no parse of its own: which builder
of `commands.py` makes a performance line is part of the builder, and a line sent to the
wrong worker is still correct, only slower or unordered. The TUI's own `LiveShow` keeps
`tune_interpreter=True`. The plan's Phase 0 deferral of a second lane can go.

## GAP-13: Control input monitor

**Needed by:** F9 MONITOR (the last 14 incoming messages) and learn mode (the next incoming
message pre-fills a `bind` line). Spec §8.9, §9 ("MIDI input").

**Today:** inputs are resolved inside the session and the binding resolver; nothing is exposed.

**Engine should provide:** a bounded, published log of inputs, `LiveShow.inputs ->
tuple[InputEvent, ...]` (the newest N, with a sequence number so a frontend polls only what is
new):

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class InputEvent:
    seq: int
    time: float                    # engine time
    surface: str                   # surface name
    input: str                     # as `bind` takes it: "cc 1 48", "note 1 0", 'osc "/x"', "clock"
    value: float | None            # 0..1, None for notes and clock
    action: str | None             # as `list bindings` prints it ("fader 1"), None if unbound
```

**Priority:** nice-to-have.

**TUI until then:** F9 hides MONITOR and learn mode. The BINDINGS `val` column shows the level of
the bound target (a playback's fader level, a master's level), not the device's raw value.

## GAP-14: Stop and restart a programmer effect

**Status:** done 2026-10-23 (see **Done** at the end of this section).

**Needed by:** the RUN/off toggle of standalone effects (F5, F1 layout B). Spec §8.5.

**Today:** a programmer effect runs from `effect add` until `effect remove <id>` or `clear`.

**Engine should provide:** `effect <id> stop|run`, keeping the instance in the programmer.
The reply is like `effect add`: `stopped effect 'fx5'`.

**Priority:** nice-to-have.

**TUI until then:** the only control on a programmer effect is `✕` (`effect remove <id>`).

**Done** (2026-10-23). `effect stop <id>` and `effect run <id>`, on a new programmer
command, `RUN_EFFECT` (`id`, `on`), and `ProgrammerStatus.stopped`, the ids of the
stopped effects. No public name was added (`busk.__all__` stays at 36); the public
dataclass gained a field and `Command` a member (the golden's diff). Documented in
`docs/console.md` (the Effects note), `docs/library.md` (section 2 and the reference),
the parser's and the programmer's module docs and `docs/dev/internals.md` (the programmer
and recording). Where it differs from the suggestion, or settles what the suggestion left
open:

- **The verb first**, `effect stop fx5`, not `effect fx5 stop`, as `effect remove fx5`:
  an id may be any word (`effect add "Pulse" id clear` is a valid line), so `effect <id>
  …` would be ambiguous with `effect add`, `remove`, `clear` and `template`. Completion
  after `effect stop ` offers the running effects' ids, after `effect run ` the stopped
  ones'.
- **The replies.** `stopped effect 'fx5'`, as suggested, and `started effect 'fx5'`.
  Stopping a stopped effect, or running a running one, is not an error: it changes
  nothing and says so (`effect 'fx5' is already stopped`), so a toggle clicked twice
  before the first click's reply is harmless. An id the programmer lacks is refused as
  `effect remove` refuses it: `the programmer has no effect 'fx9'`.
- **On stage it is removing and adding.** The programmer keeps the stopped ids, and the
  frame the session builds leaves those effects out, so the engine has nothing new. A
  stopped effect fades out over the programmer's fade time; run before it has gone, it
  fades back in on its clock; run after, it starts on a new clock, as a new effect does
  (an Hz effect at the start of its cycle, a BPM one on its master's beat grid). A
  started effect counts as the operator's latest action, as an added one does, so it
  goes on top of programmer values set since. The tests check all of this byte for byte
  against `effect remove` and `effect add`. Blind is separate: a stopped effect stays
  stopped when blind goes off, and one run while blind waits for blind off.
- **Stopping is content, not a mode.** Each stop and run is an undo step (undoing a stop
  runs the effect again), and the stopped ids are autosaved (`stopped` in the
  programmer's JSON; files from before have none) and in the event log, so `busk replay`
  replays them. A mode like blind is never undone; the stopped mark belongs to one
  instance and must follow it through an undo: removing a stopped effect and undoing it
  brings it back stopped.
- **Replacing keeps it stopped.** `effect add … id fx5` on a stopped `fx5` replaces its
  settings and leaves it stopped (the reply ends `(stopped)`), so changing an effect's
  settings off stage does not start it. `effect remove`, `effect clear` and `clear`
  forget the mark: an effect added again with that id runs.
- **A stopped effect is not recorded** (a call the user may veto). `record cue` and
  `record slot` store what the programmer runs, so a cue never starts an effect that was
  off when it was recorded. `merge` and `remove` leave the cue's own instance with that
  id alone. The reply says what was left out (`recorded cue 9/4: 2 entries, 1 effect; 1
  stopped effect not recorded`), and a programmer with nothing else to record is refused
  with `(stopped effects are not recorded)` at the end. The other reading, recording
  everything the programmer holds as blind does, would make a cue run an effect the
  operator turned off.
- **`stopped: frozenset[str]` on `ProgrammerStatus`**, instead of a key in the effect
  dicts, which stay in the show file's format. It lists only ids of `effects`: a stopped
  effect that no longer validates is left out of both, and comes back stopped with the
  undo that restores what it needs. `programmer` marks the effect `(stopped)`.
- **Under `busk run` too.** The session runs in the console process and the frame it
  installs simply lacks the effect, so the engine process needs nothing new.
- **Bindings** may carry `RUN_EFFECT`, checked for shape only, as `REMOVE_EFFECT` (the
  programmer's ids are not show data).
- Tests: `tests/test_effect_stop.py` (29, the engine change mutation-checked: every rule
  above on `OfflineShow`, a `LiveShow`, and a real `busk run` whose sACN output stops and
  moves again), the parser's rows and the help line in `tests/test_console_parser.py`,
  completion in `tests/test_console_prompt.py`, a stop and a run (undone and redone) in
  `tests/test_eventlog.py`'s replayed scenario, the command count in
  `tests/test_schema.py`, the public API golden and `tests/api_consumer.py`.

The TUI can now give a programmer effect its RUN/off toggle, on F5 and in the F1 layout B
EFFECTS panel. The state is `off` while its id is in `programmer.stopped`, and `RUN`
otherwise, dimmed while its `effects` entry fades in or out (GAP-09's `presence`). A
click sends `effect stop <id>` or `effect run <id>`, from `commands.py`, on the ordered
worker, since it is a programmer line and not a performance one (GAP-12). Each click is
an undo step, so `undo` after a toggle toggles it back, as it does for a selection. `✕`
stays `effect remove <id>`, and a cue effect's toggle stays `go N` / `release N`.

## GAP-15: Effect template library

**Status:** done 2026-10-23 (see **Done** at the end of this section).

**Needed by:** F5 TEMPLATES (name and a one-line description). Spec §8.5.

**Today:** `effect add "<template>"` finds templates in the effect library. The library is not
public (`ProfileLibrary` is; the effect library is not), so the only list is the text of
`library`. The show's own templates are in `show["effects"]`.

**Engine should provide:** a public `EffectLibrary` (like `ProfileLibrary`: iteration, `find`,
`problems`), or `LiveShow.effect_templates -> tuple[EffectTemplateInfo, ...]` with `name`, the
layers in one line (as `list effects` prints them) and the console defaults (size, low/high,
phase).

**Priority:** nice-to-have.

**TUI until then:** TEMPLATES lists the show's templates. A line under it says "more built-in
templates: type `library`".

**Done** (2026-10-23). `OfflineShow.effect_templates` and `LiveShow.effect_templates`, a
tuple of a new public dataclass, `EffectTemplateInfo` (`name`, `id`, `source`, `summary`,
`size`, `low`, `high`, `phase`). `busk.__all__` has 37 names; the golden's diff is the new
class and the two properties. Documented in `docs/library.md` (section 2 and the
reference), the runner's, console's and parser's module docs and `docs/dev/internals.md`
(the effect templates). Where it differs from the suggestion, or settles what the
suggestion left open:

- **A read on the facades, not a public `EffectLibrary`.** The TUI needs what `effect add
  "<name>"` takes, and which template a name takes is engine logic: the show's copy wins
  over the library's, found by the library template's id or by the name as an id or a
  name, in any case. With the library alone the TUI would have to merge it with
  `show["effects"]` by that rule. The library stays internal; a facade cannot be given
  another one anyway, the console always uses the built-in one.
- **One list, the show's and the library's.** The show's templates in show order, then
  the library's that the show has no copy of, in library order. `source` says which:
  `"show"`, or `"library"` for a template `effect add` embeds into the show first, after
  which it is the show's, with the same id. So F5 needs no merge of its own.
- **Listed by the rule `effect add` uses.** The parser's lookup became a function,
  `find_template`, and the list is made with it: every name of the show's templates, then
  of the library's, is looked up, and each template is kept the first time a name finds
  it, under that name. So for every entry `effect add "<name>"` takes that template, with
  those defaults; the tests check each entry on shows with a renamed copy of a library
  template, a show template named like a library one, and a repeated name. A template no
  name reaches is left out: a show template named like an earlier one (in any case), or a
  library one whose name a show template has taken. `effect add "<id>"` still reaches the
  first kind; the TUI does not offer it.
- **`summary`** is the layers in one line, as `list effects` and `library` print them
  (`pan add sine, tilt add sine +90°`): text to show as it is, like `RouteStatus.label`.
  A library template's layers are not public otherwise; once it is the show's, they are
  in `show["effects"]`.
- **The defaults are the library's, as `library` prints them**, and `None` where it has
  none: `size`, `low`, `high`, and `phase` as `(start, end)` in degrees. A show's copy of
  a library template keeps them (they are found by its id); a template the show made
  (`effect template add`) has none. `None` is not the value `effect add` then uses
  (size 1, no low or high, phase 0 0), so that a display shows only what the template
  brings, as `library` does (a call the user may veto). The rate is not here: its default
  (BPM ×1 on the show's only speed master, else 1 Hz) is the show's, not the template's.
- **The same tuple until a template changes.** The facades list again only for a new
  show object (an edit replaces the show), and keep the previous tuple when the new one is
  equal, so a frontend may compare by identity. It reads only the console's show and
  library: safe from any thread, and under `busk run --frontend` it works in the console
  process, with nothing from the engine process.
- Tests: `tests/test_effect_templates.py` (21, the engine change mutation-checked), the
  frontend probe's report in `tests/test_frontend.py` (a real `busk run --frontend`), the
  count and the golden in `tests/test_public_api.py`, `tests/api_consumer.py`, and the
  guide's example in `tests/test_docs.py`.

The TUI's F5 TEMPLATES can now be `LiveShow.effect_templates` as it is, read by the
bridge with the show (a new tuple only when a template changed): one row per entry with
its `name`, `summary` and the defaults it has (`size 20`), the `library` ones marked until
the first `effect add` embeds them. A click sends `effect add "<name>"` from
`commands.py`, so the library's defaults apply. The "type `library`" line goes, and F5
needs no `library` text. In the implementation plan's §2.6 the built-in library row
becomes **S**, from `doc`.

## GAP-16: Fixture category

**Needed by:** F1 layout A rows (PARS, SPOTS, WASHES, BARS, STROBES), layout C glyphs
(`■ ◆ ● ▲`), F8 DMX map colours by type. Spec §8.1, §8.8.

**Today:** profiles have no category. OFL and GDTF files have one, and the importers drop it.

**Engine should provide:** an optional `category` on `FixtureProfile` (for example `"par" |
"spot" | "wash" | "beam" | "strobe" | "pixel" | "dimmer" | "effect" | "other"`), filled by
`read_ofl`/`read_gdtf` and settable with `profile …`. This is an optional key, so it is not a
breaking change.

**Priority:** nice-to-have.

**TUI until then:** rows, glyphs and map colours go by profile: one row per profile, labelled
with its name, and colours assigned to profiles in show order.

## GAP-17: Playback colour

**Needed by:** F1 fader and bar colour ("colour = current cue colour"). Spec §8.1.

**Today:** a playback has an optional static `uiColor` (`playback N uiColor "#ff8800"`), which
the TUI uses. The colour of the current look depends on resolving the cue's values, presets and
tracking, which is engine logic.

**Engine should provide:** `PlaybackStatus.color: tuple[float, float, float] | None`, a
representative colour of the playback's current output (for example the colour of the first
target it drives), updated with the snapshot.

**Priority:** nice-to-have.

**TUI until then:** bars and faders use `uiColor` when it is set and parses as a colour, else the
neutral foreground.

## GAP-18: Quit signal

**Needed by:** the prompt: typing `quit` should end the TUI as it ends `busk run`.

**Today:** `execute("quit")` returns `Reply("", ok=True)` and sets a private flag.

**Engine should provide:** `Reply.quit: bool = False` (a new field with a default, so it is not
breaking), or `LiveShow.quit_requested`.

**Priority:** nice-to-have.

**TUI until then:** a line that is exactly `quit` opens the TUI's quit dialog instead of going to
the engine. It is the only line the TUI intercepts.

## GAP-19: `status` under `LiveShow`

**Needed by:** typing `status` in the TUI prompt.

**Today:** `LiveShow` builds its console without a status callable, so `status` answers
`no engine is running` while the engine runs.

**Engine should provide:** the same status line `busk run` prints, built from the snapshot.

**Priority:** nice-to-have.

**TUI until then:** `status` is sent to the engine like any other line, and the reply is shown as
it is. The status bar has the same information.

## GAP-20: Completion and hints

**Needed by:** Tab completion beyond the first word, and richer hints. Spec §6.1, §7.2.

**Today:** `busk run`'s prompt completes every word from `Console.expected(line)` (words, value
placeholders, errors, whether the line is runnable), which is internal. The TUI does what the
spec asks: it indexes the text of `help` by first word.

**Engine should provide:** `LiveShow.expected(line) -> Expected`, with public fields `words`,
`values`, `runnable` and `error`.

**Priority:** nice-to-have.

**TUI until then:** first-word completion and one or two matching `help` lines, as specified.
If the format of `help` changes, hints degrade to nothing; commands still run.

## GAP-21: Engine health

**Needed by:** a status-bar warning when the engine stalls or overruns.

**Today:** the TUI can only watch `LiveShow.frame.seq`. If no new frame arrives for 0.5 s, it shows
a red `ENGINE` chip.

**Engine should provide:** `LiveShow.health -> EngineHealth(running: bool, ticks: int,
overruns: int, lastTickAge: float)`.

**Priority:** nice-to-have.

**TUI until then:** the `frame.seq` watch described above.
