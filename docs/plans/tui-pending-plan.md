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

   **Done** (2026-11-08). As planned, in `_route_change`, sharing `_route_fields` with `route add`.
   `SET` cannot replace a list element, so each key that differs is its own edit, as `profile update`
   does. Which the user may veto:
   - An sACN route that stays sACN keeps its priority, since no line sets one.
   - A line that would change nothing is refused: `route r-1 already sends that`.
   - It asks nothing. §1 names what asks, and a change leaves the universe sent.
2. **GAP-38, several fixtures.** `delete fixture N thru M cascade`, and `fixture N thru M patch
   U.A|none`, laid out by footprint. One undo step each, and all or nothing. Verify: a gap in the
   numbers, a run past channel 512, `confirmation()` naming what goes, `undo`.

   **Done** (2026-11-08). As planned, in `_patch` and `_delete_fixtures`. `fixture_cascade` is now
   one walk over a set of ids, because two edits of one group would put back what the first took.
   A test holds a span equal to its fixtures deleted one by one, on both shipped shows. Which the
   user may veto:
   - `thru` takes the fixtures the span holds, as every other `thru` does, so a hole in the numbers
     leaves no hole in the channels.
   - A plain `delete fixture N thru M` is not a line (`expected cascade`), so deleting a run always
     asks.
   - An overlap warns, as one fixture's does: the run is not refused for it.
3. **GAP-39, profiles.** `profile import "<path>"` reads an OFL `.json` or a `.gdtf`, as
   `ProfileLibrary._load` tells them apart, and embeds the profile in one undo step. The file is
   read where `source` reads its own, so the parser stays pure. `FixtureProfileInfo` gains the
   show's revision and the library's. Verify: both formats; a file that fails; an id the show has;
   `undo`; the picker's data; a revision that differs and one that does not.

   **Done** (2026-11-08). As planned: `read_profile` in `src/busk/session/library.py`, an
   `ImportProfile` action, and `Console._import_profile`. `FixtureProfileInfo` gains `revision` and
   `library_revision`. Which the user may veto:
   - A busk profile `.json` imports too, since `_load` tells three forms apart.
   - A name the show holds is refused as well as an id, in any case: `fixture add` would never find
     it by name.
   - An id the show holds is refused whatever its revision. No line replaces a show's copy from a
     file: that stays `profile update`, from the library.
   - The importer's notes print as `note:` lines before the reply.
4. **GAP-22, parked values.** The fifth `OutputSource`, `"park"`, as its entry says. Verify: all
   of a family parked, one attribute of it, and `playback` staying `None`.

   **Done** (2026-11-08). As planned, in `busk.engine.readout`: park is one more origin, ranked above
   the programmer. Which the user may veto:
   - One parked attribute makes the family `park`, as the entry reads, over a pan the programmer
     holds.
   - **An engine phase touched the TUI, by one expression.** F3's `_RANK` and `SOURCE_COLORS` know
     four sources, so a parked fixture would raise on F3, and the club show parks two.
     `busk_tui.bridge` turns `park` into `none`, which is what F3 showed, and Phase 12 takes it out.

