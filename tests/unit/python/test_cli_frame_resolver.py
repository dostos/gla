import pytest
from gpa.cli.frame_resolver import resolve_frame


class _FakeClient:
    def __init__(self, responses: dict):
        self._responses = responses
    def get_json(self, path: str):
        if path not in self._responses:
            raise AssertionError(f"unexpected GET {path}")
        return self._responses[path]


def test_resolve_explicit_int(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    assert resolve_frame(client=_FakeClient({}), explicit=7) == 7


def test_resolve_uses_env(monkeypatch):
    monkeypatch.setenv("GPA_FRAME_ID", "42")
    assert resolve_frame(client=_FakeClient({}), explicit=None) == 42


def test_explicit_wins_over_env(monkeypatch):
    monkeypatch.setenv("GPA_FRAME_ID", "42")
    assert resolve_frame(client=_FakeClient({}), explicit=7) == 7


def test_falls_back_to_latest_via_rest(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    fake = _FakeClient({"/api/v1/frames/current/overview": {"frame_id": 99}})
    assert resolve_frame(client=fake, explicit=None) == 99


def test_latest_string_resolves_via_rest(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    fake = _FakeClient({"/api/v1/frames/current/overview": {"frame_id": 5}})
    assert resolve_frame(client=fake, explicit="latest") == 5


def test_latest_string_ignores_env(monkeypatch):
    """Explicit 'latest' should also call REST, NOT silently use GPA_FRAME_ID.

    Reasoning: if the user/agent explicitly passed --frame latest, they want
    the *current* frame, not whatever was pinned earlier.
    """
    monkeypatch.setenv("GPA_FRAME_ID", "42")
    fake = _FakeClient({"/api/v1/frames/current/overview": {"frame_id": 5}})
    assert resolve_frame(client=fake, explicit="latest") == 5


def test_env_with_invalid_int_raises(monkeypatch):
    monkeypatch.setenv("GPA_FRAME_ID", "not-a-number")
    with pytest.raises(ValueError):
        resolve_frame(client=_FakeClient({}), explicit=None)


def test_env_empty_string_falls_through(monkeypatch):
    """Empty string env should be treated as unset, not as an int."""
    monkeypatch.setenv("GPA_FRAME_ID", "")
    fake = _FakeClient({"/api/v1/frames/current/overview": {"frame_id": 8}})
    assert resolve_frame(client=fake, explicit=None) == 8
