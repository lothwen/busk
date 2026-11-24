# MVR plots: implementation plan

> Source: the user's request of 2026-11-17: bring MVR (My Virtual Rig, DIN SPEC 15801) into
> busk. The user-side design came first, in conversation (§4 is it), then this plan. On
> 2026-11-22 the user took the recommended answer to each of §6's questions: (a) for Q1 to Q4.
> §7's calls are the plan's, open to veto. Checked on 2026-11-17 at 615dbd6, with Phase 33
> uncommitted on top.

In this plan a **plot** is an MVR file: the rig as a lighting designer draws it in CAD
(Vectorworks, grandMA3, Capture, Depence, …). Importing a plot builds or updates busk's rig.
It never touches programming.

## 1. Scope

**In:**
- `rig check "<path>"` and `rig import "<path>"`. A plot's fixtures become busk fixtures: the
  profile from the plot's GDTF, the mode, number, name, patch, location and invert pan/tilt.
  The import is one undo step, with a report.
- Importing a plot again after it changed. Fixtures are matched by their MVR UUID, then
  added, moved, repatched, given another mode, renamed or removed, and programming is kept.
- A **stage frame** stored in the show: where busk's origin is in the plot, and which side the
  audience is on.
- Groups from the plot's hanging positions (Q3).
- The plot's truss and set drawn in the web stage view (Q4).
- F3's `[import plot…]` and a review dialog; on 2026-11-22 the user added Import plot… in the
  File menu, and the file picker to choose the plot, always.
- Settling busk's own x axis first: the web and TUI stage views disagree today (§11).

**Out** (§12): export to MVR, MVR-xchange, focus points, multipatch fixtures, fixtures with
several DMX breaks, a plot's newer GDTF revision, mapping a GDTF to a profile the show has,
the GDTF's own 3D models, gels and gobos.

## 2. What a plot holds

From the MVR 1.6 spec (DIN SPEC 15801) and the GDTF spec, read on 2026-11-17 at
github.com/mvrdevelopment/spec.

- **The archive.** A zip (STORE or DEFLATE, no encryption) with
  `GeneralSceneDescription.xml` and every file it references side by side at the root. Those
  files are the GDTF of each fixture type (`Maker@Fixture.gdtf`), 3D models (`.3ds`,
  deprecated; `.glb`/`.gltf`, glTF 2.0 with no required extensions) and textures. An exporter
  must keep an unchanged GDTF in the file. But a fixture's `GDTFSpec` is optional, so a plot can
  lack one.
- **The scene.** `Scene/Layers/Layer` (uuid, name, and a matrix that may only lift it) holds a
  `ChildList` of `Fixture`, `Truss`, `Support`, `SceneObject`, `VideoScreen`, `Projector`,
  `GroupObject` and `FocusPoint`. Objects can hold a `ChildList` of their own, and a child's
  matrix is relative to its parent. `AUXData` holds `Symdef` (shared geometry, placed by
  `Symbol`), `Position` (named hanging positions such as "LX1"), `Class` and
  `MappingDefinition`.
- **Coordinates.** Right-handed, Z up, millimetres. The spec says nothing about where the origin
  is or which side the audience is on: each plot chooses. Many plots are drawn with the audience
  at the bottom of the page (−Y), but busk cannot rely on that.
- **A matrix** is written `{u1,u2,u3}{v1,v2,v3}{w1,w2,w3}{o1,o2,o3}`: the local x, y and z axes,
  then the offset in mm. It is the identity when missing.
- **A fixture** has a `uuid`, a `name` and `multipatch` (the uuid of the fixture it copies). Its
  children:
  - `Matrix`;
  - `GDTFSpec` (a file in the zip) and `GDTFMode`;
  - `Position` (a uuid) and `Focus` (the uuid of a FocusPoint);
  - `FixtureID` (text, required), `FixtureIDNumeric` (an integer, required in 1.6),
    `UnitNumber` and `CustomId`;
  - `DMXInvertPan` and `DMXInvertTilt`;
  - `Addresses`;
  - `Color` (a gel, CIE xyY), `Gobo`, `Mappings`, `Protocols` and more.

  A fixture has no geometry of its own: its shape is in its GDTF.
- **An address** is `<Address break="0">`. The break defaults to 0 and is unique per fixture.
  The value is either an absolute address or `Universe.Address`, with universes from 1 and
  addresses from 1 to 512.
- **Scenery.** `Truss`, `Support`, `SceneObject`, `VideoScreen` and `Projector` have
  `Geometries`: `Geometry3D` (a model file, where no extension means 3ds) and `Symbol` (a Symdef,
  with a matrix). 3DS units are millimetres; glTF's own rule is metres.
- **GDTF's zero.** "The device shall be drawn in a hanging position displaying the front view."
  "The beam geometry emits its light into negative Z direction." So a plot fixture with an
  identity matrix hangs with its beam down and its front to −Y.
- **No programming.** No groups as busk means them, no presets, no cues.

## 3. What busk does today

- **Profiles from GDTF.** `busk.importers.gdtf.import_gdtf(bytes)` returns an `ImportReport`:
  the profile and its notes. The profile's id is `gdtf-<FixtureTypeID>` and its name
  `<Manufacturer> <Name>`; its revision is the newest revision's date plus a hash. A `DOCTYPE`
  is refused, and `description.xml` is capped at 32 MB. DMX breaks after the first are reported,
  not imported. A GDTF profile has no category.
- **`profile import "<path>"`** (GAP-39, `Console._import_profile`). The console reads the file,
  so the parser stays pure. It refuses a profile the show already holds by id or name, and
  submits one `BATCH`: one undo step. The new lines work the same way.
- **Fixtures** (`busk.model.fixture`) have:
  - `number`, `name`, `profileId`, `profileRevision` and `modeId`;
  - `patch` (`None` means unpatched);
  - `elementPatch`, which is in the model, but the compiler refuses a split patch (GAP-40,
    dropped with pending-plan Q4);
  - `orientation` (invertPan, invertTilt, swapPanTilt, panOffset, tiltOffset), `limits` and
    `location`.

  `fixture add` names a fixture `<model> <number>`.
