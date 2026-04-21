#!/bin/bash
# Round 9 subagent runner — includes `gpa trace` in the with_gpa prompt.
#
# Usage: run_subagent.sh <scenario> <mode> <model> <frame_id>
set -u

SCENARIO=$1
MODE=$2
MODEL=$3
FRAME_ID=$4

# Snapshot mapping for the 21 scenarios in R9.
case "$SCENARIO" in
  r4_3d_map_black_screen)                         SNAP="" ;;
  r19_depthtexture_share_source_after_renderta)   SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__c2c568587929" ;;
  r13_cubecamera_render_target_displaying_rand)   SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__c2c568587929" ;;
  r18_webglrenderer_reversed_depth_not_working)   SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__c2c568587929" ;;
  r16_lightprobegenerator_does_not_work_with_e)   SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__c2c568587929" ;;
  r7_webglbackend_copytexturetotexture_doesn_)    SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__c2c568587929" ;;
  r9_transparent_objects_brighten_when_using_)    SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__c2c568587929" ;;
  r17_viewport_rendering_with_postprocessing_r)   SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__c2c568587929" ;;
  # Source-logical scenarios
  r21_fix_vertical_and_horizontal_artifacts_on)   SNAP="/data3/opengpa-snapshots/github_com__mapbox__mapbox-gl-js__97fc828fc04e" ;;
  r18_model_disappears_when_rotating_or_zoomin)   SNAP="/data3/opengpa-snapshots/github_com__mapbox__mapbox-gl-js__97fc828fc04e" ;;
  r4_motion_blur_and_instancedmesh)               SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__c2c568587929" ;;
  r14_cannot_override_vertexnode_of_instanced_)   SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__c2c568587929" ;;
  r17_replacing_an_attribute_of_a_geometry_ins)   SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__c2c568587929" ;;
  r20_object_with_meshphysicalmaterial_contain)   SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__c2c568587929" ;;
  r28_objloader_loader_does_not_return_valid_g)   SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__c2c568587929" ;;
  r35_strange_bug_with_3_sprites_where_one_of_)   SNAP="/data3/opengpa-snapshots/github_com__godotengine__godot__5950fca36cb3" ;;
  # Carryover
  r10_feedback_loop_error_with_transmission_an)   SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__c2c568587929" ;;
  r22_point_sprite_rendering_issues_with_three)   SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__1f2fea769315" ;;
  r25_filters_with_backbuffers_seem_not_to_wor)   SNAP="/data3/opengpa-snapshots/pixijs" ;;
  r27_bug_black_squares_appear_when_rendering_)   SNAP="/data3/opengpa-snapshots/github_com__mrdoob__three__c2c568587929" ;;
  *) echo "unknown scenario $SCENARIO"; exit 1 ;;
esac

SCEN_DIR="/home/jingyulee/gh/gla/tests/eval/$SCENARIO"
REPORT=$(sed -n '/^## User Report$/,/^## /p' "$SCEN_DIR/scenario.md" | head -n -1)
if [ -z "$REPORT" ]; then
    REPORT=$(awk '/^## Ground Truth/{exit} 1' "$SCEN_DIR/scenario.md")
fi

OUT=/tmp/eval_round9/${SCENARIO}_${MODE}_${MODEL}.jsonl

export PATH=/home/jingyulee/gh/gla/bin:$PATH
eval "$(gpa env)"

TMPPROMPT=/tmp/eval_round9/${SCENARIO}_${MODE}_${MODEL}.prompt
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
- OpenGPA live capture is available. A reproduction has been captured as frame #$FRAME_ID.
  The \`gpa\` CLI is on PATH and the live session env is already set (GPA_TOKEN=$GPA_TOKEN, GPA_PORT=$GPA_PORT).

  Preferred workflow:
  1. Start with \`gpa report --frame $FRAME_ID --json\` — one call covers
     feedback loops, NaN uniforms, missing clears, empty capture.
     If the report says "GPA found no state-level issues", STOP querying GPA's
     state checks — the bug is outside GPA's capture layer; focus on
     source/shader reasoning.
  2. If report is clean but the bug is still visible, OR a flagged warning
     is the symptom and you need the upstream value: try
       gpa trace uniform <name> --frame $FRAME_ID --dc <dc> --json
       gpa trace value <literal> --frame $FRAME_ID --json
     These reverse-lookup app-level fields (globals, static vars, stack
     locals) that equal a captured value — narrows the search radius from
     the whole codebase to a handful of candidates.
  3. Only then drill into \`gpa check <name>\` or raw \`gpa dump\`:
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
  sonnet) MODELNAME="claude-sonnet-4-6" ;;
  opus) MODELNAME="claude-opus-4-7" ;;
esac

ADD_DIRS="--add-dir $SCEN_DIR"
if [ -n "$SNAP" ]; then
  ADD_DIRS="$ADD_DIRS --add-dir $SNAP"
fi

cd /tmp/eval_round9
timeout 900 claude -p \
  --model "$MODELNAME" \
  $ADD_DIRS \
  --allowedTools $ALLOW \
  --dangerously-skip-permissions \
  --output-format stream-json \
  --verbose \
  --max-turns ${MAX_TURNS:-40} \
  --no-session-persistence \
  "$(cat $TMPPROMPT)" > "$OUT" 2>&1
echo "wrote $OUT (exit=$?)"
