import json
import subprocess
from unittest.mock import patch, MagicMock
from gla.eval.curation.discover import GitHubSearch, DiscoveryCandidate

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
