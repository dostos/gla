"""CLI-driven eval agent: shells out to a CLI (claude / codex) per scenario.

Unlike `ApiAgent`, the CLI agent does NOT drive a turn-by-turn loop in
Python. It hands the prompt to the CLI, which runs its own internal
agent loop, then parses the CLI's structured output for metrics and the
final diagnosis.
"""
from __future__ import annotations
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from gpa.eval.agents.base import AgentBackend, AgentResult
from gpa.eval.agents.cli_spec import CliBackendSpec, CliRunMetrics
from gpa.eval.scorer import _extract_json_tail


def _has_json_tail(text: str) -> bool:
    """True iff `text` ends with a parseable JSON object."""
    return _extract_json_tail(text or "") is not None


# Rate-limit signatures from the claude CLI. When the daily cap is
# exhausted the CLI prints a one-line message instead of running the
# agent loop. R16 forensics: 11 of 14 scenarios in a single cohort
# silently recorded these as "scenario failures" with 0 tokens.
# Detecting them lets the harness raise loudly so the operator can
# pause and resume after the cap resets.
_RATE_LIMIT_SIGNATURES = (
    "you've hit your limit",
    "you have hit your limit",
    "rate limit",
    "usage limit",
    "daily limit",
)


class CliRateLimitError(RuntimeError):
    """Raised when the CLI returned a rate-limit message instead of a
    real diagnosis. Bubbled up so run_all can stop the cohort cleanly
    rather than burn through a queue producing identical failures."""


