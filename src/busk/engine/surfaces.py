"""Engine state that belongs to surfaces rather than playbacks (phase-6-plan §5.1).

Several surfaces (the MIDI controller, the phone, the console) act on the same
show at once. The state their input depends on lives here, on the engine
thread, so commands from every surface are resolved in queue order and the
result never depends on which input thread won a race (decision 2):

* :class:`PageState`: the current playback page, shared by every surface
  (decision 1). Page-relative commands (``SET_FADER {slot}`` and
  ``PLAYBACK_BUTTON {slot}``) resolve their slot through it;
* :class:`HeldButtons`: the flash and swop buttons held down through a
  slot, per control, so each release reaches the playback its press did
  (decision 3);
* :class:`Pickup`: soft takeover (§5.15, decision 6). A fader on a
  ``faderPickup: "soft"`` surface only takes over a level once it has met
  it, so a page change or a move from another surface never makes the
  output jump to wherever the hardware happens to sit.

A *control* is the binding a command came from (``CommandOrigin.control``,
decision 5); commands without one (the console, the phone, embedded
``command`` actions) are *jump sources*.
"""

from __future__ import annotations

from typing import Final, Literal

from busk.compiler.playbacks import CompiledPage
from busk.model.common import PlaybackId
from busk.model.playback import ButtonFunction


class PageState:
    """The current playback page (engine thread).

    The pages are the compiled show's, in number order. At start the current
    page is the lowest-numbered one; ``index`` is ``None`` only when the show
    has no pages. Changing pages never touches running playbacks (§5.12):
    it only changes what page-relative commands resolve to.
    """

    def __init__(self, pages: tuple[CompiledPage, ...]) -> None:
        self.pages = pages
        self.index: int | None = 0 if pages else None

    @property
    def current(self) -> CompiledPage | None:
        """The current page; ``None`` when the show has no pages."""
        return None if self.index is None else self.pages[self.index]

    def go(self, *, number: int | None = None, delta: int | None = None) -> bool:
        """Go to the page with ``number``, or move ``delta`` pages in number
        order; return whether the current page changed.

        A move stops at the first and the last page, so a missed press never
        wraps to the far end. A number that names no page (an edit deleted it
        after the command was checked) changes nothing.
        """
        if self.index is None:
            return False
        if number is not None:
            target = next((k for k, page in enumerate(self.pages) if page.number == number), None)
            if target is None:
                return False
        else:
            target = min(max(self.index + (delta or 0), 0), len(self.pages) - 1)
        moved = target != self.index
        self.index = target
        return moved

    def playback(self, slot: int) -> PlaybackId | None:
        """The playback on ``slot`` of the current page; ``None`` for an empty
        slot, a slot beyond the page, or no page."""
        page = self.current
        if page is None or slot >= len(page.slots):
            return None
        return page.slots[slot]

    def rebind(self, pages: tuple[CompiledPage, ...]) -> None:
        """Follow a live edit: keep the current page by id (renamed or
        renumbered, it stays current). If the edit deleted it, the first page
        numbered at or after it becomes current (a page that took over its
        number, else the next one), else the last page."""
        old = self.current
        self.pages = pages
        if not pages:
            self.index = None
        elif old is None:
            self.index = 0
        else:
            same = next((k for k, page in enumerate(pages) if page.id == old.id), None)
            if same is None:
                later = (k for k, page in enumerate(pages) if page.number >= old.number)
                same = next(later, len(pages) - 1)
            self.index = same


HELD: Final[frozenset[ButtonFunction]] = frozenset({"flash", "swop"})
"""The button functions held while down: their release must reach the
playback their press did."""


class HeldButtons:
    """Flash and swop buttons held down through a page slot (engine thread).

    A press through a slot records, under the control that sent it (the
    binding's id), the playback the slot named and the function applied.
    The release from that control goes to the recorded playback with the
    recorded function, whatever the page or the playback's buttons are by
    then, so a flash is never left stuck on. Presses by ``playbackId``, and
    presses without a control, are not recorded: their release names the
    same playback, or resolves its slot again.
    """

    def __init__(self) -> None:
        self._held: dict[str, tuple[PlaybackId, ButtonFunction]] = {}

    def press(self, control: str, playback: PlaybackId, function: ButtonFunction) -> None:
        """Record that ``control`` holds ``function`` down on ``playback``."""
        self._held[control] = (playback, function)

    def release(self, control: str) -> tuple[PlaybackId, ButtonFunction] | None:
        """Forget and return what ``control`` held, or ``None`` if nothing."""
        return self._held.pop(control, None)


PICKUP_TOLERANCE: Final = 0.02
"""A soft control attaches when its move lands this close to the level."""

type Knob = tuple[Literal["fader", "master"], str]
"""What a move sets: a playback's fader or a master, by id."""


class Pickup:
    """Soft takeover state (engine thread; phase-6-plan §5.4).

    Per control it keeps the last value received (``last``, applied or not:
    the hardware's position) and the knob its last applied move set
    (``attached``); per knob, the control that set it last (``setter``,
    ``None`` for a jump source). A soft control is attached to a knob while
    both agree, that is while nothing else has set the knob since.

    State is kept by binding id, so it survives live edits: switching a
    surface between ``jump`` and ``soft`` takes effect at the swap, and a
    control that was the last to set a knob is still attached to it.
    """

    def __init__(self) -> None:
        self.last: dict[str, float] = {}
        self.attached: dict[str, Knob | None] = {}
        self.setter: dict[Knob, str | None] = {}

    def accept(
        self, control: str | None, soft: bool, knob: Knob, level: float, value: float
    ) -> bool:
        """Decide whether a move of ``control`` to ``value`` applies to
        ``knob``, now at ``level``, and record it.

        A jump source, or a control on a ``jump`` surface, always applies.
        A soft control applies while attached, or when its move lands
        within :data:`PICKUP_TOLERANCE` of the level or crosses it (the level
        lies between the control's previous value and this one); it is then
        attached. Otherwise the move is ignored and the control detached.
        Every applied move makes its source the knob's setter, which
        detaches whichever control was attached to it before.
        """
        if control is None:
            self.setter[knob] = None
            return True
        previous = self.last.get(control)
        self.last[control] = value
        if (
            not soft
            or (self.attached.get(control) == knob and self.setter.get(knob) == control)
            or abs(value - level) <= PICKUP_TOLERANCE
            or (previous is not None and min(previous, value) <= level <= max(previous, value))
        ):
            self.attached[control] = knob
            self.setter[knob] = control
            return True
        self.attached[control] = None
        return False

    def missed(self, control: str | None, value: float) -> None:
        """Record a move of ``control`` that reached no knob (an empty slot):
        the hardware still moved, so a later crossing is measured from
        ``value``, and the control is attached to nothing."""
        if control is not None:
            self.last[control] = value
            self.attached[control] = None
