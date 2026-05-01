"""Tests for the cross-run scope log."""
from __future__ import annotations

import json
from pathlib import Path

from gpa.eval.curation.scope_log import (
    aggregate_scope,
    append_scope_rows,
    queries_already_mined,
    repos_already_mined,
)


def _write_journey(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def test_aggregate_scope_groups_by_query(tmp_path):
    journey = tmp_path / "journey.jsonl"
    _write_journey(journey, [
        {"discovery_query": "repo:foo/bar is:issue flicker",
         "select": {"selected": True}, "produce": {"extracted": True},
         "judge": {"committed_as": "r1_x"}},
        {"discovery_query": "repo:foo/bar is:issue flicker",
         "select": {"selected": False}},
        {"discovery_query": "repo:zog/qux is:issue invisible",
         "select": {"selected": True}, "produce": {"extracted": True},
         "judge": {"committed_as": None}},
    ])
    rows = aggregate_scope(journey_path=journey, run_id="r1", ts="t")
    by_q = {r["query"]: r for r in rows}

    foo = by_q["repo:foo/bar is:issue flicker"]
    assert foo["yielded"] == 2
    assert foo["selected"] == 1
    assert foo["extracted"] == 1
    assert foo["committed"] == 1
    assert foo["repos"] == ["foo/bar"]
    assert foo["source"] == "issue"
    assert foo["run_id"] == "r1"

    zog = by_q["repo:zog/qux is:issue invisible"]
    assert zog["committed"] == 0
    assert zog["repos"] == ["zog/qux"]


def test_aggregate_scope_handles_stackoverflow_taglist(tmp_path):
    journey = tmp_path / "journey.jsonl"
    _write_journey(journey, [
        {"discovery_query": ["webgl", "three.js"],
         "select": {"selected": False}},
    ])
    rows = aggregate_scope(journey_path=journey, run_id="r1", ts="t")
    assert rows[0]["query"] == '["three.js", "webgl"]'  # canonical-sorted
    assert rows[0]["source"] == "stackoverflow"
    assert rows[0]["repos"] == []


def test_aggregate_scope_returns_empty_for_missing_journey(tmp_path):
    rows = aggregate_scope(
        journey_path=tmp_path / "no.jsonl", run_id="r1", ts="t",
    )
    assert rows == []


def test_append_scope_rows_creates_parent_dir_and_appends(tmp_path):
    log = tmp_path / "deep" / "scope-log.jsonl"
    append_scope_rows(scope_log_path=log, rows=[
        {"run_id": "r1", "query": "q1", "yielded": 5,
         "selected": 1, "extracted": 1, "committed": 0,
         "repos": ["a/b"], "ts": "t", "source": "issue"},
    ])
    append_scope_rows(scope_log_path=log, rows=[
        {"run_id": "r2", "query": "q2", "yielded": 3,
         "selected": 0, "extracted": 0, "committed": 0,
         "repos": [], "ts": "t", "source": "issue"},
    ])
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["run_id"] == "r1"
    assert json.loads(lines[1])["run_id"] == "r2"


def test_queries_already_mined(tmp_path):
    log = tmp_path / "scope-log.jsonl"
    log.write_text(
        '{"run_id":"r1","query":"q1","yielded":1,"repos":[]}\n'
        '{"run_id":"r1","query":"q2","yielded":1,"repos":[]}\n'
        '{"run_id":"r2","query":"q1","yielded":1,"repos":[]}\n'  # repeat
    )
    assert queries_already_mined(scope_log_path=log) == {"q1", "q2"}


def test_queries_already_mined_handles_missing_log(tmp_path):
    assert queries_already_mined(scope_log_path=tmp_path / "no.jsonl") == set()


def test_repos_already_mined_histogram(tmp_path):
    log = tmp_path / "scope-log.jsonl"
    log.write_text(
        '{"repos":["foo/bar","baz/qux"]}\n'
        '{"repos":["foo/bar"]}\n'
        '{"repos":[]}\n'
    )
    h = repos_already_mined(scope_log_path=log)
    assert h["foo/bar"] == 2
    assert h["baz/qux"] == 1
