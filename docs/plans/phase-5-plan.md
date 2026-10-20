# Phase 5 — Effects: implementation plan

> Source spec: `busking-console-architecture-python.md` (§22, Phase 5; §5.10, §5.12–§5.14, §5.18, §7.1, §7.5, §7.7, §8.1–§8.2, §10, §11.3, §12, §15.2–§15.3, §19, §20). Builds on the Phase 0–4 plans and on the code as it stands after Phase 4 (1685 tests). §2 names the real modules this plan changes, so no seam-mapping step is needed.

## Context

Phase 4 ends with a console that plays song stacks, chases and tempo. Effects are still accepted by validation and then listed as ignored: Appendix A's "Slow Pulse" toggles and nothing happens, `size` faders do nothing, and size and group masters are rejected by the bus.

The spec scopes Phase 5 as *"Templates, instances, phase spread (groups/blocks/wings), relative/absolute modes, size/speed masters"*. It is done when there is a *"Circle on moving heads + pulse on pars, tap-synced"*. Phase 4 handed over (phase-4-plan §10):

- an effect's phase as a `ChaseClock`-style position (Hz, or on a speed master's beats);
- `sizeEnvelope` as an envelope with a curve;
- absolute layers as contributors with values every tick, and the §7.5 relative pass after the absolute one;
- `size` faders and size masters next to Phase 4's `rate` faders;
- group masters at stage 9, and possibly the fade-time master;
- recording effects into cues, and `ADD_EFFECT` in the programmer.

Four things make this phase harder than its one-line scope suggests:

1. **The first source whose values move every tick.** Every source so far is static between events: a fade is a lerp between two fixed arrays. An effect's values come from a waveform evaluated per member, every tick, and they still have to fade in and out, cross-fade between cues and survive live edits without a jump.
2. **A second resolver pass.** Relative effects are not layers of the stack. They apply after it, in their own order, unless a higher band has taken the slot. Taken literally, §7.5 switches a relative effect off the instant a higher band reaches full presence. In a console where everything fades (Phase 4), a 2-s override fading in over a circling head would end with a jump.
3. **Continuous motion and the beat.** A chase may re-align to the beat by stepping. A circle cannot jump. §10.1's "accumulated phase, nudged toward the beat on each tap" has to become a pure function of time (phase-4-plan decision 1) that never jumps and still locks to tapped tempo.
4. **Effects inside everything Phase 4 built.** Cue transitions, tracking, per-slot sequence numbers, releases, live edits, the programmer, flash and recording each need a rule for what an effect does. Each rule must keep the guarantees the engine already has: no jumps, and frames independent of the tick schedule.

**Done when:**

- Starting from the show that `examples/phase3-build.busk` and `examples/phase4-song.busk` build, the script `examples/phase5-effects.busk` adds, with console commands only:
  - a size master and a group master;
  - a **circle on the heads** (relative pan/tilt), a **pulse on the washes** (relative intensity) and a **wave across the bar's 12 cells** (absolute intensity, mirrored with `wings`), each on its own playback with a `size` fader, BPM-locked to "Speed 1";
  - a **colour cycle on the bar**, recorded into the song's Chorus, which tracks into the Outro;
  - nanoKONTROL2 bindings for the three effect faders, their on/off buttons and the size master.

  `busk run` on the result busks the effects from the controller, in time with tapped tempo.
- `test_effects_show.py` reproduces this deterministically. It checks:
  - the saved show matches a golden JSON file;
  - logical values at the checkpoints of §5.14 match values computed by hand, and DMX frames match golden bytes;
  - a tap moves nothing at the instant it lands, and one beat later every BPM effect is on the tapped grid;
  - the group master scales the washes and, set back, returns the exact frame;
  - the colour cycle keeps its phase from the Chorus into the Outro;
  - a programmer value on one head's pan suspends the circle on that pan only, and `clear` brings it back;
  - frames are byte-identical whether the engine ticks at 100 Hz or on an irregular schedule, and after save → load.
- The §7.8 golden test and every Phase 2–4 test still pass. The only exceptions are tests that asserted effects, `size` faders or size and group masters were ignored or rejected (§6 step 7 lists them).
- On the §19 reference rig, a busking tick with 60 playbacks mid-fade and 20 effects running stays at p99 < 10 ms. The numbers are recorded against §19's 4 ms target.
- All acceptance tests in this plan pass.

---

## 1. Scope

| In Phase 5 | Deferred (to) |
|---|---|
| Effect templates: scalar layers with the nine §10.3 waveforms, colour layers with palettes (`fade`/`snap`, literal colours and preset references) | Discrete effects (gobo or prism stepping): the schema allows scalar and colour layers only |
| Instances: targets, `rate` (Hz and BPM), `direction`, `size`, `low`/`high`, phase spread with `groups`/`blocks`/`wings` (§10.2), `sizeFadeIn`, `sizeMasterId`, `speedMasterId` | Matrix effects over a group's 2-D `layout` (§5.7); pixel mapping (a v1 non-goal) |
| `absolute`, `add` and `multiply` modes; the relative pass (§7.5) | — |
| Effects in cues: effect playbacks, sequences (tracking by instance, releases, `block`), chases; release; live edits that fade | The cross-fade when one playback hands a slot from a static value to an effect, which dips (§9) |
| BPM effects locked to the beat grid and nudged on taps; `rate` faders, speed-master steps | Bar alignment; MIDI clock and Ableton Link (both still open from Phase 4) |
| `size` faders; size masters | — |
| Flash and `temp` faders play a cue's effects while the playback is off | `swop` (unassigned in the roadmap) |
| Group masters (§12 step 1) | The fade-time master (decision 18) |
| Programmer effects: `ADD_EFFECT`, `REMOVE_EFFECT`, live at band 100, blind, fade time, undo, autosave | The blind preview resolve (Phase 6) |
| Recording effects into cues (§15.3), tracking-aware | Effects in presets (presets hold values, §5.8) |
| A built-in effect template library; console grammar; snapshot and status line | A template editor beyond JSON layers (Phase 6 UI) |
| | Colour layers on wheel-only fixtures (waits for colour → wheel matching); a frequency cap on strobe-like intensity effects (Phase 7, with the strobe-rate cap) |

---

## 2. Baseline from Phase 4

These are the modules this plan changes, as they are now.

| Area | Now | Phase 5 change |
|---|---|---|
| `model/effect.py`, `model/validate.py` | The §5.10 schema is validated structurally; semantically only template and preset references, rates, and speed and size master kinds | The §5.13 effect rules |
| `compiler/cues.py` | `CompiledCue` holds values and timing; `CueCompiler.own` ignores `effects`; `TimingTable.inTiming` | `CompiledCue.effects` and `outTiming`; the effect compile hook; `readTemplates` |
| `compiler/tracking.py` | Tracked states of values (§9.3) | Effects tracked by instance id (§5.3) |
| `compiler/compile.py`, `compiler/playbacks.py` | Memo by identity over groups and presets; `CompiledMaster` with speed fields | The memo also reads effect templates; group masters carry their intensity positions |
| `engine/contributions.py`, `engine/resolver.py` | `Source`, `SequencedSource`, `gather`; the absolute pass | `Relative`; the relative pass and per-band coverage (§5.6) |
| `engine/playback_runtime.py` | Main is a `ContributionSet`, flash a static `Source`; chases; `master`, `rate` and `temp` faders | Effect banks for main and flash; `size` faders; taps and rate changes reach effects (§5.7) |
| `engine/chase.py` | `ChaseClock._grid`, `rate_factor`, `beat_factor` | The grid rule is shared with effect clocks |
| `engine/masters.py` | Grand master, blackout, `SpeedMasterRuntime` | The group-master factor |
| `engine/install.py` | `ProgrammerRuntime` over a `ContributionSet` | Plus an effect bank; `ProgrammerFrame.effects` |
| `engine/loop.py` | Stages 1–4, 6–7, 9–13; `masterLevels` holds grand levels | Stages 5 and 8; group masters at 9; `SET_MASTER` by kind |
| `commands/` | No effect commands; `MASTER_ARRIVES_IN` rejects group, size and fade-time masters; `RECORD_CUE` writes `"effects": []` | `ADD_EFFECT`, `REMOVE_EFFECT`; group and size masters accepted; effects recorded |
| `session/` | The programmer holds selection and values | And effects |
| `console/` | No effect grammar | §5.12 |
| `compiler/limitations.py` | Lists effects, `size` faders, group, size and fade-time masters | Shorter (§5.13) |
| Tests | `harness.Harness`, `session_harness.Live`, `reference_resolver.py` (the §7.7 oracle, absolute pass only), `test_perf.py` (`busking_benchmark_rig(cues=, tracking=, chases=)`) | Extended (§7) |

**Benchmark baseline (README, Phase 4):**
- Appendix A busking tick: 0.06 ms mean.
- Reference rig, 60 playbacks mid-fade: 1.9–2.0 ms mean, 2.1–3.2 ms p99.
- All 60 mid-transition: 3.0–3.3 ms mean, 3.2–4.5 ms p99.
- 8 BPM chases stepping: 3.8–4.1 ms mean on step ticks.
- The two Phase 4 misses stay open and are not this phase's work: the 60-GO burst (16–18 ms) and the reference-rig edit overruns (Phase 7's process split).

---

## 3. Decisions and assumptions

1. **Effects are pure functions of time.** Phase 4's decision 1 holds.
   - An effect's position `P(t)`, in cycles, is linear in time (Hz) or in its speed master's beat count (BPM), rebased only at events. Nothing is integrated with `dt`.
   - Waveforms, palettes, presence envelopes and nudges are functions of `P(t)` and `t`.
   - So frames still depend only on the commands and their times, never on the tick schedule.
