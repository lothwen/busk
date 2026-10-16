# Phase 1 — Fixtures: implementation plan

> Source spec: `busking-console-architecture-python.md` (§22, Phase 1). Builds on `phase-0-plan.md`. Module paths refer to the Phase 0 layout (phase-0-plan §3).

## Context

The spec scopes Phase 1 as *"Profiles (hand-written JSON), patch, slot compiler, conversion incl. 16-bit, RGBW, virtual dimmer, shutter guard"*. It is done when *"logical values produce correct DMX for 3 real fixture types"*.

Phase 0 leaves a walking skeleton: show file → validate → compile (base images) → engine thread → frame handoff → console output thread. Its engine implements only stages 12–13, and stage 12 just copies the base image. Phase 1 makes stage 12 real:

- it compiles the patch into a **slot table** (§6.1) and a **logical frame** of float lanes (§6.2);
- it converts that frame to DMX through the fixture profiles (§13), writing slot-driven channels over the base image every tick.

Nothing produces logical values yet, because playbacks and the resolver are Phase 2. Phase 1 feeds the engine a **static logical frame**: the attribute defaults, overlaid with values from an optional file passed to `busk run --values`. Phase 2's resolver replaces the file and keeps everything downstream of it.

**Precondition:** Phase 0 is implemented and its acceptance tests pass. Today the repository holds only the spec and the plans.

**Done when:**
- `busk run examples/phase1-demo.json --values examples/phase1-values.json` prints exactly the DMX that the manufacturers' charts give for three real fixtures (§3). Golden tests check this, and their expected bytes were worked out by hand from the charts.
- The §7.8 DMX conversion table passes as a golden test on Appendix A.
- Appendix A, run with no values, outputs its shutters **open** (the shutter guard).
- Converting a 64-universe benchmark rig takes less than 1 ms (median).

---

## 1. Scope

