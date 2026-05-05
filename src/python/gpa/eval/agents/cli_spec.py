"""Backend spec + metrics dataclasses for CLI-driven eval agents."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class CliRunMetrics:
    diagnosis: str
    input_tokens: int
    output_tokens: int
    tool_calls: int
    num_turns: int
    tool_sequence: tuple[str, ...] = ()

    def with_appended_tail(self, other: "CliRunMetrics") -> "CliRunMetrics":
        """Merge a follow-up run's metrics into this one.

        Used by the JSON re-prompt fallback in `CliAgent`: the original
        response carries the prose reasoning (which the scorer's prose
        scorer reads), and the follow-up's JSON tail is appended so the
        file-level scorer can parse `proposed_patches`. Tokens / tool
        calls / turns sum across both runs.
        """
        return CliRunMetrics(
            diagnosis=(self.diagnosis or "").rstrip()
                + "\n\n"
                + (other.diagnosis or "").lstrip(),
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            tool_calls=self.tool_calls + other.tool_calls,
            num_turns=self.num_turns + other.num_turns,
            tool_sequence=tuple(self.tool_sequence) + tuple(other.tool_sequence),
        )


@dataclass(frozen=True)
class CliBackendSpec:
    name: str                                  # "claude-cli" | "codex-cli"
    binary: str
    base_args: tuple[str, ...]
    parse_run: Callable[[str, str], CliRunMetrics]
    timeout_sec: int = 1800
