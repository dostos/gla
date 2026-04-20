"""Tests for ``gpa run-browser`` CLI subcommand."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gpa.browser import BrowserRunResult, ChromiumNotFoundError
from gpa.cli.commands import run_browser as run_browser_cmd
from gpa.cli.session import Session


def _make_scenario(tmp_path: Path, name: str = "r21_stub",
                   *, with_index: bool = True) -> Path:
    root = tmp_path / "eval-browser"
    sdir = root / name
    sdir.mkdir(parents=True)
    if with_index:
        (sdir / "index.html").write_text("<html></html>")
    (sdir / "scenario.md").write_text("# stub\n")
    return sdir


def _make_extension(tmp_path: Path) -> Path:
    ext = tmp_path / "extension"
    ext.mkdir()
    (ext / "manifest.json").write_text("{}")
    return ext


def _make_session(tmp_path: Path) -> Session:
    return Session.create(dir=tmp_path / "sess", port=18080)


@pytest.fixture
def env_fixtures(tmp_path, monkeypatch):
    """Redirect scenario root + extension dir at the tmp copy."""
    scen = _make_scenario(tmp_path)
    ext = _make_extension(tmp_path)
    monkeypatch.setenv("GPA_BROWSER_SCENARIO_ROOT", str(scen.parent))
    monkeypatch.setenv("GPA_BROWSER_EXTENSION_DIR", str(ext))
    return types_ns(scenario_dir=scen, extension_dir=ext, tmp_path=tmp_path)


def types_ns(**kw):
    class NS:
        pass
    ns = NS()
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


# --------------------------------------------------------------------------- #
# Error paths
# --------------------------------------------------------------------------- #


def test_run_browser_scenario_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("GPA_BROWSER_SCENARIO_ROOT", str(tmp_path / "empty"))
    monkeypatch.setenv("GPA_BROWSER_EXTENSION_DIR", str(_make_extension(tmp_path)))

    buf = io.StringIO()
    rc = run_browser_cmd.run(scenario="nonexistent", print_stream=buf)
    assert rc == 1
    assert "scenario not found" in buf.getvalue()


def test_run_browser_no_index_html(tmp_path, monkeypatch):
    scen = _make_scenario(tmp_path, "nopage", with_index=False)
    monkeypatch.setenv("GPA_BROWSER_SCENARIO_ROOT", str(scen.parent))
    monkeypatch.setenv("GPA_BROWSER_EXTENSION_DIR", str(_make_extension(tmp_path)))

    buf = io.StringIO()
    rc = run_browser_cmd.run(scenario="nopage", print_stream=buf)
    assert rc == 1
    assert "index.html" in buf.getvalue()


def test_run_browser_chromium_not_found_exits_5(env_fixtures, tmp_path):
    sess = _make_session(tmp_path / "other")

    fake_runner = MagicMock()
    fake_runner.run.side_effect = ChromiumNotFoundError(
        "No chromium binary found on $PATH."
    )

    buf = io.StringIO()
    rc = run_browser_cmd.run(
        scenario="r21_stub",
        session_dir=sess.dir,
        runner=fake_runner,
        print_stream=buf,
    )
    assert rc == 5
    assert "chromium" in buf.getvalue().lower()


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_run_browser_invokes_runner(env_fixtures, tmp_path):
    sess = _make_session(tmp_path / "other")
    fake_runner = MagicMock()
    fake_runner.run.return_value = BrowserRunResult(
        scenario_name="r21_stub",
        frames_captured=1,
        sources_captured=1,
        timed_out=False,
        chromium_exit_code=0,
        duration_sec=0.5,
        static_port=54321,
        url="http://127.0.0.1:54321/r21_stub/index.html",
        gpa_done=True,
    )

    buf = io.StringIO()
    rc = run_browser_cmd.run(
        scenario="r21_stub",
        session_dir=sess.dir,
        runner=fake_runner,
        print_stream=buf,
    )
    assert rc == 0
    fake_runner.run.assert_called_once()
    opts = fake_runner.run.call_args.args[0]
    assert opts.scenario_name == "r21_stub"
    assert opts.session.dir == sess.dir
    assert "r21_stub" in str(opts.scenario_dir)

    # Summary line was printed.
    out = buf.getvalue()
    assert "frames=1" in out
    assert "sources=1" in out


def test_run_browser_timeout_zero_frames_exits_4(env_fixtures, tmp_path):
    sess = _make_session(tmp_path / "other")
    fake_runner = MagicMock()
    fake_runner.run.return_value = BrowserRunResult(
        scenario_name="r21_stub",
        frames_captured=0,
        sources_captured=0,
        timed_out=True,
        chromium_exit_code=0,
        duration_sec=30.0,
        static_port=11111,
        url="",
        gpa_done=False,
    )

    buf = io.StringIO()
    rc = run_browser_cmd.run(
        scenario="r21_stub",
        session_dir=sess.dir,
        runner=fake_runner,
        print_stream=buf,
    )
    assert rc == 4


def test_run_browser_no_session_exits_2(env_fixtures, tmp_path):
    """--session points somewhere with no token file."""
    bogus = tmp_path / "not-a-session"
    bogus.mkdir()

    buf = io.StringIO()
    rc = run_browser_cmd.run(
        scenario="r21_stub",
        session_dir=bogus,
        print_stream=buf,
    )
    assert rc == 2


# --------------------------------------------------------------------------- #
# argparse integration — the subcommand is wired into main
# --------------------------------------------------------------------------- #


def test_run_browser_registered_in_main_parser():
    from gpa.cli.main import build_parser
    parser = build_parser()
    # argparse raises SystemExit on unknown subcommand; parsing should work.
    args = parser.parse_args(["run-browser", "--scenario", "foo"])
    assert args.cmd == "run-browser"
    assert args.scenario == "foo"
    assert args.timeout == 30
    assert args.chromium_path is None
    assert args.keep_open is False
