#!/bin/bash
# Usage: run_subagent.sh <scenario> <mode> <model> <frame_id>
# Writes JSON result to /tmp/eval_round6/<scenario>_<mode>_<model>.json
set -u

SCENARIO=$1
MODE=$2
MODEL=$3
FRAME_ID=$4

# Snapshot mapping: scenario -> upstream source root
case "$SCENARIO" in
  r12_omniscale_cleanedge_scaling_issues)           SNAP="" ;;  # Pixelorama — shaders only, embed in report
  r23_using_multiple_alphamask_s_with_renderma)     SNAP="/data3/opengpa-snapshots/pixijs" ;;
  r24_enabling_autogeneratemipmaps_breaks_filt)     SNAP="/data3/opengpa-snapshots/pixijs" ;;
  r25_filters_with_backbuffers_seem_not_to_wor)     SNAP="/data3/opengpa-snapshots/pixijs" ;;
  r26_incorrect_behavior_in_colormatrixfilter_)     SNAP="/data3/opengpa-snapshots/pixijs" ;;
  r27_bug_black_squares_appear_when_rendering_)     SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__1f2fea769315" ;;
  r29_add_an_animated_icon_to_the_map_not_work)     SNAP="/data3/opengpa-snapshots/github_com__mapbox__mapbox-gl-js__97fc828fc04e" ;;
  r30_incomplete_lines_problem_with_mixing_lay)     SNAP="/data3/opengpa-snapshots/github_com__mapbox__mapbox-gl-js__97fc828fc04e" ;;
  r33_latest_build_6_38_1_got_glitchy_opacity_)     SNAP="/data3/opengpa-snapshots/postprocessing" ;;
  r34_depth_buffer_issue_when_using_depthoffie)     SNAP="/data3/opengpa-snapshots/postprocessing" ;;
  r32_v7_issue_with_custom_points_shader_three)     SNAP="/data3/opengpa-snapshots/postprocessing" ;;
  r28_bug_in_rendering_glb_models)                  SNAP="/data3/opengpa-snapshots/github_com__mapbox__mapbox-gl-js__97fc828fc04e" ;;
  r15_unrealbloompass_produces_no_visible_outp)     SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__1f2fea769315" ;;
  r20_three_js_meshdepthmaterial_depth_map_not)     SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__1f2fea769315" ;;
  r22_point_sprite_rendering_issues_with_three)     SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__1f2fea769315" ;;
  r24_artifacts_when_rendering_both_sides_of_a)     SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__1f2fea769315" ;;
  r11_three_js_effectcomposer_browser_window_r)     SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__1f2fea769315" ;;
  r15_post_effects_and_transparent_background_)     SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__1f2fea769315" ;;
  r3_material_shines_through_when_zooming_out)      SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__1f2fea769315" ;;
  r25_three_js_transparency_disparition)            SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__1f2fea769315" ;;
  *) echo "unknown scenario $SCENARIO"; exit 1 ;;
esac

SCEN_DIR="/home/jingyulee/gh/gla/tests/eval/$SCENARIO"
REPORT=$(sed -n '/^## User Report$/,/^## /p' "$SCEN_DIR/scenario.md" | head -n -1)
if [ -z "$REPORT" ]; then
    REPORT=$(awk '/^## Ground Truth/{exit} 1' "$SCEN_DIR/scenario.md")
fi

OUT=/tmp/eval_round6/${SCENARIO}_${MODE}_${MODEL}.json

# Source the live session so subagents inherit GPA_TOKEN/GPA_PORT
export PATH=/home/jingyulee/gh/gla/bin:$PATH
export GPA_PYTHON=/home/jingyulee/.cache/bazel/_bazel_jingyulee/97df310dd69562eef617a1c4f9fefa27/external/rules_python~~python~python_3_11_x86_64-unknown-linux-gnu/bin/python3.11
eval "$(gpa env)"

