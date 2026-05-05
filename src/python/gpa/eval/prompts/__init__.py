"""Prompt templates for the eval harness agent.

Prompts are plain Markdown files so they're easy to review in a PR and
easy to diff across rounds.  :func:`load_prompt` reads a named template
and returns its text; :func:`render_maintainer_prompt` does the simple
``{placeholder}`` substitution required by the maintainer-framing
prompt.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """Return the raw text of ``{name}.md`` from this package."""
    return (_DIR / f"{name}.md").read_text(encoding="utf-8")


def render_maintainer_prompt(
    framework: str,
    user_report: str,
    upstream_snapshot_repo: Optional[str],
    upstream_snapshot_sha: Optional[str],
    mode: str = "code_only",
    scope_hint: Optional[str] = None,
) -> str:
    """Render the maintainer-framing prompt for a scenario.

    Args:
      framework: e.g. ``"three.js"`` or the scenario's framework field.
        Falls back to ``"the framework"`` when empty or unknown.
      user_report: The verbatim issue body from the scenario.
      upstream_snapshot_repo: Repo URL of the framework at the pre-fix SHA.
      upstream_snapshot_sha: The pre-fix parent SHA.
      mode: ``"with_gla"`` or ``"code_only"`` — controls whether the
        OpenGPA tool block is included.
      scope_hint: Optional pre-computed scope-hint text from
        :func:`gpa.eval.scope_hint.compute_scope_hint`. When provided,
        the ``{scope_hint_block}`` placeholder is filled with a short
        section telling the agent the size+area of the canonical fix.
        When None, the placeholder is dropped.

    Returns:
      The fully-rendered prompt text.
    """
    template = load_prompt("maintainer_framing")
    fw = framework or "the framework"
    repo = upstream_snapshot_repo or "(no snapshot repo configured)"
    sha = upstream_snapshot_sha or "HEAD"

    # Strip the ``[with_gpa only: ...]`` gated block for code_only mode.
    # The template uses square-bracket HTML comments so we can handle the
    # substitution deterministically without a full templating engine.
    if mode == "with_gla":
        # Remove the markers but keep the content.
        template = template.replace("<!-- WITH_GPA_ONLY -->", "").replace(
            "<!-- END_WITH_GPA_ONLY -->", ""
        )
    else:
        # Drop the entire block including markers.
        import re as _re
        template = _re.sub(
            r"<!-- WITH_GPA_ONLY -->.*?<!-- END_WITH_GPA_ONLY -->\n?",
            "",
            template,
            flags=_re.DOTALL,
        )

    return (
        template
        .replace("{framework}", fw)
        .replace("{user_report}", (user_report or "").strip())
        .replace("{upstream_snapshot.repo}", repo)
        .replace("{upstream_snapshot.sha}", sha)
        .replace("{scope_hint_block}", _build_scope_hint_block(scope_hint))
    )


def _build_scope_hint_block(scope_hint: Optional[str]) -> str:
    """Inline section the agent sees when a scope hint is available.

    Empty string when no hint — the placeholder collapses to nothing
    so the prompt stays clean. The hint is framed as calibration, not
    as the answer: the agent still has to find the specific files.
    """
    if not scope_hint or not scope_hint.strip():
        return ""
    return (
        "\n# Scope hint\n\n"
        f"The canonical fix has scope: **{scope_hint.strip()}**\n\n"
        "Use this to calibrate where to look — it tells you the size "
        "and area of the fix, not the specific files. Don't propose "
        "fixes outside this scope unless you find compelling evidence "
        "that the canonical fix missed something.\n"
    )


__all__ = [
    "load_prompt",
    "render_maintainer_prompt",
]
