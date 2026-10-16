# Phase 0 — Skeleton: implementation plan

> Source spec: `busking-console-architecture-python.md` (§22, Phase 0). Once approved, this document is saved as **`phase-0-plan.md`** in the project root, next to the spec.

## Context

The repository currently holds only the architecture spec. Phase 0 is the first code. The spec scopes it as *"Show schema + validation, attribute registry, fake/real clock, engine loop, Art-Net or sACN output of a static frame"*, and it is done when *"a hand-written show lights a fixture with a fixed value"*.

Phase 0 builds the **walking skeleton** that every later phase extends: show file → validate → compile → engine thread (fixed tick) → frame handoff → output thread. Later phases add pipeline stages (§4.2) to this skeleton and leave the plumbing alone.

Two scope decisions were made during planning:

- **No network output yet.** The output thread prints universe contents to the console. `output.routes` in the show is still validated, but nothing uses it.
- **The fixed value comes from the base image.** The compiler builds a per-universe *base image*: every channel of a patched fixture holds its profile's `defaultDmx`, and every other address is 0. That is the permanent §13.5 rule for channels that no slot drives. Phase 1 converts slot-driven channels and writes them over this image.

**Done when:** `busk run examples/phase0-demo.json` prints the demo fixture's channels once, at their fixed values. The engine then keeps ticking at `engineHz` with zero overruns until Ctrl+C, and on exit it prints its tick statistics. All acceptance tests in this plan pass.

---

## 1. Scope

| In Phase 0 | Deferred (to) |
|---|---|
| Full persistent schema §5.1–§5.17 as `TypedDict`s, plus the §15.2 command types (`Binding` → `CommandAction` needs them) | Runtime model §5.18 (Phases 2–5) |
| Attribute registry §5.3 + values §5.4 | Slot table, lanes, conversion (Phase 1) |
| Structural + semantic validation with path-addressed issues | Profile import GDTF/OFL (Phase 7) |
| Load a plain `.json` show and check `schemaVersion == 1` | ZIP `.show` container, atomic save, backups, autosave (Phase 3) |
| Compiler: universe table + base images | Incremental recompile / live swap §6.4 (Phase 3) |
| `Clock` protocol, `MonotonicClock`, `FakeClock` | Speed masters / beat phase (Phase 4) |
| Engine thread: fixed tick, drop-don't-spiral, overrun + tick-time stats, publish immutable frames | Command queue (Phase 2), `dt` (first stage that needs it, Phase 4) |
| Console output thread: polls the latest frame, prints universes that changed | Art-Net / sACN / DMX-USB drivers, `OutputDriver` protocol §14.5 |
| CLI: `busk validate`, `busk run` | Migrations chain (added with the first schema change) |

Network output was in the spec's Phase 0 and has been deferred. It needs a new slot before the Phase 2 demo ("operator can busk with MIDI faders"), because that demo needs real light.

---

## 2. Decisions and assumptions

1. **Package `busk`**, src layout, managed with **uv**. The name comes from Appendix A's `meta.app`, and it is easy to rename. `requires-python = ">=3.12"` because the code uses PEP 695 `type` statements; development happens on the installed 3.14.7.
2. **Dependencies:** `numpy` (universe buffers, later lanes) and `pydantic` (validation). Dev dependencies: `pytest`, `ruff`, `mypy`.
3. **Validation = pydantic `TypeAdapter(Show)` over the spec's own TypedDicts.** The schema code stays a direct transcription of §5, and the plain-dict data model is kept. Settings:
   - `validate_json(text, strict=True)`. Strict JSON mode rejects `"1.5"` for a float and `0/1` for a bool, but still accepts ints for floats and arrays for tuples.
   - Every TypedDict is decorated `@with_config(STRICT)`, where `STRICT = ConfigDict(extra="forbid", allow_inf_nan=False)`, so typos in hand-written shows are errors.
   - Unions tagged by `kind` / `type` / `protocol` are wrapped in `Annotated[..., Field(discriminator=...)]`, which gives precise errors.
   - Simple numeric ranges are declared with `Annotated` aliases (e.g. `DmxAddress = Annotated[int, Field(ge=1, le=512)]`, `Unit = Annotated[float, Field(ge=0, le=1)]`).
   - Rules that span fields or entities go in a hand-written semantic pass (§4.3).
