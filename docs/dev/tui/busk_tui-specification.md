# busk — Terminal UI Specification

DMX lighting busking console · TUI front-end for the `busk>` command engine

Version 1.0 · 13 Oct 2026 · Reference prototype: [Busk TUI.dc.html](Busk%20TUI.html)

## 1. Scope

This document specifies the layout, visual system, input model and screen-by-screen behaviour of the busk terminal UI. It is written for implementation in any TUI framework (ratatui, Textual, Bubble Tea, notcurses, etc.). Every screen and control maps onto commands the engine already exposes; the TUI adds no engine functionality of its own.

Target operator: a busking lighting designer at a club gig — a dark room, fast reactions, one hand on a MIDI surface, the other on a laptop keyboard.

## 2. Design principles

1. **The command line is the source of truth.** Every mouse or key action in a pane is translated to exactly one engine command, executed through the same parser as typed input, and echoed to the log with a `ui>` prefix. The UI teaches the CLI.
2. **Hybrid modal panes + always-on prompt.** Ten screens (F1–F10) share one persistent prompt. Switching screens never clears the prompt or the log.
3. **Glanceable in the dark.** Charcoal background, no large bright fills. Colour carries meaning (cyan = UI focus, magenta = programmer, green = go/active, amber = tempo/warnings, red = destructive/blackout).
4. **Live, never stale.** Output swatches, faders, chases and effect waveforms redraw at ≥ 10 fps.
5. **Fluid.** Panels reflow to the terminal size; nothing assumes a fixed column count.

## 3. Terminal requirements

| Item | Requirement |
|---|---|
| Size | Fluid. Recommended minimum 100 × 30 cells; designed at ≈ 150 × 48. Below 100 columns, side-by-side panels stack vertically. |
| Colour | xterm-256 primary. 16-colour ANSI fallback (output swatches quantised to nearest ANSI colour). Truecolor optional for output swatches only. |
| Glyphs | UTF-8 with box drawing (`┌─┐│└┘`), block elements (`█ ▓ ░ ▁▂▃▄▅▆▇ ▀ ▄`), geometric (`● ◆ ■ ▲ ▶ ▸ ◂`), arrows (`↑↗→↘↓↙←↖`). |
| Font | The user's terminal monospace font. No assumption about ligatures or bold weight. |
| Mouse | SGR mouse reporting (1006) for click, drag, wheel. All functions must remain reachable without a mouse. |
| Keys | F1–F10, arrows, Tab, Esc, Space, Enter. Over SSH, F-keys may be unavailable — `Alt+1…0` is the required alternative. |

## 4. Visual system

### 4.1 Palette

All chrome colours are fixed xterm-256 indices. Do not use the terminal's theme colours 0–15 for chrome; they vary per user.

| Token | xterm | Hex | Use |
|---|---|---|---|
| bg | 234 | #1c1c1c | Screen background; panel title backing |
| bar | 235 | #262626 | Status bar, prompt line, table header rows, selected row |
| hover / sel | 236 | #303030 | Hover, selected fixture, unlit fixture swatch |
| track | 237 | #3a3a3a | Empty part of bars (`░`), inactive dots, free DMX channels |
| border | 239 | #4e4e4e | Panel borders, separators, disabled text |
| dim | 243 | #767676 | Labels, column headers, secondary values |
| mid | 248 | #a8a8a8 | Normal secondary text, inactive tabs |
| fg | 253 | #dadada | Primary text, values |
| cyan | 81 | #5fd7ff | Panel titles, active tab, selection, key names, spot fixtures |
| magenta | 206 | #ff5fd7 | Programmer values, BLIND, record actions, wash fixtures, downbeat |
| green | 113 | #87d75f | Prompt, GO, running effects, network TX, size masters, pixel bars |
| amber | 221 | #ffd75f | BPM, beat, TAP, FLASH, group masters, MIDI targets, pars |
| red | 203 | #ff5f5f | Errors, BLACKOUT, unpatched fixtures, DMX overlaps |

### 4.2 Live output colour

