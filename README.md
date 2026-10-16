# busk — busking lighting console engine

A real-time engine for improvising lighting live: the operator layers looks, colours,
positions and effects, and the engine turns that intent into DMX at the end of a
deterministic pipeline. The architecture is specified in
[`busking-console-architecture-python.md`](docs/busking-console-architecture-python.md)
("the spec"; section numbers such as §5.3 refer to it).

**Status: Phase 7 — hardening** ([plan](docs/phase-7-plan.md)), the last phase of the spec's
§22 roadmap, on top of Phase 6 — surfaces and network ([plan](docs/phase-6-plan.md)), Phase 5 —
effects ([plan](docs/phase-5-plan.md)), Phase 4 — time ([plan](docs/phase-4-plan.md)), Phase 3 — programmer & recording ([plan](docs/phase-3-plan.md)),
Phase 2 — busking core ([plan](docs/phase-2-plan.md)),
Phase 1.5 — sACN output ([plan](docs/phase-1.5-plan.md)), Phase 1 — fixtures
([plan](docs/phase-1-plan.md)) and the Phase 0 walking skeleton ([plan](docs/phase-0-plan.md)).
Phases 0–2 are the spec's "minimum viable busking engine"; Phase 3 adds the editing half:
the operator builds and changes the show from the console, live, while the output keeps
running. Phase 4 sets it in motion: fades and curves per slot, cue lists with
GO/BACK/GOTO, follow and wait, tracking, chases, speed masters and tap tempo. Phase 5 adds
**effects**: waveforms and colour cycles spread across a group's members, locked to a speed
master's beat or running in Hz, layered absolutely or relatively over the looks below,
scaled by `size` faders and size masters; group masters; effects in the programmer, in
recorded and tracked cues, and from a built-in template library. Phase 6 opens the engine
to the room: **playback pages** owned by the engine, every §8.1 button function (`go`,
`back`, `goto`, `flash`, `swop`, …), **soft takeover**, `crossfade` faders that run a cue
by hand and a **fade-time master**; **feedback** to LEDs, motor faders and OSC labels;
MIDI clock as tap tempo; **OSC** in and out; a **web remote** a phone opens over Wi-Fi;
and **Art-Net** (with ArtPoll discovery), sACN universe discovery and **DMX-USB** (Enttec
DMX USB Pro, DMXking) output. It adds no dependency: OSC, WebSocket, Art-Net and the
Enttec protocol are written against their specifications.

Phase 7 makes it fit for a show. `busk run` runs as **three processes**: the **root**
sends the output and watches the other two, the **engine** runs the pipeline, and the
**console** holds the session, the prompt, the surfaces and the web remote. A **watchdog**
restarts an engine that is killed or stalls while the output holds the last frame, and the
look comes back from the last snapshot; a console that crashes comes back against the
running engine. The §12 **safety stage** is complete (park, fixture limits, a strobe-rate
cap that also bounds intensity effects, highlight), with §18's **panic commands**
(`release all`, `output off`), unpatched-fixture warnings and
`holdLastFrameOnEngineStall: false`. Every route **reconnects**, MIDI controllers can be
**unplugged and plugged back in**, the phone and OSC are **rate-limited**, and the
engine's per-tick drain is bounded. Fixture profiles **import from OFL and GDTF** files
(`busk import`, or on the fly from a library directory), and `profile update` moves a show
to a profile's new revision. An **event log** records what the engine applied and why, and
`busk replay` rebuilds the run from it. A **soak harness** (`bench/soak.py`) runs the show
for hours under fuzzed surfaces and scheduled kills, measured on the wire. Still no new
dependency.

```
            ┌─ busk run: the ROOT (no show code) ───────────────────────────────────────────┐
terminal ───┤ output thread (44 Hz) ─▶ sACN (+ discovery), Art-Net (+ ArtPoll), DMX-USB     │
            │   routes reopen on failure · hold or dark on a stall · output off             │
            │ frame thread ◀─ frames, layouts, stats, event-log records                     │
            │ watchdog (10 Hz): no frame for 1 s → stalled; 3 s, or an exit → kill, respawn │
            │ event log · --stats · --duration · signals · restarts of either child         │
            └───┬────────────────── control links (socket pairs) ───────────────────┬───────┘
                │ ↑ frames, stats, log  ↓ attach, stop  attach, engine state, pids  │
┌───────────────▼── ENGINE (own session) ───────────────────────────┐               │
│ link thread: commands, install chunks, restore → the queue        │               │
│ engine thread, fixed tick: due events (auto-GOs, chase steps)     │               │
│   → drain (≤ 512 items: commands, installs; page, held buttons,   │               │
│   soft takeover) → per-slot fades → effects (clocks, waveforms,   │               │
│   strobe cap) → gather (+ programmer at band 100) → resolve       │               │
│   (absolute, then relative) → masters (group, grand) → safety     │               │
│   (highlight, park, blackout, limits, strobe lanes) → convert     │               │
│ publisher: frames → root; snapshots, stats → console              │               │
└───────────────▲─────────────────────────────┬─────────────────────┘               │
   commands, installs (engine view, shared    │ snapshots, stats                    │
   objects, chunks), restore after a restart  │                                     │
┌───────────────┴─────────────────────────────▼── CONSOLE (the terminal's) ─────────▼───────┐
│ console prompt ─┐                                                                         │
│ MIDI (hot-plug)─┤                        session (single writer): programmer ·            │
│ OSC ────────────┼─▶ bindings ─▶ commands ─▶ show store · undo · validate ·                │
│ phone (web API)─┘   (rate-limited remotes)  compile → install                             │
│ RemoteBus: the session's bus; queues commands while the engine restarts                   │
│ status line · feedback (30 Hz) · web broadcaster (30 Hz) · autosave                       │
└───────────────────────────────────────────────────────────────────────────────────────────┘
   commands, installs (engine view, shared    │ snapshots, stats               │
   objects, chunks), restore after a restart  │                                │
┌───────────────┴─────────────────────────────▼── CONSOLE (the terminal's) ────▼──┐
│ console prompt ─┐                                                                │
│ MIDI (hot-plug)─┤                         session (single writer): programmer ·  │
│ OSC ────────────┼─▶ bindings ─▶ commands ─▶ show store · undo · validate ·       │
│ phone (web API)─┘   (rate-limited remotes)  compile → install                    │
│ RemoteBus: the session's bus; queues commands while the engine restarts          │
│ status line · feedback (30 Hz) · web broadcaster (30 Hz) · autosave              │
└──────────────────────────────────────────────────────────────────────────────────┘
```

`busk run --threads` keeps the Phase 6 layout: the same components as threads of one
process, without the watchdog and the restarts.

