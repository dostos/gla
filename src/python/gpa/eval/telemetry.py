"""Parser for `claude -p --output-format stream-json` transcripts.

The stream format is a JSONL file where each line is one of:

- ``{"type": "system", "subtype": "init", ...}`` — session metadata
- ``{"type": "assistant", "message": {"content": [...], "usage": {...}}, ...}``
- ``{"type": "user", "message": {"content": [{"tool_use_id": ..., "content": ...}]}}``
- ``{"type": "result", "subtype": "success", "total_cost_usd": ..., "num_turns": ..., "usage": {...}}``

Assistant ``content`` blocks may include ``{"type": "tool_use", "name": ..., "input": {...}}``.

This parser extracts per-turn tool-call telemetry so we can stop self-reporting
(as we did in Rounds 5/6) and instead audit what the agent actually did.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# Heuristic: any Bash command whose first token is literally `gpa`, or that
# contains a recognised gpa subcommand with a word boundary. We list the
# subcommands explicitly so that "gpa" appearing as a filename fragment inside
# an unrelated bash pipeline does not count.
_GPA_SUBCOMMANDS = (
    "start",
    "stop",
    "env",
    "run",
    "report",
    "check",
    "dump",
    "frames",
    "annotate",
    "annotations",
)
_GPA_RE = re.compile(r"\bgpa\s+(" + "|".join(_GPA_SUBCOMMANDS) + r")\b")
_CURL_GPA_RE = re.compile(r"^\s*curl\b[^\n]*(?::18080|/api/v1|\$GPA_PORT)", re.MULTILINE)

# Some runs route file access through MCP servers (serena) even when Read is
# allowed. Map those to the equivalent first-class tool so per-mode aggregate
# counts stay comparable.
_MCP_ALIAS = {
    "mcp__plugin_serena_serena__read_file": "Read",
    "mcp__plugin_serena_serena__list_dir": "Glob",
    "mcp__plugin_serena_serena__find_file": "Glob",
    "mcp__plugin_serena_serena__search_for_pattern": "Grep",
    "mcp__plugin_serena_serena__find_symbol": "Grep",
    "mcp__plugin_serena_serena__get_symbols_overview": "Read",
    "mcp__plugin_serena_serena__execute_shell_command": "Bash",
}


def _classify_bash(command: str) -> str:
    """Classify a Bash tool-use command into gpa / curl / Bash."""
    if not command:
        return "Bash"
    stripped = command.lstrip()
    # `gpa ` prefix or any `gpa <subcommand>` fragment
    if stripped.startswith("gpa ") or _GPA_RE.search(command):
        return "gpa"
    if _CURL_GPA_RE.search(command):
        return "curl"
    return "Bash"


def _summarize_input(tool: str, tool_input: dict[str, Any]) -> str:
    """Return a short, human-readable summary of a tool invocation's input."""
    if not isinstance(tool_input, dict):
        return ""
    if tool == "Bash":
        cmd = tool_input.get("command", "")
        return cmd[:120]
    if tool in ("Read", "Edit", "Write"):
        return tool_input.get("file_path", "")[:120]
    if tool == "Grep":
        return (tool_input.get("pattern", "") + " " + tool_input.get("path", ""))[:120]
    if tool == "Glob":
        return tool_input.get("pattern", "")[:120]
    # Fallback: first 120 chars of the stringified input
    try:
        return json.dumps(tool_input, sort_keys=True)[:120]
    except Exception:
        return ""


