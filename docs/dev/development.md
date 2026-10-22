# Developing busk

Setting up, testing and finding your way around the source. [`internals.md`](internals.md)
explains how the pieces work, [`benchmarks.md`](benchmarks.md) has the performance numbers,
and [`history.md`](history.md) records how busk was built, phase by phase.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python ≥ 3.12 (development uses 3.14.7,
pinned in `.python-version`).

```bash
uv sync                 # the development setup: busk, the dev tools and the `midi` extra
uv sync --all-extras    # the same, spelled out
```

The `dev` group depends on `busk[midi]`, so python-rtmidi is installed too; on Python 3.13
and later it builds from source, which needs a C++ compiler and the ALSA headers.

## Commands

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

## What the tests prove

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
| `test_resolver.py` | Every §7.3 and §7.4 behaviour, per-lane weights and per-lane snap thresholds, and Phase 5's relative pass (order, continuous suppression by higher bands, clamps), each checked against the per-slot oracle (`reference_resolver.py`); GAP-01's attribution of each lane to what drives it |
| `test_resolver_properties.py` | Hypothesis: resolver == literal §7.7 oracle within 1e-12 (per-lane weights and relative contributions included); HTP in a band commutative and ≥ every input; LTP lanes in the hull of default and inputs; zero weight is a no-op; the attribution == the oracle's, relatives included |
| `test_output_readout.py` | GAP-01's `output` of both facades: every element by fixture number, in the show's units after masters, blackout, park, limits and the highlight; the colour wheel's filter and an explicit white; a bar's cells on its master dimmer; what drives each family (programmer, effect, playback, none) and which playback drives the intensity; a live edit's new rig; the readout compiled with the rig and left out of the engine process; a `LiveShow` captures only once read |
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
| `test_console_parser.py` · `test_console.py` | Every grammar row (311 cases, Phase 4's timing, trigger, chase, master and tempo sugar, Phase 5's effect sugar and Phase 6's page, surface, binding, feedback and route sugar included) and its error messages; execution, rendering (`list cues`, `list masters`, `list effects`, the programmer's fade and effects, `library`), scripts and `source`, defaults, Ctrl+C held back during a command, clearing a typed line at the prompt and quitting at the second in a row, quit offering to save |
| `test_console_prompt.py` | What may follow a line, per grammar area (keywords, names from the show and the libraries, described values, `<Enter>`, mistakes), with no id taken; every word of `examples/club-night.busk` offered where it stands; the `?` help and the grammar forms it picks; the completer's choices for GNU readline and libedit; a real prompt on a pseudo-terminal (Tab, `?`, Ctrl+C twice) |
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

## Layout

```
src/busk/
  __init__.py            # the public API (Phase 8): __all__, lazy re-exports, the NullHandler
  errors.py              # BuskError, ScriptError (the public errors' base and the script one)
  runner.py              # OfflineShow, LiveShow, DmxFrame, their output; _LocalRun (engine and output threads)
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
    parser.py            #   parse(): a console line → an action (pure); expected()
    console.py           #   Console.execute(), run_script(), interact()
    prompt.py            #   Tab completion and ? on readline (GNU readline and libedit)
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
    readout.py           #   ReadoutLayout, build_readout(): per-element lookups of the output readout (GAP-01)
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
    contributions.py     #   Source, SequencedSource (runs of per-slot numbers), gather(), Relative, Origin
    resolver.py          #   Resolver: LTP layer stack + snapping, HTP per band, per-lane weights, relative pass (§7)
    masters.py           #   grand and group masters, blackout (§12; the engine leaves blackout to safety.py); SpeedMasterRuntime, tap tempo (§11.3); fade-time override
    safety.py            #   apply_safety(): highlight, park, blackout, limits, strobe lanes (§12, stage 11)
    surfaces.py          #   PageState, HeldButtons, Pickup: the page, held buttons, soft takeover
    snapshot.py          #   EngineSnapshot, PlaybackStatus, SpeedStatus (beat anchors), PageStatus; OutputSnapshot, FixtureOutput (GAP-01)
    readout.py           #   Capture, capture(), read_output(): the output per fixture element and what drives it (GAP-01)
    install.py           #   Install, ProgrammerFrame, ProgrammerRuntime (fading, its effect bank), remap_lanes()
    loop.py              #   Frame, EngineStats, EngineRuntime, Engine (stages 1–13, restore, tick errors, bounded drain)
    link.py              #   EngineLink, LocalEngine: how other threads read and write an engine (LiveShow, --threads)
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
    links.py             #   RemoteBus: the console's side of the engine process
    console_host.py      #   the console process (and the --threads run): a LiveShow attached to the engine, the prompt, autosave, status
    options.py           #   RunOptions: the run flags, typed (internal)
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
LICENSE                      # MIT
CHANGELOG.md                 # releases (Keep a Changelog); 0.1.0 is the first with a public API
docs/library.md              # the library guide: installing, examples (doctests), reference, stability
examples/club-night.busk     # the demo show, built with console commands only (the five phase scripts in one)
examples/real-fixtures.json  # three real fixtures, transcribed from their manuals
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
tests/fixtures/phase1-values.json  # values for examples/real-fixtures.json: the Phase 1 golden frame
tests/fixtures/phase2-busk.json    # the Phase 2 busking demo, hand-written: 2 spots, 4 pars, 8 playbacks, a nanoKONTROL2
tests/fixtures/phase3-build.busk   # the Phase 3 build: a busking show from console commands only
tests/fixtures/phase4-song.busk    # the Phase 4 song: a tracking stack and a BPM chase on that show
tests/fixtures/phase5-effects.busk # the Phase 5 effects: a circle, a pulse, a wave and a colour cycle on it
tests/fixtures/phase6-surfaces.busk # the Phase 6 surfaces: a second page, a phone, LEDs on that show
tests/fixtures/phase7-safety.busk  # the Phase 7 safety show: limits, park, a strobe cap, panic on that show
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
tests/api_consumer.py        # a consumer of the public API, type-checked by `mypy --strict` (Phase 8)
tests/golden/public_api.json # the public API's signatures and fields: every change is a reviewed diff
tests/golden/cli/            # the CLI transcripts: output and exit codes, byte for byte (Phase 8)
tests/golden/                # the shows and DMX frames of the Phase 3 build, the Phase 4 song, the Phase 5 effects, the Phase 6 surfaces and the Phase 7 safety show
```