The Phase 7 done criteria hold. **A, the safety show**: on the show the Phase 3–6 scripts
save, the script [`examples/phase7-safety.busk`](examples/phase7-safety.busk) adds, with
console commands only, a tilt limit of 10° on the heads (a low truss), an intensity limit
of half on the bar, wash 4 **parked** dark and wash 3 parked on red, a **strobe cap** of
3 Hz, a strobe look (10 Hz asked) and an 8 Hz pulse on page 2, and marker SET bound to
**`release all`**. `test_safety_show.py` plays it with the nanoKONTROL2 through the binding
resolver and console lines through a session, and checks 13 checkpoints by hand-computed
values: the limited and parked fixtures under every look, the Chorus's tracked tilt of 40°
held at 10° (and the Circle flattened at the top, against a twin show without the limit),
the strobe at 3 Hz and the pulse repeating at the cap, a **highlighted** head at full white
whatever the grand master and the look say, blackout winning over highlight, every
playback releasing from the panic button, and `output off` sending Stream_Terminated and
`output on` the frame again. The frames match goldens and are byte-identical at 100 Hz, on
an irregular tick schedule and after save → load. **B, the soak**: `bench/soak.py` runs the
show built from the five scripts with three routes (sACN, Art-Net and a DMX-USB widget on a
pseudo-terminal) checked by an independent receiver on the wire, while a load process
busks it from MIDI, OSC, a phone and the console, and a schedule kills and stops the
engine, kills the console and unplugs the widget. A 1-hour run passed with **0 output
drops** in 474 374 packets, 7 of 7 chaos actions recovered within 4 s, 1 overrun in
359 081 ticks and flat memory; the 24-hour run is the user's
([hardening checklist](#hardening-checklist-phase-7)). Killing the engine with `kill -9`
or stalling it with `SIGSTOP` never stops the output, and on a show of static looks the
restored frame is byte-identical to the one before the kill (`test_watchdog.py`); killing
the console leaves the show running and the phone reconnects (`test_console_restart.py`).
The split also closes the overrun misses of Phases 3–6: on the §19-sized rig, live edits
overrun 1 tick in 1 911 (10 % with threads) and surface load 0.4 % (2.3 %).

The Phase 6 done criterion holds: on the show the Phase 3–5 scripts save, the script
[`examples/phase6-surfaces.busk`](examples/phase6-surfaces.busk) adds, with console
commands only, soft takeover on the nanoKONTROL2, a web surface "Phone", a fade-time
master "Fade", a **second page** "Washes" (four exclusive wash looks whose M buttons
**swop**, a three-cue list run by hand on a **crossfade fader**, and the knob playbacks of
page 1), a **goto button** that jumps the song to its Chorus, marker buttons that turn the
pages, and **LED feedback** on the S, M, R, transport and cycle buttons. `test_surfaces_show.py`
plays it deterministically from both surfaces at once (the controller through the binding
resolver, the phone through the web API) and checks 24 checkpoints by hand-computed values:
the levels and colours per group, the LEDs by CC, the faders as the phone sees them, the
page, the manual crossfade's progress and the status. A fader moved after a page change
does nothing until it crosses the playback's level, a held swop leaves only its wash lit,
the crossfade holds where the fader stops, the Chorus arrives over the time the "Fade"
master sets, and the frames are byte-identical at 100 Hz, on an irregular tick schedule and
after save → load. The same show runs over a real WebSocket: a wrong key and a foreign
origin are refused, a show edit from the phone is refused, and a flash the phone holds goes
off when the phone vanishes.

The Phase 5 done criterion holds: on the show the Phase 3 and Phase 4 scripts save, the
script [`examples/phase5-effects.busk`](examples/phase5-effects.busk) adds, with console
commands only, a size master "FX" and a group master on the washes, three effect-only
playbacks with `size` faders (a **circle** on the heads, half a revolution per beat with
MH 2 a quarter turn behind, growing over 1 s; a **pulse** travelling across the washes; a
mirrored **wave** across the bar's 12 cells), a 0.25 Hz **colour cycle** merged into the
song's Chorus, which tracks into the Outro, and nanoKONTROL2 bindings for the effect knobs,
the size master and on/off buttons. `test_effects_show.py` replays it deterministically:
the saved show and the DMX at 29 checkpoints match goldens (the logical values were
computed by hand from the effect data), a size master and a group master scale exactly, a
tap moves nothing at the tap and the effects are on the new grid one beat later, the
colour cycle's clock carries on into the Outro and fades out with the song's release, the
programmer holds a pan under a running circle, and the frames are byte-identical at 100 Hz,
on an irregular tick schedule and after save → load.

The Phase 4 done criterion holds: on the show the Phase 3 build saves, the script
[`examples/phase4-song.busk`](examples/phase4-song.busk) adds, with console commands only,
a speed master, a five-cue **tracking song stack** (Intro, Verse, Pre, Chorus, Outro) with
an eased fade, per-family timing, a `wait` cue, a `follow` cue and a release, a four-step
**chase** bouncing across the washes, BPM-locked to the speed master, and nanoKONTROL2
bindings for GO, BACK, release, tap tempo and the speed multiplier. `test_song_stack.py`
replays it deterministically: the saved show and the DMX at 34 checkpoints match goldens
(the logical values were computed by hand from the cue data), the `wait` and `follow`
cues fire at their exact times, GOTO into the stack equals stepping through it, the chase
steps on the 120 BPM grid and, after four taps, on the 128 BPM grid of the last tap, and
the frames are byte-identical at 100 Hz and on an irregular tick schedule.

The Phase 3 done criterion holds: starting from `busk new`, the script
[`examples/phase3-build.busk`](examples/phase3-build.busk) builds a complete busking show
with console commands only (a universe, two Appendix A spots, four Eurolite ML-56 and a
COLORband PiX from the Phase 1 library, four groups, global colour presets, per-head
position presets, looks and bumps on page slots, exclusivity, an sACN route and the
Phase 2 nanoKONTROL2 bindings) and saves it as a `.show` file that `busk run` busks
exactly like the Phase 2 hand-written demo. `test_build_from_scratch.py` replays the
build deterministically and checks the saved show and the DMX bytes against goldens, a
live preset edit reaching the stage through references, undo of all 120 steps back to
the template and redo forward, and save → load. `kill -9` of a running console is
recovered: the programmer, the master levels and the unsaved edits come back
(`test_recovery.py`, against a real process).

Phase 2 made the engine busk: playbacks running single-cue looks built from groups and
scoped presets, merged by one resolver (HTP intensity per priority band, LTP layer stack
for everything else, presence fades, flash, exclusivity, grand master, blackout), with
the §7.8 worked example as a golden test and MIDI faders driving it.

Phase 1 turned logical values (pan in degrees, colour as linear RGB, a gobo by name) into
DMX through the fixture profiles, verified against the manufacturers' charts for three
real fixtures (`examples/phase1-demo.json`); Phase 1.5 put those bytes on the wire as
**sACN (ANSI E1.31)** with send-on-change, keep-alive and Stream_Terminated.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python ≥ 3.12 (development uses 3.14.7,
pinned in `.python-version`).

```bash
uv sync                 # the development setup: busk, the dev tools and the `midi` extra
uv sync --all-extras    # the same, spelled out
```

MIDI surfaces are the optional extra `busk[midi]` (Phase 8): [`mido`](https://mido.readthedocs.io/)
with `python-rtmidi` (wheels exist for current CPython on Linux, macOS and Windows). The
development setup includes it, because the `dev` group depends on `busk[midi]`. Without
it, busk runs as before, except that each MIDI surface reports
`MIDI s-…: unavailable: install busk[midi]` once and stays closed. On Linux MIDI needs the
ALSA sequencer (`/dev/snd/seq`); `aseqdump -l` lists the input ports `busk run` can match.

## Usage

```bash
uv run busk new club.show --title "Club Night"
# created club.show
uv run busk run club.show --script examples/phase3-build.busk
# added universe 'Stage'
# added fixture 101–102: Generic Spot 16ch, 16ch
# …                                          (one line per command of the script)
# saved club.show
# sACN r-…: U1 Stage → universe 1, multicast 239.255.0.1 via eth0, priority 100
# MIDI s-…: nanoKONTROL2:nanoKONTROL2 _ CTRL 20:0
# busk console: type 'help' for the commands, 'quit' to stop.
busk> fader 1 1                              # Warm up …
busk> fader 3 1                              # … and the Blue bump on top
busk> blind on                               # program without touching the stage
busk> sel group 1
busk> set color 0 0.3 1
busk> record preset color 1 merge            # the stage changes live: Blue's cue references the preset
# recorded preset color 1 'Blue': 1 value
busk> undo                                   # and back
# undid: recorded preset color 1 'Blue': 1 value
busk> quit
# engine: 2311 ticks @ 100 Hz, 0 overruns, max tick 1.4 ms, 2 commands, 0 command errors

uv run busk run club.show --script examples/phase4-song.busk     # Phase 4: the song and the chase
# added master 'Speed 1'
# …
# recorded cue 9/2: 4 entries; 8 values tracked from cue 9/1       (the washes: tracked, not stored)
# …
# saved club.show
busk> list cues 9
#     1  Intro                time 3 easeInOut  go
#     2  Verse                time 2, position 4  go
#     3  Pre                  time 1/3  wait 8
#     4  Chorus               time 0.5/2  go
#     5  Outro                time 6  follow 4
busk> fader 9 1                              # the Intro eases in over 3 s
busk> go 9                                   # Verse: the heads swing out over 4 s; Pre fires 8 s later
busk> status
# GM 100% | BO off | P1 Main | Speed 1 120 BPM ×1 | 9 Song on 2 Verse 1.00
busk> fader 10 1                             # the chase bounces across the washes on the beat
busk> tap                                    # four taps at 128 BPM: the chase follows them
busk> list masters
# Grand Master         grand   100%
# Speed 1              speed    50%  128 BPM ×1
busk> quit

uv run busk run club.show --script examples/phase5-effects.busk  # Phase 5: effects on that show
# added master 'FX'
# added master 'Wash level'
# 2 targets selected
# added effect template 'Circle'                                   (embedded from the library)
# added effect 'fx1' on 2 targets
# recorded slot 11: playback 11 'Circle'                           (an effect-only cue: a size fader)
# …
# recorded cue 9/4: 3 entries, 1 effect                            (the Chorus gets the colour cycle)
# …
# saved club.show
busk> list effects
# Circle               pan add sine, tilt add sine +90°
# Pulse                intensity multiply sine
# Wave                 intensity absolute sine
# Rainbow              color fade 3 colours
busk> fader 1 1                              # Warm
busk> fader 6 1                              # the heads on the audience
busk> fader 11 1                             # the heads circle, growing over 1 s, on the beat
busk> fader 12 1                             # the washes pulse in a wave
busk> tap                                    # ×4 in time: both follow without a jump
busk> master "FX" 50%                        # both at half size
busk> list masters
# Grand Master         grand   100%
# Speed 1              speed    50%  128 BPM ×1
# FX                   size     50%
# Wash level           group   100%
busk> status
# GM 100% | BO off | P1 Main | Speed 1 128 BPM ×1 | 1 Warm on 1.00 · 6 Audience on 1.00 · 11 Circle on 1.00 · 12 Pulse on 1.00
busk> quit

uv run busk run club.show --script examples/phase6-surfaces.busk # Phase 6: pages, a phone, LEDs
# set surfaces[0].faderPickup to "soft"
# added surface 'Phone'
# added master 'Fade'
# added page 'Washes'
# …
# recorded slot 2.1: playback 14 'Wash Blue'                       (slot 1 of page 2)
# …
# playback 9 on slot 9 of page 2
# …
# feedback on 8 bindings
# …
# saved club.show
# Web s-…: http://192.168.1.20:8080/?k=…                           (open it on the phone)
busk> list pages
# *   1  Main                 1:1 2:2 3:3 4:4 5:5 6:6 7:7 8:8 9:9 10:10 11:11 12:12 13:13
#     2  Washes               1:14 2:15 3:16 4:17 5:- 6:- 7:- 8:18 9:9 10:10 11:11 12:12 13:13
busk> page 2                                 # the phone shows "Washes"; the faders take over softly
busk> status
# GM 100% | BO off | P2 Washes | Speed 1 120 BPM ×1
busk> list surfaces
# s-…  midi 'nanoKONTROL2' device 'nanoKONTROL2', soft pickup
# s-…  web 'Phone' port 8080
busk> master "Fade" 50%                      # cue and release times become 2.5 s
busk> status
# GM 100% | BO off | P2 Washes | Speed 1 120 BPM ×1 | Fade 2.5 s
busk> quit

uv run busk run club.show --script examples/phase7-safety.busk   # Phase 7: limits, park, a strobe cap, panic
# limited fixture 101 thru 102: tilt -90° to 10°
# limited fixture 301: intensity at most 0.5
# parked fixture 204 intensity at 0
# parked fixture 203 color at 1 0 0
# strobe cap 3 Hz
# …
# unbound 1 binding                                                (marker SET toggled the bar wave)
# added binding b-…                                                (now it is `release all`)
# saved club.show
busk> fader 1 1                              # Warm: wash 4 stays dark, wash 3 red, the bar at half
busk> list park
# 204 intensity 0
# 203 color 1 0 0
busk> sel fixture 102
busk> highlight on                           # MH 2 at full white, whatever the look and the GM
busk> highlight off
busk> output off                             # at the prompt it asks: Turn all DMX output off? [y/N]
busk> status
# GM 100% | BO off | OUT off | P1 Main | Speed 1 120 BPM ×1 | 1 Warm on 1.00
busk> output on
busk> info
# …
# processes: root 96567, engine 96595, console 96597
# restarts: engine 0, console 0
# event log: ~/.local/state/busk/logs/show-…/20261016T170345436622Z.log
#   (another terminal: kill -9 96595)
# engine: restarted (killed by signal 9)                           (the output held the last frame)
# engine back: restored 1 playback, 5 master levels, page 1
busk> release all 2                          # every playback, over 2 s
busk> quit
# engine: 578 ticks @ 100 Hz, 0 overruns, max tick 1.573 ms, 1 command, 0 command errors, 1 restart   (the last engine's counters)

uv run busk import ofl ~/Documents/TupperDMX/demo.show/fixtures/*.json --manufacturer TupperDMX --out profiles
# …/blinder.json: 'TupperDMX blinder' (modes 8ch) → profiles/ofl-tupperdmx-blinder.json; 3 notes (--report)
# …/moving-head.json: 'TupperDMX moving-head' (modes 12ch, 18ch) → profiles/ofl-tupperdmx-moving-head.json; 4 notes (--report)
# …
uv run busk replay ~/.local/state/busk/logs/show-…/20261016T170328907372Z.log   # the Phase 3 build's run, rebuilt
# 13706.760109  start  'Club Night', fresh engine
# 13706.780164  e      added universe 'Stage'
# …
# replayed 121 record(s) in 8 tick(s), up to t=13706.840794

uv run busk validate examples/phase2-busk.json
# 0 errors, 0 warnings

uv run busk run examples/phase2-busk.json --no-console    # Phase 2 style: busk until Ctrl+C
# sACN r1: U1 Stage → universe 1, multicast 239.255.0.1 via eth0, priority 100
# MIDI s-nano: nanoKONTROL2:nanoKONTROL2 _ CTRL 20:0
# Running; press Ctrl+C to stop.                                   (stderr)
# GM 100% | BO off | P1 Main
# GM 100% | BO off | P1 Main | 1 Warm on 0.02
# GM 100% | BO off | P1 Main | 1 Warm on 1.00
# GM 100% | BO off | P1 Main | 1 Warm on 1.00 · 3 Blue on
# GM 100% | BO off | P1 Main | 1 Warm on 1.00 · 3 Blue rel · 4 Red on
# GM 100% | BO off | P1 Main | 1 Warm on 1.00 · 4 Red on · 8 Panic flash
# ^C
# engine: 1601 ticks @ 100 Hz, 0 overruns, max tick 1.194 ms, 20 commands, 0 command errors
# sACN r1: 347 packets, 0 errors

uv run busk run tests/fixtures/appendix_a.json --duration 2 --console
# MIDI s-midi: 'nanoKONTROL2' not found; available: Midi Through:Midi Through Port-0 14:0
# [frame 1] U1 Stage: 1=128 3=128 8=255 11=128 12=4 13=11 17=128 19=128 24=255 27=128 28=4 29=11
# sACN r1: cannot open: no network interface 'eth0' (available: lo, enp6s0, wlp0s20f3)
# GM 100% | BO off | P1 Main | Speed 1 120 BPM ×1
# engine: 211 ticks @ 100 Hz, 0 overruns, max tick 1.351 ms, 0 commands, 0 command errors

uv run busk run examples/phase1-demo.json --values examples/phase1-values.json --console
# the Phase 1 chart-derived golden frame, as before (see below)
```

Appendix A with nothing up shows the **shutter guard**: the shutters output their `open`
function (13 and 29 = 11), not their closed `defaultDmx` of 0, which kept Phase 0 dark.

* `busk validate SHOW` prints one line per issue (`error   fixtures[2].patch.address: …`)
  and a summary. Exit code 0 means no errors (warnings are allowed); 1 means errors.
  Shows are `.show` (a ZIP holding `show.json`) or plain `.json`.
* `busk new PATH [--title T]` writes an empty, valid show: one grand master, one empty
  page `Main`, no routes, and the installation's sACN CID (created once in the state
  directory). It never overwrites a file.
* `busk run SHOW [--values FILE] [--duration SECONDS] [--console] [--script FILE]
  [--no-console] [--iface IF] [--state-dir D] [--library D] [--no-recover] [--threads]
  [--stats FILE] [--no-log]` opens the
  show's output routes and control surfaces (MIDI, OSC, web), runs the engine, output and
  feedback (as [three processes](#processes-and-the-watchdog), or with `--threads` as
  threads of one process, the default where `socket.send_fds` is missing) and opens
  the **[console](#the-console)**: a prompt on a terminal (Ctrl+C clears the line and never
  stops the output; `quit` or Ctrl+D ends the run and offers to save unsaved edits), or
  commands read line by line from a piped stdin, whose end quits (unless `--duration` is
  given). `--no-console` reads no commands and runs until Ctrl+C, as in Phase 2.
  `--script FILE` runs a console script first and stops at its first error, ending the run
  with exit code 1. `--iface` is the interface `route add` uses for multicast and
  broadcast (default `eth0`); `--library` adds a directory of profile files. On exit it
  prints the tick and command statistics and each route's packet and error counts (`, N
  faults` is added if its driver raised). It exits 1 if the show or the values file cannot
  be loaded or compiled (naming the newest backup, if there is one); a route or surface
  that cannot open is reported and the run goes on without it.
* **Autosave and recovery.** While it runs, the show is autosaved 5 s after a burst of
  edits (every 180 s during a long one) and the programmer (its effects included) and the
  master levels (grand, speed, group, size and fade-time) at most once per second (with
  the programmer's fade time, each speed master's tempo and the current page), under
  `$XDG_STATE_HOME/busk/autosave/<show id>/` (or `--state-dir`). After a crash or `kill
  -9`, the next `busk run` of the same show restores them: `recovered programmer with 4
  values, 1 effect (blind, fade 2 s), 4 master levels, 1 tempo, page 2, unsaved edits
  from …`
  (`--no-recover` starts clean). Quitting with unsaved edits keeps them in the newest
  autosave and prints its path. Saving keeps the 10 newest backups in `<name>.backups/`.
* **Before running** it prints compile warnings on stderr (a cue value dropped for a
  target that does not offer it, e.g. a gobo the fixture lacks) and, on stdout under
  `Ignored in Phase 7:`, every feature the show uses that this build ignores, one line
  each with its path (`hid` and `internal` surfaces, `hw` inputs, display feedback on a
  MIDI surface, feedback on a `command` action, …). Since Phase 7 the compile warnings
  include each unpatched fixture that a cue, effect or park entry drives (§18); validation
  warns about a fixture whose slowest strobe is above the show's strobe cap.
* **MIDI.** Each `midi` surface opens the first input port whose name contains its
  `match.deviceName` (case-insensitive) and prints `MIDI <surface>: <port>`. If none
  matches it prints the ports that exist, on stderr. A surface with feedback bindings also
  opens the matching output port (`MIDI <surface> feedback: <port>`). Page faders and
  buttons drive the slots of the **current page** (see [Surfaces](#surfaces)); MIDI clock
  bound with `bind "<surface>" clock tap` taps a speed master once per beat, and Start and
  Song Position set the count.
* **OSC.** Each `osc` surface listens on its UDP `match.port` (`OSC <surface>: listening
  on udp 8000, feedback to the sender`). An input is an address (`osc "/fader/1"`); the
  message's first argument is its value, clamped to 0..1 (`T`/`F` are 1 and 0), and a
  message without arguments is a press and a release. Feedback goes to
  `match.host`:`match.feedbackPort`, or to the sender's address and port for the part
  left out, as `/address <float>` (or a string for `display`).
* **Web remote.** Each `web` surface serves a phone page on its port (8080 by default)
  and prints one `Web <surface>: http://<address>:8080/?k=<key>` line per IPv4 address
  of the machine; open it on a phone on the same network. The key is created once in
  `<state dir>/web-key` (mode 0600) and every request needs it. The page shows the current
  page's strips (fader, buttons, the current cue), the page arrows, blackout, the first
  grand master, TAP with the tempo and a beat dot, the other masters and the fade time; it
  reconnects by itself. A phone sends performance commands only, and the buttons it holds
  are released when it disconnects.
* **Feedback.** A binding with a `feedback` (`led`, `motor` or `display`) shows its
  action's state: an LED lit while its playback is active (a flash button's while the flash
  is up, a `swop` button's while held, `goto`'s at its cue, a page button's while there is
  a page that way, a tap button's for the first quarter of each beat, blackout's while
  on),
  a motor fader at the level, a label with the name. The feedback thread sends only what
  changed, 30 times a second, and holds a motor fader still for 0.5 s after it was moved
  by hand.
* **Status line.** Whenever the engine's state changes, stdout gets a line like `GM 80% |
  BO off | P1 Main | Speed 1 128 BPM ×2 | Fade 2.5 s | 9 Song on 3 Pre 1.00 · 10 Chase on
  1.00 · 8 Panic flash · 18 Manual on → 2 c2 50%`: the grand master, blackout, the current
  page, each speed master's tempo and multiplier, the fade-time master's time when it is
  up, and every playback that is active (`on`), releasing (`rel`), flashing (`swop` while
  a swop button is held) or has its fader up, with the current cue of a sequence (number
  and name), the level of a `master`, `size` or `temp` fader, and a manual crossfade's
  target cue and progress. Running effects print nothing per cycle. A chase shows no
  step, so a running chase does not print a line per step. At an interactive prompt the
  lines would garble the input, so the `status` command prints it instead.
* **Live edits** reach the stage at the next engine tick: a new route opens (its line
  is printed), a removed or changed one sends Stream_Terminated, a new or changed surface
  opens (a web surface restarts only when its port or host changes, so a rename keeps the
  phones connected) and new bindings and feedback work at once.
* Route lines go to stdout: one per open route (where it sends: `sACN r1: U1 Stage →
  universe 1, multicast 239.255.0.1 via eth0, priority 100`, `Art-Net r2: U2 Bar → port
  address 0.0.1, broadcast 10.255.255.255 via eth0`, `DMX-USB r3: U3 Floor → Enttec DMX
  USB Pro on /dev/ttyUSB0 at 40 Hz`), plus `disabled` and `ignored (…)` notices (an
  `enttecOpen` interface, an unknown driver), and the Art-Net nodes that answer ArtPoll
  (`Art-Net: node 10.0.0.20 'Node 1' outputs 0.0.1`, `… forgotten (no reply for 10 s)`).
  Routes that cannot open, send failures (`sACN r1: send failed: [Errno 101] Network is
  unreachable`) and recoveries (`sACN r1: sending again`) go to stderr. With no open route
  and no `--console`, the run says so on stderr (`no output: …`) and keeps running.
  **Every route reconnects** (Phase 7): one that cannot open is tried again every 2 s,
  whatever the reason, and prints its line again ending in `(sending)` once it opens; one
  whose sends have failed for 1 s is closed and reopened on the same schedule, its
  interface, address and broadcast address looked up again. So an interface that comes up
  late, a USB network adapter plugged back in or a DMX-USB widget plugged in after the
  start are found by themselves, and an outage prints once, not on every retry.
* `--console` also prints frame lines: the non-zero channels of a universe, 1-based, or
  `all 0`. A universe prints only when its bytes change, so a static look prints once.
  Without `--console` (and at an interactive prompt) no frame lines are printed.
* Ctrl+C (or the end of `--duration`) closes the surfaces (MIDI ports, OSC sockets, the
  web servers, which tell each phone they are going away) and the feedback thread, stops
  the engine, sends the final frame, then sends 3 Stream_Terminated packets per sACN route
  so receivers release their universes at once. Art-Net nodes and DMX-USB widgets hold
  the last frame. After a crash or `kill -9` of the root (the `busk run` process itself),
  receivers fall back to E1.31's 2.5 s timeout; the engine and the console can be killed
  without stopping the output (below).

### Processes and the watchdog

`busk run` starts three processes (phase-7-plan §5.1):

* the **root** is the process you start. It sends the output, watches the other two,
  writes the event log and the `--stats` file, and owns `--duration`. It runs no show code;
* the **engine** runs the pipeline in its own session, so terminal signals never reach it;
* the **console** loads and recovers the show and runs the session, the prompt or script,
  the surfaces, feedback, the web remote, autosave and the status lines. It owns the
  terminal: Ctrl+C at the prompt keeps its meaning.

They talk over socket pairs the root makes, never over a path or a port. `info` names
their pids and the restarts so far (`processes: root 96567, engine 96595, console 96597`,
`restarts: engine 0, console 0`).

* **The watchdog** takes the engine's frames as its heartbeat. After 1 s without a new
  frame the engine is *stalled*: the output holds the last frame (`engine: no new frame
  for 1.0 s; holding the last frame`), or, when the show's `holdLastFrameOnEngineStall`
  is false, sends it with intensity off and everything else held, so heads do not swing
  home. After 3 s, or as soon as the engine process exits, the root kills it and starts a
  new one (`engine: restarted (killed by signal 9)` on stderr). The console sends it the
  show and the programmer, then **restores the look** from the last snapshot it received:
  every master level, the speed masters' tempos and beat anchors (so BPM chases and
  effects land back on the grid), blackout, output on or off, the page, and every active
  playback at its current cue and fader level (`engine back: restored 7 playbacks, 6
  master levels, page 2`). Fades in progress snap to their target; Hz effect phases, held
  flashes and soft-takeover attachments are not restored. Commands sent while the engine
  is down (a blackout pressed during the restart) wait in the console (at most 1024) and
  follow the restore. A restart within 10 s of a restore skips the restore, in case the
  restored state is what crashes the engine; after three restarts within 60 s the
  watchdog gives up: the output keeps holding, the status line says `engine failed`, and the run ends with 70.
* **Tick errors.** A tick that raises is counted (`tickErrors` in `--stats`) and the
  engine goes on; ten in a row end the engine with exit code 70, and the watchdog
  restarts it.
* **A console that crashes** (killed by a signal, or an unexpected exception: exit 70) is
  replaced (`console: restarted (killed by signal 9)`). The new one recovers the show and
  the programmer from autosave, as after `kill -9` in Phase 3, and **adopts** the running
  engine's masters, tempos and page instead of pushing its own; it runs no `--script` or
  `--values` again. If its recovered show is the engine's (the same session and show
  version), it sends only the programmer; otherwise edits made after the last show
  autosave (at most 5 s) are undone on stage. The output and the engine never stop
  meanwhile, and the phone reconnects to the new console by itself. A console that exits
  0 (`quit`) or 1 (a load, compile or script failure) ends the run with that code; after
  three restarts within 60 s the root gives it up, and the show runs on until Ctrl+C, `SIGTERM` or
  `--duration`, ending with 70.
* **Signals.** The root ignores Ctrl+C while a console lives (the console has its own);
  without one (a restart in progress, or given up) Ctrl+C stops the run. `SIGTERM` and
  `SIGHUP` to the root are passed to the console, which quits as at the end of a script.
  An engine or console whose root vanished exits at once (the console then writes no clean
  autosave, so the next run recovers).
* `--stats FILE` appends one JSON line per second: the engine's pid, state (`running`,
  `stalled`, …), restarts, ticks, overruns, longest tick, tick, install and command
  errors, longest garbage-collection pause and memory; the console's pid, restarts and
  memory; the root's memory, late output cycles and longest output gap; per route, its
  packets and errors.
* `--threads` runs the Phase 6 layout, one process with the same components as threads.
  The safety stage, the stall output, reconnects, rate limits and the event log work there
  too; the watchdog and the restarts exist only with processes.

### Safety

* **Park** (`park fixture 204 intensity 0`, `park group 2 color 1 0 0`) forces a value on
  every slot it names, whatever any playback, effect, the programmer, a master or
  highlight says. A parked intensity is not scaled by the masters, but blackout still
  darkens it (§12 lets park override blackout only "for non-intensity slots"). `unpark
  fixture 204 [intensity]` and `unpark all` remove it; `list park` lists it.
* **Limits** (`fixture 101 thru 102 limits tilt -90 10`, `… limits pan -170 170`, `…
  limits intensity 50%`, `… limits none`) clamp every element of the fixture: pan and tilt
  in degrees as programmed (before the fixture's orientation), intensity to a maximum.
  They clamp parked values too.
* **The strobe-rate cap** (`safety strobe 3`, `safety strobe off`) is off unless the show
  sets it, so existing shows keep their strobes. It clamps strobe rates, and it slows
  effects that move intensity to at most that many flashes per second: an Hz effect is
  clamped, a BPM effect halves its cycles per beat until it is under the cap, so it stays
  on the beat grid (and re-rates without a jump when the tempo changes). A fixture whose
  slowest strobe is above the cap gets a validation warning, since its strobe cannot go
  slower.
* **Highlight** (`highlight on|off`) is a programmer mode, like blind: every selected
  target lights at full (after the masters, so a grand master at half does not halve it),
  with the shutter open and the colour white; other channels take their profile's
  `highlightDmx`. It is never undone, works while the programmer is blind, and is
  autosaved. Blackout, park and limits win over it.
* **Panic.** `release all [<seconds>]` releases every playback that is active, releasing
  or flashing, each over its own release time unless one is given, and drops held flashes
  and swops (the programmer is left alone: `clear`). `output off` stops all DMX output:
  sACN streams send Stream_Terminated once, so receivers let go at once; Art-Net nodes
  and DMX-USB widgets keep their last frame, as they do by themselves. The status line
  shows `OUT off` until `output on`. At an interactive prompt `output off` asks first
  (`Turn all DMX output off? [y/N]`); scripts and bindings do not. Both can be bound:
  `bind "nanoKONTROL2" cc 1 60 release all`, `… note 1 61 output off`. Validation warns
  when `output off` is bound to something that may not be a button (a pitch bend, or a CC
  without LED feedback): a fader would send it each time it is pushed up.
* The safety stage runs after the masters on the output frame only (highlight, park on
  intensity, blackout, park on everything else, limits, strobe lanes), so releasing any of
  it returns exactly to the live state.

### Rate limits

A phone may send at most 120 commands per second (bursts of 240, twice what the page
sends), an OSC surface 200 messages per second (bursts of 400). The excess is dropped and
counted: the phone gets one `error` per second (`rate limit: 37 commands dropped`), and
OSC drops print once per second on stderr (`OSC s-touch: rate limit: 37 messages
dropped`). Releases are never dropped (a button let go, and on OSC any message whose values
are all 0), so a flood never leaves a flash stuck. MIDI is not limited: it is local
hardware. The engine applies at most 512 queued items per tick, so a flood that gets
through still cannot make one tick arbitrarily long.

**MIDI hot-plug.** The surfaces read the MIDI port names every 2 s: a controller unplugged
prints `MIDI s-nano: unplugged; waiting for it` (stderr), and plugged back in `MIDI s-nano:
nanoKONTROL2:nanoKONTROL2 _ CTRL 20:0 (connected)`. A controller missing at start-up opens
when it appears; feedback ports do the same, and get a full send, so the LEDs show the
state again.

### Importing profiles

`busk import ofl FILE… [--manufacturer M] [--out DIR] [--report]` and `busk import gdtf
FILE…` write one busk profile per file (`<id>.json` in `--out`, default here) and print
what each became: `'TupperDMX moving-head' (modes 12ch, 18ch) → ofl-tupperdmx-moving-head.json;
4 notes (--report)`. `--report` prints the notes: channels that became `control` channels
held at a value (`Fog Type: no busk attribute (FogType); held at DMX 0`), estimated speeds,
skipped modes. A file that fails names why and the run exits 1. A `--library` directory
may also hold OFL `.json` and `.gdtf` files, imported when the library loads.

* **OFL** (the Open Fixture Library's JSON) maps each capability type to a busk attribute
  (phase-7-plan §5.18). Profile ids are `ofl-<manufacturer>-<fixture>`; the manufacturer
  comes from the OFL repository layout (`<manufacturer>/<fixture>.json`) unless given. The
  revision is the file's `lastModifyDate` plus a short hash of its content, so editing the
  file makes a new revision. `FogOutput` is intensity, so the masters and blackout apply to
  a smoke machine; a mode whose colours are only whites or UV makes each its own intensity
  element; speeds OFL gives only as `slow…fast` become estimates (strobe 1–20 Hz, rotation
  10–360 °/s), flagged in the report. The five TupperDMX fixtures import and convert like
  their hand transcriptions, except the smoke machine's dead band
  (`examples/tupperdmx/build-ofl.busk` builds the TupperDMX show from them).
* **GDTF** (DIN SPEC 15800) is a subset (§5.19): single-cell fixtures, and multi-cell
  ones built from geometry references, with their wheels, emitter colours (CIE xyY to
  linear RGB), physical ranges and DMX defaults. Mode masters, DMX breaks after the first
  and virtual channels are reported, not imported. The XML is read with no `DOCTYPE`
  allowed and the archive's `description.xml` is capped at 32 MB. Only synthetic files
  were tested; a real file from the GDTF Share is a manual check.
* **`profile update "<name>"`** at the console replaces the show's embedded copy of a
  profile with the library's other revision and moves its fixtures to it, as one undo
  step. It is refused when a fixture's mode is missing from the new revision. `list
  profiles` says which embedded profiles the library has in another revision; nothing is
  ever updated silently.

### The event log

Every run writes what the engine applied, when and why, to
`<state dir>/logs/<show id>/<UTC stamp>.log` (one JSON record per line; `info` prints the
path, `--no-log` turns it off). Each connection of a console to an engine starts with the
whole state (the show, the programmer, the `--values` base, whether the engine was fresh);
then come show edits as patch ops with their labels, programmer changes, performance
commands and restores, each with the engine time at which it was applied. A file rotates
past 64 MB, and the 16 newest are kept. `busk replay LOG… [--until T] [--frames OUT]
[--at T]` rebuilds the run on a fresh engine and prints each record; `--frames` writes
every frame as JSON, and frames rebuilt this way are byte-identical to the run's.

### Busking

`examples/phase2-busk.json` is the demo: 2 Appendix A spots and 4 RGB pars on universe 1,
groups Heads / Pars / All, colour presets Blue, Red, Green, Amber (global scope) and
position presets Audience and Centre (per head), one sACN route, and a **Korg
nanoKONTROL2** in its factory CC mode (check the numbers with `aseqdump -p nanoKONTROL2`):

| Slot | Playback | Content | Fader | Exclusivity |
|---|---|---|---|---|
| 1 | Warm | All: intensity 0.8, warm white | master, LTP at 2 % (`threshold`) | base |
| 2 | Cool | All: intensity 0.8, cool white | master, `threshold` | base |
| 3–5 | Blue / Red / Green | All: colour preset, 1 s fade | master, `threshold` | color |
| 6–7 | Audience / Centre | Heads: position preset, 2 s fade | master, `followFader` | position |
| 8 | Panic | All: intensity 1, white, band 200 | none | — |

| Control | CC | Action |
|---|---|---|
| Faders 1–8 | 0–7 | playback fader (`autoStart` on leaving 0, `autoRelease` at 0) |
| S buttons | 32–39 | `toggle` |
| M buttons | 48–55 | `flash` (while held; colours, positions and Panic bring their LTP values) |
| R buttons | 64–71 | `release` |
| Knob 8 | 23 | grand master |
| ■ (stop) | 42 | blackout on and off (Phase 2: while held; see below) |

Base looks carry the intensity; bumps carry only colour or position and layer on top.
Faders jump to the controller's position unless the surface takes over softly
(`faderPickup: soft`, Phase 6). Since Phase 6 a blackout binding **latches**: one press
turns blackout on, the next turns it off; `blackout momentary` (`"momentary": true`)
keeps the Phase 2 behaviour, blackout while held. Another controller works by editing the
`bindings` (`midiCC`/`midiNote`/`midiPitchBend`, channels 1–16).

**The song** (`examples/phase4-song.busk`, run after the Phase 3 build) adds slots 9 and 10
and binds the nanoKONTROL2's free knobs and transport buttons:

| Slot | Playback | Content |
|---|---|---|
| 9 | Song | Tracking stack, `go`/`back`/`release` buttons, base exclusivity, 3 s release. 1 Intro: washes 60 % blue, 3 s `easeInOut`. 2 Verse: heads 70 % warm on Audience, 2 s, positions 4 s. 3 Pre (`wait 8`): bar 100 % amber, washes down to 30 %, 1 s in / 3 s out. 4 Chorus: everything 100 % white, 0.5 s in / 2 s out. 5 Outro (`follow 4`): heads 20 %, pan and tilt released, 6 s |
| 10 | Chase | Washes 201–204 one at a time in red, `bounce`, one step per beat of Speed 1 (×1), crossfade 0.25 |

| Control | CC | Action |
|---|---|---|
| Knob 1 / knob 2 | 16 / 17 | Song / Chase fader |
| ▶ (play) | 41 | GO the song |
| ◀◀ (rewind) | 43 | BACK |
| ● (record) | 45 | release the song |
| ▶▶ (fast-forward) | 44 | chase on/off (its first button, `toggle`) |
| cycle | 46 | tap tempo on Speed 1 |
| Knob 3 | 18 | Speed 1's multiplier: ×¼, ×½, ×1, ×2, ×4 across the knob |

Tapping locks within two taps: every tap moves the beat grid onto the tap, and from the
second tap on the tempo follows the taps, so a BPM chase steps on them.

**The effects** (`examples/phase5-effects.busk`, run after the song) add a size master
"FX", a group master "Wash level" on group 2, three effect-only slots and a colour cycle in
the song's Chorus. Each slot's cue holds one effect and no values, so its playback has a
`size` fader: the knob scales the effect's size, and the effect starts when the knob
leaves 0 and stops at 0.

| Slot | Playback | Effect |
|---|---|---|
| 11 | Circle | Heads: pan and tilt `add` sine, 15°, ×0.5 on Speed 1 (a circle every 2 beats), MH 2 a quarter turn behind MH 1, growing over 1 s, scaled by "FX" |
| 12 | Pulse | Washes: intensity `multiply` sine, size 0.8 (down to 20 % of the look below), once per beat, a wave across the four, scaled by "FX" |
| 13 | Bar wave | Bar: intensity `absolute` sine 0..1, once per beat, mirrored from both ends (`wings 2`); over a look, only its crests show (HTP) |
| 9/4 | Chorus (Song) | Bar: a red → green → blue cycle at 0.25 Hz, around the 12 cells; it tracks into the Outro |

| Control | CC | Action |
|---|---|---|
| Knobs 4 / 5 / 6 | 19 / 20 / 21 | Circle / Pulse / Bar wave size |
| Knob 7 | 22 | "FX" size master |
| track ◀ / track ▶ / marker set | 58 / 59 / 60 | Circle / Pulse / Bar wave on and off |

A tap keeps every BPM effect where it is and closes the gap to the new beat grid over one
beat, so nothing jumps and one beat later the effect is on the beat again.

### Surfaces

**The surfaces** (`examples/phase6-surfaces.busk`, run after the effects) turn on soft
takeover for the nanoKONTROL2, add a web surface "Phone" and a fade-time master "Fade", and
build a second page:

| Page 2 "Washes" | Playback | Content |
|---|---|---|
| 1–4 | Wash Blue / Red / Green / Amber | Washes at 100 % in colour preset 1–4; exclusivity `wash` (one at a time); buttons `toggle`, `swop`, `release` |
| 8 | Manual | Bar at 100 %: cues 1–3 blue, red, green, `wrap`; a `crossfade` fader; buttons `go`, `back`, `release` |
| 9–13 | Song, Chase, Circle, Pulse, Bar wave | The knob playbacks of page 1, on the same knobs |

The song gets a fourth button, `goto` its Chorus (`playback 9 goto 4`), which the phone
shows. The controller turns the pages and lights its LEDs (set the nanoKONTROL2's LED mode
to **External** with the KORG KONTROL Editor; in the factory mode a button lights only
while pressed):

| Control | CC | Action, LED |
|---|---|---|
| marker ◀ / marker ▶ | 61 / 62 | previous / next page |
| S, R buttons | 32–39, 64–71 | LED: the slot's playback is active |
| M buttons | 48–55 | LED: its flash is up, or its swop held |
| ▶, ◀◀, ● | 41, 43, 45 | LED: the song is active |
| ■ | 42 | LED: blackout is on |
| ▶▶ | 44 | LED: the chase is active |
| cycle | 46 | LED: the beat of Speed 1 |

* **Pages.** The current page is the engine's, one for every surface: the controller, the
  phone and the console (`page 2`, `page next`) turn the same page, and the status line
  and the phone show it. Page buttons stop at the first and last page. A flash held
  through a page change stays on its playback until released.
* **Soft takeover.** After a page change (or after the phone or the console moved the
  playback), a fader does nothing until it reaches the playback's level, within 2 %, or
  crosses it; then it follows. Masters on knobs take over the same way.
* **Swop.** While a `swop` button is held, only that playback's intensity shows: every
  other playback's HTP intensity is suppressed (except those with `protectFromSwop`), and
  colours and positions stay where they are. Releasing it brings everything back as it was.
* **Crossfade faders.** A `crossfade` fader runs the playback's next cue by hand: moving it
  from one end to the other runs the transition in step with the fader (every timing of
  the cue scaled to the travel), and the other end becomes its rest, so the next cue runs
  on the way back. Progress never goes back: stopping holds the mix, and moving back does
  nothing until the fader passes its furthest point. GO and BACK still run cues in real
  time.
* **The fade-time master.** While "Fade" is up, cue transitions and releases take `10 s ×
  level²` (2.5 s at half, 10 s at full) instead of their own times; at 0 the cues' times
  apply. Chase steps, an explicit `release N <seconds>` and the programmer's fade keep
  their own times.
* **The phone.** It shows the current page's strips: a fader (drag it), the buttons by
  function, the current cue; the header has the page arrows, blackout, the grand master,
  TAP with the tempo and a beat dot, and the fade time. It sends the same commands as the
  controller, so both drive the show together.

### Choosing the network interface

An sACN multicast route sends out of the interface named by its `destination.iface`. The
example shows say `eth0`; list your interfaces with `ip -br link` (Linux) and use the wired
one that reaches your sACN node, for example:

```json
{ "id": "r1", "universeId": "u1", "enabled": true, "protocol": "sacn", "universe": 1,
  "priority": 100, "destination": { "kind": "multicast", "iface": "enp5s0" } }
```

`iface` may be an interface **name** (Linux) or the interface's **IPv4 address** (any
platform). For unicast to one node, use `{ "kind": "unicast", "host": "10.0.0.20" }`; the
host is resolved once, when the run starts. The multicast TTL is 1 (one subnet) and
loopback stays on, so an sACN viewer on the same machine sees the traffic. Every 10 s
busk also announces the universes it sends on E1.31's discovery universe (64214), out of
the interfaces its multicast routes use.

An **Art-Net** route (`route add 2 artnet 0.0.1`, a Port-Address as net.sub.universe)
broadcasts on its interface's broadcast address (`{ "kind": "broadcast", "iface": "eth0" }`)
or sends to one node (`route add 2 artnet 0.0.1 unicast 10.0.0.20`). Every 2.5 s busk
polls the network (ArtPoll): a node on the interface's network that answers with an output
on the route's Port-Address then gets that universe unicast instead of the broadcast, and
a node silent for 10 s is forgotten (broadcast again). busk answers polls too, as a
controller named after the show's sACN source name. It listens on UDP 6454; if another
Art-Net program holds the port, busk sends from another one, without discovery, and says
so.

A **DMX-USB** route names a serial device: `route add 3 dmxusb enttecPro /dev/ttyUSB0 [hz
40]` (`dmxking` for a DMXking ultraDMX). The widget makes the DMX signal itself, at the
route's `refreshHz` (1–40); busk sends it a frame when the universe changes and once a
second otherwise. Pulled out, the route reports the error and tries to reopen the device
once a second, so output resumes when it is plugged back in (a device missing when the
run starts is reported and left out, like any route that cannot open). An Open DMX USB (FTDI without
a processor) needs breaks timed by the host and is not supported. On Linux, opening
`/dev/ttyUSB*` needs the `uucp` group (Arch) or `dialout` (Debian, Ubuntu).

`python -m busk …` works too.

### Values files

A values file sets what **uncontrolled** slots output: the resolver starts every tick from
it instead of the registry defaults, and playbacks layer on top. (In Phase 1, before the
resolver, it was the engine's whole static output; the Phase 1 goldens and the Phase 1.5
hardware checklist still use it.) It is a JSON list of park-shaped entries, so it reuses
the show schema:

```json
[ { "slot": { "target": { "fixtureId": "fx-mh1", "element": 0 }, "attribute": "pan" }, "value": 90 },
  { "slot": { "target": { "fixtureId": "fx-mh1", "element": 0 }, "attribute": "colorWheel" },
    "value": { "slot": "red" } } ]
```

Later entries override earlier ones for the same slot. Entries are stricter than cue
entries: an attribute the target doesn't have, a discrete `slot` that isn't one of the
channel's options, or a `wheel` that isn't the channel's wheel is an error (with a path
such as `values[3].slot.attribute`), where a cue drops the value for that target with a
warning (§6.3).

## The console

The console speaks in user-facing numbers (`fixture 101`, `group 2`, `preset color 1`,
`cue 10/1`, `playback 3`) and turns them into ids; everything it does goes through the
session, as the web remote's commands do. `help` prints the grammar.

| Area | Commands |
|---|---|
| Selection | `sel fixture 101 thru 104`, `sel group 1, group 2`, `sel + fixture 201`, `sel - group 2`, `sel 301.3 thru 301.6`, `sel none`, `sel playback 3` |
| Values | `set intensity 80%`, `set pan -45`, `set color 1 0.5 0 w 0.2`, `set gobo1 breakup`, `set pan spread -30 30 [center\|edges]`, `set color preset color 1`, `preset position 1` |
| Programmer | `clear`, `blind on\|off`, `fade 2` (programmer changes fade over 2 s), `programmer` |
| Record | `record group N`, `record preset <pool> N [global\|profile\|target]`, `record cue L/C [only <family>…] [freeze]`, `record slot S [only <family>…]`; each takes `merge`, `replace` or `remove` and a `"name"` |
| Patch | `universe add 1 "Stage"`, `fixture add 101 thru 104 "Generic Spot 16ch" mode 16ch at 1.1`, `fixture 101 patch 2.1`, `fixture 101 patch none` |
| Output | `route add 1 sacn 1 [unicast 10.0.0.20 \| multicast IF]`, `route add 1 artnet 0.0.1 [unicast 10.0.0.20 \| broadcast IF]`, `route add 1 dmxusb enttecPro\|dmxking /dev/ttyUSB0 [hz 40]` |
| Surfaces | `surface add midi "nanoKONTROL2"`, `surface add osc "Touch" [port 8000] [feedback 10.0.0.5:9000]`, `surface add web "Phone" [port 8080] [on 10.0.0.2]`, `surface "nanoKONTROL2" pickup soft\|jump` |
| Bindings, feedback | `bind "nanoKONTROL2" cc 1 0 fader 1`, `… cc 1 32 button 1 1 [led]`, `… cc 1 7 fader playback 18 [motor]`, `… cc 1 23 master gm`, `… cc 1 18 master "Speed 1"`, `… cc 1 46 tap ["Speed 1"]`, `… cc 1 42 blackout [momentary]`, `… cc 1 62 page +1`, `… note 1 60 page 2`, `bind "Touch" osc "/fader/1" fader 1 [display osc "/label/1"]`, `bind "nanoKONTROL2" clock tap`, `… cc 1 60 release all [2]`, `… note 1 61 output off`, `feedback "nanoKONTROL2" cc 1 32 thru 39 led\|motor\|display\|none`, `unbind "nanoKONTROL2" cc 1 60 [thru 61]` |
| Pages | `page 2`, `page next\|prev`, `page add 2 ["Washes"]`, `page 2 slot 1 playback 14`, `page 2 slot 5 clear`, `record slot 2.1`, `playback 9 goto 4` |
| Edit | `playback 3 exclusivity color`, `cue 3/1 timing.fadeIn 1`, `playback 1 buttons ["toggle", "flash", "release"]`, `show meta.title "Club Night"`, `rename group 1 "Heads"`, `delete cue 10/2` |
| Timing, triggers | `cue 9/1 time 3 easeInOut`, `cue 9/3 time 1/3 delay 0/1`, `cue 9/2 time position 4 [delay 1] [easeOut]`, `… bezier 0.4 0 0.2 1`, `cue 9/3 wait 8`, `cue 9/5 follow 4`, `cue 9/2 go`, `cue 9/5 release group 1 [only pan tilt]` |
| Cue lists, tempo | `cuelist 9 tracking true`, `cuelist 10 chase bpm ["Speed 1"] [x 2] [forward\|reverse\|bounce\|random] [crossfade 0.25]`, `cuelist 10 chase hz 4`, `cuelist 10 sequence`, `master add speed "Speed 1" [bpm 120] [steps 0.5, 1, 2]` |
| Effects, masters | `effect add "Circle" [id fx1] [hz 0.5 \| bpm ["Speed 1"] [x 0.5]] [size 15] [low 0 high 1] [phase 0 180] [groups N] [blocks N] [wings 2] [forward\|reverse\|bounce] [fadein 1] [sizemaster "FX"] [speedmaster "Speed 1"]`, `effect remove fx1`, `effect clear`, `effect template add "Name" [{…layers…}]`, `cue 9/4 effect rainbow size 0.5`, `master add size "FX"`, `master add group "Wash level" group 2`, `master add fadetime "Fade"` |
| Perform | `go 9`, `back 9`, `goto 9 4`, `release 3 [2]`, `fader 3 75%`, `gm 0.5`, `master "Speed 1" 0.75`, `tap ["Speed 1"]`, `bpm ["Speed 1"] 128`, `blackout on\|off` |
| Safety, panic | `park fixture 204 intensity 0`, `park group 2 color 1 0 0`, `unpark fixture 204 [intensity]`, `unpark all`, `fixture 101 thru 102 limits tilt -90 10`, `fixture 301 limits intensity 50%`, `fixture 101 limits none`, `safety strobe 3\|off`, `highlight on\|off`, `release all [2]`, `output on\|off` |
| Profiles | `profile update "Generic Spot 16ch"` (to the library's other revision), `list profiles` |
| Session | `undo`, `redo`, `save [PATH]`, `list fixtures\|groups\|presets\|cuelists\|playbacks\|pages\|universes\|routes\|surfaces\|bindings\|masters\|profiles\|effects\|park`, `list cues 9`, `library`, `info`, `status`, `source FILE`, `quit` |

* **Numbers.** Fixture `N` is every element of fixture `N`; `N.E` is element `E`, counted
  from 1 (`301.3` is the PiX's third cell). Page slots and buttons count from 1, like the
  physical controls. `thru` keeps its direction (`104 thru 101` selects backwards).
* **Recording keeps intent.** A cue references a group wherever one covers the targets
  that have the attribute (the biggest first; ties go to the group with fewer members,
  then the lower number) and keeps preset references, so editing the group or the preset
  later updates the look; `freeze` records explicit targets instead. Differing literal
  values are recorded per target. A preset cascades from the requested scope: one global
  value if every target agrees, else per profile, else per target, and the reply says so
  (`pan: 4 target values (values differ)`). Without `merge`, `replace` or `remove` a record
  command only creates, so a typo never overwrites anything.
* **`record slot S`** on an empty slot of the current page (`record slot 2.1`: slot 1 of
  page 2) creates a cue list, its cue 1, a
  playback (Appendix A's Blue playback without its exclusivity: band 50, `master` fader,
  `toggle` and `flash` buttons, `threshold` LTP at 2 %, auto start/release, a flash that
  brings LTP, 1 s release) and puts it in the slot, as one undo step. On an occupied slot
  it records into the playback's cue, with `merge`, `replace` or `remove`.
* **Tracking lists record changes only.** In a list with `tracking` on, `record cue`
  stores only the values that differ from what the list already tracks into that cue
  (`recorded cue 9/2: 4 entries; 8 values tracked from cue 9/1`); a cue whose values all
  track is created without entries. `sel playback N` selects the targets of the
  playback's *current* cue (its tracked state), or of its first cue while it is idle.
* **Timing.** `cue L/C time <in>[/<out>]` sets the cue's fade in and out (out defaults to
  in), with an optional `delay` and curve (`linear`, `easeIn`, `easeOut`, `easeInOut`,
  `snapStart`, `snapEnd`, `bezier x1 y1 x2 y2`); with a family name it sets that family's
  own timing. In a chase, cue timing and triggers are ignored except the curve: the
  crossfade sets the step fade. Speed masters have no numbers, so they are named in quotes;
  `tap` and `bpm` without a name use the show's only speed master.
* **Effects.** `effect add` adds an effect on the selection, in selection order (which sets
  the phase spread), to the programmer, where it runs live at band 100 like its values;
  `programmer` lists it (`effect fx1 'Circle' on 101, 102, bpm 'Speed 1' ×0.5, size 15`)
  and `record cue` or `record slot` records it (`only` filters it by its attributes'
  families, `merge` adds or replaces it by id, `remove` drops it). The template is the
  show's of that name, else the built-in library's (Circle, Pulse, Wave, Chase, Saw,
  Sweep, Flicker, Rainbow, listed by `library`), embedded into the show first. Defaults:
  the library's size, `low`/`high` and phase for that template, ×1 on the show's only
  speed master (else 1 Hz), and the id `fx<n>` that neither the programmer nor any cue
  uses. A slot recorded with only effects gets a `size` fader. `list effects` lists the
  show's templates, `list cues` counts each cue's effects, and `cue L/C effect <id> <prop>
  <value>` edits a recorded instance.
* **Pages and surfaces** (Phase 6). `page N`, `page next` and `page prev` turn the
  engine's page (`list pages` marks it with `*`); `page add` creates one with empty slots,
  and `page P slot S playback N` fills a slot. `surface add osc` and `surface add web`
  take their options in any order; ports default to 8000 and 8080 and must be free among
  surfaces of that kind, and surface names are unique. `bind` takes a feedback after the
  action (`led`, `motor` or `display`, sent to the input's own address unless another
  follows); `feedback "<surface>" <input> [thru <n>] led` adds feedback to the bindings
  already on those inputs (`none` removes it), and an input without a binding is an
  error. `list surfaces` and `list bindings` show ports, pickup and feedback.
* **Safety, panic and profiles** (Phase 7; see [Safety](#safety)). `park` replaces what
  was parked on the slots it names and `unpark` removes it, each as one undo step (park
  entries have no ids, so the whole list is set). `limits` sets one key of each fixture's
  limits and keeps the others. `release all` and `output on|off` are performance
  commands, like `go`, and can be bound; `bind` adds a binding next to those already on an
  input, so `unbind "<surface>" <input> [thru N]` frees it first (the safety script does
  so with marker SET, which toggled the bar wave). `info` adds the processes, their
  restarts and the event log file.
* **Undo** walks one timeline of show edits and programmer changes (1000 steps): the last
  action, whatever it was. Blind and the programmer's fade time are modes and are never
  undone. Saving is not a step.
* **Errors** name what you typed (`no group 7`, `preset color 1 exists: add merge or
  replace`), and an edit that would make the show invalid lists every place it breaks:

  ```
  busk> delete group 2
  error: deleted groups[1]: rejected, the show would not be valid
    cueLists[1].cues[0].entries[1].targets.groupId: Unknown group 'g-par'
  ```

* **Scripts** are console lines in a file (`#` starts a comment); `source FILE` runs one
  from the console and `busk run --script FILE` before it. A script stops at its first
  error and says where (`build.busk:12: sel group 7`).

## Development

```bash
uv run pytest                                          # 3175 tests + 1 opt-in skip; no packet leaves the machine
uv run pytest -m perf -s                               # conversion, output, tick, GO-burst, chase, effect, feedback and safety benchmarks (opt-in)
uv run pytest -m soak -s                               # a 60 s soak with an engine kill, a console kill and an unplug (opt-in, Phase 7)
uv run python bench/edit_latency.py [--processes]      # live-edit latency and engine stalls (Phase 3; Phase 7: across processes)
uv run python bench/surface_load.py [SECONDS] [--processes]   # ticks under a phone, MIDI, OSC and feedback load (Phase 6)
uv run python bench/transport.py                       # install sizes and load times on the console → engine link (Phase 7)
uv run python bench/soak.py --hours 1 [--chaos standard|fast|none] [--seed N] [--report FILE]   # the soak (Phase 7)
BUSK_REGOLDEN=1 uv run pytest tests/test_build_from_scratch.py tests/test_song_stack.py tests/test_effects_show.py tests/test_surfaces_show.py tests/test_safety_show.py   # rewrite the goldens, then review
uv run ruff check . && uv run ruff format --check .    # lint + format
uv run mypy                                            # --strict on src/
BUSK_TEST_IFACE=enp5s0 uv run pytest tests/test_sacn.py -k multicast   # real multicast (opt-in)
```

The tests never touch a real network by default: `run` tests use copies of the shows
whose routes are disabled (`builders.offline`) or send unicast to a localhost receiver on
an ephemeral port (`builders.localhost_route` + the `receiver` fixture, which patches
`SACN_PORT`). The one real multicast test runs only when `BUSK_TEST_IFACE` names an
interface; it sends universe 63999 at priority 0, so a live rig ignores it. OSC, the web
server, Art-Net (with a fake node answering ArtPoll, `artnet_node.py`) and sACN discovery
are tested on 127.0.0.1 with ephemeral ports, and DMX-USB on a pseudo-terminal standing in
for the widget, unplugged by closing it.

Nor do they touch your state directory: every test gets its own `XDG_STATE_HOME`, so
autosaves and the installation CID stay in temporary directories.

The tests never depend on the MIDI devices plugged in either: `run` tests see a fixed
port list. Three tests (`-m midi`, part of the default run) send a CC and MIDI clock
through real virtual ALSA ports into the bindings, and feedback out of one; they are
skipped where there is no `/dev/snd/seq`.

The process tests (`test_processes.py`, `test_watchdog.py`, `test_console_restart.py`)
start real `busk run` process trees (`process_harness.py`) and kill, stop and restart their
children while an sACN receiver on localhost checks the output
(`tests/process_site/sitecustomize.py` points the children's sACN routes at it, as the
`receiver` fixture does in-process).

The suite also passes on Python 3.12 and 3.13, for example
`UV_PROJECT_ENVIRONMENT=/tmp/venv-3.12 uv run --python 3.12 pytest`.

| Test file | Proves |
|---|---|
| `test_attributes.py` | The registry matches the §5.3 table row by row |
| `test_schema.py` | Appendix A validates; strictness (extra keys, types, ranges, NaN) holds for every `TypedDict` |
| `test_validate.py` | Every semantic rule fires with the exact `(severity, path)`, including the Phase 1 profile rules, Phase 2's duplicate preset values, Phase 5's effect rules, Phase 6's surface, binding, feedback and goto rules and Phase 7's limits, park, safety, route and command rules (the strobe cap below a fixture's slowest strobe, `OUTPUT` off on something that may not be a button); one mistake never cascades; all issues are collected |
| `test_compile.py` | Golden base-image bytes; byte splitting; patch edge cases; Phase 7: warnings for unpatched fixtures a playback or a park entry drives |
| `test_slots.py` / `test_lanes.py` | Slot allocation order, lane layout, defaults (zoom midpoint, shutter open), options, encoding |
| `test_channels.py` | Addresses, non-adjacent fine bytes, orientation folding, `invert`, option tables, byte ownership on overlap |
| `test_convert.py` | Golden bytes, worked out by hand, for **both** converters: §7.8, Appendix A defaults, rounding, 16/24-bit, curves, multi-segment maps, colour, shutter, pan/tilt |
| `test_convert_properties.py` | Hypothesis: fast == reference byte for byte; round-trip within one DMX step; monotonic; intensity 0 ⇒ dark |
| `test_real_fixtures.py` | **The done criterion:** chart-derived DMX for the MH-X25, ML-56 RGBW and COLORband PiX |
| `test_values_file.py` | Values-file checks, error paths, override order |
| `test_clock.py` / `test_engine.py` | Clock contracts; fixed-rate ticking, drop-don't-spiral, determinism; frames are converted; Phase 7: a tick that raises is counted and the schedule goes on, consecutive errors counted |
| `test_sacn.py` | E1.31 layout against a header golden written by hand; every field parsed back by an independent parser (`sacn_receiver.py`); multicast groups; per-universe sequences shared by routes; open, send, termination and error handling over real localhost sockets; universe discovery packets (goldens for 1 and 600 universes), interval and changes |
| `test_sacn_policy.py` | Send on change, 3 repeats, keep-alive inside 0.8–1.0 s, a due keep-alive never skipped (table-driven and hypothesis, with jitter and overruns) |
| `test_output_scheduler.py` | Change detection per universe, route isolation and fault counting, final pass and close on stop, hold last frame, 44 Hz; `build_routes` notices; Art-Net routes opened and sent, a taken Art-Net port reported |
| `test_console_output.py` | The Phase 0 line format and print-on-change, now as the `--console` sink |
| `test_bus.py` | Command validation at submit time (supported types, ids, every master kind, levels clamped, release times, a GOTO's cue, a BPM in range; Phase 6: `PAGE`, `SET_FADER` and `PLAYBACK_BUTTON` by playback or slot, `BLACKOUT` with or without `on`), `TOGGLE_PLAYBACK`, FIFO, envelopes; every command type is applied by the engine or sent to the session |
| `test_compile_cues.py` | Appendix A's cues as golden arrays; group expansion; preset scope precedence; spreads (linear, center, edges, `n = 1`, colour, members without the attribute); dropped targets and options with warnings; last entry wins; clamping; lane partitions; compiled playbacks, pages sorted by number, masters |
| `test_limitations.py` | Appendix A has no ignored feature since Phase 7 (8 in Phase 3, 4 in Phase 4, 2 in Phase 5, 1 in Phase 6: its limits); every other ignored feature is reported with its path; what Phase 6 plays (pages, every button and fader function, soft pickup, fade-time masters, feedback, OSC and web surfaces, Art-Net and DMX-USB) and what Phase 7 enforces (limits, park, a stall that darkens) is no longer listed |
| `test_curves.py` | The six curves and Bézier: formulas, endpoints, monotonicity, Bézier against CSS reference values, interning |
| `test_fades.py` | Envelopes; `ContributionSet`: retarget semantics (unchanged slots keep their fade, a slot changes as a whole, scaled presences, NaN extras), the sequence rules, freeze, remap, and five invariants under random retargets (hypothesis) |
| `test_resolver.py` | Every §7.3 and §7.4 behaviour, per-lane weights and per-lane snap thresholds, and Phase 5's relative pass (order, continuous suppression by higher bands, clamps), each checked against the per-slot oracle (`reference_resolver.py`) |
| `test_resolver_properties.py` | Hypothesis: resolver == literal §7.7 oracle within 1e-12 (per-lane weights and relative contributions included); HTP in a band commutative and ≥ every input; LTP lanes in the hull of default and inputs; zero weight is a no-op |
| `test_seq_runs.py` | Per-slot sequence numbers: a contributor split into runs between the other contributors' numbers composites exactly in `(priority, seq)` order (hypothesis against the oracle) |
| `test_playback_runtime.py` | The state machine, one case per row and state; weights per fader mode; the threshold latch; autoStart/autoRelease (`size` faders too); flash, `temp`, `priorityBoost`; exclusivity (own release times, never on flash); release timing; the flash bank's lifecycle |
| `test_masters.py` | The GM scales intensity lanes only; blackout zeroes flashes and override bands; toggling either away and back gives an identical frame and identical runtime state; group masters multiply per member, intensity only, before the GM, and follow live edits |
| `test_tracking.py` | §9.3 tracked states with `block` and `releases`; per-slot timing (in, out, per family, per entry, delays, curves) and what a leaving slot fades with; effects tracked by id, trimmed by releases, replaced in place |
| `test_cue_engine.py` · `test_engine_sequences.py` | GO, BACK and GOTO from every state; wrap and release at the end; exact `follow`/`wait` times; GOTO equals stepping; tracked slots don't steal from a newer bump; frames independent of the tick schedule; effects entering, changing and leaving through GO, BACK, GOTO and auto-GOs |
| `test_tempo.py` | Beat counting, tap tempo (median, tolerance, reset, phase), `SET_BPM`, multiplier steps from the level |
| `test_chase.py` | Step timing, crossfade, the four directions, beat lock, alignment on activation, taps and rate changes, `rate` faders, GO/BACK/GOTO on a running chase, schedule independence; effects on chase steps |
| `test_golden_7_8.py` | **The done criterion:** §7.8 at the resolver and the engine level, logical values and DMX bytes; the release continuation; the exclusivity variant (and its contrast without exclusivity) |
| `test_engine_busking.py` | Release in 0 s equals the frame without the playback; determinism; equal frames at 100 Hz, 37 Hz and random tick schedules; snapshots only on change (group and size levels listed, effect phases not; beat anchors move only at taps and tempo changes); a raising command is counted and ticking goes on; no memory growth over 10 000 ticks |
| `test_bindings.py` / `test_midi.py` | Every action and button function (`back`, tap, speed, group, size and fade-time masters included); page faders and buttons as `SET_FADER`/`PLAYBACK_BUTTON` by slot with their control; `select` on the snapshot's page; latching and momentary blackout; CC button edges; 1-based channels; errors reported once and never raised; MIDI message translation; MIDI clock as beats (Start, Song Position); MIDI output messages; port matching; a CC and 48 clocks through a virtual ALSA port reach the bus, and feedback reaches a virtual input |
| `test_cli.py` | `validate`; `run [--values] [--console]`; the Phase 1.5 done criterion (golden bytes over localhost, then termination); route lines and failures; the limitation block; compile warnings; MIDI not found / unavailable; **busking with (fake) MIDI faders** drives the status line and the command counters; the status line's tempo, cue and `size` fader levels; Phase 6: the page, fade time, swop and crossfade progress in the status line, every surface kind opened and feedback sent at start-up (fake MIDI ports, OSC and web on free ports), DMX-USB frames to a pseudo-terminal, the web key |
| `test_patch.py` | Copy-on-write patches: inverse ops restore the show exactly (hypothesis: random op sequences undone step by step and at once), untouched subtrees are the same objects, inputs are never mutated, id paths, protected paths |
| `test_validate_edit.py` | Per-edit validation equals a full `validate_show` on random edits of Appendix A (hypothesis), issue for issue, and normalises exactly like a load; paths are show-level |
| `test_edits.py` | The exact ops of `ADD` / `SET` / `DELETE` / `PATCH_FIXTURE` / `ASSIGN_PLAYBACK`; rejections before validation (protected paths, unknown ids) and by it (every reference to a deleted group, duplicate numbers, structure), and an edit that cannot compile |
| `test_programmer.py` | Selection order under add/remove, groups, `select` playbacks; literal, spread (by selection index), per-target and preset sources; skipped targets counted; range and shape errors; `APPLY_PRESET` scope lookup; clear and blind; dormant values; JSON round trip; `ADD_EFFECT` / `REMOVE_EFFECT` (validated, replaced by id, cleared, dormant) |
| `test_record_group.py` · `test_record_preset.py` · `test_record_cue.py` | Recording rules of phase-3-plan §5.5: the two worked cases (Appendix A's Blue cue rebuilt; the merge), group-cover tie-breaks, registry order, scope cascade and its fallbacks, preset references flattened in presets, shadowing entries removed on merge, `remove`, spread restriction keeping bit-identical lanes, `freeze`, numbering after `"3.5"`, layouts; Phase 4: a tracking list stores changes only; Phase 5: effects recorded, filtered by family, merged and removed by id, kept as group references, and tracked rather than stored when unchanged |
| `test_session.py` | A rejected edit (or a batch whose last command fails) changes nothing anywhere; one undo timeline across programmer and show steps; redo cleared by a new step; blind and the fade time never undone; undo all → the initial show; dormant values return; installs in commit order; a performance command is queued while an edit holds the lock; `post` keeps order; `SELECT_PLAYBACK` on the current cue |
| `test_engine_programmer.py` | The programmer as band 100: overrides playback intensity even downwards, LTP on top; blind; leaving blind re-touches; per-slot order against a band-100 playback; re-setting a value moves it on top; GM and blackout still apply; its fade time on change, clear, blind and undo; its effects (live, blind, faded, tapped, suspending lower relative effects) |
| `test_live_swap.py` | Live edits equal a fresh engine on the edited show: recording into a running cue, re-recording a referenced preset, moving a patch, a slot remap that keeps the programmer's order, deleting a running playback, emptying its cue list; a new universe before the old one, a new route and its removal (Stream_Terminated), new bindings and the `select` button through the session; a values frame follows a remap. Phase 4: edits fade with the cue's timing and keep the stack order, remap mid-fade, re-point by cue id (a deleted cue falls back to the next number), re-derive auto-GOs, carry chases and tempos, and leave untouched lists alone. Phase 5: an edited effect cross-fades on its running clock (main and flash), remaps, and re-times on rate and speed-master edits without a jump. Phase 6: editing the goto cue retargets goto buttons; Art-Net routes and sACN discovery follow live edits |
| `test_compile_incremental.py` | The identity-memoised compile equals a full compile after every step of the Phase 3 build; it reuses the rig and untouched cue lists, and recompiles exactly what read an edited preset or effect template |
| `test_show_file.py` | `.show` and `.json` round trips, byte-identical saves, a failing `os.replace` leaves the original and no temp file, backup rotation, the template, the state directory and CID |
| `test_autosave.py` · `test_recovery.py` | Burst and periodic show autosaves, retention, `session.json`, every row of the recovery table; then `kill -9` of a real `busk run` and a restart that brings back the programmer (with its fade time and effects), the master levels (group, size and fade-time included), the tempo, the page and the unsaved edit |
| `test_console_parser.py` · `test_console.py` | Every grammar row (311 cases, Phase 4's timing, trigger, chase, master and tempo sugar, Phase 5's effect sugar and Phase 6's page, surface, binding, feedback and route sugar included) and its error messages; execution, rendering (`list cues`, `list masters`, `list effects`, the programmer's fade and effects, `library`), scripts and `source`, defaults, Ctrl+C held back during a command and clearing the line at the prompt, quit offering to save |
| `test_build_from_scratch.py` | **The Phase 3 done criterion:** the build script from `busk new`, golden show and golden DMX (checked by hand), a live preset edit, undo all / redo all, save → load |
| `test_song_stack.py` | **The Phase 4 done criterion:** the song script on the built show, golden show, 34 checkpoints of hand-computed logical values and golden DMX, GOTO equals stepping, the tap and multiplier alignment, 100 Hz vs an irregular schedule, save → load |
| `test_waveforms.py` | The nine waveforms against a scalar transcription: key phases, the 0..1 range, `pulse` with zero-length ramps, `random` deterministic per (seed, member, cycle) and `smooth` continuous, `curve` continuous across the cycle (hypothesis) |
| `test_phase_spread.py` | §10.2 wings (mirrored odd wings), blocks, groups and the even distribution of offsets |
| `test_effect_compile.py` | Compiled instances: Appendix A's pulse as golden arrays, members and their offsets, absolute intensity as HTP, `low`/`high` defaults and clamps, palettes per member through preset scopes, rates and masters, warnings for effects that do nothing and members without a palette colour; structural `same`, trimming by releases, patch remaps |
| `test_effect_clock.py` | Hz and BPM positions, the grid start, §5.4's worked example, tap nudges closing over one beat (a second tap mid-nudge too), rate changes (rebase in Hz, re-align in BPM), speed-master steps, switching between Hz and BPM |
| `test_effect_runtime.py` | Enter, leave and change; versions mixed by presence (an exact size morph); sequence rules; four invariants under hypothesis: a pure function of time, ticked or not, no jump at a retarget, values in range |
| `test_effects_engine.py` | Effect playbacks through the engine: Appendix A's pulse, absolute and relative layers, a colour cycle winning the tie with its cue's colour, `size` and `rate` faders, size and speed masters, release and re-activation, taps, the flash bank (`includeLtp`, no doubling, `temp`, hand-over to main on the beat grid, a flash held through a release), schedule independence |
| `test_effect_library.py` | The built-in templates, found by id or name; each validates and compiles without warnings on Appendix A with the console's defaults; bad items and unreadable files are skipped and reported |
| `test_effects_show.py` | **The Phase 5 done criterion:** the effects script on the song show, golden show (`busk validate`: 0 errors, 0 warnings), 29 checkpoints of hand-computed logical values and golden DMX, the group master leaving no trace, taps that move nothing and lock a beat later (with §5.4's numbers), the colour cycle tracking into the Outro, 100 Hz vs an irregular schedule, save → load, the programmer holding a pan under the circle |
| `test_pages.py` | The engine's current page: `PAGE` by number and delta (stopping at the ends), page-relative faders and buttons (a `PAGE` and a `SET_FADER` in one tick resolve on the new page), empty slots, live edits that keep or delete the current page, a show without pages |
| `test_buttons.py` | Every §8.1 button function through the engine, from idle and from each cue, against a twin engine fed the direct command; held flashes across page changes; `goto` buttons; latching blackout |
| `test_swop.py` | Swop suppresses other playbacks' HTP presence, their flashes and effects included (not `protectFromSwop`, not colours or positions); two swops held, one playback swopped from two controls, a swop and a flash, a swop held through a page change, live edits; releasing leaves no trace |
| `test_pickup.py` | Soft takeover: attach within 0.02 or by crossing, detach on any other source, per page and per master (Appendix A and a second page); a hypothesis oracle |
| `test_fade_time.py` | Fade-time masters: `10 s × level²`, the largest master wins, which transitions they replace (against a twin show with uniform times) and which they leave alone |
| `test_crossfade.py` | Manual crossfades: rest ends, progress in step with the fader (equal to GO when moved with the clock, effects included), never reversing (a hypothesis oracle), interruptions by GO, release and live edits |
| `test_feedback.py` | Feedback values per action and kind on the current page; only changes sent, a full send on (re)open, the echo hold, beat LEDs, send errors counted and reported once |
| `test_osc.py` | The OSC codec against the specification's examples (every type tag, bundles, malformed packets); values; input, feedback and the surface manager over localhost sockets |
| `test_websocket.py` · `test_web_api.py` | The WebSocket subset (handshake, framing, limits, close codes, slow and vanished clients, no Nagle delay); the key and origin checks; the JSON protocol (hello, show, state, errors, performance commands only), 30 Hz throttling, held buttons released on disconnect; the page's command list |
| `test_surface_manager.py` | MIDI, OSC and web surfaces open, change and close with live edits; a web surface restarts only on a port or host change |
| `test_artnet.py` · `test_artnet_discovery.py` | ArtDmx against an independent parser; Port-Addresses, sequences, keep-alive, a taken port; ArtPoll every 2.5 s, ArtPollReply (ours and parsed), nodes found, unicast to them on the interface's network, forgotten after 10 s |
| `test_dmxusb.py` | The Enttec messages and parameters; frames on change and keep-alive; partial writes; unplug and replug on a pseudo-terminal |
| `test_surfaces_show.py` | **The Phase 6 done criterion:** the surfaces script on the effects show, golden show (`busk validate`: 0 errors, 0 warnings), 24 checkpoints driven by the controller and the phone together (levels and colours per group, LEDs, faders, page, progress, status), golden DMX, 100 Hz vs an irregular schedule, save → load, the phone over a real WebSocket |
| `test_safety.py` | Park and limits in the stage order: a parked slot wins over playbacks, effects, the programmer and the masters, blackout still darkens a parked intensity, live park edits across a repatch, limits on both ends, on every element and on parked values, a circle flattened at a limit; the same frames on any tick schedule |
| `test_strobe_cap.py` | Strobe lanes clamped; intensity effects capped in flashes per second (`step` counts its rises, `curve` its peaks), Hz clamped, BPM halved onto the beat grid; taps, `SET_BPM` and steps re-rate without a jump, and so does a live edit of the cap; nothing capped without `safety` |
| `test_highlight.py` | Highlight's values and bytes (`highlightDmx`, never pan, tilt or parked slots), after the masters, under blackout, park and limits; live in blind; autosaved and never undone |
| `test_panic.py` · `test_stall_output.py` | `RELEASE_ALL` from every playback state (own release times or one given; held flashes and swops dropped; the programmer kept), `OUTPUT` off and on per protocol (sACN Stream_Terminated once, then the frame again); a stalled engine's output held, or dark with everything but intensity held, from the conversion plan's dark bytes, and frames again after a stall |
| `test_wire.py` | Framing over socket pairs (partial reads, empty and 64 MiB messages, end of file); raw frames; the engine view; structural sharing preserves identity, so a live swap through the wire keeps its fades; chunked installs; the Phase 3 build through the wire byte-identical |
| `test_restore.py` · `test_engine_host.py` · `test_links.py` | Restore from a snapshot (masters, tempos and beat anchors, blackout, output, page, playbacks in activation order; a static look byte-identical); the engine process's links, layouts, frames, stats and exits, and the benches' engine process; `RemoteBus` (hello and welcome, queued commands during a restart, the show stamp, the engine's own remap from slot keys) |
| `test_processes.py` · `test_watchdog.py` · `test_console_restart.py` | Real process trees: quit, a failing script, `SIGTERM` and `kill -9` of the root, `--duration`, `--stats`, the same start-up lines as `--threads`, `info`'s pids; a killed engine back with the same frame and no gap at the receiver, a stopped one stalled at 1 s and restarted at 3 s, the dark stall, commands in the gap, the crash-loop guard, giving up; a killed console back while the show runs on (the phone reconnects), unsaved edits and patches undone on stage, giving up |
| `test_reconnect.py` · `test_hotplug.py` | Routes that fail at start-up or while sending reopen (sACN, Art-Net with a changed broadcast address, a DMX-USB pseudo-terminal), print once, and keep their sequence numbers; MIDI devices unplugged and plugged back in, a missing one opening when it appears, feedback reconnected with a full send (one test through a real virtual ALSA port) |
| `test_rate_limits.py` | Token-bucket arithmetic; a phone at 1000 commands/s held to 120/s with one error a second and every release delivered; per-client buckets; OSC drops counted and reported, all-zero messages passed; 5000 commands applied over 10 ticks in order |
| `test_ofl.py` · `test_gdtf.py` | One case per row of the import tables and every channel rule; **the TupperDMX check**: each hand-transcribed mode against its import, slot by slot, on one compiled show; the library's on-the-fly import; `busk import`; GDTF's DMX value notation at 1–3 bytes, CIE xyY against known points, wheels, cells from geometry references, reported items, a `DOCTYPE` bomb and a 40 MB `description.xml` refused |
| `test_eventlog.py` | Logged runs replay byte-identically: edits, programmer changes, undo and redo, performance commands, a restore, rotation; `busk replay`'s output and `--frames` |
| `test_safety_show.py` | **The Phase 7 done criterion A:** the safety script on the surfaces show, golden show (`busk validate`: 0 errors, 0 warnings), 13 checkpoints of hand-computed values (limits, park, the strobe cap, highlight, blackout over highlight, `release all`), the Circle under the tilt limit against a twin, output off and on at a receiver, golden DMX, 100 Hz vs an irregular schedule, save → load |
| `test_soak.py` (13 unit tests; one `-m soak`) | The soak harness's rules on made-up readings (which gaps are drops, outages and their recoveries, memory bounds, the load never touching the Circle); with `-m soak`, **done criterion B** for 60 s with an engine kill, a console kill and an unplug |
| `test_perf.py` (`-m perf`) | Conversion of the §19 reference rig takes < 1 ms; one output cycle for 64 sACN universes takes < 5 ms (medians); a busking tick takes p99 < 1 ms on Appendix A (its Slow Pulse running) and < 10 ms on the reference rig with 60 playbacks mid-fade, 60 cue transitions, 8 chases stepping, or 20 effects over the 60 looks; a tick with 60 GOs takes a median < 20 ms; one Art-Net output cycle for 64 universes takes < 5 ms; feedback values for 200 bindings take < 1 ms; Phase 7: a tick on Appendix A with park, limits and a strobe cap costs < 10 % more than without (median ratio 1.01) |

**Benchmark** (dev machine, Python 3.14.7, numpy 2.5.4; Phase 5 numbers, ranges over
several runs): the §19 reference rig, 64 universes × (4 Appendix A spots, 6 MH-X25, 10
ML-56, 9 COLORband PiX), is 1 856 fixtures, 20 608 slots and 28 928 slot-driven channels.
Conversion takes **0.29 ms median**. Validation takes 11 ms and compilation 0.21 s; both run
once per load, never in the tick. One output cycle with all 64 universes changed (64 sACN
packets to a localhost socket) takes **0.07 ms median, 0.08 ms p99**, against a 22.7 ms
cycle.

A whole **busking tick** (due events, drain, playbacks, gather, resolve, masters,
conversion, publish) takes **0.08 ms mean** (p99 0.09 ms) on Appendix A with every playback
up, its Slow Pulse effect running at full size (Phase 4, without it: 0.06 ms). On the
reference rig with **60 active playbacks in 3 bands**, all mid-fade, covering 177 582
lanes per tick between them, it takes **1.9–2.0 ms mean, 2.1–3.2 ms p99**, of which the
resolver is 0.78 ms (Phase 3: 0.89 ms mean; fades are now per lane). With 4-cue tracking
lists, **all 60 playbacks mid-transition** (191 000 lanes; position, colour and intensity
on their own times, with delays, curves and a Bézier) take **3.0–3.3 ms mean, 3.2–4.5 ms
p99**, and **8 BPM chases stepping 16 times a second** over the 60 looks take 3.8–4.1 ms
mean on the ticks where they step. All inside the 10 ms tick and around §19's 4 ms target.

**Effects** (Phase 5): **20 effect playbacks over the 60 looks** (5 circles, 5 pulses, 5
waves and 5 colour cycles from the built-in library, BPM-locked at ×¼ … ×2; 108 780 effect
lanes, 15 relative contributions per tick under 20 looks in a higher band) take **3.4–3.7
ms mean, 3.6–4.4 ms p99**: about 1.5 ms over the same rig without effects, inside the
plan's estimate of 1–2 ms. The mean meets §19's 4 ms target, the p99 is around it, and
none of the plan's three fallback optimisations was needed.

**Surfaces** (Phase 6; phase-6-plan step 19). Engine ticks are 3–6 % slower than in Phase 5
(the page, beat anchors and takeover state): 0.08 ms mean on Appendix A, 1.9–2.0 ms mean
on the reference rig with 60 playbacks. One **Art-Net** output cycle with all 64 universes
changed takes **0.07 ms median**, like sACN, and the **feedback values** of 200 bindings
take **0.05 ms mean**. `bench/surface_load.py` runs each rig for 20 s at 100 Hz on the
real clock under surface load: a phone (a WebSocket client sending 60 `SET_FADER`/s and
reading every state), 100 MIDI events/s, 60 OSC messages/s, feedback at 30 Hz and a probe
timing commands from submit to applied:

| Rig | Overruns | Tick p99 / max | States/s | Phone round trip p50 / p95 | Command latency p50 / p95 | Feedback |
|---|---|---|---|---|---|---|
| demo (18 playbacks, 59 bindings) | **0 in 2000** | 2.6 / 5.3 ms | 29.5 | 24 / 40–41 ms | 4.9–5.0 / 5.5–5.8 ms | 5 msg/s |
| reference (61 playbacks, 208 bindings) | **31–56 in 2000** (1.6–2.8 %) | 11–12 / 15–20 ms | 29.6 | 27–28 / 44 ms | 10.4–10.6 / 15 ms | 102 msg/s |

The demo rig meets the plan's hard target, no overrun under surface load. **The reference
rig misses the soft target of 1 %**: its MIDI and OSC fader moves start all 61 playbacks,
and the overruns come with them (without those moves: 0 overruns, p99 6.9 ms). The cost
is the whole rig running while the input, broadcaster and feedback threads share the GIL
with the engine; the bench's phone and probe run in the same process too, which a real
phone does not. Phase 7's process split closes it: 0.4 % across processes (below).

**Two Phase 4 targets are missed** (details in phase-4-plan step 18):

* A tick in which **all 60 playbacks GO at once** takes **16–18 ms** (gate: 10 ms). A
  retarget rebuilds its partitions over all of a playback's lanes, about 120 µs for 1 500
  lanes and 0.7 ms for 28 000, so 60 of them cost about 10 ms before the tick itself.
  (It was 55 ms before three fixes: sort-based distinct values instead of NumPy's hashing
  `unique`, a fast path for a cue over the same lanes, and no retarget for lists an edit
  did not touch.) Such a burst overruns into the next tick while the output thread keeps
  sending the last frame; a retarget of only the changed lanes, in place, would fix it.
* **Live edits on the §19-sized rig** overrun more ticks than in Phase 3 (below). Phase
  7's process split closes this one: 1 overrun in 1 911 ticks across processes.

**Live edits** (`bench/edit_latency.py`, phase-3-plan step 13): the engine runs at 100 Hz on
the real clock with autosave running while 50 edits of each kind go through the session.
On the demo rig (the Phase 3 build) an edit takes **2–4 ms median, 5.5–7.5 ms p95** with
**0 overruns** (max tick 6.4–7.2 ms; one run started straight after the perf suite
overran once, at 11.4 ms). A script that edits back to back is harsher: `busk run
--script examples/phase3-build.busk` (about 150 edits in under a second) overruns 0–2
ticks while it runs (max about 15 ms); playing the built show afterwards overruns none. On a §19-sized rig (400 fixtures over 64 universes, 4 300
slots, 40 groups, 100 presets, 100 cue lists, 20 playbacks running) edits take 39 ms
median, 124–136 ms p95 (a patch, which rebuilds the rig, ≈ 125 ms; a recorded cue ≈ 15
ms), inside the 250 ms target, but **about 10 % of ticks overrun while edits run** (130–175
of about 1 600; max 52–81 ms; Phase 3: about 2 %, max 22.7 ms). Nearly all of them apply an install: one takes
about 1 ms alone (5 ms for a patch) but 11 ms median while the edit thread compiles. That
is the GIL: numpy releases it inside large kernels and the engine then waits for the
edit's CPU-bound thread, and a Phase 4 install does more numpy work (fades retargeted, the
programmer's fade). A 0.1 ms switch interval, the identity-memoised recompile and
`gc.freeze()` brought Phase 3 down from 386 overruns and 86 ms ticks; Phase 7's process
split is the remedy for the rest. Phase 6 leaves these numbers where they were: the demo
rig 0 overruns (p95 7.3–9.1 ms), the §19-sized rig 139–166 overruns in about 1 600 ticks.

**Processes** (Phase 7; phase-7-plan steps 1 and 13, 2026-10-15). `bench/edit_latency.py` and
`bench/surface_load.py` take `--processes`: the engine then runs in a real engine process
(`bench/engines.py` plays the root and the console), so the edits, the surfaces and the
bench itself no longer share its GIL. Step 1 is the baseline before any Phase 7 code; the
thread numbers of step 13 include the safety stage:

| Bench | Rig | Step 1 (threads) | Step 13, threads | Step 13, **processes** |
|---|---|---|---|---|
| edit latency | demo | 0 in 769 ticks, p95 7.5 ms | 0 in 773, p95 7.1 ms | **0 in 804**, p95 5.5 ms |
| edit latency | §19-sized | 171 in 1617 (10.6 %), p95 141.6 ms | 163 in 1615 (10.1 %), p95 134.7 ms, max tick 64 ms | **1 in 1911 (0.05 %)**, 1 in 1810 on a rerun, p95 140–143 ms, max tick 10–11 ms, engine GC pause 0.3 ms |
| surface load | demo | 0 in 2000 | 0 in 2000 | **0 in 2014** |
| surface load | reference | 36 in 1994 (1.81 %) | 45 in 1993 (2.26 %), p99 11.2 ms | **4–9 in about 2010 (0.2–0.45 %)** over three runs, max tick 11–12 ms, GC pause 1.3–1.5 ms |

Both targets are met: 0 overruns on the demo rig, at most 1 % on the reference rig, so no
step of the plan's fallback ladder was needed. Under surface load across processes a probe
command takes 9.7 ms p50 and 14.4 ms p95 from submit to applied, and a phone round trip
44.7 ms p95. The edit itself takes as long as before (the session still compiles in the
console); only the engine no longer waits for it. What crosses the link is small
(`bench/transport.py`): the engine view of the §19-sized rig is 1.06 MB of the show's 2.67
MB, its first install 102 chunks of which the slowest loads in 0.35 ms, and an edit sends
what the incremental compile changed: 0.65 MB median for a recorded cue, 2.1 MB for a
patch (which rebuilds the rig); on the 60-playback busking rig the engine view is 7.6 MB
of 15.5 MB and the slowest chunk loads in 1.5–1.9 ms. The perf gates are where they were:
Appendix A's tick 0.079 ms mean, the reference rig with 60 playbacks 1.98 ms mean, the
60-GO burst 17.5 ms. A tick on Appendix A with park, limits and a strobe cap costs
**1.1–1.3 %** more than without (median ratio over interleaved ticks; gate 10 %), and the
output cycle for 64 universes 0.073 ms median for sACN (0.065 at step 1) and 0.067 ms for
Art-Net.

**The soak** (`bench/soak.py`, phase-7-plan step 19, 2026-10-16). The harness builds the
show from the five scripts (`busk new`, then each script, then a generated setup: three
routes on one universe and an OSC surface), starts a receiver process and `busk run
--stats`, and lets a load process busk it while a schedule acts. The receiver listens to
sACN on 127.0.0.1 and Art-Net on 127.0.0.2 with kernel receive timestamps, and reads a
pseudo-terminal standing in for a DMX USB Pro widget. The load, at `nice 10`, is seeded:
MIDI through a virtual ALSA port named like a nanoKONTROL2 (faders, buttons, taps,
pages), OSC, a phone over a real WebSocket (faders, buttons, reconnects, a 5 s flood every
hour) and console lines on stdin (edits, undo and redo, invalid commands); it never
touches the Circle, so one universe always changes. An **output drop** is a missing
sequence number, or a gap of more than two output cycles (45.5 ms) between packets, or
during an engine outage, more than the keep-alive interval plus 250 ms. The chaos:
`kill -9` of the engine, a 4 s `SIGSTOP` of it (always a watchdog kill at 3 s), `kill -9`
of the console and a 3 s unplug of the widget, on a schedule that `--chaos standard`
(first after 5–50 min, then every 20–180 min), `fast` (first after 15 s to 3.5 min, then
every 5–20 min) or `none` sets. A run **passes** with 0 drops, every action recovered,
restarts equal to
kills and stops, no tick, install or command errors, each process's memory at the end
within 10 % + 20 MB of its value after the first hour (or half the run), every route
delivering and `busk run` exiting 0; overruns outside the actions are a soft criterion
(at most 0.1 %).

| Run | Packets (sACN / Art-Net / DMX-USB) | Drops | Actions recovered | Overruns | Memory (engine, console, root) |
|---|---|---|---|---|---|
| `-m soak` (60 s, `fast`, seed 7) | — | 0 | an engine kill, an unplug, a console kill | — | — |
| 10 min `fast`, seed 10 | 26 266 / 26 252 / 25 985 | **0** | **6 of 6**: kills 0.9 and 0.5 s, the stop 4.3 s, the console 0.9 s, unplugs 3.0 and 3.1 s | 0 in 59 128 ticks; longest tick 7.2 ms | 60 → 60, 72 → 73, 66 → 66 MB |
| **1 hour `standard`, seed 11** | 158 267 / 158 254 / 157 853 | **0** | **7 of 7**: kills 0.9 and 1.2 s, the stop 4.0 s, the console 0.4 s, unplugs 3.0–3.1 s | 1 in 359 081 ticks (0.0003 %); longest tick 10.5 ms, longest GC pause 0.2 ms | 60 → 60, 74 → 73, 66 → 66 MB |

In the hour the load sent 359 277 MIDI events (61 112 LED messages came back), 215 994 OSC
messages, 213 862 phone fader moves and 1 788 buttons, a flood of 4 999 commands (rate
limited, 5 notices), 12 phone reconnects, 5 167 console lines (359 edits, 59 invalid
commands, each answered by its error), 12 blackout toggles and 179 page turns; 0 output
cycles were late, the longest output gap was 25.4 ms, and the event log reached 152 MB in 9
files. A deliberate 0.3 s `SIGSTOP` of the root is caught: 3 gap drops of 320 ms, and the
run fails. The 24-hour run is the user's ([hardening checklist](#hardening-checklist-phase-7)).
A report (`--report`, default `soak-<UTC>.json`, checkpointed while it runs, plus a
printed summary) holds the numbers above and every drop and action; the files the run
wrote stay next to it in `soak-<UTC>/`, the event log among them, so with the seed
`busk replay` shows what the engine saw. Soaks run one at a time: they use fixed
ports (UDP 5568 and 6454, the virtual MIDI port's name).

## Layout

```
src/busk/
  cli.py  __main__.py
  model/                 # persistent schema (§5.1–§5.17) as TypedDicts
    common.py            #   ids, EntityBase, TargetRef/TargetKey, STRICT, number aliases
    attributes.py        #   attribute registry (§5.3) and values (§5.4)
    profile.py           #   profiles (§5.5) + their interpretation: options, emitters
    fixture.py group.py preset.py entry.py effect.py cue.py playback.py
    master.py surface.py output.py show.py
    validate.py          #   validate_show(), validate_edit(), validate_values()
  commands/
    types.py             #   command TypedDicts (§15.2) + Phase 3–7 commands, EditPath, envelopes, CommandOrigin
    classes.py           #   command type → performance | programmer | show | session
    bus.py               #   CommandBus: the engine queue (performance commands + installs)
    patch.py             #   Op, apply(): copy-on-write JSON patches with inverses (§15.4)
    edits.py             #   ADD / SET / DELETE / PATCH_FIXTURE / ASSIGN_PLAYBACK → Edit
    record.py            #   RECORD_GROUP / RECORD_PRESET / RECORD_CUE (values and effects) → Edit (§15.3)
    errors.py            #   CommandError
  session/
    session.py           #   Session (command bus, single writer), CommandResult, InputSink
    timeline.py          #   the one undo/redo timeline
    state.py             #   ShowState: a committed show, compiled, with its lookups
    programmer.py        #   Programmer (values and effects) and its handlers (§5.14)
    frame.py             #   build_frame(), slot_remap(): what the engine gets
    library.py           #   ProfileLibrary, EffectLibrary
    ids.py               #   RandomIds, CounterIds
  library/profiles/      # the built-in profiles (Appendix A's two, Phase 1's three)
  library/effects.json   # the built-in effect templates and their console defaults
  console/
    parser.py            #   parse(): a console line → an action (pure)
    console.py           #   Console.execute(), run_script(), interact()
  persistence/
    show_file.py         #   load_show(), save_show(), atomic_write(), backups, new_show()
    autosave.py          #   AutosaveWorker, read_recovery() (+ the show stamp, highlight)
    eventlog.py          #   the event log (§15.5): causes, EventLog (writer, rotation), LogPump, read_log()
    paths.py             #   state directory, installation CID, web key, log directory
    values_file.py       #   load_values()
  compiler/
    compile.py           #   CompiledShow, compile_show(), OutputLayout (what the root's output reads)
    rig.py               #   fixtures resolved against profiles; element analysis
    slots.py             #   Slot, SlotTable, build_slots(): lanes and the default frame
    lanes.py             #   encode_value(): attribute value → lanes
    channels.py          #   CompiledChannel, build_channels()
    cues.py              #   CompiledCue, CueCompiler, cue_from_values(), TimingTable (§6.3)
    tracking.py          #   tracked states and per-slot timing of a cue list (§9.1, §9.3)
    effects.py           #   CompiledWave, CompiledLayer, CompiledEffect; phase spread (§10.2)
    playbacks.py         #   CompiledPlayback, CompiledCueList, CompiledChase, CompiledMaster (+ group members), CompiledPage
    limitations.py       #   collect_limitations(): what this build ignores
    safety.py            #   CompiledSafety: park, limits, strobe lanes; dark_bytes(), unpatched_warnings() (§12, §18)
    values.py            #   compile_values(): values file → base logical frame
  convert/
    dmx.py               #   split_raw() for ints and int arrays; UNIVERSE_SIZE
    curves.py            #   dimmer curves, vectorised
    plan.py              #   ConversionPlan: channels flattened into arrays
    converter.py         #   Converter.convert(): the per-tick kernels
  engine/
    clock.py             #   Clock, MonotonicClock, FakeClock, FixedRateSchedule
    curves.py            #   the six fade curves and cubic Bézier (§5.9)
    fades.py             #   Envelope; ContributionSet: per-slot value and presence fades
    cue_engine.py        #   GO / BACK / GOTO rules, auto-GO scheduling, CueTiming (§8.1, §9.2)
    chase.py             #   ChaseClock, CueOrder, ChaseRuntime: steps, beat lock (§9.4); grid_position()
    waveforms.py         #   the nine §10.3 waveforms, vectorised
    effects.py           #   EffectClock, EffectRuntime, EffectBank: running effects (§10)
    playback_runtime.py  #   PlaybackRuntime (state machine, cue position, chase, effect banks, manual crossfade), Playbacks (buttons, swop)
    contributions.py     #   Source, SequencedSource (runs of per-slot numbers), gather(), Relative
    resolver.py          #   Resolver: LTP layer stack + snapping, HTP per band, per-lane weights, relative pass (§7)
    masters.py           #   grand and group masters, blackout (§12; the engine leaves blackout to safety.py); SpeedMasterRuntime, tap tempo (§11.3); fade-time override
    safety.py            #   apply_safety(): highlight, park, blackout, limits, strobe lanes (§12, stage 11)
    surfaces.py          #   PageState, HeldButtons, Pickup: the page, held buttons, soft takeover
    snapshot.py          #   EngineSnapshot, PlaybackStatus, SpeedStatus (beat anchors), PageStatus
    install.py           #   Install, ProgrammerFrame, ProgrammerRuntime (fading, its effect bank), remap_lanes()
    loop.py              #   Frame, EngineStats, EngineRuntime, Engine (stages 1–13, restore, tick errors, bounded drain)
  io/
    events.py            #   InputEvent, address_key()
    bindings.py          #   BindingResolver: input events → commands (page-relative by slot), lastInput
    midi.py              #   MidiInput (mido + python-rtmidi), translate(), BeatCounter (MIDI clock), MidiOutput
    osc.py               #   OSC 1.0 codec, OscSurface (UDP input), OscFeedback
    feedback.py          #   feedback_values(), FeedbackWorker: LEDs, motor faders, labels at 30 Hz
    surfaces.py          #   SurfaceManager: MIDI, OSC and web surfaces through live edits; MIDI hot-plug
    ratelimit.py         #   TokenBucket: the web and OSC rate limits
  importers/
    __init__.py          #   ImportReport, ImportFailed
    ofl.py               #   Open Fixture Library → busk profiles (phase-7-plan §5.18)
    gdtf.py              #   GDTF (a subset) → busk profiles; XML without DOCTYPE, a size cap (§5.19)
  process/               # the process split (§16, §18; phase-7-plan §5.1–§5.9)
    wire.py              #   framing, message kinds, raw frames; engine_view(), ShowEncoder/ShowDecoder (structural sharing)
    engine_host.py       #   EngineHost: the engine process (link thread, engine thread, publisher)
    links.py             #   EngineLink, LocalEngine (--threads), RemoteBus: the console's side of the engine
    console_host.py      #   the console process (and the --threads run): session, prompt, surfaces, status
    root.py              #   Root: output, watchdog, restarts, event log, --stats, signals; FrameLink
    report.py            #   RouteReporter, print_statistics(): the route and statistics lines
  replay.py              # busk replay: Replayer
  web/
    websocket.py         #   RFC 6455, server side: handshake, frames, WebSocket (a writer thread each)
    server.py            #   WebServer: HTTP and WebSocket on one port, the key and origin checks
    api.py               #   WebLink, WebApi (the JSON protocol, the broadcaster), WebSurface
    static/              #   index.html (the phone page), commands.json (the commands it sends)
  output/
    driver.py            #   OutputDriver protocol, DriverStatus, RouteNotice (§14.5)
    sacn.py              #   E1.31 packet, multicast_group(), Sequences, SendPolicy, SacnSender, UniverseDiscovery
    artnet.py            #   ArtDmx, ArtPoll / ArtPollReply, ArtNetNetwork (shared socket, nodes), ArtNetSender
    dmxusb.py            #   the Enttec DMX USB Pro protocol, EnttecSender (serial device, reopen)
    netif.py             #   interface addresses, broadcast addresses and networks (Linux ioctls)
    scheduler.py         #   OUTPUT_HZ, ScheduledRoute, build_routes(), OutputScheduler (§14): stall output, output off, reopening, OutputStats
    console.py           #   ConsoleOutput: the --console debug sink
examples/phase1-demo.json    # three real fixtures, transcribed from their manuals
examples/phase1-values.json
examples/phase2-busk.json    # the busking demo: 2 spots, 4 pars, 8 playbacks, a nanoKONTROL2
examples/phase3-build.busk   # the Phase 3 build: a busking show from console commands only
examples/phase4-song.busk    # the Phase 4 song: a tracking stack and a BPM chase on that show
examples/phase5-effects.busk # the Phase 5 effects: a circle, a pulse, a wave and a colour cycle on it
examples/phase6-surfaces.busk # the Phase 6 surfaces: a second page, a phone, LEDs on that show
examples/phase7-safety.busk  # the Phase 7 safety show: limits, park, a strobe cap, panic on that show
examples/tupperdmx/          # the user's TupperDMX rig: hand-transcribed profiles, build.busk, build-ofl.busk (imported)
bench/edit_latency.py        # live-edit latency and engine stalls
bench/surface_load.py        # ticks, phone round trips and command latency under surface load
bench/engines.py             # the engine under a bench: a thread, or a real engine process (--processes)
bench/transport.py           # install sizes and load times on the console → engine link
bench/soak.py                # the soak: build, chaos schedule, analysis, report (done criterion B)
bench/soak_receiver.py       #   its receiver: sACN, Art-Net and a DMX-USB pseudo-terminal, timed by the kernel
bench/soak_load.py           #   its load: MIDI, OSC, a phone and console lines, seeded
tests/fixtures/appendix_a.json   # verbatim copy of the spec's Appendix A
tests/fixtures/golden_7_8.json   # the §7.8 worked example's rig and playbacks
tests/builders.py            # synthetic shows, feature matrix, benchmark rigs, busking content
tests/harness.py             # deterministic engine harness: fake clock + command script (§20)
tests/reference_convert.py   # per-channel §13 transcription: the conversion oracle
tests/reference_resolver.py  # per-slot §7.7 transcription: the resolver oracle
tests/sacn_receiver.py       # independent E1.31 parser + localhost receiver
tests/session_harness.py     # a session on a real engine with a fake clock (Phase 3)
tests/ws_client.py           # an independent WebSocket client (Phase 6)
tests/artnet_node.py         # an independent Art-Net parser, receiver and fake node (Phase 6)
tests/process_harness.py     # real busk run process trees: start, read lines, kill, stop (Phase 7)
tests/process_site/          # sitecustomize.py: points the children's sACN routes at a test receiver
tests/dmx_widget.py          # a pseudo-terminal standing in for an Enttec widget
tests/gdtf_builder.py        # synthetic GDTF files, from DIN SPEC 15800 (Phase 7)
tests/fixtures/ofl/          # OFL files: the five TupperDMX fixtures
tests/golden/                # the shows and DMX frames of the Phase 3 build, the Phase 4 song, the Phase 5 effects, the Phase 6 surfaces and the Phase 7 safety show
```

## How it works

**Validation** (`busk.model.validate`). Pydantic validates the JSON against the spec's
own `TypedDict`s in strict JSON mode, then a hand-written semantic pass checks what types
cannot express and collects every issue with a path such as `fixtures[2].patch.address`.
Phase 1 adds the profile rules that conversion depends on: capabilities by kind (a scalar
needs a `range`, a wheel a `slot`, a shutter a shutter function), every discrete channel
offers its attribute's default option (this makes the shutter guard total), function
parameters are scalar attributes, colour components name known emitters and an element
mixes either additively (R, G, B) or subtractively (C, M, Y flags), every mode can be
dimmed (a dimmer channel, or a virtually dimmed element), dimmer tables have ≥ 2 points,
and `swapPanTilt` fixtures have both pan and tilt. Phase 1.5 adds one output rule: two
enabled sACN routes on the same sACN `universe` must send the same show universe (they
share its sequence numbers under one CID). Disabled routes send nothing and are skipped.
Phase 2 adds one preset rule: a preset holds at most one value per `(scope, attribute)`,
since a second one could never be looked up.

**Slots** (`busk.compiler.slots`). Every `(fixture, element, attribute)` that can be
controlled becomes a slot with a dense index and a run of float lanes in the logical frame
(§6.1–§6.2): fixtures in show order, elements in index order, attributes in registry
order. Elements get a slot per attribute they have a channel for (never `control`), plus
derived slots: `intensity` for a virtually dimmed element (§13.2) and the parameters of
their function capabilities (`strobeRate` for a strobe range). A discrete slot's lane
holds an index into its options, which are the channel's wheel slots or shutter functions
in DMX order (the first of duplicate ids wins). The default frame holds the registry
defaults, with `zoom`'s "profile midpoint" resolved.

**Channels** (`busk.compiler.channels`). One frozen record per slot-driven channel:
universe row and byte addresses, input slot, range segments (after `invert`), pan/tilt
orientation folded into `(input slot, offset, sign)`, dimmer curve, emitter, option table.
On overlapping patches the later fixture owns each shared byte, exactly as in the base
image, so every written address is unique.

**Cues** (`busk.compiler.cues`, §6.3). Every cue of every cue list is compiled, as its
own values and then as the tracked state a playback holds at it (*Cue lists*, below).
Each entry's targets are expanded (a group follows its
members, in order), its value is resolved per target (a literal; a `perTarget` map by
target key; a preset by the §5.8 scope lookup, target → profile → global; a spread by the
member's index), targets without the attribute are dropped, and the value is encoded
into the slot's lanes and clamped to the attribute's range once, here, instead of every
tick. A later entry for the same slot wins. A discrete value the target does not offer
(a gobo it lacks, another wheel) is dropped for that target with a compile warning. The
lanes are then partitioned the way the resolver merges them: intensity (HTP, as
positions in the slot table's intensity lanes), continuous LTP lanes, and **snap
lanes** that cannot be interpolated, each with its own threshold: discrete attributes and
`positionSpeed` snap as soon as the source is present, colour extras (`w`, `a`, `uv`,
which may be `NaN` = "derive") at half presence. Everything is a sorted, read-only array.

**Conversion** (`busk.convert`). The plan flattens the records into a structure of
arrays, and the converter runs a fixed sequence of numpy kernels each tick: range inputs
and dimmer curves; colour (white extraction, explicit extras, CMY, virtual intensity) in a
small matrix with one row per emitter role; one uniform segment map for every value
(multi-segment channels pick the containing or nearest segment); options and their
strobe-rate parameters; then `split_raw` and a scatter into the universe buffers. Python
loops run only over curves and resolutions, never over channels. Rounding is half to even.
`tests/reference_convert.py` transcribes §13 channel by channel with the same
floating-point operations in the same order, and a property test checks that both agree
byte for byte.

**Commands** (`busk.commands`). Nothing outside the engine thread touches engine state:
bindings, the web API and the CLI call `CommandBus.submit`, which validates the command
on the caller's thread (a performance command, an existing playback, master or page,
levels clamped to 0..1), wraps it in a §15.1 envelope with its origin (the surface and
control, or the phone's address) and queues it. A rejected command raises
`CommandRejected` with a readable reason, such as `no page 7` or `speed master 'Clock'
does not take taps`. The engine drains the queue at the start of each tick and applies the commands,
in order, at the tick's time; each one is guarded, so a bug is counted and the tick goes
on.

**Playbacks** (`busk.engine.playback_runtime`). A playback is up to two **sources**: *main*
holds the latched state (activate → active → release → releasing → idle) and *flash* is
present while its flash button is held or its `temp` fader is up, in its own band
(`priority + priorityBoost`) with its own sequence number, so letting go of a flash leaves
the stack below exactly as it was. Every latching activation (trigger, toggle, GO,
`autoStart`) takes a fresh number from the global sequence counter, which is what "latest"
means in LTP, and releases the other active playbacks with the same exclusivity key.
Since Phase 4 the slots fade one by one with the cue's timing (*Fades per slot*, below);
a release still fades the whole playback, from where it is, over the release time, so a
release in mid-fade lasts exactly the release time. A master fader scales intensity; for LTP, `followFader` scales the
presence by the fader, `threshold` waits (when the fader started the playback) until the
fader passes `ltpThreshold`, and `ignoreFader` ignores it.

**Resolver** (`busk.engine.resolver`, §7). Each tick, the present sources are sorted by
`(priority, seq)` and composited over the frame of uncontrolled slots. LTP is a layer
stack: each source moves its lanes from what is below towards its own values by its
presence, `v + (value − v)·w` (exactly `value` at full presence), and snap lanes jump once
the presence reaches their threshold. HTP runs per band over a dense array of all
intensity lanes: `v = v·(1 − P) + M`, with `P` the band's highest presence and `M` its
highest `value · scale · presence` per lane, which is §7.4's crossfade with the division
cancelled out. Contributions are batched per source (§19's arrays, not an object per slot
per tick), so the Python loop runs over sources, never over slots. Because a source's
contributions share `(priority, seq)`, this is exactly §7.7 applied slot by slot, which
`tests/reference_resolver.py` transcribes literally; a property test checks they agree.
Since Phase 4 a source may carry a presence per lane (a slot mid-fade) and a snap
threshold per lane; a settled source at full presence takes the old scalar fast path.

**Masters** (`busk.engine.masters`, §12). Group masters (Phase 5) scale the intensity of
their group's members, each member by the product of the group masters containing it;
then the grand master (the product of every grand master's level) scales the intensity
lanes and blackout zeroes them (since Phase 7 inside the safety stage, below), on the
working frame only, after the resolver and before
conversion. Runtime state is never touched, so taking
either away returns exactly to the live look, whatever was flashing or overriding.

**Engine** (`busk.engine.loop`). Each tick fires the auto-GOs and chase steps due by its
time, each at its own time, then drains the commands (stage 1; at most 512 items since
Phase 7, the rest wait for the next tick in order), fires what the commands
made due, advances the playbacks and their fades (3–4), gathers and resolves the sources (6–7), applies the
masters (9–10) and the safety stage (11), copies the base images into the back buffer (so control channels keep
their `defaultDmx`), converts (12) and publishes a frozen `Frame` of `bytes` with one
reference assignment (13). When the visible state changed, it also publishes an
`EngineSnapshot` (master levels, blackout, each speed master's tempo, multiplier and beat
anchor, the current page and the fade time, each playback's state, fader, flash, swop,
current cue and manual progress) the same way. Effect phases are not in it:
they change every tick, and a remote can derive them from the tempo and the time.
Every value is a function of the commands applied and of the tick's time, so a show looks
the same at any tick rate (§2.5) and replays byte for byte on a fake clock (§2.7). Ticks
are scheduled from an integer count (no drift); a late tick counts as an overrun and the
schedule restarts from now.

**Time** (Phase 4). Every runtime value is still a pure function of the commands and the
time, whatever ticks run in between: positions are never integrated (`phase += rate·dt`)
but computed from a start time and a rate, and rebased only at events (a GO, a tap, a
rate change). Events that fall due between two ticks (an auto-GO, a chase step) fire at
their own times before the tick's commands, so a command sees what it would see on any
tick schedule. Frames are therefore byte-identical at 100 Hz, 37 Hz or on a random
schedule, and the song test replays to the byte.

**Fades per slot** (`busk.engine.fades.ContributionSet`). Each source holds, per lane of
its HTP, LTP and snap partitions, where its value and presence fade from and to, a timing
group (start, delay, duration, curve) and a sequence number, all as arrays; a tick
evaluates each group's curve once and lerps the lanes. A **retarget** (a GO, an edit, a
programmer change) aims the set at a new state: a slot whose target is unchanged keeps its
running fade, so a 0-s GO halfway through a 10-s pan fade does not make the pan jump; a
changed slot fades from where it is, with the timing of the destination cue for its family
(in for rising intensity and every LTP value, out for falling intensity, per family and
per entry overrides, delays, curves). A slot's lanes change together. When every group has
finished, the set compacts to a static source.

**Sequence numbers per slot.** "Latest" in LTP applies to what an action changes: an
activation numbers every slot, a GO, BACK or GOTO only the slots it changes, and
automatic advances, chase steps and edits keep the numbers they have. So a colour bump
on top of a tracking stack stays on top through every GO that leaves colour alone. A
contributor whose slots hold several numbers reaches the resolver as one source per run
of its numbers between the other contributors' numbers in its band
(`contributions.SequencedSource`), which composites exactly in `(priority, seq)` order.

**Cue lists** (`busk.compiler.tracking`, `busk.engine.cue_engine`, §8.1, §9.1–§9.3). The
compiler precomputes each cue's **tracked state**: in a tracking list a cue holds what the
cues before it set, up to a `block` cue, minus its `releases` (a cue's own values win over
its own releases); without tracking a cue holds only its own values. GOTO therefore lands
on exactly what stepping gives. GO moves to the next cue (at the last: wrap, release with
`releaseAtEnd`, or re-assert), BACK to the previous with that cue's timing, GOTO anywhere.
After a forward move the next cue's trigger is scheduled: `wait d` fires d after the move,
`follow d` d after the fades it started complete; BACK and a release cancel it.

**Chases** (`busk.engine.chase`, §9.4). A chase list steps by itself at a rate in Hz or
in steps per beat of a speed master, fading into each step over `crossfade` × the step
length with the cue's curve, `forward`, `reverse`, `bounce` or `random` (seeded per
activation). A BPM chase stays on its master's beat grid: on activation, a tap or a rate
change it moves to the next grid position rather than back, and a `rate` fader scales it
by ¼ to 4, rounded to a power of two on BPM chases.

**Speed masters** (`busk.engine.masters`, §11.3). Each counts beats from the first tick at
its BPM; a tempo change rebases the count, so the grid never jumps. Every tap (`TAP`)
moves the nearest whole beat onto the tap; from the second tap of a run (a 2-s pause
starts a new one) the tempo is 60 over the mean of the last 8 taps' intervals that lie
within 25 % of their median. `SET_BPM` sets the tempo outright. The master's level picks one of
its `multiplierSteps` (×¼ … ×4 by default), which multiplies the rate of every chase
and effect locked to it.

**Effects** (`busk.compiler.effects`, §10, Phase 5). An effect instance, in a cue or in the
programmer, names a template of layers, its targets, a rate (Hz, or a multiple of a speed
master's beat), a size, a phase range and the spread options. The compiler expands the
targets in order and places each member on the phase range (§10.2: `wings` mirror every
other wing, `blocks` give neighbours one position, `groups` repeat the pattern). It
compiles each layer to the lanes of the members that have its attribute: a waveform
(`sine`, `triangle`, `square`, `sawUp`, `sawDown`, `pulse`, `step`, `random` or `curve`)
between `low` and `high` for an absolute layer, an amplitude for `add`, a depth for
`multiply`, or, for a colour cycle, a palette per member (preset references resolved per
member). A target is exactly its element, so an effect on the PiX's group spreads over its
12 cells. An effect that drives nothing compiles to nothing, with a warning.

**Effect clocks** (`busk.engine.effects.EffectClock`). An effect's position `P`, in cycles,
is computed and never integrated, like a chase's: `p0 + rate·(t − t0)` in Hz, or `p0 +
rate·(beats(t) − b0)` on a speed master, starting on its beat grid. A tap or a rate change
re-aligns a BPM effect to the grid position nearest where it is, but the difference is
not applied at once: it shrinks linearly to nothing over one beat. Nothing moves at the
tap, and one beat later the effect is on the new grid (§10.1's "nudged toward the master's
beat phase", made exact). Each member's phase is `P`, run backwards for `reverse` and
folded for `bounce`, plus its offset and its layer's.

**Running effects** (`EffectRuntime`, `EffectBank`). Each playback has a bank of running
instances, retargeted with its slots on every activation, GO, chase step and live edit.
An instance that enters fades in over `sizeFadeIn` or the cue's in time; one that leaves
fades out with the cue's out time and keeps moving; one that changes (a new size, a
trimmed member list, an edited template) cross-fades from its old form to the new one on
the same clock, mixing the two per lane by presence, so a size change is an exact morph.
In a tracking list an instance carries on, by id, into the next cues, so its clock never
restarts. A release fades the whole playback, effects included, which keep moving. An
absolute layer is a source in its playback's band, numbered so that it wins a tie with
its cue's own values; the dynamics (`size` fader × size master) scale its presence. While
the playback's main is idle, a held flash or a `temp` fader runs a second bank in the
flash band.

**The relative pass** (`busk.engine.resolver`, §7.5). After the absolute pass, `add` and
`multiply` layers apply in `(priority, seq, order)` order: `v + amount·W` and `v·lerp(1,
amount, W)`, with `amount` = `size·d·(2w − 1)` or `1 − size·d·(1 − w)` (`w` the waveform's
0..1, `d` the dynamics). `W` is the layer's weight × `(1 − A)`, `A` being the highest
presence on that lane among the absolute sources of higher bands. So the programmer or a
higher band suspends a circle on the slots it takes, and fading it in fades the circle out
instead of cutting it. Additions to attributes with a range are clamped after the pass.

**Pages and buttons** (`busk.engine.surfaces`, Phase 6). The engine keeps the current page
(`PageState`), one for every surface: it starts on the lowest-numbered page, `PAGE` moves
it by number or by a delta that stops at the ends, and a live edit keeps it by id (a
deleted current page gives way to the first page numbered at or after it, else the last).
Bindings send page-relative commands, `SET_FADER {slot}` and `PLAYBACK_BUTTON {slot,
button, down}`, which the engine resolves on the page current when it applies them, so a
page change and a fader move land in queue order whatever thread sent them. The buttons
follow §8.1: `go`, `back`, `toggle`, `release` and `goto` (a GOTO to the playback's
`gotoCue`) act on the press, `flash` and `swop` on both edges. A held flash or swop is
recorded per control (`HeldButtons`), so its release reaches the playback its press did,
after a page change too. `select` goes to the session, resolved by the binding resolver
on the snapshot's page.

**Soft takeover** (`Pickup`). On a `soft` surface each fader and knob is attached to what it
drives or not. Detached, a move does nothing until the control comes within 0.02 of the
level or crosses it between two moves; attached, it sets the level. Pointing at something
else (a page change) or a move of the same level from another source (another control,
the phone, the console) detaches it. This is engine state, keyed by the command's
`origin.control` (the binding's id), so it never depends on which input thread won a race.
A move on an empty slot still records where the control is, so coming back to the page
cannot take over by a stale crossing.

**Swop** (`Playbacks.swop`). While a swop is held on a playback, its flash is up and every
other playback's sources (flashes and effects included) take an HTP weight of 0, unless
they are `protectFromSwop`. LTP lanes are untouched and nothing else in the runtime
changes, so letting go returns exactly to the look before. (§8.1 sets the others'
`intensityScale` to 0; removing their presence also silences §7.4's override bands, which
would otherwise hold intensity through the swop.)

**Fade-time masters** (`busk.engine.masters`). The highest fade-time master's level `L`
gives `T = 10 s × L²`. While `T > 0`, every transition that starts (an activation, GO,
BACK, GOTO, an auto-GO, and their effects) fades every slot over `T` with no delay and the
cue's curve, and a release without an explicit time (a button, `autoRelease`,
exclusivity, GO past the end) takes `T`. Chase steps, flashes, swops, live edits and the
programmer keep their own timing, and running fades are left alone.

**Manual crossfades** (`PlaybackRuntime.manual`). A `crossfade` fader rests at 0 or 1.
Leaving its rest end starts the playback's next transition (its activation, else a GO) on
a virtual clock: a travel `p` from the rest end puts the transition at `p × span`, the span
being the cue's longest delay plus fade (effects included), so every slot's own timing and
curve play out in step with the hand. Progress is the furthest travel so far, so the fader
only pushes the transition on; at the far end the transition completes and that end
becomes the rest. Fades running when the fader starts settle and finish with it; a GO, a
release or a live edit that retargets the playback freezes the manual transition where it
is and goes on in real time. A fader moved in step with the clock gives the frames a GO
gives.

**Input** (`busk.io`). The `SurfaceManager` opens each surface of the show and follows live
edits. A `midi` surface opens one port through `mido` + `python-rtmidi`; rtmidi calls back
on its own thread with each message, which becomes an `InputEvent` (control change, note,
pitch bend; channels 1–16; value 0..1). MIDI clock is counted, 24 clocks to a beat, into
one press of the `midiClock` input per beat (Start and Song Position set the count), so a
DAW drives a speed master through tap tempo. An `osc` surface has a UDP socket and a
receive thread; each message (bundles unpacked) becomes an event on its address. A
`BindingResolver` looks up the bindings of an event and submits commands: page faders and
buttons as page-relative commands with the binding as their control, absolute faders, the
grand master and other masters (a speed master's level picks the multiplier), tap tempo
(on press), blackout (toggled on press, or on and off with the button when `momentary`),
page buttons and embedded commands. Buttons are edges with per-binding state, so a
repeated CC 127 is one press and any note velocity presses. A failing binding is reported
once and never breaks the input thread.

**Feedback** (`busk.io.feedback`). `feedback_values` turns the latest snapshot into a value
per feedback binding, on the current page: an LED 1 or 0, a motor position, a label. The
`FeedbackWorker` thread computes them 30 times a second and sends only what changed: MIDI
through the output ports it owns (one writer per port), OSC through each surface's socket.
A motor fader is held back for 0.5 s after its control last moved, so the motor never
fights a finger. The tap LED needs the beat phase, which changes every tick and is not in
the snapshot: the snapshot carries each speed master's beat anchor (a time and a beat,
which change only at taps and tempo changes), and the worker computes the phase at its
own time on the engine clock.

**The web remote** (`busk.web`). One port serves the phone page and a WebSocket at `/ws`,
both behind the key (`?k=`, compared in constant time) and an origin check, so a page
from another site cannot connect. The server side of RFC 6455 is written here: each
connection reads on its handler thread and writes on a writer thread of its own, where
pongs and the close frame go first, replies queue (64 at most) and each state message
replaces the one not yet sent, so a slow phone gets the newest state, not a backlog, and a
phone that takes nothing for 2 s is dropped. The protocol is JSON: on connect a `hello`
(the protocol version and the engine's time), the `show` (pages, their playbacks and
buttons, the masters) and then whenever the compiled show changes, and the `state` (the
snapshot) at most 30 times a second. A phone sends performance commands (`PAGE`,
`SET_FADER`, `PLAYBACK_BUTTON`, `SET_MASTER`, `TAP`, `BLACKOUT`, …) and gets an `error`
with the command's id when one is refused. Show edits and programmer commands are refused:
the console stays the only editor (§23). The buttons a phone holds are released when it
disconnects.

**Output** (`busk.output`). At start-up `build_routes` creates and opens one sender per
enabled route (`SacnSender`, `ArtNetSender`, `EnttecSender`); routes that are disabled,
for an interface busk cannot drive (`enttecOpen`), or that cannot open (an unknown
interface, an unresolvable host, a missing device) are reported and left out. The output thread
(`OutputScheduler`) then runs at 44 Hz, the DMX512 refresh ceiling. Each cycle it reads
`engine.latest` once, flags each universe whose bytes differ from the previous cycle's
frame, and offers every route its universe with that flag; then it services the
`--console` sink. Each driver call is wrapped on its own, so a driver bug is counted as a
fault on that route and never stops the others.

A sender decides whether a packet is due (`SendPolicy`, E1.31 §6.6): a change is sent at
once and repeated on the next 3 cycles; after that, a keep-alive goes out whenever 0.9 s
have passed since the last send (every 40 cycles, 0.909 s: inside E1.31's 800–1000 ms and
far inside receivers' 2.5 s timeout). So a static look costs about one packet per second
per universe, and a stalled engine's last frame keeps being held. The 638-byte packet is
built once per route; a send writes the sequence number (one counter per sACN universe,
shared by its routes), the options byte and the 512 data bytes, then calls `sendto` on a
non-blocking socket. A failed send is counted, sets the route's status to `ok = False`
with the error, and never raises; it still counts as a send for the keep-alive timer, so a
dead link is retried about once a second, and the next successful send restores `ok`. The
main thread polls the statuses (and the snapshot, for the status line) every 0.1 s and
reports changes. On shutdown the output
thread makes a final pass, then closes every sender, which sends 3 Stream_Terminated
packets (if it ever sent a packet) and closes its socket.

**Art-Net** (`busk.output.artnet`, Phase 6). One socket on UDP 6454 (`ArtNetNetwork`) is
shared by the Art-Net routes, opened with the first and closed with the last. A route
sends a 530-byte ArtDmx per universe with a sequence number per Port-Address, on change
and as a keep-alive once a second. Each output cycle the network reads what arrived (64
datagrams at most, so a flood cannot stall the output), answers ArtPoll with an
ArtPollReply, records the nodes whose replies have output ports, forgets those silent for
10 s, and polls every 2.5 s on its routes' broadcast addresses. A broadcast route sends to
the nodes on its interface's network that output its Port-Address, else to the broadcast
address.

**sACN discovery** (`UniverseDiscovery`). Every 10 s, and at once when the list changes,
busk sends the sorted list of the universes its open sACN routes send (512 to a page) on
universe 64214, out of each multicast route's interface.

**DMX-USB** (`busk.output.dmxusb`, Phase 6). An Enttec DMX USB Pro or a DMXking widget is
a serial device (raw, 8N1) that takes framed messages (`0x7E`, label, length, data,
`0xE7`): on open the parameters (break, mark after break, the output rate from
`refreshHz`), then label 6 with the 512 slots on change and once a second. Writes never
block: a frame due while the previous one is still going out is dropped and owed, so the
next cycle sends it. A write error marks the route failed and closes the device, which is
reopened at most once a second; a reopen sends the parameters and a full frame.

**Session** (`busk.session`, Phase 3). The session is the command bus of §15 and the only
writer of editing state: the show store, the programmer and the undo timeline. It routes
every command by class (`busk.commands.classes`). Performance commands go straight onto
the engine's queue without taking its lock, so busking never waits for an edit; input
threads hand everything else to one worker thread (`post`), so a MIDI callback never
blocks either. Programmer and show-edit commands run under the lock. **The session only
ever holds a show that validates and compiles**: an edit becomes patch ops, applied to a
candidate show, validated and compiled, and only then committed and installed; any error
rejects the whole edit, a `BATCH` included, and nothing changes anywhere. Other threads
read an immutable `SessionSnapshot` published by one reference assignment.

**Edits and undo** (`busk.commands.patch`, §15.4). Generic edits address the show by id
(`["cueLists", {"id": "cl-song"}, "cues", {"id": "c-verse"}, "timing", "fadeIn"]`); recording
and patching have their own commands. Every edit is a list of JSON-patch ops (`add`,
`remove`, `replace`) applied **copy-on-write**: only the containers on an op's path are
copied, so an untouched subtree of the new show *is* the old object, and the inverse ops
are captured while applying. Undo applies the inverse, redo the forward ops, through the
same validate → compile → install path. Programmer changes share the timeline, so one
`undo` undoes the last action, whatever it was; blind is a mode and is never undone.

**Validating an edit** (`validate_edit`). Copy-on-write makes the touched entities exactly
those that are not the very objects they were before, so only they are validated
structurally (each with its own `TypedDict` adapter, through the same strict JSON path a
load uses, so paths read `presets[3].values[0].value`); then the whole semantic pass runs.
Touched entities are replaced by their validated copies, so the store always holds what a
load would produce (keys in schema order, floats, tuples). A property test checks that it
reports exactly what a full `validate_show` reports, and normalises the same way.

**Incremental recompile** (§6.4). The same identity rule replaces the spec's reverse
dependency index: `compile_show(show, previous)` reuses the whole rig (slots, channels,
conversion plan, base images) when profiles, fixtures and universes are the same lists,
and a compiled cue list when it and every group and preset its entries read are the same
objects. A cue edit recompiles one list; a preset edit, the lists that read it.

**Programmer** (§5.14). An immutable value: an ordered selection, values per slot (a
literal, or a preset reference kept as a reference), and blind. Spreads and per-target
values are evaluated per target when set (`set pan spread -30 30` stores each head's
own pan). Values whose slot disappears stay, dormant, and come back with an undo. The
session resolves the programmer to lanes off the engine thread (a `ProgrammerFrame`) and
installs it; in the engine it is one more source at **band 100** with full weight, so its
intensity overrides the playbacks (even downwards) and its LTP values sit on top. Each
slot carries the sequence number of the last command that set it, and the engine splits
the programmer into as few sources as the other band-100 sources require, so "latest"
holds slot by slot. Blind leaves it out of the live resolve; leaving blind applies it. With
a fade time (`fade 2`, Phase 4) every change fades: a set value, a clear, a blind switch,
an undo. Since Phase 5 it also holds effects (`ADD_EFFECT`, `REMOVE_EFFECT`), which run in
the programmer's own bank at band 100, entering, changing and leaving over its fade time.

**Recording** (`busk.commands.record`, §15.3). Recording turns programmer values into
show data that keeps intent: a cue entry references a group whenever one covers the
targets (a greedy cover over the groups whose members *with that attribute* fit), keeps
preset references, and lists the rest explicitly; a preset cascades from the requested
scope to profile and target values only where targets disagree. `merge` restricts the
existing entries to the targets the programmer does not cover (a group entry that loses a
member becomes an explicit list; a spread becomes per-target values computed from the
original fan, so nothing moves) before adding the new ones. Effects are recorded by
instance id: `merge` replaces or appends them, `remove` drops them, targets equal to a
group's members stay a group reference, and in a tracking list an instance equal to the
one the cue already tracks is not stored.

**Live swap** (`busk.engine.install`). An install is applied at stage 1, in queue order:
per-slot runtime arrays follow the slot remap in one vectorised step, and each running
playback is re-pointed at its recompiled cue by cue id (a deleted cue falls back to the
next number) and **fades** to the cue's new state with that cue's timing (a chase with its
step crossfade), keeping every slot's sequence number, so an edit never reorders the
stack. An edited effect cross-fades to its new form on its running clock. A list the edit did not touch is left alone. Pending auto-GOs are re-derived from
the edited triggers, and chases and speed masters carry their phase over. Frames carry the
compiled show they were made with: when it changes, the output thread closes, opens and
re-points its routes (rows matched by universe id) and the bindings re-read themselves.

**Persistence** (`busk.persistence`, §17). `.show` files are a ZIP holding `show.json`,
written deterministically (equal shows, equal bytes) and atomically (temp file, `fsync`,
`os.replace`, directory `fsync`), with 10 rolling backups. The autosave worker reads the
session's snapshot without its lock, writes the show 5 s after a burst of edits and
`session.json` at most once a second, and on start-up after a crash the programmer,
master levels and unsaved edits are restored.

**Processes** (`busk.process`, Phase 7, §16, §18). The root (`root.py`) makes two control
socket pairs, spawns the engine (`python -m busk.process.engine_host`, in a session of its
own) and the console (`python -m busk.process.console_host` with the run's arguments), and
hands each of them one end of a third pair (`socket.send_fds`): the console ↔ engine link.
Every message is a length, a kind and a payload (`wire.py`): a frame is a fixed header
(sequence, time, layout id, universe count, output enabled) and the raw universes,
everything else is a pickle. Pickle crosses only these links, between processes of one
tree; nothing from the network is ever unpickled. The engine host runs three threads: one
decodes the link into the engine's queue, the engine thread ticks as in `--threads`, and a
publisher sends the newest frame to the root whenever the socket takes it (a slow root
makes it skip frames, never the tick wait) and snapshots and statistics to the console. The
console runs what `busk run` ran in Phase 6, with a `RemoteBus` (`links.py`) as the
session's bus: one lock orders its writers, so an install still precedes the commands
validated against its show, and the engine never validates again. The root's output
scheduler reads an `OutputLayout` per compiled show (universes, output settings, the dark
bytes), sent before the first frame made with it, so the root runs no show code.

**Installs across processes** (`ShowEncoder`, `ShowDecoder`). A live swap keeps a
playback's fades when its compiled cue list is *the same object* as before, so a compiled
show that arrived as new objects would retarget everything. The encoder sends what the
engine reads (the *engine view*: no channel records, memo, warnings or per-slot records,
the slot keys as one tuple) and pickles with `persistent_id`: an object that is the same as
in the previous install on that link (the rig, the conversion plan, each cue list) goes as
a reference, which the decoder resolves to the object it already holds. An edit therefore
sends what the incremental compile changed and identity survives the trip. A big install
goes in chunks (the rig, then each changed list), loaded one at a time with a GIL yield in
between, and the engine sees it only when the commit arrives; it then freezes its garbage
collector (`gc.freeze()`), so collections never scan compiled shows.

**The watchdog and the restore** (`Root`, `Engine.restore`). The root's main loop (10 Hz)
sees each new frame as a heartbeat, tells the console `stalled` after 1 s, and after 3 s,
an exit, or no first frame within 15 s of a spawn (imports and the first install of a
§19-sized show), kills the engine, spawns a new one with a new link and sends the
console's end over (`Attach`, with the reason). The console says `hello`, gets `welcome
(fresh)`, sends the full install, then a `Restore` of the last `EngineSnapshot` it
received, then the commands it queued meanwhile. `Engine.restore` sets the master levels,
the speed masters' tempo and beat anchor (`CLOCK_MONOTONIC` is shared by all processes,
so the grid lands where it was), blackout, output, the page, and activates every playback
that was active at its cue and fader level, snapped, in the order of `PlaybackStatus.seq`
(each activation's number), so the LTP stack is rebuilt in activation order. A restart
within 10 s of the last restore sends no restore, and more than 3 in 60 s give up.

**Console restarts and the show stamp.** Each install carries `(sessionId, showVersion)`,
and `session.json` records the stamp of the newest show written to disk. A restarted
console (`--restarted`) recovers from autosave, takes the engine's masters, tempos and
page from its `welcome`, and compares stamps: the same stamp sends only the programmer;
otherwise it installs its recovered show as a live edit. That install's slot remap is
computed by the engine from the slot keys it keeps, since the new console never saw the
engine's compiled show.

**The safety stage** (`busk.compiler.safety`, `busk.engine.safety`, §12 stage 11). The
compiler turns park entries into slots and values (a target that lacks the attribute is
skipped with a compile warning), limits into per-lane bounds in logical degrees on every
element, and finds the strobe lanes and, per universe, the dark bytes (every dimmer byte,
and the emitter bytes of virtual-intensity fixtures, at intensity 0). Each tick, after the
masters, `apply_safety` works on the output frame only: highlight, park on intensity
lanes, blackout, park on every other lane, limits, strobe lanes clamped to the cap; after
conversion, highlight's `highlightDmx` bytes. So releasing any of it returns exactly to
the live state, and a parked slot cannot be moved by anything else.

**The strobe cap on effects** (`busk.engine.effects`). An effect with an intensity layer
counts flashes per cycle (1 for every waveform but `step`, which counts its rises, and
`curve`, its peaks). With the cap set, an Hz effect's rate is clamped so that rate ×
flashes stays under it; a BPM effect halves its cycles per beat until it does, which keeps
it on the beat grid, and a tempo change re-rates it through the existing align-and-nudge,
so it never jumps. Chases are not capped.

**Highlight** (`busk.engine.install.Highlight`) is not a source. While the mode is on,
the session builds it into the programmer frame from the selection: the selected targets'
intensity, shutter and colour lanes with the values to force (1, `open`, white), and the
byte positions and `highlightDmx` values of their other channels (never pan, tilt or a
parked slot). The safety stage writes the lanes, and the bytes over the converted
universes. It is live even while the programmer is blind.

**Panic, stalls and output off** (`busk.engine.loop`, `busk.output.scheduler`).
`RELEASE_ALL` releases every playback that is active, releasing or flashing, with its own
release time or the given one, and drops held flashes and swops. `OUTPUT` is engine state
(`EngineSnapshot.outputEnabled`), carried in each frame, so the root's output follows it
and a restore brings it back: while it is off no route sends, and sACN routes send
Stream_Terminated once and start a new stream when it is on. The scheduler also watches the
frames: 1 s without a new one, it offers the last frame again every cycle (held), or a
copy with the layout's dark bytes set when `holdLastFrameOnEngineStall` is false.

**Reconnects** (`busk.output.scheduler`, `busk.io.surfaces`). A route whose driver fails to
open is retried every 2 s by building a new driver; one whose status has failed for 1 s is
closed and opened again (its interface index and addresses are looked up at open), with
sequence numbers kept in the scheduler's shared `Sequences` and `ArtNetNetwork`, so they
continue across reopens and engine restarts. sACN and Art-Net drivers report a failure
until a send succeeds, so an outage prints once. Art-Net broadcast routes re-read their
broadcast address every 2 s and poll at once when it changes. MIDI has no unplug event in
rtmidi, so the surface manager and the feedback worker compare the port names every 2 s.

**Import** (`busk.importers`). The OFL importer builds each mode from its channels'
capabilities through a table (phase-7-plan §5.18): each capability becomes a range segment
of a busk attribute, unmapped ones become `control` channels at their `defaultValue`, and
each mode is validated alone (a mode that fails is skipped with a note), then the whole
profile. The GDTF importer reads `description.xml` from the archive with expat, refusing
any `DOCTYPE` (so no entity can be declared) and anything over 32 MB inflated, then maps
DMX modes, channel functions, wheels and emitters the same way, with GDTF's DMX notation
(`128/1` mirrored to `0x8080` on 16 bit) and CIE xyY converted to linear RGB. Both return
the profile and an `ImportReport` of notes.

**The event log** (`busk.persistence.eventlog`, `busk.replay`, §15.5). The engine appends
each applied item to a record deque in the drain, with the tick's time: a command
envelope, an install's *cause* (a show edit as its patch ops and label, a programmer
change as its new state, a connection's start with the whole state), or a restore. In
processes the engine host sends the records to the root every 100 ms, which writes them;
with `--threads` a `LogPump` thread does. Nothing in the tick does I/O, and a full deque
drops and counts (`logDropped`). A selection or a fade time, which installs nothing, rides
on the next install. `busk replay` rebuilds the session at each start record (and a new
engine when the start says the engine was fresh) and ticks at every logged time, so the frames equal the run's byte for byte.

## Conversion rules (decisions of the Phase 1 plan)

* **Capabilities are authoritative**, pan and tilt included: `physical.panRange` is
  informational. A value maps through the first range segment that contains it, else the
  nearest one (first on ties), clamped: `t = (v − v0)/(v1 − v0)`, `raw = rint(d0 + t·(d1 − d0))`.
  A zero-span segment outputs the centre of its DMX range. `invert` swaps `v0` and `v1`.
* **Orientation**: the pan channel reads the tilt value when `swapPanTilt` is set, then
  `deg = (input + panOffset)`, negated if `invertPan` — the channel's own settings.
* **Dimmer curves** (`linear`, `square`, `invSquare` = 1 − (1 − x)², `sCurve` = x²(3 − 2x),
  or a table) apply to dimmer channels and to virtual intensity alike.
* **Colour**: with a white emitter and no explicit `w`, `w = min(r, g, b)` is subtracted
  from r, g, b; an explicit `w` is used as given. Explicit `a`/`uv` are used, otherwise 0.
  CMY is `1 − r`, `1 − g`, `1 − b`. Other emitters (lime, cyan, custom) output 0 until
  calibrated mixing exists. Virtual intensity scales every additive emitter.
* **Options** output the centre of their DMX range. The shutter guard is the registry
  default: an uncontrolled shutter outputs `open`, never its `defaultDmx`.

## Decisions beyond the plan

Phase 1:

| Decision | Why |
|---|---|
| `control` channels are exempt from the `(element, attribute, component)` uniqueness rule | The MH-X25 has two control channels (special functions, built-in programmes); real fixtures commonly do. Control channels never become slots, which is what the rule protects. |
| Parameters of `control` channels' functions create no slots | They are never output (§13.5); a slot for them would do nothing. |
| Slots are in strict registry order (`gobo1` before `zoom`) | Plan decision 4 says registry order; the plan's step-3 example list put `zoom` first. |
| `Slot.wheels` | The values file must check a value's `wheel` against the channel's wheel, also for unpatched fixtures (which have no compiled channels). Phase 2's cue compiler needs the same. |
| `CompiledChannel.subtractive` | An emitter's role depends on whether it is subtractive, not only its id (a declared additive emitter may reuse a built-in id). |
| `invert` does not affect option tables or function parameters | It is defined for range capabilities ("255 = minimum"); a shutter's options have no direction. |
| Colour rows computed only for the columns that need them | White, amber, UV and CMY rows are computed per extra-column subset; that cut the colour kernel from 155 to 104 µs on the benchmark rig, bit-identically. |
| `compiler/rig.py` | Slots and channels both need each fixture's profile, mode and per-element analysis (colour system, extras, virtual dimmer); it is computed once per mode. |
| `UNIVERSE_SIZE` lives in `convert/dmx.py` | The plan module needs it and `compile.py` imports the plan; `compile.py` re-exports it. |
| Values are checked in `model/validate.validate_values` (structure + park checks) and `compiler/values.compile_values` (against the compiled show) | They reuse the show validator's path mapping and park checks; the plan's `load_values(path, show)` just reads the file. |
| Demo: MH 2 also gets intensity 1 | A strobing shutter at intensity 0 is invisible on real hardware. |
| Only the modes the demo uses are transcribed (MH-X25 12ch, ML-56 4ch, PiX 36ch) | Each profile's `notes` says so; other modes add data without exercising anything new. |

Phase 1.5:

| Decision | Why |
|---|---|
| `build_routes` returns `RouteNotice(text, failed)` notices instead of plain strings | The CLI prints open failures on stderr and disabled or ignored routes on stdout (plan §5.8), so it must tell them apart. |
| Notices name every protocol by its label (`Art-Net r2`, `DMX-USB r4`), like `sACN r1` | One naming scheme for all route lines; the plan's example used the raw tag (`artnet r2`). |
| `builders.localhost_route(show)` has no port parameter | A unicast destination has no port field; the `receiver` fixture patches `SACN_PORT` instead. |
| Termination is sent only if a packet was ever sent *successfully* | If every send failed, no receiver saw the stream, so there is nothing to release. |
| The packet is built in the `SacnSender` constructor rather than at open | It is still built once per route, and the sender never holds a missing packet. |
| `OutputScheduler.close()` is public | `run` calls it in its `finally`; tests use it to terminate streams without a thread. |
| The 0.25 s status loop also runs under `--duration` | Phase 1 slept through the whole duration; scripted runs now report send failures too. |
| A failing `IP_MULTICAST_IF` reads `cannot send multicast via '10.0.0.5': Cannot assign requested address` | The raw `[Errno 99]` doesn't say which setting is wrong (here: no interface has that address). |

Phase 2:

| Decision | Why |
|---|---|
| Step 9 (sACN, output scheduler) dropped; decision 13 (continuous 44 Hz) superseded | Phase 1.5 delivered them, with send-on-change and keep-alive, as plan step 0 anticipated. |
| Grand masters start at their `initialLevel`, else 1.0 | Decision 6 says the schema has no such field, but Phase 0's schema already added it to every master kind (§5.13's prose). |
| `--values` is kept: it sets the resolver's starting frame (what uncontrolled slots output) | The plan's `run` drops it, but the Phase 1 goldens, the Phase 1.5 done criterion and its hardware checklist use it; as a base frame it composes cleanly with playbacks. `Engine`'s third parameter is renamed `logical` → `base`. |
| `intensityLanes` live on `SlotTable`, not `CompiledShow`; no stored `defaultI` | They are derived from the slots (phase-1-plan §10 put them there); the HTP pass starts from the base frame's intensities, so a values file's intensities work too. |
| The engine owns its bus (`engine.bus`) | Bindings, the CLI and tests need the bus that the engine drains; one owner avoids wiring them separately. |
| A `Playbacks` coordinator holds the runtimes, the sequence counter, the live set and exclusivity; `EngineRuntime` holds it, the GM levels and blackout | Exclusivity and fresh sequence numbers span playbacks; the state machine stays per playback in `PlaybackRuntime`. |
| An LTP weight of exactly 1 replaces lanes exactly | `v + (x − v)·1` can miss `x` by an ulp; "the newest source wins" should be exact. The oracle's literal lerp agrees within 1e-12. |
| HTP computes `value · (scale · weight)` | One scalar product, then one array multiply, as the plan writes it; §7.4's left-to-right product differs by at most an ulp. |
| Snapshots are compared, not just flagged dirty | A no-op command (a release of an idle playback) publishes nothing; the CLI's status line only prints real changes. |
| Dropped discrete values become compile warnings (`CompiledShow.warnings`, printed by `run`), including a value on another `wheel` | Decision 9 says "reported"; a warning with the entry's path matches validation's issues. A `wheel` mismatch is the same mistake. |
| `cue_from_values()` is public | The resolver's property tests build sources from arbitrary lanes; Phase 3's programmer can reuse it. |
| The limitation report checks first cues only for curves, timing and effects; it skips cue `releases`/`block`, and Art-Net/DMX-USB routes | The rest of a multi-cue list is covered by its "only the first plays" line; `releases` and `block` cannot matter on a first cue; the route notices already list other protocols. |
| `collect_limitations(show, compiled)` takes the compiled show | It needs master kinds for bindings and embedded commands, and shares `unsupported_reason()` with the bus. |
| Panic's buttons are `toggle, flash, release` like every other slot | The plan's table says `flash, toggle, release`, but checklist step 6 says "hold M8"; one layout for every slot is also easier to play. |
| The status line prints when its *text* changes; faders show two decimals; the main thread polls every 0.1 s | A moving fader would otherwise print a line per tick; 0.1 s is the plan's poll. |
| The stats line gains `, N commands, M command errors` | One line, as checklist step 9 reads it. |
| A missing MIDI backend prints `MIDI <surface>: unavailable: …` and the run goes on | Like a missing device, without ALSA's sequencer the console still runs (from other inputs, later). |
| The benchmark uses the existing `perf` marker and `test_perf.py`, on `builders.benchmark_rig` plus busking content | The plan predates Phase 1's `perf` convention. The rig has §19's ~20 000 slots, in 1 856 fixtures rather than ~400. |
| `test_limitations.py` is its own file | The plan put the limitation list in `test_compile_cues.py`; it tests a separate module. |

Phase 3:

| Decision | Why |
|---|---|
| Setting a value counts as a touch even when it does not change (`Change.written`) | The plan's "touched" was "the source differs". But re-setting pan after a newer band-100 playback took it over must put the programmer back on top: "latest" means the operator's latest action (§8.1). |
| `validate_edit` finds touched entities by identity and stores their validated copies | Copy-on-write makes identity exact (op pointers shift when a batch inserts). Storing the validated form keeps the store identical to what a load produces (schema key order, floats, tuples), so save → load is equal and undo restores deep-equal shows. |
| Warnings are reported only when an edit introduces them | The semantic pass covers the whole show; repeating every overlap warning on every edit would bury the new ones. |
| `SET` needs a path ending at a key; the top-level lists and required root objects cannot be replaced or deleted; `SET ["meta"]` is protected too (it holds `meta.id`) | Keeps generic edits element-addressed, so undo stays precise and ids immutable. |
| `ADD` of a cue inserts it in number order | Cues must be sorted (validation); appending would reject most additions. |
| A running playback is re-pointed at its playback's (first) cue rather than looked up by `CueId` | Until Phase 4 a playback only ever plays its list's first cue; looking up the old cue id would play a cue the list no longer starts with. Phase 4 changes this with GO. |
| Edits are delivered to engine and output through the existing `CommandBus` queue (`bus.install`) and the bus's `compiled` is updated by the session at commit | One FIFO for commands and installs gives the plan's ordering for free; validating against the latest committed show lets `fader 9 1` work right after `record slot 9`. |
| `ShowState` (`session/state.py`) and `CommandError` (`commands/errors.py`) | The programmer, recording and the session share one immutable "committed show + compiled + lookups" object, and one error type with issues. |
| `record cue L` without `/C`, `bind … blackout`, `cc … button`, `route … multicast IF`, `status`, `help`, `exit` | Small gaps in the grammar the build script or busking needed (the nanoKONTROL2's buttons send CCs; a blackout button). |
| Element, slot and button numbers count from 1 in the console | They name physical controls and cells ("cell 3"); commands keep 0-based indices. |
| `--iface` defaults to `eth0` | The plan's verification runs the build script without `--iface`; `eth0` is what the example shows use. |
| Status lines are not printed at an interactive prompt (`status` prints one) | They would garble the line being typed; piped and `--no-console` runs still print them. |
| Ctrl+C is held back while a console command runs | A `KeyboardInterrupt` between queueing an install and committing would leave engine and session with different shows. |
| `--duration` with a console: the end of stdin does not end the run, and an unreadable stdin counts as its end | Keeps scripted runs (and the existing tests, whose stdin is captured) running for their duration. |
| The autosave worker notices edits by polling the session's versions | No notification hook needed, and the worker never takes the lock. |
| GIL switch interval 0.1 ms, not 1 ms, plus `gc.freeze()` after loading | Measured (step 13): 1 ms changed nothing, 0.1 ms cut stalls by ~5×; freezing cut the longest GC pause. |
| `busk new` refuses to overwrite; `busk run` names the newest backup when a show fails to load | §18: "refuse to load, offer last backup". |
| The limitation report's header says `Ignored in Phase 3:`; `select` buttons are no longer listed | They work now (`SELECT_PLAYBACK`). |
| `test_resolver_properties.py` allows one subnormal of slack | Hypothesis found `5e-324 · 0.47` rounding to 0, which a purely relative tolerance cannot express; the test's own comment allows an ulp. |

Phase 4:

| Decision | Why |
|---|---|
| A source's sort key is the newest number of its LTP and snap lanes, not of its HTP | HTP merges per band whatever the order; only LTP and snap lanes compete on "latest". |
| The per-lane LTP lerp is `below·(1 − w) + value·w`; HTP "falls" iff the target is below the current `value·weight` | The first equals the scalar form at `w = 1` exactly; the second compares what is actually on stage (decision 6's "effective intensities"). |
| Finished groups settle when the set is evaluated; scale and LTP scale are separate retarget inputs | Settling in the tick keeps commands cheap; a re-activated releasing playback folds the release level into HTP and LTP presences independently (`followFader` vs `ignoreFader`). |
| A release freezes the slots, then fades the playback's envelope | A release in mid-transition glides down from where the slots are (decision 8) instead of finishing the transition on the way out. |
| **A finished release is a due event**, fired before the tick's commands | Otherwise a GO on a playback whose release just ended would fold the old cue's frozen values or not, depending on the tick schedule. |
| A manual move to the current cue re-asserts it (also GO/BACK on a one-cue wrap list); no auto-GO when the next cue is the current one | Re-asserting is decision 9's GO at the end; an auto-GO onto itself would loop at the lap cap. |
| The lap cap (one lap of auto-GOs per tick) counts across both `advance` calls of a tick | A command between them could otherwise double the laps. |
| Snap thresholds are fixed per lane while its fade runs | A threshold that changed under a kept fade would make the value jump; the property test's generator was fixed to respect it. |
| A speed master's default level is its ×1 step (the nearest by log ratio when there is none); level → step and tap phase round half up; a tap at the same time as the previous one is ignored; a tapped tempo is capped at 999 BPM | An untouched knob means ×1; one rounding rule for levels; a bouncing contact is one tap; 999 is the schema's limit. |
| **Never-back alignment moves to the next grid position**, not to `floor(p_ref)` as §5.7 writes | `floor(p_ref)` can leave the chase between grid lines after a rate change; the next grid position keeps it on the beat (`test_never_back_stays_on_the_grid`). |
| Random chases start at cue 1 and BACK draws a new cue; BACK on a bounce steps against its heading without turning it | A random chase has no "previous"; turning on BACK would make two BACKs a no-op. |
| A chase that falls more than a lap behind (a long stall) retargets only its last lap | The skipped steps cannot be seen; retargeting each would cost a lap of retargets in one tick. |
| Blind installs of the programmer take no sequence number; programmer lanes fading out keep theirs | A blind change is not an action on stage; a value fading out stays where it was in band 100 until it is gone. |
| Edits: a releasing sequence keeps its frozen slots (a releasing chase takes the edit); BACK and release disarm auto-GO re-derivation; an auto-GO made overdue fires at the install; the transition's start and completion are kept | A release is on its way out; the operator's BACK must not be undone by an edit; overdue means now; recomputing `follow` from an edit would move a pending cue. |
| An edit that leaves a playback's compiled cue list the same object, on the same slots, does not retarget it | Its states are identical, so the retarget would change nothing, and on a big rig it cost a retarget per running playback per edit (step 18). |
| `SELECT_PLAYBACK` reads the cue number from the snapshot and falls back to the first cue when the show no longer has it | The snapshot can be a tick older than the session's show. |
| A recorded cue whose values all track is created with no entries; tracking compares clamped lanes | Recording the same look twice is not an error; a cue may hold an out-of-range value that plays clamped. |
| The snapshot also carries each playback's fader kind, chase flag and cue count; the status line shows a cue only for sequences of more than one cue, and a fader level only for `master` and `temp` faders | The status line needs them; `1 Warm on 1 Warm` and a line per chase step were noise. |
| The recovery message lists tempos only when some were restored; masters the show no longer has are skipped | Older autosaves have none; a deleted master is not an error. |
| `master add speed` rejects a duplicate name; `chase bpm` takes the multiplier as `x 2` (the plan's example wrote `x1`) | Masters are named, not numbered, in the console, so names must be unique; options are keyword–value pairs, like `crossfade 0.25`. |
| Engine-thread set operations use a sort-based `distinct`, not `np.unique`/`np.union1d`; a retarget onto the same lanes takes a fast path | NumPy 2.3+ hashes in `unique` (194 µs on 20 000 lanes against 15 µs for a sort); together they took a 60-GO tick from 55 to 17 ms (step 18). |
| The GO-burst benchmark gates the median under 20 ms, not the p99 under 10 ms | The 10 ms gate is missed (see *Benchmark*); the p99 varies between runs, the median does not. |
| The song's chase steps clear the programmer between cues | Each step must hold one wash only; the plan's illustrative script left that out. |

Phase 5:

| Decision | Why |
|---|---|
| Two absolute colour layers in one template are duplicates; a `pulse`'s fractions may exceed 1 by 1e-9; a `speedMasterId` warning only when the reference is otherwise valid; `low`/`high` must be finite, and a missing bound is reported once per bound, naming every attribute without a range | A colour layer drives `r, g, b` as a whole; `0.1 + 0.2 + 0.7` is not 1 in floating point; a warning on top of an error is noise; one message per bound reads better than one per layer. |
| `random` hashes with splitmix64, chained over seed, member and cycle, the top 53 bits giving `[0, 1)`; a `curve` is extended periodically only on its open sides | A counter-based hash keeps the wave a pure function of time (decision 3); points at both 0 and 1 with different values jump on purpose. |
| Waveform compilation and phase spread live in `compiler/effects.py`; the compiled forms compare by identity, with a structural `same()` | The compiler never imports the engine; identity is the fast path of the incremental compile, `same()` what a live edit needs. |
| Absolute intensity layers merge HTP, as positions in the intensity lanes | An intensity wave over a static look shows only above it (decision 7), as HTP does for values. |
| Coverage (`A`) is computed over LTP and intensity lanes only, not snap lanes as the plan says; relatives are gathered by their own function | Validation keeps relative layers off snapping attributes, so a snap coverage would never be read. |
| A clock's re-rate takes the master too; the same rate and master leave a running nudge alone | A new version may switch between Hz and BPM or to another master; re-applying the same rate must not restart a nudge. |
| A retarget prunes settled versions first; a change fades with the cue's in time, not `sizeFadeIn` | So an instance that has faded out starts a new clock whatever the tick schedule; `sizeFadeIn` is an entrance. |
| Taps: the bank hands out its locked clocks, and the caller reads their positions, taps the master and aligns them | Positions must be read *before* the master's phase moves, for every bank (main, flash, programmer) and for chases in one place. |
| In a tracking list a cue's own instance replaces a tracked one with the same id in place, even where its releases would have trimmed the tracked one | A cue's own content wins over its own releases (phase-4-plan §9); the instance keeps its place and its clock. |
| A main release that ends under a held flash starts the flash bank at the release's end time, not at the tick that notices it | Otherwise the flashed effects' clocks would depend on the tick schedule. |
| A live edit re-times both banks (main and flash) after retargeting | A speed master's steps or a fader's kind may have changed in the same edit. |
| Programmer effects compile with a short-lived compiler whose warnings are dropped; an instance with validation errors stays dormant and is skipped | The programmer is rebuilt on every change; dormant effects come back with an undo, like dormant values. |
| The snapshot and the recovery carry group and size master levels; recovery drops programmer effects that no longer validate, with a message | A `kill -9` must bring back the whole performance state (pulled forward from step 15). |
| `record cue` merges effects by id; ids equal to the ones a tracking cue inherits are not stored; targets equal to a group's members become that group (the lowest number), `freeze` keeps them explicit | As values: record changes only and keep intent (phase-3-plan §5.5). |
| The library is a JSON list of `{template, defaults}`; bad items and duplicate ids or names are skipped and reported; `effect add` embeds a library template as its own command (two undo steps) | The console's defaults (size, `low`/`high`, phase) belong with the template; a template already in the show is reused by name. |
| The default id is the lowest `fx<n>` used neither by the programmer nor by any cue | So `record … merge` appends a new effect instead of replacing another one. |
| `master add` takes `speed`, `size` or `group` (the error names them); `list cues` counts a cue's effects only when it has some | Grand masters are in every new show; most cues have no effects. |
| The status line shows the level of `size` faders, like `master` and `temp` | An effect playback's knob is its level. |
| Effect benchmark groups are appended after the existing ones | The benchmark rig's random generator and the earlier benchmarks stay unchanged. |

Phase 6 (the plan's own calls, which the user has not decided, are listed in phase-6-plan
§3: one global page owned by the engine, takeover as engine state, latching blackout,
swop by presence, the crossfade fader's rules, the fade-time formula, MIDI clock as taps,
a performance-only web API with a key, no new dependencies):

| Decision | Why |
|---|---|
| A `gotoCue` naming no cue and an embedded `PAGE {number}` naming no page are **warnings**, not errors as plan §5.18 says; an OSC `feedbackPort` is range-checked | The same rule as embedded GOTOs and `pageAbs`: numbers get renumbered, and an error would block that edit. |
| A deleted current page gives way to the first page numbered at or after it, else the last | A page that took over its number is the one the operator expects. |
| Every command from a binding carries `{surfaceId, control}`, not only page-relative ones (pulled forward from step 6) | Soft takeover and held buttons both need the control. |
| A held button's release applies the function recorded at the press; a stray swop release is ignored | A live edit turning a flash into `go` must still let the flash go; a release without a press must not leave a negative count. |
| `select` with no or an unknown page in the snapshot uses the first page | The resolver runs before the engine has published a page. |
| The status line prints `swop` instead of `flash` while a swop is held, `Fade 2.5 s` while a fade-time master is up (`EngineSnapshot.fadeTime`), and a manual crossfade as `on → 2 c2 50%` (the plan wrote `on 1 → 2 50%`) | The from-cue is not in the snapshot; the target and the progress are what the operator steers. |
| A move on an empty slot records the control's position and detaches it | Otherwise coming back to the page could take over by a stale crossing. |
| `MASTER_ARRIVES_IN` is removed, not left empty; recovery restores every master kind; the threshold latch keeps the cue's timing | Every master kind is implemented; the latch is a fader action, not a transition. |
| A chase ignores its crossfade fader; a fader leaving its rest end with nothing pending detaches until it reaches an end; a move to the rest value starts nothing; starting a manual transition settles running fades first; a live edit that leaves the cue list alone keeps the transition | A chase has no "next cue" to run by hand; the other rules keep the fader from ever jumping. |
| A failed feedback send counts as sent (retried when the value changes) and is reported once per surface; OSC feedback sends report socket errors (the plan said "never raises"); feedback to a non-OSC address on an OSC surface is not sent | A 30 Hz retry of a dead port would flood the log; a silent failure would hide a wrong address. |
| MIDI feedback ports open only for surfaces with feedback bindings | Opening an output nobody writes would hold a port another program may need. |
| The web key file is mode 0600; when the state directory is read-only the run goes on with a key for this run only; the show message gives masters a `tap` flag | The key is a password; a read-only directory must not stop a show; the header's TAP needs to know which master takes taps. |
| The web API releases every button a phone held, not only flashes and swops; a phone's press has no control, so its release uses the function current at release time | Any held press must end when the phone goes; a phone's buttons are addressed by playback, not by a control. |
| Surface names are unique; `feedback` on an input with no binding is an error; `record slot` says `recorded slot 2.1` only off the first page | Names address surfaces in the console; a typo must not silently do nothing; single-page shows read as before. |
| The done criterion's timeline raises the song's fader from the phone right after the goto press | §5.19 never raises it and it starts at 0, so the Chorus would show nothing. With the press first, every §5.19 value at 12.25 s holds as written. |
| Port-Addresses print dotted (`0.1.2`), as the console takes them; the Art-Net socket is reference-counted; `RouteNotice` lives in `driver.py` | One notation in and out; `build_routes` callers can never leak the socket. |
| A broadcast route unicasts only to nodes on its interface's network; at most 64 datagrams are read per output cycle; replies without output ports are ignored; nodes are kept per bind index | Two lighting networks must not feed each other; a flood must not stall output; controllers (busk included) are not nodes. |
| sACN discovery lists the unicast routes' universes too, sent only out of multicast interfaces | They are universes busk sends; discovery is multicast. |
| A DMX-USB frame dropped behind a partial write is owed and sent next cycle; the rate is clamped to 1–40 Hz; a device that fails at start-up is not retried (only after a send failure; since Phase 7 the scheduler retries it every 2 s, like every route); `DriverStatus.dropped` counts drops | A dropped change must arrive late, not never; 0 would mean "as fast as possible" to the widget; start-up failures behave like every other route. |
| The web server sets `TCP_NODELAY` | Otherwise a state frame waits for the phone's delayed ACK of the previous one (50 ms round trips in the first bench runs). |

Phase 7 (the plan's own calls, which the user has not decided, are listed in phase-7-plan
§3: three processes with the output in the root, pickle over the internal socket pairs
with structural sharing, the look restored from the last snapshot, highlight before
blackout, the strobe cap off unless set, `holdLastFrameOnEngineStall: false` darkening only
intensity, `--threads` as the Phase 6 layout, `FogOutput` as intensity in OFL import):

| Decision | Why |
|---|---|
| `SET ["park"]` replaces the whole park list; `park` and `unpark` build the new list and set it, one undo step | Park entries have no ids, so ADD and DELETE cannot address them (the plan's BATCH of ADDs and DELETEs could not work). |
| A park entry whose target lacks the attribute is skipped with a compile warning (`park[k].slot.attribute`) | Plan §5.10 said validation already rejected it; validation has no slot table. |
| The strobe-cap warning (a fixture whose slowest strobe is above the cap) is a validation warning only, not also a compile warning (§5.11) | One message, not two. |
| Validation warns about `OUTPUT` off on "not a button": a pitch bend, or a CC without `led` feedback; notes, OSC and `hw` inputs never warn | The nanoKONTROL2's CC buttons have LEDs; a fader would cut the output each time it moves up. |
| `limits` on a mode without intensity is not checked | Every valid mode has intensity (a dimmer channel or virtual). |
| The safety stage is a function, `apply_safety`, not a `SafetyStage` class; capped BPM clocks re-rate on every tap and `SET_BPM` while a cap is set, with no per-master list | Nothing needs state between ticks; re-rating an unchanged rate is a no-op. |
| `RELEASE_ALL` with a time also cuts releases already running to it; a `temp` fader that is up keeps its flash | The operator's time is a maximum; a temp fader is the operator's hand, not a playback state. |
| The status line shows `OUT off` only while output is off | Existing status lines stay unchanged. |
| The scheduler sees a new frame by identity, not by its sequence number | A restarted engine starts its numbers again. |
| `Frame.layout` and `Frame.outputEnabled` are optional (none, on) | Hand-built test frames and the `--threads` layout need no layout. |
| Slot keys travel as `(target, attribute)` pairs, not strings (§5.3) | No separator to escape; they load in 1.4 ms on the §19-sized rig. |
| The `--values` base frame travels in the console's `hello`; a base that no longer fits a repatched show is dropped with a line, not a failed restart | The plan did not say how; a restart must not fail on a stale file. |
| A `Sync` queue item: `status` right after a start (or a restart) waits until the engine's snapshot shows what was sent (15 s at most) | Across processes the first `status` showed a stale snapshot. |
| `--duration` counts from the console's `ready`, not from the root's start | A short run otherwise killed the console while it imported. |
| A restored chase steps on the *next* grid boundary; BPM chases with steps more than a beat apart keep the beat, not which beat | Activation counts the nearest boundary as passed, which lagged one step; the step phase is not in the snapshot. |
| A console that is given up leaves no one to restart the engine: an engine that dies then is not restarted | Nothing could give a new engine the show. |
| A kept console seeds its encoder with the engine's show, and the engine its decoder | Otherwise every playback would rebind on the console's first edit. |
| A save does not count as a show version; a console exiting 70 forces recovery even after its clean-exit autosave | Saving installs nothing; the crashed console's `finally` writes "clean exit". |
| sACN and Art-Net drivers set "ok" on open only the first time; after that a failure lasts until a send succeeds; sACN's close skips Stream_Terminated after a failed send | An outage prints once instead of on every reopen; terminating into a dead network would only fail again. |
| A reopened Art-Net route forgets its address (bug fix); broadcast routes re-read their broadcast address every 2 s and poll at once on a change | A reopened broadcast route kept its old address while the node table was unchanged. |
| An OSC message whose values are all 0 is never dropped by the rate limit; the web limit counts messages after JSON parsing, garbage included | It may be a release (as the web exempts button releases); a flood of garbage is still a flood. |
| `info` names the three pids and the restarts (`PROCESSES`, a message the plan did not have) and the event log file | The operator needs the engine's pid to check a kill, and to know whether anything restarted. |
| `limits` sets each fixture's whole `limits` object, keeping the other keys; `safety strobe off` leaves `safety: {}` | `SET` creates only the last key of a path; edits refuse to delete a root key. |
| `highlight on\|off` arrived with step 4, not step 16 | The recovery test needed it. |
| No `LogStart` message: a connection's start is the cause of its first install, holding the whole state; programmer undo and redo are logged as the new state; `SELECT_PLAYBACK` is logged as the `SELECT` of the targets it found; a change that installs nothing (a selection, a fade time) rides on the next install | Ordered with the records, and replay needs no undo timeline or snapshots; replay failed on `sel` lines before the last rule. |
| OFL rules beyond the plan's table: C/M/Y without R/G/B become `cyanFlag`, `magentaFlag`, `yellowFlag`; an element's colour channels lacking a primary, a second channel of one attribute on an element, and a discrete channel offering no default option (`open`, a prism's `off`) become `control` channels; a dead band maps to a rest value (a scalar's `noFunction`, a shutter's `open`, a prism's `off`) | Validation needs a whole colour system and a default option; without these rules whole modes were skipped. |
| GDTF: emitter and slot colours clipped at 0 and scaled so the brightest primary is 1; pan and tilt centred on the channel's travel (the plan said physical degrees); intensity, focus, iris and frost rescaled when outside 0…1; no strobe or rotation estimates; a channel's default is `DMXChannel@Default`, else the initial function, else the first; a channel whose functions all depend on mode masters becomes `control`; the importer reuses the OFL importer's helpers | busk's colours are relative linear RGB and its positions are programmed around the centre; GDTF gives physical values, so nothing needs estimating. |
| A new console command, `unbind "<surface>" <input> [thru N]` | `bind` adds a binding; marker SET (CC 60) toggled the bar wave since Phase 5, so the panic button would also have started the wave. |
| Two corrections to §5.24's table: at 3 s MH 1 is at tilt 10° from a tracked 40° (not 20°), and after marker SET the stage is at its defaults after 3 s (the Song's release time) | §5.24 took Phase 6's halfway values and Appendix A's release time. |
| The soak is three files (`soak.py`, `soak_receiver.py`, `soak_load.py`); a 4 s `SIGSTOP` always ends in a watchdog kill, so restarts must equal kills plus stops; `--stats` engine records gained `installErrors` and `commandErrors` | Each process has its own job and its own failure; the soak's error criterion needs the counters. |
| Bug found by the soak: after an engine restart, the root's `--stats` paired the new pid with the old engine's counters until its first `STATS`; `_start_engine` now clears them | The 1-hour report's tick totals were recomputed without those lines. |

### Transcription notes (real fixtures)

Sources: the Thomann MH-X25 manual (§7.6), the Eurolite ML-56 RGBW manual v1.0 and the
Chauvet DJ COLORband PiX manual Rev. 6, cross-checked against the Open Fixture Library
(`stairville/mh-x25`, `eurolite/led-ml-56-rgbw`, `chauvet-dj/colorband-pix`). Where they
disagree the manual wins unless it contradicts itself; each profile's `notes` records it:

* MH-X25 colour wheel: the manual gives white as 0–7, overlapping yellow at 5–9 (a typo);
  0–4 is used, as in OFL. Gobo wheel 128–255 is described as a "rainbow effect", copied
  from the colour wheel; it is gobo wheel spin. Sound-control programmes follow the
  manual's 16-value ranges (OFL has 15).
* Estimates, not measurements: MH-X25 strobe 0–13 Hz across 8–215 (the manual's spec-sheet
  shutter frequency, mapped linearly) and gobo rotation 10–360 °/s (the chart only says
  "increasing speed"). Gobo rotation DMX 0 is index 0°, used as "stopped".

## Busking checklist (Phase 2)

The manual check of phase-2-plan §8 is the remaining step of Phase 2. It needs a
nanoKONTROL2 (or another controller, with the demo's bindings edited), and an sACN
receiver: fixtures through an sACN node, or sACNView / QLC+ / OLA (Wireshark with
`udp.port == 5568` dissects E1.31). Set the demo route's `iface` to your interface, patch
the rig as in the demo (spots at 1 and 17, pars at 33, 36, 39 and 42), then:

1. `busk run examples/phase2-busk.json` prints no limitations, the route line, and the
   matched MIDI port.
2. Raise fader 1 slowly. Every fixture follows the fader, and warm white comes in once the
   fader passes 2 %. Pull the fader to 0: intensity drops with it, and the status line
   shows Warm going from `rel` to idle.
3. Raise fader 1, then press S3: everything fades to blue over 1 s. Press S4: red over
   1 s, and Blue goes `rel` → idle. Press S4 again: back to warm, **not** blue.
4. With Red up, hold M3 (flash Blue, `includeLtp`): everything is blue while held and
   exactly red again on release.
5. Raise fader 1, then press S6 and move fader 6: the heads move proportionally between
   their current position and Audience.
6. Hold M8: all white at full, over everything. Release it: the exact previous look
   returns.
7. Knob 8 scales all intensity. Holding ■ blacks out; releasing it restores the exact
   look.
8. MIDI → light latency feels immediate (worst case ~10 ms engine tick + ~23 ms output
   cycle).
9. Ctrl+C: the stats line shows 0 overruns and 0 command errors.

**Rehearsed without hardware** (no controller or rig at hand): a script played the
nanoKONTROL2 through a virtual ALSA port, ran `busk run` on a copy of the demo whose
surface matched that port and whose route sent unicast to 127.0.0.1, and read universe 1
from an sACN listener on port 5568. Steps 1–7 and 9 behave as written, byte for byte:

| Step | MH 1 R G B W / dimmer (16-bit) | Par 1 R G B | MH 1 pan / tilt |
|---|---|---|---|
| fader 1 at 2/127 (below 2 %): white, dimmed | 0 0 0 255 / 3·58 | 3 3 3 | centre |
| fader 1 at 3/127: warm white comes in | 140 76 0 115 / 4·214 | 5 4 2 | centre |
| fader 1 full: intensity 0.8 | 140 76 0 115 / 204·204 | 204 153 92 | centre |
| S3 (Blue), S4 (Red), S4 again | blue, red, then warm again (not blue) | | |
| hold M3 with Red up / release | 0 0 255 0, then exactly 255 0 0 0 | | |
| S6 + fader 6 at 64/127 | | | −15.1° / 20.2° (halfway to −30° / 40°) |
| hold M8 (Panic) / release | 0 0 0 255 / 255·255, then the look again | 255 255 255 | |
| knob 8 at 64/127 / hold ■ / release | dimmer 103·52 (0.40), 0·0, 204·204 | 103 0 0, 0 0 0, 204 0 0 | |

The status line followed every step (`… · 3 Blue rel · 4 Red on`, `… · 3 Blue flash · 4 Red
on`, `GM 50% | BO on | …`), the run ended with `0 overruns, 20 commands, 0 command errors`,
and the listener received 3 Stream_Terminated packets at the end. Step 8 needs the real
controller.

## Hardware checklist (Phase 1.5)

The manual check of phase-1.5-plan §8 is the remaining step of Phase 1.5. It needs a
wired link to an sACN → DMX node (or a fixture with native sACN) on universe 1, a copy of
the demo with the route's `iface` set to that interface, and the DMX chain patched as in
the demo: MH-X25 #1 at 1, MH-X25 #2 at 13, ML-56 at 25, COLORband PiX at 29. Then check:

1. `busk run <copy> --values examples/phase1-values.json --console` prints the route line
   and the golden frame line, and no errors.
2. An sACN viewer (sACNView, QLC+) shows universe 1 from "Busk Console" with the show's CID
   and priority 100, carrying the golden values.
3. Wireshark (`udp.port == 5568`) shows 4 packets in about 70 ms, then a keep-alive about
   every 0.91 s, identical apart from consecutive sequence numbers. Wireshark decodes the
   E1.31 layers only with *Preferences → Protocols → ACN → Streaming DMX* enabled
   (`tshark -o acn.dmx_enable:TRUE -d udp.port==5568,acn`).
4. The looks: MH-X25 #1 full, red, gobo 3, pan 90° / tilt −45°; MH-X25 #2 pan mirrored,
   strobing at about 5 Hz (an estimate; time it on slow-motion video); ML-56 orange at 80 %
   with white off; the PiX's 12 cells alternating red and blue.
5. Ctrl+C: the node releases at once (Stream_Terminated). `kill -9` instead: it holds for
   about 2.5 s, then applies its data-loss behaviour. Unplugging the cable for a few
   seconds: the look is back within a second of plugging it in.

Record any difference from the chart-derived expectations in the profile, its golden and
its `notes` (a transcription error) or in the transcription notes above (an estimate).

**Verified without hardware** (the dev machine's wired interface had no carrier, and no
packet was sent onto the Wi-Fi LAN):

* Step 1's spike: `IP_MULTICAST_IF` with a Linux `struct ip_mreqn` (by interface index)
  and with an `in_addr` both work, and a socket that joined `239.255.0.1` on that
  interface receives the packet. No fallback was needed.
* A rehearsal of checks 1–3 and 5 over loopback (the demo with `iface: "lo"`, a listener
  joined on `lo`, port 5568): packets at 0, 23, 46 and 68 ms, keep-alives at 977 ms and
  1 886 ms, then 3 Stream_Terminated packets at Ctrl+C. Repeats and keep-alives differ
  from the first packet only in byte 111 (sequence), terminations only in bytes 111–112.
  Wireshark's dissector decodes every field and flags nothing.
* The E1.31 constants of plan decisions 4–5 (3 packets before suppression, a keep-alive
  every 800–1000 ms, 3 Stream_Terminated packets, the 2.5 s timeout) match the secondary
  sources checked and common sACN implementations. The standard's own text was not at
  hand; see *Still open* below.

## Spec gaps

Resolved by the Phase 1 plan (the spec should adopt or amend these): how `invert` works
with capabilities and how §13.1's pan/tilt formula relates to them; the orientation order
and which offset applies after a swap; `invSquare` and whether the curve applies to
virtual intensity; the rounding rule; zero-span capabilities; duplicate option ids and
which functions are shutter options; per-element intensity strategy; built-in emitter
meanings; zoom's midpoint; Appendix A's closed shutter.

Still open:

* **Colour → colour wheel**: wheel-only fixtures accept only `colorWheel` for now; the
  precedence between a controlled `color` and `colorWheel` must be decided. Phase 1
  deferred it to Phase 2, but the Phase 2 plan does not schedule it, so a global colour
  preset does nothing on a wheel-only fixture yet.
* **Indexed gobo rotation** has no attribute; **strobe units** are estimates on many
  charts; **output gamma** has no profile field.
* **Single-emitter colour elements** (UV-only, white-only) and **pan/tilt-only fixtures
  with no dimmer** are rejected by the colour-system and intensity-strategy rules; they
  need their own rules.
* **`elementPatch`** is still unsupported (proposal in phase-1-plan §9); **`control`**
  needs its own path for lamp-on / reset commands (Phases 6–7).

Resolved by the Phase 1.5 plan: E1.31's transmission rules behind §14.1's "send on change,
otherwise resend periodically" (three packets before suppression, a keep-alive every
800–1000 ms); how routes sharing an sACN universe interact (they share its sequence, and
two show universes on one sACN universe are an error); a synchronous `OutputDriver` that
takes `bytes` and counts packets and errors (§14.5); the console as a `--console` sink, not
a route protocol (phase-0-plan §8); sACN termination moved from Phase 6 to here.

Still open after Phase 1.5:

* **`holdLastFrameOnEngineStall: false`** is undefined: after how long without a new frame
  is the engine stalled, and what is sent then (the base image, zeros, a termination)?
  Decide with the Phase 7 watchdog. Until then the last frame is always held, whatever the
  setting says.
* **`MulticastDestination.iface`**: names are platform-specific (`ip_mreqn` is Linux); an
  IPv4 address works everywhere. The schema could say which forms it accepts, and whether
  an empty string means "the OS default route" (now it is an unknown interface).
* **No TTL or slot-count fields**: TTL is 1 and every packet carries 512 slots. Routed
  lighting networks or §14.2's "fewer slots" would need fields.
* **Receivers that misbehave under suppression** (expecting a continuous stream): record
  the model if the hardware checklist finds one.
* **Check the E1.31 constants against the standard's text** (ANSI E1.31-2018 §6.2.6 and
  §6.6): the termination count and the keep-alive window come from secondary sources.

Resolved by the Phase 2 plan (§9 there; the spec should adopt or amend these):
`threshold` mode (a button latches LTP at once, a fader on its upward crossing, until
release); `followFader` with fades (`envelope × fader`); `priorityBoost` is added to the
band; a flash is a separate source with its own `seq` that never applies exclusivity;
release timing (`releaseTime` or the command's `time`, every family, from the current
weight); GO on an active single-cue list (re-assert, or release with `releaseAtEnd`);
`TOGGLE_PLAYBACK` for stateless bindings and a momentary blackout binding; initial levels
(faders 0, masters at `initialLevel` or 1); spreads (`center`, `edges`, `n = 1`, members
without the attribute); duplicate entries (last wins) and duplicate preset values (an
error); clamping at compile time; several grand masters multiply; MIDI channels are 1–16.
Two Phase 1 questions close with it: **`NaN` extras** snap at half presence instead of
interpolating, and **lanes are finite** (cue values are validated finite and clamped, levels
reject `NaN`, the LTP lerp only runs on finite lanes).

Still open after Phase 2:

* **Who owns the current page** (§15.2 has `PAGE` as an engine command, §4.1 resolves
  page-relative bindings before the bus): recommended for Phase 6, commands carry the
  page-relative slot and the engine resolves it. Phase 2 always uses the first page.
* **Latching blackout** and LED feedback (Phase 6); **soft takeover** (Phase 6).
* **`autoStart`/`autoRelease`** for `rate`, `size` and `crossfade` faders (Phases 4–5).
* **Element 0 vs "whole fixture"** on multi-element fixtures (§5.7 vs §5.5): element 0 is
  not fanned out to cells; decide before pixel effects (Phase 5).
* **Unassigned in the roadmap:** `swop` (recommended Phase 3 or 6), group and fade-time
  masters (Phase 5), `RELEASE_ALL` / `OUTPUT_DISABLE` (Phase 3), the event log (Phase 3).

Resolved by the Phase 3 plan (§9 there; the spec should adopt or amend these): the
programmer lives in the session, not in `EngineRuntime`, and reaches the engine as
programmer frames; its history is the unified undo timeline; `RECORD_CUE.merge` is
optional (absent = create), `RECORD_PRESET` gains `merge`, `RECORD_GROUP`, `SELECT_PLAYBACK`,
`ADD`/`SET`/`DELETE`, `BATCH`, `UNDO`/`REDO` join §15.2; preset pools record families
(`shutter` with `beam`, `control` never); preset merge across scopes removes shadowing
narrower entries of programmer targets; a cue merge splits a partly overridden group
entry into an explicit list; programmer spreads are stored per target (and recorded as
`perTarget`); new cues get 0 s `linear` timing; incremental recompile by object identity.

Still open after Phase 3:

* **sACN CID per installation or per show** (§5.16 says installation, the show stores
  it): `busk new` copies the installation's CID, but a show copied to another console
  still carries the first one. Suggestion: output uses the installation CID and the show
  field becomes an explicit override.
* **Whole fixture vs element 0** (§5.7 vs §5.5): the console's `fixture N` means every
  element, a `TargetRef` exactly its own element; decide with `elementPatch`.
* **Recording into tracking lists**: Phase 3 stores every value; whether values equal to
  the tracked state are stored is Phase 4's call.
* **Live swap snaps** values to their new targets; §6.4's "re-target, don't jump" needs
  the Phase 4 fade engine, as does the programmer's `fadeTime`.
* **Edits stall a big rig's engine** in one CPython process (the GIL; see the benchmark):
  an input for Phase 7's process split.
* **Highlight** (Phase 7, with park, which §12 orders after blackout), cascading deletes,
  persisted undo history and the event log (§15.5) are not scheduled yet; envelopes are
  JSON, so the log can be an append-only file.
* From Phase 2: who owns the current page (Phase 6), latching blackout and feedback
  (Phase 6), `autoStart`/`autoRelease` for other faders (Phases 4–5), `swop`,
  `RELEASE_ALL` / `OUTPUT_DISABLE`, group and fade-time masters.

Phase 4 deviates from the spec on purpose (§9 of its plan; the spec should adopt these):
**sequence numbers are per slot** (a GO makes the playback newest only on the slots it
changes; automatic advances and edits take no number), so tracking does not take colour
away from a bump on every GO; **unchanged slots keep their running fade** on a GO, where
§9.1 restarts every slot; a cue's **own values win over its own `releases`**; there is
**no `dt`**: positions are functions of time rebased at events, which meets §9.4 and
§10.1's "accumulated phase" without integrating; **due events fire before commands**, at
their exact times, so §20's "±1 tick" becomes exact; §5.18's per-slot `ContributionState`,
`CueTransition` and `chasePhase` are stored as arrays; `SET_BPM` and `PROGRAMMER_FADE` are
new commands; `crossfade` faders and `goto` buttons move to Phase 6.

Resolved by the Phase 4 plan (to fold back into the spec): the formulas of `easeIn`,
`easeOut`, `snapStart`, `snapEnd` and Bézier (control values 0..1); which timing a leaving
slot, a tracked slot reached by GOTO and a BACK use (the destination cue's); "rising"
compares effective intensities; a per-entry `fade` covers in and out; GO, BACK and GOTO on
idle and releasing playbacks, at the first and last cue, and onto the current cue;
auto-GOs are scheduled after forward moves only, and "completes" means the end of the
fades the transition started; chases ignore cue timing and triggers except the curve,
always loop, and align on activation, taps and rate changes; a speed master's level picks
a `multiplierSteps` entry, the tap algorithm's numbers (8 taps, ±25 % of the median, a 2-s
reset, the nearest beat), beats counted from the first tick; `rate` faders rest at 0.5 and
are quantised on BPM chases; live edits fade with the cue's timing and keep the stack
order, and a deleted current cue falls back to the next number; recording into a tracking
list stores changes only; selecting a playback uses its current cue's tracked targets.

Still open after Phase 4:

* **`crossfade` fader semantics** (which end it rests at, a GO while it is mid-travel,
  takeover) and **`goto` buttons** (a cue-number entry): Phase 6, with soft takeover.
* **Bar alignment**: chases align to beats, not bars, so a step every 4 beats starts on
  *a* beat.
* **External tempo**: MIDI clock, Ableton Link.
* **A fade-time master** would scale or replace transition durations at retarget (Phase 5,
  with the other masters).
* **Colour-wheel hysteresis** waits for colour → wheel matching.
* **Retarget cost**: a retarget rebuilds every lane of a playback, so 60 GOs in one tick
  take about two ticks (see *Benchmark*); retargeting only the changed lanes in place is
  the fix if real shows need it.
* Console rough edges: `list bindings` names master and tap actions by master id, and
  `list cues` of a chase prints its cues' (ignored) timing instead of the chase settings.
* The open items of Phases 2–3 above.

Phase 5 deviates from the spec on purpose (§9 of its plan; the spec should adopt these):
there is **no accumulated phase**: §10.1's `phase += rate·dt` becomes a position rebased at
events, and a tap **nudges** a BPM effect back onto the grid over one beat where a chase
steps; **suppression is continuous**: a relative contribution is scaled by `1 − A`, the
presence of higher bands, of which §7.5's rule (suspended only at weight exactly 1) is the
case `A = 1`, so an override fading in over an effect no longer ends with a jump;
**`sizeEnvelope` is split** into an entering fade (`sizeFadeIn`, else the cue's in timing)
and the playback's release envelope, so §10.4's "1 → 0 over the release time" is not
applied twice; **dynamics scale an absolute layer's presence**, since §10.4 defines
"effective size" only for `add` and `multiply`; **effects layer over their cue's values**,
ordered by sequence numbers, and win ties; an edited or re-cued instance **cross-fades its
versions** on its running clock; **`size` faders start at 0** and honour
`autoStart`/`autoRelease`; phase spread is compiled in `compiler/`, not §21's
`engine/phase_spread.py`; `ADD_EFFECT` and `REMOVE_EFFECT` are new commands.

Resolved by the Phase 5 plan (to fold back into the spec): `pulse`'s parameters as
fractions of a cycle, `random` as a hash per member and cycle (smoothstep for `smooth`),
`curve` piecewise-linear and periodic; `reverse` runs the phase backwards, `bounce` folds
it; the wing size, mirrored odd wings, `M` as the number of positions, and members without
the attribute; `low`/`high` defaults for every scalar absolute layer, the palette position
(a sawtooth through the palette, wrapping) and colour layers deriving their extras;
tracking effects by instance id, with releases and `block`; enter, change and leave
timing, and what "completes" includes; `speedMasterId` on Hz and BPM effects, size
masters, group masters as a product before the grand master; flash and `temp` play effects
only while main is idle; programmer effects at band 100, and how `RECORD_CUE` records
effects (filter, merge and remove by id, group references, tracking). It closes three
earlier questions: **element 0 vs whole fixture** for effects (a target is exactly its
element), `autoStart`/`autoRelease` for `size` faders, and group masters.

Still open after Phase 5:

* **A static → effect hand-over inside one playback dips.** When a GO swaps a playback's
  static value on a slot for an effect, with no value tracking under it, the value fades
  out while the effect fades in and the slot passes partly through what is below. Effects
  over tracked values (the usual case) do not dip. The fix would be a hand-over at
  retarget: the effect starts from the value's current state at full presence.
* **The fade-time master** (plan decision 18): scaling every transition or replacing cue
  times while the knob is up are both plausible and need operator input; Phase 6 is the
  natural place. It stays in the limitation report.
* **Bar alignment**, for effects as for chases: an effect cycling every 4 beats starts on
  *a* beat. **GOTO and phase**: an Hz effect reached by GOTO starts its clock at the
  GOTO, so its phase differs from stepping.
* **Flash → main hand-over**: when main starts under a held flash, a BPM effect continues
  the flash's phase only for multipliers ≥ 1; below that, and for `random` and `bounce`
  (which depend on the whole cycle count), it may jump. A chase that stalls for more than
  a lap of steps can also start an effect's clock at a different time.
* **Strobe-like intensity effects** (a fast `square` or `pulse` on intensity) escape the
  strobe-rate cap (§12, Phase 7), which should bound intensity effects' frequency too.
* **Matrix effects** on a group's 2-D `layout`, and discrete effects (a gobo or colour-wheel
  cycle).
* `ADD_EFFECT` reports validation errors but not compile warnings (an effect that drives
  nothing on the selection is added silently); `info` does not count programmer effects.
* The open items of Phases 2–4 above, including the Phase 4 GO-burst and edit-overrun
  misses.

Phase 6 deviates from the spec on purpose (§9 of its plan; the spec should adopt these):
**the engine resolves page-relative input**: bindings send `SET_FADER {slot}` and
`PLAYBACK_BUTTON {slot}` rather than resolving pages before the bus as §4.1 draws, and there
is one global page; **soft takeover and held buttons are engine state**, keyed by a new
`CommandOrigin.control`; **new commands**: `PAGE` (§15.2 names it without fields),
`PLAYBACK_BUTTON`, `SET_FADER` by slot, `BLACKOUT` without `on` toggling; **swop removes
intensity presence** instead of setting `intensityScale = 0`, because of §7.4's override
bands; **crossfade faders** never reverse and alternate rest ends (§8.2 says only "fader
position drives `manualProgress`"); **remotes get show summaries, not JSON patches** (§16
"snapshots + patches"): a summary is small and always consistent; **the web API takes
performance commands only** (§23's single writer), where the console package's docs
expected `Session.submit` whole; **Art-Net broadcast routes unicast to discovered nodes**
(§14.3 "prefer unicast"), falling back to broadcast; **DMX-USB sends all 512 slots** and
leaves the frame rate to the widget (§14.2's "fewer slots" is not done); and optional
schema additions: `Playback.gotoCue`, `BlackoutAction.momentary`,
`SurfaceMatch.feedbackPort` and the `midiClock` input. Two behaviours change for existing
shows: blackout bindings latch, and page-relative bindings follow the current page (a show
with one page behaves as before). `schemaVersion` stays 1.

Resolved by the Phase 6 plan (to fold back into the spec): who owns the page, `delta`
stopping at the ends, the page after a live edit deletes it, the page kept with the
session; the §8.1 button table as engine behaviour, `goto` buttons' target, held flashes
across page changes, latching vs momentary blackout; soft takeover's rule (crossing or
0.02, detached by any other source, faders and masters alike); feedback values per action
and kind, the echo hold, beat LEDs; `SurfaceMatch` per kind (`deviceName` for MIDI;
`port`, `host` and `feedbackPort` for OSC; `port` and `host` as the bind address for web);
OSC values (the first argument, clamped; `T`/`F`; no arguments as a press and a release);
MIDI clock as one tap per beat; fade-time masters (replace times while up, `10 s × level²`,
the largest master, which transitions they cover, initial level 0); Art-Net sequences and
keep-alive, sACN discovery interfaces and timing, the Enttec parameters. It closes these
earlier questions: **who owns the current page**, **latching blackout and feedback**,
**soft takeover**, **`swop`**, **`crossfade` faders and `goto` buttons**, **the fade-time
master** and **external tempo** (MIDI clock; Ableton Link stays open).

Still open after Phase 6:

* **Pages per surface**: two controllers on different pages. The engine would keep a page
  per surface, and `PAGE` would gain a surface.
* **The blind preview resolve** (§7.6), a programming UI on the web API (programmer and
  show edits, multi-user rules, §23) and a template editor. The phone cannot show blind
  values or effects yet.
* **HID and `internal` surfaces, `hw` inputs**; display feedback on MIDI surfaces
  (device-specific sysex); feedback for `command` actions; feedback to a non-OSC address on
  an OSC surface is not sent and not reported by validation.
* **Ableton Link.** MIDI clock covers external sync for now.
* **Reversing a manual crossfade**, and several goto cues per playback.
* **OSC address patterns**; TLS and rate limits for the web API. A client can still flood
  the bus; Phase 7's process split is the place to bound it.
* **ArtSync and sACN synchronisation**; `enttecOpen`; DMX-USB sending fewer slots; sACN
  discovery for unicast-only shows. Two enabled DMX-USB routes on one serial device are not
  rejected by validation (a rule like the sACN universe one would do).
* **Reconnect** for every route and for MIDI devices (hot-plug): this phase covers only
  DMX-USB, and only after a send failure, not a device missing at start-up.
* **Interface lookups** (`netif`) are Linux-only, like multicast by interface name.
* **Surface load on a §19-sized rig** misses the soft 1 % overrun target (1.6–2.8 %, see
  the benchmark above), on top of the GO-burst and edit-overrun misses of Phase 4.
* The open items of Phases 2–5 above.

Phase 7 deviates from the spec on purpose (§9 of its plan; the spec should adopt these):
**three processes, with the output in the root**, where §16 draws output threads inside the
engine process: the only layout in which §18's "hold the last frame while the watchdog
restarts the engine" holds through a crash; **internal links are pickled**, between the
root's own children over socket pairs (§16 says "IPC / WebSocket"), while the web API stays
JSON; **compiled shows cross with structural sharing**, which §6.4's atomic swap assumed was
free; **a restarted engine restores the look from the last snapshot**, beyond §18's
"resumes from autosave", which would blank the stage; **highlight comes before blackout**,
so blackout, park and limits win, where §12 orders it last, and it is logical (intensity,
shutter, colour) plus `highlightDmx` for other channels; **blackout darkens a parked
intensity**, the reading of §12's "including blackout for non-intensity slots"; **the strobe
cap is off unless the show sets it**, and it also bounds intensity effects;
**`holdLastFrameOnEngineStall: false` turns intensity off and holds everything else**;
**`OUTPUT off` sends nothing**, and Art-Net nodes and DMX-USB widgets keep their last
frame; **the event log is written by the root, with show edits as patch ops**, where §15.5
logs envelopes only, which cannot replay edits whose ids were generated. Additions: the
optional `Show.safety`; the commands `HIGHLIGHT` (§15.2 names it), `RELEASE_ALL` and
`OUTPUT` (§18 names `OUTPUT_DISABLE`; one command with `on` goes both ways). What changes
for existing shows: `limits` and `park` are enforced, `holdLastFrameOnEngineStall: false`
darkens a stalled output, and `busk run` starts three processes. `schemaVersion` stays 1.

Resolved by the Phase 7 plan (to fold back into the spec): the watchdog's thresholds
(stalled after 1 s, killed after 3 s, 15 s for a first frame) and its crash-loop rules (no
restore within 10 s of the last, giving up after 3 restarts in 60 s); what a restart
restores and what it does not; commands during a restart (queued, at most 1024); console
crashes: the exit codes (0, 1, 70), the show stamp, adopting the running engine; the safety
stage's full order, park and highlight against blackout, limits in logical degrees and over
every element; flashes per cycle per waveform and BPM capping on the beat grid; what a
stalled output sends and what output off does per protocol; reconnect timings (a retry
every 2 s, reopening after 1 s of failure), hot-plug polling every 2 s, the rate-limit
numbers and the drain bound (512 items); the OFL and GDTF mapping tables and modelling
rules, import revisions, profile updates; what an output drop is, and the soak's criteria.
It closes these earlier questions: **`holdLastFrameOnEngineStall: false`** (Phase 1.5),
**highlight** (Phase 3), the **strobe-rate cap**, intensity effects included (Phase 5),
**reconnect** for every route and MIDI device and **rate limits** on remote commands
(Phase 6), and the **edit-overrun and surface-load misses** (Phases 3–6).

Still open after Phase 7:

* **The programming UI**: the blind preview resolve (§7.6), programmer and show edits over
  the API, multi-user rules (§23), a template editor.
* **Pages per surface**, if two operators share one show.
* **A console that hangs** without exiting is not detected, and the root has no watchdog
  of its own: `kill -9` of the root ends the output, and receivers time out.
* **A command written to the link in the milliseconds before the console notices that the
  engine died** is lost with it: commands have no acknowledgements (replaying could apply a
  `go` twice). Commands made once the console knows (`engine restarting`) are queued.
* **A restarted console whose engine restarts at the same moment** meets a fresh engine: it
  restores nothing and does not re-apply its recovered masters (it adopts). Programmer
  values on a fixture that the revert to the last autosave removed stay in the programmer,
  listed `(gone)`, as in Phase 3.
* **Strobe-like chases** are not capped, nor are fast operator flashes.
* **GDTF** mode masters, DMX breaks after the first, virtual channels and curves (they need
  `elementPatch`); assets such as gobo images in the `.show` ZIP. Only synthetic GDTF files
  were tested.
* **Restoring fades and Hz effect phases exactly** after an engine restart, and held
  flashes, swops and soft-takeover attachments.
* **Single-emitter colour elements** and **colour → colour wheel** (Phase 1–2 gaps), which
  the importers work around.
* **Running the engine on another machine**, and a backup console (sACN priority already
  allows one).
* From Phase 6: Ableton Link, ArtSync and sACN synchronisation, `enttecOpen`, DMX-USB with
  fewer slots, OSC address patterns, TLS for the web remote, display feedback on MIDI, HID
  surfaces, Linux-only interface lookups.
* **The 60-GO burst** (17.5 ms, the engine's own cost; Phase 4).

## Programming checklist (Phase 3)

The manual check of phase-3-plan step 15 needs the Phase 2 setup (a nanoKONTROL2 and an
sACN receiver, the route's interface set with `--iface`):

1. `busk new club.show --title "Club Night"`, then `busk run club.show --script
   examples/phase3-build.busk --iface <your interface>`: the script's lines, `saved
   club.show`, the route line, the matched MIDI port, then the prompt.
2. Busk as in the [Phase 2 checklist](#busking-checklist-phase-2): faders 1–8, S/M/R
   buttons, knob 8, ■. Everything behaves as in the hand-written demo (the washes and the
   PiX take the place of the RGB pars).
3. `blind on`, `sel group 1`, `set color 0 0.3 1`, `record preset color 1 merge` with
   Blue up: the stage changes live, playback 3 is untouched; `undo` brings the original
   blue back.
4. `quit` and save; `busk validate club.show` reports 0 errors and 0 warnings, and `unzip
   -p club.show show.json` shows group and preset references in the cues.
5. Start it again, set values, `kill -9` it, start it again: `recovered programmer with …`.
6. The run ends with `0 overruns`.

**Rehearsed without hardware**: steps 1 and 3–5 behave as written. Step 3 ran through a
pseudo-terminal, with the script's route sending unicast to 127.0.0.1 and an sACN listener
on port 5568: with Warm and Blue up the heads were RGBW `0 0 255 0` (the first wash `0 0
204 0`); blind programming left them; `record preset color 1 merge` turned them to `0 76
255 0` live (and the washes, since the preset is global, to `0 61 204 0`); `undo` restored
`0 0 255 0`. The run ended with 0 overruns. Step 5 is `test_recovery.py`. Steps 2 and 6
need the controller and the rig.

## Song checklist (Phase 4)

The manual check of phase-4-plan step 20 needs the Phase 3 setup (a nanoKONTROL2 and an
sACN rig, the route's interface set with `--iface`):

1. `busk new club.show --title "Club Night"`, `busk run club.show --script
   examples/phase3-build.busk --duration 1`, then `busk run club.show --script
   examples/phase4-song.busk --iface <your interface>`. `Ignored in Phase 5:` (`Ignored in
   Phase 4:` then) lists only what the show uses that waits for later phases (limits, soft
   pickup, …); with the Phase 3 build it lists nothing.
2. Knob 1 up: the Intro eases in over 3 s, the washes going blue. ▶: Verse, the heads
   coming in warm while they swing to the audience more slowly (4 s). Wait 8 s: the Pre
   fires by itself, the bar rising fast in amber and the washes dimming slowly. ▶: Chorus,
   everything white. Four seconds after it lands the Outro starts: the heads dim and drift
   back to centre over 6 s.
3. ◀◀ during the Outro: back to the Chorus (0.5 s), and it stays there.
4. With the Verse up, bring up Blue (fader 3): the heads turn blue. ▶ (Pre): they stay
   blue, because the Pre does not change their colour and tracked slots don't steal. ▶
   (Chorus) sets every colour: white.
5. Knob 2 up: the chase bounces across the washes in red, one step per beat (120 BPM).
   Tap "cycle" in time with music: it locks within two taps. Knob 3: ×½, ×2, … staying on
   the beat. `status` shows the tempo and multiplier.
6. ●: the song releases over 3 s.
7. `fade 2`, `sel group 1`, `set intensity 100%`: the heads fade up over 2 s. `clear`: they
   fade back.
8. The run ends with 0 overruns.

**Rehearsed without hardware**: step 1 runs as written and `busk validate club.show`
reports 0 errors and 0 warnings. The timings of steps 2, 3, 5 and 6 are the checkpoints
`test_song_stack.py` replays on a fake clock (from the saved show, frame for frame), and
step 4 was checked the same way: heads warm `(1, 0.75, 0.45)` in the Verse, blue with Blue
up, still blue after the Pre's GO, white after the Chorus's. Step 7 is covered by
`test_engine_programmer.py`. Watching it on a rig, with the controller in hand, is left.

## Effects checklist (Phase 5)

The manual check of phase-5-plan step 18 needs the Phase 3 setup (a nanoKONTROL2 and an
sACN rig, the route's interface set with `--iface`):

1. `busk new club.show --title "Club Night"`, then `busk run club.show --script
   examples/phase3-build.busk --duration 1`, `busk run club.show --script
   examples/phase4-song.busk --duration 1` and `busk run club.show --script
   examples/phase5-effects.busk --iface <your interface>`. `Ignored in Phase 5:` lists
   nothing for this show.
2. Fader 1 up (Warm), fader 6 up (Audience). Knob 4 up: the heads circle around the
   audience position, a circle every two beats, MH 2 a quarter turn behind MH 1. Track ◀
   toggles the circle.
3. Knob 5 up: the washes pulse in a wave that travels across the four of them, once per
   beat.
4. Tap "cycle" in time with music: the circle and the pulse follow within a beat, without
   a jump.
5. Knob 7: both shrink and grow together (the "FX" size master). `master "Wash level"
   50%`: the washes at half; back to 100 %: unchanged.
6. Fader 1 down to 0 (Warm releases), knob 6 up: the bar shows a mirrored wave from both
   ends to the centre and back. While Warm is up, only the crests rise above it (HTP).
7. `sel fixture 101`, `set pan 0`: MH 1 stops moving across, still nodding in tilt.
   `clear`: it circles again.
8. Knob 1 up, then ▶ to the Chorus: the bar runs the colour cycle over its white. Four
   seconds after the Chorus lands, the Outro starts and the cycle carries on without
   restarting. ● releases the song: the cycle fades out over 3 s, still moving.
9. The run ends with 0 overruns.

**Rehearsed without hardware**: §8 of the plan runs as written on a fresh show (no
interface `eth0` on the dev machine, so no route opened): the three scripts succeed, there
is no `Ignored in Phase 5:` block, `list effects` lists Circle, Pulse, Wave and Rainbow
embedded from the library, four taps typed from a shell script moved Speed 1 to 127.7 BPM,
`list masters` showed FX at 50 % and Wash level at 100 %, the run ended with 0 overruns
and `busk validate club.show` reports 0 errors and 0 warnings. Steps 2–8 are the
checkpoints `test_effects_show.py` replays on a fake clock from the saved show: the
circle's and pulse's positions and levels at hand-computed times, FX and Wash level, the
taps, the bar's wave alone and under Warm, the programmer's pan, and the colour cycle
through the Outro and the release. Watching it on a rig, with the controller in hand, is
left.

## Surfaces checklist (Phase 6)

The manual check of phase-6-plan step 20 needs the Phase 3 setup (a nanoKONTROL2 and an
sACN rig, the route's interface set with `--iface`), a phone on the same network, and the
nanoKONTROL2's LED mode set to **External** with the KORG KONTROL Editor (in the factory
Internal mode the buttons light only while pressed):

1. `busk new club.show --title "Club Night"`, then `busk run club.show --script
   examples/phase3-build.busk --duration 1`, the same with `phase4-song.busk` and
   `phase5-effects.busk`, and `busk run club.show --script examples/phase6-surfaces.busk
   --iface <your interface>`. There is no `Ignored in Phase 7:` block. Open the printed
   `Web s-…` address on the phone: page 1 "Main" with its strips.
2. Fader 1 from the bottom to the top: Warm comes up. S1 and R1 light.
3. Marker ▶: the phone shows "Washes" and the S1 LED goes out. Move fader 1 down a little:
   nothing happens. Pull it to the bottom and up again: Wash Blue rises from 0, without a
   jump.
4. On the phone, drag Wash Blue to about a third. Move fader 1: nothing until it passes
   the phone's level, then it follows.
5. Hold M2: only the red washes are lit, and M2 lights. Release it: everything as before.
6. Fader 8 up slowly: the bar crossfades into blue as you move. Down slowly: into red.
   Stop halfway: the bar holds there.
7. ■: blackout stays on and the stop LED lights. ■ again: back.
8. Marker ◀ to page 1. On the phone, raise "Fade" to the middle and tap the song's `GOTO 4
   Chorus`: the Chorus fades in over about 2.5 s while Warm fades out.
9. Cycle LED: it flashes on the beat. Tap in time, or send MIDI clock from a DAW bound with
   `bind "<surface>" clock tap`: it follows.
10. Close the phone's browser while holding a FLASH on it: the flash goes off.
11. With hardware at hand: an Art-Net node shows up (`Art-Net: node …`) and its universe
    lights; an Enttec or DMXking interface outputs, and pulling and replugging its cable
    resumes output within a second.
12. The run ends with 0 overruns.

**Rehearsed without hardware**: §8 of the plan runs as written on a fresh show (no
interface `eth0` on the dev machine, so no route opened, and no nanoKONTROL2): the four
scripts succeed with no `Ignored in Phase 6:` block, the web surface prints its address,
`list pages` marks page 1, `page 2` turns the status line to `P2 Washes`, `busk validate`
reports 0 errors and 0 warnings, and a 5 s run of the saved show with every surface open
ends with 0 overruns (max tick 1.4 ms). Steps 2–8 and 10 are the checkpoints
`test_surfaces_show.py` replays on a fake clock from the saved show, with the controller's
CCs going through the binding resolver and the phone through the web API (step 10 also
over a real WebSocket); step 9's beat LED and MIDI clock are `test_feedback.py` and
`test_midi.py` (48 clocks through a virtual ALSA port), step 11 is `test_artnet_discovery.py`
(a fake node on localhost) and `test_dmxusb.py` (a pseudo-terminal unplugged and
replugged). The phone page was driven in headless Chromium: it builds its strips, a held
FLASH shows on its strip, a drag sends `SET_FADER` and shows 50 %, and BO latches.
Watching it on a rig, with the controller and a real phone in hand, is left.

## Hardening checklist (Phase 7)

The manual checks of phase-7-plan step 20. The soak needs a machine that will not sleep;
the rest needs the Phase 3 setup (a nanoKONTROL2 with its LEDs in External mode, an sACN
rig, the route's interface set with `--iface`), a phone on the same network, and for item 2
TupperDMX-Simul.

1. **The 24-hour soak.** With suspend disabled, `/dev/snd/seq` present and UDP 5568 and
   6454 free, run `uv run python bench/soak.py --hours 24 --report soak-24h.json`. The
   summary says **pass**: 0 output drops, every kill recovered, memory within bounds. Keep
   the report and, on a failure, the `soak-24h/` directory next to it (its event logs
   replay what the engine saw).
2. **TupperDMX on imported profiles.** Start TupperDMX-Simul first (it holds port 6454),
   then:

   ```
   busk import ofl ~/Documents/TupperDMX/demo.show/fixtures/*.json --manufacturer TupperDMX --out /tmp/tdmx
   busk new /tmp/tdmx/tupper.show --title "TupperDMX demo"
   busk run /tmp/tdmx/tupper.show --library /tmp/tdmx --script examples/tupperdmx/build-ofl.busk
   ```

   Play the page: the simulator shows the same looks as with the hand-transcribed build
   (`examples/tupperdmx/build.busk`), except the smoke machine's dead band (intensity above
   0 starts at DMX 8).
3. **The safety show on the Phase 3 rig**, after the five scripts (`phase3-build` …
   `phase7-safety`, as in the [Usage](#usage) example, with `--iface`):
   - Fader 1 up: wash 4 stays dark and wash 3 red, whatever is played. The bar never goes
     above half.
   - The song's Chorus: the heads tilt no higher than 10°. The Circle flattens at the top.
   - Page 2, fader 5 (Strobe): the heads strobe at about 3 Hz, not 10. Fader 6 (Fast
     pulse): the washes pulse about 3 times a second.
   - `sel fixture 102`, `highlight on`: MH 2 lights white and full at any grand master.
     Blackout still darkens it. `highlight off`.
4. `info` gives the engine's pid. `kill -9` it while a look and the Circle run: the stage
   freezes and does not go dark; within about 3 s the look is back and the Circle runs
   again, on the beat; the faders work again after crossing their levels.
5. `kill -9` the console's pid: the show runs on, a new prompt appears within seconds, and
   the phone reconnects by itself.
6. Unplug the nanoKONTROL2 for 5 s and plug it back in: `unplugged`, then `connected`. The
   LEDs show the state again.
7. Unplug the network cable of the sACN route for 10 s: `send failed`, then `sending
   again`. The rig follows.
8. Marker SET (`release all`): every playback releases. `output off` (confirm with `y`):
   the rig's receivers let go. `output on`: back.
9. A run with `--stats stats.jsonl` ends with 0 late output cycles in its last line and
   the restarts you caused.

**Rehearsed without hardware** (2026-10-16, on the dev machine: no `eth0`, so no route
opened, and no nanoKONTROL2): plan §8 runs as written on a fresh show. The five scripts
succeed with no `Ignored in Phase 7:` block, `busk validate` reports 0 errors and 0
warnings, and a run in processes with `--stats` names three pids in `info`; after `kill -9`
of the engine it prints `engine: restarted (killed by signal 9)` and `engine back: …`,
`info` shows a new engine pid and `restarts: engine 1`, `list park` lists 204 and 203, and
the run ends with 0 overruns and `1 restart`. `busk import ofl` imports the five TupperDMX
files and `busk replay` replays the run's logs. Items 3 and 8 are the checkpoints
`test_safety_show.py` replays from the saved show; item 4 is `test_watchdog.py` against an
sACN receiver, item 5 `test_console_restart.py` with a WebSocket client as the phone, item
6 `test_hotplug.py` (a virtual ALSA port created and destroyed), item 7 `test_reconnect.py`,
and item 1 ran for 1 hour (pass; see the [benchmark](#development)). Watching it on a rig,
and the 24 hours, are left.

## Next

The spec's §22 roadmap is complete. Run the Phase 7
[hardening checklist](#hardening-checklist-phase-7), the 24-hour soak first (and the
earlier checklists if they have not been run). What remains is new scope, and a choice:

* **A programming phase**, built on the process split's links: a web programmer
  (selection, values, presets, effects, recording) with the blind preview resolve as a
  second resolve in the engine process, multi-user rules (a single writer or patches,
  §23), and a template editor.
* **Pages per surface**, if two operators share one show.
* **The spec gaps** listed [above](#spec-gaps), notably colour → colour wheel and
  single-emitter colour, which would let the importers map more fixtures as they are, and
  the GDTF parts the import leaves out.
