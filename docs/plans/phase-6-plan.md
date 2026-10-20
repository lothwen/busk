# Phase 6 — Surfaces and network: implementation plan

> Source spec: `busking-console-architecture-python.md` (§22, Phase 6; §4.1, §5.12–§5.18, §7.4, §7.6, §8.1–§8.2, §11.3, §14, §15.1–§15.2, §16–§19, §23). Builds on the Phase 0–5 plans and on the code as it stands after Phase 5 (2056 tests). §2 names the real modules this plan changes, so no seam-mapping step is needed.

## Context

Phase 5 ends with a console that plays looks, song stacks, chases and effects from one MIDI controller and the line console. The controller only reaches the first page. Its faders jump to wherever the hardware is, and nothing lights up on it. Output goes out as sACN only, and remotes have no way in.

The spec scopes Phase 6 as *"Bindings, pages, soft takeover, feedback, OSC, web remote, ArtPoll discovery, sACN discovery/termination, DMX USB"*. It is done when an operator can *"run a show from a MIDI controller and a phone simultaneously"*. Earlier phases handed over (phase-5-plan §10, README "Next"):

- pages, with the engine owning the current page (phase-2-plan §9);
- soft takeover, LED and motor-fader feedback, a latching blackout;
- OSC, the web remote (snapshots over the §16 API), ArtPoll discovery, sACN discovery, DMX-USB output;
- `crossfade` faders and `goto` buttons (deferred from Phase 4);
- the blind preview resolve (deferred from Phases 4–5);
- decisions on the fade-time master, `swop`, and external tempo (MIDI clock, Ableton Link).

Five things make this phase harder than its one-line scope suggests:

1. **Several surfaces act on shared state at once.** A page change from the phone and a fader move from the controller race each other across threads. The result must not depend on which thread wins. So page-relative input has to be resolved where the state lives, in the engine, in queue order. Then the engine harness can test it deterministically.
2. **Controls have memory; bindings do not.** Soft takeover, a flash held across a page change, a latching blackout and a crossfade fader that rests at either end all need state per physical control. Phase 2's bindings are stateless by design (phase-2-plan decision 10).
3. **Four wire protocols, with no hardware in CI.** OSC, WebSocket, Art-Net and the Enttec USB protocol have to be written against their specifications. They are tested against golden bytes, localhost sockets and a pseudo-terminal, as Phase 1.5 did for sACN.
4. **More Python threads share the engine's GIL.** MIDI, OSC, web connections, feedback and discovery all run in the engine's process until Phase 7 splits it. They must stay idle enough that the demo rig keeps 0 overruns.
5. **Semantics left open for this phase.** `crossfade` faders, `goto` buttons, `swop` and the fade-time master were each deferred because they needed decisions. This plan makes those decisions (§3) so the user can veto them before any code exists.

**Done when:**

- Starting from the show that `examples/phase3-build.busk`, `phase4-song.busk` and `phase5-effects.busk` build, the script `examples/phase6-surfaces.busk` adds, with console commands only:
  - soft takeover and LED feedback on the nanoKONTROL2, and page buttons on its marker ◀ ▶;
  - a second page "Washes" with:
    - four exclusive wash looks whose M buttons `swop`;
    - a three-cue list on fader 8 played by hand with a `crossfade` fader;
    - the knob playbacks 9–13, so the knobs work on both pages;
  - a `goto` button on the song, a fade-time master "Fade", and a web remote "Phone".

  `busk run` on the result is played from the controller and from a phone's browser at the same time.
- `test_surfaces_show.py` reproduces this deterministically (§5.19). It checks that:
  - the saved show matches a golden JSON file;
  - the logical values at each checkpoint match values computed by hand, and the DMX matches golden bytes;
  - the controller's LEDs and the phone's state messages match the expected values;
  - a soft fader never jumps, and a phone move detaches it;
  - a page change leaves running playbacks alone;
  - swop and blackout give back the exact frame;
  - frames are byte-identical at 100 Hz, on an irregular tick schedule, and after save → load.

  A second test drives the phone part through a real WebSocket on localhost.
- Art-Net (with ArtPoll discovery), sACN universe discovery and DMX-USB output pass their protocol tests. Those tests use golden packets, localhost sockets and a pseudo-terminal.
- The §7.8 golden test and every Phase 2–5 test still pass. The only exceptions are tests that asserted:
  - that this phase's features were ignored;
  - the first-page binding behaviour;
  - a momentary blackout binding.

  §6 lists them step by step.
- With a phone and the controller sending continuously, the demo rig ticks at 100 Hz with 0 overruns, and the Phase 5 tick gates still pass. The numbers are recorded.
- All acceptance tests in this plan pass.

---

## 1. Scope

| In Phase 6 | Deferred (to) |
|---|---|
| Pages: the engine owns the current page (`PAGE`), page and pageAbs actions, page-relative faders and buttons resolved in the engine, the page autosaved | Pages per surface: one global page (decision 1) |
| `PLAYBACK_BUTTON`: every §8.1 button function applied by the engine; a held flash or swop is released on the playback it was pressed on | — |
| `goto` buttons (`Playback.gotoCue`), `swop` (§7.6), a latching blackout | Several goto cues per playback |
| Soft takeover for faders and masters (§5.15) | — |
| `crossfade` faders (§8.2, §5.18 `manualProgress`) | Reversing a manual crossfade (decision 11) |
| Fade-time masters (§5.13) | — |
| Feedback: LEDs, motor faders, OSC display labels; beat-flashing tap LEDs | Display feedback on MIDI surfaces (device sysex); feedback on `command` actions |
| MIDI output for feedback; MIDI clock as a tempo input | Ableton Link (needs a native library); MIDI hot-plug (Phase 7) |
| OSC input and feedback (UDP) | OSC address patterns (wildcards) |
| The web remote: HTTP + WebSocket API (snapshots, show summaries, performance commands), a phone page | Programmer and show edits over the API; the blind preview resolve; a template editor (all wait for a programming UI that §22 does not schedule) |
| Art-Net 4 output (ArtDmx), ArtPoll discovery with unicast to discovered nodes, ArtPollReply | ArtSync; sACN synchronisation |
| sACN universe discovery (termination exists since Phase 1.5) | — |
| DMX-USB output with the Enttec Pro protocol (`enttecPro`, `dmxking`), reconnect after unplugging | `enttecOpen` (needs host-timed breaks); sending fewer than 512 slots |
| Console grammar, status line, limitation report | HID and `internal` surfaces, `hw` inputs (unassigned in the roadmap) |
| | Process split, watchdog, general route reconnect, park, limits, strobe cap (Phase 7) |

---

## 2. Baseline from Phase 5

These are the modules this plan changes, as they are now.

| Area | Now | Phase 6 change |
|---|---|---|
| `model/surface.py`, `model/playback.py` | The §5.15 schema; `BlackoutAction` has no fields | `midiClock` input; `BlackoutAction.momentary`; `SurfaceMatch.feedbackPort`; `Playback.gotoCue` |
| `model/validate.py` | Bindings: surface, playback and master references only | Surface ports, input kinds per surface, feedback, `gotoCue`, page numbers (§5.18) |
| `commands/types.py`, `classes.py`, `bus.py` | `SET_FADER` by playback id; `BLACKOUT {on}`; `MASTER_ARRIVES_IN = {fadeTime}`; 32 command types | `PAGE`, `PLAYBACK_BUTTON`; `SET_FADER` by slot too; `BLACKOUT` toggles; `CommandOrigin.control`; fade-time masters accepted |
| `compiler/playbacks.py`, `compile.py` | `firstPage`; `CompiledPlayback` without `protectFromSwop`; masters default to level 1 | `pages`; `CompiledPlayback.gotoCue`, `protectFromSwop`; `CompiledShow.softControls`; fade-time masters default to 0 |
| `engine/loop.py` | `_apply(command, now)`; no page | `_apply(command, now, origin)`; `PageState`, `Pickup`, `HeldButtons`; fade-time levels |
| `engine/playback_runtime.py` | `crossfade` faders behave like `none`; no swop | Manual crossfades; swop suppression; fade-time override |
| `engine/effects.py` | `EffectBank.update(now, scalars)` | Presence evaluated at a separate fade time (manual crossfades) |
| `engine/snapshot.py` | Masters, blackout, speed (bpm, multiplier, level), playbacks | Page, beat anchors, `swop`, `progress`, the snapshot's time |
| `io/bindings.py` | Resolves slots on the first page and maps button functions to commands; faders jump; blackout momentary | Sends page-relative commands with the control's id; `select` resolved against the snapshot's page |
| `io/midi.py` | MIDI input only | MIDI clock → beats; `MidiOutput` for feedback |
| `cli.py` | `MidiPorts`, `Supervisor`, status line, `Ignored in Phase 5:` | `SurfaceManager` (MIDI, OSC, web), a feedback thread, page and fade time on the status line |
| `output/scheduler.py`, `sacn.py`, `driver.py` | sACN routes; Art-Net and DMX-USB "ignored (… arrives in Phase 6)" | Art-Net and DMX-USB drivers; `SendPolicy` parameters; Art-Net and sACN discovery serviced on the output thread |
| `persistence/autosave.py`, `paths.py` | Programmer, master levels, tempos | The current page; the web access key file |
| `console/` | `surface add midi`, `bind … cc\|note`, `route add sacn\|artnet`, `record slot` on the first page | §5.17 |
| `compiler/limitations.py` | Lists pages, non-MIDI surfaces, soft pickup, feedback, OSC/hw inputs, page actions, `crossfade`, `goto`, `swop`, fade-time masters, limits, park, stall | Shorter (§5.18) |
| Tests | `harness.Harness`, `session_harness.Live`, `sacn_receiver.py`, `test_perf.py` | Extended (§7); a WebSocket test client |

**Benchmark baseline** (phase-5-plan step 16):
- Appendix A busking tick, with the pulse running: 0.075 ms mean, 0.087 ms p99.
- Reference rig, 60 playbacks: 1.850 ms mean, 2.164 ms p99.
- 20 effects: 3.384 ms mean, 3.560 ms p99.
- 60 transitions: 3.079 ms mean, 3.675 ms p99.
- 60-GO burst: 16.5 ms mean.
- 8 chases: 3.791 ms mean on step ticks.
- Edit latency: demo rig 0 overruns, p95 7.0 ms; reference rig 130 overruns in 1558 ticks (the GIL, a Phase 7 input).

---

## 3. Decisions and assumptions

1. **The engine owns one current page**, shared by every surface (§15.2 lists `PAGE` as a performance command).
   - `PAGE {number}` goes to that page. `PAGE {delta}` moves through the pages in number order and stops at the first and last: a missed press never wraps to the far end.
   - Changing pages never touches running playbacks (§5.12).
   - At start the current page is the lowest-numbered one. A live edit keeps it by id. If that page was deleted, the next page by number becomes current, else the last.
   - The page is autosaved and restored after a crash (§17 "last page").
   - The phone shows the current page, and its page buttons change it for everyone. What the operator sees on the phone is what the controller's faders drive. Pages per surface stay open (§9).
