import subprocess
from dataclasses import dataclass
import pytest
from gpa.eval.agents.cli_agent import CliAgent, CLAUDE_CLI_SPEC, CODEX_CLI_SPEC
from gpa.eval.agents.cli_spec import CliBackendSpec, CliRunMetrics


@dataclass
class _Scenario:
    description: str = "rendering bug"
    source_path: str = "/tmp/fake_scenario/main.c"


def _stub_parse(stdout, stderr):
    return CliRunMetrics(
        diagnosis="DIAGNOSIS: it broke\nFIX: replace it",
        input_tokens=10, output_tokens=20, tool_calls=2, num_turns=3,
        tool_sequence=("gpa frames", "gpa drawcalls"),
    )


_SPEC = CliBackendSpec(
    name="fake-cli", binary="/bin/true", base_args=("-q",),
    parse_run=_stub_parse, timeout_sec=10,
)


def test_run_with_gla_invokes_capture_and_subprocess(monkeypatch, tmp_path):
    captured = {}
    def fake_run(argv, *, input, capture_output, text, env, timeout):
        captured["argv"] = argv
        captured["input"] = input
        captured["env"] = env
        return subprocess.CompletedProcess(
            argv, returncode=0, stdout="", stderr="",
        )
    monkeypatch.setattr(subprocess, "run", fake_run)
    agent = CliAgent(spec=_SPEC, model="opus-4-7")
    scenario = _Scenario(source_path=str(tmp_path / "main.c"))
    (tmp_path / "main.c").write_text("// hi")
    tools = {"run_with_capture": lambda: 42}
    result = agent.run(scenario, "with_gla", tools)
    assert result.diagnosis.startswith("DIAGNOSIS:")
    assert result.tool_calls == 2
    assert captured["env"]["GPA_FRAME_ID"] == "42"
    assert captured["env"]["GPA_SOURCE_ROOT"] == str(tmp_path)
    assert "--model" in captured["argv"]


def test_run_code_only_omits_capture(monkeypatch, tmp_path):
    captured = {}
    def fake_run(argv, *, input, **kw):
        captured["argv"] = argv
        captured["input"] = input
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    agent = CliAgent(spec=_SPEC)
    scenario = _Scenario(source_path=str(tmp_path / "main.c"))
    (tmp_path / "main.c").write_text("")
    # No run_with_capture key needed for code_only.
    result = agent.run(scenario, "code_only", tools={})
    # Code-only prompt shouldn't list with-gla tools
    assert "gpa drawcalls" not in captured["input"]
    assert "gpa upstream read" in captured["input"]


def test_timeout_returns_diagnosis_marker(monkeypatch):
    def fake_run(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)
    monkeypatch.setattr(subprocess, "run", fake_run)
    agent = CliAgent(spec=_SPEC)
    scenario = _Scenario()
    result = agent.run(scenario, "code_only", tools={})
    assert result.diagnosis == "<timeout>"


def test_pixel_first_tool_sequence_classification():
    seq = ("gpa pixel get", "gpa drawcalls list")
    metrics = CliRunMetrics(
        diagnosis="d", input_tokens=0, output_tokens=0,
        tool_calls=2, num_turns=1, tool_sequence=seq,
    )
    agent = CliAgent(spec=_SPEC)
    result = agent._to_agent_result(metrics, elapsed=0.1)
    assert result.pixel_queries == 1
    assert result.state_queries == 1
    assert result.framebuffer_first is True


def test_claude_preset_constructible():
    assert CLAUDE_CLI_SPEC.binary == "claude"
    assert callable(CLAUDE_CLI_SPEC.parse_run)
    metrics = CLAUDE_CLI_SPEC.parse_run("", "")
    assert metrics.tool_calls == 0


def test_codex_preset_constructible():
    assert CODEX_CLI_SPEC.binary == "codex"
    metrics = CODEX_CLI_SPEC.parse_run("", "")
    assert metrics.tool_calls == 0
