"""Tests for ScenarioRunner.build_and_capture."""
from unittest.mock import MagicMock, patch

from gla.eval.runner import ScenarioRunner


def test_build_and_capture_returns_framebuffer_and_metadata(tmp_path):
    # Arrange — stub subprocess.run (bazel build) and the capture function.
    with patch("subprocess.run") as mock_run, \
         patch("gla.eval.runner._capture_via_rest") as mock_capture:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mock_capture.return_value = {
            "framebuffer_png": b"PNGDATA",
            "metadata": {"draw_call_count": 2, "draw_calls": []},
        }
        r = ScenarioRunner(
            gla_base_url="http://127.0.0.1:18080",
            gla_token="t",
            shim_path="/path/libgla_gl.so",
            bazel_bin="bazel",
            repo_root=str(tmp_path),
        )
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.terminate.return_value = None
            mock_proc.wait.return_value = None
            mock_popen.return_value = mock_proc
            result = r.build_and_capture("r1_test")

    assert result["framebuffer_png"] == b"PNGDATA"
    assert result["metadata"]["draw_call_count"] == 2


def test_build_and_capture_passes_correct_args(tmp_path):
    """Verify bazel build target and Popen command are constructed correctly."""
    with patch("subprocess.run") as mock_run, \
         patch("gla.eval.runner._capture_via_rest") as mock_capture:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mock_capture.return_value = {
            "framebuffer_png": b"",
            "metadata": {"draw_call_count": 0, "draw_calls": []},
        }
        r = ScenarioRunner(
            gla_base_url="http://127.0.0.1:18080",
            gla_token="tok",
            shim_path="/shim.so",
            bazel_bin="bazel",
            repo_root=str(tmp_path),
        )
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_popen.return_value = mock_proc
            r.build_and_capture("my_scenario")

    # bazel build was called with the right target
    mock_run.assert_called_once_with(
        ["bazel", "build", "//tests/eval:my_scenario"],
        cwd=str(tmp_path),
        check=True,
    )

    # Popen was called with xvfb-run and the scenario binary
    popen_call_args = mock_popen.call_args
    cmd = popen_call_args[0][0]
    assert cmd[0] == "xvfb-run"
    assert cmd[-1].endswith("my_scenario")

    # _capture_via_rest was called with correct url and token
    mock_capture.assert_called_once_with("http://127.0.0.1:18080", "tok")


def test_build_and_capture_terminates_proc_on_success(tmp_path):
    """Verify the child process is always terminated (finally block)."""
    with patch("subprocess.run") as mock_run, \
         patch("gla.eval.runner._capture_via_rest") as mock_capture:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mock_capture.return_value = {
            "framebuffer_png": b"X",
            "metadata": {"draw_call_count": 1, "draw_calls": []},
        }
        r = ScenarioRunner(repo_root=str(tmp_path))
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_popen.return_value = mock_proc
            r.build_and_capture("s1")

    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once()
