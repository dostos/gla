"""Tests for FrameworkQueryEngine."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from gla.framework.metadata_store import MetadataStore
from gla.framework.query_engine import FrameworkQueryEngine
from gla.backends.base import DrawCallInfo, PixelResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store_with(frame_id: int, raw: dict) -> MetadataStore:
    store = MetadataStore()
    store.store(frame_id, raw)
    return store


def _make_provider(draw_calls=None, pixel=None):
    provider = MagicMock()
    provider.list_draw_calls.return_value = draw_calls or []
    provider.get_pixel.return_value = pixel
    return provider


# Typical metadata payload
METADATA_PAYLOAD = {
    "framework": "three.js",
    "objects": [
        {
            "name": "Player",
            "type": "Mesh",
            "parent": "Scene",
            "draw_call_ids": [1, 2],
            "transform": {"position": [0, 0, 0]},
            "visible": True,
            "properties": {},
        },
        {
            "name": "Enemy",
            "type": "Mesh",
            "parent": "Scene",
            "draw_call_ids": [3],
            "transform": {},
            "visible": True,
            "properties": {"hp": 100},
        },
        {
            "name": "HiddenObj",
            "type": "Light",
            "parent": "Scene",
            "draw_call_ids": [],
            "transform": {},
            "visible": False,
            "properties": {},
        },
    ],
    "materials": [
        {
            "name": "PlayerMat",
            "shader": "MeshStandardMaterial",
            "used_by": ["Player"],
            "properties": {"roughness": 0.5},
            "textures": {"albedo": "player_diffuse.png"},
        },
        {
            "name": "EnemyMat",
            "shader": "MeshPhongMaterial",
            "used_by": ["Enemy"],
            "properties": {},
            "textures": {},
        },
    ],
    "render_passes": [
        {"name": "GBuffer", "draw_call_range": [1, 2], "input": [], "output": "gbuffer_rt"},
        {"name": "Forward", "draw_call_range": [3, 3], "input": ["gbuffer_rt"], "output": "backbuffer"},
    ],
}


# ---------------------------------------------------------------------------
# list_objects
# ---------------------------------------------------------------------------

def test_list_objects_returns_all():
    store = _make_store_with(1, METADATA_PAYLOAD)
    engine = FrameworkQueryEngine(_make_provider(), store)
    objs = engine.list_objects(1)
    assert len(objs) == 3
    names = {o.name for o in objs}
    assert names == {"Player", "Enemy", "HiddenObj"}


def test_list_objects_includes_material_name():
    store = _make_store_with(1, METADATA_PAYLOAD)
    engine = FrameworkQueryEngine(_make_provider(), store)
    objs = engine.list_objects(1)
    player = next(o for o in objs if o.name == "Player")
    assert player.material == "PlayerMat"


def test_list_objects_no_material_is_none():
    store = _make_store_with(1, METADATA_PAYLOAD)
    engine = FrameworkQueryEngine(_make_provider(), store)
    objs = engine.list_objects(1)
    hidden = next(o for o in objs if o.name == "HiddenObj")
    assert hidden.material is None


def test_list_objects_no_metadata():
    store = MetadataStore()
    engine = FrameworkQueryEngine(_make_provider(), store)
    assert engine.list_objects(99) == []


def test_list_objects_preserves_fields():
    store = _make_store_with(1, METADATA_PAYLOAD)
    engine = FrameworkQueryEngine(_make_provider(), store)
    objs = engine.list_objects(1)
    enemy = next(o for o in objs if o.name == "Enemy")
    assert enemy.type == "Mesh"
    assert enemy.parent == "Scene"
    assert enemy.draw_call_ids == [3]
    assert enemy.visible is True
    assert enemy.properties == {"hp": 100}


# ---------------------------------------------------------------------------
# query_object
# ---------------------------------------------------------------------------

def test_query_object_found():
    store = _make_store_with(1, METADATA_PAYLOAD)
    engine = FrameworkQueryEngine(_make_provider(), store)
    obj = engine.query_object(1, "Player")
    assert obj is not None
    assert obj.name == "Player"
    assert obj.material == "PlayerMat"


def test_query_object_not_found():
    store = _make_store_with(1, METADATA_PAYLOAD)
    engine = FrameworkQueryEngine(_make_provider(), store)
    assert engine.query_object(1, "NonExistent") is None


def test_query_object_wrong_frame():
    store = _make_store_with(1, METADATA_PAYLOAD)
    engine = FrameworkQueryEngine(_make_provider(), store)
    assert engine.query_object(2, "Player") is None


# ---------------------------------------------------------------------------
# list_render_passes
# ---------------------------------------------------------------------------

def test_list_render_passes_from_metadata():
    store = _make_store_with(1, METADATA_PAYLOAD)
    engine = FrameworkQueryEngine(_make_provider(), store)
    passes = engine.list_render_passes(1)
    assert len(passes) == 2
    names = {p.name for p in passes}
    assert names == {"GBuffer", "Forward"}


def test_list_render_passes_draw_call_ids_from_range():
    store = _make_store_with(1, METADATA_PAYLOAD)
    engine = FrameworkQueryEngine(_make_provider(), store)
    passes = engine.list_render_passes(1)
    gbuffer = next(p for p in passes if p.name == "GBuffer")
    assert gbuffer.draw_call_ids == [1, 2]
    forward = next(p for p in passes if p.name == "Forward")
    assert forward.draw_call_ids == [3]


def test_list_render_passes_output_preserved():
    store = _make_store_with(1, METADATA_PAYLOAD)
    engine = FrameworkQueryEngine(_make_provider(), store)
    passes = engine.list_render_passes(1)
    gbuffer = next(p for p in passes if p.name == "GBuffer")
    assert gbuffer.output == "gbuffer_rt"
    assert gbuffer.input == []


def test_list_render_passes_fallback_to_debug_groups():
    """Without metadata, should build passes from debug group tree."""
    store = MetadataStore()  # no metadata
    dcs = [
        {"id": 1, "debug_group_path": "GBuffer/Mesh"},
        {"id": 2, "debug_group_path": "GBuffer/Mesh"},
        {"id": 3, "debug_group_path": "Shadow"},
        {"id": 4, "debug_group_path": ""},
    ]
    provider = _make_provider(draw_calls=dcs)
    engine = FrameworkQueryEngine(provider, store)
    passes = engine.list_render_passes(42)
    # Root-level children: GBuffer, Shadow (empty-path dc goes to root.draw_call_ids, not a pass)
    names = {p.name for p in passes}
    assert "GBuffer" in names
    assert "Shadow" in names


def test_list_render_passes_no_metadata_no_debug_groups():
    """Without metadata or debug groups, returns empty list."""
    store = MetadataStore()
    dcs = [{"id": 1, "debug_group_path": ""}]
    provider = _make_provider(draw_calls=dcs)
    engine = FrameworkQueryEngine(provider, store)
    passes = engine.list_render_passes(42)
    assert passes == []


# ---------------------------------------------------------------------------
# query_material
# ---------------------------------------------------------------------------

def test_query_material_found():
    store = _make_store_with(1, METADATA_PAYLOAD)
    engine = FrameworkQueryEngine(_make_provider(), store)
    mat = engine.query_material(1, "Player")
    assert mat is not None
    assert mat.name == "PlayerMat"
    assert mat.shader == "MeshStandardMaterial"
    assert mat.properties == {"roughness": 0.5}
    assert mat.textures == {"albedo": "player_diffuse.png"}
    assert mat.used_by == ["Player"]


def test_query_material_not_found():
    store = _make_store_with(1, METADATA_PAYLOAD)
    engine = FrameworkQueryEngine(_make_provider(), store)
    assert engine.query_material(1, "HiddenObj") is None


def test_query_material_no_metadata():
    store = MetadataStore()
    engine = FrameworkQueryEngine(_make_provider(), store)
    assert engine.query_material(1, "Player") is None


# ---------------------------------------------------------------------------
# explain_pixel
# ---------------------------------------------------------------------------

def _make_pixel():
    return PixelResult(r=128, g=64, b=200, a=255, depth=0.75, stencil=0)


def test_explain_pixel_no_pixel_data():
    store = MetadataStore()
    provider = _make_provider(pixel=None)
    engine = FrameworkQueryEngine(provider, store)
    assert engine.explain_pixel(1, 10, 20) is None


def test_explain_pixel_basic():
    store = MetadataStore()
    provider = _make_provider(pixel=_make_pixel())
    engine = FrameworkQueryEngine(provider, store)
    result = engine.explain_pixel(1, 10, 20)
    assert result is not None
    assert result.pixel["x"] == 10
    assert result.pixel["y"] == 20
    assert result.pixel["r"] == 128
    assert result.pixel["g"] == 64
    assert result.pixel["b"] == 200
    assert result.pixel["a"] == 255
    assert result.pixel["depth"] == 0.75
    assert "gl_capture" in result.data_sources


def test_explain_pixel_with_metadata_adds_source():
    store = _make_store_with(1, METADATA_PAYLOAD)
    provider = _make_provider(pixel=_make_pixel())
    engine = FrameworkQueryEngine(provider, store)
    result = engine.explain_pixel(1, 5, 5)
    assert "metadata" in result.data_sources


def test_explain_pixel_with_debug_markers_adds_source():
    store = MetadataStore()
    dcs = [{"id": 1, "debug_group_path": "GBuffer/Player"}]
    provider = _make_provider(draw_calls=dcs, pixel=_make_pixel())
    engine = FrameworkQueryEngine(provider, store)
    result = engine.explain_pixel(1, 5, 5)
    assert "debug_markers" in result.data_sources


def test_explain_pixel_no_debug_markers_if_no_paths():
    store = MetadataStore()
    dcs = [{"id": 1, "debug_group_path": ""}]
    provider = _make_provider(draw_calls=dcs, pixel=_make_pixel())
    engine = FrameworkQueryEngine(provider, store)
    result = engine.explain_pixel(1, 5, 5)
    assert "debug_markers" not in result.data_sources


def test_explain_pixel_draw_call_id_none_without_id_buffer():
    """Until we have an ID buffer, draw_call_id should be None."""
    store = _make_store_with(1, METADATA_PAYLOAD)
    provider = _make_provider(pixel=_make_pixel())
    engine = FrameworkQueryEngine(provider, store)
    result = engine.explain_pixel(1, 5, 5)
    assert result.draw_call_id is None
