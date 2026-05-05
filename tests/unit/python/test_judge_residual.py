"""LLM-judge tier — upgrade `needs_review` verdicts via semantic match.

When `score_run` lands in the prose `needs_review` band (any_hit ≥ 1
but recall below threshold), the judge tier asks an LLM to compare the
agent's free-form diagnosis against `git show --stat` for the fix-PR.
Cost-bounded: only fires for the residual band, opt-in via
`llm_client`, disk cache keyed on (fix_sha, diagnosis_text). Skips on
clear successes, clear failures, gave-up runs, and missing
snapshot_root.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# fetch_pr_diff_summary
# ---------------------------------------------------------------------------


class _Fix:
    def __init__(self, fix_sha: str = "abcdef1"):
        self.fix_sha = fix_sha
        self.fix_pr_url = "https://github.com/o/r/pull/2"
        self.bug_class = "framework-internal"
        self.files = ["src/render/draw_fill.ts"]


def test_fetch_pr_diff_summary_runs_git_commands(tmp_path, monkeypatch):
    from gpa.eval import judge

    calls = []

    def fake_run(argv, *, cwd=None, capture_output=None, text=None,
                 timeout=None, check=None, errors=None):
        calls.append((tuple(argv), cwd))
        # R16: judge calls `git cat-file -e <sha>^1` to verify the
        # parent is reachable; if it isn't, follows up with a depth=2
        # fetch. Both should succeed in this test.
        if "cat-file" in argv:
            return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")
        if "log" in argv:
            return subprocess.CompletedProcess(
                argv, returncode=0,
                stdout="commit message\n\nbody line\n", stderr="",
            )
        if "--shortstat" in argv:
            return subprocess.CompletedProcess(
                argv, returncode=0,
                stdout=" 1 file changed, 2 insertions(+), 2 deletions(-)\n",
                stderr="",
            )
        # full git show
        return subprocess.CompletedProcess(
            argv, returncode=0,
            stdout="diff --git a/file.ts b/file.ts\n@@ -10,3 +10,3 @@\n-old\n+new\n",
            stderr="",
        )
    monkeypatch.setattr(subprocess, "run", fake_run)
    out = judge.fetch_pr_diff_summary(
        fix_sha="abcdef1", snapshot_root=tmp_path,
    )
    assert "commit message" in out
    assert "1 file changed" in out
    # Diff hunks are now part of the summary (R12c refinement)
    assert "diff --git" in out
    assert "@@ -10,3 +10,3 @@" in out
    # All subprocesses ran in the snapshot dir
    assert all(c[1] == tmp_path for c in calls)


def test_fetch_pr_diff_summary_truncates(tmp_path, monkeypatch):
    from gpa.eval import judge

    huge = "x" * 50000

    def fake_run(argv, *, cwd, capture_output, text, timeout, check, errors=None):
        return subprocess.CompletedProcess(argv, 0, huge, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = judge.fetch_pr_diff_summary(
        fix_sha="x", snapshot_root=tmp_path, max_bytes=1000,
    )
    assert len(out) <= 1100  # allow small overhead for headers


def test_fetch_pr_diff_summary_handles_missing_sha(tmp_path, monkeypatch):
    from gpa.eval import judge

    def fake_run(argv, *, cwd, capture_output, text, timeout, check, errors=None):
        raise subprocess.CalledProcessError(128, argv, "", "fatal: bad object")

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = judge.fetch_pr_diff_summary(
        fix_sha="missing", snapshot_root=tmp_path,
    )
    # Doesn't raise — best-effort returns empty/short string
    assert isinstance(out, str)


def test_fetch_pr_diff_summary_no_snapshot(tmp_path):
    """If snapshot_root doesn't exist or is None, return empty string."""
    from gpa.eval import judge
    assert judge.fetch_pr_diff_summary(
        fix_sha="x", snapshot_root=None,
    ) == ""


# ---------------------------------------------------------------------------
# judge_residual: only fires for the right band
# ---------------------------------------------------------------------------


class _StubClient:
    """Returns canned verdicts for run_semantic_judge."""
    def __init__(self, verdict: str):
        self._verdict = verdict
        self.calls = 0

    def complete(self, *, system, messages):
        self.calls += 1
        # judge.run_semantic_judge extracts the last `full|partial|none`
        # word from response.text.
        from types import SimpleNamespace
        return SimpleNamespace(text=f"reasoning\n{self._verdict}")


def _solved_verdict():
    from gpa.eval.scorer import ScoreVerdict
    return ScoreVerdict(
        scorer="file_level", solved=True, confidence="high",
        file_score=1.0,
    )


def _gave_up_verdict():
    from gpa.eval.scorer import ScoreVerdict
    return ScoreVerdict(
        scorer="gave_up", solved=False, confidence="high", gave_up=True,
    )


def _no_signal_verdict():
    from gpa.eval.scorer import ScoreVerdict
    return ScoreVerdict(
        scorer="no_signal", solved=False, confidence="high",
    )


def _needs_review_verdict():
    from gpa.eval.scorer import ScoreVerdict
    return ScoreVerdict(
        scorer="prose", solved=False, confidence="low",
        prose_recall=0.33, prose_precision=1.0, needs_review=True,
    )


def test_judge_skips_when_already_solved(tmp_path, monkeypatch):
    from gpa.eval.scorer import judge_residual

    monkeypatch.setattr(
        "gpa.eval.judge.fetch_pr_diff_summary",
        lambda fix_sha, snapshot_root, **_: "diff",
    )
    client = _StubClient("full")
    verdict = _solved_verdict()
    out = judge_residual(
        verdict, fix=_Fix(), diagnosis_text="anything",
        snapshot_root=tmp_path, llm_client=client,
    )
    assert out is verdict
    assert client.calls == 0