**Phase 5 checks** (2026-11-08). The whole suite: 5,513 passed and 1 skipped, in 3:23 with `uv run
pytest -n 6`. `ruff check`, `ruff format --check` and `mypy src` clean. 40 mutations of the new
code, all caught. The perf gate, for the bridge's one changed expression: 7 passed, no overruns. A
real `busk run --state-dir …` with processes on the club show, with a unicast route added: `go 11`,
then each new line and refusal at the prompt. Each route change closed the old sender and opened
the new one, in both directions with `undo`. 0 command errors and 0 overruns. Under `busk run`, a
route change, a patched and a deleted run and an import are in `tests/test_frontend.py`, and a
parked value crosses the engine process there too. Docs: `docs/console.md`, `docs/library.md`,
`docs/profiles.md`, the F3 note of `docs/tui/guide.md`, `busk help`, GAP-22 and GAP-37 to GAP-39 in
`docs/dev/tui/engine-gaps.md`, the report's rows, "In short" and items 6 and 9, and `CHANGELOG.md`.

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

   **Done** (2026-11-09). As planned, on the edit row of `src/busk_tui/pages/cues.py`, and busk takes
   every line (the contract test). Which the user may veto:
   - `[record at…]` is grey with an empty programmer too, which the plan named only for the three
     writes. busk refuses every `record cue` then. "Empty" is no value and no effect that runs,
     since busk does not record a stopped one. `[record cue L]` keeps its old look.
   - On a list with no cues the row is only `[record at…]`.
   - **`[delete]`'s question says when a playback is on the cue**: `P9 is on it, and will leave it at
     once.` The engine moves the playback to another cue the moment the cue goes.
   - `[record at…]` starts at the next whole number after the last cue, as `record cue L` picks, and
     the new cue becomes the chosen one. `check_cue` compares numbers as busk does: `02.5` is `2.5`,
     and `2.50` is another cue.
   - `[release…]` starts at the selection. The dialog checks only that targets were typed: what
     only busk can read, such as a word it does not take, is refused in the log, as for a route.
   - The label can take at most 40% of the row, so a very long name leaves the buttons reachable.
2. **A list's controls:** `[+ list…]` in CUELISTS (`cuelist add`), `[rename…]`, `[delete]` (`delete
   cuelist N cascade`, busk's question), a tracking toggle, and `[chase…]`: a form for the rate,
   master, multiplier, direction and crossfade.

   **Done** (2026-11-09). As planned. The form is `ChaseDialog` in the new
   `src/busk_tui/widgets/chase_dialog.py`, and `CueListInfo.rate` (`ChaseRate`) holds the settings
   it starts at. `PickRow` takes where it starts. Which the user may veto:
   - The list's controls have a row of their own, `list 9 Song`, so `[rename…]` and `[delete]` are
     not read as the cue's.
   - The toggle reads `[tracking on]` or `[tracking off]`, what a click does, as F6's `[blind on]`.
   - `[+ list…]` shows the new list once it has run.
   - `[chase…]` also makes the list a chase, since the line does. A show with no speed master offers
     Hz alone, and the master row shows only with several.
   - The form's numbers go in the line as typed, so `0.125` is not rounded as `commands.number`
     would. It refuses a sign, `%` and an exponent, which a number field does not need.
3. **F6's `[delete]`** sends `delete preset … cascade` on a preset in use. The panel still names
   what uses it.

   **Done** (2026-11-09). As planned, in `PresetPanel.ask_delete`: busk's question for a preset in
   use, the TUI's own, with its note about the programmer, for one nothing uses. The panel's second
   line now reads `delete takes it out of those too`. Which the user may veto:
   - **A preset only a binding names is still sent plainly**, so busk refuses it in one line (`…: add
     cascade`) and the operator types the cascade. `PresetInfo` knows cues and palettes, not bindings.
   - A palette's last colour is not greyed: the TUI cannot tell. busk refuses it in the log, and
     the preset stays chosen.

Verify: each line as sent; grey states; at 99 columns the strips wrap; the pane cursor reaches each
new control; a deleted list or cue leaves F4 on a list that exists.

**Phase 6 checks** (2026-11-09). The whole suite: 5,591 passed and 1 skipped, in 3:31 with `uv run
pytest -n 6`. `ruff check`, `ruff format --check` and `mypy src` clean. No change to `src/busk/` or
the engine's tests. The four TUI test files the phase touched, 386 tests, and the new test on the
real engine in `tests/tui/test_tui_e2e.py` pass on Textual 8.2.0. The perf gate: 7 passed, no
overruns, F4 at +0.139 core. 54 mutations of the new code, all caught; three needed a test of their
own, which is in. A real `busk-tui --state-dir …` under `busk run` on the club show, at 150 and 99
columns: `go 9` twice, the forms of `[record at…]` and `[chase…]`, `[delete]` of the cue P9 was on
with its question, `[delete]` of the running list with busk's, F6's `[delete]` of Blue with busk's,
and `undo`, with no error in the log. Docs: `docs/tui/guide.md`, the report's rows, Summary, "In
short" and side finding, and `CHANGELOG.md`.

### Phase 7: F5: an effect's settings

Needs GAP-32. Code: `src/busk_tui/pages/effects.py`, `src/busk_tui/widgets/effects.py`,
`src/busk_tui/model.py` (`EffectInfo`), a new `widgets/effect_panel.py`. Tests:
`tests/tui/test_tui_effects.py`.

1. **An EFFECT panel**, opened from a row: rate (Hz, or a master and multiplier), direction, size,
   low and high, phase, groups, blocks, wings, fade-in, size and speed masters. One control per
   field, one line per change. A programmer effect sends `effect add "<template>" id <id> …`, with
   every setting restated. A cue effect sends `cue L/C effect <id> <prop> <value>`.

   **Done** (2026-11-09). As planned: `EffectPanel` in the new `src/busk_tui/widgets/effect_panel.py`,
   opened by a click anywhere on a row but its state or `✕`. Its rate form is `RateDialog`, the rate
   half of `ChaseDialog`, now in `widgets/chase_dialog.py`. Which the user may veto:
   - **`effect add … id` takes its targets from the selection**, which the plan did not name. A
     restated effect would move to whatever is selected, and is refused with nothing selected. So a
     programmer effect changes only while the selection is its fixtures, in their order. Otherwise
     the panel is grey and says so, and `[its fixtures]` selects them. This and the next are GAP-41
     in `docs/dev/tui/engine-gaps.md`.
   - **No line takes an optional setting away from a cue's effect.** `[none]` for a master or a
     fade-in is grey there, and the levels only change.
   - The panel takes the templates' place until `[done]`, and goes under the effects below 132
     columns.
   - A programmer effect has one `[levels…]` form, since `effect add` takes the two together. A
     cue's has `[low…]` and `[high…]`, a line each. No control removes levels.
   - A fade-in has a `[none]`, which the plan did not name: a fade-in of 0 snaps in, and without
     one an effect comes in over its cue's time.
   - A value left as it was sends nothing. Numbers go in the line with every digit and no exponent
     (`commands.exact`), since `:g` rounds and busk reads no exponent.
   - The panel says when a speed master does nothing, on a beat rate. The validator only warns, at
     load.
   - `MasterView` has an `id`, as `RouteView` has: a cue effect's `rate`, `sizeMasterId` and
     `speedMasterId` name a master by id. It shows only in the line sent.
2. **`✕` on a cue effect** (`cue L/C effect <id> remove`, with `ask`) and **`[clear]`** (`effect
   clear`, with `ask`).

   **Done** (2026-11-09). As planned: `✕` is on every row, and `[clear]` is under the table. Which
   the user may veto:
   - The question for a cue's effect says when it runs: `It is running, and will stop at once.` The
     effect goes and the cue stays active.
   - `[clear]` is grey while the programmer holds no effect.

Verify: an unchanged field stays in the restated line; a bpm effect and an Hz one; a change while
the effect runs; the wave redraw stays within the perf gate.

**Phase 7 checks** (2026-11-09). The whole suite: 5,711 passed and 1 skipped, in 3:59 with `uv run
pytest -n 6`. `ruff check`, `ruff format --check` and `mypy src` clean. No change to `src/busk/` or
the engine's tests. The five TUI test files the phase touched, 468 tests, pass on Textual 8.2.0. The
perf gate on the final code: 7 passed, no overruns, F5 at +0.186 core. An earlier run failed once at
+0.2503 on a page not recorded, and its rerun passed. F5 alone, five runs each: +0.176 before this
phase, +0.184 after it, +0.193 with the panel open. `tests/tui/test_tui_conversion.py` restates
effects on the real parser and gets an equal document, and runs each line a cue effect's controls
send. 79 mutations of the new code: 74 caught; of the five that survived, three were code that could
not run, now gone, and two needed a test of their own, which is in. `tests/tui/test_tui_e2e.py` has
two new tests on the real engine. A real `busk-tui --state-dir …` under `busk run` on the club show,
with real mouse clicks in a pty: at 150 columns, `go 11`, the size and direction of the running
effect, `✕` with its question and `undo`, a programmer effect restated, a grey panel with another
selection, `[its fixtures]` and `[clear]`; at 99 columns, the panel under the effects and two
changes. No error in the log. Docs: `docs/tui/guide.md`, the report's rows, Summary, "In short" and
side finding, GAP-41, and `CHANGELOG.md`.

### Phase 8: F5: the template editor

Needs GAP-31. Code: `src/busk_tui/pages/effects.py`, a new `widgets/template_panel.py`.

1. **A TEMPLATE panel** with a row per layer. A scalar layer has its attribute, waveform and its
   parameters, phase offset and mode. A colour layer has its palette (colours or presets) and
   blend. `[+ template…]` builds the JSON for `effect template add`, and a change on a show
   template sends `effect template update`.

   **Done** (2026-11-09). As planned: `TemplatePanel` and `NewTemplateDialog` in the new
   `src/busk_tui/widgets/template_panel.py`, in the slot the EFFECT panel uses. `TemplateInfo.layers`
   holds each layer as the show stores it, so what the panel does not edit (a colour's extra
   emitters) goes back unchanged. Which the user may veto:
   - **A new column, `[edit]`** (`[view]` for one only the library has), opens the panel. A click
     anywhere else on a row still adds an effect, as before.
   - **A new template starts with a layer**, since busk refuses one without: `intensity multiply
     sine`, or a white colour layer. Its form asks which, and the panel opens once the show has it.
   - A layer is chosen for the controls by a click on its row. There is no moving of a layer or a
     palette entry: take it out and add it again.
   - **A change of waveform resets its parameters** to where a new one starts (`duty` 0.5, and the
     like): the old ones are of another shape.
   - **A dialog refuses only what could not be sent** (a level outside 0 to 1, a name the show has).
     What only busk can tell comes back as a refusal, such as a pulse longer than its cycle.
   - The panel gives busk's reason **without the place in the document**, and the log the whole
     reply, path included (§5, item 9).
   - `+ preset` offers the colour pool only, a chip per preset. A palette's preset has no form.
   - `TemplateInfo.id` and `PresetInfo.id` exist, as `MasterView.id` does: the panel stays on a
     template through a rename, and a palette names a preset by id.
   - Added to `RunLine`: `refused`, called with busk's reply when a line fails, which the plan did
     not name. The panel sets it as each of its lines bubbles past.
2. **`[rename…]` and `[delete]`.** Delete is grey while a template is used, and the panel names the
   users, as F6's did. A library template is read-only until the show holds a copy.

   **Done** (2026-11-09). As planned. `[delete]` asks the TUI's question (§1) and is grey while a
   cue, a binding or the programmer uses the template, counted as busk counts them. Which the user
   may veto:
   - **A name is checked against the show's templates only**, as busk's rule is: naming one after a
     library template is allowed, and hides the library's.
   - The programmer's use is found by template name: `ProgrammerStatus` names no template id in the
     TUI's model.

Verify: each waveform kind round-trips; both layer kinds; a refusal shows in the panel and the log;
a name the show has.

**Phase 8 checks** (2026-11-09). The whole suite: 5,838 passed and 1 skipped, in 4:47 with `uv run
pytest -n 6`. `ruff check`, `ruff format --check` and `mypy src` clean. No change to `src/busk/` or
the engine's tests. The five TUI test files the phase touched, 557 tests, pass on Textual 8.2.0. The
perf gate on the final code: 7 passed, no overruns, F5 at +0.195 core. `tests/tui/test_tui_conversion.py`
sends each waveform and both kinds of layer into a real show, through the bridge and back, unchanged.
47 mutations of the new code: 39 caught at once, 7 needed a test of their own, which is in, and one
was a condition that could do nothing, now gone. `tests/tui/test_tui_e2e.py` has a new test on the
real engine. A real `busk-tui --state-dir …` under `busk run` on the club show, with real mouse
clicks in a pty: at 150 columns, `go 11`, Circle's phase offset and a layer's waveform changed while
it ran, an absolute layer on tilt refused with the reason in the panel and the log, the next line
clearing it, `undo`, then `[+ template…]`, a colour layer, a preset chip, `[rename…]` and `[delete]`
with its question; at 99 columns, the panel under the effects. No error in the log. Docs:
`docs/tui/guide.md`, the report's rows, "In short" and "What the TUI is missing", and `CHANGELOG.md`.

### Phase 9: F1: the playback's own buttons

Q3 decides what the strips show. Code: `src/busk_tui/widgets/playbacks.py`, `src/busk_tui/model.py`,
`src/busk_tui/bridge.py`, `src/busk_tui/pages/busk*.py`. Tests: `tests/tui/test_tui_busk.py`,
`test_tui_layouts.py`.

1. **The strips draw `buttons`**, in layouts A, B and C: one per entry, labelled by function. Each
   sends `button N B on|off`, `B` counted from 1, so a `none` keeps its place. `flash` and `swop`
   are held, as FLASH is today. The compact row of layout C follows Q3.

   **Done** (2026-11-09). As planned, under Q3's (a): `own_buttons`, `own_controls` and `HeldButton`
   in `src/busk_tui/widgets/playbacks.py`, `commands.button`, and `PlaybackInfo.buttons` and
   `gotoCue`. A strip is rebuilt only when what it is built from changes. Which the user may veto:
   - **The labels are two cells:** `GO`, `◂`, `GT`, `FL`, `SW`, `TG`, `RL`, `SL` and `—`, so that two
     fit a column. The hint row names the function under the mouse.
   - **A button that would do nothing is grey**, which the plan did not name: a `none`, a `goto` with
     no `gotoCue`, and `go` or `toggle` on a list with no cues. That last is Phase 2's warning:
     `button N B on` marks the playback active on no cue, where `go N` is refused. The prompt and a
     bound control can still do it.
   - **In a column, two buttons have no gap between them** (`[TG][FL]`). With a gap they need 9 cells
     inside the border, and the grid can leave a column with 8 as the page's scrollbar comes and
     goes, which a real run found.
   - **A `select` press is not sent as a performance line**, though `button` is one: busk runs it as
     `SELECT_PLAYBACK`, so it stays in order with the programmer's lines and is undoable.
   - **A press-only button sends only `on`.** `off` does nothing there, and would fill the log.
   - **A held button lets go when its strip goes** (another page, an edit of its buttons), which the
     plan did not name. Before, a `flash N on` stayed on after a page change under a held mouse.
   - A held button has no pane-cursor stop, as FLASH had none. It has no key to hold it.
   - A `toggle` is not lit while the playback runs: the name and the cue column say so.
   - B's button column is as wide as the page's widest row, and the bar can go down to 8 cells, from
     12, so that four buttons fit at 100 columns. Five or more can clip from 100 to about 109.
   - A column grows a line for every two buttons past four, and all of them take the tallest's height.
2. **`[record]` on an empty slot**: `record slot [P.]S`, grey with an empty programmer.

   **Done** (2026-11-09). As planned, as `record slot P.S`, naming the page the strip shows, which a
   page change cannot move under the click. `ProgrammerModel.recordable`, moved from F4, decides the
   grey, so a stopped effect is nothing to record here as well. Which the user may veto:
   - The column gets 9 cells on a compact row with an empty slot, and that row's bar goes down to 5.

Verify: all the club show's button sets; `select` and `goto`; hold and release with the mouse;
Space and `[ ]` unchanged; the perf gate on F1 in all three layouts.

**Phase 9 checks** (2026-11-09). The whole suite: 5,886 passed and 1 skipped, in 4:50 with `uv run
pytest -n 6`. `ruff check`, `ruff format --check` and `mypy src` clean. No change to `src/busk/` or
the engine's tests. The five TUI test files the phase touched, 490 tests, and the new test on the
real engine in `tests/tui/test_tui_e2e.py` pass on Textual 8.2.0. The perf gate on the final code: 7
passed, no overruns, F1 B at +0.176 core, A at +0.179 and C at +0.212. 54 mutations of the new code:
52 caught at once, and two of layout CSS needed a tighter test, which is in. A real `busk-tui
--state-dir …` under `busk run` on the club show, with real mouse presses in a pty, at 150 and 99
columns: `[TG]`, a held `[FL]` lit and let go, `[RL]`, `[GT]`, Space on a playback with no go button,
an edit of the buttons that redrew the strip, `[SL]`, `undo`, a grey `[record]` sending nothing and a
live one recording slot 2.7, a held `[SW]` let go by a page change, a held `[FL]` in layout A's column
and layout C's one button, with no error in the log. Docs: `docs/tui/guide.md` with its three F1
diagrams, the report's rows, "In short" and "What the TUI is missing", and `CHANGELOG.md`.

### Phase 10: Playback configuration

Needs GAP-35. Q2 says where. This section assumes its recommended answer, F1's `[edit]`. Code: the
pages of Phase 9, a new `widgets/playback_panel.py`, `PlaybackInfo` in `src/busk_tui/model.py`.

1. **Edit mode.** `[edit]` replaces the strips with a grid of the current page's slots, in every
   layout, so nothing performs while editing, as F3's table does.

   **Done** (2026-11-09). As planned: `PlaybackEditor`, `SlotGrid` and `SlotTile` in the new
   `src/busk_tui/widgets/playback_panel.py`, shown by `BuskPage.set_editing`. Which the user may veto:
   - **The grid and the panel take the place of the whole layout**, its masters and tempo too, not
     only of the strips: the panel needs the room.
   - **The grid has every slot of the page, past `--faders`.** F1 caps its strips for the screen; a
     playback past the cap would otherwise have no control at all.
   - **The keys still perform.** Space, `[ ]` and PgUp act on the selected playback, as they do on
     every page, F3's edit mode included. "Nothing performs" is the grid.
   - **`[edit]` is the pane cursor's last stop**, so Tab still lands first on a playback's button.
   - A click on an empty slot does nothing here. Phase 11 gives it `[new playback…]`.
2. **A PLAYBACK panel** that shows everything `Playback` holds and edits each with one control:
   name, number, buttons, fader, band (`priority`), exclusivity, flash (level, LTP, boost), LTP
   mode and threshold, auto start and release, goto cue, swop protection, release time, colour, and
   the cue list (GAP-34's picker by number).

   **Done** (2026-11-09). As planned: `PlaybackPanel` and `CueListDialog`, with `PlaybackInfo` holding
   the rest of the show's playback. A chip per word for the closed sets, a dialog for the others, and
   `[none]` on what can be left out. A test walks `Playback` and `PlaybackFlash`, so a new property
   fails until it is on the panel or named as left out. Which the user may veto:
   - **The panel follows the selected playback**, with no chosen one of its own, so ← → move it
     too, and a tile's click is the click on `Pn` of the strips.
   - **`notes` and `tags` are not on it.** The plan's list does not name them.
   - **`[buttons…]` takes the functions as typed words**, in order, in one dialog, so that adding,
     taking out and reordering are one line and one undo step. No words: no buttons.
   - **Levels are in percent**, as every other level of the TUI, and go in the line as busk's 0 to 1.
   - **The cue list's control is grey while the playback runs**, or is releasing, and the panel says
     why, as busk refuses the line then. The other settings take effect while it runs.
   - **A goto cue the new list lacks stays**, as Phase 3 left it: busk warns in the log.
   - `[goto…]` takes a typed cue number of its list, and is grey on a list with no cues.
   - `[colour…]` takes `#rrggbb`, the only form F1 can draw. Another word in the file shows as words.
   - A key typed as `none` is a key of that name: only `[none]` removes one.
   - A band and a flash boost take a sign, as busk does. `[number…]` starts at 1, as F3's does, though
     busk takes a playback number below 1.

