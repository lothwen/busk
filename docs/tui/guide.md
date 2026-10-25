# The terminal UI: `busk-tui`

`busk-tui` is a full-screen front end for busk. It runs your show under `busk run`, with the
watchdog, autosave, crash recovery and the event log, and puts a status bar, pages, a log and
the console prompt on one screen. Every click and key in it is a console line, echoed in the
log, so what the UI does is what you could type.

> **Work in progress.** This version has the frame (the status bar, the log, the prompt with
> hints and completion, the help overlay and the dialogs) and two pages: [F1 Busk](#f1-busk),
> to play the show, and [F7 Masters](#f7-masters). The other pages are not built yet: each one
> lists console lines to type meanwhile.

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
| `--layout A\|B\|C` | The layout of the F1 page: console, stack (the default) or stage. Remembered. A and C are not built yet: F1 shows B. |
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
what they did. Scroll the log with the mouse wheel.

**The prompt** runs any console line ([the console](../console.md)), and keeps working
whatever the rest of the screen does. Its right side shows the selection, the page, the
selected playback (`P1`: the one Space and `[ ]` act on) and how many steps `undo` can take back; while a long line runs (`save`, a
`source`d script), `⧗ save 1.4s`. Performance lines and the UI's controls do not wait for it.

**The hint row** under it says what may come where the cursor is (`next: off on`, `<a
fixture number>`, `<Enter>`), or the mistake that stops the line (`error: no fixture 999`),
then the matching forms of `help`.

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
| ← → on an empty prompt | Select the previous or next playback of the page shown on F1. |
| `[` `]` on an empty prompt | The selected playback's fader 5 % down or up (`fader N 55%`). |
| PgUp PgDn on an empty prompt | `page prev`, `page next`. While help is open, they scroll it. |
| Esc | Close help, else leave the page, else clear the line. |
| Ctrl+C | Clear the line; on an empty prompt, twice in a row, quit. |
| Ctrl+Q | Quit. |

Typing `help` opens the help overlay with busk's answer. The prompt stays usable while help
is open.

## F1 Busk

The performance page: the playbacks of busk's current page, with the tempo, the masters,
the running effects and the selection beside them.

```
 page 1 Main · slots 1–13 · sel 101 thru 102                                              layout   A console    B stack    C stage

 ┌─ PLAYBACKS ────────────────────────────────────────────────────────────────────────────┐┌─ TEMPO · Speed 1 ────────────────────┐
 │ #   name            level                            cue → next                        ││ ▀█  ▀▀█ █▀█   █▀█  ● ● ● ●           │
 │ P1  Warm            ██████████████████████▍░░░░░  80 —/1 → Warm          [GO] [◂] [FL] ││  █  █▀▀ █ █   █ █                    │
 │ P2  Cool            ░░░░░░░░░░░░░░░░░░░░░░░░░░░░   0 —/1 → Cool          [GO] [◂] [FL] ││ ▀▀▀ ▀▀▀ ▀▀▀ ▀ ▀▀▀  [TAP] [−] [+]     │
 │ …                                                                                      │└──────────────────────────────────────┘
 │ P8  Panic no fader  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░   — —/1 → Panic         [GO] [◂] [FL] │┌─ MASTERS ────────────────────────────┐
 │ P9  Song            ███████████████████▋░░░░░░░░  70 3/5 Pre → Chorus    [GO] [◂] [FL] ││ GM       ██████████████████████  100 │
 │ P10 Chase           ██████████████░░░░░░░░░░░░░░  50 chase 4 Cue 4 bpm … [GO] [◂] [FL] ││ FX       ██████████████████████  100 │
 │ P11 Circle size     ████████████████████████████ 100 1/1 Circle          [GO] [◂] [FL] ││ Wash lev…██████████████████████  100 │
 │ P12 Pulse size      ░░░░░░░░░░░░░░░░░░░░░░░░░░░░   0 —/1 → Pulse         [GO] [◂] [FL] ││                           [BLACKOUT] │
 │ P13 Bar wave size   ░░░░░░░░░░░░░░░░░░░░░░░░░░░░   0 —/1 → Bar wave      [GO] [◂] [FL] │└──────────────────────────────────────┘
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
- `[GO]` and `[◂]` run `go N` and `back N`. GO leaves the fader where it is.
- `[FL]` is held while the mouse button is down on it: `flash N on`, then `flash N off`. It is
  lit while a flash is held on the playback, from here or from a surface.
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

The layout switch (A console, B stack, C stage) is drawn, but only B, the stack, is built.
Below 100 columns the right column goes under the playbacks.

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

## Questions and quitting

A line busk asks about first, such as `output off`, opens a dialog with busk's question.
The line runs only on **y**; **n**, Enter or Esc cancel it (`cancelled` in the log).

`quit`, `exit` (also from a script you `source`), Ctrl+C twice and Ctrl+Q open the quit
dialog. With unsaved edits it offers **s** Save and quit, **q** Quit without saving and **c**
Cancel; without, Quit and Cancel. Under `busk run`, unsaved edits are kept in the newest
autosave either way, and the run prints its path when it ends
([Running a show](../running.md)). `SIGTERM` and `SIGHUP` end the run as `quit` does, without
the dialog.

## Files

| File | |
|---|---|
| `$XDG_CONFIG_HOME/busk-tui/config.toml` | Defaults, read only (`--config` names another). |
| `$XDG_STATE_HOME/busk-tui/state.json` | The last page and layout. |
| `$XDG_STATE_HOME/busk-tui/debug.log` | Tracebacks the TUI caught, for a bug report. |

`config.toml`:

```toml
[defaults]
layout = "B"      # A console, B stack, C stage
faders = 20       # 4-20: at most this many of a page's slots on F1
colors = "auto"   # auto, 256, 16, truecolor
```

A value that is not one of these is reported in the log at start and not used; a file that
does not parse is reported, and the defaults are used. The command line comes first, then
the remembered layout, then the config file.
