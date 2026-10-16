# Phase 3 — Programmer & recording: implementation plan

> Source spec: `busking-console-architecture-python.md` (§22, Phase 3). Builds on `phase-0-plan.md`. Phases 1 and 2 have no written plan yet; §2 lists what this plan assumes they deliver.

> **Step 1 — Phase 1–2 seam mapping** (done before implementation):
>
> | §2 seam | Actual code |
> |---|---|
> | Profile library | Did not exist: Phase 1's profiles lived inside the example shows. Added as package data, `src/busk/library/profiles/*.json` (Appendix A's Generic Spot 16ch and RGB Par 3ch; Phase 1's Stairville MH-X25, Eurolite ML-56 RGBW, Chauvet COLORband PiX), loaded by `busk.session.library.ProfileLibrary` |
> | Slot table | `CompiledShow.slots: SlotTable` with `slots`, `byKey[(TargetKey, AttributeId)]`, `find(target, attribute)`; options in `Slot.options` / `Slot.wheels`. Added `SlotTable.laneSlot` (lane → slot) for the programmer's per-slot sequence numbers |
> | Value resolution | `CueCompiler(show, slots).resolve(source, slot, k, n)` and `.preset_value(preset, slot)`; `_clamp` made public as `clamp_lanes`; added `spread_value`. The session keeps one resolver per committed show (`busk.session.state.ShowState.values`) instead of a free `resolve_source` |
> | Compiled cues | `CompiledShow.cueLists[id]: tuple[CompiledCue, …]`; `CompiledPlayback.cue` is the first cue |
> | Engine | `Engine.bus` (`CommandBus`, a FIFO drained at stage 1); `Playbacks` holds the runtimes and the global `seqCounter`; sources are composited by `(priority, seq)`; presence `Envelope`s; grand master and blackout as assumed |
> | Snapshot | `EngineSnapshot` existed; added `masterLevels` (per grand master) for autosave |
> | Output / input | `OutputScheduler` polls `engine.latest`; `BindingResolver` maps bindings on the first page. Added `Frame.compiled` and `CompiledShow.output` / `surfaces` / `bindings` for reconciliation |
> | Commands | §15.2 types in `commands/types.py`; Phase 2's `CommandBus` validated at submit time and rejected non-performance types with "not supported until Phase 3" |

## Context

Phase 2 ends with a console that can busk a show (the §7.8 golden test passes, MIDI faders work), but every show is still hand-written JSON. Phase 3 adds the editing half of the architecture: the operator builds and changes the show from the console itself, live, while output keeps running.

The spec scopes Phase 3 as *"Selection, set attribute, apply preset, record cue/preset with filters, undo, autosave"*. It is done when the operator can *"build a show from scratch without editing JSON"*. The Phase 0 plan also deferred two items to this phase: the `.show` ZIP container with atomic save, backups and autosave (§17), and incremental recompile with live swap (§6.4).

Three things make this phase harder than its one-line scope suggests:

1. **Recording must keep intent.** Programmer values have to become cue and preset data that still holds group and preset references (§5.9 busking recommendation, §5.14). This is the largest piece of logic in the phase.
2. **Edits happen while the show is live.** Each edit recompiles the show and swaps it into the running engine. Validation, compilation and saving run on other threads, but in CPython they hold the GIL, so they must not cause engine tick overruns.
3. **There is no UI yet.** The GUI and web remote arrive in Phase 6, but Phase 3 still needs an operator interface to meet its done criterion.

**Done when:**

- Starting from `busk new`, the script `examples/phase3-build.busk` builds a complete busking show using console commands only, with no JSON. The show has a universe, the Phase 1 fixture types, groups, scoped colour and position presets, looks and bumps on page slots, exclusivity, an sACN route and MIDI bindings. The script saves it as a `.show` file. `busk run` on that file busks it with MIDI faders, exactly like the Phase 2 hand-written demo.
- `test_build_from_scratch.py` reproduces that build deterministically. It checks:
  - the saved show matches a golden JSON file, and the DMX frames match golden bytes;
  - a live preset edit reaches output through references;
  - undoing every step returns the show to the `busk new` template, and redoing every step returns it to the final show;
  - save → load round-trips.
- If `busk run` is killed with SIGKILL mid-session, restarting it recovers the programmer and the unsaved show edits.
- All acceptance tests in this plan pass.

---

## 1. Scope

| In Phase 3 | Deferred (to) |
|---|---|
| Programmer: ordered selection (replace / add / remove), `SET_ATTRIBUTE` (literal, spread, per-target, preset), `APPLY_PRESET`, `CLEAR_PROGRAMMER`, `BLIND` (excluded from live output), the playback `select` button | Programmer `fadeTime` (Phase 4). Programmer effects and `ADD_EFFECT` (Phase 5). The blind *preview* resolve (Phase 6, because it needs a UI). `HIGHLIGHT` (Phase 7, with the rest of the §12 safety stage) |
| `RECORD_CUE` with family filter and create / merge / replace / remove; group and preset references kept | Tracking-aware recording, i.e. storing only what changed (Phase 4). Recording effects (Phase 5) |
| `RECORD_PRESET` with pool filter, scope cascade and merge modes; `RECORD_GROUP` | Group reorder tools (by number, stage x, mirror) |
| Show editing: generic `ADD` / `SET` / `DELETE`, `PATCH_FIXTURE`, `ASSIGN_PLAYBACK`, `BATCH`; profiles embedded from the Phase 1 library | Cascading deletes. Profile revision updates and GDTF/OFL import (Phase 7) |
| Undo / redo on one timeline shared by programmer changes and show edits | Persisted undo history. Pushing patches to remote UIs (Phase 6) |
| Live swap of each recompiled show into the running engine (§6.4), with slot remapping | Fading running values to their new targets instead of snapping (Phase 4) |
| Full recompile on every edit; identity-memoised recompile only if the benchmark requires it (§5.11) | Compiler worker thread that coalesces edits |
| `.show` ZIP, atomic save, rolling backups, show autosave, session autosave, crash recovery | Assets inside the ZIP (Phase 7, with GDTF). Watchdog restart (Phase 7). Migrations (with the first breaking schema change) |
| Operator console: line commands inside `busk run`, plus script files | GUI, web remote, MIDI learn (Phase 6) |
| — | Event log and replay (§15.5). Envelopes are already JSON, so the log is an append-only file when needed |

---

## 2. Baseline assumed from Phases 1–2

This plan touches Phases 1 and 2 only through the seams below. Step 1 maps each one to the real code and corrects the names in this plan.

