# Plots

A **plot** is an MVR file (My Virtual Rig, DIN SPEC 15801): the rig as a lighting designer
draws it in Vectorworks, grandMA3, Capture, Depence and other CAD. busk builds the rig from
it: the profiles, the universes, the fixtures with their numbers, names, patch and positions,
and a group for each hanging position. It never touches programming.

- [Importing a plot](#importing-a-plot)
- [Where the stage is](#where-the-stage-is)
- [What each fixture becomes](#what-each-fixture-becomes)
- [Groups](#groups)
- [What busk leaves out](#what-busk-leaves-out)
- [What the show keeps](#what-the-show-keeps)

## Importing a plot

`rig check` says what an import would do and changes nothing. `rig import` does it, as one
undo step:

```
$ busk new club.show --title "Club"
$ busk run club.show
busk> rig check "plots/club.mvr"
the plot has 48 fixtures, 6 profiles and 3 universes
  add 47: 101–112, 201–212, 301–315, 401–408
  profiles to add: "Robe Robin Pointe", "Martin MAC Aura XB", …
  universes to add: 1, 2, 3
  groups to add: "LX1", "LX2", "FOH", "Floor"
  note: 310 has a second DMX break, not patched
  note: no GDTF in the plot: "Hazer" not added
fixtures span x -7.5…7.5 m, y -9.0…1.5 m, z 0.0…8.0 m
busk> rig import "plots/club.mvr"
note: 310 has a second DMX break, not patched
note: no GDTF in the plot: "Hazer" not added
imported 47 fixtures, 6 profiles, 3 universes and 4 groups from club.mvr
fixtures span x -7.5…7.5 m, y -9.0…1.5 m, z 0.0…8.0 m
```

From then on it is an ordinary show: add routes, record presets and cues. `undo` takes the
whole import back. The path is read from where busk runs, as `profile import` reads its own.

For now a plot builds a rig once: a show that already has fixtures from a plot refuses
another `rig check` or `rig import`. `undo` the import, or delete those fixtures (`delete
fixture N thru M cascade`), to start again.

## Where the stage is

busk measures the stage in metres from the middle of its downstage edge, at deck height: x to
stage right, y downstage (towards the audience), z up. A plot is in millimetres, and each
CAD file picks its own origin and its own side for the audience. Two words on the line place
the plot:

- `origin <x> <y> <z>`: where busk's origin is in the plot, in the plot's millimetres. The
  default is `0 0 0`.
- `audience -y|+y|-x|+x`: the side of the plot the audience is on. The default is `-y`, the
  bottom of the page, the way most plots are drawn.

```
busk> rig check "plots/club.mvr" audience +x origin 12000 -3500 0
```

The last line of every reply is the fixtures' span in busk's metres, and shows a wrong frame
at once. A plot whose origin is a corner of the venue puts everything twenty metres off; one
drawn with the audience at the top has its front truss upstage, at negative y. Try other
words with `rig check` until the span looks like the stage.

The show keeps the frame. A later `rig check` or `rig import` starts from it, and a word on
the line replaces it.

## What each fixture becomes

| busk | From the plot |
|---|---|
| Profile | The fixture's GDTF file in the plot, imported as `profile import` would. A profile the show already has (the same GDTF fixture type) is used as the show has it. |
| Mode | The fixture's GDTF mode, found by name as `fixture add` finds a mode. |
| Number | The fixture's numeric fixture id, else its fixture id when that is a number. A fixture with neither, or with a number the show or an earlier fixture of the plot has, gets the next number above the highest, and a note says so. |
| Name | The fixture's name, else `<model> <number>`, as `fixture add` names one. |
| Patch | The address of its first DMX break, written `45` (513 is universe 2, address 1) or `2.17`. A universe the show lacks is added as `Universe N`; no route is added or changed. With no address it is added unpatched. |
| Location | Where the plot hangs it and how it is turned, through the frame. A fixture the plot hangs with no turn comes in hung, beam down, its front to the audience: `rx` 180, and `rz` 180 with the audience at `-y`. |
| Invert pan and tilt | Set when the plot says; swap and offsets stay neutral. |

The web stage view and F1's stage page draw each fixture where the plot hangs it.

## Groups

Each hanging position of the plot (LX1, FOH, a boom) that holds fixtures busk adds becomes a
group named after it, numbered after the show's highest group. Its fixtures are in order from
left to right as the audience sees them, stage right first, so fans and effects run across
the stage.

## What busk leaves out

Each of these is a note, in `rig check` and in `rig import`'s reply:

- A fixture with no GDTF in the plot, or whose GDTF is missing, cannot be imported, or
  imports under the name of another profile of the show: it is not added.
- A fixture with no GDTF mode, or a mode its GDTF does not have: not added.
- A multipatch copy of another fixture: not added. busk patches one address per fixture.
- A second DMX break: not patched. busk patches the first.
- A patch that would end past channel 512: the fixture is added unpatched.
- A profile the show has at another revision: the show's is used, not the plot's.

The GDTF import also notes, for each profile it adds, what it cannot map: a channel busk has
no attribute for, held at its default, and the like. These run long, so `rig check` counts
them for each profile (`"Martin Professional MAC Aura XB": 10 notes from its GDTF`) and `rig
import` lists them, as `profile import` does.

Focus points, gels, gobos and mappings are not read. Trusses, set pieces and screens are read
but not drawn yet.

A plot is checked before it is read: an archive of more than 50,000 files, or one that
unpacks to more than 4 GB, is refused, and so is a scene larger than 64 MB. A GDTF file over
256 MB is not imported.

## What the show keeps

The show keeps where the plot was (relative to the show file's folder when the show has a
file), a hash of it and the frame, and each fixture keeps the uuid of the plot fixture it
came from. A show built from a plot runs anywhere: its profiles are in it, as always.