- **Location.** Metres from the middle of the downstage edge at deck height: x to stage right,
  y downstage, z up. rx, ry and rz are degrees about x, then y, then z, so the rotation is
  `R_z·R_y·R_x` (`stage.html` sets three.js order `'ZYX'`). At zero a fixture stands on its base
  with its beam up; a hung fixture is rx 180. Location is display-only. The web stage view
  (`busk/web/stage.py`, `static/stage.html`), F1 layout C's stage
  (`busk_tui/pages/busk_stage.py`) and F3's `[location…]`
  (`busk_tui/widgets/location_form.py`) read it, and nothing in the engine does. The two views
  disagree on x (§11).
- **Deletes and mode changes** (Phases 4 and 24, `busk/console/cascade.py`). A delete of
  something programming uses is refused unless `cascade`. A mode or profile change that loses
  elements in use is refused in one line naming what uses them.
- **`confirmation(line)`** only parses. It cannot read a file, so a preview of an import needs a
  line of its own (`rig check`).
- **The show** is `schemaVersion` 1. A new optional field does not bump it.
- **Tests** build GDTF files in code (`tests/gdtf_builder.py`).

## 4. The design in one picture

A busker starts from a plot (the replies are sketches):

```
$ busk new club.show --title "Club"
busk> rig check "plots/club.mvr"
the plot has 48 fixtures, 6 profiles and 3 universes; the show has none of them
  add 47: 101–112, 201–212, 301–315, 401–408
  universes to add: 1, 2, 3
  groups to add: "LX1", "LX2", "FOH", "Floor"
  note: 310 has a second DMX break, not patched
  note: "Hazer" has no GDTF in the plot, not added
fixtures span x −7.5…7.5 m, y −9.0…1.5 m, z 0…8.0 m
busk> rig import "plots/club.mvr"
imported 47 fixtures, 6 profiles, 3 universes and 4 groups from club.mvr; 2 notes
```

The span line shows a wrong frame at once. A plot whose origin is a corner of the venue puts
everything 20 m off. `audience` and `origin` on the line fix it (§5).

From then on it is an ordinary show: routes on F8, presets, cues. A week later the designer
sends `club-v2.mvr`:

```
busk> rig check "plots/club-v2.mvr"
  add 4: 601–604
  move 12: 201–212
  repatch 8: 301–308
  change 1: 205 mode 8ch → 16ch
  remove 2: 309, 310: used by 3 presets and 1 cue, add cascade
  note: 601–604 are on LX3, a new position: no group made
busk> rig import "plots/club-v2.mvr" cascade
```

Fixtures keep their busk identity, so every preset and cue that uses 201–212 still does. An
import never touches a fixture the busker added by hand. In the TUI, F3's `[import plot…]`
runs `rig check`, shows the same list in a dialog, then sends `rig import`. The web stage view
puts each fixture where the plot does, and draws the truss and set from the plot's models.

## 5. Coordinates

This section assumes Q1 (a), the recommendation: busk keeps its frame, and the plot is translated
through a **stage frame** stored in the show.

The frame is two settings. The first import sets them, and every later import reuses them:
- `origin`: where busk's origin (the middle of the downstage edge, at deck height) is, in the
  plot's millimetres. The default is `0 0 0`.
- `audience`: which side of the plot the audience is on: `-y` (the default), `+y`, `-x` or
  `+x`. It gives the turn θ about z from the plot's axes to busk's:

| `audience` | θ | busk x, y from the plot's X, Y |
|---|---|---|
| `-y` | 180° | −X, −Y |
| `+y` | 0° | X, Y |
| `-x` | −90° | Y, −X |
| `+x` | 90° | −Y, X |

Under Q1 (b), add 180° to each.

Take a fixture's composed matrix M: the layer and every parent applied, with rotation R and
offset o in mm.
- **Location:** `(x, y, z) = R_z(θ) · (o − origin) / 1000`.
- **Turn:** `R_busk = R_z(θ) · R · R_x(180°)`, because busk's zero stands with the beam up and
  GDTF's hangs with the beam down. Then rx, ry and rz come from `R_busk = R_z·R_y·R_x`. A plot
  fixture with an identity matrix comes out at rx 180, ry 0, rz θ. With `audience -y` that is
  hung, its front to the audience. A gimbal case (ry ±90°) takes rx 0.
- **Scenery** uses the same transform, without the `R_x(180°)`.

Giving `audience` or `origin` on a later line changes the stored frame. Every plot fixture then
moves, and the report lists them under `move`.

Why not take MVR's frame whole (Q1 c):
- The spec fixes the axes and the unit, not the origin or the audience side, so every plot
  still needs a frame.
- Millimetres from a venue corner are hard to type in F3's form.
- Both stage views assume the origin is at downstage centre.
- A show built without a plot gains nothing.

The translation is one function, tested once.

## 6. Questions (answered 2026-11-22: (a) for each)

**Q1. Coordinates.**
- (a) *(recommended)* Keep busk's frame: metres, origin at downstage centre, x to stage right,
  y downstage, z up, zero standing with the beam up. Translate through the stored frame (§5),
  and fix the TUI stage page, which draws x mirrored (§11). Nothing to migrate.
- (b) Keep busk's units, origin and zero, but turn its axes to the way plots are drawn: x to
  house right (stage left), y upstage. Typical plots then import with θ 0, and y is positive on
  stage, as a plot reads. The TUI page is already right this way round. The web view, the spec
  and every saved location change: on load, x and y are negated and 180° is added to rz.
- (c) Take MVR's frame whole: millimetres, and each plot's own origin. Not recommended (§5).

**Q2. What a re-import changes.**
- (a) *(recommended)* The plot owns the patch, profile and mode, location, name, and invert
  pan/tilt when the file sets them. busk owns the number and everything else: swap, offsets,
  limits, park, groups. The first import sets the number, and later imports never change it; a
  different FixtureID is noted.
- (b) As (a), and the plot owns numbers too: a fixture renumbered in the plot is renumbered in
  busk. That needs a new edit, `fixture N number M`.
- (c) No re-import: a plot builds a rig once.