TMPPROMPT=/tmp/eval_round6/${SCENARIO}_${MODE}_${MODEL}.prompt
cat > "$TMPPROMPT" <<EOF
You are diagnosing a real-world graphics rendering bug. Your goal is to identify the root cause.

# Bug Report (user-facing)
$REPORT

# Resources available
EOF

if [ -n "$SNAP" ]; then
cat >> "$TMPPROMPT" <<EOF
- Upstream framework source code at: $SNAP
  Use Read and Grep to inspect any file under this directory. Note: this snapshot may not be the exact same commit as the bug report, but it contains the relevant subsystems.
EOF
else
cat >> "$TMPPROMPT" <<EOF
- Scenario source at: $SCEN_DIR (shader files and repro may be present).
EOF
fi

if [ "$MODE" = "with_gpa" ]; then
cat >> "$TMPPROMPT" <<EOF
- OpenGPA live capture of the rendered frame. A reproduction has been captured as frame #$FRAME_ID.
  The \`gpa\` CLI is on PATH and the live session env is already set (GPA_TOKEN=$GPA_TOKEN, GPA_PORT=$GPA_PORT).
  Preferred first call:
    gpa report --frame $FRAME_ID --json
      — runs every diagnostic check in one call (feedback loops, NaN uniforms,
        missing clears, empty capture). Only drill deeper if the report flags
        something.
  Drill-down when needed:
    gpa check <name> --frame $FRAME_ID [--dc N] --json
    gpa dump drawcalls --frame $FRAME_ID
    gpa dump drawcall  --frame $FRAME_ID --dc N
    gpa dump shader    --frame $FRAME_ID --dc N
    gpa dump textures  --frame $FRAME_ID --dc N
    gpa dump pixel     --frame $FRAME_ID --x X --y Y
  Raw REST fallback (equivalent to CLI):
    curl -sH "Authorization: Bearer \$GPA_TOKEN" http://127.0.0.1:\$GPA_PORT/api/v1/frames/$FRAME_ID/...
  Prefer ONE \`gpa report\` call over multiple inspect/curl queries.
  Note: the captured app is a minimal C/OpenGL repro of the same bug pattern, not the original framework. Use it as runtime evidence, then cross-reference with the framework source to explain why the original upstream code produces this bug.
EOF
fi

cat >> "$TMPPROMPT" <<EOF

# Approach
Use whatever approach you think is best to find the root cause. Be efficient — do not exhaustively read every file.

# Output
When done, output a SINGLE JSON object on the last line (no markdown, no trailing text) with this schema:
{
  "root_cause": "<1-2 sentence statement of the root cause>",
  "offending_symbol": "<function/file/field name where the bug lives, if identifiable>",
  "confidence": "high|medium|low",
  "framework_files_opened": <integer count of distinct framework source files you read>,
  "gpa_queries_made": <integer count of distinct GPA CLI or REST queries, 0 in code-only mode>,
  "reasoning": "<2-4 sentence chain explaining how you converged on the diagnosis>"
}
EOF

ALLOW="Read Grep Glob"
if [ "$MODE" = "with_gpa" ]; then
  ALLOW="Read Grep Glob Bash(curl:*) Bash(gpa:*)"
fi

MODELNAME="$MODEL"
case "$MODEL" in
  haiku) MODELNAME="claude-haiku-4-5" ;;
  sonnet) MODELNAME="claude-sonnet-4-5" ;;
esac

ADD_DIRS="--add-dir $SCEN_DIR"
if [ -n "$SNAP" ]; then
  ADD_DIRS="$ADD_DIRS --add-dir $SNAP"
fi

cd /tmp/eval_round6
timeout 900 claude -p \
  --model "$MODELNAME" \
  $ADD_DIRS \
  --allowedTools $ALLOW \
  --dangerously-skip-permissions \
  --output-format json \
  --max-turns ${MAX_TURNS:-40} \
  --no-session-persistence \
  "$(cat $TMPPROMPT)" > "$OUT" 2>&1
echo "wrote $OUT (exit=$?)"
