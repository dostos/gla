"""Debug group tree builder.

Reconstructs a hierarchical tree of debug groups from per-draw-call
``debug_group_path`` strings (e.g. ``"GBuffer/Player Mesh"``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class DebugGroupNode:
    name: str
    children: List['DebugGroupNode'] = field(default_factory=list)
    draw_call_ids: List[int] = field(default_factory=list)


def build_debug_group_tree(draw_calls) -> DebugGroupNode:
    """Build a tree from draw calls with debug_group_path strings.

    Each draw call has debug_group_path like "GBuffer/Player Mesh".
    Returns root DebugGroupNode with hierarchy.

    draw_calls: list of objects with .id and .debug_group_path (or dicts)
    """
    root = DebugGroupNode(name="Frame")
    for dc in draw_calls:
        # Support both objects and dicts
        dc_id = dc.id if hasattr(dc, 'id') else dc.get('id', 0)
        path = (
            dc.get('debug_group_path', '')
            if isinstance(dc, dict)
            else getattr(dc, 'debug_group_path', '')
        )

        if not path:
            root.draw_call_ids.append(dc_id)
            continue

        parts = path.split('/')
        node = root
        for part in parts:
            child = next((c for c in node.children if c.name == part), None)
            if not child:
                child = DebugGroupNode(name=part)
                node.children.append(child)
            node = child
        node.draw_call_ids.append(dc_id)
    return root
