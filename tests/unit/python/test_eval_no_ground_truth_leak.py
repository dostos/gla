"""Regression test: the eval agent's prompt must never contain Ground Truth.

The whole point of the User Report / Ground Truth split is that the agent
sees only the symptom and has to derive the diagnosis. If any refactor
causes the prompt builder to start including Ground Truth (or adjacent
fields that name the root cause), the eval becomes meaningless. This test
pins the invariant.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from gpa.eval.llm_agent import EvalAgent


_SENTINEL_USER_REPORT = (
    "The left quad should be red and the right quad should be blue, but "
    "both come out red at runtime. No console errors."
)
_SENTINEL_GROUND_TRUTH = (
    "SENTINEL_GT_MARKER: glBindTexture omitted before the second draw, "
    "so the texture binding leaks from the previous draw."
)


def test_user_message_excludes_ground_truth_content():
    """`_build_user_message` only embeds the scenario_description arg.
    Nothing else about the scenario can sneak in through that path.
    """
    agent = EvalAgent(model="x", max_turns=1, api_key="k")
    msg = agent._build_user_message(
        scenario_description=_SENTINEL_USER_REPORT,
        source_path="/tmp/main.c",
    )
    assert _SENTINEL_USER_REPORT in msg
    assert "SENTINEL_GT_MARKER" not in msg
    assert _SENTINEL_GROUND_TRUTH not in msg


def test_agent_factory_wires_only_bug_description_to_prompt(monkeypatch):
    """The factory in `build_agent_fn` must pull `bug_description`
    (= User Report) from the scenario object, never `ground_truth_diagnosis`
    or `gpa_advantage` (the How-OpenGPA-Helps hint).
    """
    from gpa.eval.llm_agent import build_agent_fn

    scenario = MagicMock()
    scenario.description = ""  # force fallback to bug_description
    scenario.bug_description = _SENTINEL_USER_REPORT
    scenario.ground_truth_diagnosis = _SENTINEL_GROUND_TRUTH
    scenario.gpa_advantage = (
        "SENTINEL_GT_MARKER: query inspect_drawcall and compare texture IDs."
    )
    scenario.expected_output = "red quad, blue quad"
    scenario.actual_output = "both quads red"
    scenario.source_path = "/tmp/main.c"

    captured = {}

    class StubAgent:
        def __init__(self, *a, **kw):
            pass

        def run_code_only(self, **kw):
            captured["code_only"] = kw
            r = MagicMock()
            r.diagnosis = "d"
            r.input_tokens = 0
            r.output_tokens = 0
            r.tool_calls = 0
            r.num_turns = 0
            r.time_seconds = 0.0
            return r

        def run_with_gla(self, **kw):
            captured["with_gla"] = kw
            r = MagicMock()
            r.diagnosis = "d"
            r.input_tokens = 0
            r.output_tokens = 0
            r.tool_calls = 0
            r.num_turns = 0
            r.time_seconds = 0.0
            return r

    monkeypatch.setattr("gpa.eval.llm_agent.EvalAgent", StubAgent)

    factory = build_agent_fn(model="x", api_key="k")
    tools = {
        "read_source": lambda: "// SOURCE: https://x/1\nint main(){}",
    }
    factory(scenario, "code_only", tools)

    desc = captured["code_only"]["scenario_description"]
    assert _SENTINEL_USER_REPORT in desc
    assert "SENTINEL_GT_MARKER" not in desc
    assert _SENTINEL_GROUND_TRUTH not in desc


def test_scenario_loader_does_not_merge_ground_truth_into_user_report(tmp_path):
    """Belt-and-braces: loading a scenario.md with both sections yields a
    bug_description that contains only the User Report content.
    """
    from gpa.eval.scenario import ScenarioLoader

    sdir = tmp_path / "e_x"
    sdir.mkdir()
    (sdir / "main.c").write_text("// SOURCE: https://x\nint main(){}")
    (sdir / "scenario.md").write_text(
        "# E_X: Title\n\n"
        f"## User Report\n{_SENTINEL_USER_REPORT}\n\n"
        "## Expected Correct Output\nred and blue\n\n"
        "## Actual Broken Output\nboth red\n\n"
        f"## Ground Truth\n{_SENTINEL_GROUND_TRUTH}\n\n"
        "## Difficulty Rating\n2/5\n\n"
        "## Adversarial Principles\n- x\n\n"
        "## How OpenGPA Helps\nh\n\n"
        "## Bug Signature\n```yaml\ntype: framebuffer_dominant_color\n"
        "spec:\n  expected_rgba: [1,0,0,1]\n  tolerance: 0.1\n```\n"
    )

    loader = ScenarioLoader(eval_dir=str(tmp_path))
    scenario = loader.load("e_x")

    assert _SENTINEL_USER_REPORT in scenario.bug_description
    assert "SENTINEL_GT_MARKER" not in scenario.bug_description
    # Ground Truth lives in its own field — used by scoring, never by the agent
    assert "SENTINEL_GT_MARKER" in scenario.ground_truth_diagnosis
