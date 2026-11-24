# Pending TUI and engine work: implementation plan

> Source: the user's request of 2026-11-08, to gather what is still pending and order it in
> phases, one conversation each. Written at `d628286`. It draws on five places:
> `docs/dev/tui/operations-report.md` ("What busk is missing", "What the TUI is missing" and "Side
> findings"), `docs/plans/tui-rig-plan.md` §9, and what the last conversation left open. §5 holds
> the plan's own calls, which the user may veto, and §8 the questions only the user can answer.
> On 2026-11-12 the user added Phases 26 to 36. They cover the gaps found by comparing busk with a
> grandMA3 show-programming howto (§7's items of that date). On 2026-11-18 the user added Phase
> 37, F9's MONITOR, from GAP-13 (§7). On 2026-11-23 the user added Phases 38 to 41: surfaces and
> bindings set up on F9 (§7).

## 1. How a phase runs

- **One phase, one conversation.** A new phase starts a new conversation, which reads this
  section, its phase in §6 and the files the phase names. A phase relies on the code and on the
  Done notes of the phases before it, not on what another conversation remembers.
- **Size.** The six build conversations of the rig plan (groups A to F) added 68 to 119 tests
  each. Every phase here is sized to that or less.
- **Engine first.** Phases 2 to 5 give every later control its line, so no control is left inert
  or waiting on busk. Phase 14 is the one exception: a question gates it, nothing else needs it,
  and its engine step comes first inside the phase. Phases 20 to 22, added on 2026-11-11, and
  Phase 25 are built the same way: one item each, its engine step first, then the control that
  uses it. The TUI step keeps the TUI phases' rules below. Phases 26 to 36, added on 2026-11-12,
  follow the same pattern. Where an item's engine work is too large to share a phase, it gets a
  phase of its own before the TUI's: 27 before 28, and 29 before 30. Phase 31 is engine only.
  Phase 37, added on 2026-11-18, follows it too. Phases 38 to 41, added on 2026-11-23, give the
  engine phases of their own: 38 before 39, and 40 before 41.
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

Each pending item, what it is at `d628286`, where it goes, and what Phase 16's audit found it
to be at `f851165`.

| From | Item | At `d628286` | Goes to | At `f851165` (Phase 16) |
|---|---|---|---|---|
| busk missing 1 | Delete, change or rename an effect template | open | Phase 2, GAP-31 | done: three lines |
| busk missing 2 | A playback for an existing list; another list by number | open | Phase 3, GAP-34 | done: `playback add`, `playback N cuelist L` |
| busk missing 3 | Remove one effect from a cue by its id | open | Phase 2, GAP-32 | done: `cue L/C effect <id> remove` |
| busk missing 4 | A fixture's mode and profile | closed (GAP-26) | nothing | closed |
| busk missing 5 | An empty cue list | open | Phase 2, GAP-33 | done: `cuelist add` |
| busk missing 6 | Deletes that cascade for presets, cue lists, playbacks | open | Phase 4, GAP-36 | done: all five kinds |
| busk missing 6 | One entity per line | open for fixtures (rig §9 below); the rest stays (§7) | Phase 5, GAP-38 | done for fixtures (`thru`); presets, cues and lists one per line (§7) |
| busk missing 7 | Playback and cue list settings named by `help` and `expected()` | open | Phase 3, GAP-35 | done: named, offered, `none` |
| busk missing 8 | Removing and switching a route | closed (GAP-23) | nothing | closed |
| busk missing 9 | Editing a route | open | Phase 5, GAP-37; F8 in Phase 13 | done: `route <id> change`; F8's `[edit…]` |
| TUI missing, F1 | The playback's own buttons | open | Phase 9 | done: in layouts A, B and C |
| TUI missing, F1 | `record slot` on an empty slot | open | Phase 9 | done: `[record]` |
| TUI missing, F4 | Delete a cue, re-record it, record at a number, release targets | open | Phase 6 | done |
| TUI missing, F4 | New list; delete, rename, tracking and chase settings of a list | open | Phase 6 | done |
| TUI missing, F5 | Edit an effect's settings; `effect clear` | open | Phase 7 | done, within GAP-41's limits |
| TUI missing, F5 | Add a template | open | Phase 8 | done: `[+ template…]` |
| TUI missing, Playbacks | View and edit their configuration | open | Phase 10 | done: F1's PLAYBACK panel |
| TUI missing, Playbacks | Add and delete one; page slots | open | Phase 11 | done: F1's edit mode |
| Side finding 1 | `record cue L/C remove` replies `0 effects` | **fixed** in `4abcf1f`, checked: `removed 0 values, 1 effect from cue 90/1` | Phase 1 takes it out of the report | out of the report |
| Side finding 2 | `confirmation()` asks nothing before most deletes | open | rule in §1, applied by Phases 6, 7, 12 | applied, but not to F6's `[replace]` and `[remove]`: Phase 17, which made them ask |
| Rig §9 | Groups | open | Phase 12 | done: F3's GROUPS |
| Rig §9 | `park` and `unpark` | open | Phase 12; GAP-22 in Phase 5 | done: F3's PARK, F7's PARKED, `src` reads `park` |
| Rig §9 | Cascades for presets, cue lists, playbacks, pages | open, as above | Phase 4, GAP-36 | done, as above |
| Rig §9 | Editing a route in place | open, as above | Phase 5, GAP-37; F8 in Phase 13 | done, as above |
| Rig §9 | Deleting or patching several fixtures at once | open | Phase 5, GAP-38; F3 in Phase 13 | done: a selection that is one run |
| Rig §9 | F1 C's `[location…]` | open | Phase 1 | done |
| Rig §9 | Importing a profile; `profile update` | open | Phase 5, GAP-39; F3 in Phase 13 | done: `[import…]`, `[update profile]` |
| Rig §9 | A split patch | open | Phase 14, if Q4 says so | dropped: Q4 (a) |
| Rig §9 | Editing in the table's cells | open | Phase 15, if Q5 says so | done: a dialog per cell |
| Last conversation | Refusals with a document path: `group N number M`, `route add 1 sacn 0`, a mode or profile past channel 512 | open | Phase 1 | done; an Art-Net port address still printed a path (§7), fixed in Phase 18 |
| Last conversation | The same for a plain `delete fixture N` | open | Phase 4, GAP-36 | done |
| Last conversation | The log does not wrap | open: `LogView` is built with `wrap=False` | Phase 1 | done |
| Last conversation | A step on `Bridge.standalone` takes about 3 s | **closed** by `d628286`: Textual's idle wait counted the engine thread's CPU and ran to its 1 s cap. `test_tui_e2e.py` went from 1,255 s to 107 s | nothing | closed |
| Last conversation | A show with `refreshHz` 41 to 44, or a fixture below 1, no longer loads | open: the user's call | Q1, Phase 1 | done: Q1 (b) |
| Last conversation | The other decisions in the Done notes | stay as built unless vetoed: rig plan §4, its Done notes, and the Fixed notes of §8 and §11 | the user | none vetoed so far |
| Phase 16's audit | F4's toggle back to a chase rounds the list's rate and crossfade, and fails on a speed master with a quote in its name | not yet found | Phase 17 | open; fixed in Phase 17 |
| Phase 16's audit | F1's `[GT]` stays live on a goto cue its list lacks, and does nothing | not yet found | Phase 17 | open; fixed in Phase 17 |

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
| 17 | The audit's three bugs: F4's chase toggle, F1's `[GT]`, F6's questions | TUI | 16 | |
| 18 | Small bugs: refusals in words, a mode that changes nothing, effect ids, `[chase…]`, F1's `--faders` | busk, TUI | | |
| 19 | Replies in words for the lines that work | busk | | |
| 20 | One undo step for an encoder drag (GAP-06) | busk, TUI | | Q6 |
| 21 | Removing a family's own timing from a cue (GAP-42), on F4's TIME | busk, TUI | 18 | |
| 22 | Moving and copying a cue (GAP-43); F4's `[number…]` and `[copy…]` | busk, TUI | 19 | |
| 23 | F4 counts every other family's entries (`also`) | TUI | | Q7 |
| 24 | A mode or profile change that loses elements in use, refused in words | busk | | |
| 25 | Loading a cue into the programmer (GAP-44); F4's `[load]` | busk, TUI | | Q8 |
| 26 | Odd and even in a selection (GAP-45); `[odd]` `[even]` | busk, TUI | | Q9 |
| 27 | A cue list's tracked states (GAP-46), `list cue L/C`, block cues (GAP-47) | busk | | |
| 28 | F4's track sheet, and `[block]` | TUI | 27 | Q10 |
| 29 | Timing per target, with a fan (GAP-48) | busk | | Q11 |
| 30 | F4's timing per target | TUI | 29 | Q11 |
| 31 | A recorded spread follows its group (GAP-49) | busk | | Q12 |
| 32 | Effect shapes: a layer's cycles (GAP-50), five more library templates; F5's `[cycles…]` | busk, TUI | | |
| 33 | Reusable effect settings (GAP-51); F5 | busk, TUI | 32 | Q13 |
| 34 | A DMX readout: `list dmx` (GAP-52); F8's channel values | busk, TUI | | |
| 35 | Masters renamed and deleted (GAP-53); made, renamed and deleted on F7 | busk, TUI | 33, if built | |
| 36 | F2's option chips, the strobe cap on F7, the show's title | TUI | | |
| 37 | What comes in from the surfaces (GAP-13); F9's MONITOR, raw value and learn mode | busk, TUI | | Q14 |
| 38 | Surfaces renamed, deleted and changed (GAP-60, GAP-61); the MIDI devices plugged in (GAP-62) | busk | | |
| 39 | F9: surfaces added, changed, renamed and deleted; pickup in one click | TUI | 38 | |
| 40 | One binding at a time, deleted and changed (GAP-63); what `bind` should refuse | busk | | Q15 |
| 41 | F9: bindings added, changed, moved and deleted from a form | TUI | 39, 40 | Q15 |

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

Added on 2026-11-11, for Phases 18 to 23:

10. **`50%` and a sign are refused where busk reads seconds, and in a Bézier point,** as F4's
    forms (Phase 15) already refuse them. A show file that stores such a value still loads: only
    the console's reading changes.
11. **A mode or profile that changes nothing is refused in one line,** and spends no undo step. A
    profile line that brings a newer revision of the same profile does change something, and goes
    through.
12. **A reply in words names the thing as the console does, then the change.** The generic edit
    (`show <path> …`) and `submit()` keep their paths, as call 9 says for refusals.
13. **`cue L/C number M` may pass its neighbours:** the cue moves to its place in the order.
    `cue L/C copy [L2/]M` copies a cue into its own list or another. Moving a cue to another list
    is not one line: copy it, then delete it, two undo steps.
14. **`cue L/C time <family> none`** removes a family's own timing whole: its fade, delay and
    curve. Sending the family again without a curve still removes the curve alone, as now.

Added on 2026-11-11, for Phase 24:

15. **A mode or profile change that loses elements in use is refused, with no cascade.** The line
    names what uses them, as a cascade's question does; the operator edits those first, or deletes
    the fixture with `cascade`. A `cascade` on `fixture N mode` would be a gap of its own, not
    planned.

Added on 2026-11-11, for Phase 25:

16. **`load cue L/C` replaces the programmer:** its values, effects and selection become the
    cue's, so what `[replace]` records back is the cue and the edit. It is one programmer step,
    which `undo` takes back.
17. **The line is `load cue L/C [only <family>…]`,** beside `record cue L/C`, and reads `only` as
    `record` does.
18. **What the programmer cannot hold comes as a value per target.** It holds a value or a preset
    reference per slot, so a group's entry, a spread and per-target values come target by target.
    Recording back finds the groups again by the cover, unless `freeze`; a spread comes back as
    per-target values (since Phase 31, a spread on a group comes back as the spread).

Added on 2026-11-12, for Phases 26 to 36:

19. **GAP-45 to GAP-53** are numbered here, in the order they are built.
20. **A new cue list still starts without tracking,** unlike grandMA3, where tracking is the
    default. A busking look is a list of one cue, a script that records cues keeps its meaning,
    and F4's `[tracking on]` is one click. No phase changes this.
21. **Odd and even count positions in the targets' order, not fixture numbers.** `sel fixture 108
    thru 101 odd` gives 108, 106, 104 and 102, as a spread and an effect's phase count. A target
    is an element, so a pixel bar's cells count one by one.
22. **A tracked state is the list played by GO from its first cue,** read from the compiled show.
    It is not what the stage shows, which other playbacks, the masters, park and the programmer
    change.
23. **A master in use is refused, not cascaded,** as a used template is (call 3). An effect's or a
    chase's rate cannot lose its master and still run. Only the bindings that name it go, under
    `cascade`.
24. **`list dmx` prints the last frame:** what goes out, after the masters, blackout, park and
    limits, not what the programmer or a cue holds.

Added on 2026-11-18, for Phase 37:

25. **MONITOR shows what reaches the bindings,** after a backend turns a message into an input. A
    MIDI message busk cannot bind (a program change, sysex) never shows, and nor does the web
    remote, which sends commands, not inputs.
26. **busk keeps every input; the TUI merges** consecutive inputs from one control, as the spec
    says. A frontend that wants each message has them.
27. **The monitor speaks `bind`'s words** (`cc 1 48`), not the spec's `cc ch1 #48`, so what the
    operator reads is what they type, and learn mode's pre-fill is the same text. A pitch bend,
    which `bind` cannot take, reads `bend 1`.
28. **No prompt line lists the inputs.** The read is for frontends, as `LiveShow.surfaces` is.

Added on 2026-11-23, for Phases 38 to 41:

29. **GAP-60 to GAP-63** are numbered here, in the order they are built.
30. **A surface with bindings goes only with `cascade`,** which takes them, after busk's question:
    no binding outlives its surface. A surface with none goes with a plain `delete`, which asks
    nothing.
31. **A surface keeps its kind.** `surface "<name>" change` gives how busk finds it, whole, as
    `route <id> change` does, so an option left out goes back to `surface add`'s default. Another
    kind is a delete and an add, since a binding's control belongs to its surface's kind.
32. **A MIDI surface is named by its device,** as `surface add midi` names it, and F9's form has
    no name for it. `[rename…]` renames it afterwards, a second undo step.
33. **The device chips are the MIDI input devices of the console's host,** read as the form opens,
    without ALSA's numbers and without ALSA's own `Midi Through`. A device not plugged in is typed.
    Tab does not offer them at the prompt: `busk run` names the ports when a device is missing.
34. **Pickup is two chips,** a click each, and asks nothing, as busk asks nothing.
35. **The pre-fills give way to controls:** `[pickup…]`, `[bind…]`, `[unbind…]` and
    `[feedback…]`. The lines still work typed, and `thru` stays typed. The surface's `[learn]`
    stays as Phase 37 built it, a pre-fill for the operator who types; the form's `[learn]` is the
    same read, for the form.
36. **A binding its surface cannot use is refused at the prompt,** not warned: a channel outside 1
    to 16, a number above 127, a control of another kind than the surface's, `display` on MIDI. A
    show file that holds one still loads, with the validator's warning, as call 10 says for
    seconds.

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

**Dropped** (2026-11-10): Q4 is (a). GAP-40 stays unused.

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

   **Done** (2026-11-10). As planned. `src/busk_tui/widgets/cue_dialogs.py` has `TimeDialog` and
   `CurveDialog`, on a `CueDialog` base, as `RateDialog` is the chase form's. `[delay…]` is a
   `FormDialog`, and `[follow…]`, `[wait…]` and `[rename…]` are `TextDialog`s. Also new:
   `commands.cue_time`, `cue_trigger`, `rename_cue` and `exact_pair`,
   `attributes.TIMING_FAMILIES`, and the model's `FamilyTiming`, which holds a family's own curve,
   now read by the bridge. `cuetable.edit_prefill`, `commands.cue_time_prefill` and
   `rename_cue_prefill` are gone. Which the user may veto:
   - **A form that changes nothing sends nothing**, as F5's and F8's do.
   - **`[time…]` has a `for` row of chips: `cue` and busk's six families.** A family's fade and
     delay start at its own, else at what it takes now, the cue's in. A family with no timing of its
     own is sent even unchanged, since sending is what makes it its own. busk sets a family whole,
     so its own curve rides along in its line, and the dialog says so. No chip changes a family's
     curve, and no line removes a family's own timing (§7).
   - **`[delay…]` and `[curve…]` keep the fade times to every digit** (`exact_pair`). The
     pre-fills wrote the table's two decimals, so finishing one changed a fade of 1.234 s to 1.23.
   - **`[follow…]` and `[wait…]` start at 0 while the cue has another trigger**, and say which
     (`now: wait 8`, `now: a manual GO`).
   - **`[go…]` stays a pre-fill**: `cue 9/3 go` is a whole line, with nothing to fill in. The plan
     did not name it.
   - **The forms take seconds as `cue L/C time` takes the cue's own**: no sign, no `%`. busk also
     takes `50%` in a family's fade and a trigger's delay, and `-0` in a Bézier point, which the
     forms refuse.
   - **`[rename…]` refuses an empty name**, as every rename dialog of the TUI does, though busk
     takes `rename cue 9/1 ""`.
   - **TIME opens with the keyboard in `in`**, its text selected, so a number typed replaces it.
     Shift+Tab reaches the chips. CURVE opens on its chips.
   - The cells are still not stops of the pane cursor: `[time…]` and the rest under the table are,
     and now open their dialogs.
2. **The docs:** the TUI plan's §3 item 7 and §8, the spec's open question 4, the guide.

   **Done** (2026-11-10). Also the report's rows, Summary and "In short", `CHANGELOG.md`, and the
   note on GAP-40 in `docs/dev/tui/engine-gaps.md`.

Verify: each kind, with per-family timings; Esc changes nothing; the prompt keeps the keyboard when
no dialog is open.

**Phase 15 checks** (2026-11-10). The whole suite: 6,183 passed and 1 skipped, in 7:37 with `uv run
pytest -n 6`. `ruff check`, `ruff format --check` and `mypy src` clean. No change to `src/busk/` or
the engine's tests. The four TUI test files the phase touched, 519 tests, pass on Textual 8.2.0. A
first run had F6's `test_f6_records_and_changes_presets_from_controls_on_the_real_engine` fail under
`-n 6`; it passed alone and in a second run of the four files, and this phase does not touch F6.
The perf gate: 7 passed, no overruns, F4 at +0.200 core, F3 at +0.193, F1 B at +0.216. 43
mutations of the new code: 42 caught at once. One needed a check of its own, and has it: on a cue
at 0 s, a family with no timing of its own, left at 0, must still be sent. busk's words and checks
are tested against the forms': the families after `cue 9/1 time `, the curves after `cue 9/1 time
1 `, the seconds and the Bézier points busk takes. A new test in `tests/tui/test_tui_e2e.py` runs
on the real engine: cue 9/3's fade times typed into TIME (Esc and an unchanged form send nothing),
cue 9/2's position, with a curve typed at the prompt, changed in TIME with the curve kept, the
delays with the fades kept, a Bézier, cue 9/5's follow made a wait from `[wait…]`, which says `now:
follow 4`, its rename, and `undo`. A real `busk-tui --state-dir …` under `busk run` on the club
show, with real mouse clicks in a pty: at 150 columns in layout B, a click on each of the time,
delay, curve and wait cells, Esc on TIME, the fade times typed, the delays, `[bezier]` by ← from
`[linear]` and its points, a wait on 9/5, `[rename…]` from the `edit` row, and `undo`. At 99
columns in layout A, the TIME chips wrapped on two lines, position's own from the keyboard
(Shift+Tab, → →, Tab, `6`), FOLLOW refusing `-1` and staying open, and the prompt taking `status`
after Esc. No error in the log.

### Phase 16: Audit, and the user's check

1. **Audit.** Every row of §2 against the code, and every row of the report. Rewrite the report's
   Summary and "In short". Check the guide's "Work in progress" note.

   **Done** (2026-11-11), at `f851165`, changing docs only:
   - **The engine side.** A script ran the busk line of each of the report's rows, 127 lines, each
     on a fresh copy of the club show, with `confirmation()` where a row says busk asks. Every line
     did what its row says. The scripts are in this conversation's scratchpad, not in the repo.
   - **The TUI side.** Each builder of `commands.py` has a caller in the page or widget its row
     names, but `flash`, `undo` and `redo` (§7). Of the controls that send a line §1 names (a plain
     `delete`, `record … replace` or `remove`, `effect clear`), all ask first but F6's `[replace]`
     and `[remove]`, which the presets plan built before §1's rule. F7's `[unpark all]` asks too.
   - **§2** has a column for what each row is at `f851165`. Every row is done, closed or dropped as
     its "Goes to" said. Two leave something in §7: presets, cues and lists still take one per
     line, and an Art-Net port address out of range is still refused by path.
   - **The report:** its header names the audit; the Summary marks what is typed; "In short", "What
     the TUI is missing" and the end of "What busk is missing" are rewritten. Five rows called a
     `number M` a generic property: each has been a line of its own since Phase 1 (`_renumber`,
     `_renumber_cue`), and a cue's takes the number bare. The side findings list every control
     that asks, the audit's findings and every reply with a path.
   - **Three findings, written down and not fixed**, since this phase changes docs only (§3): F4's
     toggle back to a chase rounds the list's rate and crossfade and fails on a speed master with a
     quote in its name; F1's `[GT]` stays live on a goto cue the list lacks, and does nothing; F6's
     `[replace]` and `[remove]` ask nothing. All three are in §7 and the report's side findings,
     and at the user's word they are Phase 17.

   Which the user may veto:
   - **The guide's note no longer says "Work in progress".** It is "What it covers": every page,
     what the edit modes build from controls, and what is still typed. The TUI plan's phases and
     this plan's are built, and the user's check (step 2) tests them, not new work.
   - No `CHANGELOG.md` entry: nothing an operator meets has changed.
2. **The user's check** on a rig, with the shipped shows: their step, as in the rig plan's step 15.

**Phase 16 checks** (2026-11-11). The whole suite: 6,183 passed and 1 skipped, in 8:12 with `uv run
pytest -n 6`, as at Phase 15. A first run had two failures, both timed under the suite's load, and
both passed alone and in the second run: `test_engine_host.py`'s tick count over 2 s, and
`test_tui_e2e.py`'s busy timer reading `save 1.1s` where it expects under a second. `ruff check`,
`ruff format --check` and `mypy src` clean. No code changed, so no perf gate, Textual 8.2.0 run or
real `busk run`.

### Phase 17: The audit's three bugs

The user's word of 2026-11-11: the three bugs Phase 16's audit found, as a small phase after the
user's check (Phase 16, step 2). A TUI phase: no change to `src/busk/` (§1). Code:
`src/busk_tui/pages/cues.py`, `src/busk_tui/commands.py`, `src/busk_tui/widgets/playbacks.py`,
`src/busk_tui/widgets/preset_panel.py`. Tests: `tests/tui/test_tui_cues.py`,
`test_tui_commands.py`, `test_tui_busk.py`, `test_tui_presets.py`.

1. **F4's toggle back to a chase sends the list's settings as they are.** `mode_line` builds its
   line from `CueListInfo.chase`, `bridge._chase_text`'s words, through `commands.cuelist_chase`.
   So it writes the rate with `:g` (`hz 1.23456789` as `hz 1.23457`), the multiplier too, and the
   crossfade with `commands.number` (`0.125` as `0.12`), and leaves a quote in a speed master's
   name unescaped, so busk refuses the line (`no speed master 'Say '`) and the list stays a
   sequence. Build it from `CueListInfo.rate` and `crossfade` with `commands.chase_settings`, as
   `[chase…]`'s form does, each number through `commands.exact`, the master quoted. A list with no
   chase settings (`rate` is `None`) still sends `cuelist N chase bpm x 1`. Take out of
   `commands.cuelist_chase` what is then unused. `CueListInfo.chase` stays for F4's meta line and
   F1's strips, which only show it.

   Verify: a sequence, then a chase and back, keeps the list's `chase` exactly as busk stored it,
   for a rate of many digits, a multiplier of many digits, a crossfade of `0.125`, every direction,
   a beat rate with one speed master (no name in the line) and with several, and a master named
   `Say "hi"`; a list never chased gets `bpm x 1`. Nothing else sends `_rate_text`'s or
   `_chase_text`'s words (grep), so their quote and `:g` are only shown; §7's item says so.

   **Done** (2026-11-11). `mode_line` (`pages/cues.py`) builds the chase from `CueListInfo.rate`
   and `crossfade` with `commands.chase_settings`, each number through `commands.exact`;
   `commands.cuelist_chase(N)` keeps only `bpm x 1`, for a list with no settings, and the contract
   test lost its `cuelist chase kept` row. `test_tui_cues.py` runs the round trip on busk itself:
   seven chases (Hz and beat, many digits, `0.0000001`, every direction, crossfades `0.125`, `1`
   and `0.333`, one master, the first and the second of two, `Say "hi"`), each made a sequence and
   toggled back, keep the stored `chase` equal; on the old code four of the seven failed. Song, never
   chased, gets `bpm x 1`. The grep found only drawing code (F4's meta line, F1's strips, F5's rate
   cells). `bridge._chase_text` stays, for those.

   Found, and left as the step says (§7): on a show with several speed masters, busk refuses `bpm
   x 1` for a list never chased, so the toggle there is refused in one line; and `[chase…]`'s form
   starts its crossfade field with `:g`, so `0.1234567` goes back as `0.123457` if left as it is.
2. **F1's `[GT]` is grey on a goto cue its list lacks.** `_idle_reason` greys a `goto` only when
   there is no `gotoCue`. After `playback N cuelist L` the number can name no cue of the new list:
   busk warns once, at the change, and a press then does nothing and says nothing. Grey it then
   too, with the reason in the hint row (`goto: cue list 11 has no cue 4`), comparing numbers as
   busk does (`cue_number_key`, the TUI's `cue_key`), so `04` is cue `4`. The PLAYBACK panel's
   `[goto…]` row is unchanged.

   Verify: a goto cue the list has, one it lacks, one it gets back by `record cue`, and `04`
   against cue `4`; the strip redrawn when the list or its cues change, in layouts A, B and C; the
   perf gate on F1, since the strips' update path reads it.

   **Done** (2026-11-11). `_idle_reason` (`widgets/playbacks.py`) takes the playback's cue list in
   place of `has_cues`, and greys a `goto` whose `gotoCue` no cue of it has, by `cue_key` (busk's
   `cue_number_key`, the same pattern): `goto: cue list 11 has no cue 4`. The reason is in
   `own_buttons`, so each layout's `Built` changes with it and the strip is drawn again; nothing
   else changed on the update path. busk writes a typed `playback 9 goto 04` back as `"4"`, so `04`
   reaches the TUI only from a show file; the unit test covers it, and `4.0` against `4` (another
   cue, as in busk).
3. **F6's `[replace]` and `[remove]` ask first**, as §1's rule says and as F4's and F3's do. The
   questions follow F4's: `Replace what preset color 1 "Blue" holds with the programmer?` and
   `Remove the programmer's attributes from preset color 1 "Blue"?` `[merge]` and `[record]`
   ask nothing, as before.

   Verify: each question, its yes sending the line and its no sending nothing; the pane cursor's
   Enter on each; the grey state with nothing to record unchanged.

   **Done** (2026-11-11). `PresetPanel.write` passes `RunLine.ask` for `replace` and `remove`. The
   pane cursor's stops for the three writes now call `write` (an `Item` with an `action`, labelled
   with the line as before) where they ran the line, so Enter asks too; without that, the
   question would have been the mouse's only. A test that sets the stops back to the line fails.

Docs: `docs/tui/guide.md` (F4's toggle, F1's grey buttons, F6's `[replace]` and `[remove]`), the
report's side findings (the three go), §2's two rows and side finding 2, §7's items, and
`CHANGELOG.md` under Fixed.

Verify, besides each step's: a test on the real engine in `tests/tui/test_tui_e2e.py` for each
step; a real `busk-tui --state-dir …` under `busk run` on the club show, at 150 and 99 columns,
with the toggle on a list given a speed master named with a quote, `[GT]` grey after `[list…]`,
and F6's two questions.

**Phase 17 checks** (2026-11-11), on top of `1d68f2c`. The whole suite: 6,207 passed and 1
skipped, in 7:39 with `uv run pytest -n 6`. A first run, with other tests running beside it, had
two failures, both timed, which passed alone three times and in the second run:
`test_engine_host.py`'s `test_a_root_that_stops_reading_skips_frames_and_never_the_tick`, and
F6's real-engine preset test, whose click on a `+ record` tile did not take (Phase 15 saw that once
too). `ruff check`, `ruff format --check` and `mypy src` clean. The new tests pass on Textual
8.2.0, the three on the real engine too. The perf gate: 7 passed, F1 B +0.200, A +0.206 and C
+0.216 core, no overruns. Each step's tests fail on the code before it: step 1, five (four
round trips and the numbers test); step 2, six (three numbers and the three layouts); step 3, five,
and the cursor test alone when the stops run the line again. The three real-engine tests fail on
it too.

A real `busk-tui --state-dir …` on the club show, in a pty at 150 columns (layout B) and 99
(layout A). F4: after `master add speed "Say \"hi\""`, a chase on it at `x 1.23456789` with a
crossfade of `0.125`, and `cuelist 10 sequence`, the toggle read and sent `cuelist 10 chase bpm
"Say \"hi\"" x 1.23456789 random crossfade 0.125`, busk took it, and the button became `[cuelist
10 sequence]`; the meta line still draws `x 1.23457` and the quotes bare, which only show (§7).
F1: `[edit]`, P9, `[list…]`, Circle: `[GT]` grey, `goto: cue list 11 has no cue 4` in the hint
row under the mouse, and a click sent nothing. F6: on Blue with Red loaded, `[replace]` asked and
**n** logged `cancelled: record preset color 1 global replace`; `[remove]` asked and **y** sent
`record preset color 1 remove`. No error in the log.

### Phase 18: Small bugs

The user's word of 2026-11-11: §7's simple bugs, together in one phase, as Phase 1 was. busk and
TUI: the busk steps come first, with the engine's tests, and the TUI steps keep the TUI's rules
(§1). Code: `src/busk/console/parser.py`, `src/busk_tui/commands.py`,
`src/busk_tui/widgets/chase_dialog.py`, `src/busk_tui/shell.py`.

1. **An Art-Net port address out of range is refused in words.** `_route_fields` reads
   `net.sub.universe` and checks only its shape, so `route add 1 artnet 200.0.0` is refused by
   path (`output.routes[1].portAddress.net: Input should be less than or equal to 127`). Check the
   net (0 to 127), the sub-net and the universe (0 to 15) there, as the sACN universe is checked a
   few lines above. `route <id> change` reads the same fields, so this fixes it too.

   Verify: each of the three parts at its limits and one past, in `route add` and in `route <id>
   change`; `expected()` unchanged.

   **Done** (2026-11-11). `_route_fields` checks each part after its shape: `expected an Art-Net
   net from 0 to 127, got 200`, and `sub-net` and `universe` from 0 to 15. `route <id> change`
   reads the same fields, so it refuses the same. `test_console.py`'s refusal table has each part
   one past, in both lines (with `expected()`, `confirmation()` and a script), and its edge table
   `0.0.0` and `127.15.15` in both. F8's route form already checked these ranges, and its
   agreement test with busk passes as before.
2. **Seconds and Bézier points are read the way the cue's own times are.** `_cue_verb` reads a
   family's fade and delay (`cue L/C time <family> …`) and a trigger's delay (`cue L/C follow|wait
   <d>`) through `number`. So busk takes `50%` as half a second, and refuses `-1` by path
   (`cueLists[8].cues[1].timing.perFamily.intensity.fade: Input should be greater than or equal to
   0`). Read them as `pair` reads the cue's own times (`_SECONDS`: no sign, no `%`). `curve` reads
   a Bézier point through `number` too, and the validator refuses `-0.5` and `2` by path: read it
   the same way and check it from 0 to 1 in the parser. Grep the parser for its other `number(`
   reads of seconds (`programmer fade` is one), treat them the same, and name them in the Done
   note.

   Verify: each field refuses `50%`, `-1` and `-0` in one line that names the field, and takes
   what `pair` takes; a Bézier point of `-0.5` or `2` refused in one line, `0` and `1` taken;
   F4's TIME, CURVE, FOLLOW and WAIT forms still send lines busk takes (their tests against
   busk's checks, Phase 15).

   **Done** (2026-11-11). `_Parser.seconds(what, top=None)` reads one token as `pair` reads each of
   its own (`_SECONDS`: no sign, no `%`), at most `top` if given, and refuses with `expected
   <what>, got '<text>'`. The name `unsigned` was taken (`set`'s plus-sign check). The grep found
   these seconds read through `number`, and all now go through `seconds`: a family's fade and
   delay; `follow` and `wait`'s delay; `fade` (the programmer's: `fade -1` was **taken**, as
   `programmer fade -1 s`); `release N <t>` and `release all <t>` (refused in words before, by the
   command layer); and `effect add … fadein <t>`. `release all` still decides whether a time
   follows by `_NUMBER`, so `release all -1` is refused, not read as no time. A Bézier point is
   `seconds("a Bézier control value from 0 to 1", 1)`; the old `what` lacked the range, so
   `test_console_parser.py`'s row for a short Bézier gained it. The `what`s are unchanged
   otherwise, so Tab's hints are too. `test_console.py`'s refusal table has `50%`, `-1`, `-0`
   and `+2` for each of the eight fields and five Bézier rows; its edge table, the values that
   still run. F4's forms and busk now agree on every field: `test_a_time_form_and_busk_agree_on_seconds`
   (which said busk takes more for a family and a trigger) and the Bézier agreement test now check
   every field both ways, `-0`, `+2` and `50%` included.
