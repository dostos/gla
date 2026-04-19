"""Minimal stdio-based MCP tool server for OpenGPA.

Implements the Model Context Protocol (MCP) tool-call protocol over stdin/stdout
using JSON-RPC 2.0.  The `mcp` Python SDK is not required.

Protocol summary
----------------
1. Client sends ``initialize`` — server replies with capabilities + tool list.
2. Client sends ``tools/call`` with ``{"name": "...", "arguments": {...}}`` —
   server replies with ``{"content": [{"type": "text", "text": "..."}]}``.
3. Client sends ``notifications/initialized`` — server ignores (no reply needed).

Run
---
::

    python -m gpa.mcp.server \\
        --base-url http://127.0.0.1:8080/api/v1 \\
        --token <bearer-token>
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error


# ---------------------------------------------------------------------------
# Tool definitions (declared to the MCP client on initialize)
# ---------------------------------------------------------------------------

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "query_frame",
        "description": (
            "Get a frame overview, draw call list, or framebuffer info. "
            "Use 'latest' as frame_id to get the most recent frame."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_id": {
                    "type": ["integer", "string"],
                    "description": "Frame ID or 'latest'",
                },
                "view": {
                    "type": "string",
                    "enum": ["overview", "drawcalls", "framebuffer"],
                    "description": "Which aspect of the frame to retrieve",
                    "default": "overview",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max draw calls to return (view=drawcalls only)",
                    "default": 50,
                },
                "offset": {
                    "type": "integer",
                    "description": "Draw call offset (view=drawcalls only)",
                    "default": 0,
                },
            },
            "required": ["frame_id"],
        },
    },
    {
        "name": "inspect_drawcall",
        "description": "Deep-dive into a single draw call: shader, textures, vertex info.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_id": {"type": "integer", "description": "Frame ID"},
                "dc_id": {"type": "integer", "description": "Draw call ID"},
                "aspect": {
                    "type": "string",
                    "enum": ["detail", "shader", "textures", "vertices", "feedback-loops", "nan-uniforms", "attachments"],
                    "description": "Which aspect to retrieve. 'feedback-loops' returns bound textures that are also the current FBO's color attachment (one-shot diagnosis for sample-from-render-target bugs). 'nan-uniforms' returns decoded uniforms with NaN/Inf components (one-shot diagnosis for NaN-in-output bugs).",
                    "default": "detail",
                },
            },
            "required": ["frame_id", "dc_id"],
        },
    },
    {
        "name": "query_pixel",
        "description": "Get RGBA colour and depth value at a specific pixel coordinate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_id": {"type": "integer", "description": "Frame ID"},
                "x": {"type": "integer", "description": "Pixel X coordinate"},
                "y": {"type": "integer", "description": "Pixel Y coordinate"},
            },
            "required": ["frame_id", "x", "y"],
        },
    },
    {
        "name": "query_scene",
        "description": "Query scene information from framework metadata. Requires a framework plugin to POST metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_id": {"type": "integer", "description": "Frame ID"},
                "aspect": {
                    "type": "string",
                    "enum": ["scene", "camera", "objects"],
                    "description": "Which scene aspect to retrieve",
                    "default": "scene",
                },
            },
            "required": ["frame_id"],
        },
    },
    {
        "name": "compare_frames",
        "description": "Compare two frames and return a diff at the requested depth.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_id_a": {"type": "integer", "description": "First frame ID"},
                "frame_id_b": {"type": "integer", "description": "Second frame ID"},
                "depth": {
                    "type": "string",
                    "enum": ["summary", "drawcalls", "pixels"],
                    "description": "Diff depth level",
                    "default": "summary",
                },
            },
            "required": ["frame_id_a", "frame_id_b"],
        },
    },
    {
        "name": "control_capture",
        "description": "Pause, resume, or step the OpenGPA capture engine.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["pause", "resume", "step", "status"],
                    "description": "Control action to perform",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of frames to step (action=step only)",
                    "default": 1,
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "query_object",
        "description": (
            "Get info about a named scene object — draw calls, material, transform, visibility"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_id": {"type": "integer"},
                "name": {"type": "string", "description": "Object name"},
            },
            "required": ["frame_id", "name"],
        },
    },
    {
        "name": "explain_pixel",
        "description": (
            "Full explanation of why a pixel has its color — traces through object, material, "
            "render pass, shader params"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_id": {"type": "integer"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            },
            "required": ["frame_id", "x", "y"],
        },
    },
    {
        "name": "list_render_passes",
        "description": (
            "Show the render pass structure — which passes exist, their draw call ranges, "
            "inputs and outputs"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_id": {"type": "integer"},
            },
            "required": ["frame_id"],
        },
    },
    {
        "name": "query_annotations",
        "description": (
            "Return free-form framework annotations for a frame (POSTed by a "
            "plugin as a JSON dict). Empty dict if nothing was posted. Useful "
            "for JS-layer state upstream of GL calls (e.g. mapbox tile cache, "
            "current zoom level)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_id": {"type": "integer", "description": "Frame ID"},
            },
            "required": ["frame_id"],
        },
    },
    {
        "name": "query_material",
        "description": (
            "Get material properties for a named object — shader, textures, PBR parameters"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_id": {"type": "integer"},
                "object_name": {"type": "string"},
            },
            "required": ["frame_id", "object_name"],
        },
    },
]


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

class APIClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self.base_url + path
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            return {"error": e.code, "detail": body}

    def post(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self.base_url + path
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"
        req = urllib.request.Request(
            url,
            data=b"",
            method="POST",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            return {"error": e.code, "detail": body}


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def _tool_query_frame(client: APIClient, args: Dict[str, Any]) -> str:
    frame_id = args.get("frame_id", "latest")
    view = args.get("view", "overview")

    if str(frame_id).lower() == "latest":
        if view == "overview":
            data = client.get("/frames/current/overview")
            return json.dumps(data, indent=2)
        # For other views we need an actual frame_id; fetch it first
        ov = client.get("/frames/current/overview")
        if "error" in ov:
            return json.dumps(ov, indent=2)
        frame_id = ov.get("frame_id", frame_id)

    if view == "overview":
        data = client.get(f"/frames/{frame_id}/overview")
    elif view == "drawcalls":
        limit = int(args.get("limit", 50))
        offset = int(args.get("offset", 0))
        data = client.get(f"/frames/{frame_id}/drawcalls",
                          {"limit": limit, "offset": offset})
    elif view == "framebuffer":
        data = client.get(f"/frames/{frame_id}/framebuffer")
    else:
        data = {"error": f"Unknown view '{view}'"}

    return json.dumps(data, indent=2)


def _tool_inspect_drawcall(client: APIClient, args: Dict[str, Any]) -> str:
    frame_id = int(args["frame_id"])
    dc_id = int(args["dc_id"])
    aspect = args.get("aspect", "detail")

    if aspect == "detail":
        data = client.get(f"/frames/{frame_id}/drawcalls/{dc_id}")
    elif aspect == "shader":
        data = client.get(f"/frames/{frame_id}/drawcalls/{dc_id}/shader")
    elif aspect == "textures":
        data = client.get(f"/frames/{frame_id}/drawcalls/{dc_id}/textures")
    elif aspect == "vertices":
        data = client.get(f"/frames/{frame_id}/drawcalls/{dc_id}/vertices")
    elif aspect == "feedback-loops":
        data = client.get(f"/frames/{frame_id}/drawcalls/{dc_id}/feedback-loops")
    elif aspect == "nan-uniforms":
        data = client.get(f"/frames/{frame_id}/drawcalls/{dc_id}/nan-uniforms")
    elif aspect == "attachments":
        data = client.get(f"/frames/{frame_id}/drawcalls/{dc_id}/attachments")
    else:
        data = {"error": f"Unknown aspect '{aspect}'"}

    return json.dumps(data, indent=2)


def _tool_query_pixel(client: APIClient, args: Dict[str, Any]) -> str:
    frame_id = int(args["frame_id"])
    x = int(args["x"])
    y = int(args["y"])
    data = client.get(f"/frames/{frame_id}/pixel", {"x": x, "y": y})
    return json.dumps(data, indent=2)


def _tool_query_scene(client: APIClient, args: Dict[str, Any]) -> str:
    frame_id = int(args["frame_id"])
    aspect = args.get("aspect", "scene")

    if aspect == "scene":
        data = client.get(f"/frames/{frame_id}/scene")
    elif aspect == "camera":
        data = client.get(f"/frames/{frame_id}/scene/camera")
    elif aspect == "objects":
        data = client.get(f"/frames/{frame_id}/scene/objects")
    else:
        data = {"error": f"Unknown aspect '{aspect}'"}

    return json.dumps(data, indent=2)


def _tool_compare_frames(client: APIClient, args: Dict[str, Any]) -> str:
    frame_id_a = int(args["frame_id_a"])
    frame_id_b = int(args["frame_id_b"])
    depth = str(args.get("depth", "summary"))
    data = client.get(f"/diff/{frame_id_a}/{frame_id_b}", {"depth": depth})
    return json.dumps(data, indent=2)


def _tool_control_capture(client: APIClient, args: Dict[str, Any]) -> str:
    action = args.get("action", "status")

    if action == "status":
        data = client.get("/control/status")
    elif action == "pause":
        data = client.post("/control/pause")
    elif action == "resume":
        data = client.post("/control/resume")
    elif action == "step":
        count = int(args.get("count", 1))
        data = client.post("/control/step", {"count": count})
    else:
        data = {"error": f"Unknown action '{action}'"}

    return json.dumps(data, indent=2)


def _tool_query_object(client: APIClient, args: Dict[str, Any]) -> str:
    frame_id = int(args["frame_id"])
    name = str(args["name"])
    data = client.get(f"/frames/{frame_id}/objects/{name}")
    return json.dumps(data, indent=2)


def _tool_explain_pixel(client: APIClient, args: Dict[str, Any]) -> str:
    frame_id = int(args["frame_id"])
    x = int(args["x"])
    y = int(args["y"])
    data = client.get(f"/frames/{frame_id}/explain/{x}/{y}")
    return json.dumps(data, indent=2)


def _tool_list_render_passes(client: APIClient, args: Dict[str, Any]) -> str:
    frame_id = int(args["frame_id"])
    data = client.get(f"/frames/{frame_id}/passes")
    return json.dumps(data, indent=2)


def _tool_query_annotations(client: APIClient, args: Dict[str, Any]) -> str:
    frame_id = int(args["frame_id"])
    data = client.get(f"/frames/{frame_id}/annotations")
    return json.dumps(data, indent=2)


def _tool_query_material(client: APIClient, args: Dict[str, Any]) -> str:
    frame_id = int(args["frame_id"])
    object_name = str(args["object_name"])
    data = client.get(f"/frames/{frame_id}/objects/{object_name}")
    # The material name is in the object info; fetch it and surface the material field
    if "error" not in data:
        mat_name = data.get("material")
        if mat_name:
            mat_data = client.get(f"/frames/{frame_id}/objects/{object_name}")
            return json.dumps({"object": object_name, "material": mat_name, "detail": mat_data}, indent=2)
    return json.dumps(data, indent=2)


_DISPATCH = {
    "query_frame": _tool_query_frame,
    "inspect_drawcall": _tool_inspect_drawcall,
    "query_pixel": _tool_query_pixel,
    "query_scene": _tool_query_scene,
    "compare_frames": _tool_compare_frames,
    "control_capture": _tool_control_capture,
    "query_object": _tool_query_object,
    "explain_pixel": _tool_explain_pixel,
    "list_render_passes": _tool_list_render_passes,
    "query_material": _tool_query_material,
    "query_annotations": _tool_query_annotations,
}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 helpers
# ---------------------------------------------------------------------------

def _response(req_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error_response(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _write(obj: Any) -> None:
    line = json.dumps(obj)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Main server loop
# ---------------------------------------------------------------------------

def run(base_url: str, token: str) -> None:
    client = APIClient(base_url, token)

    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        try:
            msg = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            _write(_error_response(None, -32700, f"Parse error: {exc}"))
            continue

        req_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {})

        # MCP initialize — return protocol version + tool list
        if method == "initialize":
            _write(_response(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "opengpa-mcp", "version": "0.1.0"},
            }))
            continue

        # notifications/initialized — no reply
        if method == "notifications/initialized":
            continue

        # tools/list — enumerate tools
        if method == "tools/list":
            _write(_response(req_id, {"tools": TOOLS}))
            continue

        # tools/call — dispatch
        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            handler = _DISPATCH.get(tool_name)
            if handler is None:
                _write(_error_response(req_id, -32601, f"Unknown tool: {tool_name}"))
                continue
            try:
                text = handler(client, arguments)
                _write(_response(req_id, {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                }))
            except Exception as exc:  # noqa: BLE001
                _write(_response(req_id, {
                    "content": [{"type": "text", "text": f"Tool error: {exc}"}],
                    "isError": True,
                }))
            continue

        # Unknown method
        _write(_error_response(req_id, -32601, f"Method not found: {method}"))


def main() -> None:
    import os

    parser = argparse.ArgumentParser(description="OpenGPA MCP stdio server")
    parser.add_argument(
        "--base-url",
        default=None,
        help="OpenGPA REST API base URL (default: GPA_BASE_URL env or http://127.0.0.1:8080/api/v1)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Bearer token for the OpenGPA REST API (default: GPA_TOKEN env)",
    )
    args = parser.parse_args()

    # Env vars take precedence over built-in defaults; CLI args override env vars.
    base_url = (
        args.base_url
        or os.environ.get("GPA_BASE_URL", "http://127.0.0.1:8080/api/v1")
    )
    # GPA_BASE_URL may point at the server root; ensure it ends with /api/v1
    if not base_url.endswith("/api/v1"):
        base_url = base_url.rstrip("/") + "/api/v1"

    token = args.token or os.environ.get("GPA_TOKEN", "")

    run(base_url=base_url, token=token)


if __name__ == "__main__":
    main()