def _looks_like_rate_limit(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(sig in low for sig in _RATE_LIMIT_SIGNATURES)


def _build_json_reprompt(prior_diagnosis: str) -> str:
    """Build a tight follow-up that asks ONLY for the JSON object."""
    truncated = (prior_diagnosis or "").strip()[-2000:]
    return (
        "Your previous response below was missing the required JSON "
        "object on the final line. The harness scores ONLY the JSON "
        "tail — without it your diagnosis cannot be evaluated.\n\n"
        "Reply with the JSON object and NOTHING ELSE: no markdown "
        "fence, no preamble, no trailing commentary. Use the schema "
        "from the original task. If you cannot pin a specific fix "
        "file/setting, emit the JSON anyway with confidence:\"low\" "
        "and an empty patches list.\n\n"
        "--- Your prior response (tail) ---\n"
        f"{truncated}\n"
        "--- End prior ---\n\n"
        "Now emit ONLY the JSON object as your entire response."
    )


class CliAgent(AgentBackend):
    def __init__(self, spec: CliBackendSpec, *, model: str | None = None):
        self._spec = spec
        self._model = model

    # When True, on a parse failure we send a tight follow-up asking for
    # ONLY the JSON object. Costs at most one extra round-trip; bounded
    # by the same CLI timeout. Disabled when no system_prompt is present
    # (i.e. legacy synthetic scenarios that don't expect JSON).
    JSON_REPROMPT_ENABLED = True

    def run(self, scenario, mode: str, tools: dict) -> AgentResult:
        env = os.environ.copy()

        # With-gla mode: try live capture; pin GPA_FRAME_ID when we have one.
        # If capture is unavailable (no Bazel target, build error, no engine,
        # etc.), the harness's run_with_capture lambda returns None — we
        # leave GPA_FRAME_ID unset so any `gpa` CLI calls fall back to env /
        # current-frame defaults instead of pointing at a sentinel id.
        frame_id = None
        if mode == "with_gla":
            frame_id = tools["run_with_capture"]()
            if frame_id is not None:
                env["GPA_FRAME_ID"] = str(frame_id)
            env.setdefault("GPA_BASE_URL", os.environ.get(
                "GPA_BASE_URL", "http://127.0.0.1:18080",
            ))
        # Source root (always set if we have a source path)
        source_path = getattr(scenario, "source_path", None)
        if source_path:
            env["GPA_SOURCE_ROOT"] = str(Path(source_path).parent)
        # Upstream snapshot root (passed via tools dict by the harness as a
        # callable: returns Path on success, None on fetch error).
        snap_provider = tools.get("snapshot_root") if tools else None
        snap = snap_provider() if callable(snap_provider) else snap_provider
        if snap:
            env["GPA_UPSTREAM_ROOT"] = str(snap)

        prompt = self._render_prompt(
            scenario, mode, tools,
            have_frame=(frame_id is not None),
            have_snapshot=(snap is not None),
        )
        argv = [self._spec.binary, *self._spec.base_args]
        argv = self._inject_model(argv, self._model)

        t0 = time.time()
        try:
            proc = subprocess.run(
                argv, input=prompt, capture_output=True, text=True,
                env=env, timeout=self._spec.timeout_sec,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.time() - t0
            return AgentResult(
                diagnosis="<timeout>",
                input_tokens=0, output_tokens=0, total_tokens=0,
                tool_calls=0, num_turns=0, time_seconds=elapsed,
                conversation=[],
            )
        elapsed = time.time() - t0

        metrics = self._spec.parse_run(proc.stdout, proc.stderr)

        # Bail loudly on rate-limit responses. claude-cli prints a
        # one-line "You've hit your limit · resets <time>" message and
        # exits cleanly, which the parser otherwise interprets as a
        # legitimate (terrible) diagnosis. Cohorts then record N
        # identical garbage failures. Better to stop the run, surface
        # the actual error, and resume after the cap resets.
        if (metrics.tool_calls == 0
                and metrics.input_tokens == 0
                and metrics.output_tokens == 0
                and _looks_like_rate_limit(metrics.diagnosis)):
            raise CliRateLimitError(
                f"CLI returned rate-limit message: "
                f"{metrics.diagnosis.strip()[:200]!r} — "
                "stop the cohort, resume after the cap resets."
            )

        # If the agent ignored the JSON output contract, give it one
        # follow-up shot. The first response stays in `metrics` for
        # cost accounting; we append the second response's diagnosis
        # so the scorer sees the JSON tail.
        if (self.JSON_REPROMPT_ENABLED
                and (tools or {}).get("system_prompt")
                and not _has_json_tail(metrics.diagnosis)):
            followup_prompt = _build_json_reprompt(metrics.diagnosis)
            t1 = time.time()
            try:
                proc2 = subprocess.run(
                    argv, input=followup_prompt, capture_output=True,
                    text=True, env=env,
                    timeout=self._spec.timeout_sec,
                )
                metrics2 = self._spec.parse_run(proc2.stdout, proc2.stderr)
                # Merge: keep the original diagnosis prose and append the
                # JSON tail from the follow-up so the scorer can read it
                # while the human-readable reasoning stays intact.
                if _has_json_tail(metrics2.diagnosis):
                    metrics = metrics.with_appended_tail(metrics2)
                elapsed += time.time() - t1
            except subprocess.TimeoutExpired:
                # Re-prompt timed out — accept the original (un-JSONed)
                # diagnosis. The scorer will still record no_signal but
                # we've spent the cost.
                elapsed += time.time() - t1

        return self._to_agent_result(metrics, elapsed)

    def _render_prompt(
        self, scenario, mode: str, tools: dict,
        *, have_frame: bool = False, have_snapshot: bool = False,
    ) -> str:
        # When the harness has rendered a bug-class-specific system prompt
        # (maintainer_framing / advisor / config_advice), use it as the
        # primary instruction — it carries the JSON output contract that
        # the scorer parses. We still prepend the tool block + scenario
        # blurb so the agent knows what tools are available and which
        # framework / repo it's looking at, but the system prompt drives
        # the task framing and final-output format.
        system_prompt = (tools or {}).get("system_prompt") or ""
        # Effective mode: harness sets this to "code_only" for
        # browser-tier scenarios in with_gla, so the GPA tool block is
        # dropped from the prompt (it can't help — native shim doesn't
        # see browser WebGL). Falls back to the requested mode.
        effective_mode = (tools or {}).get("effective_mode") or mode
        block = self._tool_block(effective_mode, have_frame, have_snapshot)
        blurb = self._scenario_blurb(scenario, tools)

        if system_prompt:
            parts: list[str] = []
            if blurb:
                parts.append(blurb)
            parts.append(block)
            parts.append(system_prompt.strip())
            return "\n".join(parts) + "\n"

        # Fallback for scenarios without a rendered system prompt
        # (bug_class == "legacy" or unknown — synthetic E1-E10 etc.):
        # keep the original one-line DIAGNOSIS/FIX framing.
        description = (
            getattr(scenario, "description", None)
            or getattr(scenario, "bug_description", "")
            or ""
        )
        source_path = getattr(scenario, "source_path", "")
        parts = ["You are debugging an OpenGL application that has a rendering bug.\n"]
        if blurb:
            parts.append(blurb)
        parts.append(block)
        parts.append(f"Problem:\n{description}\n")
        if source_path:
            parts.append(f"Source file: {source_path}\n")
        parts.append(
            "Investigate and end your final response with:\n"
            "DIAGNOSIS: <one-sentence root cause>\n"
            "FIX: <specific code change>"
        )
        return "\n".join(parts)

    @staticmethod
    def _scenario_blurb(scenario, tools: dict) -> str:
        """One-line "you are looking at X bug in Y repo (class Z, PR W)"
        prepended to the prompt so the agent doesn't waste turns sniffing
        framework identity / fix-PR location via list+grep."""
        framework = getattr(scenario, "framework", None) or ""
        repo = getattr(scenario, "upstream_snapshot_repo", None) or ""
        bug_class = (tools or {}).get("bug_class") or ""
        fix_pr = (tools or {}).get("fix_pr_url") or ""
        if not (framework or repo or bug_class or fix_pr):
            return ""
        bits = []
        if framework:
            bits.append(f"framework={framework}")
        if repo:
            bits.append(f"repo={repo}")
        if bug_class:
            bits.append(f"bug_class={bug_class}")
        if fix_pr:
            bits.append(f"fix_pr={fix_pr}")
        return "Scenario: " + ", ".join(bits) + "\n"

    @staticmethod
    def _tool_block(mode: str, have_frame: bool, have_snapshot: bool) -> str:
        """Render only the tools the agent can actually use right now."""
        live_block = (
            "Live-frame tools (GPA_FRAME_ID is set; --frame is automatic):\n"
            "- gpa frames overview                — current frame summary\n"
            "- gpa drawcalls list                 — list draw calls in this frame\n"
            "- gpa drawcalls explain --dc N       — deep dive on draw call N\n"
            "- gpa drawcalls diff --a A --b B     — compare two draws\n"
            "- gpa pixel get --x X --y Y          — read color/depth/stencil at pixel\n"
            "- gpa pixel explain --x X --y Y      — pixel→draw→scene-node trace\n"
            "- gpa scene find --predicate STR     — predicate-driven scene search\n"
            "- gpa scene get/camera/objects       — scene metadata\n"
            "- gpa diff frames --a A --b B        — diff two frames\n"
        )
        upstream_block = (
            "Upstream-snapshot tools (GPA_UPSTREAM_ROOT is set):\n"
            "- gpa upstream list [SUBDIR]                        — orient inside the framework tree\n"
            "- gpa upstream grep PATTERN [-C N]                  — grep with N lines of context\n"
            "- gpa upstream find-symbol NAME [--lang LANG]       — locate a definition (function/class/struct/etc)\n"
            "- gpa upstream outline PATH                          — list every function/class/struct in a file (cheap triage; 5-10x smaller than `read`)\n"
            "- gpa upstream read PATH [--lines START..END]        — read a file or just a line range (cap 512 KB)\n"
            "  prefer: outline → pick line range → read --lines\n"
            "  over:   read PATH (full 300 KB framework files burn tokens)\n"
        )
        source_block = (
            "Source tools:\n"
            "- gpa source read PATH               — read a file from buggy app\n"
        )
        if mode == "with_gla":
            if have_frame and have_snapshot:
                return live_block + "\n" + upstream_block + "\n" + source_block
            if have_frame:
                return live_block + "\n" + source_block
            if have_snapshot:
                return (
                    "Advisor mode: NO live frame for this scenario. "
                    "Investigate via the upstream snapshot.\n\n"
                    + upstream_block + "\n" + source_block
                    + "Typical loop: list → grep → read. Cite specific files.\n"
                )
            # No frame, no snapshot — just source if any.
            return source_block
        # code_only
        if have_snapshot:
            return upstream_block + "\n" + source_block
        return source_block

    def _inject_model(self, argv: list[str], model: str | None) -> list[str]:
        if not model:
            return argv
        # claude-cli accepts --model <id>. codex-cli accepts --model or -c model="<id>".
        # Stick with --model for both — both binaries accept it.
        return [*argv, "--model", model]

    def _to_agent_result(self, metrics: CliRunMetrics, elapsed: float) -> AgentResult:
        seq = list(metrics.tool_sequence)
        pixel_q = sum(1 for s in seq if s.startswith("gpa pixel"))
        state_q = sum(
            1 for s in seq
            if s.startswith("gpa drawcalls") or s.startswith("gpa scene")
        )
        fb_first = False
        for s in seq:
            if s.startswith("gpa pixel"):
                fb_first = True
                break
            if s.startswith("gpa drawcalls") or s.startswith("gpa scene"):
                break
        return AgentResult(
            diagnosis=metrics.diagnosis,
            input_tokens=metrics.input_tokens,
            output_tokens=metrics.output_tokens,
            total_tokens=metrics.input_tokens + metrics.output_tokens,
            tool_calls=metrics.tool_calls,
            num_turns=metrics.num_turns,
            time_seconds=elapsed,
            conversation=[],          # CLI loop is opaque
            tool_sequence=seq,
            pixel_queries=pixel_q,
            state_queries=state_q,
            framebuffer_first=fb_first,
        )


from gpa.eval.agents.cli_parsers import (
    parse_claude_stream_json,
    parse_codex_ndjson,
)


CLAUDE_CLI_SPEC = CliBackendSpec(
    name="claude-cli",
    binary="claude",
    base_args=("-p", "--output-format", "stream-json", "--verbose"),
    parse_run=parse_claude_stream_json,
)

CODEX_CLI_SPEC = CliBackendSpec(
    name="codex-cli",
    binary="codex",
    base_args=(
        "exec",
        "--json",
        "-s", "workspace-write",
        "--skip-git-repo-check",
    ),
    parse_run=parse_codex_ndjson,
)
