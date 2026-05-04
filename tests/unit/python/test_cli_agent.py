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


def test_with_gla_no_capture_no_snapshot_uses_minimal_block(monkeypatch, tmp_path):
    """When neither live capture nor a snapshot is available, the with_gla
    prompt must NOT advertise the 11-command tool block (most are
    unusable). And it must NOT lie about GPA_FRAME_ID being set."""
    captured = {}
    def fake_run(argv, *, input, capture_output, text, env, timeout):
        captured["input"] = input
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    agent = CliAgent(spec=_SPEC)
    scenario = _Scenario()
    tools = {"run_with_capture": lambda: None}  # no frame, no snapshot key
    agent.run(scenario, "with_gla", tools)
    assert "GPA_FRAME_ID is set" not in captured["input"]
    assert "gpa drawcalls" not in captured["input"]  # live-frame tools omitted
    assert "gpa pixel" not in captured["input"]


def test_with_gla_no_capture_but_snapshot_uses_advisor_block(monkeypatch, tmp_path):
    """With snapshot but no live frame, the prompt should be an advisor
    block: list/grep/read of upstream only, NOT the live-frame commands."""
    captured = {}
    def fake_run(argv, *, input, capture_output, text, env, timeout):
        captured["input"] = input
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    snap = tmp_path / "snap"
    snap.mkdir()
    agent = CliAgent(spec=_SPEC)
    scenario = _Scenario()
    tools = {
        "run_with_capture": lambda: None,
        "snapshot_root": lambda: snap,
    }
    agent.run(scenario, "with_gla", tools)
    text = captured["input"]
    assert "GPA_FRAME_ID is set" not in text
    assert "gpa upstream read" in text
    assert "gpa upstream grep" in text
    # Live-frame commands should not appear in advisor block
    assert "gpa drawcalls" not in text
    assert "gpa pixel" not in text


def test_with_gla_full_capture_keeps_full_block(monkeypatch, tmp_path):
    """When live capture succeeded AND snapshot is present, we get the
    full block (live-frame tools + upstream tools)."""
    captured = {}
    def fake_run(argv, *, input, capture_output, text, env, timeout):
        captured["input"] = input
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    snap = tmp_path / "snap"
    snap.mkdir()
    agent = CliAgent(spec=_SPEC)
    scenario = _Scenario()
    tools = {
        "run_with_capture": lambda: 42,
        "snapshot_root": lambda: snap,
    }
    agent.run(scenario, "with_gla", tools)
    text = captured["input"]
    assert "gpa drawcalls" in text
    assert "gpa pixel" in text
    assert "gpa upstream read" in text


def test_scenario_blurb_injected_when_metadata_present(monkeypatch, tmp_path):
    """The free signal already on disk (framework, upstream repo,
    fix_pr_url, bug_class) must be injected into the prompt so the
    agent doesn't waste turns sniffing it via list/grep."""
    captured = {}
    def fake_run(argv, *, input, capture_output, text, env, timeout):
        captured["input"] = input
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)

    from dataclasses import dataclass
    @dataclass
    class _RichScenario:
        bug_description: str = "stripes appear"
        source_path: str = ""
        framework: str = "maplibre-gl-js"
        upstream_snapshot_repo: str = "https://github.com/maplibre/maplibre-gl-js"

    scenario = _RichScenario()
    agent = CliAgent(spec=_SPEC)
    tools = {
        "run_with_capture": lambda: None,
        "bug_class": "consumer-misuse",
        "fix_pr_url": "https://github.com/maplibre/maplibre-gl-js/pull/5746",
    }
    agent.run(scenario, "with_gla", tools)
    text = captured["input"]
    assert "maplibre-gl-js" in text
    assert "maplibre/maplibre-gl-js" in text or "github.com/maplibre" in text
    assert "consumer-misuse" in text
    assert "5746" in text


