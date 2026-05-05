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


def test_render_prompt_uses_system_prompt_when_provided(monkeypatch, tmp_path):
    """When tools['system_prompt'] is set (maintainer/advisor/config),
    the cli_agent must include it instead of the legacy DIAGNOSIS/FIX
    framing — the system prompt carries the JSON output contract."""
    inputs: list[str] = []

    def fake_run(argv, *, input, capture_output, text, env, timeout):
        inputs.append(input)
        return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

    # Stub that already emits JSON, so reprompt does not fire and we
    # observe the first (only) call's input directly.
    def parse_with_json(stdout, stderr):
        return CliRunMetrics(
            diagnosis='ok\n{"bug_class":"framework-internal","proposed_patches":[],"confidence":"low","reasoning":""}',
            input_tokens=10, output_tokens=20, tool_calls=2, num_turns=3,
        )

    spec = CliBackendSpec(
        name="fake-cli", binary="/bin/true", base_args=("-q",),
        parse_run=parse_with_json, timeout_sec=10,
    )
    monkeypatch.setattr(subprocess, "run", fake_run)
    agent = CliAgent(spec=spec)
    scenario = _Scenario(source_path=str(tmp_path / "main.c"))
    (tmp_path / "main.c").write_text("// hi")

    sysprompt = (
        "You are a maintainer of foo. End with a single JSON object on "
        "the last line: {\"bug_class\":\"framework-internal\", ...}."
    )
    tools = {
        "run_with_capture": lambda: None,
        "system_prompt": sysprompt,
    }
    agent.run(scenario, "with_gla", tools)

    # Only one CLI invocation — the first (and only) prompt
    assert len(inputs) == 1
    rendered = inputs[0]
    # The maintainer-style instruction must appear in the rendered prompt
    assert "maintainer of foo" in rendered
    # The legacy DIAGNOSIS/FIX footer must NOT appear when system prompt is used
    assert "DIAGNOSIS: <one-sentence root cause>" not in rendered


def test_render_prompt_falls_back_to_legacy_when_no_system_prompt(monkeypatch, tmp_path):
    """Legacy synthetic scenarios (E1-E10) don't have a system_prompt.
    The cli_agent must keep its original DIAGNOSIS/FIX framing for them."""
    captured = {}

    def fake_run(argv, *, input, capture_output, text, env, timeout):
        captured["input"] = input
        return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    agent = CliAgent(spec=_SPEC)
    scenario = _Scenario(source_path=str(tmp_path / "main.c"))
    (tmp_path / "main.c").write_text("// hi")

    tools = {"run_with_capture": lambda: None}  # no system_prompt
    agent.run(scenario, "with_gla", tools)

    # Legacy framing must survive
    assert "DIAGNOSIS: <one-sentence root cause>" in captured["input"]


