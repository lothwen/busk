# TUI fixtures and universes: implementation plan

> Source: the user's request of 2026-11-05. Take the "F3, F8" item of "What the TUI is missing"
> in `docs/dev/tui/operations-report.md` (add a fixture, add a universe, delete either, limits,
> renumber, rename a universe) and give F3 and F8 full control of fixtures and universes.
> Written at `ab05ea3`. The same day the user asked for the engine gaps to be the plan's first
> steps, the route line first, so that every later step can be built as planned (§10). The calls
> in §4 and §5 are the plan's, and the user may veto them.

**Steps 1 to 6 are engine work.** They change `src/busk/` and its tests, as GAP-01 to GAP-21 did.
Each closes something a TUI step relies on, so no TUI step is left inert or waiting on the engine.

**From step 7 on,** the TUI rules of `docs/dev/tui/implementation-plan.md` §1 apply:
- no change to `src/busk/` or to the engine's tests;
- only `bridge.py` imports `busk`, and only its public names;
- every action is a console line sent through `LiveShow.execute()`;
- an engine gap is written down. The TUI never works around one.

## 1. Scope

The fixture operations, and what this plan makes of each:

| Operation | busk line (new lines by gap) | Today | After this plan |
|---|---|---|---|
| Show | `LiveShow.show`, `.output` | control (F3, F8) | control, plus limits, orientation and location (§6.4) |
| Add a fixture | `fixture add N [thru M] "<profile>" mode <mode> [at U.A]` | prompt | control: F3's new fixture form with a profile picker (§6.6) |
| Delete a fixture | `delete fixture N cascade` (GAP-24) | prompt, refused while used | control: busk's question, then the fixture and every reference to it go in one undo step |
| Patch, unpatch | `fixture N patch U.A`, `fixture N patch none` | pre-fill | control: F3's PATCH section, and a free channel on F8's map (§6.3, §6.5) |
| Rename | `rename fixture N "…"` | pre-fill | control: a name dialog |
| Renumber | `fixture N number M` | prompt | control: a number dialog |
| Limits | `fixture N [thru M] limits …`, `… limits pan none` (GAP-25) | prompt | control: a dialog per limit, and `[none]` (§6.5) |
| Location | `fixture N location {…}`, `… location none` (GAP-25) | pre-fill | control: a six-field dialog, and `[no place]` (§6.5) |
| Orientation | `fixture N orientation.<key> <value>` | prompt (the report has no row) | control: toggles and an offset dialog (§6.5) |
| Category | `profile "<name>" category …` | pre-fill | control: chips (§6.4) |
| Change the mode | `fixture N mode "<mode>"` (GAP-26) | none | control: chips |
| Change the profile | `fixture N profile "<profile>" mode "<mode>"` (GAP-26) | none | control: the picker |

The universes and their routes:

| Operation | busk line (new lines by gap) | Today | After this plan |
|---|---|---|---|
| Show | `LiveShow.show`, `.routes` | control (F8) | control |
| Add a universe | `universe add N ["name"]` | prompt | control: a dialog (§6.3) |
| Delete a universe | `delete universe N cascade` (GAP-24) | prompt, refused while used | control: busk's question, then its fixtures are unpatched and its routes go, in one undo step |
| Rename, renumber | `rename universe N "…"`, `universe N number M` | prompt | control: dialogs |
| Add a route | `route add …` | prompt | control: a dialog (§6.7) |
| Delete a route | `delete route <id>` (GAP-23) | none | control: busk's question |
| Disable, enable | `route <id> on\|off` (GAP-23) | none | control: a toggle |

**In:** the engine gaps of §5, then F3, F8, the FIXTURE panel and the dialogs they need, the model
and bridge additions, the command builders, tests, the guide, and updates to the report and the
TUI plan.

**Out** (§9): groups, park, F1 C's `[location…]`, profile import, and deletes that cascade for
anything but fixtures and universes.

## 2. What busk does (checked on 2026-11-05)

This is busk at `ab05ea3`, before the engine steps. Each line below was run on `OfflineShow` with
`examples/club-night.busk` or `examples/tupperdmx/tupper-demo.show`, and "Live" on a running
`LiveShow`. The exception is said where it occurs.

**Universes**
- `universe add 2 "Balcony"` works. Without a name, busk names it `Universe 3`. A taken number is
  refused (`universe 2 exists`), and so are `0` and `-1`, with a document path.
- `rename universe 3 "Roof"` works, and so does an empty name.
- `universe 3 number 7` works. A taken number is refused with a document path: `Duplicate number
  2 (first used at universes[1])`. Patches and routes hold the universe's id, so they follow it.
- `delete universe N` is refused while a fixture is patched in it **or a route sends it**. The
  report names only the fixtures. Universe 1 has a route on both shows.

**Routes**
- `route` takes only `add`, and `delete` does not take `route`. Only `undo` takes a route back.
- A route has no number. `list routes` prints its id: `r-871f61aaac06  U1 → sACN 1 multicast eth0`.
- `route add 2 sacn 2` run twice gives two identical routes.
- Refused: an sACN universe another show universe sends, an sACN universe of 0 or above 63999, a
  `subNet` above 15, and a DMX-USB port another route uses.

**Adding fixtures**
- `fixture add 901 thru 903 "RGB Par 3ch" mode 3ch at 2.1` patches 2.1, 2.4 and 2.7 in one undo
  step. Each is named `<model> <number>`. The line takes no name.
- `expected('fixture add 900 ')` lists the show's profiles, then the library's that the show does
  not embed. `expected('fixture add 900 "<profile>" mode ')` lists the modes. A mode may always
  be quoted: `mode "3ch"` works.
- **`expected()` gives no footprint.** A library profile is not in the document until the first
  `fixture add` embeds it, so the report's "built from `expected()`" gives names but no way to
  place a fixture (GAP-27).
- Refused: a taken number anywhere in the range (`fixture 903 exists`), an unknown universe, and
  an address of 0. Past channel 512 is refused with a document path, one per fixture for a `thru`
  (`Footprint of 3 channel(s) starting at 511 ends at 513, past channel 512`).
- `fixture add 0` and `fixture add -5` are accepted.
- **Overlap is a warning.** The line succeeds and replies `warning fixtures[10].patch.address:
  Channels 1–3 overlap fixture 'Par 900'`. busk treats double patching as legitimate.

**Patch**
- `fixture 900 patch 2.1` and `fixture 900 patch none` take one fixture per line. `fixture 900
  thru 901 patch 2.1` is refused with a confusing path (`fixtures[7].thru`).
- Live: `universe add`, `fixture add … at` and `fixture N patch` show in the frames at the next
  read, 0.3 s later. A patch moves the fixture's values to the new address and the old channels
  go dark. `route add` opens the route within 0.6 s, with state `ok` and packets counting.

**Delete**
- `delete fixture N` takes one fixture per line (`thru` is refused). The refusal lists document
  paths and ids. `undo` brings the fixture back.
- It is refused by a group member, a preset's target value, a cue entry, a cue's per-target
  values, a cue effect, a cue release and a park entry. Each was run. A binding's `SELECT` is
  checked too (`_command` in the validator, read, not run: neither show has one).
- A cue that reaches the fixture through a group does not refuse it. The group does.
- **None of the 18 fixtures can be deleted today:** 0 of 7 on the club show, 0 of 11 on TupperDMX.
  Seventeen are in a group. The other, TupperDMX's smoke machine 301, is used by cue 8/1.
- Deleting a fixture that is selected, or that the programmer holds, works. `ProgrammerStatus`
  drops it, but the `programmer` line prints `fx-… (gone)`, for an effect's target too.

**Properties**
- `fixture 900 number 950` works and a taken number is refused. Groups follow, because they hold
  the id.
- Limits: `fixture 101 limits tilt -90 10`, `… limits pan -180 180`, `… limits intensity 50%`
  and `… limits none`, the last removing all of them. `fixture 101 thru 102 limits …` covers
  **every fixture that exists between the ends**. `limits tilt none` is refused. A limit on an
  attribute the fixture lacks is accepted with a warning. `limits none` on a fixture without
  limits is refused.
- The club show has limits: tilt −90 to 10 on 101 and 102, intensity 0.5 on 301.
- Location: `fixture 950 location {"x": 1, "y": 2, "z": 3, "rx": 0, "ry": 0, "rz": 0}` needs all
  six keys. `location.x 3` works only once a location exists. `location none` is refused.
- Orientation: `fixture 950 orientation.invertPan true` and `orientation.panOffset 30` work, and
  so do `invertTilt`, `swapPanTilt` and `tiltOffset`. One fixture per line. They are accepted on
  a fixture with no pan, where they do nothing. busk refuses a swap on an element that has only
  one of pan and tilt. An offset of 400 is accepted.
- Mode: `fixture 1 modeId "mode-3"` works, with busk's internal id, on a two-mode test profile. No
  profile of the library or the shows has two modes.
- Category: `expected('profile "<name>" category ')` gives `par spot wash beam pixel strobe
  blinder dimmer effect fog other none`.

