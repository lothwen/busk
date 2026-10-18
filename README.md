# busk — busking lighting console engine

> [!NOTE]
> This is a personal project, fully “vibe coded” as part of my learning process, and developed as
> improvement for [tupperdmx-simulator](https://github.com/lothwen/tupperDMX-simulator).
> The engine is provided for personal and experimental use.
> Feedback, bug reports, and help with testing are greatly appreciated! Have fun!

A real-time engine for improvising lighting live. The operator layers looks, colours,
positions and effects from a MIDI controller, a phone or the keyboard, and busk turns that
intent into DMX over sACN, Art-Net or a USB DMX interface. Shows are built and changed
from a command-line console while the output keeps running.

busk is a command (`busk`) and a Python library.

## Features

- **Busking playbacks.** Looks and bumps on faders and buttons, built from groups and
  presets. Intensity merges highest-takes-precedence, everything else latest-takes-precedence.
  Flash, swop, exclusivity, a grand master and blackout.
- **Cue lists.** Fades and curves per attribute family, GO / BACK / GOTO, `follow` and
  `wait` triggers, tracking, chases locked to a speed master's beat, tap tempo and MIDI
  clock.
- **Effects.** Waveforms and colour cycles spread across a group's members, on the beat
  or in Hz, layered absolutely or relatively over the looks below, scaled by `size`
  faders and size masters. Effects come from a built-in template library.
- **Live programming.** A console that patches, programs, records presets and cues, and
  edits the show while it plays, with blind mode and one undo timeline.
- **Control surfaces.** MIDI controllers with soft takeover, LED and motor-fader feedback
  and hot-plug; OSC in and out; a web remote a phone opens over Wi-Fi. Playback pages,
  crossfade faders and a fade-time master.
- **Output.** sACN (E1.31, with universe discovery), Art-Net (with ArtPoll discovery), and
  Enttec DMX USB Pro and DMXking widgets. Every route reconnects by itself.
- **Safety.** Park, per-fixture limits, a strobe-rate cap that also slows intensity
  effects, highlight, and panic commands (`release all`, `output off`).
- **Made for a show.** `busk run` runs as three processes. A watchdog restarts a crashed or
  stalled engine while the output holds the last frame, and the look comes back. A
  crashed console comes back against the running engine. Edits are autosaved and
  recovered after a crash, and remotes are rate-limited.
- **Fixture profiles.** A built-in library, plus imports from Open Fixture Library and
  GDTF files.
- **Event log and replay.** Every run logs what the engine applied and why. `busk replay`
  rebuilds the run, frame for frame.
- **A library.** Load, validate and save shows, render frames on a clock you drive, or run
  a show live inside your own program.

Its only dependencies are numpy and pydantic, plus mido and python-rtmidi for MIDI. OSC,
WebSocket, Art-Net and the Enttec protocol are written against their specifications.

## Install

busk needs Python 3.12 or later. It is tested on Linux. Other POSIX systems should work
but are untested, and Windows is not supported.

From a checkout, with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/lothwen/busk.git && cd busk
uv sync                 # busk, the `midi` extra and the development tools
uv run busk --version
```

Or into another project, from that checkout ([details](docs/library.md#installing)):

```bash
uv add path/to/busk --extra midi        # or: pip install "path/to/busk[midi]"
```

**MIDI** is the optional extra `busk[midi]` ([`mido`](https://mido.readthedocs.io/) with
`python-rtmidi`). python-rtmidi has wheels up to Python 3.12. On 3.13 and later it builds
from source, which needs a C++ compiler and the ALSA headers. Without the extra, busk runs
as usual, except that each MIDI surface reports `MIDI s-…: unavailable: install busk[midi]`
once and stays closed. On Linux, MIDI needs the ALSA sequencer (`/dev/snd/seq`), and
`aseqdump -l` lists the input ports busk can match.

## Quick start

[`examples/club-night.busk`](examples/club-night.busk) builds a complete show with console
commands only: two moving heads, four washes and an LED bar, looks and bumps, a song, a
chase, effects, a second page, a phone remote, controller LEDs and safety limits. It is
played from a Korg nanoKONTROL2 and a phone. Build it once, then busk:

```bash
busk new club.show --title "Club Night"
# created club.show
busk run club.show --script examples/club-night.busk --iface eth0
# added universe 'Stage'
# added fixture 101–102: Generic Spot 16ch, 16ch
# …                                          (one line per command of the script)
# saved club.show
# sACN r-…: U1 Stage → universe 1, multicast 239.255.0.1 via eth0, priority 100
# MIDI s-…: nanoKONTROL2:nanoKONTROL2 _ CTRL 20:0
# Web s-…: http://192.168.1.20:8080/?k=…     (open it on the phone)
# busk console: type 'help' for the commands, 'quit' to stop.
busk> fader 1 1                              # Warm up …
busk> fader 3 1                              # … and the Blue bump on top
busk> blind on                               # program without touching the stage
busk> sel group 1
busk> set color 0 0.3 1
busk> record preset color 1 merge            # the stage changes live: Blue's cue references the preset
# recorded preset color 1 'Blue': 1 value
busk> undo                                   # and back
# undid: recorded preset color 1 'Blue': 1 value
busk> quit
# engine: 2311 ticks @ 100 Hz, 0 overruns, max tick 1.4 ms, 2 commands, 0 command errors

busk run club.show --iface eth0              # from now on, the saved show
busk> fader 9 1                              # the song: the Intro eases in over 3 s
busk> go 9                                   # Verse: the heads swing out over 4 s; Pre fires 8 s later
busk> status
# GM 100% | BO off | P1 Main | Speed 1 120 BPM ×1 | 9 Song on 2 Verse 1.00
busk> fader 10 1                             # the chase bounces across the washes on the beat
busk> tap                                    # four taps at 128 BPM: the chase follows them
busk> quit
```

Set `--iface` to the interface that reaches your sACN node (`ip -br link`). From a
checkout, prefix the commands with `uv run`. [The demo show](docs/demo-show.md) maps every
control and takes a longer tour through the effects, pages, the phone and the safety
features.

## Commands

| Command | |
|---|---|
| `busk new PATH [--title T]` | Write a new, empty show. It never overwrites a file. |
| `busk validate SHOW` | Report every issue with a path (`error   fixtures[2].patch.address: …`). Exits 1 on errors. |
| `busk run SHOW [options]` | Run the engine, the output, the surfaces and the console. See [Running a show](docs/running.md). |
| `busk import ofl\|gdtf FILE… [--out DIR] [--report]` | Convert fixture files into busk profiles. See [Fixture profiles](docs/profiles.md#importing-ofl-and-gdtf-files). |
| `busk replay LOG… [--until T] [--frames OUT]` | Rebuild a run from its event log. See [the event log](docs/running.md#the-event-log-and-replay). |

Shows are `.show` files (a ZIP holding `show.json`) or plain `.json`. `python -m busk …`
works too.

The **console** speaks in the numbers an operator uses: `fixture 101`, `group 2`,
`preset color 1`, `cue 9/2`, `playback 3`. It patches, programs, records and plays:

```
busk> universe add 1 "Stage"
busk> fixture add 201 thru 204 "Eurolite LED ML-56 RGBW" mode 4-channel at 1.33
busk> sel fixture 201 thru 204
busk> record group 1 "Washes"
busk> set color 0 0 1
busk> record preset color 1 "Blue"
busk> clear
busk> sel group 1
busk> set intensity 80%
busk> set color preset color 1
busk> record slot 1 "Blue washes"             # a playback in slot 1 of the page
# recorded slot 1: playback 1 'Blue washes'
busk> surface add midi "nanoKONTROL2"
busk> bind "nanoKONTROL2" cc 1 0 fader 1      # the controller's first fader plays it
busk> fader 1 1                               # or the console does
```

[The console](docs/console.md) lists every command.

## Documentation

| Guide | |
|---|---|
| [The demo show](docs/demo-show.md) | The club-night show: its rig, pages and controller map, and a tour. |
| [FAQ](docs/faq.md) | Shows and scripts, the order to build a show in, no light, controllers, crashes and backups. |
| [Running a show](docs/running.md) | `busk run`: its options and output, autosave and recovery, the processes and the watchdog, the event log, values files. |
| [The console](docs/console.md) | Every console command, recording rules, scripts. |
| [Control surfaces](docs/surfaces.md) | MIDI, OSC, the web remote, feedback, pages, soft takeover, swop, crossfade faders, rate limits. |
| [Output](docs/output.md) | sACN, Art-Net and DMX-USB routes, choosing the network interface, reconnects. |
| [Safety and panic](docs/safety.md) | Park, limits, the strobe cap, highlight, `release all`, `output off`. |
| [Fixture profiles](docs/profiles.md) | The built-in library, OFL and GDTF import, how values become DMX. |
| [busk as a library](docs/library.md) | Installing, examples, the reference of the public API, stability. |
| [The spec](docs/busking-console-architecture-python.md) | The architecture busk implements, and the show file schema. |

For developers: [Developing busk](docs/development.md) (tests, benches, the source layout),
[How busk works](docs/internals.md), [Benchmarks](docs/benchmarks.md),
[How busk was built](docs/history.md) (design decisions and spec gaps) and the
[manual checklists](docs/checklists.md). [`CHANGELOG.md`](CHANGELOG.md) lists the releases.

## Using busk as a library

Everything public is importable from `busk`, and [`docs/library.md`](docs/library.md) is
the guide.

```python
import busk

show, warnings = busk.load_show("club.show")
offline = busk.OfflineShow(show)          # a clock you drive: no threads, no sockets
offline.execute("fader 1 1")
frame = offline.tick(3.0)                 # frame.universes[1]: universe 1's 512 bytes, 3 s later

with busk.LiveShow(show) as live:         # real time, in your process: engine and output threads
    live.execute("go 1")
```

`LiveShow` has none of `busk run`'s safety net: no watchdog, no process isolation, no
autosave or crash recovery. For a show on stage, use `busk run`.

## Known limitations

- **Colour wheels.** A fixture with only a colour wheel takes `colorWheel` values. An RGB
  colour, such as a global colour preset, does nothing on it yet.
- **Single-emitter elements** (UV-only, white-only) and pan/tilt fixtures without a dimmer
  cannot be described yet. The importers work around them.
- **One page for every surface.** Two operators cannot be on different pages.
- **The phone plays, it does not program.** Show edits and programmer commands come from
  the console only, and there is no blind preview.
- **Not supported:** HID surfaces, display feedback on MIDI surfaces, Ableton Link (MIDI
  clock works), OSC address patterns, TLS for the web remote, ArtSync and sACN
  synchronisation, and Open DMX USB (FTDI) interfaces.
- **Interface names** in routes are Linux-only. Elsewhere, give the interface's IPv4
  address.
- **After an engine restart**, fades in progress snap to their target. Hz effect phases,
  held flashes, swops and soft-takeover attachments are not restored.
- **Killing the `busk run` process itself** ends the output, and receivers time out. A
  console that hangs without exiting is not detected.
- **GDTF import** covers a subset, tested on synthetic files only.
- **The strobe cap** does not apply to chases or fast operator flashes.

[How busk was built](docs/history.md#spec-gaps) has the full list of open questions.

## Development

```bash
uv sync
uv run pytest                                          # the suite; no packet leaves the machine
uv run ruff check . && uv run ruff format --check .    # lint + format
uv run mypy                                            # --strict on src/
```

[Developing busk](docs/development.md) has the opt-in tests, the benches and the source
layout.

## License

MIT; see [`LICENSE`](LICENSE).
