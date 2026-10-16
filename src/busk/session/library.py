"""The fixture profile and effect template libraries (spec §5.5, §17;
phase-3-plan §5.6 "Library"; phase-5-plan §5.12).

A :class:`ProfileLibrary` loads every ``*.json`` file of its directories
once, at startup: the built-in profiles of :mod:`busk.library` first, then
any directory given with ``busk run --library``. Each file holds one
:class:`~busk.model.profile.FixtureProfile` and is validated like a profile
embedded in a show (structure and the profile rules of the semantic pass).
A file that fails, or that repeats an id already loaded, is skipped and
reported in :attr:`ProfileLibrary.problems`.

A file that is an Open Fixture Library fixture (it has
``availableChannels``; Phase 7) is imported on the fly
(:mod:`busk.importers.ofl`, the manufacturer from the OFL repository
layout), and the import's notes join :attr:`ProfileLibrary.problems`. So is
a ``*.gdtf`` file (:mod:`busk.importers.gdtf`).

Profiles are looked up by id, or by name ignoring case. ``fixture add``
embeds a library profile into the show the first time a fixture uses it.
Shows keep their embedded copy: if the show already embeds a profile at a
different revision, the embedded copy is used and the console warns, it is
never silently updated (§17).

An :class:`EffectLibrary` loads effect templates the same way, from the
built-in ``effects.json`` of :mod:`busk.library`: one JSON list whose items
are ``{"template": EffectTemplate, "defaults": EffectDefaults}``. A template
is validated as a template embedded in a show; its ``defaults`` are the
console's defaults for a new instance of it (``size``, ``low``/``high``,
``phase``). An item that fails, or repeats an id or a name already loaded,
is skipped and reported in :attr:`EffectLibrary.problems`. ``effect add``
embeds a library template into the show the first time the show uses it;
after that the show's copy is used, so a show stays portable.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from pydantic import TypeAdapter, ValidationError, with_config

from busk.importers import ImportFailed, ImportReport
from busk.importers.gdtf import read_gdtf
from busk.importers.ofl import import_ofl, is_ofl, manufacturer_of
from busk.model.common import STRICT
from busk.model.effect import EffectPhase, EffectTemplate
from busk.model.profile import FixtureProfile
from busk.model.validate import has_errors, validate_show


def builtin_directory() -> Path:
    """The directory of the built-in profiles (package data of :mod:`busk.library`)."""
    return Path(str(resources.files("busk.library") / "profiles"))


class ProfileLibrary:
    """Validated profiles, by id, in load order."""

    def __init__(self, directories: Sequence[Path] = (), *, builtin: bool = True) -> None:
        self._profiles: dict[str, FixtureProfile] = {}
        self.problems: list[str] = []  # one line per skipped file
        for directory in ([builtin_directory()] if builtin else []) + list(directories):
            if not directory.is_dir():
                self.problems.append(f"{directory}: not a directory")
                continue
            for path in sorted([*directory.glob("*.json"), *directory.glob("*.gdtf")]):
                self._load(path)

    def __iter__(self) -> Iterator[FixtureProfile]:
        return iter(self._profiles.values())

    def __len__(self) -> int:
        return len(self._profiles)

    def get(self, ident: str) -> FixtureProfile | None:
        """The profile with id ``ident``."""
        return self._profiles.get(ident)

    def find(self, name: str) -> FixtureProfile | None:
        """The profile whose id is ``name`` or whose name is ``name``, ignoring case."""
        found = self._profiles.get(name)
        if found is not None:
            return found
        folded = name.casefold()
        return next((p for p in self._profiles.values() if p["name"].casefold() == folded), None)

    def _load(self, path: Path) -> None:
        data: Any = None
        if path.suffix != ".gdtf":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                self.problems.append(f"{path}: {exc}")
                return
        profile: FixtureProfile | None
        if path.suffix == ".gdtf" or is_ofl(data):
            report: ImportReport
            try:
                if path.suffix == ".gdtf":
                    report = read_gdtf(path)
                else:
                    report = import_ofl(data, manufacturer=manufacturer_of(path), key=path.stem)
            except ImportFailed as exc:
                self.problems.append(f"{path}: {exc}")
                return
            profile, problem = report.profile, ""
            self.problems.extend(f"{path}: {note}" for note in report.notes)
        else:
            profile, problem = validate_profile(data)
        if profile is None:
            self.problems.append(f"{path}: {problem}")
        elif profile["id"] in self._profiles:
            self.problems.append(f"{path}: profile id {profile['id']!r} is already loaded")
        else:
            self._profiles[profile["id"]] = profile


def validate_profile(data: Any) -> tuple[FixtureProfile | None, str]:
    """Validate one profile document as a show would; return it, or ``None``
    and the first error (with its path inside the profile)."""
    show, problem = _validate_probe(_probe_show(profiles=[data]), "profiles[0]")
    return (None, problem) if show is None else (show["profiles"][0], "")


# ------------------------------------------------------------------ effects


@with_config(STRICT)
class EffectDefaults(TypedDict):
    """The console's defaults for a new instance of a library template."""

    size: NotRequired[float]
    low: NotRequired[float]
    high: NotRequired[float]
    phase: NotRequired[EffectPhase]


