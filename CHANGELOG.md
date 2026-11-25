# Changelog

All notable changes to busk are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and busk follows 0.x
[semantic versioning](https://semver.org/): a patch release only fixes, and a minor
release may break the public API, after a deprecation wherever possible. What counts as
the public API, and as a breaking change, is in [the library guide](docs/library.md#stability).

## [Unreleased]

### Added

- `busk run` opens its interactive prompt under busk's banner: a small rig whose lamps strike
  one by one over the `busk` wordmark, animated on a colour terminal (24-bit when `COLORTERM`
  says so, else 256 colours) while busk starts. It never holds the start-up: the processes start
  and the show loads meanwhile, and the first line busk prints brings it to rest at once.
  `BUSK_NO_ANIM=1` or `CI` shows it at rest at once, `NO_COLOR` without colour, and a terminal
  narrower than 38 columns gets one line. Ctrl+C before the run starts ends it with 130.
  Scripts, pipes and `--frontend` get none. The `busk` command now starts in `busk.launch`,
  which reads the options before the command line's imports. The
  `busk>` prompt has each letter of `busk` in its banner colour, where the terminal shows colour.
- `busk.banner_frames()` gives the banner as the frames of its animation, 30 a second by
  default, each 12 lines of 38 columns in 24-bit ANSI colours, for a frontend to play.
- F3 selects with a drag: from one row to another, it selects the fixtures of the rows it
  covers in one line (`sel fixture 101 thru 104, fixture 201`), and with Ctrl held it adds them
  (`sel + …`). The rows are lit while the mouse is down, and in edit mode the FIXTURE panel
  shows the row the drag ends on.
- F9 sets up bindings from controls. `[+ binding…]` on a MIDI or OSC surface opens a form in
  three parts: the control (on MIDI `cc`, `note` or `clock`, a channel and a number; on OSC a
  path), with a `[learn]` of its own that fills it from the next control moved; what it drives
  (`fader`, `button`, `master`, `tap`, `blackout`, `page`, `release all`, `output`, each with
  its fields, the masters as chips); and its feedback, on the control or on another. It says
  what is wrong before it sends (a channel, a number, a slot or a button out of range, a path
  without `/`). A binding's strip has `[edit…]`, the same form filled in, which changes it in
  one undo step; `[learn]`, which moves it to the next control moved on its surface, what it
  drives and its feedback kept; and `[delete]`, after a question, which takes it alone. A
  binding from a show file that `bind` cannot make has `[delete]` alone, and says why under
  the mouse. F9 no longer puts `bind`, `unbind` or `feedback` lines in the prompt, but for the
  surface's learn mode.
- One binding is deleted or changed alone, by its id, which `list bindings` prints and Tab
  offers. `delete binding <id>` deletes it, whatever its control: one of two on a control, a
  clock's, a pitch bend's from a show file. `binding <id> change …` takes what `bind` takes
  after the surface and gives the binding whole (`binding b-40d1 change cc 1 49 button 2 2
  led`), keeping its id and its surface: a binding moves to another control, drives something
  else or sends its feedback elsewhere in one undo step, and the control's other bindings stay.
  On a running show, a soft-pickup fader moved to another control or slot picks the level up
  again. `unbind "<surface>" clock` takes a clock's bindings.
- F9 sets up the control surfaces from controls. `[+ surface…]` opens a form: the kind's chips
  (MIDI, OSC, web), then for MIDI the devices plugged in to the console's computer as chips, or
  a device typed, and for OSC and the web remote a name, a port and where feedback goes or the
  address to listen on. It says what is wrong before it sends (an empty name, a name or a port
  another surface has). The chosen surface's strip has its pickup as two chips, `[soft]`
  `[jump]`, a click each, and `[edit…]`, the same form filled in, which moves the surface to
  another device or port on a running show; `[rename…]`; and `[delete]`, after busk's question,
  which counts the bindings that go with it.
- Surfaces are renamed, deleted and changed from the console. `rename surface "Phone"
  "Tablet"` renames one; `delete surface "<name>"` deletes one with no bindings, and one with
  bindings with `cascade`, which takes them and asks first at the prompt. `surface "<name>"
  change …` takes what `surface add` takes after the kind and the name, a MIDI surface's
  device or an OSC or web surface's port with its feedback address or host, and sets it
  whole, keeping the surface's name, pickup and bindings; a running show reopens the surface
  there. A MIDI surface renamed is still found by its device while no surface has that name.
- `busk.midi_devices()` lists the MIDI input devices plugged in, once each, as `surface add
  midi` takes them (`nanoKONTROL2`, without ALSA's numbers), and `()` without the `midi`
  extra.
- `rig import "<path>"` builds the rig from an MVR plot (My Virtual Rig, DIN SPEC 15801), as a
  lighting designer draws it in Vectorworks, grandMA3 or other CAD, in one undo step: the
  profiles of its GDTF files, the universes it patches into, each fixture with its number,
  name, mode, patch, invert pan and tilt and location, and a group for each hanging position,
  its fixtures stage right first. `rig check` says what it would do and what it leaves out,
  and changes nothing, counting the GDTF import's notes on each profile, which `rig import`
  lists. `origin` and `audience` place the plot on busk's stage; the last line
  of each reply is the fixtures' span in metres, which shows a wrong frame at once. The show
  keeps the plot's file and hash and the frame (`stage`), and each fixture the uuid of the
  plot fixture it came from (`mvrUuid`). Imported again, a plot brings the rig up to date in
  one undo step: the fixtures it gave the show follow its patch, mode or profile, location,
  name and inverts and keep their numbers and programming, its new fixtures are added, and
  those it lost are removed, as `delete fixture N cascade` takes them (`rig import … cascade`
  while anything uses them). A new mode that loses cells in use is refused. Fixtures added by
  hand and groups are never touched. See [Plots](docs/plots.md).
- The web stage view draws a plot's trusses, supports, set pieces, screens and projectors, read
  from the plot's file each time it opens, in place of busk's own deck and PA, and lands the
  beams' pools on them. The crowd stands in front of the plot's stage, sized to it, wherever the
  plot's origin is; a plot that brings its own house (a crowd, barriers, a mix position) gets
  none of busk's, and a venue drawn as a box around the rig is seen from inside. It says when
  the plot is missing (and draws the deck) or has changed since
  the import. Saving a show into another folder keeps the plot's path relative to the new file.
- The TUI imports a plot: F3's `[import plot…]`, or Import plot… in the File menu, opens the file
  picker on `.mvr` files, each previewed with what `rig check` says of it, starting on the plot
  the rig came from. The plot chosen opens IMPORT PLOT: busk's check, the frame on a first
  import (the audience's side as chips, the origin in a form, each change checked again),
  `cascade` ticked when the import removes fixtures that something uses, and `[import]`, which
  sends the `rig import` line. It does not run while the import would change nothing or busk
  refuses it, and says why.
- `OfflineShow.rig_check(path, *, audience=None, origin=None)` and `LiveShow.rig_check` say what
  `rig import` of a plot would do, as a `RigCheck`: the text `rig check` prints, whether the
  import is a first one, the frame it placed the plot through, and whether it changes the show,
  needs `cascade` or is blocked, and why. It changes nothing, and raises `ImportFailed` for a
  file busk cannot read as a plot. `busk run`'s show has it too.
- `OfflineShow.session` and `LiveShow.session` say whether the show has unsaved edits, the file
  `save` writes (an absolute path), what `undo` and `redo` would take back (how many steps, and
  the next one's label as `undo` prints it) and the counters that grow with each change to the
  show and to the programmer, as a `SessionStatus`, all of one moment. `busk run`'s show has it
  too.
- `busk.read_profile(path)` reads a fixture profile file as `profile import` does, without
  importing it: a `.gdtf`, an Open Fixture Library `.json` or a busk profile `.json`, told apart
  as a profile library tells them. It returns an `ImportReport` and raises `ImportFailed` for a
  file it cannot use, as `read_ofl` and `read_gdtf` do.
- The profile picker's `[import…]` (Ctrl+O) in the TUI is a file picker of three columns instead
  of a typed path: the folder above, the folder, and a preview of what the cursor is on. Folders
  come first; files busk does not import are dimmed, and hidden ones show while the filter starts
  with a dot. Typing filters, ← → go up and into folders, Enter chooses. The preview of a
  profile file is what busk reads in it: the maker, the name and each mode with the channels it
  takes, or why busk cannot import it. It starts where busk-tui runs, then on the file chosen
  last.
- A File menu in the TUI, behind the status bar's `busk ▾` badge (a click, or Alt+F): Save
  (Ctrl+S), Save as…, Import script…, Import profile… and Quit. Save as opens the file picker on
  the show's file name, in its folder, and saves a copy as a show of its own; it asks before it
  replaces another file. Import script opens it on the `.busk` scripts, with each one's first
  lines as its preview, and runs the one chosen as `source` does, as one undo step: each line
  goes to the log as it runs, with its place in the file (`festival.busk:812`) and busk's
  reply, a bar under the prompt says how far it is, and the log says at the end how many lines
  ran and whether one Ctrl+Z takes them back. Meanwhile the pages and the performance controls
  work, typed lines wait for it, and New…, Open… and Open recent… wait until it ends. Import
  profile opens the profile picker's file picker on the profile file chosen last, and imports
  the one chosen with `profile import`.
- The TUI keeps the shows it ran last, the copies Save as made included, in its `state.json`
  (`recent`: newest first, at most 10), for Open recent… and the launcher.
- The TUI's File menu opens another show: New… (Ctrl+N) asks for a title and a file and writes
  the show with `busk new`, Open… (Ctrl+O) opens the file picker on show files, with a preview of
  each one's title, size and save time, and Open recent… lists the shows it ran last. busk loads
  and compiles a show before it opens it, and refuses one that does not load, saying why. With
  unsaved edits it offers Save and open, Open without saving and Cancel; while a route sends, it
  says that the output stops while the next show starts.
- `busk-tui` with no show opens a launcher: the shows it ran last, newest first, with the same
  preview as Open recent…, a new show (n) and a show from a file (o). busk reads the show chosen
  first and refuses one that does not load. The show chosen runs as the show given, with the
  options given.
- In the launcher and in Open recent…, Delete or `d` forgets a recent show at once (its file is
  not touched), and a show whose last run did not end cleanly is marked `recovers`, in amber:
  its preview says when that run last wrote what comes back, and whether its unsaved edits come
  back with the programmer. With `--no-recover`, or `--standalone`, no show is marked.
- The TUI's File menu has Close: it ends the show that runs and goes back to the launcher, to
  choose the next show or quit, whether `busk-tui` was started with a show or without one. It
  asks first as Open… does: Save and close, Close without saving (x) and Cancel with unsaved
  edits, and that the output stops until a show is opened while a route sends. A show chosen
  after a Close starts without `--values` and `--script`.
- `run_script(path, each=…)` on `OfflineShow` and `LiveShow` calls `each(number, total, line,
  reply)` after each line of the script has run, before the next one: the line's number, the
  file's number of lines, the line and its `Reply`, so a display can follow a long script as
  it runs.
- `busk.pending_recovery(path)` says whether `busk run` would recover the show at `path`
  because its last run did not end cleanly, as a `PendingRecovery`: when that run last wrote
  what it is recovered from, and whether unsaved edits come back too; else `None`. It reads
  only the show's id, and takes `busk run`'s state directory (`state_dir`).

### Changed

- busk-tui's launcher is a box in the middle of the screen, about half its size (at least 80
  columns and 12 rows), with busk's banner playing above it; on a screen of fewer than 25 rows
  a one-line `busk` badge stands there instead.
- busk-tui's `busk ▾` badge and `busk>` prompt have each letter of `busk` in its banner colour
  (magenta, amber, cyan, blue); the badge is no longer cyan, and lights whole under the mouse.
- `busk-tui SHOW` stays as the parent of `busk run` instead of replacing itself with it, so that
  the TUI can end the run and have the next show started. Its exit code is still the run's (128
  + N when a signal N killed the run); it passes SIGTERM and SIGHUP on to the run, and leaves
  Ctrl+C to the TUI. `--values` and `--script` apply to the show given only. `--standalone` runs
  each show it opens in the same process.
- `save PATH` to another file than the show's own makes a new show: the copy gets a new
  `meta.id`, and `meta.created` of now, so its autosaves and crash recovery are its own, and
  the reply says so (`saved copy.show as a new show; club.show stays as it was saved`). A script
  that made a backup with `save backup.show` now makes a new show, and goes on in it.
  `OfflineShow.save(path)` and `LiveShow.save(path)` do the same. `save`, `save` to the show's
  own file and the first save of a show without a file keep the id. Under `busk run`, the
  autosaves follow the copy, so a crash recovers the copy and not the show it was saved from,
  and a console restarted after a crash comes back on the copy.
- The TUI reads the undo steps, unsaved edits and the show's file from `session`, no longer from
  the text of `info`.
- A script is one undo step: `source FILE`, `busk run --script FILE` and `run_script`. One
  `undo` after it takes back what all its lines changed, the show and the programmer, where it
  took back its last line (`undid: source build.busk`), and a script longer than the 1,000
  steps the history keeps no longer pushes the steps from before it out. A script that stops
  at an error leaves one step for the lines that ran.
- A GDTF file with no channel busk has an attribute for, as the placeholder GDTFs in Capture's
  MVR plots (every channel a `Dimmer1`, `Dimmer2` …), is refused in one line that names three of
  them and counts the rest (`no channel has a busk attribute (Dimmer1, Dimmer2, Dimmer3 and 36
  more)`), by `profile import`, `busk import gdtf` and `rig import`. The refusal listed every
  channel of every mode.

### Fixed

- busk-tui's current page tab and F1's shown layout read dark on cyan: Textual's link colour
  painted their text white. The other tabs draw their F-key in cyan and their name in grey, as
  meant, and F1's layout names are no longer underlined.
- The TUI added to the selection on a Shift-click (fixtures on F1, F3 and F8, group buttons on
  F1 and F2), which kitty, xterm and most other terminals keep for their own text selection, so
  it never arrived. Ctrl-click now adds or takes out, and so does Alt-click; Shift-click still
  does where the terminal passes it on. The hints say Ctrl.
- `bind` took a MIDI channel outside 1 to 16 and a CC or note number above 127, which never
  fire, and `display` feedback on MIDI, which has none, in silence; and a control the surface
  cannot send (`osc` on a MIDI surface, any control on the web remote) with a warning by
  path. Each is refused in words, and Tab offers the surface's own controls alone; `unbind`
  and `feedback` refuse the ranges too. A show file that holds such a binding still loads,
  with a warning.
- A GDTF file whose `description.xml` ends in NUL bytes after its last element, as some
  exporters write it, is read: `profile import` and a profile library refused it as not
  well-formed XML. So is an MVR plot from the same exporters. A NUL anywhere else is still
  refused.
- The TUI's stage (F1 layout C) drew the rig mirrored: stage right (positive x) was on the
  right. It is now on the left, as the audience sees it and as the web remote's stage view
  draws it. Saved locations are unchanged.
- An edit made less than half a second after a save, under `busk run`, was taken as saved: it
  was not autosaved, and quitting did not keep it in an autosave.
- `save "<path>"` reads the escapes of a quoted path (`\"`, `\\`) as `source` and `profile
  import` do; it kept them, and saved to another file than the one named. An unquoted path is
  read as before, spaces and all.

## [0.1.2] - 2026-11-19

### Added

- What comes in from the control surfaces: `LiveShow.inputs` gives the newest 64 inputs, bound
  or not, each a `SurfaceInput` with a sequence number, its surface, its control as `bind` takes
  it (`cc 1 48`; a pitch bend `bend 1`), the number the device sent (`raw`: a CC's value, a
  note's velocity, a pitch bend's pitch), the value the bindings got and what its bindings drive,
  as `list bindings` prints it. `busk run`'s show has it too. `list bindings` words a pitch-bend
  binding `bend 1`, not `midiPitchBend 1`. F9 has a MONITOR panel, the last 14 inputs with a
  fader's moves on one line; BINDINGS an `in` column, the last number each control sent, beside
  `val`; and learn mode: `[learn]` on a surface, then a control moved on it, puts `bind
  "<surface>" cc 1 48 ` in the prompt, and the hint row says what the control drives already.
- Undo groups: after `undo group "pan drag"`, programmer changes are one undo step, labelled
  `pan drag`, until `undo group end`; a show edit, `undo`, `redo`, another group or 2 s with no
  change closes it too. Changes from surfaces and the web remote join it; performance lines do
  not. The commands are `UNDO_GROUP` and `UNDO_GROUP_END` (`UndoGroupCmd`, `UndoGroupEndCmd`).
  F2's encoder drag is now one undo step, and Ctrl+Z and Ctrl+Y undo and redo in the TUI.
- Timing per target: `cue 9/1 time group 2 intensity 2 delay 0 to 1.5` sets the own timing of the
  cue's intensity entries on group 2, and its `to` makes a fan, so the washes come up one after
  the other; `to` on the fade fans the fade, and `center` or `edges` shape the fan as they shape a
  spread. Fixtures are named as a list, in any order (`fixture 104, 105`), and `… none` takes the
  timing away. A fan on a group follows the group as it grows. In the show file, an entry's
  `timing` gains `fadeTo`, `delayTo` and `fan`. `list cues` shows each entry's own timing after
  its families', as the line takes it (`time 3 easeInOut, group 2 intensity 2 delay 0 to 1.5`).
  F4's TIME dialog sets it: after a family, its `on` chips are `[all]` (the family's own timing)
  and the targets the cue's entries of that family are on (`[Heads]`, `[301]`); on targets, the
  fade and the delay each have a `to`, then `[linear]` `[centre]` `[edges]`, and `[none]` takes
  their timing away. The time cell counts the targets with timing of their own (`3, +1 own`).
- An effect template keeps defaults: `effect template defaults "Circle" hz 2 size 30 phase 0 360`
  sets what `effect add "Circle"` starts from (everything it takes but the id, masters too), and
  `… none` takes them away; a line's own words still win. `list effects` and `EffectTemplateInfo`
  show them (`EffectTemplateInfo` gains `hz`, `bpm`, `direction`, `fadeIn`, `sizeMaster` and
  `speedMaster`). Adding a library template copies its defaults into the show, and `delete
  master` is refused while a template's defaults name the master. F5's EFFECT panel has `[keep as
  defaults]`, which makes the effect's settings its template's defaults, so a click in TEMPLATES
  adds it as you settled it; the TEMPLATE panel shows them, with `[none]`.
- A template's wave layer runs several waves in one cycle of its effect: `"cycles": 2` in its
  JSON, a whole number from 1 to 100, so tilt can move at twice pan's rate. `list effects` and
  `library` word it (`tilt add sine ×2 +90°`); the layer's phase offset is in degrees of its own
  wave, and the strobe cap counts each wave. The effect library has five more templates: Figure
  eight, Tilt sweep, Wander (pan and tilt at random), Square (an intensity square chase) and
  Alternate (red and blue on every other fixture, `groups 2`). A library template's defaults may
  now give groups, blocks and wings, and `EffectTemplateInfo` has them. F5's TEMPLATE panel has
  `[cycles…]` on a wave layer.
- F4 has a TRACK panel under the cue table: what the chosen cue puts on stage when its list plays
  by GO from its first cue, a row per fixture and a column per family. A value the cue stores is
  bright, one it tracks from an earlier cue dim, with that cue after it (`██ Blue ← 9/1`), and a
  release is `✕`. With the mouse on a cell, the hint row says it in words (`201 color Blue,
  tracked from 9/1`). F4's `[block]`, lit on a block cue, sends `cue 9/3 block on` or `off`.
- `list cue L/C` prints what a cue puts on stage when its list is played by GO from its first
  cue: a line per fixture (per element where a fixture's elements differ) with each value, `←
  9/1` after one tracked from an earlier cue, then what the cue releases and its effects.
  `OfflineShow.tracking(L)` and `LiveShow.tracking(L)` give the same for every cue of a list, as
  `TrackedCue`s with `TrackedValue`s and `TrackedEffect`s, read from the compiled show. `cue L/C
  block on|off` makes a cue track nothing from the cues before it, or track again, in one undo
  step with a reply in words, and `list cues L` marks a block cue `block`.
- The web remote shows the stage in 3D: the **3D** button in its header opens a view of the
  show's rig above the strips (beside them on a phone held sideways), lit by what the engine
  outputs (intensity, colour, shutter and strobe, pan, tilt and zoom), with beams in haze and
  an arena sized to the stage. Its buttons make it full screen or open it in a tab of its own
  (`/stage?k=…`). Each fixture stands where its `location` puts it, or in a row with the others
  of its kind; moving, patching or adding one redraws the view. While it is open on a narrow
  or short screen, the masters fold behind the **Masters** button. It loads three.js from the
  internet the first time; the rest of the remote still needs none.
- F2's panels have an option row per attribute set to a named option (gobos, prisms, the colour
  wheel, colour macros, fixture effects, the shutter) while the selection offers options for it:
  a chip per option sends `set gobo1 star`, and the first selected element's option is lit.
  SHUTTER's `[set shutter…]` gave way to its row. F7's PANIC shows the strobe cap (`strobe cap 3
  Hz`, or `off`), with `[cap…]` (`safety strobe 3`) and `[off]` (`safety strobe off`). A click on
  the status bar's title renames the show (`rename show "…"`).
- `rename master "<name>" "<new name>"` renames a master, and refuses a name another master has,
  in any case. `delete master "<name>" [cascade]` deletes one, and is refused while a cue's effect,
  a cue list's chase or an effect in the programmer names it, saying which; a binding that drives,
  taps or names it needs `cascade`, and goes with it after the question. The grand master is
  neither renamed nor deleted. Each is one undo step. F7 has a MASTERS panel: `[+ master…]` makes
  a speed, size, group or fade-time master from a form, and each master but the grand one has
  `[rename…]` and `[delete]`.
- `list dmx U [A [thru B]]` prints what busk sends on a universe's channels, 16 values to a line,
  as the engine's last frame has them, after the masters, park, blackout and limits.
  `list dmx fixture N` prints each channel of a fixture with its function in its mode (`pan`,
  `pan fine`, `red`, `Cell 2 red`) and its value. `list universes` counts the channels the
  fixtures take and the pairs of fixtures that overlap. On F8, the hint row names the function of
  the channel under the mouse and its value, and a CHANNELS panel under the maps lists the
  selected fixture's channels, with their values, 10 times a second.
- `load cue L/C [only <family>…]` puts what a cue stores into the programmer, in place of what it
  holds, and selects its fixtures, in one undo step: a preset as the preset, a group's value or a
  spread as each fixture's value, and the cue's effects with their ids. A cue of a tracking list
  brings its own changes, not what it tracks. `record cue L/C replace` then records the edit back.
  An entry's own timing does not come, and the reply says so. F4 has `[load]` for the chosen cue,
  which asks first while the programmer holds values or effects.
- F4's cue table has an `also` column: how many entries a cue holds of each family the intensity
  and colour columns leave out (`position 2, beam 1`; a colour wheel or a CTO counts as `color`),
  so a cue that only moves the heads no longer looks empty. From 150 columns it shows where the
  curve was, which `[curve…]` still shows; from 160 both show.
- `cue L/C number M` moves a cue past its neighbours: the cue goes to its place in the list's
  order, in one undo step, and a playback on it stays on it. `cue L/C copy M` copies a cue in its
  own list and `cue L/C copy L2/M` into another, at its place there, with a new id and the rest as
  the cue has it. A number the list has is refused. F4 has `[number…]` and `[copy…]` for the
  chosen cue, and `[number…]` for the list shown, each a dialog that refuses a number taken.
- `cue L/C time <family> none` takes a family's own timing away from a cue, its fade, delay and
  curve, so the family fades with the cue again. One undo step; a family with no timing of its own
  is refused in one line. F4's TIME dialog has a `[none]` (or Ctrl+N) that sends it, while a family
  with timing of its own is chosen.
- F4 edits a cue's timing, trigger and name in dialogs, where a click put the start of a line in
  the prompt. A click on a cue's time, delay, curve, follow or wait cell, or `[time…]`,
  `[delay…]`, `[curve…]`, `[follow…]`, `[wait…]` and `[rename…]` under the table, opens a dialog
  filled in with what the cue holds. It sends one line, `cue 9/3 time 1/3 delay 0/1`, and nothing
  when it is left as it was. `[time…]` sets a family's own fade and delay too, keeping its curve,
  and `[curve…]` takes a Bézier's four points. `[go…]` still puts `cue 9/3 go` in the prompt.
- F8's `[edit…]` changes a route: the route form, filled in with what the route holds, sends `route
  <id> change …`, which keeps its id and whether it is on. A form that changes nothing sends
  nothing.
- F3's `[delete]` and PATCH act on the selection while it is one run: `delete fixture 101 thru 104
  cascade` and `fixture 101 thru 104 patch 1.85`, one line and one undo step each, and PATCH places
  the run from its first fixture. With a fixture left out between the selected ones, both are grey,
  and PATCH says what `thru` would take as well.
- The profile picker imports a profile: `[import…]`, or Ctrl+O, then a path, sends `profile
  import`, and the list lands on the new profile. busk's refusal shows in the picker. F3's FIXTURE
  panel has `[update profile]`, live when the library holds the profile at another revision.
- F3's edit mode edits groups and park from controls. A GROUPS panel under the table has a row per
  group with its members; a click chooses one and keeps the selection. `[record…]` makes a group of
  the selection, `[merge]`, `[replace]` and `[remove]` change the chosen one with it (the last two
  ask first, and each is grey while it would change nothing), and `[rename…]`, `[number…]` and
  `[delete]` (busk's question) are there too. The FIXTURE panel has a PARK section: what park holds
  on the fixture, and `[park…]`, a form of an attribute and a value, which reaches the selected
  elements, so one pixel of a bar can be parked.
- F7 has a PARKED panel: a row per value park holds, each with `[unpark]`, and `[unpark all]`, after
  a question.
- F3's source column reads `park`, in amber, for a parked value, before anything else that drives
  it, and its legend says so.
- F1's edit mode adds, places and deletes playbacks, and manages pages, from controls. A click on a
  slot takes it in hand: `[new playback…]` on an empty one asks for a cue list, a number and a name;
  `[place…]` puts any playback on it from a picker that says where each one sits; `[clear]` empties
  it. The PLAYBACK panel has `[delete]`. Over the grid are a tab per page, `[+ page…]`, and the shown
  page's `[rename…]` and `[delete]`. Each is one line, and the deletes ask busk's question.
- F1 edits a playback from controls. `[edit]` puts a grid of the page's slots and a PLAYBACK panel in
  place of the layout: its name and number, cue list, buttons, fader, band, exclusivity, flash level,
  LTP and boost, LTP mode and threshold, auto start and release, goto cue, swop protection, release
  time and colour, each one control and one line. The grid performs nothing.
- F1's strips have each playback's own buttons, in place of the fixed GO, ◂ and FLASH: one per entry
  of its `buttons`, labelled by function, in all three layouts (layout C has room for the first).
  Each runs `button N B on`, `flash` and `swop` are held while the mouse button is down, and one
  that would do nothing is grey. `[record]`, on an empty slot, runs `record slot P.S`. Space still
  runs `go` on the selected playback.
- F5 edits effect templates from controls. `[+ template…]` makes one, and `[edit]` on a template
  opens its TEMPLATE panel, with a row per layer: a wave layer's attribute, mode, waveform with its
  parameters and phase offset, and a colour layer's blend and palette of colours and presets. Each
  change is one line and one undo step, `[rename…]` and `[delete]` are there too, and a refusal
  shows in the panel as well as the log. A library template opens read-only.
- F5 edits an effect from controls. A click on a row opens its EFFECT panel, with the rate (in Hz or
  on a master's beat), direction, size, levels, phase, groups, blocks, wings, fade-in, and size and
  speed masters, each one control and one line. `✕` removes an effect from a cue, after a question,
  and `[clear]` removes every programmer effect.
- F4 edits cue lists from controls. A cue's row has `[release…]`, `[record at…]`, `[merge]`,
  `[replace]`, `[remove]` and `[delete]`, and a list's row has a tracking toggle, `[chase…]` (a form
  for the rate, master, multiplier, direction and crossfade), `[rename…]` and `[delete]`.
  `[+ list…]`, under CUELISTS, adds one.
- `route <id> change <what route add takes>` edits a route in one undo step. It keeps the id and
  whether the route is on.
- `fixture N thru M patch U.A|none` places or unpatches a run of fixtures, each after the one
  before by its footprint, and `delete fixture N thru M cascade` deletes one. Each is one undo step.
- `profile import "<path>"` embeds an OFL `.json`, a `.gdtf` or a busk profile file in the show, in
  one undo step.
- `FixtureProfileInfo` has `revision` and `library_revision`, so a display can tell when `profile
  update` has something to do.
- `FixtureOutput.source` says `"park"` for a family that park holds, and `playback` is `None` then.
- `delete preset <pool> N cascade`, `delete group N cascade`, `delete cuelist N cascade`, `delete
  playback N cascade` and `delete page N cascade`, each one undo step. What names the entity
  leaves it or goes with it, and the question says what would go and when a playback runs. A cue
  list takes the playbacks that run it. A plain `delete` of a fixture, universe, preset, group, cue
  list, playback or page in use is now refused in one line that counts what uses it.
- `effect template delete "<name>"`, `effect template rename "<name>" "<new name>"` and `effect
  template update "<name>" <JSON layers>`, each one undo step. A delete is refused while a cue, a
  binding or the programmer uses the template, and says which. All three act on the show's own
  templates.
- `cue L/C effect <id> remove` removes one effect from a cue by its id. The cue stays.
- `cuelist add N ["name"]` makes a cue list with no cues.
- `playback add N cuelist L [at [P.]S] ["name"]` makes a playback on a list that exists, placed on
  a page in the same undo step. `playback N cuelist L` points one at another list by number, and
  is refused while it runs.
- `help`, Tab and `?` name a playback's and a cue list's properties and the values of those with
  a closed set. `<property> none` removes an optional one, such as `playback 3 exclusivity none`.
- F6's `[delete]` also takes a preset that cues or effect palettes use, after busk's question.
- F6 edits presets from controls. `[edit]` or a `+ record` tile opens the PRESET panel: what a
  preset holds and the cues that use it, rename, renumber, delete after a question, and new
  presets and new values recorded through the programmer. Its editors are the encoder rows, a
  colour picker (a hue × saturation field and named chips), option chips for gobos, prisms,
  shutters and fixture effects, and spreads. Every pool the rig can record into now shows.
  Under SELECTION, a hint says what the scope lit keeps, and a row no profile of the show takes
  shows dimmed.
- F3 and F8 edit the rig from controls. F3's `[edit]` opens the FIXTURE panel: rename, renumber,
  delete after busk's question, the mode, the profile and its category, the patch, limits,
  orientation and location. `[+ add]` adds fixtures, one or a block, with a picker of the show's
  and the library's profiles. F8 adds, renames, renumbers and deletes universes, and adds, switches
  and deletes routes. A click on a free channel of its maps arms a place, to patch the selected
  fixture there or add a new one.
- `route <id> on|off` and `delete route <id>`. A route is named by its id, as `list routes`
  prints it, and Tab offers the ids. `route <id> off` and `delete route <id>` ask first at
  the prompt, as `output off` does.
- `delete fixture N cascade` and `delete universe N cascade`, each one undo step. A fixture
  leaves everything that names it, and a universe unpatches its fixtures and removes its
  routes. The prompt always asks first and says what would go. A plain `delete` is still
  refused while anything uses what it deletes.
- `fixture N [thru M] limits pan|tilt|intensity none` removes one limit and keeps the others,
  and `fixture N location none` removes a location.
- `fixture N [thru M] orientation.<key> <value>` sets one orientation key on every fixture of a
  span, in one undo step, and Tab offers the keys. F3 sends it, so four heads are one `undo`. The
  line reads its numbers as `limits` does, so `orientation.panOffset 1e2` is no longer taken.
- `fixture N mode <mode>` and `fixture N profile "<profile>" mode <mode>` change what a fixture
  runs, by name, each in one undo step. The profile is found as `fixture add` finds it, and a
  library profile is embedded with the line. Tab offers the profiles and their modes.
- `OfflineShow.fixture_profiles` and `LiveShow.fixture_profiles` list the profiles `fixture add`
  takes, the library's too, with each mode's footprint and elements: two new public types,
  `FixtureProfileInfo` and `FixtureModeInfo`.

### Changed

- A spread recorded on a group follows the group: `record cue` finds values that are a spread
  over a group's members (`set pan spread -30 30 center` on group 1) and stores the spread, where
  it stored a value per fixture, so a head that joins the group later takes its place in the fan
  and the others move. Only a spread that gives each fixture exactly the value it had is stored,
  so the cue plays the same; other values, a list of fixtures and `freeze` stay per fixture.
  Different values on a group of two are always a spread. `load cue` then `replace` keeps a spread.
- `record cue … replace` and `merge` keep an entry's own timing when they record the same targets
  and attribute again, where they dropped it, so a cue loaded, edited and recorded back keeps it.
  `load cue`'s note says so.
- Lines that work reply in words, where they named the show document's paths: every rename
  (`renamed group 1 "Heads" to "Movers"`), every `number M` (`group 1 is now group 9`), a plain
  `delete` (`deleted cue 9/2 "Verse"`), `cue L/C time`, `follow`, `wait`, `go` and `release`
  (`cue 9/3 goes 8 s after the cue before starts`), `cue L/C effect <id> <prop> <value>`,
  `cuelist N sequence` and `chase`, the properties of a playback or a cue list (`set the priority
  of playback 3 to 60`), `playback N goto`, `fixture N location {…}` and `surface "<name>"
  pickup`. `undo` and `redo` repeat the words, and the TUI's log shows them. The generic edit
  (`show meta.title "…"`, `cue 3/1 timing.fadeIn 1`) and a command submitted to the session still
  name the path they set.

### Fixed

- `cue L/C effect <id> <property> <value>` refused a value the effect could not hold with the show
  document's path (`cueLists[10].cues[0].effects[0].groups: Input should be greater than or equal
  to 1`) under its reply. It now refuses it in one line that names the property: `effect fx1 in
  cue 11/1: groups should be 1 or more, got '0'`, `effect fx1 in cue 11/1: the size must be a
  finite number of 0 or more, got -1`, `effect fx1 in cue 11/1 has no property 'colour'`.
- `effect add "Circle" groups 0` was taken into the programmer, though a cue cannot hold such an
  effect, and `blocks 0` or `wings 0` gave `internal error: ZeroDivisionError`. A rate or a
  multiplier of 0, a size below 0, and 0 groups, blocks or wings are now refused in one line, in
  words (`expected a number of groups from 1, got '0'`), where a rate and a size were refused with
  a path under the reply.
- `safety strobe 50%` set a strobe cap of 0.5 Hz and `safety strobe +4` one of 4 Hz, and `safety
  strobe 0` or `-1` was refused with a document path (`safety.strobeMaxHz: …`). A cap is now a
  plain number of Hz above 0, with no sign and no `%`, as a tempo is; anything else is refused in
  one line: `expected a rate above 0 Hz, or off, got '50%'`.
- F2's PROGRAMMER CONTENTS put the end of a long `other` cell on a line of its own, under the
  fixture's number, on a narrow screen (99 columns, with `gobo1 breakup`). The other attributes
  now take as many lines as they need, each under their column, laid out again at a resize.
- `master add speed … bpm 0` (or above 999) and `steps 0, 1` were refused with a document path
  (`masters[1].defaultBpm: …`), and `bpm 50%` made a tempo of 0.5 BPM, at `master add speed` and
  at `bpm ["<master>"]`. A tempo is now plain BPM, above 0 and at most 999, and a multiplier step a
  plain number above 0, each with no sign and no `%`, as busk reads seconds; anything else is
  refused in one line: `expected a tempo above 0, up to 999 BPM, got '50%'`.
- `fixture N mode`, `fixture N profile` and `profile update` were refused with one document path
  per element when something named an element the new mode lacks: 22 lines of
  `groups[2].members[1].element: …` for the club show's bar. They are refused in one line now,
  which names what uses them: `fixture 301 cannot run RGB Par 3ch, 3ch: groups 3, 4 use elements
  it would lose`. F3's mode chips and `[profile…]` show that line.
- `route add` and `route <id> change` with an Art-Net net past 127, or a sub-net or universe past
  15, named the document (`output.routes[1].portAddress.net`). They now say it in one line:
  `expected an Art-Net net from 0 to 127, got 200`.
- A family's fade and delay (`cue L/C time <family> …`), a trigger's delay (`follow`, `wait`), the
  programmer's `fade`, `release N` and `release all` times and an effect's `fadein` took `50%` as
  half a second, and a sign: `fade -1` set a fade of minus a second, and the others were refused
  by document path. They now read seconds as the cue's own times do, with no sign and no `%`, and
  say so in one line. A Bézier control value is read the same way, from 0 to 1 (`expected a Bézier
  control value from 0 to 1, got '2'`). Only the console's reading changed: show files load as
  before.
- `fixture N mode <mode>` with the mode the fixture runs, and `fixture N profile` with its profile
  at the same revision and mode, spent an undo step that changed nothing. They are refused now:
  `fixture 101 already runs 16ch`.
- F5's state toggle and `✕` failed on a programmer effect whose id is two words (`id "my fx"`):
  they sent the id bare. They quote it now.
- F4's `[chase…]` form started its crossfade field at six digits, so a crossfade of `0.1234567`
  went back as `0.123457` when the form was taken as it opened. It keeps every digit now.
- With `--faders` below a page's slot count, F1's edit mode showed every slot, but ← → stopped at
  the first `--faders` playbacks, and a change of the page's slots moved a selection past them to
  the first. In edit mode they now use every slot, as the grid does.
- F4's toggle from a sequence back to a chase rounded the list's rate and multiplier to six digits
  and its crossfade to two, and was refused on a speed master with a quote in its name, so the list
  stayed a sequence. It now sends the chase settings as busk stored them.
- F1's `[GT]` stayed live when the playback's goto cue was not in the list it now runs, and a press
  did nothing. It is grey then, and the hint row says why: `goto: cue list 11 has no cue 4`.
- F6's `[replace]` and `[remove]` changed a preset without a question. They ask first now, as F4's
  and F3's do.
- `go` on a playback whose cue list has no cues replied nothing and marked it active on no cue.
  It is now a refused line that says so.
- A name in quotes with a bad escape (`"back\slash"`) or a control character raised
  `JSONDecodeError` out of `execute`, `expected`, `confirmation` and `run_script`. It is now a
  refused line that names the column.
- A digit that `int` cannot read (`²`, `①`) in an Art-Net address, a surface's port or a `bind`'s
  page raised `ValueError` out of the same calls. At the prompt it ended `busk run --threads`, and
  restarted the console with processes. It is now a refused line. `busk import` raised the same on
  an OFL pixel key such as `1²2`, sorted for `eachPixelABC`.
- A number past 4,300 digits raised `ValueError` the same way, from a line and from `submit` with
  a `GOTO`, and a show file holding such a cue number raised it out of `load_show`. A line with more
  than 300 digits in a row is now refused, and a cue number takes at most 300 on each side of its
  point, so such a file fails with `ShowLoadError`. `fade` no longer takes a number that long as an
  endless fade, which kept the programmer's values from reaching the output.
- A refusal at the prompt named the document, not the rig: `fixture add` past channel 512 printed
  a path for each fixture, and `fixture N number M` and `universe N number M` named `fixtures[7]`
  and `universes[1]`. These lines and `fixture N patch` now say it in one line: `fixture 900–903
  would end at channel 575, past channel 512`, `fixture 102 exists`.
- More refusals named the document: `N number M` on a group, cue list, playback, page or preset,
  `cue L/C number M`, `route add` with an sACN universe outside 1 to 63999, and a mode or profile
  that takes a patched fixture past channel 512. Each now says it in one line: `group 2 exists`,
  `cue 1/2 exists`, `expected an sACN universe from 1 to 63999, got 0`, `fixture 3
  would end at channel 524, past channel 512`. A cue's number no longer needs quotes:
  `cue 1/1 number 1.5`.
- The TUI's log cut a line at the pane's edge. A long line now wraps at its words, the later rows
  under the text and not the prefix, and a resize flows the log again.
- F1 layout C's `[location…]` filled the prompt with a line of JSON to finish. It now opens the
  same form of six values as F3's FIXTURE panel.
- `fixture N thru M` before anything but `limits` and `orientation.<key>` read as a property called
  `thru`. It now says `expected limits or orientation.<key>, got 'patch'`.
- Fixture numbers start at 1, as universe numbers do. `fixture add 0` and `fixture add -5` worked.
  They are now refused. A show file holding such a number loads, with a warning.
- `hz` on a DMX-USB route took any number, and the widget then kept it to 1–40 without a word, so
  `list routes` said `0 Hz` of a route sent at 1. `route add` now takes 1 to 40. A show file with
  `refreshHz` from 41 to 44 loads with a warning and runs at 40, and one below 1 or past 44 fails
  with `ShowLoadError`.
- `programmer` printed `fx-… (gone)` and `preset pr-… (gone)` for what had been deleted, and
  `selection: 1, 1, 1` for the elements a new mode lacks. It now lists what `LiveShow.programmer`
  lists: the rest is dormant, and comes back with `undo`.
- A TUI button whose look alone changed was not redrawn: a lit scope or curve, `[−]` `[+]`
  turning active, F5's `RUN` dimming.
- A name the TUI sent to busk was written bare between quotes, so `C:\new` reached busk with a
  newline in it, `back\slash` raised, and a double quote was refused. Names now go out escaped, as
  busk reads them.
- A TUI question read the name in it as markup: `x[/]y` ended the TUI, and `[left]` vanished. A
  long question was cut at the box. Both are fixed, and a question now wraps.
- A TUI number dialog raised on a digit such as `²`, and on a paste past 4,300 digits, which ended
  the TUI. Both are refused there now, and so is any number past the 300 digits busk reads.
- F3's dialogs sent a number of 1,000,000 or more as `1e+06`, which busk refuses for an offset or a
  limit, and rounded one from 100,000 on to six digits: a location's x of 1234567.5 was stored as
  1234570. Numbers now go out with every digit, to two decimals.
- `route add` took the same route twice: `route add 1 sacn 1` three times gave three routes that
  sent the same. It now says `the same as route r1 of universe 1`, also while that route is off.
- A show file whose per-target value named an element past 4,300 digits raised `ValueError` out of
  `load_show`. It now fails with `ShowLoadError`, as an element past 300 digits does.
- `record cue … remove` replied with what the cue still held, so taking the only effect out of a
  cue said `removed from cue 90/1: 0 entries, 0 effects`. It now counts what it takes out, as
  `record preset … remove` does: `removed 0 values, 1 effect from cue 90/1`.

## [0.1.1] - 2026-10-27

### Added

- `busk-tui`, a terminal UI, behind the new extra `busk[tui]`
  ([the terminal UI](docs/tui/guide.md)). `busk-tui SHOW` runs the show under `busk run` as
  its frontend, with a status bar that follows the engine (routes, grand master, tempo,
  programmer, blackout, output, page, engine health), the console prompt with hints and Tab
  completion, a log of every line run and what busk answered, a help overlay, and the
  engine's question before `output off`. `--standalone` runs the show in the TUI's own
  process, for development and rehearsal. F1 plays the current page's playbacks (levels in
  their cue's colour, cue and next cue, GO, BACK, a momentary FLASH; Space, ← →, `[ ]` and
  PgUp/PgDn on an empty prompt) with the tempo, the masters, the running effects and the
  selection; F2 selects groups, sets and steps attributes with encoders that show the
  programmer's or the output's value, runs configurable quick lines and lists the
  programmer's contents; F4 browses the cue lists, goes to a cue, records one, switches a
  list between sequence and chase, and puts a cue's timing edits in the prompt; F5 lists the
  cues' and the programmer's effects with their live state and wave, and adds, stops, runs
  and removes programmer effects from the show's and the library's templates; F6 applies
  presets from tiles; F7 has every master and the panic controls; F3 lists every fixture with
  its patch and live output, coloured by what drives it; F8 shows the universes, the routes
  with their state and packet rate, and a DMX map per universe with its overlaps; F9 shows
  the control surfaces with their state and the bindings with the level of what they drive.
  F1 has three layouts, chosen in its header or with `--layout` and remembered: the stack,
  the console (the rig's live output by fixture type, the programmer, vertical faders) and
  the stage (the fixtures placed by their `location`, in their live colours, with the
  movers' pan and tilt).
- `OfflineShow.output` and `LiveShow.output`: the engine's output read back per fixture
  element, as two new public types, `OutputSnapshot` and `FixtureOutput`
  ([the library guide](docs/library.md#2-build-a-show-and-render-it-offlineshow)). Each
  element has its intensity, colour, pan, tilt and zoom in the show's units, after the
  masters and the safety stage, what drives each family of its attributes (the
  programmer, a playback, an effect or nothing) and the playback that drives its
  intensity. A `LiveShow`'s engine reads its output back only once `output` has been read.
- `OfflineShow.effects` and `LiveShow.effects`: the effect instances the engine runs, the
  playbacks' and the programmer's, as two new public types, `EffectSnapshot` and
  `EffectStatus` ([the library guide](docs/library.md#2-build-a-show-and-render-it-offlineshow)).
  Each instance has its playback, the cue that defines it and its id, how far it has
  faded in, its size and rate now, its phase, and the next cycle of its waveform or its
  colours in 20 samples, for a sparkline. As with `output`, a `LiveShow`'s engine reads
  its effects back only once `effects` has been read.
- `OfflineShow.programmer` and `LiveShow.programmer`: the programmer as a display shows it,
  as two new public types, `ProgrammerStatus` and `ProgrammerValue`
  ([the library guide](docs/library.md#2-build-a-show-and-render-it-offlineshow)): the
  selection as fixture numbers and elements, each value in the show's units (a preset
  reference with the preset's value for that element, and its pool, number and name), the
  effects, blind, highlight and the fade time, and a `version` that grows when any of
  them changes.
- `LiveShow.routes`: the show's output routes as a display shows them, as a new public
  type, `RouteStatus` ([the library guide](docs/library.md#3-live-inside-your-own-application-liveshow)):
  each route's state (`ok`, `failed`, `disabled` or `ignored`), why it failed or is
  ignored, and the packets and errors it has counted. The same news as the `sACN r1: …`
  log lines, as data.
- `LiveShow.surfaces`: the show's control surfaces as a display shows them, as a new
  public type, `SurfaceStatus` ([the library guide](docs/library.md#3-live-inside-your-own-application-liveshow)):
  each surface's state (`ok`, `failed` or `ignored`), why it is not open (a MIDI device
  unplugged, a port in use, the `midi` extra missing), and a web remote's addresses. The
  same news as the `MIDI s-nano: …` log lines, as data.
- `OfflineShow.confirmation(line)` and `LiveShow.confirmation(line)`: the question the
  `busk run` prompt asks before a dangerous line (`Turn all DMX output off?` before
  `output off`), or `None` for a line that runs at once
  ([the library guide](docs/library.md#3-live-inside-your-own-application-liveshow)). A
  frontend asks the same without parsing the line; `execute` never asks.
- `OfflineShow.effect_templates` and `LiveShow.effect_templates`: the effect templates
  `effect add` takes, as a new public type, `EffectTemplateInfo`
  ([the library guide](docs/library.md#2-build-a-show-and-render-it-offlineshow)): the
  show's, then the built-in library's that the show has no copy of yet, each with the
  name `effect add` takes, its layers in one line and the library's defaults (size,
  low/high, phase). Before, the library's templates were only in the text of `library`.
- Fixture categories ([profiles](docs/profiles.md#categories)): a profile's optional
  `category` (`par`, `spot`, `wash`, `beam`, `pixel`, `strobe`, `blinder`, `dimmer`,
  `effect`, `fog` or `other`), for displays that group fixtures by kind. The built-in
  profiles have one, the OFL import takes the fixture's OFL category (a moving head is a
  `spot` with a gobo wheel, else a `wash`), and `profile "<name>" category <category>|none`
  sets or removes it in a show; `list profiles` shows it. It is a label: no profile gets a
  new revision for it, and `profile update` keeps the show's. GDTF files have no category.
- `PlaybackStatus.color` ([the library guide](docs/library.md#reference)): the colour of the
  cue a playback is at, for displays that draw a playback in the colour of its look. It is
  linear RGB, mixed as `FixtureOutput.color` is, of the brightest element whose colour the
  cue holds, tracked colours included; `None` while idle or when the cue holds no colour.
  The compiler works it out once per cue, so the fader, the masters and effects do not
  change it. The web remote's `state` messages have it too.
- `Reply.quit` ([the library guide](docs/library.md#3-live-inside-your-own-application-liveshow)):
  `True` in the reply of `quit` or `exit`, and of a `source` whose script stops at a `quit`,
  the lines after which the `busk run` prompt ends. `execute` still stops nothing, so a
  frontend ends when its user quits, or asks first, without matching the typed line.
- `OfflineShow.expected(line)` and `LiveShow.expected(line)`: what may come at the end of
  a line being typed, as the `busk run` prompt completes it on Tab, as a new public type,
  `Expected` ([the library guide](docs/library.md#3-live-inside-your-own-application-liveshow)):
  where the word being typed starts, the keywords and names that complete it, the values
  that may come there (described), whether the line runs as it is and the mistake that
  stops it. A frontend's own prompt completes every word as the `busk run` prompt does,
  without parsing the line.
- `LiveShow.health`, as a new public type, `EngineHealth`
  ([the library guide](docs/library.md#3-live-inside-your-own-application-liveshow)): how
  the engine is doing, for a display's engine warning. Its state (starting, running,
  stalled after 1 s without a new frame, stopped; under `busk run` with processes the
  watchdog's word, restarting and failed too), its tick and overrun counts, and how long
  ago it last ticked.
- `busk run --frontend MODULE:FUNCTION` ([Running a show](docs/running.md#frontends)):
  your own frontend instead of the prompt, called with the run's `LiveShow` in the
  console process, with `busk run`'s safety net (the engine in its own process, the
  watchdog, autosave and recovery). The run ends when the function returns; one that
  raises is restarted with the console while the output runs on. While it runs, busk
  prints nothing over it: its lines are records of the new `busk.run` logger.
- `busk run`'s show now has `frame`, `output` and `effects` too, from the engine process,
  which captures the output and effects only while they are read, at most 25 times a
  second.
- A `LiveShow` may be used from several threads at once, as documented
  ([the library guide](docs/library.md#3-live-inside-your-own-application-liveshow)).
  Lines from different threads run as if one after the other, a script whole, except
  performance lines (`go`, `fader`, `gm` …), which never wait for another thread's line:
  a frontend's controls are not held up by an edit, a `save` or a script.
- Console lines for playback buttons ([the console](docs/console.md#notes)): `flash N
  on|off` holds a playback's flash until it is released, `button N B on|off` presses and
  releases its button B as a bound control does, and `toggle N` activates or releases it.
  A frontend's buttons, and the `busk run` prompt, no longer need a controller or the
  web remote for these.
- Relative and per-component values ([the console](docs/console.md#notes)): `set
  <attribute> by <change>` adds to what the programmer holds for each selected target
  (`set intensity by 5%`, `set pan by -15`), and `set color.r 50%` or `set color.r by 10%`
  sets or changes one colour component, keeping the others. Targets with nothing in the
  programmer for that attribute are skipped. Library users and bindings have the new
  command type `ADJUST_ATTRIBUTE`.
- Stopping a programmer effect ([the console](docs/console.md#notes)): `effect stop fx1`
  stops it and keeps it in the programmer, with its settings, and `effect run fx1` runs it
  again. It fades out and back in over the programmer's fade time, as removing and adding
  it would, and `record cue` leaves a stopped effect out. `programmer` marks it
  `(stopped)`, and `ProgrammerStatus.stopped` lists the stopped ids. Library users and
  bindings have the new command type `RUN_EFFECT`.
- Tab completion and `?` at the console prompt ([the prompt](docs/console.md#the-prompt)).
  Tab completes commands, keywords and names in quotes, and lists what may come next. `?`
  prints that and the forms of the command. Both follow the parser, the show and the
  libraries.
- The web remote ([the web remote](docs/surfaces.md#the-web-remote)): tap the page name to
  choose a page from a list; a stack's strip shows the cue GO goes to next; a red OUTPUT
  OFF bar shows while `output off` holds. The `show` message lists each playback's `cues`
  (number and name).
- Colour macros: the attributes `colorMacro` (a fixture's built-in colour presets and
  programs), `colorEffect` (its colour effects) and `colorMacroRate` (how fast they run),
  in the `color` family ([attributes](docs/console.md#attributes)). Uncontrolled, a
  fixture outputs the option its own default selects.
- Tab completes the options of a discrete attribute after `set` and `park`, from the
  selected or named fixtures.
- Fixture effects: the attributes `effect` and `effect2` (the programs built into a
  fixture: an LED bar's animations, a blinder's auto program), `effectRate`,
  `effectFade`, `effectAdjust`, `effectRotation`, `effectSync` and `soundSensitivity`, in
  the `beam` family ([attributes](docs/console.md#attributes)). Uncontrolled, a fixture
  outputs the program its own default selects, and its own speed and parameters.

### Changed

- The OFL import maps `ColorPreset` to `colorMacro` and `ColorJump`/`ColorFade` programs
  to `colorEffect`; the GDTF import maps `ColorMacro1`, `ColorMacro1Rate` and
  `ColorEffects1` ([importing](docs/profiles.md#importing-ofl-and-gdtf-files)). These
  channels were `control` channels held at their default. A few channels change
  attribute: three OFL "Color Macro / Temperature" channels were `cto`, and GDTF
  channels whose logical attribute is `ColorMacro1` but whose functions are a colour
  wheel's (Robe's virtual colour wheels) were `colorWheel`.
- The OFL import maps `Effect`, `EffectSpeed`, `EffectDuration`, `EffectParameter` and
  `SoundSensitivity` on channels where nothing else maps; the GDTF import maps
  `Effects1`, `Effects2`, `Effects1Rate`, `Effects1Fade`, `Effects1Adjust1`,
  `Effects1PosRotate` and `EffectsSync` ([importing](docs/profiles.md#importing-ofl-and-gdtf-files)).
  These channels were `control` channels held at their default.
- Maintenance ranges (resets, lamp switching, settings) are never an option: colour macro
  and effect channels drop them (Fun Generation's Pico macros lose `reset`), and such a
  channel whose default selects one stays `control`.
- `colorMacroRate` starts at its channel's own default instead of 0.5, as the new rates
  do; a rate that is only a program's parameter still starts at 0.5.
- Imported profiles get a new revision: the importer's version is part of it (version 3
  with the fixture effects), so a show that embeds an older import can take the new one
  with `profile update`.

- Ctrl+C at the console prompt: on an empty line it now says how to quit, and a second
  Ctrl+C in a row quits like `quit`. Ctrl+C on a typed line still only clears it.
- `set <attribute> +5%`, with a plus sign, is refused, and the error shows the two lines
  you may have meant. It used to set 5%, a near blackout for someone who meant a change.

### Fixed

- Lines from two threads: a line parsed while another thread's edit was still being
  made could fail where it would have worked a moment later (two `effect add` of a
  template the show did not have yet), `list masters` and `list cues` could raise when
  another thread deleted what they listed, and a Ctrl+C on the main thread could be raised
  in another thread whose line ended first, or stop that thread's script.
- After a `quit` line on an `OfflineShow` or a `LiveShow`, the next `source` line or
  `run_script` ran only the first line of its script, and said nothing about it.
- `status` on an `OfflineShow` or a `LiveShow` said `no engine is running` while the
  engine ran. It now prints `busk run`'s status line (`GM 100% | BO off | P1 Main | …`),
  and a `LiveShow` says `no engine is running` only before `start()` and after `stop()`.
- The web remote on a phone held sideways: the strips were squeezed until their names
  vanished and their buttons spilled out. The header now takes one row, each fader sits
  beside its buttons, and the masters open with a **Masters** button.
- The web remote showed a TAP button that did nothing in a show without a speed master
  that takes taps.

## [0.1.0] - 2026-10-18

The first release with a public API. Phases 0–7 built the console and its `busk` command
line; Phase 8 ([plan](docs/plans/phase-8-plan.md)) made it a library too.

### Added

- **The public API**: 28 names, all importable from `busk` (see `busk.__all__` and
  [`docs/library.md`](docs/library.md)):
  - show documents: `load_show`, `save_show`, `new_show`, `validate_show`;
  - fixture profiles: `read_ofl`, `read_gdtf`, `ProfileLibrary`;
  - running a show: `OfflineShow` (frames on a clock the caller drives) and `LiveShow`
    (the engine, the DMX output and optionally the surfaces as threads in the caller's
    process), with `DmxFrame`;
  - data types: `Show`, `FixtureProfile`, `Command`, `Issue`, `CommandResult`, `Reply`,
    `ImportReport`, `EngineSnapshot`, `PlaybackStatus`, `SpeedStatus`, `PageStatus`,
    `IdFactory`, `CounterIds`;
  - errors: `BuskError`, the base of `ShowLoadError`, `UnsupportedFeature`,
    `ImportFailed` and the new `ScriptError`.
- `import busk` is cheap: the public names load lazily, on first use.
- The library prints nothing: it reports through the `busk.*` loggers, and `busk` has a
  `NullHandler`.
- The `midi` extra, `busk[midi]`, for MIDI surfaces (`mido`, `python-rtmidi`).
- The MIT license.
- The library guide, [`docs/library.md`](docs/library.md), whose examples are tested.
- [`examples/club-night.busk`](examples/club-night.busk): the demo show in one script (the
  rig, looks, a song, a chase, effects, two pages, a phone remote, LEDs and safety), with
  the controller's layout in its header.

### Changed

- `mido` and `python-rtmidi` are no longer installed by default. Without the `midi`
  extra, each MIDI surface reports `MIDI s-…: unavailable: install busk[midi]` once and
  stays closed; everything else works.
- `ShowLoadError`, `UnsupportedFeature` and `ImportFailed` now derive from `BuskError`.
  Their names, modules and attributes are unchanged, and `ImportFailed` is still a
  `ValueError`.
- Friendlier signatures, all additive: `save_show`'s `now` and every keyword of
  `new_show` (`cid`, `now`, `ids`) have defaults, and `new_show` with no `cid` touches no
  state directory. Path parameters take `str` as well as `os.PathLike`.
- The lowest supported dependency versions were lowered to what the test suite passes
  with: `numpy>=2.3.2`, `pydantic>=2.12.4`, `mido>=1.3.0`.
- The per-phase example scripts (`phase3-build.busk` … `phase7-safety.busk`), the Phase 1
  values file and the Phase 2 demo moved from `examples/` to `tests/fixtures/`;
  `examples/phase1-demo.json` is now `examples/real-fixtures.json`.
- Art-Net binds UDP 6454 only while a broadcast route is open, since only broadcast routes
  use discovery. A show whose Art-Net routes are all unicast sends from another port, so
  a receiver on the same machine, such as a visualiser, can start before or after busk;
  it no longer prints `Art-Net: cannot listen on UDP port 6454 …`, and it answers no
  ArtPolls.

The command line is otherwise unchanged: every command, flag, exit code and output line
is the same as before Phase 8.

[Unreleased]: https://github.com/lothwen/busk/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/lothwen/busk/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/lothwen/busk/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/lothwen/busk/releases/tag/v0.1.0
