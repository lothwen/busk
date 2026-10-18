# FAQ

Questions new busk users often ask. Each answer is short and links to the guide with the
details.

- [Shows and scripts](#shows-and-scripts)
- [Building a show](#building-a-show)
- [Playing](#playing)
- [Output and controllers](#output-and-controllers)
- [Saving, crashes and other machines](#saving-crashes-and-other-machines)
- [Glossary](#glossary)

## Shows and scripts

### What is the difference between a `.show` file, `show.json` and a `.busk` file?

A **`.show` file is the show**: a ZIP holding one file, `show.json`, which describes all
of it. That covers the fixture profiles it uses, universes, fixtures, groups, presets,
effects, cue lists, playbacks, pages, masters, surfaces and bindings, output routes, park
and safety. busk also runs a plain `.json` file with the same content. `busk run` loads
it and plays it.

A **`.busk` file is a console script**: lines you could type at the `busk>` prompt, with
`#` comments. It runs on a show that is open, with `busk run SHOW --script FILE` or
`source FILE` at the prompt. See [Scripts](console.md#scripts).

### Once a script has run, are its commands stored in the show?

No, their result is. Each line changes the show in memory, and `show.json` stores the
show that results, not the commands that built it: an edit typed at the prompt and the
same edit from a script give the same file. Nothing reaches the file until it is saved,
by a `save` line in the script, `save` at the prompt, or the save busk offers at `quit`.
(Autosave keeps a copy in busk's state directory for crash recovery, not in your file.)

Not every command changes the show. `fader`, `go`, `gm` and `blackout` play it, and
`sel` and `set` fill the programmer. Only edits such as `fixture add`, `record …`, `bind`
and `limits` end up in `show.json`.

### Can I run the same script twice?

Usually not on the same show. A script stops at its first error, and adding something
that already exists is one:

```
examples/club-night.busk:36: universe add 1 "Stage"
error: universe 1 exists
```

Run a build script once, on a new show from `busk new`. A script can also add to an
existing show (another page, more bindings), as long as it creates only what is not
there yet.

### Can I turn a show back into a script?

No, busk has no command that writes a show out as console lines. To see what a show
holds, use the `list …` commands at the prompt or read its JSON
(`unzip -p club.show show.json`). To see what a run changed, and when, read its event log
with [`busk replay`](running.md#the-event-log-and-replay).

### Can I edit `show.json` by hand?

Yes. Take it out of the ZIP, edit it, check it, and run it as a `.json` file:

```bash
unzip -p club.show show.json > club.json
busk validate club.json        # one line per issue; exits 1 on errors
busk run club.json
```

At the prompt, `save club.show` writes it back as a `.show` file. [The spec](busking-console-architecture-python.md)
describes the schema.

## Building a show

### I am starting from an empty show. In what order do I build it?

Here's the order I'd follow. It comes from the docs and from how [examples/club-night.busk](../examples/club-night.busk) builds its show. Each step uses things made in earlier steps (cues use groups and presets, page slots hold playbacks, bindings control slots), so building in this order means you never need something that doesn't exist yet.

**0. Before you start**
- Know each fixture's model, DMX mode and start address.
- Check that busk has a profile for each fixture: at the prompt, `library` lists the ones it can patch. For any that are missing, run `busk import ofl FILE… --out profiles` (or `busk import gdtf FILE…`), then add `--library profiles` to `busk run`.

**1. Create the show and open the console**
```bash
busk new myshow.show --title "My Show"
busk run myshow.show --iface eth0        # the interface that reaches your DMX node
```
Everything below is typed at the `busk>` prompt. Tab completes words and `?` shows what can come next.

**2. Patch**
```
universe add 1 "Stage"
fixture add 101 thru 104 "RGB Par 3ch (Generic)" mode 3ch at 1.1
list fixtures
```

**3. Output.** Add this early: a new route opens right away, so you see on stage what you program.
```
route add 1 sacn 1            # or: route add 1 artnet 0.0.1 / route add 1 dmxusb enttecPro /dev/ttyUSB0
```
`sel fixture 101` then `highlight on` turns that fixture on at full, which checks the patch fixture by fixture.

**4. Groups.** Make these before presets and cues, because recording uses them (a cue stores "group 1", not four fixture numbers).
```
sel fixture 101 thru 104
record group 1 "Pars"
```

**5. Presets** (colours, positions)
```
sel group 1
set color 0 0 1
record preset color 1 "Blue"
clear
```

**6. Looks on faders.** Each `record slot` creates a cue list, its first cue and a playback, and puts the playback on a slot of page 1.
```
sel group 1
set intensity 80%
preset color 1
record slot 1 "Blue wash"
clear
```
Then set how each playback behaves: `playback 1 exclusivity color`, `cue 1/1 timing.fadeIn 1`, `playback 1 buttons ["toggle", "flash", "release"]`.

**7. Optional extras**, once the basics work:
- **Cue stacks:** `record cue 9/2`, `cuelist 9 tracking true`, `cue 9/2 time 3`.
- **Chases:** run `master add speed "Speed 1" bpm 120` first, then `cuelist 10 chase bpm`.
- **Effects:** `effect add "Circle"`, then `record slot …`.
- **More pages:** `page add 2 "Washes"`, `record slot 2.1 …`.

**8. Controllers.** Do this after the playbacks exist, since the bindings point at them.
```
surface add midi "nanoKONTROL2"
bind "nanoKONTROL2" cc 1 0 fader 1
bind "nanoKONTROL2" cc 1 23 master gm
surface add web "Phone"           # prints a URL to open on your phone
```
`aseqdump -p <port>` shows which CC numbers your controller sends.

**9. Safety**
```
fixture 101 limits intensity 50%
park fixture 104 intensity 0
safety strobe 3
```

**10. Save**
```
save
```
From then on, `busk run myshow.show` plays it.

**Tips while you work**
- `undo` reverses the last action.
- `blind on` lets you program without changing the stage.
- `list groups|presets|playbacks|bindings|…` shows what you've built.
- Autosave covers crashes, but you still need `save` to write `myshow.show`.
- If you'd rather keep your work as a rebuildable recipe, type the same lines into a `.busk` file and run it once on a new show with `--script`.

### My fixture is not in the library. What do I do?

Import its [Open Fixture Library](https://open-fixture-library.org/) or GDTF file, and
pass the output directory to `busk run`:

```bash
busk import ofl my-fixture.json --manufacturer Acme --out profiles --report
busk run myshow.show --library profiles
```

The import prints each profile's name, which is the name `fixture add` takes. Without
`--manufacturer`, the manufacturer is the name of the file's folder, as in OFL's
repository. A show embeds a copy of every profile it patches, so `--library` is needed
only while you patch. See [Fixture profiles](profiles.md).

### What do all the numbers mean?

- **Fixtures** take the numbers you give `fixture add` (101, 102, …). `N.E` is element E
  of fixture N: `301.3` is the third cell of an LED bar.
- **Groups and presets** take the numbers you give `record group N` and
  `record preset color N`.
- **`record slot S`** puts a new playback in slot S of the current page (`P.S` for slot S
  of page P). The playback and its cue list take the number S if it is free, else the
  next one after the highest, so slot 2.1 of the demo show holds playback 14. `cue L/C`
  is cue C of cue list L.
- At the console, `fader N`, `go N` and `release N` name **playbacks**. A controller's
  `fader S` and `button S B` bindings name **slots of the current page**, so they play
  whatever that page holds.

`list playbacks`, `list pages` and the other `list` commands show the numbers.

### What can a cue hold?

A cue is a list of entries, plus effects and timing. Each entry gives one attribute a
value on some targets:

- **The value** is a direct value (`set intensity 80%`), a preset (`preset color 1`), one
  value per fixture, or a spread across the fixtures (`set pan spread -30 30`).
- **The targets** are a group, or a fixed list of fixtures or cells. A group is a live
  link: edit the group later and the cue follows.

One cue can hold many entries, for different groups, attributes and presets: group 1 in
Blue, group 2 at 50% and fixture 301 with gobo `breakup`, all in the same cue.

A cue does not store your selection, which lives only in the programmer while you work.
Recording turns it into groups wherever a group covers the selected fixtures, and lists
the fixtures otherwise; `record cue … freeze` always lists them. See
[the console](console.md#notes).

### `record` says something exists. How do I change it?

A record command without `merge`, `replace` or `remove` only creates, so a typo never
overwrites anything. Add one of them:

- `merge`: the values you set replace those already there, and the rest are kept;
- `replace`: the old content goes, and only the values you set are stored;
- `remove`: the attributes you set are deleted.

Other changes have their own commands: `rename group 1 "Heads"`, `delete cue 10/2`,
`cue 3/1 timing.fadeIn 1`. See [the console](console.md#commands).

### Why does the stage ignore my faders?

The programmer is probably still holding values. What `sel`, `set` and `preset` set goes
to the programmer, which is live on stage above every playback: its intensity overrides
the playbacks, even downwards, and its other values sit on top. After recording a look,
`clear` empties it; `programmer` lists what it holds.

To program without the stage changing at all, use `blind on`; `blind off` applies the
programmer.

### How far back does `undo` go?

1000 steps, on one timeline of show edits and programmer changes: `undo` reverses the
last action, whatever it was, and `redo` brings it back. Saving is not a step, and blind
and the programmer's fade time are modes, which are never undone.

## Playing

### What can a playback, or a fader, play?

A playback runs one cue list, nothing else. What changes is how many cues the list has:

- **one cue** is a look: the fader brings it in and out, and the buttons toggle or flash
  it;
- with **several cues**, GO and BACK step through them, each with its own fade;
- in **chase mode**, busk steps through them by itself, at a BPM or a rate in Hz.

Values, presets and effects reach a fader only inside a cue. To put a preset on a fader,
record it as a one-cue look:

```
sel group 1
preset color 1
record slot 3 "Blue"
clear
```

Fader 3 now brings in Blue. The cue keeps the preset, so editing preset color 1 later
changes what the fader does.

A controller's faders and buttons can drive more than playbacks: masters (grand, group,
speed, size, fade time), tap, pages, blackout, `release all` and `output on|off`. A group
master is the closest thing to a fader on an attribute: it scales one group's intensity.
`set` and `preset` reach only the programmer, from the console.

### Can I play a show without typing?

Yes. Bind a MIDI or OSC controller, or open the web remote on a phone, and run
`busk run SHOW --no-console`: busk reads no commands and plays from the surfaces until
Ctrl+C.

### How do I use my phone as a remote?

`surface add web "Phone"` starts a web server, and busk prints its address, one per IPv4
address of the machine:

```
Web s-…: http://192.168.1.20:8080/?k=…
```

Open it on a phone on the same network. The key at the end is required, and stays the
same from one run to the next on that machine. The phone plays the show (faders, buttons,
masters, pages, tap) but cannot edit it or the programmer. See
[the web remote](surfaces.md#the-web-remote).

### My faders jump when I change page.

That is the default `jump` pickup: a fader sets the level to wherever it is. With soft
takeover a fader does nothing until it reaches the playback's level, then follows it:

```
busk> surface "nanoKONTROL2" pickup soft
```

### How do I quit without stopping the light by accident?

One Ctrl+C on an empty line only prints `press Ctrl+C again to quit`; a second in a row
quits. On a typed line, Ctrl+C clears it. `quit` and Ctrl+D quit too, and busk offers to
save unsaved edits first.

### Something goes wrong on stage. What are the panic commands?

- `release all` (or `release all 2`, over 2 s) releases every playback;
- `blackout on` darkens everything until `blackout off`;
- `output off` stops all DMX output (at the prompt it asks first) until `output on`.

Bind them to buttons so they are one press away. See [Safety and panic](safety.md#panic).

## Output and controllers

### I see no light. What should I check?

1. **A route.** At start-up busk prints one line per route it opens:
   `sACN r-…: U1 Stage → universe 1, multicast 239.255.0.1 via eth0, priority 100`.
   `list routes` shows them; `route add` makes one.
2. **The network interface.** A route keeps the interface it was added with: `--iface`
   (default `eth0`) only sets it for routes you add. `ip -br link` lists the interfaces;
   use the one that reaches your node.
3. **The patch.** The fixture's start address and mode in busk must match the fixture's
   own. `sel fixture 101` then `highlight on` lights it at full white, whatever the look.
4. **The masters.** `status` prints the grand master and shows `BO on` while blackout is
   on and `OUT off` while the output is off.
5. **The programmer and safety.** `blind on` keeps the programmer off the stage;
   `list park` and the fixture's limits may hold it dark.

To see what busk sends without any fixture, pipe commands in with `--console`, which
prints each universe's non-zero channels when they change:

```bash
echo "fader 1 1" | busk run myshow.show --console --duration 2
```

An sACN viewer on the same machine (sACNView, QLC+, OLA) sees the traffic too. See
[Output](output.md).

### My MIDI controller is not found, or does nothing.

- Install the MIDI extra, `busk[midi]`. Without it busk prints
  `MIDI s-…: unavailable: install busk[midi]`.
- The surface's name must be part of the port's name (case does not matter). If no port
  matches, busk lists the ports it found: `'nanoKONTROL2' not found; available: …`.
  `aseqdump -l` lists them too.
- `aseqdump -p <port>` shows what each control sends; use those channels and numbers in
  `bind`.
- A controller plugged in later opens by itself within 2 s.
- On a Korg nanoKONTROL2, LED feedback needs the LED mode set to **External** in the KORG
  KONTROL Editor.

See [MIDI](surfaces.md#midi).

## Saving, crashes and other machines

### busk crashed, or I closed it without saving. Is my work lost?

No. While a show runs, edits are autosaved 5 s after a burst of them, and the programmer,
master levels and current page at most once a second. The next `busk run` of the same
show restores them and says so (`recovered programmer with 4 values, …`); `--no-recover`
starts clean instead. Quitting with unsaved edits keeps them in the newest autosave and
prints its path. See [Autosave and recovery](running.md#autosave-and-recovery).

### Where are my backups?

Saving keeps the 10 newest backups in `<name>.backups/`, next to the show. Autosaves go
to `~/.local/state/busk/autosave/<show id>/` (`$XDG_STATE_HOME/busk`, or `--state-dir`).
If a show fails to load, the error names its newest backup, if there is one.

### How do I save under another name?

`save PATH`. The extension picks the format: `.show` for the ZIP, `.json` for plain JSON.
Later `save`s without a path go to the new file.

### I moved my show to another computer and nothing comes out.

The show carries its fixture profiles, so it loads anywhere, but each route keeps the
network interface it was added with, and the new machine may name it differently. Edit
`destination.iface` of each route in `show.json` ([above](#can-i-edit-showjson-by-hand)):
an interface name on Linux, or the interface's IPv4 address on any system. The phone's
address changes too, since its key belongs to the machine.

### Which systems does busk run on?

Python 3.12 or later. busk is tested on Linux; other POSIX systems should work but are
untested, and Windows is not supported. On Python 3.13 and later, the MIDI extra builds
from source and needs a C++ compiler and the ALSA headers. See [Install](../README.md#install).

### Can I use busk from my own Python program?

Yes. Shows can be loaded, validated, saved and played from Python, on a clock you drive
or live. See [busk as a library](library.md).

## Glossary

Each of the four words you meet first is built from the one before it:

- **Attribute**: one property of a fixture that you can control, such as intensity, pan
  or colour. `set color 0 0 1` sets the `color` attribute of whatever is selected. busk
  has a fixed set of attributes, listed in [the console](console.md#attributes).
- **Preset** (palette): a named, reusable value for one attribute or a few, such as
  "Blue" or "Audience". `record preset color 1 "Blue"` records one. Cues point to the
  preset instead of copying its value, so if you edit "Blue", every cue that uses it
  changes too.
- **Cue**: one stored state: attribute values (or presets) for groups or fixtures, plus
  effects and timing (fade in and out, wait). `record cue 9/2` records cue 2 of cue
  list 9.
- **Cue list**: an ordered list of cues that you step through with GO, BACK and GOTO. A
  cue list with one cue is a **look**, and one in chase mode is a **chase**. A cue list
  does nothing until a **playback** runs it from a fader or button; `record slot 1`
  creates a cue list, its first cue and a playback in one go.

The other terms:

| Term | Meaning |
|---|---|
| **Fixture** | A patched instance of a lighting device. |
| **Fixture profile** | Library definition of a device model: modes, channels, wheels, physical ranges. |
| **Mode** | One DMX personality of a profile (e.g. "16-ch basic", "32-ch extended"). |
| **Element** | An individually controllable part of a fixture (a pixel of a bar, a cell of a multi-head). Single-cell fixtures have exactly one element. |
| **Target** | A `(fixture, element)` pair — the smallest thing an attribute belongs to. |
| **Slot** | A compiled `(target, attribute)` pair with a dense integer index; the unit the resolver works on. |
| **Lane** | One float inside a slot (a colour slot has several lanes: r, g, b, optional w/a/uv). |
| **Playback** | A performance handle that runs one cue list, with fader/button behaviour and a priority. |
| **Contribution** | What a running source offers for one slot this tick: value, weight, priority, sequence. |
| **Priority band** | All contributions sharing the same priority number. |
| **HTP / LTP** | Highest-takes-precedence / latest-takes-precedence merge rules. |
| **Weight** | 0..1 "how present" a contribution is, driven by fades and LTP fader modes. |
| **Programmer** | The temporary editing buffer the operator uses to build values before recording. |
| **Tracking** | A cue list behaviour where values persist into later cues until changed. |
| **Park** | A value forced at output regardless of everything else (e.g. a broken fixture held at 0). |