2. **BPM effects lock to the beat grid without jumping.**
   - On activation a BPM effect starts on its master's grid, with Phase 4's alignment rule (`p_ref = 0`): its cycle boundaries fall on beats, or on subdivisions for more than one cycle per beat.
   - On a tap, or when its rate changes (the master's step, a `rate` fader), it re-aligns to the grid position nearest where it is. The difference `e` (at most half a grid step) is not applied at once: it decays linearly to 0 over **one beat** of the master. `P` is continuous, and one beat after the event the effect is exactly on the grid.
   - This is §10.1's "nudged toward the master's beat phase", made exact. Chases keep Phase 4's stepping rule.
   - Hz effects rebase on a rate change and ignore taps.
3. **Waveforms** (§10.3). Phase `p ∈ [0, 1)`, value `w ∈ [0, 1]`:
   - `sine`, `triangle`, `square`, `sawUp`, `sawDown`, `step`: as §10.3 writes them.
   - `pulse`: `attack`, `width` and `decay` are fractions of a cycle, each ≥ 0, summing to ≤ 1. The wave ramps up over `attack`, holds 1 for `width`, ramps down over `decay`, then rests at 0. A zero-length ramp is a step.
   - `random`: one value per member per cycle, `hash(seed, member, cycle) ∈ [0, 1)`. The cycle is the integer part of the member's phase position. `smooth` interpolates consecutive values with smoothstep. A counter-based hash (splitmix64), not a stateful generator, keeps it a pure function of time.
   - `curve`: piecewise-linear through the points, extended periodically, so the wave is continuous across the cycle boundary. Catmull-Rom is left out.
4. **Direction** maps the position `P` to a base phase `b` before the member offsets are added:
   - `forward`: `b = P`;
   - `reverse`: `b = −P`, so a wave travels the other way across the members;
   - `bounce`: `b` is a triangle of `P` with period 2, going up for one cycle and back for the next.

   Member `k` of layer `L` is then at `φ = b + offset_k + L.phaseOffset/360`, and `p = φ − floor(φ)`.
5. **Phase spread** (§10.2), computed once at compile time over the instance's ordered targets:
   - **wings:** the wing size is `S = ceil(N / wings)`; member `k` takes position `k mod S`, reversed (`S − 1 − …`) in odd wings;
   - **blocks:** `k := floor(k / blocks)`;
   - **groups:** `k := k mod groups` when `groups > 1`;
   - with `M` = the largest position + 1, `offset_k = start + (end − start)·k / M`.

   Members without a layer's attribute keep their position and are skipped for that layer, as spreads do. A target is exactly its element (Phase 3), so an effect on the bar's group spreads over its 12 cells. This closes the "element 0 vs whole fixture" question for effects.
6. **Layer modes** (§10.4). The *dynamics* `d` of an instance are its size master's level × the playback's `size` fader level (each 1 when absent).
   - `absolute` scalar: `value = lerp(low, high, w)`. `low` and `high` default to the attribute's registry range; an attribute without one (pan, tilt, zoom, rotations, strobe rate) needs both. They apply to every scalar absolute layer of the template and are clamped at compile time.
   - `absolute` colour: the member's palette position is `x = p · K` for `K` colours. `fade` lerps from colour `floor(x)` to the next, wrapping to the first; `snap` holds colour `floor(x)`. The layer drives `r, g, b`, and holds the extras lanes at `NaN` ("derive").
   - **Dynamics scale an absolute layer's presence**, not its amplitude. A colour cycle at half size is half present over what is below it; there is no other sensible meaning for a palette. `size` itself is unused by absolute layers.
   - `add`: `amount = size·d·(2w − 1)`, in attribute units, symmetric around the base.
   - `multiply`: `amount = 1 − size·d·(1 − w)`, with `size` in 0..1, so a pulse never exceeds the look below it.
7. **Effects layer over their cue's values.**
   - A cue's effects are separate contributors of the playback, in its band. Nothing decides at compile time whether a slot belongs to a value or to an effect.
   - LTP order between them comes from sequence numbers (decision 10), and **an effect wins a tie** with its own playback's values. A cue that sets amber and a colour cycle on the bar shows the cycle, with the amber under it.
   - A later GO that changes the bar's colour takes a fresh number and goes on top: the latest change wins, per slot, as in Phase 4.
   - HTP merges by maximum as always: an absolute intensity wave over a static 0.8 shows only above 0.8.
8. **Tracking effects** (§9.3).
   - In a tracking list an effect instance persists into later cues, by its `id`, until a later cue has an instance with the same `id` (which replaces it), a `block` cue, or a `release`.
   - A release removes the released slots from tracked instances. An instance left without lanes is dropped. A cue's own effects are not trimmed by its own releases (phase-4-plan §9).
   - Without tracking, or at a `block`, a cue holds only its own effects.
   - GOTO lands on the same set of instances as stepping. Their *phases* depend on when each started: BPM effects agree up to the beat grid, Hz effects do not (§9).
9. **Transitions.** Each running instance has one clock and one or more *versions* (compiled forms), each with a presence envelope:
   - **Enter** (an `id` not running): a new clock, and a version fading in over `sizeFadeIn` (linear) if the instance has one, else the destination cue's in timing (`fadeIn`, `delayIn`, curve).
   - **Leave** (an `id` the new state lacks): every version fades out with the destination cue's out timing (`fadeOut`, `delayOut`, curve). The effect keeps moving while it fades.
   - **Change** (same `id`, different compiled form: a new size, a trimmed member list, an edited template): the new version fades in and the old ones fade out with the destination's in timing, on the **same clock**. The clock follows the newest version's rate.
   - **Mixing.** Per lane, the versions' outputs are averaged weighted by presence, and the lane's presence is `min(1, Σ presence)`. A change of size is therefore an exact morph of the amplitude, not a dip.
   - Chase steps use the step cross-fade, and the programmer its fade time, for all three.
   - A transition completes when its last slot fade *or* presence fade ends, which `follow` triggers use.
10. **Sequence numbers per instance.** An instance is one contributor with one number, under Phase 4's rules:
    - activation and re-assert give every instance the fresh number;
    - a manual GO, BACK or GOTO gives it to instances that enter or change;
    - automatic advances and live edits give none, and an entering instance takes the playback's latest number;
    - the programmer numbers the effects a command touched.
11. **Release.** A release fades the playback's envelope as in Phase 4. Effects keep running underneath, like a releasing chase. Re-activating a releasing playback folds the release level into the effect presences, as it does into the slots.
12. **Weights.** An effect inherits its playback's weights the way its values do:
    - absolute layers: HTP presence `env × presence × d`, scaled by the playback's `intensityScale`; LTP presence `ltpWeight × presence × d`;
    - relative layers: the playback's weight for that kind of lane (`env × intensityScale` on intensity, `ltpWeight` otherwise) × presence, with `d` in the amount.

    So a `master` fader at 50 % halves a pulse's depth, and a `followFader` position look's fader scales its circle.
13. **The relative pass** runs after the absolute one (§7.5):
    - Relative contributions apply in `(priority, seq, order)` order, `order` being the layer's place in its cue.
    - `add`: `v + amount·W`; `multiply`: `v · lerp(1, amount, W)`.
    - **Suppression is continuous.** `W` is the contribution's weight × `(1 − A)`, where `A` is the highest effective presence on that lane among absolute contributions of *higher* bands. At `A = 1` this is §7.5's rule exactly: the effect is suspended. A higher band fading in now fades the effect out with it instead of cutting it at the end.
    - `add` results on attributes with a registry range are clamped after the pass. Every other step stays in range on its own: multiply amounts and weights are in 0..1, and degrees are clamped by conversion.
14. **Faders.**
    - **`size` faders** start at 0 and honour `autoStart` and `autoRelease`, like `master` faders: a `size` fader is an effect playback's level. They scale `d`. A cue's static values on a `size`-fader playback are unaffected (`intensityScale` 1).
    - **`rate` faders** scale every effect of their playback as they scale a chase: by 4^(2·level − 1) on Hz effects, rounded to a power of two on BPM effects.
    - **`master` faders** scale effects through decision 12.
15. **Masters.**
    - **Size masters** scale the dynamics of the effects that name them in `sizeMasterId`.
    - **`speedMasterId`** on an Hz effect multiplies its rate by that master's multiplier step. A BPM effect follows its rate's master, step included, as chases do; a `speedMasterId` naming another master is ignored with a validation warning.
    - **Group masters** (§12 step 1) scale intensity by the product of the group masters containing each target, before the grand master, on the output frame only.
16. **Flash and `temp`** play the cue's effects while the playback's main is idle:
    - A *flash bank* runs them in the flash source's band, with its number and level, LTP layers only with `includeLtp`, at full dynamics (size masters still apply).
    - While main is active the flash adds only static values, so a pulse is never applied twice.
    - When main activates during a held flash, the flash bank stops and main's bank starts on the same beat grid.
17. **Programmer effects.**
    - New commands `ADD_EFFECT {effect}` (adds or replaces an instance by `id`; the console fills `targets` with the selection, in order) and `REMOVE_EFFECT {id?}` (one, or all without an `id`). `CLEAR_PROGRAMMER` clears effects too.
    - Effects are programmer content: undone, recorded and autosaved like values.
    - While not blind they run live at band 100, entering, changing and leaving over the programmer's fade time.
18. **The fade-time master is deferred.** §5.13 calls it "a global fade override" and nothing more. Scaling every transition, or replacing cue times while a knob is up, are both plausible and need operator input, and neither concerns effects. It stays in the limitation report as unassigned; Phase 6, which brings the surfaces, is the natural place to decide.
19. **Templates come from a built-in library**, like fixture profiles: the console embeds a library template into the show on first use, so shows stay portable. Custom templates are added as JSON layers.
20. **New commands are backward compatible**; `schemaVersion` stays 1.
21. **No new dependencies.**

---

## 4. Project layout (new and changed files)

```
src/busk/
  compiler/
    effects.py           # CompiledWave, CompiledLayer, CompiledEffect; member offsets (§10.2); compile_effect (new)
    cues.py              # CompiledCue.effects, outTiming; CueCompiler.effect(); readTemplates (changed)
    tracking.py          # effects in tracked states (changed)
    compile.py           # the memo reads effect templates; masters get the slot table (changed)
    playbacks.py         # CompiledMaster.positions for group masters (changed)
    limitations.py       # (changed)
  engine/
    waveforms.py         # vectorised §10.3 waveforms (new)
    effects.py           # EffectClock, EffectRuntime, EffectBank (new)
    contributions.py     # + Relative; relatives in gather (changed)
    resolver.py          # the relative pass, per-band coverage, clamps (changed)
    chase.py             # grid_position() shared with effect clocks (changed)
    playback_runtime.py  # main and flash banks; size faders; taps and rates reach effects (changed)
    masters.py           # group-master factor (changed)
    install.py           # ProgrammerFrame.effects; ProgrammerRuntime's bank (changed)
    loop.py              # stages 5, 8, 9; SET_MASTER by kind (changed)
  model/validate.py      # effect rules (changed)
  commands/
    types.py classes.py  # + AddEffectCmd, RemoveEffectCmd (changed)
    bus.py               # group and size masters accepted (changed)
    record.py            # RECORD_CUE records effects (changed)
  session/
    programmer.py frame.py session.py  # programmer effects (changed)
    library.py           # + EffectLibrary (changed)
  library/effects.json   # built-in effect templates with console defaults (new)
  persistence/autosave.py  # programmer effects (changed)
  io/bindings.py         # group and size masters (changed)
  console/parser.py console.py  # §5.12 grammar, list effects (changed)
  cli.py                 # status line for size faders, "Ignored in Phase 5:" (changed)
examples/phase5-effects.busk
tests/golden/phase5_effects_show.json  tests/golden/phase5_frames.json
tests/…                  # see §7
```

The engine still never imports `session/`, and `compiler/` never imports `engine/`. That is why phase spread lives in `compiler/effects.py`, not in §21's `engine/phase_spread.py`: it is computed at compile time.

---

## 5. Component design

### 5.1 Waveforms (`engine/waveforms.py`)

```python
def evaluate(wave: CompiledWave, phase: NDArray[np.float64], member: NDArray[np.intp],
             out: NDArray[np.float64]) -> NDArray[np.float64]: ...
    """w for each lane, from its phase *position* φ (cycles, not wrapped) and its member index."""
```

| Waveform | `w(p)`, `p = φ − floor(φ)` |
|---|---|
| `sine` | `0.5 − 0.5·cos(2πp)` |
| `triangle` | `2p` for `p < ½`, else `2 − 2p` |
| `square` | `1` for `p < duty`, else `0` |
| `sawUp` / `sawDown` | `p` / `1 − p` |
| `pulse` | `p/a` on `[0, a)`, `1` on `[a, a+h)`, `1 − (p−a−h)/d` on `[a+h, a+h+d)`, else `0` (decision 3) |
| `step` | `steps[floor(p·n)]` |
| `random` | `u(c)` or, with `smooth`, `u(c) + (u(c+1) − u(c))·s(p)`; `c = floor(φ)`, `u(c) = splitmix64(seed, member, c) / 2⁶⁴`, `s` = smoothstep |
| `curve` | `np.interp(p, xs, ys)` over the points extended by one point on each side, periodically |

- Every formula is vectorised over a layer's lanes: one numpy call per term, with `out=` buffers preallocated per layer. No Python loop runs over members.
- `random` hashes in `uint64` arithmetic, which wraps, so it is deterministic on every platform.
- `CompiledWave` (§5.2) carries the parameters in the form the formula wants: `xs`/`ys` already extended, `steps` as an array.

### 5.2 Compiled effects and phase spread (`compiler/effects.py`)

```python
@dataclass(frozen=True, kw_only=True)
class CompiledWave:
    kind: WaveKind
    duty: float = 0.5
    attack: float = 0.0; width: float = 0.0; decay: float = 0.0
    steps: NDArray[np.float64] = _NONE
    seed: int = 0; smooth: bool = False
    xs: NDArray[np.float64] = _NONE; ys: NDArray[np.float64] = _NONE

@dataclass(frozen=True, kw_only=True)
class CompiledLayer:
    attribute: AttributeId
    mode: Literal["absolute", "add", "multiply"]
    lanes: NDArray[np.intp]          # absolute intensity: positions in intensityLanes; else frame lanes
                                     # (colour: shape (members, 3), the r, g, b lanes)
    member: NDArray[np.intp]         # per member of the layer: its index in the instance's targets
    phase: NDArray[np.float64]       # per member: offset_k + phaseOffset/360, in cycles
    wave: CompiledWave | None        # scalar layers
    low: float = 0.0; high: float = 1.0      # absolute scalar layers, clamped to the range
    palette: NDArray[np.float64] | None = None   # colour: (members, K, 3)
    blend: Literal["fade", "snap"] = "fade"
    extras: NDArray[np.intp] = _NO_LANES     # colour: extras lanes, held at NaN (derive)
    clamp: tuple[float, float] | None = None # add layers on attributes with a registry range

@dataclass(frozen=True, kw_only=True)
class CompiledEffect:
    key: str                         # the instance id: its identity across a list's cues
    rate: Literal["hz", "bpm"]
    hz: float                        # cycles per second (hz)
    masterId: MasterId | None        # the tempo source (bpm)
    multiplier: float                # cycles per beat (bpm)
    speedMasterId: MasterId | None   # hz effects: × that master's step (decision 15)
    direction: Literal["forward", "reverse", "bounce"]
    size: float
    sizeFadeIn: float | None
    sizeMasterId: MasterId | None
    layers: tuple[CompiledLayer, ...]
    targets: tuple[TargetRef, ...]   # expanded, in order (the select button)
    def same(self, other: CompiledEffect) -> bool: ...        # structural: arrays compared exactly
    def without(self, slots: AbstractSet[SlotIndex], table: SlotTable) -> CompiledEffect | None: ...
    def remapped(self, laneMap: NDArray[np.intp], posMap: NDArray[np.intp]) -> CompiledEffect | None: ...
```

**`compile_effect(compiler, instance, path) -> CompiledEffect | None`.**
1. Look up the template. Expand the targets with the `CueCompiler` (a group follows its members; `readGroups` notes it).
2. Compute the member offsets (decision 5).
3. For each layer, keep the members that have a slot for its attribute:
   - absolute intensity layers go to HTP positions (`np.searchsorted(intensityLanes, laneOffset)`);
   - every other layer goes to frame lanes; a colour layer takes `r, g, b` and holds the extras at `NaN`.
4. Resolve palettes per member: a literal colour as is, a preset reference through the §5.8 scope lookup (`readPresets` notes it). Colours are clamped to 0..1, and their extras are dropped (decision 6). A member for which a palette preset has no colour is dropped from the layer, with a compile warning.
5. Precompute `phase` per member, the absolute `low`/`high` and the `add` clamp.
6. An instance whose layers end up without lanes compiles to `None`, with a compile warning ("no target has pan or tilt: the effect does nothing").

**Identity and `same`.** Within one compile, a tracked instance in consecutive cues is the *same object*, so the engine's "unchanged" test is an identity check. Across recompiles (live edits) it falls back to `same()`, which compares every field and array exactly.

**`without` and `remapped`** return a new compiled effect without the given slots, or on a new slot table; `None` when no lane is left. Tracking (§5.3) uses the first. The second is used for running versions that are still fading when a live swap changes the slot table (§5.10).

**`CueCompiler`** gains `effect(instance, path)` and `readTemplates`. The cue-list memo (phase-3-plan §5.11) adds the templates a list's effects read to its validity check, next to its groups and presets.

### 5.3 Effects in cue lists (`compiler/tracking.py`, `compiler/cues.py`)

`OwnCue` gains `effects: Mapping[str, CompiledEffect]` (by `id`, in cue order). `TrackedState` gains the same. The §9.3 rule extends instance by instance (decision 8):

```
effects[0] = own[0].effects
effects[n] = own[n].effects                                      if not tracking or cue n is a block
           = trim(effects[n−1], released(n)) | own[n].effects    otherwise
```

- `|` merges by `id`: the cue's own instance replaces a tracked one in place, and new ones are appended.
- `trim` applies `CompiledEffect.without(released(n))` to each tracked instance and drops those that come back `None`. Unchanged instances stay the same objects.
- `released(n)` is Phase 4's set of released slots.

`CompiledCue` gains:
- `effects: tuple[CompiledEffect, ...]`, the tracked instances in order;
- `outTiming: SlotTiming`, the cue's `fadeOut`/`delayOut`/curve. Leaving effects fade with it; Phase 4 already has `inTiming`.
- `targets` lists the effects' targets after the values' targets, for `SELECT_PLAYBACK`.

`EMPTY_CUE.effects` is `()`.

### 5.4 Effect clocks (`engine/effects.py`)

```python
NUDGE_BEATS: Final = 1.0

class EffectClock:                      # P(t), in cycles (decisions 1–2)
    master: SpeedMasterRuntime | None   # BPM
    rate: float                         # hz: cycles per second; bpm: cycles per beat
    p0: float; t0: float; b0: float     # hz: P = p0 + rate·(t − t0);  bpm: grid = p0 + rate·(beats(t) − b0)
    error: float; errorBeat: float      # bpm: P = grid + error·max(0, 1 − (beats(t) − errorBeat)/NUDGE_BEATS)
    def position(self, t: float) -> float: ...
    def rerate(self, now: float, rate: float) -> None: ...   # hz: rebase; bpm: re-align with a nudge
    def align(self, now: float, p_ref: float) -> None: ...   # bpm, after the master's phase moved (a tap)
```

- **Start.** Hz: `p0 = 0`, `t0 = now`. BPM: the grid position nearest 0, from `chase.grid_position()`, the rule of `ChaseClock._grid` moved to a module function both clocks share. There is no nudge at start: presence fades the effect in.
- **Align.** `p0, b0 := grid_position(master, rate, now, p_ref)`; `error := p_ref − p0`; `errorBeat := beats(now)`. So `P(now) = p_ref`: nothing moves at the event, and from `NUDGE_BEATS` later the effect is on the grid. A second event during a nudge aligns from the current `P`, nudge included, so it is continuous too.
- **Rate.** A BPM effect's rate is `multiplier × master.multiplier × beat_factor(rate fader)`; an Hz effect's is `hz × rate_factor(rate fader) × (the step of speedMasterId)`.
- **Who calls it.**
  - On a `TAP`, `Playbacks.tap` reads every locked clock's position *before* the master taps and aligns each one after. That covers chases (Phase 4) and effect clocks: main and flash banks, and the programmer's.
  - `SET_MASTER` on a speed master, a `rate` fader or a version with a new rate calls `rerate`.
  - `SET_BPM` needs nothing, because the beat count is continuous.

**Worked example** (§5.14): a pulse at ×1 started at t = 3 (beat 6) on 120 BPM, so its grid is `P = beats − 6`. Taps land at 10, 10.46875, 10.9375 and 11.40625 s.

| Event | Beats (old → new) | `p_ref` | New grid `p0` | `error` | Result |
|---|---|---|---|---|---|
| Tap 1 at 10 | 20 → 20 | 14 | 14 | 0 | Nothing moves |
| Tap 2 at 10.46875 | 20.9375 → 21 (128 BPM) | 14.9375 | 15 | −0.0625 | `P` continuous; the nudge closes by beat 22 (t = 10.9375) |
| Tap 3 at 10.9375 | 22 → 22 | 16 | 16 | 0 | On the grid |

### 5.5 Effect runtimes and banks (`engine/effects.py`)

§5.18's `EffectRuntime` (`phase`, `sizeEnvelope`, `memberPhase`) becomes a clock, versions with presence envelopes, and compiled member offsets.

```python
@dataclass(slots=True)
class Version:
    effect: CompiledEffect
    presence: Envelope                  # 0 → 1 entering, → 0 leaving or replaced (decision 9)

class EffectRuntime:                    # one running instance of one source; a Contributor
    key: str
    seq: int
    clock: EffectClock
    versions: list[Version]             # the newest last
    source: Source                      # absolute lanes (HTP, LTP, colour extras as snap at ½), refilled per tick
    relatives: list[Relative]           # one per relative layer, refilled per tick
    def update(self, now: float, scalars: EffectScalars) -> None: ...

class EffectBank:                       # the effects of one source: a playback's main or flash, or the programmer
    runtimes: dict[str, EffectRuntime]
    def retarget(self, now: float, effects: Sequence[CompiledEffect], timing: EffectTiming,
                 seqs: SeqRule, scale: float = 1.0) -> float: ...       # returns the completion time
    def update(self, now: float, scalars: EffectScalars) -> None: ...
    def align(self, master: SpeedMasterRuntime, now: float, before: Mapping[str, float]) -> None: ...
    def rerate(self, now: float, rateLevel: float | None) -> None: ...
    def remap(self, laneMap: NDArray[np.intp], posMap: NDArray[np.intp]) -> None: ...
    def clear(self) -> None: ...
    def contributors(self) -> Iterator[EffectRuntime]: ...
    def relatives(self) -> Iterator[Relative]: ...
```

`EffectScalars` holds what the bank's owner contributes per tick (decision 12): the HTP and LTP weights, `intensityScale`, the `size` fader level (1 when there is none), and the shared size-master levels.

**`retarget`** (decisions 9–11):
1. Evaluate every presence at `now`. With `scale` (re-activation of a releasing playback), each presence is multiplied by it, then fades back to its target with the timing below.
2. For each target instance, by `key`:
   - *not running*: a new runtime and clock, and a version entering (`timing.enter`, `sizeFadeIn` first);
   - *running with its newest version unchanged* (identity, else `same`): it keeps its fades; a version that was leaving fades back in with `timing.enter`;
   - *running and changed*: a new version entering with `timing.change`, and every older version leaving with the same timing. The clock re-rates to the new version's rate.
3. Running keys missing from the target: every version leaves with `timing.leave`.
4. Numbers follow `seqs` (decision 10). `mask` names the programmer's touched instance ids.
5. Return the latest end of the envelopes started, or `now`.

`EffectTiming` has three implementations:

| | enter | change | leave |
|---|---|---|---|
| `CueEffectTiming(cue)` | `sizeFadeIn`, else `cue.inTiming` | `cue.inTiming` | `cue.outTiming` |
| `UniformEffectTiming(t)` (chase steps, the programmer) | `sizeFadeIn`, else `t` | `t` | `t` |

**`update(now, scalars)`.** Per runtime:
1. `P = clock.position(now)`, then the base phase by direction (decision 4).
2. Per version and layer: `φ = b + layer.phase`, then the waveform or palette, then the layer's output: values for absolute layers, amounts for relative ones.
3. **One version (the steady state):** the arrays are the outputs, and the source's scalar weights are the scalars × presence × `d` (absolute). No per-lane weights exist.
4. **Several versions:** per lane, `value = Σ pᵥ·xᵥ / Σ pᵥ` and `weight = min(1, Σ pᵥ)` (absolute layers use `pᵥ·dᵥ`). The union of the versions' lanes and each version's positions in it are computed at retarget time, so a tick only scatters and divides.
5. Drop versions whose presence has settled at 0; a runtime without versions is dropped, and its clock with it.

The runtime is a Contributor in its bank's band: `seqs = (seq,)` when it has LTP or colour lanes, so it never splits. A relative-only runtime's source is absent.

**Invariants**, each a property test (§7):
- `retarget` never changes any output at `now`, values or weights: no jumps.
- `update` is a pure function of `now` between events.
- A change that only rescales `size` is an exact morph: `value(t) = lerp(old, new, f(t))`.
- Absolute values stay within their layer's range, and every weight within 0..1.

### 5.6 The relative pass (`engine/contributions.py`, `engine/resolver.py`)

```python
@dataclass(slots=True, kw_only=True)
class Relative:
    priority: int
    seq: int
    order: int                          # the layer's place in its cue (ties within one instance number)
    op: Literal["add", "multiply"]
    lanes: NDArray[np.intp]             # frame lanes, intensity included
    amounts: NDArray[np.float64]        # refilled per tick
    weights: NDArray[np.float64] | None # per lane (versions mixing), × weight
    weight: float
    clamp: tuple[float, float] | None
```

`gather` also collects the present contributors' relatives, sorted by `(priority, seq, order)`. `Resolver.resolve(sources, base, frame, relatives=())`:

1. **Absolute pass**, as now. When `relatives` is not empty, every distinct relative band `r` gets a coverage array `A_r`, zeroed per tick. Each source in a band above `r` raises `A_r` on its lanes to its effective presence: LTP and snap lanes directly, HTP positions through `intensityLanes`. Typically there is one relative band, and only the few sources above it (the programmer, override playbacks) do this work.
2. `frame[intensity] = value`, as now.
3. **Relative pass**, in order: `W = weight · weights · (1 − A_r[lanes])`, then
   - `add`: `frame[lanes] += amounts · W`;
   - `multiply`: `frame[lanes] *= 1 + (amounts − 1) · W`.
4. **Clamps**: the lanes of `add` contributions with a `clamp` are clipped once, after the pass (§7.7 clamps last).

Without relatives the resolver does exactly what it does now, at the same cost.

**The oracle** (`tests/reference_resolver.py`) gains the literal per-slot form: `A = max(c.weight for c in abs if c.priority > r.priority, default 0)`, then the two formulas in order, then the clamp. The property tests compare the two.

**Worked example.** A band-50 circle (size 15°) runs on MH 1, and a band-150 position look (pan 0°) fades in over 2 s on top of it:

| t | Look presence | Absolute pan (base −30°) | Circle weight | Result at a crest (+15°) |
|---|---|---|---|---|
| 0 | 0 | −30 | 1 | −15 |
| 1 | 0.5 | −15 | 0.5 | −7.5 |
| 2 | 1 | 0 | 0 | 0, suspended (§7.5) |

Read literally, §7.5 keeps the circle at full size until the look is fully present: just before t = 2 the crest is at 0 + 15 = 15°, and at t = 2 it drops to 0°, a 15° jump. Here every value is continuous, and so is the effect's share.

### 5.7 Playbacks with effects (`engine/playback_runtime.py`)

| | Phase 4 | Phase 5 |
|---|---|---|
| main | a `ContributionSet` (`SequencedSource`) | the same, plus a **main bank** retargeted with it |
| flash | a static `Source` | the same, plus a **flash bank** while main is idle (decision 16) |
| faders | `master`, `rate` (chases), `temp` | `size` (dynamics, autoStart/autoRelease), `rate` (chases and effects) |

**Every main retarget retargets the main bank** with the same cue and sequence rule:

| Event | Main bank |
|---|---|
| activate | `retarget(cue.effects, CueEffectTiming(cue), all(seq), scale=env)` |
| move (GO, BACK, GOTO) | `fresh(seq)` |
| auto-GO | `keep(activationSeq)` |
| chase step | `UniformEffectTiming(crossfade)`, `keep` |
| re-assert | `all(seq)`: renumbers, nothing fades |
| rebind (§5.10) | `keep` |

The completion time is the later of the slots' and the bank's, so a `follow` waits for both. Release changes nothing in the bank (decision 11), and going idle clears it.

**Per tick**, after `contributions.evaluate(now)`, `update` fills `EffectScalars` from the same scalars main uses and calls `bank.update`.

**`Playbacks.sources()`** yields, per live runtime, main, flash, the main bank's runtimes, then the flash bank's. Effects come after their playback's values, so a stable sort hands them ties (decision 7). `Playbacks.relatives()` yields both banks' relatives.

**Flash bank** (decision 16). When the flash becomes present while main is idle, it retargets to the current cue's effects at once (`UniformEffectTiming(Timing())`, `all(flashSeq)`). It clears when the flash goes away or main activates. Its scalars are the flash source's, with `d` = the size masters only.

**Faders** (decision 14). `size` faders start at 0. `set_fader` treats them like `master` faders for `autoStart` and `autoRelease`, without the threshold latch. A `rate` fader re-rates the chase (Phase 4) and the main and flash banks.

**Speed masters.** `Playbacks.tap` and `set_speed_level` iterate the live banks next to the chases (§5.4), and the engine passes the programmer's bank in too.

### 5.8 Masters: size, group, speed (`engine/masters.py`, `compiler/playbacks.py`)

- **`EngineRuntime`** keeps `masterLevels` (grand), and gains `groupLevels` and `sizeLevels`. The grand master stays the product of `masterLevels`.
- **Size levels** go in a dict shared with `Playbacks`, like `speed`, which every bank reads per tick.
- **`CompiledMaster.positions`** (group masters): the `intensityLanes` positions of the group's members' intensity slots. `compile_masters(show, slots)` computes them; masters are always rebuilt, so a group edit takes effect at once.
- **`group_factor(masters, levels) -> NDArray | None`**: the product of the group levels per intensity position, or `None` when every level is 1. It is recomputed on `SET_MASTER` of a group master and on a swap, never per tick.
- **Stage 9**: `frame[intensity] *= factor`, then the grand master and blackout as now. All of it acts on the output frame only, so setting a level back returns exactly the same frame (§12).

### 5.9 Engine loop and commands (`engine/loop.py`, `commands/`)

| §4.2 stage | Phase 5 |
|---|---|
| 1 | as Phase 4: due events, then commands and installs |
| 3–4 | `advance`, `update` (slots, then each bank's effects), the programmer's fades |
| 5 | effects evaluated inside the updates above: clocks, waveforms, version mixing |
| 6–7 | `gather` (contributors, then relatives), the absolute pass with coverage |
| 8 | the relative pass and its clamps (§5.6) |
| 9 | group masters, then the grand master; 10: blackout |
| 11–13 | unchanged |

**Applying commands:**

| Command | Engine |
|---|---|
| `SET_MASTER` | by the compiled master's kind: grand → `masterLevels`; group → `groupLevels`, then the factor; size → `sizeLevels`; speed → Phase 4, plus effect re-rates |
| `TAP` | chases and effect clocks re-align (§5.4) |
| `SET_FADER` on `size` / `rate` | §5.7 |

**Command types** (`commands/types.py`):

```python
class AddEffectCmd(TypedDict):       # programmer
    type: Literal["ADD_EFFECT"]
    effect: EffectInstance           # replaces a programmer effect with the same id

class RemoveEffectCmd(TypedDict):    # programmer
    type: Literal["REMOVE_EFFECT"]
    id: NotRequired[str]             # absent: every programmer effect
```

**The bus:**
- `MASTER_ARRIVES_IN` keeps only `fadeTime`, reported as "unassigned in the roadmap", like `swop`.
- `SET_MASTER` accepts grand, group, size and speed masters.

### 5.10 Programmer effects and live swaps (`session/`, `engine/install.py`)

**Programmer.**
- `Programmer.effects: tuple[EffectInstance, ...]` is content: it is in `same_content`, undone, restored, and autosaved in `session.json`. On load, an instance that no longer validates against the show is dropped, with a message.
- `ADD_EFFECT` checks the instance with the validator's effect rules (`validate_effect(show, instance)`, made public) and needs a non-empty `targets`.
- An effect whose template or targets vanish stays, dormant, like a value whose slot is gone.
- `build_frame` compiles the programmer's effects with the same `compile_effect` into `ProgrammerFrame.effects`. It also fills `touchedEffects`: the ids the command added or changed.
- `ProgrammerRuntime` gains a bank at band 100. `install` retargets it with `UniformEffectTiming(fadeTime)` and `mask(seq, touchedEffects)`, or to nothing while blind. A command that touches only effects still takes a number.
- The programmer's static values and its effects are separate contributors in band 100, ordered by their numbers, like a playback's.

**Live swap** (`Engine._swap`, phase-4-plan decision 14). A swap does five things for effects:
1. **Remap.** When the slot table changed, every bank remaps its versions with the lane maps (`CompiledEffect.remapped`). Lanes that are gone are dropped.
2. **Rebind.** Each running playback's main bank is retargeted, with the `keep` rule and `CueEffectTiming` of its (re-pointed) cue, whenever main is. An edited size or template therefore cross-fades on the same clock. An edited rate re-rates without a jump. An unchanged instance (`same`) carries on untouched.
3. **Flash.** A running flash bank is retargeted the same way, at once.
4. **Programmer.** The frame that arrives with the swap retargets its bank.
5. **Masters.** Size and group levels are carried by id; new ones start at their initial level, and the group factor is recomputed.

### 5.11 Recording effects (`commands/record.py`)

`RECORD_CUE` (§15.3) copies the programmer's effects into the cue's `effects` next to its entries:

| | Values (Phase 3–4) | Effects |
|---|---|---|
| `filter` | by family | an instance is recorded if any of its template's layers is in a filtered family |
| create / *replace* | the entries are the programmer's | the effects are the programmer's |
| *merge* | restrict, then append | by `id`: replace an existing instance, append a new one |
| *remove* | restrict | delete the cue's instances whose `id` the programmer holds |
| targets | group cover, unless `freeze` | a `group` reference when the targets are exactly a group's members, in order; else a `targets` list |
| tracking list | values equal to the inherited ones are left out | an instance equal to the inherited one with the same `id` is left out |

- The message counts them: `recorded cue 9/4: 0 entries, 1 effect`.
- A programmer holding only effects records them. Phase 3 fails a record when no programmer value matches the filter; now it fails only when neither a value nor an effect does.
- `RECORD_PRESET` ignores effects.
- The console's `record slot` gives a cue holding only effects a `size` fader (decision 14).

### 5.12 Effect library and console (`library/effects.json`, `session/library.py`, `console/`)

**The library** holds templates with console defaults for their instances:

| Template | Layers | Console defaults |
|---|---|---|
| Circle | pan `add` sine; tilt `add` sine, +90° | size 20 |
| Pulse | intensity `multiply` sine | size 0.7 |
| Wave | intensity `absolute` sine | low 0, high 1 |
| Chase | intensity `absolute` square, duty 0.25 | phase 0–360 |
| Saw | intensity `absolute` sawDown | phase 0–360 |
| Sweep | pan `add` triangle | size 30 |
| Flicker | intensity `multiply` random, smooth | size 0.5 |
| Rainbow | colour palette red, green, blue, `fade` | phase 0–360 |

`EffectLibrary` loads it like `ProfileLibrary`. `effect add` embeds a library template into `effects` the first time the show uses it, as `fixture add` embeds profiles.

**Grammar:**

| Area | Syntax | Becomes |
|---|---|---|
| Programmer | `effect add "<template>" [id <id>] [hz <rate> \| bpm ["<master>"] [x <m>]] [size <s>] [low <v> high <v>] [phase <start> <end>] [groups N] [blocks N] [wings N] [forward\|reverse\|bounce] [fadein <s>] [sizemaster "<name>"] [speedmaster "<name>"]` | An `ADD` of the library template if the show lacks it, then `ADD_EFFECT` with the selection as targets. Defaults: the template's, a BPM rate ×1 on the show's only speed master (else 1 Hz), phase 0–0, 1 group, 1 block, 1 wing, `forward`, id `fx<n>` |
| | `effect remove <id>`, `effect clear` | `REMOVE_EFFECT` |
| Templates | `effect template add "<name>" <JSON layers>` | `ADD` to `effects` |
| Recorded effects | `cue L/C effect <id> <prop> <JSON value>` | `SET` of `[…, "effects", {"id"}, prop]` |
| Masters | `master add size "<name>"`, `master add group "<name>" group N` | `ADD` to `masters` (names are unique, as in Phase 4) |
| Query | `list effects`; `programmer` and `library` list effects; `list cues L` counts each cue's effects | — |

- A console line that becomes two commands (a template, then the effect) runs them in order and stops at the first failure: a new `SubmitAll` action. They are two undo steps, like any two console lines.
- `help` is generated from the module docs, as before.

### 5.13 Snapshot, status line, bindings, validation and the limitation report

- **Snapshot and status line.** `masterLevels` lists grand, group, size and speed levels in show order, so autosave and recovery restore them with `SET_MASTER`. The status line shows a `size` fader's level, as it does a `master` fader's. Effect phases are not published; they change every tick (phase-4-plan §5.11).
- **Bindings.** A `master` action on a group or size master sends `SET_MASTER`.
- **Validation** (`model/validate.py`, semantic pass). Errors:
  - a template without layers, or with two `absolute` layers on one attribute;
  - a scalar layer on an attribute that snaps (`positionSpeed`);
  - `pulse` with a negative part or `attack + width + decay > 1`; `step` without steps; `curve` without points or with x not strictly ascending; a colour layer with an empty palette;
  - an instance `size` that is negative or not finite; above 1 on a template with a `multiply` layer;
  - `low`/`high` that are not numbers, or missing for an absolute scalar layer on an attribute without a registry range.

  Warnings:
  - palette colours with `w`, `a` or `uv`: they are derived;
  - a `speedMasterId` on a BPM effect that names another master: it is ignored.
- **The limitation report** (header `Ignored in Phase 5:`) keeps:
  - `crossfade` faders and `goto` buttons (Phase 6);
  - `swop`, and fade-time masters (unassigned);
  - pages, surfaces, soft pickup and feedback (Phase 6);
  - limits and park (Phase 7);
  - `holdLastFrameOnEngineStall: false`.

  The effects, `size` faders, and group and size master lines go.

### 5.14 The done criterion: `examples/phase5-effects.busk`

Run after `phase3-build.busk` and `phase4-song.busk`, on the show they saved:

```
master add size "FX"
master add group "Wash level" group 2

# ------------------------------------------------ circle on the heads
sel group 1
effect add "Circle" size 15 bpm x 0.5 phase 0 180 fadein 1 sizemaster "FX"
record slot 11 "Circle"                        # an effect-only cue: a size fader
clear

# ------------------------------------------------ pulse on the washes
sel group 2
effect add "Pulse" size 0.8 phase 0 360 sizemaster "FX"
record slot 12 "Pulse"
clear

# ------------------------------------------------ wave across the bar
sel group 3
effect add "Wave" phase 0 360 wings 2
record slot 13 "Bar wave"
clear

# ------------------------------------------------ the Chorus gets a colour cycle on the bar
sel group 3
effect add "Rainbow" id rainbow hz 0.25 phase 0 360
record cue 9/4 merge
clear

# ------------------------------------------------ nanoKONTROL2
bind "nanoKONTROL2" cc 1 19 fader 11           # knob 4: circle size
bind "nanoKONTROL2" cc 1 20 fader 12           # knob 5: pulse size
bind "nanoKONTROL2" cc 1 21 fader 13           # knob 6: bar wave
bind "nanoKONTROL2" cc 1 22 master "FX"        # knob 7: size master
bind "nanoKONTROL2" cc 1 58 button 11 1        # track ◀: circle on/off
bind "nanoKONTROL2" cc 1 59 button 12 1        # track ▶: pulse on/off
bind "nanoKONTROL2" cc 1 60 button 13 1        # marker set: wave on/off
save
```

**Checkpoints of `test_effects_show.py`.**
- The performance part runs on a fresh engine built from the saved show; "Speed 1" starts at 120 BPM at t = 0, so beats = 2t until the taps.
- Heads are the two spots (Audience: MH 1 −30°, MH 2 +30°, tilt 40°; slot 6 fades in over 2 s with `followFader`), washes the ML-56s 201–204, and the bar the PiX's 12 cells.
- Phase offsets: the heads 0 and ¼ cycle (0–180° over 2); the washes 0, ¼, ½, ¾; the bar positions 0 1 2 3 4 5 5 4 3 2 1 0, sixths of a cycle (wings 2).
- Expected values are logical and computed by hand.

| t (s) | Command | Check |
|---|---|---|
| 0 | `fader 1 1`, `fader 6 1`, `fader 11 1` | Warm at once (all 0.8); Audience fading in; the circle starts on the grid (`P = t`) and grows over 1 s |
| 0.5 | | MH 1 pan 0.0 (Audience a quarter in: −7.5; the circle at half size: +7.5), tilt 10.0 |
| 2.0 | | MH 1 pan −45, tilt 40; MH 2 pan 30, tilt 55 |
| 2.25 | | MH 1 pan −30, tilt 55; MH 2 pan 45, tilt 40 |
| 3 | `fader 12 1` | the pulse starts at beat 6: `P = 2t − 6` |
| 3.125 | | washes 0.48, 0.8, 0.48, 0.16 (0.8 × (1 − 0.8·(1 − w))) |
| 4 | `master "FX" 0.5` | |
| 4.0 | | MH 1 pan −37.5; MH 2 tilt 47.5; washes 0.48, 0.64, 0.8, 0.64 |
| 5 | `master "Wash level" 0.5` | washes 0.24, 0.32, 0.4, 0.32 |
| 5.5 | `master "Wash level" 1` | the frame at 5.75 equals a run without the two group-master commands |
| 6 | `fader 13 1` | the wave starts at beat 12: `P = 2t − 12` |
| 6.25 | | cells 1 and 12 at 1.0 (the crest); the other ten at Warm's 0.8 (HTP) |
| 7 | `release 1` | Warm releases over 1 s |
| 8.5 | | bar 0, .25, .75, 1, .75, .25, .25, .75, 1, .75, .25, 0; washes 0 (the pulse has nothing to scale) |
| 10, 10.46875, 10.9375, 11.40625 | `tap` × 4 | 128 BPM. At each tap the frame equals the frame without it (the nudge starts at 0); §5.4 lists the pulse's numbers |
| 11.171875 | | beat 22.5, on the 128 BPM grid: MH 1 pan −30, MH 2 pan 37.5 |
| 11.875 | | beat 24: MH 1 pan −37.5; the bar as at 8.5 |
| 12.8125 | `release 11` | beat 26: the circle releases over 1 s |
| 13.28125 | | beat 27: MH 1 pan −26.015625 (the crest, +7.5 × 0.53125) |
| 15 | `goto 9 4`, `fader 9 1` | the Chorus with the bar cycle: `P = (t − 15)/4`, fading in over 0.5 s |
| 19.0 | | bar colours: cell 1 red, 3 (.5, .5, 0), 5 green, 7 (0, .5, .5), 9 blue, 11 (.5, 0, .5) |
| 19.5 | — | the Outro follows (4 s after the Chorus completes at 15.5); the cycle tracks |
| 21.0 | | cell 1 (0, .5, .5): the cycle's clock did not restart |
| 25 | `release 9` | the cycle fades out with the song over 3 s, still moving |
| — | — | The whole run at 100 Hz and on a random irregular schedule gives byte-identical frames at every checkpoint, and so does save → load |

A second, short test runs on `session_harness.Live` with the circle up. `sel fixture 101` and `set pan 0` hold MH 1's pan at exactly 0, while its tilt and MH 2 keep circling. `clear` brings the circle back on MH 1's pan.

The golden DMX frames (`tests/golden/phase5_frames.json`) are produced once at the checkpoints and reviewed by hand against these values.

### 5.15 Performance

**Expected cost.**
- A running instance costs a few vector operations per layer per tick over its lanes: phase, waveform and output. A circle on 640 heads is about 1 300 lanes.
- Version mixing only runs during changes.
- The relative pass is a few fancy-index updates per relative layer. Coverage costs one masked maximum per source *above* the relative band, about 20 on the reference rig.
- With 20 effects the estimate is +1–2 ms per tick: inside the 10 ms gate, and around §19's 4 ms target.

**Benchmarks** (`test_perf.py`, `-m perf`):
- `busking_benchmark_rig(…, effects=20)` adds 20 effect playbacks over the 60 mid-fade looks, BPM-locked to `m-speed`:
  - circles on `g-heads` and per-universe head groups;
  - pulses on `g-washes`;
  - waves on per-universe cell groups;
  - colour cycles on `g-cells`.
- **Tick with effects:** gate p99 < 10 ms; the result is recorded against the 4 ms target.
- **Appendix A:** the busking tick now runs the Slow Pulse (`SET_FADER pb-pulse 1` is added to its commands). Gate p99 < 1 ms.
- **Edit latency:** `bench/edit_latency.py` is re-run; compiling effects adds to cue-list compiles. The demo-rig target stays at 0 overruns and p95 ≤ 50 ms.

If the 4 ms target is missed, in order:
1. Evaluate the layers of all instances that share a waveform kind in one call: concatenate their phases once per retarget.
2. Skip the coverage arrays when no source above the relative band touches a relative lane (a lane mask per source version, cached).
3. Cache `φ − floor(φ)` buffers per layer, and fuse the absolute lerp with `out=`.

---

## 6. Implementation steps

Each step follows TDD: write the listed tests first, then make them pass. Engine tests use a `FakeClock` and call `engine.tick(now)` directly. **Every step ends with the whole suite green** (pytest, ruff check, ruff format --check, mypy). The steps are sized so that two fit in one working session, as in Phase 4. Steps 2–6 build pure pieces with their own tests; nothing reaches the engine before step 7.

1. **Baseline.** Run `uv run pytest` and `uv run pytest -m perf -s`, and record the numbers. → *verify:* green; the numbers are noted under step 16 for comparison.
2. **Validation and waveforms.**
   - Add the §5.13 effect rules to the validator, and make `validate_effect` public.
   - Write `engine/waveforms.py`.

   → *verify:*
   - `test_waveforms.py`:
     - each formula at its key phases, with a range of 0..1;
     - `pulse` with zero-length ramps;
     - `random` deterministic per (seed, member, cycle), and `smooth` continuous across cycles (hypothesis);
     - `curve` continuous across the cycle boundary;
     - vectorised output equals a scalar transcription.
   - `test_validate.py` covers every new error and warning.
   - Appendix A still validates with 0 errors and 0 warnings.
3. **Compiled effects.** Member offsets, `compile_effect`, `CueCompiler.effect`, `CompiledCue.effects` (own effects only, no tracking yet) and `outTiming`; the memo reads templates. → *verify:*
   - `test_phase_spread.py`:
     - §10.2 cases for wings (even and uneven N), blocks and groups;
     - N = 1;
     - offsets evenly spaced over `start…end` (hypothesis).
   - `test_effect_compile.py`:
     - Appendix A's pulse as golden arrays;
     - members without the attribute;
     - `low`/`high` defaults and clamping;
     - palettes per member with preset scopes;
     - dropped members and do-nothing effects as compile warnings;
     - `same`, `without` and `remapped`.
   - `test_compile_incremental.py`: an edited template or palette preset recompiles exactly the lists that read it.
4. **The relative pass.** `Relative`, coverage, ordering and clamps in the resolver; the oracle's §7.5. → *verify:*
   - `test_resolver.py`: add and multiply; their order; suppression by a full higher band; continuous suppression mid-fade (the §5.6 table); the same band not suppressing; clamps on ranged attributes; no relatives meaning the exact Phase 4 path.
   - `test_resolver_properties.py` (hypothesis): random sources with relatives match the extended oracle.
5. **Effect clocks.** `EffectClock`; `grid_position` moved out of `ChaseClock`. → *verify:* `test_effect_clock.py`:
   - Hz positions and rebase on a rate change;
   - BPM start on the grid;
   - the tap nudge: continuous at the tap, on the grid one beat later, and a second tap mid-nudge (the §5.4 table);
   - rate changes from the master's step and the rate fader;
   - `speedMasterId` on Hz effects.

   `test_chase.py` is unchanged and green.
6. **Effect runtimes and banks**, without the engine. → *verify:* `test_effect_runtime.py`:
   - enter with `sizeFadeIn` or the in timing; leave with the out timing while still moving; change as a cross-fade on one clock;
   - each sequence rule;
   - completion times;
   - `scale` folding;
   - steady state without per-lane weights;
   - remap;
   - (hypothesis) the four §5.5 invariants under random retargets.
7. **Effect playbacks in the engine.**
   - Main banks for single-cue lists, stages 5 and 8, `size` and `rate` faders.
   - Size masters through `SET_MASTER`, and speed-master taps and steps reaching effect clocks.
   - The bus accepts size masters.

   → *verify:*
   - `test_effects_engine.py`:
     - Appendix A's pulse through the engine, logical values by hand;
     - an absolute wave over a static look (HTP);
     - a colour cycle over a static colour (it wins ties);
     - a release fading a moving effect;
     - `size` fader autoStart, autoRelease and dynamics;
     - a `rate` fader;
     - a size master;
     - taps;
     - schedule independence.
   - The tests that asserted effects, `size` faders or size masters were ignored are updated and listed in the step's commit message: `test_limitations.py` (Appendix A's 4 ignored features become 2), the `test_cli.py` limitation block, and the `test_bus.py` and `test_bindings.py` size-master rejections.
   - `test_perf.py`'s Appendix A tick sets the pulse's fader.
8. **Effects in sequences, chases and tracking.** Tracking of effects in the compiler; banks retargeted by every move, auto-GO and chase step; completion includes effects; `SELECT_PLAYBACK` sees effect targets. → *verify:*
   - `test_tracking.py`: instances track by id, are replaced by id, trimmed by releases (and dropped when empty), stopped by `block`; a cue's own effects are never trimmed by its own releases; non-tracking lists hold their own effects.
   - `test_engine_sequences.py`:
     - GO with an entering, a changing and a leaving effect;
     - a later GO's value on top of a tracked effect, and an auto-GO's value under it;
     - `follow` waiting for an effect's fade;
     - GOTO onto the same instances as stepping (BPM ×1: the same phase too).
   - `test_chase.py`: a chase whose steps carry effects.
9. **Group masters.** The compiled positions, the factor, stage 9, the bus and bindings. → *verify:*
   - `test_masters.py`: the product of overlapping group masters; intensity only; before the grand master; non-destructive (identical frame and runtime state when set back).
   - `test_bus.py`, `test_bindings.py`: group and size masters accepted.
10. **Flash and `temp` with effects.** The flash bank. → *verify:* `test_playback_runtime.py` and `test_effects_engine.py`:
    - a held flash runs the effects of an idle playback in its band;
    - LTP layers only with `includeLtp`;
    - nothing doubles while main is active;
    - activating main during a held flash hands over on the beat grid;
    - a `temp` fader scales the flashed effects.
11. **Live swaps with effects.** Bank rebind and remap; master levels carried. → *verify:* `test_live_swap.py`:
    - an edited `size` cross-fades on the same clock;
    - an edited template cross-fades;
    - an edited rate keeps the position continuous;
    - an unchanged instance is not touched;
    - a patch move remaps a running effect mid-change;
    - deleting an effect from the current cue fades it out with the out timing;
    - a speed master edit keeps BPM effects on the grid.
12. **Programmer effects.** `ADD_EFFECT`, `REMOVE_EFFECT`, `Programmer.effects`, frame compile, the programmer's bank, autosave. → *verify:*
    - `test_programmer.py`: add, replace by id, remove one or all, clear, dormant effects, JSON round trip.
    - `test_session.py`: undo and redo of effect commands; blind; `touchedEffects`.
    - `test_engine_programmer.py`: a programmer circle runs at band 100; it enters and leaves over the fade time; a programmer pan value suspends a band-50 circle and `clear` restores it; blind on and off.
    - `test_autosave.py`, `test_recovery.py`: programmer effects and group and size levels come back after a SIGKILL; an invalid saved effect is dropped with a message.
13. **Recording effects.** → *verify:* `test_record_cue.py`:
    - create, replace, merge and remove by id;
    - the family filter;
    - a group reference only for an exact, ordered member list (and never with `freeze`);
    - a tracking list leaving out an inherited equal instance;
    - the message counts;
    - Appendix A's pulse cue rebuilt from the programmer equals the original.
14. **Effect library and console.** `library/effects.json`, `EffectLibrary`, the §5.12 grammar, `SubmitAll`, the `record slot` default fader. → *verify:*
    - `test_console_parser.py`: at least one case per §5.12 row; defaults (rate from the only speed master, id `fx<n>`); errors (`no template 'X' in the library`, a bad waveform JSON, `bpm` without a speed master, `master add group` without a group).
    - `test_console.py`: a template embedded once; `list effects`; `programmer` listing effects; `list cues` counts.
    - Every library template validates and compiles on Appendix A's rig.
15. **Snapshot, status line, limitations, recovery.** → *verify:*
    - `test_cli.py`: a `size` fader's level on the status line; the limitation block.
    - `test_limitations.py`: the new list under `Ignored in Phase 5:`.
    - `test_engine_busking.py`: snapshot `masterLevels` lists group and size levels; effects running publish no snapshots.
16. **Benchmarks** (§5.15). → *verify:* the gates pass, and the numbers are recorded here, next to step 1's baseline.

    **Step 1 baseline** (2026-10-12, before any Phase 5 code; 1685 passed, 1 skipped):
    - Appendix A busking tick: mean 0.061 ms, p99 0.096 ms, max 0.348 ms.
    - Reference rig, 60 playbacks: mean 1.988 ms, p99 2.936 ms, max 3.120 ms; resolve alone mean 0.768 ms, p99 1.494 ms.
    - 60 cue transitions: mean 3.297 ms, p99 4.334 ms, max 5.365 ms.
    - 60-GO burst: mean 17.670 ms, p99 19.953 ms, max 29.197 ms; ticks between bursts mean 3.513 ms, p99 4.932 ms.
    - 8 chases: step ticks mean 4.085 ms, p99 5.137 ms; other ticks mean 2.264 ms, p99 3.307 ms.
    - Convert median 0.288 ms (p99 0.987 ms); 64-universe sACN output median 0.073 ms per cycle.

    **Step 16 results** (2026-10-13, after step 15; 2020 passed, 1 skipped; all 8 perf gates pass):
    - **20 effects over the 60 looks** (`busking_benchmark_rig(effects=20)`: 5 circles, 5 pulses, 5 waves, 5 colour cycles from the built-in library, band 100, BPM-locked at ×0.25 … ×2; 108 780 effect lanes, 15 relative contributions per tick, 20 looks above the relative band): **mean 3.384 ms, p99 3.560 ms, max 3.664 ms**. Gate (p99 < 10 ms) passes, and §19's 4 ms target is met: about +1.5 ms over the same rig without effects, inside §5.15's +1–2 ms estimate. None of §5.15's three fallback optimisations was needed.
    - Appendix A busking tick, Slow Pulse running at full size: mean 0.075 ms, p99 0.087 ms, max 0.139 ms (gate p99 < 1 ms).
    - Reference rig, 60 playbacks: mean 1.850 ms, p99 2.164 ms, max 2.303 ms; resolve alone mean 0.730 ms, p99 0.766 ms.
    - 60 cue transitions: mean 3.079 ms, p99 3.675 ms, max 6.829 ms.
    - 60-GO burst: mean 16.467 ms, p99 18.038 ms, max 18.775 ms; ticks between bursts mean 3.209 ms, p99 3.912 ms.
    - 8 chases: step ticks mean 3.791 ms, p99 4.052 ms; other ticks mean 2.083 ms, p99 2.379 ms.
    - Convert median 0.271 ms (p99 0.303 ms); 64-universe sACN output median 0.071 ms per cycle.
    - **Edit latency** (`bench/edit_latency.py`, GIL switch interval 0.1 ms): demo rig **0 overruns** in 791 ticks, edit p95 7.0 ms (hard target ≤ 50 ms met), max tick 7.2 ms. Reference rig edit p95 124.5 ms (target 250 ms met), 130 overruns in 1 558 ticks (max tick 51.9 ms), against Phase 4's 155–175: the same GIL convoy (phase-4-plan step 18), an input for Phase 7's process split.
17. **Done criterion.** Write `examples/phase5-effects.busk`, `test_effects_show.py` and the goldens. → *verify:* `test_effects_show.py` checks that:
    1. every line of the three scripts succeeds;
    2. the saved show equals `tests/golden/phase5_effects_show.json`, and `busk validate` reports 0 errors and 0 warnings;
    3. every §5.14 checkpoint matches its hand-computed logical values and the golden bytes;
    4. the taps move nothing at the tap and lock one beat later;
    5. the 100 Hz and irregular-schedule runs give byte-identical frames;
    6. save → load → a fresh engine gives the same frames;
    7. the programmer test of §5.14 passes.
18. **Manual demo on the rig.** Follow the §8 checklist with the nanoKONTROL2 and the Phase 3 rig. → *verify by eye:* the circle and the pulse lock to tapped tempo without jumps, the knobs act as listed, the Chorus's colour cycle carries on into the Outro, and the run ends with 0 overruns.
19. **README and full verification.** Add an "Effects checklist (Phase 5)", the decisions taken beyond the plan, the spec gaps and the benchmark numbers. Update "Next" and the `pyproject` description. → *verify:* §8.

---

## 7. Acceptance tests (summary)

| Test file | Proves |
|---|---|
| `test_waveforms.py` | The nine waveforms: formulas, ranges, determinism, continuity |
| `test_phase_spread.py` | §10.2 wings, blocks, groups and even distribution |
| `test_effect_compile.py` · `test_compile_incremental.py` (extended) | Compiled instances, palettes, low/high, warnings; recompiles that follow templates |
| `test_validate.py` (extended) | Every effect rule |
| `test_resolver.py` · `test_resolver_properties.py` (extended) | The relative pass, its order, continuous suppression and clamps against the §7.5 oracle |
| `test_effect_clock.py` | Hz and BPM positions, grid start, tap nudges, rate changes |
| `test_effect_runtime.py` | Enter, leave, change, mixing, sequence rules, the four invariants |
| `test_effects_engine.py` | Effect playbacks through the engine: absolute and relative, faders, masters, release, taps, flash, schedule independence |
| `test_tracking.py` · `test_engine_sequences.py` · `test_chase.py` (extended) | Effects tracked by id, trimmed, blocked; effects through GO, BACK, GOTO, auto-GOs and chase steps |
| `test_masters.py` (extended) | Group masters: product, intensity only, non-destructive |
| `test_live_swap.py` (extended) | Edited effects cross-fade on their clock; remaps; rate edits without jumps |
| `test_programmer.py` · `test_session.py` · `test_engine_programmer.py` (extended) | Programmer effects: commands, undo, blind, fade time, band 100, suspension |
| `test_record_cue.py` (extended) | Effects recorded, filtered, merged, tracked, referenced by group |
| `test_autosave.py` · `test_recovery.py` (extended) | Programmer effects and group and size levels survive a crash |
| `test_bus.py` · `test_bindings.py` · `test_limitations.py` · `test_cli.py` · `test_engine_busking.py` (extended) | Group and size masters accepted and bound; the shorter limitation list; the status line; snapshots |
| `test_console_parser.py` · `test_console.py` (extended) | The §5.12 grammar; the library |
| `test_golden_7_8.py` · `test_song_stack.py` (unchanged) | The §7.8 example and the Phase 4 song still hold |
| `test_effects_show.py` | The done criterion |
| `test_perf.py` (`-m perf`, extended) | Ticks with 20 effects fit the budget; Appendix A with its pulse running |

---

## 8. Verification

```bash
uv run pytest                                           # all green
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run pytest -m perf -s                                # gates pass; numbers recorded
uv run python bench/edit_latency.py                     # demo rig: 0 overruns, p95 ≤ 50 ms
uv run busk new /tmp/busk-demo/club.show --title "Club Night"
uv run busk run /tmp/busk-demo/club.show --script examples/phase3-build.busk --duration 1
uv run busk run /tmp/busk-demo/club.show --script examples/phase4-song.busk --duration 1
uv run busk run /tmp/busk-demo/club.show --script examples/phase5-effects.busk
#   busk> list effects               → Circle, Pulse, Wave, Rainbow (embedded from the library)
#   busk> fader 1 1                  → Warm
#   busk> fader 6 1                  → the heads on the audience
#   busk> fader 11 1                 → the heads circle, growing over 1 s, on the beat
#   busk> fader 12 1                 → the washes pulse in a wave
#   busk> tap  (×4, in time)         → both lock to the taps, without a jump
#   busk> master "FX" 50%            → both at half size
#   busk> quit
uv run busk validate /tmp/busk-demo/club.show           # → 0 errors, 0 warnings
```

**Effects checklist (Phase 5)**, for step 18, with the Phase 3 setup (nanoKONTROL2, sACN rig, `--iface`):

1. Run the three scripts. `Ignored in Phase 5:` lists nothing for this show.
2. Fader 1 up (Warm), fader 6 up (Audience). Knob 4 up: the heads circle around the audience position, half a revolution per beat, MH 2 a quarter turn behind MH 1. Track ◀ toggles the circle.
3. Knob 5 up: the washes pulse in a wave that travels across the four of them, once per beat.
4. Tap "cycle" in time with music: the circle and the pulse follow within a beat, without a jump.
5. Knob 7: both shrink and grow together (the "FX" size master). `master "Wash level" 50%`: the washes at half; back to 100 %: unchanged.
6. Fader 1 down to 0 (Warm releases), knob 6 up: the bar shows a mirrored wave from the centre outwards. While Warm is still up, only the crests rise above it (HTP).
7. `sel fixture 101`, `set pan 0`: MH 1 stops moving across, still nodding in tilt. `clear`: it circles again.
8. Knob 1 up, then ▶ to the Chorus: the bar runs the colour cycle over its white. Four seconds after the Chorus lands, the Outro starts and the cycle carries on without restarting.
9. The run ends with 0 overruns.

---

## 9. Spec deviations and gaps

**Deliberate deviations**

- **No accumulated phase** (decisions 1–2). §10.1's `phase += rate·dt` becomes a position rebased at events, as Phase 4 did for chases. A tap *nudges* BPM effects back onto the grid over one beat, where chases step.
- **Continuous suppression** (decision 13). Relative contributions are scaled by `1 − A`, the presence of higher bands. §7.5's literal rule (suppressed only at weight exactly 1) is the special case `A = 1`; without the change, every override fading in over an effect ends with a jump.
- **`sizeEnvelope` is split** (decisions 9 and 11). It becomes an entering fade (`sizeFadeIn`, else the cue's in timing) and the playback's release envelope, which already scales everything the playback contributes. §10.4's "1 → 0 over the playback's release time" is kept, just not applied twice.
- **Dynamics scale an absolute layer's presence** (decision 6). §10.4 defines "effective size" only through the `add` and `multiply` formulas.
- **Effects layer over their cue's values**, ordered by sequence numbers, and win ties (decision 7). §7 and §9 do not say how a playback's effect and its own value on one slot combine.
- **Versions mix by presence** (decision 9). An edited or re-cued instance cross-fades on its running clock.
- **`size` faders start at 0** and honour `autoStart`/`autoRelease` (decision 14). Phase 4's decision applied those only to `master` faders.
- **Phase spread is compiled in `compiler/`**, not `engine/phase_spread.py` (§21), because the compiler never imports the engine.
- **New commands:** `ADD_EFFECT`, `REMOVE_EFFECT`.

**Gaps decided here (to fold back into the spec)**

- **Waveforms:** `pulse`'s parameters as fractions of a cycle; `random` as a hash per member and cycle, with smoothstep for `smooth`; `curve` piecewise-linear and periodic (decision 3).
- **Directions:** `reverse` runs the phase backwards; `bounce` folds it (decision 4).
- **Phase spread:** the wing size, mirroring of odd wings, `M` as the number of positions, and members without the attribute (decision 5).
- **Layer values:** `low`/`high` defaults and that they apply to every scalar absolute layer; the palette position (a sawtooth through the palette, wrapping); colour layers deriving their extras (decision 6).
- **Tracking effects** by instance id, with releases and `block` (decision 8).
- **Transition timing for effects:** enter, change and leave, and what "completes" includes (decision 9).
- **Masters:** `speedMasterId` on Hz and BPM effects; size masters; group masters as a product, before the grand master (decision 15).
- **Flash and `temp`** with effects: only while main is idle (decision 16).
- **Programmer effects** at band 100, and how `RECORD_CUE` records effects: filter, merge and remove by id, group references, tracking (decisions 17, §5.11).
- **Element 0 vs whole fixture** for effects: a target is exactly its element (decision 5).

**Still open after Phase 5**

- **A static → effect hand-over inside one playback dips.** When a GO swaps a playback's static value on a slot for an effect, without the value tracking underneath, the value fades out while the effect fades in, and the slot passes partly through what is below. Effects over tracked values (the usual case) do not dip. The fix would be a hand-over at retarget: the effect starts from the value's current state at full presence.
- **The fade-time master** (decision 18).
- **Bar alignment**, for effects as for chases: an effect cycling every 4 beats starts on *a* beat.
- **GOTO and phase:** Hz effects reached by GOTO start their clocks at the GOTO, so their phase differs from stepping.
- **Strobe-like intensity effects** (fast `square` or `pulse` on intensity) are not covered by the strobe-rate cap (§12, Phase 7). The cap should also bound intensity effects' frequency.
- **Matrix effects** on a group's 2-D `layout`, and discrete effects.
- The open items of Phases 2–4 (README "Spec gaps"), including the Phase 4 GO-burst and edit-overrun misses.

---

## 10. What Phase 6 changes

- **Surfaces and network** (§22 Phase 6):
  - pages, with the engine owning the current page (phase-2-plan §9);
  - soft takeover, LED and motor-fader feedback, latching blackout;
  - OSC, the web remote (snapshots over the §16 API), ArtPoll discovery, sACN discovery, DMX-USB output.
- **Deferred from Phase 4:** `crossfade` faders (a fade evaluated from fader progress) and `goto` buttons (a cue-number entry).
- **Deferred from Phase 4–5:** the blind preview resolve (§7.6), which the UI needs to show blind programmer values *and effects*.
- **Effects in the UI:** the snapshot may need running effects per playback and their sizes. Phases stay out of it; a remote derives them from tempo and time. Templates get an editor beyond JSON layers.
- **To decide with the surfaces:** the fade-time master (decision 18), `swop`, and whether external tempo (MIDI clock, Ableton Link) arrives as an input surface driving `SpeedMasterRuntime`.
