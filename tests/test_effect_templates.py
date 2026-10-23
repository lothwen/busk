"""The effect templates ``effect add`` takes (GAP-15 of ``docs/dev/tui/engine-gaps.md``).

``OfflineShow.effect_templates`` and ``LiveShow.effect_templates`` list
every template ``effect add "<name>"`` takes, as
:class:`~busk.console.console.EffectTemplateInfo`: the show's in show order,
then the effect library's that the show has no copy of, each once, with its
layers in one line and the library's defaults. The contract: ``effect add``
with a listed name uses that template, embeds it exactly when it is the
library's, and gives the instance those defaults. Appendix A's show holds a
copy of the library's Pulse; the variants below rename it, shadow a library
template, and repeat a name.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import pytest

from builders import APPENDIX_A, ROOT, load_doc, show_of
from busk import CounterIds, EffectTemplateInfo, LiveShow, OfflineShow, load_show, new_show
from busk.persistence.show_file import save_show

LIBRARY = ["Circle", "Pulse", "Wave", "Chase", "Saw", "Sweep", "Flicker", "Rainbow"]
SINE = [
    {"attribute": "intensity", "waveform": {"kind": "sine"}, "phaseOffset": 0, "mode": "multiply"}
]
SELECT = "sel fixture 101 thru 102, fixture 201"


def appendix(*templates: dict[str, Any], rename: str | None = None, first: bool = False) -> Any:
    """Appendix A's show, with its Pulse renamed and ``templates`` added
    after it (or before it, ``first``)."""
    doc = load_doc(APPENDIX_A)
    if rename is not None:
        doc["effects"][0]["name"] = rename
    added = [{"layers": SINE, **template} for template in templates]
    doc["effects"] = added + doc["effects"] if first else doc["effects"] + added
    return show_of(doc)


def info(
    name: str, ident: str, source: Literal["show", "library"], summary: str, **defaults: Any
) -> EffectTemplateInfo:
    fields: dict[str, Any] = {"size": None, "low": None, "high": None, "phase": None, **defaults}
    return EffectTemplateInfo(name=name, id=ident, source=source, summary=summary, **fields)


CIRCLE = info("Circle", "ef-circle", "library", "pan add sine, tilt add sine +90°", size=20.0)
PULSE = info("Pulse", "ef-pulse", "show", "intensity multiply sine", size=0.7)
WAVE = info("Wave", "ef-wave", "library", "intensity absolute sine", low=0.0, high=1.0)
CHASE = info("Chase", "ef-chase", "library", "intensity absolute square", phase=(0.0, 360.0))
SAW = info("Saw", "ef-saw", "library", "intensity absolute sawDown", phase=(0.0, 360.0))
SWEEP = info("Sweep", "ef-sweep", "library", "pan add triangle", size=30.0)
FLICKER = info("Flicker", "ef-flicker", "library", "intensity multiply random", size=0.5)
RAINBOW = info("Rainbow", "ef-rainbow", "library", "color fade 3 colours", phase=(0.0, 360.0))
LISTED = (PULSE, CIRCLE, WAVE, CHASE, SAW, SWEEP, FLICKER, RAINBOW)
"""Appendix A's: its Pulse first, then the rest of the library, in its order."""


def names(templates: tuple[EffectTemplateInfo, ...]) -> list[tuple[str, str]]:
    return [(t.name, t.source) for t in templates]


# ----------------------------------------------------------------- the list


def test_a_new_show_lists_the_library_in_its_order() -> None:
    templates = OfflineShow(new_show("Empty")).effect_templates
    assert names(templates) == [(name, "library") for name in LIBRARY]
    assert templates[0] == CIRCLE
    assert templates[-1] == RAINBOW


def test_the_shows_templates_come_first_then_the_librarys_it_has_no_copy_of() -> None:
    assert OfflineShow(show_of(load_doc(APPENDIX_A))).effect_templates == LISTED


def test_the_layers_and_defaults_are_what_library_and_list_effects_print() -> None:
    offline = OfflineShow(appendix({"id": "ef-zap", "name": "Zap"}))
    library = offline.execute("library").text.splitlines()
    for template in offline.effect_templates:
        if template.source == "library" or template.id == "ef-pulse":
            assert f"effect {template.name}: {template.summary}{defaults(template)}" in library
    assert offline.execute("list effects").text.splitlines() == [
        f"{t.name:<20} {t.summary}" for t in offline.effect_templates if t.source == "show"
    ]