| Seam | Assumed shape |
|---|---|
| Profile library | Phase 1's hand-written profiles are kept in a directory with one `FixtureProfile` JSON file each (`library/profiles/`) |
| Slot table | `CompiledShow.slots` plus a lookup `(TargetKey, AttributeId) → SlotIndex`. Each slot knows its lanes, its kind and its compiled discrete options |
| Value resolution | The §6.3 step-2 helper the compiler uses for cue entries, `resolve_source(compiled, show, target, attribute, source) -> lanes \| None`. It handles preset scope lookup, spread by member index and per-target maps |
| Compiled cues | Each cue compiles to slot indices plus lanes. Running playbacks reference these |
| Engine | Command queue drained at stage 1. Sources emit contributions to the §7 resolver, ordered by `(priority, seq)`. Global `seqCounter`. Grand master and blackout. Linear presence fades on activation and release (§7.8 depends on them) |
| Snapshot | The engine publishes a throttled snapshot with playback states and master levels. If it doesn't, step 1 adds it |
| Output / input | A network output thread polls frames. A MIDI input thread maps the show's `bindings` (on page 1) to commands |
| Commands | Phase 0 defined the §15.2 command types; Phase 2 implemented the performance class |

---

## 3. Decisions and assumptions

1. **The operator interface is a line console inside `busk run`.** It takes commands such as `sel group 1`, `preset color 1` or `record slot 3 "Blue"`, and it can also run script files. It is the smallest interface that meets the done criterion, and it can be tested as text in, commands out. It is also a thin client: everything goes through `Session.submit(Command)`, which is the API the Phase 6 WebSocket server will expose. The GUI and web remote stay in Phase 6.
2. **The Session is the command bus (§15) and the only writer of editing state.** Editing state means the show store, the programmer and the undo timeline. The engine receives immutable `Install` items (a compiled show, a programmer frame, or both) through its existing queue.
   - This deviates from §5.18, which puts the programmer in `EngineRuntime`. Recording needs the programmer and the show together, and validation results must come back synchronously. With the programmer inside the engine, every programmer command would need a reply channel, and every RECORD would wait a tick for a snapshot.
   - Real-time state stays in the engine: playbacks, fades, sequence numbers, masters.
3. **Performance never waits on editing.**
   - Performance commands go straight to the engine queue and never take the session lock.
   - Input threads can also send non-performance commands, such as the `select` button or a bound `UNDO`. Those go through a single session worker thread, so a MIDI thread never blocks behind a long edit.
4. **Store invariant: the session only ever holds a show that validates and compiles.** Each edit builds a candidate show, validates it (§5.3) and compiles it, and only then commits and installs it. Any error rejects the whole edit, and nothing changes anywhere. As a result, save → load cannot fail on content the console produced.
5. **Few semantic commands; generic edits for everything else.**
   - Recording and patching need real logic, so they get their own commands.
   - Everything else is `ADD` / `SET` / `DELETE` on id-addressed paths, checked by the validator. That covers universes, routes, playback settings, renames, deletes and bindings.
   - `BATCH` makes multi-entity operations atomic and a single undo step. For example, a new playback means a cue list, a cue, a playback and a page slot.
   - Callers generate ids, so later commands in a batch can refer to entities that earlier ones create.
6. **Undo uses JSON patches with structural sharing (§15.4), on one timeline.**
   - Edits are applied as add / remove / replace ops on a copy-on-write tree, and the inverse ops are captured during application.
   - Unchanged subtrees keep their identity, which makes edits cheap and enables memoised compile (§5.11).
   - Programmer changes go on the same timeline, so one `undo` ("oops") undoes the operator's last action, whether it was a selection, a value or a record.
   - Blind on/off is a mode, not content, and is never undone: undoing it could put programming live on stage.
7. **Programmer values are stored per slot, and only as `literal` or `preset`.** Preset references stay references (§5.14). Spread and per-target sources are evaluated for each target when they are set. As a consequence, a recorded fan becomes a `perTarget` entry (see §9).
8. **Live changes snap in Phase 3.** Programmer changes and live swaps of recompiled shows take effect at the next tick, without a fade. Value fades, the programmer's `fadeTime` and §6.4's "re-target, don't jump" behaviour arrive with the Phase 4 fade engine.
9. **Recording prefers references.** Cue entries reference a group whenever one fits (the group cover in §5.5), and they keep preset references. `freeze` forces explicit targets instead (§23 recommendation).
10. **Record commands create by default.** `merge` is optional, and leaving it out means "create; error if it already exists". A typo therefore can't overwrite an existing cue or preset.
11. **Multi-cue lists can be recorded, but only cue 1 plays until Phase 4.** `record cue 10/2` works, and the console warns that GO arrives in Phase 4.
12. **Ids and wall-clock time are injected.**
    - Ids take the form `<prefix>-<12 hex chars>` (e.g. `fx-3f9a0c71b2de`) and come from an injectable factory; tests use a counter.
    - Wall-clock time (meta timestamps, autosave file names) is injected the same way.
13. **The schema version stays at 1.** Every schema change in this phase is additive (new command types reachable through `CommandAction`, new optional fields), so old shows still load and no migration is needed.
14. **Dependencies.** No new runtime dependencies. Add `hypothesis` as a dev dependency for property tests, unless Phase 2 already added it.

---

## 4. Project layout (new and changed files)

```
src/busk/
  commands/
    types.py          # + Phase 3 command TypedDicts, EditPath, IdSegment (changed)
    classes.py        # command type → performance | programmer | show | session
    patch.py          # EditPath → pointer, copy-on-write apply, inverse ops (§15.4)
    edits.py          # ADD / SET / DELETE / PATCH_FIXTURE / ASSIGN_PLAYBACK / BATCH → ops
    record.py         # RECORD_GROUP / RECORD_PRESET / RECORD_CUE → ops
  session/
    session.py        # Session (command bus, single writer), CommandResult, session worker
    timeline.py       # unified undo / redo
    programmer.py     # Programmer value object + programmer command handlers
    frame.py          # builds ProgrammerFrame and the slot remap
    library.py        # ProfileLibrary
    ids.py            # IdFactory (random / counter)
  model/validate.py   # + validate_edit (changed)
  compiler/           # + identity memoisation — only if step 13 requires it
  engine/
    install.py        # Install, ProgrammerFrame; applying them at stage 1 (remap, re-point playbacks)
    loop.py           # stage 1 handles Install; stage 6 gathers the programmer source (changed)
  output/             # route reconciliation; universe rows matched by UniverseId (changed)
  io/                 # bindings read from the latest compiled show (changed; Phase 2's input module)
  persistence/
    show_file.py      # .show ZIP + .json, atomic_write, backups, template show (changed)
    autosave.py       # AutosaveWorker, session.json, recovery decision
    paths.py          # state directory, installation CID
  console/
    parser.py         # line → Action (pure)
    console.py        # Console.execute, interactive loop, scripts
  cli.py              # + `busk new`; new `busk run` flags (changed)
examples/phase3-build.busk
bench/edit_latency.py
tests/golden/phase3_built_show.json  tests/golden/phase3_frames.json
tests/…               # see §7
```

The engine never imports `session/`: `Install` and `ProgrammerFrame` are engine types, and the session builds them.

---

## 5. Component design

### 5.1 Commands (`commands/types.py`, `commands/classes.py`)