**Q3. Groups from hanging positions.**
- (a) *(recommended)* The first import makes one group for each plot `Position` that holds
  fixtures, named after it. Members are ordered left to right as seen from the audience, stage
  right first. Groups are numbered after the show's highest group. Later imports make no groups
  and change none, because the busker owns them; a new position, or a new fixture on an old one,
  is noted.
- (b) No groups.

**Q4. Where the scenery comes from.**
- (a) *(recommended)* The show keeps the plot's path and a hash; the path is relative to the show
  file when it can be. The stage view reads the scenery from the plot when it opens. A missing
  plot draws the plain deck; a changed one is drawn with a note. The show stays one file and runs
  anywhere.
- (b) Copy the models into a folder beside the show at import.
- (c) Embed them in the show. Not recommended: a show is one JSON file, and models are megabytes.

## 7. Calls the user may veto

1. **Words.**
   - `rig check "<path>" [audience -y|+y|-x|+x] [origin <x> <y> <z>]` reports and changes
     nothing.
   - `rig import "<path>" [audience …] [origin …] [cascade]` does it.

   The word order follows `profile import`. There is no `busk import mvr` command: `busk new`
   and the line do the job, and `OfflineShow` and `LiveShow` run the line like any other.
2. **One undo step, all or nothing.** A line that cannot run whole is refused, naming what
   blocks it, as `delete` and `fixture N mode` are. Examples: a used fixture removed without
   `cascade`, or a mode change that loses elements in use. `rig check` lists the blockers first.
3. **Numbers.** `FixtureIDNumeric` when it is above 0, else `FixtureID` when it is an integer,
   else the next free number above the show's highest. A number already taken, by a hand-added
   fixture or a duplicate, also gets the next free one. Each case is noted.
4. **Names.** The plot's `name`, else busk's `<model> <number>`.
5. **Profiles.** Each GDTF goes through `import_gdtf`.
   - A profile the show holds by id is used as the show has it, at its revision. A newer revision
     in the plot is noted, not taken.
   - A GDTF that is missing from the zip, fails to import, or clashes by name with another of the
     show's profiles: its fixtures are not added, and that is noted.
   - `GDTFMode` is found the way `fixture add` finds a mode. If it is missing, the fixture is
     left out and noted.
6. **Patch.**
   - The fixture is patched at break 0's address. Other breaks are noted (no split patch:
     GAP-40).
   - An absolute address `a` is universe `(a − 1) // 512 + 1`, address `(a − 1) % 512 + 1`. To be
     checked against a real plot.
   - A universe the show lacks is added as `Universe N`. Routes are never touched.
   - A fixture with no address is added unpatched.
7. **What a fixture remembers.** A new optional `mvrUuid` on a fixture. An import never touches
   fixtures without one: they are the busker's. A fixture with one that the plot no longer has is
   removed, with `cascade` when programming uses it.
8. **Multipatch fixtures** (`multipatch` set) are not added, and are noted. busk has no notion of
   one fixture with several addresses.
9. **Orientation.** `DMXInvertPan` and `DMXInvertTilt` set `invertPan` and `invertTilt` when
   the file has them. busk's other orientation fields stay.
10. **Scenery** is the geometry of `Truss`, `Support`, `SceneObject`, `VideoScreen` and
    `Projector`, placed through the frame. With scenery, the stage view draws no generated deck.
    Focus points, mappings and gels are not drawn.
11. **Safety.** A plot is untrusted.
    - Zip members and their total size are capped.
    - `GeneralSceneDescription.xml` is capped and read the way `description.xml` is, with no
      `DOCTYPE`.
    - Member names are only looked up in the zip, never used as paths on disk.
12. **The span line.** Every report ends with the fixtures' extent in busk metres.

## 8. Phases

One conversation per phase, as in the pending plan. The engine comes first.

### Phase 1: busk's x axis (Q1)

