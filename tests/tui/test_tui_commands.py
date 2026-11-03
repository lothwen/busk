"""The lines the UI builds (``busk_tui.commands``): their format, their
performance marks, and the contract test: busk accepts every one of them on
the club-night show (plan §4.6)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

import busk
from busk.commands.record import POOL_FAMILIES
from busk.model.attributes import ATTRIBUTES
from busk_tui import attributes, commands, config
from busk_tui.bridge import show_model
from busk_tui.commands import Line

BUILDERS: dict[str, tuple[Line, str, bool]] = {
    # name: (a line it builds, that line's text, whether busk runs it as a performance line)
    "help": (commands.help_(), "help", False),
    "undo": (commands.undo(), "undo", False),
    "redo": (commands.redo(), "redo", False),
    "save": (commands.save(), "save", False),
    "go": (commands.go(3), "go 3", True),
    "back": (commands.back(3), "back 3", True),
    "release": (commands.release(9), "release 9", True),
    "release_all": (commands.release_all(), "release all", True),
    "fader": (commands.fader(3, 0.72), "fader 3 72%", True),
    "flash on": (commands.flash(3, True), "flash 3 on", True),
    "flash off": (commands.flash(3, False), "flash 3 off", True),
    "gm": (commands.gm(0.8), "gm 80%", True),
    "master": (commands.master("Wash level", 0.4), 'master "Wash level" 40%', True),
    "blackout on": (commands.blackout(True), "blackout on", True),
    "blackout off": (commands.blackout(False), "blackout off", True),
    "output on": (commands.output(True), "output on", True),
    "output off": (commands.output(False), "output off", True),
    "tap": (commands.tap("Speed 1"), 'tap "Speed 1"', True),
    "bpm": (commands.bpm("Speed 1", 120.5), 'bpm "Speed 1" 120.5', True),
    "page next": (commands.page(1), "page next", True),
    "page prev": (commands.page(-1), "page prev", True),
    "sel group": (commands.sel_group(2), "sel group 2", False),
    "sel + group": (commands.sel_group(1, add=True), "sel + group 1", False),
    "preset": (commands.preset("color", 1), "preset color 1", False),
    "effect stop": (commands.effect_stop("fx5"), "effect stop fx5", False),
    "effect run": (commands.effect_run("fx5"), "effect run fx5", False),
    "effect remove": (commands.effect_remove("fx5"), "effect remove fx5", False),
    "effect add": (commands.effect_add("Chase"), 'effect add "Chase"', False),
    "goto": (commands.goto(9, "3"), "goto 9 3", True),
    "record cue": (commands.record_cue(9), "record cue 9", False),
    "cuelist chase": (commands.cuelist_chase(9), "cuelist 9 chase bpm x 1", False),
    "cuelist chase kept": (
        commands.cuelist_chase(10, "bpm x 1 bounce", 0.25),
        "cuelist 10 chase bpm x 1 bounce crossfade 0.25",
        False,
    ),
    "cuelist sequence": (commands.cuelist_sequence(10), "cuelist 10 sequence", False),
    "sel none": (commands.sel_none(), "sel none", False),
    "set level": (commands.set_level("intensity", 0.72), "set intensity 72%", False),
    "set component": (commands.set_level("color.r", 0.5), "set color.r 50%", False),
    "set degrees": (commands.set_number("pan", -45.0), "set pan -45", False),
    "set hz": (commands.set_number("strobeRate", 12.5), "set strobeRate 12.5", False),
    "set zoom": (commands.set_number("zoom", 20.0), "set zoom 20", False),
    "step up": (commands.step_level("intensity", 0.05), "set intensity by 5%", False),
    "step down": (commands.step_level("intensity", -0.02), "set intensity by -2%", False),
    "step component": (commands.step_level("color.w", 0.05), "set color.w by 5%", False),
    "step degrees": (commands.step_number("pan", -15.0), "set pan by -15", False),
    "step hz": (commands.step_number("strobeRate", 0.5), "set strobeRate by 0.5", False),
    "blind on": (commands.blind(True), "blind on", False),
    "blind off": (commands.blind(False), "blind off", False),
    "highlight on": (commands.highlight(True), "highlight on", False),
    "highlight off": (commands.highlight(False), "highlight off", False),
    "sel fixture": (commands.sel_fixture(101), "sel fixture 101", False),
    "sel + fixture": (commands.sel_fixture(102, add=True), "sel + fixture 102", False),
    "sel - fixture": (commands.sel_fixture(101, remove=True), "sel - fixture 101", False),
    "sel fixtures": (commands.sel_fixtures((201, 202)), "sel fixture 201, fixture 202", False),
    "sel + fixtures": (
        commands.sel_fixtures((203, 204), add=True),
        "sel + fixture 203, fixture 204",
        False,
    ),
    "sel heads": (commands.sel_fixtures((101, 102)), "sel fixture 101, fixture 102", False),
    "set color": (commands.set_color(1.0, 0.254, 0.0), "set color 1 0.25 0", False),
    "set option": (commands.set_option("gobo1", "breakup"), "set gobo1 breakup", False),
    "set spread": (commands.set_spread("pan", -30.0, 30.0), "set pan spread -30 30", False),
    "set spread center": (
        commands.set_spread("tilt", 10.0, 40.5, "center"),
        "set tilt spread 10 40.5 center",
        False,
    ),
    "set spread level": (
        commands.set_spread("intensity", 0.0, 1.0, "edges", level=True),
        "set intensity spread 0% 100% edges",
        False,
    ),
    "record preset": (
        commands.record_preset("color", 5, "global", name="Crimson"),
        'record preset color 5 global "Crimson"',
        False,
    ),
    "record preset merge": (
        commands.record_preset("color", 5, "target", "merge"),
        "record preset color 5 target merge",
        False,
    ),
    "record preset replace": (
        commands.record_preset("color", 5, "global", "replace"),
        "record preset color 5 global replace",
        False,
    ),
    "record preset remove": (
        commands.record_preset("color", 5, None, "remove"),
        "record preset color 5 remove",
        False,
    ),
    "rename preset": (
        commands.rename_preset("color", 5, "Scarlet"),
        'rename preset color 5 "Scarlet"',
        False,
    ),
    "renumber preset": (
        commands.renumber_preset("color", 5, 9),
        "preset color 5 number 9",
        False,
    ),
    "delete preset": (commands.delete_preset("color", 9), "delete preset color 9", False),
    "clear": (commands.clear(), "clear", False),
}

PREFILLS = (
    commands.set_prefill("intensity"),
    commands.set_prefill("color"),
    commands.set_prefill("shutter"),
    commands.FADE_PREFILL,
    commands.cue_prefill(9, "3", "time"),
    commands.cue_prefill(9, "3", "follow"),
    commands.cue_prefill(9, "3", "wait"),
    commands.cue_prefill(9, "3", "go"),
    commands.cue_time_prefill(9, "3", "1/3", "delay"),
    commands.cue_time_prefill(9, "3", "1/3"),
    commands.rename_cue_prefill(9, "3"),
    commands.patch_prefill(101),
    commands.rename_fixture_prefill(101),
    commands.category_prefill("Generic Spot 16ch"),
    commands.bind_prefill("nanoKONTROL2"),
    commands.feedback_prefill("nanoKONTROL2", "cc 1 0"),
    commands.pickup_prefill("nanoKONTROL2"),
)
"""Lines the UI puts in the prompt to finish."""

WHOLE_PREFILLS = (
    commands.location_prefill(101, None),
    commands.location_prefill(102, (1.5, -2.0, 4.25, 0.0, 0.0, 90.0)),
    commands.unbind_prefill("nanoKONTROL2", "cc 1 0"),
)
"""Pre-fills that are whole lines: Enter runs them."""

PERFORMANCE_WORDS = {
    "go", "back", "goto", "release", "fader", "flash", "toggle", "button", "gm", "master",
    "blackout", "tap", "bpm", "page", "output",
}  # fmt: skip
"""The first words of busk's performance lines (``LiveShow.execute``);
``master add`` and ``page add`` are edits."""


@pytest.fixture
def show(club_path: Path, tmp_path: Path) -> busk.OfflineShow:
    """A club-night show of the test's own, saved to a file of its own."""
    document, _ = busk.load_show(club_path)
    return busk.OfflineShow(document, path=tmp_path / "club.show")


def test_levels_are_whole_percent() -> None:
    assert commands.percent(0.72) == "72%"
    assert commands.percent(0.004) == "0%"
    assert commands.percent(0.996) == "100%"
    assert commands.percent(1.5) == "100%"
    assert commands.percent(-0.2) == "0%"


def test_names_are_quoted_and_a_quote_in_one_is_refused() -> None:
    assert commands.quoted("Grand Master") == '"Grand Master"'
    with pytest.raises(ValueError, match="double quote"):
        commands.quoted('Say "hi"')


def test_numbers_have_two_decimals_at_most() -> None:
    assert commands.number(120.0) == "120"
    assert commands.number(120.456) == "120.46"
    assert commands.number(99.5) == "99.5"


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_each_builder_is_marked_as_busk_runs_it(name: str) -> None:
    line, text, performance = BUILDERS[name]
    assert line.text == text
    assert line.performance is performance
    first = line.text.split()[0]
    assert (first in PERFORMANCE_WORDS) is performance


def test_busk_accepts_every_builders_line(show: busk.OfflineShow) -> None:
    """With the heads selected, holding a colour (for its components and
    ``by``), and an effect to stop; in the table's order (a preset is
    recorded, merged into, replaced, removed from, renamed, renumbered and
    deleted), ``sel none`` last."""
    assert show.execute("sel group 1").ok  # something to undo and redo, an effect to stop
    assert show.execute('effect add "Circle" id fx5').ok
    assert show.execute("preset color 2").ok
    for name, (line, _, _) in sorted(BUILDERS.items(), key=lambda item: item[0] == "sel none"):
        reply = show.execute(line.text)
        assert reply.ok, (name, reply.text)


def test_the_prefills_are_lines_busk_takes_so_far(show: busk.OfflineShow) -> None:
    assert show.execute("sel group 1").ok
    for line in PREFILLS:
        answer = show.expected(line)
        assert answer.error is None, (line, answer.error)
        assert answer.words or answer.values, line


def test_the_default_quick_lines_run(show: busk.OfflineShow) -> None:
    assert show.execute("sel group 4").ok
    for line in config.QUICK:
        reply = show.execute(line)
        assert reply.ok, (line, reply.text)


@pytest.mark.parametrize(
    ("attribute", "taken"),
    [("intensity", True), ("pan", True), ("tilt", True), ("zoom", True), ("shutter", True),
     ("strobeRate", True), ("iris", False), ("cto", False), ("focus", False)],
)  # fmt: skip
def test_the_heads_take_what_their_profile_says(
    show: busk.OfflineShow, attribute: str, taken: bool
) -> None:
    """The encoders' rows show by profile: the heads take these and refuse
    the others, as ``profile_info`` reads them."""
    assert show.execute("sel group 1").ok
    value = "strobe" if attribute == "shutter" else "0.5"
    assert show.execute(f"set {attribute} {value}").ok is taken


def test_the_whole_prefills_run(show: busk.OfflineShow) -> None:
    assert commands.location_prefill(101, None) == (
        'fixture 101 location {"x": 0, "y": 0, "z": 0, "rx": 0, "ry": 0, "rz": 0}'
    )
    for line in WHOLE_PREFILLS:
        reply = show.execute(line)
        assert reply.ok, (line, reply.text)


def test_every_binding_of_the_show_unbinds_by_its_input(show: busk.OfflineShow) -> None:
    """F9's unbind pre-fill names a binding's input as busk reads it."""
    bindings = show_model(show.show).bindings
    assert len(bindings) > 50
    for binding in bindings:
        line = commands.unbind_prefill(binding.surface, binding.input)
        reply = show.execute(line)
        assert reply.ok, (line, reply.text)
    assert show.show["bindings"] == []


def test_the_families_are_busks() -> None:
    assert dict(attributes.FAMILY_OF) == {
        attribute: definition.family for attribute, definition in ATTRIBUTES.items()
    }
    assert attributes.family_of("color.w") == "color"
    assert attributes.family_of("nothing") is None


def test_the_pools_record_busks_families() -> None:
    assert dict(attributes.POOL_FAMILIES) == dict(POOL_FAMILIES)
    assert sorted(attributes.POOLS) == sorted(POOL_FAMILIES)
    assert sorted(attributes.DEFAULT_SCOPE) == sorted(POOL_FAMILIES)


UNITS = {"normalized": "level", "degrees": "degrees", "hz": "hz", "degPerSec": "degps"}


def test_every_scalar_has_a_row_and_every_discrete_attribute_options() -> None:
    """The PRESET panel's rows: a bar for each of busk's scalars, in its unit
    and under its family; options for each discrete attribute but
    ``control``, in registry order."""
    rows = {
        encoder.attribute: (family, encoder.unit)
        for family, encoders in attributes.ROWS
        for encoder in encoders
    }
    for attribute, definition in ATTRIBUTES.items():
        if definition.kind == "scalar":
            assert rows[attribute] == (definition.family, UNITS[definition.unit]), attribute
    assert all(attributes.family_of(name) == family for name, (family, _) in rows.items())
    discrete = [
        attribute
        for attribute, definition in ATTRIBUTES.items()
        if definition.kind == "discrete" and definition.family != "control"
    ]
    assert list(attributes.DISCRETE) == discrete
    assert all(
        attributes.family_of(attribute) == family
        for family, found in attributes.OPTIONS
        for attribute in found
    )


def test_f2_keeps_its_rows() -> None:
    assert [
        (family, [encoder.attribute for encoder in encoders])
        for family, encoders in attributes.FAMILIES
    ] == [
        ("intensity", ["intensity"]),
        ("position", ["pan", "tilt"]),
        ("color", ["color.r", "color.g", "color.b", "color.w", "cto"]),
        ("beam", ["zoom", "iris", "frost"]),
        ("focus", ["focus"]),
        ("shutter", ["strobeRate"]),
    ]


def test_busk_records_each_pool_at_the_default_scope(club_path: Path) -> None:
    """A record line without a scope: busk stores the values at the scope
    ``DEFAULT_SCOPE`` says. The heads get a focus channel for the focus
    pool (no profile of the show has one)."""
    document, _ = busk.load_show(club_path)
    document = copy.deepcopy(document)
    spot = next(p for p in document["profiles"] if p["name"] == "Generic Spot 16ch")
    for mode in spot["modes"]:
        for channel in mode["channels"]:
            if channel.get("component") == "white":
                del channel["component"]
                channel["attribute"] = "focus"
    show = busk.OfflineShow(document)
    for line in ("sel group 1", "set intensity 50%", "set pan 10", "set color 1 0 0",
                 "set zoom 20", "set focus 50%"):  # fmt: skip
        assert show.execute(line).ok, line
    for number, pool in enumerate(attributes.POOLS, start=11):
        reply = show.execute(f"record preset {pool} {number}")
        assert reply.ok, (pool, reply.text)
        stored = next(p for p in show.show["presets"] if (p["pool"], p["number"]) == (pool, number))
        assert {value["scope"]["kind"] for value in stored["values"]} == {
            attributes.DEFAULT_SCOPE[pool]
        }, pool
