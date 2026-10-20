# Phase 2 — Busking core: implementation plan

> Source spec: `busking-console-architecture-python.md` (§22, Phase 2). Builds on `phase-0-plan.md` and on Phase 1. Phase 1 has no plan yet, so §3 lists exactly what this plan assumes Phase 1 delivers.

> **Step 0 — Phase 1 / 1.5 contract mapping** (done before implementation):
>
> | §3 need | Actual Phase 1 / 1.5 code |
> |---|---|
> | Slot table | `CompiledShow.slots: SlotTable` → `.slots: tuple[Slot, ...]` (`index`, `target`, `attribute`, `laneOffset`, `laneCount`, `options`, `wheels`, `extras`, `.lanes` slice). Lookup `SlotTable.find(target, attribute) -> Slot \| None` (and `byKey`) |
> | Logical frame | `SlotTable.laneCount`, `SlotTable.defaultFrame` (read-only; zoom midpoint resolved) |
> | Value encoding | `compiler.lanes.encode_value(slot, value) -> tuple[float, ...]`; raises `EncodeError` for a missing option instead of returning `None` |
> | Virtual intensity | Yes: `rig.ElementInfo.virtualIntensity` gives such elements an `intensity` slot |
> | Shutter guard | Yes: built into the default frame |
> | Conversion | `Converter(compiled.plan).convert(frame, out)` |
> | Colour mixing | RGBW uses `w = min(r, g, b)`; the §7.8 golden bytes hold unchanged |
> | Engine | `Engine.tick(now)` copies a logical frame into `_work`, copies the base images, converts, publishes |
> | Network output | **Delivered by Phase 1.5** (`output/sacn.py`, `output/scheduler.py`, `--console` sink): step 9 is dropped and decision 13 is superseded by send-on-change + keep-alive (phase-1.5-plan §10) |
> | Masters | Phase 0's schema already has an optional `initialLevel` on every master, so decision 6 uses it for grand masters (default 1.0) |

## Context

The spec scopes Phase 2 as *"Groups, presets (scoped), single-cue cue lists, playbacks, contributions, HTP/LTP resolver, release, flash, exclusivity, grand master, blackout"*. It is done when *"the §7.8 example passes as a golden test; operator can busk with MIDI faders"*. Phases 0–2 together make up the spec's "minimum viable busking engine".

After Phase 1 the engine converts a logical frame to DMX, but that frame only ever holds defaults. Phase 2 fills in §4.2 stages 1–10: commands arrive, playbacks become sources, the resolver merges them, and masters and blackout are applied. Phase 0's threading and stages 12–13 stay as they are.

The spec's Phase 2 row leaves out three things that its own done criterion needs:

- **Presence fades.** In §7.8 one playback is 0.5 s into a 2 s fade, and "release" needs a release time. Phase 2 fades a source's *weight* linearly: fade-in on activation, fade-out on release. Value-to-value fades, curves and per-family timing stay in Phase 4.
- **sACN output.** Phase 0 deferred network output and noted that it needs a slot before this demo, because the demo needs real light. If Phase 1 delivers it, drop step 9.
- **A narrow MIDI → command path.** Bindings belong to Phase 6, but "busk with MIDI faders" needs CC and note input mapped to playback faders and buttons. Phase 2 implements jump pickup on the first page, without feedback.

**Done when:**

1. `test_golden_7_8.py` reproduces §7.8 at two levels:
   - the resolver, fed the table's contributions directly;
   - the engine, driven by commands on a fake clock.

   It checks the logical values and the DMX bytes of the §7.8 conversion table. It also checks the two follow-ups described under that table: the release continuation and the exclusivity variant.
2. `busk run examples/phase2-busk.json` passes the manual checklist in §8, using a MIDI controller and an sACN receiver.
3. All acceptance tests pass, and the tick benchmark results are recorded.

---

## 1. Scope

| In Phase 2 | Deferred (to) |
|---|---|
| Cue compiler: group expansion; literal, perTarget, scoped preset and spread values → lanes (§6.3 steps 1–4) | Tracked states, cue `releases`, `block` (4) |
| Single-cue playbacks: activate, release, toggle, GO (activate or re-assert), flash, `temp` fader | Multi-cue GO/BACK/GOTO, follow/wait, chase mode (4) |
| Presence envelopes: `delayIn`/`fadeIn` on activation, `releaseTime` on release, linear only | Curves, value fades, per-family and per-entry timing (4) |
| `master` fader with `followFader` / `threshold` / `ignoreFader`, `autoStart`, `autoRelease`; `none` and `temp` faders | `crossfade` (4), `rate` (4/5), `size` (5) |
| Exclusivity | `swop` (unassigned, §9), `select` (3) |
| Resolver: LTP layer stack with discrete snapping (§7.3); HTP across bands (§7.4) | Relative pass (5), programmer band and blind (3) |
| Grand master, blackout | Group masters and fade-time master (unassigned, §9); speed (4) and size (5) masters; park, limits, strobe cap (7); highlight (3) |
| Command bus: queue, envelopes, performance commands, new `TOGGLE_PLAYBACK` | Programmer and show-edit commands, undo, event log (3) |
| Minimal UI snapshot + CLI status line | API / WebSocket (6) |
| sACN data packets (multicast/unicast); output scheduler thread | Art-Net, DMX USB, discovery, `Stream_Terminated`, sync, send-on-change (6) |
| MIDI input (CC, note, pitch bend); bindings to playback fader/button, grand master, blackout, embedded command | Soft takeover, pages, tap, feedback, OSC/HID/web (6) |
| A limitation report at startup listing every show feature Phase 2 ignores | — |

---

## 2. Decisions and assumptions

1. **Contributions are batched per source, not stored per slot.** §5.18 has per-slot `ContributionState` dicts, and §7.1 builds a `Contribution` object per slot per tick. Done literally, that is tens of thousands of Python objects per tick. Instead, as §19 suggests ("contributions stored per playback in arrays indexed by slot"), each source exposes:
   - numpy arrays of lane indices and values;
   - five scalars: `priority`, `seq`, `htpWeight`, `intensityScale`, `ltpWeight`.

   All of a source's contributions share `(priority, seq)`. Compositing whole sources in `(priority, seq)` order is therefore exactly §7.3/§7.4 applied per slot. A slow, literal per-slot transcription of §7.7 lives in `tests/` as an oracle.