1. **Settle the axes.**
   - Under Q1 (a): F1 C's stage page draws x the way the web view does, with stage right on the
     left as seen from the audience.
   - Under Q1 (b): change the web view, `stage.py`'s rows and deck and the spec, and migrate
     saved locations.

   Either way, one sentence in the spec says which way x points, in words a busker reads
   ("stage right", "house left").

   Verify: a fixture at x 3 is on the same side in both views (a test on `stage_rows`, one on
   the page's `world()`). Under (b), an old show's locations migrate and save.

**Done** 2026-11-22, on 2dca222, under Q1 (a). F1 C's stage draws the largest x on the left:
`stage_rows` orders a row from stage right to stage left, and `StagePlot.draw` places each
fixture at `high − x` (`src/busk_tui/pages/busk_stage.py`). The spec's §5.1 says which way x
points, under the units table. Tests: `test_stage_right_comes_first_in_a_row` and
`test_the_stage_plot` (`tests/tui/test_tui_layouts.py`), and
`test_stage_right_is_on_the_left_from_the_front_of_house` (`tests/test_web_stage.py`), which
runs the page's own stage group, `world()` and front-of-house camera in node, and is skipped
without node. The TUI guide's layout C drawing and the `Location` docstring say stage right.
Saved locations, the web view and `examples/festival.busk` are unchanged.

### Phase 2: first import

2. **Model.** `Fixture.mvrUuid` (optional) and `Show.stage` (optional): `plot` (a path),
   `plotHash` and `frame` (`origin` in mm, `audience`). Update spec §5.6, validation and the
   public API golden file.
   Verify: save and load; a show without them loads unchanged.
3. **Reader** (`busk.importers.mvr`). It turns bytes into a plain description, without a show:
   - fixtures: uuid, name, numbers, GDTF file and mode, addresses, composed matrix, position
     name, inverts, multipatch;
   - positions;
   - scenery: model file and matrix;
   - notes.

   Matrices are composed from the layer down to the object. Add a test builder
   (`tests/mvr_builder.py`) like `gdtf_builder.py`.
   Verify:
   - nested layers, group objects and trusses;
   - both address forms, and breaks;
   - a missing GDTF;
   - a `DOCTYPE` refused, and the caps;
   - the spec's own example matrix read as its axes.
4. **The frame** (§5): plot to location, and back.
   Verify, comparing rotations as matrices rather than as rx/ry/rz triples:
   - identity gives rx 180, rz θ;
   - a floor fixture, and one facing the audience;
   - each `audience` value, and an `origin`;
   - a plot → busk → plot round trip;
   - the gimbal case.
5. **`rig check` and `rig import`** into a show without plot fixtures. The line adds profiles,
   universes, fixtures and groups (Q3) and stores the frame and plot (Q4), in one `BATCH`. Add
   the parser, completion, help and replies in words.
   Verify:
   - console transcripts on `OfflineShow` and `LiveShow`;
   - `undo` takes it all back;
   - the DMX output of an imported fixture equals that of the same fixture added by hand;
   - the numbering and naming rules;
   - a profile the show already holds, and a name clash.
6. **Docs.** A short guide (`docs/plots.md`), `docs/console.md`, the spec, CHANGELOG.

**Done** 2026-11-22, on 5c2c1c1, with the recommended answers.
- **Model** (`src/busk/model/fixture.py`, `show.py`). `Fixture.mvrUuid`, and `Show.stage`, a
  `StageSettings` of `plot`, `plotHash` (SHA-256, hex) and `frame`, a `StageFrame` of `origin`
  (mm) and `audience` (`Audience`). A repeated `mvrUuid` is an error. Spec §5.6 and §5.17; the
  API golden gained the one `stage` line.
- **Reader** (`src/busk/importers/mvr.py`). `read_plot(path)` returns a `Plot`: fixtures
  (`PlotFixture`, with the composed `Matrix`), the GDTF types (`PlotType`: report or problem),
  positions by uuid, scenery (`Scenery`: kind, name, model file, matrix), notes and the
  file's SHA-256. The caps: 50,000 members, 4 GB unpacked by declared size, a 64 MB scene, a
  256 MB GDTF, symbols 16 deep and 100,000 models and symbols (a fan-out of symbols would
  otherwise expand without end). `gdtf.parse_description` takes the file's name for its
  errors. Test builder: `tests/mvr_builder.py`.
- **Frame** (same module). `plot_location` and `location_matrix`, with `Matrix` composing as
  columns u, v, w and offset o.
- **Lines.** Parser `_cmd_rig` → `ImportRig`; `Console._rig` reads the file and works out the
  frame (the line's words, else the stored frame, else `0 0 0` and `-y`); the pure planner is
  `src/busk/console/rig.py` (`plan_rig` → `RigPlan`).
- **Tests.** `tests/test_mvr.py` (reader and frame, 95, one a Hypothesis round trip),
  `tests/test_rig.py` (40: transcripts on `OfflineShow` and `LiveShow`, undo, DMX equal to a
  fixture added by hand, numbers and names, held profiles, clashes, patch, frame, paths,
  refusals, the line and its completion), `tests/test_schema.py` (8). Mutations of the
  turn, the gimbal case, matrix composition, addresses, the frame's inverse, group order,
  numbering, the patch, held profiles, check's ids, the stored frame, the refusal and the
  relative path were each caught.
- **Calls made while building**, open to veto:
  1. A show with any fixture holding `mvrUuid` refuses both lines ("importing a plot again
     is not supported yet") until Phase 3. `cascade` is not a word yet.
  2. A line with nothing to add is refused after its notes; `rig check` says `nothing to
     add` (since Phase 6, on a first import, `no fixture busk can add`, as the import does).
  3. Notes group fixtures by reason, name three and count the rest. Numbering notes count
     fixtures and list numbers. Number lists run from three numbers (`101–103, 201, 202`),
     as `spec_words` runs `thru`.
  4. The reader leaves out, with a note, a fixture with no uuid or another's. Uuids are
     upper case. A GDTF named without `.gdtf` is found with it.
  5. Locations are rounded to 0.1 mm and 0.001°, angles in (−180°, 180°]. A matrix's scale
     is taken out; one with no turn is read as none, noted.
  6. A profile is added with the first fixture that uses it. `rig check` counts its GDTF
     import notes (`"…": 10 notes from its GDTF, listed by rig import`); `rig import` says
     them, prefixed with the file. Two files of one fixture type add one profile, the first used.
     A GDTF whose profile name another profile has, the show's or one this import adds, is
     refused. A profile the show holds at another revision is noted once.
  7. A universe is added only when a fixture is patched in it.
  8. `stage.plot` is relative to the show file's folder (`os.path.relpath`, climbing with
     `..`) when the session has a file, else absolute.
  9. Groups come in the plot's order of positions; members at the same x go by number.
- **By hand:** `busk run` with its processes, lines piped in: `rig check`, `rig import`, `list
  groups`, `save`; the saved show keeps `stage.plot` as `plots/club.mvr`, beside it.
- **A first real plot** (`Demostage_MVR.mvr`, MVR 1.5, 119 fixtures, 7 GDTFs, from an
  exporter that does not name itself) was refused: its exporter ends every XML file, the
  scene and each GDTF's `description.xml`, with a NUL byte after the last element, which XML
  forbids. `gdtf.parse_description` now drops NUL bytes there (not in a UTF-16 file, whose
  last character may end in one), so `profile import` reads such GDTF files too. The plot
  then imports whole: 119 fixtures, 7 profiles, 28 universes, no groups (it has no
  positions), span x −8.9…8.9, y −3.9…6.6, z 1.1…9.3 m. Its GDTF notes ran to 70 lines, so
  `rig check` counts them (call 6). Its `GDTFSpec`s have no `.gdtf`, which the reader
  already allows. Phase 6's check with the user's own CAD is still to come.

### Phase 3: importing again

7. **Matching and changes.** Fixtures are matched by `mvrUuid`. The line adds, moves, repatches,
   changes mode or profile, renames, sets inverts and removes. Hand-added fixtures are untouched,
   numbers are kept (Q2), and a frame given on the line replaces the stored one.
   Verify:
   - each kind of change alone and together;
   - a preset and a cue on a moved, repatched fixture output as before;
   - a removal refused without `cascade`, and done with it as `delete fixture N cascade` does;
   - a mode change refused, naming what uses the lost elements;
   - `undo`.
8. **Docs.** The guide's "when the plot changes" section.

**Done** 2026-11-22, on f280bb4, with the recommended answers (Q2 a, Q3 a).
- **Planner** (`src/busk/console/rig.py`). `plan_rig` matches the plot's fixtures to the show's
  by `mvrUuid`: it adds the new ones as Phase 2 did, updates the ones the show has (`_Item.old`,
  `_Planner.update`) and removes the show's fixtures whose uuid the plot lost, through
  `fixture_cascade`. `RigPlan` names each kind of change by fixture number (`added`, `moved`,
  `repatched`, `changed`, `renamed`, `inverted`, `removed`), what uses those removed (`uses`)
  and what stops the line even with `cascade` (`blocked`, from `element_users`, as
  `fixture N mode` refuses). `refusals(cascade)` gives the console's error lines; `command` is
  `None` when there is nothing to do. One `BATCH`: profiles, universes, the removal's cascade,
  the updates, the fixtures added, groups (a first import only), the stage.
- **Cascade** (`src/busk/console/cascade.py`). `Cascade.uses`: a fixture cascade's users,
  counted as its refusal says them, so the rig's lines say them as `delete fixture` does.
- **Lines.** `rig import "<path>" … [cascade]` (parser `_cmd_rig`, `ImportRig.cascade`;
  `rig check` takes no `cascade`). `Console._rig` no longer refuses a show with fixtures from
  a plot.
- **Tests.** `tests/test_rig.py` went from 40 to 67. The new ones: all the kinds of change
  together, each alone (10 cases), what the plot does not say, another profile, a preset and a
  cue on a moved and repatched fixture outputting as before, a removal refused without
  `cascade` and leaving the show as `delete fixture 103 cascade` does, removals nothing uses, a
  show whose plot fixtures are gone starting again, a mode that loses cells refused even with
  `cascade`, numbers, the frame, fixtures busk cannot read, a plot that changes nothing or
  only its file, a `LiveShow` transcript, and the parser and completion. Fifteen mutations
  were each caught: freeing removed numbers, the empty name, unsaid inverts, the refusal, the
  blockers, the stage compare, the position notes, location, patch, the renumber note,
  first-only groups, the profile change, the cascade's edits, keeping unreadable fixtures, and
  what counts as a first import.
- **By hand:** the real `Demostage_MVR.mvr` (119 fixtures) imported, then checked again:
  `nothing to change`, and `rig import` refused, so every location comes out the same from
  the same plot. `audience +y` then moved all 119, and `undo` took it back.
- **Calls made while building**, open to veto:
  1. A fixture of the show that busk cannot read in the new plot (no GDTF, a missing mode, a
     multipatch copy, a name clash) is left as it is and noted (`… not changed`), not
     removed.
  2. A fixture the new plot gives no name keeps busk's name. The patch follows the plot
     whole, so a fixture the plot does not patch is unpatched and a patch made by hand is
     undone (`rig check` lists both under `repatch`). An exporter that writes no addresses
     would unpatch every fixture on each import.
  3. A group counts as a use, as for `delete fixture`, so removing a fixture the first import
     put on a hanging position always needs `cascade`.
  4. `rig import … cascade` asks no question at a prompt (`confirmation` only parses the
     line, and cannot read the file); `rig check` is the preview.
  5. A refused import says one `error:` line per reason, the mode blockers first, and no
     notes. A blocker names the fixtures by the mode they would run: `fixtures 101, 102
     cannot run 1ch: groups 1, 7 use elements they would lose`. The removal's: `fixture 103
     is gone from the plot and used by 1 group: add cascade`.
  6. New fixtures on a hanging position are noted as `104 is new on "LX1": no group changed`
     when a fixture of the plot the show has hangs there, else as `301 hangs on "LX3", a new
     position: no group made`.
  7. A first import is one into a show with no fixture holding `mvrUuid`, whatever its
     `stage`: after `delete fixture … cascade` of them all, the next import makes groups.
  8. A new fixture may take the number of one the same import removes.
  9. Nothing to change: `rig check` says `nothing to change` and `rig import` is refused
     (`the rig is already as club.mvr has it`). A plot whose file changed but none of its
     fixtures (its set, or its path) imports, saying `no fixture changes`, so the show keeps
     the new hash for Phase 5.
  10. The span covers every fixture the plot places, those updated too, not only those added.
  11. The renumber note (`201 has another number in the plot (211): number kept`) comes on
      every import while the numbers differ, including for a fixture numbered otherwise at the
      first import because its number was taken.
  12. A later import's summary adds `; the show has N of them`. Its label reads `updated the
      rig from club-v2.mvr: added 2 fixtures and 1 universe; moved 1, repatched 2, changed 1,
      renamed 1, inverted 1, removed 1 (left 1 group)`.

### Phase 4: F3

9. **F3's `[import plot…]`.** It asks for a path (offering the stored plot), and for `audience`
   and `origin` on the first import. It shows `rig check`'s list in a dialog with an `[import]`
   button, with `cascade` ticked when needed. Update the TUI guide.
   Verify: an e2e test; a pty run on a real show.

**Done** 2026-11-22, on f97c2b4, with the recommended answers and the user's two additions of
that day: Import plot… in the File menu as well, and the file picker to choose the plot, always.
- **Engine: GAP-59** (`docs/dev/tui/engine-gaps.md`). The TUI never parses a reply, so whether
  the import needs `cascade` or is blocked had no typed form. `OfflineShow.rig_check(path, *,
  audience=None, origin=None)` and `LiveShow.rig_check` return a `RigCheck`: `text` (`rig
  check`'s reply, word for word), `first`, the frame used (`audience`, `origin`), `changes`,
  `cascade` and `blocked`. `Console.rig_check` and the line share `_plan_rig`. The 50th public
  name; it raises `ImportFailed`.
- **TUI.** The file picker's mode `plot` (`.mvr`; the preview is `plot_text`, the check through
  the show's frame, read by `ReadPlot` on a worker). IMPORT PLOT is
  `src/busk_tui/widgets/plot_dialog.py` (`PlotDialog`, `AudienceRow`). `BuskApp.import_plot`
  opens the picker on `ShowModel.plot` (the show's `stage.plot`, relative to its folder), else
  in the show's folder, and hands the preview's check to the dialog. It runs the line the
  dialog closes with (`commands.rig_import`). `Bridge.read_plot` and `plot_read` make
  `model.PlotRead`. F3's `[import plot…]` (`FixturesPage.ImportPlot`); the File menu's
  `import_plot`.
- **Tests.** `tests/tui/test_tui_plot.py` (20: the words, the picker and its preview, where it
  starts, the dialog starting from the preview's check, a first import's frame and line, a
  frame back where it started, a change while busk checks, a later import, `cascade`,
  blocked, nothing to do, a file busk cannot read, the scroll, a small screen, a check that
  comes back after the dialog closed, F3's button and stop, a script importing, the line busk
  runs), one e2e test on the real engine
  (`test_f3_imports_a_plot_and_imports_it_again_on_the_real_engine`), 8 in `tests/test_rig.py`
  for `rig_check`, the `busk run --frontend` probe. Six F3 tests, the prompt's pane-cursor
  test and the File menu's rows count the new control. 22 mutations: 19 caught at once, one
  (the preview's check reused) needed a test, and two showed code that did nothing (an origin
  turned to floats twice, a guard on `x`), removed.
- **By hand**, in a pty under `busk run` and `--standalone`, at 150×48, 100×30 and 80×24, on
  the real `Demostage_MVR.mvr` and `Circle_Stage.mvr` and on the tests' club plot: the
  picker's preview, the chips and the origin form re-checking, a first import from the menu,
  the picker on the stored plot from F3, a later import with nothing to change (grey), and
  one that removes a fixture in a group: `cascade` ticked, unticked (grey, and why), ticked,
  imported, `moved 1, removed 1 (left 1 group)` in the log.
- **Calls made while building**, open to veto:
  1. An engine gap (GAP-59) rather than reading `rig check`'s words.
  2. The picker's preview of a plot is the whole check, through the show's frame, so moving
     between two versions of a plot shows what each would change. The dialog starts from that
     check instead of reading the plot again.
  3. The picker starts on the plot the rig came from, else in the show's folder. Unlike
     profiles, it does not remember the plot chosen last in the run.
  4. The audience chips say where that side is, the plot drawn from above: `-y below`, `+y
     above`, `-x left`, `+x right`. ← → step them, and wrap round.
  5. The origin is set in a form of three fields (`[origin…]`, or `o`), not typed in the
     dialog, so each change is one check.
  6. A later import shows the frame the show keeps and offers no change to it (the plan asks
     on the first import only); `rig import … audience …` at the prompt still changes it.
  7. The line has `audience` and `origin` only where they moved from where they started (the
     show's frame, else busk's): a plain import is `rig import "<path>"`. The origin is written
     with every digit (`commands.exact`); the path is absolute, as the picker gives it.
  8. `[cascade]` shows only when the import needs it, ticked. Unticked, `[import]` is grey and
     the dialog says why. The key is `x`.
  9. `[import]` and Enter do nothing, and a line says why, while busk checks, when the import
     would change nothing, when it is blocked (in red, the `blocked` lines), and when busk
     cannot read the plot. The dialog stays open: Esc leaves it.
  10. The check scrolls in 16 rows at most, and fewer when the screen is small, so the buttons
      show (8 at 80×24). The plot's path is one row, its start cut.
  11. Import plot… waits while a script imports, as New… does, since its check would be of a
      show still changing. Import profile… never waited.
  12. `[import plot…]` is F3's first control, before `[+ add]`, and the pane cursor's first
      stop.
  13. Import plot… comes after Import profile… in the File menu, so Close and Quit are a row
      lower.

### Phase 5: the stage view's scenery

10. **Scenery.**
    - The server reads the stored plot (Q4) and sends a `scenery` message: each model's URL and
      its matrix in busk metres.
    - It serves each model from the zip at `/stage/scenery/<n>`, behind the same key.
    - The page loads three.js's glTF and 3DS loaders, reading 3DS in millimetres and glTF in
      metres, and draws no generated deck when there is scenery.

    Verify:
    - the headless Chromium check of the stage view;
    - a missing plot draws the deck, and a changed plot gets a note;
    - the frame rate with a real plot's models.

**Done** 2026-11-22, on 0c2876c, with the recommended answers (Q1 a, Q4 a).
- **Reader** (`src/busk/importers/mvr.py`). `scenery_matrix(matrix, frame)`: a model's axes
  turned by θ, their scale kept, and its offset in busk's metres, as `plot_location` places a
  fixture there without the R_x(180°). `read_plot(path, types=False)` imports no GDTF.
  `plot_file(path, name)` reads one file of the archive, by name only, under `MODEL_CAP`
  (256 MB) and `MEMBER_CAP`.
- **Feed** (`src/busk/web/stage.py`). The `rig` message gained `scenery` (each model file once:
  `file`, `format`, `at`, the twelve numbers of each place) and `notes`. `StageFeed.update(show,
  frame, path, opened=)` resolves `stage.plot` against the show's file (`WebLink.path`, the
  runner's `session.snapshot.path`) and reads it at each show change and each page that opens
  (`WebApi._watch`), again only when its path, mtime or size changed. `scenery_file` and
  `FILE_TYPES` say what `/stage/scenery/` serves.
- **Server** (`src/busk/web/server.py`). `GET /stage/scenery/<file>?k=` behind the key, from the
  plot the rig's scenery came from (`WebApi.scenery_file`, read outside the API's lock), with
  `nosniff` and `Content-Security-Policy: sandbox`.
- **Page** (`static/stage.html`). three.js's `GLTFLoader` and `TDSLoader` through one
  `LoadingManager` whose URL modifier adds the key (not to `blob:` and `data:`). glTF is turned
  from y up to z up; 3DS is scaled from millimetres, its own master scale reset. Each mesh is an
  `InstancedMesh` over its model's places. The floor is the scenery's lowest point (busk's 0
  when the scenery is all above it). Pools land on the scenery by raycast. The HUD shows the
  notes, and how many model files did not load.
- **Session** (`src/busk/session/session.py`, §11's finding). A Save as, or a show's first
  save, rewrites `stage.plot` relative to the new file's folder (`_plot_moved`), as it rewrites
  `meta.id`: not an undo step.
- **Tests.** `tests/test_mvr.py` (+4: scenery where a fixture at its matrix hangs, for each
  audience; its scale; no GDTF imported; a file looked up in the archive only, and the caps),
  `tests/test_web_stage.py` (+11: scenery from a plot beside the show, none without a plot, an
  absolute plot, a model once with all its places and a 3DS without extension, missing,
  unreadable, changed, other formats, read again only when the file changed, an import undone
  served no more, what is served),
  `tests/test_web_api.py` (+2: the route with and without the key, an encoded name, 404 for the
  scene, a GDTF and `..`; a `LiveShow` end to end: the plot beside the show, a page that opens
  reading a changed plot, the open page getting the new rig), `tests/test_save_as.py` (+3).
  The whole suite: 7,564 passed. 26 mutations, each caught; one (the feed keeping the path of a
  plot that is gone) needed a test.
- **By hand**, in headless Chromium (WebGPU, 1600×900; the machine was busy, so frame rates
  are rough), through `LiveShow` with a web surface:
  - `Demostage_MVR.mvr` with `origin 0 -4000 1100` (its deck's downstage edge and top): 69
    models in 48 files, 29k triangles, all loaded. The deck, walls and trusses stand where the
    fixtures hang, and the floor units stand on the deck. Its models name a texture
    (`vsBlkSatinTexture.png`) that the archive does not hold: drawn without it.
  - Frame rates, with all 119 fixtures lit: still, 61–63 fps with the scenery against 50–52
    with busk's deck; 85 heads circling, 38–45 against 43–50. Before the two calls below on
    pools: 38 still and 32–33 circling. A profile showed the pools' raycasts (about 0.1 ms a
    beam) at 30% of the page's JavaScript.
  - `Circle_Stage.mvr`, default frame: 46 models, 88–113 fps; seen from above, the pools fill
    its risers' tops.
  - The plot moved away: the deck and the note. The plot rewritten: the note. WebGL 2 (WebGPU
    hidden, as on a phone over the LAN): the scenery draws.
- **Calls made while building**, open to veto:
  1. Files are served by name (`/stage/scenery/<file>`), not by number, so a `.gltf`'s buffers
     and textures resolve as MVR places them, beside it at the archive's root. Only models,
     `.bin` and images are served (`FILE_TYPES`), never a page or an SVG, since a plot is
     untrusted.
  2. With scenery, busk draws no deck, and no backcloth and no trusses of its own either: the
     plot has its own. The house (crowd, stands, PA, barrier, mix position) stays, on the
     scenery's floor. (Changed in Phase 6, §11: no PA, the house in front of the plot's stage,
     and none when the plot brings its own.)
  3. Pools land on the scenery (a raycast on its meshes) or the floor. A beam keeps its landing
     until it moves, and at most 24 moving beams a frame look again, those waiting longest
     first, so a pool may trail a fast beam by a few frames.
  4. glTF is read y up, as glTF says; both real plots stand their fixtures on their decks only
     that way. A 3DS file's own master scale is not taken, since MVR fixes 1 unit at 1 mm.
  5. The notes: `the plot … is not there`, `cannot be read (…)`, `has changed since the rig was
     imported`, `N models of the plot in a format busk does not draw`, and from the page `N of
     M model files of the plot did not load`. The plot is named as the show keeps it.
  6. A model is served only once a page has asked for the stage: until then the feed has not
     looked for the plot, and `/stage/scenery/` is 404.
  7. Models go out `no-store`, as every route: a page that reloads for a new rig fetches them
     again.
  8. A Save as rewrites `stage.plot` (call: the §11 finding's first remedy); an absolute path on
     another drive stays. A save to the show's own file never changes it.

### Phase 6: the user's check

11. **A real plot** from the user's CAD: import it, look at both stage views, change the plot,
    import it again. Findings go to §11.

## 9. Compatibility

- Shows without `stage` or `mvrUuid` load and run unchanged. `schemaVersion` stays 1, unless Q1
  (b), which migrates locations.
- A show imported from a plot runs anywhere: its profiles are embedded as always, and only the
  scenery needs the plot.

## 10. Risks

- **Exporters differ.** Vectorworks, grandMA3, Capture, Depence and others fill different
  optional fields: `FixtureIDNumeric` 0, no `Position`, no GDTF. Only a few real plots will test
  this.
- **GDTF on real files.** The importer has only been checked to import the OpenGDTFLibrary
  without errors. A plot brings fixtures the tests never saw.
- **Matrix conventions.** Whether u, v and w are rows or columns, and which way GDTF's pan turns,
  only show up on a real plot. The stage view in Phase 6 is where a mirrored or turned rig is
  caught.
- **Large plots.** The models of a whole venue can run to hundreds of megabytes, which tests the
  caps and the stage view's frame rate.

## 11. Found while planning

- **The two stage views disagree on x.**
  - `static/stage.html` maps busk to three.js with `world(x, y, z) = (x, z, −y)` and looks from
    the audience, so +x is on the screen's left. That is stage right, as `stage.py` documents.
  - F1 C's stage page (`busk_stage.py`, `stage_rows` and the centres at line 224) puts the
    smallest x on the left with the audience at the bottom. So +x there is house right, which is
    stage left.

  The TUI plan's "x right" (implementation-plan §3, item 6) can be read either way. A show with
  locations draws mirrored in one of the two views. Fixed in Phase 1: F1 C now draws it as the
  web view does.
- **A saved copy elsewhere loses the plot** (Phase 2). `stage.plot` is relative to the show
  file's folder, so Save as into another folder leaves it pointing at the wrong place. Before
  Phase 5 reads it, Save as should rewrite it, or the show should keep the absolute path too.
  Fixed in Phase 5: Save as rewrites it.
- **Undo across a Save as restores an old relative plot** (Phase 5). Undo is op-based, so
  undoing a later `rig import` made before a Save as into another folder sets `stage` back to
  the earlier import's, whose `plot` is relative to the old folder: the stage view says the
  plot is not there, and F3's picker opens elsewhere. Checked in a script. The next `rig
  import` mends it. Not fixed.
- **The spec's §5.17 never listed `safety`** (Phase 7's optional root key); Phase 2 added
  `stage` there and left `safety` alone.
- **A GDTF mode whose name ends in a space is never found** (Phase 4, on `Circle_Stage.mvr`: 8
  Robe Spiiders left out, `"Robe Lighting Robin Spiider" has no mode "Mode 8 - Pixel RGBW"`).
  The GDTF names the mode `Mode 8 - Pixel RGBW ` with a trailing space, which the GDTF importer
  keeps. The MVR reader strips the plot's `GDTFMode` (`mvr._text`), so `rig._mode` compares a
  stripped name with an unstripped one. Not fixed: comparing both stripped is one line.
- **The house stood in the plot's stage** (Phase 6, 2026-11-24, the user's test2.show from
  `Demostage_MVR.mvr`, imported with the default frame). The plot's origin is the middle of its
  deck on the floor, not busk's (the middle of the downstage edge at deck height), so its 12 × 8
  m deck stood at y −4…4 and z 0…1.1. The stage view built the house around busk's 0, sized to
  the fixtures' span (19.8 m, from the front of house truss): the barrier (y 2.2) and the first
  rows of the crowd (from y 2.8) stood inside the deck, and busk's subs (y 0.1…1.1, z 0…1.1) too,
  their tops on the deck's top, which flickered. busk's PA also hung beside the plot's own.
  The user's call: a plot must work as imported, with no frame to fix, and busk draws no PA with
  a plot. Fixed in the page alone: `stageOf` finds the plot's stage (the scenery standing on the
  floor, bottom under 3 m, top over 0.2 m, in blocks of parts within 0.5 m of each other, the
  block over the most floor) and the rig is drawn moved by `shift`, so that the stage's
  downstage edge is at busk's 0, in the middle; W and D come from the stage. Locations, the frame
  and F1 C are unchanged. Checked headless: test2 as saved, Circle_Stage with the default frame
  (its round stage stood 4 m into the crowd too), and festival.show, unchanged. Not handled: a
  plot that draws the venue's walls, touching the stage, may take the room for the stage.
- **A plot that brings the whole venue** (Phase 6, 2026-11-24, the user's
  key_arena_remake_mvr.show from `Key_Arena_Remake_MVR.mvr`, Capture 2022.0.30). The plot draws
  the venue as one closed box, 40 × 100 × 20 m with a roof, around everything, and its own house
  inside it: about 730 figures of a crowd, barriers, a mix position. `stageOf` took the box for
  the stage (it stands on the floor), so `shift` put the box's far wall at busk's 0: busk's
  crowd, stands and camera stood outside it, looking at a wall. The box's faces look out and are
  drawn on one side, so from inside it was not there. The user's call: the plot's own venue and
  house are drawn, busk's are not. Fixed in the page alone:
  - A shell, a part holding nearly every fixture and the middles of nearly all the other parts
    (90 %), is left out of `stageOf` and drawn with only its faces that look in, found by how
    they wind (`lookingIn`).
  - The stage is the block with the most floor under the rig (its parts with a fixture over
    them), then the most floor: the plot's crowd covered 272 m² against the stage's 346 m².
    Counting the fixtures over a block's parts was tried and dropped: Demoshow_grandMA3 hangs
    115 fixtures on a flat wall upstage.
  - Anything standing on the floor more than 2 m in front of the stage makes the house the
    plot's (`housed`): busk draws no barrier, mix position, stands or crowd.
  - busk's ground gives way to a floor at its height (a polygon offset): the box's floor, 1 cm
    above it, showed through it in stripes from afar.

  Checked on the user's seven plots: only this one has a shell or a house, and the other six
  find the same stage as before. Checked headless (WebGPU and WebGL 2) on it, on
  demostage_mvr.show and on festival.show. Not handled: a venue drawn as several parts (each
  wall its own) has no shell; a lone tower out in the house turns busk's crowd off. Also found:
  this plot's GDTFs are placeholders of another kind, every channel a plain `Dimmer`, so they
  import, and all 168 fixtures have intensity only.
- **Capture's plots carry placeholder GDTFs** (Phase 6, 2026-11-24, `Capture_Demo.mvr` from
  Capture 2023.1.6 and `Template_Stage1.mvr` from Capture 2024.0.34). Each of their ten GDTFs
  has the fixture's modes and channel counts and nothing else: every channel is an 8-bit
  `Dimmer<n>` with one unnamed function, under one geometry with no beam. No channel maps to
  a busk attribute, every mode is refused, and no fixture is added, which is right. The reply
  was not: each GDTF's refusal listed every channel of every mode (24,000 and 30,000
  characters), and `rig check` said `nothing to add` where `rig import` refused. Fixed: a
  fixture type with no channel busk knows is refused in a line, naming three of its attributes
  and counting the rest, in `profile import` too, and `rig check` says `no fixture busk can add`
  as the import does. With one real `Dimmer` channel in each GDTF, both plots import whole (76
  and 118 fixtures), so the scene is read right. Not done: letting the user give such a
  fixture type a profile of their own, so the plot's patch and positions still come in.
- **`--standalone` goes LATE while a plot is read** (Phase 4). The check runs on a worker
  thread of the TUI, which is the engine's process under `--standalone`, and reading a plot
  holds the GIL for about 0.1 s: the status bar showed `LATE`. A profile's preview does the
  same. Under `busk run` the engine has a process of its own, and the walks showed none.

## 12. After this

- Exporting a show as a plot. Only fixtures whose profile came from a GDTF can carry one.
- MVR-xchange: plots over the network (TCP with mDNS, or WebSocket).
- Focus points as position presets: pan and tilt from the fixture's location to the point.
- Multipatch fixtures; several DMX breaks (needs GAP-40).
- Taking a plot's newer GDTF revision, as `profile update` does.
- Using one of the show's own profiles for a plot's GDTF ("use my profile for this fixture
  type").
- The fixtures' own GDTF models and gels in the stage view; scenery on F1 C's stage page.
