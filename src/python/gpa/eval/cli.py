"""CLI entry point for the OpenGPA evaluation harness.

Usage:
    python -m gpa.eval.cli run --scenario e1_state_leak --mode with_gla
    python -m gpa.eval.cli run --all [--scenarios e1,e2] [--modes with_gla,code_only]
    python -m gpa.eval.cli report results.json [--output report.md]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _stub_agent(
    scenario, mode: str, tools: dict
) -> tuple[str, int, int, int, int, float]:
    """Minimal stub agent used for --dry-run and tests."""
    print(f"  [stub] scenario={scenario.id} mode={mode}")
    source = tools["read_source"]()
    diagnosis = f"[stub diagnosis for {scenario.id}]"
    tokens = len(source.split())
    return diagnosis, tokens, 50, 0, 1, 0.0


def _cmd_run(args: argparse.Namespace) -> int:
    """Execute eval scenarios via the harness."""
    from gpa.eval.harness import EvalHarness
    from gpa.eval.scenario import ScenarioMetadata

    config: dict = {}
    if args.config:
        with open(args.config, encoding="utf-8") as fh:
            config = json.load(fh)

    # Override config with CLI flags
    if args.gpa_url:
        config["gpa_base_url"] = args.gpa_url
    if args.token:
        config["gpa_token"] = args.token
    if args.shim:
        config["shim_path"] = args.shim
    if args.model:
        config["model"] = args.model

    judge_client = None
    judge_cache_dir = None
    if not args.no_judge:
        judge_cache_dir = Path(args.judge_cache_dir or ".eval-judge-cache")
        try:
            from gpa.eval.curation.llm_client import (
                ClaudeCodeLLMClient, CodexCliLLMClient, LLMClient,
            )
            backend = args.judge_backend
            if backend == "claude-cli":
                judge_client = ClaudeCodeLLMClient.from_env(model=args.judge_model)
            elif backend == "codex-cli":
                judge_client = CodexCliLLMClient.from_env(model=args.judge_model)
            elif backend == "api":
                judge_client = LLMClient.from_env(model=args.judge_model)
            else:
                print(
                    f"warning: unknown --judge-backend {backend!r}; "
                    "falling back to no-judge mode",
                    file=sys.stderr,
                )
        except Exception as exc:
            print(
                f"warning: judge client setup failed ({exc}); "
                "falling back to no-judge mode",
                file=sys.stderr,
            )
            judge_client = None
            judge_cache_dir = None

    harness = EvalHarness(
        config=config,
        llm_judge_client=judge_client,
        judge_cache_dir=judge_cache_dir,
    )

    # Determine which scenarios / modes to run
    if args.all:
        scenarios = (
            [s.strip() for s in args.scenarios.split(",")]
            if args.scenarios
            else None
        )
        modes = (
            [m.strip() for m in args.modes.split(",")]
            if args.modes
            else None
        )
    else:
        if not args.scenario:
            print("error: --scenario is required unless --all is specified", file=sys.stderr)
            return 1
        scenarios = [args.scenario]
        modes = [args.mode] if args.mode else None

    if args.dry_run:
        agent_fn = _stub_agent
    else:
        from gpa.eval.agents.factory import build_agent_fn
        import os
        agent_fn = build_agent_fn(
            backend=args.agent_backend,
            model=args.agent_model,
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
        )

    results = harness.run_all(
        agent_fn=agent_fn, scenarios=scenarios, modes=modes
    )

    output_path = args.output or "results.json"
    harness.save_results(output_path)
    print(f"Saved {len(results)} result(s) to {output_path}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    """Generate a report from a saved results JSON file."""
    from gpa.eval.harness import EvalHarness
    from gpa.eval.metrics import ReportGenerator

    results = EvalHarness.load_results(args.results_file)
    gen = ReportGenerator()
    md = gen.generate_markdown(results)

    if args.output:
        Path(args.output).write_text(md, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(md)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gpa.eval.cli",
        description="OpenGPA evaluation harness CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- run subcommand ---
    run_p = sub.add_parser("run", help="Execute evaluation scenarios")
    run_p.add_argument("--scenario", help="Scenario ID (e.g. e1_state_leak)")
    run_p.add_argument("--mode", default="with_gla", choices=["with_gla", "code_only"],
                       help="Evaluation mode (default: with_gla)")
    run_p.add_argument("--all", action="store_true",
                       help="Run all scenarios")
    run_p.add_argument("--scenarios",
                       help="Comma-separated scenario IDs when using --all")
    run_p.add_argument("--modes",
                       help="Comma-separated modes when using --all")
    run_p.add_argument("--output", "-o", help="Output path for results JSON (default: results.json)")
    run_p.add_argument("--config", help="Path to JSON config file")
    run_p.add_argument("--gpa-url", help="OpenGPA server base URL")
    run_p.add_argument("--token", help="OpenGPA auth token")
    run_p.add_argument("--shim", help="Path to OpenGPA shim shared library")
    run_p.add_argument("--model", help="LLM model identifier (for metadata)")
    run_p.add_argument(
        "--agent-backend", default="api",
        choices=["api", "claude-cli", "codex-cli"],
        help="Agent backend to use (default: api)",
    )
    run_p.add_argument(
        "--agent-model", default=None,
        help="Model override for the agent backend (default: backend picks its own)",
    )
    run_p.add_argument(
        "--dry-run", action="store_true",
        help="Use the built-in stub agent instead of a real LLM backend",
    )
    run_p.add_argument(
        "--no-judge", action="store_true",
        help="Disable LLM-judge tier. Default is on — the judge upgrades "
             "needs_review verdicts by reading the actual fix-PR diff. "
             "Disable for offline runs or when no LLM backend is configured.",
    )
    run_p.add_argument(
        "--judge-backend", default="claude-cli",
        choices=["api", "claude-cli", "codex-cli"],
        help="Judge LLM backend (default: claude-cli)",
    )
    run_p.add_argument(
        "--judge-model", default="claude-sonnet-4-6",
        help="Model for the LLM-judge tier (default: claude-sonnet-4-6, "
             "cheaper than the agent's opus model and adequate for "
             "semantic match against a diff hunk)",
    )
    run_p.add_argument(
        "--judge-cache-dir", default=None,
        help="Disk cache for judge verdicts (default: .eval-judge-cache/). "
             "Keyed on (fix_sha, diagnosis_text) so re-scoring is free.",
    )

    # --- report subcommand ---
    rep_p = sub.add_parser("report", help="Generate markdown report from results JSON")
    rep_p.add_argument("results_file", help="Path to results.json")
    rep_p.add_argument("--output", "-o", help="Write report to this file (default: stdout)")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return _cmd_run(args)
    elif args.command == "report":
        return _cmd_report(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
