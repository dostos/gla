from __future__ import annotations
import io
from dataclasses import dataclass
from typing import Any, Callable, Optional
from PIL import Image

@dataclass
class SignatureMatchResult:
    matched: bool
    ambiguous: bool = False
    reason: str = ""

_Matcher = Callable[[bytes, dict], SignatureMatchResult]

_REGISTRY: dict[str, _Matcher] = {}

def register(name: str):
    def deco(fn: _Matcher) -> _Matcher:
        _REGISTRY[name] = fn
        return fn
    return deco

def match_signature(image_png: bytes, signature: dict) -> SignatureMatchResult:
    sig_type = signature.get("type")
    spec = signature.get("spec", {})
    matcher = _REGISTRY.get(sig_type)
    if matcher is None:
        return SignatureMatchResult(matched=False, ambiguous=True,
                                    reason=f"no matcher for type '{sig_type}'")
    return matcher(image_png, spec)

def _dominant_color(img: Image.Image) -> tuple[float, float, float, float]:
    rgba = img.convert("RGBA")
    pixels = list(rgba.get_flattened_data())
    n = len(pixels)
    r = sum(p[0] for p in pixels) / (n * 255)
    g = sum(p[1] for p in pixels) / (n * 255)
    b = sum(p[2] for p in pixels) / (n * 255)
    a = sum(p[3] for p in pixels) / (n * 255)
    return (r, g, b, a)

def _color_delta(a, b) -> float:
    return max(abs(a[i] - b[i]) for i in range(min(len(a), len(b))))

@register("framebuffer_dominant_color")
def _match_fb_dominant(image_png: bytes, spec: dict) -> SignatureMatchResult:
    img = Image.open(io.BytesIO(image_png))
    actual = _dominant_color(img)
    expected = spec.get("color", [0, 0, 0, 1])
    tol = spec.get("tolerance", 0.1)
    delta = _color_delta(actual, expected)
    return SignatureMatchResult(
        matched=(delta <= tol),
        reason=f"delta={delta:.3f} vs tol={tol}, actual={actual}",
    )
