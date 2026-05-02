"""Tests for gpa.eval.agents base types."""
import pytest
from gpa.eval.agents import AgentBackend, AgentResult


def test_agent_backend_is_abstract():
    with pytest.raises(TypeError):
        AgentBackend()  # type: ignore[abstract]


def test_agent_result_fields():
    r = AgentResult(
        diagnosis="x", input_tokens=1, output_tokens=2,
        total_tokens=3, tool_calls=4, num_turns=5,
        time_seconds=0.1, conversation=[],
    )
    assert r.diagnosis == "x"
    assert r.tool_sequence == []
    assert r.pixel_queries == 0
    assert r.state_queries == 0
    assert r.framebuffer_first is False