4. **Naming:** data fields keep the spec's camelCase in both TypedDicts (they are JSON keys) and dataclasses, so code and spec stay greppable. Functions, methods and modules are snake_case.
5. **Frame handoff:** each tick, the engine fills a preallocated numpy back buffer, then publishes an immutable `Frame` (a tuple of `bytes`) with a single reference assignment. In Python this is the equivalent of the §14.1 double-buffer swap: no tearing, no locks, and the output thread only reads. `bytes` objects are not GC-tracked, so there's no GC pressure.
6. **Absent `fineOffsets`** on a multi-byte channel means the fine bytes come right after the coarse byte (`offset+1`, `offset+2`).
7. **`defaultDmx` is in the channel's full resolution** (Appendix A: pan `32768` for 2 bytes). It is split big-endian into coarse/fine/ultra bytes with the §13.1 formula.
8. **Overlapping patches** are a warning (§5.6). In the base image, the later fixture in list order wins.
9. **`elementPatch`** is valid show data, but the compiler rejects it with a clear "unsupported in Phase 0" error, because the spec doesn't define channel-offset semantics for split patches (see §8).
10. **`zoom`'s default "profile midpoint"** isn't an `AttributeValue`. The registry types it as `default: AttributeValue | Literal["profileMidpoint"]`, and Phase 1's slot compiler resolves it from `physical.zoomRange`.
11. **The demo show lights its fixture through `defaultDmx`.** From Phase 1 on, slot-driven channels ignore `defaultDmx`, so this demo will go dark *by design* and needs replacing then (§9).

---

## 3. Project layout (Phase 0 subset of §21)

```
pyproject.toml                 # uv; [project.scripts] busk = "busk.cli:main"; ruff, mypy --strict, pytest config
src/busk/
  __init__.py  __main__.py     # python -m busk
  cli.py                       # validate / run
  model/
    common.py                  # NewType ids, EntityBase, TargetRef/TargetKey, STRICT config, constrained aliases
    attributes.py              # §5.3 registry + §5.4 ColorValue/DiscreteValue/AttributeValue
    profile.py fixture.py group.py preset.py cue.py playback.py
    effect.py master.py surface.py output.py show.py   # §5.5–§5.17 (Show, ParkEntry, ShowMeta in show.py)
    validate.py                # Issue, validate_show(): structural + semantic
  commands/types.py            # §15.2 command TypedDicts + Command union
  persistence/show_file.py     # load_show(path)
  compiler/compile.py          # CompiledUniverse, CompiledShow, compile_show()
  convert/dmx.py               # split_raw(raw, nbytes) — §13.1 byte split, reused in Phase 1
  engine/clock.py              # Clock protocol, MonotonicClock, FakeClock
  engine/loop.py               # Frame, EngineStats, Engine (tick + run)
  output/console.py            # ConsoleOutput thread
examples/phase0-demo.json
tests/fixtures/appendix_a.json # verbatim copy of spec Appendix A
tests/test_attributes.py test_schema.py test_validate.py test_compile.py
      test_clock.py test_engine.py test_console_output.py test_cli.py
```

---

## 4. Component design

### 4.1 Attribute registry (`model/attributes.py`)
- `AttributeDefinition` is the §5.3 dataclass (`kw_only=True`). `ATTRIBUTES: Mapping[AttributeId, AttributeDefinition]` holds exactly the 20 attributes in the §5.3 table, with family, kind, unit, merge, fade and default as tabled.
- Normalised scalars (`intensity`, `positionSpeed`, `cto`, `iris`, `frost`, `focus`) get `range=ScalarRange(0, 1)`. Degree, Hz and deg/s scalars have no registry range, because their range depends on the profile.
- Discrete attributes always `fade="snap"`, `snapAt="start"`. Discrete defaults are written `{"slot": "open"}` / `{"slot": "off"}` / `{"slot": "none"}`.
- The registry is static and tied to `SCHEMA_VERSION = 1`.

### 4.2 Show schema (`model/*.py`, `commands/types.py`)
- A literal transcription of §5.1–§5.17 and the §15.2 command types, with the changes from decision 3 (with_config, discriminators, `Annotated` ranges).
- Model modules must import referenced names at module level (no `TYPE_CHECKING` guards), so pydantic can resolve the string annotations created by `from __future__ import annotations`.
- `SHOW_ADAPTER = TypeAdapter(Show)` is built once.

**Compatibility risk** (checked first in step 2): pydantic on 3.14 has to handle the spec's notation, namely:
- the generic `EntityBase(TypedDict, Generic[TId])` base,
- PEP 695 aliases wrapping `Annotated` discriminated unions,
- functional TypedDicts (`SpreadSource` with its `from` key),
- the `"Command"` string forward reference.

*Fallback:* drop the generic base. Each entity then declares `id: XxxId` and `name: str` itself and inherits `notes` / `tags` from a non-generic `EntityMeta`.

