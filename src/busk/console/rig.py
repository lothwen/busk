"""``rig check`` and ``rig import``: a plot becomes the rig, and keeps it up to
date (MVR plan Phases 2 and 3).

:func:`plan_rig` turns a :class:`~busk.importers.mvr.Plot` and the show into a
:class:`RigPlan`: the one ``BATCH`` (one undo step) that ``rig import``
submits, and the lines ``rig check`` prints instead, changing nothing. It is a
pure function; :class:`Console <busk.console.console.Console>` reads the file,
as it reads a ``profile import`` file.

A plot fixture is found in the show by its uuid (``mvrUuid``). One the show
lacks is added, one it has is updated, and a fixture of the show whose uuid
the plot no longer has is removed. A fixture without ``mvrUuid`` is the
busker's, and no import touches it.

What a fixture of the plot becomes (MVR plan §7):

* **Left out, and noted:** a multipatch copy; one with no GDTF; one whose GDTF
  is not in the plot, cannot be imported, or imports as a profile named like
  another of the show's (in any case); one with no GDTF mode, or a mode its
  profile lacks (found as ``fixture add`` finds one: by name or id, any case).
  Such a fixture is not added, and one the show has is not changed.
* **Its profile:** the show's own when it holds the GDTF's id, at the show's
  revision (another revision in the plot is noted, not taken); else the GDTF's,
  added with the first fixture that uses it. The importer's notes on a profile
  added, which run long, are counted by ``rig check`` and said by ``rig
  import``.
* **Its number:** ``FixtureIDNumeric`` above 0, else ``FixtureID`` when it is a
  whole number above 0, else, and when the number is taken (by the show, or by
  an earlier fixture of the plot), the next above the highest, after the
  others are numbered. Both are noted. A number a removed fixture had is free.
* **Its name:** the plot's, else ``<model> <number>``, as ``fixture add``
  names one.
* **Its patch:** at break 0's address, in a universe added as ``Universe N``
  when the show lacks it (routes are never touched). Other breaks are noted,
  and so is a footprint that would end past channel 512, unpatched. With no
  address, unpatched.
* **Its orientation:** the plot's invert pan and tilt where it says; the rest
  neutral. **Its location:** through the frame
  (:func:`~busk.importers.mvr.plot_location`). **Its** ``mvrUuid``: the plot
  fixture's uuid.

**Updating** (MVR plan Q2). The plot owns a fixture's patch (unpatched where
the plot does not patch it), profile and mode, location, name (where the plot
gives one) and invert pan and tilt (where it says). busk owns its number, its
swap and offsets, limits, park and groups. A fixture the plot numbers
otherwise keeps its number, noted. A new mode or profile that lacks an
element something names is refused, naming what, as ``fixture N mode`` is,
and ``rig check`` lists it first. Fixtures removed go as ``delete fixture N
cascade`` takes them (:func:`~busk.console.cascade.fixture_cascade`), and
while anything uses them the line needs ``cascade``.

**Groups** (MVR plan Q3). The first import, into a show with no fixture from a
plot, makes one for each hanging position that holds fixtures added, named
after it, in the plot's order of positions, numbered after the show's highest
group. Its members are its fixtures as the audience sees them from left to
right, stage right (the largest x) first, the lower number first at the same
x; every element of each. A later import makes none and changes none, but for
what a removal takes from them: the fixtures it adds on a hanging position
are noted, by whether the show has others of it.

**The stage** (Q4): the plot's file, its hash and the frame, set whole.

**A frontend's preview** (GAP-59 of ``docs/dev/tui/engine-gaps.md``):
:class:`RigCheck` is ``rig check``'s answer with what a frontend needs to
offer ``rig import`` without reading the text, from
:meth:`OfflineShow.rig_check <busk.runner.OfflineShow.rig_check>`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, cast

from busk.commands.edits import short
from busk.commands.types import Command
from busk.console.cascade import element_users, fixture_cascade
from busk.importers.mvr import Plot, PlotAddress, PlotFixture, plot_location
from busk.model.fixture import Fixture, Location
from busk.model.profile import FixtureMode, FixtureProfile
from busk.model.show import Audience, Show, StageSettings
from busk.session.ids import IdFactory
from busk.session.programmer import EMPTY

CHANNELS: Final = 512
NAMED: Final = 3
"""How many fixtures a note names before it counts the rest."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RigCheck:
    """What ``rig import`` of a plot would do to the show, as ``rig check``
    says it (GAP-59 of ``docs/dev/tui/engine-gaps.md``).

    ``text`` is ``rig check``'s reply, to show as it is. ``first`` is whether
    the show has no fixture from a plot yet: the import would be a first
    one, which makes groups and settles the frame. ``audience`` and
    ``origin`` (in the plot's millimetres) are the frame the plot was placed
    through: those asked for, else the show's, else ``-y`` and ``0 0 0``.

    ``changes`` is whether ``rig import`` would change the show; without
    any, it is refused, having nothing to do. ``cascade`` is whether it
    removes fixtures that something uses, so that it needs ``cascade``.
    ``blocked`` says what refuses it even with ``cascade``, a line each, as
    text to show as it is: with any, it cannot run."""

    text: str
    first: bool
    audience: Audience
    origin: tuple[float, float, float]
    changes: bool
    cascade: bool
    blocked: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class RigPlan:
    """What ``rig import`` would do, and what ``rig check`` says.

    The fixtures are named by number: ``added`` in the plot's order, the rest
    as the show has them. ``changed`` holds each change of mode or profile
    (``mode 8ch → 16ch``) with the fixtures it changes, ``blocked`` what
    stops the line even with ``cascade``, and ``uses`` what uses the fixtures
    ``removed``, counted (empty when nothing does). ``profiles`` and
    ``groups`` are the names of what it adds, ``universes`` their numbers.
    ``command`` is the ``BATCH`` that does it, labelled; ``None`` when there
    is nothing to do. ``first`` is whether the show has no fixture from a plot
    yet. ``summary`` counts what the plot holds; ``span`` is the extent of the
    fixtures the plot places, in busk's metres (``None`` without any).
    ``gdtf_notes`` are the GDTF import's notes of each profile added that has
    any: its name, and the notes as ``rig import`` says them; ``rig check``
    counts them."""

    file: str
    first: bool
    summary: str
    added: tuple[int, ...]
    moved: tuple[int, ...]
    repatched: tuple[int, ...]
    changed: tuple[tuple[str, tuple[int, ...]], ...]
    renamed: tuple[int, ...]
    inverted: tuple[int, ...]
    removed: tuple[int, ...]
    uses: str
    blocked: tuple[str, ...]
    profiles: tuple[str, ...]
    universes: tuple[int, ...]
    groups: tuple[str, ...]
    notes: tuple[str, ...]
    gdtf_notes: tuple[tuple[str, tuple[str, ...]], ...]
    span: str | None
    command: Command | None

    @property
    def changes(self) -> bool:
        """Whether a fixture is added, changed or removed."""
        return any((self.added, self.moved, self.repatched, self.changed,
                    self.renamed, self.inverted, self.removed))  # fmt: skip

    def check(self) -> str:
        """``rig check``'s reply."""
        lines = [self.summary, *(f"  blocked: {line}" for line in self.blocked)]
        if self.added:
            lines.append(f"  add {len(self.added)}: {runs(self.added)}")
        for word, numbers in (("move", self.moved), ("repatch", self.repatched)):
            if numbers:
                lines.append(f"  {word} {len(numbers)}: {runs(numbers)}")
        for what, numbers in self.changed:
            lines.append(f"  change {len(numbers)}: {runs(numbers)} {what}")
        for word, numbers in (("rename", self.renamed), ("invert", self.inverted)):
            if numbers:
                lines.append(f"  {word} {len(numbers)}: {runs(numbers)}")
        if self.removed:
            used = f": used by {self.uses}, add cascade" if self.uses else ""
            lines.append(f"  remove {len(self.removed)}: {runs(self.removed)}{used}")
        if not self.changes:
            if self.first:
                lines.append("  no fixture busk can add")
            elif self.command is None:
                lines.append("  nothing to change")
            else:
                lines.append("  no fixture changes")
        if self.profiles:
            lines.append(f"  profiles to add: {', '.join(map(short, self.profiles))}")
        if self.universes:
            lines.append(f"  universes to add: {runs(self.universes)}")
        if self.groups:
            lines.append(f"  groups to add: {', '.join(map(short, self.groups))}")
        for name, notes in self.gdtf_notes:
            counted = _count(len(notes), "note")
            lines.append(f"  note: {short(name)}: {counted} from its GDTF, listed by rig import")
        lines += [f"  note: {note}" for note in self.notes]
        if self.span is not None:
            lines.append(self.span)
        return "\n".join(lines)

    def said(self) -> tuple[str, ...]:
        """The notes ``rig import`` says: each GDTF's in full, then the rest."""
        return (*(note for _, notes in self.gdtf_notes for note in notes), *self.notes)

    def refusals(self, cascade: bool) -> tuple[str, ...]:
        """Why ``rig import`` (with ``cascade`` or without) is refused, a line
        each: what ``blocked`` says, then the fixtures removed that something
        uses, without ``cascade``."""
        if not self.uses or cascade:
            return self.blocked
        one = len(self.removed) == 1
        who = f"fixture{'' if one else 's'} {runs(self.removed)} {'is' if one else 'are'}"
        return (*self.blocked, f"{who} gone from the plot and used by {self.uses}: add cascade")

    def nothing(self) -> str:
        """What ``rig import`` says when there is nothing to do."""
        if self.first:
            return f"{self.file} has no fixture busk can add"
        return f"the rig is already as {self.file} has it"


