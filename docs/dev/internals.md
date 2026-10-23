# How busk works

How the engine, the console and the output fit together, for anyone changing busk. The
architecture is specified in [`busking-console-architecture-python.md`](../busking-console-architecture-python.md)
("the spec"; section numbers such as §5.3 refer to it). [`development.md`](development.md)
has the source layout and the tests.

## The processes

`busk run` runs three processes: the **root** sends the output and watches the other two,
the **engine** runs the pipeline, and the **console** holds the session, the prompt, the
surfaces and the web remote. [Running a show](../running.md#processes-and-the-watchdog)
describes them from the operator's side.

```
            ┌─ busk run: the ROOT (no show code) ───────────────────────────────────────────┐
terminal ───┤ output thread (44 Hz) ─▶ sACN (+ discovery), Art-Net (+ ArtPoll), DMX-USB     │
            │   routes reopen on failure · hold or dark on a stall · output off             │
            │ frame thread ◀─ frames, layouts, stats, event-log records                     │
            │ watchdog (10 Hz): no frame for 1 s → stalled; 3 s, or an exit → kill, respawn │
            │ event log · --stats · --duration · signals · restarts of either child         │
            └───┬────────────────── control links (socket pairs) ───────────────────┬───────┘
                │ ↑ frames, stats, log  ↓ attach, stop  attach, engine state, pids  │
                │   (stderr, --frontend)                routes, news (--frontend)   │
┌───────────────▼── ENGINE (own session) ───────────────────────────┐               │
│ link thread: commands, install chunks, restore → the queue        │               │
│ engine thread, fixed tick: due events (auto-GOs, chase steps)     │               │
│   → drain (≤ 512 items: commands, installs; page, held buttons,   │               │
│   soft takeover) → per-slot fades → effects (clocks, waveforms,   │               │
│   strobe cap) → gather (+ programmer at band 100) → resolve       │               │
│   (absolute, then relative) → masters (group, grand) → safety     │               │
│   (highlight, park, blackout, limits, strobe lanes) → convert     │               │
│ publisher: frames → root; snapshots, stats → console              │               │
└───────────────▲─────────────────────────────┬─────────────────────┘               │
   commands, installs (engine view, shared    │ snapshots, stats; watched frames,   │
   objects, chunks), restore after a restart, │ output captures, effects            │
   watch                                      │                                     │
┌───────────────┴─────────────────────────────▼── CONSOLE (the terminal's) ─────────▼───────┐
│ console prompt ─┐  (or a --frontend, on the main thread)                                  │
│ MIDI (hot-plug)─┤                        session (single writer): programmer ·            │
│ OSC ────────────┼─▶ bindings ─▶ commands ─▶ show store · undo · validate ·                │
│ phone (web API)─┘   (rate-limited remotes)  compile → install                             │
│ RemoteBus: the session's bus; queues commands while the engine restarts                   │
│ status line · feedback (30 Hz) · web broadcaster (30 Hz) · autosave                       │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

`busk run --threads` runs the same components as threads of one process, without the
watchdog and the restarts.

**A frontend** (`--frontend MODULE:FUNCTION`; GAP-11 of
[`tui/engine-gaps.md`](tui/engine-gaps.md)). The console process imports it before it
loads the show (a failure is exit 1, not a crash the root would restart) and, after the
script, calls it on its main thread with the attached `LiveShow` instead of `interact`,
with the monitor thread polling as at the prompt. Everything reaches it through that
show's `EngineLink`, which has the frames, output captures and effects too: a
`LocalEngine` hands over the engine's own (`--threads`), and the `RemoteBus` asks the
engine process for them with a `WATCH` the first time each is read, and again after every
reconnect. The engine host keeps the current link's watch (a new link watches nothing),
captures the output and effects only while they are watched, and its console publisher
sends what is new after each tick (`_Watched`): `LAYOUT` and `FRAME` as to the root, an
`OUTPUT` capture without its compiled show but with the stamp of the newest show it ran
(the console reads it with its own copy of that show, which has the readout lookups the
engine view lacks, and skips a capture of a show it has replaced), and `EFFECTS`, read in
the engine process (0.16 ms for the reference rig's 20 effects, on the publisher thread),
since a capture holds the compiled effects. The terminal is the frontend's while it runs:
`busk.process.report.diverted` hands `say` and `warn` to the `busk.run` logger in the
console process, and in the root to a `NEWS` message to the console (printed if no
console takes it), which carries the route lines, the watchdog's news and the engine's
stderr, read from a pipe.

## The pipeline, piece by piece

**Validation** (`busk.model.validate`). Pydantic validates the JSON against the spec's
own `TypedDict`s in strict JSON mode, then a hand-written semantic pass checks what types
cannot express and collects every issue with a path such as `fixtures[2].patch.address`.
The profile rules that conversion depends on: capabilities by kind (a scalar
needs a `range`, a wheel a `slot`, a shutter a shutter function), every discrete channel
offers its attribute's default option (this makes the shutter guard total), function
parameters are scalar attributes, colour components name known emitters and an element
mixes either additively (R, G, B) or subtractively (C, M, Y flags), every mode can be
dimmed (a dimmer channel, or a virtually dimmed element), dimmer tables have ≥ 2 points,
and `swapPanTilt` fixtures have both pan and tilt. One output rule: two
enabled sACN routes on the same sACN `universe` must send the same show universe (they
share its sequence numbers under one CID). Disabled routes send nothing and are skipped.
One preset rule: a preset holds at most one value per `(scope, attribute)`,
since a second one could never be looked up.

**Slots** (`busk.compiler.slots`). Every `(fixture, element, attribute)` that can be
controlled becomes a slot with a dense index and a run of float lanes in the logical frame
(§6.1–§6.2): fixtures in show order, elements in index order, attributes in registry
order. Elements get a slot per attribute they have a channel for (never `control`), plus
derived slots: `intensity` for a virtually dimmed element (§13.2) and the parameters of
their function capabilities (`strobeRate` for a strobe range). A discrete slot's lane
holds an index into its options, which are the channel's wheel slots or shutter functions
in DMX order (the first of duplicate ids wins). The default frame holds the registry
defaults, with `zoom`'s "profile midpoint" resolved.

**Channels** (`busk.compiler.channels`). One frozen record per slot-driven channel:
universe row and byte addresses, input slot, range segments (after `invert`), pan/tilt
orientation folded into `(input slot, offset, sign)`, dimmer curve, emitter, option table.
On overlapping patches the later fixture owns each shared byte, exactly as in the base
image, so every written address is unique.

**Cues** (`busk.compiler.cues`, §6.3). Every cue of every cue list is compiled, as its
own values and then as the tracked state a playback holds at it (*Cue lists*, below).
Each entry's targets are expanded (a group follows its
members, in order), its value is resolved per target (a literal; a `perTarget` map by
target key; a preset by the §5.8 scope lookup, target → profile → global; a spread by the
member's index), targets without the attribute are dropped, and the value is encoded
into the slot's lanes and clamped to the attribute's range once, here, instead of every
tick. A later entry for the same slot wins. A discrete value the target does not offer
(a gobo it lacks, another wheel) is dropped for that target with a compile warning. The
lanes are then partitioned the way the resolver merges them: intensity (HTP, as
positions in the slot table's intensity lanes), continuous LTP lanes, and **snap
lanes** that cannot be interpolated, each with its own threshold: discrete attributes and
`positionSpeed` snap as soon as the source is present, colour extras (`w`, `a`, `uv`,
which may be `NaN` = "derive") at half presence. Everything is a sorted, read-only array.

**Conversion** (`busk.convert`). The plan flattens the records into a structure of
arrays, and the converter runs a fixed sequence of numpy kernels each tick: range inputs
and dimmer curves; colour (white extraction, explicit extras, CMY, virtual intensity) in a
small matrix with one row per emitter role; one uniform segment map for every value
(multi-segment channels pick the containing or nearest segment); options and their
strobe-rate parameters; then `split_raw` and a scatter into the universe buffers. Python
loops run only over curves and resolutions, never over channels. Rounding is half to even.
`tests/reference_convert.py` transcribes §13 channel by channel with the same
floating-point operations in the same order, and a property test checks that both agree
byte for byte.

**Commands** (`busk.commands`). Nothing outside the engine thread touches engine state:
bindings, the web API and the CLI call `CommandBus.submit`, which validates the command
on the caller's thread (a performance command, an existing playback, master or page,
levels clamped to 0..1), wraps it in a §15.1 envelope with its origin (the surface and
control, or the phone's address) and queues it. A rejected command raises
`CommandRejected` with a readable reason, such as `no page 7` or `speed master 'Clock'
does not take taps`. The engine drains the queue at the start of each tick and applies the commands,
in order, at the tick's time; each one is guarded, so a bug is counted and the tick goes
on.

**Playbacks** (`busk.engine.playback_runtime`). A playback is up to two **sources**: *main*
holds the latched state (activate → active → release → releasing → idle) and *flash* is
present while its flash button is held or its `temp` fader is up, in its own band
(`priority + priorityBoost`) with its own sequence number, so letting go of a flash leaves
the stack below exactly as it was. Every latching activation (trigger, toggle, GO,
`autoStart`) takes a fresh number from the global sequence counter, which is what "latest"
means in LTP, and releases the other active playbacks with the same exclusivity key.
The slots fade one by one with the cue's timing (*Fades per slot*, below);
a release still fades the whole playback, from where it is, over the release time, so a
release in mid-fade lasts exactly the release time. A master fader scales intensity; for LTP, `followFader` scales the
presence by the fader, `threshold` waits (when the fader started the playback) until the
fader passes `ltpThreshold`, and `ignoreFader` ignores it.

**Resolver** (`busk.engine.resolver`, §7). Each tick, the present sources are sorted by
`(priority, seq)` and composited over the frame of uncontrolled slots. LTP is a layer
stack: each source moves its lanes from what is below towards its own values by its
presence, `v + (value − v)·w` (exactly `value` at full presence), and snap lanes jump once
the presence reaches their threshold. HTP runs per band over a dense array of all
intensity lanes: `v = v·(1 − P) + M`, with `P` the band's highest presence and `M` its
highest `value · scale · presence` per lane, which is §7.4's crossfade with the division
cancelled out. Contributions are batched per source (§19's arrays, not an object per slot
per tick), so the Python loop runs over sources, never over slots. Because a source's
contributions share `(priority, seq)`, this is exactly §7.7 applied slot by slot, which
`tests/reference_resolver.py` transcribes literally; a property test checks they agree.
A source may carry a presence per lane (a slot mid-fade) and a snap
threshold per lane; a settled source at full presence takes the old scalar fast path.

**Masters** (`busk.engine.masters`, §12). Group masters scale the intensity of
their group's members, each member by the product of the group masters containing it;
then the grand master (the product of every grand master's level) scales the intensity
lanes and blackout zeroes them (inside the safety stage, below), on the
working frame only, after the resolver and before
conversion. Runtime state is never touched, so taking
either away returns exactly to the live look, whatever was flashing or overriding.

**Engine** (`busk.engine.loop`). Each tick fires the auto-GOs and chase steps due by its
time, each at its own time, then drains the commands (stage 1; at most 512 items,
the rest wait for the next tick in order), fires what the commands
made due, advances the playbacks and their fades (3–4), gathers and resolves the sources (6–7), applies the
masters (9–10) and the safety stage (11), copies the base images into the back buffer (so control channels keep
their `defaultDmx`), converts (12) and publishes a frozen `Frame` of `bytes` with one
reference assignment (13). When the visible state changed, it also publishes an
`EngineSnapshot` (master levels, blackout, each speed master's tempo, multiplier and beat
anchor, the current page and the fade time, each playback's state, fader, flash, swop,
current cue and manual progress) the same way. Effect phases are not in it:
they change every tick, and a remote can derive them from the tempo and the time.
Every value is a function of the commands applied and of the tick's time, so a show looks
the same at any tick rate (§2.5) and replays byte for byte on a fake clock (§2.7). Ticks
are scheduled from an integer count (no drift); a late tick counts as an overrun and the
schedule restarts from now.

**Time.** Every runtime value is a pure function of the commands and the
time, whatever ticks run in between: positions are never integrated (`phase += rate·dt`)
but computed from a start time and a rate, and rebased only at events (a GO, a tap, a
rate change). Events that fall due between two ticks (an auto-GO, a chase step) fire at
their own times before the tick's commands, so a command sees what it would see on any
tick schedule. Frames are therefore byte-identical at 100 Hz, 37 Hz or on a random
schedule, and the song test replays to the byte.

**Fades per slot** (`busk.engine.fades.ContributionSet`). Each source holds, per lane of
its HTP, LTP and snap partitions, where its value and presence fade from and to, a timing
group (start, delay, duration, curve) and a sequence number, all as arrays; a tick
evaluates each group's curve once and lerps the lanes. A **retarget** (a GO, an edit, a
programmer change) aims the set at a new state: a slot whose target is unchanged keeps its
running fade, so a 0-s GO halfway through a 10-s pan fade does not make the pan jump; a
changed slot fades from where it is, with the timing of the destination cue for its family
(in for rising intensity and every LTP value, out for falling intensity, per family and
per entry overrides, delays, curves). A slot's lanes change together. When every group has
finished, the set compacts to a static source.

**Sequence numbers per slot.** "Latest" in LTP applies to what an action changes: an
activation numbers every slot, a GO, BACK or GOTO only the slots it changes, and
automatic advances, chase steps and edits keep the numbers they have. So a colour bump
on top of a tracking stack stays on top through every GO that leaves colour alone. A
contributor whose slots hold several numbers reaches the resolver as one source per run
of its numbers between the other contributors' numbers in its band
(`contributions.SequencedSource`), which composites exactly in `(priority, seq)` order.

**Cue lists** (`busk.compiler.tracking`, `busk.engine.cue_engine`, §8.1, §9.1–§9.3). The
compiler precomputes each cue's **tracked state**: in a tracking list a cue holds what the
cues before it set, up to a `block` cue, minus its `releases` (a cue's own values win over
its own releases); without tracking a cue holds only its own values. GOTO therefore lands
on exactly what stepping gives. GO moves to the next cue (at the last: wrap, release with
`releaseAtEnd`, or re-assert), BACK to the previous with that cue's timing, GOTO anywhere.
After a forward move the next cue's trigger is scheduled: `wait d` fires d after the move,
`follow d` d after the fades it started complete; BACK and a release cancel it.

**Chases** (`busk.engine.chase`, §9.4). A chase list steps by itself at a rate in Hz or
in steps per beat of a speed master, fading into each step over `crossfade` × the step
length with the cue's curve, `forward`, `reverse`, `bounce` or `random` (seeded per
activation). A BPM chase stays on its master's beat grid: on activation, a tap or a rate
change it moves to the next grid position rather than back, and a `rate` fader scales it
by ¼ to 4, rounded to a power of two on BPM chases.

**Speed masters** (`busk.engine.masters`, §11.3). Each counts beats from the first tick at
its BPM; a tempo change rebases the count, so the grid never jumps. Every tap (`TAP`)
moves the nearest whole beat onto the tap; from the second tap of a run (a 2-s pause
starts a new one) the tempo is 60 over the mean of the last 8 taps' intervals that lie
within 25 % of their median. `SET_BPM` sets the tempo outright. The master's level picks one of
its `multiplierSteps` (×¼ … ×4 by default), which multiplies the rate of every chase
and effect locked to it.

**Effects** (`busk.compiler.effects`, §10). An effect instance, in a cue or in the
programmer, names a template of layers, its targets, a rate (Hz, or a multiple of a speed
master's beat), a size, a phase range and the spread options. The compiler expands the
targets in order and places each member on the phase range (§10.2: `wings` mirror every
other wing, `blocks` give neighbours one position, `groups` repeat the pattern). It
compiles each layer to the lanes of the members that have its attribute: a waveform
(`sine`, `triangle`, `square`, `sawUp`, `sawDown`, `pulse`, `step`, `random` or `curve`)
between `low` and `high` for an absolute layer, an amplitude for `add`, a depth for
`multiply`, or, for a colour cycle, a palette per member (preset references resolved per
member). A target is exactly its element, so an effect on the PiX's group spreads over its
12 cells. An effect that drives nothing compiles to nothing, with a warning.

**Effect clocks** (`busk.engine.effects.EffectClock`). An effect's position `P`, in cycles,
is computed and never integrated, like a chase's: `p0 + rate·(t − t0)` in Hz, or `p0 +
rate·(beats(t) − b0)` on a speed master, starting on its beat grid. A tap or a rate change
re-aligns a BPM effect to the grid position nearest where it is, but the difference is
not applied at once: it shrinks linearly to nothing over one beat. Nothing moves at the
tap, and one beat later the effect is on the new grid (§10.1's "nudged toward the master's
beat phase", made exact). Each member's phase is `P`, run backwards for `reverse` and
folded for `bounce`, plus its offset and its layer's.

**Running effects** (`EffectRuntime`, `EffectBank`). Each playback has a bank of running
instances, retargeted with its slots on every activation, GO, chase step and live edit.
An instance that enters fades in over `sizeFadeIn` or the cue's in time; one that leaves
fades out with the cue's out time and keeps moving; one that changes (a new size, a
trimmed member list, an edited template) cross-fades from its old form to the new one on
the same clock, mixing the two per lane by presence, so a size change is an exact morph.
In a tracking list an instance carries on, by id, into the next cues, so its clock never
restarts. A release fades the whole playback, effects included, which keep moving. An
absolute layer is a source in its playback's band, numbered so that it wins a tie with
its cue's own values; the dynamics (`size` fader × size master) scale its presence. While
the playback's main is idle, a held flash or a `temp` fader runs a second bank in the
flash band.

**The relative pass** (`busk.engine.resolver`, §7.5). After the absolute pass, `add` and
`multiply` layers apply in `(priority, seq, order)` order: `v + amount·W` and `v·lerp(1,
amount, W)`, with `amount` = `size·d·(2w − 1)` or `1 − size·d·(1 − w)` (`w` the waveform's
0..1, `d` the dynamics). `W` is the layer's weight × `(1 − A)`, `A` being the highest
presence on that lane among the absolute sources of higher bands. So the programmer or a
higher band suspends a circle on the slots it takes, and fading it in fades the circle out
instead of cutting it. Additions to attributes with a range are clamped after the pass.

**The output readout** (`busk.compiler.readout`, `busk.engine.readout`; GAP-01 of
[`tui/engine-gaps.md`](tui/engine-gaps.md)). `OfflineShow.output` and `LiveShow.output` read
the frame the safety stage left back per fixture element, as the public `OutputSnapshot`.
Every source and relative layer carries an `Origin` (the programmer, a playback, or an
effect of either), and `Resolver.attribute` walks them in the resolver's order to say what
drives each lane: the topmost source present on an LTP lane, on an intensity lane the
strongest contribution of the highest band present, then the last relative that moves it.
The highlight's lanes are the programmer's and parked lanes nobody's. While
`Engine.captureOutput` is set, each tick publishes a `Capture` (a copy of the frame and the
per-lane owners) by reference; `LiveShow` sets it on the first read of `output` (`busk
run`'s engine host while its console watches the output, see [the processes](#the-processes)),
and `OfflineShow` captures on demand after its tick. `read_output` turns a
capture into `FixtureOutput`s on the reader's thread, with lookups the compiler builds once
per rig (`CompiledShow.readout`, left out of the engine process's view): each element's
lanes, the master dimmer that dims a cell without its own, the colours of its colour
wheel's slots, and the runs of lanes of each family, so the per-family source is one
`reduceat`.

**The effect status** (`busk.engine.effect_status`; GAP-09 of
[`tui/engine-gaps.md`](tui/engine-gaps.md)). `OfflineShow.effects` and `LiveShow.effects`
list the instances the tick ran, as the public `EffectSnapshot`. Each `EffectRuntime` keeps
what its last update evaluated (the clock's position, each version's presence and
dynamics), and while `Engine.captureEffects` is set, each tick publishes an
`EffectCapture`: per instance of every bank (the playbacks' in show order, main then
flash, then the programmer's), its bank's `Origin`, its newest compiled form, which is
immutable, and those numbers. As with the output, `LiveShow` sets the flag on the first
read and `OfflineShow` captures on demand. `read_effects` builds the `EffectStatus`es on
the reader's thread: the next cycle of the first member of the first layer with a
waveform (and of the first colour layer) is the engine's own `base_phase`, `evaluate` and
`palette_colours` at the clock positions `P + k/20`. The cue an instance is defined in is
`CompiledEffect.cue`, set by the compiler and kept by tracking; it is not part of the
structure `same()` compares, and a retarget to a `same()` form takes the new object, so a
renumbered cue renames its running effects and changes nothing on stage.

**Pages and buttons** (`busk.engine.surfaces`). The engine keeps the current page
(`PageState`), one for every surface: it starts on the lowest-numbered page, `PAGE` moves
it by number or by a delta that stops at the ends, and a live edit keeps it by id (a
deleted current page gives way to the first page numbered at or after it, else the last).
Bindings send page-relative commands, `SET_FADER {slot}` and `PLAYBACK_BUTTON {slot,
button, down}`, which the engine resolves on the page current when it applies them, so a
page change and a fader move land in queue order whatever thread sent them. The buttons
follow §8.1: `go`, `back`, `toggle`, `release` and `goto` (a GOTO to the playback's
`gotoCue`) act on the press, `flash` and `swop` on both edges. A held flash or swop is
recorded per control (`HeldButtons`), so its release reaches the playback its press did,
after a page change too. `select` goes to the session, resolved by the binding resolver
on the snapshot's page.

**Soft takeover** (`Pickup`). On a `soft` surface each fader and knob is attached to what it
drives or not. Detached, a move does nothing until the control comes within 0.02 of the
level or crosses it between two moves; attached, it sets the level. Pointing at something
else (a page change) or a move of the same level from another source (another control,
the phone, the console) detaches it. This is engine state, keyed by the command's
`origin.control` (the binding's id), so it never depends on which input thread won a race.
A move on an empty slot still records where the control is, so coming back to the page
cannot take over by a stale crossing.

**Swop** (`Playbacks.swop`). While a swop is held on a playback, its flash is up and every
other playback's sources (flashes and effects included) take an HTP weight of 0, unless
they are `protectFromSwop`. LTP lanes are untouched and nothing else in the runtime
changes, so letting go returns exactly to the look before. (§8.1 sets the others'
`intensityScale` to 0; removing their presence also silences §7.4's override bands, which
would otherwise hold intensity through the swop.)

**Fade-time masters** (`busk.engine.masters`). The highest fade-time master's level `L`
gives `T = 10 s × L²`. While `T > 0`, every transition that starts (an activation, GO,
BACK, GOTO, an auto-GO, and their effects) fades every slot over `T` with no delay and the
cue's curve, and a release without an explicit time (a button, `autoRelease`,
exclusivity, GO past the end) takes `T`. Chase steps, flashes, swops, live edits and the
programmer keep their own timing, and running fades are left alone.

**Manual crossfades** (`PlaybackRuntime.manual`). A `crossfade` fader rests at 0 or 1.
Leaving its rest end starts the playback's next transition (its activation, else a GO) on
a virtual clock: a travel `p` from the rest end puts the transition at `p × span`, the span
being the cue's longest delay plus fade (effects included), so every slot's own timing and
curve play out in step with the hand. Progress is the furthest travel so far, so the fader
only pushes the transition on; at the far end the transition completes and that end
becomes the rest. Fades running when the fader starts settle and finish with it; a GO, a
release or a live edit that retargets the playback freezes the manual transition where it
is and goes on in real time. A fader moved in step with the clock gives the frames a GO
gives.

**Input** (`busk.io`). The `SurfaceManager` opens each surface of the show and follows live
edits. A `midi` surface opens one port through `mido` + `python-rtmidi`; rtmidi calls back
on its own thread with each message, which becomes an `InputEvent` (control change, note,
pitch bend; channels 1–16; value 0..1). MIDI clock is counted, 24 clocks to a beat, into
one press of the `midiClock` input per beat (Start and Song Position set the count), so a
DAW drives a speed master through tap tempo. An `osc` surface has a UDP socket and a
receive thread; each message (bundles unpacked) becomes an event on its address. A
`BindingResolver` looks up the bindings of an event and submits commands: page faders and
buttons as page-relative commands with the binding as their control, absolute faders, the
grand master and other masters (a speed master's level picks the multiplier), tap tempo
(on press), blackout (toggled on press, or on and off with the button when `momentary`),
page buttons and embedded commands. Buttons are edges with per-binding state, so a
repeated CC 127 is one press and any note velocity presses. A failing binding is reported
once and never breaks the input thread.

**Feedback** (`busk.io.feedback`). `feedback_values` turns the latest snapshot into a value
per feedback binding, on the current page: an LED 1 or 0, a motor position, a label. The
`FeedbackWorker` thread computes them 30 times a second and sends only what changed: MIDI
through the output ports it owns (one writer per port), OSC through each surface's socket.
A motor fader is held back for 0.5 s after its control last moved, so the motor never
fights a finger. The tap LED needs the beat phase, which changes every tick and is not in
the snapshot: the snapshot carries each speed master's beat anchor (a time and a beat,
which change only at taps and tempo changes), and the worker computes the phase at its
own time on the engine clock.

**The web remote** (`busk.web`). One port serves the phone page and a WebSocket at `/ws`,
both behind the key (`?k=`, compared in constant time) and an origin check, so a page
from another site cannot connect. The server side of RFC 6455 is written here: each
connection reads on its handler thread and writes on a writer thread of its own, where
pongs and the close frame go first, replies queue (64 at most) and each state message
replaces the one not yet sent, so a slow phone gets the newest state, not a backlog, and a
phone that takes nothing for 2 s is dropped. The protocol is JSON: on connect a `hello`
(the protocol version and the engine's time), the `show` (pages, playbacks with buttons
and cues, the masters) and then whenever the compiled show changes, and the `state` (the
snapshot) at most 30 times a second. A phone sends performance commands (`PAGE`,
`SET_FADER`, `PLAYBACK_BUTTON`, `SET_MASTER`, `TAP`, `BLACKOUT`, …) and gets an `error`
with the command's id when one is refused. Show edits and programmer commands are refused:
the console stays the only editor (§23). The buttons a phone holds are released when it
disconnects.

**Output** (`busk.output`). At start-up `build_routes` creates and opens one sender per
enabled route (`SacnSender`, `ArtNetSender`, `EnttecSender`); routes that are disabled,
for an interface busk cannot drive (`enttecOpen`), or that cannot open (an unknown
interface, an unresolvable host, a missing device) are reported and left out. The output thread
(`OutputScheduler`) then runs at 44 Hz, the DMX512 refresh ceiling. Each cycle it reads
`engine.latest` once, flags each universe whose bytes differ from the previous cycle's
frame, and offers every route its universe with that flag; then it services the
`--console` sink. Each driver call is wrapped on its own, so a driver bug is counted as a
fault on that route and never stops the others.

A sender decides whether a packet is due (`SendPolicy`, E1.31 §6.6): a change is sent at
once and repeated on the next 3 cycles; after that, a keep-alive goes out whenever 0.9 s
have passed since the last send (every 40 cycles, 0.909 s: inside E1.31's 800–1000 ms and
far inside receivers' 2.5 s timeout). So a static look costs about one packet per second
per universe, and a stalled engine's last frame keeps being held. The 638-byte packet is
built once per route; a send writes the sequence number (one counter per sACN universe,
shared by its routes), the options byte and the 512 data bytes, then calls `sendto` on a
non-blocking socket. A failed send is counted, sets the route's status to `ok = False`
with the error, and never raises; it still counts as a send for the keep-alive timer, so a
dead link is retried about once a second, and the next successful send restores `ok`. The
main thread polls the statuses (and the snapshot, for the status line) every 0.1 s and
reports changes. On shutdown the output
thread makes a final pass, then closes every sender, which sends 3 Stream_Terminated
packets (if it ever sent a packet) and closes its socket.

**Art-Net** (`busk.output.artnet`). One socket (`ArtNetNetwork`) is shared by the
Art-Net routes, opened with the first and closed with the last. It is bound to UDP 6454
while a broadcast route is open and to an ephemeral port otherwise, and is opened again
on the other port when the first broadcast route opens or the last one closes. A route
sends a 530-byte ArtDmx per universe with a sequence number per Port-Address, on change
and as a keep-alive once a second. Each output cycle the network reads what arrived (64
datagrams at most, so a flood cannot stall the output), answers ArtPoll with an
ArtPollReply, records the nodes whose replies have output ports, forgets those silent for
10 s, and polls every 2.5 s on its routes' broadcast addresses. A broadcast route sends to
the nodes on its interface's network that output its Port-Address, else to the broadcast
address.

**sACN discovery** (`UniverseDiscovery`). Every 10 s, and at once when the list changes,
busk sends the sorted list of the universes its open sACN routes send (512 to a page) on
universe 64214, out of each multicast route's interface.

**DMX-USB** (`busk.output.dmxusb`). An Enttec DMX USB Pro or a DMXking widget is
a serial device (raw, 8N1) that takes framed messages (`0x7E`, label, length, data,
`0xE7`): on open the parameters (break, mark after break, the output rate from
`refreshHz`), then label 6 with the 512 slots on change and once a second. Writes never
block: a frame due while the previous one is still going out is dropped and owed, so the
next cycle sends it. A write error marks the route failed and closes the device, which is
reopened at most once a second; a reopen sends the parameters and a full frame.

**Session** (`busk.session`). The session is the command bus of §15 and the only
writer of editing state: the show store, the programmer and the undo timeline. It routes
every command by class (`busk.commands.classes`). Performance commands go straight onto
the engine's queue without taking its lock, so busking never waits for an edit; input
threads hand everything else to one worker thread (`post`), so a MIDI callback never
blocks either. Programmer and show-edit commands run under the lock. **The session only
ever holds a show that validates and compiles**: an edit becomes patch ops, applied to a
candidate show, validated and compiled, and only then committed and installed; any error
rejects the whole edit, a `BATCH` included, and nothing changes anywhere. Other threads
read an immutable `SessionSnapshot` published by one reference assignment.

**Edits and undo** (`busk.commands.patch`, §15.4). Generic edits address the show by id
(`["cueLists", {"id": "cl-song"}, "cues", {"id": "c-verse"}, "timing", "fadeIn"]`); recording
and patching have their own commands. Every edit is a list of JSON-patch ops (`add`,
`remove`, `replace`) applied **copy-on-write**: only the containers on an op's path are
copied, so an untouched subtree of the new show *is* the old object, and the inverse ops
are captured while applying. Undo applies the inverse, redo the forward ops, through the
same validate → compile → install path. Programmer changes share the timeline, so one
`undo` undoes the last action, whatever it was; blind is a mode and is never undone.

**Validating an edit** (`validate_edit`). Copy-on-write makes the touched entities exactly
those that are not the very objects they were before, so only they are validated
structurally (each with its own `TypedDict` adapter, through the same strict JSON path a
load uses, so paths read `presets[3].values[0].value`); then the whole semantic pass runs.
Touched entities are replaced by their validated copies, so the store always holds what a
load would produce (keys in schema order, floats, tuples). A property test checks that it
reports exactly what a full `validate_show` reports, and normalises the same way.

**Incremental recompile** (§6.4). The same identity rule replaces the spec's reverse
dependency index: `compile_show(show, previous)` reuses the whole rig (slots, channels,
conversion plan, base images) when profiles, fixtures and universes are the same lists,
and a compiled cue list when it and every group and preset its entries read are the same
objects. A cue edit recompiles one list; a preset edit, the lists that read it.

**Programmer** (§5.14). An immutable value: an ordered selection, values per slot (a
literal, or a preset reference kept as a reference), and blind. Spreads and per-target
values are evaluated per target when set (`set pan spread -30 30` stores each head's
own pan). Values whose slot disappears stay, dormant, and come back with an undo. The
session resolves the programmer to lanes off the engine thread (a `ProgrammerFrame`) and
installs it; in the engine it is one more source at **band 100** with full weight, so its
intensity overrides the playbacks (even downwards) and its LTP values sit on top. Each
slot carries the sequence number of the last command that set it, and the engine splits
the programmer into as few sources as the other band-100 sources require, so "latest"
holds slot by slot. Blind leaves it out of the live resolve; leaving blind applies it. With
a fade time (`fade 2`) every change fades: a set value, a clear, a blind switch,
an undo. It also holds effects (`ADD_EFFECT`, `REMOVE_EFFECT`), which run in
the programmer's own bank at band 100, entering, changing and leaving over its fade time.
`ADJUST_ATTRIBUTE` (GAP-05, `set … by`, `set color.r`) changes values the programmer
already holds, under the session lock like any programmer command, so a change never
reads a stale base: it adds a delta (clamped to the registry range, rounded to 9
decimals) or sets one colour component, and turns a preset reference into the literal
the §5.8 lookup gave, changed. Where the programmer holds nothing it changes nothing: the
session does not know the stage's value (the output readout is the engine's, after
masters, and under `busk run` it lives in another process).

**The programmer status** (`busk.session.status`; GAP-02 of
[`tui/engine-gaps.md`](tui/engine-gaps.md)). `OfflineShow.programmer` and
`LiveShow.programmer` turn the programmer into the public `ProgrammerStatus`, on the
reader's thread, from one `SessionSnapshot` (it carries the `ShowState`, so the show and
the programmer are of the same moment), and only when that snapshot is a new one. Targets
become `(number, element)` and a preset reference gets the value the §5.8 lookup gives its
element, so a show edit alone (a renumbered fixture, an edited preset) can change the
status too. `programmer_status` returns the previous status when the new one is equal,
so `version` counts changes of the content. What is dormant is left out, by the rules
`build_frame` uses: a gone target, a value without a slot, a preset value or its option,
and an effect that no longer validates.

**Recording** (`busk.commands.record`, §15.3). Recording turns programmer values into
show data that keeps intent: a cue entry references a group whenever one covers the
targets (a greedy cover over the groups whose members *with that attribute* fit), keeps
preset references, and lists the rest explicitly; a preset cascades from the requested
scope to profile and target values only where targets disagree. `merge` restricts the
existing entries to the targets the programmer does not cover (a group entry that loses a
member becomes an explicit list; a spread becomes per-target values computed from the
original fan, so nothing moves) before adding the new ones. Effects are recorded by
instance id: `merge` replaces or appends them, `remove` drops them, targets equal to a
group's members stay a group reference, and in a tracking list an instance equal to the
one the cue already tracks is not stored.

**Live swap** (`busk.engine.install`). An install is applied at stage 1, in queue order:
per-slot runtime arrays follow the slot remap in one vectorised step, and each running
playback is re-pointed at its recompiled cue by cue id (a deleted cue falls back to the
next number) and **fades** to the cue's new state with that cue's timing (a chase with its
step crossfade), keeping every slot's sequence number, so an edit never reorders the
stack. An edited effect cross-fades to its new form on its running clock. A list the edit did not touch is left alone. Pending auto-GOs are re-derived from
the edited triggers, and chases and speed masters carry their phase over. Frames carry the
compiled show they were made with: when it changes, the output thread closes, opens and
re-points its routes (rows matched by universe id) and the bindings re-read themselves.

**Persistence** (`busk.persistence`, §17). `.show` files are a ZIP holding `show.json`,
written deterministically (equal shows, equal bytes) and atomically (temp file, `fsync`,
`os.replace`, directory `fsync`), with 10 rolling backups. The autosave worker reads the
session's snapshot without its lock, writes the show 5 s after a burst of edits and
`session.json` at most once a second, and on start-up after a crash the programmer,
master levels and unsaved edits are restored.

**Processes** (`busk.process`, §16, §18). The root (`root.py`) makes two control
socket pairs, spawns the engine (`python -m busk.process.engine_host`, in a session of its
own) and the console (`python -m busk.process.console_host` with the run's arguments), and
hands each of them one end of a third pair (`socket.send_fds`): the console ↔ engine link.
Every message is a length, a kind and a payload (`wire.py`): a frame is a fixed header
(sequence, time, layout id, universe count, output enabled) and the raw universes,
everything else is a pickle. Pickle crosses only these links, between processes of one
tree; nothing from the network is ever unpickled. The engine host runs three threads: one
decodes the link into the engine's queue, the engine thread ticks as in `--threads`, and a
publisher sends the newest frame to the root whenever the socket takes it (a slow root
makes it skip frames, never the tick wait) and snapshots and statistics to the console. The
console runs the session, the prompt, the surfaces and the web remote as `--threads` does, with a `RemoteBus` (`links.py`) as the
session's bus: one lock orders its writers, so an install still precedes the commands
validated against its show, and the engine never validates again. The root's output
scheduler reads an `OutputLayout` per compiled show (universes, output settings, the dark
bytes), sent before the first frame made with it, so the root runs no show code.

**Installs across processes** (`ShowEncoder`, `ShowDecoder`). A live swap keeps a
playback's fades when its compiled cue list is *the same object* as before, so a compiled
show that arrived as new objects would retarget everything. The encoder sends what the
engine reads (the *engine view*: no channel records, memo, warnings or per-slot records,
the slot keys as one tuple) and pickles with `persistent_id`: an object that is the same as
in the previous install on that link (the rig, the conversion plan, each cue list) goes as
a reference, which the decoder resolves to the object it already holds. An edit therefore
sends what the incremental compile changed and identity survives the trip. A big install
goes in chunks (the rig, then each changed list), loaded one at a time with a GIL yield in
between, and the engine sees it only when the commit arrives; it then freezes its garbage
collector (`gc.freeze()`), so collections never scan compiled shows.

**The watchdog and the restore** (`Root`, `Engine.restore`). The root's main loop (10 Hz)
sees each new frame as a heartbeat, tells the console `stalled` after 1 s, and after 3 s,
an exit, or no first frame within 15 s of a spawn (imports and the first install of a
§19-sized show), kills the engine, spawns a new one with a new link and sends the
console's end over (`Attach`, with the reason). The console says `hello`, gets `welcome
(fresh)`, sends the full install, then a `Restore` of the last `EngineSnapshot` it
received, then the commands it queued meanwhile. `Engine.restore` sets the master levels,
the speed masters' tempo and beat anchor (`CLOCK_MONOTONIC` is shared by all processes,
so the grid lands where it was), blackout, output, the page, and activates every playback
that was active at its cue and fader level, snapped, in the order of `PlaybackStatus.seq`
(each activation's number), so the LTP stack is rebuilt in activation order. A restart
within 10 s of the last restore sends no restore, and more than 3 in 60 s give up.

**Console restarts and the show stamp.** Each install carries `(sessionId, showVersion)`,
and `session.json` records the stamp of the newest show written to disk. A restarted
console (`--restarted`) recovers from autosave, takes the engine's masters, tempos and
page from its `welcome`, and compares stamps: the same stamp sends only the programmer;
otherwise it installs its recovered show as a live edit. That install's slot remap is
computed by the engine from the slot keys it keeps, since the new console never saw the
engine's compiled show.

**The safety stage** (`busk.compiler.safety`, `busk.engine.safety`, §12 stage 11). The
compiler turns park entries into slots and values (a target that lacks the attribute is
skipped with a compile warning), limits into per-lane bounds in logical degrees on every
element, and finds the strobe lanes and, per universe, the dark bytes (every dimmer byte,
and the emitter bytes of virtual-intensity fixtures, at intensity 0). Each tick, after the
masters, `apply_safety` works on the output frame only: highlight, park on intensity
lanes, blackout, park on every other lane, limits, strobe lanes clamped to the cap; after
conversion, highlight's `highlightDmx` bytes. So releasing any of it returns exactly to
the live state, and a parked slot cannot be moved by anything else.

**The strobe cap on effects** (`busk.engine.effects`). An effect with an intensity layer
counts flashes per cycle (1 for every waveform but `step`, which counts its rises, and
`curve`, its peaks). With the cap set, an Hz effect's rate is clamped so that rate ×
flashes stays under it; a BPM effect halves its cycles per beat until it does, which keeps
it on the beat grid, and a tempo change re-rates it through the existing align-and-nudge,
so it never jumps. Chases are not capped.

**Highlight** (`busk.engine.install.Highlight`) is not a source. While the mode is on,
the session builds it into the programmer frame from the selection: the selected targets'
intensity, shutter and colour lanes with the values to force (1, `open`, white), and the
byte positions and `highlightDmx` values of their other channels (never pan, tilt or a
parked slot). The safety stage writes the lanes, and the bytes over the converted
universes. It is live even while the programmer is blind.

**Panic, stalls and output off** (`busk.engine.loop`, `busk.output.scheduler`).
`RELEASE_ALL` releases every playback that is active, releasing or flashing, with its own
release time or the given one, and drops held flashes and swops. `OUTPUT` is engine state
(`EngineSnapshot.outputEnabled`), carried in each frame, so the root's output follows it
and a restore brings it back: while it is off no route sends, and sACN routes send
Stream_Terminated once and start a new stream when it is on. The scheduler also watches the
frames: 1 s without a new one, it offers the last frame again every cycle (held), or a
copy with the layout's dark bytes set when `holdLastFrameOnEngineStall` is false. At a
prompt `output off` asks first: its parse carries the question (`Submit.confirm`), and
`Console.confirmation`, which the facades' `confirmation` is (GAP-10 of
[`tui/engine-gaps.md`](tui/engine-gaps.md)), parses the line with a throwaway id factory,
as completion does, so asking uses up no id. The prompt adds `[y/N]`; `execute` never asks.

**Reconnects** (`busk.output.scheduler`, `busk.io.surfaces`). A route whose driver fails to
open is retried every 2 s by building a new driver; one whose status has failed for 1 s is
closed and opened again (its interface index and addresses are looked up at open), with
sequence numbers kept in the scheduler's shared `Sequences` and `ArtNetNetwork`, so they
continue across reopens and engine restarts. sACN and Art-Net drivers report a failure
until a send succeeds, so an outage prints once. Art-Net broadcast routes re-read their
broadcast address every 2 s and poll at once when it changes. MIDI has no unplug event in
rtmidi, so the surface manager and the feedback worker compare the port names every 2 s.

**The route status** (`busk.output.scheduler`; GAP-07 of
[`tui/engine-gaps.md`](tui/engine-gaps.md)). `LiveShow.routes` is
`OutputScheduler.route_status()`: every route of the show, in show order, as the public
`RouteStatus` (`ok`, `failed`, `disabled` or `ignored`, a detail, and the driver's packet
and error counters). Whenever its routes change (at construction, after a reconcile, and
when a retry opens a route or fails with another error), the output thread publishes them
by one reference assignment: the layout it follows, the open routes, and why each other
route is not sent, taken from `open_route`'s notice (`build_routes` hands its notices to
the scheduler for the routes it did not open). The reader adds each open driver's
`status()`, which is safe on any thread, so nothing is built while nobody reads. Under
`busk run` the output runs in the root: on each pass of its main loop (10 Hz) the root
sends the console a `ROUTES` message when the statuses differ from the last ones it sent,
and the last ones to a console that starts. The console's backend keeps them for its
attached show. With `--threads` the backend reads its own scheduler.

**The surface status** (`busk.io.surfaces`; GAP-08 of
[`tui/engine-gaps.md`](tui/engine-gaps.md)). `LiveShow.surfaces` is
`SurfaceManager.status()`: every surface of the show, in show order, as the public
`SurfaceStatus` (`ok`, `failed` or `ignored`, a detail, and a web remote's addresses). For
each surface it could not open, the manager keeps the reason its line gave (`open_midi`
returns it, as `OscSurface.open` and `WebSurface.open` do, and an unplugged device's is
`unplugged; waiting for it`), and for each web remote the addresses it printed. After a
reconcile, and after a hot-plug read that opened or closed a port, the supervisor builds the
tuple and publishes it by one reference assignment when it differs from the last one, so a
reader on any thread gets the same object while nothing changed; `close` leaves it as it
was. The surfaces run with the session, in `busk run`'s console process, so its attached
show has the status without a message from the root. The MIDI feedback ports, which the
feedback worker owns, are not part of it.

**Import** (`busk.importers`). The OFL importer builds each mode from its channels'
capabilities through a table (phase-7-plan §5.18): each capability becomes a range segment
of a busk attribute, unmapped ones become `control` channels at their `defaultValue`, and
each mode is validated alone (a mode that fails is skipped with a note), then the whole
profile. The GDTF importer reads `description.xml` from the archive with expat, refusing
any `DOCTYPE` (so no entity can be declared) and anything over 32 MB inflated, then maps
DMX modes, channel functions, wheels and emitters the same way, with GDTF's DMX notation
(`128/1` mirrored to `0x8080` on 16 bit) and CIE xyY converted to linear RGB. Both return
the profile and an `ImportReport` of notes.

**The event log** (`busk.persistence.eventlog`, `busk.replay`, §15.5). The engine appends
each applied item to a record deque in the drain, with the tick's time: a command
envelope, an install's *cause* (a show edit as its patch ops and label, a programmer
change as its new state, a connection's start with the whole state), or a restore. In
processes the engine host sends the records to the root every 100 ms, which writes them;
with `--threads` a `LogPump` thread does. Nothing in the tick does I/O, and a full deque
drops and counts (`logDropped`). A selection or a fade time, which installs nothing, rides
on the next install. `busk replay` rebuilds the session at each start record (and a new
engine when the start says the engine was fresh) and ticks at every logged time, so the frames equal the run's byte for byte.