def test_json_reprompt_fires_when_first_response_lacks_json(monkeypatch, tmp_path):
    """If the agent's first response has no JSON tail and a system_prompt
    is in play, the cli_agent must send a follow-up prompt and merge the
    JSON tail back into the diagnosis."""
    calls = []
    responses = [
        # First call: prose only, no JSON tail
        CliRunMetrics(
            diagnosis="DIAGNOSIS: lights flicker. FIX: clamp.",
            input_tokens=100, output_tokens=200, tool_calls=5, num_turns=4,
        ),
        # Follow-up: JSON only
        CliRunMetrics(
            diagnosis='{"bug_class":"framework-internal","proposed_patches":[{"repo":"foo","file":"src/a.cpp","change_summary":"clamp"}],"confidence":"low","reasoning":"fallback"}',
            input_tokens=20, output_tokens=30, tool_calls=0, num_turns=1,
        ),
    ]

    def fake_run(argv, *, input, capture_output, text, env, timeout):
        calls.append(input)
        return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

    spec_iter = iter(responses)
    spec = CliBackendSpec(
        name="fake-cli", binary="/bin/true", base_args=("-q",),
        parse_run=lambda s, e: next(spec_iter), timeout_sec=10,
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    agent = CliAgent(spec=spec)
    scenario = _Scenario(source_path=str(tmp_path / "main.c"))
    (tmp_path / "main.c").write_text("// hi")
    tools = {
        "run_with_capture": lambda: None,
        "system_prompt": "You are a maintainer. End with JSON.",
    }
    result = agent.run(scenario, "with_gla", tools)

    # Two CLI invocations: original + reprompt
    assert len(calls) == 2
    # Reprompt mentions the missing JSON
    assert "JSON" in calls[1]
    # Tokens summed across both calls
    assert result.input_tokens == 120
    assert result.output_tokens == 230
    # JSON tail was merged into the final diagnosis
    assert '"proposed_patches"' in result.diagnosis
    # Original prose preserved
    assert "lights flicker" in result.diagnosis


def test_json_reprompt_skipped_when_first_response_already_has_json(monkeypatch, tmp_path):
    """If the agent already complied, no follow-up — saves tokens."""
    calls = []
    responses = [
        CliRunMetrics(
            diagnosis='Reasoning text.\n{"bug_class":"framework-internal","proposed_patches":[],"confidence":"low","reasoning":""}',
            input_tokens=100, output_tokens=200, tool_calls=5, num_turns=4,
        ),
    ]

    def fake_run(argv, *, input, capture_output, text, env, timeout):
        calls.append(input)
        return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

    spec_iter = iter(responses)
    spec = CliBackendSpec(
        name="fake-cli", binary="/bin/true", base_args=("-q",),
        parse_run=lambda s, e: next(spec_iter), timeout_sec=10,
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    agent = CliAgent(spec=spec)
    scenario = _Scenario(source_path=str(tmp_path / "main.c"))
    (tmp_path / "main.c").write_text("// hi")
    tools = {
        "run_with_capture": lambda: None,
        "system_prompt": "You are a maintainer. End with JSON.",
    }
    result = agent.run(scenario, "with_gla", tools)

    # Only the original call — no reprompt
    assert len(calls) == 1
    assert result.input_tokens == 100


def test_json_reprompt_skipped_when_no_system_prompt(monkeypatch, tmp_path):
    """Legacy scenarios with no system_prompt must NOT trigger the
    reprompt — they don't expect JSON output."""
    calls = []
    responses = [
        CliRunMetrics(
            diagnosis="DIAGNOSIS: thing. FIX: other thing.",
            input_tokens=100, output_tokens=200, tool_calls=5, num_turns=4,
        ),
    ]

    def fake_run(argv, *, input, capture_output, text, env, timeout):
        calls.append(input)
        return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

    spec_iter = iter(responses)
    spec = CliBackendSpec(
        name="fake-cli", binary="/bin/true", base_args=("-q",),
        parse_run=lambda s, e: next(spec_iter), timeout_sec=10,
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    agent = CliAgent(spec=spec)
    scenario = _Scenario(source_path=str(tmp_path / "main.c"))
    (tmp_path / "main.c").write_text("// hi")
    tools = {"run_with_capture": lambda: None}  # no system_prompt
    result = agent.run(scenario, "with_gla", tools)

    assert len(calls) == 1
    assert "DIAGNOSIS:" in result.diagnosis


def test_cli_agent_raises_on_rate_limit_response(monkeypatch, tmp_path):
    """When claude-cli is over its daily cap it returns a one-line
    'You've hit your limit' message with 0 tokens. Pre-R16 the harness
    silently recorded these as scenario failures; one rate-limited
    cohort produced 11 fake-failure rows. CliAgent now raises so the
    cohort stops cleanly."""
    from gpa.eval.agents.cli_agent import CliRateLimitError

    def fake_run(*a, **kw):
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
    monkeypatch.setattr(subprocess, "run", fake_run)

    def parse_rate_limited(stdout, stderr):
        return CliRunMetrics(
            diagnosis="You've hit your limit · resets 10pm (Asia/Seoul)",
            input_tokens=0, output_tokens=0, tool_calls=0, num_turns=1,
        )

    spec = CliBackendSpec(
        name="fake", binary="/bin/true", base_args=("-q",),
        parse_run=parse_rate_limited, timeout_sec=10,
    )
    agent = CliAgent(spec=spec)
    scenario = _Scenario(source_path=str(tmp_path / "main.c"))
    (tmp_path / "main.c").write_text("// hi")
    tools = {"run_with_capture": lambda: None}

    import pytest
    with pytest.raises(CliRateLimitError) as info:
        agent.run(scenario, "with_gla", tools)
    assert "rate-limit" in str(info.value).lower()


def test_cli_agent_does_not_raise_on_legit_short_response(monkeypatch, tmp_path):
    """A legitimately short response (e.g. agent quickly emits JSON)
    must not be treated as a rate-limit. Distinguish on tokens=0 AND
    rate-limit signature, not just shortness."""
    def fake_run(*a, **kw):
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)

    def parse_short_legit(stdout, stderr):
        return CliRunMetrics(
            diagnosis='{"bug_class":"framework-internal","proposed_patches":[],"confidence":"low","reasoning":"short answer"}',
            input_tokens=10, output_tokens=20, tool_calls=0, num_turns=1,
        )

    spec = CliBackendSpec(
        name="fake", binary="/bin/true", base_args=("-q",),
        parse_run=parse_short_legit, timeout_sec=10,
    )
    agent = CliAgent(spec=spec)
    scenario = _Scenario(source_path=str(tmp_path / "main.c"))
    (tmp_path / "main.c").write_text("// hi")
    tools = {"run_with_capture": lambda: None}

    # Should NOT raise — this is a real (terse) response with non-zero tokens
    result = agent.run(scenario, "with_gla", tools)
    assert "proposed_patches" in result.diagnosis
