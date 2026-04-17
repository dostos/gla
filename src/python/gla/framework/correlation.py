"""Correlation helpers: link draw calls → objects → materials → render passes."""
from __future__ import annotations

from typing import Optional

from .types import FrameworkMaterial, FrameworkObject


def find_object_for_drawcall(dc_id: int, metadata) -> Optional[FrameworkObject]:
    """Return the FrameworkObject that owns *dc_id*, or None."""
    if not metadata:
        return None
    for obj in metadata.objects:
        if dc_id in obj.draw_call_ids:
            return obj
    return None


def find_material_for_object(obj_name: str, metadata) -> Optional[FrameworkMaterial]:
    """Return the FrameworkMaterial used by the named object, or None."""
    if not metadata:
        return None
    for mat in metadata.materials:
        if obj_name in mat.used_by:
            return mat
    return None


def find_render_pass_for_drawcall(
    dc_id: int,
    metadata=None,
    debug_group_path: str = "",
) -> Optional[str]:
    """Find render pass name.

    Checks metadata render pass ranges first; falls back to the first
    segment of *debug_group_path* if no metadata match is found.
    """
    if metadata:
        for rp in metadata.render_passes:
            r = rp.draw_call_range
            if len(r) >= 2 and r[0] <= dc_id <= r[1]:
                return rp.name
    if debug_group_path:
        return debug_group_path.split('/')[0]
    return None
