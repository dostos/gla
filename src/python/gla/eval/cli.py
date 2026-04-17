"""CLI entry point for the GLA evaluation harness.

Usage:
    python -m gla.eval.cli run --scenario e1_state_leak --mode with_gla
    python -m gla.eval.cli run --all [--scenarios e1,e2] [--modes with_gla,code_only]
    python -m gla.eval.cli report results.json [--output report.md]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _cmd_run(args: argparse.Namespace) -> int:
    """Execute eval scenarios via the harness."""
    from gla.eval.harness import EvalHarness
    from gla.eval.scenario import ScenarioMetadata

    config: dict = {}
    if args.config:
        with open(args.config, encoding="utf-8") as fh:
            config = json.load(fh)

    # Override config with CLI flags
    if args.gla_url:
        config["gla_base_url"] = args.gla_url
    if args.token:
        config["gla_token"] = args.token
    if args.shim:
        config["shim_path"] = args.shim
    if args.model:
        config["model"] = args.model

    harness = EvalHarness(config=config)

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

    # Minimal stub agent used when no real agent is configured.
    # Real usage should provide a proper agent via the Python API.
    def _stub_agent(
        scenario: ScenarioMetadata, mode: str, tools: dict
    ) -> tuple[str, int, int, int, int, float]:
        print(f"  [stub] scenario={scenario.id} mode={mode}")
        source = tools["read_source"]()
        diagnosis = f"[stub diagnosis for {scenario.id}]"
        tokens = len(source.split())
        return diagnosis, tokens, 50, 0, 1, 0.0

    results = harness.run_all(
        agent_fn=_stub_agent, scenarios=scenarios, modes=modes
    )

    output_path = args.output or "results.json"
    harness.save_results(output_path)
    print(f"Saved {len(results)} result(s) to {output_path}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    """Generate a report from a saved results JSON file."""
    from gla.eval.harness import EvalHarness
    from gla.eval.metrics import ReportGenerator

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
        prog="gla.eval.cli",
        description="GLA evaluation harness CLI",
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
    run_p.add_argument("--gla-url", help="GLA server base URL")
    run_p.add_argument("--token", help="GLA auth token")
    run_p.add_argument("--shim", help="Path to GLA shim shared library")
    run_p.add_argument("--model", help="LLM model identifier (for metadata)")

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
