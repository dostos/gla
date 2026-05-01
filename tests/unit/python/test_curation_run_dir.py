import re
from pathlib import Path
from gpa.eval.curation.run_dir import RunDir, generate_run_id

def test_generate_run_id_format():
    rid = generate_run_id(config_text="queries: []\nrules: foo")
    # YYYY-MM-DD-HHMMSS-<8-hex>
    assert re.match(r"^\d{4}-\d{2}-\d{2}-\d{6}-[0-9a-f]{8}$", rid), rid

def test_generate_run_id_is_stable_for_same_config():
    a = generate_run_id(config_text="x", clock=lambda: "2026-05-01-120000")
    b = generate_run_id(config_text="x", clock=lambda: "2026-05-01-120000")
    assert a == b

def test_run_dir_freezes_config(tmp_path):
    rd = RunDir.create(root=tmp_path, run_id="r1",
                       config_payload="queries:\n  - q1\n")
    assert (tmp_path / "runs" / "r1" / "config.yaml").read_text() == "queries:\n  - q1\n"
    assert rd.journey_path == tmp_path / "runs" / "r1" / "journey.jsonl"
    assert rd.issues_dir == tmp_path / "runs" / "r1" / "issues"
    assert rd.summary_path == tmp_path / "runs" / "r1" / "summary.md"
    assert rd.issues_dir.is_dir()

def test_run_dir_create_is_idempotent(tmp_path):
    rd1 = RunDir.create(root=tmp_path, run_id="r1", config_payload="x")
    rd2 = RunDir.create(root=tmp_path, run_id="r1", config_payload="x")
    assert rd1.root == rd2.root