**Names.** `tokenize` reads a quoted string with JSON escapes, so busk *has* an escape for a
double quote. `commands.quoted` says it has none, and writes the name bare:
- `"say \"hi\""` works, but `quoted` refuses that name;
- a name `C:\new` reaches busk with a newline in it, without a word;
- a name `back\slash` raises `JSONDecodeError`, out of `execute()`, `expected()`, `confirmation()`
  and `run_script()` alike. The prompt calls `expected()` as it is typed.

`json.dumps(name, ensure_ascii=False)` round-trips all of these, plus accents, emoji and a tab.

**What the gaps rest on.** Each gap was prototyped through `submit()`, which already takes the
commands the new lines would build:
- **Routes, Live:** `SET … enabled false` gives state `disabled`, `true` gives `ok`, and `DELETE`
  removes the route. `undo` restores each. This was in-process, not under `busk run`.
- **Fixture cascade:** one `BATCH` per fixture, on all 18. Each left a show with no validation
  error, and `undo` gave back an equal document. All 18 in a row left a valid show with empty
  groups, presets and cues, which saved and reloaded.
- **Universe cascade, Live:** one `BATCH` unpatched the fixture, removed the route and the
  universe. Its frames stopped, and `undo` gave back an equal document and the frames.
- **Removals:** `DELETE` works on `location` and on one key of `limits`. The last key leaves
  `limits: {}`.
- **Profile:** one `BATCH` setting `profileId`, `profileRevision` and `modeId` works, embedding a
  library profile first when needed, and `undo` takes the embedded profile back too. A footprint
  past 512 is refused. A 12-element bar going to one element is refused while groups name its
  elements. A spot going to a par is accepted, with a warning for its tilt limit: its presets keep
  their pan and tilt values, which then do nothing.

## 3. The design in one picture

F3 at 150 columns, with edit mode on, fixture 102 chosen and `[next free]` pressed. The live
columns give way to the rig's, and the page stops reading the output:

```
 7 fixtures · 1 selected · click chooses, Shift-click adds to the selection                            [+ add] [edit ●]
┌ FIXTURES ──────────────────────────────────────────────────────────┐ ┌ FIXTURE · 102 Spot 102 ───────────────────────┐
│     # name         profile           type mode  patch limits place │ │ [rename…] [number…] [delete]                  │
│   101 Spot 101     Generic Spot 16ch spot 16ch  1.1   tilt   ·     │ │ Generic Spot 16ch · 16ch · 16 channels        │
│ ▸ 102 Spot 102     Generic Spot 16ch spot 16ch  1.17  tilt   ·     │ │ [profile…]                                    │
│   201 LED ML-56 …  Eurolite LED ML…  par  4-ch… 1.33         ·     │ │ category of 2 fixtures                        │
│   202 LED ML-56 …  Eurolite LED ML…  par  4-ch… 1.37         ·     │ │ [par] [spot] [wash] [beam] [pixel] [strobe] … │
│   203 LED ML-56 …  Eurolite LED ML…  par  4-ch… 1.41         ·     │ │                                               │
│   204 LED ML-56 …  Eurolite LED ML…  par  4-ch… 1.45         ·     │ │ PATCH 1.17–1.32                               │
│   301 COLORband …  Chauvet DJ COLO…  pix… 36-CH 1.49  int    ·     │ │ universe [none] [1 Stage] [2 Balcony]         │
└────────────────────────────────────────────────────────────────────┘ │ address  85 [address…] [next free]            │
                                                                       │ takes 1.85–1.100 · free                       │
                                                                       │ [patch]                                       │
                                                                       │                                               │
                                                                       │ LIMITS · 102                                  │
                                                                       │ pan        none          [limit…]             │
                                                                       │ tilt       -90° to 10°   [limit…] [none]      │
                                                                       │ intensity  none          [limit…]             │
                                                                       │ [no limits]                                   │
                                                                       │                                               │
                                                                       │ ORIENTATION · 102                             │
                                                                       │ [invert pan] [invert tilt] [swap pan/tilt]    │
                                                                       │ pan offset 0° [offset…] tilt offset 0° […]    │
                                                                       │                                               │
                                                                       │ LOCATION  no place             [location…]    │
                                                                       │ [done]                                        │
                                                                       └───────────────────────────────────────────────┘
```

`[+ add]` shows the new fixture form in the same panel:

```
┌ FIXTURE · new ────────────────────────────────┐
│ profile [Generic Spot 16ch…]                  │
│ mode    [16ch]                                │
│ number  [−] 302 [+] [number…]                 │
│ count   [−] 4 [+]   302 thru 305              │
│                                               │
│ PATCH                                         │
│ universe [none] [1 Stage] [2 Balcony]         │
│ address  85 [address…] [next free]            │
│ takes 1.85–1.148 · free                       │
│                                               │
│ [add] [done]                                  │
└───────────────────────────────────────────────┘
```

F8 at 150 columns, with universe 2 and the route chosen, and a free channel clicked on universe 1's
map:

```
┌ UNIVERSES ────────────────────────────────────────────┐┌ ROUTES ────────────────────────────────────────────────┐
│   U name                 fixtures   used overlaps     ││   U proto  address destination     tx     state        │
│   1 Stage                       7  84/512        0    ││ ▸ 1 sACN   1       multicast eth0  ● 1/s  open         │
│ ▸ 2 Balcony                     0   0/512        0    ││                                                        │
│ [+ universe…] U2 Balcony [rename…] [number…] [delete] ││ [+ route…] U1 sACN 1 [off] [delete]                    │
└───────────────────────────────────────────────────────┘└────────────────────────────────────────────────────────┘
 place 1.85 · 428 free from here · [patch 102 here] [add fixture here…]
┌ DMX MAP · U1 Stage · 84/512 ────────────────────────────────────────────────────────────────────────────────────┐
│    1 █▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓█▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓█▓▓▓█▓▓▓█▓▓▓█▓▓▓█▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓                                           │
│   65 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░····························                                           │
│  129 ································································                                           │
│ …                                                                                                               │
```

## 4. Calls the user may veto

These follow the presets plan's answers and the "engine first" rule. §5 has the engine's own
calls. Each is open to veto:

1. **F3 gets an edit mode, as F6 has.** `[edit]` in a new header row turns it on, and so does
   `[+ add]`. With it off, F3 is its live table. With it on, the FIXTURE panel opens, the table
   shows the rig's columns instead of the live ones (§6.4), and `watches()` stops the output read.
2. **A click keeps selecting in edit mode.** F6's click changes meaning because applying a preset
   changes the stage. Selecting does not, so a click on F3 always selects and chooses.
3. **F3's four pre-fills go.** The panel replaces them, and the strip under the table goes with
   them. `patch_prefill`, `rename_fixture_prefill`, `category_prefill` and `_category_prefill` go
   too. `location_prefill` stays, for F1 C. The prompt takes every line as before.
4. **Two reaches.** The header, PATCH, the mode and the profile act on the chosen fixture. LIMITS
   and ORIENTATION act on every selected fixture while the chosen one is selected, because a rig's
   heads usually share them. Their headings name what they act on (`LIMITS · 101 thru 102 (2)`).
   Limits go out as `thru` lines, one per run of the show's sorted numbers that are all selected
   (`thru` covers every fixture between its ends). Orientation goes out a line per fixture: busk
   has no `thru` there. So four heads are four undo steps.
5. **Patch is a choice, then a line.** The universe chips, `[address…]` and `[next free]` send
   nothing. `[patch]` sends one line, and with `[none]` lit it sends `fixture N patch none`. It is
   inert while the choice equals the patch.
6. **The address follows the room.** Choosing a universe proposes its first run of free channels
   that fits, the whole block for a `thru`. The `takes` line says what the address means:
   `free`, amber `overlaps fixture 301` (allowed, as busk allows it), red `past channel 512`
   (`[patch]` or `[add]` inert), or `no room for 64 channels`.
7. **The picker reads `fixture_profiles`** (GAP-27), as F5 reads `effect_templates`.
8. **The profile picker is a modal dialog,** because its filter is typed and only a modal has the
   keyboard. It chooses and sends nothing. Everything else in the form is in the panel, so the log
   and the prompt stay visible, as on F6.
9. **Numbers.** A new fixture starts at the show's highest number plus one, a new universe likewise.
   `[−]` and `[+]` step over numbers free for the whole count. The TUI offers numbers from 1, though
   busk takes 0 and negatives for a fixture. `check_number` and `free_step` move from
   `preset_panel.py` to `dialogs.py`, and `check_name` with them.
10. **After `[add]`, the form stays,** with the next number and the next free address, because a rig
    goes in type by type. `[done]` leaves it. The new fixtures are not selected.
11. **`[delete]` always sends `… cascade`,** and is never inert. busk's own question (GAP-24) says
    what would go, through the app's existing `confirmation` step, so the TUI keeps no list of what
    can reference a fixture. The panel therefore has no `used by` line, unlike F6's: one click on
    `[delete]` shows it, and No sends nothing. A delete that succeeds takes the panel back to "click
    a fixture", so a second click cannot reach the next one.
