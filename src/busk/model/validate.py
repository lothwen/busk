"""Show validation: structural checks (pydantic) and semantic checks (hand-written).

:func:`validate_show` validates a whole document; :func:`validate_edit`
validates a show produced by a live edit (Phase 3). :func:`validate_show`
runs four steps and stops at the first one that fails:

1. **Parse** the JSON. Syntax errors carry their line and column.
2. **Version check.** ``schemaVersion`` must be :data:`SCHEMA_VERSION`. It is
   checked before anything else because a show from a newer version would
   otherwise produce a pile of confusing structural errors.
3. **Structural validation** against the ``TypedDict`` schema with pydantic,
   in strict JSON mode: ``"1.5"`` is not a number and ``0``/``1`` are not
   booleans, but integers are accepted for floats and arrays for tuples.
4. **Semantic validation** of everything the types cannot express: unique
   ids and numbers, references between entities, profile consistency, patch
   ranges, cue numbering, … It *collects* every issue instead of stopping at
   the first one, so one run reports everything that needs fixing.

Every :class:`Issue` carries a path into the document written like
``fixtures[2].patch.address`` (or ``…values["fx-mh1:0"]`` for keys that are
not identifiers). The empty path means the document as a whole.

The semantic pass assumes nothing beyond structural validity: it never
raises on a show whose references are broken, it reports them.

:func:`validate_values` checks a static values file (``busk run --values``)
against a show with the same machinery: structural validation, then the
checks the show's ``park`` entries get.
"""

from __future__ import annotations

import json
import math
import re
import typing
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from pydantic import TypeAdapter, ValidationError

from busk.commands.types import ColorComponent, Command
from busk.model.attributes import (
    ATTRIBUTES,
    AttributeDefinition,
    DiscreteValue,
    ValueKind,
    value_kind,
)
from busk.model.common import MasterId, TargetRef, parse_target_key, target_key
from busk.model.cue import CUE_NUMBER, Cue, CueList, CueTiming, cue_number_key
from busk.model.effect import (
    ColorLayer,
    EffectInstance,
    EffectLayer,
    PresetRef,
    Rate,
    ScalarLayer,
    Waveform,
)
from busk.model.entry import FadeCurve, TargetSpec, ValueEntry, ValueSource
from busk.model.fixture import Fixture, FixtureLimits
from busk.model.master import MAX_BPM, SpeedMaster
from busk.model.output import OutputRoute
from busk.model.preset import PresetScope
from busk.model.profile import (
    ADDITIVE_PRIMARIES,
    BUILTIN_EMITTERS,
    MACRO_ATTRIBUTES,
    SHUTTER_FUNCTIONS,
    SUBTRACTIVE_PRIMARIES,
    WHEEL_ATTRIBUTES,
    ChannelDefinition,
    FixtureMode,
    FixtureProfile,
    emitter_is_subtractive,
    option_capabilities,
)
from busk.model.show import SCHEMA_VERSION, ParkEntry, Show
from busk.model.surface import Binding

type Severity = Literal["error", "warning"]
type ColorSystem = Literal["additive", "subtractive"]


def _system_name(subtractive: bool) -> str:
    return "subtractive" if subtractive else "additive"


@dataclass(frozen=True, slots=True)
class Issue:
    """One validation finding.

    ``severity`` is ``"error"`` (the show cannot be loaded) or ``"warning"``
    (suspicious but legitimate, e.g. overlapping patches).
    """

    severity: Severity
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}" if self.path else self.message


def has_errors(issues: Iterable[Issue]) -> bool:
    """Return whether any issue is an error (as opposed to a warning)."""
    return any(issue.severity == "error" for issue in issues)


SHOW_ADAPTER: Final = TypeAdapter(Show)
"""The pydantic validator for a whole show, built once at import."""


def validate_show(text: str | bytes) -> tuple[Show | None, list[Issue]]:
    """Validate a show document given as JSON text (``bytes`` must be UTF-8).

    Returns the validated show and every issue found. The show is ``None``
    when the document could not be parsed, has the wrong schema version or is
    structurally invalid; it is returned (with the issues) when only semantic
    checks failed, so callers decide what to do with errors (see
    :func:`has_errors`).
    """
    parsed = _parse_json(text, "Show file")
    if isinstance(parsed, Issue):
        return None, [parsed]
    text, data = parsed

    version_issue = _check_schema_version(data)
    if version_issue is not None:
        return None, [version_issue]

    # A future migration chain (§17) upgrades older documents here, between
    # the version check and structural validation.

    try:
        show = SHOW_ADAPTER.validate_json(text, strict=True)
    except ValidationError as exc:
        return None, _structural_issues(exc, data)

    return show, _SemanticPass(show).run()


def _entity_adapters() -> tuple[dict[str, TypeAdapter[Any]], dict[str, TypeAdapter[Any]]]:
    """One adapter per top-level collection (for its elements) and per
    top-level object, from :class:`~busk.model.show.Show`'s own type hints."""
    lists: dict[str, TypeAdapter[Any]] = {}
    objects: dict[str, TypeAdapter[Any]] = {}
    for key, hint in typing.get_type_hints(Show, include_extras=True).items():
        if typing.get_origin(hint) is typing.NotRequired:
            hint = typing.get_args(hint)[0]
        if typing.get_origin(hint) is list:
            lists[key] = TypeAdapter(typing.get_args(hint)[0])
        elif key != "schemaVersion":
            objects[key] = TypeAdapter(hint)
    return lists, objects


_LIST_ADAPTERS, _OBJECT_ADAPTERS = _entity_adapters()
SHOW_KEYS: Final = tuple(typing.get_type_hints(Show))
"""The show root's keys, in schema order."""
REQUIRED_SHOW_KEYS: Final = tuple(
    key
    for key, hint in typing.get_type_hints(Show, include_extras=True).items()
    if typing.get_origin(hint) is not typing.NotRequired
)
"""The root keys every show has; ``safety`` (Phase 7) is optional. Read from
the type hints: ``Show.__required_keys__`` counts every key as required when
annotations are postponed."""


def validate_edit(before: Show, after: Mapping[str, Any]) -> tuple[Show | None, list[Issue]]:
    """Validate ``after``, a show produced from the valid show ``before`` by a
    copy-on-write edit (:func:`busk.commands.patch.apply`). Phase 3 runs it on
    every live edit (phase-3-plan §5.3).

    1. **Structural**, per touched entity. An entity is *touched* when it is
       not the very object it was in ``before``: copy-on-write keeps every
       untouched entity identical, and ``before`` was valid, so only touched
       entities can be structurally wrong. Each one is validated on its own
       with its ``TypedDict`` adapter, through ``json.dumps`` →
       ``validate_json(strict=True)``: the path :func:`validate_show` uses, so
       every strictness rule behaves identically and issue paths carry the
       entity's position (``presets[3].values[0].value``). Missing or extra
       root keys are reported the way pydantic reports them.
    2. **Semantic**: the full semantic pass over the whole show, as
       :func:`validate_show` runs it.

    Returns the *normalised* show and every issue. Normalised means each
    touched entity is replaced by its validated copy, exactly as
    :func:`validate_show` would have produced it (keys in schema order,
    tuples where the schema says tuple, floats where it says float), so the
    show store never holds a mix of the two forms. The show is ``None`` when
    structural validation failed; then only those issues are returned, as
    :func:`validate_show` does.

    Why not :func:`validate_show` on every edit: one pydantic call over a
    large show holds the GIL for its whole duration and can stall the engine
    tick, while per-entity calls are short. A property test checks that both
    report the same issues.
    """
    issues: list[Issue] = []
    normalised: dict[str, Any] = dict(after)
    for key in REQUIRED_SHOW_KEYS:
        if key not in after:
            issues.append(Issue("error", key, "Field required"))
    for key in after:
        if key not in SHOW_KEYS:
            issues.append(Issue("error", key, "Extra inputs are not permitted"))
    for key, adapter in _LIST_ADAPTERS.items():
        items, old = after.get(key), before[key]  # type: ignore[literal-required]
        if items is old or key not in after:
            continue
        if not isinstance(items, list):
            issues.append(Issue("error", key, "Input should be a valid array"))
            continue
        untouched = {id(item) for item in old}
        checked = list(items)
        for index, item in enumerate(items):
            if id(item) not in untouched:
                checked[index] = _validate_entity(adapter, item, f"{key}[{index}]", issues)
        normalised[key] = checked
    for key, adapter in _OBJECT_ADAPTERS.items():
        if key in after and after[key] is not before.get(key):
            normalised[key] = _validate_entity(adapter, after[key], key, issues)
    if has_errors(issues):
        return None, issues
    show = cast(Show, normalised)
    return show, _SemanticPass(show).run()


def validate_effect(show: Show, instance: EffectInstance, path: str = "effect") -> list[Issue]:
    """Check one effect instance that is not part of ``show`` with the
    semantic pass's instance rules (phase-5-plan §5.13): template, target and
    master references, the rate, ``size`` and ``low``/``high`` against the
    template. ``ADD_EFFECT`` uses it for programmer effects.

    ``instance`` must be structurally valid; issue paths start at ``path``.
    The template's own rules are not checked again: ``show`` is valid.
    """
    checker = _SemanticPass(show)
    checker._effect_instance(instance, path)
    return checker.issues


COLOR_COMPONENTS: Final[tuple[ColorComponent, ...]] = typing.get_args(ColorComponent.__value__)
"""The components of a colour value, in lane order."""


