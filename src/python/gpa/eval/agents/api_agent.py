"""OpenGPA REST-API agent backend.

Contains the canonical implementation previously in ``gpa.eval.llm_agent``.
``gpa.eval.llm_agent`` is now a thin compatibility shim that re-exports
every public symbol from this module.
"""
from __future__ import annotations

import time
import json
import os
import requests
from anthropic import Anthropic

from gpa.eval.agents.base import AgentBackend, AgentResult


class GpaToolExecutor:
    """Executes OpenGPA tool calls by proxying to the REST API."""

    def __init__(self, base_url: str, token: str, frame_id: int):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.frame_id = frame_id
        self.headers = {"Authorization": f"Bearer {token}"}

    def execute(self, tool_name: str, tool_input: dict) -> str:
        """Execute an OpenGPA tool and return the result as a string."""
        if tool_name == "query_frame":
            return self._query_frame(tool_input)
        elif tool_name == "inspect_drawcall":
            return self._inspect_drawcall(tool_input)
        elif tool_name == "query_pixel":
            return self._query_pixel(tool_input)
        elif tool_name == "query_scene":
            return self._query_scene(tool_input)
        elif tool_name == "compare_frames":
            return self._compare_frames(tool_input)
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def _query_frame(self, input: dict) -> str:
        query_type = input.get("query_type", "overview")
        if query_type == "overview":
            r = requests.get(
                f"{self.base_url}/api/v1/frames/{self.frame_id}/overview",
                headers=self.headers,
            )
        elif query_type == "drawcalls":
            limit = input.get("limit", 50)
            offset = input.get("offset", 0)
            r = requests.get(
                f"{self.base_url}/api/v1/frames/{self.frame_id}/drawcalls",
                params={"limit": limit, "offset": offset},
                headers=self.headers,
            )
        else:
            return json.dumps({"error": f"Unknown query_type: {query_type}"})
        return r.text

    def _inspect_drawcall(self, input: dict) -> str:
        dc_id = input.get("drawcall_id", 0)
        r = requests.get(
            f"{self.base_url}/api/v1/frames/{self.frame_id}/drawcalls/{dc_id}",
            headers=self.headers,
        )
        return r.text

    def _query_pixel(self, input: dict) -> str:
        x = input.get("x", 0)
        y = input.get("y", 0)
        r = requests.get(
            f"{self.base_url}/api/v1/frames/{self.frame_id}/pixel/{x}/{y}",
            headers=self.headers,
        )
        return r.text

    def _query_scene(self, input: dict) -> str:
        query_type = input.get("query_type", "camera")
        if query_type == "camera":
            r = requests.get(
                f"{self.base_url}/api/v1/frames/{self.frame_id}/scene/camera",
                headers=self.headers,
            )
        elif query_type == "objects":
            r = requests.get(
                f"{self.base_url}/api/v1/frames/{self.frame_id}/scene/objects",
                headers=self.headers,
            )
        else:
            r = requests.get(
                f"{self.base_url}/api/v1/frames/{self.frame_id}/scene",
                headers=self.headers,
            )
        return r.text

    def _compare_frames(self, input: dict) -> str:
        frame_a = input.get("frame_id_a", self.frame_id)
        frame_b = input.get("frame_id_b", self.frame_id)
        depth = input.get("depth", "summary")
        r = requests.get(
            f"{self.base_url}/api/v1/diff/{frame_a}/{frame_b}",
            params={"depth": depth},
            headers=self.headers,
        )
        return r.text


# ---------------------------------------------------------------------------
# Tool definitions for Claude API
# ---------------------------------------------------------------------------

