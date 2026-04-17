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
