# The demo show

[`examples/club-night.busk`](../examples/club-night.busk) builds a complete busking show
with console commands only: two moving heads, four RGBW washes and an LED bar on universe
1, looks and bumps, a song, a chase, effects, a second page, a phone remote, controller
LEDs and safety limits. It is played from a **Korg nanoKONTROL2** in its factory CC mode
and from a phone. The script's header maps every control it binds.

- [Building it](#building-it)
- [The rig](#the-rig)
- [Page 1: looks and bumps](#page-1-looks-and-bumps)
- [The song and the chase](#the-song-and-the-chase)
- [Effects](#effects)
- [Page 2, the phone and the LEDs](#page-2-the-phone-and-the-leds)
- [Safety](#safety)
- [A tour](#a-tour)
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