| Command | Fields | Class | Notes |
|---|---|---|---|
| `SELECT` | `targets: TargetSpec`, `mode` | programmer | spec |
| `SELECT_PLAYBACK` | `playbackId`, `mode` | programmer | new; issued by the `select` button |
| `SET_ATTRIBUTE` | `attribute`, `value: ValueSource` | programmer | spec |
| `APPLY_PRESET` | `presetId` | programmer | spec |
| `CLEAR_PROGRAMMER` | — | programmer | spec |
| `BLIND` | `on: bool` | programmer | spec lists it; fields defined here |
| `RECORD_CUE` | spec fields, `merge` now optional, plus `name?`, `freeze?` | show | |
| `RECORD_PRESET` | spec fields plus `merge?`, `name?` | show | |
| `RECORD_GROUP` | `number`, `merge?`, `name?` | show | new; replaces the spec's `EDIT_GROUP` |
| `PATCH_FIXTURE` | spec | show | |
| `ASSIGN_PLAYBACK` | `pageId`, `slot` (0-based), `playbackId \| None` | show | spec name; fields defined here; extends `slots` with `None` as needed |
| `ADD` | `path: EditPath`, `value: JsonValue` | show | append to the id'd list at `path` |
| `SET` | `path`, `value` | show | set an object key (creates an optional key) |
| `DELETE` | `path` | show | remove an id'd list element or an optional key |
| `BATCH` | `label`, `commands: list[…]` | show | show-edit commands only, no nesting; atomic; one undo step |
| `UNDO`, `REDO` | — | session | |

- `merge` is one of `"replace" | "merge" | "remove"`. When it's absent the command means "create", and it fails if the target already exists.
- `classes.py` maps every member of the `Command` union to exactly one class. The session routes commands by class. Performance commands are the Phase 2 set.
- Commands built by the console and commands stored in show bindings are already well-formed. Phase 6 validates commands where they enter from remote clients.

### 5.2 Edit paths and JSON patches (`commands/patch.py`)

- An `EditPath` is a `list[str | IdSegment]`, where `IdSegment = {"id": str}`.
  - A string segment is an object key.
  - An `IdSegment` selects the list element with that `id`.
  - Example: `["cueLists", {"id": "cl-song"}, "cues", {"id": "c-verse"}, "timing", "fadeIn"]`.
- Lists without ids (`members`, `buttons`, `slots`, preset `values`, cue `entries`) can only be replaced whole, with `SET`.
- Some paths are protected and rejected with an error:
  - any path ending at an `id` key;
  - `schemaVersion`;
  - `meta.id`;
  - `meta.created`.
- Resolution turns an `EditPath` into a pointer of keys and list indices against the current show. Ops are `add | remove | replace` with a pointer and a value.
- `apply(show, ops) -> (new_show, inverse_ops)`:
  - It shallow-copies only the containers on each op's path. Every untouched subtree of the new show **is** the corresponding old object.
  - It deep-copies inserted values, so a caller can't mutate the store afterwards.
  - It captures each inverse from the old value while applying (add ↔ remove, replace ↔ replace with the old value), and returns the inverses in reverse order.
- The show is never mutated in place. Undo applies the inverse ops to exactly the show the forward ops produced, which a linear timeline guarantees.

### 5.3 Validating edits (`model/validate.py`)

`validate_edit(show, touched) -> list[Issue]`. Here `touched` is the set of top-level entities named by the ops' pointers, for example `("presets", 3)` or `("output",)`.

1. **Structural.** Each touched entity is validated on its own with its TypedDict adapter, through `json.dumps` → `validate_json(strict=True)`.
   - This is the same path `load_show` uses, so tuples written as lists and every strictness rule behave identically.
   - Issue paths carry the entity's position, e.g. `presets[3].values[0].value`.
2. **Semantic.** The full Phase 0 semantic pass runs over the whole show. It is pure Python.
3. **Compile.** The session then compiles the candidate. Compiler errors (e.g. `UnsupportedFeature`) become issues and reject the edit.

Why not run the full `validate_show` on every edit? One pydantic call over a large show holds the GIL for its whole duration and can stall the engine tick; per-entity calls are short. A property test checks that `validate_edit` and the full `validate_show(json.dumps(show))` report the same errors on random edit sequences.

### 5.4 Programmer (`session/programmer.py`)

```python
type SlotKey = str                                # f"{TargetKey}/{AttributeId}" (§5.14)
type ProgSource = LiteralSource | PresetSource

@dataclass(frozen=True, kw_only=True)
class Programmer:
    selection: tuple[TargetRef, ...]              # ordered, no duplicates
    values: Mapping[SlotKey, ProgSource]          # copy-on-write: every command builds a new dict
    blind: bool
```

Each handler returns a new `Programmer` and a one-line message, or an error.

| Command | Behaviour |
|---|---|
| `SELECT` | Expands the `TargetSpec` (a group expands to its members, in order). `replace` sets the selection; `add` appends targets not already selected; `remove` drops targets. |
| `SELECT_PLAYBACK` | Selects the targets of the playback's first cue (Phase 4: its current cue), in entry order, de-duplicated. |
| `SET_ATTRIBUTE` | Applies to each selected target that has a slot for the attribute: |
| | • a `literal` is stored as given; |
| | • a `preset` is stored as a reference; |
| | • a `spread` is evaluated per target and stored as a literal, using the target's index and the count in the selection (the same rule the compiler uses for group spreads); |
| | • a `perTarget` source stores that target's own literal. |
| | Targets without the slot, or without the discrete option (e.g. a gobo slot their wheel lacks), are skipped and counted in the message. |
| | Errors: nothing selected; no target set; a normalised value outside 0..1; a colour component outside 0..1. |
| `APPLY_PRESET` | For each selected target, every attribute the preset defines for it (§5.8 lookup) becomes a preset reference. It is an error if the preset defines nothing for the selection. |
| `CLEAR_PROGRAMMER` | Empties the selection and the values. `blind` keeps its state. |
| `BLIND` | Sets `blind`. Values stay; the live output stops (or resumes) including them. |

- A value whose slot no longer exists, for example because its fixture was deleted, is kept but ignored by output and by recording. Undoing the delete makes it live again.
- Selecting fixture `N` from the console expands to all of its elements; `N.E` selects one element. A `TargetRef` always means exactly its own element.

### 5.5 Recording (`commands/record.py`)

All three record commands are pure functions `(show, compiled, programmer, cmd) -> ops | error`. They only read programmer values whose slot exists. If the programmer holds nothing that matches the filter, the command is an error.

**Families.** Each preset pool filters the families it records:

| Pool | Families |
|---|---|
| `intensity` | intensity |
| `position` | position |
| `color` | color |
| `beam` | beam, shutter |
| `focus` | focus |
| `all` | every family except `control` |

`RECORD_CUE.filter` lists families explicitly; when it's absent, every family except `control` is recorded.

**RECORD_GROUP.** Members are taken from the selection, in order.
- create: a new group, named `Group N` unless a name is given.
- replace: members become the selection.
- merge: selected targets that aren't already members are appended.
- remove: selected targets are removed.

If a `layout` would point at members that no longer exist, it is dropped, with a warning.