def defaults(template: EffectTemplateInfo) -> str:
    """The defaults as ``library`` prints them."""
    parts = [] if template.size is None else [f"size {template.size:g}"]
    bounds = (("low", template.low), ("high", template.high))
    if any(v is not None for _, v in bounds):
        parts.append(" ".join(f"{k} {v:g}" for k, v in bounds if v is not None))
    if template.phase is not None:
        parts.append("phase {:g} {:g}".format(*template.phase))
    return f" ({', '.join(parts)})" if parts else ""


def test_the_club_night_show_holds_the_four_it_uses(tmp_path: Path) -> None:
    show = OfflineShow(new_show("Club Night"), path=tmp_path / "club.show", ids=CounterIds())
    show.run_script(ROOT / "examples" / "club-night.busk")
    assert names(show.effect_templates) == [
        ("Circle", "show"), ("Pulse", "show"), ("Wave", "show"), ("Rainbow", "show"),
        ("Chase", "library"), ("Saw", "library"), ("Sweep", "library"), ("Flicker", "library"),
    ]  # fmt: skip


# ---------------------------------------------------------- which one is listed


def test_a_renamed_copy_of_a_library_template_is_listed_once_by_its_new_name() -> None:
    templates = OfflineShow(appendix(rename="Breathe")).effect_templates
    assert templates[0] == info("Breathe", "ef-pulse", "show", "intensity multiply sine", size=0.7)
    assert [t.name for t in templates] == ["Breathe", *(n for n in LIBRARY if n != "Pulse")]


def test_a_show_template_named_like_a_library_one_takes_its_place() -> None:
    templates = OfflineShow(appendix({"id": "ef-mine", "name": "circle"})).effect_templates
    assert names(templates) == [("Pulse", "show"), ("circle", "show")] + [
        (n, "library") for n in LIBRARY if n not in ("Circle", "Pulse")
    ]
    assert templates[1] == info("circle", "ef-mine", "show", "intensity multiply sine")


ZAPS = ({"id": "ef-zap1", "name": "Zap"}, {"id": "ef-zap2", "name": "ZAP"})
CIRCLING = [
    {"attribute": "pan", "waveform": {"kind": "sine"}, "phaseOffset": 0, "mode": "add"},
    {"attribute": "tilt", "waveform": {"kind": "sine"}, "phaseOffset": 90, "mode": "add"},
]
SPINS = (
    {"id": "ef-spin", "name": "Spin"},
    {"id": "ef-circle", "name": "Spin", "layers": CIRCLING},
)
"""A show template, then the show's copy of the library's Circle renamed
to the same name."""


def test_a_name_an_earlier_template_answers_to_is_not_listed_again() -> None:
    templates = OfflineShow(appendix(*ZAPS)).effect_templates
    assert [t.id for t in templates if t.source == "show"] == ["ef-pulse", "ef-zap1"]


def test_a_template_is_listed_under_the_first_name_that_finds_it() -> None:
    """``effect add "Spin"`` takes the first Spin, ``effect add "Circle"``
    the show's copy of Circle, renamed Spin."""
    templates = OfflineShow(appendix(*SPINS, first=True)).effect_templates
    assert [(t.name, t.id) for t in templates if t.source == "show"] == [
        ("Spin", "ef-spin"),
        ("Pulse", "ef-pulse"),
        ("Circle", "ef-circle"),
    ]
    assert templates[2] == info("Circle", "ef-circle", "show", CIRCLE.summary, size=20.0)


def test_an_own_template_named_like_the_library_one_a_renamed_copy_holds() -> None:
    """``effect add "Pulse"`` takes the show's copy of the library's Pulse,
    whatever its name, unless an earlier template answers to the name."""
    after = OfflineShow(appendix({"id": "ef-mine", "name": "Pulse"}, rename="Breathe"))
    assert [(t.name, t.id) for t in after.effect_templates if t.source == "show"] == [
        ("Breathe", "ef-pulse")
    ]
    before = OfflineShow(appendix({"id": "ef-mine", "name": "Pulse"}, rename="Breathe", first=True))
    assert [(t.name, t.id) for t in before.effect_templates if t.source == "show"] == [
        ("Pulse", "ef-mine"),
        ("Breathe", "ef-pulse"),
    ]


# ------------------------------------------------------------- the contract