Verify: every field, set and removed; the F-key and prompt still work in edit mode; `undo` redraws
the panel; a playback that runs while it is edited.

**Phase 10 checks** (2026-11-09). The whole suite: 6,004 passed and 1 skipped, in 6:18 with `uv run
pytest -n 6`. `ruff check`, `ruff format --check` and `mypy src` clean. No change to `src/busk/` or
the engine's tests. The five TUI test files the phase touched and the new test on the real engine in
`tests/tui/test_tui_e2e.py`, 570 tests, pass on Textual 8.2.0. The perf gate on the final code: 7
passed, no overruns, F1 B at +0.204 core, A at +0.229 and C at +0.222, on a loaded machine. Against
the commit before this phase, four runs each, one after the other: B 0.179 before and 0.175 after, A
0.191 before and 0.199 after. 49 mutations of the new code: 48 caught; the one that survived was a
`float()` in the bridge that could do nothing, since busk's validation stores floats, and the three
like it are gone. A real `busk-tui --state-dir …` under `busk run` on the club show, with real mouse
clicks in a pty: at 150 columns in layout B, the grid and the panel, a tile, a fader chip, the band
dialog, `go 9`, `[list…]` grey with its reason, `release 9 0`, the picker, `[buttons…]`, `[key…]`,
`undo`, and `[done]` with the strip redrawn; at 99 columns in layout A, the panel under the grid and
in sight after a click, a fader function changed while P9 ran, a new number while it ran, and `undo`
of that number, with the selection following; at 150 columns in layout C, six buttons. No error in
the log. Docs: `docs/tui/guide.md` with a section and a diagram, the report's rows, Summary, "In
short" and "What the TUI is missing", and `CHANGELOG.md`.

