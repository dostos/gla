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


class CliAgent(AgentBackend):
    def __init__(self, spec: CliBackendSpec, *, model: str | None = None):
        self._spec = spec
        self._model = model

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
        return self._to_agent_result(metrics, elapsed)

    def _render_prompt(
        self, scenario, mode: str, tools: dict,
        *, have_frame: bool = False, have_snapshot: bool = False,
    ) -> str:
        description = (
            getattr(scenario, "description", None)
            or getattr(scenario, "bug_description", "")
            or ""
        )
        source_path = getattr(scenario, "source_path", "")
        block = self._tool_block(mode, have_frame, have_snapshot)
        blurb = self._scenario_blurb(scenario, tools)
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
            "- gpa upstream list [SUBDIR]         — orient inside the framework tree\n"
            "- gpa upstream grep PATTERN          — grep upstream snapshot\n"
            "- gpa upstream read PATH             — read a file from upstream snapshot\n"
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
