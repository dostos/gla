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
    {
        "name": "gpa_report",
        "description": (
            "Run every diagnostic check on a captured frame. Returns a structured "
            "JSON report listing any findings (feedback loops, NaN uniforms, "
            "missing clears, empty capture, etc.). Prefer this ONE call over "
            "multiple inspect_drawcall queries — it covers 80% of diagnostic "
            "classes in a single query."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_id": {
                    "type": ["integer", "string"],
                    "description": "Frame ID or 'latest'",
                    "default": "latest",
                },
                "only": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Run only these checks (by name).",
                },
                "skip": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Skip these checks (by name).",
                },
            },
        },
    },
    {
        "name": "gpa_trace_value",
        "description": (
            "Reverse-lookup app-level fields whose value matches a captured "
            "uniform / texture ID / literal. Answers 'where in the framework "
            "state did this value come from?' Useful when a uniform looks "
            "wrong and you need to find the deeper field that set it. "
            "Requires the WebGL gpa-trace shim to have been enabled in the "
            "target page."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_id": {
                    "type": ["integer", "string"],
                    "description": "Frame ID or 'latest'",
                    "default": "latest",
                },
                "dc_id": {
                    "type": "integer",
                    "description": "Draw call ID (required for uniform lookup; optional for value)",
                },
                "field": {
                    "type": "string",
                    "description": (
                        "Uniform name to trace. Exactly one of 'field' or "
                        "'value' must be given."
                    ),
                },
                "value": {
                    "type": "string",
                    "description": (
                        "Literal value (number / string / bool) to reverse-look-up. "
                        "Exactly one of 'field' or 'value' must be given."
                    ),
                },
            },
        },
    },
    {
        "name": "gpa_check",
        "description": (
            "Drill down into a single diagnostic check with full detail. Use "
            "after `gpa_report` flags something. Available check names: "
            "empty-capture, feedback-loops, nan-uniforms, missing-clear."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "check_name": {
                    "type": "string",
                    "description": "Name of the check to drill into.",
                },
                "frame_id": {
                    "type": ["integer", "string"],
                    "description": "Frame ID or 'latest'",
                    "default": "latest",
                },
                "dc_id": {
                    "type": "integer",
                    "description": "Restrict to a single draw call (optional).",
                },
            },
            "required": ["check_name"],
        },
    },
    {
        "name": "gpa_check_config",
        "description": (
            "Cross-validate a captured frame against a hand-curated rule "
            "library (config-style 'is this idiomatic GL?' rules). Surfaces "
            "depth/blend/cull misconfigurations, missing clears, and other "
            "configuration smells with severity tags. Example: "
            '`{"frame_id": "latest", "severity": "warn"}` runs every '
            "default-enabled rule at warn-or-higher; "
            '`{"frame_id": 4, "rules": ["depth-test-disabled"]}` runs just '
            "that rule."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_id": {
                    "type": ["integer", "string"],
                    "description": "Frame ID or 'latest'",
                    "default": "latest",
                },
                "severity": {
                    "type": "string",
                    "enum": ["error", "warn", "info"],
                    "description": "Minimum severity to surface (default warn).",
                    "default": "warn",
                },
                "rules": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Restrict evaluation to these rule ids. Omit to run "
                        "every default-enabled rule."
                    ),
                },
            },
        },
    },
    {
        "name": "gpa_explain_draw",
        "description": (
            "Single-call explanation for one draw call: scene-node path, "
            "shader/material name, non-default uniforms, textures sampled, "
            "and the three pipeline-state values (depth-test, blend, cull) "
            "that most often explain visual outcomes. Replaces ~5 separate "
            "MCP queries (overview + drawcalls + drawcall + textures + "
            "annotations). Example: "
            '`{"frame_id": "latest", "draw_id": 12}` returns everything an '
            "agent needs to reason about draw 12 in one round trip; "
            '`{"frame_id": 4, "draw_id": 7, "fields": ["uniforms_set"]}` '
            "narrows the response to just the uniform table."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_id": {
                    "type": ["integer", "string"],
                    "description": "Frame ID or 'latest'",
                    "default": "latest",
                },
                "draw_id": {
                    "type": "integer",
                    "description": "Draw call ID within the frame.",
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional whitelist of top-level fields to keep "
                        "(scene_node_path, uniforms_set, textures_sampled, "
                        "relevant_state, ...). Omit to receive the full "
                        "payload."
                    ),
                },
            },
            "required": ["draw_id"],
        },
    },
    {
        "name": "gpa_diff_draws",
        "description": (
            "Compare two draw calls within the same frame and return only "
            "the differences (pipeline-state, uniforms, or textures, "
            "depending on `scope`). Powerful for 'why does draw N look "
            "different from draw N-1?' reasoning. Example: "
            '`{"frame_id": "latest", "a": 11, "b": 12}` defaults to the '
            "state scope and surfaces blend/depth/cull flips; "
            '`{"frame_id": 1, "a": 0, "b": 1, "scope": "uniforms"}` shows '
            "only changed decoded uniforms."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_id": {
                    "type": ["integer", "string"],
                    "description": "Frame ID or 'latest'",
                    "default": "latest",
                },
                "a": {"type": "integer", "description": "First draw call ID"},
                "b": {"type": "integer", "description": "Second draw call ID"},
                "scope": {
                    "type": "string",
                    "enum": ["state", "uniforms", "textures", "all"],
                    "description": "Diff scope (default state).",
                    "default": "state",
                },
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "gpa_scene_find",
        "description": (
            "Predicate-driven scene-graph search. Returns scene nodes that "
            "match every supplied predicate (CSV-AND form), each annotated "
            "with the draw-call ids whose debug_groups resolve to the node. "
            "Predicates: material:transparent, material:opaque, "
            "material-name:<substr>, name-contains:<substr>, type:<exact>, "
            "uniform-has-nan, texture:missing. Example: "
            '`{"frame_id": "latest", "predicate": "material:transparent"}` '
            "lists every transparent node; "
            '`{"frame_id": 4, "predicate": "uniform-has-nan,name-contains:helmet", "limit": 5}` '
            "narrows by two predicates."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_id": {
                    "type": ["integer", "string"],
                    "description": "Frame ID or 'latest'",
                    "default": "latest",
                },
                "predicate": {
                    "type": "string",
                    "description": (
                        "One predicate, or several joined with ',' "
                        "(e.g. 'material:transparent,name-contains:helmet')."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Max matches to return (default 10).",
                    "default": 10,
                },
            },
            "required": ["predicate"],
        },
    },
    {
        "name": "gpa_scene_explain",
        "description": (
            "Pixel→draw_call→scene_node trace. Given a pixel coordinate, "
            "answers 'which draw call produced this pixel and which scene "
            "node was that draw rendering?' using an approximate "
            "viewport/scissor hit-test. Reports `resolved: 'approximate'` "
            "(or `'miss'` when no draw covers the pixel). Example: "
            '`{"frame_id": "latest", "x": 400, "y": 300}` returns the '
            "draw_call_id, scene_node_path, material_name, and the "
            "uniform/texture inputs that produced the pixel."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_id": {
                    "type": ["integer", "string"],
                    "description": "Frame ID or 'latest'",
                    "default": "latest",
                },
                "x": {"type": "integer", "description": "Pixel X coordinate"},
                "y": {"type": "integer", "description": "Pixel Y coordinate"},
            },
            "required": ["x", "y"],
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