@dataclass(slots=True)
class _Item:
    """A fixture of the plot that ``rig import`` adds, or updates: ``old``,
    the show's fixture with its uuid."""

    plotted: PlotFixture
    profile: FixtureProfile
    mode: FixtureMode
    old: Fixture | None = None
    number: int = 0
    id: str = ""
    location: Location | None = None


@dataclass(slots=True)
class _Updates:
    """The fixtures a later import changes, by number, and the edits."""

    commands: list[dict[str, Any]] = field(default_factory=list)
    moved: list[int] = field(default_factory=list)
    repatched: list[int] = field(default_factory=list)
    changed: dict[str, list[int]] = field(default_factory=dict)
    renamed: list[int] = field(default_factory=list)
    inverted: list[int] = field(default_factory=list)
    modes: list[tuple[_Item, str]] = field(default_factory=list)
    """Each fixture given another mode or profile, and that mode as
    ``fixture N mode`` names it in a refusal."""


def plan_rig(show: Show, plot: Plot, stage: StageSettings, ids: IdFactory, file: str) -> RigPlan:
    """What ``rig import`` of ``plot`` (read from ``file``, a name for the
    replies) does to ``show``, the stage set to ``stage``; new ids from ``ids``."""
    return _Planner(show, plot, ids).plan(stage, file)