def test_judge_skips_when_gave_up(tmp_path, monkeypatch):
    from gpa.eval.scorer import judge_residual
    monkeypatch.setattr(
        "gpa.eval.judge.fetch_pr_diff_summary",
        lambda fix_sha, snapshot_root, **_: "diff",
    )
    client = _StubClient("full")
    out = judge_residual(
        _gave_up_verdict(), fix=_Fix(), diagnosis_text="text",
        snapshot_root=tmp_path, llm_client=client,
    )
    assert out.solved is False
    assert client.calls == 0


def test_judge_skips_when_no_signal(tmp_path, monkeypatch):
    from gpa.eval.scorer import judge_residual
    monkeypatch.setattr(
        "gpa.eval.judge.fetch_pr_diff_summary",
        lambda fix_sha, snapshot_root, **_: "diff",
    )
    client = _StubClient("full")
    out = judge_residual(
        _no_signal_verdict(), fix=_Fix(), diagnosis_text="text",
        snapshot_root=tmp_path, llm_client=client,
    )
    assert client.calls == 0


def test_judge_skips_when_no_client(tmp_path):
    from gpa.eval.scorer import judge_residual
    out = judge_residual(
        _needs_review_verdict(), fix=_Fix(), diagnosis_text="text",
        snapshot_root=tmp_path, llm_client=None,
    )
    # No upgrade — passthrough
    assert out.solved is False
    assert out.scorer == "prose"
    assert out.judge_verdict is None


def test_judge_skips_when_no_snapshot(monkeypatch):
    from gpa.eval.scorer import judge_residual
    client = _StubClient("full")
    out = judge_residual(
        _needs_review_verdict(), fix=_Fix(), diagnosis_text="text",
        snapshot_root=None, llm_client=client,
    )
    assert client.calls == 0
    assert out.solved is False


def test_judge_full_upgrades_to_solved(tmp_path, monkeypatch):
    from gpa.eval.scorer import judge_residual
    monkeypatch.setattr(
        "gpa.eval.judge.fetch_pr_diff_summary",
        lambda fix_sha, snapshot_root, **_: "stat output",
    )
    client = _StubClient("full")
    out = judge_residual(
        _needs_review_verdict(), fix=_Fix(),
        diagnosis_text="DIAGNOSIS: cache invalidation in Picking. FIX: ...",
        snapshot_root=tmp_path, llm_client=client,
    )
    assert client.calls == 1
    assert out.solved is True
    assert out.scorer == "judge"
    assert out.judge_verdict == "full"
    assert out.confidence == "medium"


def test_judge_partial_keeps_needs_review(tmp_path, monkeypatch):
    from gpa.eval.scorer import judge_residual
    monkeypatch.setattr(
        "gpa.eval.judge.fetch_pr_diff_summary",
        lambda fix_sha, snapshot_root, **_: "stat",
    )
    client = _StubClient("partial")
    out = judge_residual(
        _needs_review_verdict(), fix=_Fix(),
        diagnosis_text="text", snapshot_root=tmp_path, llm_client=client,
    )
    assert out.solved is False
    assert out.judge_verdict == "partial"
    assert out.needs_review is True


def test_judge_none_keeps_failed(tmp_path, monkeypatch):
    from gpa.eval.scorer import judge_residual
    monkeypatch.setattr(
        "gpa.eval.judge.fetch_pr_diff_summary",
        lambda fix_sha, snapshot_root, **_: "stat",
    )
    client = _StubClient("none")
    out = judge_residual(
        _needs_review_verdict(), fix=_Fix(),
        diagnosis_text="text", snapshot_root=tmp_path, llm_client=client,
    )
    assert out.solved is False
    assert out.judge_verdict == "none"


# ---------------------------------------------------------------------------
# Cache: second call with the same key skips the LLM
# ---------------------------------------------------------------------------


def test_judge_cache_skips_repeat_call(tmp_path, monkeypatch):
    from gpa.eval.scorer import judge_residual
    monkeypatch.setattr(
        "gpa.eval.judge.fetch_pr_diff_summary",
        lambda fix_sha, snapshot_root, **_: "stat",
    )
    client = _StubClient("full")
    cache_dir = tmp_path / "cache"

    out1 = judge_residual(
        _needs_review_verdict(), fix=_Fix(),
        diagnosis_text="exact-text", snapshot_root=tmp_path,
        llm_client=client, cache_dir=cache_dir,
    )
    out2 = judge_residual(
        _needs_review_verdict(), fix=_Fix(),
        diagnosis_text="exact-text", snapshot_root=tmp_path,
        llm_client=client, cache_dir=cache_dir,
    )
    assert out1.judge_verdict == "full"
    assert out2.judge_verdict == "full"
    # The LLM was called exactly once — second call hit the cache.
    assert client.calls == 1


def test_judge_cache_distinct_diagnoses_call_twice(tmp_path, monkeypatch):
    from gpa.eval.scorer import judge_residual
    monkeypatch.setattr(
        "gpa.eval.judge.fetch_pr_diff_summary",
        lambda fix_sha, snapshot_root, **_: "stat",
    )
    client = _StubClient("partial")
    cache_dir = tmp_path / "cache"

    judge_residual(
        _needs_review_verdict(), fix=_Fix(),
        diagnosis_text="A", snapshot_root=tmp_path,
        llm_client=client, cache_dir=cache_dir,
    )
    judge_residual(
        _needs_review_verdict(), fix=_Fix(),
        diagnosis_text="B", snapshot_root=tmp_path,
        llm_client=client, cache_dir=cache_dir,
    )
    assert client.calls == 2
