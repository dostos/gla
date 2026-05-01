"""Tests for the auto-summary writer that rolls up journey.jsonl."""
from pathlib import Path

from gpa.eval.curation.summary import write_summary


def test_summary_counts_by_terminal_reason(tmp_path):
    journey = tmp_path / "journey.jsonl"
    journey.write_text(
        '{"url":"u1","terminal_phase":"select","terminal_reason":"duplicate_url","tokens":{"total":0}}\n'
        '{"url":"u2","terminal_phase":"select","terminal_reason":"below_min_score","tokens":{"total":0}}\n'
        '{"url":"u3","terminal_phase":"judge","terminal_reason":"committed","tokens":{"total":12500},"select":{"taxonomy_cell":"web-3d/three.js"}}\n'
    )
    summary_path = tmp_path / "summary.md"
    write_summary(journey_path=journey, summary_path=summary_path)
    text = summary_path.read_text()
    assert "duplicate_url: 1" in text
    assert "below_min_score: 1" in text
    assert "committed: 1" in text
    assert "12500" in text  # token total


def test_summary_handles_empty_journey(tmp_path):
    journey = tmp_path / "journey.jsonl"
    journey.write_text("")
    summary_path = tmp_path / "summary.md"
    write_summary(journey_path=journey, summary_path=summary_path)
    text = summary_path.read_text()
    assert "Total candidates: 0" in text
    assert "Total tokens spent: 0" in text
