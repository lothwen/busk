"""``rig check`` and ``rig import``: a plot becomes the rig (MVR plan Phase 2).

:func:`plan_rig` turns a :class:`~busk.importers.mvr.Plot` and the show into a
:class:`RigPlan`: the one ``BATCH`` (one undo step) that ``rig import``
submits, and the lines ``rig check`` prints instead, changing nothing. It is a
pure function; :class:`Console <busk.console.console.Console>` reads the file,
as it reads a ``profile import`` file. This phase imports into a show with no
fixture from a plot; the console refuses the rest.

What a fixture of the plot becomes (MVR plan §7):

* **Left out, and noted:** a multipatch copy; one with no GDTF; one whose GDTF
  is not in the plot, cannot be imported, or imports as a profile named like
  another of the show's (in any case); one with no GDTF mode, or a mode its
  profile lacks (found as ``fixture add`` finds one: by name or id, any case).
* **Its profile:** the show's own when it holds the GDTF's id, at the show's
  revision (another revision in the plot is noted, not taken); else the GDTF's,
  added with the first fixture that uses it. The importer's notes on a profile
  added, which run long, are counted by ``rig check`` and said by ``rig
  import``.
* **Its number:** ``FixtureIDNumeric`` above 0, else ``FixtureID`` when it is a
  whole number above 0, else, and when the number is taken (by the show, or by
  an earlier fixture of the plot), the next above the highest, after the
  others are numbered. Both are noted.
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

**Groups** (MVR plan Q3): one for each hanging position that holds fixtures
added, named after it, in the plot's order of positions, numbered after the
show's highest group. Its members are its fixtures as the audience sees them
from left to right, stage right (the largest x) first, the lower number first
at the same x; every element of each.

**The stage** (Q4): the plot's file, its hash and the frame, set whole.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

from busk.commands.edits import short
from busk.commands.types import Command
from busk.importers.mvr import Plot, PlotAddress, PlotFixture, plot_location
from busk.model.fixture import Location
from busk.model.profile import FixtureMode, FixtureProfile
from busk.model.show import Show, StageSettings
from busk.session.ids import IdFactory

CHANNELS: Final = 512
NAMED: Final = 3
"""How many fixtures a note names before it counts the rest."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RigPlan:
    """What ``rig import`` would do, and what ``rig check`` says.

    ``fixtures`` are the numbers of the fixtures it adds, in the plot's order;
    ``profiles`` and ``groups`` the names of what it adds, ``universes`` their
    numbers. ``command`` is the ``BATCH`` that does it, labelled. ``summary``
    counts what the plot holds; ``span`` is the extent of the fixtures added,
    in busk's metres (``None`` without any). ``gdtf_notes`` are the GDTF
    import's notes of each profile added that has any: its name, and the
    notes as ``rig import`` says them; ``rig check`` counts them."""

    file: str
    summary: str
    fixtures: tuple[int, ...]
    profiles: tuple[str, ...]
    universes: tuple[int, ...]
    groups: tuple[str, ...]
    notes: tuple[str, ...]
    gdtf_notes: tuple[tuple[str, tuple[str, ...]], ...]
    span: str | None
    command: Command

    def check(self) -> str:
        """``rig check``'s reply."""
        lines = [self.summary]
        if self.fixtures:
            lines.append(f"  add {len(self.fixtures)}: {runs(self.fixtures)}")
        else:
            lines.append("  nothing to add")
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


@dataclass(slots=True)
class _Added:
    """A fixture of the plot that ``rig import`` adds."""

    plotted: PlotFixture
    profile: FixtureProfile
    mode: FixtureMode
    number: int = 0
    id: str = ""
    location: Location | None = None


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

    def note(self, text: str) -> None:
        self.notes[text] = None

    def plan(self, stage: StageSettings, file: str) -> RigPlan:
        added = self.fixtures()
        self.number(added)
        patched = self.patch(added)
        commands: list[dict[str, Any]] = [
            {"type": "ADD", "path": ["profiles"], "value": profile} for profile in self.new
        ]
        known = {u["number"] for u in self.show["universes"]}
        universes = self.universes(patched.values(), commands)
        taken: set[str] = {f["id"] for f in self.show["fixtures"]}
        for item in added:
            item.id = self.ids.new("fx", taken)
            taken.add(item.id)
            item.location = plot_location(item.plotted.matrix, stage["frame"])
            address = patched.get(item.number)
            patch = None
            if address is not None:
                patch = {"universeId": universes[address.universe], "address": address.address}
            commands.append(
                {"type": "ADD", "path": ["fixtures"], "value": self.fixture(item, patch)}
            )
        groups = self.groups(added)
        commands += [{"type": "ADD", "path": ["groups"], "value": group} for group in groups]
        commands.append({"type": "SET", "path": ["stage"], "value": stage})
        new_universes = sorted(set(universes) - known)
        made = [_count(len(added), "fixture"), _count(len(self.new), "profile"),
                _count(len(new_universes), "universe"), _count(len(groups), "group")]  # fmt: skip
        label = f"imported {_and([m for m in made if not m.startswith('0 ')])} from {file}"
        every = {a.universe for f in self.plot.fixtures for a in f.addresses}
        summary = (
            f"the plot has {_count(len(self.plot.fixtures), 'fixture')}, "
            f"{_count(len(self.plot.types), 'profile')} and {_count(len(every), 'universe')}"
        )
        return RigPlan(
            file=file,
            summary=summary,
            fixtures=tuple(item.number for item in added),
            profiles=tuple(profile["name"] for profile in self.new),
            universes=tuple(new_universes),
            groups=tuple(group["name"] for group in groups),
            notes=(*self.plot.notes, *self.notes),
            gdtf_notes=tuple(self.gdtf_notes),
            span=_span([item.location for item in added if item.location is not None]),
            command=cast(Command, {"type": "BATCH", "label": label, "commands": commands}),
        )

    # ----------------------------------------------------------- which fixtures

    def fixtures(self) -> list[_Added]:
        """The plot's fixtures that are added, with their profile and mode;
        the others noted, by why."""
        added: list[_Added] = []
        left: dict[str, list[str]] = {}
        for plotted in self.plot.fixtures:
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
                added.append(_Added(plotted, found, mode))
                continue
            left.setdefault(why, []).append(plotted.label)
        for why, labels in left.items():
            self.note(f"{why}: {_names(labels)} not added")
        return added

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

    def number(self, added: Sequence[_Added]) -> None:
        """Number the fixtures added; those numbered last are noted."""
        used = {f["number"] for f in self.show["fixtures"]}
        later: list[_Added] = []
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

    # ----------------------------------------------------------- patch

    def patch(self, added: Sequence[_Added]) -> dict[int, PlotAddress]:
        """Where each fixture that is patched is patched, by number: its first
        break's address. The rest are noted."""
        patched: dict[int, PlotAddress] = {}
        breaks: list[int] = []
        past: list[int] = []
        for item in added:
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

    def fixture(self, item: _Added, patch: dict[str, Any] | None) -> dict[str, Any]:
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

    # ----------------------------------------------------------- groups

    def groups(self, added: Sequence[_Added]) -> list[dict[str, Any]]:
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
