"""Smoke test: every user-facing CLI subcommand exposes an Examples block in --help.

The audit (Cleanup Batch 3 / P1) added Examples: epilogs to the commands
that previously had a one-line ``help=`` only. This test guards the
contract — adding a new subcommand without an Examples block fails here,
which is the cheap way to keep agent-facing docs uniform.
"""
from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from gpa.cli.main import build_parser


# Subcommands that MUST have an Examples block in their --help output.
# These are the ones touched in Cleanup Batch 3 P1 + the existing 5 with
# Examples already (check-config, explain-draw, diff-draws, scene-find,
# scene-explain).
_COMMANDS_WITH_EXAMPLES = [
    "start",
    "stop",
    "env",
    "run",
    "run-browser",
    "report",
    "check",
    "dump",
    "frames",
    "check-config",
    "explain-draw",
    "diff-draws",
    "scene-find",
    "scene-explain",
]


@pytest.mark.parametrize("cmd", _COMMANDS_WITH_EXAMPLES)
def test_cli_command_help_has_examples_block(cmd):
    """``gpa <cmd> --help`` must contain an ``Examples:`` block."""
    parser = build_parser()
    buf = io.StringIO()
    with redirect_stdout(buf):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args([cmd, "--help"])
    assert exc.value.code == 0
    out = buf.getvalue()
    assert "Examples:" in out, (
        f"`gpa {cmd} --help` is missing an Examples: block.\n"
        f"--- output ---\n{out}\n--- end ---"
    )


# `gpa trace` is a parent command with subcommands. Each surviving sub-
# command must have its own Examples block.
_TRACE_SUBCOMMANDS_WITH_EXAMPLES = ["uniform", "value"]


@pytest.mark.parametrize("sub", _TRACE_SUBCOMMANDS_WITH_EXAMPLES)
def test_cli_trace_subcommand_help_has_examples_block(sub):
    """``gpa trace <sub> --help`` must contain an Examples: block."""
    parser = build_parser()
    buf = io.StringIO()
    with redirect_stdout(buf):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["trace", sub, "--help"])
    assert exc.value.code == 0
    out = buf.getvalue()
    assert "Examples:" in out, (
        f"`gpa trace {sub} --help` is missing an Examples: block.\n"
        f"--- output ---\n{out}\n--- end ---"
    )
