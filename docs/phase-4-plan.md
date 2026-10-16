# Phase 4 — Time: implementation plan

> Source spec: `busking-console-architecture-python.md` (§22, Phase 4; §5.11, §5.13, §5.18, §6.3–§6.4, §7, §8.2, §9, §10.1, §11, §20). Builds on the Phase 0–3 plans and on the code as it stands after Phase 3. §2 names the real modules this plan changes, so no seam-mapping step is needed.

## Context

Phase 3 ends with a console on which an operator can build and busk a show from scratch. But everything in it is static: a playback only ever plays its cue list's first cue, a fade only fades the playback's *presence* (linearly), and the tempo-related parts of the show (chases, speed masters, `TAP`, `BACK`, `GOTO`, curves, per-family timing, follow and wait triggers) are accepted by validation and then listed as ignored.

The spec scopes Phase 4 as *"Fades & curves, cue lists with GO/BACK/GOTO, follow/wait, tracking, chases, speed masters, tap tempo"*. It is done when there is a *"song stack with timed cues and a BPM-locked chase"*. Phase 3 also handed over four items (phase-3-plan §10): the programmer's `fadeTime`, live swaps that fade instead of snapping (§6.4), `SELECT_PLAYBACK` on the current cue, and tracking-aware `RECORD_CUE`.

Four things make this phase harder than its one-line scope suggests:

1. **Fades move from the source to the slot.** Phase 2 fades a whole source's weight with one envelope. A cue transition needs, per slot, a value fade and a presence fade, each with its own timing (in or out, per family, per entry) and curve. This changes the engine's central data structure, `Source`, and the resolver that reads it.
2. **"Latest" stops being per playback.** With tracking, a GO that changes only intensity would, under §8.1's literal rule, give every slot of the playback a new sequence number. A colour bump the operator put on top would then vanish on every GO. The fix (decision 4) makes sequence numbers per slot, which the programmer already has.
3. **Time must stay deterministic.** Today every runtime value is a pure function of the commands and `now`, whatever ticks run in between (`engine/loop.py`). Chases, tempo and auto-GOs are naturally written as integration (`phase += rate · dt`). Integration would lose that property, and it is what makes golden tests possible.
4. **Tempo and chases interact.** A BPM-locked chase must stay on the beat grid, follow tempo changes without jumping, and re-align on taps. §9.4 and §10.1 state these goals but not the rules.

**Done when:**

- Starting from the show that `examples/phase3-build.busk` builds, the script `examples/phase4-song.busk` adds, with console commands only:
  - a speed master;
  - a five-cue tracking song stack with curves, per-family timing, a `wait` cue, a `follow` cue and a release;
  - a four-step chase on the washes, BPM-locked to the speed master;
  - page slots and nanoKONTROL2 bindings for GO, BACK, release, tap and the speed multiplier.

  `busk run` on the result plays the song from the controller while the chase runs on the beat.
- `test_song_stack.py` reproduces this deterministically. It checks:
  - the saved show matches a golden JSON file;
  - logical values at the checkpoints of §5.15 match values computed by hand, and DMX frames match golden bytes;
  - the `wait` and `follow` cues fire at their exact times;
  - `GOTO` into the stack gives the same frame as stepping through it;
  - the chase steps on the 120 BPM grid, and after four taps on the 128 BPM grid aligned to the last tap;
  - frames are byte-identical whether the engine ticks at 100 Hz or on an irregular schedule.
- The §7.8 golden test and every Phase 2–3 test still pass. The only exceptions are tests that asserted a snap on a live edit of a cue with a non-zero fade, which now assert the fade (§5.10).
- On the §19 reference rig, a busking tick with 60 playbacks all mid-transition stays at p99 < 10 ms. The numbers are recorded against §19's 4 ms target.
- All acceptance tests in this plan pass.

---

## 1. Scope

| In Phase 4 | Deferred (to) |
|---|---|
| Fades per slot: value and presence fades, cue `fadeIn`/`fadeOut`/`delayIn`/`delayOut`, `perFamily`, per-entry `timing`, all six curves and Bézier (§5.9) | — |
| Cue lists: `GO`, `BACK`, `GOTO`, `wrap`, `releaseAtEnd`, `follow` and `wait` triggers | `goto` *buttons*: they need a cue-number entry, which the Phase 6 UI provides |
| Tracking (§9.3) with `block` and `releases`, compiled into tracked states | — |
| Chases (§9.4): Hz and BPM rates, crossfade, the four directions, GO/BACK/GOTO on a running chase | — |
| Speed masters: BPM, beat grid, tap tempo (§11.3), multiplier steps, the new `SET_BPM` command | MIDI clock and Ableton Link (§11.3 "later") |
| `rate` faders (§8.2) | `crossfade` faders (Phase 6, see decision 13). `size` faders (Phase 5) |
| Programmer `fadeTime` (new `PROGRAMMER_FADE` command): value changes, clears and blind switches fade | The blind preview resolve (Phase 6) |
| Live swaps fade to the edited values with the cue's timing (§6.4); a running playback is re-pointed by `CueId` | — |
| `SELECT_PLAYBACK` on the current cue; tracking-aware `RECORD_CUE` | Recording `releases` from the programmer: they are authored with the console's `cue … release` |
| Console grammar for all of the above; snapshot and status line show cues and tempo | — |
| `TAP` and speed-master bindings; `back` buttons | — |
| | Effects, effect `rate`/`size`, size and group masters, the fade-time master (Phase 5). Colour-wheel hysteresis stays with colour → wheel matching, which no phase has scheduled yet |

---

## 2. Baseline from Phase 3

These are the modules this plan changes, as they are now.

| Area | Now | Phase 4 change |
|---|---|---|
| `engine/fades.py` | `Envelope`: a linear scalar ramp, pure in `now` | Gains a curve. Gains `ContributionSet`, the per-slot fades (§5.3) |
| `engine/playback_runtime.py` | `PlaybackRuntime`: a *main* and a *flash* `Source`, `env` (activation and release) and `ltpEnv` (threshold latch); `Playbacks`: runtimes, `seqCounter`, `live`, exclusivity. Plays `playback.cue`, the first cue | Main becomes a `ContributionSet`; `env` keeps only release; sequences and chases (§5.5–§5.7) |
| `engine/contributions.py` | `Source`: lanes and values as arrays (HTP / LTP / snap groups), scalar weights; `gather` sorts by `(priority, seq)` | Per-lane weights, per-lane snap thresholds, sequence runs (§5.4) |
| `engine/resolver.py` | LTP layer stack and HTP bands; scalar weight per source | Per-lane weights and thresholds |
| `engine/install.py` | `Install`, `ProgrammerFrame`, `ProgrammerRuntime`, which splits the programmer by sequence runs; `remap_lanes` | The programmer becomes a `ContributionSet` contributor; its run splitting moves into `contributions.py` |
| `engine/loop.py` | Stage 1 drains commands and installs; stages 3–4 call `Playbacks.update` | Due events are fired before commands; speed masters; new commands (§5.9) |
| `engine/masters.py` | Grand master and blackout | Speed masters and tap tempo (§5.8) |
| `compiler/cues.py` | `CompiledCue` holds the cue's own values, with `SnapGroup`s; `fadeOut`/`delayOut` stored but unused | Per-lane snap thresholds; holds the *tracked* state and per-slot timing (§5.2) |
| `compiler/playbacks.py` | `CompiledPlayback.cue` (first cue), `cueCount`; `CompiledMaster` | `CompiledCueList`, `CompiledChase`; speed fields on masters |
| `compiler/compile.py` | `CompiledShow.cueLists: Mapping[id, tuple[CompiledCue, …]]`; identity-memoised recompile | Maps to `CompiledCueList`; the memo is unchanged |
| `compiler/limitations.py` | Lists multi-cue lists, chases, curves, timing, `back`/`goto`, `rate`/`crossfade` faders, `tap`, speed masters | Most of the list goes (§5.14) |
| `commands/bus.py` | `ENGINE_COMMANDS`; `ARRIVES_IN` rejects `BACK`, `GOTO` and `TAP` as Phase 4 | Accepts them, plus `SET_BPM` and `SET_MASTER` on speed masters |
| `session/` | `SELECT_PLAYBACK` uses `playback.cue.targets`; `Programmer` has no fade time | Current cue from the engine snapshot; `fadeTime` |
| `commands/record.py` | `RECORD_CUE` stores every value; warns that only cue 1 plays | Tracking-aware; the warning goes |
| `console/parser.py` | `go N`, `release N`, `fader`, `gm`, `blackout`; `cue L/C <prop> <json>` | §5.13 grammar |
| Tests | `harness.Harness` (scripted commands on a `FakeClock`), `session_harness.Live`, `reference_resolver.py` (the §7.7 oracle), `test_perf.py` (`time_ticks`, `busking_benchmark_rig`) | Extended (§7) |

**Benchmark baseline (README):** a busking tick on the reference rig with 60 playbacks all mid-fade takes 0.92 ms p99, 0.57 ms of which is the resolver. On Appendix A it takes 0.056 ms p99.

---

## 3. Decisions and assumptions

1. **Every runtime value is a pure function of time, rebased only at events.**
   - Fades, chase positions and beat counts are piecewise-linear or curved functions of `now`. Their parameters change only at *events*: commands, taps, auto-GOs and chase step boundaries. No state is integrated with `dt`.
   - "Accumulated phase" (§9.4, §10.1) is the same thing written differently: when a rate changes, the position is *rebased* (`p0 := p(now)`, `t0 := now`), so the position never jumps. BPM chases re-align to the beat grid instead, which can move them forward within a step but never back across one (§5.7).
   - Events happen at exact times, which are computed, not sampled at ticks. An auto-GO due at 18.000 s starts its fade at 18.000 s even if it is processed on the tick at 18.004 s.
   - The engine's current guarantee holds: frames depend on commands and `now`, never on the tick schedule. §11.2's `dt` clamp is not needed, because nothing integrates. After a stall, fades and chases are where they would have been.
2. **Due events fire before commands.** Stage 1 first fires every auto-GO and chase step due at or before `now`, then applies the queued commands at `now`. Stage 3 fires any event that those commands made due at `now`. A command therefore always sees the state it would see on any tick schedule. This refines §4.2's order without changing it: the events belong to the interval before `now`.
3. **Fades are per slot, vectorised per source.** §5.18's `ContributionState` exists for every slot of a source, but stored as arrays over the source's lanes (§5.3).
   - Each lane belongs to one *timing group*: `FadeState(start, delay, duration, curve)`. One GO creates a handful of groups: in, out, per family, per entry.
   - Per tick, the engine evaluates each group once, as a Python scalar, and then gathers the results per lane with numpy.
   - A slot's lanes always share their group, presence and sequence number. Change detection is per slot.