2. **The engine resolves page-relative input** (phase-2-plan §9's recommendation).
   - `SET_FADER` and the new `PLAYBACK_BUTTON` name a playback either by `playbackId` or by `slot`, a 0-based index into the current page.
   - Bindings no longer look up pages or button functions. A page change and the fader move after it are applied in queue order, whichever surface sent them. An empty slot does nothing.
3. **`PLAYBACK_BUTTON {playbackId | slot, button, down}`**: the engine applies the function in the playback's `buttons[button]` (§8.1):

   | Function | `down` | `up` |
   |---|---|---|
   | `go`, `back`, `toggle`, `release` | `GO`, `BACK`, `TOGGLE_PLAYBACK`, `RELEASE_PLAYBACK` | — |
   | `goto` | `GOTO` its playback's `gotoCue`; nothing without one | — |
   | `flash` | `FLASH` down | `FLASH` up |
   | `swop` | swop on (decision 9) | swop off |
   | `select`, `none` | — (`select` is a programmer command: decision 4) | — |

   A flash or swop pressed through a slot is **held per control**. The release goes to the playback the press went to, even if the page changed in between, so a flash is never left stuck on.
4. **`select` buttons go to the session**, because they change the programmer. The binding resolver looks the slot up on the page in the engine's latest snapshot, which is the snapshot `SELECT_PLAYBACK` already reads its cue from (phase-4-plan §5.10). It submits `SELECT_PLAYBACK` for a `select` function and `PLAYBACK_BUTTON` for every other one. A select pressed within one tick of a page change can hit the old page. That race is harmless and accepted.
5. **A command's source control travels in its envelope**: `CommandOrigin.control`, the id of the binding that produced it.
   - The engine uses it for soft takeover and held buttons, so `_apply` receives the origin.
   - Takeover belongs to the control a command came from, not to the command. Envelopes are also what the event log (§15.5) will record.
   - Commands from the console, the phone and embedded `command` actions have no control. They act as jump sources.
6. **Soft takeover lives in the engine.** It is deterministic, and it sees page changes and every other source in order (§5.4).
   - Per control, the engine keeps the last physical value it received and what the control is attached to.
   - Per fader and per master, it keeps who set the level last.
   - A control on a `faderPickup: "soft"` surface applies its move when it is attached, or when the move crosses the current level or lands within 0.02 of it. It is then attached; otherwise the move is ignored.
   - Any other source that sets the level detaches it: another surface, the console, the phone, or this control moving another playback after a page change.
   - `jump` surfaces always apply.
   - Takeover covers playback faders and masters.
   - Motor faders are jump controls with feedback.
7. **Feedback** is computed from engine snapshots on a feedback thread at 30 Hz (§5.10).
   - Each binding with a `feedback` shows one value derived from its action, in the current page's terms: an LED (on/off), a motor-fader position, or an OSC label.
   - Values are sent only when they change, and in full when a surface opens.
   - A motor fader gets no feedback for 0.5 s after it moved, so it never fights the operator's finger.
   - A tap button's LED lights for the first quarter of every beat. To make that possible, each speed master's beat anchor joins the snapshot; it changes only at taps and tempo changes.
8. **Blackout bindings latch.** A press toggles blackout, which is what the spec's `BlackoutAction` says ("Toggle blackout"). Phase 2's hold-to-blackout is kept as `momentary: true`. `BLACKOUT` without `on` toggles in the engine, so two surfaces cannot disagree. This changes the Phase 3 show's ■ button from momentary to latching (decision 21).
9. **Swop** (§7.6, §8.1).
   - A swop button is a flash that also suppresses the intensity of every other playback that is not `protectFromSwop`, while any swop is held.
   - Suppression removes the playback's intensity *presence* (HTP weight 0, including its effects' intensity layers). It does not set `intensityScale = 0` as §7.6 writes. Under §7.4's formula, an override band that is still present at 0 would hold intensity at 0 over the swopped playback; with presence removed it cannot.
   - LTP values and the programmer are untouched.
   - Swop starts and stops instantly, like a flash.
10. **Goto buttons** go to `Playback.gotoCue`, a cue number of the playback's list, shared by all its `goto` buttons. Validation reports an error when the number names no cue of the list, as it does for embedded `GOTO` commands. A `goto` button without `gotoCue` gets a warning.
11. **`crossfade` faders** play a sequence by hand, the classic A/B way (§8.2, §5.6):
    - The fader rests at either end. It starts resting at 0, and after each transition it rests at the end where that transition completed.
    - Leaving the rest end starts the *pending* transition: to the next cue (as `GO` would, with a fresh number), or from idle to the first cue when `autoStart` is set. At the last cue of a list that does not wrap there is none, and the fader does nothing.
    - The transition's fades run on a virtual clock, `started + progress × span`. `progress` is the furthest the fader has travelled from the rest end, from 0 to 1. `span` is the transition's programmed length, or 1 s linear for a cue with no timing. Delays and per-family times keep their proportions.
    - Progress never decreases: the fader can pause a crossfade but not reverse it. Phase 4's fades settle as time passes and cannot be un-settled.
    - Reaching the far end completes the transition, and that end becomes the new rest end. Cue triggers (`follow`, `wait`) are ignored: the fader is the GO.
    - A button `GO`, `BACK`, `GOTO` or release, or a live edit, during a manual transition first freezes it where it is. It then proceeds as normal. The fader drives again once it has reached an end.
    - A `crossfade` fader scales nothing (`intensityScale` 1), and soft takeover treats its position like a level.
12. **Fade-time masters** (§5.13 "global fade override") *replace* transition times while their level is above 0.
    - The time is `T = 10 s × level²`, so a knob at 30 % gives 0.9 s, at 50 % 2.5 s, and at 100 % 10 s. With several fade-time masters the longest applies.
    - It applies to every playback transition that *starts* while it is up: activation, `GO`, `BACK`, `GOTO`, auto-GOs, and releases (by button, `autoRelease` or exclusivity). Every slot fades over `T` with no delay and the cue's in curve, and so do entering, changing and leaving effects (`sizeFadeIn` still applies).
    - An explicit `RELEASE_PLAYBACK {time}` wins over it. Flashes, swops, chase steps, the programmer and live edits keep their own timing.
    - Running fades are not changed. Fade-time masters start at level 0 when the show gives no `initialLevel`, so adding one changes nothing until it is raised.
13. **External tempo: MIDI clock arrives as taps.**
    - A new `midiClock` input address produces a press on every 24th clock (one per beat). A Start message makes the next clock a downbeat.
    - Bound to a `tap` action, it drives a speed master through the Phase 4 tap algorithm: tempo from the last 8 beats, the beat grid on each beat, and effects nudged without jumps (phase-5-plan decision 2).
    - Ableton Link needs a native library and stays open.
