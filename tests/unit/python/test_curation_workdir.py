import json
from gla.eval.curation.workdir import IssueWorkdir

def test_issue_id_from_url():
    wd = IssueWorkdir.for_url("/tmp/x", "https://github.com/mrdoob/three.js/issues/12345")
    assert wd.issue_id == "github_mrdoob_three.js_issue_12345"

def test_store_and_load_stage_output(tmp_path):
    wd = IssueWorkdir.for_url(tmp_path, "https://github.com/x/y/issues/7")
    wd.write_stage("triage", {"verdict": "in_scope"}, input_hash="abc123")
    result = wd.read_stage("triage")
    assert result is not None
    assert result["output"] == {"verdict": "in_scope"}
    assert result["input_hash"] == "abc123"

def test_skip_if_input_hash_matches(tmp_path):
    wd = IssueWorkdir.for_url(tmp_path, "https://github.com/x/y/issues/7")
    wd.write_stage("triage", {"v": 1}, input_hash="h1")
    assert wd.should_skip_stage("triage", current_input_hash="h1") is True
    assert wd.should_skip_stage("triage", current_input_hash="h2") is False

def test_not_skip_if_no_prior_output(tmp_path):
    wd = IssueWorkdir.for_url(tmp_path, "https://github.com/x/y/issues/7")
    assert wd.should_skip_stage("triage", current_input_hash="h1") is False
