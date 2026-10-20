# Manual checklists

The checks each phase left to a person with the hardware: a controller, an sACN rig, a
phone, a machine that runs for a day. [`history.md`](history.md) explains the phases.

## Busking checklist (Phase 2)

The manual check of phase-2-plan §8 is the remaining step of Phase 2. It needs a
nanoKONTROL2 (or another controller, with the demo's bindings edited), and an sACN
receiver: fixtures through an sACN node, or sACNView / QLC+ / OLA (Wireshark with
`udp.port == 5568` dissects E1.31). Set the demo route's `iface` to your interface, patch
the rig as in the demo (spots at 1 and 17, pars at 33, 36, 39 and 42), then:

1. `busk run tests/fixtures/phase2-busk.json` prints no limitations, the route line, and the
   matched MIDI port.
2. Raise fader 1 slowly. Every fixture follows the fader, and warm white comes in once the
   fader passes 2 %. Pull the fader to 0: intensity drops with it, and the status line
   shows Warm going from `rel` to idle.
3. Raise fader 1, then press S3: everything fades to blue over 1 s. Press S4: red over
   1 s, and Blue goes `rel` → idle. Press S4 again: back to warm, **not** blue.
4. With Red up, hold M3 (flash Blue, `includeLtp`): everything is blue while held and
   exactly red again on release.
5. Raise fader 1, then press S6 and move fader 6: the heads move proportionally between
   their current position and Audience.
6. Hold M8: all white at full, over everything. Release it: the exact previous look
   returns.
7. Knob 8 scales all intensity. Holding ■ blacks out; releasing it restores the exact
   look.
8. MIDI → light latency feels immediate (worst case ~10 ms engine tick + ~23 ms output
   cycle).
9. Ctrl+C: the stats line shows 0 overruns and 0 command errors.

**Rehearsed without hardware** (no controller or rig at hand): a script played the
nanoKONTROL2 through a virtual ALSA port, ran `busk run` on a copy of the demo whose
surface matched that port and whose route sent unicast to 127.0.0.1, and read universe 1
from an sACN listener on port 5568. Steps 1–7 and 9 behave as written, byte for byte:

| Step | MH 1 R G B W / dimmer (16-bit) | Par 1 R G B | MH 1 pan / tilt |
|---|---|---|---|
| fader 1 at 2/127 (below 2 %): white, dimmed | 0 0 0 255 / 3·58 | 3 3 3 | centre |
| fader 1 at 3/127: warm white comes in | 140 76 0 115 / 4·214 | 5 4 2 | centre |
| fader 1 full: intensity 0.8 | 140 76 0 115 / 204·204 | 204 153 92 | centre |
| S3 (Blue), S4 (Red), S4 again | blue, red, then warm again (not blue) | | |
| hold M3 with Red up / release | 0 0 255 0, then exactly 255 0 0 0 | | |
| S6 + fader 6 at 64/127 | | | −15.1° / 20.2° (halfway to −30° / 40°) |
| hold M8 (Panic) / release | 0 0 0 255 / 255·255, then the look again | 255 255 255 | |
| knob 8 at 64/127 / hold ■ / release | dimmer 103·52 (0.40), 0·0, 204·204 | 103 0 0, 0 0 0, 204 0 0 | |

The status line followed every step (`… · 3 Blue rel · 4 Red on`, `… · 3 Blue flash · 4 Red
on`, `GM 50% | BO on | …`), the run ended with `0 overruns, 20 commands, 0 command errors`,
and the listener received 3 Stream_Terminated packets at the end. Step 8 needs the real
controller.

## Hardware checklist (Phase 1.5)

The manual check of phase-1.5-plan §8 is the remaining step of Phase 1.5. It needs a
wired link to an sACN → DMX node (or a fixture with native sACN) on universe 1, a copy of
the demo with the route's `iface` set to that interface, and the DMX chain patched as in
the demo: MH-X25 #1 at 1, MH-X25 #2 at 13, ML-56 at 25, COLORband PiX at 29. Then check:

1. `busk run <copy> --values tests/fixtures/phase1-values.json --console` prints the route line
   and the golden frame line, and no errors.
2. An sACN viewer (sACNView, QLC+) shows universe 1 from "Busk Console" with the show's CID
   and priority 100, carrying the golden values.
3. Wireshark (`udp.port == 5568`) shows 4 packets in about 70 ms, then a keep-alive about
   every 0.91 s, identical apart from consecutive sequence numbers. Wireshark decodes the
   E1.31 layers only with *Preferences → Protocols → ACN → Streaming DMX* enabled
   (`tshark -o acn.dmx_enable:TRUE -d udp.port==5568,acn`).
4. The looks: MH-X25 #1 full, red, gobo 3, pan 90° / tilt −45°; MH-X25 #2 pan mirrored,
   strobing at about 5 Hz (an estimate; time it on slow-motion video); ML-56 orange at 80 %
   with white off; the PiX's 12 cells alternating red and blue.
5. Ctrl+C: the node releases at once (Stream_Terminated). `kill -9` instead: it holds for
   about 2.5 s, then applies its data-loss behaviour. Unplugging the cable for a few
   seconds: the look is back within a second of plugging it in.

Record any difference from the chart-derived expectations in the profile, its golden and
its `notes` (a transcription error) or in the transcription notes above (an estimate).

**Verified without hardware** (the dev machine's wired interface had no carrier, and no
packet was sent onto the Wi-Fi LAN):

* Step 1's spike: `IP_MULTICAST_IF` with a Linux `struct ip_mreqn` (by interface index)
  and with an `in_addr` both work, and a socket that joined `239.255.0.1` on that
  interface receives the packet. No fallback was needed.
* A rehearsal of checks 1–3 and 5 over loopback (the demo with `iface: "lo"`, a listener
  joined on `lo`, port 5568): packets at 0, 23, 46 and 68 ms, keep-alives at 977 ms and
  1 886 ms, then 3 Stream_Terminated packets at Ctrl+C. Repeats and keep-alives differ
  from the first packet only in byte 111 (sequence), terminations only in bytes 111–112.
  Wireshark's dissector decodes every field and flags nothing.
* The E1.31 constants of plan decisions 4–5 (3 packets before suppression, a keep-alive
  every 800–1000 ms, 3 Stream_Terminated packets, the 2.5 s timeout) match the secondary
  sources checked and common sACN implementations. The standard's own text was not at
  hand; see *Still open* below.

## Programming checklist (Phase 3)

The manual check of phase-3-plan step 15 needs the Phase 2 setup (a nanoKONTROL2 and an
sACN receiver, the route's interface set with `--iface`):

1. `busk new club.show --title "Club Night"`, then `busk run club.show --script
   tests/fixtures/phase3-build.busk --iface <your interface>`: the script's lines, `saved
   club.show`, the route line, the matched MIDI port, then the prompt.
2. Busk as in the [Phase 2 checklist](#busking-checklist-phase-2): faders 1–8, S/M/R
   buttons, knob 8, ■. Everything behaves as in the hand-written demo (the washes and the
   PiX take the place of the RGB pars).
3. `blind on`, `sel group 1`, `set color 0 0.3 1`, `record preset color 1 merge` with
   Blue up: the stage changes live, playback 3 is untouched; `undo` brings the original
   blue back.
4. `quit` and save; `busk validate club.show` reports 0 errors and 0 warnings, and `unzip
   -p club.show show.json` shows group and preset references in the cues.
5. Start it again, set values, `kill -9` it, start it again: `recovered programmer with …`.
6. The run ends with `0 overruns`.

**Rehearsed without hardware**: steps 1 and 3–5 behave as written. Step 3 ran through a
pseudo-terminal, with the script's route sending unicast to 127.0.0.1 and an sACN listener
on port 5568: with Warm and Blue up the heads were RGBW `0 0 255 0` (the first wash `0 0
204 0`); blind programming left them; `record preset color 1 merge` turned them to `0 76
255 0` live (and the washes, since the preset is global, to `0 61 204 0`); `undo` restored
`0 0 255 0`. The run ended with 0 overruns. Step 5 is `test_recovery.py`. Steps 2 and 6
need the controller and the rig.

## Song checklist (Phase 4)

The manual check of phase-4-plan step 20 needs the Phase 3 setup (a nanoKONTROL2 and an
sACN rig, the route's interface set with `--iface`):

1. `busk new club.show --title "Club Night"`, `busk run club.show --script
   tests/fixtures/phase3-build.busk --duration 1`, then `busk run club.show --script
   tests/fixtures/phase4-song.busk --iface <your interface>`. `Ignored in Phase 5:` (`Ignored in
   Phase 4:` then) lists only what the show uses that waits for later phases (limits, soft
   pickup, …); with the Phase 3 build it lists nothing.
2. Knob 1 up: the Intro eases in over 3 s, the washes going blue. ▶: Verse, the heads
   coming in warm while they swing to the audience more slowly (4 s). Wait 8 s: the Pre
   fires by itself, the bar rising fast in amber and the washes dimming slowly. ▶: Chorus,
   everything white. Four seconds after it lands the Outro starts: the heads dim and drift
   back to centre over 6 s.
3. ◀◀ during the Outro: back to the Chorus (0.5 s), and it stays there.
4. With the Verse up, bring up Blue (fader 3): the heads turn blue. ▶ (Pre): they stay
   blue, because the Pre does not change their colour and tracked slots don't steal. ▶
   (Chorus) sets every colour: white.
5. Knob 2 up: the chase bounces across the washes in red, one step per beat (120 BPM).
   Tap "cycle" in time with music: it locks within two taps. Knob 3: ×½, ×2, … staying on
   the beat. `status` shows the tempo and multiplier.
6. ●: the song releases over 3 s.
7. `fade 2`, `sel group 1`, `set intensity 100%`: the heads fade up over 2 s. `clear`: they
   fade back.
8. The run ends with 0 overruns.

**Rehearsed without hardware**: step 1 runs as written and `busk validate club.show`
reports 0 errors and 0 warnings. The timings of steps 2, 3, 5 and 6 are the checkpoints
`test_song_stack.py` replays on a fake clock (from the saved show, frame for frame), and
step 4 was checked the same way: heads warm `(1, 0.75, 0.45)` in the Verse, blue with Blue
up, still blue after the Pre's GO, white after the Chorus's. Step 7 is covered by
`test_engine_programmer.py`. Watching it on a rig, with the controller in hand, is left.

## Effects checklist (Phase 5)

The manual check of phase-5-plan step 18 needs the Phase 3 setup (a nanoKONTROL2 and an
sACN rig, the route's interface set with `--iface`):

1. `busk new club.show --title "Club Night"`, then `busk run club.show --script
   tests/fixtures/phase3-build.busk --duration 1`, `busk run club.show --script
   tests/fixtures/phase4-song.busk --duration 1` and `busk run club.show --script
   tests/fixtures/phase5-effects.busk --iface <your interface>`. `Ignored in Phase 5:` lists
   nothing for this show.
2. Fader 1 up (Warm), fader 6 up (Audience). Knob 4 up: the heads circle around the
   audience position, a circle every two beats, MH 2 a quarter turn behind MH 1. Track ◀
   toggles the circle.
3. Knob 5 up: the washes pulse in a wave that travels across the four of them, once per
   beat.
4. Tap "cycle" in time with music: the circle and the pulse follow within a beat, without
   a jump.
5. Knob 7: both shrink and grow together (the "FX" size master). `master "Wash level"
   50%`: the washes at half; back to 100 %: unchanged.
6. Fader 1 down to 0 (Warm releases), knob 6 up: the bar shows a mirrored wave from both
   ends to the centre and back. While Warm is up, only the crests rise above it (HTP).
7. `sel fixture 101`, `set pan 0`: MH 1 stops moving across, still nodding in tilt.
   `clear`: it circles again.
8. Knob 1 up, then ▶ to the Chorus: the bar runs the colour cycle over its white. Four
   seconds after the Chorus lands, the Outro starts and the cycle carries on without
   restarting. ● releases the song: the cycle fades out over 3 s, still moving.
9. The run ends with 0 overruns.

**Rehearsed without hardware**: §8 of the plan runs as written on a fresh show (no
interface `eth0` on the dev machine, so no route opened): the three scripts succeed, there
is no `Ignored in Phase 5:` block, `list effects` lists Circle, Pulse, Wave and Rainbow
embedded from the library, four taps typed from a shell script moved Speed 1 to 127.7 BPM,
`list masters` showed FX at 50 % and Wash level at 100 %, the run ended with 0 overruns
and `busk validate club.show` reports 0 errors and 0 warnings. Steps 2–8 are the
checkpoints `test_effects_show.py` replays on a fake clock from the saved show: the
circle's and pulse's positions and levels at hand-computed times, FX and Wash level, the
taps, the bar's wave alone and under Warm, the programmer's pan, and the colour cycle
through the Outro and the release. Watching it on a rig, with the controller in hand, is
left.

## Surfaces checklist (Phase 6)

The manual check of phase-6-plan step 20 needs the Phase 3 setup (a nanoKONTROL2 and an
sACN rig, the route's interface set with `--iface`), a phone on the same network, and the
nanoKONTROL2's LED mode set to **External** with the KORG KONTROL Editor (in the factory
Internal mode the buttons light only while pressed):

1. `busk new club.show --title "Club Night"`, then `busk run club.show --script
   tests/fixtures/phase3-build.busk --duration 1`, the same with `phase4-song.busk` and
   `phase5-effects.busk`, and `busk run club.show --script tests/fixtures/phase6-surfaces.busk
   --iface <your interface>`. There is no `Ignored in Phase 7:` block. Open the printed
   `Web s-…` address on the phone: page 1 "Main" with its strips.
2. Fader 1 from the bottom to the top: Warm comes up. S1 and R1 light.
3. Marker ▶: the phone shows "Washes" and the S1 LED goes out. Move fader 1 down a little:
   nothing happens. Pull it to the bottom and up again: Wash Blue rises from 0, without a
   jump.
4. On the phone, drag Wash Blue to about a third. Move fader 1: nothing until it passes
   the phone's level, then it follows.
5. Hold M2: only the red washes are lit, and M2 lights. Release it: everything as before.
6. Fader 8 up slowly: the bar crossfades into blue as you move. Down slowly: into red.
   Stop halfway: the bar holds there.
7. ■: blackout stays on and the stop LED lights. ■ again: back.
8. Marker ◀ to page 1. On the phone, raise "Fade" to the middle and tap the song's `GOTO 4
   Chorus`: the Chorus fades in over about 2.5 s while Warm fades out.
9. Cycle LED: it flashes on the beat. Tap in time, or send MIDI clock from a DAW bound with
   `bind "<surface>" clock tap`: it follows.
10. Close the phone's browser while holding a FLASH on it: the flash goes off.
11. With hardware at hand: an Art-Net node shows up (`Art-Net: node …`) and its universe
    lights; an Enttec or DMXking interface outputs, and pulling and replugging its cable
    resumes output within a second.
12. The run ends with 0 overruns.

**Rehearsed without hardware**: §8 of the plan runs as written on a fresh show (no
interface `eth0` on the dev machine, so no route opened, and no nanoKONTROL2): the four
scripts succeed with no `Ignored in Phase 6:` block, the web surface prints its address,
`list pages` marks page 1, `page 2` turns the status line to `P2 Washes`, `busk validate`
reports 0 errors and 0 warnings, and a 5 s run of the saved show with every surface open
ends with 0 overruns (max tick 1.4 ms). Steps 2–8 and 10 are the checkpoints
`test_surfaces_show.py` replays on a fake clock from the saved show, with the controller's
CCs going through the binding resolver and the phone through the web API (step 10 also
over a real WebSocket); step 9's beat LED and MIDI clock are `test_feedback.py` and
`test_midi.py` (48 clocks through a virtual ALSA port), step 11 is `test_artnet_discovery.py`
(a fake node on localhost) and `test_dmxusb.py` (a pseudo-terminal unplugged and
replugged). The phone page was driven in headless Chromium: it builds its strips, a held
FLASH shows on its strip, a drag sends `SET_FADER` and shows 50 %, and BO latches.
Watching it on a rig, with the controller and a real phone in hand, is left.

## Hardening checklist (Phase 7)

The manual checks of phase-7-plan step 20. The soak needs a machine that will not sleep;
the rest needs the Phase 3 setup (a nanoKONTROL2 with its LEDs in External mode, an sACN
rig, the route's interface set with `--iface`), a phone on the same network, and for item 2
TupperDMX-Simul.

1. **The 24-hour soak.** With suspend disabled, `/dev/snd/seq` present and UDP 5568 and
   6454 free, run `uv run python bench/soak.py --hours 24 --report soak-24h.json`. The
   summary says **pass**: 0 output drops, every kill recovered, memory within bounds. Keep
   the report and, on a failure, the `soak-24h/` directory next to it (its event logs
   replay what the engine saw).
2. **TupperDMX on imported profiles.** Start TupperDMX-Simul (before or after busk: the
   show's unicast route leaves port 6454 to it), then:

   ```
   busk import ofl ~/Documents/TupperDMX/demo.show/fixtures/*.json --manufacturer TupperDMX --out /tmp/tdmx
   busk new /tmp/tdmx/tupper.show --title "TupperDMX demo"
   busk run /tmp/tdmx/tupper.show --library /tmp/tdmx --script examples/tupperdmx/build-ofl.busk
   ```

   Play the page: the simulator shows the same looks as with the hand-transcribed build
   (`examples/tupperdmx/build.busk`), except the smoke machine's dead band (intensity above
   0 starts at DMX 8).
3. **The safety show on the Phase 3 rig**, built by `examples/club-night.busk` (as in the
   [quick start](../../README.md#quick-start), with `--iface`):
   - Fader 1 up: wash 4 stays dark and wash 3 red, whatever is played. The bar never goes
     above half.
   - The song's Chorus: the heads tilt no higher than 10°. The Circle flattens at the top.
   - Page 2, fader 5 (Strobe): the heads strobe at about 3 Hz, not 10. Fader 6 (Fast
     pulse): the washes pulse about 3 times a second.
   - `sel fixture 102`, `highlight on`: MH 2 lights white and full at any grand master.
     Blackout still darkens it. `highlight off`.
4. `info` gives the engine's pid. `kill -9` it while a look and the Circle run: the stage
   freezes and does not go dark; within about 3 s the look is back and the Circle runs
   again, on the beat; the faders work again after crossing their levels.
5. `kill -9` the console's pid: the show runs on, a new prompt appears within seconds, and
   the phone reconnects by itself.
6. Unplug the nanoKONTROL2 for 5 s and plug it back in: `unplugged`, then `connected`. The
   LEDs show the state again.
7. Unplug the network cable of the sACN route for 10 s: `send failed`, then `sending
   again`. The rig follows.
8. Marker SET (`release all`): every playback releases. `output off` (confirm with `y`):
   the rig's receivers let go. `output on`: back.
9. A run with `--stats stats.jsonl` ends with 0 late output cycles in its last line and
   the restarts you caused.

**Rehearsed without hardware** (2026-10-16, on the dev machine: no `eth0`, so no route
opened, and no nanoKONTROL2): plan §8 runs as written on a fresh show. The five scripts
succeed with no `Ignored in Phase 7:` block, `busk validate` reports 0 errors and 0
warnings, and a run in processes with `--stats` names three pids in `info`; after `kill -9`
of the engine it prints `engine: restarted (killed by signal 9)` and `engine back: …`,
`info` shows a new engine pid and `restarts: engine 1`, `list park` lists 204 and 203, and
the run ends with 0 overruns and `1 restart`. `busk import ofl` imports the five TupperDMX
files and `busk replay` replays the run's logs. Items 3 and 8 are the checkpoints
`test_safety_show.py` replays from the saved show; item 4 is `test_watchdog.py` against an
sACN receiver, item 5 `test_console_restart.py` with a WebSocket client as the phone, item
6 `test_hotplug.py` (a virtual ALSA port created and destroyed), item 7 `test_reconnect.py`,
and item 1 ran for 1 hour (pass; see the [benchmarks](benchmarks.md#the-soak)). Watching it on a rig,
and the 24 hours, are left.

## Library checklist (Phase 8)

Before tagging `v0.1.0` (phase-8-plan step 13):

1. **Install from GitHub into another project.** In a new directory:
   `git clone https://github.com/lothwen/busk.git`, `uv init app && cd app`, then
   `uv add ../busk --extra midi`.
   `uv run busk --version` prints `busk 0.1.0`, and
   `uv run python -c "import busk; print(busk.load_show)"` works.
2. **The guide's examples** ([`docs/library.md`](../library.md)) run there unchanged, from a
   copy of `examples/` and `tests/fixtures/`.
3. **TupperDMX through `LiveShow`.** Start TupperDMX-Simul. In
   Python: `show, _ = busk.load_show("examples/tupperdmx/tupper-demo.show")`, then
   `with busk.LiveShow(show) as live: live.execute("fader 1 1")`, and wait a few seconds in
   the block. The simulator shows the look, and lets go when the block ends.
4. **Without the extra.** In a second project, `uv add ../busk`. `busk run` on
   the Phase 3 show prints `MIDI s-…: unavailable: install busk[midi]` and runs on.
5. **Read [`docs/library.md`](../library.md) as a newcomer would.** Fix anything unclear
   before the tag.
6. **Tag and push:** `git tag -a v0.1.0 -m "busk 0.1.0: the first release with a public API"`,
   `git push origin v0.1.0`, and date the `0.1.0` entry of [`CHANGELOG.md`](../../CHANGELOG.md).
   A fresh `git clone --branch v0.1.0` installs as in item 1.
