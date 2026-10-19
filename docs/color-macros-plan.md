# Colour macros and colour effects: implementation plan

> Source: the user's request of 2026-10-19. Import OFL `ColorPreset` and GDTF `ColorMacro(n)`,
> `ColorMacro(n)Rate` and `ColorEffects(n)`, and give the engine what it needs so that these
> channels, in any OFL or GDTF file, are programmable in busk. Today both importers turn them
> into `control` channels held at their default. The user took every recommendation of §3.1
> on 2026-10-19: Q1(a), Q2(a), Q3(a), Q4(a), Q5(a), Q6(a), marked *(user)*. The calls of
> §3.2 are the plan's, open to veto.

## 1. Scope

**In:**
- three new attributes: `colorMacro`, `colorMacroRate` and `colorEffect`;
- the profile rule for their options, plus the validator and slot-default changes they need;
- the OFL and GDTF mappings;
- tests at every level, a sweep over real fixture libraries, and the docs.

**Out** (§9): deriving a macro from `color` on fixtures with no colour mixing (unless §3.1 Q1
picks it); generic fixture programs (OFL `Effect`/`EffectSpeed` on non-colour channels, GDTF
`Effects(n)`), such as the TupperDMX LED bar's animations; stepping discrete attributes with
busk effects.

## 2. What the files contain

Two surveys, run on 2026-10-19 (scripts in the session scratchpad, not in the repo):

**OFL**: the repository's `fixtures/` at `db1234f` (2026-10-19), 636 fixtures.
- 282 fixtures (44 %) have a `ColorPreset` channel: 336 channels and 7,990 preset ranges.
- 603 modes use one. About a third of them (211) have no RGB channels, so the macro is
  their only colour control.
- **"Off" range**:
  - 249 channels start with `NoFunction`, and 2 more have one elsewhere;
  - 24 start with a black preset ("Off", "Black", "Blackout");
  - 22 start with a preset that has no colour ("None", "No effect");
  - 39 have no off range at all: their first range is a colour, usually "Red".
- **`defaultValue`**: it falls in `NoFunction` on 236 channels and in a preset on 65.
- **Preset shapes**:
  - 5,012 have one colour;
  - 761 have two or three colours (split colours);
  - 224 are sweeps (`colorsStart`/`colorsEnd`, "Red -> Yellow");
  - 38 are colour temperatures;
  - 1,955 are a name only;
  - 36 have no name, and 51 channels repeat a name (the Wild Wash has "Red" twice).
- **Effects on the same channel**: 711 `Effect` ranges share a preset channel. 178 of them
  have a speed range (slow…fast), and 245 are `ColorJump`/`ColorFade`.
- **Colour effects without presets**: 122 more channels hold `ColorJump`/`ColorFade`
  effects and no `ColorPreset`. That is OFL's counterpart of GDTF `ColorEffects`.
- 171 of the 603 modes also have an `EffectSpeed` channel. OFL does not say which channel
  a speed controls: on the Wild Wash 5Ch it is the dimmer pattern's speed, not the macro's.
- 13 preset channels are per-pixel templates.

