#!/bin/bash
# Starts Xvfb, OpenGPA engine, and captures frames from eval scenarios
set -e

DISPLAY_NUM=${GLA_DISPLAY:-99}
PORT=${GLA_PORT:-18080}
TOKEN=${GLA_TOKEN:-$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")}
SOCKET_PATH="/tmp/gla_eval.sock"
SHM_NAME="/gla_eval"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Start Xvfb if not running
if ! pgrep -f "Xvfb :${DISPLAY_NUM}" > /dev/null; then
    echo "Starting Xvfb on :${DISPLAY_NUM}..."
    Xvfb :${DISPLAY_NUM} -screen 0 800x600x24 &
    sleep 1
fi
export DISPLAY=:${DISPLAY_NUM}

# Start OpenGPA engine + API
echo "Starting OpenGPA engine..."
PYTHONPATH="${REPO_ROOT}/src/python:${REPO_ROOT}/bazel-bin/src/bindings" \
    python3 -m gla.launcher \
    --socket "${SOCKET_PATH}" \
    --shm "${SHM_NAME}" \
    --port "${PORT}" \
    --token "${TOKEN}" &
GLA_PID=$!
sleep 2

echo ""
echo "========================================="
echo "OpenGPA Eval Server Running"
echo "========================================="
echo "API:    http://127.0.0.1:${PORT}"
echo "Token:  ${TOKEN}"
echo "Socket: ${SOCKET_PATH}"
echo "SHM:    ${SHM_NAME}"
echo ""
echo "To capture an eval scenario:"
echo "  ./scripts/capture-scenario.sh e1_state_leak"
echo ""
echo "MCP server config written to .mcp.json"
echo "========================================="

# Write .mcp.json for Claude Code
# The MCP server uses stdio, so we point to the Python MCP server
cat > "${REPO_ROOT}/.mcp.json" << MCPEOF
{
  "mcpServers": {
    "gla": {
      "command": "python3",
      "args": ["-m", "gla.mcp.server"],
      "env": {
        "PYTHONPATH": "${REPO_ROOT}/src/python:${REPO_ROOT}/bazel-bin/src/bindings",
        "GLA_BASE_URL": "http://127.0.0.1:${PORT}",
        "GLA_TOKEN": "${TOKEN}"
      }
    }
  }
}
MCPEOF

# Wait for OpenGPA engine
wait $GLA_PID
