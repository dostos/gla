"""Tests for the scenario-verifier CLI.

The verifier walks ``tests/eval``, runs tiered checks (static / network /
build), records the verdict in ``scenario.yaml``, and optionally
quarantines failed directories so :class:`ScenarioLoader` can't serve a
broken scenario to the harness.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import yaml

from gpa.eval.curation.verify import (
    verify_scenario,
    _check_static,
    _quarantine,
    _write_verdict,
)
from gpa.eval.scenario import ScenarioLoader


def _seed_scenario(root: Path, *,
                   slug: str = "scn",
                   pkg: str = "native-engine/godot/scn",
                   fix_block: str | None = None,
                   include_main_c: bool = False) -> Path:
    """Create a minimal scenario directory under ``root`` for testing."""
    sd = root / pkg
    sd.mkdir(parents=True, exist_ok=True)

    if fix_block is None:
        fix_block = (
            "fix_pr_url: https://github.com/o/r/pull/1\n"
            "fix_sha: abc123def456789012345678901234567890aaaa\n"
            "fix_parent_sha: 0000aaaa11112222333344445555666677778888\n"
            "bug_class: framework-internal\n"
            "files:\n  - src/render/foo.c\n"
        )
    md = sd / "scenario.md"
    md.write_text(
        "## User Report\n\nA bug.\n\n## Fix\n\n"
        f"```yaml\n{fix_block}```\n",
        encoding="utf-8",
    )
    yml = sd / "scenario.yaml"
    yml.write_text(
        yaml.safe_dump({
            "schema_version": 1, "slug": slug, "status": "drafted",
            "source": {"type": "github_issue",
                       "url": "https://github.com/o/r/issues/1"},
            "taxonomy": {"category": "native-engine", "framework": "godot",
                         "bug_class": "unknown"},
        }, sort_keys=False),
        encoding="utf-8",
    )
    if include_main_c:
        (sd / "main.c").write_text(
            "int main(void) { return 0; }\n", encoding="utf-8",
        )
    return sd


# ---------------------------------------------------------------------------
# Static tier
# ---------------------------------------------------------------------------


def test_static_passes_complete_fix_block(tmp_path):
    sd = _seed_scenario(tmp_path)
    assert _check_static(sd) == []


def test_static_flags_no_groundtruth_anchor(tmp_path):
    """Scenario with no `## Fix`, `## Upstream Snapshot`, or `## Bug
    Signature` is unscorable AND uninvestigatable — no signal extractable
    in any mode."""
    sd = tmp_path / "scn"
    sd.mkdir()
    (sd / "scenario.md").write_text("## User Report\n\nNothing here.\n")
    failures = _check_static(sd)
    assert len(failures) == 1
    assert "no ground-truth anchor" in failures[0]


def test_static_passes_legacy_upstream_snapshot_only(tmp_path):
    """Legacy scenarios use `## Upstream Snapshot` instead of `## Fix`.
    They're scoreable as prose-only and investigatable via upstream tools,
    so the verifier must not reject them as broken."""
    sd = tmp_path / "scn"
    sd.mkdir()
    (sd / "scenario.md").write_text(
        "## User Report\n\nA bug.\n\n"
        "## Upstream Snapshot\n"
        "- **Repo**: https://github.com/o/r\n"
        "- **SHA**: deadbeef\n"
    )
    assert _check_static(sd) == []


def test_static_passes_prose_ground_truth_only(tmp_path):
    """Early-round hand-authored synthetic scenarios anchor on a prose
    `## Ground Truth` section without yaml. They don't auto-score on the
    new stack, but they're not BROKEN — verifier must accept them."""
    sd = tmp_path / "scn"
    sd.mkdir()
    (sd / "scenario.md").write_text(
        "## User Report\n\nQuad disappears.\n\n"
        "## Ground Truth\n\nGL_CULL_FACE leaks from a UI pass.\n"
    )
    assert _check_static(sd) == []


def test_static_passes_legacy_bug_class_with_empty_files(tmp_path):
    """`bug_class: legacy` is a documented escape hatch for issues
    classified as wontfix / known limitation. Empty files + (none)
    placeholders are tolerated for that class only."""
    sd = _seed_scenario(tmp_path, fix_block=(
        "fix_pr_url: (none — issue closed without a fix PR)\n"
        "fix_sha: (none)\n"
        "fix_parent_sha: (none)\n"
        "bug_class: legacy\n"
        "files: []\n"
    ))
    assert _check_static(sd) == []


def test_static_still_requires_files_for_non_legacy_bug_class(tmp_path):
    """Empty files + bug_class=framework-internal is a real defect."""
    sd = _seed_scenario(tmp_path, fix_block=(
        "fix_pr_url: https://github.com/o/r/pull/1\n"
        "fix_sha: abc\n"
        "fix_parent_sha: dead\n"
        "bug_class: framework-internal\n"
        "files: []\n"
    ))
    failures = _check_static(sd)
    assert any("empty files list" in f for f in failures), failures


