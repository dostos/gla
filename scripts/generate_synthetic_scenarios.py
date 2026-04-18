"""Generate 100 synthetic adversarial OpenGPA eval scenarios.

Iterates through a taxonomy of (bug_class, capability) tuples and writes
each scenario to tests/eval/e<N>_<slug>/.  Uses the Claude Code CLI
backend (no API key needed).  Validates each via gcc -fsyntax-only before
committing to the repo.

Parallelism: runs up to N workers concurrently (default 4) to keep total
wall-clock time reasonable.  Each worker shells out to `claude -p` which is
30-120s per scenario.

Usage:
    PYTHONPATH=src/python python3 scripts/generate_synthetic_scenarios.py \
        --workers 4 --start-index 11 --count 100
"""
from __future__ import annotations

import argparse
import concurrent.futures
import re
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src" / "python"))

from gla.eval.curation.llm_client import ClaudeCodeLLMClient  # noqa: E402
from gla.eval.curation.synth_generator import (                  # noqa: E402
    SyntheticGenerator,
    SynthRequest,
)


# --------------------------------------------------------------------------
# Taxonomy: 100 (bug_class, capability, difficulty, principles) entries.
#
# Spread across the ~30 bug classes listed in the spec, hitting each of the
# six OpenGPA capabilities (inspect_drawcall, query_pixel, query_scene,
# query_frame, compare_frames, explain_pixel).

