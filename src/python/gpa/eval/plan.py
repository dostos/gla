"""CLI entry for the budget-aware round planner.

Used by ``scripts/round_runner_template.sh`` to validate a proposed round
before dispatching any ``claude -p`` processes.

Usage::

    python -m gpa.eval.plan \
        --scenarios scen_a scen_b scen_c \
        --tiers haiku sonnet opus \
        --modes code_only with_gpa \
        --max-budget-usd 150 \
        --baseline-per-run 0.50

Emits a JSON object on stdout (the :func:`gpa.eval.models.plan_round`
result). Exit code ``0`` if the plan fits the budget without pruning;
``2`` if pruning was needed (tiers or scenarios were dropped); ``3`` if
the budget cannot be met even after pruning.
"""
from __future__ import annotations

import argparse
import json
import sys

from gpa.eval.models import plan_round


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gpa.eval.plan")
    p.add_argument("--scenarios", nargs="+", required=True)
    p.add_argument("--tiers", nargs="+", default=["haiku", "sonnet", "opus"])
    p.add_argument("--modes", nargs="+", default=["code_only", "with_gpa"])
    p.add_argument("--max-budget-usd", type=float, required=True)
    p.add_argument("--baseline-per-run", type=float, default=0.50)
    args = p.parse_args(argv)

    plan = plan_round(
        scenarios=args.scenarios,
        tiers=args.tiers,
        modes=args.modes,
        max_budget_usd=args.max_budget_usd,
        baseline_per_run=args.baseline_per_run,
    )
    print(json.dumps(plan, indent=2))

    if plan["estimated_cost"] > args.max_budget_usd:
        return 3
    if plan["tiers_dropped"] or plan["scenarios_dropped"]:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
