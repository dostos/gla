"""Tests for gla.framework.correlation helpers."""
import pytest
from gla.framework.types import (
    FrameMetadata,
    FrameworkMaterial,
    FrameworkObject,
    FrameworkRenderPass,
)
from gla.framework import correlation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_metadata():
    objects = [
        FrameworkObject(name="Player", draw_call_ids=[1, 2]),
        FrameworkObject(name="Enemy", draw_call_ids=[3]),
        FrameworkObject(name="Ground", draw_call_ids=[4, 5]),
    ]
    materials = [
        FrameworkMaterial(name="PlayerMat", shader="pbr", used_by=["Player"]),
        FrameworkMaterial(name="GroundMat", shader="terrain", used_by=["Ground"]),
    ]
    render_passes = [
        FrameworkRenderPass(name="GBuffer", draw_call_range=[1, 3]),
        FrameworkRenderPass(name="Shadow", draw_call_range=[4, 5]),
    ]
    return FrameMetadata(
        framework="three.js",
        objects=objects,
        materials=materials,
        render_passes=render_passes,
    )


# ---------------------------------------------------------------------------
# find_object_for_drawcall
# ---------------------------------------------------------------------------

def test_find_object_for_drawcall_found():
    md = _make_metadata()
    obj = correlation.find_object_for_drawcall(1, md)
    assert obj is not None
    assert obj.name == "Player"


def test_find_object_for_drawcall_second_id():
    md = _make_metadata()
    obj = correlation.find_object_for_drawcall(2, md)
    assert obj is not None
    assert obj.name == "Player"


def test_find_object_for_drawcall_other_object():
    md = _make_metadata()
    obj = correlation.find_object_for_drawcall(3, md)
    assert obj is not None
    assert obj.name == "Enemy"


def test_find_object_for_drawcall_not_found():
    md = _make_metadata()
    assert correlation.find_object_for_drawcall(99, md) is None


def test_find_object_for_drawcall_none_metadata():
    assert correlation.find_object_for_drawcall(1, None) is None


# ---------------------------------------------------------------------------
# find_material_for_object
# ---------------------------------------------------------------------------

def test_find_material_for_object_found():
    md = _make_metadata()
    mat = correlation.find_material_for_object("Player", md)
    assert mat is not None
    assert mat.name == "PlayerMat"


def test_find_material_for_object_ground():
    md = _make_metadata()
    mat = correlation.find_material_for_object("Ground", md)
    assert mat is not None
    assert mat.name == "GroundMat"


def test_find_material_for_object_no_material():
    md = _make_metadata()
    # Enemy has no material assigned
    assert correlation.find_material_for_object("Enemy", md) is None


def test_find_material_for_object_none_metadata():
    assert correlation.find_material_for_object("Player", None) is None


# ---------------------------------------------------------------------------
# find_render_pass_for_drawcall
# ---------------------------------------------------------------------------

def test_find_render_pass_from_metadata():
    md = _make_metadata()
    assert correlation.find_render_pass_for_drawcall(1, md) == "GBuffer"
    assert correlation.find_render_pass_for_drawcall(3, md) == "GBuffer"
    assert correlation.find_render_pass_for_drawcall(4, md) == "Shadow"
    assert correlation.find_render_pass_for_drawcall(5, md) == "Shadow"


def test_find_render_pass_not_in_range():
    md = _make_metadata()
    # dc_id 0 is before any range
    result = correlation.find_render_pass_for_drawcall(0, md, debug_group_path="SomePath/X")
    # Falls back to debug group path first segment
    assert result == "SomePath"


def test_find_render_pass_fallback_to_debug_group():
    result = correlation.find_render_pass_for_drawcall(99, None, debug_group_path="PostProcess/Bloom")
    assert result == "PostProcess"


def test_find_render_pass_fallback_no_slash():
    result = correlation.find_render_pass_for_drawcall(99, None, debug_group_path="ForwardPass")
    assert result == "ForwardPass"


def test_find_render_pass_no_info():
    assert correlation.find_render_pass_for_drawcall(99, None, debug_group_path="") is None


def test_find_render_pass_metadata_preferred_over_debug_group():
    md = _make_metadata()
    # dc_id=2 is in GBuffer range [1,3]; debug group says something different
    result = correlation.find_render_pass_for_drawcall(2, md, debug_group_path="Shadow/Something")
    assert result == "GBuffer"