14. **OSC** (§5.11): OSC 1.0 over UDP, with a stdlib codec.
    - An `osc` surface listens on `match.port`. Feedback goes to `match.host` (else the address of the last message) at `match.feedbackPort` (else that message's source port).
    - A message's first argument is its value. Ints and floats are clamped to 0..1, `T`/`F` give 1/0, and a message without arguments is a press followed by a release.
    - Bundles are unpacked and their time tags ignored. Addresses are matched literally.
15. **The web remote** (§5.12), on stdlib only:
    - HTTP plus a WebSocket subset (RFC 6455: text frames, ping/pong, close, fragmented input, no extensions).
    - A `web` surface serves it on `match.port`, bound to `match.host` (default: every interface).
    - It speaks a small JSON protocol: the server sends `hello`, `show` summaries and engine `state` at up to 30 Hz; the client sends commands.
    - **Performance commands only**: §23 recommends a single writer with remotes that cannot edit. Programmer and show edits stay on the console.
    - **Access** needs a key kept per installation in `<stateDir>/web-key` and printed with the URL, compared in constant time. A browser connection must also come from the page's own origin (cross-site WebSocket hijacking).
    - The page is one bundled HTML file with no external resources, so it works in a venue without internet.
    - The phone addresses playbacks by id, so what you touch is what you get. Its faders drag relative to their level instead of jumping to the finger.
    - When a client disconnects, the server releases every flash and swop it held.
16. **Art-Net 4** (§5.14).
    - ArtDmx packets carry a sequence number (1–255) per Port-Address. A changed universe is sent at once, an unchanged one every second.
    - A `broadcast` route sends **unicast to every node that ArtPoll discovered outputting its Port-Address**, and broadcasts only while there is none. Art-Net 4 asks controllers to unicast, and §14.3 prefers it.
    - The console answers ArtPoll with an ArtPollReply (style: controller).
    - One socket bound to UDP 6454 carries all Art-Net traffic. Discovery runs inside the output thread's cycle, so it needs no thread of its own.
    - Interface broadcast addresses come from Linux `ioctl`s, as multicast already uses `ip_mreqn`.
17. **sACN universe discovery** (E1.31 §8): every 10 s, a universe list of the universes the show's sACN routes send. It goes to 239.255.250.214 on each interface that multicast routes use, serviced by the output thread.
18. **DMX-USB** with the Enttec DMX USB Pro protocol (§5.16).
    - Label 6 sends DMX. At open, label 4 sets the widget's output rate from `refreshHz` (at most 40).
    - It serves `enttecPro` and `dmxking`; DMXking interfaces speak the same protocol.
    - The serial device is opened raw and non-blocking with `termios`.
    - All 512 slots are sent, on change and every second.
    - After a write fails (an unplugged cable), the device is reopened every second (§14.2 "reconnect automatically").
    - `enttecOpen` needs breaks timed by the host. It is reported as ignored, with a notice.
19. **No new dependencies.** OSC, WebSocket, Art-Net and the Enttec protocol are small, fixed formats, written against their specifications as sACN was. If the hand-written WebSocket server proves fragile with real phones in step 20, the `websockets` package is the fallback; adding it is the user's call.
20. **Deferred again.**
    - The blind preview resolve (§7.6): no Phase 6 surface shows programmer values, so a per-tick second resolve would have no reader. It belongs with a programming UI, which §22 does not schedule.
    - The template editor beyond JSON layers.
    - Effect phases in the snapshot. Remotes derive beats from the new anchors, and effects show through their faders' levels.
21. **Backward compatible**: new commands and new optional fields only, so `schemaVersion` stays 1. Two behaviours change for existing shows:
    - blackout bindings latch (decision 8);
    - page-relative bindings follow the current page instead of always the first. A show with one page behaves exactly as before.

---

## 4. Project layout (new and changed files)

```
src/busk/
  model/
    surface.py           # MidiClock input; BlackoutAction.momentary; SurfaceMatch.feedbackPort (changed)
    playback.py          # Playback.gotoCue (changed)
    validate.py          # surface, binding, feedback, goto and page rules (changed)
  commands/
    types.py classes.py  # PageCmd, PlaybackButtonCmd; SET_FADER by slot; BLACKOUT toggle; CommandOrigin.control (changed)
    bus.py               # page-relative checks; fade-time masters accepted (changed)
  compiler/
    playbacks.py         # CompiledPage, pages; CompiledPlayback.gotoCue, protectFromSwop (changed)
    compile.py           # pages, softControls (changed)
    limitations.py       # (changed)
  engine/
    surfaces.py          # PageState, Pickup, HeldButtons (new)
    playback_runtime.py  # buttons, swop, manual crossfades, fade-time override (changed)
    effects.py           # presence at a separate fade time; hold (changed)
    masters.py           # fade_override() (changed)
    loop.py              # PAGE, PLAYBACK_BUTTON, origins, takeover, fade-time levels (changed)
    snapshot.py          # PageStatus; swop, progress; beat anchors; time (changed)
  io/
    bindings.py          # page-relative commands with the control; select; clock taps (changed)
    midi.py              # MIDI clock beats; MidiOutput (changed)
    feedback.py          # feedback values and the feedback thread (new)
    osc.py               # OSC 1.0 codec, OscSurface (new)
    surfaces.py          # SurfaceManager: MIDI, OSC and web surfaces, following live edits (new)
  web/
    websocket.py         # RFC 6455 subset (new)
    server.py            # HTTP + WebSocket server, access key, origin check (new)
    api.py               # hello, show, state and command messages (new)
    static/index.html    # the phone remote (new)
  output/
    driver.py sacn.py    # SendPolicy parameters; universe discovery (changed)
    scheduler.py         # Art-Net and DMX-USB routes; discovery serviced per cycle (changed)
    artnet.py            # ArtDmx sender, ArtPoll discovery, ArtPollReply (new)
    dmxusb.py            # Enttec Pro protocol over a serial device (new)
    netif.py             # interface addresses and broadcast addresses, Linux (new)
  persistence/autosave.py paths.py   # the page; the web key (changed)
  console/parser.py console.py       # §5.17 (changed)
  cli.py                 # SurfaceManager, feedback thread, status line, "Ignored in Phase 6:" (changed)
examples/phase6-surfaces.busk
bench/surface_load.py    # engine ticks under surface load (new)
tests/golden/phase6_surfaces_show.json  tests/golden/phase6_frames.json
tests/ws_client.py       # a minimal WebSocket client for tests (new)
tests/…                  # see §7
```

The engine still imports neither `io/`, `web/` nor `session/`. The web server and the feedback thread read published snapshots and submit commands, as the console and bindings do.

---

## 5. Component design

### 5.1 Pages (`compiler/playbacks.py`, `engine/surfaces.py`, `engine/loop.py`)

```python
@dataclass(frozen=True, kw_only=True)
class CompiledPage:
    id: str
    number: int
    name: str
    slots: tuple[PlaybackId | None, ...]

# CompiledShow.firstPage is replaced by
#   pages: tuple[CompiledPage, ...]      # sorted by number

class PageState:                         # engine thread
    pages: tuple[CompiledPage, ...]
    index: int | None                    # None only without pages
    @property
    def current(self) -> CompiledPage | None: ...
    def go(self, *, number: int | None = None, delta: int | None = None) -> bool: ...  # whether it moved
    def playback(self, slot: int) -> PlaybackId | None: ...  # None: empty, or beyond the page
    def rebind(self, pages: tuple[CompiledPage, ...]) -> None: ...  # by id, else the next number, else the last
```

- `EngineRuntime.page: PageState` is built at start and rebound in `_swap`.
- `PAGE` is a performance command. The bus checks that `number` names a page, or that `delta` is an integer, and that exactly one of the two is given.
- `Engine.tick` marks the snapshot dirty when the page changes. The snapshot's `page` is a `PageStatus(id, number, name)`.
- **Autosave**: `session.json` gains `page`, the current page's id. Recovery submits `PAGE {number}` after the masters and tempos, when the show still has that page.

### 5.2 Page-relative commands and playback buttons (`commands/`, `engine/loop.py`, `engine/surfaces.py`)

```python
class SetFaderCmd(TypedDict):            # performance (Phase 6: by slot too)
    type: Literal["SET_FADER"]
    playbackId: NotRequired[PlaybackId]  # exactly one of playbackId …
    slot: NotRequired[NonNegativeInt]    # … and a 0-based slot of the current page
    level: Unit

class PlaybackButtonCmd(TypedDict):      # performance (new)
    type: Literal["PLAYBACK_BUTTON"]
    playbackId: NotRequired[PlaybackId]  # exactly one of playbackId and slot
    slot: NotRequired[NonNegativeInt]
    button: NonNegativeInt               # index into the playback's buttons
    down: bool

class PageCmd(TypedDict):                # performance (new)
    type: Literal["PAGE"]
    number: NotRequired[int]             # exactly one of number …
    delta: NotRequired[int]              # … and delta (stops at the ends)

class BlackoutCmd(TypedDict):
    type: Literal["BLACKOUT"]
    on: NotRequired[bool]                # absent: toggle (Phase 6)

class CommandOrigin(TypedDict, total=False):
    surfaceId: SurfaceId
    user: str
    remote: str
    control: str                         # the binding that sent it (Phase 6)
```

- **Engine.** `Engine.tick` passes each envelope's origin to `_apply(command, now, origin)`. A `slot` resolves through `PageState.playback`; an empty slot does nothing and is not an error.
- **`PLAYBACK_BUTTON`** dispatches on the function (decision 3). `goto` uses `CompiledPlayback.gotoCue`: the cue index the compiler found for the number, or `None`.
- **Held buttons.** A flash or swop press through a slot *with a control* records `HeldButtons.press(control, playback, function)`. The release from that control goes to the recorded playback, whatever the page is now. A release with nothing recorded resolves the slot as usual. Presses by `playbackId` need no record.
- **The bus.** Exactly one of `playbackId` and `slot` (and of `number` and `delta`), each checked. A `playbackId` must exist, and `button` must be an integer ≥ 0. `PAGE {number}` must name a page.
- **Classes.** `PAGE` and `PLAYBACK_BUTTON` are performance commands, which makes 34 command types. `FLASH`, `GO`, `TOGGLE_PLAYBACK` and the rest stay as they are, for the console and embedded commands.

### 5.3 Swop (`engine/playback_runtime.py`)

- `Playbacks.swopping: dict[PlaybackId, int]` counts the swop presses held per playback.
- A swop press brings the playback's flash up, as `FLASH` down does, and adds the playback to `swopping`; the release reverses both.
- `PlaybackStatus.swop` is true while held.
- **Suppression.** In `PlaybackRuntime.update(now, suppressed)`, `suppressed` is true when something is swopping, this playback is not, and it is not `protectFromSwop`. A suppressed runtime gets `htpWeight = 0` on main and flash and passes 0 to its banks' `EffectScalars.htpWeight`. Absolute intensity layers then have no presence, and relative intensity layers no weight (their weight is `htpWeight × intensityScale × presence`).
- Nothing is faded, so releasing the swop gives back the exact frame. Swop applies no exclusivity, like a flash (phase-2-plan §9).

### 5.4 Soft takeover (`engine/surfaces.py`)

```python
PICKUP_TOLERANCE: Final = 0.02
type Knob = tuple[Literal["fader", "master"], str]   # a playback fader or a master

class Pickup:                            # engine thread
    last: dict[str, float]               # control → last value received (applied or not)
    attached: dict[str, Knob | None]     # control → what its last applied move set
    setter: dict[Knob, str | None]       # knob → the control that set it last (None: a jump source)

    def accept(self, control: str | None, soft: bool, knob: Knob,
               level: float, value: float) -> bool: ...
```

`accept` decides whether a move applies, and records it:

```
if control is None:            setter[knob] = None; apply
p = last.get(control); last[control] = value
attached_now = attached.get(control) == knob and setter.get(knob) == control
if not soft or attached_now or |value − level| ≤ PICKUP_TOLERANCE
   or (p is not None and min(p, value) ≤ level ≤ max(p, value)):
    attached[control] = knob; setter[knob] = control; apply
else:
    attached[control] = None; ignore
```

- **The engine** calls it for `SET_FADER` (the level is the runtime's `faderLevel`) and `SET_MASTER` (the master's own level: grand, group, size, speed or fade time). `soft` is `control in compiled.softControls`, the bindings whose surface has `faderPickup: "soft"`.
- **Page changes** need no special case: after one, a control's knob is another playback, so it is not attached until it crosses that playback's level.
- **Live edits** keep the state by binding id, so switching a surface between `jump` and `soft` takes effect at the swap.
- **Motor faders** are `jump`. The motor brings the hardware to the level instead.

### 5.5 Fade-time masters (`engine/masters.py`, `engine/playback_runtime.py`)

- `fade_override(masters, levels) -> float | None` returns `10 × max(level)²` over the fade-time masters with a level above 0, or `None` (decision 12).
- `EngineRuntime.fadeLevels` holds the levels. `Playbacks.fade`, a holder shared with every runtime like `speed` and `sizeLevels`, keeps the current override. It is recomputed on `SET_MASTER` of a fade-time master and on a swap.
- **`PlaybackRuntime._timing(target)` and `_effect_timing(target)`.** With an override and outside a chase, `_timing` returns `Uniform(Timing(T, 0, curve of target.inTiming))` and `_effect_timing` returns `EffectTiming.uniform` with the same timing. `rebind` (a live edit) passes `override=False`.
- **Releases.** `Playbacks.release` without an explicit `time`, `toggle`, `autoRelease`, exclusivity, and `GO` past the end with `releaseAtEnd` use `T` instead of `releaseTime`.
- **Auto-GOs** read the holder when they fire. Due events fire before the tick's commands (phase-4-plan decision 2), so the result does not depend on the tick schedule.
- **The bus.** `MASTER_ARRIVES_IN` becomes empty and `SET_MASTER` accepts fade-time masters. `CompiledMaster.initialLevel` defaults to 0 for them. The snapshot's `masterLevels` lists their levels too, so autosave and recovery restore them.

### 5.6 Crossfade faders (`engine/playback_runtime.py`, `engine/effects.py`)

```python
@dataclass(slots=True)
class Manual:                            # a transition driven by a crossfade fader
    started: float                       # real time it started (its fades start here)
    span: float                          # its programmed length (> 0), or 1 s
    rest: float                          # the end the fader left: 0.0 or 1.0
    progress: float = 0.0                # furthest |level − rest| so far; never decreases
    @property
    def time(self) -> float: return self.started + self.progress * self.span
```

`PlaybackRuntime` gains `manual: Manual | None` and `crossRest: float | None`. `crossRest` is the end the fader rests at: 0.0 at start, and `None` after a button took a transition over, until the fader reaches an end.

**`set_fader` on a `crossfade` fader** (decision 11):
1. With `crossRest is None`: a level of exactly 0 or 1 sets it, and nothing else happens.
2. Without a manual transition, a level ≠ `crossRest` starts one at `now`:
   - an active playback moves to its next cue (`next_cue`: at the end it wraps, or there is no pending transition);
   - an idle one activates at its first cue, if `autoStart` is set.

   Both take a fresh number, like `GO`. The retarget uses the cue's timing (or the fade-time override). Its completion gives `span = completes − started`; a span of 0 means retargeting again with `Uniform(Timing(1.0))`.
3. With one, `progress = max(progress, |level − rest|)`. At 1 the transition completes: `crossRest = 1 − rest`, and `manual = None`.

**Per tick**, while `manual` is set, `contributions.evaluate(manual.time)` and `bank.update(now, scalars, fadeAt=manual.time)`. Effect clocks keep moving in real time; only their presence follows the fader. `manual.time` never decreases, which `ContributionSet.evaluate` requires.

**Interruptions.** `GO`, `BACK`, `GOTO`, a release, re-activation or a live edit during a manual transition first call `_materialise()`:
- `contributions.freeze(manual.time)`, and `bank.hold(now, manual.time)`, which holds every presence at its value at that time;
- then `manual = None` and `crossRest = None`.

Then they proceed as usual: retargets start from the held values, so nothing jumps.

**Snapshot.** `PlaybackStatus.progress` is the progress during a manual transition, else `None`. `_schedule` arms no auto-GO for a `crossfade`-fader playback.

### 5.7 Snapshot, status line and autosave (`engine/snapshot.py`, `cli.py`)

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class PageStatus:
    id: str
    number: int
    name: str

# PlaybackStatus gains   swop: bool = False;  progress: float | None = None
# SpeedStatus gains      beatTime: float; beat: float   # beats(t) = beat + (t − beatTime) · bpm / 60
# EngineSnapshot gains   page: PageStatus | None = None;  time: float   # the tick's time
```

- `beatTime` and `beat` are the speed master's `T0` and `B0`. They change only at taps and tempo changes, so a running master publishes no snapshot per tick (phase-4-plan §5.11). Feedback and remotes derive the beat phase from them.
- **The status line** gains the page after blackout and the fade time when it is up:

  ```
  GM 100% | BO off | P2 Washes | Speed 1 120 BPM ×1 | Fade 2.5 s | 9 Song on 4 Chorus · 14 Wash Blue on 0.25
  ```
  A playback is listed with `swop` while held, and with its progress (`18 Manual on 1 → 2 50%`) during a manual crossfade.

### 5.8 Bindings (`io/bindings.py`)

| Action | Phase 5 | Phase 6 |
|---|---|---|
| `playbackFader {slot}` | `SET_FADER` of `firstPage[slot]` | `SET_FADER {slot}` |
| `playbackFaderAbs` | `SET_FADER {playbackId}` | the same |
| `playbackButton {slot, button}` | a command per function, resolved here | `PLAYBACK_BUTTON {slot, button, down}` on each edge; a `select` function (looked up on the snapshot's page) → `SELECT_PLAYBACK` on press |
| `master` | `SET_MASTER` (not fade-time) | `SET_MASTER`, every kind |
| `tap` | `TAP` on press | the same, also from `midiClock` inputs |
| `blackout` | `BLACKOUT {on}` while held | `BLACKOUT {}` (toggle) on press; with `momentary`, as before |
| `page {delta}`, `pageAbs {number}` | ignored | `PAGE` on press |
| `command` | the command on press | the same |

- Every command carries `origin = {surfaceId, control: binding id}`.
- The resolver gains `page: Callable[[], str | None]`, the current page id from the engine snapshot, used only for `select`.
- It records `lastInput[binding id] = now` for the feedback thread's echo hold (§5.10).

### 5.9 MIDI clock and MIDI output (`io/midi.py`)

- **Clock.** `translate` keeps a per-surface clock counter. A `clock` message at count ≡ 0 (mod 24) is a press of `midiClock`, and at count ≡ 1 a release. `start` resets the count, so the next clock is a downbeat; `songpos` sets it to `6 × position`; `stop` and `continue` change nothing. Step 9 first checks that mido's rtmidi backend delivers timing messages; if it filters them, it calls `ignore_types(timing=False)` on the underlying port.
- **`MidiOutput(surface)`** opens the first *output* port whose name contains `match.deviceName`, as `MidiInput` does for inputs. `send(address, value)` encodes:

  | Address | `led` | `motorFader` |
  |---|---|---|
  | `midiCC` | 127 / 0 | `round(value × 127)` |
  | `midiNote` | `note_on` velocity 127 / `note_off` | `note_on` velocity `round(value × 127)` |
  | `midiPitchBend` | — | pitch `round(value × 16383) − 8192` |

  Only the feedback thread sends, so a port is never written by two threads.

### 5.10 Feedback (`io/feedback.py`)

```python
FEEDBACK_HZ: Final = 30.0
ECHO_HOLD: Final = 0.5               # seconds without motor feedback after the control moved
BEAT_LIT: Final = 0.25               # the part of each beat a tap LED is lit

def feedback_values(compiled: CompiledShow, snapshot: EngineSnapshot,
                    now: float) -> dict[str, float | str]: ...   # binding id → value (pure)

class FeedbackWorker:                # its own thread
    def service(self, now: float) -> None: ...
    def run(self, stop: threading.Event) -> None: ...
```

A binding's value comes from its action, on the current page:

| Action | `led` (1 or 0) | `motorFader` | `display` (OSC) |
|---|---|---|---|
| `playbackFader`, `playbackFaderAbs` | level > 0 | the fader level | the playback's name (empty slot: "") |
| `playbackButton` | `go`, `back`, `toggle`, `release`, `select`: the playback is active; `goto`: active at its `gotoCue`; `flash`: flash present; `swop`: swop held | — | the playback's name |
| `master` | level > 0 | the level | the master's name |
| `tap` | lit during the first quarter of each beat | — | `"<bpm> BPM"` |
| `blackout` | blackout on | — | — |
| `page {delta}` | a page exists in that direction | — | the current page's name |
| `pageAbs {number}` | that page is current | — | that page's name |

- **The worker.** Each cycle it reads the snapshot (and `now` from the engine clock for the beat). It sends only changed values: through `MidiOutput` for MIDI surfaces (it owns those ports, and reopens them when `compiled.surfaces` changes), and through the `OscSurface` for OSC surfaces. A surface that (re)opens gets every value.
- **Echo hold.** `motorFader` values are held back while `now − lastInput[binding] < ECHO_HOLD`.
- **Errors.** A send that raises is counted on its surface and reported once, like binding errors. The worker never stops on one.

### 5.11 OSC (`io/osc.py`)

```python
OscArg = int | float | str | bytes | bool | None
def decode(packet: bytes) -> list[tuple[str, tuple[OscArg, ...]]]: ...   # bundles flattened
def encode(address: str, *args: float | str) -> bytes: ...

class OscSurface:                    # one osc surface: a UDP socket and a receive thread
    def open(self) -> str | None: ...                    # None, or why it cannot listen
    def close(self) -> None: ...
    def send(self, address: str, value: float | str) -> None: ...   # feedback; never raises
```

- **The codec.**
  - Padded OSC-strings; types `i f d h s b T F N I`. A message with an unknown type tag is dropped.
  - Bundles (`#bundle`, a time tag, elements with sizes) are decoded recursively.
  - Truncated or malformed packets are counted and dropped, never raised.
- **Input.** The receive thread blocks in `recvfrom` with a 0.2 s timeout (to notice `close`). Each message turns into `InputEvent(surface, {kind: "osc", path}, value)` (decision 14) for `BindingResolver.handle`.
- **Feedback** goes out of the same socket, so its source port is the port the client sends to; some clients reply only to that.

### 5.12 The web remote (`web/`)

**Protocol layer** (`web/websocket.py`, `web/server.py`):
- `ThreadingHTTPServer` serves:
  - `GET /` and `/index.html` (with `?k=<key>`, else 403 with a hint);
  - `GET /ws?k=<key>`, which upgrades to a WebSocket;
  - nothing else (404). No path ever reaches the file system: the page is read with `importlib.resources`.
- **The upgrade** checks `Upgrade`, `Connection`, version 13 and the key, then the `Origin` header. It must be absent, as from non-browser clients, or equal `http://<Host>`. It then answers 101 with `Sec-WebSocket-Accept = base64(SHA-1(key + GUID))`.
- **Frames are read from the handler's buffered `rfile`.** It may already hold bytes of the first frame.
  - Client frames must be masked.
  - Accepted: text, continuation, ping (answered with a pong), pong and close (answered).
  - Close codes: binary 1003, a message over 64 KiB 1009, a protocol error 1002, invalid UTF-8 1007.
- **Each client has a writer thread** with three slots: the latest `state`, the latest `show`, and a short queue of replies. A client whose socket blocks for 2 s is closed, and the others are unaffected.

**Messages** (`web/api.py`), JSON, `"version": 1`:

| Direction | Message | When |
|---|---|---|
| server → client | `{"type": "hello", "version", "surface", "time"}` | on connect |
| | `{"type": "show", "pages": [{id, number, name, slots}], "playbacks": [{id, number, name, fader, buttons, gotoCue, cueCount}], "masters": [{id, name, kind, steps}]}` | on connect; when the compiled show changes (by identity) |
| | `{"type": "state", …the EngineSnapshot as JSON…}` | on connect; when the snapshot changes, at most 30 Hz |
| | `{"type": "error", "id", "message"}` | a command the bus rejects |
| client → server | `{"id": "<client id>", "command": {…}}` | performance commands only; others are rejected with an error |

- **The broadcaster thread** checks `engine.snapshot` and `engine.bus.compiled` 30 times a second, serialises each new one once, and drops it into every client's slot. A burst of fader moves therefore costs at most 30 messages a second per client.
- **Commands** go through `Session.submit` with `origin = {surfaceId, remote: "ip:port"}`. Only performance commands are accepted, so nothing takes the session lock.
- **On disconnect** the API submits `PLAYBACK_BUTTON` up for every flash and swop the client still held (it tracks its own presses).

**The page** (`web/static/index.html`, one file, vanilla JS and CSS, no external URLs):
- A header with page ◀ name ▶, a latching BO button, the grand master, TAP with the BPM and a beat dot (from the anchors and the server's `time`), and the status.
- One strip per slot of the current page, showing:
  - the name, and the current cue of a sequence;
  - the state's colour: idle grey, active green, releasing amber, flash white;
  - a fader that drags relative to its level (`touch-action: none`, one touch per fader, sends coalesced to animation frames);
  - the playback's buttons by function (`GO`, `BACK`, `GOTO 4 Chorus`, `FLASH`, `SWOP`, `ON/OFF`, `REL`), sending `PLAYBACK_BUTTON {playbackId}` down and up. `select` is hidden.
- A masters row: size, group, speed and fade-time levels.
- It reconnects every second when the connection drops.

### 5.13 Surfaces in `busk run` (`io/surfaces.py`, `cli.py`)

- **`SurfaceManager`** replaces `cli.MidiPorts`. `reconcile(compiled)` opens new or changed surfaces and closes removed ones, per kind:
  - `midi`: a `MidiInput` (as now);
  - `osc`: an `OscSurface`;
  - `web`: a `WebServer`, restarted when its port or host changes.

  The supervisor calls it on every poll, as it called `MidiPorts`. It publishes an immutable `surfaceId → OscSurface` map for the feedback worker. A surface that cannot open is reported with the reason, and the run goes on.
- **Start-up lines** (stdout; failures to stderr):

  ```
  MIDI s-nano: nanoKONTROL2:nanoKONTROL2 _ CTRL 20:0
  MIDI s-nano feedback: nanoKONTROL2:nanoKONTROL2 _ CTRL 20:0
  OSC s-touch: listening on udp 8000, feedback to the sender at port 9000
  Web s-phone: http://10.0.0.5:8080/?k=Qx7f2LmA          (one line per IPv4 interface)
  ```
- **Threads**, started after the engine and output threads: the feedback worker, and the web broadcaster inside each `WebServer`.
- **Shutdown** runs in this order, so no command arrives after the engine stopped:
  1. inputs (the supervisor, `SurfaceManager.close()`, which stops OSC and web);
  2. the feedback worker;
  3. the session, the engine, the output thread and autosave, as now.
- **`busk run --state-dir`** also holds `web-key`: 8 URL-safe characters, created once (`paths.web_key`). Deleting the file makes a new key.

### 5.14 Art-Net (`output/artnet.py`, `output/netif.py`)

```python
ARTNET_PORT: Final = 6454            # read at open, so tests can patch it
POLL_INTERVAL: Final = 2.5           # seconds between ArtPolls
NODE_TIMEOUT: Final = 10.0           # a node not heard from for this long is forgotten

def art_dmx(sequence: int, port_address: int, data: bytes) -> bytes: ...   # 18 + 512 bytes
def art_poll() -> bytes: ...
def art_poll_reply(ip: IPv4Address, name: str) -> bytes: ...
def parse_poll_reply(packet: bytes) -> Node | None: ...   # ip, names, output port-addresses

class ArtNetNetwork:                 # one per output scheduler, opened with the first Art-Net route
    def service(self, now: float) -> None: ...   # drain replies and polls (non-blocking); poll when due
    nodes: Mapping[IPv4Address, Node]           # replaced, never mutated

class ArtNetSender:                  # an OutputDriver for one route
    ...
```

- **ArtDmx.** The fields in order:
  - `"Art-Net\0"`;
  - OpCode 0x5000, little-endian;
  - ProtVer 14;
  - Sequence 1–255, per Port-Address and shared by the routes that send it;
  - Physical 0;
  - SubUni (sub-net × 16 + universe) and Net;
  - Length 512, big-endian;
  - the data.

  The packet is built once, and a send writes only the sequence and the data, as sACN does.
- **Transmission.** `SendPolicy(repeats=0, keepalive=1.0)`: the sACN policy with parameters, so a changed universe goes at once and an unchanged one every second.
- **Destinations.**
  - `unicast`: that host.
  - `broadcast`: unicast to every discovered node with the route's Port-Address among its outputs, or the interface's directed broadcast (`netif.broadcast_address(iface)`) while there is none. The socket has `SO_BROADCAST`.
- **Discovery.** The output thread calls `ArtNetNetwork.service` once per cycle. It reads every waiting datagram without blocking: ArtPollReplies update `nodes`, and ArtPolls from other controllers get an ArtPollReply naming this console (`sacnSourceName`, style `StController`). Every `POLL_INTERVAL` it sends an ArtPoll to the broadcast address of each interface the routes use. Nodes that appear or are forgotten are reported on the scheduler's notices:

  ```
  Art-Net: node 2.0.0.10 'DMX Node 1' outputs 0:0:1
  ```
- **The socket** is bound to `0.0.0.0:6454` with `SO_REUSEADDR`. If that fails (another Art-Net program), the routes send from an ephemeral port and discovery is off, with a notice.
- **`netif`** (Linux) provides `ipv4_interfaces() -> [(name, address)]` and `broadcast_address(iface)`, through `SIOCGIFADDR` and `SIOCGIFBRDADDR`. `iface` may be a name or one of the interface's addresses. Elsewhere it raises `OSError("… needs Linux")`, and the route reports that it cannot open.

### 5.15 sACN universe discovery (`output/sacn.py`)

```python
DISCOVERY_UNIVERSE: Final = 64214            # multicast 239.255.250.214
DISCOVERY_INTERVAL: Final = 10.0
def discovery_packets(*, cid: bytes, sourceName: str, universes: Sequence[int]) -> list[bytes]: ...
```

- **The packet** (E1.31 §6.4, §8):
  - root vector `VECTOR_ROOT_E131_EXTENDED` (8);
  - framing vector `VECTOR_E131_EXTENDED_DISCOVERY` (2), with the source name and 4 reserved bytes;
  - universe discovery vector `VECTOR_UNIVERSE_DISCOVERY_UNIVERSE_LIST` (1), with page, last page, and up to 512 sorted universes per page.
- **Sending.** The scheduler sends the pages every `DISCOVERY_INTERVAL` while any sACN route is open. The list holds the universes of the enabled sACN routes. The packets go to the discovery group on each interface that multicast routes use.
- A show with only unicast routes sends no discovery, which is noted in the README.

### 5.16 DMX-USB (`output/dmxusb.py`)

```python
SEND_DMX: Final = 6                  # "Output Only Send DMX Packet Request"
SET_PARAMETERS: Final = 4            # break, mark-after-break, output rate
REOPEN_S: Final = 1.0

def enttec_message(label: int, data: bytes) -> bytes: ...   # 0x7E label len_lsb len_msb data 0xE7

class EnttecSender:                  # an OutputDriver for enttecPro and dmxking routes
    ...
```

- **Open.**
  - `os.open(port, O_RDWR | O_NOCTTY | O_NONBLOCK)`, then raw mode (`tty.setraw`) at 115200 baud, 8N1. The rate is ignored by the widget; 115200 is what other drivers set.
  - Then label 4: break 9 (× 10.67 µs), mark-after-break 1, rate `min(40, round(refreshHz))`.
- **Send.** Label 6 with start code 0 and 512 slots, on change or after 1 s. A partial non-blocking write keeps its remainder. The next send finishes it first, and drops its own frame if that is still not possible (counted, not an error).
- **Failure.** A write error (`EIO`, `ENXIO`, `ENODEV` on unplug) closes the descriptor and marks the route failed. `send` then tries to reopen every `REOPEN_S`. On success it sends the parameters and a full frame, and the status says "sending again".
- **Close** sends nothing: the widget keeps its last frame, and the cable carries no "stream end".
- **Scheduler.** `enttecOpen` routes get the notice `DMX-USB r3: ignored (Open DMX USB needs host-timed breaks; use an Enttec Pro or DMXking interface)`.
- **Tests** use `os.openpty()`. The route's port is a symlink in a temporary directory, so re-pointing it at a new pseudo-terminal simulates a replug.

### 5.17 Console (`console/parser.py`, `console/console.py`)

| Area | Syntax | Becomes |
|---|---|---|
| Pages | `page N`, `page next`, `page prev` | `PAGE {number}` / `{delta: ±1}` |
| | `page add N ["name"]` | `ADD` to `pages` |
| | `page P slot S playback N`, `page P slot S clear` | `ASSIGN_PLAYBACK` |
| | `record slot [P.]S …` | as before, on page `P`; without it, the current page (the engine snapshot's, else the first) |
| Surfaces | `surface add osc "<name>" [port N] [feedback <host>[:<port>]]` | `ADD` (`match.port` default 8000) |
| | `surface add web "<name>" [port N] [on <host>]` | `ADD` (`match.port` default 8080) |
| | `surface "<name>" pickup soft\|jump` | `SET` of `faderPickup` |
| Bindings | `bind "<s>" osc "/path" <what>` | a binding with an `osc` input |
| | `bind "<s>" clock tap ["<master>"]` | `midiClock` → `tap` |
| | `<what>` also: `page +N\|-N`, `page N`, `fader playback N`, `blackout [momentary]` | `page`, `pageAbs`, `playbackFaderAbs`, blackout |
| | `bind … <what> [led\|motor\|display [cc\|note <ch> <n> \| osc "/path"]]` | feedback, on the input's own address unless one is given |
| Feedback | `feedback "<s>" cc\|note <ch> <n> [thru <m>] led\|motor\|display`, `feedback "<s>" osc "/path" …`, `feedback … none` | a `BATCH` of `SET`s of `feedback` on every binding of those inputs; `none` removes it |
| Playbacks | `playback N goto <cue>` | `SET` of `gotoCue` |
| Masters | `master add fadetime "<name>"` | `ADD` (no `initialLevel`: it starts at 0) |
| Routes | `route add U dmxusb enttecPro\|dmxking <port> [hz N]` | `ADD` (`refreshHz` default 40) |
| Query | `list pages` marks the current page; `list surfaces` shows kind, port or device and pickup; `list bindings` names masters and pages and shows feedback; `status` shows the page and the fade time | — |

- **Scripts name their pages.** `page 2` is a performance command and reaches the engine a tick later. A script that writes `page 2` and then `record slot 1` would race it, so scripts write `record slot 2.1`.
- `list bindings` naming masters by name closes a Phase 4 rough edge, because that listing is rewritten for the new actions anyway.
- `help` is generated from the module docs, as before.

### 5.18 Validation and the limitation report

**Validation** (`model/validate.py`, semantic pass). Errors:
- an `osc` or `web` surface without `match.port` in 1–65535, or two surfaces of one of those kinds on the same port;
- a `feedback.address` of kind `midiClock`;
- `gotoCue` naming no cue of the playback's list;
- an embedded `SET_FADER` or `PLAYBACK_BUTTON` without exactly one of `playbackId` and `slot`, or a `PAGE` without exactly one of `number` and `delta`, or naming no page.

Warnings:
- a binding whose input its surface cannot send: MIDI inputs off `midi` surfaces, `osc` off `osc` surfaces, any binding on a `web` surface;
- a `goto` button without `gotoCue`;
- a `pageAbs` action naming no page;
- a `midiClock` input bound to anything but `tap`;
- feedback on a `web` surface, which shows state by itself.

**The limitation report** (header `Ignored in Phase 6:`) keeps:
- `hid` and `internal` surfaces, and `hw` inputs (unassigned in the roadmap);
- `display` feedback on MIDI surfaces, and feedback on `command` actions;
- limits and park (Phase 7);
- `holdLastFrameOnEngineStall: false` (Phase 7).

The lines for pages, OSC and web surfaces, soft pickup, feedback, page actions, `crossfade` faders, `goto` and `swop` buttons and fade-time masters go. As before, Art-Net and DMX-USB routes are reported by the scheduler, not here.

### 5.19 The done criterion: `examples/phase6-surfaces.busk`

Run after the three earlier scripts, on the show they saved. Playback and cue list numbers follow `record slot`'s rule (the slot's number if free, else one above the highest): 14–17 for the wash looks, 18 for "Manual".

```
surface "nanoKONTROL2" pickup soft
surface add web "Phone"
master add fadetime "Fade"

# ------------------------------------------------ page 2: wash looks
page add 2 "Washes"
sel group 2
set intensity 100%
preset color 1
record slot 2.1 "Wash Blue"
preset color 2
record slot 2.2 "Wash Red"
preset color 3
record slot 2.3 "Wash Green"
preset color 4
record slot 2.4 "Wash Amber"
clear
playback 14 exclusivity wash                  # … and 15, 16, 17
playback 14 buttons ["toggle", "swop", "release"]   # M swops: … and 15, 16, 17

# ------------------------------------------------ page 2: a manual crossfade on fader 8
sel group 3
set intensity 100%
preset color 1
record slot 2.8 "Manual"
preset color 2
record cue 18/2
preset color 3
record cue 18/3
clear
cuelist 18 wrap true
playback 18 fader crossfade
playback 18 buttons ["go", "back", "release"]

# ------------------------------------------------ the knob playbacks on page 2 too
page 2 slot 9 playback 9                      # … 10, 11, 12, 13

# ------------------------------------------------ the song: a goto button for the phone
playback 9 buttons ["go", "back", "release", "goto"]
playback 9 goto 4

# ------------------------------------------------ nanoKONTROL2: pages and LEDs (LED mode: external)
bind "nanoKONTROL2" cc 1 61 page -1           # marker ◀
bind "nanoKONTROL2" cc 1 62 page +1           # marker ▶
feedback "nanoKONTROL2" cc 1 32 thru 39 led   # S: the slot's playback is active
feedback "nanoKONTROL2" cc 1 48 thru 55 led   # M: flash or swop held
feedback "nanoKONTROL2" cc 1 64 thru 71 led   # R: active
feedback "nanoKONTROL2" cc 1 41 thru 45 led   # play, stop (blackout), rewind, fast-forward, record
feedback "nanoKONTROL2" cc 1 46 led           # cycle: the beat
save
```

**Checkpoints of `test_surfaces_show.py`.**
- The performance part runs on a fresh engine built from the saved show, at 100 Hz, with "Speed 1" at 120 BPM from t = 0.
- MIDI moves go through `BindingResolver.handle` (CC values as `n/127`, written here as levels). Phone commands go through `WebApi.on_message`, applied at the next tick.
- Warm is all fixtures at 0.8, colour (1, .75, .45).
- Expected values are logical and computed by hand.

| t (s) | Input | Check |
|---|---|---|
| 0, 0.1, 0.2 | MIDI fader 1: 0, 0.5, 1 | 0 attaches the soft fader; Warm comes up. At 0.3 everything is at 0.8, warm; S1 LED on; status `P1 Main` |
| 1 | marker ▶ | page 2: S1 LED off (Wash Blue is idle); the phone's state shows page 2 "Washes" |
| 1.5 | fader 1 → 0.9 | ignored: Wash Blue stays idle (no jump to 90 %) |
| 2 | fader 1 → 0 | crosses 0: attached to Wash Blue; nothing changes |
| 2.5 | fader 1 → 0.6 | Wash Blue starts. At 2.6 the washes are 0.8 (Warm wins HTP) and blue (0, 0, 1) (newer LTP); S1 LED on |
| 3 | phone: Wash Blue fader 0.3 | the MIDI fader detaches; the washes are still 0.8 blue |
| 3.5 | fader 1 → 0.65 | ignored: Wash Blue stays at 0.3 |
| 4 | fader 1 → 0.25 | crosses 0.3: Wash Blue at 0.25; the phone's state shows 0.25 |
| 5 | fader 8 → 0 | attaches to Manual |
| 5.5 | fader 8 → 0.25 | Manual starts by hand at cue 1 (0 s timing: 1 s linear). Bar: intensity 0.8 (Warm over 0.25), colour (0.75, 0.5625, 0.5875); snapshot progress 0.25 |
| 6 | fader 8 → 1 | cue 1 complete: bar 1.0, blue |
| 6.5 | fader 8 → 0.5 | halfway to cue 2: bar (0.5, 0, 0.5) |
| 6.7 | fader 8 → 0.6 | no change: progress only moves forward |
| 7 | fader 8 → 0 | cue 2 complete: bar red; rests at 0 |
| 8 | M2 down | swop on Wash Red: washes 1.0 red; heads and bar intensity 0; M2 LED on |
| 8.5 | M2 up | the frame equals the frame at 7.9 |
| 9, 9.05 | ■ down, up | blackout latched: every intensity 0; stop LED on |
| 9.5, 9.55 | ■ down, up | off: the frame equals the frame at 8.9 |
| 10 | marker ◀ | page 1: S1 LED on (Warm active) |
| 10.5 | phone: master "Fade" 0.5 | status `… \| Fade 2.5 s \| …` |
| 11 | phone: the song's goto button (down, up) | GOTO 9/4 (Chorus) over 2.5 s; base exclusivity releases Warm over 2.5 s |
| 12.25 | | washes: intensity 0.5 (Chorus 0.5, Warm 0.4, Wash Blue 0.25), colour (0.5, 0.5, 1). Heads: 0.5, colour (1, 0.9375, 0.8625), MH 1 pan −15, tilt 20. Play LED on |
| 14.0, 14.2 | | cycle LED on (beat 28), off |
| — | — | the whole run at 100 Hz and on a random irregular schedule gives byte-identical frames at every checkpoint, and so does save → load |

- **A network test** runs the phone part through a real WebSocket. The `WebServer` listens on localhost with an ephemeral port, the engine ticks on a fake clock from the test, and the client is `tests/ws_client.py`. The test checks the hello, show and state messages; a `SET_FADER` reaching the engine; a page change made from MIDI arriving as state; a rejected show edit; a wrong key (403); a foreign `Origin` (403); and a held flash released when the client disconnects.
- **Golden frames** (`tests/golden/phase6_frames.json`) are produced once at the checkpoints and reviewed by hand against these values.

### 5.20 Performance

**Expected cost.**
- The engine adds a page lookup, a takeover check and a held-button lookup per command: dictionary operations, nothing per tick.
- The snapshot gains a page and two floats per speed master.
- The new threads sleep in `recvfrom`, `accept`, condition waits and 30 Hz timers. Their bursts are small next to an edit's compile:
  - the feedback worker: a dictionary diff per cycle;
  - the broadcaster: one `json.dumps` per changed snapshot;
  - OSC and web readers: one message each.

**Benchmarks.**
- `test_perf.py` (`-m perf`) is re-run. Every Phase 5 gate must still pass.
- `test_perf.py` adds two gates:
  - an Art-Net output cycle for 64 universes: median < 5 ms, like sACN's;
  - `feedback_values` for 200 bindings on the reference rig: < 1 ms.
- `bench/surface_load.py` runs the engine at 100 Hz on the real clock for 20 s, on the demo rig and the reference rig, with:
  - a WebSocket client sending 60 `SET_FADER` per second and reading every state;
  - 100 MIDI events per second through `BindingResolver`;
  - an OSC client sending 60 messages per second;
  - the feedback worker at 30 Hz into a fake MIDI output.

  It reports overruns, tick p99, state messages per second and command latency (submit → applied). Targets: demo rig **0 overruns** (hard); reference rig under 1 % of ticks overrun (soft, recorded as an input for Phase 7's process split).

If the demo rig overruns, in order:
1. lower the broadcaster and feedback rates to 20 Hz;
2. coalesce `SET_FADER` per playback in the API reader (latest wins within a 10 ms window);
3. move JSON serialisation to the client writer threads.

---

## 6. Implementation steps

Each step follows TDD: write the listed tests first, then make them pass. Engine tests use a `FakeClock` and call `engine.tick(now)` directly. Network tests use localhost and ephemeral ports; no packet leaves the machine. **Every step ends with the whole suite green** (pytest, ruff check, ruff format --check, mypy). The steps are sized so that two fit in one working session, as in Phases 4–5. Steps 3–8 are engine work, 9–14 surfaces, 15 the done criterion, and 16–18 network output, which depends on nothing before it except step 2.

1. **Baseline.** Run `uv run pytest`, `uv run pytest -m perf -s` and `uv run python bench/edit_latency.py`, and record the numbers. → *verify:* green; the numbers are noted under step 19 for comparison.
2. **Schema and validation.**
   - Add every new type and field: `PageCmd`, `PlaybackButtonCmd`, `SET_FADER` by slot, `BLACKOUT` toggle, `CommandOrigin.control`, `Playback.gotoCue`, `BlackoutAction.momentary`, `SurfaceMatch.feedbackPort`, `midiClock`. Classes for the new commands.
   - Add the §5.18 rules.

   → *verify:*
   - `test_schema.py`: 34 command types, every new optional field accepted, and old documents unchanged.
   - `test_validate.py`: each new error and warning, with its path.
   - Appendix A and the three Phase 3–5 goldens still validate with 0 errors and 0 warnings.
3. **Pages.** `CompiledPage`, `CompiledShow.pages` (`firstPage` goes), `PageState`, `PAGE`, `SET_FADER {slot}`, the snapshot's `page`, the status line, and the page in autosave and recovery. The resolver sends `SET_FADER {slot}` and `PAGE` for page actions. → *verify:*
   - `test_pages.py`:
     - number and delta, stopping at the ends;
     - an empty or out-of-range slot;
     - a page change leaving a running playback and its fader untouched;
     - a live edit that renames, renumbers or deletes the current page;
     - PAGE then SET_FADER in one tick resolving on the new page.
   - Updated: `test_bus.py`; `test_bindings.py` (the first-page fader test becomes a slot test; page actions); `test_compile_cues.py` and `test_compile_incremental.py` (`firstPage` → `pages`); `test_live_swap.py`; `test_cli.py` (status line); `test_autosave.py` and `test_recovery.py` (the page comes back); `test_limitations.py` (the page lines go).
4. **Playback buttons.** `PLAYBACK_BUTTON` in the engine, `HeldButtons`, `goto` buttons (`CompiledPlayback.gotoCue`) and latching `BLACKOUT`. The resolver sends `PLAYBACK_BUTTON` with the control, and `SELECT_PLAYBACK` for `select`. → *verify:*
   - `test_buttons.py`:
     - every function down and up;
     - a flash held across a page change released on its own playback;
     - `goto` with and without `gotoCue`, on an idle and an active playback;
     - the blackout toggle from two sources.
   - `test_bindings.py`: buttons send `PLAYBACK_BUTTON` with the control; `select` uses the snapshot's page; a blackout binding latches and `momentary` holds.
   - `test_live_swap.py`: editing `gotoCue`.
   - Updated and listed in the step's commit message: the `test_bindings.py` tests that expected `GO`, `FLASH` and the rest from button bindings, the momentary blackout test, and the `goto` line in `test_limitations.py`.
5. **Swop.** `Playbacks.swopping`, suppression in `update`, `PlaybackStatus.swop`. → *verify:* `test_swop.py`:
   - only the swopped playback's and protected playbacks' intensity remain;
   - an override band does not hold the swopped one at 0;
   - LTP untouched;
   - effects' intensity suppressed;
   - two swops held;
   - the exact frame back on release.

   `test_limitations.py`: the swop line goes.
6. **Soft takeover.** `Pickup`, `CompiledShow.softControls`, origins reaching `_apply`, and the resolver adding `control`. → *verify:* `test_pickup.py`:
   - attach by crossing, by tolerance, and on the first message;
   - ignore while detached;
   - detach on a console or phone move;
   - re-attach after a page change only by crossing;
   - masters;
   - `jump` surfaces;
   - a live switch from `jump` to `soft`;
   - (hypothesis) over random interleavings of soft and jump moves, every applied soft move while detached satisfies the crossing-or-tolerance rule, and an attached control's level always equals its last value.

   `test_limitations.py`: the soft pickup line goes.
7. **Fade-time masters.** `fade_override`, the shared holder, `_timing`, `_effect_timing`, releases, the bus, initial level 0, status line, recovery. → *verify:* `test_fade_time.py`:
   - GO, GOTO, an auto-GO, a release and an exclusivity release under the override;
   - per-family timing and delays replaced;
   - effects entering over it, with `sizeFadeIn` kept;
   - an explicit release time winning;
   - chases, flashes, the programmer and live edits unaffected;
   - running fades unchanged when the level moves;
   - the largest of two masters;
   - level 0 meaning programmed times.

   Updated: `test_bus.py` and `test_bindings.py` (fade-time accepted), `test_limitations.py` (the `UNASSIGNED` constant goes), `test_cli.py`, `test_recovery.py` (a fade-time level comes back).
8. **Crossfade faders.** `Manual`, `crossRest`, the virtual clock for slots and effect presences, `EffectBank.hold`, materialising on interruptions, `PlaybackStatus.progress`. → *verify:* `test_crossfade.py`:
   - A/B rest ends;
   - progress per fader position, with delays and per-family times kept proportional;
   - a cue with 0 s timing crossfading linearly;
   - no reversal;
   - completion at the far end;
   - idle with and without `autoStart`;
   - the end of a list with and without wrap;
   - `GO` and a release mid-transition: no jump, then the fader waits for an end;
   - a live edit mid-transition;
   - effects entering by hand;
   - triggers ignored;
   - schedule independence.

   `test_limitations.py`: the crossfade line goes.
9. **MIDI clock, MIDI output and the surface manager.** Clock beats in `translate`; `MidiOutput`; `io/surfaces.py` with MIDI only, replacing `cli.MidiPorts`. → *verify:*
   - `test_midi.py`:
     - 24 clocks per press, Start and Song Position;
     - output encoding per address kind;
     - (marker `midi`) a virtual ALSA port pair round-trips a CC and a clock;
     - the mido timing-message check.
   - `test_surface_manager.py`: open, change and close on reconcile; a missing device reported once.
   - `test_cli.py` updated for the manager.
10. **Feedback.** `feedback_values`, `FeedbackWorker`, echo hold, beat LEDs; `SpeedStatus` anchors and `EngineSnapshot.time`. → *verify:* `test_feedback.py`:
    - every row of the §5.10 table, per kind;
    - page changes moving every page-relative value;
    - diffs only, and a full send on (re)open;
    - the echo hold for motor faders only;
    - the beat LED against the anchor across a tap;
    - a failing sender reported once.

    Also: `test_engine_busking.py` (the anchors change only at taps and tempo changes, and a running master publishes no snapshots); `test_limitations.py` (feedback lines go; MIDI display stays).
11. **OSC.** The codec, `OscSurface`, the manager's OSC branch, OSC feedback. → *verify:* `test_osc.py`:
    - golden encodings from the OSC 1.0 specification's examples;
    - every type tag, bundles inside bundles, malformed packets dropped;
    - value mapping (decision 14);
    - a localhost round trip: a message → a binding → a command on the bus;
    - feedback to `host:feedbackPort` and to the sender's address.

    `test_limitations.py`: OSC surface and input lines go.
12. **WebSocket server.** `web/websocket.py`, `web/server.py` (the static page can be a placeholder), the key file, origin check. → *verify:* `test_websocket.py`:
    - the RFC 6455 §1.3 accept-key example;
    - handshake errors (missing headers, wrong version);
    - masked frames of 0, 125, 126 and 65 536 bytes, and fragmented messages;
    - ping/pong; close codes 1002, 1003, 1007 and 1009;
    - the first frame arriving in the same packet as the headers;
    - a wrong key and a foreign origin rejected;
    - a stalled client closed without blocking another.
13. **The web API and the phone page.** `web/api.py`, the broadcaster, `index.html`, the manager's web branch. → *verify:* `test_web_api.py`:
    - hello, show and state contents;
    - states capped at 30 Hz under a burst of changes;
    - a show message after a live edit;
    - performance commands submitted with the origin;
    - programmer and show commands rejected;
    - a bad JSON message answered with an error;
    - held buttons released on disconnect.

    Also: the page served only with the key and with no `http` or `https` URL in it, and every command type the page can send accepted by the bus (a list kept next to the page and tested).

    `test_limitations.py`: web surface lines go.
14. **Console and CLI.** The §5.17 grammar, `record slot [P.]S`, the lists, the status line; `busk run` wiring: the manager, feedback thread, URL lines, shutdown order, and `Ignored in Phase 6:`. → *verify:*
    - `test_console_parser.py`: at least one case per §5.17 row, plus errors (`no page 3`, `slot 9 is in use on page 2`, `expected led, motor or display`, `surface add osc` on a taken port).
    - `test_console.py`: `list pages` with the current page marked; `list bindings` with names and feedback.
    - `test_cli.py`: start-up lines with a fake manager, and the limitation block.
    - `test_limitations.py`: the full Phase 6 list.
15. **Done criterion.** Write `examples/phase6-surfaces.busk`, `test_surfaces_show.py`, `tests/ws_client.py` and the goldens. → *verify:* `test_surfaces_show.py` checks that:
    1. every line of the four scripts succeeds;
    2. the saved show equals `tests/golden/phase6_surfaces_show.json`, and `busk validate` reports 0 errors and 0 warnings;
    3. every §5.19 checkpoint matches its hand-computed logical values, golden bytes, LED values and phone state;
    4. the 100 Hz and irregular-schedule runs give byte-identical frames;
    5. save → load → a fresh engine gives the same frames;
    6. the network test of §5.19 passes.
16. **Art-Net output.** `art_dmx`, `ArtNetSender`, `SendPolicy` parameters, sequences, `netif`, the scheduler opening Art-Net routes. → *verify:*
    - `test_artnet.py`:
      - ArtDmx golden bytes per Port-Address;
      - sequence wrap 255 → 1, shared between routes;
      - send on change and every second;
      - unicast to a localhost receiver;
      - `broadcast_address` of a mocked `ioctl`, and the non-Linux error.
    - Updated: `test_output_scheduler.py` (Art-Net no longer ignored) and `test_sacn_policy.py` (the policy's defaults unchanged).
17. **Discovery.** `ArtNetNetwork` (ArtPoll, replies, nodes, unicast to nodes, ArtPollReply to others) and sACN universe discovery. → *verify:*
    - `test_artnet_discovery.py`, with a fake node on localhost:
      - an ArtPollReply puts the node in the table, and its routes go unicast;
      - expiry returns them to broadcast;
      - our ArtPollReply's golden bytes answer an ArtPoll;
      - a taken port 6454 turns discovery off with a notice.
    - `test_sacn.py`:
      - discovery golden bytes for 1 and 600 universes (two pages);
      - the 10 s interval;
      - only enabled sACN routes' universes listed.
18. **DMX-USB.** `enttec_message`, `EnttecSender`, reopening, the scheduler, `route add … dmxusb`. → *verify:* `test_dmxusb.py` on a pseudo-terminal:
    - label 4 then label 6 golden bytes;
    - send on change and every second;
    - a partial write completed or dropped;
    - an unplug (master side closed) marking the route failed;
    - a replug (the symlink re-pointed) sending again with the parameters;
    - `enttecOpen` noticed as ignored;
    - the console grammar.
19. **Benchmarks** (§5.20). → *verify:* the gates pass, and the numbers are recorded here, next to step 1's baseline.

    **Step 1 baseline** (2026-10-13; 2056 passed, 1 skipped, 8 perf deselected; ruff, format and mypy clean):
    - Appendix A busking tick: 0.077 ms mean, 0.121 ms p99.
    - Reference rig, 60 playbacks: 1.904 ms mean, 2.128 ms p99; resolve alone 0.738 ms mean.
    - 20 effects over 60 looks: 3.588 ms mean, 4.016 ms p99.
    - 60 transitions: 3.157 ms mean, 3.656 ms p99.
    - 60-GO burst: 17.131 ms mean; ticks between bursts 3.360 ms mean.
    - 8 chases: 3.969 ms mean on step ticks, 2.184 ms on other ticks.
    - Output: 64 sACN routes, 0.073 ms median per cycle; convert 0.292 ms median.
    - Edit latency: demo rig 0 overruns in 759 ticks, p95 6.9 ms; reference rig 162 overruns in 1595 ticks, p95 134.5 ms.

    **Step 19 results** (2026-10-14; 2712 passed, 1 skipped, 10 perf deselected; ruff, format and mypy clean). Every Phase 5 gate still passes:
    - Appendix A busking tick: 0.078 ms mean, 0.110 ms p99.
    - Reference rig, 60 playbacks: 1.999 ms mean, 2.495 ms p99; resolve alone 0.749 ms mean.
    - 20 effects over 60 looks: 3.795 ms mean, 4.719 ms p99.
    - 60 transitions: 3.280 ms mean, 4.301 ms p99.
    - 60-GO burst: 17.557 ms mean; ticks between bursts 3.465 ms mean.
    - 8 chases: 4.136 ms mean on step ticks, 2.303 ms on other ticks.
    - Engine ticks are 3–6 % slower than the baseline (the page, beat and takeover state per tick).
    - Output: 64 sACN routes, 0.065 ms median per cycle; convert 0.297 ms median.
    - Edit latency: demo rig 0 overruns in 794 ticks, p95 9.1 ms; reference rig 166 overruns in 1609 ticks, p95 134.5 ms.

    The two new gates:
    - **Art-Net**, 64 routes, every universe changed every cycle: 0.066 ms median per cycle (gate 5 ms).
    - **`feedback_values`**, 200 bindings on the reference rig: 0.054 ms mean, 0.063 ms p99 (gate 1 ms).

    `bench/surface_load.py` (20 s per rig; phone 60 `SET_FADER`/s, 100 MIDI events/s, 60 OSC messages/s, feedback at 30 Hz, a probe at 10/s):

    | Rig | Overruns | Tick p99 / max | States/s | Phone round trip p50 / p95 | Command latency p50 / p95 | Feedback |
    |---|---|---|---|---|---|---|
    | demo (18 playbacks, 59 bindings) | **0 in 2000** (hard target met) | 2.62 / 5.32 ms | 29.5 | 24.2 / 40.4 ms | 5.0 / 5.8 ms | 5 msg/s |
    | reference (61 playbacks, 208 bindings) | **56 in 1990, 2.8 %** (soft target 1 %: missed) | 12.21 / 20.26 ms | 29.6 | 27.6 / 44.0 ms | 10.4 / 15.1 ms | 102 msg/s |

    - **For Phase 7's process split.** Turning load sources off one at a time (10 s runs) shows that the reference rig's overruns come with the MIDI and OSC fader moves. Those moves start all 61 playbacks; without them, only the 5 that the phone and the probe move are running. Without MIDI and OSC: 0 overruns, p99 6.9 ms. With no generators at all (the phone connected and reading): 0 overruns, p99 2.95 ms. Without the phone's sends: 2.5 %; without the probe: 3.0 %. So the cost is the whole rig running under surface load: the engine's tick plus the GIL shared with the input, broadcaster and feedback threads. The bench's phone client and probe also run in-process, which a real phone does not.
    - **The 50 ms phone round trip** in the first runs was Nagle's algorithm on the bench's client, which waited for delayed ACKs. Browsers send WebSocket frames with `TCP_NODELAY`, so the bench client now does too. The web server now sets it as well (`disable_nagle_algorithm`), so a state frame never waits for the ACK of the previous one.
20. **Manual demo on the rig.** Follow the §8 checklist with the nanoKONTROL2, a phone on the same network and the Phase 3 rig. Where hardware is available, also check an Art-Net node and an Enttec or DMXking interface. → *verify by eye:*
    - the phone and the controller drive the show together;
    - soft faders never jump;
    - the LEDs follow;
    - the run ends with 0 overruns.
21. **README and full verification.** Add a "Surfaces checklist (Phase 6)", the decisions taken beyond the plan, the spec gaps and the benchmark numbers. Update "Next" and the `pyproject` description. → *verify:* §8.

---

## 7. Acceptance tests (summary)

| Test file | Proves |
|---|---|
| `test_schema.py` · `test_validate.py` (extended) | The new commands and fields; every surface, binding, feedback and goto rule |
| `test_pages.py` | The engine's current page, page-relative faders, live edits of pages |
| `test_buttons.py` | Every button function through the engine; held flashes across pages; goto; latching blackout |
| `test_swop.py` | Swop suppression by presence; non-destructive |
| `test_pickup.py` | Soft takeover: attach, detach, crossing, pages, masters (with a hypothesis invariant) |
| `test_fade_time.py` | Fade-time masters: what they replace and what they leave alone |
| `test_crossfade.py` | Manual crossfades: rest ends, progress, interruptions, effects, determinism |
| `test_bindings.py` · `test_midi.py` (extended) | Bindings send page-relative commands with their control; MIDI clock; MIDI output |
| `test_feedback.py` | Feedback values per action and kind; diffs, echo hold, beat LEDs |
| `test_osc.py` | The OSC codec, input and feedback over localhost |
| `test_websocket.py` · `test_web_api.py` | The WebSocket subset, the key and origin checks, the JSON protocol, throttling, slow clients |
| `test_surface_manager.py` | Surfaces open, change and close with live edits |
| `test_artnet.py` · `test_artnet_discovery.py` | ArtDmx, keep-alive, sequences, ArtPoll discovery and unicast, ArtPollReply |
| `test_sacn.py` (extended) | Universe discovery packets and timing |
| `test_dmxusb.py` | The Enttec protocol, writes, unplug and replug on a pseudo-terminal |
| `test_bus.py` · `test_limitations.py` · `test_cli.py` · `test_console_parser.py` · `test_console.py` · `test_autosave.py` · `test_recovery.py` · `test_engine_busking.py` · `test_live_swap.py` · `test_output_scheduler.py` (extended) | The bus, the shorter limitation list, the CLI, the console grammar, the page across a crash, snapshots |
| `test_golden_7_8.py` · `test_song_stack.py` · `test_effects_show.py` (unchanged) | The §7.8 example, the Phase 4 song and the Phase 5 effects still hold |
| `test_surfaces_show.py` | The done criterion |
| `test_perf.py` (`-m perf`, extended) · `bench/surface_load.py` | Ticks under surface load; Art-Net output and feedback costs |

---

## 8. Verification

```bash
uv run pytest                                           # all green
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run pytest -m perf -s                                # gates pass; numbers recorded
uv run python bench/edit_latency.py                     # demo rig: 0 overruns, p95 ≤ 50 ms
uv run python bench/surface_load.py                     # demo rig: 0 overruns under surface load
uv run busk new /tmp/busk-demo/club.show --title "Club Night"
uv run busk run /tmp/busk-demo/club.show --script examples/phase3-build.busk --duration 1
uv run busk run /tmp/busk-demo/club.show --script examples/phase4-song.busk --duration 1
uv run busk run /tmp/busk-demo/club.show --script examples/phase5-effects.busk --duration 1
uv run busk run /tmp/busk-demo/club.show --script examples/phase6-surfaces.busk
#   Web s-…: http://<address>:8080/?k=…   → open it on a phone
#   busk> list pages                 → * 1 Main …, 2 Washes …
#   busk> page 2                     → the phone shows "Washes"
#   busk> status                     → "… | P2 Washes | …"
#   busk> quit
uv run busk validate /tmp/busk-demo/club.show           # → 0 errors, 0 warnings
```

**Surfaces checklist (Phase 6)**, for step 20. It needs the Phase 3 setup (nanoKONTROL2, sACN rig, `--iface`), a phone on the same network, and the nanoKONTROL2's LED mode set to **External** with the KORG KONTROL Editor (in the factory Internal mode the buttons light only while pressed):

1. Run the four scripts. There is no `Ignored in Phase 6:` block. Open the printed URL on the phone: page 1 "Main" with its strips.
2. Fader 1 from the bottom to the top: Warm comes up. S1 and R1 light.
3. Marker ▶: the phone shows "Washes" and the S1 LED goes out. Move fader 1 down a little: nothing happens. Pull it to the bottom and up again: Wash Blue rises from 0, without a jump.
4. On the phone, drag Wash Blue to about a third. Move fader 1: nothing until it passes the phone's level, then it follows.
5. Hold M2: only the red washes are lit, and M2 lights. Release it: everything as before.
6. Fader 8 up slowly: the bar crossfades into blue as you move. Down slowly: into red. Stop halfway: the bar holds there.
7. ■: blackout stays on and the stop LED lights. ■ again: back.
8. Marker ◀ to page 1. On the phone, raise "Fade" to the middle and tap the song's `GOTO 4 Chorus`: the Chorus fades in over about 2.5 s while Warm fades out.
9. Cycle LED: it flashes on the beat. Tap in time, or send MIDI clock from a DAW bound with `bind "<surface>" clock tap`: it follows.
10. Close the phone's browser while holding a FLASH on it: the flash goes off.
11. With hardware at hand: an Art-Net node shows up (`Art-Net: node …`), and its universe lights; an Enttec or DMXking interface outputs, and pulling and replugging its cable resumes output within a second.
12. The run ends with 0 overruns.

---

## 9. Spec deviations and gaps

**Deliberate deviations**

- **The engine resolves page-relative input** (decisions 1–2). Bindings send `SET_FADER {slot}` and `PLAYBACK_BUTTON {slot}` rather than resolving pages before the bus, as §4.1 draws. There is one global page.
- **Soft takeover and held buttons are engine state** (decisions 5–6), keyed by `CommandOrigin.control`, a new origin field.
- **New commands:** `PAGE` (§15.2 names it without fields), `PLAYBACK_BUTTON`; `SET_FADER` by slot; `BLACKOUT` without `on` toggles.
- **Swop removes intensity presence** instead of setting `intensityScale = 0` (decision 9), because of §7.4's note on override bands.
- **Crossfade faders** never reverse, and alternate rest ends (decision 11). §8.2 says only "fader position drives `manualProgress`".
- **Remotes get show summaries, not JSON patches** (§16 "snapshots + patches"): a summary is small and always consistent. Patches can come with collaborative editing.
- **The web API takes performance commands only** (§23's single writer). The console package's docs expected the API to expose `Session.submit` whole.
- **Art-Net broadcast routes unicast to discovered nodes** (§14.3 "prefer unicast"), falling back to broadcast.
- **DMX-USB sends all 512 slots** and leaves the frame rate to the widget (`refreshHz` sets it). §14.2's "fewer slots" is not done.
- **Schema additions** (optional): `Playback.gotoCue`, `BlackoutAction.momentary`, `SurfaceMatch.feedbackPort`, the `midiClock` input.

**Gaps decided here (to fold back into the spec)**

- **Pages:** who owns the page; `delta` stops at the ends; the page after a live edit deletes it; the page persisted with the session.
- **The §8.1 button table** as engine behaviour; `goto` buttons' target; held flashes across page changes; latching vs momentary blackout.
- **Soft takeover's rule:** crossing or 0.02, detached by any other source, for faders and masters.
- **Feedback values** per action and kind, the echo hold, beat LEDs.
- **`SurfaceMatch` per kind:** `deviceName` for MIDI; `port`, `host` and `feedbackPort` for OSC; `port` and `host` (bind address) for web.
- **OSC values:** the first argument, clamped; `T`/`F`; argument-less messages as a press and release.
- **External tempo:** MIDI clock as one tap per beat.
- **Fade-time masters:** replace times while up, `10 s × level²`, the largest master, which transitions they cover, initial level 0.
- **Art-Net** sequence and keep-alive; **sACN discovery** interfaces and timing; the Enttec parameters.

**Still open after Phase 6**

- **Pages per surface:** two controllers on different pages. The engine would keep a page per surface, and `PAGE` would gain a surface.
- **The blind preview resolve**, a programming UI on the web API (programmer and show edits, multi-user rules, §23) and a template editor.
- **HID and `internal` surfaces, `hw` inputs;** display feedback on MIDI surfaces (device-specific sysex); feedback for `command` actions.
- **Ableton Link.** MIDI clock covers external sync for now.
- **Reversing a manual crossfade,** and several goto cues per playback.
- **OSC address patterns;** TLS and rate limits for the web API. A client can still flood the bus; Phase 7's process split is the place to bound it.
- **ArtSync and sACN synchronisation;** `enttecOpen`; DMX-USB sending fewer slots; sACN discovery for unicast-only shows.
- **Reconnect** for every route and for MIDI devices (hot-plug); this phase only covers DMX-USB.
- **Interface lookups** (`netif`) are Linux-only, like multicast by interface name.
- The open items of Phases 2–5 (README "Spec gaps"), including the GO-burst and edit-overrun misses.

---

## 10. What Phase 7 changes

- **Hardening** (§22 Phase 7):
  - the process split: engine and output in one process, UI, surfaces and the web API in another, talking over the API this phase defines;
  - the watchdog; park, limits and the strobe-rate cap (which should also bound fast intensity effects);
  - 24 h soak tests with surfaces connected and fuzzed;
  - GDTF/OFL import.
- **From this phase:**
  - reconnect for every route and for MIDI devices;
  - rate limits on remote commands;
  - `holdLastFrameOnEngineStall: false`;
  - whether the surface-load numbers (§5.20) and the edit overruns are solved by the process split.
- **To decide:**
  - pages per surface;
  - whether a programming UI (the blind preview resolve, programmer and show edits over the API, a template editor) is a Phase 7 item or a phase of its own. §22 does not schedule one.
