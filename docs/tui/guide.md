# The terminal UI: `busk-tui`

`busk-tui` is a full-screen front end for busk. It runs your show under `busk run`, with the
watchdog, autosave, crash recovery and the event log, and puts a status bar, pages, a log and
the console prompt on one screen. Every click and key in it is a console line, echoed in the
log, so what the UI does is what you could type.

> **What it covers.** The frame (the status bar, the log, the prompt with hints and completion,
> the help overlay and the dialogs) and every page: [F1 Busk](#f1-busk), to play the show, in
> three layouts, A (console), B (stack) and C (stage), [F2 Program](#f2-program) and
> [F6 Presets](#f6-presets), to build a look, [F4 Cues](#f4-cues) and [F5 Effects](#f5-effects),
> [F7 Masters](#f7-masters), and the rig: [F3 Fixtures](#f3-fixtures), [F8 Patch](#f8-patch)
> and [F9 Surfaces](#f9-surfaces). Their edit modes and panels build a show from controls: the
> rig, groups and park, presets, cues and cue lists, effects and their templates, playbacks and
> pages, and masters. A few things are still typed at the prompt: renumbering a page, the
> options of an effect as it is added, and setting up safety and the show's details.
> F9 puts the start of a binding's line in the prompt.

## Install

The TUI is the optional extra `busk[tui]` ([Textual](https://textual.textualize.io/) 8.2
or later). A development checkout has it already (`uv sync`). Into another environment:

```bash
uv add path/to/busk --extra tui        # or: pip install "path/to/busk[tui]"
```

## Start

```bash
busk-tui club.show                     # or: python -m busk_tui club.show
```

`busk-tui SHOW` runs `busk run SHOW --frontend busk_tui.app:frontend` and becomes that run:
it takes `busk run`'s options and passes them on, and its exit code is the run's. Quitting the
TUI ends the run. The options:

| Option | |
|---|---|
| `--state-dir D`, `--library D` | As for `busk run` ([Running a show](../running.md)). |
| `--values FILE`, `--script FILE`, `--iface IF`, `--no-recover`, `--threads`, `--stats FILE`, `--no-log` | Passed on to `busk run` as they are. A `--script` runs before the TUI opens. |
| `--layout A\|B\|C` | The layout of the F1 page: console, stack (the default) or stage. The one chosen last is remembered. |
| `--faders N` | At most how many of a page's slots F1 shows, 4–20 (default 20). |
| `--colors auto\|256\|16\|truecolor` | The terminal's colours (default: as the terminal says). |
| `--config FILE` | The config file to read (below). |
| `--standalone` | Run the show in the TUI's own process instead of under `busk run` (below). |

`busk run`'s `--console`, `--no-console` and `--duration` make no sense with a full-screen
front end and are not offered.

### `--standalone`: for development and rehearsal

```bash
busk-tui club.show --standalone --no-output
```

`--standalone` runs the show inside the TUI's process, as the library's `busk.LiveShow`
does. It starts faster and takes two options `busk run` lacks: `--no-output` (open no route)
and `--no-surfaces` (open no MIDI, OSC or web surface). It has none of `busk run`'s safety
net: no watchdog, no process isolation, no autosave, no crash recovery and no event log. If
the TUI crashes, the output stops. **For a show, start `busk-tui` without `--standalone`.**

## The screen

```
 busk  show Club Night *  ● sACN·U1  GM 80%  BPM 120.0 ●  FADE 0.0s  PROG 3  BLIND  BLACKOUT  PAGE 1 Main   21:04:23
 F1 Busk  F2 Program  F3 Fixtures  F4 Cues  F5 Effects  F6 Presets  F7 Masters  F8 Patch  F9 Surfaces  F10 Help
 ┌ the page ──────────────────────────────────────────────────────────────────────────────────────────────┐
 ─LOG───────────────────────────────────────────────────────────────────────────────────────────────────────
 busk> sel group 1
       2 targets selected
 busk>                                                                        sel 2 · page 1 · P1 · undo 3
 next: off on    clear | blind on|off | highlight on|off | fade <seconds> | programmer
 F1–F9 pages  F10 ? help  space GO  ← → playback  [ ] fader  PgUp PgDn page  ↑ ↓ history  tab complete …
```

**The status bar**, from the left:

- the show's title, with `*` while it has unsaved edits;
- `ENGINE STALLED`, `ENGINE RESTARTING` or `ENGINE FAILED` (red) while the engine does not
  run, and a dim `ENGINE STARTING` before it first does. Under `busk run` the watchdog
  restarts a stalled or crashed engine, and the chip clears once it runs again. A dim `LATE`
  shows while the engine runs late (its ticks overrun);
- `OUTPUT OFF` (red) after `output off`;
- each output route, `● sACN·U1`: green while it is open (blinking while it sends), red
  when it fails (`busk run` keeps trying), grey when it is disabled or nothing runs the
  output;
- the grand master (amber below 100 %), the first speed master's tempo with a dot that
  flashes on the beat, the programmer's fade time, `PROG` with the number of fixtures in the
  programmer, the `BLIND` and `BLACKOUT` chips (lit when on), the current playback page, and
  the clock.

**The log** shows each line run, with what busk answered:

| | |
|---|---|
| `busk> go 1` | a line you typed |
| ` ui> preset color 3` | a line a control of the UI ran |
| (indented) | busk's answer |
| ` ✗ no playback 99` | busk refused the line |
| ` · …` | news: the TUI's messages, and what busk run would have printed (routes, surfaces, the engine) |
| ` ! …` | a warning |

Performance lines (`go`, `fader`, `gm` …) have no answer: the status bar and the pages show
what they did. A line wider than the log wraps at its words, the later rows under the text.
Scroll the log with the mouse wheel.

**The prompt** runs any console line ([the console](../console.md)), and keeps working
whatever the rest of the screen does. Its right side shows the selection, the page, the
selected playback (`P1`: the one Space and `[ ]` act on) and how many steps `undo` can take back; while a long line runs (`save`, a
`source`d script), `⧗ save 1.4s`. Performance lines and the UI's controls do not wait for it.

**The hint row** under it says what may come where the cursor is (`next: off on`, `<a
fixture number>`, `<Enter>`), or the mistake that stops the line (`error: no fixture 999`),
then the matching forms of `help`. With the mouse on some controls, it says what is there
instead: F8's DMX cells, F6's `[merge]` and its neighbours.

## Keys

The prompt always has the keyboard. The page keys work whatever is typed; the others act
on the prompt or, where noted, only when it is empty.

| Key | |
|---|---|
| F1–F9 (Alt+1–9) | Switch page. Over SSH, where F-keys may not arrive, use Alt+digit. |
| F10 (Alt+0), `?` on an empty prompt | Open or close help: busk's `help` and the keys. |
| Enter | Run the line. |
| ↑ ↓ | Earlier and later lines. |
| Tab | Complete the word at the cursor. With several candidates it completes what they share and lists them in the log. |
| Tab on an empty prompt | Move into the page: ↑ ↓ (or ← →) choose an item, Enter takes it, Esc or any typed key comes back. A button runs its line and the cursor stays on it, so Enter again taps again; a bar puts its line in the prompt (`master "FX" `) to finish with a level. |
| Space on an empty prompt | `go N` on the selected playback. |
| ← → on an empty prompt | Select the previous or next playback of the page shown on F1 (F4 shows its cue list). |
| `[` `]` on an empty prompt | The selected playback's fader 5 % down or up (`fader N 55%`). |
| PgUp PgDn on an empty prompt | `page prev`, `page next`. While help is open, they scroll it. |
| Esc | Close help, else leave the page, else clear the line. |
| Ctrl+C | Clear the line; on an empty prompt, twice in a row, quit. |
| Ctrl+Q | Quit. |

Typing `help` opens the help overlay with busk's answer. The prompt stays usable while help
is open.

## F1 Busk

The performance page: the playbacks of busk's current page, with the tempo, the masters and
the selection beside them. It has three layouts, which show the same playbacks and run the
same lines: **B, the stack** (the default, below), **A, the console** (vertical faders under
the rig's live output) and **C, the stage** (the rig from above, in its live colours). Click
one in the header (`layout A console B stack C stage`), or start with `--layout A`; the TUI
remembers the one you chose last. The pane cursor stops on the three after the page's other
controls. `[edit]`, at the right of the header, opens [edit mode](#edit-mode-and-the-playback-panel).

```
 page 1 Main · slots 1–13 · sel 101 thru 102                                     layout   A console    B stack    C stage   [edit]

 ┌─ PLAYBACKS ────────────────────────────────────────────────────────────────────────────┐┌─ TEMPO · Speed 1 ────────────────────┐
 │ #   name            level                         cue → next                           ││ ▀█  ▀▀█ █▀█   █▀█  ● ● ● ●           │
 │ P1  Warm            ████████████████████░░░░░  80 —/1 → Warm        [TG] [FL] [RL]     ││  █  █▀▀ █ █   █ █                    │
 │ P2  Cool            ░░░░░░░░░░░░░░░░░░░░░░░░░   0 —/1 → Cool        [TG] [FL] [RL]     ││ ▀▀▀ ▀▀▀ ▀▀▀ ▀ ▀▀▀  [TAP] [−] [+]     │
 │ …                                                                                      │└──────────────────────────────────────┘
 │ P8  Panic no fader  ░░░░░░░░░░░░░░░░░░░░░░░░░   — —/1 → Panic       [TG] [FL] [RL]     │┌─ MASTERS ────────────────────────────┐
 │ P9  Song            █████████████████▌░░░░░░░  70 3/5 Pre → Chorus  [GO] [◂] [RL] [GT] ││ GM       ██████████████████████  100 │
 │ P10 Chase           ████████████▌░░░░░░░░░░░░  50 chase 4 Cue 4 bp… [TG] [FL]          ││ FX       ██████████████████████  100 │
 │ P11 Circle size     █████████████████████████ 100 1/1 Circle        [TG] [FL]          ││ Wash lev…██████████████████████  100 │
 │ P12 Pulse size      ░░░░░░░░░░░░░░░░░░░░░░░░░   0 —/1 → Pulse       [TG] [FL]          ││                           [BLACKOUT] │
 │ P13 Bar wave size   ░░░░░░░░░░░░░░░░░░░░░░░░░   0 —/1 → Bar wave    [TG] [FL]          │└──────────────────────────────────────┘
 └────────────────────────────────────────────────────────────────────────────────────────┘┌─ EFFECTS ────────────────────────────┐
                                                                                           │ P11 fx1   Circle ██▇▇▅▃▂▁▁▂▃▄▇ [RUN] │
                                                                                           └──────────────────────────────────────┘
```

**Which playbacks.** One row per slot of the page busk is on (`page 1 Main`), as many as
`--faders` allows; a show with no pages lists its playbacks by number. An empty slot shows
`·` and `—`. PgUp and PgDn (on an empty prompt) change the page, as `page next` does.

**A row** is the playback's number and name (with `size`, `rate`, `xfade`, `temp` or `no
fader` when its fader is not a level), its fader level as a bar in the colour of its current
cue (else its `uiColor`, else white), the level, and where it is: `2/5 Verse → Pre` (the cue
and the next one), `—/5 → Intro` while it is idle, `chase 4 Cue 3 bpm x 1 bounce` for a
chase. A name in white is a playback that runs; the level turns amber while it releases.

- Click or drag the bar to set the fader (`fader 9 72%`, logged once, when you let go); the
  mouse wheel steps it 5 % (not logged).
- The buttons at the end of the row are the playback's own, one for each entry of its `buttons`,
  in order: `[GO]` go, `[◂]` back, `[GT]` goto, `[TG]` toggle, `[RL]` release, `[SL]` select,
  `[FL]` flash, `[SW]` swop and `[—]` none. The hint row names the one under the mouse. A click
  runs `button N B on`, counting from 1, so a `none` keeps its place. GO leaves the fader where it
  is. A button that would do nothing is grey, and the hint row says why: `[—]`, a `[GT]` with
  no goto cue or with one its list lacks (`goto: cue list 11 has no cue 4`, after the playback
  moved to another list), and `[GO]` or `[TG]` on a list with no cues.
- `[FL]` and `[SW]` are held while the mouse button is down on them: `button N B on`, then `button
  N B off`. They are lit while a flash is held on the playback, from here or from a surface. A
  strip that goes while one is held (another page, say) lets go of it.
- `[record]`, on an empty slot, records the programmer as a new playback there (`record slot
  2.7`). It is grey while the programmer has nothing to record.
- Space runs `go` on the selected playback whatever buttons it has.
- A click on `P9` (or the name) selects the playback for Space and `[ ]`; it is drawn on a
  lighter row, and the prompt says `P9`. ← → select the next one; after a page change the
  selection moves to the playback in the same slot.

**TEMPO** is the show's first speed master: its BPM, the beat (the first of four in magenta),
`[TAP]` (`tap "Speed 1"`), and `[−]` `[+]` (`bpm "Speed 1" 119`). **MASTERS** has the grand
master (GM), size masters (green) and group masters (amber) as bars to click or drag (`gm
80%`, `master "FX" 60%`), and `[BLACKOUT]`, which turns blackout on, and off again while it
is lit. **EFFECTS** lists the effects that run: a playback's (`P11 fx1`) and the
programmer's (`prog fx5`), each with its template, its next cycle as a wave (in its colours
for a colour cycle), and `[RUN]` (dimmed while it fades in or out) or `[off]`. On a playback's
effect, `[RUN]` releases the playback (`release 11`): GO on it brings the effect back. On a
programmer effect it runs `effect stop fx5`, and `[off]` runs `effect run fx5`.
**SELECTION** shows the selection (`101 thru 102, 301.3`), a button per group (`sel group
2`; Shift-click adds the group, `sel + group 2`) and a chip per colour preset (`preset color
1`; a preset with more than one colour is a grey `░░`).

Below 100 columns the right column goes under the playbacks.

### Edit mode and the PLAYBACK panel

`[edit]`, at the right of the header, turns edit mode on (`[edit ●]`), in any layout. A grid of the
page's slots and the PLAYBACK panel take the layout's place until `[done]`, at the end of the panel,
or `[edit ●]` again. Nothing on the grid performs: a click selects a playback, and takes its slot
in hand.

```
 page 1 Main · slots 1–13 · sel none                                       layout   A console    B stack    C stage   [edit ●]

 ┌─ SLOTS · page 1 Main ──────────────────────────────────────────────────────┐ ┌─ PLAYBACK · P9 Song ─────────────────────────────┐
 │ [1 Main] [2 Washes] [+ page…]                                              │ │ [rename…] [number…] [delete]                     │
 │ page 1 Main [rename…] [delete]                                             │ │                                                  │
 │                                                                            │ │ cue list     9 Song            [list…]           │
 │ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐    │ │ buttons      go back release   [buttons…]        │
 │ │ 1          P1 │ │ 2          P2 │ │ 3          P3 │ │ 4          P4 │    │ │              goto                                │
 │ │ Warm          │ │ Cool          │ │ Blue          │ │ Red           │    │ │ fader        [master] [crossfade] [rate] [size]  │
 │ └───────────────┘ └───────────────┘ └───────────────┘ └───────────────┘    │ │              [temp] [none]                       │
 │ …                                                                          │ │ band         50                [band…]           │
 │                                                                            │ │ exclusive    base              [key…] [none]     │
 │ slot 9 · P9 Song [place…] [clear]                                          │ │ flash level  100%              [level…]          │
 └────────────────────────────────────────────────────────────────────────────┘ │ flash LTP    [on] [off]                          │
                                                                                │ flash boost  none              [boost…]          │
                                                                                │ LTP mode     [followFader] [threshold]           │
                                                                                │              [ignoreFader]                       │
                                                                                │ threshold    2%                [level…]          │
                                                                                │ auto start   [on] [off]                          │
                                                                                │ auto release [on] [off]                          │
                                                                                │ goto cue     4                 [goto…] [none]    │
                                                                                │ swop protect [on] [off]                          │
                                                                                │ release      3 s               [time…]           │
                                                                                │ colour       none              [colour…]         │
                                                                                │                                                  │
                                                                                │ [done]                                           │
                                                                                └──────────────────────────────────────────────────┘
```

**The grid** has a tile for every slot of the page F1 is on, past `--faders` too, and one empty tile
past the last, since a page has only the slots that were ever filled, and a new one has none. A show
with no pages has its playbacks by number. PgUp and PgDn change the page, as they do outside edit
mode. ← → reach every playback of the grid, and a change of the page's slots keeps a selection past
`--faders`. `[done]` gives back the first `--faders` slots, so a selection past them moves to the
first playback, as it does when its slot goes.

**The pages** are the tabs over the grid. A click goes to that page (`page 2`), as PgUp does, for the
surfaces too. `[+ page…]` adds one (`page add 3 "Encore"`), and F1 stays on the page it was on. The
row under the tabs is the page shown: `[rename…]` (`rename page 2 "Washes"`) and `[delete]` (`delete
page 2 cascade`, after busk's question). A page's playbacks stay when it goes, and the bindings that
go to it by number go with it. Delete the page shown and the engine moves to the next one, else the
last. With no pages left, F1 has the playbacks by number, and `[+ page…]` is the way back.

**The slot in hand** is the last tile clicked, drawn in magenta, and the row under the grid is about
it. ← → take the selected playback's slot in hand. An empty slot stays in hand until another click.

| Slot | Control | Line |
|---|---|---|
| empty | `[new playback…]`: a cue list, then a number and a name, which starts as the list's | `playback add 30 cuelist 9 at 2.7 "Encore"`, one undo step. The new one is selected. Grey on a show with no cue list |
| empty or full | `[place…]`: a picker of the playbacks, each with the slots it sits on | `page 2 slot 7 playback 9`, over what the slot held, which stays in the show. A playback can sit on any number of slots |
| full | `[clear]` | `page 2 slot 7 clear`. The playback stays in the show |

**The panel** shows the selected playback: click a tile, or use ← → on an empty prompt. Each
setting is one control and one line, so one undo step. A value left as it was sends nothing.

| Row | Control | Line |
|---|---|---|
| `[rename…]`, `[number…]` | a dialog each | `rename playback 9 "Song"`, `playback 9 number 30`. The selection follows the number |
| `[delete]` | busk's question, which names the pages it leaves and says if it runs | `delete playback 9 cascade`. Its slots go empty; its cue list, and the bindings by slot, stay |
| cue list | `[list…]`, a picker | `playback 9 cuelist 11`. Grey while the playback runs, and the panel says why: release it first |
| buttons | `[buttons…]`: the functions as words, in order, a space between | `playback 9 buttons ["go", "flash"]`. No words: no buttons. `none` keeps a place |
| fader | a chip each | `playback 9 fader size` |
| band | `[band…]`, a whole number, of any sign | `playback 9 priority 70` |
| exclusive | `[key…]`, `[none]` | `playback 9 exclusivity "wash"`, `playback 9 exclusivity none` |
| flash level | `[level…]`, in percent | `playback 9 flash.level 0.75` |
| flash LTP | `[on]`, `[off]` | `playback 9 flash.includeLtp false` |
| flash boost | `[boost…]`, `[none]` | `playback 9 flash.priorityBoost 5` |
| LTP mode | a chip each | `playback 9 ltpFaderMode followFader` |
| threshold | `[level…]`, in percent | `playback 9 ltpThreshold 0.05` |
| auto start, auto release | `[on]`, `[off]` | `playback 9 autoStart false` |
| goto cue | `[goto…]`, a cue of its list, `[none]` | `playback 9 goto 4`, `playback 9 gotoCue none` |
| swop protect | `[on]`, `[off]` | `playback 9 protectFromSwop true` |
| release | `[time…]`, in seconds | `playback 9 releaseTime 2` |
| colour | `[colour…]`, as `#rrggbb`, `[none]` | `playback 9 uiColor "#ff8000"` |

`[none]` shows on what has a value to take away. Changing the cue list leaves a goto cue the new
list lacks: busk warns in the log, `[GT]` is grey until the list has that cue, and `[goto…]`
sets another.

The F-keys, the prompt and `undo` work as anywhere, and so do Space, `[ ]` and the other keys of an
empty prompt: they act on the selected playback as they do on every page. The pane cursor stops on
the tabs, the page's controls, each tile (Enter takes it in hand and selects its playback), the
slot's controls, the panel's controls, `[done]`, the layouts and `[edit]`. Below 100 columns the
panel goes under the grid, and a click on a tile scrolls to the slot's row and the panel under it.

### Layout A: console

```
 page 1 Main · slots 1–13 · sel 101 thru 102                                                                layout   A console    B stack    C stage

 ┌─ OUTPUT · 7 fixtures · click selects, Shift-click adds ────────────────────────────────────────┐┌─ PROGRAMMER ───────────────────────────────────┐
 │ PARS     ███ ███ ███ ███                                                                       ││ sel 101 thru 102 (2)                           │
 │          201 202 203 204                                                                       ││ programmer empty                               │
 │                                                                                                ││                                                │
 │ SPOTS    ███ ███                                                                               ││ color ██ ██ ██ ██                              │
 │          101 102                                                                               ││                                                │
 │                                                                                                ││ GM       ████████████████████████████████  100 │
 │ PIXELS   ████████████                                                                          ││ FX       ████████████████████████████████  100 │
 │              301                                                                               ││ Wash lev…████████████████████████████████  100 │
 └────────────────────────────────────────────────────────────────────────────────────────────────┘│                                                │
                                                                                                   │ Speed 1 120.0 ● ● ● ●             [TAP] [B.O.] │
                                                                                                   └────────────────────────────────────────────────┘
 ┌─ PLAYBACKS ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ ┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌──────────┐ │
 │ │   P1    ││   P2    ││   P3    ││   P4    ││   P5    ││   P6    ││   P7    ││   P8    ││   P9    ││   P10   ││   P11   ││   P12   ││   P13    │ │
 │ │  Warm   ││  Cool   ││  Blue   ││   Red   ││  Green  ││Audience ││ Centre  ││  Panic  ││  Song   ││  Chase  ││ Circle  ││  Pulse  ││ Bar wave │ │
 │ │   1/1   ││   —/1   ││   —/1   ││   —/1   ││   —/1   ││   —/1   ││   —/1   ││   —/1   ││   —/5   ││ chase 4 ││   1/1   ││   —/1   ││   —/1    │ │
 │ │  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ████   ││  ░░░░   ││   ░░░░   │ │
 │ │  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ████   ││  ░░░░   ││   ░░░░   │ │
 │ │  ████   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ████   ││  ░░░░   ││   ░░░░   │ │
 │ │  ████   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ████   ││  ░░░░   ││   ░░░░   │ │
 │ │  ████   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ████   ││  ░░░░   ││   ░░░░   │ │
 │ │  ████   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ████   ││  ████   ││  ░░░░   ││   ░░░░   │ │
 │ │  ████   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ████   ││  ████   ││  ░░░░   ││   ░░░░   │ │
 │ │  ████   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ████   ││  ████   ││  ░░░░   ││   ░░░░   │ │
 │ │  ████   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ████   ││  ████   ││  ░░░░   ││   ░░░░   │ │
 │ │  ████   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ░░░░   ││  ████   ││  ████   ││  ░░░░   ││   ░░░░   │ │
 │ │   80    ││    0    ││    0    ││    0    ││    0    ││    0    ││    0    ││    —    ││    0    ││   50    ││100 size ││ 0 size  ││  0 size  │ │
 │ │[TG][FL] ││[TG][FL] ││[TG][FL] ││[TG][FL] ││[TG][FL] ││[TG][FL] ││[TG][FL] ││[TG][FL] ││[GO][◂]  ││[TG][FL] ││[TG][FL] ││[TG][FL] ││ [TG][FL] │ │
 │ │  [RL]   ││  [RL]   ││  [RL]   ││  [RL]   ││  [RL]   ││  [RL]   ││  [RL]   ││  [RL]   ││[RL][GT] ││         ││         ││         ││          │ │
 │ └─────────┘└─────────┘└─────────┘└─────────┘└─────────┘└─────────┘└─────────┘└─────────┘└─────────┘└─────────┘└─────────┘└─────────┘└──────────┘ │
 └──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**OUTPUT** has a row per fixture type (the profile's category: PARS, SPOTS, WASHES, PIXELS,
STROBES …; a profile with no category has a row of its own, named after it), and each
fixture in it in what busk outputs now: its colour at its intensity, after the masters,
blackout, park and limits (dark when it is out). A fixture of one element is `███`, one of
several a `█` per element. The number under it is cyan while the fixture is selected, on a
lighter background. A click selects the fixture (`sel fixture 201`); Shift-click adds it or
takes it out (`sel + fixture 201`, `sel - fixture 201`).

**PROGRAMMER** shows the selection, what the programmer holds (`2 fixtures · intensity color
pan`, its effects, and `BLIND` while blind is on), the colour chips, the bars of the grand,
size and group masters, and the tempo row: the first speed master's BPM and beat, `[TAP]`
and `[B.O.]` (blackout on, and off again while it is lit).

**PLAYBACKS** is a column per slot, as many to a line as fit: the number, the name, where it
is in its list (`2/5`, `chase 4`, `—/5` while idle), its fader (ten rows, in the colour of
its current cue), the level (with `size`, `rate`, `xfade` or `temp` when the fader is not a
level) and its own buttons, two to a line, as in [layout B](#f1-busk). Click or drag the fader to
set it (logged once, when you let go), or use the wheel (5 %, not logged).
The selected playback has a cyan border. Below 100 columns PROGRAMMER goes under OUTPUT.

### Layout C: stage

```
 page 1 Main · slots 1–13 · sel 101 thru 102                                                                layout   A console    B stack    C stage

 ┌─ STAGE · click selects, Shift-click adds ────────────────────────────────────────────────────────────────┐┌─ PLAYBACKS ──────────────────────────┐
 │ y -1.0    ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄   ◆   ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄   ◆   ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄ ││ P1  Warm         ███████▎░  80  [TG] │
 │ z 5.0                       101                                                    102                   ││ P2  Cool         ░░░░░░░░░   0  [TG] │
 │                            ↑ 10°                                                  ↑ 1°                   ││ P3  Blue         ░░░░░░░░░   0  [TG] │
 │                                                                                                          ││ P4  Red          ░░░░░░░░░   0  [TG] │
 │ y 1.0     ┄┄┄┄ ■ ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄ ■ ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄ ■ ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄ ■ ┄┄┄┄┄ ││ P5  Green        ░░░░░░░░░   0  [TG] │
 │ z 4.0         201                         202                        203                        204      ││ P6  Audience     ░░░░░░░░░   0  [TG] │
 │                                                                                                          ││ P7  Centre       ░░░░░░░░░   0  [TG] │
 │           · · · · · · · · · · · · · · · · · · · · ·  AUDIENCE  · · · · · · · · · · · · · · · · · · · · · ││ P8  Panic no fa… ░░░░░░░░░   —  [TG] │
 │                                                                                                          ││ P9  Song         ░░░░░░░░░   0  [GO] │
 │ no place  ████████████                                                                                   ││ P10 Chase        ████▌░░░░  50  [TG] │
 │               301                                                                                        ││ P11 Circle size  █████████ 100  [TG] │
 │                                                                                                          ││ P12 Pulse size   ░░░░░░░░░   0  [TG] │
 │ place fixture 101 Spot 101 [location…]                                                                   ││ P13 Bar wave si… ░░░░░░░░░   0  [TG] │
 └──────────────────────────────────────────────────────────────────────────────────────────────────────────┘└──────────────────────────────────────┘
                                                                                                             ┌─ MASTERS ────────────────────────────┐
                                                                                                             │ GM       ██████████████████████  100 │
                                                                                                             │ FX       ██████████████████████  100 │
                                                                                                             │ Wash lev…██████████████████████  100 │
                                                                                                             │                                      │
                                                                                                             │ Speed 1 120.0 ● ● ● ●   [TAP] [B.O.] │
                                                                                                             └──────────────────────────────────────┘
```

**STAGE** draws the fixtures where they hang, from above, with the audience at the bottom.
busk places a fixture with its `location` (`fixture 101 location {"x": -2, "y": -1, "z": 5,
"rx": 0, "ry": 0, "rz": 0}`, in metres: x to the right, y towards the audience, z up). A row
is the fixtures at one depth and height (to 0.1 m), labelled `y` over `z`: upstage at the
top, and the higher first at the same depth (a truss above the floor). Along a row each
fixture is at its x, on one scale for every row, so fixtures one above the other on stage
are one above the other here; fixtures too close to fit are pushed apart, in order.

A fixture is its type's glyph (`■` par, `◆` spot, `●` wash, `▲` strobe, `◇` others) in its
live colour and intensity, or a `█` per element, its number under it (cyan while selected).
A fixture with pan or tilt also shows them: the pan as an arrow (`↑` at 0°, `→` at 90°,
clockwise: the angle from the fixture's home, not a direction on stage) and the tilt in
degrees. Fixtures without a place are under AUDIENCE, in a `no place` row. `[location…]`
opens the form F3 uses, of the six values (`x`, `y`, `z` in metres, `rx`, `ry`, `rz` in degrees),
starting at the fixture's place when it has one, for the first selected fixture (else the first
without a place): select a fixture, click it, type its place. Clicks select as in OUTPUT.

The right column has the playbacks as compact rows (the first of their buttons only), MASTERS
with the tempo row, and QUICK (the group buttons and colour chips). Below 100 columns it goes
under the stage.

## F2 Program

Select fixtures, set their attributes, apply presets, and see what the programmer holds.

```
 ┌─ SELECTION ────────────────────────────────────────────────────────────────────────────────────┐
 │ 101 thru 102 (2 · encoders show 101)                                                           │
 │ [1 Heads] [2 Washes] [3 Bar] [4 All] [none]                                                    │
 └────────────────────────────────────────────────────────────────────────────────────────────────┘
 ┌─ INTENSITY ─────────────────────────────┐ ┌─ POSITION ──────────────────────────────┐ ┌─ COLOR …
 │ intensity  [−] █████████░░░░░░░░ [+] 50% │ │ pan   [−] ███████▉░░░░░░░░░░░ [+]  -45° │ │ color.r …
 └─────────────────────────────────────────┘ │ tilt  [−] █████████▌░░░░░░░░░ [+]    0° │ │ …
 quick [set intensity spread 0 to 1] [set pan spread -90 to 90] … [highlight on] [blind on] [fade 0s…]
 ┌─ PROGRAMMER CONTENTS · 2 fixtures ─────────────────────────────────────────────────────────────┐
 │ #    name          intensity colour            pan     tilt    zoom    other                   │
 │ 101  Spot 101      50%       ██ Red            -45°    ·       ·                               │
```

**SELECTION** shows the selection as you would type it (`101 thru 104, 301.2`), how many
elements it has, and which one the encoders show: the first. A button per group runs `sel
group N` (Shift-click adds it, `sel + group N`), and `[none]` runs `sel none`.

**The encoders** are grouped by busk's families: INTENSITY, POSITION (`pan`, `tilt`), COLOR
(`color.r`, `.g`, `.b`, `.w`, `cto`), BEAM (`zoom`, `iris`, `frost`), FOCUS and SHUTTER
(`strobeRate`). A row shows only when a profile of your rig takes its attribute, and is named
as `set` names it. Each shows the first selected element's value: **magenta** when the
programmer holds it (from a preset too), **dim** when it is the output (intensity, pan, tilt
and zoom, after the masters), `—` with neither.

- Click the bar to set the value: `set pan -45`, `set intensity 72%`. Pan, tilt, zoom and the
  strobe rate span the first selected fixture's range (its profile's). What you set shows at
  once, before busk has run it.
- Drag the bar for a live change: it sends a `set` about ten times a second and logs the last
  one when you let go. **Each of those lines is an undo step of its own** until busk can
  group a gesture into one (GAP-06 of the engine's gap list), so `undo` after a drag goes
  back one step of it at a time. A click is one step.
- `[−]` `[+]` step the value by 5 % (15° for pan and tilt) with `set intensity by 5%`, and the
  mouse wheel by 2 % (5°), not logged. busk changes only what the programmer holds, so the
  steps act only while the programmer holds the attribute for a selected element; elsewhere
  they are grey: click the bar or apply a preset first.
- A colour component (`color.r` …) changes the colour the programmer holds, so its bar, too,
  works once there is one: click a colour chip under the rows (`preset color 2`) or type
  `set color 1 0.5 0`. The COLOR panel shows the output's colour and the programmer's as
  swatches. `[set color…]` and SHUTTER's `[set shutter…]` put the line in the prompt.
- A click on a row's name puts `set <attribute> ` in the prompt.

**quick** runs ready-made lines (set them in the config file, below), then `[highlight
on|off]` and `[blind on|off]`, which follow the programmer and are lit while on, and
`[fade 0s…]`, which puts `fade ` in the prompt.

**PROGRAMMER CONTENTS** has a row per fixture the programmer holds a value for: intensity, the
colour as a swatch and its components, pan, tilt, zoom, and the other attributes it holds. A
value from a preset shows the preset's name; a fixture whose elements differ shows `mixed`;
`·` is an attribute it does not hold.

With the pane cursor (Tab on an empty prompt), a row's name puts its `set` in the prompt and
`[−]` `[+]` run their step, so Enter Enter Enter steps the value. Below 100 columns the
panels go one under the other.

## F3 Fixtures

Every fixture, with its patch and what it outputs now. `[edit]` opens the FIXTURE panel, which
changes any of them, and `[+ add]` adds new ones.

```
 7 fixtures · 2 selected · click selects, Shift-click adds                                                           [+ add] [edit]

 ┌─ FIXTURES ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │      # name                   profile                 type   mode      patch   intensity colour         pan  tilt zoom src     │
 │    101 Spot 101               Generic Spot 16ch       spot   16ch      1.1           64% ██              0°    0°  21° P1      │
 │    102 Spot 102               Generic Spot 16ch       spot   16ch      1.17          64% ██              0°    0°  21° P1      │
 │ ▸  201 LED ML-56 RGBW 36x3W … Eurolite LED ML-56 RGBW par    4-channel 1.33          40% ██                            prog    │
 │ ▸  202 LED ML-56 RGBW 36x3W … Eurolite LED ML-56 RGBW par    4-channel 1.37          40% ██                            prog    │
 │    203 LED ML-56 RGBW 36x3W … Eurolite LED ML-56 RGBW par    4-channel 1.41          64% ██                            P1      │
 │    204 LED ML-56 RGBW 36x3W … Eurolite LED ML-56 RGBW par    4-channel 1.45           0% ██                            park    │
 │    301 COLORband PiX 301      Chauvet DJ COLORband P… pixel  36-CH     1.49          50% ████████████                  P1      │
 │                                                                                                                                │
 │ ■ park   ■ programmer   ■ playback   ■ effect   ■ nothing   — unpatched   ▸ selected                                           │
 └────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**A row** is a fixture: `▸` while it is selected (its row lighter), its number, name,
profile (`×12` for a fixture of twelve elements), type (the profile's category: `par`,
`spot`, `wash`, `pixel` …), mode and patch (`1.49`; a red `—` while it is not patched). Then
what busk outputs for it now, after the masters, blackout, park and limits:

- `intensity`: what it emits, `8–50%` while its elements differ;
- `colour`: one swatch per element (twelve at most) in its colour at its intensity; dark when
  it is out;
- `pan`, `tilt` and `zoom` in degrees, on fixtures that have them (before the fixture's
  orientation);
- `src`: what drives its intensity: `park` (a parked value holds it), `prog` (the programmer),
  `P9` (playback 9's cue), `fx P13` (an effect of playback 13's cue), `fx` (a programmer
  effect), `—` (nothing).

The values are coloured by what drives them: amber park, magenta the programmer, white a
playback, green an effect, grey nothing (the intensity and `src` by what drives the intensity,
pan and tilt by what drives the position, zoom by the beam's). Park comes first, whatever else
drives the value, as busk outputs it, and one parked element is enough for the fixture.

A click on a row selects the fixture (`sel fixture 101`); Shift-click adds it to the
selection, or takes it out when it is in (`sel + fixture 101`, `sel - fixture 101`). The pane
cursor stops on `[+ add]`, `[edit]` and each row (Enter selects it, and the cursor stays).

### Edit mode and the FIXTURE panel

`[edit]`, at the right of the header, turns edit mode on (`[edit ●]`), and `[done]`, at the end
of the panel, turns it off. The live columns give way to the rig's, and the page stops reading
the output: `limits` says what the fixture limits (`tilt`, `pan tilt`, `int`), and `place`
whether it has a location (`●`, else `·`). A click still selects, and the panel shows the
fixture clicked last, whose number is lit: several selected rows look alike. The
[GROUPS](#groups) panel is under the table.

```
 7 fixtures · 2 selected · click chooses, Shift-click adds to the selection                                        [+ add] [edit ●]

 ┌─ FIXTURES ────────────────────────────────────────────────────────────────┐ ┌─ FIXTURE · 102 Spot 102 ─────────────────────────┐
 │      # name          profile         mode      patch   limits       place │ │ [rename…] [number…] [delete 101 thru 102]        │
 │ ▸  101 Spot 101      Generic Spot 1… 16ch      1.1     tilt         ·     │ │                                                  │
 │ ▸  102 Spot 102      Generic Spot 1… 16ch      1.17    tilt         ·     │ │ Generic Spot 16ch · 16ch · 16 channels           │
 │    201 LED ML-56 RG… Eurolite LED M… 4-channel 1.33                 ·     │ │ [profile…] [update profile]                      │
 │    202 LED ML-56 RG… Eurolite LED M… 4-channel 1.37                 ·     │ │                                                  │
 │    203 LED ML-56 RG… Eurolite LED M… 4-channel 1.41                 ·     │ │ category of 2 fixtures                           │
 │    204 LED ML-56 RG… Eurolite LED M… 4-channel 1.45                 ·     │ │ [par] [spot] [wash] [pixel] [strobe] [beam]      │
 │    301 COLORband Pi… Chauvet DJ COL… 36-CH     1.49    int          ·     │ │ [blinder] [dimmer] [effect] [fog] [other] [none] │
 └───────────────────────────────────────────────────────────────────────────┘ │                                                  │
                                                                               │ PATCH · 101 thru 102 (2) · 1.1–1.32              │
 ┌─ GROUPS ──────────────────────────────────────────────────────────────────┐ │ universe [none] [1 Stage]                        │
 │ 4 groups · click chooses, and keeps the selection              [record…]  │ │ address  1 [address…] [next free]                │
 │    # name             members                                             │ │ takes 1.1–1.32 · free                            │
 │    1 Heads            101 thru 102                                        │ │ [patch]                                          │
 │    2 Washes           201 thru 204                                        │ │                                                  │
 │    3 Bar              301                                                 │ │ LIMITS · 101 thru 102 (2)                        │
 │    4 All              101 thru 102, 201 thru 204, 301                     │ │ pan         none               [limit…]          │
 │                                                                           │ │ tilt        -90° to 10°        [limit…] [none]   │
 │ group 4 All [rename…] [number…] [delete]                                  │ │ intensity   none               [limit…]          │
 │ selection 101 thru 102 [merge] [replace] [remove]                         │ │ [no limits]                                      │
 └───────────────────────────────────────────────────────────────────────────┘ │                                                  │
                                                                               │ PARK · 101 thru 102                              │
                                                                               │ nothing parked                                   │
                                                                               │ [park…]                                          │
                                                                               │                                                  │
                                                                               │ ORIENTATION · 101 thru 102 (2)                   │
                                                                               │ [invert pan] [invert tilt] [swap pan/tilt]       │
                                                                               │ pan offset  0°                 [offset…]         │
                                                                               │ tilt offset 0°                 [offset…]         │
                                                                               │                                                  │
                                                                               │ LOCATION no place                                │
                                                                               │ [location…]                                      │
                                                                               │                                                  │
                                                                               │ [done]                                           │
                                                                               └──────────────────────────────────────────────────┘
```

What a control sends is echoed `ui>` in the log with busk's answer. A chip already lit sends
nothing. From the top:

- `[rename…]` and `[number…]`, each a dialog, then one line (`rename fixture 102 "…"`, `fixture
  102 number 150`). The number dialog lists the numbers taken and refuses them, and the panel
  follows the fixture to its new number.
- `[delete]` sends `delete fixture 102 cascade`, after busk's question, which says what goes:
  `Delete fixture 501? It leaves groups 4, 5. The programmer holds it.` The fixture leaves every
  group, preset, cue, park entry and binding that names it. A cue entry, a cue effect, a release
  or a binding left with no target goes with it. A group, preset or cue left empty stays, for you
  to keep or delete. One `undo` brings it all back. With a run selected (see below), it reads
  `[delete 101 thru 102]` and sends `delete fixture 101 thru 102 cascade`: one question, one line
  and one `undo` for them all.
- **What it is:** its profile, mode and channels. With several modes, a chip per mode sends
  `fixture 102 mode "8ch"`. `[profile…]` opens the [picker](#questions-dialogs-and-quitting). The
  panel then shows what the fixture would become (`to RGB Par 3ch · 3 channels`), that profile's
  mode chips, `[change]` and `[cancel]`. `[change]` sends `fixture 102 profile "RGB Par 3ch" mode
  "3ch"`, and a library profile comes into the show with it. busk refuses a mode that would run
  past channel 512, or that loses elements a group, preset or cue uses, and an overlap is a
  warning in the log. `[update profile]` is grey unless the library holds the profile at another
  revision than the show's copy. Then it sends `profile update "Generic Spot 16ch"`, which brings
  the library's revision to every fixture of the profile, as one `undo` step. busk refuses it
  while a fixture runs a mode that revision lacks.
- **category:** a chip per word, the profile's lit (`profile "Generic Spot 16ch" category wash`).
  It belongs to the profile: `category of 2 fixtures` says how many it changes.
- **PATCH**, where the fixture is, then where to put it. Nothing goes until `[patch]`, which sends
  `fixture 102 patch 1.85`, or `fixture 102 patch none` with `[none]` lit. A universe chip
  proposes its first free run of channels that fits. The chip of the fixture's own universe gives
  back its patch. `[next free]` proposes the first free run outside the fixture's own channels,
  and `[address…]` takes any address. The `takes` line reads the choice: `free`, `overlaps fixture
  301` (amber: busk allows it), or `past channel 512` (red: `[patch]` is grey). With no universe,
  the chips say that F8 adds one. On a run (see below), PATCH places the whole run from its first
  fixture, each after the one before, as `thru` lays them out. Its heading says where the run is
  now (`PATCH · 101 thru 102 (2) · 1.1–1.32`, or `none`, or `not in one block`), the choice
  starts at the first fixture's patch, the run's own channels are free to it, and `[patch]` sends
  `fixture 101 thru 102 patch 1.85`.
- **LIMITS:** a row per limit the fixture can use: `pan` and `tilt` where the profile takes them,
  `intensity` always. `[limit…]` is a form: `from` and `to` in degrees, starting at the limit or
  the profile's range, or for intensity `at most` a level (`50` or `50%`). A limit past the
  profile's range is busk's warning, in the log. `[none]` removes that limit and keeps the others,
  and `[no limits]` removes them all.
- **PARK:** what park holds on the fixture, a line per attribute and value (`intensity 0%`), with
  the elements when it is not all of them (`intensity 0% · 301.2 thru 301.3`), or `nothing
  parked`. `[park…]` is a form of an attribute and a value, starting at `intensity` (or the
  first attribute the fixtures take) and `0`; its note lists the attributes the fixtures'
  profiles take, and it refuses another. The value goes
  as typed, as busk reads it after `set`: `0.5` or `50%`, `-45` in degrees, `1 0 0` for a colour,
  an option's name. busk refuses what it cannot read, in the log. It sends `park fixture 102,
  fixture 301.2 intensity 0`. A parked value holds whatever else drives the attribute, until
  [F7](#f7-masters) unparks it.
- **ORIENTATION**, on a fixture with pan or tilt: `[invert pan]`, `[invert tilt]` and, with both,
  `[swap pan/tilt]`, lit from the fixture, send at once (`fixture 102 orientation.invertPan
  true`). `[offset…]` is a dialog, in degrees.
- **LOCATION:** the six values of its place on stage, or `no place`. `[location…]` is a form of
  the six: `x`, `y`, `z` in metres and `rx`, `ry`, `rz` in degrees, starting at its own.
  `[no place]`, on a fixture with a place, sends `fixture 102 location none`. F1 C draws what
  has a place, and its `[location…]` opens this form.

LIMITS and ORIENTATION act on every selected fixture while the fixture shown is selected, as
their headings say (`LIMITS · 101 thru 102 (2)`). Each goes out as one line per run of the
numbers selected, and each line is one `undo` step: 101 and 102 give `fixture 101 thru 102 limits
tilt -90 10`, and a fixture left out between two selected ones gives two lines, so it stays as it
is. A toggle sets them all to the opposite of the fixture shown, so it also brings those that
differ into line. If a fixture of a run cannot take a line, busk refuses the line, in the log, and
the run stays as it was: `[swap pan/tilt]` does this with a fixture that has pan alone.

`[delete]` and PATCH act on the same fixtures while they are one run, in one line, and are grey
while they are not, since two lines would be two `undo` steps: PATCH then says what `thru` would
take as well (`not one run: thru would take 202 too`). A gap in the numbers does not part a run,
as `thru` takes only the fixtures the show has. PARK acts on the selected elements while the
fixture shown is selected, in one line, so it can hold one pixel of a bar (`PARK · 102, 301.2`),
and on all of the fixture shown otherwise. The rest of the panel acts on the fixture shown alone.

**A new fixture.** `[+ add]`, in or out of edit mode, shows the form in the panel.
[F8's map](#f8-patch) can open it too, at a free channel.

```
┌─ FIXTURE · new ──────────────────────────────────┐
│ profile  [Generic Spot 16ch…]                    │
│ mode     [16ch]                                  │
│ number   [−] 302 [+] [number…]                   │
│ count    [−] 4 [+]  302 thru 305                 │
│                                                  │
│ PATCH                                            │
│ universe [none] [1 Stage]                        │
│ address  85 [address…] [next free]               │
│ takes 1.85–1.148 · free                          │
│                                                  │
│ [add] [done]                                     │
└──────────────────────────────────────────────────┘
```

- `[choose…]` opens the [picker](#questions-dialogs-and-quitting), and the form has no profile
  until you choose one. It keeps that profile from one `[+ add]` to the next.
- With several modes, each chip shows what it takes (`8ch · 8`), and the first is lit.
- `number` starts after the show's highest. `[−]` `[+]` step over what is taken, and `[number…]`
  takes any free number.
- `count` is how many, one after the other. The range shows beside it (`302 thru 305`). A number
  of the range that is taken shows in red, and `[add]` is grey.
- PATCH works as in the panel, for the whole block, and starts at the first free run that fits.
  `[none]` adds the fixtures unpatched.

`[add]` sends `fixture add 302 thru 305 "Generic Spot 16ch" mode "16ch" at 1.85`, and a library
profile comes into the show with it. The form stays, with the next number and the next free
address, since a rig goes in type by type. `[done]` goes back to the panel, and so does a click
on a row.

The pane cursor stops on every control of the panel in reading order, and a row's Enter chooses
it as well as selecting it. The panel is beside the table from 100 columns, and under it below
that; there, a click scrolls down to it.

#### GROUPS

In edit mode, the GROUPS panel is under the table: a row per group, with its number, name and
members as you would select them (`101 thru 102, 301.2`; `—` for a group left with none). A click
on a row chooses the group, which `group 4 All` names under the rows, and sends nothing: the
selection stays as it was. So you can choose a group, then click fixtures in the table, or the
other way round.

- `[record…]` makes a group of the selection: a form of a number (after the highest) and a name,
  then `record group 5 "Floor"`; without a name busk calls it `Group 5`. The new group is chosen.
  It is grey while nothing is selected.
- `[rename…]` and `[number…]`, each a dialog, then one line (`rename group 4 "…"`, `group 4
  number 7`). The panel follows the group to its new number.
- `[delete]` sends `delete group 4 cascade`, after busk's question, which names the cues and
  masters it leaves: the cue entries, effects and releases that target the group go with it, and
  so does its master. One `undo` brings it all back.
- `selection 101 thru 102` says what the three buttons after it take. `[merge]` adds the selected
  elements the group lacks (`record group 4 merge`). `[replace]` makes the selection its members,
  and `[remove]` takes the selected out, each after a question; a group left with no members
  stays. Each is grey while it would change nothing, since busk would still spend an `undo` step
  on it. A new fixture joins a group this way: select it, choose the group, `[merge]`.

The pane cursor stops on `[record…]`, each group, then the chosen group's controls, after the
table's rows and before the FIXTURE panel. Below 100 columns the GROUPS panel comes between the
table and the FIXTURE panel.

## F4 Cues

Every cue list, and the cues of one: go to a cue, record, re-record and delete cues, load a cue
to edit its values, make and delete lists, set a list's tracking and chase, edit a cue's timing,
trigger and name, and move, copy and renumber cues and lists.

```
 ┌─ CUELISTS ─────────────────────────┐┌─ CUELIST 9 · Song ─────────────────────────────────────────────────────────────────────────────────────────┐
 │   # name           kind  cues pb   ││ mode sequence · tracking   playback P9 @ 70%   groups Washes, Heads, Bar, All                              │
 │   1 Warm           seq      1 P1   ││                                                                                                            │
 │   …                                ││   cue    name       time          delay  follow wait   intensity  colour            also          fx       │
 │   9 Song           seq      5 P9   ││   9/1    Intro      3             —      —      —      60%        ██ Blue           —                      │
 │  10 Chase          chase    4 P10  ││   9/2    Verse      2, position 4 —      —      —      70%        ██ 1.00 0.75 0.45 position 2             │
 │   …                                ││ ▶ 9/3    Pre        1/3           —      —      8      100%, 30%  ██ Amber          —                      │
 │  20 Fast pulse     seq      1 P20  ││   9/4    Chorus     0.5/2         —      —      —      100%, 100% ██ 1.00 1.00 1.00 —             rainbow  │
 │                                    ││   9/5    Outro      6             —      4      —      20%        —                 —                      │
 │ [+ list…]                          ││                                                                                                            │
 └────────────────────────────────────┘│ [GO] [BACK] [record cue 9] [cuelist 9 chase bpm x 1]                                                       │
                                       │ list 9 Song [tracking off] [chase…] [rename…] [number…] [delete]                                           │
                                       │ edit cue 9/3 Pre [time…] [delay…] [curve…] [go…] [follow…] [wait…] [rename…] [number…] [copy…] [release…]  │
                                       │                  [record at…] [load] [merge] [replace] [remove] [delete]                                   │
                                       └────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Which list.** F4 shows the cue list of the selected playback, so ← → (on an empty prompt)
step through the lists of the page's playbacks. A click on a list in CUELISTS shows it and
selects the playback that runs it (`pb`), for Space, `[ ]` and the buttons; a list no
playback runs only shows. The meta line says the list's mode (`sequence`, `· tracking`, or
`chase bpm x 1 bounce crossfade 0.25`), the playbacks that run it with their levels, and the
groups and fixtures its cues set.

**A cue row** is the cue as the show stores it: `▶` on the cue the playback is on, `L/C`,
the name, the fade times (`1/3`: in 1 s, out 3 s; a family's own after a comma, `2,
position 4`), the delays, the curve, the delay of an automatic GO under `follow` (after the
cue before has finished) or `wait` (after it has started), and the cue's intensity and colour
entries: a value, a preset's name, `spread`, or `per target` (a value per fixture, as `record
cue` stores a spread), with the colour's swatch. Under `also`, how many entries the cue holds of
each other family, so a cue that only moves the heads does not look empty: `position 2` (a pan
and a tilt), `position 2, beam 1`. A colour wheel, a CTO or a colour macro is a colour entry the
`colour` column does not show, so `also` counts it: `color 1`. Then the ids of its effects.

The table drops columns when it is narrow, the curve first: from 150 columns `also` shows where
the curve was, and `[curve…]` still shows a cue's curve. From 160 columns every column shows;
below 150, neither the curve nor `also`.

- A click on a row goes to that cue: `goto 9 3` on the list's playback (busk's `cue 9/3 go`
  sets the cue's trigger instead). A list no playback runs has no go-to: its rows only
  choose.
- A click on a cue's time, delay, curve, follow or wait chooses the row, without going to
  it, and opens that edit's dialog (see the `edit` row below).
- `[GO]` and `[BACK]` run `go 9` and `back 9`. `[record cue 9]` records the programmer as a
  new cue at the end of the list. The last button switches the list to a chase (`cuelist 9
  chase bpm x 1`, or the chase settings the list had before, every digit and the master's
  name as busk stored them) or back to a sequence (`cuelist 10 sequence`). On a show with
  several speed masters, busk refuses `bpm x 1` for a list that was never a chase: `[chase…]`
  names the master.

**The `list` row** acts on the list shown:

- `[tracking on]` and `[tracking off]` send `cuelist 9 tracking true` and `false`.
- `[chase…]` opens a form: the rate in Hz or on a speed master's beat (which master, when the
  show has several, and a multiplier), the direction and the crossfade. It starts at the
  settings the list keeps. Sending it makes the list a chase: `cuelist 9 chase hz 2 bounce
  crossfade 0.5`, one undo step.
- `[rename…]` is a name dialog.
- `[number…]` asks for a number no other list has: `cuelist 9 number 30`. The list stays shown,
  on the cue it was on.
- `[delete]` sends `delete cuelist 9 cascade`, after busk's question, which names the playbacks
  that go with the list and the pages they leave, and says when one is running: `Delete cue list
  9 "Song" and playback 9? It leaves pages 1, 2.` One `undo` brings it all back.

`[+ list…]`, under CUELISTS, asks for a number and a name (`cuelist add 30 "Encore"`), refuses a
number that is taken, and shows the new list.

**The `edit` row** acts on the chosen cue: the row clicked last, else the one the playback is
on. Each dialog is filled in with what the cue holds, sends one line, and sends nothing when it is
left as it was:

- `[time…]` has the fade in and out: `cue 9/3 time 1/3` (`cue 9/3 time 2` when they are the
  same). `in` times intensity rising and every family without its own, `out` intensity falling.
  The `for` chips choose a family instead, for its own fade and delay, which start at what the
  family takes now: `cue 9/3 time position 4 delay 1`, which F4 then shows after a comma. busk
  sets a family's timing whole, so the line carries the family's own curve, if it has one. On a
  family with timing of its own, `[none]` (or Ctrl+N) takes it away whole, fade, delay and curve,
  so the family fades with the cue again: `cue 9/3 time position none`. It asks nothing: `undo`
  brings the timing back.
- `[delay…]` has the delays in and out: `cue 9/3 time 1/3 delay 0/1`, the fade times kept.
- `[curve…]` has the curve as chips (`linear`, `easeIn`, `easeOut`, `easeInOut`, `snapStart`,
  `snapEnd`, `bezier`), and with `bezier` its four points, each from 0 to 1: `cue 9/3 time 1/3
  bezier 0.42 0 0.58 1`.
- `[follow…]` and `[wait…]` have the seconds of an automatic GO after the cue before has
  finished or started: `cue 9/3 follow 4`. While the cue has another trigger, the dialog says
  which (`now: wait 8`), and starts at 0.
- `[go…]` puts `cue 9/3 go` in the prompt, a whole line: Enter makes the cue a manual GO again.
- `[rename…]` is a name dialog: `rename cue 9/3 "Pre"`.
- `[number…]` renumbers the cue: `cue 9/3 number 7`. busk puts it at its place in the list, past
  the other cues if it must, and a playback on it stays on it. A number another cue of the list
  has is refused in the dialog. The cue stays the chosen one. A `goto` that named its old number
  names no cue then: busk warns in the log, and F1's `[GT]` goes grey.

The times are seconds from 0 (`2`, `0.5`), and the fade times a line keeps are written with every
digit the cue holds, though the table rounds them to two. Then:

- `[release…]` asks for targets, as busk reads them (`group 1`, `101 thru 104`), starting at the
  selection, and attributes, none for all of them: `cue 9/3 release group 1 only pan tilt`.
- `[copy…]` asks for a list, the one shown to start with, and a number, and copies the cue there:
  `cue 9/3 copy 7` in its own list, `cue 9/3 copy 10/7` in another. The copy holds what the cue
  holds, its effects too. A list the show lacks, or a number the list has, is refused in the
  dialog. A copy in the list shown becomes the chosen cue. To move a cue to another list, copy it,
  then `[delete]` it.
- `[record at…]` asks for a number and a name, and records the programmer as a new cue there:
  `record cue 9/2.5 "Bridge"`. `2.5` goes between 2 and 3. A cue that exists is refused in the
  dialog. The new cue becomes the chosen one.
- `[load]` puts what the cue stores into the programmer, in place of what it holds, and selects
  its fixtures: `load cue 9/3`. While the programmer holds values or effects it asks first
  (`Load cue 9/3 "Pre" into the programmer? It replaces what the programmer holds.`); `undo`
  gives the programmer back. A preset comes as the preset, a group's value or a spread as each
  fixture's value, and the cue's effects with their ids. A cue of a tracking list brings what it
  changes, not what it tracks from the cues before it.
- `[merge]`, `[replace]` and `[remove]` re-record the cue from the programmer: `record cue 9/3
  merge`. `merge` adds to what the cue holds, `replace` swaps it for the programmer's values, and
  `remove` takes out the attributes the programmer holds. The last two ask first.
- `[delete]` sends `delete cue 9/3`, after a question. When a playback is on that cue the question
  says so, since the playback leaves it at once.

`[record at…]`, `[merge]`, `[replace]` and `[remove]` are grey while the programmer has nothing
to record: no value, and no effect that runs. `[load]` is grey on a cue that stores no value and
no effect. A list with no cues offers only `[record at…]`.

**Editing a cue's values.** Choose the cue and `[load]` it. Change the look as any other, on F2,
F3 and F6, or at the prompt: the cue's fixtures are selected. Then `[replace]` records it back
(`record cue 9/3 replace`). The cue keeps its name, timing, trigger and releases. busk finds the
groups again as it does for any record, and a spread comes back as a value per fixture, which
plays the same. busk's reply to `[load]` says when an entry of the cue has a timing of its own,
which only the generic edit sets: it does not come, and `[replace]` drops it.

With the pane cursor (Tab on an empty prompt) the cues come first: Enter goes to one and
chooses it. Then the buttons and the two rows, then the lists: Enter on a list shows it, and
its cues come first again. `[+ list…]` is last. Below 100 columns the chosen list goes over the
list of lists.

## F5 Effects

Every effect the show's cues hold and every programmer effect, live, and the templates to
add one from.

```
 ┌─ EFFECTS · 5 in cues · 1 in the programmer ───────────────────────────────────────────────┐┌─ TEMPLATES ───────────────────────┐
 │ cue   id      template fixtures   rate          now   size phase   wings wave        state  ││ adds to 101 thru 102 (2)          │
 │ 9/4   rainbow Rainbow  Bar        hz 0.25      0.25      1 0→360       1 ███████████ [RUN]  ││                                   │
 │ 11/1  fx1     Circle   Heads      bpm x 0.5       ·     15 0→180       1 ▁▁▁▁▁▁▁▁▁▁▁ [off]  ││ name      layers            from  │
 │ 13/1  fx3     Wave     Bar        bpm x 1         ·    0–1 0→360       2 ▁▁▁▁▁▁▁▁▁▁▁ [off]  ││ Circle    pan add sine, …   show  │
 │ prog  fx5     Circle   101 thru … bpm x 1      2.00     20 0→0         1 ▇▇███▇▆▅▄▃▂ [RUN] ✕││ Chase     intensity abso… library │
```

**A row** is an effect: the cue that holds it (`9/4`) or `prog`, its id, template and
fixtures (a group by its name), its rate and direction as `effect add` takes them (`bpm x
0.5`, `hz 2 bounce`; forward is left out), its rate now in hertz while it runs, its size (or
the two levels of an absolute effect, `0–1`), its phase spread, its wings (with `g3 b2`, its
groups and blocks, when they are not 1), its next cycle as a wave (in its colours for a
colour cycle), and its state:

- `[RUN]` while it runs (dimmed while it fades in or out), `[off]` while not, `—` for a cue
  effect whose list no playback runs.
- On a cue's effect, `[off]` goes to its cue (`goto 11 1`) and `[RUN]` releases the playback
  (`release 11`). An effect that tracks on into later cues stays on the cue that holds it.
- On a programmer effect, `[RUN]` stops it (`effect stop fx5`: it stays in the programmer
  but does not run, and `record cue` leaves it out) and `[off]` runs it again (`effect run
  fx5`).

`✕` removes the effect. A programmer effect goes at once (`effect remove fx5`). A cue's effect goes
after a question, which says when it is running (`cue 9/4 effect rainbow remove`), and its cue
stays. `[clear]`, under the table, removes every programmer effect after a question (`effect
clear`). It is grey while the programmer holds none.

**TEMPLATES** lists every template `effect add` takes: the show's, then the effect library's
the show has no copy of yet (`library`: adding one copies it into the show), with the
defaults the library gives it (`size 20`, `low 0 high 1`, `phase 0 360`). A click adds one to
the selection the header names: `effect add "Circle"`, with those defaults; to choose
others, type the line (`effect add "Circle" bpm x 2 size 30`), or change the effect in its
panel. A template you add with `effect template add` shows here at once.

`[+ template…]`, under the table, makes a new one from controls: a name and whether its first
layer is a wave or a colour. Once the show has it, its panel opens.

**The TEMPLATE panel** opens with `[edit]` on a template's row, or `[view]` on one only the library
has, in the place of the templates, until its `[done]`. A library template is read-only: it names
its layers, and adding it to a selection copies it into the show, where it can change.

A template of the show has a row per layer, as `list effects` words it (`pan add sine +90°`). A
click on a row chooses that layer for the controls under the table, and `✕` takes it out; a
template keeps its last layer. `[+ wave]` adds a wave layer, and `[+ colour]` a colour layer, of
which a template has at most one. `[rename…]` renames it. `[delete]` deletes it, after a question,
and is grey while a cue, a binding or the programmer uses it, which the panel names. Each change
is one line and one undo step, `effect template update "<name>" <JSON layers>`, and a value left
as it was sends nothing.

- A **wave layer** has a chip for each attribute it can drive, its `mode` (`absolute`, `add`,
  `multiply`) and its waveform, then what that waveform takes (`duty`; `width`, `attack` and
  `decay`; `steps`, as `0 0.5 1`; `seed` and `smooth`; `points`, as `0 0, 0.5 1, 1 0`) and its
  `[offset…]`, in degrees.
- A **colour layer** has its `blend` and its palette. A click on a colour opens its form, `✕`
  takes an entry out, `[+ colour…]` adds one, and a chip per colour preset adds that preset. A
  palette keeps its last colour.

A dialog refuses a value that could not be sent, such as a level outside 0 to 1, and a name the
show has. What only busk can tell comes back as a refusal, such as a pulse longer than its cycle,
or an absolute layer on pan for an effect with no levels: the reason shows in red in the panel until
the next change, and the whole reply in the log.

**The EFFECT panel** opens with a click on any part of a row but its state or `✕`, in the place of
the templates, until its `[done]`. It names the effect's template and fixtures, and has one
control per setting:

- `[rate…]`: a form, in hertz or on a speed master's beat, with the master when the show has
  several, and a multiplier.
- `direction`: a chip for each way.
- `[size…]`, `[phase…]`, `[groups…]`, `[blocks…]`, `[wings…]` and `[fade-in…]`: a dialog that
  starts at the value. `[none]`, beside a fade-in, takes it away: the effect then comes in over
  its cue's time, or the programmer's fade time, where a fade-in of 0 snaps in.
- The two levels of an absolute effect: `[low…]` and `[high…]` on a cue's effect, and `[levels…]`,
  the two together, on a programmer effect.
- `size master` and `speed master`: a chip per master, and `[none]`. A speed master does nothing
  for an effect on a master's beat, and the panel says so.

Each change is one line and one undo step, and a value left as it was sends nothing. A change to an
effect that runs shows at once.

A cue's effect changes by its property: `cue 9/4 effect rainbow size 0.5`. The reply names the
property by its place in the show. No line takes a setting away from a cue's effect, so its
`[none]` is grey while it has a master or a fade-in.

A programmer effect has no such line, so a change restates the whole effect, each other setting as
it is: `effect add "Circle" id fx5 hz 2 forward size 15 …`. That line takes its fixtures from the
selection. So while the selection is not the effect's fixtures, in their order, the panel's
controls are grey and it says so, and `[its fixtures]` selects them. A stopped effect stays
stopped.

The pane cursor stops on each row (Enter opens its panel), each state and `✕`, and `[clear]`,
then each template and its `[edit]` or `[view]`, and `[+ template…]`, or a panel's controls while
it is open. Below 132 columns the templates and the panels go under the effects.

## F6 Presets

Every preset, as tiles, one panel per pool: COLOR, POSITION, BEAM, INTENSITY, FOCUS and ALL.
A pool shows when it has presets, or when your rig can record into it (a profile of the rig
takes one of its attributes). A tile shows the preset's number and name and what it gives
where all its values agree: the colour as a swatch, `pan/tilt` (`-30°/40°`), the intensity as
a block and a percentage, or its first attribute (`zoom 20°`); `mixed` where they differ (one
value per fixture). A click runs `preset color 2` on the selection, which the header names
(`applies to 101 thru 102 (2)`). A preset recorded at the prompt shows at once.

### Edit mode and the PRESET panel

`[edit]`, at the right of the header, turns edit mode on (`[edit ●]`). So does the last tile of
each pool, `+ record`. In edit mode a tile click chooses the preset for the PRESET panel
instead of applying it, and `[done]` turns edit mode off.

```
 applies to 101 thru 102 (2) · click a tile to edit it                                   [edit ●]
 ┌─ POSITION ──────────────────────────────┐ ┌─ PRESET · new position 3 ────────────────────────┐
 │ ┌───────────────┐ ┌───────────────┐     │ │ number [−] 3 [+] [number…] [name: Position 3…]   │
 │ │ 1   mixed/40° │ │ 2   mixed/10° │     │ │                                                  │
 │ │ Audience      │ │ Centre        │     │ │ scope  [global] [profile] [target]               │
 │ └───────────────┘ └───────────────┘     │ │                                                  │
 │ ┌───────────────┐                       │ │ SELECTION 101 thru 102 (2)                       │
 │ │ + record      │                       │ │ the preset keeps a value per fixture: only       │
 │ │ as 3          │                       │ │ those fixtures can take it                       │
 │ └───────────────┘                       │ │ [Heads] [Washes] [Bar] [All] [none]              │
 └─────────────────────────────────────────┘ │                                                  │
                                             │ POSITION                                         │
                                             │ pan        from [−] ███████▌░░░░░░░░░ [+]   -30° │
                                             │              to [−] █████████▌░░░░░░░ [+]    30° │
                                             │                 [centre] [edges]                 │
                                             │ tilt            [−] ███████████░░░░░░ [+]    40° │
                                             │ spread          [pan] [tilt]                     │
                                             │ positionSpeed    no fixture takes it             │
                                             │                                                  │
                                             │ RECORDS                                          │
                                             │ pan   on 101 thru 102 (2)                        │
                                             │ tilt  on 101 thru 102 (2)                        │
                                             │                                                  │
                                             │ [record]                                         │
                                             │                                                  │
                                             │ [clear] [blind on] [done]                        │
                                             └──────────────────────────────────────────────────┘
```

The panel works through the programmer, as busk does. Its editors send `set` lines, so what
you set shows on stage unless `[blind on]` is lit. Its `[record]`, `[merge]`, `[replace]` and
`[remove]` send `record preset` lines. Each line is echoed `ui>` in the log with busk's
answer (a drag's, the last one).

**A new preset** (`+ record`) starts at the pool's next free number. `[−]` `[+]` step over
the free numbers, and `[number…]` types one. `[name: Position 3…]` types a name; without
one, busk names it `Position 3`. These send nothing until `[record]`.

**scope** is what `[record]`, `[merge]` and `[replace]` record at: `global` (one value for
every fixture), `profile` (one per profile) or `target` (one per fixture). The pool's default
is lit at first: `global` for colour and intensity, `profile` for beam and focus, `target`
for position and all. Where the values differ, busk falls back to a narrower scope and says
so in its answer.

**SELECTION** shows the selection, with a button per group and `[none]`, as on F2. A preset
keeps no group, and the dim line under SELECTION says what it does keep at the scope lit. At
`global` the selection only gives the values, and a value reaches every fixture that takes the
attribute. At `profile` it reaches every fixture of its profile. At `target` the preset keeps a
value per fixture, and only those fixtures can take it. busk needs a selection all the same: it
records from the programmer, and the programmer holds values per fixture.

**The editors** are a section per family the pool records. A row acts on the selection when a
profile of your rig takes its attribute. The family's other attributes come last in the
section, dimmed (`colorMacro       no fixture takes it`): they do nothing, and show what a
preset could hold with such a fixture in the rig. The rows that act are:

- encoder rows, as on F2, plus the attributes F2 has no row for: rotations (in degrees per
  second, `-` turns the other way, the bar filled from its centre), the fixture effects'
  rate, fade and settings, `color.a` and `color.uv`;
- in COLOR, the colour picker. Its field runs through the hues across and the saturation
  down (palest at the top): a click sends that colour, `set color 1 0.25 0`, and a drag
  sends as it moves and logs the last. The field is mouse only; the named chips under it
  (`[red]`, `[amber]`, `[warm]` …) send theirs from the keyboard too. Then the programmer's
  colour, and the component rows, which act once a colour is held;
- option rows for the discrete attributes (gobos, prisms, shutters, colour wheels, fixture
  effects): a chip per option the selection offers. A click sends `set gobo1 star`; the
  programmer's option is lit;
- `spread [pan] [tilt] …`, a toggle per row (every row but a colour's components). A row
  toggled on becomes a fan over the selection: a `from` bar for the first selected fixture, a
  `to` bar for the last, and the ones between spaced evenly. A bar, `[−]` `[+]` or the wheel send
  the whole fan, `set pan spread -30 30`. `[centre]` mirrors it, with `from` at both ends and
  `to` in the middle (`set pan spread -30 30 center`), and `[edges]` the other way round.
  busk keeps the value each fixture got, not the fan, so the bars read the ends back from
  those values.

**RECORDS** is what a record takes now: every value the programmer holds in the pool's
families, for every fixture that has one. busk records those, selected or not, and RECORDS
says how many are not selected. With nothing to record, it says "set a value above", and
`[record]`, `[merge]`, `[replace]` and `[remove]` are grey.

`[record]` sends `record preset position 3 target "Name"` (the name only when you gave one).
The panel then shows the new preset. `[clear]` clears the programmer; `[blind on|off]` is lit
while blind is on.

**A preset of the show** (a tile clicked in edit mode) has, instead of the number and name:

- `[rename…]` and `[number…]`, each a dialog, then one line (`rename preset color 2 "…"`,
  `preset color 2 number 9`). The number dialog lists the numbers taken and refuses them;
- `[delete]`, after a question. The panel names what uses the preset (`used by cue 4/1,
  10/1–10/4`). A preset in use goes out of those cues and effect palettes too: `delete preset
  color 2 cascade`, after busk's question, which names the cues it leaves. The cues stay, with
  what is left, and busk refuses when the preset is a palette's last colour;
- HOLDS: each value it stores, then its scope and where (`pan  -30°  target 101`). A line too
  long for the panel ends in `…`: a long profile name is cut, never the value.

Its scope starts at the one its values share. `[its fixtures]` selects the fixtures it gives
a value to, and `[load]` applies it on the selection, so the editors show its values. Then,
in place of `[record]`:

- `[merge]` adds the programmer's values; a value of the same scope and attribute is replaced;
- `[replace]`: the programmer's values become the preset's;
- `[remove]` removes what the programmer's fixtures see, for the attributes the programmer
  holds.

`[replace]` and `[remove]` ask first (`Replace what preset color 1 "Blue" holds with the
programmer?`); `[merge]` does not.

The usual way to change a preset: `[its fixtures]`, `[load]`, change the values, `[merge]`.
With the mouse on `[load]`, the three above, `[centre]` or `[edges]`, the hint row says what
it does.

The pane cursor stops on `[edit]`, the tiles (Enter applies, or chooses in edit mode), and
every control of the panel in reading order. The panel is beside the pools from 100 columns,
and under them below that; there, a tile click scrolls down to it.

## F7 Masters

Every master, one panel per kind, three across on a wide terminal:

- **GRAND MASTER**: its level in big digits (red while blackout is on), its bar, `[BLACKOUT
  on|off]` and `[gm 100]`.
- **SPEED · name**, one per speed master: its BPM, the beat, `TAP`, `[−1]` `[+1]`, the
  master's own level, which picks its multiplier, and the multiplier steps with the current
  one lit.
- **SIZE & GROUP MASTERS**: a bar per master, and what it scales (`group · 2 Washes`).
- **FADE TIME**: a bar per fade-time master, and the fade time it imposes now (`override now
  1.6 s`, or `off`).
- **PANIC**: whether the output is on, `[release all]`, `[OUTPUT OFF]` (busk asks first, as
  for a typed `output off`) and `[OUTPUT ON]`.
- **PARKED**: a row per value park holds, by fixture (`204 intensity 0%`, `301.2 thru 301.3
  intensity 0%`), each with `[unpark]`, which sends `unpark fixture 204 intensity` at once. `[unpark
  all]` sends `unpark all` after a question (`Unpark everything? Park holds 2 values.`), and is grey
  with nothing parked. You park on [F3's FIXTURE panel](#edit-mode-and-the-fixture-panel).
- **MASTERS**: a row per master but the grand master, with its name in its bar's colour and what
  it is (`speed`, `size`, `group · 2 Washes`, `fade time`), and `[+ master…]`:
  - `[+ master…]` opens a form: the kind as chips (speed, size, group, fade time; group only
    when the show has groups), the name, and the group a group master scales, as chips, or a
    speed master's tempo, which starts at 120. It sends one line, such as `master add group
    "Washes" group 2` or `master add speed "Beat" bpm 128`, and refuses an empty name, a name
    another master has in any case, and a tempo outside 0 to 999 BPM before it sends.
  - `[rename…]` opens a name dialog and sends `rename master "FX" "Size"`.
  - `[delete]` sends `delete master "FX" cascade`. busk asks first, and names the bindings that
    go with it (`Delete master "FX"? It leaves 1 binding.`). A master that a cue's effect, a
    chase or the programmer uses stays, and the log says which (`master "Speed 1" is used by the
    chase of cue list 10 and effects in cues 11/1, 12/1, 13/1: change them first`). A group
    master also goes when its group does.

  The grand master has no row: busk neither renames nor deletes it. A master deleted at a level
  lets go of what it held, and `undo` brings it back at its initial level. The pane cursor stops
  on each `[rename…]` and `[delete]`, then `[+ master…]`.

## F8 Patch

The universes, the output routes and their state, a map of each universe's channels, and
what busk sends on the channels of the fixture selected. Universes and routes are added,
changed and deleted here, and a free channel of a map takes a fixture.

```
 ┌─ UNIVERSES ───────────────────────────────────────────────────┐┌─ ROUTES ──────────────────────────────────────────────────────┐
 │     U name                          fixtures    used overlaps ││     U proto   address   destination     tx       state        │
 │     1 Stage                               11  66/512        2 ││ ▸   1 ArtNet  0.0.0     unicast 127.0.… ● 1/s    open         │
 │ ▸   2 Balcony                              0   0/512        0 ││ [+ route…] U1 ArtNet 0.0.0 [edit…] [off] [delete]             │
 │ [+ universe…] U2 Balcony [rename…] [number…] [delete]         │└───────────────────────────────────────────────────────────────┘
 └───────────────────────────────────────────────────────────────┘
  place 1.9 · 24 free from here · [patch 101 here] [add fixture here…]
 ┌─ DMX MAP · U1 Stage · 66/512 · 2 overlaps ─────────────────────────────────────────────────────────────────────────────────────┐
 │    1 █▓▓▓▓▓▓·░░░░░░░·················█▓▓▓▓▓▓▓························                                                          │
 │   65 █▓▓▓▓▓▓▓██▓▓▓▓▓█▓▓▓▓▓█▓▓▓▓▓╳╳╳╳╳╳╳╳╳╳╳╳············╳╳╳╳╳╳╳╳╳╳╳╳·                                                          │
 │  129 ································································                                                          │
 │  …
 █ TupperDMX LED Bar   █ TupperDMX Blinder   █ TupperDMX Smoke Machine   █ TupperDMX PAR RGBW   █ TupperDMX Moving Head   █ start
 ▓ footprint   ╳ overlap   · free   hover a channel for its fixture and value; a click selects it
```

**UNIVERSES**: each universe, how many fixtures are patched in it, how many of its 512
channels they take, and how many pairs of fixtures overlap (in red). A click chooses a row
(`▸`), and the strip under the table acts on it:

- `[+ universe…]` is a form of its number, starting after the highest, and its name. Without one,
  busk names it. It sends `universe add 2 "Balcony"`;
- `[rename…]` and `[number…]`, each a dialog, then one line (`rename universe 2 "Roof"`, `universe
  2 number 7`). The number dialog lists the numbers taken and refuses them;
- `[delete]` sends `delete universe 1 cascade`, after busk's question, which says what goes:
  `Delete universe 1 "Stage"? 11 fixtures lose their patch and 1 route goes.` The fixtures stay,
  unpatched, and F3 shows them with a red `—`. One `undo` brings it all back.

**ROUTES**: each route, its protocol, address and destination as `route add` takes them, its
light (green while it is open, blinking while it sends, red when it fails, grey when it is
disabled or nothing runs the output, as with `--no-output`) with the packets it sends per
second, and its state: `open` (with the send errors, if any), `failed:` and busk's reason,
`disabled`, `ignored:` and why. busk keeps opening a failed route again. An Art-Net or sACN
route sends an unchanged universe once a second, so an idle look shows `1/s`.

A click chooses a route (`▸`). The strip under the table then has `[edit…]` (below), `[off]` or
`[on]` (`route r-c948753c3bac off`) and `[delete]` (`delete route r-c948753c3bac`), and busk asks
before `off` and `delete`, since they stop what the universe sends. A route that is off stays in
the show.

`[+ route…]` is a form for the chosen universe, else the first:

```
┌─ NEW ROUTE · U1 Stage ───────────────────────────────────┐
│                                                          │
│  protocol   [sACN] [Art-Net] [DMX-USB]                   │
│  universe   1                                            │
│  send by    [multicast] [unicast]                        │
│  interface  empty: busk's own (--iface)                  │
│                                                          │
│  Tab: next · ← →: chips · Enter: OK · Esc: cancel        │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

The protocol's chips choose the fields:

- **sACN:** the sACN universe, starting at the show universe's number, then `multicast` with an
  interface or `unicast` with a host. An interface left empty is left to busk (`--iface`);
- **Art-Net:** the port address as `net.sub.universe`, starting where Art-Net counts the show
  universe, from 0 (universe 1 is `0.0.0`), then `broadcast` or `unicast`, as for sACN;
- **DMX-USB:** the driver, `enttecPro` or `dmxking`, the port (`/dev/ttyUSB0`) and the rate, from
  1 to 40 Hz.

It sends `route add 2 sacn 2 multicast eth0`. What only busk can tell, such as an sACN universe
another universe sends, or a route the universe has already, is refused in the log.

`[edit…]` opens the same form for the chosen route, `EDIT ROUTE r-c948753c3bac · U1 Stage`,
filled in with what it holds, for its own universe: the protocol, the address, how it sends and
where, or the driver, port and rate. Any field or chip can change, the protocol too. It sends
`route r-c948753c3bac change 1 sacn 9 multicast eth0`, one `undo` step that keeps the route's id
and whether it is on; under `busk run` the old sender closes and the new one opens. A form that
changes nothing sends nothing.

**DMX MAP**, one per universe: 64 channels to a row (32 on a narrow screen), the first one's
address on the left. A fixture's start address is `█` and the rest of its footprint `▓`, in
the colour of its type (the profile's category: par amber, spot cyan, wash magenta, pixel
green, strobe white; a profile without one gets a colour of its own); `╳` in red where two
fixtures share a channel; `·` is free. The legend names the types. A fixture patched with a
split patch (one address per element) shows its main patch only: busk does not run split
patches yet, and F3 marks them `split`.

Hover over a channel and the hint row says what it is, what it does in the fixture's mode,
and what busk sends on it now: `1.17 · fixture 102 · ch 1/16 pan · 128`, or `1.94 · overlap
· fixture 501 · ch 3/12 tilt · fixture 502 · ch 3/12 tilt · 128`. The value follows the
show while the mouse stays. A click on a fixture selects it (`sel fixture 101`), and on an
overlap it selects both (`sel fixture 501, fixture 502`). Shift-click adds a fixture to the
selection, or takes it out.

**CHANNELS**, under the maps: with one fixture selected, each channel of its footprint, its
address, the value busk sends on it, and its function, as `list dmx fixture 101` prints them
at the prompt:

```
 ┌─ CHANNELS · fixture 101 Spot 101 · Generic Spot 16ch / 16ch · 1.1 ──────────────┐
 │ address dmx function                                                            │
 │ 1.1     132 pan                                                                 │
 │ 1.2     189 pan fine                                                            │
 │ 1.3     128 tilt                                                                │
 │ …                                                                               │
 │ 1.9     255 intensity                                                           │
 │ 1.10    255 intensity fine                                                      │
 │ …                                                                               │
 │ 1.14      0 unused                                                              │
 └─────────────────────────────────────────────────────────────────────────────────┘
```

The values are what goes out, 10 times a second: after the masters, park, blackout and the
limits, and not what the programmer holds. A fine byte is named after its channel (`pan fine`),
a colour channel after its emitter (`red`, `white`), and on a fixture of several elements each
function starts with its element's name (`Cell 2 red`). `unused` is a channel the mode does not
describe. With no fixture selected, or several, the panel says to select one; an unpatched
fixture says so.

**A place.** A click on a free channel sends nothing: it arms a place, and the strip above the
maps reads `place 1.9 · 24 free from here`. It offers:

- `[patch 101 here]`, with exactly one fixture selected: `fixture 101 patch 1.9`. The map draws
  what the fixture would take as `░`, cyan, red where it would overlap, and an overlap is yours
  to make. With no fixture, or several, the strip says to select one. A fixture that would go past
  channel 512 is not offered;
- `[add fixture here…]`, which opens F3's
  [new fixture form](#edit-mode-and-the-fixture-panel) at that address.

A click on a fixture clears the place, and so does that universe's map changing.

The pane cursor stops on each universe and its strip, each route and its strip, what the place
offers, then each fixture of the maps, in address order, where Enter selects it. Only the mouse
arms a place. Below 100 columns ROUTES goes under UNIVERSES.

## F9 Surfaces

The control surfaces (MIDI controllers, OSC apps, the web remote) and what each input is
bound to.

```
 ┌─ SURFACES · 2 ─────────────────────────────────────────┐┌─ BINDINGS · 51 ──────────────────────────────────────────────────┐
 │   name          kind device         pickup binds state ││ surface         input        what                  feedback  val │
 │ ● nanoKONTROL2  midi "nanoKONTROL2" soft      51 failed││ nanoKONTROL2    cc 1 0       fader 1                         80% │
 │ ● Phone         web  port 8080      jump       0 open  ││ nanoKONTROL2    cc 1 32      button 1 1            led         — │
 │                                                        ││ nanoKONTROL2    cc 1 23      master gm                      100% │
 │ nanoKONTROL2  'nanoKONTROL2' not found; available: …   ││ nanoKONTROL2    cc 1 46      tap                   led         — │
 │ Phone  http://192.168.1.135:8080/?k=Ri2I1sMN           ││ nanoKONTROL2    cc 1 60      release all                       — │
 │ edit "nanoKONTROL2" [bind…] [pickup…]                  ││ edit cc 1 32 on "nanoKONTROL2" [unbind…] [feedback…]             │
```

**SURFACES**: each surface's light (green open, red failed, grey ignored or not open, as
with `--no-surfaces`), name, kind, how busk finds it (the MIDI device's name, the OSC port
and where feedback goes, the web remote's port), its fader pickup, how many bindings it has
and its state. Under the table, busk's reason for a failed or ignored surface, and the web
remote's addresses, with their key, to open on a phone. A MIDI controller that is unplugged
turns red, and green again once it is plugged in: busk opens it when it comes back.

**BINDINGS**: each binding's surface, its input as `bind` takes it (`cc 1 48`, `note 1 36`,
`osc "/1/fader1"`, `clock`), what it drives in `bind`'s words (`fader 1`, `button 9 2`,
`master gm`, `master "FX"`, `tap`, `page +1`, `blackout momentary`, `release all`, `output
off`), its feedback (`led`, `motor`, `display`, with its own address when not the input's)
and `val`, the level of what it drives: the playback in its fader slot on the current page,
its playback, its master. busk does not report the messages that come in, so F9 has no
monitor of incoming MIDI, no learn mode and no raw MIDI value yet.

A click on a row chooses it, and the edits under each table act on it: `bind "Phone" ` and
`surface "Phone" pickup ` for a surface; `unbind "nanoKONTROL2" cc 1 32` (a whole line: Enter
runs it) and `feedback "nanoKONTROL2" cc 1 32 ` for a binding. The pane cursor stops on the
surfaces, their edits, the bindings and their edits; Enter on a row chooses it. Below 132
columns BINDINGS goes under SURFACES.

## Questions, dialogs and quitting

A line busk asks about first, such as `output off`, opens a dialog with busk's question.
The line runs only on **y**; **n**, Enter or Esc cancel it (`cancelled` in the log). F3's and
F8's `[delete]`, F8's `[off]`, F4's `[delete]` of a list and F6's `[delete]` of a preset in use are
such lines. F4's `[delete]` of a cue, `[replace]` and `[remove]`, and F6's `[delete]` of a preset
nothing uses, `[replace]` and `[remove]`, ask the TUI's own question the same way.

A name, a number or a path (`[rename…]`, `[number…]`, `[address…]`, `[offset…]`, F4's
`[follow…]` and `[wait…]`, the picker's `[import…]`) is typed in a small dialog: Enter takes it,
Esc cancels. What it refuses shows in red, and the dialog stays open. A form of several fields
(`[limit…]`, `[location…]`, `[+ universe…]`, `[+ route…]` and a route's `[edit…]`, `[+ list…]`,
`[record at…]`, `[copy…]`, `[release…]`, `[chase…]`, a cue's `[time…]`, `[delay…]` and
`[curve…]`) works the same way: Tab moves between the fields, and Enter, in any of them, takes the
form. In the route form, `[chase…]`, `[time…]` and `[curve…]`, Tab also reaches the chips, and ← →
move them.

**The profile picker** (F3's `[profile…]` and `[choose…]`) lists what `fixture add` takes: the
show's own profiles first, marked `●`, then the library's, with the maker, the name, and the modes
with what each takes (`3ch (3), 8ch (8)`). Type to filter by maker and name, in any order. ↑ ↓ and
PgUp PgDn move, Enter or a click chooses, Esc cancels. It sends nothing: the form or the panel
that opened it does.

`[import…]` under the list, or Ctrl+O, brings in a profile from a file: an Open Fixture Library
`.json`, a `.gdtf` or a busk profile `.json`. A dialog takes the path (`~` works, and a relative
path starts where busk-tui runs) and refuses one with no file there. It sends `profile import
"/home/me/fixtures/spot.gdtf"`: the profile comes into the show, as one `undo` step, and the
picker stays open with the profile in its list, marked `●`, the filter cleared and the list on
it. What busk refuses, such as a file it cannot read or a profile the show holds already, shows
in red under the list, as the log is behind the picker.

`quit`, `exit` (also from a script you `source`), Ctrl+C twice and Ctrl+Q open the quit
dialog. With unsaved edits it offers **s** Save and quit, **q** Quit without saving and **c**
Cancel; without, Quit and Cancel. Under `busk run`, unsaved edits are kept in the newest
autosave either way, and the run prints its path when it ends
([Running a show](../running.md)). `SIGTERM` and `SIGHUP` end the run as `quit` does, without
the dialog.

## Files

| File | |
|---|---|
| `$XDG_CONFIG_HOME/busk-tui/config.toml` | Defaults and F2's quick lines, read only (`--config` names another). |
| `$XDG_STATE_HOME/busk-tui/state.json` | The last page and layout. |
| `$XDG_STATE_HOME/busk-tui/debug.log` | Tracebacks the TUI caught, for a bug report. |

`config.toml`:

```toml
[defaults]
layout = "B"      # A console, B stack, C stage
faders = 20       # 4-20: at most this many of a page's slots on F1
colors = "auto"   # auto, 256, 16, truecolor

[program]
quick = [         # F2's quick lines: any console lines
  "set intensity spread 0 to 1",
  "set intensity spread 0 to 1 center",
  "set pan spread -90 to 90",
  "set tilt 45",
  "record cue 1",
  "clear",
]
```

A value that is not one of these is reported in the log at start and not used; a file that
does not parse is reported, and the defaults are used. The command line comes first, then
the remembered layout, then the config file. Without `quick`, F2 has the lines above.
