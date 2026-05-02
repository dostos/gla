"""Integration smoke test: codex-cli backend on a real eval scenario.

Skipped by default. Enable with `GPA_RUN_LIVE_EVAL=1` env var, OR run with
the `slow` marker explicitly.

Why skipped: the test launches the real `codex` CLI which:
- requires a network-connected OpenAI account
- spends real tokens
- can take 1-5 minutes per scenario

The test exists to catch end-to-end regressions before they ship.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    shutil.which("codex") is None,
    reason="codex CLI not installed",
)


@pytest.mark.skipif(
    not os.environ.get("GPA_RUN_LIVE_EVAL"),
    reason="live eval disabled (set GPA_RUN_LIVE_EVAL=1 to enable)",
)
@pytest.mark.slow
def test_codex_eval_code_only_smoke(tmp_path):
    """Run smallest synthetic scenario via codex-cli, code_only mode."""
    from gpa.eval.harness import EvalHarness
    from gpa.eval.agents.factory import build_agent_fn

    # Pick a scenario that's small, code-only friendly, and exists in tree.
    # e1_state_leak is the canonical synthetic scenario referenced in CLAUDE.md.
    scenario_id = "e1_state_leak"

    harness = EvalHarness(config={})
    agent_fn = build_agent_fn(backend="codex-cli", model=None)

    result = harness.run_scenario(scenario_id, "code_only", agent_fn)

    assert result.diagnosis_text, "expected non-empty diagnosis"
    # Tool-call count is 0 in code_only mode if the agent only reads
    # source via shell, since `gpa source read` is one tool call but
    # the parser counts shell `gpa ...` invocations.
    # Tolerate 0 tool calls to make the test robust.