def test_static_passes_synthetic_bug_signature_only(tmp_path):
    """Synthetic scenarios anchor on `## Bug Signature` — a framebuffer
    color/draw-call signature. No fix block, no upstream — the framebuffer
    matcher is the entire ground truth."""
    sd = tmp_path / "scn"
    sd.mkdir()
    (sd / "scenario.md").write_text(
        "## User Report\n\nQuad disappears.\n\n"
        "## Bug Signature\n```yaml\n"
        "type: framebuffer_dominant_color\n"
        "spec:\n  expected_rgba: [0.0, 0.0, 0.0, 1.0]\n"
        "  tolerance: 0.05\n"
        "```\n"
    )
    assert _check_static(sd) == []


def test_static_picks_fix_block_not_bug_signature(tmp_path):
    """When a scenario has BOTH `## Bug Signature` (yaml block) and
    `## Fix` (yaml block), the verifier must parse the fix block — the
    bug-signature block has its own schema and shares no fields."""
    sd = tmp_path / "scn"
    sd.mkdir()
    (sd / "scenario.md").write_text(
        "## User Report\n\nA bug.\n\n"
        "## Bug Signature\n```yaml\n"
        "type: framebuffer_dominant_color\n"
        "spec:\n  expected_rgba: [0.0, 0.0, 0.0, 1.0]\n"
        "```\n\n"
        "## Fix\n```yaml\n"
        "fix_pr_url: https://github.com/o/r/pull/1\n"
        "fix_sha: abc\n"
        "fix_parent_sha: dead\n"
        "bug_class: framework-internal\n"
        "files:\n  - src/foo.c\n"
        "```\n"
    )
    assert _check_static(sd) == []


def test_static_flags_malformed_fix_section_but_not_missing(tmp_path):
    """Author included `## Fix` but the yaml block is missing — that's a
    real defect, distinct from "no fix section at all"."""
    sd = tmp_path / "scn"
    sd.mkdir()
    (sd / "scenario.md").write_text(
        "## User Report\n\nA bug.\n\n## Fix\n\nNo yaml block here.\n"
    )
    failures = _check_static(sd)
    assert any("yaml block missing or unparseable" in f for f in failures), failures


def test_static_flags_missing_required_fields(tmp_path):
    sd = _seed_scenario(tmp_path, fix_block=(
        "fix_pr_url: https://github.com/o/r/pull/1\n"
        "files: []\n"
    ))
    failures = _check_static(sd)
    assert any("fix_sha" in f for f in failures)
    assert any("bug_class" in f for f in failures)
    assert any("empty files" in f for f in failures)


def test_static_flags_missing_parent_sha_for_github_url(tmp_path):
    sd = _seed_scenario(tmp_path, fix_block=(
        "fix_pr_url: https://github.com/o/r/pull/1\n"
        "fix_sha: abc123\n"
        "bug_class: framework-internal\n"
        "files:\n  - src/foo.c\n"
    ))
    failures = _check_static(sd)
    assert any("fix_parent_sha" in f for f in failures), failures


def test_static_skips_parent_check_for_non_github_url(tmp_path):
    sd = _seed_scenario(tmp_path, fix_block=(
        "fix_pr_url: https://gitlab.com/o/r/-/merge_requests/1\n"
        "fix_sha: abc123\n"
        "bug_class: framework-internal\n"
        "files:\n  - src/foo.c\n"
    ))
    assert _check_static(sd) == []


def test_static_detects_main_c_contamination(tmp_path):
    sd = _seed_scenario(tmp_path, include_main_c=True)
    (sd / "main.c").write_text(
        "// BUG: the depth test is reversed\n"
        "int main(void) { return 0; }\n",
        encoding="utf-8",
    )
    failures = _check_static(sd)
    assert any("source contamination" in f for f in failures), failures


def test_static_detects_contamination_in_glsl_too(tmp_path):
    """Hint comments in shader sources also leak ground truth."""
    sd = _seed_scenario(tmp_path, include_main_c=True)
    (sd / "frag.glsl").write_text(
        "// should be vec4(1.0)\n"
        "void main() { gl_FragColor = vec4(0.0); }\n",
        encoding="utf-8",
    )
    failures = _check_static(sd)
    assert any("frag.glsl" in f and "should be" in f for f in failures), failures


# ---------------------------------------------------------------------------
# Quarantine + verdict persistence
# ---------------------------------------------------------------------------


def test_write_verdict_marks_status_verified(tmp_path):
    sd = _seed_scenario(tmp_path)
    from gpa.eval.curation.verify import VerificationResult
    result = VerificationResult(
        scenario_id="scn", scenario_dir=sd,
        failures=[], checks_run=["static"],
    )
    _write_verdict(sd, result)
    data = yaml.safe_load((sd / "scenario.yaml").read_text())
    assert data["status"] == "verified"
    assert data["verification"]["checks_run"] == ["static"]
    assert data["verification"]["failures"] == []


