import json
import subprocess
from unittest.mock import patch, MagicMock
from gla.eval.curation.discover import GitHubSearch, DiscoveryCandidate, Discoverer, DEFAULT_QUERIES
from gla.eval.curation.coverage_log import CoverageLog, CoverageEntry

def _fake_gh_result():
    return json.dumps({
        "total_count": 2,
        "items": [
            {"html_url": "https://github.com/mrdoob/three.js/issues/111",
             "title": "Texture broken", "labels": [{"name": "Rendering"}],
             "created_at": "2024-02-01T00:00:00Z"},
            {"html_url": "https://github.com/mrdoob/three.js/issues/222",
             "title": "Shader z-fight", "labels": [{"name": "Rendering"}],
             "created_at": "2024-02-02T00:00:00Z"},
        ],
    })

def test_github_search_issues_parses_gh_output():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=_fake_gh_result(), returncode=0)
        search = GitHubSearch()
        results = search.search_issues('repo:mrdoob/three.js label:"Rendering"', per_page=5)
    assert len(results) == 2
    assert results[0].url == "https://github.com/mrdoob/three.js/issues/111"
    assert results[0].source_type == "issue"
    assert results[0].title == "Texture broken"

def test_github_search_uses_gh_api():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=_fake_gh_result(), returncode=0)
        GitHubSearch().search_issues("q", per_page=5)
        call = mock_run.call_args
        argv = call.args[0]
        assert argv[0] == "gh"
        assert argv[1] == "api"
        assert any("search/issues" in a for a in argv)

def test_discoverer_dedupes_already_reviewed_urls(tmp_path):
    log = CoverageLog(tmp_path / "log.jsonl")
    log.append(CoverageEntry(
        issue_url="https://github.com/x/y/issues/1",
        reviewed_at="2026-04-17T10:00:00Z", source_type="issue",
        triage_verdict="out_of_scope", root_cause_fingerprint=None,
        outcome="rejected", scenario_id=None, tier=None,
        rejection_reason="out_of_scope_compile_error",
        predicted_helps=None, observed_helps=None,
        failure_mode=None, eval_summary=None))

    class FakeSearch:
        def search_issues(self, q, per_page=30):
            return [
                DiscoveryCandidate(url="https://github.com/x/y/issues/1",
                                   source_type="issue", title="dup"),
                DiscoveryCandidate(url="https://github.com/x/y/issues/2",
                                   source_type="issue", title="new"),
            ]
        def search_commits(self, q, per_page=30):
            return []

    d = Discoverer(search=FakeSearch(), coverage_log=log,
                   queries={"issue": ["q1"], "commit": []}, batch_quota=10)
    candidates = d.run()
    urls = [c.url for c in candidates]
    assert "https://github.com/x/y/issues/2" in urls
    assert "https://github.com/x/y/issues/1" not in urls

def test_discoverer_respects_batch_quota(tmp_path):
    class FakeSearch:
        def search_issues(self, q, per_page=30):
            return [DiscoveryCandidate(url=f"https://x/{i}",
                                        source_type="issue", title="t")
                    for i in range(100)]
        def search_commits(self, q, per_page=30):
            return []

    log = CoverageLog(tmp_path / "log.jsonl")
    d = Discoverer(search=FakeSearch(), coverage_log=log,
                   queries={"issue": ["q1"], "commit": []}, batch_quota=5)
    candidates = d.run()
    assert len(candidates) == 5

def test_is_obviously_non_rendering_by_title():
    from gla.eval.curation.discover import _is_obviously_non_rendering, DiscoveryCandidate

    non_rendering_titles = [
        "TypeScript: Camera.rotationQuaternion should allow null type",
        "Docs: update webgl renderer tutorial",
        "NME: SmoothStep block losing input focus",
        "Build error on npm install",
        "ESLint config broken in examples folder",
        "VSCode plugin crashes on startup",
    ]
    for title in non_rendering_titles:
        cand = DiscoveryCandidate(url=f"https://x/{title[:5]}",
                                   source_type="issue", title=title)
        assert _is_obviously_non_rendering(cand) is True, \
            f"expected reject: {title}"

def test_is_obviously_non_rendering_by_labels():
    from gla.eval.curation.discover import _is_obviously_non_rendering, DiscoveryCandidate
    cand = DiscoveryCandidate(url="https://x/1", source_type="issue",
                               title="Plausible rendering-looking title",
                               labels=["documentation"])
    assert _is_obviously_non_rendering(cand) is True

def test_is_obviously_non_rendering_lets_real_rendering_through():
    from gla.eval.curation.discover import _is_obviously_non_rendering, DiscoveryCandidate

    rendering_titles = [
        "Z-fighting on large outdoor scenes with far clip",
        "Shader uniform not updated after material clone",
        "Transmission feedback loop when antialias:false",
        "InstanceNode UBO exceeds GL_MAX_UNIFORM_BLOCK_SIZE",
        "CubeTexture flipped on one axis",
    ]
    for title in rendering_titles:
        cand = DiscoveryCandidate(url=f"https://x/{title[:5]}",
                                   source_type="issue", title=title,
                                   labels=["Bug"])
        assert _is_obviously_non_rendering(cand) is False, \
            f"expected accept: {title}"

