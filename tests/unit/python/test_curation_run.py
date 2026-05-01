"""Tests for the unified single-path mining run.py orchestrator (Task 5).

These tests follow the plan in docs/superpowers/plans/2026-05-01-single-path-mining.md
(Task 5, steps 5.1-5.13). They verify that the orchestrator drives
SELECT -> PRODUCE -> JUDGE phases end-to-end, writing one journey row per
candidate at the terminal phase.

The orchestrator is deterministic: NO LLM calls. The two main test seams are
``build_discoverer`` (returns a Discoverer-like) and ``fetch_thread``
(re-exported from triage). Tests monkeypatch both. Additional seams
(_fetch_fix_pr_metadata, validate_draft, run_eval, commit_scenario) are added
as needed so the full SELECT/PRODUCE/JUDGE pipeline is exercised under
hermetic stubs.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gpa.eval.curation.triage import IssueThread


class FakeCand:
    """Minimal stand-in for DiscoveryCandidate.

    The orchestrator reads ``url``, ``title``, ``source_type``, ``labels``,
    and ``metadata`` (which carries ``body`` for triage-gate matching when
    no thread is available). ``query`` is included for compatibility with
    older shapes; production reads ``metadata["source_query"]`` instead.
    """

    def __init__(self, url, title, body, query="invisible cube"):
        self.url = url
        self.title = title
        self.body = body
        self.query = query
        self.source_type = "issue"
        self.labels: list[str] = []
        self.created_at = None
        self.metadata = {
            "body": body,
            "source_query": query,
            "source_query_kind": "issue",
        }


class FakeDiscoverer:
    def __init__(self, cands):
        self._cands = cands

    def run(self):
        return self._cands


def _make_fake_thread(*, url=None, title="Cubes invisible after material swap",
                       body=None) -> IssueThread:
    """Build an IssueThread that satisfies the triage_required gates.

    The mining_rules.yaml triage_required block needs:
      - ``visual_keyword_present``: at least one of invisible, disappear,
        flicker, glitch, black, wrong, missing, leak.
      - ``fix_pr_linked``: a closing-PR / pull-link reference like
        ``Closed by #N`` or a /pull/N URL.
    """
    if body is None:
        body = (
            "Cubes are invisible after a material swap. Closed by #2.\n\n"
            "## Expected\nCubes render correctly\n\n"
            "## Actual\nCubes disappear"
        )
    return IssueThread(
        url=url or "https://github.com/x/y/issues/1",
        title=title,
        body=body,
        comments=[],
    )


# ---------------------------------------------------------------------------
# Common fixtures used by all three tests.
# ---------------------------------------------------------------------------


@pytest.fixture
def queries_path(tmp_path):
    p = tmp_path / "q.yaml"
    p.write_text(
        "issue:\n"
        "  - {repo: bevyengine/bevy, query: invisible cube}\n"
    )
    return p


@pytest.fixture
def rules_path():
    # Use the real rules file so the triage_required gates exist.
    return Path("src/python/gpa/eval/curation/mining_rules.yaml")


@pytest.fixture
def fake_cand():
    return FakeCand(
        url="https://github.com/x/y/issues/1",
        title="Cubes invisible after material swap",
        body=(
            "Cubes are invisible after a material swap. Closed by #2.\n\n"
            "## Expected\nCubes render correctly\n\n"
            "## Actual\nCubes disappear"
        ),
    )


@pytest.fixture
def patch_select_seams(monkeypatch, fake_cand):
    """Monkeypatch the SELECT-phase seams (Discoverer + fetch_thread)."""
    from gpa.eval.curation import run as run_mod

    monkeypatch.setattr(
        run_mod, "build_discoverer",
        lambda *a, **kw: FakeDiscoverer([fake_cand]),
    )
    monkeypatch.setattr(
        run_mod, "fetch_thread",
        lambda url: _make_fake_thread(
            url=fake_cand.url, title=fake_cand.title, body=fake_cand.body
        ),
    )


# ---------------------------------------------------------------------------
# Test 1 (Step 5.1): SELECT phase only - writes a journey row, no LLM.
# ---------------------------------------------------------------------------


def test_run_max_phase_select_writes_journey_no_llm(
    tmp_path, queries_path, rules_path, patch_select_seams
):
    from gpa.eval.curation.run import main

    rc = main([
        "--queries", str(queries_path),
        "--rules", str(rules_path),
        "--workdir", str(tmp_path / "wd"),
        "--max-phase", "select",
    ])

    assert rc == 0
    runs = list((tmp_path / "wd" / "runs").iterdir())
    assert len(runs) == 1
    journey_lines = (runs[0] / "journey.jsonl").read_text().splitlines()
    assert len(journey_lines) == 1
    row = json.loads(journey_lines[0])
    assert row["select"]["fetched"] is True
    assert row["select"]["selected"] is True
    assert row["produce"] is None
    assert row["tokens"]["total"] == 0
    # Selected at SELECT terminal: terminal_reason must align with selected=True.
    assert row["terminal_phase"] == "select"
    assert row["terminal_reason"] == "select_done"


# ---------------------------------------------------------------------------
# Test 2 (Steps 5.5-5.8): PRODUCE phase - extract + validate.
# ---------------------------------------------------------------------------


class _FakeValidationResult:
    def __init__(self, ok=True, reason="ok"):
        self.ok = ok
        self.reason = reason


def test_run_max_phase_produce_extracts_and_validates(
    tmp_path, queries_path, rules_path, patch_select_seams, monkeypatch
):
    from gpa.eval.curation import run as run_mod

    # Stub fix-PR metadata fetcher to return source files that pass the
    # source-file filter in extract_draft._filter_source_files.
    monkeypatch.setattr(
        run_mod, "_fetch_fix_pr_metadata",
        lambda thread, url: {
            "url": "https://github.com/x/y/pull/2",
            "commit_sha": "abc1234",
            "files_changed": ["src/lib.rs"],
        },
    )

    # Stub validator to always return ok=True.
    monkeypatch.setattr(
        run_mod, "_validate_draft",
        lambda draft, eval_dir: _FakeValidationResult(ok=True),
    )

    rc = run_mod.main([
        "--queries", str(queries_path),
        "--rules", str(rules_path),
        "--workdir", str(tmp_path / "wd"),
        "--max-phase", "produce",
    ])
    assert rc == 0

    runs = list((tmp_path / "wd" / "runs").iterdir())
    assert len(runs) == 1
    journey_lines = (runs[0] / "journey.jsonl").read_text().splitlines()
    assert len(journey_lines) == 1
    row = json.loads(journey_lines[0])
    assert row["produce"] is not None
    assert row["produce"]["extracted"] is True
    assert row["produce"]["validated"] is True
    assert row["judge"] is None
    assert row["terminal_phase"] == "produce"


# ---------------------------------------------------------------------------
# Test 3 (Steps 5.9-5.11): JUDGE phase - commits without --evaluate.
# ---------------------------------------------------------------------------


def test_run_judge_commits_without_evaluate_when_flag_not_set(
    tmp_path, queries_path, rules_path, patch_select_seams, monkeypatch
):
    from gpa.eval.curation import run as run_mod

    monkeypatch.setattr(
        run_mod, "_fetch_fix_pr_metadata",
        lambda thread, url: {
            "url": "https://github.com/x/y/pull/2",
            "commit_sha": "abc1234",
            "files_changed": ["src/lib.rs"],
        },
    )
    monkeypatch.setattr(
        run_mod, "_validate_draft",
        lambda draft, eval_dir: _FakeValidationResult(ok=True),
    )

    commit_calls: list[dict] = []

    def _stub_commit_scenario(**kwargs):
        commit_calls.append(kwargs)

    monkeypatch.setattr(run_mod, "commit_scenario", _stub_commit_scenario)

    rc = run_mod.main([
        "--queries", str(queries_path),
        "--rules", str(rules_path),
        "--workdir", str(tmp_path / "wd"),
        # default max-phase=judge, no --evaluate
    ])
    assert rc == 0

    runs = list((tmp_path / "wd" / "runs").iterdir())
    assert len(runs) == 1
    journey_lines = (runs[0] / "journey.jsonl").read_text().splitlines()
    assert len(journey_lines) == 1
    row = json.loads(journey_lines[0])
    assert row["judge"] is not None
    assert row["judge"]["committed_as"] is not None
    assert row["judge"]["committed_as"].startswith("r")
    assert row["judge"]["with_gla_score"] is None
    assert row["judge"]["code_only_score"] is None
    assert row["terminal_phase"] == "judge"
    assert row["terminal_reason"] == "committed"

    # commit_scenario was actually called once.
    assert len(commit_calls) == 1
    kwargs = commit_calls[0]
    assert kwargs["scenario_id"] == row["judge"]["committed_as"]
    assert kwargs["issue_url"] == "https://github.com/x/y/issues/1"


# ---------------------------------------------------------------------------
# SELECT-phase failure-mode tests (parametrized).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case_id, body_override, fetch_thread_raises, coverage_contains_url, "
    "min_score_override, expected_terminal_reason",
    [
        # DUPLICATE_URL: coverage.contains_url(cand.url) -> True.
        (
            "duplicate_url", None, False, True, None, "duplicate_url",
        ),
        # FETCH_FAILED: fetch_thread raises.
        (
            "fetch_failed", None, True, False, None, "fetch_failed",
        ),
        # TRIAGE_REJECTED: body has no visual keyword (and no closing PR ref)
        # so the triage_required gates drop the candidate.
        (
            "triage_rejected",
            "Routine refactor; nothing visual here. Tracking general cleanup.",
            False, False, None, "triage_rejected",
        ),
        # BELOW_MIN_SCORE: real triage_required pass, but min-score is set
        # absurdly high so the scored record falls below the gate.
        (
            "below_min_score", None, False, False, 9999, "below_min_score",
        ),
    ],
)
def test_run_select_failure_modes(
    case_id, body_override, fetch_thread_raises,
    coverage_contains_url, min_score_override, expected_terminal_reason,
    tmp_path, queries_path, rules_path, fake_cand, monkeypatch,
):
    """Each parametrized case stubs exactly one seam to force one terminal_reason."""
    from gpa.eval.curation import run as run_mod

    if body_override is not None:
        fake_cand.body = body_override
        fake_cand.metadata["body"] = body_override

    monkeypatch.setattr(
        run_mod, "build_discoverer",
        lambda *a, **kw: FakeDiscoverer([fake_cand]),
    )

    if fetch_thread_raises:
        def _raise(_url):
            raise RuntimeError("simulated network failure")
        monkeypatch.setattr(run_mod, "fetch_thread", _raise)
    else:
        monkeypatch.setattr(
            run_mod, "fetch_thread",
            lambda url: _make_fake_thread(
                url=fake_cand.url, title=fake_cand.title, body=fake_cand.body,
            ),
        )

    if coverage_contains_url:
        # Patch CoverageLog.contains_url at class level so the empty/temp
        # coverage log behaves as if the URL is already known.
        monkeypatch.setattr(
            "gpa.eval.curation.run.CoverageLog.contains_url",
            lambda self, url: True,
        )

    argv = [
        "--queries", str(queries_path),
        "--rules", str(rules_path),
        "--workdir", str(tmp_path / "wd"),
        "--max-phase", "select",
    ]
    if min_score_override is not None:
        argv += ["--min-score", str(min_score_override)]

    rc = run_mod.main(argv)
    assert rc == 0

    runs = list((tmp_path / "wd" / "runs").iterdir())
    assert len(runs) == 1
    journey_lines = (runs[0] / "journey.jsonl").read_text().splitlines()
    assert len(journey_lines) == 1
    row = json.loads(journey_lines[0])
    assert row["terminal_phase"] == "select"
    assert row["terminal_reason"] == expected_terminal_reason
    # Failure rows never have produce/judge populated.
    assert row["produce"] is None
    assert row["judge"] is None


# ---------------------------------------------------------------------------
# PRODUCE-phase failure-mode tests (parametrized).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case_id, extract_raises, validate_ok, expected_terminal_reason, "
    "expected_extracted, expected_validated",
    [
        # EXTRACTION_FAILED: extract_draft raises ExtractionFailure.
        (
            "extraction_failed", True, None,
            "extraction_failed", False, False,
        ),
        # VALIDATION_FAILED: extract succeeds but validator returns ok=False.
        (
            "validation_failed", False, False,
            "validation_failed", True, False,
        ),
    ],
)
def test_run_produce_failure_modes(
    case_id, extract_raises, validate_ok,
    expected_terminal_reason, expected_extracted, expected_validated,
    tmp_path, queries_path, rules_path, patch_select_seams, monkeypatch,
):
    from gpa.eval.curation import run as run_mod
    from gpa.eval.curation.extract_draft import ExtractionFailure

    monkeypatch.setattr(
        run_mod, "_fetch_fix_pr_metadata",
        lambda thread, url: {
            "url": "https://github.com/x/y/pull/2",
            "commit_sha": "abc1234",
            "files_changed": ["src/lib.rs"],
        },
    )

    if extract_raises:
        def _raise_extract(*args, **kwargs):
            raise ExtractionFailure("simulated extraction failure")
        monkeypatch.setattr(run_mod, "extract_draft", _raise_extract)
    # else: real extract_draft runs against the fake thread/fix_pr.

    if validate_ok is False:
        monkeypatch.setattr(
            run_mod, "_validate_draft",
            lambda draft, eval_dir: _FakeValidationResult(
                ok=False, reason="simulated validator rejection",
            ),
        )
    elif validate_ok is True:
        monkeypatch.setattr(
            run_mod, "_validate_draft",
            lambda draft, eval_dir: _FakeValidationResult(ok=True),
        )

    rc = run_mod.main([
        "--queries", str(queries_path),
        "--rules", str(rules_path),
        "--workdir", str(tmp_path / "wd"),
        "--max-phase", "produce",
    ])
    assert rc == 0

    runs = list((tmp_path / "wd" / "runs").iterdir())
    assert len(runs) == 1
    journey_lines = (runs[0] / "journey.jsonl").read_text().splitlines()
    assert len(journey_lines) == 1
    row = json.loads(journey_lines[0])
    assert row["terminal_phase"] == "produce"
    assert row["terminal_reason"] == expected_terminal_reason
    assert row["produce"] is not None
    assert row["produce"]["extracted"] is expected_extracted
    assert row["produce"]["validated"] is expected_validated
    # Selected upstream, so the SELECT outcome is populated.
    assert row["select"]["selected"] is True
    assert row["judge"] is None