12. **Limits use a dialog, not bars.** A dragged limit on a running rig would clip the output at
    every step. The dialog starts at the limit, else at the profile's range. `[none]` on a row
    removes that limit, and `[no limits]` removes them all.
13. **Location is a form,** with all six fields in one line, because `location.x` fails until a
    location exists. `[no place]` removes it.
14. **Orientation shows only where it means something:** the section needs pan or tilt, and
    `[swap pan/tilt]` needs both, since busk would accept the rest and do nothing. Toggles send at
    once, as option chips do.
15. **Mode chips show only for a profile with two modes or more,** so neither shipped show will
    show them today, and only a test profile exercises them. `[profile…]` always shows, and opens
    the picker. Its mode then comes from the chips, as in the new fixture form.
16. **Category is the profile's,** so the row says how many fixtures share it. The chips are
    `colors.CATEGORY_COLORS` plus `none`, and a contract test compares them with `expected()`.
17. **F3 sorts by number,** as `list fixtures` does. It shows document order today, so a new fixture
    150 would land under 901.
18. **F8 has no edit mode.** A universe's and a route's controls are strips, and each goes through a
    dialog or a question, so a stray click sends nothing. A click on a row chooses it. Nothing is
    chosen at first, so `[delete]` is not armed.
19. **A click on a free channel arms a place and sends nothing.** Today it does nothing. The strip
    above the maps then offers `[patch 102 here]`, and the map previews the footprint. It needs
    exactly one selected fixture, and otherwise says so. It is mouse only, like F6's colour field:
    F3's PATCH is the keyboard's way.
20. **`[add fixture here…]`** goes to F3 with the form open at that universe and address. This is
    the first control that changes page, so a new message reaches the shell, which calls
    `action_page`.
21. **`commands.quoted` uses `json.dumps`** (§2). This fixes F6's dialogs as well. `check_name` then
    refuses only an empty name, and the `except ValueError` in `pages/surfaces.py` and
    `pages/effects.py` go, as nothing raises it any more.
22. **Layout.** The panel is F6's: 52 cells, right of the table at 100 columns or more, under it
    below that, scrolling on its own. Below 100 columns a click scrolls it into sight.
23. **The pane cursor** stops on `[+ add]`, `[edit]`, each row and every panel control on F3; on each
    universe row and its strip, each route row and its strip, then each footprint on F8. An inert
    button is no stop.

## 5. Engine gaps

Numbered from GAP-23, the next free number. Each step adds its gap to
`docs/dev/tui/engine-gaps.md`: a section, a Summary row and a **Done** note. It also updates
`docs/console.md`, busk's `help`, the parser's grammar notes and `CHANGELOG.md`. Each is open to
veto.

### 5.1 GAP-23: Removing and switching routes

- `delete route <id>` removes a route. `route <id> on|off` sets its `enabled`. Each is one undo step.
- **A route is named by its id,** as `effect remove <id>` names an effect, and as `list routes`
  already prints it. Tab offers the ids. A number would change the show format for one line.
- `route ` offers `add` and the ids, and `delete route ` the ids. An unknown id is refused by name
  (`no route r-x`).
- **`delete route` and `route <id> off` ask first,** through `Submit.confirm`, as `output off` does:
  each stops a universe's output. `route <id> on` does not.
- `list routes` marks a disabled route.

### 5.2 GAP-24: Deletes that cascade

- `delete fixture N cascade` and `delete universe N cascade`, each one `BATCH`, so one undo step.
  Without `cascade`, both stay as they are: refused while used.
- **A fixture leaves** every group's members, every preset's target values, every cue entry's
  targets and per-target values, every cue effect's and release's targets, every park entry, and
  every binding's `SELECT`.
- **What goes with it:** an entry, an effect, a release or a binding left with no target. Each
  would mean nothing.
- **What stays:** a group, a preset or a cue left empty. Each is valid (§2), and whether it is still
  wanted is the operator's call. A cue that reaches the fixture through a group is not touched.
- **A universe** unpatches its fixtures, removes its routes, then goes. Fixtures stay, unpatched.
- **Both ask, always,** through `Submit.confirm`, naming what goes: `Delete fixture 101? It leaves
  groups 1, 4 and presets position 1, 2.`, `Delete universe 1 "Stage"? 7 fixtures lose their patch
  and 1 route goes.`. For a fixture the programmer holds, the question says so. A line with nothing
  to cascade still asks, so a frontend can always send `cascade` and show the answer.
- The reply counts what it took. `source` does not ask, as for every line.

### 5.3 GAP-25: Removing one limit, and a location

- `fixture N [thru M] limits pan|tilt|intensity none` removes that limit and keeps the others. The
  last one takes `limits` with it, so no `limits: {}` is left. It is refused when no fixture named
  has that limit, as `limits none` is.
- `fixture N location none` removes the location, and is refused when it has none.

### 5.4 GAP-26: Changing a fixture's mode and profile

- `fixture N mode "<mode>"` sets the mode by name, as `fixture add` takes it. Tab offers the
  profile's modes.
- `fixture N profile "<profile>" mode "<mode>"` sets the profile, its revision and the mode in one
  `BATCH`. Like `fixture add`, it embeds a library profile the show has no copy of, and it takes
  the show's copy when there is one. Tab offers the same profiles and modes.
- Both rest on the validator: past 512 and missing elements are refused, and an overlap warns.
- Presets keep values the new profile lacks, which do nothing (§2). busk does not ask: `undo` takes
  the line back.

### 5.5 GAP-27: What `fixture add` takes

- `OfflineShow.fixture_profiles` and `LiveShow.fixture_profiles`, on the model of
  `effect_templates` (GAP-15): the show's profiles in show order, then the library's that the show
  has no copy of, in library order. This is the order `expected()` offers. The same tuple comes back
  until one of them changes.
- `FixtureProfileInfo`: `name`, `id`, `source` (`"show"` or `"library"`), `manufacturer` and `modes`.
  `FixtureModeInfo`: `name`, `footprint` and `elements`. These are two new names in `busk.__all__`,
  so `tests/test_public_api.py`, `tests/api_consumer.py` and `docs/library.md` change.
- **Why not read `busk.ProfileLibrary` in the bridge,** which is public: it would load the library a
  second time and need the `--library` directories passed in `BUSK_TUI_OPTIONS`, and the TUI would
  keep its own copy of which profiles `fixture add` takes. The second load measured 1.6 ms for the
  five built-in profiles. A large `--library` directory was not measured.

### 5.6 A bad escape is a refused line

This is a bug, not a gap. `tokenize` turns the `JSONDecodeError` into a `ParseError` that names the
column. `execute()` then replies `ok=False`, `expected()` gives the error, `confirmation()` gives
`None`, and `run_script()` reports the line.

## 6. TUI design

### 6.1 Model and bridge

- `FixtureInfo` gains:
  - `limits`: pan and tilt as `(low, high)` or `None`, and the intensity maximum or `None`;
  - `orientation`: the five values, read from the document.
- `ProfileInfo.modes` holds each mode's name, footprint and element count.
- `ShowModel.choices` holds what `fixture add` takes, from `fixture_profiles`. `show_model` gets it
  as it gets `templates`.
- `RouteView` gains its `id`.

### 6.2 Lines and helpers

- `commands.py` gains `fixture_add(first, last, profile, mode, at=None)`, `delete_fixture`,
  `rename_fixture`, `renumber_fixture`, `patch_fixture(number, at)`, `limit_range(first, last,
  attribute, low, high)`, `limit_intensity(first, last, level)`, `no_limit(first, last, attribute)`,
  `no_limits(first, last)`, `orientation(number, key, value)`, `location(number, values)`,
  `no_location(number)`, `fixture_mode(number, mode)`, `fixture_profile(number, profile, mode)`,
  `category(profile, word)`, `universe_add(number, name=None)`, `delete_universe`,
  `rename_universe`, `renumber_universe`, `route_add(…)`, `delete_route(id)` and `route_on(id, on)`.
  Each is added to the contract test. The two deletes always send `cascade`.
- `formats.runs(selected, numbers)` gives the `thru` runs of §4 call 4.
- `widgets/dmxmap.py` gains `first_free(prints, size)` and `clashes(prints, start, size, own)`.

### 6.3 F8

- **UNIVERSES.** A click chooses a row, lit like F3's selection. The strip under the table holds
  `[+ universe…]`, and for the chosen universe `[rename…]`, `[number…]` and `[delete]`.
- **`[+ universe…]`** is a `FormDialog`: `number` (next free) and `name` (empty: busk names it).
- **The place.** A click on a free channel posts `DmxMap.PlaceClicked(universe, channel)`. The strip
  above the maps reads `place 1.85 · 428 free from here`, with `[patch 102 here]` and `[add fixture
  here…]`. With no single fixture selected, `[patch …]` is replaced by `select one fixture to patch
  it here`. `DmxMap.place(channel, size)` draws the footprint as `░` in cyan, red where it would
  overlap. A click on a fixture, or the universe's map changing, clears the place.