def adjustment_problem(definition: AttributeDefinition, command: Mapping[str, Any]) -> str | None:
    """What is wrong with an ``ADJUST_ATTRIBUTE`` of ``definition``'s
    attribute, or ``None``: it gives exactly one of ``delta`` and ``value``,
    a finite number; a colour names one of its components, and only a colour
    does; a ``value`` is a component's, within ``0..1``; a discrete attribute
    cannot be adjusted. The session and the binding validator both use it."""
    given = [key for key in ("delta", "value") if key in command]
    if len(given) != 1:
        return "ADJUST_ATTRIBUTE needs exactly one of 'delta' and 'value'"
    number = command[given[0]]
    if isinstance(number, bool) or not isinstance(number, int | float) or not math.isfinite(number):
        return f"{given[0]} must be a finite number"
    component = command.get("component")
    if definition.kind == "discrete":
        return f"{definition.id} is discrete and cannot be adjusted"
    if definition.kind == "scalar":
        if component is not None:
            return f"{definition.id} has no components"
        if given == ["value"]:
            return f"{definition.id} takes a delta here: SET_ATTRIBUTE sets its value"
        return None
    if component not in COLOR_COMPONENTS:
        names = ", ".join(COLOR_COMPONENTS)
        if component is None:
            return f"{definition.id} is adjusted one component at a time: {names}"
        return f"a colour has no component {component!r} ({names})"
    if given == ["value"] and not 0 <= number <= 1:
        return f"{definition.id}.{component} must be within 0..1, got {number:g}"
    return None


def _validate_entity(adapter: TypeAdapter[Any], entity: Any, path: str, issues: list[Issue]) -> Any:
    """Validate one entity strictly; append its issues (rooted at ``path``) and
    return the validated copy, or the entity itself when it is invalid."""
    try:
        return adapter.validate_json(json.dumps(entity), strict=True)
    except ValidationError as exc:
        issues.extend(_structural_issues(exc, entity, root=path))
    except (TypeError, ValueError) as exc:  # not JSON-serialisable at all
        issues.append(Issue("error", path, f"Not a JSON value: {exc}"))
    return entity


VALUES_ADAPTER: Final = TypeAdapter(list[ParkEntry])
"""The pydantic validator for a static values file, built once at import."""


def validate_values(text: str | bytes, show: Show) -> tuple[list[ParkEntry] | None, list[Issue]]:
    """Validate a static values file (``busk run --values``) against ``show``.

    A values file is a JSON list of :class:`~busk.model.show.ParkEntry`-shaped
    entries, so it reuses the show schema::

        [ { "slot": { "target": { "fixtureId": "fx-mh1", "element": 0 },
                      "attribute": "pan" },
            "value": 90 } ]

    This runs the first two of its three checks:

    1. **structural**, as ``list[ParkEntry]`` in strict JSON mode;
    2. **semantic**, with the same checks as the show's ``park`` entries: the
       target exists, the attribute is in the registry and is not
       ``control``, and the value has the attribute's shape.

    The third check, against the compiled show (the target really has that
    attribute, a discrete ``slot`` is one of the channel's options), is
    :func:`busk.compiler.values.compile_values`. Paths are rooted at
    ``values``, e.g. ``values[3].slot.attribute``. The entries are ``None``
    when the file is not structurally valid.
    """
    parsed = _parse_json(text, "Values file")
    if isinstance(parsed, Issue):
        return None, [parsed]
    text, data = parsed
    try:
        entries = VALUES_ADAPTER.validate_json(text, strict=True)
    except ValidationError as exc:
        return None, _structural_issues(exc, data, root="values")
    semantic = _SemanticPass(show)
    for index, entry in enumerate(entries):
        semantic._park_entry(entry, f"values[{index}]")
    return entries, semantic.issues


