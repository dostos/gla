#!/bin/bash
# Captures frames from an eval scenario
# Usage: ./scripts/capture-scenario.sh e1_state_leak
set -e

SCENARIO=$1
if [ -z "$SCENARIO" ]; then
    echo "Usage: $0 <scenario_name>"
    echo "Available: e1_state_leak e2_nan_propagation e3_index_buffer_obo ..."
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOCKET_PATH="${GLA_SOCKET_PATH:-/tmp/gla_eval.sock}"
SHM_NAME="${GLA_SHM_NAME:-/gla_eval}"
BINARY="${REPO_ROOT}/bazel-bin/tests/eval/${SCENARIO}"

if [ ! -f "$BINARY" ]; then
    echo "Building ${SCENARIO}..."
    bazel build "//tests/eval:${SCENARIO}"
fi

echo "Running ${SCENARIO} under OpenGPA capture..."
LD_PRELOAD="${REPO_ROOT}/bazel-bin/src/shims/gl/libgla_gl.so" \
    GLA_SOCKET_PATH="${SOCKET_PATH}" \
    GLA_SHM_NAME="${SHM_NAME}" \
    "${BINARY}"

echo "Done. Frame captured. Query via REST API or MCP tools."
