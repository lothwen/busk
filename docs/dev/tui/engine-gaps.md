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

The TUI runs a `busk.LiveShow` in its own process. One module, `busk_tui/bridge.py`, imports
`busk`, and only names in `busk.__all__`:

- **Actions** go through `LiveShow.execute(line) -> Reply(text, ok)`, one console line per
  action, echoed in the TUI's log. `submit()` is not used, so the UI teaches the command line.
- **Reads** use the typed public state: `LiveShow.snapshot` (`EngineSnapshot`),
  `LiveShow.frame` (`DmxFrame`, for the engine time), `LiveShow.show` (the `Show` document),
  `LiveShow.warnings`, since GAP-01 `LiveShow.output` (`OutputSnapshot`) and since GAP-02
  `LiveShow.programmer` (`ProgrammerStatus`). The `busk.*` loggers feed the TUI's log pane.
- **Text is not parsed.** `docs/library.md` says message text (`Reply.text`, CLI output, log
  records) may change in any release, so the TUI never extracts data from the output of
  `programmer`, `info`, `list …` or `library`. It may show such output verbatim.

So a gap below is one of two kinds:

- **a read**: data the TUI must display that is not in the typed public state. The suggested
  shape is a read-only `LiveShow` property returning a frozen dataclass, published by reference
  like `EngineSnapshot`, and exported in `busk.__all__`;
- **an action**: something an operator does that has no console line. The suggested shape is a
  new console line, so `execute()` covers it and the `busk run` prompt gets it too.

Every new read should also reach `busk run`'s console process, so a later TUI attached to
`busk run` ([GAP-11](#gap-11-running-the-tui-against-busk-run)) gets it too.

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
| [GAP-07](#gap-07-output-route-status) Output route status | read | important | status bar, F8 | open |
| [GAP-08](#gap-08-surface-status) Surface status | read | important | F9 | open |
| [GAP-09](#gap-09-effect-runtime-state) Effect runtime state | read | important | F1 B, F5 | open |
| [GAP-10](#gap-10-confirmation-before-dangerous-lines) Confirmation before dangerous lines | read | important | prompt | open |
| [GAP-11](#gap-11-running-the-tui-against-busk-run) Running the TUI against `busk run` | host | important | everything, on stage | open |
| [GAP-12](#gap-12-concurrency-contract-of-execute) Concurrency contract of `execute()` | contract | important | responsiveness | open |
| [GAP-13](#gap-13-control-input-monitor) Control input monitor | read | nice-to-have | F9 | open |
| [GAP-14](#gap-14-stop-and-restart-a-programmer-effect) Stop and restart a programmer effect | action | nice-to-have | F1 B, F5 | open |
| [GAP-15](#gap-15-effect-template-library) Effect template library | read | nice-to-have | F5 | open |
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

## GAP-08: Surface status

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

## GAP-09: Effect runtime state

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

## GAP-10: Confirmation before dangerous lines

**Needed by:** the prompt. `busk run` asks before `output off`; the TUI should too.

**Today:** the question exists (`Console.confirmation(line)`) but is internal. The TUI cannot
know which lines need confirmation without parsing them.

**Engine should provide:** `LiveShow.confirmation(line) -> str | None`, the yes/no question to
ask before running `line`, or `None`.

**Priority:** important (safety).

**TUI until then:** the TUI's own `[OUTPUT OFF]` button asks first. A typed `output off` runs at
once, as in a script. The user guide says so.

## GAP-11: Running the TUI against `busk run`

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
reads above). Today the attached show's `frame` and `output` ([GAP-01](#gap-01-fixture-output-values))
are `None`: the engine process sends the console process only snapshots, so either option
must carry the frames and the output captures too.

**Priority:** important.

**TUI until then:** it runs a `LiveShow` with `tune_interpreter=True`, as `busk run` tunes its
engine process. The startup banner and the user guide say that for a show on stage, `busk run`
is the safer host. The TUI shows an `ENGINE` warning chip when frames stop arriving
(see GAP-21).

## GAP-12: Concurrency contract of `execute()`

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

**Needed by:** the RUN/off toggle of standalone effects (F5, F1 layout B). Spec §8.5.

**Today:** a programmer effect runs from `effect add` until `effect remove <id>` or `clear`.

**Engine should provide:** `effect <id> stop|run`, keeping the instance in the programmer.
The reply is like `effect add`: `stopped effect 'fx5'`.

**Priority:** nice-to-have.

**TUI until then:** the only control on a programmer effect is `✕` (`effect remove <id>`).

## GAP-15: Effect template library

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
