# Fixture profiles

A **profile** describes a fixture type: its modes, channels and what each DMX range does.
busk works in logical values (pan in degrees, colour as linear RGB, a gobo by name) and
the profile turns them into DMX. A show embeds a copy of every profile it uses, so a
`.show` file runs anywhere.

- [The built-in library](#the-built-in-library)
- [Profile libraries](#profile-libraries)
- [Importing OFL and GDTF files](#importing-ofl-and-gdtf-files)
- [Updating a show's profiles](#updating-a-shows-profiles)
- [How values become DMX](#how-values-become-dmx)
- [Notes on the built-in fixtures](#notes-on-the-built-in-fixtures)

## The built-in library

| Profile | Mode |
|---|---|
| Generic Spot 16ch | `16ch` |
| RGB Par 3ch (Generic) | `3ch` |
| Stairville MH-X25 LED Spot | `12-channel` |
| Eurolite LED ML-56 RGBW | `4-channel` |
| Chauvet DJ COLORband PiX | `36-CH` (12 cells) |

The last three were transcribed from their manufacturers' manuals and checked against
their DMX charts; [`examples/real-fixtures.json`](../examples/real-fixtures.json) is a show
with them. `library` at the console lists the profiles (and the effect templates) busk
can patch:

```
busk> fixture add 101 thru 102 "Generic Spot 16ch" mode 16ch at 1.1
busk> fixture add 201 thru 204 "Eurolite LED ML-56 RGBW" mode 4-channel at 1.33
```

## Profile libraries

`busk run --library DIR` (repeatable) adds a directory of profiles: busk profile files,
and also OFL `.json` and `.gdtf` files, which are imported when the library loads.

## Importing OFL and GDTF files

```bash
busk import ofl tests/fixtures/ofl/tupperdmx/*.json --manufacturer TupperDMX --out profiles
# tests/fixtures/ofl/tupperdmx/blinder.json: 'TupperDMX blinder' (modes 8ch) → profiles/ofl-tupperdmx-blinder.json; 3 notes (--report)
# …
# tests/fixtures/ofl/tupperdmx/moving-head.json: 'TupperDMX moving-head' (modes 12ch, 18ch) → profiles/ofl-tupperdmx-moving-head.json; 4 notes (--report)
busk import gdtf FILE…
```

`busk import ofl FILE… [--manufacturer M] [--out DIR] [--report]` and `busk import gdtf
FILE…` write one busk profile per file (`<id>.json` in `--out`, default the current
directory) and print what each became. `--report` prints the notes: channels that became
`control` channels held at a value (`Fog Type: no busk attribute (FogType); held at DMX
0`), estimated speeds, skipped modes. A file that fails names why, and the run exits 1.

**OFL** (the [Open Fixture Library](https://open-fixture-library.org/)'s JSON) maps each
capability type to a busk attribute.

- Profile ids are `ofl-<manufacturer>-<fixture>`. The manufacturer comes from the OFL
  repository layout (`<manufacturer>/<fixture>.json`) unless given with `--manufacturer`.
- The revision is the file's `lastModifyDate` plus a short hash of its content, so editing
  the file makes a new revision.
- `FogOutput` is intensity, so the masters and blackout apply to a smoke machine.
- Gobo rotation is `WheelSlotRotation`. `WheelRotation` (the whole wheel spinning) is
  never output.
- A mode whose colours are only whites or UV makes each its own intensity element.
- Speeds OFL gives only as `slow…fast` become estimates (strobe 1–20 Hz, rotation
  10–360 °/s), flagged in the report.

[`examples/tupperdmx/`](../examples/tupperdmx/) builds a show for a five-fixture rig from
hand-transcribed profiles (`build.busk`) or from the same fixtures imported from OFL
(`build-ofl.busk`); the two convert alike, except the smoke machine's dead band.

**GDTF** (DIN SPEC 15800) is a subset: single-cell fixtures, and multi-cell ones built
from geometry references, with their wheels, emitter colours (CIE xyY to linear RGB),
physical ranges and DMX defaults. `Fog1` and `Haze1` are intensity, as OFL's `FogOutput`
is. Mode masters, DMX breaks after the first and virtual channels are reported, not
imported. The XML is read with no `DOCTYPE` allowed, and the archive's `description.xml`
is capped at 32 MB. Only synthetic GDTF files have been tested so far.

## Updating a show's profiles

`list profiles` at the console says which embedded profiles the library has in another
revision. `profile update "<name>"` replaces the show's copy of a profile with the
library's other revision and moves its fixtures to it, as one undo step. It is refused
when a fixture's mode is missing from the new revision. Nothing is ever updated silently.

## How values become DMX

- **Capabilities are authoritative**, pan and tilt included: `physical.panRange` is
  informational. A value maps through the first range segment that contains it, else the
  nearest one (first on ties), clamped: `t = (v − v0)/(v1 − v0)`, `raw = rint(d0 + t·(d1 − d0))`.
  A zero-span segment outputs the centre of its DMX range. `invert` swaps `v0` and `v1`.
- **Orientation**: the pan channel reads the tilt value when `swapPanTilt` is set, then
  `deg = (input + panOffset)`, negated if `invertPan` — the channel's own settings.
- **Dimmer curves** (`linear`, `square`, `invSquare` = 1 − (1 − x)², `sCurve` = x²(3 − 2x),
  or a table) apply to dimmer channels and to virtual intensity alike.
- **Colour**: with a white emitter and no explicit `w`, `w = min(r, g, b)` is subtracted
  from r, g, b; an explicit `w` is used as given. Explicit `a`/`uv` are used, otherwise 0.
  CMY is `1 − r`, `1 − g`, `1 − b`. Other emitters (lime, cyan, custom) output 0 until
  calibrated mixing exists. Virtual intensity scales every additive emitter.
- **Options** (wheel slots, shutter functions) output the centre of their DMX range.
- **The shutter guard**: an uncontrolled shutter outputs `open`, never its `defaultDmx`,
  so a fixture with nothing up is not held dark by its shutter.
- **Rounding** is half to even.

[`internals.md`](internals.md) describes how the conversion runs.

## Notes on the built-in fixtures

Sources: the Thomann MH-X25 manual, the Eurolite ML-56 RGBW manual v1.0 and the Chauvet
DJ COLORband PiX manual Rev. 6, cross-checked against the Open Fixture Library
(`stairville/mh-x25`, `eurolite/led-ml-56-rgbw`, `chauvet-dj/colorband-pix`). Where they
disagree the manual wins unless it contradicts itself; each profile's `notes` records it:

- MH-X25 colour wheel: the manual gives white as 0–7, overlapping yellow at 5–9 (a typo);
  0–4 is used, as in OFL. Gobo wheel 128–255 is described as a "rainbow effect", copied
  from the colour wheel; it is gobo wheel spin. Sound-control programmes follow the
  manual's 16-value ranges (OFL has 15).
- Estimates, not measurements: MH-X25 strobe 0–13 Hz across 8–215 (the manual's spec-sheet
  shutter frequency, mapped linearly) and gobo rotation 10–360 °/s (the chart only says
  "increasing speed"). Gobo rotation DMX 0 is index 0°, used as "stopped".
