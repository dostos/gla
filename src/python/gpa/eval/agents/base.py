"""Base types for gpa.eval.agents.

AgentResult  — dataclass carrying all metrics from a single agent run.
AgentBackend — ABC that all agent implementations must satisfy.
AgentFn      — type alias matching gpa.eval.harness.AgentFn's call signature.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class AgentResult:
    diagnosis: str           # LLM's final diagnosis
    input_tokens: int
    output_tokens: int
    total_tokens: int
    tool_calls: int
    num_turns: int
    time_seconds: float
    conversation: list       # full message history for debugging
    # Strategy tracking — which tools were called and in what order
    tool_sequence: list = field(default_factory=list)  # ["read_source_file", "query_pixel", ...]
    pixel_queries: int = 0       # how many times query_pixel was called
    state_queries: int = 0       # inspect_drawcall + query_scene calls
    framebuffer_first: bool = False  # did agent query pixels before inspecting state?


class AgentBackend(ABC):
    """Abstract base class for eval agent backends.

    Subclasses implement :meth:`run` to drive an LLM (or any other
    inference backend) against a scenario and return an :class:`AgentResult`.
    """

    @abstractmethod
    def run(self, scenario, mode: str, tools: dict) -> AgentResult:
        """Run the agent against *scenario* in the given *mode*.

        Parameters
        ----------
        scenario:
            A scenario object (e.g. ``EvalScenario``) exposing at least
            ``description``/``bug_description`` and ``source_path``.
        mode:
            ``"with_gla"`` or ``"code_only"``.
        tools:
            Dict of harness-provided callables (``read_source``,
            ``run_with_capture``, snapshot tools, etc.).  Same shape as
            the ``tools`` arg passed by :class:`gpa.eval.harness.EvalHarness`.

        Returns
        -------
        AgentResult
        """


# Type alias matching gpa.eval.harness.AgentFn
AgentFn = Callable[
    [object, str, dict],
    tuple[str, int, int, int, int, float],
]
