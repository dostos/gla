"""Tests for gpa.eval.cli -- Task 26.

Verifies that:
1. --agent-backend causes build_agent_fn to be called with the right backend.
2. --dry-run bypasses build_agent_fn and uses _stub_agent directly.
3. The live API path (optional, gated by ANTHROPIC_API_KEY).
"""
from __future__ import annotations

import os
import pytest


# ---------------------------------------------------------------------------
# Stubbed unit test: build_agent_fn is patched, no real LLM call.
# ---------------------------------------------------------------------------


def test_agent_backend_flag_calls_factory(monkeypatch):
    """--agent-backend codex-cli passes backend='codex-cli' to build_agent_fn."""
    import gpa.eval.cli as cli_mod

    factory_calls: list[dict] = []

    def _fake_build_agent_fn(backend, model=None, api_key=None):
        factory_calls.append({"backend": backend, "model": model, "api_key": api_key})
        # Return a simple stub agent that the harness can call.
        def _agent(scenario, mode, tools):
            return "[stub]", 0, 0, 0, 1, 0.0
        return _agent

    # Patch the factory at the import-time location used by _cmd_run.
    monkeypatch.setattr(
        "gpa.eval.agents.factory.build_agent_fn",
        _fake_build_agent_fn,
    )

    # Patch harness so we don't spin up a real EvalHarness.
    class _FakeHarness:
        def __init__(self, config):
            pass
        def run_all(self, agent_fn, scenarios=None, modes=None):
            # Call agent_fn to confirm it was set correctly.
            class _FakeScenario:
                id = "test_scenario"
            result = agent_fn(_FakeScenario(), "code_only", {"read_source": lambda: "x"})
            return [result]
        def save_results(self, path):
            pass

    monkeypatch.setattr("gpa.eval.harness.EvalHarness", _FakeHarness)

    rc = cli_mod.main([
        "run",
        "--scenario", "test_scenario",
        "--mode", "code_only",
        "--agent-backend", "codex-cli",
    ])
    assert rc == 0
    assert len(factory_calls) == 1
    assert factory_calls[0]["backend"] == "codex-cli"


# ---------------------------------------------------------------------------
# --dry-run test: _stub_agent is used, factory is NOT called.
# ---------------------------------------------------------------------------


def test_dry_run_uses_stub_agent_not_factory(monkeypatch):
    """--dry-run should use _stub_agent and NOT call build_agent_fn."""
    import gpa.eval.cli as cli_mod

    factory_called = []

    def _spy_build_agent_fn(backend, model=None, api_key=None):
        factory_called.append(backend)
        def _agent(scenario, mode, tools):
            return "[should not be reached]", 0, 0, 0, 1, 0.0
        return _agent

    monkeypatch.setattr(
        "gpa.eval.agents.factory.build_agent_fn",
        _spy_build_agent_fn,
    )

    stub_agent_calls: list[str] = []
    original_stub = cli_mod._stub_agent

    def _tracked_stub(scenario, mode, tools):
        stub_agent_calls.append(scenario.id)
        return original_stub(scenario, mode, tools)

    monkeypatch.setattr(cli_mod, "_stub_agent", _tracked_stub)

    class _FakeHarness:
        def __init__(self, config):
            pass
        def run_all(self, agent_fn, scenarios=None, modes=None):
            class _FakeScenario:
                id = "dry_run_scenario"
            agent_fn(_FakeScenario(), "code_only", {"read_source": lambda: "hello world"})
            return []
        def save_results(self, path):
            pass

    monkeypatch.setattr("gpa.eval.harness.EvalHarness", _FakeHarness)

    rc = cli_mod.main([
        "run",
        "--scenario", "dry_run_scenario",
        "--mode", "code_only",
        "--dry-run",
    ])
    assert rc == 0
    assert factory_called == [], "build_agent_fn must NOT be called with --dry-run"
    assert stub_agent_calls == ["dry_run_scenario"]


# ---------------------------------------------------------------------------
# Live test (optional): gated by ANTHROPIC_API_KEY.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="needs ANTHROPIC_API_KEY",
)
def test_live_api_backend_runs_scenario(tmp_path):
    """Smoke test: --agent-backend api creates a real ApiAgent."""
    import gpa.eval.cli as cli_mod

    rc = cli_mod.main([
        "run",
        "--scenario", "e1_state_leak",
        "--mode", "code_only",
        "--agent-backend", "api",
        "--output", str(tmp_path / "results.json"),
    ])
    assert rc == 0
    assert (tmp_path / "results.json").exists()
