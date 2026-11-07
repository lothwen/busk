# TUI presets: implementation plan

> Source: the user's request of 2026-11-01. Take the Presets table of
> `docs/dev/tui/operations-report.md` and give every operation a control in the TUI. Today
> those operations are "prompt" or "pre-fill". Add must work from controls alone: the TUI has to
> set the values a preset records, so a colour preset needs a way to pick a colour on screen.
> Written at `f19c4ec`. The user answered the questions in §9 on 2026-11-01: (a) to all five.
> The calls in §4 are the plan's, and the user may veto them.

The TUI rules of `docs/dev/tui/implementation-plan.md` §1 still apply:
- no change to `src/busk/` or to the engine's tests;
- only `bridge.py` imports `busk`, and only its public names;
- every action is a console line sent through `LiveShow.execute()`;
- an engine gap is written down. The TUI never works around one.

## 1. Scope

The report's Presets rows, and what this plan makes of each:

| Operation | busk line | Today | After this plan |
|---|---|---|---|
| Show | `LiveShow.show` | control (F6 tiles) | control, plus what a preset holds and which cues use it (§5.3) |
| Add | `record preset <pool> N [global\|profile\|target] ["name"]` | pre-fill; an empty pool's first preset by prompt only | control: pool, number, name and scope, the selection, and editors for every value the pool records, including a colour picker (§5.4–5.6) |
| Delete | `delete preset <pool> N` | prompt | control, after a question; inert while cues use the preset, with their numbers shown (§5.3) |
| Change its values | `record preset <pool> N merge\|replace\|remove` | prompt | control, with the same editors, plus `[load]` and `[its fixtures]` (§5.5) |
| Rename | `rename preset <pool> N "…"` | prompt | control: a name dialog (§5.3) |
| Renumber | `preset <pool> N number M` | prompt | control: a number dialog that offers only free numbers (§5.3) |

**In:** F6, its new PRESET panel and the widgets that panel needs: a colour picker, option
chips for discrete attributes (gobos, prisms, wheels, shutters, fixture effects) and bars for
the scalars F2 lacks. Also the model and bridge additions those need, the command builders,
tests, the guide, and updates to the report and the TUI plan.

**Out** (§8): F2's own COLOR panel, which keeps its `[set color…]` pre-fill. Copying or moving
a preset, which busk has no line for. Deletes that cascade (report item 6). Fixing the engine
findings of §7.

## 2. What busk does (checked on `OfflineShow`, 2026-11-01)

Each fact below was checked by running the line on `examples/club-night.busk` or on a copy of
`examples/tupperdmx/tupper-demo.show`:

