# Fixture effects: implementation plan

> Source: the user's request of 2026-10-20. Import OFL `Effect`, `EffectSpeed`,
> `EffectDuration`, `EffectParameter` and `SoundSensitivity`, and GDTF `Effects(n)`,
> `Effects(n)Rate`, `Effects(n)Fade`, `Effects(n)Adjust(m)`, `Effects(n)Pos`,
> `Effects(n)PosRotate` and `EffectsSync`, so that the programs built into a fixture are
> programmable in busk. Today both importers turn these channels into `control` channels held
> at their default. This is the "generic fixture programs" item of
> `docs/color-macros-plan.md` §9, built on the same machinery. The user took every
> recommendation of §3.1 on 2026-10-20: Q1(a) … Q6(a), marked *(user)*. The calls of §3.2
> are the plan's, open to veto.

In this plan, **fixture effects** are the programs a fixture runs by itself. busk's own effects
(Phase 5, `effect add`) are **busk effects**.

## 1. Scope

**In:**
- new attributes: `effect` (and `effect2`, Q4), `effectRate`, `effectFade`, `effectAdjust`,
  `effectRotation`, `effectSync` and `soundSensitivity`;
- scalar defaults that follow the channel (Q2), and a rule that keeps maintenance ranges from
  being options (Q5);
- the OFL and GDTF mappings;
- tests at every level, the TupperDMX transcriptions, a sweep over real fixture libraries, and
  the docs.

**Out** (§9): the LED bar's direction channel (an OFL `Generic` channel); indexed angles of
effect, gobo and prism wheels (Q6); stepping discrete attributes with busk effects;
regenerating the TupperDMX sidecar scripts.

## 2. What the files contain

Surveys run on 2026-10-20 (scripts in the session scratchpad, not in the repo).

**OFL**: the repository's `fixtures/` at `2d74941` (2026-10-20), 636 fixtures, 567 of which
import today.
- **Schema.** An `Effect` has an `effectName` or an `effectPreset` (`ColorJump`, `ColorFade`).
  It may also have a `speed`, `duration`, `parameter` or `soundSensitivity` (each one value or
  a start/end pair) and `soundControlled`. `EffectSpeed`, `EffectDuration`, `EffectParameter`
  and `SoundSensitivity` each carry one of those properties alone.
  - speeds: Hz, bpm, %, `slow`, `fast`, `stop`, `slow reverse`, `fast reverse`;
  - durations: s, ms, %, `instant`, `short`, `long`;
  - parameters: a number, %, `off`, `low`, `high`, `small`, `big`, `slow`, `fast`, …;
  - sensitivities: %, `off`, `low`, `high`.