### 4.3 Validation (`model/validate.py`)
- `Issue(severity: "error" | "warning", path: str, message: str)`. Paths read like `fixtures[2].patch.address`.
- `validate_show(text) -> tuple[Show | None, list[Issue]]` runs in this order:
  1. JSON parse. A `JSONDecodeError` becomes an issue that carries the line and column.
  2. Peek at `schemaVersion` and require it to be 1, before any structural check (a future-version show would otherwise produce confusing structural errors).
  3. Structural validation (`SHOW_ADAPTER.validate_json`). Pydantic `loc` tuples are converted to paths.
  4. If the structure is valid, run the semantic pass. **It collects every issue rather than failing fast.**

Semantic rules (all of them errors unless marked as a warning):

| Area | Rule |
|---|---|
| Identity | `id`s unique per top-level collection; nested ids (modes, wheels, wheel slots, cues, effect instances) unique within their parent |
| Numbers | user numbers unique: universes, fixtures, groups, cue lists, playbacks, pages; presets unique per `pool` |
| References | every id reference resolves to the right collection: `profileId`, `modeId` (∈ that profile), `universeId` (patch, elementPatch, routes), `groupId`, `presetId` (sources, `PresetRef` in palettes), `templateId`, `cueListId`, page `slots`, `surfaceId`, playback/master ids in binding actions and in embedded commands |
| Master kinds | `BpmRate.masterId` / `speedMasterId` / `TapAction` → speed master; `sizeMasterId` → size master |
| Targets | every `TargetRef` and `PerTargetSource` key (`"fixtureId:element"`) names an existing fixture with `element < len(mode.elements)` |
| Revisions | **warning**: `fixture.profileRevision ≠ profile.revision` (§17: reported, never applied) |
| Attributes | every attribute id is in the registry. Value shape matches kind (scalar → number, color → `ColorValue`, discrete → `DiscreteValue`) in literals, per-target maps, presets and park. `spread` is only allowed on scalar or colour. `ScalarLayer` is only allowed on scalar attributes. `control` never appears in presets, cue entries, releases or effects (§5.5) |
| Profiles | element indices are exactly `0..n−1`. Each channel's element is valid; its offset and fine offsets are inside the footprint; no two channels share an offset in a mode; `len(fineOffsets) == bytes−1`. `defaultDmx`, `highlightDmx` and capability `dmx` fit in `0..256^bytes−1`. Capabilities are ascending and non-overlapping. Colour channels have `component` and others don't. `(element, attribute, component)` is unique. Slot capabilities name an existing wheel and slot |
| Patch | error when `address + footprint − 1 > 512`. **Warning**: overlapping footprints in one universe |
| Cues | `number` matches `^\d+(\.\d+)?$` and is unique and strictly ascending within the list, compared as an int tuple. `mode: "chase"` requires `chase` settings |
| Groups | `layout.cells` length is `width × height`; cell indices are below `len(members)` |
| Output | `sacnCid` parses as a UUID; `sacnSourceName` is at most 63 UTF-8 bytes |

### 4.4 Loader (`persistence/show_file.py`)
`load_show(path) -> tuple[Show, list[Issue]]` returns the warnings alongside the show. It raises `ShowLoadError(issues)` if there is any error and `FileNotFoundError` as usual. A future migration chain plugs in between the version check and structural validation.

### 4.5 Compiler (`compiler/compile.py`, `convert/dmx.py`)
```python
@dataclass(frozen=True, kw_only=True)
class CompiledUniverse:
    id: UniverseId
    number: int
    name: str

@dataclass(frozen=True, kw_only=True)
class CompiledShow:
    engineHz: float
    universes: tuple[CompiledUniverse, ...]   # sorted by number; index = row of baseImages
    baseImages: NDArray[np.uint8]             # shape (len(universes), 512)
```
- `compile_show(show)` loops over each patched fixture and each channel of its mode, splits `defaultDmx` with `split_raw(raw, bytes)`, and writes the coarse byte at `address−1+offset` and the fine bytes at their fine offsets.
- Unpatched fixtures contribute nothing. Universes with no fixtures produce all-zero rows.
- `elementPatch` raises `UnsupportedFeature`.
- `split_raw` is the §13.1 split: `coarse = raw >> 8·(n−1) & 0xFF`, …

### 4.6 Clock (`engine/clock.py`)
- `Clock` is a Protocol with `now() -> float` and `sleep_until(t) -> None`.
- `MonotonicClock` uses `time.monotonic()` / `time.sleep`.
- `FakeClock(start=0.0)` has `now`, `advance(dt)`, and `sleep_until(t)`, which jumps to `max(now, t)`. It is deterministic and never sleeps.