Fixture swatches show the fixture's computed output (colour × intensity), quantised for the terminal:

- Displayed brightness `d = 0.18 + 0.82 × dim` so low levels stay visible; `dim < 1.5%` renders as the unlit colour (236).
- **256 mode:** nearest of the 6×6×6 cube (levels 0, 95, 135, 175, 215, 255) or the 24-step grey ramp, whichever is closer.
- **16 mode:** nearest of the 16 ANSI colours by Euclidean RGB distance.

### 4.3 Components

| Component | Rendering | Behaviour |
|---|---|---|
| Panel | Single-line border (239). Title inset 1 cell from the left on the top border, padded with one space each side, cyan, UPPERCASE. Optional meta after `·` in the title. 1 cell inner horizontal padding. | Static container. |
| Button | `[LABEL]` text. Colour by intent: green GO, mid neutral, magenta record, amber tempo, red blackout. | Hover = bg 236. Click runs the shown command. |
| Tab | `F2 Program`; key in cyan, label mid. Active tab is reverse video: cyan bg, bg-coloured text. | Click or F-key. |
| Horizontal bar | Fill `█` in value colour, remainder `░` in 237. Width fills the available column; fill quantised to whole cells (optional ⅛ cells via `▏▎▍▌▋▊▉`). | Click/drag sets value from x position. Wheel ±5%. |
| Vertical fader | 10 rows × 4 cells. Full rows `████`, top partial row `▁▂▃▄▅▆▇` ×4, empty rows `░░░░` (237). Fill colour = current cue colour. | Click/drag sets level from y. Wheel ±5%. |
| Fixture swatch | Single-cell fixtures: `███` (grid) or a type glyph (stage plot: `■` par, `◆` spot, `●` wash, `▲` strobe). Multi-element fixtures: one `█` per element. Fixture number beneath. | Click = `sel fixture N`; Shift-click toggles in/out. |
| Table | Header row bg 235, cyan text. Rows 1 line, no row borders. Current/selected row bg 235 plus a `▸` or `▶` marker column. | Row hover 236; click per screen. |
| Status chip | Text in a 1-cell-padded block. Off: 239 text, no bg. On: coloured bg, bg-coloured text (BLIND magenta, BLACKOUT red). | Indicator only. |
| Big digits | 3-row block font built from `█ ▀`, 3 cells per glyph, 1 cell gap. Used for BPM and GM. | Display only. |
| Beat dots | Four `●`. The current beat is amber (beat 1 magenta); the others are 237. | Follows the speed master. |
| Sparkline | 20 cells of `▁…█` sampled across one effect cycle, scrolling with phase. Green running, 239 stopped; Rainbow uses per-cell hue. | Display only. |

## 5. Screen frame

Every screen shares the same vertical frame. Only the main area changes between F-keys.

| Row(s) | Region | Content |
|---|---|---|
| 1 | Status bar (bg 235) | `busk` badge (cyan reverse, bold) · show name · network TX per route (`● sACN·U1 ● ArtNet·U2`) · `GM 100%` (amber when \< 100) · `BPM 128.0 ●` (dot flashes on beat) · `FADE 0.0s` · `PROG n` (magenta) · BLIND chip · BLACKOUT chip · clock (right-aligned, HH:MM:SS). |
| 1–2 | Tab bar | F1 Busk · F2 Program · F3 Fixtures · F4 Cues · F5 Effects · F6 Presets · F7 Masters · F8 Patch · F9 MIDI · F10 Help. Wraps on narrow terminals. Bottom border 239. |
| flex | Main area | Active screen. Scrolls vertically if content exceeds height. |
| 7 | Log | Top border with `LOG` title (dim). Six visible lines, scrollable, auto-scrolls to newest. See 7.3. |
| 1 | Prompt (bg 235) | `busk>` (green, bold) + input + right-aligned context: `sel 8 · P1 · undo 3`. |
| 1 | Syntax hint | Help lines matching the first typed word (dim). See 7.2. |
| 1 | Key legend | Keys in cyan, actions dim: F1–F9 screens · F10 ? help · space GO · ← → playback · \[ \] fader · ↑ ↓ history · tab complete · esc clear. |

