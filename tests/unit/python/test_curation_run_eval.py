from unittest.mock import MagicMock
from datetime import datetime, timezone
from gla.eval.curation.run_eval import RunEval, RunEvalResult
from gla.eval.metrics import EvalResult

def _mk(mode, correct, total_tokens):
    return EvalResult(scenario_id="r1", mode=mode, correct_diagnosis=correct,
                      correct_fix=correct, diagnosis_text="",
                      input_tokens=0, output_tokens=0, total_tokens=total_tokens,
                      tool_calls=0, num_turns=0, time_seconds=0.0,
                      model="x", timestamp=datetime.now(timezone.utc).isoformat())

def test_run_eval_invokes_harness_for_both_modes():
    harness = MagicMock()
    harness.run_scenario.side_effect = [
        _mk("with_gla", True, 1000),
        _mk("code_only", False, 4000),
    ]
    agent_fn = MagicMock()
    re = RunEval(harness=harness, agent_fn=agent_fn)
    result = re.run("r1")
    assert result.with_gla.mode == "with_gla"
    assert result.code_only.mode == "code_only"
    assert harness.run_scenario.call_count == 2
