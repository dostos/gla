"""Tests for gla.framework.metadata_store.MetadataStore."""
import pytest

from gla.framework.metadata_store import MetadataStore
from gla.framework.types import FrameMetadata, FrameworkMaterial, FrameworkObject, FrameworkRenderPass


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

FULL_PAYLOAD = {
    "framework": "three.js",
    "version": "r155",
    "objects": [
        {
            "name": "Mesh1",
            "type": "Mesh",
            "parent": "Scene",
            "draw_call_ids": [0, 1],
            "transform": {"position": [0, 0, 0]},
            "visible": True,
            "properties": {"castShadow": True},
        }
    ],
    "materials": [
        {
            "name": "Mat1",
            "shader": "MeshStandardMaterial",
            "used_by": ["Mesh1"],
            "properties": {"metalness": 0.5},
            "textures": {"map": "tex_diffuse"},
        }
    ],
    "render_passes": [
        {
            "name": "ShadowPass",
            "draw_call_range": [0, 10],
            "output": "shadow_map",
            "input": [],
        }
    ],
}


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_store_and_get():
    store = MetadataStore()
    store.store(1, FULL_PAYLOAD)
    result = store.get(1)
    assert result is not None
    assert isinstance(result, FrameMetadata)
    assert result.framework == "three.js"
    assert result.version == "r155"


def test_not_found_returns_none():
    store = MetadataStore()
    assert store.get(42) is None
    assert store.has(42) is False


def test_capacity_eviction():
    store = MetadataStore(capacity=3)
    store.store(1, {"framework": "a"})
    store.store(2, {"framework": "b"})
    store.store(3, {"framework": "c"})
    # All three should be present
    assert store.has(1) and store.has(2) and store.has(3)
    # Adding a 4th evicts the oldest (frame 1)
    store.store(4, {"framework": "d"})
    assert not store.has(1)
    assert store.has(2) and store.has(3) and store.has(4)


def test_parse_objects():
    store = MetadataStore()
    store.store(1, FULL_PAYLOAD)
    meta = store.get(1)
    assert len(meta.objects) == 1
    obj = meta.objects[0]
    assert isinstance(obj, FrameworkObject)
    assert obj.name == "Mesh1"
    assert obj.type == "Mesh"
    assert obj.parent == "Scene"
    assert obj.draw_call_ids == [0, 1]
    assert obj.transform == {"position": [0, 0, 0]}
    assert obj.visible is True
    assert obj.properties == {"castShadow": True}


def test_parse_materials():
    store = MetadataStore()
    store.store(1, FULL_PAYLOAD)
    meta = store.get(1)
    assert len(meta.materials) == 1
    mat = meta.materials[0]
    assert isinstance(mat, FrameworkMaterial)
    assert mat.name == "Mat1"
    assert mat.shader == "MeshStandardMaterial"
    assert mat.used_by == ["Mesh1"]
    assert mat.properties == {"metalness": 0.5}
    assert mat.textures == {"map": "tex_diffuse"}


def test_parse_render_passes():
    store = MetadataStore()
    store.store(1, FULL_PAYLOAD)
    meta = store.get(1)
    assert len(meta.render_passes) == 1
    rp = meta.render_passes[0]
    assert isinstance(rp, FrameworkRenderPass)
    assert rp.name == "ShadowPass"
    assert rp.draw_call_range == [0, 10]
    assert rp.output == "shadow_map"
    assert rp.input == []


def test_partial_data_only_objects():
    """Store with only objects; materials and render_passes should default to empty lists."""
    store = MetadataStore()
    payload = {
        "framework": "custom",
        "objects": [{"name": "Obj", "draw_call_ids": [5]}],
    }
    store.store(10, payload)
    meta = store.get(10)
    assert meta.framework == "custom"
    assert len(meta.objects) == 1
    assert meta.objects[0].name == "Obj"
    assert meta.objects[0].draw_call_ids == [5]
    assert meta.materials == []
    assert meta.render_passes == []