def parse_stream_json(path: str) -> dict[str, Any]:
    """Parse a ``claude -p --output-format stream-json`` transcript.

    Returns a dict with:
      num_turns, total_cost_usd, tool_calls (ordered), tool_counts,
      total_tokens_in, total_tokens_out, cache_read, cache_creation,
      result_text, session_id.
    """
    p = Path(path)
    tool_calls: list[dict[str, str]] = []
    tool_counts: dict[str, int] = {}
    total_tokens_in = 0
    total_tokens_out = 0
    cache_read = 0
    cache_creation = 0
    num_turns = 0
    total_cost_usd = 0.0
    result_text: str | None = None
    session_id: str | None = None
    result_seen = False

    if not p.exists():
        return _empty(num_turns, total_cost_usd, tool_calls, tool_counts,
                     total_tokens_in, total_tokens_out, cache_read, cache_creation,
                     result_text, session_id)

    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue  # skip malformed lines
            if not isinstance(obj, dict):
                continue

            ev_type = obj.get("type")
            if ev_type == "system" and obj.get("subtype") == "init":
                session_id = obj.get("session_id") or session_id
                continue

            if ev_type == "assistant":
                msg = obj.get("message", {}) or {}
                usage = msg.get("usage") or {}
                # Accumulate tokens each time — matches what claude bills.
                total_tokens_in += int(usage.get("input_tokens", 0) or 0)
                total_tokens_out += int(usage.get("output_tokens", 0) or 0)
                cache_read += int(usage.get("cache_read_input_tokens", 0) or 0)
                cache_creation += int(usage.get("cache_creation_input_tokens", 0) or 0)

                content = msg.get("content") or []
                if isinstance(content, list):
                    for blk in content:
                        if not isinstance(blk, dict):
                            continue
                        if blk.get("type") == "tool_use":
                            name = blk.get("name") or "?"
                            tin = blk.get("input") or {}
                            if name == "Bash":
                                name = _classify_bash(
                                    (tin or {}).get("command", "") if isinstance(tin, dict) else ""
                                )
                            elif name in _MCP_ALIAS:
                                name = _MCP_ALIAS[name]
                            tool_counts[name] = tool_counts.get(name, 0) + 1
                            tool_calls.append({
                                "tool": name,
                                "input_summary": _summarize_input(
                                    "Bash" if name in ("Bash", "gpa", "curl") else name,
                                    tin if isinstance(tin, dict) else {},
                                ),
                            })
                continue

            if ev_type == "result":
                result_seen = True
                try:
                    total_cost_usd = float(obj.get("total_cost_usd") or 0.0)
                except Exception:
                    total_cost_usd = 0.0
                try:
                    num_turns = int(obj.get("num_turns") or 0)
                except Exception:
                    num_turns = 0
                r = obj.get("result")
                if isinstance(r, str):
                    result_text = r
                # The `result` event carries authoritative session totals in its
                # usage block. Prefer those over per-assistant-event accumulation
                # (which only captures the *delta* per turn, not the running sum).
                usage = obj.get("usage") or {}
                if isinstance(usage, dict):
                    total_tokens_in = int(usage.get("input_tokens", total_tokens_in) or total_tokens_in)
                    total_tokens_out = int(usage.get("output_tokens", total_tokens_out) or total_tokens_out)
                    cache_read = int(usage.get("cache_read_input_tokens", cache_read) or cache_read)
                    cache_creation = int(usage.get("cache_creation_input_tokens", cache_creation) or cache_creation)
                continue

    return {
        "num_turns": num_turns,
        "total_cost_usd": total_cost_usd,
        "tool_calls": tool_calls,
        "tool_counts": tool_counts,
        "total_tokens_in": total_tokens_in,
        "total_tokens_out": total_tokens_out,
        "cache_read": cache_read,
        "cache_creation": cache_creation,
        "result_text": result_text,
        "session_id": session_id,
        "result_seen": result_seen,
    }


def classify_verdict(run: dict, max_turns_budget: int = 40) -> str:
    """Bucket a scored run row into one of four verdicts.

    Verdicts:
      - ``solved`` — correct diagnosis within budget.
      - ``timeout`` — hit the turn cap; trajectory was plausible but ran out.
      - ``wrong`` — confidently-wrong diagnosis (agent chose to stop with a
        bad answer).
      - ``infra`` — build/capture/engine failure (no meaningful trajectory).

    Args:
      run: dict with keys ``correct`` (bool | None), ``turns`` (int),
        ``result`` (str), optionally ``error`` / ``stop_reason``.
      max_turns_budget: the turn cap used for the round (default 40).

    Returns: one of ``"solved"``, ``"timeout"``, ``"wrong"``, ``"infra"``.

    Rules:
      1. Explicit infra signal: ``error`` field set, ``stop_reason == "infra"``,
         or empty result with ``turns == 0`` → ``infra``.
      2. ``correct is True`` → ``solved``.
      3. ``correct is False`` and ``turns >= max_turns_budget - 1`` → ``timeout``.
         (The ``-1`` accounts for off-by-one in ``claude -p``'s turn accounting,
         which sometimes reports 40 when the cap is 40 and sometimes 39.)
      4. ``correct is False`` otherwise → ``wrong`` (whether ``root_cause`` is
         empty/near-empty or confidently wrong, the agent chose to stop without
         a correct answer).
      5. ``correct is None`` with a non-zero turn count falls through to
         ``wrong`` — without a score signal we cannot separate timeout from
         wrong beyond what rule 3 already catches.
    """
    # Rule 1: explicit infrastructure failures.
    if run.get("error"):
        return "infra"
    if run.get("stop_reason") == "infra":
        return "infra"
    result_text = run.get("result") or run.get("result_text") or ""
    turns = int(run.get("turns") or 0)
    if not str(result_text).strip() and turns == 0:
        # No result, no turns — the run never got off the ground.
        # Only classify as infra when we *also* lack a correctness signal;
        # a scored row with correct=False but turns=0 is still a wrong answer.
        if run.get("correct") is None:
            return "infra"

    correct = run.get("correct")

    # Rule 2: solved.
    if correct is True:
        return "solved"

    # Rule 3: timeout.
    if turns >= max_turns_budget - 1:
        return "timeout"

    # Rules 4 + 5: wrong.
    return "wrong"


def _empty(num_turns, total_cost_usd, tool_calls, tool_counts,
           total_tokens_in, total_tokens_out, cache_read, cache_creation,
           result_text, session_id):
    return {
        "num_turns": num_turns,
        "total_cost_usd": total_cost_usd,
        "tool_calls": tool_calls,
        "tool_counts": tool_counts,
        "total_tokens_in": total_tokens_in,
        "total_tokens_out": total_tokens_out,
        "cache_read": cache_read,
        "cache_creation": cache_creation,
        "result_text": result_text,
        "session_id": session_id,
        "result_seen": False,
    }