## 6. Global input model

### 6.1 Focus

The prompt always has text focus. Printable keys go to the prompt from any screen. The keys below act globally only **when the prompt is empty**, so they never interfere with typing.

| Key | Condition | Action |
|---|---|---|
| F1–F9 / Alt+1–9 | always | Switch screen; closes help. |
| F10 / Alt+0 | always | Toggle help overlay. |
| Esc | always | Close help if open, else clear the prompt. |
| ? | prompt empty | Toggle help overlay. |
| Space | prompt empty | `go N` on the selected playback. |
| ← / → | prompt empty | Select previous/next playback (wraps within the visible page). |
| \[ / \] | prompt empty | `fader N` −5% / +5% on the selected playback. |
| Enter | prompt | Execute; push to history. |
| ↑ / ↓ | prompt | Walk command history. |
| Tab | prompt, first word | Complete the command word; when ambiguous, print the candidates to the log as an info line. |

### 6.2 Mouse

- **Click** on buttons, tabs, tiles, rows, fixtures → runs the mapped command.
- **Shift-click** on fixtures or group buttons → additive selection (`sel +` / `sel -`).
- **Drag** on faders, bars and encoders → continuous update to the engine. One undo snapshot is taken at drag start. The equivalent command (e.g. `fader 2 72%`) is logged once, on release.
- **Wheel** over faders and encoders → ±5% per notch (±5° for pan/tilt). Not logged.
- **Flash** buttons are momentary: level 100% while held, restored on release or when the pointer leaves the button.

### 6.3 Undo

Every mutating command snapshots state before running; `undo` / `redo` walk the stack (the prototype keeps 100 levels). A command that errors rolls back to its snapshot and pushes nothing. Read-only commands (`list status info help library programmer save source quit`) are not recorded.

## 7. Command line

![Prompt with syntax hint](images/cmdline-hint.png)

*Fig. 1 — Prompt with `set dim spread` typed; the hint row shows the matching syntax from `help`.*

### 7.1 Parsing

Input goes verbatim to the engine parser. Tokens are whitespace-separated; double-quoted strings are a single token. The TUI does no parsing of its own except for hints and completion.

### 7.2 Syntax hint

The top-level lines of `help` (those with 4-space indent) are indexed. While typing, the hint row shows up to two lines that start with the first typed word, separated by four spaces. If there is no match but the word is a prefix of known commands, those commands are listed. Otherwise the row shows `unknown command`. With an empty prompt it reads: *type a command · help for syntax · clicks in the UI echo the command they run*.

### 7.3 Log line types

| Type | Prefix | Colours | Example |
|---|---|---|---|
| typed command | `busk> ` | prefix green, text fg | `busk> sel group 2` |
| UI-originated command | ` ui> ` | prefix 239, text dim | ` ui> preset color 3` |
| result | 6 spaces | mid | `preset color 3 "Red" → 4 fixtures` |
| error | ` ✗ ` | red | `✗ nothing selected — sel first` |
| info | ` · ` | dim | startup banner, tab-completion candidates |

## 8. Screens

### 8.1 F1 · Busk

The performance screen. A header row shows `page 1 · playbacks 1–N · sel …` on the left and the layout switch (`A console` / `B stack` / `C stage`) on the right. The number of playbacks shown is configurable (4–20; default 10). All three layouts show the same data and use the same command mapping. Pick one as the default and expose the others as a setting.

**Playback data (all layouts):** number `Pn`; name (ellipsised); cue position `cur/total`, or `chase n` for chases; current cue name; next cue name (sequences) or rate and direction (chases); level 0–100; colour = current cue colour, quantised. Empty slots show `·` and `—` in 239.

