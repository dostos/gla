"""Tests for gpa.eval.models — registry + budget-aware planner."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from gpa.eval.models import (
    MODELS,
    claude_id,
    estimate_budget,
    model_ids,
    plan_round,
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_registry_has_all_three_tiers():
    assert set(model_ids()) == {"haiku", "sonnet", "opus"}


def test_registry_shape():
    for tier, entry in MODELS.items():
        assert "claude_id" in entry
        assert "tier" in entry
        assert "est_cost_multiplier" in entry
        assert isinstance(entry["est_cost_multiplier"], (int, float))
        assert entry["est_cost_multiplier"] > 0


def test_claude_id_resolves_known_tiers():
    assert claude_id("haiku") == "claude-haiku-4-5"
    assert claude_id("sonnet") == "claude-sonnet-4-6"
    assert claude_id("opus") == "claude-opus-4-7"


def test_claude_id_unknown_tier_raises():
    with pytest.raises(KeyError):
        claude_id("gpt-7")


# ---------------------------------------------------------------------------
# Budget estimation
# ---------------------------------------------------------------------------

def test_estimate_budget_sonnet_only():
    # 10 runs at $1/run = $10.
    assert estimate_budget(10, ["sonnet"], 1.0) == pytest.approx(10.0)


def test_estimate_budget_three_tiers_scales_correctly():
    # 10 runs across all 3 tiers at $1/run baseline:
    # haiku 0.3 + sonnet 1.0 + opus 5.0 = 6.3x.
    got = estimate_budget(10, ["haiku", "sonnet", "opus"], 1.0)
    assert got == pytest.approx(10.0 * (0.3 + 1.0 + 5.0))
    # Compared to sonnet-only, the 3-tier round is ~6.3x more expensive.
    sonnet_only = estimate_budget(10, ["sonnet"], 1.0)
    assert got / sonnet_only == pytest.approx(6.3)


def test_estimate_budget_unknown_tier_raises():
    with pytest.raises(KeyError):
        estimate_budget(1, ["mystery"], 1.0)


def test_estimate_budget_negative_inputs_rejected():
    with pytest.raises(ValueError):
        estimate_budget(-1, ["sonnet"], 1.0)
    with pytest.raises(ValueError):
        estimate_budget(1, ["sonnet"], -1.0)


# ---------------------------------------------------------------------------
# plan_round
# ---------------------------------------------------------------------------

def test_plan_round_under_budget_no_pruning():
    # 2 scenarios * 2 modes * 3 tiers = 12 runs.
    # Cost @ $0.50 baseline: 4 * 0.5 * (0.3 + 1.0 + 5.0) = $12.60.
    plan = plan_round(
        scenarios=["a", "b"],
        tiers=["haiku", "sonnet", "opus"],
        modes=["code_only", "with_gpa"],
        max_budget_usd=50.0,
        baseline_per_run=0.50,
    )
    assert plan["runs"] == 12
    assert plan["tiers_dropped"] == []
    assert plan["scenarios_dropped"] == []
    assert plan["reason"] == "within budget"
    assert plan["estimated_cost"] == pytest.approx(12.60)


def test_plan_round_drops_opus_when_over_budget():
    # 10 scenarios * 2 modes = 20 per-tier runs.
    # Three tiers: 20 * 0.5 * 6.3 = $63.
    # Without opus: 20 * 0.5 * (0.3 + 1.0) = $13.
    plan = plan_round(
        scenarios=[f"s{i}" for i in range(10)],
        tiers=["haiku", "sonnet", "opus"],
        modes=["code_only", "with_gpa"],
        max_budget_usd=20.0,
        baseline_per_run=0.50,
    )
    assert "opus" in plan["tiers_dropped"]
    assert plan["scenarios_dropped"] == []
    assert plan["tiers"] == ["haiku", "sonnet"]
    assert plan["estimated_cost"] == pytest.approx(13.0)
    assert plan["runs"] == 10 * 2 * 2
    assert "opus" in plan["reason"]


def test_plan_round_drops_scenarios_when_still_over_after_opus():
    # 40 scenarios * 2 modes * (haiku+sonnet) = 80 * 0.5 * 1.3 = $52.
    # With a $10 cap, opus goes, then scenarios drop until under $10.
    # Per-scenario sonnet+haiku cost (2 modes): 2 * 0.5 * 1.3 = $1.30.
    # $10 / $1.30 ~= 7.69 -> 7 scenarios survive.
    plan = plan_round(
        scenarios=[f"s{i}" for i in range(40)],
        tiers=["haiku", "sonnet", "opus"],
        modes=["code_only", "with_gpa"],
        max_budget_usd=10.0,
        baseline_per_run=0.50,
    )
    assert plan["tiers_dropped"] == ["opus"]
    assert len(plan["scenarios_dropped"]) > 0
    assert plan["estimated_cost"] <= 10.0
    assert len(plan["scenarios"]) == 7
    assert plan["runs"] == len(plan["scenarios"]) * 2 * 2


def test_plan_round_zero_budget_prunes_everything():
    plan = plan_round(
        scenarios=["a", "b"],
        tiers=["haiku", "sonnet", "opus"],
        modes=["code_only"],
        max_budget_usd=0.0,
        baseline_per_run=0.50,
    )
    # All scenarios dropped, opus dropped.
    assert plan["scenarios"] == []
    assert plan["estimated_cost"] == 0.0
    assert plan["runs"] == 0


def test_plan_round_rejects_unknown_tier():
    with pytest.raises(KeyError):
        plan_round(
            scenarios=["a"],
            tiers=["gpt-7"],
            modes=["code_only"],
            max_budget_usd=10.0,
        )


def test_plan_round_does_not_mutate_caller_lists():
    scenarios = ["a", "b", "c"]
    tiers = ["haiku", "sonnet", "opus"]
    modes = ["code_only"]
    plan_round(scenarios, tiers, modes, max_budget_usd=0.01, baseline_per_run=0.5)
    assert scenarios == ["a", "b", "c"]
    assert tiers == ["haiku", "sonnet", "opus"]
    assert modes == ["code_only"]


# ---------------------------------------------------------------------------
# CLI (python -m gpa.eval.plan)
# ---------------------------------------------------------------------------

def test_plan_cli_under_budget_exits_zero(tmp_path):
    proc = subprocess.run(
        [
            sys.executable, "-m", "gpa.eval.plan",
            "--scenarios", "a", "b",
            "--tiers", "haiku", "sonnet",
            "--modes", "code_only",
            "--max-budget-usd", "100",
            "--baseline-per-run", "0.50",
        ],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src/python", "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["tiers_dropped"] == []
    assert data["scenarios_dropped"] == []


def test_plan_cli_pruned_exits_two():
    proc = subprocess.run(
        [
            sys.executable, "-m", "gpa.eval.plan",
            "--scenarios", *[f"s{i}" for i in range(20)],
            "--tiers", "haiku", "sonnet", "opus",
            "--modes", "code_only", "with_gpa",
            "--max-budget-usd", "15",
            "--baseline-per-run", "0.50",
        ],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src/python", "PATH": "/usr/bin:/bin"},
    )
    # Opus drop alone: 20 * 2 * 0.5 * 1.3 = $26 > $15 -> scenarios also drop -> rc=2.
    assert proc.returncode == 2, proc.stderr
    data = json.loads(proc.stdout)
    assert "opus" in data["tiers_dropped"]
