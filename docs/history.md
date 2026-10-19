# How busk was built

busk was built in phases, each with a plan in this directory, following the roadmap of the
spec's §22 ([`busking-console-architecture-python.md`](busking-console-architecture-python.md)).
This file keeps what the README used to say about them: what each phase added, the done
criteria and how they were met, the decisions taken beyond the plans, and the gaps found in
the spec. The manual checks of each phase are in [`checklists.md`](checklists.md).

## The phases

**Status: Phase 8 — busk as a library** ([plan](phase-8-plan.md)), on top of Phase 7 —
hardening ([plan](phase-7-plan.md)), the last phase of the spec's §22 roadmap, Phase 6 — surfaces and network ([plan](phase-6-plan.md)), Phase 5 —
effects ([plan](phase-5-plan.md)), Phase 4 — time ([plan](phase-4-plan.md)), Phase 3 — programmer & recording ([plan](phase-3-plan.md)),
Phase 2 — busking core ([plan](phase-2-plan.md)),
Phase 1.5 — sACN output ([plan](phase-1.5-plan.md)), Phase 1 — fixtures
([plan](phase-1-plan.md)) and the Phase 0 walking skeleton ([plan](phase-0-plan.md)).
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

Phase 8 makes busk a **library** as well as a command: a public API of 28 names, all
importable from `busk`, to load, validate and save shows, import profiles, render frames
on a clock the caller drives (`OfflineShow`) and run a show live inside another program
(`LiveShow`). The library prints nothing (it logs), MIDI became the optional extra
`busk[midi]`, and busk is an MIT-licensed package installed from its GitHub repository.
The command line did not change: its transcripts are pinned byte for byte. See
[Using busk as a library](../README.md#using-busk-as-a-library) and the guide,
[`docs/library.md`](library.md).

Phase 2 made the engine busk: playbacks running single-cue looks built from groups and
scoped presets, merged by one resolver (HTP intensity per priority band, LTP layer stack
for everything else, presence fades, flash, exclusivity, grand master, blackout), with
the §7.8 worked example as a golden test and MIDI faders driving it.

Phase 1 turned logical values (pan in degrees, colour as linear RGB, a gobo by name) into
DMX through the fixture profiles, verified against the manufacturers' charts for three
real fixtures (`examples/real-fixtures.json`); Phase 1.5 put those bytes on the wire as
**sACN (ANSI E1.31)** with send-on-change, keep-alive and Stream_Terminated.

`busk run --threads` keeps the Phase 6 layout: the same components as threads of one
process, without the watchdog and the restarts.

## Done criteria

The Phase 7 done criteria hold. **A, the safety show**: on the show the Phase 3–6 scripts
save, the script [`tests/fixtures/phase7-safety.busk`](../tests/fixtures/phase7-safety.busk) adds, with
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
([hardening checklist](checklists.md#hardening-checklist-phase-7)). Killing the engine with `kill -9`
or stalling it with `SIGSTOP` never stops the output, and on a show of static looks the
restored frame is byte-identical to the one before the kill (`test_watchdog.py`); killing
the console leaves the show running and the phone reconnects (`test_console_restart.py`).
The split also closes the overrun misses of Phases 3–6: on the §19-sized rig, live edits
overrun 1 tick in 1 911 (10 % with threads) and surface load 0.4 % (2.3 %).

The Phase 6 done criterion holds: on the show the Phase 3–5 scripts save, the script
[`tests/fixtures/phase6-surfaces.busk`](../tests/fixtures/phase6-surfaces.busk) adds, with console
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
script [`tests/fixtures/phase5-effects.busk`](../tests/fixtures/phase5-effects.busk) adds, with console
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
[`tests/fixtures/phase4-song.busk`](../tests/fixtures/phase4-song.busk) adds, with console commands only,
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
[`tests/fixtures/phase3-build.busk`](../tests/fixtures/phase3-build.busk) builds a complete busking show
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
| The GO-burst benchmark gates the median under 20 ms, not the p99 under 10 ms | The 10 ms gate is missed (see [benchmarks](benchmarks.md)); the p99 varies between runs, the median does not. |
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
  preset does nothing on a wheel-only fixture yet. The same holds for fixtures whose only
  colour control is a colour macro (`colorMacro`, since 2026-10-19): `color` does not
  pick their nearest preset.
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
* **Edits stall a big rig's engine** in one CPython process (the GIL; see [benchmarks](benchmarks.md#live-edits)):
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
  take about two ticks (see [benchmarks](benchmarks.md)); retargeting only the changed lanes in place is
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
  [benchmarks](benchmarks.md)), on top of the GO-burst and edit-overrun misses of Phase 4.
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

## Next

The spec's §22 roadmap is complete, and busk is a library (Phase 8). Run the
[library checklist](checklists.md#library-checklist-phase-8) and tag `v0.1.0`. Run the Phase 7
[hardening checklist](checklists.md#hardening-checklist-phase-7), the 24-hour soak first (and the
earlier checklists if they have not been run). What remains is new scope, and a choice:

* **A programming phase**, built on the process split's links: a web programmer
  (selection, values, presets, effects, recording) with the blind preview resolve as a
  second resolve in the engine process, multi-user rules (a single writer or patches,
  §23), and a template editor.
* **Pages per surface**, if two operators share one show.
* **For the library** (phase-8-plan §10): CI on GitHub Actions (the suite on 3.12–3.14, ruff,
  mypy, the doctests, the wheel), wheels attached to GitHub releases for installs without
  git, and on request `compile_show`, route status, custom effect templates, autosave and
  recovery in `LiveShow`.
* **The spec gaps** listed [above](#spec-gaps), notably colour → colour wheel and
  single-emitter colour, which would let the importers map more fixtures as they are, and
  the GDTF parts the import leaves out.