**GDTF**: [heliostate/OpenGDTFLibrary](https://github.com/heliostate/OpenGDTFLibrary),
5,733 descriptions (GDTF 1.0 and 1.1, last pushed in 2021).
- 150 fixture types use `ColorMacro1` (593 functions) and 21 use `ColorEffects(n)`
  (86 functions).
- n > 1 is rare: one `ColorMacro2`, and `ColorEffects2`/`3` in one Prolights family.
- **No file uses `ColorMacro(n)Rate`.** It is in the 1.2 spec only, with no physical unit:
  "Controls the time between Color Macro steps". In these files a macro's speed is
  `Effects1Rate` or channel sets such as "Max Cycle"/"Min Cycle".
- 589 of 593 macro functions carry named channel sets. 191 link a virtual wheel, and every
  slot of those wheels has a colour.
- **Off range**: 472 of 503 macro channels start with a set named "No function", "Safe",
  "NoFunction", "Open", "Normal", "None" or "Off". About 25 more use "No macro",
  "No Fonction" or "No Color macro".
- 56 channels are colour wheels (`Color1`) with macro functions inside. They stay
  `colorWheel`, and their macro ranges are never output.
- 245 of the 512 modes with a macro or colour effect have no RGB.

**Worked example**: the TupperDMX simulator's Wild Wash Pro 648 RGBW, modes 2Ch-1, 5Ch and
6Ch. Its "Color Macro" channel is:
- 0–5 "LEDs off (blackout)", a black preset (no `NoFunction`);
- 15 more presets;
- "Red" again at 126–128;
- "Colour change" at 129–192 and "Gradual colour change" at 193–255, each slow→fast.

Its default is 0. It is the only colour control in those modes. Import today reports
`Color Macro: no busk attribute (ColorPreset, Effect); held at DMX 0`.

## 3. Decisions

### 3.1 Answered by the user (2026-10-19): every recommendation, (a)

1. **What an uncontrolled `colorMacro`/`colorEffect` outputs.**
   - **(a) The fixture's own default *(user)*.** The option whose DMX range holds the
     channel's `defaultDmx`, else the first option. It is a registry sentinel,
     `"channelDefault"`, resolved per channel like zoom's `"profileMidpoint"`.
     - Every channel with an option is supported.
     - An unprogrammed fixture outputs what it outputs today.
     - A macro-only fixture whose default is a black preset stays dark until a macro is
       set, as today.
   - **(b) Strict `off`.** The registry default is `{"slot": "off"}`, and a channel must
     offer an `off` (a no-function range), as the shutter must offer `open`. About 25 % of
     OFL macro channels and 6 % of GDTF ones have none and stay `control`. The 24 OFL black
     presets named "Off" would be taken for "no macro".
   - **(c) (a), plus colour follows on macro-only elements.** On an element with no colour
     mixing, an uncontrolled `colorMacro` takes the preset nearest the `color` slot's
     colour (white by default). It closes `docs/history.md`'s open "colour → colour wheel"
     item for macros (not for wheels) and is a separate step of its own (§6, step 2b).
2. **The OFL side.**
   - **(a) Parity with GDTF *(user)*.** `Effect` ranges on a preset channel become
     options with their speed (§5.3). Channels of `ColorJump`/`ColorFade` effects without
     presets (122) become `colorEffect`, as GDTF `ColorEffects(n)` does.
   - **(b) `ColorPreset` only.** Effect ranges on a preset channel are options without a
     speed, and colour-effect channels stay `control`.
3. **`colorMacroRate`'s unit.**
   - **(a) Normalised *(user)*.** 0 slowest, 1 fastest, default 0.5. OFL gives speeds
     as slow…fast or percentages, which map exactly, and GDTF gives the rate no unit.
   - **(b) Hz.** Speeds given as keywords become estimates, as strobe speeds are now
     (1–20 Hz).
4. **Numbered instances** (`ColorMacro2`, a second preset channel on one element).
   - **(a) The first per element only *(user)*.** Later ones stay `control` and are
     reported, as `Color2` and `Gobo3` are today. The data above shows them rare.
   - **(b) Numbered attributes**: `colorMacro2`, `colorEffect2`, ….
5. **Importer version in the revision.** A profile's revision hashes the *source* file, so
   a show that embeds a v0.1.0 import of a fixture keeps it. `profile update` refuses: "is
   already at the library's revision". That applies here and to the last commit's fog and
   position-speed changes.
   - **(a) Mix an importer version into the hash *(user)*.** Every imported profile
     gets a new revision once. `list profiles` shows it, and `profile update` takes it, as
     §17 wants.
   - **(b) Leave revisions as they are.** Old shows keep their `control` channels.
6. **Option names at the prompt.**
   - **(a) Tab completion for discrete options *(user)*.** `set <discrete> ` completes
     the options of the selected targets (§5.5, step 6). Without it, the 17 macro names of
     a fixture are only in its profile file.
   - **(b) No completion.** Names are looked up in the profile file.

### 3.2 The plan's calls (open to veto)

- **Names.** `colorMacro`, `colorMacroRate` and `colorEffect`, after GDTF. All three are in
  the `color` family, so `record … only color` and colour presets carry them. They follow
  `cto` in the registry: slots of fixtures without these channels do not move.
- **One rate.** `colorMacroRate` is shared by macro programs and colour effects. GDTF
  defines no `ColorEffects(n)Rate`. On an element, a rate channel and an option's speed
  then read the same slot.
- **Every range is an option.** On a `colorMacro` or `colorEffect` channel, every range is
  a selectable option, sound-active and auto programs included, first id winning. That
  differs from wheels, whose other functions are never output. An effect range with a speed
  is a function option with `param: colorMacroRate`, the mechanism of the shutter's strobe.
- **Presets as wheel slots.** OFL presets become slots of a virtual wheel per channel, so
  their colours are kept. The wheel has `kind: "color"` and id `macro1`, `macro2`, ….
  - A preset's colour is the mean of its `colors` in linear RGB, as for colour-wheel slots.
  - Sweeps and colour temperatures get no colour.
  - A preset that repeats an earlier one's name and colour reuses its slot.
  - GDTF macros keep their linked wheel. Unlinked channel sets become function options
    named after the set.
- **`off`.** A no-function range is named `off`, so `set colorMacro off` works across
  fixtures. That means OFL `NoFunction` and GDTF `NoFeature`, or a set whose name says off,
  no function, safe, none, open or no macro.
- **Highlight is unchanged.** These channels take their `highlightDmx` (GDTF `Highlight`,
  OFL `highlightValue`), as other channels do. Highlight forces nothing else on them.
- **No `schemaVersion` bump.** The attributes are additions, so the CHANGELOG lists them
  under Added. busk 0.1.0 cannot open a show that uses them; forward compatibility was
  never promised.
- **Unchanged neighbours.** OFL `EffectSpeed` channels stay `control`: OFL does not say
  which channel they speed up. GDTF colour wheels with macro functions inside stay
  `colorWheel`.

## 4. Files

| File | Change |
|---|---|
| `src/busk/model/attributes.py` | three definitions; `"channelDefault"` in `AttributeDefinition.default` |
| `src/busk/model/profile.py` | `MACRO_ATTRIBUTES`; `option_capabilities` takes their slot and function capabilities |
| `src/busk/model/validate.py` | option and default checks for them |
| `src/busk/compiler/slots.py` | `_default_value` resolves `"channelDefault"` (it gets the channel) |
| `src/busk/importers/ofl.py` | `ColorPreset`, colour `Effect`, macro wheels, speeds, `_default_option` |
| `src/busk/importers/gdtf.py` | `ColorMacro1`, `ColorMacro1Rate`, `ColorEffects1`, sets as options |
| `src/busk/importers/__init__.py` | `IMPORT_VERSION` (Q5) |
| `src/busk/console/parser.py` | discrete options completed from the selection (Q6) |
| `tests/…` | `test_attributes`, `test_profile`/`test_validate`, `test_slots`, `test_channels`, `test_ofl`, `test_gdtf`, an end-to-end test |
| `docs/…` | `profiles.md`, `console.md`, `busking-console-architecture-python.md` §5.3, `history.md`, `CHANGELOG.md` |

No change is expected in the resolver, the converters, the engine process or cue tracking.
They are generic over the registry and over options with parameters. Step 2 proves it.

## 5. Design

### 5.1 Registry

| Attribute | Family | Kind | Unit | Merge | Fade | Default |
|---|---|---|---|---|---|---|
| `colorMacro` | color | discrete | — | LTP | snap | the channel's default option (Q1) |
| `colorMacroRate` | color | scalar | normalised, 1 fastest (Q3) | LTP | fade | 0.5 |
| `colorEffect` | color | discrete | — | LTP | snap | the channel's default option (Q1) |

### 5.2 Options and defaults

`option_capabilities(channel)` gives a `colorMacro` or `colorEffect` channel one option per
slot capability (its slot id) and per function capability (its `fn`). Options keep DMX
order, and the first capability with an id wins. The validator asks such a channel for at
least one option. With Q1(a) it drops the "must offer the default" rule for them.

`slots._default_value` resolves `"channelDefault"` to the option whose range holds
`defaultDmx`, else the first option. Those are the only four readers of
`AttributeDefinition.default`: slots, validate, and the two importers' `_default_option`.

### 5.3 OFL

- **Attribute.** `ColorPreset` → `colorMacro`. With Q2(a), an `Effect` with `effectPreset`
  `ColorJump` or `ColorFade` → `colorEffect` when the channel has no preset. The channel's
  attribute is still that of its first capability busk can drive, so 4 channels that start
  with a strobe stay `shutter`.
- **Ranges on a `colorMacro` or `colorEffect` channel**, in DMX order:
  - `ColorPreset` → a slot of the channel's macro wheel;
  - `NoFunction` → function `off`;
  - `Effect` → function `_fn(cap)` (`colourChange`, `colorJump` …). It takes
    `param: {colorMacroRate, (start, end)}` when it has a speed: `slow` 0, `fast` 1,
    `n%` n/100, `stop` 0. A speed in Hz or bpm is rescaled over the channel's span and
    reported.
  - anything else → function `_fn(cap)`.
- **Template channels.** A per-pixel template channel gets one wheel, shared by its pixels.
- **Wild Wash, 5Ch.**
  - The options are `lEDsOffBlackout`, `red` … `coldWhite`, `colourChange` and
    `gradualColourChange`. Ids follow the importers' existing camelCase rule.
  - Uncontrolled: DMX 2, black (today it is held at 0).
  - `set colorMacro red` outputs DMX 9.
  - `set colorMacro colourChange` with `set colorMacroRate 0.5` outputs DMX 160.

### 5.4 GDTF

- **Attributes.** `ATTRIBUTES` gains `ColorMacro1` → `colorMacro`, `ColorMacro1Rate` →
  `colorMacroRate` and `ColorEffects1` → `colorEffect`. `WHEEL_KINDS` gains the two
  discrete ones as `color`.
- **A `colorMacro` or `colorEffect` channel**, function by function:
  - `NoFeature` → `off`;
  - a function linked to a wheel → slots, through `_slots`;
  - other functions → one function option per channel set, named after the set (`off` for
    the off names of §3.2), or one option named after a function without sets.
- **`ColorMacro1Rate`** is a range channel. It joins `_NORMALISED`: physical values outside
  0…1 are rescaled and reported.
  - **Risk**: the direction is a guess. The spec gives no unit, and no real file has it;
    busk reads the larger physical value as faster.
- **n ≥ 2** stays `control`, reported (Q4).

### 5.5 Console (Q6)

`set <discrete> ` passes the names of the selected targets' options to `take`, so Tab
lists them and `?` shows them. Completion reads them through `parser.expected()`, as the
prompt's other names. That covers wheels and the shutter too.

## 6. Steps

Baseline at `11c2b37`: 3347 passed, 1 skipped, 13 deselected. Each step ends with the suite
green, `ruff check`, `ruff format --check` and `mypy src`. Use
`uv run python -m pytest` (the venv's console scripts have a stale shebang). Each step is one
commit.

1. **Registry, options, validator, slot default** (§5.1–5.2).
   Verify: `test_attributes` rows and the count (20 → 23); option rules for slot and
   function capabilities with first-wins ids; the validator's messages; `"channelDefault"`
   resolving to the option holding `defaultDmx` and to the first option otherwise.

   **Done** (2026-10-19): 3359 passed.
   - `profile.channel_default_option` and the private `_option_id` hold the rule shared by
     `option_capabilities`. The default is the option of *any* capability holding
     `defaultDmx`, so a default in a repeated range ("red" twice) still finds its option.
   - `ofl._default_option` (also used by GDTF) returns `None` for `"channelDefault"`.
   - The spec's §5.3 table and `console.md`'s attribute table got their three rows now,
     since `test_attributes` says it matches the spec.
2. **End to end, with a hand-written profile.** The profile has a macro channel (`off`,
   coloured slots, an effect with a rate parameter) and a rate channel. No production code
   is expected to change.
   Verify through `OfflineShow`/`DmxFrame`:
   - `set`, `record cue`, `go`: DMX bytes per option, and the parameter mapped through its
     range;
   - release back to the default option;
   - snap at the start of a fade;
   - `park`;
   - a colour preset with `colorMacro red` applied to two fixture types;
   - `highlight` writing `highlightDmx`;
   - the vectorised converter agreeing with the reference one;
   - the engine process's slot view.

   **2b (only with Q1(c)):** colour-follows-macro on elements without colour mixing,
   nearest preset by distance in linear RGB.

   **Done** (2026-10-19): 3369 passed. No production code changed.
   - `builders.macro_rig()` is the rig. `tests/test_color_macros.py` has eight cases with
     hand-computed DMX, and `test_convert_properties` runs the differential and safety
     properties on the rig too.
   - The engine process's slot view is not tested separately: `engine_view` only drops
     `slots` and `byKey`.
   - Fixed with this step: step 1's `test_slots.py` import of `slot` shadowed a loop
     variable (ruff F402).
3. **OFL** (§5.3). Verify in `test_ofl.py`:
   - a Wild Wash-like channel: no off range, a black first preset, a repeated "Red", effects
     with speed;
   - a `NoFunction`-first channel, which gives `off`;
   - a per-pixel template;
   - a second preset channel on one element (held);
   - a `ColorJump` channel (`colorEffect`);
   - sweeps, colour temperatures and unnamed presets.

   The TupperDMX examples are unchanged: their files have no `ColorPreset`.
4. **GDTF** (§5.4). Verify with synthetic descriptions in `test_gdtf.py`:
   - named sets with a "No function" set;
   - a wheel-linked macro with coloured slots;
   - `ColorEffects1`;
   - `ColorMacro1Rate` at 0…1 and at 0…100;
   - `ColorMacro2` (held);
   - a `Color1` channel with macro functions (stays `colorWheel`).
5. **Importer version** (Q5): `IMPORT_VERSION = 2`, mixed into both importers' revision
   digest. Verify: the same file and the same busk give the same revision, and a version
   bump gives a new one. With an old embedded copy, `list profiles` shows the library's
   revision and `profile update` takes it.
6. **Console** (Q6): completion of discrete options. Verify in `test_console_prompt.py`,
   including `?`.
7. **Docs and changelog.**
   - `profiles.md`: the import bullets, and how options and the default become DMX;
   - `console.md`: the attribute table and a `set colorMacro red` example;
   - the spec's §5.3 table;
   - `history.md`: the colour → wheel item now names macro-only fixtures too;
   - CHANGELOG: Added (attributes, completion) and Changed (imports, revisions).
8. **Real-file sweep.** Import every OFL fixture (636) and GDTF description (5,733) at
   `HEAD~` and at `HEAD`. Verify:
   - no import that succeeded now fails;
   - control channels drop by about the number of macro channels;
   - three fixtures checked by hand, DMX against their charts.

   Write the numbers in step 8's Done note.
9. **The user's checks.** A fixture in a macro mode in the TupperDMX simulator (the Wild
   Wash in 5Ch). Real GDTF 1.2 files with `ColorMacro(n)Rate`, if the user has any from
   GDTF Share.

## 7. Compatibility

- **Old shows** open unchanged: their embedded profiles keep `control` channels. With
  Q5(a), `list profiles` offers the new revision for each imported profile.
- **Shows that use the new attributes** need this busk, not 0.1.0.
- **Re-imported profiles** change: channels that were `control` become driven, and with
  Q1(a) an unprogrammed fixture's output stays the same. The one change is that an option
  outputs the centre of its range, not the edge `defaultDmx` (DMX 2 instead of 0 on the
  Wild Wash).

## 8. Risks

- **`ColorMacro(n)Rate`'s direction** is unverified (§5.4).
- **Function options** make sound-active and auto programs on these channels selectable.
  A typo is still refused, because the option must exist.
- **Fast colour jumps flicker**, and `safety strobe` caps only `strobeRate`. Capping
  `colorMacroRate` needs a unit in Hz (Q3(b)).
- **Generated ids are ugly** (`lEDsOffBlackout`). The camelCase rule is shared with wheel
  slots, and changing it would rename slots in existing imports. Left as it is.

## 9. After this

- **Colour → macro and wheel.** Derive a macro or wheel slot from `color` on fixtures with
  no colour mixing (`history.md`'s open item), if Q1(c) is not taken now.
- **Generic fixture programs.** A discrete attribute for OFL `Effect` and GDTF `Effects(n)`
  with `Effects(n)Rate`, on the same machinery as `colorEffect`. It would make the TupperDMX
  LED bar's animations, the blinder's auto programs and the Wild Wash's dimmer patterns
  programmable.
- **`EffectSpeed` linking**, if OFL ever ties a speed to its channel.
