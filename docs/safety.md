# Safety and panic

The safety stage holds whatever is played: values parked on fixtures, limits a truss or a
venue imposes, a cap on strobe rates, and panic commands for when something goes wrong.
It runs after the masters, on the output only, so releasing any of it returns exactly to
the live look. [The demo show](demo-show.md#safety) uses all of it.

## Park

```
busk> park fixture 204 intensity 0         # wash 4 stays dark
busk> park group 2 color 1 0 0             # the washes stay red
busk> list park
busk> unpark fixture 204 intensity
busk> unpark all
```

A parked value is forced on every slot it names, whatever any playback, effect, the
programmer, a master or highlight says. A parked intensity is not scaled by the masters,
but blackout still darkens it. `park` replaces what was parked on the slots it names, as
one undo step.

## Limits

```
busk> fixture 101 thru 102 limits tilt -90 10   # a low truss
busk> fixture 101 thru 102 limits pan -170 170
busk> fixture 301 limits intensity 50%
busk> fixture 101 limits none
```

Limits clamp every element of the fixture: pan and tilt in degrees as programmed (before
the fixture's orientation), intensity to a maximum. They clamp parked values too. Each
`limits` command sets one key and keeps the others.

## The strobe-rate cap

```
busk> safety strobe 3        # nothing flashes faster than 3 times a second
busk> safety strobe off
```

The cap is off unless the show sets it. It clamps strobe rates, and it slows effects that
move intensity to at most that many flashes per second: an effect in Hz is clamped, and an
effect on the beat halves its cycles per beat until it is under the cap, so it stays on the
beat grid (and re-rates without a jump when the tempo changes). A fixture whose slowest
strobe is above the cap gets a validation warning, since its strobe cannot go slower.
Chases and fast operator flashes are not capped.

## Highlight

```
busk> sel fixture 102
busk> highlight on           # MH 2 at full white, whatever the look and the grand master
busk> highlight off
```

Highlight is a programmer mode, like blind: every selected target lights at full (after
the masters, so a grand master at half does not halve it), with the shutter open and the
colour white; other channels take their profile's `highlightDmx`. It is never undone,
works while the programmer is blind, and is autosaved. Blackout, park and limits win over
it.

## Panic

```
busk> release all            # every playback, each over its own release time
busk> release all 2          # … over 2 s
busk> output off             # at the prompt it asks: Turn all DMX output off? [y/N]
busk> output on
```

- **`release all [<seconds>]`** releases every playback that is active, releasing or
  flashing, each over its own release time unless one is given, and drops held flashes and
  swops. The programmer is left alone (`clear` empties it).
- **`output off`** stops all DMX output: sACN streams send Stream_Terminated once, so
  receivers let go at once; Art-Net nodes and DMX-USB widgets keep their last frame, as
  they do by themselves. The status line shows `OUT off` until `output on`. At an
  interactive prompt `output off` asks first; scripts and bindings do not.

Both can be bound to a controller:

```
busk> bind "nanoKONTROL2" cc 1 60 release all
busk> bind "nanoKONTROL2" note 1 61 output off
```

Validation warns when `output off` is bound to something that may not be a button (a pitch
bend, or a CC without LED feedback): a fader would send it each time it is pushed up.

## When the engine stalls

If the engine stops producing frames, the output holds the last one, so the stage does not
go dark or jump while the watchdog restarts the engine. A show with
`holdLastFrameOnEngineStall: false` instead turns intensity off and holds everything else,
so heads do not swing home. See [the watchdog](running.md#processes-and-the-watchdog).

## The order

Each tick, after the masters: highlight, park on intensity, blackout, park on everything
else, limits, the strobe cap; then highlight's `highlightDmx` bytes after conversion.