class _Planner:
    def __init__(self, show: Show, plot: Plot, ids: IdFactory) -> None:
        self.show = show
        self.plot = plot
        self.ids = ids
        self.notes: dict[str, None] = {}  # in order, each once
        self.held = {p["id"] for p in show["profiles"]}  # the show's
        self.used: dict[str, FixtureProfile] = {p["id"]: p for p in show["profiles"]}  # and added
        self.names = {p["name"].casefold() for p in show["profiles"]}
        self.new: list[FixtureProfile] = []  # profiles to add, in order
        self.gdtf_notes: list[tuple[str, tuple[str, ...]]] = []
        # the show's fixtures from a plot, by uuid
        self.plotted = {f["mvrUuid"]: f for f in show["fixtures"] if "mvrUuid" in f}

    def note(self, text: str) -> None:
        self.notes[text] = None

    def plan(self, stage: StageSettings, file: str) -> RigPlan:
        first = not self.plotted
        items = self.fixtures()
        added = [item for item in items if item.old is None]
        kept = [item for item in items if item.old is not None]
        for item in kept:
            old = cast(Fixture, item.old)
            item.number, item.id = old["number"], old["id"]
        drawn = {plotted.uuid for plotted in self.plot.fixtures}
        removed = sorted(
            (f for uuid, f in self.plotted.items() if uuid not in drawn), key=lambda f: f["number"]
        )
        self.number(added, {f["number"] for f in removed})
        self.renumbered(kept)
        patched = self.patch(items)
        commands: list[dict[str, Any]] = [
            {"type": "ADD", "path": ["profiles"], "value": profile} for profile in self.new
        ]
        known = {u["number"] for u in self.show["universes"]}
        universes = self.universes(patched.values(), commands)
        for item in items:
            item.location = plot_location(item.plotted.matrix, stage["frame"])
        cascade = fixture_cascade(self.show, removed, EMPTY) if removed else None
        if cascade is not None:
            commands += map(dict, cascade.commands)
        updates = self.update(kept, patched, universes)
        commands += updates.commands
        taken: set[str] = {f["id"] for f in self.show["fixtures"]}
        for item in added:
            item.id = self.ids.new("fx", taken)
            taken.add(item.id)
            address = patched.get(item.number)
            patch = None
            if address is not None:
                patch = {"universeId": universes[address.universe], "address": address.address}
            commands.append(
                {"type": "ADD", "path": ["fixtures"], "value": self.fixture(item, patch)}
            )
        groups = self.groups(added) if first else []
        if not first:
            self.hung(added)
        commands += [{"type": "ADD", "path": ["groups"], "value": group} for group in groups]
        new_universes = sorted(set(universes) - known)
        made = [_count(len(added), "fixture"), _count(len(self.new), "profile"),
                _count(len(new_universes), "universe"), _count(len(groups), "group")]  # fmt: skip
        made = [m for m in made if not m.startswith("0 ")]
        if first:
            label = f"imported {_and(made)} from {file}"
            changes = bool(added)
        else:
            done = [f"added {_and(made)}"] if made else []
            did = [f"{word} {len(numbers)}" for word, numbers in (
                ("moved", updates.moved), ("repatched", updates.repatched),
                ("changed", [n for numbers in updates.changed.values() for n in numbers]),
                ("renamed", updates.renamed), ("inverted", updates.inverted),
            ) if numbers]  # fmt: skip
            if cascade is not None:
                left = f" (left {cascade.uses})" if cascade.uses else ""
                did.append(f"removed {len(removed)}{left}")
            if did:
                done.append(", ".join(did))
            label = f"updated the rig from {file}: {'; '.join(done) or 'no fixture changes'}"
            changes = bool(done) or not _same_stage(self.show.get("stage"), stage)
        commands.append({"type": "SET", "path": ["stage"], "value": stage})
        every = {a.universe for f in self.plot.fixtures for a in f.addresses}
        summary = (
            f"the plot has {_count(len(self.plot.fixtures), 'fixture')}, "
            f"{_count(len(self.plot.types), 'profile')} and {_count(len(every), 'universe')}"
        )
        if not first:
            summary += f"; the show has {len(drawn & set(self.plotted))} of them"
        command = {"type": "BATCH", "label": label, "commands": commands}
        return RigPlan(
            file=file,
            first=first,
            summary=summary,
            added=tuple(item.number for item in added),
            moved=tuple(updates.moved),
            repatched=tuple(updates.repatched),
            changed=tuple((what, tuple(numbers)) for what, numbers in updates.changed.items()),
            renamed=tuple(updates.renamed),
            inverted=tuple(updates.inverted),
            removed=tuple(f["number"] for f in removed),
            uses=cascade.uses if cascade is not None else "",
            blocked=self.blocked(updates.modes),
            profiles=tuple(profile["name"] for profile in self.new),
            universes=tuple(new_universes),
            groups=tuple(group["name"] for group in groups),
            notes=(*self.plot.notes, *self.notes),
            gdtf_notes=tuple(self.gdtf_notes),
            span=_span([item.location for item in items if item.location is not None]),
            command=cast(Command, command) if changes else None,
        )

    # ----------------------------------------------------------- which fixtures

    def fixtures(self) -> list[_Item]:
        """The plot's fixtures that are added or update the show's, with their
        profile and mode; the others noted, by why."""
        items: list[_Item] = []
        left: dict[str, list[str]] = {}  # not added: their labels, by why
        stay: dict[str, list[int]] = {}  # the show's, not changed: their numbers, by why
        for plotted in self.plot.fixtures:
            old = self.plotted.get(plotted.uuid)
            found = self.profile(plotted)
            if isinstance(found, str):
                why = found
            elif plotted.mode is None:
                why = "no GDTF mode"
            elif (mode := _mode(found, plotted.mode)) is None:
                why = f"{short(found['name'])} has no mode {short(plotted.mode)}"
            else:
                if found["id"] not in self.used:
                    self.add(found, cast(str, plotted.gdtf))
                items.append(_Item(plotted, found, mode, old))
                continue
            if old is None:
                left.setdefault(why, []).append(plotted.label)
            else:
                stay.setdefault(why, []).append(old["number"])
        for why, labels in left.items():
            self.note(f"{why}: {_names(labels)} not added")
        for why, numbers in stay.items():
            self.note(f"{why}: {runs(numbers)} not changed")
        return items

    def profile(self, plotted: PlotFixture) -> FixtureProfile | str:
        """The profile ``plotted`` takes: the show's, or one this import adds,
        when they have its GDTF's id; else its GDTF's. Or why it takes none."""
        if plotted.multipatch is not None:
            return "multipatch copies of other fixtures"
        if plotted.gdtf is None:
            return "no GDTF in the plot"
        kind = self.plot.types[plotted.gdtf]
        if kind.report is None:
            return f"{short(plotted.gdtf)} {kind.problem}"
        imported = kind.report.profile
        used = self.used.get(imported["id"])
        if used is not None:
            if imported["id"] in self.held and used["revision"] != imported["revision"]:
                self.note(
                    f"the show holds {short(used['name'])} at revision {used['revision']!r}; "
                    f"the plot's {imported['revision']!r} is not taken"
                )
            return used
        if imported["name"].casefold() in self.names:
            return (
                f"{short(plotted.gdtf)} imports as {short(imported['name'])}, "
                "a name another profile has"
            )
        return imported

    def add(self, profile: FixtureProfile, file: str) -> None:
        """Add ``profile``, imported from ``file``, with the importer's notes."""
        self.new.append(profile)
        self.used[profile["id"]] = profile
        self.names.add(profile["name"].casefold())
        report = self.plot.types[file].report
        if report is not None and report.notes:
            notes = tuple(f"{short(file)}: {note}" for note in report.notes)
            self.gdtf_notes.append((profile["name"], notes))

    # ----------------------------------------------------------- numbers

    def number(self, added: Sequence[_Item], free: set[int]) -> None:
        """Number the fixtures added, the numbers ``free`` (of fixtures
        removed) free; those numbered last are noted."""
        used = {f["number"] for f in self.show["fixtures"]} - free
        later: list[_Item] = []
        for item in added:
            wanted = _wanted(item.plotted)
            if wanted and wanted not in used:
                item.number = wanted
                used.add(wanted)
            else:
                later.append(item)
        for number, item in enumerate(later, start=max(used, default=0) + 1):
            item.number = number
        none = [item.number for item in later if not _wanted(item.plotted)]
        taken = [item for item in later if _wanted(item.plotted)]
        if none:
            have = "has" if len(none) == 1 else "have"
            self.note(
                f"{_count(len(none), 'fixture')} {have} no fixture number: numbered {runs(none)}"
            )
        if taken:
            have = "has a number" if len(taken) == 1 else "have numbers"
            asked = runs(_wanted(item.plotted) for item in taken)
            self.note(
                f"{_count(len(taken), 'fixture')} {have} already taken ({asked}): "
                f"numbered {runs(item.number for item in taken)}"
            )

    def renumbered(self, kept: Sequence[_Item]) -> None:
        """Note the fixtures of the show the plot numbers otherwise: they keep
        their numbers (MVR plan Q2)."""
        others = [(item.number, wanted) for item in kept
                  if (wanted := _wanted(item.plotted)) and wanted != item.number]  # fmt: skip
        if others:
            has = "has another number" if len(others) == 1 else "have other numbers"
            numbers = runs(number for number, _ in others)
            word = "number" if len(others) == 1 else "numbers"
            self.note(f"{numbers} {has} in the plot ({runs(w for _, w in others)}): {word} kept")

    # ----------------------------------------------------------- patch

    def patch(self, items: Sequence[_Item]) -> dict[int, PlotAddress]:
        """Where each fixture that is patched is patched, by number: its first
        break's address. The rest are noted."""
        patched: dict[int, PlotAddress] = {}
        breaks: list[int] = []
        past: list[int] = []
        for item in items:
            addresses = item.plotted.addresses
            if any(a.dmx_break != 0 for a in addresses):
                breaks.append(item.number)
            first = next((a for a in addresses if a.dmx_break == 0), None)
            if first is None:
                continue
            if first.address + item.mode["footprint"] - 1 > CHANNELS:
                past.append(item.number)
            else:
                patched[item.number] = first
        if breaks:
            has = "has" if len(breaks) == 1 else "have"
            self.note(f"{runs(breaks)} {has} a second DMX break, not patched")
        if past:
            self.note(f"{runs(past)} would end past channel {CHANNELS}, not patched")
        return patched

    def universes(
        self, patched: Iterable[PlotAddress], commands: list[dict[str, Any]]
    ) -> dict[int, str]:
        """The ids of the universes the patch takes, by number: the show's, and
        those it adds, each an ``ADD`` in ``commands``."""
        ids: dict[int, str] = {u["number"]: u["id"] for u in self.show["universes"]}
        taken: set[str] = set(ids.values())
        for number in sorted({address.universe for address in patched} - set(ids)):
            ident = self.ids.new("u", taken)
            taken.add(ident)
            ids[number] = ident
            value = {"id": ident, "name": f"Universe {number}", "number": number}
            commands.append({"type": "ADD", "path": ["universes"], "value": value})
        return ids

    def fixture(self, item: _Item, patch: dict[str, Any] | None) -> dict[str, Any]:
        plotted = item.plotted
        return {
            "id": item.id,
            "name": plotted.name or f"{item.profile['model']} {item.number}",
            "number": item.number,
            "profileId": item.profile["id"],
            "profileRevision": item.profile["revision"],
            "modeId": item.mode["id"],
            "patch": patch,
            "orientation": {
                "invertPan": bool(plotted.invert_pan),
                "invertTilt": bool(plotted.invert_tilt),
                "swapPanTilt": False,
                "panOffset": 0,
                "tiltOffset": 0,
            },
            "location": item.location,
            "mvrUuid": plotted.uuid,
        }

    # ----------------------------------------------------------- updates

    def update(
        self, kept: Sequence[_Item], patched: dict[int, PlotAddress], universes: dict[int, str]
    ) -> _Updates:
        """The edits that bring the show's fixtures ``kept`` to the plot (MVR
        plan Q2), in the plot's order."""
        updates = _Updates()
        profiles = {p["id"]: p for p in self.show["profiles"]}
        for item in kept:
            old = cast(Fixture, item.old)
            number, plotted = old["number"], item.plotted
            path: list[Any] = ["fixtures", {"id": old["id"]}]
            edits: list[dict[str, Any]] = []
            before = profiles[old["profileId"]]
            was = _by_id(before["modes"], old["modeId"])["name"]
            if item.profile["id"] != old["profileId"]:
                edits += [
                    _set([*path, "profileId"], item.profile["id"]),
                    _set([*path, "profileRevision"], item.profile["revision"]),
                    _set([*path, "modeId"], item.mode["id"]),
                ]
                what = (f"{short(before['name'])}, {was} → "
                        f"{short(item.profile['name'])}, {item.mode['name']}")  # fmt: skip
                updates.changed.setdefault(what, []).append(number)
                updates.modes.append((item, f"{item.profile['name']}, {item.mode['name']}"))
            elif item.mode["id"] != old["modeId"]:
                edits.append(_set([*path, "modeId"], item.mode["id"]))
                updates.changed.setdefault(f"mode {was} → {item.mode['name']}", []).append(number)
                updates.modes.append((item, item.mode["name"]))
            address = patched.get(number)
            patch = None
            if address is not None:
                patch = {"universeId": universes[address.universe], "address": address.address}
            if patch != old["patch"]:
                edits.append({"type": "PATCH_FIXTURE", "fixtureId": old["id"], "patch": patch})
                updates.repatched.append(number)
            if item.location != old.get("location"):
                edits.append(_set([*path, "location"], item.location))
                updates.moved.append(number)
            if plotted.name and plotted.name != old["name"]:
                edits.append(_set([*path, "name"], plotted.name))
                updates.renamed.append(number)
            orientation = old["orientation"]
            inverts = [
                _set([*path, "orientation", key], value)
                for key, value, was_inverted in (
                    ("invertPan", plotted.invert_pan, orientation["invertPan"]),
                    ("invertTilt", plotted.invert_tilt, orientation["invertTilt"]),
                )
                if value is not None and value != was_inverted
            ]
            if inverts:
                edits += inverts
                updates.inverted.append(number)
            updates.commands += edits
        for numbers in (updates.moved, updates.repatched, updates.renamed, updates.inverted):
            numbers.sort()
        return updates

    def blocked(self, modes: Sequence[tuple[_Item, str]]) -> tuple[str, ...]:
        """What stops the line: fixtures given a mode that lacks an element
        something names (as ``fixture N mode`` is refused), a line for each
        mode they would run, in the plot's order."""
        lose: dict[str, list[_Item]] = {}
        for item, what in modes:
            if element_users(self.show, {item.id: len(item.mode["elements"])}) is not None:
                lose.setdefault(what, []).append(item)
        lines: list[str] = []
        for what, items in lose.items():
            kept = {item.id: len(item.mode["elements"]) for item in items}
            one = len(items) == 1
            fixtures = f"fixture{'' if one else 's'} {runs(item.number for item in items)}"
            they = "it" if one else "they"
            lines.append(
                f"{fixtures} cannot run {what}: {element_users(self.show, kept)} elements "
                f"{they} would lose"
            )
        return tuple(lines)

    # ----------------------------------------------------------- groups

    def groups(self, added: Sequence[_Item]) -> list[dict[str, Any]]:
        top = max((g["number"] for g in self.show["groups"]), default=0)
        taken: set[str] = {g["id"] for g in self.show["groups"]}
        groups: list[dict[str, Any]] = []
        for uuid, name in self.plot.positions.items():
            hung = [item for item in added if item.plotted.position == uuid]
            if not hung:
                continue
            hung.sort(key=lambda item: (-cast(Location, item.location)["x"], item.number))
            ident = self.ids.new("g", taken)
            taken.add(ident)
            top += 1
            members = [
                {"fixtureId": item.id, "element": element}
                for item in hung
                for element in range(len(item.mode["elements"]))
            ]
            groups.append({"id": ident, "name": name, "number": top, "members": members})
        return groups

    def hung(self, added: Sequence[_Item]) -> None:
        """Note the fixtures a later import adds on each hanging position: it
        makes no group and changes none (MVR plan Q3). A position is new when
        no fixture of the plot the show has hangs on it."""
        known = {f.position for f in self.plot.fixtures if f.uuid in self.plotted}
        for uuid, name in self.plot.positions.items():
            numbers = [item.number for item in added if item.plotted.position == uuid]
            if not numbers:
                continue
            one = len(numbers) == 1
            if uuid in known:
                self.note(f"{runs(numbers)} {'is' if one else 'are'} new on {short(name)}: "
                          "no group changed")  # fmt: skip
            else:
                self.note(f"{runs(numbers)} hang{'s' if one else ''} on {short(name)}, "
                          "a new position: no group made")  # fmt: skip