### 4.7 Engine (`engine/loop.py`)
- `Frame(seq, time, universes: tuple[bytes, ...])`, frozen.
- `EngineStats(ticks, overruns, maxTickSeconds)`.
- `Engine(compiled, clock)` exposes:
  - `latest: Frame | None`
  - `stats`
  - `tick(now)`: Phase 0 implements only §4.2 stages 12–13. It does `np.copyto(back, compiled.baseImages)` and publishes `Frame`; a comment marks where later stages go.
  - `run(stop: threading.Event)`: the §11.2 loop. It sets `next += 1/engineHz`, and if `next < clock.now()` it counts an overrun and sets `next = clock.now()` (drop, don't spiral), then calls `sleep_until(next)`. It records the maximum tick duration.
- The engine does no I/O, logging or allocation besides the published `bytes`/`Frame` (§19).

### 4.8 Console output (`output/console.py`)
- `ConsoleOutput(engine, universes, clock, stream=sys.stdout)` runs on its own thread at `POLL_HZ = 44`, which mirrors the DMX refresh ceiling.
- Each poll takes `engine.latest`, compares each universe's bytes with the last bytes printed, and prints only universes that changed. A static show therefore prints once.
- Output stays on this thread and never on the engine thread. If the engine stalls, the last frame is held automatically.
- Line format, pinned by tests:
  `[frame 1] U1 Stage: 101=255 102=255`. Non-zero channels are listed 1-based. An all-zero universe prints `all 0`.
- When network drivers arrive, this poll / change-detect loop becomes the §14 scheduler. No driver protocol is introduced before then.

### 4.9 CLI (`cli.py`, argparse)
- `busk validate SHOW` prints one line per issue (`error  fixtures[2].patch.address: …`) and a summary. Exit code 0 means no errors; 1 means errors.
- `busk run SHOW [--duration S]`:
  1. Load the show. Print warnings; on errors, print them and exit 1.
  2. Compile.
  3. Print `Phase 0: console output only — N output route(s) in the show are ignored`.
  4. Start the engine and console threads.
  5. Wait for Ctrl+C or `--duration`, set `stop`, and join both threads.
  6. Print `engine: <ticks> ticks @ <Hz> Hz, <overruns> overruns, max tick <ms> ms`.

  `--duration` makes the command scriptable and testable.

---

## 5. Implementation steps

Each step follows TDD: write the listed tests first, then make them pass.

1. **Scaffold.** Run `uv init --package` (package `busk`, src layout). Then `uv add numpy pydantic` and `uv add --dev pytest ruff mypy`. Configure ruff, `mypy --strict` on `src/`, and pytest. → *verify:* `uv run pytest` (no tests yet) runs; `uv run ruff check` and `uv run mypy src` are clean.
2. **Pydantic compatibility spike** (§4.2 risk): put a throwaway module in the scratchpad that uses each notation feature. → *verify:* each feature validates and rejects as expected on 3.14. If not, apply the fallback before step 4.
3. **`model/common.py` + `model/attributes.py`.** → *verify:* `test_attributes.py` passes. It checks that:
   - the registry holds exactly the 20 ids from §5.3,
   - only `intensity` is HTP,
   - every discrete attribute snaps,
   - each default's shape matches the attribute's kind (zoom is the exception).
4. **Full schema + `commands/types.py`.** Copy Appendix A verbatim into `tests/fixtures/appendix_a.json`. → *verify:* `test_schema.py` passes:
   - Appendix A validates structurally.
   - These are all rejected with the correct path: unknown keys at depths 1, 3 and 5, a bad discriminator, a string where a float is expected, an int `cue.number`, a missing required key, `NaN`, and an address of 0 or 513.
   - A test walks every TypedDict in `busk.model` and `busk.commands` and asserts that each has `extra="forbid"`.
5. **Semantic validation.** → *verify:* `test_validate.py` is table-driven. Each case mutates Appendix A at one point and asserts the exact `(severity, path)` produced; there is at least one case per row of the §4.3 table. A multi-error mutation reports every error. Unmodified Appendix A produces **0 errors and 0 warnings**.
6. **Loader + `busk validate`.** → *verify:* `test_cli.py` checks that Appendix A exits 0, and that a broken copy exits 1 with the error path in the output.
7. **Compiler + `split_raw`.** → *verify:* `test_compile.py` passes:
   - Appendix A gives one universe whose base image is exactly `ch1=128, ch3=128, ch11=128, ch17=128, ch19=128, ch27=128`, with all other channels 0. (Pan/tilt `32768` → coarse 128 / fine 0; zoom `128`; MH2 at address 17; the par is all zeros.)
   - A non-adjacent `fineOffsets` channel and a 3-byte channel split correctly.
   - Universes are ordered by number; unpatched fixtures are skipped; on overlap the later fixture wins.
   - `elementPatch` raises `UnsupportedFeature`.
8. **Clock.** → *verify:* `test_clock.py` checks that `FakeClock` is deterministic and that `sleep_until` never goes backwards. It also checks that `MonotonicClock` never decreases and that `sleep_until` returns at or after the target.
9. **Engine.** → *verify:* `test_engine.py`, using a `FakeClock`, checks that:
   - `tick` publishes frames whose `seq` increments and whose bytes equal the base image;
   - `run` with stop set after N ticks produces tick times of exactly `k/engineHz` (no drift);
   - a simulated 35 ms tick at 100 Hz gives `overruns == 1`, the next tick at the stall's end, and no catch-up burst (no two ticks closer than 10 ms);
   - two runs produce identical frame sequences (determinism, §2.7).
10. **Console output.** → *verify:* `test_console_output.py`, driving `service(now)` directly with a `StringIO`, checks that a static frame prints exactly once, that a changed universe prints again, and that the golden line format holds, including `all 0`.
11. **`busk run` + demo show.** Write `examples/phase0-demo.json`, a minimal valid show:
    - universe `u1` "Stage";
    - one hand-written "Phase 0 Demo Par" profile, mode 4ch: intensity `defaultDmx 255`, then colour red/green/blue at `255/0/0`;
    - fixture 1 patched at u1/101;
    - one sACN route, which is ignored.

    → *verify:* `test_cli.py` runs `busk run examples/phase0-demo.json --duration 0.3`. It expects exit 0, stdout containing `U1 Stage: 101=255 102=255` exactly once, a "route(s) ignored" notice, and a stats line with more than 0 ticks.
12. **Full verification pass** (§7).

---

## 6. Acceptance tests (summary)

| Test file | Proves |
|---|---|
| `test_attributes.py` | Registry matches §5.3 |
| `test_schema.py` | Appendix A validates; strictness (extra keys, types, ranges, NaN) is enforced everywhere |
| `test_validate.py` | Every semantic rule fires with the right path and severity; all issues are collected |
| `test_compile.py` | Golden base-image bytes for Appendix A; byte splitting; patch edge cases |
| `test_clock.py` | Fake and real clock contracts |
| `test_engine.py` | Fixed-rate ticking, drop-don't-spiral, overrun counting, determinism |
| `test_console_output.py` | Print-on-change and the golden line format |
| `test_cli.py` | `validate` exit codes; `run` end to end on real threads and a real clock |

---

## 7. Verification

```bash
uv run pytest                                     # all green
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run busk validate tests/fixtures/appendix_a.json   # → 0 errors, 0 warnings
uv run busk run examples/phase0-demo.json         # prints "[frame 1] U1 Stage: 101=255 102=255" once;
                                                  # Ctrl+C → stats line, 0 overruns, max tick ≪ 10 ms
uv run busk run tests/fixtures/appendix_a.json --duration 2
                                                  # → "U1 Stage: 1=128 3=128 11=128 17=128 19=128 27=128"
```

---

## 8. Spec gaps found while planning (resolve in Phase 1+)

- **`elementPatch` offset semantics are undefined.** Is a split element's channel offset relative to the element's own address or to the mode start? This must be decided before pixel bars.
- **`AttributeDefinition.default` for `zoom`** ("profile midpoint") isn't an `AttributeValue`. Phase 0 uses a `"profileMidpoint"` sentinel.
- **Id uniqueness scope** (per collection or global) isn't stated. Phase 0 enforces per collection.
- **Cue-number grammar** is only shown by example. Phase 0 accepts `\d+(\.\d+)?` and compares as an int tuple, so `"1.10"` comes after `"1.9"`. The spec should say so explicitly.
- **§14.5 `OutputDriver.protocol`** has no debug/console variant. When network output lands, decide whether the console printer becomes a driver or stays a CLI tool.
- **Shutter default `defaultDmx: 0` in Appendix A means "closed"**, so Appendix A is dark until Phase 1's shutter guard (§13.2) exists. This is expected, and it shows why that guard matters.

## 9. What Phase 1 changes in this skeleton

- `CompiledShow` gains the slot table (§6.1).
- `Engine.tick` gains the logical frame → conversion step, which writes slot-driven channels over the copied base image.
- `split_raw` is reused by §13.1.
- `examples/phase0-demo.json` goes dark once intensity and colour become slot-driven (default 0). It gets replaced by a conversion-level demo.
- The open questions in §8 must be resolved.