### Phase 11: Adding and deleting playbacks, page slots

Needs GAP-34, GAP-36 and Phase 10.

1. **On an empty slot:** `[new playback…]`, a list picker and a name, `playback add N cuelist L at
   P.S "name"`.

   **Done** (2026-11-10). As planned, in `PlaybackEditor` of `src/busk_tui/widgets/playback_panel.py`:
   the picker, then a form of a number and a name, then one line. The picker is `PickDialog`, which
   `CueListDialog` and the new `PlaybackDialog` share. Which the user may veto:
   - **The grid has one empty tile past the last slot**, which the plan did not name. `page add` makes
     a page with no slots, and a slot exists only once something was put there, so a new page would
     have no tile at all. A slot further out is typed at the prompt.
   - **The name starts as the list's**, so Enter names the playback after what it runs. An empty name
     leaves it to busk (`Playback 30`). The number starts at the next free one.
   - The new playback is selected once busk has it, as `[number…]` does.
   - `[new playback…]` is grey on a show with no cue list.
2. **`[delete]`:** `delete playback N cascade`, busk's question.

   **Done** (2026-11-10). As planned: `[delete]` beside `[rename…]` and `[number…]` at the top of the
   PLAYBACK panel. busk's question names the pages it leaves and says when it runs. The selection then
   moves as it does when a playback leaves the page: to the one in its slot, else the first.