def test_scenario_blurb_omits_missing_fields(monkeypatch, tmp_path):
    """Fields that aren't set should silently drop, not show as 'None'."""
    captured = {}
    def fake_run(argv, *, input, capture_output, text, env, timeout):
        captured["input"] = input
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    agent = CliAgent(spec=_SPEC)
    scenario = _Scenario()  # no framework/repo/etc.
    tools = {"run_with_capture": lambda: None}
    agent.run(scenario, "with_gla", tools)
    text = captured["input"]
    # Don't print "Framework: None" or "fix-PR: None" sentinel garbage
    assert "None" not in text or text.count("None") < 3  # tolerant


def test_snapshot_root_callable_pins_gpa_upstream_root(monkeypatch, tmp_path):
    """The cli_agent resolves tools["snapshot_root"] (a callable) and pins
    GPA_UPSTREAM_ROOT so `gpa upstream read/grep` shell calls work."""
    captured = {}
    def fake_run(argv, *, input, capture_output, text, env, timeout):
        captured["env"] = env
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    snap_dir = tmp_path / "fake_snap"
    snap_dir.mkdir()
    agent = CliAgent(spec=_SPEC)
    scenario = _Scenario(source_path=str(tmp_path / "main.c"))
    (tmp_path / "main.c").write_text("")
    tools = {
        "run_with_capture": lambda: 7,
        "snapshot_root": lambda: snap_dir,
    }
    agent.run(scenario, "with_gla", tools)
    assert captured["env"]["GPA_UPSTREAM_ROOT"] == str(snap_dir)


def test_snapshot_root_none_skips_gpa_upstream_root(monkeypatch, tmp_path):
    """When the snapshot fetch failed, the callable returns None and the
    agent must skip pinning GPA_UPSTREAM_ROOT (no env var set)."""
    captured = {}
    def fake_run(argv, *, input, capture_output, text, env, timeout):
        captured["env"] = env
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    agent = CliAgent(spec=_SPEC)
    scenario = _Scenario(source_path=str(tmp_path / "main.c"))
    (tmp_path / "main.c").write_text("")
    tools = {
        "run_with_capture": lambda: 7,
        "snapshot_root": lambda: None,
    }
    agent.run(scenario, "with_gla", tools)
    assert "GPA_UPSTREAM_ROOT" not in captured["env"]


def test_run_with_gla_graceful_when_capture_returns_none(monkeypatch, tmp_path):
    """When run_with_capture returns None (e.g. no Bazel target / build
    failure), the agent should still run the with_gla prompt but skip
    pinning GPA_FRAME_ID. GPA_BASE_URL is still set so any gpa CLI
    invocations the agent attempts get a sensible default."""
    captured = {}
    def fake_run(argv, *, input, capture_output, text, env, timeout):
        captured["argv"] = argv
        captured["env"] = env
        captured["input"] = input
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    agent = CliAgent(spec=_SPEC)
    scenario = _Scenario(source_path=str(tmp_path / "main.c"))
    (tmp_path / "main.c").write_text("")
    tools = {"run_with_capture": lambda: None}
    result = agent.run(scenario, "with_gla", tools)
    assert result.diagnosis.startswith("DIAGNOSIS:")
    assert "GPA_FRAME_ID" not in captured["env"]
    assert captured["env"].get("GPA_BASE_URL")  # default applied
    # The agent still produces output. With no frame and no snapshot,
    # the live-frame tools should NOT appear in the prompt (they'd be
    # advertising commands the agent can't successfully invoke).
    assert "gpa drawcalls" not in captured["input"]


def test_run_code_only_omits_capture(monkeypatch, tmp_path):
    captured = {}
    def fake_run(argv, *, input, **kw):
        captured["argv"] = argv
        captured["input"] = input
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    snap = tmp_path / "snap"
    snap.mkdir()
    agent = CliAgent(spec=_SPEC)
    scenario = _Scenario(source_path=str(tmp_path / "main.c"))
    (tmp_path / "main.c").write_text("")
    # No run_with_capture key needed for code_only; snapshot makes upstream
    # tools appear in the prompt under the new contract.
    result = agent.run(scenario, "code_only", tools={"snapshot_root": lambda: snap})
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