MINE = {"id": "ef-mine", "name": "Pulse"}
SHOWS: dict[str, Callable[[], Any]] = {
    "appendix": lambda: show_of(load_doc(APPENDIX_A)),
    "renamed": lambda: appendix(rename="Breathe"),
    "shadowed": lambda: appendix({"id": "ef-mine", "name": "circle"}),
    "repeated": lambda: appendix(*ZAPS),
    "taken name": lambda: appendix(*SPINS, first=True),
    "own first": lambda: appendix(MINE, rename="Breathe", first=True),
    "own after": lambda: appendix(MINE, rename="Breathe"),
}


@pytest.mark.parametrize("variant", SHOWS)
def test_effect_add_takes_each_listed_name_as_listed(variant: str) -> None:
    for template in OfflineShow(SHOWS[variant]()).effect_templates:
        offline = OfflineShow(SHOWS[variant]())
        before = [t["id"] for t in offline.show["effects"]]
        offline.execute(SELECT)
        reply = offline.execute(f'effect add "{template.name}"')
        assert reply.ok, (template, reply.text)
        instance = offline.programmer.effects[-1]
        assert instance["templateId"] == template.id
        assert instance["size"] == (1 if template.size is None else template.size)
        assert instance.get("low") == template.low
        assert instance.get("high") == template.high
        phase = (instance["phase"]["start"], instance["phase"]["end"])
        assert phase == (template.phase or (0, 0))
        embedded = [] if template.source == "show" else [template.id]
        assert [t["id"] for t in offline.show["effects"]] == before + embedded


def test_adding_a_library_template_makes_it_the_shows() -> None:
    offline = OfflineShow(show_of(load_doc(APPENDIX_A)))
    offline.execute(SELECT)
    offline.execute('effect add "Rainbow" hz 1 size 0.5')  # options change the instance only
    templates = offline.effect_templates
    assert names(templates[:3]) == [("Pulse", "show"), ("Rainbow", "show"), ("Circle", "library")]
    assert templates[1] == info(
        "Rainbow", "ef-rainbow", "show", "color fade 3 colours", phase=(0.0, 360.0)
    )
    offline.execute("undo")  # the instance
    assert offline.effect_templates == templates
    offline.execute("undo")  # the embedding
    assert offline.effect_templates == LISTED


def test_a_template_the_show_makes_is_listed_with_no_defaults() -> None:
    offline = OfflineShow(show_of(load_doc(APPENDIX_A)))
    layer = (
        '{"attribute": "pan", "waveform": {"kind": "triangle"}, "phaseOffset": 90, "mode": "add"}'
    )
    assert offline.execute(f'effect template add "Zap" [{layer}]').ok
    ident = offline.show["effects"][1]["id"]
    zap = info("Zap", ident, "show", "pan add triangle +90°")
    assert offline.effect_templates == (PULSE, zap, *LISTED[1:])


# -------------------------------------------------------------- the reads


def test_the_same_tuple_until_a_template_changes() -> None:
    offline = OfflineShow(show_of(load_doc(APPENDIX_A)))
    first = offline.effect_templates
    assert offline.effect_templates is first
    offline.execute("fader 1 1")  # no edit
    assert offline.effect_templates is first
    shown = offline.show
    offline.execute("sel fixture 101")
    offline.execute('record group 7 "Seven"')  # an edit that leaves the templates as they were
    assert offline.show is not shown
    assert offline.effect_templates is first
    offline.execute('effect add "Circle"')
    assert offline.effect_templates is not first
    assert offline.effect_templates != first


def test_a_live_show_lists_them_before_it_starts_and_from_another_thread() -> None:
    live = LiveShow(show_of(load_doc(APPENDIX_A)), output=False)
    assert live.effect_templates == LISTED
    with live:
        assert live.execute(SELECT).ok
        assert live.execute('effect add "Chase"').ok
        read: list[tuple[EffectTemplateInfo, ...]] = []
        reader = threading.Thread(target=lambda: read.append(live.effect_templates))
        reader.start()
        reader.join()
    assert names(read[0])[:2] == [("Pulse", "show"), ("Chase", "show")]
    assert read[0] is live.effect_templates


def test_a_saved_show_lists_the_same_after_loading(tmp_path: Path) -> None:
    offline = OfflineShow(show_of(load_doc(APPENDIX_A)))
    offline.execute(SELECT)
    offline.execute('effect add "Sweep"')
    path = tmp_path / "saved.show"
    save_show(offline.show, path)
    loaded, _ = load_show(path)
    assert OfflineShow(loaded).effect_templates == offline.effect_templates
