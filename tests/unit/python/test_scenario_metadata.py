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


def test_scenario_yaml_round_trip(tmp_path):
    from gpa.eval.scenario_metadata import (
        Scenario, Source, Taxonomy, Backend,
        dump_scenario_yaml, load_scenario_yaml,
    )
    original = Scenario(
        path=tmp_path, slug="godot_1_x", round="r1", mined_at="2026-01-01",
        source=Source(type="github_issue", url="https://github.com/x/y/issues/1",
                      repo="x/y", issue_id=1),
        taxonomy=Taxonomy(category="native-engine", framework="godot",
                          bug_class="framework-internal"),
        backend=Backend(api="vulkan", status="reproduced"),
        status="drafted",
        tags=["postprocess"],
        notes="hello",
    )
    yaml_path = tmp_path / "scenario.yaml"
    dump_scenario_yaml(original, yaml_path)
    loaded = load_scenario_yaml(yaml_path)
    assert loaded.slug == original.slug
    assert loaded.source.url == original.source.url
    assert loaded.taxonomy.category == original.taxonomy.category
    assert loaded.tags == ["postprocess"]


def test_scenario_yaml_load_missing_file_raises(tmp_path):
    from gpa.eval.scenario_metadata import load_scenario_yaml
    import pytest
    with pytest.raises(FileNotFoundError):
        load_scenario_yaml(tmp_path / "nope.yaml")


def _make_scenario_at(dir_path, slug, category, framework):
    """Helper: write minimum scenario.md + scenario.yaml in dir_path."""
    from gpa.eval.scenario_metadata import (
        Scenario, Source, Taxonomy, Backend, dump_scenario_yaml,
    )
    dir_path.mkdir(parents=True)
    (dir_path / "scenario.md").write_text("# fixture\n")
    s = Scenario(
        path=dir_path, slug=slug, round="r1", mined_at="2026-01-01",
        source=Source(type="synthetic"),
        taxonomy=Taxonomy(category=category, framework=framework, bug_class="synthetic"),
        backend=Backend(),
        status="drafted",
    )
    dump_scenario_yaml(s, dir_path / "scenario.yaml")


def test_iter_scenarios_finds_all(tmp_path):
    from gpa.eval.scenario_metadata import iter_scenarios
    _make_scenario_at(tmp_path / "synthetic" / "uniform" / "e1_x", "e1_x", "synthetic", "synthetic")
    _make_scenario_at(tmp_path / "synthetic" / "depth" / "e2_y", "e2_y", "synthetic", "synthetic")
    found = list(iter_scenarios(tmp_path))
    assert len(found) == 2
    assert {s.slug for s in found} == {"e1_x", "e2_y"}


def test_validate_all_reports_slug_mismatch(tmp_path):
    from gpa.eval.scenario_metadata import validate_all
    _make_scenario_at(tmp_path / "synthetic" / "x" / "actually_named_this",
                      "but_yaml_says_this", "synthetic", "synthetic")
    errors = validate_all(tmp_path)
    assert any("slug" in e.lower() for e in errors)
