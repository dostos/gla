"""FrameworkQueryEngine: high-level query interface over provider + metadata."""
from __future__ import annotations

from typing import List, Optional

from .types import MaterialInfo, ObjectInfo, PixelExplanation, RenderPassInfo
from .metadata_store import MetadataStore
from .debug_groups import build_debug_group_tree, DebugGroupNode
from . import correlation


class FrameworkQueryEngine:
    """Combines a FrameProvider with MetadataStore to answer framework queries."""

    def __init__(self, provider, metadata_store: MetadataStore) -> None:
        self.provider = provider
        self.metadata = metadata_store

    # ------------------------------------------------------------------
    # Objects
    # ------------------------------------------------------------------

    def list_objects(self, frame_id: int) -> List[ObjectInfo]:
        md = self.metadata.get(frame_id)
        if not md:
            return []
        result = []
        for obj in md.objects:
            mat = correlation.find_material_for_object(obj.name, md)
            result.append(ObjectInfo(
                name=obj.name,
                type=obj.type,
                parent=obj.parent,
                draw_call_ids=obj.draw_call_ids,
                material=mat.name if mat else None,
                transform=obj.transform,
                visible=obj.visible,
                properties=obj.properties,
            ))
        return result

    def query_object(self, frame_id: int, name: str) -> Optional[ObjectInfo]:
        objects = self.list_objects(frame_id)
        return next((o for o in objects if o.name == name), None)

    # ------------------------------------------------------------------
    # Render passes
    # ------------------------------------------------------------------

    def list_render_passes(self, frame_id: int) -> List[RenderPassInfo]:
        md = self.metadata.get(frame_id)
        result = []

        # From metadata
        if md:
            for rp in md.render_passes:
                r = rp.draw_call_range
                dc_ids = list(range(r[0], r[1] + 1)) if len(r) >= 2 else []
                result.append(RenderPassInfo(
                    name=rp.name,
                    draw_call_ids=dc_ids,
                    input=rp.input,
                    output=rp.output,
                ))

        # If no metadata, fall back to debug groups from draw calls
        if not result:
            dcs = self.provider.list_draw_calls(frame_id, limit=1000)
            tree = build_debug_group_tree(dcs)
            for child in tree.children:
                all_ids = self._collect_ids(child)
                result.append(RenderPassInfo(
                    name=child.name,
                    draw_call_ids=all_ids,
                    input=[],
                    output=None,
                ))

        return result

    # ------------------------------------------------------------------
    # Materials
    # ------------------------------------------------------------------

    def query_material(self, frame_id: int, object_name: str) -> Optional[MaterialInfo]:
        md = self.metadata.get(frame_id)
        if not md:
            return None
        mat = correlation.find_material_for_object(object_name, md)
        if not mat:
            return None
        return MaterialInfo(
            name=mat.name,
            shader=mat.shader,
            properties=mat.properties,
            textures=mat.textures,
            used_by=mat.used_by,
        )

    # ------------------------------------------------------------------
    # Pixel explanation
    # ------------------------------------------------------------------

    def explain_pixel(self, frame_id: int, x: int, y: int) -> Optional[PixelExplanation]:
        pixel = self.provider.get_pixel(frame_id, x, y)
        if not pixel:
            return None

        md = self.metadata.get(frame_id)
        data_sources = ["gl_capture"]

        # Gather draw calls to check for debug markers
        dcs = self.provider.list_draw_calls(frame_id, limit=1000)

        # For now, pixel→draw call attribution requires an ID buffer (TODO).
        # Return pixel data + available metadata context.
        obj_dict = None
        mat_dict = None
        render_pass = None
        dc_id = None
        debug_group = None
        params: list = []

        if md:
            data_sources.append("metadata")

        # If draw calls carry debug group paths, record that source
        for dc in dcs:
            dgp = (
                dc.get('debug_group_path', '')
                if isinstance(dc, dict)
                else getattr(dc, 'debug_group_path', '')
            )
            if dgp:
                if "debug_markers" not in data_sources:
                    data_sources.append("debug_markers")
                break

        return PixelExplanation(
            pixel={
                "x": x, "y": y,
                "r": pixel.r, "g": pixel.g, "b": pixel.b, "a": pixel.a,
                "depth": pixel.depth,
            },
            draw_call_id=dc_id,
            debug_group=debug_group,
            render_pass=render_pass,
            object=obj_dict,
            material=mat_dict,
            shader_params=params,
            data_sources=data_sources,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _collect_ids(self, node: DebugGroupNode) -> list:
        ids = list(node.draw_call_ids)
        for child in node.children:
            ids.extend(self._collect_ids(child))
        return ids