**RECORD_PRESET.**
1. Collect `(target, attribute) → value` for the pool's families. Preset references are resolved to literals for their target, because presets can't reference presets (§5.8).
2. Apply the scope cascade, starting from the requested scope:
   - `global`: if every target agrees on an attribute, write one global value for it; otherwise fall back to `profile` for that attribute.
   - `profile`: if every target of a profile agrees, write one value for that (profile, attribute); otherwise fall back to `target`.
   - The message reports any fallback, e.g. `pan: 4 target values (values differ)`.
3. Write the preset:
   - create: a new preset. Error if the `pool` / `number` pair already exists.
   - replace: the preset's values become the new values.
   - merge: new values replace entries with the same (scope key, attribute). Then any existing *narrower* entry that would shadow a new value for a programmer target is removed: target entries for those targets, and profile entries for their profiles when the new value is global. Narrower entries for fixtures not in the programmer stay.
   - remove: deletes every entry, of any scope, that a programmer target sees for a programmer attribute.
4. Entry order is deterministic: registry attribute order, then scope (global, profile, target), then profile id or fixture number and element.

**RECORD_CUE.**
1. Collect `(target, attribute) → source` for the filter's families.
2. For each attribute, in registry order, build buckets of targets: one bucket per preset id, plus one bucket for all literal-valued targets.
3. Unless `freeze` is set, run a **group cover** on each bucket:
   - A group is a candidate when its members *that have this attribute* are a non-empty subset of the bucket's remaining targets.
   - Repeatedly take the candidate that covers the most targets (ties: fewest members, then lowest number), and remove its targets from the bucket.
   - Whatever remains becomes one `targets` entry, in selection order.
4. Choose each entry's source:
   - preset buckets use `preset`;
   - literal buckets use `literal` if every target in the entry has the same value, and `perTarget` otherwise.
5. Write into cue `cueNumber`. When `cueNumber` is absent, use the next whole number after the last cue (`"3.5"` → `"4"`), or `"1"` for an empty list.
   - create: a new cue, error if it already exists. Defaults: name `Cue <n>`, every timing 0 s with `linear`, trigger `go`, `effects: []`.
   - replace: the entries become the new entries. The id, number, name (unless one is given), timing and trigger are kept.
   - merge and remove: each existing entry is first *restricted* to the targets the programmer doesn't cover for its attribute. Merge then appends the new entries; remove does not.
   - Restriction leaves an entry unchanged if none of its targets are covered, and drops it if all are. Otherwise the entry becomes a `targets` entry listing the uncovered targets:
     - `literal` and `preset` sources stay as they are;
     - `perTarget` sources are filtered to those targets;
     - `spread` sources are flattened to `perTarget`, using each target's index in the *original* expansion, so those targets keep their exact values.
6. The cue list must already exist. The console creates it in the same `BATCH` when needed.

Two worked cases make good test cases:

- **Recreating Appendix A's Blue cue.** Select `g-mh` and `g-par`, run `APPLY_PRESET pr-blue`, then record. The result is exactly the two entries `g-mh → preset Blue` and `g-par → preset Blue`.
- **Merging into that cue.** Program MH1 red and record with `merge`. The cue becomes `[mh2] → preset Blue`, `g-par → preset Blue`, `[mh1] → literal red`.

### 5.6 Session (`session/session.py`, `session/timeline.py`)

The Session is the §15 command bus and the single writer of the show.

```python
class Session:
    show: Show                            # valid, compiled, never mutated in place
    compiled: CompiledShow
    programmer: Programmer
    path: Path
    dirty: bool
    def submit(self, cmd: Command, origin: CommandOrigin | None = None) -> CommandResult: ...  # synchronous
    def post(self, cmd: Command, origin: CommandOrigin | None = None) -> None: ...  # input threads
    def save(self, path: Path | None = None) -> CommandResult: ...

@dataclass(frozen=True, kw_only=True)
class CommandResult:
    ok: bool
    message: str                          # "Recorded cue 10/1: 2 entries"
    issues: tuple[Issue, ...]             # errors when not ok, warnings when ok
```

How `submit` handles each class of command:

- **Performance.** The command goes onto the engine queue and `ok` is returned at once. No lock is taken.
- **Programmer.** Under the session lock:
  1. The handler returns a new `Programmer`.
  2. The session builds a frame from it (§5.7) and enqueues `Install(programmer=frame)`.
  3. It pushes `ProgrammerStep(before, after)` onto the timeline. Only `selection` and `values` are recorded, never `blind`. A no-op step is not pushed.
- **Show edit.** Under the session lock:
  1. The handler produces ops.
  2. `apply` turns them into a candidate show and its inverse ops.
  3. `validate_edit` runs, then the compile. Any error rejects the edit at this point.
  4. If the slot keys changed, the session builds a remap (§5.7). It rebuilds the programmer frame against the new compiled show, then enqueues `Install(compiled, remap, frame)`.
  5. It commits, pushes `ShowStep(ops, inverse, label)`, sets `dirty`, and notifies autosave.
- **`UNDO` / `REDO`.** These pop one stack and push onto the other.
  - A show step re-applies its inverse or forward ops through the same validate → compile → install path. A failure there is a bug: the tests assert it never happens, and in production it is reported as an error result.
  - A programmer step restores `before` or `after` (selection and values only). Selected targets that no longer exist are dropped.
- **`post`** sends performance commands straight to the engine queue. Every other command goes to a single worker thread, which calls `submit` in arrival order.

Timeline rules:
- Every new step clears the redo stack.
- The timeline holds at most 1000 steps.
- Loading a show clears it.

**Ordering.** Installs and Phase 2 commands share the engine's FIFO queue, and installs are enqueued while the lock is held. The engine therefore sees edits in commit order, and a programmer frame always arrives after the compiled show it was built against.

**Library.** `ProfileLibrary(dirs)` loads and validates every profile once, at startup. Profiles can be looked up by id, or by name ignoring case. If the show already embeds a profile at a different revision, the embedded copy is used and a warning is issued. It is never silently updated (§17).

### 5.7 Engine integration and live swap (`engine/install.py`, `session/frame.py`)

```python
@dataclass(frozen=True, kw_only=True)
class ProgrammerFrame:                    # built by the Session against one CompiledShow
    slots: NDArray[np.int32]              # slot indices that hold a programmer value, ascending
    lanes: NDArray[np.float64]            # their lanes, concatenated in slot order
    touched: NDArray[np.int32]            # slots whose source changed in this update
    blind: bool

@dataclass(frozen=True, kw_only=True)
class Install:
    compiled: CompiledShow | None         # None: programmer-only update
    remap: NDArray[np.int32] | None       # old slot index → new (−1 = gone); None: slot table unchanged
    programmer: ProgrammerFrame
```

**Building a frame (session side).**
- Each value whose slot exists is resolved with `resolve_source`.
- `touched` holds the keys whose *source* differs from the previous programmer. A preset that changed underneath a reference does not count as a touch.
- When blind is switched off, every slot counts as touched: leaving blind applies the programmer *now*.
- The remap is computed on the session thread, by `(TargetKey, AttributeId)`, and only when the slot keys differ.