2. **A playback is up to two sources.**
   - *main* holds the latched state (activate / release).
   - *flash* is present while a flash button is held or a `temp` fader is above 0. It has its own `seq` and its own band, `priority + flash.priorityBoost`.

   Releasing a flash removes only the flash source, so the stack below is exactly as before. This keeps "the underlying state was never touched" (§8.1) true even for flashes that bring LTP values.
3. **Weights.** Each playback has two envelopes:
   - `env` is the presence envelope. It goes 0→1 on activation over `delayIn` + `fadeIn`, and from its current value to 0 on release.
   - `ltpEnv` is the LTP presence and equals `env` with one exception. In `threshold` mode, when the activation came from the fader below `ltpThreshold`, it stays at 0 until the fader crosses the threshold. It then fades in with the cue's `delayIn`/`fadeIn` and stays latched until release.

   Per tick, the sources get these values:

   | | `htpWeight` | `intensityScale` | `ltpWeight` |
   |---|---|---|---|
   | main | `env` | `faderLevel` if `fader == "master"`, else 1 | `ltpEnv`, × `faderLevel` if `followFader` |
   | flash | 1 | max(`flash.level` while the button is held, `faderLevel` if `fader == "temp"`) | 1 if `includeLtp`, else 0 |
4. **Release** uses the command's `time` if given, otherwise `playback.releaseTime`, for intensity and LTP alike. The weight goes from its current value to 0 in exactly that time, as in §7.8: "0.25 → 0" over 1 s. Cue `fadeOut`/`delayOut` are stored but not used until Phase 4 transitions. A release with time 0 removes the source in the same tick.
5. **Only latching activations apply exclusivity**: trigger, toggle, GO and `autoStart`. Flash and `temp` don't. Otherwise a momentary flash would permanently release the colour it covered.
6. **Initial levels.**
   - Playback faders start at 0; the grand master starts at 1.0; blackout is off. (§5.13 mentions an `initialLevel`, but the schema has no such field.)
   - A `master`-fader playback triggered by a button while its fader is at 0 brings its LTP values but no intensity. That is standard console behaviour. Playbacks meant to be button-only should use `fader: "none"`.
   - `autoStart`/`autoRelease` apply only to `master` faders in Phase 2.
7. **Snap lanes.** Lanes of attributes with `fade: "snap"` (all discrete attributes, plus `positionSpeed`) take the source's value once the weight passes `snapAt`:

   | `snapAt` | Condition |
   |---|---|
   | start | > 0 |
   | middle | ≥ 0.5 |
   | end | ≥ 1 |

   Colour extras (`w`/`a`/`uv`) snap at *middle*. A `NaN` ("derive") lane can't be interpolated against an explicit value.