| Control | Command |
|---|---|
| Fader drag / wheel / \[ \] | `fader N <level>` |
| GO / Space | `go N` (sets level to 100% if it was 0) |
| ◂ (back) | `back N` |
| FLASH (hold) | momentary full output; no command logged |
| `Pn` label click | select the playback for Space / \[ \] (UI state only) |
| Fixture swatch | `sel fixture N` · Shift: `sel + / - fixture N` |
| Colour chip | `preset color N` |
| Group button | `sel group N` · Shift: `sel + group N` |
| Master bar drag | `gm <level>` / `master "<name>" <level>` |
| \[TAP\] | `tap` |
| \[B.O.\] / \[BLACKOUT\] | `blackout on\|off` (toggle) |

The selected playback is drawn with a cyan border (layout A) or a bg-235 row (B, C), with its `Pn` label in cyan.

#### Layout A — Console

![Busk layout A](images/f1-busk-a.png)

*Fig. 2 — Busk A. OUTPUT grid (top left), PROGRAMMER summary (top right), vertical PLAYBACKS (bottom).*

- **OUTPUT** (flex 3, min ≈ 65 cols): one row per fixture type (PARS, SPOTS, WASHES, BARS, STROBES). Label 9 cells, then swatches wrapping with 1-cell gaps. Selected fixtures get bg 236 and a cyan number.
- **PROGRAMMER** (flex 1, min ≈ 38 cols): `sel …(n)`; programmer summary (`8 fixtures · dim pan`, or `programmer empty`); colour chips (12 colour presets, 2 cells each); master bars (GM fg, size masters green, group masters amber; 8-cell label, bar, 3-digit value); tempo row (name, BPM, beat dots, \[TAP\], \[B.O.\]) pinned to the bottom.
- **PLAYBACKS**: grid of columns, each at least 9 cells wide, filling the width and wrapping. Each column, top to bottom: `Pn`, name, cue position, 10-row fader, level, `GO ◂`, `FLASH`.

#### Layout B — Stack

![Busk layout B](images/f1-busk-b.png)

*Fig. 3 — Busk B. One row per playback; tempo, masters, effects and selection in the right column.*

- **PLAYBACKS** (flex 3): column header row (dim), then one row per playback. Columns: `Pn` 4 · name 8–16 · level bar (flex, min 12) · level 4 · cue/next (≤ 26) · `[GO] [◂] [FL]`.
- Right column (flex 1, min ≈ 40 cols): **TEMPO** (big BPM digits, beat dots, \[TAP\] \[−\] \[+\]); **MASTERS** (bars + \[BLACKOUT\]); **EFFECTS** (id, template, sparkline, RUN/off toggle); **SELECTION** (sel text, group buttons, colour chips).

#### Layout C — Stage

![Busk layout C](images/f1-busk-c.png)

*Fig. 4 — Busk C. Fixtures drawn on their trusses; compact playback rows on the right.*

- **STAGE** (flex 3): one row per truss position (TRUSS 3 spots, TRUSS 2 washes, TRUSS 1 pars, DECK strobes and bars). A 9-cell label column (name, then sub-label in 239), then a dashed truss line (`┄`, 239) with fixtures spaced evenly along it. Each fixture has its glyph on bg 234 (so it interrupts the line), its number, and for movers a pan arrow plus tilt in degrees (`↗ 30°`). The row order must follow the real rig (upstage at the top). A centred `AUDIENCE` marker sits at the bottom.
- Right column: compact **PLAYBACKS** rows (`Pn` · name · bar · level · GO), **MASTERS** with tempo row, **QUICK** (group buttons + colour chips).
- Fixture positions come from the show file. Proposed property: `fixture N plot.row` / `plot.x` via the generic `<entity> <prop> <value>` command.

### 8.2 F2 · Program

![Program screen](images/f2-program.png)

*Fig. 5 — Program. Selection, attribute encoders by family, quick commands, programmer contents.*

