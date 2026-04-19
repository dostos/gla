from pathlib import Path
from gla.eval.curation.signature_matchers import match_signature, SignatureMatchResult

FIX = Path(__file__).parent / "fixtures" / "curation" / "framebuffers"

def _load(name: str) -> bytes:
    return (FIX / name).read_bytes()

def test_framebuffer_dominant_color_match():
    result = match_signature(
        image_png=_load("solid_red.png"),
        signature={"type": "framebuffer_dominant_color",
                   "spec": {"color": [1.0, 0.0, 0.0, 1.0], "tolerance": 0.1}},
    )
    assert result.matched is True

def test_framebuffer_dominant_color_mismatch():
    result = match_signature(
        image_png=_load("solid_blue.png"),
        signature={"type": "framebuffer_dominant_color",
                   "spec": {"color": [1.0, 0.0, 0.0, 1.0], "tolerance": 0.1}},
    )
    assert result.matched is False
    assert result.reason

def test_unknown_signature_type_returns_ambiguous():
    result = match_signature(
        image_png=_load("solid_red.png"),
        signature={"type": "unknown_made_up_type", "spec": {}},
    )
    assert result.ambiguous is True

def test_color_histogram_in_region_match():
    result = match_signature(
        image_png=_load("red_center_blue_bg.png"),
        signature={
            "type": "color_histogram_in_region",
            "spec": {
                "region": [0.375, 0.375, 0.625, 0.625],   # center 25%
                "dominant_color": [1.0, 0.0, 0.0, 1.0],
                "tolerance": 0.1,
            },
        },
    )
    assert result.matched is True

def test_color_histogram_in_region_mismatch_outside_region():
    result = match_signature(
        image_png=_load("red_center_blue_bg.png"),
        signature={
            "type": "color_histogram_in_region",
            "spec": {
                "region": [0.0, 0.0, 0.2, 0.2],   # top-left corner, expect blue
                "dominant_color": [1.0, 0.0, 0.0, 1.0],
                "tolerance": 0.1,
            },
        },
    )
    assert result.matched is False

def test_missing_draw_call_match():
    result = match_signature(
        image_png=_load("solid_red.png"),
        signature={"type": "missing_draw_call",
                   "spec": {"expected_count": 2, "actual_count_key": "draw_call_count"}},
        metadata={"draw_call_count": 1},
    )
    assert result.matched is True

def test_missing_draw_call_mismatch():
    result = match_signature(
        image_png=_load("solid_red.png"),
        signature={"type": "missing_draw_call",
                   "spec": {"expected_count": 2, "actual_count_key": "draw_call_count"}},
        metadata={"draw_call_count": 2},
    )
    assert result.matched is False

def test_unexpected_state_in_draw():
    result = match_signature(
        image_png=_load("solid_red.png"),
        signature={"type": "unexpected_state_in_draw",
                   "spec": {"draw_call": 0, "field": "cull_mode",
                            "expected_value": "BACK", "actual_must_differ": True}},
        metadata={"draw_calls": [{"id": 0, "pipeline": {"cull_mode": "FRONT"}}]},
    )
    assert result.matched is True

def test_nan_or_inf_in_uniform():
    import math
    result = match_signature(
        image_png=_load("solid_red.png"),
        signature={"type": "nan_or_inf_in_uniform",
                   "spec": {"draw_call": 0, "uniform": "normalMatrix"}},
        metadata={"draw_calls": [{"id": 0, "params": [
            {"name": "normalMatrix", "value": [1.0, float("nan"), 0.0]}
        ]}]},
    )
    assert result.matched is True
