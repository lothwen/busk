# Phase 7 — Hardening: implementation plan

> Source spec: `busking-console-architecture-python.md` (§22, Phase 7; §2, §4.2, §5.6, §5.14, §5.16–§5.18, §6.4, §10, §12, §13.4, §14, §15, §16–§20, §23). Builds on the Phase 0–6 plans and on the code as it stands after Phase 6 (2712 tests). §2 names the real modules this plan changes, so no seam-mapping step is needed. It was written without asking the user, as requested: every call in §3 is open to veto.

## Context

Phase 6 ends with a console that a MIDI controller and a phone play together, with Art-Net, sACN and DMX-USB output. Everything runs in one CPython process, as threads that share one GIL:

- On the §19 reference rig, live edits overrun 166 of 1609 ticks (10 %), and surface load overruns 1.6–2.8 % of ticks. The engine is only waiting for the GIL that the console's compiles and the surface threads hold. Phases 3–6 each recorded this as an input for Phase 7's process split.
- Any crash ends the output. An exception inside a tick ends the engine thread, and the stage freezes on the last frame for good.
- A route that cannot open at start-up is never tried again. A MIDI controller that is unplugged stays dead. A phone or an OSC app can flood the command queue.
- `limits`, `park` and `holdLastFrameOnEngineStall: false` are listed by the limitation report as ignored. Highlight was deferred here by phase-3-plan, and the strobe-rate cap is still missing. Fast intensity effects escape any cap (phase-5-plan).
- Fixture profiles are written by hand. The user's TupperDMX rig runs on five hand transcriptions of its OFL files (`examples/tupperdmx/profiles`).

The spec scopes Phase 7 as *"Process split, watchdog, park, limits, strobe cap, soak tests, GDTF/OFL import"*. It is done when there is a *"24 h soak with zero output drops"*. phase-6-plan §10 adds route and MIDI reconnects, rate limits on remote commands, `holdLastFrameOnEngineStall: false`, and the question of whether the split closes the overrun misses.

Five things make this phase harder than its one-line scope suggests:

1. **The engine compares compiled objects by identity.** A live swap keeps a running playback's fades when its compiled cue list is *the same object* (`playback.cueList is not self.playback.cueList`), and remaps lanes only when the slot table changed (`compiled.slots is old.slots`). A compiled show that crosses a process boundary arrives as new objects. Unless the transport preserves identity, every edit would retarget every running playback.
2. **Loading a compiled show holds the GIL.** Measured while writing this plan (§2): a `CompiledShow` does not even pickle as it is (`MappingProxyType`). With a reducer, the reference rig is 15–27 MB and takes 64–86 ms to load, as one C call. Sent whole on every edit, it would move the stalls into the engine process instead of removing them.
3. **The output has to outlive the engine.** §18 asks the output to *hold the last frame* while a watchdog *restarts the engine*. So the output cannot live in the process that gets restarted, nor in one that runs the operator's edits.
4. **A restarted engine has no runtime state.** §17 never persists fades, effect phases or playback states, and §18's "resumes from autosave" would bring back masters and the programmer, but not the looks: the stage would go dark. The plan restores the looks from the last snapshot the console received.
5. **"Zero output drops for 24 h" needs a definition**, and a measurement taken on the wire by receivers, not from the sender's own counters. It also needs load that resembles a show. A 24-hour run does not fit in a test session.

**Done when:**

- `busk run` runs a show as three processes (§5.1):
  - the **root**, which sends the output and watches the others;
  - the **engine**, which runs the §4.2 pipeline;
  - the **console**, which holds the session, the prompt, the surfaces and the web remote.

  `--threads` keeps the Phase 6 single-process layout.
- **Killing the engine** (`kill -9`, or `SIGSTOP` to stall it) during a show:
  - the output never stops. The root holds the last frame, or turns intensity off when `holdLastFrameOnEngineStall` is false;
  - the watchdog restarts the engine;
  - the look comes back from the last snapshot. On a show of static looks it is byte-identical to the frame before the kill.

  **Killing the console**: the show runs on, a new console comes up, and the phone reconnects. `test_processes.py` and `test_watchdog.py` prove both against real processes and receivers on localhost.
- **The split closes the overrun misses.** On the reference rig, at most 1 % of ticks overrun under edits (`bench/edit_latency.py --processes`) and under surface load (`bench/surface_load.py --processes`). The demo rig has 0 overruns. The numbers are recorded next to Phase 6's.
- **The §12 safety stage is complete**: park, fixture limits, the strobe-rate cap (which also bounds intensity effects) and highlight. So are §18's panic commands (`RELEASE_ALL`, `OUTPUT` on/off) and its unpatched-fixture warnings. Starting from the show that the Phase 3–6 scripts build, `examples/phase7-safety.busk` adds them with console commands only. `test_safety_show.py` checks the §5.24 checkpoints by hand-computed values and golden bytes, at 100 Hz, on an irregular tick schedule and after save → load.
- **Routes reconnect** after any failure, at start-up or while sending. MIDI controllers can be unplugged and plugged back in. The web remote and OSC are rate-limited, and the engine's per-tick drain is bounded.
- **OFL import**: the five TupperDMX fixtures import, convert like the hand transcriptions (with the differences listed in §5.18), and the TupperDMX show builds from the imported profiles. **GDTF import** covers the §5.19 subset, tested on synthetic GDTF files.
- **A 24-hour soak** (`bench/soak.py`) of the Phase 7 show has **zero output drops** (definition: decision 23), every chaos kill recovered, and memory within bounds. During the soak the console, MIDI, OSC and a phone are fuzzed, and the engine and the console are killed on a schedule. A 1-hour run is recorded during development; the 24-hour run is the user's (step 20).
- Every Phase 0–6 test still passes, except the tests that asserted what this phase changes; §6 lists them step by step.

---

## 1. Scope

| In Phase 7 | Deferred (to) |
|---|---|
| Process split: root (output, watchdog, process manager, event log), engine, console; `--threads` fallback | Running the engine on another machine; a backup console (sACN priority already allows one) |
| Compiled shows sent with structural sharing, an engine view and chunked loads | — |
| Watchdog: stall and crash detection, restart, restore of the look from the last snapshot, crash-loop guard | Restoring fades and effect phases exactly |
| Console restart after a crash, against the running engine | Detecting a console that hangs without exiting |
| Safety stage: park, limits, strobe-rate cap (also on intensity effects), highlight | Capping chases that flash intensity (§9) |
| `holdLastFrameOnEngineStall: false` | — |
| `RELEASE_ALL`, `OUTPUT` on/off (§18 panic), unpatched warnings (§18), tick errors survived | — |
| Reconnect for every route; MIDI hot-plug | Network-interface hot-plug events (routes poll instead) |
| Rate limits (web, OSC) and a bounded engine drain | TLS for the web remote |
| OFL import, GDTF import (subset), profile updates in a show | GDTF mode masters, DMX breaks (need `elementPatch`); assets (gobo images) in the `.show` ZIP |
| The event log (§15.5) and `busk replay` | — |
| Soak harness, a 1 h run here, the user's 24 h run | — |
| | Pages per surface; a programming UI (blind preview, edits over the API, template editor): a phase of their own (§10) |

Highlight, the panic commands, unpatched warnings and the event log go beyond §22's one-line scope:
- earlier plans deferred highlight to "Phase 7, with the rest of the §12 safety stage";
- the panic commands and unpatched warnings are in §18, which this phase implements;
- the event log is §15.5, which no phase scheduled. Reproducing what a soak finds is where it pays off.

None of them is needed by the done criteria except highlight and the panic commands, which the safety show exercises. Step 17 (the event log) is the one step the user can defer without touching them.

---

## 2. Baseline from Phase 6

These are the modules this plan changes, as they are now.

| Area | Now | Phase 7 change |
|---|---|---|
| `cli.py` | `_run` builds everything in one process: engine, output, autosave, feedback, supervisor and stdin threads, MIDI, OSC and web | `busk run` starts the root (default) or the Phase 6 layout (`--threads`). The console half of `_run` moves to `process/console_host.py`. Adds `busk import`, `busk replay` |
| `engine/loop.py` | `run` lets an exception in `tick` end the thread. Stages 9–10 in `apply_masters`, then conversion. `Frame.compiled`. `drain` is unbounded | Tick errors counted; the safety stage; `restore`; `RELEASE_ALL`, `OUTPUT`; `Frame.layout` and `Frame.outputEnabled`; at most `MAX_DRAIN` items per tick |
| `engine/masters.py` | `apply_masters` scales by group masters and the grand master, and applies blackout | Blackout moves into the safety stage (the function keeps its signature) |
| `engine/effects.py` | `tempo()` gives an effect's rate | Capped for intensity effects; capped clocks re-rate on tempo changes |
| `engine/snapshot.py`, `engine/install.py` | `PlaybackStatus` without a sequence number; `ProgrammerFrame` without highlight | `PlaybackStatus.seq`, `EngineSnapshot.outputEnabled`; highlight lanes and bytes in the frame |
| `compiler/` | No safety data. `limitations.py` lists limits, park and hold-false | `compiler/safety.py`: park, limits, strobe lanes, dark bytes; unpatched warnings; `OutputLayout`. Those limitation lines go |
| `commands/` | 34 command types | `HIGHLIGHT`, `RELEASE_ALL`, `OUTPUT` (37) |
| `session/` | `Session(show, bus, …)` writes to a `CommandBus` | The bus may be a `RemoteBus`. Highlight in programmer frames. Installs carry the session's show stamp and, for the event log, their cause |
| `output/scheduler.py` | Holds the last frame whatever the setting. A route that failed to open is retried only when an edit changes it. No output statistics | Reads an `OutputLayout`. Hold or dark on a stall. Output off. Retries and reopens. `OutputStats` |
| `io/surfaces.py`, `io/feedback.py` | MIDI ports open at reconcile only | Hot-plug polling |
| `web/api.py`, `io/osc.py` | Every message is submitted | Token buckets |
| `model/` | `Fixture.limits`, `Show.park` and `highlightDmx` exist but nothing reads them | `Show.safety`; §5.23 rules |
| `session/library.py` | busk JSON profiles | OFL and GDTF files are imported on load |
| `persistence/` | Autosave, recovery | The show stamp in `session.json`; the event log |
| Tests | `harness.Harness`, `session_harness.Live`, `sacn_receiver.py`, `artnet_node.py`, `ws_client.py` | A process harness, a DMX widget helper, GDTF builders (§7) |

**Benchmark baseline** (phase-6-plan step 19, 2026-10-14; 2712 passed):

- Appendix A busking tick: 0.078 ms mean, 0.110 ms p99.
- Reference rig, 60 playbacks: 1.999 ms mean, 2.495 ms p99.
- 20 effects: 3.795 ms mean, 4.719 ms p99.
- 60 transitions: 3.280 ms mean, 4.301 ms p99.
- 60-GO burst: 17.6 ms mean.
- 8 chases: 4.136 ms mean on step ticks.
- Output cycle for 64 universes: 0.065 ms median for sACN, 0.066 ms for Art-Net. Conversion: 0.297 ms median.
- Edit latency:
  - demo rig: 0 overruns in 794 ticks, p95 9.1 ms;
  - reference rig: **166 overruns in 1609 ticks**, p95 134.5 ms.
- Surface load:
  - demo rig: 0 overruns in 2000 ticks;
  - reference rig: **56 overruns in 1990 ticks (2.8 %)**, 1.55 % on a later run.

**Transport measurements** (made while writing this plan, 2026-10-14, Python 3.14.7). `pickle.dumps` of a `CompiledShow`, protocol 5, with a reducer for `MappingProxyType`:

| Rig | Compile | Pickle | Load | Largest parts (load) |
|---|---|---|---|---|
| demo (phase6 golden show) | 7.5 ms | 0.08 MB | 0.6 ms | — |
| reference, 60 playbacks | 437 ms | 15.0 MB | 64 ms | `channels` 3.8 MB (44 ms), `slots` 2.1 MB (16 ms), cue lists 3.8 MB (2.4 ms), `plan` 2.4 MB (0.2 ms) |
| reference, 5 cues, 20 effects, 8 chases | 950 ms | 26.9 MB | 86 ms | cue lists 15.6 MB (39 ms); the largest list 2.1 MB (2.0 ms), median list 0.1 ms |

- Without its per-slot records, the slot table is 0.7 MB and loads in 0.04 ms.
- One run measured a single 0.9 MB list at 19–21 ms. Alone it loads in 1.3 ms; the difference was a garbage collection during the load.
- The engine never reads `compiled.channels`, `memo` or the slot table's per-slot records: only the converter's plan and the slot table's arrays.

---

## 3. Decisions and assumptions

### Processes