class _CheckClientAdapter:
    """Adapt :class:`APIClient` to the ``get_json(path)`` shape the
    ``gpa.cli.checks`` modules expect.

    The CLI checks use full REST paths like ``/api/v1/frames/1/overview``
    (and embed query strings inline). :class:`APIClient` expects paths
    relative to ``/api/v1`` and takes params as a dict. This adapter
    strips the ``/api/v1`` prefix and splits any trailing query string
    so the existing check code works unchanged.
    """

    def __init__(self, client: APIClient):
        self._client = client

    def get_json(self, path: str) -> Any:
        # Strip /api/v1 prefix if present (APIClient already roots at /api/v1).
        stripped = path
        if stripped.startswith("/api/v1"):
            stripped = stripped[len("/api/v1"):]
        # Split off any query string and rebuild as params dict for APIClient.
        query_params: Optional[Dict[str, Any]] = None
        if "?" in stripped:
            stripped, qs = stripped.split("?", 1)
            query_params = {}
            for part in qs.split("&"):
                if not part:
                    continue
                if "=" in part:
                    k, v = part.split("=", 1)
                else:
                    k, v = part, ""
                query_params[k] = v
        data = self._client.get(stripped, query_params)
        if isinstance(data, dict) and "error" in data and "detail" in data:
            # Match RestError surface so callers can distinguish HTTP failures.
            from gpa.cli.rest_client import RestError

            raise RestError(
                f"GET {path} → HTTP {data.get('error')}: {data.get('detail')!r}",
                status=int(data.get("error", 0) or 0),
            )
        return data


