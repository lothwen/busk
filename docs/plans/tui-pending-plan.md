# Pending TUI and engine work: implementation plan

> Source: the user's request of 2026-11-08, to gather what is still pending and order it in
> phases, one conversation each. Written at `d628286`. It draws on five places:
> `docs/dev/tui/operations-report.md` ("What busk is missing", "What the TUI is missing" and "Side
> findings"), `docs/plans/tui-rig-plan.md` §9, and what the last conversation left open. §5 holds
> the plan's own calls, which the user may veto, and §8 the questions only the user can answer.

## 1. How a phase runs

- **One phase, one conversation.** A new phase starts a new conversation, which reads this
  section, its phase in §6 and the files the phase names. A phase relies on the code and on the
  Done notes of the phases before it, not on what another conversation remembers.
- **Size.** The six build conversations of the rig plan (groups A to F) added 68 to 119 tests
  each. Every phase here is sized to that or less.
- **Engine first.** Phases 2 to 5 give every later control its line, so no control is left inert
  or waiting on busk. Phase 14 is the one exception: a question gates it, nothing else needs it,
  and its engine step comes first inside the phase.
- **Engine phases** change `src/busk/` and its tests. Each gap gets an entry and a Summary row in
  `docs/dev/tui/engine-gaps.md`. A wrong message or a missing range check is a bug, not a gap, and
  gets no number.
- **TUI phases** keep the rules of `docs/dev/tui/implementation-plan.md` §1: no change to
  `src/busk/` or to the engine's tests, only `bridge.py` imports `busk`, every action is a console
  line sent through `LiveShow.execute()`. A gap found in a TUI phase is written down, and the TUI
  never works around it.
- **One control, one line.** Two lines are two undo steps that can part-fail (rig plan §9). Where
  a control would need two, an engine phase gives it one.
- **Destructive controls ask.** This settles the report's second side finding. `confirmation()`
  asks before a `cascade`, `delete route` and `route <id> off`, and nothing before a plain
  `delete`, a `record … replace`, a `record … remove` or `effect clear`. A control that sends one
  of those passes `RunLine.ask`, as F6's `[delete]` does.

Every phase ends with:

- the whole suite green with `uv run pytest -n 6` (about 3 minutes);
- `ruff check`, `ruff format --check` and `mypy src` clean;
- in a TUI phase, its new tests passing on Textual 8.2.0, the floor, at least one new test in
  `tests/tui/test_tui_e2e.py` on the real engine, and the perf gate (`uv run python -m pytest -m
  perf tests/tui -s`) when a page's update path changed;
- a real `busk run` for anything that acts on a running show, always with `--state-dir` in a
  temporary directory;
- its docs: the report's rows and sections it closes, `docs/tui/guide.md` or `docs/console.md`,
  and `CHANGELOG.md`;
- **Done** notes under its steps, a status memory, and a stop. The user commits.

Baseline at `d628286` (2026-11-08): the whole suite, 5,113 passed and 1 skipped, in 3:06 with
`uv run pytest -n 6`.

## 2. Everything gathered

Each pending item, what it is at `d628286`, and where it goes.

| From | Item | At `d628286` | Goes to |
|---|---|---|---|
| busk missing 1 | Delete, change or rename an effect template | open | Phase 2, GAP-31 |
| busk missing 2 | A playback for an existing list; another list by number | open | Phase 3, GAP-34 |
| busk missing 3 | Remove one effect from a cue by its id | open | Phase 2, GAP-32 |
| busk missing 4 | A fixture's mode and profile | closed (GAP-26) | nothing |
| busk missing 5 | An empty cue list | open | Phase 2, GAP-33 |
| busk missing 6 | Deletes that cascade for presets, cue lists, playbacks | open | Phase 4, GAP-36 |
| busk missing 6 | One entity per line | open for fixtures (rig §9 below); the rest stays (§7) | Phase 5, GAP-38 |
| busk missing 7 | Playback and cue list settings named by `help` and `expected()` | open | Phase 3, GAP-35 |
| busk missing 8 | Removing and switching a route | closed (GAP-23) | nothing |
| busk missing 9 | Editing a route | open | Phase 5, GAP-37; F8 in Phase 13 |
| TUI missing, F1 | The playback's own buttons | open | Phase 9 |
| TUI missing, F1 | `record slot` on an empty slot | open | Phase 9 |
| TUI missing, F4 | Delete a cue, re-record it, record at a number, release targets | open | Phase 6 |
| TUI missing, F4 | New list; delete, rename, tracking and chase settings of a list | open | Phase 6 |
| TUI missing, F5 | Edit an effect's settings; `effect clear` | open | Phase 7 |
| TUI missing, F5 | Add a template | open | Phase 8 |
| TUI missing, Playbacks | View and edit their configuration | open | Phase 10 |
| TUI missing, Playbacks | Add and delete one; page slots | open | Phase 11 |
| Side finding 1 | `record cue L/C remove` replies `0 effects` | **fixed** in `4abcf1f`, checked: `removed 0 values, 1 effect from cue 90/1` | Phase 1 takes it out of the report |
| Side finding 2 | `confirmation()` asks nothing before most deletes | open | rule in §1, applied by Phases 6, 7, 12 |
| Rig §9 | Groups | open | Phase 12 |
| Rig §9 | `park` and `unpark` | open | Phase 12; GAP-22 in Phase 5 |
| Rig §9 | Cascades for presets, cue lists, playbacks, pages | open, as above | Phase 4, GAP-36 |
| Rig §9 | Editing a route in place | open, as above | Phase 5, GAP-37; F8 in Phase 13 |
| Rig §9 | Deleting or patching several fixtures at once | open | Phase 5, GAP-38; F3 in Phase 13 |
| Rig §9 | F1 C's `[location…]` | open | Phase 1 |
| Rig §9 | Importing a profile; `profile update` | open | Phase 5, GAP-39; F3 in Phase 13 |
| Rig §9 | A split patch | open | Phase 14, if Q4 says so |
| Rig §9 | Editing in the table's cells | open | Phase 15, if Q5 says so |
| Last conversation | Refusals with a document path: `group N number M`, `route add 1 sacn 0`, a mode or profile past channel 512 | open | Phase 1 |
| Last conversation | The same for a plain `delete fixture N` | open | Phase 4, GAP-36 |
| Last conversation | The log does not wrap | open: `LogView` is built with `wrap=False` | Phase 1 |
| Last conversation | A step on `Bridge.standalone` takes about 3 s | **closed** by `d628286`: Textual's idle wait counted the engine thread's CPU and ran to its 1 s cap. `test_tui_e2e.py` went from 1,255 s to 107 s | nothing |
| Last conversation | A show with `refreshHz` 41 to 44, or a fixture below 1, no longer loads | open: the user's call | Q1, Phase 1 |
| Last conversation | The other decisions in the Done notes | stay as built unless vetoed: rig plan §4, its Done notes, and the Fixed notes of §8 and §11 | the user |

## 3. The phases at a glance

| Phase | Builds | Changes | Needs | Question |
|---|---|---|---|---|
| 1 | Loose ends: the log wraps, one-line refusals, F1 C's dialog | busk, TUI | | Q1 |
| 2 | Lines for templates, a cue's effect, an empty list | busk | | |
| 3 | Lines for playbacks, and their settings named | busk | | |
| 4 | Deletes that cascade, and refusals in words | busk | | |
| 5 | Route edit, several fixtures, profile import, parked values | busk | | |
| 6 | F4: cue and cue list controls; F6's delete | TUI | 2, 4 | |
| 7 | F5: an effect's settings, clear, remove from a cue | TUI | 2 | |
| 8 | F5: the template editor | TUI | 2 | |
| 9 | F1: the playback's own buttons, `record slot` | TUI | | Q3 |
| 10 | Playback configuration | TUI | 3 | Q2 |
| 11 | Adding and deleting playbacks, page slots | TUI | 3, 4, 10 | Q2 |
| 12 | Groups and park | TUI | 4, 5 | |
| 13 | Rig extras: route edit, several fixtures, profiles | TUI | 5 | |
| 14 | Split patch | busk, TUI | | Q4 |
| 15 | Cue cell editing | TUI | 6 | Q5 |
| 16 | Audit, and the user's check on a rig | docs | all | |

## 4. What busk does (checked on 2026-11-08)

Run on `OfflineShow` with `examples/club-night.busk`, through `submit()` where no line exists yet.

**Accepted, and valid:**

- an empty cue list, a playback on it, and pointing a playback at another list (`SET cueListId`);
- `DELETE` of one effect of a cue, which leaves a cue with no effects and no entries;
- `SET` of a template's `name` and `layers`, while a plain `DELETE` of a used template is refused;
- as one `BATCH`, the delete of every preset of the show in a row, each taking the cue entries
  that name it; a cue list with its playback and page slot; a playback with its page slot;
- `SET` of a route's `universe` and `destination`;
- `ADD` of a library profile to `profiles`, which `fixture_profiles` then lists as `source="show"`.

**Traps the steps must handle:**

- `SET` of a template's name takes one another template has. The line must refuse it, as
  `effect template add` does.
- `playback 1 exclusivity none` stores the word `none`. No line removes an optional property.
- `delete page 1` goes through on this show, and deleting the last page leaves a show with no
  pages, which is valid. A `pageAbs` binding or an `ASSIGN_PLAYBACK` command can name a page.
- `FixtureProfileInfo` has no revision, so nothing tells a control that `profile update` has
  something to do.
- 18 of the show's 20 playbacks have no `go` button (`toggle` first), and F1 shows GO on all of
  them today (Q3).

**Not prototyped, so the phases check them:** all of the above on a running show; an effect
palette entry that names a preset; a group master; a binding that names a deleted page; a
playback pointed at another list while it runs.

## 5. Calls the user may veto

1. **GAP-31 to GAP-40** are numbered here, in the order they are built. GAP-22 already exists.
2. **A preset's cascade drops the cue entries that use it,** as GAP-24 does for a fixture. It does
   not write the preset's value into the cue. busk's question names the cues, and `undo` brings
   everything back.
3. **A used template stays refused.** `effect template delete` names what uses it. No cascade.
4. **`playback add` takes `at [P.]S`,** so adding a playback and placing it is one line.
5. **An imported profile goes into the show,** as one undo step, and not into a library directory.
   F3's picker already lists the show's profiles first. `busk import` stays as it is.
6. **Groups live in F3's edit mode, and park on F7 and F3's FIXTURE panel.** A new fixture joins a
   group by `[merge]` with it selected. The add form does not join one.
7. **Several fixtures act as one only when the selection is one run** (`thru`). Other selections
   leave `[delete]` and PATCH grey, since several lines would be several undo steps.
8. **F6's `[delete]` stops being inert** on a preset in use, and sends the cascade after busk's
   question.
9. **The generic edit keeps its paths** in a refusal: the path is what the operator typed.

## 6. Phases

### Phase 1: Loose ends

Small and independent. Code: `src/busk_tui/widgets/log.py`, `src/busk/console/parser.py`,
`src/busk_tui/pages/busk_stage.py`, `src/busk_tui/widgets/fixture_panel.py`.

1. **The log wraps.** Wrap at the pane's width, with later rows starting under the text, not the
   prefix, and flow the kept `entries` again on a resize. Verify: a 300-character reply at 99
   columns shows every word; each prefix; a resize; `entries` keeps one item per line; the perf
   gate.

   **Done** (2026-11-08). `log_rows` in `src/busk_tui/widgets/log.py` wraps with Rich's own word
   wrap, and `LogView` passes each row to `RichLog.write` at the pane's width. `entries` is
   unchanged; `_firsts`, beside it, remembers which lines start an error's reply, so a reflow marks
   them as before. A reflow is one write: a full log of 2,000 lines takes 0.2 to 0.3 s, and only
   then. It lands on the newest line, as every write of `RichLog` does, even when scrolled back.
2. **Refusals in one line** (bugs, no gap number), checked first in the parser, as `fixture N
   number M` is:
   - `group N number M` and every other numbered entity that still prints a path (`_renumber`);
   - `route add` with an sACN universe outside 1 to 63999 (`_cmd_route`);
   - `fixture N mode|profile` past channel 512 (`_fits`, as `fixture N patch` does).

   **Done** (2026-11-08). As planned, for `group`, `cuelist`, `playback`, `page` and `preset`. Added,
   which the user may veto:
   - `cue L/C number M` prints no path either: `cue 1/2 exists`, `cue 1/1 cannot pass cue 1/2`. It
     takes the number bare, so `cue 1/1 number 1.5` now works; before it needed quotes.
   - Only fixtures and universes refuse a number below 1, as before. The model lets the others
     have one.
   - The test of a lost element in `tests/test_fixture_mode.py` now uses a mode that fits: the
     parser answers first when a mode also runs past channel 512.
3. **F1 C's `[location…]`** opens F3's six-field dialog in place of the pre-fill. Move
   `FixturePanel.ask_location`'s form to where both can call it, and remove
   `commands.location_prefill` if nothing else uses it.

   **Done** (2026-11-08). The form is `open_location_form` in the new
   `src/busk_tui/widgets/location_form.py`, with `PLACE` and `check_place`. Both controls open it,
   and `commands.location_prefill` is gone.
4. **Q1's answer.** Under (a) nothing changes. Under (b), see Q1.

   **Done** (2026-11-08), (b). `Fixture.number` is an `int` again and `refreshHz` takes up to 44.
   The semantic pass warns for a number below 1 and a rate past 40, so `busk validate`, `busk run`
   and the TUI's log all say it, once, at the load. `output_rate` already ran such a route at 40.
   Which the user may veto:
   - Only the range Q1 names came back. A rate below 1 or past 44 still fails with `ShowLoadError`,
     though busk took those too before `ace5bb3`.
   - The file keeps its 44, and `list routes` prints it, as it did before `ace5bb3`.
   - `fixture N number`, `fixture add`, `route add` and the forms go on refusing new ones, and
     `undo` can bring an old number back. The generic `show output.routes […]` takes 41 to 44 with
     the same warning: the check is the file's. `show fixtures […]` cannot replace the list.
5. **The report.** Take out the first side finding (fixed in `4abcf1f`), and note in its status
   line that this plan now tracks what is left.

   **Done** (2026-11-08). Also its Location row and "In short", which still named F1 C's pre-fill.

**Phase 1 checks** (2026-11-08). The whole suite: 5,169 passed and 1 skipped, in 3:21 with `uv run
pytest -n 6`. `ruff check`, `ruff format --check` and `mypy src` clean. The five TUI test files the
phase touched, 359 tests, pass on Textual 8.2.0. The perf gate: 7 passed, no overruns. A real `busk
run --state-dir …` on a show with fixture 0 and a route at 44 Hz printed both warnings, gave each
refusal in one line, renumbered fixture 0, and `undo` brought it back. The new tests on the real
engine are in `tests/tui/test_tui_e2e.py`: F1 C's form, a one-line refusal with a long answer
wrapped at 99 columns, and an old show opening.

### Phase 2: Engine: templates, a cue's effect, an empty cue list

Code: `_cmd_effect`, `_template_add`, `_cue_effect` in `src/busk/console/parser.py`. Tests:
`tests/test_console_parser.py`, `tests/test_console.py`.

1. **GAP-31, effect templates.**
   - `effect template delete "<name>"`: refused in one line while a cue or the programmer uses it,
     naming them, and for a library template the show has no copy of.
   - `effect template rename "<old>" "<new>"`: refuses a name the show has (§4).
   - `effect template update "<name>" <JSON layers>`: replaces the layers, read as `add` reads them.

   Verify: each line and its `undo`; `expected()` at every position; a used template; a duplicate
   name in any case; saved and reloaded; `update` on a running show with the template's cue active.

   **Done** (2026-11-08). As planned, in `_effect_template` of `src/busk/console/parser.py`. A
   template is found as `effect add` finds it. Each line is a labelled `BATCH`, so the reply and
   `undo` read `renamed effect template 'Pulse' to 'Beat'`. Which the user may veto:
   - A binding counts as a user, which the plan did not name. A binding can hold an `ADD_EFFECT`,
     and the validator does not check that reference, so a delete would break the control.
   - The refusal names cues by number and counts bindings: `template 'Pulse' is used by cues 12/1,
     20/1, 1 binding and the programmer`.
   - `rename` and `update` refuse a library template the show has no copy of, as `delete` does.
   - A bad `update` is refused by document path, as `effect template add` is (§5, item 9).
2. **GAP-32, a cue's effect.** `cue L/C effect <id> remove`. Verify: one undo step; `expected()`
   offers `remove` after the id; an unknown id refused by name; the cue left empty stays; the cue
   active on a running show.

   **Done** (2026-11-08). As planned, in `_cue_effect`. It replies `removed effect fx1 from cue
   11/1`. On a running show the effect leaves and the cue stays active.
3. **GAP-33, an empty cue list.** `cuelist add N ["name"]`, built with `_cue_list`. Verify: a taken
   number refused in one line; `record cue N` then appends cue 1; `list cuelists`; `go` and `goto`
   on a playback that runs an empty list say so and do not raise.

   **Done** (2026-11-08). As planned, in `_cuelist_add`. Which the user may veto:
   - `go` is refused by the parser: `cue list 10 has no cues`. It raised nothing before, but replied
     nothing and marked the playback active on no cue. `goto` already said `no cue 1 in cue list
     10`.
   - A bound control's `GO`, and `button N B on` on a `go` button, still mark it active on no cue.
     The engine runs on. Phase 9's strips send `button`, so they will meet this on an empty list.
   - A number below 1 is taken, as `page add` takes one.

**Phase 2 checks** (2026-11-08). The whole suite: 5,238 passed and 1 skipped, in 3:11 with `uv run
pytest -n 6`. `ruff check`, `ruff format --check` and `mypy src` clean. A real `busk run --state-dir
…` with processes on the club show: `go 11`, then each new line and refusal at the prompt, 0 command
errors. Docs: `docs/console.md`, `busk help`, GAP-31 to GAP-33 in `docs/dev/tui/engine-gaps.md`, the
report's rows and items 1, 3 and 5, and `CHANGELOG.md`.

### Phase 3: Engine: playbacks

Code: `_playback`, `_set`, `_goto_cue`, `_assign` in `src/busk/console/parser.py`. Tests as Phase
2, and `tests/test_frontend.py` for a running show.

1. **GAP-34, a playback for a list.**
   - `playback add N cuelist L [at [P.]S] ["name"]`: `_playback`'s defaults, on an existing list,
     placed on a page in the same undo step when `at` is given.
   - `playback N cuelist L`: another list, by number.

   Verify: a taken number or slot, and an unknown list, refused in one line; `undo`; `playback N
   cuelist L` while it runs, on `LiveShow` and under `busk run`. If the engine does anything but
   release cleanly, the line refuses while the playback is active and says so.

   **Done** (2026-11-08). As planned, in `_playback_add` and `_run_list` of
   `src/busk/console/parser.py`. The engine does not release: `rebind` keeps a running playback
   going from the cue that follows the old cue's number, and `undo` then lands on another cue. So
   `playback N cuelist L` refuses while it is active or releasing, `playback 1 is running: release
   it first`, through a new `Context.running` that `Console._running` reads from the engine's
   snapshot. Which the user may veto:
   - A new playback is named `Playback N` and has a `master` fader. `record slot`'s `size` fader
     for a cue of effects only is not copied.
   - The generic `playback N cueListId "<id>"` keeps working, and is guarded the same way.
   - A `gotoCue` the new list lacks stays a warning, as the validator has it.
   - The check reads the last snapshot, so a line sent straight after a `go`, before the engine's
     next snapshot, goes through.
2. **GAP-35, settings named.** At the property position of `playback N ` and `cuelist N `,
   `expected()` offers the names, and a closed set offers its values (`playback N fader `, `…
   ltpFaderMode `, `cuelist N tracking `). `help` and `docs/console.md` list them. `<property>
   none` removes an optional one (`exclusivity`, `gotoCue`, `uiColor`, `flash.priorityBoost`), as
   GAP-25 did for limits. An unknown name is refused in one line. Verify: a test walks the names
   offered against `Playback` and `CueList`, so the list cannot drift from the model; a JSON value
   still works; the Tab completion tests that pin `playback N ` and `cuelist N `.

   **Done** (2026-11-08). As planned, in `_setting` and the table `_SETTINGS`. The test walks the
   two models' types, so a new property fails until it is named in the table, in `help` and in
   `docs/console.md`. Which the user may veto:
   - `none` also removes `chase`, `notes` and `tags`: every optional property of the two models,
     not only the plan's four. `chase none` is refused on a list in chase mode.
   - A name is taken in any case, as `orientation.*` is.
   - A word outside a closed set is still refused by document path (§5, item 9). Only the offer is
     new.
   - `gotoCue` takes a bare cue number, through `goto`'s line, which also refuses a cue the list
     lacks. The generic edit read `2` as a JSON number and refused it. In quotes it stays the
     generic edit, and a cue the list lacks is a warning.
   - `id`, `cueListId`, `flash`, `cues`, `chase.rate`, `chase.rate.kind` and `chase.rate.masterId`
     are taken but not offered: other lines set them, by number, or they hold a whole object.

**Phase 3 checks** (2026-11-08). The whole suite: 5,349 passed and 1 skipped, in 3:33 with `uv run
pytest -n 6`. `ruff check`, `ruff format --check` and `mypy src` clean. `tests/test_frontend.py`
runs the guard under `busk run` with processes. A real `busk run --state-dir …` with processes on
the club show: `go 11`, the refusal, `release 11 0`, then each new line, `go` on the new list, and
`undo` at the prompt, 0 command errors. Docs: `docs/console.md`, `busk help`, GAP-34 and GAP-35 in
`docs/dev/tui/engine-gaps.md`, the report's rows and items 2 and 7, and `CHANGELOG.md`.

### Phase 4: Engine: deletes that cascade

One gap, five kinds. Code: `src/busk/console/cascade.py` and `_cmd_delete`. Tests:
`tests/test_cascade.py`, `tests/test_console.py`.

1. **GAP-36, cascades.** `… cascade` on each kind, under GAP-24's rule: what names the entity
   leaves it, what is left with no target goes, and a group, preset or cue left empty stays.

   | Line | What goes with it | What stays |
   |---|---|---|
   | `delete preset <pool> N cascade` | cue entries, effect palette entries and binding commands that use it | the cues |
   | `delete cuelist N cascade` | the playbacks that run it, each as the next row | |
   | `delete playback N cascade` | its page slots, `playbackFaderAbs` bindings and binding commands that name it | its cue list; bindings by slot |
   | `delete group N cascade` | cue entries, effects and releases that target it, a group master, binding commands | |
   | `delete page N cascade` | `pageAbs` bindings and `ASSIGN_PLAYBACK` commands that name it | its playbacks |

   Verify, for each kind: every entity of both shipped shows, valid, and `undo` gives an equal
   document; all in a row, then saved and reloaded; `confirmation()` names what goes and says when
   a playback is running; an effect left with no palette; on a running show and under `busk run`.

   **Done** (2026-11-08). As planned, in `preset_cascade`, `group_cascade`, `cue_list_cascade`,
   `playback_cascade` and `page_cascade` of `src/busk/console/cascade.py`. A cue list's playbacks
   are walked as one set, or two on one page or in one `BATCH` binding would be two edits of the
   same place. Which the user may veto:
   - **An effect left with no palette refuses the line**, with `cascade` too: `preset color 3 is
     the last colour of a palette of effect template "Solid": change the template first`. The
     validator refuses a colour layer with no colour, and §5, item 3 keeps a used template out of
     cascades. Neither shipped show has a palette that names a preset. The other way would be to
     drop the layer, or the template and the cue effects that use it.
   - `PAGE` by number goes with its page, which the table did not name: it is `pageAbs` as a
     command.
   - A group's master takes what drives it: a `master` binding and `SET_MASTER`.
   - The question and the reply give the entity's name, as a universe's do: `Delete preset color 1
     "Blue"? It leaves cues 3/1, 9/1.` The programmer is not mentioned: what it holds of a deleted
     preset goes dormant, as it did.
2. **Refusals in words.** A plain `delete` of a used fixture, universe, preset, cue list, playback,
   group or page prints one line, counted from the same walk as the cascade: `fixture 101 is used
   by 2 groups, 2 presets and 14 cues: add cascade`.

   **Done** (2026-11-08). As planned: `Cascade.refusal`, which `_cmd_delete` raises. At `delete
   group 1 ` Tab offers `cascade`, and `expected()` says the line is not runnable as it stands.
   Which the user may veto:
   - The walk, not the validator, decides. So a plain `delete` is also refused for what the
     validator only warns about or never checks: a page named by a `pageAbs` binding, and a fixture
     named only by an `ADD_EFFECT` binding. Both went through before.
   - A cue list counts the pages and bindings of its playbacks too: `cue list 9 is used by 1
     playback and 2 pages: add cascade`, as the cascade's reply does.
   - The generic edit keeps its paths (§5, item 9), so `docs/console.md`'s example of a refusal by
     path is now a `group N members` edit.

**Phase 4 checks** (2026-11-08). The whole suite: 5,420 passed and 1 skipped, in 3:19 with `uv run pytest -n 6`. `ruff
check`, `ruff format --check` and `mypy src` clean. 34 mutations of `cascade.py` and `_cmd_delete`,
all caught. `tests/test_cascade.py` deletes every group, preset, cue list, playback and page of both
shipped shows with `undo`, and all of them in a row in two orders, saved and reloaded. A real `busk
run --state-dir …` with processes on the club show: `go 11`, each refusal, then `delete playback 11
cascade` and `delete cuelist 12 cascade` while they ran, the preset, the group, the current page,
each with `undo`, 0 command errors and 0 overruns. Under `busk run` the running playback's question
and its going are in `tests/test_frontend.py`. Docs: `docs/console.md`, `busk help`, GAP-36 in
`docs/dev/tui/engine-gaps.md`, the report's rows, "In short" and item 6, and `CHANGELOG.md`.

### Phase 5: Engine: routes, several fixtures, profiles, parked values

Code: `_cmd_route`, `_cascade`, `_patch`, `_cmd_profile` in
`src/busk/console/parser.py`; `src/busk/console/console.py` for `FixtureProfileInfo`. Tests add
`tests/test_route_status.py`.

1. **GAP-37, editing a route.** `route <id> change <what route add takes>`: one undo step that
   keeps the id and whether it is on, and refuses what `route add` refuses, an equal route
   included. Verify: every protocol; a change of protocol leaves none of the old keys; `undo`;
   under `busk run` with processes, the old sender closes and the new one sends.
2. **GAP-38, several fixtures.** `delete fixture N thru M cascade`, and `fixture N thru M patch
   U.A|none`, laid out by footprint. One undo step each, and all or nothing. Verify: a gap in the
   numbers, a run past channel 512, `confirmation()` naming what goes, `undo`.
3. **GAP-39, profiles.** `profile import "<path>"` reads an OFL `.json` or a `.gdtf`, as
   `ProfileLibrary._load` tells them apart, and embeds the profile in one undo step. The file is
   read where `source` reads its own, so the parser stays pure. `FixtureProfileInfo` gains the
   show's revision and the library's. Verify: both formats; a file that fails; an id the show has;
   `undo`; the picker's data; a revision that differs and one that does not.
4. **GAP-22, parked values.** The fifth `OutputSource`, `"park"`, as its entry says. Verify: all
   of a family parked, one attribute of it, and `playback` staying `None`.

### Phase 6: F4 Cues, and F6's delete

Needs GAP-33 and GAP-36. Code: `src/busk_tui/pages/cues.py`, `src/busk_tui/commands.py`,
`src/busk_tui/pages/presets.py`, `src/busk_tui/widgets/preset_panel.py`. Tests:
`tests/tui/test_tui_cues.py`, `test_tui_presets.py`, `test_tui_commands.py`.

1. **A cue's controls**, on the edit row:
   - `[delete]`: `delete cue L/C`, with `ask`.
   - `[merge]`, `[replace]`, `[remove]`: `record cue L/C …`, the last two with `ask`, all grey with
     an empty programmer.
   - `[record at…]`: a number and a name, `record cue L/C ["name"]`. A taken number is refused in
     the dialog.
   - `[release…]`: targets and attributes, `cue L/C release <targets> [only …]`.
2. **A list's controls:** `[+ list…]` in CUELISTS (`cuelist add`), `[rename…]`, `[delete]` (`delete
   cuelist N cascade`, busk's question), a tracking toggle, and `[chase…]`: a form for the rate,
   master, multiplier, direction and crossfade.
3. **F6's `[delete]`** sends `delete preset … cascade` on a preset in use. The panel still names
   what uses it.

Verify: each line as sent; grey states; at 99 columns the strips wrap; the pane cursor reaches each
new control; a deleted list or cue leaves F4 on a list that exists.

### Phase 7: F5: an effect's settings

Needs GAP-32. Code: `src/busk_tui/pages/effects.py`, `src/busk_tui/widgets/effects.py`,
`src/busk_tui/model.py` (`EffectInfo`), a new `widgets/effect_panel.py`. Tests:
`tests/tui/test_tui_effects.py`.

1. **An EFFECT panel**, opened from a row: rate (Hz, or a master and multiplier), direction, size,
   low and high, phase, groups, blocks, wings, fade-in, size and speed masters. One control per
   field, one line per change. A programmer effect sends `effect add "<template>" id <id> …`, with
   every setting restated. A cue effect sends `cue L/C effect <id> <prop> <value>`.
2. **`✕` on a cue effect** (`cue L/C effect <id> remove`, with `ask`) and **`[clear]`** (`effect
   clear`, with `ask`).

Verify: an unchanged field stays in the restated line; a bpm effect and an Hz one; a change while
the effect runs; the wave redraw stays within the perf gate.

### Phase 8: F5: the template editor

Needs GAP-31. Code: `src/busk_tui/pages/effects.py`, a new `widgets/template_panel.py`.

1. **A TEMPLATE panel** with a row per layer. A scalar layer has its attribute, waveform and its
   parameters, phase offset and mode. A colour layer has its palette (colours or presets) and
   blend. `[+ template…]` builds the JSON for `effect template add`, and a change on a show
   template sends `effect template update`.
2. **`[rename…]` and `[delete]`.** Delete is grey while a template is used, and the panel names the
   users, as F6's did. A library template is read-only until the show holds a copy.

Verify: each waveform kind round-trips; both layer kinds; a refusal shows in the panel and the log;
a name the show has.

### Phase 9: F1: the playback's own buttons

Q3 decides what the strips show. Code: `src/busk_tui/widgets/playbacks.py`, `src/busk_tui/model.py`,
`src/busk_tui/bridge.py`, `src/busk_tui/pages/busk*.py`. Tests: `tests/tui/test_tui_busk.py`,
`test_tui_layouts.py`.

1. **The strips draw `buttons`**, in layouts A, B and C: one per entry, labelled by function. Each
   sends `button N B on|off`, `B` counted from 1, so a `none` keeps its place. `flash` and `swop`
   are held, as FLASH is today. The compact row of layout C follows Q3.
2. **`[record]` on an empty slot**: `record slot [P.]S`, grey with an empty programmer.

Verify: all the club show's button sets; `select` and `goto`; hold and release with the mouse;
Space and `[ ]` unchanged; the perf gate on F1 in all three layouts.

### Phase 10: Playback configuration

Needs GAP-35. Q2 says where. This section assumes its recommended answer, F1's `[edit]`. Code: the
pages of Phase 9, a new `widgets/playback_panel.py`, `PlaybackInfo` in `src/busk_tui/model.py`.

1. **Edit mode.** `[edit]` replaces the strips with a grid of the current page's slots, in every
   layout, so nothing performs while editing, as F3's table does.
2. **A PLAYBACK panel** that shows everything `Playback` holds and edits each with one control:
   name, number, buttons, fader, band (`priority`), exclusivity, flash (level, LTP, boost), LTP
   mode and threshold, auto start and release, goto cue, swop protection, release time, colour, and
   the cue list (GAP-34's picker by number).

Verify: every field, set and removed; the F-key and prompt still work in edit mode; `undo` redraws
the panel; a playback that runs while it is edited.

### Phase 11: Adding and deleting playbacks, page slots

Needs GAP-34, GAP-36 and Phase 10.

1. **On an empty slot:** `[new playback…]`, a list picker and a name, `playback add N cuelist L at
   P.S "name"`.
2. **`[delete]`:** `delete playback N cascade`, busk's question.
3. **Slots and pages:** place a playback on a slot (`page P slot S playback N`), `[clear]`, page
   tabs, `[+ page…]` (`page add N`), rename, and `delete page N cascade`.

Verify: a playback on two pages; the last page deleted, and F1 with no pages; bindings by slot
unaffected; the page shown when it is deleted.

### Phase 12: Groups and park

Needs GAP-22 and GAP-36. Code: `src/busk_tui/pages/fixtures.py`, `src/busk_tui/pages/masters.py`,
`src/busk_tui/widgets/fixture_panel.py`, a new `widgets/group_panel.py`. Tests:
`tests/tui/test_tui_fixtures.py`, `test_tui_masters.py`.

1. **GROUPS in F3's edit mode:** number, name and members. `[record…]` from the selection (`record
   group N ["name"]`), `[merge]`, `[replace]` and `[remove]` with the selection, `[rename…]`,
   `[number…]`, `[delete]` (`delete group N cascade`).
2. **Park:** `[park…]` on F3's FIXTURE panel, an attribute and a value for the selection (`park
   <targets> <attribute> <value>`). A PARKED panel on F7 with `[unpark]` on each, and `[unpark
   all]` with `ask`. F3's source column reads `park` and the guide's note about it goes.

Verify: a group left empty by a cascade; a group master; a parked family and one attribute; a
parked pixel element.

### Phase 13: Rig extras

Needs GAP-37, GAP-38 and GAP-39. Code: `src/busk_tui/widgets/route_dialog.py`,
`src/busk_tui/pages/patch.py`, `src/busk_tui/pages/fixtures.py`,
`src/busk_tui/widgets/profile_picker.py`. Tests: `tests/tui/test_tui_patch.py`,
`test_tui_fixtures.py`, `test_tui_fixture_form.py`.

1. **`[edit…]` on a route** opens `RouteDialog` filled in with what it holds, and sends `route <id>
   change …`.
2. **Several fixtures on F3:** `[delete]` and PATCH on a selection that is one run, with `thru`.
3. **Profiles:** `[update profile]` when the library's revision differs (`profile update`), and
   `[import…]` in the picker, a path dialog (`profile import`).

Verify: every protocol through the filled form; a selection with a hole; a bad path; the new profile
offered at once.

### Phase 14: Split patch

Only if Q4 builds it. The engine step comes first.

1. **GAP-40, a split patch.** Remove the `UnsupportedFeature` in `src/busk/compiler/compile.py`,
   with Q4's rule for channel offsets. `fixture N element E patch U.A|none`. Update the spec.
   Verify: the DMX output of a split element against the same fixture unsplit; overlaps; `undo`;
   saved and reloaded; the compile cache (`same_rig`).
2. **F3 and F8:** the PATCH section by element, and F8's map showing each part.

### Phase 15: Cue cell editing

Only if Q5 asks for it. Needs Phase 6. This reverses adaptation 7 of the TUI plan, and its §8.

1. **Under Q5's recommended answer:** a click on a time, delay, curve, follow or wait cell opens a
   dialog, filled in with the value, and sends the line that the pre-fill started. The same for
   `[time…]`, `[delay…]`, `[curve…]`, `[follow…]`, `[wait…]` and `[rename…]`.
2. **The docs:** the TUI plan's §3 item 7 and §8, the spec's open question 4, the guide.

Verify: each kind, with per-family timings; Esc changes nothing; the prompt keeps the keyboard when
no dialog is open.

### Phase 16: Audit, and the user's check

1. **Audit.** Every row of §2 against the code, and every row of the report. Rewrite the report's
   Summary and "In short". Check the guide's "Work in progress" note.
2. **The user's check** on a rig, with the shipped shows: their step, as in the rig plan's step 15.

## 7. Seen, and not in the sources

Left out because the five places do not name them. Say if any should join a phase.

- GAP-06 (one undo step for a gesture) and GAP-13 (control input monitor) are still open.
- A cue's move, copy and renumber past its neighbours (the report's Cues table).
- Renumbering a cue list from F4 (the report's Cue lists table).
- F4's table shows only intensity and colour entries.
- Options when adding an effect from a template click.
- Deleting several presets, cues or lists in one line.
- `route add 1 artnet 200.0.0` still prints a path (net above 127, sub-net or universe above 15),
  like the sACN universe Phase 1 fixed. Phase 1 named only sACN. Found on 2026-11-08.

## 8. Questions

1. **A show file that no longer loads** (blocks Phase 1, step 4). A `refreshHz` of 41 to 44 or a
   fixture number below 1 now fails with `ShowLoadError`, so the operator must edit the JSON by
   hand. Neither shipped show has one. busk used to store those rates and run them at 40 Hz, and
   the old comment in the model said 44.
   - (a) Keep the refusal.
   - (b) Load it with a warning and run at 40 Hz. A fixture below 1 loads with a warning too. The
     console and the forms go on refusing new ones. **Recommended:** a show that opened yesterday
     should open today.

   ANSWER: (b), the recommended one (the user, 2026-11-08). Built in Phase 1.
2. **Where a playback's configuration lives** (Phases 10, 11). F1 to F9 are pages and F10 is help.
   - (a) F1's `[edit]`, the pattern of F3 and F6. **Recommended.**
   - (b) A panel on F4, from the chosen list. Page slots would then need a home of their own.
   - (c) A new page on F11 or F12, which some terminals keep for themselves.

   ANSWER:
3. **What F1's strips show** (Phase 9). The report says the playback's own buttons replace the fixed
   GO, ◂ and FLASH. On the club show, 18 of 20 strips would then have no GO.
   - (a) Only the playback's own buttons, as the show is built. Layout C's one button is the first.
     **Recommended:** the strip then matches the show, and Space still goes.
   - (b) The playback's own, with GO kept where it has none.

   ANSWER:
4. **A split patch** (Phase 14). The spec does not say what a split element's channel offsets are
   relative to, and no shipped show has one.
   - (a) Leave it out until a rig needs it, and drop Phase 14. **Recommended.**
   - (b) Build it, relative to the element's own address.
   - (c) Build it, relative to the start of the mode.

   ANSWER:
5. **Editing a cue's cells** (Phase 15). The TUI plan left it out on purpose. `RowTable` draws
   lines, so a cell holds no widget, and the prompt always has the keyboard.
   - (a) A dialog per cell, as F3 does. **Recommended.**
   - (b) A real editor over the cell.
   - (c) Keep the pre-fills, and drop Phase 15.

   ANSWER:
