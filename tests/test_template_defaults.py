"""A template's defaults (GAP-51 of ``docs/dev/tui/engine-gaps.md``).

``effect template defaults "<name>" <what effect add takes but the id>`` sets
what ``effect add`` starts a new instance of the template from, all at once,
and ``none`` takes them away. A line's own words win. Embedding a library
template copies the library's defaults; a copy embedded before GAP-51 holds
none, and takes the library's. A master the defaults name counts as a use,
and ``delete master`` refuses it.

The rig below has three pars in a group, a speed master and a size master,
and a template of its own, ``Beat``, with one multiply layer.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from builders import APPENDIX_A, ROOT, load_doc, show_of
from busk import CounterIds, EffectTemplateInfo, LiveShow, OfflineShow, load_show, new_show
from busk.console.parser import Context, SubmitAll, parse
from busk.model.validate import validate_show
from busk.persistence.show_file import save_show
from busk.session.library import EffectLibrary, ProfileLibrary
from busk.session.programmer import Programmer

BEAT = [
    {"attribute": "intensity", "waveform": {"kind": "sine"}, "phaseOffset": 0, "mode": "multiply"}
]
BASE = {
    "direction": "forward",
    "size": 1,
    "phase": {"start": 0, "end": 0},
    "groups": 1,
    "blocks": 1,
    "wings": 1,
}
"""What ``effect add`` gives an instance where neither line nor defaults say."""


def run(show: OfflineShow, *lines: str) -> list[str]:
    replies = []
    for line in lines:
        reply = show.execute(line)
        assert reply.ok, (line, reply.text)
        replies.append(reply.text)
    return replies


def said(show: OfflineShow, line: str) -> str:
    """The reply to ``line``, which must be refused."""
    reply = show.execute(line)
    assert not reply.ok, (line, reply.text)
    return reply.text


@pytest.fixture
def rig() -> OfflineShow:
    show = OfflineShow(new_show("Rig"))
    run(
        show,
        'universe add 1 "Stage"',
        'fixture add 1 thru 3 "RGB Par 3ch" mode 3ch at 1.1',
        "sel fixture 1 thru 3",
        'record group 1 "Pars"',
        'master add speed "Tempo"',
        'master add size "FX"',
        f'effect template add "Beat" {json.dumps(BEAT)}',
    )
    return show


def template(show: OfflineShow, name: str) -> dict[str, Any]:
    return dict(next(t for t in show.show["effects"] if t["name"] == name))


def master_id(show: OfflineShow, name: str) -> str:
    return str(next(m["id"] for m in show.show["masters"] if m["name"] == name))


def added(show: OfflineShow, line: str) -> dict[str, Any]:
    """The instance ``line`` (an ``effect add``) puts in the programmer, less
    its id, template and targets."""
    run(show, line)
    instance = dict(show.programmer.effects[-1])
    for key in ("id", "templateId", "targets"):
        del instance[key]
    return instance


def info(show: OfflineShow, name: str) -> EffectTemplateInfo:
    return next(t for t in show.effect_templates if t.name == name)


# ------------------------------------------------------------- the line


def test_the_line_sets_every_default_in_an_instances_order(rig: OfflineShow) -> None:
    reply = run(
        rig,
        'effect template defaults "Beat" speedmaster "Tempo" fadein 2 bounce wings 2 blocks 3 '
        'groups 4 phase 0 180 low 0.1 high 0.9 size 0.5 sizemaster "FX" hz 2',
    )
    assert reply == [
        "set the defaults of effect template 'Beat': hz 2, size 0.5, low 0.1 high 0.9, "
        'phase 0 180, groups 4, blocks 3, wings 2, bounce, fadein 2, sizemaster "FX", '
        'speedmaster "Tempo"'
    ]
    defaults = template(rig, "Beat")["defaults"]
    assert list(defaults) == [
        "rate", "direction", "size", "low", "high", "phase", "groups", "blocks", "wings",
        "sizeFadeIn", "sizeMasterId", "speedMasterId",
    ]  # fmt: skip
    assert defaults["rate"] == {"kind": "hz", "value": 2}
    assert defaults["sizeMasterId"] == master_id(rig, "FX")
    assert defaults["speedMasterId"] == master_id(rig, "Tempo")


def test_the_line_sets_them_all_at_once(rig: OfflineShow) -> None:
    run(
        rig,
        'effect template defaults "Beat" size 0.5 groups 2',
        'effect template defaults "Beat" hz 3',
    )
    assert template(rig, "Beat")["defaults"] == {"rate": {"kind": "hz", "value": 3}}


def test_a_beat_rate_names_its_master_and_its_multiplier(rig: OfflineShow) -> None:
    tempo = master_id(rig, "Tempo")
    assert run(rig, 'effect template defaults "Beat" bpm x 0.5') == [
        "set the defaults of effect template 'Beat': bpm \"Tempo\" x 0.5"
    ]
    assert template(rig, "Beat")["defaults"]["rate"] == {
        "kind": "bpm", "masterId": tempo, "multiplier": 0.5,
    }  # fmt: skip
    assert run(rig, 'effect template defaults "Beat" bpm "tempo"') == [
        "set the defaults of effect template 'Beat': bpm \"Tempo\""
    ]


def test_list_effects_and_effect_templates_show_them(rig: OfflineShow) -> None:
    run(
        rig,
        'effect template defaults "Beat" bpm x 2 size 0.5 phase 0 360 reverse fadein 1 '
        'sizemaster "FX" speedmaster "Tempo"',
    )
    assert run(rig, "list effects") == [
        'Beat                 intensity multiply sine (bpm "Tempo" x 2, size 0.5, phase 0 360, '
        'reverse, fadein 1, sizemaster "FX", speedmaster "Tempo")'
    ]
    beat = info(rig, "Beat")
    assert (beat.source, beat.size, beat.phase, beat.direction, beat.fadeIn) == (
        "show", 0.5, (0.0, 360.0), "reverse", 1.0,
    )  # fmt: skip
    assert (beat.hz, beat.bpm, beat.sizeMaster, beat.speedMaster) == (
        None, ("Tempo", 2.0), "FX", "Tempo",
    )  # fmt: skip
    assert (beat.low, beat.high, beat.groups, beat.blocks, beat.wings) == (None,) * 5
    run(rig, 'effect template defaults "Beat" hz 0.25 low 0 high 1 groups 2 blocks 3 wings 4')
    beat = info(rig, "Beat")
    assert (beat.hz, beat.bpm, beat.low, beat.high) == (0.25, None, 0.0, 1.0)
    assert (beat.groups, beat.blocks, beat.wings, beat.direction) == (2, 3, 4, None)


def test_a_renamed_master_is_named_by_its_new_name(rig: OfflineShow) -> None:
    run(rig, 'effect template defaults "Beat" sizemaster "FX"', 'rename master "FX" "Size"')
    assert run(rig, "list effects") == [
        'Beat                 intensity multiply sine (sizemaster "Size")'
    ]
    assert info(rig, "Beat").sizeMaster == "Size"


def test_a_template_without_defaults_says_nothing_more(rig: OfflineShow) -> None:
    assert run(rig, "list effects") == ["Beat                 intensity multiply sine"]
    beat = info(rig, "Beat")
    assert (beat.size, beat.hz, beat.bpm, beat.direction, beat.sizeMaster) == (None,) * 5


def test_each_change_is_one_undo_step(rig: OfflineShow) -> None:
    before = copy.deepcopy(rig.show)
    run(rig, 'effect template defaults "Beat" size 0.5', 'effect template defaults "Beat" none')
    assert "defaults" not in template(rig, "Beat")
    assert run(rig, "undo") == ["undid: removed the defaults of effect template 'Beat'"]
    assert template(rig, "Beat")["defaults"] == {"size": 0.5}
    run(rig, "undo")
    assert rig.show == before
    run(rig, "redo")
    assert template(rig, "Beat")["defaults"] == {"size": 0.5}


# ---------------------------------------------------------- effect add


def test_effect_add_starts_from_the_defaults(rig: OfflineShow) -> None:
    run(
        rig,
        'effect template defaults "Beat" hz 2 size 0.5 low 0.1 high 0.9 phase 0 180 groups 2 '
        'blocks 3 wings 2 bounce fadein 1.5 sizemaster "FX" speedmaster "Tempo"',
        "sel group 1",
    )
    assert added(rig, 'effect add "Beat"') == {
        "rate": {"kind": "hz", "value": 2},
        "direction": "bounce",
        "size": 0.5,
        "low": 0.1,
        "high": 0.9,
        "phase": {"start": 0, "end": 180},
        "groups": 2,
        "blocks": 3,
        "wings": 2,
        "sizeFadeIn": 1.5,
        "sizeMasterId": master_id(rig, "FX"),
        "speedMasterId": master_id(rig, "Tempo"),
    }


@pytest.mark.parametrize(
    ("words", "changed"),
    [
        ("hz 4", {"rate": {"kind": "hz", "value": 4}}),
        ("bpm x 2", {"rate": {"kind": "bpm", "masterId": "Tempo", "multiplier": 2}}),
        ("forward", {"direction": "forward"}),
        ("size 0.25", {"size": 0.25}),
        ("low 0 high 0.5", {"low": 0, "high": 0.5}),
        ("phase 90 90", {"phase": {"start": 90, "end": 90}}),
        ("groups 5", {"groups": 5}),
        ("blocks 1", {"blocks": 1}),
        ("wings 3", {"wings": 3}),
        ("fadein 0", {"sizeFadeIn": 0}),
    ],
)
def test_a_lines_own_words_win(rig: OfflineShow, words: str, changed: dict[str, Any]) -> None:
    run(
        rig,
        'effect template defaults "Beat" hz 2 size 0.5 low 0.1 high 0.9 phase 0 180 groups 2 '
        "blocks 3 wings 2 bounce fadein 1.5",
        "sel group 1",
    )
    kept = added(rig, 'effect add "Beat"')
    if "rate" in changed and changed["rate"]["kind"] == "bpm":
        changed = {"rate": {**changed["rate"], "masterId": master_id(rig, "Tempo")}}
    assert added(rig, f'effect add "Beat" {words}') == kept | changed


def test_a_master_named_on_the_line_wins_over_the_defaults(rig: OfflineShow) -> None:
    run(rig, 'master add size "Other"', 'effect template defaults "Beat" sizemaster "FX"', "sel 1")
    assert added(rig, 'effect add "Beat" sizemaster "Other"')["sizeMasterId"] == master_id(
        rig, "Other"
    )


def test_without_defaults_effect_add_gives_busks_own(rig: OfflineShow) -> None:
    run(rig, "sel group 1")
    rate = {"kind": "bpm", "masterId": master_id(rig, "Tempo"), "multiplier": 1}
    assert added(rig, 'effect add "Beat"') == {"rate": rate, **BASE}
    run(rig, 'effect template defaults "Beat" size 0.5', 'effect template defaults "Beat" none')
    assert added(rig, 'effect add "Beat"') == {"rate": rate, **BASE}


def test_an_effect_does_not_share_the_templates_dicts(rig: OfflineShow) -> None:
    run(rig, 'effect template defaults "Beat" hz 2 phase 0 90', "sel 1", 'effect add "Beat"')
    effect = rig.programmer.effects[-1]
    defaults = template(rig, "Beat")["defaults"]
    assert effect["rate"] == defaults["rate"]
    assert effect["rate"] is not defaults["rate"]
    assert effect["phase"] is not defaults["phase"]


# ------------------------------------------------------------- none


def test_none_takes_a_templates_own_defaults_away(rig: OfflineShow) -> None:
    run(rig, 'effect template defaults "Beat" size 0.5')
    assert run(rig, 'effect template defaults "Beat" none') == [
        "removed the defaults of effect template 'Beat'"
    ]
    assert "defaults" not in template(rig, "Beat")
    assert said(rig, 'effect template defaults "Beat" none') == (
        "error: effect template 'Beat' has no defaults"
    )


def test_none_on_a_copy_of_a_library_template_leaves_empty_defaults(rig: OfflineShow) -> None:
    run(rig, "sel group 1", 'effect add "Circle"', "effect clear")
    assert template(rig, "Circle")["defaults"] == {"size": 20}
    run(rig, 'effect template defaults "Circle" none')
    assert template(rig, "Circle")["defaults"] == {}  # else the library's would come back
    assert added(rig, 'effect add "Circle"')["size"] == 1
    assert run(rig, "list effects")[0].endswith(
        "Circle               pan add sine, tilt add sine +90°"
    )
    assert said(rig, 'effect template defaults "Circle" none') == (
        "error: effect template 'Circle' has no defaults"
    )


# ------------------------------------------------------- the library


def test_embedding_a_library_template_copies_its_defaults(rig: OfflineShow) -> None:
    run(rig, "sel group 1")
    assert added(rig, 'effect add "Alternate"')["groups"] == 2
    assert template(rig, "Alternate")["defaults"] == {
        "phase": {"start": 0, "end": 360}, "groups": 2,
    }  # fmt: skip
    assert template(rig, "Alternate")["layers"] == next(
        effect.template["layers"]
        for effect in EffectLibrary()
        if effect.template["name"] == "Alternate"
    )


def test_a_copys_defaults_are_its_own_once_embedded(rig: OfflineShow) -> None:
    run(rig, "sel group 1", 'effect add "Circle"', 'effect template defaults "Circle" size 5')
    assert added(rig, 'effect add "Circle"')["size"] == 5
    assert info(rig, "Circle").size == 5
    run(rig, "undo", "undo", "undo")  # the second effect, the defaults, the first effect
    assert template(rig, "Circle")["defaults"] == {"size": 20}
    run(rig, "undo")
    assert not any(t["name"] == "Circle" for t in rig.show["effects"])


def test_a_copy_embedded_before_gap_51_takes_the_librarys() -> None:
    # Appendix A embeds the library's Pulse with no defaults of its own.
    show = OfflineShow(show_of(load_doc(APPENDIX_A)))
    assert "defaults" not in template(show, "Pulse")
    assert info(show, "Pulse").size == 0.7
    assert run(show, "list effects") == ["Pulse                intensity multiply sine (size 0.7)"]
    run(show, "sel group 2")
    assert added(show, 'effect add "Pulse"')["size"] == 0.7
    run(show, 'effect template defaults "Pulse" size 0.3')
    assert added(show, 'effect add "Pulse"')["size"] == 0.3


def test_a_library_template_the_show_has_no_copy_of_is_refused(rig: OfflineShow) -> None:
    assert said(rig, 'effect template defaults "Circle" size 5') == (
        "error: template 'Circle' is the library's: the show has no copy"
    )


def write(path: Path, *items: Any) -> Path:
    path.write_text(json.dumps(list(items)), encoding="utf-8")
    return path


SINE = {"id": "ef-x", "name": "X", "layers": BEAT}
PROGRAMMER = Programmer(selection=({"fixtureId": "fx-par1", "element": 0},))


@pytest.mark.parametrize(
    ("defaults", "problem"),
    [
        ({"rate": {"kind": "bpm", "masterId": "m", "multiplier": 1}}, "name no master"),
        ({"sizeMasterId": "m"}, "name no master"),
        ({"speedMasterId": "m"}, "name no master"),
        ({"size": 2}, "defaults.size: An effect with a multiply layer needs a size within 0..1"),
        (
            {"rate": {"kind": "hz", "value": 0}},
            "defaults.rate.value: A rate must be greater than 0",
        ),
        ({"groups": 0}, "defaults.groups: Input should be greater than or equal to 1"),
    ],
)
def test_a_library_template_s_defaults_are_checked(
    tmp_path: Path, defaults: dict[str, Any], problem: str
) -> None:
    library = EffectLibrary([write(tmp_path / "fx.json", {"template": SINE, "defaults": defaults})])
    assert library.get("ef-x") is None
    assert len(library.problems) == 1
    assert problem in library.problems[0], library.problems


def test_a_library_template_s_defaults_go_beside_it(tmp_path: Path) -> None:
    item = {"template": {**SINE, "defaults": {"size": 0.5}}, "defaults": {}}
    library = EffectLibrary([write(tmp_path / "fx.json", item)])
    assert library.get("ef-x") is None
    assert "template.defaults: a library template's defaults go beside it" in library.problems[0]


def test_a_library_template_takes_a_rate_and_a_direction(tmp_path: Path) -> None:
    defaults = {"rate": {"kind": "hz", "value": 0.5}, "direction": "bounce", "sizeFadeIn": 2}
    library = EffectLibrary(
        [write(tmp_path / "fx.json", {"template": SINE, "defaults": defaults})], builtin=False
    )
    assert library.problems == []
    show = show_of(load_doc(APPENDIX_A))
    context = Context(show, ProfileLibrary(), CounterIds(), effects=library, programmer=PROGRAMMER)
    action = parse('effect add "X"', context)
    assert isinstance(action, SubmitAll)
    embed, add = (dict(command) for command in action.commands)
    assert embed["value"] == {**SINE, "defaults": defaults}
    effect = add["effect"]
    assert (effect["rate"], effect["direction"], effect["sizeFadeIn"]) == (
        {"kind": "hz", "value": 0.5}, "bounce", 2,
    )  # fmt: skip


# -------------------------------------------------------------- masters


@pytest.mark.parametrize("words", ['bpm "Tempo"', 'speedmaster "Tempo"', 'sizemaster "FX"'])
def test_delete_master_refuses_a_master_the_defaults_name(rig: OfflineShow, words: str) -> None:
    run(rig, f'effect template defaults "Beat" {words}')
    name = "FX" if "FX" in words else "Tempo"
    for line in (f'delete master "{name}"', f'delete master "{name}" cascade'):
        assert said(rig, line) == (
            f'error: master "{name}" is used by the defaults of effect template "Beat": '
            "change them first"
        )
    run(rig, 'effect template defaults "Beat" none', f'delete master "{name}"')


def test_the_refusal_names_every_template_and_the_other_uses(rig: OfflineShow) -> None:
    run(
        rig,
        'effect template add "Wobble" [{"attribute": "intensity", "waveform": {"kind": "sine"}, '
        '"phaseOffset": 0, "mode": "multiply"}]',
        'effect template defaults "Beat" sizemaster "FX"',
        'effect template defaults "Wobble" sizemaster "FX"',
        "sel 1",
        'effect add "Beat" hz 1 sizemaster "FX"',
    )
    assert said(rig, 'delete master "FX"') == (
        'error: master "FX" is used by the defaults of effect templates "Beat", "Wobble" and the '
        "programmer: change them first"
    )


def test_a_template_whose_defaults_name_a_master_may_go(rig: OfflineShow) -> None:
    run(rig, 'effect template defaults "Beat" sizemaster "FX"')
    assert run(rig, 'effect template delete "Beat"') == ["deleted effect template 'Beat'"]
    run(rig, 'delete master "FX"')


def test_with_several_speed_masters_a_beat_rate_names_one(rig: OfflineShow) -> None:
    run(rig, 'master add speed "Other"')
    assert said(rig, 'effect template defaults "Beat" bpm x 2') == (
        "error: several speed masters: name one"
    )
    run(rig, 'effect template defaults "Beat" bpm "Other" x 2')
    assert template(rig, "Beat")["defaults"]["rate"]["masterId"] == master_id(rig, "Other")


# ------------------------------------------------------------- refusals


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ('effect template defaults "Beat"', "expected effect add's options but id, or none"),
        (
            'effect template defaults "Beat" id fx9 size 0.5',
            "expected effect add's options but id, or none, got 'id'",
        ),
        ('effect template defaults "Beat" size 0.5 id fx9', "unexpected 'id'"),
        ('effect template defaults "Beat" size 0.5 size 0.4', "unexpected 'size'"),
        ('effect template defaults "Beat" hz 1 bpm', "unexpected 'bpm'"),
        ('effect template defaults "Beat" forward bounce', "unexpected 'bounce'"),
        ('effect template defaults "Beat" none size 1', "unexpected 'size'"),
        ('effect template defaults "Beat" hz 0', "expected a rate above 0 Hz, got '0'"),
        ('effect template defaults "Beat" hz -1', "expected a rate above 0 Hz, got '-1'"),
        ('effect template defaults "Beat" bpm x 0', "expected a multiplier above 0, got '0'"),
        ('effect template defaults "Beat" size -1', "expected a size of 0 or more, got '-1'"),
        ('effect template defaults "Beat" groups 0', "expected a number of groups from 1, got '0'"),
        ('effect template defaults "Beat" blocks 0', "expected a number of blocks from 1, got '0'"),
        ('effect template defaults "Beat" wings -2', "expected a number of wings from 1, got '-2'"),
        (
            'effect template defaults "Beat" size 2',
            "effect template 'Beat' has a multiply layer: expected a size within 0..1, got 2",
        ),
        (
            'effect template defaults "Beat" fadein -1',
            "expected a fade-in time in seconds, got '-1'",
        ),
        ('effect template defaults "Beat" sizemaster "Tempo"', "no size master 'Tempo'"),
        (
            'effect template defaults "Nope" size 1',
            "no template 'Nope' in the show (see 'list effects')",
        ),
    ],
)
def test_a_wrong_line_is_refused_in_words(rig: OfflineShow, line: str, error: str) -> None:
    before = copy.deepcopy(rig.show)
    assert said(rig, line) == f"error: {error}"
    assert rig.show == before


@pytest.mark.parametrize(
    ("words", "error"),
    [
        ("hz 0", "expected a rate above 0 Hz, got '0'"),
        ("bpm x -1", "expected a multiplier above 0, got '-1'"),
        ("size -0.5", "expected a size of 0 or more, got '-0.5'"),
        ("groups 0", "expected a number of groups from 1, got '0'"),
        ("blocks 0", "expected a number of blocks from 1, got '0'"),
        ("wings 0", "expected a number of wings from 1, got '0'"),
    ],
)
def test_effect_add_refuses_the_same_values_in_words(
    rig: OfflineShow, words: str, error: str
) -> None:
    run(rig, "sel group 1")
    assert said(rig, f'effect add "Beat" {words}') == f"error: {error}"
    assert rig.programmer.effects == ()


def test_tab_offers_the_line_and_its_options(rig: OfflineShow) -> None:
    assert "defaults" in rig.expected("effect template ").words
    assert rig.expected("effect template defaults ").words == ('"Beat"',)
    words = rig.expected('effect template defaults "Beat" ').words
    assert words[0] == "none"
    assert "id" not in words
    assert {"hz", "bpm", "size", "fadein", "sizemaster"} <= set(words)
    after = rig.expected('effect template defaults "Beat" size 0.5 ').words
    assert "none" not in after
    assert "size" in after


# ------------------------------------------------------- the show file


def test_defaults_save_and_load(rig: OfflineShow, tmp_path: Path) -> None:
    run(rig, 'effect template defaults "Beat" bpm x 2 size 0.5 sizemaster "FX" reverse')
    path = tmp_path / "rig.show"
    save_show(rig.show, path)
    reloaded, issues = load_show(path)
    assert not [issue for issue in issues if issue.severity == "error"]
    assert template(OfflineShow(reloaded), "Beat")["defaults"] == template(rig, "Beat")["defaults"]


@pytest.mark.parametrize(
    ("defaults", "error"),
    [
        ({"sizeMasterId": "m-nope"}, "effects[0].defaults.sizeMasterId: Unknown master 'm-nope'"),
        ({"speedMasterId": "FX"}, "effects[0].defaults.speedMasterId:"),
        (
            {"rate": {"kind": "bpm", "masterId": "FX", "multiplier": 1}},
            "effects[0].defaults.rate.masterId:",
        ),
        ({"rate": {"kind": "hz", "value": -1}}, "effects[0].defaults.rate.value:"),
        ({"size": 1.5}, "effects[0].defaults.size: An effect with a multiply layer"),
        ({"groups": 0}, "effects[0].defaults.groups"),
        ({"direction": "random"}, "effects[0].defaults.direction"),
        ({"id": "fx1"}, "effects[0].defaults.id"),
    ],
)
def test_the_validator_checks_a_show_files_defaults(
    rig: OfflineShow, defaults: dict[str, Any], error: str
) -> None:
    doc = json.loads(json.dumps(rig.show))
    masters = {m["name"]: m["id"] for m in doc["masters"]}
    text = json.dumps(defaults).replace('"FX"', json.dumps(masters["FX"]))
    doc["effects"][0]["defaults"] = json.loads(text)
    _show, issues = validate_show(json.dumps(doc))
    errors = [str(issue) for issue in issues if issue.severity == "error"]
    assert any(found.startswith(error) for found in errors), errors


def test_a_show_file_of_today_loads() -> None:
    show, issues = validate_show(APPENDIX_A.read_text(encoding="utf-8"))
    assert show is not None
    assert not [i for i in issues if i.severity == "error"]
    assert all("defaults" not in t for t in show["effects"])


def test_the_club_show_s_templates_hold_the_librarys_defaults(tmp_path: Path) -> None:
    show = OfflineShow(new_show("Club Night"), path=tmp_path / "club.show")
    show.run_script(ROOT / "examples" / "club-night.busk")
    assert {t["name"]: t.get("defaults") for t in show.show["effects"]} == {
        "Circle": {"size": 20},
        "Pulse": {"size": 0.7},
        "Wave": {"low": 0, "high": 1},
        "Rainbow": {"phase": {"start": 0, "end": 360}},
    }


# ------------------------------------------------------ a running show


def eventually(condition: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_a_running_show_adds_an_effect_from_its_templates_defaults(rig: OfflineShow) -> None:
    with LiveShow(rig.show, output=False) as live:
        for line in ('effect template defaults "Beat" hz 4 size 0.5 bounce', "sel group 1"):
            assert live.execute(line).ok, line
        assert live.execute('effect add "Beat"').ok

        def running() -> list[tuple[str, float]]:
            snapshot = live.effects
            return [] if snapshot is None else [(e.id, e.hz) for e in snapshot.effects]

        eventually(lambda: running() == [("fx1", 4.0)])
        effect = live.programmer.effects[0]
        assert (effect["size"], effect["direction"]) == (0.5, "bounce")
        assert live.effect_templates[0].hz == 4.0
        assert live.execute("undo").ok
        assert live.execute("undo").ok
        assert live.execute("undo").ok
        assert live.show == rig.show