### 6.4 F3's edit mode and FIXTURE panel

**The page.** A header row holds the counts, `[+ add]` and `[edit]`. In edit mode `RigTable`, a
second `RowTable` with its own `COLUMNS`, takes the place of `FixtureTable`, and the legend hides.
Its columns are the marker, number, name, profile, type, mode and patch, then `limits` (`tilt`,
`pan tilt`, `int`) and `place` (`●` or `·`).

**The panel** is `widgets/fixture_panel.py`, on the model of `preset_panel.py`:

- **Header:** `FIXTURE · 102 Spot 102`, `[rename…]`, `[number…]`, `[delete]`.
- **What it is:** profile, mode and channels, then `[profile…]`, and the mode chips (§4 call 15).
- **Category:** an `OptionRow` of chips with the profile's word lit, under `category of 2 fixtures`.

With nothing chosen, the panel says "click a fixture, or `[+ add]`". When the fixture leaves the
show (deleted at the prompt, or by `undo`), the panel goes back to that. A renumber's `done` moves
the choice to the new number, as on F6.

### 6.5 The panel's sections

- **PATCH** (shared with §6.6): the heading gives the patch (`PATCH 1.17–1.32`), then the universe
  chips with `[none]`, the address with `[address…]` and `[next free]`, the `takes` line (§4 call
  6), and `[patch]`. With no universe, the chips read "no universe: F8 adds one".
- **LIMITS:** a row per limit the fixture can use: `pan` and `tilt` where the profile takes them,
  `intensity` always. `[limit…]` opens a `FormDialog` with `from` and `to`, or `at most`. `[none]`
  shows on a row with a limit. `[no limits]` is inert while no fixture it acts on has limits (busk
  refuses that line).
- **ORIENTATION:** `[invert pan]`, `[invert tilt]` and `[swap pan/tilt]`, lit from the chosen
  fixture, and `pan offset` and `tilt offset` with `[offset…]`, a `TextDialog` for a number.
- **LOCATION:** the six values, or `no place`, with `[location…]`, a `FormDialog` of six fields,
  starting at the fixture's own, and `[no place]` while it has one.
- `[done]` leaves edit mode.

### 6.6 The new fixture form

`[+ add]`, or `[add fixture here…]` on F8, shows the form (§3) in the panel:

1. `[profile…]` opens `ProfileDialog` (`widgets/profile_picker.py`): a filter, then a list with
   the maker, the name and the modes. The show's own come first, marked. ↑ ↓ move, Enter chooses,
   Esc cancels. It starts on the profile last chosen, else the first.
2. The mode chips show the footprint when there are several modes. The first mode is lit.
3. `number` and `count` with `[−]` `[+]`, and `[number…]` (§4 call 9). The line beside them shows
   the range. A taken number makes `[add]` inert and names it.
4. PATCH, as in §6.5, with `[none]` lit when the show has no universe.
5. `[add]` sends `fixture add 302 thru 305 "Generic Spot 16ch" mode "16ch" at 1.85`, then §4 call 10.

`[profile…]` on an existing fixture opens the same picker, then shows that profile's mode chips and
`[change]`, which sends `fixture 102 profile "RGB Par 3ch" mode "3ch"`.

### 6.7 Routes

- **`[+ route…]`** in ROUTES opens `RouteDialog` for the chosen universe, else the first:
  - chips for `sACN`, `Art-Net` and `DMX-USB`;
  - sACN: the sACN universe, starting at the show universe's number, then `multicast` or `unicast`
    with an interface or host;
  - Art-Net: `net.sub.universe`, then `broadcast` or `unicast`;
  - DMX-USB: `enttecPro` or `dmxking`, the port, and the rate.
- **A click on a ROUTES row chooses it.** The strip then shows the route, `[off]` or `[on]`, and
  `[delete]`. busk asks before `off` and `delete` (§5.1).
- To change a route, the operator deletes it and adds another: busk has no line that edits one.
- Refusals (an sACN universe another universe sends, a port in use) show in the log, as for every
  control.

### 6.8 Dialogs

`FormDialog` is new in `widgets/dialogs.py`: a title, labelled `Input`s, and a check over their
values that returns an error or `None`. Tab moves between fields, Enter runs the check, Esc
cancels. `TextDialog` stays for one field.

## 7. Steps

Baseline at `ab05ea3` (2026-11-05): `tests/tui` has 512 passed and 7 perf tests deselected, in 14
minutes. The whole suite last ran on 2026-11-05, before that commit was made, with the same
content: 4417 passed, 1 skipped, 20 deselected, in about 18 minutes on this host. Each step ends
with:

- the whole suite green;
- `ruff check`, `ruff format --check` and `mypy src` clean;
- from step 7, the TUI's new tests passing on Textual 8.2.0, the floor;
- a **Done** note under the step.

Use `uv run python -m pytest`. Each step is one commit, which the user makes. Each group below is
one conversation, which ends with a status memory and a stop. The engine's tests go in
`tests/test_console_parser.py`, `tests/test_console.py`, `tests/test_route_status.py` and
`tests/test_frontend.py`, as each step needs.

**A. Engine: routes and deletes**

1. **GAP-23, routes** (§5.1). Verify:
   - both lines on `OfflineShow` and on a running `LiveShow`: state `disabled`, then `ok`, then
     gone, and `undo` after each;
   - the same under `busk run` with processes (`tests/test_frontend.py`). The prototype ran
     in-process only;
   - `expected()` for `route ` and `delete route `, and an unknown id refused by name;
   - `confirmation()` for `delete route` and `route <id> off`, and `None` for `route <id> on`;
   - `list routes` marks a disabled route;
   - a universe freed of its routes and fixtures can be deleted with a plain `delete universe`.

   **Done** (2026-11-05). As planned, with these additions:
   - The questions are `Switch route r-1 of universe 1 off?` and `Delete route r-1 of universe 1?`.
     As with `output off`, they ask whatever the route's state, so a route already off still asks.
   - Each line is a labelled `BATCH` of one edit, so the reply and the undo step read `switched
     route r-1 off` and `deleted route r-1`, not a document path.
   - `route <id> on` can be refused: the validator skips a disabled route, so its sACN universe or
     port may be taken while it is off. The line then fails with the validator's message. F8 shows
     that in the log (§6.7).
   - `list routes` already marked a disabled route, for every protocol. It is now tested, not
     changed.
   - `tests/process_site/frontend_probe.py` has a new `steps` key: ask about a line, run it, wait for
     the routes and the frame's universes. Step 2 uses it too.
   - Two tests of `tests/test_console_prompt.py` used `route ` as a word with one completion, which
     it no longer is. They use `effect template ` now.
