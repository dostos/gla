import json
from unittest.mock import patch, MagicMock
from gpa.eval.curation.triage import Triage, TriageResult, IssueThread, fetch_issue_thread, fetch_commit_thread, fetch_pr_thread
from gpa.eval.curation.llm_client import LLMResponse

def _fake_response(text: str) -> LLMResponse:
    return LLMResponse(text=text, input_tokens=100, output_tokens=50,
                       cache_creation_input_tokens=0, cache_read_input_tokens=0,
                       stop_reason="end_turn")

def test_triage_parses_in_scope_response():
    llm = MagicMock()
    llm.complete.return_value = _fake_response(
        '```json\n{"triage_verdict":"in_scope",'
        '"root_cause_fingerprint":"state_leak:tex_binding_persists",'
        '"rejection_reason":null,'
        '"summary":"Texture binding leaks between two draw calls"}\n```'
    )
    t = Triage(llm_client=llm)
    thread = IssueThread(url="https://x/1", title="Tex leak",
                         body="second quad gets first texture",
                         comments=[])
    result = t.triage(thread)
    assert result.verdict == "in_scope"
    assert result.fingerprint == "state_leak:tex_binding_persists"
    assert result.rejection_reason is None

def test_triage_parses_out_of_scope_response():
    llm = MagicMock()
    llm.complete.return_value = _fake_response(
        '```json\n{"triage_verdict":"out_of_scope",'
        '"root_cause_fingerprint":"other:n_a",'
        '"rejection_reason":"out_of_scope_not_rendering_bug",'
        '"summary":"feature request"}\n```'
    )
    t = Triage(llm_client=llm)
    thread = IssueThread(url="https://x/2", title="feature request",
                         body="please add a new API", comments=[])
    result = t.triage(thread)
    assert result.verdict == "out_of_scope"
    assert result.rejection_reason == "out_of_scope_not_rendering_bug"

def test_triage_respects_compile_error_rejection():
    """Shader-compile bugs are explicitly out-of-scope for the corpus. If the
    LLM returns out_of_scope_compile_error, the verdict and reason are kept
    verbatim (no rewriting to in_scope)."""
    llm = MagicMock()
    llm.complete.return_value = _fake_response(
        '```json\n{"triage_verdict":"out_of_scope",'
        '"root_cause_fingerprint":"shader_compile:glsl_syntax",'
        '"rejection_reason":"out_of_scope_compile_error",'
        '"summary":"GLSL syntax error"}\n```'
    )
    t = Triage(llm_client=llm)
    thread = IssueThread(url="https://x/1", title="compile fail",
                         body="GLSL error", comments=[])
    result = t.triage(thread)
    assert result.verdict == "out_of_scope"
    assert result.rejection_reason == "out_of_scope_compile_error"


def test_fetch_issue_thread_calls_gh_api():
    issue_json = '{"title":"x","body":"b","number":42}'
    comments_json = '[{"body":"c1"},{"body":"c2"}]'
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout=issue_json, returncode=0),
            MagicMock(stdout=comments_json, returncode=0),
        ]
        thread = fetch_issue_thread("https://github.com/owner/repo/issues/42")

    assert thread.title == "x"
    assert thread.body == "b"
    assert thread.comments == ["c1", "c2"]


def test_triage_rejects_invalid_fingerprint_category():
    llm = MagicMock()
    llm.complete.return_value = _fake_response(
        '```json\n{"triage_verdict":"in_scope",'
        '"root_cause_fingerprint":"invented_category:foo",'
        '"rejection_reason":null,"summary":"x"}\n```'
    )
    t = Triage(llm_client=llm)
    thread = IssueThread(url="https://x/3", title="t", body="b", comments=[])
    result = t.triage(thread)
    # Parser normalizes unknown categories to "other"
    assert result.fingerprint.startswith("other:")


def test_fetch_commit_thread_parses_commit_url():
    commit_json = json.dumps({
        "sha": "abc123",
        "commit": {
            "message": "fix: z-fighting in shadow pass\n\nRoot cause: depth bias was too small.",
            "author": {"date": "2025-01-01T00:00:00Z"},
        },
        "files": [
            {"filename": "src/shadow.c", "patch": "@@ -10,1 +10,1 @@\n-  depth_bias = 0.001;\n+  depth_bias = 0.01;"},
        ],
    })
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=commit_json, returncode=0)
        thread = fetch_commit_thread("https://github.com/owner/repo/commit/abc123")
    assert thread.title == "fix: z-fighting in shadow pass"
    assert "depth bias was too small" in thread.body
    assert any("depth_bias = 0.01" in c for c in thread.comments)