- **SELECTION**: compressed selection text (`1 thru 8, 17.3`) in cyan with count; buttons `[N Name]` for every group, plus `[none]`.
- **Encoder families** (grid, min 42 cols per panel): INTENSITY (dim) · COLOR (red, green, blue, white) · POSITION (pan ±270°, tilt ±135°) · BEAM (zoom, strobe). Each row: name 7 · `[−]` · bar · `[+]` · value 6 (right-aligned). Bar colours: dim fg, red 203, green 113, blue 69 (#5f87ff), white fg, position cyan, beam amber.
- Encoders show the **first selected fixture**. The value is magenta when the attribute is in the programmer and dim when it reflects live output.
- `[−]/[+]` → `set <attr> <value>` ±5% (±15°). Drag → continuous set, logged on release. Wheel → ±2% (±5°), not logged.
- **quick** row: ready-made commands run on click — `set dim spread 0 to 1`, `… center`, `set pan spread -90 to 90`, `set tilt 45`, `set dim breakup`, `record cue 1`, `clear`, `blind on|off`. This list should be user-configurable.
- **PROGRAMMER CONTENTS** (magenta title): a row per fixture in the programmer: # · name · dim · colour swatch · rgb (2 dp) · pan · tilt · zoom. Unset values are `·`. Empty state: *programmer empty · select fixtures, then set attributes or apply presets*.

### 8.3 F3 · Fixtures

![Fixtures screen](images/f3-fixtures.png)

*Fig. 6 — Fixture sheet with live values and source colouring.*

A table of all fixtures (minimum 96 columns; scrolls horizontally below that). Columns: marker `▸` · # · name · profile (`×8` for multi-element) · mode · patch `U.A` (red `—` if unpatched) · dim · colour swatch · pan · tilt (movers only) · zoom (spots/washes) · src.

**Source colouring** applies to dim, pan, tilt and src: magenta = programmer, fg = playback, green = effect, dim = nothing driving it. A legend sits below the table. Row click → `sel fixture N`; Shift-click → `sel +/-`.

### 8.4 F4 · Cues

![Cues screen](images/f4-cues.png)

*Fig. 7 — Cuelist browser (left) and cue table for the selected list (right).*

- **CUELISTS** (flex 1): every non-empty list: number · name · kind (seq / chase / flash) · cue count. Click selects the list (UI state).
- **CUELIST n · Name** (flex 4): meta line (`mode` in amber: `sequence`, or `chase bpm "Main" x1 forward crossfade 0`; playback and level; groups). Cue table: `▶` on the current cue · L/C · name · in/out · delay · curve · follow · wait · dim · colour · fx id.
- Row click → `cue L/C go`. Buttons: `[GO]` `go N`, `[BACK]` `back N`, `[record cue L]` `record cue L`, and a sequence/chase toggle (`cuelist N chase bpm x1` or `cuelist N sequence`).
- Cell editing (time, curve, follow, wait) goes through the prompt: selecting a cell pre-fills the prompt with `cue L/C time ` etc. (not in the prototype yet).

### 8.5 F5 · Effects

![Effects screen](images/f5-effects.png)

*Fig. 8 — Effect table with live waveforms; templates on the right.*

- **EFFECTS**: id · template · fixtures (compressed, cyan) · rate (`bpm x1` / `0.25 hz`) · size · phase `a→b` · wings · direction · sparkline · state (`RUN` green / `off` dim) · `✕`.
- State click: an effect tied to a playback toggles that playback (`fader N 100%|0%`); a standalone effect toggles running. `✕` → `effect remove id`.
- **TEMPLATES**: name (green) and a one-line description. Click → `effect add "<template>" bpm x1 size 0.6` on the current selection. Templates added with `effect template add` appear here as "custom layers".

### 8.6 F6 · Presets

![Presets screen](images/f6-presets.png)

*Fig. 9 — Preset pools as tile grids.*

A header line shows what presets will apply to (the current selection). There is one panel per pool: COLOR, POSITION, BEAM, INTENSITY. Tiles are at least 15 cells wide with a 1-cell border (237; cyan on hover). Each tile shows the number (dim) and a preview on line 1 (colour swatch `████`, `pan/tilt`, `zoom NN`, or an intensity block glyph) and the name on line 2. Click → `preset <pool> N`. Recording uses the prompt (`record preset <pool> N "name"`); new presets appear immediately.

### 8.7 F7 · Masters

![Masters screen](images/f7-masters.png)

*Fig. 10 — Grand master, speed master with TAP, size and group masters.*

- **GRAND MASTER**: big digits (red while blackout is on), full-width bar (drag → `gm`), `[BLACKOUT on|off]` (red reverse when on), `[gm 100]`.
- **SPEED · name** (one panel per speed master): big BPM digits (1 dp), beat dots, a large `TAP` button (amber reverse) → `tap "<name>"`, `[−1] [+1]` → `bpm "<name>" n`, and the step list.
- **SIZE & GROUP MASTERS**: a bar per master (size green, group amber) with a sub-line describing its target. Drag → `master "<name>" <level>`.
- Tap tempo: average of the intervals between taps less than 2.5 s apart, minimum 2 taps; resets the beat phase to the tap.

### 8.8 F8 · Patch

![Patch screen](images/f8-patch.png)

*Fig. 11 — Universes, routes and a 512-channel map per universe.*

- **UNIVERSES**: U · name · fixture count · used channels `n/512`.
- **ROUTES**: U · protocol · address · destination (unicast host / multicast interface) · TX indicator (`●/○` blinking green while sending; red if the socket errors).
- **DMX MAP · U n**: 8 rows × 64 cells = 512 channels, with the start address on the left (dim, 5 cells). Each cell: `·` free (237), `█` fixture start address, `▓` rest of the footprint, coloured by fixture type (par amber, spot cyan, wash magenta, pixel bar green, strobe fg). `╳` red where two fixtures overlap. Legend below.
- Proposed interactions (not in the prototype): hovering a cell shows `fixture N · ch k/fp` in the hint row; clicking a fixture's cells selects it.

### 8.9 F9 · MIDI

![MIDI screen](images/f9-midi.png)

*Fig. 12 — Surfaces, incoming-message monitor and bindings.*

- **SURFACES**: status dot (green connected / red missing) · device name · kind · binding count.
- **MONITOR**: the last 14 incoming messages, newest at the bottom: `cc ch1 #48 102 → fader 1 APC mini mk2`. Consecutive CC messages for the same control replace the previous line instead of adding a new one.
- **BINDINGS**: surface · type · channel · number · target (amber) · current value (0–127 for faders and masters).
- Proposed: **learn mode** — `[learn]` on a binding row arms it and the next incoming message pre-fills `bind "<surface>" cc|note ch num <what>` in the prompt.

### 8.10 F10 · Help overlay

![Help overlay](images/f10-help.png)

*Fig. 13 — Help overlay over the current screen.*

A modal panel (cyan border, max 110 columns, max 88% height, scrollable) over a dimmed screen. Content: the engine's `help` output verbatim, then a key reference grid. Opened by F10, `?` or the `help` command; closed by Esc, F10 or clicking outside. The prompt stays usable while help is open.

## 9. Data the engine must expose

| Data | Fields | Rate |
|---|---|---|
| Fixture output | per fixture/element: intensity, RGB, pan, tilt, zoom, source (prog/pb/fx/none) | ≥ 10 Hz |
| Playbacks | id, name, kind, level, flash, current cue, cue list, groups, chase rate/direction | on change + 10 Hz for chases |
| Masters | gm, blackout, speed masters (bpm, beat phase), size and group masters | beat phase ≥ 20 Hz |
| Programmer | selection (ordered, with elements), per-fixture values, blind, fade | on change |
| Effects | id, template, fixtures, rate, size, phase, wings, direction, running, owning playback | on change |
| Show structure | groups, presets, cues, universes, routes, surfaces, bindings, profiles (library) | on change |
| Events | command results and errors, MIDI input, route TX status, undo depth | stream |

## 10. Open questions

1. Which Busk layout (A, B or C) is the default, and should the others ship?
2. Paging: should `page N` switch the visible playback bank, and should the page number take a status-bar slot?
3. Stage-plot positions: confirm the property names for truss row and x-position.
4. Cue cell editing: inline editing in the table, or prompt pre-fill only?
5. Should GO on a fader at 0% raise it to 100%? The prototype does; console conventions differ.