1. **Three processes** (§16, §18):
   - The **root** is the `busk run` process the operator starts. It runs the output scheduler (routes, Art-Net and sACN discovery, `--console` frame lines), the watchdog and the process manager. It also writes the event log. It runs no show code: no session, no compiler, no surfaces.
   - The **engine** runs the engine thread, plus two threads that move commands in and frames, snapshots and statistics out.
   - The **console** runs everything else that runs today: the session, the console prompt, the surfaces, feedback, the web remote, autosave and the status lines. It owns the terminal.

   **Why not two processes** (engine and output together, as phase-6-plan §10 suggested)? The output must survive the process the watchdog restarts, or "hold the last frame" (§18) fails exactly when it matters. "Zero output drops" could then not survive a crash test. The cost is one frame per tick over a Unix socket: 32 KiB for 64 universes, a few microseconds.

   **Rejected alternatives**:
   - free-threaded CPython 3.14t removes the GIL contention but gives no isolation, and every dependency would need a free-threaded build;
   - sub-interpreters cannot import NumPy;
   - `multiprocessing` hides the file-descriptor and pickling rules that this design needs explicit.
2. **Links are socket pairs made by the root** (§5.2).
   - Root ↔ engine and root ↔ console are *control* links. The root also makes one console ↔ engine link per pairing and passes its two ends to the processes (`socket.send_fds`). No internal link is bound to a path or a port, so nothing outside the process tree can connect to one.
   - Messages are length-prefixed. Frames are raw bytes behind a fixed header; everything else is pickled.
   - **Pickle is used only between these processes**. The web remote and OSC stay JSON and OSC: nothing from the network is ever unpickled.
3. **Compiled shows travel as an engine view, with structural sharing, in chunks** (§5.3).
   - **The engine view** leaves out what the engine never reads: `channels`, `memo`, `warnings`, and the slot table's per-slot records and key map. It keeps the slot keys as one tuple of strings, for the rare remap the engine computes itself (decision 8).
   - **Structural sharing.** An object that is *the same object* as in the previous install on that link is sent as a reference (`persistent_id`): the rig, the plan, each compiled cue list. The engine resolves the reference to the object it already holds. An edit therefore sends what the incremental compile changed, and identity is preserved, which the live swap needs.
   - **Chunks.** A big install is sent as several chunks (the rig, then each changed cue list), loaded one by one with a GIL yield between them. The engine sees the install only once it is complete.
   - The engine process freezes its garbage collector after each install (`gc.freeze()`), so collections never scan compiled shows.
4. **The watchdog** (in the root) uses frames as the engine's heartbeat:

   | Condition | Action |
   |---|---|
   | No new frame for `STALL_S = 1.0` s | The engine is *stalled*. The output holds the last frame, or turns intensity off (decision 13). A notice is printed |
   | No new frame for `KILL_S = 3.0` s, or the engine process exits | `SIGKILL` if it is still alive, then a new engine is spawned |
   | A new engine has not published its first frame within `STARTUP_S = 15` s | It is treated as stalled. The time covers its imports and the full install of a §19-sized show |
   | More than 3 restarts within 60 s | The watchdog gives up. The output keeps holding, and the console says so |

   **Exit 70.** An engine whose ticks raise 10 times in a row exits with code 70, to get a clean restart instead of waiting for `KILL_S`. A single tick that raises is counted (`EngineStats.tickErrors`), and the loop goes on, in both modes.
5. **A restarted engine gets the look back from the last snapshot.** This goes beyond §18's "resumes from autosave", which would blank the stage. The console re-sends the full install (show and programmer) and then a `Restore` of the last `EngineSnapshot` it received:
   - every master's level;
   - the speed masters' tempo *and beat anchor*: `CLOCK_MONOTONIC` is shared by every process, so BPM chases and effects land back on the same grid;
   - blackout, output enabled, the page;
   - every active playback at its current cue and fader level, snapped (no fade), in the order of a new `PlaybackStatus.seq`, so the LTP stack is rebuilt in activation order.

   Not restored: fades in progress (they snap to their target), Hz effect phases, held flashes and swops, soft-takeover attachments. On a show of static looks, the restored frame is byte-identical to the one before the kill.

   **Crash loops.** A restart within 10 s of a restore restarts *without* the restore, in case the restored state is what crashes the engine.