GPA_TOOLS = [
    {
        "name": "query_frame",
        "description": (
            "Get frame overview or draw call list. "
            "Use 'overview' to see draw call count and frame summary. "
            "Use 'drawcalls' to list all draw calls with their details."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "enum": ["overview", "drawcalls"],
                    "description": "What to query about the frame",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max draw calls to return (for drawcalls query)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Offset for pagination",
                },
            },
            "required": ["query_type"],
        },
    },
    {
        "name": "inspect_drawcall",
        "description": (
            "Deep dive into a specific draw call. Shows shader program, "
            "uniform/parameter values, bound textures, pipeline state "
            "(depth test, blend, cull, viewport, scissor), and vertex data info."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "drawcall_id": {
                    "type": "integer",
                    "description": "The draw call ID to inspect",
                },
                "include": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["shader", "textures", "pipeline", "vertices"],
                    },
                    "description": "What aspects to include",
                },
            },
            "required": ["drawcall_id"],
        },
    },
    {
        "name": "query_pixel",
        "description": (
            "Get the color (RGBA), depth, and stencil value at a specific "
            "pixel coordinate in the framebuffer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate"},
                "y": {"type": "integer", "description": "Y coordinate"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "query_scene",
        "description": "Get scene info (requires framework metadata plugin).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "enum": ["camera", "objects", "full"],
                    "description": "What scene info to query",
                },
            },
            "required": ["query_type"],
        },
    },
    {
        "name": "compare_frames",
        "description": (
            "Compare two captured frames. Shows differences in draw calls, "
            "pipeline state, and pixel output."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "frame_id_a": {"type": "integer"},
                "frame_id_b": {"type": "integer"},
                "depth": {
                    "type": "string",
                    "enum": ["summary", "drawcalls", "pixels"],
                    "description": "Detail level of comparison",
                },
            },
            "required": ["frame_id_a", "frame_id_b"],
        },
    },
    {
        "name": "read_source_file",
        "description": "Read the source code of the buggy application. This is the ONLY way to see the code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the source file",
                },
            },
            "required": ["file_path"],
        },
    },
]

# For code-only mode, only the source reader is available
CODE_ONLY_TOOLS = [GPA_TOOLS[-1]]  # just read_source_file

