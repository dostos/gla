"""Main orchestrator for the GLA evaluation harness."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from gla.eval.metrics import DiagnosisScorer, EvalResult
from gla.eval.runner import ScenarioRunner
from gla.eval.scenario import ScenarioLoader, ScenarioMetadata

# Callable signature: (scenario, mode, tools) -> (diagnosis_text, input_tokens,
#   output_tokens, tool_calls, num_turns, time_seconds)
AgentFn = Callable[
    [ScenarioMetadata, str, dict],
    tuple[str, int, int, int, int, float],
]

_ALL_MODES = ["with_gla", "code_only"]


class EvalHarness:
    """Orchestrates eval runs across scenarios and modes."""

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        eval_dir = cfg.get("eval_dir", "tests/eval")
        self.loader = ScenarioLoader(eval_dir=eval_dir)
        self.runner = ScenarioRunner(
            gla_base_url=cfg.get("gla_base_url", "http://127.0.0.1:18080"),
            gla_token=cfg.get("gla_token", ""),
            shim_path=cfg.get("shim_path", ""),
            bazel_bin=cfg.get("bazel_bin", "bazel"),
            repo_root=cfg.get("repo_root"),
        )
        self._scorer = DiagnosisScorer(
            diagnosis_threshold=cfg.get("diagnosis_threshold", 0.25),
            fix_threshold=cfg.get("fix_threshold", 0.25),
        )
        self._model = cfg.get("model", "unknown")
        self.results: list[EvalResult] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_scenario(
        self,
        scenario_id: str,
        mode: str,
        agent_fn: AgentFn,
    ) -> EvalResult:
        """Run one scenario in one mode.

        Args:
            scenario_id: e.g. "e1_state_leak"
            mode: "with_gla" or "code_only"
            agent_fn: callable(scenario, mode, tools) ->
                      (diagnosis_text, input_tokens, output_tokens,
                       tool_calls, num_turns, time_seconds)

        Returns:
            EvalResult with scores populated.
        """
        if mode not in _ALL_MODES:
            raise ValueError(f"mode must be one of {_ALL_MODES}, got: {mode!r}")

        scenario = self.loader.load(scenario_id)

        # Build tool set for the agent
        tools = self._build_tools(scenario, mode)

        # Invoke the agent
        (
            diagnosis_text,
            input_tokens,
            output_tokens,
            tool_calls,
            num_turns,
            elapsed,
        ) = agent_fn(scenario, mode, tools)

        # Score
        correct_diag, correct_fix = self._scorer.score(diagnosis_text, scenario)

        result = EvalResult(
            scenario_id=scenario_id,
            mode=mode,
            correct_diagnosis=correct_diag,
            correct_fix=correct_fix,
            diagnosis_text=diagnosis_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            tool_calls=tool_calls,
            num_turns=num_turns,
            time_seconds=elapsed,
            model=self._model,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self.results.append(result)
        return result

    def run_all(
        self,
        agent_fn: AgentFn,
        scenarios: Optional[list[str]] = None,
        modes: Optional[list[str]] = None,
    ) -> list[EvalResult]:
        """Run all (or a subset of) scenarios in all (or subset of) modes.

        Args:
            agent_fn: see run_scenario
            scenarios: list of scenario IDs; None means all available
            modes: list of modes; None means ["with_gla", "code_only"]

        Returns:
            All EvalResult objects produced in this run.
        """
        if scenarios is None:
            all_meta = self.loader.load_all()
            scenarios = [m.id for m in all_meta]
        if modes is None:
            modes = list(_ALL_MODES)

        new_results: list[EvalResult] = []
        for sid in scenarios:
            for mode in modes:
                result = self.run_scenario(sid, mode, agent_fn)
                new_results.append(result)
        return new_results

    def save_results(self, path: str) -> None:
        """Serialize all accumulated results to a JSON file."""
        data = [r.to_dict() for r in self.results]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    @staticmethod
    def load_results(path: str) -> list[EvalResult]:
        """Load previously-saved results from a JSON file."""
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return [EvalResult.from_dict(d) for d in data]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_tools(self, scenario: ScenarioMetadata, mode: str) -> dict:
        """Return a tool dictionary passed to the agent.

        In 'with_gla' mode the runner tools are included.
        In 'code_only' mode only the source reader is provided.
        """
        tools: dict = {
            "read_source": lambda: self.runner.read_source(scenario),
        }
        if mode == "with_gla":
            tools["run_with_capture"] = lambda: self.runner.run_with_capture(scenario)
        return tools
