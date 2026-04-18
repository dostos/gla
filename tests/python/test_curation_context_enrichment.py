"""Tests for context enrichment — PR/commit file snapshotting."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from gla.eval.curation.context_enrichment import (
    UpstreamFile,
    enrich_context,
    extract_refs,
    fetch_commit_files_at_parent,
    fetch_pr_files_at_parent,
    format_for_drafter,
)


# ---------------------------------------------------------------------------
# extract_refs
# ---------------------------------------------------------------------------


def test_extract_refs_finds_pr_urls():
    text = "See https://github.com/mrdoob/three.js/pull/12345 for the fix."
    refs = extract_refs(text, "owner", "repo")
    assert ("mrdoob", "three.js", "pull", "12345") in refs


def test_extract_refs_finds_short_form():
    text = "Fixed by #9876."
    refs = extract_refs(text, "owner", "repo")
    assert ("owner", "repo", "pull", "9876") in refs


def test_extract_refs_finds_commit_urls():
    text = "Introduced in https://github.com/owner/repo/commit/abc1234def56."
    refs = extract_refs(text, "owner", "repo")
    assert ("owner", "repo", "commit", "abc1234def56") in refs


def test_extract_refs_dedupes():
    text = "#42 and #42 and https://github.com/o/r/pull/42"
    refs = extract_refs(text, "o", "r")
    pr_refs = [r for r in refs if r[2] == "pull" and r[3] == "42"]
    assert len(pr_refs) == 1


def test_extract_refs_bounds_to_10():
    text = " ".join(f"#{i}" for i in range(100))
    refs = extract_refs(text, "o", "r")
    assert len(refs) <= 10


def test_extract_refs_handles_empty_text():
    assert extract_refs("", "o", "r") == []
    assert extract_refs(None, "o", "r") == []


# ---------------------------------------------------------------------------
# fetch_pr_files_at_parent
# ---------------------------------------------------------------------------


def test_fetch_pr_files_uses_parent_sha():
    """fetch_pr_files_at_parent should fetch file contents at base.sha."""
    pr_json = json.dumps({
        "base": {"sha": "parent123"},
        "number": 42,
    })
    files_json = json.dumps([
        {"filename": "src/renderer.js", "status": "modified"},
        {"filename": "docs/readme.md", "status": "modified"},  # ignored (.md)
    ])
    contents_js_json = json.dumps({
        "encoding": "base64",
        "content": "Zm9vKCk7Cg==",  # base64 of "foo();\n"
    })

    with patch("gla.eval.curation.context_enrichment.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout=pr_json, returncode=0),
            MagicMock(stdout=files_json, returncode=0),
            MagicMock(stdout=contents_js_json, returncode=0),
        ]
        files = fetch_pr_files_at_parent("o", "r", "42")

    assert len(files) == 1
    assert files[0].path == "src/renderer.js"
    assert "foo();" in files[0].content
    assert files[0].ref == "PR #42"
    # The third call should have used ref=parent123
    third_call_argv = mock_run.call_args_list[2].args[0]
    assert any("ref=parent123" in arg for arg in third_call_argv)


def test_fetch_pr_files_filters_by_extension():
    pr_json = json.dumps({"base": {"sha": "p"}, "number": 1})
    files_json = json.dumps([
        {"filename": "README.md"},
        {"filename": "package.json"},
        {"filename": "src/main.c"},  # allowed
        {"filename": "shaders/vert.glsl"},  # allowed
    ])
    c_json = json.dumps({"encoding": "base64", "content": "aGVsbG8="})  # "hello"

    with patch("gla.eval.curation.context_enrichment.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout=pr_json, returncode=0),
            MagicMock(stdout=files_json, returncode=0),
            MagicMock(stdout=c_json, returncode=0),
            MagicMock(stdout=c_json, returncode=0),
        ]
        files = fetch_pr_files_at_parent("o", "r", "1")

    paths = [f.path for f in files]
    assert "src/main.c" in paths
    assert "shaders/vert.glsl" in paths
    assert "README.md" not in paths
    assert "package.json" not in paths


def test_fetch_pr_files_returns_empty_on_pr_fetch_failure():
    with patch("gla.eval.curation.context_enrichment.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=1)
        files = fetch_pr_files_at_parent("o", "r", "42")
    assert files == []


def test_fetch_pr_files_returns_empty_on_missing_base_sha():
    pr_json = json.dumps({"number": 1})  # no base
    with patch("gla.eval.curation.context_enrichment.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=pr_json, returncode=0)
        files = fetch_pr_files_at_parent("o", "r", "1")
    assert files == []


def test_fetch_pr_files_skips_non_base64_contents():
    pr_json = json.dumps({"base": {"sha": "p"}, "number": 1})
    files_json = json.dumps([{"filename": "a.c"}])
    bad_json = json.dumps({"encoding": "utf-8", "content": "hi"})
    with patch("gla.eval.curation.context_enrichment.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout=pr_json, returncode=0),
            MagicMock(stdout=files_json, returncode=0),
            MagicMock(stdout=bad_json, returncode=0),
        ]
        files = fetch_pr_files_at_parent("o", "r", "1")
    assert files == []


def test_fetch_pr_files_truncates_large_content():
    """Files over _MAX_FILE_SIZE are truncated with a marker."""
    import base64

    from gla.eval.curation.context_enrichment import _MAX_FILE_SIZE

    big = ("A" * (_MAX_FILE_SIZE + 500)).encode()
    big_b64 = base64.b64encode(big).decode()
    pr_json = json.dumps({"base": {"sha": "p"}, "number": 1})
    files_json = json.dumps([{"filename": "big.c"}])
    big_json = json.dumps({"encoding": "base64", "content": big_b64})

    with patch("gla.eval.curation.context_enrichment.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout=pr_json, returncode=0),
            MagicMock(stdout=files_json, returncode=0),
            MagicMock(stdout=big_json, returncode=0),
        ]
        files = fetch_pr_files_at_parent("o", "r", "1")

    assert len(files) == 1
    assert files[0].truncated is True
    assert "[truncated]" in files[0].content


# ---------------------------------------------------------------------------
# fetch_commit_files_at_parent
# ---------------------------------------------------------------------------


def test_fetch_commit_files_uses_parent_sha():
    commit_json = json.dumps({
        "sha": "abc123",
        "parents": [{"sha": "parent999"}],
        "files": [{"filename": "src/foo.c"}],
    })
    c_json = json.dumps({"encoding": "base64", "content": "aGVsbG8="})

    with patch("gla.eval.curation.context_enrichment.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout=commit_json, returncode=0),
            MagicMock(stdout=c_json, returncode=0),
        ]
        files = fetch_commit_files_at_parent("o", "r", "abc123")

    assert len(files) == 1
    assert files[0].path == "src/foo.c"
    assert files[0].ref.startswith("commit ")
    second_call = mock_run.call_args_list[1].args[0]
    assert any("ref=parent999" in a for a in second_call)


def test_fetch_commit_files_returns_empty_with_no_parents():
    commit_json = json.dumps({
        "sha": "abc123",
        "parents": [],
        "files": [{"filename": "src/foo.c"}],
    })
    with patch("gla.eval.curation.context_enrichment.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=commit_json, returncode=0)
        files = fetch_commit_files_at_parent("o", "r", "abc123")
    assert files == []


# ---------------------------------------------------------------------------
# enrich_context
# ---------------------------------------------------------------------------


def test_enrich_context_combines_pr_and_commit_refs():
    """Text with both a PR and a commit ref fetches both."""
    text = (
        "Fixed by #42 and introduced in "
        "https://github.com/o/r/commit/abc1234def56."
    )
    pr_json = json.dumps({"base": {"sha": "p1"}, "number": 42})
    files1 = json.dumps([{"filename": "a.c"}])
    commit_json = json.dumps({
        "sha": "abc1234def56",
        "parents": [{"sha": "p2"}],
        "files": [{"filename": "b.c"}],
    })
    c_json = json.dumps({"encoding": "base64", "content": "aGVsbG8="})

    with patch("gla.eval.curation.context_enrichment.subprocess.run") as mock_run:
        # Order: commit refs extracted first, then PR refs. enrich_context
        # iterates the (commit, pull) tuples in that order:
        #   1. commits/abc1234def56   (commit_json)
        #   2. contents/b.c?ref=p2    (c_json)
        #   3. pulls/42               (pr_json)
        #   4. pulls/42/files         (files1)
        #   5. contents/a.c?ref=p1    (c_json)
        mock_run.side_effect = [
            MagicMock(stdout=commit_json, returncode=0),
            MagicMock(stdout=c_json, returncode=0),
            MagicMock(stdout=pr_json, returncode=0),
            MagicMock(stdout=files1, returncode=0),
            MagicMock(stdout=c_json, returncode=0),
        ]
        files = enrich_context(text, default_owner="o", default_repo="r")

    paths = [f.path for f in files]
    assert "a.c" in paths
    assert "b.c" in paths


def test_enrich_context_respects_max_total_files():
    text = "https://github.com/o/r/pull/1 https://github.com/o/r/pull/2"
    pr_json_1 = json.dumps({"base": {"sha": "p1"}, "number": 1})
    files_1 = json.dumps([{"filename": "a.c"}, {"filename": "b.c"}])
    c_json = json.dumps({"encoding": "base64", "content": "aGVsbG8="})

    with patch("gla.eval.curation.context_enrichment.subprocess.run") as mock_run:
        # With max_total_files=2, the first PR's two files fill the budget and
        # the second PR is never fetched. That means exactly 4 gh calls total:
        # PR metadata, files list, and two contents fetches.
        mock_run.side_effect = [
            MagicMock(stdout=pr_json_1, returncode=0),
            MagicMock(stdout=files_1, returncode=0),
            MagicMock(stdout=c_json, returncode=0),
            MagicMock(stdout=c_json, returncode=0),
        ]
        files = enrich_context(
            text, default_owner="o", default_repo="r", max_total_files=2,
        )

    assert len(files) == 2


def test_enrich_context_empty_when_no_refs():
    with patch("gla.eval.curation.context_enrichment.subprocess.run") as mock_run:
        result = enrich_context(
            "just some prose, no refs", default_owner="o", default_repo="r",
        )
    assert result == []
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# format_for_drafter
# ---------------------------------------------------------------------------


def test_format_for_drafter_produces_labeled_blocks():
    files = [
        UpstreamFile(path="src/a.c", content="int main(){}",
                     ref="PR #42", truncated=False),
        UpstreamFile(path="src/b.c", content="void f(){}",
                     ref="commit abc1234", truncated=True),
    ]
    text = format_for_drafter(files)
    assert "=== Upstream source (pre-fix state) ===" in text
    assert "--- src/a.c (from PR #42) ---" in text
    assert "int main(){}" in text
    assert "truncated" in text  # marker on b.c


def test_format_for_drafter_empty_returns_empty_string():
    assert format_for_drafter([]) == ""