def _resolve_frame_id_for_checks(client: APIClient, frame_id: Any) -> Optional[int]:
    """Resolve 'latest'/None/str/int to an integer frame id, or None."""
    if frame_id is None or (isinstance(frame_id, str) and frame_id.lower() == "latest"):
        ov = client.get("/frames/current/overview")
        if not isinstance(ov, dict) or "error" in ov:
            return None
        try:
            return int(ov.get("frame_id", 0) or 0)
        except (TypeError, ValueError):
            return None
    try:
        return int(frame_id)
    except (TypeError, ValueError):
        return None


def _tool_gpa_report(client: APIClient, args: Dict[str, Any]) -> str:
    from gpa.cli import checks as checks_mod
    from gpa.cli.checks import CheckResult
    from gpa.cli.rest_client import RestError

    frame_id = _resolve_frame_id_for_checks(client, args.get("frame_id", "latest"))
    if frame_id is None:
        return json.dumps({"error": "no frames captured yet"}, indent=2)

    only = {s for s in (args.get("only") or []) if isinstance(s, str) and s.strip()}
    skip = {s for s in (args.get("skip") or []) if isinstance(s, str) and s.strip()}

    adapter = _CheckClientAdapter(client)
    results: List[CheckResult] = []
    for c in checks_mod.all_checks():
        if only and c.name not in only:
            continue
        if c.name in skip:
            continue
        try:
            results.append(c.run(adapter, frame_id=frame_id))
        except RestError as exc:
            results.append(CheckResult(name=c.name, status="error", error=str(exc)))
        except Exception as exc:  # noqa: BLE001
            results.append(CheckResult(name=c.name, status="error", error=str(exc)))

    warning_count = sum(1 for r in results if r.status != "ok")
    payload = {
        "frame": frame_id,
        "checks": [r.to_dict() for r in results],
        "warning_count": warning_count,
    }
    return json.dumps(payload, indent=2)


def _tool_gpa_check(client: APIClient, args: Dict[str, Any]) -> str:
    from gpa.cli import checks as checks_mod
    from gpa.cli.rest_client import RestError

    name = args.get("check_name")
    if not isinstance(name, str) or not name:
        return json.dumps(
            {"error": "check_name is required", "known": checks_mod.known_names()},
            indent=2,
        )

    check = checks_mod.get_check(name)
    if check is None:
        return json.dumps(
            {
                "error": f"unknown check: {name!r}",
                "known": checks_mod.known_names(),
            },
            indent=2,
        )

    frame_id = _resolve_frame_id_for_checks(client, args.get("frame_id", "latest"))
    if frame_id is None:
        return json.dumps({"error": "no frames captured yet"}, indent=2)

    dc_id = args.get("dc_id")
    if dc_id is not None:
        try:
            dc_id = int(dc_id)
        except (TypeError, ValueError):
            return json.dumps({"error": f"invalid dc_id: {dc_id!r}"}, indent=2)

    adapter = _CheckClientAdapter(client)
    try:
        result = check.run(adapter, frame_id=frame_id, dc_id=dc_id)
    except RestError as exc:
        return json.dumps(
            {"frame": frame_id, "check": name, "status": "error", "error": str(exc)},
            indent=2,
        )
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {"frame": frame_id, "check": name, "status": "error", "error": str(exc)},
            indent=2,
        )

    payload = {"frame": frame_id, "check": name, **result.to_dict()}
    return json.dumps(payload, indent=2)