6. **Commands made while the engine is down** are queued in the console (at most 1024, oldest kept; the rest dropped and counted) and sent after the restore. So a blackout pressed during a restart still happens. Installs are not queued: the reconnect sends the session's current state anyway.
7. **The console process can crash and come back.**
   - Exit code 0 (quit) or 1 (load, compile or script failure) ends the run with that code.
   - Death by a signal, or code 70 (the console's top level turns any unexpected exception into 70), starts a new console with `--restarted`. It is limited like the engine: 3 restarts in 60 s.
   - A restarted console recovers as `busk run` does after `kill -9` (show autosave and programmer, §17). It **adopts** the running engine's masters, tempos and page instead of pushing its own. It does not re-run `--script` or `--values`.
8. **The show stamp.** Each install carries `(sessionId, showVersion)`, and `session.json` records the stamp of the newest show on disk. A restarted console whose recovered show has the engine's stamp sends only the programmer. Otherwise it installs the recovered show as a live edit: edits made after the last show autosave (at most `SHOW_DELAY = 5` s) are undone on stage. The slot remap for that install is computed by the engine from the slot keys it keeps, since the new console never saw the engine's compiled show.
9. **Signals and shutdown** (§5.9).
   - The engine runs in its own session, so terminal signals never reach it.
   - The console shares the terminal's process group. Ctrl+C keeps its Phase 3 meaning at the prompt.
   - The root ignores `SIGINT` while a console is alive. Without one (a restart in progress, or given up), `SIGINT` shuts the run down.
   - `SIGTERM` and `SIGHUP` to the root are forwarded to the console, which quits as on Ctrl+C in a non-interactive run.
   - The root owns `--duration`.
   - A console or engine whose root vanished (end of file on its control link) exits at once. The console then writes no clean-exit autosave, so the next run recovers.
10. **`--threads`** runs the Phase 6 layout: one process, the same components, in-process links. It is the default where `socket.send_fds` is missing (Windows). It is what `test_cli.py` uses, because those tests replace `mido` and sockets inside the test process. The watchdog and restarts exist only with processes. The safety stage, stall output, reconnects, rate limits and the event log work in both modes.

### Safety stage

11. **Order** (§12, amended by decision 12). Each step works on the output frame only, so releasing any of them returns exactly to the live state:

    | # | Step |
    |---|---|
    | 1–2 | group masters, grand master (as now) |
    | 3 | highlight (moved before blackout) |
    | 4 | park, intensity lanes |
    | 5 | blackout |
    | 6 | park, every other lane |
    | 7 | limits |
    | 8 | strobe cap |
    | — | conversion; then highlight's `highlightDmx` bytes |

    - **Park** (§5.17) forces a slot to its value whatever any playback, effect, programmer, master or highlight says. A parked intensity is not scaled by the masters. **Blackout still darkens a parked intensity**: §12 says park overrides blackout "for non-intensity slots".
    - **Limits** (§5.6): pan and tilt lanes are clamped to the fixture's `limits.pan` and `limits.tilt`, in logical degrees (before orientation, as programmed). Intensity is clamped to `intensityMax`. Every element of the fixture is clamped, and limits clamp parked values too.
12. **Highlight** (§5.14, §12 step 7) is a programmer mode: `HIGHLIGHT {on}`, autosaved like blind, never undone, and live even when the programmer is blind.
    - Each selected target gets intensity 1 (after the masters, so a grand master at 50 % does not halve it), shutter `open` and colour white.
    - Channels of its other attributes take their profile's `highlightDmx` at conversion. Pan, tilt and parked slots never do.
    - **Blackout, park and limits win over highlight.** §12 orders highlight last, which would light a fixture in blackout or a parked, broken fixture. phase-3-plan left that question to this phase.
13. **The strobe-rate cap** (§12 step 6) is `safety.strobeMaxHz`, a new optional show field. When it is **absent, nothing is capped**: existing shows keep their strobes. The console sets it with `safety strobe <hz>`. It acts in two places:
    - **`strobeRate` lanes** are clamped to the cap. If a fixture's slowest strobe is above the cap, it gets a compile warning, since the converter cannot strobe it any slower.
    - **Effects with an intensity layer** run no faster than the cap allows, counted in *flashes per second*: the rate × flashes per cycle (1 for every waveform except `step`, which counts its rises, and `curve`, which counts its peaks).
      - An Hz effect is clamped.
      - A BPM effect halves its cycles per beat until it is under the cap, so it stays on the beat grid. A tempo change re-rates it, with the existing align-and-nudge.
      - Chases that flash intensity are not capped (§9).
14. **`holdLastFrameOnEngineStall: false`**: after `STALL_S` without a new frame, the output sends the last frame **with intensity off** until frames resume:
    - every dimmer byte (coarse, fine and ultra) and every emitter byte of a virtual-intensity fixture is set to its value at intensity 0;
    - everything else is held, so heads do not swing home.

    The positions and values come from the conversion plan, once per compiled show (`OutputLayout.dark`). The spec left "what is sent" open (README spec gaps, Phase 1.5).
15. **Panic commands** (§18):
    - **`RELEASE_ALL {time?}`** (performance) releases every playback that is active, releasing or flashing, each with its release time, or `time` when given. Held flashes and swops are dropped. The programmer is left alone: `CLEAR_PROGRAMMER` exists.
    - **`OUTPUT {on}`** (performance) is engine state (`EngineSnapshot.outputEnabled`, carried in each frame). While it is off:
      - routes send nothing;
      - sACN streams send Stream_Terminated once, so receivers let go at once, and start again when it is on;
      - Art-Net nodes and DMX-USB widgets keep their last frame, which they do by themselves.

      The status line shows `OUT off`. At an interactive prompt, `output off` asks for confirmation. Scripts and bindings do not.
16. **Unpatched warnings** (§18) are compile warnings, one per unpatched fixture that a cue, effect or park entry drives.

### Robustness

17. **Every route reconnects.**
    - A route that cannot open is retried every `REOPEN_S = 2` s, whatever the reason: an interface not up yet, a serial device not plugged in. Its notice is printed once, then `… sending` when it opens.
    - A route whose status has been failing for `FAIL_S = 1` s is closed and reopened on the same schedule. Interface indexes, addresses and broadcast addresses are resolved again at open, so a USB network adapter plugged back in with a new index is found.
    - Sequence numbers live in the scheduler's shared `Sequences` and `ArtNetNetwork`, so they continue across reopens and engine restarts.
18. **MIDI hot-plug.** The surface manager reads the MIDI port names every `HOTPLUG_S = 2` s:
    - a surface whose device appears is opened;
    - one whose port name has vanished is closed and waits for it. rtmidi raises nothing on unplug, so the vanished name is the only signal.

    Feedback outputs do the same, and a reopened surface gets a full send.
19. **Rate limits.**
    - A token bucket per web client (120 commands per second, burst 240: twice what the page sends) and per OSC surface (200 per second, burst 400).
    - The excess is dropped and counted. The client gets one `error` per second ("rate limit: 37 commands dropped"). OSC drops are reported once per second on stderr.
    - MIDI is not limited: it is local hardware.
    - The engine applies at most `MAX_DRAIN = 512` queued items per tick. The rest wait for the next tick, in order, so a flood that gets through can still not make one tick arbitrarily long.

### Import

20. **OFL import** (§5.18) follows a capability-type table.
    - Unmapped channels become `control` channels held at the OFL `defaultValue`, and the import report lists them.
    - The modelling calls of the hand transcriptions become rules:
      - `FogOutput` is intensity, so the masters and blackout apply to it;
      - a mode whose colour channels are only whites or UV makes each of them its own intensity element, and holds a master `Intensity` channel at full;
      - speeds given only as `slow…fast` become estimates (strobe 1–20 Hz, rotation 10–360 °/s), flagged in the report.
    - Profiles are imported on the fly from OFL files in a `--library` directory, or written by `busk import ofl`.
    - Ids are `ofl-<manufacturer>-<fixture>`. The revision is the OFL `lastModifyDate` plus a short hash of the file, so editing the file makes a new revision.
21. **GDTF import** is a subset (§5.19):
    - single-instance fixtures, and multi-cell fixtures built from geometry references, become elements;
    - mode-master dependencies, DMX breaks beyond the first and virtual channels are reported, not imported;
    - the XML is parsed with no `DOCTYPE` allowed, and the archive's `description.xml` is size-capped.

    No real GDTF file exists on this machine, and the GDTF Share needs an account. So tests use synthetic files written from DIN SPEC 15800, and a real file is a manual check.
22. **Profile updates** (§17): `profile update "<name>"` replaces a show's embedded profile with the library's other revision, as one undoable batch. It is refused when a fixture's mode is missing from the new revision. Nothing is ever updated silently.

### Soak

23. **An output drop** is any of these, measured by receivers on the wire with kernel receive timestamps (`SO_TIMESTAMPNS`) for UDP:
    - a missing sequence number (sACN, Art-Net);
    - outside engine stalls, a gap longer than two output cycles (45.5 ms) between packets. The soak show keeps an effect running, so every universe changes every cycle;
    - during stalls (from the root's engine timeline), a gap longer than the protocol's keep-alive interval plus 250 ms.

    DMX-USB is measured the same way, without sequence numbers, from the pseudo-terminal that stands in for the widget.
24. **Soak criteria**: zero output drops; every chaos kill recovered; each process's resident memory at the end within 10 % + 20 MB of its value after the first hour; no tick or install errors; engine overruns outside restarts at most 0.1 % (soft). Claude runs 10-minute and 1-hour soaks. The 24-hour run is the user's (step 20).

### Deferred, and compatibility

25. **Deferred.**
    - **Pages per surface**: one operator, and the phone shows the controller's page by design (phase-6-plan decision 1).
    - **The programming UI** (blind preview resolve, programmer and show edits over the API, multi-user rules, a template editor): it is not in §22. It deserves its own phase, built on the process split's API.
    - **Assets in the `.show` ZIP**: no UI shows a gobo image.
    - **Detecting a console that hangs**: only exits are seen.
26. **Backward compatible.** There are new commands and a new optional `Show.safety`, so `schemaVersion` stays 1. What changes for existing shows:
    - `limits` and `park` are enforced (they were listed as ignored);
    - `holdLastFrameOnEngineStall: false` darkens a stalled output;
    - `busk run` starts three processes.

---

## 4. Project layout (new and changed files)

```
src/busk/
  process/
    __init__.py          # the process split: what runs where (new)
    wire.py              # framing, messages, raw frames, the compiled-show codec (new)
    links.py             # EngineLink: LocalEngine (threads), RemoteBus/RemoteEngine (console side) (new)
    engine_host.py       # the engine process: python -m busk.process.engine_host (new)
    console_host.py      # the console process: python -m busk.process.console_host (new; from cli._run)
    root.py              # the root: spawn, broker links, frames → output, watchdog, stats, log (new)
  engine/
    safety.py            # the safety stage: highlight, park, blackout, limits, strobe cap (new)
    loop.py              # tick errors, MAX_DRAIN, restore, RELEASE_ALL, OUTPUT, Frame.layout (changed)
    effects.py           # capped tempo, re-rate on tempo changes (changed)
    playback_runtime.py  # release all; restore at a cue; seq for the snapshot (changed)
    snapshot.py install.py masters.py  # PlaybackStatus.seq, outputEnabled; highlight in frames (changed)
  compiler/
    safety.py            # CompiledSafety, OutputLayout, unpatched warnings (new)
    compile.py limitations.py  # (changed)
  convert/plan.py        # intensity byte positions for the dark frame (changed)
  commands/types.py classes.py bus.py   # HIGHLIGHT, RELEASE_ALL, OUTPUT (changed)
  session/session.py programmer.py frame.py  # highlight; show stamp; install causes (changed)
  output/scheduler.py    # OutputLayout, hold/dark, output off, reconnects, OutputStats (changed)
  output/sacn.py artnet.py dmxusb.py   # reopen on failure (changed)
  io/surfaces.py feedback.py midi.py   # hot-plug (changed)
  io/ratelimit.py        # TokenBucket (new)
  io/osc.py web/api.py   # rate limits (changed)
  importers/
    __init__.py          # ImportReport (new)
    ofl.py               # Open Fixture Library → FixtureProfile (new)
    gdtf.py              # GDTF subset → FixtureProfile (new)
  session/library.py     # OFL and GDTF files on load (changed)
  persistence/eventlog.py  # writer, rotation, reader (new)
  persistence/autosave.py  # the show stamp (changed)
  model/show.py validate.py  # Show.safety; §5.23 rules (changed)
  console/parser.py console.py  # §5.22 (changed)
  replay.py              # busk replay (new)
  cli.py                 # root or threads; import; replay (changed)
examples/phase7-safety.busk
examples/tupperdmx/build-ofl.busk   # the TupperDMX build on imported profiles
bench/transport.py       # install sizes and load times (new)
bench/soak.py            # the soak harness (new)
bench/edit_latency.py bench/surface_load.py   # --processes (changed)
tests/process_harness.py # BuskRun: real process trees, pids, kills, stats (new)
tests/dmx_widget.py      # the pseudo-terminal Enttec widget, moved out of test_dmxusb.py (new)
tests/gdtf_builder.py    # synthetic GDTF archives (new)
tests/fixtures/ofl/tupperdmx/*.json   # the user's five OFL files (copied)
tests/golden/phase7_safety_show.json  tests/golden/phase7_frames.json
tests/…                  # see §7
```

Dependencies are unchanged, as in Phase 6: sockets, `struct`, `pickle`, `subprocess`, `zipfile` and `xml.etree` are standard library.

---

## 5. Component design

### 5.1 Process layout and lifecycle

```
 terminal ─── busk run (ROOT) ─────────────────────────────────────────────────────────┐
              │ output thread (44 Hz): routes, discovery, hold/dark, output off        │
              │ frame thread: frames, layouts, stats, log records ← engine             │
              │ watchdog (10 Hz) · process waiters · event log writer · stats file     │
              └──────┬──────────────────────── control ─────────────────────────┬──────┘
                     │ (Attach, Stop)                         (Attach, engine state) │
   ┌─────────────────▼───────────────┐   link (commands, installs,   ┌──────────────▼──────────────────┐
   │ ENGINE (own session)            │ ◀──── restore, hello) ─────── │ CONSOLE (terminal's group)       │
   │ engine thread: §4.2 + safety    │ ───── (welcome, snapshots, ─▶ │ session · prompt · autosave      │
   │ link thread: decode → queue     │        stats)                 │ MIDI · OSC · web · feedback      │
   │ publisher: frames, snapshots    │                               │ RemoteBus = the session's bus    │
   └─────────────────────────────────┘                               └──────────────────────────────────┘
```

**Start-up.**
1. The root makes its two control socket pairs and spawns the engine (`python -m busk.process.engine_host --control <fd>`, `start_new_session=True`). The engine waits for a link.
2. The root spawns the console (`python -m busk.process.console_host --control <fd> --link <fd> <the run arguments>`) with a fresh link pair, and sends the other end to the engine (`Attach`).
3. The console loads, recovers and compiles the show, as `_run` does today, and connects (`Hello`).
4. The engine answers `Welcome(fresh=True)`. The console sends the first install, plus `--values`' base frame, then the recovered masters, tempos and page as ordinary commands.
5. The engine builds its `Engine` and starts ticking. Its first `Layout` makes the root open the routes and print their lines.

Start-up lines from the root and the console may interleave in any order.

**Shutdown** (the console ended: `quit`, end of script or stdin, `--duration`, Ctrl+C or `SIGTERM`):
1. The console stops its inputs (supervisor, surfaces, feedback), writes its final autosave and exits with 0 or 1, as `_run` does today.
2. The root sends `Stop`. The engine finishes its tick, publishes, sends `Final(stats)` and exits.
3. The output makes one last pass and closes its drivers (Stream_Terminated).
4. The root prints the engine and route statistics, as today, and exits with the console's code. The code is 70 if the engine or the console was given up during the run.

### 5.2 Links and messages (`process/wire.py`)

Every message on a link is `struct "<IB"`: the length of what follows, and a kind. Then comes the payload: a pickle, or for `Frame` a fixed header and the raw universes.

| Link | Direction | Message | Content | When |
|---|---|---|---|---|
| control (root–engine) | engine → root | `Layout` | id, `OutputLayout` (universes, output settings, engine rate, dark positions and values) | before the first frame made with a new compiled show |
| | | `Frame` | `<QdIH?`: seq, time, layout id, universe count, output enabled; then 512 bytes per universe | every tick; the newest one when the socket is busy |
| | | `Stats` | `EngineStats` (+ tick errors, longest garbage-collection pause) | every second; `Final` at exit |
| | | `Log` | event-log records | batched, every 100 ms |
| | root → engine | `Attach` | the engine end of a new console link (`send_fds`) | at start, after a console restart |
| | | `Stop` | — | at shutdown |
| control (root–console) | root → console | `Attach` | the console end of a new engine link, and why (`start`, `engine restarted: killed by signal 9`) | after an engine (re)start |
| | | `Engine` | `stalled`, `restarting`, `failed` | when the watchdog acts |
| link (console–engine) | console → engine | `Hello` | the console's session id; restarted or not | on connect |
| | | `Command` | a `CommandEnvelope` | `RemoteBus.submit` |
| | | `Chunk`… `Install` | install chunks, then the commit (§5.3) | `RemoteBus.install` |
| | | `Restore` | an `EngineSnapshot` | after an engine restart (§5.7) |
| | | `LogStart` | the show document | once per connection (§5.21) |
| | engine → console | `Welcome` | fresh, show stamp, current snapshot | on `Hello` |
| | | `Snapshot` | an `EngineSnapshot` | when the published one changes |
| | | `Stats` | `EngineStats` | every second |

- **Writers.** On the console side, one lock serialises writers (MIDI callbacks, OSC and web threads, the console and the session), so the order the session relies on is kept: an install, then the commands validated against its show (phase-3-plan §5.7).
- **The engine side never re-validates.** It may still be one install behind, and the console already checked each command against the show that will be installed first. The engine guards each command, as now.
- **Frames** are sent by the engine's publisher thread, never by the tick. The tick publishes `engine.latest` as today and sets an event. The publisher sends the newest frame whenever the socket takes it, so a slow root makes the publisher skip frames, never the tick wait.

### 5.3 The compiled-show codec (`process/wire.py`)

```python
type Token = tuple[str, ...]          # ("rig",), ("plan",), ("base",), ("list", cueListId), ("new", k) …

def engine_view(compiled: CompiledShow) -> CompiledShow: ...     # memoised by identity, console side
def components(compiled: CompiledShow) -> dict[Token, object]: ...  # the same rule on both sides

class ShowEncoder:                    # console side, one per link
    def encode(self, install: Install) -> list[bytes]: ...          # chunks; the last one commits
class ShowDecoder:                    # engine side, one per link
    def feed(self, chunk: bytes) -> Install | None: ...             # the install once complete
```

- **Engine view.** `channels=()`, `memo=None`, `warnings=()`. The slot table keeps its arrays and a `keys` tuple (slot order), and drops `slots` and `byKey`.
  - A test checks that an engine fed the view gives the same frames as one fed the full show, over the Phase 3 build.
  - The view is memoised per object, so the same compiled show always gives the same view object. Identity therefore survives the view.
- **Sharing.** The encoder keeps `components()` of the previous install it sent, and the decoder of the previous one it received. A pickler `persistent_id` returns the token of any object that *is* one of those components. The unpickler's `persistent_load` returns the decoder's object.
  - Both sides key the components by path, so they agree without coordination.
  - The encoder keeps strong references to them, so an `id()` can never be reused.
- **Chunks.** A changed rig (slot table, plan, base images, universes) is one chunk, and each changed cue list is another. The final chunk holds the rest: playbacks, which reference cue lists by token; pages, masters, output and surfaces; and the remap and programmer frame. In-install references use `("new", k)` tokens.
  - The decoder loads one chunk per call. The link thread sleeps for 0 s between chunks, which yields the GIL.
  - Target: no chunk takes more than 5 ms to load on the reference rig (the largest list measured 2 ms).
- **Order.** Installs and commands share the link, so the engine queues them in the order the session made them, as today's single queue does.
- `bench/transport.py` reports, per rig, the full and engine-view sizes, the chunk count, the largest chunk's load time, and the bytes sent by each `edit_latency.py` edit kind.

### 5.4 The engine host (`process/engine_host.py`)

```python
def main(control_fd: int) -> int:     # python -m busk.process.engine_host --control N
    ...

class EngineHost:
    engine: Engine | None              # built from the first install
    def on_link(self, sock: socket.socket) -> None: ...   # Attach: the previous link is closed
    def run(self) -> int: ...          # 0 after Stop; 70 after TICK_ERRORS_EXIT consecutive tick errors
```

- **Threads.**
  - The *engine thread* is `Engine.run`, with `SWITCH_INTERVAL` (0.1 ms) as in Phase 3.
  - The *link thread* reads the console link: envelopes go onto the engine's queue as they are, chunks into the `ShowDecoder`, and complete installs and restores onto the queue.
  - The *publisher* sends layouts and frames to the root, snapshots and statistics to the console, and log batches to the root.
  - The *control thread* reads the root: `Attach` switches links, `Stop` stops.
- **Layouts.** When `Frame.layout` changes (a new compiled show), the publisher sends its `Layout` before that frame.
- **End of file.** On the root's control link, the process exits at once. On the console's link, it keeps ticking with what it has, and waits for the next `Attach`.
- **Garbage collector.** `gc.freeze()` after each install it applies (decision 3). The longest collection is timed with `gc.callbacks` and reported in `Stats`.

### 5.5 The console host and `RemoteBus` (`process/console_host.py`, `process/links.py`)

```python
class EngineLink(Protocol):           # what the console side reads and writes
    compiled: CompiledShow            # the bus's show: the session points it at each new one
    @property
    def snapshot(self) -> EngineSnapshot | None: ...
    @property
    def stats(self) -> EngineStats: ...
    def submit(self, command: Command, origin: CommandOrigin | None = None) -> CommandEnvelope: ...
    def install(self, item: Install) -> None: ...

class LocalEngine:                    # --threads: today's Engine and CommandBus behind the protocol
    ...

class RemoteBus(CommandBus):          # processes: validates as CommandBus does, then writes to the link
    def attach(self, sock: socket.socket, reason: str) -> None: ...   # from the root's Attach
```

- `console_host.main` is today's `_run` without the engine, the output scheduler and the route lines. The session's bus is a `RemoteBus`. The feedback worker, the web link, the binding resolver, autosave and the status line read `link.snapshot` and `link.compiled` where they read `engine.snapshot` and `engine.bus.compiled`. `--threads` runs the same function with a `LocalEngine` and starts the engine and output threads around it.
- **Reconnect.** On `Attach`, `RemoteBus` sends `Hello` and reads `Welcome`:
  - **`fresh`** (a new engine): the full install, then `Restore(last snapshot)` (unless the root says the restore is skipped, decision 5), then the queued commands;
  - **not fresh** (this console is the restarted one): decision 8's stamp comparison.
- **While no engine is attached**, commands are queued (decision 6). The status line says `engine restarting` instead of the stale state.
- **`--restarted`** skips `--script` and `--values`, recovers whether or not the last exit was clean, adopts the engine's masters, tempos and page, and prints `busk console: restarted after a crash (exit 70); type 'help'`.

### 5.6 The root (`process/root.py`)

```python
STALL_S: Final = 1.0
KILL_S: Final = 3.0
STARTUP_S: Final = 15.0
RESTARTS: Final = 3                   # per RESTART_WINDOW
RESTART_WINDOW: Final = 60.0
RESTORE_GUARD: Final = 10.0           # a restart this soon after a restore skips the restore

class FrameLink:                      # the output scheduler's FrameSource in the root
    latest: Frame | None              # with layout set and compiled None
    layouts: dict[int, OutputLayout]

class Root:
    def run(self) -> int: ...
```

- **The output scheduler is unchanged in role.** It reads `FrameLink.latest` where it read `engine.latest`. It now reconciles on `frame.layout` (an `OutputLayout`, §5.13) instead of `frame.compiled`. A new engine's layouts compare equal by value, so a restart reopens no route.
- **The watchdog** runs at 10 Hz and applies decision 4. Its restart:
  1. spawns the engine with a fresh control pair;
  2. makes a new link pair: `Attach` to the engine, `Attach(reason)` to the console;
  3. prints `engine: restarted (killed by signal 9)` on stderr.

  The console then prints what came back: `engine back: restored 7 playbacks, 6 master levels, page 2`.
- **Console restarts** follow decision 7: a new link pair, the engine's end through `Attach`, the console's end inherited by the new process.
- **`--stats FILE`** (for benchmarks and the soak) appends one JSON line per second:
  - the engine (pid, state, restarts, ticks, overruns, longest tick, tick errors, longest GC pause, RSS);
  - the console (pid, restarts, RSS);
  - the root (RSS, late output cycles, longest gap between cycles);
  - each route's status.
- **Root prints**:
  - route lines and notices, as Phase 6's supervisor did;
  - engine lifecycle lines;
  - `--console` frame lines;
  - the final statistics, where `engine:` gains `, N restarts` when there were any.

### 5.7 Engine restart: `Engine.restore` (`engine/loop.py`, `engine/playback_runtime.py`)

```python
@dataclass(frozen=True, kw_only=True)
class Restore:                        # a queue item, like Install
    snapshot: EngineSnapshot

# PlaybackStatus gains   seq: int = 0          # the playback's newest activation number
# EngineSnapshot gains   outputEnabled: bool = True
```

Applied at stage 1, after the first install:
1. **Masters.** Every level in `masterLevels` (no takeover). Each speed master gets its `bpm`, `level`, and its anchor `(beatTime, beat)` as `(T0, B0)`.
2. **State.** `blackout`, `outputEnabled`, and the page by id.
3. **Playbacks.** With the fade-time override forced to 0 s (the Phase 6 holder, then refreshed), each playback whose status is `active` is restored in ascending `seq`:
   - at the index of its `cue` (chases at that step, on the beat grid);
   - then its fader level, which applies no takeover and triggers no `autoStart`.

   Effects start their clocks at the restore. `sizeFadeIn` still applies, so they grow back. A crossfade fader rests detached until it reaches an end (Phase 6 rule).
4. The snapshot is marked dirty.

A test builds a show of static looks, plays it into a state, takes its snapshot, and restores it into a fresh engine at a later time: the frames must be equal.

### 5.8 Console restart

- The root restarts a console that died (decision 7) with the original arguments plus `--restarted`, the same `--state-dir`, and stdin, stdout and stderr inherited. Lines of a piped stdin that the dead console had already read are gone.
- `persistence/autosave.py`: `session.json` gains `showStamp` (`[sessionId, showVersion]` of the newest show on disk: the autosave, or the saved file when clean). `Recovery` exposes it.
- Surfaces reopen as at start. UDP ports are free once the dead process is gone, and the web server sets `allow_reuse_address`. Phones reconnect by themselves (every 1 s, with the same key).

### 5.9 Signals, exit codes and shutdown

| Event | Root | Engine | Console |
|---|---|---|---|
| Ctrl+C, interactive | ignored | not delivered (own session) | clears the line (Phase 3) |
| Ctrl+C, not interactive | ignored while a console lives; else shut down | — | quits (exit 0) |
| `SIGTERM`/`SIGHUP` to the root | forwarded as `SIGTERM`; `SIGKILL` after 5 s | — | quits as above |
| `--duration` elapsed | `SIGTERM` to the console | — | quits |
| Console exits 0/1 | `Stop` to the engine, final pass, prints, same code | finishes, `Final`, exits 0 | — |
| Console killed or exits 70 | restart (decision 7) | keeps ticking, waits for `Attach` | — |
| Engine dies or stalls | watchdog (decision 4) | — | queues commands |
| Root killed (`-9`) | — | end of file → exits | end of file → exits without a clean autosave |

Only the root's own death stops the output. The root runs output drivers, socket I/O and process management, and no show code. The 24-hour soak is its test.

### 5.10 The safety stage (`compiler/safety.py`, `engine/safety.py`)

```python
@dataclass(frozen=True, kw_only=True)
class CompiledSafety:                 # read-only arrays, rebuilt on every compile (cheap: O(fixtures + park))
    parkIntensity: NDArray[np.intp]   # intensity lanes and their parked values
    parkIntensityValues: NDArray[np.float64]
    parkLanes: NDArray[np.intp]       # every other parked lane (discrete: option index; colour: NaN = derive)
    parkValues: NDArray[np.float64]
    limitLanes: NDArray[np.intp]      # pan, tilt and intensity lanes of fixtures with limits
    limitLow: NDArray[np.float64]
    limitHigh: NDArray[np.float64]
    strobeLanes: NDArray[np.intp]     # every strobeRate lane
    strobeMaxHz: float | None         # Show.safety.strobeMaxHz

class SafetyStage:                    # engine thread
    def apply(self, frame: NDArray[np.float64], *, blackout: bool,
              highlight: Highlight | None) -> None: ...
```

- **Engine.** `Engine.tick` calls `apply_masters(…, blackout=False, …)` and then `SafetyStage.apply`, which runs decision 11's steps 3–8 on the logical frame. Conversion follows, then `highlightDmx` bytes. A frame with no park, limits, cap or highlight takes one branch per step. A swap rebuilds the stage from `compiled.safety`.
- **Park values** are encoded by the values-file encoder (`compiler/lanes.encode_value`, as `compile_values` does). An entry whose attribute the target lacks was already rejected by validation.
- **Limits.**
  - `limits.pan` and `limits.tilt` clamp the pan and tilt lanes of every element of the fixture; `intensityMax` clamps its intensity lanes.
  - A relative effect near a limit is flattened there. That is the point of a limit.
- **Unpatched warnings** come from the same compile pass: `fixtures[5]: 'MH 2' is not patched; playback 3 'Blue' drives it`. The first playback (or park entry, or programmer effect) found is named.

### 5.11 Strobe cap (`engine/effects.py`, `compiler/safety.py`)

```python
def flashes_per_cycle(layer: CompiledLayer) -> float: ...   # 1, steps' rises, curve's peaks
def tempo(effect, speed, rateLevel, cap: float | None = None) -> tuple[float, SpeedMasterRuntime | None]: ...
```

- The cap applies only to effects with an `intensity` layer, in any mode. The largest `flashes_per_cycle` over those layers counts.
- **Hz effects.** `rate = min(rate, cap / flashes)`.
- **BPM effects.** Cycles per beat are halved until `cpb × bpm / 60 × flashes ≤ cap`. The clock is re-rated (aligned, then nudged over a beat, as now) when a tap, `SET_BPM`, a step change or a live edit moves the result. `Playbacks` lists the capped BPM clocks per master for that.
- **Strobe lanes** are clamped in the safety stage.
- **Compile warning**: `fixtures[0]: 'MH 1' strobes no slower than 1 Hz; the cap is 0.5 Hz`.
- Live edits of the cap re-rate running effects at the swap.

### 5.12 Highlight (`session/`, `engine/install.py`, `engine/safety.py`)

```python
@dataclass(frozen=True, kw_only=True)
class Highlight:                      # part of ProgrammerFrame; None when off
    lanes: NDArray[np.intp]           # intensity, shutter and colour lanes of the selected targets
    values: NDArray[np.float64]       # 1.0; the "open" option; white (NaN extras: derive)
    bytes: NDArray[np.intp]           # flat positions (row × 512 + channel) of highlightDmx channels
    byteValues: NDArray[np.uint8]     # coarse, fine and ultra split
```

- **The session builds it** in `build_frame` from the ordered selection and `compiled.channels`. It leaves out pan and tilt, and parked slots. It is rebuilt at every install, so a selection change while highlight is on moves it.
- **The engine.** `Highlight.lanes` are written at decision 11's step 3. `bytes` are written over the back buffer after conversion, except when blackout is on.
- **`HIGHLIGHT {on}`** is a programmer command and a mode: no undo step, saved in `session.json` (`highlight`), restored on recovery. `programmer` lists it.

### 5.13 Panic commands, output enable and stalled output (`engine/loop.py`, `output/scheduler.py`)

```python
@dataclass(frozen=True, kw_only=True)
class OutputLayout:                   # what the output needs of a compiled show; equal by value
    universes: tuple[CompiledUniverse, ...]
    output: OutputSettings
    engineHz: float
    darkPositions: NDArray[np.intp]   # flat positions intensity reaches
    darkValues: NDArray[np.uint8]     # their bytes at intensity 0

# Frame gains   layout: OutputLayout;  outputEnabled: bool = True
```

- **`RELEASE_ALL`.** `Playbacks.release_all(now, time)` applies decision 15. Exclusivity has nothing to do, since everything goes.
- **`OUTPUT`.** `EngineRuntime.outputEnabled` is copied into every frame and the snapshot. When a frame turns it off, the scheduler closes its sACN streams (Stream_Terminated) and sends nothing. When it turns back on, routes reopen (same sequences) and send at once. Status line: `GM 100% | BO off | OUT off | …`.
- **Stall.** The scheduler notes the time of each new frame (by `seq`). After `STALL_S` without one, it sends either the held frame (hold) or the held frame with `darkPositions` set to `darkValues`. Either way the frame is offered as *unchanged* after the first dark one, so keep-alives flow. Notices: `engine: no new frame for 1.0 s; holding the last frame` or `…; intensity off`, then `engine: frames again`.
- **`convert/plan.py`** exposes the intensity byte positions: dimmer channels' coarse, fine and ultra bytes, and the emitter channels of virtual-intensity fixtures. `compiler/safety.py` converts the default frame once to get their values at intensity 0. An inverted dimmer is 255.
- **`OutputStats`**: late cycles (a cycle that starts more than one period after its deadline), the longest gap between cycles, frames held, frames darkened.

### 5.14 Tick errors and the bounded drain (`engine/loop.py`)

- `Engine.run` wraps `tick` in a guard. An exception counts in `EngineStats.tickErrors`. The schedule goes on, and `consecutiveTickErrors` resets on a good tick. The engine host exits with 70 at 10 consecutive errors.
- `CommandBus.drain` stops after `MAX_DRAIN = 512` items. The rest stay queued, in order, for the next tick. No golden test sends that many in one tick.

### 5.15 Route reconnect (`output/scheduler.py`, `output/sacn.py`, `artnet.py`, `dmxusb.py`)

- **Opening fails.** `_skipped` routes that *failed* (not disabled or ignored) are retried every `REOPEN_S`, on the output thread. A notice is printed on the first failure only. Success prints the route line again with `(sending)`.
- **Sending fails.** A route whose `status().ok` has been false for `FAIL_S` is closed and reopened by the scheduler. Each driver's `open` re-resolves its interface, address and broadcast address, and the DMX-USB driver keeps its own reopen.
- **Sequences continue**: they are owned by the shared `Sequences` and `ArtNetNetwork`.
- Tests patch `netif.resolve` and `netif.broadcast_address` to fail and then succeed. A `sendto` that raises `ENETUNREACH` drives the reopen.

### 5.16 MIDI hot-plug (`io/surfaces.py`, `io/feedback.py`)

- **Polling.** `SurfaceManager.poll(now)` reads `mido.get_input_names()` once every `HOTPLUG_S` and serves every MIDI surface from that one list:
  - an unopened surface whose device appears opens: `MIDI s-nano: <port> (connected)`;
  - an open one whose port name is gone closes: `MIDI s-nano: unplugged; waiting for it`.

  The supervisor calls it on its 0.1 s loop.
- **Feedback.** `FeedbackWorker` does the same with output names on its own thread, and sends everything on reopen (Phase 6 rule).
- **Soft takeover.** A reopened controller's faders are detached until they cross. Nothing in the engine changes for that: its `Pickup` state is per binding, and a fresh move from an unknown position is a "first message".

### 5.17 Rate limits (`io/ratelimit.py`, `web/api.py`, `io/osc.py`)

```python
class TokenBucket:
    def __init__(self, rate: float, burst: float, clock: Callable[[], float]) -> None: ...
    def take(self) -> bool: ...
    dropped: int                      # since the last report
```

- **Web.** One bucket per client in `WebApi.received`, before submitting. When a message is dropped, at most one `error` per second goes to that client: `rate limit: N commands dropped`. Releases (`PLAYBACK_BUTTON` and `FLASH` with `down: false`) are never dropped, so a held flash cannot stick.
- **OSC.** One bucket per surface in `OscSurface.datagram`. Drops are reported to stderr once per second.

### 5.18 OFL import (`importers/ofl.py`)

```python
@dataclass(frozen=True, kw_only=True)
class ImportReport:
    profile: FixtureProfile
    notes: tuple[str, ...]            # unmapped channels, estimates, skipped modes, with their channel names

def import_ofl(data: Mapping[str, Any], *, manufacturer: str, key: str) -> ImportReport: ...
```

| OFL capability `type` | busk |
|---|---|
| `Intensity` | `intensity` range (`brightnessStart`/`End`, default 0→1) |
| `ColorIntensity` | a `color` component. Red, Green, Blue, White, Amber, UV, Cyan, Lime → the emitter ids; Magenta, Yellow, Indigo, Warm White, Cold White → custom emitters with an estimated colour (reported). In a mode with no red, green and blue: each white or UV channel is an `intensity` element (decision 20) |
| `ShutterStrobe` | `shutter` functions `open`, `closed`, `strobe`, `pulse`, `random` (`randomTiming`). A speed in Hz → param `strobeRate`; `slow…fast` → 1–20 Hz (reported). `RampUp`, `RampDown`, `Lightning`, `Spikes`, `Burst` → functions busk never outputs |
| `StrobeSpeed` | `strobeRate` |
| `Pan`, `Tilt` | `pan`, `tilt` ranges centred on the travel (`0–540deg` → −270…270), `physical.panRange`/`tiltRange` |
| `PanTiltSpeed` | `positionSpeed` (fast → 0, slow → 1) |
| `WheelSlot` | `colorWheel`, `gobo1`/`gobo2` (wheels in file order), `prism`, by the wheel's kind; slot ids from slot names (`breakup`); colour slots get their `colors` as linear RGB; fractional slot numbers (split slots) → `control` |
| `WheelRotation`, `WheelSlotRotation` with a speed | `gobo1Rotation` (°/s, CW positive; `slow…fast` → 10–360 °/s, reported). An angle range (indexed) has no attribute: its first DMX value is rotation 0 (stopped), the rest is never output, as the moving head's transcription does |
| `Prism` | `prism` slots `off`/`prism<N>` (`facets`); `PrismRotation` speed → `prismRotation` |
| `Zoom`, `Focus`, `Iris`, `Frost`, `ColorTemperature` | `zoom` (degrees; `lens.degreesMinMax` → `zoomRange`), `focus`, `iris`, `frost`, `cto` |
| `FogOutput` | `intensity` (decision 20) |
| `NoFunction` | the dead band of the channel's other capability (`intensity` 0, `prism` off …) |
| everything else (`Effect`, `EffectSpeed`, `Generic`, `Maintenance`, `Speed`, `Time`, `Rotation`, `FogType`, …) | `control`, held at `defaultValue`, never busked |

- **Channels.**
  - `fineChannelAliases` give `bytes` 2 or 3, with `fineOffsets` from each alias's place in the mode.
  - `dmxValueResolution` scales ranges to the channel's full resolution.
  - `defaultValue` and `highlightValue`, as numbers or percentages, give `defaultDmx` and `highlightDmx`.
  - `null` entries in a mode's channel list leave an offset unused.
  - `switchChannels` keep their default switch (reported).
- **Matrices.** `matrixChannels` inserts make one element per pixel (or pixel group), in `repeatFor` order, with `perPixel` or `perChannel` offsets.
- **The library.** `ProfileLibrary` imports a `*.json` file that is an OFL fixture (it has `availableChannels`) on the fly, and the import notes join `problems`. `busk import ofl FILE… [--manufacturer M] [--out DIR] [--report]` writes busk profiles and prints the report.
- **The manufacturer** comes from `--manufacturer`, else the OFL repository layout (`fixtures/<manufacturer>/<key>.json`, unless the directory is named `fixtures`), else "Unknown". The profile's name is `<manufacturer> <OFL name>`.

**The TupperDMX check.** The five files are copied into `tests/fixtures/ofl/tupperdmx/`. For each file and each mode the hand transcription has, every logical value of every attribute both profiles define must convert to the same DMX. Expected differences, asserted as such:
- the smoke machine's 0–7 dead band: OFL `NoFunction`, so intensity 0 → 0 and above 0 → 8…255;
- the moving head's 18-channel mode and the smoke machine's 2-channel mode, which only the import has;
- names, ids and notes.

`examples/tupperdmx/build-ofl.busk` is `build.busk` with the imported profiles' names.

### 5.19 GDTF import (`importers/gdtf.py`)

- **Reading.** A `.gdtf` file is a ZIP. Only `description.xml` is read, capped at 32 MB uncompressed, and parsed with `xml.etree.ElementTree`, refusing any `DOCTYPE`.
- **What is read**:
  - `FixtureType` (`Name`, `Manufacturer`, `FixtureTypeID`, newest `Revision`);
  - `Wheels`;
  - `PhysicalDescriptions/Emitters`;
  - `Geometries`, to find beams and `GeometryReference` instances;
  - `DMXModes/DMXMode/DMXChannels`: `Offset` (`"1,2"` = coarse, fine), `Default`, `Highlight` (DMX values written `value/bytes`), `LogicalChannel@Attribute`, `ChannelFunction` (`DMXFrom`, `PhysicalFrom`/`To`, `Wheel`) and `ChannelSet` (`WheelSlotIndex`).
- **Attributes**:

  | GDTF | busk |
  |---|---|
  | `Dimmer` | `intensity` |
  | `Pan`, `Tilt` | `pan`, `tilt` (physical degrees) |
  | `ColorAdd_R/G/B/W/A/UV/C/Lime`, `ColorRGB_*` | emitters, colours from the emitter's CIE xyY → linear sRGB |
  | `ColorSub_C/M/Y` | subtractive emitters |
  | `Color1` | `colorWheel` |
  | `CTO` | `cto` |
  | `Gobo1`, `Gobo2` | `gobo1`, `gobo2`; `Gobo<n>PosRotate` → `gobo<n>Rotation` |
  | `Prism1`, `Prism1PosRotate` | `prism`, `prismRotation` |
  | `Zoom`, `Focus1`, `Iris`, `Frost1` | `zoom`, `focus`, `iris`, `frost` |
  | `Shutter1` (channel sets Open, Closed, Strobe) | `shutter`; `Shutter1Strobe`/`StrobeFrequency` → `strobeRate` |
  | `PanTiltSpeed`/`MSpeed` | `positionSpeed` |
  | everything else | `control` |
- **Elements**: one per instance of the beam geometry under a `GeometryReference`, in DMX order. Without instances, one element.
- **Reported and skipped**: channel functions with a `ModeMaster` (only those without one are imported), a `DMXBreak` other than the first (`elementPatch` is unsupported), virtual channels (no `Offset`), DMX profiles (curves are linear), relations and macros.
- **Ids and revisions.** The id is `gdtf-<FixtureTypeID>`; the revision is the newest revision's date plus a short hash. `busk import gdtf FILE…` and library directories accept `.gdtf` files.
- **Tests** (`tests/gdtf_builder.py` builds the archives):
  - a 16-bit spot that matches `generic-spot-16ch.json`, checked by conversion equivalence;
  - an RGBW par;
  - a 4-cell bar from geometry references;
  - a file with a mode master, a second DMX break and a virtual channel (reported);
  - a `DOCTYPE` entity file (refused).

### 5.20 Profile updates (`console/parser.py`, `console/console.py`)

- **`profile update "<name>"`.** When the show embeds profile P at revision r, and the library has P at revision r′ ≠ r, a `BATCH` does two things: `SET profiles[i]` to the library's copy, and `SET fixtures[k].profileRevision` for every fixture of P. Validation refuses a fixture whose `modeId` the new revision lacks, naming it. The usual live edit follows: the slot remap and the fades.
- **`list profiles`** shows each embedded profile, its revision and `→ <r′> in the library` when they differ. `fixture add` keeps Phase 3's warning when it uses the show's older copy.

### 5.21 Event log and replay (`persistence/eventlog.py`, `replay.py`)

- **Records.** The engine records, at the tick that applies them:
  - each command envelope: `{"t": …, "c": envelope}`;
  - each install's cause: `{"t": …, "e": {"label", "ops"}}` for show edits, `{"t": …, "p": command}` for programmer changes;
  - each restore.

  The session attaches the cause to the `Install`: the forward patch ops of a show edit or an undo or redo, or the programmer command. The tick appends `(now, item)` to a deque. The publisher batches records to the root (processes), or a writer thread takes them (threads). No I/O happens in the tick.
- **Files.** The root writes JSON lines to `<stateDir>/logs/<show id>/<UTC start>.log`, rotated at 64 MB, keeping 16. The first line is `LogStart`: busk's version, the engine rate and the show document. Each new console connection writes a new `LogStart` line. `--no-log` turns logging off.
- **`busk replay LOG [--until T] [--frames OUT.json] [--at T …]`** builds a session and an engine on a `FakeClock` from the `LogStart` show. In order, it applies records at their tick times: ops through a new `Session.apply_ops` (the validate → compile → install path of undo), programmer commands and performance commands through `submit`, and restores through the queue. It ticks at each logged time and prints or writes frames. Since the engine does not depend on its tick schedule, the frames at the logged times are the live ones.

### 5.22 Console, CLI, status line and limitation report

| Area | Syntax | Becomes |
|---|---|---|
| Park | `park <targets> <attribute> <value>` | `BATCH` of `ADD`/`SET` on `park`, one entry per target |
| | `unpark <targets> [<attribute>]`, `unpark all` | `DELETE`s |
| | `list park` | — |
| Limits | `fixture N [thru M] limits pan\|tilt <min> <max>` | `SET fixtures[k].limits.pan` … |
| | `fixture N [thru M] limits intensity <max>`, `… limits none` | |
| Safety | `safety strobe <hz>`, `safety strobe off` | `SET safety.strobeMaxHz` / `DELETE` |
| Programmer | `highlight on\|off` | `HIGHLIGHT` |
| Panic | `release all [<seconds>]` | `RELEASE_ALL` |
| | `output on\|off` | `OUTPUT` (asks `Turn all DMX output off? [y/N]` at an interactive prompt) |
| Bindings | `<what>` also `release all`, `output on\|off` | `command` actions |
| Profiles | `profile update "<name>"`, `list profiles` | §5.20 |
| CLI | `busk run … [--threads] [--no-log] [--stats FILE]`, `busk import ofl\|gdtf FILE… [--manufacturer M] [--out DIR]`, `busk replay LOG …` | — |

- **Status line**: `OUT off` after `BO`. While the engine is down: `engine restarting` (or `engine failed`) in place of the state.
- **`info`** shows the three pids, the restarts so far, and the event log's file.
- **Limitation report**: the header becomes `Ignored in Phase 7:`. The limits, park and hold-false lines go. What stays: `hid` and `internal` surfaces, `hw` inputs, `display` feedback on MIDI surfaces, and feedback on `command` actions.

### 5.23 Validation (`model/validate.py`)

Errors:
- `limits.pan`, `limits.tilt` with min > max;
- two park entries for the same slot;
- two enabled `dmxUsb` routes on the same `device.port` (Phase 6 gap);
- `safety.strobeMaxHz` ≤ 0 (schema);
- `HIGHLIGHT`, `OUTPUT` without a boolean `on`, or `RELEASE_ALL` with a negative `time`, in `command` actions.

Warnings:
- limits outside the profile's travel (`±panRange/2`, `±tiltRange/2`);
- limits on a fixture whose mode has no pan, tilt or intensity;
- a park value outside the fixture's limits (limits win);
- a strobe cap below a strobing fixture's slowest strobe (§5.11);
- an `OUTPUT` binding with `on: false` that is not a button, since a fader would turn output off on every move.

### 5.24 Done criterion A: `examples/phase7-safety.busk`

Run after the four earlier scripts, on the show they saved. Playback numbers follow `record slot`'s rule: 19 "Strobe", 20 "Fast pulse".

```
# ------------------------------------------------ limits and park
fixture 101 thru 102 limits tilt -90 10      # a low truss: the heads never tilt above 10°
fixture 301 limits intensity 0.5             # the bar runs at half at most
park fixture 204 intensity 0                 # wash 4 is broken: held dark
park fixture 203 color 1 0 0                 # wash 3's colour is stuck on red
safety strobe 3                              # at most 3 flashes per second

# ------------------------------------------------ page 2: a strobe look and a fast pulse
sel group 1
set intensity 100%
set shutter strobe
set strobeRate 10
record slot 2.5 "Strobe"
clear
sel group 2
effect add "Pulse" hz 8 size 1
record slot 2.6 "Fast pulse"
clear

# ------------------------------------------------ panic on the marker SET button
bind "nanoKONTROL2" cc 1 60 release all
save
```

**Checkpoints of `test_safety_show.py`.**
- A fresh engine runs the saved show at 100 Hz, "Speed 1" at 120 BPM from t = 0.
- MIDI moves go through `BindingResolver.handle`, and programmer and show commands through a `Live` session (the programmer and park checkpoints need the session).
- Warm is every fixture at 0.8, colour (1, .75, .45).
- Expected values are logical and computed by hand; DMX is golden and reviewed by hand.

| t (s) | Input | Check |
|---|---|---|
| 0–0.2 | fader 1: 0, 0.5, 1 | At 0.3: washes 201–202 at 0.8, warm. 203 at 0.8, **red** (parked colour). 204 at **0** (parked intensity: its RGBW emitters 0 under a virtual dimmer). Bar at **0.5** (limit). Heads at 0.8 |
| 1 | grand master 0.5 | 201 at 0.4; 204 still 0; bar 0.4 (under its limit); 203 still red |
| 1.5 | grand master 1 | as at 0.3 |
| 2 | `goto 9 4` (Chorus), then fader 9 → 1 (Phase 6's order: the press first) | At 3: MH 1 pan −15 (as Phase 6), tilt **10** (its tracked tilt is 20) |
| 3.5 | knob 11 (Circle) 1 | Over one cycle: MH 1 tilt follows the circle below 10 and is flat at 10 above it; pan follows the circle throughout |
| 5 | marker ▶ (page 2); fader 5 → 1 (Strobe) | Heads: shutter `strobe`, `strobeRate` **3** (asked 10); intensity 1.0 |
| 6 | fader 6 → 1 (Fast pulse) | The washes' intensity repeats every **1/3 s**, not 1/8 s. 204 stays 0 |
| 6.2 | fader 5 → 0 | Strobe releases over its 1 s release time |
| 7.5 | `sel fixture 102`; `highlight on`; grand master 0.5 | MH 2: intensity **1.0**, colour (1, 1, 1), shutter `open`. MH 1 at half its 7.4 intensity. 204 still 0 |
| 8 | blackout | MH 2 dark: blackout wins over highlight |
| 8.5 | blackout; `highlight off`; grand master 1 | The frame equals, at the same time, the frame of a twin run without the inputs of 7.5–8.5 (the Circle and the pulse keep moving, so earlier frames differ) |
| 9 | `park fixture 101 pan 0` (live edit) | From the next tick, MH 1 pan 0 under the circle; tilt still circles under 10 |
| 9.5 | `unpark fixture 101 pan` | The circle's pan is back at the next tick |
| 10 | marker SET (`RELEASE_ALL`) | Every playback `releasing`. After the longest release time (2 s), all idle: the stage at defaults, except 203 red and 204 dark |
| 13 | `output off` | `Frame.outputEnabled` false. A scheduler test route records Stream_Terminated, then nothing. Status `OUT off` |
| 14 | `output on` | Packets again, the current frame at once |
| — | — | The whole run at 100 Hz, on a random irregular schedule, and after save → load gives byte-identical frames at every checkpoint |

### 5.25 Done criterion B: the soak (`bench/soak.py`)

```
uv run python bench/soak.py [--hours H] [--seed S] [--chaos standard|fast|none] [--report FILE]
```

- **The show.** The harness builds a fresh show from the Phase 3–7 scripts with `busk run --threads --duration 1`, as the earlier done criteria do. It then replaces the routes:
  - sACN unicast to 127.0.0.1;
  - Art-Net unicast to 127.0.0.2 (the receiver binds 127.0.0.2:6454 with `SO_REUSEADDR`, as `test_artnet_discovery.py` does);
  - DMX-USB to a pseudo-terminal behind a symlink (`tests/dmx_widget.py`).

  The OSC and web surfaces move to free ports. A virtual ALSA port named "nanoKONTROL2" stands in for the MIDI controller; without `/dev/snd/seq`, MIDI fuzzing is off and the report says so.
- **The run.** `busk run <show> --stats stats.jsonl`, with stdin piped. The harness raises the Circle's knob at start, so universe 1 changes every cycle (decision 23).
- **Load**, from a load process that runs at `nice 10`, seeded:

  | Source | Rate |
  |---|---|
  | MIDI | 100 events/s: faders and knobs, button presses and releases, page buttons every 20 s, blackout on and off every 10 min |
  | OSC | 60 messages/s |
  | Phone (`ws_client`) | 60 `SET_FADER`/s, a button press every 2 s; a 5 s flood of 1000/s every hour (the rate limit's test); reconnect every 5 min |
  | Console stdin | programmer commands at 1/s; a show edit every 10 s (`record cue … merge`, `record preset … merge`, `cue … time`, `undo`, `redo`, a fixture repatched and back); masters and `tap` every 5 s; a few invalid commands, counted |

- **Chaos**:

  | Mode | Engine `SIGKILL` | Engine `SIGSTOP` (stall) | Console `SIGKILL` | DMX-USB unplug and replug |
  |---|---|---|---|---|
  | `standard` | every 30 min | 4 s, every 2 h | every 3 h | every 20 min |
  | `fast` | every 5 min | 4 s, every 20 min | every 20 min | every 5 min |
- **Measurement.** A receiver process at normal priority:
  - sACN and Art-Net sockets with `SO_TIMESTAMPNS`, recording each packet's kernel time, sequence and a data hash;
  - the pseudo-terminal's Enttec messages, on `time.monotonic`.

  The harness also reads `stats.jsonl` (engine state timeline, pids, RSS, overruns) and its own chaos log.
- **The report** (`soak-<UTC>.json`, checkpointed every 10 min, plus a printed summary): duration; output drops per kind and route (decision 23) with their times; late output cycles; engine overruns; longest tick; longest GC pause; restarts against kills; RSS per process (at 1 h, at the end, the slope); fuzz counts; command errors. It ends with **pass** or **fail** against decision 24.
- **`test_soak.py`** (marker `soak`, excluded by default like `perf`): 60 s in `fast` chaos, with one engine kill and one console kill. It must pass.

### 5.26 Performance

**Expected costs.**
- **The safety stage**: a handful of fancy-indexed NumPy operations on small arrays, about 0.02 ms on the reference rig with every fixture limited. Nothing without safety data.
- **The engine process** adds a publisher wake-up per tick and a 32 KiB socket write on another thread. It loses the GIL contention of the console, surfaces, feedback and the web.
- **Installs** cost chunk loads (≤ 2 ms each, measured) on the link thread, and the swap (≈ 1 ms, 5 ms for a patch: phase-4-plan step 18) on the tick.

**Benchmarks.**
- `test_perf.py` (`-m perf`) is re-run: every Phase 6 gate must pass. A new gate: an Appendix A tick with park, limits and a strobe cap is within 10 % of the plain tick.
- `bench/edit_latency.py` and `bench/surface_load.py` gain `--processes`. The bench plays the console and the root itself: it spawns a real engine host, the session writes through a `RemoteBus`, and overruns come from the engine's `Stats`. Both modes are recorded.

  | Rig | Target |
  |---|---|
  | demo | 0 overruns (hard) |
  | reference | ≤ 1 % of ticks overrun under edits and under surface load (hard: the split exists for this); edit latency p95 ≤ 250 ms |
- `bench/transport.py` (§5.3) is recorded.

If the reference rig misses, in order:
1. split chunks per cue;
2. measure what dominates the slow chunk (`bench/transport.py` prints the largest objects) and give it a compact array form;
3. give the engine process its own core (`os.sched_setaffinity`) and record the result with and without.

The 60-GO burst (17.6 ms) is the engine's own cost and stays open (README).

---

## 6. Implementation steps

Each step follows TDD: write the listed tests first, then make them pass. Engine tests use a `FakeClock` and call `engine.tick(now)` directly. Process tests use real processes, socket pairs and localhost receivers; no packet leaves the machine. **Every step ends with the whole suite green** (pytest, ruff check, ruff format --check, mypy). Steps are sized so that two fit in one working session, as in Phases 4–6.

Steps 2–5 are the safety stage, 6–10 the process split, 11–13 robustness and benchmarks, 14–16 import and the console, 17 the event log, 18–19 the done criteria, 20 the user's, and 21 the README.

1. **Baseline.** Run `uv run pytest`, `uv run pytest -m perf -s`, `bench/edit_latency.py` and `bench/surface_load.py`, and record the numbers. → *verify:* green; the numbers are noted under step 13 for comparison.
2. **Schema, commands and validation.**
   - Add `Show.safety` (`strobeMaxHz`), and `HIGHLIGHT`, `RELEASE_ALL` and `OUTPUT` with their classes and bus checks.
   - Add the §5.23 rules.

   → *verify:*
   - `test_schema.py`: 37 command types; `safety` accepted and optional; old documents unchanged.
   - `test_validate.py`: each new error and warning, with its path.
   - Appendix A and the Phase 3–6 goldens validate with 0 errors and 0 warnings.
3. **Park and limits.** `compiler/safety.py`, `CompiledShow.safety`, `engine/safety.py` (steps 4–7 of decision 11, blackout moved), unpatched warnings. → *verify:* `test_safety.py`:
   - no source moves a parked slot: playbacks, flash, swop, override bands, the programmer, absolute and relative effects;
   - masters do not scale a parked intensity, and blackout darkens it;
   - parked colour (with derived extras), gobo and shutter;
   - live edits that add or remove a park entry, at the next tick, also across a repatch (remap);
   - limits at both ends of pan and tilt, a circle flattened at a limit, `intensityMax` under the grand master, every element of a multi-element fixture;
   - frames independent of the tick schedule.

   Also: `test_compile.py` (unpatched warnings) and `test_limitations.py` (the limits and park lines go). Every golden test is unchanged: Appendix A's ±120° tilt limit on MH 1 clamps nothing they play (the step checks it).
4. **Strobe cap and highlight.**
   - `flashes_per_cycle`, the capped `tempo`, re-rating capped BPM clocks, strobe lanes, the compile warning.
   - `HIGHLIGHT` in the session (mode, autosave, recovery), `Highlight` in `ProgrammerFrame`, the engine's step 3 and its bytes.

   → *verify:*
   - `test_strobe_cap.py`:
     - Hz clamp;
     - BPM halving across a tap, a `SET_BPM` and a step change, without a jump (the position is continuous; on the grid one beat later);
     - `step` and `curve` flash counts;
     - non-intensity effects untouched;
     - a live edit of the cap;
     - no cap without `safety`.
   - `test_highlight.py`:
     - full intensity under a grand master at 50 %, white, open;
     - `highlightDmx` bytes, but never on pan, tilt or parked slots;
     - blackout, park and limits win;
     - blind does not hide it;
     - a selection change moves it;
     - no undo step;
     - recovered after `kill -9` (`test_recovery.py` gains `highlight on`).
5. **Panic commands, stalled output, tick errors.**
   - `RELEASE_ALL`, `OUTPUT`; `Frame.layout`, `Frame.outputEnabled`, `OutputLayout`; dark bytes from the plan.
   - The scheduler's stall handling and `OutputStats`; the `run` guard and `tickErrors`; `MAX_DRAIN`.

   → *verify:*
   - `test_panic.py`: release all with its times and with `time`; flashes and swops dropped; the programmer kept; output off and on through an sACN receiver (termination, then a new stream with continuing sequence numbers); status `OUT off`.
   - `test_stall_output.py`, with a fake frame source that stops:
     - hold;
     - dark bytes for a 16-bit dimmer, an inverted dimmer and a virtual-intensity par;
     - keep-alives during the stall;
     - frames again.
   - `test_engine.py`: a tick that raises is counted and the next tick runs; 600 queued commands take two ticks, in order.
   - `test_limitations.py`: the hold-false line goes.
6. **Wire format.** `process/wire.py` (framing, messages, raw frames, `engine_view`, `components`, `ShowEncoder`, `ShowDecoder`) and `bench/transport.py`. → *verify:* `test_wire.py`:
   - framing over socket pairs: partial reads, messages of 0 bytes and 64 MiB, end of file mid-message;
   - frames round-trip with their header;
   - the encoder and decoder:
     - an unchanged cue list arrives as *the same object* as before, and an unchanged rig keeps `slots is`;
     - an edited list arrives new;
     - in-install references resolve;
     - no `MappingProxyType` failure;
     - the engine view drops what §5.3 says;
   - **the Phase 3 build's 120 steps plus undo**, fed to one engine directly and to another through encoder → bytes → decoder: byte-identical frames at every step (fake clock, one process);
   - on the reference rig, no chunk loads in more than 5 ms.

   `bench/transport.py` numbers are recorded in step 13.
7. **Engine host.** `process/engine_host.py`, `process/links.py` (`EngineLink`, `LocalEngine`, `RemoteBus`), `Engine.restore`, `PlaybackStatus.seq`, `EngineSnapshot.outputEnabled`. → *verify:*
   - `test_restore.py` (in-process, fake clock): the static-looks frame equality; LTP order rebuilt from `seq`; masters, tempo and beat anchor (a chase on the same step), page, blackout, output; releasing playbacks not restored; a crossfade fader detached.
   - `test_engine_host.py`, with a real `engine_host` child and the test playing root and console over socket pairs:
     - the layout arrives before the first frame;
     - frames arrive at about the engine rate;
     - snapshots follow commands;
     - `Stop` gives `Final` stats and exit 0;
     - end of file on the root link → exit;
     - a root that stops reading for 2 s: the engine's overruns stay 0 and frames are skipped;
     - a second `Attach` replaces the console link;
     - 10 consecutive tick errors → exit 70 (with a fake engine).
8. **The root and `busk run` in processes.** `process/root.py`, `process/console_host.py` (from `cli._run`), `--threads`, signals, shutdown order, `--duration` in the root, `--stats`, `tests/process_harness.py`. → *verify:*
   - `test_processes.py`, with real process trees:
     - a run quits on `quit` with exit 0 and prints the engine and route lines;
     - a failing `--script` exits 1;
     - `SIGTERM` to the root: an orderly stop, with an sACN receiver getting Stream_Terminated;
     - `kill -9` of the root: both children gone within 1 s;
     - `--duration`;
     - `--console` frame lines printed by the root;
     - start-up lines present (as a set);
     - `--stats` lines parse.
   - `test_recovery.py` passes unchanged (it now kills a root).
   - `test_cli.py`'s runs pass `--threads` (they replace `mido` and sockets in-process), listed in the commit message.
9. **Watchdog and engine restart.** Liveness from frames, `STALL_S`, `KILL_S`, `STARTUP_S`, restart and link brokering, the console's resync (install, restore, queued commands), the crash-loop guard, lifecycle lines. → *verify:* `test_watchdog.py`, with real processes and an sACN receiver:
   - `kill -9` of the engine on a static show:
     - no missing sequence number;
     - no gap beyond the keep-alive;
     - after the restart, the received frame equals the frame before the kill;
     - a `fader` command typed during the gap is applied after the restore;
   - `SIGSTOP`: a stall notice at 1 s, a restart at 3 s;
   - with `holdLastFrameOnEngineStall: false`, the receiver sees dark bytes during the stall;
   - four kills in 60 s: the watchdog gives up, the output keeps sending, the status says `engine failed`;
   - a restart within 10 s of a restore skips the restore.
10. **Console restart.** Exit codes, `--restarted`, `showStamp`, the stamp comparison, the engine's own remap from slot keys, surfaces reopening. → *verify:* `test_console_restart.py`:
    - `kill -9` of the console while an effect runs: the receiver's frames keep changing throughout;
    - a new console prints its banner;
    - a `ws_client` reconnects and receives state;
    - an equal stamp installs no show (the engine's install count is unchanged);
    - an edit not yet autosaved is undone on stage after the restart;
    - a patch edit not yet autosaved restores through the engine's remap;
    - three crashes in 60 s: given up, the show still runs, Ctrl+C stops it.
11. **Route reconnect and MIDI hot-plug.** → *verify:*
    - `test_reconnect.py`:
      - an sACN route whose interface appears after 3 s opens and sends;
      - a route whose sends raise `ENETUNREACH` reopens after 1 s, with sequence numbers continuing;
      - an Art-Net broadcast address that changes is followed;
      - a DMX-USB port missing at start opens when its symlink appears.
    - `test_hotplug.py`:
      - a fake port-name provider: appear, vanish, reappear, with the messages printed once;
      - feedback reopened with a full send;
      - (marker `midi`) a virtual ALSA port created and destroyed.
12. **Rate limits and the bounded drain.** `io/ratelimit.py`, the web and OSC buckets. → *verify:*
    - `test_rate_limits.py`:
      - the bucket's arithmetic on a fake clock;
      - a web client at 1000 commands per second gets 120 per second through, one error per second, and every button release;
      - OSC drops counted and reported once per second;
      - a flood of 5000 commands queued in one tick is applied over 10 ticks, in order.
    - `test_web_api.py` updated for the error message.
13. **Benchmarks** (§5.26). `--processes` for `edit_latency.py` and `surface_load.py`, the new perf gate, `bench/transport.py`. → *verify:* the gates pass and the targets are met (or the §5.26 ladder is applied and its result recorded). The numbers are recorded here, next to step 1's baseline.
14. **OFL import.** `importers/ofl.py`, `ImportReport`, `busk import ofl`, the library's on-the-fly import, `examples/tupperdmx/build-ofl.busk`. → *verify:* `test_ofl.py`:
    - one case per row of §5.18's table;
    - fine aliases out of order, 16-bit ranges from 8-bit ranges, percentages, `null` channels, matrix inserts in both channel orders, switch channels reported;
    - **the TupperDMX check** (§5.18);
    - `build-ofl.busk` builds a show that validates with the same two overlap warnings as `build.busk`, and gives the same frames for its looks wherever the profiles agree;
    - the library imports an OFL file from a `--library` directory.
15. **GDTF import.** `importers/gdtf.py`, `tests/gdtf_builder.py`, `busk import gdtf`, `.gdtf` in library directories. → *verify:* `test_gdtf.py`: the §5.19 test list; `value/bytes` DMX notation at 1, 2 and 3 bytes; CIE xyY → linear RGB against known points (D65 white, the sRGB primaries); a 40 MB `description.xml` refused.
16. **Console and CLI.** The §5.22 grammar (park, limits, safety, highlight, panic, bindings, profiles), confirmation at the prompt, `info`, the status line, `Ignored in Phase 7:`, help. → *verify:*
    - `test_console_parser.py`: one case per §5.22 row, plus errors (`no fixture 999`, `min 20 above max 10`, `expected on or off`, `no library profile named …`, a profile update with a missing mode);
    - `test_console.py`: `list park`, `list profiles`, `output off` asking at a prompt and not in a script;
    - `test_cli.py`: `busk import`, the limitation block;
    - `test_limitations.py`: the full Phase 7 list.
17. **Event log and replay.** `persistence/eventlog.py`, causes on installs, `Session.apply_ops`, the engine's record deque, root and threads writers, rotation, `busk replay`. → *verify:* `test_eventlog.py`:
    - a harness run (commands, programmer changes, show edits, undo and redo, a restore) on an irregular fake-clock schedule is logged, and `busk replay` gives byte-identical frames at every logged time;
    - rotation at a small size keeps the newest files;
    - `--no-log` writes nothing;
    - a process-mode run writes `LogStart` lines and records;
    - the engine's tick does no I/O (the writer is mocked to fail: ticks unaffected).
18. **Done criterion A: the safety show.** Write `examples/phase7-safety.busk`, `test_safety_show.py` and its goldens. → *verify:*
    1. every line of the five scripts succeeds;
    2. the saved show equals `tests/golden/phase7_safety_show.json`, and `busk validate` reports 0 errors and 0 warnings;
    3. every §5.24 checkpoint matches its hand-computed logical values and golden bytes;
    4. the 100 Hz and irregular-schedule runs give byte-identical frames;
    5. save → load → a fresh engine gives the same frames.
19. **Done criterion B: the soak.** `bench/soak.py`, the receiver and load processes, the report, `test_soak.py`. → *verify:*
    - `uv run pytest -m soak` passes;
    - a 10-minute `fast` run passes;
    - **a 1-hour `standard` run passes**, run in the background with progress checked. The reports are recorded here.

    If a run fails, its event log and seed reproduce what the engine saw: the failure is fixed with a test before going on.

    **Soak results** (2026-10-16; 3174 passed, ruff, format and mypy clean). The receiver and the load are their own files (`bench/soak_receiver.py`, `bench/soak_load.py`); `tests/test_soak.py` adds 13 unit tests of the harness's rules to the default run.
    - `uv run pytest -m soak`: passed (72 s): engine kill, DMX-USB unplug and console kill all recovered.
    - A check that drops are caught: a 0.3 s `SIGSTOP` of the root in a `none` run gave 3 gap drops of 320 ms (one per route, the root's own longest gap), and the run failed.
    - **10-minute `fast`, seed 10: pass.** 0 drops (sACN 26266, Art-Net 26252, DMX-USB 25985 packets); 6 of 6 actions recovered: engine kills in 0.9 and 0.5 s, the 4 s stop in 4.3 s (the watchdog kills a stopped engine at 3 s), the console kill in 0.9 s, unplugs in 3.0 and 3.1 s (3 s unplugged); restarts 3/3 engine, 1/1 console. 0 overruns in 59128 ticks (54907 outside outages); longest tick 7.2 ms, longest GC pause 0.2 ms; 0 late output cycles, longest output gap 26.4 ms; RSS engine 60 → 60 MB, console 72 → 73, root 66 → 66. Load: 59858 MIDI events (10854 LED feedback messages back), 35995 OSC, 35365 phone faders, a 5 s flood of 4999 (rate-limited), 855 console lines. Its 21 unexpected console errors came from the load's own command order (`redo` 10 s after `undo`, edits ending in `clear`), fixed before the 1-hour run.
    - **1-hour `standard`, seed 11: pass.** 0 drops (sACN 158267, Art-Net 158254, DMX-USB 157853 packets); 7 of 7 actions recovered: unplugs at 5, 25 and 45 min in 3.0, 3.1 and 3.1 s, engine kills at 10 and 40 min in 0.9 and 1.2 s, the stop at 20 min in 4.0 s, the console kill at 50 min in 0.4 s; restarts 3/3 engine, 1/1 console. 1 overrun in 359081 ticks (354859 outside outages: 0.0003 %), longest tick 10.5 ms (that overrun), longest GC pause 0.2 ms; 0 late output cycles, longest output gap 25.4 ms; RSS engine 60 → 60 MB, console 74 → 73, root 66 → 66 (slopes +3.6, +10.8 and 0.0 MB/h from 30 min on). Load: 359277 MIDI events (61112 LED messages back), 215994 OSC, 213862 phone faders and 1788 buttons, a 5 s flood of 4999 (rate-limited, 5 notices), 12 phone reconnects, 5167 console lines (359 edits, 59 invalid commands: 59 errors, none unexpected), 12 blackout toggles, 179 page turns. The event log reached 152 MB in 9 files.
    - **Found and fixed:** until a restarted engine's first `STATS`, the root's `--stats` lines paired its pid with the killed engine's counters (`FrameLink.report` was kept). `_start_engine` now clears it; `test_watchdog.py::test_stats_lines_never_give_a_new_engine_the_old_ones_counters`. The ticks and overruns above are recomputed without those lines (5 in the hour, 4 in the 10 minutes); no criterion depended on them. `--stats` engine lines also gained `installErrors` and `commandErrors`.
20. **The user's checks** (§8 checklist).
    - **The 24-hour soak** on the user's machine.
    - The TupperDMX rig on the simulator with imported profiles.
    - On the Phase 3 rig with the nanoKONTROL2 and a phone: kills of the engine and the console during a show, MIDI unplugging, and the safety features by eye.

    → *verify by eye and by report:* the 24-hour report says pass; the checklist holds.
21. **README and full verification.**
    - Add a "Hardening checklist (Phase 7)", the process diagram, the decisions taken beyond the plan, the spec gaps and the benchmark and soak numbers.
    - Update "Next" (the roadmap is complete) and the `pyproject` description.

    → *verify:* §8.

    **Done** (2026-10-16; 3175 passed, ruff, format and mypy clean). The README has the Phase 7 status and process diagram, both done criteria, Usage sections for the processes and the watchdog, safety, rate limits and hot-plug, import and the event log, the console rows, the step 1 vs step 13 benchmark table and the soak numbers, the new test files, the layout, ten "How it works" paragraphs, the Phase 7 decisions, the spec deviations, gaps and open items (the known limits of steps 9–10 among them), the hardening checklist and "Next". §8 ran: perf gates 12 passed (Appendix A 0.079 ms mean, reference rig 2.035 ms, 60-GO burst 16.7 ms, safety stage ratio 1.011); `-m soak` passed (72 s); `edit_latency.py --processes`: demo 0 in 805 ticks, reference 1 in 1810 (0.06 %); `surface_load.py --processes`: demo 0 in 2012, reference 4 in 2011 (0.20 %); the five scripts on a fresh show, `busk validate` 0/0, a process run with `--stats`, `info`, `kill -9` of the engine (`engine: restarted …`, `engine back: …`, `restarts: engine 1`) and `list park`; `busk import ofl` of the five TupperDMX files; `busk replay` of the runs' logs. The 1-hour soak was not run again (step 19's run stands). **Found and fixed:** `bench/engines.py` called the root's `_spawn_engine()` without the `log` argument step 17 added, so both `--processes` benches crashed; it passes `log=False`, and `test_engine_host.py::test_the_benches_process_engine_runs_a_show` (fails without the fix) covers it.

---

## 7. Acceptance tests (summary)

| Test file | Proves |
|---|---|
| `test_schema.py` · `test_validate.py` (extended) | The new commands and `safety`; every limits, park, route and command rule |
| `test_safety.py` | Park and limits in the stage order; schedule independence |
| `test_strobe_cap.py` | Strobe lanes; intensity effects capped in Hz and on the beat grid; re-rating without jumps |
| `test_highlight.py` | Highlight values, bytes and precedence; a programmer mode |
| `test_panic.py` · `test_stall_output.py` | `RELEASE_ALL`, `OUTPUT`; hold and dark output on a stall; tick errors; the bounded drain |
| `test_wire.py` | Framing; the engine view; identity preserved by structural sharing; the Phase 3 build through the wire byte-identical |
| `test_restore.py` · `test_engine_host.py` | Restore from a snapshot; the engine process's links, layouts, frames, stats and exits |
| `test_processes.py` · `test_watchdog.py` · `test_console_restart.py` | The process tree; signals and exit codes; engine kills and stalls with no output drop; console crashes; crash loops |
| `test_reconnect.py` · `test_hotplug.py` · `test_rate_limits.py` | Routes reopening; MIDI devices coming and going; floods bounded |
| `test_ofl.py` · `test_gdtf.py` | Import tables; the TupperDMX check; GDTF subset and XML safety |
| `test_eventlog.py` | Logged runs replay byte-identically |
| `test_safety_show.py` | Done criterion A |
| `test_soak.py` (`-m soak`) · `bench/soak.py` | Done criterion B (60 s here; 1 h and 24 h recorded) |
| `test_bus.py` · `test_limitations.py` · `test_cli.py` · `test_console_parser.py` · `test_console.py` · `test_autosave.py` · `test_recovery.py` · `test_engine.py` · `test_output_scheduler.py` · `test_web_api.py` · `test_osc.py` (extended) | The bus, the shorter limitation list, the CLI in both modes, the grammar, autosave's stamp and highlight, the scheduler's new duties |
| `test_golden_7_8.py` · `test_song_stack.py` · `test_effects_show.py` · `test_surfaces_show.py` (unchanged) | The §7.8 example and the Phase 4–6 done criteria still hold |
| `test_perf.py` (`-m perf`, extended) · `bench/edit_latency.py` · `bench/surface_load.py` · `bench/transport.py` | The split's overrun targets; safety costs; transport numbers |

---

## 8. Verification

```bash
uv run pytest                                           # all green
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run pytest -m perf -s                                # gates pass; numbers recorded
uv run pytest -m soak                                   # 60 s soak with chaos: pass
uv run python bench/transport.py
uv run python bench/edit_latency.py --processes         # demo 0 overruns; reference ≤ 1 %
uv run python bench/surface_load.py --processes         # demo 0 overruns; reference ≤ 1 %
uv run busk new /tmp/busk-demo/club.show --title "Club Night"
for s in phase3-build phase4-song phase5-effects phase6-surfaces phase7-safety; do
  uv run busk run /tmp/busk-demo/club.show --script examples/$s.busk --duration 1
done
uv run busk validate /tmp/busk-demo/club.show           # → 0 errors, 0 warnings
uv run busk run /tmp/busk-demo/club.show --stats /tmp/busk-demo/stats.jsonl
#   busk> info                → three pids, 0 restarts, the event log file
#   (another terminal) kill -9 <engine pid>   → "engine: restarted (killed by signal 9)", "engine back: …"
#   busk> list park           → 204 intensity 0, 203 color 1 0 0
#   busk> quit
uv run busk import ofl ~/Documents/TupperDMX/demo.show/fixtures/*.json --manufacturer TupperDMX --out /tmp/tdmx
uv run python bench/soak.py --hours 1 --report /tmp/busk-demo/soak-1h.json   # → pass
```

**Hardening checklist (Phase 7)**, for step 20:

1. **The 24-hour soak.** On a machine that will not sleep (disable suspend), with `/dev/snd/seq` present and UDP 5568 and 6454 free, run `uv run python bench/soak.py --hours 24 --report soak-24h.json`. The summary says **pass**: 0 output drops, every kill recovered, memory within bounds. Keep the report and, on a failure, the event logs it names.
2. **TupperDMX on imported profiles.** Start TupperDMX-Simul first (it holds port 6454). Then:

   ```
   busk import ofl ~/Documents/TupperDMX/demo.show/fixtures/*.json --manufacturer TupperDMX --out /tmp/tdmx
   busk new /tmp/tdmx/tupper.show
   busk run /tmp/tdmx/tupper.show --library /tmp/tdmx --script examples/tupperdmx/build-ofl.busk
   ```

   Play the page. The simulator shows the same looks as with the hand-transcribed build, except the smoke machine's dead band.
3. **On the Phase 3 rig** (nanoKONTROL2, sACN, phone), after the five scripts:
   - Fader 1 up: wash 4 stays dark and wash 3 is red whatever is played. The bar never goes above half.
   - The song's Chorus: the heads tilt no higher than 10°. The Circle flattens at the top.
   - Page 2, fader 5 (Strobe): the heads strobe at about 3 Hz, not 10. Fader 6 (Fast pulse): the washes pulse about 3 times a second.
   - `sel fixture 102`, `highlight on`: MH 2 lights white and full at any grand master. Blackout still darkens it. `highlight off`.
4. `info` gives the engine's pid. `kill -9` it while a look and the Circle run:
   - the stage freezes, and does not go dark;
   - within about 3 s the look is back, and the Circle runs again, on the beat;
   - the faders work again after crossing their levels.
5. `kill -9` the console's pid: the show runs on, a new prompt appears within seconds, and the phone reconnects by itself.
6. Unplug the nanoKONTROL2 for 5 s and plug it back in: `unplugged`, then `connected`. The LEDs show the state again.
7. Unplug the network cable of the sACN route for 10 s: `send failed`, then `sending again`. The rig follows.
8. Set marker (`release all`): every playback releases. `output off` (confirm): the rig's receivers let go. `output on`: back.
9. The run ends with 0 output drops reported by `--stats` (late cycles 0) and the expected restarts.

---

## 9. Spec deviations and gaps

**Deliberate deviations**

- **Three processes, with output in the root** (decisions 1–2), where §16 draws output threads inside the engine process. This is the only layout in which §18's "hold the last frame while the watchdog restarts the engine" holds through a crash.
- **Internal links are pickled**, between the root's own children over socket pairs. §16 says "IPC / WebSocket". The web API stays JSON.
- **Compiled shows cross with structural sharing** (decision 3), which §6.4's atomic swap assumed was free.
- **A restarted engine restores the look from the last snapshot** (decision 5), beyond §18's "resumes from autosave".
- **Highlight comes before blackout**, so blackout, park and limits win, where §12 orders it last. Highlight is logical (intensity, shutter, colour), plus `highlightDmx` for other channels (decision 12).
- **Blackout darkens a parked intensity**: the reading of §12's "including blackout for non-intensity slots" (decision 11).
- **The strobe cap is off unless the show sets it**, and it also bounds intensity effects (decision 13).
- **`holdLastFrameOnEngineStall: false` turns intensity off and holds everything else** (decision 14).
- **`OUTPUT off` sends nothing.** Art-Net nodes and DMX-USB widgets keep their last frame (decision 15).
- **The event log** is written by the root, with show edits as patch ops (§5.21). §15.5 logs envelopes only, which cannot replay edits whose ids were generated.
- **Schema addition** (optional): `Show.safety`. Command additions: `HIGHLIGHT` (§15.2 names it), `RELEASE_ALL`, `OUTPUT` (§18 names `OUTPUT_DISABLE`; one command with `on` toggles both ways).

**Gaps decided here (to fold back into the spec)**

- Watchdog thresholds and crash-loop rules; what a restart restores; commands during a restart.
- Console crashes: exit codes, the show stamp, adoption of the running engine.
- The safety stage's full order; park and highlight against blackout; limits in logical degrees and over every element.
- Flashes per cycle per waveform; BPM capping on the beat grid.
- What a stalled output sends; what output-off does per protocol.
- Reconnect timings; hot-plug polling; rate-limit numbers; the drain bound.
- The OFL and GDTF mapping tables and modelling rules; import revisions; profile updates.
- What an output drop is; the soak's criteria.

**Still open after Phase 7**

- **The programming UI**: the blind preview resolve, programmer and show edits over the API, multi-user rules (§23), a template editor.
- **Pages per surface.**
- **A console that hangs** without exiting is not detected; the root itself has no watchdog.
- **Strobe-like chases** are not capped; neither are fast operator flashes.
- **GDTF** mode masters, DMX breaks, virtual channels, curves; `elementPatch`; assets in the `.show` ZIP.
- **Restoring fades and Hz effect phases exactly** after an engine restart.
- **Single-emitter colour elements** and **colour → colour wheel** (Phase 1–2 gaps), which the importers work around.
- From Phase 6: Ableton Link, ArtSync and sACN sync, `enttecOpen`, DMX-USB with fewer slots, OSC address patterns, TLS for the web, display feedback on MIDI, HID surfaces, Linux-only interface lookups.
- **The 60-GO burst** (17.6 ms, the engine's own cost; Phase 4).

---

## 10. After Phase 7

Phase 7 is the last phase of §22's roadmap. What remains is new scope, and the user's choice:

- **A programming phase**, built on the process split's links: a web programmer (selection, values, presets, effects, recording) with the blind preview resolve as a second resolve in the engine process, multi-user rules (single writer or patches, §23), and a template editor.
- **Pages per surface**, if two operators share one show.
- **The spec gaps** listed in the README, notably colour → colour wheel and single-emitter colour, which would let the importers map more fixtures as they are.
