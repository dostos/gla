"""Tests for :func:`gpa.eval.telemetry.classify_verdict`.

The verdict classifier separates the three failure modes our rounds had
previously lumped together as "incorrect":

- ``solved`` — correct diagnosis.
- ``timeout`` — hit the turn cap before finishing.
- ``wrong`` — agent stopped with a bad answer on its own.
- ``infra`` — run never produced a meaningful trajectory.

R5-R8 all used ``--max-turns 40``, so the default budget is 40 and the
"turns>=39" threshold absorbs claude -p's off-by-one.
"""

from __future__ import annotations

from gpa.eval.telemetry import classify_verdict


def test_solved_when_correct():
    run = {"correct": True, "turns": 12, "result": "answer"}
    assert classify_verdict(run) == "solved"


def test_timeout_when_at_budget_incorrect():
    # claude -p sometimes reports 40 at the 40-turn cap; this is a timeout.
    run = {"correct": False, "turns": 40, "result": ""}
    assert classify_verdict(run) == "timeout"


def test_timeout_when_off_by_one_at_budget():
    # 39 is still the turn cap (off-by-one).
    run = {"correct": False, "turns": 39, "result": ""}
    assert classify_verdict(run) == "timeout"


def test_timeout_when_exceeding_budget_incorrect():
    # A retry at 80-turn cap that still hit 80 is clearly timeout, even if
    # the caller forgot to raise the budget argument.
    run = {"correct": False, "turns": 80, "result": ""}
    assert classify_verdict(run) == "timeout"


def test_wrong_when_incorrect_early():
    run = {"correct": False, "turns": 15, "result": "confident but wrong"}
    assert classify_verdict(run) == "wrong"


def test_wrong_when_incorrect_with_empty_root_cause_but_some_turns():
    # The agent ran, produced nothing useful, but did *not* hit the cap;
    # we count it as a wrong answer (it chose to stop).
    run = {"correct": False, "turns": 20, "result": ""}
    assert classify_verdict(run) == "wrong"


def test_infra_when_empty_result_zero_turns():
    run = {"correct": None, "turns": 0, "result": ""}
    assert classify_verdict(run) == "infra"


def test_infra_when_error_field_set():
    run = {"correct": False, "turns": 0, "result": "", "error": "capture crashed"}
    assert classify_verdict(run) == "infra"


def test_infra_when_stop_reason_infra():
    run = {"correct": None, "turns": 0, "result": "", "stop_reason": "infra"}
    assert classify_verdict(run) == "infra"


def test_custom_budget_passed_through():
    # With a budget of 80, 40 turns is *not* timeout — it's a wrong answer.
    run = {"correct": False, "turns": 40, "result": ""}
    assert classify_verdict(run, max_turns_budget=80) == "wrong"
    # And 79 still reads as timeout under the 80-budget off-by-one rule.
    run2 = {"correct": False, "turns": 79, "result": ""}
    assert classify_verdict(run2, max_turns_budget=80) == "timeout"


def test_correct_false_with_zero_turns_is_wrong_not_infra():
    # A scored run with a scoring signal (correct=False) but no trajectory
    # is a wrong answer from the scorer's perspective, not infra noise.
    run = {"correct": False, "turns": 0, "result": ""}
    assert classify_verdict(run) == "wrong"