def _set(path: list[Any], value: Any) -> dict[str, Any]:
    return {"type": "SET", "path": path, "value": value}


def _by_id(items: Iterable[Any], ident: str) -> Any:
    return next(item for item in items if item["id"] == ident)


def _same_stage(kept: StageSettings | None, stage: StageSettings) -> bool:
    """Whether the show keeps ``stage`` already (an origin may be a list)."""
    if kept is None:
        return False
    frame, other = kept["frame"], stage["frame"]
    return (
        (kept["plot"], kept["plotHash"], frame["audience"])
        == (stage["plot"], stage["plotHash"], other["audience"])
        and tuple(frame["origin"]) == tuple(other["origin"])
    )  # fmt: skip


def _mode(profile: FixtureProfile, name: str) -> FixtureMode | None:
    """The mode ``name`` names, as ``fixture add`` finds one: by name or id, any case."""
    folded = name.lower()
    return next(
        (m for m in profile["modes"] if folded in (m["name"].lower(), m["id"].lower())), None
    )


def _wanted(plotted: PlotFixture) -> int:
    """The number the plot gives ``plotted``, 0 for none."""
    return plotted.fixture_id_numeric or _whole(plotted.fixture_id)


def _whole(text: str) -> int:
    """``text`` as a whole number above 0 (at most 9 digits), else 0."""
    return int(text) if text.isascii() and text.isdecimal() and len(text) <= 9 else 0