@dataclass(frozen=True)
class LibraryEffect:
    """A library template and the console defaults for its instances."""

    template: EffectTemplate
    defaults: EffectDefaults


_DEFAULTS: TypeAdapter[EffectDefaults] = TypeAdapter(EffectDefaults)


def builtin_effects_file() -> Path:
    """The built-in effect templates (package data of :mod:`busk.library`)."""
    return Path(str(resources.files("busk.library") / "effects.json"))


class EffectLibrary:
    """Validated effect templates with their console defaults, by id, in load order."""

    def __init__(self, files: Sequence[Path] = (), *, builtin: bool = True) -> None:
        self._effects: dict[str, LibraryEffect] = {}
        self.problems: list[str] = []  # one line per skipped file or item
        for path in ([builtin_effects_file()] if builtin else []) + list(files):
            self._load(path)

    def __iter__(self) -> Iterator[LibraryEffect]:
        return iter(self._effects.values())

    def __len__(self) -> int:
        return len(self._effects)

    def get(self, ident: str) -> LibraryEffect | None:
        """The library effect whose template has id ``ident``."""
        return self._effects.get(ident)

    def find(self, name: str) -> LibraryEffect | None:
        """The library effect whose template id is ``name`` or whose name is
        ``name``, ignoring case."""
        found = self._effects.get(name)
        if found is not None:
            return found
        folded = name.casefold()
        return next(
            (e for e in self._effects.values() if e.template["name"].casefold() == folded), None
        )

    def _load(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.problems.append(f"{path}: {exc}")
            return
        if not isinstance(data, list):
            self.problems.append(f"{path}: expected a list of effect templates")
            return
        for i, item in enumerate(data):
            effect, problem = validate_library_effect(item)
            if effect is None:
                self.problems.append(f"{path}[{i}]: {problem}")
            elif effect.template["id"] in self._effects:
                ident = effect.template["id"]
                self.problems.append(f"{path}[{i}]: template id {ident!r} is already loaded")
            elif self.find(effect.template["name"]) is not None:
                name = effect.template["name"]
                self.problems.append(f"{path}[{i}]: template name {name!r} is already loaded")
            else:
                self._effects[effect.template["id"]] = effect


def validate_library_effect(item: Any) -> tuple[LibraryEffect | None, str]:
    """Validate one library item ``{"template": …, "defaults": …}``: the
    template as a show would, the defaults by type. Returns the effect, or
    ``None`` and the first error (with its path inside the item)."""
    if not isinstance(item, dict) or set(item) != {"template", "defaults"}:
        return None, 'expected {"template": {…}, "defaults": {…}}'
    show, problem = _validate_probe(
        _probe_show(effects=[item["template"]]), "effects[0]", "template"
    )
    if show is None:
        return None, problem
    try:
        defaults = _DEFAULTS.validate_python(item["defaults"], strict=True)
    except ValidationError as exc:
        error = exc.errors()[0]
        where = ".".join(str(part) for part in error["loc"])
        return None, f"defaults{'.' + where if where else ''}: {error['msg']}"
    return LibraryEffect(show["effects"][0], defaults), ""


@functools.cache
def builtin_effects() -> EffectLibrary:
    """The built-in effect library, loaded once (the console's default)."""
    return EffectLibrary()


# ------------------------------------------------------------------ probing


def _validate_probe(probe: Mapping[str, Any], prefix: str, label: str = "") -> tuple[Any, str]:
    """Validate a probe show; return it, or ``None`` and its first error. An
    error path inside the probed item at ``prefix`` is written relative to
    it, after ``label``."""
    show, issues = validate_show(json.dumps(probe))
    if show is None or has_errors(issues):
        error = next(issue for issue in issues if issue.severity == "error")
        path = error.path
        if path.startswith(prefix):
            inside = path.removeprefix(prefix)
            path = label + inside if label else inside.lstrip(".")
        return None, f"{path}: {error.message}" if path else error.message
    return show, ""


_EMPTY_LISTS = (
    "universes", "fixtures", "groups", "presets", "effects", "cueLists",
    "playbacks", "pages", "masters", "surfaces", "bindings", "park",
)  # fmt: skip


def _probe_show(profiles: Sequence[Any] = (), effects: Sequence[Any] = ()) -> Mapping[str, Any]:
    """An otherwise empty show embedding ``profiles`` and ``effects``, to
    reuse the show validator."""
    return {
        "schemaVersion": 1,
        "meta": {"id": "library", "title": "", "created": "", "modified": "", "app": ""},
        **{key: [] for key in _EMPTY_LISTS},
        "profiles": list(profiles),
        "effects": list(effects),
        "output": {
            "engineHz": 100,
            "sacnSourceName": "",
            "sacnCid": "00000000-0000-0000-0000-000000000000",
            "holdLastFrameOnEngineStall": True,
            "routes": [],
        },
    }