4. **Sequence numbers are per slot.** "Latest" (§8.1) applies to what an action *changes*:
   - **Activation and re-assert** (trigger, toggle, `autoStart`, a GO that lands on the current cue) give every slot the fresh number.
   - **A manual GO, BACK or GOTO** gives the fresh number only to slots it brings in or changes the value of. Unchanged and outgoing slots keep theirs.
   - **Automatic advances** (follow and wait auto-GOs, chase steps) and **live edits** take no fresh number. A slot entering the source without a number gets the playback's latest activation number.

   As a result, a GO that changes only intensity leaves a newer colour bump on top, and a chase never takes a colour back from a bump at each step. The programmer already works this way (Phase 3, `Change.written`), and its run splitting becomes the general mechanism (§5.4).
5. **Unchanged slots keep their running fade.** On a GO, a slot whose target (value and presence) is the same as in the running transition continues its fade untouched. Only slots the GO changes start new fades, from their current interpolated values. Otherwise a 0-s GO halfway through a 10-s pan fade would make the pan jump to its target. §9.1 asks for "no jumps" and follows Eos-style tracking.
6. **Timing comes from the destination cue.** This applies to GO, BACK (§8.1: "with its timing"), GOTO, and automatic advances. For each slot:
   - **Set by an entry of the destination cue:** the entry's `timing` fields; any field the entry leaves out comes from the next rule.
   - **Otherwise:** `perFamily[family]` if the cue has it. If not, intensity rising uses `fadeIn`/`delayIn` and intensity falling uses `fadeOut`/`delayOut`; every other family uses `fadeIn`/`delayIn`.
   - **Curve:** the entry's, then the family's, then the cue's.
   - **Rising or falling:** current effective intensity (value × presence) compared with the target.

   Slots that leave (in the old state, not the new) use the destination cue's out or family timing.
7. **Curves.**
   - `linear`: f = t.
   - `easeIn`: t².
   - `easeOut`: t(2 − t).
   - `easeInOut`: t²(3 − 2t), the smoothstep §5.9 specifies.
   - `snapStart`: 1 as soon as the fade starts, after its delay.
   - `snapEnd`: 0 until the end, then 1.
   - `bezier`: CSS cubic-bezier with fixed end points (0,0) and (1,1). Validation requires all four control values in 0..1, so f stays in 0..1. That keeps every interpolation convex, so the compile-time clamp (phase-2-plan decision 8) still holds.

   Values and presence use the same f. Snap lanes switch value when f reaches their `snapAt` threshold.
