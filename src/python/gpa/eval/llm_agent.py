"""Compatibility shim — moved to gpa.eval.agents.api_agent.

This module exists to keep existing imports of ``gpa.eval.llm_agent``
working after Task 17 of the cli/eval refactor. New code should import
from ``gpa.eval.agents`` directly.

Note: patch targets for unit tests have been updated to point at
``gpa.eval.agents.api_agent`` where the actual implementations live.
"""
from __future__ import annotations

import warnings

from gpa.eval.agents.api_agent import (
    ApiAgent as EvalAgent,
    GpaToolExecutor,
    GPA_TOOLS,
    CODE_ONLY_TOOLS,
    SNAPSHOT_TOOLS,
    build_agent_fn,
)
from gpa.eval.agents.base import AgentResult

warnings.warn(
    "gpa.eval.llm_agent is deprecated; import from gpa.eval.agents",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "EvalAgent",
    "GpaToolExecutor",
    "GPA_TOOLS",
    "CODE_ONLY_TOOLS",
    "SNAPSHOT_TOOLS",
    "build_agent_fn",
    "AgentResult",
]