3. **A mode or profile that changes nothing is refused.** `fixture 101 mode 16ch`, on a fixture
   that already runs 16ch, goes through and spends an undo step (`undid: fixture 101 runs 16ch`).
   `_fixture_mode` refuses it in one line (`fixture 101 already runs 16ch`). `_fixture_profile`
   refuses the same profile, revision and mode. F3's lit chip already sends nothing, so only the
   prompt meets this.

   Verify: the same mode refused, with nothing on the timeline; the same profile and mode refused;
   the same profile at a newer library revision taken (§5, call 11); another mode taken.

   **Done** (2026-11-11). `_fixture_mode` refuses the mode the fixture runs (`fixture 101 already
   runs 16ch`), by id, so a name in any case and the mode's id are refused alike. `_fixture_profile`
   refuses when the profile's id and revision and the mode's id are the fixture's (`fixture 101
   already runs Generic Spot 16ch, 16ch`). **A newer library revision never arrives through this
   line:** `_profile` takes the show's copy when it has one (with its `warning:` note), so with
   only the library newer, the line changes nothing and is refused; `profile update` brings the
   library's. What the line does change is a fixture whose `profileRevision` is behind the show's
   copy (a show file can hold one, with a warning): that is taken, and sets the revision.
   `test_fixture_mode.py` has both, the same mode by name, other case and id with `nothing to
   undo` after, and another mode taken. Three tests sent the mode a fixture runs and now meet the
   refusal: the mode test of `test_fixture_mode.py` (it now starts fixture 1 elsewhere),
   `test_console_prompt.py`'s `fixture 101 mode 16ch` row (moved to its error rows), and
   `test_tui_commands.py`'s contract row `fixture mode`, which keeps its line and expects the
   refusal (`SAME_MODE`): no shipped profile has two modes, so on the club show no mode line
   changes anything, and the refusal still shows busk read the quoted mode and found it.
4. **Effect ids are quoted where they need it.** `commands.effect_stop`, `effect_run` and
   `effect_remove` write the id bare, so F5's run toggle and `✕` fail on an id of two words, which
   only `id "my fx"` makes. busk reads a quoted id (`effect stop "my fx"`). Write it through
   `commands.word`, as `cue_effect`, `cue_effect_remove` and `effect_replace` do.

   Verify: the three lines for `fx1` (bare) and `my fx` (quoted); F5's toggle and `✕` on such an
   effect on the real engine.

   **Done** (2026-11-11). The three builders write the id through `commands.word`. The contract
   table has the three lines for `my fx`, and its test adds `effect add "Circle" id "my fx"` so
   busk takes each. `test_f5_stops_runs_and_removes_an_effect_of_two_words_on_the_real_engine`
   types the effect, then stops, runs and removes it from F5's table; on the old code it times out
   at the stop.
5. **`[chase…]`'s crossfade field starts with every digit.** `ChaseDialog` fills it with `:g`, so a
   crossfade of `0.1234567` goes back as `0.123457` if the form is taken as it opened. Fill it
   through `commands.exact`, as the rate and the multiplier already are.

   Verify: crossfades of `0.1234567`, `0.125` and `1` come back unchanged through a form taken as
   it opened.

   **Done** (2026-11-11). `ChaseDialog` fills the field with `commands.exact`. `test_tui_cues.py`'s
   `test_the_chase_form_taken_as_it_opened_keeps_what_busk_stored` runs on busk itself: a chase at
   `hz 1.23456789 bounce` with each of `0.1234567`, `0.125`, `1` and `0.0000001`, F4's form opened
   on it and taken, and busk's stored `chase` equal after. On the old code `0.1234567` and
   `0.0000001` fail (the other two survive `:g`).
6. **F1's selection follows every slot in edit mode.** With `--faders` below a page's slot count,
   F1's edit grid shows every slot (`BuskPage` passes `None` to `visible_slots`). But the shell's
   `_redraw` keeps `follow` on `visible_slots(…, view.faders)`, and ← → `step` along those slots
   too. So with `--faders 8` on a page of 12, ← → never reach slots 9 to 12, and a change of the
   slots moves a selection there back to the first. Use every slot while F1 edits, as the grid
   does, and the first `faders` again when it stops.

   Verify: `--faders 8` on a page of 12: in edit mode ← → reach slot 12, and out of it they stop at
   8; in edit mode a change of slots keeps a selection on slot 10; leaving edit mode on slot 10
   moves the selection as `follow` does today; the perf gate on F1.

   **Done** (2026-11-11). `BuskPage.set_editing` posts `BuskPage.EditingChanged(on)`. The shell
   keeps `_f1_editing` from it, and `_follow_slots()` (out of `_redraw`) computes the slots with no
   cap while F1 edits, else `faders`, and moves the selection by `follow`; the message's handler
   calls it too, so entering and leaving edit mode refollow at once. Leaving on slot 10 moves the
   selection to the first playback (slot 10's index is past the eight slots); within them it stays.
   F1's edit mode stays on when another page shows, and so do the shell's slots: ← → there step
   along F1's grid, which is F1's selection. Three tests in `test_tui_playback_panel.py` (a page of
   12, `faders=8`) and one on the real engine (the club's Main, 13 slots, `--faders 8`), each
   failing on the old code.

Docs: `docs/console.md` where it shows one of these refusals, `docs/tui/guide.md` (F1's ← → in
edit mode), the report's side findings, §7's items, and `CHANGELOG.md` under Fixed.

Verify, besides each step's: tests on the real engine in `tests/tui/test_tui_e2e.py` for steps 4
and 6; a real `busk run --state-dir …` with the lines of steps 1 to 3.

**Phase 18 checks** (2026-11-11), on top of `531e452`. The whole suite: 6,290 passed and 1
skipped, in 7:56 with `uv run pytest -n 6`. `ruff check`, `ruff format --check` and `mypy src`
clean. The new TUI tests pass on Textual 8.2.0, the two on the real engine too. The perf gate: 7
passed, F1 B +0.172, A +0.183 and C +0.202 core, no overruns. Each TUI step's tests fail on the
code before it: step 4's real-engine test (it times out at the stop), step 5's round trip for
`0.1234567` and `0.0000001`, and step 6's three headless tests and its real-engine one.

A real `busk run club.show --state-dir … --threads` on the club show, the lines piped in: `route
add 1 artnet 200.0.0`, `0.16.0` and `0.0.16` each refused in one line, `127.15.15 unicast
127.0.0.1` added; `route <id> change 1 artnet 0.16.0` and `0.0.16` refused, `127.15.15 unicast
127.0.0.1` changed it; `cue 8/1 time intensity 50%` and `-1`, `… delay -0`, `follow -1`, `wait
50%`, Bézier points `-0.5` and `2`, `fade -1`, `release 1 -1` and `release all 50%` each refused
in one line naming the field, while `cue 8/1 time intensity 2 delay 0.5 bezier 0 0 1 1` and `fade
0.5` went through; `fixture 101 mode 16ch` and `fixture 101 profile "Generic Spot 16ch" mode 16ch`
refused (`already runs`), and three `undo`s took back the cue's timing and the route, then said
`nothing to undo`.

### Phase 19: Replies in words

The user's word of 2026-11-11: the lines that work but reply with a document path, which F1's,
F3's, F4's and F5's controls now put in the log (§7, five items). An engine phase. Code:
`src/busk/console/parser.py`. Tests: `tests/test_console.py`, `tests/test_session.py`, and the
goldens `tests/golden/cli/run-processes.txt` and `run-threads.txt`, which hold about 60 replies
with a path between them.

1. **The list.** A script, like Phase 16's, runs on a fresh copy of the club show each line the
   report's last side finding names, and each other line of `docs/console.md` that edits the show.
   It lists every reply that works and holds a document path (`cueLists[8]`, `pages[0].name`).
   The list goes in the Done note. Today it holds at least: every rename; every `number M`;
   `fixture N location {…}`; a plain `delete` of something unused; `cue L/C time`, `follow`,
   `wait`, `go` and `release`; `cue L/C effect <id> <prop> <value>`; `cuelist N sequence`, `chase`
   and `tracking`; `playback N <prop> <value>`; and `rename page`.

   **Done** (2026-11-11). The script ran 136 lines, each on a fresh copy of the club show, with
   `undo` and `redo` after each that worked, and listed 74 whose reply named a path:
   - every rename: a fixture, universe, group, preset, cue, cue list, playback, page and the show
     (`set meta.title to "Club"`);
   - every `number M`, of the same eight kinds;
   - `fixture N location {…}`;
   - a plain `delete` of something unused, of all eight kinds (`deleted cueLists[8].cues[1]`);
   - `cue L/C time`, both forms, `follow`, `wait`, `go` and `release`;
   - `cue L/C effect <id> <prop> <value>`;
   - `cuelist N sequence`, `chase hz|bpm …`, and each cue list property but `number` and the `none`
     lines (`tracking`, `wrap`, `name`, `chase.crossfade`, …);
   - each playback property but `number`, `cuelist` and the `none` lines, and `playback N goto`;
   - one the plan did not name: `surface "<name>" pickup soft|jump` (`set
     surfaces[0].faderPickup to "jump"`).

   Every other line already replied in words: `record`, every `add`, `patch`, `mode` and
   `profile`, the route, surface, binding and master lines, `park`, `limits`, `orientation`,
   `safety`, `profile … category`, the `none` lines and the cascades. Four replies held a path
   only in a warning, which the validator writes after the reply: `fixture 101 patch none`,
   `fixture 101 thru 102 patch none` and `delete universe 1 cascade` (`warning fixtures[0]: 'Spot
   101' is not patched; …`), and `playback 9 gotoCue none` (`warning playbacks[8].buttons[3]: A
   goto button needs …`). The script is `replies.py` in this conversation's scratchpad, not in the
   repo; after step 2 it lists none.
2. **Each line says what it did,** labelled through `_labelled`, as `cue L/C effect <id> remove`
   and `<property> none` already are: the thing as the console names it, then the change (§5,
   call 12). For example: `renamed cue 9/2 "Verse"`, `group 1 is now group 9`, `deleted cue 9/1`,
   `cue 9/3 follows after 0.5 s`, `cue list 9 is a sequence`. The label is also the undo step's,
   so `undo` says it too. A value too long for the line is cut, as `_short` cuts it.

   **Done** (2026-11-11). Each line's command is now a `BATCH` labelled with its words, holding the
   same edits, so the label is the reply and the undo step's. What they say, on the club show:

   | Line | Reply |
   |---|---|
   | `rename group 1 "Movers"`, `playback 3 name "…"`, `cuelist 9 name "…"` | `renamed group 1 "Heads" to "Movers"`; the show: `renamed the show "Club Night" to "Club"` |
   | `group 1 number 9`, `cue 9/2 number 2.5` | `group 1 is now group 9`, `cue 9/2 is now cue 9/2.5` |
   | `fixture 101 location {…}` | `set the location of fixture 101 to {"x": 1, …}` |
   | `delete cue 9/2`, `delete group 9` | `deleted cue 9/2 "Verse"`, `deleted group 9 "One"` |
   | `cue 9/3 time 1/3 delay 0/1 easeOut` | `cue 9/3 fades in 1 s, out 3 s, delay in 0 s, out 1 s, easeOut` |
   | `cue 9/2 time position 4 delay 1` | `cue 9/2 fades position over 4 s, delay 1 s` |
   | `cue 9/5 follow 4`, `cue 9/3 wait 8`, `cue 9/2 go` | `cue 9/5 goes 4 s after the cue before ends`, `… starts`, `cue 9/2 waits for GO` |
   | `cue 9/5 release group 1 only pan tilt` | `cue 9/5 releases pan, tilt of group 1` |
   | `cue 9/4 effect rainbow size 0.5` | `set the size of effect rainbow in cue 9/4 to 0.5` |
   | `cuelist 10 sequence`, `cuelist 9 chase bpm "Speed 1" x 2 bounce crossfade 0.25` | `cue list 10 is a sequence`, `cue list 9 is a chase: bpm "Speed 1" ×2, bounce, crossfade 0.25` |
   | `playback 3 priority 60`, `cuelist 9 tracking true` | `set the priority of playback 3 to 60`, `set the tracking of cue list 9 to true` |
   | `playback 9 goto 4` | `set the gotoCue of playback 9 to cue 9/4` |
   | `surface "nanoKONTROL2" pickup jump` | `set the pickup of surface "nanoKONTROL2" to jump` |

   In the code: `_Parser._who(head, path)` names an entity as the console does (`cue 9/2`,
   `preset color 1`, `cue list 9`, `the show`), and `_entity_at` finds it. `_set` takes `of`, and
   `_value` a `said`, to word a property line; without them the generic edit keeps its path. A
   plain `delete` of something unused replies its cascade's label, the words `delete … cascade`
   says when it leaves nothing. `_short` is now `busk.commands.edits.short`, so a name and a value
   are cut alike, at 60 characters. `_batch`, the unlabelled step, went with its two callers. A
   named setting busk's validator refuses now starts its error in words too (`error: set the
   ltpFaderMode of playback 3 to "sideways": rejected, …`); the issue lines under it are the
   validator's, with their paths.

   Which the user may veto:
   - **A rename names the old name and the new one,** where the plan's example had the new one
     alone, so `undid: renamed group 1 "Heads" to "Movers"` says what comes back.
   - **A delete names what went, with its name,** as a cascade's reply does (`deleted cue 9/2
     "Verse"`), where the plan's example had the number alone. A fixture has no name there, as in
     its cascade (`deleted fixture 401`).
   - **Names are in double quotes,** as the console reads them and the cascades write them. Older
     replies use single quotes (`added page 'Page 3'`, `recorded group 9 'One'`) and are left.
   - **A property is named as the model has it** (`flash.level`, `ltpFaderMode`), and its value
     as JSON (`"size"` in quotes), as `<property> none` already said `removed the exclusivity of
     playback 3`.
   - **A release names its targets as typed:** `cue 1/2 release 201` replies `cue 1/2 releases
     201`.
   - **Seconds and rates show with `:g`,** as `list cues` shows them, so a time of `0.1234567`
     reads `0.123457 s`. busk keeps every digit.
   - **Warnings keep their paths.** They come from the validator, after the reply, and `busk
     validate` prints the same.
   - **`surface "<name>" pickup`** is worded too, though the plan did not name it.
3. **The tests and goldens follow.** Only the replies change; each line's ops stay as they were.

   **Done** (2026-11-11). The 47 rows and tests of `test_console_parser.py` that failed now
   expect the same edits, in `labelled(<words>, …)`, a helper that replaced `batch`. The goldens
   changed by the 24 lines of the playback settings their script sends; their five `cue L/C
   timing.fadeIn` lines are the generic edit and keep their paths. New:
   `test_console.py`'s table of 46 lines on Appendix A, each with its reply, then `undo` and
   `redo` saying it again, and no path in it; a long name cut; the generic edit keeping its path
   (`show meta.title`, `cue 1/1 timing.fadeIn`, `fixture 101 name`); and a named setting refused
   with its words first. `test_session.py`: a command `submit()`ted to the session, labelled or
   not, names its path, and `undo` and `redo` repeat it. No TUI test held one of these replies.

Verify: step 1's script finds no path in a reply that works; the generic edit (`show <path> …`)
and `submit()` still reply with their paths; `undo` and `redo` repeat the new words; the TUI's tests
pass, changed only where they hold a reply (the bridge parses none, `bridge.py`'s docstring).

Docs: `docs/console.md`'s replies, the report's last side finding (it goes), §7's items, and
`CHANGELOG.md` under Changed.

**Phase 19 checks** (2026-11-11), on top of `bdafc9a`. The whole suite: 6,342 passed and 1
skipped, in 7:41 with `uv run pytest -n 6`. `ruff check`, `ruff format --check` and `mypy src`
clean. Step 1's script lists no reply with a path, and the generic edit's lines still name theirs.
No TUI file or test changed, so no perf gate or Textual 8.2.0 run. Docs: `docs/console.md` has a
note on replies; the report's last side finding is gone, and it gains the finding below; §7's
seven items say "Fixed there", and a new one is at its end; `CHANGELOG.md` has a Changed entry.

A real `busk run club.show --threads --state-dir …` on the club show, 23 lines piped in: each
rename, number, delete, `cue … time`, `follow`, `wait`, `go`, `release`, cue effect, `cuelist …
sequence`, `chase`, `tracking`, `playback … priority`, `goto`, `fixture … location`, `surface …
pickup` and `rename page` replied in words, as in step 2's table; `show meta.title "Club"`
replied `set meta.title to "Club"`; three `undo`s and a `redo` said `undid: set meta.title to
"Club"`, `undid: deleted page 3 "Page 3"`, `undid: added page 'Page 3'` and `redid: added page
'Page 3'`.

### Phase 20: One undo step for an encoder drag

The user's word of 2026-11-11. GAP-06, which `docs/dev/tui/engine-gaps.md` calls important: an F2
drag sends about ten `set` lines a second, each an undo step of its own, so undoing a drag takes
as many `undo`s. Its shape waits on Q6. The engine step comes first. Code:
`src/busk/session/timeline.py`, `src/busk/session/session.py`, `src/busk/console/parser.py`;
`src/busk_tui/widgets/encoders.py`, `src/busk_tui/commands.py`.

1. **GAP-06, under Q6's answer.** Under (a), the shape engine-gaps.md gives, kept to what a drag
   needs:
   - `undo group "<label>"` opens a group, and the programmer steps after it join it.
   - `undo group end` closes it. The timeline then has one step labelled `<label>`, holding the
     programmer as it was before the group's first step and after its last.
   - A show step, `undo`, `redo` or another `undo group` closes it first. So does a step that comes
     more than 2 s after the group's last one, which needs no timer.
   - A group with no step leaves nothing. Performance lines never wait and never join (GAP-12).

   Update engine-gaps.md's entry and Summary row, `docs/console.md`, `busk help` and `expected()`.

   Verify: 30 `set` lines in a group are one `undo` and one `redo`; each way a group closes; an
   empty group; a group never closed; a line from another thread during the group joins it (the
   group is the session's, and the guide says so); `LiveShow` and `OfflineShow`; the timeline's
   limit.

   **Done** (2026-11-17), under Q6 (a). The group lives in the timeline
   (`src/busk/session/timeline.py`: `Group`, `open_group`, `close_group`, and `push`, which grows
   the group's step in place), so the session only routes two new session-class commands,
   `UNDO_GROUP` (`label`) and `UNDO_GROUP_END` (`UndoGroupCmd`, `UndoGroupEndCmd` in
   `busk.commands.types`, so a binding may hold them too). The parser's `_cmd_undo` reads the
   lines. GAP-06's entry and Summary row are in engine-gaps.md; `docs/console.md` (the Session row
   and a note), `busk help`, the parser's, session's, timeline's and command types' docs, and
   `CHANGELOG.md`. Replies: `undo group "pan drag" is open`, `closed undo group "pan drag": 30 steps,
   undone as one`, `… 1 step`, `…, which took no step`; `undo` then says `undid: pan drag`.

   Calls the user may veto:
   - **The 2 s are measured on the engine's clock,** which the session now takes (`clock=`): real
     time on `LiveShow` and under `busk run`, an `OfflineShow`'s fake time, which moves only with
     `tick`. A script on `OfflineShow` never times a group out unless it ticks.
   - **A step after the gap closes the group and stands alone,** and so does every step after it,
     as the step says. The group is not reopened: the frontend does that (step 2).
   - **A refused line changes nothing, the group included.** A refused show edit, or `undo` with
     nothing to undo, leaves the group open; only a step that happens closes it.
   - **`undo group end` with no group open is refused** (`no undo group is open`), as `undo` with
     nothing to undo is. A frontend that sends it after busk's 2 s gets a refusal it can ignore.
   - **A label is required, in quotes, and not blank.** busk does not make one up. A long one is
     cut in the replies as a name is (`short`), so its closing quote goes with the cut.
   - **Modes neither close nor join a group** (`blind`, `fade`, `highlight`), as they are not steps.
     Nor does `save`.
   - **A group's step may change nothing,** a drag that comes back where it started. It stays, and
     `undo` says it undid it, as a step of the group's label.
2. **F2's drag is one group.** It sends `undo group` at its start, its `set` lines as now, and
   `undo group end` on release, so the light follows the drag and `undo` takes it back whole. A
   click stays one `set`. Change `encoders.py`'s docstring and the guide's note on drags
   (`docs/tui/guide.md`, which names GAP-06).

   Verify: a drag on the real engine is one `undo`; a click is one; a drag cut short by a page
   change still closes, by its end line or by busk's 2 s; the perf gate on F2.

   **Done** (2026-11-17). `EncoderRow.on_encoder_bar_moved` in `src/busk_tui/widgets/encoders.py`
   sends `undo group "<attribute> drag"` before a drag's first `set` and `undo group end` after the
   release's, both unlogged (`internal`); a click, a release with no move before it, sends neither.
   The lines are `commands.undo_group` and `undo_group_end`, in the contract test. Each goes on the
   bridge's ordered worker with the `set` lines, and a newer keyed `set` that replaces an unsent
   one goes after the lines before it, so the order holds. The guide's drag note and the module's
   docstring say so.

   **A bug found here, from Phase 2:** an F-key during a drag hid the bar, and Textual kept the
   mouse with it but dropped every mouse event, the release too, since a hidden widget has no
   region. So the drag never ended, and clicks on the new page did nothing until F2 came back.
   With the group, it would also have kept busk's group open for 2 s, and a selection made on the
   new page in that time would have joined the drag's step. Now `EncoderBar.on_hide` lets go of the
   mouse, and `on_mouse_release` ends the drag as a release would, at its last level: the last
   `set`, logged, then `undo group end`. A dialog (Ctrl+Q while dragging) takes the mouse, and ends
   it the same way. Both apply to F6's spread rows too, which use the same bar.

   At the user's word (this conversation), Ctrl+Z sends `undo` and Ctrl+Y `redo`, logged,
   whatever the prompt holds (the prompt has no undo of its own), from `BuskApp.prompt_key`. The
   help lists both, the key legend `ctrl+z undo`, and the guide's key table both. Ctrl+Shift+Z was
   built first; the user chose Ctrl+Y instead, since a terminal without the kitty keyboard protocol
   sends Ctrl+Shift+Z as Ctrl+Z, so it undid.

   Calls the user may veto:
   - **A drag that pauses for 1 s opens a new group when it moves on** (`GROUP_PAUSE_S`), so a
     drag held still past busk's 2 s is two undo steps, not one per line after the pause. The
     plan did not name this case.
   - **The label is `<attribute> drag`** (`undid: pan drag`, `undid: color.r drag`).

Under (b), step 1 is busk merging a `set` of one attribute on the same selection into the step
before, within 1 s, and step 2 changes only the docstring and the guide.

**Phase 20 checks** (2026-11-17), on top of `cd73e0e`. The whole suite: 7,066 passed and 1
skipped, in 8:43 with `uv run pytest -n 6`. `ruff check`, `ruff format --check` and `mypy src`
clean. New tests:
`tests/test_undo_group.py` (27: the timeline, the lines on `OfflineShow` and `LiveShow`, the gap in
real time, 40 lines from four threads), parser and completion rows, the command count and binding
checks of `tests/test_schema.py`, the public API golden (`UndoGroupCmd`, `UndoGroupEndCmd`), the
contract test's two builders, and in the TUI: F2's drag opens and closes a group, a click opens
none, a pause opens another, a page change and a dialog end a drag, Ctrl+Z and Ctrl+Y, and
`test_tui_hints.py`, where `undo` now has two forms. On the real engine
(`test_an_f2_drag_is_one_undo_on_the_real_engine`): a drag of ten moves is one step, a click
another, Ctrl+Z twice takes both back and Ctrl+Y brings the drag back. The touched TUI files
pass on Textual 8.2.0 (537 and 53 tests, and the e2e drag). The perf gate: 8 passed (`busk run`
F2 +0.173, F2 with P11's Circle +0.222). Sixteen mutations of the new code, all caught.
Then Ctrl+Y replaced Ctrl+Shift+Z and `commands.flash` went, TUI files only: `tests/tui`, 1,764
passed (8:42 with `-n 6`), and the touched files on Textual 8.2.0, 467 and the e2e drag.

A real `busk run` of the club show (processes, `--state-dir` in a temporary directory), a script:
`undo group "pan drag"`, 20 `set pan` lines, `undo group end` (`20 steps, undone as one`), then
`undo` twice took a tilt and the whole drag, `redo` brought the drag back (101 and 102 at pan 20),
and a second `undo group end` was refused (`no undo group is open`).

### Phase 21: A family's own timing removed

The user's word of 2026-11-11. No line removes a family's own timing from a cue, so once F4's TIME
dialog (Phase 15) sets one, only `undo` takes it away. Needs Phase 18, whose step 2 changes how
these fields are read. The engine step comes first. Code: `src/busk/console/parser.py`
(`_cue_verb`), `src/busk_tui/widgets/cue_dialogs.py`, `src/busk_tui/commands.py`.

1. **GAP-42: `cue L/C time <family> none`** removes the family's own timing, its fade, delay and
   curve (§5, call 14), so the family fades with the cue again. Removing the last one removes
   `perFamily`. A family with no timing of its own is refused in one line (`cue 9/2 has no
   position timing of its own`). One undo step, with a reply in words. `expected()` offers `none`
   after a family. Add the entry and its Summary row to engine-gaps.md, and update
   `docs/console.md` and `busk help`.

   Verify: removing one of two families, the last one, and one the cue lacks; `undo`; the
   compiled cue fades the family with the cue's times afterwards (the compile, not only the JSON);
   `list cues`.

   **Done** (2026-11-11). `_family_none` in `console/parser.py`, reached from `_cue_verb` when
   `none` follows a family. With other families left it sets `perFamily` without this one; with
   none left it deletes `perFamily`, so a cue is as it was before its first family line. One
   labelled step: `cue 9/2 fades position with the cue again`, which `undo` and `redo` repeat.
   `cue 9/2 has no position timing of its own` refuses the rest, with nothing on the timeline.
   `busk help` and the grammar have `| cue L/C time <family> none` on the family's line, and the
   module docs and `docs/console.md` say what it removes. GAP-42's entry and Summary row are in
   engine-gaps.md. Tests: `test_console_parser.py` (one of two families, the last, the words in any
   case, and four refusals), `test_console.py` (the compiled Verse of Appendix A: its leave table
   and its colour and pan lanes take the cue's in timing once each family goes, `list cues`, two
   `undo`s; no undo step spent on a refusal; the refusal table, wherever a line goes; the replies
   table; and a running `LiveShow`, whose active cue stays active), and three rows of
   `test_console_prompt.py`'s completion table, with its grammar test.

   Which the user may veto:
   - **The reply says what the family does now,** `cue 9/2 fades position with the cue again`,
     the words step 2 gives the dialog, after the family line's `cue 9/2 fades position over 4 s`.
   - **Tab offers `none` after every family,** whether or not the cue has timing of its own for
     it; the line says so when it runs, as `playback N <optional> none` does.
   - **Words after `none` are refused first** (`unexpected '4'`), before whether the family has its
     own, as `cue L/C effect <id> remove` does.
2. **F4's TIME dialog removes it.** While a family chip with timing of its own is chosen, a
   `[none]` button sends the line, and the dialog says what it does (`position fades with the cue
   again`). No question: `undo` brings it back.

   Verify: the button shows only on a family with timing of its own; Esc sends nothing; the time
   cell drops the family (`2, position 4` becomes `2`); a test on the real engine.

   **Done** (2026-11-11). `TimeDialog` (`widgets/cue_dialogs.py`) has a row under its note:
   `[none] Ctrl+N · position fades with the cue again`, shown only while the chosen chip is a
   family the cue has timing of its own for. A click, or Ctrl+N, closes the dialog with
   `commands.no_family_time` (`cue 9/2 time position none`), which F4 runs with no question. The
   contract test runs it on the club show after the family line. `test_tui_cues.py`: the row on
   each chip (only `position` and `beam` of the fake cue), Ctrl+N doing nothing while it is
   hidden, its words, Esc sending nothing, and the line by a click and by the keyboard alone
   (Shift+Tab, →, Tab, Ctrl+N from the fade field). `test_tui_e2e.py`: on the club show, cue 9/2's
   time cell goes from `2, position 4` to `2` after `[none]`, busk's words are in the log, and
   `undo` brings it back.

   Which the user may veto:
   - **Ctrl+N** reaches `[none]` from the keyboard, as Ctrl+O reaches the profile picker's
     `[import…]`: the dialog's keys are Tab, ← →, Enter and Esc, and a button has no focus.
   - **`[none]` sends the line whatever the fields hold:** a fade typed and not sent is dropped.
   - **The row sits under the note, at the dialog's left edge,** not under the fields: indented
     like them, `… with the cue again` was cut at 60 columns for most families.

Docs: the guide's F4, the report's Cues rows, §7's item, and `CHANGELOG.md`.

**Done** (2026-11-11). As listed, and also the report's header, which names Phase 21.

**Phase 21 checks** (2026-11-11), on top of `5a47856`, built before Phase 20 at the user's word.
The whole suite: 6,359 passed and 1 skipped, in 8:31 with `uv run pytest -n 6`. `ruff check`,
`ruff format --check` and `mypy src` clean. Two later edits to the dialog (the row's indent, and a
simpler lookup) were checked on the files they touch: `test_tui_cues.py`, `test_tui_commands.py`
and the two F4 dialog tests on the real engine, on Textual 8.2.8 and 8.2.0. Two mutations of the
dialog (the row on every family chip, Ctrl+N while it is hidden) each fail a new test. F4's
update path is unchanged (only the modal changed), so no perf gate.

A real `busk run club.show --threads --state-dir …`, the lines piped in: `go 9`, then `cue 9/2
time position none` replied `cue 9/2 fades position with the cue again`, and `list cues 9` showed
Verse as `time 2`; the same line again was refused (`cue 9/2 has no position timing of its own`);
colour and beam timing set, colour's removed, `list cues 9` showed `time 2, beam 2`; four `undo`s
said each step's words, and Verse was back to `time 2, position 4`. A real `busk-tui --state-dir …`
under `busk run` on the club show, in a pty at 150 columns (layout B) and 99 (layout A): F4, Song,
a click on 9/2's time cell, the `position` chip, the `[none]` row in full, a click on it, the time
cell at `2` and busk's words in the log; `undo` typed at the prompt; then Shift+Tab, → →, Tab and
Ctrl+N sent it again. No error in the log.

### Phase 22: Moving and copying a cue

The user's word of 2026-11-11. A cue can be renumbered only between its neighbours, and neither
copied nor renumbered from F4; nor can a cue list. Needs Phase 19, which words the replies of
`cue L/C number M`. The engine steps come first. Code: `src/busk/console/parser.py`
(`_renumber_cue`, `_cue_verb`), `src/busk/commands/edits.py` (`cue_insert_index`),
`src/busk_tui/pages/cues.py`, `src/busk_tui/commands.py`.

1. **GAP-43: a cue moves past its neighbours.** `cue L/C number M` takes a number on either side
   of the others, and the cue goes to its place in the list's order (`cue_insert_index`), in one
   undo step (§5, call 13). A number the list already has stays refused. Check:
   - a running list whose current cue moves (the playback stays on it);
   - a `follow` or `wait` chain, which now runs in the new order;
   - a `gotoCue` or a `GOTO` that names the old number (busk warns, as a renumber does today);
   - a chase.

   **Done** (2026-11-11). `_renumber_cue` in `console/parser.py`. A cue that keeps its place
   among the others (`cue_insert_index` of the list without it is where it is) takes the number in
   one `SET`, as before. One that passes them is a `DELETE` and an `ADD` of the same cue, its id
   kept and its number changed, in one labelled step: the `ADD` places it as `record cue` does.
   The reply is the one Phase 19 gave a renumber, `cue 9/2 is now cue 9/7`. Checked on the Live
   harness: a playback on the cue stays on it (the engine finds a running cue by id), and `back`
   then goes to the cue now before it; a `follow` runs after the cue now before it; a running
   chase on the moved step goes on in the new order. A `gotoCue` that names the old number gets
   the validator's warning, as before. `cannot pass` is gone.
2. **GAP-43: a cue is copied.** `cue L/C copy [L2/]M` adds a copy of the cue at `M`, in its own list
   or in list `L2`, at its place in the order. The copy gets a new id, and keeps the cue's name,
   entries, timing, trigger, releases and effects. A number the list already has is refused.
   Check: the effect ids inside the copy, a copy into a chase, and a copy into an empty list. Add
   GAP-43's entry and Summary row to engine-gaps.md, and update `docs/console.md`, `busk help`
   and `expected()`.

   Verify: both lines on `OfflineShow` and on a running `LiveShow`; `undo`; the compiled list after
   each.

   **Done** (2026-11-11). `_copy_cue`, reached from `_entity` by `copy` after a cue. `M` names a
   cue of the same list, `L2/M` one of list `L2`. The copy is the cue deep-copied, with a new id
   (`ids.new("c", …)` over every list's cues, as `record cue` makes one) and the number, in one
   labelled `ADD`: `copied cue 9/4 "Chorus" to cue 10/5`. Its effects keep their ids: they are
   unique within a cue only, and the compiled copy runs `ei-1` as the cue does. A copy into a
   running chase is one more step, in its place; one into an empty list is its first cue, and
   `go` runs it. Refused in one line: a number the list has (`cue 10/1 exists`), a list it lacks
   (`no cue list 99`), and anything that is not `M` or `L/M` (`expected a cue number, or L/C for
   another list, got '10/'`). `busk help` and the grammar have `cue L/C number M | cue L/C copy
   [L2/]M`; the module docs and `docs/console.md` say what each does, and GAP-43's entry and
   Summary row are in engine-gaps.md. Tab offers `number` and `copy` after a cue.

   Tests: `test_console_parser.py` (a renumber that stays a `SET`, three that move, a copy in its
   own list and in another); `test_console.py` (the refusal table, with `cannot pass` gone and
   ten new rows; the edge table, with the three old `cannot pass` lines and four copies; the
   replies table, with a move and two copies; and ten tests of GAP-43: the document and the
   compiled list after a move, `list cues`, `undo` and `redo`; a move back before the others; a
   running playback that stays on its cue; a follow; a running chase; a goto's warning; a copy
   that keeps all but its id, effects included; a copy into another list, a chase and an empty
   list; refusals that spend no undo step; and a move and a copy on a running `LiveShow`); and
   `test_console_prompt.py` (four completion rows and two grammar lines).

   Which the user may veto:
   - **A move is two edits in one step,** a `DELETE` and an `ADD` of the same cue, where a cue
     that stays between its neighbours is one `SET`. `SET` cannot move an element of a list.
   - **`2.0` is a number of its own,** after `2`, as the validator compares them. So `cue 1/1
     number 2.0` now moves cue 1 past cue 2, where it was refused (`cannot pass`).
   - **Nothing follows the cue to its new number:** a `gotoCue` or a `GOTO` that named it names no
     cue afterwards, and busk warns, as a renumber between neighbours did.
   - **A copy keeps its effects' ids,** as `record cue` keeps the programmer's.
   - **Tab offers `number` after a cue too,** which it did not, beside the new `copy`.
3. **F4's `[number…]` and `[copy…]` on a cue, and `[number…]` on a list.** Each is a dialog that
   refuses a number already taken, as F3's `[number…]` does. `[copy…]` takes a list (the chosen
   one first) and a number. The report's two "renumber: prompt" cells become controls.

   Verify: each control on the real engine; Esc; a taken number; the table's order after a move;
   `[GT]` greyed (Phase 17) when a renumber takes its goto cue away.

   **Done** (2026-11-11). In `pages/cues.py`: the `edit` row has `[number…]` and `[copy…]` after
   `[rename…]`, and the `list` row `[number…]` after its `[rename…]`. Builders
   `commands.renumber_cue`, `copy_cue` and `renumber_cuelist`, in the contract table and its
   test of what the lines do.
   - The cue's `[number…]` is a `TextDialog` filled with the cue's number, under `the cue goes to
     its place in the list`; it refuses another cue's number (`check_cue`, so `03` is 3) and sends
     nothing for its own, in any form (`02`). It sends `cue 9/4 number 7`, and the cue stays
     chosen at its new number (`_cue_after`, which `[record at…]`'s `_recorded` became).
   - `[copy…]` is a `FormDialog` of a list and a number, starting at the chosen list and the next
     whole number after its last cue, under `lists: 1–20`. It refuses a list the show lacks (`no
     cue list 99`) and a number that list has, and sends `cue 9/4 copy 8` or `cue 9/4 copy
     10/2.5`. A copy into the list shown becomes the chosen cue; one into another list leaves F4
     as it is.
   - The list's `[number…]` is a `TextDialog` as F3's are (`check_number`, `taken: 10–11, 21`),
     and sends `cuelist 9 number 30`. The list stays shown, on the cue it was on, whichever of
     busk's reply and the new show comes first (`_list_after`).
   - **F4's fallback for a list it can no longer find** now takes the selected playback's list
     before the first. F4 keeps its list by number, so a renumber typed at the prompt, or an
     `undo` of one, sent it to list 1 (found in the pty walk).

   Tests: `test_tui_cues.py`: the three strips' words and the pane cursor's stops; `[number…]`
   (refusals, its own number in two forms, Esc, the line, the cue chosen at its new place);
   `[copy…]` (six refusals, a copy into another list leaving the chosen cue, one into its own list
   chosen, Esc); the list's `[number…]` in both orders of reply and show (the `show_first` case
   fails when `_list_after` does not restore the cue); and a list renumbered at the prompt and
   back by `undo` staying shown (fails on the old fallback). `test_tui_e2e.py`: on the club show,
   cue 9/4, P9's goto cue, moved to 7 (after Esc and a refused 3), copied to 10/2.5 and to 9/8,
   list 9 made 30; the log's lines and busk's replies; P9's `[GT]` grey with `goto: cue list 30
   has no cue 4`; four typed `undo`s bring it all back and `[GT]` live again.

   Which the user may veto:
   - **`[copy…]`'s list is a field,** the chosen list's number to start, not chips: the club show
     has 20 lists. Its number starts after the chosen list's last cue even when another list is
     typed; a number that list has is refused as `cue 3 exists`, as `[record at…]` says it.
   - **A copy into another list leaves F4 on the list shown,** so several cues can be copied in a
     row; the log says where each went.
   - **No question** before any of the three: each is one undo step and changes no value.
   - **F4's fallback change** above, which the plan did not name.

Docs: the guide's F4, the report's Cues and Cue lists rows and its "busk lacks a little", §7's
items, and `CHANGELOG.md`.

**Done** (2026-11-11). As listed, and also the report's header, Summary rows, "In short", "What
busk is missing" (item 10) and "What the TUI is missing"; the guide's forms paragraph; and the
changelog's older Fixed entry, whose `cue 1/1 cannot pass cue 1/2` became `cue 1/2 exists`.

**Phase 22 checks** (2026-11-11), on top of `a1e6f79`. The whole suite: 6,411 passed and 1
skipped, in 7:45 with `uv run pytest -n 6`. An earlier run, under load from the pty walks, failed
only F6's real-engine preset test (Phase 15's notes call it flaky under `-n 6`), which then passed
three times alone. `ruff check`, `ruff format --check` and `mypy src` clean. The new TUI tests pass
on Textual 8.2.0, the real-engine ones too. The perf gate: 7 passed, F4 +0.159 core, no overruns.
Two mutations of step 3 (the list's cue not restored, a copy elsewhere choosing a cue) and the old
fallback each fail a new test.

A real `busk run club.show --threads --state-dir …`, the lines piped in: `go 9`, then `cue 9/1
number 6` replied `cue 9/1 is now cue 9/6`, and the status line said `9 Song on 6 Intro`; `cue
9/2 number 7` and `list cues 9` showed 1, 3, 4, 5, 7; `cue 9/4 number 3` replied with busk's
warning that P9's `gotoCue` names no cue; `cue 9/7 copy 10/2.5`, `cue 9/1 copy 1.5`, and a copy
into a new empty list 30 went through; `cue 9/3 copy 4`, `copy 99/1` and `copy 10/` were refused
in one line each; `cue 10/1 number 5` on the running chase P10 put it last; the `undo`s said each
step's words, and P9 was back `on 1 Intro`. A real `busk-tui --state-dir …` under `busk run` on the
club show, in a pty at 150 columns (layout B) and 99 (layout A, F4 stacked): F4, Song, a click on
cue 9/4; `[number…]` refused 3 in red, then 7 moved Chorus last, still chosen, with ▶ on it;
`[copy…]` opened on list 9 and number 8, took 10 and 2.5, then 9/8 as it opened; the list's
`[number…]` 30 showed CUELIST 30 with the copy 30/8 chosen; busk's words in the log; four typed
`undo`s brought list 9 back, with F4 still on it (the walk that found the fallback). Every button
shows at 99 columns. No error in the log.

### Phase 23: Every family on F4

The user's word of 2026-11-11. F4's cue table shows only intensity and colour entries, as the spec's
§8.4 lists them, so a cue that holds only position or beam values looks empty. Its shape waits on
Q7. A TUI phase. Code: `src/busk_tui/widgets/cuetable.py`; `src/busk_tui/model.py` and
`src/busk_tui/bridge.py` only if `CueInfo.values` lacks what Q7's answer shows.

1. **Under Q7's answer.** Under (a): one more column after colour, `also`, naming the other
   families the cue holds values for, and how many of each (`position 2, beam 1`). It is the first
   column dropped on a narrow screen.

   Verify: a cue with only position values shows them; a cue with every family; the widths at 99
   and 150 columns; the perf gate on F4.

   **Done** (2026-11-11), under Q7 (a) and the user's word on the widths (§8). In
   `widgets/cuetable.py`: an `also` column after `colour`, 13 cells wide, and `_also`, which
   counts the cue's entries whose attribute is neither `intensity` nor `color` (`SHOWN`) by
   busk's family, in busk's order of families (`FAMILIES`, from `attributes.FAMILY_OF`):
   `position 2, beam 1`, or `—` in the border's colour. An entry of any kind counts once: a
   literal, a preset, a spread, per target. `CueInfo.values` already held every entry, so the
   model and the bridge are unchanged. The order of dropping is now the curve (`drop=7`), then
   `also` (`drop=6`), then as before. Measured: the cue table is 106 cells wide at 150 columns,
   so `also` shows where the curve was from 150; from 160 every column shows; at 99 (stacked, 93
   cells) and from 100 to 144 F4 shows what it showed before.

   Tests: `test_tui_cues.py`, the cell (none, intensity and colour alone, a preset and a spread,
   every family in busk's order with a colour wheel and a CTO under `color`) and the widths (at
   160 the curve and `also`, at 150 `also` alone with a position-only cue's `position 2` on its
   line, at 99 neither). Two tests that click the curve cell now run at 160 columns:
   `test_a_row_goes_to_its_cue_and_an_edit_cell_opens_its_dialog` and the real-engine
   `test_f4_edits_a_cues_timing_trigger_and_name_in_dialogs_on_the_real_engine`.
   `test_tui_e2e.py`: on the club show at 150 columns, the header has `also` and no `curve`,
   Verse's line has `position 2`; `sel fixture 101`, `set zoom 50` and `record cue 9/1 merge`
   typed make the Intro `beam 1`, and `undo` takes it back to `—`.

   Which the user may veto:
   - **Every entry neither column shows counts,** by family: a `colorWheel`, `cto` or
     `colorMacro` entry is `color 1` under `also`, beside a `colour` column that shows only
     `color` entries. Leaving them out would let a cue of a colour wheel alone look empty.
   - **At 145 to 149 columns the curve no longer shows,** where it did: it goes first, and `also`
     does not fit either (the table is 101 to 105 cells wide). `RowTable` drops columns and never
     puts one back that fits again; changing that changes every table's fitting, the option the
     user did not take.
   - **The column is there on every list,** `—` on each row of a list whose cues hold no other
     family, so at 150 columns the curve gives way on those too. Columns that change with the
     list shown would move under the mouse as lists change.
   - **Busk's family words** (`color`, not `colour`), as F4's TIME chips have them.
2. **The docs:** the guide's F4, the spec's §8.4 cue table line, and the report's Show row for
   cues.

   **Done** (2026-11-11). The guide's F4: what `also` counts and the widths, and the screen drawn
   again at 150 columns from a real `busk-tui`. The spec's §8.4 cue table line, with the order of
   dropping. The report's header and its Cues Show row. §7's item, §3's row, §8's Q7 and
   `CHANGELOG.md` under Added.

**Phase 23 checks** (2026-11-11), on top of `1d7e23f`. The whole suite: 6,416 passed and 1
skipped, in 8:16 with `uv run pytest -n 6`. `ruff check`, `ruff format --check` and `mypy src`
clean. `test_tui_cues.py` and the two F4 real-engine tests that changed pass on Textual 8.2.0. Two
mutations each fail a new test: `also` dropped first (Q7 as first written: the width test at 150
and the real-engine test), and every entry counted (the cell test).

The perf gate flaps on F6, a page this phase did not touch: three runs with the change gave F4
+0.182, +0.203 and +0.214 core and F6 +0.256, +0.236 and +0.251, against 0.25, so two runs failed
on F6. Two runs with `HEAD`'s `cuetable.py`: one failed (which case was not kept), the other
passed with F4 +0.166 and F6 +0.231. `_also` costs 12 µs a draw of list 9 (`cue_cells` 135 µs),
about 0.0001 core at 10 Hz, so it is not what moves the numbers. A `busk-tui` on the TupperDMX
show, not started by this phase, took about 0.09 core during those runs. No overruns in any case.

A real `busk-tui --state-dir …` (which runs `busk run`) on the club show, in a pty: at 150
columns (layout B), F4, Song: the header has `also` and no `curve`, Verse reads `position 2`;
`sel fixture 101`, `set zoom 50` and `record cue 9/1 merge` typed at the prompt made the Intro
`beam 1`, and `undo` took it back to `—`. At 99 columns (stacked) F4 shows the columns it showed
before (no curve, no delay, no `also`: the real table is narrower there than the headless one).
No error in the log.

### Phase 24: A mode change refused in words

The user's word of 2026-11-11, on the finding Phase 19 left in §7. `fixture N mode` and `fixture N
profile` leave a target on an element the new mode lacks to the validator, which refuses the line
with one document path per element: on the club show, `fixture 301 profile "Generic Spot 16ch"
mode 16ch` takes the 12-pixel bar to one element, and gets 22 lines of `groups[2].members[1].element:
…`, from groups 3 and 4. F3's mode chips and `[profile…]` show them all in the log. An engine
phase, and a bug, so no gap number (§1). It needs nothing, and no question, so it may run before
Phase 20 while Q6 waits. Code: `src/busk/console/parser.py` (`_fixture_mode`, `_fixture_profile`,
`_patch_fits`, and `profile "<name>" update`'s check), `src/busk/console/cascade.py`
(`fixture_cascade`'s walk).

1. **The parser refuses it first, in one line,** as Phase 1 did for a footprint past channel 512
   (`_patch_fits`), so the validator's paths never show. The line names what uses the elements the
   new mode lacks, as the fixture cascade's question names what uses a fixture (§5, call 15):

   `fixture 301 cannot run Generic Spot 16ch, 16ch: groups 3, 4 use elements it would lose`

   The check refuses what the validator refuses, and no more: group members, a preset's values on
   a target, a cue's entries, effects and releases, a parked value, and a binding's command
   (`validate.py`'s `_target` and `_target_spec` callers). `fixture_cascade` already walks all
   of them for a whole fixture; here only the elements past the new mode's count. What the
   programmer holds on a lost element still goes dormant, as GAP-26 settled. A new revision from
   `profile "<name>" update` (GAP-39) that gives a mode fewer elements likely meets the same
   paths: check it, and refuse it the same way if so.

   Verify: one test per kind of user, and a mix; the club show's line in one line; a mode that
   loses only unused elements still goes through; both lines on `OfflineShow` and on a running
   `LiveShow`; nothing changes and no undo step is spent; `profile … update`; a real `busk run`.

   **Done** (2026-11-11). On the club show, `fixture 301 profile "Generic Spot 16ch" mode 16ch`
   now replies `error: fixture 301 cannot run Generic Spot 16ch, 16ch: groups 3, 4 use elements
   it would lose`, where it gave 22 document paths. `fixture N mode` reads `fixture 3 cannot run
   One Channel: …`. Several users read as a cascade's question names them, with one verb:
   `groups 7, 8; preset intensity 1; cue 1/1; 1 parked value and 2 bindings use elements it would
   lose`. A new revision from `profile update` that gives a fixture's mode fewer elements did
   meet the same paths, and is refused the same way: `fixture 3 cannot run revision '2' of 'Two
   Mode Par': group 7 uses elements it would lose`.

   In the code: `fixture_cascade`'s walk in `cascade.py` now takes `kept`, how many elements of
   each fixture stay (0 for a fixture that goes), where it took the ids that go, and `_lost`
   decides a target. `element_users(show, kept)` runs the same walk on a scratch list and names
   what it found, with its verb, or `None`. Its binding step is `_element_command`, a selection
   and values per target, which `_fixture_command` now extends with an added effect and a
   patch. In `parser.py`, `_keeps_elements` raises the line, after the same-mode check and
   `_patch_fits`, in `_fixture_mode`, `_fixture_profile` and, for each fixture of the profile,
   `profile update`.

   Tests, in `test_fixture_mode.py`: each kind of user alone (a group, a preset's target value,
   a cue's entry, effect and release, a parked value, a cue's value per target under a group
   target, a binding's selection and its values per target), each in one line; all of them
   together; a cue that targets a group named through the group; a mode that loses only unused
   elements, and one where another fixture's element of the same number is used; the profile
   line, which embeds nothing; no undo step spent; the club show's bar to both profiles; `profile
   update` refused, then taken once the group no longer names the lost element; both lines on a
   running `LiveShow`. The two tests that expected the validator's `does not exist` now expect
   the line. Four mutations each fail a new test: `_lost` without the element, an added effect
   counted, no check in `profile update`, and the verb always plural.

   Which the user may veto:
   - **An effect a binding adds does not refuse the line,** as the validator does not check
     it: its `_command` has no `ADD_EFFECT` branch, so this follows "and no more". The mode goes
     through, and a press of that binding is refused then, in words (`effect 'fx1': Fixture
     'fx-3' has 1 element(s); element 3 does not exist`). The cascade still takes such an effect
     with its fixture.
   - **A binding's `BATCH` is not a case of its own:** it may hold only show edits (`ADD`, `SET`,
     `RECORD_GROUP`, …), none of which names an element, so it can never refuse the line.
   - **A cue that targets a group is not named;** the group is, as the validator reports the
     group's member and not the cue.
   - **`profile update` names the first fixture that would lose elements in use,** in the show's
     order, and stops there, as its refusal of a missing mode does. A second fixture with users
     shows on the next try. Its words keep the single quotes of that line's other replies.
   - **The programmer counts for nothing:** what it holds on a lost element goes dormant, as
     GAP-26 settled.
2. **The docs:** `docs/console.md`'s note on mode and profile, the parser's module docs (GAP-26's
   paragraph, "Both leave the rest to the validator"), GAP-26's **Done** in
   `docs/dev/tui/engine-gaps.md`, the report's "Found in Phase 19" side finding (removed), §7's
   item, and `CHANGELOG.md` under Fixed. F3 needs no change: its controls show busk's one line.

   **Done** (2026-11-11). `docs/console.md`'s note on mode and profile names what counts and
   gives the line; the parser's and the cascade's module docs; GAP-26's **Done**; the report's
   "Found in Phase 19" side finding is gone, and its header names Phase 24; §7's item;
   `CHANGELOG.md` under Fixed. `busk help` says nothing of the refusals, so it is unchanged.

**Phase 24 checks** (2026-11-11), on top of `e1f684a`. The whole suite: 6,430 passed and 1
skipped, in 7:47 with `uv run pytest -n 6`; the 1,339 tests that read the docs again after the
docs changed. `ruff check`, `ruff format --check` and `mypy src` clean. No TUI file or test
changed, so no perf gate or Textual 8.2.0 run.

A real `busk run club.show --threads --state-dir …`, the club script first, then lines piped in:
`fixture 301 profile "Generic Spot 16ch" mode 16ch` and `fixture 301 profile "RGB Par 3ch" mode
3ch` each replied `error: fixture 301 cannot run …: groups 3, 4 use elements it would lose`, one
line each; with group 9 on fixture 101 alone, `fixture 101 profile "RGB Par 3ch" mode 3ch` went
through (one element, nothing lost) and `undo` took it back; `list groups` showed the groups as
they were.

### Phase 25: Loading a cue into the programmer

The user's question of 2026-11-11, after Phase 22: F4 shows a cue's entries, but none is edited
one by one. A cue's values change only by re-recording from the programmer (`[merge]`,
`[replace]`, `[remove]`), and no line puts a cue's values in the programmer to start from. Its
shape waits on Q8. The engine step comes first. Code: `src/busk/console/parser.py`,
`src/busk/session/programmer.py` (a programmer command, as `SELECT_PLAYBACK` is),
`src/busk/commands/types.py`; `src/busk_tui/pages/cues.py`, `src/busk_tui/commands.py`.

1. **GAP-44: `load cue L/C [only <family>…]`** puts the cue's values into the programmer, under
   Q8's answer, and selects their targets, as `sel playback N` does. It replaces what the
   programmer holds (§5, call 16), in one programmer step. A preset reference stays a reference;
   a group's entry, a spread and per-target values come as a value per target (call 18). The
   cue's effects come too, with their ids, so `record cue L/C replace` puts them back. The cue's
   timing, trigger and releases stay in the cue, and `replace` keeps them. An entry's own timing
   (which only the generic edit sets) does not come, and `replace` would drop it: the reply says
   so when the cue has one. The reply counts what came (`loaded cue 9/3 "Pre": 6 values on 4
   fixtures, 1 effect`). `expected()` offers the families after `only`. Add GAP-44's entry and
   Summary row to engine-gaps.md, and update `docs/console.md` and `busk help`.

   Verify: each kind of entry (literal, preset, spread, per target, on a group and on targets);
   effects and their ids; `only`; a cue of a tracking list, under Q8's answer; `undo` gives back
   the programmer and selection as they were; with `blind on` the stage does not change; on
   `OfflineShow` and a running `LiveShow`. **The round trip:** every cue of the club show loaded,
   then recorded back with `replace` and nothing changed in between; list in the Done note what
   differs from the cue as it was (a spread per target, a group the cover finds otherwise, an
   entry equal to what a tracking list inherits).

   **Done** (2026-11-11), under Q8 (a). A programmer command, `LOAD_CUE` (`cueListId`,
   `cueNumber`, and `filter` as `RECORD_CUE` has it), in `commands/types.py` and
   `commands/classes.py`, handled by `_load_cue` in `session/programmer.py`. Each entry the
   filter keeps goes through `entry_sources`, which is `record.py`'s `_own_sources` moved there
   and shared: `record.inherited` uses it as before. The line is `_cmd_load` in
   `console/parser.py`, after `self.cue()`, with `options("only")`. On the club show: `loaded cue
   9/1 "Intro": 8 values on 4 fixtures`, `loaded cue 9/4 "Chorus": 24 values on 7 fixtures, 1
   effect`, `loaded cue 12/1 "Pulse": 1 effect`.
   - **What comes:** the cue's own entries, a value per target, a later entry winning a slot; a
     preset stays a reference; a target without the attribute, or without a value in a preset or
     a per-target map, gets nothing, as the compiler drops it. The effects come as stored, ids,
     group targets and settings included, and none is stopped, even one whose id the programmer
     had stopped. A cue of a tracking list brings its own changes only (Q8 (a)).
   - **The selection** is the values' targets in the programmer's target order, then the targets
     the effects drive that are not among them.
   - **It replaces** values, effects and stopped effects, in one step, and `undo` gives back the
     programmer and the selection. Blind, highlight and the fade time stay. Every loaded slot
     and effect is touched, as `set` touches it.
   - **Refused in one line,** spending no step: a cue with nothing to load (`cue 30/1 has no
     values or effects to load`, `… no position values …` under `only`), and what `self.cue()`
     refuses (`no cue 1/9`, `expected a cue as L/C, e.g. 10/1`).
   - **An entry's own timing** (only the generic edit sets one) does not come, and the reply ends
     `; 1 entry's own timing is not loaded, and replace drops it`, counting the entries of the
     families loaded.
   - **A binding may load a cue,** since `LOAD_CUE` is a command: the validator checks its list
     (an error) and its cue number (a warning, as a `GOTO`'s), and `delete cuelist N cascade`
     takes such a binding with the list (`cascade._list_command`). The event log keeps the
     command and replay runs it again: it reads only the show.
   - Tab offers `cue` after `load`, `only` after the cue and the families after `only`; `busk
     help` has the grammar line. Documented in `docs/console.md` (the Load row and "Editing a
     cue's values"), both modules' docs, `docs/dev/internals.md`, the spec's §15.2 table, and
     GAP-44's entry and Summary row in engine-gaps.md.

   **The round trip.** Every cue of the club show (29) and of the TupperDMX show (8), loaded and
   recorded back with `replace`, nothing changed in between, is the cue it was, byte for byte:
   they hold group and target entries of literals and presets, and effects on groups, in the
   order recording writes them. What differs elsewhere, each in a test:
   - **a spread comes back as per-target values,** on the group (Appendix A's Verse: `pan` from
     -20 to 20 becomes `{"fx-mh1:0": -20, "fx-mh2:0": 20}`). **Since** Phase 31 (GAP-49) it comes
     back as the spread, and the test says so;
   - **entries come in recording's order,** attributes in the registry's (Verse's pan moves before
     its colour);
   - **a list of targets that is a group's members comes back as the group,** the cover, unless
     `freeze`;
   - **an own value equal to what a tracking list inherits goes,** and tracks (`recorded cue 1/2:
     2 entries; 2 values tracked from cue 1/1`);
   - **an entry's own timing goes.**

   The compiled cue is the same in each but the last.

   Tests: the new `tests/test_load_cue.py` (25: each kind of entry, a target without the
   attribute, effects and a stopped id, the selection's order, `only`, a tracking list, the
   programmer replaced and `undo`, blind, the stage, three refusals, an entry's timing, an edit
   recorded back, the round trip on both shipped shows and the five differences, bindings and a
   renumber's warning, a running `LiveShow`); rows in `test_console_parser.py` (three lines, eight
   refusals) and `test_console_prompt.py` (five completions, the grammar line); a `LOAD_CUE`
   binding in `test_cascade.py`'s list cascade; a load in `test_eventlog.py`'s replayed run; the
   command count in `test_schema.py`. Mutations: five of `_load_cue` (no effect targets selected,
   `only` ignored by values or by effects, no timing note, the selection kept) and the stopped
   set kept each fail a test.

   Which the user may veto:
   - **A command, not only a line,** so a binding may load a cue; hence the validator's and the
     cascade's cases.
   - **A cue with nothing to load is refused,** where it could have cleared the programmer.
   - **The selection is what came,** so a target of an entry that got no value (no slot) is not
     selected, where `sel playback N` would select it.
   - **The reply counts fixtures,** not elements: Pre's 28 values are `on 5 fixtures`.
   - **Not in `tests/api_consumer.py`:** a typed consumer cannot write a `LOAD_CUE` literal, since
     `busk` does not export `CueListId`, as for `RECORD_CUE` today.
   - **Tab's word after `load cue`** is the shared `a cue list number, as L or L/C`, though only
     `L/C` is taken, as for `rename cue` and `delete cue`.
2. **F4's `[load]`** on the chosen cue, before `[merge]`: `load cue 9/3`. It asks the TUI's own
   question first while the programmer holds values or effects, since it replaces them (`Load cue
   9/3 "Pre" into the programmer? It replaces what the programmer holds.`). After it, the cue is
   edited as any look is, on F2, F3 and F6, and `[replace]` records it back.

   Verify: `[load]` on the real engine; the question only when the programmer holds something;
   the programmer and the selection after; load, change one value, `[replace]`: the cue holds the
   change and the rest as before; the perf gate on F4.

   **Done** (2026-11-11). In `pages/cues.py`: `[load]` in the `edit` row after `[record at…]` and
   before `[merge]`, magenta, the spec's colour for programmer values and record actions;
   `ask_load` sends `commands.load_cue` (`load cue 9/3`) at once on an empty programmer, and with
   the TUI's question (`Load cue 9/3 "Pre" into the programmer?` and, on its second line, `It
   replaces what the programmer holds.`) while it holds a value or an effect, a stopped one too.
   On a cue that stores no value and no effect it is grey, with no click and no pane cursor. After
   it the cue is edited as any look, and `[replace]` records it back. The builder is in the
   contract table and in the test of what the cue lines do.

   Tests: `test_tui_cues.py`: the strip's words and the pane cursor's stops (`[load]` between
   `[release…]` and `[delete]`, and its `ConfirmDialog`); `[load]` at once on an empty programmer,
   then asked with values, with an effect and with a stopped one (n sends nothing, y sends);
   grey on Spare's cues, live on a cue of effects and a per-target value; 99 columns.
   `test_tui_e2e.py`: on the club show, with 201 at 50 % in the programmer, `[load]` on 9/2 asks,
   n, then y: the heads selected and 201's value gone; `set intensity 30%` typed and `[replace]`:
   Verse's entries are as before but the intensity, 0.3; `undo` gives back 0.7. Mutations: the
   question on values only, always asking, and never grey each fail a test.

   Which the user may veto:
   - **The question counts a stopped effect,** since busk replaces it too.
   - **Grey only on a cue that stores nothing;** a cue whose values all reach no slot is live, and
     busk refuses it in the log.
   - **F4 stays where it is** after a load: the operator goes to F2, F3 or F6 to change the look.

Docs: the guide's F4 (the steps of an edit: `[load]`, change, `[replace]`), the report's Cues row
"Change its values", `docs/console.md`, §7's item, and `CHANGELOG.md`.

**Done** (2026-11-11). The guide's F4: its first line, the screen's `edit` row, a `[load]` item and
"Editing a cue's values". The report: its header, the Cues row "Change its values", "What busk is
missing" (item 11), "What the TUI is missing", "In short" and the side finding on questions.
`docs/console.md`, §7's item, §8's Q8, and `CHANGELOG.md` under Added.

**Phase 25 checks** (2026-11-11), on top of `89c6ad2`. The whole suite: 6,475 passed and 1
skipped, in 8:35 with `uv run pytest -n 6`. The run before failed twice: the public API's golden,
which then took `LoadCueCmd` in the `Command` union, one line (`BUSK_REGOLDEN=1`), and F6's
real-engine preset test, whose click on a new position tile did not land under load (Phase 22's
notes call it flaky under `-n 6`); it then passed three times alone. `ruff check`, `ruff format
--check`, `mypy src` and `mypy --strict tests/api_consumer.py` clean. The F4 tests, the contract
table and the new real-engine test pass on Textual 8.2.0.

The perf gate failed twice on F1 B, a page this phase did not touch (+0.262 and +0.252 core,
against 0.25), with a `busk-tui` on the TupperDMX show running alongside, not started by this
phase, its engine and console hosts taking about 0.3 core. A copy of the gate that prints every
page instead of stopping at the first (made and deleted at once) gave each under 0.25: F1 B
+0.232, A +0.232, C +0.245, F2 +0.194 and +0.243, F3 +0.212, F4 +0.204, F5 +0.212, F6 +0.234.
No overruns in any run. F4's change adds one button to a strip that is built anyway.

A real `busk run club.show --threads --state-dir …`, the club script first, then lines piped in:
`sel fixture 201`, `set intensity 50%`, `go 9`, `load cue 9/3` replied `loaded cue 9/3 "Pre": 28
values on 5 fixtures` and `programmer` listed the bar's and the washes' values and none of 201;
`set intensity by -50%` and `record cue 9/3 replace` (`recorded cue 9/3: 3 entries`); `load cue
9/4 only color` brought 18 values and the rainbow; `load cue 12/1` the effect alone; `load cue 9/9`
and `load cue 9/4 only position` were refused in one line each; with `blind on`, `load cue 9/2`;
four `undo`s gave back 201 at 0.5. A real `busk-tui --state-dir …` (which runs `busk run`) on the
club show, in a pty at 150 columns (layout B) and 99 (F4 stacked): `sel fixture 201` and `set
intensity 50%` typed, F4, Song: `[load]` on 9/1 Intro asked (`Load cue 9/1 "Intro" into the
programmer?` / `It replaces what the programmer holds.`), `n` logged `cancelled: load cue 9/1`,
then `y` logged `loaded cue 9/1 "Intro": 8 values on 4 fixtures` and PROG showed 4; `set
intensity 30%` typed and `[replace]` made the Intro's row 30 %; `undo` 60 % again. Every button
shows at 99 columns, where on the Intro `[delete]` now wraps to a third row. No error in the log.

### Phase 26: Odd and even in a selection

The user's word of 2026-11-12, after the grandMA3 comparison (§7). grandMA3's groups by purpose
(Spots Odd, Spots Even) take every other fixture of a selection. busk selects only by number, span
and group, so today the line is `sel fixture 101, fixture 103, fixture 105, fixture 107`. Its shape
waits on Q9. The engine step comes first. Code: `src/busk/console/parser.py` (`_cmd_sel`),
`src/busk/commands/types.py` (`SELECT`), `src/busk/session/programmer.py`;
`src/busk_tui/widgets/quick.py` (`group_buttons`), `src/busk_tui/commands.py`, and the places with
group buttons: `pages/program.py`, `widgets/preset_panel.py`, `pages/busk_stack.py`,
`pages/busk_stage.py`.

1. **GAP-45: odd and even**, under Q9's answer. Under (a):
   - `sel <targets> odd|even` keeps every other target of those the line names, in their order,
     counted from 1. `odd` keeps the first, third and so on; `even` keeps the second, fourth and
     so on (§5, call 21). A target is an element, so `sel fixture 301 even` selects the bar's even
     cells. `sel + <targets> odd` adds those targets, and `sel - <targets> odd` takes them out.
   - `sel odd` and `sel even` keep every other target of the current selection, in its order. The
     parser does not see the selection, so this form is a programmer command: a mode of `SELECT`
     or a command of its own, which the step chooses and names. It is one programmer step.
   - The reply counts what is selected, as `sel` does. `sel odd` with nothing selected is refused
     in one line. Tab offers `odd` and `even` after the targets and after `sel`.

   Add the entry and its Summary row to engine-gaps.md, and update `docs/console.md` and `busk
   help`.

   Verify: each form on a group, a span, a span written backwards, a fixture's elements, and a
   list of these; `sel odd` on a single target; `undo`; `record group 5 "Spots Odd"` afterwards
   records those members in order; a running `LiveShow`.
2. **`[odd]` and `[even]`** come after the group buttons (before `[none]` on a strip that has
   one): on F2's SELECTION, F6's PRESET panel, F1 B's SELECTION and F1 C's QUICK. Each sends `sel
   odd` or `sel even`, and is grey while fewer than two targets are selected. F3's GROUPS
   `[record…]` then makes the group.

   Verify: the line by a click and by the pane cursor; the grey state; the selection afterwards; a
   test on the real engine; the perf gate on F1 and F2, whose strips change.

Under (b), step 1 reads `every N [from K]` in place of the two words. `odd` and `even` stay as its
two common cases, and step 2's buttons stay `[odd]` and `[even]`.

Docs: the guide's F1, F2 and F6, F3's GROUPS (a group of every other fixture), and `CHANGELOG.md`.

### Phase 27: Tracked states and block cues

The user's word of 2026-11-12. A tracking list stores each cue's changes, and on stage a cue shows
them over what the cues before it left. Nothing shows that today:

- `list cues L` gives each cue's timing and trigger.
- F4 shows what each cue stores (Phase 23's `also` counts it).
- `load cue` brings only the cue's own changes (Q8 (a)).

The compiler works out each cue's state (`src/busk/compiler/tracking.py`), but no facade reads it.
A cue's `block` (a tracking stop: the cue is a whole state) is in the model. Only the generic edit
sets it (`cue 9/3 block true`, which replies with a path), and neither `list cues` nor F4 shows it.
This phase is engine only; F4 is Phase 28. Code: `src/busk/compiler/tracking.py`,
`src/busk/runner.py`, `src/busk/console/console.py` (`list`), `src/busk/console/parser.py`
(`_cue_verb`).

1. **GAP-46: a cue list's tracked states.** `OfflineShow.tracking(L)` and `LiveShow.tracking(L)`
   read the compiled show, not the engine (§5, call 22). For each cue, in order, the read gives:
   - its number, name and `block`;
   - for each target and attribute the cue gives a value: the value (a literal, or a preset by
     name) and where it comes from, `own` (the cue stores it) or `tracked` from cue N;
   - what the cue releases;
   - its effects, own or tracked, in the same way.

   A list without tracking has only `own`. Name and export the classes as the other reads are
   (`TrackedCue`, `TrackedValue`). Check that the console process under `busk run` has the
   compiled show to read.

   Verify: Song with tracking on (Verse's colour is tracked from Intro); a release; a block cue;
   an effect that tracks on; a list without tracking; a list with no cues; a chase (say what the
   compiler does with tracking there); `OfflineShow` and a running `LiveShow`; the read's cost on
   the reference rig, in `docs/dev/benchmarks.md`.

   **Done** (2026-11-16). `tracked_cues` in the new `src/busk/session/tracked.py`, read by
   `_Facade.tracking(cue_list)` in `src/busk/runner.py`, so both facades have it. Three public
   names, `TrackedCue`, `TrackedValue` and `TrackedEffect` (44 in `busk.__all__`). The entry, its
   Summary row and its **Done** are in engine-gaps.md. What it gives:
   - **Each cue** of the list, in order: `number`, `name`, `block`, `values`, `released` and
     `effects`. `None` for a list number the show lacks, `()` for a list with no cues.
   - **A value** is a `ProgrammerValue`'s fields (fixture number, element from 1, attribute, the
     value in the show's units, the preset's `(pool, number, name)` or `None`) and `trackedFrom`:
     the number of the cue that stores it, `None` for the cue's own. By fixture number, element and
     the registry's order of the attributes. On the club show, Verse's washes read `intensity 0.6`
     and preset Blue, both tracked from `1`.
   - **`released`**: the `(number, element, attribute)` slots the cue takes away. Those its
     `releases` name that the cue before it held, as a value or through an effect instance it
     tracks, and that it does not set itself. The Outro's are the heads' pan and tilt.
   - **An effect**: its `id` and `trackedFrom`, as for a value. The Outro has `rainbow` from `4`.
   - **How:** the compiler's states are lanes, which name no preset. So the read runs
     `tracking.py`'s rule on show data, as `record.inherited` does, through `entry_sources` and
     `released_slots`. `released_slots` was `record.py`'s `_released`; it moved beside
     `entry_sources` and is shared, as Phase 25 shared `entry_sources`. The effects come from the
     compiled cue: `CompiledEffect.cue` already names the cue that holds each instance.
   - **A chase** tracks as a sequence does, in list order, whatever its direction: the compiler
     works out the states once, and the engine plays them in the chase's order. With tracking on,
     the club show's chase (list 10) reads the same states forward and in reverse.
   - **Under `busk run`** the console process compiles every edit before it sends it to the engine
     process, so it holds the compiled show; the read needs nothing from the engine.
   - **Cost**, on the §19 reference rig with 4-cue tracking lists: see the Phase 27 checks below,
     and `docs/dev/benchmarks.md`.

   Calls the user may veto:
   - **A method, not a property** (`tracking(L)`), since it takes the list, and **`None`** for a
     list that is not there, as `confirmation` returns `None`, rather than an error.
   - **`released` counts what the cue takes away,** not every slot its releases name: a release of
     something nothing held is not listed. It counts a slot only an effect drove, so a track
     sheet's `✕` shows where an effect stops too.
   - **`TrackedEffect` has only the id and where it comes from.** As with an `EffectStatus`, a
     display finds the instance, its template, targets and settings in the show. A release that
     trims some of a tracked instance's slots shows only in `released`.
   - **Made on each call, not cached**, since Phase 28 reads it when F4 shows a list and after a
     show edit, not on every tick.
2. **`list cue L/C`** prints the cue's state from GAP-46: a line per fixture with each value and
   where it comes from (`101  intensity 100%  color Blue ← 9/1  pan 20 ← 9/2`), then what the cue
   releases, then its effects. `list cues L` marks a block cue `block`. Tab offers `cue` after
   `list`.

   Verify: Song's five cues against GAP-46's read; a fixture whose elements differ; a released
   attribute; a list without tracking.

   **Done** (2026-11-16). The `cue` kind of `_cmd_list` in `src/busk/console/parser.py` reads the
   cue with `self.cue()` and makes a `Query` with a new field, `cue`, the cue's number as the list
   stores it; `Console._list_cue` prints it from GAP-46's read, with `_rows` and `_tracked_value`.
   `cue` is in `LIST_KINDS`, so Tab offers it after `list`. The Outro:

   ```
   cue 9/5 'Outro'
     101  intensity 20%  color 1 1 1 ← 9/4
     ...
     301  intensity 100% ← 9/3  color 1 1 1 ← 9/4
     releases 101 pan tilt, 102 pan tilt
     effect rainbow 'Rainbow' on group 3, 0.25 Hz, size 1 ← 9/4
   ```

   Calls the user may veto:
   - **A first line names the cue,** `cue 9/3 'Pre'`, with `, a block cue` and `(cue list 12 does
     not track)` where they apply, and a cue with nothing shows `  nothing`.
   - **Names in single quotes** (`color 'Blue'`, `cue 9/2 'Verse'`), as `programmer` and `list
     cuelists` print them, where the plan's example has `color Blue`: a preset named `50` would read
     as a value, and the effect lines, which come from `programmer`'s printer, have them.
   - **A 0-to-1 scalar in per cent** (`intensity 70%`, as the plan's example and `set` take it),
     where `programmer` prints `0.7`; colours as `set` takes them (`1 0.75 0.45`).
   - **A fixture's line** holds its values only when every element has the same; otherwise each
     element has a line (`301.3`), also when only some have values. Labels are right-aligned to the
     widest.
   - **Releases on one line,** per fixture as values are (`releases 101 pan tilt, 102 pan tilt`),
     and effects as `programmer` prints them, `← L/C` after a tracked one.
3. **GAP-47: `cue L/C block on|off`** is one undo step, with a reply in words (`cue 9/3 tracks
   nothing from the cues before it`, `cue 9/3 tracks again`). On a list without tracking it goes
   through, and the reply says it does nothing until tracking is on. Tab offers `block`, then `on`
   and `off`.

   Verify: on, off and `undo`; the compiled states change (a block cue drops what it tracked, and
   the cues after it track from it); `list cues`; the generic edit still works.

   **Done** (2026-11-16). `Parser._block` in `src/busk/console/parser.py`, reached from the `cue`
   head when `block` is followed by `on` or `off`, in any case; `block true`, `block false` and any
   other value stay the generic edit, with its path. `on` sets `block`, `off` deletes it, each one
   labelled undo step. Blocking Pre on the club show drops the heads and Blue from it, and Chorus
   then has no pan or tilt, and tracks the bar's intensity from `3`. The entry, its Summary row and
   its **Done** are in engine-gaps.md.

   Calls the user may veto:
   - **A line that changes nothing is refused** (`cue 9/3 is a block cue already`, `cue 9/3 is
     not a block cue`), and spends no step, as call 11 does for a mode.
   - **`off` deletes the key** rather than setting `false`, so the cue is as one recorded without
     it.
   - **On a list without tracking** the reply reads `cue 18/2 is a block cue; cue list 18 does not
     track, so that changes nothing until tracking is on`, and the validator's warning of the same
     still follows it, with its path (`warning cueLists[17].cues[1].block: block has no effect
     without tracking`), as every new warning of an edit does.
   - `block on` on a list's first cue goes through and changes nothing in the states, as the
     compiler has it; the reply does not say so.
2. **`list cue L/C`** prints the cue's state from GAP-46: a line per fixture with each value and
   where it comes from (`101  intensity 100%  color Blue ← 9/1  pan 20 ← 9/2`), then what the cue
   releases, then its effects. `list cues L` marks a block cue `block`. Tab offers `cue` after
   `list`.

   Verify: Song's five cues against GAP-46's read; a fixture whose elements differ; a released
   attribute; a list without tracking.
3. **GAP-47: `cue L/C block on|off`** is one undo step, with a reply in words (`cue 9/3 tracks
   nothing from the cues before it`, `cue 9/3 tracks again`). On a list without tracking it goes
   through, and the reply says it does nothing until tracking is on. Tab offers `block`, then `on`
   and `off`.

   Verify: on, off and `undo`; the compiled states change (a block cue drops what it tracked, and
   the cues after it track from it); `list cues`; the generic edit still works.

Add the entries and Summary rows for GAP-46 and GAP-47 to engine-gaps.md. Docs: `docs/console.md`
(the List row, and "Tracking lists record changes only"), `docs/library.md` (the read), and
`CHANGELOG.md`.

**Done** (2026-11-16). engine-gaps.md: GAP-46 and GAP-47, with their Summary rows.
`docs/console.md`: the Session row (`list cue 9/2`), the Timing row (`cue 9/3 block on|off`) and
"Tracking lists record changes only". `docs/library.md`: the read, with a running example, its
three reference rows, `tracking` in `OfflineShow`'s row, and "The 44 names" (it said 39, stale
since GAP-27). `docs/dev/internals.md`: "The tracked states". `docs/dev/benchmarks.md`: the read's
cost. `busk help` and the parser's module docs: the two grammar lines and a paragraph each.
`CHANGELOG.md` under Added. §7's items.

**Phase 27 checks** (2026-11-16), on top of `17d534a`. The whole suite: 6,701 passed and 1
skipped, in 8:18 with `uv run pytest -n 6`. The run before failed twice: the docs test, which read
`docs/library.md` while its reference rows were being written, and F6's real-engine preset test,
flaky under `-n 6` as Phases 15, 22, 25 and 36 note; it passed three times alone. `ruff check`,
`ruff format --check`, `mypy src` and `mypy --strict tests/api_consumer.py` clean. The public
API's golden took `tracking` on both facades and the three new classes (`BUSK_REGOLDEN=1`). No
TUI file changed, so the TUI rules, Textual 8.2.0 and the perf gate do not apply.

Mutations of `tracked.py` (block ignored, a release that does not remove, the cue's own values
not winning, a tracked effect's slots or a replaced instance's left out of `released`, values or
effects never tracked), of `_block` (no refusal, `off` setting `false`, no word on a list without
tracking) and of the printer (a fixture's line without counting its elements, no `block` mark,
no `←` on an effect) each fail a test. The first rule for `released` let the cue's own effects
keep a slot from its releases. A mutation survived it, and the compiler showed it wrong: a
release drops a tracked value even where the cue's own effect drives the slot. What an own
instance does is take the place of a tracked one with its id, which the release then does not
trim. The rule and its test now say so.

The read's cost, on the §19 reference rig with 4-cue tracking lists, is linear: about 2.7 ms per
1,000 values over a list's cues. That is 8.2 ms for most of its 60 lists (3,000 values) and up to
162 ms for the three whose cues cover whole universes (about 55,700). Giving each tracked value
one object, shared by every cue it reaches, saved nothing there (163 to 162 ms), since those
values are mostly each cue's own, so it was taken out again.

A real `busk run club.show --state-dir …` (processes), the club script first, then lines piped
in: `go 9`; `list cue 9/3` printed Pre, the heads tracked from 9/2 and Blue from 9/1; `cue 9/3
block on` replied in words and `list cues 9` marked Pre `block`. `list cue 9/4` then lost the
heads' pan and tilt, and `undo` brought them back (`pan 'Audience' ← 9/2`). `cue 9/3 block off`
was refused (`cue 9/3 is not a block cue`). `cue 18/2 block on` said a list without tracking
changes nothing, and `list cue 9/9` was refused in words. `tests/test_tracked_states.py` runs the
same under `busk run` with processes and with `--threads`.

### Phase 28: F4's track sheet

Needs Phase 27. Its shape waits on Q10. Code: `src/busk_tui/bridge.py`, `src/busk_tui/model.py`,
`src/busk_tui/pages/cues.py`, `src/busk_tui/widgets/cuetable.py`.

1. **The bridge reads GAP-46** for the list F4 shows: when the list is shown and after a show edit,
   not every tick.

   **Done** (2026-11-16). `Bridge.track(L)` (in `BridgeLike` too) says which list the reader reads.
   The app calls it with the shown page's `Page.tracks()`, as it calls `watch` with `watches`: on
   a page switch, and when a page posts `Page.WatchesChanged`. F4's `tracks()` is the list it
   shows (other pages' `None`), and F4 posts the message when that changes. The
   reader calls `LiveShow.tracking(L)` at its next look, then again only when the show document
   is a new object (an edit) or the list changes. It sends `TrackingChanged(TrackSheet)` when the
   sheet differs from the last one sent; after a new `track`, it sends the next read whatever it
   is. `track_sheet` turns busk's `TrackedCue`s into the model's `TrackSheet`, `TrackCue` and
   `TrackValue` (a preset by its name, the value as `_value` reads one, `since` for
   `trackedFrom`). `CueInfo.block` now comes from the show, for `[block]`. The read runs on the
   reader thread, never the UI's; Phase 27 measured up to 162 ms on the reference rig, once per
   edit.

   Calls the user may veto:
   - **Read only while F4 shows the list,** not while another page shows: each read costs busk a
     pass over every value of every cue.
   - **The sheet leaves the effects out.** TRACK's cells are values; the cue table's `fx` column
     and F5 show effects, and only the cue's own.
2. **The track view**, under Q10's answer. Under (b), the list's panel gets `[cues]` and `[track]`
   chips. The `track` view keeps the table's rows (one per cue) and its first columns (`▶`, `L/C`,
   name). Then it has a column per fixture for one family, chosen by chips (`intensity`, `color`,
   `position`, `beam`, `focus`, `shutter`). Each cell is:
   - the value the cue stores, bright;
   - a tracked value, dim;
   - `✕` where the cue releases it;
   - `·` where there is nothing.

   A fixture whose elements differ shows `mixed`, as F2's PROGRAMMER CONTENTS does. A block cue's
   row is marked. Fixtures past the width either scroll or are counted (`+6 fixtures`); the step
   picks one and says which. With the mouse on a cell, the hint row says where its value comes from
   (`201 color Blue, tracked from 9/1`). A click on a row chooses the cue, as in `cues`, so the
   `edit` row acts on it.

   **Done** (2026-11-16), under Q10 (a), the user's word after a first build under (b). That
   first build was a track view: `[cues]` and `[track]` chips switched F4's table to a row per cue
   and a column per fixture for one family, 8 cells wide, with `[◂]` `[▸]` along the fixtures.
   The user's check found it confusing and its columns too narrow to read ("change my mind and
   implement it following the (a) answer"), so it was taken out, chips, scrolling and all, and
   TRACK built in its place.

   `src/busk_tui/widgets/trackpanel.py`: `families(sheet)` gives the families the list's cues use,
   and `track(cue, L, families, mode)` the chosen cue's table, which F4 keeps for the newest
   sheet, cue and colour mode. `TrackTable` is a `RowTable` whose columns are its own:
   `RowTable.columns()` now returns the class's `COLUMNS`, and `TrackTable` overrides it.
   - **Where:** a panel of its own, `TRACK 9/3 · Pre`, under CUELIST (both in a column of their
     own, which goes over CUELISTS below 100 columns, as CUELIST did). It follows the chosen cue,
     as the `edit` row does: the row clicked last, else the cue the playback is on, else the
     first. A list with no cues has no panel.
   - **Rows** are the fixtures the cue gives a value of, or takes one away from, by number.
   - **Columns** are the families that any cue of the list uses (`intensity`, `colour`,
     `position`, `beam`, `focus`, `shutter`, in that order), so they stay while the operator
     moves from cue to cue. Each has a least width (intensity 14, colour 24, position and beam 22,
     focus 12, shutter 16), the last takes the room left, and when narrow the last go first. At
     80 columns Song's three families show.
   - **A cell**: the cue's own value bright; a tracked one dim, then `← 9/1` in grey. A preset by
     its name, a colour with its swatch and components, a number in its unit. Each attribute
     named where the family has several (`pan -30° tilt 40°`), once where one preset gives them
     all (`Audience ← 9/2`). Where they come from different cues, each says its own, with `·`
     between (`pan -30° · tilt 40° ← 9/2`). `mixed` where the elements' values or presets
     differ, `← several cues` where they come from different cues. `✕` in amber for an attribute
     released, `✕ released` for the whole family, `·` for nothing.
   - **A line over the table** says when the cue is a block cue (`a block cue: it tracks nothing
     from the cues before it`) or the list does not track (`cue list 10 does not track: each
     value is the cue's own`). Until the sheet arrives, the table says `reading the tracked
     states…`; a cue with nothing on stage, `cue 30/1 gives no fixture a value`.
   - **The hint row**, with the mouse on a cell: `201 color Blue, tracked from 9/1`, `101
     intensity 70%, stored in this cue`, `101 pan released · tilt released`.
   - The panel is only to look: no click, and no pane cursor stop.

   Calls the user may veto:
   - **A panel of its own under CUELIST,** not inside it between the table and the buttons: its
     height changes with each cue's fixtures, and would move the buttons under the mouse.
   - **The columns are the list's families, not the cue's,** so they do not jump from cue to cue;
     a family the chosen cue lacks shows `·`.
   - **The cue's own values carry no mark**, only the tracked ones a `← L/C`.
   - **A literal colour shows its components** (`1.00 0.75 0.45`), as F2's PROGRAMMER CONTENTS.
   - **The effects are not shown:** see step 1's calls.
3. **`[block]`**, in the `edit` row and lit on a block cue, sends `cue 9/3 block on|off` without a
   question: `undo` takes it back.

   Verify: the club show's Song with tracking on; every family chip; a narrow terminal; the perf
   gate on F4; a test on the real engine (`[block]`, then the view changes).

   **Done** (2026-11-16). `commands.cue_block`, with two rows in the contract table and a run in
   `test_the_cue_and_list_lines_do_what_they_say`. `[block]` comes after `[release…]`, amber, and
   reversed on a block cue: a span, not the label's base style, since `Text`'s equality ignores
   that, and the strip would not redraw. It sends without a question. On the real engine,
   `[block]` on Pre makes TRACK say so and drop the heads and Blue from Pre, and the heads'
   position from the Chorus, and `undo` brings them back.

   Call the user may veto: **`[block]` stays live on a list without tracking.** busk takes the
   line and says that it changes nothing until tracking is on.

Docs: the guide's F4, the report's Cues rows, and `CHANGELOG.md`.

**Done** (2026-11-16). The guide's F4: its drawing redrawn from a 150-column capture, with
`[block]` and TRACK on Pre, a TRACK section, and a `[block]` item in the `edit` row. The report:
the Phase 27 and 28 sentence in its opening, and two Cues rows, "Show the tracked state" and
"Block". `CHANGELOG.md` under Added. §7's items and Q10's answer.

**Phase 28 checks** (2026-11-16), on top of `7b716b6`, after the rebuild under (a). The whole
suite: 6,714 passed and 1 skipped, in 8:50 with `uv run pytest -n 6`. `ruff check`, `ruff format
--check`, `mypy src` and `mypy --strict tests/api_consumer.py` clean. On Textual 8.2.0, the
floor, the new tests, F4's, the commands' and the bridge's: 532 passed. New tests:
`tests/tui/test_tui_track.py` (10: the table, its cells and hints on the club show's real
states, named and mixed attributes, a list without tracking, the bridge's reads, and on F4 the
panel following the cue and the list, a block cue, a cue with nothing, a list with no cues, the
hint row, 80 columns and `[block]`), the real-engine
`test_f4_tracks_the_chosen_cue_and_blocks_it_on_the_real_engine`, and two contract rows. Two F4
tests changed: the `edit` row and the pane cursor's stops have `[block]`.

The perf gate: F4, which now reads and draws TRACK, +0.189 with no overruns. The gate failed on
F6 editing a position preset (+0.273), a page this phase did not change. Run one by one, F6
gave +0.256 and +0.258 with this phase and +0.257 and +0.240 at `7b716b6`, so it sits on the
limit on this host as it is; F8 +0.199. During the first build, the gate failed on F1 C
(+0.251). Ten runs each, at `7b716b6` and with the first build, in both orders, averaged +0.247
and +0.252, and whichever ran second was higher: F1 C sits on the limit too. The rest passed:
F1 B +0.205, A +0.210, C +0.215, F2 +0.181 and +0.248 with P11's Circle running, F3 +0.204,
F5 +0.234, and every standalone page at 98% of the bare rate or more.

A real terminal (`busk-tui club.show --state-dir …`, which runs `busk run` with processes, in a
pty, at 150 and 99 columns): TRACK on Pre showed the heads' 70% and Audience from 9/2 and the
washes' Blue from 9/1, and on the Outro `✕ released` for the heads' position. `[block]` on Pre
said so over the table and dropped the heads and Blue, and `undo` brought them back. The hint
row named `201 color Blue, tracked from 9/1` under the mouse. At 99 columns TRACK sits between
CUELIST and CUELISTS. The guide's drawing comes from the 150-column capture.

### Phase 29: Timing per target

The user's word of 2026-11-12. busk times a cue, and each family of a cue (`cue 9/2 time position
4`), but not a single fixture: no line staggers eight spots, each starting a little after the one
before. The model has an entry's own timing (`TimingOverride`), but only the generic edit reaches
it, by rewriting the cue's whole `entries` list as JSON, since an entry has no id a path can name.
`load cue` leaves that timing out, and `record … replace` drops it (Phase 25). Its shape waits on
Q11. This phase is engine only; F4 is Phase 30. Code: `src/busk/model/entry.py`, where the
compiler applies an entry's timing, `src/busk/commands/record.py`,
`src/busk/session/programmer.py` (`LOAD_CUE`'s note), `src/busk/console/parser.py` (`_cue_verb`).

1. **GAP-48: timing per target**, under Q11's answer. Under (a):
   - An entry's timing takes a fan: `fadeTo` and `delayTo` beside `fade` and `delay`. The fan
     spreads over the entry's targets in their order, as a spread value does (`spread_fraction`,
     with its `curve`: linear, center or edges). An entry on a group fans over the group's members,
     so a fixture that joins the group takes its place in the fan. The fields are optional, so
     `schemaVersion` stays 1, as it did for `safety`.
   - `cue L/C time <targets> <family> <fade> [to <fade>] [delay <d> [to <d>]] [center|edges]`
     sets the own timing of the cue's entries of that family on exactly those targets: a group by
     its number, fixtures as a list. The cue's other entries keep theirs. `cue L/C time <targets>
     <family> none` removes it. A cue with no entry on those targets is refused in one line that
     names the targets it has for that family (`cue 9/1 sets position on group 1 and fixture 301:
     name one of them`). One undo step, with a reply in words.
   - `record cue L/C merge|replace` keeps an entry's own timing when it records the same targets
     and attribute again. The note `load cue` prints changes to say so.

   Add the entry and its Summary row to engine-gaps.md, and update `docs/console.md`, `busk help`
   and `expected()`.

   Verify: the compiled fades (each target's start and end) for a fan up, down, center and edges;
   a group that gains a member; a family's own timing beside an entry's (the entry's wins); `none`;
   the refusal; `load` then `replace` keeps the timing; a show file of today loads; a running
   `LiveShow`.

   **Done** (2026-11-17), under Q11 (a). `TimingOverride` in `src/busk/model/entry.py` gains
   `fadeTo`, `delayTo` and `fan`, with `same_targets`, which the line and recording share;
   `fanned` in `src/busk/compiler/cues.py` places each member in the fan, where `CueCompiler.own`
   takes an entry's timing; the line is `_entry_time` (and `_spec_words`, for its refusal) in
   `src/busk/console/parser.py`, reached from `_cue_verb` when `fixture` or `group` follows
   `time`; `keep_timing` in `src/busk/commands/record.py`; the validator's `_entry_timing`. GAP-48
   and its Summary row are in engine-gaps.md, with a **Since** under GAP-44. `busk help` and `?`
   have two grammar lines; Tab offers `fixture` and `group` after `time`, then `to`, `delay`,
   `center` and `edges` where they may come. `docs/console.md`'s Timing and `load cue` items, the
   spec's model and §9.1, and `CHANGELOG.md` (Added, and Changed for recording).

   On the club show, `cue 9/1 time group 2 intensity 2 delay 0 to 1.5` brings the four washes up
   half a second apart, and on stage five heads with `delay 0 to 2` and no fade light one by one.

   Calls the user may veto:
   - **`fan`, not `curve`,** names the fan's shape in the model: an entry's `curve` is already its
     fade curve. Absent, the fan is linear.
   - **The line sets the timing whole,** as the family line does: the delay 0 unless given, and a
     curve only if one follows (`[<curve>]` after the rest). The plan's grammar had no curve; the
     line takes one so that it never drops a curve it could not set back.
   - **Exactly those targets** is `group N` for an entry on that group, and fixtures for an entry
     on a list of the same targets, in any order. A group and a list of its members differ, as
     recording keeps them apart. Every entry of the family on them takes the timing (pan and
     tilt both, for `position`).
   - **The refusal comes as soon as the family is read,** so `?` says it before the times are
     typed. It names the targets as a line takes them: `group 3`, `fixture 101 thru 103, 105` (a
     run of three or more whole fixtures in number order), `fixture 301.1, 301.2` (elements).
     The reply names the targets the same way, not as typed.
   - **A fan counts a target without the attribute,** as a spread does: a par in a group of heads
     keeps its place in a pan fan.
   - **`center` or `edges` without a `to` is refused,** in words, rather than kept and doing
     nothing. The validator warns of such a `fan` in a show file, and refuses a `fadeTo` without
     a `fade` or a `delayTo` without a `delay`.
   - **A `merge` that covers part of an entry** leaves the rest with its timing as it was, so a
     fan there spreads over the targets left, and the covered targets' new entry has none. A
     list that recording now covers with a group is not the same targets, and loses it.
   - **`list cues` shows it** (added at the user's word, the same day, after the first build):
     after the cue's and its families' timing, in the cue's entry order, each item as the line
     takes it after `time` (`time 3 easeInOut, group 2 intensity 2 delay 0 to 1.5  go`), so it can
     be typed back. Entries of a family on the same targets with the same timing come once.

Under (b), step 1 is timing in the programmer, as grandMA3 has it: `set … delay 0 to 2`, held with
each slot's value and recorded into the entries. The step then says what `load cue` brings back.

**Phase 29 checks** (2026-11-17), on top of `76d302e`. The whole suite: 6,972 passed and 1 skipped, in 11:10 with `uv run
pytest -n 6`. The first run failed one test, F4's `test_the_timing_forms_words_are_busks` in
`tests/tui/test_tui_commands.py`, which held busk's words after `cue 9/1 time ` equal to F4's
family chips: busk now offers `fixture` and `group` there too, and the test says so, the one TUI
file this phase touched (420 passed on Textual 8.2.0 too). `ruff check`, `ruff format --check`,
`mypy src` and `mypy --strict tests/api_consumer.py` clean. New tests: `tests/test_entry_timing.py`
(50, three of them for `list cues`), nine completion rows in `tests/test_console_prompt.py` and its grammar test, and
`tests/test_load_cue.py`'s note test, which now records back with the timing kept.

A real `busk run` of the club show (processes, `--state-dir` in a temporary directory), lines
piped in: the washes' fan in 9/1, the refusal on 9/3 (`cue 9/3 sets intensity on group 3 and
group 2: name one of them`), a centre fan with `easeOut` on the heads' position in 9/2, `go 9`,
`none` and `undo` on the running list, `load cue 9/1` (the note) and `record cue 9/1 replace`,
then an `edges` fan and `save`. The saved file holds the fans, 9/1's through the round trip. No
perf gate: no page changed.

With `list cues`, the same day: the whole suite, 6,974 passed, 1 failed and 1 skipped, in 9:59.
The failure was F6's real-engine preset test, flaky under `-n 6` since Phase 15; it passed three
times alone. Lint and `mypy` clean.

### Phase 30: F4's timing per target

Needs Phase 29, built under Q11's answer. Code: `src/busk_tui/widgets/cue_dialogs.py`
(`TimeDialog`), `src/busk_tui/pages/cues.py`, `src/busk_tui/commands.py`, `src/busk_tui/model.py`.

1. **F4's TIME dialog chooses targets.** After a family chip comes a chip for each target that the
   cue's entries of that family have (`Heads`, `301`), plus `[all]` for the family's own timing, as
   today. On a target, the fields are the fade and its `to`, the delay and its `to`, and `[centre]`
   `[edges]`, filled in with what the entry holds. The dialog sends `cue 9/1 time group 1 position
   4 delay 0 to 2`, and `[none]` (Ctrl+N) takes the timing away.

   **Done** (2026-11-17), under Q11 (a). `StoredValue` gains `timing`, an `EntryTiming` (`fade`,
   `delay`, `fadeTo`, `delayTo`, `fan`, `curve`), which the bridge's `entry_timing` reads, so the
   dialog knows what each entry holds. After a family the cue has entries of, TIME has an `on` row
   (`entry_targets` in `src/busk_tui/widgets/cue_dialogs.py`, a `PickRow` per family): `[all]`,
   the family's own as before, then a chip per target, a group by its name and fixed elements as
   F3 writes a selection (`[301]`, `[301.2 thru 301.4]`, `[102, 101]`). Entries on the same
   targets (pan and tilt, or a list in another order) are one chip, as busk's `same_targets` takes
   them. The line names them `group 1`, or `fixture 101 thru 102, fixture 301.2`, the set busk
   compares. A contract test sends every chip of the club show's cues through busk (50, with cues
   recorded on fixtures out of order, on bar cells and on the whole bar with `freeze`). On a
   target the form has `fade` and `to`, `delay` and `to`, and `fan` (`[linear]` `[centre]`
   `[edges]`). It sends `commands.entry_time` (`cue 9/1 time group 2 intensity 3 delay 0 to 1.5`),
   and `[none]` sends `commands.no_entry_time`. The fields start at the targets' own timing, else
   the family's own, else the cue's in. They fill in again only when the family or the targets
   change (`TimeDialog.where`), so a click on a fan chip keeps what was typed.

   Calls the user may veto:
   - **The fan's chips are three, `[linear]` `[centre]` `[edges]`,** one always chosen, as the
     form's other chips are, rather than F6's two toggles. The labels are F6's (`centre`), the
     line busk's (`center`).
   - **A shape without a `to` is refused in the form** (`centre shapes a fan: give the fade or the
     delay a to`), as busk refuses it. An empty `to` is no fan; a wrong one says `to: a time in
     seconds, such as 2; empty: no fan`.
   - **Targets with timing of their own are sent only when something changed;** targets without
     are always sent, as a family without is.
   - **The `on` row shows only on a family the cue has entries of.**
   - **The targets' own curve is kept** in the line, as a family's is. The form has no chips for
     it; `[curve…]` sets the cue's.
   - **Entries on the same targets that differ** (only the generic edit can do that) start the
     form at the first with timing of its own, and the line sets them all alike.
   - **A stored shape without a `to` reads as `[linear]`:** it does nothing, so the form counts it
     as unchanged and sends nothing for it.
2. **The time cell** shows that a cue has timing per target, after the families (`2, position 4,
   +1 own`), and the dialog shows which targets. The step may word this another way if it fits
   better, and says why.

   Verify: the dialog on the real engine; the cell; Esc sends nothing; 99 columns; the perf gate on
   F4.

   **Done** (2026-11-17), reworded: the count comes **before** the families, `2, +1 own, position
   4`, and `3, +1 own` on a cue without them. The time column is 13 cells and never grows (only
   the name takes the room left), and `2, position 4` fills it on the club's Verse already, so a
   mark after the families would be cut on every cue that has a family's timing. Before them, it
   shows on any cue whose times are short, and the dialog's `on` chips name the targets.
   `formats.own_timings` counts targets with timing of their own, each family apart, and entries
   on the same targets once: a fan on the heads' position is `+1`.

Docs: the guide's F4, the report's Cues rows, and `CHANGELOG.md`.

**Done** (2026-11-17). The guide's F4: the cue row's time cell, and a paragraph on the `on` chips
under `[time…]`. The report: the Phase 29 and 30 sentence in its opening, the count in the Show
row, and a Cues row "Timing per target, a fan". `CHANGELOG.md`: a sentence under Phase 29's Added
item. §7's item. The guide's drawing stays: the club show has no timing per target.

**Phase 30 checks** (2026-11-17), on top of `a4781fb`. The whole suite: 6,991 passed and 1 skipped, in 10:05 with `uv run pytest -n 6`. `ruff check`,
`ruff format --check`, `mypy src` and `mypy --strict tests/api_consumer.py` clean. On Textual
8.2.0, the floor, the four files the phase touched (`test_tui_cues.py`, `test_tui_commands.py`,
`test_tui_conversion.py`, `test_tui_e2e.py`): 636 passed. New tests: in `test_tui_cues.py`, the
time cell's count, the `on` row and its Tab order, the fields' start and the lines sent, a start
at the family's own, the form's refusals, `[none]` by click and Ctrl+N, a shape without a `to`,
entries on the same targets as one chip, and target names at 99 columns (a long name's note
wraps; it was cut at first, 60 cells in a 54-cell dialog, and the notes now wrap at the
dialog's width). In `test_tui_commands.py`, three contract rows, the lines doing what they say,
the seconds agreement for the `to`s, and every chip the club show's cues give, sent through
busk. In `test_tui_conversion.py`, two reads of an entry's timing. On the real engine,
`test_f4_fans_a_groups_timing_in_the_time_dialog_on_the_real_engine`. Ten mutations of the new
code: eight caught at first. One survivor was equivalent (the delay sent when only its `to` is
given), and that code now has the simpler form. The other (a later entry without timing
replacing an earlier one's) is caught by a new test.

The perf gate: 8 passed, F4 +0.178 with no overruns; F6 +0.234, F1 C +0.221, the rest from
+0.168 to +0.206, and every standalone page at 98% of the bare rate or more.

A real terminal (`busk-tui` on the club show with `--state-dir`, which runs `busk run`, in a pty,
at 150 and 99 columns): TIME on 9/1, `intensity`, `[Washes]`, a delay `to` 1.5 sent `cue 9/1
time group 2 intensity 3 delay 0 to 1.5`; busk replied `… delay 0 s to 1.5 s`, and the cell
showed `3, +1 own`. TIME opened again at the fan, Esc sent nothing, `[none]` took it away (`3`),
and `undo` brought it back. On 9/2, `position` and `[Heads]` started at position's own 4 s. At 99
columns the dialog fits, and the `[none]` note wraps to a second line. Below 100 columns CUELISTS
is under the screen, so the walk chose Song with → on the empty prompt.

### Phase 31: A recorded spread follows its group

The user's word of 2026-11-12. grandMA3's recipes rebuild a look for a rig that grows. In busk, a
cue recorded on a group already follows the group. After `record group 1 merge` with four more
heads:

- every cue entry on group 1 reaches the new heads;
- a preset of `global` or `profile` scope gives them its value;
- an effect spreads its phase over the group as it now is.

A spread does not follow. The programmer holds each target's value (phase-3-plan decision 7), and
`record cue` stores those values per target even on a group, so a new head gets nothing. Checked on
2026-11-12: `set pan spread -30 30` on group 1, then recorded, is stored as `perTarget`. Its shape
waits on Q12. This phase is engine only. Code: `src/busk/commands/record.py`,
`src/busk/compiler/cues.py` (`spread_fraction`, `spread_value`), `src/busk/session/programmer.py`.

1. **GAP-49: a spread on a group**, under Q12's answer. Under (a), when recording finds a group and
   the values differ, it checks whether they are a spread over the group's members in their order,
   from the first member's value to the last's, `linear`, `center` or `edges`.
   - If they are, it records `{"kind": "spread"}`; otherwise it records per target, as now.
   - It works for scalars and colours, as `set … spread` takes them. The step says how close a value
     must be to the spread's: exactly the float the spread gives, or within a tolerance.
   - Two members always fit a linear spread, which plays the same.
   - `freeze` records per target, as it already records targets.
   - `load cue` still brings each target's value, and recording back finds the spread again. So
     Phase 25's round trip now keeps a spread: update its note and test.

   Add the entry and its Summary row to engine-gaps.md, and update `docs/console.md` ("Recording
   keeps intent").

   Verify: `set pan spread` on group 1, recorded, then a fixture merged into the group: it takes its
   place in the fan and the others move. Also: center and edges; a spread over a span that is not a
   group (per target, as now); values that are not a fan; a colour spread; a tracking list (a
   spread equal to what the list inherits tracks); the round trip on both shipped shows.

   **Done** (2026-11-17), under Q12 (a). `_spread` and `_ends` in `src/busk/commands/record.py`:
   `_entry` calls them for a group's entry whose literals differ, after the group cover, so the
   cover, presets and literals that agree do not change. Each value takes its place as the
   compiler places a spread over the group (member `k` of `n`, a member without the attribute
   keeping its place). The shapes are tried `linear`, `center`, `edges`; for each, the line through
   the values at the lowest and the highest fraction gives the ends. A spread is recorded when it
   gives **every value exactly**, the float the programmer holds, and when `set` would take both
   ends. The ends are tried rounded to 9 decimals first, then as computed. GAP-49 and its Summary
   row are in engine-gaps.md, with a **since** under GAP-44's round trip. `docs/console.md`
   ("Recording keeps intent" and "Editing a cue's values"), the record and programmer modules'
   docs, the spec's §15.3, `docs/dev/internals.md`, two sentences of `docs/tui/guide.md`'s F4
   that said busk records a spread per fixture, and `CHANGELOG.md` (Changed).

   On a running club show, `set intensity spread 20% to 90% center` on the washes, recorded, plays
   20, 66.7, 66.7 and 20 %. With a fifth wash merged into group 2, the same cue plays 20, 55, 90, 55
   and 20 %.

   Calls the user may veto:
   - **Exactly, not within a tolerance.** The cue then compiles to the same lanes, bit for bit,
     until the group changes. A later cue of a tracking list that holds the same values still
     tracks them, since tracking compares lanes exactly. A value off the fan by a rounding error
     stays per target.
   - **The ends are rounded to 9 decimals first.** Where no member sits on an end (`center` over
     four heads has none at `to`), the line reaches it only within a rounding error: `-30 30
     center` gives `30.000000000000004`, and a colour's red `0.2000000000000001`. Rounding gives
     back the typed end, which then fits exactly, and an end at 0 is 0, not `-0` (`set pan
     spread 0 -30 edges` reached it at `-1.8e-15`). Ends with more decimals are kept as computed.
   - **`center` before `edges`.** `edges` from `a` to `b` is `center` from `b` to `a`, the same
     fan, so `set pan spread -30 30 edges` over five heads is stored as `center` from 30 to -30.
     It plays the same, and follows the group the same way. Over four heads only `edges` fits
     exactly, as typed.
   - **Both ends must be values `set` would take.** A line through the values can reach past an
     attribute's range: 50, 100, 100 and 50 % over four heads is a centre fan to 125 %. Such values
     stay per target, so no cue holds a spread no line could type. For a colour, an end outside
     0..1 would not be a valid show.
   - **Two members always fit,** as the step says: different values on a group of two are now a
     spread. A third head that joins takes the middle and moves the second. busk cannot tell a
     typed spread from values set one by one: that is Q12 (a)'s trade.
   - **A spread over a group and more** leaves the group's values on a fan of their own: `set pan
     spread -30 30` on group 1 and fixture 105 records group 1 from -30 to 15, and 105's 30 as its
     own.
   - **A member listed twice** (only the generic edit makes one) takes its last place, whose value
     wins when the cue compiles.
   - **In a tracking list**, the values equal to what the cue inherits are set aside before the
     cover, as before. So a new fan that shares one member's value with the cue before (`-30 60`
     after `-30 30`) loses that member to tracking, the group is not covered, and the other three
     are stored per target, as they were before this phase. Not changed: it would mean covering
     groups with tracked values too.

Under (b), the programmer keeps a fan as a third form of value, beside a literal and a preset
reference, until a later line sets one of its slots, and recording writes it. Under (c) the phase
is dropped.

**Phase 31 checks** (2026-11-17), on top of `cc99879`. The whole suite: 7,021 passed and 1
skipped, in 9:09 with `uv run pytest -n 6`. `ruff check`, `ruff format --check`, `mypy src` and
`mypy --strict tests/api_consumer.py` clean. New tests: `tests/test_record_spread.py` (28). Five
tests changed where they held a spread on a group per target: two in `tests/test_record_cue.py`
(one split into values that are not a fan, on a group of three, and a spread), two in
`tests/test_load_cue.py` (an edit recorded back on two heads; Verse's spread coming back as the
spread), and `tests/tui/test_tui_conversion.py`'s recorded spread, which held busk's recording,
the one TUI file this phase touched (84 passed on Textual 8.2.0 too). One more in
`tests/test_load_cue.py`: a centre fan on the club's washes, loaded and recorded back, is the cue
it was. Eleven mutations of the new code, all caught: without the rounded ends, without the ends
as computed, without the check of the ends, with a fit that is not exact, with a member's first
place, with `edges` before `center`, without the curve, with a wrong `to`, with a spread on a list
of targets, without the rounded colour (caught once the colour case had ends that need it), and
with `-0`.

A real `busk run` of the club show (processes, `--state-dir` in a temporary directory), lines
piped in: the washes' centre fan recorded into list 30, `go 30`, a fifth wash added and merged
into group 2 while the playback ran (`list cue 30/1`: 20, 55, 90, 55, 20 %), `load cue 30/1` and
`record cue 30/1 replace`, then `save`. The saved file holds the spread on group 2, of five
members. No perf gate: no page changed.

### Phase 32: Effect shapes

The user's word of 2026-11-12. A layer runs one wave per effect cycle, so tilt cannot move at twice
pan's rate: a figure eight is a `curve` wave of two cycles, with corners. The library has no tilt
sweep, no random movement, no square dimmer and no two-colour alternation, though `effect template
add` can build each. The engine steps come first. Code: `src/busk/model/effect.py` (`ScalarLayer`),
`src/busk/engine/effects.py`, `src/busk/library/effects.json`, `src/busk/session/library.py`
(`EffectDefaults`), `src/busk/console/parser.py` (`list effects`);
`src/busk_tui/widgets/template_panel.py`.

1. **GAP-50: a layer's `cycles`.** A whole number from 1: how many of its waves the layer runs in
   one effect cycle. The default, 1, is left out of the show file. Its `phaseOffset` stays in
   degrees of its own wave; the step checks this and says. `list effects` and `library` word it
   (`tilt add sine ×2`). The field is optional, so `schemaVersion` stays 1.

   Verify: the waveform at 2 and 3; a phase offset; `bounce` and `reverse`; a rate change keeps the
   layers in step; 0 and 1.5 are refused.

   **Done** (2026-11-17). `ScalarLayer.cycles` in `src/busk/model/effect.py` (`Cycles`,
   `MAX_CYCLES`), `CompiledLayer.cycles` in `src/busk/compiler/effects.py`, read by
   `_Part.evaluate` and `flashes_per_cycle` in `src/busk/engine/effects.py` and by the effect
   status's `_next_cycle`; `_layers` in `src/busk/console/console.py` words it. The entry, its
   Summary row and its **Done** are in engine-gaps.md. What it gives:
   - **A row's phase is `cycles · (b + spread) + phaseOffset / 360`**, `b` the effect's base
     phase. Checked: the `phaseOffset` stays in degrees of the layer's own wave (90° on a ×2 layer
     is an eighth of the effect's cycle), and the instance's phase spread is in degrees of the
     effect's cycle, so every member traces the same shape a part of the cycle later (a test
     follows four heads through an eight). The layers share the effect's clock, so a change of
     rate keeps them in step, and `reverse` and `bounce` run each wave back.
   - **The strobe cap counts every wave:** an intensity square ×3 at 10 Hz under a cap of 1.5
     runs at 0.5 Hz.
   - **The effect status's `wave`** is the effect's next cycle, so a ×2 layer shows two waves.
   - **Words:** `tilt add sine ×2 +90°`, in `list effects`, `library` and
     `EffectTemplateInfo.summary`.

   Calls the user may veto:
   - **At most 100** (`MAX_CYCLES`), where the plan gave no top: a huge number would overflow
     the engine's phase arithmetic, and 100 is far past what a light can show. 0, 101, `1.5`,
     `2.0`, `"2"` and `true` are refused by the schema, by path (`effects[4].layers[0].cycles:
     Input should be greater than or equal to 1`), as every other field of a JSON layer is; F5's
     panel strips the path, and its dialog refuses them first.
   - **Only a wave layer has cycles.** A colour layer cycles faster by listing its colours twice.
   - **`×N` comes after the waveform and before the offset**, and ×1 is never written. A
     `"cycles": 1` typed in a JSON layer is kept as typed; F5 sends none.
2. **The library gains five templates:**
   - `Figure eight`: pan sine, tilt sine ×2;
   - `Tilt sweep`: tilt triangle;
   - `Wander`: pan and tilt random, smooth, different seeds;
   - `Square`: intensity square, duty 0.5, phase 0 360;
   - `Alternate`: red and blue, snap, `groups 2`, phase 0 180.

   The library's defaults also take `groups`, `blocks` and `wings`, for Alternate. F5's TEMPLATES
   lists the new templates at once.

   Verify: each one added to the club show's heads and washes, and what `programmer` and F5 say.

   **Done** (2026-11-17). In `src/busk/library/effects.json`, after Rainbow:

   | Template | id | Layers | Defaults |
   |---|---|---|---|
   | Figure eight | `ef-eight` | pan add sine, tilt add sine ×2 +90° | size 20 |
   | Tilt sweep | `ef-tilt-sweep` | tilt add triangle | size 20 |
   | Wander | `ef-wander` | pan add random (smooth, seed 2), tilt add random (smooth, seed 3) | size 20 |
   | Square | `ef-square` | intensity absolute square, duty 0.5 | phase 0 360 |
   | Alternate | `ef-alternate` | color snap, red and blue | phase 0 360, groups 2 |

   `EffectDefaults` takes `groups`, `blocks` and `wings`; `effect add` starts from them, and a
   line's own wins (`effect add "Alternate" groups 3`). `library` prints them (`(phase 0 360,
   groups 2)`), and `EffectTemplateInfo` has them, `None` where the library has none (the public
   API's golden took the three fields). On the club show, each added to the heads (group 1) and
   the washes (group 2): `programmer` names each as it names every effect, with its rate and size
   (`effect fx5 'Figure eight' on 101, 102, 0.5 Hz, size 20`), and F5's TEMPLATES lists the five
   at once, from the library, Alternate with `phase 0 360 groups 2`. The tests in
   `tests/test_effect_library.py` read the output: the heads draw the eight (pan `-20 cos θ`, tilt
   `20 sin 2θ` about their base), the tilt sweep moves tilt only, Wander stays within ±20 with
   pan and tilt apart, Square lights two washes of four at a time, each half the cycle, and
   Alternate gives each wash the other colour from its neighbour, swapping each half cycle. The
   club show parks wash 204 dark and wash 203's colour red, and limits the heads' tilt to -90..10,
   so those tests unpark and give the heads tilt -40.

   Calls the user may veto:
   - **Figure eight's tilt has +90°,** where the plan wrote `tilt sine ×2` alone: busk's sine as an
     add layer is `-cos`, so with no offset tilt is `1 − 2·pan²`, an arc traced back and forth. At
     +90° it is `sin 2θ`, the eight, and the same offset the Circle's tilt has.
   - **Alternate's phase is 0 360,** where the plan wrote 0 180: busk spreads a phase over the
     count of positions, not one less, so `groups 2` with 0 180 puts the two at 0° and 90°, the
     same colour half the time. 0 360 puts them at 0° and 180°.
   - **Square is an absolute layer** like Chase, with Chase's phase default.
   - **Tilt sweep's size is 20**, the Circle's, where Sweep's pan has 30: a head's tilt range is
     about half its pan range.
   - **Wander's seeds are 2 and 3,** so neither runs in step with Flicker's 1 on the same fixture.
   - **Movement on the washes:** the washes have no pan or tilt, and `effect add "Figure eight"` on
     them is taken in silence and runs nothing, as Circle there is: a finding in §7, not changed
     here.
3. **F5's TEMPLATE panel** gets `[cycles…]` on a wave layer: a dialog for a whole number from 1,
   which sends one `effect template update` line.

   Verify: the dialog; the layer's words; a test on the real engine.

   **Done** (2026-11-17). `src/busk_tui/widgets/template_panel.py`: a `cycles` row between
   `smooth` and `phase offset`, with the layer's cycles (`1` where it has none) and `[cycles…]`, a
   `TextDialog` checked by `check_cycles` (a whole number from 1 to `MAX_CYCLES`, which a test
   holds to busk's). It sends one `effect template update` line with every layer as the show stores
   it; 1 takes the key out of the layer, as busk leaves the default out, and a value left as it
   was sends nothing. A colour layer has no row. The pane cursor stops on `cycles cycles…` before
   `offset offset…`. `layer_text` words `×2` as busk does (a test holds it to busk's `_layers`), and
   TEMPLATES' defaults column says `groups 2` (`TemplateInfo` takes `groups`, `blocks` and `wings`
   from the bridge). The phase offset's dialog now says `in degrees of its own wave`.

   On the real engine (`test_f5_adds_a_figure_eight_and_changes_its_cycles_on_the_real_engine`):
   TEMPLATES lists the five, a click adds a Figure eight to the heads, its panel shows `tilt add
   sine ×2 +90°` with cycles 2, `[cycles…]` 3 on its pan layer makes the running effect's wave three
   crests a cycle, and `undo` brings back one.

   Call the user may veto: **the row comes before the phase offset,** in the order busk words them
   (`×2 +90°`), and shows the plain number.

Add GAP-50's entry and Summary row to engine-gaps.md. Docs: `docs/console.md` (Effects, and the
library's list), the guide's F5, and `CHANGELOG.md`.

**Done** (2026-11-17). engine-gaps.md: GAP-50, its Summary row, and a note in GAP-15 on the new
defaults. `docs/console.md`: the library's list, the defaults, and "A layer's cycles". The spec:
`ScalarLayer.cycles` (§5.10) and the per-member formula (§10.3). `docs/library.md`:
`EffectTemplateInfo`'s three fields. The guide's F5: TEMPLATES' `groups 2`, the layer row's
words and `[cycles…]`. The report: the Phase 32 sentence in its opening and the template row.
`CHANGELOG.md` under Added. §7's items.

**Phase 32 checks** (2026-11-17), on top of `ff3a98e`. The whole suite: 6,770 passed and 1
skipped, in 9:20 with `uv run pytest -n 6`. `ruff check`, `ruff format --check`, `mypy src` and
`mypy --strict tests/api_consumer.py` clean. The public API's golden took `EffectTemplateInfo`'s
three fields (`BUSK_REGOLDEN=1`); no public name was added. On Textual 8.2.0, the floor, F5's
tests, the conversion tests and the real-engine F5 tests: 229 passed. New tests:
`tests/test_effect_cycles.py` (33), seven on the club show in `tests/test_effect_library.py`, nine
in `tests/tui/test_tui_templates.py` and one in `tests/tui/test_tui_effects.py`, and the
real-engine `test_f5_adds_a_figure_eight_and_changes_its_cycles_on_the_real_engine`. The tests
that pinned the library's eight templates now hold thirteen; one looked up `Square` as a name the
library lacks, and now looks up `Zigzag`.

Mutations, each failing a test: the compiler not scaling a row's spread by its cycles, or scaling
its offset too; the engine, the strobe cap or the effect status ignoring cycles; the words leaving
`×N` out or writing `×1`; the plan's Alternate (`phase 0 180`), a Figure eight with no offset on
tilt, `effect add` ignoring the library's `groups`, and Wander's two seeds made equal (which a
first test, comparing floats exactly, let through); in F5, `[cycles…]` keeping the key at 1,
sending a value left as it was, taking 0 or 101, the row without a pane cursor stop, and
`layer_text` without `×N`.

The perf gate: 8 passed. F5 +0.201 with P11's Circle running; F1 B +0.186, A +0.206, C +0.213, F2
+0.173 and +0.226 with the Circle, F3 +0.192, F4 +0.199, F6 editing a position preset +0.219,
F8 +0.212, and every standalone page at 98% of the bare rate or more.

A real `busk run` (processes, `--state-dir` in a temporary directory) of the club show with its
surfaces, bindings and routes taken out, so that it opened no MIDI device, web remote or network
output: `library` listed the five with their defaults (`(phase 0 360, groups 2)`); a Figure eight
on the heads; `effect template update` to pan ×3 and `list effects` worded it (`pan add sine ×3,
tilt add sine ×2 +90°`), and `undo` took it back; `cycles` 0 was refused (`effects[4].layers[0].
cycles: Input should be greater than or equal to 1`); Alternate on the washes, and `effect add
"Square" id sq groups 3`. 838 ticks, no overrun. No real-terminal (pty) walk was made.

### Phase 33: Reusable effect settings

The user's word of 2026-11-12. grandMA3 stores a phaser in a preset, with its speed, size and
phase, and applies it to any selection. A busk show template keeps only its layers. The library's
templates bring defaults to `effect add` (Circle's size 20, Chase's phase 0 360), but a template of
the show's own starts from busk's defaults. So a settled effect is typed in full each time, or set
again on F5's EFFECT panel. Needs Phase 32, whose library defaults this phase extends. Its shape
waits on Q13. The engine step comes first. Code: `src/busk/model/effect.py` (`EffectTemplate`),
`src/busk/session/library.py`, `src/busk/console/parser.py` (`effect add`, `effect template`);
`src/busk_tui/widgets/template_panel.py`, `src/busk_tui/widgets/effect_panel.py`.

1. **GAP-51: a template's defaults**, under Q13's answer. Under (b):
   - A show template keeps `defaults`: everything `effect add` takes except the id. That is the
     rate, direction, size, low and high, phase, groups, blocks, wings, fade-in and masters.
     Embedding a library template copies its defaults.
   - `effect template defaults "Name" <what effect add takes>` sets them all at once, and `effect
     template defaults "Name" none` removes them. `effect add "Name"` starts from them, and the
     line's own words win.
   - `list effects` and `effect_templates()` show them. A master named in the defaults counts as a
     use, for `effect template delete` and for Phase 35's `delete master`.

   Add the entry and its Summary row to engine-gaps.md, and update `docs/console.md` and `busk
   help`.

   Verify: `effect add` with and without defaults, and a line that overrides one; a library
   template embedded; a master named and then deleted; `undo`; a show file of today loads.

   **Done** (2026-11-17), under Q13 (b), the recommended answer, at the user's standing word.
   `EffectTemplate.defaults` and `EffectDefaults` in `src/busk/model/effect.py`, checked by the
   validator's `_defaults`; the library's `EffectDefaults` is now the model's type. In
   `src/busk/console/parser.py`: `template_defaults` (the rule below), `defaults_words` (the
   words), `_template_defaults` (the line) and `_effect_options` (the option loop `effect add` and
   the line share). `_list_effects` and `EffectTemplateInfo` in `src/busk/console/console.py`;
   `_master_users` in `src/busk/console/cascade.py`. GAP-51's entry, its Summary row and its
   **Done** are in engine-gaps.md, with notes in GAP-15 and GAP-53. What it gives:
   - `effect template defaults "Circle" hz 2 size 30 phase 0 360 sizemaster "FX"` stores them in
     an instance's key order and replies `set the defaults of effect template 'Circle': hz 2, size
     30, phase 0 360, sizemaster "FX"`; `list effects` prints them the same way after the layers.
     `effect add "Circle"` starts from them, and each word of its own line wins.
   - **Embedding copies:** `effect add "Alternate"` puts `"defaults": {"phase": …, "groups": 2}`
     in the show's copy. Three goldens (the Phase 5, 6 and 7 shows) took the four library copies'
     defaults, and nothing else.
   - **A master in the defaults blocks `delete master`**, with or without `cascade`: `master "FX"
     is used by effects in cues 11/1, 12/1, the defaults of effect template "Circle" and the
     programmer: change them first`.

   Calls the user may veto:
   - **A copy embedded before this phase takes the library's defaults**, as it did: Appendix A's
     Pulse and every show made before hold copies with no `defaults`, and their `effect add`
     would otherwise change (Pulse from 0.7 to 1). So the rule is: the template's own `defaults`,
     else the library's for its id. `none` on such a copy stores `{}`, since removing the key
     would bring the library's back; on any other template it removes the key.
   - **`none` with nothing to take is refused** (`effect template 'Circle' has no defaults`), as
     `fixture N location none` and `safety strobe off` are. A line that sets the defaults they
     already are goes through, as a rename to the same name does.
   - **A library's defaults name no master**, and a library item that puts `defaults` inside its
     template is skipped: a library cannot know a show's masters, and one place for them is
     clearer. A library's defaults are now checked against its layers too (a size of 2 on a
     multiply layer is skipped and reported).
   - **The values are refused in words, `effect add` too.** The line shares `effect add`'s option
     reader, which now refuses a rate or a multiplier of 0, a size below 0 and 0 groups, blocks or
     wings: `expected a number of groups from 1, got '0'`. Before, `effect add "Circle" groups 0`
     was taken into the programmer (a cue would refuse the effect) and `blocks 0` gave `internal
     error: ZeroDivisionError`, a bug found while building (§7); a rate of 0 and a size below 0
     were refused with a path under the reply. A size above 1 on a template with a multiply layer
     stays the session's refusal for `effect add` (a test holds its two-command reply), and is the
     line's own for the defaults: `effect template 'Pulse' has a multiply layer: expected a size
     within 0..1, got 2`.
   - **`effect template delete` is not refused by the masters its defaults name:** the defaults go
     with the template. The plan's "a use, for `effect template delete`" is read as: the master's
     use, which `delete master` checks.
   - **`EffectTemplateInfo`'s six new fields default to `None`**, so a caller that builds one
     still works. `bpm` is the master's name and the multiplier, and the masters are named, as
     `list effects` names them.
2. **F5.** The TEMPLATE panel shows the template's defaults, with `[none]`. The EFFECT panel's
   `[keep as defaults]` sends the effect's settings as its template's defaults, in one line. A
   template click then adds the effect with those settings.

   Verify: both on the real engine; a template click after `[keep as defaults]`.

   **Done** (2026-11-17). `TemplateInfo` takes the six new fields from the bridge.
   `defaults_words` in `src/busk_tui/widgets/effects.py` words a template's defaults as `list
   effects` does (a test holds the two equal), and TEMPLATES' defaults column uses it. The
   TEMPLATE panel (`src/busk_tui/widgets/template_panel.py`) has a `defaults` row under
   `[rename…] [delete]`: the words, or a dim `none`, and `[none]`, which sends `effect template
   defaults "<name>" none` and is grey with none. The EFFECT panel
   (`src/busk_tui/widgets/effect_panel.py`) has `[keep as defaults]` before `[done]`
   (`keep_defaults`), with `base_effect`, `template_effect` and `kept_settings`. The builder is
   `commands.effect_template_defaults`, in the contract test.

   On the real engine (`test_f5_keeps_an_effects_settings_as_its_templates_defaults_on_the_real_engine`):
   a template click adds a Circle at the library's size 20, and `[keep as defaults]` is grey; at
   size 30 it is live, and sends `effect template defaults "Circle" size 30`; TEMPLATES then says
   `size 30`, and the next click adds a Circle at 30. The TEMPLATE panel's `[none]` takes them
   away, the next click adds busk's size 1, and two `undo`s bring `size 30` back.

   Calls the user may veto:
   - **`[keep as defaults]` sends only what `effect add` would not give anyway:** `forward`, size
     1, phase 0 0, one group, block and wing, no levels, fade-in or masters, and the rate `effect
     add` gives with none (×1 on the show's only speed master, else 1 Hz). So a Circle at `hz 2
     size 30` keeps `hz 2 size 30`, not a line of every setting. An effect that is busk's own in
     everything sends `none`.
   - **It is grey while the template's defaults already make this effect**, compared the same way,
     so a click never spends an undo step on nothing. It is live on a cue's effect, and on a
     programmer effect the selection cannot restate: it changes the template, not the effect.
   - **The defaults row comes under `[rename…] [delete]`,** before the layers, and wraps in the
     panel. A library template's panel has no row: TEMPLATES' column shows its defaults.
   - **No question before either button**: both are one undo step, and §1's rule asks only before
     a cascade, a route's delete or `off`.
   - **TEMPLATES' column writes a beat rate as busk does,** `bpm "Speed 1"` with no ` x 1`, and
     names the master always; the EFFECT panel's own lines name it only when the show has
     several, as before.

Under (c), a preset holds effects as well as values. `record preset` records the programmer's
effects without their targets, and `preset <pool> N` adds them on the selection; the cascades,
`load` and F6's tiles change with it. That is too large for one phase and would be split. Under (a)
the phase is dropped.

Docs: `docs/console.md`, the guide's F5, and `CHANGELOG.md`.

**Done** (2026-11-17). `docs/console.md`: the Effects row, `effect add`'s defaults and its
refusals, a note "A template's defaults", and `delete master`'s uses, in its note and the cascade
table. `busk help` and the parser's module docs: the grammar line and a paragraph on GAP-51. The
spec (§5.10): `EffectTemplate.defaults`, `EffectDefaults` and what the validator holds them to.
`docs/library.md`: `EffectTemplateInfo`'s six fields. The guide's F5: TEMPLATES' defaults, the
TEMPLATE panel's `defaults` row and `[none]`, the EFFECT panel's `[keep as defaults]`, and the pane
cursor. engine-gaps.md: GAP-51, with its **TUI since**, and notes in GAP-15 and GAP-53. The report:
its opening, and the rows "Add to the programmer" and "A template's defaults". §7's items and Q13's
answer. `CHANGELOG.md` under Added, and the `effect add` fix under Fixed.

**Phase 33 checks** (2026-11-17), on top of `615dbd6`. The whole suite: 6,880 passed and 1
skipped, in 9:32 with `uv run pytest -n 6`. `ruff check`, `ruff format --check`, `mypy src` and
`mypy --strict tests/api_consumer.py` clean. The public API's golden took `EffectTemplateInfo`'s
six fields (`BUSK_REGOLDEN=1`), and the Phase 5, 6 and 7 show goldens their library copies'
defaults; no public name was added. On Textual 8.2.0, the floor, F5's tests, the template and
effect panels', the contract and conversion tests and F5's four real-engine tests: 722 passed.
New tests: `tests/test_template_defaults.py` (78), five rows in `tests/test_console_prompt.py`,
11 in `tests/tui/test_tui_templates.py`, 16 in `tests/tui/test_tui_effects.py`, one in
`tests/tui/test_tui_conversion.py`, two builders in the contract test, and the real-engine
`test_f5_keeps_an_effects_settings_as_its_templates_defaults_on_the_real_engine`. Six tests
changed for the new words: `list effects` with the defaults, the embed with them, `effect
template`'s verbs, and two F5 pane-cursor lists that now end `keep as defaults`, `done`.

Mutations, 37, run in a copy: 35 failed a test. Among them `find_template` ignoring a template's
own defaults or the library's for an old copy, `none` removing the key from a library copy, the
embed without the defaults, `effect add` ignoring the defaults' rate, direction or masters, the
line keeping `id` or the order typed, each range check, the multiply check, `bpm … x 1` worded,
`delete master` ignoring the defaults, each of the validator's and the library's checks, `list
effects` and `EffectTemplateInfo` without them; in F5, `kept_settings` keeping busk's own,
`[keep as defaults]` never grey or always a stop, a beat's master named with one speed master,
the base rate wrong, a library template taken for the show's, `[none]` sending nothing or never
grey, and the builder without `none`. Two survived: an `inert` guard in `keep_defaults`, dead
since an inert button calls nothing and the pane cursor skips it, now removed; and the bridge
dropping `bpm`, for which `test_a_template_carries_every_default_busk_lists` now fails, as it
does for each of the six fields.

The perf gate: 8 passed. F5 +0.203 with P11's Circle running; F1 B +0.224, A +0.220, C +0.222,
F2 +0.189 and +0.230 with the Circle, F3 +0.202, F4 +0.196, F6 editing a position preset +0.227,
F8 +0.200, and every standalone page at 97% of the bare rate or more.

A real `busk run` (processes, `--state-dir` in a temporary directory) of the club show with its
surfaces, bindings and routes taken out: `list effects` named the library copies' defaults
(`Circle … (size 20)`); `effect template defaults "Circle" hz 2 size 30 phase 0 360 sizemaster
"FX"`, and `effect add "Circle"` on the heads ran at 2 Hz, size 30; `delete master "FX"` was
refused, naming the cues, the template's defaults and the programmer; `groups 0` and Pulse's size
2 were refused in words; `none`, a Circle at busk's size 1, and two `undo`s back to the defaults;
`effect add "Alternate"` embedded it with `(phase 0 360, groups 2)`, and `effect template defaults
"Alternate" bpm "Speed 1" x 2 groups 3` gave the next one ×2. No overrun. No real-terminal (pty)
walk was made.

### Phase 34: A DMX readout

The user's word of 2026-11-12. Checking a fixture's personality means seeing what busk sends on
each channel, and nothing shows it: F3 shows attributes (intensity, colour, pan, tilt, zoom) and
F8's map shows footprints. The TUI already has every frame (`Bridge.frame`, carried under `busk
run` since GAP-11), but the prompt has nothing. Nor does `list universes` count overlaps, as F8
does. The engine step comes first. Code: `src/busk/console/console.py`, `src/busk/runner.py`,
`src/busk/process/` (what the console process gets under `busk run`);
`src/busk_tui/widgets/dmxmap.py`, `src/busk_tui/pages/patch.py`, `src/busk_tui/hints.py`.

1. **GAP-52: `list dmx`.**
   - `list dmx U [A [thru B]]` prints the channel values of the last frame, which is what goes out
     (§5, call 24), 16 to a line after their address.
   - `list dmx fixture N` prints a fixture's channels with their functions from its mode (`1.17
     pan 128`, `1.18  pan fine  0`).
   - `list universes` adds the channels used and the overlaps (`1  Stage  66/512  2 overlaps`).

   Check first how the console process gets frames under `busk run` with no frontend, and say what
   this step adds there. Add the entry and its Summary row to engine-gaps.md, and update
   `docs/console.md` and `busk help`.

   Verify: the values against `OfflineShow.tick`'s frame; blackout and park; a fine channel; an
   unpatched fixture, refused in words; a universe with no fixtures; under `busk run`.

   **Done** (2026-11-12). `_list_dmx` in `src/busk/console/parser.py` makes a `Query` of kind
   `dmx`, with a new `span` field. `Console._dmx` prints it from a frame source that `Console`
   now takes (`frame=`): `OfflineShow` passes its engine's `latest`, and `LiveShow` passes
   `_fresh_frame`. Both shows of `busk run` go through the latter (`_attached` too).
   `_list_universes` counts from `_patched` and `_functions`, module helpers of `console.py`. The
   entry, its Summary row and its **Done** are in engine-gaps.md. What this step adds under `busk
   run`, which the step asked to check first:
   - **Under `busk run` the console process had no frames.** The engine process sends frames to
     the console process only while it watches them (`WATCH`). Only a frontend asks for them,
     through `LiveShow.frame`, `output` or `health`. A `busk run` without one, at the prompt or
     piped, had nothing. The first `list dmx` now asks (`link.watch(frames=True)`), and from then
     on every frame goes to the console process, as under a frontend. That costs the console
     process 0.015 to 0.036 core and the engine process 0.148 to 0.159 core, measured over 10 s
     on the club show with the song and the chase running, with no frontend.
   - **A frame made after the lines before.** While the engine runs, `_fresh_frame` syncs with
     it (`EngineLink.sync`), then waits for a frame newer than the one it holds, at most
     `FRAME_WAIT_S` (1 s) for each. So `set intensity 100%` then `list dmx 1 9`, piped into
     `busk run`, shows 255. Under processes the first frame comes within a tick of the request.
     A stalled engine gives its last frame after those waits. A `LiveShow` not yet started gives
     `no frame yet: the engine has not run`, and a stopped one its last frame.

   Calls the user may veto:
   - **The layout of `list dmx U`:** 16 values to a line, each 4 cells wide, after the first
     channel's address, which is left-aligned to the widest address of the reply (`1.1  128 …`,
     `1.497   0 …`). A span starts its lines at `A`, not on a multiple of 16. `thru` counts either
     way, as `unbind`'s does.
   - **A fixture's lines:** the address, the function and the value, in aligned columns, one per
     channel of the footprint. A colour channel is named after its emitter (`red`, `white`), not
     after `set`'s components (`color.w`), which name the colour and not the channel. A fine
     byte is `<function> fine` and an ultra byte `<function> ultra`, where the profile puts
     them. On a mode of several elements the profile's element name comes first (`Cell 2 red`).
     A channel the mode does not describe is `unused`, and the first definition of a channel
     wins.
   - **`output off`** adds a first line (`output is off: no route sends these`), since the frame
     is then not what goes out. The reply is not an error.
   - **`list universes`** gives `used/512` always and the overlaps only when there are some
     (`  1 overlap`), as a pair count, the way F8 counts. The name is padded to 20, as `list
     fixtures` pads.
   - **Kind `action` in the Summary,** since it is a line at the prompt; the TUI's read is
     `LiveShow.frame`, which already existed.
   - GAP-45 to GAP-51 stay for Phases 26 to 33, which come later; GAP-52 is used first.
2. **F8's channel values.** A channel's hint adds its function and value (`1.17 · fixture 102 · ch
   1/16 pan · 128`). With one fixture selected, a CHANNELS panel under the maps lists its channels,
   each with its address, function and value, live at 10 Hz.

   Verify: the panel against `list dmx fixture N`; a fixture of several elements; no selection;
   F8's cost (F8 is not in the perf gate: add it).

   **Done** (2026-11-12). The view has a new part, `dmx` (`DmxModel`: the frame's bytes by
   universe number, from busk's `DmxFrame`), sent as `DmxChanged`. The bridge's reader sends it
   while a page with `WATCH_DMX` shows, at most every `DMX_S` (0.1 s), and only when the bytes
   change. `Bridge.watch` takes `dmx=`, and the shell passes the page's `WATCH_DMX` (only F8's
   is true). `FixtureInfo.channels` holds each footprint channel's function, from
   `channel_functions(mode)` in `bridge.py`. On the map, `Footprint.functions` carries them,
   `channel_text` adds the function and the value, and `DmxMap.values()` updates the hint while
   the mouse stays still (the old `_channel` method is now `_under`, since `_channel` is the
   channel under the mouse). F8 has a CHANNELS panel (`ChannelTable`, `channel_cells`) between
   the maps and the legend. The perf gate runs F8 standalone and under `busk run`, with 101
   selected while both heads move.

   Calls the user may veto:
   - **The functions come from the document, not from `list dmx fixture N`'s text,** which the
     TUI never parses (engine-gaps.md, "Text is not parsed"). `channel_functions` names them by
     the same rules as `Console._functions`, and
     `test_each_channels_function_is_what_list_dmx_fixture_prints` holds the two equal on the
     club show, the TupperDMX show and every mode of the library's profiles. The bridge already
     reads each mode's channels for `profile_info`.
   - **The panel's columns are address, value, then function,** where `list dmx fixture N` puts
     the value last. The function column takes the room left, so a long name is never cut, and
     the value sits next to its address on a wide screen. A value of 0 is dim, and `-` means no
     frame has come yet.
   - **The panel always shows.** With no fixture, or several, it says `select one fixture to see
     what busk sends on its channels`, and on an unpatched one `fixture 701 is not patched`, as
     the place strip says what it needs. Its title holds the fixture, its profile and mode, and
     its address. The pane cursor does not stop on its rows, since nothing there acts.
   - **The hint row gives the value of a free channel too** (`1.200 · free · 0`), and the value
     once for an overlap, at the end. While no frame has come, it has no value part.
   - **"One fixture selected"** is F8's own rule for the place (`placing()`): the elements of one
     fixture count as one.
   - The legend's last words are now `hover a channel for its fixture and value; a click selects
     it`.

Docs: `docs/console.md`, the guide's F8, and `CHANGELOG.md`.

**Done** (2026-11-12). `docs/console.md`: the Session row, and a note "What goes out". `busk
help` and the parser's module docs: the grammar line and a paragraph on GAP-52. The guide's F8:
its first lines, the hint row, the CHANNELS panel and the legend. engine-gaps.md: GAP-52, with
its **TUI since**. The report: its header, and the rows "Show" and "What busk sends" of Universes
and routes. §7's item. `CHANGELOG.md` under Added.

**Phase 34 checks** (2026-11-12), on top of `604dc3f`. The whole suite: 6,519 passed and 1
skipped, in 7:56 with `uv run pytest -n 6`. `ruff check`, `ruff format --check`, `mypy src` and
`mypy --strict tests/api_consumer.py` clean. The F8, bridge and conversion tests, the two F8
real-engine tests, and the pages whose watch the shell now passes (F1's layouts, F2, F3, F5, F9,
the frame, help, hints) pass on Textual 8.2.0: 498 tests.

The perf gate passed, 8 of 8. Standalone, F8 kept 100.0 frames/s against 100.0 bare. Under `busk
run`, F8 with 101 selected and P11's Circle running used +0.189 core and had 0 overruns in 1,007
ticks. The other pages: F1 B +0.197, A +0.218, C +0.228, F2 +0.160 and +0.214, F3 +0.190, F4
+0.156, F5 +0.197, F6 +0.206.

A real `busk run` with processes and one with `--threads` are in `tests/test_dmx_readout.py`:
piped `list dmx 1 9` gave `1.9   0` before any frame was watched, then `set intensity 100%` and
`list dmx fixture 101` gave `1.9   intensity      255`. The costs in step 1's notes come from
a real `busk run club.show --state-dir …` with no frontend, the song and the chase running,
`list dmx 1 1` piped in after 10 s. A real `busk-tui club.show --state-dir …` (which runs `busk
run`), in a pty at 150 columns and at 99: F8, `sel fixture 101`, `set intensity 100%` and `set
pan 10` typed. CHANNELS read `fixture 101 Spot 101 · Generic Spot 16ch / 16ch · 1.1`, with 1.1
`132 pan`, 1.2 `189 pan fine` and 1.9 and 1.10 at 255. The hint on channel 9 read `1.9 · fixture
101 · ch 9/16 intensity · 255`, then `… · 51` after `set intensity 20%`, the mouse still. `sel
fixture 301`, `set color 1 0 0` and `set intensity 100%` gave 36 rows from `1.49 128 Cell 1 red`,
the bar at its half limit. `list dmx fixture 101` typed in the TUI printed in the log. At 99
columns the panel fits, under a map at 64 to a row. No error in the log.

### Phase 35: Masters made on F7

The user's word of 2026-11-12. Masters are made only at the prompt (`master add …`), and no line
renames or deletes one: `rename master` and `delete master` are refused (`cannot delete 'master'`).
Needs Phase 33, whose template defaults can name a master, unless Q13 drops it. The engine step
comes first. Code:
`src/busk/console/parser.py`, `src/busk/console/cascade.py`, `src/busk/console/console.py`
(`confirmation`); `src/busk_tui/pages/masters.py`, `src/busk_tui/widgets/masters.py`.

1. **GAP-53: `rename master "<name>" "<new>"` and `delete master "<name>" [cascade]`.**
   - A rename refuses a name another master has, in any case, as `effect template rename` does.
   - A delete is refused while an effect, a chase or a template's defaults name the master, and
     the refusal names them (§5, call 23).
   - A binding that names the master goes with it under `cascade`, after `confirmation()`'s
     question.
   - The grand master can be neither renamed nor deleted.
   - Each is one undo step, with a reply in words. Tab offers the masters' names.

   Add the entry and its Summary row to engine-gaps.md, and update `docs/console.md` and `busk
   help`.

   Verify: each kind of master; each use that refuses; a binding that goes, and comes back with
   `undo`; a running `LiveShow` with the master at a level.

   **Done** (2026-11-12), before Phases 26 to 33, at the user's word. `_rename_master`,
   `_delete_master` and `_own_master` in `src/busk/console/parser.py`, and `master_cascade` in
   `src/busk/console/cascade.py`, with the help line and a paragraph in both modules' docs.
   GAP-53's entry, its Summary row and its **Done** are in engine-gaps.md. Phase 33 is not built,
   so no template has defaults: when it builds them, a master they name joins the uses here, as
   its step 1 says. Tests: `tests/test_master_lines.py` (43) and four rows of
   `tests/test_console_prompt.py`.

   Calls the user may veto:
   - **The refusal of a used master** is one line naming the chases and the cues by number, and
     the programmer: `master "Speed 1" is used by the chase of cue list 10 and effects in cues
     11/1, 12/1, 13/1: change them first`. It comes with `cascade` or without, so a plain
     `delete` never says `add cascade` for a master the cascade cannot take, and Tab then offers
     no `cascade`.
   - **A list in sequence mode that keeps chase settings on the master** counts as a chase: the
     validator reads them, so the delete would fail by path. `cuelist N chase none` frees it.
   - **A binding's `ADD_EFFECT` that names the master goes with `cascade`,** as the group's cascade
     drops one that targets the group. It is a control, not one of the show's effects.
   - **The words of a cascade with bindings** are the group's, preset's and playback's: `Delete
     master "FX"? It leaves 1 binding.`, `deleted master "FX": left 1 binding`, and `master "FX"
     is used by 1 binding: add cascade`. The master is named by its name in quotes, since it has
     no number.
   - **A rename to the name it has, or to an empty one,** goes through, as every other `rename`
     does; F7's dialog sends neither.
   - **`undo` brings a deleted master back at its initial level,** not at the level it had: the
     engine keeps the levels of the masters the show has.
   - Found while building (§7): `master add speed … bpm 0`, `bpm 1000` and `steps 0, 1` were
     refused by document path, and `bpm 50%` gave a tempo of 0.5. Fixed the same day, at the
     user's word: see §7.
2. **F7's masters.** `[+ master…]` opens a form: the kind (speed, size, group, fade time), the
   name, and the group for a group master or the BPM for a speed one. It sends, for example,
   `master add group "Washes" group 2`. Each master has `[rename…]` and `[delete]`; `[delete]` asks
   busk's question for a cascade.

   Verify: each kind added; a rename; a delete refused, in the log; a delete with a binding; a test
   on the real engine.

   **Done** (2026-11-12). F7 has a MASTERS panel (`MasterPanel` in
   `src/busk_tui/widgets/master_panel.py`), the last of its panels. A row per master but the grand
   master: its name in its bar's colour and what it is, then `[rename…]` and `[delete]`. Under the
   rows, `[+ master…]` opens `MasterDialog`, in the same module: the kind's chips, the name, and the
   group's chips or the tempo, by the kind. The builders are `commands.master_add`,
   `rename_master` and `delete_master`, in the contract test. The page builds the panel again when
   the masters change, as it builds the others, and gives it each new show, for the groups and the
   names its dialogs check. Tests: 7 in `tests/tui/test_tui_masters.py` (4 changed for the new
   panel), 22 in `tests/tui/test_tui_commands.py`, and
   `test_f7_makes_renames_and_deletes_masters_from_controls_on_the_real_engine`.

   Calls the user may veto:
   - **One panel lists the masters, with their buttons,** rather than buttons in each kind's
     panel. The panels an operator plays with keep their rows, so nothing moves under a fader;
     MASTERS comes last, after PARKED, so PANIC stays where it was on a narrow screen.
   - **The grand master has no row,** since busk neither renames nor deletes it. A show with no
     other master says `no masters but the grand master · [+ master…]`.
   - **The form starts with an empty name and the cursor in it,** with the kind chips above it
     (speed first). The group chips are `1 Heads`, by number, and the group kind is left out on a
     show with no groups. The tempo starts at 120, busk's own default, and the line always
     carries it (`bpm 120`).
   - **The form checks what it can before it sends:** an empty name, a name another master has
     in any case, and a tempo outside 0 to 999 BPM (`MAX_BPM`, held equal to busk's), each in
     words under the fields. A name is sent without the spaces around it.
   - **`[delete]` always sends `cascade`,** as F3's group `[delete]` does: busk asks, and names
     the bindings. A master in use is not greyed, since the TUI would have to read every cue's
     effects for it: busk refuses it, the log says why, and nothing is asked.
   - **The rename dialog's title is `RENAME MASTER`,** as F5's template one is: a name in a title
     could read as markup.

Docs: the guide's F7, and `CHANGELOG.md`.

**Done** (2026-11-12). The guide's F7 (the MASTERS panel) and its first note; `docs/console.md`
(the Effects, masters row, a paragraph, and a row of the cascade table); `busk help` and the
parser's and the cascade's module docs; engine-gaps.md (GAP-53, with its **TUI since**); the
report's header and its "Beyond this report"; §7's item; `CHANGELOG.md` under Added.

**Phase 35 checks** (2026-11-12), on top of `e76e282`. The whole suite: 6,596 passed and 1
skipped, in 8:24 with `uv run pytest -n 6`. `ruff check`, `ruff format --check`, `mypy src` and
`mypy --strict tests/api_consumer.py` clean. F7's tests, the contract test, the hints and help
tests, and the two F7 real-engine tests pass on Textual 8.2.0: 443 tests. The perf gate was not
run: F7 is not in it, and its per-tick path (levels, beats) did not change; only a show change
now also hands the new show to the panel.

A real `busk run club.show --state-dir …` with processes, lines piped in: with `sel group 2`, `set
intensity 100%` and `master "Wash level" 0%`, `list dmx fixture 201` gave `1.36  white 0`; after
`delete master "Wash level"`, `255`. `rename master "FX" "Size"` and the refusal of `Speed 1` (the
chase of cue list 10 and cues 11/1, 12/1, 13/1) read as in step 1's notes; a binding on `Fade`
refused the plain delete, went with `cascade` (`left 1 binding`), and two `undo` brought both
back.

### Phase 36: The last setup lines on screen

The user's word of 2026-11-12. Three setup lines have no control:

- the discrete attributes on F2 (only F6's PRESET panel has their chips);
- the strobe cap (`safety strobe 3`);
- the show's title (`rename show "…"`).

TUI only. Code: `src/busk_tui/pages/program.py`, `src/busk_tui/widgets/options.py`,
`src/busk_tui/pages/masters.py`, `src/busk_tui/shell.py` (`StatusBar`).

1. **F2's options.** F6's option rows (`widgets/options.py`) come to F2, one row per discrete
   attribute the selection's profiles take: gobos, prisms, the colour wheel, shutter and fixture
   effects. A chip sends `set gobo1 star`, and the programmer's option is lit. SHUTTER's `[set
   shutter…]` gives way to its row.

   **Done** (2026-11-12), before Phases 26 to 33, at the user's word. `attributes.shown` gives
   each F2 panel its encoder rows and the discrete attributes of its family that the rig takes
   (`OPTIONS`); a family with only options gets a panel too. `EncoderPanel` puts an `OptionRow`
   per attribute under its encoder rows, and `show_options` draws them at a show or programmer
   change, not with the output. `[set shutter…]` and `SHUTTER_PREFILL` are gone. Tests: 6 in
   `tests/tui/test_tui_program.py`, on the TupperDMX show and the club show with busk's own
   completion, and 1 changed.

   Calls the user may veto:
   - **A row shows only while the selection offers options for it,** as this step says ("the
     selection's profiles"), where F6's rows stay and say why they offer nothing. F2 follows the
     selection: a spot and a pixel bar show the spot's `gobo1` and `shutter`, and nothing selected
     shows no row. A panel with no encoder rows keeps its option rows, which then say why, so it is
     never an empty box.
   - **The rows come under the panel's encoder rows,** before COLOR's swatches and chips, their
     names 11 cells wide, under the encoders' names. A row's name puts nothing in the prompt, as on
     F6; an encoder's name does.
   - **`[set shutter…]` is gone,** not kept beside the row: the row's chips are what it led to. A
     shutter the selection does not offer has no control on F2, and is typed.
2. **The strobe cap,** in F7's PANIC, shows the cap now (`strobe cap 3 Hz`, or `off`), with `[cap…]`
   (`safety strobe 3`) and `[off]` (`safety strobe off`).

   **Done** (2026-11-12). `ShowModel.strobeMaxHz`, read from `safety.strobeMaxHz` by the bridge;
   `commands.strobe_cap` and `no_strobe_cap`, in the contract test. PANIC has a line under its
   buttons: `strobe cap 3 Hz  [cap…]  [off]`, drawn at each show change (`MastersPage._show_cap`).
   `[cap…]` opens a `TextDialog` (`STROBE CAP`), checked by the chase form's `check_rate`; `[off]`
   is grey with no cap, and the pane cursor stops on it only then. Tests: 3 in
   `tests/tui/test_tui_masters.py` (2 changed for the new stops), and 13 in
   `tests/tui/test_tui_commands.py`.

   Calls the user may veto:
   - **`[off]` asks nothing,** as busk's `confirmation()` asks nothing before `safety strobe off`
     and §1's rule names no safety line. `undo` and `[cap…]` put a cap back.
   - **The dialog takes a plain number above 0, with no top,** as busk has none (`safety strobe
     1000` goes through). It refuses `+4` and `50%`, as busk does since §7's fix of the same day.
     It starts at the cap, every digit, or empty with none, and sends nothing for the cap there
     is.
3. **The show's title.** A click on the status bar's title opens a name dialog that sends `rename
   show "Club Night"`.

   **Done** (2026-11-12). The title in `StatusBar.left_text` carries `@click` meta for the app's
   `action_rename_show`, as the tabs carry theirs, with the tabs' hover look. The action opens a
   `TextDialog` (`RENAME SHOW`) and sends `commands.rename_show`. Tests: 2 in
   `tests/tui/test_tui_frame.py`, and the line in the contract test.

   Calls the user may veto:
   - **Only the title is the link,** not `show` before it or the `*` after it; `—` is, on a show
     with an empty title.
   - **The dialog refuses an empty name,** as every rename dialog does, sends the name without the
     spaces around it, and sends nothing for the title the show has. busk itself takes `rename show
     ""`, as Phase 35's call says every `rename` does.
   - **The click is the only control:** the pane cursor stays in the page, so the keyboard types
     `rename show "…"`. Before the show is there, the click does nothing.

   Verify: each one on the real engine; F2 at 99 columns with a spot and a bar selected; the perf
   gate on F2.

   **Done** (2026-11-12). `test_f2s_options_f7s_strobe_cap_and_the_title_on_the_real_engine`
   selects a spot and a bar, sets a gobo from its chip and sees it lit, sets and takes away the cap,
   brings it back with `undo`, and renames the show from the status bar. F2 at 99 columns: a
   headless test, and a real terminal (pty and pyte) under `busk run`, where the spot's `gobo1` and
   `shutter` rows drew under the encoders' names, one panel under another. The perf gate: in the
   checks below.

Docs: the guide's F2, F7 and the status bar, and `CHANGELOG.md`.

**Done** (2026-11-12). The guide's first note (the strobe cap and the title are no longer typed),
its status bar, F2 (option rows, the pane cursor) and F7 (PANIC); the report's header and its
"Beyond this report"; §7's item; `CHANGELOG.md` under Added.

**Phase 36 checks** (2026-11-12), on top of `5c816bd`. The whole suite: 6,637 passed and 1
skipped, in 8:56 with `uv run pytest -n 6`. `ruff check`, `ruff format --check`, `mypy src` and
`mypy --strict tests/api_consumer.py` clean. F2's, F7's, the frame's, F6's and the contract tests,
and the three real-engine tests of F2 and F7, pass on Textual 8.2.0: 573 tests. 20 mutations of
the new code: all caught, once the title's test pressed `end` before its space (Textual's input
selects its text when it takes the focus, so the space had replaced the title) and clicked the
`—` of a show not yet there; a line no mutation could fail, a new option row hidden before its
first draw, was removed. The perf gate: 8 passed, F2 +0.201 core under busk run, +0.235 with the
heads moving (the gate is 0.25). Every page read 0.04 to 0.05 core more than in Phase 18's notes,
F1 B +0.233; the same gate on `5c816bd`, without this phase, read the same (F1 B +0.230, F2
+0.207 and +0.227), and the status bar's link costs 0.1 µs a draw, so the rise is not this phase's.

A real `busk run club.show --state-dir …`, lines piped in: with 101 strobing at 20 Hz, `list dmx
fixture 101` gave its shutter channel 28 under the club's cap of 3 Hz, 70 after `safety strobe 10`,
and 131 after `safety strobe off`. `busk-tui` under `busk run`, in a pty at 99 columns (pyte): F2
drew the spot's `gobo1` and `shutter` rows with `sel fixture 101, fixture 301`, and `[breakup]`
sent `set gobo1 breakup` (`gobo1: 1 target; skipped 12 no gobo1`); F7's `[cap…]` set 4.5 Hz,
`[off]` took it away, and a click on the title renamed the show (`show Late Night *`).

### Phase 37: Incoming messages on F9

The user's word of 2026-11-18. F9 was built without its MONITOR, its learn mode and the raw value
in BINDINGS (the TUI plan's Phase 4 and its Q12), because busk does not publish what comes in
(GAP-13); §7 had left GAP-13 as not planned. Without it, finding which CC a fader sends needs
another program, and nothing shows that a surface's messages reach busk at all. The engine step
comes first. Code: `src/busk/io/bindings.py` (`BindingResolver.handle` sees every event, bound or
not), `src/busk/io/events.py`, `src/busk/io/midi.py` (`translate`), `src/busk/io/osc.py`,
`src/busk/io/surfaces.py`, `src/busk/runner.py`; `src/busk_tui/bridge.py`,
`src/busk_tui/model.py`, `src/busk_tui/pages/surfaces.py`.

1. **GAP-13: what comes in.**
   - `LiveShow.inputs` gives the newest 64 inputs, oldest first, each with a sequence number, so a
     frontend reads only what is new. An input names its surface, its control as `bind` takes it
     (`cc 1 48`, `note 1 60`, `osc "/fader/1"`, `clock`), the value the device sent (102 for a
     CC, a note's velocity; none for OSC and the clock), the value from 0 to 1 that the bindings
     get, and what its bindings drive, as `list bindings` prints it, or nothing when it has none.
   - Every input is kept, bound or not: an unbound one is what learn mode needs (step 3).
   - It is `()` while no surface is open, and `OfflineShow`, which opens none, has no `inputs`.
   - engine-gaps.md proposes the name `InputEvent`, which `busk.io.events` already has for the
     backends' events. The public dataclass takes another name, and goes in `busk.__all__`.
   - Each surface calls in on its own thread. The log is written under a lock and published as a
     new tuple, as the surfaces' status is (replaced, never changed). A fader sweep sends about
     100 messages a second: measure what the record costs the input thread.
   - Under `busk run` the surfaces and the frontend share the console process, so the read
     should need nothing on the wire. Check it before building on it.

   Update GAP-13's entry, its Summary row and engine-gaps.md's list of reads, and `docs/library.md`.

   Verify: a CC; a note on and off, with its velocity; a pitch bend; the clock; an unbound input;
   an input with two bindings; a message busk cannot bind (a program change), which does not
   show; the sequence past 64 inputs; an OSC surface on localhost, which needs no device, as
   `tests/test_osc.py` sends to one; under `busk run` with processes and with `--threads`.

   **Done** (2026-11-18). `LiveShow.inputs -> tuple[SurfaceInput, ...]`, `SurfaceInput` in
   `busk.__all__` (45 names). The log is `busk.console.inputs.InputLog`, in the console's words:
   the control through `_input` (which now words a pitch bend `bend 1`, for `list bindings` too)
   and each binding's action through `_action` (`_binding_names`, shared with `list bindings`).
   `BindingResolver` takes `record=` and calls it after an event's commands, with the bindings it
   found; a monitor that raises is reported once and the bindings keep working.
   `busk.io.events.InputEvent` gained `raw`, filled in by `midi.translate`. The read needed
   nothing on the wire: the surfaces, the resolver and the log live in `busk run`'s console process
   with the frontend, with processes and with `--threads`, both tested. The record costs the input
   thread 2.4 µs (the resolver's own work, 0.7 µs), so a sweep of 100 messages a second costs
   0.02 % of a core. GAP-13's **Done**, `docs/library.md`, `docs/dev/internals.md` ("The input
   monitor"). Tests: 21 in `tests/test_surface_inputs.py`, the 7 `translate` cases of
   `tests/test_midi.py` with `raw`, the public API golden and `tests/api_consumer.py`.

   Calls the user may veto:
   - **The name is `SurfaceInput`,** with `surfaceId` and `surface` (its name) as
     `SurfaceStatus` has both, and no `time`: nothing needed it, and `seq` orders them.
   - **`raw` and `value`:** `raw` is the number the message carried, `None` for OSC and the
     clock; `value` is what the bindings got (a note on 1, a note off 0).
   - **A note off keeps its own velocity** as `raw` (often 0 or 64), as a MIDI monitor shows it.
     So a pad pressed and let go shows one line with the release's velocity (`note 1 60  64`).
   - **`drives` is a tuple,** one `list bindings` text per binding, in show order, named from
     the show as it was when the input came (`master 'Grand Master'`, with `list bindings`'
     quotes, where F9's BINDINGS says `master gm`).
   - **After `stop()`, the inputs as they ended,** as `surfaces` keeps its status; `()` before
     `start()` and with `surfaces=False`.
2. **F9's MONITOR.** A panel between SURFACES and BINDINGS: the last 14 inputs, newest at the2. **F9's MONITOR.** A panel between SURFACES and BINDINGS: the last 14 inputs, newest at the
   bottom, each with its control, the value the device sent, what it drives and its surface
   (`cc 1 48  102  → fader 1  APC mini mk2`). Consecutive inputs from one control replace its line
   (spec §8.9), so a fader sweep is one line that moves. An unbound input reads `→ —`, dim. With no
   surface open the panel says `no surface is open: messages show here as they come in`. The
   bridge reads `inputs` at 10 Hz, only while F9 shows (as F8's `WATCH_DMX`), and on F9's first
   show takes the whole log.

   BINDINGS gets the raw value: a column `in` before `val`, the last value its control sent, or
   `—` before any. `val` stays the level of what it drives, so with soft pickup the two differ
   until the fader picks up.

   Verify: OSC messages on the real engine in a `tests/tui/test_tui_e2e.py` test; the merging, with
   two faders moved in turns; a pitch bend; F9 at 99 columns; F9's cost (F9 is not in the perf
   gate: add it, with an OSC sender running).

   **Done** (2026-11-18). `InputView` (with `sent`, the number, or an OSC value as `0.50`) and
   `InputsChanged`, a state event carrying busk's whole log; the part `"inputs"`, `View.inputs`,
   `Page.WATCH_INPUTS` (F9 only), `Bridge.watch(inputs=)`, `INPUTS_S` (10 Hz) and
   `input_views`, which keeps an input's view while busk keeps it. The page keeps its own lines
   (`merged`, `MONITOR_LINES`) and each control's last input (`last_sent`), taking the inputs past
   the newest it took, so a sweep longer than busk's 64 still leaves the other lines. MONITOR
   (`MonitorTable`, `monitor_cells`) sits under SURFACES in their column, BINDINGS beside them; below
   132 columns all three stack. BINDINGS has `in` before `val`. Tests: 6 in
   `tests/tui/test_tui_surfaces.py` (2 changed for `[learn]`), 2 in `tests/tui/test_tui_bridge.py`,
   and `test_f9_monitors_an_osc_surface_and_learns_from_it_on_the_real_engine`; F9 in the perf gate.

   Calls the user may veto:
   - **The page keeps MONITOR's lines,** not the bridge: busk keeps 64, the page its 14 merged
     ones, past F9's hiding. Inputs that come while another page shows are read when F9 shows
     again, as far as busk's 64 go.
   - **MONITOR goes under SURFACES** in the left column at 132 columns and more, so BINDINGS keeps
     its height; below, the three stack in that order.
   - **Columns:** `input`, `in`, `drives` (`→ fader 1, blackout` amber; `→ —` dim), `surface`,
     the surface going first when narrow. `in` shows an OSC or clock input's value (`0.50`,
     `1.00`), as it has no number of its own.
   - **The empty panel** says `messages show here as they come in` while a surface is open,
     with `no surface is open: ` before it while none is.
   - **`in` goes, when narrow, before `val`.**
3. **Learn mode,** as Q14 answers. Under (a): `[learn]` among the chosen surface's edits arms it,3. **Learn mode,** as Q14 answers. Under (a): `[learn]` among the chosen surface's edits arms it,
   lit amber. The next input from that surface puts `bind "APC mini mk2" cc 1 48 ` in the prompt,
   for the operator to finish with what it drives, and disarms. Esc or a second click disarms with
   nothing in the prompt. When the control already has a binding, the hint row says so (`cc 1 48
   drives fader 1: unbind it to replace it`), since `bind` adds beside the bindings already there.
   Nothing is sent until the operator sends the line.

   Verify: learn from an OSC input on the real engine, the line sent, the binding listed; an input
   already bound; Esc; a pitch bend, which `bind` cannot take, passed over.

   **Done** (2026-11-18), under Q14 (a), the recommended answer (the user's "use recommended
   answers"). `[learn]` is the last of the chosen surface's edits, a `StripButton` with an action,
   its label a span so lit and unlit compare different (`LEARN_LIT`, reversed amber). Armed, the
   first new input from the chosen surface that is not a `bend` or the `clock` posts
   `FillPrompt(commands.learned_prefill(surface, input), note)` and disarms. `FillPrompt` gained
   `note`: the shell shows it in the hint row while the prompt holds the pre-fill unchanged
   (`_fill_note`), since the prompt's change redraws the hint row. `Page.escape()` is a new hook,
   which the shell's Esc asks after the help and before the pane cursor and the prompt. Tests: 3 in
   `tests/tui/test_tui_surfaces.py`, the pre-fill in the contract test, and the real-engine test
   above.

   Calls the user may veto:
   - **The clock is passed over too,** not only a pitch bend: a device that sends clock would
     otherwise be learned at its next beat. `bind "<surface>" clock tap` is typed.
   - **Learn takes only inputs that came after `[learn]`,** as far as the bridge has read them:
     one that came in the 0.1 s before the click and was read after it counts.
   - **Choosing another surface, or another page, disarms it,** as Esc and a second click do.
   - **The hint row's note stays until the line changes;** a key typed brings busk's own hint
     back. It names every binding of the control (`cc 1 48 drives fader 2, blackout: unbind it to
     replace it`).

Docs: engine-gaps.md (GAP-13, with its **TUI since**), the TUI plan's §2.10 and §2.11 rows,
`docs/library.md`, the guide's F9 (its note that F9 has no monitor goes), the page's module
docs, and `CHANGELOG.md`.

**Done** (2026-11-18). engine-gaps.md: GAP-13's status, **TUI since** and **Done**, its Summary
row and the list of reads; the TUI plan's §2.10 rows (MONITOR, `val`, learn mode), §2.11's MIDI
input and adaptation 20; `docs/library.md` (section 3 and the reference);
`docs/dev/internals.md`; the guide's first note and its F9 (a new drawing, MONITOR, `in`, learn
mode); `docs/surfaces.md`'s MIDI section points to F9; the operations report's header and its
"Beyond this report"; the modules' docs; `CHANGELOG.md` under Added.

**Phase 37 checks** (2026-11-18), on top of `fbecf0d`. The whole suite: 7,094 passed and 1
skipped, in 10:07 with `uv run pytest -n 6`. `ruff check`, `ruff format --check`, `mypy src` and
`mypy --strict tests/api_consumer.py` clean. F9's, the bridge's, the contract, the frame's, the
prompt's, the hints' and the e2e tests pass on Textual 8.2.0: 607 tests. 31 mutations of the new
code, engine and TUI: all caught, once the note's test pressed Backspace back to the pre-fill (the
note had come back with the line). The perf gate: F9 with a sweep of 100 OSC messages a second
coming in, +0.18 to +0.20 core over a frontend that waits through the same sweep (F1 under it,
+0.21 to +0.22), no overrun. F1 A and C flapped around the 0.25 gate (+0.23 to +0.28); the same
runs of `fbecf0d`, without this phase, read the same, alternated with this phase's.

A real `busk run` under `busk-tui`, in a pty at 99 columns (pyte), `--state-dir` in the scratchpad:
OSC to a surface on localhost showed a sweep as one line (`osc "/fader/1"  0.80  → fader 1`) and an
unbound path as `→ —`; `[learn]` on Touch put `bind "Touch" osc "/fader/3" ` in the prompt, with
busk's completion hint under it. A virtual ALSA port (mido) as a MIDI surface: a CC with two
bindings (`cc 1 48  102  → fader 2, blackout`), a note on and off on one line (`64`, the off's
velocity), a pitch bend (`bend 1  4096`), and a program change that never showed; learn passed
the bend over, took the CC with the note `cc 1 48 drives fader 2, blackout: unbind it to replace
it` in the hint row, and `fader 3` sent from there was the third binding `list bindings` listed.
This host has a real nanoKONTROL2 plugged in; its faders were not moved.

### Phase 38: Engine: surfaces deleted, renamed and changed

The user's word of 2026-11-23: surfaces and bindings cannot be added, removed or edited from the
TUI. F9 shows them, and its edits put `bind`, `unbind`, `feedback` and `pickup` lines in the
prompt, but nothing on screen sets one up (the report's "Beyond this report"). Phases 38 to 41
give F9 those controls, the engine's lines first. For surfaces, busk lacks them. Checked on
`0c63290`, with `OfflineShow` on the club show:

- `delete surface "Phone"` and `rename surface "Phone" "Tablet"` are refused (`cannot delete
  'surface'`, `cannot rename 'surface'`);
- no line changes how busk finds a surface: `surface "Phone" port 8081` replies `expected
  pickup, got 'port'`;
- a `DELETE` of a surface that has bindings, through `submit()`, is refused by path, a line per
  binding (`bindings[0].surfaceId: Unknown surface 's-…'`); one with no bindings goes;
- nothing public lists the MIDI devices plugged in: `busk.io.midi.input_names()` is internal,
  and a failed surface's `detail` names the ports only once it has failed.

Engine only. Code: `src/busk/console/parser.py` (`_cmd_surface`, `_listening`, `surface`),
`src/busk/console/cascade.py`, `src/busk/console/console.py` (`confirmation`, `list surfaces`),
`src/busk/io/surfaces.py` (`SurfaceManager.reconcile`, `_unchanged`), `src/busk/io/midi.py`
(`input_names`), `src/busk/__init__.py`.

1. **GAP-60: `rename surface "<name>" "<new>"` and `delete surface "<name>" [cascade]`.**
   - A rename refuses a name another surface has, in any case, as `surface add` does. A line
     also finds a MIDI surface by its device (`surface()`), so a name that is another surface's
     device is refused too.
   - A delete of a surface with bindings is refused in one line that counts them (`surface
     "nanoKONTROL2" has 51 bindings: add cascade`). With `cascade` they go with it, after
     `confirmation()`'s question, in the words of the other cascades (`Delete surface
     "nanoKONTROL2"? It leaves 51 bindings.`). A surface with none goes with a plain `delete`,
     which asks nothing (§5, call 30).
   - A surface of any kind can go, `hid` and `internal` too, which busk shows as ignored.
   - Each is one undo step, with a reply in words. Tab offers `surface` after `delete` and
     `rename`, and the surfaces' names after it.
   - On a running show the surface closes at the manager's next reconcile, and `undo` opens it
     again. A renamed web remote keeps its server, as GAP-08 found.

   **Done** (2026-11-23). `_rename_surface` and `_delete_surface` in
   `src/busk/console/parser.py`, `surface_cascade` in `src/busk/console/cascade.py`, with the help
   lines and a paragraph in both modules' docs. The words are as this step has them: `renamed
   surface "Phone" to "Tablet"`, `surface "nanoKONTROL2" has 51 bindings: add cascade`, `Delete
   surface "nanoKONTROL2"? It leaves 51 bindings.`, `deleted surface "nanoKONTROL2": left 51
   bindings`. Tests: in `tests/test_surface_lines.py` (61 in all, with steps 2 and 3), and the
   `rename ` and `delete ` rows of `tests/test_console_prompt.py`.

   Calls the user may veto:
   - **A name that is another surface's device is not refused;** the lookup changed instead. A
     surface is found by its name first, and by a MIDI surface's device only when no surface has
     that name. Before, the first surface whose name or device matched won, which never differed
     while a MIDI surface was always named after its device. So a surface renamed `"Left"` is
     still `"nanoKONTROL2"` to a script that binds it by its device, until a surface takes that
     name, and then the name wins. Refusing the name as this step said would not have been
     enough: `surface add midi` of a device a renamed surface opens would have made the same
     clash.
   - **`delete surface … cascade` asks even with nothing to take** (`Delete surface "Phone"?`), as
     every cascade does (`delete master "FX" cascade` too). Phase 39's `[delete]` should send
     `cascade` only to a surface with bindings if it wants a surface without them to go unasked;
     its text says busk asks when bindings go.
   - **A rename or a pickup change reopens nothing on a running show,** found in the real `busk
     run` below: the surface manager and the feedback worker reopened a surface whose definition
     changed in any way, so renaming an OSC surface closed and reopened its socket, and a MIDI
     controller its ports, which drops what comes in meanwhile. Now a surface reopens only when
     its kind or its `match` changes (`same_device` in `src/busk/io/surfaces.py`, used by both);
     the web remote's rule is unchanged. Phase 39's pickup chips and `[rename…]` would have hit it
     at every click.
2. **GAP-61: `surface "<name>" change <what surface add takes after the kind>`.**
   - `surface "nanoKONTROL2" change "nanoKONTROL2 MIDI"`, `surface "Touch" change port 9001
     feedback 10.0.0.2:9001`, `surface "Phone" change port 8081 on 10.0.0.5`.
   - The surface keeps its kind, id, name, pickup and bindings (§5, call 31). Another kind is a
     delete and an add.
   - The line gives the whole of how busk finds the surface, as `route <id> change` gives the
     whole route (GAP-37): an option left out goes back to `surface add`'s default (port 8000 or
     8080, no feedback, no host).
   - It refuses what `surface add` refuses, by the same code (a port another surface of its kind
     listens on, its own excepted), and a line that changes nothing (`surface "Touch" already
     listens there`), which would be an undo step of no edit. A `hid` or `internal` surface is
     refused: busk opens neither.
   - On a running show the manager closes the old definition and opens the new one: it compares a
     surface by value, and restarts a web remote only when its port or host changes
     (`_unchanged`). A MIDI surface moved to a device that is not plugged in turns `failed` with
     busk's reason, and opens when the device comes.

   **Done** (2026-11-23). `_surface_change` in `src/busk/console/parser.py`, which shares
   `_device` and `_listening` (now with the surface's own id, whose port is free to it) with
   `surface add`, and `_new_surface_name` with it and the rename. One `SET` of the surface's
   `match`. The reply names what it is now, as `list surfaces` does: `changed surface "Touch":
   port 9001, feedback to 10.0.0.2:9001`, `changed surface "nanoKONTROL2": device "nanoKONTROL2
   MIDI"`. `surface "<name>" ` now offers `pickup` and `change`, and a wrong word after the name
   says `expected pickup or change`.

   Calls the user may veto:
   - **The refusal of a line that changes nothing** is `surface "Touch" is set up that way
     already`, one sentence for every kind, where this step had `already listens there`, which
     reads wrong for a MIDI device. Tab shows it before Enter: `surface "Phone" change ` on a web
     remote on 8080 with no host is not runnable, since the bare line would change nothing.
   - **A `hid` or `internal` surface** is refused as `surface "Keys" is a hid surface, which busk
     does not open`, the words of its `ignored` status (`hid surfaces are not implemented`) put
     as a reason.
   - **A MIDI device is any word or quote,** as `surface add midi` takes it, an empty `""` too,
     which opens nothing; the same code, so the same reading.
3. **GAP-62: the MIDI devices plugged in.**
   - A read for frontends, its name settled in the phase (`busk.midi_devices()`, say): the MIDI
     input devices the system offers now, once each, as `surface add midi` takes them: a port's
     name without ALSA's client and port numbers (`nanoKONTROL2:nanoKONTROL2 _ CTRL 20:0` reads
     `nanoKONTROL2`), with ALSA's own `Midi Through` left out (§5, call 33).
   - `()` without the `midi` extra or a MIDI backend, never an error: a form calls it.
   - Under `busk run` the frontend shares the console process, so it reads the console's host.
     Check it, as Phase 37 checked `inputs`. Measure a read: F9's form makes one as it opens.

   **Done** (2026-11-23). `busk.midi_devices() -> tuple[str, ...]`, in `src/busk/io/surfaces.py`
   with `device_names`, which gives the words; `busk.__all__` has 51 names. Without `mido` it
   returns `()` and does not import `busk.io.midi`; a backend that raises gives `()` too. Under
   `busk run` the probe frontend read it in the console process, with processes and with
   `--threads`, equal to the test's own read on the same host. A read costs about 20 ms here:
   rtmidi makes a client for each. Tests: in `tests/test_surface_lines.py`, one of them on a
   virtual ALSA port under the `midi` marker; `tests/test_public_api.py`, its golden (the one
   new entry) and `tests/api_consumer.py`.

   Calls the user may veto:
   - **A function of `busk`, not a property of a show:** the devices are the host's, and a form
     can ask before any show runs.
   - **The words:** a client with one port named after it, as a controller's is, reads as its
     name (`nanoKONTROL2`); any other ALSA port as its client and port, without the numbers. A
     virtual port that a program opens through rtmidi is `RtMidiOut Client:Phase38 Pad`, and the
     bare client name would have offered `RtMidiOut Client`, which any rtmidi program's port
     matches. A device with several ports gives each (`X-Touch:X-Touch MIDI 2`), so each opens
     its own. A name without a client, as macOS and Windows give them, comes whole. Two devices
     alike read once. In the system's order.
   - **Nothing polls it, and Tab does not offer it,** as §5's call 33 says.

   Add the entries of GAP-60 to GAP-62 and their Summary rows to engine-gaps.md, and update
   `docs/console.md` (the Surfaces row and the cascade table), `docs/surfaces.md`,
   `docs/library.md` (the read) and `busk help`.

   Verify: each kind renamed, changed and deleted, with bindings and without; the cascade, and
   `undo` bringing the surface back with its bindings; a rename to a name or a device in use; each
   refusal of `change`; Tab; on a running `LiveShow`, an OSC surface on localhost moved to another
   port (the old port stops listening, and a message on the new one reaches its bindings), a web
   remote renamed (it keeps its server) and moved (it restarts), and a surface deleted and brought
   back by `undo`; a virtual MIDI port (mido, as Phase 37 used one) for a MIDI surface's `change`
   and for the read; `busk run` with processes and with `--threads`.

Docs: as above, the parser's and the cascade's module docs, and `CHANGELOG.md`.

**Done** (2026-11-23). engine-gaps.md: GAP-60 to GAP-62, their Summary rows and the list of
reads; `docs/console.md` (the Surfaces row, the surfaces paragraph, a row of the cascade table);
`docs/surfaces.md` (a paragraph under the opening); `docs/library.md` (section 3, the reference
and the table of what raises); `docs/running.md`'s live edits; `busk help` and the modules' docs
(the parser, the cascade, `busk.io.surfaces`, `busk/__init__.py`); `CHANGELOG.md` under Added. The
operations report and the guide change with F9, in Phases 39 and 41.

**Phase 38 checks** (2026-11-23), on top of `0c63290`. The whole suite: 7,626 passed and 1
skipped, in 14:54 with `uv run pytest -n 6`. `ruff check`, `ruff format --check`, `mypy src` and
`mypy --strict tests/api_consumer.py` clean. The new test of the reopen fix fails with the old
comparison put back. No TUI code changed, so neither Textual 8.2.0 nor the perf gate was run.

A real `busk run club.show --state-dir …` with processes, lines piped to its prompt, the club
show with an OSC surface `Touch` on udp 19000 bound to fader 1 and its web remote moved to
127.0.0.1:18080: OSC on 19000 set playback 1 to 0.40; `surface "Touch" change port 19001`
replied `changed surface "Touch": port 19001, feedback to the sender`, `OSC …: listening on udp
19001` followed, a message to 19000 changed nothing, and one to 19001 set 0.60. `delete surface
"Touch"` was refused (`has 1 binding: add cascade`); `rename surface "Touch" "Desk"` renamed it,
and `list bindings` named `Desk`. That rename printed `listening on udp 19001` again: the socket
had been reopened, which led to the reopen fix in step 1's calls. With a virtual ALSA port open
(mido, `Phase38 Pad`), `busk.midi_devices()` gave `('RtMidiOut Client:Phase38 Pad',)`, and
`surface "nanoKONTROL2" change "RtMidiOut Client:Phase38 Pad"` opened it (`MIDI s-…:
RtMidiOut Client:Phase38 Pad 128:0`); closing the port printed `unplugged; waiting for it`.
`delete surface "Desk" cascade` (`left 1 binding`) and `undo` reopened it on 19001. The same run
with the fix: the rename printed nothing, and the rest read the same. The feedback port of the
virtual device was `not found`, rightly: a program's output port has no input for busk to send
to.

### Phase 39: F9: surfaces set up from controls

The user's word of 2026-11-23. Needs Phase 38. F9's SURFACES then adds, changes, renames and
deletes a surface, and sets its pickup in one click. TUI only. Code:
`src/busk_tui/pages/surfaces.py` (`_draw_surface_edits`), `src/busk_tui/bridge.py`
(`surface_views`, `_device_words`), `src/busk_tui/model.py` (`SurfaceView`),
`src/busk_tui/commands.py`, and a new form on the pattern of F8's route form
(`src/busk_tui/widgets/route_dialog.py`: `RouteDialog`, `PickRow`).

1. **A new surface.** `[+ surface…]` under SURFACES opens a form: the kind's chips (MIDI, OSC,
   web), then the kind's fields.
   - MIDI: the devices plugged in (GAP-62) as chips, dim where another surface finds the device
     already, or a name typed, so a controller can be set up before it is plugged in. It sends
     `surface add midi "nanoKONTROL2"`, which names the surface by its device (§5, call 32).
   - OSC: a name, the port (8000) and where feedback goes, empty for the sender (a host, a
     `host:port` or a `:port`): `surface add osc "Touch" port 9000 feedback 10.0.0.2:9001`.
   - Web: a name, the port (8080) and the address to listen on, empty for every interface:
     `surface add web "Phone" port 8080`.

   The line always carries the port, as F7's master form carries the tempo. The form checks what
   the show tells it, each in words under its field: an empty name, a name another surface has in
   any case, a port outside 1 to 65535 or one another surface of the kind listens on. What only
   busk can tell is refused in the log, as for every control.

   **Done** (2026-11-23). `SurfaceDialog` in the new `src/busk_tui/widgets/surface_dialog.py`, on
   the route form's pattern (`PickRow` for the kinds, `row`), with `DeviceChips` (a focusable
   `ButtonStrip`), `check_surface_name`, `check_device`, `check_port`, `check_feedback`,
   `finders` and `found_by`. The devices come through a new message, `ReadDevices`, which the
   shell answers on a worker thread from `Bridge.midi_devices()` (busk's `midi_devices()`), as
   it answers `ReadProfile`; `BridgeLike` and the tests' fake have the member. `SurfaceView`
   gained `midi`, `port`, `host` and `feedback_port`, and `where`, the feedback target or address
   as the line takes it. The builders: `surface_add_midi`, `surface_add`, `surface_change_midi`,
   `surface_change`, `surface_pickup`, `rename_surface`, `delete_surface`. The form says what is
   wrong in one red line under the fields, as the route and master forms do, the first problem
   from the top.

   Calls the user may veto:
   - **The devices are read on a worker thread as the form opens,** only when it opens on MIDI
     (a new surface, MIDI first, or a MIDI surface's `[edit…]`): the chips say `reading the
     devices plugged in…` for the 20 ms or so, and `no MIDI device is plugged in: type its name`
     when there is none.
   - **A chip puts its device in the field, and the field is what the line sends.** The chip of
     the device the field holds is lit; ← → on the chips step through them. The chips go above
     the field (`plugged in`, then `device`), whose placeholder says `click one above, or type
     its name`.
   - **`in use` is said in words, not only dim:** `[nanoKONTROL2 · in use]` where another MIDI
     surface's device is contained in the chip's name, busk's own rule for finding a port. With
     such a device in the field, a line under it names the surface (`surface "Left" finds it
     already`). The chip still works: busk opens one device for two surfaces.
   - **An empty device is refused,** though busk takes `surface add midi ""` and `change ""`,
     which open nothing: the one place the form refuses what busk takes, said in the agreement
     test.
   - **A new MIDI surface's form says `busk names it after its device: [rename…] renames it`**
     (§5, call 32).
   - **The port goes as busk stores it** (`08001` is sent `8001`), and a feedback target or an
     address as typed, bare or quoted by `commands.word`.
2. **The chosen surface's edits.** The strip under SURFACES (`edit "Touch"`) becomes:
   - `[soft]` `[jump]`, the pickup, its own lit, giving way to `[pickup…]`: a click sends
     `surface "Touch" pickup soft` (§5, call 34);
   - `[edit…]`: the form filled in, its kind fixed, which sends `surface "Touch" change …`, and
     nothing when nothing changed;
   - `[rename…]`: a `TextDialog` (`RENAME SURFACE`) that sends `rename surface "Touch" "Pad"`;
   - `[delete]`: `delete surface "Touch" cascade`, always, as F7's `[delete]` sends it, passing
     `RunLine.ask`, so busk asks when bindings go and names how many.

   `[bind…]` and `[learn]` stay until Phase 41. An ignored surface (`hid`, `internal`) has
   `[rename…]` and `[delete]` alone. A failed MIDI surface's `[edit…]` offers the devices plugged
   in, so a controller that came back under another name is a click away. `SurfaceView` carries
   the parts of the definition the form starts from (the device, the port, the host, the
   feedback's host and port), and the bridge reads GAP-62 for the form.

   Verify: each kind added, changed, renamed and deleted on the real engine in
   `tests/tui/test_tui_e2e.py`, and a delete with bindings asked and brought back by `undo`; an
   OSC surface moved to another port on a running show, turning green there; the form's checks
   agreeing with busk's refusals, as F7's tempo agreement test does; F9 at 99 columns; a real
   `busk run` under `busk-tui` with a virtual MIDI port among the device chips.

   **Done** (2026-11-23). `_draw_surface_edits` in `src/busk_tui/pages/surfaces.py` builds the
   strip: `[+ surface…]`, the chosen surface's name, its pickup through F3's `chips` (the lit one a
   note), `[edit…]`, `[rename…]` (`TextDialog`, `RENAME SURFACE`, `check_surface_name` with its
   own name free), `[delete]`, `[bind…]` and `[learn]`; `IGNORED` (`hid`, `internal`) leaves
   `[rename…]` and `[delete]`. `ask_add`, `ask_edit` and `ask_name` open the dialogs, and
   `_follow` chooses the surface a line named once busk took it. `commands.pickup_prefill` went
   with `[pickup…]`. `NO_SURFACES` reads `no surfaces · [+ surface…]`. Tests: 10 new and 2
   changed in `tests/tui/test_tui_surfaces.py`; in `tests/tui/test_tui_commands.py` 9 builders in
   the contract test, the lines doing what they say, and the form and busk agreeing on a port (16
   texts), a surface's own port, a feedback target (13) and a name (4); the new fields in
   `tests/tui/test_tui_conversion.py`; two tests on the real engine in `tests/tui/test_tui_e2e.py`,
   `test_f9_adds_moves_renames_and_deletes_an_osc_surface_on_the_real_engine` and
   `test_f9_adds_changes_and_deletes_a_midi_surface_and_a_web_remote_on_the_real_engine`.

   Calls the user may veto:
   - **`[+ surface…]` goes first in the strip, and the chosen surface's name after it** (`[+
     surface…] "Touch" [soft] [jump] [edit…] …`), as F8's strips have `[+ route…] U1 sACN 1
     [edit…] …`, where the strip had the label `edit "Touch"` on its left. One strip wraps
     between buttons: one line at 99 columns, two at 132 where SURFACES is a column; with the
     label beside it, the buttons would have had 30 cells there, and five lines.
   - **`[delete]` always sends `cascade`, and passes no `RunLine.ask`:** busk asks before every
     cascade, a surface without bindings too (`Delete surface "Phone"?`), so a TUI question would
     never show. Every surface deleted is asked about, as F7's masters are.
   - **The choice follows a rename, and goes to a new surface,** once busk has the line, as F8's
     `[number…]` follows a universe. A line busk refuses leaves the choice where it was.

Docs: the guide's F9, the TUI plan's §2.10 SURFACES row, the report's header and its "Beyond this
report", the page's module docs, and `CHANGELOG.md`.

**Done** (2026-11-23). The guide: its first note, F9's drawing, a list of SURFACES' strip, the
forms (`[+ surface…]` and a surface's `[edit…]`, chips reached by Tab) and the questions (F9's
`[delete]`); the TUI plan's §2.10 (a row for setting surfaces up, which the spec has not); the
report's header and its "Beyond this report"; `docs/surfaces.md`'s opening points to F9; the
modules' docs (the page, the form, `busk_tui.widgets.controls`); `CHANGELOG.md` under Added.

**Phase 39 checks** (2026-11-23), on top of `aa60229`. The whole suite with `uv run pytest -n
12`: 7,681 passed, 1 skipped and 1 failed in 7:47. The failure was
`test_a_drag_that_pauses_opens_a_new_undo_group_when_it_moves_on`, the pause-timer flake under
load, which passed 3 runs of 3 alone. A first run, before the last fixes, had the other two known
load flakes (the engine host's tick overrun and the F2 drag on the real engine), each 3 of 3
alone. `ruff check`, `ruff format --check` and `mypy src` clean. F9's, the bridge's, the
contract's, the conversion's, the frame's, the prompt's, the boundary's and the e2e tests pass on
Textual 8.2.0: 752 tests. 29 mutations of the new code: 26 caught at first. Of the other three,
the found note's display was untested (now tested), and the form's focus on the kind's chips and
`where`'s kind check were redundant (Textual focuses the first field; a web remote has no feedback
port) and went. The perf gate: F1 B and then F1 A read +0.251 and +0.254 against 0.25, F1 being
untouched, as in Phase 37. F9's run alone, with its sweep of 100 OSC messages a second, read
+0.166 to +0.179 core over three runs (Phase 37: +0.18 to +0.20), with no overrun.

The first e2e test raced under 12 workers: it sent to the old port before busk had closed it,
because an OSC surface that moves from open to open shows no change of state. It now sends there
only after the new port is heard, and it passed 6 runs of 6 under load, on both Textual versions.

A real `busk run` under `busk-tui`, in a pty at 99 columns (pyte), `--state-dir` in the
scratchpad, the club show with its web remote moved to `127.0.0.1:18080`, and a virtual ALSA
port open (mido, `Phase39 Pad`). F9's strip was one line. `[+ surface…]` offered `[RtMidiOut
Client:Phase39 Pad]`, the one device plugged in. A click put it in the field, and Enter sent
`surface add midi "RtMidiOut Client:Phase39 Pad"`, which opened green (`MIDI s-…: RtMidiOut
Client:Phase39 Pad 128:0`) and was chosen. Then, on that surface: `[soft]` sent `surface "…"
pickup soft`; `[rename…]` renamed it `Pad`, and the choice followed; `[edit…]` with `Other Pad`
typed turned it red with busk's reason (`'Other Pad' not found; available: …`); `[delete]` asked
`Delete surface "Pad"?`, `y` deleted it, and `undo` brought it back. The OSC form typed with the
keyboard (→ to OSC, Tab, the name, Tab, the port) sent `surface add osc "Touch" port 19000`. A
binding typed at the prompt took a message there to fader 1 (40%). `[edit…]` with port 19001 sent
`surface "Touch" change port 19001`, and busk printed `listening on udp 19001`. A message to 19001
showed in MONITOR (`osc "/fader/1"  0.70  → fader 1`), and one sent to 19000 never did.

The driver first typed the OSC form too fast: a key it sent a few milliseconds after Tab landed in
the field Tab was leaving (`"Touch1" port 9000`). Textual hands a key to the focused field before
Tab's binding moves the focus. Paced at 0.3 s, as a person types, every key landed where it
should. The headless tests, which wait between keys, never see it.

### Phase 40: Engine: one binding at a time

The user's word of 2026-11-23, with Phase 38. A binding has an id but no number or name, and the
lines that remove or change bindings name a control: `unbind "<s>" <input>` and `feedback "<s>"
<input> …` take every binding on it. Checked on `0c63290`, with `OfflineShow` on the club show:

- one of two bindings on a control (`cc 1 48` driving `button 1 2` and `blackout`) cannot go
  alone;
- `unbind "nanoKONTROL2" clock` is refused (`expected cc or note or osc, got 'clock'`), though
  `bind` takes `clock`, so a clock's binding goes only with its surface (Phase 38);
- a pitch bend's or a hardware control's binding, which a show file can hold and no line makes,
  cannot go at all;
- nothing changes a binding in place. Another target, another control or another feedback
  address is `unbind` then `bind`: two undo steps, and the control's other bindings go too. Q14
  left a binding row's learn mode, which moves a binding to another control, waiting on such a
  line.

Engine only. Q15 settles the line's words. Code: `src/busk/console/parser.py` (`_cmd_bind`,
`address`, `_what`, `_cmd_feedback`, `_cmd_unbind`, `bound`), `src/busk/console/console.py`
(`list bindings`), `src/busk/model/validate.py` (`_check_bindings`, `_binding_surface`),
`src/busk/io/bindings.py`, `src/busk/compiler/compile.py` (soft pickup, kept by binding id).

1. **GAP-63: a binding by its id,** as Q15 answers. Under (a):
   - `delete binding <id>` takes one binding, whatever its control. It asks nothing, as a plain
     `delete` does, and `undo` brings it back.
   - `binding <id> change <what bind takes after the surface>`, as in `binding b-40d1 change cc 1
     49 button 2 2 led`. The binding keeps its id and its surface; its control, what it drives
     and its feedback are the line's, so a feedback left out goes, as `route <id> change`
     replaces a route whole. A clock's binding takes `clock tap ["<master>"]`.
   - It refuses what `bind` refuses, by the same code, and a line that changes nothing.
   - Tab offers the ids after `binding` and `delete binding`, as it does after `route`. `list
     bindings` prints them already.
   - `unbind "<s>" clock` takes the clock's bindings, as `bind` takes `clock`.
   - On a running show the resolver follows the compiled show. Check that a soft-pickup fader
     moved to another slot picks the level up again rather than jumping to it, since the compiler
     keeps soft pickup by binding id, and that feedback moves to the new address and stops on the
     old one.

   Under (b), the same edits, worded `unbind "<s>" <input> <what>` and `rebind "<s>" <input>
   <what> to <input> <what> [led|motor|display [<input>]]`.

   Add GAP-63's entry and its Summary row to engine-gaps.md, and update `docs/console.md` (the
   Bindings row), `docs/surfaces.md` and `busk help`.

   **Done** (2026-11-23), under Q15 (a), the user's "use recommended answer to questions".
   `_cmd_binding`, `_delete_binding` and `_binding_by_id` in `src/busk/console/parser.py`, and
   `_binding`, what `bind` takes after the surface, which `bind` and `change` share. `_input`,
   `_action` and `_binding_names` moved there from `busk.console.console`, with a new
   `_binding_text`, so a reply words a binding as `list bindings` does; `_address_text` went
   for `_input`, which also words a clock. The words: `deleted binding b-40d1: cc 1 48 →
   blackout`, `changed binding b-40d1: cc 1 49 → button 2 2 [led]`, `binding b-40d1 is set up
   that way already`, `no binding b-nope`. `unbind "<s>" clock` reads `clock`, with no `thru`
   after it. The help lines and two paragraphs of the parser's module docs. Tests: in the new
   `tests/test_binding_lines.py` (62 in all, with step 2), two in `tests/test_pickup.py`, and
   rows in `tests/test_console_prompt.py`.

   Calls the user may veto:
   - **A `change` sets each part that differs** (`input`, `action`, `feedback`) and deletes a
     feedback left out, as `route <id> change` does, so the binding keeps its place in the list
     and `list bindings` its order.
   - **The replies name the binding, then what it is now or was,** as `list bindings` prints it
     after the surface, where `delete route` says only `deleted route r-1`: a binding's id says
     nothing to a reader.
   - **A binding on a web remote or a `hid` surface, from a show file, is deleted but not
     changed:** `change` refuses as `bind` does there, since no control on it is one busk reads.
   - **A soft-pickup fader moved to another control now picks the level up again,** found by the
     live test this step asked for: soft takeover is kept by binding id, so the moved binding was
     still attached to its fader and the new fader, wherever it stood, jumped the level at its
     first move (62.5% to 25% in the test). The engine's swap now forgets the takeover state of
     a binding whose input changed (`Pickup.forget` in `src/busk/engine/surfaces.py`, called
     from `_swap` in `src/busk/engine/loop.py`). A binding moved to another slot on the same
     control keeps its position, which is the hardware's, and picks the new slot's level up as
     before. The test fails with the call taken out.
   - **The old feedback address keeps the last value it was sent,** as after `unbind`: an LED
     the binding lit stays lit until something else sends there. Darkening it would mean
     sending a value nothing asked for, a motor fader's to 0 among them.
2. **What `bind` takes and should not,** found while planning (2026-11-23). Bugs, with no
   number:
   - a MIDI channel outside 1 to 16 and a CC or note number above 127 go through in silence
     (`bind "nanoKONTROL2" note 0 128 fader 1`, `cc 17 0`), and the binding never fires;
   - a control the surface's kind cannot send (`osc` on a MIDI surface, `cc` on an OSC one, any
     control on the web remote) goes through with a warning by path and by the surface's id:
     `warning bindings[52].input: midi surface 's-e2c28b90d767' cannot send osc inputs; this
     binding does nothing`;
   - `display` feedback on a MIDI control goes through in silence, though MIDI has no display
     (`busk.io.midi`'s feedback table).

   Each is refused in one line, in words, by `bind` and by GAP-63's `change`; the ranges by
   `feedback` and `unbind` too (§5, call 36). A show file that holds one still loads, with the
   validator's warning.

   **Done** (2026-11-23). `address` in `src/busk/console/parser.py` takes the controls a
   surface sends (`_CONTROLS`: `cc`, `note` and `clock` on MIDI, `osc` on OSC; `_sends` names
   the surface) and reads a channel and a number through `within`; Tab offers the surface's
   controls and feedback alone. The words, each `expected …, got …` as the parser's other
   refusals: `expected a MIDI channel (1–16), got '17'`, `expected a CC number (0–127), got
   '128'` (`a note number` after `note`, `… after thru` for `thru`'s end), `surface "Pad" is a
   MIDI surface: expected cc, note or clock, got 'osc'`, `surface "Touch" is an OSC surface:
   expected osc, got 'cc'`, `surface "Pad" is a MIDI surface: expected led or motor, got
   'display'` (`led, motor or none` from `feedback`), and `surface "Phone" is a web remote,
   which sends commands of its own: it takes no binding`. The validator (`_binding_surface`,
   `_midi_numbers` in `src/busk/model/validate.py`) now warns of the ranges and of `display`
   on MIDI, as it warned of the kinds: `bindings[3].input.channel: A MIDI channel is from 1 to
   16, got 17; this binding does nothing`, `… .feedback.kind: MIDI surface 's-…' has no
   display; this feedback is not sent`.

   Calls the user may veto:
   - **A binding on a `hid` or `internal` surface is refused too,** in the words of `surface
     … change` (`surface "Keys" is a hid surface, which busk does not open`): its controls are
     hardware ones no line makes.
   - **`feedback … display` on MIDI is refused,** which the step listed for `bind` and
     `change` alone: it makes the same binding.
   - **`unbind` and `feedback` refuse the ranges but not the kinds,** so a show file's `cc` on an
     OSC surface can still be unbound by its control; `delete binding` takes any of them.
   - **The validator warns of the ranges and of `display`,** where it was silent, so "still
     loads, with the validator's warning" holds for each: the feedback address's ranges too
     (`this feedback is not sent`).

   Verify: one of two bindings on a control deleted, and changed; a clock's binding changed and
   deleted; a pitch bend's binding from a show file deleted; each refusal, with Tab and `?`;
   `undo`; on a running `LiveShow` with an OSC surface on localhost, a binding moved to another
   path driving from it and no longer from the old one, a soft-pickup fader moved to another slot,
   and feedback moved; `busk run` with processes.

Docs: as above, the parser's module docs, and `CHANGELOG.md`.

**Done** (2026-11-23). engine-gaps.md: GAP-63 and its Summary row; `docs/console.md` (the
Bindings row, the surfaces paragraph, the line on `unbind`); `docs/surfaces.md` (a paragraph
under the opening, and a sentence under Feedback); `busk help` and the parser's module docs (the
grammar, two paragraphs); the modules' docs of `Pickup` and the engine's swap; `CHANGELOG.md`,
under Added (the lines) and Fixed (what `bind` took). The guide and the operations report change
with F9, in Phase 41.

**Phase 40 checks** (2026-11-23), on top of `afdefef`. The whole suite with `uv run pytest -n
12`: 7,755 passed and 1 skipped, in 8:23. A first run had 6 failures, each a row with the old
words: three rows of `tests/test_console_prompt.py` (`delete ` now offers `binding`, a MIDI
binding's feedback no longer offers `display`, its address no longer `osc`), one error row of
`tests/test_console_parser.py` (`expected a CC number (0–127)`), and two tests of
`tests/tui/test_tui_conversion.py`, whose rig bound an OSC control with LED feedback on `note 1
40`, a control an OSC surface does not send; it now sends it to `osc "/1/led1"`, and the TUI
words it as before. `ruff check`, `ruff format --check` and `mypy src` clean. 19 mutations of the
new code, all caught. No TUI code changed, so neither Textual 8.2.0 nor the perf gate was run.

A real `busk run club.show --state-dir …` with processes, lines piped to its prompt, the club
show with its web remote moved to `127.0.0.1:18080` and an OSC surface `Touch` on udp 19100,
soft pickup, with two bindings on `/fader/1`: fader 1 and a momentary blackout. `/fader/1` at
0.75 set playback 1 to 0.75 and held the blackout. `delete binding` of the blackout's replied
`deleted binding b-…: osc "/fader/1" → blackout momentary`, and 0.75 then moved the fader alone.
`binding b-… change osc "/fader/2" fader 1` replied `changed binding b-…: osc "/fader/2" → fader
1`; `/fader/2` at 0 and at 0.5 changed nothing (soft pickup, the level at 0.75), at 1.0 it crossed
and took the level, and `/fader/1` then did nothing. `list bindings` showed the one binding on
`/fader/2`, and two `undo`s brought both back on `/fader/1`.

### Phase 41: F9: bindings set up from controls

The user's word of 2026-11-23. Needs Phases 39 and 40. F9's BINDINGS then adds, changes, moves
and deletes a binding from a form, and none of F9's edits needs the prompt. TUI only. Code:
`src/busk_tui/pages/surfaces.py` (`_draw_binding_edits`, `toggle_learn`, `_take_inputs`),
`src/busk_tui/bridge.py` (`binding_info`, `_input_words`, `_action_words`),
`src/busk_tui/model.py` (`BindingInfo`), `src/busk_tui/commands.py`, and a new form.

1. **The binding form.** `[+ binding…]` among the chosen surface's edits, giving way to
   `[bind…]`, opens a form in three parts:
   - **the control**, by the surface's kind: on MIDI the chips `cc`, `note` and `clock`, a
     channel (1 to 16) and a number (0 to 127); on OSC a path (`/fader/1`). `[learn]` in the form
     fills them from the next input that comes from the surface, passing a pitch bend and the
     clock over, as F9's `[learn]` does;
   - **what it drives**: the chips `fader`, `button`, `master`, `tap`, `blackout`, `page`,
     `release all` and `output`, then each one's fields: a slot or a playback (`fader playback
     18`); a slot and a button; `gm` or a master, as chips by name; the speed master, when the
     show has more than one; `momentary`; `+N`, `-N` or a page; a release time; on or off. A
     clock offers `tap` alone;
   - **feedback**: `none`, `led`, `motor` and, on OSC, `display`, on the control itself or on
     another, given as the control is.

   It sends one `bind` line, and checks what it can first (the ranges, an empty path, a slot from
   1); busk refuses the rest, in the log. On a web remote or an ignored surface `[+ binding…]` is
   grey, and the hint row says why (`a web remote sends commands of its own: a binding on it does
   nothing`).

   **Done** (2026-11-24), under Q15 (a), the user's "use recommended answer to questions".
   `BindingDialog` in the new `src/busk_tui/widgets/binding_dialog.py`, on the route and surface
   forms' pattern (`PickRow` for every row of chips, `row`), with the checks `check_channel`,
   `check_number`, `check_path`, `check_slot`, `check_button`, `check_playback`, `check_page`
   and `check_release` (`within`, `read_int`), and the words `what_words`, `feedback_words`,
   `binding_words` and `page_words`; `control_parts` reads a control as busk words it, and
   `unworded` says why the form cannot word a binding. `[+ binding…]` replaced `[bind…]` in
   SURFACES' strip (`ask_bind`); the form's line runs as it closes (`_open_form`). The builders:
   `commands.control`, `bind`, `binding_change` and `delete_binding`; `bind_prefill`,
   `unbind_prefill` and `feedback_prefill` went with their buttons. `StripButton` gained `hint`,
   which `ButtonStrip` shows in the hint row while the mouse is on the button, a grey one too.

   Calls the user may veto:
   - **The form's `[learn]` hears through the page.** F9 stays the current page under a modal,
     so the bridge still reads `inputs` and the page's `update_view` still runs; the page hands
     the form the first input learn takes (`learnable`, which the surface's learn uses too). The
     check the step asked for holds headless, on the real engine and in a real `busk-tui`. One
     learn mode is armed at a time: opening the form disarms the surface's and a binding's.
   - **No chip that can only be refused:** no `clock` and no `tap` without a speed master, no
     `master` without a master, as F7's form has no `group` without a group. A clock only taps,
     so its drives row says `tap: a clock taps the tempo` and has no chips.
   - **The checks read numbers as busk does** (Python's `int`), so `+3` and `1_0` pass as a
     channel because busk takes them; the agreement tests (80 texts over the eight checks) say
     so. **The line carries them as busk stores them:** `07` goes as `7`, a page step `+01` as
     `+1`, a release time `2.50` as `2.5` (`commands.exact`), so a form left as it was makes
     the same line and sends nothing.
   - **A playback or a page the show has not is busk's to refuse** (`no playback 99`), as the
     step says, though the show model has them.
   - **Blackout is two chips, `toggle` and `momentary`:** busk's `blackout` toggles on a press.
   - **A clock's feedback lights another control,** always: it has no address of its own, so
     the `on` chips do not show for a clock.
   - **The form's `[learn]` is a click:** Tab reaches the chips and the fields, not it.
   - **The edit form's title names the binding by its control** (`EDIT BINDING cc 1 23 ·
     "nanoKONTROL2"`), not by its id.
   - **A web remote has no `[learn]` either,** which Phase 39 left there: it sends no input, so
     learn mode never fired on it.
2. **A binding's edits.** The strip under BINDINGS (`edit cc 1 32 on "nanoKONTROL2"`) becomes:
   - `[edit…]`: the form filled in, which sends `binding <id> change …` (Q15), and nothing when
     nothing changed;
   - `[learn]`: moves the binding to the next control that comes from its surface, what it drives
     and its feedback kept, in one line. This is the spec's learn mode on a binding row, which
     Q14 left for a gap. It arms, lights and disarms as the surface's `[learn]` does;
   - `[delete]`: `delete binding <id>`, passing `RunLine.ask`.

   `[unbind…]` and `[feedback…]` give way to these; `unbind … thru` and `feedback … thru` stay
   typed (§5, call 35). A binding the form cannot word (a pitch bend's, a hardware control's, a
   command other than `release all` and `output`, each from a show file) has `[delete]` alone,
   its `[edit…]` and `[learn]` grey with the reason in the hint row. `BindingInfo` gains its id
   and the parts the form starts from.

   The bridge reads `inputs` only while F9 shows (`Page.WATCH_INPUTS`), and F9's `on_hide`
   disarms learn mode: check that the form's `[learn]` still hears, with the form a modal screen
   over F9.

   Verify: each kind of target added and changed on the real engine; the form's `[learn]` from an
   OSC input, and a row's `[learn]` moving a binding, on the real engine; one of two bindings on a
   control deleted; a clock's binding changed and deleted; the form's checks agreeing with busk's
   refusals; F9 at 99 columns; a real `busk run` under `busk-tui` with a virtual MIDI port.

   **Done** (2026-11-24). `_draw_binding_edits` in `src/busk_tui/pages/surfaces.py` builds
   `[edit…]` (`ask_edit_binding`), `[learn]` (`toggle_move`, `moving`) and `[delete]`
   (`ask_delete_binding`), or `[edit…]` and `[learn]` grey with `unworded`'s reason as their
   hint. `BindingInfo` gained `id`, `action`, `values`, `feedback_kind` and `feedback_to`, which
   the bridge fills (`_action_fields`). Armed, a binding's `[learn]` sends `binding <id> change`
   with the first control from its surface that is not its own, a bend or the clock
   (`binding_words` with `to`). `escape`, `on_hide`, `choose_binding` and the surface's
   `[learn]` disarm it. The choice follows a binding by its id when the show changes.
   `NO_BINDINGS` reads `no bindings · a surface's [+ binding…] adds one`. Tests: 12 new and 3
   changed in `tests/tui/test_tui_surfaces.py`; in `tests/tui/test_tui_commands.py` 3 builders
   in the contract test, every club binding's words refused by busk as `set up that way already`
   and moved to another control keeping what it drives, the lines doing what they say, and the
   form and busk agreeing on a channel, a number, a path, a slot, a button, a playback, a page
   and a release time; the new fields and a show file's command and pitch bend in
   `tests/tui/test_tui_conversion.py`; two tests on the real engine in
   `tests/tui/test_tui_e2e.py`,
   `test_f9_binds_learns_moves_and_deletes_a_binding_on_the_real_engine` and
   `test_f9_binds_and_changes_each_kind_of_target_and_a_clock_on_the_real_engine`.

   Calls the user may veto:
   - **A binding's `[learn]` passes over its own control** too: a move there would change
     nothing, which busk refuses, and a hand still on the fader would disarm it.
   - **The move keeps what it drives and its feedback:** a feedback on its own control follows
     it to the new control; one on another control stays there.
   - **`[delete]` asks the TUI's question, naming the binding as BINDINGS shows it**
     (`Delete binding cc 1 23 → master gm on "nanoKONTROL2"?`), since busk asks none. A deleted
     binding leaves no choice, and `undo` does not choose it again.
   - **What the form cannot word,** each from a show file: a binding on a web remote or on a
     surface busk does not open, a control its surface does not send (a pitch bend, a hardware
     control, `osc` on MIDI), a command but `release all` and `output`, a feedback its surface
     has not (`display` on MIDI), or on such a control. The step listed the first three.
   - **The label stays on the left of BINDINGS' strip** (`edit cc 1 32 on "nanoKONTROL2"`), as
     the step drew it: unlike SURFACES', the strip fits beside it at 99 columns.

Docs: the guide's F9 and its first note (F9 no longer puts a binding's line in the prompt, but for
the surface's learn mode), the TUI plan's §2.10 rows (BINDINGS, learn mode), the report's header
and its "Beyond this report", the page's module docs, and `CHANGELOG.md`.

**Done** (2026-11-24). The guide: its first note, F9's drawing, SURFACES' `[+ binding…]`, the
BINDINGS strip, what the form cannot word, learn mode (one armed at a time), the questions (F9's
`[delete]` of a binding) and the forms; the TUI plan's §2.10 (a row for setting bindings up,
learn mode on a binding row); the report's header and its "Beyond this report"; GAP-63's **TUI
since**; `docs/surfaces.md` (two sentences point to F9's form); the modules' docs (the page, the
form, `StripButton`); `CHANGELOG.md` under Added.

**Phase 41 checks** (2026-11-24), on top of `6542d99`. The whole suite with `uv run pytest -n
12`: 7,855 passed and 1 skipped, in 8:30. `ruff check`, `ruff format --check` and `mypy src`
clean. F9's, the contract's, the conversion's, the widgets', the hints', the prompt's, the
boundary's, the frame's and the bridge's tests pass on Textual 8.2.0 (852), and so do F9's five
real-engine tests. 38 mutations of the new code: 36 caught at first. The other two were real
gaps in the tests, now tested: a binding's `[learn]` left armed when its binding goes, which
would spend the next Esc, and the binding strip redrawn when the surfaces come after the show.
Every club binding round-trips: `binding <id> change` with the words the form starts from is
refused as `set up that way already`. The perf gate: 9 passed; F9 with a sweep of 100 OSC
messages a second read +0.159 core (Phase 39: +0.166 to +0.179), with no overrun.

A real `busk-tui club.show --state-dir …` under `busk run`, in a pty at 99 columns (pyte), the
club show without its nanoKONTROL2 (not plugged in), its web remote on `127.0.0.1:18080`, a
virtual ALSA port (mido, `Phase41 Pad`) as a MIDI surface and an OSC surface on udp 19200.
`[+ binding…]` on the pad, the form's `[learn]` armed (`move a control on "RtMidiOut
Client:Phase41 Pad"…`), and a CC 21 from the port filled it (`learned cc 1 21`) with the form
open over F9; `[led]` and Enter sent `bind "RtMidiOut Client:Phase41 Pad" cc 1 21 fader 1 led`,
and CC 21 at 100 then read `→ fader 1` in MONITOR and 79% in BINDINGS. The binding's `[learn]`
passed CC 21 over and took CC 22: `binding b-… change cc 1 22 fader 1 led` (`changed binding
b-…: cc 1 22 → fader 1 [led]`), the choice staying on it. `[edit…]` with `[master]` sent `binding
b-… change cc 1 22 master gm led`; `[delete]` asked `Delete binding cc 1 22 → master gm on
"RtMidiOut Client:Phase41 Pad"?`, `y` deleted it, and `undo` brought it back. On the OSC
surface, `/fader/9` typed in the form sent `bind "Touch" osc "/fader/9" fader 1`, and a message
there read `→ fader 1` and 50%. busk warned that the pad's feedback port was `not found`,
rightly: a program's virtual output has no input for busk to send to (as in Phase 38).

## 7. Seen, and not in the sources

Left out because the five places do not name them. Say if any should join a phase.

On 2026-11-11 the user put them into phases: the simple bugs in Phase 18, the replies with a path
in Phase 19, and the items worth building in Phases 20 to 23. Each item below names its phase.
Those marked **Not planned** are extras or matter less, and stay here.

- GAP-06 (one undo step for a gesture): **Phase 20**. Done there: `undo group "<label>"`, `undo
  group end`, and F2's drag as one step. GAP-13 (control input monitor): **Not planned**. `bind`
  lines can be typed. On 2026-11-18 the user gave it **Phase 37**: F9's MONITOR, the raw value
  and learn mode. Done there: `LiveShow.inputs`, MONITOR, BINDINGS' `in` and `[learn]`.
- A cue's move, copy and renumber past its neighbours (the report's Cues table): **Phase 22**,
  steps 1 to 3. Done there: GAP-43, F4's `[number…]` and `[copy…]`.
- Renumbering a cue list from F4 (the report's Cue lists table): **Phase 22**, step 3. Done
  there: the list's `[number…]`.
- F4's table shows only intensity and colour entries: **Phase 23**, Q7. Done there: the `also`
  column.
- Options when adding an effect from a template click: **Not planned**. F5's EFFECT panel changes
  them afterwards. Since Phase 33, `[keep as defaults]` makes the next click add them.
- Deleting several presets, cues or lists in one line: **Not planned**. Fixtures take `thru`.
- `route add 1 artnet 200.0.0` still prints a path (net above 127, sub-net or universe above 15),
  like the sACN universe Phase 1 fixed. Phase 1 named only sACN. Found on 2026-11-08. **Phase
  18**, step 1. Fixed there.
- Some replies still print a path, and F4's controls now put them in the log: `delete cue L/C`
  (`deleted cueLists[8].cues[1]`), `cue L/C release`, `cuelist N tracking`, `rename cuelist` and
  `cuelist N chase`. The refusals are in words; these are the answers to lines that worked. Found on
  2026-11-09. **Phase 19**. Fixed there.
- `cue L/C effect <id> <prop> <value>` replies with a path too, and F5's EFFECT panel now puts that
  in the log. Found on 2026-11-09. **Phase 19**. Fixed there.
- `playback N <prop> <value>` replies with a path too, and F1's PLAYBACK panel now puts that in the
  log. `go` on a playback whose `gotoCue` its list lacks, after a change of list, was not checked.
  Found on 2026-11-09. Checked in Phase 16, on `LiveShow`: `go` runs the new list, and the `goto`
  button does nothing and says nothing. busk warns once, at the change. F1 greys `[GT]` only when
  there is no `gotoCue`, so it stays live on one the list lacks: **Phase 17**, step 2. Fixed
  there: `[GT]` is grey, and the hint row says why. The reply with a path: **Phase 19**. Fixed
  there.
- `rename page N "…"` replies with a path too (`set pages[2].name to "Finale"`), and F1's page
  `[rename…]` now puts that in the log. Found on 2026-11-10. **Phase 19**. Fixed there.
- With `--faders` below a page's slot count, ← → and the selection that follows a change of slots
  use only the first `faders` slots, in edit mode too, where the grid has them all: a change of those
  slots moves a selection past them to the first. Found on 2026-11-10. **Phase 18**, step 6.
  Fixed there.
- `rename group N "…"` and `group N number M` reply with a path too (`set groups[4].name to "V"`),
  and F3's GROUPS now puts that in the log. So does a plain `delete group N` (`deleted
  groups[4]`), which F3 does not send. Found on 2026-11-10. **Phase 19**. Fixed there.
- `cue L/C time …`, `cue L/C follow|wait <d>` and `rename cue L/C "…"` reply with a path too (`set
  cueLists[8].cues[2].timing.fadeIn to 2; …`), and F4's dialogs now put that in the log. Found on
  2026-11-10. **Phase 19**. Fixed there.
- No line removes a family's own timing from a cue (`perFamily`), nor a family's own curve but by
  setting the family again without one. busk reads a family's fade, a trigger's delay and a Bézier
  point as any number (`50%`, `-0`), and the cue's own times as plain seconds. Found on 2026-11-10.
  On 2026-11-11, also: a value busk then rejects is refused by path, not in words (`cue 9/2 time
  intensity -1`, `cue 9/3 follow -1`, a Bézier point of `-0.5`). The reading: **Phase 18**, step
  2. Fixed there, with every other seconds read of the parser (`fade -1` was taken). Removing a
  family's timing: **Phase 21**. Done there: `cue L/C time <family> none` (GAP-42) and TIME's
  `[none]`. Sending the family again without a curve still removes its curve (§5, call 14).
- `commands.effect_stop`, `effect_run` and `effect_remove` do not quote an id, so those controls
  fail on an effect id of two words, which only `id "my fx"` makes. `_rate_text` in the bridge does
  not escape a quote in a master's name. Found on 2026-11-09. Phase 16 found that a control sends
  it: F4's toggle back to a chase restates `CueListInfo.chase`, `_chase_text`'s words, through
  `commands.cuelist_chase`. So the toggle fails on such a master (`no speed master 'Say '`), and
  writes the rate with `:g` (`hz 1.23456789` as `hz 1.23457`) and the crossfade with
  `commands.number` (`0.125` as `0.12`). `[chase…]`'s form keeps every digit and quotes the name,
  so the fix is to build the toggle's line from `CueListInfo.rate` as the form does: **Phase 17**,
  step 1. Fixed there: `_rate_text`'s and `_chase_text`'s words are now only shown (F4's meta
  line, F1's strips, F5's rate cells), so their quote and `:g` send nothing. The effect ids stay
  open: **Phase 18**, step 4. Fixed there.
- `commands.flash`, `undo` and `redo` have no caller. `flash` lost its own when Phase 9's strips
  began sending `button N B`; `undo` and `redo` never had one, since `undo` is typed. The contract
  test still runs all three. Found on 2026-11-11. **Not planned**: dead code, left until the user
  says to remove it or to give `undo` and `redo` a key. On 2026-11-17 (Phase 20) the user asked
  for the keys: Ctrl+Z sends `undo` and Ctrl+Y `redo`. `flash` had no caller: F1's `[FL]` is the
  playback's own flash button, a `HeldButton` that sends `button N B on|off`, and Q3 (a) leaves no
  control a flash of its own. At the user's word the builder and its contract rows are removed;
  busk's `flash N on|off` line stays, for the prompt and bindings.
- F6's other drags still send a programmer step per line: the colour picker's field (`set color
  …`) and a spread row's two bars (`set … spread …`), each about ten a second. `undo group` would
  make each one step, as F2's encoder drag is since Phase 20. Found on 2026-11-17. Not in a phase.
- Every rename, every `number M`, `fixture N location {…}`, a plain `delete` of something unused
  and `cuelist N sequence` reply with a path too: the report's side findings list them all. Found
  on 2026-11-11. **Phase 19**. Fixed there.
- F6's `[replace]` and `[remove]` send `record preset … replace|remove` and ask nothing, where
  F4's and F3's ask first, as §1's rule says. The presets plan built them before the rule, and
  Phase 6 brought only F6's `[delete]` under it. Found on 2026-11-11. **Phase 17**, step 3. Fixed
  there: both ask first.
- `fixture N mode <the mode it runs>` goes through and spends an undo step that changes nothing.
  F3's lit chip sends nothing, so only the prompt meets it. Found on 2026-11-11. **Phase 18**,
  step 3. Fixed there, for a profile line that changes nothing too.
- On a show with several speed masters, F4's toggle on a list that was never a chase sends
  `cuelist N chase bpm x 1`, and busk refuses it (`several speed masters: name one`); the list
  stays a sequence, and `[chase…]` names the master. Phase 17 kept that line, as its step 1 said.
  Naming the show's first speed master would make the toggle work, but it picks one for the
  operator. Found on 2026-11-11. **Not planned**: the refusal is in words, and `[chase…]` works.
  If it comes back, the toggle could open `[chase…]` there in place of sending.
- `[chase…]`'s form starts its crossfade field with `:g` (`ChaseDialog`, `f"{crossfade:g}"`), so
  a crossfade of `0.1234567` goes back as `0.123457` if the operator takes the form as it opened.
  Its rate and multiplier start through `commands.exact`. Found on 2026-11-11. **Phase 18**, step
  5. Fixed there.
- `fixture N mode <mode>` and `fixture N profile "<profile>" mode <mode>` are refused by document
  path when a group, a cue or a parked value names an element the new mode lacks, as GAP-26 left it
  to the validator: on the club show, `fixture 301 profile "Generic Spot 16ch" mode 16ch` replies
  `error: fixture 301 runs Generic Spot 16ch, 16ch: rejected, the show would not be valid` and 22
  lines of `groups[2].members[1].element: Fixture 'fx-…' has 1 element(s); element 1 does not
  exist`. F3's `[profile…]` would put them in the log. The first line is in words. Found on
  2026-11-11, in Phase 19. **Phase 24** (the user's word, 2026-11-11). Fixed there, for `profile
  update` too: one line names what uses the elements.
- F4 shows a cue's entries, but none is edited one by one: a cue's values change only by
  re-recording from the programmer, and no line loads a cue into the programmer to edit it. The
  user's question, 2026-11-11, after Phase 22. **Phase 25** (the user's word, 2026-11-11), Q8.
  Done there: `load cue L/C [only <family>…]` (GAP-44) and F4's `[load]`.

**From the grandMA3 howto (2026-11-12).** The user had busk compared, at `604dc3f`, with a
grandMA3 guide to programming a live show: patch, attributes, groups, presets, phasers, cues,
sequences, executors and recipes. Each doubtful point was checked on `OfflineShow` with
`examples/club-night.busk`. What busk lacks went into Phases 26 to 36 (the user's word,
2026-11-12). The rest stays here, **Not planned**, each with the reason.

- Every other fixture of a selection (grandMA3's MAtricks interleave, used for groups like "Spots
  Odd"): **Phase 26**, Q9.
- A track sheet. Nothing shows what a cue of a tracking list puts on stage: there is no `list cue
  L/C`, `list cues` gives only the timing, and F4 and `load cue` give what the cue stores.
  **Phases 27 and 28**, Q10. Phase 27 built the read (`tracking(L)`, GAP-46) and `list cue L/C`,
  and Phase 28 F4's TRACK panel, for the chosen cue.
- A cue's `block` is set only by the generic edit, which replies with a path, and `list cues` and
  F4 never show it: **Phases 27 and 28**. Phase 27 built `cue L/C block on|off` (GAP-47), and
  `list cues` marks a block cue; Phase 28 F4's `[block]`, and TRACK says when a cue is one.
- Timing per fixture, and a stagger over a selection: only the generic edit reaches an entry's own
  timing, by rewriting the whole `entries` list. **Phases 29 and 30**, Q11. Phase 29 built
  `cue L/C time <targets> <family> …` with a fan (GAP-48), under Q11 (a), and Phase 30 F4's TIME
  `on` chips, which send it.
- A spread is recorded per target even on a group, so a fixture that joins the group gets nothing
  from it, where entries, global and profile presets, and effects follow the group: **Phase 31**,
  Q12. Built there, under Q12 (a): recording finds the spread (GAP-49). Recipes themselves
  (regenerating presets and cues for another rig): **Not planned**.
- `docs/tui/guide.md`'s "Editing a cue's values" still says that an entry's own timing is set only
  by the generic edit, and that `[replace]` drops it. Since Phases 29 and 30, `cue L/C time
  <targets> …` and F4's TIME `on` chips set it, and `replace` keeps it on the same targets, as
  `load cue`'s reply says. Found on 2026-11-17, in Phase 31, which changed the sentence before it.
  Fixed the same day, at the user's word ("Fix that error in the TUI guide"): the reply to
  `[load]` names a timing of its own, as TIME's `on` chips set it, and `[replace]` keeps it on
  each entry it records again on the same targets.
- A figure eight (a layer at twice the rate of another), and library templates for a tilt sweep,
  random movement, a square dimmer and a two-colour alternation: **Phase 32**. Built there.
- `effect add` of a template whose layers no target has (Circle or Figure eight on the club
  show's washes, which have no pan or tilt) is taken in silence: the reply counts the targets
  (`added effect 'fx5' on 4 targets`) and `programmer` lists the effect, but it runs nothing.
  The compiler's warning reaches only `record cue`'s reply, which records the effect, with its
  path (`warning cueLists[20].cues[0].effects[0]: no target has pan or tilt: the effect does
  nothing`). Found on 2026-11-17, in Phase 32, and left as it is.
- A phaser kept with its settings for reuse (grandMA3 stores one in a preset): **Phase 33**, Q13.
  Built there, under Q13 (b): a template's defaults (GAP-51), set by F5's `[keep as defaults]`.
- `effect add "Circle" groups 0` was taken into the programmer, where a cue would refuse such an
  effect when recorded, and `blocks 0` or `wings 0` gave `internal error: ZeroDivisionError`. A
  rate of 0 and a size below 0 were refused with a path under the reply. Found on 2026-11-17, in
  Phase 33, whose line shares `effect add`'s option reader, and fixed there: each is refused in one
  line, in words (`expected a number of groups from 1, got '0'`). The cue effect's line is safe but
  refuses by path: `cue 11/1 effect fx1 groups 0` replies `set the groups of effect fx1 in cue
  11/1 to 0: rejected, the show would not be valid` and `cueLists[10].cues[0].effects[0].groups:
  Input should be greater than or equal to 1`, as `size -1` does. F5's dialogs refuse both first,
  so only the prompt meets them. Fixed the same day, at the user's word ("Fix the refusal with
  document path"): the line tries the new value on a copy of the instance first, by its schema
  and `validate_effect`'s rules, the checks busk runs on it in a cue, and refuses the first error
  in one line that names the property as the line does (`rate.value`), with no path: `effect fx1
  in cue 11/1: groups should be 1 or more, got '0'`, `… blocks should be a whole number, got
  '1.5'`, `… direction should be 'forward', 'reverse' or 'bounce', got 'sideways'`, `… rate.kind
  should be 'hz' or 'bpm', got 'fast'`, `… the size must be a finite number of 0 or more, got
  -1`, and `effect fx1 in cue 11/1 has no property 'colour'`. `_effect_edit` and
  `_schema_words` in `src/busk/console/parser.py`; `_set` and `_value` take the check, and
  `validate.py` names `loc_to_path` for it. Tests: 33 rows in `tests/test_console_parser.py`, 3
  in `tests/test_console.py`; eight mutations of the check each fail one. Calls the user may
  veto: a schema error's words are pydantic's after `should be` (`a valid number`), with busk's
  own for the bounds, a whole number, a missing key and a wrong kind; a rule's words are the
  validator's sentence, its first letter lowered; a master is named by its id, as the line takes
  it; and the check runs for `expected()` too, so `?` after the value and a space shows the
  refusal before Enter (`runnable` false, the line's error). With the fix, the whole suite: 6,917
  passed and 1 skipped, in 8:55 with `uv run pytest -n 6`.
- What busk sends on each DMX channel, to check a fixture's personality; overlaps at the prompt:
  **Phase 34**. Built there.
- Masters are made only at the prompt, and no line renames or deletes one: **Phase 35**. Built
  there.
- `master add speed "X" bpm 0`, `bpm 1000` and `steps 0, 1` are refused by document path
  (`masters[1].defaultBpm: The tempo must be greater than 0 and at most 999 BPM, got 0`), and `bpm
  50%` makes a master at 0.5 BPM, where `cue L/C time` and the other seconds refuse `%` since
  Phase 18. F7's form checks the tempo itself, so it never sends one of these; only the prompt
  meets them. Found on 2026-11-12, in Phase 35. Fixed the same day, at the user's word ("Fix
  those 2 findings"): `Parser.tempo` reads a tempo as plain BPM, above 0 and at most `MAX_BPM`,
  and `Parser.steps` each step as a plain number above 0, both with no sign and no `%`, as
  `seconds` reads a time. Anything else is refused in one line (`expected a tempo above 0, up to
  999 BPM, got '50%'`, `expected a multiplier step above 0, got '0'`). `bpm ["<master>"] <bpm>`
  read its tempo the same way (`bpm "Speed 1" 50%` set 0.5 BPM), so it takes the same reader;
  `numbers`, whose only caller was the steps, is gone. Rows in `tests/test_console_parser.py`, and
  `50%` and `+120` in the F7 form's agreement test, which now agrees with busk on both. The
  chase's and an effect's `x <multiplier>` were not checked.
- The guide's first note still said that renumbering a cue and a cue list is typed at the
  prompt, though F4 has had `[number…]` for both since Phase 22. Found on 2026-11-12, in Phase
  35, and fixed the same day: only a page's number is typed, as the report says. With both fixes, the
  whole suite: 6,609 passed and 1 skipped, in 8:34 with `uv run pytest -n 6`.
- Three setup lines with no control: F2's discrete attributes, the strobe cap and the show's
  title: **Phase 36**. Built there.
- `safety strobe 50%` sets a cap of 0.5 Hz, and `safety strobe +4` one of 4 Hz, where `bpm` and the
  seconds refuse a sign and `%` since Phase 18 and Phase 35's fix. `safety strobe 0` and `-1` are
  refused by document path (`strobe cap 0 Hz: rejected, the show would not be valid` and
  `safety.strobeMaxHz: Input should be greater than 0`), not in words. `_cmd_safety` reads the rate
  with `self.number`. F7's `[cap…]` refuses all four itself, so only the prompt meets them. Found
  on 2026-11-12, in Phase 36. Fixed on 2026-11-13, at the user's word ("fix the two findings"):
  `_cmd_safety` reads the rate as `Parser.tempo` reads a tempo, plain and above 0, with no top, as
  the model has none, and refuses anything else in one line (`expected a rate above 0 Hz, or off,
  got '50%'`). Rows in `tests/test_console_parser.py`; the F7 dialog's agreement test now holds
  `+4` and `50%` among the rates both refuse.
- At 99 columns, F2's PROGRAMMER CONTENTS wraps a long `other` cell onto a line of its own, under
  the `#` column: with 101 holding `gobo1 breakup`, `breakup` stands alone on the next line. The
  table did not change in Phase 36, whose option chips first set such a value from F2. Found on
  2026-11-12, in Phase 36's real-terminal check. Fixed on 2026-11-13, at the user's word: the other
  attributes wrap in their own column (`other_lines` in `src/busk_tui/widgets/programmer.py`), as
  many to a line as fit with `·` between them, and one too long for a line of its own breaks at
  its space (`textwrap`); each later line starts under `other`. The table is laid out again at
  each resize. Below 8 cells for the column (`OTHER_MIN`, where the fixed columns fill the screen
  anyway), a row stays one line, as before. Under `busk run` at 99 columns, 101 holding `gobo1
  breakup` and `shutter strobe` shows `gobo1`, `breakup`, `shutter`, `strobe` down the column,
  which is 11 cells there. Tests: 2 in `tests/tui/test_tui_program.py`. Calls the user may veto:
  wrapping, not cutting with `…` as the table's other cells are cut, so every value held shows;
  and an attribute split from its value at a narrow column, not cut. With both fixes, the whole suite:
  6,647 passed and 1 skipped, in 9:11 with `uv run pytest -n 6`. A first run failed F6's
  real-engine preset test once, which passed alone three times and in its file under `-n 6`, as
  in Phase 15. The perf gate: 8 passed, F2 +0.198 core, +0.237 with the heads moving.
- Cue parts. **Not planned**: a family's own timing (GAP-42) and, after Phase 29, an entry's own
  timing do what parts are mostly used for.
- A Control preset pool. **Not planned**: busk never programs `control` attributes (lamp on,
  reset), by design.
- A Gobo preset pool. **Not planned**: gobos record in `beam`, and `only beam` takes them.
- The library ships five profiles, where grandMA3 ships thousands. **Not planned**: `profile
  import` takes OFL and GDTF files, and F3's picker has `[import…]`.
- A wave layer that steps through presets (a position phaser between position presets). **Not
  planned**: only a colour palette takes presets, and a position step needs pan and tilt from one
  preset, which is a layer kind of its own.
- A form and a width for each effect, rather than for its template. **Not planned**: a copy of a
  template is one line, or `[+ template…]` on F5.
- Blocks, groups and wings for `set … spread` and for a timing fan, as for effects. **Not
  planned**: `center` and `edges` cover two wings, and Phase 26 covers interleaving.
- Times given with `record cue` (grandMA3 stores with a fade). **Not planned**: F4's `[time…]`
  sets them in one click afterwards.
- A position preset recorded at `target` scope, its pool's default, reaches no fixture added
  later. **Not planned**: `profile` scope reaches every fixture of the profile, and F6's scope chips
  choose it.
- `busk-tui` opens a show but does not make one. **Built** by the file-menu plan
  (`docs/plans/file-menu-plan.md`, Phase 3, 2026-11-20): the File menu's New… writes a show with
  `busk new` and opens it, and Open… and Open recent… open another show, each from inside the
  TUI.
- New cue lists start without tracking: §5, call 20.

**F9's setup (2026-11-23).**

- F9 sets up no surface or binding: its edits put `bind`, `unbind`, `feedback` and `pickup` lines
  in the prompt (the report's "Beyond this report"), and busk has no line to delete, rename or
  change a surface, nor one that removes or changes a single binding. **Phases 38 to 41**, the
  user's word of 2026-11-23.
- `bind` takes a MIDI channel outside 1 to 16 and a number above 127 in silence, a control its
  surface cannot send with a warning by path, and `display` feedback on MIDI in silence. Found on
  2026-11-23, while planning Phase 40. **Phase 40**, step 2. Fixed there the same day.

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

   ANSWER: (a), the recommended one (the user, 2026-11-10: "Skip phase 14"). Phase 14 is dropped,
   and busk still refuses a split patch when it compiles a show.
5. **Editing a cue's cells** (Phase 15). The TUI plan left it out on purpose. `RowTable` draws
   lines, so a cell holds no widget, and the prompt always has the keyboard.
   - (a) A dialog per cell, as F3 does. **Recommended.**
   - (b) A real editor over the cell.
   - (c) Keep the pre-fills, and drop Phase 15.

   ANSWER: (a), the recommended one (the user, 2026-11-10). Built in Phase 15.
6. **How busk groups a drag into one undo step** (Phase 20). An F2 drag sends about ten `set`
   lines a second, each an undo step.
   - (a) `undo group "<label>"` and `undo group end`, as engine-gaps.md's GAP-06 has it, kept to
     programmer steps. A show step, `undo` or 2 s with no step closes it. Other lines sent during
     the group, from the web remote or a MIDI surface, join it. **Recommended:** it is explicit,
     the TUI says where a gesture starts and ends, and a typed line never merges by surprise.
   - (b) busk merges a `set` of one attribute on the same selection into the step before, within
     1 s. There are no new lines, but two quick lines typed at the prompt merge too.

   ANSWER: (a), the recommended one (the user's standing word, "use recommended answers",
   2026-11-17). Built in Phase 20.
7. **What F4 shows of the other families** (Phase 23). The cue table has intensity and colour
   columns only, as the spec's §8.4 says, and narrow screens already drop columns.
   - (a) One more column, `also`, naming the other families and how many entries each has
     (`position 2, beam 1`), dropped first when narrow. **Recommended:** it is small, and shows
     that a cue is not empty.
   - (b) A panel under the table listing every entry of the chosen cue, with values.
   - (c) Leave F4 as the spec says, and drop Phase 23.

   ANSWER: (a), the recommended one (the user, 2026-11-11). But "dropped first" left it hidden at
   150 and 99 columns (the table is 106 cells wide at 150 and its columns took 102), so the user
   chose then that the curve goes first and `also` second: it shows from 150 columns. Built in
   Phase 23.
8. **What `load cue` takes** (Phase 25). A cue of a tracking list stores its changes only; on
   stage it shows those over what the cues before it left.
   - (a) The cue's own entries and effects: what it stores. **Recommended:** `[replace]` then gives
     back the cue as it was, and the programmer holds nothing of other cues, so a `[merge]` into
     another cue cannot carry their values there.
   - (b) Its tracked state: what it shows on stage, the cues before it included, less its
     releases. `[replace]` on a tracking list still stores only the changes, but the programmer
     holds values the cue does not.

   ANSWER: (a), the recommended one (the user, 2026-11-11). Built in Phase 25.
9. **How busk takes every other target** (Phase 26).
   - (a) `odd` and `even`, after the targets of a `sel` line or alone on the selection.
     **Recommended:** it is what the howto's groups need, in two words.
   - (b) `every N [from K]`, with `odd` and `even` as its two common cases. Thirds and quarters
     then come too, for three- and four-colour looks, at the cost of a longer grammar.
10. **What F4 shows of tracking** (Phase 28).
    - (a) A TRACK panel under the cue table for the chosen cue: each fixture, its value in each
      family, and where it comes from. It is small, and it answers "why is this blue here".
    - (b) A track sheet: F4's table switches to a view with the same rows, one per cue, and a
      column per fixture for one family at a time. Own values are bright and tracked ones dim, and
      releases and block cues are marked. **Recommended:** it is what the howto's track sheet is,
      it shows how a value runs down the cues, and it keeps F4's rows, so a click still chooses a
      cue.
    - (c) Only `list cue L/C` at the prompt, and drop Phase 28.

    ANSWER: (a) (the user, 2026-11-16). Phase 28 was built first under (b), the recommended one;
    the user's check found the track sheet confusing and its columns too narrow to read, and
    chose (a): "the info deploys in a new panel under the current cue table". Built in Phase 28.
11. **How a fixture gets its own timing** (Phases 29, 30).
    - (a) An entry's timing takes a fan (`delay 0 to 2`), set by `cue L/C time <targets> <family>
      …` and by F4's TIME dialog. **Recommended:** the cue stays recorded on its groups, so a fan
      follows a group as it grows, and the programmer and `load cue` do not change.
    - (b) Timing in the programmer, as grandMA3 has it: `set … delay 0 to 2`, recorded into the
      entries. The programmer, `record` and `load cue` all change, and each slot carries a time
      beside its value.
    - (c) Leave it out, and drop Phases 29 and 30.

    ANSWER: (a), the recommended one (the user's standing word, "use recommended answers",
    2026-11-17). Built in Phases 29 and 30.
12. **How a recorded spread follows its group** (Phase 31).
    - (a) Recording finds the fan: values on a group that form a spread over its members are
      recorded as a spread. **Recommended:** the programmer does not change, and the cue plays the
      same until the group changes.
    - (b) The programmer keeps the fan that `set … spread` made, as a third form of value, and
      recording writes it. This changes phase-3-plan's decision 7, and a later `set` on one target
      has to break the fan.
    - (c) Leave spreads per target, and drop Phase 31.

    ANSWER: (a), the recommended one (the user's standing word, "use recommended answers",
    2026-11-17). Built in Phase 31.
13. **How an effect's settings are kept for reuse** (Phase 33).
    - (a) As now. A playback holding one effect, on a busking page, already replays it with its
      settings, and F5's EFFECT panel changes it afterwards. Drop Phase 33.
    - (b) A show template keeps defaults, as the library's templates do, set from F5's EFFECT panel.
      **Recommended:** it is the smallest change that makes a settled effect one click, and it fits
      `effect add`'s words.
    - (c) A preset holds effects, as grandMA3's phaser presets do. The model, `record preset`,
      `preset`, the cascades, `load cue` and F6 all change, so it is two phases.

    ANSWER: (b), the recommended one (the user's standing word, "use recommended answers",
    2026-11-17). Built in Phase 33.
14. **What learn mode learns** (Phase 37, step 3). The spec puts `[learn]` on a binding row, but
    `bind` adds a binding beside those already on an input, so moving one to another control is
    two lines, `unbind` then `bind`, and two undo steps.
    - (a) `[learn]` on the chosen surface. The next input from it pre-fills `bind "<surface>"
      <input> `, and the operator types what it drives. **Recommended:** one pre-fill, one line,
      and nothing is removed behind the operator's back.
    - (b) `[learn]` on a binding row, as the spec has it. The next input moves that binding to
      the new control. This needs a new engine line, so the move is one undo step (a new gap).
    - (c) Both.

    ANSWER: (a), the recommended one (the user's standing word, "use recommended answers",
    2026-11-18). Built in Phase 37.
15. **How a line names one binding** (Phases 40, 41). A binding has an id but no number or name,
    and `unbind` and `feedback` name a control, so they take every binding on it.
    - (a) By its id, as a route is named (`route <id> change`, `delete route <id>`): `delete
      binding <id>` and `binding <id> change <input> <what> [feedback]`. `list bindings` prints
      the ids, and Tab offers them. **Recommended:** it names any binding (one of two on a
      control, a clock's, a pitch bend's from a show file), F9 holds the ids, and `unbind` stays
      the readable line at the prompt.
    - (b) By its surface, its control and what it drives: `unbind "<s>" <input> <what>` takes that
      one, and `rebind "<s>" <input> <what> to <input> <what> [feedback]` changes it. It reads
      well typed, but it is long, two alike bindings on one control cannot be told apart, and a
      binding whose target `bind` cannot word (a command from a show file) has no name.

    ANSWER: (a), the recommended one (the user's standing word, "use recommended answer to
    questions", 2026-11-23). Built in Phase 40.