def runs(numbers: Iterable[int]) -> str:
    """Numbers in order, three or more in a row as a run: ``101–112, 201, 202``."""
    ordered = sorted(set(numbers))
    parts: list[str] = []
    start = 0
    for k in range(1, len(ordered) + 1):
        if k == len(ordered) or ordered[k] != ordered[k - 1] + 1:
            run = ordered[start:k]
            parts += [f"{run[0]}–{run[-1]}"] if len(run) > 2 else map(str, run)
            start = k
    return ", ".join(parts)


def _names(labels: Sequence[str]) -> str:
    """``"A", "B", "C" and 4 more``."""
    if len(labels) <= NAMED:
        return ", ".join(labels)
    return f"{', '.join(labels[:NAMED])} and {len(labels) - NAMED} more"


def _span(locations: Sequence[Location]) -> str | None:
    """``fixtures span x -7.5…7.5 m, y -9.0…1.5 m, z 0.0…8.0 m``."""
    if not locations:
        return None
    parts = []
    for axis in ("x", "y", "z"):
        values = [location[axis] for location in locations]
        parts.append(f"{axis} {_metres(min(values))}…{_metres(max(values))}")
    return f"fixtures span {', '.join(parts)} m"


def _metres(value: float) -> str:
    text = f"{value:.1f}"
    return "0.0" if text == "-0.0" else text


def _count(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _and(parts: Sequence[str]) -> str:
    """``a, b and c``; ``nothing`` for none."""
    if len(parts) < 2:
        return parts[0] if parts else "nothing"
    return f"{', '.join(parts[:-1])} and {parts[-1]}"
