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
| Universes, routes | control (F8) | control (F8) | control (a universe cascades) | control; editing a route: prompt |
| Cues | control (F4) | control | control | control (values, releases); pre-fill (timing, trigger, name) |
| Cue lists | control (F4) | control | control (cascades) | control; renumber: prompt |
| Presets | control (F6, colour chips) | control (F6's PRESET panel) | control | control (values, name, number) |
| Effects in the programmer | control (F5, F1 B) | control | control | control (F5's EFFECT panel, stop, run) |
| Effects in cues | control (F5) | control (via `record cue`) | control | control (F5's EFFECT panel) |
| Effect templates | control (F5) | control (F5's `[+ template…]`) | control (F5's TEMPLATE panel) | control (F5's TEMPLATE panel) |
| Playbacks, operating | control (F1) | n/a | n/a | control: fader, GO, ◂, FLASH; the playback's own buttons: prompt |
| Playbacks, configuration | partial: not shown | prompt | prompt | prompt |

In short:

- **SHOW is covered** for all of them except a playback's configuration: its buttons, fader
  function, band, exclusivity, flash, LTP mode and release time are on no screen.
- **The TUI is a performance and programming frontend, and it edits the rig, the presets, the
  cue lists and the effects, but not the rest of a show yet.** F3, F8, F6, F4 and F5 show, add,
  delete and update fixtures, universes, routes, presets, cues, cue lists, effects and effect
  templates from controls alone; a cue's timing, trigger and name are pre-fills. The rest, a
  playback's configuration, is typed at the prompt.
- **busk has the lines the TUI needs.** Deleting several presets, cues or lists at once is all it
  still lacks (see [What busk is missing](#what-busk-is-missing)).

## Fixtures and patch

| Operation | busk line | Engine | TUI |
|---|---|---|---|
| Show | typed `LiveShow.show` and `.output`; `list fixtures` | yes | control: F3 table (profile, mode, patch, live values, source); its edit mode (limits, place) and FIXTURE panel (limits, orientation, location); F8's DMX map; F1 A and C |
| Add | `fixture add N [thru M] "<profile>" mode <mode> [at U.A]` | yes | control: F3's new fixture form, with a picker from `fixture_profiles` (GAP-27); F8's `[add fixture here…]` opens it at a free channel |
| Delete | `delete fixture N [thru M] cascade` (GAP-24, GAP-38), `delete fixture N` | yes: a run takes `thru` and always `cascade`. A plain `delete` is refused in one line while anything names it | control: `[delete]`, always `cascade`, after busk's question |
| Patch, unpatch | `fixture N [thru M] patch U.A`, `fixture N [thru M] patch none` (GAP-38) | yes | control: F3's PATCH; F8's `[patch N here]` on a free channel |
| Rename | `rename fixture N "…"` | yes | control: `[rename…]`, a name dialog |
| Renumber | `fixture N number M` (generic property) | yes | control: `[number…]`, a dialog that refuses a taken number |
| Limits | `fixture N [thru M] limits …`, `… limits pan\|tilt\|intensity none` (GAP-25), `… limits none` | yes | control: `[limit…]`, `[none]`, `[no limits]`, on the selection |
| Location | `fixture N location {…}`, `… location none` (GAP-25) | yes | control: `[location…]`, `[no place]` on F3; `[location…]` on F1 C |
| Orientation | `fixture N [thru M] orientation.<key> <value>` (GAP-28) | yes | control: toggles and `[offset…]`, on the selection |
| Category | `profile "<name>" category …` | yes | control: chips |
| Change mode | `fixture N mode <mode>` (GAP-26) | yes | control: chips |
| Change profile | `fixture N profile "<profile>" mode <mode>` (GAP-26) | yes | control: `[profile…]`, the picker, `[change]` |

GAP-22 is closed in busk: `FixtureOutput.source` says `park`. F3's source column still reads a
parked value as "none", until the pending plan's Phase 12.

## Universes and routes

| Operation | busk line | Engine | TUI |
|---|---|---|---|
| Show | typed `LiveShow.show` and `.routes`; `list universes`, `list routes` | yes | control: F8 UNIVERSES, ROUTES with each route's state and packet rate, and a DMX map per universe |
| Add a universe | `universe add N ["name"]` | yes | control: `[+ universe…]`, a form |
| Delete a universe | `delete universe N cascade` (GAP-24), `delete universe N` | yes. A plain `delete` is refused in one line while a fixture is patched in it or a route sends it | control: `[delete]`, always `cascade`, after busk's question |
| Rename | `rename universe N "…"` | yes | control: `[rename…]`, a name dialog |
| Renumber | `universe N number M` (generic property) | yes | control: `[number…]`, a dialog that refuses a taken number |
| Add a route | `route add …` | yes | control: `[+ route…]`, a form per protocol |
| Delete a route | `delete route <id>` (GAP-23) | yes | control: `[delete]`, after busk's question |
| Disable, enable | `route <id> on\|off` (GAP-23) | yes | control: `[off]`, after busk's question, and `[on]` |
| Change a route | `route <id> change <what route add takes>` (GAP-37) | yes | prompt |

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
| Add at a number, insert | `record cue L/C [only …] [freeze] ["name"]` (`9/2.5` goes between 2 and 3) | yes | control: F4 `[record at…]`, a form that refuses a cue that exists; `only` and `freeze`: prompt |
| Delete | `delete cue L/C` | yes | control: F4 `[delete]`, after the TUI's question, which says when a playback is on the cue |
| Change its values | `record cue L/C merge\|replace\|remove [only …]` | yes | control: F4 `[merge]`, `[replace]`, `[remove]`, the last two after the TUI's question; `only`: prompt |
| Timing | `cue L/C time …`, `cue L/C time <family> …` | yes | pre-fill on F4 (`time…`, `delay…`, `curve…`, and a click on those cells) |
| Trigger | `cue L/C go`, `… follow <d>`, `… wait <d>` | yes | pre-fill on F4 |
| Rename | `rename cue L/C "…"` | yes | pre-fill on F4 |
| Release targets | `cue L/C release <targets> [only …]` | yes | control: F4 `[release…]`, a form that starts at the selection |
| Renumber, move, copy | `cue L/C number "…"` (generic property) | partial: only while the order stays; no move or copy | prompt |

## Cue lists

| Operation | busk line | Engine | TUI |
|---|---|---|---|
| Show | typed `LiveShow.show`; `list cuelists` | yes | control: F4 CUELISTS (number, name, kind, cue count, playback) and the meta line (mode, tracking, chase settings, playbacks and level, groups) |
| Add | `cuelist add N ["name"]` (GAP-33), a list with no cues. `record cue N/1` creates list N with its first cue; `record slot` creates a list with a playback | yes | control: F4 `[+ list…]`, a form that refuses a number that is taken |
| Delete | `delete cuelist N cascade` (GAP-36), with the playbacks that run it; `delete cuelist N` | yes. A plain `delete` is refused in one line while a playback runs it | control: F4 `[delete]`, after busk's question |
| Sequence or chase | `cuelist N sequence`, `cuelist N chase hz\|bpm …` | yes | control: F4 toggle (keeps the list's chase settings, else `bpm x 1`), and `[chase…]`, a form for the rate, master, multiplier, direction and crossfade |
| Tracking | `cuelist N tracking true\|false` (generic property) | yes | control: F4 `[tracking on]`, `[tracking off]` |
| Rename | `rename cuelist N "…"` | yes | control: F4 `[rename…]`, a name dialog |
| Renumber | `cuelist N number M` (generic property) | yes | prompt |

## Presets

| Operation | busk line | Engine | TUI |
|---|---|---|---|
| Show | typed `LiveShow.show`; `list presets` | yes | control: F6 tiles per pool with a preview; colour chips on F1 and F2. In edit mode, the PRESET panel shows what a preset holds (each stored value, its scope and where) and the cues and effect palettes that use it |
| Add | `record preset <pool> N [global\|profile\|target] ["name"]` | yes | control: F6's `+ record` tile opens the PRESET panel, with the next free number. Every pool the rig can record into shows. The panel sets the number, name and scope, the selection, and every value the pool records: encoder rows, a colour picker, option chips for the discrete attributes, and spreads (fans). It shows what a record takes, then `[record]` |
| Delete | `delete preset <pool> N cascade` (GAP-36), `delete preset <pool> N` | yes. A plain `delete` is refused in one line while a cue or a palette uses it. The cascade is refused only for a palette's last colour | control: `[delete]`, and the panel names what uses the preset. In use by a cue or a palette: the cascade, after busk's question. Else the plain line, after the TUI's own question (busk asks none). A preset only a binding names is refused in one line: the TUI does not know that use, so the cascade is typed at the prompt |
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
| Add a template | `effect template add "<name>" <JSON layers>` | yes | control: `[+ template…]` on F5, a name and what its first layer is; the panel then edits it |
| Remove from the programmer | `effect remove <id>`, `effect clear` | yes | control: `✕` on F5; `[clear]`, after a question |
| Remove from a cue | `cue L/C effect <id> remove` (GAP-32) | yes | control: `✕` on F5, after a question |
| Delete a template | `effect template delete "<name>"` (GAP-31) | yes: refused while a cue, a binding or the programmer uses it, and for a template only the library has | control: `[delete]` on F5's TEMPLATE panel, after a question, grey while something uses it |
| Stop, run (programmer) | `effect stop <id>`, `effect run <id>` | yes | control: state toggle on F5 and F1 B |
| Change settings (programmer) | `effect add "<template>" id <id> …` replaces them | partial: the line takes its targets from the selection (GAP-41) | control: F5's EFFECT panel, while the selection is the effect's fixtures |
| Change settings (cue) | `cue L/C effect <id> <prop> <value>` | partial: no line takes an optional setting away (GAP-41) | control: F5's EFFECT panel |
| Change or rename a template | `effect template update "<name>" <JSON layers>`, `effect template rename "<name>" "<new name>"` (GAP-31) | yes: the show's own templates | control: F5's TEMPLATE panel, a control per setting of each layer, and `[rename…]` |

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
| Add | `playback add N cuelist L [at [P.]S] ["name"]` (GAP-34); `record slot [P.]S` makes one with a new cue list and its cue 1 | yes | prompt |
| Delete | `delete playback N cascade` (GAP-36), `delete playback N` | yes: its cue list stays. A plain `delete` is refused in one line while a page slot holds it | prompt |
| Place on a page | `page P slot S playback N`, `page P slot S clear`, `page add N` | yes | prompt |
| Buttons, fader function | `playback N buttons ["go", "flash", "release"]`, `playback N fader rate` | yes: `help` and `?` name them (GAP-35) | prompt |
| Band, exclusivity, flash, LTP, release time, colour | `playback N priority 60`, `… exclusivity wash`, `… flash.level 0.5`, `… ltpFaderMode followFader`, `… releaseTime 2`, `… uiColor "#ff8800"`, `<optional> none` | yes: as above | prompt |
| Rename, renumber | `rename playback N "…"`, `playback N number M` | yes | prompt |
| Run another cue list | `playback N cuelist L` (GAP-34) | yes: refused while it runs | prompt |

## What busk is missing

Candidates for [engine-gaps.md](engine-gaps.md), if the TUI is to cover these:

1. **Closed: effect templates** (GAP-31). `effect template delete`, `rename` and `update` do
   what only `submit()` could.
2. **Closed: a playback for a list** (GAP-34). `playback add N cuelist L [at [P.]S] ["name"]`
   makes one and `playback N cuelist L` points one at another list by number.
3. **Closed: a cue's effect** (GAP-32). `cue L/C effect <id> remove` removes one by its id.
4. **Closed: a fixture's mode and profile** (GAP-26). `fixture N mode <mode>` and `fixture N
   profile "<profile>" mode <mode>` change them by name, each in one undo step.
5. **Closed: an empty cue list** (GAP-33). `cuelist add N ["name"]` makes one.
6. **Closed in part: deletes that cascade** (GAP-24, GAP-36). A fixture, universe, preset,
   group, cue list, playback and page each take `cascade`, and a plain `delete` of something in
   use says so in one line. Fixtures take `thru` (GAP-38). The others still take one entity per
   line.
7. **Closed: playback and cue list settings** (GAP-35). `help` and `expected()` name them, a
   closed set offers its values, and `<property> none` removes an optional one.
8. **Closed: removing and switching a route** (GAP-23). This list first left it out: `route add`
   was the only route line, so none removed a route or switched one off.
9. **Closed: editing a route** (GAP-37). `route <id> change <what route add takes>` does it in
   one undo step, and keeps the id and whether it is on.

## What the TUI is missing

busk has the line for all of these, but no screen offers it. Grouped by the screen that would
host it:

- **F1**: the playback's own buttons (`button N B on|off`) instead of the fixed GO, ◂ and
  FLASH; `record slot` on an empty slot.
- **Playbacks**: no screen views or edits their configuration (buttons, fader function,
  band, exclusivity, flash, LTP mode, release time, page slots), and none adds or deletes one.

## Side findings

- `LiveShow.confirmation()` asks before every `delete … cascade`, `delete route <id>` and
  `route <id> off`, so F3's and F8's controls show busk's question. It asks nothing before
  any other `delete`, a `record … replace` or `effect clear`. They are undo steps. A TUI control
  there would rely on `undo`, unless the TUI asks first itself. F6's `[delete]`, F4's cue
  `[delete]`, `[replace]` and `[remove]`, and F5's `✕` on a cue's effect and `[clear]` ask first
  (`RunLine.ask`).
