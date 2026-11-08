# TUI status: show, add, delete and update

What the TUI lets an operator show, add, delete and update for fixtures and the patch, universes
and routes, cues, cue lists, presets, effects and playbacks (buttons and faders). For each
operation it says whether the TUI offers it, and if not, whether the TUI or busk is missing it.

Written 2026-11-01 at `f19c4ec` (after TUI Phase 5). Every busk line below was run on
`OfflineShow` with `examples/club-night.busk`. The TUI side comes from `src/busk_tui/`:
`commands.py` builds every line the UI sends, and the pages hold the controls and pre-fills.
The Presets rows were updated on 2026-11-02, once
[the presets plan](../../plans/tui-presets-plan.md) gave every one a control (F6's edit mode
and its PRESET panel). The fixture, universe and route rows were updated on 2026-11-07, once
[the rig plan](../../plans/tui-rig-plan.md) gave every one a control (F3's edit mode, FIXTURE
panel and new fixture form, F8's strips and place) and closed what busk lacked (GAP-23 to GAP-27).
From 2026-11-08, [the pending plan](../../plans/tui-pending-plan.md) tracks what is left, phase by
phase.

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
| Fixtures, patch | control (F3, F8, F1 A/C) | control (F3's form, F8's place) | control (cascades) | control (F3's FIXTURE panel, F8's place) |
| Universes, routes | control (F8) | control (F8) | control (a universe cascades) | control; a route cannot be edited: engine no |
| Cues | control (F4) | control (append); prompt (at a number) | prompt | pre-fill (timing, trigger, name); prompt (values) |
| Cue lists | control (F4) | prompt | prompt; engine partial | control (sequence/chase); prompt for the rest |
| Presets | control (F6, colour chips) | control (F6's PRESET panel) | control; engine partial | control (values, name, number) |
| Effects in the programmer | control (F5, F1 B) | control | control | control (stop, run); prompt (settings) |
| Effects in cues | control (F5) | control (via `record cue`) | prompt | prompt |
| Effect templates | control (F5) | prompt (JSON) | prompt | prompt |
| Playbacks, operating | control (F1) | n/a | n/a | control: fader, GO, ◂, FLASH; the playback's own buttons: prompt |
| Playbacks, configuration | partial: not shown | prompt; engine partial | prompt; engine partial | prompt; engine partial |

In short:

- **SHOW is covered** for all of them except a playback's configuration: its buttons, fader
  function, band, exclusivity, flash, LTP mode and release time are on no screen.
- **The TUI is a performance and programming frontend, and it edits the rig and the presets,
  but not the rest of a show yet.** F3, F8 and F6 show, add, delete and update fixtures,
  universes, routes and presets from controls alone. Beyond them, nothing can be deleted from
  a screen except a programmer effect (`✕`), and ADD has controls only for cues (append) and
  programmer effects. UPDATE has pre-fills for a cue's timing, trigger and name. The rest is
  typed at the prompt.
- **busk itself is missing a few lines.** It cannot add a playback for an existing cue
  list, or edit a route. Only a fixture and a universe delete with what uses them: a preset, cue list or playback that something uses must first
  be freed by hand (see [What busk is missing](#what-busk-is-missing)).

## Fixtures and patch

| Operation | busk line | Engine | TUI |
|---|---|---|---|
| Show | typed `LiveShow.show` and `.output`; `list fixtures` | yes | control: F3 table (profile, mode, patch, live values, source); its edit mode (limits, place) and FIXTURE panel (limits, orientation, location); F8's DMX map; F1 A and C |
| Add | `fixture add N [thru M] "<profile>" mode <mode> [at U.A]` | yes | control: F3's new fixture form, with a picker from `fixture_profiles` (GAP-27); F8's `[add fixture here…]` opens it at a free channel |
| Delete | `delete fixture N cascade` (GAP-24), `delete fixture N` | yes: one fixture per line (`thru` is refused). A plain `delete` stays refused while a group, preset or cue names it | control: `[delete]`, always `cascade`, after busk's question |
| Patch, unpatch | `fixture N patch U.A`, `fixture N patch none` | yes | control: F3's PATCH; F8's `[patch N here]` on a free channel |
| Rename | `rename fixture N "…"` | yes | control: `[rename…]`, a name dialog |
| Renumber | `fixture N number M` (generic property) | yes | control: `[number…]`, a dialog that refuses a taken number |
| Limits | `fixture N [thru M] limits …`, `… limits pan\|tilt\|intensity none` (GAP-25), `… limits none` | yes | control: `[limit…]`, `[none]`, `[no limits]`, on the selection |
| Location | `fixture N location {…}`, `… location none` (GAP-25) | yes | control: `[location…]`, `[no place]` on F3; `[location…]` on F1 C |
| Orientation | `fixture N [thru M] orientation.<key> <value>` (GAP-28) | yes | control: toggles and `[offset…]`, on the selection |
| Category | `profile "<name>" category …` | yes | control: chips |
| Change mode | `fixture N mode <mode>` (GAP-26) | yes | control: chips |
| Change profile | `fixture N profile "<profile>" mode <mode>` (GAP-26) | yes | control: `[profile…]`, the picker, `[change]` |

GAP-22 is still open: a parked value reads as "none" in F3's source column.

## Universes and routes

| Operation | busk line | Engine | TUI |
|---|---|---|---|
| Show | typed `LiveShow.show` and `.routes`; `list universes`, `list routes` | yes | control: F8 UNIVERSES, ROUTES with each route's state and packet rate, and a DMX map per universe |
| Add a universe | `universe add N ["name"]` | yes | control: `[+ universe…]`, a form |
| Delete a universe | `delete universe N cascade` (GAP-24), `delete universe N` | yes. A plain `delete` stays refused while a fixture is patched in it or a route sends it | control: `[delete]`, always `cascade`, after busk's question |
| Rename | `rename universe N "…"` | yes | control: `[rename…]`, a name dialog |
| Renumber | `universe N number M` (generic property) | yes | control: `[number…]`, a dialog that refuses a taken number |
| Add a route | `route add …` | yes | control: `[+ route…]`, a form per protocol |
| Delete a route | `delete route <id>` (GAP-23) | yes | control: `[delete]`, after busk's question |
| Disable, enable | `route <id> on\|off` (GAP-23) | yes | control: `[off]`, after busk's question, and `[on]` |
| Change a route | none: delete it and add another | no | none |

**Corrections to the first version of this report,** found while planning the rig (2026-11-05):

- `delete universe` is refused by routes too, not only by a fixture patched in it. No console
  line removed a route, so a universe with one could not be deleted from the console at all.
- A fixture's mode could already be changed: `fixture N modeId` took busk's internal id. So
  "engine no" was too strong for the mode. It held for a mode by name and for the profile.
- Orientation had no row.
- `expected()` gives a picker the profiles' and modes' names but no footprint, so a picker could
  not be built from it alone, as the report said. GAP-27 added `fixture_profiles`.

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
| Add | `cuelist add N ["name"]` (GAP-33), a list with no cues. `record cue N/1` creates list N with its first cue; `record slot` creates a list with a playback | yes | prompt |
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
| Remove from a cue | `cue L/C effect <id> remove` (GAP-32) | yes | prompt |
| Delete a template | `effect template delete "<name>"` (GAP-31) | yes: refused while a cue, a binding or the programmer uses it, and for a template only the library has | prompt |
| Stop, run (programmer) | `effect stop <id>`, `effect run <id>` | yes | control: state toggle on F5 and F1 B |
| Change settings (programmer) | `effect add "<template>" id <id> …` replaces them | yes | prompt |
| Change settings (cue) | `cue L/C effect <id> <prop> <value>` | yes | prompt |
| Change or rename a template | `effect template update "<name>" <JSON layers>`, `effect template rename "<name>" "<new name>"` (GAP-31) | yes: the show's own templates | prompt |

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

1. **Closed: effect templates** (GAP-31). `effect template delete`, `rename` and `update` do
   what only `submit()` could.
2. **Playbacks** can only be created by `record slot`, which always makes a new cue list. No
   line adds a playback for an existing list, or points a playback at another list by number.
3. **Closed: a cue's effect** (GAP-32). `cue L/C effect <id> remove` removes one by its id.
4. **Closed: a fixture's mode and profile** (GAP-26). `fixture N mode <mode>` and `fixture N
   profile "<profile>" mode <mode>` change them by name, each in one undo step.
5. **Closed: an empty cue list** (GAP-33). `cuelist add N ["name"]` makes one.
6. **Deletes cascade only for fixtures and universes** (GAP-24 closed those), and take one
   entity per line. To delete a preset used by cues, a cue list a playback runs or a playback
   on a page, every reference must be removed first. The error lists them. A TUI delete button
   for those would mostly show that error, as F6's stays grey and names what uses the preset.
7. **Playback and cue list settings** are only reachable as generic property lines with JSON
   values. They work, but `help` and `expected()` name no properties (`playback 3 ` gives "a
   property, e.g. name or timing.fadeIn"). A TUI form would have to hard-code busk's schema
   names.
8. **Closed: removing and switching a route** (GAP-23). This list first left it out: `route add`
   was the only route line, so none removed a route or switched one off.
9. **A route** cannot be edited. To change one, delete it and add another.

## What the TUI is missing

busk has the line for all of these, but no screen offers it. Grouped by the screen that would
host it:

- **F1**: the playback's own buttons (`button N B on|off`) instead of the fixed GO, ◂ and
  FLASH; `record slot` on an empty slot.
- **F4**: delete a cue; re-record a cue (`merge`, `replace`, `remove`); record at a number;
  a new cue list; delete, rename, tracking and chase settings of a list; release targets.
- **F5**: edit an effect's settings (programmer: `effect add … id <id>`; cue: `cue L/C
  effect`); remove one effect from a cue; `effect clear`; add, delete, rename and change a
  template.
- **Playbacks**: no screen views or edits their configuration (buttons, fader function,
  band, exclusivity, flash, LTP mode, release time, page slots), and none adds or deletes one.

## Side findings

- `LiveShow.confirmation()` asks before `delete fixture|universe N cascade`, `delete route <id>`
  and `route <id> off`, so F3's and F8's controls show busk's question. It asks nothing before
  any other `delete`, a `record … replace` or `effect clear`. They are undo steps. A TUI delete
  button there would rely on `undo`, unless the TUI asks first itself. F6's `[delete]` asks first
  (`RunLine.ask`).
