"""Tests for the pipeline's `(auto-resolve from PR #NNN)` sentinel resolver."""
from unittest.mock import patch, MagicMock
import json
from gla.eval.curation.pipeline import _resolve_snapshot_sha


def test_resolves_pr_reference_to_parent_sha():
    pr_json = json.dumps({"base": {"sha": "parent_abc123"}, "number": 42})
    md = (
        "## Upstream Snapshot\n"
        "- **Repo**: https://github.com/o/r\n"
        "- **SHA**: (auto-resolve from PR #42)\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=pr_json, returncode=0)
        out = _resolve_snapshot_sha(md, "o", "r")
    assert "parent_abc123" in out
    assert "(auto-resolve from PR" not in out

def test_resolves_commit_reference_to_parent_sha():
    commit_json = json.dumps({"parents": [{"sha": "parent_xyz"}], "sha": "abc123def"})
    md = (
        "## Upstream Snapshot\n"
        "- **Repo**: https://github.com/o/r\n"
        "- **SHA**: (auto-resolve from commit abc123def)\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=commit_json, returncode=0)
        out = _resolve_snapshot_sha(md, "o", "r")
    assert "parent_xyz" in out
    assert "(auto-resolve from commit" not in out

def test_leaves_marker_when_gh_api_fails():
    md = (
        "## Upstream Snapshot\n"
        "- **Repo**: https://github.com/o/r\n"
        "- **SHA**: (auto-resolve from PR #42)\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=1)
        out = _resolve_snapshot_sha(md, "o", "r")
    # Unresolved — human can fix later
    assert "(auto-resolve from PR #42)" in out

def test_noop_when_no_marker_present():
    md = "## Upstream Snapshot\n- **Repo**: https://github.com/o/r\n- **SHA**: deadbeef\n"
    # No gh api calls should fire
    with patch("subprocess.run") as mock_run:
        out = _resolve_snapshot_sha(md, "o", "r")
    assert out == md
    mock_run.assert_not_called()

def test_resolves_multiple_markers_in_one_md():
    """A draft might reference two different PRs (e.g., a follow-up fix). Resolve each."""
    responses = [
        MagicMock(stdout=json.dumps({"base": {"sha": "sha_one"}}), returncode=0),
        MagicMock(stdout=json.dumps({"base": {"sha": "sha_two"}}), returncode=0),
    ]
    md = (
        "## Upstream Snapshot\n"
        "- **SHA**: (auto-resolve from PR #1)\n"
        "Also see (auto-resolve from PR #2) for context.\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = responses
        out = _resolve_snapshot_sha(md, "o", "r")
    assert "sha_one" in out
    assert "sha_two" in out
    assert "(auto-resolve from PR" not in out
