# The demo show

[`examples/club-night.busk`](../examples/club-night.busk) builds a complete busking show
with console commands only: two moving heads, four RGBW washes and an LED bar on universe
1, looks and bumps, a song, a chase, effects, a second page, a phone remote, controller
LEDs and safety limits. It is played from a **Korg nanoKONTROL2** in its factory CC mode
and from a phone. The script's header maps every control it binds.

[`examples/festival.busk`](../examples/festival.busk) is a bigger one: a festival main
stage of 54 fixtures on TupperDMX's simulated rig, which uses every feature of busk that
rig can show. See [The festival show](#the-festival-show).

- [Building it](#building-it)
- [The rig](#the-rig)
- [Page 1: looks and bumps](#page-1-looks-and-bumps)
- [The song and the chase](#the-song-and-the-chase)
- [Effects](#effects)
- [Page 2, the phone and the LEDs](#page-2-the-phone-and-the-leds)
- [Safety](#safety)
- [A tour](#a-tour)
- [The festival show](#the-festival-show)
- [Other examples](#other-examples)

## Building it

```bash
busk new club.show --title "Club Night"
busk run club.show --script examples/club-night.busk --iface eth0
```

Run the script once, on a new show: it builds and saves `club.show`, and from then on
`busk run club.show --iface eth0` plays it. Set `--iface` to the interface that reaches
your sACN node (`ip -br link`; see [Output](output.md#choosing-the-network-interface)).
Check the controller's CC numbers with `aseqdump -p nanoKONTROL2`; another controller
works by editing the bindings.

## The rig

2 Generic Spot 16ch moving heads (fixtures 101–102), 4 Eurolite ML-56 RGBW washes
(201–204) and a Chauvet COLORband PiX bar (301, 12 cells) on universe 1, sent over sACN.
Groups Heads (1), Washes (2), Bar and All; colour presets Blue, Red, Green, Amber (global)
and position presets Audience and Centre (per head).

## Page 1: looks and bumps

| Slot | Playback | Content | Fader | Exclusivity |
|---|---|---|---|---|
| 1 | Warm | All: intensity 0.8, warm white | master, LTP at 2 % (`threshold`) | base |
| 2 | Cool | All: intensity 0.8, cool white | master, `threshold` | base |
| 3–5 | Blue / Red / Green | All: colour preset, 1 s fade | master, `threshold` | color |
| 6–7 | Audience / Centre | Heads: position preset, 2 s fade | master, `followFader` | position |
| 8 | Panic | All: intensity 1, white, band 200 | none | — |

| Control | CC | Action |
|---|---|---|
| Faders 1–8 | 0–7 | playback fader (`autoStart` on leaving 0, `autoRelease` at 0) |
| S buttons | 32–39 | `toggle` |
| M buttons | 48–55 | `flash` (while held; colours, positions and Panic bring their LTP values) |
| R buttons | 64–71 | `release` |
| Knob 8 | 23 | grand master |
| ■ (stop) | 42 | blackout on and off |

Base looks carry the intensity; bumps carry only colour or position and layer on top.

## The song and the chase

The script's second part adds slots 9 and 10 and binds the nanoKONTROL2's free knobs and
transport buttons:

| Slot | Playback | Content |
|---|---|---|
| 9 | Song | Tracking stack, `go`/`back`/`release` buttons, base exclusivity, 3 s release. 1 Intro: washes 60 % blue, 3 s `easeInOut`. 2 Verse: heads 70 % warm on Audience, 2 s, positions 4 s. 3 Pre (`wait 8`): bar 100 % amber, washes down to 30 %, 1 s in / 3 s out. 4 Chorus: everything 100 % white, 0.5 s in / 2 s out. 5 Outro (`follow 4`): heads 20 %, pan and tilt released, 6 s |
| 10 | Chase | Washes 201–204 one at a time in red, `bounce`, one step per beat of Speed 1 (×1), crossfade 0.25 |

| Control | CC | Action |
|---|---|---|
| Knob 1 / knob 2 | 16 / 17 | Song / Chase fader |
| ▶ (play) | 41 | GO the song |
| ◀◀ (rewind) | 43 | BACK |
| ● (record) | 45 | release the song |
| ▶▶ (fast-forward) | 44 | chase on/off (its first button, `toggle`) |
| cycle | 46 | tap tempo on Speed 1 |
| Knob 3 | 18 | Speed 1's multiplier: ×¼, ×½, ×1, ×2, ×4 across the knob |

Tapping locks within two taps: every tap moves the beat grid onto the tap, and from the
second tap on the tempo follows the taps, so a BPM chase steps on them.

## Effects

The script's third part adds a size master "FX", a group master "Wash level" on group 2, three effect-only slots and a colour cycle in
the song's Chorus. Each slot's cue holds one effect and no values, so its playback has a
`size` fader: the knob scales the effect's size, and the effect starts when the knob
leaves 0 and stops at 0.

| Slot | Playback | Effect |
|---|---|---|
| 11 | Circle | Heads: pan and tilt `add` sine, 15°, ×0.5 on Speed 1 (a circle every 2 beats), MH 2 a quarter turn behind MH 1, growing over 1 s, scaled by "FX" |
| 12 | Pulse | Washes: intensity `multiply` sine, size 0.8 (down to 20 % of the look below), once per beat, a wave across the four, scaled by "FX" |
| 13 | Bar wave | Bar: intensity `absolute` sine 0..1, once per beat, mirrored from both ends (`wings 2`); over a look, only its crests show (HTP) |
| 9/4 | Chorus (Song) | Bar: a red → green → blue cycle at 0.25 Hz, around the 12 cells; it tracks into the Outro |

| Control | CC | Action |
|---|---|---|
| Knobs 4 / 5 / 6 | 19 / 20 / 21 | Circle / Pulse / Bar wave size |
| Knob 7 | 22 | "FX" size master |
| track ◀ / track ▶ | 58 / 59 | Circle / Pulse on and off |

A tap keeps every BPM effect where it is and closes the gap to the new beat grid over one
beat, so nothing jumps and one beat later the effect is on the beat again.

## Page 2, the phone and the LEDs

The script's fourth part turns on soft takeover for the nanoKONTROL2, adds a web surface
"Phone" and a fade-time master "Fade", and builds a second page:

| Page 2 "Washes" | Playback | Content |
|---|---|---|
| 1–4 | Wash Blue / Red / Green / Amber | Washes at 100 % in colour preset 1–4; exclusivity `wash` (one at a time); buttons `toggle`, `swop`, `release` |
| 5 / 6 | Strobe / Fast pulse | Heads strobing at 10 Hz / washes pulsing at 8 Hz, both held at 3 Hz by the strobe cap (see [Safety](#safety)) |
| 8 | Manual | Bar at 100 %: cues 1–3 blue, red, green, `wrap`; a `crossfade` fader; buttons `go`, `back`, `release` |
| 9–13 | Song, Chase, Circle, Pulse, Bar wave | The knob playbacks of page 1, on the same knobs |

The song gets a fourth button, `goto` its Chorus (`playback 9 goto 4`), which the phone
shows. The controller turns the pages and lights its LEDs (set the nanoKONTROL2's LED mode
to **External** with the KORG KONTROL Editor; in the factory mode a button lights only
while pressed):

| Control | CC | Action, LED |
|---|---|---|
| marker ◀ / marker ▶ | 61 / 62 | previous / next page |
| S, R buttons | 32–39, 64–71 | LED: the slot's playback is active |
| M buttons | 48–55 | LED: its flash is up, or its swop held |
| ▶, ◀◀, ● | 41, 43, 45 | LED: the song is active |
| ■ | 42 | LED: blackout is on |
| ▶▶ | 44 | LED: the chase is active |
| cycle | 46 | LED: the beat of Speed 1 |

[Surfaces](surfaces.md) explains pages, soft takeover, swop, crossfade faders and the
fade-time master.

## Safety

The script's last part limits the heads' tilt to 10° (a low truss) and the bar to half,
parks wash 4 dark and wash 3 on red, caps strobes at 3 Hz, and binds marker SET (CC 60) to
`release all`. See [Safety](safety.md).

## A tour

After the build, each run below starts from the saved show. Lines starting with `#` are
what busk prints.

```bash
busk run club.show                           # the song and the chase
busk> list cues 9
#     1  Intro                time 3 easeInOut  go
#     2  Verse                time 2, position 4  go
#     3  Pre                  time 1/3  wait 8
#     4  Chorus               time 0.5/2  go  1 effect
#     5  Outro                time 6  follow 4
busk> fader 9 1                              # the Intro eases in over 3 s
busk> go 9                                   # Verse: the heads swing out over 4 s; Pre fires 8 s later
busk> status
# GM 100% | BO off | P1 Main | Speed 1 120 BPM ×1 | 9 Song on 2 Verse 1.00
busk> fader 10 1                             # the chase bounces across the washes on the beat
busk> tap                                    # four taps at 128 BPM: the chase follows them
busk> list masters
# Grand Master         grand   100%
# Speed 1              speed    50%  128 BPM ×1
# FX                   size    100%
# Wash level           group   100%
# Fade                 fadeTime    0%
busk> quit

busk run club.show                           # the effects
busk> list effects
# Circle               pan add sine, tilt add sine +90°
# Pulse                intensity multiply sine
# Wave                 intensity absolute sine
# Rainbow              color fade 3 colours
busk> fader 1 1                              # Warm
busk> fader 6 1                              # the heads on the audience
busk> fader 11 1                             # the heads circle, growing over 1 s, on the beat
busk> fader 12 1                             # the washes pulse in a wave
busk> tap                                    # ×4 in time: both follow without a jump
busk> master "FX" 50%                        # both at half size
busk> list masters
# Grand Master         grand   100%
# Speed 1              speed    50%  128 BPM ×1
# FX                   size     50%
# Wash level           group   100%
# Fade                 fadeTime    0%
busk> status
# GM 100% | BO off | P1 Main | Speed 1 128 BPM ×1 | 1 Warm on 1.00 · 6 Audience on 1.00 · 11 Circle on 1.00 · 12 Pulse on 1.00
busk> quit

busk run club.show                           # pages, the phone, LEDs
busk> list pages
# *   1  Main                 1:1 2:2 3:3 4:4 5:5 6:6 7:7 8:8 9:9 10:10 11:11 12:12 13:13
#     2  Washes               1:14 2:15 3:16 4:17 5:19 6:20 7:- 8:18 9:9 10:10 11:11 12:12 13:13
busk> page 2                                 # the phone shows "Washes"; the faders take over softly
busk> status
# GM 100% | BO off | P2 Washes | Speed 1 120 BPM ×1
busk> list surfaces
# s-…  midi 'nanoKONTROL2' device 'nanoKONTROL2', soft pickup
# s-…  web 'Phone' port 8080
busk> master "Fade" 50%                      # cue and release times become 2.5 s
busk> status
# GM 100% | BO off | P2 Washes | Speed 1 120 BPM ×1 | Fade 2.5 s
busk> quit

busk run club.show                           # safety: limits, park, a strobe cap, panic
busk> fader 1 1                              # Warm: wash 4 stays dark, wash 3 red, the bar at half
busk> list park
# 204 intensity 0
# 203 color 1 0 0
busk> sel fixture 102
busk> highlight on                           # MH 2 at full white, whatever the look and the GM
busk> highlight off
busk> output off                             # at the prompt it asks: Turn all DMX output off? [y/N]
busk> status
# GM 100% | BO off | OUT off | P1 Main | Speed 1 120 BPM ×1 | 1 Warm on 1.00
busk> output on
busk> info
# …
# processes: root 96567, engine 96595, console 96597
# restarts: engine 0, console 0
# event log: ~/.local/state/busk/logs/show-…/20261016T170345436622Z.log
#   (another terminal: kill -9 96595)
# engine: restarted (killed by signal 9)                           (the output held the last frame)
# engine back: restored 1 playback, 5 master levels, page 1
busk> release all 2                          # every playback, over 2 s
busk> quit
# engine: 578 ticks @ 100 Hz, 0 overruns, max tick 1.573 ms, 1 command, 0 command errors, 1 restart   (the last engine's counters)
```

## The festival show

[`examples/festival.busk`](../examples/festival.busk) builds a festival main stage on the
TupperDMX profiles: three songs, busking pages for colours, positions, effects, strobes and
the house, an emergency pair on every page, a web remote and a nanoKONTROL2. It uses every
feature of busk that this rig can show, each where a festival LD would use it. The script's
comments say why each one is there, and its header maps the controller.

### Building it

```bash
busk new festival.show --title "Festival Main Stage"
busk run festival.show --script examples/festival.busk
```

Run it from the repository's top folder: the script imports the TupperDMX profiles from
`examples/tupperdmx/profiles/`, and `festival.show` keeps a copy of each. The output goes over
Art-Net to TupperDMX's simulator on 127.0.0.1; the web remote's **3D** button shows the
stage without it.

### The rig and the pages

54 fixtures on universe 1, 506 of its 512 channels: 12 spots and 12 washes (the same moving
head), 16 RGBW PARs, 8 LED bars, 8 blinders and 2 smoke machines, on a FOH truss, three
trusses over the stage, the upstage floor and the downstage lip. Page P, slot S holds
playback P·100+S.

| Page | What it holds |
|---|---|
| 1 Songs | Songs 1–3 (tracking stacks with GO, BACK and GOTO), Busking FX and Special Looks |
| 2 Colors | Ten colours, three colour effects and a colour chase, one at a time |
| 3 Positions & Beams | Positions 1–7, crossfaded by the fader, and beams 1–8, snapping in at half way |
| 4 Movement FX | Six movements on the spots, five on the washes, one per type at a time |
| 5 Dimmer FX | Eleven dimmer effects, sized by their faders and "FX Size" |
| 6 Strobes & SFX | Strobes, the Blinder Hit (with a swop), smoke, the LED bars' own programs |
| 7 House & Audience | House lights on a crossfade fader, audience lighting, blinders, the MC light |

Slots 9 and 10 of every page hold HOUSE FULL and PANIC WORK LIGHT, at band 200.

### What it uses, and where

| Feature | Where |
|---|---|
| `profile import`, `profile … category` | The five TupperDMX profiles |
| `fixture … location` | Every fixture, for the web remote's 3D view |
| `orientation.invertPan` | The floor washes, which stand: a positive pan turns every head the same way on stage |
| Elements in a selection and a group | Group 40, the audience blinders' warm cells |
| `sel +`, `sel -` | Group 9 (Full Stage); PANIC's shutters (everything but the LED bars) |
| `set … spread`, `center` | Every position preset; Song 3's Solo, recorded as one spread on group 35 |
| `set color.r`, `set … by`, `w` | Deep Blue and Lavender, mixed from Blue and Magenta; Warm White drives the white LEDs |
| `set <attribute> preset …` | Song 3's Solo: the Gobo 2 star in the Soft Beam |
| Presets in five pools | Colour, position (per truss), beam, intensity, and an `all` preset, MC Wash |
| Masters | Beat and Move Speed (with `steps`), Move Size and FX Size, a group master per fixture type, Fade |
| The effect library, template defaults | All thirteen library templates; the songs' settings kept as defaults, so most `effect add` lines name only an id |
| A layer's `cycles` | Figure eight (the library's, ×2) and Ballyhoo (the show's own, ×3) |
| Waveforms | Sine, triangle, square, saw, pulse (Kick), step (Build), random, curve (Heartbeat), colour palettes |
| An effect on a beam attribute | Zoom Breathe, in Busking FX |
| `reverse`, `bounce`, `groups`, `blocks`, `wings`, `fadein`, speed and size masters | Busking FX, pages 4 and 5 |
| Tracking, releases, `releaseAtEnd` | The three songs: a release stops an effect, GO after the last cue releases the song |
| A point cue | Song 1's 2.5 Riser |
| A block cue | Song 1's Breakdown: recorded, made a block, then recorded again with `merge` |
| Family timing, curves, split fades and delays | Every song; the Ballad eases in and out, its Solo fades 4/6 with a delay |
| Timing per target, fans | Song 1's Build Up (`edges`), Song 2's Intro, the Walk-in (a fan of fades), the Audience Hit (`center`) |
| `wait`, `follow` | Song 2's Chorus Hold, Song 3's Blackout |
| A Bézier curve | The house fades |
| `cue … effect <id> …` | Song 1's Final Drop (a size touch-up), Busking FX 5.5 (an effect removed) |
| `cue … copy`, `load cue`, `record … replace`, `rename cue` | Busking FX 5.5; Special Looks 6 (Song 1's Breakdown, copied in) and 7 (Blue Silhouette) |
| `record … only`, `freeze` | Pages 2 and 3; HOUSE FULL and PANIC |
| `record slot`, `number` | The MC light, renumbered to 704 |
| A cue-list chase, `wrap` | Page 2's Colour Step (random, on the beat, with a crossfade); Busking FX and Special Looks |
| Faders: `master`, `size`, `rate`, `crossfade`, `temp`, `none` | Most playbacks, the effect pages, Colour Step, House Lights, Audience Blinders, the emergency pair |
| Buttons: `go`, `back`, `goto`, `toggle`, `flash`, `swop`, `release`, `select` | Page 1, the other pages, the Blinder Hit, the MC light |
| LTP modes | Positions follow the fader, beams snap in at half way (`ltpThreshold`), Special Looks ignore it |
| A flash's level, LTP and band | Audience Blinders hit at 60 %, the MC light's flash brings no LTP, the Blinder Hit's plays at band 150 |
| Exclusivity, priority, `protectFromSwop`, auto start and release, release times | Every page; the emergency pair at band 200 |
| `uiColor`, `notes`, `tags` | Page 2, the strobes and the emergency pair in their colours; the emergency pair's notes; the songs' tags |
| Safety | A 10 Hz strobe cap, a tilt limit on the hung spots, an 80 % limit on the audience blinders, spot 112 parked |
| Surfaces, bindings, feedback | The web remote; the nanoKONTROL2's faders, buttons, masters, tap, blackout (latched and momentary), pages, `release all`, LEDs and soft takeover |

It leaves out what the rig, the controller or a script cannot show:

- The attributes the TupperDMX profiles lack: focus, iris, frost, CTO, the colour wheel,
  colour macros and effects, gobo 2, prism rotation and position speed, and with them the
  `focus` preset pool.
- What the nanoKONTROL2 does not send in CC mode: OSC, MIDI notes, pitch bend and clock,
  motor and display feedback, and `fader playback N`, which it has no spare control for.
- sACN and DMX USB routes (the script's output section says how to switch), and `route <id>
  …`, whose id a script cannot know.
- A colour palette entry that names a preset: the template's JSON takes the preset's id,
  which a script cannot know either.
- `profile update` and mode changes: each TupperDMX profile has one revision and one mode.
- `rig check` and `rig import`: the rig is patched by the script's lines, not drawn in a CAD
  plot.
- Lines that work on a running show rather than build it: the tour below shows them.

### A tour of the festival show

```bash
busk run festival.show                         # the songs
busk> list cues 101
#     1  Intro                time 3 easeInOut, position 0  go
#     2  Build Up             time 2, position 4, color 1, beam 0.5, group 35 intensity 2 delay 0 to 1.5 edges  go  1 effect
#   2.5  Riser                time 1  go  1 effect
#     3  Drop                 time 0/2, position 1, color 0, beam 0  go  1 effect
#     4  Verse                time 2, position 4, color 1, beam 0.5  go
#     5  Chorus               time 1, position 2, color 0.5, beam 0  go  3 effects
#     6  Breakdown            time 4, position 3, color 3, beam 1  go  block
#     7  Final Drop           time 0/3, position 0.5, color 0, beam 0  go  2 effects
busk> list cue 101/6                           # a block cue: its whole look, nothing tracked
# cue 101/6 'Breakdown', a block cue
#   101  intensity 'Dimmer 25%'  pan 'Spots Upstage'  tilt 'Spots Upstage'  color 'Deep Blue'  gobo1 'Gobo 2'  …
#   …
#   601  intensity 50%
#   602  intensity 50%
busk> fader 101 1                              # the Intro eases in over 3 s
busk> go 101                                   # Build Up: the back PARs come in from the centre out
busk> go 101                                   # Riser: they step up on every beat
busk> status
# GM 100% | BO off | P1 Songs | Beat 128 BPM ×1 · Move Speed 120 BPM ×1 | 101 Song 1 Opener on 2.5 Riser 1.00
busk> list effects                             # the library's templates with the show's defaults, and its own
# Circle               pan add sine, tilt add sine +90° (bpm "Beat" x 0.25, size 15, phase 0 360)
# Figure eight         pan add sine, tilt add sine ×2 +90° (bpm "Beat" x 0.5, size 15, phase 0 180, groups 2)
# …
# Ballyhoo             pan add sine, tilt add sine ×3 +90° (bpm "Beat" x 0.125, size 20, phase 0 180, groups 2)
# …
busk> quit

busk run festival.show                         # live edits, each one undo step
busk> list park
# 112 pan 0
# 112 tilt 0
busk> unpark fixture 112                       # the techs fixed it
# unparked fixture 112
busk> sel group 31
# 6 targets selected
busk> preset position 1
# Spots Center Stage: 12 values on 6 targets
busk> undo group "focus"                       # nudges, undone together
# undo group "focus" is open
busk> set pan by 5
# pan: 6 targets
busk> set pan by 5
# pan: 6 targets
busk> set tilt by -3
# tilt: 6 targets
busk> undo group end
# closed undo group "focus": 3 steps, undone as one
busk> undo
# undid: focus
busk> sel group 4
# 16 targets selected
busk> effect add "Kick" id k                   # a kick on the PARs, on the beat
# added effect 'k' on 16 targets
busk> effect stop k                            # kept, with its settings, until it runs again
# stopped effect 'k'
busk> effect run k
# started effect 'k'
busk> clear
# programmer cleared
busk> sel playback 704                         # the MC light's fixtures, to touch up its focus
# 20 targets selected
busk> delete group 35 cascade                  # it asks first, naming what would lose the group:
                                               # Delete group 35 "Back PARs"? It leaves cues 101/2, 101/2.5, … 701/3. [y/N]
busk> output off                               # it asks: Turn all DMX output off? [y/N]
busk> status
# GM 100% | BO off | OUT off | P1 Songs | Beat 128 BPM ×1 · Move Speed 120 BPM ×1
busk> output on
busk> release all 2                            # every playback, over 2 s
busk> quit
```

In the TUI (`busk-tui festival.show`, see [the TUI guide](tui/guide.md)), F4's TRACK panel
draws a song cue's look: on cue 101/5, the washes' Wide Beam is dim, tracked from 101/4,
and on cue 101/6 nothing is, and `[block]` is lit. F9's MONITOR lists what the nanoKONTROL2
sends; `[learn]` on it, then a control moved, puts its `bind "nanoKONTROL2" cc 1 …` line in
the prompt.

## Other examples

- [`examples/tupperdmx/`](../examples/tupperdmx/): the TupperDMX demo rig as a busk show
  (eleven fixtures: moving heads, RGBW pars, an LED bar, blinders and a smoke machine), a
  page of looks and a web remote, sent over Art-Net to TupperDMX's simulator on
  127.0.0.1. `build.busk` builds it from hand-transcribed profiles, `build-ofl.busk` from
  the fixtures' OFL files.
- [`examples/real-fixtures.json`](../examples/real-fixtures.json): the three real fixtures
  of the [built-in library](profiles.md#the-built-in-library), as a show file.
- The test suite builds the club-night show in five steps, from the scripts in
  [`tests/fixtures/`](../tests/fixtures/), and checks the DMX it sends at every step.
