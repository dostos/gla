from __future__ import annotations
import io
import math
from dataclasses import dataclass
from typing import Any, Callable, Optional
from PIL import Image

@dataclass
class SignatureMatchResult:
    matched: bool
    ambiguous: bool = False
    reason: str = ""

_Matcher = Callable[[bytes, dict, dict], SignatureMatchResult]

_REGISTRY: dict[str, _Matcher] = {}

def register(name: str):
    def deco(fn: _Matcher) -> _Matcher:
        _REGISTRY[name] = fn
        return fn
    return deco

def match_signature(image_png: bytes, signature: dict,
                    metadata: Optional[dict] = None) -> SignatureMatchResult:
    metadata = metadata or {}
    sig_type = signature.get("type")
    spec = signature.get("spec", {})
    matcher = _REGISTRY.get(sig_type)
    if matcher is None:
        return SignatureMatchResult(matched=False, ambiguous=True,
                                    reason=f"no matcher for type '{sig_type}'")
    return matcher(image_png, spec, metadata)

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

@register("color_histogram_in_region")
def _match_region_histogram(image_png: bytes, spec: dict, metadata: dict) -> SignatureMatchResult:
    img = Image.open(io.BytesIO(image_png)).convert("RGBA")
    W, H = img.size
    x0, y0, x1, y1 = spec.get("region", [0, 0, 1, 1])
    crop = img.crop((int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)))
    actual = _dominant_color(crop)
    expected = spec.get("dominant_color", [0, 0, 0, 1])
    tol = spec.get("tolerance", 0.1)
    delta = _color_delta(actual, expected)
    return SignatureMatchResult(
        matched=(delta <= tol),
        reason=f"region={spec.get('region')}, actual={actual}, delta={delta:.3f}",
    )

@register("framebuffer_dominant_color")
def _match_fb_dominant(image_png: bytes, spec: dict, metadata: dict) -> SignatureMatchResult:
    img = Image.open(io.BytesIO(image_png))
    actual = _dominant_color(img)
    expected = spec.get("color", [0, 0, 0, 1])
    tol = spec.get("tolerance", 0.1)
    delta = _color_delta(actual, expected)
    return SignatureMatchResult(
        matched=(delta <= tol),
        reason=f"delta={delta:.3f} vs tol={tol}, actual={actual}",
    )

@register("missing_draw_call")
def _match_missing_dc(image_png: bytes, spec: dict, metadata: dict) -> SignatureMatchResult:
    expected = spec.get("expected_count", 0)
    key = spec.get("actual_count_key", "draw_call_count")
    actual = metadata.get(key)
    if actual is None:
        return SignatureMatchResult(matched=False, ambiguous=True,
                                    reason=f"metadata missing key '{key}'")
    return SignatureMatchResult(
        matched=(actual < expected),
        reason=f"expected>={expected}, actual={actual}",
    )

@register("unexpected_state_in_draw")
def _match_state(image_png: bytes, spec: dict, metadata: dict) -> SignatureMatchResult:
    dc_id = spec.get("draw_call", 0)
    field = spec.get("field")
    expected = spec.get("expected_value")
    must_differ = spec.get("actual_must_differ", True)
    dcs = metadata.get("draw_calls") or []
    dc = next((d for d in dcs if d.get("id") == dc_id), None)
    if dc is None:
        return SignatureMatchResult(matched=False, ambiguous=True,
                                    reason=f"draw_call {dc_id} not in metadata")
    actual = (dc.get("pipeline") or {}).get(field)
    if must_differ:
        return SignatureMatchResult(
            matched=(actual != expected),
            reason=f"field={field}, actual={actual}, expected={expected}",
        )
    return SignatureMatchResult(
        matched=(actual == expected),
        reason=f"field={field}, actual={actual}, expected={expected}",
    )

@register("nan_or_inf_in_uniform")
def _match_nan(image_png: bytes, spec: dict, metadata: dict) -> SignatureMatchResult:
    dc_id = spec.get("draw_call", 0)
    uniform = spec.get("uniform")
    dcs = metadata.get("draw_calls") or []
    dc = next((d for d in dcs if d.get("id") == dc_id), None)
    if dc is None:
        return SignatureMatchResult(matched=False, ambiguous=True,
                                    reason=f"draw_call {dc_id} missing")
    param = next((p for p in (dc.get("params") or []) if p.get("name") == uniform), None)
    if param is None:
        return SignatureMatchResult(matched=False, ambiguous=True,
                                    reason=f"uniform '{uniform}' missing")
    values = param.get("value") or []
    if not isinstance(values, (list, tuple)):
        values = [values]
    for v in values:
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if math.isnan(fv) or math.isinf(fv):
            return SignatureMatchResult(matched=True,
                                        reason=f"found non-finite in {uniform}")
    return SignatureMatchResult(matched=False, reason="all values finite")