3. **Slots and pages:** place a playback on a slot (`page P slot S playback N`), `[clear]`, page
   tabs, `[+ page…]` (`page add N`), rename, and `delete page N cascade`.

   **Done** (2026-11-10). As planned. Over the grid, a tab per page and `[+ page…]`, then a row for the
   page shown, `page 1 Main [rename…] [delete]`, as F4's list has. Which the user may veto:
   - **The slot in hand**, which the plan did not name: the row under the grid is about the tile last
     clicked, `slot 2 · P9 Song [place…] [clear]` or `slot 3 · empty [new playback…] [place…]`. A
     playback can sit on two slots of one page, so the selection cannot say which. ← → take the
     selected playback's slot in hand. **Only the selection moving takes the hand elsewhere**, not a
     new show: the selection reaches the editor after the engine's next frame, and the first build
     cleared slot 9 when slot 14 was meant (the test on the real engine found it). **An empty slot
     stays in hand** until another click, so a second click on `[clear]` finds no slot to clear.
   - **`[place…]` replaces what a full slot holds, and asks nothing**: §1 does not name it, and `undo`
     brings it back. What the slot held stays in the show. Its picker starts at what the slot holds,
     else the selected playback, and each row says where that playback sits (`9 Song · 1.9 2.9`).
     The playback placed is selected.
   - **A tab goes to the page** (`page 2`), as PgUp does, so the surfaces follow too. There is no
     looking at a page without going to it.
   - **`[+ page…]` stays on the page it was on.** Going to the new page would move what the surfaces
     play; its tab is one click.
   - No `[number…]` for a page, which the plan did not name: `page N number M` is typed.
   - A tab cuts a name past 16 characters.
   - With no pages, the grid has the playbacks by number, as F1 does, and only `[+ page…]` is over it.
   - Below 100 columns a click on a tile scrolls to the slot's row, with the panel under it, not to
     the panel's top.