8. **Values are clamped at compile time, not every tick** (a deviation from §7.7's `clampToAttributeRange`).
   - Compile time clamps normalised attributes, colour components, `flash.level` and `ltpThreshold` to 0..1.
   - Every resolve step is a convex combination: the LTP lerp, and HTP `v(1−P)+M` with `M ≤ P`. In-range inputs therefore stay in range.
   - Degree attributes are clamped by conversion (Phase 1).
9. **Cue compile rules that §6.3 leaves open:**
   - A later entry for the same slot in one cue wins, so "all heads blue, MH1 red" works.
   - Spread uses each member's index in the full expanded list: `u = k/(n−1)`, and `u = 0` when `n = 1`. Members without the attribute keep their position. `f` is `u` for linear, `1−|2u−1|` for center and `|2u−1|` for edges. The value is `lerp(from, to, f)` per lane.
   - A discrete value whose slot id isn't in the target's option list is dropped and reported. Example: a global "breakup" gobo on a fixture without that gobo.
   - A `perTarget` source with no key for a target contributes nothing to that target.
   - New validation rule: a duplicate `(scope, attribute)` within one preset is an error.
10. **Bindings stay stateless and resolve off the engine thread**, following §4.1 (bindings → Commands).
    - Toggle needs engine state, so Phase 2 adds `TOGGLE_PLAYBACK {playbackId}` to the command union. The addition is backward compatible: old shows stay valid, so `schemaVersion` stays 1.
    - The blackout binding is momentary: press sets it on, release sets it off. `BlackoutAction` carries no state, and `BLACKOUT` takes `on: bool`.
11. **Page:** page-relative bindings always use the lowest-numbered page. Page switching is Phase 6.
12. **Commands are validated at submit time** on the caller's thread.
    - Checks: the playback or master id exists, the command type is supported in Phase 2, and levels are clamped to 0..1.
    - Ids can't change before Phase 3 show edits, so the engine applies commands as trusted.
    - The engine still wraps each command's application in `try/except`. An exception is counted and the tick continues (§1.1: live-safe).
13. **sACN only.** Appendix A and the Phase 0 demo already use it.
    - Every enabled route sends full 512-slot packets continuously at 44 Hz. That is the simplest approach, and it always stays inside the receivers' 2.5 s timeout.
    - §14.1 send-on-change with keep-alive is a Phase 6 optimisation.
    - Termination, discovery and sync are Phase 6, per the roadmap.
14. **`OutputDriver` is synchronous** (`open` / `send` / `close` / `status`) and runs on plain threads. This deviates from §14.5's `async` signatures. The rest of the protocol keeps its shape.
15. **The console printer stays a debug sink** (`busk run --console`), not a route protocol. This resolves the open question in Phase 0 §8.
16. **MIDI backend:** `mido` with `python-rtmidi`, behind an `InputEvent` boundary so the backend can be swapped (see the spike in step 1). MIDI channels in show data are 1-based, as in Appendix A.
17. **New dependencies:** `mido`, `python-rtmidi`; dev dependency `hypothesis`. mido has no type stubs, so mypy is told to ignore missing imports for `mido` only, and mido is imported only in `io/midi.py`.

---

## 3. Inputs from Phase 1 (assumed contract)

Phase 2 needs the following from Phase 1. The names are suggestions; step 0 maps them to whatever Phase 1 actually ships.

| Need | Assumed shape |
|---|---|
| Slot table | `CompiledShow.slots: tuple[Slot, ...]` with `index`, `target`, `attribute: AttributeDefinition`, `laneOffset`, `laneCount`. Lookup `slot_of(targetKey, attributeId) -> SlotIndex \| None` |
| Logical frame | `totalLanes`; `defaultFrame: NDArray[float64]`, with zoom's "profile midpoint" resolved |
| Value encoding | `encode_value(slot, AttributeValue) -> NDArray[float64] \| None`. Colour → r, g, b + extras (`NaN` = derive). Discrete → option index. `None` when this slot doesn't have the option |
| Virtual intensity | A mode with `intensityStrategy: "virtual"` exposes an intensity slot on every element that has colour; otherwise Appendix A's par can't be dimmed. §5.5 derives slots from channels, so this needs an explicit rule |
| Shutter guard | Built into the default frame: an uncontrolled `shutter` slot holds the index of `open`. Phase 2 then needs no "touched slots" mask |
| Conversion | `convert_frame(frame, compiled, out)` writes slot-driven channels over the base image |
| Colour mixing | RGBW uses `w = min(r, g, b)`, the method the §7.8 table assumes. If Phase 1 picked calibrated mixing instead, recompute the golden colour bytes and note the deviation |
| Engine | `Engine.tick(now)` copies the base image, converts a logical frame and publishes a `Frame`. Phase 2 inserts stages 1–11 before conversion |

---

## 4. Project layout (additions)

```
src/busk/
  commands/types.py            # + TogglePlaybackCmd
  commands/bus.py              # CommandBus: submit (validate → envelope → queue), drain
  compiler/cues.py             # CompiledCue, SnapGroup, compile_cue(): expansion, value sources, lanes
  compiler/playbacks.py        # CompiledPlayback; playback, first-page and grand-master tables
  compiler/limitations.py      # Limitation, collect_limitations(show)
  engine/fades.py              # Envelope
  engine/playback_runtime.py   # PlaybackRuntime: state machine, owns its two Sources
  engine/contributions.py      # Source, gather()
  engine/resolver.py           # resolve(): LTP stack + snap, HTP bands
  engine/masters.py            # grand master, blackout
  engine/snapshot.py           # EngineSnapshot, PlaybackStatus
  engine/loop.py               # tick stages 1–13 wired together
  output/driver.py             # OutputDriver protocol, DriverStatus
  output/sacn.py               # SacnPacket (preallocated), SacnSender
  output/scheduler.py          # OutputScheduler thread: routes + optional console sink
  output/console.py            # Phase 0 printer, now a sink of the scheduler
  io/events.py                 # InputEvent
  io/bindings.py               # BindingResolver: InputEvent → commands
  io/midi.py                   # MidiInput: mido messages → InputEvent
  cli.py                       # run: limitations, routes, MIDI, status line
examples/phase2-busk.json
tests/
  harness.py  reference_resolver.py
  fixtures/golden_7_8.json
  test_bus.py test_compile_cues.py test_fades.py test_resolver.py test_resolver_properties.py
  test_playback_runtime.py test_masters.py test_golden_7_8.py test_engine_busking.py
  test_sacn.py test_output_scheduler.py test_bindings.py test_midi.py test_cli.py
  bench/rig.py bench/test_tick_budget.py      # marked `bench`, not run by default
```

---

## 5. Component design

### 5.1 Commands and bus (`commands/`)

- `TogglePlaybackCmd = TypedDict(..., {"type": Literal["TOGGLE_PLAYBACK"], "playbackId": PlaybackId})` joins the `Command` union as a Performance-class command.
- `CommandBus(compiled, clock)`:
  - `submit(command, origin)` validates the command per decision 12 and raises `CommandRejected(reason)` on failure. It wraps the command in a `CommandEnvelope` (sequential `id`, `issuedAt = clock.now()`, `origin`) and puts it on a `queue.SimpleQueue`.
  - `drain()` yields envelopes until the queue is empty. The engine applies them at the tick's `now`, in arrival order.
- Commands supported in Phase 2: `TRIGGER_PLAYBACK`, `RELEASE_PLAYBACK`, `TOGGLE_PLAYBACK`, `FLASH`, `GO`, `SET_FADER`, `SET_MASTER` (grand masters only), `BLACKOUT`. Any other command is rejected with "not supported until Phase N".

### 5.2 Cue compiler (`compiler/cues.py`, `compiler/playbacks.py`)

```python
@dataclass(frozen=True, kw_only=True)
class SnapGroup:
    threshold: float                   # 5e-324 (≡ w > 0), 0.5 or 1.0 — one comparison `w >= threshold`
    lanes: NDArray[np.intp]
    values: NDArray[np.float64]

@dataclass(frozen=True, kw_only=True)
class CompiledCue:
    id: CueId
    number: str
    htpPos: NDArray[np.intp]           # positions into CompiledShow.intensityLanes
    htpValues: NDArray[np.float64]
    ltpLanes: NDArray[np.intp]         # frame lane indices of continuous LTP lanes
    ltpValues: NDArray[np.float64]
    snap: tuple[SnapGroup, ...]        # ≤ 3 groups
    fadeIn: float
    delayIn: float
    fadeOut: float                     # stored for Phase 4
    delayOut: float
    targets: tuple[TargetRef, ...]     # deduplicated, entry order (Phase 3 `select`)
```

For each cue:

1. Expand each entry's `TargetSpec`.
2. Resolve the `ValueSource` per target.
3. Look up the slot; drop the target if it has none.
4. Encode the value, then clamp it (decision 8).
5. Store the result in a dict keyed by slot, so the last write wins.
6. Partition the lanes into HTP, continuous LTP and snap groups.
7. Build the arrays, sorted by lane.

The preset index is built once per show: `attribute → (byTarget, byProfile, global)`. Lookup goes target → profile → global (§5.8).

Every cue is compiled, so errors surface uniformly and Phase 4 gets the compiled cues, but only the first cue is played. An empty cue list compiles to an empty cue.

`CompiledShow` gains:

- `intensityLanes`, the sorted lane indices of all intensity slots, with `defaultI`;
- `playbacks: dict[PlaybackId, CompiledPlayback]`, holding the `Playback` fields the runtime uses plus `cue` and `cueCount`;
- `firstPage: tuple[PlaybackId | None, ...]`;
- `grandMasters`.

### 5.3 Limitation report (`compiler/limitations.py`)

`Limitation(path, message)`. `busk run` prints these under `Ignored in Phase 2:`, one line each, so an operator never has to wonder why a feature does nothing. They are collected for:

- multi-cue lists, chase mode, cue `effects` / `releases` / `block`, non-linear curves, `perFamily` and per-entry timing;
- `crossfade` / `rate` / `size` faders; `back` / `goto` / `swop` / `select` buttons;
- non-grand masters and bindings to them, `park` entries, fixture `limits`, `holdLastFrameOnEngineStall: false`;
- Art-Net and DMX-USB routes;
- non-MIDI surfaces, soft pickup, binding feedback, page/tap actions, pages other than the first.

### 5.4 Envelope (`engine/fades.py`)

```python
@dataclass(slots=True)
class Envelope:                         # the presence half of §5.18 FadeState; Phase 4 adds `curve`
    start: float = 0.0
    delay: float = 0.0
    duration: float = 0.0
    fromValue: float = 0.0
    toValue: float = 0.0
    def value(self, now: float) -> float: ...          # linear; duration 0 → step at start + delay
    def retarget(self, now: float, to: float, duration: float, delay: float = 0.0) -> None: ...
        # fromValue = value(now), start = now — fades always start from the actual current weight
    def settled(self, now: float) -> bool: ...
```

### 5.5 Playback runtime (`engine/playback_runtime.py`)

The fields are `state`, `faderLevel`, `activationSeq`, `env`, `ltpEnv`, `flashButton`, `flashSeq`, plus two preallocated `Source` objects that are mutated in place. These map onto §5.18's `PlaybackRuntime` as follows:

- `currentCue` is always 0 while active;
- `transition` is always `None` (Phase 4);
- `contributions` becomes the cue arrays plus the envelopes.

Main-source state machine:

| Event | idle | active | releasing |
|---|---|---|---|
| `TRIGGER_PLAYBACK` | activate | re-assert | activate |
| `TOGGLE_PLAYBACK` | activate | release | activate |
| `GO` | activate | `releaseAtEnd` ? release : re-assert | activate |
| `RELEASE_PLAYBACK` | — | release | — |
| fader leaves 0 (`autoStart`) | activate *by fader* | — | activate *by fader* |
| fader reaches 0 (`autoRelease`) | — | release | — |
| fader ≥ `ltpThreshold` while LTP is unlatched | — | latch LTP | — |
| `env` and `ltpEnv` both settled at 0 | | | → idle |

The actions in the table work like this:

- **activate(by)**
  1. Take a fresh `seq` and set the state to active.
  2. `env.retarget(now, 1, fadeIn, delayIn)`.
  3. Latch LTP with the same retarget on `ltpEnv`, unless `by == fader`, the mode is `threshold` and `faderLevel < ltpThreshold`.
  4. Release every other active playback with the same exclusivity key, each with its own release time.
- **re-assert** is activate-by-button on an already active playback. It takes a fresh `seq`, so its LTP values move back on top. Its weights are already at 1, so nothing else visibly changes.
- **release(t)** retargets `env` and `ltpEnv` to 0 over `t` and sets the state to releasing. When `t == 0` the playback goes straight to idle.
- **Flash.** `FLASH` down/up sets `flashButton`. When the flash source goes from absent to present, it takes a fresh `seq`.

Every state change sets the engine's snapshot `dirty` flag.

### 5.6 Sources and resolver (`engine/contributions.py`, `engine/resolver.py`)

```python
@dataclass(slots=True)
class Source:                          # one source's contributions this tick (§7.1, batched)
    sourceId: str
    priority: int
    seq: int
    htpPos: NDArray[np.intp]           # views of a CompiledCue; Phase 4 swaps in interpolated arrays
    htpValues: NDArray[np.float64]
    ltpLanes: NDArray[np.intp]
    ltpValues: NDArray[np.float64]
    snap: tuple[SnapGroup, ...]
    htpWeight: float
    intensityScale: float
    ltpWeight: float
```

`gather()` refills a reusable list with the sources that have a non-zero weight and sorts it by `(priority, seq)`. Then:

```python
np.copyto(frame, compiled.defaultFrame)
np.copyto(vI, compiled.defaultI)                         # intensity default 0
for band in bands(sources):                              # ascending priority
    P.fill(0.0); M.fill(0.0)                             # dense over all intensity lanes
    for s in band:                                       # ascending seq
        if s.ltpWeight > 0.0:
            cur = frame[s.ltpLanes]
            frame[s.ltpLanes] = cur + (s.ltpValues - cur) * s.ltpWeight        # §7.3 lerp
            for g in s.snap:
                if s.ltpWeight >= g.threshold:
                    frame[g.lanes] = g.values                                   # §7.3 snap
        if s.htpWeight > 0.0:
            P[s.htpPos] = np.maximum(P[s.htpPos], s.htpWeight)
            M[s.htpPos] = np.maximum(M[s.htpPos], s.htpValues * (s.intensityScale * s.htpWeight))
    vI *= 1.0 - P; vI += M                               # §7.4
frame[compiled.intensityLanes] = vI
```

`v·(1−P) + M` is §7.4's `lerp(v, M/P, P)` with the division cancelled out. When `P = 0`, `M = 0` too, so lanes the band doesn't touch keep their value. Lanes are unique within one source, so fancy-index updates never see duplicate indices. Weights are scalars in Phase 2. The LTP and HTP lines already broadcast per-lane weight arrays, which Phase 4 will need; snapping will then need masks. Use `out=` scratch buffers only where the benchmark shows a gain.

### 5.7 Masters and blackout (`engine/masters.py`)

These are stages 9–10, applied to the working frame, which is rebuilt from defaults every tick:

- `frame[I] *= gm`, where `gm` is the product of all grand-master levels (normally there is one).
- If blackout is on, `frame[I] = 0`.

Runtime state is never touched. Releasing blackout or raising the GM therefore returns exactly to the live look.

### 5.8 Engine tick (`engine/loop.py`)

| § 4.2 stage | Phase 2 |
|---|---|
| 1 Drain commands | `bus.drain()` → apply, with `try/except` per command; count `commandsApplied` and `commandErrors` |
| 2 Clocks | `now` only; Phase 2 needs no `dt` |
| 3–4 Playbacks, fades | `update(now)` on every non-idle runtime: idle transitions, then fill its sources |
| 5 Effects | — (Phase 5) |
| 6–7 Gather, resolve | §5.6 |
| 8 Relative | — (Phase 5) |
| 9–10 Masters, blackout | §5.7 |
| 11 Safety | — (Phase 7) |
| 12–13 Convert, publish | Phase 1 / Phase 0. A new `EngineSnapshot` is published only when `dirty` |

`EngineRuntime` holds `now`, `seqCounter`, `playbacks` (dict by id), `live` (non-idle ids), master levels and `blackout`.

`EngineSnapshot(seq, grandMaster, blackout, playbacks: tuple[PlaybackStatus, ...])` lists each playback's number, name, state, fader level and flash state. It is immutable and published by reference assignment, like `Frame`.

### 5.9 sACN (`output/sacn.py`)

E1.31 data packet, always 638 bytes (512 slots):

| Offset | Size | Field | Value |
|---|---|---|---|
| 0 | 2 | Preamble size | `0x0010` |
| 2 | 2 | Post-amble size | `0x0000` |
| 4 | 12 | ACN packet identifier | `ASC-E1.17\0\0\0` |
| 16 | 2 | Root flags & length | `0x7000 \| 622` |
| 18 | 4 | Root vector | `0x00000004` |
| 22 | 16 | CID | `output.sacnCid` (UUID bytes) |
| 38 | 2 | Framing flags & length | `0x7000 \| 600` |
| 40 | 4 | Framing vector | `0x00000002` |
| 44 | 64 | Source name | `sacnSourceName`, UTF-8, NUL-padded |
| 108 | 1 | Priority | `route.priority` |
| 109 | 2 | Sync address | 0 |
| 111 | 1 | Sequence number | per route, mod 256 |
| 112 | 1 | Options | 0 |
| 113 | 2 | Universe | `route.universe` |
| 115 | 2 | DMP flags & length | `0x7000 \| 523` |
| 117 | 1 | DMP vector | `0x02` |
| 118 | 1 | Address & data type | `0xA1` |
| 119 | 2 | First property address | `0x0000` |
| 121 | 2 | Address increment | `0x0001` |
| 123 | 2 | Property value count | 513 |
| 125 | 1 | START code | `0x00` |
| 126 | 512 | DMX data | universe bytes |

- Each route keeps a preallocated `bytearray` with the static header. A send writes only the sequence byte and the data, then calls `sendto`.
- **Multicast** goes to `239.255.{u >> 8}.{u & 0xFF}`, port 5568.
  - The interface is selected with `IP_MULTICAST_IF`, using a Linux `ip_mreqn` built from `socket.if_nametoindex(iface)`. An IPv4 literal is also accepted as `iface`.
  - `IP_MULTICAST_LOOP` is on, so sACN viewers on the same machine see the traffic.
- **Unicast** goes to `host:5568`. The constructor takes `port` so tests can use an ephemeral port.
- An `OSError` on open or send sets `status.ok = False` with a detail message and never raises into the scheduler. The send is retried on the next cycle.

### 5.10 Output scheduler (`output/scheduler.py`)

- One thread runs at 44 Hz, with the same drop-don't-spiral timing as the engine loop. Each cycle:
  - it reads `engine.latest`;
  - every enabled route sends its universe's row;
  - the optional console sink is serviced (Phase 0's print-on-change, unchanged line format).
- If the engine stalls, the last frame keeps going out (`holdLastFrameOnEngineStall: true`).
- The scheduler exposes per-route `DriverStatus` for the CLI.

### 5.11 MIDI and bindings (`io/`)

`InputEvent(surfaceId, address: InputAddress, value: float)` carries a value in 0..1.

`MidiInput` opens the first input port whose name contains `surface.match.deviceName`, compared case-insensitively. ALSA names look like `nanoKONTROL2:nanoKONTROL2 _ CTRL 20:0`. Its port callback translates messages:

| mido message | InputEvent |
|---|---|
| `control_change` ch *c*, control *n*, value *v* | `midiCC(c+1, n)`, *v*/127 |
| `note_on` velocity > 0 | `midiNote(c+1, n)`, 1.0 (any velocity is a press) |
| `note_off`, or `note_on` velocity 0 | `midiNote(c+1, n)`, 0.0 |
| `pitchwheel` | `midiPitchBend(c+1)`, (pitch + 8192)/16383 |

`BindingResolver` indexes bindings by `(surfaceId, address)` and turns events into `bus.submit(...)` calls:

| Action | Commands |
|---|---|
| `playbackFader {slot}` / `playbackFaderAbs` | `SET_FADER(value)`, using `firstPage[slot]` for the page-relative form |
| `playbackButton {slot, button}` | A press is the value rising to ≥ 0.5; a release is the value falling below 0.5. The binding keeps its own edge state, so a repeated CC 127 is still one press. Then by `playback.buttons[button]`: `go` → `GO` on press; `toggle` → `TOGGLE_PLAYBACK`; `release` → `RELEASE_PLAYBACK`; `flash` → `FLASH` down/up |
| `master` (grand) | `SET_MASTER(value)` |
| `blackout` | `BLACKOUT(on)` on press, `BLACKOUT(off)` on release |
| `command` | The embedded command is submitted on press, if supported |
| anything else | Ignored; listed as a limitation at startup |

Edge state is per binding. Each binding belongs to one surface, and so to one callback thread, so no locking is needed. A `CommandRejected` raised inside a callback is printed once per binding and never escapes into rtmidi.

### 5.12 CLI (`busk run SHOW [--duration S] [--console]`)

1. Load and compile the show, then print warnings and the limitation block.
2. Open the sACN routes and print one line each, e.g. `sACN r1: U1 → universe 1, multicast 239.255.0.1 via eth0`. Open the MIDI surfaces and print the matched port, or `not found; available: …`. Startup continues without the missing device.
3. Start the engine, the output scheduler and the MIDI callbacks.
4. The main thread polls every 100 ms and prints:
   - a status line when the snapshot changes, e.g. `GM 80% | BO off | 1 Warm on 0.75 · 3 Blue rel · 8 Panic flash` (only playbacks that are non-idle or have their fader up);
   - any change in a route's status.
5. On Ctrl+C or `--duration`, shut down in this order:
   1. close MIDI;
   2. stop the engine;
   3. stop output, so the last frame keeps going out until the end.

   Then print the Phase 0 stats line, plus `commands N, command errors M`.

### 5.13 Demo show (`examples/phase2-busk.json`)

- **Rig:** 2 × Appendix A "Generic Spot 16ch" and 4 × "RGB Par 3ch" (virtual intensity), on universe 1.
- **Groups:** Heads, Pars, All.
- **Presets:** colour Blue, Red, Green, Amber (global scope); position Audience and Centre (per-target scope).
- **Route:** one sACN multicast route. Set `iface` to the local machine's interface.
- **Controller:** the bindings target a nanoKONTROL2 in factory CC mode: faders on CC 0–7; S, M and R buttons on CC 32–39, 48–55 and 64–71; knob 8 (CC 23) as GM; ■ (CC 42) as blackout. Check the numbers with `aseqdump`.

| Slot | Playback | Content | Fader / LTP mode | Buttons S, M, R | Exclusivity |
|---|---|---|---|---|---|
| 1 | Warm | All: intensity 0.8, warm white | master / threshold | toggle, flash, release | base |
| 2 | Cool | All: intensity 0.8, cool white | master / threshold | toggle, flash, release | base |
| 3–5 | Blue / Red / Green | All: colour preset, fade 1 s | master / threshold | toggle, flash, release | color |
| 6–7 | Audience / Centre | Heads: position preset, fade 2 s | master / followFader | toggle, flash, release | position |
| 8 | Panic | All: intensity 1, white, priority 200 | none | flash (`includeLtp`), toggle, release | — |

Base looks carry the intensity and bumps carry only colour or position. This is the layering the spec is designed around. Every lit fixture, pars included, needs intensity from a base look.

---

## 6. Implementation steps

Each step is TDD: write the listed tests first, then make them pass.

0. **Phase 1 contract check (§3).** Read the Phase 1 code and map every assumed name. If Phase 1 already ships network output, drop step 9. → *verify:* a short mapping note is added to the top of this file.
1. **Spikes** (throwaway code in the scratchpad):
   - (a) `uv add mido python-rtmidi` on 3.14, from a wheel or a source build (which needs the alsa-lib headers). Then open a virtual output port and receive from it in-process.
   - (b) Send one sACN multicast packet out of a named interface with `ip_mreqn`, and watch it with `tcpdump -i <iface> udp port 5568`.

   *Fallbacks for (a):* the `alsa-midi` package, or a raw reader for `/dev/snd/midiC*D*` behind the same `InputEvent` boundary. → *verify:* both spikes work, or a fallback is chosen before steps 9–10.
2. **Command types + bus.** → *verify:* `test_bus.py` checks that:
   - `TOGGLE_PLAYBACK` validates, both on its own and embedded in a binding's `command` action;
   - unsupported types and unknown ids are rejected with readable reasons;
   - levels are clamped;
   - the queue is FIFO and envelope fields are filled in.
3. **Cue compiler, compiled playbacks, limitation report, preset-duplicate validation rule.** → *verify:* `test_compile_cues.py` covers:
   - golden arrays for Appendix A:
     - Verse gives MH intensity 0.4, colour `[1, .8, .6, NaN]`, and pan −20 / +20;
     - Blue gives MH `[0, 0, 1, NaN]` and par `[0, 0, 1]`;
   - scope precedence target > profile > global;
   - spread for linear, center and edges, including `n = 1` and colour spreads;
   - dropped targets without the attribute; dropped and reported missing discrete options; last-wins entries; clamping;
   - lane partition: gobo and `positionSpeed` snap at *start*, colour extras at *middle*;
   - Appendix A's limitation list, exactly 8 lines:
     - Song has 2 cues;
     - Verse uses `easeInOut`;
     - Pulse has an effect;
     - pb-song has a `back` button;
     - pb-pulse has a `size` fader;
     - `m-speed`;
     - soft pickup on `s-midi`;
     - MH 1 has tilt limits.
4. **Envelope.** → *verify:* `test_fades.py` covers linear values, delay, a zero-duration step, retargeting from mid-fade and `settled`.
5. **Resolver + reference oracle.**
   - → *verify:* `test_resolver.py` covers:
     - each §7.3 bullet: the newest source wins, quarter-way at weight 0.25, release glides back, a higher band beats a newer lower one;
     - the three snap thresholds;
     - each §7.4 bullet: the base band is classic HTP; a 2 s override of 100 % over 80 % passes 90 % at 1 s; a source still fading in can't pull below one that is fully up;
     - the **resolver-level §7.8 golden** (0.60 / `{0.75, 0.75, 1.0}` / 22.5°).
   - `test_resolver_properties.py` (hypothesis) checks that:
     - the fast resolver equals the oracle within 1e-12 on random sources;
     - HTP within a band ignores order and is never below any single `value·scale·weight`;
     - each LTP lane stays inside the hull of its default and its inputs;
     - a zero-weight source is a no-op.
6. **Playback runtime.** → *verify:* `test_playback_runtime.py` is table-driven:
   - one case per row of the §5.5 state table;
   - the decision 3 weights over time for each `ltpFaderMode`;
   - the threshold latch when activated by the fader vs by a button;
   - `autoStart` / `autoRelease` edges;
   - flash on an idle and on an active playback, with `includeLtp` and `priorityBoost`;
   - `temp`;
   - exclusivity releases others with their own time, and never on a flash;
   - a release from mid-fade lasts exactly `releaseTime`; a release with time 0.
7. **Masters and blackout.** → *verify:* `test_masters.py` checks that:
   - the GM scales only intensity lanes;
   - blackout zeros them, including flashes and override bands;
   - toggling the GM and blackout away and back restores an identical frame *and* identical runtime state.
8. **Engine integration, harness, golden.** Build `tests/fixtures/golden_7_8.json`:
   - four heads with the Appendix A spot profile at addresses 1 / 17 / 33 / 49;
   - P1 Verse, P2 Chorus, P3 Blue (2 s linear, `releaseTime` 1), P4 Red, P5 Audience (MH1 pan 45°, `followFader`, fade 0);
   - P3 and P4 share `exclusivity: "color"`.

   The harness script:
   1. t = 0: GM 0.8; P1 fader 1.0; P2 fader 0.6.
   2. t = 10.0: toggle P3.
   3. t = 10.1: P5 fader 0.5.
   4. Assert at 10.5.

   → *verify:*
   - `test_golden_7_8.py` checks MH1 at 10.5:
     - logical intensity 0.48, colour `{0.75, 0.75, 1.0}`, pan 22.5°;
     - DMX: dimmer **122/225**, pan **138/170**, R G B W **0/0/64/191**;
     - MH2–4 the same, except pan 0° → **128/0**;
     - every other channel equals the no-playback frame.
   - The release continuation: release P3 at 10.5. At 11.0, B = **32** and W = **223** (colour `{.875, .875, 1}`). At 11.5 the colour is white and P3 is idle.
   - The exclusivity variant: Red is up, Blue is triggered, Blue is released → white, not red.
   - `test_engine_busking.py` checks that:
     - a release with time 0 gives the frame computed without the playback;
     - two runs give identical frame sequences;
     - the same script ticked at 100 Hz, 37 Hz and random intervals gives equal frames at the shared times (§2.5);
     - snapshots are published only on change;
     - a command that raises is counted and ticking continues;
     - 10 000 steady ticks show no `tracemalloc` growth.
9. **sACN + output scheduler.** → *verify:*
   - `test_sacn.py`:
     - an independent parser checks every field of the §5.9 table at its offset;
     - multicast groups for universes 1, 256 and 63999;
     - the sequence wraps 255 → 0;
     - source-name padding and CID;
     - a real receive over localhost unicast on an ephemeral port.
   - `test_output_scheduler.py`, using a `FakeClock` and calling `service(now)` directly:
     - every enabled route sends each cycle and disabled routes are skipped;
     - a raising driver marks its own status and doesn't stop the others;
     - the last frame is held when the engine stalls;
     - the console sink's output is identical to Phase 0.
10. **Bindings + MIDI.** → *verify:*
    - `test_bindings.py`:
      - every action and button mapping;
      - CC button edges (127/0, repeated 127 gives one press) and note velocity as a press;
      - the first page is used; out-of-range slots and buttons are ignored;
      - unsupported bindings are listed; channels are 1-based.
    - `test_midi.py`:
      - message → `InputEvent` conversion;
      - an end-to-end check through a virtual port: fader CC → `SET_FADER` on the bus. It is marked `midi` and skipped when there is no `/dev/snd/seq`.
11. **CLI + demo show.** → *verify:* `test_cli.py` checks that:
    - `busk validate examples/phase2-busk.json` reports 0 issues;
    - `busk run tests/fixtures/appendix_a.json --duration 0.3` prints the 8-line limitation block and a stats line with 0 command errors;
    - `--console` prints frames;
    - a missing MIDI device prints the available ports and the run continues.
12. **Benchmark.** `tests/bench/rig.py` generates two rigs:
    - small: like Appendix A, 1 universe;
    - reference (§19): 64 universes, ~400 fixtures including pixel bars, ~20 000 slots, 60 active playbacks across 3 bands.

    Record the mean and p99 tick time. Gates:
    - small rig: p99 < 1 ms;
    - reference rig: p99 < 10 ms, i.e. no overruns at 100 Hz.

    §19's < 4 ms is a target. If it is missed, record the result and open an optimisation item (`out=` buffers, merged index ops); a miss does not block Phase 2.
13. **Full verification pass** (§8), including the manual MIDI checklist.

---

## 7. Acceptance tests (summary)

| Test file | Proves |
|---|---|
| `test_bus.py` | Command validation, `TOGGLE_PLAYBACK`, FIFO, envelopes |
| `test_compile_cues.py` | Group expansion, scoped presets, spreads, drop rules, lane partitions, limitation list |
| `test_fades.py` | Envelope contract |
| `test_resolver.py` | §7.3 / §7.4 behaviours, snapping, resolver-level §7.8 golden |
| `test_resolver_properties.py` | Fast resolver = literal §7.7 oracle; §20 HTP and LTP properties |
| `test_playback_runtime.py` | State machine, fader modes, threshold latch, flash, `temp`, exclusivity, release timing |
| `test_masters.py` | GM / blackout correct and non-destructive |
| `test_golden_7_8.py` | §7.8 end to end: commands → logical → DMX bytes, release continuation, exclusivity |
| `test_engine_busking.py` | Determinism, tick-schedule independence, release-0 equivalence, live-safety, no memory growth |
| `test_sacn.py`, `test_output_scheduler.py` | E1.31 packet layout and transmission, route isolation, hold-last-frame |
| `test_bindings.py`, `test_midi.py` | MIDI → InputEvent → commands |
| `test_cli.py` | `run` wiring, limitation report, missing-device behaviour |

---

## 8. Verification

```bash
uv run pytest                                          # all green (midi tests skip without ALSA seq)
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run pytest -m bench -s                              # record numbers in this file
uv run busk validate examples/phase2-busk.json         # 0 errors, 0 warnings
uv run busk run tests/fixtures/appendix_a.json --duration 2 --console
                                                       # 8 "Ignored in Phase 2" lines, sACN route line, stats
```

> **Results** (implementation, 2026-10-11; dev machine, Python 3.14.7, numpy 2.5.4). The benchmark runs under the existing `perf` marker (`uv run pytest -m perf -s`), not `bench`.
>
> - `uv run pytest`: 884 passed, 1 opt-in skip (real multicast). The `midi` test runs through a virtual ALSA port. The suite also passes on Python 3.12 and 3.13. ruff, ruff format and mypy `--strict` are clean.
> - Busking tick, small rig (Appendix A, every playback up): **mean 0.053 ms, p99 0.056 ms** (gate: p99 < 1 ms).
> - Busking tick, reference rig (64 universes, 20 608 slots, 60 playbacks in 3 bands, all mid-fade, 177 582 contributed lanes): **mean 0.89 ms, p99 0.92 ms**, of which the resolver is 0.57 ms mean (gate: p99 < 10 ms). §19's 4 ms target is met with no optimisation item needed.
> - `busk validate examples/phase2-busk.json`: 0 errors, 0 warnings. `busk run` on Appendix A prints the 8 limitation lines, the route line and the stats.
> - The manual checklist was rehearsed over loopback, with a virtual MIDI port and an sACN listener on 127.0.0.1. Steps 1–7 and 9 behave as written (README, *Busking checklist*). Running it on a real controller and rig remains, along with step 8 (latency).

**Manual checklist.** Use a nanoKONTROL2 or another controller with edited bindings. For the receiver, use a fixture through an sACN node, or sACNView / QLC+ / OLA. Wireshark with the filter `udp.port == 5568` dissects E1.31.

1. `busk run examples/phase2-busk.json` prints no limitations, the route line, and the matched MIDI port.
2. Raise fader 1 slowly. Every fixture follows the fader, and warm white comes in once the fader passes 2 %. Pull the fader to 0. Intensity drops with it, and the status line shows Warm going from `rel` to idle.
3. Raise fader 1, then press S3: everything fades to blue over 1 s. Press S4: red over 1 s, and Blue goes `rel` → idle. Press S4 again: back to warm, **not** blue.
4. With Red up, hold M3 (flash Blue, `includeLtp`). Everything is blue while held and exactly red again on release.
5. Raise fader 1, then press S6 and move fader 6. The heads move proportionally between their current position and Audience.
6. Hold M8: all white at full, over everything. Release it: the exact previous look returns.
7. Knob 8 scales all intensity. Holding ■ blacks out; releasing it restores the exact look.
8. MIDI → light latency feels immediate. The worst case is ~10 ms engine tick + ~23 ms output cycle.
9. Press Ctrl+C. The stats line shows 0 overruns and 0 command errors.

---

## 9. Spec gaps found while planning

Each gap is listed with the resolution this plan chose. Fold the resolutions into the spec once they are confirmed.

- **`threshold` LTP mode** only says "snaps in when the fader passes the threshold". Chosen: a button activation latches immediately; a fader activation latches on the upward crossing; LTP stays latched until release.
- **`followFader` with fades:** the spec says weight = level, but activation and release fades also apply. Chosen: `env × fader`.
- **`priorityBoost`:** it is unclear whether it is added to the playback's band or is an absolute band (the §7.2 table says "300"). Chosen: added, so 300 is a boost of 250 on a band-50 playback.
- **Flash identity:** the spec doesn't say whether a flash takes over the playback's own `seq`, or whether it applies exclusivity. Chosen: the flash is a separate source with its own `seq`, and it never applies exclusivity.
- **Release timing:** `releaseTime` (or `cmd.time`) applies to every family, with a fixed duration from the current weight. Cue `fadeOut` is a Phase 4 transition concept.
- **GO on an active single-cue list** is undefined. Chosen: re-assert with a fresh `seq`, or release if `releaseAtEnd`. `wrap` has no effect with one cue.
- **`autoStart` / `autoRelease` for `rate`, `size` and `crossfade` faders** are undefined. Phase 2 applies them to `master` only. Decide in Phases 4–5.
- **Toggle and latching blackout need state that stateless bindings lack.** `TOGGLE_PLAYBACK` is added to the command set. Blackout is momentary for now; decide on latching blackout in Phase 6, together with LED feedback.
- **Who owns the current page:** §15.2 lists `PAGE` as an engine performance command, but §4.1 resolves page-relative bindings *before* the bus. Recommendation for Phase 6: commands carry the page-relative slot, and the engine resolves it, since the UI snapshot needs the current page anyway.
- **Initial levels:** faders start at 0 and the GM at 1.0. `initialLevel` (§5.13) is mentioned but missing from the schema.
- **Spread:** the `center` / `edges` curves, the `n = 1` case, and members that lack the attribute are all undefined (resolved in decision 9).
- **Duplicate entries for one slot in a cue:** last wins. A duplicate `(scope, attribute)` within one preset is now a validation error.
- **Colour extras** mixing explicit and `NaN` values snap at the middle of the fade (decision 7).
- **Clamping** moves from every tick (§7.7) to compile time (decision 8).
- **Element 0 vs "whole fixture"** on multi-element fixtures: §5.7 says "whole fixtures (element 0)", but §5.5 makes element 0 the main element. Phase 2 does not fan element 0 out to cells. Decide before pixel effects (Phase 5).
- **More than one grand master:** their levels multiply.
- **Not assigned to any roadmap phase:**
  - `swop` — recommend Phase 3 or 6, together with the button set;
  - group masters and the `fadeTime` master — recommend Phase 5, with the other masters;
  - `RELEASE_ALL` / `OUTPUT_DISABLE` (§18) — recommend Phase 3;
  - the event log (§15.5) — recommend Phase 3, together with commands and undo.
- **§14.5 `OutputDriver`** is `async`. Phase 2's threaded scheduler makes it synchronous.
- **MIDI channel numbering** isn't stated. Chosen: 1–16, matching Appendix A.

---

## 10. What later phases change in this design

- **Phase 3.**
  - The programmer becomes one more `Source` at band 100; the resolver doesn't change.
  - The `select` button maps to `CompiledCue.targets`.
  - Show edits trigger a recompile, and the engine swaps the `CompiledShow` at a tick boundary. Each `PlaybackRuntime` is keyed by id and rebound to its new `CompiledPlayback`; its envelopes are kept.
  - Command validation must move into engine apply, because ids can now change.
  - The event log must record each command's *applied* tick time for exact replay.
- **Phase 4.**
  - `Source` arrays become per-transition interpolated values with per-lane weights. LTP and HTP already broadcast; snapping gains masks.
  - `Envelope` gains curves.
  - GO/BACK/GOTO replace re-assert, and most of the limitation list disappears.
- **Phase 5.** The relative pass runs after the absolute pass; group masters are added to stage 9.
- **Phase 6.**
  - Soft takeover, pages, feedback, OSC and web input.
  - Art-Net and DMX USB.
  - sACN send-on-change with keep-alive, termination and discovery.
