"""The effect template library (phase-5-plan §5.12): loading and its
problems, lookups, and every built-in template on Appendix A's rig."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from builders import APPENDIX_A, load_doc, state_of
from busk.compiler.cues import CueCompiler
from busk.console.parser import Context, Submit, SubmitAll, parse
from busk.model.validate import validate_effect, validate_show
from busk.session.ids import CounterIds
from busk.session.library import EffectLibrary, ProfileLibrary
from busk.session.programmer import Programmer

NAMES = ["Circle", "Pulse", "Wave", "Chase", "Saw", "Sweep", "Flicker", "Rainbow"]
HEADS = ({"fixtureId": "fx-mh1", "element": 0}, {"fixtureId": "fx-mh2", "element": 0})


def item(ident: str, name: str, **defaults: Any) -> dict[str, Any]:
    """A library item: a pan sweep template and its defaults."""
    layer = {"attribute": "pan", "waveform": {"kind": "triangle"}, "phaseOffset": 0, "mode": "add"}
    return {"template": {"id": ident, "name": name, "layers": [layer]}, "defaults": defaults}


def test_the_builtin_library_loads_every_template() -> None:
    library = EffectLibrary()
    assert library.problems == []
    assert [effect.template["name"] for effect in library] == NAMES
    assert len(library) == 8


def test_templates_are_found_by_id_or_by_name_ignoring_case() -> None:
    library = EffectLibrary()
    circle = library.get("ef-circle")
    assert circle is not None
    assert library.find("CIRCLE") is circle
    assert library.find("ef-circle") is circle
    assert (library.get("Circle"), library.find("Square")) == (None, None)
    assert circle.defaults == {"size": 20}


def test_bad_items_are_skipped_and_reported(tmp_path: Path) -> None:
    empty = item("ef-b", "Empty")
    empty["template"]["layers"] = []
    items = [
        item("ef-a", "Swing", size=10),
        empty,
        item("ef-a", "Again"),  # the id of an item already loaded
        item("ef-c", "SWING"),  # the name, in another case
        item("ef-d", "Big", size="big"),
        item("ef-e", "Half", phase={"start": 0}),
        {"template": item("ef-f", "Odd")["template"]},  # no defaults
        [1],
    ]
    path = tmp_path / "effects.json"
    path.write_text(json.dumps(items))
    library = EffectLibrary([path], builtin=False)
    assert [effect.template["id"] for effect in library] == ["ef-a"]
    assert library.problems == [
        f"{path}[1]: template.layers: An effect template needs at least one layer",
        f"{path}[2]: template id 'ef-a' is already loaded",
        f"{path}[3]: template name 'SWING' is already loaded",
        f"{path}[4]: defaults.size: Input should be a valid number",
        f"{path}[5]: defaults.phase.end: Field required",
        f'{path}[6]: expected {{"template": {{…}}, "defaults": {{…}}}}',
        f'{path}[7]: expected {{"template": {{…}}, "defaults": {{…}}}}',
    ]


def test_unreadable_files_are_reported(tmp_path: Path) -> None:
    broken, scalar, missing = tmp_path / "a.json", tmp_path / "b.json", tmp_path / "c.json"
    broken.write_text("[")
    scalar.write_text("{}")
    library = EffectLibrary([broken, scalar, missing], builtin=False)
    assert len(library) == 0
    assert [problem.split(": ", 1)[0] for problem in library.problems] == [
        str(broken),
        str(scalar),
        str(missing),
    ]
    assert library.problems[1] == f"{scalar}: expected a list of effect templates"


@pytest.mark.parametrize("name", NAMES)
def test_every_library_template_validates_and_compiles_on_appendix_a(name: str) -> None:
    """The console's instance of each template, on the two moving heads,
    with every default (BPM ×1 on Speed 1)."""
    doc = load_doc(APPENDIX_A)
    state = state_of(doc)
    context = Context(
        state.show, ProfileLibrary(), CounterIds(), programmer=Programmer(selection=HEADS)
    )
    action = parse(f'effect add "{name}"', context)
    if isinstance(action, SubmitAll):
        embedding, adding = action.commands
        doc["effects"].append(embedding["value"])  # type: ignore[typeddict-item]
    else:
        assert isinstance(action, Submit)  # Appendix A embeds the library's Pulse
        adding = action.command
    instance = adding["effect"]  # type: ignore[typeddict-item]
    show, issues = validate_show(json.dumps(doc))
    assert show is not None
    assert issues == []
    assert validate_effect(show, instance) == []
    state = state_of(doc)
    compiler = CueCompiler(state.show, state.compiled.slots)
    assert compiler.effect(instance, "programmer.effects[0]") is not None
    assert compiler.warnings == []
