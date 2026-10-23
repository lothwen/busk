# Benchmarks

Measured on the development machine as each phase finished; [`history.md`](history.md)
explains the phases. The perf gates run with `uv run pytest -m perf -s`, the benches with
the scripts in [`bench/`](../../bench/) ([`development.md`](development.md#commands)).

## The engine and the output

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

**The output readout** (GAP-01, 2026-10-22; measured with the perf suite's helpers, GC
off). Capturing a tick's output on the engine thread (a copy of the frame and the
attribution of every lane) takes **0.01 ms** on the Phase 3 show (18 elements, 90 lanes),
whose tick takes 0.06 ms. On the reference rig (8 192 elements, 37 120 lanes) it takes
0.6 ms median with the 60 looks and 0.9 ms with 20 effects over them: ticks go from 2.1 to
2.8–2.9 ms mean and from 3.6–3.8 to 4.8 ms mean (p99 6.1 ms), inside the 10 ms tick. That
is why the engine captures only while something reads `output`. Turning a capture into
an `OutputSnapshot`, on the reader's thread, takes 0.04 ms on the Phase 3 show and
10–11 ms on the reference rig (one `FixtureOutput` per element): polled 20 times a second,
a fifth of a core.

**The effect status** (GAP-09, 2026-10-23; same helpers, GC off). Capturing the running
effects on the engine thread (a small record per instance) takes **0.03 ms** a tick for
the reference rig's 20 effects; their tick took 3.85 ms mean with the capture and 3.79 ms
without it, within run-to-run noise. The engine captures only while something reads
`effects` all the same, as it does for the output. Building the 20 `EffectStatus`es with
their next cycle, on the reader's thread, takes 0.16 ms mean (0.23 ms p99).

**A frontend on `busk run`** (GAP-11, 2026-10-23; `busk run --frontend` on the reference
rig with its 20 effects, every playback up, three processes, 15 s per run). A frontend
that polls `frame`, `output` and `effects` 20 times a second costs the engine process
0.015 core (0.49–0.50 core without it, 0.505–0.51 with it), and its overruns stay at
the idle runs' level (3 and 10 per 1 400 ticks, against 2 and 7: noise). That is with the
pacing the engine host does: it lets the engine capture the output and the effects only
every 40 ms (`WATCH_S`) and sends each capture once; frames go after every tick. Without
the pacing, capturing and sending every tick (600 KB of output a tick), the same reads
cost 0.13 core and doubled the overruns (about 0.5 % of ticks against 0.25 %). The
console process spends 0.25 core on them, almost all of it turning each capture into
`FixtureOutput`s (15 ms a read for 8 192 elements, as with `LiveShow`).

## Misses

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

## Live edits

**Live edits** (`bench/edit_latency.py`, phase-3-plan step 13): the engine runs at 100 Hz on
the real clock with autosave running while 50 edits of each kind go through the session.
On the demo rig (the Phase 3 build) an edit takes **2–4 ms median, 5.5–7.5 ms p95** with
**0 overruns** (max tick 6.4–7.2 ms; one run started straight after the perf suite
overran once, at 11.4 ms). A script that edits back to back is harsher: `busk run
--script tests/fixtures/phase3-build.busk` (about 150 edits in under a second) overruns 0–2
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

## Processes

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

## The soak

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
run fails. The 24-hour run is the user's ([hardening checklist](checklists.md#hardening-checklist-phase-7)).
A report (`--report`, default `soak-<UTC>.json`, checkpointed while it runs, plus a
printed summary) holds the numbers above and every drop and action; the files the run
wrote stay next to it in `soak-<UTC>/`, the event log among them, so with the seed
`busk replay` shows what the engine saw. Soaks run one at a time: they use fixed
ports (UDP 5568 and 6454, the virtual MIDI port's name).