def _parse_json(text: str | bytes, what: str) -> tuple[str, object] | Issue:
    """Decode ``text`` (``bytes`` must be UTF-8) and parse it as JSON.

    Returns the text and the parsed document, or an issue saying why that
    failed; syntax errors carry their line and column.
    """
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            return Issue("error", "", f"{what} is not valid UTF-8: {exc}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        message = f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        return Issue("error", "", message)
    return text, data


# ---------------------------------------------------------------- version


def _check_schema_version(data: object) -> Issue | None:
    """Require ``schemaVersion == SCHEMA_VERSION`` before structural checks."""
    if not isinstance(data, dict):
        return Issue("error", "", "A show must be a JSON object")
    if "schemaVersion" not in data:
        return Issue("error", "schemaVersion", "Field required")
    version = data["schemaVersion"]
    if type(version) is not int:  # bool is an int subclass; reject it too
        return Issue("error", "schemaVersion", "Input should be a valid integer")
    if version != SCHEMA_VERSION:
        return Issue(
            "error",
            "schemaVersion",
            f"Unsupported schema version {version}; this build reads version {SCHEMA_VERSION}",
        )
    return None


# ------------------------------------------------------------- structural

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TAG_KEYS = ("kind", "type", "protocol")  # discriminator keys used by the schema


def _join(path: str, segment: str | int) -> str:
    """Append a list index or object key to a path."""
    if isinstance(segment, int):
        return f"{path}[{segment}]"
    if _IDENTIFIER.fullmatch(segment):
        return f"{path}.{segment}" if path else segment
    return f"{path}[{json.dumps(segment)}]"


join_path = _join
"""Public name of the path joiner, so other modules (edit patches) write paths
exactly as issues do: ``fixtures[2].patch.address``, ``values["fx-mh1:0"]``."""


def _structural_issues(exc: ValidationError, data: object, root: str = "") -> list[Issue]:
    """Convert pydantic errors into path-addressed issues (deduplicated).

    ``root`` names the document in paths (``"values"`` gives ``values[3].slot``).
    """
    issues: list[Issue] = []
    seen: set[tuple[str, str]] = set()
    for error in exc.errors(include_url=False):
        path = _loc_to_path(error["loc"], data, error["type"], root)
        if error["type"] in ("union_tag_invalid", "union_tag_not_found"):
            # The loc stops at the union; point at the tag field itself.
            discriminator = str(error.get("ctx", {}).get("discriminator", "")).strip("'")
            if _IDENTIFIER.fullmatch(discriminator):
                path = _join(path, discriminator)
        if (path, error["msg"]) not in seen:
            seen.add((path, error["msg"]))
            issues.append(Issue("error", path, error["msg"]))
    return issues


def _loc_to_path(loc: tuple[int | str, ...], data: object, error_type: str, root: str = "") -> str:
    """Turn a pydantic error location into a document path.

    Pydantic locations interleave real keys with labels it adds for unions:
    the tag of a discriminated union (``'range'`` in
    ``(…, 'capabilities', 0, 'range', 'dmx')``), the member name of a plain
    union (``'list[float]'``) or ``'[key]'`` for dict-key errors. Walking the
    original JSON alongside the location tells them apart:

    * a segment equal to the current object's tag value is the union tag —
      skipped, at most once per object (``{"kind": "slot", "slot": …}`` has a
      ``slot`` tag *and* a ``slot`` key);
    * a segment that is a key of the current object is a real key;
    * the last segment of a ``missing`` error is the missing key;
    * anything else is a label and is skipped.
    """
    path = root
    node: Any = data
    tag_skipped = False
    for position, segment in enumerate(loc):
        if isinstance(segment, int):
            path = _join(path, segment)
            node = node[segment] if isinstance(node, list) and segment < len(node) else None
            tag_skipped = False
            continue
        if isinstance(node, dict):
            if not tag_skipped and any(node.get(key) == segment for key in _TAG_KEYS):
                tag_skipped = True
                continue
            if segment in node:
                path = _join(path, segment)
                node = node[segment]
                tag_skipped = False
                continue
            if position == len(loc) - 1 and error_type == "missing":
                path = _join(path, segment)
    return path


# --------------------------------------------------------------- semantic

_SACN_SOURCE_NAME_MAX_BYTES = 63
_KIND_TEXT: Final[Mapping[ValueKind, str]] = {
    "scalar": "a number",
    "color": "a colour {r, g, b}",
    "discrete": "a discrete value {slot}",
}


def _scope_key(scope: PresetScope) -> tuple[str, ...]:
    """A hashable form of a preset value's scope (§5.8)."""
    if scope["kind"] == "profile":
        return ("profile", scope["profileId"])
    if scope["kind"] == "target":
        return ("target", target_key(scope["target"]))
    return ("global",)


def _scope_text(key: tuple[str, ...]) -> str:
    return "the global scope" if len(key) == 1 else f"{key[0]} {key[1]!r}"


def _by_id[T: Mapping[str, object]](items: Iterable[T]) -> dict[str, T]:
    """Index entities by id; with duplicate ids the first one wins."""
    index: dict[str, T] = {}
    for item in items:
        index.setdefault(cast(str, item["id"]), item)
    return index


class _SemanticPass:
    """Cross-field and cross-entity checks over a structurally valid show.

    Each ``_check_*`` method walks one top-level collection and appends to
    :attr:`issues`; the shared helpers check the constructs that appear in
    several places (targets, attributes, values, references).
    """

    def __init__(self, show: Show) -> None:
        self.show = show
        self.issues: list[Issue] = []
        self.profiles = _by_id(show["profiles"])
        self.universes = _by_id(show["universes"])
        self.fixtures = _by_id(show["fixtures"])
        self.groups = _by_id(show["groups"])
        self.presets = _by_id(show["presets"])
        self.templates = _by_id(show["effects"])
        self.cue_lists = _by_id(show["cueLists"])
        self.playbacks = _by_id(show["playbacks"])
        self.masters = _by_id(show["masters"])
        self.surfaces = _by_id(show["surfaces"])
        self.page_numbers = {page["number"] for page in show["pages"]}
        # Element counts of the fixtures whose profile and mode resolve.
        self.element_counts: dict[str, int] = {}
        for fixture in show["fixtures"]:
            mode = self._mode_of(fixture)
            if mode is not None:
                self.element_counts.setdefault(fixture["id"], len(mode["elements"]))

    def run(self) -> list[Issue]:
        """Run every check; issues are grouped by top-level collection, in the
        order the collections appear in a show document."""
        self._check_profiles()
        self._check_universes()
        self._check_fixtures()
        self._check_groups()
        self._check_presets()
        self._check_effects()
        self._check_cue_lists()
        self._check_playbacks()
        self._check_pages()
        self._check_masters()
        self._check_surfaces()
        self._check_bindings()
        self._check_output()
        self._check_park()
        return self.issues

    # -- reporting

    def _error(self, path: str, message: str) -> None:
        self.issues.append(Issue("error", path, message))

    def _warning(self, path: str, message: str) -> None:
        self.issues.append(Issue("warning", path, message))

    # -- uniqueness (identity and user numbers)

    def _unique(
        self, path: str, items: Sequence[Mapping[str, object]], field: str, what: str
    ) -> None:
        """Report items whose ``field`` repeats an earlier item's value."""
        first: dict[object, int] = {}
        for index, item in enumerate(items):
            value = item[field]
            if value in first:
                self._error(
                    f"{path}[{index}].{field}",
                    f"Duplicate {what} {value!r} (first used at {path}[{first[value]}])",
                )
            else:
                first[value] = index

    def _unique_ids_and_numbers(self, path: str, items: Sequence[Mapping[str, object]]) -> None:
        self._unique(path, items, "id", "id")
        self._unique(path, items, "number", "number")

    # -- references

    def _ref(self, ident: str, index: Mapping[str, object], path: str, what: str) -> bool:
        """Check that ``ident`` names an entity of ``index``; return whether it does."""
        if ident in index:
            return True
        self._error(path, f"Unknown {what} {ident!r}")
        return False

    def _master(self, ident: MasterId, path: str, kind: str | None = None) -> bool:
        """Check a master reference, optionally requiring a master ``kind``;
        return whether it is valid."""
        master = self.masters.get(ident)
        if master is None:
            self._error(path, f"Unknown master {ident!r}")
            return False
        if kind is not None and master["kind"] != kind:
            self._error(
                path, f"Master {ident!r} is a {master['kind']} master; expected a {kind} master"
            )
            return False
        return True

    def _rate(self, rate: Rate, path: str) -> None:
        """A chase's or an effect's rate: a positive Hz value, or a positive
        multiplier of a speed master's tempo (phase-4-plan §5.14)."""
        if rate["kind"] == "bpm":
            self._master(rate["masterId"], f"{path}.masterId", "speed")
            if not rate["multiplier"] > 0:
                self._error(
                    f"{path}.multiplier",
                    f"The multiplier must be greater than 0, got {rate['multiplier']:g}",
                )
        elif not rate["value"] > 0:
            self._error(f"{path}.value", f"A rate must be greater than 0 Hz, got {rate['value']:g}")

    def _curve(self, curve: FadeCurve, path: str) -> None:
        """Bézier control values are limited to 0..1 (phase-4-plan decision 7):
        the curve then stays in 0..1, so every fade is a convex interpolation."""
        if isinstance(curve, str):
            return
        for k, point in enumerate(curve["bezier"]):
            if not 0.0 <= point <= 1.0:
                self._error(
                    f"{path}.bezier[{k}]",
                    f"Bézier control values must be within 0..1, got {point:g}",
                )

    def _timing(self, timing: CueTiming, path: str) -> None:
        self._curve(timing["curve"], f"{path}.curve")
        for family, override in timing.get("perFamily", {}).items():
            if "curve" in override:
                self._curve(override["curve"], f"{_join(f'{path}.perFamily', family)}.curve")

    # -- targets

    def _mode_of(self, fixture: Fixture) -> FixtureMode | None:
        profile = self.profiles.get(fixture["profileId"])
        if profile is None:
            return None
        return next((m for m in profile["modes"] if m["id"] == fixture["modeId"]), None)

    def _target_problem(self, ref: TargetRef) -> tuple[str, str] | None:
        """Return ``(field, message)`` if ``ref`` does not name an existing target."""
        fixture_id = ref["fixtureId"]
        if fixture_id not in self.fixtures:
            return "fixtureId", f"Unknown fixture {fixture_id!r}"
        count = self.element_counts.get(fixture_id)
        if count is not None and ref["element"] >= count:
            return "element", (
                f"Fixture {fixture_id!r} has {count} element(s); "
                f"element {ref['element']} does not exist"
            )
        return None

    def _target(self, ref: TargetRef, path: str) -> None:
        problem = self._target_problem(ref)
        if problem is not None:
            self._error(f"{path}.{problem[0]}", problem[1])

    def _target_key(self, key: str, path: str) -> None:
        """Check a ``"fixtureId:element"`` map key (the issue points at the key)."""
        ref = parse_target_key(key)
        if ref is None:
            self._error(path, f"Invalid target key {key!r}; expected 'fixtureId:element'")
            return
        problem = self._target_problem(ref)
        if problem is not None:
            self._error(path, problem[1])

    def _target_spec(self, spec: TargetSpec, path: str) -> None:
        if spec["kind"] == "group":
            self._ref(spec["groupId"], self.groups, f"{path}.groupId", "group")
        else:
            for index, ref in enumerate(spec["refs"]):
                self._target(ref, f"{path}.refs[{index}]")

    # -- attributes and values

    def _attribute(self, attribute: str, path: str) -> AttributeDefinition | None:
        """Look ``attribute`` up in the registry, reporting unknown ids."""
        definition = ATTRIBUTES.get(attribute)
        if definition is None:
            self._error(path, f"Unknown attribute {attribute!r}")
        return definition

    def _busked_attribute(
        self, attribute: str, path: str, where: str
    ) -> AttributeDefinition | None:
        """Like :meth:`_attribute`, and reject ``control`` attributes, which are
        reachable only through explicit commands and are never busked (§5.5)."""
        definition = self._attribute(attribute, path)
        if definition is not None and definition.family == "control":
            self._error(path, f"Control attributes cannot be used in {where}")
            return None
        return definition

    def _value(self, definition: AttributeDefinition, value: object, path: str) -> None:
        """Check that a value's shape matches the attribute's kind."""
        if value_kind(value) != definition.kind:
            self._error(
                path, f"Expected {_KIND_TEXT[definition.kind]} for attribute {definition.id!r}"
            )

    def _value_source(
        self, definition: AttributeDefinition | None, source: ValueSource, path: str
    ) -> None:
        """Check a value source; shape checks need a known ``definition``."""
        if source["kind"] == "literal":
            if definition is not None:
                self._value(definition, source["value"], f"{path}.value")
        elif source["kind"] == "perTarget":
            for key, value in source["values"].items():
                key_path = _join(f"{path}.values", key)
                self._target_key(key, key_path)
                if definition is not None:
                    self._value(definition, value, key_path)
        elif source["kind"] == "preset":
            self._ref(source["presetId"], self.presets, f"{path}.presetId", "preset")
        elif definition is not None:  # spread
            if definition.kind == "discrete":
                self._error(
                    path,
                    f"A spread needs a scalar or colour attribute; {definition.id!r} is discrete",
                )
            else:
                self._value(definition, source["from"], f"{path}.from")
                self._value(definition, source["to"], f"{path}.to")

    def _entry(self, entry: ValueEntry, path: str, where: str) -> None:
        self._target_spec(entry["targets"], f"{path}.targets")
        definition = self._busked_attribute(entry["attribute"], f"{path}.attribute", where)
        self._value_source(definition, entry["value"], f"{path}.value")

    # -- profiles

    def _check_profiles(self) -> None:
        profiles = self.show["profiles"]
        self._unique("profiles", profiles, "id", "id")
        for p, profile in enumerate(profiles):
            path = f"profiles[{p}]"
            self._unique(f"{path}.modes", profile["modes"], "id", "mode id")
            self._unique(f"{path}.wheels", profile["wheels"], "id", "wheel id")
            wheel_slots: dict[str, set[str]] = {}
            for w, wheel in enumerate(profile["wheels"]):
                self._unique(f"{path}.wheels[{w}].slots", wheel["slots"], "id", "slot id")
                wheel_slots.setdefault(wheel["id"], {slot["id"] for slot in wheel["slots"]})
            for m, mode in enumerate(profile["modes"]):
                self._check_mode(profile, mode, f"{path}.modes[{m}]", wheel_slots)

    def _check_mode(
        self,
        profile: FixtureProfile,
        mode: FixtureMode,
        path: str,
        wheel_slots: Mapping[str, set[str]],
    ) -> None:
        elements = mode["elements"]
        for e, element in enumerate(elements):
            if element["index"] != e:
                self._error(
                    f"{path}.elements[{e}].index",
                    f"Element indices must be 0..{len(elements) - 1} in list order; expected {e}",
                )
        used_offsets: dict[int, str] = {}  # byte offset → path of the channel using it
        identities: dict[tuple[int, str, str | None], str] = {}
        for c, channel in enumerate(mode["channels"]):
            channel_path = f"{path}.channels[{c}]"
            if channel["element"] >= len(elements):
                self._error(
                    f"{channel_path}.element",
                    f"Element {channel['element']} does not exist; "
                    f"the mode has {len(elements)} element(s)",
                )
            self._check_channel_attribute(channel, channel_path, identities)
            self._check_channel_offsets(channel, channel_path, mode["footprint"], used_offsets)
            self._check_channel_dmx(channel, channel_path, wheel_slots)
            self._check_channel_capabilities(channel, channel_path)
        systems = self._check_color_systems(profile, mode, path)
        self._check_intensity_strategy(mode, path, systems)
        curve = mode.get("dimmerCurve")
        if isinstance(curve, list) and len(curve) < 2:
            self._error(f"{path}.dimmerCurve", "A dimmer table needs at least 2 points")

    def _check_color_systems(
        self, profile: FixtureProfile, mode: FixtureMode, path: str
    ) -> dict[int, ColorSystem | None]:
        """Check each element's colour channels and return its colour system.

        Every component must name a declared or built-in emitter. An element
        mixes colour either additively (red, green and blue emitters, plus any
        extras) or subtractively (the cyan, magenta and yellow flags), never
        both (§13.3). The result maps each element that has colour channels to
        its system, or to ``None`` when its channels are already in error;
        those elements are not checked further, so one mistake is reported
        once instead of cascading.
        """
        by_element: dict[int, list[tuple[int, ChannelDefinition]]] = {}
        for c, channel in enumerate(mode["channels"]):
            if channel["attribute"] == "color" and channel["element"] < len(mode["elements"]):
                by_element.setdefault(channel["element"], []).append((c, channel))
        systems: dict[int, ColorSystem | None] = {}
        for element, channels in sorted(by_element.items()):
            systems[element] = None
            components: dict[str, bool] = {}  # component → subtractive
            first_mix: tuple[int, bool] | None = None  # (channel index, subtractive)
            valid = True
            for c, channel in channels:
                component = channel.get("component")
                if component is None or component in components:
                    valid = False  # reported by _check_channel_attribute
                    continue
                subtractive = emitter_is_subtractive(profile, component)
                if subtractive is None:
                    self._error(
                        f"{path}.channels[{c}].component",
                        f"Unknown emitter {component!r}; declare it in the profile's emitters "
                        f"or use a built-in id ({', '.join(BUILTIN_EMITTERS)})",
                    )
                    valid = False
                    continue
                components[component] = subtractive
                if first_mix is None:
                    first_mix = (c, subtractive)
                elif subtractive != first_mix[1] and valid:
                    self._error(
                        f"{path}.channels[{c}].component",
                        f"Element {element} mixes additive and subtractive colour channels "
                        f"(channels[{first_mix[0]}] is {_system_name(first_mix[1])})",
                    )
                    valid = False
            if not valid or first_mix is None:
                continue
            subtractive = first_mix[1]
            primaries = SUBTRACTIVE_PRIMARIES if subtractive else ADDITIVE_PRIMARIES
            missing = [primary for primary in primaries if primary not in components]
            if missing:
                self._error(
                    f"{path}.elements[{element}]",
                    f"{_system_name(subtractive).capitalize()} colour mixing needs "
                    f"{', '.join(primaries)} channels; element {element} has no "
                    f"{', '.join(missing)}",
                )
                continue
            systems[element] = "subtractive" if subtractive else "additive"
        return systems

    def _check_intensity_strategy(
        self, mode: FixtureMode, path: str, systems: Mapping[int, ColorSystem | None]
    ) -> None:
        """Blackout and masters must always be able to reach the fixture (§13.2).

        A ``dimmerChannel`` mode needs an intensity channel. A ``virtual`` mode
        needs an element that is dimmed virtually: one with additive colour
        channels and no intensity channel. Elements whose colour channels are
        in error count as possibly virtual, so their errors don't cascade here.
        """
        with_dimmer = {
            channel["element"]
            for channel in mode["channels"]
            if channel["attribute"] == "intensity"
        }
        if mode["intensityStrategy"] == "dimmerChannel":
            if not with_dimmer:
                self._error(
                    f"{path}.intensityStrategy",
                    "A 'dimmerChannel' mode needs at least one intensity channel",
                )
            return
        if not any(
            system != "subtractive" and element not in with_dimmer
            for element, system in systems.items()
        ):
            self._error(
                f"{path}.intensityStrategy",
                "A 'virtual' mode needs an element with additive colour channels and no "
                "intensity channel, whose emitters the virtual dimmer can scale",
            )

    def _check_channel_attribute(
        self,
        channel: ChannelDefinition,
        path: str,
        identities: dict[tuple[int, str, str | None], str],
    ) -> None:
        """Registry membership, colour components and ``(element, attribute,
        component)`` uniqueness within the mode (control channels excepted)."""
        attribute = channel["attribute"]
        self._attribute(attribute, f"{path}.attribute")
        component = channel.get("component")
        if attribute == "color" and component is None:
            self._error(f"{path}.component", "Field required for colour channels")
        elif attribute != "color" and component is not None:
            self._error(f"{path}.component", "Only colour channels take a component")
        if attribute == "control":
            # Control channels never become slots (they keep their defaultDmx,
            # §13.5), so several per element are fine: real fixtures have
            # special-function, programme and macro channels side by side.
            return
        identity = (channel["element"], attribute, component)
        if identity in identities:
            described = f"element {identity[0]}, attribute {attribute!r}"
            if component is not None:
                described += f", component {component!r}"
            self._error(
                path, f"Duplicate channel for {described} (first at {identities[identity]})"
            )
        else:
            identities[identity] = path

    def _check_channel_offsets(
        self, channel: ChannelDefinition, path: str, footprint: int, used: dict[int, str]
    ) -> None:
        """Every byte of the channel lies inside the footprint and no other
        channel of the mode uses it. Without ``fineOffsets`` the fine bytes
        follow the coarse byte."""
        nbytes = channel["bytes"]
        offset = channel["offset"]
        byte_offsets: list[tuple[int, str, str]] = [(offset, f"{path}.offset", "Offset")]
        if "fineOffsets" in channel:
            fine = channel["fineOffsets"]
            if len(fine) != nbytes - 1:
                self._error(
                    f"{path}.fineOffsets",
                    f"A {nbytes}-byte channel needs {nbytes - 1} fine offset(s), got {len(fine)}",
                )
            byte_offsets += [
                (value, f"{path}.fineOffsets[{k}]", "Fine offset") for k, value in enumerate(fine)
            ]
        else:
            byte_offsets += [
                (offset + k, f"{path}.bytes", "Implied fine offset") for k in range(1, nbytes)
            ]
        for value, value_path, label in byte_offsets:
            if value >= footprint:
                self._error(
                    value_path,
                    f"{label} {value} is outside the footprint of {footprint} channel(s)",
                )
            elif value in used:
                self._error(value_path, f"{label} {value} is already used by {used[value]}")
            else:
                used[value] = path

    def _check_channel_dmx(
        self, channel: ChannelDefinition, path: str, wheel_slots: Mapping[str, set[str]]
    ) -> None:
        """DMX values fit the channel's resolution; capabilities are ordered,
        non-overlapping and name existing wheels, slots and attributes."""
        max_raw = 256 ** channel["bytes"] - 1
        for field in ("defaultDmx", "highlightDmx"):
            value = channel.get(field)
            if value is not None and value > max_raw:
                self._error(
                    f"{path}.{field}",
                    f"{value} does not fit a {channel['bytes']}-byte channel (max {max_raw})",
                )
        previous_end: int | None = None
        for k, capability in enumerate(channel["capabilities"]):
            cap_path = f"{path}.capabilities[{k}]"
            low, high = capability["dmx"]
            if low > high:
                self._error(f"{cap_path}.dmx", f"Range [{low}, {high}] is reversed")
            elif high > max_raw:
                self._error(
                    f"{cap_path}.dmx",
                    f"Range [{low}, {high}] does not fit a {channel['bytes']}-byte channel "
                    f"(max {max_raw})",
                )
            elif previous_end is not None and low <= previous_end:
                self._error(
                    f"{cap_path}.dmx",
                    f"Capabilities must be ascending and non-overlapping; this one starts at "
                    f"{low}, the previous one ends at {previous_end}",
                )
            if low <= high:
                previous_end = high
            if capability["kind"] == "slot" and "wheel" in capability:
                wheel = capability["wheel"]
                if wheel not in wheel_slots:
                    self._error(f"{cap_path}.wheel", f"Unknown wheel {wheel!r}")
                elif capability["slot"] not in wheel_slots[wheel]:
                    self._error(
                        f"{cap_path}.slot", f"Wheel {wheel!r} has no slot {capability['slot']!r}"
                    )
            elif capability["kind"] == "function" and "param" in capability:
                param_path = f"{cap_path}.param.attribute"
                definition = self._attribute(capability["param"]["attribute"], param_path)
                if definition is not None and definition.kind != "scalar":
                    self._error(
                        param_path,
                        f"A function parameter needs a scalar attribute; {definition.id!r} is "
                        f"{definition.kind}",
                    )

    def _check_channel_capabilities(self, channel: ChannelDefinition, path: str) -> None:
        """The capabilities a channel needs for conversion (§13).

        A scalar or colour channel maps through ``range`` capabilities. A
        discrete channel outputs one of its options (see
        :func:`~busk.model.profile.option_capabilities`) and must offer its
        attribute's default: the default is what the channel outputs when
        nothing controls it, which is what makes the shutter guard (§13.2)
        total. A colour macro or effect channel's default is its own (see
        :func:`~busk.model.profile.channel_default_option`), so any option
        will do. Control channels are never converted and need nothing.
        """
        definition = ATTRIBUTES.get(channel["attribute"])
        if definition is None or definition.family == "control":
            return  # unknown attributes are reported by _check_channel_attribute
        caps_path = f"{path}.capabilities"
        if definition.kind != "discrete":
            if not any(capability["kind"] == "range" for capability in channel["capabilities"]):
                self._error(
                    caps_path, f"A {definition.kind} channel needs at least one range capability"
                )
            return
        option_ids = [option for option, _ in option_capabilities(channel)]
        if not option_ids:
            if definition.id in WHEEL_ATTRIBUTES:
                needed = "a slot capability"
            elif definition.id in MACRO_ATTRIBUTES:
                needed = "a slot or function capability other than maintenance"
            else:
                needed = "a function capability among " + ", ".join(sorted(SHUTTER_FUNCTIONS))
            self._error(caps_path, f"A {definition.id!r} channel needs {needed}")
            return
        if definition.default == "channelDefault":
            return
        default = cast(DiscreteValue, definition.default)["slot"]
        if default not in option_ids:
            self._error(
                caps_path,
                f"A {definition.id!r} channel must offer the attribute's default option "
                f"{default!r}, which it outputs when nothing controls it",
            )

    # -- patch

    def _check_universes(self) -> None:
        self._unique_ids_and_numbers("universes", self.show["universes"])

    def _check_fixtures(self) -> None:
        fixtures = self.show["fixtures"]
        self._unique_ids_and_numbers("fixtures", fixtures)
        # universe id → [(first channel, last channel, fixture index)]
        spans: dict[str, list[tuple[int, int, int]]] = {}
        for f, fixture in enumerate(fixtures):
            path = f"fixtures[{f}]"
            profile = self.profiles.get(fixture["profileId"])
            mode = self._mode_of(fixture)
            if profile is None:
                self._error(f"{path}.profileId", f"Unknown profile {fixture['profileId']!r}")
            else:
                if mode is None:
                    self._error(
                        f"{path}.modeId",
                        f"Profile {profile['id']!r} has no mode {fixture['modeId']!r}",
                    )
                if fixture["profileRevision"] != profile["revision"]:
                    # Reported, never silently applied (§17).
                    self._warning(
                        f"{path}.profileRevision",
                        f"Patched with revision {fixture['profileRevision']!r} of profile "
                        f"{profile['id']!r}, but the embedded profile is revision "
                        f"{profile['revision']!r}",
                    )
            if mode is not None and fixture["orientation"]["swapPanTilt"]:
                self._check_swap(mode, f"{path}.orientation.swapPanTilt")
            patch = fixture["patch"]
            if patch is not None:
                universe_known = self._ref(
                    patch["universeId"], self.universes, f"{path}.patch.universeId", "universe"
                )
                if mode is not None:
                    first = patch["address"]
                    last = first + mode["footprint"] - 1
                    if last > 512:
                        self._error(
                            f"{path}.patch.address",
                            f"Footprint of {mode['footprint']} channel(s) starting at {first} "
                            f"ends at {last}, past channel 512",
                        )
                    if universe_known:
                        spans.setdefault(patch["universeId"], []).append((first, min(last, 512), f))
            for element, element_patch in fixture.get("elementPatch", {}).items():
                self._ref(
                    element_patch["universeId"],
                    self.universes,
                    f"{_join(f'{path}.elementPatch', str(element))}.universeId",
                    "universe",
                )
            limits = fixture.get("limits")
            if limits is not None:
                travel = profile["physical"] if profile is not None else {}
                attributes = _mode_attributes(mode) if mode is not None else None
                if "pan" in limits:
                    self._limit_span(fixture, "pan", limits["pan"], travel.get("panRange"),
                                     attributes, f"{path}.limits.pan")  # fmt: skip
                if "tilt" in limits:
                    self._limit_span(fixture, "tilt", limits["tilt"], travel.get("tiltRange"),
                                     attributes, f"{path}.limits.tilt")  # fmt: skip
            if mode is not None:
                self._check_strobe_cap(fixture, mode, path)
        self._warn_overlaps(spans)

    def _limit_span(
        self,
        fixture: Fixture,
        axis: str,
        span: tuple[float, float],
        travel: float | None,
        attributes: frozenset[str] | None,
        path: str,
    ) -> None:
        """Check a pan or tilt limit (Phase 7, §5.6): ``min ≤ max`` is an error;
        a span past the profile's travel (``±travel/2``) or on a fixture whose
        mode has no such axis is a warning, since the limit cannot act there."""
        low, high = span
        if low > high:
            self._error(path, f"The minimum {low:g}° is above the maximum {high:g}°")
        if travel is not None and max(abs(low), abs(high)) > travel / 2:
            self._warning(
                path,
                f"{axis.title()} limits {low:g}°..{high:g}° reach past the travel of profile "
                f"{fixture['profileId']!r} (±{travel / 2:g}°)",
            )
        if attributes is not None and axis not in attributes:
            self._warning(path, f"{fixture['name']!r} has no {axis}; this limit does nothing")

    def _check_strobe_cap(self, fixture: Fixture, mode: FixtureMode, path: str) -> None:
        """Warn when the show's strobe cap is below the fixture's slowest strobe
        (Phase 7, phase-7-plan §5.11): the converter cannot strobe it slower."""
        cap = self.show.get("safety", {}).get("strobeMaxHz")
        slowest = _slowest_strobe(mode)
        if cap is not None and slowest is not None and slowest > cap:
            self._warning(
                path,
                f"{fixture['name']!r} strobes no slower than {slowest:g} Hz; the cap is {cap:g} Hz",
            )

    def _check_swap(self, mode: FixtureMode, path: str) -> None:
        """With ``swapPanTilt`` the pan channel reads the tilt value and vice
        versa (§13.1), so every element that has one must have both."""
        attributes: dict[int, set[str]] = {}
        for channel in mode["channels"]:
            if channel["attribute"] in ("pan", "tilt"):
                attributes.setdefault(channel["element"], set()).add(channel["attribute"])
        lopsided = [
            f"element {element} has only {next(iter(found))!r}"
            for element, found in sorted(attributes.items())
            if len(found) == 1
        ]
        if lopsided:
            self._error(
                path,
                "Swapping pan and tilt needs both on every element that has either; "
                + "; ".join(lopsided),
            )

    def _warn_overlaps(self, spans: Mapping[str, list[tuple[int, int, int]]]) -> None:
        """Overlapping footprints are a warning, not an error: double-patching
        is legitimate for some setups (§5.6). Each pair is reported once, on
        the later fixture."""
        fixtures = self.show["fixtures"]
        for universe_spans in spans.values():
            for j, (first, last, f) in enumerate(universe_spans):
                for other_first, other_last, other in universe_spans[:j]:
                    if first <= other_last and other_first <= last:
                        self._warning(
                            f"fixtures[{f}].patch.address",
                            f"Channels {max(first, other_first)}–{min(last, other_last)} "
                            f"overlap fixture {fixtures[other]['name']!r} (fixtures[{other}])",
                        )

    # -- groups, presets, effects

    def _check_groups(self) -> None:
        groups = self.show["groups"]
        self._unique_ids_and_numbers("groups", groups)
        for g, group in enumerate(groups):
            path = f"groups[{g}]"
            members = group["members"]
            for m, member in enumerate(members):
                self._target(member, f"{path}.members[{m}]")
            if "layout" in group:
                layout = group["layout"]
                cells = layout["cells"]
                expected = layout["width"] * layout["height"]
                if len(cells) != expected:
                    self._error(
                        f"{path}.layout.cells",
                        f"Expected width × height = {expected} cells, got {len(cells)}",
                    )
                for k, cell in enumerate(cells):
                    if cell is not None and cell >= len(members):
                        self._error(
                            f"{path}.layout.cells[{k}]",
                            f"Cell refers to member {cell}, but the group has "
                            f"{len(members)} member(s)",
                        )

    def _check_presets(self) -> None:
        presets = self.show["presets"]
        self._unique("presets", presets, "id", "id")
        first_in_pool: dict[tuple[str, int], int] = {}
        for p, preset in enumerate(presets):
            path = f"presets[{p}]"
            key = (preset["pool"], preset["number"])
            if key in first_in_pool:
                self._error(
                    f"{path}.number",
                    f"Duplicate number {preset['number']} in the {preset['pool']!r} pool "
                    f"(first used at presets[{first_in_pool[key]}])",
                )
            else:
                first_in_pool[key] = p
            first_value: dict[tuple[str, ...], int] = {}
            for v, value in enumerate(preset["values"]):
                value_path = f"{path}.values[{v}]"
                scope = value["scope"]
                # One value per (scope, attribute): a second one could never be looked up.
                scope_key = _scope_key(scope)
                where = first_value.setdefault((*scope_key, value["attribute"]), v)
                if where != v:
                    self._error(
                        f"{value_path}.attribute",
                        f"Duplicate {value['attribute']!r} value for {_scope_text(scope_key)} "
                        f"(first at {path}.values[{where}])",
                    )
                if scope["kind"] == "profile":
                    self._ref(
                        scope["profileId"],
                        self.profiles,
                        f"{value_path}.scope.profileId",
                        "profile",
                    )
                elif scope["kind"] == "target":
                    self._target(scope["target"], f"{value_path}.scope.target")
                definition = self._busked_attribute(
                    value["attribute"], f"{value_path}.attribute", "presets"
                )
                if definition is not None:
                    self._value(definition, value["value"], f"{value_path}.value")

    def _check_effects(self) -> None:
        """Effect templates (phase-5-plan §5.13): at least one layer, one
        ``absolute`` layer per attribute, scalar layers on scalar attributes
        that fade, well-formed waveforms and non-empty palettes."""
        templates = self.show["effects"]
        self._unique("effects", templates, "id", "id")
        for e, template in enumerate(templates):
            path = f"effects[{e}]"
            if not template["layers"]:
                self._error(f"{path}.layers", "An effect template needs at least one layer")
            # Two absolute layers on one attribute would both *be* its value.
            absolute: dict[str, int] = {}
            for k, layer in enumerate(template["layers"]):
                layer_path = f"{path}.layers[{k}]"
                if layer["mode"] == "absolute":
                    first = absolute.setdefault(layer["attribute"], k)
                    if first != k:
                        self._error(
                            f"{layer_path}.attribute",
                            f"Duplicate absolute layer on {layer['attribute']!r} "
                            f"(first at {path}.layers[{first}])",
                        )
                if "palette" in layer:
                    self._color_layer(cast(ColorLayer, layer), layer_path)
                else:
                    self._scalar_layer(layer, layer_path)

    def _scalar_layer(self, layer: ScalarLayer, path: str) -> None:
        attribute = layer["attribute"]
        definition = self._busked_attribute(attribute, f"{path}.attribute", "effects")
        if definition is not None:
            if definition.kind != "scalar":
                self._error(
                    f"{path}.attribute",
                    f"A scalar layer needs a scalar attribute; {attribute!r} is {definition.kind}",
                )
            elif definition.fade == "snap":
                # A snapping lane jumps once per fade; a wave on it would only jump.
                self._error(
                    f"{path}.attribute",
                    f"Effects cannot drive {attribute!r}: it snaps instead of fading",
                )
        self._waveform(layer["waveform"], f"{path}.waveform")

    def _waveform(self, wave: Waveform, path: str) -> None:
        """The waveform parameters the schema cannot bound (phase-5-plan
        decision 3); ``duty``, step levels and curve points are ``0..1`` by type."""
        if wave["kind"] == "pulse":
            parts = (wave["attack"], wave["width"], wave["decay"])
            for name, part in zip(("attack", "width", "decay"), parts, strict=True):
                if part < 0:
                    self._error(
                        f"{path}.{name}", f"A pulse's {name} must be 0 or more, got {part:g}"
                    )
            # The tolerance absorbs rounding: 0.1 + 0.2 + 0.7 is 1.0000000000000002.
            if sum(parts) > 1 + 1e-9:
                self._error(
                    path,
                    "A pulse's attack + width + decay is a fraction of a cycle and must be "
                    f"at most 1, got {sum(parts):g}",
                )
        elif wave["kind"] == "step":
            if not wave["steps"]:
                self._error(f"{path}.steps", "A step wave needs at least one step")
        elif wave["kind"] == "curve":
            points = wave["points"]
            if not points:
                self._error(f"{path}.points", "A curve needs at least one point")
            for k in range(1, len(points)):
                if not points[k][0] > points[k - 1][0]:
                    self._error(
                        f"{path}.points[{k}]",
                        f"Curve points need strictly ascending x: {points[k][0]:g} follows "
                        f"{points[k - 1][0]:g}",
                    )

    def _color_layer(self, layer: ColorLayer, path: str) -> None:
        palette = layer["palette"]
        if not palette:
            self._error(f"{path}.palette", "A colour layer needs at least one colour")
        for i, entry in enumerate(palette):
            entry_path = f"{path}.palette[{i}]"
            if "presetId" in entry:
                preset_id = cast(PresetRef, entry)["presetId"]
                self._ref(preset_id, self.presets, f"{entry_path}.presetId", "preset")
                continue
            extras = [name for name in ("w", "a", "uv") if name in entry]
            if extras:
                # A colour layer drives r, g and b and derives the rest (decision 6).
                self._warning(
                    entry_path,
                    "A colour layer sets r, g and b and derives the other emitters; "
                    f"{', '.join(repr(name) for name in extras)} ignored",
                )

    def _effect_instance(self, instance: EffectInstance, path: str) -> None:
        """An instance's references, rate and masters, and the rules that
        depend on its template: ``size`` and ``low``/``high``."""
        known = self._ref(
            instance["templateId"], self.templates, f"{path}.templateId", "effect template"
        )
        self._target_spec(instance["targets"], f"{path}.targets")
        rate = instance["rate"]
        self._rate(rate, f"{path}.rate")
        if "speedMasterId" in instance:
            speed = instance["speedMasterId"]
            if (
                self._master(speed, f"{path}.speedMasterId", "speed")
                and rate["kind"] == "bpm"
                and speed != rate["masterId"]
            ):
                self._warning(
                    f"{path}.speedMasterId",
                    f"A BPM effect follows its rate's master {rate['masterId']!r}; "
                    f"speed master {speed!r} is ignored",
                )
        if "sizeMasterId" in instance:
            self._master(instance["sizeMasterId"], f"{path}.sizeMasterId", "size")
        layers = self.templates[instance["templateId"]]["layers"] if known else []
        self._size(instance["size"], layers, f"{path}.size")
        self._bounds(instance, layers, path)

    def _size(self, size: float, layers: Sequence[EffectLayer], path: str) -> None:
        if not (math.isfinite(size) and size >= 0):
            self._error(path, f"The size must be a finite number of 0 or more, got {size:g}")
        elif size > 1 and any(layer["mode"] == "multiply" for layer in layers):
            # amount = 1 − size·(1 − w) would turn negative (decision 6).
            self._error(
                path, f"An effect with a multiply layer needs a size within 0..1, got {size:g}"
            )

    def _bounds(self, instance: EffectInstance, layers: Sequence[EffectLayer], path: str) -> None:
        """``low``/``high`` are numbers, and required when an ``absolute``
        scalar layer drives an attribute without a registry range."""
        for bound in ("low", "high"):
            value = instance.get(bound)
            if value is not None and not (
                value_kind(value) == "scalar" and math.isfinite(cast(float, value))
            ):
                self._error(f"{path}.{bound}", f"{bound} must be a number")
        unranged = []
        for layer in layers:
            definition = ATTRIBUTES.get(layer["attribute"])
            if (
                layer["mode"] == "absolute"
                and "waveform" in layer
                and definition is not None
                and definition.kind == "scalar"
                and definition.range is None
                and layer["attribute"] not in unranged
            ):
                unranged.append(layer["attribute"])
        if unranged:
            names = ", ".join(repr(attribute) for attribute in unranged)
            verb = "has" if len(unranged) == 1 else "have"
            for bound in ("low", "high"):
                if bound not in instance:
                    self._error(
                        f"{path}.{bound}",
                        f"{bound} is required: {names} {verb} no fixed range to sweep",
                    )

    # -- cue lists

    def _check_cue_lists(self) -> None:
        cue_lists = self.show["cueLists"]
        self._unique_ids_and_numbers("cueLists", cue_lists)
        for index, cue_list in enumerate(cue_lists):
            self._check_cue_list(cue_list, f"cueLists[{index}]")

    def _check_cue_list(self, cue_list: CueList, path: str) -> None:
        if "chase" in cue_list:
            self._rate(cue_list["chase"]["rate"], f"{path}.chase.rate")
        elif cue_list["mode"] == "chase":
            self._error(f"{path}.chase", "Field required when mode is 'chase'")
        cues = cue_list["cues"]
        self._unique(f"{path}.cues", cues, "id", "cue id")
        self._check_cue_numbers(cues, path)
        for c, cue in enumerate(cues):
            self._check_cue(cue, f"{path}.cues[{c}]", cue_list["tracking"])

    def _check_cue_numbers(self, cues: Sequence[Cue], path: str) -> None:
        """Numbers match ``digits[.digits]`` and are unique and strictly
        ascending, compared as integer tuples (``"1.10"`` > ``"1.9"``)."""
        first: dict[tuple[int, ...], int] = {}
        previous: tuple[tuple[int, ...], str] | None = None
        for c, cue in enumerate(cues):
            number = cue["number"]
            number_path = f"{path}.cues[{c}].number"
            if CUE_NUMBER.fullmatch(number) is None:
                self._error(
                    number_path,
                    f"Invalid cue number {number!r}; expected digits with an optional "
                    f"decimal part, e.g. '1' or '1.5'",
                )
                continue
            key = tuple(int(part) for part in number.split("."))
            if key in first:
                self._error(
                    number_path,
                    f"Duplicate cue number {number!r} (first used at {path}.cues[{first[key]}])",
                )
                continue
            first[key] = c
            if previous is not None and key < previous[0]:
                self._error(
                    number_path,
                    f"Cue numbers must be strictly ascending; {number!r} comes after "
                    f"{previous[1]!r}",
                )
            previous = (key, number)

    def _check_cue(self, cue: Cue, path: str, tracking: bool) -> None:
        self._timing(cue["timing"], f"{path}.timing")
        for n, entry in enumerate(cue["entries"]):
            self._entry(entry, f"{path}.entries[{n}]", "cue entries")
            if "curve" in entry.get("timing", {}):
                self._curve(entry["timing"]["curve"], f"{path}.entries[{n}].timing.curve")
        if not tracking:
            # Releases and blocks shape tracked states only (§9.3).
            if cue.get("releases"):
                self._warning(f"{path}.releases", "Cue releases have no effect without tracking")
            if cue.get("block"):
                self._warning(f"{path}.block", "block has no effect without tracking")
        for r, release in enumerate(cue.get("releases", [])):
            release_path = f"{path}.releases[{r}]"
            self._target_spec(release["targets"], f"{release_path}.targets")
            if release["attributes"] != "all":
                for a, attribute in enumerate(release["attributes"]):
                    self._busked_attribute(
                        attribute, f"{release_path}.attributes[{a}]", "cue releases"
                    )
        self._unique(f"{path}.effects", cue["effects"], "id", "effect instance id")
        for i, instance in enumerate(cue["effects"]):
            self._effect_instance(instance, f"{path}.effects[{i}]")

    # -- playbacks, pages, masters

    def _check_playbacks(self) -> None:
        playbacks = self.show["playbacks"]
        self._unique_ids_and_numbers("playbacks", playbacks)
        for p, playback in enumerate(playbacks):
            path = f"playbacks[{p}]"
            self._ref(playback["cueListId"], self.cue_lists, f"{path}.cueListId", "cue list")
            if "gotoCue" in playback:
                self._cue_number(playback["cueListId"], playback["gotoCue"], f"{path}.gotoCue")
            else:
                for k, function in enumerate(playback["buttons"]):
                    if function == "goto":
                        self._warning(
                            f"{path}.buttons[{k}]",
                            "A goto button needs the playback's gotoCue; it does nothing",
                        )

    def _check_pages(self) -> None:
        pages = self.show["pages"]
        self._unique_ids_and_numbers("pages", pages)
        for p, page in enumerate(pages):
            for s, playback_id in enumerate(page["slots"]):
                if playback_id is not None:
                    self._ref(playback_id, self.playbacks, f"pages[{p}].slots[{s}]", "playback")

    def _check_masters(self) -> None:
        masters = self.show["masters"]
        self._unique("masters", masters, "id", "id")
        for m, master in enumerate(masters):
            if master["kind"] == "group":
                self._ref(master["groupId"], self.groups, f"masters[{m}].groupId", "group")
            elif master["kind"] == "speed":
                self._speed_master(master, f"masters[{m}]")

    def _speed_master(self, master: SpeedMaster, path: str) -> None:
        """A tempo in ``0 < bpm ≤ 999`` and at least one positive multiplier step."""
        bpm = master["defaultBpm"]
        if not 0 < bpm <= MAX_BPM:
            self._error(
                f"{path}.defaultBpm",
                f"The tempo must be greater than 0 and at most {MAX_BPM:g} BPM, got {bpm:g}",
            )
        steps = master["multiplierSteps"]
        if not steps:
            self._error(f"{path}.multiplierSteps", "A speed master needs at least one step")
        for k, step in enumerate(steps):
            if not step > 0:
                self._error(
                    f"{path}.multiplierSteps[{k}]",
                    f"Multiplier steps must be greater than 0, got {step:g}",
                )

    # -- surfaces and bindings

    def _check_surfaces(self) -> None:
        """Unique ids; OSC and web surfaces listen on a valid port, one surface
        of a kind per port (Phase 6)."""
        surfaces = self.show["surfaces"]
        self._unique("surfaces", surfaces, "id", "id")
        listening: dict[tuple[str, int], int] = {}  # (kind, port) → first surface index
        for k, surface in enumerate(surfaces):
            if surface["kind"] not in ("osc", "web"):
                continue
            path = f"surfaces[{k}].match"
            port = surface["match"].get("port")
            if port is None or not 0 < port < 65536:
                self._error(
                    f"{path}.port",
                    f"An {surface['kind']} surface needs a port from 1 to 65535, got {port!r}",
                )
            elif (surface["kind"], port) in listening:
                first = listening[surface["kind"], port]
                self._error(f"{path}.port", f"Port {port} is already used by surfaces[{first}]")
            else:
                listening[surface["kind"], port] = k
            feedback_port = surface["match"].get("feedbackPort")
            if feedback_port is not None and not 0 < feedback_port < 65536:
                self._error(
                    f"{path}.feedbackPort",
                    f"The feedback port must be from 1 to 65535, got {feedback_port}",
                )

    def _check_bindings(self) -> None:
        bindings = self.show["bindings"]
        self._unique("bindings", bindings, "id", "id")
        for b, binding in enumerate(bindings):
            path = f"bindings[{b}]"
            if self._ref(binding["surfaceId"], self.surfaces, f"{path}.surfaceId", "surface"):
                self._binding_surface(binding, path)
            if binding["input"]["kind"] == "midiClock" and binding["action"]["kind"] != "tap":
                self._warning(
                    f"{path}.action", "A MIDI clock input only drives tap actions; it does nothing"
                )
            feedback = binding.get("feedback")
            if feedback is not None and feedback["address"]["kind"] == "midiClock":
                self._error(
                    f"{path}.feedback.address", "Feedback cannot be sent to a MIDI clock input"
                )
            action = binding["action"]
            action_path = f"{path}.action"
            if action["kind"] == "pageAbs":
                self._page_number(action["number"], f"{action_path}.number")
            elif action["kind"] == "playbackFaderAbs":
                self._ref(
                    action["playbackId"], self.playbacks, f"{action_path}.playbackId", "playback"
                )
            elif action["kind"] == "master":
                self._master(action["masterId"], f"{action_path}.masterId")
            elif action["kind"] == "tap":
                self._master(action["masterId"], f"{action_path}.masterId", "speed")
            elif action["kind"] == "command":
                command = action["command"]
                self._command(command, f"{action_path}.command")
                if command["type"] == "OUTPUT" and not command["on"] and _fader_like(binding):
                    self._warning(
                        f"{path}.input",
                        "OUTPUT off is sent each time this control is pushed up; "
                        "bind it to a button",
                    )

    def _binding_surface(self, binding: Binding, path: str) -> None:
        """Warn about a binding its surface cannot drive (Phase 6): MIDI inputs
        belong on MIDI surfaces and OSC paths on OSC surfaces; a web remote
        sends commands of its own and shows state by itself, so it takes no
        bindings and no feedback."""
        kind = self.surfaces[binding["surfaceId"]]["kind"]
        surface = binding["surfaceId"]
        if kind == "web":
            self._warning(
                f"{path}.surfaceId",
                f"Web surface {surface!r} sends commands of its own; this binding does nothing",
            )
            if "feedback" in binding:
                self._warning(
                    f"{path}.feedback",
                    f"Web surface {surface!r} shows state by itself; this feedback is not sent",
                )
            return
        input_kind = binding["input"]["kind"]
        sent_by = "osc" if input_kind == "osc" else "midi"
        if input_kind != "hw" and kind != sent_by:
            self._warning(
                f"{path}.input",
                f"{kind} surface {surface!r} cannot send {input_kind} inputs; "
                "this binding does nothing",
            )

    def _page_number(self, number: int, path: str) -> None:
        """A warning, not an error, for a page number no page has: page numbers
        are user-facing and get renumbered, like cue numbers."""
        if number not in self.page_numbers:
            self._warning(path, f"There is no page {number}")

    def _one_of(self, command: Mapping[str, object], keys: tuple[str, str], path: str) -> bool:
        """Check that ``command`` has exactly one of ``keys``; return whether it does."""
        if sum(key in command for key in keys) == 1:
            return True
        self._error(path, f"{command['type']} needs exactly one of {keys[0]!r} and {keys[1]!r}")
        return False

    def _command(self, command: Command, path: str) -> None:
        """Check the references of a command embedded in a binding."""
        if command["type"] in ("SET_FADER", "PLAYBACK_BUTTON"):
            if self._one_of(command, ("playbackId", "slot"), path) and "playbackId" in command:
                self._ref(command["playbackId"], self.playbacks, f"{path}.playbackId", "playback")
        elif command["type"] == "PAGE":
            if self._one_of(command, ("number", "delta"), path) and "number" in command:
                self._page_number(command["number"], f"{path}.number")
        elif command["type"] == "SET_MASTER":
            self._master(command["masterId"], f"{path}.masterId")
        elif command["type"] == "TAP":
            self._master(command["masterId"], f"{path}.masterId", "speed")
        elif command["type"] == "SET_BPM":
            self._master(command["masterId"], f"{path}.masterId", "speed")
            if not 0 < command["bpm"] <= MAX_BPM:
                self._error(
                    f"{path}.bpm",
                    f"The tempo must be greater than 0 and at most {MAX_BPM:g} BPM, "
                    f"got {command['bpm']:g}",
                )
        elif command["type"] == "SELECT":
            self._target_spec(command["targets"], f"{path}.targets")
        elif command["type"] == "SET_ATTRIBUTE":
            definition = self._busked_attribute(
                command["attribute"], f"{path}.attribute", "programmer values"
            )
            self._value_source(definition, command["value"], f"{path}.value")
        elif command["type"] == "ADJUST_ATTRIBUTE":
            definition = self._busked_attribute(
                command["attribute"], f"{path}.attribute", "programmer values"
            )
            problem = None if definition is None else adjustment_problem(definition, command)
            if problem is not None:
                self._error(path, problem)
        elif command["type"] == "APPLY_PRESET":
            self._ref(command["presetId"], self.presets, f"{path}.presetId", "preset")
        elif command["type"] == "RECORD_CUE":
            self._ref(command["cueListId"], self.cue_lists, f"{path}.cueListId", "cue list")
        elif command["type"] == "PATCH_FIXTURE":
            self._ref(command["fixtureId"], self.fixtures, f"{path}.fixtureId", "fixture")
            if command["patch"] is not None:
                self._ref(
                    command["patch"]["universeId"],
                    self.universes,
                    f"{path}.patch.universeId",
                    "universe",
                )
        elif command["type"] == "ASSIGN_PLAYBACK":
            self._ref(command["pageId"], _by_id(self.show["pages"]), f"{path}.pageId", "page")
            if command["playbackId"] is not None:
                self._ref(command["playbackId"], self.playbacks, f"{path}.playbackId", "playback")
        elif command["type"] == "BATCH":
            for c, inner in enumerate(command["commands"]):
                self._command(inner, f"{path}.commands[{c}]")
        elif command["type"] in _PLAYBACK_COMMANDS:
            playback_id = cast(Mapping[str, str], command)["playbackId"]
            known = self._ref(playback_id, self.playbacks, f"{path}.playbackId", "playback")
            if known and command["type"] == "GOTO":
                self._goto(playback_id, command["cueNumber"], f"{path}.cueNumber")

    def _goto(self, playback_id: str, number: str, path: str) -> None:
        """Check the cue number of a ``GOTO`` to ``playback_id``."""
        self._cue_number(self.playbacks[playback_id]["cueListId"], number, path)

    def _cue_number(self, cue_list_id: str, number: str, path: str) -> None:
        """A warning, not an error, for a cue number (of a ``GOTO`` or a
        ``gotoCue``) the cue list does not have: cue numbers are user-facing
        and get renumbered, and an error would block that edit."""
        cue_list = self.cue_lists.get(cue_list_id)
        if cue_list is None:
            return  # reported with the playback
        wanted = cue_number_key(number)
        if wanted is None or all(cue_number_key(c["number"]) != wanted for c in cue_list["cues"]):
            self._warning(path, f"Cue list {cue_list['name']!r} has no cue {number!r}")

    # -- output and park

    def _check_output(self) -> None:
        output = self.show["output"]
        routes = output["routes"]
        self._unique("output.routes", routes, "id", "id")
        for r, route in enumerate(routes):
            self._ref(
                route["universeId"], self.universes, f"output.routes[{r}].universeId", "universe"
            )
        self._check_sacn_universes(routes)
        self._check_dmx_usb_ports(routes)
        try:
            uuid.UUID(output["sacnCid"])
        except ValueError:
            self._error("output.sacnCid", f"Not a valid UUID: {output['sacnCid']!r}")
        name_bytes = len(output["sacnSourceName"].encode("utf-8"))
        if name_bytes > _SACN_SOURCE_NAME_MAX_BYTES:
            self._error(
                "output.sacnSourceName",
                f"Must be at most {_SACN_SOURCE_NAME_MAX_BYTES} UTF-8 bytes, got {name_bytes}",
            )

    def _check_sacn_universes(self, routes: Sequence[OutputRoute]) -> None:
        """Enabled sACN routes on one sACN universe send one show universe.

        They share the universe's sequence numbers under the show's CID, so
        two show universes there would reach receivers as one stream with two
        different data sets. Disabled routes send nothing and are skipped.
        """
        senders: dict[int, tuple[str, str]] = {}  # sACN universe → (route id, universeId)
        for r, route in enumerate(routes):
            if route["protocol"] != "sacn" or not route["enabled"]:
                continue
            first_id, first_universe = senders.setdefault(
                route["universe"], (route["id"], route["universeId"])
            )
            if route["universeId"] != first_universe:
                self._error(
                    f"output.routes[{r}].universe",
                    f"sACN universe {route['universe']} is already sent by route "
                    f"{first_id!r} from universe {first_universe!r}",
                )

    def _check_dmx_usb_ports(self, routes: Sequence[OutputRoute]) -> None:
        """Two enabled DMX-USB routes cannot share a serial port (Phase 7): the
        second one would fail to open it, or both would write to it."""
        users: dict[str, str] = {}  # port → id of the first route on it
        for r, route in enumerate(routes):
            if route["protocol"] != "dmxUsb" or not route["enabled"]:
                continue
            port = route["device"]["port"]
            first = users.setdefault(port, route["id"])
            if first != route["id"]:
                self._error(
                    f"output.routes[{r}].device.port",
                    f"Port {port!r} is already used by route {first!r}",
                )

    def _check_park(self) -> None:
        """Check each park entry, then (Phase 7) that no slot is parked twice
        and that parked values sit inside the fixture's limits, which win at
        the safety stage."""
        parked: dict[tuple[str, str], int] = {}  # (target key, attribute) → first entry
        for k, entry in enumerate(self.show["park"]):
            path = f"park[{k}]"
            self._park_entry(entry, path)
            target, attribute = entry["slot"]["target"], entry["slot"]["attribute"]
            first = parked.setdefault((target_key(target), attribute), k)
            fixture = self.fixtures.get(target["fixtureId"])
            name = repr(fixture["name"]) if fixture is not None else repr(target["fixtureId"])
            if first != k:
                self._error(
                    f"{path}.slot",
                    f"{name} element {target['element']} {attribute} is already parked by "
                    f"park[{first}]",
                )
            if fixture is not None:
                self._park_limits(fixture.get("limits"), attribute, entry["value"], path)

    def _park_limits(
        self, limits: FixtureLimits | None, attribute: str, value: object, path: str
    ) -> None:
        """Warn about a parked pan, tilt or intensity outside the fixture's limits."""
        if limits is None or not isinstance(value, int | float) or isinstance(value, bool):
            return
        span = limits.get("pan") if attribute == "pan" else limits.get("tilt")
        if attribute in ("pan", "tilt") and span is not None and span[0] <= span[1]:
            if not span[0] <= value <= span[1]:
                self._warning(
                    f"{path}.value",
                    f"Parked {attribute} {value:g}° is outside the fixture's limits "
                    f"{span[0]:g}°..{span[1]:g}°; the limits win",
                )
        elif attribute == "intensity" and value > limits.get("intensityMax", 1.0):
            self._warning(
                f"{path}.value",
                f"Parked intensity {value:g} is above the fixture's intensityMax "
                f"{limits['intensityMax']:g}; the limit wins",
            )

    def _park_entry(self, entry: ParkEntry, path: str) -> None:
        """A park entry names an existing target, a busked attribute and a
        value of the attribute's shape."""
        self._target(entry["slot"]["target"], f"{path}.slot.target")
        definition = self._busked_attribute(
            entry["slot"]["attribute"], f"{path}.slot.attribute", "park entries"
        )
        if definition is not None:
            self._value(definition, entry["value"], f"{path}.value")


def _mode_attributes(mode: FixtureMode) -> frozenset[str]:
    """The attributes a mode has channels for, plus ``intensity`` for a
    virtually dimmed mode (enough for the limits checks of Phase 7)."""
    attributes = {channel["attribute"] for channel in mode["channels"]}
    if mode["intensityStrategy"] == "virtual":
        attributes.add("intensity")
    return frozenset(attributes)


def _slowest_strobe(mode: FixtureMode) -> float | None:
    """The lowest ``strobeRate`` (Hz) a mode can be set to, or ``None`` if it
    has no strobe rate: from ``strobeRate`` channels' ranges and the strobe
    parameters of function capabilities, on busked (non-control) channels."""
    rates: list[float] = []
    for channel in mode["channels"]:
        definition = ATTRIBUTES.get(channel["attribute"])
        if definition is None or definition.family == "control":
            continue
        for capability in channel["capabilities"]:
            if capability["kind"] == "range" and channel["attribute"] == "strobeRate":
                rates.append(min(capability["value"]))
            elif capability["kind"] == "function":
                param = capability.get("param")
                if param is not None and param["attribute"] == "strobeRate":
                    rates.append(min(param["value"]))
    return min(rates, default=None)


def _fader_like(binding: Binding) -> bool:
    """Whether a binding's input is a fader or knob, which sends a press every
    time it is pushed past half way (Phase 7). Pitch bend always is; a CC is
    unless it lights an LED (CC buttons, like the nanoKONTROL2's). Notes are
    buttons, and OSC and hardware controls cannot be told apart."""
    kind = binding["input"]["kind"]
    if kind == "midiPitchBend":
        return True
    feedback = binding.get("feedback")
    return kind == "midiCC" and (feedback is None or feedback["kind"] != "led")


_PLAYBACK_COMMANDS: Final = frozenset(
    {
        "TRIGGER_PLAYBACK",
        "RELEASE_PLAYBACK",
        "TOGGLE_PLAYBACK",
        "FLASH",
        "GO",
        "BACK",
        "GOTO",
        "SELECT_PLAYBACK",
    }
)
"""Command types whose only reference is ``playbackId`` (``SET_FADER`` may
name a slot instead since Phase 6, so it is checked on its own)."""