TAXONOMY: list[dict] = [
    # -- texture binding leaks (1-4) --------------------------------------
    {"bug_class": "state leak: GL_TEXTURE_2D binding from previous draw never rebound for a second mesh",
     "capability": "inspect_drawcall(dc_id=1, include=['textures']) shows the stale TEXTURE_BINDING_2D from the prior draw",
     "difficulty": 2,
     "principles": ["Stale state", "Absent code", "Implicit state machine"]},
    {"bug_class": "state leak: GL_TEXTURE_3D unit 0 still bound to volumetric texture while shader samples unit 1",
     "capability": "inspect_drawcall reveals active_texture=GL_TEXTURE0 plus TEXTURE_BINDING_3D=stale volume handle",
     "difficulty": 3,
     "principles": ["Stale state", "Off-by-one unit", "Cross-module leak"]},
    {"bug_class": "state leak: GL_TEXTURE_CUBE_MAP binding from skybox retained for terrain draw",
     "capability": "inspect_drawcall exposes TEXTURE_BINDING_CUBE_MAP still pointing at skybox id",
     "difficulty": 3,
     "principles": ["Stale state", "Module boundary leak"]},
    {"bug_class": "state leak: GL_TEXTURE_2D_ARRAY slice selection uniform reused, wrong layer sampled",
     "capability": "inspect_drawcall shows uniform uLayerIndex=7 when intended slice was 2",
     "difficulty": 3,
     "principles": ["Stale uniform", "Index confusion"]},

    # -- uniform leaks / lifecycle (5-10) ---------------------------------
    {"bug_class": "uniform value leaked: glUseProgram switch, old uTint still applied to new program due to shared name assumption",
     "capability": "inspect_drawcall displays uTint=previous_program_value on the current draw",
     "difficulty": 3,
     "principles": ["Stale state", "Implicit coupling"]},
    {"bug_class": "uniform lifecycle: glGetUniformLocation cached across glLinkProgram re-link, stale location used",
     "capability": "query_frame shows that the second draw uses a uniform location that no longer maps to its name",
     "difficulty": 4,
     "principles": ["Caching across invalidation", "Silent no-op"]},
    {"bug_class": "uniform type mismatch: glUniform1f used for a vec3 uniform, resulting in ignored set",
     "capability": "inspect_drawcall shows uniform remained at default zero vec3 while code believed it set a tint",
     "difficulty": 3,
     "principles": ["Silent no-op", "Type confusion"]},
    {"bug_class": "uniform wrong program: glUseProgram(A) set, glUniform called while B is the intended target",
     "capability": "inspect_drawcall shows uniform on program A was updated; program B still has default",
     "difficulty": 4,
     "principles": ["Wrong context", "Name-based ambiguity"]},
    {"bug_class": "uniform location -1 silently ignored because shader compiler optimized the uniform away",
     "capability": "inspect_drawcall shows uniform_location=-1 returned by glGetUniformLocation for the named uniform",
     "difficulty": 2,
     "principles": ["Silent no-op", "Dead-code elimination"]},
    {"bug_class": "uniform never uploaded because glUseProgram was called AFTER glUniform",
     "capability": "inspect_drawcall shows uniform at default value despite CPU code path calling glUniform with correct value",
     "difficulty": 3,
     "principles": ["Out-of-order ops", "Silent no-op"]},

    # -- depth (11-16) -----------------------------------------------------
    {"bug_class": "depth precision: near=0.001, far=10000 causes z-fighting between near-coplanar quads",
     "capability": "query_pixel(x,y) returns alternating colors across coplanar region; compare_frames shows flicker frame-to-frame",
     "difficulty": 4,
     "principles": ["Subtle numerics", "Platform-dependent"]},
    {"bug_class": "depth test: GL_GREATER set with standard perspective; back faces occlude front faces",
     "capability": "inspect_drawcall shows depth_func=GL_GREATER and back-to-front ordering producing incorrect occlusion",
     "difficulty": 3,
     "principles": ["Inverted predicate", "State pollution"]},
    {"bug_class": "depth write disabled (GL_FALSE) for opaque geometry; later draws incorrectly pass depth test",
     "capability": "inspect_drawcall shows depth_mask=GL_FALSE while depth_test=GL_TRUE on opaque pass",
     "difficulty": 3,
     "principles": ["Mismatched flags", "Legacy state leak"]},
    {"bug_class": "reversed-Z expected but projection matrix still produces [0,1] depth range",
     "capability": "inspect_drawcall shows projection matrix entries inconsistent with clip_control/reversed-Z assumption",
     "difficulty": 5,
     "principles": ["Convention mismatch", "Hidden assumption"]},
    {"bug_class": "glDepthRange set to (1,0) but depth test is GL_LESS: nothing visible",
     "capability": "query_scene returns depth_range=[1,0] which contradicts standard less-than depth test",
     "difficulty": 4,
     "principles": ["Inverted range", "Compensating errors"]},
    {"bug_class": "depth buffer not cleared between frames; previous frame depth blocks current frame's draws",
     "capability": "compare_frames(0,1) shows second frame missing pixels where frame 0's closer geometry persists",
     "difficulty": 3,
     "principles": ["Missing clear", "Accumulated state"]},

    # -- culling (17-20) ---------------------------------------------------
    {"bug_class": "culling: mesh authored CW under default GL_CCW front-face; all faces culled",
     "capability": "inspect_drawcall shows front_face=GL_CCW and cull_face=GL_BACK with CW-wound vertex data",
     "difficulty": 2,
     "principles": ["Winding convention", "Invisible geometry"]},
    {"bug_class": "culling: model matrix has scale=-1 on X; winding flips and back-face culling removes all triangles",
     "capability": "inspect_drawcall shows model matrix with negative determinant while cull_face=GL_BACK",
     "difficulty": 4,
     "principles": ["Hidden determinant flip", "Matrix composition subtlety"]},
    {"bug_class": "culling: glFrontFace(GL_CW) was set during debug and never reset; subsequent draws invisible",
     "capability": "inspect_drawcall reveals front_face=GL_CW when the engine assumes GL_CCW",
     "difficulty": 3,
     "principles": ["Debug state leak", "Module boundary leak"]},
    {"bug_class": "culling: GL_FRONT_AND_BACK culled — every triangle discarded",
     "capability": "inspect_drawcall shows cull_face_mode=GL_FRONT_AND_BACK; no fragments generated",
     "difficulty": 2,
     "principles": ["Over-enabled state", "Silent nothing"]},

    # -- stencil (21-23) ---------------------------------------------------
    {"bug_class": "stencil test leaked from a UI pass; main geometry fails stencil reference everywhere",
     "capability": "inspect_drawcall shows stencil_test=GL_TRUE, stencil_func=GL_EQUAL, ref=1 on a 3D draw",
     "difficulty": 4,
     "principles": ["Cross-pass state leak", "Invisible failure mode"]},
    {"bug_class": "stencil: glStencilFunc(GL_NEVER, 0, 0xFF) set accidentally; no pixels pass",
     "capability": "inspect_drawcall reveals stencil_func=GL_NEVER, so nothing is written",
     "difficulty": 2,
     "principles": ["Wrong predicate", "Total occlusion"]},
    {"bug_class": "stencil mask=0 on write; attempts to update stencil are silently no-ops",
     "capability": "inspect_drawcall shows stencil_write_mask=0 at the clear-stencil draw",
     "difficulty": 4,
     "principles": ["Silent no-op", "Masked update"]},

    # -- scissor / viewport (24-28) ---------------------------------------
    {"bug_class": "scissor rect from UI pass applied to full-screen 3D pass; content clipped to corner",
     "capability": "inspect_drawcall shows scissor_test=true, scissor_box=(0,0,200,100) on a 800x600 target",
     "difficulty": 3,
     "principles": ["Cross-pass leak", "Clipped output"]},
    {"bug_class": "scissor y axis computed as (height - y - h) but engine expects GL bottom-left origin differently",
     "capability": "inspect_drawcall shows scissor_box placing the cutout in the wrong vertical position",
     "difficulty": 3,
     "principles": ["Y-axis convention", "Coordinate origin confusion"]},
    {"bug_class": "viewport not reset after shadow pass; main render uses shadow-map-sized viewport",
     "capability": "inspect_drawcall shows viewport=(0,0,1024,1024) on the main-render draw (framebuffer is 800x600)",
     "difficulty": 3,
     "principles": ["Cross-pass leak", "Missing restore"]},
    {"bug_class": "sub-viewport split-screen: secondary view uses half width but full width in draw",
     "capability": "query_pixel on the right split shows geometry from the left split bleeding over",
     "difficulty": 3,
     "principles": ["Half-enabled feature", "Geometry bleed"]},
    {"bug_class": "glViewport width/height swapped after window resize callback",
     "capability": "inspect_drawcall shows viewport=(0,0,height,width) producing squashed render",
     "difficulty": 3,
     "principles": ["Axis swap", "Resize callback bug"]},

    # -- blending (29-33) --------------------------------------------------
    {"bug_class": "blend func (GL_ONE, GL_ONE) used for normal alpha blend; bright additive overlay result",
     "capability": "inspect_drawcall shows blend_src=GL_ONE, blend_dst=GL_ONE on a draw that intended GL_SRC_ALPHA + GL_ONE_MINUS_SRC_ALPHA",
     "difficulty": 2,
     "principles": ["Wrong blend func", "Over-bright result"]},
    {"bug_class": "blending disabled for transparent decals; alpha ignored and hard edges appear",
     "capability": "inspect_drawcall shows GL_BLEND=GL_FALSE while fragments have alpha<1",
     "difficulty": 2,
     "principles": ["Disabled required feature", "Hard edges"]},
    {"bug_class": "glBlendEquation(GL_MIN) set instead of GL_FUNC_ADD; draws are darkened",
     "capability": "inspect_drawcall shows blend_equation=GL_MIN",
     "difficulty": 3,
     "principles": ["Wrong equation", "Darkened output"]},
    {"bug_class": "blend func for RGB differs from alpha, but using non-separate glBlendFunc overwrites both",
     "capability": "inspect_drawcall shows blend_src_alpha mismatched with intent (unified rather than separate)",
     "difficulty": 4,
     "principles": ["Separate-vs-unified", "Hidden default"]},
    {"bug_class": "premultiplied alpha texture blended with (SRC_ALPHA, ONE_MINUS_SRC_ALPHA): double multiply",
     "capability": "query_pixel shows darker-than-expected color around the alpha fringe",
     "difficulty": 4,
     "principles": ["Premultiplication confusion", "Double apply"]},

    # -- vertex attributes (34-39) ----------------------------------------
    {"bug_class": "vertex attribute: uint8 color data read as GL_FLOAT; garbage positions",
     "capability": "inspect_drawcall shows vertex_attrib[1] type=GL_FLOAT when source data is GL_UNSIGNED_BYTE",
     "difficulty": 3,
     "principles": ["Type mismatch", "Byte reinterpretation"]},
    {"bug_class": "vertex attribute: stride set to sizeof(float)*3 when vertex is actually 8 floats (pos+normal+uv)",
     "capability": "inspect_drawcall shows vertex_attrib stride=12 bytes while vertex layout is 32 bytes",
     "difficulty": 3,
     "principles": ["Stride mismatch", "Aliased reads"]},
    {"bug_class": "vertex attribute offset off by sizeof(float) — UVs read from normal slot",
     "capability": "inspect_drawcall shows vertex_attrib[2].offset=4 bytes too small",
     "difficulty": 4,
     "principles": ["Off-by-one offset", "Attribute scramble"]},
    {"bug_class": "vertex attribute not enabled (glEnableVertexAttribArray forgotten); attribute reads zero",
     "capability": "inspect_drawcall shows vertex_attrib[1].enabled=false while program expects it bound",
     "difficulty": 3,
     "principles": ["Absent call", "Default zero"]},
    {"bug_class": "two vertex attributes both bound to location 0; second overwrites the first",
     "capability": "inspect_drawcall shows two active attributes mapped to location 0",
     "difficulty": 4,
     "principles": ["Binding collision", "Overwrite"]},
    {"bug_class": "glVertexAttribDivisor set to 1 on per-vertex attribute; instance drawing messes up",
     "capability": "inspect_drawcall shows attribute divisor=1 when intended per-vertex (divisor=0)",
     "difficulty": 4,
     "principles": ["Wrong divisor", "Instancing confusion"]},

    # -- index buffer (40-43) ---------------------------------------------
    {"bug_class": "index buffer: glDrawElements count=sizeof(indices) instead of array length",
     "capability": "inspect_drawcall shows element_count=N*4 (bytes) rather than N (ushort entries)",
     "difficulty": 3,
     "principles": ["sizeof vs length", "Byte confusion"]},
    {"bug_class": "index buffer: GL_UNSIGNED_SHORT spec used with GL_UNSIGNED_INT data",
     "capability": "inspect_drawcall shows index_type=GL_UNSIGNED_SHORT while EBO was populated with 32-bit ints",
     "difficulty": 4,
     "principles": ["Type mismatch", "Silent misread"]},
    {"bug_class": "index buffer: out-of-range indices cause undefined-value reads; some tris missing",
     "capability": "inspect_drawcall exposes max(indices)=<n+5> while vertex_count=<n>",
     "difficulty": 4,
     "principles": ["OOB access", "Undefined memory"]},
    {"bug_class": "index buffer was bound to GL_ARRAY_BUFFER instead of GL_ELEMENT_ARRAY_BUFFER",
     "capability": "inspect_drawcall shows ELEMENT_ARRAY_BUFFER binding=0 while vertex array has no EBO attached",
     "difficulty": 4,
     "principles": ["Wrong target", "Silent default"]},

    # -- framebuffer (44-47) -----------------------------------------------
    {"bug_class": "framebuffer: wrong FBO bound during geometry pass; draws went to gbuffer instead of main",
     "capability": "inspect_drawcall shows DRAW_FRAMEBUFFER_BINDING = gbuffer while code intended main",
     "difficulty": 4,
     "principles": ["Wrong target", "Multi-pass confusion"]},
    {"bug_class": "framebuffer feedback loop: color attachment texture also bound as sampler",
     "capability": "inspect_drawcall shows the same texture id appearing in both sampler_binding and color_attachment",
     "difficulty": 5,
     "principles": ["Feedback loop", "UB zone"]},
    {"bug_class": "framebuffer incomplete: depth attachment missing while depth test is enabled",
     "capability": "inspect_drawcall reports framebuffer_status=GL_FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT",
     "difficulty": 3,
     "principles": ["Incomplete FBO", "Silent GL error"]},
    {"bug_class": "framebuffer not restored to 0 (default) after post-processing pass; blit goes to screen but draw didn't",
     "capability": "inspect_drawcall shows DRAW_FRAMEBUFFER_BINDING != 0 for the final swap-surface draw",
     "difficulty": 4,
     "principles": ["Missing restore", "Multi-pass state leak"]},

    # -- NaN / numerics (48-51) -------------------------------------------
    {"bug_class": "NaN: matrix inversion of a zero-scale matrix produces Inf; normal matrix propagates NaN",
     "capability": "inspect_drawcall shows uNormalMatrix containing Inf/NaN entries",
     "difficulty": 4,
     "principles": ["Silent numerical failure", "Causal distance"]},
    {"bug_class": "NaN: normalize(vec3(0)) in vertex shader; lighting result is NaN",
     "capability": "query_pixel returns (0,0,0,1) in lit region; inspect_drawcall shows normal uniform is fine — bug is shader-local",
     "difficulty": 5,
     "principles": ["Shader NaN", "Implementation-defined NaN"]},
    {"bug_class": "NaN: perspective divide by w=0 at a degenerate vertex; infinite position clipped oddly",
     "capability": "compare_frames(0,1) shows flicker as NaN tris appear/disappear",
     "difficulty": 5,
     "principles": ["Degenerate geometry", "Implementation-defined clipping"]},
    {"bug_class": "uniform uploaded as NaN because sqrt(negative) on CPU; then fragments go black",
     "capability": "inspect_drawcall shows uniform fAmbient=nan",
     "difficulty": 3,
     "principles": ["CPU-side math bug", "NaN propagation"]},

    # -- projection/view/model matrices (52-59) ---------------------------
    {"bug_class": "projection: glmPerspective FOV 60 passed in degrees to a radians-expecting function",
     "capability": "query_scene returns camera.fov_y_rad=60 (should be ~1.05)",
     "difficulty": 3,
     "principles": ["Unit confusion", "Radians-vs-degrees"]},
    {"bug_class": "projection: aspect ratio = height/width (swapped); image stretched",
     "capability": "query_scene returns camera.aspect_ratio=0.75 when framebuffer is 4:3",
     "difficulty": 3,
     "principles": ["Axis swap", "Ratio inversion"]},
    {"bug_class": "projection: left-handed matrix in a right-handed engine; Z flipped, nothing visible",
     "capability": "query_scene shows projection.handedness=LH while view/model assume RH",
     "difficulty": 5,
     "principles": ["Convention mismatch", "Invisible geometry"]},
    {"bug_class": "view matrix: used the camera's model matrix directly without inverting",
     "capability": "query_scene returns view = model (no inverse); world appears to move with camera",
     "difficulty": 4,
     "principles": ["Missing inverse", "Matrix role confusion"]},
    {"bug_class": "view matrix: look-at up vector (0,0,1) used while engine is Y-up; camera banked 90°",
     "capability": "query_scene returns camera.up=(0,0,1) not (0,1,0)",
     "difficulty": 3,
     "principles": ["Axis convention", "Engine-wide"]},
    {"bug_class": "model matrix: order is S*R*T instead of T*R*S; scale applied after translation shifts origin",
     "capability": "query_scene returns model matrix with scale applied post-translate",
     "difficulty": 4,
     "principles": ["Matrix multiplication order", "Transform composition"]},
    {"bug_class": "normal matrix used model matrix directly (not inverse-transpose); non-uniform scale breaks lighting",
     "capability": "inspect_drawcall shows uNormalMatrix == mat3(uModel) even though model has non-uniform scale",
     "difficulty": 4,
     "principles": ["Wrong matrix for normals", "Non-uniform scale"]},
    {"bug_class": "orthographic matrix used where perspective expected; no foreshortening, odd near-plane behavior",
     "capability": "query_scene returns projection with w-preserving structure (orthographic) where perspective expected",
     "difficulty": 3,
     "principles": ["Wrong projection kind", "Plausible intent"]},

    # -- alpha / transparency (60-62) -------------------------------------
    {"bug_class": "alpha sort: transparent objects drawn in creation order (back to front not enforced)",
     "capability": "query_frame drawcalls show transparent meshes not sorted by z",
     "difficulty": 4,
     "principles": ["Missing sort", "Order-dependent blend"]},
    {"bug_class": "alpha test threshold 0.5 rejects foliage that has mostly 0.3 alpha; most pixels missing",
     "capability": "inspect_drawcall reveals uAlphaCutoff=0.5 while texture alpha histogram peaks at 0.3",
     "difficulty": 3,
     "principles": ["Threshold mismatch", "Invisible geometry"]},
    {"bug_class": "transparent object drawn before opaque, writing depth and blocking opaque behind it",
     "capability": "explain_pixel(x,y) shows transparent draw wrote the depth of that pixel, blocking opaque",
     "difficulty": 5,
     "principles": ["Draw order", "Depth-write transparency"]},

    # -- color space / gamma (63-65) --------------------------------------
    {"bug_class": "sRGB texture uploaded as GL_RGBA8 (linear); samples look too dark",
     "capability": "inspect_drawcall shows texture.internal_format=GL_RGBA8 while content is sRGB",
     "difficulty": 3,
     "principles": ["Color space mismatch", "Wrong internal format"]},
    {"bug_class": "gamma applied on CPU AND fragment shader; doubled; output too bright",
     "capability": "query_pixel on gray swatch returns 0.73 sRGB where 0.5 was intended",
     "difficulty": 4,
     "principles": ["Double apply", "Pipeline duplication"]},
    {"bug_class": "framebuffer is GL_SRGB8_ALPHA8 but user writes already-gamma-encoded color; double encode",
     "capability": "inspect_drawcall shows framebuffer is sRGB AND shader outputs pow(c, 1/2.2)",
     "difficulty": 5,
     "principles": ["Hidden double encode", "Wrong assumption about target"]},

    # -- texture filtering / mip (66-70) ----------------------------------
    {"bug_class": "min_filter=GL_LINEAR_MIPMAP_LINEAR but no mipmaps generated; texture appears as default zero",
     "capability": "inspect_drawcall shows texture.min_filter uses mipmaps but texture.num_levels=1",
     "difficulty": 3,
     "principles": ["Incomplete texture", "Silent default color"]},
    {"bug_class": "wrap mode GL_REPEAT used on tile that has non-tileable edges; seams visible",
     "capability": "query_pixel along tile boundary shows sharp color discontinuity",
     "difficulty": 3,
     "principles": ["Wrap mismatch", "Subtle seam"]},
    {"bug_class": "texture dimensions uploaded with width=0 due to truncated read; draw gets zero-texel samples",
     "capability": "inspect_drawcall shows texture dimensions 0x256",
     "difficulty": 3,
     "principles": ["Corrupt metadata", "Silent failure"]},
    {"bug_class": "texture format GL_RED (single channel) read as vec4 in shader: xyz all come from red channel",
     "capability": "inspect_drawcall shows texture.format=GL_RED while shader samples .xyz",
     "difficulty": 3,
     "principles": ["Channel mismatch", "Plausible looks-ok"]},
    {"bug_class": "mipmap auto-generate not called; trilinear filter reads from undefined levels",
     "capability": "inspect_drawcall shows texture has base level only; min_filter uses mipmaps",
     "difficulty": 4,
     "principles": ["Absent call", "UB region"]},

    # -- instancing (71-72) ------------------------------------------------
    {"bug_class": "instancing: glDrawArraysInstanced drew N-1 instances (off-by-one on count)",
     "capability": "inspect_drawcall shows instance_count=9 when the scene requested 10",
     "difficulty": 3,
     "principles": ["Off-by-one", "Hidden omission"]},
    {"bug_class": "instancing: divisor=0 for per-instance color; all instances share the same color",
     "capability": "inspect_drawcall shows per-instance attribute divisor=0",
     "difficulty": 4,
     "principles": ["Wrong divisor", "Instance collapse"]},

    # -- multi-pass (73-75) ------------------------------------------------
    {"bug_class": "multi-pass: pass-1 uniform uTime not re-set for pass-2; pass-2 uses stale time",
     "capability": "compare_frames shows pass-2 animation frozen compared to expected",
     "difficulty": 3,
     "principles": ["Uniform reuse", "Animation freeze"]},
    {"bug_class": "multi-pass: pass-1 FBO still bound for pass-2; pass-2 renders into the wrong target",
     "capability": "inspect_drawcall on pass-2 shows DRAW_FRAMEBUFFER_BINDING=pass1_fbo",
     "difficulty": 4,
     "principles": ["Missing restore", "Target confusion"]},
    {"bug_class": "post-processing: ping-pong FBOs swapped twice; output comes from input",
     "capability": "compare_frames(0,1) identical; explain_pixel shows postFX effectively no-op",
     "difficulty": 4,
     "principles": ["Double swap", "Identity pipeline"]},

    # -- glClear (76-78) ---------------------------------------------------
    {"bug_class": "glClear not called; previous frame's content accumulates with new draws",
     "capability": "compare_frames(0,1) shows frame 1 contains frame 0 content merged with new draws",
     "difficulty": 2,
     "principles": ["Absent call", "Accumulated state"]},
    {"bug_class": "glClear only cleared color, not depth; depth buffer accumulates across frames",
     "capability": "inspect_drawcall shows GL_CLEAR called with only COLOR_BUFFER_BIT mask",
     "difficulty": 3,
     "principles": ["Partial clear", "Depth persists"]},
    {"bug_class": "glClearColor G component forgotten (zero); intended gray comes out red",
     "capability": "query_pixel on clear area returns (0.5, 0.0, 0.5, 1.0)",
     "difficulty": 2,
     "principles": ["Parameter typo", "Off-channel"]},

    # -- buffer targets / state (79-81) -----------------------------------
    {"bug_class": "buffer target mix-up: glBufferSubData to GL_ARRAY_BUFFER while EBO was meant",
     "capability": "inspect_drawcall shows EBO contents unchanged; VBO now contains index-like bytes",
     "difficulty": 4,
     "principles": ["Wrong target", "Data mis-routed"]},
    {"bug_class": "polygon mode set to GL_LINE during debug and never reset; wireframe in release",
     "capability": "inspect_drawcall shows polygon_mode=GL_LINE on release-build frame",
     "difficulty": 2,
     "principles": ["Debug leak", "Visible symptom"]},
    {"bug_class": "glEnable(GL_SCISSOR_TEST) without glScissor set: default scissor rect (0,0,0,0) clips everything",
     "capability": "inspect_drawcall shows scissor_test=true and scissor_box=(0,0,0,0)",
     "difficulty": 3,
     "principles": ["Unset parameter", "Invisible output"]},

    # -- shader outputs (82-84) -------------------------------------------
    {"bug_class": "fragment shader writes only red channel of gl_FragColor; green/blue remain zero",
     "capability": "query_pixel in lit region returns (1,0,0,1); inspect_drawcall confirms shader source writes vec4(c.r,0,0,1)",
     "difficulty": 2,
     "principles": ["Incomplete write", "Color channel bug"]},
    {"bug_class": "MRT: fragment shader writes gl_FragData[0] only; attachment 1 has garbage / default zero",
     "capability": "inspect_drawcall shows draw has 2 color attachments; shader outputs only one",
     "difficulty": 4,
     "principles": ["Incomplete MRT", "Silent attachment skip"]},
    {"bug_class": "fragment shader forgets to output (no gl_FragColor assignment); framebuffer gets default zero",
     "capability": "query_pixel returns (0,0,0,1) across draw; inspect_drawcall shows shader source has no output write",
     "difficulty": 3,
     "principles": ["Absent write", "Missing output"]},

    # -- point / line (85) -------------------------------------------------
    {"bug_class": "point size not set; default 1px points invisible on high-DPI display",
     "capability": "inspect_drawcall shows GL_POINT_SIZE=1.0 with draw_mode=GL_POINTS",
     "difficulty": 3,
     "principles": ["Default tiny size", "DPI blind spot"]},

    # -- color channel / write mask (86-87) -------------------------------
    {"bug_class": "glColorMask(GL_FALSE, GL_TRUE, GL_TRUE, GL_TRUE) left from a shadow trick; red never written",
     "capability": "inspect_drawcall shows color_write_mask=(false, true, true, true)",
     "difficulty": 4,
     "principles": ["State leak", "Masked output"]},
    {"bug_class": "glDrawBuffer set to GL_NONE from prior depth-only pass; subsequent color writes no-op",
     "capability": "inspect_drawcall shows draw_buffer=GL_NONE on a color-writing draw",
     "difficulty": 5,
     "principles": ["Cross-pass leak", "Silent no-op"]},

    # -- error-ignoring (88-89) -------------------------------------------
    {"bug_class": "glGetError not checked; INVALID_ENUM from glUniform-on-wrong-type propagates silently",
     "capability": "query_frame shows a pending GL error that the app never consumed",
     "difficulty": 3,
     "principles": ["Ignored error", "Silent bug"]},
    {"bug_class": "GL context not current on thread; all GL calls are no-ops until fixed",
     "capability": "query_frame reports zero drawcalls recorded because no context was current",
     "difficulty": 3,
     "principles": ["Missing context", "Silent no-op"]},

    # -- mrt / gbuffer (90-91) --------------------------------------------
    {"bug_class": "glDrawBuffers never called; MRT shader writes color0 only, attachments 1-3 stay clear",
     "capability": "inspect_drawcall shows draw_buffers=[GL_BACK] on FBO with 4 color attachments",
     "difficulty": 4,
     "principles": ["MRT config", "Setup omission"]},
    {"bug_class": "attachment 1 has wrong internal format (GL_R8) for normals intended GL_RGB16F; truncation",
     "capability": "inspect_drawcall shows color_attachment[1].internal_format=GL_R8 with RGB data uploaded",
     "difficulty": 4,
     "principles": ["Wrong format", "Silent truncation"]},

    # -- BufferSubData / PBO (92) -----------------------------------------
    {"bug_class": "glBufferSubData range exceeds buffer size silently; driver discards writes beyond end",
     "capability": "inspect_drawcall shows buffer size < (offset+size) of last subdata call",
     "difficulty": 4,
     "principles": ["OOB write", "Silent discard"]},

    # -- coordinate / origin (93) -----------------------------------------
    {"bug_class": "glReadPixels uses top-left origin mental model; actual GL is bottom-left; vertical flip",
     "capability": "query_pixel(0, H-1) returns the top-row color rather than the bottom-row color",
     "difficulty": 3,
     "principles": ["Y-axis convention", "Origin confusion"]},

    # -- texture unit (94-95) ---------------------------------------------
    {"bug_class": "sampler uniform never set: defaults to 0 but texture was bound to unit 3",
     "capability": "inspect_drawcall shows sampler uniform uTex=0 while texture is bound to TEXTURE_UNIT=3",
     "difficulty": 3,
     "principles": ["Silent default", "Wrong unit"]},
    {"bug_class": "glActiveTexture set to GL_TEXTURE2 but glBindTexture subsequently bound without reactivating",
     "capability": "inspect_drawcall shows sampler path mapping to TEXTURE2 while intended TEXTURE0",
     "difficulty": 4,
     "principles": ["Active unit sticky", "Module boundary"]},

    # -- race / ordering (96) ---------------------------------------------
    {"bug_class": "glTexSubImage2D uploaded right before draw; driver async path shows stale content for first frame",
     "capability": "compare_frames(0,1) shows frame 0 stale, frame 1 correct",
     "difficulty": 4,
     "principles": ["Upload-draw race", "First-frame anomaly"]},

    # -- GLSL precision (97) ----------------------------------------------
    {"bug_class": "GLSL precision mediump vec3 position for large world coordinates; jitter at distance",
     "capability": "query_pixel shows precision-related flicker near edges; inspect_drawcall shows mediump declaration",
     "difficulty": 5,
     "principles": ["Precision loss", "Mobile-specific"]},

    # -- depth-stencil interaction (98) -----------------------------------
    {"bug_class": "depth-stencil attachment is separate depth + separate stencil; stencil writes lost",
     "capability": "inspect_drawcall shows depth_attachment != stencil_attachment (expected combined D24S8)",
     "difficulty": 5,
     "principles": ["Attachment topology", "Hidden constraint"]},

    # -- swizzle / texture binding (99) -----------------------------------
    {"bug_class": "texture swizzle mask RGBA→RRRR applied for grayscale optimization, carried over to color texture",
     "capability": "inspect_drawcall shows texture.swizzle=(R,R,R,R) on a color texture",
     "difficulty": 4,
     "principles": ["Swizzle leak", "Perceptual monochrome"]},

    # -- primitive restart (100) ------------------------------------------
    {"bug_class": "primitive restart index 0xFFFFFFFF configured but indices use 0xFFFF (ushort); restart triggers unexpectedly",
     "capability": "inspect_drawcall shows primitive_restart_index=0xFFFFFFFF with index_type=GL_UNSIGNED_SHORT",
     "difficulty": 5,
     "principles": ["Type-width mismatch", "Restart confusion"]},
]


