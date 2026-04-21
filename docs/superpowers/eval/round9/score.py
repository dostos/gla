#!/usr/bin/env python3
"""Score Round 9 eval outputs.

Supports haiku + sonnet + opus, plus three scenario categories:
  - state_collision (8)
  - source_logical (8)  -- new for R9; tests native-trace's value
  - carryover (4)
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, "/home/jingyulee/gh/gla/src/python")
from gpa.eval.telemetry import parse_stream_json, classify_verdict

RESULTS_DIR = Path("/tmp/eval_round9")


def find_json_object(s: str) -> dict | None:
    if not s:
        return None
    s = re.sub(r"```(?:json)?", "", s)
    matches = re.findall(r'\{[\s\S]*?\}', s)
    for m in reversed(matches):
        try:
            d = json.loads(m)
            if isinstance(d, dict) and "root_cause" in d:
                return d
        except Exception:
            continue
    a = s.rfind("{")
    if a >= 0:
        try:
            return json.loads(s[a:])
        except Exception:
            pass
    return None


# ------------------------- Ground truth keyword specs ------------------------

GT: dict[str, dict] = {
    # State-collision (8)
    "r4_3d_map_black_screen": {
        "groups": [
            ["feedback.?loop", "INVALID_OPERATION", "framebuffer.*texture.*same",
             "same.*texture.*framebuffer"],
            ["sampler", "texture.?bind", "bind.?point", "attachment",
             "COLOR_ATTACHMENT"],
            ["no-op", "dropped", "black", "clear.color", "stale"],
        ],
        "min_matches": 2,
    },
    "r19_depthtexture_share_source_after_renderta": {
        "groups": [
            ["DepthTexture", "depth.?texture", "Source", "texture.?source",
             "source.image"],
            ["copy", "clone", "share", "alias", "same.*source", "same.*object",
             "reference"],
            ["feedback.?loop", "ping.?pong", "EffectComposer", "both.*framebuffer",
             "shared"],
        ],
        "min_matches": 2,
    },
    "r13_cubecamera_render_target_displaying_rand": {
        "groups": [
            ["cube.?map", "TEXTURE_CUBE_MAP", "samplerCube", "cube.?texture",
             "envMap"],
            ["target.?type", "multiple.?targets", "rebind", "different.?target",
             "GL_TEXTURE_2D", "INVALID_OPERATION", "target.specific"],
            ["invalid", "no-?op", "wrong.?texture", "previous.?texture",
             "prior", "black"],
        ],
        "min_matches": 2,
    },
    "r18_webglrenderer_reversed_depth_not_working": {
        "groups": [
            ["reversed.?z", "reversed.?depth", "reverse.?depth", "GL_GREATER",
             "DEPTH_TEST", "depthFunc"],
            ["clearDepth", "depth.?clear", "clear.*depth", "autoClear",
             "1.0", "0.0", "not.?cleared", "never.?clear"],
            ["PMREMGenerator", "_sceneToCubeUV", "cube.?UV",
             "render.?target", "attachment"],
        ],
        "min_matches": 2,
    },
    "r16_lightprobegenerator_does_not_work_with_e": {
        "groups": [
            ["FloatType", "HalfFloat", "Float32Array", "Uint16Array",
             "readPixels", "readback", "buffer.?size"],
            ["mismatch", "wrong.?type", "type.?mismatch", "byte.?length",
             "too.?small", "size", "half.*size"],
            ["LightProbeGenerator", "fromCubeRenderTarget", "INVALID_OPERATION",
             "not.*written", "zero"],
        ],
        "min_matches": 2,
    },
    "r7_webglbackend_copytexturetotexture_doesn_": {
        "groups": [
            ["copyTextureToTexture", "copy.?texture", "3D.?texture", "TEXTURE_3D",
             "TEXTURE_2D_ARRAY", "layer", "slice", "depth"],
            ["single.?slice", "only.*layer", "layer.?0", "base.?layer",
             "z=0", "first.?layer", "not.?iterate", "fall?back"],
            ["WebGLBackend", "framebufferTextureLayer", "2D.?only", "codepath",
             "differ"],
        ],
        "min_matches": 2,
    },
    "r9_transparent_objects_brighten_when_using_": {
        "groups": [
            ["sRGB", "gamma", "linear", "color.?space", "colorSpace"],
            ["pow\\(", "1/2.2", "encoded?", "encoding", "inline", "shader",
             "fragment.*output", "before.*blend", "pre.?blend"],
            ["blend", "alpha.?blend", "transparent", "opacity", "framebuffer",
             "FRAMEBUFFER_SRGB", "non.?linear"],
        ],
        "min_matches": 2,
    },
    "r17_viewport_rendering_with_postprocessing_r": {
        "groups": [
            ["glClear", "clear", "clear.color", "autoClear", "color.?buffer"],
            ["viewport", "scissor", "GL_SCISSOR_TEST", "sub.?region",
             "small.?viewport"],
            ["PostProcessing", "post.?process", "framebuffer", "render.?target",
             "separate", "second.*render"],
        ],
        "min_matches": 2,
    },

    # Source-logical (8)
    "r21_fix_vertical_and_horizontal_artifacts_on": {
        "groups": [
            ["stencil", "stencilMask", "stencilFunc", "0xF8", "5.?bit"],
            ["tile.?id", "clipping.?mask", "clip.?mask", "id.?next",
             "idNext", "wrap", "collision", "collide"],
            ["overflow", "31", "shift", "<<\\s*3", "3.?bit"],
        ],
        "min_matches": 2,
    },
    "r18_model_disappears_when_rotating_or_zoomin": {
        "groups": [
            ["cull", "culled", "culling", "frustum", "visible", "visibility"],
            ["anchor", "lng", "lat", "center", "instance.?point",
             "per.?instance", "bounding", "bounds"],
            ["tile", "tileID", "tile.?set", "model.?layer", "world.?space"],
        ],
        "min_matches": 2,
    },
    "r4_motion_blur_and_instancedmesh": {
        "groups": [
            ["previous", "prev", "prevInstance", "previousInstance",
             "previousInstanceMatrix", "last.?frame"],
            ["instance", "InstancedMesh", "InstanceNode", "a_instanceMatrix",
             "per.?instance"],
            ["velocity", "motion.?blur", "viewProj", "clip.*position",
             "cur.?clip", "prev.?clip", "zero.?vector"],
        ],
        "min_matches": 2,
    },
    "r14_cannot_override_vertexnode_of_instanced_": {
        "groups": [
            ["positionLocal", "positionGeometry", "vertexNode", "vertex.?node"],
            ["instance", "instancing", "morph", "skinning", "batch"],
            ["override", "bypass", "skip", "not.*applied", "not.*included",
             "unresolved", "missing"],
        ],
        "min_matches": 2,
    },
    "r17_replacing_an_attribute_of_a_geometry_ins": {
        "groups": [
            ["cache", "cached", "WeakMap", "reference", "identity", "uuid",
             "version"],
            ["replace", "reassign", "swap", "stale", "not.*invalidat", "never.*invalidat"],
            ["attribute", "InstanceNode", "NodeMaterialObserver", "VAO",
             "vertex.?attrib", "BufferAttribute", "instanceMatrix"],
        ],
        "min_matches": 2,
    },
    "r20_object_with_meshphysicalmaterial_contain": {
        "groups": [
            ["bicubic", "textureBicubic", "textureLod", "textureSize",
             "transmission_pars", "getTransmissionSample"],
            ["AMD", "ANGLE", "D3D11", "HLSL", "driver", "miscompile", "Windows",
             "GPU"],
            ["transmission", "MeshPhysicalMaterial", "mipmap", "LOD",
             "dynamic.?LOD", "sample"],
        ],
        "min_matches": 2,
    },
    "r28_objloader_loader_does_not_return_valid_g": {
        "groups": [
            ["normal", "OBJLoader", "OBJ.?loader", "addFace"],
            ["count", "mismatch", "short", "missing", "omit", "synth",
             "misalign", "lockstep"],
            ["attribute", "position", "BufferAttribute", "face", "vertex"],
        ],
        "min_matches": 2,
    },
    "r35_strange_bug_with_3_sprites_where_one_of_": {
        "groups": [
            ["uniform", "declar", "declaration"],
            ["driver", "Vulkan", "Adreno", "Android", "device", "hardware"],
            ["crash", "abort", "binding", "canvas_item", "command.?submission"],
        ],
        "min_matches": 2,
    },

    # Carryover (4)
    "r10_feedback_loop_error_with_transmission_an": {
        "groups": [
            ["feedback.?loop", "INVALID_OPERATION", "framebuffer.*texture",
             "same.*texture.*framebuffer", "bind.*collision"],
            ["transmission", "transmissionSamplerMap", "antialias", "MSAA",
             "multisampl", "samples", "capabilities.samples"],
            ["attachment", "COLOR_ATTACHMENT", "sampler", "DoubleSide",
             "back.?face", "back.?side"],
        ],
        "min_matches": 2,
    },
    "r22_point_sprite_rendering_issues_with_three": {
        "groups": [
            ["PointsMaterial", "point.?sprite", "gl_PointSize", "POINTS"],
            ["size.?attenuation", "sizeAttenuation", "scale", "perspective",
             "distance"],
            ["uniform", "shader", "vertex", "render", "issue"],
        ],
        "min_matches": 2,
    },
    "r25_filters_with_backbuffers_seem_not_to_wor": {
        "groups": [
            ["backbuffer", "back.?buffer", "ping.?pong", "double.?buffer",
             "copy"],
            ["filter", "Filter", "FilterPipe", "pipeline", "uniform"],
            ["render.?texture", "RenderTexture", "framebuffer", "FBO",
             "target"],
        ],
        "min_matches": 2,
    },
    "r27_bug_black_squares_appear_when_rendering_": {
        "groups": [
            ["anisotrop", "GGX", "V_GGX", "visibility", "alphaT", "alphaB"],
            ["negative", "clamp", "saturate", "energy.?conservation",
             "diffuse.?scaling", "totalScatteringDielectric"],
            ["PR.?32330", "#32330", "bicubic", "specular", "overshoot",
             "out.?of.?range", "black"],
        ],
        "min_matches": 2,
    },
}


STATE_COLLISION = {
    "r4_3d_map_black_screen",
    "r19_depthtexture_share_source_after_renderta",
    "r13_cubecamera_render_target_displaying_rand",
    "r18_webglrenderer_reversed_depth_not_working",
    "r16_lightprobegenerator_does_not_work_with_e",
    "r7_webglbackend_copytexturetotexture_doesn_",
    "r9_transparent_objects_brighten_when_using_",
    "r17_viewport_rendering_with_postprocessing_r",
}
SOURCE_LOGICAL = {
    "r21_fix_vertical_and_horizontal_artifacts_on",
    "r18_model_disappears_when_rotating_or_zoomin",
    "r4_motion_blur_and_instancedmesh",
    "r14_cannot_override_vertexnode_of_instanced_",
    "r17_replacing_an_attribute_of_a_geometry_ins",
    "r20_object_with_meshphysicalmaterial_contain",
    "r28_objloader_loader_does_not_return_valid_g",
    "r35_strange_bug_with_3_sprites_where_one_of_",
}
CARRYOVER = {
    "r10_feedback_loop_error_with_transmission_an",
    "r22_point_sprite_rendering_issues_with_three",
    "r25_filters_with_backbuffers_seem_not_to_wor",
    "r27_bug_black_squares_appear_when_rendering_",
}


def categorize(scen: str) -> str:
    if scen in STATE_COLLISION:
        return "state_collision"
    if scen in SOURCE_LOGICAL:
        return "source_logical"
    if scen in CARRYOVER:
        return "carryover"
    return "other"


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


def count_gpa_subtools(messages: list) -> dict:
    """Count gpa report / gpa trace / gpa check invocations from tool_use events."""
    counts = defaultdict(int)
    for m in messages:
        try:
            if m.get("type") != "assistant":
                continue
            content = m.get("message", {}).get("content", [])
            for c in content:
                if c.get("type") == "tool_use" and c.get("name") == "Bash":
                    cmd = c.get("input", {}).get("command", "")
                    if "gpa report" in cmd:
                        counts["gpa_report"] += 1
                    if "gpa trace" in cmd:
                        counts["gpa_trace"] += 1
                    if "gpa check" in cmd:
                        counts["gpa_check"] += 1
                    if "gpa dump" in cmd:
                        counts["gpa_dump"] += 1
        except Exception:
            continue
    return dict(counts)


def main() -> None:
    rows = []
    for f in sorted(RESULTS_DIR.glob("*_*.jsonl")):
        name = f.stem
        m = re.match(r"^(.*?)_(code_only|with_gpa)_(haiku|sonnet|opus)$", name)
        if not m:
            continue
        scen, mode, model = m.group(1), m.group(2), m.group(3)
        if scen not in GT:
            continue

        parsed = parse_stream_json(str(f))
        diag = find_json_object(parsed.get("result_text") or "") or {}
        text = json.dumps(diag) + " " + (parsed.get("result_text") or "")
        correct, hits = score_diagnosis(scen, text)

        # Parse messages for gpa subtool counts
        msgs = []
        try:
            with open(f) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msgs.append(json.loads(line))
                    except Exception:
                        pass
        except Exception:
            pass
        gpa_subs = count_gpa_subtools(msgs)

        timed_out = (
            (not parsed.get("result_text"))
            and parsed.get("num_turns", 0) >= 38
        ) or parsed.get("is_error", False)

        # Use classify_verdict
        try:
            run_for_verdict = {
                "correct": correct,
                "turns": parsed["num_turns"],
                "result": parsed.get("result_text",""),
                "error": parsed.get("is_error", False),
            }
            verdict = classify_verdict(run_for_verdict, max_turns_budget=40)
        except Exception:
            if timed_out:
                verdict = "timeout"
            elif correct:
                verdict = "solved"
            else:
                verdict = "wrong"

        rows.append({
            "scenario": scen,
            "mode": mode,
            "model": model,
            "correct": correct,
            "hits": hits,
            "turns": parsed["num_turns"],
            "cost_usd": parsed["total_cost_usd"],
            "tool_counts": parsed["tool_counts"],
            "gpa_subtools": gpa_subs,
            "cache_read": parsed["cache_read"],
            "cache_creation": parsed["cache_creation"],
            "total_output_tokens": parsed["total_tokens_out"],
            "total_input_tokens": parsed["total_tokens_in"],
            "confidence": diag.get("confidence", ""),
            "offending_symbol": diag.get("offending_symbol", ""),
            "root_cause": (diag.get("root_cause", "") or "")[:300],
            "timed_out": timed_out,
            "verdict": verdict,
            "category": categorize(scen),
        })

    (RESULTS_DIR / "scored.json").write_text(json.dumps(rows, indent=2))

    total = len(rows)
    by_cell: dict[tuple[str, str], list[dict]] = {}
    by_scen: dict[str, list[dict]] = {}
    by_cat_cell: dict[tuple[str, str, str], list[dict]] = {}
    total_cost = 0.0
    for r in rows:
        k = (r["mode"], r["model"])
        by_cell.setdefault(k, []).append(r)
        by_scen.setdefault(r["scenario"], []).append(r)
        by_cat_cell.setdefault((r["category"], r["mode"], r["model"]), []).append(r)
        total_cost += r["cost_usd"]

    out = []
    out.append(f"Total runs: {total}  Total cost: ${total_cost:.2f}")

    # Accuracy
    out.append("\n## Mode x Model Accuracy")
    out.append(f"{'Mode':<12} {'Model':<8} {'N':>3} {'Correct':>8} {'Acc':>7} "
               f"{'AvgCost':>10} {'AvgTurns':>9} {'Timeout':>8}")
    for (mode, model) in sorted(by_cell):
        rs = by_cell[(mode, model)]
        n = len(rs)
        c = sum(int(r["correct"]) for r in rs)
        to = sum(int(r["timed_out"]) for r in rs)
        avg_cost = sum(r["cost_usd"] for r in rs) / n if n else 0
        avg_turns = sum(r["turns"] for r in rs) / n if n else 0
        out.append(f"{mode:<12} {model:<8} {n:>3} {c:>8} "
                   f"{c/n*100 if n else 0:>6.1f}% ${avg_cost:>9.4f} "
                   f"{avg_turns:>9.1f} {to:>8}")

    # Verdict breakdown
    out.append("\n## Verdict Breakdown (mode x model)")
    out.append(f"{'Mode':<12} {'Model':<8} {'solved':>7} {'timeout':>8} {'wrong':>6} {'infra':>6}")
    for (mode, model) in sorted(by_cell):
        rs = by_cell[(mode, model)]
        vc = defaultdict(int)
        for r in rs:
            vc[r["verdict"]] += 1
        out.append(f"{mode:<12} {model:<8} {vc['solved']:>7} "
                   f"{vc['timeout']:>8} {vc['wrong']:>6} {vc['infra']:>6}")

    # Per scenario
    out.append("\n## Per-Scenario (Y/N/-)")
    hdr = f"{'scenario':<50} " + " ".join(
        f"{mode[:2]}_{model[0]}" for mode in ("code_only","with_gpa")
        for model in ("haiku","sonnet","opus"))
    out.append(hdr)
    for scen in sorted(by_scen):
        d = {(r["mode"], r["model"]): r["correct"] for r in by_scen[scen]}
        parts = [f"{scen:<50}"]
        for mode in ("code_only","with_gpa"):
            for model in ("haiku","sonnet","opus"):
                if (mode, model) in d:
                    parts.append("  Y  " if d[(mode, model)] else "  N  ")
                else:
                    parts.append("  -  ")
        out.append(" ".join(parts))

    # Tool breakdown
    out.append("\n## Mean Tool Calls per Run (mode x model)")
    out.append(f"{'Mode':<12} {'Model':<8} {'gpa':>5} {'grpt':>5} {'gtrc':>5} "
               f"{'gchk':>5} {'gdmp':>5} {'curl':>5} {'Read':>5} {'Grep':>5} {'Bash':>5}")
    for (mode, model) in sorted(by_cell):
        rs = by_cell[(mode, model)]
        n = max(len(rs), 1)
        s = {k: 0 for k in ("gpa","curl","Read","Grep","Bash")}
        subs = {k: 0 for k in ("gpa_report","gpa_trace","gpa_check","gpa_dump")}
        for r in rs:
            for k in s:
                s[k] += int(r["tool_counts"].get(k, 0))
            for k in subs:
                subs[k] += int(r["gpa_subtools"].get(k, 0))
        out.append(f"{mode:<12} {model:<8} "
                   f"{s['gpa']/n:>5.1f} {subs['gpa_report']/n:>5.1f} "
                   f"{subs['gpa_trace']/n:>5.1f} {subs['gpa_check']/n:>5.1f} "
                   f"{subs['gpa_dump']/n:>5.1f} {s['curl']/n:>5.1f} "
                   f"{s['Read']/n:>5.1f} {s['Grep']/n:>5.1f} {s['Bash']/n:>5.1f}")

    # Category x mode x model accuracy
    out.append("\n## Accuracy by Category x Mode x Model")
    out.append(f"{'Cat':<18} {'Mode':<12} {'Model':<8} {'N':>3} {'Correct':>8} {'Acc':>7}")
    for (cat, mode, model) in sorted(by_cat_cell):
        rs = by_cat_cell[(cat, mode, model)]
        n = len(rs)
        c = sum(int(r["correct"]) for r in rs)
        out.append(f"{cat:<18} {mode:<12} {model:<8} {n:>3} {c:>8} "
                   f"{c/n*100 if n else 0:>6.1f}%")

    # Source-logical: trace invocation
    out.append("\n## Source-Logical: Trace Usage + Solvability")
    for model in ("haiku","sonnet","opus"):
        co_solved = sum(1 for r in rows if r["scenario"] in SOURCE_LOGICAL
                        and r["mode"]=="code_only" and r["model"]==model and r["correct"])
        gp_solved = sum(1 for r in rows if r["scenario"] in SOURCE_LOGICAL
                        and r["mode"]=="with_gpa" and r["model"]==model and r["correct"])
        gp_n = sum(1 for r in rows if r["scenario"] in SOURCE_LOGICAL
                   and r["mode"]=="with_gpa" and r["model"]==model)
        co_n = sum(1 for r in rows if r["scenario"] in SOURCE_LOGICAL
                   and r["mode"]=="code_only" and r["model"]==model)
        trace_uses = sum(r["gpa_subtools"].get("gpa_trace",0) for r in rows
                         if r["scenario"] in SOURCE_LOGICAL
                         and r["mode"]=="with_gpa" and r["model"]==model)
        trace_runs = sum(1 for r in rows if r["scenario"] in SOURCE_LOGICAL
                         and r["mode"]=="with_gpa" and r["model"]==model
                         and r["gpa_subtools"].get("gpa_trace",0) > 0)
        out.append(f"  {model:<7} code_only {co_solved}/{co_n}  with_gpa {gp_solved}/{gp_n}  "
                   f"trace_calls={trace_uses}  runs_with_trace={trace_runs}/{gp_n}")

    # Paired deltas by model
    out.append("\n## Paired Deltas (both modes correct) per model")
    for model in ("haiku","sonnet","opus"):
        paired = []
        for scen, rs in by_scen.items():
            d = {(r["mode"], r["model"]): r for r in rs}
            co = d.get(("code_only", model))
            gp = d.get(("with_gpa", model))
            if not co or not gp:
                continue
            if not (co["correct"] and gp["correct"]):
                continue
            paired.append({
                "scen": scen,
                "dcost": gp["cost_usd"] - co["cost_usd"],
                "dcache": gp["cache_read"] - co["cache_read"],
                "dout": gp["total_output_tokens"] - co["total_output_tokens"],
                "dturns": gp["turns"] - co["turns"],
            })
        if paired:
            n = len(paired)
            out.append(f"\n  model={model}  N={n} paired scenarios")
            out.append(f"    mean dcost  (gp - co): ${sum(p['dcost'] for p in paired)/n:+.4f}")
            out.append(f"    mean dcache (gp - co): {sum(p['dcache'] for p in paired)/n:+.0f}")
            out.append(f"    mean dout   (gp - co): {sum(p['dout'] for p in paired)/n:+.0f}")
            out.append(f"    mean dturns (gp - co): {sum(p['dturns'] for p in paired)/n:+.1f}")

    # Subset paired deltas
    out.append("\n## Subset Paired Deltas")
    for cat in ("state_collision","source_logical","carryover"):
        out.append(f"\n### {cat}")
        for model in ("haiku","sonnet","opus"):
            paired = []
            for scen, rs in by_scen.items():
                if not rs:
                    continue
                if rs[0]["category"] != cat:
                    continue
                d = {(r["mode"], r["model"]): r for r in rs}
                co = d.get(("code_only", model))
                gp = d.get(("with_gpa", model))
                if not co or not gp:
                    continue
                if not (co["correct"] and gp["correct"]):
                    continue
                paired.append({
                    "dcost": gp["cost_usd"] - co["cost_usd"],
                    "dturns": gp["turns"] - co["turns"],
                })
            if paired:
                n = len(paired)
                out.append(f"  model={model}  N={n}  mean dcost "
                           f"${sum(p['dcost'] for p in paired)/n:+.4f}  "
                           f"mean dturns {sum(p['dturns'] for p in paired)/n:+.1f}")
            else:
                out.append(f"  model={model}  N=0 (no paired-correct)")

    # Opus unique wins
    out.append("\n## Opus Capability Ceiling")
    opus_only = []
    for scen, rs in by_scen.items():
        d = {(r["mode"], r["model"]): r["correct"] for r in rs}
        opus_solved = d.get(("code_only","opus"),False) or d.get(("with_gpa","opus"),False)
        son_solved = d.get(("code_only","sonnet"),False) or d.get(("with_gpa","sonnet"),False)
        haiku_solved = d.get(("code_only","haiku"),False) or d.get(("with_gpa","haiku"),False)
        if opus_solved and not son_solved and not haiku_solved:
            opus_only.append(scen)
    out.append(f"  Opus-only wins (Haiku+Sonnet both failed): {len(opus_only)}")
    for s in opus_only:
        out.append(f"    - {s}")
    # Sonnet > Opus (regressions)
    regressions = []
    for scen, rs in by_scen.items():
        d = {(r["mode"], r["model"]): r["correct"] for r in rs}
        opus_solved = any(d.get((m,"opus"),False) for m in ("code_only","with_gpa"))
        son_solved  = any(d.get((m,"sonnet"),False) for m in ("code_only","with_gpa"))
        if son_solved and not opus_solved:
            regressions.append(scen)
    out.append(f"  Sonnet-solved, Opus-failed (potential regression): {len(regressions)}")
    for s in regressions:
        out.append(f"    - {s}")

    text = "\n".join(out) + "\n"
    (RESULTS_DIR / "summary.txt").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