**Applying an `Install` (engine, stage 1).**
1. If the `Install` carries a compiled show:
   - When there is a `remap`, every per-slot runtime array is remapped with one vectorised gather. That covers programmer seq numbers and any per-contribution fade state.
   - Each active playback is re-pointed at its cue in the new compiled show, found by `CueId`. A playback is dropped when its playback or its cue list is gone, or when the cue list is now empty.
   - Values snap to the new compiled values. Presence weights continue unchanged.
   - The next tick time is computed from the new `engineHz`.
2. The programmer frame is stored, and every `touched` slot gets `seq = ++seqCounter`. The whole update shares one seq number.

**Stage 6.** Unless the frame is blind, the programmer is one more source, at band 100 with weight 1 and `intensityScale` 1. Each slot uses the seq it was given in stage 1.
- Its band sits above the playbacks, so the §7.3 and §7.4 formulas let programmer intensity and LTP values override playbacks. That includes intensity values *lower* than the playbacks' (§7.6).
- Masters and blackout still apply after the resolve.

**Other threads.**
- `Frame` gains a reference to the `CompiledShow` it was made with. When that reference changes, the output thread reconciles its drivers:
  - routes are compared by id and value;
  - removed or changed routes are closed, and sACN routes send `Stream_Terminated` when closed;
  - new routes are opened.
- Universe rows are matched by `UniverseId`, never by position: adding universe 1 after universe 2 reorders the rows.
- The same change makes the MIDI input layer re-read bindings and surfaces, so new bindings work without a restart.
- Anything else that captured the universe list at startup reads it from the frame's compiled show instead.

### 5.8 Show files (`persistence/show_file.py`, `persistence/paths.py`)

- **Formats.** The format is chosen by file extension; any other extension is an error.
  - `.show` is a ZIP with one entry, `show.json`. It is deflated and stamped with a fixed date (1980-01-01), so equal shows produce byte-identical files.
  - `.json` is plain JSON, used for hand-written shows and tests.
  - Both formats are written with `indent=2`, with keys in schema order.
- **Atomic writes.** `atomic_write(path, data)` works in five steps:
  1. Write to `.<name>.tmp` in the same directory.
  2. Flush and `fsync` the file.
  3. `os.replace` it over the target.
  4. `fsync` the directory.
  5. On any error, delete the temp file. The original stays untouched.
- **Backups.** Before saving over an existing file, the old file is copied to `<stem>.backups/<stem>-<UTC timestamp>.<ext>` next to it. The newest 10 are kept.
- **Saving.** `save` sets `meta.modified` from the injected wall clock and clears `dirty`. Saving is not an undo step.
- **Loading.** `load_show` reads both formats. When loading fails, the CLI error names the newest backup (§18: "offer last backup").
- **`busk new PATH [--title T]`** writes the template show and exits.
  - `schemaVersion: 1`.
  - `meta`: a new id, the title, `created` and `modified` set to now, and `app` set to `busk <version>`.
  - Empty profiles, universes, fixtures, groups, presets, effects, cue lists, playbacks, surfaces, bindings and park.
  - One grand master, and one empty page named `Main`.
  - `output`: `engineHz: 100`, source name `Busk Console`, the installation CID, `holdLastFrameOnEngineStall: true`, and no routes.
- **Installation CID.** §5.16 says the sACN CID persists *per installation*, so `busk new` reads it from `<stateDir>/cid`. That file is created once, with `uuid4`. Shows don't each get a new CID (see §9).

### 5.9 Autosave and crash recovery (`persistence/autosave.py`)

The state directory comes from `--state-dir`. It defaults to `$XDG_STATE_HOME/busk`, or `~/.local/state/busk` when that variable isn't set. Each show gets its own folder, `<stateDir>/autosave/<meta.id>/`.

| File | Written | Content |
|---|---|---|
| `show-<UTC timestamp>.show` | Only while the show has unsaved edits. Written 5 s after the last show edit (the end of a burst), or every 180 s during a long burst. The newest 20 are kept | the show |
| `session.json` | At most once per second, when the programmer or the master levels have changed; also on a clean exit | `programmer` (selection, values, blind), `masterLevels` (from the engine snapshot), `showPath`, `showAutosave` (the newest autosave since the last save, or `null`), `cleanExit` |

- An `AutosaveWorker` thread calls `service(now)` every 0.5 s. This is the same testable pattern as the Phase 0 console printer.
- The worker serialises the session's current immutable objects. It never takes the session lock, so it never blocks edits.
- `save` sets `showAutosave` to `null`, because the saved file is now current.

On startup, `busk run SHOW` reads the show's `meta.id` and looks for `session.json`:

| `session.json` | Action |
|---|---|
| missing, or `cleanExit: true` | Normal start with an empty programmer |
| `cleanExit: false` | Crash recovery. Load `showAutosave` if it's set and newer than the show file, and mark the show dirty. Restore the programmer (including its blind state) and the master levels. Print what was recovered |
| any, with `--no-recover` | Normal start |

- A clean quit writes `cleanExit: true`. Unsaved edits at a clean quit stay in the newest autosave, and the quit message prints its path.
- A recovered programmer goes live exactly as it was before the crash. That reproduces the pre-crash output, which is what §18 asks for.

### 5.10 Operator console (`console/parser.py`, `console/console.py`)

- **Parsing.** `parse(line, show, library, ids) -> Action`, where `Action = Submit(Command) | Query(…) | Save(path) | Source(path) | Quit`. It is a pure function. It:
  - turns user-facing numbers into ids, using the current show;
  - picks the next free number when none is given;
  - fills in entity defaults;
  - wraps multi-entity operations in a `BATCH`.
- **Execution.** `Console.execute(line) -> str` runs one line and returns the text to print. The interactive loop adds `readline` history on top.
- **`busk run SHOW`** accepts these flags: `[--script FILE] [--no-console] [--iface IF] [--state-dir D] [--library D] [--no-recover] [--duration S]`.
  - On a TTY, the console prompt opens.
  - When stdin is not a TTY, commands are read from it line by line, and EOF quits.
  - `--script FILE` runs a file first and stops at the first error, exiting with code 1.
- **Live safety.** At the prompt, Ctrl+C clears the line instead of stopping output. `quit` or Ctrl+D asks whether to save when there are unsaved edits. The Phase 0 universe printer is switched off while the console is active.

Grammar. `N` is a user-facing number. `U.A` means universe.address. `<merge>` is `merge`, `replace` or `remove`. Quoted strings are names.

