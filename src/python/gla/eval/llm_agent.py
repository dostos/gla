"""LLM agent for eval harness — invokes Claude API with/without GLA tools."""

import time
import json
import requests
from dataclasses import dataclass, field
from anthropic import Anthropic


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


class GlaToolExecutor:
    """Executes GLA tool calls by proxying to the REST API."""

    def __init__(self, base_url: str, token: str, frame_id: int):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.frame_id = frame_id
        self.headers = {"Authorization": f"Bearer {token}"}

    def execute(self, tool_name: str, tool_input: dict) -> str:
        """Execute a GLA tool and return the result as a string."""
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

GLA_TOOLS = [
    {
        "name": "query_frame",
        "description": (
            "Get frame overview, draw call list, or framebuffer data. "
            "Use 'overview' to see draw call count and framebuffer size. "
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
        "description": (
            "Get semantic scene information: camera parameters (position, FOV, "
            "near/far), scene objects with transforms and bounding boxes, or "
            "full scene reconstruction."
        ),
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
CODE_ONLY_TOOLS = [GLA_TOOLS[-1]]  # just read_source_file


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class EvalAgent:
    """Runs a Claude agent against an eval scenario."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: str = None,
        max_turns: int = 20,
    ):
        self.client = Anthropic(api_key=api_key) if api_key else Anthropic()
        self.model = model
        self.max_turns = max_turns

    def run_with_gla(
        self,
        scenario_description: str,
        source_code: str,
        source_path: str,
        tool_executor: GlaToolExecutor,
    ) -> AgentResult:
        """Run the agent WITH GLA tools available."""
        return self._run(
            scenario_description=scenario_description,
            source_code=source_code,
            source_path=source_path,
            tools=GLA_TOOLS,
            tool_executor=tool_executor,
            mode="with_gla",
        )

    def run_code_only(
        self,
        scenario_description: str,
        source_code: str,
        source_path: str,
    ) -> AgentResult:
        """Run the agent with ONLY source code access."""
        return self._run(
            scenario_description=scenario_description,
            source_code=source_code,
            source_path=source_path,
            tools=CODE_ONLY_TOOLS,
            tool_executor=None,
            mode="code_only",
        )

    def _run(
        self,
        scenario_description: str,
        source_code: str,
        source_path: str,
        tools: list,
        tool_executor,
        mode: str,
    ) -> AgentResult:
        """Core agent loop with tool use."""

        system_prompt = self._build_system_prompt(mode)
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
                tools=tools,
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

    def _build_system_prompt(self, mode: str) -> str:
        base = (
            "You are debugging an OpenGL application that has a rendering bug. "
            "Your goal is to identify the root cause and suggest a fix.\n\n"
        )
        if mode == "with_gla":
            return base + (
                "You have access to these tools:\n"
                "- read_source_file: Read the application source code\n"
                "- query_frame: Get frame overview and draw call list\n"
                "- inspect_drawcall: Inspect a draw call's shader params, "
                "textures, pipeline state, or vertex data\n"
                "- query_pixel: Get color/depth at a pixel coordinate\n"
                "- query_scene: Get camera and object information\n"
                "- compare_frames: Diff two frames\n\n"
                "Use whatever approach you think is best.\n\n"
                "End your response with:\n"
                "DIAGNOSIS: <one-sentence root cause>\n"
                "FIX: <specific code change needed>"
            )
        else:
            return base + (
                "You have access to these tools:\n"
                "- read_source_file: Read the application source code\n\n"
                "Use whatever approach you think is best.\n\n"
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