def test_fetch_commit_thread_rejects_non_commit_url():
    import pytest
    with pytest.raises(ValueError, match="Not a GitHub commit URL"):
        fetch_commit_thread("https://github.com/owner/repo/issues/42")


def test_fetch_thread_dispatches_by_url_shape():
    issue_stub = MagicMock()
    commit_stub = MagicMock()
    issue_stub.return_value = IssueThread(url="issue", title="i", body="b")
    commit_stub.return_value = IssueThread(url="commit", title="c", body="b")

    import gpa.eval.curation.triage as T
    with patch.object(T, "fetch_issue_thread", issue_stub), \
         patch.object(T, "fetch_commit_thread", commit_stub):
        r1 = T.fetch_thread("https://github.com/o/r/issues/1")
        r2 = T.fetch_thread("https://github.com/o/r/commit/abc")
    assert r1.title == "i"
    assert r2.title == "c"


def test_fetch_thread_dispatches_to_stackoverflow():
    """SO URLs are routed to fetch_stackoverflow_thread."""
    import gpa.eval.curation.triage as T
    import gpa.eval.curation.stackoverflow as SO

    so_stub = MagicMock(return_value=IssueThread(url="so", title="so", body="b"))
    with patch.object(SO, "fetch_stackoverflow_thread", so_stub):
        result = T.fetch_thread("https://stackoverflow.com/questions/12345/title")
    assert result.title == "so"
    so_stub.assert_called_once()


def test_extract_pr_refs_finds_short_form():
    from gpa.eval.curation.triage import _extract_pr_refs
    text = "Fixed by #1234 and also see #5678."
    refs = _extract_pr_refs(text, "owner", "repo")
    nums = [r[2] for r in refs]
    assert "1234" in nums
    assert "5678" in nums
    assert refs[0][0] == "owner"

def test_extract_pr_refs_finds_full_urls():
    from gpa.eval.curation.triage import _extract_pr_refs
    text = "See https://github.com/mrdoob/three.js/pull/12345 for context."
    refs = _extract_pr_refs(text, "owner", "repo")
    assert any(r == ("mrdoob", "three.js", "12345") for r in refs)

def test_extract_pr_refs_handles_commit_urls():
    from gpa.eval.curation.triage import _extract_pr_refs
    text = "Fixed in https://github.com/owner/repo/commit/abc123def456"
    refs = _extract_pr_refs(text, "owner", "repo")
    assert any(r == ("owner", "repo", "abc123def456") for r in refs)

def test_extract_pr_refs_dedupes():
    from gpa.eval.curation.triage import _extract_pr_refs
    text = "See #1234, also #1234 and https://github.com/o/r/pull/1234"
    refs = _extract_pr_refs(text, "o", "r")
    assert len(refs) == 1

def test_fetch_issue_thread_follows_pr_reference():
    """When the issue body references a PR via #NNNN, the PR body is appended."""
    issue_json = json.dumps({
        "title": "Z-fighting on far plane",
        "body": "Fixed by #9999. See that PR for details.",
        "number": 42,
    })
    comments_json = json.dumps([])
    pr_json = json.dumps({
        "title": "fix: use logarithmic depth near far plane",
        "body": "Root cause: depth precision collapses when far/near > 1e6.",
    })

    with patch("subprocess.run") as mock_run:
        # fetch_issue_thread makes 2 calls (issue + comments) then
        # _fetch_linked_context makes 1 (PR) → 3 total.
        mock_run.side_effect = [
            MagicMock(stdout=issue_json, returncode=0),
            MagicMock(stdout=comments_json, returncode=0),
            MagicMock(stdout=pr_json, returncode=0),
        ]
        thread = fetch_issue_thread("https://github.com/owner/repo/issues/42")

    # The linked PR body should be in comments
    joined = "\n".join(thread.comments)
    assert "logarithmic depth" in joined
    assert "#9999" in joined  # ref header

