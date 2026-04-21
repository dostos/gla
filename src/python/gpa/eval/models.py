"""Model registry + budget-aware round planner for OpenGPA eval rounds.

Shared source of truth for model tier -> Claude CLI ``--model`` argument
mapping, and helpers used by per-round dispatcher scripts (see
``scripts/round_runner_template.sh``).

Each round runner imports :data:`MODELS` / :func:`claude_id` rather than
hardcoding model IDs, so bumping a tier (e.g. Sonnet 4.6 -> 4.7) is a
one-line change here.
"""
from __future__ import annotations

from typing import Any

# Tier key -> {claude_id, tier, est_cost_multiplier}
# Multipliers are relative to sonnet = 1.0 (our prior-round baseline).
# Calibrated from observed per-run costs in Round 9 (haiku $0.37,
# sonnet $0.57, opus $0.75). Earlier estimates used list-price ratios
# which over-estimated Opus by ~3.5× because Opus terminates faster
# on hard problems (fewer turns, cleaner reasoning). Re-tune after
# each round.
MODELS: dict[str, dict[str, Any]] = {
    "haiku":  {"claude_id": "claude-haiku-4-5",  "tier": "fast",     "est_cost_multiplier": 0.65},
    "sonnet": {"claude_id": "claude-sonnet-4-6", "tier": "standard", "est_cost_multiplier": 1.0},
    "opus":   {"claude_id": "claude-opus-4-7",   "tier": "strong",   "est_cost_multiplier": 1.4},
}


def model_ids() -> list[str]:
    """Return the tier keys in registry order: haiku, sonnet, opus."""
    return list(MODELS.keys())


def claude_id(tier: str) -> str:
    """Resolve a tier key (``haiku``/``sonnet``/``opus``) to the Claude CLI
    ``--model`` argument value.

    Raises:
        KeyError: if ``tier`` is not a known tier.
    """
    if tier not in MODELS:
        raise KeyError(
            f"Unknown model tier {tier!r}; known tiers: {list(MODELS)}"
        )
    return MODELS[tier]["claude_id"]


def estimate_budget(
    n_runs: int,
    tiers: list[str],
    baseline_per_run: float,
) -> float:
    """Estimate total USD cost for a round.

    Args:
        n_runs: number of runs per tier (i.e. scenarios * modes).
        tiers: tier keys participating in the round.
        baseline_per_run: observed sonnet per-run cost from a prior round
            (USD). Other tiers are scaled via ``est_cost_multiplier``.

    Returns:
        Estimated total USD cost across all (run * tier) combinations.
    """
    if n_runs < 0:
        raise ValueError("n_runs must be non-negative")
    if baseline_per_run < 0:
        raise ValueError("baseline_per_run must be non-negative")
    total = 0.0
    for tier in tiers:
        if tier not in MODELS:
            raise KeyError(f"Unknown tier {tier!r}")
        total += n_runs * baseline_per_run * MODELS[tier]["est_cost_multiplier"]
    return total


def plan_round(
    scenarios: list[str],
    tiers: list[str],
    modes: list[str],
    max_budget_usd: float,
    baseline_per_run: float = 0.50,
) -> dict[str, Any]:
    """Build a budget-aware plan for a round.

    Strategy when over budget:
        1. Drop Opus first (most expensive + most marginal for low-ceiling
           scenarios).
        2. Then drop scenarios from the tail until the estimate fits.

    Args:
        scenarios: scenario names to run.
        tiers: tier keys to evaluate.
        modes: mode keys (typically ``["code_only", "with_gpa"]``).
        max_budget_usd: hard ceiling in USD.
        baseline_per_run: sonnet per-run USD cost used as the scale factor.

    Returns:
        A dict with ``runs`` (total dispatched, scenarios*modes*tiers),
        ``estimated_cost``, ``tiers_dropped``, ``scenarios_dropped``,
        ``reason``, plus echoed ``scenarios``/``tiers``/``modes`` after
        pruning.
    """
    if max_budget_usd < 0:
        raise ValueError("max_budget_usd must be non-negative")
    for tier in tiers:
        if tier not in MODELS:
            raise KeyError(f"Unknown tier {tier!r}")

    scenarios = list(scenarios)
    tiers = list(tiers)
    modes = list(modes)

    tiers_dropped: list[str] = []
    scenarios_dropped: list[str] = []

    def _estimate() -> float:
        n = len(scenarios) * len(modes)
        return estimate_budget(n, tiers, baseline_per_run)

    estimate = _estimate()
    reason = "within budget"

    # Step 1: drop opus first if over budget.
    if estimate > max_budget_usd and "opus" in tiers:
        tiers.remove("opus")
        tiers_dropped.append("opus")
        estimate = _estimate()
        reason = "dropped opus to fit budget"

    # Step 2: drop scenarios from the tail until under budget.
    while estimate > max_budget_usd and scenarios:
        scenarios_dropped.append(scenarios.pop())
        estimate = _estimate()
        reason = "dropped opus and/or scenarios to fit budget"

    # If still over (e.g. empty scenarios but nonzero tiers & modes),
    # surface it — caller should abort.
    if estimate > max_budget_usd:
        reason = "cannot fit budget even after pruning"

    runs = len(scenarios) * len(modes) * len(tiers)

    return {
        "runs": runs,
        "estimated_cost": estimate,
        "tiers_dropped": tiers_dropped,
        "scenarios_dropped": scenarios_dropped,
        "reason": reason,
        "scenarios": scenarios,
        "tiers": tiers,
        "modes": modes,
    }