Verify: a playback on two pages; the last page deleted, and F1 with no pages; bindings by slot
unaffected; the page shown when it is deleted.

**Phase 11 checks** (2026-11-10). The whole suite: 6,062 passed and 1 skipped, in 6:27 with `uv run
pytest -n 6`. `ruff check`, `ruff format --check` and `mypy src` clean. No change to `src/busk/` or
the engine's tests. The two TUI test files the phase changed most, 454 tests, and the new test on the
real engine with Phase 10's beside it pass on Textual 8.2.0. The perf gate: 7 passed, no overruns, F1
B at +0.175 core, A at +0.186 and C at +0.199. 61 mutations of the new code: 58 caught at once; of the
three that survived, one was code that could do nothing, now gone, and two needed a tighter test,
which is in. The new test in `tests/tui/test_tui_e2e.py` runs on the real engine: a new playback on
page 2, P9 placed on both pages and cleared from one, a playback deleted with busk's question and
every binding left, slot 7's by slot among them, a new page, renamed, the page shown deleted and the
engine on the next, the last page deleted with F1 by number, and `undo`. A real `busk-tui --state-dir
…` under `busk run` on the club show, with real mouse clicks in a pty, on the final code: at 150
columns in layout B, the same walk, with `go 21` before its `[delete]`, whose question said it runs;
at 99 columns in layout A, a tile's row and panel scrolled into sight, `[place…]`, the wheel and a
tab. No error in the log. Docs: `docs/tui/guide.md` with its diagram, the report's Summary, rows, "In
short" and "What the TUI is missing", and `CHANGELOG.md`.

### Phase 12: Groups and park

Needs GAP-22 and GAP-36. Code: `src/busk_tui/pages/fixtures.py`, `src/busk_tui/pages/masters.py`,
`src/busk_tui/widgets/fixture_panel.py`, a new `widgets/group_panel.py`. Tests:
`tests/tui/test_tui_fixtures.py`, `test_tui_masters.py`.