def _tool_gpa_trace_value(client: APIClient, args: Dict[str, Any]) -> str:
    from urllib.parse import quote

    field = args.get("field")
    value = args.get("value")
    if (field is None) == (value is None):
        return json.dumps(
            {
                "error": (
                    "Exactly one of 'field' or 'value' must be provided"
                ),
            },
            indent=2,
        )

    frame_id = _resolve_frame_id_for_checks(client, args.get("frame_id", "latest"))
    if frame_id is None:
        return json.dumps({"error": "no frames captured yet"}, indent=2)

    dc_id = args.get("dc_id")
    if dc_id is not None:
        try:
            dc_id = int(dc_id)
        except (TypeError, ValueError):
            return json.dumps({"error": f"invalid dc_id: {dc_id!r}"}, indent=2)

    if field is not None:
        if dc_id is None:
            return json.dumps(
                {"error": "dc_id is required when tracing a uniform field"},
                indent=2,
            )
        path = (
            f"/frames/{frame_id}/drawcalls/{dc_id}"
            f"/trace/uniform/{quote(str(field), safe='')}"
        )
        data = client.get(path)
    else:
        if dc_id is None:
            path = (
                f"/frames/{frame_id}/trace/value"
                f"?query={quote(str(value), safe='')}"
            )
        else:
            path = (
                f"/frames/{frame_id}/drawcalls/{dc_id}"
                f"/trace/value?query={quote(str(value), safe='')}"
            )
        data = client.get(path)
    return json.dumps(data, indent=2)


def _tool_gpa_check_config(client: APIClient, args: Dict[str, Any]) -> str:
    """Run the rule-engine check-config endpoint and return its JSON payload.

    Mirrors the CLI command (and the REST route): resolves 'latest' alias,
    folds in optional severity / rule-id filters as query params.
    """
    frame_id = _resolve_frame_id_for_checks(client, args.get("frame_id", "latest"))
    if frame_id is None:
        return json.dumps({"error": "no frames captured yet"}, indent=2)

    severity = args.get("severity") or "warn"
    if severity not in {"error", "warn", "info"}:
        return json.dumps(
            {"error": f"invalid severity {severity!r}; must be error|warn|info"},
            indent=2,
        )

    params: Dict[str, Any] = {"severity": severity}

    rules = args.get("rules")
    if isinstance(rules, list) and rules:
        # APIClient builds the query as ``k=v`` pairs; FastAPI accepts
        # comma-separated values for a single ``rule`` query param.
        params["rule"] = ",".join(str(r) for r in rules if r)

    data = client.get(f"/frames/{frame_id}/check-config", params)
    return json.dumps(data, indent=2)


def _tool_gpa_explain_draw(client: APIClient, args: Dict[str, Any]) -> str:
    """Single-call explanation for one draw call.

    Optional ``fields`` filters the top-level payload to a whitelist so
    agents can request just the slice they care about.
    """
    frame_id = _resolve_frame_id_for_checks(client, args.get("frame_id", "latest"))
    if frame_id is None:
        return json.dumps({"error": "no frames captured yet"}, indent=2)

    draw_id = args.get("draw_id")
    try:
        draw_id = int(draw_id)
    except (TypeError, ValueError):
        return json.dumps({"error": f"invalid draw_id: {draw_id!r}"}, indent=2)

    data = client.get(f"/frames/{frame_id}/draws/{draw_id}/explain")

    fields = args.get("fields")
    if (
        isinstance(fields, list)
        and fields
        and isinstance(data, dict)
        and "error" not in data
    ):
        keep = {str(f) for f in fields if f}
        # Always preserve the identifying header so the response is
        # self-describing even after filtering.
        keep |= {"frame_id", "draw_call_id"}
        data = {k: v for k, v in data.items() if k in keep}

    return json.dumps(data, indent=2)


