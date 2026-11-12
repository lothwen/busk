"""The TUI's own view of the engine: frozen view models, the events the
bridge sends, and :class:`BridgeLike`, what the UI calls.

Nothing here imports busk or Textual. The bridge (:mod:`busk_tui.bridge`)
turns busk's objects into these, keyed by the numbers and names the operator
types, never by ids, and the pages and widgets see only these. Tests swap in
a fake bridge that implements :class:`BridgeLike` (``tests/tui/tui_fakes.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

type Origin = Literal["typed", "ui", "internal"]
"""Who sent a line: typed at the prompt (echoed ``busk>``), run by a control
of the UI (echoed ``ui>``), or sent by the TUI itself (not echoed)."""

type EngineState = Literal["starting", "running", "stalled", "restarting", "failed", "stopped"]
"""What the engine does (busk's ``EngineHealth.state``)."""

type RouteState = Literal["ok", "failed", "disabled", "ignored"]

type SurfaceState = Literal["ok", "failed", "ignored"]

type Source = Literal["park", "programmer", "playback", "effect", "none"]
"""What drives a family of a fixture element's attributes (busk's
``FixtureOutput.source``)."""

type Rgb = tuple[float, float, float]
"""A colour, each component 0..1 (busk's linear RGB)."""


class ShowLoadFailed(Exception):
    """The show file of ``--standalone`` does not load; ``messages`` say why,
    one line each."""

    def __init__(self, messages: list[str]) -> None:
        super().__init__("\n".join(messages))
        self.messages = messages


# ----------------------------------------------------------------- answers


@dataclass(frozen=True, slots=True)
class Completion:
    """What may come where the word being typed starts (busk's ``Expected``).

    ``words`` replace ``line[start:]`` on Tab; ``values`` describe anything
    else (``a fixture number``); ``runnable``: the line before ``start`` is a
    whole command; ``error``: the mistake that stops it."""

    words: tuple[str, ...] = ()
    values: tuple[str, ...] = ()
    runnable: bool = False
    error: str | None = None
    start: int = 0


@dataclass(frozen=True, slots=True)
class Busy:
    """The ordered worker's line running now, since ``since`` (monotonic s)."""

    line: str
    since: float


# ------------------------------------------------------------- view models


type Components = tuple[tuple[str, float], ...]
"""A colour value's components, in busk's order: ``r``, ``g``, ``b``, then
``w``, ``a`` and ``uv`` when it has them."""

type Value = float | str | Components
"""A value as busk stores it: a number (intensity 0..1, degrees, Hz …), a
discrete value's slot (``breakup``), or a colour's components."""


@dataclass(frozen=True, slots=True)
class PageView:
    number: int
    name: str


@dataclass(frozen=True, slots=True)
class SpeedView:
    """A speed master's tempo. Its beat count comes in :class:`Beat` events."""

    name: str
    bpm: float
    multiplier: float
    level: float


@dataclass(frozen=True, slots=True)
class MasterLevel:
    name: str
    kind: str  # grand, group, size, speed, fadeTime
    level: float


@dataclass(frozen=True, slots=True)
class PlaybackView:
    """One playback as it runs (busk's ``PlaybackStatus``)."""

    number: int
    name: str
    state: str  # idle, active, releasing
    level: float  # the fader's level; ``fader`` says what it means
    flash: bool  # a flash is held on it
    fader: str  # master, crossfade, rate, size, temp, none
    chase: bool
    cue: str | None  # the current cue's number (a chase's step); None while idle
    cueName: str | None
    next: str | None  # the cue GO goes to
    cueCount: int
    progress: float | None  # a crossfade fader's transition, 0..1
    color: Rgb | None  # the current cue's colour


@dataclass(frozen=True, slots=True)
class LiveState:
    """The engine's published state (busk's ``EngineSnapshot``)."""

    seq: int
    gm: float
    blackout: bool
    outputEnabled: bool
    page: PageView | None
    fadeTime: float | None  # the fade-time master's override, seconds
    masters: tuple[MasterLevel, ...]
    speed: tuple[SpeedView, ...]
    playbacks: tuple[PlaybackView, ...]

    def playback(self, number: int) -> PlaybackView | None:
        return next((view for view in self.playbacks if view.number == number), None)


@dataclass(frozen=True, slots=True)
class GroupInfo:
    number: int
    name: str
    members: tuple[tuple[int, int], ...] = ()  # (fixture number, element) pairs, in order


@dataclass(frozen=True, slots=True)
class Targets:
    """What a stored value or an effect applies to: a group (a live
    reference, which follows the group's edits), or fixed elements."""

    group: GroupInfo | None = None
    elements: tuple[tuple[int, int], ...] = ()  # (fixture number, element) pairs, in order


@dataclass(frozen=True, slots=True)
class ChaseRate:
    """A chase's or an effect's rate and direction, to fill the form that edits
    them."""

    hz: float | None  # its rate in Hz; None: a speed master's beat
    master: str | None  # that master's name, when the show has several
    multiplier: float
    direction: str  # forward, reverse, bounce, random


@dataclass(frozen=True, slots=True)
class EffectInfo:
    """An effect instance as the show or the programmer holds it: a cue's
    and the programmer's are made alike, with the settings ``effect add``
    takes, in its words."""

    id: str
    template: str  # the template's name
    targets: Targets = Targets()
    rate: str = ""  # "bpm x 1", "hz 0.25", 'bpm "Speed 2" x 2' (a master by name with several)
    direction: str = "forward"  # forward, reverse, bounce
    size: float = 1.0
    low: Value | None = None  # an absolute layer's levels, when the instance has them
    high: Value | None = None
    phase: tuple[float, float] = (0.0, 0.0)  # start, end, in degrees
    groups: int = 1
    blocks: int = 1
    wings: int = 1
    pace: ChaseRate = ChaseRate(1.0, None, 1.0, "forward")  # ``rate``, one value at a time
    fadeIn: float | None = None  # the seconds its size takes to come in
    sizeMaster: str | None = None  # a size master's name
    speedMaster: str | None = None  # a speed master's name


@dataclass(frozen=True, slots=True)
class HeldValue:
    """One value of the programmer (busk's ``ProgrammerValue``): what it gives
    one attribute of one fixture element. A preset reference has the value
    the preset gives this element, and ``preset`` names it."""

    number: int
    element: int  # counted from 1
    attribute: str
    value: Value
    preset: str | None  # the preset's name, for a preset reference
    ref: tuple[str, int] | None = None  # the preset's pool and number, for a preset reference


@dataclass(frozen=True, slots=True)
class ProgrammerModel:
    """The programmer (busk's ``ProgrammerStatus``), and the options the
    selection offers for each discrete attribute the rig takes (read from
    busk's completion of ``set <attribute> ``)."""

    version: int
    selection: tuple[tuple[int, int], ...]  # (fixture number, element) pairs, in order
    blind: bool
    highlight: bool
    fadeTime: float
    fixtures: int  # the fixtures that hold a value
    effects: tuple[EffectInfo, ...]  # in the order they were added
    stopped: frozenset[str]  # the ids of the stopped effects
    values: tuple[HeldValue, ...] = ()  # in the order the programmer holds them
    options: tuple[tuple[str, tuple[str, ...]], ...] = ()  # (attribute, options), registry order

    def recordable(self) -> bool:
        """Whether it has what a cue records: a value, or an effect that runs
        (busk does not record a stopped one)."""
        return bool(self.values) or any(e.id not in self.stopped for e in self.effects)

    def offered(self, attribute: str) -> tuple[str, ...]:
        """The options the selection offers for the discrete ``attribute``
        (``open``, ``breakup`` …); none when no selected element takes it."""
        return next((found for name, found in self.options if name == attribute), ())

    def held(self, number: int, element: int, attribute: str) -> HeldValue | None:
        """The value the programmer holds for one attribute of one element."""
        return next(
            (
                value
                for value in self.values
                if value.number == number
                and value.element == element
                and value.attribute == attribute
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class ElementOutput:
    """One fixture element as the engine outputs it (busk's ``FixtureOutput``),
    after the masters: what the fixture is asked to do."""

    number: int
    element: int  # counted from 1
    intensity: float
    color: Rgb | None  # at full intensity; None: no colour
    pan: float | None
    tilt: float | None
    zoom: float | None
    sources: tuple[tuple[str, Source], ...] = ()  # (family, what drives it), the families it has
    playback: int | None = None  # the playback whose cue or effect drives its intensity

    def source(self, family: str) -> Source | None:
        """What drives ``family``; ``None`` when the element has none of it."""
        return next((source for name, source in self.sources if name == family), None)


@dataclass(frozen=True, slots=True)
class OutputModel:
    """The engine's output at one tick (busk's ``OutputSnapshot``)."""

    seq: int
    fixtures: tuple[ElementOutput, ...]  # by fixture number, then element

    def element(self, number: int, element: int) -> ElementOutput | None:
        return next(
            (out for out in self.fixtures if out.number == number and out.element == element),
            None,
        )


@dataclass(frozen=True, slots=True)
class DmxModel:
    """What busk sends: the engine's newest frame (busk's ``DmxFrame``), 512
    bytes per universe, by universe number."""

    seq: int
    universes: tuple[tuple[int, bytes], ...]  # by number

    def universe(self, number: int) -> bytes | None:
        return next((values for found, values in self.universes if found == number), None)


@dataclass(frozen=True, slots=True)
class EffectView:
    """One running effect instance (busk's ``EffectStatus``): a playback's
    (``playback``, and ``cue``, the cue that holds it) or the programmer's
    (both ``None``)."""

    playback: int | None
    cue: str | None
    id: str
    presence: float  # 0..1: how far in it is
    size: float
    hz: float
    phase: float
    wave: tuple[float, ...]  # the next cycle, 0..1 at equal steps; () without a waveform
    colors: tuple[Rgb, ...]  # the same for its colour layer; () without one


@dataclass(frozen=True, slots=True)
class EffectsModel:
    """The effects running at one tick (busk's ``EffectSnapshot``)."""

    seq: int
    effects: tuple[EffectView, ...]


@dataclass(frozen=True, slots=True)
class RouteView:
    """One output route: from the show, with its status once the output runs.

    ``state`` is ``None`` while nothing runs the output (``--no-output``)."""

    protocol: str  # as the operator reads it: sACN, ArtNet, DMX-USB
    universe: int  # the show universe it sends
    enabled: bool
    state: RouteState | None
    detail: str
    packets: int
    address: str = ""  # as route add takes it: the sACN universe, 0.0.1, enttecPro
    destination: str = ""  # multicast eth0, unicast 10.0.0.50, a DMX-USB port
    errors: int = 0  # the sends that failed since it opened
    id: str = ""  # as list routes prints it: route <id> off, delete route <id>
    rate: float | None = None  # a DMX-USB route's refresh rate, as hz takes it


@dataclass(frozen=True, slots=True)
class SurfaceView:
    """One control surface: from the show, with its status once the
    surfaces are open.

    ``state`` is ``None`` while no surface is open (``--no-surfaces``)."""

    name: str
    kind: str  # midi, osc, web, hid, internal
    device: str  # how it is found, as surface add takes it: "nanoKONTROL2", port 8000
    pickup: str  # soft, jump
    state: SurfaceState | None
    detail: str
    urls: tuple[str, ...]  # an open web remote's addresses, with its key


@dataclass(frozen=True, slots=True)
class BindingInfo:
    """One binding, in the words of ``bind``: its surface, its input
    (``kind`` cc, note, osc, clock, bend, hw; ``channel``; ``number``, or an
    OSC path), what it drives (``what``: ``fader 1``, ``master gm``), its
    feedback, and the level it shows (``target``)."""

    surface: str
    kind: str
    channel: int | None
    number: str  # the CC or note number, the OSC path, a hardware control; "" for the others
    what: str
    feedback: str  # led, motor, display, with its address when not the input's; "" for none
    target: tuple[str, int | str] | None = None  # ("slot", 0), ("playback", 9), ("master", name)

    @property
    def input(self) -> str:
        """The input as ``bind`` and ``unbind`` take it (``cc 1 0``, ``osc
        "/1/fader1"``, ``clock``); a pitch bend and a hardware control, which
        no line binds, alike (``bend 1``, ``hw fader1``)."""
        if self.kind == "osc":
            return f'osc "{self.number}"'
        channel = [] if self.channel is None else [str(self.channel)]
        return " ".join([self.kind, *channel, *([self.number] if self.number else [])])


@dataclass(frozen=True, slots=True)
class UniverseView:
    number: int
    name: str


@dataclass(frozen=True, slots=True)
class MasterView:
    name: str
    kind: str  # grand, group, size, speed, fadeTime
    group: GroupInfo | None  # a group master's group
    steps: tuple[float, ...]  # a speed master's multiplier steps
    id: str = ""  # as a cue effect's sizeMasterId, speedMasterId and rate take it


@dataclass(frozen=True, slots=True)
class PageInfo:
    """A playback page: the playback number in each slot (``None``: empty)."""

    number: int
    name: str
    slots: tuple[int | None, ...]


@dataclass(frozen=True, slots=True)
class PlaybackInfo:
    number: int
    name: str
    cueList: int  # the number of the cue list it runs
    uiColor: Rgb | None  # its ``uiColor``, when it is one
    buttons: tuple[str, ...] = ()  # its own buttons' functions, in order
    gotoCue: str | None = None  # the cue its ``goto`` buttons go to
    priority: int = 50  # its band
    fader: str = "master"  # master, crossfade, rate, size, temp, none
    ltpFaderMode: str = "threshold"  # followFader, threshold, ignoreFader
    ltpThreshold: float = 0.02
    autoStart: bool = True
    autoRelease: bool = True
    flashLevel: float = 1.0
    flashLtp: bool = True  # a flash brings its LTP values too
    flashBoost: int | None = None  # added to its band while it flashes
    exclusivity: str | None = None
    protectFromSwop: bool = False
    releaseTime: float = 1.0
    uiColorText: str | None = None  # ``uiColor`` as the show stores it, whatever it is


@dataclass(frozen=True, slots=True)
class StoredValue:
    """One value entry of a cue, as the show stores it: a ``literal`` value,
    a ``preset`` reference, a ``spread`` from one value to another, or a
    value ``perTarget``."""

    attribute: str
    targets: Targets
    kind: str  # literal, preset, spread, perTarget
    value: Value | None = None  # a literal's value; a spread's first
    to: Value | None = None  # a spread's last
    preset: str | None = None  # a preset reference's name
    color: Rgb | None = None  # the colour it gives: a literal's, or a preset's single one


@dataclass(frozen=True, slots=True)
class FamilyTiming:
    """A family's own timing in a cue: ``cue L/C time position 4 delay 1``
    sets it whole, so a form that changes the fade keeps the curve."""

    family: str
    fade: float
    delay: float = 0.0
    curve: str | None = None  # in busk's words; None: the cue's


@dataclass(frozen=True, slots=True)
class CueInfo:
    number: str
    name: str
    effects: tuple[EffectInfo, ...]
    fadeIn: float = 0.0
    fadeOut: float = 0.0
    delayIn: float = 0.0
    delayOut: float = 0.0
    curve: str = "linear"  # in busk's words: easeInOut, bezier 0.25 0.1 0.25 1
    families: tuple[FamilyTiming, ...] = ()  # the families with a timing of their own
    trigger: str = "go"  # go, follow, wait
    delay: float = 0.0  # a follow's or a wait's delay
    values: tuple[StoredValue, ...] = ()  # its value entries, in the order stored


@dataclass(frozen=True, slots=True)
class CueListInfo:
    number: int
    name: str
    mode: str  # sequence, chase
    chase: str | None  # a chase's rate and direction, in busk's words: "bpm x 1 bounce"
    cues: tuple[CueInfo, ...]  # in cue order
    crossfade: float = 0.0  # a chase's crossfade, when it has chase settings
    tracking: bool = False
    rate: ChaseRate | None = None  # the same settings as ``chase``, one by one


type Layer = Mapping[str, Any]
"""An effect layer as the show stores it, which is what ``effect template
update`` takes back: the TUI keeps what it does not edit (a colour's extra
emitters) by not reading it into fields of its own."""


@dataclass(frozen=True, slots=True)
class TemplateInfo:
    """An effect template ``effect add "<name>"`` takes (busk's
    ``EffectTemplateInfo``): the show's, or the library's that the show has
    no copy of, with the defaults the library gives an instance."""

    name: str
    source: str  # show, library
    summary: str  # its layers in one line, as busk words them
    size: float | None = None
    low: float | None = None
    high: float | None = None
    phase: tuple[float, float] | None = None
    id: str = ""  # stays through a rename
    layers: tuple[Layer, ...] = field(default=(), hash=False)  # the show's only
    used_by: tuple[tuple[int, str], ...] = ()  # the cues that hold an effect of it: (list, cue)
    bindings: int = 0  # how many bindings add an effect of it


type Summary = float | str | None
"""What a preset gives one attribute where all its values of it agree: a
number, or a discrete value's slot; ``None`` where they differ (mixed)."""


@dataclass(frozen=True, slots=True)
class PresetEntry:
    """One value a preset stores (busk's ``PresetValue``): its scope
    (``global``, ``profile`` or ``target``), where that is (``None`` for
    ``global``, the profile's name, or a ``(fixture number, element)`` pair),
    the attribute, and the value."""

    scope: str
    where: str | tuple[int, int] | None
    attribute: str
    value: Value


@dataclass(frozen=True, slots=True)
class PresetInfo:
    pool: str
    number: int
    name: str
    color: Rgb | None  # the colour it gives, when it gives one colour everywhere
    values: tuple[tuple[str, Summary], ...] = ()  # its other attributes, in the order stored
    entries: tuple[PresetEntry, ...] = ()  # what it stores, in the order stored
    used_by: tuple[tuple[int, str], ...] = ()  # the cues that take it: (list, cue), in that order
    palettes: tuple[str, ...] = ()  # the effect templates whose colour palette takes it
    id: str = ""  # as a colour palette takes it


type Location = tuple[float, float, float, float, float, float]
"""A fixture's place on stage: x, y, z in metres, rx, ry, rz in degrees."""


@dataclass(frozen=True, slots=True)
class Limits:
    """What a fixture's limits allow (``None``: no such limit): pan and tilt
    from low to high, in degrees, and the highest intensity, 0..1."""

    pan: tuple[float, float] | None = None
    tilt: tuple[float, float] | None = None
    intensity: float | None = None


@dataclass(frozen=True, slots=True)
class Orientation:
    """How a fixture hangs, under busk's own keys (``orientation.invertPan``)."""

    invertPan: bool = False
    invertTilt: bool = False
    swapPanTilt: bool = False
    panOffset: float = 0.0
    tiltOffset: float = 0.0


@dataclass(frozen=True, slots=True)
class Parked:
    """A value park holds on one attribute of one fixture element (an entry of
    the show's ``park``)."""

    number: int  # the fixture's
    element: int  # counted from 1
    attribute: str
    value: Value


@dataclass(frozen=True, slots=True)
class FixtureInfo:
    number: int
    elements: int
    name: str = ""
    profile: str = ""  # its profile's name
    mode: str = ""  # its mode's name
    footprint: int = 1  # the DMX channels its mode takes
    patch: tuple[int, int] | None = None  # (universe number, start address); None: unpatched
    split: bool = False  # it has an element patch (busk does not run those yet)
    location: Location | None = None
    limits: Limits = Limits()
    orientation: Orientation = Orientation()
    channels: tuple[str, ...] = ()  # what each channel of its footprint does, by offset


@dataclass(frozen=True, slots=True)
class ModeInfo:
    """A profile's mode: its name, the DMX channels it takes, and how many
    elements it has."""

    name: str
    footprint: int
    elements: int


@dataclass(frozen=True, slots=True)
class ProfileChoice:
    """A profile ``fixture add`` takes (busk's ``FixtureProfileInfo``): the
    show's, or the library's that the show has no copy of."""

    name: str
    source: str  # show, library
    manufacturer: str
    modes: tuple[ModeInfo, ...]
    revision: str = ""  # the show's, for a profile the show holds
    library_revision: str | None = None  # the library's; None: the library has no such profile

    def outdated(self) -> bool:
        """Whether ``profile update`` has something to do: the show's copy
        is at a revision the library's is not. A library profile's two
        revisions are both the library's."""
        return self.library_revision not in (None, self.revision)


@dataclass(frozen=True, slots=True)
class ProfileInfo:
    """A fixture profile: the attributes its modes take, as ``set`` names
    them (``intensity``, ``pan``, ``color``, ``color.w`` with a white
    emitter, ``strobeRate`` …), and the range of each that is not 0..1."""

    name: str
    attributes: frozenset[str]
    ranges: tuple[tuple[str, float, float], ...]  # (attribute, low, high)
    category: str | None = None  # par, spot, wash, pixel, strobe …; None: not set
    modes: tuple[ModeInfo, ...] = ()

    def range(self, attribute: str) -> tuple[float, float] | None:
        return next(((low, high) for name, low, high in self.ranges if name == attribute), None)


@dataclass(frozen=True, slots=True)
class ShowModel:
    """The parts of the show document the pages use."""

    title: str
    universes: tuple[UniverseView, ...]
    masters: tuple[MasterView, ...]
    pages: tuple[PageInfo, ...]
    playbacks: tuple[PlaybackInfo, ...]  # by number
    cueLists: tuple[CueListInfo, ...]
    groups: tuple[GroupInfo, ...]
    presets: tuple[PresetInfo, ...]
    fixtures: tuple[FixtureInfo, ...]
    profiles: tuple[ProfileInfo, ...] = ()
    templates: tuple[TemplateInfo, ...] = ()  # what effect add takes
    bindings: tuple[BindingInfo, ...] = ()  # in show order
    choices: tuple[ProfileChoice, ...] = ()  # what fixture add takes
    park: tuple[Parked, ...] = ()  # in show order
    strobeMaxHz: float | None = None  # the strobe cap (safety strobe); None: off

    def group(self, number: int) -> GroupInfo | None:
        return next((info for info in self.groups if info.number == number), None)

    def playback(self, number: int) -> PlaybackInfo | None:
        return next((info for info in self.playbacks if info.number == number), None)

    def cue_list(self, number: int) -> CueListInfo | None:
        return next((info for info in self.cueLists if info.number == number), None)

    def runs(self, cue_list: int) -> tuple[int, ...]:
        """The numbers of the playbacks that run the cue list ``cue_list``."""
        return tuple(info.number for info in self.playbacks if info.cueList == cue_list)

    def fixture(self, number: int) -> FixtureInfo | None:
        return next((info for info in self.fixtures if info.number == number), None)

    def profile(self, name: str) -> ProfileInfo | None:
        return next((info for info in self.profiles if info.name == name), None)


@dataclass(frozen=True, slots=True)
class SessionState:
    """Undo depth and unsaved edits, read from the text of ``info``: a
    temporary parser until GAP-03 gives them typed (question Q2)."""

    undo: int
    redo: int
    dirty: bool


# ------------------------------------------------------------------ events


@dataclass(frozen=True, slots=True)
class EngineStarting:
    pass


@dataclass(frozen=True, slots=True)
class EngineRunning:
    title: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EngineFailed:
    """``--standalone`` only: the show could not be built or started."""

    message: str


@dataclass(frozen=True, slots=True)
class EngineStopped:
    pass


@dataclass(frozen=True, slots=True)
class CommandDone:
    ticket: int
    line: str
    origin: Origin
    ok: bool
    lines: tuple[str, ...]  # the reply's text, line by line
    seconds: float
    quit: bool


@dataclass(frozen=True, slots=True)
class LiveChanged:
    state: LiveState


@dataclass(frozen=True, slots=True)
class Beat:
    """The engine time of the newest frame, and each speed master's beat
    count then, in the order of ``LiveState.speed``."""

    time: float
    beats: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class ShowChanged:
    show: ShowModel


@dataclass(frozen=True, slots=True)
class ProgrammerChanged:
    programmer: ProgrammerModel


@dataclass(frozen=True, slots=True)
class EffectsChanged:
    effects: EffectsModel


@dataclass(frozen=True, slots=True)
class OutputChanged:
    output: OutputModel


@dataclass(frozen=True, slots=True)
class DmxChanged:
    dmx: DmxModel


@dataclass(frozen=True, slots=True)
class RoutesChanged:
    routes: tuple[RouteView, ...]


@dataclass(frozen=True, slots=True)
class SurfacesChanged:
    surfaces: tuple[SurfaceView, ...]


@dataclass(frozen=True, slots=True)
class HealthChanged:
    state: EngineState
    late: bool  # the engine's overruns grew over the last second or more


@dataclass(frozen=True, slots=True)
class SessionChanged:
    session: SessionState


@dataclass(frozen=True, slots=True)
class EngineNews:
    """A record of the ``busk`` loggers, shown as it is."""

    level: Literal["info", "warning"]
    text: str


type BridgeEvent = (
    EngineStarting
    | EngineRunning
    | EngineFailed
    | EngineStopped
    | CommandDone
    | LiveChanged
    | Beat
    | ShowChanged
    | ProgrammerChanged
    | EffectsChanged
    | OutputChanged
    | DmxChanged
    | RoutesChanged
    | SurfacesChanged
    | HealthChanged
    | SessionChanged
    | EngineNews
)

STATE_EVENTS: tuple[type, ...] = (
    LiveChanged,
    Beat,
    ShowChanged,
    ProgrammerChanged,
    EffectsChanged,
    OutputChanged,
    DmxChanged,
    RoutesChanged,
    SurfacesChanged,
    HealthChanged,
    SessionChanged,
)
"""The events that carry a whole state: of each kind, only the newest of a
batch matters."""


def newest_only(events: list[BridgeEvent]) -> list[BridgeEvent]:
    """``events`` in order, with only the last of each kind of state event."""
    last = {type(event): index for index, event in enumerate(events)}
    return [
        event
        for index, event in enumerate(events)
        if not isinstance(event, STATE_EVENTS) or last[type(event)] == index
    ]


# ---------------------------------------------------------------- protocol


class BridgeLike(Protocol):
    """What the UI calls (the real :class:`~busk_tui.bridge.Bridge`, and the
    tests' fake). Every member is safe on the UI thread and returns at once."""

    def start(self) -> None: ...

    def stop(self, timeout: float = 5.0) -> None: ...

    def send(
        self, line: str, origin: Origin, key: str | None = None, performance: bool = False
    ) -> int: ...

    def confirmation(self, line: str) -> str | None: ...

    def expected(self, line: str) -> Completion: ...

    def watch(self, output: bool, effects: bool, dmx: bool = False) -> None: ...

    def drain(self) -> list[BridgeEvent]: ...

    @property
    def busy(self) -> Busy | None: ...

    @property
    def help_lines(self) -> tuple[str, ...]: ...
