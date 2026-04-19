#!/usr/bin/env python3
"""Parse and score Round 5 eval outputs."""
import json, os, re, sys
from pathlib import Path

RESULTS_DIR = Path("/tmp/eval_round5")

# Ground-truth keyword groups per scenario. A diagnosis is correct if at least
# `min_matches` groups have at least one keyword matching.
GT = {
    "r12_omniscale_cleanedge_scaling_issues": {
        "groups": [
            ["transformation_matrix", "transformation matrix", "identity", "mat2"],
            ["never written", "never set", "not uploaded", "never uploaded",
             "zero matrix", "default to zero", "defaults to zero", "uninitialized",
             "missing uniform", "no default", "unset uniform", "zero-initialized",
             "uniform.*(?:zero|0)", "missing upload", "(?:no|not).*(?:glUniform|upload)"],
            ["top-left", "(0,0)", "(0, 0)", "origin", "one texel", "same texel",
             "uv.*zero", "vec2\\(0", "flat fill", "uniform collaps"],
        ],
        "min_matches": 2,
    },
    "r23_using_multiple_alphamask_s_with_renderma": {
        "groups": [
            ["_textureMatrix", "textureMatrix", "MaskFilter", "mask filter"],
            ["same texture", "same reference", "identical", "equality",
             "if.*texture.*===", "short.?circuit", "setter guard", "early return",
             "pool", "TexturePool", "reuses", "aliased", "aliasing"],
            ["mapCoord", "updateUvs", "update()", "not updated", "stale uniform",
             "stale uv", "wrong uv", "incorrect uv", "not re-derived", "uv coord"],
        ],
        "min_matches": 2,
    },
    "r24_enabling_autogeneratemipmaps_breaks_filt": {
        "groups": [
            ["mipmap", "mip level", "mip levels", "autoGenerateMipmaps", "generateMipmap"],
            ["TexturePool", "pool", "render target", "render texture", "filter target"],
            ["uninitialized", "unpopulated", "never populated", "never generated",
             "not generated", "pool key", "cache key", "pool id", "ids", "reused",
             "sampling invalid", "garbage", "undefined data"],
        ],
        "min_matches": 2,
    },
    "r25_filters_with_backbuffers_seem_not_to_wor": {
        "groups": [
            ["uBackTexture", "backbuffer", "backBuffer", "back texture", "back buffer"],
            ["group 0", "binding 3", "group 99", "group=99", "bind group",
             "bindgroup", "bind point", "binding point", "wrong binding", "binding mismatch"],
            ["Shader constructor", "FilterSystem", "nameHash", "fallback", "gpuProgram",
             "WGSL", "binding metadata"],
        ],
        "min_matches": 2,
    },
    "r26_incorrect_behavior_in_colormatrixfilter_": {
        "groups": [
            ["ColorMatrixFilter", "colorMatrix", "_colorMatrix", "color matrix"],
            ["offset", "rightmost column", "column", "fourth column", "4th column",
             "translation"],
            ["divide by 255", "/255", "/ 255", "normaliz", "*255", "* 255",
             "multiply mode", "mode multiply", "should not", "shouldn't",
             "wrong division", "incorrect division", "spurious"],
        ],
        "min_matches": 2,
    },
    "r27_bug_black_squares_appear_when_rendering_": {
        "groups": [
            ["anisotropic", "V_GGX", "GGX", "smith", "visibility term", "vis term"],
            ["saturate", "negative", "overshoot", "out of range", "clamped", "clamp",
             "exceeds 1", "greater than 1", ">1"],
            ["diffuse", "energy conservation", "scattering", "totalScattering",
             "1.0 - ", "1 -"],
        ],
        "min_matches": 2,
    },
    "r29_add_an_animated_icon_to_the_map_not_work": {
        "groups": [
            ["symbol layer", "two layer", "two symbol", "icon", "animated icon",
             "pulsing", "static image", "image layer"],
            ["collision", "placement", "allow-overlap", "ignore-placement",
             "icon-allow-overlap", "icon-ignore-placement", "already placed",
             "suppress"],
            ["shared source", "same source", "shared geojson", "source+feature",
             "feature id", "keyed by"],
        ],
        "min_matches": 2,
    },
    "r30_incomplete_lines_problem_with_mixing_lay": {
        "groups": [
            ["drape", "batch", "batching", "order", "layer order", "registration order",
             "slot"],
            ["globe", "terrain", "3d", "draped"],
            ["line layer", "building", "symbol", "fill layer", "overlay"],
        ],
        "min_matches": 2,
    },
    "r33_latest_build_6_38_1_got_glitchy_opacity_": {
        "groups": [
            ["blend", "blending", "GL_BLEND", "glBlendFunc", "blendFunc",
             "NormalBlending", "alpha blend"],
            ["opacity", "alpha", "fade", "transparent", "transparency"],
            ["EffectPass", "EffectMaterial", "final pass", "default framebuffer",
             "6.38.1", "last pass", "to screen", "renderToScreen"],
        ],
        "min_matches": 2,
    },
    "r34_depth_buffer_issue_when_using_depthoffie": {
        "groups": [
            ["PERSPECTIVE_CAMERA", "perspective camera", "perspective projection",
             "perspectiveDepthToViewZ"],
            ["CoC", "circle of confusion", "cocMaterial", "DepthOfField",
             "depth of field"],
            ["nonlinear", "non-linear", "linear depth", "depth buffer", "depth value",
             "depth texture", "depth encoding", "viewZ", "ortho"],
        ],
        "min_matches": 2,
    },
    "r32_v7_issue_with_custom_points_shader_three": {
        "groups": [
            ["gBufferNormal", "g-buffer", "gbuffer", "color attachment", "attachment 1",
             "layout(location=1)", "layout (location = 1)", "drawBuffers",
             "glDrawBuffers", "multiple render target", "MRT", "second attachment"],
            ["PointsMaterial", "points material", "SpriteMaterial", "sprite material",
             "custom points", "fragment output", "frag output", "out_Color",
             "output declaration", "fragment declaration"],
            ["undefined", "missing", "doesn't declare", "not declared", "not written",
             "unwritten", "unset", "does not output"],
        ],
        "min_matches": 2,
    },
    "r28_bug_in_rendering_glb_models": {
        "groups": [
            ["16 bit", "16-bit", "uint16", "UNSIGNED_SHORT", "GL_UNSIGNED_SHORT",
             "short index", "16bit"],
            ["index buffer", "indices", "index array"],
            ["65536", "65535", "88948", "overflow", "truncat", "exceeds",
             "too many vertices", "vertex count"],
        ],
        "min_matches": 2,
    },
    "r15_unrealbloompass_produces_no_visible_outp": {
        "groups": [
            ["UnrealBloomPass", "bloom pass", "bloom"],
            ["shader compilation", "shader compile", "silent", "no error",
             "getError", "compilation error", "program link", "link error",
             "FullScreenQuad", "ShaderMaterial", "internal"],
            ["no output", "no visible", "no glow", "missing", "empty output",
             "invisible", "not drawn", "not rendered"],
        ],
        "min_matches": 2,
    },
    "r20_three_js_meshdepthmaterial_depth_map_not": {
        "groups": [
            ["MeshDepthMaterial", "depth material", "depth map", "depth visualization"],
            ["near", "far", "near plane", "far plane", "frustum", "near/far",
             "near far ratio", "logarithmicDepthBuffer", "log depth"],
            ["nonlinear", "non-linear", "1/z", "perspective", "precision",
             "compressed", "concentrated", "bright", "saturated"],
        ],
        "min_matches": 2,
    },
    "r22_point_sprite_rendering_issues_with_three": {
        "groups": [
            ["THREE.Points", "Points", "point sprite", "sprite"],
            ["depth", "depthWrite", "depth write", "z-fight", "z fighting",
             "zfighting", "coplanar"],
            ["transparent", "alpha", "alphaTest", "fringe", "blending",
             "alpha blend"],
        ],
        "min_matches": 2,
    },
    "r24_artifacts_when_rendering_both_sides_of_a": {
        "groups": [
            ["double.?sided", "both sides", "BackSide", "FrontSide", "DoubleSide",
             "side =", "material.side"],
            ["transparent", "transparency", "alpha blend", "blend", "self.?transparency"],
            ["order", "ordering", "sort", "depth.?write", "depthMask", "depth mask",
             "triangle order", "render order"],
        ],
        "min_matches": 2,
    },
    "r11_three_js_effectcomposer_browser_window_r": {
        "groups": [
            ["EffectComposer", "effect composer", "composer"],
            ["resize", "setSize", "window.resize"],
            ["tDiffuse2", "uniform", "sampler", "stale", "old texture",
             "render target", "renderTarget", "reset", "rebind", "not updated",
             "orphan", "old reference"],
        ],
        "min_matches": 2,
    },
    "r15_post_effects_and_transparent_background_": {
        "groups": [
            ["UnrealBloomPass", "bloom pass", "bloom"],
            ["alpha", "transparent", "transparency", "gl_FragColor", "fragColor"],
            ["getSeperableBlur", "separable blur", "gaussian blur", "blur material",
             "1.0", "hardcoded", "hard-coded", "vec4.*1\\.0", "alpha.*1"],
        ],
        "min_matches": 2,
    },
    "r3_material_shines_through_when_zooming_out": {
        "groups": [
            ["zNear", "near plane", "zFar", "far plane", "near/far", "near.far",
             "precision", "depth precision", "depth buffer"],
            ["z-fight", "z fighting", "zfighting", "shines through", "depth collision",
             "fighting"],
            ["logarithmicDepthBuffer", "log depth", "raise near", "increase near",
             "reduce far", "ratio", "1/z", "non.?linear"],
        ],
        "min_matches": 2,
    },
    "r25_three_js_transparency_disparition": {
        "groups": [
            ["transparent: true", "transparent:true", "transparent=true",
             "transparent flag", "material.transparent", "set transparent",
             "transparent true"],
            ["opacity", "alpha blend", "GL_BLEND", "blend", "blending"],
            ["MeshNormalMaterial", "material", "second material", "larger cylinder",
             "outer cylinder", "cylinder"],
        ],
        "min_matches": 2,
    },
}