- **Recording reads the programmer, not the selection.** `record preset <pool> N` records every
  value the programmer holds in the pool's families, for every fixture that has one. The
  families per pool:
  - `color`: color
  - `position`: position
  - `beam`: beam and shutter
  - `intensity`: intensity
  - `focus`: focus
  - `all`: every family except `control`

  With nothing to record it fails with "the programmer has no color values". It refuses a
  number that is already taken unless the line says `merge` or `replace` ("… exists: add merge
  or replace"). It refuses `merge`, `replace` and `remove` on a number that has no preset ("no
  preset color 9"). The scope keyword, the merge keyword and the name can come in any order.
- **Default scopes** (`parser._DEFAULT_SCOPE`): `color` and `intensity` record `global`;
  `beam` and `focus` record `profile`; `position` and `all` record `target`. Where the values
  differ, a scope falls back to a narrower one, and the reply says so ("color: 2 target values
  (values differ)").
- **Colour.** `set color r g b` takes levels from 0 to 1 or percentages. Without `w`, `a` or
  `uv`, busk derives those emitters itself (a "derive" lane). `w x` sets white explicitly.
  `set color.<c>` lines work only once the programmer holds a colour (GAP-05). That is why the
  colour picker has to send a whole colour first.
- **Discrete attributes.** `expected("set gobo1 ")` lists the options the *selection* offers,
  after the keywords `spread` and `preset`. On the TupperDMX heads that is `open breakup dots
  lines star spiral triangles closed`. `set prism ` gives `off prism3`. `set effect ` on the
  blinders gives `off autoProgram soundActive`. A selection without the attribute is refused:
  "no selected target takes this colorWheel".
- **Rename and renumber.** `rename preset color 7 "Scarlet"` works.
  `preset color 7 number 9` works. `preset color 7 number 2` is refused while 2 is taken, with a
  validation message: "Duplicate number 2 in the 'color' pool (first used at presets[1])".
- **Delete.** `delete preset color 2` is refused while a cue uses the preset. The error names
  document paths, not cue numbers: `cueLists[3].cues[0].entries[0].value.presetId: Unknown
  preset 'pr-…'`. A preset that only the programmer references *is* deleted, and the
  programmer then shows `preset pr-… (gone)`. `confirmation()` asks nothing before a delete.
  `undo` brings the preset back.
- **Both rigs.** Every coloured fixture in them takes `color` (RGB, with W on the washes and
  the PARs); none has a `colorWheel`. The club spot has `gobo1`, `shutter` and `zoom`. The
  TupperDMX head has `gobo1`, `gobo1Rotation`, `prism`, `shutter` and `zoom`. The TupperDMX
  blinders and bar have `effect` and `effectRate`. F2 has controls for none of the discrete
  attributes and none of the rotations.

## 3. The design in one picture

The mockup is at 150 columns, with edit mode on and a new colour preset open:

```
 applies to 201 thru 204 (4) · click a tile to edit it                  [edit ●]
┌ color ──────────────────────────────┐ ┌ PRESET · new color 5 ──────────────────────┐
│ 1  ████   2  ████   3  ████         │ │ number [−] 5 [+] [number…]  [name: Color 5…]│
│ Blue      Red       Green           │ │ scope  [global] [profile] [target]         │
│ 4  ████   + record                  │ │                                            │
│ Amber     as 5                      │ │ SELECTION 201 thru 204 (4)                 │
└─────────────────────────────────────┘ │ [Heads] [Washes] [Bar] [All] [none]        │
┌ position ───────────────────────────┐ │                                            │
│ 1 -30°/40°  2 15°/10°  + record     │ │ COLOR                                      │
│ Audience    Centre     as 3         │ │ ██████████████████████████████████████████ │
└─────────────────────────────────────┘ │ ██████████████████████████████████████████ │
┌ beam ───────────────────────────────┐ │ ██ hue →, saturation ↓ (5 rows) ██████████ │
│ + record                            │ │ ██████████████████████████████████████████ │
│ as 1                                │ │ ██████████████████████████████████████████ │
└─────────────────────────────────────┘ │ [red] [orange] [amber] [yellow] [lime] …   │
                                        │ ████ 1 0.25 0 · #ff4000                    │
                                        │ color.r [−] ━━━━━━━━━━━━━━━━━━━ [+] 100%   │
                                        │ color.g [−] ━━━━━               [+]  25%   │
                                        │ color.b [−]                     [+]   0%   │
                                        │ color.w [−]                     [+]   0%   │
                                        │                                            │
                                        │ RECORDS color on 201 thru 204 (4)          │
                                        │ [record] [clear] [blind on] [done]         │
                                        └────────────────────────────────────────────┘
```

- **F6 gains an edit mode** (Q1, Q2). The header's `[edit]` toggle turns it on, and so does a
  `+ record` tile. While it is on, a tile click chooses that preset for the PRESET panel
  instead of applying it. `[done]` turns edit mode off. While it is off, F6 is what it is
  today: a click applies.
- **The PRESET panel works through the programmer**, as busk does. Its editors send `set`
  lines, so the look shows on stage unless `[blind on]` is lit. Its `[record]`, `[merge]`,
  `[replace]` and `[remove]` buttons send `record preset` lines. Every line is echoed
  `ui> …` in the log, and every refusal shows there too, as for every other control.
- **A name or a number** is typed in a small modal dialog (Enter: OK, Esc: cancel). Modal
  dialogs already take the keyboard while they are open (`widgets/dialogs.py`), so the prompt
  still has the keyboard everywhere else.

## 4. Calls the user may veto

These follow the project's earlier calls and the "engine first" rule. Each is open to veto:

1. **Every pool the rig can record into shows,** with at least its `+ record` tile. A pool also
   shows when it holds presets. A pool the rig can record into is one where some profile in
   the show takes an attribute in that pool's families. This fixes the report's "the first beam
   or focus preset is prompt only". On the club rig, focus does not show: the spot has no
   focus channel, so busk would refuse the record anyway.
2. **`+ record` opens the panel** in record mode. It no longer pre-fills the prompt. The prompt
   still takes `record preset …` lines as before.
3. **Default scopes are a small table in the TUI** (`DEFAULT_SCOPE`), as command words are.
   The scope buttons light the pool's default, and the record line always names its scope,
   so the echo says what was recorded. The contract test records without a keyword and checks
   that busk stored the same scope as the table says.
4. **Options come from busk's own completion.** On each selection change, the bridge reads
   `expected("set <attribute> ")` for each discrete attribute the rig takes, and drops the
   keywords `spread` and `preset`. The options reach the page as `ProgrammerModel.options`.
   This uses busk's rule for which options exist, maintenance functions included, rather than
   a copy of it read from the profiles. It works for the Phase 4 profile reading too.
5. **The panel shows what will be recorded** (RECORDS). This is the programmer's values in the
   pool's families, per attribute, with their fixtures compressed (`color on 201 thru 204
   (4)`). When some of those fixtures are not selected, it says so (`2 not selected`), because
   busk records them too. With nothing to record, `[record]` is inert and the line says "set a
   value above".
6. **Delete is inert while cues use the preset.** The panel names those cues instead of the
   engine's document paths. The TUI reads this from
   the document. On the club show, Red reads "used by cue 4/1, 10/1–10/4, 15/1, 18/2". When
   the programmer references the preset, the question before the delete says so.
7. **Numbers.** A new preset starts at the pool's last number plus one, as `+ record` does
   today. `[−]` and `[+]` step over free numbers only, at least 1, and send nothing.
   `[number…]` opens the dialog, which lists the numbers already taken and refuses them. For an
   existing preset, only `[number…]` renumbers, so each renumber is one line and one undo step.
8. **Names.** The dialog starts with the preset's name, or empty for a new preset (busk then
   names it `Color 5`). It refuses a double quote (`commands.quoted`: busk has no escape for
   one) and, when renaming, an empty name.
9. **`[its fixtures]`** selects the fixtures the preset gives a value to: a `target` value's
   fixture, every fixture of a `profile` value's profile, and for a `global` value every fixture
   whose profile takes the attribute. Whole fixtures are selected, with `sel fixture a, fixture
   b`.
10. **`[load]` is `preset <pool> N`** on the selection. The programmer then holds references,
    the editors show the preset's values, and their steps act on them (`set … by` counts a
    reference with the preset's value). `record … merge` or `replace` resolves the references
    to values.
11. **The colour field** (Q4) uses one cell per pick: Textual reports clicks per cell, not per
    half-cell. Its columns run through the hue (360° over the field's width) and its five rows
    through the saturation (0.2 to 1, palest at the top), all at full value. It sends `set
    color r g b` to two decimals and leaves white to busk. A drag sends at most every 0.1 s
    and logs the last line, as an encoder bar does. The cell nearest the programmer's colour is
    marked when that colour is at full value. The field is mouse only. From the keyboard, the
    named chips and the component rows reach every colour.
12. **The named chips** are a constant list in the TUI: red, orange, amber, yellow, lime, green,
    cyan, sky, blue, violet, magenta, pink, white, warm (`1 0.75 0.45`, the club's Warm) and
    cool (`0.75 0.85 1`). The club's own presets use `0 0 1`, `1 0 0`, `0 1 0` and `1 0.5 0`,
    and the chips give the same values for blue, red, green and amber.
13. **Rows follow the rig, as on F2** (changed on 2026-11-05: see "After the plan" in §6). A row
    shows when some profile of the show takes its attribute, and acts only where the selection
    does (F2's `Selected` rule). The panel's layout therefore does not jump when the selection
    changes.
14. **F6 reads the output only while the panel is open** (`Page.watches`). The encoders show
    the output's values dim, as on F2. The perf test gets an "F6 editing" case.
15. **Layout.** The panel is 52 cells wide, to the right of the pools, at 100 columns or more.
    Below 100 columns it goes under the pools (spec §3), and the page scrolls. The panel
    scrolls on its own when it is taller than the page.
16. **The pane cursor** stops on the header toggle, the tiles (apply, or choose in edit mode)
    and every control in the panel, in reading order.

## 5. Design

### 5.1 Model and bridge

- `PresetEntry(scope, where, attribute, value)` gives each stored value:
  - `scope`: `global`, `profile` or `target`;
  - `where`: the profile's name, or `(fixture, element)`;
  - `value`: a `Value`, as `HeldValue` has.

  `PresetInfo.entries` holds them in stored order, and `PresetInfo.used_by` holds the cues
  whose entries reference the preset (`"4/1"`), in list and cue order.
- `ProgrammerModel.options` holds, for each discrete attribute the rig takes, the options the
  selection offers (§4 call 4). It is read again only when the selection changes. The step
  checks that `expected()` is safe on the bridge's reading thread (GAP-12's concurrency notes;
  until now only the UI thread called it). If it is not, the read moves to the UI thread on
  `ProgrammerChanged`.
- `profile_info` gains `color.a` and `color.uv`, read like `color.w` from an amber or UV
  emitter. It also gains ranges for the rotations (`gobo1Rotation`, `gobo2Rotation`,
  `prismRotation`, `effectRotation`): the channels' capability span, else ±360 °/s.

### 5.2 Tables and lines

- `attributes.py` gains:
  - `FAMILY_OF`: each of busk's attributes and its family (the registry's 31 rows). A test
    checks it against `busk.model.attributes.ATTRIBUTES`. Tests may import busk; `src/busk_tui`
    may not.
  - `POOL_FAMILIES` and `DEFAULT_SCOPE`.
  - Rows for the scalars F2 lacks: `positionSpeed`, `colorMacroRate`, the rotations
    (degrees per second, a signed bar centred on 0), `effectRate`, `effectFade`,
    `effectAdjust`, `effectSync`, `soundSensitivity`, `color.a` and `color.uv`.
  - The discrete attributes per family.
  - `pool_rows(pool, show)`: the rows a pool's editor shows.
  - `records(pool, programmer)`: the RECORDS summary.
- `commands.py` gains `record_preset(pool, n, scope, merge=None, name=None)`, `delete_preset`,
  `rename_preset`, `renumber_preset`, `set_color(r, g, b)`, `set_option(attribute, option)`,
  `set_spread(attribute, low, high, how)` (Q5) and `clear()`. Each is added to the contract
  test.

### 5.3 Inspect, rename, renumber, delete

When a preset is chosen, the panel shows:

- **header:** `PRESET · color 2 "Red"`;
- **actions:** `[rename…]`, `[number…]` and `[delete]`;
- **HOLDS:** a line per entry, for example `color  global  ████ 1 0 0` or
  `pan  target 101  -30°`. Long lists scroll within the panel;
- **use:** `used by cue 4/1, 10/1–10/4` (consecutive cues of one list compressed), or
  `used by no cue`.

`[delete]` posts `RunLine(delete_preset(…), ask=…)`. `RunLine.ask` is new: a question the TUI
asks itself, through the existing `ConfirmDialog`, when the engine asks none (Q3). Once the
delete is done, the panel goes back to "click a tile". `TextDialog` is new in
`widgets/dialogs.py`: a title, an `Input` and a check that returns an error or `None`. Enter
runs the check, Esc cancels. The name and number dialogs are two uses of it.

### 5.4 Record a new preset

The panel, top to bottom:

1. **Number, name and scope** (§4 calls 3, 7 and 8).
2. **SELECTION:** the selection (`selection_text`, as F2 shows it), the group buttons, `[none]`,
   and `[its fixtures]` for an existing preset.
3. **The pool's editors** (§5.6): one section per family. The `all` pool shows every section.
4. **RECORDS** (§4 call 5).
5. **Buttons:** `[record]` (magenta, the "record" intent), `[clear]`, `[blind on|off]` (a
   toggle that follows the programmer, as on F2), and `[done]`.

`[record]` sends `record preset color 5 global "Crimson"`, with the name only when one was
given. Once the line succeeds (`RunLine.done`), the panel shows the new preset, as in §5.3 and
§5.5.

### 5.5 Change a preset's values

For a chosen preset, the panel shows §5.3's parts and §5.4's editors. In place of
`[record]` it has:

- `[load]` (§4 call 10);
- `[merge]`: "adds the programmer's values; a value of the same scope and attribute is
  replaced";
- `[replace]`: "the programmer's values become the preset's";
- `[remove]`: "removes what the programmer's fixtures see, for the attributes the programmer
  holds".

The text after each button is the dim hint shown under the mouse. The scope buttons apply to
`merge` and `replace` as well. The intended flow is: `[its fixtures]`, then `[load]`, change
the values, then `[merge]`.

### 5.6 The editors

- **Scalar rows** reuse F2's `EncoderRow`: the bar sets, `[−]`/`[+]` and the wheel step, and a
  value from the programmer shows magenta, from the output dim. Both pages build their rows
  from one table.
- **The colour picker** (`widgets/colorpicker.py`, Q4):
  - `ColorField`: the field described in §4 call 11;
  - the named chips (§4 call 12);
  - a readout of the programmer's colour (a swatch, `r g b` and the hex value);
  - the component rows, from `color.r` to `color.uv` as the rig takes them, and `cto`.

  It renders with `colors.swatch`, so it works in truecolour, 256 and 16 colours. Colours are
  coarser in 256 and 16, but what it sends is the same.
- **Option rows** (`widgets/options.py`): the attribute, then a chip per option the selection
  offers (`ProgrammerModel.options`). The programmer's option for the first selected element
  is lit. A click sends `set gobo1 star`. With no options, the row reads "the selection has no
  gobo1". This covers `colorWheel`, `colorMacro` and `colorEffect` in COLOR; `gobo1`, `gobo2`,
  `prism`, `effect` and `effect2` in BEAM; and `shutter` in SHUTTER.
- **Spread** (Q5): a `[spread]` toggle on a scalar row swaps its bar for two bars, "from" and
  "to", and adds `[centre]` and `[edges]`. Changes send `set pan spread -30 30` (with `center`
  or `edges` when chosen). It is offered on the scalar rows (`pan`, `tilt`, `zoom`,
  `intensity` …), not on a colour component: busk refuses `set color.r spread 0 1` ("expected
  the colour's r").

## 6. Steps

Baseline at `f19c4ec` (2026-11-01): the TUI suite (`tests/tui`) has 419 passed and 7 perf
tests deselected. Each step ends with:

- the whole suite green;
- `ruff check`, `ruff format --check` and `mypy src` clean;
- the TUI's new tests passing on Textual 8.2.0, the floor;
- a **Done** note under the step.

Use `uv run python -m pytest`. Each step is one commit, which the user makes. Following the
TUI phases, each group below (A to D) is one conversation, which ends with a status memory and
a stop.

**A. Read and manage**

1. **Model, bridge, tables, lines** (§5.1, §5.2). Verify:
   - conversion: `entries` for global, profile and target values (the club's Audience is per
     target); `used_by` for Red (`4/1`, `10/1`–`10/4`, `15/1`, `18/2`);
   - `options` on the TupperDMX heads, the blinders, and a selection without the attribute;
   - `color.w` on the washes; `color.a` and `color.uv` on a test profile; the rotation ranges
     on the TupperDMX head;
   - `FAMILY_OF` against busk's registry, `DEFAULT_SCOPE` against what busk records, and every
     new builder's line in the contract test.

   **Done** (2026-11-01). As planned, with these deviations and additions:
   - `used_by` holds `(list, cue)` pairs, not `"4/1"` text, so F6 can compress a run by the
     list's cue order (`formats.cues_text`, step 2).
   - **Added `PresetInfo.palettes`:** the effect templates whose colour palette takes the
     preset. busk refuses to delete a preset that a palette references, as it does for a cue,
     so "inert while used" counts palettes too. No show here has one; the test adds one to a
     copy of the club show.
   - **Added `HeldValue.ref`,** the preset's pool and number. `HeldValue.preset` holds only the
     name, and names are not unique across pools. The delete question needs to know whether
     the programmer refers to *this* preset.
   - **Options** (`bridge.selection_options`) are read on the reader thread. busk documents
     `LiveShow.expected` as read-only and safe from a frontend's own thread, so the read stays
     there. They are read again when the selection changes and when the document changes (a
     new document can change what a profile offers). An empty selection reads nothing.
   - **One row table:** `attributes.ROWS` has every encoder row. F2's `FAMILIES` is derived from
     the rows marked `program`, so F2 is unchanged: the new rows are for the panel only, as
     §1 says. Rotations have a unit of their own, `degps`, rounded like degrees. Their signed
     bar, centred on 0, is drawing work, so it is left to step 3.
   - `POOLS` moved from `pages/presets.py` to `attributes.py`. Also added: `family_of`,
     `recordable(show)` (§4 call 1, used in step 2), `OPTIONS` and `DISCRETE`, and dataclasses
     for `pool_rows` (`Section`: family, encoders, discrete attributes) and `records`
     (`Records`: attribute → elements, and the count not selected).
   - `record_preset` always names its scope (§4 call 3). The contract test runs the new
     builders in order on the club show: record, merge (at `target`), replace, remove,
     rename, renumber, delete.
   - **The default-scope test** records each pool without a scope and compares the stored
     scope with `DEFAULT_SCOPE`. No profile of either show has a focus channel, so the test
     turns the club spot's white channel into focus, in a copy. The test also checks
     `POOL_FAMILIES` against `busk.commands.record`. It checks that each of busk's scalars has a
     row in its family and unit, and that `DISCRETE` is busk's discrete attributes except
     `control`.
2. **Edit mode, inspect, rename, renumber, delete** (§3, §4 calls 1, 2, 6–8, 15, 16, §5.3).
   Verify:
   - every recordable pool shows (beam on the club, focus not), and `+ record` opens the panel;
   - a tile click applies with edit mode off and chooses with it on;
   - HOLDS and `used by`;
   - rename and renumber through the dialog: one line each, refused input stays in the dialog,
     and a quote is refused;
   - delete: inert on Red, while on a fresh preset `ConfirmDialog` asks, Yes sends the line and
     No logs "cancelled";
   - the pane cursor's stops, and the layout at 150, 100 and 99 columns.

   **Done** (2026-11-01). The panel is `widgets/preset_panel.py` (`PresetPanel`, `Chosen`),
   and the page owns edit mode. Deviations and additions:
   - **A stopgap until step 3.** A new preset's panel has `[record…]`. It puts
     `record preset color 5 global "Name"` in the prompt, with the pool's default scope and the
     name given. Call 2 drops the `+ record` pre-fill, and `[record]` comes in step 3. Without
     the stopgap, this commit could not record a preset from F6 at all. Step 3 replaces it.
     When the show gets a preset with the panel's number (recorded at the prompt, for
     example), the panel shows that preset. Step 3's "after `[record]`" relies on this too.
   - **The users line** also names effect palettes (`used by cue 4/1 · effect Rainbow`), and adds
     "to delete it, take it out of those first" while `[delete]` is inert. An inert delete is
     no pane-cursor stop.
   - **The delete question** counts the programmer's fixtures that refer to the preset ("The
     programmer holds it on 2 fixtures: they would show it as gone."). A delete that succeeds
     takes the panel back to "click a tile". So does a chosen preset that the show no longer
     has, for example one deleted at the prompt.
   - **Renumber:** the line's `done` moves the choice to the new number. A refused renumber
     leaves it. A rename to the same name sends nothing.
   - **A new preset's name** shows as `[name: Color 5…]`, busk's own default (`<Pool> N`) until one
     is given. It is cut at 16 characters.
   - **The chosen tile** has a magenta border.
   - **The header** reads "click a tile to apply it" or "click a tile to edit it". It no longer
     reads "click = preset <pool> N".
   - **Mine:** below 100 columns, a *click* on a tile scrolls the panel into sight. Without the
     scroll, the panel would be out of sight under the pools. The pane cursor does not do
     this, because it scrolls to what it marks.
   - Removed `commands.record_preset_prefill`, which nothing uses now.
   - **The real-terminal check** (pty and pyte, club show, 150 and 99 columns) covered the
     panel beside and under the pools, Red's HOLDS and users, Audience's fan, and the rename
     dialog. The full check on both shows is step 7.

**B. Record from controls**

3. **Selection, record, update, scalar editors** (§4 calls 5, 9, 10, 13, 14, §5.4, §5.5, the
   scalar rows of §5.6). Verify:
   - on the club show, from controls only: select Heads, set intensity, record an intensity
     preset; set pan and tilt and record a position preset with `target`; `[its fixtures]`,
     `[load]`, a step, `[merge]`; `[remove]`; `[replace]`;
   - RECORDS with fixtures outside the selection;
   - `[record]` inert with nothing to record;
   - the panel follows the programmer when it is changed from the prompt;
   - after `[record]`, the panel shows the new preset;
   - perf: F6 editing with the heads moving, under the 0.25 gate.

   **Done** (2026-11-02). As planned, with these deviations and additions:
   - **The scope a preset of the show starts at** is the one its values share. Only when they
     differ is it the pool's default. A new preset starts at the pool's default, as planned.
     Why: `[merge]` at the pool's default on a colour preset recorded per target would write a
     global value and drop the programmer's fixtures' target values. A scope chosen is
     forgotten when another preset is chosen.
   - **`[remove]` names no scope.** busk's `remove` deletes entries of every scope that a
     programmer target sees, and ignores a scope word, so `record_preset` takes `scope=None`
     and sends `record preset color 2 remove`. The echo then does not suggest a scope. The
     contract test changed with it.
   - **What is inert:** `[record]`, `[merge]`, `[replace]` and `[remove]` while RECORDS is
     empty (busk: "the programmer has no color values"), and `[load]` with nothing selected
     (busk: "nothing selected"). An inert button is no pane-cursor stop.
   - **Two button rows:** `[record]`, or `[load] [merge] [replace] [remove]`, then
     `[clear] [blind on] [done]`. Together they do not fit the panel's 47 cells.
   - **Hints:** `CommandButton(hint=)` shows its hint in the hint row while the mouse is on it
     (`ShowHint`). `[load]` has one too. The pane cursor shows none: the hint row has no
     per-item hints.
   - **RECORDS** is a heading and a line per attribute (`color  on 201 thru 204 (4)`). Elements
     outside the selection show as "· 1 not selected, recorded too", in amber.
   - **The panel's group buttons** have no numbers (F2's do), as in the mockup.
   - **Editors:** a section per family with a heading (`POSITION`). A section with only
     discrete attributes shows nothing until step 5. In the panel, the encoder names are 16
     cells wide (F2: 11), so `soundSensitivity` fits. The panel's scrollbar is one cell, as
     the log's is.
   - **The signed bar** (`bars.signed_bar_text`) fills whole cells from the centre, and marks 0
     with `│`. `EncoderBar(signed=)` uses it for the `degps` rows.
   - **`Page.WatchesChanged`** (new): F6 posts it when edit mode changes what it watches, and
     the shell then tells the bridge if F6 is the page shown.
   - **`[its fixtures]`** lists the fixtures by number. On the club show, Red selects all
     seven.
   - **Removed the stopgap:** `[record…]` and `prefill_record`.
   - **Tests:** the panel's tests in `test_tui_presets.py` (fake bridge, club model), the
     signed bar in `test_tui_widgets.py`, and an end-to-end test on the real engine
     (`test_f6_records_and_changes_presets_from_controls_on_the_real_engine`). That test does
     the first verify item from controls only, and checks the stored values after each line.
   - **Perf:** a case "F6 editing a position preset, P11's Circle running" in
     `test_tui_perf.py` (`tui_perf_frontend` takes `edit`). Under `busk run`, three
     alternating rounds measured F6 editing at +0.245, +0.274 and +0.233, and F2 moving
     (unchanged code) at +0.243, +0.260 and +0.272. Overruns were 0. F6 met the 0.25 gate in
     2 rounds, F2 in 1: the same cost, within the noise. The whole perf test failed on F1 A (+0.260), which this step does not
     touch. A Chromium renderer was taking 83 % of a core: the machine noise of Phase 5.
   - **The real-terminal check** (pty and pyte, club show, 150 and 99 columns) recorded
     position 3 from controls only. It covered Heads, the pan and tilt bars, RECORDS,
     `[record]`, and the panel turning into the new preset. It also checked Red's panel, the
     `[merge]` hint on hover, and the panel under the pools at 99 columns.

**C. Colour and options**

4. **The colour picker** (§4 calls 11, 12, §5.6). Verify:
   - a click on the field sends the cell's colour (hue and saturation to RGB, two decimals),
     and a drag sends throttled lines and logs the last;
   - a chip sends its colour; the marker follows the programmer's colour; the component rows
     act after the first pick;
   - rendering in 16, 256 and truecolour;
   - on the TupperDMX show, from controls only: select Pars, pick a colour, `[record]` a colour
     preset, and see it on F1 and F2's chips.

   **Done** (2026-11-02). As planned, with these deviations and additions:
   - **The picker** is `widgets/colorpicker.py`: `ColorField`, the chips (`CHIPS`), the readout,
     and `ColorPicker`, which holds the three. It starts the panel's colour section when the
     rig takes a colour, above the component rows.
   - **No marker for a grey.** A colour with a saturation under 0.1 (white, a pale tint) has no
     cell: its hue means nothing, and the palest row is 0.2. As planned, a colour under full
     value has no marker either.
   - **While a pick is in flight,** the marker shows the cell picked. Once its line is done, the
     marker shows the programmer's colour again.
   - **The field sets only while something is selected,** as an encoder bar does. The chips
     always send, as F2's colour chips do: with nothing selected, busk replies "nothing
     selected".
   - **The chips' look and values.** Each chip is ` red ` on its own colour, its text dark on a
     light colour and light on a dark one (`ink`), so the name reads in every mode. The plan
     gave values only for red, green, blue, amber, warm and cool. The rest are mine:
     - orange `1 0.25 0`, between red and amber;
     - yellow `1 1 0`, lime `0.5 1 0`, cyan `0 1 1`, sky `0 0.5 1`;
     - violet `0.5 0 1`, magenta `1 0 1`, pink `1 0.4 0.7`, white `1 1 1`.

     A test checks red, green, blue and amber against the club's presets.
   - **The readout** reads `████ 0.2 1 0.8 · #33ffcc`, plus the preset's name when the colour
     comes from one. With no colour held it reads "no colour held: pick one, then the rows
     act", and with nothing selected, "nothing selected". HOLDS uses the same component text
     (`colorpicker.components_text`).
   - **The pane cursor** stops on the chips, then the component rows. The field has no stop: it
     is mouse only.
   - **A test helper fixed.** `tap` in `test_tui_presets.py` now waits a frame before scrolling.
     With the taller panel, `test_a_new_preset_has_no_load_nor_writes…` clicked `[done]` before
     it was laid out, and missed in two runs out of three.
   - **Tests:**
     - in `test_tui_presets.py`: the field's cells; the marker, round trip on every cell; the
       three colour modes; the chips; a click; a drag (throttled, the last line logged);
       nothing selected; the marker and readout following the programmer; the component rows
       once a colour is held;
     - end to end on the real engine, `test_f6_records_a_colour_from_the_picker_on_the_real_engine`:
       TupperDMX Pars, a click on the field, `[record]`, then the new chip on F2 and on F1's
       layout B.
   - **The real-terminal check** (pty and pyte, TupperDMX, 150 and 99 columns, truecolour)
     covered the field's colours and its marker, and the chips' text colours. It then selected
     Pars, picked `set color 0.2 1 0.8` and recorded colour 5, which showed on F2's chips and
     F1's.
5. **Option rows** (§5.6). Verify:
   - the TupperDMX heads: `gobo1` and `prism` chips, `set gobo1 star`, and a beam preset with a
     gobo, a zoom and a rotation, recorded at `profile` scope;
   - the blinders: `effect` and `effectRate`;
   - the lit option follows the programmer;
   - a selection without the attribute.

   **Done** (2026-11-02). As planned, with these deviations and additions:
   - **Option rows** are `widgets/options.py` (`OptionRow`). Each row is the attribute, 16 cells
     wide like the encoder names, then its `[option]` chips, which wrap under themselves. The
     rows come after the section's encoder rows. A section with only discrete attributes now
     shows.
   - **The lit chip** is reversed in magenta, the programmer's colour. Its style is a span, not
     the label's base style: Rich's `Text` equality ignores the base style, so the strip would
     not redraw when only the lit chip changed.
   - **A row with no options** reads "nothing selected" or "the selection has no gobo1".
   - **The row's name is no control,** unlike an encoder's (which pre-fills `set <attribute> `).
     The chips are the row's pane-cursor stops.
   - **Engine fact:** the TupperDMX blinders take `effect` and `effectRate` on one cell each.
     `set effect soundActive` on both blinders replies "effect: 2 targets; skipped 6 no
     effect".
   - **Fixed, from step 3:** an empty signed bar was drawn filled from its left end, because
     level 0 is −360 °/s. It now shows the centre mark.
   - **Tests:**
     - in `test_tui_presets.py`, on the TupperDMX model with the options busk's completion
       gives: the heads, the blinders, nothing selected, the lit chip following the
       programmer, and the pane cursor;
     - end to end on the real engine,
       `test_f6_records_a_beam_preset_with_a_gobo_on_the_real_engine`: the heads, `[star]`,
       the zoom and rotation bars, and `[record]` at `profile`, with the stored values
       checked; then the blinders' `[soundActive]` and their effect rate.
   - **The real-terminal check** (pty and pyte, TupperDMX, 150 columns) selected the heads,
     clicked `[star]` (lit at once), set a zoom and a rotation, and recorded beam 1 at
     `profile` with three values.
   - **Found, not fixed:** in HOLDS, a profile value's line is as wide as the panel
     (`gobo1  profile TupperDMX Moving Head`), so each value wraps onto a line of its own. That
     is step 2's layout.

     **Fixed** (2026-11-03): a HOLDS line is now the attribute, the value, then the scope
     (`gobo1  star  profile TupperDMX Moving Head`). The widget crops a line too long with
     `…` instead of wrapping it, so only the scope's end is cut, and the crop follows the
     panel's width beside the pools and under them. Test:
     `test_holds_crops_a_long_scope_instead_of_wrapping`.

**D. Spread and docs**

6. **Spread** (Q5, §5.6). Verify: the club's Audience preset rebuilt from controls (`pan
   spread -30 30`, `tilt 40`, `target`) gives the same stored values as the script's.

   **Done** (2026-11-02). As planned, with these deviations and additions:
   - **The toggles are a line per section,** `spread [pan] [tilt] …`, after the section's
     encoder rows. There is no `[spread]` button on each row: the panel's 47 cells have no room
     for one without cutting the 16-cell names. A toggle sends nothing, and is lit while on.
     The row it names then shows as a spread row in place of its encoder row. Both rows are
     built, and `display` swaps them, so the other rows do not move.
   - **A spread row** (`widgets/spread.py`, `SpreadRow`) has a `from` line and a `to` line, each
     `[−]`, a bar, `[+]` and the value, as an encoder row has. Their names are 15 cells
     (`pan        from`), and a name longer than 10 is cut (`gobo1Rota… from`). Under them,
     `[centre]` and `[edges]` are toggles; with neither lit, the fan is linear. Each has a
     hover hint. A bar, a step, the wheel or a curve sends the whole spread, `set pan spread
     -30 30 center`, keyed `set:<attribute>`. A drag sends at most every `DRAG_S` and logs the
     last, as an encoder bar does.
   - **Reading the ends back.** busk keeps no spread. `set pan spread` gives each selected
     element its own value, by the compiler's rule, and the programmer holds those. The row
     fits a line through the programmer's values at the lowest and the highest fraction
     (`attributes.spread_fraction`, `spread_ends`, `spread_reading`). A test checks
     `spread_fraction` against busk's own. When the programmer holds nothing, the ends come
     from the output, dim. With one element, or two and `center` or `edges`, the values cannot
     tell `to`: both elements are at `from`. The row then shows the spread it last sent, as long
     as the programmer still holds what that spread gave. A change made elsewhere is read from
     the values again.
   - **What acts.** The bars act while something is selected. The steps, the wheel and a curve's
     line act only where the programmer holds the attribute on the selection, as on an
     encoder. With nothing held, a curve only lights. A bar then takes the other end from the
     output, or else sends a flat fan (`set tilt spread 0 0`).
   - **Which rows.** Every scalar row of the panel takes a spread, the rotations and the fixture
     effects' settings included: busk spreads any scalar. A colour's components take none.
   - **`StripButton.action`** (new): a strip button may call the page's own action instead of
     running a line, and `strip_stops` gives it an action stop. The spread toggles use it. Each
     button keeps one callable, so equal buttons compare equal and the strip is not redrawn
     for nothing.
   - **Fixed, from Phase 1.** `CommandButton.change` compared the old and the new `Text` with
     `!=`, and Rich's `Text` equality ignores the style. So a change of look alone (lit, inert,
     intent, dim) was never drawn. In a real terminal, these all kept their old look:
     - the lit scope (step 3);
     - a lit curve;
     - F2's and the panel's `[−]` `[+]` turning active;
     - `[record]` leaving grey;
     - F5's `RUN` dimming while an effect fades in.

     The headless tests checked the attributes, not what was drawn. `change` now compares the
     plain text and the style, and a test in `test_tui_widgets.py` checks what is drawn.
   - **Tests:**
     - in `test_tui_presets.py`: busk's rule, the ends read back, the reading, the toggles,
       the bars, steps and curves, nothing held, the last spread sent, a drag, no spread on
       a colour's components, and the pane cursor;
     - end to end, `test_f6_rebuilds_the_audience_fan_from_controls_on_the_real_engine`:
       Heads, pan as a spread (bars and steps), tilt (bar, steps and wheel), then `[record]`.
       The stored values equal Audience's.
   - **Perf** was not measured again. A spread row draws only while toggled on. At the
     output's 10 Hz it reads the output of each selected element.
   - **The real-terminal check** (pty and pyte):
     - club, 150 columns: the same by mouse. Position 3 was recorded with pan −30 and 30 and
       tilt 40 per target, and its tile reads `mixed/40°`, as Audience's does;
     - TupperDMX, 150 columns: a pan fan over the four heads with `[centre]` (busk gave −270,
       90, 90 and −270; the bars read −270 and 270), a signed fan of `gobo1Rotation`, and the
       spread line wrapping in BEAM;
     - club, 99 columns: the panel under the pools.

     It also found the `CommandButton` bug above.
7. **Docs.**
   - `docs/tui/guide.md` F6;
   - the help screen's keys and the hint row;
   - `docs/dev/tui/operations-report.md`'s Presets rows and summary;
   - the TUI plan's §2.7 table, with a pointer to this plan;
   - a real-terminal check (pty and pyte, as in Phases 2–5) on both shows.

   **Done** (2026-11-02).
   - **The guide's F6** is rewritten: which pools show, edit mode, the panel (its mockup is
     from the real terminal), the editors, RECORDS, a preset's own actions, the pane cursor
     and the layout. The guide's hint row now mentions what shows under the mouse. Its
     dialogs section adds the delete question and the name and number dialogs.
   - **The help screen's keys** are unchanged. The panel adds no key: the pane cursor (Tab)
     was there, and the dialogs show their own keys (`Enter: OK · Esc: cancel`). **The hint
     row:** `[centre]` and `[edges]` got hover hints, as `[load]` and the writes have.
   - **The report:** the Presets rows, the summary's row and its "In short" item, and a note
     on the delete question in the side findings. F6 is gone from "What the TUI is missing".
   - **The TUI plan's §2.7** has four rows for the panel and a pointer to this plan.
   - **The real-terminal check** on both shows is step 6's. Groups A to C checked the rest of
     the panel.
8. **The user's:** on the rig, record a colour preset from the picker, a beam preset with a
   gobo and a position fan; rename, renumber and delete one; update one with `[merge]`.

**After the plan** (2026-11-05). On 2026-11-03 the user asked why `+ record` needs a selection
and why no Color Macro row shows. Their answers to the two choices that came out of it:
- **A hint under SELECTION** (`preset_panel.KEEPS`) says what the scope lit keeps. A value that
  differs falls back to a narrower scope, so the `global` and `profile` hints say "if they
  agree". `test_each_scope_keeps_what_the_panels_hint_says` checks them against busk.
- **A row no profile of the show takes shows dimmed,** last in its section:
  `colorMacro       no fixture takes it`. It has no control and no pane-cursor stop. `pool_rows`
  now gives every family of the pool, so `all` has a FOCUS section on the club show. F2 is
  unchanged, and call 1 still decides which pools show.
- **The cost:** the panel gets taller. At 150×48 on the club show, `color` goes from 28 lines to
  37 and `beam` from 22 to 39, past the 30 the panel shows, so `[record]` needs a scroll there.

## 7. Found while planning (busk, not fixed here)

These are for the user to number in `docs/dev/tui/engine-gaps.md`, or not:

1. **Refusals in document paths.** `delete preset` names `cueLists[3].cues[0].entries[0]…`
   and an id. A renumber to a taken number names `presets[1]`. The TUI shows `used by` and the
   free numbers itself (§4 calls 6 and 7), so it never sends those lines. At the prompt the
   messages stay unclear.
2. **Bug: a wrong fallback note.** With the `profile` scope, the default for beam and focus,
   `record preset` adds "(values differ)" for every attribute, even when every profile
   agrees: `record preset beam 1 "Gobo"` on four identical heads replies "gobo1: 1 profile
   value (values differ)". `_cascade` in `commands/record.py` adds the note whenever the scope
   is not `target`, instead of only when a value fell back. The panel shows this reply in the
   log.
3. Deleting a preset the programmer references leaves `preset pr-… (gone)` in the
   programmer. busk allows this; the TUI asks first and says so (§4 call 6). The text is fixed
   (2026-11-07): `programmer` now leaves the value out, as `ProgrammerStatus` does.

## 8. Not in this plan

- The picker and option rows on F2. The widgets are reusable, and F2 could take them in a later
  step.
- Copying or moving a preset (no busk line). Deletes that cascade (report item 6).
- Editing one stored value of a preset in place (for example, changing only fixture 101's pan
  in Audience without the programmer). busk records presets only from the programmer, and
  `submit()` is out of bounds for the TUI.
- A configurable chip list (`config.toml`). It can come later if the constant list is not
  enough.

## 9. Open questions

Each has a recommendation, (a):

1. **Where is the editor?**
   - **(a) A PRESET panel on F6, in an edit mode.** The log and the prompt stay visible, so the
     panel's lines and refusals show like every control's.
   - (b) A modal dialog. It takes every key and hides the log.
   - (c) A page of its own. There is no free F-key: F10 is help.

   ANSWER: (a).
2. **How does the operator choose a preset to edit?**
   - **(a) The header's `[edit]` toggle.** While it is on, a click chooses. This is the console
     idiom (EDIT, then a preset). Applying stays one click, and the pane cursor keeps one stop
     per tile.
   - (b) A `✎` cell on each tile. There is no mode, but the target is one cell and each tile
     has two stops.
   - (c) A right click. Not every terminal sends one, and the keyboard cannot reach it.

   ANSWER: (a).
3. **What does the TUI ask before running?** busk asks nothing.
   - **(a) Before a delete only.** Everything is an undo step, and a delete is the one action a
     stray click on the panel loses most with.
   - (b) Before delete, replace and remove.
   - (c) Nothing: rely on `undo`.

   ANSWER: (a).
4. **What is the colour picker?**
   - **(a) A hue × saturation field, named chips, and the component bars.**
   - (b) Chips and bars only. That is quicker to build, but there is no free choice of colour
     until a colour is held.
   - (c) (a), plus a hex value typed in a dialog.

   ANSWER: (a).
5. **Spread (fans)?**
   - **(a) Step 6: spread rows in the editor.** The show's own position presets are fans.
   - (b) Leave spread to the prompt. A fan would then need one selection and one `set` per head.

   ANSWER: (a).