| Area | Syntax | Becomes |
|---|---|---|
| Selection | `sel <targets>`, `sel + <targets>`, `sel - <targets>`, `sel none` | `SELECT` with replace / add / remove; `none` replaces with `[]` |
| | `<targets>` is `<t>[, <t>…]`, where `<t>` is `fixture N[.E] [thru M]` or `group N` | fixture `N` means all its elements unless `.E` is given; `thru` keeps the direction |
| | `sel playback N` | `SELECT_PLAYBACK` |
| Values | `set <attribute> <value>` | `SET_ATTRIBUTE` with a literal |
| | `set <attribute> spread <from> <to> [center\|edges]` | spread |
| | `set <attribute> preset <pool> N` | preset source |
| | `preset <pool> N` | `APPLY_PRESET` |
| | `<value>` is a number, a percentage (`50%` = 0.5), a colour `r g b [w x] [a x] [uv x]`, or a discrete slot id (`breakup`, `strobe`) | |
| Programmer | `clear`, `blind on\|off`, `programmer` (prints the programmer) | |
| Record | `record group N [<merge>] ["name"]` | `RECORD_GROUP` |
| | `record preset <pool> N [global\|profile\|target] [<merge>] ["name"]` | `RECORD_PRESET`. Default scope by pool: colour and intensity → global, beam and focus → profile, position and all → target (§5.8) |
| | `record cue L/C [only <family>…] [<merge>] [freeze] ["name"]` | `BATCH` of cue list `L` (if it's new) + `RECORD_CUE` |
| | `record slot S [only <family>…] [<merge>] ["name"]` | Empty slot on the first page: `BATCH` of a new cue list, cue 1, a playback (number `S` if free) and `ASSIGN_PLAYBACK`. Occupied slot: `RECORD_CUE` into its cue 1, which requires `<merge>` |
| Patch | `universe add N ["name"]` | `ADD` |
| | `fixture add N [thru M] "<profile>" mode <mode> [at U.A]` | `BATCH`: the profile from the library if it isn't embedded yet, plus one `ADD` per fixture; addresses advance by the mode's footprint |
| | `fixture N patch U.A`, `fixture N patch none` | `PATCH_FIXTURE` |
| Output and surfaces | `route add U sacn <universe> [unicast <host>]`, `route add U artnet <net>.<sub>.<uni> [unicast <host>]` | `ADD` to `output.routes`. Without `unicast`, sACN uses multicast and Art-Net uses broadcast, on `--iface` |
| | `surface add midi "<device>"` | `ADD` |
| | `bind "<surface>" cc <ch> <n> fader <slot>`, `… note <ch> <n> button <slot> <b>`, `… cc <ch> <n> master gm` | `ADD` of a binding |
| Edit | `<entity> <prop[.sub…]> <value>`, e.g. `playback 3 exclusivity color`, `cue 10/1 timing.fadeIn 2` | `SET`. The value is parsed as JSON, and as a bare string if that fails |
| | `rename <entity> "name"`, `delete <entity>` | `SET` of the name; `DELETE` |
| Perform | `go N`, `release N`, `fader N <level>`, `gm <level>`, `blackout on\|off` | Phase 2 performance commands |
| Session | `undo`, `redo`, `save [PATH]`, `list <kind>`, `library`, `info`, `source FILE`, `quit` | |

`<entity>` is one of `fixture N`, `group N`, `preset <pool> N`, `cuelist N`, `cue L/C`, `playback N`, `page N`, `universe N`, or `show` for root properties (e.g. `show meta.title "Club Night"`).

**Defaults the console fills in.**
- A playback created by `record slot` copies Appendix A's Blue playback, without its exclusivity: priority 50, `master` fader, `toggle` and `flash` buttons, `threshold` LTP mode with threshold 0.02, auto start and auto release on, a full-level flash that includes LTP, and a 1 s release time.
- A cue list is created in `sequence` mode, with no tracking, no wrap and no release at the end.
- A fixture gets a neutral orientation and a name built from the profile's model and the fixture number.

**Error messages** say what the operator typed, e.g. `no group 7` or `preset color 1 exists: add merge or replace`. Validator issues are appended with their paths. For example, deleting a fixture that is still in use lists every path that references it.

Illustrative opening of `examples/phase3-build.busk` (the profile names will come from the Phase 1 library):

```
universe add 1 "Stage"
fixture add 101 thru 104 "Generic Spot 16ch" mode 16ch at 1.1
fixture add 201 thru 204 "RGBW Par 8ch" mode 8ch at 1.101
sel fixture 101 thru 104
record group 1 "Moving Heads"
sel fixture 201 thru 204
record group 2 "Pars"

sel group 1, group 2
set color 0 0 1
record preset color 1 "Blue"
set color 1 0 0
record preset color 2 "Red"
clear

sel group 1
set pan spread -45 45
set tilt -15
record preset position 1 "Audience"
clear

sel group 1, group 2
set intensity 1
set color 1 0.8 0.6
record slot 1 "Warm base"
playback 1 exclusivity base
clear
sel group 1, group 2
preset color 1
record slot 3 "Blue"
playback 3 exclusivity color
# … Red bump, Audience bump, route, surface and bindings …
save
```

### 5.11 Compile and stall budget

**The risk.** The session validates, compiles and builds frames on the caller's thread, and the autosave thread serialises. In CPython all of this holds the GIL and can delay engine ticks.

**The benchmark.** `bench/edit_latency.py` builds two rigs:
- the §19 reference rig: 400 fixtures over 64 universes using Phase 1 profiles, 40 groups, 100 presets and 100 cue lists;
- the demo rig.

For each rig it runs the engine at 100 Hz on the real clock, performs 50 edits of each kind (record cue, record preset, patch, set) with autosave running, and reports edit latency (p50 and p95), engine overruns and the maximum tick time.

| Measure | Demo rig | Reference rig |
|---|---|---|
| Engine overruns during edits and autosave | 0 (hard requirement) | target 0 |
| Edit latency p95 | ≤ 50 ms | target ≤ 250 ms |

If a target is missed, apply these mitigations in order, re-measuring after each one:

1. **Shorter GIL switch interval.** Call `sys.setswitchinterval(0.001)` in `busk run`, so the engine thread gets the GIL back sooner.
2. **Per-entity JSON encoding.** Encode `show.json` with one `json.dumps` call per fixture, cue list and so on, so that no single C call holds the GIL for long.
3. **Identity-memoised compile (§6.4).**
   - Reuse the old slot table when `fixtures`, `profiles` and `universes` are the same objects as before. Copy-on-write guarantees that for any edit that doesn't touch them.
   - Reuse a compiled cue list when the cue list object, and every group and preset it read, are the same objects. The compiler records what each cue list read.
   - This gives §6.4's dependency graph from object identity, without a separate reverse index.

Record the measured numbers under step 13. If the reference rig still misses its targets after all three mitigations, the gap becomes an input for Phase 7's process split rather than a blocker.

---

## 6. Implementation steps

Each step follows TDD: write the listed tests first, then make them pass. All engine tests use a `FakeClock` and call `engine.tick(now)` directly.

1. **Reconcile with Phases 1–2.** Map every §2 seam to the real code, correct the names in this plan, and add anything missing: the engine snapshot, `Frame.compiled`, and `resolve_source` as a public helper. Add `hypothesis` if needed. → *verify:* the existing suite is green, and §2 of this plan matches the code.
2. **Command types and classes.** → *verify:* `test_schema.py` is extended, and these hold:
   - Phase 0's walk test covers every new TypedDict automatically, so each new command type is strict.
   - A table test asserts that every member of the `Command` union has exactly one class.
   - Appendix A still validates with 0 errors and 0 warnings.
3. **Patches.** → *verify:* `test_patch.py` checks that:
   - applying the forward ops and then the inverse ops restores a deep-equal show, for `add`, `remove` and `replace` on both dicts and lists;
   - untouched siblings are the *same objects* (`is`);
   - `IdSegment` lookup works, and an unknown id produces an error;
   - protected paths are rejected;
   - a snapshot taken before an edit is unchanged after it;
   - (hypothesis) random op sequences, undone in reverse order, restore the original.
4. **`validate_edit`.** → *verify:* `test_validate_edit.py` checks that:
   - structural errors in a touched entity carry show-level paths;
   - (hypothesis) on random edit sequences over Appendix A, `validate_edit` and `validate_show(json.dumps(show))` report the same errors.
5. **Generic edits, `PATCH_FIXTURE`, `ASSIGN_PLAYBACK`, `BATCH`.** → *verify:* `test_edits.py` is table-driven. It covers:
   - the exact ops each command produces;
   - rejections: a dangling reference (the message lists the paths that reference it), a duplicate number, a protected path;
   - `ASSIGN_PLAYBACK` extending `slots`;
   - a `BATCH` whose last command fails changes nothing.
6. **Programmer.** → *verify:* `test_programmer.py` covers every row of the §5.4 table, including:
   - selection order under add and remove;
   - spread values computed from selection indices;
   - `APPLY_PRESET` scope lookup when some targets receive nothing;
   - skipped targets counted in the message;
   - dormant values after a fixture is deleted, which come back when the delete is undone.
7. **Recording.** → *verify:* `test_record_group.py`, `test_record_preset.py` and `test_record_cue.py` cover every rule in §5.5. In particular:
   - the two worked cases (rebuilding Appendix A's Blue cue, and the merge);
   - scope cascade fallbacks;
   - preset references flattened inside presets;
   - removal of shadowing entries on merge;
   - spread restriction that keeps exact values;
   - `freeze`;
   - cue numbering after `"3.5"`;
   - group-cover tie-breaks;
   - deterministic entry order.
8. **Session and timeline.** → *verify:* `test_session.py`, using a real `Engine` on a `FakeClock`, checks that:
   - a rejected edit leaves the show, compiled show, programmer, timeline and engine queue all unchanged;
   - undo and redo work across a mix of programmer and show steps, and a new step clears redo;
   - blind is never undone;
   - undoing everything returns the initial show;
   - a performance command submitted while another thread holds the session lock is queued immediately (the test coordinates the threads with `Event`s, so it is deterministic);
   - `post` keeps arrival order.
9. **Engine integration.** → *verify:*
   - `test_engine_programmer.py`:
     - the programmer overrides playback intensity, including with a lower value, and LTP values from band 100;
     - blind excludes the programmer from output;
     - leaving blind re-touches every programmer slot;
     - a band-100 playback triggered after a touch wins over the programmer;
     - grand master and blackout still apply.
   - `test_live_swap.py` checks golden frames for each of these:
     - recording into a live cue;
     - re-recording a preset that a live cue references;
     - moving a fixture's patch (remap);
     - deleting a running playback;
     - adding a universe and a route, after which output and input reconcile.
10. **Show files and `busk new`.** → *verify:*
    - `test_show_file.py` checks:
      - ZIP and JSON round-trips;
      - byte-identical saves for equal shows;
      - a failing `os.replace` leaves the original file intact and removes the temp file;
      - backup rotation keeps 10.
    - `test_cli.py`: `busk new` writes a template that `busk validate` accepts with 0 errors and 0 warnings.
11. **Autosave and recovery.** → *verify:*
    - `test_autosave.py`, using a `FakeClock` and temp directories, checks the burst and periodic triggers, retention, the contents of `session.json`, and every row of the §5.9 recovery table.
    - `test_recovery.py` runs `busk run` as a subprocess:
      1. pipe commands into it;
      2. wait for `session.json`;
      3. kill it with SIGKILL;
      4. restart it;
      5. assert that the programmer and the unsaved edits came back.
12. **Console and CLI.** → *verify:*
    - `test_console_parser.py` checks line → `Action`, with at least one case per grammar row, plus error messages.
    - `test_console.py` covers `execute`, `source` and the defaults.
    - `test_cli.py` covers `--script` (including stopping at the first error with exit code 1), stdin mode, and Ctrl+C at the prompt not stopping output.
13. **Benchmark.** Run `bench/edit_latency.py` and apply the §5.11 mitigations if needed. → *verify:* the demo rig shows 0 overruns and an edit p95 ≤ 50 ms, and the reference-rig numbers are recorded below.
    - *Results* (2026-10-11, dev machine, Python 3.14.7; `uv run python bench/edit_latency.py`, with `busk run`'s settings). The reference rig is 400 fixtures (Appendix A spots, MH-X25, ML-56, COLORband PiX in turn) over 64 universes, 4 300 slots, 40 groups, 100 presets, 100 cue lists with playbacks, 20 running.

      | Rig | Edit p50 / p95 / max | Overruns during edits + autosave | Max tick |
      |---|---|---|---|
      | Demo (the Phase 3 build, 7 fixtures) | 4.2 / 7.4 / 9.5 ms | **0** in 786 ticks | 3.3 ms |
      | Reference | 38 / 121 / 125 ms (patch ≈ 110 ms, record preset ≈ 36 ms, set ≈ 38 ms, record cue ≈ 15 ms) | 32 in 1 696 ticks | 22.7 ms |

      Without mitigations the reference rig had p95 131 ms and **386 overruns** (max tick 86 ms); the demo rig met its targets from the start (p95 8.4 ms, 0 overruns). The mitigations, in order:

      1. **Switch interval.** 1 ms (the planned value) changed nothing measurable: the stalls are the GIL *convoy effect* (numpy releases the GIL inside large kernels, and the engine then waits a full interval to get it back from the edit's CPU-bound thread), so a tick is delayed by up to N × interval. 0.1 ms cut overruns to ~40 and the worst tick to ~30 ms; `busk run` uses **0.1 ms** (`busk.cli.SWITCH_INTERVAL`) and restores the old value on exit.
      2. **Per-entity JSON encoding** was not needed: encoding the whole reference show holds the GIL for 2.3 ms (the `.show` autosave 5.4 ms, of which zlib releases the GIL), below one tick.
      3. **Identity-memoised compile** is implemented (`compile_show(show, previous=…)`, §5.11): the rig is reused when profiles, fixtures and universes are the same lists, a cue list when it and every group and preset it read are the same objects. A full compile of the reference rig takes 45 ms; a `SET` now costs 4 ms in isolation, a `RECORD_CUE` 12 ms. Patch edits still rebuild the rig.
      4. Beyond the plan: **`gc.freeze()`** after loading moves the show and its compiled form out of the cyclic GC's scans, cutting the longest full collection from ~23 to ~13–17 ms.

      The reference rig still misses its "0 overruns" target (≈ 2 % of ticks overrun while edits run, none while idle), as §5.11 anticipated for CPython threads: it is an input for Phase 7's process split. Edit latency is well inside its 250 ms target.
14. **Build from scratch.** Write `examples/phase3-build.busk` and `test_build_from_scratch.py`. The test uses a counter id factory, a fixed wall clock and a state directory holding a fixed CID. → *verify:* the test checks that:
    1. every line of the script succeeds;
    2. the saved show equals `tests/golden/phase3_built_show.json`, and `busk validate` reports 0 errors and 0 warnings;
    3. after `fader 1 1` and `fader 3 1` and a tick, the universe bytes equal the golden frame;
    4. after `record preset color 1 merge` with a new blue, the moving heads' bytes change on the next tick, and the playback's cue still holds the preset reference;
    5. undoing everything gives the template show and an empty programmer, and redoing everything gives the final show again;
    6. save → load gives an equal show, and a fresh engine on the loaded show produces the same frame.
15. **Manual demo on real fixtures.** Run `busk new`, then `busk run --script examples/phase3-build.busk`, then busk from the MIDI controller. Re-record a preset live and watch the stage change; then `undo`. → *verify by eye:* everything behaves as in the Phase 2 demo, and no overruns are reported.
16. **Full verification pass** (§8).

---

## 7. Acceptance tests (summary)

| Test file | Proves |
|---|---|
| `test_schema.py` (extended) | New command types are strict; each command has exactly one class |
| `test_patch.py` | Inverse ops restore the original show; structural sharing; id paths; protected paths; no in-place mutation |
| `test_validate_edit.py` | Per-edit validation agrees with full validation |
| `test_edits.py` | Generic edits, patching, page assignment, atomic `BATCH`, rejections with paths |
| `test_programmer.py` | Selection, the four value sources, preset application, skips, blind, dormant values |
| `test_record_group.py` · `test_record_preset.py` · `test_record_cue.py` | Recording keeps references, follows scopes and filters, and merges correctly |
| `test_session.py` | Store invariant, unified undo / redo, performance never blocked, install ordering |
| `test_engine_programmer.py` | Programmer as a band-100 source; blind; sequence ordering |
| `test_live_swap.py` | Golden frames across live edits, remaps, deletions, new routes |
| `test_show_file.py` | `.show` / `.json` I/O, atomicity, backups, template |
| `test_autosave.py` · `test_recovery.py` | Autosave triggers and retention; crash recovery end to end |
| `test_console_parser.py` · `test_console.py` · `test_cli.py` | Grammar, defaults, scripts, CLI flags, live-safe Ctrl+C |
| `test_build_from_scratch.py` | The done criterion |

---

## 8. Verification

```bash
uv run pytest                                          # all green
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run busk new /tmp/busk-demo/club.show --title "Club Night"
uv run busk run /tmp/busk-demo/club.show --script examples/phase3-build.busk
#   script output ends with "saved /tmp/busk-demo/club.show"; the console stays open
#   busk> fader 1 1
#   busk> fader 3 1                  → warm base, then the bump turns the fixtures blue
#   busk> sel group 1
#   busk> set color 0 0.3 1
#   busk> record preset color 1 merge → stage changes live; playback 3 untouched
#   busk> undo                        → back to the original blue
#   busk> quit
uv run busk validate /tmp/busk-demo/club.show          # → 0 errors, 0 warnings
unzip -p /tmp/busk-demo/club.show show.json | head -20 # readable JSON, group/preset references in cues
uv run python bench/edit_latency.py                    # demo rig: 0 overruns, p95 ≤ 50 ms
# crash check: start busk run, set values, `kill -9 <pid>`, start again → "recovered programmer …"
```

---

## 9. Spec deviations and gaps

**Deliberate deviations**

- **Programmer location.** Programmer state lives in the Session, not in `EngineRuntime` (§5.18), and programmer commands don't travel on the engine's "same queue" (§15.2). The engine receives `ProgrammerFrame`s instead (decision 2).
- **Programmer history.** `ProgrammerState.history` is replaced by the unified timeline (decision 6).
- **Programmer value fields.** `ProgrammerValue.active` and `touchedSeq` are not stored. No command makes a value inactive yet, and the engine assigns sequence numbers when it installs a frame.
- **§15.2 command changes:**
  - `RECORD_CUE.merge` becomes optional;
  - `RECORD_CUE` gains `name` and `freeze`;
  - `RECORD_PRESET` gains `merge` and `name`;
  - new commands: `SELECT_PLAYBACK`, `RECORD_GROUP`, `ADD`, `SET`, `DELETE`, `BATCH`, `UNDO`, `REDO`;
  - `BLIND` and `ASSIGN_PLAYBACK` get concrete fields;
  - `EDIT_GROUP`, `UPDATE_PRESET` and `RENAME` become `RECORD_GROUP`, `RECORD_PRESET` with `merge`, and `SET`.
- **Live swap.** It snaps until Phase 4; §6.4 asks for re-targeted fades.
- **Incremental recompile.** If it is needed, it comes from object identity rather than a reverse-dependency index (§5.11).

**Gaps decided here (to fold back into the spec)**

- **Pools vs families.** The `shutter` family has no pool, so it goes in the beam pool. `control` never goes in any pool.
- **Preset merge across scopes.** §15.3 defines merge for cues only. The rule used here is in §5.5.
- **Whole fixture vs element 0.** §5.7 calls element 0 "whole fixtures". Here, the console's `fixture N` means every element, and a `TargetRef` always means exactly its own element. The spec needs to decide this before multi-element fixtures matter, together with Phase 0's open `elementPatch` question.
- **Spreads in the programmer.** §5.14 stores one source per slot, which can't hold a spread. Spreads are therefore flattened to literals, recorded as `perTarget`, and don't re-fan when the group changes. Keeping them would need programmer entries at entry level rather than slot level.
- **Cue merge on group entries.** Overriding some members of a group entry splits it. The members that weren't overridden become an explicit list that no longer follows the group.
- **sACN CID.** §5.16 calls the CID persistent per installation, but the show stores it. `busk new` uses the installation's CID, yet a show copied to another console still carries the first console's CID. Suggestion: output always uses the installation CID, and the show field is dropped or becomes an explicit override.
- **Unspecified defaults:**
  - new cues get 0 s `linear` timing;
  - undo history is not persisted;
  - the `select` button picks the first cue's targets until Phase 4.
- **Highlight vs blackout and park.** §12 orders highlight after both, which would light a fixture in blackout or a parked fixture. This is decided in Phase 7, together with park.
- **Recording into tracking lists.** §15.3 doesn't say whether values equal to the tracked state are stored. Phase 3 stores everything; Phase 4 decides.

---

## 10. What Phase 4 changes

- The programmer's `fadeTime` applies to programmer changes and to clears, with both value and presence fades from the Phase 4 fade engine.
- Live swap fades running contributions to their new values using cue timing, instead of snapping, as §6.4 is written.
- GO, BACK and GOTO play the multi-cue lists that Phase 3 can already record. `SELECT_PLAYBACK` uses the current cue, and the console drops its "only cue 1 plays" warning.
- `RECORD_CUE` becomes tracking-aware, and it can record `releases`.