def extract_json_tail(text: str) -> dict | None:
    if not text: return None
    try:
        # claude -p --output-format json returns a top-level JSON object whose 'result' field is the string
        wrapper = json.loads(text.strip())
        if isinstance(wrapper, dict) and "result" in wrapper:
            inner = wrapper["result"]
            # inner may have fenced json or be plain text ending in json
            return find_json_object(inner)
    except Exception:
        pass
    return find_json_object(text)


def find_json_object(s: str) -> dict | None:
    if not s: return None
    # Strip code fences
    s = re.sub(r"```(?:json)?", "", s)
    matches = re.findall(r'\{[\s\S]*?\}', s)
    # Try last match that parses and has root_cause
    for m in reversed(matches):
        try:
            d = json.loads(m)
            if isinstance(d, dict) and "root_cause" in d:
                return d
        except Exception:
            continue
    # Try greedy grab from first "{" to last "}"
    a = s.rfind("{")
    if a >= 0:
        b = s.rfind("}")
        if b > a:
            try:
                d = json.loads(s[a:b+1])
                if isinstance(d, dict) and "root_cause" in d:
                    return d
            except Exception:
                pass
    return None


def score_diagnosis(scenario: str, text: str) -> tuple[bool, int]:
    spec = GT[scenario]
    lower = text.lower()
    hits = 0
    for group in spec["groups"]:
        for kw in group:
            if re.search(kw.lower(), lower):
                hits += 1
                break
    return hits >= spec.get("min_matches", 2), hits


