"""Tests for parse_claude_stream_json.

Fixture: tests/unit/python/fixtures/claude_stream.jsonl
The fixture is fabricated from the documented Anthropic stream-json event
schema and validated against a real capture (echo "Say hello in one word." |
claude -p --output-format stream-json --verbose) on 2026-05-02. It covers:
  - system/init event (ignored)
  - three assistant turns with tool_use blocks (5 tool calls total)
  - a malformed line (must be skipped)
  - a result event with canonical usage totals and num_turns
"""
from __future__ import annotations
import pathlib
from gpa.eval.agents.cli_parsers import parse_claude_stream_json
from gpa.eval.agents.cli_spec import CliRunMetrics

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "claude_stream.jsonl"


def _load_fixture() -> str:
    return FIXTURE.read_text()


class TestParseClaudeStreamJson:
    def test_success_path(self):
        """All metrics extracted from fixture."""
        text = _load_fixture()
        m = parse_claude_stream_json(text, "")
        assert isinstance(m, CliRunMetrics)
        # result event: "num_turns": 4
        assert m.num_turns == 4
        # 5 tool_use blocks across three assistant turns
        assert m.tool_calls == 5
        # result event usage: input_tokens=35, output_tokens=63
        assert m.input_tokens == 35
        assert m.output_tokens == 63
        # diagnosis from result.result field
        assert "uniform not uploaded" in m.diagnosis

    def test_tool_sequence_order(self):
        """tool_sequence preserves insertion order."""
        text = _load_fixture()
        m = parse_claude_stream_json(text, "")
        # First tool in fixture is Bash, then Read, Bash, Grep, Bash
        assert m.tool_sequence[0] == "Bash"
        assert len(m.tool_sequence) == 5

    def test_empty_stdout_returns_zeros(self):
        """Empty input produces a zeroed CliRunMetrics."""
        m = parse_claude_stream_json("", "")
        assert m.diagnosis == ""
        assert m.input_tokens == 0
        assert m.output_tokens == 0
        assert m.tool_calls == 0
        assert m.num_turns == 0
        assert m.tool_sequence == ()

    def test_malformed_line_tolerated(self):
        """A single bad JSON line must not raise."""
        text = 'this is not json\n{"type":"result","result":"ok","num_turns":1,"usage":{"input_tokens":1,"output_tokens":2}}\n'
        m = parse_claude_stream_json(text, "")
        assert m.diagnosis == "ok"
        assert m.num_turns == 1

    def test_tool_use_count_only_from_assistant(self):
        """tool_use blocks inside user/result events must NOT be counted."""
        text = (
            '{"type":"user","message":{"content":[{"type":"tool_use","name":"Bash"}]}}\n'
            '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Read","input":{}}],"usage":{"input_tokens":5,"output_tokens":3}}}\n'
            '{"type":"result","result":"done","num_turns":1,"usage":{"input_tokens":5,"output_tokens":3}}\n'
        )
        m = parse_claude_stream_json(text, "")
        assert m.tool_calls == 1
        assert m.tool_sequence == ("Read",)

    def test_result_usage_overrides_per_turn_sums(self):
        """When result event has usage, it replaces accumulated per-turn values."""
        text = (
            '{"type":"assistant","message":{"content":[],"usage":{"input_tokens":100,"output_tokens":50}}}\n'
            '{"type":"result","result":"final","num_turns":2,"usage":{"input_tokens":999,"output_tokens":777}}\n'
        )
        m = parse_claude_stream_json(text, "")
        assert m.input_tokens == 999
        assert m.output_tokens == 777