2. **GAP-24, deletes that cascade** (§5.2). Verify:
   - a case per kind on a fresh fixture: group, preset target value, cue entry, per-target values,
     cue effect, cue release, park, and a binding's `SELECT`, which the prototype did not cover. In
     each, the fixture goes and the other fixtures of that entity stay;
   - what goes and what stays: an entry, effect, release or binding left with no target goes, and a
     group, preset or cue left empty stays;
   - on every fixture of both shows: a valid show, and `undo` gives back an equal document. All 18
     in a row, then saved and reloaded;
   - a universe on a running show, under `busk run` too: fixtures unpatched, routes closed, frames
     stopped, and `undo`;
   - `confirmation()`: what it names, the programmer's note, and a line with nothing to cascade;
   - a plain `delete` stays refused.

   **Done** (2026-11-05). The edits are in a new pure module, `src/busk/console/cascade.py`, and its
   tests in `tests/test_cascade.py`. As planned, with these deviations and additions, which the
   user may veto:
   - **A group's layout follows.** §5.2 did not mention it. `layout.cells` holds positions in
     `members`, so a member leaving would point cells at the wrong member, or past the end, which
     the validator refuses. The fixture's cells go empty and the others follow their members. `record
     group` drops a layout instead, but here the shape is kept: one fixture left a matrix. Neither
     shipped show has a layout, which is why the prototype did not meet this.
   - **Every binding command that names the fixture, not only `SELECT`.** The validator also checks
     `PATCH_FIXTURE` and a `SET_ATTRIBUTE`'s per-target values, and looks inside a `BATCH`, so the
     line would otherwise be refused on such a show. `ADD_EFFECT` is covered too, though the
     validator does not check it, as §1 says every reference goes. The universe cascade removes a
     binding that patches into the universe.
   - **A per-target entry left with no value goes,** even when its targets are a group. So a cue that
     reaches the fixture through a group is touched in this one case: a per-target value for it.
   - Three kinds or more in a question are parted by `;`, since a kind has commas of its own: `It
     leaves groups 2, 4; cue 10/3 and 1 parked value.`
   - "The programmer holds it" means selected, with a value there, or named by an effect's targets.
     An effect on a group does not count: the group loses the fixture and the effect runs on.
   - An emptied `releases` stays as `[]`, which means the same as none.
   - `elementPatch` is not touched: a show with a split patch does not compile.
   - Beyond the list: a fixture cascade on a running `LiveShow` is a test too, and by hand, with two
     playbacks running and the programmer holding the fixture, both deletes and two `undo`s gave back
     an equal document, the output and the frames.
   - 31 mutations of `cascade.py` and 7 of the parser's lines for steps 1 and 2 were all caught.
   - Steps 1 and 2 were built in one working tree, so they share one run of the whole suite: 4524
     passed, 1 skipped, 20 deselected, in 17:51 (the baseline was 4417). Step 1 alone was not run
     whole. After that run, only two tests changed, to wait for quiet on the line instead of a
     fixed time. Their two files pass three times over, and those two tests under load on every
     core.

**B. Engine: the small gaps**

3. **GAP-25, removing a limit and a location** (§5.3). Verify:
   - one limit removed with the others kept, the last one taking `limits` with it, and `undo`;
   - `thru` over fixtures with and without that limit, and refused when none has it;
   - `location none`, refused without a location, and `undo`.

   **Done** (2026-11-05). As planned, with these additions:
   - `help` gained `fixture N location <location>` beside `none`. A form that fits hides the generic
     edit from `?`, so `none` would have been the only way it showed.
   - Tab offers `location` after a fixture, and `none` after `location` and after a limit's name,
     beside what else may come there.
4. **GAP-26, mode and profile** (§5.4). Verify, on a two-mode test profile:
   - `fixture N mode` and its completion, past 512 refused and an overlap warned;
   - `fixture N profile … mode …` to an embedded and to a library profile, `undo` taking the
     embedded profile back, and a 12-element bar refused while groups name its elements;
   - the show's copy used when the library's revision differs, as for `fixture add`.

   **Done** (2026-11-05). As planned, with these additions, which the user may veto:
   - The reply is `fixture 102 runs 3ch`, or `fixture 102 runs RGB Par 3ch, 3ch`, and the undo step
     has the same label.
   - `fixture add` now shares its parsing of `"<profile>" mode <mode>` with these lines
     (`_profile_and_mode`, `_mode`), so they take the same words.
   - A cue or a parked value on an element the mode lacks refuses the line too. §5.4 named groups
     only. Each was run.
   - What the programmer holds on a lost element goes dormant. `ProgrammerStatus` and the output are
     right, and `undo` brings it back, but the `programmer` line prints `selection: 1, 1, 1…`, one
     `1` per lost element. That is §8 item 4 again, so it was left.
   - Beyond the list: a running `LiveShow` follows a profile and `undo`, and so does the engine
     process under `busk run`, through a new `elements` key of the probe's `steps`.
5. **GAP-27, `fixture_profiles`** (§5.5). Verify:
   - its names equal `expected('fixture add 900 ')` on both shows, with a `--library` directory, and
     under `busk run`;
   - the same tuple until a profile changes, and a profile moving from `library` to `show` when
     `fixture add` embeds it;
   - the public API golden, `api_consumer.py` and the tested example in `docs/library.md`.

   **Done** (2026-11-05). As planned, with these additions:
   - `find_profile` in `busk.console.parser` is `fixture add`'s lookup, moved out of the parser's
     class as `find_template` was for GAP-15, so the list cannot drift from the line.
   - One difference from `expected()`, which §2 did not meet: for a renamed copy of a library
     profile, `expected()` offers both names, which find the same profile, and `fixture_profiles`
     lists it once, under the show's. On both shipped shows the names are equal, which a test holds.
   - As for templates, a profile is listed under the first name that finds it, and one no name
     finds is left out.
   - `busk.__all__` is now 41, and the golden's diff only adds.
6. **A bad escape** (§5.6). Verify: all four calls of §2 with `"back\slash"`, and that `"C:\new"`
   and a JSON `\"` still read as they did.

   **Done** (2026-11-05). As planned, with these additions:
   - A literal tab or other control character in a quote raised the same error, which §2 did not
     list, so it is refused too: `control character in a quote at column 7`. A bad escape reads `bad
     escape in a quote at column 25`, the column of its backslash. For a broken `\u12` it is the
     column of the `u`, where `json` stops.
   - A lone surrogate, `"\ud800"`, is read, then refused by the validator, so it raises nothing.
   - `docs/console.md` gained a note on names in quotes, which had none.
   - 46 mutations of the lines of steps 3 to 6. 44 were caught at once. One showed a missing test,
     since every profile had revision 1, and that test now catches it. The other showed a redundant
     `not embed` in `_profile`, which went.
   - Steps 3 to 6 were built in one working tree, so they share one run of the whole suite: 4643
     passed, 1 skipped, 20 deselected, in 17:59 (group A left 4524).

**C. Read and universes**

7. **Model, bridge, lines, names** (§6.1, §6.2, §4 calls 7, 17, 21). Verify:
   - conversion: the club's limits on 101 and 301, orientation, modes on both shows' profiles,
     `RouteView.id`, and `choices` from `fixture_profiles`;
   - `quoted` round trips: a double quote, a backslash, `\n` as typed, an accent and an emoji;
   - every new builder in the contract test, in order, on a copy of the club show;
   - `first_free` with gaps, a full universe and a block; `clashes` leaving out the fixture itself;
     `runs` with a gap, one number, and a fixture between that is not selected.

   **Done** (2026-11-06). As planned, with these additions, which the user may veto:
   - `Limits` and `Orientation` are small dataclasses of their own, and `Orientation` keeps busk's
     keys, so a panel can hand a key straight to `commands.orientation`. `ModeInfo` is shared by
     `ProfileInfo.modes` and the new `ProfileChoice`. `choices` carries no id: the TUI keys by what
     the operator types.
   - `route_add(universe, protocol, address, destination=None, hz=None)` takes the words
     `RouteView.address` and `.destination` already hold, so step 13's dialog has no new format.
   - The builders take `first` and `last` always, and `fixture_add(301, 301, …)` writes no `thru`.
   - F3 sorts in the page, not in `show_model`, so F1 C's plot and the other pages keep document
     order.
   - `_category_prefill` lost its `except ValueError` here, one step before step 9 removes it,
     because `quoted` no longer raises. A profile name with a double quote now has a category edit,
     escaped. `_add_line` in `pages/effects.py` and `_prefills` in `pages/surfaces.py` went with
     their `except`.
   - `location_prefill` is now `location(…).text`, and its parameter is `place`, since the builder
     has the old name.
   - The guide's "a name cannot hold a double quote" went, as it was no longer true. The rest of
     the guide waits for step 14. §4.6 of `docs/dev/tui/implementation-plan.md` still lists that
     refusal among the tests it asked for. It is left as a record of that plan.
8. **Dialogs and F8's universes** (§6.3 except the place, §6.8, §4 calls 9, 18). Verify:
   - `FormDialog`: Tab, Enter, Esc, and a refused value staying in the dialog;
   - a row click chooses and lights a universe, and the strip follows it;
   - add, rename and renumber through dialogs, one line each, with a taken number refused in the
     dialog, and the maps following a renumber;
   - `[delete]` on universe 1: busk's question with its counts, Yes sends, No logs "cancelled";
   - the pane cursor's stops at 150 and 99 columns;
   - end to end on the real engine, from controls only: add a universe, rename it, renumber it,
     delete it.

   **Done** (2026-11-06). As planned, with these additions, which the user may veto:
   - **F8 sorts its universes by number,** as `list universes` does. The plan asked this of F3 only
     (§4 call 17), but `[number…]` is what makes it show: a universe renumbered to 7 stayed above a
     new 2. The maps follow the same order.
   - `StripButton.note`: words among a strip's buttons, with no click and no pane cursor stop, for
     `U2 Balcony`. A note wider than the strip ends in `…`: wrapped, it put the rows `lines()`
     counted and the rows drawn out of step, so a click missed `[delete]`. Steps 11 and 13 can use
     it for their strips.
   - The table has a `▸` column, as in §3, beside the lit row. `next_number` is new in `dialogs.py`
     (§4 call 9). §6.3 says "next free" and §4 call 9 "highest plus one": this is the second.
   - `FormDialog` uses compact `Input`s, one line each, so step 10's six-field location stays short.
     Each field starts with its value selected, as `TextDialog`'s does, so typing replaces it.
   - The form's note lists the numbers taken, as F6's number dialog does.
   - Beyond the list, the end-to-end test also deletes universe 1 with the rig and its route on it,
     and `undo` brings all of it back.

   **Three bugs of `dialogs.py`, fixed here** (all older than this plan):
   - A name in busk's question was read as markup: a universe named `x[/]y` raised `MarkupError` and
     ended the TUI, and `[left]` vanished from the question. F6's own question had the same bug.
   - A long question was cut at the box instead of wrapping (`.question` was `width: auto`). This
     matters from here on, since §4 call 11 leaves the question as the only place that says what a
     delete takes.
   - `check_number` took `²`, which `isdigit` accepts and `int` refuses, so the dialog raised. It
     uses `isdecimal` now.

   Steps 7 and 8 were built in one working tree, so they share one run of the whole suite: 4716
   passed, 1 skipped, 20 deselected, in 19:35 (group B left 4643). The changed TUI test files and
   the new end-to-end test, 345 tests, pass on Textual 8.2.0. A real-terminal check on the club show,
   at 150 and 99 columns, drove the form, a universe named `x[/]y`, the strip and the delete
   question. 34 mutations of the lines of both steps were all caught.