def _tool_gpa_diff_draws(client: APIClient, args: Dict[str, Any]) -> str:
    """Diff two draw calls within the same frame.

    ``a`` and ``b`` are both required.  ``scope`` controls which channels
    of difference are surfaced (state / uniforms / textures / all).
    """
    frame_id = _resolve_frame_id_for_checks(client, args.get("frame_id", "latest"))
    if frame_id is None:
        return json.dumps({"error": "no frames captured yet"}, indent=2)

    a = args.get("a")
    b = args.get("b")
    try:
        a = int(a)
        b = int(b)
    except (TypeError, ValueError):
        return json.dumps(
            {"error": f"diff_draws requires integer 'a' and 'b' (got {a!r}, {b!r})"},
            indent=2,
        )

    scope = args.get("scope") or "state"
    if scope not in {"state", "uniforms", "textures", "all"}:
        return json.dumps(
            {"error": f"invalid scope {scope!r}; must be state|uniforms|textures|all"},
            indent=2,
        )

    data = client.get(
        f"/frames/{frame_id}/draws/diff",
        {"a": a, "b": b, "scope": scope},
    )
    return json.dumps(data, indent=2)


def _tool_gpa_scene_find(client: APIClient, args: Dict[str, Any]) -> str:
    """Predicate-driven scene-graph search.

    The ``predicate`` argument is a single string holding one or more
    predicates joined with ``,`` (matching the CLI form). FastAPI's
    ``predicate=…`` query parameter is a list, so we pass it once and let
    the route's CSV splitter expand it.
    """
    frame_id = _resolve_frame_id_for_checks(client, args.get("frame_id", "latest"))
    if frame_id is None:
        return json.dumps({"error": "no frames captured yet"}, indent=2)

    predicate = args.get("predicate")
    if not isinstance(predicate, str) or not predicate.strip():
        return json.dumps(
            {"error": "scene_find requires a non-empty 'predicate' string"},
            indent=2,
        )

    limit = args.get("limit", 10)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return json.dumps({"error": f"invalid limit: {limit!r}"}, indent=2)
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    data = client.get(
        f"/frames/{frame_id}/scene/find",
        {"predicate": predicate, "limit": limit},
    )
    return json.dumps(data, indent=2)


def _tool_gpa_scene_explain(client: APIClient, args: Dict[str, Any]) -> str:
    """Pixel → draw → scene-node trace.

    Wraps the ``/frames/{id}/explain-pixel`` route. ``x``/``y`` are
    required and must both be non-negative.
    """
    frame_id = _resolve_frame_id_for_checks(client, args.get("frame_id", "latest"))
    if frame_id is None:
        return json.dumps({"error": "no frames captured yet"}, indent=2)

    x = args.get("x")
    y = args.get("y")
    try:
        x = int(x)
        y = int(y)
    except (TypeError, ValueError):
        return json.dumps(
            {"error": f"scene_explain requires integer 'x' and 'y' (got {x!r}, {y!r})"},
            indent=2,
        )
    if x < 0 or y < 0:
        return json.dumps(
            {"error": f"scene_explain requires non-negative x and y (got {x}, {y})"},
            indent=2,
        )

    data = client.get(
        f"/frames/{frame_id}/explain-pixel",
        {"x": x, "y": y},
    )
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
    "gpa_report": _tool_gpa_report,
    "gpa_check": _tool_gpa_check,
    "gpa_trace_value": _tool_gpa_trace_value,
    "gpa_check_config": _tool_gpa_check_config,
    "gpa_explain_draw": _tool_gpa_explain_draw,
    "gpa_diff_draws": _tool_gpa_diff_draws,
    "gpa_scene_find": _tool_gpa_scene_find,
    "gpa_scene_explain": _tool_gpa_scene_explain,
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