8. **Release stays a playback-level fade.** `releaseTime` (or the command's `time`) fades the whole playback from where it is, as in Phase 2. Cue `fadeOut` applies only inside transitions. Re-activating a releasing playback folds the release level into its slots' presences, so nothing jumps.
9. **Sequences.**
   - **GO.** On a playback that is not active, it activates at the first cue. On an active one, it moves to the next cue. At the last cue it wraps (`wrap`), or releases (`releaseAtEnd`), or else re-asserts, which is Phase 2's single-cue behaviour.
   - **BACK.** Moves to the previous cue, or wraps to the last one. At the first cue without `wrap`, and on an idle playback, it does nothing.
   - **GOTO.** Activates or moves to the given cue. A GOTO to the current cue re-asserts.
   - **TRIGGER, TOGGLE and `autoStart`** activate at the first cue.
   - **Auto-GO scheduling.** After a forward move (activation, GO, GOTO or an auto-GO), the *next* cue's trigger is scheduled:
     - `wait d` at the transition's start + d;
     - `follow d` at its completion + d, where completion is the latest end among the fades this transition started.
   - **Cancelling.** A manual GO, BACK, GOTO or release cancels the scheduled auto-GO. BACK schedules nothing, or a `follow 0` cue would undo every BACK at once.
   - **Runaway loops.** At most one lap of auto-GOs (one per cue) fires per playback per tick, so a wrapped list of zero-time cues cannot hang the engine.
10. **Chases.**
    - A chase's *position* is a function of time (Hz) or of its speed master's beat count (BPM). A step boundary occurs each time the position crosses an integer.
    - At each boundary the chase moves to the next cue in its direction, with one fade for every slot: delay 0, duration `crossfade` × the step length at that moment, and the destination cue's curve. All other cue timing and triggers are ignored in chase mode.
    - The first step fades in the same way. Chases always loop: `wrap` and `releaseAtEnd` do not apply.
    - GO and BACK step once immediately without moving the boundary grid. GOTO jumps to a cue the same way.
    - Directions: `forward`; `reverse` starts at the last cue; `bounce` reverses at both ends; `random` never repeats a cue. Its sequence is seeded from the playback id and the activation number, so it is deterministic.
11. **Tempo.**
    - **Beat count.** A speed master keeps a beat count `beats(t)`, linear between events, starting at its `defaultBpm`.
    - **`TAP`** (§11.3, from the second tap of a run): the master keeps its last 8 taps, takes their intervals, drops those more than 25 % from the median and averages the rest. A gap over 2 s starts a new run. Every tap, including the first of a run, moves the beat phase to the nearest whole beat.
    - **`SET_BPM`** changes the tempo and keeps the phase.
    - **Level.** A speed master's *level* selects one of its `multiplierSteps`: step `round(level × (n − 1))`. It starts at `initialLevel` if the show has one, otherwise at the step whose value is 1.
    - **BPM chase rate.** Steps per beat = `rate.multiplier` × the master's step multiplier × the rate fader (decision 12).
    - **Activation.** A BPM chase starts aligned to its master's beat grid. Its first boundary is the first grid point at least half a step away.
    - **Taps and rate changes.** On every tap of its master, and whenever its own rate changes, a locked chase re-aligns to the beat grid, but never moves back to an earlier step. With a steady tempo the correction is tiny.
12. **`rate` faders** scale a chase's rate by 4^(2·level − 1): ×¼ at 0, ×1 at 0.5, ×4 at 1 (§8.2). On a BPM chase the factor is rounded to a power of two, so the chase stays on the beat grid. A `rate` fader starts at 0.5, not 0 (phase-2-plan decision 6), so an untouched rate fader means ×1. `autoStart` and `autoRelease` still apply only to `master` faders.
13. **`crossfade` faders move to Phase 6.** Their semantics depend on decisions that belong with soft takeover and pickup: which end the fader rests at, what a GO button does while the fader is mid-travel, how the fader takes over again. The transition model is ready for them: a fade evaluated from a fader's progress instead of from the clock. The limitation report and the spec-gap list say so.
14. **Live edits fade.** Installing a recompiled show retargets every running playback to its cue's new state, with that cue's timing (decision 6). For a chase, the step crossfade is used.
    - No sequence numbers are taken: an edit does not reorder the stack.
    - Running playbacks are re-pointed by `CueId`. When their cue is gone, they move to the cue that now follows its number, or to the last cue.
    - A pending auto-GO is re-derived from the edited next cue.
    - Programmer changes fade over the programmer's `fadeTime`, with a linear curve, and so does a preset edited under a programmer reference.
15. **New commands, all backward compatible** (`schemaVersion` stays 1):
    - `SET_BPM {masterId, bpm}`: performance class.
    - `PROGRAMMER_FADE {time}`: programmer class. Like `BLIND`, it is a mode and is not undone.

    The bus now accepts `BACK`, `GOTO`, `TAP`, `SET_BPM` and `SET_MASTER` on speed masters.
16. **The session reads the engine snapshot** for `SELECT_PLAYBACK`. The snapshot carries each playback's current cue; it may be one tick old, which is fine for a button. The session gets the snapshot through an injected callable, so it still never touches the engine.
17. **Recording into a tracking list stores changes only.**
    - A programmer value equal to what the cue would inherit is not stored. Equal means the same preset reference, or literals that encode to the same lanes.
    - What the cue would inherit is the tracked state of the cue before it, minus the new cue's own `releases`; a `block` cue inherits nothing.
    - With `merge`, the cue's own entry for such a slot is still removed, by the existing restriction, so the slot tracks the inherited value.
    - The message counts the omitted values.
18. **No new dependencies.**

---

## 4. Project layout (new and changed files)

```
src/busk/
  engine/
    curves.py            # the §5.9 curves and Bézier (new)
    fades.py             # Envelope gains a curve; FadeState, ContributionSet (changed)
    contributions.py     # Source with per-lane weights/thresholds; Contributor, sequence runs, gather (changed)
    resolver.py          # per-lane weights and snap thresholds (changed)
    cue_engine.py        # next/previous cue, triggers, auto-GO scheduling (new)
    chase.py             # ChaseClock: position, boundaries, re-alignment; direction stepping (new)
    masters.py           # + SpeedMasterRuntime, tap tempo (changed)
    playback_runtime.py  # main = ContributionSet; sequences and chases (changed)
    install.py           # programmer runtime as a contributor; lane remaps for every runtime (changed)
    snapshot.py          # + cue, next cue, speed masters (changed)
    loop.py              # stage 1 fires due events first; new commands (changed)
  compiler/
    tracking.py          # tracked states (§9.3) and per-slot timing (new)
    cues.py              # CompiledCue: tracked arrays, per-lane thresholds and timing (changed)
    playbacks.py         # CompiledCueList, CompiledChase, speed fields on CompiledMaster (changed)
    slots.py             # + SlotTable.laneFamily (changed)
    limitations.py       # (changed)
  model/validate.py      # rate, BPM, Bézier, multiplier-step rules; tracking warnings (changed)
  commands/
    types.py             # + SetBpmCmd, ProgrammerFadeCmd (changed)
    classes.py bus.py    # (changed)
    record.py            # tracking-aware RECORD_CUE (changed)
  session/
    programmer.py frame.py session.py   # fadeTime; SELECT_PLAYBACK on the current cue (changed)
  persistence/autosave.py # + fadeTime, speed-master BPMs (changed)
  io/bindings.py          # back buttons, tap, speed-master faders (changed)
  console/parser.py console.py          # §5.13 grammar, `list cues`, `list masters` (changed)
  cli.py                  # status line, "Ignored in Phase 4:" (changed)
examples/phase4-song.busk
tests/golden/phase4_song_show.json  tests/golden/phase4_frames.json
tests/…                   # see §7
```

The engine still never imports `session/`, and `compiler/` never imports `engine/`.

---

## 5. Component design

### 5.1 Curves and envelopes (`engine/curves.py`, `engine/fades.py`)

```python
type Curve = Callable[[float], float]     # f(t), t ∈ [0, 1] → [0, 1]; f(0) = 0, f(1) = 1

def curve_of(spec: FadeCurve) -> Curve: ...   # memoised per spec; bezier specs by their tuple
```

| Curve | f(t) on 0 < t < 1 |
|---|---|
| `linear` | t |
| `easeIn` | t² |
| `easeOut` | t(2 − t) |
| `easeInOut` | t²(3 − 2t) |
| `snapStart` | 1 |
| `snapEnd` | 0 |
| `bezier (x1, y1, x2, y2)` | y(s), where s solves x(s) = t. Newton steps from s = t; bisection if the slope is near 0; tolerance 1e-7 |

The fade around a curve is evaluated as `fade_fraction(elapsed, duration, curve)`:

- `elapsed < 0` (still in its delay) gives 0;
- `elapsed ≥ duration` gives exactly 1, including when `duration = 0`, which is a step at the end of the delay;
- anything in between gives `curve(elapsed / duration)`.

`Envelope` keeps its pure-in-time contract and gains a `curve` field (default `linear`). Release envelopes stay linear. The threshold-mode LTP gate uses the current cue's LTP in-timing curve.

### 5.2 Compiled cue lists (`compiler/tracking.py`, `compiler/cues.py`, `compiler/playbacks.py`)

```python
@dataclass(frozen=True, kw_only=True)
class SlotTiming:
    fade: float
    delay: float
    curve: FadeCurve

@dataclass(frozen=True, kw_only=True)
class CompiledCue:
    id: CueId
    number: str
    name: str
    # the tracked state: what the playback holds at this cue (sorted, read-only)
    htpPos: NDArray[np.intp];    htpValues: NDArray[np.float64]
    ltpLanes: NDArray[np.intp];  ltpValues: NDArray[np.float64]
    snapLanes: NDArray[np.intp]; snapValues: NDArray[np.float64]; snapThresholds: NDArray[np.float64]
    # timing, as indices into `timings`
    timings: tuple[SlotTiming, ...]
    htpIn: NDArray[np.int16]; htpOut: NDArray[np.int16]       # per HTP position
    ltpTiming: NDArray[np.int16]; snapTiming: NDArray[np.int16]
    leave: NDArray[np.int16]          # per family code: timing for slots that leave
    trigger: Literal["go", "follow", "wait"]
    triggerDelay: float
    targets: tuple[TargetRef, ...]    # the tracked state's targets (SELECT_PLAYBACK)

@dataclass(frozen=True, kw_only=True)
class CompiledChase:
    rate: Literal["hz", "bpm"]
    hz: float                         # steps per second (hz)
    masterId: MasterId | None         # bpm
    multiplier: float                 # steps per beat (bpm)
    direction: Literal["forward", "reverse", "bounce", "random"]
    crossfade: float

@dataclass(frozen=True, kw_only=True)
class CompiledCueList:
    id: CueListId
    mode: Literal["sequence", "chase"]
    tracking: bool
    wrap: bool
    releaseAtEnd: bool
    chase: CompiledChase | None       # set whenever the list has chase settings
    cues: tuple[CompiledCue, ...]
    byNumber: Mapping[tuple[int, ...], int]   # cue number key → index (GOTO)
    byId: Mapping[CueId, int]
```

**Snap groups become per-lane thresholds.**
- `SnapGroup` goes. Each snap lane carries its own threshold: `SNAP_START` (start), 0.5 (middle) or 1 (end). Colour extras snap at middle, as before.
- With per-lane presence, the resolver needs a per-lane comparison anyway (§5.4). One snap partition also keeps `ContributionSet` to three partitions.
- `cue_from_values` builds the new arrays. The programmer frame (`session/frame.py`) and the tests that build sources call it unchanged.

**Tracked states** (`compiler/tracking.py`). The compiler already resolves each cue's own entries to `slot → lanes`; tracking works on those maps, never on show data.

```python
own[n]     = slot → (lanes, timing of the entry that set it)   # last entry wins (phase-2 decision 9)
state[0]   = own[0]
state[n]   = own[n]                                              if not tracking or cue n is a block
           = (state[n-1] − released(n)) | own[n]                 otherwise
```

- The cue's own values win over its own `releases`. This is a deliberate deviation from §9.3, which applies `without` after the merge (see §9).
- `released(n)` expands each `CueRelease`: its targets, then its attributes, or every busked attribute of each target for `"all"`. Targets without a given slot are skipped.
- Each state is then encoded with `cue_from_values`. Its timing index arrays follow decision 6:
  - slots in `own[n]` take their entry's override, layered over the family and cue defaults;
  - tracked-in slots take the family and cue defaults.

  Distinct `SlotTiming`s are interned per cue, so `timings` stays small.
- `targets` lists the cue's own entry targets first, in entry order, then the tracked targets in the previous cue's `targets` order, de-duplicated.

**Compile cost.** States are O(cues × tracked slots) in Python, once per edit of the list. Identity memoisation (phase-3-plan §5.11) already recompiles per cue list, and a list's states depend only on its own cues and the groups and presets they read. The memo key does not change. Step 18 re-measures edit latency.

**`SlotTable.laneFamily`.** An `int8` family code per lane, in registry family order. It is computed once with the slot table. The engine uses it to look up `cue.leave` for slots that leave.

**`CompiledPlayback`** replaces `cue` and `cueCount` with `cueList: CompiledCueList`. `releaseAtEnd` moves into the list. **`CompiledMaster`** gains `defaultBpm`, `tap` and `multiplierSteps` (set for speed masters only).

### 5.3 Per-slot fades (`engine/fades.py`: `ContributionSet`)

§5.18's per-slot `ContributionState` (from and to values, from and to presence, `FadeState`), stored as arrays over one source's lanes.

```python
@dataclass(slots=True)
class FadeState:                      # one timing group (§5.18)
    start: float
    delay: float
    duration: float
    curve: Curve

class Partition:                      # HTP positions, LTP lanes or snap lanes, sorted
    index: NDArray[np.intp]
    fromValue: NDArray[np.float64];  toValue: NDArray[np.float64]
    fromWeight: NDArray[np.float64]; toWeight: NDArray[np.float64]
    group: NDArray[np.intp]           # timing group per lane; 0 = settled
    seq: NDArray[np.int64]            # LTP and snap only
    threshold: NDArray[np.float64]    # snap only
    value: NDArray[np.float64]; weight: NDArray[np.float64]   # evaluated each tick, preallocated

class ContributionSet:
    htp: Partition; ltp: Partition; snap: Partition
    groups: list[FadeState]           # groups[0] is the settled group: f = 1
    def evaluate(self, now: float) -> None: ...
    def retarget(self, now: float, target: Target, timing: TimingRule,
                 fresh: SeqRule, scale: float = 1.0) -> float: ...   # returns the completion time
    def remap(self, laneMap: NDArray[np.intp], posMap: NDArray[np.intp]) -> None: ...
    def clear(self) -> None: ...
    settled: bool                     # every group has finished: arrays are static
```

**`evaluate(now)`** fills each partition's `value` and `weight` arrays:

1. One Python scalar per group: `f[g] = fade_fraction(now − start − delay, duration, curve)`.
2. `fl = f[group]`, one `np.take` per partition.
3. HTP and LTP: `value = from + (to − from)·fl`.
4. Snap: `value = where(fl ≥ threshold, to, from)`.
5. All partitions: `weight = fromWeight + (toWeight − fromWeight)·fl`.

When every group has finished, the set **compacts**:
- `from := to` and `fromWeight := toWeight`;
- lanes whose `toWeight = 0` are dropped;
- every group becomes 0;
- `settled` is set.

From then until the next retarget, `evaluate` does nothing and the source's arrays are static, with all weights 1. Steady-state busking is Phase 2's fast path again.

**`retarget(now, target, …)`** (decisions 3–6), per partition, all vectorised:

1. Evaluate the current `(v, w)` at `now`. With `scale` (re-activating a releasing playback, decision 8), `w := w · scale`.
2. Take the union of the current lanes and the target's lanes. A lane not currently present gets `v := target value` and `w := 0`.
3. Targets per lane:
   - lanes in the target: `(target value, 1)`;
   - lanes not in the target: `(v, 0)`, i.e. hold the value and fade out.
4. **Changed** (per slot): the target differs from the running `(toValue, toWeight)`, or the lane is new. `NaN` equals `NaN`, so extras in "derive" mode are not changed forever. Lane-level flags are reduced per slot through `SlotTable.laneSlot`.
5. **Unchanged lanes** keep their from and to values and their group.
6. **Changed lanes** get `from := (v, w)`, `to := target`, and a new group from the `TimingRule`:
   - for a cue transition: the cue's in, out or leave timing per decision 6;
   - for a chase step or the programmer: one uniform `FadeState`.

   Groups are interned by `(delay, duration, curve)`. All new groups start at `now`.
7. **Sequence numbers** per `SeqRule` (decision 4):

   | Rule | Changed lanes that enter or change value | Every other lane |
   |---|---|---|
   | `fresh(n)` | get `n` | keep their number (lanes that leave included) |
   | `all(n)` | get `n` | get `n` |
   | `keep(n)` | keep their number; a lane without one gets `n` | keep their number |
   | `mask(n, slots)` (programmer) | lanes of the given slots get `n` | keep their number; a lane without one gets `n` |

   `fresh` is used for manual moves, `all` for activation and re-assert, `keep` for automatic advances and live edits, and `mask` for the programmer's touched slots.
8. Drop lanes with `w = 0` whose target presence is 0 (gone, not coming back).
9. Drop groups no lane uses. Settle groups that have finished.
10. Return `max(start + delay + duration)` over the new groups. The cue engine uses it as the completion time.

Retargeting runs on the engine thread at command time: a few numpy set operations over the source's lanes, tens of µs for a few thousand lanes.

**Invariants**, each a property test (§7):
- `retarget` never changes `(v, w)` at `now`: no jumps.
- `evaluate` is a pure function of `now` between retargets.
- Values stay between their from and to values and in range, and presence stays in 0..1.
- After the completion time, the state equals the target.
- A slot's lanes share their group and their sequence number.

### 5.4 Sources, sequence runs and the resolver (`engine/contributions.py`, `engine/resolver.py`)

```python
@dataclass(slots=True, kw_only=True)
class Source:                             # what the resolver reads; one per sequence run
    sourceId: str
    priority: int
    seq: int                              # sort key: the newest number in the run
    htpPos: NDArray[np.intp];    htpValues: NDArray[np.float64];  htpWeights: NDArray[np.float64] | None
    ltpLanes: NDArray[np.intp];  ltpValues: NDArray[np.float64];  ltpWeights: NDArray[np.float64] | None
    snapLanes: NDArray[np.intp]; snapValues: NDArray[np.float64]; snapThresholds: NDArray[np.float64]
    snapWeights: NDArray[np.float64] | None
    htpWeight: float = 0.0                # scalar multipliers: release envelope, LTP gate, followFader
    intensityScale: float = 1.0
    ltpWeight: float = 0.0

class Contributor(Protocol):              # a playback's main source, its flash, the programmer
    priority: int
    seqs: tuple[int, ...]                 # distinct sequence numbers of its LTP and snap lanes, ascending
    present: bool
    def sources(self, boundaries: tuple[int, ...]) -> Sequence[Source]: ...
```

**The resolver** composites sources as now. A per-lane weight array, when present, multiplies the scalar weight:

- **LTP:** `frame[lanes] = below + (values − below)·w`. The exact-replacement shortcut is kept for a scalar weight ≥ 1 with no array.
- **Snap:** `m = w ≥ thresholds`, then `frame[lanes[m]] = values[m]`.
- **HTP:** `presence[pos] = max(presence[pos], w)` and `maximum[pos] = max(maximum[pos], values·scale·w)`.

Phase 2 planned this broadcasting (phase-2-plan §10). A source whose weights are all zero is a no-op in every branch.

**Sequence runs.** All sequence numbers come from the one global counter, so no two contributors share a number.

1. For each band, `gather` collects the `seqs` of every present contributor in it.
2. Each contributor gets as `boundaries` the numbers of the *other* contributors in its band that fall strictly between its own lowest and highest number.
3. A contributor with no boundaries returns one source, sorted at its newest number. That is the usual case.
4. Otherwise it returns one source per run of its numbers between consecutive boundaries, each sorted at the newest number in the run. Its HTP positions go with its newest run; HTP ignores order within a band.

This is `ProgrammerRuntime._build` generalised. It is exact: a slot's contributions end up in `(priority, seq)` order, which the per-slot oracle checks.

- Runs are cached per contributor, keyed by `(its version, boundaries)`.
- They are rebuilt only when the contributor is retargeted or the band's other numbers change, which happens only at commands.
- Per tick, a split contributor fills its runs' arrays with `np.take` from its evaluated partitions. An unsplit one hands out its partition arrays directly.

**The oracle** (`tests/reference_resolver.py`) takes per-slot contributions with their own sequence number and weight, and per-lane snap thresholds. It stays the slow, literal §7.7 transcription.

### 5.5 Playback runtime (`engine/playback_runtime.py`)

A playback is still up to two contributors, *main* and *flash* (phase-2-plan decision 2):

| | Phase 3 | Phase 4 |
|---|---|---|
| main values | the first cue's static arrays | a `ContributionSet`: the current cue's tracked state, fading |
| main sequence numbers | one `activationSeq` | per lane (decision 4); `activationSeq` is the newest one, used for lanes that enter on automatic moves |
| `env` | activation fade in, release fade out | release only: 1 while active; on release, from 1 to 0 over the release time |
| `ltpEnv` | threshold-mode LTP latch | unchanged: a scalar gate on LTP and snap lanes; it fades in with the current cue's LTP in-timing and curve |
| flash | the first cue, full weight, its own number | the cue main is at or going to (when idle, the first cue); static arrays, full weight, its own number |

Per tick, main's weights are `ContributionSet` weights × the scalars:
- HTP: × `env`;
- LTP and snap: × `env` × `ltpEnv` × (`faderLevel` in `followFader` mode).

`intensityScale` is the fader level for `master` faders and 1 for any other fader, as before.

**Runtime state** (§5.18, renamed where it differs):

```python
class PlaybackRuntime:
    state: PlaybackState                  # idle | active | releasing
    faderLevel: float                     # 0, or 0.5 for `rate` faders (decision 12)
    cue: int                              # index into cueList.cues; −1 when idle
    contributions: ContributionSet        # main
    env: Envelope; ltpEnv: Envelope; ltpLatched: bool
    activationSeq: int; flashButton: bool; flashSeq: int
    started: float; completes: float      # the current cue's transition (follow/wait)
    auto: float | None                    # the scheduled auto-GO time
    chase: ChaseRuntime | None            # chase-mode lists (§5.7)
```

**State machine** (Phase 2's events, plus the new ones):

| Event | Idle or releasing | Active |
|---|---|---|
| `TRIGGER`, `autoStart` | activate at cue 0 | re-assert (`TRIGGER` only) |
| `TOGGLE` | activate at cue 0 | release |
| `GO` | activate at cue 0 | sequence: next cue, wrap, release or re-assert (decision 9); chase: step forward |
| `BACK` | nothing | sequence: previous cue or wrap, else nothing; chase: step back |
| `GOTO c` | activate at `c` | sequence: move to `c` (re-assert if `c` is current); chase: jump to `c` |
| `RELEASE`, `autoRelease` | — | release (cancels the auto-GO) |
| auto-GO due | — | next cue, with `keep` numbers |
| chase boundary | — (a releasing chase keeps stepping) | next step, with `keep` numbers |

The actions behind the table:

- **Activate at cue `c`.**
  1. Take a fresh number and fold `env`'s current value into the slots as the retarget `scale`.
  2. Set `env := 1` and latch LTP per Phase 2's threshold rule.
  3. Retarget to `c` with the `all` rule.
  4. Apply exclusivity.
  5. Schedule the next auto-GO.
- **Move** (GO, BACK, GOTO): take a fresh number, retarget with the `fresh` rule, cancel the auto-GO, then schedule a new one unless the move was a BACK.
- **Re-assert:** take a fresh number and retarget to the current cue with the `all` rule. Nothing changes value, so this only renumbers.
- **Release:** as in Phase 2. When the release finishes, the playback goes idle: `clear()`, `cue := −1`.

`Playbacks` keeps the live set, `seqCounter` and the exclusivity index. It gains `advance(now)`: each live runtime fires its due events in time order (§5.6, §5.7), then evaluates its fades. The loop calls `advance` at stage 1, before the commands, and at stage 3 (decision 2).

### 5.6 Cue engine (`engine/cue_engine.py`)

Pure functions over a `CompiledCueList`, so the sequence rules can be tested without an engine:

```python
def next_cue(cues: CompiledCueList, current: int) -> int | Literal["release", "reassert"]: ...
def previous_cue(cues: CompiledCueList, current: int) -> int | None: ...
def schedule(cues: CompiledCueList, current: int, started: float, completes: float) -> float | None:
    """When the next cue fires by itself: wait → started + d, follow → completes + d; None for go,
    or when there is no next cue (the last cue without wrap)."""
```

**Firing auto-GOs.** `PlaybackRuntime.fire(until)` runs a loop:
- while `auto ≤ until`: GO to the next cue *at time `auto`* (the retarget, the `started` time and the next schedule all use `auto`, not the tick time);
- stop after `len(cues)` firings in one call (decision 9).

A `follow` completion time comes from the retarget's return value. A transition that changes nothing completes at its start.

**Live edits.**
- The runtime is re-pointed by `CueId` (decision 14) and retargeted with the `keep` rule.
- `auto` is re-derived with `schedule()` from the kept `started` and `completes`, unless it has already fired.
- A list whose mode changed keeps its current cue. A list that became a chase gets a chase clock, started as on activation.
- A runtime whose list is now empty is dropped at once (Phase 3).

### 5.7 Chases (`engine/chase.py`)

```python
class ChaseClock:                     # the position p(t), in steps; boundaries at integers
    kind: Literal["hz", "bpm"]
    rate: float                       # hz: steps per second; bpm: steps per beat
    p0: float; t0: float              # hz:  p(t) = p0 + rate · (t − t0)
    b0: float                         # bpm: p(t) = p0 + rate · (beats(t) − b0)
    done: int                         # the last boundary already processed
    def position(self, t: float) -> float: ...
    def boundary_time(self, k: int) -> float: ...   # hz: t0 + (k − p0)/rate;  bpm: master.time_of(b0 + (k − p0)/rate)
    def step_seconds(self) -> float: ...            # 1/rate, or 60 / (bpm · rate)
    def rebase(self, now: float, rate: float) -> None: ...   # hz: p0 := p(now); t0 := now
    def align(self, now: float, rate: float, p_ref: float) -> bool: ...   # bpm; True if it stepped
```

- **Rate.**
  - Hz: `chase.hz` × the rate-fader factor.
  - BPM: `chase.multiplier` × the master's step multiplier × the rate-fader factor rounded to a power of two (decision 12).
  - On an Hz chase, a rate change rebases, so the position is continuous. On a BPM chase it *aligns* (below).
- **Alignment** (BPM). One rule serves activation, taps and rate changes. With `B` the master's beat count at `now`, `m` the chase's steps per beat, `g = min(m, 1)` and `p_ref` a reference position:

  ```
  p0 := m·B + g·round((p_ref − m·B) / g);   b0 := B
  ```

  It picks the position nearest `p_ref` from which the boundaries fall on the beat grid: on beats and their subdivisions for `m ≥ 1`, every `1/m` beats on whole beats for `m < 1`.
  - **Activation:** `p_ref = 0`, and `done := floor(p0 + ½)`. The first boundary is then between half a step and one and a half steps away.
  - **Tap:** `p_ref` is the position *before* the master changes; `B` is its new whole beat count.
  - **Rate change** (the master's step, the rate fader): `p_ref = p(now)`, under the new `m`.

  In both of the last two cases, `p0 := max(p0, floor(p_ref))`, so the chase never goes back a step. If `floor(p0) > done`, the chase steps at `now`.

  Hz chases start with `p0 = 0`, `t0 = now`, `done = 0`.
- **Boundaries.**
  - `ChaseRuntime.fire(until)` processes every boundary `k` in `done + 1 … floor(p(until))`. At `t_k = boundary_time(k)` it moves to the next cue and retargets with the `keep` rule and one uniform fade: delay 0, duration `crossfade × step_seconds()`, the destination cue's curve.
  - At most one lap (n boundaries) per call. Beyond that it jumps to the last boundary, which only happens if the step rate is at least n × the tick rate.
  - `boundary_time` for BPM inverts the master's *current* tempo segment. That is exact because every tempo change happens at a command, and due boundaries fire before commands (decision 2).
- **Cue order.** The cue order is separate from the position: the runtime keeps the current cue `c` and, for `bounce`, a direction.
  - `forward`: `c + 1`, wrapping.
  - `reverse`: `c − 1`, wrapping; it starts at the last cue.
  - `bounce`: reverses at either end; a 1-cue chase stays put.
  - `random`: a draw from the other `n − 1` cues, from `random.Random(seed)` with `seed = crc32(playbackId) · 2³² + activationSeq`.

  GO, BACK and GOTO change `c` and retarget at `now` without touching the position, so the grid stays put (decision 10).

**Worked example** (§5.15). The chase runs ×1 at 120 BPM from t = 60 (beat 120), so `p0 = 0`.

| Event | Beat count | `p_ref` | `p0` | Result |
|---|---|---|---|---|
| Second tap at 70.46875 | 141 | 20.9375 | 21 | Steps on the tap, 0.03 s ahead of the old grid |
| ×2 at t = 80 | 161.333 | 41.333 | 41.667 | No step now; the next boundary is at beat 161.5 (t = 80.078125), then every half beat |

### 5.8 Speed masters and tap tempo (`engine/masters.py`)

```python
class SpeedMasterRuntime:
    bpm: float; level: float; multiplier: float     # multiplier = steps[round(level · (n − 1))]
    T0: float; B0: float                            # beats(t) = B0 + bpm / 60 · (t − T0)
    taps: list[float]                               # the current tap run, ≤ 8
    def beats(self, t: float) -> float: ...
    def time_of(self, beats: float) -> float: ...
    def tap(self, t: float) -> None: ...
    def set_bpm(self, t: float, bpm: float) -> None: ...   # B0 := beats(t); T0 := t
```

**`tap(t)`** follows decision 11:
- A tap more than 2 s after the previous one starts a new run.
- From the second tap of a run on:
  1. Take the intervals of the run's last 8 taps.
  2. Keep those within ±25 % of their median.
  3. Set `bpm = 60 / mean(kept)`, or `60 / last interval` if none are kept.
- In every case, `B0 := round(beats(t))` under the old tempo, then `T0 := t`.

**Lifecycle.**
- Masters start counting at the engine's first tick (`B0 = 0`).
- A master added by a live edit starts at the tick that installs it.
- A master that survives an edit keeps its tempo, phase and level.

**`EngineRuntime`** gains `speed: dict[MasterId, SpeedMasterRuntime]`. Grand-master levels stay in `masterLevels`, and the snapshot's `masterLevels` now also lists speed-master levels, for autosave.

### 5.9 Engine loop and commands (`engine/loop.py`, `commands/`)

| §4.2 stage | Phase 4 |
|---|---|
| 1 | `playbacks.advance(now)` fires due auto-GOs and chase steps (decision 2), then the queue is drained: commands and installs, guarded as before |
| 2 | — Clocks are functions of `now` (decision 1) |
| 3–4 | `playbacks.advance(now)` again (events the commands made due at `now`); finished releases go idle; every unsettled `ContributionSet` is evaluated; the scalar multipliers are set |
| 6–7 | `gather` with sequence runs over the playbacks' and the programmer's contributors, then resolve |
| 9–13 | unchanged |

**Applying commands:**

| Command | Engine |
|---|---|
| `GO` / `BACK` / `GOTO` | `Playbacks.go / back / goto(id, now[, number])` (§5.5) |
| `TAP` | `Playbacks.tap(masterId, now)`: the master's `tap`, then re-alignment of the locked chases (§5.7) |
| `SET_BPM` | locked chases are not touched (their position follows the beat count); `set_bpm` |
| `SET_MASTER` on a speed master | the level and its step change, then the locked chases align to their new rate (§5.7) |
| `SET_FADER` on a `rate` fader | the level changes, then the chase rebases (Hz) or aligns (BPM) |

**Command types** (`commands/types.py`):

```python
class SetBpmCmd(TypedDict):        # performance
    type: Literal["SET_BPM"]
    masterId: MasterId             # a speed master
    bpm: float                     # 0 < bpm ≤ 999

class ProgrammerFadeCmd(TypedDict):   # programmer; a mode: never undone, like BLIND
    type: Literal["PROGRAMMER_FADE"]
    time: Seconds
```

**The bus** (`commands/bus.py`):
- `ENGINE_COMMANDS` gains `BACK`, `GOTO`, `TAP` and `SET_BPM`; `ARRIVES_IN` goes.
- `MASTER_ARRIVES_IN` loses `speed`.
- New checks:
  - `GOTO`: the cue number parses and exists in the playback's list (`no cue 7 in cue list 9`);
  - `TAP`: the master is a speed master and `tap` is true;
  - `SET_BPM`: a speed master and a number in range;
  - `SET_MASTER`: grand or speed masters.

### 5.10 Programmer fades and live swaps (`engine/install.py`, `session/`)

**Programmer.**
- `Programmer` gains `fadeTime: float = 0.0`, a mode like `blind`: kept by undo and restore, and autosaved.
- `ProgrammerFrame` gains `fadeTime`.
- The engine's `ProgrammerRuntime` becomes a contributor at band 100 backed by a `ContributionSet`. Installing a frame retargets it:
  - target: the frame's lanes, or nothing while blind;
  - timing: one uniform linear fade of `fadeTime`;
  - sequence numbers: the `mask` rule over the frame's `touched` slots, with one fresh number for the whole update (Phase 3).
- The contributor stays present while lanes are fading out. So:
  - `CLEAR_PROGRAMMER`, `BLIND on` and undo fade out over `fadeTime`;
  - `BLIND off` fades in, since every slot is touched.
- `PROGRAMMER_FADE` installs nothing. The next frame carries the new time.

**Live swap** (`Engine._swap`):
1. **Lane maps.** When the slot keys changed, one lane map (old lane → new, −1 = gone) and one HTP-position map are built from the remap, vectorised like `remap_lanes`. Lanes of slots whose lane count changed are dropped.
2. **Remap.** Every `ContributionSet` (playbacks, programmer) and every per-lane array is remapped with them. Its groups and sequence numbers are carried along.
3. **Playbacks.** Each playback is rebound and retargeted to its cue's new state per decision 14: the cue's timing (or the step crossfade), the `keep` rule.
4. **Programmer.** The frame that arrives in the same install retargets it with its `fadeTime`.
5. **Chases and masters.** Chase clocks rebase if their rate changed. Speed masters are carried over by id.

The session needs no change for this: it already sends `Install(compiled, remap, frame)`.

**`SELECT_PLAYBACK`.**
- `Session` takes an optional `engine_state: Callable[[], EngineSnapshot | None]`; `busk run` and `session_harness.Live` pass the engine's snapshot.
- The command selects the targets of the playback's current cue from the snapshot (the tracked state's `targets`, §5.2).
- When the playback is idle, or there is no snapshot, it selects the first cue's targets, as in Phase 3.

### 5.11 Snapshot and status line (`engine/snapshot.py`, `cli.py`)

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class PlaybackStatus:                 # + three fields
    ...
    cue: str | None                   # the current cue's number (a chase: its current step); None when idle
    cueName: str | None
    next: str | None                  # what GO goes to; None at the end without wrap

@dataclass(frozen=True, slots=True, kw_only=True)
class SpeedStatus:
    id: MasterId
    name: str
    bpm: float
    multiplier: float
    level: float

# EngineSnapshot gains  speed: tuple[SpeedStatus, ...]
```

- Beat phase is left out on purpose. It changes every tick, and the snapshot is only published on change. A UI can derive the phase from the tempo.
- A chase publishes a snapshot per step, which is cheap.
- The **status line** shows a sequence's cue (`9 Song on 3 Pre`), but for a chase only `on`. Otherwise a running chase would print several lines a second in piped runs.
- It gains the tempo: `Speed 1 128 BPM ×2`.
- Fader levels are shown for `master` and `temp` faders only, since a `rate` fader at 0.5 is its resting state.

### 5.12 Recording and autosave (`commands/record.py`, `persistence/autosave.py`)

**Tracking-aware `RECORD_CUE`** (decision 17). A helper computes the source each slot inherits at the cue position, from show data (not compiled lanes), on the session thread:

```python
def inherited(state: ShowState, cue_list: CueList, position: int, releases: Sequence[CueRelease]) -> dict[SlotKey, ProgSource]
```

- It walks cues `0 … position − 1` with the §5.2 rule, flattening every entry to per-slot sources:
  - literals, `perTarget` values and spreads become literals;
  - presets stay references.
- For a cue that does not exist yet, `position` is its insertion point.
- Before the programmer values are bucketed (step 2 of the Phase 3 algorithm), the collected values equal to `inherited` are set aside:
  - a preset reference is equal if it names the same preset;
  - a literal is equal if it encodes to the same lanes.
- *merge* still restricts the cue's own entries over every collected slot, the set-aside ones included. So an existing entry for a slot that now matches the inherited value is removed, and the slot tracks.
- The message reads `recorded cue 9/2: 3 entries; 4 values tracked from cue 9/1`.
- Non-tracking lists, `block` cues and *remove* are unchanged.
- The Phase 3 warning "only the first cue plays until Phase 4" goes.

**Autosave.**
- `session.json` gains `programmer.fadeTime` and `speedBpm: {masterId: bpm}`. The speed-master levels are already in `masterLevels`.
- Recovery restores the BPMs with `SET_BPM`, after the levels.
- Older `session.json` files without the new fields still load.

### 5.13 Console (`console/parser.py`, `console/console.py`)

New grammar. Masters have no numbers, so a master is named in quotes. `tap` and `bpm` without a name use the show's only speed master, and are an error when it has none or several.

| Area | Syntax | Becomes |
|---|---|---|
| Perform | `back N`, `goto N <cue>`, `release N [<seconds>]` | `BACK`, `GOTO`, `RELEASE_PLAYBACK` with `time` |
| Tempo | `tap ["<master>"]`, `bpm ["<master>"] <bpm>`, `master "<name>" <level>` | `TAP`, `SET_BPM`, `SET_MASTER` (any kind the bus accepts; `gm` stays) |
| | `master add speed "<name>" [bpm <x>] [steps <a>,<b>,…]` | `ADD` to `masters`. Defaults: 120 BPM, `tap: true`, steps `0.25,0.5,1,2,4` |
| Programmer | `fade <seconds>` | `PROGRAMMER_FADE` |
| Cue timing | `cue L/C time <in>[/<out>] [delay <in>[/<out>]] [<curve>]` | `BATCH` of `SET`s on `timing`. `<out>` defaults to `<in>`. `<curve>` is a curve name or `bezier x1 y1 x2 y2` |
| | `cue L/C time <family> <fade> [delay <d>] [<curve>]` | `SET` of `timing.perFamily`, merged with the families already there |
| | `cue L/C follow <d>`, `cue L/C wait <d>`, `cue L/C go` | `SET` of `trigger` |
| | `cue L/C release <targets> [only <attribute>…]` | `SET` of `releases`, with the new release appended |
| Chase | `cuelist N chase hz <rate> [<direction>] [crossfade <f>]` | `BATCH`: `SET` of `chase`, then `SET` of `mode: "chase"` |
| | `cuelist N chase bpm ["<master>"] [x <multiplier>] [<direction>] [crossfade <f>]` | as above. Defaults: ×1, `forward`, crossfade 0 |
| | `cuelist N sequence` | `SET` of `mode: "sequence"` (the chase settings are kept) |
| Bind | `bind "<surface>" cc\|note <ch> <n> tap ["<master>"]` | `ADD` of a binding with a `tap` action |
| | `bind … master "<name>"` | `ADD` of a `master` action (the speed multiplier knob) |
| Query | `list cues L`, `list masters` | Cues with number, name, timing summary and trigger; masters with kind, level and BPM |

- `cuelist N chase {json}` still goes to the generic `SET`: the sugar applies only when `hz` or `bpm` follows `chase`.
- `cue L/C block true` already works through the generic `SET`.
- `help` is generated from the module docs, as before.
- `programmer` prints the fade time.

### 5.14 Bindings, validation and the limitation report

**Bindings** (`io/bindings.py`):
- A `back` button sends `BACK`.
- A `tap` action sends `TAP` on press.
- A `master` action on a speed master sends `SET_MASTER`.
- `goto` buttons stay unbound (decision 13's companion: they need a cue entry, which comes with Phase 6).

**Validation** (`model/validate.py`, semantic pass). The errors and warnings below are new. Effects are validated now, so Phase 5 inherits the rate rules.

- Errors:
  - `HzRate.value > 0`, in chases and effects;
  - `BpmRate.multiplier > 0`;
  - `SpeedMaster.defaultBpm` in `0 < bpm ≤ 999`;
  - `multiplierSteps` not empty, every step > 0;
  - Bézier control values in 0..1.
- Warnings:
  - `releases` or `block` on a cue in a non-tracking list ("has no effect without tracking");
  - a binding's or command's `GOTO` cue number that the playback's list does not have. It is a warning because cue numbers are user-facing and get renumbered.
- `_command` checks `SET_BPM`'s master reference (a speed master).

**The limitation report** (`compiler/limitations.py`, header `Ignored in Phase 4:`) keeps:
- effects, in every cue now (Phase 5);
- `size` faders (Phase 5);
- `crossfade` faders and `goto` buttons (Phase 6);
- `swop`;
- group, size and fade-time masters;
- pages, surfaces, soft pickup and feedback (Phase 6);
- limits and park (Phase 7);
- `holdLastFrameOnEngineStall: false`.

Everything else Phase 2 listed as "until Phase 4" goes.

### 5.15 The done criterion: `examples/phase4-song.busk`

Run after `phase3-build.busk`, on the show it saved. An illustrative opening:

```
master add speed "Speed 1" bpm 120

# ------------------------------------------------ song stack (tracking)
sel group 2
set intensity 60%
preset color 1
record slot 9 "Song"
rename cue 9/1 "Intro"
cuelist 9 tracking true
cue 9/1 time 3 easeInOut
sel group 1
set intensity 70%
set color 1 0.75 0.45
preset position 1
record cue 9/2 "Verse"           # the washes' values equal cue 1's: tracked, not stored
cue 9/2 time 2
cue 9/2 time position 4
clear
sel group 3
set intensity 100%
preset color 4
sel group 2
set intensity 30%
record cue 9/3 "Pre"
cue 9/3 time 1/3
cue 9/3 wait 8
clear
sel group 4
set intensity 100%
set color 1 1 1
record cue 9/4 "Chorus"
cue 9/4 time 0.5/2
clear
sel group 1
set intensity 20%
record cue 9/5 "Outro"
cue 9/5 time 6
cue 9/5 follow 4
cue 9/5 release group 1 only pan tilt
clear
playback 9 buttons ["go", "back", "release"]
playback 9 exclusivity base
playback 9 releaseTime 3

# ------------------------------------------------ chase (BPM-locked)
sel fixture 201
set intensity 100%
preset color 2
record slot 10 "Chase"
# … fixtures 202–204 as cues 10/2–10/4 …
cuelist 10 chase bpm x1 bounce crossfade 0.25

# ------------------------------------------------ nanoKONTROL2
bind "nanoKONTROL2" cc 1 16 fader 9          # knob 1: song master
bind "nanoKONTROL2" cc 1 17 fader 10         # knob 2: chase master
bind "nanoKONTROL2" cc 1 41 button 9 1       # ▶  GO
bind "nanoKONTROL2" cc 1 43 button 9 2       # ◀◀ BACK
bind "nanoKONTROL2" cc 1 45 button 9 3       # ●  release the song
bind "nanoKONTROL2" cc 1 44 button 10 1      # ▶▶ chase on/off
bind "nanoKONTROL2" cc 1 46 tap              # cycle: tap tempo
bind "nanoKONTROL2" cc 1 18 master "Speed 1" # knob 3: ×¼ … ×4
save
```

**Checkpoints of `test_song_stack.py`.**
- The performance part runs on a fresh `Harness` built from the saved show; the speed master starts at t = 0.
- Expected values are logical, computed by hand from the cue data.
- Washes are the ML-56s, heads the two spots (Audience: MH 1 −30°, MH 2 +30°, tilt 40°), and the bar is the PiX.

| t (s) | Command | Check |
|---|---|---|
| 0 | `fader 9 1` | Intro starts (`autoStart`) |
| 0.75 | | washes' intensity 0.6 · smoothstep(0.25) = 0.09375 |
| 1.5 | | washes' intensity 0.3; colour (0.5, 0.5, 1), halfway from the default white to Blue |
| 10 | `go 9` | Verse; the washes do not move (tracked) |
| 11 | | heads' intensity 0.35; MH 1 pan −7.5°, tilt 10°: position fades over 4 s from the default |
| 18 | — | Pre fires by itself (wait 8 after 10.0) |
| 18.5 | | bar 0.5 (rising, 1 s); washes 0.55 (falling 0.6 → 0.3 over 3 s) |
| 25 | `go 9` | Chorus; it completes at 25.5 |
| 25.25 | | washes 0.65; heads 0.85 |
| 29.5 | — | Outro fires by itself (follow 4 after 25.5) |
| 32.5 | | heads 0.6 (1.0 → 0.2 over 6 s); MH 1 pan −15°, being released to the default |
| 40 | `back 9` | Chorus with its own timing; nothing fires afterwards |
| 40.25 | | heads 0.6; MH 1 pan −15°, re-entering over 0.5 s |
| 50 | `release 9` | release over 3 s: at 51.5 every intensity is half its Chorus value |
| 60 | `fader 10 1` | the chase starts on beat 120 with wash 201, which fades in over 0.125 s |
| 60.5625 | | halfway through the crossfade to wash 202: washes 201 and 202 at 0.5 |
| 61.7 | | wash 204 alone (steps at 60.5, 61.0, 61.5) |
| 62.2 | | wash 203 alone (bounce) |
| 70, 70.46875, 70.9375, 71.40625 | `tap` × 4 | 128 BPM. The chase steps on the second tap (0.03 s ahead of its grid), then on every tap |
| 71.875, 72.34375 | | step boundaries on the 128 BPM grid: the frame changes from that tick on, not before |
| 80 | `master "Speed 1" 0.75` | ×2. No step at 80, and the frame equals the frame without the command. Steps at 80.078125 (beat 161.5), then every 0.234375 s |
| — | — | A second run with `goto 9 4` at t = 1 equals the main run at t = 28, once all fades are done (GOTO = stepping) |
| — | — | The whole script ticked at 100 Hz and on a random irregular schedule gives byte-identical frames at every checkpoint |

The golden DMX frames (`tests/golden/phase4_frames.json`) are produced once at the checkpoints and reviewed by hand against these logical values.

### 5.16 Performance

**Expected cost.**
- A settled source costs what it costs now.
- A transitioning source adds about eight vector operations over its lanes per tick (gather, two lerps, the snap `where`) and per-lane weight multiplies in the resolver.
- The reference benchmark rig averages about 3 000 lanes per playback. With all 60 playbacks mid-transition, that is an estimated 2–3 ms per tick against today's 0.92 ms p99: inside §19's 4 ms target, and far inside the 10 ms gate.
- Retargets run at command time, tens of µs each.

**Benchmarks** (`test_perf.py`, `-m perf`):
- `busking_benchmark_rig(cues=4, tracking=True)` gives each playback a 4-cue list with per-family timing and curves.
- **Tick under transitions:** 60 playbacks GO'd at staggered times, measured while every one of them is mid-transition. Gate: p99 < 10 ms; the result is recorded against the 4 ms target.
- **Command burst:** a tick in which all 60 playbacks GO at once (60 retargets plus the tick). Gate: < 10 ms.
- **Chases:** 8 BPM chases at 16 steps per second, measured over the ticks where they step.
- **Edit latency:** `bench/edit_latency.py` is re-run, because tracked states add compile time. The Phase 3 targets still apply: demo rig with 0 overruns and p95 ≤ 50 ms.

If the 4 ms target is missed, in order:
1. Evaluate only the lanes of unsettled groups. Keep a per-partition mask of lanes in running groups, and copy settled values once.
2. Fuse the value and weight lerps into preallocated buffers with `out=`.
3. Profile the resolver's masked snap path.

---

## 6. Implementation steps

Each step follows TDD: write the listed tests first, then make them pass. Engine tests use a `FakeClock` and call `engine.tick(now)` directly. **Every step ends with the whole suite green.** Steps 3–7 change the engine's core without changing behaviour, and step 7 is the riskiest, so nothing new is built on it until the Phase 2–3 tests pass on the new machinery.

1. **Baseline.** Run `uv run pytest` and `uv run pytest -m perf -s`, and record the tick numbers. → *verify:* green; the numbers are noted under step 18 for comparison.
2. **Curves and validation.**
   - Write `engine/curves.py` and give `Envelope` a curve.
   - Add the §5.14 validation rules.
   → *verify:*
   - `test_curves.py`:
     - each curve's endpoints and formula;
     - monotone on [0, 1];
     - `fade_fraction` around delays and zero durations;
     - Bézier against the CSS `ease` values (cubic-bezier(.25, .1, .25, 1) at t = 0.25, 0.5, 0.75 to 1e-6), and (hypothesis) it stays in 0..1.
   - `test_validate.py` covers every new error and warning.
   - Appendix A still validates with 0 errors and 0 warnings.
3. **Per-lane snap thresholds.** Replace `SnapGroup` in `CompiledCue`, `Source`, the resolver, `install.py` and the oracle. → *verify:* every existing test passes unchanged except those that build `SnapGroup`s by hand, which are updated mechanically; the §7.8 golden test passes.
4. **Per-lane weights in the resolver.** → *verify:*
   - `test_resolver.py` covers per-lane LTP, HTP and snap weights.
   - `test_resolver_properties.py` (hypothesis): random sources with per-lane weights and per-slot sequence numbers match the extended oracle.
5. **Contributors and sequence runs.**
   - Move the programmer's run splitting into `contributions.py` as the general rule (§5.4).
   - Make the programmer and the flash sources contributors.
   → *verify:*
   - `test_seq_runs.py`:
     - no boundaries gives one source;
     - interleaved numbers of two contributors split both correctly;
     - HTP positions go with the newest run;
     - the cache is keyed correctly;
     - (hypothesis) splitting and compositing in `(priority, seq)` order equals the per-slot oracle.
   - `test_engine_programmer.py` is unchanged and green.
6. **`ContributionSet`.** → *verify:* `test_fades.py` is extended with:
   - table tests for retarget: entering, leaving, a value change, unchanged keeps its running fade, each sequence rule, colour extras with `NaN`, a snap value switching at its threshold, `scale`, the completion time, compaction to the settled fast path, `remap`;
   - (hypothesis) the five §5.3 invariants.
7. **Playback runtime on `ContributionSet`, with Phase 3 behaviour only.**
   - Main becomes a `ContributionSet` playing the first cue's tracked state; `env` covers release only; the threshold gate stays.
   - `CompiledPlayback.cueList` replaces `cue`, and `CompiledCue` carries timing, still compiled without tracking.
   → *verify:* all Phase 2–3 tests pass, the §7.8 golden test included. Linear single-cue activation is identical, by construction.

   Run the reference-rig tick benchmark now: if it is far off the 4 ms target, apply §5.16's mitigations before going on.
8. **Tracking and per-slot timing in the compiler.** → *verify:* `test_tracking.py`:
   - the §9.3 states with `block` and `releases`, where a cue's own values win;
   - a non-tracking list holds each cue's own values;
   - per-slot timing for entry overrides, per-family timing, intensity in and out, curve fallbacks, the `leave` table;
   - the `targets` order;
   - interning of `timings`;
   - `test_compile_incremental.py`: memoised equals full compile, with tracking lists.
9. **Cue engine: GO, BACK, GOTO and triggers.**
   - `cue_engine.py`, the §5.5 state machine, `advance` before and after the commands (decision 2).
   - The bus accepts `BACK` and `GOTO`.
   → *verify:*
   - `test_cue_engine.py` (pure functions): next and previous with wrap and `releaseAtEnd`; the schedule for `wait` and `follow`.
   - `test_engine_sequences.py`:
     - each row of the §5.5 table;
     - per-slot timing and curves through the engine;
     - a GO mid-fade with unchanged slots continuing;
     - tracked slots not stealing from a newer bump (decision 4), while changed slots do;
     - GOTO equals stepping (hypothesis over random lists);
     - BACK with the destination's timing and no reschedule;
     - auto-GOs firing at exact times, chained, cancelled by a manual GO, BACK or release, and capped at one lap per tick;
     - schedule independence: frames identical at 100 Hz and on random tick schedules.
   - `test_bus.py`: GOTO with a bad number.
10. **Speed masters and tap tempo.** `SpeedMasterRuntime`, `TAP`, `SET_BPM`, `SET_MASTER` on speed masters; bus checks. → *verify:* `test_tempo.py`:
    - the beat count across `SET_BPM` keeps its phase;
    - taps: two taps; eight steady taps; an outlier dropped; a 2-s gap starts a new run; the phase moves to the nearest beat;
    - multiplier steps from the level, and the default level;
    - masters added by an edit start at their install tick.
11. **Chases and `rate` faders.** `chase.py`, `ChaseRuntime`, the rate fader. → *verify:* `test_chase.py`:
    - Hz step timing and the crossfade duration, with the curve;
    - each direction, with `random` deterministic across runs and never repeating;
    - a rate change mid-step without a jump;
    - BPM: boundaries on beats; activation alignment and the first step between ½ and 1½ steps; tap alignment with forward steps, restarts and never back; rate-change alignment (the §5.7 worked example);
    - GO, BACK and GOTO keep the grid;
    - the rate-fader factor, quantised for BPM;
    - a releasing chase keeps stepping;
    - schedule independence.
12. **Programmer `fadeTime`.** `PROGRAMMER_FADE`, `Programmer.fadeTime`, the frame field, the programmer `ContributionSet`. → *verify:*
    - `test_engine_programmer.py`: a value change, a clear, blind on and blind off, and undo, each fading over `fadeTime`; touched slots still go on top.
    - `test_session.py`: `PROGRAMMER_FADE` is not undone and survives `restore_programmer`.
13. **Live swaps that fade.** Lane maps, remapping every set, re-pointing by `CueId`, the fallback for a deleted cue, re-deriving schedules, chase and master carry-over. → *verify:*
    - `test_live_swap.py`:
      - a recorded change fades with the cue's timing and takes no sequence number, so the stack order is kept;
      - a patch move remaps a running transition mid-fade;
      - deleting the current cue;
      - editing the next cue's trigger re-derives the auto-GO;
      - a chase's rate edit;
      - a speed master's tempo survives an edit.
    - Phase 3 tests that asserted a snap on a timed cue are updated to assert the fade, and are listed in the step's commit message: `test_build_from_scratch.py` check 4, since the Blue bump has a 1 s fade in.
14. **Session and recording.** `SELECT_PLAYBACK` via `engine_state`; tracking-aware `RECORD_CUE`; the Phase 3 warning goes. → *verify:*
    - `test_record_cue.py`:
      - values equal to the inherited ones are omitted and counted in the message;
      - *merge* removes the cue's own entry for an inherited value;
      - a released slot is stored;
      - `block` and non-tracking lists are unchanged;
      - a preset reference against a literal of the same value is stored;
      - recording at an insertion point (`2.5`).
    - `test_session.py`: `SELECT_PLAYBACK` on cue 3 of a running stack, and on an idle playback.
15. **Autosave and recovery.** `fadeTime` and `speedBpm`. → *verify:*
    - `test_autosave.py`: the new fields are written, and old files load.
    - `test_recovery.py`: after a SIGKILL, the BPM and the fade time come back.
16. **Snapshot, status line, bindings, limitations.** → *verify:*
    - `test_engine.py` snapshot cases: the cue, the next cue and `speed` change only at events.
    - `test_cli.py`: the status line formats, and a chase does not print per step.
    - `test_bindings.py`: back, tap and speed-master actions.
    - `test_limitations.py`: the new list under "Ignored in Phase 4:".
17. **Console grammar.** → *verify:*
    - `test_console_parser.py`: at least one case per §5.13 row, plus errors (`no speed master`, `several speed masters: name one`, a bad curve, `chase bpm` without a master).
    - `test_console.py`: `list cues`, `list masters`, `programmer` with its fade time.
18. **Benchmarks** (§5.16). → *verify:* the gates pass and the numbers are recorded below, next to step 1's baseline.
    - *Baseline (step 1, before any Phase 4 change):* 1255 tests passed. Busking tick on Appendix A: 0.054 ms mean, 0.058 ms p99. Reference rig, 60 playbacks mid-fade: 0.903 ms mean, 0.985 ms p99, resolver alone 0.578 ms mean. Conversion 0.281 ms median; output cycle 0.071 ms median.
    - *After step 3 (per-lane snap thresholds):* reference rig 0.98–1.02 ms mean, 1.06–1.41 ms p99, resolver alone 0.63–0.68 ms mean. Every source of that benchmark is mid-fade, so every tick takes the masked snap path (mitigation 3 below).
    - *After step 7 (playbacks on `ContributionSet`):* 1373 tests passed. Reference rig, 60 playbacks mid-fade: 2.00 ms mean, 3.04 ms p99, 3.59 ms max; resolver alone 0.76 ms mean. Appendix A: 0.059 ms mean, 0.071 ms p99. Inside the 4 ms target, as §5.16 estimated, so no mitigation was applied yet.
    - *Results (step 18, 2026-10-12):* 1643 tests passed. `busking_benchmark_rig(cues=4, tracking=True)` gives each of the 60 playbacks a 4-cue tracking wrap list (cues 2–4: 20 s in / 30 s out eased, positions 40 s with a 1-s delay, colours 25 s on a Bézier); `chases=8` adds 8 chases at ×8 on 120 BPM (16 steps per second, crossfade 0.5).
      - **Tick under transitions** (all 60 mid-transition, 191 000 lanes): 3.0–3.3 ms mean, 3.2–4.5 ms p99, 4.8 ms max. Gate (p99 < 10 ms) passed; the 4 ms target is met on the mean and sometimes missed at p99. No §5.16 mitigation applied yet.
      - **Command burst** (60 GOs in one tick, every 0.1 s round the lists): first run **55 ms**: each retarget cost 0.2–1.5 ms, not "tens of µs". Three fixes, beyond the plan: (1) `fades.distinct` replaces `np.unique`/`np.union1d` on the engine thread (`_Draft`, `_regroup`, `_intern`, the slot mask in `retarget`, `split_runs`, `SequencedSource.assign`): NumPy 2.3+ hashes there, 194 µs on 20 000 lanes against 15 µs for a sort; (2) `_Draft` has a **same-lanes fast path** (a tracking list's cues hold the same slots): no union, no scatters, `np.where` in `build`; (3) installs no longer retarget a playback whose compiled cue list is the same object on the same slots (the memoised compile reuses it). Now **16–18 ms mean, 19–23 ms p99**: retargets about 10 ms (≈ 120 µs for a 1 500-lane playback, 0.7 ms for the three 28 000-lane ones covering every PiX cell), the sources' re-split 3 ms, the tick 3.5 ms. **The 10 ms gate is missed.** The test now gates the median under 20 ms and says why. The remedy is a retarget that touches only the changed lanes in place (a `ContributionSet` redesign), left for a later phase. Such a burst only comes from 60 GOs in one tick, or from an edit that changes the slot table with every playback running.
      - **Chases** (8 BPM chases over the 60 mid-fade looks, all stepping on the same 160 of 1000 ticks): step ticks 3.8–4.1 ms mean, 4.1–5.1 ms p99; other ticks 2.1–2.2 ms mean. Gate passed.
      - **Earlier benchmarks:** reference rig 60 playbacks mid-fade 1.9–2.0 ms mean, 2.1–3.2 ms p99, resolver alone 0.76–0.79 ms; Appendix A 0.060–0.063 ms mean; conversion 0.29 ms median; output cycle 0.065–0.073 ms median.
      - **Edit latency** (`bench/edit_latency.py`): demo rig **0 overruns**, p95 6.7–7.3 ms (hard target met). Reference rig p95 127–131 ms (target 250 ms met), but **155–175 overruns in ~1 500 ticks** (max tick 51–72 ms), against Phase 3's ≈ 2 % (max 22.7 ms). 143 of 151 ticks over 10 ms apply an install. An install tick costs about 1 ms alone (5 ms for a patch) but 11 ms median while the edit thread compiles: the GIL convoy of phase-3-plan step 13, now with more NumPy calls per install (retargets, programmer fades). Fix (3) cut the install tick alone from 2.8 to 1 ms but not the overruns. As in Phase 3, it is an input for Phase 7's process split.
19. **Done criterion.** Write `examples/phase4-song.busk`, `test_song_stack.py` and the goldens. → *verify:* `test_song_stack.py` checks that:
    1. every line of the script succeeds;
    2. the saved show equals `tests/golden/phase4_song_show.json`, and `busk validate` reports 0 errors and 0 warnings;
    3. every §5.15 checkpoint matches its hand-computed logical values and the golden bytes;
    4. GOTO equals stepping;
    5. the 100 Hz and irregular-schedule runs give byte-identical frames;
    6. save → load → a fresh engine gives the same frames.
20. **Manual demo on the rig.** Follow the §8 checklist with the nanoKONTROL2 and the Phase 3 rig. → *verify by eye:* the stack's fades look right, the chase locks to tapped tempo, the knobs act as listed, and the run ends with 0 overruns.
21. **README and full verification.** Add a "Song checklist (Phase 4)", the decisions taken beyond the plan, the spec gaps and the benchmark numbers. Update "Next" and the `pyproject` description. → *verify:* §8.

---

## 7. Acceptance tests (summary)

| Test file | Proves |
|---|---|
| `test_curves.py` | Curve formulas, endpoints, monotonicity; Bézier against CSS reference values |
| `test_validate.py` (extended) | Rate, BPM, multiplier-step and Bézier rules; tracking warnings |
| `test_resolver.py` · `test_resolver_properties.py` (extended) | Per-lane weights and snap thresholds agree with the §7.7 oracle |
| `test_seq_runs.py` | Per-slot sequence numbers composite exactly in `(priority, seq)` order |
| `test_fades.py` (extended) | `ContributionSet`: retarget semantics, sequence rules, the five invariants |
| `test_tracking.py` | §9.3 tracked states with `block` and releases; per-slot timing; targets |
| `test_cue_engine.py` · `test_engine_sequences.py` | GO, BACK and GOTO; wrap and release at the end; exact `follow`/`wait`; GOTO = stepping; tracked slots don't steal; schedule independence |
| `test_tempo.py` | Beat count, tap tempo, `SET_BPM`, multiplier steps |
| `test_chase.py` | Step timing, crossfade, directions, beat lock, alignment, rate faders, schedule independence |
| `test_engine_programmer.py` (extended) | Programmer fades on change, clear, blind and undo |
| `test_live_swap.py` (extended) | Edits fade with cue timing, keep the stack order, remap mid-fade, re-derive schedules |
| `test_record_cue.py` · `test_session.py` (extended) | Tracking-aware recording; `SELECT_PLAYBACK` on the current cue; `PROGRAMMER_FADE` is a mode |
| `test_autosave.py` · `test_recovery.py` (extended) | Fade time and BPM survive a crash |
| `test_bus.py` · `test_bindings.py` · `test_limitations.py` · `test_cli.py` (extended) | New commands accepted and checked; back, tap and speed bindings; the shorter limitation list; status line |
| `test_console_parser.py` · `test_console.py` (extended) | The §5.13 grammar |
| `test_golden_7_8.py` (unchanged) | The §7.8 example still holds on the new machinery |
| `test_song_stack.py` | The done criterion |
| `test_perf.py` (`-m perf`, extended) | Ticks under transitions, GO bursts and chases fit the budget |

---

## 8. Verification

```bash
uv run pytest                                           # all green
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run pytest -m perf -s                                # gates pass; numbers recorded
uv run python bench/edit_latency.py                     # demo rig: 0 overruns, p95 ≤ 50 ms
uv run busk new /tmp/busk-demo/club.show --title "Club Night"
uv run busk run /tmp/busk-demo/club.show --script examples/phase3-build.busk --duration 1
uv run busk run /tmp/busk-demo/club.show --script examples/phase4-song.busk
#   busk> list cues 9                → Intro … Outro with timing and triggers
#   busk> fader 9 1                  → the Intro fades in over 3 s, eased
#   busk> go 9                       → Verse; the heads swing out over 4 s; Pre fires 8 s later by itself
#   busk> status                     → "… | Speed 1 120 BPM ×1 | 9 Song on 3 Pre"
#   busk> fader 10 1                 → the chase bounces across the washes on the beat
#   busk> tap  (×4, in time)         → the chase follows the taps
#   busk> quit
uv run busk validate /tmp/busk-demo/club.show           # → 0 errors, 0 warnings
```

**Song checklist (Phase 4)**, for step 20, with the Phase 3 setup (nanoKONTROL2, sACN rig, `--iface`):

1. Run both scripts. "Ignored in Phase 4:" lists only effects, pages, surfaces and the other §5.14 items.
2. Knob 1 up: the Intro eases in. ▶: Verse, with the heads' slower position fade. Wait 8 s: Pre fires by itself, the bar rising fast and the washes dimming slowly. ▶: Chorus. Four seconds after it lands, the Outro starts and the heads drift back.
3. ◀◀ during the Outro: back to the Chorus, and it stays there.
4. With the Verse up, bring up Blue (fader 3), then ▶: the washes stay blue, because tracked slots don't steal.
5. Knob 2 up: the chase steps on the beat. Tap "cycle" in time with music: it locks within two taps. Knob 3: ×½, ×2, staying on the beat.
6. ●: the song releases over 3 s.
7. `fade 2`, `sel group 1`, `set intensity 100%`: the heads fade up over 2 s. `clear`: they fade back.
8. The run ends with 0 overruns.

---

## 9. Spec deviations and gaps

**Deliberate deviations**

- **Sequence numbers per slot** (decision 4).
  - §8.1 gives the playback one `activationSeq` per GO. Here a GO makes the playback newest only on the slots it changes, and automatic advances and edits take no number.
  - Without this, tracking would take colour away from bumps on every GO.
  - §5.18's `activationSeq` remains, as the playback's newest number.
- **Unchanged slots keep their running fade** on a GO (decision 5). §9.1 restarts every slot "from the current interpolated values" with the new cue's timing, which makes a 0-s GO cut short a running fade.
- **Releases.** A cue's own values win over its own `releases`. §9.3's formula applies `without` after the merge, which would release a value the cue itself sets.
- **No `dt`** (decision 1). Positions are functions of time, rebased at events. That meets §9.4 and §10.1's "accumulated phase" goal without integrating, so §11.2's `dt` and its clamp are not needed.
- **Event order** (decision 2). Due auto-GOs and chase steps fire before the tick's commands, at their exact times. §20's "±1 tick" tolerance becomes exact.
- **Fades are stored as arrays.** §5.18's `ContributionState` per slot, `CueTransition` and `chasePhase` become `ContributionSet`, `started`/`completes`/`auto` and `ChaseClock`.
- **New commands:** `SET_BPM`, and `PROGRAMMER_FADE` (a mode, not undone).
- **`crossfade` faders and `goto` buttons move from Phase 4 to Phase 6** (decision 13).

**Gaps decided here (to fold back into the spec)**

- **Curve formulas** for `easeIn`, `easeOut`, `snapStart`, `snapEnd` and Bézier, and Bézier control values limited to 0..1 (decision 7).
- **Timing details:**
  - which timing a slot that leaves, or a tracked slot reached by GOTO, uses: the destination's (decision 6);
  - BACK uses the destination's timing (§8.1 says "its", read as the previous cue's);
  - "rising" compares effective intensities;
  - a per-entry `fade` covers both in and out.
- **GO, BACK and GOTO edge cases:** idle and releasing playbacks; the first and last cue; GOTO to the current cue (decision 9).
- **When auto-GOs are scheduled:** after forward moves only. "Completes" means the end of the fades the transition started.
- **Chases:**
  - cue timing and triggers ignored except the curve;
  - always looping;
  - the first step's fade;
  - GO, BACK and GOTO on a running chase;
  - the `reverse` start and `random` seeding;
  - activation, tap and rate-change alignment (§5.7).
- **Speed masters:**
  - the level selects a `multiplierSteps` entry;
  - the tap algorithm's exact numbers (8 taps, median ±25 %, 2-s reset, phase to the *nearest* beat, from the second tap);
  - beat counting starts at the first tick.
- **`rate` faders** start at 0.5 and are quantised on BPM chases.
- **Live edits** fade with the cue's timing and keep the stack order (§6.4 says "fades smoothly" without a time). A deleted current cue falls back to the next number.
- **Recording in tracking lists** stores changes only (README's open question from Phase 3).
- **Selecting a playback** uses the current cue's *tracked* targets.

**Still open after Phase 4**

- `crossfade` fader semantics and `goto` buttons (Phase 6).
- Bar alignment for multi-beat chase steps: chases align to beats, not bars, so a step every 4 beats starts on *a* beat.
- External tempo: MIDI clock, Ableton Link.
- A fade-time master: it would scale or replace transition durations at retarget (Phase 5, with the other masters).
- Colour-wheel hysteresis, which waits for colour → wheel matching.
- The open items carried from Phases 2–3 (README "Spec gaps").

---

## 10. What Phase 5 changes

- **Effects** reuse this phase's time machinery:
  - an effect's phase is a `ChaseClock`-style position: Hz, or BPM on a speed master's beat count, with the same alignment rule or a gentler nudge (§10.1);
  - `sizeEnvelope` is an `Envelope` with a curve;
  - absolute effect layers are contributors with per-lane values every tick;
  - the relative pass (§7.5) runs after the absolute one, and its "top full band" uses the per-lane weights from this phase.
- **`size` faders and size masters**, alongside this phase's `rate` faders; effect speed masters reuse `SpeedMasterRuntime`.
- **Group masters** at stage 9, and possibly the fade-time master, applied when transitions are retargeted.
- **Recording effects** into cues; `ADD_EFFECT` in the programmer.