**D. The FIXTURE panel**

9. **Edit mode, the panel's header, category, mode** (§6.4, §4 calls 1–3, 11, 15, 16, 22, 23).
   `[profile…]` comes with the picker, in step 12. Verify:
   - `[edit]` swaps the tables, hides the legend and stops the output read, and leaving restores
     them;
   - a click selects and chooses, Shift-click adds;
   - rename and renumber: one line each, and the choice following a renumber;
   - delete on the club's 101: busk's question, Yes and No, then the panel goes back to "click a
     fixture", and `undo` brings it back;
   - the category chips, and the mode chips on a two-mode test profile, with busk's refusal past
     512 in the log;
   - the layout at 150, 100 and 99 columns;
   - that no pre-fill builder is left unused.

   **Done** (2026-11-06). As planned, with these additions, which the user may veto:
   - **`[+ add]` is not there yet.** It comes with its form in step 12, as `[profile…]` does: a
     button with nothing behind it would mislead. So the header row holds the counts and `[edit]`,
     and the panel's hint reads "click a fixture". §4 calls 1 and 23 and §6.4 wait for step 12.
   - **F3 has no control for the patch until step 11.** §4 call 3 takes the pre-fill now, and PATCH
     comes later. The prompt takes the line meanwhile.
   - **A lit chip sends nothing** and is no pane cursor stop, through `StripButton.note`. busk spends
     an undo step on a line that changes nothing, and refuses `category none` on a profile with
     none, which §2 did not list.
   - The choice is the fixture clicked last, in or out of edit mode, and it stays through `[done]`.
     Only a click or the pane cursor chooses, so `[edit]` on a selection alone shows "click a
     fixture". The chosen fixture's number is lit in `RigTable`, beside the selection's `▸`, since
     the selected rows look alike and the panel may act on one of them.
   - The counts moved from the table's title to the header row, in both modes. A click reads
     `click selects, Shift-click adds`, and in edit mode as §3 has it.
   - `limits` is 12 cells wide, for `pan tilt int`. The columns go in the order type, mode, place,
     profile, so at 100 columns `RigTable` holds the number, name, patch and limits.
   - The chips are in `CATEGORY_COLORS`' order, so `beam` comes after `strobe`, unlike §3's picture
     and `expected()`. The contract test compares them as sets.
   - `FixtureTable` and `RigTable` share `identity_cells`, up to the patch.
   - Beyond the list: a click beside the table leaves the page where it is, and chips hidden for
     the next fixture are no stops. A strip keeps its buttons while it is hidden, so a two-mode
     fixture's chips would have stayed in the cursor's way.
10. **Limits, orientation, location** (§6.5, §4 calls 4, 12–14). Verify:
    - each limit through its dialog, `[none]`, `[no limits]`, and the dialog's refusals (low above
      high, an intensity over 100 %);
    - `thru` runs: 101 and 102 selected give one line, a gap gives two, and the fixture between
      stays unlimited;
    - the toggles lit from the document, a line per selected fixture, and the section absent on a
      par;
    - `[swap pan/tilt]` absent where a profile lacks pan or tilt;
    - location: a first location, a change with the F1 C plot following it, and `[no place]`;
    - end to end on the real engine: the stored limits, orientation and location of each.

    **Done** (2026-11-06). As planned, with these additions, which the user may veto:
    - **`[none]` shows when any fixture of the reach has that limit,** not only the chosen one, as
      `[no limits]` does. The row's value stays the chosen fixture's, so a row can read `none` beside
      a `[none]`.
    - **A removal leaves out a run with nothing to remove,** since busk refuses a span where no
      fixture has it (`fixture 101 thru 301 has no tilt limit`). A span with one that has it is
      fine: busk takes it from those.
    - **Orientation skips a fixture already at the value,** which would cost an undo step for
      nothing. A toggle sets the reach to the opposite of the chosen fixture's, so it also brings
      fixtures that differ into line.
    - `[invert pan]`, `[invert tilt]` and the offsets show per axis, which §4 call 14 left open. A
      scanner with pan alone shows `[invert pan]` and `pan offset`.
    - A fixture of the reach without the axis still gets the line, as §4 call 4 says: a limit on a
      par brings busk's warning to the log, and a swap on a fixture with pan alone is refused there.
    - `[limit…]` always sends, even with the values unchanged: with two fixtures selected, that is
      how the chosen one's limit reaches the other. An unchanged place sends nothing, since it
      acts on one fixture.
    - The form takes `from` equal to `to`, as busk does, and refuses only `from` above `to`. A limit
      past the profile's range is busk's warning, in the log. Its note gives the range.
    - `at most` takes `50` or `50%`. A decimal goes out in whole percent, as every level does.
    - `read_number` is new in `dialogs.py`, for a number of any sign: `float` also reads `nan` and
      `inf`, which it refuses. `Setting` is a row of the panel, for limits and offsets.
    - A stop's label says which row it is on (`tilt limit…`, `pan offset…`), since the pane cursor
      finds its place again by the label.

    Steps 9 and 10 were built in one working tree, so they share one run of the whole suite: 4784
    passed, 1 skipped, 20 deselected, in 25:23 (group C left 4716, in 19:35). The three new
    end-to-end tests take most of the added time, the limits one over two minutes. `ruff`, `ruff
    format`, `mypy src` and `mypy --strict tests/api_consumer.py` are clean. The changed fast test
    files, 233 tests, and the F3 end-to-end tests pass on Textual 8.2.0. A first run of the suite
    failed on `test_the_pane_cursor_moves_into_the_page_and_back`, which used F3's rows and
    `[patch…]`: its rows now start after `[edit]`, and its pre-fill half moved to F7's grand master.
    A real-terminal check on the club show at 150 and 99 columns drove the rig table, the limit
    form and its refusal, a `thru` line, and busk's delete question. At 100 columns it checked the
    layout, and at 150 by 26 rows, reached from F1, a name `x[/]y [left]` and the panel scrolling on
    its own. Of 69 mutations, 61 were caught at once. Seven showed a missing test, and each test now
    catches it: among them the pane cursor marking the hidden table, and an intensity limit of 0
    losing its `[none]`. The other showed a redundant guard in `stops()`, which went.

**E. Patch and add**

11. **PATCH and F8's place** (§6.3's place, §6.5, §4 calls 5, 6, 19). Verify:
    - the universe chips propose the first free run, `[next free]` and `[address…]`;
    - the `takes` line: free, overlap (`[patch]` live) and past 512 (`[patch]` inert);
    - `[patch]`, and `[none]` then `[patch]`;
    - a click on a free channel: nothing sent, the place drawn, `[patch 102 here]` sends one line,
      and the map redraws;
    - no selection, and two selected;
    - on a running show, under `busk run`: a patch reaches the DMX frame at the new address.

    **Done** (2026-11-06). As planned, with these additions, which the user may veto:
    - **PATCH is a widget of its own,** `widgets/patch_chooser.py`, since the panel and the form share
      it. Its choice follows the show until the operator makes one: the fixture's patch in the panel,
      the free room in the form.
    - **`[next free]` counts the fixture's own channels as taken,** so it gives a new place, as §3
      draws: 102 goes to 1.85 on the club show, not back to 1.17.
    - **The chip of the fixture's own universe gives back its patch,** not the first free run, so a
      wrong chip can be undone. §4 call 6 has every universe propose its free room.
    - **`[address…]` takes any address from 1 to 512,** on a universe with no room too, so an overlap
      stays the operator's to make. The `takes` line then reads it.
    - **The strip above the maps always holds its row,** with `click a free channel to place a
      fixture there` until a place is armed. Shown only then, it would push the map a row down under
      the mouse. It goes only when the show has no universe.
    - **`[patch 102 here]` gives way to `102 would go past channel 512`,** as `[patch]` goes inert
      (§4 call 6). An overlap stays live, and red in the preview.
    - The place's buttons are pane cursor stops, though only the mouse can arm a place (§4 call 19):
      once they show, the keyboard reaches them.
    - `DmxMap.place` takes the fixture too (`own`), so a fixture is not red on itself. `free_from` is
      new in `dmxmap.py`.
    - `pick_chips` in `options.py` is a chip that sends nothing. `_css` in `dialogs.py` is public now,
      as `dialog_css`, for the picker. A universe's chip shows 24 characters of its name, since a chip
      never wraps.
    - The test under `busk run` moves the fixture both ways, with F3's `[patch]` and with F8's place,
      through a new frontend, `tests/tui/tui_rig_frontend.py`.