def load_cost(wrapper: dict) -> float:
    try:
        return float(wrapper.get("total_cost_usd") or wrapper.get("cost_usd") or 0)
    except Exception:
        return 0.0


def load_turns(wrapper: dict) -> int:
    try:
        return int(wrapper.get("num_turns", 0))
    except Exception:
        return 0


def main():
    rows = []
    for f in sorted(RESULTS_DIR.glob("*_*.json")):
        name = f.stem
        # Parse scenario, mode, model
        # mode is code_only or with_gpa
        m = re.match(r"^(.*?)_(code_only|with_gpa)_(haiku|sonnet)$", name)
        if not m: continue
        scen, mode, model = m.group(1), m.group(2), m.group(3)
        if scen not in GT: continue

        raw = f.read_text()
        wrapper = None
        try:
            wrapper = json.loads(raw)
        except Exception:
            pass
        diag = extract_json_tail(raw) or {}
        text = json.dumps(diag) + " " + ((wrapper or {}).get("result", "") if wrapper else "")
        correct, hits = score_diagnosis(scen, text)
        cost = load_cost(wrapper or {})
        turns = load_turns(wrapper or {})
        rows.append({
            "scenario": scen,
            "mode": mode,
            "model": model,
            "correct": correct,
            "hits": hits,
            "turns": turns,
            "cost_usd": cost,
            "framework_files_opened": diag.get("framework_files_opened", None),
            "gpa_queries_made": diag.get("gpa_queries_made", None),
            "confidence": diag.get("confidence", ""),
            "offending_symbol": diag.get("offending_symbol", ""),
            "root_cause": (diag.get("root_cause", "") or "")[:300],
        })
    (RESULTS_DIR / "scored.json").write_text(json.dumps(rows, indent=2))
    # Summary
    total = len(rows)
    by_mode_model = {}
    by_scen = {}
    total_cost = 0.0
    for r in rows:
        k = (r["mode"], r["model"])
        by_mode_model.setdefault(k, [0, 0])
        by_mode_model[k][0] += 1
        by_mode_model[k][1] += int(r["correct"])
        by_scen.setdefault(r["scenario"], []).append(r)
        total_cost += r["cost_usd"]
    print(f"Total runs: {total}  Total cost: ${total_cost:.2f}")
    print("\n## Mode × Model Accuracy")
    print(f"{'Mode':<12} {'Model':<8} {'N':>3} {'Correct':>8} {'Acc':>7}")
    for (mode, model), (n, c) in sorted(by_mode_model.items()):
        print(f"{mode:<12} {model:<8} {n:>3} {c:>8} {c/n*100 if n else 0:>6.1f}%")
    print("\n## Per-Scenario")
    print(f"{'scenario':<50} {'co_h':>5} {'co_s':>5} {'gp_h':>5} {'gp_s':>5}")
    for scen in sorted(by_scen):
        d = {(r["mode"], r["model"]): r["correct"] for r in by_scen[scen]}
        co_h = "Y" if d.get(("code_only","haiku")) else "N" if ("code_only","haiku") in d else "-"
        co_s = "Y" if d.get(("code_only","sonnet")) else "N" if ("code_only","sonnet") in d else "-"
        gp_h = "Y" if d.get(("with_gpa","haiku")) else "N" if ("with_gpa","haiku") in d else "-"
        gp_s = "Y" if d.get(("with_gpa","sonnet")) else "N" if ("with_gpa","sonnet") in d else "-"
        print(f"{scen:<50} {co_h:>5} {co_s:>5} {gp_h:>5} {gp_s:>5}")


if __name__ == "__main__":
    main()
