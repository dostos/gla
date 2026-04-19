"""Tests for the Stack Overflow discovery + fetch helpers."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


def _make_resp(payload: str) -> MagicMock:
    """Build a MagicMock that behaves like urllib.request.urlopen's context-mgr."""
    r = MagicMock()
    r.__enter__ = MagicMock(return_value=r)
    r.__exit__ = MagicMock(return_value=False)
    r.read = MagicMock(return_value=payload.encode())
    return r


def test_search_questions_returns_sorequestion_list():
    payload = json.dumps({
        "items": [
            {
                "link": "https://stackoverflow.com/questions/111/how",
                "title": "How to bind texture correctly?",
                "body": "<p>I try to <code>glBindTexture</code>.</p>",
                "tags": ["opengl", "texture"],
                "accepted_answer_id": 999,
                "creation_date": 1700000000,
            },
            {
                "link": "https://stackoverflow.com/questions/222/tworld",
                "title": "Z-fighting in three.js",
                "body": "<p>z-fight</p>",
                "tags": ["three.js", "webgl"],
                "accepted_answer_id": 1000,
                "creation_date": 1700001000,
            },
        ]
    })
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _make_resp(payload)
        from gla.eval.curation.stackoverflow import search_questions, SOQuestion
        results = search_questions(["three.js"], per_page=10)
    assert len(results) == 2
    assert isinstance(results[0], SOQuestion)
    assert results[0].url == "https://stackoverflow.com/questions/111/how"
    assert results[0].title == "How to bind texture correctly?"
    assert results[0].tags == ["opengl", "texture"]
    assert results[0].accepted_answer_id == 999
    assert results[0].creation_date  # ISO string, non-empty


def test_search_questions_returns_empty_on_api_failure():
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = OSError("network down")
        from gla.eval.curation.stackoverflow import search_questions
        results = search_questions(["three.js"])
    assert results == []


def test_fetch_stackoverflow_thread_rejects_non_so_url():
    from gla.eval.curation.stackoverflow import fetch_stackoverflow_thread
    with pytest.raises(ValueError):
        fetch_stackoverflow_thread("https://github.com/mrdoob/three.js/issues/1")


def test_fetch_stackoverflow_thread_parses_question_and_accepted_answer():
    question_json = json.dumps({
        "items": [{
            "title": "How to bind texture?",
            "body": "<p>I try to <code>glBindTexture</code> but nothing.</p>",
            "tags": ["opengl"],
            "accepted_answer_id": 9999,
            "creation_date": 1700000000,
        }]
    })
    answer_json = json.dumps({
        "items": [{
            "score": 42,
            "body": "<p>You need to <code>glActiveTexture</code> first.</p>",
        }]
    })
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = [
            _make_resp(question_json),
            _make_resp(answer_json),
        ]
        from gla.eval.curation.stackoverflow import fetch_stackoverflow_thread
        thread = fetch_stackoverflow_thread(
            "https://stackoverflow.com/questions/12345/some-title"
        )
    assert thread.title == "How to bind texture?"
    assert "glBindTexture" in thread.body
    assert any("glActiveTexture" in c for c in thread.comments)
    assert any("Accepted Answer (score: 42)" in c for c in thread.comments)


def test_fetch_stackoverflow_thread_handles_missing_accepted_answer():
    question_json = json.dumps({
        "items": [{
            "title": "A question",
            "body": "<p>body</p>",
            "tags": ["opengl"],
            "creation_date": 1700000000,
            # no accepted_answer_id
        }]
    })
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _make_resp(question_json)
        from gla.eval.curation.stackoverflow import fetch_stackoverflow_thread
        thread = fetch_stackoverflow_thread(
            "https://stackoverflow.com/questions/9/q"
        )
    assert thread.title == "A question"
    assert thread.comments == []


def test_fetch_stackoverflow_thread_raises_if_question_not_found():
    empty_json = json.dumps({"items": []})
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _make_resp(empty_json)
        from gla.eval.curation.stackoverflow import fetch_stackoverflow_thread
        with pytest.raises(ValueError):
            fetch_stackoverflow_thread(
                "https://stackoverflow.com/questions/99999/does-not-exist"
            )


def test_strip_html_preserves_code_blocks():
    from gla.eval.curation.stackoverflow import _strip_html
    html_text = (
        "<p>Try this:</p>"
        "<pre><code>glEnable(GL_DEPTH_TEST);</code></pre>"
        "<p>Then call <code>glDraw()</code> later.</p>"
    )
    out = _strip_html(html_text)
    assert "glEnable(GL_DEPTH_TEST);" in out
    assert "```" in out  # pre block converted to fenced code
    assert "`glDraw()`" in out  # inline code wrapped in backticks
    # Paragraph tags stripped
    assert "<p>" not in out
    assert "</p>" not in out


def test_strip_html_unescapes_entities():
    from gla.eval.curation.stackoverflow import _strip_html
    html_text = "<p>Use &lt;canvas&gt; &amp; draw()</p>"
    out = _strip_html(html_text)
    assert "<canvas>" in out
    assert "&amp;" not in out
    assert "&" in out