# Snapshot tool specs — added dynamically when scenario has snapshot refs.
# These tools operate over the FULL snapshot tree.  The scenario's
# ``relevant_files`` hint list is just a starting point; the agent is
# free to walk, read, and grep anywhere inside the snapshot.
SNAPSHOT_TOOLS = [
    {
        "name": "read_upstream",
        "description": (
            "Read a file from the upstream repository snapshot. "
            "Use this to inspect the original upstream source code that the "
            "scenario is based on. The path is relative to the repository root. "
            "You can read ANY file in the snapshot, not just the hint list."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file, relative to the upstream repo root",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_upstream_files",
        "description": (
            "List files and directories under a subdirectory of the upstream "
            "repository snapshot. Directories are shown with a trailing '/'. "
            "Use an empty string for the repo root. Walk anywhere in the tree."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subdir": {
                    "type": "string",
                    "description": "Subdirectory path relative to repo root, or empty string for root",
                },
            },
            "required": [],
        },
    },
    {
        "name": "grep_upstream",
        "description": (
            "Regex-search the entire upstream snapshot. Returns matches as "
            "path:line:text. Use this to locate symbols or API usage across "
            "the full tree."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for",
                },
                "subdir": {
                    "type": "string",
                    "description": "Optional subdirectory to restrict the search (defaults to repo root)",
                },
                "glob": {
                    "type": "string",
                    "description": "Optional filename glob, e.g. '*.ts'",
                },
                "max_matches": {
                    "type": "integer",
                    "description": "Maximum number of matches to return (default 200)",
                },
            },
            "required": ["pattern"],
        },
    },
]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ApiAgent(AgentBackend):
    """Runs a Claude agent against an eval scenario via the Anthropic REST API.

    Formerly named ``EvalAgent`` (in ``gpa.eval.llm_agent``).  The old name
    is still exported by the compatibility shim.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: str = None,
        max_turns: int = 20,
    ):
        self.client = Anthropic(api_key=api_key) if api_key else Anthropic()
        self.model = model
        self.max_turns = max_turns

    # ------------------------------------------------------------------
    # AgentBackend interface
    # ------------------------------------------------------------------

    def run(self, scenario, mode: str, tools: dict) -> AgentResult:
        """Implement AgentBackend.run by dispatching to run_with_gla / run_code_only.

        Adapts the harness ``tools`` dict (same shape as build_agent_fn uses)
        to the keyword-arg style expected by the underlying methods.
        """
        source_code = tools["read_source"]()
        description = getattr(scenario, "description", "") or getattr(
            scenario, "bug_description", ""
        )
        source_path = getattr(scenario, "source_path", "")

        extra_tools: dict = {}
        if "read_upstream" in tools:
            _ru = tools["read_upstream"]
            extra_tools["read_upstream"] = lambda inp, _f=_ru: _f(inp.get("path", ""))
        if "list_upstream_files" in tools:
            _luf = tools["list_upstream_files"]
            extra_tools["list_upstream_files"] = lambda inp, _f=_luf: _f(inp.get("subdir", ""))
        if "grep_upstream" in tools:
            _gu = tools["grep_upstream"]
            def _grep_adapter(inp, _f=_gu):
                return _f(
                    inp.get("pattern", ""),
                    subdir=inp.get("subdir", ""),
                    glob=inp.get("glob", ""),
                    max_matches=int(inp.get("max_matches", 200) or 200),
                )
            extra_tools["grep_upstream"] = _grep_adapter

        system_prompt = tools.get("system_prompt")

        if mode == "with_gla":
            frame_id = tools["run_with_capture"]()
            if frame_id is None:
                # Live capture unavailable; agent has no live frame to query.
                # Fall through to code_only so the executor is never built
                # against a sentinel id (would 404 every call).
                return self.run_code_only(
                    scenario_description=description,
                    source_code=source_code,
                    source_path=source_path,
                    extra_tools=extra_tools or None,
                    system_prompt=system_prompt,
                )
            executor = GpaToolExecutor(
                base_url=os.environ.get("GPA_BASE_URL", "http://127.0.0.1:18080"),
                token=os.environ.get("GPA_TOKEN", ""),
                frame_id=frame_id,
            )
            return self.run_with_gla(
                scenario_description=description,
                source_code=source_code,
                source_path=source_path,
                tool_executor=executor,
                extra_tools=extra_tools or None,
                system_prompt=system_prompt,
            )
        else:
            return self.run_code_only(
                scenario_description=description,
                source_code=source_code,
                source_path=source_path,
                extra_tools=extra_tools or None,
                system_prompt=system_prompt,
            )

    # ------------------------------------------------------------------
    # Existing methods (kept for backward-compat with direct callers)
    # ------------------------------------------------------------------

    def run_with_gla(
        self,
        scenario_description: str,
        source_code: str,
        source_path: str,
        tool_executor: GpaToolExecutor,
        extra_tools: dict | None = None,
        system_prompt: str | None = None,
    ) -> AgentResult:
        """Run the agent WITH OpenGPA tools available.

        Args:
            extra_tools: optional dict of name -> callable for supplementary
                tools (e.g. snapshot tools). Each callable receives the
                tool_input dict and returns a string result.
            system_prompt: optional override — when provided, the agent
                uses this verbatim as the system prompt instead of the
                built-in diagnosis prompt.  Used by the Phase 4
                maintainer-framing harness to drive bug_class-specific
                prompts.
        """
        # Build the tool spec list: always include GPA_TOOLS, then append
        # specs for any extra_tools that are present.
        tool_specs = list(GPA_TOOLS)
        if extra_tools:
            tool_specs += [s for s in SNAPSHOT_TOOLS if s["name"] in extra_tools]
        return self._run(
            scenario_description=scenario_description,
            source_code=source_code,
            source_path=source_path,
            tool_specs=tool_specs,
            tool_executor=tool_executor,
            extra_tools=extra_tools or {},
            mode="with_gla",
            system_prompt_override=system_prompt,
        )

    def run_code_only(
        self,
        scenario_description: str,
        source_code: str,
        source_path: str,
        extra_tools: dict | None = None,
        system_prompt: str | None = None,
    ) -> AgentResult:
        """Run the agent with ONLY source code access.

        Args:
            extra_tools: optional dict of name -> callable for supplementary
                tools (e.g. snapshot tools). Each callable receives the
                tool_input dict and returns a string result.
            system_prompt: optional override — when provided, the agent
                uses this verbatim as the system prompt instead of the
                built-in diagnosis prompt.  Used by the Phase 4
                maintainer-framing harness to drive bug_class-specific
                prompts.
        """
        tool_specs = list(CODE_ONLY_TOOLS)
        if extra_tools:
            tool_specs += [s for s in SNAPSHOT_TOOLS if s["name"] in extra_tools]
        return self._run(
            scenario_description=scenario_description,
            source_code=source_code,
            source_path=source_path,
            tool_specs=tool_specs,
            tool_executor=None,
            extra_tools=extra_tools or {},
            mode="code_only",
            system_prompt_override=system_prompt,
        )

    def _run(
        self,
        scenario_description: str,
        source_code: str,
        source_path: str,
        tool_specs: list,
        tool_executor,
        extra_tools: dict,
        mode: str,
        system_prompt_override: str | None = None,
    ) -> AgentResult:
        """Core agent loop with tool use.

        Args:
            tool_specs: Anthropic tool-use spec dicts sent to the API.
            tool_executor: GpaToolExecutor for OpenGPA REST API tools (or None).
            extra_tools: dict of tool_name -> callable(tool_input: dict) -> str,
                for tools dispatched locally (e.g. snapshot tools). The callable
                receives the raw tool_input dict.
            system_prompt_override: if set, the agent uses this exact
                string as its system prompt (Phase 4 maintainer prompt).
                Otherwise ``_build_system_prompt`` generates the default.
        """

        if system_prompt_override:
            system_prompt = system_prompt_override
        else:
            system_prompt = self._build_system_prompt(mode, extra_tools=extra_tools)
        user_message = self._build_user_message(scenario_description, source_path)

        messages = [{"role": "user", "content": user_message}]

        total_input_tokens = 0
        total_output_tokens = 0
        tool_call_count = 0
        tool_sequence = []
        num_turns = 0
        start_time = time.time()
        conversation = []
        assistant_content = []

        for _turn in range(self.max_turns):
            num_turns += 1

            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                tools=tool_specs,
                messages=messages,
            )

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            # Collect assistant message
            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})
            conversation.append(
                {
                    "role": "assistant",
                    "content": [b.model_dump() for b in assistant_content],
                }
            )

            # Done when model stops asking for tools
            if response.stop_reason == "end_turn":
                break

            # Handle tool calls
            tool_results = []
            for block in assistant_content:
                if block.type == "tool_use":
                    tool_call_count += 1
                    tool_name = block.name
                    tool_input = block.input
                    tool_sequence.append(tool_name)

                    if tool_name == "read_source_file":
                        result = source_code
                    elif tool_name in extra_tools:
                        # Dispatch locally via the callable
                        try:
                            result = extra_tools[tool_name](tool_input)
                        except Exception as exc:
                            result = f"ERROR: tool {tool_name!r} raised: {exc}"
                    elif tool_executor is not None:
                        result = tool_executor.execute(tool_name, tool_input)
                    else:
                        result = json.dumps(
                            {"error": "Tool not available in code-only mode"}
                        )

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )

            if tool_results:
                messages.append({"role": "user", "content": tool_results})
                conversation.append({"role": "user", "content": tool_results})

        elapsed = time.time() - start_time

        # Extract final text diagnosis from last assistant message
        diagnosis = ""
        for block in assistant_content:
            if hasattr(block, "text"):
                diagnosis += block.text

        # Analyze strategy
        pixel_queries = tool_sequence.count("query_pixel")
        state_queries = tool_sequence.count("inspect_drawcall") + tool_sequence.count("query_scene")
        # Did agent query pixels before ever inspecting structured state?
        fb_first = False
        for t in tool_sequence:
            if t == "query_pixel":
                fb_first = True
                break
            if t in ("inspect_drawcall", "query_scene"):
                break

        return AgentResult(
            diagnosis=diagnosis,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            total_tokens=total_input_tokens + total_output_tokens,
            tool_calls=tool_call_count,
            num_turns=num_turns,
            time_seconds=elapsed,
            conversation=conversation,
            tool_sequence=tool_sequence,
            pixel_queries=pixel_queries,
            state_queries=state_queries,
            framebuffer_first=fb_first,
        )

    def _build_system_prompt(self, mode: str, extra_tools: dict | None = None) -> str:
        base = (
            "You are debugging an OpenGL application that has a rendering bug. "
            "Your goal is to identify the root cause and suggest a fix.\n\n"
        )
        snapshot_lines = ""
        if extra_tools and "read_upstream" in extra_tools:
            snapshot_lines = (
                "- read_upstream: Read a file from the upstream repository snapshot\n"
                "- list_upstream_files: List files in a directory of the upstream repo\n"
            )
        if mode == "with_gla":
            return base + (
                "You have access to these tools:\n"
                "- read_source_file: Read the application source code\n"
                "- query_frame: Get frame overview and draw call list\n"
                "- inspect_drawcall: Inspect a draw call's shader params, "
                "textures, pipeline state, or vertex data\n"
                "- query_pixel: Get color/depth at a pixel coordinate\n"
                "- query_scene: Get scene info (requires framework metadata plugin)\n"
                "- compare_frames: Diff two frames\n"
                + snapshot_lines
                + "\nThese tools are provided by OpenGPA (Open Graphics Profiler for Agents).\n"
                "Use whatever approach you think is best.\n\n"
                "End your response with:\n"
                "DIAGNOSIS: <one-sentence root cause>\n"
                "FIX: <specific code change needed>"
            )
        else:
            return base + (
                "You have access to these tools:\n"
                "- read_source_file: Read the application source code\n"
                + snapshot_lines
                + "\nUse whatever approach you think is best.\n\n"
                "End your response with:\n"
                "DIAGNOSIS: <one-sentence root cause>\n"
                "FIX: <specific code change needed>"
            )

    def _build_user_message(self, scenario_description: str, source_path: str) -> str:
        return (
            f"Debug this OpenGL application. The rendering output is incorrect.\n\n"
            f"Problem description:\n{scenario_description}\n\n"
            f"Source file: {source_path}\n\n"
            f"Please investigate and identify the root cause of the rendering bug. "
            f"End with DIAGNOSIS and FIX."
        )


# ---------------------------------------------------------------------------
# Factory: default agent_fn for EvalHarness
# ---------------------------------------------------------------------------


def build_agent_fn(
    model: str = "claude-sonnet-4-20250514",
    max_turns: int = 20,
    api_key: str = None,
):
    """Return the default agent_fn used by EvalHarness.

    The returned callable has signature
        (scenario, mode, tools) ->
            (diagnosis_text, input_tokens, output_tokens,
             tool_calls, num_turns, time_seconds)
    matching :class:`gpa.eval.harness.AgentFn`.

    In "with_gla" mode the agent is given the full OpenGPA tool set plus the
    source reader and is driven by a `GpaToolExecutor` pointed at the
    captured frame. In "code_only" mode the agent only has `read_source_file`.

    When the scenario carries Phase-4 maintainer-framing metadata
    (``tools["bug_class"]`` set to ``"framework-internal"``,
    ``"consumer-misuse"``, or ``"user-config"``), the agent uses the
    class-specific prompt in ``tools["system_prompt"]`` and the harness
    can post-score via :func:`gpa.eval.scorer.score_maintainer_patch`
    (the scorer call itself is the harness's responsibility; this
    function just ensures the agent produces the JSON-tail output).
    """

    def agent_fn(scenario, mode: str, tools: dict):
        agent = ApiAgent(model=model, api_key=api_key, max_turns=max_turns)

        source_code = tools["read_source"]()
        description = getattr(scenario, "description", "") or getattr(
            scenario, "bug_description", ""
        )
        source_path = getattr(scenario, "source_path", "")

        # Build extra_tools dict for locally-dispatched tools (snapshot tools).
        # The harness passes callables keyed by tool name; the agent dispatches
        # them by calling callable(tool_input_dict). We adapt the harness
        # callables (which take keyword args) to accept a dict.
        extra_tools: dict = {}
        if "read_upstream" in tools:
            _ru = tools["read_upstream"]
            extra_tools["read_upstream"] = lambda inp, _f=_ru: _f(inp.get("path", ""))
        if "list_upstream_files" in tools:
            _luf = tools["list_upstream_files"]
            extra_tools["list_upstream_files"] = lambda inp, _f=_luf: _f(inp.get("subdir", ""))
        if "grep_upstream" in tools:
            _gu = tools["grep_upstream"]
            def _grep_adapter(inp, _f=_gu):
                return _f(
                    inp.get("pattern", ""),
                    subdir=inp.get("subdir", ""),
                    glob=inp.get("glob", ""),
                    max_matches=int(inp.get("max_matches", 200) or 200),
                )
            extra_tools["grep_upstream"] = _grep_adapter

        # Phase 4: pick up the harness-rendered system prompt if present.
        # None → agent falls back to its built-in diagnosis prompt.
        system_prompt = tools.get("system_prompt")

        if mode == "with_gla":
            frame_id = tools["run_with_capture"]()
            if frame_id is None:
                # Live capture unavailable — fall back to code_only.
                result = agent.run_code_only(
                    scenario_description=description,
                    source_code=source_code,
                    source_path=source_path,
                    extra_tools=extra_tools or None,
                    system_prompt=system_prompt,
                )
            else:
                executor = GpaToolExecutor(
                    base_url=os.environ.get("GPA_BASE_URL", "http://127.0.0.1:18080"),
                    token=os.environ.get("GPA_TOKEN", ""),
                    frame_id=frame_id,
                )
                result = agent.run_with_gla(
                    scenario_description=description,
                    source_code=source_code,
                    source_path=source_path,
                    tool_executor=executor,
                    extra_tools=extra_tools or None,
                    system_prompt=system_prompt,
                )
        else:
            result = agent.run_code_only(
                scenario_description=description,
                source_code=source_code,
                source_path=source_path,
                extra_tools=extra_tools or None,
                system_prompt=system_prompt,
            )

        return (
            result.diagnosis,
            result.input_tokens,
            result.output_tokens,
            result.tool_calls,
            result.num_turns,
            result.time_seconds,
        )

    return agent_fn
