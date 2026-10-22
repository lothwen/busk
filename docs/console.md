# The console

The console is where a show is built and changed: patching, programming, recording
presets and cues, binding controllers. It runs at the `busk run` prompt, from a script
(`busk run --script FILE`, or `source FILE` at the prompt), and from a pipe. The stage
keeps running while you edit, and every edit can be undone.

- [The prompt](#the-prompt)
- [Commands](#commands)
- [Notes](#notes)
- [Attributes](#attributes)
- [Scripts](#scripts)

## The prompt

At a terminal, `busk run` opens the `busk>` prompt:

- **Tab** completes the word being typed: a command, a keyword, a name in quotes (a
  master, surface, profile, mode or effect template), or an option of a discrete
  attribute (`set colorMacro `, `park fixture 3 gobo1 `: the options of the selected or
  named fixtures). Where several words fit, or a value comes next, it lists what may come
  next instead.
- **`?`** prints what may come next and the forms of the command, then gives the line back
  as it was:

  ```
  busk> route add 1 ?
  next: artnet  dmxusb  sacn
      route add U sacn <universe> [unicast <host> | multicast <iface>]
      route add U artnet <net>.<sub>.<uni> [unicast <host>]
      route add U dmxusb enttecPro|dmxking <port> [hz N]
          (hz: the widget's output rate, 40 by default)
  busk> route add 1
  ```

  `<a fixture number>` describes a value to type, `<Enter>` means the line runs as it is,
  and a line that cannot go on says why (`error: no fixture 99`). To type a `?` itself (in
  a name), press Ctrl+V first. Where Python's readline is libedit (macOS, and Pythons
  installed by uv), `?` is not a key: end the line with `?` and press Enter.
- **Ctrl+C** clears a typed line. On an empty line it prints `press Ctrl+C again to quit`,
  and a second Ctrl+C in a row quits, so one stray press never stops the output. `quit`
  and Ctrl+D quit too; with unsaved edits, busk asks whether to save them first. With
  libedit every Ctrl+C counts as one on an empty line.

## Commands

The console speaks in user-facing numbers (`fixture 101`, `group 2`, `preset color 1`,
`cue 10/1`, `playback 3`) and turns them into ids; everything it does goes through the
session, as the web remote's commands do. `help` prints the grammar.

| Area | Commands |
|---|---|
| Selection | `sel fixture 101 thru 104`, `sel group 1, group 2`, `sel + fixture 201`, `sel - group 2`, `sel 301.3 thru 301.6`, `sel none`, `sel playback 3` |
| Values | `set intensity 80%`, `set pan -45`, `set color 1 0.5 0 w 0.2`, `set gobo1 breakup`, `set pan spread -30 30 [center\|edges]`, `set color preset color 1`, `preset position 1`, `set intensity by 5%`, `set pan by -15`, `set color.r 50%`, `set color.b by -10%` |
| Programmer | `clear`, `blind on\|off`, `fade 2` (programmer changes fade over 2 s), `programmer` |
| Record | `record group N`, `record preset <pool> N [global\|profile\|target]`, `record cue L/C [only <family>…] [freeze]`, `record slot S [only <family>…]`; each takes `merge`, `replace` or `remove` and a `"name"` |
| Patch | `universe add 1 "Stage"`, `fixture add 101 thru 104 "Generic Spot 16ch" mode 16ch at 1.1`, `fixture 101 patch 2.1`, `fixture 101 patch none` |
| Output | `route add 1 sacn 1 [unicast 10.0.0.20 \| multicast IF]`, `route add 1 artnet 0.0.1 [unicast 10.0.0.20 \| broadcast IF]`, `route add 1 dmxusb enttecPro\|dmxking /dev/ttyUSB0 [hz 40]` |
| Surfaces | `surface add midi "nanoKONTROL2"`, `surface add osc "Touch" [port 8000] [feedback 10.0.0.5:9000]`, `surface add web "Phone" [port 8080] [on 10.0.0.2]`, `surface "nanoKONTROL2" pickup soft\|jump` |
| Bindings, feedback | `bind "nanoKONTROL2" cc 1 0 fader 1`, `… cc 1 32 button 1 1 [led]`, `… cc 1 7 fader playback 18 [motor]`, `… cc 1 23 master gm`, `… cc 1 18 master "Speed 1"`, `… cc 1 46 tap ["Speed 1"]`, `… cc 1 42 blackout [momentary]`, `… cc 1 62 page +1`, `… note 1 60 page 2`, `bind "Touch" osc "/fader/1" fader 1 [display osc "/label/1"]`, `bind "nanoKONTROL2" clock tap`, `… cc 1 60 release all [2]`, `… note 1 61 output off`, `feedback "nanoKONTROL2" cc 1 32 thru 39 led\|motor\|display\|none`, `unbind "nanoKONTROL2" cc 1 60 [thru 61]` |
| Pages | `page 2`, `page next\|prev`, `page add 2 ["Washes"]`, `page 2 slot 1 playback 14`, `page 2 slot 5 clear`, `record slot 2.1`, `playback 9 goto 4` |
| Edit | `playback 3 exclusivity color`, `cue 3/1 timing.fadeIn 1`, `playback 1 buttons ["toggle", "flash", "release"]`, `show meta.title "Club Night"`, `rename group 1 "Heads"`, `delete cue 10/2` |
| Timing, triggers | `cue 9/1 time 3 easeInOut`, `cue 9/3 time 1/3 delay 0/1`, `cue 9/2 time position 4 [delay 1] [easeOut]`, `… bezier 0.4 0 0.2 1`, `cue 9/3 wait 8`, `cue 9/5 follow 4`, `cue 9/2 go`, `cue 9/5 release group 1 [only pan tilt]` |
| Cue lists, tempo | `cuelist 9 tracking true`, `cuelist 10 chase bpm ["Speed 1"] [x 2] [forward\|reverse\|bounce\|random] [crossfade 0.25]`, `cuelist 10 chase hz 4`, `cuelist 10 sequence`, `master add speed "Speed 1" [bpm 120] [steps 0.5, 1, 2]` |
| Effects, masters | `effect add "Circle" [id fx1] [hz 0.5 \| bpm ["Speed 1"] [x 0.5]] [size 15] [low 0 high 1] [phase 0 180] [groups N] [blocks N] [wings 2] [forward\|reverse\|bounce] [fadein 1] [sizemaster "FX"] [speedmaster "Speed 1"]`, `effect remove fx1`, `effect clear`, `effect template add "Name" [{…layers…}]`, `cue 9/4 effect rainbow size 0.5`, `master add size "FX"`, `master add group "Wash level" group 2`, `master add fadetime "Fade"` |
| Perform | `go 9`, `back 9`, `goto 9 4`, `release 3 [2]`, `fader 3 75%`, `flash 3 on\|off`, `toggle 3`, `button 3 2 on\|off`, `gm 0.5`, `master "Speed 1" 0.75`, `tap ["Speed 1"]`, `bpm ["Speed 1"] 128`, `blackout on\|off` |
| Safety, panic | `park fixture 204 intensity 0`, `park group 2 color 1 0 0`, `unpark fixture 204 [intensity]`, `unpark all`, `fixture 101 thru 102 limits tilt -90 10`, `fixture 301 limits intensity 50%`, `fixture 101 limits none`, `safety strobe 3\|off`, `highlight on\|off`, `release all [2]`, `output on\|off` |
| Profiles | `profile update "Generic Spot 16ch"` (to the library's other revision), `list profiles` |
| Session | `undo`, `redo`, `save [PATH]`, `list fixtures\|groups\|presets\|cuelists\|playbacks\|pages\|universes\|routes\|surfaces\|bindings\|masters\|profiles\|effects\|park`, `list cues 9`, `library`, `info`, `status`, `source FILE`, `quit` |

## Notes

* **Numbers.** Fixture `N` is every element of fixture `N`; `N.E` is element `E`, counted
  from 1 (`301.3` is the PiX's third cell). Page slots and buttons count from 1, like the
  physical controls. `thru` keeps its direction (`104 thru 101` selects backwards).
* **Relative values.** `set <attribute> by <change>` adds the change to what the
  programmer holds for each selected target: `set intensity by 5%`, `set pan by -15`. A
  preset reference counts with the preset's value for that target, and becomes that value,
  changed. `set color.r 50%` sets one component of the colour (`r`, `g`, `b`, `w`, `a` or
  `uv`) and keeps the others; `set color.r by 10%` changes it. Changes stop at the ends of
  a range (intensity and colour components at 0 and 1; pan and tilt have none), and a
  component the colour does not have starts from 0 (for `w`, the fixture then stops
  deriving its white). A target with nothing for that attribute in the programmer is
  skipped and the reply says so: busk changes only what the programmer holds, so set a
  value first. A colour changes only by component, a discrete attribute not at all. A plus
  sign is refused where `by` may come: `set intensity +5%` would set 5%.
* **Recording keeps intent.** A cue references a group wherever one covers the targets
  that have the attribute (the biggest first; ties go to the group with fewer members,
  then the lower number) and keeps preset references, so editing the group or the preset
  later updates the look; `freeze` records explicit targets instead. Differing literal
  values are recorded per target. A preset cascades from the requested scope: one global
  value if every target agrees, else per profile, else per target, and the reply says so
  (`pan: 4 target values (values differ)`). Without `merge`, `replace` or `remove` a record
  command only creates, so a typo never overwrites anything.
* **`record slot S`** on an empty slot of the current page (`record slot 2.1`: slot 1 of
  page 2) creates a cue list, its cue 1, a
  playback (Appendix A's Blue playback without its exclusivity: band 50, `master` fader,
  `toggle` and `flash` buttons, `threshold` LTP at 2 %, auto start/release, a flash that
  brings LTP, 1 s release) and puts it in the slot, as one undo step. On an occupied slot
  it records into the playback's cue, with `merge`, `replace` or `remove`.
* **Tracking lists record changes only.** In a list with `tracking` on, `record cue`
  stores only the values that differ from what the list already tracks into that cue
  (`recorded cue 9/2: 4 entries; 8 values tracked from cue 9/1`); a cue whose values all
  track is created without entries. `sel playback N` selects the targets of the
  playback's *current* cue (its tracked state), or of its first cue while it is idle.
* **Timing.** `cue L/C time <in>[/<out>]` sets the cue's fade in and out (out defaults to
  in), with an optional `delay` and curve (`linear`, `easeIn`, `easeOut`, `easeInOut`,
  `snapStart`, `snapEnd`, `bezier x1 y1 x2 y2`); with a family name it sets that family's
  own timing. In a chase, cue timing and triggers are ignored except the curve: the
  crossfade sets the step fade. Speed masters have no numbers, so they are named in quotes;
  `tap` and `bpm` without a name use the show's only speed master.
* **Effects** (busk effects; a fixture's own programs are the `effect` attribute, see
  [Attributes](#attributes)). `effect add` adds an effect on the selection, in selection
  order (which sets the phase spread), to the programmer, where it runs live at band 100
  like its values; `programmer` lists it
  (`effect fx1 'Circle' on 101, 102, bpm 'Speed 1' ×0.5, size 15`) and `record cue` or
  `record slot` records it (`only` filters it by its attributes' families, `merge` adds
  or replaces it by id, `remove` drops it). The template is the show's of that name,
  else the built-in library's (Circle, Pulse, Wave, Chase, Saw, Sweep, Flicker, Rainbow,
  listed by `library`), embedded into the show first. Defaults: the library's size,
  `low`/`high` and phase for that template, ×1 on the show's only speed master (else 1
  Hz), and the id `fx<n>` that neither the programmer nor any cue uses. A slot recorded
  with only effects gets a `size` fader. `list effects` lists the show's templates,
  `list cues` counts each cue's effects, and `cue L/C effect <id> <prop> <value>` edits
  a recorded instance.
* **Pages and surfaces.** `page N`, `page next` and `page prev` turn the
  engine's page (`list pages` marks it with `*`); `page add` creates one with empty slots,
  and `page P slot S playback N` fills a slot. `surface add osc` and `surface add web`
  take their options in any order; ports default to 8000 and 8080 and must be free among
  surfaces of that kind, and surface names are unique. `bind` takes a feedback after the
  action (`led`, `motor` or `display`, sent to the input's own address unless another
  follows); `feedback "<surface>" <input> [thru <n>] led` adds feedback to the bindings
  already on those inputs (`none` removes it), and an input without a binding is an
  error. `list surfaces` and `list bindings` show ports, pickup and feedback.
* **Buttons.** `flash N on` holds playback N's flash until `flash N off` (or `release
  all`), as a held flash button does, whether or not the playback has one. `button N B
  on|off` presses and releases the playback's button B as a bound control does: `go`,
  `back`, `toggle`, `release` and `goto` act on `on`, `flash` and `swop` on both, and
  `select` selects the playback's targets, as `sel playback N`. `toggle N` releases an
  active playback and activates any other. These lines are for a frontend, which sends
  `on` when its button goes down and `off` when it comes up; they name playbacks, not
  slots.
* **Safety, panic and profiles** (see [Safety](safety.md) and [Fixture profiles](profiles.md#updating-a-shows-profiles)). `park` replaces what
  was parked on the slots it names and `unpark` removes it, each as one undo step (park
  entries have no ids, so the whole list is set). `limits` sets one key of each fixture's
  limits and keeps the others. `release all` and `output on|off` are performance
  commands, like `go`, and can be bound; `bind` adds a binding next to those already on an
  input, so `unbind "<surface>" <input> [thru N]` frees it first. `info` adds the
  processes, their restarts and the event log file.
* **Undo** walks one timeline of show edits and programmer changes (1000 steps): the last
  action, whatever it was. Blind and the programmer's fade time are modes and are never
  undone. Saving is not a step.
* **Errors** name what you typed (`no group 7`, `preset color 1 exists: add merge or
  replace`), and an edit that would make the show invalid lists every place it breaks:

  ```
  busk> delete group 2
  error: deleted groups[1]: rejected, the show would not be valid
    cueLists[1].cues[0].entries[1].targets.groupId: Unknown group 'g-par'
  ```

## Attributes

The attributes are built into busk: a show cannot add one, and each fixture has those its
profile supports. `set`, `park` and `release … only` take an attribute's name, in any
case; `record … only` takes a family (any but `control`). A normalised value is `0..1`
or a percentage (`80%`), a discrete value names one of the fixture's options
(`set gobo1 breakup`), and a colour is `r g b` with optional `w`, `a` and `uv`, each
one also settable on its own (`set color.w 20%`).

| Attribute | Family | Kind | Unit | Merge | Fade | Default |
|---|---|---|---|---|---|---|
| `intensity` | intensity | scalar | normalised | **HTP** | fade | 0 |
| `pan` | position | scalar | degrees | LTP | fade | 0 |
| `tilt` | position | scalar | degrees | LTP | fade | 0 |
| `positionSpeed` | position | scalar | normalised | LTP | snap | 0 (fastest) |
| `color` | color | color | linear RGB | LTP | fade | white `{1,1,1}` |
| `colorWheel` | color | discrete | — | LTP | snap | open |
| `cto` | color | scalar | normalised | LTP | fade | 0 |
| `colorMacro` | color | discrete | — | LTP | snap | the channel's default option |
| `colorMacroRate` | color | scalar | normalised | LTP | fade | the channel's, else 0.5 (0 slowest, 1 fastest) |
| `colorEffect` | color | discrete | — | LTP | snap | the channel's default option |
| `gobo1`, `gobo2` | beam | discrete | — | LTP | snap | open |
| `gobo1Rotation`, `gobo2Rotation` | beam | scalar | degPerSec | LTP | fade | 0 |
| `prism` | beam | discrete | — | LTP | snap | off |
| `prismRotation` | beam | scalar | degPerSec | LTP | fade | 0 |
| `zoom` | beam | scalar | degrees | LTP | fade | profile midpoint |
| `iris` | beam | scalar | normalised | LTP | fade | 1 (open) |
| `frost` | beam | scalar | normalised | LTP | fade | 0 |
| `effect`, `effect2` | beam | discrete | — | LTP | snap | the channel's default option |
| `effectRate` | beam | scalar | normalised | LTP | fade | the channel's, else 0.5 (0 slowest, 1 fastest) |
| `effectFade` | beam | scalar | normalised | LTP | snap | the channel's, else 0 (snap or shortest) |
| `effectAdjust` | beam | scalar | normalised | LTP | fade | the channel's, else 0.5 |
| `effectRotation` | beam | scalar | degPerSec | LTP | fade | the channel's, else 0 |
| `effectSync` | beam | scalar | normalised | LTP | snap | the channel's, else 0 |
| `soundSensitivity` | beam | scalar | normalised | LTP | snap | the channel's, else 0 (off or lowest) |
| `focus` | focus | scalar | normalised | LTP | fade | 0.5 |
| `shutter` | shutter | discrete | — | LTP | snap | `open` |
| `strobeRate` | shutter | scalar | hz | LTP | fade | 0 |
| `control` | control | discrete | — | LTP | snap | none (lamp on, reset… — never busked) |

`colorMacro` picks a colour preset or program built into a fixture (`set colorMacro red`,
`set colorMacro colourChange`), `colorEffect` one of its colour effects, and
`colorMacroRate` sets how fast a program runs. Their options are the fixture's own,
named after its OFL or GDTF file. Nothing controlling them, a fixture outputs the option
its own default selects, usually "no function" (`off`): on most fixtures a macro
overrides the colour mix while it is set.

`effect` picks one of a fixture's **fixture effects**, the programs it runs by itself: an
LED bar's animations, a blinder's auto program, a head's pan/tilt macro (`set effect
fuego`, `set effect off`). A fixture with two program channels has `effect2` too.
`effectRate`, `effectFade`, `effectAdjust`, `effectRotation`, `effectSync` and
`soundSensitivity` are their speed, fade, parameter, rotation, sync and sound
sensitivity, whether a channel of their own or the range of a program (one slot drives
both). Nothing controlling them, the fixture keeps its own defaults. They are in the
`beam` family, so `record preset beam` and `only beam` carry them. Fixture effects are
not **busk effects** (`effect add`, below), which are busk's own waveforms over
attributes; a busk effect can move a fixture effect's rate.

```
busk> sel fixture 101
busk> set effect fuego            # the LED bar's "Fuego" animation (DMX 69)
busk> set effectRate 50%          # its speed channel at 128
busk> set effect off              # back to the static colour
```

## Scripts

Scripts are console lines in a file (`#` starts a comment); `source FILE` runs one
from the console and `busk run --script FILE` before it. A script stops at its first
error and says where (`build.busk:12: sel group 7`).
