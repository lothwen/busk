# TUI status: show, add, delete and update

What the TUI lets an operator show, add, delete and update for fixtures and the patch, cues,
cue lists, presets, effects and playbacks (buttons and faders). For each operation it says
whether the TUI offers it, and if not, whether the TUI or busk is missing it.

Written 2026-11-01 at `f19c4ec` (after TUI Phase 5). Every busk line below was run on
`OfflineShow` with `examples/club-night.busk`. The TUI side comes from `src/busk_tui/`:
`commands.py` builds every line the UI sends, and the pages hold the controls and pre-fills.
The Presets rows were updated on 2026-11-02, once
[the presets plan](../../plans/tui-presets-plan.md) gave every one a control (F6's edit mode
and its PRESET panel).

## How to read it

The TUI acts only through console lines, sent with `LiveShow.execute()`
([implementation plan](implementation-plan.md) §1.1, Q1). So busk's console grammar is the
most the TUI can do. busk's command layer (`submit()`, with generic `ADD`, `SET` and `DELETE`
on any path of the show) can do more, but the TUI does not use it.

The prompt passes any line to busk, with Tab completion and `?`. So everything the console can
do can already be typed in the TUI. The tables below show how much the screens help beyond that:

| TUI | Meaning |
|---|---|
| **control** | a click or a key runs the line |
| **pre-fill** | a click puts the start of the line in the prompt, and the operator finishes it |
| **prompt** | only by typing the whole line |
| **none** | busk's console has no line for it |

| Engine | Meaning |
|---|---|
| **yes** | a console line does it |
| **partial** | a line exists but has a limit that matters, given in the row |
| **no** | no console line does it |

## Summary

