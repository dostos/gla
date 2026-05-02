from pathlib import Path
import pytest
from gpa.eval.scenario_metadata import Scenario, Source, Taxonomy, Backend


def test_scenario_dataclass_minimum():
    s = Scenario(
        path=Path("/tmp/x"),
        slug="godot_86493_world_environment_glow",
        round="r96fdc7",
        mined_at="2026-04-21",
        source=Source(type="github_issue", url="https://github.com/godotengine/godot/issues/86493",
                      repo="godotengine/godot", issue_id=86493),
        taxonomy=Taxonomy(category="native-engine", framework="godot",
                          bug_class="framework-internal"),
        backend=Backend(api="vulkan", status="not-yet-reproduced"),
        status="drafted",
        tags=[],
        notes="",
    )
    assert s.slug == "godot_86493_world_environment_glow"


def test_validate_unknown_category_rejected(tmp_path):
    from gpa.eval.scenario_metadata import validate_scenario, Scenario, Source, Taxonomy, Backend
    s = Scenario(
        path=tmp_path, slug="x", round="r1", mined_at="2026-01-01",
        source=Source(type="synthetic"),
        taxonomy=Taxonomy(category="not-a-real-category", framework="godot"),
        backend=Backend(),
        status="drafted",
    )
    errors = validate_scenario(s)
    assert any("category" in e for e in errors)


def test_validate_unknown_framework_rejected(tmp_path):
    from gpa.eval.scenario_metadata import validate_scenario, Scenario, Source, Taxonomy, Backend
    s = Scenario(
        path=tmp_path, slug="x", round="r1", mined_at="2026-01-01",
        source=Source(type="synthetic"),
        taxonomy=Taxonomy(category="native-engine", framework="not-a-framework"),
        backend=Backend(),
        status="drafted",
    )
    errors = validate_scenario(s)
    assert any("framework" in e for e in errors)


def test_validate_required_fields_complete(tmp_path):
    from gpa.eval.scenario_metadata import validate_scenario, Scenario, Source, Taxonomy, Backend
    s = Scenario(
        path=tmp_path, slug="godot_1_x", round="r1", mined_at="2026-01-01",
        source=Source(type="github_issue", url="https://github.com/x/y/issues/1",
                      repo="x/y", issue_id=1),
        taxonomy=Taxonomy(category="native-engine", framework="godot",
                          bug_class="framework-internal"),
        backend=Backend(api="vulkan", status="reproduced"),
        status="drafted",
    )
    errors = validate_scenario(s)
    assert errors == []
