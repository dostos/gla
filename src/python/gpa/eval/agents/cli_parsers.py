"""Parsers for stream-json / NDJSON outputs of CLI agents.

Supported backends:
- claude-cli: `claude -p --output-format stream-json --verbose`
- codex-cli:  `codex exec --json`

Both parsers are pure text → CliRunMetrics transformers; no subprocess imports.
"""
from __future__ import annotations
import json
import shlex
from gpa.eval.agents.cli_spec import CliRunMetrics


def parse_claude_stream_json(stdout: str, stderr: str) -> CliRunMetrics:
    """Parse `claude -p --output-format stream-json --verbose` output.

    Counts tool_use blocks, sums token usage, extracts final result text.
    Tolerant of extra whitespace and trailing partial lines.

    Event schema (Anthropic stream-json format):
    - {"type": "system", "subtype": "init", ...}  — first event
    - {"type": "assistant", "message": {"content": [...], "usage": {...}}}
    - {"type": "result", "subtype": "success", "result": "...", "num_turns": N,
       "usage": {...}}  — canonical totals override per-turn sums
    """
    diagnosis = ""
    input_tokens = 0
    output_tokens = 0
    tool_calls = 0
    num_turns = 0
    tool_sequence: list[str] = []

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        ev_type = evt.get("type")
        if ev_type == "assistant":
            num_turns += 1
            msg = evt.get("message", {}) or {}
            usage = msg.get("usage", {}) or {}
            input_tokens += int(usage.get("input_tokens", 0) or 0)
            output_tokens += int(usage.get("output_tokens", 0) or 0)
            for block in msg.get("content", []) or []:
                if block.get("type") == "tool_use":
                    tool_calls += 1
                    tool_sequence.append(block.get("name", "<unknown>"))
        elif ev_type == "result":
            text = evt.get("result", "") or ""
            if text:
                diagnosis = text
            # If `usage` on result is the canonical total, prefer it.
            usage = evt.get("usage", {}) or {}
            if usage:
                input_tokens = int(usage.get("input_tokens", input_tokens) or input_tokens)
                output_tokens = int(usage.get("output_tokens", output_tokens) or output_tokens)
            if "num_turns" in evt:
                num_turns = int(evt["num_turns"])

    return CliRunMetrics(
        diagnosis=diagnosis,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_calls=tool_calls,
        num_turns=num_turns,
        tool_sequence=tuple(tool_sequence),
    )


def parse_codex_ndjson(stdout: str, stderr: str) -> CliRunMetrics:
    """Parse `codex exec --json` event stream.

    Counts shell calls (command_execution items) whose command starts with
    `gpa`, extracts the final agent_message, and reads token usage from
    the turn.completed event or falls back to stderr for a summary line.

    Real codex --json event schema (captured 2026-05-02):
    - {"type": "thread.started", "thread_id": "..."}
    - {"type": "turn.started"}
    - {"type": "item.started",   "item": {"id":"...", "type":"command_execution",
       "command": "/bin/bash -lc '<cmd>'", ...}}
    - {"type": "item.completed", "item": {"id":"...", "type":"command_execution",
       "command": "...", "aggregated_output":"...", "exit_code":0}}
    - {"type": "item.completed", "item": {"id":"...", "type":"agent_message",
       "text": "<final text>"}}
    - {"type": "turn.completed", "usage": {"input_tokens":N, "cached_input_tokens":N,
       "output_tokens":N, "reasoning_output_tokens":N}}

    Note: older / documented schema used msg-wrapper events (local_shell_call /
    task_complete); the real binary emits the flat item schema above.  We
    handle both for forward-compatibility.
    """
    diagnosis = ""
    tool_calls = 0
    num_turns = 0
    tool_sequence: list[str] = []
    last_agent_msg = ""
    input_tokens = 0
    output_tokens = 0

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue

        ev_type = evt.get("type", "")

        # --- Real codex item-based schema ---
        # Only count on item.completed (authoritative); item.started is provisional.
        if ev_type == "item.completed":
            item = evt.get("item") or {}
            itype = item.get("type", "")
            if itype == "command_execution":
                cmd = item.get("command", "") or ""
                # Strip leading shell wrapper: /bin/bash -lc '<cmd>'
                inner = _extract_inner_command(cmd)
                if inner.startswith("gpa "):
                    tool_calls += 1
                    parts = inner.split()
                    tool_sequence.append(" ".join(parts[:2]))
            elif itype == "agent_message":
                text = item.get("text", "") or ""
                if text:
                    num_turns += 1
                    last_agent_msg = text
        elif ev_type == "turn.completed":
            usage = evt.get("usage") or {}
            input_tokens = int(usage.get("input_tokens", 0) or 0)
            output_tokens = int(usage.get("output_tokens", 0) or 0)

        # --- Legacy / documented msg-wrapper schema ---
        elif ev_type == "":
            pass  # unknown, skip
        else:
            msg = evt.get("msg") or {}
            mtype = msg.get("type", "")
            if mtype == "agent_message":
                num_turns += 1
                last_agent_msg = msg.get("message", "") or last_agent_msg
            elif mtype == "task_complete":
                diagnosis = msg.get("last_agent_message", last_agent_msg) or last_agent_msg
            elif mtype == "local_shell_call":
                command = (msg.get("action") or {}).get("command") or []
                inner = ""
                for i, c in enumerate(command):
                    if c == "-lc" and i + 1 < len(command):
                        inner = command[i + 1].strip()
                        break
                if not inner and command:
                    inner = " ".join(command)
                if inner.startswith("gpa "):
                    tool_calls += 1
                    parts = inner.split()
                    tool_sequence.append(" ".join(parts[:2]))

    if not diagnosis:
        diagnosis = last_agent_msg

    # Token fallback from stderr if turn.completed wasn't in stdout
    if input_tokens == 0:
        for ln in stderr.splitlines():
            s = ln.strip()
            if s.startswith("tokens used"):
                digits = "".join(ch for ch in s if ch.isdigit() or ch == ",").replace(",", "")
                if digits:
                    input_tokens = int(digits)
                    break

    return CliRunMetrics(
        diagnosis=diagnosis,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_calls=tool_calls,
        num_turns=num_turns,
        tool_sequence=tuple(tool_sequence),
    )


def _extract_inner_command(cmd: str) -> str:
    """Extract inner command from a shell wrapper like /bin/bash -lc '<cmd>'.

    Uses shlex.split to correctly handle single/double-quoted arguments.
    Falls back to the original string on parse errors.
    """
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return cmd.strip()
    for i, tok in enumerate(tokens):
        if tok == "-lc" and i + 1 < len(tokens):
            return tokens[i + 1].strip()
    return cmd.strip()