# --------------------------------------------------------------------------


def slugify(text: str, maxlen: int = 60) -> str:
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:maxlen].strip("_")


def gcc_syntax_check(main_c: str, timeout: int = 30) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "main.c"
        f.write_text(main_c)
        try:
            proc = subprocess.run(
                ["gcc", "-Wall", "-std=gnu11", "-fsyntax-only", str(f)],
                capture_output=True, text=True, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            return False, "gcc timed out"
        if proc.returncode == 0:
            return True, ""
        return False, (proc.stderr or proc.stdout)[:500]


def generate_one(
    spec: dict, scenario_num: int, eval_dir: Path, retries: int = 2
) -> tuple[str, bool, str]:
    """Return (scenario_dir_name, success, message)."""
    bug_class: str = spec["bug_class"]
    capability: str = spec["capability"]
    difficulty: int = spec["difficulty"]
    principles: list[str] = spec["principles"]

    slug = slugify(bug_class)
    scenario_id_short = f"e{scenario_num}"
    scenario_id_full = f"{scenario_id_short}_{slug}" if slug else scenario_id_short
    scen_dir = eval_dir / scenario_id_full

    if scen_dir.exists():
        return scenario_id_full, True, "exists"

    llm = ClaudeCodeLLMClient(timeout=600)
    gen = SyntheticGenerator(llm_client=llm)

    last_err = ""
    for attempt in range(retries + 1):
        try:
            req = SynthRequest(
                scenario_id=scenario_id_full,
                bug_class=bug_class,
                capability=capability,
                difficulty=difficulty,
                adversarial_principles=principles,
            )
            result = gen.generate(req)

            # Identify the main .c source
            c_files = {n: c for n, c in result.files.items() if n.endswith(".c")}
            main_c = result.files.get("main.c") or next(iter(c_files.values()))

            ok, err = gcc_syntax_check(main_c)
            if not ok:
                last_err = f"gcc: {err}"
                if attempt < retries:
                    time.sleep(1)
                    continue
                return scenario_id_full, False, last_err

            scen_dir.mkdir(parents=True, exist_ok=True)
            for name, content in result.files.items():
                if "/" in name or name.startswith(".."):
                    continue
                (scen_dir / name).write_text(content)
            return scenario_id_full, True, "ok"
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            if attempt < retries:
                time.sleep(1)
                continue
            return scenario_id_full, False, last_err

    return scenario_id_full, False, last_err


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--start-index", type=int, default=11)
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--indices", type=str, default=None,
                    help="Comma-separated list of 0-based taxonomy indices to run "
                         "(overrides --count)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    eval_dir = REPO / "tests" / "eval"
    if not eval_dir.is_dir():
        print(f"eval dir not found: {eval_dir}", file=sys.stderr)
        return 2

    if args.indices:
        idxs = [int(x) for x in args.indices.split(",") if x.strip()]
    else:
        idxs = list(range(min(args.count, len(TAXONOMY))))

    if args.dry_run:
        for i in idxs:
            spec = TAXONOMY[i]
            scen_num = args.start_index + i
            slug = slugify(spec["bug_class"])
            print(f"e{scen_num}_{slug}")
        print(f"---\nDry run: {len(idxs)} scenarios queued")
        return 0

    t0 = time.time()
    ok = []
    failed = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {}
        for i in idxs:
            spec = TAXONOMY[i]
            scen_num = args.start_index + i
            fut = ex.submit(generate_one, spec, scen_num, eval_dir)
            futures[fut] = (i, scen_num)

        done_count = 0
        total = len(futures)
        for fut in concurrent.futures.as_completed(futures):
            i, scen_num = futures[fut]
            done_count += 1
            try:
                scen_name, success, msg = fut.result()
            except Exception as e:  # noqa: BLE001
                scen_name = f"e{scen_num}"
                success = False
                msg = f"uncaught: {e}\n{traceback.format_exc()[:400]}"
            elapsed = time.time() - t0
            status = "OK" if success else "FAIL"
            print(f"[{done_count}/{total}] [{elapsed:6.1f}s] {status} {scen_name}: {msg[:160]}",
                  flush=True)
            (ok if success else failed).append((scen_name, msg))

    print("---")
    print(f"Total: {len(ok)+len(failed)}  OK: {len(ok)}  FAIL: {len(failed)}")
    if failed:
        print("Failures:")
        for name, msg in failed:
            print(f"  {name}: {msg[:200]}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