def test_discoverer_processes_stackoverflow_queries(tmp_path):
    """Discoverer wires the so_search provider end-to-end, yielding
    candidates with source_type='stackoverflow' and carrying accepted_answer_id."""
    from gla.eval.curation.discover import Discoverer
    from gla.eval.curation.stackoverflow import SOQuestion
    from gla.eval.curation.coverage_log import CoverageLog

    class FakeGitHub:
        def search_issues(self, q, per_page=30):
            return []
        def search_commits(self, q, per_page=30):
            return []

    class FakeSOSearch:
        def search_questions(self, tags, per_page=30):
            return [
                SOQuestion(
                    url="https://stackoverflow.com/questions/111/zfight",
                    title="Z-fighting on large scenes",
                    body_html="<p>body</p>",
                    tags=["three.js", "webgl"],
                    accepted_answer_id=555,
                    creation_date="2024-01-01T00:00:00+00:00",
                ),
                SOQuestion(
                    url="https://stackoverflow.com/questions/222/typescript",
                    title="TypeScript typings for Camera",
                    body_html="<p>typings</p>",
                    tags=["three.js", "typescript"],
                    accepted_answer_id=556,
                    creation_date="2024-01-02T00:00:00+00:00",
                ),
            ]

    log = CoverageLog(tmp_path / "log.jsonl")
    d = Discoverer(
        search=FakeGitHub(),
        so_search=FakeSOSearch(),
        coverage_log=log,
        queries={"issue": [], "commit": [], "stackoverflow": [["three.js"]]},
        batch_quota=10,
    )
    candidates = d.run()

    urls = [c.url for c in candidates]
    # Real rendering SO question passes through
    assert "https://stackoverflow.com/questions/111/zfight" in urls
    # Non-rendering (TypeScript) one is filtered at discovery
    assert "https://stackoverflow.com/questions/222/typescript" not in urls

    # Verify source_type + metadata carries over
    so_cand = next(c for c in candidates
                   if c.url == "https://stackoverflow.com/questions/111/zfight")
    assert so_cand.source_type == "stackoverflow"
    assert so_cand.metadata["accepted_answer_id"] == 555
    assert "three.js" in so_cand.labels

    # Filtered SO question should be logged as rejection
    entries = log.read_all()
    assert any(e.issue_url == "https://stackoverflow.com/questions/222/typescript"
               and e.source_type == "stackoverflow"
               and e.outcome == "rejected"
               and e.rejection_reason == "out_of_scope_not_rendering_bug"
               for e in entries)


def test_discoverer_skips_so_when_no_so_search_provider(tmp_path):
    """Without an so_search provider, SO queries are silently skipped
    (backward compat)."""
    from gla.eval.curation.discover import Discoverer
    from gla.eval.curation.coverage_log import CoverageLog

    class FakeGitHub:
        def search_issues(self, q, per_page=30):
            return []
        def search_commits(self, q, per_page=30):
            return []

    log = CoverageLog(tmp_path / "log.jsonl")
    d = Discoverer(
        search=FakeGitHub(),
        coverage_log=log,
        queries={"issue": [], "commit": [], "stackoverflow": [["three.js"]]},
        batch_quota=10,
    )
    candidates = d.run()
    assert candidates == []


def test_discoverer_skips_obviously_non_rendering(tmp_path):
    from gla.eval.curation.discover import Discoverer, DiscoveryCandidate
    from gla.eval.curation.coverage_log import CoverageLog

    class FakeSearch:
        def search_issues(self, q, per_page=30):
            return [
                DiscoveryCandidate(url="https://x/typescript-1", source_type="issue",
                                   title="TypeScript: fix camera typing"),
                DiscoveryCandidate(url="https://x/real-1", source_type="issue",
                                   title="z-fighting in shadows"),
            ]
        def search_commits(self, q, per_page=30):
            return []

    log = CoverageLog(tmp_path / "log.jsonl")
    d = Discoverer(search=FakeSearch(), coverage_log=log,
                   queries={"issue": ["q1"], "commit": []}, batch_quota=10)
    candidates = d.run()

    urls = [c.url for c in candidates]
    # TypeScript one was filtered at discovery
    assert "https://x/typescript-1" not in urls
    # Real rendering bug made it through
    assert "https://x/real-1" in urls
    # The filtered one should have a rejection entry in the log
    entries = log.read_all()
    assert any(e.issue_url == "https://x/typescript-1"
               and e.outcome == "rejected"
               and e.rejection_reason == "out_of_scope_not_rendering_bug"
               for e in entries)
