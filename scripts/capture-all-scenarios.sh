#!/bin/bash
# Capture all eval scenarios sequentially
set -e

SCENARIOS=(
    e1_state_leak
    e2_nan_propagation
    e3_index_buffer_obo
    e4_double_negation_cull
    e5_uniform_collision
    e6_depth_precision
    e7_shader_include_order
    e8_race_texture_upload
    e9_scissor_not_reset
    e10_compensating_vp
)

for s in "${SCENARIOS[@]}"; do
    echo "=== Capturing $s ==="
    ./scripts/capture-scenario.sh "$s"
    sleep 0.5
done

echo ""
echo "All scenarios captured. Frames available via OpenGPA API."