12. **The new fixture form and the picker** (§6.6, §4 calls 7–10, 20). Verify:
    - the picker: the filter, ↑ ↓, Enter, Esc, a long list, and an empty result;
    - a library profile not yet embedded shows its footprint, and adding it embeds it;
    - number and count: a taken number in the range, stepping over it, and `thru` in the line;
    - after `[add]`, the next number and the next free address;
    - a show with no universe, and a full universe;
    - `[add fixture here…]` opens F3 at that address, and `[−]` `[+]` keep it;
    - `[profile…]` on an existing fixture, and `[change]`;
    - end to end on the real engine, on `busk.new_show`, from controls only: a universe, four pars
      with `thru` at an address, a rename, limits on two, one deleted, then `undo`;
    - the perf test's F3 case stays under its gate, or the change is measured against HEAD (perf
      has not been run on this host: the baseline comes first).

    **Done** (2026-11-06). As planned, with these additions, which the user may veto:
    - **The form starts with no profile:** `[choose…]`, `[add]` inert, and a `takes` line that reads
      `choose a profile`. §3 draws one chosen, but a default puts a wrong fixture one click away.
      From then on the form keeps the profile from one `[+ add]` to the next, and the picker starts
      on it.
    - **A click on a row leaves the form,** as §4 call 2 has a click always choose. `[+ add]` then
      starts a new form, which keeps only the profile and the mode.
    - **The form's `[done]` goes back to the panel,** whose own `[done]` leaves edit mode. So `[+ add]`
      from the live table takes two `[done]`s to get back to it.
    - `[+ add]` is inert while the form shows, so a stray click keeps what was set.
    - **After `[add]` the count stays,** beside the next number, which is the one after the block,
      stepping over what is taken, not the highest plus one.
    - **The next address is the first run that fits, counted from channel 1,** not the channels after
      the block added. So a block placed at 1.200 is followed by a proposal from the first room.
    - `[address…]` and F8's place hold the address when the count or the mode changes. `[next free]` or
      a universe chip hands it back to the room. The step asked this of F8's place only.
    - **`[cancel]` sits beside `[change]`,** which the plan did not have. The fixture's own profile
      and choosing another fixture also drop the change. The mode chips that send a line hide while a
      change shows. `[change]` is inert when the prompt has made the same change.
    - `widgets/fixture_form.py` holds the form. A taken number has its own row under `count`, so a long
      list is not cut.
    - The filter reads the maker and the name, each word in any order. PgUp and PgDn page the list. It
      is a Textual `OptionList` that never takes the focus.

    **Perf.** The baseline came first, and found that the gate already fails here: at `8003f96` the
    `busk run` test stops on F1 A at +0.265, before it reaches F3. So F3 was measured alone,
    alternating with `8003f96`, 18 runs each: +0.237 there, 6 runs over 0.25, and +0.247 here, 8 over.
    By phase, 9 runs each, the steady loop takes 0.238 core there and 0.231 here, and start-up 0.295 s
    and 0.323 s of CPU. So this group adds about 0.03 s at start-up, and nothing while it runs.

    The gate's number follows how long a run lasted, more than what it did.
    `tui_perf_frontend.py` starts its clock before the imports and divides by a fixed 8 s, and a run
    lasts 8 to 12 s (800 to 1200 ticks). Over the 36 runs, the number and the ticks correlate at 0.84:
    under 850 ticks it averages +0.210 with none over, and above 1050 it averages +0.268 with 6 of 7
    over. That fits the flapping noted since Phase 3. The gate and the harness are left as they are.

    Steps 11 and 12 were built in one working tree, so they share one run of the whole suite: 4891
    passed, 1 skipped, 20 deselected, in 31:44 (group D left 4784, in 25:23). `ruff`, `ruff format`,
    `mypy src` and `mypy --strict tests/api_consumer.py` are clean, and neither `src/busk/` nor the
    engine's tests changed. The changed test files and the new end-to-end tests, 267 tests, pass on
    Textual 8.2.0. F3 standalone keeps the engine's rate: 100.0 frames/s bare, 100.1 with the TUI. A
    first run of the suite failed on `test_the_pane_cursor_moves_into_the_page_and_back`, which counts
    F3's stops by position: `[+ add]` now comes first. A real-terminal check on the club show at 150
    columns drove PATCH, `[patch]`, F8's place with its red overlap, `[add fixture here…]`, the picker
    and `[add]` with a count, and at 99 columns the form under the table. The TupperDMX show waits
    for step 14. Of 105 mutations, 92 were caught at once. Ten showed a missing test, and each test
    now catches it. Three showed code with no use, which went: `OptionList` stops at its own ends, and
    `set_editing` can run twice.

**F. Routes**