def test_write_verdict_marks_status_quarantined_with_failures(tmp_path):
    sd = _seed_scenario(tmp_path)
    from gpa.eval.curation.verify import VerificationResult
    result = VerificationResult(
        scenario_id="scn", scenario_dir=sd,
        failures=["fix_sha not found on github"],
        checks_run=["static", "network"],
    )
    _write_verdict(sd, result)
    data = yaml.safe_load((sd / "scenario.yaml").read_text())
    assert data["status"] == "quarantined"
    assert data["verification"]["failures"] == ["fix_sha not found on github"]


def test_quarantine_moves_directory_mirroring_taxonomy(tmp_path):
    eval_root = tmp_path / "tests" / "eval"
    quarantine_root = tmp_path / "tests" / "eval-quarantine"
    sd = _seed_scenario(eval_root, slug="bad",
                        pkg="native-engine/godot/bad")
    new_path = _quarantine(sd, eval_root=eval_root,
                           quarantine_dir=quarantine_root)
    assert not sd.exists()
    expected = quarantine_root / "native-engine" / "godot" / "bad"
    assert new_path == expected
    assert (new_path / "scenario.md").exists()


def test_quarantine_refuses_to_overwrite(tmp_path):
    eval_root = tmp_path / "tests" / "eval"
    quarantine_root = tmp_path / "tests" / "eval-quarantine"
    sd = _seed_scenario(eval_root, slug="bad",
                        pkg="native-engine/godot/bad")
    # Pre-create destination
    dest = quarantine_root / "native-engine" / "godot" / "bad"
    dest.mkdir(parents=True)
    (dest / "stale_marker").write_text("")

    import pytest
    with pytest.raises(FileExistsError):
        _quarantine(sd, eval_root=eval_root, quarantine_dir=quarantine_root)
    # Source still in place
    assert sd.exists()


# ---------------------------------------------------------------------------
# Orchestration: verify_scenario stops at first tier with failures
# ---------------------------------------------------------------------------


def test_verify_scenario_skips_network_when_static_failed(tmp_path):
    eval_root = tmp_path / "tests" / "eval"
    sd = _seed_scenario(eval_root, slug="bad", pkg="x/y/bad",
                        fix_block="fix_pr_url: https://github.com/o/r/pull/1\n"
                                  "files: []\n")
    with patch("gpa.eval.curation.verify._gh_commit_exists") as mock_gh:
        result = verify_scenario(
            sd, eval_root=eval_root, repo_root=tmp_path,
            network=True, build=True,
        )
    assert not result.passed
    assert result.checks_run == ["static"]
    mock_gh.assert_not_called()


# ---------------------------------------------------------------------------
# ScenarioLoader filters quarantined scenarios from load_all
# ---------------------------------------------------------------------------


def test_loader_load_all_skips_quarantined_by_default(tmp_path):
    eval_root = tmp_path
    good = _seed_scenario(eval_root, slug="good", pkg="cat/fw/good")
    bad = _seed_scenario(eval_root, slug="bad", pkg="cat/fw/bad")
    # Quarantine the bad one in-place
    bad_yml = bad / "scenario.yaml"
    data = yaml.safe_load(bad_yml.read_text())
    data["status"] = "quarantined"
    bad_yml.write_text(yaml.safe_dump(data, sort_keys=False))

    loader = ScenarioLoader(eval_dir=str(eval_root))
    ids = [s.id for s in loader.load_all()]
    assert "good" in ids
    assert "bad" not in ids


def test_loader_load_all_includes_quarantined_when_asked(tmp_path):
    eval_root = tmp_path
    bad = _seed_scenario(eval_root, slug="bad", pkg="cat/fw/bad")
    bad_yml = bad / "scenario.yaml"
    data = yaml.safe_load(bad_yml.read_text())
    data["status"] = "quarantined"
    bad_yml.write_text(yaml.safe_dump(data, sort_keys=False))

    loader = ScenarioLoader(eval_dir=str(eval_root))
    ids = [s.id for s in loader.load_all(include_quarantined=True)]
    assert "bad" in ids


def test_loader_load_one_does_not_filter(tmp_path):
    """`load(scenario_id)` is a direct lookup — it must NOT filter on
    status, so diagnostics and verifier re-runs can target a quarantined
    scenario by name."""
    eval_root = tmp_path
    bad = _seed_scenario(eval_root, slug="bad", pkg="cat/fw/bad")
    bad_yml = bad / "scenario.yaml"
    data = yaml.safe_load(bad_yml.read_text())
    data["status"] = "quarantined"
    bad_yml.write_text(yaml.safe_dump(data, sort_keys=False))

    loader = ScenarioLoader(eval_dir=str(eval_root))
    s = loader.load("bad")
    assert s.id == "bad"
