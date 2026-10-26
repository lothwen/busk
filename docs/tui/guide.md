# The terminal UI: `busk-tui`

`busk-tui` is a full-screen front end for busk. It runs your show under `busk run`, with the
watchdog, autosave, crash recovery and the event log, and puts a status bar, pages, a log and
the console prompt on one screen. Every click and key in it is a console line, echoed in the
log, so what the UI does is what you could type.

> **Work in progress.** This version has the frame (the status bar, the log, the prompt with
> hints and completion, the help overlay and the dialogs) and every page: [F1 Busk](#f1-busk),
> to play the show, [F2 Program](#f2-program) and [F6 Presets](#f6-presets), to build a look,
> [F4 Cues](#f4-cues) and [F5 Effects](#f5-effects), to run and edit cue lists and effects,
> [F7 Masters](#f7-masters), and the rig: [F3 Fixtures](#f3-fixtures), [F8 Patch](#f8-patch)
> and [F9 Surfaces](#f9-surfaces). F1 has one of its three layouts so far, B (stack).

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
| ← → on an empty prompt | Select the previous or next playback of the page shown on F1 (F4 shows its cue list). |
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

Every fixture, with its patch and what it outputs now.

```
 ┌─ FIXTURES · 7 fixtures · 4 selected · click selects, Shift-click adds ─────────────────────────────────────────┐
 │      # name                  profile                        type   mode      patch   intensity colour       pan  tilt zoom src     │
 │    101 Spot 101              Generic Spot 16ch              spot   16ch      1.1           64% ██           12°   10°  21° P1      │
 │ ▸  201 LED ML-56 RGBW 201    Eurolite LED ML-56 RGBW        par    4-channel 1.33          40% ██                          prog    │
 │ ▸  204 LED ML-56 RGBW 204    Eurolite LED ML-56 RGBW        par    4-channel 1.45           0% ██                          —       │
 │    301 COLORband PiX 301     Chauvet DJ COLORband PiX ×12   pixel  36-CH     1.49        8–50% ████████████                fx P13  │
 │                                                                                                                                    │
 │ ■ programmer   ■ playback   ■ effect   ■ nothing   — unpatched   ▸ selected                                                        │
 │ edit fixture 201 LED ML-56 RGBW 201 [patch…] [location…] [category…] [rename…]                                                     │
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
- `src`: what drives its intensity: `prog` (the programmer), `P9` (playback 9's cue), `fx
  P13` (an effect of playback 13's cue), `fx` (a programmer effect), `—` (nothing).

The values are coloured by what drives them: magenta the programmer, white a playback, green
an effect, grey nothing (the intensity and `src` by what drives the intensity, pan and tilt
by what drives the position, zoom by the beam's). A parked value counts as nothing: busk
does not say which values park holds.

A click on a row selects the fixture (`sel fixture 101`); Shift-click adds it to the
selection, or takes it out when it is in (`sel + fixture 101`, `sel - fixture 101`). The
edits under the table act on the fixture clicked last (else the first selected): they put
`fixture 101 patch `, `fixture 101 location {"x": 0, …}` (with its place when it has one),
`profile "Generic Spot 16ch" category ` or `rename fixture 101 "` in the prompt to finish.
The pane cursor stops on each row (Enter selects it, and the cursor stays), then the edits.

## F4 Cues

Every cue list, and the cues of one: go to a cue, record one, switch a list between sequence
and chase, and edit a cue's timing at the prompt.

```
 ┌─ CUELISTS ─────────────────────────┐┌─ CUELIST 9 · Song ────────────────────────────────────────────────────────────────────┐
 │   # name           kind  cues pb   ││ mode sequence · tracking   playback P9 @ 70%   groups Washes, Heads, Bar, All         │
 │   1 Warm           seq      1 P1   ││                                                                                       │
 │   …                                ││   cue    name           time          delay  curve     follow wait   intensity  …     │
 │   9 Song           seq      5 P9   ││   9/1    Intro          3             —      easeInOut —      —      60%        …     │
 │  10 Chase          chase    4 P10  ││   9/2    Verse          2, position 4 —      linear    —      —      70%        …     │
 │   …                                ││ ▶ 9/3    Pre            1/3           —      linear    —      8      100%, 30%  …     │
 │  20 Fast pulse     seq      1 P20  ││   9/4    Chorus         0.5/2         —      linear    —      —      100%, 100% …     │
 └────────────────────────────────────┘│   9/5    Outro          6             —      linear    4      —      20%        …     │
                                       │                                                                                       │
                                       │ [GO] [BACK] [record cue 9] [cuelist 9 chase bpm x 1]                                  │
                                       │ edit cue 9/3 Pre [time…] [delay…] [curve…] [go…] [follow…] [wait…] [rename…]          │
                                       └───────────────────────────────────────────────────────────────────────────────────────┘
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
cue` stores a spread), with the colour's swatch; then the ids of its effects.

- A click on a row goes to that cue: `goto 9 3` on the list's playback (busk's `cue 9/3 go`
  sets the cue's trigger instead). A list no playback runs has no go-to: its rows only
  choose.
- A click on a cue's time, delay, curve, follow or wait puts that edit in the prompt, to
  finish and Enter: `cue 9/3 time `, `cue 9/3 time 1/3 delay ` (the fade times kept), `cue
  9/3 time 1/3 ` (a curve next), `cue 9/3 follow `, `cue 9/3 wait `.
- The `edit` row under the buttons does the same for the chosen cue (the row clicked last,
  else the one the playback is on), and adds `cue 9/3 go` (back to a manual GO) and `rename
  cue 9/3 "`.
- `[GO]` and `[BACK]` run `go 9` and `back 9`. `[record cue 9]` records the programmer as a
  new cue at the end of the list. The last button switches the list to a chase (`cuelist 9
  chase bpm x 1`, or the chase settings the list had before) or back to a sequence
  (`cuelist 10 sequence`).

With the pane cursor (Tab on an empty prompt) the cues come first: Enter goes to one and
chooses it. Then the buttons and the edits, then the lists: Enter on a list shows it, and
its cues come first again. Below 100 columns the chosen list goes over the list of lists.

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
  fx5`). `✕` removes it (`effect remove fx5`).

**TEMPLATES** lists every template `effect add` takes: the show's, then the effect library's
the show has no copy of yet (`library`: adding one copies it into the show), with the
defaults the library gives it (`size 20`, `low 0 high 1`, `phase 0 360`). A click adds one to
the selection the header names: `effect add "Circle"`, with those defaults; to choose
others, type the line (`effect add "Circle" bpm x 2 size 30`). A template you add with
`effect template add` shows here at once.

The pane cursor stops on each state and `✕`, then each template. Below 132 columns the
templates go under the effects.

## F6 Presets

Every preset, as tiles, one panel per pool that has presets: COLOR, POSITION, BEAM,
INTENSITY, FOCUS and ALL. A tile shows the preset's number and name and what it gives where
all its values agree: the colour as a swatch, `pan/tilt` (`-30°/40°`), the intensity as a
block and a percentage, or its first attribute (`zoom 20°`); `mixed` where they differ (one
value per fixture). A click runs `preset color 2` on the selection, which the header names
(`applies to 101 thru 102 (2)`).

The last tile of each pool, `+ record`, puts `record preset color 5 "` in the prompt, with the
next free number: type the name, close the quotes, Enter. A preset recorded at the prompt
shows at once. A pool with no preset yet does not show: record its first one at the prompt.

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

## F8 Patch

The universes, the output routes and their state, and a map of each universe's channels.

```
 ┌─ UNIVERSES ──────────────────────────────────────────────┐┌─ ROUTES ──────────────────────────────────────────────────────┐
 │   U name                        fixtures    used overlaps ││   U proto   address  destination        tx       state         │
 │   1 Stage                             11  66/512        2 ││   1 ArtNet  0.0.0    unicast 127.0.0.1  ● 1/s    open          │
 └──────────────────────────────────────────────────────────┘└───────────────────────────────────────────────────────────────┘
 ┌─ DMX MAP · U1 Stage · 66/512 · 2 overlaps ───────────────────────────────────────────────────────────────────────────────┐
 │    1 █▓▓▓▓▓▓·························█▓▓▓▓▓▓▓························                                                    │
 │   65 █▓▓▓▓▓▓▓██▓▓▓▓▓█▓▓▓▓▓█▓▓▓▓▓╳╳╳╳╳╳╳╳╳╳╳╳············╳╳╳╳╳╳╳╳╳╳╳╳·                                                    │
 │  129 ································································                                                    │
 │  …                                                                                                                       │
 █ LED Bar   █ Blinder   █ fog   █ par   █ spot   █ start   ▓ footprint   ╳ overlap   · free
```

**UNIVERSES**: each universe, how many fixtures are patched in it, how many of its 512
channels they take, and how many pairs of fixtures overlap (in red). **ROUTES**: each route,
its protocol, address and destination as `route add` takes them, its light (green while it
is open, blinking while it sends, red when it fails, grey when it is disabled or nothing
runs the output, as with `--no-output`) with the packets it sends per second, and its state:
`open` (with the send errors, if any), `failed:` and busk's reason, `disabled`, `ignored:`
and why. busk keeps opening a failed route again. An Art-Net or sACN route sends an unchanged
universe once a second, so an idle look shows `1/s`.

**DMX MAP**, one per universe: 64 channels to a row (32 on a narrow screen), the first one's
address on the left. A fixture's start address is `█` and the rest of its footprint `▓`, in
the colour of its type (the profile's category: par amber, spot cyan, wash magenta, pixel
green, strobe white; a profile without one gets a colour of its own); `╳` in red where two
fixtures share a channel; `·` is free. The legend names the types. A fixture patched with a
split patch (one address per element) shows its main patch only: busk does not run split
patches yet, and F3 marks them `split`.

Hover over a channel and the hint row says what it is (`1.94 · overlap · fixture 501 · ch
3/12 · fixture 502 · ch 3/12`). A click selects the fixture (`sel fixture 101`), both on an
overlap (`sel fixture 501, fixture 502`); Shift-click adds it, or takes it out. The pane
cursor stops on each fixture of the maps, in address order, and Enter selects it. Below 100
columns ROUTES goes under UNIVERSES.

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
