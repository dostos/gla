"""Tests for the gen_queries CLI."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
import yaml

from gpa.eval.curation.gen_queries import (
    build_user_message,
    filter_duplicates,
    main,
    parse_llm_response,
    write_yaml_fragment,
)


class _StubLLMResponse:
    def __init__(self, text):
        self.text = text


class _StubLLMClient:
    """Captures calls; returns a canned response."""

    def __init__(self, response_text: str):
        self._response_text = response_text
        self.calls = []

    def complete(self, system, messages, cache_system=True, max_tokens=None):
        self.calls.append({
            "system": system,
            "messages": messages,
            "cache_system": cache_system,
        })
        return _StubLLMResponse(self._response_text)


# ---------- parse_llm_response ----------


def test_parse_llm_response_plain_json():
    text = '{"queries": ["q1", "q2"]}'
    assert parse_llm_response(text) == ["q1", "q2"]


def test_parse_llm_response_fenced_markdown():
    text = '```json\n{"queries": ["q1"]}\n```'
    assert parse_llm_response(text) == ["q1"]


def test_parse_llm_response_with_prose():
    text = 'Here you go:\n{"queries": ["q1", "q2"]}\nLet me know if you need more.'
    assert parse_llm_response(text) == ["q1", "q2"]


def test_parse_llm_response_strips_empty_strings():
    text = '{"queries": ["q1", "", "  "]}'
    assert parse_llm_response(text) == ["q1"]


def test_parse_llm_response_raises_on_garbage():
    with pytest.raises(ValueError, match="no JSON object"):
        parse_llm_response("just some prose")


def test_parse_llm_response_raises_when_queries_not_list():
    with pytest.raises(ValueError, match="queries field is not a list"):
        parse_llm_response('{"queries": "not a list"}')


# ---------- filter_duplicates ----------


def test_filter_duplicates_drops_already_mined():
    kept, dropped = filter_duplicates(
        proposed=["q1", "q2", "q3"],
        already_mined={"q2"},
    )
    assert kept == ["q1", "q3"]
    assert dropped == ["q2"]


def test_filter_duplicates_drops_within_batch_dupes():
    kept, dropped = filter_duplicates(
        proposed=["q1", "q1", "q2"],
        already_mined=set(),
    )
    assert kept == ["q1", "q2"]
    assert dropped == ["q1"]  # second occurrence dropped


# ---------- build_user_message ----------


def test_build_user_message_includes_instruction_and_dedup_lists():
    msg = build_user_message(
        instruction="WebGPU bugs",
        already_mined={"q1", "q2"},
        repos=Counter({"foo/bar": 3, "baz/qux": 1}),
        max_queries=5,
    )
    assert "WebGPU bugs" in msg
    assert "ALREADY_MINED (2 queries)" in msg
    assert "'q1'" in msg
    assert "REPO_HISTOGRAM (2 repos already touched)" in msg
    assert "foo/bar: 3" in msg
    assert "up to 5 new queries" in msg


def test_build_user_message_handles_empty_scope():
    msg = build_user_message(
        instruction="test",
        already_mined=set(),
        repos=Counter(),
        max_queries=3,
    )
    assert "(none)" in msg


# ---------- write_yaml_fragment ----------


def test_write_yaml_fragment_round_trip(tmp_path):
    out = tmp_path / "deep" / "out.yaml"
    write_yaml_fragment(
        queries=["q1", "q2"], out_path=out,
        instruction="test instruction", batch_quota=15,
    )
    loaded = yaml.safe_load(out.read_text())
    assert loaded["batch_quota"] == 15
    assert loaded["queries"]["issue"] == ["q1", "q2"]
    # Header comments persist
    text = out.read_text()
    assert "# Generated from instruction" in text


# ---------- main (end-to-end with stub LLM) ----------


def test_main_dedups_against_scope_log(tmp_path, monkeypatch):
    # Prepare a scope log with 1 mined query.
    scope_log = tmp_path / "scope-log.jsonl"
    scope_log.write_text(
        '{"query":"repo:foo/bar is:issue flicker","repos":["foo/bar"]}\n'
    )

    out = tmp_path / "new.yaml"
    # LLM proposes 3 queries: 1 duplicate of the scope log, 2 new.
    stub = _StubLLMClient(
        '{"queries": ['
        '"repo:foo/bar is:issue flicker", '   # dup
        '"repo:zog/qux is:issue invisible", '  # new
        '"repo:zog/qux is:pr is:merged fix"'   # new
        ']}'
    )

    rc = main(
        argv=[
            "--instruction", "test",
            "--scope-log", str(scope_log),
            "--out", str(out),
            "--max-queries", "5",
        ],
        llm_client_factory=lambda backend, model: stub,
    )
    assert rc == 0

    loaded = yaml.safe_load(out.read_text())
    assert loaded["queries"]["issue"] == [
        "repo:zog/qux is:issue invisible",
        "repo:zog/qux is:pr is:merged fix",
    ]
    # Verify the LLM was given the existing scope as context
    msg = stub.calls[0]["messages"][0]["content"]
    assert "repo:foo/bar is:issue flicker" in msg
    assert "foo/bar: 1" in msg


def test_main_works_with_empty_scope_log(tmp_path):
    out = tmp_path / "new.yaml"
    stub = _StubLLMClient('{"queries": ["repo:foo/bar fresh"]}')
    rc = main(
        argv=[
            "--instruction", "test",
            "--scope-log", str(tmp_path / "missing.jsonl"),
            "--out", str(out),
            "--max-queries", "3",
        ],
        llm_client_factory=lambda backend, model: stub,
    )
    assert rc == 0
    loaded = yaml.safe_load(out.read_text())
    assert loaded["queries"]["issue"] == ["repo:foo/bar fresh"]


# ---------- _build_llm_client ----------


def test_build_llm_client_codex_cli():
    from gpa.eval.curation.gen_queries import _build_llm_client
    client = _build_llm_client("codex-cli", model="ignored")
    from gpa.eval.curation.llm_client import CodexCliLLMClient
    assert isinstance(client, CodexCliLLMClient)
