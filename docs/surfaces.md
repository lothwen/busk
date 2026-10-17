# Control surfaces

A show is played from **surfaces**: MIDI controllers, OSC devices and apps, and the web
remote a phone opens over Wi-Fi. Each surface's **bindings** turn its inputs into
commands (a fader drives a playback, a button GOes a cue list), and **feedback** sends the
show's state back to LEDs, motor faders and labels. The console's
[`surface`, `bind` and `feedback` commands](console.md#commands) set them up;
[the demo show](demo-show.md) binds a Korg nanoKONTROL2 and a phone.

- [MIDI](#midi)
- [OSC](#osc)
- [The web remote](#the-web-remote)
- [Feedback](#feedback)
- [Pages](#pages)
- [Faders and buttons](#faders-and-buttons)
- [Rate limits](#rate-limits)

## MIDI

MIDI needs the `midi` extra (`busk[midi]`, see the [README](../README.md#install)); without
it each MIDI surface reports `MIDI s-…: unavailable: install busk[midi]` once and stays
closed. On Linux MIDI uses the ALSA sequencer (`/dev/snd/seq`); `aseqdump -l` lists the
input ports, and `aseqdump -p <port>` shows what a controller sends.

```
busk> surface add midi "nanoKONTROL2"
busk> bind "nanoKONTROL2" cc 1 0 fader 1           # CC 0 on channel 1 → page fader 1
busk> bind "nanoKONTROL2" cc 1 32 button 1 1 led   # CC 32 → slot 1's first button, with its LED
```

- Each `midi` surface opens the first input port whose name contains its
  `match.deviceName` (case-insensitive) and prints `MIDI <surface>: <port>`. If none
  matches, it prints the ports that exist, on stderr.
- A surface with feedback bindings also opens the matching output port (`MIDI <surface>
  feedback: <port>`).
- Inputs are control changes (`cc`), notes (`note`) and pitch bend, on channels 1–16.
  Buttons act on their edges, so a repeated CC 127 is one press, and any note velocity
  presses.
- **MIDI clock.** `bind "<surface>" clock tap` taps a speed master once per beat (24
  clocks), so a DAW or a drum machine sets the tempo; Start and Song Position set the count.
- **Hot-plug.** The surfaces read the MIDI port names every 2 s. A controller unplugged
  prints `MIDI s-nano: unplugged; waiting for it` (stderr), and plugged back in `MIDI s-nano:
  nanoKONTROL2:nanoKONTROL2 _ CTRL 20:0 (connected)`. A controller missing at start-up
  opens when it appears. Feedback ports do the same and get a full send, so the LEDs show
  the state again.

## OSC

```
busk> surface add osc "Touch" port 8000 feedback 10.0.0.5:9000
busk> bind "Touch" osc "/fader/1" fader 1 display osc "/label/1"
```

Each `osc` surface listens on its UDP port, 8000 by default (`OSC <surface>: listening on
udp 8000, feedback to the sender`). An input is an address (`osc "/fader/1"`); the
message's first argument is its value, clamped to 0..1 (`T`/`F` are 1 and 0), and a
message without arguments is a press and a release. Bundles are unpacked. Feedback goes to
`match.host`:`match.feedbackPort` (`feedback HOST:PORT`), or to the sender's address and
port for the part left out, as `/address <float>` (or a string for `display`).

## The web remote

```
busk> surface add web "Phone"
```

Each `web` surface serves a phone page on its port (8080 by default) and prints one line
per IPv4 address of the machine:

```
Web s-…: http://192.168.1.20:8080/?k=…
```

Open it on a phone on the same network. The key in the address is created once in
`<state dir>/web-key` (mode 0600), and every request needs it; requests from a page on
another site are refused.

The page shows the current page's strips (a fader to drag, the buttons by function, the
current cue and, in a stack, the cue GO goes to next); the header has the page arrows,
the page name (tap it to choose a page from a list), blackout, the first grand master, TAP
with the tempo and a beat dot, the other masters and the fade time. On a phone held
sideways the header takes one row, each fader sits beside its buttons, and the masters
open with the **Masters** button. While `output off` holds, a red OUTPUT OFF bar says so.
It sends the same commands as a controller, so both drive the show together, and it
reconnects by itself (after a console restart too).

A phone sends **performance commands only**: it plays the show but cannot edit it or the
programmer. The buttons it holds are released when it disconnects, so a phone that loses
Wi-Fi in the middle of a flash does not leave the flash up.

## Feedback

A binding with a feedback (`led`, `motor` or `display`) shows its action's state:

- an **LED** is lit while its playback is active, or for a flash button while the flash is
  up, a `swop` button while held, a `goto` button while the playback is at that cue, a page
  button while there is a page that way, a tap button for the first quarter of each beat,
  and blackout while on;
- a **motor fader** follows the level, and is held still for 0.5 s after it was moved by
  hand, so the motor never fights a finger;
- a **label** (`display`, OSC only) shows the name.

Feedback is sent 30 times a second, only what changed. `feedback "<surface>" cc 1 32 thru
39 led` adds feedback to bindings already on those inputs (`none` removes it).

On a Korg nanoKONTROL2, set the LED mode to **External** with the KORG KONTROL Editor;
in the factory mode a button lights only while pressed.

## Pages

Playbacks sit in the slots of **pages**. Page faders and buttons drive the slots of the
**current page**, so one controller plays several pages of playbacks.

- The current page is one for every surface: the controller, the phone and the console
  (`page 2`, `page next`) turn the same page, and the status line and the phone show it.
- Page buttons (`bind … page +1`, `… page 2`) stop at the first and last page.
- A flash held through a page change stays on its playback until released.

## Faders and buttons

**Soft takeover.** On a surface with `pickup soft` (`surface "nanoKONTROL2" pickup soft`),
after a page change, or after the phone or the console moved the playback, a fader does
nothing until it reaches the playback's level, within 2 %, or crosses it; then it follows.
Masters on knobs take over the same way. With `pickup jump` (the default) a fader jumps the
level to where it is.

**Button functions.** A playback's buttons (`playback 1 buttons ["toggle", "flash",
"release"]`) each have a function: `go`, `back`, `toggle`, `release`, `goto` (to the
playback's goto cue, `playback 9 goto 4`), `flash` or `swop`. `flash` and `swop` act while
held; the others on the press.

**Swop.** While a `swop` button is held, only that playback's intensity shows: every other
playback's intensity is suppressed (except those with `protectFromSwop`), and colours and
positions stay where they are. Releasing it brings everything back as it was.

**Crossfade faders.** A `crossfade` fader runs the playback's next cue by hand: moving it
from one end to the other runs the transition in step with the fader (every timing of the
cue scaled to the travel), and the other end becomes its rest, so the next cue runs on the
way back. Progress never goes back: stopping holds the mix, and moving back does nothing
until the fader passes its furthest point. GO and BACK still run cues in real time.

**Fade-time master.** While a fade-time master is up, cue transitions and releases take
`10 s × level²` (2.5 s at half, 10 s at full) instead of their own times; at 0 the cues'
times apply. Chase steps, an explicit `release N <seconds>` and the programmer's fade keep
their own times.

**Blackout.** A blackout binding latches: one press turns blackout on, the next turns it
off. `blackout momentary` (`"momentary": true` in the show) makes it act while held.

**Tap tempo.** Every tap moves the beat grid onto the tap, and from the second tap on the
tempo follows the taps, so a BPM chase steps on them. A tap moves no running effect at
once: it closes the gap to the new grid over one beat.

## Rate limits

A phone may send at most 120 commands per second (bursts of 240, twice what the page
sends), an OSC surface 200 messages per second (bursts of 400). The excess is dropped and
counted: the phone gets one `error` per second (`rate limit: 37 commands dropped`), and
OSC drops print once per second on stderr (`OSC s-touch: rate limit: 37 messages
dropped`). Releases are never dropped (a button let go, and on OSC any message whose
values are all 0), so a flood never leaves a flash stuck. MIDI is not limited: it is local
hardware.
