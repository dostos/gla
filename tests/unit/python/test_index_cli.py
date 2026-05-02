"""Tests for gpa.eval.index_cli."""
from pathlib import Path


def test_index_by_taxonomy_renders_counts(tmp_path):
    from gpa.eval.index_cli import build_taxonomy_table
    from gpa.eval.scenario_metadata import (
        Scenario, Source, Taxonomy, Backend, dump_scenario_yaml,
    )
    for cat, fw, slug in [
        ("native-engine", "godot", "x1"),
        ("native-engine", "godot", "x2"),
        ("web-3d", "three.js", "y1"),
    ]:
        d = tmp_path / cat / fw / slug
        d.mkdir(parents=True)
        (d / "scenario.md").write_text("x")
        s = Scenario(path=d, slug=slug, round="r1", mined_at="2026-01-01",
                     source=Source(type="synthetic"),
                     taxonomy=Taxonomy(category=cat, framework=fw, bug_class="synthetic"),
                     backend=Backend(), status="drafted")
        dump_scenario_yaml(s, d / "scenario.yaml")
    table = build_taxonomy_table(tmp_path)
    assert "native-engine" in table
    assert "godot" in table
    assert "2" in table  # 2 godot scenarios


def test_index_by_backend_renders_counts(tmp_path):
    from gpa.eval.index_cli import build_backend_table
    from gpa.eval.scenario_metadata import (
        Scenario, Source, Taxonomy, Backend, dump_scenario_yaml,
    )
    for api, st, slug in [
        ("opengl", "not-yet-reproduced", "a1"),
        ("opengl", "not-yet-reproduced", "a2"),
        ("vulkan", "reproduced", "b1"),
    ]:
        d = tmp_path / "cat" / "fw" / slug
        d.mkdir(parents=True)
        (d / "scenario.md").write_text("x")
        s = Scenario(path=d, slug=slug, round="r1", mined_at="2026-01-01",
                     source=Source(type="synthetic"),
                     taxonomy=Taxonomy(category="synthetic", framework="synthetic", bug_class="synthetic"),
                     backend=Backend(api=api, status=st), status="drafted")
        dump_scenario_yaml(s, d / "scenario.yaml")
    table = build_backend_table(tmp_path)
    assert "opengl" in table
    assert "vulkan" in table
    assert "2" in table  # 2 opengl scenarios


def test_main_returns_zero(tmp_path):
    from gpa.eval.index_cli import main
    from gpa.eval.scenario_metadata import (
        Scenario, Source, Taxonomy, Backend, dump_scenario_yaml,
    )
    d = tmp_path / "synthetic" / "synthetic" / "z1"
    d.mkdir(parents=True)
    (d / "scenario.md").write_text("x")
    s = Scenario(path=d, slug="z1", round="r1", mined_at="2026-01-01",
                 source=Source(type="synthetic"),
                 taxonomy=Taxonomy(category="synthetic", framework="synthetic", bug_class="synthetic"),
                 backend=Backend(), status="drafted")
    dump_scenario_yaml(s, d / "scenario.yaml")
    assert main(["index", "--by", "taxonomy", "--root", str(tmp_path)]) == 0