- **`Effect`** (other than `ColorJump`/`ColorFade`): 658 channels, 6,286 ranges.
  - **417 channels have nothing else busk drives.** These become `effect`.
    - 302 of them also have a `NoFunction` range (278 start with one), and 77 are all
      effects.
    - 42 hold `Maintenance` ranges ("Reset all", motor resets, "Blackout with pan/tilt
      movement").
    - 9 are per-pixel templates, used by 5 modes.
  - 51 more also hold colour effects. They are `colorEffect` today and stay so.
  - 190 share a channel with something busk drives (`ColorPreset` 67, `ShutterStrobe` 58,
    `WheelSlot` 36, `Prism` 9 …). They keep their attribute.
  - Of the 6,286 ranges, 655 are sound-controlled, 248 have a speed, 68 a duration, 58 a parameter
    and 16 a sound sensitivity. Two have two of these, a speed and a parameter.
  - **430 modes have an effect channel, and 110 have two or more** (82 two, 16 three, 12 four
    to nine). The second is often a different selector: "Pan/Tilt Macro" beside "Auto
    Programs", "Effect Palette" beside "Effect Mode", "Sound Mode Selection", "Program Group
    Size".
- **`EffectSpeed`**: 321 channels in 286 fixtures. 297 of them are speed only, 7 of those with
  a `NoFunction`.
  - Speeds are almost all `slow`…`fast`. Of the 297, 19 have a `stop` range, 11 have reverse
    ranges, and 3 are in Hz or bpm.
  - 254 of the 297 have no `defaultValue`, so they are held at DMX 0 today.
  - OFL does not say which channel a speed drives. Of the 290 modes with a speed channel:
    - 87 have an effect channel and no colour macro;
    - 101 have a colour macro and no effect channel;
    - 90 have both, and 12 neither.
  - 13 modes have two speed channels ("Color Snap Speed" and "Color Fade Speed").
- **`SoundSensitivity`**: 91 channels in 84 fixtures. 82 are sensitivity only, and 4 have a
  `NoFunction` "sound off" range. The 2 with a strobe stay `shutter`.
- **`EffectParameter`**: 55 channels in 26 fixtures, 49 of them parameter only. 25 are in %,
  17 in keywords and 7 in plain numbers (Astera's group size 1–4).
- **`EffectDuration`**: 35 channels in 27 fixtures, all duration only (5 with a `NoFunction`).
  27 use keywords (`instant`…`long`); the rest use seconds or %.
- **Maintenance on option channels today.** 4 `ColorPreset` channels of Cameo's Pico family
  (10 mode channels) are `colorMacro` channels with a `reset` option, which `set colorMacro
  reset` outputs.

**GDTF**: [heliostate/OpenGDTFLibrary](https://github.com/heliostate/OpenGDTFLibrary), 5,733
descriptions (5,380 GDTF 1.1, 353 GDTF 1.0), as for the colour macros, and the 1.2 spec
([mvrdevelopment/spec](https://github.com/mvrdevelopment/spec)).
- **The spec puts all seven attributes in the `Beam` feature:**

  | Attribute | Spec | Unit |
  |---|---|---|
  | `Effects(n)` | "Generically predefined macros and effects of a fixture." | — |
  | `Effects(n)Rate` | "Frequency of running effects." | Frequency |
  | `Effects(n)Fade` | "Snapping or smooth look of running effects." | — |
  | `Effects(n)Adjust(m)` | "Controls parameter (m) of effect (n)" | — |
  | `Effects(n)Pos` | "Controls angle of indexed rotation of slot/effect in effect wheel/macro (n). This is the main attribute of effect wheel/macro (n) slot/effect control." | Angle |
  | `Effects(n)PosRotate` | "Controls speed and direction of slot/effect in effect wheel (n)." | AngularSpeed |
  | `EffectsSync` | "Sets offset between running effects and effects 2." | — |

- **Mode channels by logical attribute:**
  - `Effects1`: 142 (66 fixture types);
  - `Effects1Rate`: 136 (62);
  - `Effects1Fade`: 68 (22);
  - `EffectsSync`: 25 (9, Martin's VDO family);
  - `Effects1Pos`: 9 (3, Robe's Pointe family);
  - `Effects2` and `Effects2Rate`: 1 each.
- **No file uses `Effects(n)Adjust(m)`.** It is in the 1.2 spec only, as `ColorMacro(n)Rate`
  was. GDTF has no sound sensitivity attribute.
- **`Effects1` channels** hold `Effects1` functions only (120), with a `NoFeature` (19), or
  with strobe functions (3).
  - Their channel sets are named: "No Effect" 163 times, "Safe" 51, "NoFeature" 30, then
    chases, programs and "Music Control".
  - None links a wheel.
- **51 `Effects1` functions sit in `Control1` channels**, next to `FixtureGlobalReset`,
  `PositionReset`, `ZoomReset` and `LampControl`.
- **Physical values.**
  - `Effects1Rate` is 0…1 in 97 of 137 functions, else a span such as 1…10, 0.1…25.5 or
    0…100. The 1.0/1.1 files give it the unit "Speed" (59) or "Frequency" (9).
  - `Effects1Fade` is 0…1 (52 of 75) or 0.1…25.5 (Robe's "Effect Time").
  - `EffectsSync` is 0…255, its sets "No Sync", "Fixture Offset 10deg" ….
  - `Effects1Pos` is −180…180°, and its `Effects1PosRotate` ±30.
- 127 of the 135 modes with `Effects1Rate` have an `Effects1` channel. 2 have only a colour
  macro.

**Worked examples**: the user's TupperDMX fixtures (`tupperDMX-simulator/fixtures`). The LED
bar and the blinder are also in `tests/fixtures/ofl/tupperdmx`.
- **LED bar, 7ch.**
  - `animation`: 35 effects of 4 DMX values each ("On" 0–3, "Strobo" 4–7 … "Fuego" 68–71 …
    "Strobo+rain" 136–139), then `NoFunction` 140–255. Default 0.
  - `speed`: `EffectSpeed` slow→fast, default 255.
  - `direction`: `Generic` "Forward" 0–127, "Reverse" 128–255.
  - Import today reports `Animation speed: no busk attribute (EffectSpeed); held at DMX 255`.
- **Blinder, 8ch.**
  - `mode`: `NoFunction` "Manual" 0–9, "Auto program" 10–249 slow→fast, "Sound active"
    250–255 (sound-controlled). Default 0.
  - `speed`: `EffectSpeed` slow→fast, default 0.
- **Wild Wash Pro 648 RGBW, 6Ch** (in the simulator only).
  - "Dimmer Pattern": `NoFunction` 0–16, then 18 patterns.
  - "Dimmer Pattern Speed": two `EffectSpeed` ranges, "Change" 0–127 and "Gradual transient"
    128–255, each slow→fast.
  - "Color Macro": `colorMacro` since the colour macros.
  - "Sound Control": `NoFunction` "Sound control off" 0–5, then `SoundSensitivity` low→high
    6–255.

## 3. Decisions

### 3.1 Answered by the user (2026-10-20): every recommendation, (a)

1. **Names.**
   - **(a) After GDTF and OFL *(user)*:** `effect`, `effectRate`, `effectFade`,
     `effectAdjust`, `effectRotation`, `effectSync`, `soundSensitivity`.
     - They match `colorEffect`, which already means a fixture's own effects.
     - The docs say "fixture effect" and "busk effect" to keep them apart.
     - The parser has no clash: attribute names come after `set`, `park`, `unpark` and
       `release … only`, never where the `effect` command is parsed.
   - **(b) After GDTF's display names:** `fx`, `fxRate`, `fxFade`, …. No word is shared with
     busk effects, but they don't match `colorEffect`.

   Shows store these names, so renaming later is a breaking change.
2. **What an uncontrolled rate, fade, parameter or sensitivity outputs.**
   - **(a) The channel's own default *(user)*.** This is Q1(a) of the colour macro plan,
     applied to scalars.
     - A slot with a channel starts at the value its `defaultDmx` reads back to, through the
       range that holds it.
     - A slot without a channel (a parameter only) takes the registry's number (§5.1).
     - An unprogrammed fixture outputs what it outputs today: the LED bar's speed stays at
       255.
     - `colorMacroRate` follows its channel too. No imported file changes, because its slots
       are all parameters today.
   - **(b) The registry's number.** Every uncontrolled speed channel moves to the middle of its
     range: DMX 128 on the LED bar, which runs at 255 today.
3. **Which rate an OFL `EffectSpeed` channel drives.**
   - **(a) The mode decides *(user)*.** It drives `colorMacroRate` in a mode with a colour
     macro or colour effect channel and no effect channel, and `effectRate` everywhere else.
     - 101 of the 290 modes are macro-only.
     - There, `set colorMacroRate 0.8` moves the speed channel and the speeds inside the
       macro's options together.
   - **(b) Always `effectRate`.** It is simpler, but on a macro-only par the user speeds up
     its colour programs with `effectRate`.

   GDTF `Effects(n)Rate` is always `effectRate`: 127 of 135 modes pair it with an
   `Effects(n)` channel.
4. **A second effect channel on an element** (26 % of the OFL modes that have one).
   - **(a) `effect2` *(user)*.** It is the second effect channel in DMX order, and GDTF's
     `Effects2`. Later ones are held and reported. The rates and fades are shared (§3.2).
   - **(b) The first only.** Later ones are held, as `ColorMacro2` is (Q4(a) of the colour
     macro plan). Second macros were rare; second effect channels are not.
5. **Maintenance ranges on option channels** (42 OFL effect channels; 4 colour macro channels
   today).
   - **(a) Never options *(user)*.**
     - The channel is driven, but its maintenance ranges are never output, as on wheels and
       shutters.
     - The OFL import names `Maintenance` ranges `maintenance`, and no `reset`, `lampOn`,
       `lampOff` or `maintenance` function is ever an option.
     - The Cameo Pico macros lose their `reset` option.
   - **(b) Such a channel stays `control`.** The 42 channels' programs are lost, and the colour
     macros are unchanged.
   - **(c) Options like any other range,** the colour macro rule. `set effect resetAll` then
     resets the fixture.
6. **`Effects(n)Pos`, the index angle** (3 Robe types; OFL has no counterpart).
   - **(a) As a gobo index *(user)*.**
     - On a channel with both index and rotation functions, the rotation drives it
       (`effectRotation`, °/s).
     - The index function is a dead band at rotation 0, as `Gobo1Pos` is today.
     - The angle is not settable, as it is not for gobos and prisms.
   - **(b) `effectPosition`, in degrees.** The spec makes `Effects(n)Pos` the main attribute,
     so the Robe channels would take the index and lose the rotation. Having both needs a
     channel driven by two slots, which is a converter change (§9).

### 3.2 The plan's calls (open to veto)

- **Family `beam`.** It is GDTF's feature for all seven attributes.
  - `record preset beam` and `only beam` carry them, and cues time them with the beam family.
  - A new family would change the show schema (`perFamily` timing, the preset pools).
  - They follow `frost` in the registry. Slots of fixtures without these channels do not move.
- **Units.** All are normalised except `effectRotation` (°/s, CW positive, as
  `gobo1Rotation`).
  - `effectRate`: 0 slowest, 1 fastest, as `colorMacroRate` (Q3(a) of the colour macro plan).
    GDTF calls it a frequency, but most files give 0…1, and OFL speeds are mostly
    `slow`…`fast`.
  - `effectFade`: 0 snap or shortest, 1 smoothest or longest.
  - `effectAdjust` and `effectSync`: 0…1.
  - `soundSensitivity`: 0 off or lowest, 1 highest.
  - Values outside 0…1 (seconds, Hz, GDTF's 0…255) are rescaled over the channel's span and
    reported, as GDTF's `_NORMALISED` attributes are today.
- **One of each per element.**
  - `effectRate`, `effectFade`, `effectAdjust` and `soundSensitivity` are shared by `effect`,
    `effect2`, their own channels and the options' parameters.
  - A second channel of one is held and reported: 13 OFL modes have two speeds, and GDTF has
    `Effects2Rate` and `Effects(n)Adjust(m ≥ 2)`.
- **Every range is an option** on an effect channel, sound-active programs included, except
  maintenance (Q5). This is the colour macro rule.
  - An option with a speed, duration, parameter or sensitivity takes the first of them, in
    that order, as its parameter. A second one is reported (2 OFL ranges).
  - A strobe range keeps `strobeRate`, so `safety strobe` still caps it.
- **Last resort.** The new types never take a channel that busk drives today.
  - On OFL, they choose a channel's attribute only when no other capability on it maps. A
    channel with colour effects stays `colorEffect`.
  - On GDTF, `effect` comes only from a logical channel's own attribute, so the `Control1`
    channels with resets stay `control`.
- **Colour macro channels are unchanged**, apart from Q5. Their effect ranges still take a
  speed only (`colorMacroRate`).
- **Speed channels.** `slow` and `stop` are 0, `fast` is 1, and n % is n/100
  (`_macro_speed`).
  - The converter outputs the first range that holds a value, so reverse ranges could never be
    reached. They become functions named `reverse`, reported (11 OFL channels).
  - The Wild Wash's "Gradual transient", a second slow…fast range, is never output either, as
    with any repeated range.
- **Registry numbers** (the default of a slot without a channel):
  - `effectRate` and `effectAdjust` 0.5; `effectFade`, `effectRotation`, `effectSync` and
    `soundSensitivity` 0.
  - `effectRate`, `effectAdjust` and `effectRotation` fade. `effectFade`, `effectSync` and
    `soundSensitivity` snap, like `positionSpeed`.
- **No `schemaVersion` bump**, as for the colour macros: the attributes are additions. **No
  highlight change.** **`IMPORT_VERSION` becomes 3.**

## 4. Files

| File | Change |
|---|---|
| `src/busk/model/attributes.py` | the definitions; scalars that follow their channel (Q2) |
| `src/busk/model/profile.py` | `effect` and `effect2` in `MACRO_ATTRIBUTES`; `MAINTENANCE_FUNCTIONS` (Q5) |
| `src/busk/compiler/slots.py` | `_default_value` reads a following scalar's `defaultDmx` back |
| `src/busk/importers/ofl.py` | the new types as a second tier, their values, Q3, Q4, Q5 |
| `src/busk/importers/gdtf.py` | the `Effects…` attributes, the index dead band, option attributes from logical channels only |
| `src/busk/importers/__init__.py` | `IMPORT_VERSION = 3` |
| `examples/tupperdmx/` | the LED bar's and blinder's transcriptions; `tupper-demo.show` rebuilt |
| `tests/…` | `test_attributes`, `test_profile`, `test_slots`, `test_ofl`, `test_gdtf`, `test_fixture_effects` (end to end), the CLI transcripts |
| `docs/…` | `profiles.md`, `console.md`, `safety.md`, the spec's §5.3 table, `CHANGELOG.md` |

No change is expected in the validator, the resolver, the converters, the engine process, cue
tracking or the console. They are generic over the registry, over options with parameters
and, for Tab completion, over `option_capabilities`. Step 2 proves it.

## 5. Design

### 5.1 Registry

| Attribute | Family | Kind | Unit | Merge | Fade | Default |
|---|---|---|---|---|---|---|
| `effect` | beam | discrete | — | LTP | snap | the channel's default option |
| `effect2` (Q4) | beam | discrete | — | LTP | snap | the channel's default option |
| `effectRate` | beam | scalar | normalised, 1 fastest | LTP | fade | the channel's (Q2), else 0.5 |
| `effectFade` | beam | scalar | normalised, 1 longest | LTP | snap | the channel's, else 0 |
| `effectAdjust` | beam | scalar | normalised | LTP | fade | the channel's, else 0.5 |
| `effectRotation` | beam | scalar | °/s, CW positive | LTP | fade | the channel's, else 0 |
| `effectSync` | beam | scalar | normalised | LTP | snap | the channel's, else 0 |
| `soundSensitivity` | beam | scalar | normalised, 0 off | LTP | snap | the channel's, else 0 |

The registry grows from 23 attributes to 31 (30 without `effect2`).

### 5.2 Options, maintenance and defaults

- **Options.** `MACRO_ATTRIBUTES` gains `effect` and `effect2`. Their options are every slot
  and function capability, the first id winning, as for colour macros. The validator's
  messages and `channel_default_option` need nothing new.
- **Maintenance (Q5(a)).** `MAINTENANCE_FUNCTIONS = {"reset", "lampOn", "lampOff",
  "maintenance"}`.
  - `_option_id` never makes them options, on any channel. Today only option channels can
    offer them.
  - `FunctionCapability.fn`'s literal gains `"maintenance"`.
- **Scalar defaults (Q2(a)).** A definition gets `followsChannel: bool`. It is false for the
  14 scalars of today, except `colorMacroRate`. `_default_value` then returns:
  - with a channel, the value of the range capability that holds its `defaultDmx`,
    interpolated, with `invert` applied as the converter applies it;
  - otherwise (no channel, or a `defaultDmx` inside a function), the registry number.

  `default` stays a number, so the validator and the importers' `_default_option`, the other
  readers of `default`, don't change.

### 5.3 OFL

- **Attribute.** A channel's attribute is still that of its first capability busk drives
  today, the colour effect rule included. Failing that, it is that of its first capability
  among the new types:
  - `Effect` → `effect`;
  - `EffectSpeed` → `effectRate` (or `colorMacroRate`, Q3);
  - `EffectDuration` → `effectFade`;
  - `EffectParameter` → `effectAdjust`;
  - `SoundSensitivity` → `soundSensitivity`.

  In `_candidate` this is a second tier, as the `others` check already is for colour effects.
- **Q3(a)**, in `_assign`: an `effectRate` channel in a mode with a `colorMacro` or
  `colorEffect` channel and no `effect` channel becomes `colorMacroRate`.
- **Q4(a)**, in `_dedupe`: a second `effect` on an element becomes `effect2`, and a third is
  held.
- **The ranges of an effect channel** go through `_Fixture.macro` and `_ModeBuilder._macro`,
  as for colour macros:
  - `NoFunction` → `off`, and `Maintenance` → `maintenance` (Q5);
  - `Effect` → a function named after its `effectName`, `comment` or `effectPreset`. Its
    parameter comes from its speed (`effectRate`), duration (`effectFade`), parameter
    (`effectAdjust`) or sensitivity (`soundSensitivity`);
  - an `EffectSpeed`, `EffectDuration`, `EffectParameter` or `SoundSensitivity` range → a
    function option with that parameter;
  - `ShutterStrobe` keeps `strobeRate`.
- **Scalar channels** map their ranges in `_values`. `NoFunction` is a dead band at 0, so
  `_REST` gains the five scalars.
  - Speed: `_macro_speed` (slow and stop 0, fast 1, n %). Reverse ranges become a function
    `reverse`. Speeds in Hz or bpm are rescaled over the channel's span and reported.
  - Duration: `instant` and `short` 0, `long` 1, n %. Seconds and milliseconds are rescaled
    over the span and reported.
  - Parameter: `off`, `low`, `small`, `slow`, `instant` and `short` 0; `high`, `big`, `fast`
    and `long` 1; n %. Plain numbers are rescaled over the span and reported.
  - Sensitivity: `_fraction({"off": 0, "low": 0, "high": 1})`.
- **Templates.** A per-pixel effect channel's pixels share option names, since
  `_Fixture.macro` is keyed by the OFL channel.
- **The worked examples**, with Q2(a) and Q3(a):
  - **LED bar.**
    - `effect`'s options are `on`, `strobo`, `fade`, `loadingCortaArriba` … `stroboRain`
      and `off`.
    - Uncontrolled, it outputs DMX 1 (`on`). `set effect fuego` outputs 69, and `set effect
      off` 197.
    - `effectRate` is 1 when uncontrolled (DMX 255, as today), and `set effectRate 0.5`
      outputs 128.
    - `direction` stays `control`.
  - **Blinder.**
    - `effect`'s options are `off` (uncontrolled, DMX 4), `autoProgram` (with `effectRate`)
      and `soundActive` (252).
    - `set effect autoProgram` with `set effectRate 0.5` outputs 130 on `mode` and 128 on
      `speed`: one slot drives two channels.
  - **Wild Wash 6Ch.**
    - `effect`'s options are `off` and `dimmerPattern1` … `dimmerPattern18`.
    - `effectRate` drives the speed channel, because the mode has an effect channel. It
      reaches "Change" only.
    - `soundSensitivity` 0 is DMX 0 (sound off), and 0.5 is 130.

### 5.4 GDTF

- **Attributes.** `ATTRIBUTES` gains:
  - `Effects1` → `effect` and `Effects2` → `effect2` (Q4);
  - `Effects1Rate` → `effectRate` and `Effects1Fade` → `effectFade`;
  - `Effects1Adjust1` → `effectAdjust`;
  - `Effects1PosRotate` → `effectRotation`;
  - `EffectsSync` → `effectSync`.

  Other numbers stay `control` and are reported.
- **Option attributes from logical channels only.** `_assign` takes an attribute of
  `MACRO_ATTRIBUTES` from a logical channel's own attribute, never from a function inside
  another logical channel. That keeps the 51 `Control1` channels `control`. The sweep checks
  that no colour macro changes.
- **An effect channel** goes through `_macro`, as for colour macros:
  - `NoFeature` and the `_OFF` names ("No Effect" included) → `off`;
  - channel sets → options named after them;
  - strobe functions keep `strobeRate`;
  - a function of one of the new scalars → an option with that parameter, through `_unit`.
- **Scalars.** `_NORMALISED` gains `effectRate`, `effectFade`, `effectAdjust` and
  `effectSync`, so physical values outside 0…1 are rescaled and reported. The larger physical
  value is the faster or the longer one.
- **Q6(a).** `_INDEX` gains `Effects1Pos`.
  - The Robe channels' logical attribute, `Effects1Pos`, maps to nothing. Their first mapped
    function, `Effects1PosRotate`, makes them `effectRotation`, in °/s as given.
  - The index function is a dead band at rotation 0, as for gobos.

### 5.5 Console

Nothing changes:
- `set effect <Tab>` offers the selection's programs (colour macro step 6);
- `?` shows them;
- the parser takes `effect` as an attribute name.

Step 2 checks all three.

## 6. Steps

Baseline at `4b24c0b`: 3380 passed, 1 skipped, 13 deselected (2026-10-20). Each step ends with
the suite green, `ruff check`, `ruff format --check` and `mypy src`. Use `uv run python -m pytest` (the venv's console scripts have a stale
shebang). Each step is one commit.

1. **Registry, options, maintenance, scalar defaults** (§5.1–5.2).
   Verify:
   - `test_attributes`' rows and count (23 → 31). The spec's §5.3 table and `console.md`'s
     attribute table get their rows now, since `test_attributes` checks them against the
     registry;
   - an effect channel's options, with maintenance functions left out, also on a colour macro;
   - a following scalar's default:
     - the value of the range holding `defaultDmx`, also with `invert`;
     - the registry number when no range holds it;
     - the registry number for a slot that is a parameter only.

   **Done** (2026-10-20): 3397 passed.
   - `AttributeDefinition.followsChannel` (scalars only), read by
     `slots._channel_default_value`: the first range capability holding `defaultDmx`,
     interpolated, `invert` applied. A `defaultDmx` in a function falls back to the registry.
   - `profile.MAINTENANCE_FUNCTIONS`; `_option_id` leaves them out on every channel. The
     validator's message for a macro channel without options now says "other than
     maintenance".
   - There is no `test_profile.py`: the option and default tests are in `test_slots.py`
     (`effects_show`), as the colour macros' are.
   - `test_color_macros.py` changed with Q2(a): `macro_rig`'s rate channel has
     `defaultDmx` 0, so its uncontrolled rate is now 0, while the macro-only fixture's
     parameter-only rate stays 0.5. The highlight case sets the rate to keep its DMX.
2. **End to end, with a hand-written profile.** `builders.effects_rig()` has three fixtures:
   - an LED-bar-like fixture: `off` last, and a speed channel defaulting to 255;
   - a blinder-like fixture: an option with `effectRate`, and a speed channel;
   - a fixture with a sound sensitivity channel and its dead band.

   No production code is expected to change. Verify through `OfflineShow`/`DmxFrame`, in
   `tests/test_fixture_effects.py`:
   - `set`, `record cue` and `go`: the DMX of each option, and a parameter through its range;
   - one `effectRate` slot driving an option's parameter and a speed channel together;
   - release back to the channel's defaults (DMX 255 on the speed channel);
   - `effect` snapping at the start of a fade, and `effectRate` fading;
   - `park` and `highlight`;
   - a beam preset applied to two fixture types;
   - a busk effect (a sine) on `effectRate`;
   - `set effect <Tab>` and `?`;
   - the vectorised converter agreeing with the reference one (`test_convert_properties` on
     the rig).

   **Done** (2026-10-20): 3409 passed. No production code changed.
   - `builders.effects_rig()` and `tests/test_fixture_effects.py`: ten cases with
     hand-computed DMX; `test_convert_properties` runs on the rig too.
   - Beam presets default to the `profile` scope (`parser._DEFAULT_SCOPE`), so the
     cross-type case records with `global`.
   - The busk effect is checked at t = 1/6 and 0.5, not 0.25: there the sine is
     0.5 − 3·10⁻¹⁷, which rounds to DMX 127.
3. **OFL** (§5.3). Verify in `test_ofl.py`, with synthetic channels:
   - the LED bar, the blinder and the Wild Wash 6Ch: the worked examples' DMX;
   - an effect channel with `Maintenance` ranges, and a Cameo-like macro without its `reset`
     (Q5);
   - speed channels with reverse and stop ranges, and in Hz;
   - Q3's two cases;
   - two and three effect channels on an element (Q4);
   - an option with a speed and a parameter (reported);
   - the channels that keep their attribute: a strobe channel with effects (`shutter`), a
     channel with colour and other effects (`colorEffect`), `EffectSpeed` with `ShutterStrobe`
     (`shutter`);
   - durations, parameters and sensitivities in each of their units;
   - a per-pixel template.

   The TupperDMX check compares whole frames, so the LED bar's and the blinder's hand
   transcriptions (`examples/tupperdmx/profiles`) get the same `effect` and `effectRate`
   channels. Rebuild `tupper-demo.show`, and regolden `import-ofl.txt` (`BUSK_REGOLDEN=1`).

   **Done** (2026-10-20): 3427 passed. Deviations from §5.3:
   - **Tiers.** `_candidate` is unchanged (busk's existing attributes); `_attribute` falls
     back to `PROGRAMS` (by capability type) only when no capability maps. `_capabilities`
     maps a range when `_candidate(cap) or PROGRAMS[cap.type]` is the channel's attribute.
   - **A default in a maintenance range holds the channel** (a call open to veto). On 21 OFL
     mode channels (Elation Platinum and Proteus "Special functions", ADJ VBar Pak "Mode",
     Briteq BT-LEDROTOR "Blades", Eurolite LED TMH-X12, ADJ Vizi Spot), `defaultValue`
     selects a maintenance range such as "Dimmer mode" or "Colour change normal". With
     Q5(a) busk cannot output it, and the first option, sometimes a program, would run on an
     unprogrammed fixture. Such a macro or effect channel stays `control` at its default,
     reported (`_maintenance_default`, shared with the GDTF import).
   - **`stop` and `instant` are 0 Hz and 0 s** when a channel's speeds or durations are
     rescaled: Panasonic's "Fade in" is instant, 0.5 s … 10 s, and over 0.5…10 s the 0.5 s
     range would be unreachable.
   - **Option parameters in Hz or seconds are rescaled** over the channel's span, as scalar
     channels are. The colour macros' rule (Hz or bpm: no speed, reported) is unchanged.
   - **Scalars with no range** (a speed channel of reverse speeds only) are held as control,
     reported ("no range drives effectRate"), instead of giving a profile the validator
     refuses. This applies to every scalar; the sweep found no old channel affected.
   - The worked examples hold. Q3 is reported ("taken as their colorMacroRate"), because
     OFL does not say whose speed it is.
   - The TupperDMX transcriptions are at revision 2. `tupper-demo.show` took them with
     `profile update` (no backup written), so its ids and other content are unchanged.
   - The plan's "Cameo Pico" macro channels are Fun Generation's Pico family (`Program`
     channels with a `Maintenance` "Reset").
   - A sweep against step 2 (636 OFL fixtures at `2d74941`): 567 import and 69 fail, before
     and after; no mode lost; no driven channel changes attribute; no uncontrolled byte of a
     driven channel moves. Control channels 6,937 → 5,916. Two `colorEffect` channels lose
     their maintenance ranges as options (Phocea Box LEDs, Mega-Lite Zoom 360). Step 7
     redoes it with the GDTF import.
4. **GDTF** (§5.4). Verify with synthetic descriptions in `test_gdtf.py`:
   - `Effects1` with "No Effect" and named sets, and with strobe functions;
   - `Effects1Rate` at 0…1 and at 1…10 Hz, and `Effects1Fade` at 0.1…25.5;
   - `Effects1Adjust1` (driven) and `Effects1Adjust2` (held);
   - an `Effects1Pos` channel with `Effects1PosRotate` (Q6);
   - `EffectsSync` at 0…255;
   - a `Control1` channel with `Effects1` and reset functions, which stays `control`;
   - `Effects2` (Q4) and `Effects2Rate` (held).
5. **Importer version 3.** Verify as in the colour macro plan's step 5:
   - the same file and the same busk give the same revision, and version 3 gives a new one;
   - with an old embedded copy, `list profiles` shows the library's revision, and `profile
     update` takes it.
6. **Docs and changelog.**
   - `profiles.md`: the import bullets, options with parameters, scalar defaults from the
     channel, maintenance ranges;
   - `console.md`: "fixture effects" next to busk effects, and a `set effect fuego` example;
   - `safety.md`: `safety strobe` caps `strobeRate` only, so a fixture's own strobing
     programs are not capped;
   - the importers' module docstrings, written in steps 3–4;
   - CHANGELOG: Added (the attributes); Changed (imports, revisions, macro channels without
     maintenance options, and `colorMacroRate`'s default with Q2(a)).
7. **Real-file sweep.** Import every OFL fixture (636) and GDTF description (5,733) at step 2's
   commit, before either importer changes, and at `HEAD`. Verify:
   - no import that succeeded now fails, and no mode is lost;
   - no channel busk drove changes attribute, and only colour macros lose maintenance options;
   - in each mode's uncontrolled frame, only the bytes of former control channels change. Each
     change is listed with its two values;
   - control channels drop by about §2's counts;
   - by hand, against their charts:
     - the three TupperDMX fixtures;
     - Robe BMFL Blade: `Effects1`, `Effects1Rate`, and `Effects1Fade` in seconds;
     - Martin VDO Dotron: `EffectsSync`;
     - Robe MegaPointe: `Effects1PosRotate`.

   Write the numbers in step 7's Done note.
8. **The user's checks.**
   - In the TupperDMX simulator: the LED bar's animations and speed, the blinder's auto
     program, and the Wild Wash 6Ch's dimmer patterns and sound control.
   - Real GDTF 1.2 files with `Effects(n)Adjust(m)`, if the user has any from GDTF Share.

## 7. Compatibility

- **Old shows** open unchanged: their embedded profiles keep `control` channels. With
  `IMPORT_VERSION` 3, `list profiles` offers each imported profile's new revision.
- **Shows that use the new attributes** need this busk.
- **Re-imported profiles** change: channels that were `control` become driven.
  - With Q2(a), an unprogrammed fixture's scalars output what they output today.
  - An option outputs the centre of its range, not the edge `defaultDmx`. The LED bar's
    uncontrolled animation is DMX 1 instead of 0, and the blinder's mode DMX 4 instead of 0.
- **Colour macros** (Q5(a)): the 4 Cameo Pico channels lose their `reset` option.

## 8. Risks

- **`Effects(n)Rate`'s unit.** The 1.2 spec says Frequency, but most files give 0…1. A real
  1.2 file in Hz is rescaled: `effectRate` stays 0…1, and the Hz are lost.
- **The owner of an OFL speed** (Q3) is a guess from the mode. In the 90 modes with both an
  effect channel and a colour macro, it is `effectRate`.
- **Unreachable ranges:** reverse speeds, and a second slow…fast range for another mode (the
  Wild Wash's "Gradual transient").
- **Fixture strobing is not capped.** Programs such as the LED bar's "Strobo" flash at the
  fixture's own rate, and `safety strobe` caps only `strobeRate`, as with colour effects.
  Step 6 documents it.
- **Function options** make sound-active and auto programs selectable. A typo is still
  refused, because the option must exist.
- **Generated ids** follow the importers' camelCase rule (`loadingCortaArriba`,
  `lEDsOffBlackout`).
- **`effect` beside busk effects** (Q1(a)): the docs must keep "fixture effect" and "busk
  effect" apart.

## 9. After this

- **Effect direction.** The LED bar's "Forward"/"Reverse" is an OFL `Generic` channel. OFL has
  no type for it and GDTF no attribute, so a rule would have to guess from names.
- **Indexed angles** of effect, gobo and prism wheels: a channel driven by two slots, its index
  used while rotation is stopped (Q6).
- **The TupperDMX sidecar scripts** (`ledbar.busk` …) could send the animations as `set effect
  …`. Their generator was in a session scratchpad and is gone.
- **Numbered rates and adjusts** (`Effects2Rate`, `Effects(n)Adjust(m ≥ 2)`), if real 1.2 files
  use them.
