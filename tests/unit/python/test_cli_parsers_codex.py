"""Tests for parse_codex_ndjson.

Fixture: tests/unit/python/fixtures/codex_events.jsonl
The fixture is based on a real capture of `codex exec --skip-git-repo-check
--json -s read-only -C /tmp "echo hello"` on 2026-05-02 and extended with
gpa tool calls. Real event schema uses flat item.started/item.completed
events with a turn.completed usage block — different from the msg-wrapper
schema in the original spec. The parser handles both schemas.

Fixture covers:
  - thread.started / turn.started (ignored for metrics)
  - two gpa command_execution items (tool calls)
  - one non-gpa command_execution (cat, not counted)
  - one malformed line (must be skipped)
  - one agent_message with final diagnosis
  - turn.completed with input/output token counts
"""
from __future__ import annotations
import pathlib
from gpa.eval.agents.cli_parsers import parse_codex_ndjson
from gpa.eval.agents.cli_spec import CliRunMetrics

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "codex_events.jsonl"


def _load_fixture() -> str:
    return FIXTURE.read_text()


class TestParseCodexNdjson:
    def test_success_path(self):
        """All metrics correctly extracted from fixture."""
        text = _load_fixture()
        m = parse_codex_ndjson(text, "")
        assert isinstance(m, CliRunMetrics)
        # Two gpa commands (frames, drawcalls); cat is NOT a gpa call
        assert m.tool_calls == 2
        assert m.tool_sequence == ("gpa frames", "gpa drawcalls")
        # diagnosis from agent_message
        assert "glUniform" in m.diagnosis
        # token counts from turn.completed
        assert m.input_tokens == 30318
        assert m.output_tokens == 44

    def test_num_turns_counts_agent_messages(self):
        """Each agent_message item increments num_turns."""
        text = _load_fixture()
        m = parse_codex_ndjson(text, "")
        assert m.num_turns == 1

    def test_only_agent_messages_no_tools(self):
        """Agent message without any tool calls returns zero tool_calls."""
        text = (
            '{"type":"item.completed","item":{"id":"i0","type":"agent_message","text":"All done."}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":10}}\n'
        )
        m = parse_codex_ndjson(text, "")
        assert m.tool_calls == 0
        assert m.diagnosis == "All done."
        assert m.input_tokens == 100
        assert m.output_tokens == 10

    def test_malformed_lines_tolerated(self):
        """Malformed JSON lines must not raise."""
        text = (
            'not json at all\n'
            '{"type":"item.completed","item":{"id":"i0","type":"agent_message","text":"ok"}}\n'
        )
        m = parse_codex_ndjson(text, "")
        assert m.diagnosis == "ok"

    def test_token_fallback_from_stderr(self):
        """When turn.completed is absent, fall back to stderr summary line."""
        stdout = '{"type":"item.completed","item":{"id":"i0","type":"agent_message","text":"done"}}\n'
        stderr = "some preamble\ntokens used: 12,345\nother line\n"
        m = parse_codex_ndjson(stdout, stderr)
        assert m.input_tokens == 12345
        assert m.output_tokens == 0   # codex doesn't split input/output in summary

    def test_non_gpa_commands_not_counted(self):
        """Shell calls that don't start with `gpa` must NOT increment tool_calls."""
        text = (
            '{"type":"item.completed","item":{"id":"i0","type":"command_execution",'
            '"command":"/bin/bash -lc \'ls /tmp\'","aggregated_output":"","exit_code":0}}\n'
            '{"type":"item.completed","item":{"id":"i1","type":"agent_message","text":"listed"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":2}}\n'
        )
        m = parse_codex_ndjson(text, "")
        assert m.tool_calls == 0
        assert m.tool_sequence == ()