| | SHOW | ADD | DELETE | UPDATE |
|---|---|---|---|---|
| Fixtures, patch | control (F3, F8, F1 A/C) | prompt | prompt; engine partial | pre-fill (patch, location, category, name); prompt for the rest; mode change: engine no |
| Cues | control (F4) | control (append); prompt (at a number) | prompt | pre-fill (timing, trigger, name); prompt (values) |
| Cue lists | control (F4) | prompt; engine partial | prompt; engine partial | control (sequence/chase); prompt for the rest |
| Presets | control (F6, colour chips) | control (F6's PRESET panel) | control; engine partial | control (values, name, number) |
| Effects in the programmer | control (F5, F1 B) | control | control | control (stop, run); prompt (settings) |
| Effects in cues | control (F5) | control (via `record cue`) | prompt; engine partial | prompt |
| Effect templates | control (F5) | prompt (JSON) | none: engine no | none: engine no |
| Playbacks, operating | control (F1) | n/a | n/a | control: fader, GO, ◂, FLASH; the playback's own buttons: prompt |
| Playbacks, configuration | partial: not shown | prompt; engine partial | prompt; engine partial | prompt; engine partial |

In short:

- **SHOW is covered** for all of them except a playback's configuration: its buttons, fader
  function, band, exclusivity, flash, LTP mode and release time are on no screen.
- **The TUI is a performance and programming frontend, not a show editor yet.** Presets are
  the exception: F6 shows, adds, deletes and updates them from controls alone. Beyond them,
  nothing can be deleted from a screen except a programmer effect (`✕`), and ADD has
  controls only for cues (append) and programmer effects. UPDATE has pre-fills for a
  fixture's patch, location, category and name, and for a cue's timing, trigger and name. The
  rest is typed at the prompt.
- **busk itself is missing a few lines.** It cannot delete, change or rename an effect
  template. It cannot add a playback for an existing cue list, or remove one effect from a
  cue. It cannot change a fixture's mode, or create an empty cue list. Deletes never
  cascade: a fixture, preset, cue list, playback or universe that something uses must first
  be freed by hand (see [What busk is missing](#what-busk-is-missing)).

## Fixtures and patch

| Operation | busk line | Engine | TUI |
|---|---|---|---|
| Show | typed `LiveShow.show` and `.output`; `list fixtures`, `list universes` | yes | control: F3 table (profile, mode, patch, live values, source); F8 universes, routes and DMX map; F1 A and C |
| Add a fixture | `fixture add N [thru M] "<profile>" mode <mode> [at U.A]` | yes | prompt (the empty-state text shows the syntax) |
| Add a universe | `universe add N ["name"]` | yes | prompt |
| Delete a fixture | `delete fixture N` | partial: one fixture per line (`thru` is refused); refused while a group, preset or cue names it | prompt |
| Delete a universe | `delete universe N` | partial: refused while a fixture is patched in it | prompt |
| Patch, unpatch | `fixture N patch U.A`, `fixture N patch none` | yes | pre-fill on F3 (`patch…`) |
| Rename | `rename fixture N "…"`, `rename universe N "…"` | yes | pre-fill on F3 for a fixture; prompt for a universe |
| Location | `fixture N location {…}` | yes | pre-fill on F3 and F1 C |
| Category | `profile "<name>" category …` | yes | pre-fill on F3 |
| Renumber | `fixture N number M` (generic property) | yes | prompt |
| Limits | `fixture N [thru M] limits …` | yes | prompt |
| Change mode or profile | none (`fixture N modeId "<id>"` takes busk's internal mode id) | no: delete it and add it again | none |

GAP-22 is still open: a parked value reads as "none" in F3's source column.

## Cues

| Operation | busk line | Engine | TUI |
|---|---|---|---|
| Show | typed `LiveShow.show`; `list cues L` | yes | control: F4 cue table (current cue, number, name, fades with family timings, delays, curve, trigger, intensity and colour entries, effect ids). Values of the other families (position, beam…) are not shown |
| Add at the end | `record cue L` | yes | control: F4 `[record cue L]` |
| Add at a number, insert | `record cue L/C [only …] [freeze] ["name"]` (`9/2.5` goes between 2 and 3) | yes | prompt |
| Delete | `delete cue L/C` | yes | prompt |
| Change its values | `record cue L/C merge\|replace\|remove [only …]` | yes | prompt |
| Timing | `cue L/C time …`, `cue L/C time <family> …` | yes | pre-fill on F4 (`time…`, `delay…`, `curve…`, and a click on those cells) |
| Trigger | `cue L/C go`, `… follow <d>`, `… wait <d>` | yes | pre-fill on F4 |
| Rename | `rename cue L/C "…"` | yes | pre-fill on F4 |
| Release targets | `cue L/C release <targets> [only …]` | yes | prompt |
| Renumber, move, copy | `cue L/C number "…"` (generic property) | partial: only while the order stays; no move or copy | prompt |

## Cue lists

| Operation | busk line | Engine | TUI |
|---|---|---|---|
| Show | typed `LiveShow.show`; `list cuelists` | yes | control: F4 CUELISTS (number, name, kind, cue count, playback) and the meta line (mode, tracking, chase settings, playbacks and level, groups) |
| Add | none. `record cue N/1` creates list N with its first cue; `record slot` creates a list with a playback | partial: no empty list | prompt |
| Delete | `delete cuelist N` | partial: refused while a playback runs it | prompt |
| Sequence or chase | `cuelist N sequence`, `cuelist N chase hz\|bpm …` | yes | control: F4 toggle (keeps the list's chase settings, else `bpm x 1`); prompt for rate, direction and crossfade |
| Tracking | `cuelist N tracking true\|false` (generic property) | yes | prompt (F4 shows it) |
| Rename | `rename cuelist N "…"` | yes | prompt |
| Renumber | `cuelist N number M` (generic property) | yes | prompt |

## Presets

| Operation | busk line | Engine | TUI |
|---|---|---|---|
| Show | typed `LiveShow.show`; `list presets` | yes | control: F6 tiles per pool with a preview; colour chips on F1 and F2. In edit mode, the PRESET panel shows what a preset holds (each stored value, its scope and where) and the cues and effect palettes that use it |
| Add | `record preset <pool> N [global\|profile\|target] ["name"]` | yes | control: F6's `+ record` tile opens the PRESET panel, with the next free number. Every pool the rig can record into shows. The panel sets the number, name and scope, the selection, and every value the pool records: encoder rows, a colour picker, option chips for the discrete attributes, and spreads (fans). It shows what a record takes, then `[record]` |
| Delete | `delete preset <pool> N` | partial: refused while a cue uses it | control: `[delete]`, after the TUI's own question (busk asks none). Inert while cues or effect palettes use the preset, and the panel names them |
| Change its values | `record preset <pool> N merge\|replace\|remove` | yes | control: `[its fixtures]`, `[load]`, the panel's editors, then `[merge]`, `[replace]` or `[remove]` |
| Rename | `rename preset <pool> N "…"` | yes | control: `[rename…]`, a name dialog |
| Renumber | `preset <pool> N number M` (generic property) | yes | control: `[number…]`, a dialog that refuses a taken number |

## Effects

busk has three kinds of effect: programmer effects (`effect add`, ids like `fx5`), effects
recorded into cues, and the templates both are made from.

| Operation | busk line | Engine | TUI |
|---|---|---|---|
| Show | typed `ProgrammerStatus.effects`, `LiveShow.show`, `LiveShow.effects`, `LiveShow.effect_templates` | yes | control: F5 table (cue and programmer effects, their settings, live wave, state) and TEMPLATES; F1 B EFFECTS |
| Add to the programmer | `effect add "<template>" [options…]` | yes | control: a template click on F5 (`effect add "<name>"`, the library's defaults); prompt for options |
| Add to a cue | `record cue L/C` with effects in the programmer | yes | control: F4 `[record cue L]` |
| Add a template | `effect template add "<name>" <JSON layers>` | yes | prompt |
| Remove from the programmer | `effect remove <id>`, `effect clear` | yes | control: `✕` on F5; prompt for `effect clear` |
| Remove from a cue | none. Work-around: `effect add` with the same id, then `record cue L/C remove` | partial | prompt |
| Delete a template | none (`submit()` can, while no cue uses it) | no | none |
| Stop, run (programmer) | `effect stop <id>`, `effect run <id>` | yes | control: state toggle on F5 and F1 B |
| Change settings (programmer) | `effect add "<template>" id <id> …` replaces them | yes | prompt |
| Change settings (cue) | `cue L/C effect <id> <prop> <value>` | yes | prompt |
| Change or rename a template | none: `effect template add` refuses a name that exists | no | none |

## Playbacks (buttons and faders)

| Operation | busk line | Engine | TUI |
|---|---|---|---|
| Show live state | typed `PlaybackStatus` (state, level, fader function, flash, cue, next, chase, colour) | yes | control: F1 shows the current page's playbacks with level, cue, next, colour and a fader tag (`xfade`, `rate`, `size`, `temp`, `no fader`); F4 names the playbacks that run a list |
| Show configuration | `LiveShow.show`; `list playbacks` | yes | none: no screen shows buttons, band, exclusivity, flash, LTP mode or release time. The TUI's `PlaybackInfo` reads only number, name, cue list and `uiColor` |
| Fader | `fader N <level>` | yes | control: drag, wheel, `[ ]` |
| GO, BACK, go to a cue | `go N`, `back N`, `goto N <cue>` | yes | control: F1 GO and ◂; F4 buttons and cue rows |
| Flash | `flash N on\|off` | yes | control: FLASH, held |
| Release | `release N [<s>]`, `release all` | yes | control: F5 state click (cue effects), F7 `release all`; prompt for one playback |
| The playback's own buttons | `button N B on\|off`, `toggle N` (GAP-04) | yes | prompt. Every strip shows GO, ◂ and FLASH whatever the playback's `buttons` are, so a `toggle`, `release`, `select` or `swop` button cannot be pressed from F1 |
| Add | none. `record slot [P.]S` creates a playback, always with a new cue list and its cue 1, with fixed defaults | partial: no playback for an existing cue list (`submit()` can) | prompt |
| Delete | `delete playback N` | partial: refused while a page slot holds it (`page P slot S clear` on every page first); its cue list stays | prompt |
| Place on a page | `page P slot S playback N`, `page P slot S clear`, `page add N` | yes | prompt |
| Buttons, fader function | `playback N buttons ["go", "flash", "release"]`, `playback N fader "rate"` | partial: generic properties with JSON values; `help` and `?` name no properties | prompt |
| Band, exclusivity, flash, LTP, release time, colour | `playback N priority 60`, `… exclusivity "wash"`, `… flash.level 0.5`, `… ltpFaderMode "followFader"`, `… releaseTime 2`, `… uiColor "#ff8800"` | partial: as above | prompt |
| Rename, renumber | `rename playback N "…"`, `playback N number M` | yes | prompt |
| Run another cue list | `playback N cueListId "<id>"` | partial: needs busk's internal id | prompt |

## What busk is missing

Candidates for [engine-gaps.md](engine-gaps.md), if the TUI is to cover these:

1. **Effect templates** cannot be deleted, changed or renamed from the console.
   `effect template add` refuses an existing name, and `delete` does not take templates.
   `submit()` can do all three.
2. **Playbacks** can only be created by `record slot`, which always makes a new cue list. No
   line adds a playback for an existing list, or points a playback at another list by number.
3. **A cue's effect** cannot be removed by its id. `record cue L/C remove` needs the effect in
   the programmer first.
4. **A fixture's mode** (or profile) cannot be changed. The only way is to delete the fixture
   and add it again, which its groups, presets and cues prevent (item 6).
5. **An empty cue list** cannot be created. This is minor: recording cue 1 creates the list.
6. **Deletes do not cascade** and take one entity per line. To delete a fixture used by groups
   and presets, a preset used by cues, a cue list a playback runs, a playback on a page, or a
   universe with fixtures in it, every reference must be removed first. The error lists them.
   A TUI delete button would mostly show that error.
7. **Playback and cue list settings** are only reachable as generic property lines with JSON
   values. They work, but `help` and `expected()` name no properties (`playback 3 ` gives "a
   property, e.g. name or timing.fadeIn"). A TUI form would have to hard-code busk's schema
   names.

## What the TUI is missing

busk has the line for all of these, but no screen offers it. Grouped by the screen that would
host it:

- **F1**: the playback's own buttons (`button N B on|off`) instead of the fixed GO, ◂ and
  FLASH; `record slot` on an empty slot.
- **F3, F8**: add a fixture, add a universe, delete either, limits, renumber, rename a
  universe. A profile and mode picker for `fixture add` can be built from `expected()`, which
  lists the library's profiles and a profile's modes, so it needs no new gap.
- **F4**: delete a cue; re-record a cue (`merge`, `replace`, `remove`); record at a number;
  a new cue list; delete, rename, tracking and chase settings of a list; release targets.
- **F5**: edit an effect's settings (programmer: `effect add … id <id>`; cue: `cue L/C
  effect`); `effect clear`; add a template.
- **Playbacks**: no screen views or edits their configuration (buttons, fader function,
  band, exclusivity, flash, LTP mode, release time, page slots), and none adds or deletes one.

## Side findings

- **busk bug:** `record cue L/C remove` removes the cue's effect but replies `… 0 effects`.
  Seen on cue 11/1; `undo` brings the effect back.
- `LiveShow.confirmation()` asks nothing before a `delete`, a `record … replace` or `effect
  clear`. They are undo steps. A TUI delete button would rely on `undo`, unless the TUI asks
  first itself. F6's `[delete]` asks first (`RunLine.ask`).
