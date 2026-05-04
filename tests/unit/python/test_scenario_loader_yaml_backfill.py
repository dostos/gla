"""ScenarioLoader should backfill scenario.md gaps from scenario.yaml.

The codex-mined scenarios (rfc2ac5_*, r5211bd_*) put taxonomy + source
metadata in scenario.yaml and put fix metadata in scenario.md but never
emit a `## Upstream Snapshot` section. The loader needs to:

  - read scenario.yaml when present
  - backfill `framework` from `taxonomy.framework`
  - backfill `upstream_snapshot_repo` from `source.repo`
  - backfill `upstream_snapshot_sha` from `fix.fix_parent_sha` (preferred)
    or fall back to `fix.fix_sha` when no parent is recorded
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gpa.eval.scenario import ScenarioLoader


_BASE_MD = """\
## Bug Description

Some rendering bug.

## Difficulty

3

## Fix

```yaml
fix_pr_url: https://github.com/godotengine/godot/pull/109971
fix_sha: ec62f12862c4cfc76526eaf99afa0a24249f8288
{fix_parent}bug_class: framework-internal
files:
  - servers/rendering/foo.cpp
```
"""


_BASE_YAML = """\
schema_version: 1
slug: {slug}
source:
  type: github_issue
  url: https://github.com/godotengine/godot/issues/86098
  repo: godotengine/godot
  issue_id: 86098
taxonomy:
  category: native-engine
  framework: godot
  bug_class: unknown
"""


def _make_scenario_dir(tmp_path: Path, *, slug: str, fix_parent: str = "") -> Path:
    d = tmp_path / "tests-eval" / "native-engine" / "godot" / slug
    d.mkdir(parents=True)
    (d / "scenario.md").write_text(_BASE_MD.format(fix_parent=fix_parent))
    (d / "scenario.yaml").write_text(_BASE_YAML.format(slug=slug))
    return d


def test_framework_backfilled_from_scenario_yaml(tmp_path):
    _make_scenario_dir(tmp_path, slug="rfc2ac5_test_framework_backfill")
    loader = ScenarioLoader(str(tmp_path / "tests-eval"))
    s = loader.load("rfc2ac5_test_framework_backfill")
    assert s.framework == "godot"


def test_upstream_repo_backfilled_from_source_repo(tmp_path):
    _make_scenario_dir(tmp_path, slug="rfc2ac5_test_repo_backfill")
    loader = ScenarioLoader(str(tmp_path / "tests-eval"))
    s = loader.load("rfc2ac5_test_repo_backfill")
    assert s.upstream_snapshot_repo == "https://github.com/godotengine/godot"


def test_upstream_sha_uses_fix_parent_sha_when_present(tmp_path):
    fix_parent_block = "fix_parent_sha: deadbeef00deadbeef00deadbeef00deadbeef0000\n"
    _make_scenario_dir(
        tmp_path, slug="rfc2ac5_test_parent_sha", fix_parent=fix_parent_block,
    )
    loader = ScenarioLoader(str(tmp_path / "tests-eval"))
    s = loader.load("rfc2ac5_test_parent_sha")
    assert s.upstream_snapshot_sha == "deadbeef00deadbeef00deadbeef00deadbeef0000"


def test_upstream_sha_falls_back_to_fix_sha_when_parent_missing(tmp_path):
    """Document the limitation: when no fix_parent_sha is recorded, use
    fix_sha. This shows the agent the post-fix state, not the bug state.
    Mining-pipeline upgrade should populate fix_parent_sha; until then the
    eval is biased toward 'agent finds correct fix easily.'"""
    _make_scenario_dir(tmp_path, slug="rfc2ac5_test_sha_fallback")
    loader = ScenarioLoader(str(tmp_path / "tests-eval"))
    s = loader.load("rfc2ac5_test_sha_fallback")
    assert s.upstream_snapshot_sha == "ec62f12862c4cfc76526eaf99afa0a24249f8288"


def test_no_scenario_yaml_means_no_backfill(tmp_path):
    """When scenario.yaml is absent, only md-derived fields are used."""
    d = tmp_path / "tests-eval" / "x" / "rfc2ac5_no_yaml"
    d.mkdir(parents=True)
    (d / "scenario.md").write_text(_BASE_MD.format(fix_parent=""))
    # No scenario.yaml created
    loader = ScenarioLoader(str(tmp_path / "tests-eval"))
    s = loader.load("rfc2ac5_no_yaml")
    # framework not backfilled → still None
    assert s.framework is None
    # repo also not backfilled → None
    assert s.upstream_snapshot_repo is None


def test_md_upstream_section_takes_priority_over_yaml_backfill(tmp_path):
    """If scenario.md has its own `## Upstream Snapshot` block, the yaml
    backfill must not override it."""
    md = (
        "## Bug Description\n\nx\n\n"
        "## Upstream Snapshot\n\n"
        "- **Repo**: https://github.com/explicit/repo\n"
        "- **SHA**: cafebabe\n\n"
        "## Difficulty\n\n3\n"
    )
    yaml_text = _BASE_YAML.format(slug="rfc2ac5_priority_test")
    d = tmp_path / "tests-eval" / "x" / "rfc2ac5_priority_test"
    d.mkdir(parents=True)
    (d / "scenario.md").write_text(md)
    (d / "scenario.yaml").write_text(yaml_text)
    loader = ScenarioLoader(str(tmp_path / "tests-eval"))
    s = loader.load("rfc2ac5_priority_test")
    assert s.upstream_snapshot_repo == "https://github.com/explicit/repo"
    assert s.upstream_snapshot_sha == "cafebabe"


def test_md_framework_section_takes_priority_over_yaml_backfill(tmp_path):
    md = (
        "## Bug Description\n\nx\n\n"
        "## Framework\n\nthree.js\n\n"
        "## Difficulty\n\n3\n"
    )
    yaml_text = _BASE_YAML.format(slug="rfc2ac5_fw_priority")
    d = tmp_path / "tests-eval" / "x" / "rfc2ac5_fw_priority"
    d.mkdir(parents=True)
    (d / "scenario.md").write_text(md)
    (d / "scenario.yaml").write_text(yaml_text)
    loader = ScenarioLoader(str(tmp_path / "tests-eval"))
    s = loader.load("rfc2ac5_fw_priority")
    assert s.framework == "three.js"