13. **Routes on F8** (§6.7). Verify:
    - each protocol's line, and the dialog's checks, in the contract test;
    - a refusal in the log, such as an sACN universe another universe sends;
    - a click chooses a route, and `[off]`, `[on]` and `[delete]`, with busk's question before `off`
      and `delete`;
    - on a running show, a new route opens and its light goes green, `[off]` greys it, and `[delete]`
      takes the row away;
    - end to end from controls only: a new universe, a route, a fixture patched in it and seen in
      the frame, then the universe deleted.

    **Done** (2026-11-07). As planned, with these additions, which the user may veto:
    - **An interface left empty is left to busk,** and the line then has no destination, because the
      TUI cannot know `--iface`. `unicast` needs its host.
    - **Art-Net starts where it counts the show universe, from 0:** universe 1 is `0.0.0`, as on the
      TupperDMX show. §6.7 named only sACN's start. `docs/console.md`'s example has `0.0.1`.
    - **The port starts empty,** with `/dev/ttyUSB0` as a placeholder, since a default puts a wrong
      port one Enter away.
    - **The rate takes 1 to 40 Hz,** which is stricter than busk (§8 item 7). The prompt takes any.
    - **`commands.word` is new:** a typed interface, host or port goes in quotes when busk needs them,
      so `Ethernet 2` works. Route ids go through it too, as a show written by hand may hold any id.
    - The form is `widgets/route_dialog.py`. Its chips are `PickRow`, a `ButtonStrip` that takes the
      focus: Tab reaches it, ← → move it, and Enter runs the checks from there too. The focus starts
      on the protocol.
    - What was typed stays from one protocol to the next, and so does `unicast`. What was wrong goes
      with a change of chip.
    - The route added is not chosen (§4 call 18). The choice is held by id, as two routes may read the
      same, and the pane cursor's label has the id too.
    - With no universe, `[+ route…]` gives way to `a route sends a universe: add one first`.
    - `[off]` is amber and `[on]` green.
    - **The strip marks itself again when `[off]` becomes `[on]`.** `ButtonStrip.show` clears the mark,
      so the pane cursor went from sight just after busk's question. Only this strip does so.
    - **`address` is 9 cells, not 8,** for `enttecPro` and `127.15.15`. `destination` still goes first
      when narrow, as it did.
    - Beyond the list: the test under `busk run` drives the route too, through
      `tests/tui/tui_rig_frontend.py`, and the end-to-end test reads real sACN packets from a receiver,
      not only the frame. The refusal has a test of its own, on the club show with no output.

    The whole suite: 4971 passed, 1 skipped, 20 deselected, in 35:27 (group E left 4891, in 31:44).
    `ruff`, `ruff format`, `mypy src` and `mypy --strict tests/api_consumer.py` are clean, and neither
    `src/busk/` nor the engine's tests changed. The changed test files and the new end-to-end tests,
    279 tests, pass on Textual 8.2.0. A real-terminal check on the club show drove the form by mouse at
    150 columns (each protocol, a refusal, a route to 127.0.0.1 opening, `[off]`, `[on]` and `[delete]`
    with busk's questions) and by keyboard at 99, which is how the `address` column was found. The
    TupperDMX show waits for step 14.

    Of 82 mutations, 70 were caught at once. Three did not apply, by a mistake in the script. Two
    survived only because the run left their tests out. One showed a line with no use, which went: the
    screen focuses the protocol by itself. Six showed a missing test, and each test now catches it. So
    did one counted as caught, whose failure came from elsewhere. A second run recorded what caught
    each: 81 of 81, each by a test that fits.

    The new end-to-end test takes 130 s. On `Bridge.standalone` a step of a test takes about 3 s, at
    around a fifth of a core, and under `busk run` about 0.3 s. That holds with no output too, so it
    is not this step's, and the cause was not looked into.

    Afterwards, at the user's word, §8 item 6 was fixed. The next run of the suite failed on
    `test_the_packet_rate_and_a_steady_light_once_sending_stops`, older than this plan: alone, it
    failed 8 of 20 cold runs at `31074cd` and 10 of 20 here. It mixed a `now` of its own with the real
    clock of `update_view`, so a blink, which needs 0.25 s between two updates, never came back on. Of
    24 runs it failed exactly when it blinked, and a warm run of the file was too quick to blink. So
    it passed only where it did not reach what its name says. It now has a clock of its own and blinks
    every time: 30 of 30 cold runs pass, and it fails with the steady branch removed. The whole suite
    then: 4982 passed, 1 skipped, 20 deselected, in 35:49.

**G. Docs**

14. **Docs.**
    - `docs/tui/guide.md` F3 and F8, with mockups from the real terminal, and its dialogs section;
    - the help screen and the hint row, if a key or hint changed;
    - `docs/dev/tui/operations-report.md`: the fixture rows, the summary, "In short", "What busk is
      missing" (its items 4 and 6 and the routes, now closed), and the corrections of §8 item 5;
    - the TUI plan's §2.4 and §2.9 tables, with a pointer to this plan;
    - the changelog's `[Unreleased]`;
    - a real-terminal check (pty and pyte) on both shows at 150 and 99 columns. The driver can be
      recovered from transcript 188008bc.

    **Done** (2026-11-07). As planned, with these additions, which the user may veto:
    - **The report's item 6 is not closed, only narrowed.** The step says closed, but §9 leaves
      cascades for presets, cue lists and playbacks out, so it now reads that deletes cascade only
      for fixtures and universes. Item 4 is marked closed, and the numbers stay, since §9 cites item 6.
    - **The report had no routes item to close.** So item 8 records GAP-23 as closed, and item 9 is new:
      a route cannot be edited. Universes and routes have a table of their own, with the rows of §1,
      and a row in the summary. §8 item 5's corrections are a list under that table.
    - **No key or hint changed.** `help.py`, `frame.py` and `hints.py` are as they were at `ab05ea3`,
      so the help screen and the hint row have no edit. The empty tables' words (`no fixtures · fixture
      add 101 …`, `no universes · …`, `no routes · …`) still name the typed line beside the new
      controls. They are true, so they stay.
    - The guide's "Questions and quitting" is now "Questions, dialogs and quitting", and holds the
      forms and the picker. No link pointed at the old heading.
    - **The changelog also lists the three TUI fixes of steps 7 and 8** under `Fixed` (names sent
      escaped, a question read as markup and cut, the number dialog on `²`), which had no entry. They
      are user-visible, and §8 item 6 and §5.6 already had theirs.
    - The TUI plan's `doc` row now names `fixture_profiles`, beyond the two tables, since the new rows
      cite it. Those rows read `*(rig plan)*`, as F6's read `*(presets plan)*`.
    - **The mockups are captures, pasted by script at 132 columns.** F3 comes from the club show and
      F8 from TupperDMX, as before, because the club's route cannot open on this host (no `eth0`). One
      glyph was changed: F8's light shows `●`, the other half of its blink from the `○` captured. F8's
      empty rows are cut to `…`, as they were.

    The real-terminal check found no bug. TupperDMX, for the first time in this plan: at 150 columns by
    mouse, the panel on a moving head, busk's question and No, the limit, location and profile dialogs,
    `[invert pan]`, the form, a universe, the place, `[patch 101 here]` and `[add fixture here…]`, with
    `[add]`. At 99 by keyboard, edit mode, a real cascade on 501 and `undo`, then on F8 the route's
    `[off]`, `[on]`, both questions, and `delete universe 1 cascade`. The club show: at 150 a `thru`
    limit on two heads and the form with a count, at 99 the picker's filter, the form under the table,
    each protocol of the route form with a refusal, and a place with and without a selection. Every
    line the guide quotes was also run on `OfflineShow`.

    One thing seen, older than this plan and left alone: the log does not wrap (`wrap=False`), so at 99
    columns a long answer is cut at the edge, behind a horizontal scrollbar. TupperDMX's overlap warning
    shows it at start.

    The step changed no code and no test, so nothing new runs on Textual 8.2.0. The whole suite: 4982
    passed, 1 skipped, 20 deselected, in 34:20, as group F left it. `ruff`, `ruff format` and `mypy src`
    are clean.
15. **The user's:** on the rig, add a fixture from the library, patch it from F8's map, set a limit
    and an orientation on the heads, set a location, then rename, renumber and delete it; add a
    universe with a route, switch the route off and on, then delete both.

## 8. Found while planning (busk, not fixed here)

These block no step: the TUI checks first or offers only what works. They are for the user to
number in `docs/dev/tui/engine-gaps.md`, or not:

1. **Refusals in document paths.** `fixture add` past channel 512 prints one path per fixture, and
   `universe N number M` and `fixture N number M` name `universes[1]` or `fixtures[7]`. At the prompt
   the messages stay unclear.
2. **`thru` where it is not taken.** `fixture 900 thru 901 patch 2.1` replies `set fixtures[7].thru
   to "901 patch 2.1"`. The line reads as a generic property. `orientation` does the same. A `thru`
   on `orientation` would also make four heads one undo step (§4 call 4). That half is done
   (GAP-28, 2026-11-07), and F3 sends a `thru` line per run. `patch` still reads as a property.
3. **Fixture numbers are not checked:** `fixture add 0` and `fixture add -5` work, while a universe
   starts at 1.
4. **`programmer` prints `fx-… (gone)`** for a deleted fixture, selected or in an effect, while
   `ProgrammerStatus` leaves it out. The presets plan's §7 item 3 is the same thing for a preset.
5. **The report needs correcting** (step 14, not a busk change):
   - `delete universe` is refused by routes too;
   - the mode could already be changed with `modeId`;
   - orientation has no row;
   - `expected()` gives a picker its names but no footprint.
6. **A digit `int` cannot read ended a line, and with it `busk run --threads`** (found at step 13,
   fixed 2026-11-07 at the user's word, so this one change to `src/busk/` comes after step 7).
   `isdigit` takes `²` and `①`, and `int` refuses them, so `route add 1 artnet 0.0.²`, `bind … page ²`
   and `surface add osc "L" port ²` raised `ValueError` out of `execute()` and `confirmation()`, and
   out of `expected()` once a word followed. At the prompt of `busk run --threads` that ended the run,
   with a traceback and exit 1. With processes the console restarted (exit 70) and the engine ran on.
   Under the TUI the bridge caught it. All three now use `isdecimal`, and each is a refused line. The
   OFL importer's `eachPixelABC` sort had the same mistake, on a pixel key such as `1²2`, and it is
   fixed the same way. A sweep of 55,117 lines from the tests and examples, with their numbers swapped
   for such digits, raised 276 times before and never after.
7. **`hz` takes any number** (found at step 13). `route add 1 dmxusb enttecPro /dev/ttyUSB0 hz 0`,
   `hz -1` and `hz 1000` are stored, and `output_rate` then keeps the widget to 1–40 Hz without a
   word. The model's comment says 44. F8's form takes 1 to 40.
8. **A number past 4,300 digits raised** (found fixing item 6, fixed 2026-11-07 as GAP-30, by one
   check in `tokenize` and a cap on cue numbers, at the user's choice). `int` refuses it, so
   `ValueError` leaves `execute()`, as in item 6, for an Art-Net address, a surface's port, `bind …
   page`, `goto`, `cue` and `record slot`. `integer()` already catches it, so `route add 1 sacn` does
   not. It takes a bad paste, not a slip. Nothing between a line and the prompt catches what a line
   raises, so one guard there would cover this and whatever comes next, at the cost of showing a
   real bug as a refused line. That is a design call for the user.

## 9. Not in this plan

- Groups. A new fixture joins no group, and `record group` stays at the prompt. This is the likely
  next step.
- `park` and `unpark`, beyond what a cascade removes.
- Cascades for presets, cue lists, playbacks and pages (the report's item 6). A fixture and a
  universe are what F3 and F8 delete.
- Editing a route in place: it is deleted and added again (§6.7).
- Deleting or patching several fixtures at once. busk takes one per line, and several lines would
  be several undo steps that can part-fail.
- F1 C's `[location…]`, which keeps its pre-fill. It could take the new dialog in one line later.
- Importing a profile (`busk import`) or `profile update`.
- A split patch: busk refuses them at compile.
- Editing in the table's cells (the TUI plan's §8).

## 10. Questions

Both were open when the plan was first written. The user's instruction of 2026-11-05, that the
engine gaps come first so that the whole plan can be built, settles them:

1. **Routes.** A universe sends nothing without a route, and nothing in busk removes a route, so a
   universe with one cannot be deleted.
   - (a) Number a gap and build it first.
   - (b) Only `[+ route…]`, no engine work.
   - (c) Routes stay at the prompt.

   ANSWER: (a), as step 1. The user named this gap.
2. **Deleting a fixture that something uses.** On the shipped shows that is all 18 of them.
   - (a) Inert, with the users named, as F6 does.
   - (b) Number a gap first: `delete fixture N cascade`, one undo step, with a question that lists
     what goes.
   - (c) (a), plus a `[leave groups]` control on F3.

   ANSWER: (b), as step 2. This is the plan's reading of the instruction: only (b) lets `[delete]`
   work on a fixture in use. The prototype answered what (b) left open: a group, preset or cue left
   empty is valid, so it stays.
