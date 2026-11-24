# Plots

A **plot** is an MVR file (My Virtual Rig, DIN SPEC 15801): the rig as a lighting designer
draws it in Vectorworks, grandMA3, Capture, Depence and other CAD. busk builds the rig from
it: the profiles, the universes, the fixtures with their numbers, names, patch and positions,
and a group for each hanging position. When the designer sends the plot again, the same line
brings the rig up to date. It adds no programming and keeps yours: only a fixture the plot
removes leaves the presets and cues that use it.

- [Importing a plot](#importing-a-plot)
- [Where the stage is](#where-the-stage-is)
- [What each fixture becomes](#what-each-fixture-becomes)
- [Groups](#groups)
- [When the plot changes](#when-the-plot-changes)
- [In the TUI](#in-the-tui)
- [In the stage view](#in-the-stage-view)
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
When the plot changes, import it again ([below](#when-the-plot-changes)).

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

Only the first import makes groups. From then on they are yours: a later import makes none
and changes none, and says where its new fixtures hang, so you can add them by hand.

## When the plot changes

A week later the designer sends `club-v2.mvr`. Check it, then import it:

```
busk> rig check "plots/club-v2.mvr"
the plot has 52 fixtures, 6 profiles and 3 universes; the show has 47 of them
  add 4: 601–604
  move 12: 201–212
  repatch 8: 301–308
  change 1: 205 mode 8ch → 16ch
  remove 2: 309, 310: used by 1 group, 3 presets and 1 cue, add cascade
  note: 601–604 hang on "LX3", a new position: no group made
fixtures span x -7.5…7.5 m, y -9.0…1.5 m, z 0.0…8.0 m
busk> rig import "plots/club-v2.mvr" cascade
note: 601–604 hang on "LX3", a new position: no group made
updated the rig from club-v2.mvr: added 4 fixtures; moved 12, repatched 8, changed 1, removed 2 (left 1 group, 3 presets and 1 cue)
fixtures span x -7.5…7.5 m, y -9.0…1.5 m, z 0.0…8.0 m
```

busk finds each fixture by the plot's own id for it, a uuid it keeps from the first import, so
a fixture keeps its number, and every preset and cue that uses it, whatever the plot changes.
Each line of the check is one kind of change:

| Line | What it does to the fixture |
|---|---|
| `add` | A fixture new to the plot is added, as the first import adds one. |
| `move` | Its location follows the plot. |
| `repatch` | Its patch follows the plot: a fixture the plot no longer patches is unpatched. |
| `change` | It takes the plot's mode, or another profile and mode. |
| `rename` | It takes the plot's name. A fixture the plot gives no name keeps yours. |
| `invert` | Its invert pan or tilt follows the plot, where the plot says. |
| `remove` | A fixture the plot no longer has is removed. |

The plot owns the patch, the profile and mode, the location, the name and the inverts. You
own the rest: the number, swap pan and tilt, the offsets, limits, park and groups. A fixture
the plot numbers otherwise keeps its number, and a note says so. A fixture you added by hand
is never touched, and a new fixture may take the number of one the plot removed.

Two things stop the line:

- **A removed fixture in use.** A fixture the plot removes goes with what uses it, as `delete
  fixture N cascade` takes it: out of groups, presets, cues, park and bindings. While anything
  uses it, `rig import` is refused until you add `cascade`. A fixture in a group the first
  import made is in use.
- **A mode that loses cells in use.** A new mode or profile with fewer cells than a group, a
  preset or a cue uses is refused, as `fixture N mode` is, even with `cascade`. `rig check`
  lists it first, as `blocked:`. Change what uses the lost cells first, then import again.

A word on the line (`audience`, `origin`) moves every fixture from the plot, and the show
keeps the new frame. A fixture of the show that busk cannot read in the new plot (its GDTF is
missing, say) is left as it is, and a note says so: it is not removed. When nothing changes,
`rig check` says `nothing to change` and `rig import` is refused; when only the file changed
(the set, say), `no fixture changes`, and the import keeps the new file's hash.

## In the TUI

F3's `[import plot…]`, or Import plot… in the File menu, does the same without typing a path.
The file picker opens on `.mvr` files, starting on the plot the rig came from, and the preview
of each is what `rig check` says of it. Enter on one opens IMPORT PLOT: busk's check, with the
frame on a first import (the audience's side, and the origin), `cascade` ticked when the import
removes fixtures in use, and `[import]`, which sends the `rig import` line. See [the TUI
guide](tui/guide.md#importing-a-plot).

## In the stage view

The web remote's stage view ([surfaces](surfaces.md#the-stage-view)) draws the plot's trusses,
supports, set pieces, screens and projectors where the plot puts them, through the same frame
as the fixtures, in place of busk's own deck, backcloth, trusses and PA: a plot brings its own.
Pools of light land on them. The audience's floor is the scenery's lowest point.

The crowd stands in front of the plot's stage, sized to it, wherever the plot's origin is: the
middle of the deck, a corner of the venue or busk's own. The stage is what of the scenery stands
on the floor (decks, risers, walls, towers, a PA stacked on the floor; not what is flown), the
largest block of it where several stand apart, and its downstage edge faces the crowd. A wrong
`audience` still shows here: the crowd faces the stage's side or its back.

busk reads the scenery from the plot's file each time a view opens, so keep the plot where
the show says it is (beside the show, as a rule). The show keeps only the plot's path, so it
stays one small file and runs anywhere; without the plot the view draws busk's deck and says
so:

```
the plot ../plots/club.mvr is not there: the stage is drawn without its scenery
```

When the plot's file has changed since the import, the view draws its scenery as it is now
and says `the plot ../plots/club.mvr has changed since the rig was imported`: `rig check` it
to see what else changed. F1's stage page draws no scenery.

## What busk leaves out

Each of these is a note, in `rig check` and in `rig import`'s reply:

- A fixture with no GDTF in the plot, or whose GDTF is missing, cannot be imported, or
  imports under the name of another profile of the show: it is not added.
- A fixture with no GDTF mode, or a mode its GDTF does not have: not added.
- A multipatch copy of another fixture: not added. busk patches one address per fixture.
- A second DMX break: not patched. busk patches the first.
- A patch that would end past channel 512: the fixture is added unpatched.
- A profile the show has at another revision: the show's is used, not the plot's.

Some CAD writes a placeholder GDTF for each fixture type: the right modes and channel counts,
but every channel a `Dimmer1`, `Dimmer2` and so on, which says nothing of what it does. Capture
does, in the plots it exports. busk cannot make a profile of one, and says so in a line
(`"Robe@Robin MegaPointe@r3038.gdtf" cannot be imported: no channel has a busk attribute
(Dimmer1, Dimmer2, Dimmer3 and 36 more)`); when every GDTF of the plot is one, `rig check`
says `no fixture busk can add`, and `rig import` refuses.

The GDTF import also notes, for each profile it adds, what it cannot map: a channel busk has
no attribute for, held at its default, and the like. These run long, so `rig check` counts
them for each profile (`"Martin Professional MAC Aura XB": 10 notes from its GDTF`) and `rig
import` lists them, as `profile import` does.

Focus points, gels, gobos and mappings are not read. The fixtures' own 3D models are not
drawn, and a model of the scenery in a format other than glTF and 3DS is not drawn either (the
view says how many).

A plot is checked before it is read: an archive of more than 50,000 files, or one that
unpacks to more than 4 GB, is refused, and so is a scene larger than 64 MB. A GDTF file over
256 MB is not imported, and a model over 256 MB is not drawn. The stage view loads only the
plot's models and the files they name: nothing else in it is served.

## What the show keeps

The show keeps where the plot was (relative to the show file's folder when the show has a
file), a hash of it and the frame, and each fixture keeps the uuid of the plot fixture it
came from, which is how a later import finds it. Saving the show into another folder keeps
the path relative to the new file, so the copy still finds the plot. A show built from a plot
runs anywhere: its profiles are in it, as always, and only the stage view's scenery needs the
plot.
