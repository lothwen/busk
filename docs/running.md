# Running a show

`busk run SHOW` opens the show's output routes and control surfaces (MIDI, OSC, the web
remote), runs the engine and the DMX output, and opens the [console](console.md). This
guide covers what a run does, what it prints, and how it survives crashes.

- [Ways to run](#ways-to-run)
- [Options](#options)
- [What it prints](#what-it-prints)
- [Live edits](#live-edits)
- [Autosave and recovery](#autosave-and-recovery)
- [Stopping](#stopping)
- [Processes and the watchdog](#processes-and-the-watchdog)
- [The event log and replay](#the-event-log-and-replay)
- [Values files](#values-files)

Shows are `.show` files (a ZIP holding `show.json`) or plain `.json`. `busk new PATH
[--title T]` writes an empty, valid show: one grand master, one empty page `Main`, no
routes, and the installation's sACN CID (created once in the state directory). It never
overwrites a file. `busk validate SHOW` prints one line per issue (`error
fixtures[2].patch.address: …`) and a summary; it exits 0 when there are no errors
(warnings are allowed) and 1 when there are.

## Ways to run

```bash
busk run club.show                                   # a prompt on the terminal
busk run club.show --script build.busk               # run a console script first, then the prompt
echo "fader 1 1" | busk run club.show --duration 10  # commands from a pipe
busk run club.show --no-console                      # no commands: busk from the surfaces until Ctrl+C
busk run club.show --duration 2 --console            # print the DMX frames too
```

- **At a terminal** the console is a prompt, with [Tab completion and `?`](console.md#the-prompt).
  Ctrl+C clears a typed line. On an empty line it prints `press Ctrl+C again to quit`, and
  a second Ctrl+C in a row ends the run, so one stray press never stops the output. `quit`,
  Ctrl+D or that second Ctrl+C ends the run and offers to save unsaved edits.
- **From a pipe** the commands are read line by line, and the end of the input quits,
  unless `--duration` is given.
- **`--script FILE`** runs a [console script](console.md#scripts) first and stops at its
  first error, ending the run with exit code 1.
- **`--no-console`** reads no commands and runs until Ctrl+C: the show is played from its
  surfaces only.
- **`--console`** also prints frame lines: the non-zero channels of each universe, 1-based,
  or `all 0`. A universe prints only when its bytes change, so a static look prints once.
  Without `--console` (and at an interactive prompt) no frame lines are printed.

`python -m busk …` works too.

## Options

| Option | |
|---|---|
| `--script FILE` | Run console commands from `FILE` first. |
| `--no-console` | Read no console commands. |
| `--console` | Also print each universe when its bytes change. |
| `--duration SECONDS` | Stop after this many seconds instead of waiting for Ctrl+C or `quit`. |
| `--iface IF` | The interface `route add` uses for new multicast and broadcast routes (default `eth0`; see [Output](output.md#choosing-the-network-interface)). |
| `--library D` | Another directory of fixture profiles (repeatable; see [Fixture profiles](profiles.md#profile-libraries)). |
| `--values FILE` | What uncontrolled slots output ([values files](#values-files)). |
| `--state-dir D` | busk's state directory (default `$XDG_STATE_HOME/busk`). |
| `--no-recover` | Ignore the last run's crash state and start clean. |
| `--threads` | Run the engine and the output as threads of one process: no watchdog, no restarts. |
| `--stats FILE` | Append the processes' statistics to `FILE`, one JSON line per second. |
| `--no-log` | Write no [event log](#the-event-log-and-replay). |

## What it prints

**Before running**, compile warnings go to stderr: a cue value dropped for a target that
does not offer it (a gobo the fixture lacks), a fixture that a cue, effect or park entry
drives but that is not patched. Validation also warns about a fixture whose slowest strobe
is above the show's strobe cap. On stdout, under `Ignored in Phase 7:`, comes every feature
the show uses that busk ignores, one line each with its path (`hid` and `internal`
surfaces, `hw` inputs, display feedback on a MIDI surface, feedback on a `command` action,
…).

**At start-up**, one line per open route and surface:

```
sACN r-…: U1 Stage → universe 1, multicast 239.255.0.1 via eth0, priority 100
MIDI s-…: nanoKONTROL2:nanoKONTROL2 _ CTRL 20:0
Web s-…: http://192.168.1.20:8080/?k=…
busk console: Tab completes, ? shows what comes next, 'help' lists the commands, 'quit' stops.
```

[Output](output.md#route-messages) and [Surfaces](surfaces.md) list the other messages
routes and surfaces print. A route or surface that cannot open is reported and the run
goes on without it (a route keeps trying; see [reconnects](output.md#reconnects)). With no
open route and no `--console`, the run says so on stderr (`no output: …`) and keeps
running.

**The status line.** Whenever the engine's state changes, stdout gets a line like

```
GM 80% | BO off | P1 Main | Speed 1 128 BPM ×2 | Fade 2.5 s | 9 Song on 3 Pre 1.00 · 10 Chase on 1.00 · 8 Panic flash · 18 Manual on → 2 c2 50%
```

that is: the grand master, blackout, `OUT off` while the output is off, the current page,
each speed master's tempo and multiplier, the fade-time master's time when it is up, and
every playback that is active (`on`), releasing (`rel`), flashing (`swop` while a swop
button is held) or has its fader up, with the current cue of a sequence (number and name),
the level of a `master`, `size` or `temp` fader, and a manual crossfade's target cue and
progress. Running effects and chase steps print nothing, so a running chase does not print
a line per step. At an interactive prompt the lines would garble the input, so the
`status` command prints it instead.

**On exit** it prints the tick and command statistics and each route's packet and error
counts (`, N faults` is added if its driver raised):

```
engine: 1601 ticks @ 100 Hz, 0 overruns, max tick 1.194 ms, 20 commands, 0 command errors
sACN r1: 347 packets, 0 errors
```

**Exit codes.** 0 for a normal end. 1 when the show or the values file cannot be loaded or
compiled (the message names the newest backup, if there is one), or a script fails. 70
when the watchdog gave up on the engine or the console ([below](#processes-and-the-watchdog)).

## Live edits

Edits made at the console reach the stage at the next engine tick. A new route opens (its
line is printed), and a removed or changed one sends Stream_Terminated. A new or changed
surface opens; a web surface restarts only when its port or host changes, so renaming it
keeps the phones connected. New bindings and feedback work at once. A running cue that you
re-record or whose preset you edit fades to its new state with the cue's timing.

## Autosave and recovery

While a show runs, it is autosaved 5 s after a burst of edits (every 180 s during a long
one). The programmer (its effects included) and the master levels (grand, speed, group,
size and fade-time), with the programmer's fade time, each speed master's tempo and the
current page, are saved at most once a second. Everything goes under
`$XDG_STATE_HOME/busk/autosave/<show id>/` (or `--state-dir`).

After a crash or `kill -9`, the next `busk run` of the same show restores them:

```
recovered programmer with 4 values, 1 effect (blind, fade 2 s), 4 master levels, 1 tempo, page 2, unsaved edits from …
```

`--no-recover` starts clean. Quitting with unsaved edits keeps them in the newest autosave
and prints its path. Saving keeps the 10 newest backups in `<name>.backups/`.

## Stopping

Ctrl+C with `--no-console`, `quit` at the prompt, or the end of `--duration` closes the
surfaces (MIDI ports, OSC sockets, the web servers, which tell each phone they are going
away) and the feedback, stops the engine, sends the final frame, then sends 3
Stream_Terminated packets per sACN route so receivers release their universes at once.
Art-Net nodes and DMX-USB widgets hold the last frame.

If the `busk run` process itself is killed (`kill -9`), receivers fall back to E1.31's
2.5 s timeout. The engine and the console can be killed without stopping the output
([below](#processes-and-the-watchdog)).

## Processes and the watchdog

`busk run` starts three processes:

- the **root** is the process you start. It sends the output, watches the other two,
  writes the event log and the `--stats` file, and owns `--duration`. It runs no show code;
- the **engine** runs the pipeline in its own session, so terminal signals never reach it;
- the **console** loads and recovers the show and runs the programmer, the prompt or
  script, the surfaces, feedback, the web remote, autosave and the status lines. It owns
  the terminal: Ctrl+C at the prompt keeps its meaning.

They talk over socket pairs the root makes, never over a path or a port. `info` at the
console names their pids and the restarts so far (`processes: root 96567, engine 96595,
console 96597`, `restarts: engine 0, console 0`).

**The watchdog** takes the engine's frames as its heartbeat. After 1 s without a new frame
the engine is *stalled*: the output holds the last frame (`engine: no new frame for 1.0 s;
holding the last frame`), or, when the show's `holdLastFrameOnEngineStall` is false, sends
it with intensity off and everything else held, so heads do not swing home. After 3 s, or
as soon as the engine process exits, the root kills it and starts a new one:

```
engine: restarted (killed by signal 9)
engine back: restored 7 playbacks, 6 master levels, page 2
```

The console sends the new engine the show and the programmer, then **restores the look**
from the last state it saw: every master level, the speed masters' tempos and beat
positions (so BPM chases and effects land back on the grid), blackout, output on or off,
the page, and every active playback at its current cue and fader level. Fades in progress
snap to their target; Hz effect phases, held flashes and soft-takeover attachments are not
restored. Commands sent while the engine is down (a blackout pressed during the restart)
wait in the console (at most 1024) and follow the restore.

A restart within 10 s of a restore skips the restore, in case the restored state is what
crashes the engine. After three restarts within 60 s the watchdog gives up: the output
keeps holding, the status line says `engine failed`, and the run ends with 70.

**Tick errors.** A tick that raises is counted (`tickErrors` in `--stats`) and the engine
goes on; ten in a row end the engine, and the watchdog restarts it.

**A console that crashes** (killed by a signal, or an unexpected exception) is replaced
(`console: restarted (killed by signal 9)`). The new one recovers the show and the
programmer from autosave and **adopts** the running engine's masters, tempos and page
instead of pushing its own; it does not run `--script` or `--values` again. If its
recovered show is the one the engine runs, it sends only the programmer; otherwise edits
made after the last show autosave (at most 5 s) are undone on stage. The output and the
engine never stop meanwhile, and phones reconnect to the new console by themselves. A
console that exits normally (`quit`) or fails to load the show or a script ends the run
with that code. After three restarts within 60 s the root gives the console up, and the
show runs on until Ctrl+C, `SIGTERM` or `--duration`, ending with 70.

**Signals.** The root ignores Ctrl+C while a console lives (the console has its own);
without one (a restart in progress, or given up) Ctrl+C stops the run. `SIGTERM` and
`SIGHUP` to the root are passed to the console, which quits as at the end of a script. An
engine or console whose root vanished exits at once (the console then writes no clean
autosave, so the next run recovers).

**`--stats FILE`** appends one JSON line per second: the engine's pid, state (`running`,
`stalled`, …), restarts, ticks, overruns, longest tick, tick, install and command errors,
longest garbage-collection pause and memory; the console's pid, restarts and memory; the
root's memory, late output cycles and longest output gap; per route, its packets and
errors.

**`--threads`** runs everything as threads of one process. The safety stage, the stall
output, reconnects, rate limits and the event log work there too; the watchdog and the
restarts exist only with processes. It is the default where `socket.send_fds` is missing.

## The event log and replay

Every run writes what the engine applied, when and why, to
`<state dir>/logs/<show id>/<UTC stamp>.log`, one JSON record per line (`info` prints the
path, `--no-log` turns it off). Each connection of a console to an engine starts with the
whole state (the show, the programmer, the `--values` base, whether the engine was fresh);
then come show edits with their labels, programmer changes, performance commands and
restores, each with the engine time at which it was applied. A file rotates past 64 MB,
and the 16 newest are kept.

`busk replay LOG… [--until T] [--frames OUT] [--at T]` rebuilds the run on a fresh engine
and prints each record; `--frames` writes every frame as JSON, and frames rebuilt this way
are byte-identical to the run's.

```bash
busk replay ~/.local/state/busk/logs/show-…/20261016T170328907372Z.log
# 31666.650112  start  'Club Night', fresh engine
# 31666.660170  e      added universe 'Stage'
# …
# replayed 284 record(s) in 21 tick(s), up to t=31666.850168
```

## Values files

A values file (`--values FILE`) sets what **uncontrolled** slots output: every tick starts
from it instead of the attributes' defaults, and playbacks layer on top. It is a JSON list
of park-shaped entries, so it reuses the show schema:

```json
[ { "slot": { "target": { "fixtureId": "fx-mh1", "element": 0 }, "attribute": "pan" }, "value": 90 },
  { "slot": { "target": { "fixtureId": "fx-mh1", "element": 0 }, "attribute": "colorWheel" },
    "value": { "slot": "red" } } ]
```

Later entries override earlier ones for the same slot. Entries are stricter than cue
entries: an attribute the target doesn't have, a discrete `slot` that isn't one of the
channel's options, or a `wheel` that isn't the channel's wheel is an error (with a path
such as `values[3].slot.attribute`), where a cue drops the value for that target with a
warning.
