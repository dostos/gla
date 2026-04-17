"""Tests for debug_groups.build_debug_group_tree."""
import pytest
from gla.framework.debug_groups import build_debug_group_tree, DebugGroupNode


def _dc(dc_id, path=""):
    """Helper: dict-style draw call."""
    return {"id": dc_id, "debug_group_path": path}


class _DC:
    """Helper: object-style draw call."""
    def __init__(self, dc_id, path=""):
        self.id = dc_id
        self.debug_group_path = path


# ---------------------------------------------------------------------------
# 1. empty_frame — no draw calls → root with no children
# ---------------------------------------------------------------------------

def test_empty_frame():
    root = build_debug_group_tree([])
    assert root.name == "Frame"
    assert root.children == []
    assert root.draw_call_ids == []


# ---------------------------------------------------------------------------
# 2. single_draw_no_group — dc without path → in root.draw_call_ids
# ---------------------------------------------------------------------------

def test_single_draw_no_group():
    root = build_debug_group_tree([_dc(1, "")])
    assert root.draw_call_ids == [1]
    assert root.children == []


def test_single_draw_no_group_object():
    """Same test with object-style draw call."""
    root = build_debug_group_tree([_DC(1, "")])
    assert root.draw_call_ids == [1]
    assert root.children == []


# ---------------------------------------------------------------------------
# 3. nested_groups — "GBuffer/Player" → root > GBuffer > Player
# ---------------------------------------------------------------------------

def test_nested_groups():
    root = build_debug_group_tree([_dc(5, "GBuffer/Player")])
    assert len(root.children) == 1
    gbuffer = root.children[0]
    assert gbuffer.name == "GBuffer"
    assert gbuffer.draw_call_ids == []
    assert len(gbuffer.children) == 1
    player = gbuffer.children[0]
    assert player.name == "Player"
    assert player.draw_call_ids == [5]


# ---------------------------------------------------------------------------
# 4. multiple_draws_same_group — 3 DCs in "Shadow" → one node with 3 IDs
# ---------------------------------------------------------------------------

def test_multiple_draws_same_group():
    dcs = [_dc(1, "Shadow"), _dc(2, "Shadow"), _dc(3, "Shadow")]
    root = build_debug_group_tree(dcs)
    assert len(root.children) == 1
    shadow = root.children[0]
    assert shadow.name == "Shadow"
    assert sorted(shadow.draw_call_ids) == [1, 2, 3]


# ---------------------------------------------------------------------------
# 5. sibling_groups — "Pass1" and "Pass2" → 2 children of root
# ---------------------------------------------------------------------------

def test_sibling_groups():
    dcs = [_dc(1, "Pass1"), _dc(2, "Pass2"), _dc(3, "Pass2")]
    root = build_debug_group_tree(dcs)
    names = [c.name for c in root.children]
    assert "Pass1" in names
    assert "Pass2" in names
    assert len(root.children) == 2

    pass2 = next(c for c in root.children if c.name == "Pass2")
    assert sorted(pass2.draw_call_ids) == [2, 3]


# ---------------------------------------------------------------------------
# Extra: mixed path lengths in same tree
# ---------------------------------------------------------------------------

def test_mixed_nesting():
    dcs = [
        _dc(1, "GBuffer/Player"),
        _dc(2, "GBuffer/Enemy"),
        _dc(3, "GBuffer"),
        _dc(4, ""),
    ]
    root = build_debug_group_tree(dcs)
    assert root.draw_call_ids == [4]
    assert len(root.children) == 1
    gbuffer = root.children[0]
    assert gbuffer.draw_call_ids == [3]
    child_names = {c.name for c in gbuffer.children}
    assert child_names == {"Player", "Enemy"}