1. **GROUPS in F3's edit mode:** number, name and members. `[record…]` from the selection (`record
   group N ["name"]`), `[merge]`, `[replace]` and `[remove]` with the selection, `[rename…]`,
   `[number…]`, `[delete]` (`delete group N cascade`).

   **Done** (2026-11-10). As planned: `GroupPanel` in the new `src/busk_tui/widgets/group_panel.py`,
   under the table in F3's edit mode, and `GroupInfo.members`. Which the user may veto:
   - **A click on a group chooses it and sends nothing.** The selection stays, so the group can be
     chosen before or after its fixtures are clicked. There is no `[select]`, which the plan did not
     name: `sel group N` is typed, or F1's and F2's group buttons send it.
   - **`[merge]`, `[replace]` and `[remove]` are grey while they would change nothing**, which the
     plan did not name: busk spends an undo step on a merge of members and a remove of what is not
     one. `[replace]` and `[remove]` ask the TUI's question (§1), and the second says how many
     members stay, or that the group stays with none.
   - `[record…]` starts at the number after the highest, as F4's `[+ list…]` and F1's `[+ page…]`
     do. Its note lists the members the selection gives. The new group is chosen.
   - `[delete]` always sends `cascade`: busk asks even for a group nothing uses (`Delete group 5
     "Five"?`).
   - A choice the show lacks is dropped only when a new show comes, since a record's or a
     renumber's done may come before its show.
   - Below 100 columns the panel is between the table and the FIXTURE panel. On a short terminal the
     page now scrolls for it, where the table alone did not.
   - `GroupInfo` holds its members in a cue's and a master's targets too, so the conversion tests
     that build one name its members.
2. **Park:** `[park…]` on F3's FIXTURE panel, an attribute and a value for the selection (`park
   <targets> <attribute> <value>`). A PARKED panel on F7 with `[unpark]` on each, and `[unpark
   all]` with `ask`. F3's source column reads `park` and the guide's note about it goes.

   **Done** (2026-11-10). As planned: a PARK section in `FixturePanel`, `ParkedPanel` and
   `parked_rows` in the new `src/busk_tui/widgets/parked.py`, `ShowModel.park` (`Parked`), and
   `park` in `Source`, `_RANK`, `SOURCE_COLORS`, `source_text` and the legend. The bridge's `park →
   none` is gone. Which the user may veto:
   - **PARK reaches the selected elements**, not fixtures, while the chosen fixture is selected,
     so a pixel can be parked (`PARK · 102, 301.2`); else all of the chosen fixture. LIMITS reaches
     by fixture. It is always one line, since `park` takes a list of targets.
   - **The section shows what park holds on the chosen fixture**, which the plan did not name, with
     no `[unpark]`: F7 unparks, where the plan puts it.
   - `[park…]`'s form takes the attribute as a word, checked against what the reach's profiles take
     (its note lists them). The value goes as typed, and busk refuses in the log what it cannot
     read, as for F4's `[release…]`. A colour's component is not offered: busk's `park` refuses
     `color.w`, and `color 1 0 0 w 0.5` takes the white. The form starts at `intensity` and `0`, a
     broken fixture held dark, not at what is parked. It is grey where no profile of the reach
     says what it takes.
   - **F7 has a row per fixture, attribute and value**, the elements compressed, so a bar parked
     whole is one row and one `unpark fixture 301 color`. A row per entry would be twelve.
   - `[unpark]` asks nothing: busk asks nothing, §1 does not name it, and `undo` brings it back.
     `[unpark all]` asks, and counts the values: `Unpark everything? Park holds 2 values.`
   - PARKED is F7's last panel, after PANIC, on every show: with nothing parked it says where
     parking is.
   - Park reads amber, above the programmer as busk ranks it, and one parked element is enough
     for the fixture's `src`.

Verify: a group left empty by a cascade; a group master; a parked family and one attribute; a
parked pixel element.

**Phase 12 checks** (2026-11-10). The whole suite: 6,098 passed and 1 skipped, in 6:47 with `uv run
pytest -n 6`. `ruff check`, `ruff format --check` and `mypy src` clean. No change to `src/busk/` or
the engine's tests. The five TUI test files the phase touched and the new test on the real engine,
534 tests, pass on Textual 8.2.0. The perf gate: 7 passed, no overruns, F3 at +0.185 core, F1 B at
+0.191, A at +0.201 and C at +0.217 (F1's code did not change). 81 mutations of the new code: 70
caught at once, 7 by tests the first run's selection had left out, 3 needed a test of their own
(groups out of number order, park entries out of element order, a note long enough to wrap), which
is in, and 1 was equivalent: busk's order puts `intensity` first, so the park form now starts at the
first attribute. The new test in `tests/tui/test_tui_e2e.py` runs on the real engine: `src` reads
`park` on wash 4, a group recorded from the bar, merged, removed from with the question, renamed,
renumbered and deleted with busk's, the bar's group left with no members by a typed cascade and
`undo`, two pixels parked from the FIXTURE panel and `src` reading `park`, F7's `[unpark]` and
`[unpark all]` with its question, `undo`, and a parked tilt turning the pan cell amber. A real
`busk-tui --state-dir …` under `busk run` on the club show, with real mouse clicks in a pty: at 150
columns in layout B, the same walk through GROUPS, PARK and F7; at 99 columns in layout A, GROUPS
between the table and the FIXTURE panel, a group chosen and merged, a row's click bringing the panel
into sight, wash 4 parked again at 50%, and F7 in one column. No error in the log. Docs:
`docs/tui/guide.md` (F3's `src` and legend, its edit-mode diagram, PARK and GROUPS; F7's PARKED),
the report's rows and "In short", GAP-22's entry in `docs/dev/tui/engine-gaps.md`, and
`CHANGELOG.md`.

### Phase 13: Rig extras

Needs GAP-37, GAP-38 and GAP-39. Code: `src/busk_tui/widgets/route_dialog.py`,
`src/busk_tui/pages/patch.py`, `src/busk_tui/pages/fixtures.py`,
`src/busk_tui/widgets/profile_picker.py`. Tests: `tests/tui/test_tui_patch.py`,
`test_tui_fixtures.py`, `test_tui_fixture_form.py`.

1. **`[edit…]` on a route** opens `RouteDialog` filled in with what it holds, and sends `route <id>
   change …`.

   **Done** (2026-11-10). As planned: `RouteDialog(universe, name, route)`, `commands.route_change`,
   and `[edit…]` on F8's strip, between the route's name and `[off]`. `RouteView` gains `rate`, a
   DMX-USB route's, for the filled form. Which the user may veto:
   - **The route keeps its universe.** The form has no universe field, as the new one has none: a
     route moves to another universe by `[delete]` and `[+ route…]`, though `route <id> change`
     takes one.
   - **A form that changes nothing closes and sends nothing**, as a rename to the same name does.
     busk would refuse it (`already sends that`).
   - The fields of the other protocols start where the new form starts them, so a change of
     protocol reads as in `[+ route…]`. The interface or host stays when sACN becomes Art-Net.
   - A DMX-USB rate past 40 (41 to 44 load since Phase 1) is filled in as it is, and the form
     refuses it until it is changed, as busk does.
   - `[off]` and `[on]` are one place further along the strip, so the pane cursor reaches them one
     step later.
2. **Several fixtures on F3:** `[delete]` and PATCH on a selection that is one run, with `thru`.

   **Done** (2026-11-10). As planned, with the reach of LIMITS: `FixturePanel.run()` is the reach
   while it is one span. `PatchChooser` places a run (`own` is now a tuple of fixtures), `layout`
   says where `thru` puts each, and `clashes` and `takes_text` leave out every fixture of the run.
   `commands.delete_fixture` and `patch_fixture` take a `last`. Which the user may veto:
   - **A selection of several runs greys `[delete]` and PATCH even for the fixture shown** (§5
     call 7), where both acted on it alone before this phase. To patch one fixture of such a
     selection, click it alone. PATCH says why: `not one run: thru would take 202 too`, and its
     choice and `[next free]` go.
   - **`[delete]` names a run in its label**, `[delete 101 thru 104]`, since nothing else in the
     header says how far it reaches.
   - **PATCH starts a run at its first fixture's patch**, even when the run is not in one block;
     `[patch]` is then live and lays the run out from there. A run whose first fixture is unpatched
     starts at none. Its heading says where it is: the span while it is one block as `thru` would
     lay it out, else `none` or `not in one block`.
   - A choice made in PATCH goes when the fixtures it places change (a selection from the prompt,
     say), not only when another fixture is chosen.
   - `[next free]` counts the run's own channels as taken, as for one fixture (rig plan, group E).
   - F8's `[patch N here]` stays for one fixture: the plan named F3.
   - The guide's picture of the FIXTURE panel now has a run selected, `101 thru 102`, where it had
     `102, 301.2`, which this phase greys.
3. **Profiles:** `[update profile]` when the library's revision differs (`profile update`), and
   `[import…]` in the picker, a path dialog (`profile import`).

   **Done** (2026-11-10). As planned: `[update profile]` beside `[profile…]`, `[import…]` under the
   picker's list, `ProfileChoice.revision`, `library_revision` and `outdated()`,
   `commands.profile_update` and `profile_import`, and `ProfileDialog.offer`, which the app calls on
   every open picker when the show changes. Which the user may veto:
   - `[update profile]` always shows, grey unless the library holds the profile at another
     revision, older or newer. It asks nothing: busk asks nothing, and `undo` takes it back.
   - **Ctrl+O** opens the path dialog too, which the plan did not name: the picker's filter has the
     keyboard, and nothing else reaches `[import…]` from it.
   - **The TUI makes the path whole** (`~` expanded, a relative path from where busk-tui runs), so
     the log shows the file busk reads. The dialog refuses a path with no file there; what is in it
     is busk's to read.
   - **The picker stays open after an import**, and lands on the profile once the show brings it,
     the filter cleared. Choosing it is still Enter: an import alone changes no fixture. A library
     profile the file brings into the show under its id is the one landed on too.
   - **busk's refusal shows in red under the list**, since the log is behind the picker. The
     importer's `note:` lines go to the log only.
   - The shell hands the choices to open pickers (`BuskApp.take`): the one place it knows what a
     dialog shows.

Verify: every protocol through the filled form; a selection with a hole; a bad path; the new profile
offered at once.

**Phase 13 checks** (2026-11-10). The whole suite: 6,144 passed and 1 skipped, in 8:01 with `uv run
pytest -n 6`. `ruff check`, `ruff format --check` and `mypy src` clean. No change to `src/busk/` or
the engine's tests. The seven TUI test files the phase touched and the two new tests on the real
engine, 735 tests, pass on Textual 8.2.0. The perf gate: 7 passed, no overruns, F3 at +0.181 core,
F1 B at +0.198, A at +0.214 and C at +0.220. 75 mutations of the new code: 69 caught at once, 4
needed a test of their own (a route id of two words in `route_change`, a selected fixture between a
hole's ends, `[patch]` going grey when a live run becomes a hole, a run deleted with another than
its first fixture chosen), which are in, and 2 were dead code, now gone: a library profile's two
revisions are both the library's, so `outdated()` needs no `source`, and `offer` needs no guard for
choices that did not change. Two new tests in `tests/tui/test_tui_e2e.py` run on the real engine:
F8's route edited through its filled form to sACN 9, Art-Net to a host, DMX-USB and sACN again,
keeping its id, a form that changes nothing sending nothing, and `undo`; F3's `[update profile]` on
the spots at revision 7, the pars 201 thru 204 patched in one line, a hole that greys `[delete]` and
PATCH, the run deleted after busk's question and back with `undo`, and the picker refusing a missing
path, showing busk's refusal of a bad file, and landing on the imported profile. Under `busk run`
(`tests/tui/test_tui_host.py`), a route edited from F8 closes its sender and opens the new one. A
real `busk-tui --state-dir …` under `busk run` on the club show, its spots at revision 7, with real
mouse clicks in a pty: at 150 columns in layout B, the club's route (failing here: no `eth0`) edited
to sACN 9, then to Art-Net unicast `127.0.0.1`, which opened and sent, an unchanged form sending
nothing, two `undo`s; 101 and 102 shift-clicked, `[delete 101 thru 102]`, `[next free]` and `fixture
101 thru 102 patch 1.85`; 201 and 203 greying both with `not one run: thru would take 202 too`;
`[update profile]`; and an import through Ctrl+O, the picker listing it among the show's. At 99
columns in layout A: the route edited to DMX-USB (its `failed` state), a run chosen in the panel
under the table, a missing `~` path refused, the import, and Enter choosing the new profile. No
error in the log but the routes' own. Docs: `docs/tui/guide.md` (F3's `[delete]`, PATCH, the reach,
`[update profile]` and its picture, now of a run; F8's `[edit…]` and its picture; the picker's
`[import…]`; the dialogs), the report's rows, Summary and "What the TUI is missing", the TUI notes
of GAP-37 to GAP-39 in `docs/dev/tui/engine-gaps.md`, and `CHANGELOG.md`.

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
- Some replies still print a path, and F4's controls now put them in the log: `delete cue L/C`
  (`deleted cueLists[8].cues[1]`), `cue L/C release`, `cuelist N tracking`, `rename cuelist` and
  `cuelist N chase`. The refusals are in words; these are the answers to lines that worked. Found on
  2026-11-09.
- `cue L/C effect <id> <prop> <value>` replies with a path too, and F5's EFFECT panel now puts that
  in the log. Found on 2026-11-09.
- `playback N <prop> <value>` replies with a path too, and F1's PLAYBACK panel now puts that in the
  log. `go` on a playback whose `gotoCue` its list lacks, after a change of list, was not checked.
  Found on 2026-11-09.
- `rename page N "…"` replies with a path too (`set pages[2].name to "Finale"`), and F1's page
  `[rename…]` now puts that in the log. Found on 2026-11-10.
- With `--faders` below a page's slot count, ← → and the selection that follows a change of slots
  use only the first `faders` slots, in edit mode too, where the grid has them all: a change of those
  slots moves a selection past them to the first. Found on 2026-11-10.
- `rename group N "…"` and `group N number M` reply with a path too (`set groups[4].name to "V"`),
  and F3's GROUPS now puts that in the log. So does a plain `delete group N` (`deleted
  groups[4]`), which F3 does not send. Found on 2026-11-10.
- `commands.effect_stop`, `effect_run` and `effect_remove` do not quote an id, so those controls
  fail on an effect id of two words, which only `id "my fx"` makes. `_rate_text` in the bridge does
  not escape a quote in a master's name. Found on 2026-11-09.

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

   ANSWER: (a), the recommended one (the user's standing word, 2026-11-09). Built in Phase 10.
3. **What F1's strips show** (Phase 9). The report says the playback's own buttons replace the fixed
   GO, ◂ and FLASH. On the club show, 18 of 20 strips would then have no GO.
   - (a) Only the playback's own buttons, as the show is built. Layout C's one button is the first.
     **Recommended:** the strip then matches the show, and Space still goes.
   - (b) The playback's own, with GO kept where it has none.

   ANSWER: (a), the recommended one (the user's standing word, 2026-11-09). Built in Phase 9.
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