def test_fetch_issue_thread_swallows_broken_links(caplog):
    """If a referenced PR 404s, the issue fetch still succeeds."""
    issue_json = json.dumps({
        "title": "Broken link test",
        "body": "See #9999",
        "number": 42,
    })
    comments_json = json.dumps([])

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout=issue_json, returncode=0),
            MagicMock(stdout=comments_json, returncode=0),
            # PR fetch: returncode != 0 (404 from gh)
            MagicMock(stdout="", returncode=1),
            # Issue fallback fetch: also fails
            MagicMock(stdout="", returncode=1),
        ]
        thread = fetch_issue_thread("https://github.com/owner/repo/issues/42")

    # Thread was returned successfully despite the 404s
    assert thread.title == "Broken link test"
    # No linked-content blocks added
    assert all("Linked" not in c for c in thread.comments)

def test_fetch_issue_thread_skips_self_reference():
    """A PR ref that matches the parent issue shouldn't self-fetch."""
    issue_json = json.dumps({
        "title": "Self-ref test",
        "body": "See #42 (this very issue)",
        "number": 42,
    })
    comments_json = json.dumps([])

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout=issue_json, returncode=0),
            MagicMock(stdout=comments_json, returncode=0),
        ]
        thread = fetch_issue_thread("https://github.com/owner/repo/issues/42")

    # Only 2 gh calls (issue + comments), no self-fetch
    assert mock_run.call_count == 2


def test_fetch_pr_thread_calls_pulls_endpoint():
    """A `/pull/<n>` URL fetches via the PR API for body + issues API for
    comments — the iter-5 fix that keeps the 6 merged-PR queries from
    bouncing at fetch_failed."""
    pr_json = json.dumps({
        "title": "fix: shadow depth wrapper crash",
        "body": "Resolves crash on creating a shadow depth wrapper. See #18090.",
        "number": 18091,
        "merge_commit_sha": "abcdef1234567890",
    })
    comments_json = json.dumps([
        {"body": "Reviewed, LGTM."},
        {"body": "Ship it."},
    ])
    issue_json = json.dumps({
        "title": "Crash creating ShadowGenerator",
        "body": "Stack trace shows null deref in `_setupRTT`.",
    })
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout=pr_json, returncode=0),
            MagicMock(stdout=comments_json, returncode=0),
            # Linked-issue fetch tries pulls first (expected to 404), then issues:
            MagicMock(stdout="", returncode=1),
            MagicMock(stdout=issue_json, returncode=0),
        ]
        thread = fetch_pr_thread(
            "https://github.com/BabylonJS/Babylon.js/pull/18091"
        )

    assert thread.title == "fix: shadow depth wrapper crash"
    assert "shadow depth wrapper" in thread.body
    # Conversation comments are present
    assert "LGTM" in "\n".join(thread.comments)
    assert "Ship it" in "\n".join(thread.comments)
    # Linked-issue body is appended
    joined = "\n".join(thread.comments)
    assert "null deref" in joined
    assert "#18090" in joined


def test_fetch_pr_thread_rejects_non_pr_url():
    import pytest
    with pytest.raises(ValueError, match="Not a GitHub PR URL"):
        fetch_pr_thread("https://github.com/owner/repo/issues/42")


def test_fetch_thread_dispatches_pr_url():
    """`fetch_thread()` must route `/pull/<n>` URLs to `fetch_pr_thread`,
    not `fetch_issue_thread` (which would raise ValueError)."""
    pr_stub = MagicMock(return_value=IssueThread(url="pr", title="p", body="b"))
    import gpa.eval.curation.triage as T
    with patch.object(T, "fetch_pr_thread", pr_stub):
        result = T.fetch_thread("https://github.com/o/r/pull/123")
    assert result.title == "p"
    pr_stub.assert_called_once()


def test_fetch_commit_thread_truncates_large_diffs():
    huge_patch = "\n".join(f"+ line {i}" for i in range(3000))  # ~36KB
    commit_json = json.dumps({
        "sha": "abc",
        "commit": {"message": "fix", "author": {"date": "..."}},
        "files": [{"filename": "big.c", "patch": huge_patch}],
    })
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=commit_json, returncode=0)
        thread = fetch_commit_thread("https://github.com/o/r/commit/abc")
    # Diff in comments should be capped
    all_comments = "\n".join(thread.comments)
    assert len(all_comments) <= 21000  # 20k cap + some overhead
    assert "truncated" in all_comments
