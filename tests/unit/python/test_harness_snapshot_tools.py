"""Tests for EvalHarness snapshot tools (read_upstream / list_upstream_files).

These tests use a MagicMock for SnapshotFetcher and tmp_path for the fake
snapshot working tree — no actual git clones happen.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gla.eval.harness import EvalHarness, _SNAPSHOT_MAX_BYTES
from gla.eval.scenario import ScenarioMetadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scenario(**overrides) -> ScenarioMetadata:
    base = dict(
        id="test_id",
        title="T",
        bug_description="b",
        expected_output="e",
        actual_output="a",
        ground_truth_diagnosis="gt",
        ground_truth_fix="fix",
        difficulty=3,
        adversarial_principles=[],
        gla_advantage="",
        source_path="/tmp/x.c",
        binary_name="test_id",
    )
    base.update(overrides)
    return ScenarioMetadata(**base)


def _make_harness(snapshot_root: Path) -> tuple[EvalHarness, MagicMock]:
    """Build a harness whose SnapshotFetcher.fetch returns snapshot_root."""
    mock_fetcher = MagicMock()
    mock_fetcher.fetch.return_value = snapshot_root
    # Bypass __init__ network calls by injecting fake runner + loader
    harness = EvalHarness.__new__(EvalHarness)
    harness.results = []
    harness._model = "test"
    harness._snapshot_fetcher = mock_fetcher
    # We don't need a real runner/loader/scorer for these unit tests
    harness.runner = MagicMock()
    harness.loader = MagicMock()
    harness._scorer = MagicMock()
    return harness, mock_fetcher


# ---------------------------------------------------------------------------
# Test 1 — scenario without snapshot refs → no snapshot tools in dict
# ---------------------------------------------------------------------------


def test_no_snapshot_tools_when_no_refs():
    harness = EvalHarness.__new__(EvalHarness)
    harness.results = []
    harness._model = "test"
    harness._snapshot_fetcher = None
    harness.runner = MagicMock()
    harness.runner.read_source.return_value = "src"
    harness.loader = MagicMock()
    harness._scorer = MagicMock()

    scenario = _make_scenario()  # no upstream_snapshot_* fields
    tools = harness._build_tools(scenario, mode="code_only")

    assert "read_upstream" not in tools
    assert "list_upstream_files" not in tools


# ---------------------------------------------------------------------------
# Test 2 — scenario WITH snapshot refs → both tools present
# ---------------------------------------------------------------------------


def test_snapshot_tools_present_when_refs_set(tmp_path):
    harness, _ = _make_harness(tmp_path)
    scenario = _make_scenario(
        upstream_snapshot_repo="https://github.com/x/y",
        upstream_snapshot_sha="abc123",
    )
    tools = harness._build_tools(scenario, mode="code_only")

    assert "read_upstream" in tools
    assert "list_upstream_files" in tools


# ---------------------------------------------------------------------------
# Test 3 — read_upstream returns file content
# ---------------------------------------------------------------------------


def test_read_upstream_returns_content(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.c").write_text("int main() {}\n", encoding="utf-8")
    # Create .complete sentinel so SnapshotFetcher thinks the clone is done
    (tmp_path / ".complete").write_text("")

    harness, _ = _make_harness(tmp_path)
    scenario = _make_scenario(
        upstream_snapshot_repo="https://github.com/x/y",
        upstream_snapshot_sha="abc123",
    )

    result = harness._read_snapshot_file(scenario, "src/main.c")
    assert result == "int main() {}\n"


# ---------------------------------------------------------------------------
# Test 4 — path traversal returns ERROR
# ---------------------------------------------------------------------------


def test_read_upstream_path_traversal(tmp_path):
    harness, _ = _make_harness(tmp_path)
    scenario = _make_scenario(
        upstream_snapshot_repo="https://github.com/x/y",
        upstream_snapshot_sha="abc123",
    )

    result = harness._read_snapshot_file(scenario, "../secret")
    assert result.startswith("ERROR:")
    assert "traversal" in result.lower()


# ---------------------------------------------------------------------------
# Test 5 — nonexistent file returns ERROR
# ---------------------------------------------------------------------------


def test_read_upstream_nonexistent(tmp_path):
    harness, _ = _make_harness(tmp_path)
    scenario = _make_scenario(
        upstream_snapshot_repo="https://github.com/x/y",
        upstream_snapshot_sha="abc123",
    )

    result = harness._read_snapshot_file(scenario, "does_not_exist.c")
    assert result.startswith("ERROR:")
    assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# Test 6 — file larger than 200 KB is truncated with marker
# ---------------------------------------------------------------------------


def test_read_upstream_truncates_large_file(tmp_path):
    big = b"x" * (_SNAPSHOT_MAX_BYTES + 1000)
    (tmp_path / "big.bin").write_bytes(big)

    harness, _ = _make_harness(tmp_path)
    scenario = _make_scenario(
        upstream_snapshot_repo="https://github.com/x/y",
        upstream_snapshot_sha="abc123",
    )

    result = harness._read_snapshot_file(scenario, "big.bin")
    assert "TRUNCATED" in result
    # Should be shorter than the full file decoded
    assert len(result) < len(big)


# ---------------------------------------------------------------------------
# Test 7 — list_upstream_files returns sorted entries with '/' on dirs
# ---------------------------------------------------------------------------


def test_list_upstream_files_root(tmp_path):
    (tmp_path / "aaa").mkdir()
    (tmp_path / "bbb").mkdir()
    (tmp_path / "ccc.c").write_text("", encoding="utf-8")
    (tmp_path / ".complete").write_text("")  # sentinel, should be excluded

    harness, _ = _make_harness(tmp_path)
    scenario = _make_scenario(
        upstream_snapshot_repo="https://github.com/x/y",
        upstream_snapshot_sha="abc123",
    )

    result = harness._list_snapshot_files(scenario, "")
    lines = result.splitlines()

    # Dirs come first (sorted by (is_file, name)), then files
    assert "aaa/" in lines
    assert "bbb/" in lines
    assert "ccc.c" in lines
    # .complete sentinel must NOT appear
    assert ".complete" not in lines
    # Dirs before files
    assert lines.index("aaa/") < lines.index("ccc.c")


# ---------------------------------------------------------------------------
# Test 8 — fetcher raises exception → read_upstream returns ERROR string
# ---------------------------------------------------------------------------


def test_read_upstream_fetcher_exception():
    mock_fetcher = MagicMock()
    mock_fetcher.fetch.side_effect = RuntimeError("network failure")

    harness = EvalHarness.__new__(EvalHarness)
    harness.results = []
    harness._model = "test"
    harness._snapshot_fetcher = mock_fetcher
    harness.runner = MagicMock()
    harness.loader = MagicMock()
    harness._scorer = MagicMock()

    scenario = _make_scenario(
        upstream_snapshot_repo="https://github.com/x/y",
        upstream_snapshot_sha="abc123",
    )

    result = harness._read_snapshot_file(scenario, "any.c")
    assert result.startswith("ERROR:")
    assert "network failure" in result
    # Must not propagate the exception