| In Phase 1 | Deferred (to) |
|---|---|
| Slot table §6.1, including derived slots (virtual intensity, function parameters); lanes §6.2; default frame | `Slot.groupMasters` (Phase 2, with group masters) |
| Value encoding `AttributeValue` → lanes (Phase 2's cue compiler reuses it) | Cue / preset / group expansion §6.3 (Phase 2) |
| Compiled channels: patch addresses, fine offsets, orientation, capabilities, option tables, byte ownership on overlap | `elementPatch` (still `UnsupportedFeature`; semantics proposed in §9) |
| Conversion §13: range capabilities (incl. multi-segment), 8/16/24-bit, `invert`, pan/tilt swap/offset/invert, dimmer curves, virtual intensity, RGB / RGBW / explicit extras / CMY, wheel and prism slots, shutter functions with strobe parameter, shutter guard, untouched channels | Colour → colour-wheel matching (Phase 2, when global colour presets first need it; hysteresis in Phase 4, with colour fades). Calibrated least-squares / NNLS mixing for RGBA, RGBAW+UV… (Phase 7, with GDTF import). Output gamma (the schema has no field for it) |
| Profile validation rules that conversion depends on | Masters, blackout, park, limits, strobe cap, highlight (Phases 2 and 7) |
| Static values file, `busk run --values` | Resolver, command queue (Phase 2) |
| Three real fixture profiles, hand-transcribed, in a demo show | GDTF / OFL import (Phase 7) |
| Vectorised converter and a benchmark | Network output (decision 14) |

---

## 2. Decisions and assumptions

1. **Static logical frame.** `--values FILE` takes a JSON list of `ParkEntry`-shaped entries, so the file reuses the show schema and the Phase 0 park validators:
   ```json
   [ { "slot": { "target": { "fixtureId": "fx-mh1", "element": 0 }, "attribute": "pan" }, "value": 90 },
     { "slot": { "target": { "fixtureId": "fx-mh1", "element": 0 }, "attribute": "colorWheel" }, "value": { "slot": "red" } } ]
   ```
   The CLI compiles the file once into a logical frame. Later entries override earlier ones for the same slot. Each tick, the engine copies the frame into a working buffer, which is where Phase 2's stages 1–11 will write. Entries are stricter than cue entries: an attribute the target doesn't have, or a discrete `slot` that isn't one of the channel's options, is an **error**. A cue entry in that situation is silently dropped (§6.3).
2. **Conversion is vectorised.** The compiler flattens every channel into a *conversion plan*, a structure of numpy arrays. The converter runs a fixed sequence of array kernels over it, so the Python work per tick does not grow with rig size. Measured on the dev machine (Python 3.14.7, numpy 2.5.3):
   - a per-channel Python loop over 32 000 channels takes **~4.3 ms** for the simplest channel kind, with no branching. That is 4× the §19 budget (masters + safety + conversion < 1 ms);
   - a numpy model of the same work takes **~0.4 ms** median.

   Numpy temporaries are acceptable inside the tick: ndarrays are not tracked by the cyclic GC (checked), so they add no GC pauses. Per-channel or per-slot Python objects are not acceptable.
3. **A per-channel reference converter is the test oracle.** `tests/reference_convert.py` transcribes §13 channel by channel and reads the readable `CompiledChannel` records. The fast converter reads the plan built from those same records. The golden suites run against both converters, and a property test asserts that they agree byte for byte on random frames. Both use the same operation order, so their float results are identical.
4. **Slot allocation.** Fixtures are walked in show order, then elements in index order. Each element gets slots in **registry order** (the §5.3 table) for:
   - every attribute that has a channel on the element, **except `control`**;
   - `intensity`, if the mode's `intensityStrategy` is `virtual` and the element has additive colour channels but no intensity channel. This is the virtual dimmer (§13.2). The rule is per element, so a bar with a master dimmer and RGB cells works under either strategy;
   - every `param.attribute` of a function capability on the element, unless the slot already exists (e.g. `strobeRate` from a shutter's strobe range).

   Unpatched fixtures get slots, because they are still programmable, but no channels. `control` channels never get slots: they are untouched channels (§13.5) and output `defaultDmx`.
5. **Lanes** follow §6.2:
   - scalar → 1 lane, in logical units;
   - colour → `r, g, b`, then whichever extras the element has, always in the order `w, a, uv`. `NaN` means "derive";
   - discrete → 1 lane holding the option index as a float.

   The default frame encodes the registry defaults. `zoom`'s `"profileMidpoint"` resolves to the midpoint of `physical.zoomRange`, falling back to the midpoint of the zoom channel's capability values.
6. **Discrete options.**
   - A wheel or prism channel's options are its `slot` capabilities, in DMX order.
   - A `shutter` channel's options are its `function` capabilities whose `fn` is one of `open`, `closed`, `strobe`, `pulse`, `random`.
   - When an id appears twice, the first capability wins. The MH-X25 has two "open" ranges on its shutter and two "open" ranges on its gobo wheel.
   - All other capabilities (shake, wheel spin, macros) are never output.
   - An option outputs the centre of its DMX range, `(lo + hi) // 2` (§13.4).
7. **The shutter guard comes from the defaults.** The registry default for `shutter` is `open`, and slot-driven channels ignore `defaultDmx`. An uncontrolled shutter therefore outputs its `open` function. A new validation rule (§5.6) makes the guard total: every discrete channel must offer its attribute's default option.
8. **Capabilities are authoritative for scalars**, including pan and tilt. §13.1's `(deg + range/2) / range` is the special case of a capability that spans ±range/2; `physical.panRange` is informational. For a value `v` on a channel with range segments:
   - Choose the first segment whose value interval contains `v`. If none does, choose the nearest one (the first on ties) and clamp `v` into it.
   - Map with `t = (v − v0) / (v1 − v0)` and `raw = rint(d0 + t · (d1 − d0))`.
   - A zero-span segment (`v0 == v1`) outputs `(d0 + d1) // 2`.
   - `invert` reverses each range segment's value direction, by swapping `v0` and `v1` at compile time. DMX ranges and `defaultDmx` therefore always stay in wire values.
9. **Rounding is round-half-even** (`np.rint`, the same rule as the spec's Python `round`).
10. **Orientation** applies to pan and tilt channels on every element. The source is the other attribute's lane when `swapPanTilt` is set, and the channel's own lane otherwise. Then `deg = source + offset`, negated if inverted. Offset and invert are the **channel's** own settings: the pan channel uses `panOffset` and `invertPan`. This follows §13.1's order. The compiler folds orientation into a per-channel `(srcLane, offset, sign)`.
11. **Intensity curves.** The mode's `dimmerCurve` applies under both strategies: before a dimmer channel is mapped, and before virtual intensity multiplies the emitters. For x ∈ [0, 1]:
    - `linear`: x
    - `square`: x²
    - `invSquare`: 1 − (1 − x)²
    - `sCurve`: x²(3 − 2x), the spec's smoothstep
    - a table: piecewise linear over equally spaced points
12. **Colour (the Phase 1 subset of §13.3)**, per element:
    - **Additive** (requires red, green and blue channels). If the element has a white emitter and its `w` lane is `NaN`, then `w = min(r, g, b)` and `w` is subtracted from r, g and b (the spec's fast method). An explicit `w` is used as given, with no subtraction. The `a` and `uv` lanes are used when not `NaN`, and are 0 otherwise. Any other additive emitter (lime, cyan, custom) outputs 0 until calibrated mixing exists. The RGB emitters already reach every colour in their gamut; the extras only widen it.
    - **Subtractive** (requires all three flags): `c = 1 − r`, `m = 1 − g`, `y = 1 − b`.
    - **Virtual intensity** multiplies every additive emitter value, extras included, by `curve(intensity)`.
    - **Emitters**: a `component` resolves to `profile.emitters` when declared, else to a built-in id. Appendix A's par declares no emitters. Phase 1 needs only each emitter's id and its `subtractive` flag; emitter colours only matter for calibrated mixing.
13. **Byte ownership on overlap.** Phase 0's base image lets the later fixture in list order win each byte. The plan keeps a driven write only if its byte belongs to that channel under the same rule, so scatter indices are unique. This is necessary because numpy does not define which write wins when a fancy-index assignment repeats an index.
14. **Network output stays deferred.** Phase 1 is verified byte for byte against the manufacturers' charts. The recommendation is a short **Phase 1.5 (sACN)** straight after, so the real fixtures can be checked on hardware before Phase 2's MIDI demo (scope in §10).
15. **Immutability.** Compiled dataclasses are frozen and use tuple fields. Shared numpy arrays are made read-only (`flags.writeable = False`), because the compiled show is shared between threads.
16. **New dev dependency: `hypothesis`**, for the property tests in §20. Phase 2's resolver properties will need it too.

---

## 3. Real fixtures

The three fixtures are chosen so that, between them, they exercise every Phase 1 conversion feature. They are popular budget models with Open Fixture Library (OFL) definitions to cross-check against:

| | Fixture | Mode | Exercises |
|---|---|---|---|
| A | **Stairville MH-X25** (LED spot) | 12ch | 16-bit pan/tilt with **non-adjacent** fine channels (coarse at offsets 0–1, fine at 2–3). Colour and gobo wheels. A shutter whose DMX 0 is **closed** (the shutter guard), with a strobe range and a duplicate "open" range. A gobo-rotation channel that mixes index, CW and CCW ranges (multi-segment mapping). `positionSpeed`. An 8-bit dimmer. Two control channels, which stay untouched |
| B | **Eurolite LED ML-56 RGBW** | 4ch | RGBW with **no dimmer channel**: virtual intensity and white extraction |
| C | **Chauvet DJ COLORband PiX** | 36ch | 12 elements (RGB cells): per-element slots and virtual intensity per cell |

Appendix A's generic spot covers the rest: a 16-bit dimmer, `invertPan`, and the §7.8 numbers.

**Transcription rules**
- The manufacturer's manual is the source. Cross-check against OFL (`stairville/mh-x25`, `eurolite/led-ml-56-rgbw`, `chauvet-dj/colorband-pix`). Where the two disagree, the manual wins and the profile's `notes` records the disagreement.
- Charts often describe speeds as "slow → fast" with no units. The `strobeRate` (Hz) and `gobo1Rotation` (deg/s) ranges are then estimates (measure them if possible), and `notes` says so.
- Write ranges the busking model can't express (colour-wheel split colours and colour fades, gobo shake, wheel spin, macros) as `function` capabilities with descriptive custom `fn` names. The profile stays a complete record of the chart, and nothing outputs those ranges.
- MH-X25 gobo rotation: stop is `{dmx [0, 0], value [0, 0]}` (index at 0°). CW speeds are positive deg/s over the CW range, and CCW speeds are negative deg/s over the CCW range.
- If you own different fixtures, substitute models that cover the same rows of the table.

**Example expectations**, worked out by hand from the chart (MH-X25 at address 1):
- **Defaults** → `1=128 2=128 6=2 7=5 9=3`. Pan and tilt are centred (32768 → 128/0), the colour wheel is open (centre of 0–4), the gobo wheel is open (centre of 0–7), and the **shutter is open (centre of 4–7) rather than at DMX 0, which is closed**.
- **Pan 90°, tilt −45°** → `1=170 3=170` (raw 43690) and `2=85 4=85` (raw 21845).
- **The same pan on a fixture with `invertPan`** at address 13 → `13=85 15=85`.
- **ML-56 at address 25** (linear dimmer curve), intensity 0.8, colour `{1, 0.5, 0}` → `25=204 26=102 27=0 28=0`.

---

## 4. Project layout (additions to Phase 0)

```
src/busk/
  compiler/
    compile.py          # CompiledShow gains slots (SlotTable), channels, plan
    slots.py            # Slot, SlotTable, build_slots(): allocation, lanes, options, defaults (§6.1–6.2)
    lanes.py            # encode_value(slot, value) → lanes; Phase 2's cue compiler reuses it
    channels.py         # CompiledChannel, build_channels(): addresses, orientation, segments, options, ownership
    values.py           # compile_values(compiled, entries) → static logical frame
  convert/
    dmx.py              # split_raw (Phase 0); now also applied to int arrays
    curves.py           # dimmer curves, vectorised
    plan.py             # ConversionPlan (structure of arrays), build_plan()
    converter.py        # Converter.convert(frame, out): the kernels
  persistence/values_file.py   # load_values(path, show) → entries, issues
  model/validate.py            # + Phase 1 rules (§5.6)
  engine/loop.py               # tick: copy logical frame → convert → publish
  cli.py                       # run --values
examples/phase1-demo.json  examples/phase1-values.json      # replace phase0-demo.json
tests/
  builders.py                  # synthetic profiles/shows, incl. the "feature matrix" show
  reference_convert.py         # per-channel oracle (§13, transcribed)
  test_slots.py test_lanes.py test_channels.py
  test_convert.py              # golden cases, parametrised over the reference and fast converters
  test_convert_properties.py   # hypothesis: differential, round-trip, monotonic, safety
  test_real_fixtures.py        # chart-derived goldens for the demo show
  test_values_file.py test_perf.py
  test_validate.py test_engine.py test_cli.py   # extended / updated
```

---

## 5. Component design

### 5.1 Slots (`compiler/slots.py`)

```python
@dataclass(frozen=True, kw_only=True)
class Slot:
    index: SlotIndex
    target: TargetRef
    attribute: AttributeDefinition
    laneOffset: int
    laneCount: int
    options: tuple[str, ...] = ()                     # discrete: option ids; the lane holds the index
    extras: tuple[Literal["w", "a", "uv"], ...] = ()  # colour: lanes after r, g, b

@dataclass(frozen=True, kw_only=True)
class SlotTable:
    slots: tuple[Slot, ...]
    laneCount: int
    byKey: Mapping[tuple[TargetKey, AttributeId], SlotIndex]
    defaultFrame: NDArray[np.float64]                 # read-only
```
- A slot's options come from its channel (decision 6). Phase 0 makes `(element, attribute, component)` unique, so a discrete attribute has exactly one channel per element and its option list is unambiguous.
- `groupMasters` (§6.1) arrives in Phase 2, together with group masters.

### 5.2 Lanes (`compiler/lanes.py`)
- `encode_value(slot, value) -> tuple[float, ...]`:
  - scalar → `(v,)`;
  - colour → `(r, g, b, *extras)`. Extras come from the value when present and are `NaN` otherwise. Extras the element doesn't have are dropped, so a colour preset with `uv` still works on a fixture without UV;
  - discrete → `(options.index(slot),)`. Raises `EncodeError` if the option doesn't exist; the caller decides what that means (the values file reports an error, and Phase 2's cue compiler will drop the entry).
- A kind mismatch can't happen here, because validation has already checked value shapes.

### 5.3 Compiled channels (`compiler/channels.py`)

There is one record per slot-driven DMX channel of a patched fixture:

```python
@dataclass(frozen=True, kw_only=True)
class Segment:                         # one range capability, after `invert`
    v0: float
    v1: float                          # logical units
    d0: int
    d1: int                            # raw, full resolution

@dataclass(frozen=True, kw_only=True)
class OptionOut:
    raw: int                                   # centre of the capability's DMX range
    param: tuple[SlotIndex, Segment] | None    # e.g. strobe: strobeRate slot → strobe range

@dataclass(frozen=True, kw_only=True)
class CompiledChannel:
    fixtureId: FixtureId
    offset: int                                # within the footprint, for diagnostics
    universe: int                              # row in the universe buffers
    addresses: tuple[int | None, ...]          # 0-based bytes: coarse[, fine[, ultra]]; None = owned by a later fixture
    kind: Literal["range", "color", "option"]
    slot: SlotIndex                            # main input (after pan/tilt swap)
    segments: tuple[Segment, ...] = ()         # range, color
    offsetDeg: float = 0.0                     # range: pan/tilt orientation
    sign: float = 1.0
    curve: DimmerCurve | None = None           # intensity range channels; colour channels with virtual intensity
    component: str | None = None               # color
    intensitySlot: SlotIndex | None = None     # color: virtual intensity
    options: tuple[OptionOut, ...] = ()        # option
```
- Records are built in fixture order. Byte ownership (decision 13) is worked out in the same pass, over **all** channels, both driven and untouched, exactly as the base image is written.
- The relation between slots and channels is not one-to-one. A colour slot drives several channels. A virtual intensity slot drives none directly. A `strobeRate` slot may only feed option parameters.

### 5.4 Conversion plan and converter (`convert/plan.py`, `convert/converter.py`)

`build_plan(channels, slotTable)` flattens the records into arrays. `Converter(plan)` preallocates its scratch buffers and exposes `convert(frame, out)`. `frame` is the float64 logical frame, and `out` is the `(U, 512)` uint8 back buffer, which already holds the base image. The kernels run in this order:

1. **Range inputs.** For every range channel: `V = (L[src] + offsetDeg) * sign`. Then, for intensity channels grouped by curve: `V = curve(clip(V, 0, 1))`.
2. **Colour inputs.** For each colour slot:
   - gather `r, g, b` (clipped to 0..1) and its extras;
   - derive `w` and the subtraction amount `s` (decision 12);
   - fill a small matrix with one row per component code and one column per colour slot. The rows are `r−s, g−s, b−s, w, a, uv, 1−r, 1−g, 1−b, 0`.

   Each colour channel then selects its entry with a single fancy index and multiplies it by `curve(clip(L[intensityLane], 0, 1))` where it has virtual intensity (by 1 elsewhere). The results go into `V`.
3. **Segment mapping, `V → raw`** (decision 8). Channels fall into two buckets:
   - single-segment channels (almost all of them) are mapped with one set of array operations;
   - multi-segment channels use `(n, K)` arrays padded with `+inf` distance. `argmin` along axis 1 returns the first minimum, which is the first segment on ties. These channels are then mapped the same way.

   Zero-span segments use their precomputed centre.
4. **Options.** `i = clip(rint(L[lane]), 0, n − 1)` and `raw = optionRaw[start + i]`. When the chosen option has a parameter, the parameter slot's lane is mapped through the parameter segment instead.
5. **Split and scatter.** There is one group per byte count. Each group runs `split_raw` on the int array, then `out.ravel()[addr] = byte`, using the precomputed unique addresses.

Python loops run only over a fixed set of groups (curves and byte counts), never over channels or slots. The plan is built once per compile.

### 5.5 Engine and CLI
- `Engine(compiled, clock, logical: NDArray | None = None)`. The default is `compiled.slots.defaultFrame`. The engine owns its `Converter` and that converter's scratch buffers. Its tick:
  ```python
  np.copyto(self._work, self._logical)                # stages 1–11 write here from Phase 2
  np.copyto(self._back, self._compiled.baseImages)    # untouched channels (§13.5)
  self._converter.convert(self._work, self._back)     # stage 12
  # stage 13: publish Frame (unchanged)
  ```
- `busk run SHOW [--values FILE] [--duration S]`:
  1. load and check the values file (on errors, print them and exit 1);
  2. compile it into the logical frame;
  3. start the threads as in Phase 0. The notice now reads `console output only — N output route(s) in the show are ignored`.
- `busk validate` reports the new rules.

### 5.6 New validation rules (`model/validate.py`)

These are added as rows of the Phase 0 semantic pass. All of them are errors, and every issue carries a path:

| Area | Rule |
|---|---|
| Capabilities by kind | A scalar or colour channel has at least one `range` capability. A wheel or prism channel has at least one `slot` capability. A shutter channel has at least one function among `open`, `closed`, `strobe`, `pulse`, `random` |
| Default options | Every discrete channel offers its attribute's default option (`open`; `off` for prism). This is what makes the shutter guard total |
| Function params | `param.attribute` is a scalar attribute in the registry |
| Colour systems | Every `component` is a declared emitter or a built-in id. An element's colour channels are either additive (with red, green and blue) or subtractive (with all three flags), never a mix |
| Intensity strategy | A `dimmerChannel` mode has at least one intensity channel, so blackout can always reach the fixture. A `virtual` mode has at least one element with additive colour channels and no intensity channel |
| Dimmer table | At least 2 points, each in 0..1 |
| Orientation | A fixture with `swapPanTilt: true` has both pan and tilt on every element that has either |

The values file is checked in three passes:
1. structurally, as `list[ParkEntry]` with the strict adapter;
2. semantically, by the Phase 0 park checks, factored out for reuse (the target exists, the attribute is in the registry and isn't `control`, the value has the right shape);
3. against the compiled show: the slot exists on that target, a discrete `slot` is one of the options, and a given `wheel` is the channel's wheel.

Issue paths look like `values[3].slot.attribute`.

### 5.7 Demo show and values
- `examples/phase1-demo.json`:
  - universe `u1` "Stage";
  - profiles A, B and C;
  - fixtures: MH-X25 #1 at 1, MH-X25 #2 at 13 with `invertPan`, ML-56 at 25, COLORband PiX at 29 (29–64);
  - every other collection empty, plus one sACN route, which is ignored.
- `examples/phase1-values.json`:
  - MH 1: intensity 1, pan 90, tilt −45, colour wheel red, gobo 3;
  - MH 2: the same pan, to show the inversion; shutter strobe, `strobeRate` 5;
  - ML-56: intensity 0.8, colour `{1, 0.5, 0}`;
  - COLORband: intensity 1 on every cell, with cells alternating red and blue.
- `examples/phase0-demo.json` is deleted. It went dark by design (phase-0-plan §9).

---

## 6. Implementation steps

Each step follows TDD: write the listed tests first, then make them pass.

0. **Preconditions.** Phase 0 is green (pytest, ruff and mypy are clean). Run `uv add --dev hypothesis`. Register a `perf` marker and exclude it from the default run (`addopts = "-m 'not perf'"`).
1. **Transcribe the real profiles** (§3) into `examples/phase1-demo.json`. Write their chart-derived golden tables in `tests/test_real_fixtures.py`, marked `xfail(strict=True)` until step 7. → *verify:* `busk validate examples/phase1-demo.json` reports 0 errors under the Phase 0 rules. Doing this first brings out what real charts need (duplicate ranges, zero-span stops, mixed channels) before the compiler is shaped around Appendix A alone.
2. **Validation rules** (§5.6). → *verify:* `test_validate.py` gains one table-driven case per new row. Each case mutates Appendix A or the demo show and asserts the exact `(severity, path)`. Appendix A and the demo still give 0 errors and 0 warnings.
3. **Slots and lanes.** → *verify:* `test_slots.py` checks that:
   - Appendix A's slot list is exactly, per spot: `intensity, pan, tilt, color (r,g,b,w), zoom, gobo1, shutter, strobeRate`; and for the par: `intensity (virtual), color (r,g,b)`;
   - the default frame holds zoom 21.0, shutter = the index of `open`, gobo1 = the index of `open`, and colour `1, 1, 1, NaN`;
   - the COLORband has 12 elements × (intensity, color), and the MH-X25's control channels have no slots;
   - an unpatched fixture has slots, and two compiles produce identical tables.

   `test_lanes.py` covers each kind's encoding: extras missing from the value become `NaN`, extras the element lacks are dropped, and an unknown option raises `EncodeError`.
4. **Compiled channels.** → *verify:* `test_channels.py` checks:
   - the golden channel table for Appendix A (addresses, kinds, segments);
   - MH 2 has `sign = −1`;
   - on a swapped fixture, the pan channel reads the tilt lane and uses `panOffset`;
   - the MH-X25's fine bytes land at offsets 2 and 3;
   - `invert` swaps segment values;
   - with overlapping fixtures, the earlier fixture loses exactly the shared bytes;
   - option tables hold centres, the first "open" wins, and shake/spin ranges are absent.
5. **Reference converter and golden suite.** Write `tests/reference_convert.py` and `test_convert.py`. The suite is parametrised over a `convert(compiled, frame) → universes` fixture; for now only the reference implements it. Expected bytes are computed by hand in the test, written as the spec's formula with literal numbers. They are never produced by running the code. Cases:
   - **§7.8 table**, Appendix A MH1: `9=122 10=225` (dimmer), `1=138 2=170` (pan), `5=0 6=0 7=64 8=191` (RGBW);
   - **Appendix A defaults**: `1=128 3=128 8=255 11=128 12=4 13=11 17=128 19=128 24=255 27=128 28=4 29=11`. The shutters are open at 13 and 29, where Phase 0 printed 0;
   - **rounding at exact halves**, including one case where half-even and half-up disagree (segment `dmx [0, 253]` at t = 0.5 → 126); a 24-bit split; non-adjacent fine bytes; an inverted dimmer; each curve at 0, 0.25, 0.5 and 1, and a table curve;
   - **multi-segment mapping**: a value inside each segment, in a gap (nearest segment), beyond both ends (clamped), and a zero-span centre;
   - **colour**: virtual intensity 0 → every emitter 0; RGBW white extraction; an explicit `w` (no subtraction); `a` and `uv` explicit and derived (0); CMY;
   - **shutter**: open by default; strobe maps `strobeRate` through the parameter range and clamps it;
   - **pan/tilt**: invert, offset, swap;
   - untouched control channels keep `defaultDmx`, and unpatched addresses stay 0.

   → *verify:* the whole suite is green against the reference. Synthetic cases come from a **feature-matrix show** in `builders.py`, which has one fixture per edge case.
6. **Plan and fast converter.** → *verify:* the step-5 suite passes for both implementations. `test_convert_properties.py` (hypothesis) checks:
   - **differential**: fast == reference, byte for byte, on random frames for Appendix A, the demo show and the feature-matrix show. Frames include out-of-range values and `NaN` extras;
   - **round-trip**: on a single-segment channel, inverting the raw value lands within one DMX step of the clamped input;
   - **monotonicity**: raw never decreases as `v` increases, on a segment with `v1 > v0` and `d1 > d0`;
   - **safety**: intensity 0 puts every dimmer channel at its 0-intensity value and every virtual element's additive emitters at 0. Phase 2's blackout relies on this;
   - **`split_raw`** recombines exactly for every 16-bit value.

   Then run the step-9 benchmark once, to catch performance surprises early.
7. **Engine integration.** Update `Engine.tick` and remove the step-1 `xfail` markers. → *verify:* the updated `test_engine.py` shows that frames equal the converted Appendix A defaults. All Phase 0 timing and determinism tests still pass, and `test_real_fixtures.py` is green.
8. **Values file and CLI.** → *verify:*
   - `test_values_file.py`: a valid file compiles, and later entries override earlier ones. Each of these is an error with its path: an attribute the target lacks, an unknown option, a mismatched `wheel`, an unknown fixture, a wrong value shape, and `control`.
   - `test_cli.py`: `busk run examples/phase1-demo.json --values examples/phase1-values.json --duration 0.3` prints the golden line exactly once and exits 0. The same command on Appendix A without values prints the defaults line. A bad values file exits 1.
9. **Benchmark** (`test_perf.py`). The rig is built by `builders.py`. Each universe holds 4 Appendix A spots, 6 MH-X25, 10 ML-56 and 9 COLORband PiX, about 500 channels. Across 64 universes that is ≈ 20 600 slots and ≈ 31 000 channels, the §19 reference size. The test reports the compile time and times `convert` over random frames. → *verify:* median < 1 ms, with p99 reported. If it is over budget, profile each kernel before changing anything. The likely culprits are fancy-index gathers (switch to `np.take(..., out=)`) and temporaries (switch to preallocated scratch).
10. **Full verification pass** (§8).

---

## 7. Acceptance tests (summary)

| Test file | Proves |
|---|---|
| `test_validate.py` (extended) | Every Phase 1 profile rule fires with the right path; Appendix A and the demo are clean |
| `test_slots.py` / `test_lanes.py` | Slot allocation, lane layout, defaults (zoom midpoint, shutter open), encoding |
| `test_channels.py` | Addresses, fine offsets, orientation folding, `invert`, options, byte ownership |
| `test_convert.py` | Golden bytes for both converters: §7.8, Appendix A defaults, every §13 rule in Phase 1 scope |
| `test_convert_properties.py` | Fast == reference; round-trip within one DMX step; monotonic; intensity 0 ⇒ dark |
| `test_real_fixtures.py` | **The done criterion:** chart-derived DMX for the MH-X25, ML-56 RGBW and COLORband PiX |
| `test_values_file.py` | Values file errors and override order |
| `test_engine.py` / `test_cli.py` (updated) | The engine publishes converted frames; `run --values` works end to end |
| `test_perf.py` (`-m perf`) | Conversion of the §19 reference rig takes < 1 ms |

---

## 8. Verification

```bash
uv run pytest                                          # all green
uv run pytest -m perf -s                               # median convert < 1 ms on the 64-universe rig
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run busk validate examples/phase1-demo.json         # → 0 errors, 0 warnings
uv run busk run tests/fixtures/appendix_a.json --duration 1
    # → "U1 Stage: 1=128 3=128 8=255 11=128 12=4 13=11 17=128 19=128 24=255 27=128 28=4 29=11"
uv run busk run examples/phase1-demo.json --values examples/phase1-values.json
    # → one line equal to the chart-derived golden; Ctrl+C → 0 overruns, max tick ≪ 10 ms
```

---

## 9. Spec gaps found while planning

**Resolved by this plan** (the spec should adopt or amend these):
- How `invert` works alongside capabilities, and how the §13.1 pan/tilt formula relates to them (decision 8).
- The order of the orientation steps, and which offset applies after a swap (decision 10).
- `invSquare` is undefined, and it is unclear whether the dimmer curve applies to virtual intensity (decision 11).
- The rounding rule (decision 9). Zero-span range capabilities (decision 8).
- Duplicate option ids on one channel, and which function `fn`s count as shutter options (decision 6).
- `intensityStrategy` is set per mode, but elements can differ (decision 4's per-element rule).
- `emitters` is optional, so colour components need built-in meanings (decision 12).
- Phase 0's open questions about `zoom`'s midpoint (decision 5) and Appendix A's closed shutter (decision 7) are now closed.

**Still open:**
- **Colour → colour wheel** (deferred to Phase 2). Until a derived `color` slot maps colours to the nearest wheel colour, wheel-only fixtures accept only `colorWheel`. That slot needs a precedence rule for when both `color` and `colorWheel` are controlled. Proposal: an explicitly controlled `colorWheel` wins. That requires the resolver to report which slots have contributions, so Phase 2 must decide.
- **`NaN` extras don't interpolate.** `lerp(NaN, x, w)` is `NaN`. Phase 2's LTP stack must define how a derived extra blends with an explicit one.
- **Indexed gobo rotation.** The registry has only `gobo1Rotation` (deg/s), so a fixture's index-angle range has no attribute. The MH-X25 profile uses index 0° as "stopped".
- **Strobe units.** Many charts give no Hz, so profiles carry estimates. The alternatives are to accept estimates or to add a normalised strobe speed.
- **Output gamma** (§13.3) has no profile field.
- **Single-emitter colour elements** (UV-only, white-only) are rejected by the colour-system rule. They need their own rule, e.g. driven by explicit lanes only.
- **`elementPatch`.** Proposal: a split element's channels keep their relative spacing, and the element's lowest-offset channel lands at the element's own address. Elements without an entry use the fixture patch. This is not implemented yet.
- **`control`** has a registry default (`none`) but never gets a slot. That is right for busking, but the lamp-on and reset commands (Phase 6/7) will need their own path to those channels.

---

## 10. What Phase 2 changes in this skeleton

- The resolver's output replaces the static logical frame. `encode_value` becomes the lane encoder of the cue compiler (§6.3).
- `Slot` gains `groupMasters`, and the slot table exposes intensity-lane indices for masters and blackout.
- Colour → wheel matching lands, along with a decision on its precedence and on how `NaN` extras blend (§9).
- **Recommended before Phase 2's MIDI demo — Phase 1.5, sACN output:**
  - the `OutputDriver` protocol (§14.5);
  - E1.31 data packets, sent multicast to `239.255.{hi}.{lo}` or unicast;
  - per-universe sequence numbers;
  - send-on-change with a keep-alive well inside the 2.5 s timeout;
  - Stream_Terminated packets on shutdown;
  - CID, source name and priority taken from the show.

  The Phase 0 poll loop becomes the §14 scheduler. Phase 1.5 also settles whether console printing becomes a debug driver or stays a CLI option (phase-0-plan §8).
